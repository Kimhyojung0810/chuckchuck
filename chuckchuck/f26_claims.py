"""
[F-26] 주장 그래프 — 개념 사이의 **주장**을 자료 원문 인용과 함께 뽑는 모듈입니다.
ConceptGraph + SlideDoc → ClaimDoc.

    from chuckchuck.f26_claims import build_claims
    claims = build_claims(graph, slidedoc, llm="solar")                 # 세션에 한 번
    triage = triage_questions(graph, ..., claims=claims.to_dict())      # F-08 이 탐침을 찾는다

왜 있나 (2026-09-29 실측, 수면 덱):
  질문이 「수면의 질이 시간보다 중요한 이유를 … 세 가지 요소(시간, 연속성, 규칙성)를 바탕으로
  설명해 주세요」 로 나왔다. 1장은 「수면 시간보다 중요한 수면의 질」, 4장은 「수면의 질 = 시간 ×
  연속성 × 규칙성」 이다 — **시간보다 중요하다면서 시간이 그 요소** 라는 긴장이 자료 안에 있는데,
  개념 그래프(F-07)는 위계·연결만 알아서 코드가 이걸 볼 수 없었다. 그래서 LLM 이 긴장을 오히려
  질문의 전제로 삼켰다. 주장(compose·compare·cause·solve·absolute·contrast)을 따로 두면 F-08 이
  tension·unsolved·unsupported_cause 같은 탐침을 **코드로** 찾는다.

F-07 과 LLM 호출을 합치지 않는다 — F-07 프롬프트에 칸을 더했다가 위계가 흔들려 되돌린 적이 있다
(노드 links 칸 요구안). 그래서 한 번 더, 따로 부른다. 이 모듈의 핵심은 LLM 이 아니라 **대조**다:

1. LLM 은 주장 후보와 인용을 낸다 (1콜, JSON 이 깨지면 한 번 더).
2. 코드가 그래프 밖 id·모르는 kind 를 버리고, 인용이 **그 장 원문에 실제로 있는지** 대조한다
   (공백·따옴표를 정규화한 부분 문자열, 또는 글 상자 한 줄과 90% 이상 일치). 통과한 인용이 하나도
   없는 주장은 버린다 — 지어낸 인용 위에 선 질문은 교수 앞에서 거짓말이 된다.
3. has_support(그 장에 수치·출처가 있는가)는 코드가 채운다. LLM 에게 묻지 않는다.
4. 구조가 뻔한 것(「A = B × C × D」 식, 「A보다 중요한 B」)은 LLM 없이 규칙으로도 뽑는다.
   LLM 이 놓치거나 죽어도 수면 덱의 긴장은 남는다.

모듈 규칙(DEV_POLICY §4): 다른 fXX 를 import 하지 않는다. 유틸(_evidence·_match·_json_text)만 쓴다.
"""

from __future__ import annotations

import difflib
import os
import re
import sys

from ._evidence import clean_slide_text, slide_units
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
#: 주장 하나에 남길 인용 최대 수.
EVIDENCE_MAX = 3
#: 인용이 원문 한 줄과 이만큼 같으면(문자 단위 유사도) 옮겨 적은 것으로 본다. 띄어쓰기·조사 한둘 차이를 받는다.
FUZZY_MIN = 0.9
#: 정규화한 뒤 이보다 짧은 인용은 버린다 — 「시간」 두 글자는 어디에나 있어서 근거가 못 된다.
QUOTE_MIN_CHARS = 4
#: 프롬프트에 싣는 장 본문 상한(자). 20장 덱이면 ~20K 자 — Solar 입력으로 넉넉하다.
SLIDE_CHARS_MAX = 1200
#: 프롬프트에 싣는 장 수 상한. 넘으면 앞에서부터 (부록·참고문헌이 뒤에 온다).
SLIDES_MAX = 40
MAX_TOKENS = 3000

