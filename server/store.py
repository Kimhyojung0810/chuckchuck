"""
인메모리 저장소입니다. **나중에 DB로 갈아끼울 자리**를 표시해 둔 것뿐입니다.

지금은 dict 하나라 서버를 끄면 다 사라집니다.
DB를 붙이기로 하면 이 파일의 함수 시그니처만 유지한 채 안쪽을 바꾸면 됩니다.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# artifact kind — 모듈 산출물 이름. 새 모듈은 여기 한 줄 추가.
SLIDE_DOC = "slide_doc"          # F-01
TRANSCRIPT = "transcript"        # F-05
CONCEPT_DOC = "concept_doc"      # F-06
CONCEPT_GRAPH = "concept_graph"  # F-07
ALIGNMENT_DOC = "alignment_doc"  # F-11
FLOW_DIFF = "flow_diff"          # F-11 파생
QA_TRIAGE = "qa_triage"          # F-08 1차 — 트랙과 무관해 세션에 캐시한다
QUESTION_DOC = "question_doc"    # F-08 2차 — 트랙별 질문 세트


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Session:
    """발표 연습 한 건. 화면의 '내 발표' 한 행."""

    id: str = field(default_factory=new_id)
    title: str = ""
    context: dict = field(default_factory=dict)                # Context.to_dict()
    artifacts: dict[str, dict] = field(default_factory=dict)   # kind -> ours to_dict()
    uploads: dict[str, str] = field(default_factory=dict)      # kind -> 로컬 파일 경로
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "context": self.context,
            "artifacts": self.artifacts,
            "created_at": self.created_at,
        }

    def summary(self) -> dict:
        """목록 화면용. 무거운 artifact 본문은 뺀다."""
        slide_doc = self.artifacts.get(SLIDE_DOC) or {}
        return {
            "id": self.id,
            "title": self.title or slide_doc.get("file_name", ""),
            "total_slides": slide_doc.get("total_slides"),
            "has": sorted(self.artifacts),
            "created_at": self.created_at,
        }


@dataclass
class Job:
    """오래 걸리는 작업 한 건. 프론트는 이걸 폴링한다."""

    id: str = field(default_factory=new_id)
    session_id: str = ""
    type: str = ""                       # parse | transcribe | concepts | graph | alignment | questions
    status: str = "queued"               # queued | running | succeeded | failed
    phase: str = ""                      # 프론트 onProgress 의 phase 와 같은 이름
    detail: str = ""
    params: dict = field(default_factory=dict)
    result: dict | None = None           # 성공 시 ours to_dict()
    error: dict | None = None            # 실패 시 {"error": ..., "message": ...}
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "job_id": self.id,
            "session_id": self.session_id,
            "type": self.type,
            "status": self.status,
            "progress": {"phase": self.phase, "detail": self.detail},
            "result": self.result,
            "error": self.error,
        }


class Store:
    """세션·잡을 담아 두는 곳. 워커 스레드와 같이 쓰므로 락을 건다."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, Session] = {}
        self._jobs: dict[str, Job] = {}

    # ----- 세션 -------------------------------------------------------

    def create_session(self, title: str = "", context: dict | None = None) -> Session:
        with self._lock:
            s = Session(title=title, context=context or {})
            self._sessions[s.id] = s
            return s

    def get_session(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def list_sessions(self) -> list[Session]:
        with self._lock:
            return sorted(
                self._sessions.values(), key=lambda s: s.created_at, reverse=True
            )

    def update_session(self, session_id: str, **fields: Any) -> Session | None:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                return None
            for k, v in fields.items():
                setattr(s, k, v)
            return s

    def put_artifact(self, session_id: str, kind: str, payload: dict) -> None:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is not None:
                s.artifacts[kind] = payload

    def drop_artifact(self, session_id: str, *kinds: str) -> None:
        """
        파생 산출물을 버린다. 상류가 바뀌면 하류는 무효이기 때문이다.

        예: 자료를 다시 올려 ConceptGraph 가 교체되면 그 그래프로 만든
        QA_TRIAGE·QUESTION_DOC 은 옛 덱의 node_id 만 들고 있어 쓸 수 없다.
        지우지 않으면 캐시 히트로 집어 들어 질문 생성이 영구 실패한다.
        """
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None:
                return
            for kind in kinds:
                s.artifacts.pop(kind, None)

    def put_upload(self, session_id: str, kind: str, path: str) -> None:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is not None:
                s.uploads[kind] = path

    # ----- 잡 ---------------------------------------------------------

    def create_job(self, session_id: str, type_: str, params: dict | None = None) -> Job:
        with self._lock:
            j = Job(session_id=session_id, type=type_, params=params or {})
            self._jobs[j.id] = j
            return j

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update_job(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            j = self._jobs.get(job_id)
            if j is None:
                return
            for k, v in fields.items():
                setattr(j, k, v)


store = Store()
