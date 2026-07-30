"""
F-14 말 속도·시간 배분의 성질을 고정합니다.

여기서 지켜야 할 판단 셋:
- 빠름/느림은 **본인 평균 기준**이다. 절대 기준으로 재면 원래 빠른 사람은
  전 구간이 빨갛게 뜨고, 그건 피드백이 아니라 잡음이다.
- 짧은 구간의 자/분은 못 믿는다. 한두 마디로 값이 튀므로 reliable=False 로 표시한다.
- 시간 배분의 '권장' 은 자료가 배분한 weight 다. 임의의 이상적 배분이 아니다.
"""

from __future__ import annotations

import pytest

from chuckchuck.contracts import (
    ConceptGraph,
    ConceptNode,
    Section,
    SlideSpeech,
    Transcript,
)
from chuckchuck.f14_pace import MIN_RELIABLE_SEC, analyze_pace


def speech(slide_no: int, start: float, end: float, text: str) -> SlideSpeech:
    return SlideSpeech(slide_no=slide_no, visit=1, start_sec=start, end_sec=end, text=text)


def make_transcript(parts: list[SlideSpeech]) -> Transcript:
    return Transcript(
        full_text=" ".join(p.text for p in parts),
        by_slide=list(parts),
        provider="test",
        duration_sec=max((p.end_sec for p in parts), default=0.0),
    )


def steady(n_slides: int = 4, chars: int = 150, dur: float = 30.0) -> Transcript:
    """모든 구간이 같은 속도인 발화 (150자 / 30초 = 300자/분)."""
    return make_transcript([
        speech(i + 1, i * dur, (i + 1) * dur, "가" * chars)
        for i in range(n_slides)
    ])


# ---------------------------------------------------------------------------
# 속도 계산
# ---------------------------------------------------------------------------


def test_자분은_공백을_뺀_글자수로_잰다():
    """띄어쓰기 습관이 속도에 섞이면 안 된다."""
    tight = make_transcript([speech(1, 0, 60, "가" * 300)])
    spaced = make_transcript([speech(1, 0, 60, " ".join("가" * 300))])
    assert tight.by_slide[0].text != spaced.by_slide[0].text
    assert analyze_pace(tight).avg_cpm == analyze_pace(spaced).avg_cpm == 300


def test_구간별_속도가_계산된다():
    doc = analyze_pace(steady())
    assert len(doc.segments) == 4
    assert [round(s.cpm) for s in doc.segments] == [300, 300, 300, 300]


def test_길이가_0인_구간은_나눗셈을_안_태운다():
    doc = analyze_pace(make_transcript([speech(1, 10, 10, "말했다")]))
    assert doc.segments[0].cpm == 0
    assert doc.avg_cpm == 0


def test_발화가_비어도_안_터진다():
    doc = analyze_pace(Transcript(full_text="", by_slide=[], duration_sec=0))
    assert doc.avg_cpm == 0
    assert doc.segments == []
    assert doc.fastest is None and doc.slowest is None


def test_마크가_없으면_전체_전사로_평균을_낸다():
    """by_slide 가 비면 구간은 못 나눠도 전체 속도는 알려줘야 한다."""
    t = Transcript(full_text="가" * 600, by_slide=[], duration_sec=120.0)
    assert analyze_pace(t).avg_cpm == 300


# ---------------------------------------------------------------------------
# 빠름 / 느림 판정
# ---------------------------------------------------------------------------


def test_고른_속도에서는_아무_구간도_빠르지_않다():
    doc = analyze_pace(steady())
    assert not any(s.is_fast or s.is_slow for s in doc.segments)


def test_평균보다_확실히_빠른_구간만_빠름으로_찍힌다():
    t = make_transcript([
        speech(1, 0, 30, "가" * 150),     # 300
        speech(2, 30, 60, "가" * 150),    # 300
        speech(3, 60, 90, "가" * 250),    # 500 — 빠름
    ])
    doc = analyze_pace(t)
    flags = {s.slide_no: s.is_fast for s in doc.segments}
    assert flags == {1: False, 2: False, 3: True}
    assert doc.fastest.slide_no == 3


