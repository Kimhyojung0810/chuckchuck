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
    SCHOLAR_MAILTO     polite pool 용 연락 메일 (OpenAlex·Crossref). OPENALEX_MAILTO 도 읽는다
    S2_API_KEY         Semantic Scholar 키 (선택 — 없으면 공용 한도 100회/5분)
    SCHOLAR_TIMEOUT_SEC  요청 시간 초과 (기본 8)
"""

from __future__ import annotations

import datetime
import html
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import requests

from ..contracts import PAPER_ABSTRACT_MAX, PaperError, PaperRef
from .scholar_base import ScholarProvider

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
#: coverage 를 잴 때 무시할 낱말.
_QUERY_STOP = {"the", "and", "for", "with", "from", "into", "over", "under", "using", "based",
               "study", "review", "analysis", "effect", "effects", "approach", "method", "methods"}


_UA = {"User-Agent": "chuckchuck/1.0 (F-24 papers; mailto:%s)"}


def _mailto() -> str:
    return os.environ.get("SCHOLAR_MAILTO") or os.environ.get("OPENALEX_MAILTO") or ""


#: 429(속도 제한)를 받으면 이만큼 쉬고 **한 번만** 다시 묻는다. Retry-After 가 있으면 그 값(상한 RATE_LIMIT_WAIT_MAX).
RATE_LIMIT_WAIT_SEC = 1.5
RATE_LIMIT_WAIT_MAX = 4.0


def _get_json(url: str, params: dict | None, timeout: float, headers: dict | None = None, who: str = "",
              _retry: bool = True) -> dict | list | None:
    """GET → JSON. 404 는 None, 429 는 한 번 쉬고 재시도, 나머지 오류는 PaperError. 벤더 이름은 메시지에만 남는다."""
    try:
        res = requests.get(url, params=params, timeout=timeout,
                           headers={**_UA, "User-Agent": _UA["User-Agent"] % _mailto(), **(headers or {})})
    except requests.RequestException as e:
        raise PaperError(f"{who} 요청 실패: {e}") from e
    if res.status_code == 404:
        return None
    if res.status_code == 429 and _retry:
        # 09-23 실측: Semantic Scholar 는 키 없이 연속 3번째부터 429. 한 번 쉬면 대개 통과한다.
        try:
            wait = min(float(res.headers.get("Retry-After") or RATE_LIMIT_WAIT_SEC), RATE_LIMIT_WAIT_MAX)
        except (TypeError, ValueError):
            wait = RATE_LIMIT_WAIT_SEC
        time.sleep(max(0.0, wait))
        return _get_json(url, params, timeout, headers, who, _retry=False)
    if res.status_code != 200:
        raise PaperError(f"{who} 응답 {res.status_code}: {res.text[:200]}")
    try:
        return res.json()
    except ValueError as e:
        raise PaperError(f"{who} 응답이 JSON 이 아닙니다") from e


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


def _stems(text: str) -> set[str]:
    return {_stem(t) for t in _TOKEN_RE.findall((text or "").lower())
            if len(t) > 2 and t not in _QUERY_STOP}


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


class OpenAlexScholar(ScholarProvider):
    """OpenAlex Works API (https://docs.openalex.org). 키 없이 동작한다."""

    name = "openalex"

    #: 응답에서 받을 필드만 고른다 — 기본 응답은 항목당 수십 KB 다.
    SELECT = ",".join((
        "id", "doi", "display_name", "publication_year", "cited_by_count",
        "authorships", "primary_location", "abstract_inverted_index",
        "is_retracted", "type", "relevance_score",
    ))

    def __init__(self, base_url: str | None = None, mailto: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or os.environ.get("OPENALEX_BASE_URL", "https://api.openalex.org")).rstrip("/")
        self.mailto = mailto if mailto is not None else os.environ.get("OPENALEX_MAILTO", "")
        self.timeout = timeout or _timeout()

    def search(self, query: str, *, limit: int = 5) -> list[PaperRef]:
        q = clean_query(query)
        if not q:
            return []
        params = {
            "search": q,
            # 품질 재정렬을 위해 넉넉히 받는다. 철회 논문·초록 없는 항목은 API 에서 거른다.
            "per-page": max(limit * 5, 10),
            "filter": "is_retracted:false,has_abstract:true",
            "select": self.SELECT,
        }
        if self.mailto:
            params["mailto"] = self.mailto
        try:
            res = requests.get(f"{self.base_url}/works", params=params, timeout=self.timeout,
                               headers={"User-Agent": "chuckchuck/1.0 (F-24 papers)"})
        except requests.RequestException as e:
            raise PaperError(f"OpenAlex 요청 실패: {e}") from e
        if res.status_code != 200:
            raise PaperError(f"OpenAlex 응답 {res.status_code}: {res.text[:200]}")
        try:
            works = res.json().get("results") or []
        except ValueError as e:
            raise PaperError("OpenAlex 응답이 JSON 이 아닙니다") from e
        return self._rank(self._to_refs(works, q), limit)

    def resolve(self, title: str, doi: str = "") -> list[PaperRef]:
        """DOI 가 있으면 `/works/https://doi.org/…` 로 정확히, 없으면 제목 필터 검색(초록 유무 무관).

        제목 `search=` 는 어간 검색이라 옛 논문(초록 없는 Elsevier 등)을 놓친다 — 2026-09-22 실측에서
        Leroy(2009) 를 못 찾았다. 되찾기는 「있는 논문의 메타데이터」 라 초록 필터를 걸지 않는다."""
        params = {"select": self.SELECT}
        if self.mailto:
            params["mailto"] = self.mailto
        try:
            if doi:
                res = requests.get(f"{self.base_url}/works/https://doi.org/{doi}", params=params,
                                   timeout=self.timeout, headers={"User-Agent": "chuckchuck/1.0 (F-24 papers)"})
                if res.status_code == 404:
                    return []
                if res.status_code != 200:
                    raise PaperError(f"OpenAlex 응답 {res.status_code}: {res.text[:200]}")
                works = [res.json()]
            else:
                q = clean_query(title)
                if not q:
                    return []
                params.update({"filter": f"is_retracted:false,title.search:{q}", "per-page": 3})
                res = requests.get(f"{self.base_url}/works", params=params, timeout=self.timeout,
                                   headers={"User-Agent": "chuckchuck/1.0 (F-24 papers)"})
                if res.status_code != 200:
                    raise PaperError(f"OpenAlex 응답 {res.status_code}: {res.text[:200]}")
                works = res.json().get("results") or []
        except requests.RequestException as e:
            raise PaperError(f"OpenAlex 요청 실패: {e}") from e
        except ValueError as e:
            raise PaperError("OpenAlex 응답이 JSON 이 아닙니다") from e
        return [ref for _, ref in self._to_refs(works, title)][:1]

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
    """Semantic Scholar Graph API. TLDR 한 줄이 있으면 초록 대신 쓴다 (짧고 사람이 쓴 요약이 아니라 모델 요약이지만
    S2 가 만든 것이지 우리 LLM 이 만든 것이 아니다 — 출처가 남는다). 키 없이 100회/5분."""

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
                abstract=(tldr or _WS_RE.sub(" ", str(w.get("abstract") or "")).strip())[:PAPER_ABSTRACT_MAX],
                cited_by=int(w.get("citationCount") or 0), query=query, source=self.name,
            ))
        return out


