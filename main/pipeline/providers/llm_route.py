"""
일(stage)마다 다른 모델에 맡긴다 — Q&A 질문은 Solar 혼자 하지 않는다 (2026-10-16 사용자 「나눠 맡기기」).

    QA_TRIAGE_MODEL   1차 심사(어느 개념을 얼마나 세게·함정·각도)    비우면 REASONING_BACKEND(+REASONING_FALLBACK)
    QA_PHRASE_MODEL   질문 문장·모범답·힌트 (+ 문헌 인용 고쳐 쓰기)   기본 DEFAULT_STAGE_MODELS["phrase"]
    QA_CHECK_MODEL    논문 주장 대조(temperature 0, 코드가 원문 대조)   비우면 REASONING_BACKEND
    QA_<STAGE>_DEADLINE_SEC  주 모델을 기다리는 상한(초). 넘기면 예비(서비스 기본 체인)로 한 번 넘긴다.

값은 `solar` · `ax` · `exaone` · `midm` 중 하나. `default`·빈 값은 서비스 기본 체인(REASONING_BACKEND+REASONING_FALLBACK)과 같다.

규율:
- **예비는 언제나 서비스 기본 체인**(지금 solar → ax)이다. 주 모델이 마감을 넘기거나 · 오류를 내거나 · 빈 답이거나 ·
  json_mode 인데 JSON 이 아니면 예비가 **한 번** 받는다. 누가 답했는지는 `name` 에 남는다 (FallbackLLM 과 같은 정직성 규칙).
- 주 모델 키가 없으면(팀원 노트북 등) 조용히 기본 체인으로 간다 — 로그에 한 줄 남긴다.
- mock 모드(REASONING_BACKEND=mock · MOCK_EXTERNAL_APIS)에서는 나누지 않는다 — 테스트·mock 데모가 실 엔드포인트로 새지 않게.
- 호출부가 llm 을 **명시**하면(벤치 --llm · 테스트 · 개발 경로) 이 라우팅을 타지 않는다 (f08 `_stage_engine`).
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from .._json_text import extract_json_object
from ..contracts import ConceptError
from .llm_base import LLMProvider
from .llm_impl import REGISTRY, get_llm

#: 일 → 환경변수. 이름이 곧 운영 문서다 (MODEL_LEDGER.md · .env.example).
STAGE_ENV = {"triage": "QA_TRIAGE_MODEL", "phrase": "QA_PHRASE_MODEL", "check": "QA_CHECK_MODEL"}

#: 환경변수가 없을 때의 기본값. ""(빈 값) = 서비스 기본 체인.
#: 10-16 벤치(etc/bench/results/ledgers/MODEL_LEDGER.md §2, 고정 번들 5개 × 2회 × 2실행, 판정·심사관 solar 고정):
#: 질문 문장을 EXAONE 에 맡기면(1차 심사는 Solar) 특이도 1.27→1.54 · 근거 인용률 0.69→0.69 · 환각 0 · 나란히 비교 8승 2패 10무.
#: 대가는 문장 호출 p50 7.3→11.2초와 가끔(5/43) 되풀이 고리 — 마감(20초)에서 Solar 가 받는다. A.X 는 질이 같고 느리다.
#: 1차 심사·논문 대조는 Solar 그대로 — EXAONE 1차 심사는 인용률이 0.63 으로 내려갔다.
DEFAULT_STAGE_MODELS: dict[str, str] = {"triage": "", "phrase": "exaone", "check": ""}

#: 주 모델을 기다리는 상한(초). 질문은 분석이 끝나는 순간 미리 만들어 두지만(app.js prefetchLiveQuestions),
#: 부스 사진 경로(booth.js)는 바로 기다린다 — 그래서 마감이 있다. 넘기면 예비가 처음부터 다시 만든다.
#: phrase 20초: EXAONE 문장 호출 41회 중 20초 넘은 것 2회(되풀이 고리 제외) — 고리는 4096 토큰까지 ~40~50초를 태운다.
DEFAULT_DEADLINE_SEC: dict[str, float] = {"triage": 30.0, "phrase": 20.0, "check": 20.0}

#: 마감을 넘긴 주 모델 호출은 뒤에서 마저 끝나고 버려진다. 그 스레드가 오래 붙잡지 않게 HTTP 제한도 마감 근처로 줄인다.
_HTTP_SLACK_SEC = 5

_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="llm-route")


def _mock_mode() -> bool:
    backend = (os.environ.get("REASONING_BACKEND") or "").strip().lower()
    mock_ext = (os.environ.get("MOCK_EXTERNAL_APIS") or "").strip().lower() in ("1", "true", "yes")
    return backend == "mock" or mock_ext


def stage_model(stage: str) -> str:
    """이 일에 지정된 주 모델 이름. "" 이면 서비스 기본 체인."""
    if stage not in STAGE_ENV:
        raise ConceptError(f"모르는 일: {stage}. 가능한 값: {', '.join(STAGE_ENV)}")
    raw = os.environ.get(STAGE_ENV[stage])
    spec = (DEFAULT_STAGE_MODELS.get(stage, "") if raw is None else raw).strip().lower()
    return "" if spec in ("", "default") else spec


def stage_deadline(stage: str) -> float:
    raw = os.environ.get(f"QA_{stage.upper()}_DEADLINE_SEC")
    try:
        return float(raw) if raw else DEFAULT_DEADLINE_SEC.get(stage, 30.0)
    except ValueError:
        return DEFAULT_DEADLINE_SEC.get(stage, 30.0)


def route_identity() -> str:
    """캐시 키에 넣을 라우팅 지문 — 환경변수로 모델을 바꿔 다시 띄우면 옛 모델이 만든 질문을 돌려주지 않게."""
    if _mock_mode():
        return "mock"
    return ";".join(f"{s}={stage_model(s) or 'default'}@{stage_deadline(s):g}" for s in STAGE_ENV)


class RoutedLLM(LLMProvider):
    """주 모델에 마감을 두고, 못 받으면 예비(서비스 기본 체인)로 **한 번** 넘긴다.

    FallbackLLM 과 다른 점: (1) 마감(deadline) — 느린 모델이 사용자를 붙잡지 않는다, (2) json_mode 인데 JSON 을 못 돌려준
    것도 실패로 친다 — 예비가 서비스에서 검증된 경로이므로 같은 모델에 다시 묻기보다 넘기는 편이 낫다.
    """

    def __init__(self, primary: LLMProvider, secondary: LLMProvider, deadline_sec: float, stage: str = ""):
        self.primary, self.secondary = primary, secondary
        self.deadline_sec = float(deadline_sec)
        self.stage = stage
        self._last = primary.name
        self.answered: LLMProvider = primary
        self.fallbacks = 0
        self.last_reason = ""

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._last

    @property
    def last_usage(self) -> Any:
        return getattr(self.answered, "last_usage", None)

    def complete(self, *, system: str, user: str, temperature: float = 0.2,
                 max_tokens: int = 4096, json_mode: bool = False) -> str:
        kw = dict(system=system, user=user, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
        t0 = time.monotonic()
        fut = _POOL.submit(self.primary.complete, **kw)
        try:
            out = fut.result(timeout=self.deadline_sec)
            reason = _unusable(out, json_mode)
        except FutureTimeout:
            reason = f"마감 {self.deadline_sec:g}초"
        except Exception as e:  # noqa: BLE001 — 주 모델의 어떤 실패든 예비가 받는다 (예비의 실패는 그대로 올린다)
            reason = f"{type(e).__name__}: {str(e)[:100]}"
        if not reason:
            self._last, self.answered, self.last_reason = self.primary.name, self.primary, ""
            return out
        self.fallbacks += 1
        self.last_reason = reason
        sys.stderr.write(f"[llm-route] {self.stage or '?'} {self.primary.name} 실패({reason}, {time.monotonic() - t0:.1f}s)"
                         f" → {self.secondary.name} 로 넘겨요\n")
        out = self.secondary.complete(**kw)
        self._last, self.answered = self.secondary.name, self.secondary
        return out


def _unusable(out: str, json_mode: bool) -> str:
    """답을 못 쓸 까닭. 쓸 만하면 빈 문자열."""
    if not out or not out.strip():
        return "빈 응답"
    if json_mode:
        try:
            extract_json_object(out)
        except ValueError:
            return "JSON 아님"
    return ""


def get_stage_llm(stage: str) -> LLMProvider:
    """일에 맞는 LLM. 지정이 없거나 mock 이거나 주 모델이 기본과 같으면 서비스 기본 체인(get_llm()) 그대로."""
    base = get_llm()
    if _mock_mode():
        return base
    spec = stage_model(stage)
    if not spec:
        return base
    if spec not in REGISTRY:
        sys.stderr.write(f"[llm-route] {STAGE_ENV[stage]}={spec} 는 모르는 모델이에요 — 기본 체인으로 가요\n")
        return base
    if spec == getattr(getattr(base, "primary", base), "name", ""):
        return base
    try:
        primary = REGISTRY[spec]()
    except ConceptError as e:   # 키 없음 — 팀원 노트북 등
        sys.stderr.write(f"[llm-route] {stage} 주 모델 {spec} 을 못 만들어요({str(e)[:80]}) — 기본 체인으로 가요\n")
        return base
    deadline = stage_deadline(stage)
    if hasattr(primary, "timeout"):
        primary.timeout = min(int(getattr(primary, "timeout") or deadline), int(deadline) + _HTTP_SLACK_SEC)
    return RoutedLLM(primary, base, deadline, stage=stage)
