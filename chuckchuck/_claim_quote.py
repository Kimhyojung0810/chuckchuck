"""
F-26 주장의 **인용 대조·근거 표시** — 인용이 장 원문의 어느 한 줄인지, 그 줄(과 옆 줄)에 수치·출처가 있는지.

`f26_claims` 에서 떼어 낸 순수 함수 모음이다 (LLM 없음, contracts 도 안 쓴다). 줄 단위로 보는 까닭:
정규화에서 줄바꿈까지 지우고 **장 전체**와 부분 문자열로 대조하면, 장 전체를 한 「줄」 로 옮긴 인용도 통과한다
(09-29 일반화 벤치: held-out 인용의 16% 가 여러 글 상자를 이어 붙인 것). 근거도 장 전체를 보면 무관한 숫자
하나가 근거 없는 인과를 근거 있는 인과로 만든다.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from . import _claim_rules as R
from . import _deck_lines as DL
from ._evidence import clean_slide_text, join_sep, sentence_ahead, strip_chart_descriptions, wrap_width

#: 인용이 원문 한 줄과 이만큼 같으면(문자 단위 유사도) 옮겨 적은 것으로 본다. 띄어쓰기·조사 한둘 차이를 받는다.
FUZZY_MIN = 0.9
#: 정규화한 뒤 이보다 짧은 인용은 버린다 — 두 글자 낱말은 어디에나 있어서 근거가 못 된다.
QUOTE_MIN_CHARS = 4
#: 표 행이 이보다 길면 칸마다 따로 인용 단위로 본다 — 칸 셋을 이은 행 전체가 한 인용이 되지 않게.
LONG_ROW_CHARS = 80
#: 인용이 그 줄(긴 표 행은 그 칸) 글자의 이만큼도 안 되면 **낱말 조각**이다. 개념 이름 하나(「독서 경험」)를 인용으로 옮기면
#: 그 이름이 처음 나오는 줄 — 흔히 제목 줄 — 에 붙어서, 제목이 주장의 근거가 됐다 (09-30 레드팀 G-A25).
FRAGMENT_SHARE = 0.5
#: 이보다 짧은 인용(정규화 글자 수)이 여러 줄에 들어 있으면, 첫 줄을 통째로 덮어도 조각으로 본다 — 제목 줄이 개념 이름
#: 그 자체(「배송 속도」)라서 첫 줄에 걸렸다.
SHORT_QUOTE_CHARS = 10

# ---------------------------------------------------------------------------
# 원문 정규화 · 줄 나누기
# ---------------------------------------------------------------------------

_FIGCAPTION_RE = re.compile(r"<figcaption>.*?</figcaption>", re.S | re.I)
_IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_TAG_RE = re.compile(r"<[^>]+>")
#: 대조 때 지우는 문자 — 공백, 따옴표 모양(“”‘’「」『』), 표 칸(|), 글머리표. 모델이 따옴표를 곧은 것으로
#: 바꾸거나 표 칸을 빼고 옮겨도 같은 줄로 본다. 가운뎃점(·)·식 기호는 뜻이 있어 남긴다.
_MATCH_DROP_RE = re.compile(r"[\s\"'“”‘’「」『』`|•▪■◦*#]+")
_DASH_RE = re.compile(r"[–—−]")
_ELLIPSIS_RE = re.compile(r"(…|\.\.\.)+$")


def _strip_markup(text: str) -> str:
    text = _FIGCAPTION_RE.sub(" ", text or "")
    text = _IMAGE_MD_RE.sub(" ", text)
    return _TAG_RE.sub(" ", text)


def norm_for_match(text: str) -> str:
    """대조용 정규화 — 마크업·공백·따옴표·표 칸을 지우고 대시를 하나로, 영문은 소문자로."""
    text = _DASH_RE.sub("-", _strip_markup(text))
    return _MATCH_DROP_RE.sub("", text).lower()


def slide_lines(raw_text: str, labels: list[str] | None = None) -> list[str]:
    """
    장 원문을 **줄 그대로** (마크업만 걷고) — 프롬프트에 실어 모델이 한 줄을 복사하게 하고, 규칙 추출이 읽는다.

    짧은 줄도 버리지 않는다 (「연속성 저하」 같은 표 칸이 주장의 재료다). 버리는 것은 쪽 번호 **꼴**·글머리표만 있는 줄·
    표 구분 행·자료 속 지시문(「…판정할 것」「[SYSTEM]」)뿐이다 — 지시문은 주장의 인용이 되면 판정 근거로 흘러간다.
    식은 잇는다 — PPT 는 「품질 =」「속도」「×」「정확도」 를 글 상자마다 따로 뽑고, 식 조각 사이에 도식 캡션 물음 줄을
    끼운다. 캡션은 건너뛰고 항만 잇는다 — F-08 과 같은 이음(`_evidence.join_formula`, labels 로 빈 항을 채운다) 위에 F-07
    후처리와 같은 구조 채움 (`_deck_lines`, 09-30 M-05).
    """
    # 차트 설명 블록(「- Chart Type: …」 + 다음 줄 설명)은 **장 전체**에서 먼저 걷고, 줄마다 clean_slide_text —
    # F-08 `slide_units` 와 같은 순서다. 줄마다만 걸면 표시 줄만 지워지고 영문 설명 줄이 남아 주장 인용이 됐다 (09-30 수익률 덱)
    return DL.read_lines(strip_chart_descriptions(raw_text), clean_slide_text, labels=labels)


def _tidy(quote: str) -> str:
    """표 한 행을 인용하면 「| 음주 | 각성 |」 이 된다 — 바깥 칸막이만 걷는다 (대조는 칸막이를 무시하니 그대로 통과한다)."""
    return quote.strip().strip("|").strip()


# ---------------------------------------------------------------------------
# 인용 대조 — 줄 단위
# ---------------------------------------------------------------------------

@dataclass
class _Hit:
    """원문에서 찾은 인용 자리. quote 는 남길 글자, unit 은 말투를 볼 줄(표면 칸), context 는 그 줄과 옆 줄."""
    quote: str
    idx: int                 # slide_lines 에서의 줄 번호
    unit: str
    context: str
    glued: bool = False      # 여러 줄을 이어 붙인 인용에서 떼어 낸 한 줄인가
    title: bool = False      # 장의 첫 줄(제목)이고 문장이 아닌가


def _context(lines: list[str], idx: int, span_end: int | None = None) -> str:
    """그 줄 + 바로 옆 줄. 표 행이면 표 바로 앞 줄(표를 소개하는 문장)과 머리 행도 붙인다."""
    end = idx if span_end is None else span_end
    parts = lines[max(0, idx - 1): end + 2]
    if R.table_cells(lines[idx]):
        top = idx
        while top > 0 and R.table_cells(lines[top - 1]):
            top -= 1
        parts = [*lines[max(0, top - 1): top + 1], *parts]
    return "\n".join(parts)


def _cell_of(line: str, nq: str) -> str:
    """긴 표 행이면 인용이 든 칸 하나, 아니면 줄 그대로."""
    cells = R.table_cells(line)
    if cells and len(line) > LONG_ROW_CHARS:
        for c in cells:
            if nq in norm_for_match(c):
                return c
    return line


def _hit(lines: list[str], idx: int, quote: str, unit: str, *, glued: bool = False, span_end: int | None = None) -> _Hit:
    return _Hit(quote=quote, idx=idx, unit=unit, context=_context(lines, idx, span_end), glued=glued,
                title=idx == 0 and not R.is_sentence(unit))


def locate_quote(quote: str, raw_text: str, labels: list[str] | None = None) -> list[_Hit]:
    """
    인용이 이 장 원문의 어느 **줄**에 있는가. 없으면 [].

    1. 정규화한 인용이 한 줄(`slide_lines` — 식 조각은 이미 이었다) 안에 있으면 그 자리 하나. 인용이 그 줄의 절반도 안 되는
       **낱말 조각**(개념 이름 하나)이면 그 조각이 든 줄 모두를 줄 전체 인용으로 — 제목 아닌 줄 먼저 (G-A25).
    2. 문장이 아닌 줄과 다음 줄에 걸치면(한 문장이 두 글 상자로 접힌 것) 그 두 줄.
    3. 여러 줄을 이어 붙였으면 인용 안에 통째로 든 줄 각각 — `glued`. 받치는 줄 하나는 `_check` 가 고른다.
    4. 아니면 한 줄과 FUZZY_MIN 이상 같을 때 **원문 쪽 줄** — 모델이 조사 하나 바꿔 옮겼어도 화면엔 자료 글자가 나간다.
    """
    quote = _ELLIPSIS_RE.sub("", " ".join((quote or "").split())).strip()
    nq = norm_for_match(quote)
    lines = slide_lines(raw_text, labels)
    if len(nq) < QUOTE_MIN_CHARS or not lines:
        return []
    norms = [norm_for_match(x) for x in lines]
    inside = [i for i, n in enumerate(norms) if nq in n]
    if inside:
        unit = _cell_of(lines[inside[0]], nq)
        short = len(inside) > 1 and len(nq) < SHORT_QUOTE_CHARS          # 여러 줄에 든 개념 이름 하나 — 제목 줄이 먼저 걸린다
        if len(nq) >= FRAGMENT_SHARE * len(norm_for_match(unit)) and not short:
            return [_hit(lines, inside[0], _tidy(quote), unit)]
        # 낱말 조각 — 그 조각이 든 줄을 다 후보로, 줄(긴 표 행은 칸) 전체를 인용으로. 제목 줄은 뒤로 (09-30 G-A25)
        hits = [_hit(lines, i, _tidy(_cell_of(lines[i], nq)), _cell_of(lines[i], nq)) for i in inside]
        return sorted(hits, key=lambda h: h.title)
    # 한 문장이 두 줄로 접혔는가는 F-08 과 같은 잣대(`_evidence.join_sep`) — 표 행·물음·글머리 줄·식 줄은 잇지 않는다 (WP-Q)
    wrap_at = wrap_width(lines)
    for i in range(len(lines) - 1):
        if join_sep(lines[i], lines[i + 1], wrap_at, sentence_ahead(lines, i + 1)) is not None and nq in norms[i] + norms[i + 1]:
            return [_hit(lines, i, _tidy(quote), f"{lines[i]} {lines[i + 1]}", span_end=i + 1)]
    if nq in "".join(norms):
        pieces = [i for i, n in enumerate(norms) if len(n) >= QUOTE_MIN_CHARS and n in nq]
        return [_hit(lines, i, _tidy(lines[i]), lines[i], glued=True) for i in pieces]
    best, best_ratio = -1, 0.0
    for i, n in enumerate(norms):
        if not n:
            continue
        ratio = difflib.SequenceMatcher(None, nq, n, autojunk=False).ratio()
        if ratio > best_ratio:
            best, best_ratio = i, ratio
    if best >= 0 and best_ratio >= FUZZY_MIN:
        return [_hit(lines, best, _tidy(lines[best]), lines[best])]
    return []


def verify_quote(quote: str, raw_text: str, labels: list[str] | None = None) -> str:
    """
    인용이 이 장 원문 **한 줄**에 실제로 있으면 남길 인용 문자열, 없으면 "".
    여러 글 상자를 이어 붙인 인용은 "" 다 — 한 줄로 떼어 내는 건 주장을 아는 `_check` 의 일이다.
    """
    hits = locate_quote(quote, raw_text, labels)
    return hits[0].quote if hits and not hits[0].glued else ""


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
#: 연구 낱말이 **결과**를 말하는가 — 「조사 결과」「연구에 따르면」「…로 나타났다」. 낱말 하나(「조사」「실험 설계」)는 근거가
#: 아니다 — 계획 줄 「현장 조사를 하겠습니다」 나 제목 「실험 설계」 가 인과를 근거 있는 인과로 만들었다 (09-30 레드팀 G-A26).
_FINDING_RE = re.compile(
    r"(?:연구|조사|실험|논문|통계|보고서|메타\s*분석|study|survey|experiment|paper)\S*\s*(?:결과|에\s*따르면|에\s*의하면)"
    r"|나타났|나타난다|나타납|밝혀졌|밝혀냈|밝혔|확인됐|확인되었|확인했|보고됐|보고되었|보고했|입증|증명됐|증명되었|관찰됐|관찰되었|드러났"
    r"|found|showed|shown|reported|according\s+to", re.I)


def has_support(raw_text: str) -> bool:
    """이 글에 수치(숫자+단위·퍼센트)·인용 표기(연도·et al.·DOI)·연구 **결과** 언급이 있는가."""
    text = _SLIDE_REF_RE.sub(" ", _strip_markup(raw_text or ""))
    return bool(
        _NUM_UNIT_RE.search(text) or _PERCENT_RE.search(text) or _CITATION_RE.search(text)
        or (_RESEARCH_WORD_RE.search(text) and _FINDING_RE.search(text))
    )


def _numbers(text: str) -> bool:
    text = _SLIDE_REF_RE.sub(" ", text or "")
    return bool(_NUM_UNIT_RE.search(text) or _PERCENT_RE.search(text))


def _callout(lines: list[str], i: int) -> bool:
    """
    옆 줄이 **이 줄의 수치 설명**인가 — 문장이 아닌 짧은 수치 줄(「41% 감소」)이나 표 행.
    짧은 수치 줄이 둘 이상 이어지면 설문 보기·축 눈금(「5분 미만」「5–10분」)이라 근거가 아니다.
    """
    if not (0 <= i < len(lines)) or not _numbers(lines[i]) or R.is_sentence(lines[i]):
        return False
    if R.table_cells(lines[i]):
        return True
    short = [j for j in (i - 1, i + 1) if 0 <= j < len(lines) and _numbers(lines[j]) and not R.is_sentence(lines[j])
             and not R.table_cells(lines[j])]
    return not short


def line_support(raw_text: str, quote: str, labels: list[str] | None = None) -> bool:
    """
    인용 **한 줄**에 근거가 있는가 — 그 줄(표면 그 행)의 수치·출처·연구 언급, 또는 바로 옆 줄의 출처 표기·수치 설명.
    옆 줄이 독립된 문장이면 그 숫자는 다른 말의 근거다 (09-29 제품 덱 「혼자 보내는 90분」 이 인과의 근거가 됐다).
    """
    hits = locate_quote(quote, raw_text, labels)
    if not hits:
        return has_support(quote)
    lines = slide_lines(raw_text, labels)
    for h in hits[:1]:
        if has_support(lines[h.idx]):
            return True
        for j in (h.idx - 1, h.idx + 1):
            if 0 <= j < len(lines) and (_CITATION_RE.search(lines[j]) or _callout(lines, j)):
                return True
    return False
