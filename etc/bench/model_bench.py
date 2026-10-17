"""
모델 나눠 맡기기 벤치 — Q&A 질문(F-08)의 1차 심사(triage)·질문 문장(phrase)을 어느 모델에 맡길지 잰다.

    python etc/bench/model_bench.py health                         # 모델마다 작은 JSON 호출 한 번 (살았나 · 몇 초 · JSON)
    python etc/bench/model_bench.py qa --bundle-dir DIR            # 기본 조합 5개 × 번들 × 2회
    python etc/bench/model_bench.py qa --bundle-dir DIR --configs solar/solar,solar/exaone --reps 1
    python etc/bench/model_bench.py report --run DIR               # LLM 없이 이미 잰 결과로 표만 다시
    ... --ledger                                                   # 표를 etc/bench/results/ledgers/MODEL_LEDGER.md 끝에 붙인다

조합은 `triage/phrase` (예: `solar/exaone` = 1차 심사 Solar · 질문 문장 EXAONE). **판정(F-09)·rubric 심사관은 solar 로 고정**한다 —
각 모델이 자기 질문을 채점하지 않게. 판정 모델을 재려면 `triage/phrase@judge` (예: `solar/exaone@midm` — 판정만 Mi:dm,
rubric 심사관은 그대로 solar). 판정 조합은 질문 품질(rubric)을 다시 매기지 않는다 — 판정은 질문을 바꾸지 않는다. 측정 자체는 `qa_eval.py` 를 그대로 부른다 (같은 지표 · 같은 코드 가드).
결과 원문(질문 문장 — 자료 본문이 든다)은 `--out`(기본 /data/models/_runs/qa-route/bench) 아래에만 남고 저장소에는 표만 들어간다.

실 LLM 을 부른다 (.env, 과금). mock 으로 재지 않는다 (CLAUDE.md §2).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path[:0] = [str(ROOT / "main"), str(ROOT / "etc"), str(ROOT)]

LEDGER = ROOT / "etc" / "bench" / "results" / "ledgers" / "MODEL_LEDGER.md"
LEDGER_MARK = "<!-- model_bench rows: 이 줄 아래에 model_bench.py --ledger 가 붙인다 -->"
DEFAULT_OUT = Path(os.environ.get("MODEL_BENCH_OUT", "/data/models/_runs/qa-route/bench"))
DEFAULT_CONFIGS = "solar/solar,ax/ax,exaone/exaone,solar/ax,solar/exaone"
JUDGE = "solar"


def _slug(cfg: str) -> str:
    return cfg.replace("/", "-").replace("+", "_").replace("@", "_j")


def _split_cfg(cfg: str) -> tuple[str, str, str]:
    """`triage/phrase[@judge]` → (triage, phrase, judge). judge 를 안 적으면 JUDGE(solar)."""
    body, _, judge = cfg.partition("@")
    triage, phrase = body.split("/", 1)
    return triage, phrase, (judge or JUDGE)


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

def cmd_health(args) -> int:
    from pipeline.config import load_dotenv

    load_dotenv()
    from pipeline.providers.llm_impl import health_rows

    rows = health_rows()
    stamp = time.strftime("%Y-%m-%d %H:%M")
    for r in rows:
        if r["status"] == "live":
            print(f"  {r['model']:<7} live   {r['sec']:>5.2f}s JSON {'O' if r['json_ok'] else 'X'}  {r['out'][:40]}")
        else:
            print(f"  {r['model']:<7} BROKEN {r['sec']:>5.2f}s  {r['error'][:90]}")
    if args.ledger:
        cells = " · ".join(f"{r['model']} {'live' if r['status'] == 'live' else 'broken'} {r['sec']}s"
                           + ("" if r["status"] == "live" else f" ({_short_err(r['error'])})") for r in rows)
        _append_ledger([f"| {stamp} | health | {cells} | {_head()} |"])
    return 0 if all(r["status"] == "live" for r in rows if r["model"] != "midm") else 1


def _short_err(err: str) -> str:
    for code in ("401", "403", "404", "429", "500", "502", "503", "504"):
        if f" {code}" in err:
            return code
    return err[:40].replace("|", "/")


# ---------------------------------------------------------------------------
# qa — qa_eval.py 를 조합 × 반복으로 부른다
# ---------------------------------------------------------------------------

def _done(run_dir: Path, tag: str, bundle: Path) -> bool:
    return any(not p.name.endswith(".raw.json") for p in run_dir.glob(f"*_{tag}_{bundle.stem}.json"))


def _run_one(cfg: str, rep: int, bundle: Path, args, run_dir: Path) -> tuple[str, int, int]:
    triage, phrase, judge = _split_cfg(cfg)
    tag = f"{_slug(cfg)}-r{rep}"
    if _done(run_dir, tag, bundle):
        return f"{tag} {bundle.stem}", 0, 0
    log = run_dir / f"{tag}_{bundle.stem}.log"
    cmd = [sys.executable, str(ROOT / "etc" / "bench" / "qa_eval.py"),
           "--bundle", str(bundle), "--track", args.track, "--limit", str(args.limit),
           "--llm", phrase, "--triage-llm", triage, "--judge-llm", judge,
           "--no-coach", "--fresh-triage", "--tag", tag, "--out-dir", str(run_dir)]
    if not args.no_rubric and judge == JUDGE:
        cmd += ["--rubric", "--rubric-llm", JUDGE, "--rubric-runs", str(args.rubric_runs)]
    t0 = time.time()
    with log.open("w", encoding="utf-8") as f:
        code = subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=str(ROOT))
    return f"{tag} {bundle.stem}", code, int(time.time() - t0)


def cmd_qa(args) -> int:
    if (os.environ.get("MOCK_EXTERNAL_APIS") or "").lower() in ("1", "true", "yes"):
        raise SystemExit("MOCK 으로는 재지 않아요 (CLAUDE.md §2)")
    bundles = sorted(Path(args.bundle_dir).glob("*.json"))
    if not bundles:
        raise SystemExit(f"번들이 없어요: {args.bundle_dir} — etc/bench/build_deck_bundle.py --booth --out DIR")
    run_dir = args.resume or (args.out / time.strftime("%Y%m%d-%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    # 조합을 번갈아 돌린다 — 한 제공자에 몰지 않는다. 판정·심사관(solar)은 모든 일이 같이 쓰므로 동시 실행은 낮게 둔다:
    # 10-16 첫 실행에서 5개를 동시에 돌렸더니 Upstage 429(요청 한도)가 났다 — 같은 키를 서비스(8799)도 쓴다.
    jobs = [(c, r, b) for r in range(1, args.reps + 1) for b in bundles for c in configs]
    print(f"번들 {len(bundles)}개 × 조합 {len(configs)}개 × {args.reps}회 → {run_dir} (동시 {args.parallel})", flush=True)
    with ThreadPoolExecutor(max_workers=args.parallel) as ex:
        for tag, code, sec in ex.map(lambda j: _run_one(j[0], j[1], j[2], args, run_dir), jobs):
            print(f"  {tag:<48} {'ok' if code == 0 else f'EXIT {code}'} {sec}s", flush=True)
    table = report(run_dir, configs)
    print(table)
    if args.ledger:
        _append_ledger(ledger_rows(run_dir, configs, len(bundles), args.reps))
    return 0


# ---------------------------------------------------------------------------
# 집계
# ---------------------------------------------------------------------------

def _pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return round(xs[max(0, min(len(xs) - 1, int(round(q * (len(xs) - 1)))))], 1)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def _frac(rows, key):
    hit = tot = 0
    for r in rows:
        v = (r["summary"].get("judge") or {}).get(key, "-")
        if isinstance(v, str) and "/" in v:
            a, b = v.split("/")
            hit, tot = hit + int(a), tot + int(b)
    return f"{hit}/{tot}" if tot else "-"


def aggregate(run_dir: Path, cfg: str) -> dict:
    rows = []
    for p in sorted(run_dir.glob(f"*_{_slug(cfg)}-r*_*.json")):
        if p.name.endswith((".raw.json", ".corpus.json")):
            continue
        rows.append(json.loads(p.read_text(encoding="utf-8")))
    if not rows:
        return {"config": cfg, "runs": 0}
    qs = [q for r in rows for q in r["questions"]]
    calls = [c for r in rows for c in r["calls"]]
    f08 = [c for c in calls if c.get("role") in ("triage", "phrase")]
    rub = [r["summary"].get("rubric") or {} for r in rows]
    rub_n = sum(x.get("n") or 0 for x in rub)
    overall = [x.get("overall_mean") for x in rub for _ in range(x.get("n") or 0) if x.get("overall_mean") is not None]
    depth = [x.get("depth_mean") for x in rub for _ in range(x.get("n") or 0) if x.get("depth_mean") is not None]
    rel = [x.get("relevance_mean") for x in rub for _ in range(x.get("n") or 0) if x.get("relevance_mean") is not None]

    def role_secs(role):
        return [c["sec"] for c in calls if c.get("role") == role]

    answered = sorted({c.get("model") for c in calls if c.get("role") == "phrase"})
    return {
        "config": cfg, "runs": len(rows), "questions": len(qs),
        "specificity": _mean([q["specificity"] for q in qs]),
        "grounding": _mean([q["grounding"] for q in qs]),
        "template_fallback": sum(1 for q in qs if q["fallback"]),
        "impolite": sum(1 for q in qs if q["impolite"]),
        "honorifics": sum(q["honorifics"] for q in qs),
        "traps": sum(1 for q in qs if q["trap"]),
        "rubric_overall": _mean(overall), "rubric_depth": _mean(depth), "rubric_relevance": _mean(rel), "rubric_n": rub_n,
        "hallucination": sum(x.get("hallucination") or 0 for x in rub),
        "gist_passed": _frac(rows, "gist_passed"), "unrelated_wrong": _frac(rows, "unrelated_wrong"),
        "trap_agree_wrong": _frac(rows, "trap_agree_wrong"), "trap_fixed_passed": _frac(rows, "trap_fixed_passed"),
        "json_fail": f"{sum(1 for c in f08 if c.get('json_ok') is False)}/{sum(1 for c in f08 if c.get('json_ok') is not None)}",
        "errors": sum(1 for c in f08 if c.get("error")),
        "f08_p50": _pct([r["summary"].get("f08_sec") for r in rows], 0.5),
        "f08_p95": _pct([r["summary"].get("f08_sec") for r in rows], 0.95),
        "triage_p50": _pct(role_secs("triage"), 0.5), "phrase_p50": _pct(role_secs("phrase"), 0.5),
        "phrase_p95": _pct(role_secs("phrase"), 0.95),
        "judge_p50": _pct(role_secs("judge"), 0.5), "judge_p95": _pct(role_secs("judge"), 0.95),
        "judge_json_fail": (f"{sum(1 for c in calls if c.get('role') == 'judge' and c.get('json_ok') is False)}/"
                            f"{sum(1 for c in calls if c.get('role') == 'judge' and c.get('json_ok') is not None)}"),
        "judge_errors": sum(r["summary"].get("judge_errors") or 0 for r in rows),
        "judge_answered_by": ",".join(sorted({c.get("model") or "" for c in calls if c.get("role") == "judge"} - {""})),
        "tokens_per_f08": (round(sum((c.get("prompt_tokens") or 0) + (c.get("completion_tokens") or 0) for c in f08) / len(rows))
                           if rows else None),
        "completion_tokens_per_f08": round(sum(c.get("completion_tokens") or 0 for c in f08) / len(rows)) if rows else None,
        "phrase_answered_by": ",".join(m for m in answered if m),
    }


COLS = [("config", "조합 triage/phrase"), ("runs", "n(번들×회)"), ("questions", "질문"), ("specificity", "특이도"),
        ("grounding", "인용률"), ("rubric_overall", "rubric"), ("rubric_depth", "깊이"), ("rubric_relevance", "관련"),
        ("hallucination", "환각"), ("template_fallback", "템플릿"), ("impolite", "반말"), ("traps", "함정"),
        ("trap_agree_wrong", "함정동의→wrong"), ("trap_fixed_passed", "함정정정→통과"), ("gist_passed", "골자→통과"),
        ("json_fail", "JSON실패"), ("errors", "오류"), ("f08_p50", "F-08 p50(s)"), ("f08_p95", "p95"),
        ("phrase_p50", "문장 p50"), ("tokens_per_f08", "토큰/F-08"),
        ("judge_answered_by", "판정 모델"), ("judge_p50", "판정 p50"), ("judge_json_fail", "판정 JSON실패"), ("judge_errors", "판정 오류")]


def report(run_dir: Path, configs: list[str]) -> str:
    aggs = [aggregate(run_dir, c) for c in configs]
    (run_dir / "aggregate.json").write_text(json.dumps(aggs, ensure_ascii=False, indent=1), encoding="utf-8")
    head = "| " + " | ".join(h for _, h in COLS) + " |"
    sep = "|" + "---|" * len(COLS)
    lines = [head, sep]
    for a in aggs:
        lines.append("| " + " | ".join(str(a.get(k, "-")) if a.get(k) is not None else "-" for k, _ in COLS) + " |")
    table = "\n".join(lines)
    (run_dir / "table.md").write_text(table + "\n", encoding="utf-8")
    return table


def ledger_rows(run_dir: Path, configs: list[str], n_bundles: int, reps: int) -> list[str]:
    stamp = time.strftime("%Y-%m-%d %H:%M")
    rows = []
    for c in configs:
        a = aggregate(run_dir, c)
        if not a.get("runs"):
            continue
        rows.append(
            f"| {stamp} | qa {c} | n={a['runs']} 질문 {a['questions']} · 특이도 {a['specificity']} · 인용률 {a['grounding']} · "
            f"rubric {a['rubric_overall']} · 환각 {a['hallucination']} · 템플릿 {a['template_fallback']} · 함정 {a['traps']} "
            f"(동의→wrong {a['trap_agree_wrong']}, 정정→통과 {a['trap_fixed_passed']}) · JSON실패 {a['json_fail']} · "
            f"F-08 p50 {a['f08_p50']}s p95 {a['f08_p95']}s · 토큰/F-08 {a['tokens_per_f08']} · "
            f"판정 {a['judge_answered_by']} p50 {a['judge_p50']}s JSON실패 {a['judge_json_fail']} 오류 {a['judge_errors']} | {_head()} |"
        )
    return rows


def _head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "?"


def _append_ledger(lines: list[str]) -> None:
    text = LEDGER.read_text(encoding="utf-8") if LEDGER.exists() else ""
    if LEDGER_MARK not in text:
        text = text.rstrip("\n") + f"\n\n## 실행 기록\n\n| 시각 | 무엇 | 결과 | HEAD |\n|---|---|---|---|\n{LEDGER_MARK}\n"
    LEDGER.write_text(text.rstrip("\n") + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"장부에 {len(lines)}줄 붙였어요: {LEDGER.relative_to(ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("health")
    h.add_argument("--ledger", action="store_true")
    q = sub.add_parser("qa")
    q.add_argument("--bundle-dir", type=Path, default=Path("/data/models/_runs/qa-route/bundles"))
    q.add_argument("--configs", default=DEFAULT_CONFIGS)
    q.add_argument("--reps", type=int, default=2)
    q.add_argument("--track", default="10")
    q.add_argument("--limit", type=int, default=3, help="판정에 넣을 질문 수")
    q.add_argument("--rubric-runs", type=int, default=3)
    q.add_argument("--no-rubric", action="store_true")
    q.add_argument("--parallel", type=int, default=2, help="동시 실행 수 (높이면 Upstage 429 — 서비스와 같은 키다)")
    q.add_argument("--resume", type=Path, default=None, help="이 실행 폴더에 이어서 (이미 잰 번들은 건너뛴다)")
    q.add_argument("--out", type=Path, default=DEFAULT_OUT)
    q.add_argument("--ledger", action="store_true")
    r = sub.add_parser("report")
    r.add_argument("--run", type=Path, required=True)
    r.add_argument("--configs", default=DEFAULT_CONFIGS)
    r.add_argument("--ledger", action="store_true")
    args = ap.parse_args()
    if args.cmd == "health":
        return cmd_health(args)
    if args.cmd == "qa":
        return cmd_qa(args)
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    print(report(args.run, configs))
    if args.ledger:
        n_b = len({p.name.rsplit("_", 1)[-1] for p in args.run.glob("*_*-r*_*.json")})
        _append_ledger(ledger_rows(args.run, configs, n_b, 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
