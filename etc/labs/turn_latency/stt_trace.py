#!/usr/bin/env python3
"""
실제 A.X 실시간 받아쓰기의 **사건 시각표**를 뜬다 (2026-10-17 tune · 말 끝 → 다음 말 지연).

브라우저와 똑같이 브리지 /api/v1/stt/live 에 16kHz mono PCM16 을 **실시간 속도**(0.1초에 1600표본)로 흘리고, 돌아오는
speech on/off(A.X vad bos/eos) · text(문장 확정)를 오디오 시각으로 적는다. 오디오의 실제 말소리 구간(에너지 VAD)도 같이 적어서
「진짜 말 끝 → eos → 문장 확정」 늦음(α)과 문장 사이 쉼의 분포를 낸다. 결과 JSON 은 sim.py(말 끝 판단 모의)가 읽는다.

    .venv/bin/python etc/labs/turn_latency/stt_trace.py --base http://127.0.0.1:8824 --out /data/models/_runs/wt-qa-tune/stt_trace \\
        --audio "main/decks/수익률격차/최종녹음본_척척발표.m4a" --start 0 --sec 240

과금: A.X STT 실시간 세션 1건 = 오디오 길이만큼. 호출 로그는 브리지가 남긴다(record_live_session).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

RATE = 16000
FRAME = 1600          # 0.1초 — 브라우저 live_stt.js LIVE_STT_FRAME_SAMPLES 와 같다
FFMPEG = str(Path.home() / ".local/bin/ffmpeg")


def load_pcm(path: str, start: float, sec: float) -> np.ndarray:
    if not Path(path).exists():   # 맥에서 온 파일 이름은 한글이 NFD 라 이름으로 못 찾는다 — 그 폴더의 녹음 하나
        path = str(next(Path(path).parent.glob("*.m4a")))
    cmd = [FFMPEG, "-v", "error", "-ss", str(start), "-t", str(sec), "-i", path, "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype="<i2")


def energy_segments(pcm: np.ndarray, *, win: float = 0.03, min_sil: float = 0.25, min_speech: float = 0.12) -> list[tuple[float, float]]:
    """말소리 구간 — 30ms 창 RMS 가 (잡음 바닥 + 문턱) 넘는 곳. min_sil 보다 짧은 쉼은 이어 붙인다."""
    n = int(RATE * win)
    frames = pcm[: len(pcm) // n * n].astype(np.float32).reshape(-1, n)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-9)
    db = 20 * np.log10(rms + 1e-9)
    floor = np.percentile(db, 10)
    thr = max(floor + 12.0, np.percentile(db, 30))
    on = db > thr
    segs, i = [], 0
    while i < len(on):
        if on[i]:
            j = i
            while j < len(on) and on[j]:
                j += 1
            segs.append([i * win, j * win])
            i = j
        else:
            i += 1
    merged: list[list[float]] = []
    for s in segs:
        if merged and s[0] - merged[-1][1] < min_sil:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return [(round(a, 3), round(b, 3)) for a, b in merged if b - a >= min_speech]


async def stream(base: str, pcm: np.ndarray, tail_sec: float) -> list[dict]:
    import websockets
    url = base.replace("http", "ws", 1).rstrip("/") + "/api/v1/stt/live?purpose=present"
    origin = base.rstrip("/")
    events: list[dict] = []
    async with websockets.connect(url, additional_headers={"Origin": origin}, max_size=2 ** 22) as ws:
        t0 = None

        async def rx():
            async for m in ws:
                if isinstance(m, bytes):
                    continue
                d = json.loads(m)
                d["t"] = round(time.monotonic() - (t0 or time.monotonic()), 3)
                events.append(d)
                if d.get("type") in ("done", "error"):
                    return

        task = asyncio.create_task(rx())
        # ready 를 기다린다 (브라우저도 열리면 쌓아 둔 걸 보낸다)
        for _ in range(100):
            if any(e.get("type") == "ready" for e in events):
                break
            await asyncio.sleep(0.05)
        t0 = time.monotonic()
        for e in events:
            e["t"] = 0.0
        silence = np.zeros(int(RATE * tail_sec), dtype="<i2")
        allpcm = np.concatenate([pcm, silence])
        for k in range(0, len(allpcm), FRAME):
            due = t0 + k / RATE
            now = time.monotonic()
            if due > now:
                await asyncio.sleep(due - now)
            await ws.send(allpcm[k:k + FRAME].tobytes())
        await ws.send(json.dumps({"type": "stop"}))
        try:
            await asyncio.wait_for(task, timeout=15)
        except asyncio.TimeoutError:
            pass
    return events


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8824")
    ap.add_argument("--audio", required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--sec", type=float, default=180.0)
    ap.add_argument("--tail", type=float, default=6.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="")
    args = ap.parse_args()
    pcm = load_pcm(args.audio, args.start, args.sec)
    segs = energy_segments(pcm)
    events = asyncio.run(stream(args.base, pcm, args.tail))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = args.name or f"{Path(args.audio).parent.name}_{int(args.start)}"
    rec = {"audio": args.audio, "start": args.start, "sec": len(pcm) / RATE, "segments": segs, "events": events}
    (out / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    texts = [e for e in events if e.get("type") == "text"]
    print(f"{name}: 말소리 구간 {len(segs)} · 문장 {len(texts)} · 사건 {len(events)} · 마지막 {events[-1] if events else None}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
