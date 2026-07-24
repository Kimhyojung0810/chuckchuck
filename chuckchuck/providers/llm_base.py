"""
LLM(글 읽고 답하기) provider의 공통 인터페이스입니다.
F-06 개념 추출이 이 인터페이스로 모델을 호출합니다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        """텍스트 completion. JSON 응답을 기대하는 호출자가 파싱한다."""
