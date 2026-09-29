"""
한국어 글 조각 — 페르소나 · 태거 · 공격 답이 같이 쓰는 **순수 함수**. 대상 저장소 코드를 import 하지 않는다.

잣대는 고정이어야 한다: 대상 코드(`_evidence`·`_traps`)로 대상 코드를 재면 같은 버그를 못 본다
(labs/qa_bench/metrics.py 머리말과 같은 원칙). 여기 규칙은 전부 **말의 모양**이다 — 특정 덱의 낱말은 없다.
"""

from __future__ import annotations

import hashlib
import re

# ---------------------------------------------------------------------------
# 토큰
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)")
_TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{3,}|\d+(?:[.,]\d+)?%?p?")
#: 낱말 끝 조사 — 떼고 줄기만 비교한다 (긴 것 먼저).
_JOSA_RE = re.compile(r"(?:에서는|에서도|으로는|으로써|에게서|이라고|이라는|에서|으로|에게|까지|부터|처럼|보다|라고|라는|이나|이며"
                      r"|과는|와는|은|는|이|가|을|를|의|에|와|과|도|로|만)$")
#: 비교에서 빼는 뼈대 낱말 — 물음 틀·상투어. 어느 발표에나 있는 말이라 겹쳐도 내용이 겹친 게 아니다.
STOP = frozenset({
    "무엇", "무엇인가요", "어떤", "어떻게", "어느", "있나요", "했는데", "대해", "설명해", "주세요", "경우", "의미", "근거",
    "이유", "자료", "발표", "말씀", "생각", "그렇게", "있는", "하는", "것은", "것이", "이런", "그런", "그래서", "그리고",
    "하지만", "때문", "때문에", "있어요", "없어요", "해요", "했어요", "이에요", "예요", "거예요", "같아요", "있습니다",
    "합니다", "입니다", "됩니다", "무슨", "정도", "부분", "내용", "핵심", "질문", "설명", "통해", "위해", "관련", "보여",
    "보여주", "나와", "나와요", "말해요", "해서", "라고", "이라고", "하고", "되는", "된다", "한다", "이다", "있다",
})


def tokens(text: str) -> list[str]:
    """내용 낱말 (두 글자 이상 한글 · 세 글자 이상 영문 · 숫자). 조사를 떼고, 뼈대 낱말은 뺀다. 순서를 지킨다."""
    out: list[str] = []
    for w in _TOKEN_RE.findall(_TAG_RE.sub(" ", text or "")):
        s = _JOSA_RE.sub("", w) if re.match(r"[가-힣]", w) and len(w) > 2 else w
        if len(s) < 2 and not re.match(r"\d", s):
            continue
        if s in STOP or w in STOP:
            continue
        if s not in out:
            out.append(s)
    return out


def _same(a: str, b: str) -> bool:
    """두 낱말이 같은 말인가 — 같거나, 두 글자 이상 앞부분을 공유하면서 짧은 쪽이 긴 쪽의 머리다(조사·활용 차이)."""
    if a == b:
        return True
    if min(len(a), len(b)) < 2:
        return False
    return a.startswith(b) or b.startswith(a)


def overlap(a: str | list[str], b: str | list[str]) -> int:
    """a 의 내용 낱말 가운데 b 에 (같은 줄기로) 나오는 것의 수."""
    ta = tokens(a) if isinstance(a, str) else a
    tb = tokens(b) if isinstance(b, str) else b
    return sum(1 for x in ta if any(_same(x, y) for y in tb))


def coverage(part: str, whole: str) -> float:
    """part 의 내용 낱말 중 whole 에 나오는 몫 (0~1). 낱말이 없으면 1.0 — 판단할 거리가 없다."""
    tp = tokens(part)
    if not tp:
        return 1.0
    return overlap(tp, whole) / len(tp)


def squash(text: str) -> str:
    """대조용 — 태그·공백·따옴표·문장부호를 지우고 소문자로."""
    text = _TAG_RE.sub(" ", text or "")
    return re.sub(r"[\s\"'“”‘’「」『』«»`|•▪■◦*#.,·:;!?()\[\]{}~…—–-]+", "", text).lower()


