#!/usr/bin/env python3
"""
CLI 벤치·실험 스크립트를 **국내 AI API 호출 로그를 켠 채로** 돌린다 (2026-10-17 — 지난 CLI 벤치는 한 건도 안 적혔다).

    AI_CALLLOG=all AI_CALLLOG_DIR=/data/models/_runs/qa-ensemble/calllog \\
        python etc/bench/calllog_run.py etc/bench/build_deck_bundle.py --out DIR --deck X=...

브리지는 main() 에서 `_ai_calllog.install()` 을 부르지만 CLI 는 아무도 안 부른다. 이 껍데기가 먼저 설치하고 대상 스크립트를
같은 프로세스에서 `runpy` 로 돌린다. AI_CALLLOG 를 안 줬으면 all 로 둔다 (CLI 엔 팀 쿠키 범위가 없어서 team 이면 0건이다).
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "main"), str(ROOT / "etc"), str(ROOT)]
os.environ.setdefault("AI_CALLLOG", "all")

from pipeline.config import load_dotenv  # noqa: E402

load_dotenv()
from pipeline import _ai_calllog  # noqa: E402
from pipeline.config import settings  # noqa: E402

_ai_calllog.install(settings)
sys.stderr.write(f"[calllog_run] AI_CALLLOG={_ai_calllog.mode()} · {_ai_calllog.root()}\n")

if len(sys.argv) < 2:
    sys.exit("사용: calllog_run.py <스크립트.py> [인자…]")
target = sys.argv[1]
sys.argv = sys.argv[1:]
sys.path.insert(0, str(Path(target).resolve().parent))
runpy.run_path(target, run_name="__main__")
