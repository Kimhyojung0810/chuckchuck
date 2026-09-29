"""
학술 검색 provider 구현체입니다 — 키 없이 바로 쓰는 통로 5개와, 여럿을 합치는 MultiScholar.

    from chuckchuck.providers.scholar_impl import get_scholar
    refs = get_scholar("openalex").search("smartphone notification attention cost", limit=3)
    refs = get_scholar("openalex,semanticscholar,arxiv").search("dense retrieval", limit=5)   # 합쳐서 품질순

| 통로 | 무엇이 강한가 | 키 | 초록 | 피인용 |
|---|---|---|---|---|
| openalex | 전 분야 메타데이터 · DOI 조회 · 학술지 | 없음 | 있음(역색인) | 있음 |
| semanticscholar | CS/AI · TLDR 한 줄 · 오픈액세스 PDF 링크 | 없음(있으면 한도 ↑) | TLDR/초록 | 있음 |
| arxiv | 최신 프리프린트(AI·물리·수학) | 없음 | 있음 | 없음 |
| crossref | DOI 권위 원본 · 출판사 메타데이터 | 없음 | 드묾 | 있음 |
| europepmc | 생명과학·의학(PubMed 포함) · 전문 | 없음 | 있음 | 있음 |

품질 순위는 코드가 정한다 — **검색어 낱말이 제목·초록에 실제로 있는 비율(coverage)** 을 가장
크게, 그다음 OpenAlex 관련도·피인용(log)·최근성을 섞는다. 가중치는 `_quality()` 한 곳에만 있다.

왜 coverage 인가 (2026-09-22 실측): OpenAlex 관련도만 믿으면 "attention residue task switching"
에 AlphaFold(피인용 1.5만)가 1위로 오고, "smartphone notification attention cost" 에 건강앱
리뷰(피인용 1,241)가 1위였다. 관련도 점수가 낱말 하나("switching"·"smartphone")에도 크게
붙고, 피인용을 더하면 그쪽으로 더 쏠린다. 검색어 낱말이 절반도 안 들어간 논문은 뒤로 보낸다.

환경변수:
    SCHOLAR_PROVIDER   openalex | semanticscholar | arxiv | crossref | europepmc | all | none,
                       쉼표로 여러 개 (기본 none). all = openalex,arxiv,europepmc (+semanticscholar, S2_API_KEY 가 있을 때)
    SCHOLAR_MAILTO     polite pool 용 연락 메일 (OpenAlex·Crossref — User-Agent 와 `mailto` 쿼리)
    OPENALEX_MAILTO    OpenAlex 만 쓸 polite pool 메일 (`mailto` 쿼리). 없으면 SCHOLAR_MAILTO
    OPENALEX_API_KEY   OpenAlex 키 (선택, 무료 발급) — 키 없는 하루 예산의 10배. `Authorization: Bearer` 머리로 보낸다
    S2_API_KEY         Semantic Scholar 키 (선택 — 없으면 공용 한도 100회/5분)

키·메일은 환경변수에서만 읽고 값을 찍지 않는다 — 로그는 「설정됨/없음」 만(브리지 시작 배너 `config.masked` 와 같은 규칙),
오류 문구는 `_redact` 로 값을 가린 뒤에 만든다.
    SCHOLAR_TIMEOUT_SEC  요청 시간 초과 (기본 8)
    SCHOLAR_QUEUE_WAIT_SEC  통로 요청 한도(LANES) 줄에서 기다릴 최대 초 (기본 10, 마감이 걸려 있으면 마감까지)

요청 한도 (09-30 G-A9·B-14/B-15): f24 가 개념 넷을 동시에 띄우면 통로마다 4병렬이 됐다 — arXiv 는 「3초에 한 번」 이
이용 규칙이라 줄줄이 429 를 받았고, 그 429 는 합친 결과에 묻혀 성공처럼 보였다. 이제 통로마다 동시 요청 수와 요청 사이
최소 간격(`LANES`)을 **프로세스 전체에서** 지키고, 429 를 받으면 그 통로를 다 같이 쉰다(Retry-After). 줄이 마감보다 길면
보내지 않고 throttled 로 알린다 — 벤더가 막은 것(rate_limited)과 우리가 참은 것(throttled)을 가른다.
"""

from __future__ import annotations

import contextvars
import datetime
import html
import math
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import quote, quote_plus

import requests

from ..contracts import PAPER_ABSTRACT_MAX, PaperRef
from .scholar_base import ScholarCallError, ScholarProvider, SearchHits, dominant_state, remaining, status_of_error

_WS_RE = re.compile(r"\s+")
#: OpenAlex 는 `?`·`*` 가 든 검색어에 400 을 낸다 (와일드카드로 읽는다). 따옴표·콜론도 지운다.
_QUERY_STRIP_RE = re.compile(r"[?*\"“”'’:;|()\[\]{}<>]")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
#: 어간 비교용 접두 길이 — "retrieval/retrievals", "switching/switch" 를 같은 낱말로 본다.
_STEM_LEN = 5
#: 낱말 겹침이 이 아래면 「검색어와 다른 논문」 이다. 다만 상한 수를 못 채우면 이 아래도 채운다.
COVERAGE_MIN = 0.5
#: 검색어 낱말(어간)이 **제목**에 이만큼은 있어야 한다 (검색어 낱말 수가 더 적으면 전부). 09-23 실측: 초록 겹침만 보면
#: "attention residue task switching" 에 단백질 결합 부위 논문(초록에 attention·residue·task 가 다 있다)이 3위에 올랐고,
#: "smartphone notification … concentration loss" 에 냉장 창고 IoT 알림 시스템(제목엔 notification 하나)이 올랐다.
#: 교수가 인용할 논문이라 제목이 검색어를 말해야 한다. 검색어 낱말이 1개뿐이면 문턱을 걸지 않는다.
TITLE_HIT_MIN = 2
#: 피인용 0 이고 한 통로만 찾은 논문(아무도 보증하지 않은 것)은 검색어 낱말 중 하나만 빼고 다 제목에 있어야 한다.
#: 두 통로가 같이 찾았거나(source 에 "+") 피인용이 있으면 남이 이미 검증한 논문이라 TITLE_HIT_MIN 이면 된다.
TITLE_MISS_MAX_UNVOUCHED = 1
#: coverage·관련성을 잴 때 무시할 낱말 (**어간 전에 낱말 통째로** 본다 — 「context」 를 빼도 「content」 는 남는다).
#: 09-30 G-A31: 기능어·학술 상투어(research·impact·effect·method …)가 겹침으로 세여, 주제가 다른 논문이 「검색어 낱말을
#: 나눈다」 로 통과했다. 어느 분야 논문에나 있는 말만 둔다 — model·system·data 처럼 분야에 따라 내용인 말은 두지 않는다.
_QUERY_STOP = {"the", "and", "for", "with", "from", "into", "over", "under", "using", "based",
               "study", "review", "analysis", "effect", "effects", "approach", "method", "methods",
               "studies", "reviews", "analyses", "research", "impact", "impacts", "influence", "influences", "role", "roles",
               "factor", "factors", "relationship", "relationships", "association", "associations", "evidence",
               "outcome", "outcomes", "result", "results", "finding", "findings", "methodology", "among", "between",
               "toward", "towards", "via", "within", "across", "through", "novel", "new", "recent", "latest", "paper", "papers",
               "article", "articles", "approaches", "survey",
               "surveys", "case", "cases", "perspective", "perspectives", "implication", "implications", "aspect",
               "aspects", "issue", "issues", "context", "contexts", "use", "uses", "does", "how", "what", "why", "which",
               "are", "its", "their", "this", "that", "these", "those", "than", "not", "can", "may", "was", "were"}


