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
        json_mode: bool = False,
    ) -> str:
        """
        텍스트 completion. JSON 응답을 기대하는 호출자가 파싱한다.

        json_mode=True 면 제공자에게 JSON 객체만 내라고 **구조적으로** 요구한다.
        프롬프트로만 부탁하면 모델이 문자열 안에 이스케이프 안 된 따옴표를 넣거나
        말머리를 붙여 파싱이 깨진다 — 그 실패가 사용자에게는 422 로 보였다.
        지원하지 않는 제공자는 무시해도 된다 (프롬프트 지시가 폴백이다).
        """
