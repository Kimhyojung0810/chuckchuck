"""
발표를 들으며 3번+ 질문 준비 (2026-10-17, docs/qa-ensemble/LIVE_REPORT.md) — 가짜 엔진으로 흐름 · 규율만 본다.

- 1·2번은 언제나 자료 묶음(슬라이드 기반) — 발표 중 음성 후보는 3번부터 (사용자 10-17)
- 프롬프트 맥락은 「모든 장의 요지 + 신호 장 원문」 — 앞 2,400자 자르기로 뒷장이 빠지던 것
- 노드의 장을 다 들은 뒤에만 신호 · 같은 신호는 한 번만
- 같은 덱 세션을 여러 사람이 써도 발표(talk_id) 단위로 나뉘어 남의 발화 · 후보가 섞이지 않는다
"""
from __future__ import annotations

import json
import re

from pipeline import _ens_live as EL
from pipeline import f08_ensemble as FE
from pipeline.contracts import ConceptGraph, ConceptNode, Slide, SlideBlock, SlideDoc
from pipeline.providers.llm_base import LLMProvider
from server import qa_listen
from server.session_store import SessionStore


def _slide(no: int, text: str, title: str) -> Slide:
    return Slide(slide_no=no, title=title, blocks=[SlideBlock(category="paragraph", text=t) for t in text.split("\n")])


def deck():
    slides = [
        _slide(1, "급속충전은 배터리 수명을 깎는가\n2C 충전은 500 사이클에서 용량의 4분의 1을 깎았다", "급속충전"),
        _slide(2, "실험 설계\n충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었다\n셀 24개를 3수준 × 2수준에 4개씩 배정했다", "설계"),
        _slide(3, "결과\n2C 충전 후 유지율은 76%였다\n온도를 45도로 올리면 유지율이 더 떨어졌다", "결과"),
        _slide(4, "한계\n가속 조건에서 나온 값이라 실사용과는 다르다\n실사용 주행 데이터로 다시 확인해야 한다", "한계"),
    ]
    nodes = [
        ConceptNode(id="root", label="2C 충전은 500 사이클에서 용량의 4분의 1을 깎았다", slide_nos=[1, 3], kind="thesis", weight=1.0),
        ConceptNode(id="design", label="충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었다", slide_nos=[2], kind="claim",
                    parent_id="root", depth=2, weight=0.6),
        ConceptNode(id="limit", label="가속 조건에서 나온 값이라 실사용과는 다르다", slide_nos=[4], kind="claim", parent_id="root",
                    depth=2, weight=0.5),
    ]
    graph = ConceptGraph(file_name="a.pptx", total_slides=4, nodes=nodes)
    return graph, SlideDoc(file_name="a.pptx", total_slides=4, slides=slides)


# 결론(라벨)은 말하고 근거 줄은 거의 안 말한 발화 → skipped_reason 신호
SAID = {
    1: "오늘 결론은 2C 충전은 500 사이클에서 용량의 4분의 1을 깎았다는 것입니다.",
    2: "충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었다 이렇게 정리할 수 있습니다.",
    3: "그래서 2C 충전은 용량을 깎았다고 봅니다.",
    4: "가속 조건에서 나온 값이라 실사용과는 다르다는 점만 짚고 마치겠습니다.",
}