SYSTEM_PROMPT = """당신은 발표 자료의 논증 구조 분석가다.
개념 목록과 슬라이드 원문을 받아, 자료가 **개념 사이에 실제로 하는 주장**을 뽑는다.

kind 는 여섯 가지 중 하나다 (subject → objects 방향):
- compose  : subject 는 objects 로 이뤄진다        예) 「수면의 질 = 시간 × 연속성 × 규칙성」
- compare  : subject 가 objects 보다 더 중요·크다  예) 「수면 시간보다 중요한 수면의 질」 → subject=수면의 질, objects=[수면 시간]
- cause    : subject(원인)가 objects(결과)를 일으키거나 끊는다 예) 「카페인이 수면 주기를 끊는다」 → subject=카페인, objects=[연속성]
- solve    : subject(해결책)가 objects(문제·요소)를 해결한다 예) 「일정한 기상 시간 유지」 → subject=실천 방법, objects=[규칙성]
- absolute : subject 에 대한 단정 (반드시·완전히·항상·절대) — objects 는 비워도 된다
- contrast : subject 와 objects 를 맞세운다        예) 깊은 수면 ↔ REM 수면

kind 고르는 법 — 자료의 말투가 정한다. compare 는 「보다·대비·vs·더」 가 있을 때만 쓴다:
- compose  ← 「=」「세 가지·다섯 가지 요인·조건·구성」
- cause    ← 「때문에·→·일으킨다·끊는다·늘린다·만든다·증가·감소」
- solve    ← 「해결·방법·줄이기·유지·규칙·통제」
- absolute ← 「반드시·완전히·항상·절대·하나도 없다·예외 없는」
- contrast ← 「A가 아니라 B」「↔」

규칙:
- subject_id·object_ids 는 개념 목록의 「id:」 값을 **글자 그대로** 옮긴다 (괄호·이름 없이). 목록에 없는 id 는 버려진다.
- slide_no 는 그 주장이 적힌 장 번호, quote 는 그 장 원문에서 **한 줄을 글자 그대로 복사한** 것이다.
  요약·의역·말줄임 금지. 코드가 원문과 대조해서 없는 인용은 버리고, 인용이 버려진 주장도 버린다.
- 자료에 적힌 주장만. 당신의 상식으로 관계를 지어내지 마라. 수치 하나하나를 주장으로 만들지 마라 — 개념 사이의 관계만.
- 슬라이드 1 부터 마지막 장까지 **순서대로** 훑으며, 한 장에서 많아야 2개. 같은 주장을 두 번 적지 마라.
- 서로 다른 장에 걸친 주장(1장의 비교와 4장의 식)도 각각 따로 적는다 — 둘이 부딪쳐도 그대로 둔다.
- text 는 주장 한 줄 (자료 표현에 가깝게). 모두 합쳐 5~15개.
- 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마:
{ "claims": [ { "slide_no": 4, "kind": "compose", "subject_id": "<목록의 id>", "object_ids": ["<목록의 id>"],
                "quote": "<그 장 원문 한 줄 그대로>", "text": "…" } ] }
"""

JSON_RETRY_NUDGE = """
[재요청] 직전 응답이 완전한 JSON 객체가 아니어서 버렸다.
코드펜스·주석·말머리·말끝 문장 없이, 출력 스키마 그대로의 JSON 객체 하나만 다시 출력하라.
"""

# ---------------------------------------------------------------------------
# 원문 정규화 · 인용 대조
# ---------------------------------------------------------------------------