_UA = {"User-Agent": "chuckchuck/1.0 (F-24 papers; mailto:%s)"}


def _mailto() -> str:
    return os.environ.get("SCHOLAR_MAILTO") or os.environ.get("OPENALEX_MAILTO") or ""


def _openalex_mailto() -> str:
    """OpenAlex `mailto` 쿼리(polite pool) — OPENALEX_MAILTO, 없으면 SCHOLAR_MAILTO (09-30 까지는 OPENALEX_MAILTO 만 읽어서
    .env.example 대로 SCHOLAR_MAILTO 만 넣으면 OpenAlex 쿼리에는 안 실렸다)."""
    return (os.environ.get("OPENALEX_MAILTO") or os.environ.get("SCHOLAR_MAILTO") or "").strip()


def _openalex_api_key() -> str:
    """OpenAlex 키 — OPENALEX_API_KEY 환경변수에서만. 값은 로그·오류 문구·응답에 싣지 않는다."""
    return (os.environ.get("OPENALEX_API_KEY") or "").strip()


def _state(value: str) -> str:
    """설정 값의 상태만 — 브리지 시작 배너(`config.masked`)처럼 값의 어느 글자도 찍지 않는다."""
    return "설정됨" if value else "없음"


#: 오류 문구에서 가릴 설정 값. requests 의 연결 오류 문구는 요청 주소를 쿼리째 싣는다(「… with url: /works?…&mailto=…」) —
#: 그 문구가 stderr·통로 사정(status)·응답의 까닭 글로 나간다.
_SECRET_ENVS = ("OPENALEX_API_KEY", "OPENALEX_MAILTO", "SCHOLAR_MAILTO", "S2_API_KEY")
#: 요청에 실어 보낸 값 가운데 가릴 것 — 쿼리 mailto·api_key, 머리 Authorization·x-api-key.
_SECRET_PARAMS = ("mailto", "api_key")
_SECRET_HEADERS = ("Authorization", "x-api-key")
#: 이보다 짧은 값은 가리지 않는다 — 한두 글자를 지우면 오류 문구가 뭉개진다 (키·메일은 이보다 길다).
_SECRET_MIN = 4


def _redact(text, params: dict | None = None, headers: dict | None = None) -> str:
    """
    글에서 키·연락 메일 값을 「***」 로 가린다 — 환경변수 값과 이번 요청에 실은 값(쿼리·머리) 모두, 날값과 주소 인코딩 값
    (「%40」) 모두. 오류 문구를 만드는 곳(`_http_get`·`_checked_get`·통로)이 부른다.
    """
    out = str(text or "")
    values = {(os.environ.get(n) or "").strip() for n in _SECRET_ENVS}
    values |= {str((params or {}).get(k) or "").strip() for k in _SECRET_PARAMS}
    for h in _SECRET_HEADERS:
        v = str((headers or {}).get(h) or "").strip()
        values |= {v, v.split(" ", 1)[-1]}          # 「Bearer <키>」 는 키만 나와도 가린다
    for v in sorted((v for v in values if len(v) >= _SECRET_MIN), key=len, reverse=True):
        for form in {v, quote(v, safe=""), quote_plus(v)}:
            out = out.replace(form, "***")
    return out


#: 429(속도 제한)를 받으면 이만큼 쉬고 **한 번만** 다시 묻는다. Retry-After 가 있으면 그 값 — 단 RATE_LIMIT_WAIT_MAX 를 넘으면
#: 다시 묻지 않는다 (요청 안에서 몇 분·몇 시간을 잘 수는 없다).
RATE_LIMIT_WAIT_SEC = 1.5
RATE_LIMIT_WAIT_MAX = 4.0
#: 429 뒤 그 통로 전체가 쉬는 최대 초 — Retry-After 를 이만큼까지는 지킨다. 09-30 실측: 키 없는 OpenAlex 가 하루 한도를 다 써
#: Retry-After 19517(≈5.4시간)을 줬는데, 예전 코드는 4초 뒤 다시 묻고 다른 개념 검색도 그대로 보내 9번 모두 429 를 받았다.
LANE_COOLDOWN_MAX = 900.0
#: 요청 하나에 줄 최소 시간 (마감이 가까워도 이보다 짧게는 안 준다 — 그럴 바에는 안 보낸다).
REQUEST_MIN_SEC = 1.0

#: 통로마다 (동시 요청 수, 요청 사이 최소 간격 초). 벤더가 적어 둔 한도 아래로 — 프로세스 전체에서 나눠 쓴다.
#:   arxiv           이용 규칙 「3초에 한 번」 (export.arxiv.org API terms). 09-30 G-A9: 4병렬 → 429 연쇄.
#:   semanticscholar 키 없이 100회/5분(공용), 키가 있어도 초당 1회.
#:   openalex        초당 10회 (polite pool) — 넷까지.
#:   crossref·europepmc  공개 한도가 넉넉하지만 공용 자원이라 둘씩.
LANES: dict[str, tuple[int, float]] = {
    "openalex": (4, 0.12),
    "arxiv": (1, 3.1),
    "semanticscholar": (1, 1.1),
    "crossref": (2, 0.25),
    "europepmc": (2, 0.25),
}
_LANE_DEFAULT = (2, 0.25)


def _now() -> float:
    return time.monotonic()


def _pause(seconds: float) -> None:
    """줄 간격만큼 기다린다. time.sleep 을 안 쓴다 — 429 백오프(time.sleep)와 따로 세야 테스트가 가른다."""
    if seconds > 0:
        threading.Event().wait(seconds)


