"""
rubric 심사관(LLM)을 믿어도 되는지 재는 도구 — 사람 채점표를 뽑고, 채점이 들어오면 일치율을 낸다 (로드맵 B2 남은 절반).

    python examples/rubric_human_sheet.py sheet exports/qa_eval/<결과>.json [...] --out exports/rubric_human/sheet.csv
        → 질문·근거 장 본문·rubric 항목 빈칸이 든 CSV. 사람이 1~5 를 채운다 (환각은 0/1). 심사관 점수는 안 보여 준다(편향 방지).
    python examples/rubric_human_sheet.py agree exports/rubric_human/sheet.csv
        → 항목별 일치율: 정확히 같음 / ±1 안 / 평균 차. 심사관 점수는 CSV 의 숨은 열(llm_*)에서 읽는다.

판단 기준(제안): ±1 일치율이 0.8 을 넘는 항목만 "판정" 에 쓰고, 그 아래면 "참고" 로 둔다.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ITEMS = ("groundedness", "relevance", "coverage", "depth", "answerability", "non_duplication", "hallucination")


def build_rows(results: list[Path]) -> list[dict]:
    rows = []
    for rp in results:
        d = json.loads(rp.read_text(encoding="utf-8"))
        rub = {r["question_id"]: r for r in d.get("rubric", []) if not r.get("missing")}
        for q in d.get("questions", []):
            r = rub.get(q["id"], {})
            row = {"result": rp.stem, "question_id": q["id"], "situation": (d.get("context") or {}).get("situation", ""),
                   "question": q["question"], "gist": q.get("gist", "")}
            for k in ITEMS:
                row[f"human_{k}"] = ""
                v = r.get(k)
                row[f"llm_{k}"] = ("" if v is None else (int(bool(v)) if k == "hallucination" else v))
            rows.append(row)
    return rows


def write_sheet(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["result", "question_id", "situation", "question", "gist"] + [f"human_{k}" for k in ITEMS] + [f"llm_{k}" for k in ITEMS]
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def agreement(rows: list[dict]) -> dict:
    """항목별 (n, 정확 일치율, ±1 일치율, 평균 차 사람−심사관). 사람 칸이 빈 행은 뺀다."""
    out = {}
    for k in ITEMS:
        pairs = []
        for r in rows:
            h, m = str(r.get(f"human_{k}", "")).strip(), str(r.get(f"llm_{k}", "")).strip()
            if h == "" or m == "":
                continue
            try:
                pairs.append((float(h), float(m)))
            except ValueError:
                continue
        if not pairs:
            out[k] = {"n": 0}
            continue
        exact = sum(1 for h, m in pairs if h == m) / len(pairs)
        within1 = sum(1 for h, m in pairs if abs(h - m) <= 1) / len(pairs)
        bias = sum(h - m for h, m in pairs) / len(pairs)
        out[k] = {"n": len(pairs), "exact": round(exact, 2), "within1": round(within1, 2), "bias": round(bias, 2)}
    return out


def read_sheet(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("sheet"); a.add_argument("results", nargs="+", type=Path)
    a.add_argument("--out", type=Path, default=ROOT / "exports" / "rubric_human" / "sheet.csv")
    b = sp.add_parser("agree"); b.add_argument("sheet", type=Path)
    args = ap.parse_args()
    if args.cmd == "sheet":
        rows = build_rows(args.results)
        write_sheet(rows, args.out)
        print(f"채점표 {len(rows)}행 → {args.out}. human_* 칸을 1~5(환각 0/1)로 채운 뒤 `agree` 로 잰다.")
        return 0
    res = agreement(read_sheet(args.sheet))
    print(f"{'항목':<16}{'n':>4}{'정확':>7}{'±1':>7}{'편차(사람−심사관)':>18}")
    for k, v in res.items():
        if v["n"] == 0:
            print(f"{k:<16}{0:>4}   (채점 없음)")
            continue
        mark = "판정에 써도 됨" if v["within1"] >= 0.8 else "참고만"
        print(f"{k:<16}{v['n']:>4}{v['exact']:>7}{v['within1']:>7}{v['bias']:>18}  {mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