_FIGCAPTION_RE = re.compile(r"<figcaption>.*?</figcaption>", re.S | re.I)
_IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_TAG_RE = re.compile(r"<[^>]+>")
#: 대조 때 지우는 문자 — 공백, 따옴표 모양(“”‘’「」『』), 표 칸(|), 글머리표. 모델이 따옴표를 곧은 것으로
#: 바꾸거나 표 칸을 빼고 옮겨도 같은 줄로 본다. 가운뎃점(·)·식 기호는 뜻이 있어 남긴다.
_MATCH_DROP_RE = re.compile(r"[\s\"'“”‘’「」『』`|•▪■◦*#]+")
_DASH_RE = re.compile(r"[–—−]")
_ELLIPSIS_RE = re.compile(r"(…|\.\.\.)+$")
_PAGE_NO_RE = re.compile(r"^[\d\s/|.·-]+$")
_BULLET_ONLY_RE = re.compile(r"^[\s•▪■◦·*\-–—]+$")
#: 식을 잇는 기호. 이 기호로 끝나거나 시작하거나 이것만 있는 줄은 옆 줄과 한 식이다.
_OPERATORS = "=×+·*÷→"
_OP_EDGE_RE = re.compile(rf"[{re.escape(_OPERATORS)}]$")
_OP_START_RE = re.compile(rf"^[{re.escape(_OPERATORS)}]")
_OP_ONLY_RE = re.compile(rf"^[{re.escape(_OPERATORS)}\s]+$")


def _strip_markup(text: str) -> str:
    text = _FIGCAPTION_RE.sub(" ", text or "")
    text = _IMAGE_MD_RE.sub(" ", text)
    return _TAG_RE.sub(" ", text)


def norm_for_match(text: str) -> str:
    """대조용 정규화 — 마크업·공백·따옴표·표 칸을 지우고 대시를 하나로, 영문은 소문자로."""
    text = _DASH_RE.sub("-", _strip_markup(text))
    return _MATCH_DROP_RE.sub("", text).lower()


def slide_lines(raw_text: str) -> list[str]:
    """
    장 원문을 **줄 그대로** (마크업만 걷고) — 프롬프트에 실어 모델이 한 줄을 복사하게 하고, 규칙 추출이 읽는다.

    `slide_units` 와 달리 짧은 줄도 버리지 않는다 (「연속성 저하」 같은 표 칸이 주장의 재료다).
    식만은 잇는다 — PPT 는 「수면의 질 =」「시간」「×」「연속성」 을 글 상자마다 따로 뽑는다.
    """
    out: list[str] = []
    for line in (raw_text or "").split("\n"):
        # 줄마다 clean_slide_text — 이미지 캡션이 새어 나온 긴 영문 설명(「The bar chart compares…」)도 걷는다 (slide_units 와 같은 처리)
        line = clean_slide_text(line)
        if not line or _PAGE_NO_RE.match(line) or _BULLET_ONLY_RE.match(line):
            continue
        if out and (_OP_EDGE_RE.search(out[-1]) or _OP_START_RE.match(line) or _OP_ONLY_RE.match(line)):
            out[-1] = f"{out[-1]} {line}"
        else:
            out.append(line)
    return out


def verify_quote(quote: str, raw_text: str) -> str:
    """
    인용이 이 장 원문에 **실제로 있으면** 남길 인용 문자열, 없으면 "".

    - 정규화한 인용이 정규화한 원문의 부분 문자열이면 인용(공백만 접은 것)을 그대로 남긴다.
    - 아니면 원문의 글 상자 한 줄(`slide_units`·`slide_lines`)과 FUZZY_MIN 이상 같을 때 **원문 쪽 줄**을 남긴다 —
      모델이 조사 하나 바꿔 옮겼어도, 화면에 나가는 건 자료에 있는 글자다.
    """
    quote = _ELLIPSIS_RE.sub("", " ".join((quote or "").split())).strip()
    nq = norm_for_match(quote)
    if len(nq) < QUOTE_MIN_CHARS or not raw_text:
        return ""
    if nq in norm_for_match(raw_text):
        return _tidy(quote)
    best, best_ratio = "", 0.0
    for unit in (*slide_units(raw_text), *slide_lines(raw_text)):
        nu = norm_for_match(unit)
        if not nu:
            continue
        ratio = difflib.SequenceMatcher(None, nq, nu, autojunk=False).ratio()
        if ratio > best_ratio:
            best, best_ratio = unit, ratio
    return _tidy(best) if best_ratio >= FUZZY_MIN else ""


