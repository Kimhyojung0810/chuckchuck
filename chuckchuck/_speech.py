"""
말투·근거 공용 헬퍼 — F-08(질문·골자)과 F-09(판정·코칭)가 같이 쓴다.

화면 말투(CLAUDE.md §3-1 해요체)와 「자료에 있는 것만」 은 프롬프트로 부탁만 해서는 지켜지지 않았다
(09-12 반말 · 09-13 높임 · 09-24 높임 · 09-26 합쇼체·지어낸 숫자 실측). 코드가 받는다.
결정적이고 멱등이다 — 이미 해요체면 그대로, 숫자가 전부 자료에 있으면 빈 목록.
"""

from __future__ import annotations

import re

#: 자료 인용 «…» · 「…」 안은 자료 원문이라 손대지 않는다 (합쇼체여도 우리 말이 아니다).
_QUOTE_SPAN_RE = re.compile(r"(«[^»]*»|「[^」]*」)")
#: 어절 끝 — 뒤가 끝·공백·문장부호일 때만 어미로 본다 ("입니다만" 은 안 건드린다).
_END = r"(?=$|[\s.,!?»」)'\"…])"

#: 과거·완료 「~았/었습니다」 → 「~았/었어요」. 앞 음절이 이미 시제를 품고 있어 어미만 바꾸면 된다.
_PAST_RE = re.compile(r"(았|었|였|했|됐|겼|렸|났|왔|봤|줬|쳤|졌|켰|혔|섰|썼|랐|웠|팠|웠|캤|탔)습니다" + _END)
_PAST_Q_RE = re.compile(r"(았|었|였|했|됐|겼|렸|났|왔|봤|줬|쳤|졌|켰|혔|섰|썼|랐|웠|팠)습니까" + _END)
#: 어간별 표 — 활용이 규칙적이지 않아 낱말 단위로 둔다. 긴 것부터 맞춘다 ("만듭니다" 가 "듭니다" 보다 먼저).
_HAPSYO_MAP: dict[str, str] = {
    "만듭니다": "만들어요", "있습니다": "있어요", "없습니다": "없어요", "같습니다": "같아요", "않습니다": "않아요",
    "많습니다": "많아요", "좋습니다": "좋아요", "높습니다": "높아요", "낮습니다": "낮아요", "작습니다": "작아요",
    "적습니다": "적어요", "받습니다": "받아요", "맞습니다": "맞아요", "붙습니다": "붙어요", "넣습니다": "넣어요",
    "찾습니다": "찾아요", "남습니다": "남아요", "막습니다": "막아요", "낫습니다": "나아요", "짧습니다": "짧아요",
    "길습니다": "길어요", "크습니다": "커요", "합니다": "해요", "됩니다": "돼요", "봅니다": "봐요", "줍니다": "줘요",
    "옵니다": "와요", "갑니다": "가요", "냅니다": "내요", "씁니다": "써요", "압니다": "알아요", "듭니다": "들어요",
    "겁니다": "거예요", "큽니다": "커요", "깁니다": "길어요", "납니다": "나요", "삽니다": "사요", "섭니다": "서요",
    "있습니까": "있나요", "없습니까": "없나요", "합니까": "하나요", "됩니까": "되나요", "입니까": "인가요",
    "맞습니까": "맞나요", "같습니까": "같나요",
}
_MAP_RE = re.compile("(" + "|".join(sorted(map(re.escape, _HAPSYO_MAP), key=len, reverse=True)) + ")" + _END)
_IPNIDA_RE = re.compile(r"입니다" + _END)


def _has_batchim(ch: str) -> bool:
    return bool(ch) and "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 != 0


def _ipnida(m: re.Match) -> str:
    prev = m.string[m.start() - 1] if m.start() > 0 else ""
    # 앞이 한글이고 받침이 없으면 「예요」, 그 밖(받침·숫자·로마자)은 「이에요」.
    if "가" <= prev <= "힣" and not _has_batchim(prev):
        return "예요"
    return "이에요"


#: 모음 어간 + 「ㅂ니다」 — 「시킵니다」 처럼 표에 없는 규칙 활용. 어간 마지막 모음에 따라 어요/아요를 붙이고 줄인다.
#: 자모 인덱스: 초성 19 · 중성 21 · 종성 28. ㅂ 종성 = 17.
_BNIDA_RE = re.compile(r"([가-힣])니다" + _END)
_BNIDA_Q_RE = re.compile(r"([가-힣])니까" + _END)
#: 중성 인덱스 → (합쳐진 중성 인덱스). ㅏ0 ㅐ1 ㅑ2 ㅒ3 ㅓ4 ㅔ5 ㅕ6 ㅖ7 ㅗ8 ㅘ9 ㅙ10 ㅚ11 ㅛ12 ㅜ13 ㅝ14 ㅞ15 ㅟ16 ㅠ17 ㅡ18 ㅢ19 ㅣ20
_VOWEL_JOIN = {0: 0, 1: 1, 4: 4, 5: 5, 8: 9, 13: 14, 20: 6, 11: 10, 18: 4, 16: 16}   # 아→아 애→애 어→어 에→에 오→와 우→워 이→여 외→왜 으→어 위→위(어요 따로)


