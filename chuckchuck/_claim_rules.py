"""
주장(F-26)과 탐침(_probes)이 함께 쓰는 **자료 말투 규칙** — 인용 한 줄이 주장을 받치는지 코드가 가른다.

`_match.py`·`_evidence.py` 와 같은 자리다 — 기능 모듈이 아니라 유틸이라 F-26 과 `_probes` 가 같이
import 해도 정책 위반이 아니다 (DEV_POLICY §4-1). LLM 을 부르지 않고 문자열만 본다.

왜 따로 두나 (2026-09-29 일반화 벤치, held-out 8덱):
- 인용이 원문에 **있는지**만 보고 인용이 주장을 **받치는지**는 안 봐서, 단정 표지 없는 줄이 absolute 로
  (held-out absolute 의 75%), 물음 줄 「몇 명이 구독하는가」 가 absolute 로, 표지 제목이 compose 로 들어갔다.
- 규칙은 전부 **구조**다 — 특정 발표의 낱말이 아니라 한국어 말투(단정 부사·부정·물음 어미·식 기호·
  목록 제목·「X보다」)와 개념 이름 토큰의 겹침만 본다. 새 덱이 들어와도 같은 잣대가 선다.

09-30 레드팀(G-A1·A2·A3·A14·A15·A16·A27) 뒤로 **형태**를 더 본다 — 「덜·적다·않다」 비교의 방향, 절 안의 부정,
반의어 수식어(증가↔감소), 한 글자 단위의 개수 말(「세대」「열대」), 「요」 로 끝나는 명사(「수요」「필요」),
「연구 방법」 같은 비해결 제목, 글자 「x」·목록 가운뎃점 「·」.
"""

from __future__ import annotations

import re

from ._match import norm_tokens

# ---------------------------------------------------------------------------
# 개념 이름 토큰 — 조사가 붙어도 같은 낱말
# ---------------------------------------------------------------------------

#: 이보다 짧은 토큰은 이름 대조에 쓰지 않는다 — 「수」「양」「질」 한 글자는 어디에나 있다.
TOKEN_MIN = 2
#: 개념 이름이 한 줄에 「나왔다」고 볼 변별 토큰 비율. 「사전 예방」 ↔ 「예방 체계」 는 1/2 로 통과한다.
MENTION_MIN = 0.5

_HANGUL_RE = re.compile(r"^[가-힣]+$")


def content_tokens(text: str) -> list[str]:
    """대조에 쓰는 토큰 — 두 글자 이상만 (한 글자 토큰·숫자 하나는 우연히 다 걸린다)."""
    return [t for t in norm_tokens(text) if len(t) >= TOKEN_MIN]


def tok_match(text_tok: str, label_tok: str) -> bool:
    """
    본문 토큰 하나가 이름 토큰 하나와 같은 낱말인가.

    - 한글은 조사·어미가 붙으므로 포함이면 같다 (「배송비를」 ∋ 「배송비」).
    - 이름 쪽 토큰에 붙은 관형격 「의」 는 떼고 본다 (「품질의 향상」 의 「품질의」 ↔ 본문 「품질」).
      그 밖에 본문 쪽이 짧은 경우는 다른 낱말이다 (「구독」 ≠ 「구독자」).
    - 영문·숫자는 통째로 같아야 한다 (「ai」 가 「detail」 안에서 걸리면 오탐이다).
    """
    if text_tok == label_tok:
        return True
    if not (_HANGUL_RE.match(text_tok) and _HANGUL_RE.match(label_tok)):
        return False
    if label_tok in text_tok:
        return True
    return len(label_tok) > TOKEN_MIN and label_tok.endswith("의") and label_tok[:-1] in text_tok


def distinct_tokens(label: str, exclude: str | list[str] = "") -> list[str]:
    """
    이름의 **변별 토큰** — 맞은편 이름(exclude)에도 있는 토큰은 뺀다 (「수면 시간」 ↔ 「수면의 질」 의 「수면」).
    다 빠지면 원래 토큰을 쓴다 (한쪽 이름이 다른 쪽을 품는 경우).
    """
    toks = content_tokens(label)
    ex_list = [exclude] if isinstance(exclude, str) else list(exclude)
    ex = [t for e in ex_list for t in content_tokens(e)]
    kept = [t for t in toks if not any(tok_match(x, t) or tok_match(t, x) for x in ex)]
    return kept or toks


def mention_score(label: str, text: str, exclude: str | list[str] = "") -> float:
    """이름의 변별 토큰 가운데 본문에 나온 비율 (0.0~1.0). 토큰이 없으면 0."""
    toks = distinct_tokens(label, exclude)
    if not toks:
        return 0.0
    body = norm_tokens(text)
    return sum(1 for t in toks if any(tok_match(b, t) for b in body)) / len(toks)


def mentioned(label: str, text: str, exclude: str | list[str] = "", min_score: float = MENTION_MIN) -> bool:
    return mention_score(label, text, exclude) >= min_score


def first_position(label: str, text: str) -> int:
    """본문에서 이름 토큰이 처음 나오는 토큰 위치 (못 찾으면 큰 수) — 「먼저 나온 쪽이 원인」 같은 순서 판단에 쓴다."""
    toks = content_tokens(label)
    body = norm_tokens(text)
    for i, b in enumerate(body):
        if any(tok_match(b, t) for t in toks):
            return i
    return 10_000


