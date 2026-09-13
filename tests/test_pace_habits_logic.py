"""F-17(말 속도)·F-18(음성 습관 heuristic) 규칙 로직 감사 테스트.

손으로 만든 작은 Transcript 로 모든 분기를 밟는다. LoRA(_lora_tagger)는 절대 로드하지 않는다 —
provider="heuristic" 을 강제하거나, lora 경로는 sys.modules 스텁으로만 폴백·병합 로직을 본다.
골든 값은 주석의 산수로 검증했다. 잘못된 동작은 xfail(strict) 로 표시하고 절대 고정하지 않는다.
"""

from __future__ import annotations

import json
import math
import sys
import types
from pathlib import Path

import pytest

from chuckchuck.contracts import (
    ConceptDoc,
    Context,
    HabitError,
    HabitSpan,
    PaceError,
    SlideConcepts,
    SlideSpeech,
    Transcript,
    Word,
)
from chuckchuck.f17_pace import analyze_pace, count_chars, count_syllables
from chuckchuck.f18_habits import PAUSE_SEC, _heuristic_spans, extract_habits

# ---------------------------------------------------------------------------
# 빌더
# ---------------------------------------------------------------------------


def W(text: str, s: float, e: float) -> Word:
    return Word(text=text, start_sec=s, end_sec=e)


def S(no: int, s: float, e: float, words: list[Word], text: str | None = None) -> SlideSpeech:
    txt = " ".join(w.text for w in words) if text is None else text
    return SlideSpeech(slide_no=no, visit=1, start_sec=s, end_sec=e, text=txt, words=words)


def T(slides: list[SlideSpeech], words: list[Word] | None = None, dur: float = 0.0) -> Transcript:
    ws = [w for sp in slides for w in sp.words] if words is None else words
    return Transcript(full_text=" ".join(w.text for w in ws), words=ws, by_slide=slides, duration_sec=dur)


def concept(*imps: tuple[int, str]) -> ConceptDoc:
    return ConceptDoc(file_name="x.pdf", total_slides=len(imps), slides=[
        SlideConcepts(slide_no=no, title=f"제목{no}", topic="", importance=imp) for no, imp in imps
    ])


def pace_two_slides() -> Transcript:
    """골든용. 1번: 0~10s 체류, 발화 0~3.0s, 글자 14. 2번: 10~40s 체류, 발화 12~14.5s, 글자 6."""
    return T([
        S(1, 0, 10, [W("안녕하세요", 0, 0.5), W("오늘", 0.5, 1.0), W("발표", 1.0, 1.5), W("시작합니다", 1.5, 3.0)]),
        S(2, 10, 40, [W("핵심", 12, 12.5), W("AI", 12.5, 13), W("모델", 13.5, 14.5)]),
    ])


def habit_two_slides() -> Transcript:
    """1번: 간투어 2(음…, 그니까)·반복 1(지도 지도)·휴지 1(3.2→9.0 = 5.8s). 2번: 간투어 1(어)·'다음'×3."""
    return T([
        S(1, 0, 20, [
            W("음…", 0, 0.3), W("오늘은", 0.3, 0.8), W("그니까", 0.8, 1.3), W("지도", 1.3, 1.6),
            W("지도", 1.6, 2.0), W("그리고", 2.0, 2.4), W("저는", 2.4, 2.8), W("발표", 2.8, 3.2),
            W("합니다", 9.0, 9.5),
        ]),
        S(2, 20, 40, [
            W("어", 20, 20.2), W("다음", 20.2, 20.6), W("다음", 20.6, 21.0), W("다음", 21.0, 21.4),
            W("슬라이드", 21.4, 22.0),
        ]),
    ])


def _heur(t: Transcript):
    return extract_habits(t, provider="heuristic")


# ---------------------------------------------------------------------------
# F-17 골든 (산수는 주석)
# ---------------------------------------------------------------------------


