"""
[F-24] 교수가 읽고 온 논문 — 자료가 인용한 문헌 + 실재 논문 검색으로 질문의 근거를 만드는 모듈입니다.
SlideDoc(+ConceptGraph) → PaperDoc.  자유 질문 문자열 → PaperDoc.

    from chuckchuck.f24_papers import build_papers, search_papers
    papers = build_papers(graph, slidedoc, scholar="openalex", llm="solar")   # 세션에 한 번
    doc = build_questions(graph, triage, track="5", papers=papers, ...)       # F-08 이 인용
    hits = search_papers("알림이 주의에 미치는 비용", scholar="openalex", llm="solar")  # 자유 검색

F-08·F-11 과 같은 철학이다 — **어떤 논문이 있는지는 코드와 검색 API 가 정하고, LLM 은 문장만 쓴다.**

1. **자료가 인용한 문헌(deck)** 은 `_evidence.citation_lines` 가 정규식으로 뽑는다. LLM 0.
   교수가 "3장에서 인용한 Stothart(2015)는 …" 로 묻는 재료이고, 지어냄이 구조적으로 없다.
2. **실재 논문(scholar)** 은 상위 weight 개념마다 학술 검색 API 를 부른다. 제목·저자·연도·
   DOI·초록은 API 원문 그대로다. 초록은 **자른 원문**이지 요약이 아니다 — 논문 내용을
   LLM 이 다시 쓰게 두면 거기서 지어낸다.
3. LLM 은 한 번만 쓴다 — 한국어 개념 이름을 **영어 검색어**로 바꾸는 일. 검색어는 사실이
   아니라 열쇠라 지어내도 해가 없다 (검색 결과가 없거나 엉뚱할 뿐이고, 그건 코드가 거른다).
   영문 개념은 LLM 없이 그대로 쓴다.

검색이 꺼져 있거나(SCHOLAR_PROVIDER=none) 실패하면 deck 만 남고 `note` 에 사정을 적는다.
빈 목록으로 조용히 넘어가지 않는다 — "왜 논문 근거 질문이 안 나오지" 를 디버깅할 수 있어야 한다.
"""

from __future__ import annotations

import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from ._evidence import citation_lines
from ._json_text import extract_json_object
from .contracts import (
    PAPER_NODE_MAX,
    PAPER_PER_NODE,
    PAPER_SEARCH_MAX,
    ConceptGraph,
    ConceptNode,
    PaperDoc,
    PaperError,
    PaperRef,
    SlideDoc,
)
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm
from .providers.scholar_base import ScholarProvider
from .providers.scholar_impl import get_scholar

#: 검색을 동시에 몇 개 띄울지. OpenAlex 는 초당 10 요청까지 받는다 — 그 아래로 둔다.
SEARCH_WORKERS = 4
#: 자료 인용(deck)을 검색으로 되찾아 DOI·초록을 채울 최대 개수. 참고문헌이 30개여도 다 안 간다.
RESOLVE_DECK_MAX = int(os.environ.get("CHUCKCHUCK_PAPER_RESOLVE_MAX", "5"))
#: 되찾은 검색 결과가 자료의 제목과 이만큼 겹쳐야 같은 논문으로 본다 (토큰 Jaccard).
RESOLVE_MATCH_MIN = 0.6

QUERY_SYSTEM_PROMPT = """당신은 학술 검색 사서다.
발표 자료에서 뽑은 개념 목록을 받아, 개념마다 **영어 학술 검색어** 하나를 만든다.

- query: 3~7 단어의 영어 명사구. 학술 데이터베이스(OpenAlex 등)에 그대로 넣을 검색어다.
  개념의 뜻을 영어 학술 용어로 옮기되, **'발표 주제' 의 맥락 낱말을 반드시 포함**해서 다른 분야의
  논문이 걸리지 않게 하라. "환경 설계" 를 그냥 "environmental design" 으로 옮기면 환경경제학
  논문이 온다 — 주제가 스마트폰 알림이면 "notification-free workspace design" 처럼 쓴다.
  한국어·따옴표·불리언 연산자를 쓰지 마라.
  (예: 주제 "스마트폰 알림과 집중" · 개념 "알림의 주의 비용" → "smartphone notification attention cost")
- node_id 는 개념 목록의 괄호 안 id 를 **글자 그대로** 옮긴다. label 은 개념 이름 그대로.
  예시의 id 를 베끼지 마라 — 목록에 없는 id 는 버려진다.
- 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마 (id·label 은 목록의 것):
{ "queries": [ { "node_id": "<목록의 id>", "label": "<목록의 개념 이름>", "query": "smartphone notification attention cost" } ] }
"""