# ---------------------------------------------------------------------------
# 양·방향 수식어 — 같은 변수, 다른 극성 (09-30 G-A3)
# ---------------------------------------------------------------------------
# 「충분한 시간」·「시간 부족」·「시간」 은 한 변수(시간)의 세 이름이다. 예전 same_concept 은 수식어를 떼고 토큰 집합만 봐서
# 「매출 증가」 = 「매출 감소」 가 됐다 — 반대 주장이 한 개념으로 합쳐지고, 「시간 확보」 가 「시간 부족」 을 푼다는 주장은
# 「A 가 A 를 푼다」 로 버려졌다. 이제 변수(concept_key)와 극성(polarity)을 따로 든다:
#   same_variable  변수만 같다 (극성 무시)                  — 짝 찾기의 가장 넓은 잣대
#   same_concept   같은 개념 — 반의 수식어(증가↔감소)면 다르다. 충족 짝(충분↔부족)은 한 논증 자리라 같다
#   same_sense     같은 뜻 — 극성이 같거나 한쪽이 중립     — 「A 가 A 를 푼다」 거르기
#   antonyms       같은 변수의 반대 극성 (충족 짝은 빼고)

#: 커지는 쪽 수식어.
_UP_WORDS = frozenset({"증가", "향상", "개선", "상승", "강화", "확대", "증대", "호전", "증진", "높은", "많은", "큰", "긴", "넓은",
                       "빠른", "과다", "과잉", "충분", "충분한", "충분히", "확보", "늘어난", "늘어남", "회복"})
#: 작아지는 쪽 수식어.
_DOWN_WORDS = frozenset({"감소", "저하", "악화", "하락", "약화", "축소", "감퇴", "둔화", "절감", "완화", "낮은", "적은", "작은",
                         "짧은", "좁은", "느린", "부족", "부족한", "결핍", "부재", "미흡", "줄어든", "줄어듦"})
#: 극성 없이 붙는 수식어 — 변수를 가를 때만 뗀다.
_NEUTRAL_MODS = frozenset({"문제", "관리", "제한", "정도", "수준", "유지"})
#: 충족 짝 — 요건(충분한 X)과 그 결핍(X 부족)은 같은 논증 자리다 (문제 목록의 「X 부족」 이 식의 요소 「충분한 X」 의 실패).
_SUFFICIENCY_WORDS = frozenset({"충분", "충분한", "충분히", "확보", "부족", "부족한", "결핍", "부재", "미흡"})
_MOD_WORDS = _UP_WORDS | _DOWN_WORDS | _NEUTRAL_MODS
#: 붙여 쓴 합성어의 끝 수식어를 뗄 때 남아야 할 줄기 길이 (「재고부족」 → 「재고」, 「개선안」 은 끝이 아니라 안 뗀다).
_STEM_MIN = 2


def _split_mod(tok: str) -> tuple[str, str]:
    """토큰 → (변수 줄기, 수식어). 수식어 토큰이면 줄기가 "", 붙여 쓴 합성어면 끝 수식어를 뗀다."""
    if tok in _MOD_WORDS:
        return "", tok
    for w in _MOD_WORDS:
        if len(w) >= 2 and tok.endswith(w) and len(tok) - len(w) >= _STEM_MIN:
            return tok[: -len(w)], w
    return tok, ""


def _mods(label: str) -> list[str]:
    return [w for w in (_split_mod(t)[1] for t in norm_tokens(label)) if w]


def concept_key(label: str) -> frozenset[str]:
    """개념 이름에서 양·방향 수식어를 뺀 토큰 집합(변수) — 둘이 같으면 같은 변수의 이름이다."""
    toks = [t[:-1] if len(t) > 2 and t.endswith("의") else t for t in content_tokens(label)]
    out = set()
    for t in toks:
        stem, _ = _split_mod(t)
        if len(stem) >= TOKEN_MIN:
            out.add(stem)
    return frozenset(out)


def polarity(label: str) -> int:
    """이름의 극성 — 커지는 쪽 +1, 작아지는 쪽 -1, 없거나 섞이면 0."""
    score = sum(1 if w in _UP_WORDS else -1 if w in _DOWN_WORDS else 0 for w in _mods(label))
    return (score > 0) - (score < 0)


def _sufficiency(label: str) -> bool:
    polar = [w for w in _mods(label) if w in _UP_WORDS or w in _DOWN_WORDS]
    return bool(polar) and all(w in _SUFFICIENCY_WORDS for w in polar)


def same_variable(a: str, b: str) -> bool:
    """두 이름이 같은 변수인가 — 극성은 보지 않는다 (「매출 증가」·「매출 감소」·「매출」)."""
    if not a or not b:
        return False
    if a == b:
        return True
    ka, kb = concept_key(a), concept_key(b)
    return bool(ka) and ka == kb


def antonyms(a: str, b: str) -> bool:
    """같은 변수의 **반대** 극성인가 — 「매출 증가」↔「매출 감소」. 충족 짝(「충분한 X」↔「X 부족」)은 반의어로 보지 않는다."""
    return same_variable(a, b) and polarity(a) * polarity(b) < 0 and not (_sufficiency(a) and _sufficiency(b))


