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
#: 뒤집은 수치 후보 배율 — ±20~50%. 줄마다 시작 자리를 달리한다(`_seed`).
#: 09-29 P5 최종 평가: 예전 (2.0, 0.5, 3.0, 1.5) 는 거의 늘 ×2 라 「광주기 32시간」「만 58세」「3,800원(두 배)」 처럼
#: 듣는 순간 틀린 줄 아는 값이 나왔다. 함정은 **믿을 만해야** 연습이 된다.
NUMBER_FACTORS = (1.5, 0.6, 1.3, 0.7, 1.4, 0.8, 1.25, 0.75)
#: 단위별 자연 상한 — 원래 값이 이 안이면 바꾼 값도 이 안에 둔다 (하루 24시간·100%·한 시간 60분…). 어느 분야에나 같은 단위 상식.
_UNIT_CAP = {"%": 100.0, "시간": 24.0, "분": 60.0, "초": 60.0, "개월": 12.0, "세": 100.0, "살": 100.0, "점": 100.0}

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


def _seed(text: str) -> int:
    """줄마다 다른(그러나 같은 줄이면 늘 같은) 시작 자리 — 모든 함정이 같은 배율로 바뀌지 않게."""
    return sum(ord(ch) for ch in text or "") % len(NUMBER_FACTORS)


def _grain(raw: str) -> float:
    """원래 값의 반올림 단위 — 소수 자릿수, 정수면 끝 0 의 수(84,200 → 100), 5 의 배수면 5. 바꾼 값도 같은 결로 쓴다."""
    digits = raw.replace(",", "")
    if "." in digits:
        return 10 ** -len(digits.split(".")[1])
    zeros = len(digits) - len(digits.rstrip("0"))
    if zeros and zeros < len(digits):
        return float(10 ** zeros)
    return 5.0 if digits.endswith("5") and len(digits) >= 2 else 1.0


def _in_bounds(w: float, v: float, unit: str) -> bool:
    cap = _UNIT_CAP.get(unit)
    if cap is not None and abs(v) <= cap and abs(w) > cap:
        return False
    return (w > 0) == (v > 0) or v == 0


def _wrong_value(raw: str, sign: str, unit: str, avoid: set[float], *, siblings: list[str] | tuple[str, ...] = (),
                 seed: int = 0) -> str:
    """
    믿을 만한 틀린 값. ① 같은 열·같은 장에서 **같은 단위로 쓰인 다른 값**(발표자가 실제로 헷갈릴 값)이 먼저,
    ② 없으면 ±20~50% 로 바꾸되 원래 값과 같은 결(자릿수·끝 0·5 단위)로 반올림하고 단위의 자연 상한을 지킨다.
    ② 는 자료 어디에도 없는 값이어야 한다 — 답이 어느 쪽을 말했는지 가려야 하므로.
    """
    v = float(raw.replace(",", ""))
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    for sib in siblings:
        try:
            w = float(sib.replace(",", ""))
        except ValueError:
            continue
        if abs(w - v) > 1e-9 and w != 0 and _in_bounds(w, v, unit):
            return sib
    g = _grain(raw)
    order = NUMBER_FACTORS[seed % len(NUMBER_FACTORS):] + NUMBER_FACTORS[:seed % len(NUMBER_FACTORS)]
    for f in order:
        w = round(round(v * f / g) * g, decimals)
        if decimals == 0 and abs(w - round(w)) > 1e-9:
            continue
        if w == 0 or abs(w - v) < 1e-9 or abs(w) in avoid or not _in_bounds(w, v, unit):
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
    if re.search(r"\d\s*[–~\-]\s*$", before) or re.match(r"\s*[–~]\s*\d", text[m.end():]):
        return False       # 「90–110분」 — 범위의 한 끝을 바꾸면 「90–80분」 처럼 범위가 뒤집힌다 (loop2 dry-run)
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


#: 식 줄 — 「A = B × C ÷ 100」 의 상수는 사실이 아니라 정의다. 바꾸면 틀린 전제가 아니라 다른 식이 된다.
_FORMULA_LINE_RE = re.compile(r"=.*[×✕*+÷/]")


