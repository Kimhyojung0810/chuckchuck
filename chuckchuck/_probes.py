"""
주장 그래프(F-26 ClaimDoc)에서 **질문거리(Probe)** 를 결정적으로 찾는 순수 함수입니다 (P3).
`_evidence.py` 와 같은 자리다 — 기능 모듈(fXX_*)이 아니라 유틸이라 F-08 이 import 해도
정책 위반이 아닙니다 (DEV_POLICY §4-1). contracts 타입만 받고 LLM 을 부르지 않습니다.

왜 따로 두나 (2026-09-29):
- 사용자가 "이 질문은 어떤 근거로 나왔는지" 물었는데 코드를 다시 돌려 보기 전엔 답할 수 없었다.
  질문이 **왜** 있는지를 기록한 곳이 없었다.
- 녹음 없이 자료만 올린 경로는 근거가 전부 core_weight 라, QA_TRACK_MIX 의 weak 자리가
  "약점" 이 아니라 weight 순으로 찼다. 자료 **안의** 긴장·빈틈을 코드가 찾아야 weak 자리가 뜻을 갖는다.
- 그래서 주장(원문 인용이 확인된 것) → 탐침(코드가 조립) → 질문(탐침에 묶임) 순으로 흐르게 한다.
  탐침의 각도·근거·템플릿 문장이 전부 여기서 나와서, 같은 그래프·주장이면 언제나 같은 탐침이 나온다.

    probes = derive_probes(graph, claims)          # list[Probe], 정렬돼 있다
"""

from __future__ import annotations

import re

from . import _claim_rules as R
from . import _deck_lines as DL
from . import _grounding as G
from ._evidence import clean_slide_text, is_question_line, noise_lines, page_marker_rows, strip_chart_descriptions
from ._match import contains_tokens, label_tokens, norm_tokens
from .contracts import (
    PROBE_KINDS,
    QA_TEXT_MAX,
    Claim,
    ClaimDoc,
    ClaimQuote,
    ConceptGraph,
    ConceptNode,
    Probe,
)

_KIND_RANK = {kind: i for i, kind in enumerate(PROBE_KINDS)}

#: 「X보다 …」 — 견주는 대상과 그 뒤 서술어 첫 낱말. f08 `_COMPARE_RE` 와 같은 꼴 (f08 을 import 하지 않으려고 따로 둔다).
_COMPARE_RE = re.compile(r"([가-힣A-Za-z]{1,12})보다\s+([가-힣]+)")

#: 서술어를 못 뽑았을 때. 「수면 시간보다 중요한 수면의 질」 처럼 비교 주장은 대부분 이 뜻이다.
_PRED_FALLBACK = "더 중요하다"

#: 단정 탐침 템플릿에 인용을 통째로 넣을 상한. 넘으면 인용 대신 「단정적으로 말했는데」 로 쓴다 —
#: 120자 인용을 문장에 박으면 QA_TEXT_MAX(200) 안에서 물음이 잘린다.
ABSOLUTE_QUOTE_MAX = 50


# ---------------------------------------------------------------------------
# 한국어 조사 — 템플릿이 라벨 뒤에 붙인다
# ---------------------------------------------------------------------------

def _batchim(word: str) -> bool:
    """마지막 글자에 받침이 있는가. 한글이 아니면(REM·AI) 받침 없음으로 본다 — 「AI가」 가 「AI이」 보다 자연스럽다."""
    ch = (word or "")[-1:]
    return bool(ch) and "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 != 0


def josa(word: str, with_batchim: str, without: str) -> str:
    """word + 알맞은 조사. josa("수면의 질", "이", "가") → "수면의 질이"."""
    return word + (with_batchim if _batchim(word) else without)


# ---------------------------------------------------------------------------
# 라벨 언급 — 질문 문장이 탐침의 개념을 실제로 부르는가
# ---------------------------------------------------------------------------

def mentions(text: str, label: str) -> bool:
    """
    문장이 이 라벨을 부르는가. 조사가 붙어도 같은 낱말로 본다 (`_match` — 한글 토큰은 포함 허용).
    라벨이 너무 짧아 토큰 대조를 못 하면(한 글자) 글자 그대로 찾는다.
    """
    tokens = label_tokens(label)
    if not tokens:
        return bool(label) and label in (text or "")
    return contains_tokens(norm_tokens(text), tokens)


def _related(a: str, b: str) -> bool:
    """
    두 라벨이 같은 개념을 가리키는가 — 한쪽 토큰열이 다른 쪽 안에 있거나("작업 시간" ⊇ "시간"),
    양·방향 수식어만 다르다("충분한 시간" = "시간 부족" — F-07 이 같은 개념을 두 노드로 둔 경우). 반의어(「매출 증가」↔「매출 감소」)는
    다른 개념이다 (`_claim_rules.same_concept`) — 긴장·비교에서 반대 쪽을 같은 요소로 읽지 않는다.
    """
    ta, tb = label_tokens(a), label_tokens(b)
    if not ta or not tb:
        return bool(a) and a == b
    return contains_tokens(ta, tb) or contains_tokens(tb, ta) or R.same_concept(a, b)


def _same_variable(a: str, b: str) -> bool:
    """
    해결·문제 짝을 볼 때의 「같은 개념」 — **극성은 보지 않는다** (`_claim_rules.same_variable`). 「매출 감소」 문제를 푸는 해결 주장은
    목적어를 「매출 증가」 로 적는다 — 반의어라서 같은 개념이 아니라고 보면 풀린 문제가 빈칸 탐침(unsolved)이 된다 (09-30 WP-C 요청).
    """
    ta, tb = label_tokens(a), label_tokens(b)
    if not ta or not tb:
        return bool(a) and a == b
    return contains_tokens(ta, tb) or contains_tokens(tb, ta) or R.same_variable(a, b)


# ---------------------------------------------------------------------------
# 탐침 찾기
# ---------------------------------------------------------------------------

def _evidence_of(*claims: Claim) -> list[ClaimQuote]:
    """주장들의 인용 합집합. 같은 (장, 문장) 은 한 번만, 주장 순서대로."""
    seen: set[tuple[int, str]] = set()
    out: list[ClaimQuote] = []
    for c in claims:
        for ev in c.evidence:
            key = (ev.slide_no, ev.quote)
            if ev.quote and key not in seen:
                seen.add(key)
                out.append(ClaimQuote(slide_no=ev.slide_no, quote=ev.quote))
    return out


def _compare_pred(compare: Claim, b_label: str) -> str:
    """
    비교 주장의 서술어를 「…하다」 꼴로. 인용 원문에서 「B보다 ○○한」 을 찾는다.
    「한」 으로 끝나는 것만 「하다」 로 바꾼다 — 「넓은」 을 「넓은는 건」 으로 만들지 않으려고 나머지는 폴백이다.
    """
    for text in [*(e.quote for e in compare.evidence), compare.text]:
        for m in _COMPARE_RE.finditer(text or ""):
            if not _related(m.group(1), b_label):
                continue
            pred = m.group(2)
            if pred.endswith("하다"):
                return pred
            if pred.endswith("한") and len(pred) > 1:
                return pred[:-1] + "하다"
    return _PRED_FALLBACK


def _short_quote(claim: Claim) -> str:
    """단정 탐침에 넣을 인용 — 가장 짧은 원문 인용, 상한을 넘으면 ""."""
    quotes = sorted((e.quote.strip() for e in claim.evidence if e.quote.strip()), key=len)
    return quotes[0] if quotes and len(quotes[0]) <= ABSOLUTE_QUOTE_MAX else ""


def _short_evidence(probe: Probe) -> str:
    """탐침 근거 가운데 가장 짧은 인용 (상한 안) — 주장 id 가 옛 것이라 주장을 못 찾을 때(캐시된 triage) 쓴다."""
    quotes = sorted((e.quote.strip() for e in probe.evidence if (e.quote or "").strip()), key=len)
    return quotes[0] if quotes and len(quotes[0]) <= ABSOLUTE_QUOTE_MAX else ""


def _pred_from_quotes(probe: Probe, b_label: str) -> str:
    """주장 없이(자료 구조 긴장) 비교 서술어를 탐침 인용에서 — 「B보다 ○○한」 → 「○○하다」."""
    for e in probe.evidence:
        for m in _COMPARE_RE.finditer(e.quote or ""):
            pred = m.group(2)
            if pred.endswith("하다"):
                return pred
            if pred.endswith("한") and len(pred) > 1:
                return pred[:-1] + "하다"
            if pred in ("더",):
                continue
    return _PRED_FALLBACK