def same_concept(a: str, b: str) -> bool:
    """
    두 이름이 같은 개념인가 — 통째로 같거나, 같은 변수이고 반의어가 아니다.
    「충분한 시간」 = 「시간 부족」(충족 짝) · 「응답 속도 저하」 = 「응답 속도」 · 「매출 증가」 ≠ 「매출 감소」.
    """
    return bool(a) and bool(b) and (a == b or (same_variable(a, b) and not antonyms(a, b)))


def same_sense(a: str, b: str) -> bool:
    """
    같은 **뜻**인가 — 같은 변수에 극성이 같거나 한쪽이 중립이다. 「시간 확보」 는 「시간 부족」 과 같은 변수지만 뜻은
    반대라서, 「시간 확보가 시간 부족을 푼다」 는 「A 가 A 를 푼다」 가 아니다.
    """
    if not same_variable(a, b):
        return False
    pa, pb = polarity(a), polarity(b)
    return pa == pb or pa == 0 or pb == 0


#: 뜻이 가벼운 머리 명사 — 「X 체계」「X 방식」「X 수」 는 X 를 가리킨다 (「예방 체계」 ≈ 「사전 예방」). 머리말을 셀 때 건너뛴다.
_LIGHT_HEADS = frozenset({"체계", "구조", "방식", "방법", "방안", "전략", "과정", "요소", "측면", "부분", "영역", "분야", "현황",
                          "개념", "원리", "구성", "기반", "차원", "수", "양"})
_JOSA_1 = frozenset("의을를은는이가에로와과도만")


def _bare(tok: str) -> str:
    """토큰 끝의 한 글자 조사를 뗀 꼴 — 뗀 꼴이 수식어·가벼운 머리일 때만 쓴다 (「체계의」 → 「체계」, 「만족도」 는 그대로)."""
    if len(tok) > 2 and tok[-1] in _JOSA_1 and (tok[:-1] in _MOD_WORDS or tok[:-1] in _LIGHT_HEADS):
        return tok[:-1]
    return tok


def head_token(label: str) -> str:
    """
    이름의 머리말 — 끝 토큰 (한국어 명사구는 머리가 끝에 온다). 끝의 양·방향 수식어(「저하」「부족」)와 뜻이 가벼운 머리
    (「체계」「방식」「수」)는 건너뛴다 — 「대출 권수 감소」 의 머리는 「권수」, 「예방 체계」 의 머리는 「예방」.
    """
    toks = [_bare(t) for t in norm_tokens(label)]
    for t in reversed(toks):
        stem, _ = _split_mod(t)
        if stem and not stem.isdigit() and stem not in _LIGHT_HEADS:
            return stem
    return toks[-1] if toks else ""


def same_head(a: str, b: str) -> bool:
    """두 이름의 머리말이 같은가 — 「낡은 온라인 예약 시스템」·「온라인 예약 시스템」(시스템), 「혈당 부하」·「혈당」 은 아니다."""
    ha, hb = head_token(a), head_token(b)
    return bool(ha) and bool(hb) and (ha == hb or tok_match(ha, hb) or tok_match(hb, ha))


def head_compatible(phrase: str, label: str) -> bool:
    """
    구절과 이름의 **머리말이 통하는가** — 반쯤 겹치는 이름을 고를 때 쓴다. 머리말을 못 가리면(빈 이름) 막지 않는다.

    09-30 held-out 감사 M-05: 「혈당 부하」 가 노드 「혈당 스파이크」「30분 혈당」 으로 풀렸다 (낱말 「혈당」 하나로 절반).
    한국어 명사구는 머리가 끝에 온다 — 머리 「부하」 가 다르면 다른 개념이다. 「예방 체계」 ↔ 「사전 예방」 은 가벼운 머리
    「체계」 를 건너뛰면 머리가 「예방」 으로 같다.
    """
    if not head_token(phrase) or not head_token(label):
        return True
    return same_head(phrase, label)


# ---------------------------------------------------------------------------
# 줄의 말투 — 단정
# ---------------------------------------------------------------------------

