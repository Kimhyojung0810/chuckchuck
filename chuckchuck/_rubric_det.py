"""
채점표 v3 의 결정 채점기입니다 — LLM 없이 코드가 계산하는 19개 항목.

f14_rubric 의 비공개 도우미입니다. `_match.py`·`_json_text.py` 와 같은 층입니다.

규칙 셋:

1. **못 재면 None 을 낸다.** 0점이 아니다. 자료가 없어서 못 잰 것과 못해서 0점인 것은
   완전히 다른 말이고, 섞으면 멀쩡한 발표가 낙제한다.
2. **모든 점수에 근거를 붙인다.** `(점수, 근거 한 줄)` 을 함께 낸다. 근거 없는 숫자는
   지금 걷어내는 그 블랙박스와 같다.
3. **임계값은 전부 파일 상단 상수다.** 왜 그 값인지 한 줄씩 남긴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .contracts import (
    AlignmentDoc,
    ConceptGraph,
    HabitDoc,
    PaceDoc,
    SlideDoc,
    Transcript,
)

# ---------------------------------------------------------------------------
# 임계값 — 전부 여기에 모은다
# ---------------------------------------------------------------------------

#: 추가 발화(5번) 관용 비율. 개념 대비 이만큼까지는 애드리브로 본다.
EXTRA_SPEECH_FREE_RATIO = 0.15
#: 이 비율을 넘으면 0점. 자료의 절반만큼 딴 얘기를 했다는 뜻이다.
EXTRA_SPEECH_ZERO_RATIO = 0.50

#: 모순(4번) 1건의 감점. doc_weight 로 비례 조정된다. f13 의 12점을 100점 척도로 옮긴 값.
CONTRADICTION_UNIT_PENALTY = 25.0

#: 지시어(17번) 빈도, 100어절당. 이 아래면 만점.
DEIXIS_FREE_PER_100 = 1.5
#: 100어절당 이만큼이면 0점. 여섯 어절에 한 번꼴로 "이거"를 쓰는 수준이다.
DEIXIS_ZERO_PER_100 = 6.0

#: 문장 길이(19번) 적정 어절 수. 한국어 구어에서 편하게 따라오는 길이.
SENTENCE_GOOD_WORDS = 16.0
#: 이보다 길면 0점.
SENTENCE_ZERO_WORDS = 34.0
#: 문장 종결이 이보다 적으면 문장 단위를 판단할 수 없다 — 못 잰 것으로 둔다.
SENTENCE_MIN_COUNT = 3

#: 무의미 반복(20번) 빈도, 100어절당.
REPEAT_FREE_PER_100 = 0.5
REPEAT_ZERO_PER_100 = 5.0

#: 신호어(21번) 종류 수. 이만큼 쓰면 만점.
SIGNAL_FULL_KINDS = 6

#: 말속도(22번) 권장 구간(자/분). f17_pace 의 권장 구간과 같은 값이다.
PACE_GOOD_CPM = (300.0, 350.0)
#: 권장 구간에서 이만큼 벗어나면 0점.
PACE_ZERO_DRIFT_CPM = 180.0
#: 과속·감속 슬라이드 1개당 감점.
PACE_UNSTABLE_PENALTY = 8.0

#: 필러(23번) 빈도, 분당. 이 아래면 만점.
FILLER_FREE_PER_MIN = 2.0
FILLER_ZERO_PER_MIN = 14.0
#: 핵심 슬라이드에 필러가 몰렸을 때의 추가 감점 상한.
FILLER_CORE_PENALTY_MAX = 20.0

#: 긴 침묵(24번) 1건당 감점. f18 은 슬라이드 안에서 5초 넘게 끊긴 것만 잡으므로,
#: 잡힌 건 전부 "구간 전환이 아닌 자리에서 멈춤" 이다.
PAUSE_UNIT_PENALTY = 20.0

#: 낭독(27번) 판정용 글자 n-gram 길이. 한국어는 어절보다 글자 단위가 안정적이다.
READING_NGRAM = 5
#: 슬라이드 문장과 발화가 이만큼 겹치는 건 자연스럽다 (제목·용어는 그대로 말한다).
READING_FREE_OVERLAP = 0.20
#: 이만큼 겹치면 화면을 읽은 것으로 본다.
READING_ZERO_OVERLAP = 0.65
#: 이 글자 수 아래인 슬라이드는 낭독 판정에서 뺀다 — 표지·간지가 점수를 흔든다.
READING_MIN_CHARS = 40

#: 시간 배분(28번) 감점. 핵심을 놓친 게 보조를 놓친 것보다 무겁다.
ALLOC_CORE_PENALTY = 14.0
ALLOC_SUPPORT_PENALTY = 6.0

#: 제한시간(31번) 허용 오차. 이 안이면 만점.
TIME_FREE_DRIFT = 0.05
#: 목표의 이만큼을 벗어나면 0점 (7분 발표에서 ±2분 48초).
TIME_ZERO_DRIFT = 0.40

#: 핵심 슬라이드 체류(33번) 허용 오차.
CORE_DWELL_FREE_DRIFT = 0.15
CORE_DWELL_ZERO_DRIFT = 0.60

#: 정보 밀도(34번). 이 글자 수 아래면 읽기 편하다.
DENSITY_GOOD_CHARS = 150.0
#: 이 글자 수를 넘으면 한 장에 다 못 읽는다.
DENSITY_ZERO_CHARS = 520.0

#: 목차 슬라이드(36번)가 없을 때의 점수. 짧은 발표는 목차가 없어도 되므로 0점은 아니다.
ROADMAP_MISSING_SCORE = 30

#: 출처 표기(38번). 이 개수 이상 숫자가 있으면 근거 자료로 본다.
CITATION_DIGIT_HITS = 3

#: 근거 문자열이 화면과 로그를 뒤덮지 않게 자른다.
EVIDENCE_QUOTE_MAX = 60


#: 불명확한 지시어(17번). 뒤에 조사가 붙어도 잡히게 어간만 둔다.
DEIXIS_WORDS = (
    "이거", "그거", "저거", "요거",
    "이것", "그것", "저것",
    "이런", "그런", "저런",
    "이렇게", "그렇게", "저렇게",
    "여기", "거기", "저기",
    "이쪽", "그쪽", "저쪽",
)

#: 구조 신호어(21번). 종류별로 하나만 세서 "따라서"만 열 번 쓴 발표가 만점이 되지 않게 한다.
SIGNAL_GROUPS: dict[str, tuple[str, ...]] = {
    "열거": ("첫째", "둘째", "셋째", "첫 번째", "두 번째", "세 번째"),
    "순서": ("먼저", "우선", "다음으로", "이어서"),
    "대조": ("반면", "하지만", "그러나", "반대로"),
    "인과": ("따라서", "그래서", "그러므로", "왜냐하면"),
    "환언": ("즉", "다시 말해", "말하자면"),
    "예시": ("예를 들어", "예컨대", "가령"),
    "정리": ("정리하면", "요약하면", "결론적으로", "마지막으로", "끝으로"),
}

#: 목차·로드맵 슬라이드(36번) 제목 단서.
ROADMAP_HINTS = ("목차", "차례", "발표 순서", "agenda", "contents", "overview", "outline")

#: 출처 표기(38번) 단서.
CITATION_PATTERN = re.compile(
    r"(출처|자료\s*:|참고\s*문헌|참고자료|source|sources|reference|references|et\s+al\.?|"
    r"\[\d+\]|https?://)",
    re.IGNORECASE,
)

#: 문장 종결(19번). f05_stt 의 것과 같은 뜻이지만, 모듈끼리 import 하지 않는 규칙에 따라
#: 여기에 따로 둔다 (docs/DEV_POLICY.md §4).
SENTENCE_END = re.compile(r"[.!?。]|(?:니다|세요|어요|아요|네요|군요|겠죠|나요|까요)(?=\s|$)")

_DIGIT = re.compile(r"\d")
_WS = re.compile(r"\s+")

#: 화면에 안 보이는 블록. `figure` 는 Upstage 가 이미지를 보고 쓴 영문 설명이라
#: 발표자가 읽는 글자가 아니다 — 실제 자료에서 한 장의 figure 블록만 9,047자였다.
#: 이걸 그대로 세면 정보 밀도가 전부 0점이 되고, 낭독·출처 판정도 같이 망가진다.
#: `table` 은 화면에 실제로 보이는 값이라 남긴다.
NON_READABLE_CATEGORIES = frozenset({"figure", "header", "footer"})

#: `table` 블록 **안에도** `<figure><figcaption>` 이미지 설명이 끼어 있다
#: (실제 자료의 1번 슬라이드 table 블록이 26,984자였다). 카테고리로 거른 뒤에도
#: 한 번 더 걷어내야 한다.
_FIGURE_HTML = re.compile(r"<figure\b.*?</figure>", re.DOTALL | re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]{1,200}>")
_IMG_PLACEHOLDER = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def readable_text(slide) -> str:
    """
    슬라이드에서 **사람이 실제로 읽는** 글자만.

    표 안의 값은 남기고, 이미지 설명 블록·끼어든 figure HTML·태그·이미지
    자리표시자를 걷어낸다. 밀도(34)·낭독(27)·출처(38) 가 전부 이걸 쓴다.

    `Slide.total_char_count` 를 쓰지 않는 이유: F-01 이 그걸 모든 블록 길이의 합으로
    계산해서(`f01_parse.py:289`) 같은 이유로 부풀어 있다.
    """
    parts = [b.text for b in slide.blocks if b.category not in NON_READABLE_CATEGORIES]
    text = _FIGURE_HTML.sub(" ", "\n".join(parts))
    text = _IMG_PLACEHOLDER.sub(" ", text)
    text = _HTML_TAG.sub(" ", text)
    return _WS.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# 채점에 쓰는 재료 묶음
# ---------------------------------------------------------------------------

@dataclass
class Evidence:
    """
    한 번의 채점에 들어온 자료 전부. **전부 없어도 된다.**

    부스에서 파이프라인 일부가 실패해도 점수가 나와야 한다. 없는 자료에 기대는
    항목만 '못 쟀다'가 되고 나머지는 정상 채점된다.
    """

    situation: str = ""
    #: 청중과 목표 시간. 13번(청중 수준 맞춤)·14번(목적에 맞는 강조점)이 이걸 봐야
    #: 판단할 수 있다. 없으면 프롬프트에서 "안 알려 줬다" 고 밝힌다 — 그냥 비워 두면
    #: 모델이 근거 없이 0점을 준다 (실제로 solar 가 그랬다).
    audience: str = ""
    duration_min: int | None = None
    slides: SlideDoc | None = None
    graph: ConceptGraph | None = None
    transcript: Transcript | None = None
    alignment: AlignmentDoc | None = None
    flow: object | None = None          # FlowDiff. 결정 채점에는 안 쓰고 LLM 힌트로 간다
    pace: PaceDoc | None = None
    habits: HabitDoc | None = None

    @property
    def is_mock_stt(self) -> bool:
        """
        모의 STT 인가.

        MockSTT 는 단어를 균등 간격으로 뱉는다 — 침묵이 구조적으로 0 이고 말속도가
        상수다. 이걸 그대로 채점하면 음성 전달이 통째로 만점처럼 보인다.
        """
        return bool(self.transcript and self.transcript.provider == "mock")

    @property
    def words(self) -> list[str]:
        if not self.transcript:
            return []
        if self.transcript.words:
            return [w.text for w in self.transcript.words if w.text.strip()]
        return [w for w in _WS.split(self.transcript.full_text or "") if w]

    @property
    def word_count(self) -> int:
        return len(self.words)

    @property
    def full_text(self) -> str:
        if not self.transcript:
            return ""
        return self.transcript.full_text or " ".join(self.words)

    @property
    def spoken_sec(self) -> float:
        """발화 길이(초). transcript 를 먼저 보고, 없으면 pace 를 본다."""
        if self.transcript and self.transcript.duration_sec > 0:
            return float(self.transcript.duration_sec)
        if self.pace and self.pace.actual_sec > 0:
            return float(self.pace.actual_sec)
        return 0.0

    def core_slide_nos(self) -> set[int]:
        """핵심 슬라이드 번호. pace 가 있으면 그걸 쓰고, 없으면 그래프에서 찾는다."""
        if self.pace and self.pace.slides:
            return {s.slide_no for s in self.pace.slides if s.importance == "core"}
        if self.graph:
            return {
                no
                for node in self.graph.nodes
                if node.importance == "core"
                for no in node.slide_nos
            }
        return set()


# ---------------------------------------------------------------------------
# 공통 도우미
# ---------------------------------------------------------------------------

def _band(value: float, good: float, bad: float) -> int:
    """
    value 가 good 이면 100, bad 면 0, 사이는 선형.

    good > bad 여도 된다 (클수록 좋은 지표).
    """
    if good == bad:
        return 100 if value == good else 0
    ratio = (value - bad) / (good - bad)
    return int(round(max(0.0, min(1.0, ratio)) * 100))


def _penalize(penalty: float) -> int:
    """100 에서 깎는다. 0 밑으로는 안 내려간다."""
    return int(round(max(0.0, 100.0 - penalty)))


def _quote(text: str, limit: int = EVIDENCE_QUOTE_MAX) -> str:
    flat = _WS.sub(" ", str(text or "")).strip()
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _char_ngrams(text: str, n: int) -> set[str]:
    flat = _WS.sub("", str(text or ""))
    if len(flat) < n:
        return set()
    return {flat[i:i + n] for i in range(len(flat) - n + 1)}


# ---------------------------------------------------------------------------
# 항목별 채점기 — 전부 (점수, 근거) 아니면 None
# ---------------------------------------------------------------------------

Result = tuple[int, str] | None


def _item_01_coverage(ev: Evidence) -> Result:
    """핵심 개념 커버리지 — F-11 이 계산한 가중 커버리지를 그대로 쓴다."""
    if not ev.alignment:
        return None
    cov = max(0.0, min(1.0, float(ev.alignment.summary.coverage)))
    counts = ev.alignment.summary.verdict_counts or {}
    total = len(ev.alignment.items)
    aligned = int(counts.get("aligned", 0))
    return (
        int(round(cov * 100)),
        f"핵심 개념 {total}개 중 {aligned}개를 실제로 설명했어요 (비중 반영 커버리지 {cov:.0%})",
    )


def _item_04_contradiction(ev: Evidence) -> Result:
    """
    자료-발화 일치성 — 모순만 본다.

    누락은 1번 커버리지가 이미 값을 매겼다. 여기서 또 깎으면 같은 실수를 두 번 청구한다
    (f13 의 설계 원칙 1을 그대로 잇는다).
    """
    if not ev.alignment:
        return None
    bad = [i for i in ev.alignment.items if i.verdict == "contradiction"]
    if not bad:
        return 100, "자료와 어긋나게 말한 곳이 없어요"
    # weight 가 0 인 노드도 모순은 모순이라 최소 절반은 매긴다
    penalty = sum(CONTRADICTION_UNIT_PENALTY * max(0.5, min(1.0, i.doc_weight)) for i in bad)
    sample = next((i.evidence for i in bad if i.evidence), "")
    tail = f" — 예: “{_quote(sample)}”" if sample else ""
    return _penalize(penalty), f"자료와 어긋난 설명이 {len(bad)}곳 있어요{tail}"


def _item_05_extra_speech(ev: Evidence) -> Result:
    """근거 없는 추가 발화 — 자료에 없는 개념을 얼마나 얹었나."""
    if not ev.alignment:
        return None
    nodes = len(ev.alignment.items)
    if nodes == 0:
        return None
    extras = ev.alignment.extra_concepts
    ratio = len(extras) / nodes
    score = _band(ratio, good=EXTRA_SPEECH_FREE_RATIO, bad=EXTRA_SPEECH_ZERO_RATIO)
    if not extras:
        return score, "자료에 없는 내용을 덧붙이지 않았어요"
    labels = ", ".join(e.label for e in extras[:3])
    return score, f"자료에 없는 이야기를 {len(extras)}개 덧붙였어요 ({labels})"


def _item_17_deixis(ev: Evidence) -> Result:
    """지시어 남용 — '이거/저거' 가 몇 어절에 한 번 나오나."""
    words = ev.words
    if not words:
        return None
    hits = [w for w in words if any(w.startswith(d) for d in DEIXIS_WORDS)]
    per100 = len(hits) / len(words) * 100
    score = _band(per100, good=DEIXIS_FREE_PER_100, bad=DEIXIS_ZERO_PER_100)
    if not hits:
        return score, "가리키는 말 대신 이름을 불러 설명했어요"
    top = ", ".join(sorted(set(hits))[:4])
    return score, f"100어절당 지시어 {per100:.1f}번이에요 ({top})"


def _item_19_sentence(ev: Evidence) -> Result:
    """문장 길이·완결성 — 종결 어미가 없으면 판단할 수 없다."""
    text = ev.full_text
    if not text.strip():
        return None
    ends = list(SENTENCE_END.finditer(text))
    if len(ends) < SENTENCE_MIN_COUNT:
        return None
    words = ev.word_count or len(_WS.split(text))
    avg = words / len(ends)
    score = _band(avg, good=SENTENCE_GOOD_WORDS, bad=SENTENCE_ZERO_WORDS)
    # 마지막 종결 뒤에 많이 남으면 끝맺지 못한 것이다
    tail = text[ends[-1].end():].strip()
    unfinished = len(_WS.split(tail)) if tail else 0
    if unfinished > SENTENCE_GOOD_WORDS:
        return max(0, score - 15), f"문장 하나가 평균 {avg:.0f}어절이고, 마지막 문장을 끝맺지 못했어요"
    return score, f"문장 하나가 평균 {avg:.0f}어절이에요 (문장 {len(ends)}개)"


def _item_20_repeat(ev: Evidence) -> Result:
    """의미 없는 반복 — F-18 이 잡은 REP 빈도."""
    if not ev.habits:
        return None
    words = ev.word_count
    if words == 0:
        return None
    per100 = ev.habits.repeat_cnt / words * 100
    score = _band(per100, good=REPEAT_FREE_PER_100, bad=REPEAT_ZERO_PER_100)
    if ev.habits.repeat_cnt == 0:
        return score, "같은 말을 되풀이하지 않았어요"
    sample = next((s.text for s in ev.habits.spans if s.kind == "REP" and s.text), "")
    tail = f" — 예: “{_quote(sample, 24)}”" if sample else ""
    return score, f"같은 말을 {ev.habits.repeat_cnt}번 되풀이했어요 (100어절당 {per100:.1f}번){tail}"


def _item_21_signals(ev: Evidence) -> Result:
    """구조 신호어 — 종류를 세서 한 단어만 반복한 발표를 걸러낸다."""
    text = ev.full_text
    if not text.strip():
        return None
    used = [name for name, words in SIGNAL_GROUPS.items() if any(w in text for w in words)]
    score = _band(float(len(used)), good=float(SIGNAL_FULL_KINDS), bad=0.0)
    if not used:
        return score, "첫째·반면·따라서 같은 구조 신호어를 쓰지 않았어요"
    return score, f"구조 신호어를 {len(used)}종류 썼어요 ({', '.join(used)})"


def _item_22_speed(ev: Evidence) -> Result:
    """말속도 적절성 — 평균 속도와 구간별 흔들림을 같이 본다."""
    if ev.is_mock_stt or not ev.pace:
        return None
    cpm = float(ev.pace.avg_chars_per_min)
    if cpm <= 0:
        return None
    low, high = PACE_GOOD_CPM
    drift = 0.0 if low <= cpm <= high else (low - cpm if cpm < low else cpm - high)
    score = _band(drift, good=0.0, bad=PACE_ZERO_DRIFT_CPM)
    unstable = [s.slide_no for s in ev.pace.slides if s.status in ("fast", "slow")]
    if unstable:
        score = _penalize((100 - score) + len(unstable) * PACE_UNSTABLE_PENALTY)
        return score, f"평균 {cpm:.0f}자/분이고, {len(unstable)}개 슬라이드에서 속도가 크게 흔들렸어요"
    if drift > 0:
        way = "느려요" if cpm < low else "빨라요"
        return score, (
            f"평균 {cpm:.0f}자/분으로 권장 구간({low:.0f}~{high:.0f})보다 {drift:.0f}자/분 {way}"
        )
    return score, f"평균 {cpm:.0f}자/분으로 권장 구간({low:.0f}~{high:.0f}) 안이에요"


def _item_23_fillers(ev: Evidence) -> Result:
    """필러 빈도·위치 — 핵심 슬라이드에 몰렸으면 더 깎는다."""
    if ev.is_mock_stt or not ev.habits:
        return None
    minutes = ev.spoken_sec / 60.0
    if minutes <= 0:
        return None
    per_min = ev.habits.filler_cnt / minutes
    score = _band(per_min, good=FILLER_FREE_PER_MIN, bad=FILLER_ZERO_PER_MIN)

    core = ev.core_slide_nos()
    if core and ev.habits.filler_cnt > 0:
        core_hits = sum(h.filler_cnt for h in ev.habits.by_slide if h.slide_no in core)
        share = core_hits / ev.habits.filler_cnt
        if share > 0.5:
            score = _penalize((100 - score) + FILLER_CORE_PENALTY_MAX * share)
            return score, f"분당 간투어 {per_min:.1f}번이고, 그중 {share:.0%}가 핵심 슬라이드에 몰렸어요"
    if ev.habits.filler_cnt == 0:
        return score, "어·음 같은 간투어가 거의 없었어요"
    return score, f"분당 간투어 {per_min:.1f}번이에요 (전체 {ev.habits.filler_cnt}번)"


def _item_24_pauses(ev: Evidence) -> Result:
    """
    휴지·침묵의 위치.

    F-18 은 **슬라이드 안에서** 5초 넘게 끊긴 것만 잡는다. 슬라이드가 넘어가는 자리의
    정적은 애초에 세지 않으므로, 여기 잡힌 건 전부 '전환이 아닌 자리에서 멈춤'이다.
    5초라는 문턱이 거칠어서 짧은 머뭇거림은 못 잡는다.
    """
    if ev.is_mock_stt or not ev.habits:
        return None
    if not ev.transcript or not ev.transcript.words:
        return None
    n = ev.habits.pause_cnt
    score = _penalize(n * PAUSE_UNIT_PENALTY)
    if n == 0:
        return score, "말이 끊긴 긴 정적이 없었어요 (5초 기준)"
    return score, f"슬라이드 도중에 5초 넘게 멈춘 곳이 {n}군데 있어요"


def _item_27_reading(ev: Evidence) -> Result:
    """낭독 vs 실제 설명 — 슬라이드 글자와 발화가 얼마나 그대로 겹치나."""
    if not ev.slides or not ev.transcript:
        return None
    overlaps: list[tuple[int, float]] = []
    for slide in ev.slides.slides:
        body = readable_text(slide)
        if len(_WS.sub("", body)) < READING_MIN_CHARS:
            continue
        spoken = ev.transcript.text_for_slide(slide.slide_no)
        if not spoken.strip():
            continue
        grams = _char_ngrams(body, READING_NGRAM)
        if not grams:
            continue
        overlaps.append((slide.slide_no, len(grams & _char_ngrams(spoken, READING_NGRAM)) / len(grams)))
    if not overlaps:
        return None
    avg = sum(o for _, o in overlaps) / len(overlaps)
    score = _band(avg, good=READING_FREE_OVERLAP, bad=READING_ZERO_OVERLAP)
    worst_no, worst = max(overlaps, key=lambda x: x[1])
    if worst >= READING_ZERO_OVERLAP:
        return score, f"화면 글자를 그대로 읽은 비율이 평균 {avg:.0%}예요 ({worst_no}번이 가장 높아요)"
    return score, f"화면 문장과 겹치는 비율이 평균 {avg:.0%}로, 자기 말로 풀었어요"


def _item_28_slide_alloc(ev: Evidence) -> Result:
    """슬라이드별 설명시간 균형 — 중요도를 가중해서 어긋난 슬라이드를 센다."""
    if not ev.pace or not ev.pace.slides:
        return None
    penalty = 0.0
    off: list[int] = []
    for s in ev.pace.slides:
        if s.status in ("short", "long"):
            penalty += ALLOC_CORE_PENALTY if s.importance == "core" else ALLOC_SUPPORT_PENALTY
            off.append(s.slide_no)
    score = _penalize(penalty)
    if not off:
        return score, "슬라이드마다 중요도에 맞게 시간을 나눠 썼어요"
    return score, f"시간 배분이 어긋난 슬라이드가 {len(off)}개예요 ({', '.join(map(str, off[:5]))}번)"


def _item_30_emphasis_match(ev: Evidence) -> Result:
    """슬라이드-발화 강조 일치 — 자료 비중과 발화 비중의 순위 상관."""
    if not ev.alignment:
        return None
    tau = ev.alignment.summary.rank_correlation
    if tau is None:
        return None
    # -1~1 을 0~100 으로. 역순으로 말했으면(-1) 0 에 가깝게 떨어져야 한다
    score = int(round(max(0.0, min(1.0, (float(tau) + 1.0) / 2.0)) * 100))
    return score, f"자료가 힘준 순서와 발표에서 힘준 순서의 상관이 {tau:+.2f}예요"


def _item_31_total_time(ev: Evidence) -> Result:
    """제한시간 준수."""
    if not ev.pace or ev.pace.target_sec <= 0:
        return None
    target, actual = float(ev.pace.target_sec), float(ev.pace.actual_sec)
    drift = abs(actual - target) / target
    score = _band(drift, good=TIME_FREE_DRIFT, bad=TIME_ZERO_DRIFT)
    gap = actual - target
    word = "넘겼어요" if gap > 0 else "남겼어요"
    return score, (
        f"목표 {target / 60:.0f}분에 견줘 {abs(gap) / 60:.1f}분 {word} (실제 {actual / 60:.1f}분)"
    )


def _item_32_section_alloc(ev: Evidence) -> Result:
    """구간별 시간 배분 — 도입·본론·결론 비중."""
    if not ev.pace or not ev.pace.sections:
        return None
    sections = ev.pace.sections
    off = [s for s in sections if s.status != "ok"]
    score = _band(len(off) / len(sections), good=0.0, bad=1.0)
    if not off:
        return score, f"{len(sections)}개 구간 모두 시간 비중이 알맞아요"
    detail = ", ".join(f"{s.name}{s.label or ''}" for s in off[:3])
    return score, f"{len(sections)}개 구간 중 {len(off)}개가 비중이 어긋났어요 ({detail})"


def _item_33_core_dwell(ev: Evidence) -> Result:
    """핵심 슬라이드 체류시간."""
    if not ev.pace or not ev.pace.slides:
        return None
    cores = [s for s in ev.pace.slides if s.importance == "core" and s.recommended_sec > 0]
    if not cores:
        return None
    drifts = [abs(s.delta_sec) / s.recommended_sec for s in cores]
    avg = sum(drifts) / len(drifts)
    score = _band(avg, good=CORE_DWELL_FREE_DRIFT, bad=CORE_DWELL_ZERO_DRIFT)
    if avg <= CORE_DWELL_FREE_DRIFT:
        return score, f"핵심 슬라이드 {len(cores)}장에 권장 시간만큼 머물렀어요"
    worst = max(cores, key=lambda s: abs(s.delta_sec) / s.recommended_sec)
    return score, (
        f"핵심 슬라이드 {len(cores)}장이 권장 시간과 평균 {avg:.0%} 어긋나요 "
        f"({worst.slide_no}번이 {worst.delta_sec:+.0f}초)"
    )


def _item_34_density(ev: Evidence) -> Result:
    """
    슬라이드 정보 밀도.

    글자 수와 줄 수만 본다. 좌표(`Slide.alignment`)는 `UPSTAGE_DOCPARSE_COORDINATES`
    가 기본 꺼짐이라 보통 None 이고, 발표자 노트는 아예 파싱되지 않는다.
    """
    if not ev.slides or not ev.slides.slides:
        return None
    sized = [(s.slide_no, len(readable_text(s))) for s in ev.slides.slides]
    counts = [n for _, n in sized if n > 0]
    if not counts:
        return None
    avg = sum(counts) / len(counts)
    score = _band(avg, good=DENSITY_GOOD_CHARS, bad=DENSITY_ZERO_CHARS)
    heavy = [no for no, n in sized if n > DENSITY_ZERO_CHARS]
    if heavy:
        return score, f"한 장 평균 {avg:.0f}자예요. {', '.join(map(str, heavy[:5]))}번이 특히 빽빽해요"
    return score, f"한 장 평균 {avg:.0f}자로 읽기 편한 밀도예요"


def _item_36_roadmap(ev: Evidence) -> Result:
    """목차·로드맵 슬라이드 — 그래프의 intro 구간이나 제목 단서로 찾는다."""
    if not ev.slides and not ev.graph:
        return None
    if ev.graph:
        for section in ev.graph.sections:
            if section.slide_role == "intro" and section.slide_nos:
                return 100, f"{section.slide_nos[0]}번이 발표 구조를 미리 알려 줘요"
    if ev.slides:
        for slide in ev.slides.slides:
            haystack = f"{slide.title} {readable_text(slide)[:80]}".lower()
            if any(hint in haystack for hint in ROADMAP_HINTS):
                return 100, f"{slide.slide_no}번 목차 슬라이드로 전체 흐름을 안내했어요"
    return ROADMAP_MISSING_SCORE, "전체 구조를 미리 보여 주는 목차 슬라이드가 안 보여요"


def _item_38_citation(ev: Evidence) -> Result:
    """출처·근거 표기 — 근거 자료를 실은 슬라이드에 출처가 붙었나."""
    if not ev.slides or not ev.slides.slides:
        return None
    needs: list[int] = []
    cited: list[int] = []
    for slide in ev.slides.slides:
        body = readable_text(slide)
        has_data = bool(
            len(_DIGIT.findall(body)) >= CITATION_DIGIT_HITS
            or {"chart", "table"} & set(slide.visual_type)
        )
        if not has_data:
            continue
        needs.append(slide.slide_no)
        if CITATION_PATTERN.search(body):
            cited.append(slide.slide_no)
    if not needs:
        return 100, "출처를 밝혀야 할 통계나 인용 자료가 없어요"
    score = int(round(len(cited) / len(needs) * 100))
    missing = [n for n in needs if n not in cited]
    if not missing:
        return score, f"근거 자료를 실은 {len(needs)}장 모두 출처를 밝혔어요"
    return score, (
        f"근거 자료 {len(needs)}장 중 {len(missing)}장에 출처가 없어요 "
        f"({', '.join(map(str, missing[:5]))}번)"
    )


#: 항목 번호 → 채점 함수. rubric_v3 에서 source == "det" 인 19개와 정확히 맞아야 한다.
DET_SCORERS = {
    1: _item_01_coverage,
    4: _item_04_contradiction,
    5: _item_05_extra_speech,
    17: _item_17_deixis,
    19: _item_19_sentence,
    20: _item_20_repeat,
    21: _item_21_signals,
    22: _item_22_speed,
    23: _item_23_fillers,
    24: _item_24_pauses,
    27: _item_27_reading,
    28: _item_28_slide_alloc,
    30: _item_30_emphasis_match,
    31: _item_31_total_time,
    32: _item_32_section_alloc,
    33: _item_33_core_dwell,
    34: _item_34_density,
    36: _item_36_roadmap,
    38: _item_38_citation,
}


def score_item(no: int, ev: Evidence) -> Result:
    """항목 하나를 코드로 매긴다. 못 재면 None."""
    fn = DET_SCORERS.get(no)
    if fn is None:
        return None
    try:
        result = fn(ev)
    except Exception:  # noqa: BLE001 — 한 항목이 터져도 나머지 채점은 계속한다
        return None
    if result is None:
        return None
    score, evidence = result
    return max(0, min(100, int(score))), str(evidence)