def _number_from_line(row, idx, avoid: set[float]) -> TrapPremise | None:
    text = row.text
    if _FORMULA_LINE_RE.search(text):
        return None
    spans = grounding.label_spans(text, idx.labels)
    found = [m for m in _GEN_NUM_RE.finditer(text) if _eligible_number(m, text, spans)]
    if not found:
        return None
    m = found[-1]              # 줄의 끝 숫자가 대개 결과다 (「3,200원에서 1,900원으로 41% 줄었습니다」 의 41%)
    sign, raw, space, unit = m.group(1), m.group(2), m.group(3), m.group(4) or ""
    # 글 줄은 같은 장의 다른 값을 빌리지 않는다 — 09-29 dry-run: 「1년차 1,000만원」「최상위 구간 평균 25%」 처럼 다른 대상의 값이
    # 붙어 뜻이 없어졌다. 같은 줄 안의 대상이 무엇인지 코드가 모르니 ±20~50% 로만 바꾼다.
    wrong = _wrong_value(raw, sign, unit, avoid, seed=_seed(text))
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
    if not name or grounding.numbers(name) and not re.search(r"[가-힣A-Za-z]{2,}", name):
        return ""
    # 한글 자료에 영문이 대부분인 열 이름은 문서 변환기의 차트 설명 머리다(09-29 P5: 「Profit Margin (p.p., Annual)」) —
    # 발표자가 쓴 말이 아니다. 머리 행 전체가 한글이면 그 표는 한글 표다.
    # 한글이 없고 소문자 영단어가 든 이름(「Value」「Profit Margin (…)」)은 변환기가 차트에 붙인 머리다. 대문자 약어(「EBITDA」「Q/Q」)는 둔다.
    if not re.search(r"[가-힣]", name) and re.search(r"[a-z]{3,}", name):
        return ""
    return name


def _row_key(row) -> str:
    """표 첫 열의 이름(「연도」「메뉴」) — 행 머리가 무엇인지. 없으면 ""."""
    if not row.header:
        return ""
    first = row.header.strip().strip("|").split("|")[0].strip()
    return first if re.fullmatch(r"[가-힣]{1,8}", first) else ""


def _row_values(row, k: int, sign: str, unit: str) -> list[str]:
    """
    같은 행 **다른 열**의 값 가운데 부호·단위가 같은 것 (원문 표기) — 숫자 전제를 믿을 만한 값으로 바꿀 때 먼저 쓴다.
    같은 행은 같은 대상의 같은 지표라(「도입 전 | 도입 후」「30분 | 60분」) 열을 헷갈린 값이 가장 그럴듯한 틀린 값이다.
    같은 열의 다른 행은 쓰지 않는다 — 행마다 지표가 다른 표(행 머리가 지표 이름)에서 단위가 다른 값이 붙었다(09-29 dry-run).
    """
    out: list[str] = []
    for j, cell in enumerate(row.cells[1:], start=1):
        m = _GEN_NUM_RE.fullmatch(cell.strip() or "x")
        if j == k or not m or (m.group(4) or "") != unit or bool(m.group(1)) != bool(sign):
            continue
        out.append(m.group(2))
    return out


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
        col = _column_name(row, k)
        numeric = sum(1 for c in row.cells[1:] if _GEN_NUM_RE.fullmatch(c.strip() or "x"))
        if not col and numeric >= 2:
            continue       # 값 칸이 여럿인데 열 이름을 모르면 「무엇의 값」 인지 말할 수 없다 (09-29 P5)
        if float(raw.replace(",", "")) == 0:
            continue       # 0 은 「없음」 이다 — 다른 값으로 바꾸면 뜻이 바뀌는 게 아니라 다른 사실이 된다
        wrong = _wrong_value(raw, sign, unit, avoid, siblings=_row_values(row, k, sign, unit), seed=_seed(row.text))
        if not wrong:
            continue
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
        # 머리 행은 데이터가 아니다 — 「1인당 …」 처럼 열 이름에 숫자가 있으면 값 행으로 읽혔다 (09-29 P5: 극값 전제의 열 이름이 빠졌다)
        data = [x for x in block if x.cells and x.text != x.header
                and any(_cell_number(c) is not None for c in x.cells[1:])]
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
        units = {u for h in heads for u in re.findall(r"\(([^)]{1,6})\)", h)}
        if len(units) >= 2:
            continue       # 행 머리마다 단위가 다르면(「회전율(회)」「보유(월)」) 행끼리 견줄 수 없는 표다 — 가장 큰 행이 뜻이 없다
        same_sign = all(v <= 0 for v, _ in vals) or all(v >= 0 for v, _ in vals)
        if not same_sign:
            continue
        key = (lambda t: abs(t[0]))
        top, low = max(vals, key=key), min(vals, key=key)
        col = _column_name(block[0], k) if block[0].header else ""
        if not col:
            continue       # 어느 열의 끝인지 말할 수 없으면 만들지 않는다 (09-29 P5: 「값이 가장 큰 것은 2025」)
        size = "크기가" if all(v <= 0 for v, _ in vals) else "값이"
        key_name = _row_key(block[0])
        who = f"{josa(key_name, '은', '는')}" if key_name else "것은"
        premise = f"표에서 「{col}」 {size} 가장 큰 {who} {low[1].cells[0].strip()}"
        fact = f"표에서 「{col}」 {size} 가장 큰 {who} {top[1].cells[0].strip()}({top[1].cells[k].strip()})"
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
        swapped = _swap_compared(clause, idx)
        if swapped is None:
            continue
        premise, x, y = swapped
        fact = _clean(clause)
        premise = _clean(premise)
        if not (TRAP_LINE_MIN <= len(premise) <= TRAP_LINE_MAX) or grounding.squash(premise) == grounding.squash(fact):
            continue
        return _premise("order", premise, fact, row.slide_no, _cue(x, "보다"), _cue(y, "보다"))
    return None