def _tension(graph_by: dict[str, ConceptNode], claims: list[Claim]) -> list[Probe]:
    """compare(A>B) 와 compose(A⊃B) 가 함께 있다. B 는 compose 의 요소 id 이거나, 라벨이 요소 라벨과 겹친다."""
    out: list[Probe] = []
    composes = [c for c in claims if c.kind == "compose"]
    for cmp in (c for c in claims if c.kind == "compare"):
        a = cmp.subject_id
        for b in cmp.object_ids:
            b_label = graph_by[b].label if b in graph_by else ""
            for comp in (c for c in composes if c.subject_id == a):
                element = b if b in comp.object_ids else next(
                    (o for o in comp.object_ids if o in graph_by and _related(graph_by[o].label, b_label)), "")
                if not element:
                    continue
                el_label = graph_by[element].label
                a_label = graph_by[a].label
                said = cmp.evidence[0].quote if cmp.evidence else (cmp.text or f"{b_label}보다 {_compare_pred(cmp, b_label)}")
                out.append(Probe(
                    kind="tension",
                    node_ids=[a, element],
                    claim_ids=[cmp.id, comp.id],
                    angle=f"「{said}」{_quote_josa(said, '이라면서', '라면서')} {josa(el_label, '을', '를')} {a_label}의 요소로 둔다 — 두 말이 함께 성립하는 뜻을 묻는다",
                    evidence=_evidence_of(cmp, comp),
                ))
                break
    return out


def _is_problem_list(comp: Claim, graph_by: dict[str, ConceptNode]) -> bool:
    """
    compose 가 **문제 목록**인가 — 인용 줄이 문제 명사로 끝나는 제목(「해결해야 할 세 가지 문제」「…실패하는 이유」)이거나,
    요소 이름이 전부 문제 낱말(저하·부족·장벽·지연 …)이다. 식(「A = B × C」)은 구성 요소·해결 축이지 문제 목록이 아니다
    (09-29 벤치: 해결 축 식을 문제 목록으로 읽어 「처벌 강화는 어떻게 개선하나요?」 가 나왔다).
    """
    if any(R.is_formula(q.quote) for q in comp.evidence):
        return False
    if any(R.is_problem_head(q.quote) for q in comp.evidence):
        return True
    labels = [graph_by[o].label for o in comp.object_ids if o in graph_by]
    return len(labels) >= 2 and all(R.is_problem_label(x) for x in labels)


