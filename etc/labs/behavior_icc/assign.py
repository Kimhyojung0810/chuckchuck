"""코더 배정표 만들기 — 본인 영상은 빼고, 영상마다 비발표자 두 명, 사람마다 12편씩 고르게.

    python3 etc/labs/behavior_icc/assign.py                 # → /data/models/_runs/behavior-icc/배정표.csv + 화면에 사람별 목록
    python3 etc/labs/behavior_icc/assign.py --people 5 --situations 6 --print-only

규칙: 사람 p 의 상황 1~3 은 (p+1, p+2), 상황 4~6 은 (p+3, p+4) 가 코딩한다(5명 기준, 번호는 돌려 셈).
→ 사람마다 12편, 1차 · 2차 자리를 반반, 같은 짝이 6편씩. 훈련 영상(train1, train2)은 모두가 먼저 코딩한다(분석에서 뺌).
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_icc import OUT, SITUATIONS  # noqa: E402


def plan(people: int, situations: int, n_train: int) -> list[dict]:
    if people < 3:
        raise SystemExit("본인을 뺀 코더 두 명이 있으려면 3명 이상이어야 해요")
    rows = []
    half = (situations + 1) // 2
    for t in range(1, n_train + 1):
        rows.append({"clip": f"train{t}", "person": "", "situation": "훈련", "rater_a": "모두", "rater_b": "", "split": "train"})
    for p in range(1, people + 1):
        for c in range(1, situations + 1):
            off = (1, 2) if (c <= half or people < 5) else (3, 4)
            ra = (p - 1 + off[0]) % people + 1
            rb = (p - 1 + off[1]) % people + 1
            rows.append({"clip": f"p{p}_c{c}", "person": f"p{p}", "situation": SITUATIONS.get(c, str(c)),
                         "rater_a": f"p{ra}", "rater_b": f"p{rb}", "split": "eval"})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="코더 배정표")
    ap.add_argument("--people", type=int, default=5)
    ap.add_argument("--situations", type=int, default=6)
    ap.add_argument("--train", type=int, default=2, help="훈련 영상 수")
    ap.add_argument("--out", type=Path, default=OUT / "배정표.csv")
    ap.add_argument("--print-only", action="store_true")
    a = ap.parse_args()
    rows = plan(a.people, a.situations, a.train)
    if not a.print_only:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"→ {a.out}")
    print("\n사람별 코딩할 영상 (먼저 훈련 영상 " + ", ".join(r["clip"] for r in rows if r["split"] == "train") + ")")
    for p in range(1, a.people + 1):
        me = f"p{p}"
        mine = [r["clip"] for r in rows if me in (r["rater_a"], r["rater_b"])]
        print(f"  {me}: {len(mine)}편 — {' '.join(mine)}")


if __name__ == "__main__":
    main()
