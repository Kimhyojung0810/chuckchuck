"""
10-17 Q&A 버그 사냥(etc/labs/qa_hunt/sim.py · docs/qa-ensemble/HUNT_REPORT.md) 회귀 — 같은 덱 세션을 나눠 쓰는 판끼리의 충돌,
3번+ 질문 고르기의 지연, 갇힘 출구 해설 · 되물음 문장, 줄 번호 떼기.
"""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

import server.bridge as bridge
from pipeline import f08_ensemble as FE
from pipeline import f09_judge as J
from pipeline.contracts import Question, QuestionBasis
from server.session_store import MAX_TRACKS, SessionStore

SID = "20261017T000000Z_deadbeef"


# ── 요청 제한 칸 — 같은 덱 세션을 나눠 쓰는 사람끼리 30회/분을 나눠 쓰지 않는다 ─────────────────────────

class _H(bridge.Handler):
    def __init__(self):  # noqa: D401 — 소켓 없이 칸만 계산
        self.headers = {}
        self.client_address = ("127.0.0.1", 0)

    def _client_key(self):
        return "203.0.113.7"


def test_요청_제한은_QA_판마다_센다(monkeypatch):
    monkeypatch.setattr(bridge.ARCHIVE, "safe_id", lambda raw: raw if raw == SID else None)
    h = _H()
    a = h._rate_bucket(f"/api/v1/sessions/{SID}/qa/judge", json.dumps({"session_id": SID, "qa_run_id": "rAAAA1111"}).encode())
    b = h._rate_bucket("/api/v1/qa/next", json.dumps({"session_id": SID, "qa_run_id": "rBBBB2222"}).encode())
    assert a == f"session:{SID}:rAAAA1111" and b == f"session:{SID}:rBBBB2222"
    monkeypatch.setattr(bridge, "_deck_session_known", lambda sid: False)
    assert h._rate_bucket("/api/v1/chatter", json.dumps({"session_id": SID}).encode()) == "session:" + SID   # 판 값 없는 옛 요청은 예전처럼


def test_시연_덱_세션의_분석_요청은_세션과_사람_칸으로(monkeypatch):
    monkeypatch.setattr(bridge.ARCHIVE, "safe_id", lambda raw: raw if raw == SID else None)
    monkeypatch.setattr(bridge, "_deck_session_known", lambda sid: sid == SID)
    assert _H()._rate_bucket("/api/v1/chatter", json.dumps({"session_id": SID}).encode()) == f"session:{SID}@203.0.113.7"