#: 명사 뒤 조사(떼고 명사구를 본다). 긴 것 먼저.
_NP_JOSA_RE = re.compile(r"(?:에서는|으로는|에게는|에서|으로|에게|은|는|이|가|을|를|의|와|과|도|에|로|만)$")
#: 주어·화제 조사 — 비교 대상 명사구 바로 앞 낱말이 이것으로 끝나면 그 낱말은 다른 비교 대상(주어)이다.
_SUBJECT_JOSA = ("은", "는", "이", "가")
#: 관형형 끝(「화면을 본 시간」 의 「본」, 「중요한 것」 의 「중요한」) — 명사구를 꾸미는 절이다. 어느 분야에나 같은 문법.
_ADNOMINAL_RE = re.compile(r"(?:한|된|던|는|적인|같은|있는|없는|많은|작은|큰|높은|낮은|좋은|새로운)$")
#: 닮음·가까움 서술어 — 「보다」 가 주어가 아니라 다른 말(「C에」)과 견준다.
_SIMILAR_RE = re.compile(r"가깝|가까|비슷|닮|같")
#: 「Y보다 … 것은 X입니다」 — 비교의 다른 쪽이 서술어 자리에 있는 꼴.
_THING_IS_RE = re.compile(r"(?:것은|것이|건)\s+(?P<x>[^,.·]+?)(?:입니다|이다|예요|이에요|다)[.]?$")


def _bare_noun(token: str, idx) -> bool:
    """조사·관형형이 안 붙은 명사 낱말인가 — 자료에 두 번 이상 나오거나 개념 이름에 든다."""
    if not re.fullmatch(r"[가-힣A-Za-z0-9]+", token or "") or _ADNOMINAL_RE.search(token) or _NP_JOSA_RE.search(token) and len(token) > 2:
        return False
    return _deck_noun(token, idx) or any(grounding.mentions(lab, token) for lab in idx.labels)


def _np_before(tokens: list[str], end: int, idx, last: str) -> int:
    """tokens[end] 의 줄기(last)로 끝나는 명사구의 첫 낱말 자리. 앞 낱말은 조사 없는 명사일 때만 붙인다 (「대출 권수」)."""
    if not _bare_noun(last, idx):
        return -1
    start = end
    while start > 0 and _bare_noun(tokens[start - 1], idx):
        start -= 1
    return start


def _suffix_share(a: str, b: str) -> int:
    n = 0
    while n < min(len(a), len(b)) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


def _with_josa(word: str, josa_after: str) -> str:
    """낱말 뒤에 붙던 조사를 새 낱말의 받침에 맞춘다."""
    pairs = {"은": ("은", "는"), "는": ("은", "는"), "이": ("이", "가"), "가": ("이", "가"), "을": ("을", "를"),
             "를": ("을", "를"), "과": ("과", "와"), "와": ("과", "와")}
    if josa_after in pairs:
        return josa(word, *pairs[josa_after])
    return word + josa_after


