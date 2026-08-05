"""
플랫 라우트(/api/v1/*) 통합 테스트입니다.

데모 프론트(demo/YEHS_demo)는 세션 없이 이 플랫 경로만 씁니다.
세션 라우트에는 테스트가 있었지만 플랫 라우트에는 없어서, 프론트가 실제로
의존하는 계약이 무방비였습니다. 이 파일이 그 빈칸을 메웁니다.

LLM 은 payload 의 llm="mock" 으로 못박습니다 — 과금·네트워크 없이 계약만 검증합니다.

    python -m pytest tests/test_flat_routes.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import app

ROOT = Path(__file__).resolve().parents[1]
LIVE_QA_RUN = ROOT / "fixtures" / "live_qa_run.json"


@pytest.fixture(scope="module")
def artifacts() -> dict:
    """실제 발표 1회분에서 뽑아 둔 산출물. 합성 데이터로는 이 계약을 못 지킨다."""
    if not LIVE_QA_RUN.is_file():
        pytest.skip(f"fixture 없음: {LIVE_QA_RUN}")
    return json.loads(LIVE_QA_RUN.read_text())["session"]["artifacts"]


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _questions_payload(artifacts: dict, **over) -> dict:
    payload = {
        "graph": artifacts["concept_graph"],
        "alignment": artifacts["alignment_doc"],
        "context": {"situation": "학회", "audience": "교수님", "duration_min": 10},
        "track": "10",
        "llm": "mock",
    }
    payload.update(over)
    return payload


def test_questions_returns_questions_for_real_graph(client, artifacts):
    """프론트가 기대하는 것: questions 가 비지 않는다.

    비면 화면은 조용히 데모 질문으로 되돌아간다 (app.js qaLiveBlockReason).
    """
    res = client.post("/api/v1/questions", json=_questions_payload(artifacts))

    assert res.status_code == 200, res.text
    doc = res.json()
    assert doc.get("questions"), "questions 가 비었다 — 프론트가 데모 질문으로 되돌아간다"
    first = doc["questions"][0]
    for key in ("id", "node_id", "label", "question", "severity"):
        assert key in first, f"프론트가 소비하는 키 누락: {key}"


def test_questions_works_without_alignment(client, artifacts):
    """녹음 없이 자료만 올린 경로.

    triage_questions 의 계약이 명시한다 —
    "alignment·flow·transcript 없이 그래프만으로도 동작한다".
    세션 라우트도 개념 그래프만 요구한다. 플랫 라우트만 alignment 를 강제하면,
    녹음을 안 한 사용자는 이유도 모른 채 데모 질문을 받는다.
    """
    payload = _questions_payload(artifacts)
    payload.pop("alignment")

    res = client.post("/api/v1/questions", json=payload)

    assert res.status_code == 200, res.text
    assert res.json().get("questions"), "그래프만으로도 질문이 나와야 한다"


def test_questions_accepts_explicit_null_alignment(client, artifacts):
    """프론트가 실제로 보내는 모양은 키 누락이 아니라 alignment: null 이다.

    app.js 는 out.alignment(녹음이 없으면 null)를 그대로 실어 보내고
    JSON.stringify 는 명시적 null 을 지우지 않는다. 키가 없는 경우와
    다른 경로이므로 따로 고정한다.
    """
    payload = _questions_payload(artifacts, alignment=None)

    res = client.post("/api/v1/questions", json=payload)

    assert res.status_code == 200, res.text
    assert res.json().get("questions"), "alignment: null 도 '없음' 으로 다뤄야 한다"


def test_questions_rejects_missing_graph(client, artifacts):
    """그래프는 진짜 필수다 — 없으면 400 으로 분명히 거절한다."""
    payload = _questions_payload(artifacts)
    payload.pop("graph")

    res = client.post("/api/v1/questions", json=payload)

    # 에러 봉투는 평평하다 (server/app.py _http_error) — 프론트 브리지가
    # doc.error / doc.message 를 그대로 읽는다.
    assert res.status_code == 400
    assert res.json()["error"] == "bad_request"


def test_flow_requires_graph_and_alignment(client, artifacts):
    """F-11 파생 흐름 비교는 둘 다 있어야 계산된다 (LLM 없는 결정적 경로).

    /api/v1/questions 와 달리 alignment 이 진짜 필수다 — 흐름 비교는 자료 순서와
    발표 순서를 맞대는 diff 라서 한쪽만으로는 정의되지 않는다.
    두 라우트의 차이는 불일치가 아니라 의도다. 통일하지 말 것.
    """
    res = client.post(
        "/api/v1/flow",
        json={"graph": artifacts["concept_graph"], "alignment": artifacts["alignment_doc"]},
    )
    assert res.status_code == 200, res.text
    assert "issues" in res.json()

    assert client.post("/api/v1/flow", json={"graph": artifacts["concept_graph"]}).status_code == 400


def test_judge_falls_back_to_body_question_without_session(client, artifacts):
    """플랫 경로에는 서버 세션이 없다.

    프론트는 sessionId 자리에 'flat' 을 넣고 질문 본문을 함께 보낸다.
    세션이 없어도 404 가 아니라 판정이 돌아와야 한다.
    """
    question = artifacts["question_doc"]["questions"][0]

    res = client.post(
        "/api/v1/sessions/flat/qa/judge",
        json={
            "question_id": question["id"],
            "question": question,
            "answer": "알림은 확인 여부와 무관하게 작업 맥락을 끊어 복귀 비용을 만듭니다.",
            "history": [],
            "llm": "mock",
        },
    )

    assert res.status_code == 200, res.text
    assert res.json().get("verdict"), "판정 결과가 비었다"


def test_judge_response_carries_multiturn_fields(client, artifacts):
    """
    다턴 코칭에 필요한 재료가 HTTP 응답까지 실려 나오는지.

    프론트는 이 셋으로 화면을 만든다 — `passed` 로 넘어갈지 정하고,
    `followup` 으로 되묻고, `hints` 로 힌트 사다리를 그린다.
    하나라도 빠지면 되묻기 루프가 서지 않는다.
    """
    question = artifacts["question_doc"]["questions"][0]

    res = client.post(
        "/api/v1/sessions/flat/qa/judge",
        json={
            "question_id": question["id"],
            "question": question,
            "answer": "짧게",  # mock 은 짧은 답을 partial 로 본다 → 되묻는 경로
            "history": [],
            "llm": "mock",
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body) >= {"passed", "followup", "hints"}, body
    assert body["passed"] is False, "짧은 답이 통과하면 되묻기가 영영 안 걸린다"
    assert body["followup"].strip(), "되물을 질문이 없으면 사용자가 갇힌다"
    assert len(body["hints"]) >= 2