_HANGUL_RE = re.compile(r"[가-힣]")
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}")
_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# 검색어 — 영문은 그대로, 한글은 LLM 1콜 (실패하면 영문 토큰만, 그것도 없으면 검색 안 함)
# ---------------------------------------------------------------------------

def _needs_translation(text: str) -> bool:
    return bool(_HANGUL_RE.search(text or ""))


def _ascii_fallback(*texts: str) -> str:
    toks: list[str] = []
    for t in texts:
        for tok in _ASCII_TOKEN_RE.findall(t or ""):
            if tok.lower() not in (x.lower() for x in toks):
                toks.append(tok)
    return " ".join(toks[:6])


def _engine(llm: str | LLMProvider | None, llm_kwargs: dict | None) -> LLMProvider:
    return llm if isinstance(llm, LLMProvider) else get_llm(llm, **(llm_kwargs or {}))


def _translate_queries(items: list[tuple[str, str]], llm: str | LLMProvider | None,
                       llm_kwargs: dict | None, topic: str = "") -> dict[str, str]:
    """[(id, 한글 설명)] → {id: 영어 검색어}. topic 은 발표 주제 한 줄. LLM 이 실패하면 빈 dict — 호출자가 폴백한다."""
    if not items:
        return {}
    lines = [f"- ({i}) {text}" for i, text in items]
    head = f"[TASK] paper-queries\n\n발표 주제: {topic}\n\n" if topic else "[TASK] paper-queries\n\n"
    user = head + "## 개념 목록\n" + "\n".join(lines)
    try:
        engine = _engine(llm, llm_kwargs)
        raw = engine.complete(system=QUERY_SYSTEM_PROMPT, user=user, temperature=0.0,
                              max_tokens=1024, json_mode=True)
        data = extract_json_object(raw)
    except Exception as e:  # noqa: BLE001 — 검색어는 열쇠일 뿐, 실패해도 폴백이 있다
        sys.stderr.write(f"[f24] 검색어 번역 실패, 영문 토큰으로 폴백: {e}\n")
        return {}
    # id → label → 순서. 2026-09-22 실측: Solar 가 예시의 "c1" 을 그대로 베껴 id 가 하나도 안 맞았다.
    # 검색어는 열쇠일 뿐이라 느슨하게 받는다 — 잘못 붙어도 검색 결과가 엉뚱할 뿐 사실이 생기지는 않는다.
    known = {i for i, _ in items}
    by_label = {text.split(" — ", 1)[0].strip(): i for i, text in items}
    rows = [q for q in ((data.get("queries") or []) if isinstance(data, dict) else []) if isinstance(q, dict)]
    out: dict[str, str] = {}
    for pos, q in enumerate(rows):
        query = _WS_RE.sub(" ", str(q.get("query", "") or "")).strip()
        if not query or _needs_translation(query):
            continue
        nid = str(q.get("node_id", "") or "")
        if nid not in known:
            nid = by_label.get(str(q.get("label", "") or "").strip(), "")
        if not nid and len(rows) == len(items):
            nid = items[pos][0]
        if nid in known and nid not in out:
            out[nid] = query[:120]
    return out


def _pick_nodes(graph: ConceptGraph, node_max: int) -> list[ConceptNode]:
    """상위 weight 개념. core 가 support 보다 앞, 같으면 weight, 그다음 id (결정적)."""
    ordered = sorted(
        graph.nodes,
        key=lambda n: (0 if n.importance == "core" else 1, -n.weight, n.id),
    )
    return ordered[:max(0, node_max)]


def _topic_line(graph: ConceptGraph) -> str:
    """발표 주제 한 줄 — 검색어가 다른 분야로 새지 않게 번역 프롬프트에 싣는다. 루트 개념 + 상위 3개 이름."""
    roots = [n for n in graph.nodes if n.depth == 1] or graph.nodes[:1]
    tops = sorted(graph.nodes, key=lambda n: -n.weight)[:3]
    names = []
    for n in (*roots, *tops):
        if n.label and n.label not in names:
            names.append(n.label)
    head = roots[0].summary if roots and roots[0].summary else ""
    return " · ".join(names[:4]) + (f" — {head[:80]}" if head else "")


