#!/usr/bin/env python3
"""
네 모델 Q&A 앙상블 실험 판 하나 = (덱 × 반복 × 방식). 지금 방식(release: 1차 심사 Solar → 문장 EXAONE → 가드) 과
앙상블(f08_ensemble)을 **같은 덱·같은 답**으로 돌리고, 질문 세트를 가린 심판단이 핵심성 체크리스트로 매긴다.

    AI_CALLLOG=all AI_CALLLOG_DIR=/data/models/_runs/qa-ensemble/calllog \\
      python etc/bench/calllog_run.py etc/bench/qa_ensemble_bench.py --deck A1 --rep 0 --out /data/models/_runs/qa-ensemble/runs/X

계획·기준: docs/qa-ensemble/PLAN.md. 판정 집계는 qa_ensemble_report.py (기준표 → 실측·통과/미달·잡음 폭).
한 판의 산출: <out>/<deck>-r<rep>.json — 질문 세트·후보 묶음·흐름(1·2번 답 유형별 3·4번)·판정·심판 점수·지연·호출.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import traceback
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "main"), str(ROOT / "etc"), str(ROOT)]

from pipeline.config import load_dotenv  # noqa: E402

load_dotenv()
from pipeline import _ai_calllog  # noqa: E402
from pipeline import _ens_slots as ES  # noqa: E402
from pipeline import f08_ensemble as FE  # noqa: E402
from pipeline import build_questions, judge_answer, triage_questions  # noqa: E402
from pipeline.contracts import ClaimDoc, ConceptGraph, Context, Question, SlideDoc, Transcript  # noqa: E402
from pipeline.providers.llm_impl import REGISTRY  # noqa: E402

BUNDLES = {
    # dev — 프롬프트·규칙은 이것으로만 고친다 (공학 · 사회과학 · 생활/심리 · 금융 · 제품/의료 피치)
    "A1": "/data/models/_runs/qa-route/bundles/booth_A1_battery.json",
    "C1": "/data/models/_runs/qa-route/bundles/booth_C1_delivery.json",
    "sleep": "/data/models/_runs/qa-route/bundles/sleep_fixture.json",
    "invest": "/data/models/_runs/qa-ensemble/bundles/investor_gap.json",
    "pitch": "/data/models/_runs/qa-ensemble/bundles/chuck_pitch.json",
    # test — 게이트·마지막에만 (환경과학 · 의학/생활 · 영문 임상 증례 · 의학 논문)
    "B1": "/data/models/_runs/qa-route/bundles/booth_B1_microplastic.json",
    "glucose": "/data/models/_runs/qa-route/bundles/held_health_glucose.json",
    "iohexol": "/data/models/_runs/qa-ensemble/bundles/iohexol_case.json",
    "vitd": "/data/models/_runs/qa-ensemble/bundles/vitd_kim2011.json",
    # test 늘림 (etc/labs/qa_bench/corpus — 녹음 없는 덱은 「자료만으로」 경로를 본다): 인문 · 정책 · 사업 IR · 과학 · 의료 서비스(녹음 있음)
    "novel": "/data/models/_runs/qa-ensemble/bundles/hum_novel.json",
    "jeonse": "/data/models/_runs/qa-ensemble/bundles/policy_jeonse.json",
    "banchan": "/data/models/_runs/qa-ensemble/bundles/ir_banchan.json",
    "led": "/data/models/_runs/qa-ensemble/bundles/sci_led.json",
    "clinic": "/data/models/_runs/qa-ensemble/bundles/clinic.json",
}
DEV = ("A1", "C1", "sleep", "invest", "pitch")
TEST = ("B1", "glucose", "iohexol", "vitd", "novel", "jeonse", "banchan", "led", "clinic")
JUDGES = ("solar4", "ax", "exaone", "midm")
FAMILY = {"solar": "solar", "solar4": "solar", "solar4r": "solar", "ax": "ax", "exaone": "exaone", "midm": "midm"}

# 답 유형 (1·2번) — 흐름이 답에 반응하는지 본다
UNRELATED = "저희 팀은 지난 분기에 물류 창고 세 곳의 재고 회전율을 비교했고, 동절기 배송 지연이 반품률을 끌어올린다는 결론을 얻었어요."
VAGUE = "음… 자료에 나온 대로 그런 결과가 나왔다고 봐요. 상황마다 좀 다를 것 같아요."
UNKNOWN = "잘 모르겠어요."
SHORT = "그냥 그래서 그런 거임"
FLOWS = {"good-good": ("good", "good"), "vague-partial": ("vague", "partial"), "unknown-wrong": ("unknown", "wrong")}

CORE_SYSTEM = """당신은 발표 Q&A 품질 심사관이다. 작성자는 가려져 있다. 질문마다 아래를 매긴다. 길이·말투가 아니라 내용으로 판단한다.
- core (1~5): 이 질문에 잘 답하려면 자료의 **핵심 논리**를 이해해야 한다(5) ↔ 자료를 외우거나 찾아 읽기만 해도 답한다(1)
- open_book (true/false): 자료를 펼쳐 놓고 찾아 읽기만 하면 답할 수 있다
- transplant (true/false): 이 질문을 다른 발표에 그대로 붙여도 말이 된다 (뻔한 질문)
- micro (true/false): 숫자·용어·장 번호·말과 자료의 작은 차이를 확인하는 질문이다
- deep (true/false): 왜·어떻게 이어지나·만약에·어디까지 맞나·충분한가 를 묻는다 (단답 확인형이면 false)
- single (true/false): 한 번에 하나만 묻는다
- grounded (1~5): 질문의 전제가 자료와 맞다(5) ↔ 자료에 없는 사실을 깐다(1). trap=true 질문은 일부러 틀린 전제라 null
- reason: 근거 한 줄 (core 판단의 까닭을 먼저 생각하고 쓴다)
출력은 JSON 객체 하나: {"scores": [{"id": "Q01", "reason": "…", "core": 4, "open_book": false, "transplant": false, "micro": false, "deep": true, "single": true, "grounded": 5}]}"""

PAIR_SYSTEM = """당신은 발표 Q&A 심사위원장이다. 같은 발표에 대해 두 질문 묶음(A·B, 각 2문항 — 발표가 끝나고 처음 받을 질문)을 비교한다.
기준: 발표자가 자료의 **핵심을 간파했는지** 더 잘 드러내는 묶음 (숫자·용어 확인, 뻔한 질문, 틀린 전제는 감점).
먼저 근거를 두세 가지 쓰고, 그다음 고른다. 출력은 JSON 하나: {"reasons": ["…", "…"], "winner": "A" | "B" | "tie"}"""

SUMMARY_SYSTEM = """당신은 이 발표의 요약 몇 줄만 들은 청중이다. 질문마다, 요약에 나온 주장들과 그 사이의 논리만으로 답의 **골자**(왜 그런지·어떻게 이어지는지·어디까지 맞는지)를 말할 수 있으면 true 다.
요약에 없는 세부(특정 숫자·표의 값·특정 장의 문구·용어 정의)를 꼭 봐야만 답할 수 있으면 false 다. 답이 완벽할 필요는 없다 — 방향을 잡을 수 있으면 true.
먼저 질문마다 판단 근거를 짧게 생각하고, 출력은 JSON 하나: {"items": [{"id": "Q01", "answerable": true}]}"""


def load(name: str) -> dict:
    return json.loads(Path(BUNDLES[name]).read_text(encoding="utf-8"))["session"]["artifacts"]


def _complete_json(llm, system, user, max_tokens=2500):
    calls: list = []
    data = FE._complete(llm, "bench", calls, system=system, user=user, temperature=0.0, max_tokens=max_tokens)
    return data, (calls[-1].to_dict() if calls else {})


# ─── 질문 만들기 ────────────────────────────────────────────────────────────────────────────

def run_release(art: dict, track: str = "10") -> dict:
    """지금 방식 (서비스 기본 경로 llm=None — 1차 심사 Solar · 문장 EXAONE(마감 20초→Solar) · 가드 · 모범답 정리)."""
    t0 = time.monotonic()
    g = ConceptGraph.from_dict(art["concept_graph"])
    ctx = Context.from_dict(art.get("context") or {})
    claims = ClaimDoc.from_dict(art["claims"]) if art.get("claims") else None
    tri = triage_questions(g, art.get("alignment_doc"), art.get("flow_diff"), ctx, transcript=art.get("transcript"),
                           slidedoc=art.get("slide_doc"), claims=claims)
    t1 = time.monotonic()
    qd = build_questions(g, tri, track=track, alignment=art.get("alignment_doc"), flow=art.get("flow_diff"),
                         transcript=art.get("transcript"), slidedoc=art.get("slide_doc"), context=ctx, claims=claims)
    return {"questions": [q.to_dict() for q in qd.questions], "model": qd.model,
            "sec": {"triage": round(t1 - t0, 2), "questions": round(time.monotonic() - t1, 2)}}


def run_ensemble(art: dict, args, seed: int) -> dict:
    pool = FE.build_pool(art["concept_graph"], art["slide_doc"], art.get("claims"), transcript=art.get("transcript"),
                         models=args.models, peer=True, peer_self=args.peer_self, seed=seed, prompt=args.prompt,
                         assign=args.assign)
    t0 = time.monotonic()
    opening = FE.pick_opening(pool, art.get("transcript"))
    pick_sec = time.monotonic() - t0
    five = FE.pick_session(pool, art.get("transcript"), 5)
    return {"pool": pool.to_dict(), "opening": opening, "five": five, "pick_opening_ms": round(pick_sec * 1000, 2)}


# ─── 흐름: 1·2번 답 유형 → 음성 3번 → 4번 ─────────────────────────────────────────────────────────

def answer_for(kind: str, q: Question) -> str:
    gist = q.answer_gist or ""
    return {"good": gist, "vague": VAGUE, "wrong": UNRELATED, "unknown": UNKNOWN, "short": SHORT,
            "partial": (re.split(r"(?<=[.?!요])\s+", gist)[0][: max(12, len(gist) // 2)] if gist else VAGUE)}[kind]


def judge(q: Question, answer: str, art: dict, prior=None, history=None) -> dict:
    t0 = time.monotonic()
    try:
        v = judge_answer(q, answer, graph=art["concept_graph"], alignment=art.get("alignment_doc"),
                         transcript=art.get("transcript"), context=art.get("context"), slidedoc=art.get("slide_doc"),
                         prior_answers=prior or [], history=history or [])
        return {"verdict": v.verdict, "score": v.score, "passed": v.passed, "followup": v.followup,
                "missing": list(getattr(v, "missing_points", []) or [])[:3], "sec": round(time.monotonic() - t0, 2)}
    except Exception as e:  # noqa: BLE001
        return {"verdict": "error", "error": f"{type(e).__name__}: {str(e)[:160]}", "sec": round(time.monotonic() - t0, 2)}


def run_flow(flow: str, ens: dict, art: dict, args, seed: int) -> dict:
    """1·2번 답(유형) → 음성 1차(발표 끝에 시작) → 3번 고르기 → 3번 답(좋은 답) → 음성 2차(앞 답 반영) → 4번."""
    pool = _pool_from(ens["pool"])
    opening = [c for c in ens["opening"]]
    qs = [FE.to_question(c, i + 1) for i, c in enumerate(opening)]
    a_kinds = FLOWS[flow]
    asked, turns = [], []
    t_flow = time.monotonic()
    # 음성 1차는 발표 끝에 시작 — 1·2번 답과 동시에 돈다
    with ThreadPoolExecutor(1) as ex:
        fut = ex.submit(_ai_calllog.carry(FE.voice_round), pool, art["concept_graph"], art["slide_doc"],
                        art.get("transcript"), alignment=art.get("alignment_doc"), asked=[], claims=art.get("claims"),
                        models=args.models)
        for i, (q, kind) in enumerate(zip(qs, a_kinds)):
            ans = answer_for(kind, q)
            v = judge(q, ans, art)
            asked.append({"question": q.question, "node_id": q.node_id, "answer": ans, "verdict": v["verdict"],
                          "missing": v.get("missing")})
            turns.append({"n": i + 1, "q": q.question, "by": opening[i].get("model"), "kind": kind, **v})
        vr1 = fut.result()
    judge_sec = sum(t.get("sec", 0) for t in turns)
    # 사용자 답 시간 가정: 30초 · 10초 — 음성 1차가 그 안에 끝났나 (대신 냈나)
    ready_30 = vr1.sec <= 2 * 30 + judge_sec
    ready_10 = vr1.sec <= 2 * 10 + judge_sec
    pick_calls: list = []
    t0 = time.monotonic()
    nxt3 = FE.choose_next(pool, vr1, asked, picker=args.picker, seed=seed, calls=pick_calls)
    pick3 = time.monotonic() - t0
    out = {"flow": flow, "turns": turns, "voice1": _vr_dict(vr1), "ready_30": ready_30, "ready_10": ready_10,
           "pick3_sec": round(pick3, 2), "q3": _brief(nxt3), "pick_calls": [c.to_dict() for c in pick_calls]}
    if not nxt3:
        return out
    q3 = FE.to_question(nxt3, 3)
    v3 = judge(q3, answer_for("vague" if a_kinds[0] != "good" else "good", q3), art)
    asked.append({"question": q3.question, "node_id": q3.node_id, "answer": "", "verdict": v3["verdict"],
                  "missing": v3.get("missing")})
    out["turns"].append({"n": 3, "q": q3.question, "by": nxt3.get("model"), **v3})
    if args.voice2:
        vr2 = FE.voice_round(pool, art["concept_graph"], art["slide_doc"], art.get("transcript"),
                             alignment=art.get("alignment_doc"), asked=asked, claims=art.get("claims"), models=args.models)
        t0 = time.monotonic()
        nxt4 = FE.choose_next(pool, vr2, asked, picker=args.picker, seed=seed + 1, calls=pick_calls)
        out.update({"voice2": _vr_dict(vr2), "ready4_30": vr2.sec <= 30 + v3.get("sec", 0),
                    "pick4_sec": round(time.monotonic() - t0, 2), "q4": _brief(nxt4)})
    out["flow_sec"] = round(time.monotonic() - t_flow, 2)
    return out


def _brief(c: dict) -> dict:
    keys = ("uid", "model", "slot", "signal", "signal_kind", "signal_note", "node_id", "label", "pattern", "question",
            "answer", "lines", "substituted", "pick_reason", "pick_failed", "peer", "slide_no", "quote")
    return {k: c.get(k) for k in keys if k in c}


def _vr_dict(vr) -> dict:
    return {"signals": vr.signals, "candidates": [_brief(c) for c in vr.candidates], "dropped": vr.dropped,
            "calls": [c.to_dict() for c in vr.calls], "sec": vr.sec}


def _pool_from(d: dict) -> FE.Pool:
    slots = [ES.Slot(**{k: v for k, v in s.items() if k not in ("pattern_desc", "angle")}) for s in d["slots"]]
    return FE.Pool(slots=slots, candidates=d["candidates"], dropped=d["dropped"], models=d.get("models", []))


# ─── 평가 ───────────────────────────────────────────────────────────────────────────────────

def summary_text(art: dict) -> str:
    """코드가 조립한 3~5문장 요약 — 루트 + 1단계 주장 (기술조사 §1-3 B: 요약을 LLM 이 쓰면 지엽적일 수 있다)."""
    g = ConceptGraph.from_dict(art["concept_graph"])
    root = ES._root(g)
    claims = sorted([n for n in g.nodes if n.kind == "claim"], key=lambda n: -float(n.weight or 0))[:5]
    kids = claims or sorted([n for n in g.nodes if n is not root], key=lambda n: -float(n.weight or 0))[:5]
    lines = [f"핵심 주장: {root.label}" if root else ""] + [f"- {n.label}" + (f" ({n.summary})" if n.summary and n.summary != n.label else "")
                                                         for n in kids]
    return "\n".join(x for x in lines if x)


def eval_sets(sets: dict[str, list[dict]], art: dict, args, seed: int) -> dict:
    """세트 이름 → [{id, question, answer, author, node_id, trap}] 를 섞어 가린 채 심판단(JUDGES)에 한 번씩."""
    items = [(name, it) for name, xs in sets.items() for it in xs]
    rng = random.Random(seed)
    rng.shuffle(items)
    keyed = [(f"Q{i:02d}", name, it) for i, (name, it) in enumerate(items, 1)]
    deck = FE.Deck.build(art["concept_graph"], art["slide_doc"], art.get("claims"))
    body = ["[TASK] qa-core-judge", "", f"## 발표의 핵심 주장\n{deck.thesis}", "", "## 자료", ES.deck_block(deck.lines, 160),
            "", "## 질문"]
    body += [f"{k} (trap={'true' if it.get('trap') else 'false'}): {it['question']}" for k, _, it in keyed]
    user = "\n".join(body)
    out = {"keys": [{"id": k, "set": name, **{x: it.get(x) for x in ("question", "author", "node_id", "trap")}}
                    for k, name, it in keyed], "judges": {}, "summary": {}}

    def one(j):
        llm = REGISTRY[j]()
        data, call = _complete_json(llm, CORE_SYSTEM, user, max_tokens=4000)
        rows = {str(r.get("id")): r for r in (data.get("scores") or []) if isinstance(r, dict)}
        return j, {"rows": rows, "call": call}

    with _ai_calllog.feature_scope("F-08-bench"), ThreadPoolExecutor(len(args.judges)) as ex:
        for j, res in ex.map(_ai_calllog.carry(one), args.judges):
            out["judges"][j] = res
    # 요약만 보고 답할 수 있나 (핵심성 B) — 질문을 안 쓴 심판 하나(solar4)
    sm = ["[TASK] qa-summary-answerable", "", "## 발표 요약", summary_text(art), "", "## 질문"]
    sm += [f"{k}: {it['question']}" for k, _, it in keyed]
    with _ai_calllog.feature_scope("F-08-bench"):
        data, call = _complete_json(REGISTRY[args.summary_judge](), SUMMARY_SYSTEM, "\n".join(sm), max_tokens=1500)
    out["summary"] = {"rows": {str(r.get("id")): bool(r.get("answerable")) for r in (data.get("items") or [])
                               if isinstance(r, dict)}, "call": call}
    return out


def pairwise(a: list[dict], b: list[dict], art: dict, args) -> list[dict]:
    """release 1·2번 vs ensemble 1·2번 — 심판마다 자리 바꿔 두 번. 둘 다 같은 쪽이면 승, 아니면 무."""
    deck = FE.Deck.build(art["concept_graph"], art["slide_doc"], art.get("claims"))
    head = ["[TASK] qa-pairwise", "", f"## 발표의 핵심 주장\n{deck.thesis}", "", "## 자료", ES.deck_block(deck.lines, 140)]

    def ask(j, first, second):
        user = "\n".join(head + ["", "## A", *[f"- {x['question']}" for x in first], "", "## B",
                                 *[f"- {x['question']}" for x in second]])
        data, call = _complete_json(REGISTRY[j](), PAIR_SYSTEM, user, max_tokens=800)
        return str((data or {}).get("winner", "")).strip().upper(), (data or {}).get("reasons", []), call

    rows = []

    def one(j):
        w1, r1, c1 = ask(j, a, b)      # A=release
        w2, r2, c2 = ask(j, b, a)      # A=ensemble
        v1 = {"A": "release", "B": "ensemble"}.get(w1, "tie")
        v2 = {"A": "ensemble", "B": "release"}.get(w2, "tie")
        return {"judge": j, "order1": v1, "order2": v2, "winner": v1 if v1 == v2 else "tie", "reasons": [r1, r2],
                "calls": [c1, c2]}

    with _ai_calllog.feature_scope("F-08-bench"), ThreadPoolExecutor(len(args.judges)) as ex:
        rows = list(ex.map(_ai_calllog.carry(one), args.judges))
    return rows


def gist_checks(qs: list[Question], art: dict) -> list[dict]:
    """1단계: 모범답 그대로 → good? · 외운 답(근거 자료 줄 그대로 읽기) vs 이해한 답(모범답)이 다르게 판정되나."""
    rows = []
    for q in qs:
        g = judge(q, q.answer_gist, art)
        rec = q.evidence_quote or ""
        m = judge(q, f"자료에는 「{rec}」라고 나와 있어요.", art) if rec and not q.trap else {}
        rows.append({"id": q.id, "question": q.question, "gist": q.answer_gist, "checks": (q.basis.checks if q.basis else []),
                     "good_verdict": g.get("verdict"), "good_score": g.get("score"), "good_passed": g.get("passed"),
                     "memo_verdict": m.get("verdict"), "memo_score": m.get("score"), "trap": q.trap})
    return rows


# ─── 판 하나 ────────────────────────────────────────────────────────────────────────────────

def reeval(args) -> int:
    """심판 프롬프트를 고친 뒤 같은 질문으로 다시 잰다 — 생성 잡음 없이 심판만 비교."""
    args.judges = [j for j in args.judges.split(",") if j]
    rec = json.loads(args.reeval.read_text(encoding="utf-8"))
    art = load(rec["deck"])
    seed = zlib.crc32(f"{rec['deck']}:{rec['rep']}:{rec.get('tag', '')}".encode()) % 10_000
    sets: dict = {}
    for k in rec.get("eval", {}).get("keys", []):
        sets.setdefault(k["set"], []).append({x: k.get(x) for x in ("question", "author", "node_id", "trap")})
    rec["eval_prev"] = rec.get("eval")
    rec["eval"] = eval_sets(sets, art, args, seed)
    out = args.out / args.reeval.name
    out.write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"다시 잼: {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True)
    ap.add_argument("--rep", type=int, default=0)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--modes", default="release,ensemble")
    ap.add_argument("--models", default="solar,ax,midm,exaone")
    ap.add_argument("--picker", default="solar4")
    ap.add_argument("--judges", default=",".join(JUDGES))
    ap.add_argument("--summary-judge", default="solar4")
    ap.add_argument("--prompt", default="guide")
    ap.add_argument("--assign", default="all", help="실험 판은 비교를 위해 all 이 기본 (서비스 기본은 f08_ensemble.assign_mode)")
    ap.add_argument("--peer-self", action="store_true", default=True)
    ap.add_argument("--flows", default=",".join(FLOWS))
    ap.add_argument("--voice2", action="store_true", default=True)
    ap.add_argument("--no-eval", action="store_true")
    ap.add_argument("--tag", default="")
    ap.add_argument("--reeval", type=Path, help="저장된 판 JSON 의 평가(심판단·요약·짝 비교)만 다시 — 생성은 그대로")
    args = ap.parse_args()
    if args.reeval:
        return reeval(args)
    args.models = [m for m in args.models.split(",") if m]
    args.judges = [j for j in args.judges.split(",") if j]
    args.out.mkdir(parents=True, exist_ok=True)
    art = load(args.deck)
    seed = zlib.crc32(f"{args.deck}:{args.rep}:{args.tag}".encode()) % 10_000
    rec = {"deck": args.deck, "rep": args.rep, "tag": args.tag, "split": "dev" if args.deck in DEV else "test",
           "args": {k: v for k, v in vars(args).items() if k != "out"}, "t_start": time.time()}
    modes = args.modes.split(",")
    with ThreadPoolExecutor(2) as ex:
        f_rel = ex.submit(_ai_calllog.carry(run_release), art) if "release" in modes else None
        f_ens = ex.submit(_ai_calllog.carry(run_ensemble), art, args, seed) if "ensemble" in modes else None
        if f_rel:
            try:
                rec["release"] = f_rel.result()
            except Exception as e:  # noqa: BLE001
                rec["release"] = {"error": f"{type(e).__name__}: {str(e)[:200]}", "trace": traceback.format_exc()[-800:]}
        if f_ens:
            try:
                rec["ensemble"] = f_ens.result()
            except Exception as e:  # noqa: BLE001
                rec["ensemble"] = {"error": f"{type(e).__name__}: {str(e)[:200]}", "trace": traceback.format_exc()[-800:]}
    ens = rec.get("ensemble") or {}
    rel = rec.get("release") or {}
    if ens.get("opening") and art.get("transcript"):
        rec["flows"] = {}
        for fl in [f for f in args.flows.split(",") if f]:
            try:
                rec["flows"][fl] = run_flow(fl, ens, art, args, seed)
            except Exception as e:  # noqa: BLE001
                rec["flows"][fl] = {"error": f"{type(e).__name__}: {str(e)[:200]}", "trace": traceback.format_exc()[-800:]}
    if not args.no_eval:
        sets = {}
        if rel.get("questions"):
            sets["release"] = [{"question": q["question"], "author": rel.get("model"), "node_id": q["node_id"],
                                "trap": q["trap"]} for q in rel["questions"][:5]]
        if ens.get("five"):
            sets["ensemble"] = [{"question": c["question"], "author": c["model"], "node_id": c["node_id"],
                                 "trap": c["pattern"] == "P9"} for c in ens["five"]]
        for fl, f in (rec.get("flows") or {}).items():
            for k in ("q3", "q4"):
                if f.get(k) and f[k].get("question"):
                    sets.setdefault("voice", []).append({"question": f[k]["question"], "author": f[k].get("model"),
                                                         "node_id": f[k].get("node_id"), "trap": False, "flow": fl, "n": k})
        if sets:
            rec["eval"] = eval_sets(sets, art, args, seed)
        if rel.get("questions") and ens.get("opening"):
            rec["pairwise"] = pairwise(rel["questions"][:2], ens["opening"], art, args)
        gq = [Question.from_dict(q) for q in rel.get("questions", [])[:5]] + \
            [FE.to_question(c, i + 1) for i, c in enumerate(ens.get("five", []))]
        rec["gist"] = gist_checks(gq, art)
    rec["t_end"] = time.time()
    path = args.out / f"{args.deck}-r{args.rep}{('-' + args.tag) if args.tag else ''}.json"
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"저장: {path} · {round(rec['t_end'] - rec['t_start'])}초")
    return 0


if __name__ == "__main__":
    sys.exit(main())