def _tidy(quote: str) -> str:
    """표 한 행을 인용하면 「| 음주 | 수면 후반 각성 |」 이 된다 — 바깥 칸막이만 걷는다 (대조는 칸막이를 무시하니 그대로 통과한다)."""
    return quote.strip().strip("|").strip()


# ---------------------------------------------------------------------------
# 근거 표시 (has_support) — 코드가 정한다
# ---------------------------------------------------------------------------

#: 숫자+단위. 「4번 슬라이드」 같은 자료 안 참조는 수치가 아니다 (09-29 수면 7장) — 먼저 지운다.
_SLIDE_REF_RE = re.compile(r"\d+\s*(?:번\s*)?(?:슬라이드|장|쪽|페이지|page|slide)", re.I)
_NUM_UNIT_RE = re.compile(
    r"\d[\d,.]*\s*(?:%|퍼센트|배|명|회|번|시간|분|초|년|개월|주|일|세|살|kg|g|mg|ml|l|km|m|cm|원|달러|점|건|개|곳|hz|ms|db|위)(?![가-힣a-z])"
    r"|\d[\d,.]*\s*[-–~]\s*\d[\d,.]*\s*(?:%|시간|분|회|명|배|년)",
    re.I,
)
_PERCENT_RE = re.compile(r"\d\s*%")
_CITATION_RE = re.compile(
    r"\((?:[^()]*?)(?:19|20)\d{2}[a-z]?\)|et\s+al\.?|(?<!\d)(?:19|20)\d{2}(?:년)?\s*(?:연구|조사|보고|발표)"
    r"|\[\d{1,3}\]|doi\s*:|10\.\d{4,9}/",
    re.I,
)
_RESEARCH_WORD_RE = re.compile(r"연구|조사|실험|논문|통계|보고서|학회|저널|메타\s*분석|study|survey|experiment|paper", re.I)


def has_support(raw_text: str) -> bool:
    """이 장에 수치(숫자+단위·퍼센트)·인용 표기(연도·et al.·DOI)·연구 언급이 있는가."""
    text = _SLIDE_REF_RE.sub(" ", _strip_markup(raw_text or ""))
    return bool(
        _NUM_UNIT_RE.search(text) or _PERCENT_RE.search(text)
        or _CITATION_RE.search(text) or _RESEARCH_WORD_RE.search(text)
    )


# ---------------------------------------------------------------------------
# 개념 이름 대조 — 규칙 추출이 쓴다
# ---------------------------------------------------------------------------

_QUOTE_MARK_RE = re.compile(r"[\"'“”‘’「」『』()\[\]]")


def _loose(text: str) -> str:
    return re.sub(r"\s+", "", _QUOTE_MARK_RE.sub("", text or "")).lower()


def _tok_in(outer: str, inner: str) -> bool:
    """토큰 하나가 다른 토큰에 든다 — 한글은 조사가 붙어도 같다 (「시간보다」 ∋ 「시간」)."""
    return outer == inner or (len(inner) >= 2 and inner in outer)


