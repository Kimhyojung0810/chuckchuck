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
from dataclasses import dataclass

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
from .providers.scholar_impl import _stems as _word_stems
from .providers.scholar_impl import get_scholar

#: 검색을 동시에 몇 개 띄울지. OpenAlex 는 초당 10 요청까지 받는다 — 그 아래로 둔다.
SEARCH_WORKERS = 4
#: 자료 인용(deck)을 검색으로 되찾아 DOI·초록을 채울 최대 개수. 참고문헌이 30개여도 다 안 간다.
RESOLVE_DECK_MAX = int(os.environ.get("CHUCKCHUCK_PAPER_RESOLVE_MAX", "5"))
#: 되찾은 검색 결과가 자료의 제목과 이만큼 겹쳐야 같은 논문으로 본다 (토큰 Jaccard).
RESOLVE_MATCH_MIN = 0.6
#: 검색 결과(scholar hit)의 제목+초록 어간이 검색어 어간과 최소 이만큼 겹쳐야 남긴다. 어간은 provider 의 순위 매기기와
#: 같은 것(소문자 · 불용어 제거 · 복수/진행형 꼬리 뗀 앞 5글자)이다. provider 가 `rank_refs` 로 이미 거르지만, 그 검사는
#: provider 마다 따로 부르는 것이라 새 통로·가짜 통로가 빠뜨리면 그대로 서가에 올라간다 — f24 가 마지막에 한 번 더 본다.
#: 2026-09-24 실측: "B2B·B2C 수익모델" 개념에 임신성 당뇨(GDM) 논문이 붙어 질문 why 에 들어갔다.
RELEVANCE_SHARED_MIN = 1
#: 검색어의 내용 토큰이 이보다 적으면 발표 주제 토큰을 붙인다. 09-24 실측: 영문 라벨은 번역을 안 거쳐 "B2C"·"B2B"·
#: "Concept Graph" 가 그대로 검색어가 됐고, "B2C" 에 당뇨 선별 B2C 모델 논문, "Concept Graph" 에 수술 영상 논문이 왔다.
QUERY_MIN_TOKENS = 3
#: 붙일 주제 토큰 최대 수 (루트 개념 + 상위 weight 개념의 영문 라벨에서, 자기 자신 빼고).
QUERY_TOPIC_TOKENS = 5
#: 검색어 토큰을 셀 때 뺄 기능어.
_QUERY_FILLER = {"a", "an", "the", "of", "and", "or", "for", "in", "on", "to", "with", "by", "vs"}
_QUERY_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]*")

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


def _topic_nodes(graph: ConceptGraph) -> list[ConceptNode]:
    """발표 주제를 말하는 개념 — **core 개념만**(얕은 순, 같으면 weight 순). core 가 하나도 없을 때만 루트 + 상위 weight 3개.
    weight 만 보면 지엽이 올라온다: 09-24 실측에서 수익모델 자료의 B2C·B2B·SaaS(weight 1.0, support)가 주제로 뽑혀
    "B2C" 검색어에 "B2B SaaS" 가 붙었고, 전자상거래 논문이 관련성 검사를 통과했다. 주제는 core 가 말한다."""
    core = sorted((n for n in graph.nodes if n.importance == "core"), key=lambda n: (n.depth, -n.weight, n.id))
    roots = [n for n in graph.nodes if n.depth == 1] or graph.nodes[:1]
    tops = sorted(graph.nodes, key=lambda n: -n.weight)[:3]
    out: list[ConceptNode] = []
    for n in core or (*roots, *tops):
        if n.label and n.label not in (m.label for m in out):
            out.append(n)
    return out


def _topic_line(graph: ConceptGraph) -> str:
    """발표 주제 한 줄 — 검색어가 다른 분야로 새지 않게 번역 프롬프트에 싣는다. 루트 개념 + 상위 3개 이름."""
    roots = [n for n in graph.nodes if n.depth == 1] or graph.nodes[:1]
    names = [n.label for n in _topic_nodes(graph)]
    head = roots[0].summary if roots and roots[0].summary else ""
    return " · ".join(names[:4]) + (f" — {head[:80]}" if head else "")


def _query_tokens(text: str) -> list[str]:
    """검색어의 내용 토큰 (기능어 뺀 영숫자 낱말, 원래 대소문자)."""
    return [t for t in _QUERY_TOKEN_RE.findall(text or "") if t.lower() not in _QUERY_FILLER]


