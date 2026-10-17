#!/usr/bin/env python3
"""
조건 사이 비교를 **같은 심판 · 같은 호출 안에서** — 「가장 특화된(핵심을 찌르는) 조합」 순위.

심판마다 너그러움이 다르다(10-17 dev: solar4 core 평균 3.57 · midm 4.39). 조건마다 「작성 계열을 뺀 심판」이 다르면 심판 차이가
조건 차이로 둔갑한다(한 모델만 쓴 조건은 가장 깐깐한 심판이 빠져 부풀었다). 그래서 덱마다 모든 조건의 질문을 섞어 가린 채
**심판 하나가 한 번에** 매기고, 조건 순위는 (1) 심판별 순위 (2) 자기 계열 질문을 뺀 평균 둘 다 낸다.

    python etc/bench/calllog_run.py etc/bench/qa_ensemble_cross.py --cond release=DIR:release --cond all4=DIR:ensemble \\
        --cond only-solar=DIR2:ensemble:only-solar ... --decks A1,C1,sleep,invest,pitch --out cross.json
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


def questions_of(path: Path, kind: str) -> list[dict]:
    run = json.loads(path.read_text(encoding="utf-8"))
    if kind == "release":
        rel = run.get("release") or {}
        return [{"question": q["question"], "author": rel.get("model") or "exaone", "trap": q["trap"]}
                for q in rel.get("questions", [])[:5]]
    if kind == "voice":
        out = []
        for f in (run.get("flows") or {}).values():
            for k in ("q3", "q4"):
                if (f.get(k) or {}).get("question"):
                    out.append({"question": f[k]["question"], "author": f[k].get("model"), "trap": False})
        return out
    if kind.startswith("rule-"):
        return [{"question": c["question"], "author": c["model"], "trap": c["pattern"] == "P9"}
                for c in reselect(run, kind[5:])]
    return [{"question": c["question"], "author": c["model"], "trap": c["pattern"] == "P9"}
            for c in (run.get("ensemble") or {}).get("five", [])]


def reselect(run: dict, rule: str) -> list[dict]:
    """같은 묶음에서 고르는 규칙만 바꿔 세션 5문항을 다시 — 생성 잡음 없이 선택 규칙 비교.
    rule: peer(지금) · core(서로 평가의 core 칸만) · nopeer(서로 평가 안 씀) · rev-<모델>(그 심판 하나의 점수만)."""
    pool_d = (run.get("ensemble") or {}).get("pool") or {}
    cands = [dict(c) for c in pool_d.get("candidates", [])]
    for c in cands:
        rows = [x for x in c.get("peer_scores", []) if not x.get("self")]
        if rule == "core":
            c["peer"] = round(st.mean((x["core"] - 1) / 4 for x in rows), 4) if rows else 0.0
        elif rule == "nopeer":
            c["peer"] = 0.0
        elif rule.startswith("rev-"):
            mine = [x for x in rows if x["reviewer"] == rule[4:]]
            c["peer"] = FE.peer_score(mine) if mine else 0.0
    slots = [ES.Slot(**{k: v for k, v in s.items() if k not in ("pattern_desc", "angle")}) for s in pool_d.get("slots", [])]
    pool = FE.Pool(slots=slots, candidates=cands)
    art = load(run["deck"])
    return FE.pick_session(pool, art.get("transcript"), 5)


def run_deck(deck: str, conds: dict[str, list[dict]], judges: list[str]) -> dict:
    art = load(deck)
    items = [(name, q) for name, qs in conds.items() for q in qs]
    rng = random.Random(zlib.crc32(deck.encode()))
    rng.shuffle(items)
    keyed = [(f"Q{i:02d}", name, q) for i, (name, q) in enumerate(items, 1)]
    d = FE.Deck.build(art["concept_graph"], art["slide_doc"], art.get("claims"))
    user = "\n".join(["[TASK] qa-core-judge", "", f"## 발표의 핵심 주장\n{d.thesis}", "", "## 자료", ES.deck_block(d.lines, 150),
                      "", "## 질문", *[f"{k} (trap={'true' if q['trap'] else 'false'}): {q['question']}" for k, _, q in keyed]])

    def one(j):
        calls: list = []
        data = FE._complete(REGISTRY[j](), "bench", calls, system=CORE_SYSTEM, user=user, temperature=0.0, max_tokens=8000)
        return j, {str(r.get("id")): r for r in (data.get("scores") or []) if isinstance(r, dict)}

    with _ai_calllog.feature_scope("F-08-bench"), ThreadPoolExecutor(len(judges)) as ex:
        res = dict(ex.map(_ai_calllog.carry(one), judges))
    return {"deck": deck, "items": [{"id": k, "cond": n, **q, "scores": {j: res[j].get(k) for j in judges}} for k, n, q in keyed]}


def summarize(decks: list[dict], judges: list[str]) -> dict:
    per_judge = defaultdict(lambda: defaultdict(list))
    loo = defaultdict(list)            # 자기 계열 뺀 평균
    flags = defaultdict(lambda: defaultdict(list))
    for d in decks:
        for it in d["items"]:
            fam = FAMILY.get(it.get("author") or "", it.get("author"))
            vals = []
            for j in judges:
                s = it["scores"].get(j) or {}
                c = s.get("core")
                if isinstance(c, (int, float)):
                    per_judge[it["cond"]][j].append(c)
                    if FAMILY.get(j, j) != fam:
                        vals.append(c)
                for key in ("open_book", "micro", "transplant", "deep"):
                    if isinstance(s.get(key), bool):
                        flags[it["cond"]][key].append(s[key])
            if vals:
                loo[it["cond"]].append(st.mean(vals))
    conds = sorted(per_judge)
    table = {c: {"n": len(loo[c]), "core_loo": round(st.mean(loo[c]), 3) if loo[c] else None,
                 **{f"core_{j}": round(st.mean(per_judge[c][j]), 3) if per_judge[c][j] else None for j in judges},
                 **{k: round(sum(v) / len(v), 3) for k, v in flags[c].items() if v}} for c in conds}
    ranks = {j: sorted(conds, key=lambda c: -(table[c].get(f"core_{j}") or 0)) for j in judges}
    return {"table": table, "rank_by_judge": ranks,
            "rank_loo": sorted(conds, key=lambda c: -(table[c]["core_loo"] or 0))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cond", action="append", required=True, help="이름=폴더:종류[:태그]  (종류 release|ensemble|voice)")
    ap.add_argument("--decks", default="A1,C1,sleep,invest,pitch")
    ap.add_argument("--rep", type=int, default=0)
    ap.add_argument("--judges", default=",".join(JUDGES))
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    judges = a.judges.split(",")
    specs = []
    for c in a.cond:
        name, _, rest = c.partition("=")
        parts = rest.split(":")
        specs.append((name, Path(parts[0]), parts[1], parts[2] if len(parts) > 2 else ""))
    decks_out = []
    for deck in a.decks.split(","):
        conds = {}
        for name, folder, kind, tag in specs:
            p = folder / f"{deck}-r{a.rep}{('-' + tag) if tag else ''}.json"
            if p.exists():
                qs = questions_of(p, kind)
                if qs:
                    conds[name] = qs
        if len(conds) >= 2:
            decks_out.append(run_deck(deck, conds, judges))
            print(f"{deck}: 조건 {list(conds)}", flush=True)
    summ = summarize(decks_out, judges)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"decks": decks_out, **summ}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summ.items()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
