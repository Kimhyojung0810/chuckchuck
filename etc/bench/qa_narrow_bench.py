#!/usr/bin/env python3
"""
「모르겠어요」 1단(narrow) 보기 칩 실험 판 (2026-10-17 tune). 5단계 고정 질문 세트(qa_dialogue_bench.question_set)마다
coach_stuck(1단)을 불러 되물음 · 보기 둘을 남기고, 보기가 **핵심 논리를 고르는가**(숫자 둘 · 낱말 조각 · 정답 누설)를 센다.

    QA_DLG_OUT=/data/models/_runs/wt-qa-tune python etc/bench/calllog_run.py etc/bench/qa_narrow_bench.py run --split dev --tag n0 --rep 0
    ... qa_narrow_bench.py report --tags n0,n1

지표 (코드):
- with_choices: 보기 둘이 나간 비율 · numeric: 보기 중 하나라도 숫자가 든 비율(질문 · 모범답이 결론을 그 숫자에 걸지 않는 한 미시 확인)
- fragment: 보기가 낱말 하나(공백 없는 2~5자 조각 — 「'것만으로' 쪽인가요」) 인 비율 · reason_form: 보기 둘 다 「~해서 · ~라서 · ~때문」 처럼
  이유 · 설명 꼴인 비율
- leak: 보기 · 되물음이 모범답 긴 조각(공백 빼고 12자)을 그대로 싣는 비율
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "main"), str(ROOT / "etc"), str(ROOT), str(ROOT / "etc" / "bench")]

from pipeline.config import load_dotenv  # noqa: E402

load_dotenv()
from pipeline import _ai_calllog  # noqa: E402
from pipeline import f08_ensemble as FE  # noqa: E402
from pipeline.f09_judge import coach_stuck  # noqa: E402
try:
    from pipeline.f09_judge import _choice_nums  # noqa: E402
except ImportError:  # 기준선 코드
    import re as _re
    def _choice_nums(t):
        return _re.findall(r"\d+(?:\.\d+)?", _re.sub(r"[A-Za-z]+[-‑]?\d+[A-Za-z]*|\d+(?:[A-Za-z]+|\([A-Za-z]+\)[A-Za-z]*)", " ", t or ""))

import qa_dialogue_bench as QB  # noqa: E402

OUT = Path(os.environ.get("QA_DLG_OUT") or "/data/models/_runs/wt-qa-tune")
_NUM_RE = re.compile(r"\d")


def _squash(t: str) -> str:
    return re.sub(r"[\s\W_]+", "", t or "")


def leaks(text: str, gist: str, n: int = 12) -> bool:
    g, t = _squash(gist), _squash(text)
    return any(g[i:i + n] in t for i in range(0, max(0, len(g) - n + 1), 3))


def run(args) -> int:
    decks = QB.DEV if args.split == "dev" else QB.TEST if args.split == "test" else tuple(args.split.split(","))
    out_dir = OUT / "runs" / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)

    def deck_run(deck):
        art = QB.load_art(deck)
        rows = []
        for i, c in enumerate(QB.question_set(deck)):
            q = FE.to_question(c, i + 1)
            t0 = time.monotonic()
            try:
                v = coach_stuck(q, graph=art.get("concept_graph"), alignment=art.get("alignment_doc"),
                                transcript=art.get("transcript"), context=art.get("context"), slidedoc=art.get("slide_doc"),
                                history=[], llm=args.llm).to_dict()
            except Exception as e:  # noqa: BLE001
                v = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            rows.append({"deck": deck, "qid": q.id, "question": q.question, "gist": q.answer_gist, "pattern": c.get("pattern"),
                         "trap": bool(c.get("trap")), "rep": args.rep, "sec": round(time.monotonic() - t0, 2),
                         **{k: v.get(k) for k in ("coach_stage", "react", "followup", "choices", "evidence_quote", "error")}})
        (out_dir / f"{deck}-r{args.rep}.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n",
                                                           encoding="utf-8")
        return deck, len(rows)

    with ThreadPoolExecutor(args.par) as ex:
        for deck, n in ex.map(_ai_calllog.carry(deck_run), decks):
            print(f"{args.tag} {deck} r{args.rep}: {n}", flush=True)
    return 0


def metrics(rows: list[dict]) -> dict:
    ok = [r for r in rows if not r.get("error") and r.get("coach_stage") == "narrow"]
    ch = [r for r in ok if len(r.get("choices") or []) == 2]

    def rate(xs):
        xs = list(xs)
        return round(sum(xs) / len(xs), 3) if xs else None

    def numeric(r):
        # 질문이 먼저 꺼낸 숫자 · 이름 속 숫자(GLP-1 · 2C)는 미시 확인이 아니다 — 자료의 다른 수치를 보기로 들였나
        own = set(_choice_nums(r["question"]))
        return any(n not in own for x in r["choices"] for n in _choice_nums(x))

    return {"n": len(ok), "errors": sum(1 for r in rows if r.get("error")),
            "with_choices": rate(len(r.get("choices") or []) == 2 for r in ok),
            "numeric": rate(numeric(r) for r in ch),
            "numeric_any": rate(any(_choice_nums(x) for x in r["choices"]) for r in ch),
            "fragment": rate(any(" " not in x.strip() and len(x.strip()) <= 6 for x in r["choices"]) for r in ch),
            "reason_form": rate(all(" " in x.strip() and len(x.strip()) >= 6 for x in r["choices"]) for r in ch),
            "leak": rate(any(leaks(x, r.get("gist") or "") for x in r["choices"]) or leaks(r.get("followup") or "", r.get("gist") or "")
                         for r in ch),
            "sec_p50": sorted(r["sec"] for r in ok)[len(ok) // 2] if ok else None}


def report(args) -> int:
    out = {}
    for tag in [t for t in args.tags.split(",") if t]:
        rows = []
        for f in sorted((OUT / "runs" / tag).glob("*.jsonl")):
            rows += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        out[tag] = metrics(rows)
        if args.show:
            for r in rows:
                print(f"[{tag}] {r['deck']} {r['qid'][:28]:28} | {r.get('followup')} | {r.get('choices')}")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "report"])
    ap.add_argument("--split", default="dev")
    ap.add_argument("--tag", default="n0")
    ap.add_argument("--tags", default="")
    ap.add_argument("--rep", type=int, default=0)
    ap.add_argument("--llm", default="solar4+solar")
    ap.add_argument("--par", type=int, default=3)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    return {"run": run, "report": report}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