def _queries_for(nodes: list[ConceptNode], llm, llm_kwargs, topic: str = "") -> list[tuple[ConceptNode, str]]:
    plain: dict[str, str] = {}
    to_translate: list[tuple[str, str]] = []
    for n in nodes:
        if not _needs_translation(n.label):
            plain[n.id] = n.label.strip()
        else:
            desc = n.label + (f" — {n.summary}" if n.summary else "")
            to_translate.append((n.id, desc[:160]))
    translated = _translate_queries(to_translate, llm, llm_kwargs, topic)
    out: list[tuple[ConceptNode, str]] = []
    for n in nodes:
        q = plain.get(n.id) or translated.get(n.id) or _ascii_fallback(n.label, n.summary)
        if q:
            out.append((n, q))
    return out


# ---------------------------------------------------------------------------
# 검색 · 병합
# ---------------------------------------------------------------------------

def _scholar(scholar: str | ScholarProvider | None) -> ScholarProvider:
    return scholar if isinstance(scholar, ScholarProvider) else get_scholar(scholar)


def _dedup_key(ref: PaperRef) -> str:
    if ref.doi:
        return f"doi:{ref.doi.lower()}"
    return "title:" + re.sub(r"[^a-z0-9가-힣]", "", ref.title.lower())[:80]


def _title_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2}


def _same_paper(deck: PaperRef, hit: PaperRef) -> bool:
    if deck.doi and hit.doi:
        return deck.doi.lower() == hit.doi.lower()
    a, b = _title_tokens(deck.title), _title_tokens(hit.title)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= RESOLVE_MATCH_MIN


def _search_many(provider: ScholarProvider, jobs: list[tuple[str, object]]) -> tuple[dict[str, list[PaperRef]], str]:
    """[(key, 호출)] → {key: refs}, note. 실패한 호출은 note 에 첫 사유만 남기고 나머지는 그대로 받는다."""
    results: dict[str, list[PaperRef]] = {}
    note = ""
    if not jobs:
        return results, note

    def run(job):
        key, call = job
        return key, call()

    with ThreadPoolExecutor(max_workers=SEARCH_WORKERS) as pool:
        futures = [pool.submit(run, j) for j in jobs]
        for fut in futures:
            try:
                key, refs = fut.result()
                results[key] = refs
            except PaperError as e:
                note = note or f"{provider.name} 검색 실패: {e}"
            except Exception as e:  # noqa: BLE001 — provider 버그가 질문 생성을 막으면 안 된다
                note = note or f"{provider.name} 검색 오류: {type(e).__name__}: {e}"
    return results, note


def _assign_ids(refs: list[PaperRef], prefix: str) -> None:
    for i, r in enumerate(refs, 1):
        r.id = f"{prefix}{i:02d}"


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------

