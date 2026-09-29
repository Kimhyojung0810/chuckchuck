"""
감사 실행 결과(labs/qa_convo/out — git 에 안 올라감)에서 보고서가 가리키는 증거만 evidence/ 로 옮긴다.
실행마다: prepared.json(질문 전부) · pipeline_summary.json(정합·채점 결함·리포트·시간 배분·장 구간 — 저장된 세션에서 뽑음).
대화마다: turns.json · q*.md · 보고서가 가리키는 사진만.

    .venv/bin/python "docs/review/2026-09-30_QA_녹음대화감사/tools/collect_evidence.py"
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVID = HERE.parent / "evidence"
OUT = HERE.parents[3] / "labs" / "qa_convo" / "out"
KEEP_PNG = {
    "qa_first.png", "gate.png", "00_entry.png", "99_result.png", "99_report.png",
    "q1_side_speech_01_answer.png", "q1_side_speech_02_answer.png", "q1_side_speech_03_answer.png",
    "q1_typo_claim_01_answer.png", "q1_typo_claim_02_answer.png", "q1_dunno_01_stuck.png", "q1_dunno_02_stuck.png",
    "q1_side_deck_01_answer.png", "q4_literal_then_content_08_answer.png", "q5_premise_follow_then_fix_10_answer.png",
    "q3_short_then_good_01_answer.png", "q1_no_contradiction_claim_01_answer.png", "q2_trap_agree_01_answer.png",
    "q5_trap_agree_04_answer.png",
}
FULLPAGE_ONLY_FOR = ("co2_r1_audio_t10", "bunt_r2_audio_t10", "co2_r3_audio_t10", "co2_r2_audio_t10")


def summary(storage: dict) -> dict:
    nf = json.loads(storage["cheokcheok:new-flow"])
    sess = json.loads(storage["cheokcheok:chuckchuck-session"])
    po = nf.get("pipelineOut") or {}
    al = po.get("alignment") or {}
    labels = {n["id"]: n["label"] for n in (po.get("graph") or {}).get("nodes", [])}
    tr = sess.get("transcript") or {}
    sc = po.get("score") or {}
    return {
        "alignment": {k: al.get(k) for k in ("speech_match", "speech_overlap", "basis", "skipped_slides")}
        | {"items": [{"node_id": it["node_id"], "label": labels.get(it["node_id"]), "verdict": it["verdict"],
                      "decided_by": it.get("decided_by"), "deck_slide_no": it.get("deck_slide_no"),
                      "evidence": it.get("evidence"), "deck_quote": it.get("deck_quote")} for it in al.get("items", [])]},
        "score": {k: sc.get(k) for k in ("score", "cap", "basis", "note", "faults", "unmeasured")},
        "report": po.get("report"),
        "pace": {k: (po.get("pace") or {}).get(k) for k in ("target_sec", "actual_sec", "avg_chars_per_min", "slides", "tips")},
        "transcript_by_slide": [{"slide_no": b.get("slide_no"), "start_sec": b.get("start_sec"), "end_sec": b.get("end_sec"),
                                 "text": b.get("text")} for b in tr.get("by_slide", [])],
        "pipeline_log": nf.get("_pipelineLog"),
    }


def main() -> None:
    for prep in sorted(OUT.glob("2026093*_audit_*")):
        name = prep.name.split("_audit_", 1)[1]
        dst = EVID / name
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(prep / "prepared.json", dst / "prepared.json")
        storage = json.loads((prep / "storage.json").read_text(encoding="utf-8"))
        (dst / "pipeline_summary.json").write_text(json.dumps(summary(storage), ensure_ascii=False, indent=1), encoding="utf-8")
        for png in ("qa_first.png", "gate.png"):
            if (prep / png).exists():
                shutil.copy2(prep / png, dst / png)
        for play in sorted(prep.glob("play_*")):
            pd = dst / play.name
            pd.mkdir(exist_ok=True)
            for f in play.iterdir():
                if f.suffix in (".md", ".json"):
                    shutil.copy2(f, pd / f.name)
                elif f.suffix == ".png" and f.name in KEEP_PNG:
                    if f.name in ("99_report.png",) and name not in FULLPAGE_ONLY_FOR:
                        continue
                    shutil.copy2(f, pd / f.name)
        print(name, "→", dst.relative_to(HERE.parents[3]))


if __name__ == "__main__":
    main()