#: 단정 표지. 규칙 추출(rule_absolute)은 STRONG 만, LLM 후보 검사는 ANY 를 받는다.
ABSOLUTE_STRONG = (
    r"반드시|완전히|완벽하게|완벽히|항상|언제나|절대로|절대|결코|전혀|하나도|아무도|아무것도|아무런|"
    r"예외\s*(?:없이|없는|없다|없습니다)|무조건|100\s*%|틀림없이|누구나|영원히"
)
ABSOLUTE_ANY = ABSOLUTE_STRONG + r"|모든|완전한|(?<![가-힣])늘(?=\s)"
_ABS_STRONG_RE = re.compile(ABSOLUTE_STRONG)
_ABS_ANY_RE = re.compile(ABSOLUTE_ANY)
#: 부정과 함께 써야 단정이 되는 표지 — 「절대 … 않는다」「하나도 없었다」 는 부정된 단정이 아니라 단정이다.
_NEG_POLARITY_RE = re.compile(r"^(?:절대|절대로|결코|전혀|하나도|아무도|아무것도|아무런)$")
#: 단정을 뒤집는 말 — 「반드시 …는 아니다」「완전히 …되지는 않는다」「완전한 회복이 어렵다」 는 유보다.
_NEGATION_RE = re.compile(r"아니|아닙|아닌|아님|않|어렵|없지|수는\s*없|수\s*없|못\s|못하|못한|힘들")
#: 절 경계 — 부정·유보는 **같은 절 안**에서만 표지를 뒤집는다 (예전엔 표지 뒤 24자였다 — 「반드시 모든 사람에게 효과가 있는
#: 것은 아닙니다」 는 부정이 24자 밖이라 단정으로 읽혔다, 09-30 G-A2). 뒤 절의 부정은 앞 절의 단정을 뒤집지 않는다.
_CLAUSE_END_RE = re.compile(r"[.!?;。]|지만|는데|으나|면서도|반면|다만")
#: 양화 표지 — 「누구나·모든」 은 가능 양태·경향 말과 같은 절이면 능력·허용을 말하는 유보다 (「누구나 쉽게 쓸 수 있습니다」).
_QUANTIFIERS = frozenset({"누구나", "모든"})
_HEDGE_RE = re.compile(r"수\s*(?:도\s*)?있|수도|대부분|대체로|편이|경향|일반적으로|보통|흔히|가능")
#: 「100%」 가 **값**인 자리 — 「만족도 100%」「참여율이 100%였다」「100% 달성」 은 잰 값이지 단정 부사가 아니다.
_PERCENT_VALUE_RE = re.compile(
    r"(?:\s*$|\s*[,.)\]%·]|(?:이었|였|입니|이다|이며|이고|이라|이에요|예요|의|를|을|가|이|로|으로|에|까지|와|과|은|는|도|만)"
    r"|\s+(?:달성|수준|정도|가까이|기록|이상|이하|미만|초과))")


def _clause_around(line: str, start: int, end: int) -> tuple[str, str]:
    """표지 앞뒤의 같은 절 — (앞 조각, 뒤 조각)."""
    before = _CLAUSE_END_RE.split(line[:start])[-1]
    after = _CLAUSE_END_RE.split(line[end:], maxsplit=1)[0]
    return before, after


def absolute_marker(line: str, strong_only: bool = False) -> str:
    """줄에 **부정·유보되지 않은** 단정 표지가 있으면 그 표지, 없으면 ""."""
    text = line or ""
    rx = _ABS_STRONG_RE if strong_only else _ABS_ANY_RE
    for m in rx.finditer(text):
        word = m.group(0)
        if word.replace(" ", "").startswith("100") and _PERCENT_VALUE_RE.match(text[m.end():]):
            continue                                 # 잰 값 — 「만족도 100%」
        if _NEG_POLARITY_RE.match(word):
            return word
        before, after = _clause_around(text, m.start(), m.end())
        if _NEGATION_RE.search(after):
            continue                                 # 「반드시 … 것은 아니다」 — 유보
        if word in _QUANTIFIERS and _HEDGE_RE.search(before + " " + after):
            continue                                 # 「누구나 … 쓸 수 있다」 — 능력·허용
        return word
    return ""


# ---------------------------------------------------------------------------
# 줄의 말투 — 물음·문장
# ---------------------------------------------------------------------------

_QUESTION_END_RE = re.compile(r"(?:[?？]|(?:는가|은가|인가|던가|을까|일까|할까|될까|볼까|까요|나요|는지|을지|니까)\s*[.]?)\s*$")

#: 가설·예상·물음을 머리에 단 줄 — 「가설: A가 높을수록 B가 는다」 는 검증할 말이지 주장이 아니다.
_POSED_RE = re.compile(r"^\s*(?:가설|예상|예측|추측|질문|탐구\s*질문|연구\s*질문|hypothesis|question)\s*\d*\s*[:：)]", re.I)


def is_question(line: str) -> bool:
    """물음 줄인가 — 「…는가」「…일까?」 나 「가설: …」 는 자료가 던진 물음이지 주장이 아니다."""
    line = (line or "").strip()
    return bool(_QUESTION_END_RE.search(line) or _POSED_RE.match(line))


_SENT_PUNCT_RE = re.compile(r"[.!。]\s*$")
_LAST_WORD_RE = re.compile(r"([가-힣]+)\s*[.!]?\s*$")
#: 「요」 로 끝나도 문장이 아닌 한자어 명사 — 수요·필요·중요·개요·주요 … (09-30 G-A15: 「반찬 구독 수요」 가 문장으로
#: 읽혀 목록이 끊겼다). 해요체 끝맺음(「…해요」「…에요」「…나요」)은 동사·형용사 활용이라 여기 걸리지 않는다.
_YO_NOUN_RE = re.compile(r"(?:수요|필요|중요|개요|주요|소요|강요|동요|민요|긴요|요요|필수요)$")
#: 명사형 어미 「-음」 은 받침 있는 줄기 뒤에만 붙는다 (있음·없음·높음·했음). 받침 없는 음절 뒤의 「음」(소음·마음·처음·다음)은
#: 명사다. 받침 규칙이 못 거르는 흔한 명사는 따로 둔다.
_EUM_NOUN_RE = re.compile(r"(?:죽음|웃음|믿음|걸음|얼음|울음|잡음|발음|고음|저음|화음|무음|볶음|녹음)$")
#: 「함·됨·임」 으로 끝나는 명사 — 책임·모임·보관함 ….
_NOMINAL_NOUN_RE = re.compile(r"(?:책임|모임|보관함|사물함|우편함|수납함|건의함|신고함|투표함)$")


