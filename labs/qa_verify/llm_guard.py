"""
대상 저장소의 **실제 LLM 제공자**에 겉감을 씌운다 — 막기(quick: 한 번이라도 부르면 예외) 또는 세기(standard/full: 호출마다
한 줄 기록 · 예산에서 끊기). 대상 코드 파일은 건드리지 않는다: 프로세스 안에서 클래스의 `complete` 만 감싼다.

브리지(bridge_wrap.py)와 판정 자식(target_probe.py)이 같은 파일(calls.jsonl)에 쓰므로 예산은 두 프로세스를 합쳐 센다.
합성 제공자(FallbackLLM → 1차·2차)는 바깥 호출 하나로 센다 — 재시도·예비 전환은 한 번의 「논리 호출」이다.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

_local = threading.local()
_lock = threading.Lock()


class BudgetExceeded(RuntimeError):
    pass


class LLMForbidden(RuntimeError):
    pass


def count_calls(path: Path | None) -> int:
    if path is None or not Path(path).exists():
        return 0
    with Path(path).open(encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _caller() -> str:
    """이 호출을 부른 기능 모듈 (chuckchuck.fXX · demo.bridge · 하네스) — 기록용."""
    f = sys._getframe(2)
    seen = []
    while f is not None:
        mod = f.f_globals.get("__name__", "")
        if mod.startswith(("chuckchuck.f", "chuckchuck._", "demo.", "labs.")) and "providers" not in mod:
            seen.append(f"{mod}.{f.f_code.co_name}")
            if mod.startswith("chuckchuck.f") or mod.startswith("labs."):
                break
        f = f.f_back
    return seen[-1] if seen else "?"


def install(mode: str, calls_path: str | Path | None = None, budget: int | None = None, stage: str = "") -> list[str]:
    """
    mode: "forbid" | "count". 감싼 클래스 이름 목록을 돌려준다.
    count 면 calls_path 에 호출마다 {"ts","stage","caller","sec","err"} 한 줄. budget 을 넘으면 부르기 **전에** BudgetExceeded.
    """
    from chuckchuck.providers import llm_base, llm_impl

    path = Path(calls_path) if calls_path else None
    wrapped = []
    for name, obj in list(vars(llm_impl).items()):
        if not (isinstance(obj, type) and issubclass(obj, llm_base.LLMProvider) and obj is not llm_base.LLMProvider):
            continue
        if "complete" not in vars(obj) or getattr(obj.complete, "_qa_verify", False):
            continue
        _wrap(obj, mode, path, budget, stage)
        wrapped.append(name)
    return wrapped


def _wrap(cls, mode: str, path: Path | None, budget: int | None, stage: str) -> None:
    orig = cls.complete

    def complete(self, *args, **kwargs):
        if getattr(_local, "depth", 0):
            return orig(self, *args, **kwargs)          # 합성 제공자 안쪽 — 바깥에서 이미 셌다
        if mode == "forbid":
            raise LLMForbidden(f"qa_verify quick: LLM 을 부르지 않아야 한다 ({_caller()})")
        with _lock:
            if budget is not None and count_calls(path) >= budget:
                raise BudgetExceeded(f"qa_verify LLM 예산 {budget} 을 다 썼어요 ({_caller()})")
        _local.depth = 1
        t0, err = time.time(), ""
        who = _caller()
        try:
            return orig(self, *args, **kwargs)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:160]}"
            raise
        finally:
            _local.depth = 0
            if path is not None:
                with _lock:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"ts": time.strftime("%H:%M:%S"), "stage": stage, "caller": who,
                                            "model": getattr(self, "name", ""), "sec": round(time.time() - t0, 2),
                                            "err": err}, ensure_ascii=False) + "\n")

    complete._qa_verify = True  # type: ignore[attr-defined]
    cls.complete = complete
