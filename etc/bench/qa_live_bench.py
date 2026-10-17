#!/usr/bin/env python3
"""
발표를 들으며 질문 준비 — 3번+ 질문이 발표 전체를 반영하나 (2026-10-17, docs/qa-ensemble/LIVE_REPORT.md).

같은 덱 · 같은 묶음 · 같은 1·2번 답으로 두 방식을 짝지어 돌린다 (실 API · 호출 로그):
  base  지금 방식 — 3번+ 는 답마다 네 모델 음성 라운드(앞 답 하나 뒤처짐), 프롬프트에 받아쓰기 앞 2,400자 (QA_ENS_DIGEST=0)
  live  새 방식 — 발표 중 장을 닫을 때마다 모델 1~2개로 장 몫 음성 후보(qa_listen.Listener · F-08-live) + 장별 요지 맥락(QA_ENS_DIGEST=1)
        + 답마다 음성 라운드(그대로). 1·2번은 두 방식 모두 자료 묶음(pick_opening) — 같다.

    AI_CALLLOG=all AI_CALLLOG_DIR=/data/models/_runs/wt-qa-live/calllog \\
      .venv/bin/python etc/bench/qa_live_bench.py --deck C1 --rep 0 --out /data/models/_runs/wt-qa-live/bench/r1

한 판 산출: <out>/<deck>-r<rep>.json — 1·2번 · 모드별 3~5번(장 · 출처 · 신호) · 발표 중 라운드(완료 시각 vs 장 닫힌 시각) ·
심판 점수(핵심성 체크리스트, 가린 채 섞어서) · 호출 수. 집계: --report <out>.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "main"), str(ROOT / "etc"), str(ROOT)]

import bench.qa_ensemble_bench as QB  # noqa: E402  (load_dotenv · 묶음 · 판정 · 심판을 같이 쓴다)
from pipeline import _ai_calllog  # noqa: E402
from pipeline import _ens_live as EL  # noqa: E402
from pipeline import f08_ensemble as FE  # noqa: E402
from server import qa_listen  # noqa: E402
from server.session_store import SessionStore  # noqa: E402

BUNDLES = {**QB.BUNDLES, "invest_long": "/data/models/_runs/wt-qa-live/bundles_invest_long.json"}
QB.BUNDLES.update(BUNDLES)
#: 받아쓰기가 있는 덱만 (3번+ 는 발표 음성이 재료)
DECKS = ("C1", "A1", "B1", "sleep", "clinic", "glucose", "pitch", "vitd", "invest_long")
#: 1·2번 답 — 1번은 반쯤(약점 신호가 생기게), 2번은 좋은 답
A_KINDS = ("partial", "good")
N_AFTER = 3          # 3 · 4 · 5번


def _talk_order(tr: dict) -> list[tuple[int, float, str]]:
    """받아쓰기 → [(장, 그 장을 떠난 초, 그 장 발화 누적)] 말한 순서대로."""
    out, acc = [], {}
    for seg in tr.get("by_slide") or []:
        no = int(seg["slide_no"])
        text = seg.get("text") or " ".join(w.get("text", "") for w in seg.get("words") or [])
        acc[no] = (acc.get(no, "") + " " + text).strip()
        out.append((no, float(seg.get("end_sec") or 0), acc[no]))
    return out


def run_live_talk(art: dict, sid: str = "S1") -> dict:
    """발표 시간표대로 장을 닫으며 Listener 를 돌린다(같은 스레드). 라운드마다 「장 닫힌 초 + 걸린 초」 = 준비된 초."""
    store = SessionStore()
    L = qa_listen.Listener(store, lambda s: (art["concept_graph"], art["slide_doc"]), lambda key, fn: fn())
    talk = "tBENCH0001"
    timeline = []
    order = _talk_order(art["transcript"])
    end_sec = max((t for _, t, _ in order), default=0.0)
    for i, (no, t_close, text) in enumerate(order):
        before = len(L.state(sid, talk)["rounds"])
        L.put(sid, talk, slide_no=no, text=text, closed=True, final=(i == len(order) - 1))
        for r in L.state(sid, talk)["rounds"][before:]:
            timeline.append({"slide_closed": no, "closed_at": t_close, "sec": r["sec"], "ready_at": round(t_close + r["sec"], 1),
                             "slides": r["slides"], "n_cand": r["n_cand"], "n_calls": len(r["calls"]),
                             "ok_calls": sum(1 for c in r["calls"] if c.get("ok"))})
    st = L.state(sid, talk)
    return {"talk_end_sec": end_sec, "rounds": timeline, "candidates": st["candidates"], "dropped": st["dropped"],
            "speech_of": {str(k): v for k, v in L.speech_of(sid, talk).items()}}


def _asked_from(c: dict, q, ans: str, v: dict) -> dict:
    return {"question": q.question, "node_id": q.node_id, "answer": ans, "verdict": v["verdict"], "missing": v.get("missing"),
            "slide_no": int((q.slide_nos or [0])[0] or 0)}


def run_after(mode: str, pool, art: dict, opening_asked: list[dict], live: list[dict], seed: int) -> list[dict]:
    """3·4·5번 — prod 처럼 앞 답 하나 뒤처진 음성 라운드(n번을 고를 땐 n-2번까지의 답) + 고르기."""
    os.environ["QA_ENS_DIGEST"] = "1" if mode == "live" else "0"
    asked = list(opening_asked)
    out = []
    for n in range(3, 3 + N_AFTER):
        t0 = time.monotonic()
        lag = asked[:-1]           # 바로 앞 질문의 답은 아직 판정 중 — 그 앞까지로 만든 라운드를 쓴다(QA_ENS_NEXT_WAIT_SEC 0.5)
        vr = FE.voice_round(pool, art["concept_graph"], art["slide_doc"], art.get("transcript"),
                            alignment=art.get("alignment_doc"), asked=lag, claims=art.get("claims"))
        vsec = time.monotonic() - t0
        calls: list = []
        t1 = time.monotonic()
        nxt = FE.choose_next(pool, vr, asked, seed=seed + n, calls=calls, live=live if mode == "live" else None)
        if not nxt:
            break
        q = FE.to_question(nxt, n)
        kind = "vague" if n == 3 else "good"
        ans = QB.answer_for(kind, q)
        v = QB.judge(q, ans, art, prior=[], history=[])
        rec = {"n": n, "uid": nxt.get("uid"), "by": nxt.get("model"), "origin": nxt.get("origin") or "pool",
               "slide_no": int(nxt.get("slide_no") or nxt.get("signal_slide") or 0), "node_id": nxt.get("node_id"),
               "signal_kind": nxt.get("signal_kind", ""), "pattern": nxt.get("pattern"), "question": nxt.get("question"),
               "answer": nxt.get("answer"), "substituted": bool(nxt.get("substituted")), "pick_reason": nxt.get("pick_reason", ""),
               "voice_sec": round(vsec, 2), "pick_sec": round(time.monotonic() - t1, 2), "n_voice": len(vr.candidates),
               "n_signals": len(vr.signals), "signal_slides": sorted({int(s.get("slide_no") or 0) for s in vr.signals}),
               "verdict": v["verdict"], "trap": bool(nxt.get("trap"))}
        out.append(rec)
        asked.append(_asked_from(nxt, q, ans, v))
    return out


def one(deck: str, rep: int, out_dir: Path, judges: list[str]) -> dict:
    art = QB.load(deck)
    seed = 1000 * rep + 7
    t0 = time.monotonic()
    pool = FE.build_pool(art["concept_graph"], art["slide_doc"], art.get("claims"), transcript=art.get("transcript"), seed=seed)
    pool_sec = time.monotonic() - t0
    opening = FE.pick_opening(pool, art.get("transcript"))
    opening_asked, turns = [], []
    for i, (c, kind) in enumerate(zip(opening, A_KINDS)):
        q = FE.to_question(c, i + 1)
        ans = QB.answer_for(kind, q)
        v = QB.judge(q, ans, art)
        opening_asked.append(_asked_from(c, q, ans, v))
        turns.append({"n": i + 1, "uid": c["uid"], "pattern": c["pattern"], "slot": c.get("slot"), "origin": c.get("origin") or "pool",
                      "slide_no": int(c.get("slide_no") or 0), "question": c["question"], "verdict": v["verdict"]})
    t1 = time.monotonic()
    talk = run_live_talk(art)
    live_sec = time.monotonic() - t1
    modes = {m: run_after(m, pool, art, opening_asked, talk["candidates"], seed) for m in ("base", "live")}
    # 핵심성 심판 — 두 방식의 3~5번을 섞어 가린 채 (QB.eval_sets · CORE_SYSTEM)
    sets = {m: [{"question": r["question"], "author": r["by"], "node_id": r["node_id"], "trap": r["trap"]} for r in rs]
            for m, rs in modes.items()}

    class _A:
        pass
    a = _A()
    a.judges, a.summary_judge = judges, "solar4"
    ev = QB.eval_sets(sets, art, a, seed)
    slides_n = len(art["slide_doc"]["slides"])
    res = {"deck": deck, "rep": rep, "slides": slides_n, "pool_sec": round(pool_sec, 1), "live_sec": round(live_sec, 1),
           "opening": turns, "talk": {k: v for k, v in talk.items() if k != "speech_of"}, "modes": modes, "eval": ev}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{deck}-r{rep}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return res


# ─── 집계 ─────────────────────────────────────────────────────────────────────────────────

def _scores(res: dict) -> dict[str, list[dict]]:
    ev = res["eval"]
    by_key = {k["id"]: k for k in ev["keys"]}
    out: dict[str, list[dict]] = {}
    for kid, meta in by_key.items():
        rows = [j["rows"].get(kid) for j in ev["judges"].values() if j["rows"].get(kid)]
        if not rows:
            continue
        mean = lambda f: statistics.mean([float(r.get(f) or 0) for r in rows if r.get(f) is not None]) if rows else None  # noqa: E731
        rate = lambda f: sum(1 for r in rows if r.get(f) is True) / len(rows)  # noqa: E731
        out.setdefault(meta["set"], []).append({"core": mean("core"), "micro": rate("micro"), "transplant": rate("transplant"),
                                                "open_book": rate("open_book"), "summary_ok": ev["summary"]["rows"].get(kid)})
    return out


def report(out_dir: Path) -> int:
    rows = [json.loads(p.read_text()) for p in sorted(out_dir.glob("*-r*.json"))]
    if not rows:
        print("결과가 없어요")
        return 1
    agg = {m: {"n": 0, "late": 0, "spread": [], "core": [], "micro": [], "transplant": [], "sub": 0, "live": 0} for m in ("base", "live")}
    ready = {"rounds": 0, "by_end": 0, "by_q3": 0, "cands": [], "calls": 0, "ok": 0}
    open12 = {"n": 0, "deck": 0}
    print(f"{'덱':12s} {'장':>3s} | {'base 장':16s} | {'live 장':16s} | 발표 중 라운드(준비 초 / 발표 끝 초)")
    for r in rows:
        n = r["slides"]
        late_cut = n * 2 / 3
        for m in ("base", "live"):
            rs = r["modes"][m]
            a = agg[m]
            a["n"] += len(rs)
            a["late"] += sum(1 for x in rs if x["slide_no"] > late_cut)
            a["spread"].append(len({x["slide_no"] for x in rs}) / max(1, len(rs)))
            a["sub"] += sum(1 for x in rs if x["substituted"])
            a["live"] += sum(1 for x in rs if x["origin"] == "live")
        for s, items in _scores(r).items():
            for it in items:
                agg[s]["core"].append(it["core"])
                agg[s]["micro"].append(it["micro"])
                agg[s]["transplant"].append(it["transplant"])
        t_end = r["talk"]["talk_end_sec"]
        # 3번을 고르는 때 ≈ 발표 끝 + 1·2번 (질문당 45초 가정)
        for x in r["talk"]["rounds"]:
            ready["rounds"] += 1
            ready["by_end"] += x["ready_at"] <= t_end + 1.0
            ready["by_q3"] += x["ready_at"] <= t_end + 90
            ready["calls"] += x["n_calls"]
            ready["ok"] += x["ok_calls"]
        ready["cands"].append(len(r["talk"]["candidates"]))
        for t in r["opening"]:
            open12["n"] += 1
            open12["deck"] += t["origin"] == "pool" and str(t["pattern"]).startswith("P")
        print(f"{r['deck']:12s} {n:>3d} | {str([x['slide_no'] for x in r['modes']['base']]):16s} | "
              f"{str([x['slide_no'] for x in r['modes']['live']]) + ' ' + ''.join('L' if x['origin'] == 'live' else '.' for x in r['modes']['live']):16s} | "
              f"{[(x['ready_at'], x['n_cand']) for x in r['talk']['rounds']]} / {t_end:.0f}")
    print()
    for m, a in agg.items():
        core = statistics.mean(a["core"]) if a["core"] else float("nan")
        sd = statistics.pstdev(a["core"]) if len(a["core"]) > 1 else 0.0
        print(f"{m:5s} 3번+ {a['n']}개 · 뒷 1/3 장 {a['late'] / max(1, a['n']):.2f} · 장 퍼짐(서로 다른 장/질문) "
              f"{statistics.mean(a['spread']) if a['spread'] else 0:.2f} · 핵심성 {core:.2f}±{sd:.2f} · 미시 "
              f"{statistics.mean(a['micro']) if a['micro'] else 0:.2f} · 뻔함 {statistics.mean(a['transplant']) if a['transplant'] else 0:.2f} · "
              f"대신 냄 {a['sub']} · 발표 중 후보 {a['live']}")
    print(f"발표 중 라운드 {ready['rounds']}번 · 발표 끝까지 준비 {ready['by_end']}/{ready['rounds']} · 3번 전까지 {ready['by_q3']}/{ready['rounds']} · "
          f"호출 {ready['calls']}(성공 {ready['ok']}) · 덱당 후보 {ready['cands']}")
    print(f"1·2번 자료 묶음 {open12['deck']}/{open12['n']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck", default="C1")
    ap.add_argument("--rep", type=int, default=0)
    ap.add_argument("--out", default="/data/models/_runs/wt-qa-live/bench/r1")
    ap.add_argument("--judges", default="solar4,ax,exaone,midm")
    ap.add_argument("--report", default="")
    args = ap.parse_args()
    if args.report:
        return report(Path(args.report))
    os.environ.setdefault("QA_ENSEMBLE", "1")
    try:
        with _ai_calllog.feature_scope(None):
            one(args.deck, args.rep, Path(args.out), [j.strip() for j in args.judges.split(",") if j.strip()])
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