class FakeGen(LLMProvider):
    """생성 · 서로 평가 · 고르기 · 음성(발표 중 포함) 가짜 엔진. 받은 프롬프트를 남긴다."""

    def __init__(self, name: str):
        self.name = name
        self.users: list[str] = []

    def complete(self, *, system: str, user: str, **kw) -> str:
        self.users.append(user)
        if "[TASK] qa-ensemble-generate" in user:
            items = []
            for m in re.finditer(r"^(T\d+) · P\d+ .*?대상: 「([^」]+)」.*?관련 줄: ([^\n]*)", user, re.M):
                items.append({"slot": m.group(1), "question": f"{m.group(2)[:20]}이라는 결론은 왜 그렇게 나왔나요?",
                              "answer": "충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었기 때문이에요.",
                              "lines": [m.group(3).split(",")[0].strip()]})
            return json.dumps({"items": items}, ensure_ascii=False)
        if "[TASK] qa-ensemble-peer-review" in user:
            ids = re.findall(r"^(K\d+) ", user, re.M)
            return json.dumps({"scores": [{"id": k, "core": 4, "grounded": 5, "specific": 4, "clear": 5, "answer_ok": True}
                                          for k in ids]})
        if "[TASK] qa-ensemble-live" in user or "[TASK] qa-ensemble-voice" in user:
            items = []
            for m in re.finditer(r"^(V\d+) \[[a-z_]+\] 「([^」]+)」", user, re.M):
                items.append({"signal": m.group(1),
                              "question": f"{m.group(2)[:18]}이라는 주장을 충전 속도와 온도만 바꾼 설계가 어떻게 받치나요?",
                              "answer": "충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었기 때문이에요.", "lines": ["S2.2"]})
            return json.dumps({"items": items}, ensure_ascii=False)
        if "[TASK] qa-ensemble-pick" in user:
            # 신호가 붙은(음성 · 발표 중) 후보가 있으면 그것 — 없으면 첫 후보
            m = re.search(r"^(C\d+): .*\[신호:", user, re.M)
            return json.dumps({"pick": m.group(1) if m else "C1", "reason": "핵심 논리를 묻는 질문이에요."}, ensure_ascii=False)
        return "{}"


def _pool():
    graph, sd = deck()
    llms = {n: FakeGen(n) for n in ("solar4", "ax")}
    return graph, sd, FE.build_pool(graph, sd, models=["solar4", "ax"], llms=llms), llms


# ─── 1·2번은 자료 기반 ────────────────────────────────────────────────────────────────────────────

def test_1_2번은_언제나_자료_묶음에서_나온다_발표_중_후보는_3번부터():
    graph, sd, pool, _ = _pool()
    picked = FE.pick_session(pool, None, 5)
    assert len(picked) >= 2
    for c in picked[:2]:
        assert c["pattern"].startswith("P") and c.get("origin") is None and c.get("slot", "").startswith("T")
        q = FE.to_question(c, 1)
        assert "live" not in q.basis.checks and not any(x.startswith("signal:") for x in q.basis.checks)
    # 발표 중 후보가 잔뜩 있어도 1·2번 고르기(pick_opening)는 묶음만 본다 — 입력에 발표 후보가 들어갈 자리가 없다
    import inspect
    assert "live" not in inspect.signature(FE.pick_opening).parameters
    assert "live" not in inspect.signature(FE.pick_session).parameters


# ─── 맥락: 장별 요지 + 신호 장 원문 ───────────────────────────────────────────────────────────────

def test_맥락은_발표_전체를_덮는다_앞부분_자르기로_뒷장이_빠지지_않는다(monkeypatch):
    graph, sd = deck()
    d = FE.Deck.build(graph, sd)
    long = {n: (SAID[n] + " ") * 25 for n in SAID}          # 장마다 ~1,000자 — 앞 2,400자면 3·4장이 통째로 빠진다
    long[4] = long[4] + " 마지막으로 실사용 주행 데이터로 다시 확인해야 한다고 말씀드립니다."
    monkeypatch.setenv("QA_ENS_DIGEST", "0")
    old = FE.speech_context(long, d, [])
    assert "4장" not in old and "실사용 주행" not in old
    monkeypatch.setenv("QA_ENS_DIGEST", "1")
    new = FE.speech_context(long, d, [{"slide_no": 3}])
    assert all(f"- {n}장:" in new for n in (1, 2, 3, 4))
    assert "[3장]" in new and len(new) <= EL.DIGEST_MAX + 200


def test_장_요지는_자료_낱말을_담은_문장을_고른다():
    toks = EL._slide_tokens(deck()[1].slides[1])
    speech = "음 안녕하세요 반갑습니다 오늘 날씨가 좋네요. " * 6 + "충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었습니다."
    g = EL.slide_gist(speech, toks, 80)
    assert "충전 속도" in g and len(g) <= 80


# ─── 장 단위 쌓기 · 신호 ─────────────────────────────────────────────────────────────────────────

