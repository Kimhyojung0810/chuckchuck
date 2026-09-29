"""
다른 발표 녹음이면 녹음으로 재는 값은 전부 「안 쟀다」 (09-30 녹음 대화 감사 REC-10 — qa/report2).

녹음이 이 자료의 발표가 아니면(F-11 speech_match "unrelated" / basis "skipped") 말 속도·시간·말버릇·신호어·시간 배분은 이 발표의 값이
아니다 — 0점이 아니라 「못 쟀다」. F-17 은 빈 PaceDoc, F-14 는 녹음으로 재는 항목 전부 unmeasured, F-19 는 LLM 없이 정해진 말만,
브리지 /pace·/report 는 정합을 넘긴다. 이 자료의 발표인 녹음은(정합이 짐작뿐이어도) 전부 그대로 잰다.
재료는 튜닝 덱이 아니다 — 학생회 축제 부스 결산 녹음(감사의 R3)과 임의의 세 장 자료.
"""

from __future__ import annotations

import io
import json
from email.message import Message

import pytest

import demo.bridge as bridge
from chuckchuck.contracts import (
    AlignmentDoc,
    ConceptDoc,
    Context,
    HabitDoc,
    RubricFault,
    RubricScore,
    SlideConcepts,
    SlideSpeech,
    Transcript,
    Word,
)
from chuckchuck.f14_rubric import score_rubric
from chuckchuck.f17_pace import analyze_pace
from chuckchuck.f19_report import compose_report
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


FESTIVAL = talk(
    (1, "안녕하세요 학생회 축제 준비팀이에요 음 오늘은 작년 축제 부스 결산을 말씀드릴게요"),
    (2, "먼저 전체 숫자부터 볼게요 부스가 모두 스물네 개였고 평균 매출은 삼십팔만 원이었어요"),
    (3, "정리하면 준비 시간이 길수록 매출이 높았어요 그러니까 내년에는 준비를 일찍 시작해요 감사합니다"),
)
CONCEPTS = ConceptDoc("deck.pptx", 3, [SlideConcepts(slide_no=n, title=f"{n}장", topic="", importance="core")
                                        for n in (1, 2, 3)])
CTX = Context(situation="school_project", duration_min=5)
UNRELATED = AlignmentDoc(file_name="deck.pptx", total_slides=3, model="code",
                         speech_match="unrelated", speech_overlap=0.04, basis="skipped")
GUESSED = AlignmentDoc(file_name="deck.pptx", total_slides=3, model="scripted", basis="fallback")
MATCHED = AlignmentDoc(file_name="deck.pptx", total_slides=3, model="scripted")
RECORDING_ITEMS = (17, 19, 20, 21, 22, 23, 24, 31)


class Scripted(LLMProvider):
    """정해 둔 리포트 JSON 을 돌려주고 부른 횟수를 센다."""

    name = "scripted"

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def complete(self, **_) -> str:
        self.calls += 1
        return json.dumps(self.payload, ensure_ascii=False)


HABITS = HabitDoc(repeat_cnt=0, filler_cnt=3, pause_cnt=0, provider="heuristic")


# ---------------------------------------------------------------------------
# F-17 — 다른 발표 녹음이면 재지 않는다, 이 발표의 녹음이면 그대로 잰다
# ---------------------------------------------------------------------------

def test_pace_is_not_measured_for_an_unrelated_recording():
    pace = analyze_pace(FESTIVAL, CTX, CONCEPTS, UNRELATED)
    assert (pace.slides, pace.sections, pace.tips) == ([], [], [])
    assert (pace.target_sec, pace.actual_sec, pace.avg_chars_per_min) == (0.0, 0.0, 0.0)
    # dict 로 와도(브리지 본문) 같다
    assert analyze_pace(FESTIVAL.to_dict(), CTX.to_dict(), CONCEPTS.to_dict(), UNRELATED.to_dict()).slides == []


@pytest.mark.parametrize("alignment", [None, MATCHED, GUESSED], ids=["no-alignment", "matched", "guessed"])
def test_pace_of_this_talks_recording_is_measured_as_before(alignment):
    """정합이 없거나(옛 호출), 맞거나, 전부 짐작이어도 녹음은 이 발표의 것이다 — 속도·시간은 정합과 상관없이 잰다."""
    got = analyze_pace(FESTIVAL, CTX, CONCEPTS, alignment)
    assert got.to_dict() == analyze_pace(FESTIVAL, CTX, CONCEPTS).to_dict()
    assert got.slides and got.avg_chars_per_min > 0 and got.tips


# ---------------------------------------------------------------------------
# F-14 — 녹음으로 재는 항목 전부 「못 쟀다」 (0점이 아니다)
# ---------------------------------------------------------------------------

def test_rubric_does_not_score_recording_items_even_if_a_measured_pace_is_passed():
    """옛 호출이 잰 PaceDoc 을 그대로 보내도 채점표는 정합을 보고 안 잰다 — 「시간 관리 0/100」 이 기둥에 섰던 자리 (REC-10)."""
    stale = analyze_pace(FESTIVAL, CTX, CONCEPTS)            # 정합 없이 잰 값
    got = score_rubric(situation="school_project", transcript=FESTIVAL, alignment=UNRELATED, pace=stale,
                       habits=HABITS, llm="mock")
    for no in RECORDING_ITEMS:
        it = got.item(no)
        assert it.status == "unmeasured" and it.score == 0 and "발표가 아니라서" in it.note, no
    assert got.cluster("time").status == "omitted" and got.cluster("delivery").status == "omitted"
    assert "말하기 습관만 봤" not in got.note and "녹음으로 재는 항목" in got.note


