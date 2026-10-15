"""
평가 결과를 표로 — 판정기별(Solar F-11 · LoRA · LoRA+Solar) · 정답 출처별(구성 · 두 모델 일치 · 생략 규칙) · 녹음 종류별.

정답 출처를 가르는 까닭: 시험 정답의 대부분은 Solar·A.X 라벨러가 맞춘 것이고 LoRA 는 그 라벨러에게서 배웠다 —
LoRA 가 라벨러의 말버릇을 닮아 점수가 부풀 수 있다. **구성(일부러 심은 결함) 정답**만의 점수가 그 영향을 덜 받는다.

  python make_report.py --tag r1
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict

from common import DATA, RUN, read_jsonl

from train_lora import macro_f1

JUDGES = [("solar", "f11_solar.jsonl"), ("lora", "f11_lora.jsonl"), ("lora+solar", "f11_lora_solar.jsonl")]


def fmt(rep: dict) -> str:
    cls = " · ".join(f"{k[:4]} {rep[k]['f1']:.2f}({rep[k]['n']})" for k in ("aligned", "missing", "contradiction", "justified_skip")
                     if rep[k]["n"])
    return f"macroF1 **{rep['macro_f1']:.3f}** · acc {rep['acc']:.3f} · {cls}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--sets_dir", default=str(DATA / "sets"))
    args = ap.parse_args()
    from pathlib import Path
    base = RUN / "eval" / args.tag
    gold: dict[tuple, dict] = {}
    for name in ("test_ko_real", "test_ko_synth"):
        for r in read_jsonl(Path(args.sets_dir) / f"{name}.jsonl"):
            gold[(r["rec"], r["item"]["node_id"])] = r
    out = {}
    lines = [f"# F-11 판정 평가 — {args.tag}", ""]
    for jname, fname in JUDGES:
        rows = read_jsonl(base / fname)
        if not rows:
            continue
        groups: dict[str, list] = defaultdict(list)
        for x in rows:
            g = gold.get((x["rec"], x["node_id"]))
            if g is None:
                continue
            groups[f"set:{x['set']}"].append(x)
            groups[f"basis:{x['set']}:{g['basis']}"].append(x)
            groups[f"variant:{x['set']}:{g.get('variant')}"].append(x)
            if g["basis"].startswith("cons"):
                groups["cons_only:all"].append(x)
        res = {}
        lines.append(f"## {jname}")
        for k in sorted(groups):
            xs = groups[k]
            fin = macro_f1([x["gold"] for x in xs], [x["final"] for x in xs])
            raw = macro_f1([x["gold"] for x in xs], [x["raw"] or "missing" for x in xs])
            res[k] = {"n": len(xs), "final": fin, "raw": raw}
            lines.append(f"- {k} (n={len(xs)}) final: {fmt(fin)} | raw: macroF1 {raw['macro_f1']:.3f} acc {raw['acc']:.3f}")
        out[jname] = res
        lines.append("")
    (base / "report.md").write_text("\n".join(lines), encoding="utf-8")
    (base / "report_groups.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
