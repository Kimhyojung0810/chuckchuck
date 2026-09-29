"""
발화(받아쓰기 글)를 **문장 단위로** 읽는 공용 유틸 — F-11 정합·F-17 시간 배분이 같이 쓴다.
기능 모듈(fXX_*)이 아니라 유틸이라 어느 모듈에서 import 해도 정책 위반이 아니다 (DEV_POLICY §4-1, `_match`·`_deck_claims` 와 같은 자리).

09-30 held-out 감사 C-06(혈당 녹음 — 3장은 「시간 관계상 그냥 넘어갈게요」, 6장 29% 를 「49퍼센트」로 말함)에서
녹음 경로가 세 가지를 못 읽었다.

1. 건너뛴다는 말 「음 이건 혈당 부하 계산식인데요, 시간 관계상 그냥 넘어갈게요.」 이 그 장 개념 둘의 **정합 근거**가 됐다.
   → `skip_cue` : 이 문장은 어떤 개념의 근거도 될 수 없고, 그 장은 「말로 건너뛴 장」 이다.
2. 인용 창(24어절)이 **두 장의 발화를 이어 붙여** 「…먹었느냐보다 그러니까 졸린 건 …」 같은 가짜 인용이 정합 근거가 됐다.
   → `utterances` : 문장은 한 장·한 구간(SlideSpeech) 안에서만 나온다. 구간을 넘는 문장은 만들지 않는다.
3. 받아쓰기는 수·% 를 말로 적는다(「49퍼센트」「이십구 프로」「3천 원」). 자료 숫자(29%)와 같은 자로 견주지 못했다.
   → `spoken_numbers` : 「49%」「29%」「3000원」 으로. 한 글자 수(「오 분」「이 명」)는 「이 사람」 과 못 가려 바꾸지 않는다.

규칙은 한국어 발표 말투의 **구조**로만 짠다 — 특정 발표·분야의 낱말을 넣지 않는다 (부스에는 처음 보는 자료가 온다).
놓치는 쪽이 안전하다: 건너뛰기를 잘못 잡으면 설명한 장이 「건너뛴 장」 이 되고, 숫자를 잘못 바꾸면 없던 모순이 생긴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ._deck_claims import content_stems
from .contracts import Transcript

__all__ = ["Utterance", "utterances", "split_sentences", "skip_cue", "defer_cue", "skip_targets",
           "spoken_numbers", "same", "hit", "count_hits"]


# ---------------------------------------------------------------------------
# 문장 — 한 구간 안에서만
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Utterance:
    """발화 문장 하나. seg 는 Transcript.by_slide 안의 구간 번호 — 인용은 같은 seg 안에서만 잇는다."""

    slide_no: int
    seg: int
    idx: int                  # 구간 안 문장 순번
    text: str
    start_sec: float | None = None
    end_sec: float | None = None
    skip: bool = False        # 건너뛰기 말인가 (`skip_cue`) — 그 장은 말로 건너뛴 장이다
    defer: bool = False       # 미루는 말인가 (`defer_cue`) — 근거는 아니지만 장을 건너뛴 것도 아니다


#: 문장 부호 뒤 공백 — 소수점(3.5)은 끝이 아니다.
_PUNCT_SPLIT_RE = re.compile(r"(?<=[.?!。])(?!\d)\s+")
#: 부호 없는 받아쓰기(A.X STT 는 마침표를 거의 안 찍는다)의 종결 어절. 「필요·중요·수요」 처럼 요로 끝나는 명사를 안 자르게
#: 요 앞 글자를 활용 모음으로 묶는다. 「…인데요,」 는 연결이라 자르지 않는다 — 「…계산식인데요, 시간 관계상 넘어갈게요」 가
#: 한 문장이어야 앞 반쪽이 개념의 근거로 떨어져 나가지 않는다.
_ENDING_WORD_RE = re.compile(
    r"(?:니다|[어아여해돼예에네군죠까래게세지워와봐줘꿔져쳐셔려겨고든]요|죠|[했였었았한된인]다)[.?!]?$"
)
#: 이 어절 수보다 긴 조각만 종결 어미로 한 번 더 자른다 — 부호가 있는 받아쓰기의 문장은 대개 이보다 짧다.
LONG_PIECE_WORDS = 20


def split_sentences(text: str) -> list[str]:
    """문장 부호로 자르고, 부호 없이 긴 조각은 종결 어절에서 한 번 더 자른다."""
    out: list[str] = []
    for piece in _PUNCT_SPLIT_RE.split((text or "").strip()):
        words = piece.split()
        if not words:
            continue
        if len(words) <= LONG_PIECE_WORDS:
            out.append(" ".join(words))
            continue
        cur: list[str] = []
        for w in words:
            cur.append(w)
            if _ENDING_WORD_RE.search(w):
                out.append(" ".join(cur))
                cur = []
        if cur:
            out.append(" ".join(cur))
    return out


def utterances(transcript: Transcript) -> list[Utterance]:
    """
    Transcript → 문장 목록 (말한 순서). 구간(SlideSpeech)을 넘는 문장은 없다.

    구간에 낱말 시각(words)이 있고 글과 어절 수가 맞으면 문장 시각을 낱말에서 잡고, 아니면 구간 길이를 어절 수로 나눈다
    (프런트 slimTranscript 는 by_slide 의 words 를 뺀다).
    """
    segs = list(transcript.by_slide)
    if not segs and (transcript.full_text or "").strip():
        # 장 구분이 없는 받아쓰기 — 통째로 한 구간(0장)이다
        from .contracts import SlideSpeech
        segs = [SlideSpeech(slide_no=0, visit=1, start_sec=0.0, end_sec=float(transcript.duration_sec or 0.0),
                            text=transcript.full_text, words=list(transcript.words))]
    # 구간에 낱말이 없으면(프런트가 뺐다) 전체 낱말을 어절 수대로 차례로 나눠 준다 — split_by_slide 는 낱말을 순서대로
    # 구간에 담고 글을 낱말로 이어 만들므로, 어절 수 합이 맞으면 구간 경계가 그대로 되살아난다.
    seg_words: list[list] = [list(s.words) for s in segs]
    counts = [len((s.text or "").split()) for s in segs]
    if segs and not any(seg_words) and transcript.words and sum(counts) == len(transcript.words):
        k = 0
        for i, n in enumerate(counts):
            seg_words[i] = list(transcript.words[k:k + n])
            k += n
    out: list[Utterance] = []
    for seg_no, seg in enumerate(segs):
        sents = split_sentences(seg.text)
        if not sents:
            continue
        n_words = sum(len(s.split()) for s in sents)
        words = seg_words[seg_no]
        timed = bool(words) and len(words) == n_words
        span = max(0.0, float(seg.end_sec) - float(seg.start_sec))
        k = 0
        for i, sent in enumerate(sents):
            n = len(sent.split())
            if timed:
                start, end = words[k].start_sec, words[k + n - 1].end_sec
            elif span > 0 and n_words:
                start = seg.start_sec + span * k / n_words
                end = seg.start_sec + span * (k + n) / n_words
            else:
                start = end = None
            out.append(Utterance(seg.slide_no, seg_no, i, sent,
                                 None if start is None else round(start, 2),
                                 None if end is None else round(end, 2),
                                 skip_cue(sent), defer_cue(sent)))
            k += n
    return out


# ---------------------------------------------------------------------------
# 건너뛰기 말
# ---------------------------------------------------------------------------

#: 건너뛰기 동사를 **발표자가 지금 하겠다는 꼴**로 쓴 것 — 「건너뛸게요·생략하겠습니다·넘어갈게요·넘깁니다」.
#: 「아침을 건너뛰면」「광고를 스킵하면」「패스해서 골을」「그냥 넘어가면 큰일」 은 발표 **내용**이지 건너뛰는 말이 아니다.
_SKIP_INTENT_RE = re.compile(
    r"(?:건너\s?뛸|생략할|스킵할|패스할|넘어\s?갈|넘길)\s?(?:게|께)"
    r"|(?:건너\s?뛰|생략하|스킵하|패스하|넘어\s?가|넘기)(?:겠|죠|도록)"
    r"|(?:건너\s?뜁|생략합|스킵합|패스합|넘어\s?갑|넘깁)(?:시다|니다)"
)
#: 이어 가는 꼴(「…건너뛰고 결론만」「…넘어가고」) — 건너뛰는 대상이 이 자리(이건·이 부분은·자세한 건)일 때만 건너뛰기다.
_SKIP_CONNECT_RE = re.compile(r"(?:건너\s?뛰|생략하|스킵하|패스하|넘어\s?가|넘기)고(?=[\s,.]|$)")
#: 이것만으로 「설명을 건너뛴다」 는 뜻인 동사 — 넘어가다·넘기다는 「다음으로 넘어갈게요」(전환)에도 쓴다.
_SKIP_VERB_RE = re.compile(r"건너\s?뛰|건너\s?뛸|건너\s?뜁|생략|스킵|패스")
#: 넘어가기를 건너뛰기로 만드는 센 표지 — 설명을 하지 않는다는 말. 전환 표지(다음으로)가 같이 있어도 건너뛰기다.
_SKIP_STRONG_RE = re.compile(
    r"그냥|시간\s?관계|시간상|시간이\s?(?:없|부족|모자)|자세(?:히|한)|설명\s?(?:없이|은\s?(?:안|못|생략)|하지|안\s?하|은\s?빼)"
)
#: 약한 표지 — 이 장·이 부분을 주제로 세운 말(「이건 …넘어갈게요」). 전환 표지가 있으면 건너뛰기가 아니다(「이건 다음 장에서」).
_SKIP_TOPIC_RE = re.compile(
    r"(?:^|\s)(?:음\s)?(?:이건|이거는|이것은|요건|얘는|여기는|이\s?부분은|이\s?장은|이\s?슬라이드는|이\s?표는|이\s?식은|"
    r"이\s?그래프는|이\s?과정은|이\s?내용은|설명은)"
)
#: 다음 장으로 넘어가는 전환 — 「다음으로 넘어갈게요」「다음 장 볼게요」.
_TRANSITION_RE = re.compile(r"다음\s?(?:으로|장|슬라이드|내용|페이지|주제|부분)")
#: 넘어가기 **전에** · 여기까지 하고 넘어가기 — 설명을 마친 뒤의 말이다.
_BEFORE_MOVE_RE = re.compile(r"넘어\s?가기\s?전|넘어가기에\s?앞서|여기까지")

# --- 빼기·안 다루기 (09-30 녹음 감사 REC-12) -----------------------------------------------------------------
# 「예외인 경우는 오늘은 빼고 바로 결론으로 가겠습니다」「여기는 제외하고」「이 부분은 오늘 다루지 않을게요」「이 장은 오늘은 안 볼게요」 —
# 닫힌 동사 목록(건너뛰·생략·스킵·패스·넘어가·넘기)에 없어 건너뛴 장이 비고, 정합 LLM 은 「정당한 생략」 을 줬다.
# 이 동사들은 발표 **내용**에도 흔하다(「설탕을 빼고 만들면」「흡연자는 제외하고 분석했어요」「그 연구는 청소년을 다루지 않았어요」) —
# 그래서 ① 지금 하겠다는 꼴(빼고·빼겠·뺄게·제외하고·다루지 않을게…)이고 ② 빼는 것이 **발표의 이 자리**일 때만 건너뛰기다:
# 가리키는 말(이 장·이 부분·여기는·이건 — `_SKIP_TOPIC_RE`), 발표의 한 자리를 이르는 화제(「…경우는」「예외는」「나머지는」「설명은」),
# 또는 「오늘은」 + 목적어 없이 빼는 말(「오늘은 빼고」 — 「오늘은 설탕을 빼고」 는 내용이다).
#: 지금 하겠다는 꼴 그 자체 — 「빼겠습니다·뺄게요·제외할게요·다루지 않을게요·안 볼게요·설명은 안 할게요」.
_SKIP_REMOVE_INTENT_RE = re.compile(
    r"(?:빼|제외하)(?:겠|도록)|(?:뺄|제외할)\s?(?:게|께)|(?:뺍|제외합)(?:시다|니다)"
    r"|다루지\s?않(?:을\s?(?:게|께|거)|겠)|안\s?다(?:룰\s?(?:게|께)|루겠)"
    r"|안\s?(?:볼\s?(?:게|께)|보겠)|보지\s?않(?:을\s?(?:게|께)|겠)"
    r"|설명(?:은|을|도)?\s?(?:안|못)\s?(?:할\s?(?:게|께)|하겠|드릴\s?(?:게|께)|드리겠|해\s?드릴\s?(?:게|께))"
    # 「설명드리지 않겠습니다」「설명해 드리지 않을게요」 — 드리다(하다·주다의 낮춤)도 같은 말이다 (held-out 지하철 덱)
    r"|설명(?:은|을|도)?\s?(?:해\s?)?(?:하|드리)지\s?않(?:을\s?(?:게|께)|겠)"
)
#: 이어 가는 꼴 — 「빼고·제외하고·다루지 않고·설명 안 하고」. 뒤 서술이 **발표자가 지금 하겠다는 말**(갈게요·말씀드릴게요·가겠습니다)일 때만
#: 건너뛰기다 — 「이 부분은 제외하고 계산했어요」 는 분석 방법(내용)이다.
_SKIP_REMOVE_CONNECT_RE = re.compile(
    r"(?:빼|제외하)고(?=[\s,.]|$)|다루지\s?않고(?=[\s,.]|$)|설명(?:은|을|도)?\s?(?:안|못)\s?하고(?=[\s,.]|$)"
    r"|설명(?:은|을|도)?\s?하지\s?않고(?=[\s,.]|$)"
)
#: 발표자가 지금 하겠다는 끝맺음 — 「-ㄹ게(요)」(받침 ㄹ + 게), 「-겠습니다/-겠어요」, 「-(ㅂ)시다」.
_PROMISSIVE_RE = re.compile(r"([가-힣])\s?[게께]요?(?=[\s.,!?]|$)")
_WILL_RE = re.compile(r"겠(?:습니다|어요|죠)|(?:합|갑|봅|넘어갑)시다")


def _speaker_intent(s: str) -> bool:
    """문장이 발표자가 지금 하겠다는 말로 끝맺는가 (「…결론으로 가겠습니다」「…결론만 말씀드릴게요」)."""
    if _WILL_RE.search(s):
        return True
    return any((ord(m.group(1)) - 0xAC00) % 28 == 8 for m in _PROMISSIVE_RE.finditer(s))   # 받침 ㄹ + 게
#: 발표의 한 자리를 이르는 화제 — 「예외인 경우는」「나머지는」「자세한 설명은」.
_SKIP_META_TOPIC_RE = re.compile(
    r"(?:경우|예외|나머지|사례|부분|내용|설명|계산|공식|과정|얘기|이야기|세부|자세한\s?(?:건|것|내용|설명))(?:는|은|도)(?=\s|$)"
)
_SKIP_TODAY_RE = re.compile(r"(?:^|\s)오늘은(?=\s|$)")


def _skip_removal(s: str) -> bool:
    """빼기·안 다루기 동사가 **발표의 이 자리**를 빼는 말인가 (위 주석)."""
    m = _SKIP_REMOVE_INTENT_RE.search(s)
    if m is None:
        m = _SKIP_REMOVE_CONNECT_RE.search(s)
        if m is None or not _speaker_intent(s[m.end():]):
            return False
    if _SKIP_TOPIC_RE.search(s) or _SKIP_META_TOPIC_RE.search(s):
        return True
    if not _SKIP_TODAY_RE.search(s):
        return False
    before = s[:m.start()].split()
    return not (before and re.search(r"(?:을|를)$", before[-1]))       # 「오늘은 설탕을 빼고」 는 내용이다


# --- 제쳐 두기 · 발표 밖으로 미루기 (held-out 2차) ---------------------------------------------------------------
# 「주차별 실천율 표는 오늘은 제쳐 두고, 설문 얘기로 바로 갈게요」「이 장은 접어 두겠습니다」 — 두다 앞의 「제쳐·접어·덮어·미뤄」 는
# 설명을 치워 두는 말이다. 「모바일 수납 시범 결과는 궁금하신 분만 발표 끝나고 따로 물어봐 주세요」「나눠 드린 자료에 다 적어 뒀으니까」 —
# 발표 **밖**(끝난 뒤·따로·나눠 준 자료)으로 미루면 발표에서는 건너뛴 것이다(「나중에 설명할게요」 는 발표 안에서 미루는 말 — `defer_cue`).
# 어느 쪽이든 **무엇을** 넘기는지 화제(「…표는」「…결과는」「이 장은」)로 세운 말이어야 한다 — 「우산을 접어 두고」 는 내용이다.
_SKIP_SET_ASIDE_RE = re.compile(r"(?:제쳐|접어|덮어|미뤄)\s?(?:두겠|둘\s?(?:게|께)|둡니다|두죠|두고(?=[\s,.]|$))")
#: 발표 뒤로 미루는 말 — 뒤에 묻기·알려 주기 말이 와야 한다. 「질문은 발표 끝나고 받을게요」(묻고 답하는 때)·「봉사자들은 발표 끝나고
#: 남아 주세요」 는 내용을 넘기는 말이 아니다. 「따로」 만으로는 발표 밖인지 모른다(「따로 한 장으로 설명드릴게요」) — 듣는 이가 따로 묻는 말만.
_SKIP_AFTER_TALK_RE = re.compile(
    r"(?:발표\s?(?:끝나고|끝난\s?(?:뒤|후)에?|후에|마치고|마친\s?(?:뒤|후)에?)|끝나고\s?따로)\s?"
    r"(?:[가-힣]+\s)?(?:물어|질문해|여쭤|말씀|설명|얘기|이야기|알려|보여|보내)"
    r"|따로\s?(?:물어|질문해|여쭤)"
)
#: 나눠 준 자료로 미루는 말 — 뒤에 담겨 있다·보라는 말이 와야 한다(「오늘 나눠 드린 자료는 발표 뒤에 걷어 갈게요」 는 아니다).
_SKIP_HANDOUT_RE = re.compile(
    r"(?:나눠\s?드린|배포한|배포해\s?드린|첨부한|공유한|보내\s?드린)\s?자료(?:\s?[가-힣]+)?\s?"
    r"(?:[가-힣]+\s)?(?:적어|있|나와|정리|담아|실어|참고|보시|보세요|보면|확인)"
)
#: 화제로 세운 말(「…결과는」「…통계 표는」) — 무엇을 치워 두는지 말한 자리다. 한 글자 명사는 자료의 한 부분을 이르는 말(표·식·값·글)만.
_TOPIC_WORD_RE = re.compile(r"(?:[가-힣]{2,}|(?<=\s)(?:표|식|값|글))(?:은|는)(?=\s|$)")
#: 화제 꼴이지만 넘기는 **내용**이 아닌 말 — 때·차례(「오늘은」「다음은」)와 묻고 답하는 때(「질문은 발표 끝나고」).
_NOT_SKIPPED_TOPIC_RE = re.compile(
    r"^(?:오늘|다음|그다음|지금|이번엔|이번에|우선|먼저|일단|저|제|저희|우리|질문|질의|문의|궁금한\s?점)(?:은|는)$"
)


def _topic_before(s: str, end: int) -> bool:
    """end 앞에 넘기는 내용을 화제로 세운 말이 있는가 (위 주석)."""
    if _SKIP_TOPIC_RE.search(s[:end]):
        return True
    return any(not _NOT_SKIPPED_TOPIC_RE.match(m.group(0)) for m in _TOPIC_WORD_RE.finditer(s[:end]))


def _skip_set_aside(s: str) -> bool:
    """제쳐 두기·발표 밖으로 미루기로 이 자리를 넘기는 말인가 (위 주석)."""
    m = _SKIP_SET_ASIDE_RE.search(s)
    if m is not None:
        return _topic_before(s, m.start()) and (not m.group(0).endswith("고") or _speaker_intent(s[m.end():]))
    m = _SKIP_AFTER_TALK_RE.search(s) or _SKIP_HANDOUT_RE.search(s)
    return m is not None and _topic_before(s, m.start())


def skip_cue(sentence: str) -> bool:
    """발표자가 이 자리의 내용을 **설명하지 않고 넘긴다**고 말한 문장인가."""
    s = " ".join((sentence or "").split())
    if not s or _BEFORE_MOVE_RE.search(s):
        return False
    if _skip_removal(s) or _skip_set_aside(s):
        return True
    intent = _SKIP_INTENT_RE.search(s)
    connect = None if intent else _SKIP_CONNECT_RE.search(s)
    verb = intent or connect
    if verb is None:
        return False
    strong_verb = bool(_SKIP_VERB_RE.search(verb.group(0)))
    marked = bool(_SKIP_STRONG_RE.search(s))
    topic = bool(_SKIP_TOPIC_RE.search(s))
    if intent and strong_verb:
        return True                                   # 「건너뛸게요」「생략하겠습니다」
    if connect:
        return marked or topic                         # 「이 과정은 건너뛰고 …」「자세한 설명은 생략하고 …」
    if marked:
        return True                                   # 「시간 관계상 그냥 넘어갈게요」
    return topic and not _TRANSITION_RE.search(s)     # 「이건 넘어갈게요」 (「이건 다음 장에서」 는 아니다)


#: 미루는 말 — 「이건 나중에 설명할게요」「뒤에서 자세히 볼게요」. 이름을 불러도 설명한 게 아니다.
_DEFER_RE = re.compile(
    r"(?:나중에|이따가?|뒤에서|잠시\s?후에?|다음\s?기회에|질문\s?때|질의응답\s?때)\s?(?:\S+\s){0,3}?\S*"
    r"(?:설명|말씀|다루|다룰|볼게|보겠|얘기|이야기)"
)


def defer_cue(sentence: str) -> bool:
    """설명을 **뒤로 미룬다**고 말한 문장인가 — 근거로 쓰지 않는다 (장을 건너뛴 것은 아니다)."""
    return bool(_DEFER_RE.search(" ".join((sentence or "").split())))


# ---------------------------------------------------------------------------
# 줄기 대조 — `_deck_claims` 의 규칙과 같게 (조사 뗀 줄기, 한글은 앞머리 일치, 두 글자 이상)
# ---------------------------------------------------------------------------

def same(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) < 2 or len(b) < 2 or not (a[0] >= "가" and b[0] >= "가"):
        return False
    return a.startswith(b) or b.startswith(a)


def hit(stems, stem: str) -> bool:
    return any(same(stem, s) for s in stems)


def count_hits(wanted, have) -> int:
    """wanted 줄기 중 have 에 있는 것의 수 (중복은 한 번)."""
    return sum(1 for s in dict.fromkeys(wanted) if hit(have, s))


# ---------------------------------------------------------------------------
# 건너뛴 장
# ---------------------------------------------------------------------------

#: 건너뛰기 말 자체의 낱말 — 어느 장을 건너뛰는지 가를 때 뺀다 (「시간」 은 수면 발표 본문에도 있다).
_SKIP_WORD_HEADS = ("시간", "관계", "그냥", "넘어", "넘기", "넘겨", "건너", "생략", "스킵", "패스", "자세", "설명", "이건",
                    "이거", "여기", "부분", "다음", "빼고", "빼겠", "뺄게", "제외", "다루", "오늘", "경우", "나머지",
                    # 건너뛰고 **할 일** — 「바로 정리할게요」「마무리할게요」 는 마지막 장(정리·결론)의 낱말이지 건너뛴 장이 아니다
                    "바로", "정리", "마무리", "요약", "결론")
#: 건너뛰고 **가는 곳** — 「바로 결론으로 가겠습니다」「결과로 넘어갈게요」 의 결론·결과는 건너뛴 장이 아니라 다음 장의 낱말이다.
_SKIP_DESTINATION_RE = re.compile(r"\S+(?:으로|로)\s+(?:바로\s+)?(?:가|갈|갑|가겠|넘어가|넘어갈|넘어갑|넘기|넘길|넘깁|이동)\S*")


#: 건너뛰는 말이 부르는 장의 **꼴** — 식(= 와 연산 기호) · 표(| 행) · 그래프·그림.
_SHAPE_WORDS = (
    (re.compile(r"(?:계산)?식|공식|수식|계산법"), re.compile(r"=.*[×÷+\-−*/]|[×÷+\-−*/].*=")),
    (re.compile(r"(?:^|\s)(?:이\s?)?표(?:는|를|가|도|에|$|\s)|도표"), re.compile(r"^\s*\|.*\|", re.M)),
    (re.compile(r"그래프|차트|그림|사진"), re.compile(r"!\[|Chart Type|\bchart\b", re.I)),
)


def _slide_has_shape(slide_text: str, cue: str) -> bool:
    """건너뛰는 말이 부른 꼴(식·표·그래프)이 이 장에 있는가."""
    return any(word.search(cue) and shape.search(slide_text or "") for word, shape in _SHAPE_WORDS)


def _skip_words(text: str) -> list[str]:
    """건너뛰는 말에서 장을 가를 낱말 — 건너뛰기 말 자체의 낱말·가는 곳(「결론으로 가겠습니다」)은 뺀다."""
    return [s for s in content_stems(_SKIP_DESTINATION_RE.sub(" ", text)) if not s.startswith(_SKIP_WORD_HEADS)]


def skip_targets(utts: list[Utterance], texts: dict[int, str]) -> dict[int, Utterance]:
    """
    건너뛰기 말 → 건너뛴 장. 말이 놓인 장과 그 앞뒤 장 중 말에 나온 낱말(「이건 혈당 부하 계산식인데요」)이 가장 많이 든 장이다.
    낱말이 없거나 비기면 말이 놓인 장. 장을 모르는 구간(0장)이면 낱말이 가장 많이 든 장, 그것도 없으면 버린다.
    장 구간은 녹음에서 추정한 것이라 한 장 밀려 있을 수 있다 (09-30 혈당: 3장 말이 4장 구간 머리에 붙었다).
    """
    stems_by_slide = {no: content_stems(t) for no, t in texts.items()}
    out: dict[int, Utterance] = {}
    for k, u in enumerate(utts):
        if not u.skip:
            continue
        said = _skip_words(u.text)
        cands = [u.slide_no, u.slide_no + 1, u.slide_no - 1] if u.slide_no else sorted(stems_by_slide)

        def score(words: list[str]) -> list[tuple[int, int, int]]:
            return [(count_hits(words, stems_by_slide.get(no, [])), -i, no) for i, no in enumerate(cands) if no in stems_by_slide]

        scored = score(said)
        if not scored:
            continue
        # 건너뛰는 말에 그 장 낱말이 없으면: ① 말이 장의 **꼴**을 부른다(「여기 계산식이 있는데요」 → 식이 있는 장, 「이 표는」 → 표가 있는 장)
        # ② 바로 앞 문장이 그 장을 부른 말이다(「하반기 운영안은 단톡방에 따로 올려 둘게요. 여기는 스킵하고…」). 장 경계는 추정이라
        # 앞 문장이 앞 구간에 있을 수 있다 (held-out 지하철·배드민턴 덱).
        if max(scored)[0] == 0:
            shaped = [no for no in cands if no in texts and _slide_has_shape(texts[no], u.text)]
            prev = utts[k - 1] if k > 0 and not utts[k - 1].skip else None
            if len(shaped) == 1:
                scored = [(1, 0, shaped[0])]
            elif prev is not None:
                pcands = list(dict.fromkeys([*cands, prev.slide_no]))
                scored = [(count_hits(_skip_words(prev.text), stems_by_slide.get(no, [])), -i, no)
                          for i, no in enumerate(pcands) if no in stems_by_slide] or scored
        hits, _, target = max(scored)          # 낱말이 많이 든 장 — 비기면 말이 놓인 장(cands 앞쪽)
        if hits == 0:
            if not u.slide_no:
                continue                        # 장도 모르고 가릴 낱말도 없다 — 짐작하지 않는다
            target = u.slide_no
        out.setdefault(target, u)
    return out


# ---------------------------------------------------------------------------
# 말로 적은 숫자
# ---------------------------------------------------------------------------

#: 단위 바로 뒤에 와도 되는 조사·어미의 첫머리 — 「49프로나」「20프로정도로」. 「프로그램·프로젝트」「이십 분석」 은 단위가 아니다.
_AFTER_UNIT = (r"(?=$|[^가-힣]|나|가|는|도|의|를|로|으로|요|예|에|이|였|입|정도|쯤|씩|가량|까지|만|은|을|과|와|보다|밖에|대|라|인|임|면|짜리)")
_PCT_POINT_RE = re.compile(r"(\d)\s*(?:퍼센트|프로|%)\s?포인트")
_PCT_WORD_RE = re.compile(r"(\d)\s*퍼센트")
_PRO_RE = re.compile(r"(\d)\s*프로" + _AFTER_UNIT)

_SINO_DIGIT = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_SINO_MULT = {"십": 10, "백": 100, "천": 1000}
#: 한자어 수 + 단위. 수 앞은 낱말 머리여야 한다(「일이 많아서」의 일이는 수가 아니다 — 아래 파서가 거른다).
#: 앞이 숫자면(「3천 원」) 한자어 수가 아니라 섞어 쓴 수다 — `_MIXED_*` 가 받는다.
_SINO_RE = re.compile(
    r"(?<![가-힣\d])([영공일이삼사오육칠팔구십백천만]+)\s?"
    r"(퍼센트|프로|%|개월|시간|만원|억원|명|개|원|배|분|초|년|회|점|세|살|위|건|억|할)" + _AFTER_UNIT
)
#: 「할」(10분의 1 — 타율 「이 할」「삼 할」) 은 바로 뒤에 조사가 붙을 때만 수다. 「이 할 일」「할 수」 의 할(하다)은 수가 아니다.
#: 09-30 녹음 감사 REC-03: 「타율이 이 할도 안 되는」 이 수로 안 바뀌어 질문이 「자료 7장의 수치와 달라요」 라고 했다.
_HAL_NEXT_RE = re.compile(r"(?:도|이|가|은|는|을|를|에|의|대|짜리|쯤|정도|미만|이상|이하)")
_PCT_UNITS = ("퍼센트", "프로", "%")
#: 숫자 + 천 — 「3천 원」「2천 명」 → 3000원 · 2000명. 자료는 「3,200원」 처럼 쓴다.
_MIXED_THOUSAND_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s?천\s?(원|명|개|건|회|번|배)" + _AFTER_UNIT)
#: 숫자 + 만·억 + 원 — 「30만 원」「5억 원」 → 30만원 · 5억원 (자료 쪽 대조가 만원·억원을 한 단위로 읽는다).
_MIXED_WON_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s?(만|억)\s?원" + _AFTER_UNIT)


def _sino_value(word: str) -> int | None:
    """「이십구」→29 · 「삼백」→300 · 「이십만」→200000. 숫자가 연달아 오면(「일이」) 수가 아니다 → None."""
    total, block, digit = 0, 0, None
    for ch in word:
        if ch in _SINO_DIGIT:
            if digit is not None:
                return None
            digit = _SINO_DIGIT[ch]
        elif ch in _SINO_MULT:
            block += (1 if digit is None else digit) * _SINO_MULT[ch]
            digit = None
        elif ch == "만":
            total += ((block + (digit or 0)) or 1) * 10000
            block, digit = 0, None
        else:
            return None
    return total + block + (digit or 0)


def _sino_sub(m: re.Match) -> str:
    word, unit = m.group(1), m.group(2)
    if unit == "할" and not _HAL_NEXT_RE.match(m.string, m.end()):
        return m.group(0)
    # 한 글자 수(「오」「이」)는 퍼센트·할 앞에서만 — 「이 명」「오 분」 은 「이 사람」「오분」 과 가를 수 없다
    if len(word) < 2 and not any(c in _SINO_MULT for c in word) and unit not in (*_PCT_UNITS, "할"):
        return m.group(0)
    value = _sino_value(word)
    if value is None:
        return m.group(0)
    if value >= 10000 and value % 10000 == 0 and unit == "원":
        return f"{value // 10000}만원"          # 자료는 「30만 원」 이라 쓴다 — 같은 단위(만원)로 맞춰야 견줄 수 있다
    return f"{value}{' ' if unit in _PCT_UNITS else ''}{unit}"


#: 고유어 수 + 세는 말 — 「열 명 중에 여덟 명」「스물여섯 명」「여섯 분」「석 달」「두 배」. 세는 말 앞에서만 수다(「창문을 열 때」「네, 두 번」 은
#: 아니다). 「한 번」 은 「한번 보세요」 와 못 가르므로 번은 세는 말에서 뺀다. 사람을 높여 세는 「분」 은 명으로 — 고유어 수 + 분은
#: 시간이 아니다(시간은 「오 분」 처럼 한자어 수로 센다). held-out 배드민턴 덱: 「열 명 중에 여덟 명」(자료 10명 중 6명)을 수로 못 읽었다.
_NATIVE_TENS = {"열": 10, "스물": 20, "스무": 20, "서른": 30, "마흔": 40, "쉰": 50, "예순": 60, "일흔": 70, "여든": 80, "아흔": 90}
_NATIVE_ONES = {"한": 1, "두": 2, "세": 3, "석": 3, "네": 4, "넉": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9}
#: 자료 대조가 단위로 읽는 세는 말만 — 단위 없는 맨 수(「세 가지」→「3」)는 자료의 아무 3 과 짝지어져 없는 모순을 만든다.
_NATIVE_COUNTERS = ("명", "분", "사람", "개", "배", "달", "살", "시간")
_NATIVE_RE = re.compile(
    r"(?<![가-힣\d])(열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔)?(한|두|세|석|네|넉|다섯|여섯|일곱|여덟|아홉)?"
    r"\s?(" + "|".join(_NATIVE_COUNTERS) + r")" + _AFTER_UNIT
)
#: 「두 배 반」 = 2.5배.
_HALF_TIMES_RE = re.compile(r"(\d+)배\s?반(?![가-힣])")


def _native_sub(m: re.Match) -> str:
    tens, ones, counter = m.group(1), m.group(2), m.group(3)
    if not tens and not ones:
        return m.group(0)
    value = _NATIVE_TENS.get(tens or "", 0) + _NATIVE_ONES.get(ones or "", 0)
    unit = {"분": "명", "사람": "명", "달": "개월"}.get(counter, counter)     # 「석 달」 → 3개월 (자료는 「3개월」 로 쓴다)
    return f"{value}{unit}"


def spoken_numbers(text: str) -> str:
    """받아쓰기의 말로 적은 수·퍼센트를 자료 표기로 — 「이십구 퍼센트」→「29%」, 「3 퍼센트 포인트」→「3%p」, 「열 명」→「10명」."""
    t = _SINO_RE.sub(_sino_sub, text or "")
    t = _NATIVE_RE.sub(_native_sub, t)
    t = _HALF_TIMES_RE.sub(lambda m: f"{m.group(1)}.5배", t)
    t = _MIXED_THOUSAND_RE.sub(lambda m: f"{float(m.group(1)) * 1000:g}{m.group(2)}", t)
    t = _MIXED_WON_RE.sub(r"\1\2원", t)
    t = _PCT_POINT_RE.sub(r"\1%p", t)
    t = _PCT_WORD_RE.sub(r"\1%", t)
    return _PRO_RE.sub(r"\1%", t)