class _Lane:
    """통로 하나의 요청 줄 — 동시 요청 수(slots)와 시작 간격(interval). 스레드 안전."""

    def __init__(self, name: str, slots: int, interval: float):
        self.name = name
        self.interval = max(0.0, interval)
        self._slots = threading.BoundedSemaphore(max(1, slots))
        self._lock = threading.Lock()
        self._next = 0.0          # 다음 요청을 시작해도 되는 시각 (_now 기준)
        self._cool_until = 0.0    # 벤더가 429 로 쉬라고 한 끝 시각 — 이 줄에서 기다리다 못 보내면 rate_limited 다 (우리가 참은 것이 아니다)

    def _throttled(self, why: str) -> ScholarCallError:
        if self._cool_until > _now():
            return ScholarCallError(f"{self.name} 응답 429 뒤 쉬는 중 — {why} 보내지 않음", kind="rate_limited", provider=self.name)
        return ScholarCallError(f"{self.name} 요청 한도 — {why} 보내지 않음", kind="throttled", provider=self.name)

    def _start_at(self, now: float, after_backoff: bool) -> float:
        """이 요청이 시작해도 되는 가장 이른 시각 — 우리 간격(_next)과 벤더 쉼(_cool_until). 백오프를 마친 재시도는 벤더 쉼만 건너뛴다."""
        return max(now, self._next) if after_backoff else max(now, self._next, self._cool_until)

    def enter(self, wait_max: float, after_backoff: bool = False) -> None:
        """
        자리를 잡는다. wait_max 안에 시작할 수 없으면 보내지 않고 throttled(벤더가 쉬라고 한 동안이면 rate_limited).
        시작 시각은 **자리를 잡은 뒤에** 차지한다 — 먼저 차지하면 늦게 차지한 스레드가 자리를 먼저 잡아, 간격이 무너졌다
        (테스트 실측: 3초 간격 통로에서 0.02초 간격 요청). 429 백오프 뒤 재시도(after_backoff)도 **간격은 지킨다** — 09-30 리뷰:
        간격까지 건너뛰자 arXiv 에 네 스레드의 재시도가 0.05초 간격으로 몰렸다.
        """
        end = _now() + max(0.0, wait_max)
        with self._lock:
            ahead = self._start_at(_now(), after_backoff) - _now()
            if ahead > wait_max:
                raise self._throttled(f"{ahead:.1f}초 줄이라")
        if not self._slots.acquire(timeout=max(0.0, end - _now())):
            raise self._throttled("동시 요청 자리가 없어")
        try:
            while True:
                with self._lock:
                    now = _now()
                    start = self._start_at(now, after_backoff)
                    if start > now and start > end:          # 기다려야 하는데 그만큼 기다릴 수 없다
                        raise self._throttled(f"{start - now:.1f}초 줄이라")
                    if start <= now:
                        self._next = max(self._next, now + self.interval)
                        return
                _pause(start - now)
        except BaseException:
            self._slots.release()
            raise

    def leave(self) -> None:
        self._slots.release()

    def cool_down(self, seconds: float) -> None:
        """429 — 이 통로를 부르는 모두가 이만큼 쉰다 (LANE_COOLDOWN_MAX 까지). 우리 간격(_next)과 따로 든다."""
        with self._lock:
            self._cool_until = max(self._cool_until, _now() + min(max(0.0, seconds), LANE_COOLDOWN_MAX))


_LANES: dict[str, _Lane] = {}
_LANES_LOCK = threading.Lock()


def lane(name: str) -> _Lane:
    """통로 이름 → 요청 줄 (프로세스에 하나)."""
    with _LANES_LOCK:
        got = _LANES.get(name)
        if got is None:
            slots, interval = LANES.get(name, _LANE_DEFAULT)
            got = _LANES[name] = _Lane(name, slots, interval)
        return got


def reset_lanes() -> None:
    """요청 줄을 비운다 (테스트·LANES 를 바꾼 뒤)."""
    with _LANES_LOCK:
        _LANES.clear()


def _queue_wait() -> float:
    """줄에서 기다릴 최대 초 — 마감이 걸려 있으면 마감까지(요청 하나 몫은 남기고), 없으면 SCHOLAR_QUEUE_WAIT_SEC.
    마감을 건 호출자(f24 의 시간 예산)는 그 안에서 줄을 다 써도 된다 — 09-30 가짜 arXiv 실측: 10초로 자르면 예산 20초 안에
    들어갈 개념 검색 둘이 throttled 로 빠졌다."""
    left = remaining()
    if left is not None:
        return max(0.0, left - REQUEST_MIN_SEC)
    try:
        return float(os.environ.get("SCHOLAR_QUEUE_WAIT_SEC", "10"))
    except ValueError:
        return 10.0


def _request_timeout(who: str, timeout: float | None = None) -> float:
    """요청 하나의 시간 초과 — 통로의 timeout(없으면 SCHOLAR_TIMEOUT_SEC), 마감이 더 가까우면 마감까지. 마감이 지났으면 안 보낸다."""
    base = timeout or _timeout()
    left = remaining()
    if left is not None and left < REQUEST_MIN_SEC:
        raise ScholarCallError(f"{who} 시간 예산이 끝나 보내지 않음", kind="timeout", provider=who)
    return base if left is None else min(base, left)


def _http_get(who: str, url: str, params: dict | None = None, headers: dict | None = None, *,
              timeout: float | None = None, after_backoff: bool = False):
    """통로 줄(lane)을 지켜 GET 한 번. 줄에서 기다린 만큼 마감이 줄어드니 시간 초과는 자리를 잡은 **뒤에** 정한다."""
    ln = lane(who)
    ln.enter(_queue_wait(), after_backoff=after_backoff)
    try:
        return requests.get(url, params=params, timeout=_request_timeout(who, timeout),
                            headers={**_UA, "User-Agent": _UA["User-Agent"] % _mailto(), **(headers or {})})
    # requests 의 오류 문구는 요청 주소를 쿼리째 싣는다 — 값을 가리고, 원래 예외는 잇지 않는다(from None). 브리지가 찍는
    # traceback 에 이어진 예외(__cause__)의 문구가 그대로 나온다.
    except requests.Timeout as e:
        raise ScholarCallError(f"{who} 시간 초과: {_redact(e, params, headers)}", kind="timeout", provider=who) from None
    except requests.RequestException as e:
        raise ScholarCallError(f"{who} 요청 실패: {_redact(e, params, headers)}", kind="network", provider=who) from None
    finally:
        ln.leave()


def _retry_after(res) -> float:
    """429 응답이 쉬라고 한 초 (없거나 못 읽으면 RATE_LIMIT_WAIT_SEC). 자르지 않는다 — 자르는 것은 쓰는 쪽이 정한다."""
    try:
        return max(0.0, float((getattr(res, "headers", None) or {}).get("Retry-After") or RATE_LIMIT_WAIT_SEC))
    except (TypeError, ValueError):
        return RATE_LIMIT_WAIT_SEC


def _checked_get(who: str, url: str, params: dict | None = None, headers: dict | None = None, *,
                 timeout: float | None = None):
    """
    GET → 응답 (200 또는 404). 429 는 그 통로를 다 같이 쉬게 하고(cool_down) **한 번만** 다시 묻는다 — 마감 안에 쉴 수 있을 때만.
    나머지 상태는 ScholarCallError(http). 09-23 실측: Semantic Scholar 는 키 없이 연속 3번째부터 429, 한 번 쉬면 대개 통과한다.
    """
    res = _http_get(who, url, params, headers, timeout=timeout)
    if res.status_code == 429:
        wait = _retry_after(res)
        left = remaining()
        lane(who).cool_down(wait)
        if wait > RATE_LIMIT_WAIT_MAX:
            raise ScholarCallError(f"{who} 응답 429 — {wait:.0f}초 쉬라고 함", kind="rate_limited", provider=who)
        if left is not None and left - wait < REQUEST_MIN_SEC:
            raise ScholarCallError(f"{who} 응답 429 — 쉴 시간이 예산에 없음", kind="rate_limited", provider=who)
        time.sleep(max(0.0, wait))
        res = _http_get(who, url, params, headers, timeout=timeout, after_backoff=True)
        if res.status_code == 429:
            lane(who).cool_down(_retry_after(res))
            body = _redact(getattr(res, "text", ""), params, headers)[:120]
            raise ScholarCallError(f"{who} 응답 429: {body}", kind="rate_limited", provider=who)
    if res.status_code not in (200, 404):
        body = _redact(getattr(res, "text", ""), params, headers)[:200]
        raise ScholarCallError(f"{who} 응답 {res.status_code}: {body}", kind="http", provider=who)
    return res


