#!/usr/bin/env python3
"""
모델별 강약 — 후보 묶음 **전체**(뽑힌 것만이 아니라)를 가린 심판단이 핵심성 체크리스트로 매기고, 최종 선택 모델 후보들을 같은 선택지로
견준다. qa_ensemble_bench 의 판 JSON 을 읽어 결과를 <out>/<판>.models.json 으로 남긴다.

    python etc/bench/calllog_run.py etc/bench/qa_ensemble_models.py judge-pool RUN.json --out DIR
    python etc/bench/calllog_run.py etc/bench/qa_ensemble_models.py pickers RUN.json --out DIR --pickers solar,solar4,ax,exaone,midm
    python etc/bench/qa_ensemble_models.py table DIR...            # 모델 × 패턴 × 덱 표 (호출 없음)

심판 점수는 그 후보를 쓴 모델 계열의 표를 뺀다. 선택 모델 일치도의 기준은 「심판단 core 1등」(사람 라벨 전 대용 — Claude 라벨과 따로 견준다).
"""
from __future__ import annotations

import argparse
import json
import random
import statistics as st
import sys
import zlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "main"), str(ROOT / "etc"), str(ROOT)]

from pipeline.config import load_dotenv  # noqa: E402

load_dotenv()
from pipeline import _ai_calllog  # noqa: E402
from pipeline import _ens_slots as ES  # noqa: E402
from pipeline import f08_ensemble as FE  # noqa: E402
from pipeline.providers.llm_impl import REGISTRY  # noqa: E402

from bench.qa_ensemble_bench import CORE_SYSTEM, FAMILY, JUDGES, load  # noqa: E402

TOPIC = {"A1": "공학", "C1": "사회과학", "sleep": "생활·심리", "invest": "금융", "pitch": "의료 제품",
         "B1": "환경과학", "glucose": "의학·생활", "iohexol": "영문 임상", "vitd": "의학 논문"}


def judge_pool(run: dict, judges: list[str]) -> dict:
    """묶음의 후보 전부(통과한 것)를 심판단에 — 작성자 가림 · 순서 섞음."""
    art = load(run["deck"])
    cands = (run.get("ensemble") or {}).get("pool", {}).get("candidates", [])
    if not cands:
        return {}
    rng = random.Random(zlib.crc32(run["deck"].encode()) + run["rep"])
    order = cands[:]
    rng.shuffle(order)
    keyed = [(f"Q{i:02d}", c) for i, c in enumerate(order, 1)]
    deck = FE.Deck.build(art["concept_graph"], art["slide_doc"], art.get("claims"))
    user = "\n".join(["[TASK] qa-core-judge", "", f"## 발표의 핵심 주장\n{deck.thesis}", "", "## 자료",
                      ES.deck_block(deck.lines, 160), "", "## 질문",
                      *[f"{k} (trap={'true' if c['pattern'] == 'P9' else 'false'}): {c['question']}" for k, c in keyed]])

    def one(j):
        calls: list = []
        data = FE._complete(REGISTRY[j](), "bench", calls, system=CORE_SYSTEM, user=user, temperature=0.0, max_tokens=6000)
        return j, {str(r.get("id")): r for r in (data.get("scores") or []) if isinstance(r, dict)}

    with _ai_calllog.feature_scope("F-08-bench"), ThreadPoolExecutor(len(judges)) as ex:
        res = dict(ex.map(_ai_calllog.carry(one), judges))
    out = {}
    for k, c in keyed:
        fam = FAMILY.get(c["model"], c["model"])
        rows = [res[j].get(k) for j in judges if FAMILY.get(j, j) != fam and res[j].get(k)]
        cores = [r.get("core") for r in rows if isinstance(r.get("core"), (int, float))]
        out[c["uid"]] = {"model": c["model"], "pattern": c["pattern"], "slot": c["slot"], "peer": c["peer"],
                         "core": round(st.mean(cores), 3) if cores else None,
                         "open_book": sum(1 for r in rows if r.get("open_book") is True) * 2 > len(rows) if rows else None,
                         "micro": sum(1 for r in rows if r.get("micro") is True) * 2 > len(rows) if rows else None,
                         "transplant": sum(1 for r in rows if r.get("transplant") is True) * 2 > len(rows) if rows else None,
                         "question": c["question"], "answer": c["answer"],
                         "per_judge": {j: (res[j].get(k) or {}).get("core") for j in judges}}
    return out


def pickers(run: dict, names: list[str], judged: dict) -> list[dict]:
    """흐름마다 3번 선택지(음성 후보 + 묶음 상위 2)를 선택 모델마다 고르게 한다. 기준 = 선택지 중 심판단 core 1등."""
    out = []
    pool = (run.get("ensemble") or {}).get("pool") or {}
    winners = FE.Pool(slots=[], candidates=pool.get("candidates", []))
    for fl, f in (run.get("flows") or {}).items():
        voice = (f.get("voice1") or {}).get("candidates") or []
        if not voice:
            continue
        asked = [{"question": t["q"], "verdict": t.get("verdict")} for t in f.get("turns", [])[:2]]
        rest = [c for c in sorted(winners.candidates, key=lambda c: -c["peer"])
                if all(c["question"] != a["question"] for a in asked)][:2]
        options = voice + rest
        row = {"flow": fl, "n_options": len(options), "picks": {}}
        for name in names:
            calls: list = []
            with _ai_calllog.feature_scope("F-08-pick"):
                got = FE.ens_pick(name, REGISTRY[name](), options, asked, calls, seed=7)
            c = next((o for o in options if o["uid"] == got.get("uid")), None)
            row["picks"][name] = {"uid": got.get("uid"), "author": c.get("model") if c else None,
                                  "reason": got.get("reason", ""), "sec": calls[-1].sec if calls else None}
        row["options"] = [{"uid": o["uid"], "author": o.get("model"), "question": o["question"]} for o in options]
        out.append(row)
    return out