def resolve_label(phrase: str, nodes: list[ConceptNode], exclude: str = "") -> ConceptNode | None:
    """
    자료의 한 구절이 가리키는 개념. 없으면 None.

    1. 이름이 통째로 같다 (공백·따옴표 무시)
    2. 구절이 개념 이름을 품는다 — 가장 긴 이름 (「핵심 수면의 질」 → 수면의 질)
    3. 구절의 **변별 낱말**(맞은편 구절에도 있는 낱말은 뺀다 — 「수면 시간보다 … 수면의 질」 의 「수면」)이
       모두 이름에 든다 — 이름의 군더더기 낱말이 적은 쪽, weight 큰 쪽, id 순.

    같은 규칙을 compose·compare 가 함께 쓰므로, 같은 「시간」 은 두 주장에서 같은 개념이 된다 —
    그래야 F-08 이 compare 와 compose 의 겹침(tension)을 id 로 찾는다.
    """
    want = _loose(phrase)
    if not want:
        return None
    for n in nodes:
        if _loose(n.label) == want:
            return n
    ptoks = norm_tokens(_QUOTE_MARK_RE.sub(" ", phrase))
    contained = []
    for n in nodes:
        ltoks = norm_tokens(n.label)
        if ltoks and sum(len(t) for t in ltoks) >= 2 and _seq_in(ptoks, ltoks):
            contained.append(n)
    if contained:
        return max(contained, key=lambda n: (len(_loose(n.label)), n.weight, n.id))
    xtoks = norm_tokens(_QUOTE_MARK_RE.sub(" ", exclude))
    distinct = [t for t in ptoks if len(t) >= 2 and not any(_tok_in(x, t) or _tok_in(t, x) for x in xtoks)]
    if not distinct:
        return None
    cands = []
    for n in nodes:
        ltoks = norm_tokens(n.label)
        if all(any(_tok_in(lt, t) for lt in ltoks) for t in distinct):
            extra = sum(1 for lt in ltoks if not any(_tok_in(lt, t) for t in distinct))
            cands.append((extra, -n.weight, n.id, n))
    return min(cands, key=lambda c: c[:3])[3] if cands else None


def _seq_in(outer: list[str], inner: list[str]) -> bool:
    n = len(inner)
    return any(all(_tok_in(outer[i + j], inner[j]) for j in range(n)) for i in range(len(outer) - n + 1))


# ---------------------------------------------------------------------------
# 규칙 추출 — LLM 없이 뻔한 구조 (compose 식, compare 「보다」)
# ---------------------------------------------------------------------------

_FORMULA_RE = re.compile(r"^(?P<lhs>[^=]{1,30}?)\s*=\s*(?P<rhs>.+)$")
_FORMULA_SPLIT_RE = re.compile(r"\s*[×✕*+·]\s*|\s+x\s+")
_ADJ_FORM = r"중요한|넓은|큰|높은|강한|효과적인|결정적인|나은|본질적인|근본적인|우선인"
_ADJ_STEM = r"중요|넓|크|큰|높|강하|효과적|결정적|낫|나은|본질적|근본적|우선"
#: 「A보다 (더) 중요한 B」 — 제목형. subject 는 뒤쪽 B 다.
_COMPARE_HEAD_RE = re.compile(
    rf"^(?P<a>[^,.?!]{{1,24}}?)보다\s*(?:더\s*|훨씬\s*)?(?:{_ADJ_FORM})\s+(?P<b>[^,.?!]{{1,24}}?)[.!]?$"
)
#: 「B는 (단순한) A보다 (더) 넓은 …」 — 문장형.
_COMPARE_SENT_RE = re.compile(
    rf"(?P<b>[^,.?!]{{1,24}}?)(?:은|는|이|가)\s+(?:단순한\s+|단순히\s+|그냥\s+)?(?P<a>[^,.?!]{{1,24}}?)보다\s*"
    rf"(?:더\s*|훨씬\s*)?(?:{_ADJ_STEM})"
)


def _formula_parts(line: str) -> tuple[str, list[str]] | None:
    m = _FORMULA_RE.match(line.strip())
    if not m:
        return None
    parts = [p.strip(" .") for p in _FORMULA_SPLIT_RE.split(m.group("rhs")) if p.strip(" .")]
    return (m.group("lhs").strip(), parts) if len(parts) >= 2 else None


def rule_compose(graph: ConceptGraph, slidedoc: SlideDoc) -> list[Claim]:
    """「<개념> = A × B × C」 (+·· 도) 줄에서 compose 주장. 요소가 둘 이상 개념에 닿아야 남긴다."""
    out: list[Claim] = []
    for s in slidedoc.slides:
        for line in slide_lines(s.raw_text):
            parsed = _formula_parts(line)
            if not parsed:
                continue
            lhs, parts = parsed
            subj = resolve_label(lhs, graph.nodes)
            if subj is None:
                continue
            objs: list[str] = []
            for p in parts:
                n = resolve_label(p, graph.nodes, exclude=lhs)
                if n is not None and n.id != subj.id and n.id not in objs:
                    objs.append(n.id)
            if len(objs) >= 2:
                out.append(Claim(id="", kind="compose", subject_id=subj.id, object_ids=objs, text=line,
                                 evidence=[ClaimQuote(s.slide_no, line)]))
    return out


