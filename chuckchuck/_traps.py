"""
함정 질문의 **틀린 전제**를 자료에서 결정적으로 만든다. LLM 을 부르지 않는다 (qa/trap, 2026-09-29).

함정 질문은 자료의 사실 하나를 뒤집어 얹고(「자료에서 「…」라고 했는데, …」) 발표자가 그걸 바로잡는지 보는 연습이다.
`_grounding`·`_deck_claims` 와 같은 자리의 유틸이라 F-08·F-09 가 둘 다 import 해도 정책 위반이 아니다 (DEV_POLICY §4-1).

왜 코드가 만드나 (09-29 두 덱 기준선 §5-1 · 일반화 벤치 §3):
- triage LLM 이 붙인 함정 표시에는 질문에 거짓 전제가 없었다 — 함정 21/21. 판정은 표시만 보고 골자대로 한 정답을
  wrong 35 로 내렸다.
- fix08 이 「LLM 이 trap_premise 를 적어 오고 그게 자료와 어긋날 때만」 함정으로 두자 solar 는 한 번도 안 적었고,
  함정은 모든 트랙에서 0개가 됐다. 설계(QA_TRACK_TRAPS 5분 1 · 10분 3)가 통째로 꺼졌다.
그래서 전제는 코드가 **근거 장의 자료 줄 하나를 골라 한 곳만 바꿔** 만든다. 바꾼 곳이 곧 단서다 — 질문에 그 단서가
있는지(F-08), 답이 어느 쪽 단서를 말했는지(F-09)를 글자로 셀 수 있다. 자료 줄에서 확인할 것이 없으면 함정이 아니다
(자료 밖 말로 전제를 지어내지 않는다).

뒤집는 방법 (전부 구조로만 — 특정 발표의 낱말을 규칙에 넣지 않는다):
1. number   — 숫자+단위 하나를 자료에 없는 값(×2, 안 되면 ×½·×3·×1.5)으로. 표 행이면 「표에서 {행}의 {열} 값이 …」.
2. order    — 「X보다 (형용사) Y」 제목 꼴은 X·Y 를 맞바꾸고, 「X는 Y보다 …」 문장은 비교 두 대상을 맞바꾼다.
3. extreme  — 수치 표의 한 열에서 가장 큰 행을 가장 작은 행으로.
4. direction— 방향 서술어 짝(늘리다↔줄이다·높이다↔낮추다·끊다↔이어 주다 …, 어느 분야에나 쓰는 한국어 문법 낱말)을 뒤집거나,
               「A가 B를 일으킨다」 꼴의 원인·결과를 맞바꾼다.
5. negation — 「X가 아니라 Y」 를 「Y가 아니라 X」 로, 「…가 아닙니다/없습니다」 를 긍정으로.

단서 문법 (`TrapPremise.wrong/right`): number 는 「값+단위」 문자열, 나머지는 「머리|꼬리」 — 머리 낱말 뒤에 조사 하나가
끼어도 꼬리가 이어지면 맞다(「혈당 부하|보다」 ∋ 「혈당 부하보다」). 꼬리가 비면 머리만 본다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import _grounding as grounding
from ._deck_claims import explicit_agreement
from ._deck_claims import numbers as claim_numbers
from .contracts import TrapPremise

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

#: 전제로 쓸 자료 줄 길이. 짧으면 주장이 아니고, 길면 질문 한 문장에 못 얹는다 (길면 바꾼 절만 쓴다).
TRAP_LINE_MIN = 8
TRAP_LINE_MAX = 70
#: 종류별 선호. 수치·순서는 틀린 곳이 하나로 또렷해서 연습으로 좋고 판정도 확실하다.
KIND_PRIORITY = {"number": 3, "order": 3, "extreme": 3, "direction": 2, "negation": 1}
#: 자료 줄이 이 개념의 이름(또는 이름의 낱말)을 부르면 더하는 점수 — 개념과 묶인 사실을 먼저 고른다.
LABEL_BONUS = 2
#: 뒤집은 수치 후보 배율. 앞에서부터 자료에 없는 값이 나오면 쓴다.
NUMBER_FACTORS = (2.0, 0.5, 3.0, 1.5)

#: 숫자 뒤 단위 (긴 것 먼저). 시각(「18시」)·장 번호·서수는 단위로 받지 않는다 — 뒤집으면 말이 안 된다.
_UNITS = ("%p", "%", "배", "회", "번", "개월", "개", "년", "주", "명", "건", "만 원", "만원", "억 원", "억원", "억",
          "원", "분", "시간", "초", "점", "곳", "세", "살", "kg", "km", "cm²", "cm", "mm", "g", "m", "℃", "ml", "L")
_UNIT_ALT = "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))
_GEN_NUM_RE = re.compile(rf"(?<![\w.,])([-−]?)(\d{{1,3}}(?:,\d{{3}})+|\d+(?:\.\d+)?)(\s?)({_UNIT_ALT})?")
#: 단위 없는 숫자 뒤에 와도 되는 글자 — 조사. 「18시」·「1인」 의 시·인은 조사가 아니다.
_JOSA_START = set("이가은는을를의와과로에보도만")
#: 크기가 곧 뜻인 단위 — 한 자리 수여도 사실 숫자다(「2배」·「6%」). 셈 단위(개·곳·명)의 한 자리 수는 셈이다.
_MEASURE_UNITS = {"%", "%p", "배"}

#: 방향 서술어 짝 (앞 → 뒤, 뒤 → 앞 둘 다). 어느 분야에나 쓰는 한국어 문법 낱말만 둔다.
_DIRECTION_PAIRS = (
    ("늘어났습니다", "줄어들었습니다"), ("늘어납니다", "줄어듭니다"), ("늘어난다", "줄어든다"),
    ("늘렸습니다", "줄였습니다"), ("늘립니다", "줄입니다"), ("늘린다", "줄인다"),
    ("늘었습니다", "줄었습니다"), ("늘었다", "줄었다"), ("늘릴 수", "줄일 수"),
    ("높아졌습니다", "낮아졌습니다"), ("높아집니다", "낮아집니다"), ("높였습니다", "낮췄습니다"), ("높입니다", "낮춥니다"),
    ("높았습니다", "낮았습니다"), ("높습니다", "낮습니다"), ("높았다", "낮았다"), ("높다", "낮다"), ("높음", "낮음"),
    ("커졌습니다", "작아졌습니다"), ("커집니다", "작아집니다"), ("큽니다", "작습니다"),
    ("넓었습니다", "좁았습니다"), ("넓어집니다", "좁아집니다"), ("넓습니다", "좁습니다"),
    ("많았습니다", "적었습니다"), ("많습니다", "적습니다"),
    ("길어집니다", "짧아집니다"), ("길었습니다", "짧았습니다"), ("빨라집니다", "느려집니다"),
    ("증가합니다", "감소합니다"), ("증가했습니다", "감소했습니다"), ("상승했습니다", "하락했습니다"),
    ("개선됩니다", "악화됩니다"), ("개선했습니다", "악화했습니다"), ("상회", "하회"),
    ("끊습니다", "이어 줍니다"), ("끊는다", "이어 준다"), ("끊는", "이어 주는"),
    ("막습니다", "부추깁니다"), ("없앱니다", "만듭니다"), ("깎습니다", "올립니다"), ("해소합니다", "키웁니다"),
)
_DIRECTION_MAP = {**{a: b for a, b in _DIRECTION_PAIRS}, **{b: a for a, b in _DIRECTION_PAIRS}}
_DIRECTION_RE = re.compile("|".join(re.escape(w) for w in sorted(_DIRECTION_MAP, key=len, reverse=True)))

#: 원인 → 결과를 말하는 서술어 (방향이 없는 것). 「A가 B를 V」 의 A·B 를 맞바꾸면 원인과 결과가 뒤집힌다.
_CAUSE_VERBS = ("일으킵니다", "만듭니다", "낳습니다", "부릅니다", "유발합니다", "초래합니다", "결정합니다", "좌우합니다",
                "이어집니다")
_CAUSE_RE = re.compile(
    r"^(?P<x>[^,·]{2,24}?)(?P<j1>이|가|은|는)\s+(?P<y>[^,·]{2,24}?)(?P<j2>을|를|으로|로)\s+(?P<v>"
    + "|".join(_CAUSE_VERBS) + r")[.]?$")

#: 제목 꼴 비교 「X보다 (형용사) Y」 — 줄 전체가 이 꼴일 때만.
_TITLE_THAN_RE = re.compile(
    r"^(?P<x>[^,.?!|]{2,24}?)보다\s+(?P<adj>[가-힣]{1,6}(?:한|은|인|운|른|된|큰|진|난))\s+(?P<y>[^,.?!|]{2,24}?)[.]?$")
#: 문장 속 비교 「… Y보다 …」 의 Y. 「보다」 앞 낱말이 비교의 한쪽이다.
_THAN_TOKEN_RE = re.compile(r"(?P<y>[가-힣A-Za-z0-9]{2,})보다(?=\s)")
_FIRST_TOKEN_RE = re.compile(r"^\s*(?P<x>[가-힣A-Za-z0-9]{2,}?)(?P<j>은|는|이|가|의)?(?=\s)")
#: 비교의 한쪽이 될 수 없는 낱말 — 「생각보다·예상보다·평소보다」 는 기준점이지 비교 대상이 아니다. 어느 발표에나 쓰는 말.
_THAN_BASELINE = ("생각", "예상", "기대", "평소", "예전", "과거", "이전", "지난", "작년", "전년", "기존", "보통", "다른",
                  "무엇", "어느", "그것", "이것", "우리", "저희", "다만", "또한", "특히", "반대로", "결국")

#: 대조 「X(이|가) 아니라 Y」.
_CONTRAST_RE = re.compile(r"(?P<j>이|가)\s+아니라\s+")
_COPULA_END_RE = re.compile(r"(입니다|이에요|예요|이다|다)?[.]?$")
#: 「다」 로 끝나도 명사구가 아닌 꼴 — 서술어 끝.
_VERB_ENDS = ("니", "었", "았", "였", "했", "겠", "합", "됩", "습", "한", "된", "는", "진")
#: 부정 → 긍정. 「하지 않습니다」 처럼 활용이 분명한 꼴만 — 그 밖의 「…지 않습니다」 는 긍정꼴을 코드가 모른다.
_NEGATION_FLIPS = (
    (re.compile(r"(?P<n>[가-힣A-Za-z0-9]+?)(?:이|가|은|는)\s+아닙니다"), lambda m: f"{m.group('n')}입니다"),
    (re.compile(r"(?P<n>[가-힣A-Za-z0-9]+?)(?:이|가|은|는)\s+아니다"), lambda m: f"{m.group('n')}이다"),
    (re.compile(r"하지\s+않습니다"), lambda m: "합니다"),
    (re.compile(r"되지\s+않습니다"), lambda m: "됩니다"),
    (re.compile(r"수는?\s+없습니다"), lambda m: "수 있습니다"),
    (re.compile(r"없었습니다"), lambda m: "있었습니다"),
    (re.compile(r"없습니다"), lambda m: "있습니다"),
)

#: 답이 전제를 **바로잡는다고 말하는** 표지. 어느 발표에나 쓰는 말이다. 전제 문장에도 있는 표지는 세지 않는다.
_DISPUTE_MARKS = ("아니", "않", "다르", "달라", "달리", "틀리", "틀렸", "틀린", "잘못", "사실은", "사실과", "오히려", "반대",
                  "전제", "오해")
#: 질문 속 전제를 받아들였다고 보는 말 — 「가장」 없이 표의 끝을 말할 수 없다.
_SUPERLATIVE_RE = re.compile(r"가장|제일|최대|최고")
_JOSA_ALT = r"(?:이|가|은|는|을|를|의|와|과|도|에서|에)?"


# ---------------------------------------------------------------------------
# 한국어 조각
# ---------------------------------------------------------------------------

_DIGIT_BATCHIM = {"0": True, "1": True, "2": False, "3": True, "4": False, "5": False, "6": True, "7": True, "8": True,
                  "9": False}


def _batchim(word: str) -> bool | None:
    """마지막 소리에 받침이 있는가. 괄호 속(「(cm²)」)은 건너뛴다. 모르면 None."""
    w = re.sub(r"\([^)]*\)\s*$", "", (word or "").rstrip()).rstrip()
    w = re.sub(r"[\"'“”‘’「」『』]+$", "", w)
    if not w:
        return None
    ch = w[-1]
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    if ch in _DIGIT_BATCHIM:
        return _DIGIT_BATCHIM[ch]
    if ch == "%":
        return False       # 퍼센트
    return None


def josa(word: str, with_batchim: str, without: str) -> str:
    """낱말 + 받침에 맞는 조사. 받침을 모르면 「(이)가」 꼴."""
    b = _batchim(word)
    if b is None:
        return f"{word}({with_batchim}){without}" if len(with_batchim) == 1 else word + without
    return word + (with_batchim if b else without)


def _josa_only(word: str, with_batchim: str, without: str) -> str:
    return josa(word, with_batchim, without)[len(word):]


#: 줄 머리의 글머리표·번호(「· 」「05. 」「① 」「※ 」) — 문장이 아니라 꾸밈이다.
_BULLET_RE = re.compile(r"^(?:[·•▪◦\-–—*※]+|\d{1,2}[.)]|[①-⑳])\s*")


#: 줄 머리의 짧은 꼬리표(「정리 : 」「결론부터: 」) — 뒤에 문장이 이어질 때만 뗀다(「합격률: 42%」 는 꼬리표가 주어다).
_LEAD_LABEL_RE = re.compile(r"^[가-힣A-Za-z]{1,6}\s*:\s+(?=(?:\S+\s+){2,}\S)")


def _clean(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").replace("<br>", " ")).strip()
    t = _BULLET_RE.sub("", t).strip()
    return _LEAD_LABEL_RE.sub("", t).strip().rstrip(" .")


def _variants(phrase: str) -> list[str]:
    """단서 머리의 다른 꼴 — 통째, 첫 낱말, 끝 낱말(두 글자 이상). 발표자는 「탄수화물 양」 을 「탄수화물」 로 줄여 말한다."""
    p = _clean(phrase)
    parts = p.split()
    out = [p]
    if len(parts) >= 2:
        for w in (parts[0], parts[-1]):
            if len(grounding.squash(w)) >= 2 and re.search(r"[가-힣A-Za-z]", w) and w not in out:
                out.append(w)
    return out


def _cue(head: str, tail: str = "") -> list[str]:
    return [f"{v}|{tail}" for v in _variants(head)]


def _disjoint(wrong: list[str], right: list[str]) -> tuple[list[str], list[str]]:
    """두 쪽에 다 있는 머리 꼴은 뺀다 — 「수면 시간」·「수면의 질」 의 「수면」 은 어느 쪽 단서도 아니다."""
    heads_w = {grounding.squash(c.partition("|")[0]) for c in wrong}
    heads_r = {grounding.squash(c.partition("|")[0]) for c in right}
    # 한쪽 머리가 다른 쪽 머리 안에 들어 있어도 가려낼 수 없다 (「문제」 ⊂ 「실력의문제」·「행동의문제」)
    shared = {h for h in heads_w if any(h in o or o in h for o in heads_r)}
    shared |= {h for h in heads_r if any(h in o or o in h for o in heads_w)}
    keep_w = [c for c in wrong if grounding.squash(c.partition("|")[0]) not in shared]
    keep_r = [c for c in right if grounding.squash(c.partition("|")[0]) not in shared]
    return keep_w, keep_r


def _premise(kind: str, premise: str, fact: str, slide_no: int, wrong: list[str], right: list[str]) -> TrapPremise:
    w, r = (wrong, right) if kind == "number" else _disjoint(wrong, right)
    return TrapPremise(kind=kind, premise=premise, fact=fact, slide_no=slide_no, wrong=w, right=r)


# ---------------------------------------------------------------------------
# 후보
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    premise: TrapPremise
    score: int
    line: str          # 뒤집은 자료 줄 원문 — 같은 줄로 함정을 둘 만들지 않게


def _deck_values(idx) -> set[float]:
    vals: set[float] = set()
    for row in idx.all_rows():
        for n in grounding.numbers(row.text):
            try:
                vals.add(abs(float(n)))
            except ValueError:
                pass
    return vals


def _fmt(value: float, raw: str, sign: str) -> str:
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    body = f"{abs(value):,.{decimals}f}" if "," in raw else f"{abs(value):.{decimals}f}"
    return f"{sign}{body}"


def _wrong_value(raw: str, sign: str, unit: str, avoid: set[float]) -> str:
    """자료에 없는 뒤집힌 값. 퍼센트는 100 을 넘기지 않고, 정수는 정수로 남는 배율만."""
    v = float(raw.replace(",", ""))
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    for f in NUMBER_FACTORS:
        w = round(v * f, decimals)
        if unit == "%" and w > 100:
            continue
        if decimals == 0 and abs(w - round(w)) > 1e-9:
            continue
        if w == 0 or abs(w - v) < 1e-9 or abs(w) in avoid:
            continue
        return _fmt(w, raw, sign)
    return ""


def _eligible_number(m: re.Match, text: str, label_spans) -> bool:
    sign, raw, _, unit = m.groups()
    unit = unit or ""
    if any(s.start <= m.start(2) < s.end for s in label_spans):
        return False       # 라벨 안의 숫자(「상위 25%」)는 이름이다
    whole = float(raw.replace(",", ""))
    before = text[max(0, m.start() - 6):m.start()]
    if re.search(r"[’‘'`]\s*$", before):
        return False       # 「’26」 — 줄인 연도
    if re.search(r"(?:상위|하위|top|bottom)\s*$", before, re.I):
        return False       # 「상위 25%」 — 순위 구간은 집단의 이름이다
    if not unit:
        nxt = text[m.end():m.end() + 1]
        if nxt and ("가" <= nxt <= "힣") and nxt not in _JOSA_START:
            return False   # 「18시」·「1인」 — 모르는 셈 단위
        if nxt in (".", ":", "/") or text[m.start() - 1:m.start()] in (".", "/", ":"):
            return False   # 날짜·쪽 번호·시각
        if 1900 <= int(whole) <= 2100:
            return False   # 연도 · 「2026.09」 같은 날짜
    elif unit == "년" and "." not in raw and 1900 <= whole <= 2100:
        return False
    if unit in _MEASURE_UNITS:
        return True
    return "." in raw or whole >= 10


def _number_from_line(row, idx, avoid: set[float]) -> TrapPremise | None:
    text = row.text
    spans = grounding.label_spans(text, idx.labels)
    found = [m for m in _GEN_NUM_RE.finditer(text) if _eligible_number(m, text, spans)]
    if not found:
        return None
    m = found[-1]              # 줄의 끝 숫자가 대개 결과다 (「3,200원에서 1,900원으로 41% 줄었습니다」 의 41%)
    sign, raw, space, unit = m.group(1), m.group(2), m.group(3), m.group(4) or ""
    wrong = _wrong_value(raw, sign, unit, avoid)
    if not wrong:
        return None
    changed = text[:m.start()] + wrong + space + unit + text[m.end():]
    premise = _clean(changed)
    fact = _clean(text)
    if len(premise) > TRAP_LINE_MAX:
        # 긴 줄은 바꾼 숫자가 든 절만 — 질문 한 문장에 얹을 수 있게
        cl_fact = next((c for c in grounding.clauses(text) if f"{sign}{raw}" in c), "")
        cl_prem = next((c for c in grounding.clauses(changed) if wrong in c), "")
        if not cl_fact or not cl_prem or len(cl_prem) > TRAP_LINE_MAX:
            return None
        premise, fact = _clean(cl_prem), _clean(cl_fact)
    return TrapPremise(kind="number", premise=premise, fact=fact, slide_no=row.slide_no,
                       wrong=[f"{wrong}{unit}"], right=[f"{sign}{raw}{unit}"])


def _table_head(row) -> str:
    head = (row.cells[0] if row.cells else "").strip()
    if not re.search(r"[가-힣A-Za-z]", head):
        return ""          # 행 머리가 숫자뿐이면 무엇의 값인지 말할 수 없다
    if len(grounding.squash(head)) >= 2:
        return head
    hdr = [c.strip() for c in row.header.strip().strip("|").split("|")] if row.header else []
    return f"{hdr[0]} {head}".strip() if hdr and head and row.text != row.header else ""


def _column_name(row, k: int) -> str:
    if not row.header or row.text == row.header:
        return ""
    hdr = [c.strip() for c in row.header.strip().strip("|").split("|")]
    name = hdr[k] if k < len(hdr) else ""
    # 머리 행이 데이터 행이면(문서 변환기 버릇) 열 이름이 숫자다 — 이름으로 안 쓴다
    return "" if not name or grounding.numbers(name) and not re.search(r"[가-힣A-Za-z]{2,}", name) else name


def _number_from_table_row(row, idx, avoid: set[float]) -> TrapPremise | None:
    head = _table_head(row)
    if not head or row.text == row.header:
        return None
    for k in range(len(row.cells) - 1, 0, -1):
        cell = row.cells[k].strip()
        m = _GEN_NUM_RE.fullmatch(cell) or _GEN_NUM_RE.match(cell)
        if not m or m.group(0).strip() != cell:
            continue
        sign, raw, _, unit = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        wrong = _wrong_value(raw, sign, unit, avoid)
        if not wrong:
            continue
        col = _column_name(row, k)
        what = f"{head}의 「{col}」 값" if col else f"{head}의 값"
        premise = f"표에서 {josa(what, '이', '가')} {wrong}{unit}"
        fact = f"표에서 {josa(what, '은', '는')} {cell}"
        return TrapPremise(kind="number", premise=premise, fact=fact, slide_no=row.slide_no,
                           wrong=[f"{wrong}{unit}"], right=[f"{sign}{raw}{unit}"])
    return None


def _cell_number(cell: str) -> float | None:
    nums = grounding.numbers(cell)
    if len(nums) != 1:
        return None
    try:
        return float(nums[0]) * (-1 if re.search(r"[-−–]\s*\d", cell) else 1)
    except ValueError:
        return None


def _numeric_tables(rows) -> list[list]:
    """장 안의 이어진 표 행 묶음 가운데 **값 칸이 숫자인** 데이터 행들 (3행 이상)."""
    out, block = [], []
    for r in list(rows) + [None]:
        if r is not None and r.table and (not block or block[-1].header == r.header):
            block.append(r)
            continue
        data = [x for x in block if x.cells and any(_cell_number(c) is not None for c in x.cells[1:])]
        if len(data) >= 3:
            out.append(data)
        block = [r] if (r is not None and r.table) else []
    return out


def _extreme_from_table(block, idx) -> TrapPremise | None:
    width = min(len(r.cells) for r in block)
    for k in range(1, width):
        vals = [(v, r) for r in block if (v := _cell_number(r.cells[k])) is not None]
        if len(vals) < 3 or len({v for v, _ in vals}) != len(vals):
            continue
        heads = [r.cells[0].strip() for _, r in vals]
        if any(len(grounding.squash(h)) < 2 for h in heads) or len(set(heads)) != len(heads):
            continue       # 행 머리가 「A」 처럼 짧으면 답에서 가려낼 수 없다
        same_sign = all(v <= 0 for v, _ in vals) or all(v >= 0 for v, _ in vals)
        if not same_sign:
            continue
        key = (lambda t: abs(t[0]))
        top, low = max(vals, key=key), min(vals, key=key)
        col = _column_name(block[0], k) if block[0].header else ""
        size = "크기가" if all(v <= 0 for v, _ in vals) else ""
        what = f"「{col}」 {size or '값이'}" if col else (size or "값이")
        premise = f"표에서 {what} 가장 큰 것은 {low[1].cells[0].strip()}"
        fact = f"표에서 {what} 가장 큰 것은 {top[1].cells[0].strip()}({top[1].cells[k].strip()})"
        return _premise("extreme", premise, fact, block[0].slide_no, _cue(low[1].cells[0]), _cue(top[1].cells[0]))
    return None


def _deck_noun(word: str, idx) -> bool:
    """비교의 한쪽으로 믿을 만한 낱말 — 기준점 낱말이 아니고, 자료에 두 번 이상 나오거나 개념 이름에 든다."""
    w = grounding.stem(word)
    if len(w) < 2 or any(w.startswith(b) for b in _THAN_BASELINE):
        return False
    if any(grounding.mentions(lab, w) for lab in idx.labels):
        return True
    return grounding.squash(idx.text).count(grounding.squash(w)) >= 2


def _order_from_line(row, idx) -> TrapPremise | None:
    text = _clean(row.text)
    m = _TITLE_THAN_RE.match(text)
    # 제목 꼴은 끝이 명사구이고(서술어 끝 「…니다」 가 아니고) 앞쪽에 주어가 없을 때만 — 문장이면 아래 문장 꼴로 본다.
    if m and (m.group("y").endswith(("다", "요")) or re.search(r"[은는이가]\s", m.group("x"))):
        m = None
    if m:
        x, adj, y = m.group("x").strip(), m.group("adj"), m.group("y").strip()
        if grounding.squash(x) == grounding.squash(y):
            return None
        return _premise("order", f"{y}보다 {adj} {x}", text, row.slide_no, _cue(y, "보다"), _cue(x, "보다"))
    for clause in grounding.clauses(text):
        t = _THAN_TOKEN_RE.search(clause)
        f = _FIRST_TOKEN_RE.match(clause)
        if not t or not f or f.end("x") > t.start("y"):
            continue
        x, y = f.group("x"), t.group("y")
        if grounding.squash(x) == grounding.squash(y) or not (_deck_noun(x, idx) and _deck_noun(y, idx)):
            continue
        j = f.group("j") or ""
        new_j = {"은": _josa_only(y, "은", "는"), "는": _josa_only(y, "은", "는"), "이": _josa_only(y, "이", "가"),
                 "가": _josa_only(y, "이", "가"), "의": "의"}.get(j, "")
        swapped = (clause[:f.start("x")] + y + new_j + clause[f.end("j") if j else f.end("x"):t.start("y")]
                   + x + clause[t.end("y"):])
        premise, fact = _clean(swapped), _clean(clause)
        if not (TRAP_LINE_MIN <= len(premise) <= TRAP_LINE_MAX):
            continue
        return _premise("order", premise, fact, row.slide_no, _cue(x, "보다"), _cue(y, "보다"))
    return None


def _direction_from_line(row, idx) -> TrapPremise | None:
    text = _clean(row.text)
    if row.table or not (TRAP_LINE_MIN <= len(text) <= TRAP_LINE_MAX):
        return None
    spans = grounding.label_spans(text, idx.labels)
    for m in _DIRECTION_RE.finditer(text):
        nxt = text[m.end():m.end() + 1]
        if nxt and not (nxt.isspace() or nxt in ".,!;:)"):
            continue       # 「끊는다」 의 「끊는」 — 활용이 이어지는 자리는 짝이 안 맞는다
        if any(s.start <= m.start() < s.end for s in spans):
            continue       # 개념 이름 안의 낱말(「… 증가」)은 서술이 아니다
        if m.start() > 0 and "가" <= text[m.start() - 1] <= "힣":
            continue       # 낱말 가운데서 걸린 것
        new = _DIRECTION_MAP[m.group(0)]
        premise = text[:m.start()] + new + text[m.end():]
        return TrapPremise(kind="direction", premise=premise, fact=text, slide_no=row.slide_no,
                           wrong=[f"{new}|"], right=[f"{m.group(0)}|"])
    c = _CAUSE_RE.match(text)
    if c:
        x, y = c.group("x").strip(), c.group("y").strip()
        if not (_deck_noun(x.split()[-1], idx) and _deck_noun(y.split()[-1], idx)):
            return None
        j1 = _josa_only(y, "은", "는") if c.group("j1") in ("은", "는") else _josa_only(y, "이", "가")
        j2 = _josa_only(x, "을", "를") if c.group("j2") in ("을", "를") else ("으로" if _batchim(x) else "로")
        premise = f"{y}{j1} {x}{j2} {c.group('v')}"
        return _premise("direction", premise, text, row.slide_no, _cue(y, "(?:이|가|은|는)"), _cue(x, "(?:이|가|은|는)"))
    return None


def _negation_from_line(row, idx) -> TrapPremise | None:
    text = _clean(row.text)
    if row.table or not (TRAP_LINE_MIN <= len(text) <= TRAP_LINE_MAX):
        return None
    m = _CONTRAST_RE.search(text)
    if m:
        left = text[:m.start()].strip()
        left = re.split(r"\s[—–-]\s|:\s", left)[-1].strip()
        # 주제어(「…은/는 」)는 제자리에 두고 뒤의 명사구만 맞바꾼다 — 「S는 X가 아니라 Y다」 → 「S는 Y가 아니라 X다」
        topic = re.match(r"^(.*[은는]\s+)", left)
        prefix = topic.group(1) if topic else ""
        left = left[len(prefix):].strip()
        right_full = text[m.end():].strip().lstrip(",·- ").strip()
        end = _COPULA_END_RE.search(right_full)
        tail = end.group(1) or "" if end else ""
        right = right_full[:end.start()].strip() if end else right_full
        if len(grounding.squash(left)) < 2 or len(grounding.squash(right)) < 2 or len(right.split()) > 4:
            return None
        if tail == "다" and (right.endswith(_VERB_ENDS) or re.search(r"[을를]\s", right)):
            return None    # 「…를 봐야 합니다」 — 명사구가 아니면 맞바꿀 수 없다
        cop = {"입니다": "입니다", "이에요": _josa_only(left, "이에요", "예요"), "예요": _josa_only(left, "이에요", "예요"),
               "이다": _josa_only(left, "이다", "다"), "다": _josa_only(left, "이다", "다")}.get(tail, "")
        premise = f"{prefix}{right}{_josa_only(right, '이', '가')} 아니라 {left}{cop}"
        fact_from = text.find(prefix) if prefix else text.find(left)
        text = text[max(0, fact_from):] if fact_from > 0 else text
        return _premise("negation", premise, text, row.slide_no, _cue(right, "(?:이|가)?아니"), _cue(left, "(?:이|가)?아니"))
    for pat, repl in _NEGATION_FLIPS:
        n = pat.search(text)
        if n:
            premise = text[:n.start()] + repl(n) + text[n.end():]
            new = repl(n)
            return TrapPremise(kind="negation", premise=_clean(premise), fact=text, slide_no=row.slide_no,
                               wrong=[f"{new}|"], right=[f"{n.group(0)}|"])
    return None


#: 뒤 줄이 이만큼 짧으면 앞 줄의 서술어가 줄바꿈으로 떨어져 나온 것이다 (「…지수를 2.6%p」 / 「하회」).
_TAIL_ROW_MAX = 6
_SENTENCE_END_RE = re.compile(r"(?:다|요|음|임|함|[.!?])\s*$")


def _joined(rows: list) -> list:
    """글 상자 줄바꿈으로 서술어만 따로 떨어진 줄을 앞 줄에 붙인다. 표 행은 그대로."""
    out = []
    skip = False
    for i, row in enumerate(rows):
        if skip:
            skip = False
            continue
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if (nxt is not None and not row.table and not nxt.table and not _SENTENCE_END_RE.search(row.text)
                and 0 < len(grounding.squash(nxt.text)) <= _TAIL_ROW_MAX and not grounding.numbers(nxt.text)):
            out.append(grounding.Row(slide_no=row.slide_no, index=row.index, text=f"{row.text} {nxt.text}"))
            skip = True
            continue
        out.append(row)
    return out


def _mentions_label(text: str, label: str, summary: str = "") -> bool:
    if grounding.mentions(text, label) or any(grounding.mentions(text, w) for w in grounding.label_words(label)):
        return True
    head = grounding.head_word(label)
    return bool(head) and grounding.mentions(text, head)


def candidates(label: str, anchors: list[int], idx) -> list[Candidate]:
    """
    이 개념의 근거 장(anchors)에서 뒤집을 수 있는 자료 사실 전부 — 점수 높은 순.

    점수 = 종류 선호(KIND_PRIORITY) + 개념 이름을 부르는 줄이면 LABEL_BONUS. 자료가 없거나(idx None) 근거 장이 없으면 [].
    물음 줄(「…할까?」)·설문 보기처럼 주장이 아닌 줄은 쓰지 않는다.
    """
    if idx is None:
        return []
    avoid = _deck_values(idx)
    out: list[Candidate] = []
    for no in anchors:
        rows = idx.rows.get(no, [])
        for row in _joined(rows):
            if "?" in row.text or "？" in row.text:
                continue
            if len(re.findall(r"[A-Za-z]", row.text)) > len(re.findall(r"[가-힣]", row.text)):
                continue       # 차트 설명·영문 캡션(「(red bar)」) — 문서 변환기가 만든 줄이지 발표의 주장이 아니다
            if row.table:
                made = [_number_from_table_row(row, idx, avoid)]
            else:
                if len(_clean(row.text)) < TRAP_LINE_MIN:
                    continue
                made = [_number_from_line(row, idx, avoid), _order_from_line(row, idx),
                        _direction_from_line(row, idx), _negation_from_line(row, idx)]
            tied = _mentions_label(row.text, label) or (row.table and _mentions_label(row.header, label))
            for tp in made:
                if tp is None or not verify(tp, idx):
                    continue
                out.append(Candidate(tp, KIND_PRIORITY[tp.kind] + (LABEL_BONUS if tied else 0), row.text))
        for block in _numeric_tables(rows):
            tp = _extreme_from_table(block, idx)
            if tp is not None and verify(tp, idx):
                tied = any(_mentions_label(r.text, label) for r in block) or _mentions_label(block[0].header, label)
                out.append(Candidate(tp, KIND_PRIORITY["extreme"] + (LABEL_BONUS if tied else 0), block[0].header))
    out.sort(key=lambda c: -c.score)
    return out


def verify(tp: TrapPremise, idx) -> bool:
    """
    전제가 정말 **자료와 어긋나는가** — 코드가 만든 것도 한 번 더 대조한다.
    전제가 자료 한 줄과 글자까지 같으면 사실이다. 수치 전제면 바꾼 값이 자료 어디에도 없어야 한다.
    전제와 사실이 같은 말이면(뒤집기가 아무것도 안 바꿨으면) 함정이 아니다.
    """
    if idx is None or not tp.premise or not tp.fact or not tp.wrong or not tp.right:
        return False
    p = grounding.squash(tp.premise)
    if p == grounding.squash(tp.fact) or len(p) < grounding.PREMISE_MIN:
        return False
    if any(grounding.squash(r.text) == p for r in idx.all_rows()):
        return False
    if tp.kind == "number":
        vals = _deck_values(idx)
        for w in tp.wrong:
            nums = grounding.numbers(w)
            if not nums or abs(float(nums[0])) in vals:
                return False
    return True


# ---------------------------------------------------------------------------
# 질문 · 골자 · 이유 · 힌트 (결정적 문장)
# ---------------------------------------------------------------------------

_QUESTION_TAIL = {
    "number": "이 수치가 무엇을 보여 주는지 설명해 주세요.",
    "order": "왜 그런지 설명해 주세요.",
    "extreme": "그 까닭은 무엇인가요?",
    "direction": "그렇게 되는 이유를 설명해 주세요.",
    "negation": "그 근거는 무엇인가요?",
}
_WHAT_CHANGED = {"number": "수치", "order": "비교 순서", "extreme": "표의 순위", "direction": "방향", "negation": "긍정·부정"}


def _from_table(text: str) -> bool:
    return text.startswith("표에서 ")


def trap_question(tp: TrapPremise) -> str:
    """전제를 맞는 말처럼 얹은 질문 — 「자료에서 「…」라고 했는데, …」. 표에서 읽은 전제는 따옴표 없이 「자료 표에서 …」."""
    tail = _QUESTION_TAIL.get(tp.kind, _QUESTION_TAIL["number"])
    if _from_table(tp.premise):
        return f"자료 {josa(tp.premise, '이라고', '라고')} 했는데, {tail}"
    return f"자료에서 「{tp.premise}」라고 했는데, {tail}"


def trap_gist(tp: TrapPremise) -> str:
    """기대 답 — 전제를 자료의 사실로 바로잡는다 (자료 줄 그대로, 표면 표에서 읽은 값)."""
    if _from_table(tp.fact):
        where = f"자료 {tp.slide_no}장" if tp.slide_no else "자료"
        return f"질문의 전제와 달리, {where} {josa(tp.fact, '이에요', '예요')}."
    where = f"자료 {tp.slide_no}장은" if tp.slide_no else "자료는"
    return f"질문의 전제와 달리, {where} 「{tp.fact}」라고 해요."


def trap_why(label: str) -> str:
    """질문과 함께 보이는 이유 — 함정의 답을 흘리지 않는다."""
    name = f"「{label}」에 대해 " if label else ""
    return f"{name}질문이 말한 내용이 자료와 같은지 먼저 따져 보는 연습이에요."


def trap_hint(tp: TrapPremise) -> str:
    """막혔을 때 — 장을 가리키고 무엇을 대조할지만 말한다. 자료의 값·순서는 말하지 않는다."""
    where = f"자료 {tp.slide_no}장을" if tp.slide_no else "자료를"
    return f"{where} 다시 보고, 질문 속 {josa(_WHAT_CHANGED.get(tp.kind, '내용'), '이', '가')} 자료와 같은지 확인해 보세요."


# ---------------------------------------------------------------------------
# 단서 대조 — 질문이 전제를 실었나 (F-08) · 답이 어느 쪽을 말했나 (F-09)
# ---------------------------------------------------------------------------

def _num_cue_hit(text: str, cue: str) -> bool:
    want = claim_numbers(cue, skip_years=False)
    if not want:
        return False
    said = claim_numbers(text, skip_years=False)
    return any(any(w.same_value(n) for n in said) for w in want)


def _cue_hit(text: str, cue: str, kind: str) -> bool:
    if kind == "number":
        return _num_cue_hit(text, cue)
    head, _, tail = cue.partition("|")
    sq = grounding.squash(text)
    h = grounding.squash(head)
    if len(h) < 1:
        return False
    if not tail:
        return h in sq
    # 꼬리는 코드가 만든 정규식 조각이다 (자료 글자는 re.escape 로만 들어간다)
    return re.search(re.escape(h) + _JOSA_ALT + (tail if tail.startswith("(") else re.escape(tail)), sq) is not None


def hits(text: str, cues: list[str], kind: str) -> bool:
    return any(_cue_hit(text, c, kind) for c in cues)


#: 질문이 스스로 전제를 의심하게 만드는 말 — 「실제 값은 어떻게 되나요」「맞나요」 는 함정을 드러낸다 (qa/trap 벤치:
#: solar 문장 16개 중 2개가 「실제 값은…」 「실제 자료에서는 어떻게…」 로 물었다). 전제 문장에 있는 말은 세지 않는다.
_REVEAL_MARKS = ("실제", "사실", "정말", "맞나요", "맞는지", "맞다면", "맞습니까", "정확한지", "확인해", "다시 보면")


def question_carries(question: str, tp: TrapPremise) -> bool:
    """질문 문장이 전제를 실었는가 — 바꾼 단서가 있고, 자료의 단서(정답)는 없고, 전제를 의심하는 말이 없다.
    표의 순위 전제는 「가장」 까지."""
    if not question or not hits(question, tp.wrong, tp.kind) or hits(question, tp.right, tp.kind):
        return False
    if tp.kind == "extreme" and not _SUPERLATIVE_RE.search(question):
        return False
    if any(m in question and m not in tp.premise for m in _REVEAL_MARKS):
        return False
    return not _disputes(question, tp)


def strip_wrong(text: str, tp: TrapPremise) -> str:
    """글에서 전제의 단서(바꾼 값·낱말)를 뺀 나머지 — 질문의 **다른** 숫자가 자료에 있는지 볼 때 쓴다."""
    out = text or ""
    for cue in tp.wrong:
        head = cue.partition("|")[0]
        for piece in {head, *grounding.numbers(head), *re.findall(r"\d[\d,.]*", head)}:
            if piece:
                out = out.replace(piece, " ")
    return out


def _disputes(text: str, tp: TrapPremise) -> bool:
    """바로잡는 표지가 있는가 — 전제 문장에도 있는 표지(「…가 아니라」 전제의 「아니」)는 세지 않는다."""
    return any(m in text and m not in tp.premise for m in _DISPUTE_MARKS)


def without_premise(answer: str, tp: TrapPremise) -> str:
    """답에서 전제를 되뇌는 절(바꾼 단서가 든 절)을 뺀 나머지 — 「82%가 아니라 41%예요」 의 82% 를 자료 대조에서 빼려고."""
    kept = [c for c in grounding.clauses(answer) if not hits(c, tp.wrong, tp.kind)]
    return " ".join(kept)


def premise_stance(answer: str, tp: TrapPremise | None) -> str:
    """
    답이 전제를 어떻게 다뤘나 — "agree"(받아들임) · "correct"(바로잡음) · ""(모름 — LLM 판정에 맡긴다).

    - 자료의 단서(right)를 말했으면 바로잡은 것이다 — 전제의 단서(wrong)도 같이 말했으면 바로잡는 표지가 있어야 한다.
    - 전제의 단서만 말하고 바로잡는 표지가 없으면, 또는 「네, 맞아요」 면 받아들인 것이다.
    - 단서 없이 「자료와 달라요」 처럼 전제를 반박하면 바로잡은 것이다.
    """
    if tp is None or not (answer or "").strip():
        return ""
    right = hits(answer, tp.right, tp.kind)
    wrong = hits(answer, tp.wrong, tp.kind)
    dispute = _disputes(answer, tp)
    if right and (not wrong or dispute):
        return "correct"
    if wrong and dispute:
        return "correct"
    if wrong and not right:
        return "agree"
    if explicit_agreement(answer):
        return "agree"
    if dispute and not right:
        return "correct"
    return ""
