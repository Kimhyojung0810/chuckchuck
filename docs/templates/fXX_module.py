"""
새 기능 모듈(fXX_*.py)을 만들 때 복사하는 템플릿입니다.
"""

from __future__ import annotations

from typing import Any

# from .contracts import InType, OutType, MyError
# from .providers.my_impl import get_my  # 외부 AI 있을 때만


def do_thing(
    inp: Any,  # InType | dict
    *,
    provider: str | None = None,
) -> Any:  # OutType
    """
    입력(ours) → 출력(ours).

    - dict 로 오면 입구에서 from_dict
    - 다른 fXX_* 모듈을 import 하지 말 것
    - 벤더 raw 는 provider/어댑터 밖으로 새기지 말 것
    """
    # if isinstance(inp, dict):
    #     inp = InType.from_dict(inp)
    #
    # eng = get_my(provider)
    # raw_or_partial = eng.run(...)
    # return OutType(...)
    raise NotImplementedError("F-XX: contracts 확정 후 구현")
