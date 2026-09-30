"""
함정 질문의 **화면 사본** — 두 서버(demo/bridge.py · server/app.py)가 같은 규칙(`chuckchuck._client_payload`)으로 내보내는지 (qa/tidy).

09-30 WP-J2 가 브리지에서 함정의 전제(trap_premise)·기대 답(answer_gist·answer_gist_parts)을 화면 사본에서 뺐는데, 같은 계약의
FastAPI 서버는 세 칸을 그대로 내보냈다 — 서버를 붙인 화면은 개발자 도구 한 번이면 정답이었다. 규칙을 한곳으로 옮기고 두 서버를 본다:
질문 묶음(플랫 라우트 · 세션 잡 결과 · 세션 조회)은 사본으로, 채점은 서버의 원본으로, 기대 답은 바로잡았거나·닫혔거나·해설 단계이거나
「답 보고 다시 말해보기」(reveal 요청, LLM 없음)일 때만.

LLM 은 부르지 않는다 — 질문 생성·판정은 가짜로 끼운다. **튜닝·held-out·벤치 덱의 낱말을 쓰지 않는다** — 동네 수영장 수질 덱.
"""

from __future__ import annotations

import copy
import json
from collections import OrderedDict

import pytest
from fastapi.testclient import TestClient

import chuckchuck
import demo.bridge as bridge
from chuckchuck import _client_payload as CP
from chuckchuck.contracts import QaJudgement, QaTriage, Question, QuestionDoc, TrapPremise
from server import app as server_app
from server import jobs
from server.store import QUESTION_DOC, store

TRAP_Q = Question(
    id="q03-chlorine", node_id="chlorine", label="잔류 염소", slide_nos=[3], evidence_slide_no=3,
    question="자료에서 「잔류 염소를 0.2ppm 으로 맞춥니다」라고 했는데, 이 기준을 어떻게 지키는지 설명해 주세요.",
    answer_gist="질문의 전제와 달리, 자료 3장은 「잔류 염소를 0.6ppm 으로 맞춥니다」라고 해요.",
    answer_gist_parts=["잔류 염소 0.6ppm", "하루 네 번 측정"], trap=True,
    trap_premise=TrapPremise(kind="number", premise="잔류 염소를 0.2ppm 으로 맞춥니다", fact="잔류 염소를 0.6ppm 으로 맞춥니다",
                             slide_no=3, wrong=["0.2ppm"], right=["0.6ppm"]),
)
PLAIN_Q = Question(id="q01-filter", node_id="filter", label="여과기", slide_nos=[2],
                   question="여과기를 언제 돌리는지 설명해 주세요.", answer_gist="여과기는 영업 시간 내내 돌려요.")
GRAPH = {"file_name": "pool.pdf", "total_slides": 3, "nodes": [
    {"id": "filter", "label": "여과기", "weight": 0.8, "slide_nos": [2], "depth": 1},
    {"id": "chlorine", "label": "잔류 염소", "weight": 1.0, "slide_nos": [3], "depth": 1}], "edges": []}
FACT = TRAP_Q.trap_premise.fact


def _doc() -> dict:
    return QuestionDoc(file_name="pool.pdf", track="5", model="fake", questions=[TRAP_Q, PLAIN_Q]).to_dict()