def test_노드의_장을_다_들은_뒤에만_신호_같은_신호는_한번만():
    graph, sd = deck()
    d = FE.Deck.build(graph, sd)
    t = EL.LiveTalk()
    t.put(1, SAID[1], closed=True)
    # root 는 1·3장 — 1장만 들었으면 아직 아니다
    assert all(s["node_id"] != "root" for s in EL.new_signals(t, d.graph, d.slides, d.lines))
    t.put(2, SAID[2], closed=True)
    t.put(3, SAID[3], closed=True)
    sigs = EL.new_signals(t, d.graph, d.slides, d.lines)
    assert any(s["node_id"] == "root" for s in sigs)
    t.done_sigs = [EL.sig_key(s) for s in sigs]
    assert EL.new_signals(t, d.graph, d.slides, d.lines) == []
    t.put(3, SAID[3] + " 덧붙여요.", closed=True)            # 같은 장을 다시 보내면 바꿔 쓴다(멱등) — 닫힌 장 목록은 그대로
    assert t.closed == [1, 2, 3] and t.slides[3].endswith("덧붙여요.")


def _listener(store, graph, sd, llms):
    return qa_listen.Listener(store, lambda sid: (graph.to_dict(), sd.to_dict()), lambda key, fn: fn(),
                              llms=llms, models=["solar4"])


def test_발표_중_후보는_발표_단위로_나뉜다_같은_덱_세션의_남의_후보가_안_보인다(monkeypatch):
    monkeypatch.setenv("QA_ENSEMBLE", "1")
    graph, sd = deck()
    store = SessionStore()
    llms = {"solar4": FakeGen("solar4")}
    L = _listener(store, graph, sd, llms)
    sid = "20261017T000000Z_deadbeef"                      # 부스 덱 — 두 사람이 같은 세션
    for n in (1, 2, 3, 4):
        L.put(sid, "tAAAA1111", slide_no=n, text=SAID[n], closed=True, final=(n == 4))
    a = L.candidates(sid, "tAAAA1111")
    assert a and all(c["origin"] == "live" and c["uid"].split(":")[-1].startswith("lv") for c in a)
    assert L.candidates(sid, "tBBBB2222") == [] and L.speech_of(sid, "tBBBB2222") == {}
    L.put(sid, "tBBBB2222", slide_no=1, text="B 는 1장만 말했어요.", closed=False)
    assert "B 는" not in " ".join(L.speech_of(sid, "tAAAA1111").values())
    live_users = [u for u in llms["solar4"].users if "qa-ensemble-live" in u]
    assert live_users and all("B 는" not in u for u in live_users)
    # 라운드 상한 · 같은 신호 두 번 안 함 — 장을 다시 보내도 새 신호가 없으면 부르지 않는다
    n_calls = len(llms["solar4"].users)
    L.put(sid, "tAAAA1111", slide_no=4, text=SAID[4], closed=True)
    assert len(llms["solar4"].users) == n_calls


def test_3번은_발표_중_후보를_고르고_아직_안_물은_장을_먼저(monkeypatch):
    graph, sd, pool, llms = _pool()
    opening = FE.pick_opening(pool)
    asked = [{"question": o["question"], "node_id": o["node_id"], "slide_no": o.get("slide_no")} for o in opening]
    free = next(n.id for n in graph.nodes if n.id not in {o["node_id"] for o in opening})
    live = [
        {"uid": "solar4:V1:lv0", "model": "solar4", "node_id": free, "slide_no": 4, "question": "가속 조건 값이 실사용과 다르다는 한계가 결론을 어디까지 흔드나요?",
         "origin": "live", "signal_kind": "skipped_reason", "signal_note": "…", "peer": 0.0},
        {"uid": "ax:V2:lv1", "model": "ax", "node_id": free, "slide_no": 4, "question": "같은 노드 둘째 후보예요?", "origin": "live",
         "peer": 0.0},
    ]
    opts = FE.live_options(live, asked)
    assert [o["uid"] for o in opts] == ["solar4:V1:lv0"]          # 장 · 노드마다 하나
    nxt = FE.choose_next(pool, None, asked, live=live, llm=llms["solar4"])
    assert nxt["substituted"] is False and nxt["origin"] == "live"
    # 한 번 물은 노드의 발표 중 후보는 뒤로(다른 각도라 남긴다) · 두 번 물은 노드는 뺀다
    other = {"uid": "ax:V3:lv2", "model": "ax", "node_id": "zzz", "slide_no": 1, "question": "전혀 다른 노드의 질문이에요?", "origin": "live"}
    assert [o["uid"] for o in FE.live_options(live + [other], asked + [{"question": "x", "node_id": free}])][0] == "ax:V3:lv2"
    assert all(o["node_id"] != free for o in FE.live_options(live, asked + [{"question": "x", "node_id": free}] * 2))


