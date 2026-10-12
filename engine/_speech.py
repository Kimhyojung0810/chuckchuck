"""
말투·근거 공용 헬퍼 — F-08(질문·골자)과 F-09(판정·코칭)가 같이 쓴다.

화면 말투(CLAUDE.md §3-1 해요체)와 「자료에 있는 것만」 은 프롬프트로 부탁만 해서는 지켜지지 않았다
(09-12 반말 · 09-13 높임 · 09-24 높임 · 09-26 합쇼체·지어낸 숫자 실측). 코드가 받는다.
결정적이고 멱등이다 — 이미 해요체면 그대로, 숫자가 전부 자료에 있으면 빈 목록.
"""

from __future__ import annotations

import re

#: 자료 인용 «…» · 「…」 · 『…』 · '…' · "…"(곧은·굽은) 안은 자료 원문이라 손대지 않는다 (합쇼체여도 우리 말이 아니다).
#: 09-30 held-out M-01: 해설이 자료 줄을 작은따옴표로 인용했는데(「'야식이 다음 날 아침 공복 혈당을 높입니다'」) 변환이 인용 속까지
#: 들어가 「높이에요」 로 바꿨다 — 자료 인용이 자료와 달라졌다. 작은따옴표는 줄바꿈 없이 80자 안의 짝만 인용으로 본다.
_QUOTE_SPAN_RE = re.compile(
    r"(«[^»]*»|「[^」]*」|『[^』]*』|‘[^’\n]{1,80}’|“[^”\n]{1,80}”|'[^'\n]{1,80}'|\"[^\"\n]{1,80}\")")
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
    # 09-30 대화 감사 §9 — 규칙 활용 표가 틀리게 바꾸던 꼴. 「아닙니다」 는 ㅂ 규칙이 「아녀요」 로, 「보입니다」 는 서술격 규칙이
    # 「보예요」 로 만들었다. 「것입니다」 는 「것이에요」 도 틀리진 않지만 입말은 「거예요」 다.
    "아닙니다": "아니에요", "아닙니까": "아닌가요", "것입니다": "거예요", "것입니까": "건가요",
    "보입니다": "보여요", "쓰입니다": "쓰여요", "줄입니다": "줄여요", "높입니다": "높여요", "붙입니다": "붙여요",
    "쌓입니다": "쌓여요", "놓입니다": "놓여요", "움직입니다": "움직여요", "기울입니다": "기울여요", "들입니다": "들여요",
    "보입니까": "보이나요",
    # 「-이-」 사동·피동 어간 + ㅂ니다 — 「입니다」 를 서술격으로 읽으면 「먹이에요」 가 된다 (09-30 held-out M-01 「높이에요」)
    "먹입니다": "먹여요", "녹입니다": "녹여요", "속입니다": "속여요", "죽입니다": "죽여요", "끓입니다": "끓여요",
    "숙입니다": "숙여요", "섞입니다": "섞여요", "늘입니다": "늘여요", "꺾입니다": "꺾여요", "닦입니다": "닦여요",
    "묶입니다": "묶여요", "벌입니다": "벌여요", "절입니다": "절여요", "굽입니다": "굽혀요",
    # ㄷ 불규칙 — 아래 받침 어간 규칙이 「듣어요」 로 만들지 않게 먼저 둔다
    "듣습니다": "들어요", "묻습니다": "물어요", "걷습니다": "걸어요", "싣습니다": "실어요", "깨닫습니다": "깨달아요",
    # ㅅ·ㅎ 불규칙 — 받침 어간 규칙이 건너뛰는 꼴 가운데 흔한 것
    "짓습니다": "지어요", "붓습니다": "부어요", "잇습니다": "이어요", "그렇습니다": "그래요", "이렇습니다": "이래요",
    "저렇습니다": "저래요", "어떻습니까": "어때요",
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


#: ㅂ 불규칙 형용사 「아쉽습니다」 → 「아쉬워요」. 어간 끝 음절 꼴로만 잡는다 — 「잡습니다·좁습니다」 같은 규칙 활용은 이 꼴이 아니다.
#: 09-30 실측: 판정 총평 「…가 아쉽습니다」 가 그대로 나갔다(표에 없는 어간이라 to_haeyo 가 건너뛰었다).
_B_IRREGULAR_RE = re.compile(r"([가-힣]*(?:럽|롭|깝|겁|볍|렵|쉽|갑|맙|섭|덥|춥|엽|깁|겹|껍))습니다" + _END)


def _b_irregular(m: re.Match) -> str:
    word = m.group(1)
    last = word[-1]
    code = ord(last) - 0xAC00
    return word[:-1] + chr(0xAC00 + (code - 17)) + "워요"      # ㅂ 받침(17)을 떼고 「워요」