def _leaks(obj) -> bool:
    return FACT in json.dumps(obj, ensure_ascii=False) or "0.6ppm" in json.dumps(obj, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 규칙 한 벌
# ---------------------------------------------------------------------------

def test_사본은_함정의_세_칸을_비우고_보통_질문은_그대로_둔다_원본은_안_바뀐다():
    doc = _doc()
    before = copy.deepcopy(doc)
    out = CP.client_questions(doc)
    trap, plain = out["questions"]
    assert trap["gist_withheld"] is True and trap["trap"] is True
    assert trap["trap_premise"] is None and trap["answer_gist"] == "" and trap["answer_gist_parts"] == []
    assert not _leaks(trap) and trap["question"] == TRAP_Q.question
    assert plain is doc["questions"][1] and "gist_withheld" not in plain
    assert doc == before                                                     # 원본(채점 기준)은 그대로다


def test_함정이_없거나_모양이_다르면_받은_것을_그대로_돌려준다():
    plain_only = QuestionDoc(file_name="pool.pdf", questions=[PLAIN_Q]).to_dict()
    assert CP.client_questions(plain_only) is plain_only
    for odd in (None, {}, {"questions": None}, {"questions": "x"}, [1, 2], {"error": "bad"}):
        assert CP.client_questions(odd) is odd
    # 전제만 있고 trap 표시가 빠진 질문도 뺀다 (코드가 만든 전제를 들고 있으면 함정이다)
    only_premise = {"questions": [{**TRAP_Q.to_dict(), "trap": False}]}
    assert CP.client_questions(only_premise)["questions"][0]["gist_withheld"] is True


@pytest.mark.parametrize("verdict,score,stage,due", [
    ("wrong", 30, "", False),        # 아직 전제를 못 바로잡았다
    ("good", 85, "", True),          # 바로잡았다 (통과)
    ("unknown", 0, "explain", True), # 해설 단계
    ("partial", 55, "choices", False),
])
def test_기대_답은_바로잡았거나_해설_단계일_때만_싣는다(verdict, score, stage, due):
    j = QaJudgement(question_id=TRAP_Q.id, node_id=TRAP_Q.node_id, verdict=verdict, score=score, react="음.", coach_stage=stage)
    assert CP.reveal_due(TRAP_Q, j) is due
    assert CP.reveal_due(PLAIN_Q, j) is False                               # 보통 질문의 골자는 사본에 이미 있다
    assert CP.reveal_fields(TRAP_Q) == {"answer_gist": TRAP_Q.answer_gist, "reveal_quote": FACT, "reveal_slide_no": 3}


def test_브리지는_같은_규칙을_쓴다():
    assert bridge.client_questions is CP.client_questions
    assert bridge.reveal_fields is CP.reveal_fields and bridge.reveal_due is CP.reveal_due
    assert bridge.client_judgement is CP.client_judgement          # 판정 응답의 화면 사본 (근거 줄 포함, 2026-10-01)
    assert bridge.TRAP_WITHHELD == CP.TRAP_WITHHELD == ("trap_premise", "answer_gist", "answer_gist_parts")


# ---------------------------------------------------------------------------
# FastAPI 서버 — 플랫 라우트 · 세션 잡 · 세션 조회 · 판정
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    seen: dict = {"judged": []}

    def fake_build(graph, triage, *, track, **_):
        return QuestionDoc(file_name="pool.pdf", track=track, model="fake", questions=[TRAP_Q, PLAIN_Q])

    def fake_judge(question, answer, **kw):
        seen["judged"].append(question)
        if kw.get("give_up"):
            return QaJudgement(question_id=question.id, node_id=question.node_id, verdict="unknown", score=0,
                               react="괜찮아요.", coach_stage="explain", explanation="해설")
        fixed = "0.6ppm" in answer
        return QaJudgement(question_id=question.id, node_id=question.node_id, verdict="good" if fixed else "wrong",
                           score=85 if fixed else 30, react="음.")

    monkeypatch.setattr(server_app, "build_questions", fake_build)
    monkeypatch.setattr(server_app, "triage_questions", lambda *a, **k: QaTriage(file_name="pool.pdf"))
    monkeypatch.setattr(server_app, "judge_answer", fake_judge)
    monkeypatch.setattr(jobs, "build_questions", fake_build)
    monkeypatch.setattr(jobs, "triage_questions", lambda *a, **k: QaTriage(file_name="pool.pdf"))
    monkeypatch.setattr(chuckchuck, "build_papers", lambda *a, **k: None)
    monkeypatch.setattr(server_app, "_FLAT_TRAPS", OrderedDict(), raising=False)   # 테스트마다 비운다
    return TestClient(server_app.app), seen


def _flat_questions(tc) -> dict:
    res = tc.post("/api/v1/questions", json={"graph": GRAPH, "track": "5", "papers": False, "llm": "mock"})
    assert res.status_code == 200, res.text
    return res.json()


def _judge(tc, sid: str, q: dict, answer: str, **extra):
    res = tc.post(f"/api/v1/sessions/{sid}/qa/judge",
                  json={"question_id": q["id"], "question": q, "answer": answer, "history": [], "llm": "mock", **extra})
    assert res.status_code == 200, res.text
    return res.json()


def test_서버_플랫_질문은_화면_사본으로_나가고_판정은_원본으로_한다(client):
    tc, seen = client
    trap, plain = _flat_questions(tc)["questions"]
    assert trap["gist_withheld"] is True and not _leaks(trap)
    assert plain["answer_gist"] == PLAIN_Q.answer_gist and "gist_withheld" not in plain
    body = _judge(tc, "flat", trap, "네, 0.2ppm 으로 맞춰요.")                # 사본을 그대로 보냈다
    assert seen["judged"][-1].trap_premise is not None and seen["judged"][-1].answer_gist == TRAP_Q.answer_gist
    assert "answer_gist" not in body and "reveal_quote" not in body          # 못 바로잡았다 — 사실을 안 싣는다
    body = _judge(tc, "flat", trap, "아니에요, 자료 3장은 0.6ppm 으로 맞춘다고 해요.")
    assert body["passed"] and body["answer_gist"] == TRAP_Q.answer_gist and body["reveal_quote"] == FACT
    body = _judge(tc, "flat", trap, "(모르겠어요)", give_up=True)
    assert body["coach_stage"] == "explain" and body["answer_gist"] == TRAP_Q.answer_gist


def test_서버_답_보기는_reveal_요청으로_판정_없이_골자를_받는다(client):
    tc, seen = client
    trap = _flat_questions(tc)["questions"][0]
    n = len(seen["judged"])
    body = _judge(tc, "flat", trap, "", reveal=True)
    assert body["reveal"] is True and body["answer_gist"] == TRAP_Q.answer_gist and body["reveal_slide_no"] == 3
    assert len(seen["judged"]) == n                                          # 판정(LLM)을 부르지 않았다


def test_서버_문장이_다른_본문_질문에는_원본을_붙이지_않는다(client):
    """플랫은 모두가 나눠 쓰는 자리라 id 만 같은 다른 덱의 질문이 있을 수 있다 — 브리지처럼 문장까지 같을 때만 원본을 쓴다."""
    tc, seen = client
    trap = _flat_questions(tc)["questions"][0]
    other = {**trap, "question": "다른 덱의 질문이에요 — 같은 id 를 썼어요."}
    _judge(tc, "flat", other, "모르겠어요")
    assert seen["judged"][-1].trap_premise is None and seen["judged"][-1].question == other["question"]


def test_서버_세션_잡_결과와_세션_조회는_사본이고_세션의_원본으로_채점한다(client):
    tc, seen = client
    s = store.create_session(title="수영장")
    store.put_artifact(s.id, "concept_graph", GRAPH)
    job = store.create_job(s.id, "questions", {"track": "5", "llm": "mock"})
    result = jobs._handle_questions(job.id, s.id, {"track": "5", "llm": "mock"})
    store.update_job(job.id, status="succeeded", result=result)
    assert store.get_session(s.id).artifacts[QUESTION_DOC]["questions"][0]["trap_premise"]["fact"] == FACT   # 원본은 서버에

    polled = tc.get(f"/api/v1/jobs/{job.id}").json()
    assert polled["status"] == "succeeded" and polled["result"]["questions"][0]["gist_withheld"] is True
    assert not _leaks(polled)
    session = tc.get(f"/api/v1/sessions/{s.id}").json()
    assert session["artifacts"][QUESTION_DOC]["questions"][0]["gist_withheld"] is True and not _leaks(session)
    patched = tc.patch(f"/api/v1/sessions/{s.id}", json={"title": "동네 수영장"}).json()
    assert patched["title"] == "동네 수영장" and not _leaks(patched)

    trap = polled["result"]["questions"][0]
    _judge(tc, s.id, trap, "네, 0.2ppm 이에요.")
    assert seen["judged"][-1].trap_premise is not None                        # 세션의 원본(QUESTION_DOC)으로 채점
