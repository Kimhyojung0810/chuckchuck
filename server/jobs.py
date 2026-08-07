"""
오래 걸리는 작업(파싱·STT·개념추출)을 백그라운드로 돌리는 곳입니다.

파싱은 수십 초, STT 는 분 단위라 HTTP 요청 안에서 끝낼 수 없습니다.
그래서 요청은 잡만 만들어 바로 돌려주고(202), 실제 실행은 워커 스레드가 합니다.

**여기가 모듈 순서를 아는 유일한 지점입니다.** (docs/DEV_POLICY.md §4-1)
f01/f05/f06 은 서로를 부르지 않고, 이 파일이 순서를 잡습니다.

지금은 러프 버전이라 큐가 `queue.Queue` 이고 재시도·재시작 복구가 없습니다.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from pathlib import Path

from chuckchuck import (
    ChuckchuckError,
    Context,
    align_speech,
    build_flow_diff,
    build_graph,
    build_questions,
    extract_concepts,
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
    QaTriage,
    SlideDoc,
    SlideMark,
    Transcript,
)

from .store import (
    ALIGNMENT_DOC,
    CONCEPT_DOC,
    CONCEPT_GRAPH,
    FLOW_DIFF,
    QA_TRIAGE,
    QUESTION_DOC,
    SLIDE_DOC,
    TRANSCRIPT,
    store,
)

log = logging.getLogger("server.jobs")

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_SLIDEDOC = ROOT / "fixtures" / "sample_slidedoc.json"


def _mock() -> bool:
    """MOCK_EXTERNAL_APIS.

    주의: 이 플래그는 모듈이 아니라 **서버가** 지킨다.
    `parse_document()` 에는 mock 경로가 없고, F-05/F-06 은 provider/llm 을
    명시적으로 "mock" 으로 넘겨야 외부 호출을 안 한다.
    (demo/bridge.py 도 같은 방식이다.)
    """
    return settings.mock_external

_queue: queue.Queue[str] = queue.Queue()
_workers: list[threading.Thread] = []
_stop = threading.Event()

# 워커 종료 신호
_SHUTDOWN = "__shutdown__"


def enqueue(session_id: str, type_: str, params: dict | None = None) -> str:
    """잡을 만들고 큐에 넣는다. 반환값은 프론트가 폴링할 job_id."""
    job = store.create_job(session_id, type_, params)
    _queue.put(job.id)
    return job.id


# ---------------------------------------------------------------------------
# 핸들러 — job type 하나당 함수 하나
# ---------------------------------------------------------------------------

def _progress(job_id: str, phase: str, detail: str = "") -> None:
    """프론트 onProgress 와 같은 phase 이름을 쓴다 (chuckchuck_bridge.js 참고)."""
    store.update_job(job_id, phase=phase, detail=detail)


def _handle_parse(job_id: str, session_id: str, params: dict) -> dict:
    """F-01 · 업로드된 파일 → SlideDoc."""
    session = store.get_session(session_id)
    path = (session.uploads or {}).get("document") if session else None
    if not path:
        raise ChuckchuckError("업로드된 발표자료가 없습니다.")

    _progress(job_id, "parsing", "발표자료를 읽는 중")
    if _mock():
        doc = SlideDoc.from_dict(json.loads(SAMPLE_SLIDEDOC.read_text(encoding="utf-8")))
        doc.file_name = Path(path).name
    else:
        doc = parse_document(path)

    payload = doc.to_dict()
    store.put_artifact(session_id, SLIDE_DOC, payload)
    _progress(job_id, "done", f"슬라이드 {doc.total_slides}장")
    return payload


def _handle_transcribe(job_id: str, session_id: str, params: dict) -> dict:
    """F-05 · 녹음 + 슬라이드 마크 → Transcript."""
    session = store.get_session(session_id)
    path = (session.uploads or {}).get("audio") if session else None
    if not path:
        raise ChuckchuckError("업로드된 녹음이 없습니다.")

    marks = [SlideMark.from_dict(m) for m in params.get("marks", [])]

    _progress(job_id, "stt", "음성을 글로 바꾸는 중")
    provider = "mock" if _mock() else params.get("provider")
    t = transcribe(path, marks, provider=provider)

    payload = t.to_dict()
    store.put_artifact(session_id, TRANSCRIPT, payload)
    _progress(
        job_id,
        "stt_done",
        f"단어 {len(t.words)}개 · 슬라이드 구간 {len(t.by_slide)}개",
    )
    return payload


def _handle_concepts(job_id: str, session_id: str, params: dict) -> dict:
    """F-06 · SlideDoc(+Context, 선택적 Transcript) → ConceptDoc."""
    session = store.get_session(session_id)
    if session is None or SLIDE_DOC not in session.artifacts:
        raise ChuckchuckError("먼저 발표자료를 파싱해야 합니다.")

    doc = SlideDoc.from_dict(session.artifacts[SLIDE_DOC])
    ctx = Context.from_dict(session.context or {})

    raw_transcript = session.artifacts.get(TRANSCRIPT)
    t = Transcript.from_dict(raw_transcript) if raw_transcript else None

    _progress(job_id, "concepts", "발표자료 개념 추출 중")
    llm = "mock" if _mock() else params.get("llm")
    result = extract_concepts(doc, ctx, transcript=t, llm=llm)

    payload = result.to_dict()
    store.put_artifact(session_id, CONCEPT_DOC, payload)
    _progress(job_id, "concepts_done", f"개념 슬라이드 {len(result.slides)}장")
    return payload


def _need_artifact(session_id: str, kind: str, message: str) -> dict:
    """전제 artifact 를 꺼낸다. 없으면 원인이 분명한 실패로 끝낸다."""
    session = store.get_session(session_id)
    payload = (session.artifacts or {}).get(kind) if session else None
    if payload is None:
        raise ChuckchuckError(message)
    return payload


def _handle_graph(job_id: str, session_id: str, params: dict) -> dict:
    """F-07 · ConceptDoc(+선택 SlideDoc) → ConceptGraph."""
    doc = ConceptDoc.from_dict(
        _need_artifact(session_id, CONCEPT_DOC, "먼저 개념 추출이 끝나야 합니다.")
    )
    session = store.get_session(session_id)
    raw_slide_doc = session.artifacts.get(SLIDE_DOC) if session else None
    ctx = Context.from_dict((session.context if session else None) or {})

    _progress(job_id, "graph", "개념 그래프 만드는 중")
    llm = "mock" if _mock() else params.get("llm")
    graph = build_graph(
        doc,
        ctx,
        slide_doc=SlideDoc.from_dict(raw_slide_doc) if raw_slide_doc else None,
        llm=llm,
    )

    payload = graph.to_dict()
    store.put_artifact(session_id, CONCEPT_GRAPH, payload)
    # 그래프가 바뀌면 그 아래 QA 산출물은 옛 덱의 node_id 만 들고 있어 무효다.
    # 남겨 두면 다음 질문 생성이 캐시 히트로 집어 들어 영구 실패한다.
    store.drop_artifact(session_id, QA_TRIAGE, QUESTION_DOC)
    _progress(job_id, "graph_done", f"개념 {len(graph.nodes)}개 · 연결 {len(graph.edges)}개")
    return payload


def _handle_alignment(job_id: str, session_id: str, params: dict) -> dict:
    """
    F-11 · ConceptGraph + Transcript → AlignmentDoc, 이어서 파생 FlowDiff 까지.

    FlowDiff 는 LLM 없는 순수 함수라 여기서 같이 계산해 둔다 —
    F-08 이 weak_flow 근거로 쓰고, 리포트 '논리 흐름' 탭도 이걸 읽는다.
    """
    graph = ConceptGraph.from_dict(
        _need_artifact(session_id, CONCEPT_GRAPH, "먼저 개념 그래프를 만들어야 합니다.")
    )
    transcript = Transcript.from_dict(
        _need_artifact(session_id, TRANSCRIPT, "먼저 녹음을 글로 바꿔야 합니다.")
    )
    session = store.get_session(session_id)
    ctx = Context.from_dict((session.context if session else None) or {})

    _progress(job_id, "alignment", "발화와 자료를 대조하는 중")
    llm = "mock" if _mock() else params.get("llm")
    alignment = align_speech(graph, transcript, ctx, llm=llm)

    payload = alignment.to_dict()
    store.put_artifact(session_id, ALIGNMENT_DOC, payload)
    store.put_artifact(session_id, FLOW_DIFF, build_flow_diff(graph, alignment).to_dict())

    _progress(
        job_id,
        "alignment_done",
        f"정합률 {alignment.summary.coverage} · 판정 {len(alignment.items)}건",
    )
    return payload


def _triage_fits(cached: dict, graph: ConceptGraph) -> bool:
    """
    캐시된 triage 가 이 그래프에서 나온 것인지 본다.

    triage 는 트랙과 무관하지만 **그래프에는 매인다**. 자료를 다시 올려 덱이
    바뀌면 옛 node_id 만 든 triage 가 남고, build_questions 가 그걸 받으면
    "QaTriage 에 이 그래프의 개념이 없습니다" 로 죽는다.
    합성 노드(`extra:` 접두)는 그래프에 없는 것이 정상이라 대조에서 뺀다.
    """
    node_ids = {n.id for n in graph.nodes}
    marked = {
        str(m.get("node_id", ""))
        for m in (cached.get("marks") or [])
        if not str(m.get("node_id", "")).startswith("extra:")
    }
    marked.discard("")
    if not marked:
        return False
    return bool(marked & node_ids)


def _handle_questions(job_id: str, session_id: str, params: dict) -> dict:
    """
    F-08 · ConceptGraph(+선택 AlignmentDoc·FlowDiff) → QuestionDoc.

    triage 는 트랙과 무관하므로 세션에 캐시한다 — 1/5/10분을 바꿔도 재호출이 없다.
    (인메모리 저장소라 서버를 재시작하면 캐시가 날아가고 재-triage 1콜이 든다.)
    alignment 가 없어도 동작한다 — 녹음 없이 자료만 올린 경로다.
    """
    graph = ConceptGraph.from_dict(
        _need_artifact(session_id, CONCEPT_GRAPH, "먼저 개념 그래프를 만들어야 합니다.")
    )
    session = store.get_session(session_id)
    artifacts = (session.artifacts if session else None) or {}
    ctx = Context.from_dict((session.context if session else None) or {})

    raw_alignment = artifacts.get(ALIGNMENT_DOC)
    alignment = AlignmentDoc.from_dict(raw_alignment) if raw_alignment else None
    raw_flow = artifacts.get(FLOW_DIFF)
    flow = FlowDiff.from_dict(raw_flow) if raw_flow else None
    raw_transcript = artifacts.get(TRANSCRIPT)
    transcript = Transcript.from_dict(raw_transcript) if raw_transcript else None

    track = str(params.get("track") or QA_TRACK_FALLBACK)
    if track not in QA_TRACKS:
        track = QA_TRACK_FALLBACK
    llm = "mock" if _mock() else params.get("llm")

    cached = artifacts.get(QA_TRIAGE)
    if cached and not _triage_fits(cached, graph):
        # _handle_graph 가 지우고 지나가는 것이 정상 경로다. 여기 가드는 그 밖으로
        # 그래프가 교체된 세션(직접 put, 예전 버전이 남긴 캐시)을 위한 자가 복구다.
        # 이걸 안 하면 그 세션은 재시도해도 영영 QuestionError 로 죽는다.
        log.info("triage 캐시가 현재 그래프와 맞지 않아 다시 만듭니다 (session=%s)", session_id)
        store.drop_artifact(session_id, QA_TRIAGE, QUESTION_DOC)
        cached = None

    if cached:
        triage = QaTriage.from_dict(cached)
        _progress(job_id, "questions", "질문 순위 재사용 중")
    else:
        _progress(job_id, "triage", "물어볼 개념을 고르는 중")
        triage = triage_questions(
            graph, alignment, flow, ctx, transcript=transcript, llm=llm
        )
        store.put_artifact(session_id, QA_TRIAGE, triage.to_dict())

    _progress(job_id, "questions", f"{track}분 코스 예상 질문 만드는 중")
    doc = build_questions(
        graph,
        triage,
        track=track,
        alignment=alignment,
        flow=flow,
        transcript=transcript,
        context=ctx,
        llm=llm,
    )

    # 힌트 사다리를 얹는다 — 브리지·동기 라우트와 같은 응답이어야 한다.
    from chuckchuck.f08_questions import with_hint_ladders
    payload = with_hint_ladders(doc.to_dict(), doc.questions)
    store.put_artifact(session_id, QUESTION_DOC, payload)
    _progress(job_id, "questions_done", f"예상 질문 {len(doc.questions)}개")
    return payload


HANDLERS = {
    "parse": _handle_parse,
    "transcribe": _handle_transcribe,
    "concepts": _handle_concepts,
    "graph": _handle_graph,
    "alignment": _handle_alignment,
    "questions": _handle_questions,
    # 새 모듈은 여기 한 줄 추가하면 된다.
}


# ---------------------------------------------------------------------------
# 워커
# ---------------------------------------------------------------------------

def _run_one(job_id: str) -> None:
    job = store.get_job(job_id)
    if job is None:
        return

    handler = HANDLERS.get(job.type)
    if handler is None:
        store.update_job(
            job_id,
            status="failed",
            error={"error": "unknown_job_type", "message": f"모르는 작업: {job.type}"},
        )
        return

    store.update_job(job_id, status="running")
    log.info("job %s start type=%s session=%s", job_id, job.type, job.session_id)
    try:
        result = handler(job_id, job.session_id, job.params)
        store.update_job(job_id, status="succeeded", result=result)
        log.info("job %s succeeded", job_id)
    except ChuckchuckError as e:
        # 모듈이 의도적으로 낸 실패 — 원인이 분명하다
        store.update_job(
            job_id,
            status="failed",
            error={"error": type(e).__name__, "message": str(e)},
        )
        log.warning("job %s failed: %s: %s", job_id, type(e).__name__, e)
    except Exception as e:  # noqa: BLE001 — 워커 스레드가 죽으면 안 된다
        store.update_job(
            job_id,
            status="failed",
            error={"error": type(e).__name__, "message": str(e)},
        )
        log.exception("job %s crashed", job_id)


def _loop() -> None:
    while not _stop.is_set():
        try:
            job_id = _queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            if job_id == _SHUTDOWN:
                return
            _run_one(job_id)
        finally:
            _queue.task_done()


def start_worker(concurrency: int = 2) -> None:
    if _workers:
        return
    _stop.clear()
    for i in range(max(1, concurrency)):
        t = threading.Thread(target=_loop, name=f"worker-{i}", daemon=True)
        t.start()
        _workers.append(t)
    log.info("worker started (concurrency=%d)", len(_workers))


def stop_worker(timeout: float = 5.0) -> None:
    _stop.set()
    for _ in _workers:
        _queue.put(_SHUTDOWN)
    for t in _workers:
        t.join(timeout=timeout)
    _workers.clear()
    log.info("worker stopped")
