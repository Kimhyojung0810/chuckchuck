"""
브리지 질문 미리 만들기 (2026-09-29) — 같은 입력의 질문은 한 번만 만들고, 만드는 중이면 기다려 받는다.

프론트가 분석이 끝나는 순간 /api/v1/questions 를 prefetch=true 로 먼저 보내 두고, 사용자가 시간을 고르면
같은 요청을 다시 보낸다. 두 번째는 LLM 을 부르지 않아야 한다 — 그게 이 기능의 전부다.
"""
from __future__ import annotations

import io
import json
import threading
from email.message import Message

import pytest

import chuckchuck
import demo.bridge as bridge
from chuckchuck.contracts import QaTriage, QuestionDoc
from demo.session_store import SessionStore


class FakeHandler(bridge.Handler):
    def __init__(self) -> None:  # noqa: D107 — 소켓 없이 응답만 잡는다
        self.path = "/api/v1/questions"
        self.headers = Message()
        self.client_address = ("127.0.0.1", 1)
        self.sent: list[tuple[int, dict]] = []
        self.wfile = io.BytesIO()

    def _json(self, code: int, payload: dict):
        self.sent.append((code, payload))


GRAPH = {"file_name": "deck.pdf", "total_slides": 1, "nodes": []}


def body(**kw) -> bytes:
    return json.dumps({"graph": GRAPH, "context": {"situation": "수업"}, "track": "10", **kw}).encode()


@pytest.fixture
def builds(monkeypatch):
    calls: list[str] = []
    gate = {"ev": None}

    def fake_build(graph, triage, *, track, **_):
        calls.append(track)
        if gate["ev"] is not None:
            gate["ev"].wait(5)
        return QuestionDoc(file_name="deck.pdf", track=track, model=f"fake-{len(calls)}")

    monkeypatch.setattr(chuckchuck, "build_questions", fake_build)
    monkeypatch.setattr(chuckchuck, "triage_questions", lambda *a, **k: QaTriage(file_name="deck.pdf"))
    monkeypatch.setattr(bridge, "STORE", SessionStore())
    monkeypatch.setattr(bridge.Handler, "_papers_for", lambda self, *a: None)
    monkeypatch.setattr(bridge.Handler, "_memory_for", lambda self, *a: None)
    monkeypatch.setattr(bridge.Handler, "_archive", staticmethod(lambda *a: None))
    return calls, gate


def ask(raw: bytes) -> tuple[int, dict]:
    h = FakeHandler()
    h._handle_questions(raw)
    return h.sent[-1]


def test_미리_만든_질문을_다시_만들지_않고_돌려준다(builds):
    calls, _ = builds
    code1, first = ask(body(prefetch=True))
    code2, second = ask(body())
    assert code1 == code2 == 200 and calls == ["10"] and second == first


def test_트랙이_다르거나_fresh_면_새로_만든다(builds):
    calls, _ = builds
    ask(body())
    ask(body(track="5"))
    ask(body(fresh=True))
    assert calls == ["10", "5", "10"]


def test_만드는_중이면_기다렸다가_그_결과를_쓴다(builds):
    calls, gate = builds
    gate["ev"] = threading.Event()
    results: list = []
    t = threading.Thread(target=lambda: results.append(ask(body(prefetch=True))))
    t.start()
    while not calls:            # 미리 만들기가 LLM 자리에 들어갈 때까지
        pass
    t2 = threading.Thread(target=lambda: results.append(ask(body())))
    t2.start()
    gate["ev"].set()
    t.join(5)
    t2.join(5)
    assert calls == ["10"] and len(results) == 2 and results[0][1] == results[1][1]
    assert not bridge._QUESTIONS_INFLIGHT


def test_문헌_검색_결과가_달라도_같은_요청으로_알아본다(builds, monkeypatch):
    # 09-29 실측: 미리 만들기와 실제 요청이 동시에 문헌을 찾아 4편·3편으로 갈렸고, 문헌을 지문에 넣었던 탓에 둘 다 LLM 을 불렀다
    from chuckchuck.contracts import PaperDoc, PaperRef
    n = {"i": 0}

    def papers(self, *a):
        n["i"] += 1
        return PaperDoc(file_name="deck.pdf", refs=[PaperRef(id=f"s{k}", kind="scholar", title="t", authors=["A"], year=2020)
                                                    for k in range(n["i"])])
    monkeypatch.setattr(bridge.Handler, "_papers_for", papers)
    calls, _ = builds
    ask(body(prefetch=True))
    ask(body())
    assert calls == ["10"]
