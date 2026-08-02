"""F-17·18·19 더미 파이프라인 테스트입니다."""

from __future__ import annotations

import json
from pathlib import Path

from chuckchuck import Context, analyze_pace, compose_report, extract_habits
from chuckchuck.contracts import ConceptDoc, Transcript

ROOT = Path(__file__).resolve().parent.parent


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
    assert 40 <= report.score <= 95
    assert report.one_liner
    assert len(report.actions) >= 1


def test_sample_transcript_pace_without_concepts():
    transcript = Transcript.from_dict(
        json.loads((ROOT / "fixtures/sample_transcript.json").read_text(encoding="utf-8"))
    )
    pace = analyze_pace(transcript, Context(duration_min=1), None)
    assert pace.actual_sec > 0
    assert pace.slides
