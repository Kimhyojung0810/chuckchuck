#!/usr/bin/env python3
"""
5단계 실험실 퍼널 시뮬레이션 — 「2번 질문 도달」 · 「wrong 직후 계속」 을 **추정**한다 (2026-10-17). 실측이 아니다.

두 갈래:
1) 구조 시뮬레이션 (LLM 없음) — 가상 방문자가 답 유형을 섞어 낸다. 판정 결과는 실험 판(qa_dialogue_bench single)의 답 유형별 실측
   판정을 그대로 뽑아 쓴다. 방문자의 인내(같은 질문에 몇 번까지 답하나)는 10/7 부스 실측 분포(같은 질문 시도 1·1·1·1·3·4·7·7·10·17·19·25·26)에서.
   옛 흐름: 질문은 good 이거나 셋째 답부터 통과(70+)일 때만 닫힌다. 새 흐름: 셋째 답 · 둘째 「모르겠어요」 에 해설로 닫힌다.
2) 가상 방문자 반응 (LLM, 말하기에 안 쓴 모델) — wrong 판정 화면 글(판정 낱말 + 반응 + 꼬리질문)을 보여 주고 「계속 답한다 / 그만둔다」 를
   고르게 한다. 옛 글(엔진 끔)과 새 글(엔진 켬)을 같은 답에 견준다. 사람 이탈의 대용일 뿐이다.

    python etc/bench/qa_dialogue_funnel.py --new t1-solar4 --old j0-solar4 --persona-llm ax --out funnel.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "main"), str(ROOT / "etc"), str(ROOT)]

from pipeline.config import load_dotenv  # noqa: E402

load_dotenv()
from pipeline import _ai_calllog  # noqa: E402
from pipeline._json_text import extract_json_object  # noqa: E402

OUT = Path("/data/models/_runs/qa-dialogue")
#: 10/7 부스 실측 — (방문, 질문) 쌍마다 같은 질문에 낸 답 수 (실사용_QA_데이터분석 §3-4)
BOOTH_PATIENCE = [1, 1, 1, 1, 3, 4, 7, 7, 10, 17, 19, 25, 26]
#: 가상 방문자 묶음 — 답 유형 섞기 (부스: 자기가 발표하지 않은 자료 · 외부: 자기 자료 발표자)
VISITORS = {
    "booth": {"unrelated": .25, "vague": .25, "unknown": .15, "partial": .15, "banmal": .1, "premise": .1},
    "external": {"own": .25, "partial": .25, "vague": .15, "premise": .1, "recital": .1, "banmal": .1, "unknown": .05},
}
OLD_WORD = {"good": "설득 완료", "partial": "부분 인정", "wrong": "미방어", "unknown": "판정 보류"}
NEW_WORD = {"good": "설득 완료", "partial": "부분 인정", "wrong": "다시 짚어요", "unknown": "판정 보류"}

PERSONA_SYSTEM = """당신은 발표 연습 앱을 처음 써 보는 대학생이다. 방금 AI 교수의 질문에 답했고, 아래가 화면에 뜬 판정과 교수의 말이다.
이 화면을 본 직후 **계속 답할지, 앱을 닫고 떠날지** 고른다. 판단 기준은 당신의 기분이다 — 무시당하거나 같은 말을 되풀이 듣거나
무엇을 해야 할지 모르겠으면 떠나고, 내 말을 들었다고 느끼고 다음에 할 일이 분명하면 계속한다.
JSON 하나: {"reason": "한 줄", "stay": true}"""


def load(tag: str) -> list[dict]:
    rows = []
    for f in sorted((OUT / "runs" / tag).glob("*.jsonl")):
        rows += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if r.get("verdict") != "error"]


def outcome_table(rows: list[dict]) -> dict:
    """답 유형 → 판정 결과 목록 (passed · verdict)."""
    t: dict = {}
    for r in rows:
        t.setdefault(r["kind"], []).append({"verdict": r["verdict"], "passed": bool(r.get("passed")), "good": r["verdict"] == "good"})
    return t


#: 10/7 부스 실측 — 첫 wrong 직후 이탈 82% (계속 0.18)
BOOTH_STAY_AFTER_WRONG = 0.18


def simulate(table: dict, mix: dict, *, new: bool, n: int = 4000, seed: int = 7, stay_after_wrong: float = 1.0) -> dict:
    """질문 하나(Q1)에서 2번으로 넘어가는가. 인내를 다 쓰기 전에 질문이 닫혀야 2번에 닿는다."""
    rng = random.Random(seed)
    kinds, weights = list(mix), list(mix.values())
    reach, wrong_turns, stuck4 = 0, 0, 0
    for _ in range(n):
        patience = rng.choice(BOOTH_PATIENCE)
        closed, giveups = False, 0
        for attempt in range(1, patience + 1):
            k = rng.choices(kinds, weights)[0]
            if k == "unknown":
                giveups += 1
                if new and (giveups >= 2 or attempt >= 3):
                    closed = True
            else:
                o = rng.choice(table.get(k) or [{"verdict": "wrong", "passed": False, "good": False}])
                wrong_turns += o["verdict"] == "wrong"
                if o["good"] or (attempt >= 3 and o["passed"]) or (new and attempt >= 3):
                    closed = True
                elif o["verdict"] == "wrong" and rng.random() > stay_after_wrong:
                    break                      # wrong 을 보고 떠남
            if attempt >= 4 and not closed:
                stuck4 += 1 if attempt == 4 else 0
            if closed:
                break
        reach += closed
    return {"q2_reach": round(reach / n, 3), "stuck4": round(stuck4 / n, 3)}


def persona_stay(rows_old: list[dict], rows_new: list[dict], model: str) -> dict:
    """같은 질문 · 같은 답에서 wrong 화면의 옛 글 · 새 글을 가상 방문자에게 보이고 「계속」 비율을 잰다."""
    from pipeline.providers.llm_impl import get_llm
    llm = get_llm(model)
    key = lambda r: (r["deck"], r["qid"], r["kind"])  # noqa: E731
    new_by = {key(r): r for r in rows_new}
    pairs = [(o, new_by[key(o)]) for o in rows_old if o["verdict"] == "wrong" and key(o) in new_by
             and new_by[key(o)]["verdict"] in ("wrong", "partial") and not o.get("coach_stage")]

    def screen(r, words):
        return (f"판정: {words.get(r['verdict'], r['verdict'])}\n교수: {r.get('react') or ''}\n"
                + (f"이어서 묻는 말: {r['followup']}" if r.get("followup") else ""))

    def ask(args):
        r, words = args
        user = f"내가 받은 질문: {r['question']}\n내 답: {r['answer']}\n\n화면:\n{screen(r, words)}"
        with _ai_calllog.feature_scope("F-09-bench"):
            for _ in range(3):
                try:
                    return bool(extract_json_object(llm.complete(system=PERSONA_SYSTEM, user=user, temperature=0.0,
                                                                 max_tokens=300, json_mode=True)).get("stay"))
                except Exception:  # noqa: BLE001
                    continue
        return None

    jobs = [(o, OLD_WORD) for o, _ in pairs] + [(n, NEW_WORD) for _, n in pairs]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(_ai_calllog.carry(ask, "F-09-bench"), jobs))
    old, new = res[:len(pairs)], res[len(pairs):]
    o = [x for x in old if x is not None]
    nw = [x for x in new if x is not None]
    return {"pairs": len(pairs), "old_stay": round(sum(o) / len(o), 3) if o else None,
            "new_stay": round(sum(nw) / len(nw), 3) if nw else None, "model": model}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True)
    ap.add_argument("--old", required=True)
    ap.add_argument("--persona-llm", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    rn, ro = load(args.new), load(args.old)
    res = {"structure": {}}
    for name, mix in VISITORS.items():
        res["structure"][name] = {"old": simulate(outcome_table(ro), mix, new=False),
                                  "new": simulate(outcome_table(rn), mix, new=True)}
    if args.persona_llm:
        res["persona"] = per = persona_stay(ro, rn, args.persona_llm)
        # 보정: 가상 방문자의 옛 글 「계속」 비율을 부스 실측(0.18)에 맞춰 새 글에도 같은 배율 — 추정이다
        if per.get("old_stay") and per.get("new_stay") is not None:
            scale = BOOTH_STAY_AFTER_WRONG / per["old_stay"]
            stay_new = min(1.0, per["new_stay"] * scale)
            res["calibrated"] = {"stay_after_wrong_old": BOOTH_STAY_AFTER_WRONG, "stay_after_wrong_new": round(stay_new, 3)}
            for name, mix in VISITORS.items():
                res["calibrated"][name] = {
                    "old": simulate(outcome_table(ro), mix, new=False, stay_after_wrong=BOOTH_STAY_AFTER_WRONG),
                    "new": simulate(outcome_table(rn), mix, new=True, stay_after_wrong=stay_new)}
    txt = json.dumps(res, ensure_ascii=False, indent=1)
    print(txt)
    if args.out:
        Path(args.out).write_text(txt, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
