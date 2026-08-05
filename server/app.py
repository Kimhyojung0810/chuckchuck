"""
HTTP 창구입니다. 라우트는 전부 여기 모여 있습니다.

규격은 docs/API_SDK_TEMPLATE.md §4 를 따릅니다.
  - 성공: ours to_dict() 그대로
  - 실패: {"error": "ErrorClass", "message": "..."}

무거운 작업은 여기서 하지 않고 jobs.enqueue() 로 넘긴 뒤 202 + job_id 만 돌려줍니다.
"""

from __future__ import annotations

import json
import logging
import tempfile
import uuid
from base64 import b64decode
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.concurrency import run_in_threadpool

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from chuckchuck import (
    ChuckchuckError,
    Context,
    align_speech,
    build_flow_diff,
    build_graph,
    build_questions,
    extract_concepts,
    judge_answer,
    parse_document,
    settings,
    transcribe,
    triage_questions,
)
from chuckchuck.contracts import (
    QA_TRACK_FALLBACK,
    QA_TRACKS,
    AlignmentDoc,
    ConceptDoc,
    ConceptGraph,
    FlowDiff,
    Question,
    QuestionDoc,
    SlideDoc,
    SlideMark,
    Transcript,
)

from . import __version__, jobs
from .store import (
    ALIGNMENT_DOC,
    CONCEPT_DOC,
    CONCEPT_GRAPH,
    QUESTION_DOC,
    SLIDE_DOC,
    TRANSCRIPT,
    store,
)

ROOT = Path(__file__).resolve().parent.parent
SDK_DIR = ROOT / "chuckchuck" / "sdk"
DEMO_DIR = ROOT / "demo" / "YEHS_demo"
UPLOAD_DIR = ROOT / "var" / "uploads"

MAX_UPLOAD_BYTES = 30 * 1024 * 1024        # 제품 스펙 30MB
DOCUMENT_EXT = {".pdf", ".pptx"}
AUDIO_EXT = {".webm", ".m4a", ".wav", ".mp3", ".ogg"}

log = logging.getLogger("server.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    jobs.start_worker(concurrency=2)
    log.info("mock_external=%s", settings.mock_external)
    try:
        yield
    finally:
        jobs.stop_worker()


app = FastAPI(title="척척발표 API (rough)", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 러프 버전. 배포 전에 좁힐 것
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 에러 → HTTP.  모듈 예외를 그대로 계약 형식으로 내보낸다.
# ---------------------------------------------------------------------------

@app.exception_handler(ChuckchuckError)
async def _chuckchuck_error(request: Request, exc: ChuckchuckError):
    # 로그가 없으면 접근 로그에 '422' 한 줄만 남아, 무엇이 왜 틀어졌는지
    # 사용자 화면에 뜬 문구로 역추적해야 한다. 도메인 실패는 반드시 기록한다.
    log.warning("%s %s -> %s: %s", request.method, request.url.path, type(exc).__name__, exc)
    return JSONResponse(
        status_code=422,
        content={"error": type(exc).__name__, "message": str(exc)},
    )


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        return JSONResponse(status_code=exc.status_code, content=detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "http_error", "message": str(detail)},
    )


def _need_session(session_id: str):
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(404, {"error": "not_found", "message": "세션이 없습니다."})
    return session


async def _save_upload(upload: UploadFile, allowed_ext: set[str]) -> str:
    """업로드를 청크로 받아 디스크에 흘려보낸다. 통째로 메모리에 올리지 않는다."""
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in allowed_ext:
        raise HTTPException(
            400,
            {
                "error": "unsupported_type",
                "message": f"{', '.join(sorted(allowed_ext))} 만 올릴 수 있어요.",
            },
        )

    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    total = 0
    try:
        with dest.open("wb") as f:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        413,
                        {
                            "error": "too_large",
                            "message": f"최대 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB까지 올릴 수 있어요.",
                        },
                    )
                f.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return str(dest)


# ---------------------------------------------------------------------------
# 라우트
# ---------------------------------------------------------------------------

@app.get("/api/v1/health")
def health():
    return {"ok": True, "mock": settings.mock_external, "version": __version__}


