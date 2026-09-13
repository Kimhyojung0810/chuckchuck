"""
같은 조건으로 여러 번 잰 결과에서 지표별 잡음 폭을 실측하고, `qa_eval_compare.PRIMARY` 의 폭과 대조한다.

    python examples/qa_eval_noise.py --glob '*_rep*-ax-20260913.json'          # 한 묶음
    python examples/qa_eval_noise.py --glob '*_rep*-ax-*' --glob '*_rep*-solar-*'   # 묶음 여럿, 나란히
    python examples/qa_eval_noise.py --tags rep1-ax-20260913 rep2-ax-20260913 rep3-ax-20260913
    python examples/qa_eval_noise.py --glob '*_rep*-ax-*' --md exports/qa_eval/reports/noise_ax.md

왜 — FAILURE_QUESTIONS 0-2·0-3: "같은 조건으로 두 번 재면 같은 값이 나오나 · 잡음 폭이 실측인가 짐작인가".
PRIMARY 의 폭(특이도 ±0.5, 인용률 ±0.05, rubric ±0.5)은 9/10 결과 다섯 개를 보고 정한 값이라 절반이 짐작이다.
폭이 실측 범위보다 좁으면 잡음을 신호로 채택하고(거짓 IMPROVED), 넓으면 진짜 개선을 NOISE 로 버린다.
이 스크립트는 판정하지 않는다 — 실측 범위와 제안 폭을 표로 내고, PRIMARY 를 고치는 건 사람이 한다.

제안 폭 = max(범위, 2·표준편차) 를 소수 둘째 자리로 올림. 정수 지표(폴백·오류 수)는 범위 그대로.
표본이 3개면 범위는 과소추정이다 — "최소 이만큼" 으로 읽는다.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "exports" / "qa_eval"

_spec = importlib.util.spec_from_file_location("qa_eval_compare", ROOT / "examples" / "qa_eval_compare.py")
_cmp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cmp)  # type: ignore[union-attr]
PRIMARY, get_path, as_number = _cmp.PRIMARY, _cmp.get_path, _cmp.as_number

INTEGER_METRICS = {"fallback", "honorifics_questions", "honorifics_judge", "impolite_questions", "judge_errors",
                   "rubric.hallucination"}


def load_summaries(paths: list[Path]) -> list[dict]:
    out = []
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        out.append(data.get("summary", data))
    return out


def stats(values: list[float]) -> dict:
    n = len(values)
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "mean": mean, "sd": sd, "min": min(values), "max": max(values), "range": max(values) - min(values)}


def suggest_tol(metric: str, st: dict) -> float:
    if metric in INTEGER_METRICS:
        return float(int(round(st["range"])))
    raw = max(st["range"], 2 * st["sd"])
    return math.ceil(raw * 100 - 1e-9) / 100 if raw > 0 else 0.0


def analyze(summaries: list[dict]) -> list[dict]:
    """PRIMARY 지표마다 실측 통계와 현재 폭·제안 폭·평가('좁다'|'맞다'|'넓다'|'n/a')."""
    rows = []
    for metric, _direction, tol in PRIMARY:
        vals = [as_number(get_path(s, metric)) for s in summaries]
        vals = [v for v in vals if v is not None]
        if len(vals) < 2:
            rows.append({"metric": metric, "tol": tol, "verdict": "n/a", "n": len(vals)})
            continue
        st = stats(vals)
        sug = suggest_tol(metric, st)
        if st["range"] > tol + 1e-9:
            verdict = "좁다"      # 실측 범위가 폭 밖 → 잡음이 신호로 채택될 수 있다
        elif tol > 0 and sug > 0 and tol >= 3 * sug:
            verdict = "넓다"      # 폭이 실측의 3배 이상 → 진짜 개선을 놓친다
        else:
            verdict = "맞다"
        rows.append({"metric": metric, "tol": tol, "suggest": sug, "verdict": verdict, **st})
    return rows


def render(groups: dict[str, list[dict]]) -> str:
    lines = []
    for name, rows in groups.items():
        n = max((r.get("n", 0) for r in rows), default=0)
        lines += [f"### {name} — 반복 {n}회", "",
                  "| 지표 | 평균 | 표준편차 | 최소~최대 | 범위 | 현재 폭 | 제안 폭 | 평가 |", "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            if r["verdict"] == "n/a":
                lines.append(f"| {r['metric']} | – | – | – | – | {r['tol']} | – | n/a ({r['n']}개) |")
                continue
            lines.append(f"| {r['metric']} | {r['mean']:.2f} | {r['sd']:.2f} | {r['min']:.2f}~{r['max']:.2f} | "
                         f"{r['range']:.2f} | {r['tol']} | {r['suggest']:.2f} | {r['verdict']} |")
        narrow = [r["metric"] for r in rows if r["verdict"] == "좁다"]
        wide = [r["metric"] for r in rows if r["verdict"] == "넓다"]
        lines.append("")
        lines.append(f"폭이 좁은 지표 {len(narrow)}개 ({', '.join(narrow) or '없음'}) · 넓은 지표 {len(wide)}개 ({', '.join(wide) or '없음'})")
        lines.append("")
    return "\n".join(lines)


def group_name(pattern: str) -> str:
    return re.sub(r"[*?\[\]]|\.json$", "", pattern).strip("_-") or pattern


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--glob", action="append", default=[], help="exports/qa_eval 안의 파일 패턴 (묶음 하나). 여러 번 가능")
    ap.add_argument("--tags", nargs="*", default=[], help="tag 목록 (각 tag 의 최신 결과를 한 묶음으로)")
    ap.add_argument("--md", type=Path, help="표를 이 파일에도 쓴다")
    a = ap.parse_args(argv)
    groups: dict[str, list[dict]] = {}
    for pat in a.glob:
        files = sorted(p for p in OUT.glob(pat) if p.suffix == ".json" and ".raw." not in p.name and ".corpus." not in p.name)
        if len(files) < 2:
            print(f"⚠ {pat}: 결과가 {len(files)}개 — 둘 이상 필요", file=sys.stderr)
            continue
        groups[group_name(pat)] = analyze(load_summaries(files))
    if a.tags:
        files = [_cmp.latest_for_tag(t) for t in a.tags]
        groups["+".join(a.tags)] = analyze(load_summaries(files))
    if not groups:
        print("묶음이 없어요. --glob 또는 --tags 를 준다.", file=sys.stderr)
        return 2
    text = render(groups)
    print(text)
    if a.md:
        a.md.parent.mkdir(parents=True, exist_ok=True)
        a.md.write_text(text, encoding="utf-8")
        print(f"→ {a.md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
