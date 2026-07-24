"""
새 외부 AI provider를 만들 때 복사하는 템플릿입니다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MyProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    def run(self, payload: Any) -> Any:
        """벤더 호출 → ours 조각(또는 중간 구조). raw dict를 호출자에게 주지 말 것."""


class MockMyProvider(MyProvider):
    name = "mock"

    def run(self, payload: Any) -> Any:
        return {"ok": True, "echo": payload}


def get_my(name: str | None = None) -> MyProvider:
    key = (name or "mock").lower()
    if key == "mock":
        return MockMyProvider()
    raise ValueError(f"unknown provider: {key}")