def _get_json(url: str, params: dict | None, timeout: float | None = None, headers: dict | None = None,
              who: str = "") -> dict | list | None:
    """GET → JSON. 404 는 None, 429 는 한 번 쉬고 재시도, 나머지 오류는 PaperError(ScholarCallError)."""
    res = _checked_get(who, url, params, headers, timeout=timeout)
    if res.status_code == 404:
        return None
    try:
        return res.json()
    except ValueError as e:
        raise ScholarCallError(f"{who} 응답이 JSON 이 아닙니다", kind="parse", provider=who) from e


def _timeout() -> float:
    try:
        return float(os.environ.get("SCHOLAR_TIMEOUT_SEC", "8"))
    except ValueError:
        return 8.0


def _abstract_from_inverted(index: dict | None) -> str:
    """OpenAlex 는 초록을 {낱말: [위치…]} 로 준다. 위치 순으로 되돌려 한 줄로 접는다."""
    if not index:
        return ""
    slots: list[tuple[int, str]] = []
    for word, positions in index.items():
        for pos in positions or []:
            slots.append((int(pos), str(word)))
    slots.sort()
    text = _WS_RE.sub(" ", " ".join(w for _, w in slots)).strip()
    return text[:PAPER_ABSTRACT_MAX]


def _surname(display_name: str) -> str:
    """cite_key 용 성. 서양 이름은 마지막 토큰, 한글 이름은 그대로."""
    name = (display_name or "").strip()
    if not name:
        return ""
    if re.search(r"[가-힣]", name):
        return name
    return name.split()[-1]


def clean_query(query: str) -> str:
    """API 가 거부하거나 오해하는 글자를 지운 검색어."""
    return _WS_RE.sub(" ", _QUERY_STRIP_RE.sub(" ", query or "")).strip()


def _stem(t: str) -> str:
    """아주 거친 영어 어간 — 복수·진행형 꼬리만 떼고 접두 5자. "tasks/task", "switching/switch" 가 같아진다."""
    if t.endswith("ing") and len(t) > 5:
        t = t[:-3]
    elif t.endswith("es") and len(t) > 4:
        t = t[:-2]
    elif t.endswith("s") and len(t) > 3:
        t = t[:-1]
    return t[:_STEM_LEN]


#: 부정·반대 접두 + 낱말 (non-sleep · anti-inflammatory) 은 **한 낱말**로 붙인다 — 떼면 뒤 낱말이 그대로 겹침으로 세인다.
#: 09-30 실측(09-29 기준선 문헌 다시 판정): 「깊은 수면」 검색어 deep sleep recovery 에 non-sleep deep rest(잠이 아닌 휴식) 논문 둘이
#: sleep·deep 겹침으로 붙어 있었다.
_NEGATED_RE = re.compile(r"\b(non|anti)[-\s]+(?=[a-z])")


def _stems(text: str) -> set[str]:
    folded = _NEGATED_RE.sub(r"\1", (text or "").lower())
    return {_stem(t) for t in _TOKEN_RE.findall(folded)
            if len(t) > 2 and t not in _QUERY_STOP}


def word_stems(text: str) -> set[str]:
    """영어 내용 낱말의 어간 집합 (기능어·학술 상투어를 뺀 것). 순위(coverage·제목 문턱)와 f24 관련성 바닥이 같은 잣대를 쓴다."""
    return _stems(text)


def word_stem_seq(text: str) -> list[str]:
    """word_stems 와 같은 잣대의 어간을 **글 순서대로** (겹침 없이 빼지 않는다) — 이웃한 낱말 짝을 볼 때 쓴다."""
    folded = _NEGATED_RE.sub(r"\1", (text or "").lower())
    return [_stem(t) for t in _TOKEN_RE.findall(folded) if len(t) > 2 and t not in _QUERY_STOP]


def coverage(query: str, title: str, abstract: str) -> float:
    """검색어 낱말(어간) 중 제목·초록에 실제로 있는 비율. 검색어에 낱말이 없으면 1.0."""
    want = _stems(query)
    if not want:
        return 1.0
    have = _stems(title) | _stems(abstract)
    return len(want & have) / len(want)


def _quality(cov: float, rank_score: float, rank_max: float, cited_by: int, cited_max: int,
             year: int, year_now: int) -> float:
    """낱말 겹침 0.5 · 관련도 0.2 · 피인용(log) 0.2 · 최근성 0.1. 전부 0~1 로 정규화한 뒤 섞는다."""
    rel = (rank_score / rank_max) if rank_max > 0 else 0.0
    cit = (math.log1p(max(cited_by, 0)) / math.log1p(cited_max)) if cited_max > 0 else 0.0
    age = max(0, year_now - year) if year else 30
    recent = max(0.0, 1.0 - age / 30.0)
    return 0.5 * cov + 0.2 * rel + 0.2 * cit + 0.1 * recent


#: 이 프로세스에서 이미 알린 OpenAlex 설정 상태 — (mailto, api_key) 상태 짝마다 한 번만 stderr 에 적는다.
_OPENALEX_NOTED: set[tuple[str, str]] = set()
_OPENALEX_NOTED_LOCK = threading.Lock()


def _note_openalex_config(mailto: str, api_key: str) -> None:
    """OpenAlex 통로를 처음 만들 때 설정 **상태**만 한 줄 — 「mailto 설정됨 · api_key 없음」. 값은 찍지 않는다."""
    state = (_state(mailto), _state(api_key))
    with _OPENALEX_NOTED_LOCK:
        if state in _OPENALEX_NOTED:
            return
        _OPENALEX_NOTED.add(state)
    sys.stderr.write(f"[scholar] openalex mailto {state[0]} · api_key {state[1]}\n")


