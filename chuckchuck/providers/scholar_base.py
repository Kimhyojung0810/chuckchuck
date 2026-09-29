"""
학술 검색(논문 찾기) provider 의 공통 인터페이스입니다.
F-24 문헌 모듈이 이 인터페이스로 OpenAlex 같은 검색 API 를 부릅니다.

LLM provider 와 같은 규율이다 — 벤더 raw 는 구현체 안에서만 살고, 밖으로는
`contracts.PaperRef` 만 나간다 (DEV_POLICY §4-2·§4-3).

09-30 (G-A9): 검색이 실패·지연·부분 성공했을 때 **왜** 그랬는지가 밖으로 안 나왔다 — 한 통로가 429 를 받아도 합친 결과는
성공처럼 보였고(stderr 한 줄), 호출자는 「검색 결과 없음」 과 「검색 못 함」 을 가르지 못했다. 그래서 인터페이스에 셋을 더한다.
기존 호출 모양(`search(query, *, limit)` → list)은 그대로다.

- `ScholarCallError` — PaperError 에 까닭 코드(kind)를 싣는다: rate_limited · timeout · throttled · http · network · parse.
- `SearchHits` — 그냥 list 다. 여러 통로를 합친 결과(MultiScholar)는 통로마다 사정(status)을 달고 온다.
- `deadline_scope(초)` — 호출자가 검색 묶음 전체에 시간 예산을 건다. 통로는 그 안에서만 줄 서고(요청 한도) 기다린다.
  contextvars 라 스레드로 넘길 때는 `contextvars.copy_context().run` 으로 넘긴다.
"""

from __future__ import annotations

import contextvars
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager

from ..contracts import PaperError

#: 검색 한 번의 결과 상태 (status 항목의 state). ok·empty 는 성공이고 나머지는 결과를 못 받은 까닭이다.
SEARCH_STATES = ("ok", "empty", "rate_limited", "timeout", "throttled", "http", "network", "parse", "failed", "error")


class ScholarCallError(PaperError):
    """검색 한 번이 실패한 까닭을 코드로 싣는 PaperError. `status` 는 여러 통로를 합친 호출이 통로마다 남긴 사정."""

    def __init__(self, message: str, *, kind: str = "failed", provider: str = "", status: list[dict] | None = None):
        super().__init__(message)
        self.kind = kind if kind in SEARCH_STATES else "failed"
        self.provider = provider
        self.status = [dict(s) for s in (status or [])]


class SearchHits(list):
    """provider.search/resolve 의 결과. 그냥 list 라 예전 호출자는 그대로 쓴다. status 는 통로마다의 사정."""

    def __init__(self, refs=(), status=()):
        super().__init__(refs)
        self.status = [dict(s) for s in (status or ())]


def status_of_error(provider: str, e: BaseException) -> dict:
    """예외 하나 → 통로 사정 한 줄 {provider, state, error} (state 는 SEARCH_STATES)."""
    if isinstance(e, ScholarCallError):
        return {"provider": provider, "state": e.kind, "error": str(e)[:200]}
    if isinstance(e, PaperError):
        return {"provider": provider, "state": "failed", "error": str(e)[:200]}
    return {"provider": provider, "state": "error", "error": f"{type(e).__name__}: {e}"[:200]}


def status_rows(value) -> list[dict]:
    """통로가 달고 온 사정(status)을 믿을 만한 모양으로 — dict 목록만. 다른 라이브러리 예외의 status(정수 HTTP 코드 등)는 버린다."""
    return [dict(r) for r in value if isinstance(r, dict)] if isinstance(value, (list, tuple)) else []


#: 여러 사정 가운데 대표를 고르는 순서 — 벤더가 막은 것·실패가 우리가 참은 것(throttled)·예산(not_searched)보다 앞선다.
_STATE_ORDER = ("rate_limited", "timeout", "http", "network", "parse", "failed", "error", "throttled", "not_searched")


def dominant_state(rows: list[dict]) -> str:
    """결과를 못 받은 사정들의 대표 state (없으면 "")."""
    states = {str(r.get("state", "") or "") for r in rows}
    for k in _STATE_ORDER:
        if k in states:
            return "failed" if k == "error" else k
    return ""


_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar("scholar_deadline", default=None)


def deadline() -> float | None:
    """지금 걸린 마감 시각 (time.monotonic 기준). 없으면 None."""
    return _DEADLINE.get()


def remaining(default: float | None = None) -> float | None:
    """마감까지 남은 초. 마감이 없으면 default."""
    end = _DEADLINE.get()
    return default if end is None else end - time.monotonic()


@contextmanager
def deadline_scope(seconds: float | None):
    """이 안에서 부르는 검색은 `seconds` 안에 끝나야 한다 (이미 더 이른 마감이 걸려 있으면 그것을 따른다). None 이면 마감 없음."""
    if seconds is None:
        yield
        return
    end = time.monotonic() + max(0.0, float(seconds))
    outer = _DEADLINE.get()
    token = _DEADLINE.set(end if outer is None else min(outer, end))
    try:
        yield
    finally:
        _DEADLINE.reset(token)


class ScholarProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    def search(self, query: str, *, limit: int = 5) -> list:
        """
        검색어 → `PaperRef` 목록 (kind="scholar", id 는 비어 있다 — 호출자가 문서 안에서 매긴다).

        결과는 **품질 순**이어야 한다 (관련도 + 피인용 + 최근성). 실패하면
        `contracts.PaperError`(가능하면 까닭을 실은 `ScholarCallError`)를 던진다 — 빈 목록으로 조용히 넘기지 않는다.
        호출자는 그 예외를 받아 자료 인용(deck)만으로 폴백한다.
        """

    def resolve(self, title: str, doi: str = "") -> list:
        """
        자료가 인용한 문헌 하나를 되찾는다 (DOI 가 있으면 정확히, 없으면 제목으로).
        기본 구현은 제목 검색 1건이다. 구현체가 DOI 조회를 지원하면 덮어쓴다.
        """
        return self.search(title, limit=1) if title else []