def _haeyo_span(text: str) -> str:
    t = _PAST_RE.sub(r"\1어요", text)
    t = _PAST_Q_RE.sub(r"\1나요", t)
    t = _B_IRREGULAR_RE.sub(_b_irregular, t)
    t = _MAP_RE.sub(lambda m: _HAPSYO_MAP[m.group(1)], t)
    t = _IPNIDA_RE.sub(_ipnida, t)
    t = _BNIDA_RE.sub(lambda m: _bnida(m, "요"), t)
    t = _BATCHIM_SEUMNIDA_RE.sub(_batchim_seumnida, t)
    return _BNIDA_Q_RE.sub(_bnida_q, t)


#: 받침 어간 + 「습니다」 (표에 없는 규칙 활용) → 모음 조화로 「아요/어요」. 09-30 실측: 코칭 react 「괜찮습니다」 가 그대로 나갔다.
#: ㅂ·ㄷ 불규칙은 위 규칙·표가 먼저 받는다.
_BATCHIM_SEUMNIDA_RE = re.compile(r"([가-힣])습니다" + _END)


def _batchim_seumnida(m: re.Match) -> str:
    ch = m.group(1)
    code = ord(ch) - 0xAC00
    final = code % 28
    # 받침 없음·ㅅ(19)·ㅎ(27) 받침은 불규칙일 수 있어(「파랗습니다」→「파래요」) 두고 넘어간다 — 틀리게 바꾸느니 남긴다
    if final in (0, 19, 27):
        return m.group(0)
    vowel = (code % 588) // 28
    return ch + ("아요" if vowel in (0, 8) else "어요")


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
# 해라체 「…했다.」 → 해요체 — 판정 총평이 보고서 말투로 오는 것 (09-30 대화 감사 §9: 해라체 총평 7건)
# ---------------------------------------------------------------------------

#: 문장 끝 해라체 어절. 뒤가 문장부호·끝일 때만 — 「…했다는 점」 처럼 이어지는 말은 건드리지 않는다.
_HAERA_RE = re.compile(r"([가-힣]+)다(?=\s*(?:[.!]|$))")
_PAST_SYLLABLES = set("았었였했됐겼렸났왔봤줬쳤졌켰혔섰썼랐웠팠캤탔갔냈셨")
_ONE_SYLLABLE_OK = set("크")


def _to_hapsyo(word: str) -> str:
    """해라체 어절(「…다」 뗀 앞) → 합쇼체. 모르는 꼴은 빈 문자열 — 틀리게 바꾸느니 둔다."""
    if not word:
        return ""
    last = word[-1]
    code = ord(last) - 0xAC00
    if not (0 <= code < 11172):
        return ""
    final = code % 28
    if last in _PAST_SYLLABLES:                      # 했다 → 했습니다
        return word + "습니다"
    if word.endswith("는"):                          # 먹는다 → 먹습니다 (현재 동사 — 어간은 「는」 앞)
        return word[:-1] + "습니다" if len(word) >= 2 else ""
    if final == 4:                                   # 설명한다·보여준다(ㄴ 받침 + 다) → 설명합니다·보여줍니다
        return word[:-1] + chr(0xAC00 + code - 4 + 17) + "니다"
    if last == "이":                                 # …이다 → …입니다 (서술격)
        return word[:-1] + "입니다"
    if final == 0:                                   # 크다·아니다(모음 어간) → 큽니다·아닙니다
        return word[:-1] + chr(0xAC00 + code + 17) + "니다"
    return word + "습니다"                            # 많다·없다·좋다(받침 어간) → 많습니다


def plain_to_haeyo(text: str) -> str:
    """
    문장 끝 해라체(「…설명했다.」「…부족하다.」「…것이다.」)를 해요체로. 인용 «…»·「…」 안은 그대로.

    합쇼체로 한 번 옮긴 뒤 `to_haeyo` 표를 탄다 — 그 표가 모르는 꼴(바꿔도 「…습니다」 로 남는 것)은 원문을 둔다.
    판정 문장(F-09)에만 쓴다. 자료 인용이 섞인 F-08 골자에 걸면 자료 원문 말투까지 바뀐다.
    """
    if not text:
        return text

    def one(m: re.Match) -> str:
        word = m.group(1)
        if word.endswith("아니"):                    # 「…핵심이 아니다.」 → 「아니에요」 (「니」 끝은 아래에서 합쇼 잔여로 보고 건너뛴다)
            return word + "에요"
        # 「…습니다·…입니다」 가 표에 없어 남은 합쇼체는 해라체가 아니다(「잡습니다」 의 「잡습니」+다). 한 음절 어절은 명사 끝일 수
        # 있어(「바다」) 받침 있는 형용사 어간·흔한 동사 활용만 받는다.
        if word.endswith("니") or (len(word) == 1 and not _has_batchim(word) and word not in _ONE_SYLLABLE_OK):
            return m.group(0)
        hapsyo = _to_hapsyo(word)
        if not hapsyo:
            return m.group(0)
        out = _haeyo_span(hapsyo)
        return m.group(0) if out == hapsyo or "니다" in out else out

    parts = _QUOTE_SPAN_RE.split(text)
    return "".join(p if i % 2 else _HAERA_RE.sub(one, p) for i, p in enumerate(parts))


