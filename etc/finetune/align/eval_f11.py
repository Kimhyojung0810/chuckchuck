"""
F-11 전체 경로 평가 — 지금 서비스의 Solar 판정(align_speech, judge=solar)과 LoRA(lora · lora+solar)를 같은 녹음에 돌려 비교한다.

녹음 = 시험셋의 rec(ko_real 녹음 · ko_synth 시험 덱의 clean/flawed/drop 대본). 정답은 시험 세트의 개념별 정답(assemble.py).
판정기마다 두 가지를 잰다
  raw   : 판정기가 낸 판정 그대로(코드 대조 전)
  final : align_speech 가 돌려준 최종 판정(코드 대조 네 겹 · 폴백 뒤) — 리포트에 실제로 나가는 것
그리고 녹음당 걸린 시간 · Solar 호출 수 · 판정 출처(decided_by) 분포.

  flock /home/yehschuck/.cache/chuckchuck-gpu.lock python eval_f11.py --adapter RUN/runs/r1/final --tag r1
산출: RUN/eval/<tag>/f11_<judge>.jsonl · f11_report.json
"""

from __future__ import annotations

import argparse
import time
from collections import Counter, defaultdict
from pathlib import Path

from common import DATA, RUN, jdump, jload, load_env, read_jsonl, write_jsonl

from train_lora import macro_f1


def recordings(sets: list[str]) -> dict[str, dict]:
    """rec → {graph, slide_doc, transcript, ctx, gold{node_id: verdict}}"""
    out: dict[str, dict] = {}
    real = {r["rec_id"]: r for r in jload(DATA / "ko_real" / "recs.json")}
    for name in sets:
        for row in read_jsonl(DATA / "sets" / f"{name}.jsonl"):
            rec = row.get("rec")
            if not rec:
                continue
            if rec not in out:
                if row["source"] == "ko_real":
                    meta = real[rec]
                    base = DATA / "ko_real" / meta["deck"]
                    out[rec] = {"set": name, "graph": jload(base / "graph.json"), "slide_doc": jload(base / "slide_doc.json"),
                                "transcript": jload(Path(meta["transcript"])), "ctx": meta["ctx"], "gold": {}}
                else:
                    did, var = rec.split(":")
                    base = DATA / "ko_synth" / did
                    spec = jload(base / "deck.json")["spec"]
                    out[rec] = {"set": name, "graph": jload(base / "graph.json"), "slide_doc": jload(base / "slide_doc.json"),
                                "transcript": jload(base / f"transcript_{var}.json"),
                                "ctx": {"situation": spec["situation"], "audience": spec["audience"],
                                        "duration_min": spec["duration_min"]}, "gold": {}}
            out[rec]["gold"][row["item"]["node_id"]] = row["verdict"]
    return out


