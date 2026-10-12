"""
근거를 묻는 질문의 **이유 줄 · 배경 줄 · 대비 쌍** — 한 장의 절 구조와 말투로 코드가 가른다.

`_claim_rules`·`_evidence` 와 같은 자리다 — 기능 모듈이 아니라 유틸이라 F-26(대비·상관 주장), F-08(골자 검사·
「모르겠어요」 대비 쌍), F-09(채점 기준)가 같이 import 해도 정책 위반이 아니다 (DEV_POLICY §4-1). LLM 을 부르지 않는다.

왜 따로 두나 (09-30 실측, 부스 덱):
- 「…라고 결론지은 근거는 무엇인가요」 의 골자가 한 장의 **배경 절**(「01 현상은 실재한다 · 평균 N%p 낮음」)과
  **이유 절**(「02 원인은 X 가 아니다 · A 와 B 의 상관은 약함 · C 는 B 와 역상관」)을 섞었고, 가장 곧은 줄
  (「X 가 아니라 Y 가 결과를 갈랐다」)은 빠졌다. 골자 검사는 「자료에 있나」 만 보고 「이 질문에 답하나」 는 안 봤다.
- 「모르겠어요」 보기는 인용 한 줄의 낱말에서 뽑아서, 자료가 스스로 세운 대비(X 아니라 Y)를 모르면 둘 다 틀린 쌍이 나왔다.

규칙은 전부 **구조**다 — 절 제목(짧은 줄 + 글머리표 줄), 원인·이유 제목, 「아니라·아닌·보다 … 갈랐다」,
상관·역상관, 인과를 잇는 말, 질문과 겹치는 변별 낱말 수. 특정 발표의 낱말은 규칙에 없다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import _claim_rules as R
from ._evidence import clean_slide_text, page_marker_rows
from ._grounding import stem as _josa_stem

# ---------------------------------------------------------------------------
# 줄 모양 — 슬라이드 원문을 절(제목 + 글머리표) 단위로
# ---------------------------------------------------------------------------

#: 글머리표만 있는 줄 — 다음 줄이 그 글머리표의 글이다 (PPT 파싱이 표와 글을 따로 뽑는다).
_BULLET_ONLY_RE = re.compile(r"^[·•▪■◦∙*\-–—]+$")
#: 글머리표 줄. 「-」「*」 는 뒤에 빈칸이 있어야 한다 — 「−3.6%」 같은 음수를 글머리표로 읽지 않게.
_BULLET_RE = re.compile(r"^(?:[·•▪■◦∙]\s*|[*\-–—]\s+|[①-⑳]\s*|\(?\d{1,2}[.)]\s+)(?P<body>\S.*)$")
#: 절 번호 줄(「01」「02」「(2)」) — 절이 바뀐다는 표시. 그 밖의 쪽 번호 꼴(「3 / 12」「- 3 -」「p. 3」)은 F-26 과 같은 잣대로 버린다
#: (`_evidence.page_marker_rows`).
_MARKER_RE = re.compile(r"^\(?\d{1,2}\)?\.?$")
_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{3,}")
#: 줄이 이렇게 끝나면 다음 줄이 이어진다 (조사·관형형·쉼표) — 글상자 폭으로 꺾인 줄.
_CONT_END_RE = re.compile(r"(?:은|는|이|가|을|를|의|와|과|에|로|으로|에서|에게|한|된|인|하는|되는|하게|적인|및|,)$")
#: 문장이 끝난 줄 — 뒤에 오는 한 낱말은 이어진 줄이 아니다.
_END_RE = re.compile(r"(?:[.!?。]|다|요|죠|는가|은가|인가|던가|까)$")
#: 앞 줄이 안 끝났을 때 한 낱말 줄은 꺾여 내려온 낱말이다 (「낮음」「역상관」). 이보다 길면 새 줄로 본다.
WRAP_WORD_MAX = 6
#: 앞 줄이 조사·관형형으로 끝났을 때 이어 붙일 줄 길이 상한 — 꺾여 내려온 꼬리는 짧다(「27%로 하락」).
#: 긴 줄까지 이으면 「…원인」(명사 끝 「인」) 뒤의 날짜 줄이 붙는다 (09-30 실측, 표지).
WRAP_TAIL_MAX = 10
#: 앞 줄이 쉼표·「아니라」 로 끝나면 문장이 이어진다 — 뒤 절이 길어도 잇는다 (「핵심은 X가 아니라 ,」 / 「Y 다 .」).
WRAP_CLAUSE_MAX = 40
_OPEN_END_RE = re.compile(r"(?:,|아니라|아닌|보다)\s*$")
#: 절 제목으로 볼 길이 — 바로 밑에 글머리표 줄이 오는 짧은 줄.
HEAD_MAX = 24


@dataclass
class Unit:
    """장의 한 줄 (꺾인 줄은 이어 붙인 것). kind: heading · bullet · text · row. head 는 이 줄이 든 절의 제목."""
    slide_no: int
    text: str
    kind: str
    head: str = ""
    title: str = ""
    order: int = 0


def units(slide_no: int, raw_text: str) -> list[Unit]:
    """장 원문 → 줄 목록. 글머리표·꺾인 낱말·절 번호·절 제목을 읽는다."""
    items: list[list] = []            # [text, kind]
    pending = False
    cleaned = [clean_slide_text(raw).strip() for raw in (raw_text or "").split("\n")]
    pages = page_marker_rows(cleaned)
    for k, line in enumerate(cleaned):
        # 절 번호 꼴(「02」「(2)」)은 쪽 번호 잣대보다 먼저 절 번호로 읽는다 — 장 가운데의 「(2)」 를 쪽 번호로 버리면 두 절이 한 절이 된다
        if not line or (k in pages and not _MARKER_RE.match(line)):
            continue
        if _BULLET_ONLY_RE.match(line):
            pending = True
            continue
        if _MARKER_RE.match(line):
            items.append(["", "marker"])
            pending = False
            continue
        if line.startswith("|"):
            if not _TABLE_SEP_RE.match(line):
                items.append([line, "row"])
            continue
        m = _BULLET_RE.match(line)
        if m or pending:
            items.append([m.group("body").strip() if m else line, "bullet"])
            pending = False
            continue
        prev = items[-1] if items else None
        if prev and prev[1] in ("bullet", "text") and prev[0] and not _END_RE.search(prev[0]) and (
                (" " not in line and len(line) <= WRAP_WORD_MAX)
                or (len(line) <= WRAP_TAIL_MAX and _CONT_END_RE.search(prev[0]))
                or (len(line) <= WRAP_CLAUSE_MAX and _OPEN_END_RE.search(prev[0]))):
            prev[0] = f"{prev[0]} {line}"
            continue
        items.append([line, "text"])
    out: list[Unit] = []
    head = ""
    title = next((t for t, k in items if k == "text"), "")
    title = title if len(title) <= HEAD_MAX and not _END_RE.search(title) else ""
    for i, (text, kind) in enumerate(items):
        if kind == "marker":
            head = ""
            continue
        nxt = next((k for _, k in items[i + 1:] if k != "marker"), "")
        if kind == "text" and len(text) <= HEAD_MAX and (nxt == "bullet" or text.endswith(":")):
            head = text.rstrip(":").strip()
            out.append(Unit(slide_no, head, "heading", head, title, len(out)))
            continue
        out.append(Unit(slide_no, text, kind, head, title, len(out)))
    return out


# ---------------------------------------------------------------------------
# 줄의 말투 — 대비 · 상관 · 인과
# ---------------------------------------------------------------------------

#: 이유 절의 제목 — 원인·이유·요인·근거를 말하는 머리.
_REASON_HEAD_RE = re.compile(r"원인|이유|요인|근거|까닭|때문|비결|동인|메커니즘|(?<![가-힣])왜(?![가-힣])")
#: 배경 절·장의 제목 — 현상이 있다는 것(규모·현황)을 보이는 머리.
_BACKGROUND_HEAD_RE = re.compile(r"현황|배경|현상|실태|규모|개요|추이|문제\s*제기")
#: 상관을 말하는 줄. 약한 상관은 「원인이 아니다」 쪽 이유다.
_CORR_RE = re.compile(r"상관|비례|연관성|관련성")
_CORR_WEAK_RE = re.compile(r"(?:상관|연관성|관련성)\S*\s*(?:은|이)?\s*(?:약|낮|없|미미|거의\s*없)")
_CORR_INVERSE_RE = re.compile(r"역상관|반비례|음의\s*상관|부적\s*상관")
#: 원인과 결과를 잇는 말 (F-26 의 인과 잇는 말과 같은 꼴) — 바꾸는 동사만으로는 계획일 수 있어 넣지 않는다.
_CAUSE_LINK_RE = re.compile(
    r"때문|해서\s|하여|[가-힣](?:아|어)서\s|(?:으로|로)\s*인해|탓|수록|면서|원인|이유|결과로|결과적으로|일으|야기|유발|초래|"
    r"영향|좌우|이어지|이어집|이어져|가져오|가져와|→|->")
#: 결과를 가른 줄 — 「…가 결과를 갈랐다」「…가 성패를 좌우했다」. 목적어가 무엇이든 동사가 정한다.
_DECISIVE_RE = re.compile(r"(?:을|를)\s*(?:갈랐|가른|가릅|가르는|갈라|좌우|결정지|결정했|결정한|결정적)")
#: 결론을 여는 머리말.
_CONCLUDE_RE = re.compile(r"결론|요컨대|핵심은|정리하면|즉[,\s]")

#: 「X(이/가) 아니라[,] Y」 · 「X(이/가) 아닌 Y」 · 「X보다 Y(이/가) …(을/를) 갈랐다」.
_NOT_BUT_RE = re.compile(r"(?P<neg>[^,:;·—\-]+?)\s*아니라\s*[,]?\s*(?P<pos>.+)$")
_NOT_ADN_RE = re.compile(r"(?P<neg>[^,:;·—\-]+?)(?:이|가)\s+아닌\s+(?P<pos>.+)$")
_THAN_RE = re.compile(r"(?P<neg>[^,:;·—\-]+?)보다\s+(?:(?:더|오히려|훨씬)\s+)?(?P<pos>.+)$")
#: 대비 한쪽의 구절이 끝나는 낱말 — 서술어.
_PREDICATE_RE = re.compile(r"(?:다|요|니다|까|죠|음|함|됨|임)[.!?]?$")
#: 격조사가 붙은 낱말에서 구절이 끝난다 (「행동에서 만들어진다」 → 행동). 관형격 「의」 는 이어진다.
_CASE_END_RE = re.compile(r"(?:에서는|에서|으로|에게|부터|까지|처럼|은|는|이|가|을|를|에|로|도|만)$")
#: 구절 맨 앞의 주제어(「A는 X가 아니라 Y」 의 A는) — 부정된 것은 그 뒤다.
_TOPIC_RE = re.compile(r"(?:은|는)$")
#: 대비 쪽의 낱말 수 상한.
SIDE_WORDS_MAX = 3


_QUOTE_CHARS_RE = re.compile(r"[\"'“”‘’「」『』«»()\[\]]")
#: 활용형·관형형 꼬리 — 명사구의 끝이 못 된다.
#: 명사도 흔히 이렇게 끝나서(시간·공간·사진·제한) 두 글자 낱말은 활용형으로 보지 않는다 — 세 글자 이상만 (「만들어진」「중요한」).
_VERBAL_TAIL_RE = re.compile(r"(?:는|던|될|할|게)$|^[가-힣]{2,}(?:진|한|된|하|되)$")


#: 관형형 뒤에 오는 의존 명사 — 「…하는 게」「…한 것」.
_BOUND_HEADS = frozenset({"게", "것", "거", "수", "데", "바", "점", "줄", "것이", "것은", "게가"})
#: 관형형 낱말 — 앞 낱말의 주격 조사(「집중이 끊기는 횟수」)가 구절을 끝내지 않는다.
_ADNOMINAL_RE = re.compile(r"(?:는|은|던|[한된진운른간온난인할될])$")


def _copula_noun(word: str) -> str:
    """「속도다」「시간이다」「요인입니다」 → 명사. 활용형 서술어(「만들어진다」「늘린다」)면 ""."""
    if re.search(r"(?:이다|입니다|이에요)$", word):
        noun = re.sub(r"(?:이다|입니다|이에요)$", "", word)
    elif re.search(r"(?:다|예요)$", word) and len(word) >= 3:
        noun = re.sub(r"(?:다|예요)$", "", word)
        code = ord(noun[-1]) - 0xAC00
        if not (0 <= code < 11172) or code % 28:      # 받침 있는 글자 + 다 = 「늘린다」「높다」 꼴의 용언
            return ""
    else:
        return ""
    return noun if len(noun) >= 2 and not _VERBAL_TAIL_RE.search(noun) else ""


def _words(text: str) -> list[str]:
    text = _QUOTE_CHARS_RE.sub("", text or "")      # 「“더 참기”가」 → 「더 참기가」 — 조사가 떨어져 나가지 않게
    return [w.strip(" .,") for w in re.split(r"\s+", text.strip()) if w.strip(" .,")]


def _neg_side(text: str) -> str:
    # 따옴표 바로 뒤 조사는 떼고 본다 — 「“초”가 아니라」 의 부정된 쪽은 「초」 다 (따옴표를 먼저 지우면 「초가」 가 남는다)
    words = _words(re.sub(r"[”’」』\"'](?:이|가|은|는)\s*$", "", (text or "").strip()))
    # 주제어(「A는」)까지는 부정된 쪽이 아니다 — 마지막 주제어 뒤만 (「재이용률 하락은 대여소 부족이」 → 대여소 부족)
    # 뒤에 의존 명사가 오는 「…는」 은 관형형이다 (「시간을 훔치는 게」)
    # 목적어(「집중을 의지의 문제가 아니라」 의 「집중을」)도 부정된 쪽 밖이다.
    topic = max((i for i, w in enumerate(words[:-1])
                 if (_TOPIC_RE.search(w) and words[i + 1] not in _BOUND_HEADS) or re.search(r"[을를]$", w)), default=-1)
    words = words[topic + 1:][-SIDE_WORDS_MAX:]
    if not words:
        return ""
    # 끝 낱말의 주격·주제 조사를 뗀다 — 두 글자 낱말(「양이」)은 앞에 다른 낱말이 있을 때만 (「차이」 홀로면 명사일 수 있다)
    last = re.sub(r"(?:이|가|은|는)$", "", words[-1]) if (len(words[-1]) > 2 or len(words) > 1) else words[-1]
    return " ".join(words[:-1] + [last]).strip()


def _pos_side(text: str) -> str:
    words = _words(text)
    out: list[str] = []
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if _PREDICATE_RE.search(w) and out:
            noun = _copula_noun(w)
            if noun and (out[-1].endswith("의") or _ADNOMINAL_RE.search(out[-1]) or not _CASE_END_RE.search(out[-1])):
                out.append(noun)          # 「반납 경험의 문제다」 · 「…끊기는 횟수다」 · 「피드백 속도다」
            break
        # 관형절 — 「집중이 끊기는 횟수」: 주격 뒤 관형형, 관형형 뒤 명사로 머리 명사까지 간다
        if nxt and ((re.search(r"[이가]$", w) and _ADNOMINAL_RE.search(nxt) and not _PREDICATE_RE.search(nxt))
                    or (out and _ADNOMINAL_RE.search(w))):
            out.append(w)
            continue
        m = _CASE_END_RE.search(w)
        if m and nxt and len(w) - len(m.group(0)) >= 1:
            out.append(w[: -len(m.group(0))])
            break
        out.append(w)                    # 줄 끝 낱말은 조사를 떼지 않는다 — 「이해도」 의 「도」 는 조사가 아니다
        if len(out) >= SIDE_WORDS_MAX + 1:
            break
    while out and out[-1].endswith("의"):
        out.pop()
    return " ".join(out).strip()


def contrast_sides(line: str) -> tuple[str, str] | None:
    """
    줄이 세운 대비 → (부정된 쪽, 세운 쪽) 구절. 없으면 None.

    「결론: A는 X가 아니라 Y에서 온다」 → (X, Y) · 「X가 아닌 Y」 → (X, Y) · 「X보다 Y가 결과를 갈랐다」 → (X, Y).
    머리말(「결론:」)·주제어(「A는」)는 뗀다. 물음 줄은 대비가 아니다.
    """
    text = (line or "").strip()
    if not text or R.is_question(text):
        return None
    for rx, need_decisive in ((_NOT_BUT_RE, False), (_NOT_ADN_RE, False), (_THAN_RE, True)):
        m = rx.search(text)
        if not m:
            continue
        if need_decisive and not _DECISIVE_RE.search(m.group("pos")):
            continue
        neg, pos = _neg_side(m.group("neg")), _pos_side(m.group("pos"))
        if neg and pos and neg != pos:
            return neg, pos
    return None


def correlation(line: str) -> str:
    """상관을 말하는 줄이면 "weak" · "inverse" · "strong", 아니면 ""."""
    if not _CORR_RE.search(line or ""):
        return ""
    if _CORR_WEAK_RE.search(line):
        return "weak"
    return "inverse" if _CORR_INVERSE_RE.search(line) else "strong"


def reason_kind(line: str) -> str:
    """줄이 이유를 말하는 말투 — "contrast"(X 아니라 Y) · "correlation" · "cause" · ""."""
    if contrast_sides(line):
        return "contrast"
    if correlation(line):
        return "correlation"
    if _CAUSE_LINK_RE.search(line or "") or _DECISIVE_RE.search(line or ""):
        return "cause"
    return ""


def decisive(line: str) -> bool:
    """결과를 가른 줄 — 대비이거나 「…를 갈랐다·좌우했다」. 근거를 묻는 질문에 가장 곧은 답이다."""
    return bool(contrast_sides(line) or _DECISIVE_RE.search(line or ""))


def is_reason_head(text: str) -> bool:
    return bool(_REASON_HEAD_RE.search(text or ""))


_HANGUL_ANY_RE = re.compile(r"[가-힣]")


def role_of(unit: Unit, slide_units: list[Unit]) -> str:
    """
    줄의 쓰임 — "reason"(결론을 받치는 이유) · "background"(현상이 있다는 배경) · ""(모름).

    이유: 이유 절(제목에 원인·이유·요인·근거)의 줄과 그 제목, 절 밖의 이유 말투(대비·상관·인과) 줄.
    배경: 같은 장에 이유 절이 **있을 때** 그와 나란한 다른 절의 줄, 또는 절·장 제목이 현황·배경인 줄.
    같은 장에 이유 절이 있으면 **절이 말투보다 먼저다** — 배경 절의 「일부가 아닌 전반적 현상」 은 대비 말투여도
    현상이 넓다는 배경이다. 절 구조가 없는 장의 말투 없는 줄은 모른다("") — 배경이라고 단정하면 이유를 버린다.
    """
    if not _HANGUL_ANY_RE.search(unit.text):
        return ""                            # 영문 차트 설명(「→ interaction → analysis」)은 이유도 배경도 아니다
    if unit.head and any(is_reason_head(u.head) for u in slide_units):
        return "reason" if is_reason_head(unit.head) else "background"
    if reason_kind(unit.text):
        return "reason"
    if _BACKGROUND_HEAD_RE.search(unit.head or "") or _BACKGROUND_HEAD_RE.search(unit.title or ""):
        return "background"
    return ""


def has_reason_structure(raw_text: str, slide_no: int = 0) -> bool:
    """장에 이유 구조가 있는가 — 원인·이유 절, 또는 대비·상관 줄. 인과를 잇는 말 한 줄만으로는 아니다(어느 장에나 있다)."""
    return any(is_reason_head(u.head) or reason_kind(u.text) in ("contrast", "correlation")
               for u in units(slide_no, raw_text))


# ---------------------------------------------------------------------------
# 질문 — 근거를 묻는가
# ---------------------------------------------------------------------------

#: 근거·이유를 묻는 말. 「왜 중요한지」 는 중요성을 묻는 것이라 뺀다 — 그때는 규모·현황이 답이다.
_ASKS_REASON_RE = re.compile(
    r"근거|이유|(?<![가-힣])왜(?![가-힣])|어째서|무엇\s*때문|때문인|원인|결론(?:지|을\s*내|을\s*내린|에\s*이른)|"
    r"판단한|뒷받침|입증|증명|설명할\s*수\s*있")
_ASKS_IMPORTANCE_RE = re.compile(r"왜\s*중요|중요한\s*(?:이유|까닭)|중요성|의미(?:는|가)")
#: 해결·방법을 묻는 말 — 그때는 해결(solve) 주장도 이유로 본다.
_ASKS_REMEDY_RE = re.compile(r"방법|방안|대책|해결|어떻게\s*(?:줄|늘|막|풀|바꾸|개선)")


def asks_reason(question: str) -> bool:
    q = question or ""
    return bool(_ASKS_REASON_RE.search(q)) and not _ASKS_IMPORTANCE_RE.search(q)


def asks_remedy(question: str) -> bool:
    return bool(_ASKS_REMEDY_RE.search(question or ""))


# ---------------------------------------------------------------------------
# 낱말 겹침 — 조사를 떼고, 숫자는 따로
# ---------------------------------------------------------------------------

#: 질문 틀 낱말 — 어느 질문에나 있어 겹침으로 치지 않는다.
_FRAME = frozenset({
    "근거", "이유", "무엇", "무엇인가", "무엇인가요", "어떤", "어떻게", "왜", "결론", "결론지은", "결론을", "판단", "판단한",
    "설명", "설명해", "자료", "발표", "주장", "생각", "그렇게", "이렇게", "때문", "발생", "발생한다고", "말해요",
    "라고", "했는데", "있나요", "무엇인지", "구체적", "구체적으로", "근거는", "이유는",
})
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_HANGUL_RE = re.compile(r"^[가-힣]+$")


def tokens(text: str) -> set[str]:
    """변별 낱말(조사 뗀 줄기) + 숫자."""
    out = set()
    for t in R.content_tokens(text or ""):
        s = _josa_stem(t)
        if len(s) >= 2 and s not in _FRAME and t not in _FRAME:
            out.add(s)
    out |= {n for n in _NUM_RE.findall(text or "") if "." in n or len(n) >= 2}
    return out


def _tmatch(a: str, b: str) -> bool:
    if a == b:
        return True
    if _HANGUL_RE.match(a) and _HANGUL_RE.match(b) and min(len(a), len(b)) >= 2:
        return a in b or b in a
    return False


def overlap(a: str | set[str], b: str | set[str]) -> int:
    """a 의 낱말 가운데 b 에 (조사 떼고·포함으로) 있는 것의 수."""
    ta = a if isinstance(a, set) else tokens(a)
    tb = b if isinstance(b, set) else tokens(b)
    return sum(1 for x in ta if any(_tmatch(x, y) for y in tb))


def has_number(text: str) -> bool:
    return any("." in n or len(n) >= 2 for n in _NUM_RE.findall(text or ""))


# ---------------------------------------------------------------------------
# 근거 묶음 — 질문의 근거 장에서 결론 줄 · 이유 줄 · 배경 줄
# ---------------------------------------------------------------------------

#: 결론 줄로 볼 질문 겹침 — 질문 낱말의 이 비율 이상, 또는 이 수 이상.
CONCLUSION_SHARE = 0.6
CONCLUSION_MIN = 3
#: 골자에 다시 쓸 이유 줄 수. 셋이면 화면 한 칸(200자)에 들어간다.
REASON_GIST_LINES = 3
#: 골자 절이 자료 줄에 「닿았다」 고 볼 겹침.
CLAUSE_MATCH_MIN = 2


@dataclass
class Line:
    slide_no: int
    text: str
    role: str = ""
    kind: str = ""
    graph: bool = False
    conclusion: bool = False
    order: int = 0
    q_overlap: int = 0


@dataclass
class Evidence:
    """근거를 묻는 질문 하나의 재료. reasons 는 결론 줄을 뺀 이유 줄(좋은 순), strongest 는 그 맨 앞."""
    lines: list[Line] = field(default_factory=list)
    reasons: list[Line] = field(default_factory=list)
    background: list[Line] = field(default_factory=list)
    conclusion: Line | None = None

    @property
    def strongest(self) -> Line | None:
        return self.reasons[0] if self.reasons else None


def _same(a: str, b: str) -> bool:
    fa, fb = re.sub(r"\W+", "", a or ""), re.sub(r"\W+", "", b or "")
    return bool(fa) and bool(fb) and (fa == fb or (len(fb) >= 8 and fb in fa) or (len(fa) >= 8 and fa in fb))


def evidence(question: str, anchors: list[int], texts: dict[int, str],
             graph_lines: list[tuple[int, str, str]] | None = None) -> Evidence | None:
    """
    근거 장(anchors)에서 이 질문의 이유 줄 · 배경 줄 · 결론 줄. 이유 줄이 없으면 None.

    graph_lines 는 F-26 주장 그래프에서 이 질문의 개념에 닿은 대비·인과·비교(·해결) 주장의 인용 (장, 줄, kind) — 먼저 믿는다.
    그래프가 비었으면(09-29 부스 사진 덱: 주장 0개) 장의 절 구조·말투만으로 고른다.
    """
    q = tokens(question)
    lines: list[Line] = []
    for no in anchors:
        us = units(no, texts.get(no, ""))
        for u in us:
            kind = "heading" if u.kind == "heading" else (reason_kind(u.text) or u.kind)
            lines.append(Line(no, u.text, role_of(u, us), kind, order=len(lines),
                              q_overlap=overlap(q, u.text)))
    for no, quote, kind in graph_lines or []:
        if no not in anchors or not quote:
            continue
        hit = next((ln for ln in lines if ln.slide_no == no and _same(ln.text, quote)), None)
        if hit is None:
            hit = Line(no, quote, order=len(lines), q_overlap=overlap(q, quote))
            lines.append(hit)
        if kind == "compare" and hit.role == "background":
            continue       # 「A 대비 B」 비교 주장은 규모를 말하는 배경 줄에서 자주 나온다 — 절 구조가 배경이면 배경이다
        hit.role, hit.graph = "reason", True
        hit.kind = hit.kind if hit.kind in ("contrast", "correlation", "cause") else kind
    if not lines or not q:
        return None
    best = max(lines, key=lambda ln: (ln.q_overlap, ln.graph, -ln.order))
    need = min(CONCLUSION_MIN, max(2, round(len(q) * CONCLUSION_SHARE)))
    conclusion = best if best.q_overlap >= need else None
    if conclusion is not None and conclusion.role == "background":
        return None        # 질문이 되뇌는 것이 배경 줄이면 현상 자체의 근거를 묻는 것이다 — 그때는 규모·현황이 답이다
    # 질문을 그대로 되뇌는 줄은 결론의 다른 말이지 이유가 아니다 — 근거는 질문과 낱말이 적게 겹친다
    # (표지의 「A가 아니라 B의 문제다」 가 요약 장의 결론 줄과 같은 말을 한다).
    # 결론이 대비(「X 아니라 Y」)면 같은 Y 를 세운 다른 대비 줄도 결론의 다른 말이다 (표지 부제가 요약 장 결론을 되풀이한다).
    c_sides = contrast_sides(conclusion.text) if conclusion else None
    for ln in lines:
        l_sides = contrast_sides(ln.text) if c_sides and ln is not conclusion else None
        ln.conclusion = ln.q_overlap >= need or bool(l_sides and overlap(l_sides[1], c_sides[1]) >= 1)
    near = {ln.slide_no for ln in lines if ln.conclusion} or {ln.slide_no for ln in lines if ln.q_overlap >= 2}
    reasons = [ln for ln in lines if ln.role == "reason" and not ln.conclusion
               and (ln.graph or ln.slide_no in near or ln.q_overlap >= 1)]
    if not reasons:
        return None
    home = {conclusion.slide_no} if conclusion else near
    reasons.sort(key=lambda ln: (not decisive(ln.text), ln.slide_no not in home, not ln.graph, ln.kind == "heading",
                                 not (has_number(ln.text) or ln.kind in ("correlation", "cause")),
                                 -ln.q_overlap, ln.order))
    background = [ln for ln in lines if ln.role == "background" and not ln.conclusion]
    return Evidence(lines=lines, reasons=reasons, background=background, conclusion=conclusion)


# ---------------------------------------------------------------------------
# 골자 검사 — 절마다 어느 줄에 닿는가
# ---------------------------------------------------------------------------

_SENT_SPLIT_RE = re.compile(r"(?<=[.?!])\s+|(?<=요)\s+(?=[가-힣A-Z«「])")
#: 절 경계 — 쉼표, 가운뎃점, 연결 어미(고·며·면서·지만) 뒤 빈칸.
_CLAUSE_SEP_RE = re.compile(r",\s*|\s+·\s+|(?:(?<=[가-힣]고)|(?<=[가-힣]며)|(?<=면서)|(?<=지만)|(?<=는데)|(?<=으나))\s+")


def _clauses(sentence: str) -> list[tuple[int, str]]:
    """(시작 위치, 절) 목록."""
    out, start = [], 0
    for m in _CLAUSE_SEP_RE.finditer(sentence):
        if sentence[start:m.start()].strip():
            out.append((start, sentence[start:m.start()]))
        start = m.end()
    if sentence[start:].strip():
        out.append((start, sentence[start:]))
    return out


def clause_role(clause: str, ev: Evidence) -> str:
    """절이 닿은 자료 줄의 쓰임 — "conclusion" · "reason" · "background" · ""(어느 줄에도 뚜렷이 안 닿음)."""
    ct = tokens(clause)
    scored = [(overlap(ct, ln.text), ln) for ln in ev.lines]
    top = max((s for s, _ in scored), default=0)
    if top < CLAUSE_MATCH_MIN and not (top >= 1 and any(n in clause for n in _NUM_RE.findall(clause) if has_number(n))):
        return ""
    tied = [ln for s, ln in scored if s == top]
    if any(ln.conclusion for ln in tied):
        return "conclusion"
    if any(ln.role == "reason" for ln in tied):
        return "reason"
    if all(ln.role == "background" for ln in tied):
        return "background"
    return ""


def covers(text: str, line: str) -> bool:
    """글이 자료 줄 하나를 담았는가 — 줄 낱말의 절반 이상, 또는 둘 이상이 겹친다."""
    lt = tokens(line)
    got = overlap(lt, text)
    return bool(lt) and (got >= CLAUSE_MATCH_MIN or got * 2 >= len(lt))


def wrap_lines(lines: list[Line]) -> str:
    """자료 줄 그대로 이은 골자 — 「자료는 이렇게 말해요 — A · B (N장)」 (F-08 의 자료 줄 골자와 같은 꼴)."""
    nos = sorted({ln.slide_no for ln in lines})
    body = " · ".join(ln.text.rstrip(" .") for ln in lines)
    return f"자료는 이렇게 말해요 — {body} ({', '.join(str(n) for n in nos)}장)"


def check_gist(gist: str, ev: Evidence, limit: int = 200) -> tuple[str, list[str]]:
    """
    근거를 묻는 질문의 골자를 **이유로** 맞춘다 → (골자, 검사 이름).

    1. 문장을 절로 나눠 절마다 닿은 자료 줄을 본다. 배경 줄에만 닿은 절은 뺀다 — 문장 앞쪽 절이면 뒤쪽만 남기고,
       뒤쪽 절이면(남는 말이 어미로 끝나지 않는다) 문장째 뺀다 (gist_background_dropped).
    2. 남은 골자가 가장 곧은 이유 줄(결과를 가른 대비 줄)과 수치가 있는 이유 줄을 담지 않았으면 자료 줄 그대로 붙인다.
       남은 것이 없거나 붙여서 넘치면 이유 줄로 다시 쓴다 (gist_reason_rebuilt).
    """
    checks: list[str] = []
    kept: list[str] = []
    for sent in (s for s in _SENT_SPLIT_RE.split(gist or "") if s.strip()):
        parts = _clauses(sent)
        roles = [clause_role(c, ev) for _, c in parts]
        if "background" not in roles:
            kept.append(sent.strip())
            continue
        checks.append("gist_background_dropped")
        last_bg = max(i for i, r in enumerate(roles) if r == "background")
        rest = roles[last_bg + 1:]
        if rest and any(r in ("reason", "conclusion") for r in rest):
            kept.append(sent[parts[last_bg + 1][0]:].strip())
    need = [ev.strongest] if ev.strongest else []
    numeric = next((ln for ln in ev.reasons if has_number(ln.text)), None)
    if numeric is not None and numeric not in need:
        need.append(numeric)
    body = " ".join(kept).strip()
    missing = [ln for ln in need if not covers(body, ln.text)]
    if body and not missing:
        return body, sorted(set(checks))
    rebuilt = wrap_lines(missing) if body else ""
    if body and not re.search(r"[.?!]$", body):
        body += "."
    out = f"{body} {rebuilt}".strip() if body else ""
    if not out or len(out) > limit:
        lines = list(need)
        for ln in ev.reasons:
            if len(lines) >= REASON_GIST_LINES:
                break
            if ln not in lines:
                lines.append(ln)
        lines.sort(key=lambda ln: (ln is not ev.strongest, ln.order))
        out = wrap_lines(lines)
        while len(out) > limit and len(lines) > 1:
            lines = lines[:-1]
            out = wrap_lines(lines)
    return out, sorted(set(checks + ["gist_reason_rebuilt"]))


def part_role(part: str, ev: Evidence) -> str:
    """골자 요소 하나의 쓰임 — 요소 전체가 배경에만 닿으면 "background"."""
    roles = [clause_role(c, ev) for _, c in _clauses(part)]
    if roles and "background" in roles and not any(r in ("reason", "conclusion") for r in roles):
        return "background"
    return ""


# ---------------------------------------------------------------------------
# 「모르겠어요」 대비 쌍 — 자료가 세운 쪽이 정답
# ---------------------------------------------------------------------------

#: 보기가 못 되는 말 — 의문·정도 부사, 세는 단위.
_NOT_CHOICE = frozenset({"얼마", "얼마나", "어떻게", "무엇", "무엇을", "누가", "언제", "어디", "어디서", "어디에", "가장",
                         "매우", "더욱", "자주", "가지", "개", "명", "번", "것", "게", "수", "때", "경우", "정도", "부분", "쪽"})
#: 명사구 안에서는 괜찮은 의존 명사 — 「기능 수」「처리 건」.
_BOUND_IN_PHRASE = frozenset({"개", "명", "번", "수", "것", "게", "때", "경우", "정도", "부분", "쪽", "가지"})
#: 보기의 꼬리가 활용·물음꼴이면 명사구가 아니다 (「샀는가」「빌리느냐」「줄이는」).
_NOT_NOUN_END_RE = re.compile(r"(?:는가|은가|인가|는지|은지|느냐|으냐|냐|던가|하는|되는|하게|되게|하며|하고|해서|하여|했|었|았|였|니다|요|다)$")
#: 보기 하나의 최대 길이 (F-09 선택지 상한과 같다).
CHOICE_MAX = 24


def choice_term(phrase: str) -> str:
    """대비 쪽 구절 → 보기 낱말. 명사구가 아니면 ""."""
    words = _words(phrase)
    if not words or len(phrase) > CHOICE_MAX:
        return ""
    # 의존 명사·부사는 **홀로** 보기가 못 된다 (「'가지' 쪽인가요」) — 「기능 수」 처럼 명사구 안에 있으면 괜찮다
    if len(words) == 1 and words[0] in _NOT_CHOICE:
        return ""
    for w in words:
        if w in _NOT_CHOICE - _BOUND_IN_PHRASE or _NOT_NOUN_END_RE.search(w) or re.fullmatch(r"[\d.%]+", w):
            return ""
    # 앞 낱말에 격조사가 붙었으면 절이다 (「시간을 훔치는 게」) — 관형격 「의」 만 명사구 안에 온다
    if any(_CASE_END_RE.search(w) and not w.endswith("의") for w in words[:-1]):
        return ""
    last = words[-1]
    if last.endswith("의") or _VERBAL_TAIL_RE.search(last):
        return ""
    # 조사는 대비 쪽 구절을 뽑을 때 이미 뗐다 — 여기서 또 떼면 「이해도」 의 「도」 가 떨어진다
    term = " ".join(words)
    return term if len(re.sub(r"\s", "", term)) >= 2 else ""


def choice_pair(line: str) -> tuple[str, str] | None:
    """줄의 대비 → (세운 쪽, 부정된 쪽) 보기. 둘 다 명사구여야 한다."""
    sides = contrast_sides(line)
    if not sides:
        return None
    neg, pos = choice_term(sides[0]), choice_term(sides[1])
    if not neg or not pos or neg == pos or neg in pos or pos in neg:
        return None
    return pos, neg


# ---------------------------------------------------------------------------
# 그래프 먼저 — F-26 주장에서 질문의 개념에 닿은 이유·대비
# ---------------------------------------------------------------------------

#: 근거 질문의 이유로 읽는 주장 종류. 해결·방법을 물으면 solve 도 본다.
REASON_KINDS = ("cause", "contrast", "compare")


def _family(node_id: str, nodes) -> set[str]:
    """질문의 개념과 그 자식 개념 — 「이 개념에 닿은 주장」 의 범위."""
    return {node_id} | {n.id for n in nodes or [] if getattr(n, "parent_id", None) == node_id}


def graph_lines(claims, node_id: str, nodes, question: str, anchors: list[int],
                remedy: bool = False) -> list[tuple[int, str, str]]:
    """
    주장 그래프에서 이 질문의 이유 줄 후보 (장, 인용, kind). 주장의 주어·목적어가 질문의 개념(또는 그 자식)이거나,
    인용 줄이 질문과 변별 낱말 둘 이상을 나눌 때. 근거 장(anchors) 밖의 인용은 뺀다 — 질문이 가리킨 자리가 아니다.
    """
    if claims is None:
        return []
    kinds = set(REASON_KINDS) | ({"solve"} if remedy else set())
    fam = _family(node_id, nodes)
    q = tokens(question)
    out: list[tuple[int, str, str]] = []
    for c in getattr(claims, "claims", []) or []:
        if c.kind not in kinds:
            continue
        touches = c.subject_id in fam or any(o in fam for o in c.object_ids)
        for e in c.evidence:
            if e.slide_no in anchors and e.quote and (touches or overlap(q, e.quote) >= CLAUSE_MATCH_MIN):
                out.append((e.slide_no, e.quote, c.kind))
    return out


@dataclass
class ContrastChoice:
    affirmed: str
    negated: str
    slide_no: int
    quote: str
    source: str        # "graph" (F-26 대비 주장) · "line" (근거 장의 대비 줄)


def contrast_choice(claims, node_id: str, nodes, question: str, anchors: list[int], texts: dict[int, str],
                    evidence_quote: str = "", evidence_slide: int = 0, quote_only: bool = False) -> ContrastChoice | None:
    """
    「모르겠어요」 보기 쌍 — 자료가 **스스로 세운** 대비 (세운 쪽이 정답, 부정한 쪽이 오답).

    1. 그래프: F-26 대비 주장 가운데 질문의 개념(·자식)에 닿았거나, 인용이 질문의 힌트 인용이거나, 질문과 변별 낱말 둘 이상을
       나누는 것. 쪽의 방향은 주장이 아니라 **줄의 문법**(아니라 앞/뒤)이 정한다 — LLM 이 적은 contrast 는 대칭(A↔B)이라 방향이 없다.
    2. 줄: 그래프가 비었거나(부스 사진 덱) 대비 노드가 없으면, 근거 장의 대비 줄 가운데 힌트 인용이거나 질문과 둘 이상 겹치는 것.
    보기 둘 다 명사구가 아니면(「무엇을 샀는가」) 쓰지 않는다 — 그때는 F-09 가 인용 한 줄의 대비(aadf68f)·빈칸으로 간다.
    quote_only 면 힌트 인용 줄의 대비만 — 탐침 질문은 따져 묻는 줄이 따로 있어 옆 장의 대비로 새지 않는다.
    """
    q = tokens(question)
    fam = _family(node_id, nodes)
    scope = set(anchors) | ({evidence_slide} if evidence_slide else set())
    cands: list[tuple[tuple, ContrastChoice]] = []
    for c in getattr(claims, "claims", None) or []:
        if c.kind != "contrast":
            continue
        touches = c.subject_id in fam or any(o in fam for o in c.object_ids)
        for e in c.evidence:
            pair = choice_pair(e.quote)
            if not pair or e.slide_no not in scope:
                continue
            is_quote = _same(e.quote, evidence_quote)
            ov = overlap(q, e.quote)
            if quote_only and not is_quote:
                continue
            if touches or is_quote or ov >= CLAUSE_MATCH_MIN:
                cands.append(((0, not (is_quote or ov >= CONCLUSION_MIN), not touches, -ov),
                              ContrastChoice(pair[0], pair[1], e.slide_no, e.quote, "graph")))
    for no in sorted(scope):
        for u in units(no, texts.get(no, "")):
            pair = choice_pair(u.text)
            if not pair:
                continue
            is_quote = _same(u.text, evidence_quote)
            ov = overlap(q, u.text)
            if quote_only and not is_quote:
                continue
            if is_quote or ov >= CLAUSE_MATCH_MIN:
                # 질문이 되뇌는 결론 줄(겹침 CONCLUSION_MIN+)은 힌트 인용과 같은 무게다 — 근거 질문은 그 결론의 대비를 묻는다
                cands.append(((1, not (is_quote or ov >= CONCLUSION_MIN), True, -ov),
                              ContrastChoice(pair[0], pair[1], no, u.text, "line")))
    return min(cands, key=lambda c: c[0])[1] if cands else None