def judge_options(run: dict, rows: list[dict], judges: list[str]) -> dict:
    """선택지 질문들을 심판단에 (음성 후보는 묶음 심판에 없으니 따로)."""
    art = load(run["deck"])
    qs = {o["uid"]: o for r in rows for o in r["options"]}
    if not qs:
        return {}
    keyed = [(f"Q{i:02d}", uid, o) for i, (uid, o) in enumerate(qs.items(), 1)]
    deck = FE.Deck.build(art["concept_graph"], art["slide_doc"], art.get("claims"))
    user = "\n".join(["[TASK] qa-core-judge", "", f"## 발표의 핵심 주장\n{deck.thesis}", "", "## 자료",
                      ES.deck_block(deck.lines, 160), "", "## 질문", *[f"{k} (trap=false): {o['question']}" for k, _, o in keyed]])

    def one(j):
        calls: list = []
        data = FE._complete(REGISTRY[j](), "bench", calls, system=CORE_SYSTEM, user=user, temperature=0.0, max_tokens=4000)
        return j, {str(r.get("id")): r for r in (data.get("scores") or []) if isinstance(r, dict)}

    with _ai_calllog.feature_scope("F-08-bench"), ThreadPoolExecutor(len(judges)) as ex:
        res = dict(ex.map(_ai_calllog.carry(one), judges))
    out = {}
    for k, uid, o in keyed:
        fam = FAMILY.get(o.get("author") or "", "")
        cores = [res[j].get(k, {}).get("core") for j in judges if FAMILY.get(j, j) != fam]
        cores = [c for c in cores if isinstance(c, (int, float))]
        out[uid] = round(st.mean(cores), 3) if cores else None
    return out


def table(paths: list[Path]) -> str:
    recs = []
    for p in paths:
        recs += [json.loads(f.read_text()) for f in (sorted(p.glob("*.models.json")) if p.is_dir() else [p])]
    by = defaultdict(list)
    for r in recs:
        for uid, v in (r.get("pool_judged") or {}).items():
            by[("model", v["model"])].append(v)
            by[("model×pattern", f"{v['model']}·{v['pattern']}")].append(v)
            by[("model×topic", f"{v['model']}·{TOPIC.get(r['deck'], r['deck'])}")].append(v)
    L = ["| 묶음 | 키 | n | core(남 심판) | 서로 평가 | 열린책 | 미시 | 뻔함 |", "|---|---|---|---|---|---|---|---|"]
    for (kind, key), vs in sorted(by.items()):
        core = [v["core"] for v in vs if v["core"] is not None]
        L.append(f"| {kind} | {key} | {len(vs)} | {round(st.mean(core), 2) if core else '-'} | "
                 f"{round(st.mean(v['peer'] for v in vs), 2)} | {sum(1 for v in vs if v['open_book']) / len(vs):.2f} | "
                 f"{sum(1 for v in vs if v['micro']) / len(vs):.2f} | {sum(1 for v in vs if v['transplant']) / len(vs):.2f} |")
    # 선택 모델 일치도
    agree = defaultdict(lambda: [0, 0, 0, 0])
    for r in recs:
        oc = r.get("option_core") or {}
        for row in r.get("pickers") or []:
            scored = [(oc.get(o["uid"]), o) for o in row["options"] if oc.get(o["uid"]) is not None]
            if len(scored) < 2:
                continue
            top = max(s for s, _ in scored)
            for name, pk in row["picks"].items():
                a = agree[name]
                a[2] += 1
                if pk.get("uid") and oc.get(pk["uid"]) == top:
                    a[0] += 1
                if pk.get("author") and FAMILY.get(pk["author"]) == FAMILY.get(name):
                    a[1] += 1
                a[3] += sum(1 for _, o in scored if FAMILY.get(o.get("author") or "") == FAMILY.get(name)) / len(scored)
    L += ["", "| 선택 모델 | 판 | 심판단 1등과 일치 | 자기 계열 고름 | 선택지 중 자기 계열 비율(기대) |", "|---|---|---|---|---|"]
    for name, (hit, own, n, exp) in sorted(agree.items()):
        if n:
            L.append(f"| {name} | {n} | {hit / n:.2f} | {own / n:.2f} | {exp / n:.2f} |")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("judge-pool", "pickers", "both", "table"))
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--judges", default=",".join(JUDGES))
    ap.add_argument("--pickers", default="solar,solar4,ax,exaone,midm")
    a = ap.parse_args()
    if a.cmd == "table":
        print(table(a.paths))
        return 0
    judges = a.judges.split(",")
    a.out.mkdir(parents=True, exist_ok=True)
    for p in a.paths:
        run = json.loads(p.read_text())
        dest = a.out / (p.stem + ".models.json")
        rec = json.loads(dest.read_text()) if dest.exists() else {"deck": run["deck"], "rep": run["rep"], "src": str(p)}
        if a.cmd in ("judge-pool", "both"):
            rec["pool_judged"] = judge_pool(run, judges)
        if a.cmd in ("pickers", "both"):
            rec["pickers"] = pickers(run, a.pickers.split(","), rec.get("pool_judged") or {})
            rec["option_core"] = judge_options(run, rec["pickers"], judges)
        dest.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"저장: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
