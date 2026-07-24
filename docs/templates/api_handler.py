"""
새 모듈용 HTTP API 핸들러 템플릿(복사해서 쓰는 뼈대)입니다.
"""

from __future__ import annotations

import json
from typing import Any, Callable


def handle_action(raw: bytes, *, run: Callable[..., Any], mock: bool = False) -> tuple[int, dict]:
    """
    브리지/서버에서 한 엔드포인트당 이 흐름을 그대로 쓴다.

    1) JSON 파싱
    2) 입력 ours from_dict
    3) 모듈 함수 호출 (mock 이면 provider/llm="mock")
    4) out.to_dict() 반환
    """
    try:
        body = json.loads(raw or b"{}")
        # inp = InType.from_dict(body["in_field"])
        # provider = "mock" if mock else body.get("provider")
        # out = run(inp, provider=provider)
        # return 200, out.to_dict()
        _ = (body, run, mock)
        return 501, {"error": "NotImplemented", "message": "F-XX handler stub"}
    except KeyError as e:
        return 400, {"error": "KeyError", "message": f"missing field: {e}"}
    except Exception as e:  # noqa: BLE001 — 경계에서만 포장
        return 500, {"error": type(e).__name__, "message": str(e)}


# 라우팅 예 (bridge 스타일):
#
# if parsed.path == "/api/v1/my-action":
#     code, payload = handle_action(raw, run=do_thing, mock=_mock())
#     return self._json(code, payload)
