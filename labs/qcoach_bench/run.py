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
import time
from concurrent.futures import ThreadPoolExecutor

from common import OUT, key_of, load_env, load_fixtures, load_keys

TRACK = "10"
DUNNO = "(모르겠어요)"
#: 지난 리허설을 이만큼 전으로 둔다 — F-25 는 시각으로 최신을 고를 뿐이라 값 자체는 상관없다
HOUR = 3600
GOOD = {"verdict": "good", "score": 90, "missing_points": [], "coach_stage": "", "close_reason": "good"}


def session(inp: dict, memory=None) -> dict:
    """한 리허설의 질문 목록 — 브리지 _triage_for · _build_questions_payload 와 같은 인자."""
    from chuckchuck import build_questions, triage_questions
    g, sd, claims, ctx, llm = inp["graph"], inp["slidedoc"], inp["claims"], inp["ctx"], inp["llm"]
    triage = triage_questions(g, None, None, ctx, memory=memory, claims=claims, slidedoc=sd, llm=llm)
    doc = build_questions(g, triage, track=TRACK, slidedoc=sd, context=ctx, memory=memory, claims=claims, llm=llm)
    return {"questions": [q.to_dict() for q in doc.questions], "deferred": doc.deferred_node_ids,
            "triage": [m.to_dict() for m in triage.marks]}


def judge(inp: dict, q: dict, answer: str, *, give_up=False, history=None) -> dict:
    from chuckchuck import judge_answer
    j = judge_answer(q, answer, graph=inp["graph"], slidedoc=inp["slidedoc"], context=inp["ctx"], give_up=give_up,
                     history=history, prior_answers=[], llm=inp["llm"])
    return {**j.to_dict(), "passed": j.passed, "mastered": j.mastered, "close_reason": j.close_reason}


def turn(q: dict, answer: str, j: dict, at: float, give_up=False) -> dict:
    """브리지가 보관소에 남기는 qa_turns 한 줄 (demo/bridge.py _handle_qa_judge) — F-25 가 이것으로 기억을 만든다."""
    return {"at": at, "question_id": q["id"], "question": q, "answer": answer, "prior_answers": [], "hints_shown": [],
            "give_up": give_up, "judgement": {**j, "grounded_on_deck": True}, "question_source": "server"}


def next_rehearsal(inp: dict, turns: list[dict]) -> dict:
    """지난 리허설 한 번(turns) → F-25 기억 → 그 기억을 실은 다음 리허설 질문 목록."""
    from chuckchuck import build_memory
    reh = [{"session_id": "bench-past", "at": time.time() - HOUR, "title": "수익률격차", "turns": turns}]
    mem = build_memory(reh, file_name="bench", learner_key="learner:bench", graph=inp["graph"], slidedoc=inp["slidedoc"])
    return {"memory": mem.to_dict(), "session2": session(inp, mem)}


def scenario_b(inp: dict, s1: dict) -> dict:
    """정답 — 첫 질문에 모범답 그대로. 닫혔으면 다음 말은 다음 질문, 아니면 되물음."""
    q1, qs = s1["questions"][0], s1["questions"]
    j = judge(inp, q1, q1["answer_gist"])
    nxt = (qs[1] if len(qs) > 1 else None) if j["mastered"] else {"followup": j["followup"]}
    return {"state": "첫 질문에 모범답으로 답함", "answer": q1["answer_gist"], "judgement": j, "next": nxt,
            **next_rehearsal(inp, [turn(q1, q1["answer_gist"], j, time.time() - HOUR)])}


def scenario_c(inp: dict, s1: dict, keys: dict) -> dict:
    """오답 — 첫 질문의 핵심 개념에 맞춰 미리 써 둔 오해 (핵심 밖이면 공통 오답)."""
    q1 = s1["questions"][0]
    k = key_of(q1["label"], keys)
    ans = next((c["wrong_answer"] for c in keys["concepts"] if c["id"] == k), keys["generic_wrong_answer"])
    j = judge(inp, q1, ans)
    return {"state": f"첫 질문에 오답 ({k or '핵심 밖'} 오해)", "answer": ans, "judgement": j,
            "next": {"followup": j["followup"]} if not j["mastered"] else None,
            **next_rehearsal(inp, [turn(q1, ans, j, time.time() - HOUR)])}


def scenario_d(inp: dict, s1: dict) -> dict:
    """모르겠어요 두 번 — 두 번째는 첫 포기를 history 로 실어 코칭 단계가 올라가는지 본다."""
    q1 = s1["questions"][0]
    j1 = judge(inp, q1, DUNNO, give_up=True)
    hist = [{"question": q1["question"], "answer": DUNNO, "verdict": "unknown", "question_id": q1["id"], "gave_up": True}]
    j2 = judge(inp, q1, DUNNO, give_up=True, history=hist)
    t0 = time.time() - HOUR
    return {"state": "첫 질문에 모르겠어요 두 번", "judgement": j1, "judgement2": j2,
            "next": {"followup": j1["followup"], "choices": j1.get("choices")},
            **next_rehearsal(inp, [turn(q1, DUNNO, j1, t0, True), turn(q1, DUNNO, j2, t0 + 30, True)])}


def scenario_e(inp: dict, s1: dict, keys: dict) -> dict:
    """이미 이해 — 첫 세션 상위 3개 중 핵심 개념(K) 질문을 지난번에 good 으로 닫았다. 없으면 첫 질문 하나."""
    top = s1["questions"][:3]
    cleared = [q for q in top if key_of(q["label"], keys)] or top[:1]
    t0 = time.time() - 2 * HOUR
    turns = [turn(q, q["answer_gist"], {**GOOD, "node_id": q["node_id"]}, t0 + i * 60) for i, q in enumerate(cleared)]
    return {"state": "지난 리허설에서 핵심 개념 " + ", ".join(q["label"] for q in cleared) + " 를 good 으로 닫음",
            "cleared": [q["node_id"] for q in cleared], **next_rehearsal(inp, turns)}


def one_rep(inp: dict, keys: dict) -> dict:
    """첫 세션(A) 하나를 만들고, 그 첫 질문으로 B~E 를 나란히 돌린다."""
    s1 = session(inp)
    with ThreadPoolExecutor(4) as ex:
        futures = {"B": ex.submit(scenario_b, inp, s1), "C": ex.submit(scenario_c, inp, s1, keys),
                   "D": ex.submit(scenario_d, inp, s1), "E": ex.submit(scenario_e, inp, s1, keys)}
        return {"A": {"state": "기억 없음 (처음 리허설)", "session1": s1}, **{k: f.result() for k, f in futures.items()}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--llm", default="solar")
    args = ap.parse_args()
    load_env()
    fx = load_fixtures()
    inp = {"graph": fx["graph"], "slidedoc": fx["slidedoc"], "claims": fx["claims"], "ctx": fx["context"], "llm": args.llm}
    keys = load_keys()
    out = OUT / args.tag
    out.mkdir(parents=True, exist_ok=True)
    for r in range(args.reps):
        p = out / f"rep{r}.json"
        if p.exists():
            print(f"skip {p}")    # 이미 돈 회차는 건너뛴다 — --reps 를 늘려 이어 돌릴 수 있다
            continue
        t = time.time()
        p.write_text(json.dumps(one_rep(inp, keys), ensure_ascii=False, indent=1))
        print(f"rep{r} {time.time() - t:.0f}s → {p}")


if __name__ == "__main__":
    main()
