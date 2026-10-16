"""
Q&A 한 판(qa_run_id) 나누기 (2026-10-17 5단계 · 4단계 보고) — 파싱이 같은 파일의 세션을 재사용해서(부스 덱은 미리 파싱한 세션 하나를
모두가 쓴다) 같은 덱을 고른 두 사람의 3번 이후 기록(이해 상태 · 이미 한 말 · 음성 후보 열쇠)이 한 세션에 섞이던 것.
"""

from __future__ import annotations

import server.bridge as bridge
from pipeline.contracts import QaJudgement
from server.session_store import SessionStore


def test_판_값은_모양이_맞을_때만_쓰고_없으면_예전처럼_세션_단위():
    assert bridge.qa_run_of({"qa_run_id": "r3f9a0c1d2e"}) == "r3f9a0c1d2e"
    assert bridge.qa_run_of({"qa_run_id": "../../etc"}) == ""
    assert bridge.qa_run_of({}) == ""
    assert bridge.run_key("S1", "rA1b2") == "S1:rA1b2" and bridge.run_key("S1", "") == "S1"


def test_같은_덱을_고른_두_사람의_기록은_서로_안_보인다(monkeypatch):
    monkeypatch.setattr(bridge, "STORE", SessionStore())
    sid = "20261017T000000Z_deadbeef"                      # 미리 파싱한 부스 덱 세션 — 두 사람이 같이 쓴다
    a, b = bridge.run_key(sid, "rAAAA1111"), bridge.run_key(sid, "rBBBB2222")
    ja = QaJudgement(question_id="e01", node_id="n1", verdict="wrong", score=30, react="「A 의 말」이라고 했죠.",
                     followup="A 에게 묻는 꼬리질문이에요?", move="challenge", dialogue={"read": {"skipped": "A 의 빈 고리"}})
    bridge._dialogue_note(a, ja)
    assert bridge._dialogue_said(b) == [] and bridge.STORE.get_triage(bridge._DLG_NODES + b) is None
    assert "「A 의 말」이라고 했죠." in bridge._dialogue_said(a)
    assert bridge.STORE.get_triage(bridge._DLG_NODES + a)["n1"]["state"] == "misread"
    jb = QaJudgement(question_id="e01", node_id="n1", verdict="good", score=85, react="B 의 반응이에요.", move="deepen")
    bridge._dialogue_note(b, jb)
    assert bridge.STORE.get_triage(bridge._DLG_NODES + b)["n1"]["state"] == "understood"
    assert bridge.STORE.get_triage(bridge._DLG_NODES + a)["n1"]["state"] == "misread"     # A 의 상태는 그대로
    assert "B 의 반응이에요." not in bridge._dialogue_said(a)