def seed_of(*parts: str) -> int:
    """같은 입력이면 늘 같은 수 — 페르소나 말투 고르기용 (random 을 쓰지 않는다)."""
    h = hashlib.sha1("\0".join(parts).encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def strip_quotes(text: str) -> str:
    """«…» 「…」 “…” 인용 안의 말은 뺀다 — 자료 원문의 합쇼체는 코치의 잘못이 아니다."""
    return re.sub(r"«[^»]*»|“[^”]*”|「[^」]*」|『[^』]*』|\"[^\"]*\"", " ", text or "")


# ---------------------------------------------------------------------------
# 받침 · 조사
# ---------------------------------------------------------------------------

_DIGIT_BATCHIM = {"0": True, "1": True, "2": False, "3": True, "4": False, "5": False, "6": True, "7": True,
                  "8": True, "9": False}


def batchim(word: str) -> bool:
    """끝 글자에 받침이 있는가. 한글이 아니면 숫자 읽기로, 그것도 아니면 받침 없음으로 본다."""
    w = (word or "").rstrip(" .)」'\"")
    if not w or w.endswith(("%", "%p")):
        return False            # 퍼센트 · 퍼센트포인트
    ch = w[-1]
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    if ch in _DIGIT_BATCHIM:
        return _DIGIT_BATCHIM[ch]
    return ch.lower() in "lmnr"


def josa(word: str, with_batchim: str, without: str) -> str:
    return word + (with_batchim if batchim(word) else without)


def _jong(ch: str) -> int:
    return (ord(ch) - 0xAC00) % 28 if "가" <= ch <= "힣" else -1


def _set_jong(ch: str, jong: int) -> str:
    base = ord(ch) - ((ord(ch) - 0xAC00) % 28)
    return chr(base + jong)


# ---------------------------------------------------------------------------
# 자료 줄 → 입말
# ---------------------------------------------------------------------------

_BULLET_RE = re.compile(r"^\s*(?:[·•▪■◦∙*\-–—]+|[①-⑳]|\(?\d{1,2}[.)])\s*")
_PAGE_RE = re.compile(r"^[\d\s/|.·-]+$")


def is_caption(line: str) -> bool:
    """문서 변환기가 만든 영문 그림 설명 줄 (「- Chart Type: …」 · 한글이 30% 안 되는 긴 줄)."""
    s = (line or "").strip()
    if re.search(r"(?:Chart|Figure|Graph|Diagram|Image)\s+Type\s*:", s, re.I) or s.startswith(("<figcaption", "<p class")):
        return True
    h, a = len(re.findall(r"[가-힣]", s)), len(re.findall(r"[A-Za-z]", s))
    return len(s) >= 30 and a > 0 and h / (h + a) < 0.3


def clean_line(line: str) -> str:
    """글머리표·마크업·끝 문장부호를 지운 한 줄."""
    s = _TAG_RE.sub(" ", line or "")
    s = _BULLET_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([.,])", r"\1", s)
    return s.rstrip(" .,。!")


def slide_texts(slide_doc: dict | None) -> dict[int, str]:
    """{장 번호: 원문}. raw_text 가 없으면 블록 글을 잇는다."""
    out: dict[int, str] = {}
    for s in (slide_doc or {}).get("slides") or []:
        raw = s.get("raw_text")
        if raw is None:
            raw = "\n".join(str(b.get("text", "")) for b in s.get("blocks") or [] if isinstance(b, dict))
        out[int(s.get("slide_no") or 0)] = raw or ""
    return out


#: 줄이 이렇게 끝나면 문장이 다음 줄로 이어진다 (쉼표 · 대비 · 연결 어미 · 조사).
_OPEN_END_RE = re.compile(r"(?:,|아니라|아닌|보다|는데|지만|으며|면서|에서|으로|에게|은|는|이|을|를|와|과|의|고|며|및|=|×|→)$")


def deck_lines(slide_doc: dict | None) -> list[tuple[int, str]]:
    """
    (장, 줄) — 캡션·쪽 번호·표 구분선을 뺀 자료 줄. 문장이 안 끝난 줄(쉼표·「아니라」·조사로 끝남)은 다음 줄과 잇는다
    — 「좋은 잠은 … 잠이 아니라,」 / 「몸과 뇌가 … 잠입니다.」 는 한 문장이다.
    """
    out: list[tuple[int, str]] = []
    for no, raw in slide_texts(slide_doc).items():
        pending = ""
        for line in raw.split("\n"):
            raw_line = _TAG_RE.sub(" ", line).strip()
            s = clean_line(line)
            if not s or _PAGE_RE.match(s) or is_caption(s) or re.fullmatch(r"\|?\s*:?-{3,}.*", s):
                continue
            if pending:
                s = f"{pending} {s}"
                pending = ""
            elif (out and out[-1][0] == no and " " not in s and len(s) <= 6 and not _BULLET_RE.match(raw_line)
                  and not re.search(r"(?:[.!?]|다|요|죠)$", out[-1][1])):
                out[-1] = (no, f"{out[-1][1]} {s}")      # 폭으로 꺾여 내려온 한 낱말 (「… 2.6%p」 / 「하회」)
                continue
            if _OPEN_END_RE.search(raw_line.rstrip(" .")) and len(s) < 90:
                pending = s
                continue
            if len(s) >= 6:
                out.append((no, s))
        if pending and len(pending) >= 6:
            out.append((no, pending))
    return out


_META_RE = re.compile(r"※|출처|참고\s*문헌|리서치팀|\b\d{4}\.\s*\d{1,2}\b|©|All rights|Page\s*\d")


def is_meta(line: str) -> bool:
    """표지 날짜·출처·주의 문구 — 발표의 주장이 아니다."""
    return bool(_META_RE.search(line or ""))


def table_text(line: str) -> str:
    """「| 거래 비용 | -0.2 |」 → 「거래 비용 -0.2」. 표 행이 아니면 그대로."""
    if "|" not in (line or ""):
        return line
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    cells = [c for c in cells if c and not re.fullmatch(r":?-{3,}:?", c)]
    return " ".join(cells)


def deck_text(slide_doc: dict | None) -> str:
    return "\n".join(line for _, line in deck_lines(slide_doc))


def plain_form(line: str) -> tuple[str, bool]:
    """
    자료 줄의 끝을 **평서 기본형**(…다)으로 — (글, 명사로 끝났나). 합쇼체·명사형(…음/함/됨)을 푼다.
    「격차는 행동에서 만들어진다」 → 그대로 · 「됩니다」 → 「된다」 · 「상관은 약함」 → 「상관은 약하다」.
    """
    s = clean_line(line)
    if not s:
        return "", True
    s = re.sub(r"(?:이에요|예요)$", "이다", s)
    if s.endswith("입니다"):
        return s[:-3] + "이다", False
    if s.endswith("아닙니다"):
        return s[:-4] + "아니다", False
    if s.endswith("습니다"):
        return s[:-3] + "다", False
    if len(s) >= 3 and s.endswith("니다") and _jong(s[-3]) == 17:     # ㅂ니다 → ㄴ다 (됩니다 → 된다)
        return s[:-3] + _set_jong(s[-3], 4) + "다", False
    if s.endswith(("해요", "해요.")):
        return s[: s.rfind("해요")] + "한다", False
    for tail, repl in (("함", "하다"), ("됨", "된다"), ("임", "이다"), ("짐", "진다")):
        if s.endswith(tail) and len(s) >= 2:
            return s[: -len(tail)] + repl, False
    if s.endswith("음") and len(s) >= 3 and "가" <= s[-2] <= "힣":
        return s[:-1] + "다", False
    if s.endswith("다"):
        return s, False
    return s, True


def reported(line: str) -> str:
    """「…라고 / …다고」 — 자료 줄을 옮겨 말하는 꼴. 입말 답의 한 조각이다."""
    s, nominal = plain_form(line)
    if not s:
        return ""
    if nominal:
        return josa(s, "이라고", "라고")
    if s.endswith("아니다"):
        return s[:-1] + "라고"
    if s.endswith("이다"):
        return s[:-1] + "라고"
    if len(s) >= 3 and "가" <= s[-2] <= "힣" and not batchim(s[-2]) and not s[:-1].endswith(_ADJ_STEMS):
        return s[:-1] + "라고"          # 「…횟수다」 — 받침 없는 명사 + 서술격 조사
    return s + "고"


#: 받침 없이 「다」 로 끝나는 형용사 줄기 — 서술격 조사로 읽지 않는다.
_ADJ_STEMS = ("크", "빠르", "느리", "아프", "바쁘", "기쁘", "예쁘", "나쁘", "고프", "슬프", "다르", "이르", "모자라", "그르")


def swap_topic_particle(line: str) -> str:
    """첫 주제 조사(은/는)를 주격(이/가)으로 — 가벼운 바꿔 말하기. 뜻은 같다."""
    m = re.search(r"([가-힣]{2,})(은|는)\s", line or "")
    if not m or m.group(1).endswith(("하", "되", "있", "없", "지", "치", "리", "우", "추", "주", "시", "기", "이")):
        return line                     # 「뒷받침하는 연구」 의 「는」 은 관형형이다 — 조사가 아니다
    word = m.group(1)
    return line[: m.start()] + josa(word, "이", "가") + " " + line[m.end():]


# ---------------------------------------------------------------------------
# 대비 · 명사구 · 뒤집기
# ---------------------------------------------------------------------------

#: 「X(이|가) 아니라 Y」 · 「X가 아닌 Y」 — X 는 부정한 쪽, Y 는 자료가 세운 쪽.
CONTRAST_RE = re.compile(r"(?P<neg>[가-힣A-Za-z0-9·\s]{1,24}?)(?:이|가|은|는)?\s*(?:아니라|아닌)\s*,?\s*(?P<pos>[가-힣A-Za-z0-9·]+(?:\s[가-힣A-Za-z0-9·]+)?)")
#: 세는 단위·의존 명사 — 홀로는 보기가 못 된다 (「'가지' 쪽인가요」).
BOUND_NOUNS = frozenset({"가지", "개", "명", "번", "회", "곳", "점", "등", "것", "수", "때", "중", "개월", "년", "주", "일", "분",
                         "초", "배", "차", "쪽", "부분", "경우", "정도", "이상", "이하", "대비", "위", "편", "게"})
#: 명사구가 아닌 꼬리 — 활용 · 연결 어미 · 물음꼴 (「방해하지」「제시하지」「줄이는」「샀는가」).
VERB_TAIL_RE = re.compile(r"(?:하지|되지|해야|아지|어지|하게|되게|하는|되는|하며|하고|해서|하여|했|었|았|였|겠|니다|는가|은가|인가|는지|"
                          r"은지|느냐|수록|도록|면서|지만|어서|아서|다|요|며|고|는|을|를|의|에|로)$")
_NOUN_OK = frozenset({"피해", "이해", "방해", "손해", "재해", "마음", "처음", "다음", "소음", "얼음", "도로", "경로", "진로", "기로",
                      "올해", "매해", "하나", "사고", "보고", "재고", "광고", "최고", "참고", "경고", "비교", "학교", "모두",
                      "수요", "필요", "중요", "개요", "주요", "관계", "정보", "기간", "시간", "공간", "인간"})


def noun_like(term: str) -> bool:
    """보기 하나가 명사(구)인가 — 끝 낱말이 활용 꼬리·조사로 끝나지 않고, 홀로 선 세는 단위가 아니다."""
    words = re.findall(r"[가-힣A-Za-z0-9%.]+", term or "")
    if not words:
        return False
    last = words[-1]
    if len(words) == 1 and last in BOUND_NOUNS:
        return False
    if re.fullmatch(r"[A-Za-z0-9%.]+", last):
        return True
    if last in _NOUN_OK:
        return True
    return not VERB_TAIL_RE.search(last)


def noun_phrase_ok(phrase: str) -> bool:
    """대비 한쪽이 보기감 명사구인가 — 앞 낱말은 명사거나 관형격(「과제의 양」), 끝 낱말은 명사. 「시간을 훔치는 게」 는 절이다."""
    words = re.findall(r"[가-힣A-Za-z0-9%.·]+", phrase or "")
    if not words or len(words) > 3 or len(re.sub(r"\s", "", phrase)) < 2:
        return False
    for w in words[:-1]:
        if not (noun_like(w) or w.endswith("의")):
            return False
    last = words[-1]
    if last in BOUND_NOUNS:
        return len(words) >= 2 and noun_like(words[-2])       # 「기능 수」 는 되고 홀로 선 「수」 는 안 된다
    return noun_like(last)


def contrast_sides(line: str) -> tuple[str, str] | None:
    """「X 아니라 Y」 → (부정한 쪽 X, 세운 쪽 Y) — 조사를 뗀 구절. 물음 줄이나 X·Y 가 비면 None."""
    if "?" in (line or ""):
        return None
    m = CONTRAST_RE.search(line or "")
    if not m:
        return None
    neg = re.split(r"[:：,]", m.group("neg"))[-1].strip()
    neg_words = [w for w in neg.split() if w]
    # 주제어(「격차는」)는 부정된 쪽이 아니다 — 뒤 낱말만
    while len(neg_words) > 1 and re.search(r"(은|는)$", neg_words[0]):
        neg_words = neg_words[1:]
    neg = _JOSA_RE.sub("", " ".join(neg_words[-2:]))
    pos = _noun_phrase(line[m.start("pos"):])
    if not neg or not pos:
        return None
    return neg, pos


def _noun_phrase(rest: str) -> str:
    """「행동에서 만들어진다」 → 「행동」 · 「첫 화면 이해도」 → 그대로. 조사가 붙은 낱말에서 명사구가 끝난다."""
    words = re.findall(r"[가-힣A-Za-z0-9·%.]+", rest or "")[:4]
    out: list[str] = []
    for i, w in enumerate(words):
        stripped = _JOSA_RE.sub("", w) if len(w) > 1 else w
        last = i == len(words) - 1
        if stripped != w and not last:
            out.append(stripped)
            break
        if last and len(w) >= 3 and w.endswith("다") and not batchim(w[:-1]):
            out.append(w[:-1])          # 「피드백 속도다」 — 명사 + 서술격 조사
            break
        if VERB_TAIL_RE.search(w) and w not in _NOUN_OK and out:
            break
        out.append(w)
        if len(out) >= 3:
            break
    return " ".join(out).strip()


def negated_terms(line: str) -> list[str]:
    """줄에서 **부정된 절**(「… 아니라/아닌/않」 앞) 안의 내용 낱말 — 정답 보기가 여기 있으면 거꾸로다."""
    out: list[str] = []
    for m in re.finditer(r"아니라|아닌|아니다|않", line or ""):
        clause = re.split(r"[:.·,]", line[: m.start()])[-1]
        out += tokens(clause)
    return out


_UNIT_RE = r"(?:%p|%|배|회|번|개월|개|년|주|명|건|만\s?원|억\s?원|억|원|분|시간|초|점|곳|세|살|kg|km|cm|mm|g|m|℃|ml|L)"
_NUM_RE = re.compile(rf"(?<![\w.,])([-−]?)(\d{{1,3}}(?:,\d{{3}})+|\d+(?:\.\d+)?)(\s?)({_UNIT_RE})?")


def numbers(text: str) -> list[str]:
    """숫자 토큰 (단위 포함, 공백 제거). 두 자리 미만 맨숫자는 셈이라 뺀다."""
    out = []
    for m in _NUM_RE.finditer(text or ""):
        tok = (m.group(1) + m.group(2) + (m.group(4) or "")).replace(" ", "")
        if not m.group(4) and len(m.group(2).replace(",", "")) < 2:
            continue
        out.append(tok)
    return out


def _fmt(value: float, raw: str) -> str:
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    if "," in raw:
        return f"{value:,.{decimals}f}"
    return f"{value:.{decimals}f}" if decimals else str(int(round(value)))


def number_flip(text: str, avoid: str = "") -> tuple[str, str, str] | None:
    """글의 첫 「숫자+단위」 하나를 자료에 없는 값으로 (×1.5, 안 되면 ×0.6·×1.3) → (새 글, 원래, 바꾼 것)."""
    avoid_sq = squash(avoid)
    matches = [m for m in _NUM_RE.finditer(text or "") if m.group(4)]
    # 크기가 곧 뜻인 단위(%·배·원·명…)를 먼저 — 「1년 새」 같은 기간은 뒤로
    matches.sort(key=lambda m: m.group(4) in ("년", "개월", "주", "일"))
    for m in matches:
        raw = m.group(2)
        try:
            v = float(raw.replace(",", ""))
        except ValueError:
            continue
        if v == 0:
            continue
        for f in (1.5, 0.6, 1.3, 0.7):
            w = v * f
            if m.group(4) in ("%", "점") and v <= 100:
                w = min(w, 99.0 if v < 99 else 100.0)
            new = _fmt(w, raw)
            if new == raw or squash(new + (m.group(4) or "")) in avoid_sq:
                continue
            old_tok = m.group(0)
            new_tok = m.group(1) + new + m.group(3) + (m.group(4) or "")
            return text[: m.start()] + new_tok + text[m.end():], old_tok.strip(), new_tok.strip()
    return None


#: 방향 짝 — 어느 분야에나 쓰는 한국어 문법 낱말 (앞 → 뒤, 뒤 → 앞 둘 다). 긴 것부터 맞춘다.
ANTONYM_PAIRS = (
    ("멀어질수록", "가까울수록"), ("늘어날수록", "줄어들수록"), ("높을수록", "낮을수록"), ("많을수록", "적을수록"),
    ("클수록", "작을수록"), ("길수록", "짧을수록"), ("늘어났", "줄어들었"), ("늘어나", "줄어들"), ("늘었", "줄었"),
    ("늘리", "줄이"), ("늘어", "줄어"), ("높아지", "낮아지"), ("높아졌", "낮아졌"), ("높였", "낮췄"), ("높은", "낮은"),
    ("높다", "낮다"), ("높고", "낮고"), ("증가", "감소"), ("상승", "하락"), ("상회", "하회"), ("커지", "작아지"),
    ("커졌", "작아졌"), ("많은", "적은"), ("많다", "적다"), ("좋아지", "나빠지"), ("좋아졌", "나빠졌"), ("개선", "악화"),
    ("강화", "약화"), ("빨라지", "느려지"), ("빠르", "느리"), ("끊는", "이어 주는"), ("끊긴", "이어진"), ("뚜렷한", "약한"),
    ("역상관", "정상관"), ("유리", "불리"), ("긍정", "부정"), ("끊는다", "이어 준다"), ("끊긴다", "이어진다"),
    ("끊어", "이어"),
)
_ANT_MAP = {**{a: b for a, b in ANTONYM_PAIRS}, **{b: a for a, b in ANTONYM_PAIRS}}
ANTONYM_RE = re.compile("|".join(re.escape(w) for w in sorted(_ANT_MAP, key=len, reverse=True)))


def antonym_of(word: str) -> str:
    return _ANT_MAP.get(word, "")


def antonym_flip(text: str) -> tuple[str, str, str] | None:
    """글의 첫 방향 낱말 하나를 반대로 → (새 글, 원래, 바꾼 것)."""
    m = ANTONYM_RE.search(text or "")
    if not m:
        return None
    w = m.group(0)
    return text[: m.start()] + _ANT_MAP[w] + text[m.end():], w, _ANT_MAP[w]


def contrast_swap(text: str) -> tuple[str, str, str] | None:
    """「X가 아니라 Y」 → 「Y가 아니라 X」 → (새 글, 원래 구절, 바꾼 구절). X·Y 가 한 낱말 명사일 때만 — 구절을 바꾸면 말이 깨진다."""
    m = re.search(r"(?<![가-힣])([가-힣A-Za-z0-9·]+?)(이|가)\s+아니라\s*,?\s*([가-힣A-Za-z0-9·]+?)(에서|이|가|을|를|로|으로|의)?(?=\s|$)", text or "")
    if not m:
        return None
    x, y = m.group(1), m.group(3)
    before = text[: m.start()].rstrip()
    if (x == y or not m.group(4) or re.search(r"[가-힣]의$", before) or not (noun_like(x) and noun_like(y))):
        return None
    new = f"{josa(y, '이', '가')} 아니라 {x}{m.group(4) or ''}"
    return text[: m.start()] + new + text[m.end():], m.group(0), new


FLIP_KINDS = ("number", "direction", "contrast")


def one_fact_flip(text: str, avoid: str = "", kinds: tuple[str, ...] = FLIP_KINDS) -> tuple[str, str, str, str] | None:
    """하나만 뒤집는다 — 숫자 → 방향 → 대비 순. (새 글, 종류, 원래, 바꾼 것)."""
    for kind in kinds:
        got = {"number": lambda: number_flip(text, avoid), "direction": lambda: antonym_flip(text),
               "contrast": lambda: contrast_swap(text)}[kind]()
        if got:
            return got[0], kind, got[1], got[2]
    return None