def test_rubric_still_scores_pace_and_habits_when_only_the_alignment_is_guessed():
    pace = analyze_pace(FESTIVAL, CTX, CONCEPTS, GUESSED)
    got = score_rubric(situation="school_project", transcript=FESTIVAL, alignment=GUESSED, pace=pace,
                       habits=HABITS, llm="mock")
    assert got.item(22).status == "scored" and got.item(31).status == "scored" and got.item(23).status == "scored"
    assert got.item(1).status == "unmeasured"                 # 정합 결과를 쓰는 항목만 뺀다 (G-A22)


# ---------------------------------------------------------------------------
# F-19 — 다른 발표 녹음이면 LLM 없이 정해진 말
# ---------------------------------------------------------------------------

UNRELATED_RUBRIC = RubricScore(score=29, cap=39, faults=[RubricFault(
    "unrelated_speech", "녹음이 이 발표 자료와 다른 발표예요 (발화 낱말 중 자료에도 있는 비중 4%) — 녹음으로 재는 항목은 채점하지 않았어요")])
SPEEDY_LLM = {"one_liner": "말 속도가 일정해서 듣기 편했어요", "strengths": ["말 속도가 일정해서 청중이 따라가기 편해요"],
              "weaknesses": ["평균 93자/분으로 너무 느렸어요"], "actions": ["2. 말 속도를 300~350자/분 정도로 빠르게 연습해 보세요."],
              "pace_summary": "평균 93자/분으로 권장 구간보다 207자/분 느려서 말 속도가 너무 느렸어요.",
              "habit_summary": "REP와 FIL이 0으로 눈에 띄는 반복이나 간투어가 적었어요."}


@pytest.mark.parametrize("rubric,alignment", [(UNRELATED_RUBRIC, None), (RubricScore(score=12), UNRELATED),
                                              (None, UNRELATED.to_dict())], ids=["rubric-fault", "alignment-only", "dict"])
def test_unrelated_report_is_code_only_and_carries_no_recording_measurement(rubric, alignment):
    llm = Scripted(SPEEDY_LLM)
    pace = analyze_pace(FESTIVAL, CTX, CONCEPTS)               # 옛 호출처럼 잰 값이 와도
    rep = compose_report(pace, HABITS, CTX, rubric=rubric, alignment=alignment, llm=llm)
    assert llm.calls == 0 and rep.model == "code"
    prose = " ".join([rep.one_liner, *rep.strengths, *rep.weaknesses, *rep.actions, rep.pace_summary, rep.habit_summary])
    for said in ("자/분", "속도가 일정", "빠르게 연습", "간투어가 적", "REP", "FIL", "0으로"):
        assert said not in prose, said
    assert rep.strengths == [] and "다른 발표" in rep.weaknesses[0] and "녹음을 다시 올려" in rep.actions[0]
    assert "재지 않았어요" in rep.pace_summary and "보지 않았어요" in rep.habit_summary
    assert rep.score == (rubric.score if isinstance(rubric, RubricScore) else 0)


# ---------------------------------------------------------------------------
# 브리지 — /pace·/report 가 정합을 넘긴다
# ---------------------------------------------------------------------------

class H(bridge.Handler):
    def __init__(self):  # noqa: D107 — 소켓 없이 핸들러 함수만 부른다
        self.headers, self.sent, self.wfile = Message(), [], io.BytesIO()

    def _json(self, code, payload):
        self.sent.append((code, payload))


@pytest.fixture()
def no_archive(monkeypatch):
    monkeypatch.setattr(bridge.Handler, "_archive", staticmethod(lambda *a: None))


def test_pace_route_passes_the_alignment(no_archive):
    body = {"transcript": FESTIVAL.to_dict(), "context": CTX.to_dict(), "concept_doc": CONCEPTS.to_dict()}
    h = H()
    h._handle_pace(json.dumps({**body, "alignment": UNRELATED.to_dict()}).encode())
    assert h.sent[-1][0] == 200 and h.sent[-1][1]["slides"] == [] and h.sent[-1][1]["avg_chars_per_min"] == 0.0
    h._handle_pace(json.dumps({**body, "alignment": MATCHED.to_dict()}).encode())
    assert h.sent[-1][1]["slides"]
    h._handle_pace(json.dumps(body).encode())                  # 정합을 안 보내는 옛 화면
    assert h.sent[-1][1]["slides"]


def test_a_broken_alignment_body_does_not_break_pace_or_report(no_archive, monkeypatch):
    """정합은 곁다리 칸이다 — 모양이 깨져 와도 /pace·/report 는 예전처럼 잰다·쓴다 (정합 없이)."""
    monkeypatch.setattr(bridge, "_pick_llm", lambda body: "mock")
    broken = {"speech_match": "unrelated"}                  # file_name·total_slides 가 없다
    h = H()
    h._handle_pace(json.dumps({"transcript": FESTIVAL.to_dict(), "context": CTX.to_dict(),
                               "concept_doc": CONCEPTS.to_dict(), "alignment": broken}).encode())
    code, pace = h.sent[-1]
    assert code == 200 and pace["slides"]
    h._handle_report(json.dumps({"pace": pace, "habits": HABITS.to_dict(), "alignment": broken}).encode())
    assert h.sent[-1][0] == 200 and h.sent[-1][1]["model"] == "mock"


def test_report_route_passes_the_alignment(no_archive, monkeypatch):
    monkeypatch.setattr(bridge, "_pick_llm", lambda body: "mock")
    pace = analyze_pace(FESTIVAL, CTX, CONCEPTS)
    h = H()
    h._handle_report(json.dumps({"pace": pace.to_dict(), "habits": HABITS.to_dict(), "rubric": RubricScore(score=20).to_dict(),
                                 "alignment": UNRELATED.to_dict()}).encode())
    code, payload = h.sent[-1]
    assert code == 200 and payload["model"] == "code" and payload["strengths"] == []
