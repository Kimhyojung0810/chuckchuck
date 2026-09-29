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

09-30 감사 (docs/review/2026-09-29_QA_근거검증/redteam/report.md):
- G-A31 관련성 바닥이 기능어·학술 상투어(「연구·효과·방법」, research·impact·effect)로 통과했다 — 한글 논문은 개념 라벨·요약의
  **아무 낱말 하나**만 초록에 있어도 붙었다. 이제 상투어를 뺀 **변별 낱말**로 본다: 한글 논문은 라벨의 낱말 하나를 포함해
  라벨·요약·근거 장 자료 줄의 낱말 둘 이상(그중 하나는 제목), 영문 논문은 검색어 변별 어간의 절반·두 개 이상(하나는 제목).
- G-A32 번역 응답을 id·이름으로 못 맞추면 **순서**로 붙였다 — LLM 이 순서를 바꾸거나 한 줄을 빠뜨리면 다른 개념의 검색어가
  붙어 엉뚱한 개념에 논문이 달렸다. 이제 id → 표기만 다른 이름 → (개념이 하나뿐일 때만) 그 하나. 못 맞춘 개념은 검색하지 않고
  `status` 에 까닭을 남긴다.
- G-A9 검색 한 번이 막혀도 전체가 서 있었고, 부분 실패(한 통로 429)는 성공처럼 보였다 — 이제 시간 예산(PAPER_BUDGET_SEC) 안에
  받은 것만 쓰고, 개념·자료 인용·통로마다 사정을 `PaperDoc.status` 에 싣는다. 요청 한도는 통로 쪽(scholar_impl.LANES)이 지킨다.
"""

from __future__ import annotations

import contextvars
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from ._deck_claims import content_stems
from ._evidence import citation_lines
from ._json_text import extract_json_object
from .contracts import (
    MEMORY_SAME_NAME,
    PAPER_NODE_MAX,
    PAPER_PER_NODE,
    PAPER_SEARCH_MAX,
    ConceptGraph,
    ConceptNode,
    PaperDoc,
    PaperRef,
    SlideDoc,
    memory_similarity,
)
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm
from .providers.scholar_base import ScholarProvider, deadline_scope, dominant_state, status_of_error, status_rows
from .providers.scholar_impl import get_scholar, word_stem_seq, word_stems

#: 검색을 동시에 몇 개 띄울지. 통로마다의 동시 요청 수·간격은 scholar_impl.LANES 가 따로 지킨다 (arXiv 는 하나씩 3초 간격).
SEARCH_WORKERS = 4
#: build_papers 한 번의 검색 시간 예산 (초). 브리지는 PAPERS_DEADLINE_SEC(6초)만 기다리고 나머지는 뒤에서 마저 해 캐시를 채운다 —
#: 이 예산이 그 「뒤에서」 의 끝이다. 넘긴 검색은 timeout·not_searched 로 status 에 남는다. 09-30 G-A9: 막힌 통로 하나가 ~60초.
PAPER_BUDGET_SEC = float(os.environ.get("CHUCKCHUCK_PAPER_BUDGET_SEC", "20") or 20)
#: 예산이 끝난 뒤 막 끝나는 요청을 거둘 여유 (초).
_BUDGET_GRACE_SEC = 0.5
#: 자료 인용(deck)을 검색으로 되찾아 DOI·초록을 채울 최대 개수. 참고문헌이 30개여도 다 안 간다.
RESOLVE_DECK_MAX = int(os.environ.get("CHUCKCHUCK_PAPER_RESOLVE_MAX", "5"))
#: 되찾은 검색 결과가 자료의 제목과 이만큼 겹쳐야 같은 논문으로 본다 (토큰 Jaccard).
RESOLVE_MATCH_MIN = 0.6
#: 검색 결과(scholar hit)의 제목+초록 어간이 검색어 어간과 최소 이만큼 겹쳐야 남긴다. 어간은 provider 의 순위 매기기와
#: 같은 것(소문자 · 기능어·학술 상투어 제거 · 복수/진행형 꼬리 뗀 앞 5글자)이다. provider 가 `rank_refs` 로 이미 거르지만, 그 검사는
#: provider 마다 따로 부르는 것이라 새 통로·가짜 통로가 빠뜨리면 그대로 서가에 올라간다 — f24 가 마지막에 한 번 더 본다.
#: 2026-09-24 실측: "B2B·B2C 수익모델" 개념에 임신성 당뇨(GDM) 논문이 붙어 질문 why 에 들어갔다.
RELEVANCE_SHARED_MIN = 1
#: 검색어의 내용 토큰이 이보다 적으면 발표 주제 토큰을 붙인다. 09-24 실측: 영문 라벨은 번역을 안 거쳐 "B2C"·"B2B"·
#: "Concept Graph" 가 그대로 검색어가 됐고, "B2C" 에 당뇨 선별 B2C 모델 논문, "Concept Graph" 에 수술 영상 논문이 왔다.
QUERY_MIN_TOKENS = 3
#: 붙일 주제 토큰 최대 수 (루트 개념 + 상위 weight 개념의 영문 라벨에서, 자기 자신 빼고).
QUERY_TOPIC_TOKENS = 5
#: 번역이 안 된 한글 개념을 라벨·요약의 영문 낱말로 검색하려면 변별 어간이 이만큼은 있어야 한다 ("RAG LLM" 은 되고 "LED" 하나는 안 된다).
ASCII_FALLBACK_MIN_STEMS = 2
#: 검색어 토큰을 셀 때 뺄 기능어.
_QUERY_FILLER = {"a", "an", "the", "of", "and", "or", "for", "in", "on", "to", "with", "by", "vs"}
_QUERY_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]*")

QUERY_SYSTEM_PROMPT = """당신은 학술 검색 사서다.
발표 자료에서 뽑은 개념 목록을 받아, 개념마다 **영어 학술 검색어** 하나를 만든다.

