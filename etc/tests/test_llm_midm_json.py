"""Mi:dm 공식 API 는 response_format 으로 json_schema 만 받는다 — json_object 를 보내면 400 7005 (2026-10-16 새 키 실측)."""
from __future__ import annotations

import pipeline.providers.llm_impl as impl


class _Res:
    status_code, text = 200, ""

    def json(self):
        return {"choices": [{"message": {"content": '{"answer": "서울"}'}, "finish_reason": "stop"}]}


def _sent(monkeypatch, llm, **kw):
    sent = []
    monkeypatch.setattr(impl.requests, "post", lambda url, headers=None, json=None, timeout=None: sent.append(json) or _Res())
    out = llm.complete(system="JSON 객체 하나로만 답한다.", user="수도", **kw)
    return out, sent[-1]


def test_midm_json_mode_sends_no_json_object_format(monkeypatch):
    out, payload = _sent(monkeypatch, impl.MidmLLM(api_key="k", endpoint_id="midm-pro-fp8-kaic"), json_mode=True)
    assert "response_format" not in payload
    assert "JSON 객체 하나로만" in payload["messages"][0]["content"]
    assert out == '{"answer": "서울"}'


def test_other_providers_keep_json_object_format(monkeypatch):
    llm = impl.OpenAICompatLLM(api_key="k", base_url="http://x", model="m", name="t")
    _, payload = _sent(monkeypatch, llm, json_mode=True)
    assert payload["response_format"] == {"type": "json_object"}


def test_midm_plain_mode_unchanged(monkeypatch):
    _, payload = _sent(monkeypatch, impl.MidmLLM(api_key="k", endpoint_id="e"), json_mode=False)
    assert "response_format" not in payload
    assert payload["messages"][0]["content"] == "JSON 객체 하나로만 답한다."