def test_pace_golden_without_concepts():
    # 1번: chars 5+2+2+5=14, speak 3.0 → cpm 14/3*60 = 280.0, syl 14 → sps 4.67
    # 2번: chars 2+2+2=6, speak 14.5-12=2.5 → cpm 144.0, syl 2+1+2=5 → sps 2.0
    # speaking 5.5 → avg_cpm 20/5.5*60 = 218.18 → 218.2, avg_sps 19/5.5 = 3.45
    # target 60 (duration_min=1), support 0.35 씩 → rec 30/30. actual 10+30 = 40
    p = analyze_pace(pace_two_slides(), Context(duration_min=1), None)
    s1, s2 = p.slides
    assert (p.target_sec, p.actual_sec) == (60.0, 40.0)
    assert (s1.chars_per_min, s1.syllable_per_sec) == (280.0, 4.67)
    assert (s2.chars_per_min, s2.syllable_per_sec) == (144.0, 2.0)
    assert (p.avg_chars_per_min, p.avg_syllable_per_sec) == (218.2, 3.45)
    assert (p.max_chars_per_min, p.max_slide_no) == (280.0, 1)
    assert (s1.recommended_sec, s2.recommended_sec) == (30.0, 30.0)
    # 1번: 10/30 = 0.33 < 0.75 → short, int((1-0.333)*100) = 66
    assert (s1.status, s1.note) == ("short", "권장 대비 66% 부족")
    # 2번: 30/30 ok 범위, cpm 144 ≤ 218.18*0.75 = 163.6 → slow
    assert s2.status == "slow"
    # 섹션: core 없음 → support 만. rec 60, act 40 → r 0.667 → short "-33% 부족"
    assert [(x.name, x.status, x.label) for x in p.sections] == [("보조(support)", "short", "-33% 부족")]
    assert p.tips == ["목표 시간보다 짧아요. 핵심 슬라이드에 예시나 한 문장을 더 넣어 보세요."]


def test_pace_golden_with_core_concept():
    # 1번 core(1.0) + 2번 support(0.35) → Σ 1.35. rec1 = 60/1.35 = 44.44, rec2 = 21/1.35 = 15.56
    # 1번 act 10 → 1-10/44.44 = 0.775 → "핵심 · 권장 대비 77% 부족"
    # 2번 act 30/15.56 = 1.929 → long, int(0.929*100) = 92
    p = analyze_pace(pace_two_slides(), Context(duration_min=1), concept((1, "core"), (2, "support")))
    s1, s2 = p.slides
    assert (s1.title, s1.importance, s1.importance_weight) == ("제목1", "core", 1.0)
    assert (s1.recommended_sec, s2.recommended_sec) == (44.44, 15.56)
    assert (s1.status, s1.note) == ("short", "핵심 · 권장 대비 77% 부족")
    assert (s2.status, s2.note) == ("long", "권장 대비 92% 초과")
    assert [(x.name, x.slide_nos, x.status) for x in p.sections] == [
        ("핵심(core)", [1], "short"), ("보조(support)", [2], "long"),
    ]
    assert any(t.startswith("1번은 핵심인데 권장 44초 중 10초만") for t in p.tips)


def test_pace_target_falls_back_to_actual_when_no_context():
    # Context 없음 → target = actual 40. rec 20/20. 1번 10/20 = 0.5 short, 2번 30/20 = 1.5 long
    p = analyze_pace(pace_two_slides(), None, None)
    assert p.target_sec == 40.0
    assert [s.status for s in p.slides] == ["short", "long"]
    # duration_min=None 인 Context 도 같은 폴백
    assert analyze_pace(pace_two_slides(), Context(), None).target_sec == 40.0


