"""
사람이 고친 습관 판정을 LoRA 재학습용으로 내보낸다 — 문턱을 넘었을 때만 의미가 있다.

    python examples/export_lora_corrections.py            # exports/lora_corrections.jsonl

**무엇이 라벨인가.** 동의 세션에서 사용자가 「이건 반복이 아니에요」 / 「이건 간투어가
아니에요」 를 누른 것(`habit_dispute`)만이다. 태거 자체 출력·침묵·점수는 라벨이 아니다
(docs/DATA_PIPELINE.md §5, docs/PRIVACY.md). 이의는 **음성 라벨**(이 구간은 REP/FIL 이 아님)이라
단독으로는 학습셋이 못 되고 hard negative 로만 쓴다 — 「놓친 반복」 을 표시하는 양성
피드백이 생기면 그때 학습셋이 된다.

**언제 학습하나.** 30세션 이상에서 200건 이상. 그 밑이면 이 스크립트는 파일을 만들되
"아직 학습할 만큼이 아니다" 라고 말한다. 학습은 저장소 밖(`20_AIHub_data/`)에서, AI Hub 데이터와
split 을 분리해서 한다 — 출처·라이선스가 다르다.

출력 한 줄 = 세션 하나:
    {"session_id", "code_version", "stt_text", "model_spans": [{"tag","text","start_sec","end_sec"}],
     "negatives": [{"tag","text","spans":[…]}]}
`stt_text` 는 `_lora_tagger.USER_TEMPLATE` 에 그대로 넣는 전사문, `model_spans` 는 그때 태거가
낸 답(REP/FIL), `negatives` 가 사람이 아니라고 한 것.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from demo.session_archive import SessionArchive  # noqa: E402

DEFAULT_OUT = ROOT / "exports" / "lora_corrections.jsonl"
MIN_SESSIONS = 30
MIN_CORRECTIONS = 200


def rows_for(archive: SessionArchive) -> list[dict]:
    rows = []
    for rec in archive.iter_consented():
        disputes = [e for e in archive.read_stream(rec.session_id, "feedback") if e.get("kind") == "habit_dispute"]
        if not disputes:
            continue
        transcript = archive.read_artifact(rec.session_id, "transcript") or {}
        habits = archive.read_artifact(rec.session_id, "habit_doc") or {}
        rows.append({
            "session_id": rec.session_id,
            "code_version": rec.code_version,
            "provider": habits.get("provider", ""),
            "stt_text": transcript.get("full_text", ""),
            "model_spans": [{"tag": s.get("kind"), "text": s.get("text"), "start_sec": s.get("start_sec"),
                             "end_sec": s.get("end_sec")} for s in habits.get("spans", [])
                            if s.get("kind") in ("REP", "FIL")],
            "negatives": [{"tag": (e.get("payload") or {}).get("kind"), "text": (e.get("payload") or {}).get("text"),
                           "spans": (e.get("payload") or {}).get("spans", [])} for e in disputes],
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=ROOT / "var" / "data")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    rows = rows_for(SessionArchive(args.data_dir))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    corrections = sum(len(r["negatives"]) for r in rows)
    print(f"세션 {len(rows)}건 · 정정 {corrections}건 → {args.out}")
    if len(rows) < MIN_SESSIONS or corrections < MIN_CORRECTIONS:
        print(f"아직 학습할 만큼이 아니에요 (문턱: 세션 {MIN_SESSIONS} · 정정 {MIN_CORRECTIONS}). "
              "그 전까지는 평가의 hard negative 로만 써요.")
    else:
        print("문턱을 넘었어요. 20_AIHub_data/ 쪽 파이프라인에서 AI Hub split 과 분리해 학습하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
