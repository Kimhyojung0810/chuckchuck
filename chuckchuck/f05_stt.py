"""
[F-05] 녹음 음성을 글로 바꾸고, 슬라이드 구간별로 나누는 모듈입니다.
STT(기본 A.X) + 슬라이드 marks 시각을 맞춰 Transcript를 만듭니다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .contracts import SlideMark, SlideSpeech, STTError, Transcript, Word
from .providers.stt_base import STTProvider
from .providers.stt_impl import get_provider

SENTENCE_END = re.compile(r"[.!?]$|다$|요$|까$|죠$|음$|임$")


def _sentence_end(text: str) -> bool:
    return bool(SENTENCE_END.search(text.strip()))


def split_by_slide(words: list[Word], marks: list[SlideMark]) -> list[SlideSpeech]:
    """
    단어별 시각과 슬라이드 구간을 대조해 발화를 슬라이드별로 나눈다.

    문장이 시작된 시점의 슬라이드에 문장 전체를 넣는다.
    되돌아가기(재방문)는 visit 로 별도 보존한다.
    """
    if not marks:
        return []

    ordered = sorted(marks, key=lambda m: m.start_sec)
    buckets: list[list[Word]] = [[] for _ in ordered]
    locked_idx: int | None = None

    for w in words:
        idx = None
        for i, m in enumerate(ordered):
            if m.start_sec <= w.start_sec < m.end_sec:
                idx = i
                break
        if idx is None:
            idx = len(ordered) - 1 if w.start_sec >= ordered[-1].start_sec else 0

        target = locked_idx if locked_idx is not None else idx
        buckets[target].append(w)

        if _sentence_end(w.text):
            locked_idx = None
        elif locked_idx is None:
            locked_idx = target

    out: list[SlideSpeech] = []
    for m, bucket in zip(ordered, buckets):
        out.append(SlideSpeech(
            slide_no=m.slide_no,
            visit=m.visit,
            start_sec=m.start_sec,
            end_sec=m.end_sec,
            text=" ".join(w.text for w in bucket),
            words=bucket,
        ))
    return out


def transcribe(
    audio_path: str | Path,
    marks: list[SlideMark] | list[dict],
    *,
    provider: str | STTProvider | None = None,
    provider_kwargs: dict | None = None,
    keywords: list[str] | None = None,
) -> Transcript:
    """
    녹음을 글자로 바꾸고 슬라이드별로 나눈다.

    provider 기본값: STT_PROVIDER 환경변수, 없으면 skt-ax.
    개발 시 provider="mock" 으로 바꾸면 된다.
    """
    if marks and isinstance(marks[0], dict):
        marks = [SlideMark.from_dict(m) for m in marks]  # type: ignore[arg-type]

    if provider is None:
        provider = os.environ.get("STT_PROVIDER", "skt-ax")

    kwargs = dict(provider_kwargs or {})
    if keywords and "keywords" not in kwargs and not isinstance(provider, STTProvider):
        kwargs["keywords"] = keywords

    engine = (
        provider
        if isinstance(provider, STTProvider)
        else get_provider(str(provider), **kwargs)
    )
    engine.check_capability()

    full_text, words = engine.transcribe(audio_path)
    if not words and not full_text:
        raise STTError(f"[{engine.name}] 인식 결과가 비어 있습니다.")

    return Transcript(
        full_text=full_text,
        words=words,
        by_slide=split_by_slide(words, marks),  # type: ignore[arg-type]
        provider=engine.name,
        duration_sec=max((w.end_sec for w in words), default=0.0),
    )


def speech_for_slide(t: Transcript, slide_no: int) -> str:
    """특정 슬라이드에서 한 말 전부 (재방문 포함)."""
    parts = [s.text for s in t.by_slide if s.slide_no == slide_no and s.text.strip()]
    return " ".join(parts)