def test_pace_fast_and_stable_tips():
    # 두 슬라이드 모두 30s 체류·발화 10s. 1번 글자 10 → 60cpm, 2번 글자 30 → 180cpm.
    # avg = 40/20*60 = 120. 2번 180 ≥ 144 → fast. 1번 60 ≤ 90 → slow. target 60 = actual 60.
    t = T([
        S(1, 0, 30, [W("가나다라마", 0, 5), W("바사아자차", 5, 10)]),
        S(2, 30, 60, [W("가나다라마바사아자차", 30, 35), W("가나다라마바사아자차가나다라마바사아자차", 35, 40)]),
    ])
    p = analyze_pace(t, Context(duration_min=1), concept((1, "core"), (2, "core")))
    assert [s.status for s in p.slides] == ["slow", "fast"]
    assert p.slides[1].note == "이 구간 말이 평균보다 빨라요"
    assert any("2번(핵심)에서 말이 빨라요(180자/분)" in tip for tip in p.tips)
    # 글자 수를 맞추면 전부 ok → 안정 팁 하나만
    t2 = T([
        S(1, 0, 30, [W("가나다라마", 0, 5), W("바사아자차", 5, 10)]),
        S(2, 30, 60, [W("가나다라마", 30, 35), W("바사아자차", 35, 40)]),
    ])
    p2 = analyze_pace(t2, Context(duration_min=1), None)
    assert [s.status for s in p2.slides] == ["ok", "ok"]
    assert p2.tips == ["시간 배분과 말 속도가 대체로 안정적이에요."]


def test_pace_over_target_tips_support_vs_core():
    # target 30(0.5분) vs actual 40 → over 10초. rec 15/15: 1번 10/15 = 0.67 short, 2번 30/15 = 2 long
    p = analyze_pace(pace_two_slides(), Context(duration_min=0.5), None)
    assert [s.status for s in p.slides] == ["short", "long"]
    assert p.tips[0] == "목표보다 10초 길어요. 덜 중요한 2번을(를) 빠르게 줄여 보세요."
    # 전부 core 면 long support 가 없어 else 분기
    p2 = analyze_pace(pace_two_slides(), Context(duration_min=0.5), concept((1, "core"), (2, "core")))
    assert p2.tips[0] == "목표보다 10초 길어요. 보조 슬라이드 설명을 한 문장씩 줄여 보세요."


def test_pace_accepts_dicts_and_unknown_importance():
    t = pace_two_slides().to_dict()
    cd = concept((1, "weird"), (2, "core")).to_dict()
    p = analyze_pace(t, {"duration_min": 1}, cd)
    assert p.target_sec == 60.0
    assert p.slides[0].importance == "support"  # 모르는 importance 는 support 로


# ---------------------------------------------------------------------------
# F-17 엣지·속성
# ---------------------------------------------------------------------------


def test_pace_empty_transcript_raises():
    with pytest.raises(PaceError):
        analyze_pace(Transcript(full_text=""))


def test_pace_single_word_and_zero_duration_do_not_divide_by_zero():
    # 발화 0s → speak_sec 0 → 체류 10s 로 폴백: 3/10*60 = 18
    p = analyze_pace(T([S(1, 0, 10, [W("가나다", 2, 2)])]))
    assert p.slides[0].chars_per_min == 18.0
    # 체류도 0 → 전부 0, 예외 없음, target 폴백 1.0
    p0 = analyze_pace(T([S(1, 0, 0, [W("가나다", 2, 2)])]))
    assert (p0.slides[0].chars_per_min, p0.actual_sec, p0.target_sec) == (0.0, 0.0, 1.0)
    # 발화 0.2s 이하는 속도 계산 안 함
    assert analyze_pace(T([S(1, 0, 10, [W("가나다", 0, 0.2)])])).slides[0].chars_per_min == 0.0


