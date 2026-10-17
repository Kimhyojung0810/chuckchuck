"""
파일럿(Fine-Tune/alignment-pilot) 라벨 감사 — 읽기만 한다. 수치는 DATA_CARD.md 에 옮긴다.

본다: silver/review 규모 · 클래스 비 · 보조 표시(partial·asr·guard) · 같은 모델 두 번 일치율 · 발표 출처 · 언어 · 이유 글 언어
"""

from __future__ import annotations

import json
import re
from collections import Counter

from common import PILOT, jdump, read_jsonl, DATA


def main() -> None:
    silver, review = read_jsonl(PILOT / "silver.jsonl"), read_jsonl(PILOT / "review.jsonl")
    for f in sorted((PILOT / "talks").glob("*/silver.jsonl")):
        silver += read_jsonl(f)
    for f in sorted((PILOT / "talks").glob("*/review.jsonl")):
        review += read_jsonl(f)
    talks_done = len(list((PILOT / "talks").glob("*/labeled.done")))
    lab = Counter(r["label"] for r in silver)
    flags = Counter((bool(r.get("partial")), bool(r.get("asr_suspect")), bool(r.get("guard_conflict"))) for r in silver)
    errors = sum(1 for r in review if r.get("error"))
    disagree = [r for r in review if not r.get("error") and r.get("label") != r.get("run2_label")]
    pairs = Counter((r.get("label"), r.get("run2_label")) for r in disagree)
    ko_reason = sum(1 for r in silver if re.search(r"[가-힣]", r.get("reason") or ""))
    out = {
        "silver": len(silver), "review_rows": len(review), "review_errors": errors,
        "self_disagree": len(disagree),
        "self_agree_rate": round(len(silver) / max(1, len(silver) + len(disagree)), 4),
        "labels": dict(lab), "labels_pct": {k: round(v / len(silver), 4) for k, v in lab.items()},
        "flags(partial,asr,guard)": {str(k): v for k, v in flags.items()},
        "disagree_pairs": {f"{a}->{b}": n for (a, b), n in pairs.most_common(10)},
        "talks_with_silver": len({r["talk_id"] for r in silver}), "talks_done": talks_done,
        "source_prefix": dict(Counter(r["talk_id"].split("-")[0] for r in silver)),
        "reason_in_korean": round(ko_reason / max(1, len(silver)), 4),
        "models": dict(Counter(r.get("model") for r in silver)),
    }
    jdump(DATA / "pilot_audit.json", out)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