@app.get("/api/v1/sessions")
def list_sessions():
    return {"sessions": [s.summary() for s in store.list_sessions()]}


@app.post("/api/v1/sessions", status_code=201)
async def create_session(payload: dict | None = None):
    payload = payload or {}
    s = store.create_session(
        title=payload.get("title", ""),
        context=payload.get("context") or {},
    )
    return s.to_dict()


@app.get("/api/v1/sessions/{session_id}")
def get_session(session_id: str):
    """이어하기용. artifact 전부 내려준다 (sessionStorage 대체)."""
    return _need_session(session_id).to_dict()


@app.patch("/api/v1/sessions/{session_id}")
async def patch_session(session_id: str, payload: dict):
    """F-02 발표 정보 폼 저장."""
    _need_session(session_id)
    fields = {}
    if "title" in payload:
        fields["title"] = payload["title"]
    if "context" in payload:
        fields["context"] = payload["context"] or {}
    s = store.update_session(session_id, **fields)
    return s.to_dict()


@app.post("/api/v1/sessions/{session_id}/document", status_code=202)
async def upload_document(session_id: str, document: UploadFile = File(...)):
    """F-01 · 발표자료 업로드 → 파싱 잡."""
    session = _need_session(session_id)
    path = await _save_upload(document, DOCUMENT_EXT)
    store.put_upload(session_id, "document", path)
    if not session.title:
        store.update_session(session_id, title=document.filename or "")
    return {"job_id": jobs.enqueue(session_id, "parse")}


@app.post("/api/v1/sessions/{session_id}/rehearsal", status_code=202)
async def upload_rehearsal(
    session_id: str,
    audio: UploadFile = File(...),
    marks: str = Form("[]"),
):
    """F-03/04 결과(녹음 + 슬라이드 마크) 업로드 → F-05 STT 잡."""
    _need_session(session_id)
    try:
        mark_list = json.loads(marks or "[]")
    except json.JSONDecodeError:
        raise HTTPException(
            400, {"error": "bad_marks", "message": "marks 가 JSON 배열이 아닙니다."}
        )

    path = await _save_upload(audio, AUDIO_EXT)
    store.put_upload(session_id, "audio", path)
    return {"job_id": jobs.enqueue(session_id, "transcribe", {"marks": mark_list})}


@app.post("/api/v1/sessions/{session_id}/concepts", status_code=202)
async def start_concepts(session_id: str, payload: dict | None = None):
    """F-06 · 개념 추출 잡. SlideDoc 이 먼저 있어야 한다."""
    session = _need_session(session_id)
    if SLIDE_DOC not in session.artifacts:
        raise HTTPException(
            409,
            {"error": "no_slide_doc", "message": "발표자료 파싱이 먼저 끝나야 해요."},
        )
    return {"job_id": jobs.enqueue(session_id, "concepts", {"llm": (payload or {}).get("llm")})}


def _need_artifact(session, kind: str, code: str, message: str) -> dict:
    """전제 artifact 가 없으면 409. 프론트가 이 message 를 진행 상황 줄에 그대로 띄운다."""
    payload = (session.artifacts or {}).get(kind)
    if payload is None:
        raise HTTPException(409, {"error": code, "message": message})
    return payload


@app.post("/api/v1/sessions/{session_id}/graph", status_code=202)
async def start_graph(session_id: str, payload: dict | None = None):
    """F-07 · 개념 그래프 잡. ConceptDoc 이 먼저 있어야 한다."""
    session = _need_session(session_id)
    _need_artifact(session, CONCEPT_DOC, "no_concept_doc", "개념 추출이 먼저 끝나야 해요.")
    return {"job_id": jobs.enqueue(session_id, "graph", {"llm": (payload or {}).get("llm")})}


