"""
함정 질문 벤치 (qa/trap, 2026-09-29) — 코드가 만든 함정 전제가 덱이 바뀌어도 서는가.

    .venv/bin/python labs/qa_bench/traps.py              # 전 덱 · 5·10분 질문(실 LLM) + 5분 함정 판정 탐침
    .venv/bin/python labs/qa_bench/traps.py --no-judge   # 질문만
    .venv/bin/python labs/qa_bench/traps.py --report     # LLM 없이 저장한 결과로 표만

run.py 의 캐시(out/<deck>/slide_doc·graph·claims·triage.json)를 **그대로** 읽는다 — triage 는 다시 돌리지 않는다(함정은
F-08 이 고르므로 triage 를 다시 돌릴 이유가 없고, 돌리면 호출만 는다). 호출은 run.py 의 `Counted` 로 세고 `--budget` 에서 끊는다.

잰 것:
- 트랙마다 함정 개수 vs 허용치(QA_TRACK_TRAPS)
- 함정마다: 전제가 자료 어느 줄과도 같지 않고 바꾼 값이 자료에 없는가(`_traps.verify`) · 사실이 자료 줄 그대로인가
  (표에서 읽은 사실이면 그 값·행 머리가 그 장에 있는가) · 질문이 전제의 단서를 싣고 정답 단서는 안 싣는가
- 5분 트랙 함정 질문마다 판정 탐침 셋: 골자 그대로(전제를 바로잡음 → 통과해야) · 전제 동의(「네」 없이 전제를 되뇜 →
  통과 못 해야) · 무관한 답(→ wrong)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run as B  # noqa: E402  (run.py 가 sys.path·.env 를 맞춘다)

from chuckchuck import _grounding as grounding  # noqa: E402
from chuckchuck import _traps as traps  # noqa: E402
from chuckchuck.contracts import QA_TRACK_TRAPS, Question, SlideDoc, ConceptGraph  # noqa: E402

OUT = B.OUT / "traps_run.json"


def agree_answer(tp) -> str:
    """전제 동의 탐침 — 「네」 같은 동의 표지 없이 전제를 사실처럼 되뇌고 이유를 붙인다(코드 표지에 기대지 않는 쪽)."""
    return f"{tp.premise.removeprefix('표에서 ')}. 그 결과가 발표의 핵심 근거예요."


def fact_on_slide(tp, sd: dict) -> bool:
    slide = next((s for s in sd.get("slides") or [] if s.get("slide_no") == tp.slide_no), None)
    if slide is None:
        return False
    raw = grounding.squash(slide.get("raw_text") or "")
    if not tp.fact.startswith("표에서 "):
        return grounding.squash(tp.fact) in raw
    # 표에서 읽은 사실: 정답 단서(값 또는 행 머리)가 그 장에 있어야 한다
    heads = [c.partition("|")[0] for c in tp.right]
    return all(grounding.squash(h) in raw for h in heads if h) and bool(heads)


def check_trap(q: dict, sd: dict, graph: dict) -> dict:
    qq = Question.from_dict(q)
    tp = qq.trap_premise
    by_no = {s.slide_no: s for s in SlideDoc.from_dict(sd).slides}
    idx = grounding.build_index(by_no, ConceptGraph.from_dict(graph).nodes)
    return {
        "q": qq.id, "label": qq.label, "kind": tp.kind if tp else "", "question": qq.question,
        "premise": tp.premise if tp else "", "fact": tp.fact if tp else "", "slide_no": tp.slide_no if tp else 0,
        "gist": qq.answer_gist, "hint": qq.hint, "why": qq.why,
        "has_premise": tp is not None,
        "premise_false": bool(tp) and traps.verify(tp, idx),
        "fact_is_deck": bool(tp) and fact_on_slide(tp, sd),
        "carries": bool(tp) and traps.question_carries(qq.question, tp),
        "worded": "llm" if "trap_llm_worded" in (qq.basis.checks if qq.basis else []) else "template",
        "slot": qq.basis.slot if qq.basis else "", "probe": bool(qq.basis and qq.basis.probe),
    }


def run_questions(run: B.DeckRun, track: str) -> dict | None:
    d = run.dir
    sd, graph, claims, triage = (B.read_json(d / f) for f in ("slide_doc.json", "graph.json", "claims.json", "triage.json"))
    if not (sd and graph and triage):
        return None
    from chuckchuck import build_questions

    t0 = time.time()
    doc = build_questions(graph, triage, track=track, slidedoc=sd, context=run.spec["context"], claims=claims,
                          llm=B.engine(run.name, f"trap_q{track}")).to_dict()
    B.note(f"  [{run.name}] 질문 t{track} {time.time() - t0:.1f}s · 함정 {sum(q['trap'] for q in doc['questions'])}")
    B.write_json(d / f"trap_questions_t{track}.json", doc)
    return doc


KINDS = ("gist", "agree", "offtopic")


def judge_one(run: B.DeckRun, q: dict, track: str, kinds: tuple[str, ...] = KINDS) -> list[dict]:
    """함정 질문 하나에 탐침 셋 — 골자 그대로(통과해야) · 전제 동의(통과 못 해야) · 무관한 답(wrong 이어야)."""
    from chuckchuck import judge_answer
    from chuckchuck.f09_judge import _TRAP_AGREED_REACT

    d = run.dir
    sd, graph = B.read_json(d / "slide_doc.json"), B.read_json(d / "graph.json")
    tp = Question.from_dict(q).trap_premise
    rows = []
    for kind, text, expect in (("gist", q["answer_gist"], "pass"), ("agree", agree_answer(tp) if tp else "", "not_pass"),
                               ("offtopic", B.OFFTOPIC, "wrong")):
        if kind not in kinds or not text:
            continue
        t0, c0 = time.time(), B.BUDGET.used
        j = judge_answer(q, text, graph=graph, context=run.spec["context"], slidedoc=sd,
                         llm=B.engine(run.name, f"trap_judge:{kind}")).to_dict()
        B.log_stage(run.name, f"trap_judge:{kind}", t0, c0)
        passed = j["verdict"] in ("good", "partial") and j["score"] >= 70
        ok = {"pass": passed, "not_pass": not passed, "wrong": j["verdict"] == "wrong"}[expect]
        rows.append({"q": q["id"], "track": track, "kind": kind, "answer": text, "verdict": j["verdict"], "score": j["score"],
                     "react": j.get("react", ""), "trap_guard": j.get("react", "") == _TRAP_AGREED_REACT,
                     "expect": expect, "ok": ok})
        B.note(f"  [{run.name}] t{track} 판정 {kind:8s} → {j['verdict']} {j['score']} {'✓' if ok else '✗'} {j.get('react', '')[:50]}")
    return rows


def summarize(results: dict) -> str:
    lines = ["| 덱 | 묶음 | 트랙 | 함정/허용 | 전제 거짓 | 사실=자료 | 질문이 전제를 실음 | LLM 문장/템플릿 | 판정 ✓ |",
             "|---|---|---|---|---|---|---|---|---|"]
    agg: dict[str, dict] = {}
    for name, r in results.items():
        for t in ("5", "10"):
            tr = r.get("tracks", {}).get(t)
            if tr is None:
                continue
            ts = tr["traps"]
            judge = [x for x in r.get("judge", []) if x.get("track", "5") == t]
            a = agg.setdefault(f"{r['group']}|{t}", {"decks": 0, "traps": 0, "budget": 0, "false": 0, "deck": 0, "carry": 0,
                                                    "llm": 0, "judge_ok": 0, "judge_n": 0})
            a["decks"] += 1
            a["traps"] += len(ts)
            a["budget"] += QA_TRACK_TRAPS[t]
            a["false"] += sum(x["premise_false"] for x in ts)
            a["deck"] += sum(x["fact_is_deck"] for x in ts)
            a["carry"] += sum(x["carries"] for x in ts)
            a["llm"] += sum(x["worded"] == "llm" for x in ts)
            a["judge_ok"] += sum(x["ok"] for x in judge)
            a["judge_n"] += len(judge)
            lines.append(f"| {name} | {r['group']} | {t} | {len(ts)}/{QA_TRACK_TRAPS[t]} | {sum(x['premise_false'] for x in ts)} | "
                         f"{sum(x['fact_is_deck'] for x in ts)} | {sum(x['carries'] for x in ts)} | "
                         f"{sum(x['worded'] == 'llm' for x in ts)}/{sum(x['worded'] == 'template' for x in ts)} | "
                         f"{sum(x['ok'] for x in judge)}/{len(judge)} |")
    lines += ["", "| 묶음·트랙 | 덱 | 함정/허용 | 전제 거짓 | 사실=자료 | 전제 실음 | LLM 문장 | 판정 ✓ |", "|---|---|---|---|---|---|---|---|"]
    for k, a in sorted(agg.items()):
        lines.append(f"| {k} | {a['decks']} | {a['traps']}/{a['budget']} | {a['false']}/{a['traps']} | {a['deck']}/{a['traps']} | "
                     f"{a['carry']}/{a['traps']} | {a['llm']}/{a['traps']} | {a['judge_ok']}/{a['judge_n']} |")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="labs/qa_bench/traps.py")
    ap.add_argument("--decks", default="all")
    ap.add_argument("--budget", type=int, default=52)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--from-bench", action="store_true",
                    help="질문을 새로 만들지 않고 run.py 가 방금 만든 questions_t5/t10.json 을 그대로 잰다 (P5 — 함정은 F-08 안에서 코드가 만든다)")
    ap.add_argument("--kinds", default=",".join(KINDS), help="함정 판정 탐침 종류 (gist·agree·offtopic)")
    ap.add_argument("--no-extra", action="store_true", help="10분 트랙에만 있는 함정은 판정하지 않는다")
    ap.add_argument("--repo-root", default=str(B.DEFAULT_REPO))
    ns = ap.parse_args(argv)
    if ns.report:
        print(summarize(B.read_json(OUT) or {}))
        return 0
    B.BUDGET.limit = ns.budget
    decks = B.load_decks(Path(ns.repo_root), set())
    names = list(decks) if ns.decks == "all" else ns.decks.split(",")
    results: dict = {} if ns.from_bench else (B.read_json(OUT) or {})
    kinds = tuple(k.strip() for k in ns.kinds.split(",") if k.strip())
    docs: dict[str, dict[str, dict]] = {}
    runs = {name: B.DeckRun(decks[name], None) for name in names}
    try:
        # 1. 질문 (덱 × 5·10분)
        for name, run in runs.items():
            B.note(f"\n== {name} ({decks[name]['group']})")
            sd, graph = B.read_json(run.dir / "slide_doc.json"), B.read_json(run.dir / "graph.json")
            r = {"group": decks[name]["group"], "tracks": {}, "judge": []}
            for t in ("5", "10"):
                doc = B.read_json(run.dir / f"questions_t{t}.json") if ns.from_bench else run_questions(run, t)
                if doc is None:
                    continue
                docs.setdefault(name, {})[t] = doc
                r["tracks"][t] = {"n": len(doc["questions"]),
                                  "traps": [check_trap(q, sd, graph) for q in doc["questions"] if q.get("trap")]}
            results[name] = r
            B.write_json(OUT, results)
        if not ns.no_judge:
            # 2. 5분 트랙 함정 전부 → 3. 10분 트랙에만 있는 함정을 덱마다 돌아가며 (예산까지)
            for name, run in runs.items():
                for q in [q for q in docs.get(name, {}).get("5", {}).get("questions", []) if q.get("trap")]:
                    results[name]["judge"] += judge_one(run, q, "5", kinds)
                    B.write_json(OUT, results)
            extra = {name: [q for q in docs.get(name, {}).get("10", {}).get("questions", []) if q.get("trap")
                            and q["node_id"] not in {x["node_id"] for x in docs[name].get("5", {}).get("questions", []) if x.get("trap")}]
                     for name in runs}
            while any(extra.values()) and not ns.no_extra:
                for name, run in runs.items():
                    if extra[name] and B.BUDGET.limit - B.BUDGET.used >= 3:
                        results[name]["judge"] += judge_one(run, extra[name].pop(0), "10", kinds)
                        B.write_json(OUT, results)
                    elif extra[name]:
                        extra[name] = []
    except B.BudgetExceeded as e:
        B.note(f"\n예산에서 멈췄어요: {e}")
    B.write_json(OUT, results)
    print(summarize(results))
    print(f"\nLLM 호출 {B.BUDGET.used}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
