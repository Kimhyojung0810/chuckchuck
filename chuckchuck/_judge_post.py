"""
판정(F-09) 문장 후처리 — LLM 이 쓴 결손·react·되물음을 **자료와 발표자의 답**에 맞춘다. LLM 을 부르지 않는다.
`_deck_claims`·`_evidence` 와 같은 자리의 유틸이라 기능 모듈이 import 해도 정책 위반이 아니다 (DEV_POLICY §4-1).

왜 따로 두나 (2026-09-30 #/qa 대화 감사, docs/review/2026-09-29_QA_근거검증/convo/report.md):
- §4 판정 규칙 7 의 결손(missing_points)을 자료와 대조하지 않아 「높은 온도를 낮추는 실천 방안」「측정 방법(예: 실험 절차…)」
  처럼 **자료에 없는 것**을 약 25턴 요구했다.
- §5 답 첫머리에 말한 것을 「아직 언급되지 않았어요」 라고 또 요구했다 — 누적 답과 대조하지 않았다.
- §6 결손 문장이 「…설명이 부족합니다.」 처럼 문장째 와서 되물음 틀(「{point} — 이 부분은 어떻게 봐요?」)이 깨졌다.
- §3 react 가 발표자가 말하지 않은 것을 「…은 맞아요」 라고 칭찬했다.
- §9 3인칭 「발표자는…」, 내부 표기 「S4, S7」, 높임 「짚으셨어요」.

**규칙은 전부 구조로만 짠다** — 문장 부호·어미·조사·숫자·인용 부호, 자료 줄과의 낱말 겹침. 특정 발표의 낱말은 없다.
부스에서는 처음 보는 자료가 들어온다.
"""

from __future__ import annotations

import re

from ._deck_claims import Deck, conflicts, content_stems, numbers, opposes

# ---------------------------------------------------------------------------
# 문장 단위
# ---------------------------------------------------------------------------

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split((text or "").strip()) if s.strip()]


def keep_sentences(text: str, drop) -> str:
    """drop(문장) 이 참인 문장을 뺀 나머지. 다 빠지면 빈 문자열."""
    return " ".join(s for s in sentences(text) if not drop(s))


# ---------------------------------------------------------------------------
# 표기 정리 — 내부 장 표기 · 3인칭 · 문서 표기 지적 (§9 · §7)
# ---------------------------------------------------------------------------

#: 판정 프롬프트의 장 꼬리표 「[S4]」 가 문장에 새어 나온 꼴 — 「S4, S7, S8의」 「(S3)」. 앞뒤가 영문·숫자면 낱말의 일부다.
#: 앞이 영문 낱말 + 띄어쓰기면(「Galaxy S23」) 제품 이름이다 — 건드리지 않는다.
_S_RUN_RE = re.compile(
    r"\[?(?<![A-Za-z0-9])(?<![A-Za-z] )S(\d{1,2})\]?(?:\s*(?:,|·|와|과|및|그리고)\s*\[?S(\d{1,2})\]?)*(?![A-Za-z0-9])"
)
_S_ONE_RE = re.compile(r"S(\d{1,2})")
#: 발표자를 3인칭으로 부르는 말 — 화면은 발표자에게 직접 말한다. 주어를 빼도 한국어는 선다.
_THIRD_PERSON_RULES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"발표자(?:님)?(?:께서|은|는|이|가)\s*"), ""),
    (re.compile(r"발표자(?:님)?에게\s*"), ""),
    (re.compile(r"발표자(?:님)?의\s*"), "방금 "),
    (re.compile(r"발표자(?:님)?[,，]\s*"), ""),
)
#: 자료의 **표기**(철자·오타)를 고치라는 말 — 문서 변환기(OCR)가 틀린 글자를 발표자에게 고치라고 한다 (09-30: 「'손실 희망'으로
#: 표기된 점을 확인해 주세요」). 판정은 내용을 보지 글자를 교정하지 않는다.
_NOTATION_RE = re.compile(r"표기|오타|오기(?:가|를|로)|철자|맞춤법|오탈자|잘못\s*적")


def _slides_phrase(m: re.Match) -> str:
    nums = _S_ONE_RE.findall(m.group(0))
    return f"자료 {', '.join(nums)}장"