def _batchim(ch: str) -> bool:
    return "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 != 0


def is_sentence(line: str, nominal: bool = True) -> bool:
    """
    문장으로 끝나는 줄인가 (마침표·「다」「요」「죠」, nominal 이면 개조식 「…음·함·됨·임」 도). 아니면 제목·낱말 칸·접힌 줄이다.
    끝 낱말의 **형태**를 본다 — 「수요」「필요」 는 「요」 로 끝나도 명사, 「소음」 은 「음」 으로 끝나도 명사다 (09-30 G-A15).
    """
    s = (line or "").strip()
    if _SENT_PUNCT_RE.search(s):
        return True
    m = _LAST_WORD_RE.search(s)
    if not m:
        return False
    w = m.group(1)
    if w.endswith("다"):
        return True
    if w.endswith(("요", "죠")):
        return not _YO_NOUN_RE.search(w)
    if not nominal:
        return False
    if w.endswith("음"):
        return len(w) >= 2 and not _EUM_NOUN_RE.search(w) and _batchim(w[-2])
    if w.endswith(("함", "됨", "임")):
        return len(w) >= 2 and not _NOMINAL_NOUN_RE.search(w)
    return False


# ---------------------------------------------------------------------------
# 비교 — 어느 쪽이 큰가 (09-30 G-A1)
# ---------------------------------------------------------------------------

#: 비교 표지 — compare 는 이게 있을 때만 (F-26 프롬프트에 적힌 규칙을 코드가 지킨다). 「A만큼 …지 않다」 도 비교다.
COMPARE_RE = re.compile(r"보다|대비|(?<![a-z])vs\.?(?![a-z])|비해|than|더\s|만큼\s*[가-힣]+지\s*(?:는\s*)?(?:않|못)", re.I)

_CMP_ADV = r"(?P<adv>(?:(?:더|덜|훨씬|더욱|조금|약간|좀|한층|한결|다소|월등히)\s*)*)"
#: 제목꼴 「A보다 (더) <관형형> B」 — 서술어는 목록이 아니라 꼴로 (중요한·필요한·앞서는·큰 …), 「…지 않은」 도 받는다.
_CMP_HEAD_RE = re.compile(
    r"^(?P<a>[^,.?!]{1,24}?)보다\s*" + _CMP_ADV +
    r"(?P<pred>[가-힣]{1,8}지\s+(?:않은|못한)|[가-힣]{0,8}(?:한|은|인|운|는|된|난|진|른|큰|린|쁜|던))"
    r"\s+(?P<b>[^,.?!]{1,24}?)[.!]?$")
#: 문장꼴 「B는 (수식어) A보다 (더) <서술어> …」.
_CMP_SENT_RE = re.compile(
    r"(?P<b>[^,.?!]{1,24}?)(?:은|는|이|가)\s+(?:[^,.?!\s]{1,10}\s+)??(?P<a>[^,.?!]{1,24}?)보다\s*" + _CMP_ADV +
    r"(?P<pred>[가-힣]+)(?P<rest>[^.?!]*)")
#: 「A 대비 B가 <서술어>」.
_CMP_VS_RE = re.compile(
    r"(?P<a>[^,.?!]{1,24}?)\s*대비\s+(?P<b>[^,.?!]{1,24}?)(?:이|가|은|는)\s+(?P<pred>[^\s.?!]+)(?P<rest>[^.?!]*)")
#: 「B는 A만큼 <서술어>지 않다」 — A 가 크다. 부정이 없으면(「A만큼 중요하다」) 방향이 없어 비교가 아니다.
_CMP_EQ_RE = re.compile(
    r"(?P<b>[^,.?!]{1,24}?)(?:은|는|이|가)\s+(?:[^,.?!\s]{1,10}\s+)??(?P<a>[^,.?!]{1,24}?)만큼\s*(?P<pred>[가-힣]+)"
    r"(?P<rest>[^.?!]*)")
#: 작은 쪽을 말하는 서술어 줄기. 「적」 은 「효과적인·적극·적합·적절·적용·적정·적색·적어도」 가 아닐 때만.
_LESS_PRED_RE = re.compile(
    r"^(?:작|낮|짧|좁|약하|약한|약해|약했|느리|느린|느려|나쁘|나쁜|나빠|못(?:하|한|해|했|미)|뒤지|뒤진|뒤처|"
    r"떨어지|떨어진|떨어져|떨어졌|적(?!인|극|합|절|용|정|색|자|응|어도)|줄|감소|하락)")
_NEG_TAIL_RE = re.compile(r"지\s*(?:는|도|가)?\s*(?:않|못)|(?:는|은)\s*아니")
_CMP_QUOTE_RE = re.compile(r"[\"'“”‘’「」『』()\[\]]")


def _less(adv: str, pred: str, rest: str) -> bool:
    """작은 쪽 비교인가 — 「덜」, 작은 쪽 서술어, 서술어 부정 중 홀수 개 (「작지 않다」 는 두 번 뒤집혀 큰 쪽이다)."""
    flags = ["덜" in (adv or "").split(), bool(_LESS_PRED_RE.match(pred or "")), bool(_NEG_TAIL_RE.search((pred or "") + (rest or "")))]
    return sum(flags) % 2 == 1