def _common_tokens(graph_by: dict[str, ConceptNode]) -> set[str]:
    """노드 이름 셋 중 하나 이상에 나오는 토큰 — 덱의 주제어(「OO 효과」「OO의 질」)라 짝 맞추기에 쓰지 않는다."""
    counts: dict[str, int] = {}
    for n in graph_by.values():
        for t in set(R.content_tokens(n.label)):
            counts[t] = counts.get(t, 0) + 1
    limit = max(3, len(graph_by) // 3)
    return {t for t, k in counts.items() if k >= limit}


def _shares_token(a: str, b: str, common: set[str]) -> bool:
    ta = [t for t in R.content_tokens(a) if t not in common]
    tb = [t for t in R.content_tokens(b) if t not in common]
    return any(R.tok_match(x, y) or R.tok_match(y, x) for x in ta for y in tb)


def _unsolved(graph_by: dict[str, ConceptNode], claims: list[Claim]) -> list[Probe]:
    """
    **문제 목록**(compose) 가운데 해결책이 안 닿은 문제. 코드가 구조로 가른다:

    - 문제 목록만 본다 (`_is_problem_list`). 식·조건 목록은 아니다.
    - 해결 장이 있어야 한다 — 목록 장 밖에 solve 주장이 하나 이상. 해결 장이 없는 발표에는 만들지 않는다.
    - 문제 하나가 풀렸다고 보는 경우: solve 의 objects 에 있다(같은 개념의 다른 이름 포함) / solve 인용 줄에 그 이름이
      나온다 / 해결 장에 나온 개념(solve 주어·그 장 노드)이 그 문제의 자식이거나 변별 낱말을 나눈다
      (「일정 자동 공유」 ↔ 「일정 불일치」). 짝을 넉넉히 잡을수록 오탐이 준다 — 빈 칸이 확실할 때만 묻는다.
    - 형제 중 적어도 하나는 풀렸어야 한다 (자료가 해결책을 내놓는 발표일 때만).
    """
    out: list[Probe] = []
    solves = [c for c in claims if c.kind == "solve"]
    common = _common_tokens(graph_by)
    for comp in (c for c in claims if c.kind == "compose" and _is_problem_list(c, graph_by)):
        items = [o for o in comp.object_ids if o in graph_by]
        list_slides = {q.slide_no for q in comp.evidence}
        fixes = [s for s in solves if any(q.slide_no not in list_slides for q in s.evidence)]
        if not fixes:
            continue
        fix_slides = {q.slide_no for s in fixes for q in s.evidence}
        fix_nodes = {s.subject_id for s in fixes} | {
            n.id for n in graph_by.values() if fix_slides & set(n.slide_nos or [])}
        # 문제 항목 자신과 그 겹친 이름(F-07 이 같은 개념을 두 노드로 둔 것 — 극성만 다른 이름도)은 해결 쪽 개념이 아니다
        fix_nodes = {n for n in fix_nodes - set(items)
                     if n in graph_by and not any(_same_variable(graph_by[n].label, graph_by[i].label) for i in items)}

        def solved_by(o: str) -> list[Claim]:
            label = graph_by[o].label
            return [s for s in fixes
                    if any(x == o or (x in graph_by and _same_variable(graph_by[x].label, label)) for x in s.object_ids)
                    or any(R.mentioned(label, q.quote) for q in s.evidence)]

        def solved(o: str) -> bool:
            label = graph_by[o].label
            return bool(solved_by(o)) or any(
                graph_by[n].parent_id == o or _shares_token(graph_by[n].label, label, common) for n in fix_nodes if n in graph_by)

        done = [o for o in items if solved(o)]
        if not done:
            continue
        sib = next((o for o in done if solved_by(o)), done[0])
        for e in items:
            if e in done:
                continue
            e_label, sib_label = graph_by[e].label, graph_by[sib].label
            out.append(Probe(
                kind="unsolved",
                node_ids=[e, sib],
                claim_ids=[comp.id, *(s.id for s in solved_by(sib))],
                angle=(f"{graph_by[comp.subject_id].label}의 요소 가운데 {sib_label}에는 해결책이 있는데 "
                       f"{josa(e_label, '을', '를')} 개선하는 방법은 자료에 없다 — {josa(e_label, '은', '는')} 어떻게 다루는지 묻는다"),
                evidence=_evidence_of(comp, *solved_by(sib)),
            ))
    return out


def _cause_nodes(c: Claim, graph_by: dict[str, ConceptNode]) -> list[str]:
    """
    인과 탐침의 대상 — 주어(원인)와, 인용 줄에 **이름이 나온** 결과 하나. 인용에 안 나온 결과를 붙이면
    「1인 가구 증가가 직장인에 영향을」 같은 자료에 없는 문장이 된다 (09-29 벤치). 결과가 안 나왔으면 주어만,
    주어도 안 나왔으면 [] (탐침을 버린다).
    """
    said = c.evidence[0].quote if c.evidence else ""
    s_label = graph_by[c.subject_id].label
    others = [graph_by[o].label for o in c.object_ids if o in graph_by]
    if not said or not R.mentioned(s_label, said, exclude=others):
        return []
    shown = [o for o in c.object_ids if o in graph_by and R.mentioned(graph_by[o].label, said, exclude=s_label)]
    return [c.subject_id, *shown[:1]]


def _unsupported_cause(graph_by: dict[str, ConceptNode], claims: list[Claim]) -> list[Probe]:
    """cause 주장인데 인용 줄(과 옆 줄)에 수치·출처가 없다 (has_support 는 F-26 코드가 줄 단위로 채운다)."""
    out: list[Probe] = []
    for c in claims:
        if c.kind != "cause" or c.has_support:
            continue
        nodes = _cause_nodes(c, graph_by)
        if not nodes:
            continue
        said = c.evidence[0].quote
        out.append(Probe(
            kind="unsupported_cause",
            node_ids=nodes,
            claim_ids=[c.id],
            angle=f"「{said}」는 인과를 말하지만 그 줄에 수치·출처가 없다 — 그렇게 볼 수 있는 근거를 묻는다",
            evidence=_evidence_of(c),
        ))
    return out


def _absolute_boundary(graph_by: dict[str, ConceptNode], claims: list[Claim]) -> list[Probe]:
    """
    단정("반드시·완전히·항상") — 그 말이 들어맞지 않는 경우나 조건을 묻는다.
    인용 줄에 **부정되지 않은** 단정 표지가 있고(「반드시 …는 아니다」 는 유보다 — F-26 이 거르지만 한 번 더), 그 단정이
    **따져 물을 주장**일 때만 (`_claim_rules.absolute_kind` — 09-30 WP-P2). 자기 자료에서 본 것(「…하나도 없었다」)·늘어놓은 것
    안에서 센 것·비용이 붙는 기제·정의는 반례를 물을 말이 아니다.

    각도(angle)는 프롬프트에 그대로 실린다 — 「경계」 같은 우리 말을 쓰면 LLM 이 질문에 옮긴다(09-30 standard: 「…주장의 경계는
    무엇인가요?」). 발표자에게 그대로 물을 수 있는 말로 쓴다.
    """
    out: list[Probe] = []
    for c in claims:
        if c.kind != "absolute":
            continue
        marked = [e for e in c.evidence if R.absolute_marker(e.quote) and R.contestable_absolute(e.quote)]
        if not marked:
            continue
        said = marked[0].quote
        out.append(Probe(
            kind="absolute_boundary",
            node_ids=[c.subject_id],
            claim_ids=[c.id],
            angle=f"「{said}」{_quote_josa(said, '은', '는')} 예외 없이 말한 문장이다 — 이 말이 들어맞지 않는 경우나 조건이 있는지 묻는다",
            evidence=_evidence_of(c),
        ))
    return out


def _joint(comp: Claim, claims: list[Claim]) -> bool:
    """compose 의 요소가 함께 필요하다고 자료가 말하는가 — compose 인용(F-26 이 그런 줄을 붙인다)이나 같은 장의 다른 인용."""
    slides = {q.slide_no for q in comp.evidence}
    quotes = [q.quote for q in comp.evidence] + [q.quote for c in claims for q in c.evidence if q.slide_no in slides]
    return any(R.both_needed(x) for x in quotes)


#: 자료가 요소 사이에 **순위·맞바꿈**을 말하는 표지 — 우선·먼저·더 중요·대신·상충·둘 중 …. 어느 분야에나 쓰는 한국어 문법 낱말만.
_RANKING_RE = re.compile(
    r"우선|먼저|더\s*중요|더\s*큰|보다|대신|트레이드\s*오프|trade-?off|상충|둘\s*중|희생|포기|맞바꾸|맞바꿔|균형|택해|택할|택하|"
    r"양자택일|반면|중요도|순위|비중", re.I)


def _ranked(x: str, y: str, comp: Claim, claims: list[Claim], graph_by: dict[str, ConceptNode]) -> bool:
    """
    자료가 형제 x·y 사이에 **순위나 맞바꿈을 스스로 말하는가** — 그럴 때만 「하나만 챙긴다면」 을 물을 수 있다.

    09-29 P5 최종 평가 문제 4: 형제 우선순위가 탐침 25개 중 7개였고, 자료에 없는 우선순위를 골자가 지어내거나(「정보 비대칭과
    신축 빌라 중…」) 「둘 다 동등」 을 말한 모범답이 partial 65 를 받았다. 식·목록의 항은 대개 **나란히** 둔 것이다.
    신호: x·y 를 **함께** 주어·목적어로 둔 비교 주장, 또는 식·목록 장이나 x·y 의 장에서 x·y 이름을 **둘 다** 부르는 인용 줄에 순위 표지.
    """
    pair = {x, y}
    if any(c.kind == "compare" and pair <= ({c.subject_id} | set(c.object_ids)) for c in claims):
        return True
    slides = {q.slide_no for q in comp.evidence} | set(graph_by[x].slide_nos or []) | set(graph_by[y].slide_nos or [])
    labels = [graph_by[x].label, graph_by[y].label]
    # **둘 사이의** 순위여야 한다 — 한쪽만 다른 개념과 견준 줄(「A보다 중요한 C」)은 형제 순위가 아니다 (loop2 dry-run).
    for c in claims:
        for q in c.evidence:
            # 이름은 **통째로** 나와야 한다 — 절반 겹침(R.mentioned)이면 덱 주제어(「수면 …」「매출 …」) 하나로 두 이름이 다 걸린다.
            if q.slide_no in slides and _RANKING_RE.search(q.quote) and all(R.mention_score(lab, q.quote) >= 1 for lab in labels):
                return True
    return False


def _sibling_priority(graph_by: dict[str, ConceptNode], claims: list[Claim]) -> list[Probe]:
    """
    같은 compose 의 형제 요소(그래프에서 부모가 같은 요소 둘 이상) — 하나만 챙길 수 있다면 어느 쪽인가.

    **대상은 형제 중 가장 무거운 요소다** (weight 내림차순 → compose 에 적힌 순서). compose 의 주어(A)로 하면
    A 에 이미 tension 이 있는 흔한 경우에 개념당 질문이 하나라 이 탐침이 늘 죽는다 — 요소에 두면
    트랙의 part 자리가 뜻 있는 각도를 얻는다. 둘째 노드는 그다음 무거운 형제. compose 하나에 최대 하나.

    자료가 「둘 다 필요하다」「하나만으로는 …」 라고 말한 compose 는 건너뛴다 — 자료가 부정한 선택을 강요하면
    골자가 자료에 없는 우선순위를 정답으로 가르친다 (09-29 벤치). 그리고 자료가 두 요소 사이에 순위·맞바꿈을 **스스로**
    말한 짝만 만든다(`_ranked`, 09-29 P5 최종 평가) — 나란히 둔 항에 순위를 묻지 않는다. 상한(SIBLING_MAX)은 그대로.
    """
    out: list[Probe] = []
    for comp in (c for c in claims if c.kind == "compose"):
        if _joint(comp, claims):
            continue
        by_parent: dict[str, list[str]] = {}
        for o in comp.object_ids:
            parent = graph_by[o].parent_id
            if parent is not None:
                by_parent.setdefault(parent, []).append(o)
        groups = sorted((g for g in by_parent.values() if len(g) >= 2), key=lambda g: (-len(g), comp.object_ids.index(g[0])))
        if not groups:
            continue
        order = {o: i for i, o in enumerate(comp.object_ids)}
        ranked = sorted(groups[0], key=lambda o: (-graph_by[o].weight, order[o]))
        # 자료가 순위·맞바꿈을 말한 짝만 — 무거운 순으로 첫 짝. 없으면 만들지 않는다 (09-29 P5 문제 4).
        pair = next(((a, b) for i, a in enumerate(ranked) for b in ranked[i + 1:] if _ranked(a, b, comp, claims, graph_by)), None)
        if pair is None:
            continue
        x, y = pair
        a_label = graph_by[comp.subject_id].label
        out.append(Probe(
            kind="sibling_priority",
            node_ids=[x, y],
            claim_ids=[comp.id],
            angle=(f"{a_label}의 요소 {graph_by[x].label}·{graph_by[y].label} 가운데 하나만 챙길 수 있다면 "
                   f"어느 쪽인지 — 요소 사이의 우선순위를 묻는다"),
            evidence=_evidence_of(comp),
        ))
    return out


def _usable(claims: list[Claim], graph_by: dict[str, ConceptNode]) -> list[Claim]:
    """그래프 밖 id 를 걷어낸 주장. 주어가 그래프 밖이면 버린다 (F-26 어댑터가 이미 거르지만 계약을 믿지 않고 한 번 더)."""
    out: list[Claim] = []
    for c in claims:
        if c.subject_id not in graph_by:
            continue
        objs = [o for o in c.object_ids if o in graph_by and o != c.subject_id]
        out.append(Claim(id=c.id, kind=c.kind, subject_id=c.subject_id, object_ids=objs, text=c.text,
                         evidence=list(c.evidence), has_support=c.has_support))
    return out


def as_claims(claims: ClaimDoc | dict | None) -> ClaimDoc | None:
    """
    dict 도 받는다. None 만 None 이다 — **빈 주장 문서는 빈 문서 그대로** 돌려준다.

    09-30 WP-Q2(WP-C 요청): 예전엔 주장이 하나도 없으면 None 으로 바꿔서, F-26 이 빈 문서를 낸 덱(식을 못 읽었거나 LLM 이
    주장을 못 낸 덱)은 F-08 `build_questions` 가 「주장을 안 돌린 호출」 로 보고 **자료 구조로 찾는 탐침**(비교 줄 + 식 줄의
    긴장, `structural_tensions`)까지 통째로 건너뛰었다. F-26 이 빈 문서를 내는 것은 실패가 아니라 결과다(c0ca80a). 주장이 없어서
    생기는 차이(주장 인용·주장 id)는 쓰는 쪽이 `doc.claims` 로 가른다.
    """
    if claims is None:
        return None
    if isinstance(claims, dict):
        claims = ClaimDoc.from_dict(claims)
    return claims


def derive_probes(graph: ConceptGraph, claims: ClaimDoc | dict | None,
                  slides: dict[int, str] | None = None) -> list[Probe]:
    """
    ConceptGraph + ClaimDoc (+ 선택 slides: 장 번호 → 원문) → 탐침 목록. 결정적이고 LLM 을 부르지 않는다.

    정렬: PROBE_KINDS 순서(= QA_SOURCES 우선순위) → 대상 노드의 그래프 순서 → 주장 id.
    같은 (종류, 대상) 은 하나만 남긴다 — 개념당 질문이 하나라 둘째는 쓸 자리가 없다.
    이 정렬 덕분에 `QaTriage.probe_for(node_id)` 가 그 노드의 **가장 우선인** 탐침을 돌려준다.

    slides 를 주면 (09-30 held-out 감사 C-01·M-05):
    - **자료 구조의 긴장**(`structural_tensions`) — 「X보다 중요한 Y」 줄과 「Y = … × X × …」 식 줄이 함께 있으면, F-26 이
      식을 못 읽었어도(캡션이 식 가운데 끼어 compose 주장이 빠졌다) 긴장 탐침을 세운다.
    - **덱 전체 대조**(`validate_probes`) — 해결책 빠짐(unsolved)은 형제 한 줄이 아니라 덱의 모든 해결 줄을 본다.
    안 주면 예전과 같다. 주장 문서가 비어도(F-26 이 아무 주장도 못 낸 덱) slides 가 있으면 자료 구조 탐침은 찾는다.
    """
    doc = as_claims(claims)
    has_claims = doc is not None and bool(doc.claims)
    if not graph.nodes or (not has_claims and not slides):
        return []
    graph_by = {n.id: n for n in graph.nodes}
    usable = _usable(doc.claims, graph_by) if has_claims else []
    found = [
        *_tension(graph_by, usable), *_unsolved(graph_by, usable), *_unsupported_cause(graph_by, usable),
        *_absolute_boundary(graph_by, usable), *_sibling_priority(graph_by, usable),
    ]
    if slides:
        lines = _deck_lines(slides, [n.label for n in graph.nodes])
        found += structural_tensions(graph, slides, found, lines=lines)
        found = validate_probes(found, graph, slides, lines=lines)
    node_order = {n.id: i for i, n in enumerate(graph.nodes)}
    found.sort(key=lambda p: (_KIND_RANK[p.kind], node_order.get(p.node_ids[0], len(node_order)), p.claim_ids))
    out: list[Probe] = []
    for p in found:
        # 같은 이름·같은 개념의 두 노드(F-07 이 겹쳐 둔 것)는 한 대상이다 — 같은 개념은 변수에 **극성까지** 본다
        # (`_same_target`: 「매출 증가」 와 「매출 감소」 는 다른 대상, 「충분한 시간」 과 「시간 부족」 은 같은 대상)
        label = graph_by[p.node_ids[0]].label
        if not any(q.kind == p.kind and _same_target(label, graph_by[q.node_ids[0]].label) for q in out):
            out.append(p)
    return _cap_sibling(out)


def _same_target(a: str, b: str) -> bool:
    """
    탐침 두 개가 한 대상인가 — 이름이 같거나(띄어쓰기·따옴표 무시) 같은 개념이다 (`_claim_rules.same_concept`: 같은 변수에
    극성이 반대가 아니다). 09-30 WP-Q2(WP-C 요청): 예전엔 변수(`concept_key`)만 봐서 「매출 증가」 의 단정 탐침과 「매출 감소」 의
    단정 탐침이 한 대상으로 합쳐져 뒤의 것이 사라졌다. 수식어 없는 이름(「시간」)·충족 짝(「충분한 시간」↔「시간 부족」)은 그대로 합친다.
    """
    return G.squash(a) == G.squash(b) or R.same_concept(a, b)


#: 형제 우선순위 탐침은 덱에 하나만 — 다른 탐침이 하나도 없을 때만 더 둔다. 목록마다 하나씩 나오면
#: 「A와 B 중 하나만」 질문이 트랙을 채운다 (09-29 벤치: 탐침 10개 중 3개).
SIBLING_MAX = 1


def _cap_sibling(probes: list[Probe]) -> list[Probe]:
    if all(p.kind == "sibling_priority" for p in probes):
        return probes
    kept, n = [], 0
    for p in probes:
        if p.kind == "sibling_priority":
            n += 1
            if n > SIBLING_MAX:
                continue
        kept.append(p)
    return kept


# ---------------------------------------------------------------------------
# 탐침 템플릿 — LLM 이 탐침 개념을 빼먹은 질문을 썼을 때 코드가 쓰는 문장 (P4)
# ---------------------------------------------------------------------------

def probe_question(probe: Probe, labels: dict[str, str], graph_by: dict[str, ConceptNode] | None = None,
                   claims: ClaimDoc | None = None) -> str:
    """
    탐침 종류별 결정적 질문 문장 (해요체 물음). 탐침의 개념 라벨이 전부 들어간다 — 같은 검사를 통과하는 문장이다.

    tension 은 `_undercut_question`(c6a1fa1) 과 같은 꼴이다: 「B도 A의 요소인데, A가 B보다 ○○하다는 건 어떤 뜻인가요?」.
    """
    ids = probe.node_ids
    lab = [labels.get(i, i) for i in ids]
    if probe.kind == "tension" and len(lab) >= 2:
        # 자료의 말 그대로 부른다 — 그래프 이름은 자료의 낱말과 다를 수 있다 (09-30 held-out 도서관: 식의 항 「대출 권수」 가 개념
        # 「대출 권수 감소」 에 붙어 「대출 권수 감소도 독서 경험의 요소인데」 가 됐다). 비교 줄에서 두 쪽을 못 읽으면 이름으로.
        big, part = tension_terms(probe)
        a, b = (big or lab[0]), (part or lab[1])
        compare = claims.claim(probe.claim_ids[0]) if claims is not None and probe.claim_ids else None
        pred = _compare_pred(compare, b) if compare is not None else _pred_from_quotes(probe, b)
        text = f"{b}도 {a}의 요소인데, {josa(a, '이', '가')} {b}보다 {pred}는 건 어떤 뜻인가요?"
    elif probe.kind == "unsolved" and len(lab) >= 2:
        text = f"{lab[1]}에는 해결책을 제시했는데, {josa(lab[0], '은', '는')} 어떻게 개선하나요?"
    elif probe.kind == "unsupported_cause":
        cause = claims.claim(probe.claim_ids[0]) if claims is not None and probe.claim_ids else None
        quote = _short_quote(cause) if cause is not None else ""
        quote = quote or _short_evidence(probe)
        if quote:
            # 인용 원문을 그대로 — 라벨로 문장을 지으면 자료에 없는 방향·목적어가 끼어든다 (09-29 벤치)
            q = quote.strip()
            text = f"「{q}」{_quote_josa(q, '이라고', '라고')} 했는데, 그렇게 볼 수 있는 근거는 무엇인가요?"
        elif len(lab) >= 2:
            text = f"{josa(lab[0], '이', '가')} {lab[1]}에 영향을 준다고 했는데, 그렇게 볼 수 있는 근거는 무엇인가요?"
        else:
            text = f"{lab[0]}에 대해 말한 원인과 결과는 어떤 근거로 볼 수 있나요?"
    elif probe.kind == "absolute_boundary":
        absolute = claims.claim(probe.claim_ids[0]) if claims is not None and probe.claim_ids else None
        quote = (_short_quote(absolute) if absolute is not None else "") or _short_evidence(probe)
        # 인용이 있으면 개념 이름을 머리에 달지 않는다 — 그래프 이름(「전세사기 완전 사라짐」)은 자료의 말이 아닐 수 있다.
        q = quote.strip()
        text = (f"「{q}」{_quote_josa(q, '이라고', '라고')} 했는데, 이 말이 들어맞지 않는 경우도 있나요?" if quote
                else f"{lab[0]}에 대해 단정적으로 말했는데, 이 말이 들어맞지 않는 경우도 있나요?")
    elif probe.kind == "sibling_priority" and len(lab) >= 2:
        parent = ""
        if graph_by is not None and ids[0] in graph_by:
            up = graph_by[ids[0]].parent_id
            parent = graph_by[up].label if up and up in graph_by else ""
        where = f"{parent}에는 " if parent else ""
        text = f"{josa(lab[0], '과', '와')} {lab[1]} 중 하나만 챙길 수 있다면, {where}어느 쪽이 더 중요한가요?"
    else:
        text = f"{lab[0]}에 대해 자료가 말한 것을 어떤 근거로 볼 수 있나요?"
    if len(text) <= QUESTION_TEXT_MAX:
        return text
    # 길면 **뒤를 자르지 않는다** — 09-30 레드팀(Q-C): 200자에서 잘려 물음표가 사라진 문장이 화면에 나갔다. 인용을 뺀 짧은 꼴로 바꾼다.
    short = _short_template(probe, lab)
    return short if len(short) <= QUESTION_TEXT_MAX else f"{lab[0]}에 대해 자료가 말한 것은 어디까지 맞나요?"


#: 질문 한 문장의 상한 — 화면 말풍선 두 줄 (09-30 held-out 감사 M-04: 120자를 넘는 한 문장 질문은 읽다가 놓친다).
QUESTION_TEXT_MAX = 120


def _short_template(probe: Probe, lab: list[str]) -> str:
    """인용을 뺀 짧은 탐침 문장 — 긴 인용·긴 라벨로 상한을 넘을 때."""
    a = lab[0]
    b = lab[1] if len(lab) >= 2 else ""
    if probe.kind == "tension" and b:
        return f"{b}도 {a}의 요소인데, {josa(a, '이', '가')} {b}보다 중요하다는 건 어떤 뜻인가요?"
    if probe.kind == "unsolved":
        return f"{josa(a, '은', '는')} 어떻게 개선하나요?"
    if probe.kind == "unsupported_cause":
        return f"{a}에 대해 말한 원인과 결과는 어떤 근거로 볼 수 있나요?"
    if probe.kind == "absolute_boundary":
        return f"{a}에 대해 단정적으로 말했는데, 들어맞지 않는 경우도 있나요?"
    if probe.kind == "sibling_priority" and b:
        return f"{josa(a, '과', '와')} {b} 중 하나만 챙길 수 있다면 어느 쪽인가요?"
    return f"{a}에 대해 자료가 말한 것은 어디까지 맞나요?"


#: 탐침 질문의 「왜 묻는지」 (화면에 나간다 — 해요체). angle 은 프롬프트용 한다체라 그대로 못 보여 준다.
_PROBE_WHY = {
    "tension": "자료 안의 두 표현이 서로 부딪혀서, 둘이 어떻게 함께 성립하는지 확인하는 질문이에요",
    "unsolved": "다른 요소에는 해결책을 냈는데 이 요소는 비어 있어서 묻는 질문이에요",
    "unsupported_cause": "원인과 결과를 말했지만 그 대목에 수치나 출처가 없어서 근거를 묻는 질문이에요",
    "absolute_boundary": "단정적으로 말한 대목이라 그 말이 통하지 않는 경우를 묻는 질문이에요",
    "sibling_priority": "나란히 둔 요소 사이에서 무엇이 더 중요한지 묻는 질문이에요",
}


def probe_why(probe: Probe) -> str:
    return _PROBE_WHY.get(probe.kind, _PROBE_WHY["tension"])


# ---------------------------------------------------------------------------
# 자료 구조로 찾는 긴장 · 덱 전체로 다시 보는 탐침 (09-30 held-out 감사 C-01·M-05)
# ---------------------------------------------------------------------------

#: 「X보다 (더) <형용사 관형형> Y」 제목꼴 · 「X보다 (더) <관형형> 것은 Y(입니다)」 · 「Y는 X보다 (더) <서술어>」 — 비교의 두 쪽.
_THAN_TITLE_RE = re.compile(
    r"(?P<x>[가-힣A-Za-z0-9·]+(?:\s[가-힣A-Za-z0-9·]+){0,2}?)보다\s+(?:더\s+|훨씬\s+)?(?P<p>[가-힣]{1,6}(?:한|은|인|운|른|큰|진|된|선|는))"
    r"\s+(?:것은\s+|건\s+)?(?P<y>[가-힣A-Za-z0-9·]+(?:\s[가-힣A-Za-z0-9·]+){0,2}?)(?:입니다|이다|예요|이에요|다)?[.!]?$")
_THAN_SENT_RE = re.compile(
    r"^(?P<y>[가-힣A-Za-z0-9·]+(?:\s[가-힣A-Za-z0-9·]+){0,2}?)(?:은|는|이|가)\s+(?P<x>[가-힣A-Za-z0-9·]+(?:\s[가-힣A-Za-z0-9·]+){0,2}?)보다\s+"
    r"(?:더\s+|훨씬\s+)?(?P<p>중요|크|큰|높|많|앞서|우선|넓)")


def compare_sides(line: str) -> tuple[str, str] | None:
    """
    비교 줄 → (작은 쪽, 큰 쪽) 명사구. 「X보다 중요한 Y」 는 (X, Y). 물음 줄·식 줄은 아니다.

    두 쪽의 **자리**는 이 파일의 꼴(짧은 명사구)로 찾고, **어느 쪽이 큰지**는 주장 쪽 잣대(`_claim_rules.compare_sides`)에 묻는다 —
    「X보다 적은 Y」「X보다 낮은 Y」 는 X 가 큰 쪽이다 (09-30 G-A1 이 F-26 에서 고친 것을 질문 쪽도 따른다, WP-Q2).
    """
    text = (line or "").strip()
    if not text or is_question_line(text) or R.is_formula(text):
        return None
    for rx in (_THAN_TITLE_RE, _THAN_SENT_RE):
        m = rx.search(text)
        if m:
            x, y = m.group("x").strip(), _COPULA_END_RE.sub("", m.group("y").strip()).strip()
            if x and y and x != y:
                return (y, x) if _reads_reversed(text, x, y) else (x, y)
    return None


def _reads_reversed(line: str, lesser: str, greater: str) -> bool:
    """주장 쪽 잣대가 이 줄의 큰 쪽을 lesser 로 읽는가 — 그 해석의 큰 쪽 구절이 lesser 를 품고 작은 쪽 구절이 greater 를 품는다."""
    def has(phrase: str, np_: str) -> bool:
        return contains_tokens(norm_tokens(phrase), label_tokens(np_) or norm_tokens(np_))

    for big, small in R.compare_sides(line):
        if has(big, greater) and not has(big, lesser):
            return False
        if has(big, lesser) and has(small, greater) and not has(big, greater):
            return True
    return False


#: 명사구 끝의 서술격 — 「…것은 독서 경험입니다」 의 「입니다」.
_COPULA_END_RE = re.compile(r"(?:입니다|이다|예요|이에요|이었다|였다)$")


def _formula_terms(line: str) -> tuple[str, list[str]] | None:
    """
    식 줄 → (좌변, 항 목록). 항은 주장 쪽과 **같은** 잣대로 나눈다 (`_claim_rules.formula_terms` — 「×·÷·+·*」 는 늘, 「x」「·」 는
    앞뒤를 띄운 낱자일 때만 연산). 09-30 WP-Q2: 이 파일만 붙인 가운뎃점(「기술·자본」)까지 나눠서 F-26 과 다른 항을 읽었다
    (09-30 G-A27 — 가운뎃점은 나열이다). 숫자만 있는 항(계수)은 뺀다.
    """
    sides = R.formula_sides(line)
    if not sides:
        return None
    parts = [p for p in R.formula_terms(sides[1]) if not re.fullmatch(r"[\d.,%]+", p)]
    return (sides[0].strip(), parts) if len(parts) >= 2 else None


def _content_part(phrase: str) -> list[str]:
    """
    구절의 **뜻을 싣는 낱말** — 머리말(`_claim_rules.head_token`)까지의 토큰. 머리 뒤에 붙은 가벼운 머리(「체계」「방식」)·양 수식어
    (「감소」「부족」)는 뺀다: 「예방 체계」 → [예방], 「대출 권수 감소」 → [대출, 권수], 「수면 시간」 → [수면, 시간].
    """
    toks = [t for t in norm_tokens(phrase) if len(t) >= 2]
    head = R.head_token(phrase)
    at = max((i for i, t in enumerate(toks) if head and t.startswith(head)), default=len(toks) - 1)
    return toks[: at + 1]


def _node_for(term: str, graph_by: dict[str, ConceptNode], slide_no: int = 0) -> ConceptNode | None:
    """
    자료의 낱말(식 항·비교 쪽)이 가리키는 개념 — 주장 쪽(F-26 `resolve_label`)과 같은 잣대로 고른다 (09-30 WP-Q2):

    1. 이름이 그 낱말과 같다 (띄어쓰기·따옴표 무시).
    2. 한쪽 토큰열이 다른 쪽 안에 이어서 든다 — **머리말이 통해야** 한다 (`head_compatible`: 「혈당 부하」 는 「혈당」 을 품지만
       머리는 「부하」 다). 반의어(「매출 증가」↔「매출 감소」)는 아니다.
    3. 그래도 없으면 낱말의 뜻 낱말(`_content_part` — 가벼운 머리를 뗀 것)이 전부 이름에 든다, 머리말이 통하고 반의어가 아니다
       (「예방 체계」 → 「사전 예방」). 09-30 WP-Q2: 그래프가 발표 주제를 자료와 다른 말로 지으면(「사전 예방」) 자료 구조 긴장이
       대상 노드를 못 찾아 F-26 이 빈 주장을 낸 덱에서 긴장 T1 이 사라졌다. 「수면 시간」 → 「작업 시간」 은 뜻 낱말 「수면」 이
       없어서 아니다.

    같은 차례 안에서는 극성이 같은 이름(「대출 권수」 에 「대출 권수 감소」 보다 「대출 권수」), 그 장에 걸친 이름, 길이가 비슷한 이름 순.
    """
    tt = label_tokens(term)
    if not tt:
        return None
    content = _content_part(term)
    pol = R.polarity(term)
    cands = []
    for n in graph_by.values():
        lt = label_tokens(n.label)
        if not lt:
            continue
        if G.squash(n.label) == G.squash(term):
            rank = 0
        elif R.antonyms(term, n.label) or not R.head_compatible(term, n.label):
            continue
        elif contains_tokens(tt, lt) or contains_tokens(lt, tt):
            rank = 1
        elif content and all(any(R.tok_match(x, c) or R.tok_match(c, x) for x in lt) for c in content):
            rank = 2
        else:
            continue
        cands.append((rank, R.polarity(n.label) != pol, slide_no not in (n.slide_nos or []), abs(len(lt) - len(tt)), n.id, n))
    return min(cands)[-1] if cands else None


def _deck_lines(slides: dict[int, str], labels: list[str]) -> list[tuple[int, str]]:
    """
    덱의 줄 (장, 줄) — **F-26 인용과 같은 줄 읽기** (`_deck_lines.read_lines`: 차트 설명 블록을 장 전체에서 먼저 걷고, 쪽 번호 꼴·
    글머리표만 있는 줄·자료 속 지시문을 빼고, 식 조각을 라벨로 잇되 캡션 물음은 항이 아니고 물음꼴 라벨로는 안 채우며, 그래도 열린
    식은 몇 줄 안의 항 같은 줄로 마저 채운다). 여기에 설문 보기·축 눈금(`_evidence.noise_lines`)만 더 뺀다 — 보기는 사실이 아니다.
    09-30 WP-Q2: 예전엔 이 파일만의 줄 읽기라 F-26 이 채운 식을 여기서는 「…×」 로 읽어 자료 구조 긴장을 놓칠 수 있었다.
    """
    out: list[tuple[int, str]] = []
    for no in sorted(slides):
        raw = strip_chart_descriptions(slides[no] or "")
        rows = raw.split("\n")
        cleaned = [clean_slide_text(x) for x in rows]
        # 보기·눈금만 먼저 뺀다 — 쪽 번호 꼴은 read_lines 가 F-26 과 같은 자리 셈(빈 줄 뺀 맨 앞·맨 끝)으로 뺀다
        noise, pages = noise_lines(raw), page_marker_rows(cleaned)
        kept = [x for k, x in enumerate(rows) if k in pages or x.strip().startswith("|") or cleaned[k].strip() not in noise]
        out += [(no, ln) for ln in DL.read_lines("\n".join(kept), clean_slide_text, labels=labels) if ln]
    return out


def structural_tensions(graph: ConceptGraph, slides: dict[int, str], existing: list[Probe] | None = None, *,
                        lines: list[tuple[int, str]] | None = None) -> list[Probe]:
    """
    「X보다 중요한 Y」 줄 + 「Y = … × X × …」 식 줄 → 긴장 탐침 (주장 그래프 없이, 자료 줄만으로).

    09-30 held-out(도서관): 1장 「대출 권수보다 더 중요한 것은 독서 경험입니다」 와 4장 식이 있는데, 식 가운데 캡션이 끼어
    F-26 이 식(compose)을 못 읽어 긴장 탐침이 없었다. 식은 F-26 과 같은 줄 읽기(`_deck_lines`)로 잇는다. 이미 같은 대상의 긴장이
    있으면 만들지 않는다. 대상 노드는 식의 좌변(Y)·항(X)에 맞는 개념(`_node_for` — F-26 과 같은 잣대) — 못 찾으면 만들지 않는다.
    F-26 이 빈 주장 문서를 낸 덱에서도 여기가 돈다 (`as_claims`). lines 는 `_deck_lines` 결과 (부르는 쪽이 이미 읽었으면 넘긴다).
    """
    graph_by = {n.id: n for n in graph.nodes}
    if lines is None:
        lines = _deck_lines(slides, [n.label for n in graph.nodes])
    have = {(p.node_ids[0], p.node_ids[1]) for p in existing or [] if p.kind == "tension" and len(p.node_ids) >= 2}
    have_targets = {p.node_ids[0] for p in existing or [] if p.kind == "tension"}
    out: list[Probe] = []
    for c_no, c_line in lines:
        sides = compare_sides(c_line)
        if sides is None:
            continue
        lesser, greater = sides
        for f_no, f_line in lines:
            parsed = _formula_terms(f_line)
            if parsed is None:
                continue
            lhs, terms = parsed
            if not _same_phrase(lhs, greater):
                continue
            term = next((t for t in terms if _same_phrase(t, lesser)), "")
            if not term:
                continue
            a = _node_for(lhs, graph_by, f_no) or _node_for(greater, graph_by, c_no)
            b = _node_for(term, graph_by, f_no) or _node_for(lesser, graph_by, c_no)
            if a is None or b is None or a.id == b.id or (a.id, b.id) in have or a.id in have_targets:
                continue
            have.add((a.id, b.id))
            out.append(Probe(
                kind="tension",
                node_ids=[a.id, b.id],
                claim_ids=[],
                angle=f"「{c_line}」{_quote_josa(c_line, '이라면서', '라면서')} {josa(term, '을', '를')} {lhs}의 요소로 둔다 — 두 말이 함께 성립하는 뜻을 묻는다",
                evidence=[ClaimQuote(slide_no=c_no, quote=c_line), ClaimQuote(slide_no=f_no, quote=f_line)],
            ))
            break
    return out


def _same_phrase(a: str, b: str) -> bool:
    """자료의 두 구절(식 좌변·항 ↔ 비교 쪽)이 같은 것을 부르는가 — 한쪽 토큰열이 다른 쪽에 이어서 들고 머리말이 통한다
    (`head_compatible`: 「혈당 부하」 ↔ 「혈당」 은 아니다 — F-26·F-07 과 같은 잣대)."""
    ta, tb = label_tokens(a), label_tokens(b)
    return bool(ta) and bool(tb) and (contains_tokens(ta, tb) or contains_tokens(tb, ta)) and R.head_compatible(a, b)


def solution_line(label: str, slides: dict[int, str], exclude_slides: set[int] | None = None,
                  labels: list[str] | None = None, *, strict: bool = False,
                  lines: list[tuple[int, str]] | None = None) -> tuple[int, str] | None:
    """
    덱 전체에서 이 개념의 **해결 줄** — 개념 이름과 해결 동사(줄이다·막다·낮추다·지원·도입 …)가 한 줄에 있다. 이름이 통째로
    나온 줄이 먼저, 없으면(strict 가 아니면) 변별 토큰의 절반 이상이 나온 줄. 문제 목록 장(exclude_slides)의 줄·식 줄은 문제나
    구성을 늘어놓은 것이라 뺀다 (09-30 전세 덱: 식 「예방 체계 = 정보 공개 × …」 의 「예방」 이 해결 줄로 잡혔다). 없으면 None.
    lines 는 `_deck_lines` 결과 (부르는 쪽이 이미 읽었으면 넘긴다).
    """
    cands = [(no, ln) for no, ln in (lines if lines is not None else _deck_lines(slides, labels or []))
             if not (exclude_slides and no in exclude_slides) and not is_question_line(ln) and not R.is_formula(ln)
             and G.REMEDY_VERB_RE.search(ln)]
    for need in ((1.0,) if strict else (1.0, R.MENTION_MIN)):
        for no, ln in cands:
            if R.mention_score(label, ln) >= need:
                return no, ln
    return None


def remedies_target(label: str, line: str) -> bool:
    """줄이 이 개념을 해결한다고 말하는가 (`_grounding.remedy_of` — 「자료에 없다」 대조와 같은 판단)."""
    return G.remedy_of(label, line)


def validate_probes(probes: list[Probe], graph: ConceptGraph, slides: dict[int, str], *,
                    lines: list[tuple[int, str]] | None = None) -> list[Probe]:
    """
    덱 전체로 탐침을 다시 본다 — 틀린 탐침은 버리고, 형제 근거는 실제 해결 줄로 바꾼다.

    - unsolved: 대상 문제가 **덱 어딘가의 해결 줄**에 나오면 해결된 것이다 — 버린다. 09-30 held-out(혈당 t10): 5장 첫 줄
      「… 순서로 먹으면 식후 졸림을 줄일 수 있습니다」 가 있는데 F-26 이 해결 주장을 다른 줄에 붙여 「식후 졸림」 이 빈칸 탐침이
      됐고, 골자가 「개선 방법은 자료에 제시되지 않았어요」 로 거짓을 가르쳤다.
    - unsolved 의 형제(해결된 쪽) 근거는 그 형제의 해결 줄로 — 「잦은 허기를 막습니다」 줄을 「졸림」 의 해결로 인용하지 않게.
    lines 는 `_deck_lines` 결과 — 탐침마다 덱을 다시 읽지 않는다.
    """
    graph_by = {n.id: n for n in graph.nodes}
    labels = [n.label for n in graph.nodes]
    if lines is None:
        lines = _deck_lines(slides, labels)
    out: list[Probe] = []
    for p in probes:
        if p.kind != "unsolved" or not p.node_ids or p.node_ids[0] not in graph_by:
            out.append(p)
            continue
        list_slides = {e.slide_no for e in p.evidence[:1]}
        target = graph_by[p.node_ids[0]].label
        if solution_line(target, slides, list_slides, labels, strict=True, lines=lines) is not None:
            continue
        # 근거가 나온 장(문제 목록일 수 있다)도 본다 — 개념이 해결 동사의 **대상**인 줄만 해결 줄로 친다 (`remedies_target`).
        # WP-Q 테스트: 한 장에 「좌석 부족은 주말에 심합니다」 와 「흡음재를 붙이면 소음을 줄일 수 있습니다」 가 같이 있으면 그 장을
        # 통째로 빼서 「소음」 이 빈칸 탐침으로 남았고, 골자가 「자료에는 소음을 개선하는 방법이 나와 있지 않아요」 로 거짓을 가르쳤다.
        if any(no in list_slides and not R.is_formula(ln) and not is_question_line(ln) and remedies_target(target, ln)
               for no, ln in lines):
            continue
        ev = list(p.evidence[:1])
        sib = p.node_ids[1] if len(p.node_ids) >= 2 and p.node_ids[1] in graph_by else ""
        fix = solution_line(graph_by[sib].label, slides, list_slides, labels, lines=lines) if sib else None
        if sib and fix is None:
            # 형제의 해결 줄이 근거와 같은 장에 있으면 그 줄 (개념이 해결 동사의 대상인 줄만 — `remedies_target`)
            fix = next(((no, ln) for no, ln in lines
                        if no in list_slides and not R.is_formula(ln) and not is_question_line(ln)
                        and remedies_target(graph_by[sib].label, ln)), None)
        if fix is not None:
            ev.append(ClaimQuote(slide_no=fix[0], quote=fix[1]))
        else:
            ev += [e for e in p.evidence[1:]]
        out.append(Probe(kind=p.kind, node_ids=list(p.node_ids), claim_ids=list(p.claim_ids), angle=p.angle, evidence=ev))
    return out


# ---------------------------------------------------------------------------
# 탐침 질문의 꼴 · 코드가 쓰는 골자와 힌트 (09-30 held-out C-01(a) · 레드팀 R9)
# ---------------------------------------------------------------------------

#: 종류별로 질문이 **그 탐침을 묻는다**고 볼 말. 탐침 개념 이름만 부르고 딴 것을 묻는 문장(「월 반복 매출이 구독자 수보다 더 중요한
#: 이유는?」 — 긴장이 아니라 한쪽 주장의 이유)은 탐침 질문이 아니다. 어느 발표에나 쓰는 물음 말만 둔다.
_SHAPE = {
    "tension": (re.compile(r"보다|더\s*중요|우선|앞서"),
                re.compile(r"요소|구성|포함|이루|곱|식|=|계산|들어가|함께\s*성립|모순|부딪|동시에|라면서|이면서|하면서도|어떤\s*뜻|무슨\s*뜻")),
    "unsolved": (re.compile(r"어떻게\s*(?:개선|해결|줄이|줄일|막|다루|대응|풀|보완|채우|낮추)|방법|방안|대책|해결책|대응책|계획"),),
    "unsupported_cause": (re.compile(r"근거|출처|수치|데이터|증거|뒷받침|입증|어떻게\s*알|확인할\s*수|자료로\s*보|볼\s*수\s*있"),),
    "absolute_boundary": (re.compile(r"경우|예외|한계|조건|경계|들어맞지|않을\s*수|아닐\s*수|안\s*될|못\s*할|반례|항상\s*그런|언제나\s*그런"),),
    "sibling_priority": (re.compile(r"어느\s*쪽|둘\s*중|하나만|우선|먼저|더\s*중요"),),
}
#: 탐침과 다른 것을 묻는 말 — 기제·경로·차이(「심리적·생리적 경로는 무엇이며, 졸림과는 어떻게 다른가요」).
_OFF_PROBE_RE = re.compile(r"메커니즘|기제|경로는|심리적|생리적|어떻게\s*다른|차이는|차이가\s*무엇")


def probe_shaped(text: str, probe: Probe) -> bool:
    """질문 문장이 이 탐침을 묻는 꼴인가 — 종류별 물음 말이 (다) 있고, 탐침과 다른 것을 묻는 말이 없다."""
    t = text or ""
    if not t.strip() or _OFF_PROBE_RE.search(t):
        return False
    return all(rx.search(t) for rx in _SHAPE.get(probe.kind, ()))


def tension_terms(probe: Probe) -> tuple[str, str]:
    """긴장 탐침의 (큰 쪽, 요소 쪽) 을 **자료의 말 그대로** — 비교 줄에서. 못 찾으면 ("", "")."""
    for e in probe.evidence:
        sides = compare_sides(e.quote)
        if sides:
            return sides[1], sides[0]
    return "", ""


def _q(text: str, limit: int = 50) -> str:
    t = " ".join((text or "").split()).rstrip(" .")
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def _quote_josa(quote: str, with_batchim: str, without: str) -> str:
    """「인용」 뒤 조사 — 인용 마지막 글자의 받침으로 (「…매출」과 · 「…시간」은)."""
    last = re.sub(r"[\s.…」”\"']+$", "", quote or "")[-1:]
    b = bool(last) and "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
    return with_batchim if b else without


#: 단정의 경계를 자료가 스스로 말한 줄 — 「…다를 수 있으니」「지역마다」「경우에 따라」「예외」. 어느 분야에나 쓰는 유보 말.
_HEDGE_RE = re.compile(r"다를\s*수|달라질\s*수|경우에\s*따라|사람마다|지역마다|개인에\s*따라|마다\s*다르|조건에\s*따라|않을\s*수\s*있|아닐\s*수\s*있")


def hedge_line(slides: dict[int, str] | None, near: set[int] | None = None, about: str = "") -> tuple[int, str] | None:
    """
    자료가 스스로 단 유보 줄 (가까운 장 먼저). 단정 탐침의 골자가 「자료에 적었듯 …」 으로 기댈 곳.

    about(단정 줄·대상 이름)을 주면 **그 단정의 조건일 수 있는 줄**만 — 가까운 장(HEDGE_NEAR 안)이거나 낱말을 나눈다.
    덱 끝의 「날씨에 따라 일정이 달라질 수 있습니다」 를 다른 장의 효과 단정의 조건이라고 말하면 모범답이 거짓이 된다 (WP-P2).
    """
    if not slides:
        return None
    cands = [(no, ln) for no, ln in _deck_lines(slides, []) if _HEDGE_RE.search(ln) and not is_question_line(ln)
             and not R.absolute_marker(ln, strong_only=True)]
    anchor = min(near) if near else 0
    if about and anchor:
        # 낱말은 **내용 명사**로 견준다 — 「있습니다」 같은 서술어 하나로 먼 장의 다른 이야기가 붙었다 (WP-P2 테스트)
        own = set(G.content_nouns(about))
        cands = [(no, ln) for no, ln in cands
                 if abs(no - anchor) <= HEDGE_NEAR
                 or any(R.tok_match(t, o) or R.tok_match(o, t) for t in G.content_nouns(ln) for o in own)]
    cands.sort(key=lambda x: (0 if near and x[0] in near else 1, abs(x[0] - anchor) if anchor else 0, x[0]))
    return cands[0] if cands else None


#: 단정 줄과 이만큼 떨어진 장까지의 유보 줄은 그 단정의 조건으로 읽는다 (낱말을 안 나눠도).
HEDGE_NEAR = 2
#: 유보 줄에서 「…수 있」 까지 — 조건을 해요체 한 절로 옮긴다(「개인에 따라 반응이 다를 수 있어요」).
_CAN_RE = re.compile(r"수\s*(?:도\s*)?있")


#: 유보 줄 머리의 접속 말 — 「다만 …」 을 「자료에 적었듯 다만 …」 으로 옮기면 어색하다.
_HEDGE_LEAD_RE = re.compile(r"^(?:다만|단|하지만|그러나|물론|또한|그리고)\s*,?\s*")


def _hedge_clause(line: str) -> str:
    """유보 줄 → 조건을 말하는 해요체 한 절. 「…수 있」 꼴이 아니면 "" (호출자가 인용으로)."""
    text = _HEDGE_LEAD_RE.sub("", " ".join((line or "").split()).rstrip(" ."))
    m = _CAN_RE.search(text)
    if not m or not _HEDGE_RE.search(text[: m.end()]) or len(text[: m.end()]) > HEDGE_CLAUSE_MAX:
        return ""
    return text[: m.end()] + "어요."


#: 조건 절의 상한 — 골자 한 칸(200자) 안에 단정 표지·장 번호·보완 말까지 들어가야 한다.
HEDGE_CLAUSE_MAX = 48


def probe_code_gist(probe: Probe, labels: dict[str, str], slides: dict[int, str] | None = None) -> str:
    """
    탐침 종류로 코드가 조립하는 기대 답 — LLM 골자 대신 **언제나** 이것을 쓴다 (09-30 held-out C-01(a)).
    held-out 5덱에서 탐침 질문의 LLM 골자는 해결책을 지어내거나(「신속한 반환 절차 도입이 필요해요」), 근거 없는 인과를 근거가
    있는 것처럼 풀었다(「…를 근거로 제시돼요」). 탐침 질문의 답은 **자료가 비어 있거나 단정했다는 사실**이 중심이라, 자료 줄
    인용과 정해진 틀로 쓴다. 인용은 탐침 근거(F-26 이 원문과 대조한 것)나 덱 전체 대조(`solution_line`·`hedge_line`)에서만 온다.

    **발표자가 그대로 말할 모범답**으로 쓴다 — 화면이 「이렇게 말하면 완성이에요 — 」 뒤에 싣는다. 09-30 standard 실측:
    「…점을 인정하고, 어떤 자료로 보강할지 말하는 게 답이에요」 처럼 채점 지시로 써서 모범답 칸이 지시문이 됐다.
    첫 절(`_gist_fragment` 가 자르는 곳)에 탐침의 열쇠 말(빈칸 탐침 이름·「수치」·「단정」·요소 이름)을 둔다 — 빈칸 칸이 그 말을 가린다.
    """
    ids = probe.node_ids
    lab = [labels.get(i, i) for i in ids]
    quotes = [e for e in probe.evidence if (e.quote or "").strip()]
    first = quotes[0] if quotes else None
    where = f"자료 {first.slide_no}장" if first and first.slide_no else "자료"
    if probe.kind == "tension" and len(quotes) >= 2:
        big, part = tension_terms(probe)
        big = big or (lab[0] if lab else "")
        part = part or (lab[1] if len(lab) >= 2 else "")
        formula = next((e.quote for e in quotes if R.is_formula(e.quote)), quotes[1].quote)
        compare = next((e.quote for e in quotes if compare_sides(e.quote)), quotes[0].quote)
        return (f"{part}도 {big}의 요소예요 — 「{_q(formula, 50)}」. 그래서 「{_q(compare, 36)}」"
                f"{_quote_josa(compare, '은', '는')} {part} 하나만 보지 말고 요소 전체를 함께 봐야 한다는 뜻이에요.")
    if probe.kind == "unsolved" and lab:
        target = lab[0]
        fix = next((e for e in quotes[1:]), None)
        tail = (f" {lab[1]}에는 「{_q(fix.quote, 45)}」{_quote_josa(fix.quote, '이라는', '라는')} 해결책을 냈지만 "
                f"{josa(target, '은', '는')} 아직 비어 있어요." if fix is not None and len(lab) >= 2 else "")
        return (f"{josa(target, '을', '를')} 개선하는 방법은 아직 자료에 없어요 —{tail or ' 이번 자료에서는 다루지 못했어요.'} "
                f"이 부분은 앞으로 보완할게요.")
    if probe.kind == "unsupported_cause" and first is not None:
        return (f"{where}의 「{_q(first.quote)}」에는 아직 수치나 출처가 없어요. "
                f"설문이나 통계, 비교 자료로 보강할게요.")
    if probe.kind == "absolute_boundary" and first is not None:
        return _absolute_gist(first, lab[0] if lab else "", where, slides)
    if probe.kind == "sibling_priority" and len(lab) >= 2:
        return (f"{josa(lab[0], '과', '와')} {lab[1]}{josa(lab[1], '은', '는')[len(lab[1]):]} 둘 다 필요해요. 어느 하나만 고르기보다, "
                f"상황에 따라 먼저 챙길 쪽을 정하면 돼요.")
    return ""


def _absolute_gist(first: ClaimQuote, target: str, where: str, slides: dict[int, str] | None) -> str:
    """
    단정 탐침의 모범답 (09-30 WP-P2) — 발표자 목소리, 해요체, 단정 줄을 되읊지 않는다. 첫 절에 열쇠 말 「단정」 을 둔다(빈칸 칸).

    예전 골자 「…는 모든 경우에 그렇다고 단정할 수는 없어요. 자료가 보여 준 범위 안에서만 그렇게 말할 수 있어요.」 는 **조건을
    하나도 말하지 않아서**, 그대로 답하면 단정 줄을 다시 말한 것과 같았다(09-30 standard: 이 골자를 답한 사람이 「자료의 단정을
    다시 말했어요」 55).
    - 자료가 스스로 단 조건(`hedge_line` — 「개인에 따라 반응이 다를 수 있으니」)이 있으면 그 조건과 장을 댄다.
    - 없으면 자료에 조건이 없다고 솔직히 말하고 무엇을 더할지(누구에게·언제·어떤 조건에서) 말한다 — 빈칸·근거 없는 인과 골자와
      같은 「비어 있다 → 보완할게요」 꼴.
    """
    marker = R.absolute_marker(first.quote) or R.absolute_marker(first.quote, strong_only=True)
    said = f"「{marker}」{_quote_josa(marker, '이라고', '라고')}" if marker else "그렇게"
    hedge = hedge_line(slides, {first.slide_no}, about=f"{first.quote} {target}") if slides else None
    if hedge is not None:
        clause = _hedge_clause(hedge[1])
        cond = (f"자료 {hedge[0]}장에 적었듯 {clause}" if clause
                else f"자료 {hedge[0]}장에도 「{_q(hedge[1], 45)}」{_quote_josa(_q(hedge[1], 45), '이라고', '라고')} 적었어요.")
        return f"{said} 단정할 수는 없어요 — {cond} 이 조건을 붙여서 말할게요."
    return (f"{said} 단정할 수는 없어요 — {where}에는 이 말이 들어맞는 조건이 아직 없어요. "
            f"누구에게, 언제, 어떤 조건에서 그런지 정해서 보완할게요.")


def probe_hint(probe: Probe, labels: dict[str, str]) -> str:
    """탐침 질문의 첫 힌트(방향) — 답을 말하지 않고 **무엇을 확인할지**만. LLM 힌트는 「관련 연구를 찾아보세요」 처럼 자료에 없는
    것을 찾게 했다 (09-30 held-out M-06: 근거 없는 인과 질문에 「실험 결과를 찾아보세요」)."""
    lab = [labels.get(i, i) for i in probe.node_ids]
    first = next((e for e in probe.evidence if (e.quote or "").strip()), None)
    where = f"자료 {first.slide_no}장" if first and first.slide_no else "자료"
    if probe.kind == "tension":
        return "두 문장이 각각 무엇을 말하는지 — 하나는 견주는 말, 하나는 구성 요소 — 나눠서 떠올려 보세요."
    if probe.kind == "unsolved" and lab:
        return f"자료가 해결책을 낸 문제와 {josa(lab[0], '을', '를')} 나란히 놓고, {lab[0]}에 대한 방법이 있는지 확인해 보세요."
    if probe.kind == "unsupported_cause":
        return f"{where}의 그 문장 옆에 수치나 출처가 있는지부터 확인해 보세요."
    if probe.kind == "absolute_boundary":
        marker = R.absolute_marker(first.quote) if first else ""
        said = f"「{marker}」라는 말이" if marker else "그 말이"
        return f"{said} 들어맞지 않을 만한 상황을 하나 떠올려 보세요."
    if probe.kind == "sibling_priority":
        return "자료가 두 요소 사이의 우선순위를 직접 말한 곳이 있는지부터 찾아보세요."
    return ""