def scrub(text: str) -> str:
    """내부 장 표기를 「자료 N장」 으로, 3인칭 발표자를 뺀다. 멱등."""
    out = _S_RUN_RE.sub(_slides_phrase, text or "")
    out = re.sub(r"\(\s*(자료 [\d, ]+장)\s*\)", r"(\1)", out)
    for pat, rep in _THIRD_PERSON_RULES:
        out = pat.sub(rep, out)
    return re.sub(r"\s{2,}", " ", out).strip()


def talks_notation(text: str) -> bool:
    return bool(_NOTATION_RE.search(text or ""))


# ---------------------------------------------------------------------------
# 결손 항목 (missing_points) — §4 자료 지지 · §5 이미 말함 · §6 명사구 · §7 인용 조각
# ---------------------------------------------------------------------------

#: 답을 평하는 말 — 결손의 **내용**이 아니다. 자료 지지·누적 답 대조에서 뺀다(어느 발표에나 쓰는 판정 어휘).
_META_STEMS = (
    "구체", "명확", "정확", "직접", "추가", "제시", "언급", "명시", "인용", "예시", "사례", "방안", "필요", "연결", "고리",
    "논리", "메커니즘", "측면", "관점", "요소", "항목", "포인트", "점을", "점이", "점은", "강조", "보완", "확인", "비교",
    "구성", "전체", "각각", "자체", "관련", "해당", "실제", "정도", "수준",
    # 뜻 없는 서술 줄기 — 「…해야 한다는 점」 의 「한다는」
    "한다", "된다", "하게", "되게", "해야", "돼야", "하기", "되기", "했다", "됐다", "있다", "없다",
)


def _is_meta(stem: str) -> bool:
    return any(stem.startswith(m) for m in _META_STEMS)


def claim_stems(text: str) -> list[str]:
    """결손·칭찬 문장의 **내용** 낱말 (판정 어휘를 뺀 줄기)."""
    return [s for s in dict.fromkeys(content_stems(text)) if not _is_meta(s)]


def _has(stems: list[str], stem: str) -> bool:
    """같은 낱말인가 — 앞머리 포함, 또는 세 글자 이상끼리 앞 두 글자가 같다(활용 꼬리만 다른 「어둡게」·「어둡고」)."""
    for s in stems:
        if s == stem or (len(s) >= 2 and len(stem) >= 2 and (s.startswith(stem) or stem.startswith(s))):
            return True
        if len(s) >= 3 and len(stem) >= 3 and s[:2] == stem[:2] and "가" <= s[0] <= "힣":
            return True
    return False


#: 「(예: 실험 절차, 정량적 지표…)」「(알림 줄이기, 묶어서 확인 등)」 — 결손을 늘어놓는 예시 괄호. 자료에 없는 말을 끌고 온다.
_EXAMPLE_PAREN_RE = re.compile(r"\s*\((?:(?:예|예를 들어|예컨대|e\.g\.)\s*[:：]?[^)]*|[^)]*\s등)\)")
#: 해요체·합쇼체로 끝난 결손 → 「…다는 점」. 흔한 끝만 — 모르는 끝은 그대로 둔다.
#: 09-30 레드팀 J10: 「…시간과는 다릅니다.」 가 「…다릅니다는 점」, 「짚어주셔야 합니다」 가 「…합니다는 점」 으로 칩에 떴다.
_HAEYO_TO_NOUN = (
    ("아니에요", "아니라는 점"), ("아닙니다", "아니라는 점"), ("돼요", "된다는 점"), ("되요", "된다는 점"), ("됩니다", "된다는 점"),
    ("야 해요", "야 한다는 점"), ("야 합니다", "야 한다는 점"), ("해요", "한다는 점"), ("합니다", "한다는 점"),
    ("있어요", "있다는 점"), ("있습니다", "있다는 점"), ("없어요", "없다는 점"), ("없습니다", "없다는 점"),
    ("않아요", "않는다는 점"), ("않습니다", "않는다는 점"), ("져요", "진다는 점"), ("집니다", "진다는 점"),
    ("커요", "크다는 점"), ("큽니다", "크다는 점"), ("같아요", "같다는 점"), ("같습니다", "같다는 점"),
    ("달라요", "다르다는 점"), ("다릅니다", "다르다는 점"), ("많아요", "많다는 점"), ("많습니다", "많다는 점"),
    ("적어요", "적다는 점"), ("적습니다", "적다는 점"), ("높아요", "높다는 점"), ("높습니다", "높다는 점"),
    ("낮아요", "낮다는 점"), ("낮습니다", "낮다는 점"), ("작아요", "작다는 점"), ("작습니다", "작다는 점"),
)
#: 결손 문장 끝의 평가 서술 — 「…설명이 부족합니다」「…이 빠져 있어요」「…을 언급하지 않음」.
_EVAL_TAIL_RE = re.compile(
    r"\s*(?:(?:이|가|은|는|을|를|에\s*대한)\s*)?(?:(?:아직|정확히|구체적으로|명확히|충분히)\s*)*"
    r"(?:(?:언급|제시|설명|확인|명시|보완|추가)(?:하지|되지|을\s*하지)?\s*(?:않았|않음|않은|안\s*했|못\s*했|못함|없)[가-힣]*"
    r"|빠져\s*있[가-힣]*|빠졌[가-힣]*|빠짐|누락[가-힣]*|부족[가-힣]*|미흡[가-힣]*|필요[가-힣]*|없[어습다음][가-힣]*"
    # 「…을 짚어 줘야 해요」「…을 언급해야 합니다」 — 해야 할 말을 가리키는 평가 서술 (09-30 레드팀 J10)
    r"|(?:짚어|언급해|제시해|설명해|말해|밝혀)\s*(?:줘|주어)?야\s*(?:해요|합니다|한다|함)?)\s*[.]?$"
)


