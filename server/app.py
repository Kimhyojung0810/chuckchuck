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

from chuckchuck import ChuckchuckError, Context, extract_concepts, parse_document, settings, transcribe
from chuckchuck.contracts import SlideDoc, SlideMark, Transcript

from . import __version__, jobs
from .store import SLIDE_DOC, store

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


# ---------------------------------------------------------------------------
# 정적 — SDK 와 팀원 데모. python -m demo.bridge 를 대체할 수 있게.
# ---------------------------------------------------------------------------

if SDK_DIR.is_dir():
    app.mount("/sdk", StaticFiles(directory=str(SDK_DIR)), name="sdk")

if DEMO_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(DEMO_DIR), html=True), name="demo")
