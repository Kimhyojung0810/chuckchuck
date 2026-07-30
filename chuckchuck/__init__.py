"""
이 폴더(chuckchuck)의 출입구 파일입니다.
밖에서 `from chuckchuck import parse_document`처럼 쓸 수 있게
주요 함수·타입을 모아 내보내 줍니다.
"""

from .config import settings
from .contracts import (
    AlignError,
    AlignmentDoc,
    AlignmentItem,
    AlignmentSummary,
    ChatterDoc,
    ChatterError,
    ChatterRef,
    ChatterTurn,
    ChuckchuckError,
    ConceptDoc,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    Context,
    ExtraConcept,
    FlowDiff,
    FlowIssue,
    FlowStep,
    GraphError,
    ParseError,
    Section,
    SlideDoc,
    SlideMark,
    SpeechBasis,
    SpeechEdge,
    STTError,
    Transcript,
    WeightBasis,
    WordTimestampUnsupported,
)
from .f01_parse import parse_document, sparse_slide_numbers
from .f05_stt import speech_for_slide, split_by_slide, transcribe
from .f06_concepts import extract_concepts
from .f07_graph import build_graph
from .f11_align import align_speech
from .f11_flow import build_flow_diff
from .f12_chatter import build_chatter
from .f13_score import score_presentation

__all__ = [
    "AlignError",
    "AlignmentDoc",
    "AlignmentItem",
    "AlignmentSummary",
    "ChatterDoc",
    "ChatterError",
    "ChatterRef",
    "ChatterTurn",
    "ChuckchuckError",
    "ConceptDoc",
    "ConceptEdge",
    "ConceptGraph",
    "ConceptNode",
    "Context",
    "ExtraConcept",
    "FlowDiff",
    "FlowIssue",
    "FlowStep",
    "GraphError",
    "ParseError",
    "STTError",
    "Section",
    "SlideDoc",
    "SlideMark",
    "SpeechBasis",
    "SpeechEdge",
    "Transcript",
    "WeightBasis",
    "WordTimestampUnsupported",
    "align_speech",
    "build_chatter",
    "build_flow_diff",
    "score_presentation",
    "build_graph",
    "extract_concepts",
    "parse_document",
    "settings",
    "sparse_slide_numbers",
    "speech_for_slide",
    "split_by_slide",
    "transcribe",
]

__version__ = "0.3.0"
