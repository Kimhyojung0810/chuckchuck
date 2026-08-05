"""
triage 캐시가 그래프 교체를 견디는지 검사합니다.

triage 는 트랙과 무관해서 세션에 캐시한다 (1/5/10분 전환 시 LLM 재호출 없음).
그런데 캐시 키가 세션뿐이면, 자료를 다시 올려 그래프가 바뀌었을 때 옛 덱의
node_id 만 든 triage 를 그대로 집어 든다. 그러면 build_questions 가
"QaTriage 에 이 그래프의 개념이 없습니다" 로 죽고, 무효화 경로가 없어
그 세션에서는 재시도해도 영영 같은 실패다 (서버 재시작만이 탈출구).

두 가지를 못 박는다:
1. 같은 그래프면 캐시가 실제로 히트한다 (트랙 전환에 LLM 재호출 없음)
2. 그래프가 바뀌면 캐시를 버리고 다시 triage 한다

LLM 은 mock 이라 네트워크·API 키가 필요하지 않습니다.
"""

import json
from pathlib import Path

import pytest

from chuckchuck.contracts import ConceptGraph
from server import jobs
from server.store import CONCEPT_DOC, CONCEPT_GRAPH, QA_TRIAGE, store

ROOT = Path(__file__).resolve().parent.parent
LIVE_QA_RUN = ROOT / "fixtures" / "live_qa_run.json"


@pytest.fixture(scope="module")
def graph_payload() -> dict:
    if not LIVE_QA_RUN.is_file():
        pytest.skip(f"fixture 없음: {LIVE_QA_RUN}")
    return json.loads(LIVE_QA_RUN.read_text())["session"]["artifacts"]["concept_graph"]


def _relabelled(payload: dict, prefix: str) -> dict:
    """node_id 를 전부 바꾼 '다른 덱'. 자료를 다시 올린 상황을 흉내낸다."""
    graph = json.loads(json.dumps(payload))
    remap = {n["id"]: f"{prefix}{n['id']}" for n in graph.get("nodes", [])}
    for node in graph.get("nodes", []):
        node["id"] = remap[node["id"]]
    for edge in graph.get("edges", []):
        for key in ("from", "to"):
            if edge.get(key) in remap:
                edge[key] = remap[edge[key]]
    return graph


@pytest.fixture
def session_id(graph_payload) -> str:
    s = store.create_session(title="triage 캐시 검사")
    store.put_artifact(s.id, CONCEPT_GRAPH, graph_payload)
    return s.id


@pytest.fixture
def triage_calls(monkeypatch) -> list:
    """triage_questions 호출을 세되 원래 동작은 그대로 둔다."""
    calls: list = []
    original = jobs.triage_questions

    def spy(*args, **kwargs):
        calls.append(kwargs.get("llm"))
        return original(*args, **kwargs)

    monkeypatch.setattr(jobs, "triage_questions", spy)
    return calls


def test_same_graph_reuses_triage_across_tracks(session_id, triage_calls):
    """트랙만 바꾸면 triage 를 재사용한다 — 캐시가 존재하는 이유다."""
    jobs._handle_questions("job1", session_id, {"track": "10", "llm": "mock"})
    jobs._handle_questions("job2", session_id, {"track": "1", "llm": "mock"})

    assert len(triage_calls) == 1, "트랙 전환에 triage 가 다시 돌면 캐시가 무의미하다"


def test_replaced_graph_invalidates_triage_cache(session_id, graph_payload, triage_calls):
    """자료를 다시 올려 그래프가 바뀌면 다시 triage 한다.

    무효화가 없으면 옛 덱 node_id 만 든 triage 를 집어 QuestionError 로 죽고,
    그 세션에서는 몇 번을 재시도해도 같은 실패다.
    """
    first = jobs._handle_questions("job1", session_id, {"track": "10", "llm": "mock"})
    assert first["questions"], "1차 질문 생성이 비면 이 검사가 의미 없다"

    new_graph = _relabelled(graph_payload, "v2-")
    store.put_artifact(session_id, CONCEPT_GRAPH, new_graph)

    second = jobs._handle_questions("job2", session_id, {"track": "10", "llm": "mock"})

    assert len(triage_calls) == 2, "그래프가 바뀌었는데 옛 triage 를 재사용했다"
    assert second["questions"], "교체된 덱으로 질문이 나와야 한다"
    new_ids = {n["id"] for n in new_graph["nodes"]}
    assert any(q["node_id"] in new_ids for q in second["questions"]), \
        "질문이 옛 덱 개념을 가리키고 있다"


def test_graph_job_drops_stale_qa_artifacts(session_id, graph_payload, triage_calls, monkeypatch):
    """그래프 잡이 새 그래프를 쓰면 그 아래 QA 산출물은 무효다."""
    jobs._handle_questions("job1", session_id, {"track": "10", "llm": "mock"})
    assert store.get_session(session_id).artifacts.get(QA_TRIAGE), "전제: 캐시가 있어야 한다"

    store.put_artifact(
        session_id, CONCEPT_DOC,
        {"file_name": "deck.pdf", "total_slides": 1, "model": "mock", "slides": []},
    )
    monkeypatch.setattr(
        jobs, "build_graph",
        lambda *a, **k: ConceptGraph.from_dict(_relabelled(graph_payload, "v3-")),
    )
    jobs._handle_graph("job2", session_id, {"llm": "mock"})

    assert not store.get_session(session_id).artifacts.get(QA_TRIAGE), \
        "그래프를 새로 만들었는데 옛 triage 가 남아 있다"