# ─── 브리지: /qa/live → /qa/next 는 그 발표(talk)의 후보만 ─────────────────────────────────────────────

def test_브리지_3번은_내_발표의_후보만_쓰고_남의_발표_후보는_안_본다(monkeypatch):
    from types import SimpleNamespace

    import server.bridge as bridge

    monkeypatch.setenv("QA_ENSEMBLE", "1")
    graph, sd, pool, llms = _pool()
    fake = {n: FakeGen(n) for n in ("solar4", "ax", "midm", "exaone")}
    monkeypatch.setattr(FE, "make_llm", lambda name: fake.get(name) or FakeGen(name))
    monkeypatch.setattr(bridge, "STORE", SessionStore())
    monkeypatch.setattr(bridge.ARCHIVE, "read_artifact", lambda sid, kind: sd.to_dict() if kind == "slide_doc" else None)
    L = qa_listen.Listener(bridge.STORE, lambda sid: (graph.to_dict(), sd.to_dict()), lambda key, fn: fn(), llms=fake,
                           models=["solar4"])
    monkeypatch.setattr(bridge, "LISTENER", L)
    sid = "20261017T000000Z_deadbeef"
    bridge.STORE.set_triage("ens_pool:x", pool)
    bridge.STORE.set_triage("ens_sid:" + sid, "ens_pool:x")
    h = SimpleNamespace(_json=lambda code, body: (code, body), _ensemble_round=lambda *a, **k: None)
    h._resolve = lambda body, *keys: bridge.Handler._resolve(h, body, *keys)
    for n in (1, 2, 3, 4):                                   # A 만 발표했다 (B 는 같은 덱 세션 · 다른 발표)
        code, body = bridge.Handler._handle_qa_live(h, json.dumps({"session_id": sid, "talk_id": "tAAAA1111", "slide_no": n,
                                                                    "text": SAID[n], "closed": True, "final": n == 4}).encode())
        assert code == 202 and body["live"] is True
    assert L.candidates(sid, "tAAAA1111")
    opening = FE.pick_opening(pool)
    asked = [{"question_id": "", "question": o["question"], "answer": "모르겠어요", "verdict": "partial"} for o in opening]

    def nxt(talk, run):
        req = {"session_id": sid, "graph": graph.to_dict(), "transcript": None, "alignment": None, "asked": asked,
               "qa_run_id": run, "talk_id": talk, "wait_sec": 2}
        return bridge.Handler._handle_qa_next(h, json.dumps(req).encode())[1]

    a = nxt("tAAAA1111", "rAAAA1111")
    b = nxt("tBBBB2222", "rBBBB2222")
    # A — 발표 중 후보 · A 의 장별 발화로 만든 음성 후보 중에서 (대신 내지 않음). B — A 의 발화 · 후보가 안 보여 묶음에서 대신 낸다
    assert a["origin"] in ("live", "answer") and a["substituted"] is False
    assert b["origin"] == "pool" and b["substituted"] is True
    # 발표가 없는 판(talk 없음)은 예전 그대로
    assert nxt("", "rCCCC3333")["origin"] != "live"