def test_pace_slide_without_words_and_text_only_slide():
    # words·text 둘 다 없는 슬라이드는 버린다. text 만 있으면 체류 시간을 발화로 쓴다.
    t = T([S(1, 0, 5, [], text=""), S(2, 5, 10, [], text="가나다라"), S(3, 10, 20, [W("마바", 10, 11)])])
    p = analyze_pace(t)
    assert [s.slide_no for s in p.slides] == [2, 3]
    assert p.slides[0].chars_per_min == 48.0  # 4/5*60
    assert p.actual_sec == 15.0


def test_pace_no_by_slide_falls_back_to_single_bucket():
    # by_slide 없음 → 1번 슬라이드 하나. duration_sec 0 → 마지막 end - 첫 start = 2s. 4자 → 120cpm
    t = T([], words=[W("가나", 0, 1), W("다라", 1, 2)])
    p = analyze_pace(t)
    assert [(s.slide_no, s.title, s.chars_per_min) for s in p.slides] == [(1, "1번 슬라이드", 120.0)]
    # duration_sec 가 있으면 그것을 체류로 쓴다
    assert analyze_pace(T([], words=[W("가나", 0, 1)], dur=30.0)).actual_sec == 30.0


def test_pace_revisit_is_merged_and_sections_split_in_thirds():
    t = T([S(n, (n - 1) * 10, n * 10, [W("가나다", (n - 1) * 10, (n - 1) * 10 + 1)]) for n in range(1, 7)]
          + [S(1, 60, 70, [W("라마", 60, 61)])])
    p = analyze_pace(t, Context(duration_min=1))
    assert len(p.slides) == 6
    assert p.slides[0].actual_sec == 20.0  # 재방문 합산
    assert [x.name for x in p.sections] == ["전반", "중반", "후반"]
    assert [x.slide_nos for x in p.sections] == [[1, 2], [3, 4], [5, 6]]


def test_pace_properties_on_fixture_and_handmade(fixture_transcript):
    for t, ctx in ((fixture_transcript, Context(duration_min=10)), (pace_two_slides(), None)):
        p = analyze_pace(t, ctx)
        assert p.avg_chars_per_min >= 0 and math.isfinite(p.avg_chars_per_min)
        for s in p.slides:
            assert s.chars_per_min >= 0 and math.isfinite(s.chars_per_min)
            assert s.syllable_per_sec >= 0 and math.isfinite(s.syllable_per_sec)
            assert s.status in ("ok", "short", "long", "fast", "slow")
            assert s.delta_sec == pytest.approx(s.actual_sec - s.recommended_sec, abs=0.02)
        assert sum(s.recommended_sec for s in p.slides) == pytest.approx(p.target_sec, abs=0.05)
        assert sum(s.actual_sec for s in p.slides) == pytest.approx(p.actual_sec, abs=0.05)


def test_pace_per_slide_cpm_matches_chars_over_speech_minutes():
    t = pace_two_slides()
    p = analyze_pace(t)
    for sp, s in zip(t.by_slide, p.slides):
        chars = sum(count_chars(w.text) for w in sp.words)
        speak_min = (sp.words[-1].end_sec - sp.words[0].start_sec) / 60.0
        assert s.chars_per_min == pytest.approx(chars / speak_min, abs=0.1)


def test_pace_does_not_mutate_input():
    t = pace_two_slides()
    before = t.to_dict()
    analyze_pace(t, Context(duration_min=1), concept((1, "core"), (2, "support")))
    assert t.to_dict() == before


def test_count_helpers():
    assert count_syllables("안녕 AI Contrastive") == 2 + 1 + 4  # (2+2)//3=1, (11+2)//3=4
    assert count_chars(" 안녕 하세요 ") == 5
    assert count_syllables("") == 0 and count_chars(None) == 0


# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_pace_unordered_words_same_cpm_as_sorted():
    # 정렬: 발화 2~6 = 4s, 5자 → 75cpm. 뒤집으면 6-... 음수 → 0 → 체류 10s 폴백 → 30cpm
    ordered = T([S(1, 0, 10, [W("가나다", 2, 3), W("라마", 5, 6)])])
    shuffled = T([S(1, 0, 10, [W("라마", 5, 6), W("가나다", 2, 3)])])
    assert analyze_pace(ordered).slides[0].chars_per_min == 75.0
    assert analyze_pace(shuffled).slides[0].chars_per_min == 75.0