def compare_sides(line: str) -> list[tuple[str, str]]:
    """
    비교 줄 → 해석 후보 (큰 쪽 구절, 작은 쪽 구절) 목록, 앞의 것부터. 비교가 아니면 [].

    예전 규칙은 「A보다 …한 B」·「B는 A보다 …」 를 **늘 B > A** 로 적었다 — 「B는 A보다 덜 중요하다」「B가 A보다 적다」
    「B는 A만큼 중요하지 않다」 도 B 가 큰 쪽이 됐다 (09-30 G-A1). 이제 「덜」·작은 쪽 서술어(적다·낮다·작다·못하다 …)·
    서술어 부정(「…지 않다」)으로 방향을 뒤집는다. 「A만큼 중요하다」 처럼 방향이 없는 줄은 비교로 보지 않는다.
    """
    plain = _CMP_QUOTE_RE.sub("", line or "").strip()
    out: list[tuple[str, str]] = []

    def add(a: str, b: str, less: bool) -> None:
        a, b = a.strip(), b.strip()
        if a and b:
            out.append((a, b) if less else (b, a))

    m = _CMP_HEAD_RE.match(plain)
    if m:
        add(m.group("a"), m.group("b"), _less(m.group("adv"), m.group("pred"), ""))
    m = _CMP_SENT_RE.search(plain)
    if m:
        add(m.group("a"), m.group("b"), _less(m.group("adv"), m.group("pred"), m.group("rest")))
    m = _CMP_VS_RE.search(plain)
    if m:
        add(m.group("a"), m.group("b"), _less("", m.group("pred"), m.group("rest")))
    m = _CMP_EQ_RE.search(plain)
    if m and _NEG_TAIL_RE.search(m.group("pred") + m.group("rest")):
        add(m.group("a"), m.group("b"), True)          # 「B는 A만큼 …지 않다」 — A 가 크다
    return out


# ---------------------------------------------------------------------------
# 인과·해결·식·목록
# ---------------------------------------------------------------------------

#: 인과 표지 — 원인·결과를 잇는 말(때문에·해서·수록), 바꾸는 동사의 줄기(늘리·넓히·떨어지 …). 「→」 도 인과로 쓴다.
CAUSE_RE = re.compile(
    r"때문|→|->|수록|해서|하여|[가-힣](?:아|어)서\s|(?:으로|로)\s*인해|탓|일으|야기|유발|초래|이어지|이어집|이어져|가져오|가져와|좌우|영향|"
    r"늘었|줄었|높았|낮았|컸|올랐|"
    r"만든|만듭|만들|늘리|늘려|늘렸|늘립|늘어|늘고|줄이|줄여|줄였|줄입|줄어|줄고|높이|높여|높였|높입|높아|"
    r"낮추|낮춰|낮췄|낮춥|낮아|넓히|넓혀|넓혔|좁히|좁혀|좁혔|키우|키워|키웠|키웁|커지|커져|커졌|작아|많아|적어|"
    r"바꾸|바꿔|바꿨|올리|올려|올렸|내리|내려|내렸|늦추|늦춰|앞당|깎|해치|해쳐|빼앗|방해|"
    r"떨어|끊|증가|감소|촉진|억제|확대|축소|향상|저하|강화|약화|악화|막(?:는|아|습|을|았|기|지|힌|혀)"
)
#: 원인 절과 결과 절을 가르는 연결 어미 — 「A가 부족해서 B가 는다」「A할수록 B가 떨어진다」「A 때문에 B」, 그리고 변화끼리
#: 맞물린 「A가 늘면서 B가 줄었다」(늘·줄·오르·…지면서 — 「들으면서 적는다」 같은 동시 동작은 아니다).
CAUSE_SPLIT_RE = re.compile(r"(?:해서|하여서?|[가-힣](?:아|어)서|때문에|(?:으로|로)\s*인해|탓에|수록|(?:늘|줄|오르|내리|[가-힣]지)면서)\s")
#: 식의 연산 기호 — ×·÷·+·* 는 늘, 「x」「·」 는 앞뒤를 띄운 낱자일 때만 연산이다. 「기술·자본」 의 가운뎃점은 나열이고
#: 「Box·Flex」 의 x 는 글자다 (09-30 G-A27: 예전엔 우변 어디든 「x」「·」 가 있으면 식이었다).
_FORMULA_OP = r"(?:[×✕÷+*]|\s[xX·]\s)"
FORMULA_RE = re.compile(rf"^(?P<lhs>[^=]{{1,40}}?)\s*=\s*(?P<rhs>.*{_FORMULA_OP}.*)$")
_FORMULA_SPLIT_RE = re.compile(r"\s*[×✕÷+*]\s*|\s+[xX·]\s+")
#: 문제 목록 제목 — 줄이 문제 명사로 끝난다 (「해결해야 할 세 가지 문제」). 「…문제와 연결됩니다」 는 아니다.
_PROBLEM_HEAD_RE = re.compile(r"(?:문제|문제점|원인|이유|한계|한계점|위험|장벽|걸림돌|어려움|병목|취약점|약점|고충|불편)(?:들)?\s*[.:!]?\s*$")
#: 문제 낱말 — 개념 이름·목록 항목이 문제를 가리키는가 (「연속성 저하」「보증 가입 장벽」).
_PROBLEM_WORD_RE = re.compile(r"문제|원인|저하|부족|위험|한계|장벽|지연|손실|불일치|부담|실패|결핍|과잉|과다|악화|방해|이탈|취소|낭비|오류|누락")
#: 해결 장 제목. 「방법」 은 해결 동작과 함께일 때만(「줄이는 방법」「개선 방법」), 「기능」 은 제품 기능 소개(「핵심 기능」)일
#: 때만 — 「연구 방법」「측정 방법」「인지 기능」 장을 해결 장으로 읽으면 그 장의 인과가 계획으로 버려진다 (09-30 G-A16).
SOLVE_HEAD_RE = re.compile(r"해결|해소|대책|방안|개선|전략|제안|솔루션|처방|실천")
_METHOD_SOLVE_RE = re.compile(
    r"(?:해결|개선|극복|대처|대응|예방|완화|관리|절감)\s*방법|(?:줄이|막|높이|늘리|바꾸|지키|푸|없애|낮추|살리|되살리)는\s*방법"
    r"|방법\s*(?:제안|찾기)")