def _swap_compared(clause: str, idx) -> tuple[str, str, str] | None:
    """
    문장 속 비교 「… Y보다 …」 의 두 대상을 **명사구째** 맞바꾼다 → (바꾼 절, 원래 X, 원래 Y). 못 가리면 None.

    09-29 P5 최종 평가: 예전엔 문장 첫 낱말과 「보다」 앞 낱말 **하나씩**을 바꿔 「권수 대출보다」「시간은 화면을 본 손실보다」
    가 나왔다. 이제는:
    - Y 는 「보다」 앞의 조사 없는 명사 낱말 묶음(「대출 권수」)이다. 그 앞 낱말이 관형형·목적어면(「화면을 본 시간」)
      Y 가 절의 꾸밈을 받는 것이라 바꾸지 않는다 — 주어 조사로 끝난 낱말만 앞에 올 수 있다.
    - X 는 ① 「Y보다 … 것은 X입니다」 의 X, ② 앞쪽 명사구 가운데 Y 와 끝 글자가 겹치는 것(같은 종류의 이름), ③ 없으면
      Y 바로 앞의 주어 명사구. 명사구는 조사 없는 명사 낱말 묶음이다.
    """
    tokens = clause.split()
    y_end = next((i for i, t in enumerate(tokens) if re.search(r"[가-힣A-Za-z0-9]보다$", t)), -1)
    if y_end < 0:
        return None
    y_last = tokens[y_end][: -len("보다")]
    y_start = _np_before(tokens, y_end, idx, y_last)
    if y_start < 0:
        return None
    y_words = tokens[y_start:y_end] + [y_last]
    y = " ".join(y_words)
    if any(y.startswith(b) for b in _THAN_BASELINE):
        return None
    before = tokens[y_start - 1] if y_start > 0 else ""
    if before and not before.endswith(_SUBJECT_JOSA) and not before.endswith((",", "—", "-")):
        return None        # 「화면을 본 시간보다」 — Y 가 꾸밈을 받는다
    rest = " ".join(tokens[y_end + 1:])
    if _SIMILAR_RE.search(rest):
        return None        # 「A는 B보다 C에 가깝다」 — 견주는 쪽이 B·C 라 A 와 B 를 바꾸면 뜻이 없어진다 (09-29 P5 focus)
    thing = _THING_IS_RE.search(rest)
    if y_start == 0 and thing:
        x = thing.group("x").strip()
        if not all(_bare_noun(w, idx) for w in x.split()) or len(x.split()) > 4:
            return None
        head = " ".join(tokens[:y_start])
        new_rest = rest[:thing.start("x")] + y + rest[thing.end("x"):]
        return f"{head} {x}보다 {new_rest}".strip(), x, y
    # 앞쪽 명사구 후보 (낱말 하나씩과 묶음) — 조사를 뗀 줄기로 본다
    cands: list[tuple[int, int, str, str]] = []      # (시작, 끝, 명사구, 뒤 조사)
    for i in range(y_start):
        m = _NP_JOSA_RE.search(tokens[i])
        stem = tokens[i][: m.start()] if m and len(tokens[i]) - len(m.group(0)) >= 1 else tokens[i]
        j = m.group(0) if m and stem != tokens[i] else ""
        s0 = _np_before(tokens, i, idx, stem)
        if s0 >= 0:
            cands.append((s0, i, " ".join(tokens[s0:i] + [stem]), j))
            if s0 < i:
                cands.append((i, i, stem, j))
    if not cands:
        return None
    y_head = y_words[-1]
    shared = [c for c in cands if _suffix_share(c[2].split()[-1], y_head) >= 1 and grounding.squash(c[2]) != grounding.squash(y)]
    if shared:
        pick = max(shared, key=lambda c: (_suffix_share(c[2].split()[-1], y_head), -c[0]))
    else:
        subj = [c for c in cands if c[1] == y_start - 1 and c[3] in _SUBJECT_JOSA]
        if not subj:
            return None
        pick = subj[0]
    s0, e0, x, jx = pick
    if grounding.squash(x) == grounding.squash(y):
        return None
    out = tokens[:s0] + [_with_josa(y, jx)] + tokens[e0 + 1:y_start] + [f"{x}보다"] + tokens[y_end + 1:]
    return " ".join(out), x, y


def _direction_from_line(row, idx) -> TrapPremise | None:
    text = _clean(row.text)
    if row.table or not (TRAP_LINE_MIN <= len(text) <= TRAP_LINE_MAX):
        return None
    if row.index == 0 and not _SENTENCE_END_RE.search(text):
        return None        # 장 제목(「…을 끊는 4 단계」)은 주장이 아니라 이름표다 — 뒤집어도 물을 거리가 안 된다 (loop2 dry-run)
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
        # 뒤 줄이 그 자체로 존댓말 문장(「감사합니다」)이면 떨어진 서술어가 아니다 — 09-29 P5: 「연 6,800만 원 감사합니다」 가 전제가 됐다.
        if (nxt is not None and not row.table and not nxt.table and not _SENTENCE_END_RE.search(row.text)
                and 0 < len(grounding.squash(nxt.text)) <= _TAIL_ROW_MAX and not grounding.numbers(nxt.text)
                and not re.search(r"(?:니다|요)[.!]?\s*$", nxt.text)):
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


