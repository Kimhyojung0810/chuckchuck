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


def test_후보_판도_판마다_나뉘어_남의_3번_이후_기록이_안_보인다(monkeypatch):
    """4단계 리포트 판(ens_board) — 바탕은 같은 덱 질문 캐시로 나눠 쓰고, 3번+ 기록은 각자 판 칸에만 (합침 10-17)."""
    import json
    from types import SimpleNamespace
    from server import qa_board as QB

    monkeypatch.setattr(bridge, "STORE", SessionStore())
    archived = {}
    monkeypatch.setattr(bridge.Handler, "_archive", staticmethod(lambda body, kind, p: archived.__setitem__(kind, p)))
    monkeypatch.setattr(bridge.ARCHIVE, "read_artifact", lambda sid, kind: archived.get(kind))
    sid = "20261017T000000Z_deadbeef"
    graph = {"nodes": [{"id": "k", "label": "개념", "kind": "concept"}]}
    pool = {"slots": [{"id": "T1", "node_id": "k"}], "candidates": [{"uid": "ax:T1:0", "model": "ax", "slot": "T1", "question": "왜요?"}],
            "dropped": [], "calls": [], "timings": {}, "models": ["ax"]}
    bridge.STORE.set_triage("ens_board_base:x", QB.board(pool, ["ax:T1:0"], graph, track="10"))
    payload = {"questions": [], "ensemble": {"board_key": "ens_board_base:x"}}
    h = SimpleNamespace(_archive=bridge.Handler._archive, _json=lambda code, body: (code, body))
    for run in ("rAAAA1111", "rBBBB2222"):                    # 캐시된 같은 질문을 두 사람이 받아 간다
        bridge.Handler._bind_board(h, {"session_id": sid, "qa_run_id": run}, payload)
    vr = SimpleNamespace(signals=[{"id": "V1", "kind": "skip_reason", "label": "개념", "note": "A 가 건너뛴 곳"}],
                         candidates=[], dropped=[], calls=[], sec=1.0)
    nxt = {"uid": "solar4:V1:0", "model": "solar4", "question": "A 에게만 묻는 3번 질문?", "signal_kind": "skip_reason"}
    bridge.Handler._ensemble_round(h, {"session_id": sid, "qa_run_id": "rAAAA1111"}, 3, nxt, vr, [], 0.4)

    def read(run):
        code, body = bridge.Handler._handle_qa_board(h, json.dumps({"session_id": sid, "qa_run_id": run}).encode())
        return code, (body.get("board") or {})

    code_a, a = read("rAAAA1111")
    code_b, b = read("rBBBB2222")
    assert code_a == 200 and [r["question"] for r in a["rounds"]] == ["A 에게만 묻는 3번 질문?"]
    assert code_b == 200 and b["rounds"] == [] and b["picked"] == ["ax:T1:0"]
    assert bridge.STORE.get_triage("ens_board_base:x")["rounds"] == []          # 바탕은 안 고친다
    # 메모리가 지나 보관본만 남아도 — 보관본은 A 의 판이라 B 에게 안 준다
    monkeypatch.setattr(bridge, "STORE", SessionStore())
    assert read("rAAAA1111")[0] == 200 and read("rBBBB2222")[0] == 404
