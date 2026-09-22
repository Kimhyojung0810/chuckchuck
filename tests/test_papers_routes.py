"""
F-24 경로 — FastAPI 동기 라우트(/api/v1/papers, /api/v1/papers/search)와 데모 브리지 핸들러.
mock 모드라 외부 검색은 부르지 않는다 (provider=none) — 자료 인용(deck)만 나온다.
"""

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from chuckchuck.contracts import ConceptGraph, ConceptNode  # noqa: E402
from server.app import app  # noqa: E402


def graph() -> dict:
    return ConceptGraph(file_name="deck.pdf", total_slides=3, nodes=[
        ConceptNode(id="c1", label="Attention residue", slide_nos=[2], weight=1.0),
    ]).to_dict()


def slide_doc() -> dict:
    return {"file_name": "deck.pdf", "total_slides": 3, "slides": [
        {"slide_no": 2, "title": "선행", "blocks": [{"category": "paragraph", "text": "Leroy (2009)가 처음 보고했다"}]},
    ]}


def test_papers_route_returns_deck_refs_in_mock(monkeypatch):
    monkeypatch.setattr("server.app.settings.mock_external", True)
    res = TestClient(app).post("/api/v1/papers", json={"graph": graph(), "slide_doc": slide_doc()})
    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "none" and body["refs"][0]["cite_key"] == "Leroy (2009)"
    assert body["refs"][0]["node_ids"] == ["c1"]


def test_papers_search_route_requires_query_and_is_off_in_mock(monkeypatch):
    monkeypatch.setattr("server.app.settings.mock_external", True)
    c = TestClient(app)
    assert c.post("/api/v1/papers/search", json={}).status_code == 400
    body = c.post("/api/v1/papers/search", json={"query": "dense retrieval"}).json()
    assert body["refs"] == [] and "검색 꺼짐" in body["note"]


def test_flat_questions_carries_paper_ids_and_papers_keys(monkeypatch):
    monkeypatch.setattr("server.app.settings.mock_external", True)
    res = TestClient(app).post("/api/v1/questions", json={"graph": graph(), "slide_doc": slide_doc(), "track": "1"})
    assert res.status_code == 200
    body = res.json()
    assert "papers" in body and all("paper_ids" in q for q in body["questions"])