def build_papers(
    graph: ConceptGraph | dict,
    slidedoc: SlideDoc | dict | None = None,
    *,
    scholar: str | ScholarProvider | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
    node_max: int = PAPER_NODE_MAX,
    per_node: int = PAPER_PER_NODE,
) -> PaperDoc:
    """
    ConceptGraph (+선택 SlideDoc) → PaperDoc. **트랙과 무관하니 세션에 한 번만** 만든다.

    - slidedoc 이 있으면 자료가 인용한 문헌(deck)을 먼저 뽑는다. 이건 검색이 꺼져 있어도 나온다.
    - scholar 가 none 이 아니면 ① deck 문헌을 제목으로 되찾아 DOI·초록을 채우고
      ② 상위 `node_max` 개념마다 `per_node` 편을 검색해 붙인다 (`node_ids` 로 조인).
    - 같은 논문(DOI 또는 제목)은 하나로 합치고 node_ids 를 더한다.
    - 검색 실패는 `note` 에 남기고 deck 만으로 돌려준다. 예외를 밖으로 던지지 않는다.
    """
    if isinstance(graph, dict):
        graph = ConceptGraph.from_dict(graph)
    if isinstance(slidedoc, dict):
        slidedoc = SlideDoc.from_dict(slidedoc)
    provider = _scholar(scholar)

    deck = citation_lines(slidedoc)
    # deck 문헌에 근거 개념을 붙인다 — 그 장을 근거로 가진 개념이면 관련 문헌이다.
    for ref in deck:
        ref.node_ids = [n.id for n in graph.nodes if ref.slide_no in n.slide_nos]

    if provider.name == "none":
        _assign_ids(deck, "d")
        return PaperDoc(file_name=graph.file_name, refs=deck, provider=provider.name,
                        note="검색 꺼짐(SCHOLAR_PROVIDER=none) — 자료가 인용한 문헌만")

    jobs: list[tuple[str, object]] = []
    resolvable = [r for r in deck if r.title or r.doi][:RESOLVE_DECK_MAX]
    for ref in resolvable:
        jobs.append((f"resolve:{ref.cite_key}", (lambda r=ref: provider.resolve(r.title, r.doi))))
    node_queries = _queries_for(_pick_nodes(graph, node_max), llm, llm_kwargs, _topic_line(graph))
    for node, query in node_queries:
        jobs.append((f"node:{node.id}", (lambda q=query: provider.search(q, limit=per_node))))
    results, note = _search_many(provider, jobs)

    # ① deck 되찾기 — 같은 논문일 때만 채운다. kind 는 deck 그대로 (자료가 인용한 사실이 근거다).
    for ref in resolvable:
        hits = results.get(f"resolve:{ref.cite_key}") or []
        if hits and _same_paper(ref, hits[0]):
            hit = hits[0]
            ref.title = ref.title or hit.title
            ref.doi = ref.doi or hit.doi
            ref.url = ref.url or hit.url
            ref.venue = ref.venue or hit.venue
            ref.abstract = ref.abstract or hit.abstract
            ref.cited_by = hit.cited_by
            if len(hit.authors) > len(ref.authors):
                ref.authors = hit.authors

    # ② 개념별 검색 — deck 과 겹치면 deck 에 node_ids 만 더하고 버린다.
    seen = {_dedup_key(r): r for r in deck}
    scholar_refs: list[PaperRef] = []
    for node, _ in node_queries:
        for hit in results.get(f"node:{node.id}") or []:
            key = _dedup_key(hit)
            if key in seen:
                if node.id not in seen[key].node_ids:
                    seen[key].node_ids.append(node.id)
                continue
            hit.node_ids = [node.id]
            seen[key] = hit
            scholar_refs.append(hit)

    _assign_ids(deck, "d")
    _assign_ids(scholar_refs, "s")
    if not note and not scholar_refs and node_queries:
        note = "검색 결과 없음"
    if not node_queries and not deck:
        note = note or "검색어를 만들 수 없음(개념 없음)"
    return PaperDoc(file_name=graph.file_name, refs=deck + scholar_refs,
                    provider=provider.name, note=note)


def search_papers(
    query: str,
    *,
    limit: int = PAPER_SEARCH_MAX,
    scholar: str | ScholarProvider | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> PaperDoc:
    """
    자유 질문 → PaperDoc (전부 kind="scholar"). "이 주제의 수준 높은 논문을 바로 보여 줘" 용.

    한국어 질문이면 LLM 1콜로 영어 검색어를 만들고, 영문이면 그대로 검색한다.
    순위는 provider 가 매긴 품질 순(관련도·피인용·최근성)이다. 실패는 `note` 에 남긴다.
    """
    q = _WS_RE.sub(" ", query or "").strip()
    provider = _scholar(scholar)
    if not q:
        return PaperDoc(file_name="", provider=provider.name, note="검색어가 비어 있음")
    if provider.name == "none":
        return PaperDoc(file_name="", provider=provider.name, note="검색 꺼짐(SCHOLAR_PROVIDER=none)")

    search_q = q
    if _needs_translation(q):
        search_q = _translate_queries([("q", q[:200])], llm, llm_kwargs).get("q") or _ascii_fallback(q)
        if not search_q:
            return PaperDoc(file_name="", provider=provider.name,
                            note="검색어를 영어로 만들지 못했어요 — 영어로 다시 물어봐 주세요")
    results, note = _search_many(provider, [("q", (lambda: provider.search(search_q, limit=max(1, limit))))])
    refs = results.get("q") or []
    for r in refs:
        r.query = search_q
    _assign_ids(refs, "s")
    if not refs and not note:
        note = "검색 결과 없음"
    return PaperDoc(file_name="", refs=refs, provider=provider.name, note=note)
