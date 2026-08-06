"""
F-17·18·19 음성 종합 진단을 더미(또는 실데이터)로 돌리는 스모크 스크립트입니다.

더미:
  python examples/run_voice_report.py

실 STT+파싱(키 필요):
  MOCK_EXTERNAL_APIS=false python examples/run_voice_report.py --live-pptx fixtures/focus_notification_demo_designed.pptx --audio /path/to.wav
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chuckchuck.config import load_dotenv

load_dotenv()

from chuckchuck import (  # noqa: E402
    Context,
    analyze_pace,
    compose_report,
    extract_concepts,
    extract_habits,
    parse_document,
    transcribe,
)
from chuckchuck.contracts import ConceptDoc, SlideMark, Transcript  # noqa: E402


def _marks_from_transcript(t: Transcript) -> list[SlideMark]:
    return [
        SlideMark(slide_no=s.slide_no, start_sec=s.start_sec, end_sec=s.end_sec, visit=s.visit)
        for s in t.by_slide
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", default=str(ROOT / "fixtures/focus_transcript.json"))
    ap.add_argument("--concepts", default=str(ROOT / "fixtures/focus_concepts.json"))
    ap.add_argument("--slidedoc", default=str(ROOT / "fixtures/raw/focus_notification_demo_designed.slidedoc.json"))
    ap.add_argument("--duration-min", type=int, default=10)
    ap.add_argument("--live-pptx", default="")
    ap.add_argument("--audio", default="")
    ap.add_argument("--out", default=str(ROOT / "fixtures/focus_voice_report.json"))
    ap.add_argument("--habits", default=os.environ.get("HABIT_PROVIDER", "lora"), choices=("lora", "heuristic"))
    args = ap.parse_args()

    ctx = Context(situation="학회·수업 발표", audience="일반 청중", duration_min=args.duration_min)

    if args.live_pptx:
        print("[live] parse", args.live_pptx)
        slide_doc = parse_document(args.live_pptx)
        concepts = extract_concepts(slide_doc, ctx, llm=os.environ.get("REASONING_BACKEND", "mock"))
    else:
        concepts = ConceptDoc.from_dict(json.loads(Path(args.concepts).read_text(encoding="utf-8")))
        print(f"[dummy] concepts {len(concepts.slides)} slides")

    if args.audio:
        print("[live] transcribe", args.audio)
        # even spacing marks if we have concepts
        n = concepts.total_slides
        # placeholder equal marks — real UI sends marks from recorder
        marks = [SlideMark(slide_no=i, start_sec=(i - 1) * 30.0, end_sec=i * 30.0) for i in range(1, n + 1)]
        transcript = transcribe(args.audio, marks)
    else:
        transcript = Transcript.from_dict(json.loads(Path(args.transcript).read_text(encoding="utf-8")))
        print(f"[dummy] transcript {transcript.duration_sec:.1f}s words={len(transcript.words)}")

    pace = analyze_pace(transcript, ctx, concepts)
    print(f"[habits] provider={args.habits}")
    habits = extract_habits(transcript, provider=args.habits)
    report = compose_report(pace, habits, ctx, llm="mock")

    payload = {
        "context": ctx.to_dict(),
        "pace": pace.to_dict(),
        "habits": habits.to_dict(),
        "report": report.to_dict(),
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("--- Pace ---")
    print(f"target={pace.target_sec}s actual={pace.actual_sec}s avg_cpm={pace.avg_chars_per_min}")
    for s in pace.slides:
        if s.status != "ok":
            print(f"  {s.slide_no} [{s.importance}] {s.status}: {s.actual_sec:.0f}/{s.recommended_sec:.0f}s {s.note}")
    print("--- Habits ---")
    print(f"REP={habits.repeat_cnt} FIL={habits.filler_cnt} PAUSE={habits.pause_cnt} ({habits.provider})")
    print("--- Report ---")
    # 점수는 채점표(F-14)가 매긴다. 여기서는 rubric 을 안 넘기므로 0 이 정상이다.
    print(report.one_liner)
    for a in report.actions:
        print(f"  · {a}")
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