# ---------------------------------------------------------------------------
# F-18 heuristic 골든
# ---------------------------------------------------------------------------


def test_habits_golden_two_slides():
    d = _heur(habit_two_slides())
    assert d.provider == "heuristic"
    fil = [s for s in d.spans if s.kind == "FIL"]
    assert [s.text for s in fil] == ["음…", "그니까", "어"]  # 그리고·저는 은 간투어가 아니다
    assert [s.slide_no for s in fil] == [1, 1, 2]
    assert d.filler_cnt == 3
    # 휴지: 3.2 → 9.0 = 5.8s ≥ 5.0. 슬라이드 경계(2번 시작 20.0) 앞뒤 9.5→20.0 = 10.5s 는 다른 슬라이드라 제외
    pauses = [s for s in d.spans if s.kind == "PAUSE"]
    assert [(s.text, s.start_sec, s.end_sec, s.slide_no) for s in pauses] == [("5.8s", 3.2, 9.0, 1)]
    assert d.pause_cnt == 1
    s1 = next(x for x in d.by_slide if x.slide_no == 1)
    assert (s1.repeat_cnt, s1.filler_cnt, s1.pause_cnt) == (1, 2, 1)
    assert s1.note == "긴 휴지 1회"
    assert "5초 이상 긴 쉼이 1번 있어요. 전환 멘트를 미리 정해 보세요." in d.tips


def test_habits_repeat_runs():
    two = T([S(1, 0, 5, [W("지도", 0, 0.4), W("지도", 0.4, 0.8), W("중요", 0.8, 1.2)])])
    reps = [s for s in _heuristic_spans(two) if s.kind == "REP"]
    assert [(s.text, s.start_sec, s.end_sec) for s in reps] == [("지도 지도", 0, 0.8)]
    three = T([S(1, 0, 5, [W("지도", 0, 0.4), W("지도", 0.4, 0.8), W("지도", 0.8, 1.2)])])
    reps3 = [s for s in _heuristic_spans(three) if s.kind == "REP"]
    assert len(reps3) >= 1  # 3연속을 1회로 볼지 2회로 볼지는 스펙 미정 (현재 2회)
    assert all(0 <= s.start_sec < s.end_sec <= 1.2 for s in reps3)
    # 대소문자·구두점 무시
    ai = T([S(1, 0, 5, [W("AI,", 0, 0.4), W("ai", 0.4, 0.8)])])
    assert sum(1 for s in _heuristic_spans(ai) if s.kind == "REP") == 1


@pytest.mark.parametrize("gap,expected", [(PAUSE_SEC - 0.01, 0), (PAUSE_SEC, 1), (PAUSE_SEC + 0.01, 1)])
def test_habits_pause_threshold_inclusive(gap, expected):
    t = T([S(1, 0, 30, [W("가", 0, 1), W("나", 1 + gap, 2 + gap)])])
    assert _heur(t).pause_cnt == expected


def test_habits_pause_count_equals_in_slide_gaps(fixture_transcript):
    """같은 슬라이드 안에서 PAUSE_SEC 이상 벌어진 간격 수 == pause_cnt (실 fixture 로)."""
    d = _heur(fixture_transcript)
    ws = fixture_transcript.words
    expected = 0
    for sp in fixture_transcript.by_slide:
        idx = [i for i, w in enumerate(ws) if sp.words and sp.words[0].start_sec <= w.start_sec <= sp.words[-1].end_sec]
        expected += sum(1 for a, b in zip(idx, idx[1:]) if ws[b].start_sec - ws[a].end_sec >= PAUSE_SEC)
    assert d.pause_cnt == expected >= 1


