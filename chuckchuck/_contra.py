"""
모순 질문 — 「발표에서 “…”라고 했는데, 자료 N장의 수치와 달라요. 어느 쪽이 맞나요?」 — 을 판정(F-09)과 「모르겠어요」 사다리가
같이 읽는 결정적 헬퍼입니다 (09-30 WP-CONTRA · 녹음 대화 감사 REC-04·08·09). LLM 을 부르지 않습니다. `_deck_claims`·`_probe_stance`
와 같은 자리의 유틸이라 F-09 가 import 해도 정책 위반이 아닙니다 (DEV_POLICY §4-1).

왜 따로 두나 (docs/review/2026-09-30_QA_녹음대화감사/report.md):
- REC-04: 발표 쪽 값(틀린 값)을 다시 우긴 답이 75·70 「제대로 설명했어요」 로 통과했고, 첫 반응이 자료 쪽 값을 말해 버렸다. 맞게 바로잡은
  답은 다른 장과의 가짜 어긋남으로 55 를 받고 「자료 2장과 한 번 더 맞춰 볼 부분」 으로 닫혔다(모순은 5장).
- REC-08: 「모르겠어요」 1단이 다른 장의 수(「2배」)와 자료 값(「40%」)을 보기로 세웠다 — 발표 값은 보기에 없었다.
- REC-09: 「자료가 오타고 발표가 맞다, 출처는 …」 에 「답으로는 조금 멀어요」, 근거 없이 되풀이하자 35 → 65.

**규칙은 구조로만** — 두 인용(질문이 든 발표 쪽 문장 · 자료 쪽 줄)에서 코드가 뽑은 값, 이 제품의 구조 낱말(자료·발표·N장·표),
「맞다·틀렸다·고치다」 같은 한국어 서술어. 특정 발표의 낱말은 넣지 않는다 — 부스에는 처음 보는 자료와 녹음이 들어온다.
애매하면 판정 LLM 에 맡긴다(놓치는 쪽이 안전하다 — 여기서 잘못 잡으면 맞게 답한 사람이 진다).

값 읽기는 `_deck_claims.numbers` 를 쓴다 — 그 파서가 로마자 단위(ppm·kg)를 단위로 읽든(09-30 WP-A) 안 읽든 같은 답이 나오게
짰다: 값은 두 인용 **사이의** 짝으로만 고르고(단위가 없으면 둘 다 없어야 짝), 칩 글에는 뒤에 붙은 로마자 단위를 그대로 싣는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ._deck_claims import Num, clauses, directions, numbers
from ._speech import josa_of
from ._spoken import spoken_numbers
from .contracts import PROBE_STANCES, ProbeStance

#: 모순 질문의 출처 이름 (`Question.source` · `QuestionBasis.source`).
CONTRA = "contradiction"

#: 인용을 칩·물음에 실을 때의 상한 — 물음 전체가 말풍선 한 칸(QA_TEXT_MAX)에 들어가게.
SAID_LEAD_MAX = 70
#: 자료 쪽 줄을 글자 그대로 옮겼다고 볼 길이 (띄어쓰기·문장부호 뺀 글자) — F-08 `_contra_leaks` 와 같은 잣대.
DECK_CHUNK = 10


def is_contra(question) -> bool:
    """코드가 확인한 모순에서 나온 질문인가 — 근거 묶음의 출처(없으면 질문의 출처)가 contradiction."""
    basis = getattr(question, "basis", None)
    src = (getattr(basis, "source", "") if basis is not None else "") or getattr(question, "source", "")
    return src == CONTRA


# ---------------------------------------------------------------------------
# 두 쪽 — 자료 쪽 줄 · 발표 쪽 문장 · 코드가 뽑은 어긋난 값 짝
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Sides:
    slide_no: int
    deck_quote: str          # 자료 쪽 줄 (F-08 evidence_quote)
    said_full: str           # 발표 쪽 문장 전체 (F-08 speech_quote — 정합이 어긋난다고 본 바로 그 문장)
    said_clause: str         # 질문이 따옴표로 든 절 (없으면 값이 든 절)
    deck_value: Num | None   # 자료 쪽에만 있는 값 — 모순 질문의 답
    said_value: Num | None   # 발표 쪽에만 있는 값
    deck_label: str = ""     # 칩 글 — 「40%」「1,450ppm」
    said_label: str = ""

    @property
    def numeric(self) -> bool:
        return self.deck_value is not None and self.said_value is not None

    @property
    def where(self) -> str:
        return f"자료 {self.slide_no}장" if self.slide_no else "자료"


_SAID_QUOTE_RE = re.compile(r"발표에서\s*[“\"「]([^”\"」]{2,200})[”\"」]")
_GIST_QUOTE_RE = re.compile(r"“([^”]{2,240})”")
#: 절 머리의 군말·이음말 — 「음」「그리고」 (어느 발표에나 있는 말). F-08 `_FILLER_HEAD_RE` 와 같은 뜻.
_FILLER_HEAD_RE = re.compile(r"^(?:(?:음+|아+|어+|그+|저기|뭐|그리고|그래서|그런데|근데|그러니까|그니까|그러면|그럼|또한|또|아무튼|즉)"
                             r"\s*,?\s+)+")
_CLAUSE_CUT_RE = re.compile(r"(?<=[,.?!])\s+")
#: 수 바로 뒤에 붙은 로마자 단위 — 파서가 단위로 읽지 않아도 칩 글에는 붙인다.
_LATIN_UNIT_RE = re.compile(r"[A-Za-z]{1,6}(?![A-Za-z])")


def _clip_words(text: str, limit: int) -> str:
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rsplit(" ", 1)[0].rstrip(" ,.")
    return (cut or flat[:limit]) + "…"


def _label(text: str, n: Num) -> str:
    raw = text[n.start:n.end].strip()
    tail = _LATIN_UNIT_RE.match(text[n.end:]) if not raw[-1:].isalpha() else None
    return raw + (tail.group(0) if tail else "")


def _value_pair(deck: str, said: str) -> tuple[Num | None, Num | None, str, str]:
    """
    (자료 쪽 값, 발표 쪽 값, 자료 칩 글, 발표 칩 글). 한쪽에만 있는 값끼리 **같은 단위**로 짝짓는다 — 「40%」 ↔ 「육십 퍼센트」.
    단위 없는 값끼리는 한쪽에 하나씩만 남을 때만 짝이다(어느 수끼리인지 모르면 놓친다). 짝이 없으면 (None, None, "", "").
    """
    s_text = spoken_numbers(said)
    d_nums, s_nums = numbers(deck), numbers(s_text)
    d_only = [n for n in d_nums if not any(n.close_value(s) for s in s_nums)]
    s_only = [n for n in s_nums if not any(n.close_value(d) for d in d_nums)]
    for s in s_only:
        if s.unit is None:
            continue
        for d in d_only:
            if d.unit == s.unit:
                return d, s, _label(deck, d), _label(s_text, s)
    bare_d = [n for n in d_only if n.unit is None]
    bare_s = [n for n in s_only if n.unit is None]
    if len(bare_d) == 1 and len(bare_s) == 1:
        d, s = bare_d[0], bare_s[0]
        return d, s, _label(deck, d), _label(s_text, s)
    return None, None, "", ""


def _pick_clause(said: str, numeric: bool) -> str:
    """발표 쪽 문장에서 질문에 실을 절 — 수치 모순이면 수가 든 절, 아니면 첫 절. 군말은 떼고 끝 문장부호도 뗀다."""
    parts = [c.strip() for c in _CLAUSE_CUT_RE.split(" ".join((said or "").split())) if c.strip()]
    if not parts:
        return ""
    pick = next((c for c in parts if numbers(spoken_numbers(c))), None) if numeric else None
    return _FILLER_HEAD_RE.sub("", pick or parts[0]).strip().rstrip(" ,.?!")


def sides_of(question) -> Sides | None:
    """
    모순 질문의 두 쪽. 자료 쪽 줄은 근거 인용(없으면 골자의 첫 인용), 발표 쪽 문장은 발화 인용(없으면 질문·골자의 인용).
    둘 중 하나라도 없으면 None — 그 질문은 예전 판정 그대로다.
    """
    if not is_contra(question):
        return None
    gist_quotes = _GIST_QUOTE_RE.findall(getattr(question, "answer_gist", "") or "")
    deck = " ".join((getattr(question, "evidence_quote", "") or "").split()) or (gist_quotes[0] if gist_quotes else "")
    m = _SAID_QUOTE_RE.search(getattr(question, "question", "") or "")
    quoted = m.group(1).strip() if m else (gist_quotes[1] if len(gist_quotes) >= 2 else "")
    said = " ".join((getattr(question, "speech_quote", "") or "").split()) or quoted
    if not deck or not said:
        return None
    d, s, d_label, s_label = _value_pair(deck, said)
    clause = quoted or _pick_clause(said, numeric=d is not None)
    if d is not None and quoted and not numbers(spoken_numbers(quoted)):
        clause = _pick_clause(said, numeric=True) or quoted
    no = getattr(question, "evidence_slide_no", 0) or 0
    return Sides(no, deck, said, clause.rstrip(" ,.?!"), d, s, d_label, s_label)


def contra_brief(question) -> str:
    """
    판정 프롬프트에 붙일 「이 질문이 묻는 것」 블록 — 모순 질문이 아니면 "". 채점은 코드 가드(F-09 `_contra_call`)가 받치고, 이 블록은
    LLM 의 반응·되물음이 자료 쪽(= 답)을 먼저 말하지 않게 한다 (그래도 새면 코드가 걸러 낸다 — `leaks`).
    """
    sides = sides_of(question)
    if sides is None:
        return ""
    where = sides.where
    return (f"\n\n## 이 질문은 발표에서 한 말과 {where}{josa_of(where, '이', '가')} 다른 곳을 묻는다 (채점 기준 — 발표자에게는 보이지 않는다)\n"
            f"- 발표 쪽(발표에서 한 값·방향)을 다시 고른 답은 까닭을 달아도 통과가 아니다. {where} 쪽을 말하고 발표에서 한 말을 그쪽으로"
            " 바로잡은 답이 정답이다.\n"
            f"- 발표자가 아직 {where} 쪽을 말하지 않았으면 react·followup·missing_points 에 {where}의 값·문장을 쓰지 마라 — 그게 답이다.")


def said_lead(sides: Sides) -> str:
    """「발표에서는 “…”라고 했어요.」 — 1·2단이 보여 주는 것은 발표 쪽 인용과 장 번호뿐이다 (자료 쪽 줄은 3단 해설에서)."""
    clause = _clip_words(sides.said_clause, SAID_LEAD_MAX)
    return f"발표에서는 “{clause}”{josa_of(clause, '이라고', '라고')} 했어요." if clause else ""


# ---------------------------------------------------------------------------
# 입장 둘 중 하나 — contracts.PROBE_STANCES 의 contradiction 줄 + 질문마다 값 칩 (`_probe_stance.STANCE_RESOLVERS`)
# ---------------------------------------------------------------------------

def contra_stance(question) -> ProbeStance | None:
    """
    모순 질문의 입장 둘 — 두 값을 코드가 알면 (자료 값, 발표 값) 칩(글자 순 — 자리로 정답을 못 맞히게), 모르면(방향·부정 모순)
    표의 줄(「자료 쪽」「발표 쪽」). 물음은 장 번호를 부르고 자료 쪽 값·문장은 말하지 않는다 — 1단에서 답을 흘리지 않는다 (REC-08).
    """
    sides = sides_of(question)
    row = PROBE_STANCES.get(CONTRA)
    if sides is None or row is None:
        return None
    if sides.numeric and sides.deck_label and sides.said_label and sides.deck_label != sides.said_label:
        a, b = sorted([sides.deck_label, sides.said_label])
        return ProbeStance(ask=f"{sides.where}에 적힌 값은 어느 쪽인가요?", choices=(a, b), correct=sides.deck_label)
    return ProbeStance(ask=f"{sides.where}{josa_of(sides.where, '과', '와')} 견주면 {row.ask}", choices=row.choices,
                       correct=row.correct)


def contra_prompt(question, stance: ProbeStance) -> str:
    """「모르겠어요」 1단 물음 — 발표 쪽 인용 + 입장 물음. 자료 쪽 줄은 싣지 않는다."""
    sides = sides_of(question)
    lead = said_lead(sides) if sides is not None else ""
    return f"{lead} {stance.ask}".strip()


#: 발판 빈칸 뒤에 남은 힘줌 조사 — 「60퍼센트**나** 낮아진」 의 「나」. 빈칸을 자료 값으로 채우면 어색하다.
_EMPH_AFTER_RE = re.compile(r"^(?:이나|나|씩이나)(?=\s|$)")


def contra_scaffold(question) -> tuple[str, str, list[str]]:
    """
    「모르겠어요」 2단 발판 — (빈칸 글, 정답, 보기). **발표 쪽 인용**에서 어긋난 값을 가린 문장(「자료 5장에 맞추면 발표에서 한 말은
    “평균 농도가 ___ 낮아진 거예요”가 돼요.」)이라 자료 쪽 줄을 보이지 않는다 (REC-08 — 예전엔 자료 줄 빈칸·인용 상자가 떴다).
    값을 모르면(방향 모순) 입장 칩이 들어가는 틀. 모순 질문이 아니면 ("", "", []).
    """
    sides = sides_of(question)
    st = contra_stance(question)
    if sides is None or st is None:
        return "", "", []
    if sides.numeric:
        conv = spoken_numbers(sides.said_clause)
        hit = next((n for n in numbers(conv) if n.close_value(sides.said_value)), None)
        if hit is not None:
            rest = conv[hit.end:]
            unit = _LATIN_UNIT_RE.match(rest)
            rest = rest[unit.end():] if unit and not conv[hit.start:hit.end][-1:].isalpha() else rest
            masked = _clip_words(f"{conv[:hit.start]}___{_EMPH_AFTER_RE.sub('', rest)}", SAID_LEAD_MAX + 10)
            return (f"{sides.where}에 맞추면 발표에서 한 말은 “{masked}”{josa_of(masked, '이', '가')} 돼요.", sides.deck_label,
                    list(st.choices))
    return f"{sides.where}{josa_of(sides.where, '과', '와')} 견주면 맞는 쪽은 ___", st.correct, list(st.choices)


# ---------------------------------------------------------------------------
# 답이 어느 쪽을 골랐나 — 구조 낱말(자료·발표·N장·표) + 서술어(맞다·틀렸다·고치다) + 두 값
# ---------------------------------------------------------------------------

_DECK_WORD = r"자료|슬라이드|(?<![\d.,])\d{1,3}\s*장(?=[은는이가을를의에도로\s,.]|$)|(?<![가-힣])표(?=[에의는가를도로]|\s|$)"
_TALK_WORD = r"발표|제\s*말(?![가-힣])|제가\s*(?:한|말한)\s*말"
_TOKEN_RE = re.compile(rf"(?P<deck>{_DECK_WORD})|(?P<talk>{_TALK_WORD})")
#: 맞다 쪽 — 「맞아요·맞다고·맞는·맞으니까·정확해요·정답」. 「맞춰·맞게·맞도록」 은 「…에 맞춘다」 라서 아니다.
_RIGHT_RE = re.compile(r"(?<!안\s)(?<!안)맞(?:아|습|다|는|네|죠|고|을|았|으)(?![^.,!?]{0,5}(?:않|아니))|정확하|정확해|옳|정답")
#: 틀렸다 쪽 — 「틀렸어요·잘못·오타·실수·착각·거꾸로·A가 아니라」 · 부정한 맞다(「맞지 않아요·안 맞아요」).
_WRONG_RE = re.compile(r"틀[렸린려리]|잘못|오타|오기(?=[가를예였])|실수|착각|오류|거꾸로|반대로|헷갈|"
                       r"아니(?:라|고|에요|예요|야|었|였|다|죠)|아닌|아닙|맞지\s*않|맞는\s*(?:게|것이|건)\s*아니|안\s*맞")
#: 고친다 쪽 — 무엇을 고칠지(「자료 5장을 고칠게요」)·무엇으로 고칠지(「40%로 바로잡을게요」).
_FIX_RE = re.compile(r"고칠|고쳐|고치|바로잡|정정|수정(?:할|해|하)")
#: 「X 에 맞춰·맞게」 — X 쪽을 기준으로 삼는다 (「발표를 자료에 맞춰 고칠게요」).
_ALIGN_RE = re.compile(rf"(?P<x>{_DECK_WORD}|{_TALK_WORD})(?:\s*\d{{1,3}}\s*장)?(?:의\s*[가-힣]+)?(?:에|대로)\s*맞(?:춰|추|게|도록)")
#: 값 바로 뒤의 풀이말 — 「40%예요」「40%입니다」 는 그 값을 맞다고 하는 말이다.
_COPULA_AFTER_RE = re.compile(r"^\s*(?:이에요|예요|입니다|이다|이었어요|였어요|이었습니다|였습니다|이죠|죠|이래요|래요|거든요|이거든요)")
#: 값 바로 뒤 「로·으로」 — 고치는 서술어와 같이 오면 그 값으로 바꾼다는 말이다.
_TO_AFTER_RE = re.compile(r"^\s*(?:으로|로)\s")
#: 남의 말을 옮긴 값 — 「60%라고 했는데」「40%로 나와 있어요」. 맞다·틀렸다가 없으면 어느 쪽도 고른 말이 아니다.
_REPORTED_AFTER_RE = re.compile(r"^\s*(?:이라고|라고|이라는|라는|다고|로\s*(?:나와|적혀|쓰여|되어|돼))")
#: 목적어 + 잘못 봤다 — 「자료를 잘못 봤어요」 는 자료가 틀렸다는 말이 아니라 내가 잘못 읽었다는 말이다(그쪽이 맞다).
_MISREAD_RE = re.compile(r"^\s*(?:을|를)\s*(?:잘못|거꾸로|반대로|헷갈려|헷갈리게)\s*(?:봤|읽었|알았|이해|해석|기억)")
#: 주어 없이 제 실수를 말하는 꼴 — 「제가 잘못 말했어요」「거꾸로 말했어요」. 발표에서 한 말이 틀렸다는 뜻이다.
_OWN_SLIP_RE = re.compile(r"(?:잘못|거꾸로|반대로|헷갈려서|착각해서|실수로)\s*(?:말했|말한|말씀|읽었|봤|알았|기억)")
#: 「맞는 건 X」「틀린 건 X」 — 서술어가 앞에 오는 꼴.
_PRED_FIRST_RE = re.compile(r"^\s*(?:건|것은|거는|쪽은|쪽이)\s")
#: 쪽 이름만 댄 짧은 답 — 「자료 쪽이요」「발표요」. 「어느 쪽이 맞나요?」 에 대한 답이다.
_BARE_SIDE_RE = re.compile(r"^\s*(?P<x>자료|슬라이드|발표)(?:\s*\d{1,3}\s*장)?(?:\s*쪽)?(?:이에요|예요|이요|요|입니다|이죠|죠)?\s*[.!]?\s*$")
#: 까닭 — 출처·원본·측정을 대거나 자료가 틀렸다고 한다 (반박, REC-09).
_SOURCE_RE = re.compile(r"출처|원본|원자료|원래\s*자료|기록|엑셀|파일|데이터|측정|조사|논문|보고서|통계|설문|실험|직접")
_OWN_FIX_RE = re.compile(r"정정|바로잡")


@dataclass(frozen=True)
class Take:
    """답이 고른 쪽 — side: "deck"(자료 쪽) · "said"(발표 쪽) · ""(모름). dispute: 발표 쪽을 까닭(출처·자료 오류)과 함께 고름.
    owned: 자료 쪽을 고르며 발표에서 한 말이 틀렸다고(고치겠다고) 인정함. deck_named·said_named: 그 값을 말함(수치 모순)."""
    side: str = ""
    dispute: bool = False
    owned: bool = False
    deck_named: bool = False
    said_named: bool = False


def _value_side(n: Num, sides: Sides) -> str:
    if sides.deck_value is not None and n.close_value(sides.deck_value):
        return "deck"
    if sides.said_value is not None and n.close_value(sides.said_value):
        return "said"
    return ""


def _clause_votes(clause: str, sides: Sides) -> list[tuple[int, str, str]]:
    """한 절의 표 — (자리, 쪽, 까닭). 까닭: right · wrong · fix · align · copula · misread · slip."""
    votes: list[tuple[int, str, str]] = []
    for m in _ALIGN_RE.finditer(clause):
        votes.append((m.start(), "deck" if m.group("x") and re.match(_DECK_WORD, m.group("x")) else "said", "align"))
    text = _ALIGN_RE.sub(lambda m: " " * len(m.group(0)), clause)
    tokens: list[tuple[int, int, str, str]] = []       # (시작, 끝, 종류, 쪽)
    for m in _TOKEN_RE.finditer(text):
        tokens.append((m.start(), m.end(), "word", "deck" if m.group("deck") else "said"))
    for n in numbers(text):
        side = _value_side(n, sides)
        if side:
            unit = _LATIN_UNIT_RE.match(text[n.end:])
            tokens.append((n.start, n.end + (unit.end() if unit else 0), "value", side))
    tokens.sort()
    other = {"deck": "said", "said": "deck"}

    def before(pos: int):
        prev = [t for t in tokens if t[1] <= pos]
        return prev[-1] if prev else None

    def after(pos: int):
        nxt = [t for t in tokens if t[0] >= pos]
        return nxt[0] if nxt else None

    for m in _RIGHT_RE.finditer(text):
        tok = before(m.start())
        if tok is None and _PRED_FIRST_RE.match(text[m.end():m.end() + 8] or ""):
            tok = after(m.end())
        if tok is not None:
            votes.append((m.start(), tok[3], "right"))
    for m in _WRONG_RE.finditer(text):
        tok = before(m.start())
        if tok is None and _PRED_FIRST_RE.match(text[m.end():m.end() + 8] or ""):
            tok = after(m.end())
        if tok is not None:
            if tok[2] == "word" and _MISREAD_RE.match(text[tok[1]:]):
                votes.append((m.start(), tok[3], "misread"))      # 「자료를 잘못 봤어요」 — 그쪽이 맞다
            else:
                votes.append((m.start(), other[tok[3]], "wrong"))
        elif _OWN_SLIP_RE.match(text[m.start():]):
            votes.append((m.start(), "deck", "slip"))             # 「제가 잘못 말했어요」 — 발표에서 한 말이 틀렸다
    for m in _FIX_RE.finditer(text):
        tok = before(m.start())
        if tok is None:
            continue
        if tok[2] == "value" and _TO_AFTER_RE.match(text[tok[1]:] + " "):
            votes.append((m.start(), tok[3], "fix"))              # 「40%로 고칠게요」 — 그 값으로 바꾼다
        else:
            votes.append((m.start(), other[tok[3]], "fix"))       # 「자료 5장을 고칠게요」 — 그쪽이 틀렸다
    for t in tokens:
        if t[2] == "value" and _COPULA_AFTER_RE.match(text[t[1]:]):
            votes.append((t[0], t[3], "copula"))
    return votes


def take_of(text: str, sides: Sides | None) -> Take:
    """답(또는 누적 답)이 어느 쪽을 골랐나. 절마다 서술어의 주어(바로 앞의 구조 낱말·값)로 표를 모으고, 두 쪽 표가 다 있으면 **나중 표**가
    이긴다(「처음엔 발표가 맞다고 생각했는데, 다시 보니 자료가 맞아요」). 표가 없으면 옮긴 말이 아닌 값 언급으로 가른다."""
    if sides is None or not (text or "").strip():
        return Take()
    conv = spoken_numbers(" ".join(text.split()))
    votes: list[tuple[int, int, str, str]] = []
    for ci, clause in enumerate(clauses(conv) or [conv]):
        votes += [(ci, pos, side, why) for pos, side, why in _clause_votes(clause, sides)]
    named = {_value_side(n, sides) for n in numbers(conv)} - {""}
    deck_votes = [v for v in votes if v[2] == "deck"]
    said_votes = [v for v in votes if v[2] == "said"]
    if deck_votes and said_votes:
        side = max(votes, key=lambda v: (v[0], v[1]))[2]
    elif deck_votes or said_votes:
        side = "deck" if deck_votes else "said"
    else:
        bare = set()
        for n in numbers(conv):
            s = _value_side(n, sides)
            if s and not _REPORTED_AFTER_RE.match(conv[n.end:]):
                bare.add(s)
        only = _BARE_SIDE_RE.match(conv)
        if only:
            bare.add("said" if only.group("x") == "발표" else "deck")
        side = next(iter(bare)) if len(bare) == 1 else ""
    dispute = side == "said" and (any(v[3] in ("wrong", "fix") for v in said_votes) or bool(_SOURCE_RE.search(conv)))
    owned = side == "deck" and (any(v[3] in ("wrong", "fix", "slip", "misread", "align") for v in deck_votes)
                                or bool(_OWN_FIX_RE.search(conv)))
    return Take(side, dispute, owned, "deck" in named, "said" in named)


# ---------------------------------------------------------------------------
# 누설 — 반응·되물음·결손이 자료 쪽(= 답)을 발표자보다 먼저 말하는가 (REC-04 · REC-08)
# ---------------------------------------------------------------------------

_SQUASH_RE = re.compile(r"[^가-힣A-Za-z0-9%]")


def _squash(text: str) -> str:
    return _SQUASH_RE.sub("", (text or "").lower())


def revealed(said: str, sides: Sides | None) -> bool:
    """발표자가 이미 자료 쪽을 말했는가 — 수치 모순은 자료 값을, 아니면 자료 쪽을 골랐다(`take_of`). 말했으면 반응이 그걸 되받아도 누설이 아니다."""
    if sides is None:
        return True
    t = take_of(said, sides)
    return t.deck_named if sides.numeric else t.side == "deck"


def leaks(text: str, sides: Sides | None, said: str = "") -> bool:
    """
    글이 모순의 **자료 쪽**(= 답)을 말하는가 — 자료 쪽 값이 글에 있거나(말로 적은 수도 바꿔 본다), 자료 쪽 줄 가운데 발표 쪽 문장에 없는
    조각(DECK_CHUNK 글자)을 글자 그대로 옮겼다. 발표자가 이미 말한 값·조각은 누설이 아니다 (F-08 `_contra_leaks` 와 같은 잣대에 누적 답을 더함).
    """
    if sides is None or not (text or "").strip():
        return False
    told = numbers(spoken_numbers(text))
    known = numbers(spoken_numbers(said or ""))
    if sides.deck_value is not None and any(n.close_value(sides.deck_value) for n in told) \
            and not any(k.close_value(sides.deck_value) for k in known):
        return True
    deck, spoken, body, prior = _squash(sides.deck_quote), _squash(sides.said_full), _squash(text), _squash(said)
    return any(deck[i:i + DECK_CHUNK] in body and deck[i:i + DECK_CHUNK] not in spoken and deck[i:i + DECK_CHUNK] not in prior
               for i in range(0, max(0, len(deck) - DECK_CHUNK + 1)))


# ---------------------------------------------------------------------------
# 자료 안의 숫자로 확인 — 표의 전·후 두 값이 자료 쪽 값·발표 쪽 값 가운데 어느 쪽으로 계산되나 (REC-09)
# ---------------------------------------------------------------------------

def _computes(a: Num, b: Num, target: Num, base_hint: str) -> bool:
    """두 값(a→b)으로 target 이 나오나 — %는 변화율(줄었으면 큰 값, 늘었으면 작은 값이 기준 · 모르면 둘 다), %p 는 차, 배는 비."""
    x, y, t = abs(a.value), abs(b.value), abs(target.value)
    tol = 0.5 * 10 ** -target.decimals + 1e-9
    if x == y or t == 0:
        return False
    if target.unit == "pct":
        bases = {"down": (max(x, y),), "up": (min(x, y),)}.get(base_hint, (x, y))
        return any(base and abs(abs(x - y) / base * 100 - t) <= tol for base in bases)
    if target.unit == "pp":
        return abs(abs(x - y) - t) <= tol
    if target.unit == "배":
        lo, hi = sorted((x, y))
        return lo > 0 and abs(hi / lo - t) <= tol
    return False


def _pairs(deck, slide_no: int) -> tuple[list[tuple[Num, Num]], bool]:
    """그 장의 전·후 짝 — 같은 표의 같은 열(행끼리), 글줄 안의 이웃한 같은 단위 값. (짝들, 표에서 나왔나)."""
    lines = [ln for ln in getattr(deck, "lines", ()) if ln.slide_no == slide_no]
    out: list[tuple[Num, Num]] = []
    from_table = False
    run: list[tuple[Num, ...]] = []
    for ln in [*lines, None]:
        if ln is not None and ln.is_row:
            if ln.nums:
                run.append(ln.nums)
            continue
        for i in range(len(run)):
            for j in range(i + 1, len(run)):
                for a, b in zip(run[i], run[j]):
                    if a.unit == b.unit:
                        out.append((a, b))
                        from_table = True
        run = []
        if ln is not None:
            ns = list(ln.nums)
            out += [(a, b) for a, b in zip(ns, ns[1:]) if a.unit == b.unit]
    return out, from_table


def table_support(sides: Sides | None, deck) -> tuple[str, bool]:
    """
    자료 쪽 장 **안의 숫자**가 어느 값을 받치나 — ("deck" | "said" | "", 표에서 나왔나). 반박(「자료가 오타고 발표가 맞다」)에 코치가 확인할 수
    있는 것은 발표자의 원본이 아니라 자료 스스로의 숫자다: 표의 전·후 값(1,450 → 870)이 자료 쪽 값(40%)으로 계산되면 자료는 제 안에서
    맞다. 발표 쪽 값으로 계산되면 그 줄이 표와 어긋난 것이다. 둘 다·둘 다 아니면 "" — 모르면 모른다고 한다.
    """
    if sides is None or not sides.numeric or deck is None:
        return "", False
    dirs = directions(sides.deck_quote)
    hint = next(iter(dirs)) if len(dirs) == 1 else ""
    pairs, from_table = _pairs(deck, sides.slide_no)
    pairs = [(a, b) for a, b in pairs
             if not any(x.close_value(v) for x in (a, b) for v in (sides.deck_value, sides.said_value))]
    to_deck = any(_computes(a, b, sides.deck_value, hint) for a, b in pairs)
    to_said = any(_computes(a, b, sides.said_value, hint) for a, b in pairs)
    if to_deck == to_said:
        return "", False
    return ("deck" if to_deck else "said"), from_table