def test_브리지_묶음이_있으면_질문_요청이_지금_방식을_건너뛰고_자료_묶음에서_1_2번(monkeypatch):
    from types import SimpleNamespace

    import server.bridge as bridge

    monkeypatch.setenv("QA_ENSEMBLE", "1")
    graph, sd, pool, _ = _pool()
    monkeypatch.setattr(bridge, "STORE", SessionStore())
    sid = "20261017T000000Z_deadbeef"
    nodes = sorted((n.get("id"), n.get("label"), n.get("kind"), n.get("parent_id")) for n in graph.to_dict()["nodes"])
    key = "ens_pool:" + bridge.fingerprint(nodes, bridge.fingerprint(sd.to_dict()), FE.model_names(), FE.assign_mode(), sid)
    bridge.STORE.set_triage(key, pool)
    h = SimpleNamespace(_json=lambda code, body: (code, body), _archive=lambda *a: None, _bind_board=lambda *a: None)
    h._ensemble_pool = lambda *a, **k: bridge.Handler._ensemble_pool(h, *a, **k)
    h._ensemble_questions = lambda *a, **k: bridge.Handler._ensemble_questions(h, *a, **k)
    h._index_questions = lambda *a, **k: bridge.Handler._index_questions(h, *a, **k)
    body = {"session_id": sid, "qa_run_id": "rAAAA1111", "talk_id": "tAAAA1111"}
    code, out = bridge.Handler._ensemble_fast(h, body, {"graph": graph.to_dict()}, sd.to_dict(), None, "10", "questions:k")
    assert code == 200 and len(out["questions"]) >= 2
    for q in out["questions"][:2]:
        checks = (q.get("basis") or {}).get("checks") or []
        assert "ensemble" in checks and any(c.startswith("pattern:P") for c in checks)
        assert "live" not in checks and not any(c.startswith("signal:") for c in checks)
    assert bridge.STORE.get_triage(bridge._RUN_TALK + bridge.run_key(sid, "rAAAA1111")) == "tAAAA1111"


def test_음성_후보_질문_앞머리의_장_번호는_뗀다():
    assert FE._SLIDE_REF_RE.sub("", "6장에서 회전율 구간별 수익률이 왜 줄어드나요?") == "회전율 구간별 수익률이 왜 줄어드나요?"
    assert FE._SLIDE_REF_RE.sub("", "발표 3장에서는 결론을 왜 그렇게 냈나요?") == "결론을 왜 그렇게 냈나요?"
    assert FE._SLIDE_REF_RE.sub("", "결론은 왜 그렇게 나왔나요?") == "결론은 왜 그렇게 나왔나요?"


def test_고르기_판에_장_표시와_아직_안_물은_부분(monkeypatch):
    graph, sd, pool, llms = _pool()
    opts = [{"uid": "a", "question": "가속 조건 한계가 결론을 어디까지 흔드나요?", "slide_no": 4},
            {"uid": "b", "question": "설계가 결론을 받치나요?", "slide_no": 2}]
    monkeypatch.setenv("QA_PICK_SPREAD", "1")
    FE.ens_pick("solar4", llms["solar4"], opts, [{"question": "q", "slide_no": 2, "verdict": "good"}], [])
    user = [u for u in llms["solar4"].users if "qa-ensemble-pick" in u][-1]
    assert "[발표 4장 · 아직 안 물은 부분]" in user and "[발표 2장]" in user
    monkeypatch.setenv("QA_PICK_SPREAD", "0")
    FE.ens_pick("solar4", llms["solar4"], opts, [], [])
    assert "발표 4장" not in [u for u in llms["solar4"].users if "qa-ensemble-pick" in u][-1]


def test_3번_음성_질문의_외운_것_꺼내기는_버리고_수를_맥락으로_쓴_핵심_질문은_남긴다():
    bad = ["농도만 다르게 하고 나머지 사육 조건을 모두 고정했다고 했는데, 구체적으로 어떤 조건들을 동일하게 유지했는지 말해 주세요.",
           "보정 후에도 Q4의 위험이 Q1보다 낮다는 근거는 표의 어떤 수치에서 확인되나요?",
           "충전 속도 2C에서 온도가 25°C에서 45°C로 바뀌면 용량 유지율이 어떻게 달라지나요?",
           "그 결론을 뒷받침하는 핵심 근거로 재주문율 변화와 별점 차이를 함께 말해 줄 수 있을까요?"]
    good = ["별점이 4.5~5.0 구간에 82% 몰려 있다는 분포만으로 '4.7은 수집 방식의 결과'라고 말할 수 없는 이유는 무엇인가요?",
            "충전 속도를 0.5C, 1C, 2C 세 수준으로 나눈 이유는 무엇인가요?",
            "살아 있는 개체의 번식 자체가 줄었다는 주장을 뒷받침하려면 사망률과 번식력을 어떻게 분리해야 하나요?"]
    assert all(FE.recall_ask(q) for q in bad)
    assert not any(FE.recall_ask(q) for q in good)
