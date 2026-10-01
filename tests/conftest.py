"""테스트 공통 — 다수결 추출·뼈대 판단은 한 번으로 (가짜 LLM 호출 수를 세는 테스트가 많다). 다수결 자체는 test_typed_graph 가 따로 본다."""
import pytest


@pytest.fixture(autouse=True)
def _single_vote(monkeypatch):
    monkeypatch.setenv("CHUCKCHUCK_CONCEPT_VOTES", "1")
    monkeypatch.setenv("CHUCKCHUCK_GRAPH_SKELETON_VOTES", "1")
