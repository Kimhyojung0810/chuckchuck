"""
하네스 공통 — 경로 · JSON · 명령 실행 · 시각. 대상 저장소 코드를 import 하지 않는다.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: 하네스가 들어 있는 저장소 (잣대·벤치 캐시·결과가 여기 있다). 검증 대상(--repo)과 다를 수 있다.
HARNESS_ROOT = HERE.parents[1]
OUT = HERE / "out"
HISTORY = OUT / "history.jsonl"
FROZEN = OUT / "frozen"
#: 실제 덱·부스 세션이 있는 주 체크아웃 — 읽기만 한다 (회귀 사례 원본 · ppt/ 덱).
MAIN_CHECKOUT = Path(os.environ.get("QA_VERIFY_MAIN", "/home/yehschuck/project/chuckchuck"))
#: 벤치 캐시(labs/qa_bench 산출물) — 결정적 재생의 입력. 대상이 아니라 하네스 쪽 것을 쓴다(두 대상을 같은 입력으로 잰다).
BENCH_CACHE = Path(os.environ.get("QA_VERIFY_BENCH_CACHE", str(HARNESS_ROOT / "labs" / "qa_bench" / "out")))
#: 헤드리스 크로미움이 찾는 libasound (루트 없는 우회, labs/qa_call/README.md)
PW_LIBS = "/tmp/pwlibs/usr/lib/x86_64-linux-gnu"


def nfc(text: str | None) -> str:
    return unicodedata.normalize("NFC", text or "")


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def append_jsonl(path: Path, row: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None,
        timeout: int = 900) -> subprocess.CompletedProcess:
    """명령을 돌리고 출력을 잡는다. 실패해도 예외를 내지 않는다 — 시간 초과는 returncode 124 로 돌려준다."""
    try:
        return subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True,
                              timeout=timeout, env={**os.environ, **(env or {})})
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return subprocess.CompletedProcess(cmd, 124, out, err + f"\n(시간 초과 {timeout}s)")


def tail(text: str, n: int = 12) -> list[str]:
    return [line for line in (text or "").strip().splitlines()[-n:]]


def pct(a: float, b: float) -> str:
    return "-" if not b else f"{100 * a / b:.0f}% ({a:g}/{b:g})"


def note(msg: str) -> None:
    print(msg, flush=True)


def json_dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False)