def counting(inner):
    """Solar 호출 수를 세는 감싸개 — align_speech 가 LLMProvider 인지 본다."""
    from pipeline.providers.llm_base import LLMProvider

    class CountingLLM(LLMProvider):
        def __init__(self):
            self.inner, self.calls, self.name = inner, 0, inner.name

        def complete(self, **kw):
            self.calls += 1
            return self.inner.complete(**kw)

    return CountingLLM()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--judges", default="solar,lora,lora+solar")
    ap.add_argument("--sets", default="test_ko_real,test_ko_synth")
    ap.add_argument("--escalate_below", type=float, default=None)
    args = ap.parse_args()
    load_env()
    import pipeline.f11_align as f11
    from pipeline import _align_lora as lora
    from pipeline.providers.llm_impl import get_llm

    if args.escalate_below is not None:
        f11.LORA_ESCALATE_BELOW = args.escalate_below
    recs = recordings(args.sets.split(","))
    judge = lora.LoraAlignJudge(args.adapter) if args.adapter else None
    out = RUN / "eval" / args.tag
    report: dict = {"recordings": len(recs), "escalate_below": f11.LORA_ESCALATE_BELOW}

    # raw 판정을 가로채 기록한다 — final 과 견주려고
    captured: dict[str, list[dict]] = {}
    orig_solar, orig_lora = f11._solar_raw, f11._lora_raw

    def solar_raw(*a, **k):
        data, raw = orig_solar(*a, **k)
        captured.setdefault("raw", []).extend(raw)
        return data, raw

    def lora_raw(*a, **k):
        raw, name, esc = orig_lora(*a, **k)
        captured.setdefault("raw", []).extend(raw)
        captured["esc"] = list(esc)
        return raw, name, esc

    f11._solar_raw, f11._lora_raw = solar_raw, lora_raw

    for jname in [j for j in args.judges.split(",") if j]:
        if jname != "solar" and judge is None:
            continue
        rows, stats = [], defaultdict(list)
        for rec, r in recs.items():
            eng = counting(get_llm("solar"))
            captured.clear()
            t = time.time()
            try:
                doc = f11.align_speech(r["graph"], r["transcript"], r["ctx"], llm=eng, slide_doc=r["slide_doc"],
                                       judge=jname, lora_judge=judge)
            except Exception as e:  # noqa: BLE001
                print(f"[f11:{jname}] {rec} FAIL {type(e).__name__}: {str(e)[:120]}", flush=True)
                continue
            el = time.time() - t
            raw = {str(x.get("node_id")): x for x in captured.get("raw", [])}
            esc = set(captured.get("esc", []))
            stats["sec"].append(el)
            stats["solar_calls"].append(eng.calls)
            stats["escalated"].append(len(esc))
            for it in doc.items:
                if it.node_id not in r["gold"]:
                    continue
                rv = raw.get(it.node_id, {}).get("verdict", "")
                rows.append({"rec": rec, "set": r["set"], "node_id": it.node_id, "gold": r["gold"][it.node_id],
                             "final": it.verdict, "raw": rv if rv in ("aligned", "justified_skip", "missing", "contradiction") else "",
                             "decided_by": it.decided_by, "escalated": it.node_id in esc,
                             "evidence": it.evidence, "model": doc.model, "basis": doc.basis,
                             "speech_match": doc.speech_match})
            print(f"[f11:{jname}] {rec} {el:.1f}s solar_calls={eng.calls} esc={len(esc)} model={doc.model}", flush=True)
        write_jsonl(out / f"f11_{jname.replace('+', '_')}.jsonl", rows)
        rep = {}
        for sname in sorted({x["set"] for x in rows}) + ["all"]:
            sub = [x for x in rows if sname == "all" or x["set"] == sname]
            rep[sname] = {"n": len(sub),
                          "final": macro_f1([x["gold"] for x in sub], [x["final"] for x in sub]),
                          "raw": macro_f1([x["gold"] for x in sub], [x["raw"] or "missing" for x in sub]),
                          "raw_missing": sum(1 for x in sub if not x["raw"]),
                          "decided_by": dict(Counter(x["decided_by"] for x in sub))}
        rep["sec_per_rec"] = round(sum(stats["sec"]) / max(1, len(stats["sec"])), 2)
        rep["solar_calls_per_rec"] = round(sum(stats["solar_calls"]) / max(1, len(stats["solar_calls"])), 2)
        rep["escalated_per_rec"] = round(sum(stats["escalated"]) / max(1, len(stats["escalated"])), 2)
        rep["recs"] = len(stats["sec"])
        report[jname] = rep
        print(f"[f11:{jname}] final macroF1={rep['all']['final']['macro_f1']} raw={rep['all']['raw']['macro_f1']} "
              f"{rep['sec_per_rec']}s/rec solar_calls/rec={rep['solar_calls_per_rec']}", flush=True)
    try:
        import torch
        report["peak_vram_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 1)
    except Exception:  # noqa: BLE001
        pass
    jdump(out / f"f11_report{'' if args.escalate_below is None else '_esc' + str(args.escalate_below)}.json", report)


if __name__ == "__main__":
    main()
