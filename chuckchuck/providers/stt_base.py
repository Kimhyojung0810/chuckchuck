"""
STT(음성→글자) provider의 공통 인터페이스입니다.
어떤 회사 STT를 쓰든 같은 방식으로 부르게 하는 설계도입니다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..contracts import Word, WordTimestampUnsupported


class STTProvider(ABC):
    name: str = "unknown"
    SUPPORTS_WORD_TIMESTAMPS: bool = False
    VERIFIED: str = "미확인"

    @abstractmethod
    def transcribe(self, audio_path: str | Path) -> tuple[str, list[Word]]:
        """오디오 → (전체 텍스트, 단어 목록)."""

    def check_capability(self) -> None:
        if not self.SUPPORTS_WORD_TIMESTAMPS:
            raise WordTimestampUnsupported(
                f"[{self.name}] 은 단어별 시각을 주지 않습니다.\n"
                f"이 제공자를 쓰면 F-17(말 속도) 기능을 만들 수 없습니다."
            )

    def describe(self) -> str:
        ts = "O" if self.SUPPORTS_WORD_TIMESTAMPS else "X"
        return f"{self.name:<20} 단어별시각 {ts}  ({self.VERIFIED})"