def test_habits_spans_lie_inside_their_slide(fixture_transcript):
    for t in (fixture_transcript, habit_two_slides()):
        d = _heur(t)
        rng = {sp.slide_no: (sp.start_sec, sp.end_sec) for sp in t.by_slide}
        for s in d.spans:
            lo, hi = rng[s.slide_no]
            assert lo <= s.start_sec <= s.end_sec <= hi, s
        assert d.repeat_cnt == sum(x.repeat_cnt for x in d.by_slide)
        assert d.filler_cnt == sum(x.filler_cnt for x in d.by_slide)
        assert d.pause_cnt == sum(x.pause_cnt for x in d.by_slide)


def test_habits_fillers_not_matched_inside_other_words():
    t = T([S(1, 0, 5, [W("그리고", 0, 0.3), W("음악", 0.3, 0.6), W("어제", 0.6, 0.9), W("좀", 0.9, 1.1), W("그", 1.1, 1.2)])])
    assert [s.text for s in _heuristic_spans(t) if s.kind == "FIL"] == ["좀", "그"]


def test_habits_words_from_by_slide_when_top_level_empty_and_nearest_slide():
    # transcript.words 비어 있으면 by_slide 의 words 를 쓴다. 11.0 은 어느 슬라이드에도 없어 가까운 2번(중점 15)
    t = T([S(1, 0, 10, [W("음", 0, 0.3)]), S(2, 12, 18, [W("어", 12.0, 12.2)])], words=[])
    d = _heur(t)
    assert [(s.text, s.slide_no) for s in d.spans] == [("음", 1), ("어", 2)]
    # 어느 슬라이드 구간에도 없는 11.0 → 중점 거리 |11-5|=6 vs |11-15|=4 → 2번
    d2 = extract_habits(t, spans=[HabitSpan(kind="FIL", text="어", start_sec=11.0, end_sec=11.1)])
    assert d2.spans[0].slide_no == 2


def test_habits_notes_and_default_tip():
    # REP 2 · FIL 3 → 두 문구 모두 (REP 는 다른 단어 두 쌍으로 2회)
    t = T([S(1, 0, 5, [W("가", 0, .2), W("가", .2, .4), W("나", .4, .6), W("나", .6, .8),
                       W("음", .8, 1), W("음", 1, 1.2), W("어", 1.2, 1.4)])])
    d = _heur(t)
    s1 = d.by_slide[0]
    assert (s1.repeat_cnt, s1.filler_cnt) == (3, 3)
    assert s1.note == "같은 장을 더듬으며 반복 3회 · 간투어 3회"
    assert d.tips[0] == f"1번: {s1.note}"
    quiet = _heur(T([S(1, 0, 5, [W("발표", 0, 0.5), W("시작", 0.5, 1)])]))
    assert quiet.tips == ["눈에 띄는 반복·간투어·긴 휴지는 적어요."]
    assert [x.slide_no for x in quiet.by_slide] == [1]


def test_habits_empty_input_and_unknown_provider():
    with pytest.raises(HabitError):
        extract_habits(Transcript(full_text=""), provider="heuristic")
    with pytest.raises(HabitError):
        extract_habits(habit_two_slides(), provider="nope")


def test_habits_env_var_forces_heuristic(monkeypatch):
    monkeypatch.setenv("HABIT_PROVIDER", "heuristic")
    d = extract_habits(habit_two_slides().to_dict())  # dict 입력 + 환경변수 경로
    assert d.provider == "heuristic"
    assert d.filler_cnt == 3


def test_habits_fixture_spans_path_fills_slide_from_time():
    t = habit_two_slides()
    d = extract_habits(t, spans=[{"kind": "FIL", "text": "어", "start_sec": 20.0, "end_sec": 20.2},
                                 {"kind": "BAD", "text": "?", "start_sec": 1.0, "end_sec": 1.1, "slide_no": 1}])
    assert d.provider == "fixture"
    assert [(s.kind, s.slide_no) for s in d.spans] == [("FIL", 2), ("FIL", 1)]  # BAD→FIL, 시간으로 2번
    assert d.filler_cnt == 2 and d.repeat_cnt == 0


