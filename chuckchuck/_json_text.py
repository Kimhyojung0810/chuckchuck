"""
LLM 이 뱉은 느슨한 JSON 문자열을 복구해 dict 로 만드는 공용 헬퍼입니다.
기능 모듈(fXX_*)이 아니라 유틸이라, 어느 모듈에서 import 해도 정책 위반이 아닙니다.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger("chuckchuck.json")

_FENCE_OPEN = re.compile(r"^```(?:json)?\s*", flags=re.I)
_FENCE_CLOSE = re.compile(r"\s*```$")
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _strip_trailing_commas(text: str) -> str:
    """문자열 밖의 `, }` `, ]` 만 지운다. 정규식은 문자열 안의 ", ]" 까지 지워 값을 바꿨다 (2026-09-13 감사)."""
    out, in_str, esc, i = [], False, False, 0
    while i < len(text):
        ch = text[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
            out.append(ch)
        elif ch == ",":
            j = i + 1
            while j < len(text) and text[j] in " \t\r\n":
                j += 1
            if j < len(text) and text[j] in "}]":
                i = j
                continue
            out.append(ch)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


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

    text = _strip_trailing_commas(text)

    # 응답이 잘려 괄호가 안 닫힌 경우: 마지막으로 완전한 객체까지만 남기고 닫는다
    if text.count("{") > text.count("}"):
        last_complete = text.rfind("}")
        if last_complete > 0:
            text = text[: last_complete + 1]

    if text.count("[") > text.count("]"):
        text += "]" * (text.count("[") - text.count("]"))
    if text.count("{") > text.count("}"):
        text += "}" * (text.count("{") - text.count("}"))

    return _strip_trailing_commas(text)


def extract_json_object(text: str) -> dict[str, Any]:
    """
    LLM 응답 문자열에서 JSON 객체 하나를 뽑는다.

    원문 → 복구본 → 가장 바깥 {...} 순으로 시도한다.
    끝내 실패하면 ValueError. 도메인 예외(GraphError 등)로는 호출자가 감싼다.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("빈 응답입니다.")

    repaired = repair_json_text(text)
    # 펜스만 벗긴 후보를 따로 둔다 — 괄호 세기(repair)는 문자열 안의 '{' 를 괄호로 오해할 수 있다 (2026-09-13 감사)
    unfenced = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", text)).strip()
    candidates = [text]
    for c in (unfenced, _strip_trailing_commas(unfenced), repaired):
        if c and c not in candidates:
            candidates.append(c)
    outermost = re.search(r"\{.*\}", repaired, flags=re.S)
    if outermost:
        candidates.append(outermost.group(0))

    last_err: Exception | None = None
    for cand in candidates:
        try:
            # strict=False: 인용문 안의 개행·탭을 허용한다. A.X 가 json_mode 를 무시하고 evidence 를 여러 줄로 내면
            # 기본값에선 "Invalid control character" 로 통째로 실패했다 — 09-12 판정 JSON 실패의 유력한 원인.
            data = json.loads(cand, strict=False)
        except json.JSONDecodeError as e:
            last_err = e
            continue
        if isinstance(data, dict):
            return data
        last_err = ValueError(f"JSON 최상위가 객체가 아닙니다: {type(data).__name__}")
    # 마지막 시도: 앞뒤에 산문이 붙은 응답 — 첫 '{' 부터 raw_decode. 단 앞에 '[' 가 있거나(최상위 배열)
    # 뒤에 또 다른 객체·배열이 오면(객체 둘) 어느 것이 답인지 모르므로 받지 않는다.
    start = unfenced.find("{")
    if start >= 0 and "[" not in unfenced[:start]:
        try:
            data, end = json.JSONDecoder(strict=False).raw_decode(unfenced[start:])
            rest = unfenced[start + end:]
            if isinstance(data, dict) and "{" not in rest and "[" not in rest:
                return data
        except json.JSONDecodeError as e:
            last_err = e

    # 원문은 **서버 로그로** 남긴다. 예외 메시지는 사용자 화면까지 흘러가므로
    # 앞부분만 담는다 — 이 실패를 화면 문구만 보고 역추적하느라 고생한 적이 있다.
    log.warning("JSON 파싱 실패 (%s). 원문 %d자:\n%s", last_err, len(text), text)
    raise ValueError(f"JSON 파싱 실패: {last_err}. preview={text[:200]!r}")