class OpenAlexScholar(ScholarProvider):
    """
    OpenAlex Works API (https://docs.openalex.org). 키 없이도 동작한다 — 다만 키 없는 요청은 **하루 예산**을 IP 로 나눠 쓴다.
    09-30 이 서버가 그 예산을 다 써서 429 · Retry-After ≈ 5.4시간을 받았다. OPENALEX_API_KEY(무료 발급)를 넣으면 예산이 10배고
    자정(UTC)에 다시 찬다 (help.openalex.org/api/authentication). 키는 `Authorization: Bearer` 머리로 보낸다 — 문서는 쿼리
    `api_key=` 도 받지만 주소는 requests 오류 문구·프록시·접근 로그에 쿼리째 남는다. polite pool 메일은 예전처럼 `mailto` 쿼리
    (OPENALEX_MAILTO, 없으면 SCHOLAR_MAILTO).
    """

    name = "openalex"

    #: 응답에서 받을 필드만 고른다 — 기본 응답은 항목당 수십 KB 다.
    SELECT = ",".join((
        "id", "doi", "display_name", "publication_year", "cited_by_count",
        "authorships", "primary_location", "abstract_inverted_index",
        "is_retracted", "type", "relevance_score",
    ))

    def __init__(self, base_url: str | None = None, mailto: str | None = None, timeout: float | None = None,
                 api_key: str | None = None):
        self.base_url = (base_url or os.environ.get("OPENALEX_BASE_URL", "https://api.openalex.org")).rstrip("/")
        self.mailto = mailto if mailto is not None else _openalex_mailto()
        self._api_key = api_key if api_key is not None else _openalex_api_key()
        self.timeout = timeout or _timeout()
        _note_openalex_config(self.mailto, self._api_key)

    def _params(self, extra: dict) -> dict:
        return {**extra, "mailto": self.mailto} if self.mailto else dict(extra)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    def _get(self, url: str, params: dict):
        """통로 줄을 지켜 GET (`_checked_get`). 키 없이 받은 429 에는 키를 넣으면 예산이 는다고 덧붙인다 — 값이 아니라 상태만."""
        try:
            return _checked_get(self.name, url, params, self._headers(), timeout=self.timeout)
        except ScholarCallError as e:
            if e.kind != "rate_limited" or self._api_key:
                raise
            raise ScholarCallError(f"{e} (api_key 없음 — OPENALEX_API_KEY 를 넣으면 하루 예산 10배)", kind=e.kind,
                                   provider=e.provider, status=e.status) from None

    def _failed(self, res, params: dict) -> ScholarCallError:
        body = _redact(getattr(res, "text", ""), params, self._headers())[:200]
        return ScholarCallError(f"openalex 응답 {res.status_code}: {body}", kind="http", provider=self.name)

    def search(self, query: str, *, limit: int = 5) -> list[PaperRef]:
        q = clean_query(query)
        if not q:
            return []
        params = self._params({
            "search": q,
            # 품질 재정렬을 위해 넉넉히 받는다. 철회 논문·초록 없는 항목은 API 에서 거른다.
            "per-page": max(limit * 5, 10),
            "filter": "is_retracted:false,has_abstract:true",
            "select": self.SELECT,
        })
        res = self._get(f"{self.base_url}/works", params)
        if res.status_code != 200:
            raise self._failed(res, params)
        works = (self._json(res) or {}).get("results") or []
        return self._rank(self._to_refs(works, q), limit)

    def resolve(self, title: str, doi: str = "") -> list[PaperRef]:
        """DOI 가 있으면 `/works/https://doi.org/…` 로 정확히, 없으면 제목 필터 검색(초록 유무 무관).

        제목 `search=` 는 어간 검색이라 옛 논문(초록 없는 Elsevier 등)을 놓친다 — 2026-09-22 실측에서
        Leroy(2009) 를 못 찾았다. 되찾기는 「있는 논문의 메타데이터」 라 초록 필터를 걸지 않는다."""
        if doi:
            params = self._params({"select": self.SELECT})
            res = self._get(f"{self.base_url}/works/https://doi.org/{doi}", params)
            if res.status_code == 404:
                return []
            works = [self._json(res) or {}]
        else:
            q = clean_query(title)
            if not q:
                return []
            params = self._params({"select": self.SELECT, "filter": f"is_retracted:false,title.search:{q}", "per-page": 3})
            res = self._get(f"{self.base_url}/works", params)
            if res.status_code != 200:
                raise self._failed(res, params)
            works = (self._json(res) or {}).get("results") or []
        return [ref for _, ref in self._to_refs(works, title)][:1]

    def _json(self, res) -> dict:
        try:
            data = res.json()
        except ValueError as e:
            raise ScholarCallError("openalex 응답이 JSON 이 아닙니다", kind="parse", provider=self.name) from e
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _to_refs(works: list[dict], query: str) -> list[tuple[float, PaperRef]]:
        out: list[tuple[float, PaperRef]] = []
        for w in works:
            if not isinstance(w, dict) or w.get("is_retracted"):
                continue
            title = _WS_RE.sub(" ", str(w.get("display_name") or "")).strip()
            if not title:
                continue
            authors = []
            for a in (w.get("authorships") or [])[:3]:
                nm = _surname(((a or {}).get("author") or {}).get("display_name", ""))
                if nm:
                    authors.append(nm)
            loc = w.get("primary_location") or {}
            source = (loc.get("source") or {}).get("display_name") or ""
            doi = str(w.get("doi") or "").replace("https://doi.org/", "").strip()
            url = f"https://doi.org/{doi}" if doi else str(loc.get("landing_page_url") or w.get("id") or "")
            ref = PaperRef(
                id="", kind="scholar", title=title, authors=authors,
                year=int(w.get("publication_year") or 0), venue=str(source),
                doi=doi, url=url,
                abstract=_abstract_from_inverted(w.get("abstract_inverted_index")),
                cited_by=int(w.get("cited_by_count") or 0), query=query, source="openalex",
            )
            out.append((float(w.get("relevance_score") or 0.0), ref))
        return out

    @staticmethod
    def _rank(scored: list[tuple[float, PaperRef]], limit: int) -> list[PaperRef]:
        return rank_refs(scored, limit)


def rank_refs(scored: list[tuple[float, PaperRef]], limit: int) -> list[PaperRef]:
    """
    [(관련도, ref)] → 품질 순 상위 limit. 모든 통로가 이 한 함수로 순위를 매긴다.

    낱말 겹침이 COVERAGE_MIN 에 못 미치는 결과는 **채워 넣지 않는다.** 09-22 실측: 뒤채움이
    코로나·AlphaFold·설치류 논문을 서가에 올렸다. 적게 주는 것이 엉뚱한 것을 주는 것보다 낫다 —
    서가는 인용 후보라서.
    """
    if not scored:
        return []
    year_now = datetime.date.today().year
    rank_max = max(s for s, _ in scored)
    cited_max = max(r.cited_by for _, r in scored)
    rows = []
    for rel, ref in scored:
        cov = coverage(ref.query, ref.title, ref.abstract)
        if not _title_hits(ref.query, ref.title, _vouched(ref)):
            continue
        rows.append((_quality(cov, rel, rank_max, ref.cited_by, cited_max, ref.year, year_now), cov, ref))
    rows.sort(key=lambda r: -r[0])
    out: list[PaperRef] = []
    seen: set[str] = set()
    for _, cov, ref in rows:
        if cov < COVERAGE_MIN:
            continue
        # 같은 논문이 두 번 오면(Europe PMC 는 MED·PMC·PPR 판을 따로 낸다) 품질이 높은 첫 것만.
        keys = {paper_key(ref), title_key(ref)}
        if keys & seen:
            continue
        seen |= keys
        out.append(ref)
        if len(out) >= limit:
            break
    return out


