"""네 모델 Q&A 후보 판 (main/server/qa_board.py) — 리포트 「질문은 이렇게 골랐어요」 재료."""
from types import SimpleNamespace

from server import qa_board as QB

GRAPH = {"nodes": [{"id": "t", "label": "핵심", "kind": "thesis", "evidence": "긴 근거 문장"},
                   {"id": "c", "label": "주장", "kind": "claim", "parent_id": "t"},
                   {"id": "k", "label": "개념", "kind": "concept", "parent_id": "c", "weight": 0.3}]}
POOL = {"slots": [{"id": "T1", "node_id": "k", "label": "개념", "pattern": "P8"}],
        "candidates": [{"uid": "ax:T1:0", "model": "ax", "slot": "T1", "question": "왜요?", "peer": 0.8, "peer_scores": []}],
        "dropped": [], "calls": [{"role": "generate", "model": "ax", "sec": 1.0, "ok": True, "prompt": "숨길 원문"}],
        "timings": {"total_sec": 3.0}, "models": ["ax"]}


def test_board_adds_path_graph_and_keeps_contract_fields():
    b = QB.board(POOL, ["ax:T1:0"], GRAPH, track="5")
    assert b["paths"]["T1"] == ["개념", "주장", "핵심"]
    assert all(set(n) <= set(QB.NODE_KEYS) for n in b["graph"]["nodes"])     # 근거 문장 같은 칸은 안 싣는다
    assert "prompt" not in b["calls"][0]
    assert b["picked"] == ["ax:T1:0"] and b["tracks"] == {"5": ["ax:T1:0"]}
    for k in ("slots", "candidates", "dropped", "calls", "timings", "models"):
        assert k in b


def test_rounds_replace_same_number_and_survive_same_pool_only():
    b = QB.board(POOL, ["ax:T1:0"], GRAPH, track="5")
    vr = SimpleNamespace(signals=[{"id": "V1", "kind": "weak_answer", "label": "개념", "speech_quote": "내 답 원문", "note": "약함"}],
                         candidates=[], dropped=[], calls=[], sec=1.0)
    nxt = {"uid": "ax:T1:0", "model": "ax", "question": "왜요?", "signal_kind": "weak_answer", "signal_quote": "내 답 원문"}
    b = QB.with_round(b, QB.round_record(3, nxt, vr, [], 0.5))
    b = QB.with_round(b, QB.round_record(3, {**nxt, "question": "다시?"}, vr, [], 0.5))
    assert [r["question"] for r in b["rounds"]] == ["다시?"]
    assert "speech_quote" not in b["rounds"][0]["signals"][0] and b["rounds"][0]["signal_quote"] == ""   # 답 원문은 판에 안 남긴다
    again = QB.board(POOL, ["ax:T1:0"], GRAPH, track="10", prev=b)
    assert len(again["rounds"]) == 1 and set(again["tracks"]) == {"5", "10"}
    other = QB.board({**POOL, "candidates": []}, [], GRAPH, prev=b)
    assert other["rounds"] == []