#: 라벨 낱말이 이 몫보다 많은 장에 나오면 덱 주제어다 — 그 낱말 하나로는 「이 개념의 사실」 이라고 묶지 않는다.
DISTINCTIVE_SLIDE_SHARE = 0.5


def _distinctive(word: str, idx) -> bool:
    """라벨 낱말이 이 덱에서 개념을 가려 주는 말인가 — 장 절반 이하에만 나온다. 09-30 실측: 「깊은 수면」 의 「수면」 은 수면
    발표 모든 장에 있어서 「수면의 연속성을 끊는 요인」 줄이 「깊은 수면」 함정이 됐다."""
    slides = [no for no, rows in idx.rows.items() if rows]
    if not slides:
        return False
    hit = sum(1 for no in slides if any(grounding.mentions(r.text, word) for r in idx.rows[no]))
    return hit <= DISTINCTIVE_SLIDE_SHARE * len(slides)


def _tied(text: str, label: str, idx) -> bool:
    """자료 줄이 **이 개념의** 사실인가 — 라벨 통째, 또는 덱 주제어가 아닌 라벨 낱말·머리 낱말을 부른다.
    라벨이 비면(개념 없이 자료 줄만 훑을 때) 묶을 대상이 없어 거르지 않는다."""
    if not (label or "").strip() or grounding.mentions(text, label):
        return True
    words = [w for w in grounding.label_words(label)] + [grounding.head_word(label)]
    return any(w and grounding.mentions(text, w) and _distinctive(w, idx) for w in words)


def _chart_rounded(row, idx) -> bool:
    """
    표 행의 정수 값이 같은 장 본문의 소수 값을 반올림한 것인가 — 문서 변환기가 차트 막대를 읽은 표다(「시장지수 | 9」 ↔ 본문 「8.7%」).
    09-30 실측(수익률 Q4·Q5): 이런 행으로 만든 함정은 사실이 「9」 라서, 본문 값 「8.7」 로 바로잡은 정답이 동의로 읽혔다.
    반올림한 값은 발표자가 말할 값이 아니다 — 함정 재료로 쓰지 않는다.
    """
    body = [n for r in idx.rows.get(row.slide_no, []) if not r.table for n in claim_numbers(r.text, skip_years=False)]
    decimals = [n for n in body if n.decimals > 0]
    if not decimals:
        return False
    for cell in row.cells[1:]:
        for v in claim_numbers(cell, skip_years=False):
            if v.decimals == 0 and any(v.close_value(d) and not v.same_value(d) for d in decimals):
                return True
    return False


def _cover_slide(idx) -> int | None:
    """
    표지 장 — 덱 첫 장인데 **문장이 하나도 없다**(제목·부제·발표자 이름뿐). 첫 장이라도 문장으로 주장을 하면 표지가 아니다.
    09-30 실측(focus): 표지 줄 「척척발표 데모 용 10분 발표 알림 하나를」 이 「집중 손실」 함정이 됐다 — 발표 길이를 뒤집은
    전제라 답할 거리가 없었다. 표지·부제는 이름표지 자료의 사실이 아니다.
    """
    first = min((no for no, rows in idx.rows.items() if rows), default=None)
    if first is None:
        return None
    rows = idx.rows[first]
    return None if any(not r.table and _SENTENCE_END_RE.search(_clean(r.text)) for r in rows) else first