def title_key(ref: PaperRef) -> str:
    """제목만으로 만든 판별 키 (기호·공백 제거 80자). DOI 가 있는 판과 없는 판(arXiv 프리프린트)을 잇는다."""
    return "title:" + re.sub(r"[^a-z0-9가-힣]", "", ref.title.lower())[:80]


def paper_key(ref: PaperRef) -> str:
    """같은 논문 판별 키 — DOI 가 있으면 DOI, 없으면 제목. f24 의 dedup 과 같은 규칙."""
    if ref.doi:
        return "doi:" + ref.doi.lower()
    return title_key(ref)


def _title_hits(query: str, title: str, vouched: bool = True) -> bool:
    """검색어 낱말(어간)이 제목에 충분히 있는가. 검색어 낱말이 1개뿐이면 늘 참.

    vouched(피인용 있음 또는 두 통로 이상이 찾음)면 TITLE_HIT_MIN, 아니면 검색어 낱말 수 - TITLE_MISS_MAX_UNVOUCHED
    (둘 다 검색어 낱말 수를 넘지 않고, TITLE_HIT_MIN 밑으로 내려가지 않는다)."""
    want = _stems(query)
    if len(want) <= 1:
        return True
    need = TITLE_HIT_MIN if vouched else max(TITLE_HIT_MIN, len(want) - TITLE_MISS_MAX_UNVOUCHED)
    return len(want & _stems(title)) >= min(need, len(want))


def _vouched(ref: PaperRef) -> bool:
    return ref.cited_by > 0 or "+" in (ref.source or "")


def _positional(refs: list[PaperRef]) -> list[tuple[float, PaperRef]]:
    """관련도 점수를 안 주는 통로용 — 응답 순서를 관련도로 삼는다 (1위 = 1.0)."""
    n = max(len(refs), 1)
    return [(1.0 - i / n, r) for i, r in enumerate(refs)]


def _strip_tags(text: str) -> str:
    return _WS_RE.sub(" ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


class SemanticScholarScholar(ScholarProvider):
    """Semantic Scholar Graph API. 초록이 없을 때만 TLDR 한 줄을 쓴다 — TLDR 은 S2 의 모델 요약이라, 인용 주장을
    대조할 원문(f08 _verify_paper_claims)으로는 초록이 낫다 (2026-09-29). 키 없이 100회/5분."""

    name = "semanticscholar"
    FIELDS = "title,authors,year,venue,externalIds,abstract,citationCount,tldr,openAccessPdf,url"

    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or os.environ.get("S2_BASE_URL", "https://api.semanticscholar.org/graph/v1")).rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("S2_API_KEY", "")
        self.timeout = timeout or _timeout()

    def _headers(self) -> dict:
        return {"x-api-key": self.api_key} if self.api_key else {}

    def search(self, query: str, *, limit: int = 5) -> list[PaperRef]:
        q = clean_query(query)
        if not q:
            return []
        data = _get_json(f"{self.base_url}/paper/search", {"query": q, "limit": max(limit * 4, 10), "fields": self.FIELDS},
                         self.timeout, self._headers(), self.name)
        works = (data or {}).get("data") or []
        return rank_refs(_positional(self._to_refs(works, q)), limit)

    def resolve(self, title: str, doi: str = "") -> list[PaperRef]:
        if doi:
            w = _get_json(f"{self.base_url}/paper/DOI:{doi}", {"fields": self.FIELDS}, self.timeout, self._headers(), self.name)
            return self._to_refs([w], title)[:1] if w else []
        q = clean_query(title)
        if not q:
            return []
        data = _get_json(f"{self.base_url}/paper/search/match", {"query": q, "fields": self.FIELDS},
                         self.timeout, self._headers(), self.name)
        return self._to_refs((data or {}).get("data") or [], title)[:1]

    def _to_refs(self, works: list, query: str) -> list[PaperRef]:
        out = []
        for w in works:
            if not isinstance(w, dict) or not w.get("title"):
                continue
            ext = w.get("externalIds") or {}
            doi = str(ext.get("DOI") or "").strip()
            tldr = ((w.get("tldr") or {}).get("text") or "").strip()
            pdf = ((w.get("openAccessPdf") or {}).get("url") or "")
            out.append(PaperRef(
                id="", kind="scholar", title=_WS_RE.sub(" ", w["title"]).strip(),
                authors=[_surname((a or {}).get("name", "")) for a in (w.get("authors") or [])[:3] if (a or {}).get("name")],
                year=int(w.get("year") or 0), venue=str(w.get("venue") or ""), doi=doi,
                url=f"https://doi.org/{doi}" if doi else str(pdf or w.get("url") or ""),
                abstract=(_strip_tags(str(w.get("abstract") or "")) or tldr)[:PAPER_ABSTRACT_MAX],
                cited_by=int(w.get("citationCount") or 0), query=query, source=self.name,
            ))
        return out


#: arXiv 가 매긴 DOI 의 앞머리 (10.48550/arXiv.2112.09118).
ARXIV_DOI_PREFIX = "10.48550/arxiv."


class ArxivScholar(ScholarProvider):
    """arXiv Atom API. 최신 프리프린트 — 피인용 수는 없다 (순위는 겹침·최근성·응답 순서)."""

    name = "arxiv"
    NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or os.environ.get("ARXIV_BASE_URL", "https://export.arxiv.org/api/query")).rstrip("/")
        self.timeout = timeout or _timeout()

    def _fetch(self, search_query: str, max_results: int) -> list[PaperRef]:
        res = _checked_get(self.name, self.base_url, {"search_query": search_query, "max_results": max_results,
                                                      "sortBy": "relevance"}, timeout=self.timeout)
        if res.status_code != 200:
            raise ScholarCallError(f"arxiv 응답 {res.status_code}: {str(res.text)[:200]}", kind="http", provider=self.name)
        try:
            root = ET.fromstring(res.content)
        except ET.ParseError as e:
            raise ScholarCallError("arxiv 응답이 Atom XML 이 아닙니다", kind="parse", provider=self.name) from e
        out = []
        for e in root.findall("a:entry", self.NS):
            title = _WS_RE.sub(" ", (e.findtext("a:title", "", self.NS) or "")).strip()
            if not title:
                continue
            authors = [_surname(a.findtext("a:name", "", self.NS) or "") for a in e.findall("a:author", self.NS)[:3]]
            published = e.findtext("a:published", "", self.NS) or ""
            doi = (e.findtext("arxiv:doi", "", self.NS) or "").strip()
            link = (e.findtext("a:id", "", self.NS) or "").strip()
            out.append(PaperRef(
                id="", kind="scholar", title=title, authors=[a for a in authors if a],
                year=int(published[:4]) if published[:4].isdigit() else 0, venue="arXiv",
                doi=doi, url=f"https://doi.org/{doi}" if doi else link,
                abstract=_WS_RE.sub(" ", (e.findtext("a:summary", "", self.NS) or "")).strip()[:PAPER_ABSTRACT_MAX],
                cited_by=0, source=self.name,
            ))
        return out

    def search(self, query: str, *, limit: int = 5) -> list[PaperRef]:
        q = clean_query(query)
        if not q:
            return []
        words = [w for w in q.split() if w]
        refs = self._fetch("all:" + " AND all:".join(words) if len(words) > 1 else f"all:{q}", max(limit * 4, 10))
        if not refs and len(words) > 1:
            refs = self._fetch(f"all:{q}", max(limit * 4, 10))
        for r in refs:
            r.query = q
        return rank_refs(_positional(refs), limit)

    def resolve(self, title: str, doi: str = "") -> list[PaperRef]:
        """제목으로 프리프린트를 되찾는다. arXiv 가 아닌 DOI(학술지 논문)는 묻지 않는다 — arXiv 는 그 DOI 를 모르고,
        「3초에 한 번」 인 줄을 자료 인용 되찾기가 먼저 차지하면 개념 검색이 줄에서 밀린다 (09-30 G-A9)."""
        q = clean_query(title)
        if not q or (doi and not doi.lower().startswith(ARXIV_DOI_PREFIX)):
            return []
        refs = self._fetch(f'ti:"{q}"', 3)
        for r in refs:
            r.query = title
        return refs[:1]


