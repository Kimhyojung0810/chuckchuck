"""
미리 판정 (2026-10-17 tune · server/qa_spec.py) — 화면이 말 끝을 짐작한 순간 같은 본문을 speculative 로 보내면 판정만 뒤에서 돌고,
진짜 요청이 그 판정을 받아 쓴다. 미리 보낸 요청은 기록(qa_turns)도 대화 상태도 남기지 않는다. 답이 바뀌면(더 말함) 새로 판정한다.
"""
from __future__ import annotations

import time

import server.bridge as bridge
from server import qa_spec
from tests.test_judge_followups_j2 import PLAIN_Q, _post, _questions, bridge_env  # noqa: F401 — 픽스처 재사용


def _judge_body(sid: str, answer: str, **extra) -> dict:
    return {"session_id": sid, "question_id": PLAIN_Q.id, "answer": answer, "history": [], "prior_answers": [],
            "hints_shown": [], "give_up": False, "qa_run_id": "rspec0001", **extra}


def _wait_done(timeout: float = 3.0) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        with qa_spec._LOCK:
            if all(f.done() for _, f in qa_spec._ITEMS.values()):
                return
        time.sleep(0.02)


def test_미리_판정은_202_로_받고_진짜_요청이_그_판정을_쓴다_기록은_진짜_요청만(bridge_env):
    sid, seen = bridge_env
    _questions(sid)
    path = f"/api/v1/sessions/{sid}/qa/judge"
    code, pay = _post(path, _judge_body(sid, "전해질이 고체라 불이 잘 안 붙어요", speculative=True))
    assert code == 202 and pay["speculative"] is True and pay["started"] is True
    _wait_done()
    assert len(seen["judge"]) == 1                                         # 판정은 뒤에서 한 번 돌았다
    assert bridge.ARCHIVE.read_stream(sid, "qa_turns") == []               # 미리 보낸 요청은 기록을 안 남긴다
    code, pay = _post(path, _judge_body(sid, "전해질이 고체라 불이 잘 안 붙어요"))
    assert code == 200 and pay.get("speculative_hit") is not None
    assert len(seen["judge"]) == 1                                         # 진짜 요청은 다시 판정하지 않았다
    assert len(bridge.ARCHIVE.read_stream(sid, "qa_turns")) == 1           # 기록은 진짜 요청이 남긴다


def test_더_말해서_답이_바뀌면_미리_한_판정은_버리고_새로_판정한다(bridge_env):
    sid, seen = bridge_env
    _questions(sid)
    path = f"/api/v1/sessions/{sid}/qa/judge"
    assert _post(path, _judge_body(sid, "전해질이 고체라서요", speculative=True))[0] == 202
    _wait_done()
    code, pay = _post(path, _judge_body(sid, "전해질이 고체라서요. 그래서 불이 잘 안 붙어요"))
    assert code == 200 and "speculative_hit" not in pay
    assert len(seen["judge"]) == 2


def test_같은_본문을_두_번_미리_보내도_판정은_한_번(bridge_env):
    sid, seen = bridge_env
    _questions(sid)
    path = f"/api/v1/sessions/{sid}/qa/judge"
    body = _judge_body(sid, "고체 전해질이라 불이 덜 붙어요", speculative=True)
    assert _post(path, body)[1]["started"] is True
    assert _post(path, body)[1]["started"] is False
    _wait_done()
    assert len(seen["judge"]) == 1


def test_QA_SPEC_0_이면_미리_판정을_하지_않는다(bridge_env, monkeypatch):
    sid, seen = bridge_env
    _questions(sid)
    monkeypatch.setenv("QA_SPEC", "0")
    path = f"/api/v1/sessions/{sid}/qa/judge"
    code, pay = _post(path, _judge_body(sid, "고체라서요", speculative=True))
    assert code == 202 and pay["started"] is False
    assert seen["judge"] == []


def test_화면_주소를_해시로_돌려보낼_때_qa_설정만_실어_간다():
    assert bridge._qa_query("qa_turn=fast&utm=x&qa_send_ms=1200") == "?qa_turn=fast&qa_send_ms=1200"
    assert bridge._qa_query("x=1") == ""
    assert bridge._qa_query("qa_eot=%3Cscript%3E") == ""
