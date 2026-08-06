"""F-17·18·19 더미 파이프라인 테스트입니다."""

from __future__ import annotations

import json
from pathlib import Path

from chuckchuck import Context, analyze_pace, compose_report, extract_habits
from chuckchuck.contracts import ConceptDoc, RubricScore, Transcript
from chuckchuck.providers.llm_base import LLMProvider

ROOT = Path(__file__).resolve().parent.parent


class ScriptedLLM(LLMProvider):
    """정해 둔 문자열만 돌려주는 가짜 LLM. 후처리 로직만 시험한다 (test_judge 와 같은 패턴)."""

    name = "scripted"

    def __init__(self, payload: str):
        self.payload = payload

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False) -> str:
        return self.payload


def _pace_and_habits():
    transcript = Transcript.from_dict(
        json.loads((ROOT / "fixtures/focus_transcript.json").read_text(encoding="utf-8"))
    )
    concepts = ConceptDoc.from_dict(
        json.loads((ROOT / "fixtures/focus_concepts.json").read_text(encoding="utf-8"))
    )
    ctx = Context(situation="학회·수업 발표", audience="일반 청중", duration_min=10)
    return analyze_pace(transcript, ctx, concepts), extract_habits(transcript, provider="heuristic")


def test_focus_dummy_voice_pipeline():
    transcript = Transcript.from_dict(
        json.loads((ROOT / "fixtures/focus_transcript.json").read_text(encoding="utf-8"))
    )
    concepts = ConceptDoc.from_dict(
        json.loads((ROOT / "fixtures/focus_concepts.json").read_text(encoding="utf-8"))
    )
    ctx = Context(situation="학회·수업 발표", audience="일반 청중", duration_min=10)

    pace = analyze_pace(transcript, ctx, concepts)
    habits = extract_habits(transcript, provider="heuristic")
    report = compose_report(pace, habits, ctx, llm="mock")

    assert pace.target_sec == 600
    assert len(pace.slides) >= 10
    assert any(s.importance == "core" for s in pace.slides)
    # core 3/5 are short by construction
    assert any(s.status == "short" and s.importance == "core" for s in pace.slides)
    assert habits.filler_cnt >= 1
    assert habits.pause_cnt >= 1
    # 점수는 이제 F-14 채점표가 만든다. rubric 없이 부르면 짐작하지 않고 0 이다.
    assert report.score == 0
    assert report.grade == ""
    assert report.one_liner
    assert len(report.actions) >= 1


def test_sample_transcript_pace_without_concepts():
    transcript = Transcript.from_dict(
        json.loads((ROOT / "fixtures/sample_transcript.json").read_text(encoding="utf-8"))
    )
    pace = analyze_pace(transcript, Context(duration_min=1), None)
    assert pace.actual_sec > 0
    assert pace.slides


# ---------------------------------------------------------------------------
# S-1 · 점수는 채점표가 진실이다 — LLM 이 덮어쓸 수 없다
# ---------------------------------------------------------------------------

def test_llm_score_and_grade_cannot_override_rubric():
    """LLM 이 score=99 · grade='S급' 을 줘도 채점표 점수가 이긴다."""
    pace, habits = _pace_and_habits()
    llm = ScriptedLLM(json.dumps({
        "one_liner": "정말 잘했어요!",
        "score": 99,
        "grade": "S급",
        "strengths": ["좋아요"],
        "weaknesses": [],
        "actions": ["연습해보세요"],
        "pace_summary": "빠르지 않았어요",
        "habit_summary": "간투어가 적었어요",
    }, ensure_ascii=False))

    report = compose_report(pace, habits, rubric=RubricScore(score=64), llm=llm)

    assert report.score == 64          # 채점표 점수. LLM 의 99 는 버린다
    assert report.grade == ""          # 등급은 더 이상 매기지 않는다 (읽는 화면이 없다)
    assert report.one_liner == "정말 잘했어요!"   # 서술은 LLM 몫 그대로


def test_non_numeric_llm_score_does_not_crash():
    """LLM 이 score='85점' 처럼 줘도 리포트가 터지지 않는다 (기존: int() ValueError)."""
    pace, habits = _pace_and_habits()
    llm = ScriptedLLM(json.dumps({
        "one_liner": "수고했어요",
        "score": "85점",
        "grade": "B+",
    }, ensure_ascii=False))

    report = compose_report(pace, habits, rubric=RubricScore(score=58), llm=llm)

    assert report.score == 58
    assert report.grade == ""
