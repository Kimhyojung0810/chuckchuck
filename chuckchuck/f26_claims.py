"""
[F-26] 주장 그래프 — 개념 사이의 **주장**을 자료 원문 인용과 함께 뽑는 모듈입니다.
ConceptGraph + SlideDoc → ClaimDoc.

    from chuckchuck.f26_claims import build_claims
    claims = build_claims(graph, slidedoc, llm="solar")                 # 세션에 한 번
    triage = triage_questions(graph, ..., claims=claims.to_dict())      # F-08 이 탐침을 찾는다

왜 있나 (2026-09-29 실측, 수면 덱):
  1장 「A보다 중요한 B」 와 4장 「B = A × C × D」 처럼 **A보다 중요하다면서 A가 B의 요소**라는 긴장이
  자료 안에 있는데, 개념 그래프(F-07)는 위계·연결만 알아서 코드가 이걸 볼 수 없었다. 주장
  (compose·compare·cause·solve·absolute·contrast)을 따로 두면 F-08 이 tension·unsolved·unsupported_cause
  같은 탐침을 **코드로** 찾는다.

F-07 과 LLM 호출을 합치지 않는다 — F-07 프롬프트에 칸을 더했다가 위계가 흔들려 되돌린 적이 있다
(노드 links 칸 요구안). 그래서 한 번 더, 따로 부른다. 이 모듈의 핵심은 LLM 이 아니라 **대조**다:

1. LLM 은 주장 후보와 인용을 낸다 (1콜, JSON 이 깨지면 한 번 더).
2. 코드가 그래프 밖 id·모르는 kind 를 버리고, 인용이 **그 장 원문의 한 줄**에 실제로 있는지 대조한다.
   여러 글 상자를 이어 붙인 인용은 줄마다 나눠, 주장을 받치는 줄 하나만 남긴다 (09-29 벤치: held-out 인용 16%).
3. 인용 한 줄이 주장을 **받치는지** 본다 (`_claim_rules`) — absolute 는 부정되지 않은 단정 표지가 있어야,
   compare 는 비교 표지와 두 개념 이름이, compose 는 식이나 목록이, cause 는 인과 말투와 두 이름이 있어야 한다.
   물음 줄(「…는가」)은 주장이 아니다. held-out 에서 absolute 의 75% 가 표지 없는 줄이었다.
4. has_support(인용 줄에 수치·출처가 있는가)는 코드가 **인용 줄과 그 옆 줄**만 보고 채운다 — 장 전체를 보면
   무관한 숫자 하나(「90분」)가 근거 없는 인과를 근거 있는 인과로 만든다.
5. 구조가 뻔한 것(「A = B × C」 식, 「A보다 ○○한 B」, 문제 목록 제목 + 항목, 단정 표지 줄, 문제→해결 표 행,
   문제 항목을 부르며 푸는 해결 줄)은 LLM 없이 규칙으로도 뽑는다. LLM 이 놓치거나 죽어도 뼈대는 남는다.
6. 자료 속 지시문(「…판정할 것」「[SYSTEM]」)은 줄 읽기(`_deck_lines`)에서 빠져 인용·프롬프트에 못 들어가고, 장 원문은
   <slide> 울타리 안에 싣는다 (09-30 레드팀 R3). 주장 id 는 내용 해시라 다시 만들어도 같다 (G-A21).

모듈 규칙(DEV_POLICY §4): 다른 fXX 를 import 하지 않는다. 유틸(_evidence·_match·_claim_rules·_deck_lines·_graph_items·_json_text)만 쓴다.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from dataclasses import dataclass

from . import _claim_rules as R
from . import _deck_lines as DL
from . import _graph_items as GI
from . import _reason as RS
from ._claim_quote import (  # noqa: F401 — 테스트·브리지가 f26 에서 부른다
    QUOTE_MIN_CHARS,
    _Hit,
    _tidy,
    has_support,
    line_support,
    locate_quote,
    norm_for_match,
    slide_lines,
    verify_quote,
)
from ._json_text import extract_json_object
from ._match import norm_tokens
from .contracts import (
    CLAIM_KINDS,
    Claim,
    ClaimDoc,
    ClaimQuote,
    ConceptGraph,
    ConceptNode,
    SlideDoc,
)
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm

#: 한 덱에서 남길 주장 최대 수. 탐침은 주장 수의 곱으로 늘어난다 — 많으면 F-08 프롬프트가 흐려진다.
CLAIM_MAX = int(os.environ.get("CHUCKCHUCK_CLAIM_MAX", "24"))
#: 주장 하나에 남길 인용 최대 수. 「요소가 함께 필요하다」 줄은 이 위에 하나 더 붙을 수 있다 (`_attach_joint_lines`).
EVIDENCE_MAX = 3
#: 목록 제목 밑에서 읽을 항목 줄 수 상한.
LIST_ITEMS_MAX = 10
#: 프롬프트에 싣는 장 본문 상한(자). 20장 덱이면 ~20K 자 — Solar 입력으로 넉넉하다.
SLIDE_CHARS_MAX = 1200
#: 프롬프트에 싣는 장 수 상한. 넘으면 앞에서부터 (부록·참고문헌이 뒤에 온다).
SLIDES_MAX = 40
MAX_TOKENS = 3000

# 예시는 어느 실제 발표에서도 가져오지 않는다 — 예시 덱과 모양이 같은 주장만 받아 쓰는 쏠림을 막으려고
# 가상의 중립 주제(가게 운영·회의)로 둔다 (09-29 벤치: 프롬프트 예시 덱 0% vs 안 본 덱 69% 템플릿 폴백).
SYSTEM_PROMPT = """당신은 발표 자료의 논증 구조 분석가다.
개념 목록과 슬라이드 원문을 받아, 자료가 **개념 사이에 실제로 하는 주장**을 뽑는다.

kind 는 여섯 가지 중 하나다 (subject → objects 방향):
- compose  : subject 는 objects 로 이뤄진다        예) 「고객 만족 = 속도 × 정확도 × 친절」, 「매장이 겪는 세 가지 문제」 밑의 항목들
- compare  : subject 가 objects 보다 더 중요·크다  예) 「가격보다 중요한 신뢰」 → subject=신뢰, objects=[가격]
             「덜·적다·낮다·…지 않다」 는 반대다  예) 「신뢰보다 덜 중요한 가격」「가격은 신뢰만큼 중요하지 않다」 → subject=신뢰
- cause    : subject(원인)가 objects(결과)를 일으키거나 바꾼다 예) 「잦은 회의가 개발 속도를 늦춘다」 → subject=회의, objects=[개발 속도]
- solve    : subject(해결책)가 objects(문제·요소)를 해결한다 예) 「주문 확인 문자 발송 — 주문 오류를 줄인다」 → subject=확인 문자, objects=[주문 오류]
- absolute : subject 에 대해 예외 없이 단정한다     예) 「이 방식이면 대기 시간은 반드시 0분이 된다」
- contrast : subject 와 objects 를 맞세운다        예) 단기 성과 ↔ 장기 성과

kind 고르는 법 — 자료의 말투가 정한다:
- compose  ← 「=」 식, 또는 「세 가지·다섯 가지 요인·조건·문제」 제목 밑에 항목이 줄마다 있을 때 (제목 한 줄만으로는 아니다)
- compare  ← 「보다·대비·vs·더」 가 그 줄에 있을 때만
- cause    ← 「때문에·→·수록·일으킨다·늘린다·줄인다·떨어진다·증가·감소」
- solve    ← 「해결·해소·방법·줄이기·막는다·없앤다」, 또는 문제 칸과 해결 칸이 한 행에 있는 표
- absolute ← 그 줄에 「반드시·완전히·항상·절대·전혀·하나도·예외 없이·무조건」 이 있고 부정되지 않았을 때만
             (「반드시 …는 아니다」「완전히 …되지는 않는다」 는 유보라서 absolute 가 아니다)
- contrast ← 「A가 아니라 B」「↔」

규칙:
- subject_id·object_ids 는 개념 목록의 「id:」 값을 **글자 그대로** 옮긴다 (괄호·이름 없이). 목록에 없는 id 는 버려진다.
- slide_no 는 그 주장이 적힌 장 번호(<slide n="…"> 의 n), quote 는 그 장 원문에서 **한 줄을 글자 그대로 복사한** 것이다.
  여러 줄을 이어 붙이지 마라. 요약·의역·말줄임 금지. 코드가 원문과 줄 단위로 대조해서 없는 인용은 버린다.
