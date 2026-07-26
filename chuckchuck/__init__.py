"""
이 폴더(chuckchuck)의 출입구 파일입니다.
밖에서 `from chuckchuck import parse_document`처럼 쓸 수 있게
주요 함수·타입을 모아 내보내 줍니다.
"""

from .config import settings
from .contracts import (
    ChuckchuckError,
    ConceptDoc,
    ConceptNode,
    ConceptTree,
    Context,
    ParseError,
    Section,
    SlideDoc,
    SlideMark,
    STTError,
    Transcript,
    TreeError,
    WordTimestampUnsupported,
)
from .f01_parse import parse_document, sparse_slide_numbers
from .f05_stt import speech_for_slide, split_by_slide, transcribe
from .f06_concepts import extract_concepts
from .f07_tree import build_tree

__all__ = [
    "ChuckchuckError",
    "ConceptDoc",
    "ConceptNode",
    "ConceptTree",
    "Context",
    "ParseError",
    "STTError",
    "Section",
    "SlideDoc",
    "SlideMark",
    "Transcript",
    "TreeError",
    "WordTimestampUnsupported",
    "build_tree",
    "extract_concepts",
    "parse_document",
    "settings",
    "sparse_slide_numbers",
    "speech_for_slide",
    "split_by_slide",
    "transcribe",
]

__version__ = "0.1.2"
