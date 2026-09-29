"""
판정(F-09)이 **자료 본문을 정답의 원본으로** 쓰게 하는 결정적 대조 헬퍼입니다. LLM 을 부르지 않습니다.
`_evidence.py`·`_match.py` 와 같은 자리의 유틸이라 기능 모듈 어디서 import 해도 정책 위반이 아닙니다 (DEV_POLICY §4-1).

왜 따로 두나 (2026-09-29 두 덱 기준선, docs/review/2026-09-29_QA_근거검증/baseline.md):
- 그럴듯한 오답 6건 중 3건이 통과(partial 70~75)했고, react 가 틀린 주장에 「정확해요」 라고 했다.
  요인의 %p 를 서로 바꿔 붙인 답, 표에서 더 낮은 쪽을 「더 높다」 고 한 답이다. 무관 가드는 낱말이 **겹치면**
  통과라서 같은 주제의 오답은 못 잡는다. 수치·순서·방향이 자료와 어긋나는지는 **글자로 셀 수 있는 것**이라 코드가 본다.
- 판정의 채점 기준이 F-08 의 골자였는데, 골자가 자료에 없는 서열·잘못 붙인 숫자를 담아도 그대로 정답이 됐다.
  골자가 자료로 받쳐지는지(낱말·숫자가 자료에 있는가, 자료와 어긋나는 짝이 없는가)를 여기서 잰다.

**규칙은 전부 구조로만 짠다** — 숫자·단위, 표의 행, 비교·서열 표지(「보다」「가장」), 방향 낱말(늘다/줄다),
부정 표지. 특정 발표의 낱말을 목록에 넣지 않는다: 부스에서는 처음 보는 자료가 들어온다.

놓치는 쪽이 안전하다. 여기서 잘못 잡으면 맞게 답한 사람이 「자료와 어긋나요」 를 받는다 —
그래서 짝이 분명할 때만(자료가 그 낱말에 **다른** 숫자를 붙였고, 답이 댄 숫자는 자료에서 **다른** 낱말의 것일 때 등)
어긋남으로 본다. 애매하면 LLM 판정에 맡긴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ._evidence import clean_slide_text

# ---------------------------------------------------------------------------
# 낱말 · 숫자
# ---------------------------------------------------------------------------

#: 숫자 + 단위. 앞이 영문·숫자면 숫자로 보지 않는다(「N1」「v2」). 시각(03:00)은 버린다.
_NUM_RE = re.compile(
    r"(?<![A-Za-z\d.,:])([-−–]?)(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\d:])\s?"
    r"(%p|%|p\.p\.?|배|회|번|개월|개|일|년|월|주|명|건|만원|억원|억|원|분|시간|초|점|장|위|차)?",
    re.I,
)
_WORD_RE = re.compile(r"[가-힣]+|[A-Za-z]+")
#: 자료 구조를 가리키는 숫자 — 「5장」「2차」. 사실 숫자가 아니다.
_STRUCTURAL_UNITS = frozenset({"장", "차"})
_UNIT_CLASS = {"%p": "pp", "p.p": "pp", "p.p.": "pp", "%": "pct"}

#: 이것만으로는 무엇에 대한 말인지 알 수 없는 낱말(앞머리 일치). 어느 발표에나 나오는 말만 둔다.
_GENERIC = (
    "발표", "자료", "질문", "설명", "개념", "근거", "이유", "핵심", "내용", "부분", "경우", "방법", "방식", "정도",
    "이것", "그것", "저희", "우리", "이후", "생각", "때문", "그래서", "하지만", "그리고", "위해", "통해", "대해",
    "관해", "무엇", "어떤", "어느", "어떻게", "있어", "있었", "있는", "있다", "있습", "없어", "없었", "없는", "없다",
    "같아", "같은", "거예요", "이에요", "예요", "해요", "했어", "했다", "했습", "합니", "입니", "됩니", "됐어", "봤어",
    "가장", "제일", "매우", "아주", "너무", "정말", "특히", "모두", "각각", "다른", "이런", "그런", "저런", "것은",
    "것이", "것을", "수는", "수가", "라고", "이라", "대한", "관련", "해서", "하는", "되는", "하고", "되고", "보면",
    "다만", "또한", "그러나", "오히려", "결국", "먼저", "다음", "그럼", "여기", "거기", "이번", "지금", "해당",
)

#: 명사 뒤 조사. 떼고 줄기끼리 견준다 — 「실패가」 와 「실패에」 는 같은 낱말이다.
_PARTICLE_RE = re.compile(
    r"(에서는|으로는|에서도|에게는|이라는|이라고|에서|으로|에게|부터|까지|처럼|보다는|보다|이나|과의|와의|에는|에도|"
    r"은|는|이|가|을|를|의|도|에|와|과|로|만)$"
)
MIN_STEM = 2


def _stem(word: str) -> str:
    w = word.lower()
    m = _PARTICLE_RE.search(w)
    if m and len(w) - len(m.group(1)) >= MIN_STEM:
        return w[: -len(m.group(1))]
    return w


def _is_generic(word: str) -> bool:
    return any(word.startswith(g) for g in _GENERIC)


def _same(a: str, b: str) -> bool:
    """줄기 둘이 같은 낱말인가. 한글은 앞머리 포함(합성어·활용 꼬리)도 같다고 본다 — 둘 다 두 글자 이상일 때만."""
    if a == b:
        return True
    if len(a) < MIN_STEM or len(b) < MIN_STEM or not (a[0] >= "가" and b[0] >= "가"):
        return False
    return a.startswith(b) or b.startswith(a)


def content_stems(text: str, *, drop_units: bool = False) -> list[str]:
    """대조용 줄기 목록 (문장 순서). 한 글자·상투어는 버린다.

    drop_units 면 숫자에 바로 붙은 글자(「48만원」의 만원 · 「1년차엔」의 년차)를 단위 조각으로 보고 뺀다 — 「같은 말을 하는
    줄인가」(방향·부정 대조)를 볼 때만. 09-30 실측(수익률 함정 Q3): 「1,000만원 넣었을 때 1년차엔 48만원 차이라 체감이 안
    되지만」 이 자료 줄 「체감하기 어려운 수준의 차이 5년차 307만원」 과 **만원·년차** 덕에 「거의 같은 말」(겹침 4/6)로 잡혀
    부정 어긋남 55 를 받았다. 숫자 짝 대조에서는 단위 조각이 「그 숫자의 줄」 을 알아보는 단서라 남긴다.
    """
    out: list[str] = []
    src = text or ""
    for m in _WORD_RE.finditer(src):
        w = m.group(0)
        if drop_units and m.start() > 0 and src[m.start() - 1].isdigit():
            continue
        if len(w) < MIN_STEM or _is_generic(w):
            continue
        s = _stem(w)
        if len(s) >= MIN_STEM and not _is_generic(s):
            out.append(s)
    return out


def _has(stems, stem: str) -> bool:
    return any(_same(stem, s) for s in stems)


@dataclass(frozen=True)
class Num:
    value: float
    unit: str | None
    negative: bool
    start: int
    end: int
    #: 소수 자릿수 — 「8.7」 은 1, 「9」 는 0. 반올림한 같은 값인지(`close_value`) 볼 때 덜 정밀한 쪽에 맞춘다.
    decimals: int = 0

    def same_value(self, other: "Num") -> bool:
        if abs(self.value - other.value) > 1e-9:
            return False
        return self.unit is None or other.unit is None or self.unit == other.unit

    def close_value(self, other: "Num") -> bool:
        """
        같은 값이거나, **덜 정밀한 쪽으로 반올림하면 같은 값**인가 (8.7 ↔ 9 · 7.9 ↔ 8 · 11.8 ↔ 12).

        09-30 실측(수익률 함정 Q4·Q5): 자료 3장 차트 표는 「시장지수 9 · 기관 8」, 본문은 「지수 8.7% vs 기관 7.9%」 — 같은 사실의
        두 표기다. 본문 값 「8.7」 로 바로잡은 답이 차트 값 9 와 다르다고 함정 동의 wrong 30 을 받았다.
        두 값의 정밀도가 같으면 반올림 허용이 없다(8 ↔ 9 는 다른 값).
        """
        if self.unit is not None and other.unit is not None and self.unit != other.unit:
            return False
        if abs(self.value - other.value) <= 1e-9:
            return True
        if self.decimals == other.decimals:
            return False
        prec = min(self.decimals, other.decimals)
        return abs(self.value - other.value) <= 0.5 * 10 ** -prec + 1e-9


#: 「1, 2, 3장」「4~7장」 — 나열 전체가 장 번호다. 마지막 숫자에만 「장」 이 붙어 앞 숫자가 사실 숫자로 잡힌다.
_SLIDE_LIST_RE = re.compile(r"\d+(?:\s*[,·~–-]\s*\d+)+\s*(?:장|번\s*슬라이드)")


def numbers(text: str, *, skip_years: bool = True) -> list[Num]:
    """사실 숫자만. 장 번호(「5장」「1, 2, 3장」)·앞자리 0 서수(「01.」)·단위 없는 연도(2016)는 뺀다.
    위치(start·end)는 원문 기준이다 — 가린 자리는 같은 길이의 빈칸으로 바꾼다."""
    text = _SLIDE_LIST_RE.sub(lambda m: " " * len(m.group(0)), text or "")
    out: list[Num] = []
    for m in _NUM_RE.finditer(text):
        sign, raw, unit = m.group(1), m.group(2), (m.group(3) or "")
        if unit in _STRUCTURAL_UNITS:
            continue
        if len(raw) >= 2 and raw.startswith("0") and "." not in raw:
            continue
        value = float(raw.replace(",", ""))
        if skip_years and not unit and "." not in raw and 1900 <= value <= 2100:
            continue
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        out.append(Num(value, _UNIT_CLASS.get(unit.lower(), unit or None), bool(sign), m.start(), m.end(), decimals))
    return out


# ---------------------------------------------------------------------------
# 방향 · 부정 · 비교 표지 — 어느 분야에나 쓰는 한국어 문법 낱말만
# ---------------------------------------------------------------------------

_UP = ("높", "많", "늘", "증가", "상승", "오르", "올라", "올랐", "커지", "커졌", "커진", "큰", "컸", "크다", "크고",
       "강하", "강한", "강했", "강함", "강해", "커져", "커요", "길어", "길다", "긴", "빠르", "빨라", "빨랐", "개선", "상회", "앞서", "앞섰", "넘었", "넘는")
_DOWN = ("낮", "적은", "적어", "적었", "적다", "줄", "감소", "하락", "떨어", "내려", "내렸", "작아", "작은", "작았", "작다",
         "약하", "약한", "약했", "약함", "약해", "짧", "느리", "느려", "느렸", "악화", "하회", "뒤지", "뒤졌", "뒤처", "못미", "못 미")


#: 방향 줄기 뒤에 와도 되는 꼬리 — 활용 어미·명사형·조사. 09-30 레드팀: 앞머리만 보니 「낮잠·줄거리」 가 감소, 「긴장·개선안」 이
#: 증가로 읽혔다. 줄기 뒤가 이 꼴일 때만 방향 낱말이다(어느 분야에나 같은 한국어 문법).
_DIR_TAIL_RE = re.compile(
    r"^(?:$|하|되|된|돼|했|됐|함|됨|해|아|어|았|었|여|였|게|고|다|은|는|을|음|지|기|면|며|겠|습|니|이|인|일|임|던|도록|수록|"
    r"리|려|렸|린|릴|립|추|춰|췄|춘|출|춥|입|합|됩|집|웁|"
    r"가|를|의|로|와|과|에|도|만|요|세요|죠|네)"
)


def direction(word: str) -> str:
    """낱말 하나의 방향 — 'up' · 'down' · ''. 방향 줄기 + 활용 꼬리일 때만 (`_DIR_TAIL_RE`)."""
    w = word.lower()
    if any(w.startswith(p) and _DIR_TAIL_RE.match(w[len(p):]) for p in _UP):
        return "up"
    if any(w.startswith(p) and _DIR_TAIL_RE.match(w[len(p):]) for p in _DOWN):
        return "down"
    return ""


def directions(text: str) -> set[str]:
    found = {direction(w) for w in _WORD_RE.findall(text or "")} - {""}
    if re.search(r"못\s*미", text or ""):
        found.add("down")
    return found


#: 서술의 부정. 「A 가 아니라 B」 「A 가 아닌 B」 는 대조라 부정이 아니다. 「없이」 는 부사다.
#: 「아니라고·아니라서·아니라면」 은 대조가 아니라 **부정**이다(인용·이유·조건) — 09-30 실측(녹음 수면 Q2): 「자료는 반대로 잠은
#: 하나의 상태가 **아니라고** 했어요」 가 긍정으로 읽혀, 판정 react 의 「…아니다」 와 반대라는 자기모순 partial 60 을 받았다.
#: 「X 아니고 Y」 도 대조다(09-30 레드팀) · 「없애다·없앴다」 는 부정이 아니라 동사다.
_NEG_RE = re.compile(
    r"않|(?:^|\s)못(?:\s|하|했|해)|(?:^|\s)안\s+[가-힣]|없(?![이애앴앤앨])|아니(?!라(?![고서면며는]))(?!고(?:\s|,))|아닙|"
    r"아닌(?=\s*(?:$|[.,]))"
)
#: 양보의 부정 — 「확인 안 해도」「가까이 없어도」「않아도」 는 「…해도 그렇다」 는 말이지 명제를 뒤집는 부정이 아니다.
#: 09-30 실측(focus Q6): 「알림은 확인 안 해도 주의를 끌고」 ↔ 판정 「확인 없이도 주의가 끌리는」 이 부정 반대로 읽혔다.
_CONCESSIVE_NEG_RE = re.compile(
    r"(?:^|\s)안\s+[가-힣]*(?:도|더라도)(?=[\s,.]|$)|[가-힣]*(?:않|없|아니)(?:어도|아도|더라도|이도|어서도)(?=[\s,.]|$)"
)


def negated(text: str) -> bool:
    return bool(_NEG_RE.search(_CONCESSIVE_NEG_RE.sub(" ", text or "")))


_SUPERLATIVE_RE = re.compile(r"가장|제일")
_THAN_RE = re.compile(r"([가-힣A-Za-z0-9%]+?)(?:보다는|보다|보단)(?=\s|$)")


# ---------------------------------------------------------------------------
# 자료 모형
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DeckLine:
    slide_no: int
    text: str
    stems: tuple[str, ...]
    nums: tuple[Num, ...]
    is_row: bool = False
    #: 표 행의 **맥락 낱말** — 표 바로 위 제목 줄(「연간 회전율 구간별 평균 수익률 (%)」)과 머리 행. 행 이름이 숫자 구간(「50% 미만」)
    #: 이면 행 자체에는 무엇의 값인지 말하는 낱말이 없다. 숫자의 주인을 찾을 때만 쓴다.
    context: tuple[str, ...] = ()


@dataclass(frozen=True)
class Table:
    slide_no: int
    #: (행 이름, 값) — 숫자 칸이 하나뿐인 표만 서열을 본다. 여러 칸이면 어느 칸끼리 견줄지 모른다.
    rows: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class Deck:
    lines: tuple[DeckLine, ...] = ()
    #: 숫자 짝을 볼 단위 — 표의 행은 한 행씩, 글줄은 줄 하나와 「줄+다음 줄」 (한 줄이 두 상자에 걸친 경우).
    regions: tuple[DeckLine, ...] = ()
    tables: tuple[Table, ...] = ()
    stems: frozenset[str] = field(default_factory=frozenset)

    @property
    def empty(self) -> bool:
        return not self.lines


_PAGE_NO_RE = re.compile(r"^[\d\s/|.·-]+$")
_ROW_SEP_RE = re.compile(r"^:?-{2,}:?$")
_CONTINUES_RE = re.compile(r"(,|보다|아니라|는데|지만|으며|면서|에서|으로|에게|은|는|이|을|를|와|과|의|고|며|[=×+→÷])$")
#: 짧은 꼬리 줄 — 「약함」「하회」 처럼 글 상자가 줄을 바꿔 떨어진 서술어. 앞 줄에 붙인다.
_TAIL_MAX = 5


def _is_caption(line: str) -> bool:
    """Upstage 가 붙인 영문 그림 설명. 숫자가 많아 짝 대조를 흐린다."""
    latin = len(re.findall(r"[A-Za-z]", line))
    hangul = len(re.findall(r"[가-힣]", line))
    return line.lstrip().startswith("- ") and latin > hangul or (latin > 2 * hangul and len(line) > 30)


def _line(slide_no: int, text: str, is_row: bool = False) -> DeckLine:
    return DeckLine(slide_no, text, tuple(content_stems(text)), tuple(numbers(text)), is_row)


def build_deck(slides) -> Deck:
    """
    [(장 번호, raw_text)] → Deck. SlideDoc 의 raw_text 를 그대로 받는다 (줄 구조가 살아 있어야 한다).
    """
    lines: list[DeckLine] = []
    regions: list[DeckLine] = []
    tables: list[Table] = []
    for slide_no, raw in slides:
        text_units: list[str] = []
        table_rows: list[list[str]] = []
        caption = ""        # 표 바로 위 글줄 — 표의 제목인 경우가 많다

        def close_table() -> None:
            if table_rows:
                t = _single_value_table(slide_no, table_rows)
                if t is not None:
                    tables.append(t)
                table_rows.clear()

        for raw_line in (raw or "").split("\n"):
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith("|"):
                cells = [clean_slide_text(c) for c in stripped.strip("|").split("|")]
                if all(_ROW_SEP_RE.match(c.replace(" ", "")) or not c for c in cells):
                    continue
                table_rows.append(cells)
                row = _line(slide_no, " | ".join(c for c in cells if c), is_row=True)
                ctx = tuple(content_stems(f"{caption} {' '.join(table_rows[0])}"))
                row = DeckLine(row.slide_no, row.text, row.stems, row.nums, True, ctx)
                lines.append(row)
                regions.append(row)
                continue
            close_table()
            line = clean_slide_text(stripped)
            if not line or _PAGE_NO_RE.match(line) or _is_caption(line):
                continue
            if not stripped.startswith(("-", "!")):
                caption = line
            if text_units and (_CONTINUES_RE.search(text_units[-1])
                               or (len(line) <= _TAIL_MAX and not re.search(r"[.?!]$", text_units[-1]))):
                text_units[-1] = f"{text_units[-1]} {line}"
            else:
                text_units.append(line)
        close_table()
        for i, unit in enumerate(text_units):
            one = _line(slide_no, unit)
            lines.append(one)
            regions.append(one)
            if i + 1 < len(text_units):
                regions.append(_line(slide_no, f"{unit} {text_units[i + 1]}"))
    stems = frozenset(s for ln in lines for s in ln.stems)
    return Deck(tuple(lines), tuple(regions), tuple(tables), stems)


def deck_from_slidedoc(slidedoc) -> Deck:
    if slidedoc is None:
        return Deck()
    return build_deck((s.slide_no, s.raw_text or "") for s in getattr(slidedoc, "slides", None) or [])


def _single_value_table(slide_no: int, rows: list[list[str]]) -> Table | None:
    out: list[tuple[str, float]] = []
    for cells in rows[1:]:   # 첫 행은 머리글
        if len(cells) < 2 or not re.search(r"[가-힣A-Za-z]", cells[0]):
            continue
        # 표 칸의 숫자는 값이다 — 「2000」 을 연도로 보고 버리면 표 전체가 빠진다.
        vals = [n for c in cells[1:] for n in numbers(c, skip_years=False)]
        if len(vals) != 1 or any(re.search(r"[가-힣A-Za-z]{2,}", c) for c in cells[1:]):
            return None
        v = vals[0]
        out.append((cells[0], -v.value if v.negative else v.value))
    return Table(slide_no, tuple(out)) if len(out) >= 3 else None


# ---------------------------------------------------------------------------
# 답을 절로 — 「…했고, …라서 …」 는 주장이 여럿이다
# ---------------------------------------------------------------------------

_CLAUSE_END_RE = re.compile(r"(고|며|서|면서|지만|는데|은데|거나|으나|니까|므로|요|니다|다)$")
#: 문장 경계. 소수점(4.8)·천 단위 쉼표(1,000)·나열 쉼표(1, 2, 3장)는 경계가 아니다.
_SENTENCE_SPLIT_RE = re.compile(r"(?<!\d)[.;!?\n]+|[.;!?\n]+(?!\d)|,(?=\s*[^\d\s])|\s+[—–-]\s+")


def clauses(text: str) -> list[str]:
    """문장 부호와 연결 어미에서 자른다. 「…보다」 는 비교의 앞말이라 자르지 않는다."""
    out: list[str] = []
    for sentence in _SENTENCE_SPLIT_RE.split(text or ""):
        cur: list[str] = []
        for word in sentence.split():
            cur.append(word)
            bare = re.sub(r"[^가-힣A-Za-z0-9%]+$", "", word)
            if _CLAUSE_END_RE.search(bare) and not bare.endswith(("보다", "처럼")):
                out.append(" ".join(cur))
                cur = []
        if cur:
            out.append(" ".join(cur))
    return [c.strip() for c in out if c.strip()]


# ---------------------------------------------------------------------------
# 어긋남 — 숫자 짝 · 표 서열 · 방향 · 부정
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Conflict:
    kind: str          # number · order · direction · negation
    slide_no: int
    deck_line: str
    claim: str         # 답에서 걸린 절
    what: str          # 사람에게 보여 줄 「다시 볼 곳」 — 답의 낱말로만 쓴다(정답을 흘리지 않게)


def _terms_around(clause: str, num: Num, deck: Deck) -> tuple[list[str], list[str]]:
    """숫자 앞 세 낱말·뒤 두 낱말 중 **자료에 있는** 줄기. 앞은 다른 숫자를 넘지 않는다."""
    before_text = clause[: num.start]
    prev = [n for n in numbers(before_text)]
    if prev:
        before_text = before_text[prev[-1].end:]
    before = [s for s in content_stems(before_text)[-3:] if _has(deck.stems, s)]
    after = [s for s in content_stems(clause[num.end:])[:2] if _has(deck.stems, s)]
    return before, after


def _number_conflicts(clause: str, deck: Deck) -> list[Conflict]:
    """
    답이 낱말 X 에 숫자 N 을 붙였는데, 자료는 X 에 **다른** 숫자를 붙였고 N 은 자료에서 **다른** 낱말의 것이다.
    09-29 실측: 「타이밍 실패가 연 1.6%p로 가장 컸고 과잉 매매는 0.2%p」 — 자료 표는 타이밍 −1.2 · 과잉 매매 −1.6 ·
    거래 비용 −0.2. 숫자 자체는 다 자료에 있어서 F-08 식 「자료 밖 숫자」 검사로는 안 잡힌다.
    자료에 없는 숫자(계산한 합·반올림)는 짝을 모르니 건드리지 않는다.
    """
    out: list[Conflict] = []
    for num in numbers(clause):
        before, after = _terms_around(clause, num, deck)
        if not before:
            continue
        # 반올림한 같은 값도 그 값이다 — 차트 표 「9」 와 본문 「8.7」 은 같은 사실이다 (`Num.close_value`).
        holders = [r for r in deck.regions if any(num.close_value(n) for n in r.nums)]
        if not holders:
            continue
        # 자료와 같은 짝인지는 **절 전체**로 본다 — 「전체 4.8%p 격차의 58%」 처럼 한 절에 숫자가 여럿이면
        # 숫자 바로 앞 낱말이 다른 숫자의 것일 수 있다. 짝이 하나라도 맞으면 어긋남으로 보지 않는다(놓치는 쪽이 안전하다).
        near = before + after + [s for s in content_stems(clause) if _has(deck.stems, s)]
        if any(any(_has(r.stems, t) for t in near) for r in holders):
            continue
        # 행 이름이 숫자 구간(「50% 미만 | 7」)이면 표 제목·머리 행이 그 값의 주인을 말한다 — 절이 그 표의 **다른 행**을 부르지
        # 않을 때만 (「리튬인산철은 5000회」 는 같은 표 「전고체 | 5000」 의 값을 다른 행에 붙인 어긋남이다).
        clause_stems = content_stems(clause)
        if any(r.is_row and any(_has(r.context, t) for t in near) and not _names_other_row(clause_stems, r, deck)
               for r in holders):
            continue
        # 표 행 이름이 문서 변환기(OCR)에서 한 글자 틀려도(「종목수」→「중목수」) 그 행이 이 숫자의 주인이다.
        # 09-30 실측(수익률 Q6): 「종목 수 12 대 3」 이 11장 표 「중목수 | 12 | 3」 을 못 알아보고 8장 「수익 종목 | 52」 와
        # 짝지어져 맞는 답이 네 턴 내리 55 를 받고 답 보기로만 빠져나갔다.
        if any(r.is_row and _fuzzy_in(_row_key(r.text), clause) for r in holders):
            continue
        owners = [
            r for r in deck.regions
            if all(_has(r.stems, t) for t in before)
            and any(n.unit is None or num.unit is None or n.unit == num.unit for n in r.nums)
            # 표 행이 주인이려면 행 이름의 낱말이 **전부** 답의 절에 있어야 한다 — 「종목」 한 낱말로 「수익 종목」 행을 주인으로
            # 삼지 않는다(주어가 겹치는 정도가 약하면 어느 행의 값인지 모른다. 놓치는 쪽이 안전하다).
            and (not r.is_row or all(_has(near, t) for t in content_stems(_row_key(r.text))))
        ]
        if not owners:
            continue
        owner = min(owners, key=lambda r: (not r.is_row, len(r.text)))
        out.append(Conflict("number", owner.slide_no, owner.text, clause, " ".join(before) + "의 수치"))
    return out


def _names_other_row(clause_stems: list[str], row: DeckLine, deck: Deck) -> bool:
    """절이 같은 장 표의 **다른 행** 이름을 부르는가."""
    for r in deck.lines:
        if not r.is_row or r is row or r.slide_no != row.slide_no:
            continue
        key = content_stems(_row_key(r.text))
        if key and all(_has(clause_stems, k) for k in key):
            return True
    return False


def _nospace(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _row_key(row_text: str) -> str:
    """표 행 줄(「중목수 | 12 | 3」)의 행 이름 칸. 괄호 단위(「회전율(회)」 의 「(회)」)는 뗀다."""
    return re.sub(r"\([^)]*\)", "", (row_text or "").split("|")[0]).strip()


#: 한 글자 틀림을 같은 이름으로 볼 최소 길이 — 두 글자 이름은 한 글자만 달라도 다른 낱말이 된다.
FUZZY_KEY_MIN = 3


def _fuzzy_in(key: str, text: str) -> bool:
    """행 이름(key)이 글에 **한 글자까지 틀린 채** 들어 있는가 (띄어쓰기 무시). 문서 변환기의 글자 오인을 견딘다."""
    k, t = _nospace(key), _nospace(text)
    if len(k) < FUZZY_KEY_MIN or len(t) < len(k):
        return False
    return any(sum(a != b for a, b in zip(k, t[i:i + len(k)])) <= 1 for i in range(len(t) - len(k) + 1))


def _lcs(a: str, b: str) -> int:
    """가장 긴 공통 부분 문자열 길이 (짧은 문자열용)."""
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            best = max(best, k)
    return best


def _row_for(text: str, table: Table, min_len: int) -> int | None:
    """글에 가장 뚜렷하게 나오는 행 번호. 동률이면 모른다(None)."""
    flat = _nospace(text)
    scored = sorted(((_lcs(_nospace(name), flat), i) for i, (name, _) in enumerate(table.rows)), reverse=True)
    if not scored or scored[0][0] < min_len or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return None
    return scored[0][1]


def _magnitudes(values: list[float]) -> list[float]:
    """전부 음수(손실·감소 표)면 크기로 견준다 — 「더 크다」 는 절댓값이 크다는 말이다."""
    return [abs(v) for v in values] if all(v < 0 for v in values) else values


def _order_conflicts(clause: str, deck: Deck, prefix: str = "") -> list[Conflict]:
    """
    「X 가 Y 보다 높다」·「X 가 가장 크다」 를 **숫자 칸이 하나인 자료 표**와 견준다.
    09-29 실측: 「상위 25% 그룹은 … 기관보다 높은 수익」 — 자료 3장 표는 기관 8 · 개인 상위25% 6.
    """
    out: list[Conflict] = []
    for m in _THAN_RE.finditer(clause):
        after_dirs = [direction(w) for w in _WORD_RE.findall(clause[m.end():])]
        want = next((d for d in after_dirs if d), "")
        if not want:
            continue
        subject, other = clause[: m.start()], m.group(1)
        for table in deck.tables:
            iy = _row_for(other, table, 2)
            # 주어는 보통 문장 머리에 있다 — 「A 는 …해서 … B 보다 높다」 는 연결 어미에서 절이 갈린다.
            ix = _row_for(subject, table, 3)
            if ix is None and prefix:
                ix = _row_for(f"{prefix} {subject}", table, 3)
            if ix is None or iy is None or ix == iy:
                continue
            vx, vy = _magnitudes([table.rows[ix][1], table.rows[iy][1]])
            if (want == "up" and vx < vy) or (want == "down" and vx > vy):
                line = f"{table.rows[ix][0]} {table.rows[ix][1]:g} · {table.rows[iy][0]} {table.rows[iy][1]:g}"
                out.append(Conflict("order", table.slide_no, line, clause, f"{m.group(1)}보다 큰지 작은지"))
    sup = _SUPERLATIVE_RE.search(clause)
    if sup:
        want = next((d for d in [direction(w) for w in _WORD_RE.findall(clause[sup.end():])] if d), "")
        subject = clause[: sup.start()]
        if want and subject.strip():
            for table in deck.tables:
                ix = _row_for(subject, table, 3)
                if ix is None:
                    continue
                mags = _magnitudes([v for _, v in table.rows])
                target = max(mags) if want == "up" else min(mags)
                if mags[ix] != target:
                    line = " · ".join(f"{n} {v:g}" for n, v in table.rows)
                    out.append(Conflict("order", table.slide_no, line, clause, "무엇이 가장 큰지"))
    return out


#: 절과 자료 줄이 「같은 말을 하고 있다」 고 볼 최소 겹침. 방향·부정을 견주려면 주어가 같아야 한다.
STRONG_MATCH_MIN = 3
STRONG_MATCH_RATIO = 0.6


def _scored_lines(stems: list[str], deck: Deck) -> list[tuple[float, int, DeckLine]]:
    """
    (무게, 겹친 줄기 수, 줄) — 무게 순. 무게는 겹친 줄기마다 1/(그 줄기가 나오는 줄 수) 다.
    덱 곳곳에 나오는 낱말(주제어)보다 한 줄에만 나오는 낱말이 「그 줄을 말하고 있다」 는 더 센 신호라서다.
    """
    wanted = list(dict.fromkeys(stems))
    if not wanted:
        return []
    df = {s: sum(1 for ln in deck.lines if _has(ln.stems, s)) for s in wanted}
    out: list[tuple[float, int, DeckLine]] = []
    for ln in deck.lines:
        hit = [s for s in wanted if df[s] and _has(ln.stems, s)]
        if hit:
            out.append((sum(1.0 / df[s] for s in hit), len(hit), ln))
    out.sort(key=lambda x: (-x[0], -x[1], len(x[2].text)))
    return out


def _best_line(stems: list[str], deck: Deck) -> tuple[DeckLine | None, int]:
    """가장 가까운 자료 줄과 겹친 줄기 수. 무게가 같은 다른 줄이 있으면 None — 어느 줄과 견줄지 모른다."""
    scored = _scored_lines(stems, deck)
    if not scored:
        return None, 0
    if len(scored) > 1 and abs(scored[1][0] - scored[0][0]) < 1e-9 and scored[1][2].text != scored[0][2].text:
        return None, 0
    return scored[0][2], scored[0][1]


def _polarity_conflicts(clause: str, deck: Deck, question_stems: tuple[str, ...] = ()) -> list[Conflict]:
    """
    절이 자료 한 줄과 **거의 같은 말**을 하는데(주어·대상 낱말이 셋 이상, 그 줄 낱말의 60% 이상 겹침)
    방향(늘다/줄다·강하다/약하다)이나 부정이 반대다. 09-29 실측: 「종목 선정 능력과 수익률의 상관이 강하게 나왔고」
    ↔ 자료 「종목 선정 능력과 수익률의 상관은 약함」.
    한쪽에 방향 낱말이 둘 이상이면(「늘수록 낮아진다」) 짝을 모르니 보지 않는다.
    """
    # 「X 가 아니라 Y」 는 X 를 버리고 Y 를 세우는 말이다 — 대조는 **Y 쪽만** 한다. X 쪽 낱말로 자료 줄과 짝지으면
    # 버린 명제가 자료와 반대라고 잡힌다 (09-30 실측 수익률 함정 Q3: 「38만원이 아니라 48만원」 이 55).
    clause = _contrast_kept(clause)
    stems = [s for s in content_stems(clause, drop_units=True) if not direction(s)]
    line, hit = _best_line(stems, deck)
    if line is None or _quoted_by_question(line, question_stems):
        return []
    line_stems = [s for s in content_stems(line.text, drop_units=True) if not direction(s)]
    # 양쪽 다 거의 같은 말이어야 한다 — 긴 절이 짧은 자료 줄을 품고 딴말을 덧붙인 것이면 부정·방향이 어느 말에 걸렸는지 모른다.
    if (hit < STRONG_MATCH_MIN or hit < STRONG_MATCH_RATIO * max(1, len(set(line_stems)))
            or hit < STRONG_MATCH_RATIO * max(1, len(set(stems)))):
        return []
    a_dirs, l_dirs = directions(clause), directions(line.text)
    if len(a_dirs) == 1 and len(l_dirs) == 1 and a_dirs != l_dirs:
        return [Conflict("direction", line.slide_no, line.text, clause, "높고 낮은 방향")]
    if (not a_dirs and not l_dirs and negated(clause) != negated(line.text)
            and not _SOFT_NEG_RE.search(clause) and not _SOFT_NEG_RE.search(line.text)):
        return [Conflict("negation", line.slide_no, line.text, clause, "맞다·아니다 쪽")]
    return []


#: 「A 가 아니라 B」 의 B 쪽 (대조가 없으면 절 그대로).
_CONTRAST_SPLIT_RE = re.compile(r"(?:이|가)?\s*아니(?:라(?![고서면며는])|고)[,\s]+")
#: 부정 표지 없이 뜻으로 부정하는 말 — 「어렵다」「힘들다」「불가」「부족」「드물다」 는 「안 된다」 와 같은 쪽일 수 있다.
#: 이런 말이 한쪽에라도 있으면 부정의 짝을 글자로 못 가린다 — 놓친다 (09-30 실측: 「체감이 안 되지만」 ↔ 「체감하기 어려운」).
_SOFT_NEG_RE = re.compile(r"어렵|어려|힘들|힘든|불가|불충분|부족|드물|드문|무관|모르|몰라|없이|미흡|미미")


def _contrast_kept(clause: str) -> str:
    parts = _CONTRAST_SPLIT_RE.split(clause or "", maxsplit=1)
    return parts[1] if len(parts) == 2 and parts[1].strip() else clause


#: 자료의 **정의형 부정** 한 줄 — 「S 는 O 가 아니다」. 제목·요지에 흔한 꼴이고, 뜻이 분명해 짝이 짧아도 믿을 만하다.
#: 「A 가 아니라 B」 (대조)는 여기 안 든다 — 끝이 「아니다」 류로 닫혀야 한다.
_DEFINITION_NEG_RE = re.compile(
    r"^(?P<subj>[가-힣A-Za-z0-9]+?)(?:은|는)\s+(?P<obj>[^.?!]+?)(?:이|가)\s+"
    r"(?:아니다|아닙니다|아니에요|아니예요|없다|없습니다|없어요|않다|않습니다|않아요)[.!]?$"
)
#: 답 쪽의 부정 — 정의형 부정에서는 「아니라」「아닌」 도 부정이다(「하나의 상태가 아니라 여러 단계」).
_ANY_NEG_RE = re.compile(r"않|(?:^|\s)못|(?:^|\s)안\s+[가-힣]|없(?!이)|아니|아닌|아닙")


def _definition_conflicts(clause: str, deck: Deck, question_stems: tuple[str, ...] = ()) -> list[Conflict]:
    """
    자료가 「S 는 O 가 아니다」 라고 못 박았는데, 답이 S 와 O 의 머리말을 같이 말하면서 부정하지 않는다.
    09-29 실측(수면 1번 c, partial 75 통과): 자료 2장 제목 「잠은 하나의 상태가 아니다」 ↔ 답 「잠은 한 가지 상태로 쭉
    이어지기 때문에」. 방향·부정 검사(_polarity_conflicts)는 겹친 낱말이 둘뿐이라 못 잡았다.
    주어는 주제 조사(은·는)까지 같이 있어야 한다 — 다른 자리의 같은 낱말에 걸리지 않게.
    """
    if _ANY_NEG_RE.search(clause):
        return []
    out: list[Conflict] = []
    words = clause.split()
    for line in deck.lines:
        m = _DEFINITION_NEG_RE.match(line.text.strip())
        if not m or _quoted_by_question(line, question_stems):
            continue
        subj = m.group("subj").lower()
        obj_stems = content_stems(m.group("obj"))
        if not obj_stems:
            continue
        head = obj_stems[-1]
        has_subj = any(re.fullmatch(rf"{re.escape(subj)}(?:은|는)", w.lower()) for w in words)
        if has_subj and _has(content_stems(clause), head):
            out.append(Conflict("negation", line.slide_no, line.text, clause, f"{m.group('subj')}에 대해 자료가 부정한 말"))
    return out


#: 자료 줄의 낱말이 질문에 이만큼 들었으면 질문이 **그 줄을 따져 묻는** 것이다.
QUOTED_BY_QUESTION = 0.7


def _quoted_by_question(line: DeckLine, question_stems: tuple[str, ...]) -> bool:
    """
    질문이 이 자료 줄을 옮겨 와 「이 말이 안 맞는 경우는?」 처럼 따지는 중인가.
    그 줄에 반대로 답하는 것이 정답일 수 있다 — 방향·부정 대조에서 뺀다.
    09-29 벤치(health_glucose): 자료 5장이 「식사 순서만 바꾸면 혈당 스파이크는 완전히 막을 수 있습니다」 라고 과하게
    말하고, 질문이 그 문장을 인용해 경계를 물었다. 골자 「완전히 막을 수 없다」 가 이 줄과 부정이 달라 어긋남으로 잡혔다.
    """
    if not question_stems or not line.stems:
        return False
    inside = sum(1 for s in set(line.stems) if _has(question_stems, s))
    return inside >= QUOTED_BY_QUESTION * len(set(line.stems))


def conflicts(text: str, deck: Deck, question: str = "") -> list[Conflict]:
    """
    답(또는 골자)이 자료와 어긋나는 곳. 자료가 비었으면 빈 목록.
    question 을 주면 질문이 옮겨 와 따지는 자료 줄은 방향·부정 대조에서 뺀다(`_quoted_by_question`).
    """
    if deck.empty or not (text or "").strip():
        return []
    q_stems = tuple(content_stems(question))
    out: list[Conflict] = []
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        prefix = ""
        for clause in clauses(sentence):
            out += _number_conflicts(clause, deck)
            out += _order_conflicts(clause, deck, prefix)
            out += _polarity_conflicts(clause, deck, q_stems)
            out += _definition_conflicts(clause, deck, q_stems)
            prefix = f"{prefix} {clause}".strip()
    seen: set[tuple[str, str]] = set()
    unique: list[Conflict] = []
    for c in out:
        if (c.kind, c.claim) not in seen:
            seen.add((c.kind, c.claim))
            unique.append(c)
    return unique


#: 남의 말을 옮기는 꼴 — 절이 「…다고/라고」 로 끝나고, 출처(자료·N장·표·연구…)를 부르거나 다음 절이 「했어요·돼 있어요·적혀 있어요」 다.
_REPORTED_END_RE = re.compile(r"(?:다|라|자|냐)고\s*$")
_REPORTED_INLINE_RE = re.compile(r"(?:다|라)고\s*(?:했|말했|적혀|적었|돼\s*있|되어\s*있|써\s*있|쓰여|나와|나왔)")
_REPORT_SOURCE_RE = re.compile(r"자료|\d+\s*장|슬라이드|표에|그래프|연구|논문|발표에서")
_REPORT_VERB_RE = re.compile(r"^\s*(?:했|말했|적혀|적었|돼\s*있|되어\s*있|써\s*있|쓰여|나와|나왔|하더)")


def _reported(clause: str, following: str = "") -> bool:
    """이 절이 **출처의 말을 옮긴** 것인가 (「자료는 …가 아니라고」 + 「했어요」)."""
    if _REPORTED_INLINE_RE.search(clause) and _REPORT_SOURCE_RE.search(clause):
        return True
    return bool(_REPORTED_END_RE.search(clause) and (_REPORT_SOURCE_RE.search(clause) or _REPORT_VERB_RE.search(following)))

#: 판정이 **답을 평하는** 말 — 명제가 아니다.
_META_RE = re.compile(r"답변|답에|언급|제시|설명|빠져|빠졌|빠진|부족|누락|말하지|짚지|다루지")


def _restates_line(stems: list[str], line: str) -> bool:
    """절의 줄기가 자료 줄 하나를 **거의 그대로** 말하는가 — 그 줄 낱말(방향 낱말 빼고)의 60% 이상·셋 이상."""
    line_stems = {s for s in content_stems(line) if not direction(s)}
    if not line_stems:
        return False
    hit = sum(1 for s in line_stems if _has(stems, s))
    return hit >= min(STRONG_MATCH_MIN, len(line_stems)) and hit >= STRONG_MATCH_RATIO * len(line_stems)


def opposes(answer: str, judge_text: str, exempt: tuple[str, ...] | list[str] = ()) -> str:
    """
    판정 자신의 말(react·missing_points)이 답의 한 절을 **반대 방향·반대 부정으로** 다시 말하는가. 걸린 판정 절을 돌려준다.

    09-29 벤치(held-out): 그럴듯한 오답 4건이 partial 70~75 로 통과했는데, 그중 둘은 판정이 스스로 반대를 알았다 —
    답 「부담은 매칭 시도를 **늘리는** 효과」 에 missing 「부담이 매칭 시도를 **줄인다**는 핵심 근거가 빠져」,
    답 「완전히 막을 수 **있다**는 말은」 에 react 「막을 수 **없다**는 점을 정확히 짚었어요」(답에 없는 말을 칭찬).
    판정이 반대 명제를 정답으로 들고 있으면서 통과를 준 것은 자기모순이라, 코드가 통과를 막는다.
    """
    parts = clauses(answer)
    for i, a in enumerate(parts):
        # 「자료는 …라고 했어요」 처럼 **자료가 한 말을 옮긴** 절은 답의 주장이 아니라 인용이다 — 인용의 부정·방향은 옮기면서
        # 어미가 바뀌어(「아니다」→「아니라고」) 글자로는 뒤집힌 것처럼 보인다 (09-30 실측 녹음 수면 Q2: 자료대로 답한
        # 정답이 자기모순 60). 「…다고 봤어요」 는 자기 생각이라 인용이 아니다.
        if _reported(a, parts[i + 1] if i + 1 < len(parts) else ""):
            continue
        a = _contrast_kept(a)
        a_stems = [s for s in content_stems(a, drop_units=True) if not direction(s)]
        if len(a_stems) < 2:
            continue
        # 질문이 **따져 보라고 한** 자료 줄(탐침 근거)을 뒤집는 절은 자기모순 대조에서 뺀다 — 그 줄을 부정하는 것이 정답일 수
        # 있다. 09-29 P5 최종 평가(health): 판정 react 가 단정 줄 「완전히 막을 수 있다」 를 되풀이했고, 그 반대를 말한 골자가
        # 「자기모순」 으로 partial 60 을 받았다.
        if any(_restates_line(a_stems, line) for line in exempt):
            continue
        for j in clauses(judge_text):
            j_stems = [s for s in content_stems(j) if not direction(s)]
            hit = sum(1 for s in set(j_stems) if _has(a_stems, s))
            # 같은 명제를 두고 하는 말이어야 한다 — 낱말 셋 이상, 짧은 쪽의 60% 이상.
            if hit < STRONG_MATCH_MIN or hit < STRONG_MATCH_RATIO * min(len(set(a_stems)), len(set(j_stems))):
                continue
            a_dirs, j_dirs = directions(a), directions(j)
            if len(a_dirs) == 1 and len(j_dirs) == 1 and a_dirs != j_dirs:
                return j
            # 부정은 서술의 부정만 — 「A 가 아니라 B」 대조는 명제를 뒤집지 않는다(_NEG_RE).
            # 「…가 제시되지 않았어요」「…이 빠져 있어요」 는 답에 대한 평이지 세상에 대한 명제가 아니다 — 부정 대조에서 뺀다.
            if not a_dirs and not j_dirs and not _META_RE.search(j) and negated(a) != negated(j):
                return j
    return ""


# ---------------------------------------------------------------------------
# 골자가 자료로 받쳐지는가 · 답이 자료 사실을 말했는가 · 전제에 동의했는가
# ---------------------------------------------------------------------------

#: 골자 낱말 중 자료에 있어야 하는 몫. 활용 꼬리(「보여줘요」)는 자료에 없어도 되므로 1.0 이 아니다.
GIST_GROUNDED_MIN = 0.6


@dataclass(frozen=True)
class Support:
    ratio: float
    missing_numbers: tuple[str, ...]
    conflicts: tuple[Conflict, ...]

    @property
    def grounded(self) -> bool:
        return self.ratio >= GIST_GROUNDED_MIN and not self.missing_numbers and not self.conflicts


def support(text: str, deck: Deck, question: str = "", against: Deck | None = None) -> Support:
    """
    글(골자·골자 요소)의 낱말·숫자가 자료에 있는가, 자료와 어긋나는 짝이 있는가. 자료가 비면 받쳐진 것으로 본다.
    against 를 주면 어긋남은 그 덱으로 본다 — 탐침 질문은 따져 묻는 줄을 뺀 덱(`without_lines`)이 대조 원본이다.
    """
    if deck.empty or not (text or "").strip():
        return Support(1.0, (), ())
    stems = content_stems(text)
    ratio = (sum(1 for s in stems if _has(deck.stems, s)) / len(stems)) if stems else 1.0
    deck_nums = [n for r in deck.lines for n in r.nums]
    missing = tuple(
        f"{n.value:g}" for n in numbers(text) if not any(n.close_value(d) for d in deck_nums)
    )
    return Support(round(ratio, 2), missing, tuple(conflicts(text, against if against is not None else deck, question)))


def _holds(line_text: str, quote: str) -> bool:
    """자료 줄이 이 인용을 담거나 인용에 담기는가 (띄어쓰기 무시). 짧은 조각(8자 미만)은 우연히 걸리니 보지 않는다."""
    a, q = _nospace(clean_slide_text(line_text)), _nospace(clean_slide_text(quote)).rstrip(".")
    if len(q) < 8 or len(a) < 8:
        return False
    return q in a or a.rstrip(".") in q


def without_lines(deck: Deck, quotes: list[str] | tuple[str, ...]) -> Deck:
    """
    이 인용들을 담은 줄을 뺀 덱 — 판정의 **대조 원본**에서 뺄 때 쓴다.

    09-29 P5 최종 평가: 탐침 질문(단정의 경계 · 근거 없는 인과 · 긴장)은 자료 줄 **자체를 따져 보라는** 질문이다.
    판정 가드는 그 줄을 정답으로 삼아, 단정을 반박한 모범답에 「자료와 방향이 거꾸로」 를 주고 단정에 동의한 답은 통과시켰다.
    따져 묻는 줄은 채점 원본이 아니다 — 골자가 자료로 받쳐지는지 보는 낱말 집합(stems)은 그대로 둔다(낱말은 여전히 자료의 말이다).
    """
    wanted = [q for q in quotes if (q or "").strip()]
    if deck.empty or not wanted:
        return deck
    keep = tuple(ln for ln in deck.lines if not any(_holds(ln.text, q) for q in wanted))
    regions = tuple(r for r in deck.regions if not any(_holds(r.text, q) for q in wanted))
    return Deck(keep, regions, deck.tables, deck.stems)


def line_support(text: str, deck: Deck) -> int:
    """글의 내용 낱말을 **자료 한 곳**(한 줄 또는 이어진 두 줄)이 가장 많이 같이 말하는 수. 흩어진 낱말을 이어 붙인 요구인지 가린다."""
    stems = list(dict.fromkeys(content_stems(text)))
    return max((sum(1 for s in stems if _has(r.stems, s)) for r in deck.regions), default=0)


def nearest_lines(text: str, deck: Deck, k: int = 6) -> list[DeckLine]:
    """
    답의 절마다 가장 가까운 자료 줄 (근거 장 밖 포함, 동률이면 둘까지). 판정 LLM 이 대조할 수 있게 프롬프트에 싣는다.
    09-29 실측: 규칙성 질문의 근거 장은 4·7·8장인데, 오답 「주말에 늦잠으로 채우면 리듬까지 완전히 돌아온다」 를 반박하는
    줄은 6장에 있었다 — 프롬프트에 없으니 판정이 partial 75 「맞아요」 를 줬다.
    """
    out: list[DeckLine] = []
    for clause in clauses(text):
        scored = [x for x in _scored_lines(content_stems(clause), deck) if x[1] >= 2]
        if not scored:
            continue
        top = scored[0][0]
        for weight, _, line in scored[:2]:
            if weight >= top - 1e-9 and line not in out:
                out.append(line)
        if len(out) >= k:
            break
    return out[:k]


#: 답이 기대한 답(골자·인용)의 낱말을 이만큼 말했으면 「자료 사실을 말한 답」 이다.
STATES_REFERENCE_RATIO = 0.35
STATES_REFERENCE_MIN = 3


def states_reference(answer: str, question: str, reference: str) -> bool:
    """
    답이 **질문에 없던** 기대 답(골자·자료 인용)의 낱말·숫자를 충분히 말했는가.

    함정 표시가 틀린 질문(전제가 없는 질문)에 자료대로 답한 사람을 함정 가드가 wrong 으로 내리지 않게 하는 신호다.
    질문의 낱말을 되풀이한 것은 세지 않는다 — 전제를 되읊은 답도 질문 낱말은 다 갖고 있다.
    """
    q = content_stems(question)
    novel = [s for s in dict.fromkeys(content_stems(reference)) if not _has(q, s)]
    if not novel:
        return False
    said = content_stems(answer)
    hit = [s for s in novel if _has(said, s)]
    q_nums = numbers(question)
    ref_nums = [n for n in numbers(reference) if not any(n.same_value(x) for x in q_nums)]
    num_hit = [n for n in ref_nums if any(n.same_value(a) for a in numbers(answer))]
    if num_hit and len(hit) >= 2:
        return True
    return len(hit) >= STATES_REFERENCE_MIN and len(hit) >= STATES_REFERENCE_RATIO * len(novel)


_AGREE_OPEN_RE = re.compile(r"^\s*(네|예|응|맞아요|맞습니다|맞아|그렇습니다|그래요|그렇죠|그렇네요)(?=[\s,.!]|$)")
_AGREE_ANY_RE = re.compile(r"(질문|말씀)(하신|한)?\s*대로|전제가\s*(정확|맞)")
_CORRECT_RE = re.compile(r"아니|않|다르|달라|달랐|틀리|틀렸|틀린|잘못|사실은|오히려|없어요|없습니다|없었")


def explicit_agreement(answer: str) -> bool:
    """「네, 맞아요」·「질문한 대로예요」 처럼 전제를 그대로 받는다고 **말한** 답. 바로잡는 말이 섞였으면 아니다."""
    text = answer or ""
    if _CORRECT_RE.search(text):
        return False
    return bool(_AGREE_OPEN_RE.search(text) or _AGREE_ANY_RE.search(text))


#: 골자가 전제를 **바로잡는** 표지 — 부정·대조·「전제」「사실은」. 질문에도 있는 낱말은 세지 않는다.
_CORRECTS_PREMISE_RE = re.compile(r"전제|사실은|사실과|오해|잘못|틀리|틀린|다르|달라|아니|아닌|아닙|않|없(?!이)")


def gist_corrects_premise(gist: str, question: str) -> bool:
    """
    골자가 질문의 전제를 바로잡는 답인가 — 질문에 없는 부정·대조 표지가 골자에 있는가.

    09-29 두 덱 기준선·벤치(held-out 21/21): 함정 표시가 붙은 질문의 골자가 전제를 바로잡는 말을 **하나도** 안 담았다.
    질문에 거짓 전제가 실제로 없다는 뜻이다(F-08 이 표시만 남겼다). 그런 질문에서 「바로잡지 않았다」 는 흠이 아니다.
    """
    q_words = set(re.findall(r"[가-힣A-Za-z]+", question or ""))
    novel = " ".join(w for w in re.findall(r"[가-힣A-Za-z]+", gist or "") if w not in q_words)
    return bool(_CORRECTS_PREMISE_RE.search(novel))


def echoes_unsupported_number(answer: str, question: str, deck: Deck, reference: str = "") -> bool:
    """질문에만 있고 자료·기대 답에는 없는 숫자를 답이 되풀이했다 — 거짓 전제의 숫자를 받아들인 것이다."""
    # 「80%가 아니라 58%예요」 — 되풀이해도 바로잡는 말이면 동의가 아니다.
    if deck.empty or _CORRECT_RE.search(answer or ""):
        return False
    deck_nums = [n for r in deck.lines for n in r.nums] + numbers(reference)
    q_only = [n for n in numbers(question) if not any(n.same_value(d) for d in deck_nums)]
    said = numbers(answer)
    return any(any(n.same_value(a) for a in said) for n in q_only)
