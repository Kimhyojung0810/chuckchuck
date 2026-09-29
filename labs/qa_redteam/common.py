"""labs/qa_redteam 공통 — 예산 걸린 LLM 겉감(모든 호출을 프롬프트·응답째 남김)과 덱 묶음 읽기."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
OUT = HERE / "out"
FROZEN = Path("/home/yehschuck/project/wt-qa-final/labs/qa_bench/out")

from chuckchuck.config import load_dotenv  # noqa: E402

load_dotenv()
from chuckchuck.providers.llm_base import LLMProvider  # noqa: E402

LIMIT = 150


def used() -> int:
    p = OUT / "calls.jsonl"
    return sum(1 for _ in p.open(encoding="utf-8")) if p.exists() else 0


class BudgetExceeded(RuntimeError):
    pass


class Counted(LLMProvider):
    def __init__(self, stage: str):
        from chuckchuck.providers.llm_impl import get_llm
        self.inner = get_llm(None)
        self.stage = stage
        self.name = getattr(self.inner, "name", "unknown")

    def complete(self, *, system: str, user: str, temperature: float = 0.2, max_tokens: int = 4096,
                 json_mode: bool = False) -> str:
        if used() >= LIMIT:
            raise BudgetExceeded(f"예산 {LIMIT} 소진 ({self.stage})")
        t0, err, out = time.time(), "", ""
        try:
            out = self.inner.complete(system=system, user=user, temperature=temperature, max_tokens=max_tokens,
                                      json_mode=json_mode)
            return out
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:200]}"
            raise
        finally:
            OUT.mkdir(parents=True, exist_ok=True)
            with (OUT / "calls.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.strftime("%H:%M:%S"), "stage": self.stage, "model": self.name,
                                    "temperature": temperature, "sec": round(time.time() - t0, 1),
                                    "system": system, "user": user, "out": out, "err": err},
                                   ensure_ascii=False) + "\n")


def rj(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def wj(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
