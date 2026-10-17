"""
미리 판정 (speculative judge, 2026-10-17 tune · 음성UX 조사 R3) — 말이 끝났다고 **짐작한 순간** 판정을 먼저 돌려 둔다.

화상판 자동 보내기는 말 끝(받아쓰기 문장 확정) 뒤 침묵 + 초읽기를 기다렸다가 답을 보낸다(지금 2.2초 + 3초). 판정 LLM(solar4 p50 3.7초)은
그 뒤에야 돌기 시작해, 말 끝 → 다음 말 첫 글자가 9초를 넘었다. 화면이 초읽기를 시작할 때(또는 문장이 확정될 때) 같은 본문에
`speculative: true` 를 실어 보내면, 브리지는 **판정만** 뒤에서 돌려 두고 202 를 바로 돌려준다. 초읽기가 끝나 진짜 요청이 오면
같은 본문(열쇠가 같은 것)의 판정을 기다려 받아 쓰고, 그때 판정 기록(qa_turns) · 대화 상태 같은 부작용을 남긴다. 사람이 더 말해
답이 바뀌면 열쇠가 달라 미리 한 판정은 버려진다(호출 로그에는 남는다 — 그만큼 호출이 는다).

- 판정(`judge_answer`)만 미리 돌린다 — 질문 찾기 · 자료 확인 · 요청 제한 · 기록은 진짜 요청이 한다.
- 열쇠 = 판정에 들어가는 재료 전부(세션 · 판 · 질문 · 답 · 앞 답 · 대화 · 힌트 · 포기 · 판정 모델 · 이미 한 말)의 지문.
- 보관 QA_SPEC_TTL_SEC(기본 60초) · 최대 QA_SPEC_MAX(기본 64개). 끄기: `QA_SPEC=0` (미리 판정 요청을 202 로 받기만 하고 아무것도 안 한다).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

from pipeline import _ai_calllog


def enabled() -> bool:
    return (os.environ.get("QA_SPEC", "1") or "1").strip().lower() not in ("0", "off", "false", "no")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


TTL_SEC = _env_float("QA_SPEC_TTL_SEC", 60.0)
MAX_ITEMS = int(_env_float("QA_SPEC_MAX", 64))
#: 진짜 요청이 미리 한 판정을 기다리는 상한 — 판정 LLM 의 p99 정도. 넘으면 새로 판정한다(같은 일을 두 번 하는 것보다 기다리는 게 싸다).
TAKE_WAIT_SEC = _env_float("QA_SPEC_WAIT_SEC", 25.0)

_POOL = ThreadPoolExecutor(max_workers=int(_env_float("QA_SPEC_WORKERS", 6)), thread_name_prefix="qa-spec")
_LOCK = threading.Lock()
_ITEMS: dict[str, tuple[float, Future]] = {}
STATS = {"started": 0, "dup": 0, "hit": 0, "miss": 0, "failed": 0, "expired": 0}


def key(*parts) -> str:
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _prune(now: float) -> None:
    for k in [k for k, (t, _) in _ITEMS.items() if now - t > TTL_SEC]:
        _ITEMS.pop(k, None)
        STATS["expired"] += 1
    while len(_ITEMS) > MAX_ITEMS:
        _ITEMS.pop(next(iter(_ITEMS)))
        STATS["expired"] += 1


def start(k: str, fn) -> bool:
    """판정을 뒤에서 돌리기 시작한다. 같은 열쇠가 이미 돌고 있으면 아무것도 안 한다(False)."""
    now = time.monotonic()
    with _LOCK:
        _prune(now)
        if k in _ITEMS:
            STATS["dup"] += 1
            return False
        _ITEMS[k] = (now, _POOL.submit(_ai_calllog.carry(fn, "F-09")))
        STATS["started"] += 1
    return True


def take(k: str, wait: float | None = None):
    """미리 한 판정 — 없거나 실패했으면 None(진짜 요청이 새로 판정한다). 돌고 있으면 끝날 때까지 기다린다."""
    with _LOCK:
        item = _ITEMS.pop(k, None)
    if item is None:
        STATS["miss"] += 1
        return None
    t0, fut = item
    try:
        out = fut.result(timeout=TAKE_WAIT_SEC if wait is None else wait)
    except Exception as e:  # noqa: BLE001 — 늦거나 실패하면 새로 판정
        STATS["failed"] += 1
        sys.stderr.write(f"[qa-spec] 미리 판정 못 씀: {type(e).__name__}: {str(e)[:120]}\n")
        return None
    STATS["hit"] += 1
    return out, round(time.monotonic() - t0, 2)


__all__ = ["enabled", "key", "start", "take", "STATS", "TTL_SEC"]