def candidates(label: str, anchors: list[int], idx) -> list[Candidate]:
    """
    이 개념의 근거 장(anchors)에서 뒤집을 수 있는 자료 사실 전부 — 점수 높은 순.

    점수 = 종류 선호(KIND_PRIORITY) + 개념 이름을 부르는 줄이면 LABEL_BONUS. 자료가 없거나(idx None) 근거 장이 없으면 [].
    물음 줄(「…할까?」)·설문 보기처럼 주장이 아닌 줄은 쓰지 않는다.

    09-30 대화 감사 §12 로 더 거른다 — 함정은 **이 개념의 자료 사실**이어야 연습이 된다.
    - 표지(문장 없는 덱 첫 장)는 재료가 아니다 (`_cover_slide` — 「척척발표 데모 용 10분 발표」 가 「집중 손실」 함정이 됐다).
    - 차트 반올림 값 표 행은 재료가 아니다 (`_chart_rounded`).
    - 줄이 이 개념을 불러야 한다(`_tied`) — 덱 주제어 하나 겹친 줄은 다른 개념의 사실이다.
    """
    if idx is None:
        return []
    avoid = _deck_values(idx)
    cover = _cover_slide(idx)
    out: list[Candidate] = []
    for no in anchors:
        if no == cover:
            continue
        rows = idx.rows.get(no, [])
        heading_tied = any(_tied(r.text, label, idx) for r in rows[:grounding.HEADING_ROWS] if not r.table)
        for row in _joined(rows):
            if "?" in row.text or "？" in row.text:
                continue
            if len(re.findall(r"[A-Za-z]", row.text)) > len(re.findall(r"[가-힣]", row.text)):
                continue       # 차트 설명·영문 캡션(「(red bar)」) — 문서 변환기가 만든 줄이지 발표의 주장이 아니다
            # 장 머리(제목·부제)가 이 개념을 부르면 그 장의 줄은 이 개념의 사실이다 (「격차를 만든 다섯 가지 행동 요인」 장의 표).
            tied = (heading_tied or _tied(row.text, label, idx) or (row.table and _tied(row.header, label, idx)))
            if not tied:
                continue
            if row.table:
                if _chart_rounded(row, idx):
                    continue
                made = [_number_from_table_row(row, idx, avoid)]
            else:
                if len(_clean(row.text)) < TRAP_LINE_MIN:
                    continue
                made = [_number_from_line(row, idx, avoid), _order_from_line(row, idx),
                        _direction_from_line(row, idx), _negation_from_line(row, idx)]
            for tp in made:
                if tp is None or not verify(tp, idx):
                    continue
                out.append(Candidate(tp, KIND_PRIORITY[tp.kind] + LABEL_BONUS, row.text))
        for block in _numeric_tables(rows):
            tied = heading_tied or any(_tied(r.text, label, idx) for r in block) or _tied(block[0].header, label, idx)
            if not tied:
                continue
            tp = _extreme_from_table(block, idx)
            if tp is not None and verify(tp, idx):
                out.append(Candidate(tp, KIND_PRIORITY["extreme"] + LABEL_BONUS, block[0].header))
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
        # 바꾼 값이 **사실 줄**의 값이면 전제가 사실이다. 같은 표의 다른 행·같은 장 다른 줄의 값은 된다 — 발표자가 실제로
        # 헷갈릴 값이 더 믿을 만한 함정이다 (09-29 P5). 그 줄에 없는 값인지는 사실 문장과 견준다.
        fact_vals = {abs(float(n)) for n in grounding.numbers(tp.fact)}
        for w, r in zip(tp.wrong, tp.right):
            nums, rn = grounding.numbers(w), grounding.numbers(r)
            if not nums or abs(float(nums[0])) in fact_vals or (rn and float(nums[0]) == float(rn[0])):
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


def trap_narrow(tp: TrapPremise) -> str:
    """
    함정 질문의 첫 「모르겠어요」 — **장만 가리킨다.** 자료의 값·순서·사실 줄은 말하지 않는다.
    09-29 P5 최종 평가 문제 6: 코칭 1단(narrow)이 사실 줄을 인용 카드로 바로 보여 줘서 함정이 첫 「모르겠어요」 에 풀렸다.
    """
    where = f"자료 {tp.slide_no}장을" if tp.slide_no else "자료를"
    what = josa(_WHAT_CHANGED.get(tp.kind, "내용"), "이", "가")
    return f"{where} 떠올려 볼래요? 질문이 말한 {what} 그 장에 적힌 것과 같은지부터 짚어 보면 돼요."


def leaks_fact(text: str, tp: TrapPremise) -> bool:
    """글이 자료의 사실(정답 단서·사실 줄)을 흘리는가 — 함정 코칭 1·2단 문장 검사."""
    if not text:
        return False
    return hits(text, tp.right, tp.kind, tolerant=True) or (
        len(grounding.squash(tp.fact)) >= 8 and grounding.squash(tp.fact) in grounding.squash(text))


# ---------------------------------------------------------------------------
# 단서 대조 — 질문이 전제를 실었나 (F-08) · 답이 어느 쪽을 말했나 (F-09)
# ---------------------------------------------------------------------------

def _num_cue_hit(text: str, cue: str, tolerant: bool = False) -> bool:
    want = claim_numbers(cue, skip_years=False)
    if not want:
        return False
    said = claim_numbers(text, skip_years=False)
    if tolerant:
        # 자료의 값은 반올림한 다른 표기로도 말할 수 있다 — 차트 「9」 ↔ 본문 「8.7」 (`Num.close_value`, 09-30 실측 수익률 Q4)
        return any(any(w.close_value(n) for n in said) for w in want)
    return any(any(w.same_value(n) for n in said) for w in want)


