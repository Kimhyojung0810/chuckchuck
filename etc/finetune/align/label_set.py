"""
항목 파일에 큰 한국 LLM 라벨을 붙인다 — Solar · A.X(K2) 각각 한 번(온도 0, 캐시). 결과는 같은 파일 옆 *.labels.jsonl.

  python label_set.py --items items_ko_synth.jsonl --engines solar,ax --workers 6
  python label_set.py --items items_en.jsonl --engines solar          # 영어는 A.X 라벨이 파일럿에 이미 있다
  python label_set.py --items items_ko_real.jsonl --engines solar,ax,midm   # 시험셋 — 셋째 표(Mi:dm Pro API)로 갈린 것을 가린다
"""

from __future__ import annotations

import argparse
from collections import Counter

import hashlib

from common import DATA, pmap, read_jsonl, usage_report, write_jsonl
from labeler import label_item

from pipeline._align_lora import render_user


def item_hash(item: dict) -> str:
    """라벨러가 본 글의 지문 — 항목 그림이 바뀌면(build_item 수정) 옛 라벨을 버리고 다시 묻는다."""
    return hashlib.sha1(render_user(item).encode()).hexdigest()[:16]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--engines", default="solar,ax")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only_cons", action="store_true", help="구성 라벨이 있는 항목만(셋째 표 아끼기)")
    args = ap.parse_args()
    path = DATA / args.items
    rows = read_jsonl(path)
    if args.limit:
        rows = rows[: args.limit]
    out_path = path.with_suffix(".labels.jsonl")
    old = {r["uid"]: r.get("labels", {}) for r in read_jsonl(out_path)}
    for r in rows:
        h = item_hash(r["item"])
        r["labels"] = {k: v for k, v in old.get(r["uid"], {}).items() if v.get("h") == h}
        r["_h"] = h
    for eng in [e.strip() for e in args.engines.split(",") if e.strip()]:
        todo = [r for r in rows if eng not in r["labels"] or not r["labels"][eng].get("label")]
        if args.only_cons and eng not in ("solar", "ax"):
            todo = [r for r in todo if r.get("cons") or _split(r)]

        def run(r, eng=eng):
            return label_item(eng, r["item"])

        res = pmap(run, todo, workers=args.workers, desc=f"label:{eng}", every=100)
        bad = 0
        for r, got in zip(todo, res):
            if isinstance(got, Exception):
                bad += 1
                r["labels"][eng] = {"label": "", "error": f"{type(got).__name__}: {str(got)[:120]}"}
            else:
                r["labels"][eng] = {**got, "h": r["_h"]}
        print(f"[label:{eng}] done={len(todo)} errors={bad} dist={Counter(r['labels'][eng].get('label') for r in rows)}",
              flush=True)
        write_jsonl(out_path, [{k: v for k, v in x.items() if k != "_h"} for x in rows])
    print("[usage]", usage_report())


def _split(r: dict) -> bool:
    """solar·ax 가 갈린 항목."""
    a, b = r["labels"].get("solar", {}).get("label"), r["labels"].get("ax", {}).get("label")
    return bool(a and b and a != b)


if __name__ == "__main__":
    main()