def to_noun_phrase(text: str) -> str:
    """
    결손 한 줄을 **명사구**로 — 되물음 틀 「{결손} — 이 부분은 어떻게 봐요?」 에 그대로 끼울 수 있게.
    09-30 실측: 「알림 확인 없이도 … 구체적인 설명이 부족합니다. — 이건 자료에 있었나요, 없었나요?」.
    """
    t = scrub(text)
    t = _EXAMPLE_PAREN_RE.sub("", t).strip(" .·—-")
    t = _EVAL_TAIL_RE.sub("", t).strip(" .·—-")
    # 해요체·합쇼체 끝이 먼저다 — 「다릅니다」 의 「다」 를 해라체로 읽어 「…다릅니다는 점」 을 만들던 것 (J10).
    for tail, noun in _HAEYO_TO_NOUN:
        if t.endswith(tail):
            return (t[: -len(tail)] + noun).strip()
    if re.search(r"(?:이에요|예요|입니다)$", t):
        return re.sub(r"(?:이에요|예요|입니다)$", "", t).strip()
    if re.search(r"(?:(?<!아)니다|어요|아요|여요)$", t):
        return t.strip()                  # 모르는 활용 — 틀리게 바꾸느니 문장 그대로 둔다 (해라체 「아니다」 는 아래에서)
    # 해라체로 끝나면 「…다는 점」 으로 닫는다 (「잠은 하나의 상태가 아니다」 → 「…아니라는 점」)
    if re.search(r"아니다$", t):
        t = t[: -len("아니다")] + "아니라는 점"
    elif re.search(r"[가-힣]다$", t) and not re.search(r"(?:이|하|되)?는다$", t[-3:]):
        t = t + "는 점"
    return t.strip()


#: 결손 한 줄에 든 인용 조각 「'…'」 — 자료의 글자라고 주장하는 말이다.
_QUOTED_RE = re.compile(r"['‘’\"“”「」«»]([^'‘’\"“”「」«»]{2,40})['‘’\"“”「」«»]")


