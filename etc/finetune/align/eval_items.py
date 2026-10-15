"""
개념 단위 평가 — 학습한 LoRA 판정기를 시험 세트에 그대로 돌린다(생성 · 첫 토큰 확신도 · 근거 번호).

  flock /home/yehschuck/.cache/chuckchuck-gpu.lock python eval_items.py --adapter RUN/runs/r1/final --tag r1

지표: 클래스별 P/R/F1 · macro-F1 · 정확도 · JSON 깨짐 · 근거 유효(aligned·contradiction 예측의 sid 가 그 항목 발화 문장인가)
      · 근거 일치(정답 sid 또는 라벨러 sid 와 같은가) · 확신 0.8 이상의 정확도·비율 · 개념당 지연 · 최대 VRAM.
산출: RUN/eval/<tag>/items_<set>.jsonl · items_report.json
"""

from __future__ import annotations

import argparse
import json
import time

from common import DATA, RUN, jdump, read_jsonl, write_jsonl

from pipeline._align_lora import LoraAlignJudge, evidence_valid
from train_lora import macro_f1

SETS = ("test_ko_real", "test_ko_synth", "test_en", "dev")


def report(rows: list[dict], preds: list[dict]) -> dict:
    gold = [r["verdict"] for r in rows]
    pv = [p["verdict"] for p in preds]
    rep = macro_f1(gold, pv)
    quoted = [(r, p) for r, p in zip(rows, preds) if p["verdict"] in ("aligned", "contradiction")]
    rep["evidence_valid"] = round(sum(1 for r, p in quoted if evidence_valid(r["item"], p["sid"], p["evidence"]))
                                  / max(1, len(quoted)), 4)
    both = [(r, p) for r, p in zip(rows, preds) if p["verdict"] == r["verdict"] and r.get("sid")]
    rep["evidence_match"] = round(sum(
        1 for r, p in both if p["sid"] in {r["sid"], *(v.get("sid") for v in r.get("labels", {}).values())})
        / max(1, len(both)), 4)
    rep["json_ok"] = round(sum(1 for p in preds if p["ok"]) / max(1, len(preds)), 4)
    hi = [(g, p) for g, p in zip(gold, preds) if p["confidence"] >= 0.8]
    rep["conf>=0.8"] = {"share": round(len(hi) / max(1, len(preds)), 3),
                        "acc": round(sum(1 for g, p in hi if g == p["verdict"]) / max(1, len(hi)), 3)}
    lo = [(g, p) for g, p in zip(gold, preds) if p["confidence"] < 0.8]
    rep["conf<0.8"] = {"share": round(len(lo) / max(1, len(preds)), 3),
                       "acc": round(sum(1 for g, p in lo if g == p["verdict"]) / max(1, len(lo)), 3)}
    conf = {}
    for g, p in zip(gold, pv):
        conf.setdefault(g, {}).setdefault(p, 0)
        conf[g][p] += 1
    rep["confusion"] = conf
    return rep


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--sets", default=",".join(SETS))
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--sets_dir", default=str(DATA / "sets"))
    args = ap.parse_args()
    import torch

    out = RUN / "eval" / args.tag
    judge = LoraAlignJudge(args.adapter, batch_size=args.batch)
    t0 = time.time()
    judge.load()
    load_s = time.time() - t0
    from common import jload
    full = {**(jload(out / "items_report.json") or {}), "adapter": args.adapter, "load_s": round(load_s, 1)}
    for name in [s for s in args.sets.split(",") if s]:
        from pathlib import Path
        rows = read_jsonl(Path(args.sets_dir) / f"{name}.jsonl")
        if not rows:
            continue
        # 길이 순으로 묶어 패딩을 줄인다(결과는 원래 순서로 돌린다)
        order = sorted(range(len(rows)), key=lambda i: len(json.dumps(rows[i]["item"], ensure_ascii=False)))
        torch.cuda.synchronize()
        t = time.time()
        js = judge.judge_items([rows[i]["item"] for i in order])
        torch.cuda.synchronize()
        el = time.time() - t
        preds = [None] * len(rows)
        for i, j in zip(order, js):
            preds[i] = {"verdict": j.verdict, "sid": j.sid, "evidence": j.evidence, "note": j.note,
                        "confidence": j.confidence, "probs": j.probs, "ok": j.ok, "raw": j.raw}
        write_jsonl(out / f"items_{name}.jsonl", [{"uid": r["uid"], "gold": r["verdict"], "gold_sid": r.get("sid"),
                                                  "lang": r["lang"], "variant": r.get("variant"), **p}
                                                 for r, p in zip(rows, preds)])
        rep = report(rows, preds)
        rep["n"] = len(rows)
        rep["sec_per_item"] = round(el / len(rows), 3)
        if name == "dev":
            for lang in ("ko", "en"):
                sub = [(r, p) for r, p in zip(rows, preds) if r["lang"] == lang]
                if sub:
                    rep[lang] = report([r for r, _ in sub], [p for _, p in sub])
        if name == "test_ko_real":
            for var in sorted({r.get("variant") for r in rows}):
                sub = [(r, p) for r, p in zip(rows, preds) if r.get("variant") == var]
                rep[f"variant:{var}"] = {k: v for k, v in report([r for r, _ in sub], [p for _, p in sub]).items()
                                         if k in ("macro_f1", "acc", "n")} | {"n": len(sub)}
        full[name] = rep
        full["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 1)
        jdump(out / "items_report.json", full)            # 세트마다 — 중간에 끊겨도 앞 세트 결과는 남는다
        print(f"[eval:{name}] n={len(rows)} macroF1={rep['macro_f1']} acc={rep['acc']} ev_valid={rep['evidence_valid']} "
              f"{rep['sec_per_item']}s/item", flush=True)
    full["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 1)
    jdump(out / "items_report.json", full)


if __name__ == "__main__":
    main()