def _bnida(m: re.Match, tail: str) -> str:
    ch = m.group(1)
    if ch in ("습", "입"):                # 「습니다·입니다」 는 자음 어간·서술격 — 위 규칙들의 몫이다 (먹습니다 는 두고 넘어간다)
        return m.group(0)
    code = ord(ch) - 0xAC00
    lead, vowel, final = code // 588, (code % 588) // 28, code % 28
    if final != 17:                      # ㅂ 받침이 아니면 「~ㅂ니다」 가 아니다
        return m.group(0)
    base_vowel = vowel
    if lead == 18 and vowel == 0:        # 하 → 해
        return chr(0xAC00 + lead * 588 + 1 * 28) + tail
    if lead == 3 and vowel == 11:        # 되 → 돼
        return chr(0xAC00 + lead * 588 + 10 * 28) + tail
    if base_vowel == 18 and lead == 5:   # 르 어간(모르→몰라)은 불규칙 — 두고 넘어간다
        return m.group(0)
    if base_vowel == 16:                 # 위 + 어 → 위어 (줄이지 않는다: 쉬→쉬어요)
        return chr(0xAC00 + lead * 588 + 16 * 28) + "어" + tail
    joined = _VOWEL_JOIN.get(base_vowel)
    if joined is None:
        return m.group(0)
    return chr(0xAC00 + lead * 588 + joined * 28) + tail


def _haeyo_span(text: str) -> str:
    t = _PAST_RE.sub(r"\1어요", text)
    t = _PAST_Q_RE.sub(r"\1나요", t)
    t = _MAP_RE.sub(lambda m: _HAPSYO_MAP[m.group(1)], t)
    t = _IPNIDA_RE.sub(_ipnida, t)
    t = _BNIDA_RE.sub(lambda m: _bnida(m, "요"), t)
    return _BNIDA_Q_RE.sub(_bnida_q, t)


def _bnida_q(m: re.Match) -> str:
    """「~ㅂ니까」 → 「~나요」. 어간은 그대로 두고 ㅂ 받침만 뗀다 (시킵니까 → 시키나요)."""
    ch = m.group(1)
    code = ord(ch) - 0xAC00
    if ch in ("습", "입") or code % 28 != 17:
        return m.group(0)
    return chr(0xAC00 + (code - 17)) + "나요"


def to_haeyo(text: str) -> str:
    """합쇼체(~습니다·~입니다·~합니까)를 해요체로 바꾼다. 어절 끝만, 인용 «…» 안은 그대로.

    표에 없는 어간(「먹습니다」 같은)은 두고 넘어간다 — 틀리게 바꾸는 것보다 남기는 쪽이 낫다.
    남은 것은 실험대(labs/qa_lab) 의 `합쇼체N` 표식이 센다."""
    if not text:
        return text
    parts = _QUOTE_SPAN_RE.split(text)
    return "".join(p if i % 2 else _haeyo_span(p) for i, p in enumerate(parts))


# ---------------------------------------------------------------------------
# 지어낸 숫자 — 자료·발화·문헌 어디에도 없는 수치
# ---------------------------------------------------------------------------

#: 낱말에 붙은 숫자(개념1 · q01 · B2C · S3)는 이름이라 세지 않는다 — 앞이 글자·숫자가 아닐 때만.
_NUMBER_RE = re.compile(r"(?<![가-힣A-Za-z0-9])\d+(?:[.,]\d+)?\s*(?:%|퍼센트|회|배|명|건|초|분|시간|일|주|개월|년|원|달러|점|장|차|번째|번|개)?")
#: 인용 표기 「Boyle et al. (2022)」 의 연도는 문헌 것이라 자료에 없어도 된다.
_CITE_YEAR_RE = re.compile(r"\((\d{4})[a-z]?\)")
#: 자료의 위치·차례를 가리키는 단위 — 숫자 자체가 사실 주장이 아니다 ("2장", "1차", "세 번째").
_STRUCTURAL_UNITS = ("장", "차", "번째", "번")


def _squash(text: str) -> str:
    return re.sub(r"[\s,]+", "", text or "")


def ungrounded_numbers(text: str, sources: list[str] | tuple[str, ...]) -> list[str]:
    """`text` 의 숫자 토큰 중 `sources`(자료 글·발화·문헌) 어디에도 없는 것. 인용 연도·장 번호·단위 없는 한 자리 수는 뺀다.
    sources 가 비면 판단할 수 없어 빈 목록이다."""
    hay = _squash(" ".join(s for s in sources if s))
    if not hay:
        return []
    body = _CITE_YEAR_RE.sub("", text or "")
    out: list[str] = []
    for m in _NUMBER_RE.finditer(body):
        tok = _squash(m.group(0))
        digits = re.match(r"\d+(?:\.\d+)?", tok).group(0)
        unit = tok[len(digits):]
        if unit in _STRUCTURAL_UNITS:
            continue
        if len(digits) < 2 and not unit:
            continue
        if digits not in hay and tok not in out:
            out.append(tok)
    return out
