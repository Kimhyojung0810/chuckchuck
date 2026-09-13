"""
결정 채점기(`_rubric_det`) 19개 항목의 논리 테스트입니다.

항목마다 임계값 경계(정확히·바로 아래·바로 위), 빈 증거, 빠진 선택 필드, 단조성을
확인합니다. 코드가 채점표 문서(`docs/RUBRIC_SCORING_PLAN.md`)나 상식과 어긋나는 곳은
문서대로 쓰고 `xfail(strict=True)` 로 표시합니다 — 틀린 동작을 골든으로 박지 않습니다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from chuckchuck import _rubric_det as det
from chuckchuck._rubric_det import DET_SCORERS, Evidence, score_item
from chuckchuck.contracts import (
    AlignmentDoc, AlignmentItem, AlignmentSummary, ConceptGraph, ConceptNode, ExtraConcept,
    HabitDoc, HabitSpan, PaceDoc, Section, SectionAlloc, Slide, SlideBlock, SlideDoc,
    SlideHabits, SlidePace, SlideSpeech, Transcript, Word,
)

FIX = Path(__file__).resolve().parents[1] / "fixtures"
KOREAN = re.compile(r"[가-힣]")
SLIDE_TEXT = "대조 학습은 같은 샘플의 표현을 가깝게 만들고 다른 샘플의 표현은 멀게 만드는 자기지도 학습 방법입니다"

# --- 재료 만들기 — f14_rubric 이 파이프라인 산출물을 Evidence 로 묶는 모양을 따른다 ---

def words_of(text: str) -> list[Word]:
    return [Word(w, i * 0.5, i * 0.5 + 0.4) for i, w in enumerate(text.split())]

def tr(text: str = "", *, provider: str = "clova", duration: float = 0.0,
       with_words: bool = False, by_slide: dict[int, str] | None = None) -> Transcript:
    return Transcript(
        full_text=text, words=words_of(text) if with_words else [], provider=provider,
        duration_sec=duration,
        by_slide=[SlideSpeech(no, 1, 0, 1, t) for no, t in (by_slide or {}).items()],
    )

def slide(no: int, text: str = "", *, title: str = "", category: str = "paragraph",
          visual: tuple[str, ...] = ()) -> Slide:
    blocks = [SlideBlock(category, text)] if text else []
    return Slide(slide_no=no, title=title, blocks=blocks, visual_type=list(visual))

def sdoc(*slides: Slide) -> SlideDoc:
    return SlideDoc("deck.pdf", len(slides), list(slides))

def align(items=(), extras=(), *, coverage: float = 0.0, tau=None) -> AlignmentDoc:
    counts = {"aligned": sum(1 for i in items if i.verdict == "aligned")}
    summary = AlignmentSummary(coverage=coverage, rank_correlation=tau, verdict_counts=counts)
    return AlignmentDoc("deck.pdf", 5, items=list(items), extra_concepts=list(extras), summary=summary)

def pace(*, target: float = 600, actual: float = 600, cpm: float = 320, slides=(), sections=()) -> PaceDoc:
    return PaceDoc(target_sec=target, actual_sec=actual, avg_chars_per_min=cpm,
                   slides=list(slides), sections=list(sections))

def habits(*, rep: int = 0, fil: int = 0, pause: int = 0, by_slide=(), spans=()) -> HabitDoc:
    return HabitDoc(spans=list(spans), by_slide=list(by_slide), repeat_cnt=rep,
                    filler_cnt=fil, pause_cnt=pause, provider="lora")

def sentences(n_sent: int, n_words: int, tail: int = 0) -> str:
    """'말 말 … 합니다' 문장 n_sent 개 + 끝맺지 않은 어절 tail 개."""
    one = " ".join(["말"] * (n_words - 1) + ["합니다"])
    return " ".join([one] * n_sent + ["말"] * tail)

def fixture_evidence() -> Evidence:
    """실제 파이프라인 산출물 픽스처로 묶은 Evidence (정렬 문서 픽스처는 없다)."""
    voice = json.loads((FIX / "focus_voice_report.json").read_text())
    return Evidence(
        situation="school_project",
        slides=SlideDoc.from_dict(json.loads((FIX / "sample_slidedoc.json").read_text())),
        transcript=Transcript.from_dict(json.loads((FIX / "sample_transcript.json").read_text())),
        pace=PaceDoc.from_dict(voice["pace"]),
        habits=HabitDoc.from_dict(voice["habits"]),
    )

# --- 공통 성질 — 19개 전부 ---

@pytest.mark.parametrize("no", sorted(DET_SCORERS))
def test_빈_증거면_예외_없이_None(no):
    assert score_item(no, Evidence()) is None

@pytest.mark.parametrize("no", sorted(DET_SCORERS))
def test_픽스처로_채점하면_범위_안이고_근거가_한글이다(no):
    got = score_item(no, fixture_evidence())
    if got is None:
        assert no in (1, 4, 5, 30), f"{no}번은 정렬 문서 없이도 잴 수 있어야 해요"
        return
    score, reason = got
    assert 0 <= score <= 100 and KOREAN.search(reason)

def test_모르는_번호와_터진_채점기는_None():
    assert score_item(2, Evidence()) is None  # llm 항목
    assert score_item(1, Evidence(alignment=SimpleNamespace())) is None  # .summary 없음 → 예외

def test_점수는_0_100_으로_잘린다(monkeypatch):
    monkeypatch.setitem(det.DET_SCORERS, 99, lambda ev: (250, "x"))
    assert score_item(99, Evidence()) == (100, "x")
    monkeypatch.setitem(det.DET_SCORERS, 99, lambda ev: (-5, "x"))
    assert score_item(99, Evidence()) == (0, "x")

# --- Evidence 속성과 도우미 ---

def test_어절은_words_가_없으면_full_text_에서_나눈다():
    assert Evidence(transcript=tr("가 나  다")).words == ["가", "나", "다"]
    assert Evidence(transcript=tr("가 나", with_words=True)).word_count == 2
    assert Evidence().full_text == "" and Evidence(transcript=tr("", with_words=True)).full_text == ""

def test_발화_길이는_transcript_다음_pace_순이다():
    assert Evidence(transcript=tr(duration=30), pace=pace(actual=90)).spoken_sec == 30
    assert Evidence(transcript=tr(duration=0), pace=pace(actual=90)).spoken_sec == 90
    assert Evidence(transcript=tr()).spoken_sec == 0.0

def test_핵심_슬라이드는_pace_다음_graph_순이다():
    p = pace(slides=[SlidePace(1, importance="core"), SlidePace(2)])
    g = ConceptGraph("d", 3, nodes=[ConceptNode("a", "A", [3], importance="core"),
                                    ConceptNode("b", "B", [4], importance="support")])
    assert Evidence(pace=p, graph=g).core_slide_nos() == {1}
    assert Evidence(graph=g).core_slide_nos() == {3}
    assert Evidence(pace=pace()).core_slide_nos() == set()

def test_mock_stt_판정():
    assert Evidence(transcript=tr(provider="mock")).is_mock_stt
    assert not Evidence(transcript=tr(provider="clova")).is_mock_stt and not Evidence().is_mock_stt

def test_도우미_경계():
    assert det._band(5, 5, 5) == 100 and det._band(4, 5, 5) == 0
    assert det._band(1, good=0, bad=10) == 90 and det._band(20, good=10, bad=0) == 100
    assert det._penalize(150) == 0 and det._penalize(0) == 100
    assert det._quote("a" * 70) == "a" * 60 + "…" and det._quote(" a \n b ") == "a b"
    assert det._char_ngrams("가나", 5) == set() and det._char_ngrams("가 나다라마", 5) == {"가나다라마"}

def test_readable_text_는_figure_header_footer_와_HTML_을_걷어낸다():
    s = Slide(1, blocks=[SlideBlock("paragraph", "본문 <b>굵게</b> ![img](x.png)"),
                         SlideBlock("figure", "F" * 9000), SlideBlock("header", "머리"),
                         SlideBlock("table", "<table>1</table><figure><figcaption>설명</figcaption></figure>")])
    assert det.readable_text(s) == "본문 굵게 1"

# --- 1·4·5·30 — F-11 정렬 결과 ---

@pytest.mark.parametrize("cov, want", [(0.0, 0), (0.5, 50), (1.0, 100), (1.3, 100), (-0.2, 0)])
def test_01_커버리지는_가중_커버리지_그대로(cov, want):
    items = [AlignmentItem("a", verdict="aligned"), AlignmentItem("b", verdict="aligned"),
             AlignmentItem("c", verdict="missing")]
    score, reason = score_item(1, Evidence(alignment=align(items, coverage=cov)))
    assert score == want and "3개 중 2개" in reason

@pytest.mark.parametrize("weights, want", [((), 100), ((1.0,), 75), ((0.0,), 88), ((0.5,), 88),
                                           ((2.0,), 75), ((1.0,) * 4, 0), ((1.0,) * 5, 0)])
def test_04_모순_1건당_25점_가중치는_0_5_1_0_로_묶는다(weights, want):
    items = [AlignmentItem(f"n{i}", verdict="contradiction", doc_weight=w) for i, w in enumerate(weights)]
    items.append(AlignmentItem("ok", verdict="missing", doc_weight=1.0))  # 누락은 안 깎는다
    score, reason = score_item(4, Evidence(alignment=align(items)))
    assert score == want and ("없어요" in reason) == (not weights)

def test_04_근거_발화를_인용한다():
    items = [AlignmentItem("n", verdict="contradiction", evidence="정확도가 99% 라고 했어요")]
    assert "예: “정확도가 99%" in score_item(4, Evidence(alignment=align(items)))[1]

@pytest.mark.parametrize("n_extra, want", [(0, 100), (1, 100), (2, 86), (5, 0), (6, 0)])
def test_05_추가_발화_비율_경계_15퍼센트_50퍼센트(n_extra, want):
    items = [AlignmentItem(f"n{i}") for i in range(10)]
    extras = [ExtraConcept(f"개념{i}") for i in range(n_extra)]
    score, reason = score_item(5, Evidence(alignment=align(items, extras)))
    assert score == want and ("덧붙이지" in reason) == (n_extra == 0)
    if n_extra:
        assert f"{n_extra}개" in reason and "개념0" in reason
    assert score_item(5, Evidence(alignment=align([], extras))) is None  # 노드 0 → 못 잰다

@pytest.mark.parametrize("tau, want", [(None, None), (-1.0, 0), (0.0, 50), (1.0, 100), (1.5, 100), (-2, 0)])
def test_30_순위_상관은_tau_1_을_2로_나눈다(tau, want):
    got = score_item(30, Evidence(alignment=align(tau=tau)))
    if want is None:
        assert got is None
    else:
        assert got[0] == want and f"{tau:+.2f}" in got[1]

# --- 17·19·20·21 — 언어적 명료성 ---

@pytest.mark.parametrize("hits, want", [(0, 100), (1, 100), (2, 89), (6, 0), (7, 0)])
def test_17_지시어_100어절당_1_5_이하_만점_6_이상_0점(hits, want):
    text = " ".join(["이거는"] * hits + ["설명"] * (100 - hits))
    score, reason = score_item(17, Evidence(transcript=tr(text, with_words=True)))
    assert score == want and ("이름을 불러" in reason) == (hits == 0)

# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_17_접속사_그런데는_지시어가_아니다():
    text = " ".join(["그런데"] * 6 + ["설명"] * 94)
    assert score_item(17, Evidence(transcript=tr(text)))[0] == 100

@pytest.mark.parametrize("n_words, want", [(8, 100), (16, 100), (17, 94), (25, 50), (34, 0), (40, 0)])
def test_19_평균_어절_16_이하_만점_34_이상_0점(n_words, want):
    score, reason = score_item(19, Evidence(transcript=tr(sentences(3, n_words))))
    assert score == want and "문장 3개" in reason

def test_19_문장_종결이_3개_미만이면_못_잰다():
    assert score_item(19, Evidence(transcript=tr("   "))) is None
    assert score_item(19, Evidence(transcript=tr(sentences(2, 5)))) is None

@pytest.mark.parametrize("tail, penalty", [(16, 0), (17, 15)])
def test_19_마지막_문장을_끝맺지_못하면_15점_감점(tail, penalty):
    base = score_item(19, Evidence(transcript=tr(sentences(3, 16))))[0]
    score, reason = score_item(19, Evidence(transcript=tr(sentences(3, 16, tail=tail))))
    expected = det._band((48 + tail) / 3, det.SENTENCE_GOOD_WORDS, det.SENTENCE_ZERO_WORDS) - penalty
    assert score == expected <= base and ("끝맺지" in reason) == bool(penalty)

# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_19_소수점은_문장_종결이_아니다():
    text = "매출이 3.5% 올랐고 이익이 2.1% 늘었고 비용이 1.2% 줄었고 아무튼"
    assert score_item(19, Evidence(transcript=tr(text))) is None

# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_19_해요체_종결도_문장으로_센다():
    text = "이게 핵심이죠 그래서 결과가 좋은 거예요 다음은 한계거든요 이제 정리해 볼게요"
    assert score_item(19, Evidence(transcript=tr(text))) is not None

@pytest.mark.parametrize("rep, want", [(0, 100), (1, 100), (2, 89), (10, 0), (11, 0)])
def test_20_반복_100어절당_0_5_이하_만점_5_이상_0점(rep, want):
    ev = Evidence(transcript=tr(" ".join(["말"] * 200)), habits=habits(rep=rep))
    score, reason = score_item(20, ev)
    assert score == want and ("되풀이하지" in reason) == (rep == 0)

def test_20_어절이_없으면_못_재고_REP_예시를_인용한다():
    assert score_item(20, Evidence(transcript=tr(""), habits=habits(rep=1))) is None
    assert score_item(20, Evidence(transcript=tr("말"))) is None
    spans = [HabitSpan("FIL", "어"), HabitSpan("REP", "그 그")]
    ev = Evidence(transcript=tr(" ".join(["말"] * 100)), habits=habits(rep=3, spans=spans))
    assert "예: “그 그”" in score_item(20, ev)[1] and "3번" in score_item(20, ev)[1]

@pytest.mark.parametrize("text, want", [
    ("말 말 말", 0), ("따라서 따라서 따라서", 17), ("첫째 먼저 반면", 50),
    ("첫째 먼저 반면 따라서 즉 예를 들어", 100), ("첫째 먼저 반면 따라서 즉 예를 들어 정리하면", 100),
])
def test_21_신호어는_종류_수로_6종이면_만점(text, want):
    score, reason = score_item(21, Evidence(transcript=tr(text)))
    assert score == want and ("쓰지 않았어요" in reason) == (want == 0)
    assert score_item(21, Evidence(transcript=tr(" "))) is None

# --- 22·23·24 — 음성 전달 (mock STT 면 전부 못 잰다) ---

@pytest.mark.parametrize("no", [22, 23, 24])
def test_음성_항목은_mock_STT_면_못_잰다(no):
    ev = Evidence(transcript=tr("말", provider="mock", duration=60, with_words=True),
                  pace=pace(), habits=habits())
    assert score_item(no, ev) is None

@pytest.mark.parametrize("cpm, want, word", [
    (300, 100, "안이에요"), (350, 100, "안이에요"), (299, 99, "느려요"), (351, 99, "빨라요"),
    (210, 50, "느려요"), (440, 50, "빨라요"), (120, 0, "느려요"), (530, 0, "빨라요"), (600, 0, "빨라요"),
])
def test_22_말속도_권장구간_300_350_에서_180_벗어나면_0점(cpm, want, word):
    score, reason = score_item(22, Evidence(pace=pace(cpm=cpm)))
    assert score == want and word in reason

def test_22_속도_0이면_못_재고_흔들린_슬라이드_1개당_8점():
    assert score_item(22, Evidence(pace=pace(cpm=0))) is None
    sl = [SlidePace(1, status="fast"), SlidePace(2, status="slow"), SlidePace(3, status="long")]
    score, reason = score_item(22, Evidence(pace=pace(cpm=320, slides=sl)))
    assert score == 84 and "2개 슬라이드" in reason

@pytest.mark.xfail(strict=True, reason="계획서 §0-2 는 fast/slow **비율**인데 코드는 개수라 긴 발표가 더 깎인다")
def test_22_흔들린_슬라이드는_비율로_본다():
    def deck(n, bad):
        sl = [SlidePace(i, status="fast" if i <= bad else "ok") for i in range(1, n + 1)]
        return Evidence(pace=pace(cpm=320, slides=sl))
    assert score_item(22, deck(4, 1))[0] == score_item(22, deck(20, 5))[0]

@pytest.mark.parametrize("fil, want", [(0, 100), (10, 100), (11, 98), (40, 50), (70, 0), (80, 0)])
def test_23_필러_분당_2_이하_만점_14_이상_0점(fil, want):
    ev = Evidence(transcript=tr("말", duration=300, provider="clova"), habits=habits(fil=fil))
    score, reason = score_item(23, ev)
    assert score == want and ("거의 없었어요" in reason) == (fil == 0)

def test_23_발화_길이가_없으면_못_재고_pace_로도_잰다():
    assert score_item(23, Evidence(transcript=tr("말"), habits=habits(fil=1))) is None
    assert score_item(23, Evidence(pace=pace(actual=300), habits=habits(fil=10)))[0] == 100

@pytest.mark.parametrize("core_hits, want", [(0, 100), (5, 90), (6, 88), (10, 80)])  # 5분·10개: base 100, 핵심 밀도 c/5 ÷ 2 × 20 = 2c
def test_23_핵심_슬라이드_간투어_밀도로_최대_20점_더_깎는다(core_hits, want):
    p = pace(actual=300, slides=[SlidePace(1, importance="core"), SlidePace(2)])
    h = habits(fil=10, by_slide=[SlideHabits(1, filler_cnt=core_hits), SlideHabits(2, filler_cnt=10 - core_hits)])
    score, reason = score_item(23, Evidence(pace=p, habits=h))
    assert score == want and ("몰렸어요" in reason) == (core_hits > 5)

def test_23_pace_가_없으면_그래프에서_핵심을_찾는다():
    g = ConceptGraph("d", 2, nodes=[ConceptNode("a", "A", [1], importance="core")])
    h = habits(fil=10, by_slide=[SlideHabits(1, filler_cnt=10)])
    assert score_item(23, Evidence(transcript=tr("말", duration=300), graph=g, habits=h))[0] == 80

# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_23_필러가_늘면_점수는_내려가야_한다():
    def ev(total):
        p = pace(actual=300, slides=[SlidePace(1, importance="core"), SlidePace(2)])
        h = habits(fil=total, by_slide=[SlideHabits(1, filler_cnt=10), SlideHabits(2, filler_cnt=total - 10)])
        return Evidence(pace=p, habits=h)
    assert score_item(23, ev(20))[0] <= score_item(23, ev(10))[0]

@pytest.mark.parametrize("n, want", [(0, 100), (1, 80), (4, 20), (5, 0), (6, 0)])
def test_24_긴_침묵_1건당_20점(n, want):
    score, reason = score_item(24, Evidence(transcript=tr("말", with_words=True), habits=habits(pause=n)))
    assert score == want and ("없었어요" in reason) == (n == 0) and "5초" in reason
    assert score_item(24, Evidence(transcript=tr("말"), habits=habits(pause=n))) is None  # 타임스탬프 없음
    assert score_item(24, Evidence(transcript=tr("말", with_words=True))) is None

# --- 27·28·31·32·33 — 시각자료·시간 ---

def test_27_화면을_그대로_읽으면_0점_자기_말로_풀면_만점():
    read = Evidence(slides=sdoc(slide(1, SLIDE_TEXT)), transcript=tr(by_slide={1: SLIDE_TEXT}))
    score, reason = score_item(27, read)
    assert score == 0 and "그대로 읽은" in reason and "1번" in reason
    own = Evidence(slides=sdoc(slide(1, SLIDE_TEXT)), transcript=tr(by_slide={1: "오늘은 날씨 이야기로 시작할게요 " * 3}))
    score, reason = score_item(27, own)
    assert score == 100 and "자기 말로" in reason

def test_27_짧은_슬라이드_발화_없는_슬라이드_figure_는_뺀다():
    assert score_item(27, Evidence(slides=sdoc(slide(1, "짧은 제목")), transcript=tr(by_slide={1: "짧은 제목"}))) is None
    assert score_item(27, Evidence(slides=sdoc(slide(1, SLIDE_TEXT)), transcript=tr(by_slide={2: SLIDE_TEXT}))) is None
    fig = Evidence(slides=sdoc(slide(1, SLIDE_TEXT, category="figure")), transcript=tr(by_slide={1: SLIDE_TEXT}))
    assert score_item(27, fig) is None
    assert score_item(27, Evidence(slides=sdoc(slide(1, SLIDE_TEXT)))) is None

def test_27_겹침은_슬라이드_평균이다():
    slides = sdoc(slide(1, SLIDE_TEXT), slide(2, SLIDE_TEXT))
    ev = Evidence(slides=slides, transcript=tr(by_slide={1: SLIDE_TEXT, 2: "전혀 다른 이야기를 길게 했어요 " * 3}))
    assert score_item(27, ev)[0] == det._band(0.5, det.READING_FREE_OVERLAP, det.READING_ZERO_OVERLAP) == 33

@pytest.mark.parametrize("statuses, want", [
    ((), 100), ((("core", "short"),), 86), ((("support", "long"),), 94),
    ((("core", "fast"), ("support", "slow")), 100), ((("core", "short"),) * 8, 0),
])
def test_28_배분_어긋남은_핵심_14점_보조_6점(statuses, want):
    sl = [SlidePace(i + 1, importance=imp, status=st) for i, (imp, st) in enumerate(statuses)]
    score, reason = score_item(28, Evidence(pace=pace(slides=sl or [SlidePace(1)])))
    assert score == want and ("나눠 썼어요" in reason) == (want == 100)
    assert score_item(28, Evidence(pace=pace())) is None

@pytest.mark.parametrize("actual, want, word", [
    (600, 100, "남겼어요"), (630, 100, "넘겼어요"), (570, 100, "남겼어요"), (636, 97, "넘겼어요"),
    (735, 50, "넘겼어요"), (465, 50, "남겼어요"), (840, 0, "넘겼어요"), (360, 0, "남겼어요"), (0, 0, "남겼어요"),
])
def test_31_제한시간_5퍼센트_안_만점_40퍼센트_밖_0점(actual, want, word):
    score, reason = score_item(31, Evidence(pace=pace(target=600, actual=actual)))
    assert score == want and word in reason and "목표 10분" in reason
    assert score_item(31, Evidence(pace=pace(target=0, actual=actual))) is None

@pytest.mark.parametrize("bad, want", [(0, 100), (1, 67), (2, 33), (3, 0)])
def test_32_구간_배분은_어긋난_구간_비율(bad, want):
    secs = [SectionAlloc(n, status="long" if i < bad else "ok", label="+34%" if i < bad else "")
            for i, n in enumerate(("전반", "중반", "후반"))]
    score, reason = score_item(32, Evidence(pace=pace(sections=secs)))
    assert score == want and ("모두" in reason) == (bad == 0) and ("전반+34%" in reason) == (bad > 0)
    assert score_item(32, Evidence(pace=pace())) is None

@pytest.mark.parametrize("delta, want", [(0, 100), (15, 100), (-15, 100), (16, 98), (37.5, 50), (-60, 0), (90, 0)])
def test_33_핵심_체류_15퍼센트_안_만점_60퍼센트_밖_0점(delta, want):
    sl = [SlidePace(1, importance="core", recommended_sec=100, delta_sec=delta),
          SlidePace(2, importance="support", recommended_sec=10, delta_sec=99),  # 보조는 안 본다
          SlidePace(3, importance="core", recommended_sec=0, delta_sec=99)]     # 권장 0 은 뺀다
    score, reason = score_item(33, Evidence(pace=pace(slides=sl)))
    assert score == want and ("권장 시간만큼" in reason) == (abs(delta) <= 15)
    if abs(delta) > 15:
        assert f"1번이 {delta:+.0f}초" in reason
    assert score_item(33, Evidence(pace=pace(slides=sl[1:]))) is None

# --- 34·36·38 — 슬라이드 텍스트 ---

@pytest.mark.parametrize("chars, want", [(50, 100), (150, 100), (151, 100), (335, 50), (520, 0), (600, 0)])
def test_34_밀도_평균_150자_이하_만점_520자_이상_0점(chars, want):
    ev = Evidence(slides=sdoc(slide(1, "가" * chars), slide(2, "")))  # 빈 장은 평균에서 뺀다
    score, reason = score_item(34, ev)
    assert score == want and ("빽빽해요" in reason) == (chars > 520)

def test_34_figure_블록은_밀도에_안_들어가고_전부_비면_못_잰다():
    heavy = Slide(1, blocks=[SlideBlock("paragraph", "가" * 100), SlideBlock("figure", "F" * 9000)])
    assert score_item(34, Evidence(slides=sdoc(heavy)))[0] == 100
    assert score_item(34, Evidence(slides=sdoc(slide(1, "")))) is None
    assert score_item(34, Evidence(slides=sdoc())) is None

def test_36_그래프_intro_구간이_먼저다():
    g = ConceptGraph("d", 3, sections=[Section("도입", slide_role="intro", slide_nos=[2])])
    assert score_item(36, Evidence(graph=g)) == (100, "2번이 발표 구조를 미리 알려 줘요")
    empty_intro = ConceptGraph("d", 3, sections=[Section("도입", slide_role="intro", slide_nos=[])])
    assert score_item(36, Evidence(graph=empty_intro, slides=sdoc(slide(1, "본문"))))[0] == det.ROADMAP_MISSING_SCORE

@pytest.mark.parametrize("title, body, want", [
    ("목차", "", 100), ("Agenda", "", 100), ("", "오늘의 발표 순서", 100), ("소개", "본문", 30),
])
def test_36_제목이나_앞머리의_목차_단서_없으면_30점(title, body, want):
    score, reason = score_item(36, Evidence(slides=sdoc(slide(1, body, title=title))))
    assert score == want and ("안 보여요" in reason) == (want == 30)

def test_38_근거_슬라이드_중_출처가_붙은_비율():
    slides = sdoc(
        slide(1, "2024년 매출 1,234억"), slide(2, "성장률 12.5% 출처: 통계청"),
        slide(3, "숫자 없음", visual=("chart",)), slide(4, "Smith et al. 2020 [1]"), slide(5, "숫자 12 두 개"),
    )
    score, reason = score_item(38, Evidence(slides=slides))
    assert score == 50 and "4장 중 2장" in reason and "(1, 3번)" in reason

def test_38_전부_출처가_있거나_근거_자료가_없으면_만점():
    assert score_item(38, Evidence(slides=sdoc(slide(1, "소개 문장")))) == (100, "출처를 밝혀야 할 통계나 인용 자료가 없어요")
    ok = sdoc(slide(1, "12 34 56 https://example.org"), slide(2, "1 2 3 참고문헌"))
    assert score_item(38, Evidence(slides=ok)) == (100, "근거 자료를 실은 2장 모두 출처를 밝혔어요")
    fig = Slide(1, blocks=[SlideBlock("figure", "12 34 56 출처")])  # 이미지 설명의 숫자는 안 센다
    assert score_item(38, Evidence(slides=sdoc(fig)))[0] == 100
    assert score_item(38, Evidence(slides=sdoc())) is None

# --- 단조성 — 나쁜 증거가 늘면 점수는 절대 안 오른다 ---

def _non_increasing(scores: list[int]) -> bool:
    return all(a >= b for a, b in zip(scores, scores[1:])) and scores[0] > scores[-1]

def test_지시어_모순_추가발화_침묵_배분어긋남이_늘면_점수가_내려간다():
    deixis = [score_item(17, Evidence(transcript=tr(" ".join(["저것"] * h + ["말"] * (50 - h)))))[0]
              for h in range(8)]
    contra = [score_item(4, Evidence(alignment=align([AlignmentItem(f"n{i}", verdict="contradiction", doc_weight=0.7)
                                                      for i in range(n)])))[0] for n in range(6)]
    extras = [score_item(5, Evidence(alignment=align([AlignmentItem(f"n{i}") for i in range(10)],
                                                     [ExtraConcept("x")] * n)))[0] for n in range(8)]
    pauses = [score_item(24, Evidence(transcript=tr("말", with_words=True), habits=habits(pause=n)))[0]
              for n in range(7)]
    alloc = [score_item(28, Evidence(pace=pace(slides=[SlidePace(i, importance="core", status="short" if i <= n else "ok")
                                                       for i in range(1, 9)])))[0] for n in range(9)]
    assert all(_non_increasing(s) for s in (deixis, contra, extras, pauses, alloc))
