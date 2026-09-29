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
    양·방향 수식어만 다르다("충분한 시간" = "시간 부족" — F-07 이 같은 개념을 두 노드로 둔 경우).
    """
    ta, tb = label_tokens(a), label_tokens(b)
    if not ta or not tb:
        return bool(a) and a == b
    return contains_tokens(ta, tb) or contains_tokens(tb, ta) or R.same_concept(a, b)


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
                    angle=f"「{said}」라면서 {josa(el_label, '을', '를')} {a_label}의 요소로 둔다 — 두 말이 함께 성립하는 뜻을 묻는다",
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
        # 문제 항목 자신과 그 겹친 이름(F-07 이 같은 개념을 두 노드로 둔 것)은 해결 쪽 개념이 아니다
        fix_nodes = {n for n in fix_nodes - set(items)
                     if n in graph_by and not any(_related(graph_by[n].label, graph_by[i].label) for i in items)}

        def solved_by(o: str) -> list[Claim]:
            label = graph_by[o].label
            return [s for s in fixes if any(x == o or (x in graph_by and _related(graph_by[x].label, label)) for x in s.object_ids)
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
    단정("반드시·완전히·항상") — 그 말이 통하지 않는 경우·경계를 묻는다.
    인용 줄에 **부정되지 않은** 단정 표지가 있을 때만 (「반드시 …는 아니다」 는 유보다 — F-26 이 거르지만 한 번 더).
    """
    out: list[Probe] = []
    for c in claims:
        if c.kind != "absolute":
            continue
        marked = [e for e in c.evidence if R.absolute_marker(e.quote)]
        if not marked:
            continue
        said = marked[0].quote
        out.append(Probe(
            kind="absolute_boundary",
            node_ids=[c.subject_id],
            claim_ids=[c.id],
            angle=f"「{said}」는 단정이다 — 이 말이 들어맞지 않는 경우·경계를 묻는다",
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
    """dict 도 받는다. 주장이 하나도 없으면 None — 없는 것과 같다 (프롬프트·순위를 안 바꾼다)."""
    if claims is None:
        return None
    if isinstance(claims, dict):
        claims = ClaimDoc.from_dict(claims)
    return claims if claims.claims else None


def derive_probes(graph: ConceptGraph, claims: ClaimDoc | dict | None) -> list[Probe]:
    """
    ConceptGraph + ClaimDoc → 탐침 목록. 결정적이고 LLM 을 부르지 않는다.

    정렬: PROBE_KINDS 순서(= QA_SOURCES 우선순위) → 대상 노드의 그래프 순서 → 주장 id.
    같은 (종류, 대상) 은 하나만 남긴다 — 개념당 질문이 하나라 둘째는 쓸 자리가 없다.
    이 정렬 덕분에 `QaTriage.probe_for(node_id)` 가 그 노드의 **가장 우선인** 탐침을 돌려준다.
    """
    doc = as_claims(claims)
    if doc is None or not graph.nodes:
        return []
    graph_by = {n.id: n for n in graph.nodes}
    usable = _usable(doc.claims, graph_by)
    found = [
        *_tension(graph_by, usable), *_unsolved(graph_by, usable), *_unsupported_cause(graph_by, usable),
        *_absolute_boundary(graph_by, usable), *_sibling_priority(graph_by, usable),
    ]
    node_order = {n.id: i for i, n in enumerate(graph.nodes)}
    found.sort(key=lambda p: (_KIND_RANK[p.kind], node_order.get(p.node_ids[0], len(node_order)), p.claim_ids))
    out: list[Probe] = []
    seen: set[tuple] = set()
    for p in found:
        # 같은 이름·같은 개념의 두 노드(F-07 이 겹쳐 둔 것)는 한 대상이다
        label = graph_by[p.node_ids[0]].label
        key = (p.kind, R.concept_key(label) or label)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return _cap_sibling(out)


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
        a, b = lab[0], lab[1]
        compare = claims.claim(probe.claim_ids[0]) if claims is not None and probe.claim_ids else None
        pred = _compare_pred(compare, b) if compare is not None else _PRED_FALLBACK
        text = f"{b}도 {a}의 요소인데, {josa(a, '이', '가')} {b}보다 {pred}는 건 어떤 뜻인가요?"
    elif probe.kind == "unsolved" and len(lab) >= 2:
        text = f"{lab[1]}에는 해결책을 제시했는데, {josa(lab[0], '은', '는')} 어떻게 개선하나요?"
    elif probe.kind == "unsupported_cause":
        cause = claims.claim(probe.claim_ids[0]) if claims is not None and probe.claim_ids else None
        quote = _short_quote(cause) if cause is not None else ""
        if quote:
            # 인용 원문을 그대로 — 라벨로 문장을 지으면 자료에 없는 방향·목적어가 끼어든다 (09-29 벤치)
            text = f"「{quote}」라고 했는데, 그렇게 볼 수 있는 근거는 무엇인가요?"
        elif len(lab) >= 2:
            text = f"{josa(lab[0], '이', '가')} {lab[1]}에 영향을 준다고 했는데, 그렇게 볼 수 있는 근거는 무엇인가요?"
        else:
            text = f"{lab[0]}에 대해 말한 원인과 결과는 어떤 근거로 볼 수 있나요?"
    elif probe.kind == "absolute_boundary":
        absolute = claims.claim(probe.claim_ids[0]) if claims is not None and probe.claim_ids else None
        quote = _short_quote(absolute) if absolute is not None else ""
        said = f"「{quote}」라고 했는데" if quote else "단정적으로 말했는데"
        text = f"{lab[0]}에 대해 {said}, 이 말이 들어맞지 않는 경우도 있나요?"
    elif probe.kind == "sibling_priority" and len(lab) >= 2:
        parent = ""
        if graph_by is not None and ids[0] in graph_by:
            up = graph_by[ids[0]].parent_id
            parent = graph_by[up].label if up and up in graph_by else ""
        where = f"{parent}에는 " if parent else ""
        text = f"{josa(lab[0], '과', '와')} {lab[1]} 중 하나만 챙길 수 있다면, {where}어느 쪽이 더 중요한가요?"
    else:
        text = f"{lab[0]}에 대해 자료가 말한 것을 어떤 근거로 볼 수 있나요?"
    return text if len(text) <= QA_TEXT_MAX else text[: QA_TEXT_MAX - 1].rstrip() + "…"


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
