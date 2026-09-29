"""
리포트 문장이 잰 값과 같은 말을 한다 (09-30 녹음 대화 감사 REC-15 — qa/report2).

LLM 은 문장만 쓴다. 문장의 말 속도 방향·자/분 수는 F-17 이 잰 값과 맞아야 하고(116자/분을 「너무 빨라서」 라고 쓰면 그 문장을 빼고 코드
문장으로 채운다), 내부 이름(자분·SPS·REP·core)은 프롬프트에 싣지 않으며 새어 나온 것은 사람 말로 바꾼다. 구간 이름도 사람 말이다.
재료는 감사의 kiosk R1 리포트 문장 그대로다.
"""

from __future__ import annotations

import json

from chuckchuck.contracts import (
    ConceptDoc,
    Context,
    HabitDoc,
    PaceDoc,
    ReportDoc,
    RubricScore,
    SlideConcepts,
    SlidePace,
    SlideSpeech,
    Transcript,
    Word,
)
from chuckchuck.f17_pace import analyze_pace
from chuckchuck.f19_report import _checked, _facts_block, _humanize, compose_report
from chuckchuck.providers.llm_base import LLMProvider

# ---------------------------------------------------------------------------
# 재료
# ---------------------------------------------------------------------------


def talk(*segs: tuple[int, str], sec: float = 30.0) -> Transcript:
    """(장, 발화) → 장마다 sec 초, 낱말마다 시각이 있는 Transcript."""
    by_slide, words, t = [], [], 0.0
    for no, text in segs:
        toks = text.split()
        step = sec / max(1, len(toks))
        ws = [Word(tok, round(t + k * step, 2), round(t + (k + 1) * step, 2)) for k, tok in enumerate(toks)]
        words += ws
        by_slide.append(SlideSpeech(no, 1, t, t + sec, text, ws))
        t += sec
    return Transcript(full_text=" ".join(x for _, x in segs), words=words, by_slide=by_slide,
                      provider="clova", duration_sec=t)


CTX = Context(situation="school_project", duration_min=5)


class Scripted(LLMProvider):
    """정해 둔 리포트 JSON 을 돌려주고 부른 횟수를 센다."""

    name = "scripted"

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def complete(self, **_) -> str:
        self.calls += 1
        return json.dumps(self.payload, ensure_ascii=False)


def slow_pace() -> PaceDoc:
    """감사 kiosk R1 과 같은 꼴 — 평균 116.3자/분(권장 300~350보다 느림), 7장만 내 평균보다 빠름."""
    slides = [SlidePace(slide_no=n, title=f"{n}장", importance="core" if n <= 5 else "support",
                        actual_sec=35.0, recommended_sec=90.0, chars_per_min=c, status=st)
              for n, c, st in ((1, 110.0, "short"), (2, 118.0, "short"), (3, 0.0, "short"), (4, 120.4, "short"),
                               (5, 96.2, "short"), (6, 101.0, "ok"), (7, 164.0, "fast"), (8, 112.0, "ok"))]
    return PaceDoc(target_sec=600.0, actual_sec=295.0, avg_chars_per_min=116.3, max_chars_per_min=164.0,
                   max_slide_no=7, slides=slides, tips=["목표 시간보다 짧아요. 핵심 슬라이드에 예시나 한 문장을 더 넣어 보세요."])


HABITS = HabitDoc(repeat_cnt=0, filler_cnt=3, pause_cnt=0, provider="heuristic")


# ---------------------------------------------------------------------------
# 구간 이름 (F-17)
# ---------------------------------------------------------------------------

def test_section_names_are_user_words_not_importance_labels():
    """「핵심(core)이 계획보다 63% 모자랐어요」 — 구간 이름은 화면·채점 근거·리포트에 그대로 나간다 (REC-15)."""
    two = talk((1, "가나다라 마바사"), (2, "아자차카 타파하"), sec=20.0)
    concepts = ConceptDoc("d.pdf", 2, [SlideConcepts(slide_no=1, title="a", topic="", importance="core"),
                                       SlideConcepts(slide_no=2, title="b", topic="", importance="support")])
    names = [s.name for s in analyze_pace(two, Context(duration_min=1), concepts).sections]
    assert names == ["핵심 장", "보조 장"]
    assert not any("core" in n or "support" in n or "(" in n for n in names)


# ---------------------------------------------------------------------------
# 문장의 말 속도 방향·수 · 내부 이름 (F-19)
# ---------------------------------------------------------------------------

def _doc(**kw) -> ReportDoc:
    base = {"one_liner": "", "strengths": [], "weaknesses": [], "actions": [], "pace_summary": "", "habit_summary": ""}
    return ReportDoc(**{**base, **kw})