def _topic_tokens_for(node: ConceptNode, topic_nodes: list[ConceptNode], query: str) -> list[str]:
    """이 개념의 검색어에 붙일 주제 토큰. 영문 라벨만, 자기 자신·검색어에 이미 있는 낱말은 빼고, 최대 QUERY_TOPIC_TOKENS 개.
    라벨은 **통째로** 붙인다 — "Slide-Speech Alignment" 를 "Slide" 로 자르면 뜻이 없는 낱말이 검색어가 된다. 다 안 들어가면 그 라벨은 건너뛴다."""
    have = {t.lower() for t in _query_tokens(query)}
    out: list[str] = []
    for n in topic_nodes:
        if n.id == node.id or _needs_translation(n.label):
            continue
        toks = [t for t in _query_tokens(n.label) if t.lower() not in have]
        if not toks or len(out) + len(toks) > QUERY_TOPIC_TOKENS:
            continue
        out.extend(toks)
        have.update(t.lower() for t in toks)
        if len(out) >= QUERY_TOPIC_TOKENS:
            break
    return out


@dataclass
class _NodeQuery:
    """개념 하나의 검색어. topic 이 비어 있지 않으면 짧은 검색어에 주제 토큰을 붙인 것이다 (query = concept + " " + topic)."""
    node: ConceptNode
    query: str
    concept: str
    topic: str = ""


def _queries_for(nodes: list[ConceptNode], llm, llm_kwargs, topic: str = "",
                 topic_nodes: list[ConceptNode] | None = None) -> list[_NodeQuery]:
    """개념마다 검색어. 영문 라벨은 그대로, 한글은 번역. 내용 토큰이 QUERY_MIN_TOKENS 미만이면 주제 토큰을 붙인다
    (번역 프롬프트엔 이미 주제가 실리지만, 결과가 짧으면 같은 보강을 한다)."""
    plain: dict[str, str] = {}
    to_translate: list[tuple[str, str]] = []
    for n in nodes:
        if not _needs_translation(n.label):
            plain[n.id] = n.label.strip()
        else:
            desc = n.label + (f" — {n.summary}" if n.summary else "")
            to_translate.append((n.id, desc[:160]))
    translated = _translate_queries(to_translate, llm, llm_kwargs, topic)
    out: list[_NodeQuery] = []
    for n in nodes:
        q = plain.get(n.id) or translated.get(n.id) or _ascii_fallback(n.label, n.summary)
        if not q:
            continue
        extra = _topic_tokens_for(n, topic_nodes or [], q) if len(_query_tokens(q)) < QUERY_MIN_TOKENS else []
        topic_part = " ".join(extra)
        out.append(_NodeQuery(node=n, query=f"{q} {topic_part}" if topic_part else q, concept=q, topic=topic_part))
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


def _shares(want: set[str], have: set[str]) -> bool:
    return not want or len(want & have) >= RELEVANCE_SHARED_MIN


def _relevant(hit: PaperRef, query: str, topic: str = "") -> bool:
    """검색 결과가 검색어와 낱말(어간)을 RELEVANCE_SHARED_MIN 개 이상 나누는가. 검색어에 낱말이 없으면 참 (볼 것이 없다).

    topic 을 주면(짧은 검색어에 주제 토큰을 붙인 경우) query 는 **개념 부분**이고, 개념 낱말과 주제 낱말을 **각각**
    나눠야 남는다 — "B2C" 만 맞는 당뇨 선별 B2C 모델 논문은 presentation·coaching 이 없어 떨어진다."""
    have = _word_stems(hit.title) | _word_stems(hit.abstract)
    if not topic:
        return _shares(_word_stems(query), have)
    return _shares(_word_stems(query), have) and _shares(_word_stems(topic) - _word_stems(query), have)


def _dropped_note(n: int) -> str:
    return f"관련성 없음 {n}건 버림" if n else ""


def _join_notes(*notes: str) -> str:
    return " · ".join(n for n in notes if n)


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
    node_queries = _queries_for(_pick_nodes(graph, node_max), llm, llm_kwargs, _topic_line(graph), _topic_nodes(graph))
    for nq in node_queries:
        jobs.append((f"node:{nq.node.id}", (lambda q=nq.query: provider.search(q, limit=per_node))))
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
    dropped = 0
    for nq in node_queries:
        node = nq.node
        for hit in results.get(f"node:{node.id}") or []:
            # 검색어와 낱말 하나 안 나누는 결과는 버린다 — deck 과 겹치는지 보기 **전에** (엉뚱한 개념을 deck 에 붙이지 않게).
            # 보강된 검색어면 개념 낱말·주제 낱말을 각각 나눠야 한다. 다 떨어지면 그 개념은 문헌 없이 간다 (다른 논문을 끌어오지 않는다).
            if not _relevant(hit, nq.concept, nq.topic):
                dropped += 1
                continue
            hit.query = hit.query or nq.query      # 디버깅용 — 실제로 보낸(보강된) 검색어
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
    note = _join_notes(note, _dropped_note(dropped))
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
    hits = results.get("q") or []
    refs = [r for r in hits if _relevant(r, search_q)]
    note = _join_notes(note, _dropped_note(len(hits) - len(refs)))
    for r in refs:
        r.query = search_q
    _assign_ids(refs, "s")
    if not refs and not note:
        note = "검색 결과 없음"
    return PaperDoc(file_name="", refs=refs, provider=provider.name, note=note)