- quote 한 줄 안에 subject 와 objects 의 이름(또는 자료 속 그 낱말)이 보여야 한다. 안 보이면 코드가 버린다.
- 물음 줄(「…는가」「…일까?」)·표지의 부제·날짜 줄은 주장이 아니다.
- 자료에 적힌 주장만. 당신의 상식으로 관계를 지어내지 마라. 수치 하나하나를 주장으로 만들지 마라 — 개념 사이의 관계만.
- 슬라이드 1 부터 마지막 장까지 **순서대로** 훑으며, 한 장에서 많아야 4개. 같은 줄을 두 번 인용하지 마라.
- 서로 다른 장에 걸친 주장(앞 장의 비교와 뒤 장의 식)도 각각 따로 적는다 — 둘이 부딪쳐도 그대로 둔다.
- 문제 목록 장과 해결책 장이 있으면, 해결책 줄마다 그것이 다루는 문제를 objects 로 solve 를 적는다.
- text 는 주장 한 줄 (자료 표현에 가깝게). 모두 합쳐 5~20개.
- {FENCE}
- 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마:
{ "claims": [ { "slide_no": 4, "kind": "compose", "subject_id": "<목록의 id>", "object_ids": ["<목록의 id>"],
                "quote": "<그 장 원문 한 줄 그대로>", "text": "…" } ] }
