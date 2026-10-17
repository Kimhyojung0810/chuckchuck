#!/usr/bin/env python3
"""
5단계 판정 · 꼬리질문 대화 엔진 실험 판 (2026-10-17). 1~3단계에서 얼린 질문 세트(앙상블 five + 함정 후보)에
**답 유형 여러 개**(골자 · 자기 말 · 외운 답 · 일부만 · 모호 · 틀린 전제 · 반대 · 엉뚱 · 모름 · 짧은 반말 · 함정 동의)를 넣어
judge_answer(판정 + 꼬리질문 엔진)를 돌리고 한 줄씩 남긴다. 집계는 qa_dialogue_report.py.

    AI_CALLLOG=all AI_CALLLOG_DIR=/data/models/_runs/qa-dialogue/calllog \\
      python etc/bench/calllog_run.py etc/bench/qa_dialogue_bench.py answers --split dev
    ... qa_dialogue_bench.py single --split dev --talk solar4 --judge solar --rep 0 --tag base
    ... qa_dialogue_bench.py stuck --split dev --tag stuck

답 유형은 solar4 한 콜로 질문마다 한 번 만들어 얼린다(F-09-bench, 제출 외) — 모든 조건이 같은 답을 받는다.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "main"), str(ROOT / "etc"), str(ROOT)]

from pipeline.config import load_dotenv  # noqa: E402

load_dotenv()
from pipeline import _ai_calllog  # noqa: E402
from pipeline import f08_ensemble as FE  # noqa: E402
from pipeline import f09_dialogue as DLG  # noqa: E402
from pipeline import judge_answer  # noqa: E402
from pipeline._json_text import extract_json_object  # noqa: E402
from pipeline.contracts import Question  # noqa: E402

OUT = Path(os.environ.get("QA_DLG_OUT") or "/data/models/_runs/qa-dialogue")   # 실험 폴더 — 에이전트마다 따로 (10-17 tune)
ENS_RUNS = Path("/data/models/_runs/qa-ensemble/runs")
BUNDLES = {
    "A1": "/data/models/_runs/qa-route/bundles/booth_A1_battery.json",
    "C1": "/data/models/_runs/qa-route/bundles/booth_C1_delivery.json",
    "sleep": "/data/models/_runs/qa-route/bundles/sleep_fixture.json",
    "invest": "/data/models/_runs/qa-ensemble/bundles/investor_gap.json",
    "pitch": "/data/models/_runs/qa-ensemble/bundles/chuck_pitch.json",
    "B1": "/data/models/_runs/qa-route/bundles/booth_B1_microplastic.json",
    "glucose": "/data/models/_runs/qa-route/bundles/held_health_glucose.json",
    "iohexol": "/data/models/_runs/qa-ensemble/bundles/iohexol_case.json",
    "vitd": "/data/models/_runs/qa-ensemble/bundles/vitd_kim2011.json",
    "novel": "/data/models/_runs/qa-ensemble/bundles/hum_novel.json",
    "jeonse": "/data/models/_runs/qa-ensemble/bundles/policy_jeonse.json",
    "banchan": "/data/models/_runs/qa-ensemble/bundles/ir_banchan.json",
    "led": "/data/models/_runs/qa-ensemble/bundles/sci_led.json",
    "clinic": "/data/models/_runs/qa-ensemble/bundles/clinic.json",
}
DEV = ("A1", "C1", "sleep", "invest", "pitch")
TEST = ("B1", "glucose", "iohexol", "vitd", "novel", "jeonse", "banchan", "led", "clinic")

UNRELATED = "저희 팀은 지난 분기에 물류 창고 세 곳의 재고 회전율을 비교했고, 동절기 배송 지연이 반품률을 끌어올린다는 결론을 얻었어요."
UNKNOWN = "잘 모르겠어요."
KINDS = ("gist", "own", "recital", "memo", "partial", "vague", "premise", "disagree", "unrelated", "unknown", "banmal", "trap_agree")
#: 기대 — 판정이 이 유형에 줘야 하는 것 (good / pass(70+) / notgood / wrong / coach)
EXPECT = {"gist": "good", "own": "pass", "recital": "notgood", "memo": "notgood", "partial": "notgood", "vague": "notgood",
          "premise": "notpass", "disagree": "notgood", "unrelated": "wrong", "unknown": "coach", "banmal": "any",
          "trap_agree": "wrong"}

GEN_SYSTEM = """당신은 발표 Q&A 실험용 **가상 발표자 답**을 쓴다. 질문 · 모범답 · 근거 자료 줄을 보고 아래 유형마다 발표자가 말로 할 법한 답 하나씩.
- own: 모범답과 **같은 논리**를 자기 말로 (모범답 문장을 베끼지 말고 낱말 · 순서를 바꿔, 1~2문장, 해요체 입말).
- partial: 모범답의 논리 중 **절반만** — 결론이나 근거 하나만 말하고 「왜 그런지」 이유 고리는 빠뜨린다 (1문장).
- vague: 이 주제의 낱말을 한두 개 쓰지만 핵심을 흐리는 답 (「좀 다를 것 같아요」「상황마다」 같은 말, 1문장).
- premise: 자료와 **사실이 어긋나는** 답 — 조건 · 방향 · 범위 하나를 자신 있게 거꾸로 말한다 (1~2문장).
- disagree: 질문의 전제 · 자료의 결론에 **반대 의견**을 이유 하나와 함께 (1~2문장).
- banmal: 핵심은 맞지만 아주 짧은 반말 (「~임」「~거든」「~인 듯」, 20자 안).
- trap_agree: 질문의 전제를 그대로 받아들이며 「네, 맞아요」 로 시작하는 답 (1문장).
출력은 JSON 하나: {"own": "", "partial": "", "vague": "", "premise": "", "disagree": "", "banmal": "", "trap_agree": ""}"""


def load_art(deck: str) -> dict:
    return json.loads(Path(BUNDLES[deck]).read_text(encoding="utf-8"))["session"]["artifacts"]


def question_set(deck: str) -> list[dict]:
    """1~3단계에서 얼린 앙상블 질문 five (+ 함정 후보 하나). dev 는 dev5 strength r0, test 는 test1 p4 (r0 가 비면 r1)."""
    pats = [f"dev5/{deck}-r0-strength.json"] if deck in DEV else [f"test1/{deck}-r0-p4.json", f"test1/{deck}-r1-p4.json"]
    for pat in pats:
        for f in glob.glob(str(ENS_RUNS / pat)):
            r = json.loads(Path(f).read_text(encoding="utf-8"))
            e = r.get("ensemble") or {}
            five = list(e.get("five") or [])
            if not five:
                continue
            trap = next((c for c in (e.get("pool") or {}).get("candidates", []) if c.get("pattern") == "P9" and c.get("trap")), None)
            if trap is not None and all(c.get("uid") != trap.get("uid") for c in five):
                five.append(trap)
            return five
    return []


def evidence_lines(q: Question, art: dict) -> list[str]:
    sd = art.get("slide_doc") or {}
    no = q.evidence_slide_no or (q.slide_nos[0] if q.slide_nos else 0)
    for s in sd.get("slides", []):
        if s.get("slide_no") == no:
            text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s.get("raw_text") or "")
            return [x.strip(" -#*") for x in text.splitlines() if len(x.strip(" -#*")) >= 6][:8]
    return [q.evidence_quote] if q.evidence_quote else []


def gen_answers(args) -> int:
    from pipeline.providers.llm_impl import get_llm
    llm = get_llm("solar4")
    decks = DEV if args.split == "dev" else TEST if args.split == "test" else tuple(args.split.split(","))
    for deck in decks:
        path = OUT / "answers" / f"{deck}.json"
        if path.exists() and not args.force:
            print("있음", path)
            continue
        art = load_art(deck)
        qs = question_set(deck)
        rows = []

        def one(i_c):
            i, c = i_c
            q = FE.to_question(c, i + 1)
            ev = evidence_lines(q, art)
            user = (f"질문: {q.question}\n모범답: {q.answer_gist}\n근거 자료 줄:\n" + "\n".join(f"- {x}" for x in ev)
                    + (f"\n함정 질문의 틀린 전제: {c['trap'].get('premise', '')}" if c.get("trap") else ""))
            with _ai_calllog.feature_scope("F-09-bench"):
                try:
                    raw = llm.complete(system=GEN_SYSTEM, user=user, temperature=0.5, max_tokens=900, json_mode=True)
                    gen = extract_json_object(raw)
                except Exception as e:  # noqa: BLE001
                    gen = {"error": str(e)[:200]}
            recital = " ".join(ev[:2]) if ev else (q.evidence_quote or "")
            answers = {"gist": q.answer_gist, "own": gen.get("own", ""), "recital": recital,
                       "memo": f"자료에는 「{q.evidence_quote}」라고 나와 있어요." if q.evidence_quote else "",
                       "partial": gen.get("partial", ""), "vague": gen.get("vague", ""), "premise": gen.get("premise", ""),
                       "disagree": gen.get("disagree", ""), "unrelated": UNRELATED, "unknown": UNKNOWN,
                       "banmal": gen.get("banmal", ""), "trap_agree": gen.get("trap_agree", "") if c.get("trap") else ""}
            return {"i": i, "cand": c, "answers": {k: v for k, v in answers.items() if (v or "").strip()}}

        with ThreadPoolExecutor(4) as ex:
            rows = list(ex.map(_ai_calllog.carry(one, "F-09-bench"), list(enumerate(qs))))
        path.write_text(json.dumps({"deck": deck, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("만듦", path, len(rows))
    return 0


def _judge(q: Question, answer: str, art: dict, *, judge_llm, prior=None, history=None, give_up=False, avoid=None) -> dict:
    """판정 한 번. 요청 제한(429)으로 실패하면 물러났다 다시 (실험 판에서 오류 줄이 기준표를 흔들지 않게) — 시간은 마지막 시도만."""
    for wait in (8, 20, 40, None):
        d = _judge_once(q, answer, art, judge_llm=judge_llm, prior=prior, history=history, give_up=give_up, avoid=avoid)
        if d.get("verdict") != "error" or wait is None or "429" not in str(d.get("error")):
            return d
        time.sleep(wait)
    return d


def _judge_once(q: Question, answer: str, art: dict, *, judge_llm, prior=None, history=None, give_up=False, avoid=None) -> dict:
    t0 = time.monotonic()
    try:
        v = judge_answer(q, answer, graph=art["concept_graph"], alignment=art.get("alignment_doc"),
                         transcript=art.get("transcript"), context=art.get("context"), slidedoc=art.get("slide_doc"),
                         prior_answers=prior or [], history=history or [], give_up=give_up, llm=judge_llm, avoid=avoid)
        d = v.to_dict()
        d["sec"] = round(time.monotonic() - t0, 2)
        return d
    except Exception as e:  # noqa: BLE001
        return {"verdict": "error", "error": f"{type(e).__name__}: {str(e)[:200]}", "trace": traceback.format_exc()[-600:],
                "sec": round(time.monotonic() - t0, 2)}


def run_single(args) -> int:
    """한 번 답 — (질문 × 답 유형) 판정 + 꼬리질문. 세션 되풀이 금지(avoid)는 덱 안에서 쌓는다(답 유형 순서대로)."""
    os.environ["QA_DIALOGUE_LLM"] = args.talk
    os.environ["QA_DIALOGUE"] = "0" if args.talk == "off" else "1"
    decks = DEV if args.split == "dev" else TEST if args.split == "test" else tuple(args.split.split(","))
    kinds = [k for k in args.kinds.split(",") if k] if args.kinds else list(KINDS)
    out_dir = OUT / "runs" / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    judge_llm = None if args.judge == "default" else args.judge

    def deck_run(deck):
        path = OUT / "answers" / f"{deck}.json"
        if not path.exists():
            return deck, 0
        data = json.loads(path.read_text(encoding="utf-8"))
        art = load_art(deck)
        rows = []
        for r in data["rows"]:
            q = FE.to_question(r["cand"], r["i"] + 1)
            avoid: list[str] = []
            for k in kinds:
                ans = r["answers"].get(k)
                if not ans:
                    continue
                d = _judge(q, ans, art, judge_llm=judge_llm, avoid=list(avoid) if args.avoid else None)
                if d.get("followup"):
                    avoid.append(d["followup"])
                if d.get("react"):
                    avoid.append(d["react"])
                rows.append({"deck": deck, "split": "dev" if deck in DEV else "test", "qid": q.id, "question": q.question,
                             "pattern": r["cand"].get("pattern"), "trap": bool(r["cand"].get("trap")), "gist": q.answer_gist,
                             "kind": k, "answer": ans, "expect": EXPECT[k], "talk": args.talk, "judge": args.judge,
                             "rep": args.rep, **{f: d.get(f) for f in ("verdict", "score", "passed", "mastered", "guard", "react",
                                                                      "followup", "move", "anchor", "dialogue", "coach_stage",
                                                                      "close_reason", "missing_points", "sec", "error",
                                                                      "guard_reason", "claim")},
                             "grounds": [{"role": g.get("role"), "slide_no": g.get("slide_no"), "text": (g.get("text") or "")[:120]}
                                         for g in (d.get("grounds") or []) if isinstance(g, dict)]})
        f = out_dir / f"{deck}-r{args.rep}.jsonl"
        f.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n", encoding="utf-8")
        return deck, len(rows)

    with ThreadPoolExecutor(args.par) as ex:
        for deck, n in ex.map(_ai_calllog.carry(deck_run), decks):
            print(f"{args.tag} {deck} r{args.rep}: {n}줄", flush=True)
    return 0


#: 갇힘 대본 — 같은 질문에 계속 틀린 답 · 모르겠어요.
STUCK_SCRIPTS = {
    "wrong4": ["unrelated", "vague", "premise", "unrelated"],
    "giveup2": ["__giveup__", "__giveup__", "__giveup__"],
    "mixed": ["vague", "__giveup__", "partial", "vague"],
    "partial4": ["partial", "partial", "vague", "partial"],
}


def run_stuck(args) -> int:
    """여러 턴 — 대본대로 같은 질문에 계속 답해 몇 번째에 닫히는지(갇힘), 꼬리질문이 턴마다 바뀌는지(R9)."""
    os.environ["QA_DIALOGUE_LLM"] = args.talk
    decks = DEV if args.split == "dev" else TEST if args.split == "test" else tuple(args.split.split(","))
    out_dir = OUT / "runs" / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    judge_llm = None if args.judge == "default" else args.judge

    def deck_run(deck):
        data = json.loads((OUT / "answers" / f"{deck}.json").read_text(encoding="utf-8"))
        art = load_art(deck)
        rows = []
        for r in data["rows"][: args.max_q]:
            q = FE.to_question(r["cand"], r["i"] + 1)
            for name, script in STUCK_SCRIPTS.items():
                history, prior, turns = [], [], []
                asked_now = q.question
                for t, k in enumerate(script):
                    give_up = k == "__giveup__"
                    ans = "" if give_up else r["answers"].get(k, UNKNOWN)
                    d = _judge(q, ans or "(모르겠어요)", art, judge_llm=judge_llm, prior=prior, history=history,
                               give_up=give_up)
                    turns.append({"t": t + 1, "kind": k, "answer": ans, **{f: d.get(f) for f in (
                        "verdict", "score", "mastered", "closed", "coach_stage", "close_reason", "react", "followup", "move",
                        "anchor", "explanation", "sec", "error")}})
                    history.append({"질문": asked_now, "답변": ans or "(모르겠어요)", "판정": d.get("verdict") or "unknown",
                                    "question_id": q.id, "포기": give_up})
                    if not give_up:
                        prior.append(ans)
                    if d.get("mastered") or d.get("coach_stage") == "explain":
                        break
                    asked_now = d.get("followup") or asked_now
                rows.append({"deck": deck, "qid": q.id, "script": name, "turns": turns,
                             "closed_at": turns[-1]["t"] if (turns[-1].get("mastered") or turns[-1].get("coach_stage") == "explain") else None})
        (out_dir / f"{deck}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        return deck, len(rows)

    with ThreadPoolExecutor(args.par) as ex:
        for deck, n in ex.map(_ai_calllog.carry(deck_run), decks):
            print(f"stuck {deck}: {n}", flush=True)
    return 0


def run_traps(args) -> int:
    """함정 질문(지금 방식이 만든 P9 · trap_premise) — 동의 둘(wrong 기대) · 바로잡은 모범답(통과 기대). 기존 판정 정확도 유지 확인."""
    os.environ["QA_DIALOGUE_LLM"] = args.talk
    os.environ["QA_DIALOGUE"] = "0" if args.talk == "off" else "1"
    judge_llm = None if args.judge == "default" else args.judge
    seen, jobs = set(), []
    for f in sorted(glob.glob(str(ENS_RUNS / "*" / "*.json"))):
        try:
            r = json.loads(Path(f).read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        deck = r.get("deck")
        if deck not in BUNDLES:
            continue
        for qd in ((r.get("release") or {}).get("questions") or []):
            if qd.get("trap") and qd.get("trap_premise") and qd["question"] not in seen:
                seen.add(qd["question"])
                jobs.append((deck, qd))
    out_dir = OUT / "runs" / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    arts = {}

    def one(job):
        deck, qd = job
        q = Question.from_dict(qd)
        art = arts.setdefault(deck, load_art(deck))
        prem = (q.trap_premise.premise if q.trap_premise else "").strip().rstrip(".")
        answers = {"trap_agree": "네, 맞아요. 자료에 그렇게 나와 있어요.", "trap_echo": f"네, {prem}. 그래서 그렇게 된 거예요.",
                   "trap_fix": q.answer_gist}
        rows = []
        for k, a in answers.items():
            if not (a or "").strip():
                continue
            d = _judge(q, a, art, judge_llm=judge_llm)
            rows.append({"deck": deck, "qid": q.id, "question": q.question, "kind": k, "answer": a, "gist": q.answer_gist,
                         "expect": "pass" if k == "trap_fix" else "wrong", "rep": args.rep,
                         **{f: d.get(f) for f in ("verdict", "score", "passed", "guard", "react", "followup", "move", "dialogue",
                                                  "coach_stage", "sec", "error")}})
        return rows

    with ThreadPoolExecutor(args.par) as ex:
        rows = [x for rs in ex.map(_ai_calllog.carry(one), jobs) for x in rs]
    (out_dir / f"traps-r{args.rep}.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n",
                                                      encoding="utf-8")
    print(f"traps {len(jobs)}문항 {len(rows)}줄")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["answers", "single", "stuck", "traps"])
    ap.add_argument("--split", default="dev")
    ap.add_argument("--talk", default="solar4", help="꼬리질문 엔진 모델 (off = 엔진 끔)")
    ap.add_argument("--judge", default="default", help="판정 모델 (default = REASONING_BACKEND)")
    ap.add_argument("--rep", type=int, default=0)
    ap.add_argument("--tag", default="x")
    ap.add_argument("--kinds", default="")
    ap.add_argument("--par", type=int, default=5)
    ap.add_argument("--max-q", type=int, default=3)
    ap.add_argument("--avoid", action="store_true", default=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    return {"answers": gen_answers, "single": run_single, "stuck": run_stuck, "traps": run_traps}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
