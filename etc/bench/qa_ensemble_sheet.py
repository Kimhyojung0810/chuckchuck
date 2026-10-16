#!/usr/bin/env python3
"""
사람 라벨 시트 — 앙상블 실험의 질문을 **가린 채**(어느 방식·어느 모델인지 숨김) 사람이 핵심성을 매기게 한다. rubric_human_sheet.py 와 같은 결.

    python etc/bench/qa_ensemble_sheet.py sheet RUN_DIR --decks A1,C1,sleep,invest,pitch --out sheet.csv [--per-deck 20]
        → 덱 · 번호 · 발표의 핵심 주장 · 질문 · 모범답 + 빈칸(human_core 1~5 · human_open_book 0/1 · human_micro 0/1 ·
          human_transplant 0/1 · human_note). 숨은 열(_set · _author · _llm_core)은 맨 뒤 — 매길 때 가린다.
    python etc/bench/qa_ensemble_sheet.py agree sheet.csv [--label human|claude]
        → 심판단 core 와 사람(또는 Claude) 라벨의 순위 상관(Spearman) · ±1 일치율 · 세트별 사람 평균.

라벨 기준(§0-1 시험): core 5 = 잘 답하려면 자료의 핵심 논리를 이해해야 한다 · 1 = 자료를 외우거나 찾아 읽기만 해도 답한다.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "main"), str(ROOT / "etc"), str(ROOT)]

from bench.qa_ensemble_report import judged  # noqa: E402

LABELS = ("core", "open_book", "micro", "transplant", "note")


def build(run_dir: Path, decks: list[str], per_deck: int, seed: int = 17) -> list[dict]:
    rows = []
    for deck in decks:
        items = []
        for f in sorted(run_dir.glob(f"{deck}-r*.json")):
            run = json.loads(f.read_text(encoding="utf-8"))
            ans = {}
            for q in (run.get("release") or {}).get("questions", []):
                ans[q["question"]] = q.get("answer_gist", "")
            for c in (run.get("ensemble") or {}).get("five", []):
                ans[c["question"]] = c.get("answer", "")
            for fl in (run.get("flows") or {}).values():
                for k in ("q3", "q4"):
                    if (fl.get(k) or {}).get("question"):
                        ans[fl[k]["question"]] = fl[k].get("answer", "")
            thesis = ""
            for k, j in judged(run).items():
                items.append({"deck": deck, "rep": run["rep"], "question": j["question"], "answer": ans.get(j["question"], ""),
                              "_set": j["set"], "_author": j.get("author") or "", "_llm_core": j.get("core")})
        seen, uniq = set(), []
        for it in items:
            if it["question"] not in seen:
                seen.add(it["question"])
                uniq.append(it)
        rng = random.Random(f"{seed}:{deck}")
        rng.shuffle(uniq)
        rows += uniq[:per_deck]
    for i, r in enumerate(rows, 1):
        r["no"] = i
    return rows


def write(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["no", "deck", "question", "answer"] + [f"human_{k}" for k in LABELS] + ["_set", "_author", "_llm_core", "rep"]
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, **{f"human_{k}": "" for k in LABELS}})


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return round(num / den, 3) if den else None


def agree(path: Path, label: str) -> dict:
    with path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    col = f"{label}_core"
    pairs = [(float(r[col]), float(r["_llm_core"])) for r in rows if r.get(col, "").strip() and r.get("_llm_core", "").strip()]
    by_set: dict = {}
    for r in rows:
        if r.get(col, "").strip():
            by_set.setdefault(r["_set"], []).append(float(r[col]))
    return {"n": len(pairs), "spearman": spearman([a for a, _ in pairs], [b for _, b in pairs]),
            "within1": round(sum(1 for a, b in pairs if abs(a - b) <= 1) / len(pairs), 3) if pairs else None,
            "label_mean_by_set": {k: round(st.mean(v), 3) for k, v in by_set.items()}}


def main() -> int:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("sheet")
    a.add_argument("run_dir", type=Path)
    a.add_argument("--decks", default="A1,C1,sleep,invest,pitch")
    a.add_argument("--per-deck", type=int, default=20)
    a.add_argument("--out", type=Path, required=True)
    b = sp.add_parser("agree")
    b.add_argument("sheet", type=Path)
    b.add_argument("--label", default="human")
    args = ap.parse_args()
    if args.cmd == "sheet":
        rows = build(args.run_dir, args.decks.split(","), args.per_deck)
        write(rows, args.out)
        print(f"시트 {len(rows)}행 → {args.out}")
    else:
        print(json.dumps(agree(args.sheet, args.label), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