@app.post("/api/v1/sessions/{session_id}/alignment", status_code=202)
async def start_alignment(session_id: str, payload: dict | None = None):
    """
    F-11 · 발화-자료 정합 판정 잡 (파생 FlowDiff 포함).

    녹음이 없으면 409 로 끝난다. 프론트는 이 호출을 건너뛸 수 있게 감싸 두었고
    실패 message 를 진행 상황 줄에 그대로 보여 주므로, 안내문처럼 읽혀야 한다.
    """
    session = _need_session(session_id)
    _need_artifact(session, CONCEPT_GRAPH, "no_concept_graph", "개념 그래프가 먼저 필요해요.")
    _need_artifact(
        session, TRANSCRIPT, "no_transcript", "녹음이 없어 정합 판정은 건너뛰어요."
    )
    return {"job_id": jobs.enqueue(session_id, "alignment", {"llm": (payload or {}).get("llm")})}


@app.post("/api/v1/sessions/{session_id}/questions", status_code=202)
async def start_questions(session_id: str, payload: dict | None = None):
    """
    F-08 · 예상 질문 잡. ConceptGraph 만 있으면 되고 정합 판정은 선택이다.

    프론트는 시간 트랙을 `mode` 로 보내 왔다. 계약 이름은 `track` 이지만
    구버전 캐시가 남은 브라우저를 위해 둘 다 받는다.
    """
    session = _need_session(session_id)
    _need_artifact(session, CONCEPT_GRAPH, "no_concept_graph", "개념 그래프가 먼저 필요해요.")

    body = payload or {}
    track = str(body.get("track") or body.get("mode") or QA_TRACK_FALLBACK)
    if track not in QA_TRACKS:
        track = QA_TRACK_FALLBACK
    return {
        "job_id": jobs.enqueue(
            session_id, "questions", {"track": track, "llm": body.get("llm")}
        )
    }


def _resolve_question(session, question_id: str, fallback: dict | None) -> Question:
    """
    판정할 질문을 찾는다. 세션의 QuestionDoc 이 정본이고, 없으면 요청 바디를 믿는다.

    저장소가 인메모리라 서버를 재시작하면 세션이 통째로 날아간다. 반면 프론트는
    질문 세트를 브라우저에 영속시켜 두므로, 그 상태로 답을 보내면 모든 질문이
    '판정 실패' 가 된다. 바디 폴백이 그 경로를 살린다 — 판정 자체는 무상태다.
    """
    if session is not None:
        raw_doc = (session.artifacts or {}).get(QUESTION_DOC)
        if raw_doc:
            found = QuestionDoc.from_dict(raw_doc).question(question_id)
            if found is not None:
                return found

    if fallback:
        question = Question.from_dict(fallback)
        if question.question.strip():
            return question

    raise HTTPException(
        404,
        {
            "error": "question_not_found",
            "message": "그 질문을 찾을 수 없어요. 질문을 다시 만들어 주세요.",
        },
    )


@app.post("/api/v1/sessions/{session_id}/qa/judge")
async def judge_qa_answer(session_id: str, payload: dict):
    """
    F-09 · 답변 판정. **잡이 아니라 동기 라우트다** — 프론트가 응답 바디를 바로 읽는다.

    세션이 살아 있으면 그래프·정합 판정을 근거로 함께 넘긴다.
    """
    question = _resolve_question(
        store.get_session(session_id),
        str(payload.get("question_id", "") or ""),
        payload.get("question"),
    )

    session = store.get_session(session_id)
    artifacts = (session.artifacts if session else None) or {}
    raw_graph = artifacts.get(CONCEPT_GRAPH)
    raw_alignment = artifacts.get(ALIGNMENT_DOC)
    raw_transcript = artifacts.get(TRANSCRIPT)

    llm = "mock" if settings.mock_external else payload.get("llm")
    judgement = await run_in_threadpool(
        lambda: judge_answer(
            question,
            str(payload.get("answer", "") or ""),
            graph=ConceptGraph.from_dict(raw_graph) if raw_graph else None,
            alignment=AlignmentDoc.from_dict(raw_alignment) if raw_alignment else None,
            transcript=Transcript.from_dict(raw_transcript) if raw_transcript else None,
            history=payload.get("history") or [],
            context=Context.from_dict((session.context if session else None) or {}),
            # 「모르겠어요」 버튼. 타이핑으로 포기해도 f09 가 알아서 같은 길로 보낸다
            give_up=bool(payload.get("give_up")),
            # 이 질문에 앞서 낸 답변들. 판정은 누적 전체를 본다 (f09._answer_block).
            prior_answers=[
                str(a) for a in (payload.get("prior_answers") or []) if str(a).strip()
            ],
            llm=llm,
        )
    )
    return judgement.to_dict()


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str):
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(404, {"error": "not_found", "message": "작업이 없습니다."})
    return job.to_dict()


