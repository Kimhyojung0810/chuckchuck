"""
이 폴더(chuckchuck)의 출입구 파일입니다.
밖에서 `from chuckchuck import parse_document`처럼 쓸 수 있게
주요 함수·타입을 모아 내보내 줍니다.
"""

from .config import settings
from .contracts import (
    ChuckchuckError,
    ConceptDoc,
    Context,
    ParseError,
    SlideDoc,
    SlideMark,
    STTError,
    Transcript,
    WordTimestampUnsupported,
)
from .f01_parse import parse_document, sparse_slide_numbers
from .f05_stt import speech_for_slide, split_by_slide, transcribe
from .f06_concepts import extract_concepts

__all__ = [
    "ChuckchuckError",
    "ConceptDoc",
    "Context",
    "ParseError",
    "STTError",
    "SlideDoc",
    "SlideMark",
    "Transcript",
    "WordTimestampUnsupported",
    "extract_concepts",
    "parse_document",
    "settings",
    "sparse_slide_numbers",
    "speech_for_slide",
    "split_by_slide",
    "transcribe",
]

__version__ = "0.1.1"
