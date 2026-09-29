"""
객석 수다는 세션 id + 재료 해시로 한 번만 만든다 (09-30 녹음 대화 감사 REC-19 — qa/report2).

예전엔 결과·리포트 화면을 열 때마다 네 모델(라운드 둘, 최대 8콜)을 다시 불렀다 — 감사 LLM 230콜 중 101콜이 객석, 그중 약 55콜이 이미
분석한 세션의 재렌더였다. 브리지가 단계 캐시(_stage_cache_*)에 둔다. 못 온 병아리가 있으면(LLM 실패) 캐시에 안 쓴다 — 방금 실패한 것만
잠깐(CHATTER_RETRY_AFTER_SEC) 결석 표시 그대로 돌려주고, 창이 지나면 다시 부른다.
"""

from __future__ import annotations

import io
import json
from email.message import Message

import pytest

import chuckchuck
import demo.bridge as bridge
from chuckchuck.contracts import AlignmentDoc, ChatterDoc, ChatterTurn, ConceptGraph, ConceptNode, FlowDiff

GUESSED = AlignmentDoc(file_name="deck.pptx", total_slides=3, model="scripted", basis="fallback")
MATCHED = AlignmentDoc(file_name="deck.pptx", total_slides=3, model="scripted")


class H(bridge.Handler):
    def __init__(self):  # noqa: D107 — 소켓 없이 핸들러 함수만 부른다
        self.headers, self.sent, self.wfile = Message(), [], io.BytesIO()

    def _json(self, code, payload):
        self.sent.append((code, payload))


@pytest.fixture()
def no_archive(monkeypatch):
    monkeypatch.setattr(bridge.Handler, "_archive", staticmethod(lambda *a: None))


GRAPH = ConceptGraph("deck.pptx", 3, nodes=[ConceptNode(id="booth", label="부스 매출", slide_nos=[2], importance="core")])


def _chatter_body(sid: str = "20260930T060000Z_aaaaaaaa", alignment: AlignmentDoc = MATCHED) -> bytes:
    return json.dumps({"session_id": sid, "graph": GRAPH.to_dict(), "alignment": alignment.to_dict(),
                       "flow": FlowDiff(file_name="deck.pptx").to_dict()}).encode()


@pytest.fixture()
def chatter_calls(tmp_path, monkeypatch, no_archive):
    """build_chatter 를 가짜로 — 부른 횟수를 센다. absent 를 바꿔 끼우면 실패한 병아리를 흉내 낸다."""
    calls: list[dict] = []
    state = {"absent": []}

    def fake(graph, alignment, flow, **_):
        calls.append(alignment)
        return ChatterDoc(file_name="deck.pptx", total_slides=3, absent=list(state["absent"]),
                          turns=[ChatterTurn(speaker="solar", text=f"{len(calls)}번째 수다")])

    monkeypatch.setattr(chuckchuck, "build_chatter", fake)
    monkeypatch.setattr(bridge, "_CHATTER_PARTIAL", {})
    monkeypatch.setattr(bridge, "STAGE_CACHE_ON", True)
    monkeypatch.setattr(bridge, "STAGE_CACHE_DIR", tmp_path / "stage")
    return calls, state


def test_chatter_is_built_once_per_session_and_inputs(chatter_calls):
    calls, _ = chatter_calls
    first, second = H(), H()
    first._handle_chatter(_chatter_body())
    second._handle_chatter(_chatter_body())
    assert len(calls) == 1 and first.sent[-1] == second.sent[-1]          # 결과·리포트를 다시 열어도 LLM 을 다시 안 부른다
    H()._handle_chatter(_chatter_body(sid="20260930T060000Z_bbbbbbbb"))
    assert len(calls) == 2                                                  # 다른 세션은 다른 키
    H()._handle_chatter(_chatter_body(alignment=GUESSED))
    assert len(calls) == 3                                                  # 재료가 바뀌면(다시 분석) 다른 키


def test_chatter_with_absent_speakers_is_not_cached(chatter_calls, monkeypatch):
    calls, state = chatter_calls
    monkeypatch.setattr(bridge, "CHATTER_RETRY_AFTER_SEC", 0)              # 잠깐 기억도 끄고 — 디스크 캐시만 본다
    state["absent"] = ["exaone"]                                            # LLM 이 죽어 대타 대사가 섰다
    H()._handle_chatter(_chatter_body())
    H()._handle_chatter(_chatter_body())
    assert len(calls) == 2                                                  # 실패를 성공처럼 굳히지 않는다
    state["absent"] = []
    H()._handle_chatter(_chatter_body())
    H()._handle_chatter(_chatter_body())
    assert len(calls) == 3


def test_chatter_right_after_a_partial_build_reuses_it_with_the_absence_shown(chatter_calls, monkeypatch):
    """방금 45초를 태우고 죽은 모델을 곧바로 다시 부르지 않는다 — 결석 표시 그대로 잠깐 돌려주고, 창이 지나면 다시 부른다."""
    calls, state = chatter_calls
    monkeypatch.setattr(bridge, "CHATTER_RETRY_AFTER_SEC", 90)
    state["absent"] = ["midm", "exaone"]
    first, again = H(), H()
    first._handle_chatter(_chatter_body())
    again._handle_chatter(_chatter_body())
    assert len(calls) == 1 and again.sent[-1][1]["absent"] == ["midm", "exaone"]   # 결석은 결석으로 보인다
    assert list((bridge.STAGE_CACHE_DIR).glob("chatter-*.json")) == []            # 디스크 캐시에는 안 남는다
    monkeypatch.setattr(bridge, "CHATTER_RETRY_AFTER_SEC", 0)               # 창이 지났다
    state["absent"] = []
    H()._handle_chatter(_chatter_body())
    assert len(calls) == 2 and bridge._stage_cache_get("chatter", bridge._chatter_key(
        "20260930T060000Z_aaaaaaaa", json.loads(_chatter_body()))) is not None


def test_chatter_stage_key_follows_its_code():
    assert "chuckchuck.f12_chatter" in bridge.STAGE_MODULES["chatter"]
    assert chuckchuck.build_chatter.__module__ in bridge.STAGE_ENTRY_MODULES["chatter"]
