"""
lora+solar 의 올림 문턱(ALIGN_LORA_ESCALATE_BELOW) 고르기 — **dev 세트**의 개념 단위 결과로만 고른다(시험 세트를 보고 고르지 않는다).

문턱 τ 마다: 올리는 비율 · 남긴(LoRA 그대로) 것의 정확도 · 올린 것의 LoRA 정확도.
고르는 규칙: 남긴 것의 정확도가 target 이상인 가장 낮은 τ (올림을 최소로).

  python calibrate.py --tag r1 --target 0.95
"""

from __future__ import annotations

import argparse
import json

from common import RUN, read_jsonl


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--set", default="dev")
    ap.add_argument("--target", type=float, default=0.95)
    args = ap.parse_args()
    rows = read_jsonl(RUN / "eval" / args.tag / f"items_{args.set}.jsonl")
    out, pick = [], None
    for tau in [x / 100 for x in range(40, 100, 5)]:
        kept = [r for r in rows if r["confidence"] >= tau and r["ok"]]
        esc = [r for r in rows if not (r["confidence"] >= tau and r["ok"])]
        acc_k = sum(r["verdict"] == r["gold"] for r in kept) / max(1, len(kept))
        acc_e = sum(r["verdict"] == r["gold"] for r in esc) / max(1, len(esc))
        out.append({"tau": tau, "escalate_share": round(len(esc) / max(1, len(rows)), 3),
                    "kept_acc": round(acc_k, 3), "escalated_lora_acc": round(acc_e, 3)})
        if pick is None and acc_k >= args.target:
            pick = tau
    rep = {"set": args.set, "n": len(rows), "target": args.target, "pick": pick, "sweep": out}
    (RUN / "eval" / args.tag / "calibration.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
