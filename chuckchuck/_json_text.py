"""
LLM 이 뱉은 느슨한 JSON 문자열을 복구해 dict 로 만드는 공용 헬퍼입니다.
기능 모듈(fXX_*)이 아니라 유틸이라, 어느 모듈에서 import 해도 정책 위반이 아닙니다.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_OPEN = re.compile(r"^```(?:json)?\s*", flags=re.I)
_FENCE_CLOSE = re.compile(r"\s*```$")
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def repair_json_text(text: str) -> str:
    """
    코드펜스·trailing comma·잘린 괄호를 최대한 손봐서 파싱 가능한 문자열로.

    복구를 보장하지는 않는다. 실패해도 예외를 던지지 않고 최선의 결과를 준다.
    """
    text = (text or "").strip()
    text = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", text))

    start = text.find("{")
    if start > 0:
        text = text[start:]

    text = _TRAILING_COMMA.sub(r"\1", text)

    # 응답이 잘려 괄호가 안 닫힌 경우: 마지막으로 완전한 객체까지만 남기고 닫는다
    if text.count("{") > text.count("}"):
        last_complete = text.rfind("}")
        if last_complete > 0:
            text = text[: last_complete + 1]

    if text.count("[") > text.count("]"):
        text += "]" * (text.count("[") - text.count("]"))
    if text.count("{") > text.count("}"):
        text += "}" * (text.count("{") - text.count("}"))

    return _TRAILING_COMMA.sub(r"\1", text)


def extract_json_object(text: str) -> dict[str, Any]:
    """
    LLM 응답 문자열에서 JSON 객체 하나를 뽑는다.

    원문 → 복구본 → 가장 바깥 {...} 순으로 시도한다.
    끝내 실패하면 ValueError. 도메인 예외(TreeError 등)로는 호출자가 감싼다.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("빈 응답입니다.")

    repaired = repair_json_text(text)
    candidates = [text]
    if repaired != text:
        candidates.append(repaired)
    outermost = re.search(r"\{.*\}", repaired, flags=re.S)
    if outermost:
        candidates.append(outermost.group(0))

    last_err: Exception | None = None
    for cand in candidates:
        try:
            data = json.loads(cand)
        except json.JSONDecodeError as e:
            last_err = e
            continue
        if isinstance(data, dict):
            return data
        last_err = ValueError(f"JSON 최상위가 객체가 아닙니다: {type(data).__name__}")

    raise ValueError(f"JSON 파싱 실패: {last_err}. preview={text[:200]!r}")