# ---------------------------------------------------------------------------
# 플랫 호환 — demo/bridge.py 와 같은 경로. 프론트 chuckchuck_bridge.js 가
# 세션 없이 바로 부르는 API 를 이 서버 하나로 처리한다 (동작 계약 동일).
# ---------------------------------------------------------------------------

FIXTURE_SLIDEDOC = ROOT / "fixtures" / "sample_slidedoc.json"


def _fixture_slidedoc() -> SlideDoc:
    return SlideDoc.from_dict(json.loads(FIXTURE_SLIDEDOC.read_text(encoding="utf-8")))


@app.get("/api/health")
def flat_health():
    return {"ok": True, "mock": settings.mock_external}


@app.post("/api/v1/parse")
async def flat_parse(request: Request):
    """F-01 · 파일(멀티파트) 또는 {"fixture": true} → SlideDoc."""
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        body = await request.json()
        if settings.mock_external:
            return _fixture_slidedoc().to_dict()
        if body.get("fixture"):
            raise HTTPException(400, {
                "error": "fixture_disabled",
                "message": "MOCK_EXTERNAL_APIS=false 입니다. PDF/PPTX 파일을 업로드하세요.",
            })
        raise HTTPException(400, {"error": "bad_request", "message": "document 파일이 필요합니다."})

    form = await request.form()
    upload = form.get("document")
    if upload is None or isinstance(upload, str):
        raise HTTPException(400, {"error": "bad_request", "message": "document 필드가 필요합니다."})
    data = await upload.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, {"error": "too_large", "message": "최대 30MB까지 올릴 수 있어요."})
    if settings.mock_external:
        doc = _fixture_slidedoc()
        doc.file_name = upload.filename or "upload.pdf"
        return doc.to_dict()
    suffix = Path(upload.filename or "upload.pdf").suffix or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        log.info("flat parse start file=%r bytes=%d", upload.filename, len(data))
        doc = await run_in_threadpool(parse_document, tmp_path)
        # parse_document 는 임시파일 이름을 넣는다. 화면에는 올린 파일 이름을 보여준다.
        doc.file_name = upload.filename or doc.file_name
        log.info("flat parse done slides=%d", doc.total_slides)
        return doc.to_dict()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.post("/api/v1/transcribe")
async def flat_transcribe(payload: dict):
    """F-05 · {marks, audio_base64, ext} → Transcript."""
    marks = [SlideMark.from_dict(m) for m in payload.get("marks", [])]
    provider = "mock" if settings.mock_external else payload.get("provider")
    audio_b64 = payload.get("audio_base64")
    if not audio_b64:
        raise HTTPException(400, {"error": "bad_request", "message": "audio_base64 가 필요합니다."})
    with tempfile.NamedTemporaryFile(suffix=payload.get("ext", ".webm"), delete=False) as tmp:
        tmp.write(b64decode(audio_b64))
        tmp_path = tmp.name
    try:
        t = await run_in_threadpool(lambda: transcribe(tmp_path, marks, provider=provider))
        return t.to_dict()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@app.post("/api/v1/concepts")
async def flat_concepts(payload: dict):
    """F-06 · {slide_doc, context, transcript?} → ConceptDoc."""
    if not payload.get("slide_doc"):
        raise HTTPException(400, {"error": "bad_request", "message": "slide_doc 이 필요합니다."})
    doc = SlideDoc.from_dict(payload["slide_doc"])
    ctx = Context.from_dict(payload.get("context") or {})
    transcript = Transcript.from_dict(payload["transcript"]) if payload.get("transcript") else None
    llm = "mock" if settings.mock_external else payload.get("llm")
    result = await run_in_threadpool(
        lambda: extract_concepts(doc, ctx, transcript=transcript, llm=llm)
    )
    return result.to_dict()