# ---------------------------------------------------------------------------
# 물음 끝 — 「…알고 있는가요?」 → 「…알고 있나요?」 (판정 되물음·react)
# ---------------------------------------------------------------------------

#: 동사 어간 + 「는가요」 는 해요체 물음이 아니다 — 「는가」 는 해라체·하게체 물음 어미라 「요」 를 붙여도 어색하다(「알고 있는가요?」
#: 「고려하고 있는가요?」 — 09-30 standard 실측 LLM 되물음 2건). 해요체 물음은 「나요」 다. 「인가요」(서술격)·「한가요·은가요」(형용사)는
#: 맞는 꼴이라 그대로 둔다. 뒤가 물음표·끝·공백일 때만 — 「…는가요소」 같은 낱말 속은 안 건드린다.
_NEUNGAYO_RE = re.compile(r"(?<=[가-힣])는가요(?=\s*[?？]|\s*$|[\s.,!…])")
#: 해라체 물음 「…측정했는가?」「…무엇인가?」 — 요 없이 끝난 물음. 「는가?」 → 「나요?」, 「인가?」 → 「인가요?」.
_NEUNGA_Q_RE = re.compile(r"(?<=[가-힣])는가(?=\s*[?？])")
_INGA_Q_RE = re.compile(r"(?<=[가-힣])(인|한|은)가(?=\s*[?？])")
#: 「…설정되었는지요?」 — 맞는 말이지만 해요체 물음이 아니다(09-30 실측 질문 31건). 「는지요?」 → 「나요?」,
#: 「인지요·한지요·은지요?」 → 「인가요·한가요·은가요?」.
_NEUNJIYO_RE = re.compile(r"(?<=[가-힣])는지요(?=\s*[?？])")
_INJIYO_RE = re.compile(r"(?<=[가-힣])(인|한|은)지요(?=\s*[?？])")


def _question_endings_span(text: str) -> str:
    t = _NEUNGAYO_RE.sub("나요", text)
    t = _NEUNGA_Q_RE.sub("나요", t)
    t = _INGA_Q_RE.sub(r"\1가요", t)
    t = _NEUNJIYO_RE.sub("나요", t)
    return _INJIYO_RE.sub(r"\1가요", t)


def fix_question_endings(text: str) -> str:
    """
    물음 끝을 해요체 물음으로 — 「있는가요?」→「있나요?」 · 「했는가?」→「했나요?」 · 「무엇인가?」→「무엇인가요?」 ·
    「되었는지요?」→「되었나요?」. 인용 «…»·「…」 안은 그대로(자료 원문의 「얼마나 잤는가」 는 제목이다). 결정적·멱등.
    판정 문장(F-09 react·되물음·해설)에만 쓴다.
    """
    if not text:
        return text
    parts = _QUOTE_SPAN_RE.split(text)
    return "".join(p if i % 2 else _question_endings_span(p) for i, p in enumerate(parts))


def josa_of(word: str, with_batchim: str, without: str) -> str:
    """
    낱말 **뒤에 붙일 조사만** — 마지막 소리의 받침으로 (「…낮음」이라고 · 「…늘었다」라고 · 「…42%」라고).
    닫는 따옴표·괄호·마침표는 건너뛰고 본다. 숫자는 읽는 소리로(1·3·6·7·8·0 은 받침), 모르는 글자(로마자)는 받침 없는 쪽.
    09-30 WP-Q: 인용 뒤 「라고」 를 받침과 상관없이 붙여 「…낮음」라고 · 「…다섯」라고 가 나갔다.
    """
    w = re.sub(r"[\s.…」』”\"'’»)\]]+$", "", word or "")
    last = w[-1:] if w else ""
    if not last:
        return without
    if "가" <= last <= "힣":
        return with_batchim if _has_batchim(last) else without
    if last.isdigit():
        return with_batchim if last in "013678" else without
    return without


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
