#!/usr/bin/env python3
"""
가린 라벨 묶음 (2026-10-17 tune) — 고친 판과 기준선 판을 섞고 출처를 숨긴 표본을 만든다. 라벨은 사람(이번엔 Claude)이 읽고 붙인다.

    python etc/bench/qa_tune_labels.py make --kind premise --tags B1,N2 --n 40     # 틀린 전제 답에 대한 반응 · 꼬리질문
    python etc/bench/qa_tune_labels.py make --kind narrow --tags n0,n3 --n 40      # 「모르겠어요」 1단 되물음 · 보기
    python etc/bench/qa_tune_labels.py score --kind premise                        # labels/<kind>_labels.json 을 열쇠와 맞춰 집계

라벨 파일 꼴: {"P000": {"ok": true, "leak": false}, ...}
- premise.ok : 반응 · 꼬리질문이 **답이 자료와 어긋난 곳**을 짚었나(그 말을 가리키며 자료와 견주게 하나). 연결만 묻거나 칭찬하면 false.
- premise.leak: 자료가 실제로 뭐라고 하는지(값 · 방향 · 정답 문장)를 먼저 말해 버렸나.
- narrow.ok  : 보기(또는 보기 없는 되물음)가 **핵심 논리**(왜 · 어느 근거 · 어디까지)를 고르게 하나. 숫자 · 낱말 조각 · 엉뚱한 쌍이면 false.
- narrow.leak: 되물음 · 보기가 정답을 사실상 말해 버렸나(정답 문장을 그대로 옮김 · 한쪽이 뻔히 자료 문장).
"""
from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path

OUT = Path(os.environ.get("QA_DLG_OUT") or "/data/models/_runs/wt-qa-tune")


def rows_of(tag: str) -> list[dict]:
    rows = []
    for f in sorted((OUT / "runs" / tag).glob("*.jsonl")):
        rows += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    return rows


def make(args) -> int:
    rng = random.Random(1017)
    pool = []
    for tag in args.tags.split(","):
        rows = rows_of(tag)
        if args.kind == "premise":
            rows = [r for r in rows if r.get("kind") == "premise" and r.get("verdict") != "error" and not r.get("coach_stage")]
        else:
            rows = [r for r in rows if r.get("coach_stage") == "narrow" and not r.get("error")]
        rng.shuffle(rows)
        pool += [(tag, r) for r in rows[: args.n]]
    rng.shuffle(pool)
    items, key = {}, {}
    pre = "P" if args.kind == "premise" else "N"
    for i, (tag, r) in enumerate(pool):
        k = f"{pre}{i:03d}"
        key[k] = {"tag": tag, "deck": r["deck"], "qid": r["qid"], "rep": r.get("rep")}
        if args.kind == "premise":
            items[k] = {"question": r["question"], "gist(참고)": r.get("gist"), "answer": r["answer"],
                        "react": r.get("react"), "followup": r.get("followup")}
        else:
            items[k] = {"question": r["question"], "gist(참고)": r.get("gist"), "react": r.get("react"),
                        "followup": r.get("followup"), "choices": r.get("choices")}
    lab = OUT / "labels"
    lab.mkdir(parents=True, exist_ok=True)
    (lab / f"{args.kind}_items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    (lab / f"{args.kind}_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(items)} 표본 → {lab / f'{args.kind}_items.json'} (열쇠는 {args.kind}_key.json — 라벨 다 붙이기 전엔 열지 않는다)")
    return 0


def score(args) -> int:
    lab = OUT / "labels"
    key = json.loads((lab / f"{args.kind}_key.json").read_text(encoding="utf-8"))
    labels = json.loads((lab / f"{args.kind}_labels.json").read_text(encoding="utf-8"))
    by: dict = {}
    for k, v in labels.items():
        tag = key[k]["tag"]
        s = by.setdefault(tag, {"n": 0, "ok": 0, "leak": 0})
        s["n"] += 1
        s["ok"] += bool(v.get("ok"))
        s["leak"] += bool(v.get("leak"))
    for tag, s in by.items():
        s["ok_rate"] = round(s["ok"] / s["n"], 3)
        s["leak_rate"] = round(s["leak"] / s["n"], 3)
    print(json.dumps(by, ensure_ascii=False, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["make", "score"])
    ap.add_argument("--kind", choices=["premise", "narrow"], required=True)
    ap.add_argument("--tags", default="")
    ap.add_argument("--n", type=int, default=40)
    args = ap.parse_args()
    return {"make": make, "score": score}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
