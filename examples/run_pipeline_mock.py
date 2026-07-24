"""
외부 API 없이 mock으로 파이프라인만 검증하는 예제입니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chuckchuck import Context, extract_concepts, transcribe
from chuckchuck.contracts import SlideDoc
from chuckchuck.providers import compare_table


def main():
    print(compare_table())
    print()

    doc = SlideDoc.from_dict(
        json.loads((ROOT / "fixtures" / "sample_slidedoc.json").read_text(encoding="utf-8"))
    )
    ctx = Context(situation="학회·수업 발표", audience="교수님", duration_min=10)
    concepts = extract_concepts(doc, ctx, llm="mock")
    print("F-06 ConceptDoc")
    print(json.dumps(concepts.to_dict(), ensure_ascii=False, indent=2)[:800])
    print()

    marks = [
        {"slide_no": 1, "start_sec": 0.0, "end_sec": 8.0, "visit": 1},
        {"slide_no": 2, "start_sec": 8.0, "end_sec": 16.0, "visit": 1},
        {"slide_no": 3, "start_sec": 16.0, "end_sec": 30.0, "visit": 1},
    ]
    t = transcribe(ROOT / "fixtures" / ".keep", marks, provider="mock")
    print("F-05 Transcript")
    for s in t.by_slide:
        print(f"  slide {s.slide_no} visit {s.visit}: {s.text[:60]}...")


if __name__ == "__main__":
    main()