- query: 3~7 단어의 영어 명사구. 학술 데이터베이스(OpenAlex 등)에 그대로 넣을 검색어다.
  개념의 뜻을 영어 학술 용어로 옮기되, **'발표 주제' 의 맥락 낱말을 반드시 포함**해서 다른 분야의
  논문이 걸리지 않게 하라. "매장 동선" 을 그냥 "store layout" 으로 옮기면 건축·물류 논문이
  온다 — 주제가 카페 재방문이면 "cafe store layout customer revisit" 처럼 쓴다.
  한국어·따옴표·불리언 연산자를 쓰지 마라.
  (예: 주제 "카페 재방문" · 개념 "대기 시간" → "cafe waiting time customer satisfaction")
- node_id 는 개념 목록의 괄호 안 id 를 **글자 그대로** 옮긴다. label 은 개념 이름 그대로.
  예시의 id 를 베끼지 마라 — 목록에 없는 id 는 버려진다.
- 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마 (id·label 은 목록의 것):
{ "queries": [ { "node_id": "<목록의 id>", "label": "<목록의 개념 이름>", "query": "cafe waiting time customer satisfaction" } ] }
"""

_HANGUL_RE = re.compile(r"[가-힣]")
_HANGUL_ONLY_RE = re.compile(r"[가-힣]+")
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{2,}")
_WS_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# 검색어 — 영문은 그대로, 한글은 LLM 1콜 (못 맞춘 개념은 영문 낱말이 넉넉할 때만 그것으로, 아니면 검색 안 함)
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


def _label_of(text: str) -> str:
    """번역 목록 한 줄 「이름 — 요약」 의 이름."""
    return str(text or "").split(" — ", 1)[0].strip()


def _row_owner(row: dict, items: list[tuple[str, str]], taken: set[str]) -> str:
    """
    번역 응답 한 줄의 주인 개념 id. ① 목록의 id 그대로 ② 표기만 다른 이름(조사·띄어쓰기 — memory_similarity 가 같은 이름으로 보는 것)
    이 **하나**만 맞을 때. 못 맞추면 "" — 순서로 짐작하지 않는다 (09-30 G-A32: LLM 이 순서를 바꾸면 다른 개념의 검색어가 붙었다).
    """
    nid = str(row.get("node_id", "") or "")
    if nid and nid not in taken and any(nid == i for i, _ in items):
        return nid
    label = _label_of(str(row.get("label", "") or ""))
    if label:
        owners = [i for i, text in items if i not in taken and memory_similarity(label, _label_of(text)) >= MEMORY_SAME_NAME]
        if len(owners) == 1:
            return owners[0]
    return ""


def _translate_queries(items: list[tuple[str, str]], llm: str | LLMProvider | None,
                       llm_kwargs: dict | None, topic: str = "") -> tuple[dict[str, str], dict[str, str]]:
    """
    [(id, 「한글 이름 — 요약」)] → ({id: 영어 검색어}, {id: 못 만든 까닭}). topic 은 발표 주제 한 줄.

    까닭: llm_error(LLM 실패) · unmatched(응답 줄을 어느 개념에도 못 맞춤) · no_row(이 개념의 줄이 없음) · hangul(검색어가 한글)
    · empty(빈 검색어). 2026-09-22 실측: Solar 가 예시의 "c1" 을 그대로 베껴 id 가 하나도 안 맞았다 — 이름으로 받는다.
    개념이 하나뿐이면(자유 검색) 응답 줄 하나도 그 개념의 것이다 — 모호하지 않다.
    """
    if not items:
        return {}, {}
    lines = [f"- ({i}) {text}" for i, text in items]
    head = f"[TASK] paper-queries\n\n발표 주제: {topic}\n\n" if topic else "[TASK] paper-queries\n\n"
    user = head + "## 개념 목록\n" + "\n".join(lines)
    try:
        engine = _engine(llm, llm_kwargs)
        raw = engine.complete(system=QUERY_SYSTEM_PROMPT, user=user, temperature=0.0,
                              max_tokens=1024, json_mode=True)
        data = extract_json_object(raw)
    except Exception as e:  # noqa: BLE001 — 검색어는 열쇠일 뿐. 실패는 까닭으로 남기고 그 개념은 검색하지 않는다
        sys.stderr.write(f"[f24] 검색어 번역 실패: {type(e).__name__}: {e}\n")
        return {}, {i: "llm_error" for i, _ in items}
    rows = [q for q in ((data.get("queries") or []) if isinstance(data, dict) else []) if isinstance(q, dict)]
    out: dict[str, str] = {}
    failed: dict[str, str] = {}
    taken: set[str] = set()
    unmatched = 0
    for row in rows:
        owner = _row_owner(row, items, taken)
        if not owner and len(items) == 1 and len(rows) == 1:
            owner = items[0][0]
        if not owner:
            unmatched += 1
            continue
        taken.add(owner)
        query = _WS_RE.sub(" ", str(row.get("query", "") or "")).strip()
        if not query:
            failed[owner] = "empty"
        elif _needs_translation(query):
            failed[owner] = "hangul"
        else:
            out[owner] = query[:120]
    for i, _ in items:
        if i not in out and i not in failed:
            failed[i] = "unmatched" if unmatched else "no_row"
    if unmatched:
        sys.stderr.write(f"[f24] 검색어 번역 응답 {unmatched}줄을 어느 개념에도 못 맞춤 — 순서로 붙이지 않는다\n")
    return out, failed


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
    """개념 하나의 검색어. topic 이 비어 있지 않으면 짧은 검색어에 주제 토큰을 붙인 것이다 (query = concept + " " + topic).
    source: label(영문 라벨 그대로) · llm(번역) · ascii(번역 실패 → 라벨·요약의 영문 낱말) · none(검색어 없음 — 검색 안 함)."""
    node: ConceptNode
    query: str
    concept: str
    topic: str = ""
    source: str = "label"
    reason: str = ""


def _queries_for(nodes: list[ConceptNode], llm, llm_kwargs, topic: str = "",
                 topic_nodes: list[ConceptNode] | None = None) -> list[_NodeQuery]:
    """개념마다 검색어 (검색어가 없는 개념도 source="none" 으로 돌려준다 — status 가 까닭을 말한다).
    영문 라벨은 그대로, 한글은 번역. 내용 토큰이 QUERY_MIN_TOKENS 미만이면 주제 토큰을 붙인다
    (번역 프롬프트엔 이미 주제가 실리지만, 결과가 짧으면 같은 보강을 한다)."""
    to_translate = [(n.id, (n.label + (f" — {n.summary}" if n.summary else ""))[:160])
                    for n in nodes if _needs_translation(n.label)]
    translated, failed = _translate_queries(to_translate, llm, llm_kwargs, topic)
    out: list[_NodeQuery] = []
    for n in nodes:
        reason = ""
        if not _needs_translation(n.label):
            q, source = n.label.strip(), "label"
        elif n.id in translated:
            q, source = translated[n.id], "llm"
        else:
            reason = failed.get(n.id, "no_row")
            fallback = _ascii_fallback(n.label, n.summary)
            enough = len(word_stems(fallback)) >= ASCII_FALLBACK_MIN_STEMS
            q, source = (fallback, "ascii") if enough else ("", "none")
        if not q:
            out.append(_NodeQuery(node=n, query="", concept="", source="none", reason=reason or "empty_label"))
            continue
        extra = _topic_tokens_for(n, topic_nodes or [], q) if len(_query_tokens(q)) < QUERY_MIN_TOKENS else []
        topic_part = " ".join(extra)
        out.append(_NodeQuery(node=n, query=f"{q} {topic_part}" if topic_part else q, concept=q, topic=topic_part,
                              source=source, reason=reason))
    return out


# ---------------------------------------------------------------------------
# 관련성 — 상투어를 뺀 변별 낱말로 (09-30 G-A31)
# ---------------------------------------------------------------------------

#: 한글 논문 제목·초록과 개념을 견줄 때 뺄 학술 상투어·기능어 (앞머리 일치). 어느 분야 논문에나 있는 말만 둔다 —
#: 09-30 G-A31: 「연구」「효과」「방법」 하나로 한글 논문이 개념에 붙었다. `_deck_claims.content_stems` 가 이미 빼는 말(발표·자료·방법 …)은 겹쳐도 된다.
_GENERIC_KO = (
    "연구", "효과", "분석", "결과", "영향", "사례", "기반", "활용", "방안", "개선", "중심", "통한", "위한", "대한", "관한",
    "따른", "의한", "관련", "문제", "현황", "필요", "이용", "사용", "제시", "제안", "검토", "고찰", "탐색", "모형", "모델",
    "요인", "특성", "차이", "변화", "수준", "이해", "의미", "역할", "과정", "관계", "비교", "평가", "측정", "조사", "실태",
    "적용", "동향", "전략", "시사", "방향", "가능", "측면", "관점", "요소", "기존", "최근", "국내", "해외", "대상", "중요",
    "주요", "논문", "학술", "저널", "학회", "개발", "설계", "구축", "구현", "제고", "증진", "향상", "탐구", "실증", "고려",
)
#: 한글 논문이 개념과 나눠야 할 변별 낱말 수 (라벨 낱말 하나 포함, 하나는 제목에).
KO_SHARED_MIN = 2
#: 관련성 바닥 — 검색어의 **변별 어간**(수량·순위 낱말·학술 상투어를 뺀 것) 가운데 제목+초록에 있어야 할 비율.
RELEVANCE_COVERAGE_MIN = 0.5
#: 영문 논문이 검색어와 나눠야 할 변별 어간 수 (검색어 어간이 이보다 적으면 전부).
EN_SHARED_MIN = 2
#: 검색어 변별 어간이 이만큼 이상이면 **이웃한 낱말 짝** 하나가 논문에서도 이웃해야 한다 (순서는 안 본다). 09-30 실측(09-29 기준선에
#: 기록된 실제 검색 결과 다시 판정): 흩어진 낱말만 맞은 논문 — 「깊은 수면」(deep sleep recovery)에 non-sleep deep rest 논문 둘,
#: 「수면 주기」(sleep cycle 90-110 minute rhythm)에 월경 주기(menstrual cycle) 논문 — 이 낱말 겹침 바닥을 다 넘었다.
#: 관련 논문은 개념의 두 낱말을 붙여 쓴다(REM sleep · glycemic load · individual investors).
PHRASE_MIN_STEMS = 3
#: 수량·순위를 말하는 낱말. 「top 25 percent」 같은 검색어에서 이것만 맞은 논문은 주제가 아니라 숫자 표현이 겹친 것이다.
#: 2026-09-29 기준선 §5-5: 「개인 투자자 상위 25% 수익률」 개념에 「The Top 1 Percent in International and Historical
#: Perspective」(소득 불평등)가 붙어, 질문 틀·골자(「노동 시장 협상 모델」)·채점 요소로 새어 나갔다. 겹친 낱말이
#: top·percent·return·investment 였다 — 개념의 머리말(individual investor)은 제목에 없었다.
_QUANTITY_WORDS = ("top", "bottom", "percent", "percentage", "percentile", "ratio", "rate", "average", "mean", "median",
                   "high", "higher", "highest", "low", "lower", "lowest", "number", "amount", "total", "level", "degree",
                   "first", "last", "increase", "decrease", "large", "small", "effect", "effects")


def _quantity_stems() -> set[str]:
    return word_stems(" ".join(_QUANTITY_WORDS))


def _ko_stems(text: str) -> set[str]:
    """한글 변별 줄기 — 조사를 떼고(_deck_claims.content_stems) 한글만, 학술 상투어는 뺀다."""
    return {s for s in content_stems(text) if _HANGUL_ONLY_RE.fullmatch(s) and len(s) >= 2 and not s.startswith(_GENERIC_KO)}


def _stem_in(stem: str, pool: set[str]) -> bool:
    """같은 낱말인가 — 같거나, 두 글자 이상끼리 앞머리 포함(「투자자」↔「투자」, 활용·합성 꼬리)."""
    return stem in pool or any(len(p) >= 2 and (p.startswith(stem) or stem.startswith(p)) for p in pool)


@dataclass(frozen=True)
class _Profile:
    """개념의 변별 낱말 — 라벨(label) 과 요약·근거 장 자료 줄(context). 한글 논문을 견줄 때 쓴다."""
    label: frozenset[str] = frozenset()
    context: frozenset[str] = frozenset()


def _slide_texts(slidedoc: SlideDoc | None) -> dict[int, str]:
    return {s.slide_no: s.raw_text or "" for s in (slidedoc.slides if slidedoc is not None else [])}


def _profile_of(node: ConceptNode, texts: dict[int, str] | None = None) -> _Profile:
    lines = " ".join((texts or {}).get(no, "") for no in node.slide_nos)
    label = frozenset(_ko_stems(node.label))
    return _Profile(label=label, context=frozenset(_ko_stems(f"{node.summary} {lines}") - label))


def _korean_floor(hit: PaperRef, profile: _Profile) -> bool:
    """한글 논문의 관련성 바닥 — 라벨 낱말 하나를 포함해 변별 낱말 KO_SHARED_MIN 개 이상, 그중 하나는 제목에. 변별 낱말이 없으면 버린다."""
    want = profile.label | profile.context
    if not want:
        return False
    have = _ko_stems(f"{hit.title} {hit.abstract}")
    shared = {w for w in want if _stem_in(w, have)}
    if profile.label and not shared & profile.label:
        return False
    title = _ko_stems(hit.title)
    return len(shared) >= KO_SHARED_MIN and any(_stem_in(w, title) for w in shared)


#: 짝을 견줄 때 쓰는 어간 앞머리 길이 — 거친 어간은 꼬리를 고르게 못 뗀다(slides→slid · slide→slide, scoring→scor · score→score).
_PAIR_PREFIX = 4


def _pairs(seq: list[str]) -> set[frozenset[str]]:
    """이웃한 어간 짝 (순서 없이, 앞 _PAIR_PREFIX 글자로). 같은 낱말끼리의 짝은 뺀다."""
    keys = [s[:_PAIR_PREFIX] for s in seq]
    return {frozenset(p) for p in zip(keys, keys[1:]) if p[0] != p[1]}


def _query_floor(hit: PaperRef, concept: str) -> bool:
    """
    영문 논문의 관련성 바닥 — 검색어의 변별 어간(수량·순위 낱말·학술 상투어 제외) 가운데 RELEVANCE_COVERAGE_MIN 이상,
    EN_SHARED_MIN 개 이상(검색어 어간이 더 적으면 전부)이 제목+초록에 있고, **제목**이 그중 하나 이상을 나눠야 한다.
    제목은 논문이 무엇에 관한 것인지 스스로 말하는 줄이다. 변별 어간이 PHRASE_MIN_STEMS 개 이상이면 이웃한 짝 하나도 맞아야 한다.
    변별 어간이 하나도 없으면(상투어뿐) 댈 근거가 없어 버린다.
    """
    quantity = _quantity_stems()
    seq = [s for s in word_stem_seq(concept) if s not in quantity]
    want = set(seq)
    if not want:
        return False
    have = word_stems(hit.title) | word_stems(hit.abstract)
    shared = want & have
    if not (len(shared) >= min(EN_SHARED_MIN, len(want)) and len(shared) / len(want) >= RELEVANCE_COVERAGE_MIN
            and bool(want & word_stems(hit.title))):
        return False
    if len(want) < PHRASE_MIN_STEMS:
        return True
    # 제목과 초록은 따로 센다 — 제목 끝 낱말과 초록 첫 낱말은 이웃이 아니다. 수량 낱말은 검색어에서처럼 양쪽 다 뺀다.
    def hit_pairs(text: str) -> set[frozenset[str]]:
        return _pairs([s for s in word_stem_seq(text) if s not in quantity])

    return bool(_pairs(seq) & (hit_pairs(hit.title) | hit_pairs(hit.abstract)))


def _above_floor(hit: PaperRef, concept: str, node: ConceptNode | None = None, profile: _Profile | None = None) -> bool:
    """
    개념 검색 결과의 관련성 바닥 (결정적). `_relevant` 는 검색어와 어간 **하나**만 나눠도 남긴다 — 그 위에 한 번 더 본다.
    한글 제목 논문은 개념(node 또는 profile)의 한글 변별 낱말로(`_korean_floor`), 영문 논문은 검색어의 변별 어간으로(`_query_floor`).
    """
    if _HANGUL_RE.search(hit.title or "") and (node is not None or profile is not None):
        return _korean_floor(hit, profile if profile is not None else _profile_of(node))
    return _query_floor(hit, concept)


def _shares(want: set[str], have: set[str]) -> bool:
    return not want or len(want & have) >= RELEVANCE_SHARED_MIN


def _relevant(hit: PaperRef, query: str, topic: str = "") -> bool:
    """검색 결과가 검색어와 변별 어간을 RELEVANCE_SHARED_MIN 개 이상 나누는가. 검색어에 변별 어간이 없으면 참 (볼 것이 없다).

    topic 을 주면(짧은 검색어에 주제 토큰을 붙인 경우) query 는 **개념 부분**이고, 개념 낱말과 주제 낱말을 **각각**
    나눠야 남는다 — "B2C" 만 맞는 당뇨 선별 B2C 모델 논문은 presentation·coaching 이 없어 떨어진다."""
    have = word_stems(hit.title) | word_stems(hit.abstract)
    if not topic:
        return _shares(word_stems(query), have)
    return _shares(word_stems(query), have) and _shares(word_stems(topic) - word_stems(query), have)


def _keeps(hit: PaperRef, nq: _NodeQuery, profile: _Profile) -> bool:
    """개념 검색 결과를 이 개념에 붙여도 되는가. 한글 논문은 개념의 한글 변별 낱말로만 — 영어 검색어와는 못 견준다."""
    if _HANGUL_RE.search(hit.title or ""):
        return _korean_floor(hit, profile)
    return _relevant(hit, nq.concept, nq.topic) and _query_floor(hit, nq.concept)


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


def _dropped_note(n: int) -> str:
    return f"관련성 없음 {n}건 버림" if n else ""


def _join_notes(*notes: str) -> str:
    return " · ".join(n for n in notes if n)


@dataclass
class _Outcome:
    """검색 한 건의 결과. state: ok · empty · (실패) failed · rate_limited · timeout · http · network · parse · error ·
    (참음) throttled · (예산) not_searched. providers 는 통로마다의 사정 (여럿을 합친 통로면 통로마다)."""
    refs: list[PaperRef] = field(default_factory=list)
    state: str = "ok"
    error: str = ""
    providers: list[dict] = field(default_factory=list)


def _outcome_of(provider: ScholarProvider, fut) -> _Outcome:
    if fut.cancelled():
        return _Outcome(state="not_searched", error="시간 예산이 끝나 시작 못 함",
                        providers=[{"provider": provider.name, "state": "not_searched"}])
    if not fut.done():
        return _Outcome(state="timeout", error="시간 예산 초과", providers=[{"provider": provider.name, "state": "timeout"}])
    try:
        got = fut.result()
    except Exception as e:  # noqa: BLE001 — provider 버그가 질문 생성을 막으면 안 된다 (까닭은 status 로 남긴다)
        row = status_of_error(provider.name, e)
        return _Outcome(state=row["state"], error=row["error"], providers=status_rows(getattr(e, "status", None)) or [row])
    refs = [r for r in (got or []) if isinstance(r, PaperRef)]   # None·엉뚱한 항목을 돌려주는 통로도 있다 (09-30 리뷰)
    rows = status_rows(getattr(got, "status", None)) or [{"provider": provider.name, "state": "ok" if refs else "empty"}]
    if refs:
        return _Outcome(refs=refs, state="ok", providers=rows)
    # 빈 결과라도 어느 통로가 묻지도 못했으면(실패·요청 한도) 「결과 없음」 이 아니다 — 그 까닭을 개념의 state 로 (09-30 리뷰)
    bad = [r for r in rows if r.get("state") not in ("ok", "empty")]
    state = dominant_state(bad) or "empty"
    return _Outcome(state=state, error=str(bad[0].get("error", "") or state)[:160] if bad else "", providers=rows)


def _run_jobs(provider: ScholarProvider, jobs: list[tuple[str, object]], budget: float | None) -> dict[str, _Outcome]:
    """
    [(key, 호출)] → {key: _Outcome}. SEARCH_WORKERS 개씩 동시에, **시간 예산 안에** — 넘긴 검색은 기다리지 않는다(timeout),
    시작도 못 한 검색은 취소한다(not_searched). 예산은 contextvars 로 통로까지 내려가 줄 서기·요청 시간 초과를 같이 묶는다.
    """
    if not jobs:
        return {}
    pool = ThreadPoolExecutor(max_workers=SEARCH_WORKERS)
    with deadline_scope(budget):
        futs = {key: pool.submit(contextvars.copy_context().run, call) for key, call in jobs}
    wait(list(futs.values()), timeout=None if budget is None else budget + _BUDGET_GRACE_SEC)
    pool.shutdown(wait=False, cancel_futures=True)
    return {key: _outcome_of(provider, fut) for key, fut in futs.items()}


def _assign_ids(refs: list[PaperRef], prefix: str) -> None:
    for i, r in enumerate(refs, 1):
        r.id = f"{prefix}{i:02d}"


# ---------------------------------------------------------------------------
# 사정 (status) · note
# ---------------------------------------------------------------------------

#: 번역이 안 된 까닭 (_translate_queries) — 다시 하면 나아질 수 있어 「검색 실패」 로 적는다 (브리지가 짧게만 든다).
_TRANSLATION_FAILURES = frozenset({"llm_error", "unmatched", "no_row", "hangul", "empty"})
#: 통로 사정 표의 칸 — 실패 계열(http·network·parse·error)은 failed 로 모은다.
_PROVIDER_COLUMNS = ("ok", "empty", "failed", "rate_limited", "timeout", "throttled", "not_searched")
_FAILED_STATES = frozenset({"failed", "http", "network", "parse", "error"})


def _provider_rows(outcomes: list[_Outcome]) -> list[dict]:
    table: dict[str, dict] = {}
    for oc in outcomes:
        for row in oc.providers:
            name = str(row.get("provider", "") or "?")
            state = str(row.get("state", "") or "failed")
            col = "failed" if state in _FAILED_STATES else state
            t = table.setdefault(name, {"kind": "provider", "provider": name, "calls": 0,
                                        **{c: 0 for c in _PROVIDER_COLUMNS}, "error": ""})
            t["calls"] += 1
            t[col if col in _PROVIDER_COLUMNS else "failed"] += 1
            if not t["error"] and row.get("error") and state not in ("ok", "empty"):
                t["error"] = str(row["error"])[:160]
    return [table[k] for k in sorted(table)]


def _note_of(provider: ScholarProvider, rows: list[dict], concept_rows: list[dict], dropped: int,
             resolve_rows: list[dict] | None = None) -> str:
    """사람이 읽을 한 줄. 실패가 있으면 「검색 실패」 를 넣는다 — 브리지(_papers_degraded)가 이 말로 폴백을 가려 짧게만 든다.
    요청 한도로 참은 것(throttled)은 실패가 아니다 (벤더가 막은 것이 아니고, 다시 해도 같은 줄에 선다)."""
    bits: list[str] = []
    resolve_rows = resolve_rows or []
    failed = [r for r in rows if r["failed"] or r["rate_limited"] or r["timeout"] or r["not_searched"]]
    if failed:
        parts = []
        for r in failed:
            n = r["failed"] + r["rate_limited"] + r["timeout"] + r["not_searched"]
            parts.append(f"{r['provider']} {n}/{r['calls']}" + (f" ({r['error'][:60]})" if r["error"] else ""))
        bits.append(f"{provider.name} 검색 실패: " + ", ".join(parts))
    # 요청 한도로 아무 결과도 못 받은 검색(개념·자료 인용)은 다시 해야 한다 — 「검색 실패」 로 적어 브리지가 짧게만 든다 (09-30 리뷰:
    # arXiv 하나만 켠 설정에서 줄에 밀린 개념이 성공처럼 6시간 들고 보관돼 다시 검색되지 않았다). 다른 통로가 답한 검색 안의 참음은 알림만.
    unsearched = sum(1 for c in concept_rows + resolve_rows if c.get("state") == "throttled")
    throttled = sum(r["throttled"] for r in rows)
    if unsearched:
        bits.append(f"요청 한도로 {unsearched}건 검색 실패 — 다음 요청에서 다시")
    elif throttled:
        bits.append(f"요청 한도로 {throttled}건 건너뜀")
    untranslated = [c for c in concept_rows if c["reason"] in _TRANSLATION_FAILURES]
    if untranslated:
        by_ascii = sum(1 for c in untranslated if c["query_source"] == "ascii")
        bits.append(f"검색어 번역 실패로 개념 {len(untranslated) - by_ascii}개 검색 실패"
                    + (f"·{by_ascii}개는 영문 낱말로 검색" if by_ascii else ""))
    return _join_notes(*bits, _dropped_note(dropped))


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------

def _fill_deck(resolvable: list[PaperRef], outcomes: dict[str, _Outcome]) -> list[dict]:
    """① deck 되찾기 — 같은 논문일 때만 채운다. kind 는 deck 그대로 (자료가 인용한 사실이 근거다)."""
    rows = []
    for i, ref in enumerate(resolvable):
        oc = outcomes.get(f"resolve:{i}") or _Outcome(state="not_searched")
        hit = oc.refs[0] if oc.refs else None
        state = oc.state if oc.state != "ok" else ("ok" if hit is not None and _same_paper(ref, hit) else "not_found")
        if state == "ok":
            ref.title = ref.title or hit.title
            ref.doi = ref.doi or hit.doi
            ref.url = ref.url or hit.url
            ref.venue = ref.venue or hit.venue
            ref.abstract = ref.abstract or hit.abstract
            ref.cited_by = hit.cited_by
            if len(hit.authors) > len(ref.authors):
                ref.authors = hit.authors
        rows.append({"kind": "resolve", "cite_key": ref.cite_key, "state": "not_found" if state == "empty" else state})
    return rows


def _attach(node_queries: list[_NodeQuery], outcomes: dict[str, _Outcome], deck: list[PaperRef],
            profiles: dict[str, _Profile]) -> tuple[list[PaperRef], list[dict], int]:
    """② 개념별 검색 결과를 관련성 바닥으로 거르고 붙인다. deck 과 겹치면 deck 에 node_ids 만 더한다 → (검색 문헌, 개념 사정, 버린 수)."""
    seen = {_dedup_key(r): r for r in deck}
    scholar_refs: list[PaperRef] = []
    rows: list[dict] = []
    dropped_all = 0
    for nq in node_queries:
        node = nq.node
        row = {"kind": "concept", "node_id": node.id, "label": node.label, "query": nq.query,
               "query_source": nq.source, "state": "no_query", "kept": 0, "dropped": 0, "reason": nq.reason}
        rows.append(row)
        if not nq.query:
            continue
        oc = outcomes.get(f"node:{node.id}") or _Outcome(state="not_searched")
        row["state"] = oc.state
        if oc.error:
            row["reason"] = row["reason"] or oc.error[:160]
        for hit in oc.refs:
            # 관련성 바닥을 deck 과 겹치는지 보기 **전에** (엉뚱한 개념을 deck 에 붙이지 않게). 다 떨어지면 그 개념은 문헌 없이 간다.
            if not _keeps(hit, nq, profiles[node.id]):
                row["dropped"] += 1
                continue
            row["kept"] += 1
            hit.query = hit.query or nq.query      # 디버깅용 — 실제로 보낸(보강된) 검색어
            key = _dedup_key(hit)
            if key in seen:
                if node.id not in seen[key].node_ids:
                    seen[key].node_ids.append(node.id)
                continue
            hit.node_ids = [node.id]
            seen[key] = hit
            scholar_refs.append(hit)
        dropped_all += row["dropped"]
    return scholar_refs, rows, dropped_all


def build_papers(
    graph: ConceptGraph | dict,
    slidedoc: SlideDoc | dict | None = None,
    *,
    scholar: str | ScholarProvider | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
    node_max: int = PAPER_NODE_MAX,
    per_node: int = PAPER_PER_NODE,
    budget_sec: float | None = None,
) -> PaperDoc:
    """
    ConceptGraph (+선택 SlideDoc) → PaperDoc. **트랙과 무관하니 세션에 한 번만** 만든다.

    - slidedoc 이 있으면 자료가 인용한 문헌(deck)을 먼저 뽑는다. 이건 검색이 꺼져 있어도 나온다.
    - scholar 가 none 이 아니면 ① deck 문헌을 제목으로 되찾아 DOI·초록을 채우고
      ② 상위 `node_max` 개념마다 `per_node` 편을 검색해 붙인다 (`node_ids` 로 조인).
    - 같은 논문(DOI 또는 제목)은 하나로 합치고 node_ids 를 더한다.
    - 검색은 시간 예산(budget_sec, 기본 PAPER_BUDGET_SEC) 안에서만 — 받은 것만 쓰고 나머지는 status 에 까닭을 남긴다.
    - 검색 실패는 `note`(「검색 실패」)·`status` 에 남기고 deck 만으로 돌려준다. 예외를 밖으로 던지지 않는다.
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

    resolvable = [r for r in deck if r.title or r.doi][:RESOLVE_DECK_MAX]
    node_queries = _queries_for(_pick_nodes(graph, node_max), llm, llm_kwargs, _topic_line(graph), _topic_nodes(graph))
    jobs: list[tuple[str, object]] = [(f"resolve:{i}", (lambda r=ref: provider.resolve(r.title, r.doi)))
                                      for i, ref in enumerate(resolvable)]
    jobs += [(f"node:{nq.node.id}", (lambda q=nq.query: provider.search(q, limit=per_node))) for nq in node_queries if nq.query]
    outcomes = _run_jobs(provider, jobs, PAPER_BUDGET_SEC if budget_sec is None else budget_sec)

    resolve_rows = _fill_deck(resolvable, outcomes)
    texts = _slide_texts(slidedoc)
    profiles = {nq.node.id: _profile_of(nq.node, texts) for nq in node_queries}
    scholar_refs, concept_rows, dropped = _attach(node_queries, outcomes, deck, profiles)
    provider_rows = _provider_rows(list(outcomes.values()))

    _assign_ids(deck, "d")
    _assign_ids(scholar_refs, "s")
    note = _note_of(provider, provider_rows, concept_rows, dropped, resolve_rows)
    searched = [c for c in concept_rows if c["query"]]
    if not note and not scholar_refs and searched:
        note = "검색 결과 없음"
    if not node_queries and not deck:
        note = note or "검색어를 만들 수 없음(개념 없음)"
    return PaperDoc(file_name=graph.file_name, refs=deck + scholar_refs, provider=provider.name, note=note,
                    status=concept_rows + resolve_rows + provider_rows)