def test_habits_lora_stub_fallback_and_merge(monkeypatch):
    """실 _lora_tagger 는 절대 import 하지 않는다 — sys.modules 스텁으로 폴백·병합 분기만 밟는다."""
    t = habit_two_slides()
    stub = types.SimpleNamespace(adapter_available=lambda: False, tag_spans=lambda tr: [])
    monkeypatch.setitem(sys.modules, "chuckchuck._lora_tagger", stub)
    monkeypatch.delenv("HABIT_PROVIDER", raising=False)
    assert extract_habits(t).provider == "heuristic(lora-fallback)"
    # 어댑터 있음 + REP 만 반환 → FIL·PAUSE 는 heuristic 보강, REP 는 LoRA 것만
    rep = HabitSpan(kind="REP", text="지도 지도", start_sec=1.3, end_sec=2.0, slide_no=1)
    stub2 = types.SimpleNamespace(adapter_available=lambda: True, tag_spans=lambda tr: [rep])
    monkeypatch.setitem(sys.modules, "chuckchuck._lora_tagger", stub2)
    d = extract_habits(t, provider="lora")
    assert d.provider == "lora"
    assert (d.repeat_cnt, d.filler_cnt, d.pause_cnt) == (1, 3, 1)
    # LoRA 가 FIL 만 주면 REP·PAUSE 를 heuristic 으로 보강
    fil = HabitSpan(kind="FIL", text="음…", start_sec=0, end_sec=0.3, slide_no=1)
    monkeypatch.setitem(sys.modules, "chuckchuck._lora_tagger",
                        types.SimpleNamespace(adapter_available=lambda: True, tag_spans=lambda tr: [fil]))
    d2 = extract_habits(t, provider="lora")
    assert (d2.filler_cnt, d2.pause_cnt) == (1, 1) and d2.repeat_cnt >= 1
    # tag_spans 예외 · import 실패(None 스텁) → heuristic 폴백
    for bad in (types.SimpleNamespace(adapter_available=lambda: True, tag_spans=lambda tr: 1 / 0), None):
        monkeypatch.setitem(sys.modules, "chuckchuck._lora_tagger", bad)
        assert extract_habits(t, provider="lora").provider == "heuristic(lora-fallback)"


def test_habits_does_not_mutate_transcript():
    t = habit_two_slides()
    before = t.to_dict()
    _heur(t)
    assert t.to_dict() == before


# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_habits_prefix_repeat_span_covers_the_two_repeated_words():
    t = T([S(1, 0, 3, [W("지도", 0, 0.4), W("지도력은", 0.4, 1.0), W("중요합니다", 1.0, 1.6)])])
    reps = [s for s in _heuristic_spans(t) if s.kind == "REP"]
    assert [(s.text, s.start_sec, s.end_sec) for s in reps] == [("지도 지도력은", 0, 1.0)]


# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_habits_prefix_repeat_at_end_of_transcript_is_detected():
    t = T([S(1, 0, 3, [W("지도", 0, 0.4), W("지도력은", 0.4, 1.0)])])
    assert sum(1 for s in _heuristic_spans(t) if s.kind == "REP") == 1


# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_habits_fixture_path_does_not_mutate_caller_spans():
    span = HabitSpan(kind="FIL", text="어", start_sec=20.0, end_sec=20.2, slide_no=None)
    extract_habits(habit_two_slides(), spans=[span])
    assert span.slide_no is None


@pytest.fixture
def fixture_transcript() -> Transcript:
    root = Path(__file__).resolve().parent.parent
    return Transcript.from_dict(json.loads((root / "fixtures/focus_transcript.json").read_text(encoding="utf-8")))
