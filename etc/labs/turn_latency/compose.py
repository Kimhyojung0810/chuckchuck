#!/usr/bin/env python3
"""
말 끝 → 다음 말 첫 글자 합성 (2026-10-17 tune) — 화면 쪽 기다림(말 끝 판단 + 초읽기, 결정적)과 판정 쪽 시간(판정 + 엔진, 실험 판에서 잰
분포)을 턴마다 합친다. 미리 판정이 있으면 판정은 보내기보다 lead 초 먼저 시작한다:

    다음 말 = max(보내기, 미리 판정 시작 + 판정 시간) + 화면 그리기(--render)      ← 말 끝(eos) 기준
    진짜 말 끝 기준 = 위 + A.X eos 늦음(α, stt_trace 실측 p50 0.70초)

판정 시간은 qa_dialogue_bench 판의 행 `sec`(judge_answer 전체 = 판정 LLM + 엔진 기다림). 실 브라우저 실험실(run.py) 수치와 같이 본다.

    python etc/labs/turn_latency/compose.py --runs B1@0,L1@0 --out /data/models/_runs/wt-qa-tune
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TICK = 0.3
PRESETS = {
    # 이름: (말 끝 침묵(종결어미 문장) 초, 초읽기 초, 미리 판정 시점: none | quiet | final)
    "지금 기본(5단계)": (2.2, 3.0, "none"),
    "기본 + 미리 판정(초읽기 때) [이번 기본값]": (2.2, 3.0, "quiet"),
    "권고안 ending 1.8 + 1.4 + 문장 확정 때 미리 판정": (1.8, 1.4, "final"),
    "fast 0.9 + 1.2 + 문장 확정 때": (0.9, 1.2, "final"),
}


def rows_of(out: Path, tag: str) -> list[dict]:
    base, rep = (tag.split("@") + [None])[:2]
    rows = []
    for f in sorted((out / "runs" / base).glob("*.jsonl")):
        rows += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = [r for r in rows if rep is None or str(r.get("rep")) == rep]
    return [r for r in rows if r.get("sec") and r.get("verdict") != "error" and not r.get("coach_stage")]


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * len(xs)))], 2) if xs else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--out", default="/data/models/_runs/wt-qa-tune")
    ap.add_argument("--render", type=float, default=0.1)
    ap.add_argument("--alpha", type=float, default=0.70)
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    report = {}
    for tag in args.runs.split(","):
        secs = [r["sec"] for r in rows_of(Path(args.out), tag)]
        row = {"n": len(secs), "judge_p50": pct(secs, .5), "judge_p90": pct(secs, .9)}
        for name, (sil, cd, spec) in PRESETS.items():
            send = sil + cd + TICK / 2
            lead = {"none": 0.0, "quiet": cd, "final": sil + cd}[spec]
            nxt = [max(send, send - lead + s) + args.render for s in secs]
            row[name] = {"eot_to_send": round(send, 2), "eot_to_next_p50": pct(nxt, .5), "eot_to_next_p90": pct(nxt, .9),
                         "true_end_to_next_p50": round(pct(nxt, .5) + args.alpha, 2)}
        report[tag] = row
    txt = json.dumps(report, ensure_ascii=False, indent=1)
    print(txt)
    if args.json:
        Path(args.json).write_text(txt, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
