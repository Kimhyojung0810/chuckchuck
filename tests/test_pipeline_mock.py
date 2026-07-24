"""
mock으로 SlideDoc·개념추출·STT 파이프라인이 깨지지 않는지 검사하는 테스트입니다.
"""

import json
from pathlib import Path

from chuckchuck import Context, extract_concepts, transcribe
from chuckchuck.contracts import SlideDoc, SlideMark


ROOT = Path(__file__).resolve().parents[1]


def test_slidedoc_roundtrip():
    raw = json.loads((ROOT / "fixtures" / "sample_slidedoc.json").read_text(encoding="utf-8"))
    doc = SlideDoc.from_dict(raw)
    assert doc.total_slides == 5
    assert doc.slides[4].text_sparse is True
    again = SlideDoc.from_dict(doc.to_dict())
    assert again.slides[0].title == "IMU2CLIP 논문 리뷰"


def test_extract_concepts_mock():
    raw = json.loads((ROOT / "fixtures" / "sample_slidedoc.json").read_text(encoding="utf-8"))
    doc = SlideDoc.from_dict(raw)
    out = extract_concepts(
        doc,
        Context(situation="학회·수업 발표", audience="교수님", duration_min=10),
        llm="mock",
    )
    assert out.model == "mock"
    assert len(out.slides) == 5
    assert out.slides[0].topic


def test_transcribe_mock():
    marks = [
        {"slide_no": 1, "start_sec": 0.0, "end_sec": 8.0, "visit": 1},
        {"slide_no": 2, "start_sec": 8.0, "end_sec": 20.0, "visit": 1},
    ]
    t = transcribe(ROOT / "fixtures" / ".keep", marks, provider="mock")
    assert t.provider == "mock"
    assert t.words
    assert t.by_slide
    assert isinstance(SlideMark.from_dict(marks[0]).duration, float)
