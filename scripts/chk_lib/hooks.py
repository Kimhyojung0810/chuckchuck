"""
gate 를 훅으로 건다.

- `scripts/chk install-hooks`  → git 의 core.hooksPath 를 scripts/githooks 로. 이후 `git commit` 마다 staged 범위로 gate.
- `scripts/chk hook-precommit` → Claude Code PreToolUse(Bash) 훅. stdin JSON 의 command 에 `git commit` 이 있으면
  worktree 범위로 gate 를 돌리고, 실패면 exit 2 (도구 실행을 막고 stderr 를 모델에 보여 준다).
  git 훅이 이미 설치돼 있으면 두 번 돌지 않게 건너뛴다 — git 훅(staged)이 더 정확하다.

건너뛰기: CHK_SKIP_GATE=1. 검증 안 끝난 커밋이 필요할 때가 아니라, 훅 자체가 고장났을 때만 쓴다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from . import common as C

HOOKS_DIR = "scripts/githooks"
COMMIT_RE = re.compile(r"\bgit\s+(?:-\S+\s+)*commit\b")


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="scripts/chk install-hooks", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uninstall", action="store_true")
    ns = ap.parse_args(argv)
    if ns.uninstall:
        C.sh(["git", "config", "--unset", "core.hooksPath"])
        print(C.ok("core.hooksPath 해제 — 이제 git commit 은 gate 를 안 거친다"))
        return 0
    hook = C.ROOT / HOOKS_DIR / "pre-commit"
    hook.chmod(hook.stat().st_mode | 0o111)
    r = C.sh(["git", "config", "core.hooksPath", HOOKS_DIR])
    if r.returncode != 0:
        print(C.bad(f"git config 실패: {r.stderr.strip()}"))
        return 1
    print(C.ok(f"core.hooksPath = {HOOKS_DIR} — git commit 마다 `chk gate --scope staged` 가 돈다"))
    return 0


def git_hook_installed() -> bool:
    return C.git("config", "core.hooksPath").strip() == HOOKS_DIR


def run_hook(argv: list[str]) -> int:
    if os.environ.get("CHK_SKIP_GATE") == "1":
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    cmd = str((payload.get("tool_input") or {}).get("command", ""))
    if not COMMIT_RE.search(cmd) or "--no-verify" in cmd:
        return 0
    if git_hook_installed():
        return 0  # git 훅이 staged 범위로 곧 돈다
    from . import gate
    r = C.sh([sys.executable, str(C.ROOT / "scripts/chk"), "gate", "--scope", "worktree"], timeout=900)
    if r.returncode == 0:
        return 0
    sys.stderr.write("chk gate 가 커밋을 막았어요 (CLAUDE.md §3-5). 아래를 고친 뒤 다시 커밋한다.\n")
    sys.stderr.write(r.stdout[-3000:] + r.stderr[-1000:])
    return 2