#: 단서 머리 끝의 부정 서술어 → 활용이 바뀌어도 남는 줄기. 「상태가 아니다」 는 답에서 「상태가 아니라고·아니에요」 로 온다.
_NEG_PRED_RE = re.compile(r"(아니다|아닙니다|아니에요|아니예요|않다|않습니다|않아요|없다|없습니다|없어요)$")
_NEG_PRED_STEM = {"아니다": "아니", "아닙니다": "아니", "아니에요": "아니", "아니예요": "아니", "않다": "않", "않습니다": "않",
                  "않아요": "않", "없다": "없", "없습니다": "없", "없어요": "없"}


def _relaxed_heads(h: str) -> list[str]:
    """자료 쪽 단서 머리의 다른 꼴 — 부정 서술어의 줄기(「상태가아니」), 「것은」↔「건」. 세 글자 미만은 우연히 걸려 버린다."""
    out: list[str] = []
    m = _NEG_PRED_RE.search(h)
    if m:
        out.append(h[: m.start()] + _NEG_PRED_STEM[m.group(1)])
    out += [x.replace("것은", "건").replace("것이", "게") for x in [h, *out] if "것은" in x or "것이" in x]
    return [x for x in out if len(x) >= 3 and x != h]


def _cue_hit(text: str, cue: str, kind: str, tolerant: bool = False) -> bool:
    if kind == "number":
        return _num_cue_hit(text, cue, tolerant)
    head, _, tail = cue.partition("|")
    sq = grounding.squash(text)
    h = grounding.squash(head)
    if len(h) < 1:
        return False
    if not tail:
        # 자료 쪽 단서는 활용이 바뀐 꼴도 받는다 — 09-30 실측: 「…상태가 아니라고 했어요」 가 단서 「상태가 아니다」 를 못 맞혔다.
        return h in sq or (tolerant and any(x in sq for x in _relaxed_heads(h)))
    # 꼬리는 코드가 만든 정규식 조각이다 (자료 글자는 re.escape 로만 들어간다)
    return re.search(re.escape(h) + _JOSA_ALT + (tail if tail.startswith("(") else re.escape(tail)), sq) is not None


def hits(text: str, cues: list[str], kind: str, tolerant: bool = False) -> bool:
    """글에 단서가 있는가. tolerant 는 **자료 쪽 단서**(정답)에만 켠다 — 반올림 값·활용이 바뀐 부정도 같은 사실이다.
    틀린 쪽 단서(전제)는 글자 그대로만 본다 — 느슨하게 보면 바로잡은 답을 동의로 읽는다."""
    return any(_cue_hit(text, c, kind, tolerant) for c in cues)


#: 질문이 스스로 전제를 의심하게 만드는 말 — 「실제 값은 어떻게 되나요」「맞나요」 는 함정을 드러낸다 (qa/trap 벤치:
#: solar 문장 16개 중 2개가 「실제 값은…」 「실제 자료에서는 어떻게…」 로 물었다). 전제 문장에 있는 말은 세지 않는다.
#: 09-29 P5: 「이 주장은 **자료와 어떻게 다른가요**?」 가 통과했다 — 다름·차이·오류를 묻는 말도 함정을 드러낸다.
_REVEAL_MARKS = ("실제", "사실", "정말", "맞나요", "맞는지", "맞다면", "맞습니까", "정확한지", "확인해", "다시 보면",
                 "다른가요", "다른지", "다릅니까", "어떻게 다른", "달라진", "차이가 있", "차이는", "틀린", "틀렸", "오류", "잘못")
#: 전제 뒤 물음에 와도 되는 낱말 — 전제를 두고 **무엇을·왜** 묻는 뼈대. 이 밖의 낱말이 전제·사실·개념 이름에 없으면
#: 전제와 따로 노는 둘째 질문이다 (09-29 P5: 「…18,416이라고 했는데, 차입금과 현금의 동시 보유가 재무 전략에 미치는 의미는?」).
_TAIL_FRAME = ("무엇", "어떻", "어떤", "어느", "설명", "이유", "근거", "의미", "보여", "수치", "주장", "자료", "결과",
               "까닭", "말해", "알려", "그렇", "이렇", "생각", "해석", "핵심", "발표", "이것", "그것", "나타", "시사", "가리키",
               "되는", "하는", "있는", "그런", "이런", "얼마", "보나요", "보는", "볼", "뜻", "주세요", "주는", "주나", "인가요",
               "나요", "하나", "되나", "할까", "까요", "해요", "했나", "였나", "왜", "그래서", "그러면", "이렇게", "그렇게",
               "그게", "이게", "그건", "이건", "무슨", "어째서", "정도", "뭔가", "뭐", "뭘")
