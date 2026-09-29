"""
quick 단계 — LLM 0콜, 3분 안. 대상 저장소의 pytest·node 스모크 + 회귀 사례 + 벤치 캐시 결정적 재생 + 판정 가드 감사.

다섯을 스레드로 같이 돌린다 (각각 따로 프로세스라 대상 코드가 섞이지 않는다).
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import common as C
from . import scoreboard as S
from .target import Target, bench_name

#: 벤치 캐시에서 가드 감사를 돌릴 트랙 — 5분 트랙이면 덱마다 질문 3~4개라 40초 안쪽이다.
GUARD_TRACKS = ("5",)
REPLAY_TRACKS = ("5", "10")


def parse_pytest(text: str) -> tuple[int, int, int, str]:
    """마지막 요약 줄 → (passed, failed, errors, 줄). scripts/chk_lib/gate.py 와 같은 읽기."""
    for line in reversed((text or "").strip().splitlines()):
        if " passed" in line or " failed" in line or " error" in line:
            num = lambda pat: int(m.group(1)) if (m := re.search(pat, line)) else 0  # noqa: E731
            return num(r"(\d+) passed"), num(r"(\d+) failed"), num(r"(\d+) errors?"), line.strip()
    lines = (text or "").strip().splitlines()
    return 0, 0, 1, lines[-1] if lines else "(출력 없음)"


def run_pytest(t: Target, run_dir: Path) -> dict:
    r = C.run([t.python, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider", "--no-header"],
              cwd=t.repo, env={"PYTHONDONTWRITEBYTECODE": "1"}, timeout=600)
    (run_dir / "pytest.log").write_text((r.stdout or "") + (r.stderr or ""), encoding="utf-8")
    passed, failed, errors, line = parse_pytest((r.stdout or "") + (r.stderr or ""))
    fails = [ln for ln in (r.stdout or "").splitlines() if ln.startswith(("FAILED", "ERROR"))][:5]
    return {"passed": passed, "failed": failed + errors + (1 if r.returncode not in (0, 1, 5) else 0), "line": line,
            "examples": fails or ([line] if failed or errors else [])}


def run_node(t: Target, run_dir: Path) -> dict:
    smokes = sorted((t.repo / "tests" / "js").glob("*.smoke.mjs"))
    passed = failed = 0
    lines, examples = [], []
    for s in smokes:
        r = C.run(["node", str(s)], cwd=t.repo, timeout=120)
        last = (r.stdout.strip().splitlines() or ["(출력 없음)"])[-1]
        m = re.search(r"(\d+) passed, (\d+) failed", last)
        p, f = (int(m.group(1)), int(m.group(2))) if m else (0, 1 if r.returncode else 0)
        if r.returncode and not f:
            f = 1
        passed += p
        failed += f
        lines.append(f"{s.name}: {last}")
        if f:
            examples.append(f"{s.name}: {' / '.join(C.tail(r.stdout + r.stderr, 4))}")
    (run_dir / "node.log").write_text("\n".join(lines), encoding="utf-8")
    return {"passed": passed, "failed": failed, "examples": examples, "n": len(smokes)}


def run(t: Target, run_dir: Path, decks: list[str] | None = None) -> tuple[dict[str, dict], list[dict], dict]:
    """→ (지표, 회귀 사례 행, 세부)."""
    t0 = time.time()
    bench = [bench_name(d) for d in decks] if decks else None
    cache = str(C.BENCH_CACHE)
    jobs = {
        "pytest": lambda: run_pytest(t, run_dir),
        "node": lambda: run_node(t, run_dir),
        "regress": lambda: t.probe("regress", {}, timeout=300, log=run_dir / "regress.log"),
        "replay": lambda: t.probe("replay", {"cache": cache, "decks": bench, "tracks": list(REPLAY_TRACKS)},
                                  timeout=600, log=run_dir / "replay.log"),
        "guard": lambda: t.probe("guard", {"cache": cache, "decks": bench, "tracks": list(GUARD_TRACKS)},
                                 timeout=600, log=run_dir / "guard.log"),
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futs = {k: ex.submit(fn) for k, fn in jobs.items()}
        res = {k: f.result() for k, f in futs.items()}
    metrics: dict[str, dict] = {}
    py, node = res["pytest"], res["node"]
    metrics["quick.pytest.failed"] = S.metric(py["failed"], None, py["examples"])
    metrics["quick.pytest.passed"] = S.metric(py["passed"], None, [py["line"]])
    metrics["quick.node.failed"] = S.metric(node["failed"], node["n"], node["examples"])
    metrics["quick.node.passed"] = S.metric(node["passed"], node["n"])
    cases = (res["regress"] or {}).get("cases") or []
    if not res["regress"].get("ok"):
        cases = [{"id": "regress_runner", "status": "fail", "detail": res["regress"].get("error", ""), "source": "-"}]
    metrics["quick.cases.failed"] = S.metric(sum(c["status"] == "fail" for c in cases), len(cases),
                                             [f"{c['id']}: {c.get('detail', '')}" for c in cases if c["status"] == "fail"])
    metrics["quick.cases.skipped"] = S.metric(sum(c["status"] == "skip" for c in cases), len(cases),
                                              [f"{c['id']}: {c.get('detail', '')}" for c in cases if c["status"] == "skip"])
    for key in ("replay", "guard"):
        got = res[key] or {}
        if got.get("ok"):
            metrics.update(got.get("metrics") or {})
        else:
            metrics[f"{key}.errors"] = S.metric(1, None, [got.get("error", "?")] + (got.get("tail") or [])[-3:])
    C.write_json(run_dir / "quick_detail.json", {k: v for k, v in res.items() if k in ("replay", "guard")})
    metrics["quick.sec"] = S.metric(round(time.time() - t0, 1))
    detail = {"decks": (res["replay"] or {}).get("decks") or [], "tracks": list(REPLAY_TRACKS)}
    return metrics, cases, detail