"""

SYSTEM_PROMPT = SYSTEM_PROMPT.replace("{FENCE}", DL.FENCE_RULE)

JSON_RETRY_NUDGE = """
[재요청] 직전 응답이 완전한 JSON 객체가 아니어서 버렸다.
코드펜스·주석·말머리·말끝 문장 없이, 출력 스키마 그대로의 JSON 객체 하나만 다시 출력하라.
"""

# ---------------------------------------------------------------------------
# 개념 이름 대조 — 규칙 추출이 쓴다
# ---------------------------------------------------------------------------

_QUOTE_MARK_RE = re.compile(r"[\"'“”‘’「」『』()\[\]]")


def _loose(text: str) -> str:
    return re.sub(r"\s+", "", _QUOTE_MARK_RE.sub("", text or "")).lower()


def _on(n: ConceptNode, slide_no: int | None) -> bool:
    return slide_no is not None and slide_no in (n.slide_nos or [])


def resolve_label(phrase: str, nodes: list[ConceptNode], exclude: str = "",
                  slide_no: int | None = None) -> ConceptNode | None:
    """
    자료의 한 구절이 가리키는 개념. 없으면 None. 동점이면 그 장(slide_no)에 나온 노드를 먼저 고른다.

    1. 이름이 통째로 같다 (공백·따옴표 무시)
    2. 구절이 개념 이름을 품는다 — 가장 긴 이름 (「핵심 품질 지표」 → 품질 지표). 그 이름이 구절의 머리여야 한다
    3. 구절의 **변별 낱말**(맞은편 구절에도 있는 낱말은 뺀다)과 가장 많이 겹치는 이름 — 변별 낱말의 절반 이상이
       이름에 들어야 한다 (「예방 체계」 → 「사전 예방」). 전부 들어야 했을 때는 자료 표현과 라벨이 조금만 달라도
       규칙 추출이 죽었다 (09-29 벤치 정책 덱). 단 머리말이 통해야 하고(`head_compatible`) 반의어는 안 된다 (09-30).

    같은 규칙을 compose·compare 가 함께 쓰므로, 같은 구절은 두 주장에서 같은 개념이 된다 —
    그래야 F-08 이 compare 와 compose 의 겹침(tension)을 id 로 찾는다.
    """
    want = _loose(phrase)
    if not want:
        return None
    exact = [n for n in nodes if _loose(n.label) == want]
    if exact:
        return max(exact, key=lambda n: (_on(n, slide_no), n.weight))
    ptoks = norm_tokens(_QUOTE_MARK_RE.sub(" ", phrase))
    contained = []
    for n in nodes:
        ltoks = norm_tokens(n.label)
        # 구절이 이름을 품어도 그 이름이 구절의 **머리**여야 한다 — 「혈당 부하」 는 「혈당」 을 품지만 머리는 「부하」다 (09-30)
        if ltoks and sum(len(t) for t in ltoks) >= 2 and _seq_in(ptoks, ltoks) and R.head_compatible(phrase, n.label):
            contained.append(n)
    if contained:
        return max(contained, key=lambda n: (len(_loose(n.label)), _on(n, slide_no), n.weight, n.id))
    distinct = R.distinct_tokens(_QUOTE_MARK_RE.sub(" ", phrase), _QUOTE_MARK_RE.sub(" ", exclude)) if exclude \
        else R.content_tokens(_QUOTE_MARK_RE.sub(" ", phrase))
    if not distinct:
        return None
    cands = []
    for n in nodes:
        # 반쯤 겹치는 이름은 머리말이 통하고 반의어가 아닐 때만 — 「혈당 부하」 가 낱말 「혈당」 하나로 「혈당 스파이크」 가,
        # 「매출 증가」 가 「매출 감소」 가 되지 않게 (09-30 M-05 · G-A3)
        if not R.head_compatible(phrase, n.label) or R.antonyms(phrase, n.label):
            continue
        ltoks = R.content_tokens(n.label)
        hits = sum(1 for t in distinct if any(R.tok_match(t, lt) or R.tok_match(lt, t) for lt in ltoks))
        if hits and hits / len(distinct) >= R.MENTION_MIN:
            extra = sum(1 for lt in ltoks if not any(R.tok_match(t, lt) or R.tok_match(lt, t) for t in distinct))
            cands.append((-hits, extra, not _on(n, slide_no), -n.weight, n.id, n))
    return min(cands, key=lambda c: c[:5])[5] if cands else None


def _seq_in(outer: list[str], inner: list[str]) -> bool:
    n = len(inner)

    def tin(o: str, i: str) -> bool:
        return o == i or (len(i) >= 2 and i in o)
    return any(all(tin(outer[i + j], inner[j]) for j in range(n)) for i in range(len(outer) - n + 1))


def best_node(text: str, nodes: list[ConceptNode], slide_no: int | None = None,
              skip: set[str] | None = None) -> ConceptNode | None:
    """
    한 줄에 가장 뚜렷이 나온 개념 — 이름이 통째로 나온 것, 이름 토큰이 많이 나온 것, 비율 높은 것, 먼저 나온 것,
    그 장에 나온 것 순. 이름 토큰의 절반도 안 나오면 후보가 아니다. 통째로 나온 이름이 먼저인 까닭: 질문이 그 개념을
    부를 때 자료의 낱말 그대로라야 자연스럽다 (반쯤 걸친 「소설 확산」 보다 줄에 있는 「권선징악」).
    """
    cands = []
    for n in nodes:
        if skip and n.id in skip:
            continue
        toks = R.content_tokens(n.label)
        score = R.mention_score(n.label, text)
        if not toks or score < R.MENTION_MIN:
            continue
        cands.append((score < 1, -round(score * len(toks)), -score, R.first_position(n.label, text), not _on(n, slide_no),
                      -n.weight, n.id, n))
    return min(cands, key=lambda c: c[:7])[7] if cands else None


# ---------------------------------------------------------------------------
# 규칙 추출 — LLM 없이 뻔한 구조
# ---------------------------------------------------------------------------

def _formula_parts(line: str) -> tuple[str, list[str]] | None:
    sides = R.formula_sides(line)
    if not sides:
        return None
    lhs, rhs = sides
    parts = R.formula_terms(rhs)
    return (lhs, parts) if len(parts) >= 2 else None


def rule_compose(graph: ConceptGraph, slidedoc: SlideDoc) -> list[Claim]:
    """「<개념> = A × B × C」 (+·÷ 도) 줄에서 compose 주장. 요소가 둘 이상 개념에 닿아야 남긴다."""
    out: list[Claim] = []
    for s in slidedoc.slides:
        for line in slide_lines(s.raw_text):
            parsed = _formula_parts(line)
            if not parsed:
                continue
            lhs, parts = parsed
            subj = resolve_label(lhs, graph.nodes, slide_no=s.slide_no)
            if subj is None:
                continue
            objs: list[str] = []
            for p in parts:
                n = resolve_label(p, graph.nodes, exclude=lhs, slide_no=s.slide_no)
                if n is not None and n.id != subj.id and n.id not in objs:
                    objs.append(n.id)
            if len(objs) >= 2:
                out.append(Claim(id="", kind="compose", subject_id=subj.id, object_ids=objs, text=line,
                                 evidence=[ClaimQuote(s.slide_no, line)]))
    return out


def list_items(lines: list[str], head_idx: int) -> list[str]:
    """
    목록 제목 밑의 항목 글 — 번호·글머리표·표 첫 칸. 문장이 나오면 목록이 끝난다.
    제목 바로 밑의 소개 문장 하나(「흔한 이유는 이렇습니다.」)는 건너뛴다.
    """
    items: list[str] = []
    start = head_idx + 1
    if start < len(lines) and not R.is_item_line(lines[start]):
        start += 1
    for line in lines[start: start + LIST_ITEMS_MAX]:
        if not R.is_item_line(line):
            break
        text = R.item_text(line)
        if text:
            items.append(text)
    return items


def _ancestors(node_id: str, by_id: dict[str, ConceptNode]) -> set[str]:
    out: set[str] = set()
    cur = by_id.get(node_id)
    while cur is not None and cur.parent_id and cur.parent_id not in out:
        out.add(cur.parent_id)
        cur = by_id.get(cur.parent_id)
    return out


def _list_subject(head: str, items: list[str], graph: ConceptGraph, slide_no: int) -> ConceptNode | None:
    """목록의 주어 — 제목이 가리키는 개념, 없으면 항목들이 함께 매달린 부모."""
    by_id = {n.id: n for n in graph.nodes}
    got = resolve_label(head, graph.nodes, slide_no=slide_no)
    if got is not None and got.id not in items:
        return got
    parents = {by_id[i].parent_id for i in items if i in by_id}
    if len(parents) == 1:
        (pid,) = parents
        return by_id.get(pid or "")
    return None


def rule_list_compose(graph: ConceptGraph, slidedoc: SlideDoc) -> list[Claim]:
    """
    목록 제목(「해결해야 할 세 가지 문제」「매출을 이루는 네 요소」) + 항목 줄 → compose(주어 ⊃ 항목).

    인용은 제목 줄이다 — 제목에 「문제·원인·이유」 가 있으면 F-08 이 문제 목록으로 읽는다 (unsolved 재료).
    항목이 둘 이상 서로 다른 개념에 닿아야 남긴다.
    """
    out: list[Claim] = []
    for s in slidedoc.slides:
        lines = slide_lines(s.raw_text)
        for i, head in enumerate(lines):
            if not R.is_list_heading(head):
                continue
            objs: list[str] = []
            for item in list_items(lines, i):
                n = resolve_label(item, graph.nodes, slide_no=s.slide_no)
                if n is not None and R.mentioned(n.label, item) and n.id not in objs:
                    objs.append(n.id)
            if len(objs) < 2:
                continue
            subj = _list_subject(head, objs, graph, s.slide_no)
            if subj is None or subj.id in objs:
                continue
            out.append(Claim(id="", kind="compose", subject_id=subj.id, object_ids=objs, text=head,
                             evidence=[ClaimQuote(s.slide_no, head)]))
    return out


def rule_compare(graph: ConceptGraph, slidedoc: SlideDoc) -> list[Claim]:
    """
    비교 줄(「A보다 ○○한 B」·「B는 A보다 ○○」·「A 대비 B가 …」·「B는 A만큼 …지 않다」) → compare(큰 쪽 > 작은 쪽).
    방향은 `_claim_rules.compare_sides` 가 「덜·적다·않다」 까지 보고 정한다 (09-30 G-A1 — 예전엔 늘 B > A 였다).
    양쪽이 서로 다른 개념에 닿아야 남긴다.
    """
    out: list[Claim] = []
    for s in slidedoc.slides:
        for line in slide_lines(s.raw_text):
            if R.is_question(_QUOTE_MARK_RE.sub("", line).strip()):
                continue
            # 여러 꼴을 다 본다 — 문장형은 제목형 정규식에도 걸리지만(b=「개념입니다」) 개념에 안 닿는다. 닿는 첫 해석을 쓴다.
            for big_phrase, small_phrase in R.compare_sides(line):
                big = resolve_label(big_phrase, graph.nodes, exclude=small_phrase, slide_no=s.slide_no)
                small = resolve_label(small_phrase, graph.nodes, exclude=big_phrase, slide_no=s.slide_no)
                if big is None or small is None or big.id == small.id:
                    continue
                out.append(Claim(id="", kind="compare", subject_id=big.id, object_ids=[small.id], text=line,
                                 evidence=[ClaimQuote(s.slide_no, line)]))
                break
    return out


def rule_absolute(graph: ConceptGraph, slidedoc: SlideDoc) -> list[Claim]:
    """부정되지 않은 강한 단정 표지(반드시·완전히·항상·절대 …)가 있는 문장 → absolute(그 줄에 가장 뚜렷한 개념)."""
    out: list[Claim] = []
    for s in slidedoc.slides:
        for i, line in enumerate(slide_lines(s.raw_text)):
            if R.is_question(line) or not R.absolute_marker(line, strong_only=True):
                continue
            if i == 0 and not R.is_sentence(line):
                continue                      # 제목 한 줄은 단정이 아니라 표어다
            n = best_node(line, graph.nodes, slide_no=s.slide_no)
            if n is not None:
                out.append(Claim(id="", kind="absolute", subject_id=n.id, text=line,
                                 evidence=[ClaimQuote(s.slide_no, _tidy(line))]))
    return out


def _fix_node(fix_text: str, graph: ConceptGraph, slide_no: int, skip: set[str]) -> ConceptNode | None:
    """
    해결 칸이 **이름으로 부르는** 개념 — 칸 낱말의 절반 이상이 그 이름에 있어야 한다. 칸 안에 나온 목적어 하나는
    해결책이 아니라 줄일 대상이다 (09-29 graph_ab 남은 문제 2: 「카페인·음주·빛·소음 줄이기」 의 주어가 후처리로 생긴
    노드 「카페인」 이 되어, 해결 짝이 틀어지고 거짓 미해결 탐침이 났다).
    """
    n = best_node(fix_text, graph.nodes, slide_no=slide_no, skip=skip)
    return n if n is not None and R.mention_score(fix_text, n.label) >= R.MENTION_MIN else None


def rule_solve_rows(graph: ConceptGraph, slidedoc: SlideDoc) -> list[Claim]:
    """
    문제 칸과 해결 칸이 한 행에 있는 표(「| 문제 | 해결 |」) → solve(해결 칸의 개념 → 문제 칸의 개념).

    해결 장이라는 표시(제목이 해결 장 제목 — `is_solution_head`)가 있고 해결 칸이 무엇을 하는 말
    (「…확보」「…줄이기」)일 때만 읽는다 — 문제 장의 현황 칸(「평균 1년 이상」)은 해결이 아니다.
    해결 칸이 **이름으로 부르는** 개념이 없으면 그 장 제목이 가리키는 개념, 그것도 없으면 문제의 부모 개념을 주어로 둔다 —
    짝(문제→해결)이 있다는 사실이 unsolved 판단의 재료다. 표 첫 칸의 개념(문제들)은 주어가 되지 못한다.
    """
    out: list[Claim] = []
    for s in slidedoc.slides:
        lines = slide_lines(s.raw_text)
        if not lines or not R.is_solution_head(lines[0]):
            continue
        head = resolve_label(lines[0], graph.nodes, slide_no=s.slide_no)
        rows: list[tuple[ConceptNode, list[str], str]] = []
        for line in lines[1:]:
            cells = R.table_cells(line)
            if len(cells) < 2 or not R.SOLVE_ACT_RE.search(" ".join(cells[1:])):
                continue
            prob = resolve_label(cells[0], graph.nodes, slide_no=s.slide_no)
            if prob is not None and R.mentioned(prob.label, cells[0]) and R.mentioned(cells[0], prob.label):
                rows.append((prob, cells, line))
        firsts = {p.id for p, _, _ in rows}
        for prob, cells, line in rows:
            parent = next((n for n in graph.nodes if n.id == prob.parent_id), None)
            fix = _fix_node(" ".join(cells[1:]), graph, s.slide_no, firsts) or head or parent
            if fix is None or fix.id in firsts:
                continue
            out.append(Claim(id="", kind="solve", subject_id=fix.id, object_ids=[prob.id], text=_tidy(line),
                             evidence=[ClaimQuote(s.slide_no, _tidy(line))]))
    return out


def _solver(lines: list[str], i: int, graph: ConceptGraph, slide_no: int, skip: set[str]) -> ConceptNode | None:
    """해결 줄의 주어 — 그 줄에 뚜렷한 개념, 없으면 바로 앞 줄(「시세 지도 — …」 + 「정보 비대칭을 해소합니다」)에 뚜렷한 개념."""
    for j in (i, i - 1):
        if j < 1:
            continue
        n = best_node(lines[j], graph.nodes, slide_no=slide_no, skip=skip)
        if n is not None and _clear(n.label, lines[j]):
            return n
    return None


def rule_solve_lines(graph: ConceptGraph, slidedoc: SlideDoc) -> list[Claim]:
    """
    다른 장 문제·원인 목록의 항목을 **이름으로 부르며** 푸는 문장 → solve(해결책 → 그 항목). 주어는 그 줄(없으면 앞 줄)에
    뚜렷한 개념, 그것도 없으면 장 제목이 가리키는 개념 — 해결 장 제목은 해결책의 이름이다.

    09-30 실측: 규칙 주장만으로는 held-out 미해결 U1 을 한 덱도 못 찾았다 (벤치 그래프 규칙 경로 0/5). 해결 줄을 LLM 이 solve 로
    적을 때만 찾았고, LLM 표본이 바뀌면 사라졌다 (건강 덱). 해결 짝은 줄의 꼴로 가를 수 있다 — 문제 항목의 변수 낱말이 다 나오고
    (`names_variable`) 푸는 말투(`solves`: 줄이·막·해소·풀, 모자람이면 늘리·확충)가 있다.
    """
    deck = _Deck.of(graph, slidedoc)
    rows = _problem_rows(deck)
    if not rows:
        return []
    items = {nid for _, nid, _, _ in rows}
    out: list[Claim] = []
    for s in slidedoc.slides:
        lines = deck.lines.get(s.slide_no) or []
        title = resolve_label(lines[0], graph.nodes, slide_no=s.slide_no) if lines else None
        for i in range(1, len(lines)):
            line = lines[i]
            if R.is_question(line) or not R.is_sentence(line):
                continue
            probs = []
            for no, nid, _, _ in rows:
                label = deck.labels[nid]
                if no != s.slide_no and nid not in probs and R.names_variable(label, line) and R.solves(line, label):
                    probs.append(nid)
            if not probs:
                continue
            subj = _solver(lines, i, graph, s.slide_no, items) or (title if title is not None and title.id not in items else None)
            if subj is None or subj.id in probs:
                continue
            out.append(Claim(id="", kind="solve", subject_id=subj.id, object_ids=probs, text=line,
                             evidence=[ClaimQuote(s.slide_no, _tidy(line))]))
    return out


def _clear(label: str, text: str) -> bool:
    """이름이 글에 **뚜렷이** 나왔는가 — 통째로 나왔거나, 토큰 둘 이상이 나왔다."""
    toks = R.content_tokens(label)
    score = R.mention_score(label, text)
    return score >= 1 or (score >= R.MENTION_MIN and round(score * len(toks)) >= 2)


def rule_cause(graph: ConceptGraph, slidedoc: SlideDoc) -> list[Claim]:
    """
    원인 절과 결과 절이 연결 어미로 이어진 문장(「A가 부족해서 B가 는다」「A할수록 B가 떨어진다」「A 때문에 B」)
    → cause(원인 절에 가장 뚜렷한 개념 → 결과 절에 가장 뚜렷한 개념). 두 절이 서로 다른 개념에 닿아야 남긴다.
    """
    out: list[Claim] = []
    for s in slidedoc.slides:
        lines = slide_lines(s.raw_text)
        heads = [ln for ln in lines[:2] if len(ln.strip()) <= _SOLVE_HEAD_MAX and not R.is_sentence(ln)]
        solution_slide = any(R.is_solution_head(h) for h in heads)
        for line in lines:
            if R.is_question(line) or not R.is_sentence(line):
                continue
            if solution_slide and not _CAUSE_LINK_RE.search(line):
                continue       # 해결 장의 계획 줄은 인과가 아니다 (09-29 P5 문제 7 · `_under_solution_head`)
            m = R.CAUSE_SPLIT_RE.search(line)
            svo = R.CAUSE_SVO_RE.match(line.strip().rstrip("."))
            if m:
                left, right = line[:m.end()], line[m.end():]
            elif svo and R.CAUSE_RE.search(svo.group("v")):
                left, right = svo.group("a"), svo.group("b")
            else:
                continue
            src = best_node(left, graph.nodes, slide_no=s.slide_no)
            dst = best_node(right, graph.nodes, slide_no=s.slide_no, skip={src.id} if src else None)
            # 규칙은 LLM 보다 좁게 — 두 절에 개념 이름이 뚜렷이 나와야 한다 (낱말 하나 겹침으로 짝을 짓지 않는다)
            if src is None or dst is None or not (_clear(src.label, left) and _clear(dst.label, right)):
                continue
            out.append(Claim(id="", kind="cause", subject_id=src.id, object_ids=[dst.id], text=line,
                             evidence=[ClaimQuote(s.slide_no, _tidy(line))]))
    return out


def _side_node(phrase: str, other: str, graph: ConceptGraph, slide_no: int) -> ConceptNode | None:
    """
    대비 한쪽 구절이 가리키는 개념 — resolve_label 보다 **좁게**: 구절의 변별 낱말(맞은편 구절에 없는 것)이 전부 이름에
    있어야 한다. 절반 겹침이면 「X 선택」 이 「X 수 하한」 으로 풀려 보기의 부정된 쪽이 엉뚱한 개념이 된다 (09-30 dry-run).
    """
    node = resolve_label(phrase, graph.nodes, exclude=other, slide_no=slide_no)
    if node is None:
        return None
    toks = R.distinct_tokens(phrase, other)
    ltoks = R.content_tokens(node.label)
    ok = all(any(R.tok_match(t, lt) or R.tok_match(lt, t) for lt in ltoks) for t in toks)
    return node if ok else None


def rule_contrast(graph: ConceptGraph, slidedoc: SlideDoc) -> list[Claim]:
    """
    「X(이/가) 아니라 Y」·「X가 아닌 Y」·「X보다 Y가 …를 갈랐다」 줄 → contrast(subject=세운 쪽 Y, objects=[부정된 쪽 X]).

    09-30 실측: 근거 질문의 「모르겠어요」 보기가 인용 한 줄의 낱말에서 나와 자료가 세운 대비를 몰랐다 — 그래프에 대비 주장이
    있으면 F-08 이 질문의 개념에 닿은 대비로 보기(세운 쪽이 정답)를 고른다. 양쪽이 **서로 다른 개념**에 닿아야 남긴다.
    한쪽이 개념에 안 닿으면 주장을 만들지 않는다 — 그래프 밖 구절을 노드로 더하면 F-07 이 세운 위계·가중치를 F-26 이 바꾸는
    꼴이다. 그 줄은 F-08 이 장의 구조 규칙(`_reason`)으로 따로 읽는다 (보기 글은 어차피 자료 줄의 낱말 그대로다).
    배경 절의 「일부가 아닌 전반적 현상」 같은 줄도 양쪽이 개념이면 주장이 된다 — 이유인지는 F-08 이 절 구조로 가른다.
    """
    out: list[Claim] = []
    for s in slidedoc.slides:
        for line in slide_lines(s.raw_text):
            sides = RS.contrast_sides(line)
            if not sides:
                continue
            neg, pos = sides
            big = _side_node(pos, neg, graph, s.slide_no)
            small = _side_node(neg, pos, graph, s.slide_no)
            # 같은 뜻의 두 이름(F-07 이 겹쳐 둔 노드)은 대비가 아니다 — 반대 극성(「매출 증가가 아니라 매출 감소」)은 대비다 (G-A3)
            if big is None or small is None or big.id == small.id or R.same_sense(big.label, small.label):
                continue
            out.append(Claim(id="", kind="contrast", subject_id=big.id, object_ids=[small.id], text=line,
                             evidence=[ClaimQuote(s.slide_no, _tidy(line))]))
    return out


#: 「A와 B의 상관은 …」 · 「A는 B와 (뚜렷한) 역상관」 — 두 절을 가른다.
_CORR_PAIR_RE = re.compile(
    r"^(?P<a>[^,.?!]{2,30}?)(?:와|과)\s+(?P<b>[^,.?!]{2,30}?)(?:의|간의|사이의)\s+(?:[가-힣]+\s+)?(?:상관|연관성|관련성)")
_CORR_SVO_RE = re.compile(r"^(?P<a>[^,.?!]{2,30}?)(?:은|는|이|가)\s+(?P<b>[^,.?!]{2,30}?)(?:와|과)\s+.*(?:상관|비례)")
#: 「A → B」 줄 — 화살표 앞이 원인, 뒤가 결과.
_ARROW_RE = re.compile(r"\s*(?:→|->)\s*")


def rule_correlation(graph: ConceptGraph, slidedoc: SlideDoc) -> list[Claim]:
    """
    상관·역상관 줄과 「A → B」 줄 → cause(A → B). **약한 상관은 주장을 만들지 않는다** — 「A 와 B 의 상관은 약함」 은
    A 가 B 의 원인이 **아니라는** 말이라 cause 로 적으면 근거 없는 인과 탐침이 거꾸로 선다. 그 줄은 F-08 이 이유 줄로 읽는다.
    해결 장의 「방법 → 효과」 는 계획이라 인과로 보지 않는다 (rule_cause 와 같은 규율). 두 쪽이 다른 개념에 또렷이 닿아야 남긴다.
    """
    out: list[Claim] = []
    for s in slidedoc.slides:
        lines = slide_lines(s.raw_text)
        heads = [ln for ln in lines[:2] if len(ln.strip()) <= _SOLVE_HEAD_MAX and not R.is_sentence(ln)]
        solution_slide = any(R.is_solution_head(h) for h in heads)
        for unit in (u.text for u in RS.units(s.slide_no, s.raw_text) if u.kind in ("bullet", "text")):
            if R.is_question(unit):
                continue
            strength = RS.correlation(unit)
            parts = _ARROW_RE.split(unit, maxsplit=1)
            if strength and strength != "weak":
                m = _CORR_PAIR_RE.match(unit) or _CORR_SVO_RE.match(unit)
                if not m:
                    continue
                left, right = m.group("a"), m.group("b")
            elif len(parts) == 2 and not solution_slide and not strength and R.CAUSE_RE.search(parts[1]) \
                    and not _ARROW_RE.search(parts[1]):
                left, right = parts      # 화살표 하나 + 뒤쪽이 바꾸는 말 — 「A → B 가 는다」. 「가 → 나 → 다」 순서 나열은 아니다
            else:
                continue
            # 짧은 쪽 구절이라 이름을 품는 가장 구체적인 개념을 먼저 (「오배송률」 이 루트 「오배송」 보다) — 없으면 가장 뚜렷한 개념
            src = resolve_label(left, graph.nodes, exclude=right, slide_no=s.slide_no) or best_node(left, graph.nodes, slide_no=s.slide_no)
            dst = resolve_label(right, graph.nodes, exclude=left, slide_no=s.slide_no) or best_node(
                right, graph.nodes, slide_no=s.slide_no, skip={src.id} if src else None)
            if src is None or dst is None or src.id == dst.id or not (_clear(src.label, left) and _clear(dst.label, right)):
                continue
            out.append(Claim(id="", kind="cause", subject_id=src.id, object_ids=[dst.id], text=unit,
                             evidence=[ClaimQuote(s.slide_no, _tidy(unit))]))
    return out


def rule_claims(graph: ConceptGraph, slidedoc: SlideDoc) -> list[Claim]:
    return (rule_compose(graph, slidedoc) + rule_list_compose(graph, slidedoc) + rule_compare(graph, slidedoc)
            + rule_absolute(graph, slidedoc) + rule_solve_rows(graph, slidedoc) + rule_solve_lines(graph, slidedoc)
            + rule_cause(graph, slidedoc) + rule_contrast(graph, slidedoc) + rule_correlation(graph, slidedoc))


# ---------------------------------------------------------------------------
# LLM 후보
# ---------------------------------------------------------------------------

def _engine(llm: str | LLMProvider | None, llm_kwargs: dict | None) -> LLMProvider:
    return llm if isinstance(llm, LLMProvider) else get_llm(llm, **(llm_kwargs or {}))


def _user_prompt(graph: ConceptGraph, slidedoc: SlideDoc) -> str:
    by_id = {n.id: n for n in graph.nodes}
    nodes = []
    for n in graph.nodes:
        parent = by_id.get(n.parent_id or "")
        nodes.append(
            f"- id: {n.id} · 이름: {n.label}" + (f" — {n.summary}" if n.summary else "")
            + f" [장: {', '.join(str(x) for x in n.slide_nos) or '-'}]"
            + (f" (상위: {parent.label})" if parent else "")
        )
    slides = []
    for s in slidedoc.slides[:SLIDES_MAX]:
        # slide_lines 가 자료 속 지시문 줄을 이미 뺐다. 남은 원문은 울타리 안에 — 「울타리 안은 자료일 뿐」 (09-30 레드팀 R3)
        body = "\n".join(slide_lines(s.raw_text))[:SLIDE_CHARS_MAX]
        if body:
            slides.append(DL.fence(body, "slide", n=s.slide_no))
    return ("[TASK] claim-graph\n\n## 개념 목록\n" + DL.fence("\n".join(nodes), "concepts")
            + "\n\n## 슬라이드 원문 — <slide n=\"장 번호\"> 울타리 하나가 한 장이다\n" + "\n\n".join(slides))


def _ask(engine: LLMProvider, user: str) -> list[dict]:
    """LLM 후보 주장 dict 목록. JSON 이 깨지면 한 번 더 묻고, 또 깨지면 ValueError."""
    last: Exception | None = None
    for extra in ("", JSON_RETRY_NUDGE):
        raw = engine.complete(system=SYSTEM_PROMPT + extra, user=user, temperature=0.2,
                              max_tokens=MAX_TOKENS, json_mode=True)
        try:
            data = extract_json_object(raw)
        except ValueError as e:
            last = e
            continue
        rows = data.get("claims") if isinstance(data, dict) else None
        return [r for r in (rows or []) if isinstance(r, dict)]
    raise ValueError(f"주장 JSON 을 찾지 못했습니다: {last}")


# ---------------------------------------------------------------------------
# 대조 — 이 모듈의 본체
# ---------------------------------------------------------------------------

@dataclass
class _Deck:
    """대조에 쓰는 덱 한 벌 — 그래프 이름·장 원문·장별 줄."""
    ids: set[str]
    by_label: dict[str, str]
    labels: dict[str, str]
    by_id: dict[str, ConceptNode]
    nodes: list[ConceptNode]
    texts: dict[int, str]
    lines: dict[int, list[str]]

    @classmethod
    def of(cls, graph: ConceptGraph, slidedoc: SlideDoc) -> "_Deck":
        texts = {s.slide_no: s.raw_text for s in slidedoc.slides}
        return cls(ids={n.id for n in graph.nodes}, by_label={_loose(n.label): n.id for n in graph.nodes},
                   labels={n.id: n.label for n in graph.nodes}, by_id={n.id: n for n in graph.nodes},
                   nodes=list(graph.nodes), texts=texts, lines={no: slide_lines(t) for no, t in texts.items()})


#: id 칸에 적힌 이름을 풀어 볼 최대 낱말 수. 이보다 길면 이름이 아니라 문장(인용을 id 칸에 옮긴 것)이다.
RESOLVE_MAX_TOKENS = 4


def _resolve_id(value, ids: set[str], by_label: dict[str, str], nodes: list[ConceptNode] | None = None) -> str:
    """
    그래프 id 면 그대로, 아니면 그 이름이 가리키는 개념의 id, 없으면 "".

    Solar 는 id 칸에 이름을 자주 적는다. 이름이 통째로 같으면 바로 받고, 아니면 규칙 추출과 **같은 잣대**
    (`resolve_label` — 이름 포함 → 변별 낱말 절반 이상)로 푼다. 09-29 P5: IR 덱의 LLM 주장 13개가 전부
    id 칸에 「높은 배송비」「구독자 수」 같은 자료 표현을 적어서, 통째 일치만 받던 때는 13개 모두 버렸다
    (그래프 id 가 프롬프트 예시 id 를 따라 한 「encoder-2」 꼴이라 뜻이 없었다).
    """
    # 09-29 실측: 목록을 「- (gap) …」 꼴로 줬더니 Solar 가 "(gap)" 을 통째로 옮겼다. 괄호는 벗긴다.
    v = str(value or "").strip().strip("()[]{}<>「」 ").strip()
    if v in ids:
        return v
    got = by_label.get(_loose(v), "")
    if got or not nodes or not v or len(R.content_tokens(v)) > RESOLVE_MAX_TOKENS:
        return got
    node = resolve_label(v, nodes)
    return node.id if node is not None else ""


def _men(deck: _Deck, nid: str, text: str, others: list[str]) -> bool:
    """개념 nid 가 text 에 나왔는가 — 맞은편 개념들과 겹치는 낱말은 빼고 본다."""
    return R.mentioned(deck.labels[nid], text, exclude=[deck.labels[o] for o in others if o in deck.labels])


#: 원인과 결과를 **잇는** 말 — 연결 어미·인과 명사·인과 동사. 「늘립니다」 같은 바꾸는 동사만으로는 인과가 아니라 계획일 수 있다.
_CAUSE_LINK_RE = re.compile(
    r"때문|해서|하여|[가-힣](?:아|어)서\s|(?:으로|로)\s*인해|탓|수록|면서|원인|이유|결과로|결과적으로|일으|야기|유발|초래|"
    r"영향|좌우|이어지|이어집|이어져|가져오|가져와|→|->")
#: 해결 장 제목으로 볼 길이 — 짧은 머리 줄만(「제안」「해결 방안」「개선 전략」).
_SOLVE_HEAD_MAX = 20


def _under_solution_head(deck: _Deck, no: int, idx: int) -> bool:
    """
    이 줄이 **해결 장**(제목·첫 줄이 제안·해결·방안 …)에 있는가. 09-29 P5 최종 평가 문제 7: 제안 장의
    「자유열람실 확충 — 좌석을 40석 늘립니다」 가 근거 없는 인과로 읽혀 5분 트랙 weak 질문이 됐다. 해결 장의 줄은
    계획이지 원인 주장이 아니다 — 인과를 잇는 말(`_CAUSE_LINK_RE`)이 있을 때만 인과로 본다.
    """
    lines = deck.lines.get(no) or []
    heads = [ln for i, ln in enumerate(lines[:2]) if i != idx and len(ln.strip()) <= _SOLVE_HEAD_MAX and not R.is_sentence(ln)]
    return any(R.is_solution_head(h) for h in heads)


def _plan_not_cause(deck: _Deck, no: int, hit: _Hit) -> bool:
    """해결 장의 줄인데 원인·결과를 잇는 말이 없다 — cause 로 받지 않는다."""
    return _under_solution_head(deck, no, hit.idx) and not _CAUSE_LINK_RE.search(hit.unit)


def _as_cause(deck: _Deck, ids: list[str], unit: str) -> tuple[str, str, list[str]] | None:
    """비교 표지 없이 인과 말투인 줄 — 줄에 나온 순서대로 원인 → 결과 (「A할수록 B가 떨어진다」·「A해서 B가 는다」)."""
    shown = [i for i in ids if _men(deck, i, unit, [x for x in ids if x != i])]
    if len(shown) < 2:
        return None
    shown.sort(key=lambda i: R.first_position(deck.labels[i], unit))
    if re.search(r"때문(?:이|입)", unit):
        shown.reverse()                     # 「B는 A 때문이다」 — 결과가 먼저 나온다
    return "cause", shown[0], shown[1:]


def _compose_support(deck: _Deck, subj: str, objs: list[str], no: int, hit: _Hit) -> tuple[str, str, list[str]] | None:
    """compose 받침 — 식(좌변=주어, 우변=요소) / 요소 둘 이상을 나열한 문장 / 목록 제목 + 항목."""
    s_label = deck.labels[subj]
    sides = R.formula_sides(hit.unit)
    if sides:
        lhs, rhs = sides
        if not R.mentioned(s_label, lhs):
            return None
        ob = [o for o in objs if R.mentioned(deck.labels[o], rhs, exclude=s_label)]
        return ("compose", subj, ob) if len(ob) >= 2 else None
    ancestor_ok = lambda ob: all(subj in _ancestors(o, deck.by_id) for o in ob)  # noqa: E731
    if not hit.title:
        ob = [o for o in objs if _men(deck, o, hit.unit, [subj])]
        if len(ob) >= 2 and (_men(deck, subj, hit.context, ob) or ancestor_ok(ob)):
            return "compose", subj, ob
    if R.is_list_heading(hit.unit):
        items = list_items(deck.lines.get(no, []), hit.idx)
        ob = [o for o in objs if any(R.mentioned(deck.labels[o], it, exclude=s_label) for it in items)]
        if len(ob) >= 2 and (R.mentioned(s_label, hit.unit) or ancestor_ok(ob)):
            return "compose", subj, ob
    return None


def _compare_direction(deck: _Deck, subj: str, objs: list[str], unit: str) -> tuple[str, list[str]]:
    """
    LLM 이 적은 비교 방향을 인용 줄의 말투로 바로잡는다 — 줄이 「주어가 작은 쪽」 이라고 말하면(「B는 A보다 덜 …」
    「B가 A보다 적다」「B는 A만큼 …지 않다」) 큰 쪽을 주어로 뒤집는다 (09-30 G-A1). 줄에서 두 쪽이 안 갈리면 그대로 둔다.
    """
    s_label = deck.labels[subj]
    for big, small in R.compare_sides(unit):
        if R.mentioned(s_label, small, exclude=big) and not R.mentioned(s_label, big, exclude=small):
            flip = [o for o in objs if R.mentioned(deck.labels[o], big, exclude=small)]
            if flip:
                return flip[0], [subj]
        if R.mentioned(s_label, big, exclude=small):
            break
    return subj, objs


def _supported(deck: _Deck, kind: str, subj: str, objs: list[str], no: int,
               hit: _Hit) -> tuple[str, str, list[str]] | None:
    """
    인용 한 줄이 주장을 받치면 (kind, subject, objects) — 받치는 만큼으로 고친 것, 아니면 None.

    고침은 좁히기만 한다: 줄에 안 나온 objects 는 빼고, absolute 의 주어가 줄에 없으면 줄에 가장 뚜렷한 개념으로,
    비교 표지 없는 「compare」 가 인과 말투면 cause 로. 새 관계를 지어내지 않는다.
    """
    unit, ctx = hit.unit, hit.context
    if kind == "absolute":
        if not R.absolute_marker(unit) or hit.title:
            return None
        # 주어는 그 줄이 **통째로** 부르는 개념 — 반쯤 걸친 이름보다 줄에 그대로 있는 이름이 질문에서 자연스럽다
        n = best_node(unit, deck.nodes, slide_no=no)
        if R.mention_score(deck.labels[subj], unit) >= 1 or (
                R.mentioned(deck.labels[subj], unit) and (n is None or R.mention_score(n.label, unit) < 1)):
            return "absolute", subj, []
        return ("absolute", n.id, []) if n is not None else None
    if kind == "compose":
        return _compose_support(deck, subj, objs, no, hit)
    if kind == "compare":
        if not R.COMPARE_RE.search(unit):
            return None
        subj, objs = _compare_direction(deck, subj, objs, unit)
    if kind == "contrast":
        ob = [o for o in objs if _men(deck, o, unit, [subj])]
        return ("contrast", subj, ob) if ob and _men(deck, subj, unit, objs) else None
    if kind == "solve":
        # 문제 칸 + 해결 칸이 한 행인 표 — 짝 자체가 받침이다 (주어는 해결 칸·장 제목에서 온 것이라 행에 없을 수 있다)
        cells = R.table_cells(deck.lines[no][hit.idx])
        if len(cells) >= 2 and R.SOLVE_ACT_RE.search(" ".join(cells[1:])):
            ob = [o for o in objs if R.mentioned(deck.labels[o], cells[0])]
            if ob:
                return "solve", subj, ob
    if kind == "solve" and not any(R.solves(unit, deck.labels[o]) for o in objs):
        # 해결 말투가 옆 줄에 있으면 그 줄이 목적어를 불러야 한다 (「시세 지도 — …」 + 「정보 비대칭을 해소합니다」)
        near = [x for x in ctx.split("\n") if any(R.solves(x, deck.labels[o]) and _men(deck, o, x, [subj]) for o in objs)]
        if not near:
            return None
    if kind == "solve" and deck.lines.get(no):
        # 해결 장 제목은 해결책의 이름이다 — 주어가 줄·옆 줄에 없어도 제목이 부르면 받는다 (`rule_solve_lines`)
        ctx = ctx + "\n" + deck.lines[no][0]
    if kind == "cause" and _plan_not_cause(deck, no, hit):
        return None
    if kind == "cause" and not R.CAUSE_RE.search(unit):
        # 표 행·목록 칸은 인과를 제목·소개 줄이 말한다 (「흐름을 끊는 요인」 밑의 「| 소음 | 밤늦은 공사 |」)
        if not (R.table_cells(deck.lines[no][hit.idx]) and R.CAUSE_RE.search(ctx)):
            return None
    if not _men(deck, subj, ctx, objs):
        return None
    # 해결 줄은 문제를 반대 극성으로 부르기도 한다 — 「산책 시간 확보를 돕습니다」 가 「산책 시간 부족」 을 푼다 (변수를 다 부르면 받는다)
    ob = [o for o in objs if _men(deck, o, ctx, [subj]) or (kind == "solve" and R.names_variable(deck.labels[o], ctx))]
    return (kind, subj, ob) if ob else None


def _reread(deck: _Deck, ids: list[str], no: int, hit: _Hit) -> tuple[str, str, list[str]] | None:
    """
    적힌 kind 로는 줄이 안 받칠 때 **줄의 말투**로 다시 읽는다 — 인과 말투면 cause(줄에 나온 순서),
    강한 단정 표지가 있으면 absolute. kind 는 자료의 말투가 정한다 (프롬프트 규칙을 코드가 지킨다).
    """
    if R.CAUSE_RE.search(hit.unit) and not _plan_not_cause(deck, no, hit) and (got := _as_cause(deck, ids, hit.unit)) is not None:
        return got
    if R.absolute_marker(hit.unit, strong_only=True) and not hit.title:
        return _supported(deck, "absolute", ids[0], [], no, hit)
    return None


def _check(raw: dict, deck: _Deck) -> Claim | str:
    """후보 하나 → 대조·받침을 통과한 Claim, 아니면 버린 까닭(kind·id·objects·quote·question·support) — 로그로 센다."""
    kind = str(raw.get("kind", "") or "").strip().lower()
    if kind not in CLAIM_KINDS:
        return "kind"
    subj = _resolve_id(raw.get("subject_id"), deck.ids, deck.by_label, deck.nodes)
    if not subj:
        return "id"
    objs: list[str] = []
    for o in raw.get("object_ids") or []:
        oid = _resolve_id(o, deck.ids, deck.by_label, deck.nodes)
        # 주어와 같은 뜻의 다른 이름(F-07 이 겹쳐 둔 노드)은 목적어가 아니다 — 「A 가 A 를 해결한다」. 반대 극성은 짝이다:
        # 「시간 확보」 가 「시간 부족」 을 푼다 (09-30 G-A3 — 예전엔 수식어를 떼고 같은 개념으로 봐서 이 주장을 버렸다)
        if oid and oid != subj and oid not in objs and not R.same_sense(deck.labels[oid], deck.labels[subj]):
            objs.append(oid)
    if kind != "absolute" and not objs:
        return "objects"
    # 프롬프트는 주장마다 인용 하나를 평평하게(slide_no·quote) 받는다 — 중첩 evidence 스키마는 Solar 가 한 줄을
    # 30번 되풀이하다 토큰이 끊겼다 (09-29). 규칙 주장·옛 모양(evidence 목록)도 같이 받는다.
    flat = [{"slide_no": raw.get("slide_no"), "quote": raw.get("quote")}] if raw.get("quote") else []
    hits: list[tuple[int, _Hit]] = []
    for ev in flat + list(raw.get("evidence") or []):
        if not isinstance(ev, dict):
            continue
        try:
            no = int(ev.get("slide_no") or 0)
        except (TypeError, ValueError):
            continue
        hits.extend((no, h) for h in locate_quote(str(ev.get("quote", "") or ""), deck.texts.get(no, "")))
    if not hits:
        return "quote"
    hits = [(no, h) for no, h in hits if not R.is_question(h.unit)]
    if not hits:
        return "question"
    backed = [(r, no, h) for no, h in hits if (r := _supported(deck, kind, subj, objs, no, h)) is not None]
    if not backed:
        backed = [(r, no, h) for no, h in hits if (r := _reread(deck, [subj, *objs], no, h)) is not None]
    if not backed:
        return "support"
    (kind2, subj2, objs2), _, first = backed[0]
    quotes: list[ClaimQuote] = []
    for r, no, h in backed:
        if r[:2] == (kind2, subj2) and all((q.slide_no, norm_for_match(q.quote)) != (no, norm_for_match(h.quote)) for q in quotes):
            quotes.append(ClaimQuote(no, h.quote))
    text = " ".join(str(raw.get("text", "") or "").split())[:160]
    if not text or kind2 != kind or first.glued:
        text = first.quote[:160] or f"{deck.labels.get(subj2, subj2)} {kind2} " + ", ".join(deck.labels.get(o, o) for o in objs2)
    return Claim(id="", kind=kind2, subject_id=subj2, object_ids=objs2, text=text, evidence=quotes[:EVIDENCE_MAX])


def _merge(claims: list[Claim]) -> list[Claim]:
    """같은 (kind, subject, objects) 는 하나로 — 인용은 합친다. 앞(LLM)의 text 를 남긴다."""
    out: dict[tuple, Claim] = {}
    for c in claims:
        key = (c.kind, c.subject_id, tuple(sorted(c.object_ids)))
        if c.kind == "absolute":
            # 단정은 줄이 주장이다 — 같은 줄을 주어만 달리 두 번 적으면(LLM·규칙) 탐침이 같은 줄을 두 번 묻는다
            key = ("absolute", c.evidence[0].slide_no, norm_for_match(c.evidence[0].quote))
        have = out.get(key)
        if have is None:
            out[key] = c
            continue
        for q in c.evidence:
            if len(have.evidence) >= EVIDENCE_MAX:
                break
            if all((q.slide_no, norm_for_match(q.quote)) != (h.slide_no, norm_for_match(h.quote)) for h in have.evidence):
                have.evidence.append(q)
    return _absorb_subsets(list(out.values()))


def _quote_keys(c: Claim) -> set[tuple[int, str]]:
    return {(q.slide_no, norm_for_match(q.quote)) for q in c.evidence}


def _absorb_subsets(claims: list[Claim]) -> list[Claim]:
    """
    같은 kind·subject 에 **같은 인용**을 든 두 주장 중 objects 가 부분집합인 쪽은 큰 쪽에 합친다.

    09-29 실측: LLM 은 「A = B × C × D」 를 C·D 둘로만 적었다(B 노드 이름이 자료 표현과 달라서). 규칙은 셋을
    다 잡았다. 둘 다 남기면 F-08 의 형제 우선순위 탐침이 같은 식을 두 번 센다.
    """
    keep: list[Claim] = []
    for c in sorted(claims, key=lambda c: -len(c.object_ids)):
        big = next((k for k in keep if k.kind == c.kind and k.subject_id == c.subject_id
                    and set(c.object_ids) < set(k.object_ids) and _quote_keys(c) & _quote_keys(k)), None)
        if big is None:
            keep.append(c)
            continue
        for q in c.evidence:
            if len(big.evidence) < EVIDENCE_MAX and (q.slide_no, norm_for_match(q.quote)) not in _quote_keys(big):
                big.evidence.append(q)
    return keep


def _problem_rows(deck: _Deck) -> list[tuple[int, str, str, str]]:
    """
    문제·원인 목록의 항목 줄 → (장, 노드 id, 항목 줄, 설명 칸 글). 목록 제목이 문제 명사로 끝나고(「…세 가지 문제」
    「…대표적인 원인」), F-07 후처리가 믿는 목록(`_graph_items.item_groups` — 개수 말과 항목 수가 맞거나, 개수 말 없이
    셋 이상)만 — 설명 문장·식 줄을 항목으로 읽지 않게. 표 행이면 첫 칸이 이름이고 나머지 칸이 설명이다.
    """
    out: list[tuple[int, str, str, str]] = []
    for no, raw in deck.texts.items():
        for g in GI.item_groups([(no, raw)]):
            if g.kind != "list" or not R.is_problem_head(g.head):
                continue
            for item in g.items:
                node = resolve_label(item, deck.nodes, slide_no=no)
                if node is None or not R.mentioned(node.label, item):
                    continue
                row = next((ln for ln in deck.lines.get(no, []) if item in R.item_text(ln)), item)
                out.append((no, node.id, _tidy(row), " ".join(R.table_cells(row)[1:])))
    return out


#: 설명 칸 낱말로 칠 수 없는 한 글자 말 — 의존 명사·접속어.
_ONE_CHAR_STOP = frozenset("등수것및또더안밖중후전간곳점때개명원년월일")


def _desc_tokens(desc: str) -> list[str]:
    """설명 칸의 낱말 — 한 글자 말도 받는다(「빛·소음」 의 「빛」), 의존 명사·숫자는 뺀다."""
    return [t for t in norm_tokens(desc) if not t.isdigit() and (len(t) >= 2 or (t not in _ONE_CHAR_STOP and _HANGUL_1.match(t)))]


_HANGUL_1 = re.compile(r"^[가-힣]$")


def _addressed_rows(claims: list[Claim], deck: _Deck) -> list[Claim]:
    """
    해결 줄이 다른 장 문제·원인 목록의 **항목 줄**(이름, 또는 그 줄에만 있는 설명 낱말 **둘 이상**)을 부르면 solve(해결 주어 →
    그 항목)을 더한다 — 인용은 해결 줄 + 항목 줄. 09-29 graph_ab 남은 문제 2: 수면 덱 원인 표 「| 환경 | 빛·소음·높은 온도 |」 를
    해결 행 「카페인·음주·빛·소음 줄이기」 가 다루는데 이름 「환경」 이 안 나와서 미해결 탐침이 났다. 설명 낱말 하나(「계약」)로는
    짝을 짓지 않는다 — 전세 덱 「보증료 지원 — 첫 전세 계약의…」 가 「정보 비대칭(…계약 전에 알기 어렵다)」 을 푼 것이 됐다.
    여러 항목 줄에 두루 나오는 낱말도 쓰지 않는다. 새 관계를 지어내지 않는다 — 두 줄이 다 원문이다.
    """
    rows = _problem_rows(deck)
    if not rows:
        return []
    counts: dict[str, int] = {}
    for _, _, _, desc in rows:
        for t in set(_desc_tokens(desc)):
            counts[t] = counts.get(t, 0) + 1
    out: list[Claim] = []
    for c in (x for x in claims if x.kind == "solve"):
        for q in c.evidence:
            words = norm_tokens(q.quote)
            for no, nid, row, desc in rows:
                if no == q.slide_no or nid in c.object_ids or nid == c.subject_id:
                    continue
                own = [t for t in _desc_tokens(desc) if counts.get(t) == 1]
                shared = sum(1 for t in own if any(w == t or (len(t) >= 2 and R.tok_match(w, t)) for w in words))
                if R.mention_score(deck.labels[nid], q.quote) >= 1 or (own and shared >= min(2, len(own))):
                    out.append(Claim(id="", kind="solve", subject_id=c.subject_id, object_ids=[nid], text=q.quote,
                                     evidence=[ClaimQuote(q.slide_no, q.quote), ClaimQuote(no, row)]))
    return out


def _backed_elsewhere(c: Claim, deck: _Deck) -> bool:
    """
    인과의 두 개념이 **덱의 다른 줄**에서 수치·출처와 함께 나오는가 — 가설 장의 「A가 높을수록 B가 는다」 를
    결과 장의 「A 조건의 B가 39% 컸다」 가 받치는 구조 (09-29 벤치 과학 덱). 두 이름이 다 나와야 한다.
    """
    s_label = deck.labels.get(c.subject_id, "")
    o_labels = [deck.labels[o] for o in c.object_ids if o in deck.labels]
    for lines in deck.lines.values():
        for line in lines:
            if not (has_support(line) and R.mentioned(s_label, line, exclude=o_labels)):
                continue
            if any(R.mentioned(o, line, exclude=s_label) for o in o_labels):
                return True
    return False


def _attach_joint_lines(claims: list[Claim], deck: _Deck) -> None:
    """
    compose 의 요소가 **함께** 필요하다는 줄(「둘 다 필요하다」「하나만으로는 …」「A뿐 아니라 B도」)을 그 compose 의
    인용에 붙인다 — F-08 의 형제 우선순위 탐침이 자료가 부정한 「하나만 고른다면」 을 묻지 않게 (_probes 가 본다).
    찾는 장: compose 인용 장 + 요소 둘 이상이 함께 나온 장 (그래프 slide_nos).
    """
    for c in claims:
        if c.kind != "compose":
            continue
        slides = {q.slide_no for q in c.evidence}
        counts: dict[int, int] = {}
        for o in c.object_ids:
            for no in deck.by_id[o].slide_nos if o in deck.by_id else []:
                counts[no] = counts.get(no, 0) + 1
        slides |= {no for no, k in counts.items() if k >= 2}
        have = _quote_keys(c)
        for no in sorted(slides):
            line = next((x for x in deck.lines.get(no, []) if R.both_needed(x) and not R.is_question(x)), "")
            if line and (no, norm_for_match(line)) not in have:
                c.evidence.append(ClaimQuote(no, _tidy(line)))
                break


def validate_claims(raw_claims: list[dict], graph: ConceptGraph, slidedoc: SlideDoc,
                    extra: list[Claim] | None = None) -> tuple[list[Claim], int]:
    """
    LLM 후보(dict) + 규칙 주장 → (대조를 통과한 Claim 목록, 버린 후보 수). id·has_support 는 여기서 채운다.

    규칙 주장도 **같은 대조를 거친다** — 규칙이 만든 인용도 원문 한 줄에 없거나 주장을 안 받치면 버린다.
    """
    deck = _Deck.of(graph, slidedoc)
    kept: list[Claim] = []
    reasons: dict[str, int] = {}
    for raw in list(raw_claims) + [c.to_dict() for c in (extra or [])]:
        c = _check(raw, deck)
        if isinstance(c, str):
            reasons[c] = reasons.get(c, 0) + 1
        else:
            kept.append(c)
    dropped = sum(reasons.values())
    if dropped:
        # 무엇 때문에 버렸는지 남긴다 — 「주장이 왜 적지」 를 인용 탓인지 받침 탓인지 가를 수 있어야 한다.
        sys.stderr.write("[f26] 버린 후보 " + " ".join(f"{k}={v}" for k, v in sorted(reasons.items())) + "\n")
    merged = _merge(kept + _addressed_rows(kept, deck))
    for c in merged:
        c.has_support = any(line_support(deck.texts.get(q.slide_no, ""), q.quote) for q in c.evidence) \
            or (c.kind == "cause" and _backed_elsewhere(c, deck))
    _attach_joint_lines(merged, deck)
    order = {k: i for i, k in enumerate(CLAIM_KINDS)}
    merged.sort(key=lambda c: (min(q.slide_no for q in c.evidence), order[c.kind], c.subject_id, c.object_ids))
    merged = _within_budget(merged, CLAIM_MAX)
    _assign_ids(merged, deck)
    return merged, dropped


def _within_budget(claims: list[Claim], cap: int) -> list[Claim]:
    """
    CLAIM_MAX 안에서 **장마다 고루** 남긴다 — 장 순서로 앞에서 자르면 결론·정리 장(발표 끝)의 주장이 먼저 잘렸다
    (09-30 레드팀 G-A20). 장마다 한 개씩 돌아가며 채우고, 돌 때는 앞 장·끝 장을 번갈아 본다 (주장 있는 장이 상한보다
    많아도 결론 장이 남는다). 한 장 안에서는 이미 정렬된 순서(kind 순)다. 결과는 다시 장 순서.
    """
    if len(claims) <= cap:
        return claims
    by_slide: dict[int, list[Claim]] = {}
    for c in claims:
        by_slide.setdefault(min(q.slide_no for q in c.evidence), []).append(c)
    nos = sorted(by_slide)
    ends = [nos[i // 2] if i % 2 == 0 else nos[-1 - i // 2] for i in range(len(nos))]
    picked: set[int] = set()
    depth = 0
    while len(picked) < cap and any(len(by_slide[no]) > depth for no in nos):
        for no in ends:
            if len(picked) < cap and len(by_slide[no]) > depth:
                picked.add(id(by_slide[no][depth]))
        depth += 1
    return [c for c in claims if id(c) in picked]


def _claim_key(c: Claim, deck: _Deck) -> str:
    """
    주장의 **내용 열쇠** — kind · 주어 이름 · 목적어 이름 · 첫 인용(장 번호 포함)의 해시. 노드 id 가 아니라 이름으로 만든다 —
    그래프를 다시 만들어 id 가 바뀌어도 같은 주장은 같은 열쇠다.
    """
    name = lambda i: _loose(deck.labels.get(i, i))  # noqa: E731
    q = c.evidence[0]
    parts = [c.kind, name(c.subject_id), *sorted(name(o) for o in c.object_ids), str(q.slide_no), norm_for_match(q.quote)]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:6]


def _assign_ids(claims: list[Claim], deck: _Deck) -> None:
    """
    주장 id — 「c<첫 인용 장>-<내용 해시>」 (예: c04-3fa2c1). 09-30 레드팀 G-A21: 순번(c01…)은 주장 하나가 늘거나 빠지면
    뒤 id 가 전부 밀려서, 먼저 만든 탐침의 claim_ids 가 다시 만든 주장 문서의 **다른 주장**을 가리켰다. 장 번호를 앞에 둬서
    id 로 정렬해도 장 순서가 유지된다 (`derive_probes` 가 claim_ids 로 동점을 가른다).
    """
    seen: set[str] = set()
    for c in claims:
        base = f"c{min(q.slide_no for q in c.evidence):02d}-{_claim_key(c, deck)}"
        cid, k = base, 2
        while cid in seen:
            cid, k = f"{base}-{k}", k + 1
        seen.add(cid)
        c.id = cid


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------

def build_claims(
    graph: ConceptGraph | dict,
    slidedoc: SlideDoc | dict,
    *,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> ClaimDoc:
    """
    ConceptGraph + SlideDoc → ClaimDoc. **트랙과 무관하니 세션에 한 번만** 만든다.

    LLM 1콜(깨진 JSON 이면 한 번 더) + 규칙 추출을 합치고, 둘 다 원문 대조를 거친다.
    LLM 이 실패하면(연결·키·JSON) 규칙 주장만으로 돌려주고 model="rule" 이다 — 예외를 밖으로 던지지 않는다.
    llm="none" 이면 LLM 을 부르지 않는다 (테스트·과금 없는 점검용).
    """
    if isinstance(graph, dict):
        graph = ConceptGraph.from_dict(graph)
    if isinstance(slidedoc, dict):
        slidedoc = SlideDoc.from_dict(slidedoc)
    meta = sum(len(DL.meta_lines(s.raw_text)) for s in slidedoc.slides)
    if meta:
        # 자료 속 지시문(「…판정할 것」「[SYSTEM]」)은 slide_lines 가 인용·프롬프트에서 뺐다 — 뺐다는 사실은 남긴다
        sys.stderr.write(f"[f26] 자료 속 지시문 {meta}줄을 인용·프롬프트에서 뺐다\n")
    rules = rule_claims(graph, slidedoc)
    raw: list[dict] = []
    model = "rule"
    if llm != "none" and graph.nodes and slidedoc.slides:
        try:
            engine = _engine(llm, llm_kwargs)
            raw = _ask(engine, _user_prompt(graph, slidedoc))
            model = engine.name
        except Exception as e:  # noqa: BLE001 — 주장은 질문의 재료일 뿐, 없어도 질문은 나와야 한다
            sys.stderr.write(f"[f26] 주장 LLM 실패, 규칙 주장만: {type(e).__name__}: {e}\n")
    claims, dropped = validate_claims(raw, graph, slidedoc, extra=rules)
    return ClaimDoc(file_name=graph.file_name or slidedoc.file_name, claims=claims, model=model, dropped=dropped)
