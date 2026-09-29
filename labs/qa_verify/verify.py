"""
척척발표 Q&A 파이프라인 검증 하네스 — 아무 worktree 에나 걸어 되풀이해 돌리고, 기준선보다 나빠지면 exit 1.

    .venv/bin/python labs/qa_verify/verify.py --repo <worktree> --tier quick
    .venv/bin/python labs/qa_verify/verify.py --repo <worktree> --tier standard --port 8815 --budget 50
    .venv/bin/python labs/qa_verify/verify.py --repo <worktree> --tier full --budget 150
    .venv/bin/python labs/qa_verify/verify.py --repo <worktree> --tier quick --baseline out/<stamp>/scoreboard.json

tier
- quick     LLM 0콜 · 3분 안: 대상 pytest·node 스모크 · 회귀 사례(regression/cases.json) · 벤치 캐시 결정적 재생 · 판정 가드 감사
- standard  quick + 대상 코드로 브리지를 띄워(기본 8815) 덱 3개(튜닝 1 + held-out 2) 5분 트랙을 화면으로 대화 · 레드팀 판정 (≤ ~50콜)
- full      quick + 덱 전부 · 5·10분 트랙 · 녹음 모드 덱 하나 · booth.html 사진 흐름 (≤ ~150콜)

결과: labs/qa_verify/out/<stamp>_<tier>_<label>/scoreboard.json · scoreboard.md (+ out/history.jsonl — git 무시)
기준선: --baseline latest(기본, 같은 tier·범위의 마지막) · latest-any · none · <scoreboard.json>
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

if __package__ in (None, ""):          # `python labs/qa_verify/verify.py` 로 불렀을 때 — 패키지로 올린다
    _root = Path(__file__).resolve().parents[2]
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != Path(__file__).resolve().parent]
    sys.path.insert(0, str(_root))
    __package__ = "labs.qa_verify"
    import importlib

    importlib.import_module(__package__)

from . import common as C  # noqa: E402
from . import quick  # noqa: E402
from . import scoreboard as S  # noqa: E402
from .target import Target  # noqa: E402

DEFAULT_BUDGET = {"quick": 0, "standard": 50, "full": 150}


def parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="labs/qa_verify/verify.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="검증할 worktree (척척발표 저장소 뿌리)")
    ap.add_argument("--tier", choices=("quick", "standard", "full"), default="quick")
    ap.add_argument("--decks", default="", help="쉼표로. quick 은 벤치 캐시 이름(sleep·yield_gap…), standard/full 은 ppt 폴더 이름·줄임말")
    ap.add_argument("--tracks", default="", help="standard/full 트랙 (기본 standard 5 · full 5,10)")
    ap.add_argument("--port", type=int, default=8815, help="standard/full 브리지 포트 (8799 는 쓰지 않는다)")
    ap.add_argument("--budget", type=int, default=None, help="LLM 호출 상한 (브리지+판정 합). 기본 standard 50 · full 150")
    ap.add_argument("--baseline", default="latest", help="latest · latest-any · none · <scoreboard.json>")
    ap.add_argument("--skip-quick", action="store_true", help="standard/full 에서 quick 단계를 건너뛴다")
    ap.add_argument("--no-record", action="store_true", help="history.jsonl 에 남기지 않는다 (기준선이 안 된다)")
    ap.add_argument("--no-redteam", action="store_true", help="standard/full 에서 레드팀 판정을 건너뛴다")
    ap.add_argument("--no-papers", action="store_true", help="브리지를 SCHOLAR_PROVIDER=none 으로 (문헌 검색 LLM 1콜/덱 아낌)")
    ap.add_argument("--keep-bridge", action="store_true", help="끝나도 브리지를 끄지 않는다 (디버그)")
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    ns = parse(argv)
    if ns.port == 8799:
        raise SystemExit("8799 는 팀 브리지 자리예요 — 다른 포트를 쓰세요 (기본 8815)")
    t0 = time.time()
    target = Target.open(ns.repo)
    stamp = C.stamp()
    run_dir = C.OUT / f"{stamp}_{ns.tier}_{target.label.replace('@', '_')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    budget = DEFAULT_BUDGET[ns.tier] if ns.budget is None else ns.budget
    decks = [d.strip() for d in ns.decks.split(",") if d.strip()]
    C.note(f"qa_verify {ns.tier} · 대상 {target.repo} ({target.label}{', 변경 있음' if target.dirty else ''}) · 결과 {run_dir.name}")
    metrics: dict[str, dict] = {}
    cases: list[dict] = []
    scope_decks: list[str] = []
    tracks: list[str] = []
    llm_calls = 0
    if ns.tier == "quick" or not ns.skip_quick:
        C.note("── quick: pytest · node · 회귀 사례 · 결정적 재생 · 가드 감사")
        qm, cases, qd = quick.run(target, run_dir, decks if ns.tier == "quick" else None)
        metrics.update(qm)
        if ns.tier == "quick":
            scope_decks, tracks = qd["decks"], qd["tracks"]
        _print_quick(qm, cases)
    if ns.tier in ("standard", "full"):
        from . import llm_tier

        lm, info = llm_tier.run(target, run_dir, ns, budget)
        metrics.update(lm)
        scope_decks, tracks, llm_calls = info["decks"], info["tracks"], info["llm_calls"]
    meta = dict(target.meta(), tier=ns.tier, stamp=stamp, dir=run_dir.name, decks=scope_decks, tracks=tracks,
                budget=budget, llm_calls=llm_calls, sec=round(time.time() - t0, 1))
    baseline = S.find_baseline(ns.baseline, meta)
    board = S.assemble(meta, metrics, cases, baseline)
    C.write_json(run_dir / "scoreboard.json", board)
    (run_dir / "scoreboard.md").write_text(S.to_markdown(board), encoding="utf-8")
    if not ns.no_record:
        S.record(board)
    _print_summary(board, run_dir)
    return board["exit_code"]


def _print_quick(qm: dict, cases: list[dict]) -> None:
    ok = sum(c["status"] == "pass" for c in cases)
    C.note(f"   pytest {qm['quick.pytest.passed']['value']} 통과 · 실패 {qm['quick.pytest.failed']['value']} · "
           f"node 실패 {qm['quick.node.failed']['value']} · 회귀 사례 {ok}/{len(cases)} · {qm['quick.sec']['value']}s")
    for c in cases:
        if c["status"] != "pass":
            C.note(f"   ✗ {c['id']} [{c['status']}] {c.get('detail', '')[:140]}")


def _print_summary(board: dict, run_dir: Path) -> None:
    rows = board["metrics"]
    bad = [k for k, r in rows.items() if r["status"] == "fail"]
    C.note(f"── 점수판 {run_dir.relative_to(C.HARNESS_ROOT)}/scoreboard.md")
    C.note(f"   기준 못 넘음 {len(bad)} · 회귀 {len(board['regressions'])} · 회귀 사례 실패 {len(board['failed_cases'])}"
           f" · 기준선 {board['meta'].get('baseline_label') or '없음'}")
    for k in board["regressions"]:
        r = rows[k]
        C.note(f"   ↓ {k}: {S.fmt(r.get('baseline'), r['unit'])} → {S.fmt(r.get('value'), r['unit'])} ({r['label']})")
    C.note(f"   exit {board['exit_code']}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
