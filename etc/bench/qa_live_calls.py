#!/usr/bin/env python3
"""
발표를 들으며 준비 — 호출 수 · 429 · 토큰 집계 (호출 로그 jsonl). 시각 구간과 기능으로 거른다.

    .venv/bin/python etc/bench/qa_live_calls.py /data/models/_runs/wt-qa-live/calllog --since 13:00 --until 14:00 [--route /api/v1/qa/live]
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--since", default="00:00")
    ap.add_argument("--until", default="24:00")
    ap.add_argument("--route", default="")
    ap.add_argument("--day", default="2026-10-17")
    a = ap.parse_args()
    rows = collections.defaultdict(lambda: {"n": 0, "ok": 0, "429": 0, "in": 0, "out": 0})
    for f in sorted((Path(a.root) / a.day).glob("*.jsonl")):
        for line in f.open(encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            t = (r.get("request") or {}).get("time_kst", "")[11:16]
            if not (a.since <= t < a.until):
                continue
            if a.route and (r.get("request_scope") or {}).get("route") != a.route:
                continue
            k = (r.get("feature_code") or f.stem, (r.get("request") or {}).get("model_label") or "?")
            x = rows[k]
            x["n"] += 1
            x["ok"] += bool(r.get("ok"))
            x["429"] += (r.get("response") or {}).get("status") == 429
            u = ((r.get("response") or {}).get("summary") or {}).get("usage") or {}
            x["in"] += int(u.get("prompt_tokens") or 0)
            x["out"] += int(u.get("completion_tokens") or 0)
    print(f"{'기능':12s} {'모델':42s} {'호출':>5s} {'성공':>5s} {'429':>4s} {'입력토큰':>9s} {'출력토큰':>8s}")
    for (feat, model), x in sorted(rows.items()):
        print(f"{feat:12s} {model[:42]:42s} {x['n']:5d} {x['ok']:5d} {x['429']:4d} {x['in']:9d} {x['out']:8d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