def test_덱_sha_묶음은_요청_스레드에서_만들지_않는다(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(bridge, "_DECK_SHAS", {"at": 0.0, "shas": frozenset()})
    monkeypatch.setattr(bridge, "_deck_shas", lambda: (gate.wait(5), {"abc": {}})[1])
    t0 = time.monotonic()
    assert bridge._deck_session_known(SID) is False
    assert time.monotonic() - t0 < 0.5                      # 덱 파일을 다 읽는 동안 서 있지 않는다
    gate.set()


# ── 3번+ 질문 트랙은 판마다 — 뒷사람이 같은 id 로 덮어써 앞사람 답이 남의 질문으로 채점되던 것 ────────────────

def _next_handler(monkeypatch, picks):
    monkeypatch.setattr(bridge, "STORE", SessionStore())
    monkeypatch.setattr(FE, "enabled", lambda: True)
    monkeypatch.setattr(FE, "voice_round", lambda *a, **k: None)
    monkeypatch.setattr(FE, "choose_next", lambda pool, vr, asked, calls=None: picks.pop(0))
    monkeypatch.setattr(bridge.ARCHIVE, "read_artifact", lambda sid, kind: None)
    monkeypatch.setattr(bridge.ARCHIVE, "safe_id", lambda raw: raw if raw == SID else None)
    bridge.STORE.set_triage("ens_sid:" + SID, "ens_pool:x")
    bridge.STORE.set_triage("ens_pool:x", {"pool": True})
    h = SimpleNamespace(_resolve=lambda body, *keys: {k: None for k in keys}, _json=lambda code, body: (code, body),
                        _ensemble_round=lambda *a, **k: None)
    return h


def test_같은_id_의_3번_질문을_두_판이_받아도_각자_제_질문으로_채점된다(monkeypatch):
    cand = lambda text: {"uid": "ax:T3:0", "model": "ax", "node_id": "n3", "label": "개념", "question": text, "answer": "모범답이에요.",
                         "slot": "T3", "pattern": "P2"}
    h = _next_handler(monkeypatch, [cand("A 에게 낸 3번 질문인가요?"), cand("B 에게 낸 3번 질문인가요?")])
    asked = [{"question_id": "e01-x", "answer": "답", "verdict": "good"}, {"question_id": "e02-y", "answer": "답", "verdict": "good"}]
    out = {}
    for run in ("rAAAA1111", "rBBBB2222"):
        code, body = bridge.Handler._handle_qa_next(h, json.dumps({"session_id": SID, "qa_run_id": run, "asked": asked}).encode())
        assert code == 200
        out[run] = body["question"]
    assert out["rAAAA1111"]["id"] == out["rBBBB2222"]["id"]                       # 자리 번호 + 노드라 id 가 같다
    for run, text in (("rAAAA1111", "A 에게 낸 3번 질문인가요?"), ("rBBBB2222", "B 에게 낸 3번 질문인가요?")):
        q, src = bridge.Handler._resolve_question(None, SID, SID, out[run]["id"], {"id": out[run]["id"], "question": text})
        assert src == "server" and q.question == text                              # 예전: A 는 mismatch 로 B 의 질문으로 채점됐다


def test_다음_질문의_앞_답은_화면이_실은_문장으로_고른다(monkeypatch):
    seen = {}

    def choose(pool, vr, asked, calls=None):
        seen["asked"] = [a["question"] for a in asked]
        return {}

    h = _next_handler(monkeypatch, [])
    monkeypatch.setattr(FE, "choose_next", choose)
    bridge.STORE.remember_questions(SID, "10", {"questions": [{"id": "e03-n", "question": "준비한 3번이에요?"}]})
    bridge.STORE.remember_questions(SID, "ens:rZZZZ9999:e03-n", {"questions": [{"id": "e03-n", "question": "남의 3번이에요?"}]})
    body = {"session_id": SID, "qa_run_id": "rAAAA1111",
            "asked": [{"question_id": "e03-n", "question": "준비한 3번이에요?", "answer": "답", "verdict": "wrong"}]}
    bridge.Handler._handle_qa_next(h, json.dumps(body).encode())
    assert seen["asked"] == ["준비한 3번이에요?"]


def test_세션_질문_트랙은_상한까지만_쌓인다():
    st = SessionStore()
    for i in range(MAX_TRACKS + 40):
        st.remember_questions(SID, f"ens:r{i:08d}:e03", {"questions": [{"id": f"e{i}", "question": "?"}]})
    st.remember_questions(SID, "10", {"questions": [{"id": "q01", "question": "기본"}]})
    assert st.find_questions(SID, "q01") and not st.find_questions(SID, "e0")       # 가장 오래된 것부터 빠진다
    assert st.find_questions(SID, f"e{MAX_TRACKS + 39}")


# ── 후보 판은 실제로 물은 3번+ 질문만 ────────────────────────────────────────────────────────────────

def test_판에는_판정받은_질문만_남는다(monkeypatch):
    monkeypatch.setattr(bridge, "STORE", SessionStore())
    b = {"candidates": [1], "rounds": [{"n": 3, "question_id": "e03-a", "question": "늦게 고른 질문?"},
                                       {"n": 4, "question_id": "e04-b", "question": "물은 질문?"},
                                       {"n": 5, "question": "id 없는 옛 기록?"}]}
    key = bridge.run_key(SID, "rAAAA1111")
    bridge._note_judged(key, "e04-b")
    bridge._note_judged(key, "e04-b")
    out = bridge.board_asked_only(b, bridge.STORE.get_triage(bridge._ENS_JUDGED + key))
    assert [r["n"] for r in out["rounds"]] == [4, 5] and len(b["rounds"]) == 3              # 원본은 그대로
    assert bridge.board_asked_only(b, None) is b                                         # 기록이 없으면(다시 띄움) 그대로


# ── 최종 선택은 상한 안에서만 기다린다 ─────────────────────────────────────────────────────────────

def test_최종_선택이_늦으면_음성_후보_1등을_바로_낸다(monkeypatch):
    pool = SimpleNamespace(winners=lambda: [{"uid": "p", "node_id": "n9", "question": "묶음 질문이에요?", "peer": 0.5}])
    vr = SimpleNamespace(candidates=[{"uid": "v1", "node_id": "n1", "question": "음성 질문 하나예요?", "peer": 0.4},
                                     {"uid": "v2", "node_id": "n2", "question": "다른 음성 질문이에요?", "peer": 0.9}])
    monkeypatch.setattr(FE, "ens_pick", lambda *a, **k: (time.sleep(2), {"uid": "v1", "reason": "늦은 선택"})[1])
    t0 = time.monotonic()
    got = FE.choose_next(pool, vr, [], llm=object(), pick_wait=0.3)
    assert time.monotonic() - t0 < 1.0 and got["uid"] == "v2" and got["pick_failed"] and "늦어" in got["pick_reason"]
    monkeypatch.setattr(FE, "ens_pick", lambda *a, **k: {"uid": "v1", "reason": "고른 까닭이에요."})
    assert FE.choose_next(pool, vr, [], llm=object(), pick_wait=0.3)["uid"] == "v1"


# ── 줄 번호 떼기 · 되물음 · 해설 문장 ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, want", [
    ("S8.19가 말하는 ‘감각의 문제’는 무엇인가요?", "자료 8장이 말하는 ‘감각의 문제’는 무엇인가요?"),
    ("S2.1로 보면 어떤가요?", "자료 2장으로 보면 어떤가요?"),
    ("S3.4의 차트에서 무엇이 보이나요?", "차트에서 무엇이 보이나요?"),            # 예전 그대로
    ("근거(S3.2)는 무엇인가요?", "근거는 무엇인가요?"),
])
def test_줄_번호를_떼도_조사만_남지_않는다(raw, want):
    assert FE._strip_line_ids(raw) == want


