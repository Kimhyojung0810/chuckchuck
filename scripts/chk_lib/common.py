"""
chk 서브커맨드가 같이 쓰는 것: 저장소 경로 · 명령 실행 · git 질의 · 출력 포맷.

왜 — 검사 하나가 두 곳(git 훅 · Claude 훅 · 에이전트)에서 불리므로 로직은 여기 한 번만 있어야 한다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO = Path("demo/YEHS_demo")
INDEX_HTML = DEMO / "index.html"
APP_JS = DEMO / "js/app.js"
REVEAL_HTML = DEMO / "f11_reveal.html"

# pytest 기준선. 2026-09-13 이 머신 실측 830 passed · 7 skipped (WORKLOG 09-13 은 826).
# 환경이 달라 skip 이 늘면 CHK_PYTEST_MIN 으로 낮춘다 — 단 failed/error 는 어디서든 0 이어야 한다.
PYTEST_MIN = int(os.environ.get("CHK_PYTEST_MIN", "830"))

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if USE_COLOR else s


def ok(msg: str) -> str:
    return _c("32", "✓ ") + msg


def bad(msg: str) -> str:
    return _c("31", "✗ ") + msg


def warn(msg: str) -> str:
    return _c("33", "⚠ ") + msg


def dim(s: str) -> str:
    return _c("2", s)


def bold(s: str) -> str:
    return _c("1", s)


def sh(cmd: list[str], *, cwd: Path | None = None, timeout: int = 600,
       env: dict | None = None) -> subprocess.CompletedProcess:
    """명령을 돌리고 출력을 잡는다. 실패해도 예외를 내지 않는다 — 호출자가 returncode 를 본다."""
    return subprocess.run(
        cmd, cwd=str(cwd or ROOT), text=True, capture_output=True, timeout=timeout,
        env={**os.environ, **(env or {})},
    )


def venv_python() -> str:
    p = ROOT / ".venv/bin/python"
    return str(p) if p.exists() else sys.executable


def git(*args: str) -> str:
    r = sh(["git", *args])
    return r.stdout if r.returncode == 0 else ""


def changed_files(scope: str) -> list[str]:
    """scope: 'staged' = 인덱스에 올라간 것 · 'worktree' = HEAD 대비 바뀐 전부(추적 안 된 파일 포함)."""
    if scope == "staged":
        out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
        return [l for l in out.splitlines() if l.strip()]
    files: list[str] = []
    for line in git("status", "--porcelain", "-uall").splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path.strip('"'))
    return files


def diff_text(scope: str) -> str:
    """비밀키 검사용 diff 원문. worktree 는 추적 안 된 파일 내용도 붙인다 (git add -A 로 올라갈 수 있다)."""
    if scope == "staged":
        return git("diff", "--cached", "--unified=0")
    text = git("diff", "HEAD", "--unified=0")
    for path in git("ls-files", "--others", "--exclude-standard").splitlines():
        p = ROOT / path
        if p.is_file() and p.stat().st_size < 2_000_000:
            try:
                body = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            text += f"\n+++ b/{path}\n" + "\n".join("+" + l for l in body.splitlines())
    return text


def file_at(path: str, scope: str) -> str:
    """검사 대상 시점의 파일 내용. staged 는 인덱스 사본, worktree 는 작업 사본."""
    if scope == "staged":
        r = sh(["git", "show", f":{path}"])
        if r.returncode == 0:
            return r.stdout
    p = ROOT / path
    return p.read_text(encoding="utf-8") if p.exists() else ""


def file_at_head(path: str) -> str:
    r = sh(["git", "show", f"HEAD:{path}"])
    return r.stdout if r.returncode == 0 else ""


@dataclass
class Check:
    name: str
    status: str            # ok | fail | warn | skip
    detail: str = ""
    lines: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.status == "fail"


def render(checks: list[Check]) -> str:
    icon = {"ok": ok, "fail": bad, "warn": warn, "skip": lambda m: dim("– " + m)}
    out = []
    for c in checks:
        out.append(icon[c.status](f"{c.name:<14} {c.detail}"))
        out.extend("    " + l for l in c.lines[:12])
    return "\n".join(out)


def read_dotenv(path: Path = ROOT / ".env") -> dict[str, str]:
    """config.load_dotenv 와 같은 규칙으로 읽되 os.environ 에 넣지 않는다 — 값을 밖으로 흘리지 않기 위해."""
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env
