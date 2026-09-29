"""
브리지 진입점 — 대상 저장소의 demo.bridge 를 그대로 띄우되, LLM 제공자에 세는 겉감(llm_guard)을 씌운다.

    <대상 python> labs/qa_verify/bridge_wrap.py        (cwd=<대상>, 환경: QA_VERIFY_REPO · QA_VERIFY_CALLS · QA_VERIFY_BUDGET)

대상 코드 파일은 건드리지 않는다. 호출마다 calls.jsonl 에 한 줄, 예산을 넘으면 그 요청이 실패한다(부르기 전에 끊는다).
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    here = Path(__file__).resolve().parent
    repo = Path(os.environ["QA_VERIFY_REPO"]).resolve()
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != here]
    sys.path.insert(0, str(repo))
    import chuckchuck  # noqa: F401 — 대상 패키지

    sys.path.insert(0, str(here.parents[1]))
    from labs.qa_verify import llm_guard

    budget = int(os.environ.get("QA_VERIFY_BUDGET") or 0) or None
    wrapped = llm_guard.install("count", os.environ.get("QA_VERIFY_CALLS"), budget, stage="bridge")
    sys.path.remove(str(here.parents[1]))
    print(f"[qa_verify] LLM 호출을 센다: {', '.join(wrapped)} · 예산 {budget}", flush=True)
    runpy.run_module("demo.bridge", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
