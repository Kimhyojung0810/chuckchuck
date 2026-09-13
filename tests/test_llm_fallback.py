"""주 LLM 이 넘어지면 예비로 한 번 넘긴다 — 누가 답했는지는 name 에 남는다 (2026-09-13 A/B 뒤)."""
from __future__ import annotations

import pytest

import chuckchuck.providers.llm_impl as impl
from chuckchuck.contracts import ConceptError
from chuckchuck.providers.llm_base import LLMProvider


class _Fake(LLMProvider):
    def __init__(self, name, outcomes):
        self.name, self.outcomes, self.calls = name, list(outcomes), 0

    def complete(self, **kw):
        self.calls += 1
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def test_primary_ok_never_touches_secondary():
    a, b = _Fake("solar", ["답"]), _Fake("ax", ["예비"])
    llm = impl.FallbackLLM(a, b)
    assert llm.complete(system="s", user="u") == "답"
    assert b.calls == 0 and llm.name == "solar" and llm.fallbacks == 0


def test_connection_error_falls_back_once_and_names_who_answered():
    a, b = _Fake("solar", [ConceptError("[solar] LLM 연결 실패 (2회)")]), _Fake("ax", ["예비"])
    llm = impl.FallbackLLM(a, b)
    assert llm.complete(system="s", user="u") == "예비"
    assert llm.name == "ax" and llm.fallbacks == 1


def test_empty_answer_is_a_failure_too():
    a, b = _Fake("solar", ["   "]), _Fake("ax", ["예비"])
    llm = impl.FallbackLLM(a, b)
    assert llm.complete(system="s", user="u") == "예비"
    assert llm.name == "ax"


def test_secondary_failure_propagates_no_third_try():
    a = _Fake("solar", [ConceptError("x")])
    b = _Fake("ax", [ConceptError("[ax] LLM 오류 500")])
    llm = impl.FallbackLLM(a, b)
    with pytest.raises(ConceptError, match="ax"):
        llm.complete(system="s", user="u")
    assert a.calls == 1 and b.calls == 1


def test_name_recovers_after_primary_comes_back():
    a, b = _Fake("solar", [ConceptError("x"), "복귀"]), _Fake("ax", ["예비"])
    llm = impl.FallbackLLM(a, b)
    llm.complete(system="s", user="u")
    assert llm.name == "ax"
    assert llm.complete(system="s", user="u") == "복귀"
    assert llm.name == "solar"


def test_same_provider_twice_is_rejected():
    with pytest.raises(ConceptError, match="같은"):
        impl.FallbackLLM(_Fake("solar", []), _Fake("solar", []))


def _keys(monkeypatch):
    for k in ("UPSTAGE_API_KEY", "AX_API_KEY"):
        monkeypatch.setenv(k, "k")


def test_get_llm_plus_syntax(monkeypatch):
    _keys(monkeypatch)
    llm = impl.get_llm("solar+ax")
    assert isinstance(llm, impl.FallbackLLM)
    assert llm.primary.name == "solar" and llm.secondary.name == "ax"


def test_get_llm_default_path_reads_fallback_env(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setenv("REASONING_BACKEND", "solar")
    monkeypatch.setenv("REASONING_FALLBACK", "ax")
    assert isinstance(impl.get_llm(), impl.FallbackLLM)


def test_explicit_name_ignores_fallback_env(monkeypatch):
    """벤치 --llm ax 처럼 이름을 박은 호출은 섞이면 안 된다 — 측정이 오염된다."""
    _keys(monkeypatch)
    monkeypatch.setenv("REASONING_FALLBACK", "ax")
    assert not isinstance(impl.get_llm("solar"), impl.FallbackLLM)


def test_fallback_same_as_backend_is_ignored(monkeypatch):
    _keys(monkeypatch)
    monkeypatch.setenv("REASONING_BACKEND", "solar")
    monkeypatch.setenv("REASONING_FALLBACK", "solar")
    assert not isinstance(impl.get_llm(), impl.FallbackLLM)


def test_mock_never_gets_a_fallback(monkeypatch):
    monkeypatch.setenv("REASONING_FALLBACK", "ax")
    assert isinstance(impl.get_llm("mock"), impl.MockLLM)


def test_unknown_secondary_is_an_error(monkeypatch):
    _keys(monkeypatch)
    with pytest.raises(ConceptError, match="모르는 LLM"):
        impl.get_llm("solar+gpt")