def rule_compare(graph: ConceptGraph, slidedoc: SlideDoc) -> list[Claim]:
    """「A보다 중요한 B」·「B는 A보다 넓은 …」 줄에서 compare(B > A) 주장. 양쪽이 서로 다른 개념에 닿아야 남긴다."""
    out: list[Claim] = []
    for s in slidedoc.slides:
        for line in slide_lines(s.raw_text):
            plain = _QUOTE_MARK_RE.sub("", line).strip()
            # 두 꼴을 다 본다 — 문장형 「수면의 질은 단순한 시간보다 넓은 개념입니다」 는 제목형 정규식에도
            # 걸리지만(b=「개념입니다」) 개념에 안 닿는다. 닿는 첫 해석을 쓴다.
            for m in (_COMPARE_HEAD_RE.match(plain), _COMPARE_SENT_RE.search(plain)):
                if not m:
                    continue
                a, b = m.group("a").strip(), m.group("b").strip()
                big = resolve_label(b, graph.nodes, exclude=a)
                small = resolve_label(a, graph.nodes, exclude=b)
                if big is None or small is None or big.id == small.id:
                    continue
                out.append(Claim(id="", kind="compare", subject_id=big.id, object_ids=[small.id], text=line,
                                 evidence=[ClaimQuote(s.slide_no, line)]))
                break
    return out


def rule_claims(graph: ConceptGraph, slidedoc: SlideDoc) -> list[Claim]:
    return rule_compose(graph, slidedoc) + rule_compare(graph, slidedoc)


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
        body = "\n".join(slide_lines(s.raw_text))[:SLIDE_CHARS_MAX]
        if body:
            slides.append(f"### 슬라이드 {s.slide_no}\n{body}")
    return "[TASK] claim-graph\n\n## 개념 목록\n" + "\n".join(nodes) + "\n\n## 슬라이드 원문\n" + "\n\n".join(slides)


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

def _resolve_id(value, ids: set[str], by_label: dict[str, str]) -> str:
    """그래프 id 면 그대로, 아니면 이름이 통째로 같은 개념의 id (Solar 가 id 칸에 이름을 적는 일이 있다), 없으면 ""."""
    # 09-29 수익률 실측: 목록을 「- (gap) 수익률 격차」 꼴로 줬더니 Solar 가 "(gap)" 을 통째로 옮겼다. 괄호는 벗긴다.
    v = str(value or "").strip().strip("()[]{}<>「」 ").strip()
    if v in ids:
        return v
    return by_label.get(_loose(v), "")


