"""
Upstage 임베딩 (embedding-passage) — 개념 그래프의 같은 개념 묶기 후보를 고를 때 쓴다 (`_typed_graph.call_same`).
키가 없거나 호출이 깨지면 None — 묶기를 건너뛰고 그래프는 그대로 나온다. 같은 글은 프로세스 안에서 다시 부르지 않는다.
"""
from __future__ import annotations

import os
import sys

import requests

MODEL = os.environ.get("UPSTAGE_EMBED_MODEL", "embedding-passage")
_CACHE: dict[str, list[float]] = {}


def embed_texts(texts: list[str], timeout: float = 30.0) -> list[list[float]] | None:
    key = os.environ.get("UPSTAGE_API_KEY", "")
    if not key or not texts:
        return None
    base = os.environ.get("UPSTAGE_SOLAR_BASE_URL", "https://api.upstage.ai/v1")
    todo = [t for t in dict.fromkeys(texts) if t not in _CACHE]
    try:
        for i in range(0, len(todo), 50):
            chunk = todo[i:i + 50]
            r = requests.post(f"{base}/embeddings", timeout=timeout, headers={"Authorization": f"Bearer {key}"},
                              json={"model": MODEL, "input": chunk})
            r.raise_for_status()
            for t, d in zip(chunk, sorted(r.json()["data"], key=lambda d: d["index"])):
                _CACHE[t] = d["embedding"]
    except Exception as e:  # noqa: BLE001 — 묶기는 보조라 그래프를 실패시키지 않는다, 적고 넘어간다
        sys.stderr.write(f"[embed] 임베딩 실패 — 같은 개념 묶기를 건너뛴다: {type(e).__name__}: {str(e)[:120]}\n")
        return None
    return [_CACHE[t] for t in texts]