_FEATURE_HEAD_RE = re.compile(r"(?:핵심|주요|대표|새로운|신규|추가|제공|서비스|앱|제품)\s*기능|기능\s*(?:소개|안내|제안)")
#: 해결 말투 — 문제를 줄이거나 없애는 동사·명사. 「높인다·늘린다」 는 인과에도 쓰여서 넣지 않는다.
SOLVE_RE = re.compile(
    r"해결|해소|개선|완화|방지|예방|대책|방안|차단|극복|보완|덜어|줄이|줄입|줄여|줄였|줄어|줄었|낮추|낮춥|낮춰|낮췄|"
    r"없애|없앱|없앴|없앨|없앤|막(?:는|아|습|을|기|았)|확보|지원|도입|유지|지키|지킵|지켜|풉니|풀어|풀었|푸는|풀기|풀고|풀면|"
    r"줄일|줄인|낮출|낮춘"
)
#: 늘리는 말 — 모자람(「부족한 X」「짧은 X」)을 푸는 것은 줄이는 말이 아니라 늘리는 말이다 (「좌석을 40석 늘립니다」).
_INCREASE_RE = re.compile(r"늘리|늘립|늘려|늘렸|늘릴|늘린|확충|확대|연장|높이|높입|높여|높였|높일|높인|채우|채웁|채워|더합|더해")
#: 「A가 B를 <바꾸는 동사>」 — 조사로 원인(주어)·결과(목적어)가 갈린 한 문장.
CAUSE_SVO_RE = re.compile(r"^(?P<a>[^,.?!]{2,30}?)(?:이|가)\s+(?P<b>[^,.?!]{2,30}?)(?:을|를)\s+(?P<v>\S+)\s*$")
#: 해결 칸의 말 — 무엇을 하는 칸인가 (「…확보」「…줄이기」「…유지」). 현황 칸(「평균 1년 이상」)과 가른다.
SOLVE_ACT_RE = re.compile(
    r"확보|유지|줄이|줄임|낮추|낮춤|없애|막기|막는|방지|예방|해소|개선|도입|지원|설정|정하|관리|늘리|높이|바꾸|"
    r"기르|만들|두기|하기|제공|공개|연동|인증|점검|제한|[가-힣]기\s*$"
)
#: 요소가 **함께** 필요하다는 말 — 이게 있으면 「하나만 챙긴다면」 은 자료가 부정한 선택이다.
BOTH_NEEDED_RE = re.compile(
    r"둘\s*다|모두\s*(?:필요|중요|갖춰|챙겨|있어야)|함께\s*(?:필요|중요|갖춰|챙겨|작용|있어야)|하나만으로는|"
    r"하나만\s*\S+?(?:서는|로는)|만으로는|만으로\s+[^.,]{0,15}?(?:않|어렵|부족|못)|뿐\s*(?:만\s*)?아니라|동시에|"
    r"만큼\s[^.]{0,30}?도\s*중요|어느\s*하나(?:도|만)"
)


def solves(line: str, problem_label: str) -> bool:
    """
    이 줄이 이 문제를 **푸는** 말투인가 — 줄이고·막고·없애고·해소하는 말, 또는 모자람을 뜻하는 문제(극성 -)면 늘리는 말.
    09-30: 「자유열람실 확충 — 열람 좌석을 40석 늘립니다」 가 「부족한 열람 좌석」 을 푸는데 해결 말투 목록에 「늘리」 가 없었다
    (늘리는 말은 인과에도 쓰여서 목록에 못 넣는다 — 문제가 모자람일 때만 푸는 말로 본다).
    """
    return bool(SOLVE_RE.search(line or "")) or (polarity(problem_label) < 0 and bool(_INCREASE_RE.search(line or "")))


def names_variable(label: str, line: str) -> bool:
    """줄이 이 이름의 **변수**(양·방향 수식어를 뗀 낱말)를 다 부르는가 — 낱말이 셋 이상이면 하나는 빠져도 된다."""
    key = list(concept_key(label))
    if not key:
        return False
    body = norm_tokens(line)
    hit = sum(1 for t in key if any(tok_match(b, t) for b in body))
    return hit == len(key) or (len(key) >= 3 and hit >= len(key) - 1)