class CrossrefScholar(ScholarProvider):
    """Crossref REST. DOI 의 권위 원본 — 되찾기(resolve)에 가장 정확하고, 검색은 초록이 드물어 겹침을 제목으로만 잰다."""

    name = "crossref"
    SELECT = "DOI,title,author,issued,container-title,abstract,is-referenced-by-count,URL"

    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or os.environ.get("CROSSREF_BASE_URL", "https://api.crossref.org")).rstrip("/")
        self.timeout = timeout or _timeout()

    def _params(self, extra: dict) -> dict:
        p = {"select": self.SELECT, **extra}
        if _mailto():
            p["mailto"] = _mailto()
        return p

    def search(self, query: str, *, limit: int = 5) -> list[PaperRef]:
        q = clean_query(query)
        if not q:
            return []
        data = _get_json(f"{self.base_url}/works", self._params({"query.bibliographic": q, "rows": max(limit * 4, 10)}),
                         self.timeout, None, self.name)
        items = ((data or {}).get("message") or {}).get("items") or []
        return rank_refs(_positional(self._to_refs(items, q)), limit)

    def resolve(self, title: str, doi: str = "") -> list[PaperRef]:
        if doi:
            data = _get_json(f"{self.base_url}/works/{doi}", None, self.timeout, None, self.name)
            item = (data or {}).get("message")
            return self._to_refs([item], title)[:1] if item else []
        q = clean_query(title)
        if not q:
            return []
        data = _get_json(f"{self.base_url}/works", self._params({"query.bibliographic": q, "rows": 1}), self.timeout, None, self.name)
        return self._to_refs(((data or {}).get("message") or {}).get("items") or [], title)[:1]

    def _to_refs(self, items: list, query: str) -> list[PaperRef]:
        out = []
        for w in items:
            if not isinstance(w, dict):
                continue
            title = _WS_RE.sub(" ", " ".join(w.get("title") or [])).strip()
            if not title:
                continue
            parts = ((w.get("issued") or {}).get("date-parts") or [[0]])[0] or [0]
            doi = str(w.get("DOI") or "").strip()
            out.append(PaperRef(
                id="", kind="scholar", title=title,
                authors=[str(a.get("family") or a.get("name") or "") for a in (w.get("author") or [])[:3] if isinstance(a, dict)],
                year=int(parts[0] or 0), venue=" ".join(w.get("container-title") or [])[:80],
                doi=doi, url=f"https://doi.org/{doi}" if doi else str(w.get("URL") or ""),
                abstract=_strip_tags(str(w.get("abstract") or ""))[:PAPER_ABSTRACT_MAX],
                cited_by=int(w.get("is-referenced-by-count") or 0), query=query, source=self.name,
            ))
        return out


class EuropePmcScholar(ScholarProvider):
    """Europe PMC REST (PubMed 포함). 생명과학·의학·심리학 저널. 초록·피인용 있음."""

    name = "europepmc"

    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or os.environ.get("EUROPEPMC_BASE_URL", "https://www.ebi.ac.uk/europepmc/webservices/rest")).rstrip("/")
        self.timeout = timeout or _timeout()

    def _fetch(self, query: str, page_size: int) -> list[dict]:
        data = _get_json(f"{self.base_url}/search", {"query": query, "format": "json", "pageSize": page_size, "resultType": "core"},
                         self.timeout, None, self.name)
        return ((data or {}).get("resultList") or {}).get("result") or []

    def search(self, query: str, *, limit: int = 5) -> list[PaperRef]:
        q = clean_query(query)
        if not q:
            return []
        return rank_refs(_positional(self._to_refs(self._fetch(q, max(limit * 4, 10)), q)), limit)

    def resolve(self, title: str, doi: str = "") -> list[PaperRef]:
        if doi:
            return self._to_refs(self._fetch(f'DOI:"{doi}"', 1), title)[:1]
        q = clean_query(title)
        return self._to_refs(self._fetch(f'TITLE:"{q}"', 1), title)[:1] if q else []

    def _to_refs(self, items: list, query: str) -> list[PaperRef]:
        out = []
        for w in items:
            if not isinstance(w, dict) or not w.get("title"):
                continue
            doi = str(w.get("doi") or "").strip()
            names = [n.strip() for n in str(w.get("authorString") or "").split(",") if n.strip()][:3]
            out.append(PaperRef(
                id="", kind="scholar", title=_WS_RE.sub(" ", w["title"]).strip().rstrip("."),
                authors=[n.split()[0] for n in names if n.split()],   # "Stothart C" 꼴 — 성이 앞
                year=int(w.get("pubYear") or 0), venue=str(w.get("journalTitle") or ""),
                doi=doi, url=f"https://doi.org/{doi}" if doi else f"https://europepmc.org/article/{w.get('source','MED')}/{w.get('id','')}",
                abstract=_strip_tags(str(w.get("abstractText") or ""))[:PAPER_ABSTRACT_MAX],   # 구조화 초록은 <h4> 가 섞여 온다
                cited_by=int(w.get("citedByCount") or 0), query=query, source=self.name,
            ))
        return out


#: 여러 통로를 합칠 때 마감이 없으면 통로 하나를 이만큼까지 기다린다 (요청 한도 줄 + 요청 시간 초과 + 429 한 번 쉼).
MULTI_WAIT_SEC = 20.0