def _nospace(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def quotes_absent(text: str, anchor_text: str) -> bool:
    """결손이 인용한 조각이 이 질문의 근거 장 본문에 없는가 — 자료에 없는 말을 자료의 글자처럼 요구하는 것이다."""
    if not anchor_text:
        return False
    hay = _nospace(anchor_text)
    return any(_nospace(q) not in hay for q in _QUOTED_RE.findall(text or ""))


#: 비교·서열 표지 — 결손이 「A 가 B 보다 크다」「가장」「순위」 를 요구하면 자료에도 그런 줄이 있어야 한다.
_COMPARE_RE = re.compile(r"보다|가장|제일|순위|상대적|더\s*(?:크|큰|많|높|중요|심)")
#: 결손이 자료 줄 하나와 공유해야 하는 내용 낱말 수 (결손 낱말이 이보다 적으면 그 수).
POINT_LINE_MIN = 2
#: 결손 낱말 가운데 자료에 있어야 하는 몫 — `_deck_claims.GIST_GROUNDED_MIN` 과 같은 기준.
POINT_DECK_MIN = 0.6


def point_supported(point: str, deck: Deck | None, question: str = "") -> bool:
    """
    결손이 **자료로 받쳐지는가** (§4). 자료가 없으면 판단 근거가 없어 받쳐진 것으로 본다.

    - 내용 낱말의 60% 이상이 자료에 있다 · 숫자가 자료에 있다(반올림 허용) · 자료와 어긋나는 짝이 없다
    - 자료 **한 줄**이 그 낱말을 둘 이상 같이 말한다 (여기저기 흩어진 낱말을 이어 붙인 요구가 아니다)
    - 비교·서열을 요구하면 자료에도 비교·서열을 말한 줄이 있다 (09-30: 「카페인·음주가 빛·소음보다 더 큰 영향」 — 자료에 순위가 없다)
    """
    if deck is None or deck.empty:
        return True
    stems = claim_stems(point)
    deck_stems = list(deck.stems)
    nums = numbers(point)
    num_ok = [n for n in nums if deck.has_number(n)]
    if len(num_ok) < len(nums):
        return False
    # 숫자도 내용이다 — 「1년차 정확한 금액(48만원)」 은 낱말 「금액」 이 자료에 없어도 숫자가 자료의 것이다.
    tokens = len(stems) + len(nums)
    if tokens:
        in_deck = sum(1 for s in stems if _has(deck_stems, s)) + len(num_ok)
        if in_deck / tokens < POINT_DECK_MIN:
            return False
    if len(stems) >= 2 and max((sum(1 for s in stems if _has(list(r.stems), s)) for r in deck.regions), default=0) < POINT_LINE_MIN:
        return False
    if conflicts(point, deck, question):
        return False
    if _COMPARE_RE.search(point):
        # 비교를 요구하는 결손은 자료에도 **그 낱말들로** 비교한 줄이 있어야 한다 — 낱말 60% 이상을 같이 담은 비교 줄
        need = max(2, -(-len(stems) * 6 // 10))
        if not any(_COMPARE_RE.search(ln.text) and sum(1 for s in stems if _has(list(ln.stems), s)) >= need
                   for ln in deck.lines):
            return False
    return True


#: 결손 낱말 가운데 누적 답에 이만큼 나왔으면 이미 말한 것이다 (§5).
POINT_COVERED_MIN = 0.6
#: 결손이 숫자를 들고 있고 그 숫자를 답이 다 말했으면, 낱말은 이만큼만 겹쳐도 말한 것이다 (「1년차 정확한 금액(48만원)」).
POINT_COVERED_WITH_NUMBERS = 0.3


def point_covered(point: str, said: str) -> bool:
    """결손이 누적 답에 이미 나왔는가 — 내용 낱말 60% 이상, 또는 숫자를 다 말하고 낱말도 30% 이상.
    낱말이 겹쳐도 방향·부정이 반대면(결손 「…를 줄인다는 점」 ↔ 답 「…를 늘린다」) 말한 것이 아니다."""
    if opposes(said, point):
        return False
    stems = claim_stems(point)
    said_stems = content_stems(said)
    ratio = (sum(1 for s in stems if _has(said_stems, s)) / len(stems)) if stems else 0.0
    nums = numbers(point)
    if nums:
        said_nums = numbers(said)
        if all(any(n.close_value(x) for x in said_nums) for n in nums) and (
                len(stems) <= 1 or ratio >= POINT_COVERED_WITH_NUMBERS):
            return True
    return bool(stems) and ratio >= POINT_COVERED_MIN


def clean_points(
    points: list[str], *, deck: Deck | None, said: str, anchor_text: str = "", question: str = "",
) -> tuple[list[str], int]:
    """
    LLM 결손을 명사구로 다듬고, 자료에 없는 것·이미 말한 것·표기 지적·근거 장에 없는 인용은 뺀다.
    (남은 결손, 자료로 안 받쳐져 뺀 개수) — 뒤의 수는 「자료에 없다」 답을 받아 줄지 정할 때 쓴다.
    """
    kept: list[str] = []
    unsupported = 0
    for raw in points:
        p = to_noun_phrase(raw)
        if not p or talks_notation(p) or quotes_absent(p, anchor_text):
            continue
        if not point_supported(p, deck, question):
            unsupported += 1
            continue
        if said and point_covered(p, said):
            continue
        if p not in kept:
            kept.append(p)
    return kept, unsupported


# ---------------------------------------------------------------------------
# react — §3 말하지 않은 것 칭찬 · §5 닫힌 질문의 「다만…」 · §10 길이
# ---------------------------------------------------------------------------

#: 칭찬·인정 문장의 표지.
_PRAISE_SENT_RE = re.compile(
    r"맞아요|맞습니다|맞는\s*말|정확해요|정확합니다|정확히\s*(?:짚|설명|말|파악|언급|이해|정리)|잘\s*(?:짚|설명|말|정리|언급|파악|연결)|"
    r"훌륭|좋은\s*답|옳아요|올바르|잘\s*했"
)
#: 칭찬 문장의 내용 낱말 가운데 누적 답에 이만큼은 있어야 「발표자가 말한 것」 을 칭찬한 것이다.
PRAISE_GROUNDED_MIN = 0.5


def praise_ungrounded(sentence: str, said: str) -> bool:
    """칭찬 문장이 **발표자가 말하지 않은 것**을 칭찬하는가 — 09-30: 「참는 걸로는 안 되니까요」 에 「폰이 가까울수록 인지 자원이
    사용된다는 점은 맞아요」. 인정하는 대상의 내용 낱말이 누적 답에 절반도 없으면 그렇다. 대상이 없는 칭찬(「좋아요」)은 둔다."""
    if not _PRAISE_SENT_RE.search(sentence or ""):
        return False
    stems = claim_stems(_PRAISE_SENT_RE.split(sentence)[0])
    if not stems:
        return False
    said_stems = content_stems(said)
    hit = sum(1 for s in stems if _has(said_stems, s))
    return hit / len(stems) < PRAISE_GROUNDED_MIN


#: 「다만 …가 빠져 있어요」 — 닫힌 질문에 붙으면 「부분 인정 ✓」 옆에서 또 요구하는 말이 된다 (§5).
_MISSING_TALK_RE = re.compile(
    r"다만|하지만|그런데|그러나|빠져|빠졌|누락|아직|부족|더\s*좋|덧붙|추가로|보완|없었|못\s*했|않았|필요해요|필요합니다|해\s*주면|해\s*보면"
)


def trim_missing_talk(text: str) -> str:
    return keep_sentences(text, lambda s: bool(_MISSING_TALK_RE.search(s)))


#: react 길이 상한 — 말풍선 한 번에 읽히는 길이 (09-30: 120자 넘는 react 11건).
REACT_MAX = 120


def cap_length(text: str, limit: int = REACT_MAX) -> str:
    """문장 단위로 상한 안에 담는다. 첫 문장부터 넘치면 마지막 띄어쓰기에서 자르고 「…」."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    out = ""
    for s in sentences(text):
        joined = f"{out} {s}".strip()
        if len(joined) > limit:
            break
        out = joined
    if out:
        return out
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit // 2 else cut).rstrip(" ,") + "…"


# ---------------------------------------------------------------------------
# §4 「자료에 없다」 답 · 자료 밖을 묻는 질문 · §3 짧은 답
# ---------------------------------------------------------------------------

#: 「자료에 없다·발표에 안 넣었다·다루지 않았다·순위를 매기지 않았다」 — 자료의 범위를 정직하게 밝히는 답.
_NOT_IN_DECK_RE = re.compile(
    r"자료(?:에서는|에서|에는|에|엔)?\s*(?:[가-힣]+\s*){0,3}?(?:따로\s*)?(?:없|안\s*나|나오지\s*않|나오진\s*않|안\s*나오|다루지\s*않|"
    r"안\s*다뤄|제시되지\s*않|제시하지\s*않|안\s*넣|넣지\s*않|명시되지\s*않)|"
    r"(?:발표|자료)에\s*(?:는\s*)?안\s*넣|다루지(?:는)?\s*(?:못|않)|넣지(?:는)?\s*않|"
    r"(?:까지는|까지)\s*(?:[가-힣]+\s*){0,2}(?:안\s*넣|다루지\s*않|넣지\s*않|제시하지\s*않)|순위를\s*매기지(?:는)?\s*않|"
    r"(?:나오진|나오지는)\s*않"
)


def says_not_in_deck(text: str) -> bool:
    return bool(_NOT_IN_DECK_RE.search(text or ""))


#: 질문의 뼈대 낱말 — 무엇을·어떻게 묻는지의 말이지 자료의 대상이 아니다 (어느 발표에나 쓰는 질문 어휘).
_QUESTION_FRAME = (
    "무엇", "어떻", "어떤", "어느", "왜", "이유", "근거", "설명", "구체", "방법", "방안", "차이", "비교", "의미", "역할", "영향",
    "관계", "판단", "결론", "단정", "제시", "측면", "과정", "경우", "사례", "예시", "핵심", "중요", "가장", "요인", "기준",
    "발표", "자료", "질문", "개념", "생각", "내용", "부분", "메커니즘", "구조", "계산", "가져", "보나요", "보는지",
)
#: 줄기 끝의 동사 활용 — 명사가 아니다(「남겨」「방해한다는」). 하다·되다 동사는 앞 명사만 남긴다.
_HADA_RE = re.compile(r"(?:하|했|되|됐|할|한|해|돼|시킨|시켜)[가-힣]*$")
_VERBISH_END_RE = re.compile(r"(?:겨|아|어|여|고|며|서|면|는|은|을|기|게|지|요|다|까|나|니|던|든|록|수록)$")


def beyond_deck_terms(question: str, deck: Deck | None, label: str = "") -> list[str]:
    """
    질문이 묻는 명사 가운데 **자료에 없는 말** — 질문 자체가 자료 밖(측정 방법·실천 방안·순위)을 묻는지 보는 신호.
    자료가 없으면 빈 목록이다.
    """
    if deck is None or deck.empty:
        return []
    label_stems = content_stems(label)
    out: list[str] = []
    for s in content_stems(question):
        if any(s.startswith(f) for f in _QUESTION_FRAME) or _has(label_stems, s):
            continue
        noun = _HADA_RE.sub("", s) if _HADA_RE.search(s) and len(_HADA_RE.sub("", s)) >= 2 else s
        if _VERBISH_END_RE.search(noun) or len(noun) < 2:
            continue
        if not _has(list(deck.stems), noun) and noun not in out:
            out.append(noun)
    return out


def content_word_count(text: str) -> int:
    """내용 낱말 수 (상투어·한 글자 빼고) + 숫자 수. 「규칙」「8.7」 은 1이다."""
    return len(set(content_stems(text))) + len(numbers(text))


# ---------------------------------------------------------------------------
# §8 선택형 되물음 — 두 자료 낱말 사이의 진짜 양자택일인가
# ---------------------------------------------------------------------------

_OPEN_IN_CHOICE_RE = re.compile(r"어떤|무엇|어느|어떻게|왜|무슨")
_CHOICE_TAIL_RE = re.compile(
    r"^\s*['’」\"”]?\s*(?:(?:이|가|은|는)\s*)?(?:(?:쪽|측|편|이야기|얘기|문제|경우|부분|단계|때문)\s*)?"
    r"(?:인가요|이에요|예요|일까요|인지|이요|였나요|이었나요|인가|일까|이죠|쪽이|쪽인)"
)


def real_either_or(followup: str, choices: list[str]) -> bool:
    """
    되물음이 **두 선택지 사이에서 고르라는** 말인가 — 선택지가 문장 안에 그대로 있고, 바로 뒤가 「쪽인가요·인가요」 꼴이며,
    열린 물음 낱말(어떤·무엇)이 없다. 09-30 실측: 「수면 시간은 어떤 요소인가요, 연속성은 어떤 요소인가요?」 가 모양만 보고 통과했다.
    """
    if len(choices) != 2 or not followup or _OPEN_IN_CHOICE_RE.search(followup):
        return False
    for c in choices:
        i = followup.find(c)
        if i < 0 or not _CHOICE_TAIL_RE.match(followup[i + len(c): i + len(c) + 14]):
            return False
    return True


def same_kind(a: str, b: str) -> bool:
    """두 선택지가 같은 종류의 말인가 — 숫자끼리·영문끼리·한글끼리, 길이도 비슷하게(한쪽이 다른 쪽의 세 배를 넘지 않는다)."""
    def kind(x: str) -> str:
        if re.search(r"\d", x):
            return "num"
        return "latin" if re.fullmatch(r"[A-Za-z .\-]+", x.strip()) else "ko"
    la, lb = len(a.strip()), len(b.strip())
    return kind(a) == kind(b) and la > 0 and lb > 0 and max(la, lb) <= 3 * min(la, lb)