def is_formula(line: str) -> bool:
    return bool(FORMULA_RE.match((line or "").strip()))


def formula_sides(line: str) -> tuple[str, str] | None:
    m = FORMULA_RE.match((line or "").strip())
    return (m.group("lhs").strip(), m.group("rhs").strip()) if m else None


def formula_terms(rhs: str) -> list[str]:
    """식 우변 → 항 목록 (연산 기호로 나눈다)."""
    return [p.strip(" .") for p in _FORMULA_SPLIT_RE.split(rhs or "") if p.strip(" .")]


def is_solution_head(line: str) -> bool:
    """해결 장의 제목인가 — 해결 낱말이 있고, 문제 목록 제목(「해결해야 할 세 가지 문제」)이 아니다."""
    t = (line or "").strip()
    if not t or is_problem_head(t):
        return False
    return bool(SOLVE_HEAD_RE.search(t) or _METHOD_SOLVE_RE.search(t) or _FEATURE_HEAD_RE.search(t))


#: 한글 수사 → 수.
_NUM_WORDS = {"두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}
#: 개수 말 — 수사 + 단위. 한 글자 단위(개·대·축)는 한글 수사와 **띄어 써야** 개수다 (「세 대」 ↔ 「세대」「열대」), 단위 뒤에
#: 다른 글자가 붙으면 개수 말이 아니다 (「12개월」「5개국」). 조사·서술격은 붙어도 된다 (「세 가지를」「네 가지입니다」). 09-30 G-A14.
_COUNT_WORD_RE = re.compile(
    r"(?<![가-힣0-9])(?:(?P<h>두|세|네|다섯|여섯|일곱|여덟|아홉|열)(?:\s*(?:가지|단계|요소|요인|조건|원칙)|\s+(?:개|대|축))"
    r"|(?P<d>\d{1,2})\s*(?:가지|개|대|단계|요소|요인|조건|축|원칙))"
    r"(?=$|[^가-힣0-9]|(?:의|가|를|을|는|은|로|으로|와|과|만|도|씩|에|에서|이다|입니다|이며|이고|예요|이에요|로는)(?![가-힣]))")


def count_word(line: str) -> int | None:
    """줄의 개수 말(「세 가지」「5대」「네 단계」) → 수. 없으면 None."""
    m = _COUNT_WORD_RE.search(line or "")
    if not m:
        return None
    return _NUM_WORDS[m.group("h")] if m.group("h") else int(m.group("d"))


#: 문장이어도 목록을 여는 줄 — 「문제는 세 가지입니다」「원인은 다음과 같습니다」.
_LIST_SENTENCE_RE = re.compile(r"(?:가지|개|단계|요인|조건|원칙|다음과\s*같)\S*\s*(?:입니다|이다|있습니다|있다|같습니다|같다)\s*[.:]?$")


def is_list_heading(line: str) -> bool:
    """
    목록을 여는 제목 줄인가 — 개수 말이 있거나 문제 명사로 끝나고, 식·물음·긴 줄이 아니다.
    문장은 목록을 소개하는 꼴(「…세 가지입니다」)일 때만 — 「해결책은 세 가지 문제와 연결됩니다」 는 제목이 아니다.
    """
    line = (line or "").strip()
    if not line or len(line) > 40 or is_formula(line) or is_question(line):
        return False
    if is_sentence(line) and not _LIST_SENTENCE_RE.search(line):
        return False
    return count_word(line) is not None or bool(_PROBLEM_HEAD_RE.search(line))


def is_problem_head(line: str) -> bool:
    return bool(_PROBLEM_HEAD_RE.search((line or "").strip()))


def is_problem_label(label: str) -> bool:
    return bool(_PROBLEM_WORD_RE.search(label or ""))


def both_needed(line: str) -> bool:
    return bool(BOTH_NEEDED_RE.search(line or ""))


# ---------------------------------------------------------------------------
# 목록 항목
# ---------------------------------------------------------------------------

_ITEM_MARK_RE = re.compile(r"^(?:[①-⑳]|\(?\d{1,2}[.)]|[-•▪■◦·*>]|[a-zA-Z][.)])\s*")


def table_cells(line: str) -> list[str]:
    """「| a | b |」 → ["a", "b"]. 표 행이 아니면 []."""
    line = (line or "").strip()
    if not line.startswith("|"):
        return []
    return [c.strip() for c in line.strip("|").split("|") if c.strip()]


def item_text(line: str) -> str:
    """목록 한 칸의 글 — 번호·글머리표를 떼고, 표 행이면 첫 칸."""
    cells = table_cells(line)
    text = cells[0] if cells else (line or "").strip()
    return _ITEM_MARK_RE.sub("", text).strip()


def is_item_line(line: str) -> bool:
    """목록 항목처럼 생긴 줄 — 표 행, 번호·글머리표 줄, 또는 문장이 아닌 짧은 줄."""
    line = (line or "").strip()
    if not line:
        return False
    if table_cells(line) or _ITEM_MARK_RE.match(line):
        return True
    return len(line) <= 30 and not is_sentence(line) and not is_question(line)
