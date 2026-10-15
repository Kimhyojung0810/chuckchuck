"""추론 모델(엑사원)의 사고 과정을 답으로 넘기지 않는다 — 2026-10-16 Friendli 실측 뒤."""
from __future__ import annotations

import json

import pytest

import pipeline.providers.llm_impl as impl
from pipeline.contracts import ConceptError


class _Res:
    def __init__(self, message: dict, finish: str = "stop", usage: dict | None = None):
        self.status_code, self.text = 200, ""
        self._body = {"choices": [{"message": message, "finish_reason": finish}], "usage": usage or {}}

    def json(self):
        return self._body


def _client(monkeypatch, res, cls=impl.OpenAICompatLLM, **kw):
    sent = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append(json)
        return res

    monkeypatch.setattr(impl.requests, "post", fake_post)
    if cls is impl.OpenAICompatLLM:
        return impl.OpenAICompatLLM(api_key="k", base_url="http://x", model="m", name="t", **kw), sent
    return cls(api_key="k", endpoint_id="ep", **kw), sent


def test_strip_thinking_drops_tag_blocks():
    assert impl.strip_thinking('<think>Okay, let me…</think>\n{"a": 1}') == '{"a": 1}'
    assert impl.strip_thinking('<thought>음…</thought>{"a": 1}') == '{"a": 1}'


def test_strip_thinking_keeps_tail_after_lone_close_and_drops_unclosed_open():
    assert impl.strip_thinking('reasoning here</think>{"a": 1}') == '{"a": 1}'
    assert impl.strip_thinking("<think>cut off mid thought") == ""


def test_last_json_object_takes_outer_last_object_not_inner():
    text = 'draft {"a": 1} then final {"q": {"inner": 2}, "n": 3} done'
    assert json.loads(impl.last_json_object(text)) == {"q": {"inner": 2}, "n": 3}
    assert impl.last_json_object("no json here") == ""


def test_reasoning_only_truncated_raises_instead_of_returning_thoughts(monkeypatch):
    res = _Res({"content": "", "reasoning_content": "Okay, let's tackle this. The user wants"}, finish="length")
    llm, _ = _client(monkeypatch, res)
    with pytest.raises(ConceptError, match="사고 과정만"):
        llm.complete(system="s", user="u", json_mode=True)


def test_reasoning_only_with_json_answer_returns_json(monkeypatch):
    res = _Res({"content": None, "reasoning": 'Let me think. Answer: {"answer": "서울"}'})
    llm, _ = _client(monkeypatch, res)
    assert json.loads(llm.complete(system="s", user="u json", json_mode=True)) == {"answer": "서울"}


def test_plain_reasoning_only_model_still_works_when_not_json(monkeypatch):
    # 사고 칸에만 답을 쓰는 모델 호환 — json_mode 가 아니고 잘리지 않았으면 예전처럼 그 글을 돌려준다
    res = _Res({"content": "", "reasoning_content": "서울이에요"})
    llm, _ = _client(monkeypatch, res)
    assert llm.complete(system="s", user="u") == "서울이에요"


def test_inline_think_tags_in_content_are_removed(monkeypatch):
    res = _Res({"content": '<think>hmm</think>{"answer": "서울"}'})
    llm, _ = _client(monkeypatch, res)
    assert llm.complete(system="s", user="u json", json_mode=True) == '{"answer": "서울"}'


def test_usage_and_finish_are_kept_for_bench(monkeypatch):
    res = _Res({"content": "ok"}, usage={"prompt_tokens": 5, "completion_tokens": 2})
    llm, _ = _client(monkeypatch, res)
    llm.complete(system="s", user="u")
    assert llm.last_usage == {"prompt_tokens": 5, "completion_tokens": 2} and llm.last_finish == "stop"


def test_exaone_sends_thinking_off_by_default(monkeypatch):
    monkeypatch.delenv("EXAONE_THINKING", raising=False)
    llm, sent = _client(monkeypatch, _Res({"content": "{}"}), cls=impl.ExaoneLLM)
    llm.complete(system="s", user="u json", json_mode=True)
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert llm.thinking is False


def test_exaone_thinking_can_be_turned_on_by_env(monkeypatch):
    monkeypatch.setenv("EXAONE_THINKING", "1")
    llm, sent = _client(monkeypatch, _Res({"content": "{}"}), cls=impl.ExaoneLLM)
    llm.complete(system="s", user="u")
    assert sent[0]["chat_template_kwargs"] == {"enable_thinking": True}


def test_other_providers_send_no_extra_fields(monkeypatch):
    llm, sent = _client(monkeypatch, _Res({"content": "ok"}))
    llm.complete(system="s", user="u")
    assert "chat_template_kwargs" not in sent[0]
