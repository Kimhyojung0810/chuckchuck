"""
질문 코치 벤치 실행 — 시나리오 5개(A~E)를 실제 코치 함수(F-08 triage·build_questions → F-09 judge_answer → F-25 build_memory)로
돌리고, 질문마다 대상 노드 · 선택 이유 · 사용자 상태 · 생성된 질문을 남긴다. 실 과금(Solar). 채점은 score.py 가 한다.

    .venv/bin/python labs/qcoach_bench/run.py --tag baseline --reps 3
    .venv/bin/python labs/qcoach_bench/run.py --tag after --reps 3

브리지의 「자료만」 경로와 같은 인자로 부른다 (graph · slidedoc · claims · context, 녹음 없음, 10분 트랙).

시나리오 (사용자 상태 → 코치가 보여 줄 다음 말)
  A 아무것도 학습 안 함   기억 없음 → 첫 세션 질문 목록
  B 핵심 개념 정답         첫 질문에 모범답(answer_gist)으로 답 → 판정 · 다음 말 · 다음 리허설 첫 질문
  C 핵심 개념 오답         첫 질문에 덱이 반박하는 오해로 답 → 판정 · 되물음 · 다음 리허설 첫 질문
  D 모르겠어요             첫 질문에 「모르겠어요」 두 번 → 코칭 1·2단 · 다음 리허설 첫 질문
  E 핵심 개념 이미 이해    지난 리허설에서 첫 세션 상위 핵심 개념을 good 으로 닫음 → 이번 세션 질문 목록

결과: labs/qcoach_bench/out/<tag>/rep<N>.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from prepare import FIX, _env  # noqa: E402
from score import key_of, load_keys  # noqa: E402

TRACK = "10"
DUNNO = "(모르겠어요)"


def _load():
    read = lambda n: json.loads((FIX / f"{n}.json").read_text())  # noqa: E731
    return read("graph"), read("slidedoc"), read("claims"), read("context")


def session(inp: dict, memory=None) -> dict:
    """한 리허설의 질문 목록 — 브리지 _triage_for · _build_questions_payload 와 같은 인자."""
    from chuckchuck import build_questions, triage_questions
    g, sd, claims, ctx, llm = inp["graph"], inp["slidedoc"], inp["claims"], inp["ctx"], inp["llm"]
    triage = triage_questions(g, None, None, ctx, memory=memory, claims=claims, slidedoc=sd, llm=llm)
    doc = build_questions(g, triage, track=TRACK, slidedoc=sd, context=ctx, memory=memory, claims=claims, llm=llm)
    return {"questions": [q.to_dict() for q in doc.questions], "deferred": doc.deferred_node_ids,
            "triage": [m.to_dict() for m in triage.marks]}


def judge(inp: dict, q: dict, answer: str, *, give_up=False, history=None, memory=None) -> dict:
    from chuckchuck import judge_answer
    j = judge_answer(q, answer, graph=inp["graph"], slidedoc=inp["slidedoc"], context=inp["ctx"], give_up=give_up,
                     history=history, prior_answers=[], llm=inp["llm"], memory=memory)
    return {**j.to_dict(), "passed": j.passed, "mastered": j.mastered, "close_reason": j.close_reason}


def turn(q: dict, answer: str, j: dict, at: float, give_up=False) -> dict:
    """브리지가 보관소에 남기는 qa_turns 한 줄 (demo/bridge.py _handle_qa_judge) — F-25 가 이것으로 기억을 만든다."""
    return {"at": at, "question_id": q["id"], "question": q, "answer": answer, "prior_answers": [], "hints_shown": [],
            "give_up": give_up, "judgement": {**j, "grounded_on_deck": True}, "question_source": "server"}


def memory_of(inp: dict, turns: list[dict]):
    from chuckchuck import build_memory
    reh = [{"session_id": "bench-past", "at": time.time() - 3600, "title": "수익률격차", "turns": turns}]
    return build_memory(reh, file_name="bench", learner_key="learner:bench", graph=inp["graph"], slidedoc=inp["slidedoc"])


def scenario_b(inp, s1):
    q1, qs = s1["questions"][0], s1["questions"]
    j = judge(inp, q1, q1["answer_gist"])
    nxt = (qs[1] if len(qs) > 1 else None) if j["mastered"] else {"followup": j["followup"]}
    mem = memory_of(inp, [turn(q1, q1["answer_gist"], j, time.time() - 3600)])
    return {"state": "첫 질문에 모범답으로 답함", "answer": q1["answer_gist"], "judgement": j, "next": nxt,
            "memory": mem.to_dict(), "session2": session(inp, mem)}


def scenario_c(inp, s1, keys):
    q1 = s1["questions"][0]
    k = key_of(q1["label"], keys)
    ans = next((c["wrong_answer"] for c in keys["concepts"] if c["id"] == k), keys["generic_wrong_answer"])
    j = judge(inp, q1, ans)
    mem = memory_of(inp, [turn(q1, ans, j, time.time() - 3600)])
    return {"state": f"첫 질문에 오답 ({k or '핵심 밖'} 오해)", "answer": ans, "judgement": j,
            "next": {"followup": j["followup"]} if not j["mastered"] else None,
            "memory": mem.to_dict(), "session2": session(inp, mem)}


def scenario_d(inp, s1):
    q1 = s1["questions"][0]
    j1 = judge(inp, q1, DUNNO, give_up=True)
    hist = [{"question": q1["question"], "answer": DUNNO, "verdict": "unknown", "question_id": q1["id"], "gave_up": True}]
    j2 = judge(inp, q1, DUNNO, give_up=True, history=hist)
    t0 = time.time() - 3600
    mem = memory_of(inp, [turn(q1, DUNNO, j1, t0, True), turn(q1, DUNNO, j2, t0 + 30, True)])
    return {"state": "첫 질문에 모르겠어요 두 번", "judgement": j1, "judgement2": j2,
            "next": {"followup": j1["followup"], "choices": j1.get("choices")},
            "memory": mem.to_dict(), "session2": session(inp, mem)}


def scenario_e(inp, s1, keys):
    """첫 세션 상위 3개 중 핵심 개념(K)을 겨냥한 질문을 지난번에 good 으로 닫았다. 없으면 첫 질문 하나."""
    top = s1["questions"][:3]
    cleared = [q for q in top if key_of(q["label"], keys)] or top[:1]
    t0 = time.time() - 7200
    good = {"verdict": "good", "score": 90, "missing_points": [], "coach_stage": "", "close_reason": "good"}
    turns = [turn(q, q["answer_gist"], {**good, "node_id": q["node_id"]}, t0 + i * 60) for i, q in enumerate(cleared)]
    mem = memory_of(inp, turns)
    return {"state": "지난 리허설에서 핵심 개념 " + ", ".join(q["label"] for q in cleared) + " 를 good 으로 닫음",
            "cleared": [q["node_id"] for q in cleared], "memory": mem.to_dict(), "session2": session(inp, mem)}


def one_rep(inp: dict, keys: dict) -> dict:
    s1 = session(inp)
    with ThreadPoolExecutor(4) as ex:
        fb = ex.submit(scenario_b, inp, s1)
        fc = ex.submit(scenario_c, inp, s1, keys)
        fd = ex.submit(scenario_d, inp, s1)
        fe = ex.submit(scenario_e, inp, s1, keys)
        out = {"A": {"state": "기억 없음 (처음 리허설)", "session1": s1},
               "B": fb.result(), "C": fc.result(), "D": fd.result(), "E": fe.result()}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--llm", default="solar")
    args = ap.parse_args()
    _env()
    g, sd, claims, ctx = _load()
    inp = {"graph": g, "slidedoc": sd, "claims": claims, "ctx": ctx, "llm": args.llm}
    keys = load_keys()
    out = HERE / "out" / args.tag
    out.mkdir(parents=True, exist_ok=True)
    for r in range(args.reps):
        p = out / f"rep{r}.json"
        if p.exists():
            print(f"skip {p}")
            continue
        t = time.time()
        res = one_rep(inp, keys)
        p.write_text(json.dumps(res, ensure_ascii=False, indent=1))
        print(f"rep{r} {time.time() - t:.0f}s → {p}")


if __name__ == "__main__":
    main()
