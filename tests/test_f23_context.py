"""F-23 상황 추정 — 자료만 보고 "업무 보고 같아요" 를 낼 수 있는가. 결정론, LLM 없음."""
from __future__ import annotations

import json

import pytest

import demo.bridge as bridge
from chuckchuck.contracts import ContextSuggestion, SlideDoc
from chuckchuck.f23_context import suggest_context


def _doc(*slides):
    return SlideDoc.from_dict({"file_name": "a.pdf", "total_slides": len(slides), "slides": [
        {"slide_no": i + 1, "title": t, "blocks": [{"category": "paragraph", "text": b}]} for i, (t, b) in enumerate(slides)]})


def test_work_report_deck_is_recognized_with_slide_evidence():
    doc = _doc(("3분기 실적 보고", "매출 현황과 목표 대비 진행률"),
               ("이슈와 리스크", "지연 원인과 대응 계획"),
               ("요청 사항", "인력 2명 추가 — 의사결정 필요"))
    s = suggest_context(doc)
    assert s.situation == "work_report" and s.audience == "상사"
    assert s.confidence >= 0.8
    assert "1장 '실적'" in s.why or "1장 '보고'" in s.why       # 제목 신호가 먼저 나온다
    assert "3장 '요청 사항'" in s.why or "2장" in s.why


def test_school_project_deck():
    doc = _doc(("서론", "선행 연구와 가설"), ("실험 방법", "데이터셋과 방법론"), ("참고문헌", "논문 목록"))
    assert suggest_context(doc).situation == "school_project"


def test_ambiguous_or_thin_deck_returns_undecided():
    s = suggest_context(_doc(("발표", "안녕하세요 오늘은 집중에 대해 이야기합니다")))
    assert s.situation == "" and s.audience == ""
    assert "어려워요" in s.why
    mixed = suggest_context(_doc(("연구 현황", "실험 계획과 가격 정책"), ("데모 공유", "고객 회고")))
    assert mixed.situation == "" or mixed.confidence < 0.7      # 신호가 흩어지면 확신하지 않는다


def test_suggestion_roundtrip_and_dict_input():
    s = suggest_context({"file_name": "a.pdf", "total_slides": 1,
                         "slides": [{"slide_no": 1, "title": "신제품 출시 안내", "blocks": [{"category": "p", "text": "가격과 사전 예약"}]}]})
    assert s.situation == "product_launch"
    assert ContextSuggestion.from_dict(s.to_dict()).to_dict() == s.to_dict()


class FakeHandler(bridge.Handler):
    def __init__(self):  # noqa: D107 — super 호출 안 함
        self.sent = []

    def _json(self, code, payload):
        self.sent.append((code, payload))


def test_bridge_route_returns_suggestion_without_llm():
    h = FakeHandler()
    doc = _doc(("분기 실적 보고", "현황"), ("요청 사항", "예산 결정 필요"))
    h._handle_suggest_context(json.dumps({"slide_doc": doc.to_dict()}).encode())
    code, payload = h.sent[-1]
    assert code == 200 and payload["situation"] == "work_report" and payload["why"]
    h._handle_suggest_context(b"{}")
    assert h.sent[-1][0] == 400


def test_deck_gaps_marks_missing_expectations_for_work_report():
    from chuckchuck.f23_context import deck_gaps
    doc = _doc(("3분기 실적 보고", "목표 대비 진행률 80%"),
               ("이슈", "지연 원인은 인력 부족"),
               ("요청 사항", "예산 승인 필요"))
    g = deck_gaps(doc, "work_report")
    by = {i["key"]: i for i in g["items"]}
    assert by["status"]["status"] == "present" and 1 in by["status"]["slide_nos"]
    assert by["ask"]["status"] == "present"
    assert by["risk"]["status"] == "missing" and by["risk"]["slide_nos"] == []
    assert by["next"]["status"] in ("weak", "missing")          # '계획·일정·기한' 낱말이 없다
    assert g["summary"]["missing"] >= 1 and g["situation_label"].startswith("업무 보고")


def test_deck_gaps_unknown_situation_is_empty():
    from chuckchuck.f23_context import deck_gaps
    assert deck_gaps(_doc(("a", "b")), "")["items"] == []


def test_bridge_deck_gaps_falls_back_to_suggested_situation():
    h = FakeHandler()
    doc = _doc(("분기 실적 보고", "현황과 진행률"), ("요청 사항", "예산 결정 필요"))
    h._handle_deck_gaps(json.dumps({"slide_doc": doc.to_dict()}).encode())
    code, out = h.sent[-1]
    assert code == 200 and out["situation"] == "work_report" and any(i["status"] == "missing" for i in out["items"])
    h._handle_deck_gaps(json.dumps({"slide_doc": _doc(("발표", "안녕하세요")).to_dict()}).encode())
    assert h.sent[-1][1]["items"] == [] and "골라" in h.sent[-1][1]["message"]