def test_opposite_speed_direction_is_replaced_with_the_measured_one():
    """감사 kiosk R1 그대로 — 116자/분(느림)을 「너무 빨라서」 · 「천천히 말해 보세요」 라고 썼다."""
    doc = _checked(_doc(
        one_liner="말 속도가 너무 빠르고, 핵심 슬라이드 3장을 건너뛰어 내용이 부족했어요. 특히 3번 슬라이드를 한 문장이라도 설명하고 넘어가면 더 좋을 거예요.",
        weaknesses=["말 속도가 너무 빨라서(116자/분) 청중이 따라가기 힘들었어요. 특히 슬라이드 3번을 통째로 건너뛰어 핵심 내용이 빠졌어요."],
        actions=["슬라이드 3번을 한 문장이라도 설명하고 넘어가보세요.", "말 속도를 1분에 100자 정도로 천천히 말해보세요."],
        pace_summary="평균 116자/분으로 매우 빨랐고, 슬라이드 3번에서 속도가 크게 흔들렸어요.",
        habit_summary="REP(같은 말 반복)와 FIL(긴 휴지)은 거의 없었어요. 다만 말 속도가 너무 빨라서 청중이 따라가기 힘들었어요.",
    ), slow_pace(), HABITS)
    prose = " ".join([doc.one_liner, *doc.weaknesses, *doc.actions, doc.pace_summary, doc.habit_summary])
    for wrong in ("빠르고", "빨라서", "빨랐고", "천천히", "100자"):
        assert wrong not in prose, wrong
    assert doc.one_liner == "3번 슬라이드를 한 문장이라도 설명하고 넘어가면 더 좋을 거예요."   # 남은 문장 · 머리 접속사 뗌
    assert doc.weaknesses == ["슬라이드 3번을 통째로 건너뛰어 핵심 내용이 빠졌어요.",
                              "평균 말 속도는 116자/분으로 권장 구간(300~350자/분)보다 184자/분 느렸어요."]
    assert doc.actions[-1] == "말 속도를 권장 구간(300~350자/분)에 가깝게 조금 빠르게 연습해 보세요."
    assert doc.pace_summary == "평균 말 속도는 116자/분으로 권장 구간(300~350자/분)보다 184자/분 느렸어요."
    assert doc.habit_summary == "간투어는 3번, 같은 말 반복은 0번, 5초 넘게 멈춘 곳은 0곳이었어요."


def test_consistent_sentences_and_per_slide_claims_are_left_alone():
    """느린 발표에 「느렸어요」·「빠르게 연습」 은 맞는 말이다. 「7번은 평균보다 빠르게」 는 장 하나의 상대 속도라 따지지 않는다."""
    kept = _doc(
        one_liner="말 속도가 권장 구간보다 184자/분 느려서 전달력이 떨어졌어요.",
        strengths=["말 속도는 평균 116자/분으로 권장 구간보다 느리지만, 전체적으로 안정적인 말 속도를 유지했어요."],
        weaknesses=["7번(핵심)에서 말이 빨라요(164자/분). 핵심 문장은 천천히 또박또박."],
        actions=["말 속도를 조금 빠르게 해서 평균 116자/분을 권장 구간(300~350자/분)에 가깝게 맞춰 보세요."],
        pace_summary="평균 말 속도가 권장 구간보다 184자/분 느려서 전체적으로 천천히 말했어요. 슬라이드 7번은 평균보다 빠르게 말했어요.",
        habit_summary="반복이나 간투어는 적었어요.",
    )
    before = json.loads(json.dumps(kept.to_dict(), ensure_ascii=False))
    assert _checked(kept, slow_pace(), HABITS).to_dict() == before


def test_unmeasured_speed_numbers_and_ok_claims_are_checked_too():
    doc = _checked(_doc(strengths=["말 속도가 적절해서 듣기 편했어요."], weaknesses=["평균 250자/분으로 조금 느렸어요."],
                        pace_summary=""), slow_pace(), HABITS)
    assert doc.strengths == []                                   # 116자/분을 「적절」 — 권장 구간 밖이다
    assert doc.weaknesses == ["평균 말 속도는 116자/분으로 권장 구간(300~350자/분)보다 184자/분 느렸어요."]   # 250 은 잰 적 없는 수


def test_llm_object_in_a_sentence_field_is_not_printed_as_python():
    """감사 co2 R2 — pace_summary 자리에 {'average_sps': 2.26, 'average_cpm': 144.9, 'status': '…빠르고…'} 가 실렸다."""
    llm = Scripted({"one_liner": "시간이 짧았어요", "strengths": [{"text": "말버릇이 적었어요", "score": 3}],
                    "pace_summary": {"average_sps": 2.26, "average_cpm": 116.3, "status": "전체적으로 말 속도가 빠르고, 핵심 장이 짧았어요."},
                    "habit_summary": {"repetitions": 0, "status": "눈에 띄는 반복은 적었어요."}})
    rep = compose_report(slow_pace(), HABITS, rubric=RubricScore(score=50), llm=llm)
    assert rep.strengths == ["말버릇이 적었어요"]
    assert rep.pace_summary == "평균 말 속도는 116자/분으로 권장 구간(300~350자/분)보다 184자/분 느렸어요."
    assert rep.habit_summary == "눈에 띄는 반복은 적었어요."
    assert "{" not in rep.pace_summary + rep.habit_summary and "average" not in rep.pace_summary


def test_internal_names_become_user_words_with_the_right_particle():
    assert _humanize("REP(반복)는 0, FIL(간투어)는 1, PAUSE(휴지)는 0으로") == "같은 말 반복은 0, 간투어는 1, 긴 멈춤은 0으로"
    assert _humanize("REP와 FIL이 0으로 적었어요") == "같은 말 반복과 간투어가 0으로 적었어요"
    assert _humanize("1번(core)과 2번(support)") == "1번(핵심)과 2번(보조)"
    doc = _checked(_doc(pace_summary="평균 자분 144.9, 평균 SPS 2.26으로 말 속도가 일정하고 빠르지 않아요.",
                        weaknesses=["status=short 인 장이 많아요.", "핵심 장이 짧았어요."]), slow_pace(), HABITS)
    assert "자분" not in doc.pace_summary and "SPS" not in doc.pace_summary
    assert doc.weaknesses == ["핵심 장이 짧았어요."]


def test_prompt_states_the_measured_direction_in_user_words():
    block = _facts_block(slow_pace(), HABITS, CTX, None)
    assert "평균 말 속도 116.3자/분 — 권장 300~350자/분이라 권장보다 느려요" in block
    assert "- 7번(보조)" in block and "내 평균보다 빠름" in block
    empty = _facts_block(PaceDoc(), HabitDoc(), None, None)
    assert "재지 않았어요" in empty and "0.0자/분" not in empty