def _q(label, **kw):
    return Question(id="e03-x", node_id="n", label=label, question="왜 그런가요?", **kw)


def test_되물음_마지막_틀은_문장_이름에도_말이_된다():
    long = "평균 별점 대신 환불·재주문 같은 행동 지표를 함께 노출하고, 리뷰 이벤트 매장은 따로 표시해야 한다"
    text = J._why_needed(_q(long, evidence_slide_no=3))
    assert " 이 왜" not in text and text.startswith("자료 3장의 「") and text.endswith("볼까요?")
    assert J._why_needed(_q("수면 부채")) == "수면 부채가 왜 필요했는지부터 떠올려 볼까요?"
    assert J._why_needed(_q("별점 인플레이션")) == "별점 인플레이션이 왜 필요했는지부터 떠올려 볼까요?"


def test_해설_인용은_표_칸을_잇고_제목_한_낱말은_싣지_않는다():
    assert J._explain_quote("| 리뷰 이벤트가 높은 별점을 산다 | 지지 | 매장 평균이 +0.34점 높았다. |") == \
        "리뷰 이벤트가 높은 별점을 산다 · 지지 · 매장 평균이 +0.34점 높았다."
    q = _q("제언", answer_gist="행동 지표가 별점 편향을 보완해요.", evidence_slide_no=3, evidence_quote="제언")
    out = J._explain_text(q, "환불과 재주문은 리뷰를 안 써도 남는 기록이라 별점 편향을 보완해요.", None)
    assert "«제언»" not in out and out.startswith("환불과 재주문은")


def test_앙상블_모범답은_자료로_다듬어졌으면_해설에_쓴다(monkeypatch):
    q = _q("행동 지표", answer_gist="환불과 재주문은 리뷰를 쓰지 않아도 남아서 별점 편향을 보완해요.", evidence_slide_no=3,
           evidence_quote="제언", basis=QuestionBasis(source="core_weight", checks=["ensemble", "gist_polished"]))
    monkeypatch.setattr(J, "support", lambda *a, **k: SimpleNamespace(grounded=False, conflicts=[], missing_numbers=[]))
    deck = SimpleNamespace(empty=False)
    assert J._explain_text(q, "", deck).startswith("환불과 재주문은")
    plain = _q("행동 지표", answer_gist=q.answer_gist, evidence_slide_no=3, evidence_quote="제언")
    assert not J._explain_text(plain, "", deck).startswith("환불과 재주문은")         # 앙상블이 아니면 예전처럼 자료 대조


@pytest.mark.parametrize("raw, want", [
    ("그 근거를 설명해 주실 수 있나요?", "그 근거를 설명해 줄 수 있나요?"),
    ("2장에서 거의 설명하지 않으셨어요. 왜 그런지 설명해 주실 수 있을까요?", "2장에서 거의 설명하지 않았어요. 왜 그런지 설명해 줄 수 있을까요?"),
    ("발표에서 강조하신 부분은 왜 중요한가요?", "발표에서 강조한 부분은 왜 중요한가요?"),
])
def test_앙상블_질문의_높임을_푼다(raw, want):
    assert FE.tidy({"question": raw, "answer": "모범답이에요."})["question"] == want


def test_꼬리질문_틀의_인용_뒤_조사는_받침에_맞춘다():
    from pipeline import f09_dialogue as DLG
    assert DLG._quote_josa("「리뷰 수집 방법」는 다른 이야기예요.", "리뷰 수집 방법") == "「리뷰 수집 방법」은 다른 이야기예요."
    assert DLG._quote_josa("「표본이 작음」로 근거와 결론을 이었어요.", "표본이 작음") == "「표본이 작음」으로 근거와 결론을 이었어요."
    assert DLG._quote_josa("「그 말」로 이었어요.", "그 말") == "「그 말」로 이었어요."                       # ㄹ 받침은 「로」
    assert DLG._quote_josa("「축구 보셨어요」는 다른 이야기예요.", "축구 보셨어요") == "「축구 보셨어요」는 다른 이야기예요."


def test_꼬리질문_틀이_다_쓰였는데_구절이_없으면_그_말을_지어내지_않는다():
    from pipeline import f09_dialogue as DLG
    ti = SimpleNamespace(slide_no=0, asked=[], avoid=[q for _, q in DLG._TEMPLATES["refocus"]])
    react, _ = DLG.template_turn("refocus", "", ti)
    assert "그 말" not in react