def test_판정은_절대값이_아니라_본인_평균_기준이다():
    """전 구간이 권장(300~350)보다 빨라도, 고르면 빠름이 하나도 안 뜬다."""
    fast_speaker = make_transcript([
        speech(i + 1, i * 30, (i + 1) * 30, "가" * 300)  # 600자/분
        for i in range(3)
    ])
    doc = analyze_pace(fast_speaker)
    assert doc.avg_cpm == 600
    assert not any(s.is_fast for s in doc.segments)


def test_짧은_구간은_못_믿는다고_표시한다():
    t = make_transcript([
        speech(1, 0, 60, "가" * 300),
        speech(2, 60, 60 + MIN_RELIABLE_SEC - 1, "가" * 90),   # 너무 짧다
    ])
    doc = analyze_pace(t)
    assert doc.segments[0].reliable is True
    assert doc.segments[1].reliable is False
    # 못 믿는 구간은 최고/최저 후보에서 빠진다
    assert doc.fastest.slide_no == 1


# ---------------------------------------------------------------------------
# 시간 배분
# ---------------------------------------------------------------------------


def make_graph() -> ConceptGraph:
    """앞 구획이 무겁고(weight 1.0) 뒤 구획이 가벼운(0.2) 자료."""
    return ConceptGraph(
        file_name="deck.pdf",
        total_slides=4,
        nodes=[
            ConceptNode(id="a", label="핵심", slide_nos=[1, 2], weight=1.0),
            ConceptNode(id="b", label="곁가지", slide_nos=[3, 4], weight=0.2),
        ],
        sections=[
            Section(name="본론", slide_nos=[1, 2]),
            Section(name="마무리", slide_nos=[3, 4]),
        ],
    )


def test_그래프가_없으면_시간_배분은_비어_있다():
    assert analyze_pace(steady()).allocations == []


def test_권장_비율은_자료가_배분한_weight_다():
    doc = analyze_pace(steady(), make_graph())
    rec = {a.name: round(a.recommended_pct) for a in doc.allocations}
    # 1.0 vs 0.2 → 83% / 17%
    assert rec == {"본론": 83, "마무리": 17}


def test_무거운_구획에_시간을_안_쓰면_부족으로_잡힌다():
    """네 구간에 시간을 똑같이 썼는데 자료는 앞쪽에 힘을 실었다."""
    doc = analyze_pace(steady(), make_graph())
    by = {a.name: a for a in doc.allocations}
    assert by["본론"].actual_pct == pytest.approx(50.0)
    assert by["본론"].verdict() == "under"      # 83% 권장인데 50% 만 썼다
    assert by["마무리"].verdict() == "over"     # 17% 권장인데 50% 를 썼다


def test_실제_비율의_합은_100이다():
    doc = analyze_pace(steady(), make_graph())
    assert sum(a.actual_pct for a in doc.allocations) == pytest.approx(100.0)


def test_구간에_그래프_개념_이름이_붙는다():
    doc = analyze_pace(steady(), make_graph())
    assert doc.segments[0].label == "핵심"
    assert doc.segments[2].label == "곁가지"


# ---------------------------------------------------------------------------
# 직렬화
# ---------------------------------------------------------------------------


def test_직렬화가_계약을_지킨다():
    d = analyze_pace(steady(), make_graph()).to_dict()
    assert set(d) == {
        "file_name", "total_sec", "total_chars", "avg_cpm",
        "recommended_min", "recommended_max",
        "segments", "allocations", "fastest", "slowest",
    }
    assert set(d["segments"][0]) == {
        "slide_no", "label", "start_sec", "end_sec", "chars",
        "cpm", "is_fast", "is_slow", "reliable",
    }
    assert set(d["allocations"][0]) == {
        "name", "slide_nos", "recommended_pct", "actual_pct",
        "actual_sec", "gap_pct", "verdict",
    }