class ArxivScholar(ScholarProvider):
    """arXiv Atom API. 최신 프리프린트 — 피인용 수는 없다 (순위는 겹침·최근성·응답 순서)."""

    name = "arxiv"
    NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or os.environ.get("ARXIV_BASE_URL", "https://export.arxiv.org/api/query")).rstrip("/")
        self.timeout = timeout or _timeout()

    def _fetch(self, search_query: str, max_results: int) -> list[PaperRef]:
        try:
            res = requests.get(self.base_url, params={"search_query": search_query, "max_results": max_results,
                                                      "sortBy": "relevance"},
                               timeout=self.timeout, headers={"User-Agent": _UA["User-Agent"] % _mailto()})
        except requests.RequestException as e:
            raise PaperError(f"arxiv 요청 실패: {e}") from e
        if res.status_code != 200:
            raise PaperError(f"arxiv 응답 {res.status_code}: {res.text[:200]}")
        try:
            root = ET.fromstring(res.content)
        except ET.ParseError as e:
            raise PaperError("arxiv 응답이 Atom XML 이 아닙니다") from e
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
        q = clean_query(title)
        if not q:
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
                abstract=_WS_RE.sub(" ", str(w.get("abstractText") or "")).strip()[:PAPER_ABSTRACT_MAX],
                cited_by=int(w.get("citedByCount") or 0), query=query, source=self.name,
            ))
        return out


class MultiScholar(ScholarProvider):
    """통로 여러 개를 동시에 부르고 합친다. 같은 논문(DOI 또는 제목)은 하나로 — 피인용은 최대, 빈 초록·DOI 는 채운다.

    한 통로가 죽어도 나머지로 간다 (전부 죽으면 PaperError). 어느 통로가 찾았는지는 `PaperRef.source` 에 "a+b" 로 남는다."""

    def __init__(self, providers: list[ScholarProvider]):
        self.providers = providers
        self.name = "+".join(p.name for p in providers)

    @staticmethod
    def _key(ref: PaperRef) -> str:
        return paper_key(ref)

    def _fan_out(self, call, what: str) -> list[list[PaperRef]]:
        results: list[list[PaperRef]] = []
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=max(1, len(self.providers))) as pool:
            futs = [(p, pool.submit(call, p)) for p in self.providers]
            for p, fut in futs:
                try:
                    results.append(fut.result())
                except PaperError as e:
                    errors.append(f"{p.name}: {e}")
                except Exception as e:  # noqa: BLE001 — 통로 하나의 버그가 나머지를 막지 않는다
                    errors.append(f"{p.name}: {type(e).__name__}: {e}")
        if errors:
            sys.stderr.write(f"[scholar] {what} 일부 통로 실패: {' · '.join(errors)[:300]}\n")
        if not results:
            raise PaperError(f"모든 통로 실패 — {' · '.join(errors)[:200]}")
        return results

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
        lists = self._fan_out(lambda p: p.search(query, limit=limit), f"search({query[:40]})")
        return rank_refs(self._merge(lists), limit)

    def resolve(self, title: str, doi: str = "") -> list[PaperRef]:
        lists = self._fan_out(lambda p: p.resolve(title, doi), f"resolve({(doi or title)[:40]})")
        merged = self._merge([l[:1] for l in lists if l])
        if not merged:
            return []
        merged.sort(key=lambda t: -t[0])
        return [merged[0][1]]


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
