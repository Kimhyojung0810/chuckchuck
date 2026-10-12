"""
개발용 — 클로바노트 전사(.txt)를 녹음 대신 쓴다 (`#/test/qa` 의 「녹음까지」).

오디오가 없는 덱 폴더에 클로바 전사가 있으면, 브리지가 **표식이 박힌 무음 WAV** 를 녹음처럼 내려주고,
그 WAV 가 /api/v1/transcribe 로 돌아오면 STT 대신 이 전사로 Transcript 를 만든다. 화면 코드는 그대로다.
DEMO_DEV_ROUTES=1 일 때만 브리지가 부른다.

2026-09-29: 수면 발표는 음성 파일이 없고 클로바 전사만 있어서, 녹음 경로(정합·흐름·시간 배분)를
화면에서 직접 볼 길이 없었다.

클로바 .txt 모양:
    제목 줄 · "2026.08.04 화 오후 3:09 ・ 8분 15초" · 화자
    00:01            ← 구간 시작 (MM:SS)
    문장 …
    01:20
    …
시각은 구간 안에서 글자 수 비례로 나눈다 — 음성 정렬이 아니라 근사다. 슬라이드 구간은 F-04 가 추정한다.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

#: 무음 WAV 의 LIST/INFO 에 박는 표식. 뒤에 덱 폴더 이름(UTF-8)이 온다.
MARKER = b"CHUCKCHUCK-CLOVA:"
#: 무음 WAV 표본율 — 작게 둔다 (8분 ≈ 3.8MB). 받아쓰기로 안 가므로 소리 품질은 상관없다.
_RATE = 4000

_STAMP_RE = re.compile(r"(\d{1,2}):(\d{2})")
_DURATION_RE = re.compile(r"(\d+)\s*분\s*(\d+)\s*초")


def find_clova_txt(files: list[Path]) -> Path | None:
    """폴더 파일 중 클로바 전사로 보이는 .txt (MM:SS 줄이 둘 이상)."""
    for q in files:
        if q.suffix.lower() != ".txt":
            continue
        try:
            text = q.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        if sum(1 for line in text.splitlines() if _STAMP_RE.fullmatch(line.strip())) >= 2:
            return q
    return None


def _blocks(text: str) -> tuple[list[tuple[int, list[str]]], float]:
    blocks: list[tuple[int, list[str]]] = []
    duration = 0.0
    for line in text.splitlines():
        s = line.strip()
        m = _STAMP_RE.fullmatch(s)
        if m:
            blocks.append((int(m.group(1)) * 60 + int(m.group(2)), []))
            continue
        if not blocks:
            d = _DURATION_RE.search(s)
            if d:
                duration = float(int(d.group(1)) * 60 + int(d.group(2)))
            continue
        if s and "clovanote" not in s:
            blocks[-1][1].append(s)
    if not duration and blocks:
        duration = float(blocks[-1][0] + 60)
    return blocks, duration


def duration_of(path: Path) -> float:
    return _blocks(path.read_text(encoding="utf-8-sig"))[1]


def transcript_dict(path: Path) -> dict:
    """클로바 .txt → Transcript 사전 (words 에 근사 시각, by_slide 는 비움 — F-04 가 나눈다)."""
    blocks, duration = _blocks(path.read_text(encoding="utf-8-sig"))
    words: list[dict] = []
    sentences: list[str] = []
    for i, (t0, lines) in enumerate(blocks):
        t1 = blocks[i + 1][0] if i + 1 < len(blocks) else max(duration, t0 + 1)
        sents = [x for line in lines for x in re.split(r"(?<=[.?!])\s+", line) if x.strip()]
        total = sum(len(x) for x in sents) or 1
        t = float(t0)
        for sent in sents:
            span = (t1 - t0) * len(sent) / total
            toks = sent.split()
            step = span / max(len(toks), 1)
            for k, tok in enumerate(toks):
                words.append({"text": tok, "start_sec": round(t + k * step, 2),
                              "end_sec": round(t + (k + 1) * step, 2)})
            sentences.append(sent)
            t += span
    return {
        "full_text": " ".join(sentences),
        "words": words,
        "by_slide": [],
        "provider": "clova-txt(개발용 근사)",
        "duration_sec": duration,
    }


def marked_silence(deck_key: str, seconds: float) -> bytes:
    """표식을 LIST/INFO 에 박은 무음 16-bit mono WAV."""
    tag = MARKER + deck_key.encode("utf-8")
    if len(tag) % 2:
        tag += b"\x00"
    info = b"INFO" + b"ICMT" + struct.pack("<I", len(tag)) + tag
    list_chunk = b"LIST" + struct.pack("<I", len(info)) + info
    n = int(max(seconds, 1.0) * _RATE)
    data = b"\x00\x00" * n
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, _RATE, _RATE * 2, 2, 16)
    body = b"WAVE" + fmt + list_chunk + b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


def marked_deck_key(audio: bytes) -> str | None:
    """무음 WAV 에 박힌 덱 폴더 이름. 표식이 없으면 None."""
    head = audio[:512]
    if not head.startswith(b"RIFF"):
        return None
    i = head.find(MARKER)
    if i < 0:
        return None
    rest = head[i + len(MARKER):]
    end = min((j for j in (rest.find(b"\x00"), rest.find(b"data")) if j >= 0), default=len(rest))
    try:
        return rest[:end].decode("utf-8")
    except UnicodeDecodeError:
        return None