@app.post("/api/v1/graph")
async def flat_graph(payload: dict):
    """F-07 · {concept_doc, slide_doc?, context} → ConceptGraph."""
    if not payload.get("concept_doc"):
        raise HTTPException(400, {"error": "bad_request", "message": "concept_doc 이 필요합니다."})
    doc = ConceptDoc.from_dict(payload["concept_doc"])
    ctx = Context.from_dict(payload.get("context") or {})
    slide_doc = SlideDoc.from_dict(payload["slide_doc"]) if payload.get("slide_doc") else None
    llm = "mock" if settings.mock_external else payload.get("llm")
    result = await run_in_threadpool(
        lambda: build_graph(doc, ctx, slide_doc=slide_doc, llm=llm)
    )
    return result.to_dict()


@app.post("/api/v1/alignment")
async def flat_alignment(payload: dict):
    """F-11 · {graph, transcript, context} → AlignmentDoc."""
    if not payload.get("graph") or not payload.get("transcript"):
        raise HTTPException(
            400, {"error": "bad_request", "message": "graph 와 transcript 가 필요합니다."}
        )
    graph = ConceptGraph.from_dict(payload["graph"])
    transcript = Transcript.from_dict(payload["transcript"])
    ctx = Context.from_dict(payload.get("context") or {})
    llm = "mock" if settings.mock_external else payload.get("llm")
    result = await run_in_threadpool(
        lambda: align_speech(graph, transcript, ctx, llm=llm)
    )
    return result.to_dict()


@app.post("/api/v1/questions")
async def flat_questions(payload: dict):
    """F-08 · {graph, alignment?, flow?, transcript?, context, track} → QuestionDoc.

    alignment 은 선택이다. 세션 라우트와 같은 규칙 — 개념 그래프만 있으면 만든다.
    녹음 없이 자료만 올린 경로에는 정합 판정 자체가 없기 때문이다
    (triage_questions 계약: "그래프만으로도 동작한다").
    """
    if not payload.get("graph"):
        raise HTTPException(
            400, {"error": "bad_request", "message": "graph 가 필요합니다."}
        )
    graph = ConceptGraph.from_dict(payload["graph"])
    alignment = (
        AlignmentDoc.from_dict(payload["alignment"]) if payload.get("alignment") else None
    )
    flow = FlowDiff.from_dict(payload["flow"]) if payload.get("flow") else None
    transcript = Transcript.from_dict(payload["transcript"]) if payload.get("transcript") else None
    ctx = Context.from_dict(payload.get("context") or {})

    track = str(payload.get("track") or QA_TRACK_FALLBACK)
    if track not in QA_TRACKS:
        track = QA_TRACK_FALLBACK
    llm = "mock" if settings.mock_external else payload.get("llm")

    def run() -> QuestionDoc:
        triage = triage_questions(graph, alignment, flow, ctx, transcript=transcript, llm=llm)
        return build_questions(
            graph,
            triage,
            track=track,
            alignment=alignment,
            flow=flow,
            transcript=transcript,
            context=ctx,
            llm=llm,
        )

    doc = await run_in_threadpool(run)
    return doc.to_dict()


@app.post("/api/v1/flow")
async def flat_flow(payload: dict):
    """F-11 파생 · {graph, alignment} → FlowDiff. LLM 없는 순수 계산."""
    if not payload.get("graph") or not payload.get("alignment"):
        raise HTTPException(
            400, {"error": "bad_request", "message": "graph 와 alignment 가 필요합니다."}
        )
    graph = ConceptGraph.from_dict(payload["graph"])
    alignment = AlignmentDoc.from_dict(payload["alignment"])
    return build_flow_diff(graph, alignment).to_dict()


# ---------------------------------------------------------------------------
# 정적 — SDK 와 팀원 데모. python -m demo.bridge 를 대체할 수 있게.
# ---------------------------------------------------------------------------

if SDK_DIR.is_dir():
    app.mount("/sdk", StaticFiles(directory=str(SDK_DIR)), name="sdk")

if DEMO_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(DEMO_DIR), html=True), name="demo")