#: 꼬리의 새 낱말이 이만큼이면 딴 질문이다. 하나(「비결이 뭔가요」)는 전제를 두고 **왜** 를 달리 말한 것이라 둔다.
TAIL_NOVEL_MAX = 1
#: 전제를 얹는 이음말 — 여기부터가 전제에 대해 묻는 꼬리다.
_CARRY_RE = re.compile(r"(?:했는데|하는데|이라는데|라는데|인데|다는데|는데)\s*,?\s*")


def _carry_end(question: str) -> int:
    """전제를 얹는 이음말이 끝나는 자리 — 없으면 -1 (「…라는 주장은 무엇인가요」 는 전제를 발표자의 말로 얹지 않은 꼴이다)."""
    m = None
    for m in _CARRY_RE.finditer(question or ""):
        pass
    return m.end() if m is not None else -1


def _tail_novel(question: str, tp: TrapPremise, label: str = "") -> list[str]:
    """전제 뒤 물음의 낱말 가운데 전제·사실·개념 이름·물음 뼈대 어디에도 없는 것 (+ 전제 밖 숫자)."""
    end = _carry_end(question)
    if end < 0:
        return []
    tail = question[end:]
    known = grounding.squash(" ".join([tp.premise, tp.fact, label]))
    out = [w for w in re.findall(r"[가-힣A-Za-z]{2,}", tail)
           if not w.startswith(_TAIL_FRAME) and grounding.squash(grounding.stem(w)) not in known]
    nums = [n for n in grounding.numbers(tail) if n not in grounding.numbers(tp.premise + " " + tp.fact)]
    return out + nums


def question_carries(question: str, tp: TrapPremise, label: str = "", deck_text: str = "") -> bool:
    """
    질문 문장이 전제를 실었는가 — 바꾼 단서가 있고, 자료의 단서(정답)는 없고, 전제를 의심하는 말이 없고,
    전제를 발표자의 말로 얹었고(「…라고 했는데」), 그 뒤에 **딴 질문**을 붙이지 않았다(`_tail_novel`). 표의 순위 전제는 「가장」 까지.
    deck_text 를 주면 꼬리의 새 낱말이 자료의 **다른 대상**(다른 행·다른 개념)이면 하나여도 딴 질문이다
    (loop2 실측: 「…172라고 했는데, 채소 먼저의 60분 혈당 값은 얼마인가요?」 — 전제를 바로잡아도 답이 안 된다).
    """
    if not question or not hits(question, tp.wrong, tp.kind) or hits(question, tp.right, tp.kind):
        return False
    if tp.kind == "extreme" and not _SUPERLATIVE_RE.search(question):
        return False
    if any(m in question and m not in tp.premise for m in _REVEAL_MARKS):
        return False
    if _carry_end(question) < 0:
        return False
    novel = _tail_novel(question, tp, label)
    if len(novel) > TAIL_NOVEL_MAX or any(re.fullmatch(r"[\d.,]+", w) for w in novel):
        return False
    deck = grounding.squash(deck_text)
    if deck and any(len(grounding.stem(w)) >= 2 and grounding.squash(grounding.stem(w)) in deck for w in novel):
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


#: 바로잡는다고 **분명히** 말하는 표지. 「오히려·사실은·달리」 는 전제를 받아들이면서도 쓴다 — 09-30 실측(focus Q2):
#: 「알림이 와서 오히려 작업 흐름을 이어 주는 신호」(전제에 동의)가 「오히려」 하나로 바로잡은 답이 됐다.
_STRONG_DISPUTE_MARKS = tuple(m for m in _DISPUTE_MARKS if m not in ("오히려", "사실은", "달리"))


def _disputes(text: str, tp: TrapPremise, strong: bool = False) -> bool:
    """바로잡는 표지가 있는가 — 전제 문장에도 있는 표지(「…가 아니라」 전제의 「아니」)는 세지 않는다."""
    marks = _STRONG_DISPUTE_MARKS if strong else _DISPUTE_MARKS
    return any(m in text and m not in tp.premise for m in marks)


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
    right = hits(answer, tp.right, tp.kind, tolerant=True)
    wrong = hits(answer, tp.wrong, tp.kind)
    # 틀린 단서를 말한 답은 **분명한** 반박이 있어야 바로잡은 것이다 — 「오히려」 는 동의 문장에도 온다.
    dispute = _disputes(answer, tp, strong=wrong)
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