def _check(raw: dict, ids: set[str], by_label: dict[str, str], texts: dict[int, str],
           labels: dict[str, str]) -> Claim | str:
    """후보 하나 → 대조를 통과한 Claim, 아니면 버린 까닭(kind·id·objects·quote) — 로그로 센다."""
    kind = str(raw.get("kind", "") or "").strip().lower()
    if kind not in CLAIM_KINDS:
        return "kind"
    subj = _resolve_id(raw.get("subject_id"), ids, by_label)
    if not subj:
        return "id"
    objs: list[str] = []
    for o in raw.get("object_ids") or []:
        oid = _resolve_id(o, ids, by_label)
        if oid and oid != subj and oid not in objs:
            objs.append(oid)
    if kind != "absolute" and not objs:
        return "objects"
    quotes: list[ClaimQuote] = []
    # 프롬프트는 주장마다 인용 하나를 평평하게(slide_no·quote) 받는다 — 09-29 수익률 덱에서 중첩 evidence 스키마는
    # Solar 가 3장 한 줄을 30번 되풀이하다 토큰이 끊겼다. 규칙 주장·옛 모양(evidence 목록)도 같이 받는다.
    flat = [{"slide_no": raw.get("slide_no"), "quote": raw.get("quote")}] if raw.get("quote") else []
    for ev in flat + list(raw.get("evidence") or []):
        if not isinstance(ev, dict):
            continue
        try:
            no = int(ev.get("slide_no") or 0)
        except (TypeError, ValueError):
            continue
        kept = verify_quote(str(ev.get("quote", "") or ""), texts.get(no, ""))
        if kept and all(norm_for_match(q.quote) != norm_for_match(kept) or q.slide_no != no for q in quotes):
            quotes.append(ClaimQuote(no, kept))
    if not quotes:
        return "quote"
    text = " ".join(str(raw.get("text", "") or "").split())[:160]
    if not text:
        text = f"{labels.get(subj, subj)} {kind} " + ", ".join(labels.get(o, o) for o in objs)
    return Claim(id="", kind=kind, subject_id=subj, object_ids=objs, text=text,
                 evidence=quotes[:EVIDENCE_MAX])


def _merge(claims: list[Claim]) -> list[Claim]:
    """같은 (kind, subject, objects) 는 하나로 — 인용은 합친다. 앞(LLM)의 text 를 남긴다."""
    out: dict[tuple, Claim] = {}
    for c in claims:
        key = (c.kind, c.subject_id, tuple(sorted(c.object_ids)))
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

    09-29 수면 실측: LLM 은 「수면의 질 = 시간 × 연속성 × 규칙성」 을 연속성·규칙성 둘로만 적었다(「시간」
    노드가 그래프에 없어서). 규칙은 셋을 다 잡았다. 둘 다 남기면 F-08 의 형제 우선순위 탐침이 같은 식을 두 번 센다.
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


def validate_claims(raw_claims: list[dict], graph: ConceptGraph, slidedoc: SlideDoc,
                    extra: list[Claim] | None = None) -> tuple[list[Claim], int]:
    """
    LLM 후보(dict) + 규칙 주장 → (대조를 통과한 Claim 목록, 버린 후보 수). id·has_support 는 여기서 채운다.

    규칙 주장도 **같은 대조를 거친다** — 규칙이 만든 인용도 원문에 없으면 버린다 (둘에 다른 잣대를 대지 않는다).
    """
    ids = {n.id for n in graph.nodes}
    by_label = {_loose(n.label): n.id for n in graph.nodes}
    labels = {n.id: n.label for n in graph.nodes}
    texts = {s.slide_no: s.raw_text for s in slidedoc.slides}
    kept: list[Claim] = []
    reasons: dict[str, int] = {}
    for raw in list(raw_claims) + [c.to_dict() for c in (extra or [])]:
        c = _check(raw, ids, by_label, texts, labels)
        if isinstance(c, str):
            reasons[c] = reasons.get(c, 0) + 1
        else:
            kept.append(c)
    dropped = sum(reasons.values())
    if dropped:
        # 무엇 때문에 버렸는지 남긴다 — 「주장이 왜 적지」 를 인용 탓인지 id 탓인지 가를 수 있어야 한다.
        sys.stderr.write("[f26] 버린 후보 " + " ".join(f"{k}={v}" for k, v in sorted(reasons.items())) + "\n")
    merged = _merge(kept)
    for c in merged:
        c.has_support = any(has_support(texts.get(q.slide_no, "")) for q in c.evidence)
    order = {k: i for i, k in enumerate(CLAIM_KINDS)}
    merged.sort(key=lambda c: (min(q.slide_no for q in c.evidence), order[c.kind], c.subject_id, c.object_ids))
    merged = merged[:CLAIM_MAX]
    for i, c in enumerate(merged, 1):
        c.id = f"c{i:02d}"
    return merged, dropped


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