class MultiScholar(ScholarProvider):
    """통로 여러 개를 동시에 부르고 합친다. 같은 논문(DOI 또는 제목)은 하나로 — 피인용은 최대, 빈 초록·DOI 는 채운다.

    한 통로가 죽어도 나머지로 간다 (전부 죽으면 PaperError). 어느 통로가 찾았는지는 `PaperRef.source` 에 "a+b" 로 남는다.
    결과는 `SearchHits` 라 통로마다 사정(status)을 달고 온다 — 09-30 G-A9: 한 통로가 429 를 받아도 합친 결과는 성공처럼 보였다.
    늦은 통로는 마감(없으면 MULTI_WAIT_SEC)까지만 기다리고 timeout 으로 적는다 — 제일 느린 통로가 개념 검색 전체를 붙들지 않게."""

    def __init__(self, providers: list[ScholarProvider]):
        self.providers = providers
        self.name = "+".join(p.name for p in providers)

    @staticmethod
    def _key(ref: PaperRef) -> str:
        return paper_key(ref)

    def _fan_out(self, call, what: str) -> tuple[list[list[PaperRef]], list[dict]]:
        """통로마다 call 을 동시에 → (받은 목록들, 통로마다 사정). 마감까지 안 온 통로는 버리고 기다리지 않는다."""
        pool = ThreadPoolExecutor(max_workers=max(1, len(self.providers)))
        # 마감(contextvars)을 통로 스레드로 넘긴다 — 스레드마다 제 사본이어야 한다 (한 Context 를 두 스레드가 같이 못 돈다)
        futs = [(p, pool.submit(contextvars.copy_context().run, call, p)) for p in self.providers]
        done, _ = wait([f for _, f in futs], timeout=max(0.0, remaining(MULTI_WAIT_SEC)))
        pool.shutdown(wait=False, cancel_futures=True)
        results: list[list[PaperRef]] = []
        status: list[dict] = []
        for p, fut in futs:
            if fut not in done:
                status.append({"provider": p.name, "state": "timeout", "error": f"{p.name} 제한 시간 안에 안 옴"})
                continue
            try:
                refs = fut.result()
            except Exception as e:  # noqa: BLE001 — 통로 하나의 버그가 나머지를 막지 않는다
                status.append(status_of_error(p.name, e))
                continue
            results.append(refs)
            status.append({"provider": p.name, "state": "ok" if refs else "empty", "n": len(refs)})
        bad = [s for s in status if s["state"] not in ("ok", "empty")]
        if bad:
            sys.stderr.write(f"[scholar] {what} 일부 통로 실패: "
                             f"{' · '.join(s['provider'] + ': ' + s.get('error', s['state']) for s in bad)[:300]}\n")
        if not results:
            raise ScholarCallError(f"모든 통로 실패 — {' · '.join(s.get('error', s['state']) for s in bad)[:200]}",
                                   kind=dominant_state(bad) or "failed", provider=self.name, status=status)
        return results, status

    @staticmethod
    def _merge(lists: list[list[PaperRef]]) -> list[tuple[float, PaperRef]]:
        merged: dict[str, tuple[float, PaperRef]] = {}
        by_title: dict[str, str] = {}     # 제목 키 → merged 의 키. DOI 있는 판과 없는 판(arXiv)을 같은 논문으로 잇는다
        for refs in lists:
            n = max(len(refs), 1)
            for i, ref in enumerate(refs):
                rel = 1.0 - i / n
                key = MultiScholar._key(ref)
                tkey = title_key(ref)
                canon = key if key in merged else by_title.get(tkey)
                if canon is None:
                    merged[key] = (rel, ref)
                    by_title[tkey] = key
                    continue
                key = canon
                rel0, keep = merged[key]
                keep.cited_by = max(keep.cited_by, ref.cited_by)
                keep.abstract = keep.abstract or ref.abstract
                if not keep.doi and ref.doi:
                    keep.doi, keep.url = ref.doi, f"https://doi.org/{ref.doi}"
                keep.venue = keep.venue or ref.venue
                keep.url = keep.url or (f"https://doi.org/{keep.doi}" if keep.doi else ref.url)
                if len(ref.authors) > len(keep.authors):
                    keep.authors = ref.authors
                if ref.source and ref.source not in keep.source.split("+"):
                    keep.source = f"{keep.source}+{ref.source}" if keep.source else ref.source
                # 두 통로가 같이 찾은 논문은 관련도를 올린다 — 합의는 신호다.
                merged[key] = (min(1.0, max(rel0, rel) + 0.15), keep)
        return list(merged.values())

    def search(self, query: str, *, limit: int = 5) -> list[PaperRef]:
        lists, status = self._fan_out(lambda p: p.search(query, limit=limit), f"search({query[:40]})")
        return SearchHits(rank_refs(self._merge(lists), limit), status)

    def resolve(self, title: str, doi: str = "") -> list[PaperRef]:
        lists, status = self._fan_out(lambda p: p.resolve(title, doi), f"resolve({(doi or title)[:40]})")
        merged = self._merge([l[:1] for l in lists if l])
        if not merged:
            return SearchHits([], status)
        merged.sort(key=lambda t: -t[0])
        return SearchHits([merged[0][1]], status)


class NoScholar(ScholarProvider):
    """검색 끔. 항상 빈 목록 — 자료 인용(deck)만으로 돈다."""

    name = "none"

    def search(self, query: str, *, limit: int = 5) -> list[PaperRef]:
        return []


_REGISTRY = {
    "openalex": OpenAlexScholar,
    "semanticscholar": SemanticScholarScholar,
    "s2": SemanticScholarScholar,
    "arxiv": ArxivScholar,
    "crossref": CrossrefScholar,
    "europepmc": EuropePmcScholar,
    "pubmed": EuropePmcScholar,
    "none": NoScholar,
}

#: "all" 로 한 번에 켜는 기본 묶음. crossref 는 검색 초록이 없어 되찾기용이라 뺀다 (되찾기는 openalex 가 DOI 로 한다).
#: semanticscholar 는 S2_API_KEY 가 있을 때만 끼운다 — 09-23 실측: 키 없이는 3번째 요청부터 429 (한 번 쉬어도 다시 429).
ALL_PROVIDERS = ("openalex", "arxiv", "europepmc")
ALL_PROVIDERS_KEYED = ("semanticscholar",)


def _all_provider_names() -> tuple[str, ...]:
    keyed = tuple(n for n in ALL_PROVIDERS_KEYED if os.environ.get("S2_API_KEY"))
    return ALL_PROVIDERS + keyed


def get_scholar(name: str | None = None, **kwargs) -> ScholarProvider:
    """
    name 생략 시 SCHOLAR_PROVIDER 환경변수(기본 none)를 따른다. 쉼표로 여러 개면 MultiScholar 로 합친다.
    "all" 은 ALL_PROVIDERS(+ S2_API_KEY 가 있으면 semanticscholar). 모르는 이름은 건너뛰고, 하나도 안 남으면 none.
    """
    raw = (name or os.environ.get("SCHOLAR_PROVIDER") or "none").strip().lower()
    names = []
    for n in raw.split(","):
        n = n.strip()
        if n == "all":
            names.extend(_all_provider_names())
        elif n:
            names.append(n)
    providers: list[ScholarProvider] = []
    seen = set()
    for n in names:
        cls = _REGISTRY.get(n)
        if cls is None or cls is NoScholar or cls in seen:
            continue
        seen.add(cls)
        providers.append(cls(**kwargs) if not kwargs or n == "openalex" else cls())
    if not providers:
        return NoScholar()
    return providers[0] if len(providers) == 1 else MultiScholar(providers)
