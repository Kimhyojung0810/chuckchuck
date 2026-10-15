"""일마다 다른 모델에 맡기기 (providers/llm_route) — 마감·JSON 실패면 서비스 기본 체인으로 한 번 (10-16)."""
from __future__ import annotations

import threading

import pytest

import pipeline.providers.llm_route as route
from pipeline.contracts import ConceptError
from pipeline.providers.llm_base import LLMProvider


class _Fake(LLMProvider):
    def __init__(self, name, out='{"ok": 1}', delay=0.0, exc=None):
        self.name, self.out, self.delay, self.exc, self.calls = name, out, delay, exc, 0

    def complete(self, **kw):
        self.calls += 1
        if self.delay:
            threading.Event().wait(self.delay)
        if self.exc:
            raise self.exc
        return self.out


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("QA_TRIAGE_MODEL", "QA_PHRASE_MODEL", "QA_CHECK_MODEL", "QA_PHRASE_DEADLINE_SEC",
              "MOCK_EXTERNAL_APIS", "REASONING_FALLBACK"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("REASONING_BACKEND", "solar")


def test_primary_answer_is_used_and_named():
    a, b = _Fake("exaone"), _Fake("solar")
    llm = route.RoutedLLM(a, b, deadline_sec=5, stage="phrase")
    assert llm.complete(system="s", user="u", json_mode=True) == '{"ok": 1}'
    assert llm.name == "exaone" and b.calls == 0 and llm.fallbacks == 0


def test_deadline_hands_over_to_secondary():
    a, b = _Fake("ax", delay=0.5), _Fake("solar", out='{"from": "solar"}')
    llm = route.RoutedLLM(a, b, deadline_sec=0.05, stage="phrase")
    assert llm.complete(system="s", user="u", json_mode=True) == '{"from": "solar"}'
    assert llm.name == "solar" and llm.fallbacks == 1 and "마감" in llm.last_reason


def test_non_json_in_json_mode_hands_over():
    a, b = _Fake("exaone", out="Okay, let's tackle this."), _Fake("solar")
    llm = route.RoutedLLM(a, b, deadline_sec=5)
    assert llm.complete(system="s", user="u", json_mode=True) == '{"ok": 1}'
    assert llm.name == "solar" and llm.last_reason == "JSON 아님"


def test_plain_text_is_fine_when_not_json_mode():
    a, b = _Fake("exaone", out="그냥 글"), _Fake("solar")
    llm = route.RoutedLLM(a, b, deadline_sec=5)
    assert llm.complete(system="s", user="u") == "그냥 글" and b.calls == 0


def test_primary_error_hands_over_and_secondary_error_propagates():
    a, b = _Fake("ax", exc=ConceptError("[ax] 500")), _Fake("solar", exc=ConceptError("[solar] 503"))
    llm = route.RoutedLLM(a, b, deadline_sec=5)
    with pytest.raises(ConceptError, match="solar"):
        llm.complete(system="s", user="u")
    assert a.calls == 1 and b.calls == 1


def test_name_recovers_when_primary_comes_back():
    a, b = _Fake("exaone", out=""), _Fake("solar")
    llm = route.RoutedLLM(a, b, deadline_sec=5)
    llm.complete(system="s", user="u")
    assert llm.name == "solar"
    a.out = '{"ok": 2}'
    assert llm.complete(system="s", user="u", json_mode=True) == '{"ok": 2}' and llm.name == "exaone"


def _registry(monkeypatch, made: list):
    def factory(name):
        class _P(_Fake):
            def __init__(self, *a, **k):
                super().__init__(name)
                self.timeout = 180
                made.append(self)
        return _P
    monkeypatch.setattr(route, "REGISTRY", {n: factory(n) for n in ("solar", "ax", "exaone", "midm", "mock")})
    monkeypatch.setattr(route, "get_llm", lambda *a, **k: _Fake("solar"))


def test_stage_env_builds_routed_with_deadline_and_short_http_timeout(monkeypatch):
    made: list = []
    _registry(monkeypatch, made)
    monkeypatch.setenv("QA_PHRASE_MODEL", "exaone")
    monkeypatch.setenv("QA_PHRASE_DEADLINE_SEC", "12")
    llm = route.get_stage_llm("phrase")
    assert isinstance(llm, route.RoutedLLM) and llm.primary.name == "exaone" and llm.secondary.name == "solar"
    assert llm.deadline_sec == 12 and made[0].timeout == 12 + route._HTTP_SLACK_SEC


def test_unset_or_default_stage_uses_service_chain(monkeypatch):
    _registry(monkeypatch, [])
    monkeypatch.setattr(route, "DEFAULT_STAGE_MODELS", {"triage": "", "phrase": "", "check": ""})
    assert not isinstance(route.get_stage_llm("triage"), route.RoutedLLM)
    monkeypatch.setenv("QA_PHRASE_MODEL", "default")
    assert not isinstance(route.get_stage_llm("phrase"), route.RoutedLLM)


def test_explicit_empty_env_overrides_code_default(monkeypatch):
    _registry(monkeypatch, [])
    monkeypatch.setattr(route, "DEFAULT_STAGE_MODELS", {"triage": "", "phrase": "exaone", "check": ""})
    assert isinstance(route.get_stage_llm("phrase"), route.RoutedLLM)
    monkeypatch.setenv("QA_PHRASE_MODEL", "")
    assert not isinstance(route.get_stage_llm("phrase"), route.RoutedLLM)


def test_mock_mode_never_routes_to_real_endpoints(monkeypatch):
    _registry(monkeypatch, [])
    monkeypatch.setenv("QA_PHRASE_MODEL", "exaone")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    assert not isinstance(route.get_stage_llm("phrase"), route.RoutedLLM)
    monkeypatch.delenv("MOCK_EXTERNAL_APIS")
    monkeypatch.setenv("REASONING_BACKEND", "mock")
    assert not isinstance(route.get_stage_llm("phrase"), route.RoutedLLM)
    assert route.route_identity() == "mock"


def test_missing_key_falls_back_to_chain_quietly(monkeypatch):
    monkeypatch.setattr(route, "get_llm", lambda *a, **k: _Fake("solar"))
    monkeypatch.setenv("QA_PHRASE_MODEL", "exaone")
    monkeypatch.delenv("EXAONE_API_KEY", raising=False)     # 실제 ExaoneLLM 이 키 없음으로 ConceptError 를 낸다
    llm = route.get_stage_llm("phrase")
    assert not isinstance(llm, route.RoutedLLM) and llm.name == "solar"


def test_unknown_model_name_falls_back(monkeypatch):
    _registry(monkeypatch, [])
    monkeypatch.setenv("QA_TRIAGE_MODEL", "gpt")
    assert not isinstance(route.get_stage_llm("triage"), route.RoutedLLM)


def test_route_identity_changes_with_env(monkeypatch):
    before = route.route_identity()
    monkeypatch.setenv("QA_PHRASE_MODEL", "ax")
    assert route.route_identity() != before and "phrase=ax" in route.route_identity()


def test_f08_explicit_llm_bypasses_routing(monkeypatch):
    import pipeline.f08_questions as f08

    monkeypatch.setenv("QA_PHRASE_MODEL", "exaone")
    fake = _Fake("mine")
    assert f08._stage_engine("phrase", fake, None) is fake


def test_f08_default_path_uses_stage_router(monkeypatch):
    import pipeline.f08_questions as f08

    seen = []
    monkeypatch.setattr(f08, "get_stage_llm", lambda stage: seen.append(stage) or _Fake("routed"))
    assert f08._stage_engine("triage", None, None).name == "routed" and seen == ["triage"]


def test_bridge_question_key_changes_when_stage_model_changes(monkeypatch):
    import server.bridge as bridge

    monkeypatch.setenv("REASONING_FALLBACK", "ax")
    before = bridge._qa_llm_identity(None)
    monkeypatch.setenv("QA_PHRASE_MODEL", "ax")
    assert bridge._qa_llm_identity(None) != before
    assert bridge._qa_llm_identity("mock") == "mock"   # 개발 경로·mock 은 본문이 고른 이름 그대로


def test_default_phrase_model_is_the_benched_winner(monkeypatch):
    # 10-16 벤치: 질문 문장 = EXAONE (1차 심사·논문 대조는 서비스 기본 체인). 바꾸면 MODEL_LEDGER §3 도 고친다.
    assert route.stage_model("phrase") == "exaone"
    assert route.stage_model("triage") == "" and route.stage_model("check") == ""
    assert route.stage_deadline("phrase") == 20.0