def search_papers(
    query: str,
    *,
    limit: int = PAPER_SEARCH_MAX,
    scholar: str | ScholarProvider | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
    budget_sec: float | None = None,
) -> PaperDoc:
    """
    자유 질문 → PaperDoc (전부 kind="scholar"). "이 주제의 수준 높은 논문을 바로 보여 줘" 용.

    한국어 질문이면 LLM 1콜로 영어 검색어를 만들고, 영문이면 그대로 검색한다.
    순위는 provider 가 매긴 품질 순(관련도·피인용·최근성)이다. 실패는 `note`·`status` 에 남긴다.
    """
    q = _WS_RE.sub(" ", query or "").strip()
    provider = _scholar(scholar)
    if not q:
        return PaperDoc(file_name="", provider=provider.name, note="검색어가 비어 있음")
    if provider.name == "none":
        return PaperDoc(file_name="", provider=provider.name, note="검색 꺼짐(SCHOLAR_PROVIDER=none)")

    search_q, source = q, "label"
    if _needs_translation(q):
        translated, _ = _translate_queries([("q", q[:200])], llm, llm_kwargs)
        search_q, source = (translated["q"], "llm") if translated.get("q") else (_ascii_fallback(q), "ascii")
        if not search_q:
            return PaperDoc(file_name="", provider=provider.name,
                            note="검색어를 영어로 만들지 못했어요 — 영어로 다시 물어봐 주세요")
    outcomes = _run_jobs(provider, [("q", (lambda: provider.search(search_q, limit=max(1, limit))))],
                         PAPER_BUDGET_SEC if budget_sec is None else budget_sec)
    oc = outcomes["q"]
    refs = [r for r in oc.refs if _relevant(r, search_q)]
    provider_rows = _provider_rows([oc])
    note = _note_of(provider, provider_rows, [], len(oc.refs) - len(refs))
    for r in refs:
        r.query = search_q
    _assign_ids(refs, "s")
    if not refs and not note:
        note = "검색 결과 없음"
    status = [{"kind": "concept", "node_id": "", "label": q[:80], "query": search_q, "query_source": source,
               "state": oc.state, "kept": len(refs), "dropped": len(oc.refs) - len(refs), "reason": oc.error[:160]}]
    return PaperDoc(file_name="", refs=refs, provider=provider.name, note=note, status=status + provider_rows)
