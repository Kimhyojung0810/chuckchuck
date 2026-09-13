"""OpenAI 호환 LLM 클라이언트 — 일시 오류는 한 번만 다시 부른다 (2026-09-12 A.X 타임아웃·500 실측)."""
from __future__ import annotations

import pytest
import requests

import chuckchuck.providers.llm_impl as impl
from chuckchuck.contracts import ConceptError


class _Res:
    def __init__(self, status=200, content="응답"):
        self.status_code, self.text = status, "err"
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(impl.time, "sleep", lambda s: None)
    return impl.OpenAICompatLLM(api_key="k", base_url="http://x", model="m", name="t")


def _post_seq(monkeypatch, *outcomes):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        out = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(impl.requests, "post", fake_post)
    return calls


def test_timeout_then_ok_is_one_retry(client, monkeypatch):
    calls = _post_seq(monkeypatch, requests.Timeout("read timed out"), _Res(content="ok"))
    assert client.complete(system="s", user="u") == "ok"
    assert len(calls) == 2


def test_500_then_ok_is_one_retry(client, monkeypatch):
    calls = _post_seq(monkeypatch, _Res(status=503), _Res(content="ok"))
    assert client.complete(system="s", user="u") == "ok"
    assert len(calls) == 2


def test_two_timeouts_raise_once_not_forever(client, monkeypatch):
    calls = _post_seq(monkeypatch, requests.Timeout("1"), requests.Timeout("2"))
    with pytest.raises(ConceptError, match="2회"):
        client.complete(system="s", user="u")
    assert len(calls) == 2


def test_400_is_not_retried(client, monkeypatch):
    calls = _post_seq(monkeypatch, _Res(status=400))
    with pytest.raises(ConceptError, match="400"):
        client.complete(system="s", user="u")
    assert len(calls) == 1
