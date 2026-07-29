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
    extract_concepts,
    parse_document,
    settings,
    transcribe,
)
from chuckchuck.contracts import SlideDoc, SlideMark, Transcript

from .store import CONCEPT_DOC, SLIDE_DOC, TRANSCRIPT, store

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


HANDLERS = {
    "parse": _handle_parse,
    "transcribe": _handle_transcribe,
    "concepts": _handle_concepts,
    # F-07+ 는 여기 한 줄 추가하면 된다.
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
