"""chk 서브커맨드 분배. 각 서브커맨드는 자기 모듈의 run(args) 이 int 를 돌려준다."""

from __future__ import annotations

import argparse
import importlib

COMMANDS = {
    "gate": ("gate", "커밋 전 문지기 — pytest · node 스모크 · ?v= 캐시 버전 · 비밀키 (실패면 exit 1)"),
    "bump": ("bump", "바뀐 css/js 의 index.html ?v= 와 리빌 iframe v= 를 올린다"),
    "doctor": ("doctor", "이 머신에서 브리지가 뜰 조건 점검 — 키 유무(값 안 보임) · torch/CUDA · LoRA · ffmpeg · 포트"),
    "warmup": ("warmup", "브리지 예열 — /api/v1/habits 를 두 번 불러 provider 와 지연을 확인"),
    "brief": ("brief", "세션 시작 브리핑 — 마일스톤 D-day · 할 일 · 장부 · WORKLOG 맨 위 · git"),
    "ledger-chart": ("ledger", "장부의 IMPROVED 줄을 이어 결선 그래프(SVG)와 표(MD)를 만든다"),
    "install-hooks": ("hooks", "git pre-commit 훅으로 gate 를 건다 (core.hooksPath)"),
    "hook-precommit": ("hooks", "(Claude Code PreToolUse 훅용) git commit 명령이면 gate 를 돌린다"),
}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="scripts/chk", description="척척발표 개발 도구. LLM 호출 없음 · 과금 없음.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(f"  {k:<15} {v[1]}" for k, v in COMMANDS.items()),
    )
    ap.add_argument("command", choices=COMMANDS.keys())
    ap.add_argument("rest", nargs=argparse.REMAINDER)
    ns = ap.parse_args(argv)
    module_name, _ = COMMANDS[ns.command]
    mod = importlib.import_module(f"chk_lib.{module_name}")
    if ns.command == "hook-precommit":
        return mod.run_hook(ns.rest)
    return mod.run(ns.rest)
