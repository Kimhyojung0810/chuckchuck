#!/usr/bin/env python3
"""
qa_ensemble_bench.py 판들 → 지표 · 기준표(PLAN.md: 실측 · 통과/미달 · 잡음 폭) · 모델 강약 표.

    python etc/bench/qa_ensemble_report.py /data/models/_runs/qa-ensemble/runs/dev1 [--split dev] [--md out.md] [--json out.json]

잡음 폭 = 같은 덱 반복 판 사이 표준편차의 평균(덱 평균). 「나아짐」은 짝지은 차이(같은 덱·같은 반복)의 95% 붓스트랩 구간이 0 밖일 때만.
핵심성 합성 지표(기술조사 §1-3) = 평균[A 루트 거리(≤1:1, 2:.5, 그 밖 0) · B 요약만 보고 답함 · C (core−1)/4 · D 열린 책 아님].
심판 점수는 그 질문을 쓴 모델 계열의 표를 뺀다(자기 선호 편향).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "main"), str(ROOT / "etc"), str(ROOT)]

from pipeline import _ens_slots as ES  # noqa: E402
from pipeline import f08_ensemble as FE  # noqa: E402
from pipeline.contracts import ConceptGraph, Question  # noqa: E402

from bench.qa_ensemble_bench import BUNDLES, FAMILY, load  # noqa: E402

TEMPLATE_CHECKS = {"fallback_template", "question_follows_gist", "unanswerable_fallback", "trap_template",
                   "contradiction_template"}
_DOUBLE_RE = re.compile(r"\?.+\?|(?:고|며|그리고)\s*[^?]{3,}(?:무엇|어떻게|왜)[^?]*\?.*(?:무엇|어떻게|왜)")


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(st.mean(xs), 3) if xs else None


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return round(xs[k], 2)


def boot_ci(diffs, n=2000, seed=0):
    diffs = [d for d in diffs if d is not None]
    if len(diffs) < 2:
        return (None, None)
    rng = random.Random(seed)
    ms = sorted(st.mean(rng.choice(diffs) for _ in diffs) for _ in range(n))
    return (round(ms[int(0.025 * n)], 3), round(ms[int(0.975 * n)], 3))


# ─── 질문 하나의 지표 ─────────────────────────────────────────────────────────────────────

class DeckInfo:
    _cache: dict = {}

    @classmethod
    def get(cls, name):
        if name not in cls._cache:
            art = load(name)
            g = ConceptGraph.from_dict(art["concept_graph"])
            deck = FE.Deck.build(g, art["slide_doc"], art.get("claims"))
            cls._cache[name] = (art, g, deck)
        return cls._cache[name]


def q_metrics(question: str, node_id: str, deck_name: str) -> dict:
    art, g, deck = DeckInfo.get(deck_name)
    node = next((n for n in g.nodes if n.id == node_id), None)
    dist = ES.root_distance(g, node_id) if node is not None else 9
    terms = ES.specific_terms(question, node.label if node else "", deck.deck_tokens)
    floor = ES.specific_terms(question, "", deck.deck_tokens)        # 바닥 검사(거르기와 같은 정의 — 라벨 낱말도 센다)
    body = re.split(r"(?<=[.!])\s+", question.strip())[-1]
    root = bool(node is not None and node.kind == "thesis")
    return {"root_dist": dist, "kind": (node.kind if node else "") or "concept", "spec_floor": len(floor),
            "spec": len(terms), "micro_code": ES.micro(question), "deixis": ES.vague_deixis(question, deck.deck_tokens, root_slot=root),
            "double": question.count("?") + question.count("？") > 1 or bool(_DOUBLE_RE.search(question)),
            "len_ok": 25 <= len(body) <= 70, "polite": bool(ES.POLITE_END_RE.search(question))}


def judged(run: dict) -> dict[str, dict]:
    """eval 키 → 심판 합(작성 계열 표 뺌)."""
    ev = run.get("eval") or {}
    out = {}
    for k in ev.get("keys", []):
        fam = FAMILY.get(k.get("author") or "", k.get("author"))
        rows = [res["rows"].get(k["id"]) for j, res in ev.get("judges", {}).items() if FAMILY.get(j, j) != fam]
        rows = [r for r in rows if isinstance(r, dict)]
        maj = lambda key: (sum(1 for r in rows if r.get(key) is True) * 2 > len(rows)) if rows else None  # noqa: E731
        cores = [r.get("core") for r in rows if isinstance(r.get("core"), (int, float))]
        gr = [r.get("grounded") for r in rows if isinstance(r.get("grounded"), (int, float))]
        out[k["id"]] = {**k, "core": mean(cores), "open_book": maj("open_book"), "transplant": maj("transplant"),
                        "micro_j": maj("micro"), "deep": maj("deep"), "single": maj("single"), "grounded": mean(gr),
                        "summary_ok": (ev.get("summary") or {}).get("rows", {}).get(k["id"]),
                        "per_judge": {j: (res["rows"].get(k["id"]) or {}).get("core") for j, res in ev["judges"].items()}}
    return out


def core_index(r: dict) -> float | None:
    a = 1.0 if r["root_dist"] <= 1 else (0.5 if r["root_dist"] == 2 else 0.0)
    parts = [a, 1.0 if r.get("summary_ok") else 0.0 if r.get("summary_ok") is not None else None,
             (r["core"] - 1) / 4 if r.get("core") is not None else None,
             (0.0 if r.get("open_book") else 1.0) if r.get("open_book") is not None else None]
    parts = [p for p in parts if p is not None]
    return round(st.mean(parts), 3) if parts else None


# ─── 판 하나 → 세트별 지표 ─────────────────────────────────────────────────────────────────

def run_rows(run: dict) -> list[dict]:
    """질문 하나 = 한 줄 (set · deck · rep · 지표)."""
    js = judged(run)
    rows = []
    for k, j in js.items():
        m = q_metrics(j["question"], j.get("node_id") or "", run["deck"])
        rows.append({"deck": run["deck"], "rep": run["rep"], "set": j["set"], "author": j.get("author"), **m, **j})
    for r in rows:
        r["core_index"] = core_index(r)
        r["micro"] = bool(r["micro_code"] or r.get("micro_j"))
    return rows


def set_summary(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {}
    f = lambda key: round(sum(1 for r in rows if r.get(key)) / n, 3)  # noqa: E731
    return {"n": n, "core": mean([r["core"] for r in rows]), "core_index": mean([r["core_index"] for r in rows]),
            "open_book": f("open_book"), "transplant": f("transplant"), "micro": f("micro"), "deep": f("deep"),
            "single": f("single"), "grounded": mean([r["grounded"] for r in rows]),
            "summary_ok": f("summary_ok"), "spec": mean([r["spec"] for r in rows]),
            "spec_zero": round(sum(1 for r in rows if r.get("spec_floor", r["spec"]) == 0) / n, 3),
            "thesis_claim": round(sum(1 for r in rows if r["kind"] in ("thesis", "claim")) / n, 3),
            "leaf": round(sum(1 for r in rows if r["kind"] not in ("thesis", "claim") and r["root_dist"] >= 2) / n, 3),
            "deixis": f("deixis"), "double": f("double"), "len_ok": f("len_ok"), "polite": f("polite"),
            "root_dist": mean([min(r["root_dist"], 4) for r in rows])}


def run_extras(run: dict) -> dict:
    """세트 밖 지표 — 템플릿·모범답·협업·자기 선호·지연·흐름·짝 비교."""
    out: dict = {}
    rel = run.get("release") or {}
    ens = run.get("ensemble") or {}
    if rel.get("questions"):
        qs = rel["questions"][:5]
        out["release_template"] = sum(1 for q in qs if TEMPLATE_CHECKS & set((q.get("basis") or {}).get("checks") or []))
        out["release_n"] = len(qs)
        out["release_dirty_gist"] = sum(1 for q in qs if FE.dirty_gist(Question.from_dict(q)))
        out["release_sec"] = sum((rel.get("sec") or {}).values())
    if ens.get("pool"):
        pool = ens["pool"]
        out["pool_sec"] = pool["timings"].get("total_sec")
        out["pool_gen_sec"] = pool["timings"].get("generate_sec")
        out["opening_ms"] = ens.get("pick_opening_ms")
        out["cands"] = len(pool["candidates"])
        out["dropped"] = len(pool["dropped"])
        out["drop_reasons"] = Counter(r for d in pool["dropped"] for r in d["reasons"])
        out["drop_by_model"] = Counter(d["model"] for d in pool["dropped"])
        out["kept_by_model"] = Counter(c["model"] for c in pool["candidates"])
        out["calls_by_model"] = Counter(c["model"] for c in pool["calls"])
        out["calls_fail"] = sum(1 for c in pool["calls"] if not c["ok"])
        out["calls_retry"] = sum(c.get("retries", 0) for c in pool["calls"])
        out["tokens"] = sum((c.get("prompt_tokens") or 0) + (c.get("completion_tokens") or 0) for c in pool["calls"])
        out["winner_by_model"] = Counter(c["model"] for c in ens.get("five", []))
        out["opening_by_model"] = Counter(c["model"] for c in ens.get("opening", []))
        out["opening_core_pattern"] = any(c["pattern"] in ("P1", "P2") for c in ens.get("opening", []))
        out["opening_root"] = sum(1 for c in ens.get("opening", []) if c["pattern"] == "P1")
        out["opening_nodes"] = [c["node_id"] for c in ens.get("opening", [])]
        five = ens.get("five", [])
        out["defensive"] = sum(1 for c in five if c["pattern"] in ("P7", "P9"))
        out["expansive"] = sum(1 for c in five if c["pattern"] == "P10")
        keys = [(c["node_id"], c["angle"]) for c in five]
        out["dup_node_angle"] = len(keys) - len(set(keys))
        out["self_bias"] = self_bias(pool)
        out["peer_by_reviewer"] = peer_by_reviewer(pool)
    gist = run.get("gist") or []
    if gist:
        out["gist_n"] = len(gist)
        out["gist_good"] = sum(1 for g in gist if g.get("good_verdict") == "good")
        out["gist_dirty"] = sum(1 for g in gist if FE._DIRTY_GIST_RE.search(g.get("gist") or ""))
        out["gist_sent_ok"] = sum(1 for g in gist if 1 <= len(re.findall(r"[.?!요](?:\s|$)", g.get("gist") or "")) <= 3)
        memo = [g for g in gist if g.get("memo_verdict")]
        out["memo_n"] = len(memo)
        out["memo_diff"] = sum(1 for g in memo if g["memo_verdict"] != g["good_verdict"]
                               or (g.get("memo_score") or 0) <= (g.get("good_score") or 0) - 15)
    flows = run.get("flows") or {}
    if flows:
        q3s, sig, sub, micro3, ready30, ready10, pick = [], 0, 0, 0, 0, 0, []
        for fl, f in flows.items():
            if "q3" not in f:
                continue
            q3 = f["q3"] or {}
            q3s.append(q3.get("question"))
            sub += bool(q3.get("substituted"))
            sig += bool(q3.get("signal_kind")) and not q3.get("substituted")
            micro3 += ES.micro(q3.get("question") or "")
            ready30 += bool(f.get("ready_30"))
            ready10 += bool(f.get("ready_10"))
            pick.append(f.get("pick3_sec"))
            q4 = f.get("q4") or {}
            if q4:
                sig += bool(q4.get("signal_kind")) and not q4.get("substituted")
                sub += bool(q4.get("substituted"))
                micro3 += ES.micro(q4.get("question") or "")
        n3 = len(q3s)
        n34 = n3 + sum(1 for f in flows.values() if f.get("q4"))
        out.update({"flows_n": n3, "q3_distinct": len(set(q3s)), "voice_signal": sig, "voice_n": n34, "substituted": sub,
                    "voice_micro": micro3, "ready30": ready30, "ready10": ready10, "pick3_sec": pick,
                    "voice_sec": [f["voice1"]["sec"] for f in flows.values() if f.get("voice1")],
                    "voice_signals": [len(f["voice1"]["signals"]) for f in flows.values() if f.get("voice1")],
                    "voice_cands": [len(f["voice1"]["candidates"]) for f in flows.values() if f.get("voice1")],
                    "voice_drop": Counter(r for f in flows.values() for k in ("voice1", "voice2") if f.get(k)
                                          for d in f[k]["dropped"] for r in d["reasons"])})
    pw = run.get("pairwise") or []
    if pw:
        out["pair"] = Counter(p["winner"] for p in pw)
        out["pair_pos_A"] = sum((p["order1"] == "release") + (p["order2"] == "ensemble") for p in pw)  # A 자리를 고른 수
        out["pair_n"] = 2 * len(pw)
    return out


def self_bias(pool: dict) -> dict:
    """심판 모델이 슬롯마다 1등으로 매긴 후보가 자기 것인 비율 − 그 슬롯 후보 중 자기 비율 (가림 적용 상태)."""
    by_slot = defaultdict(list)
    for c in pool["candidates"]:
        by_slot[c["slot"]].append(c)
    stats = defaultdict(lambda: [0, 0.0, 0])
    for slot, cs in by_slot.items():
        reviewers = {s["reviewer"] for c in cs for s in c.get("peer_scores", [])}
        for rv in reviewers:
            own = [c for c in cs if c["model"] == rv]
            if not own or len(cs) < 2:
                continue
            def sc(c):
                s = next((x for x in c.get("peer_scores", []) if x["reviewer"] == rv), None)
                return sum(FE.PEER_WEIGHTS[k] * s[k] for k in FE.PEER_WEIGHTS) if s else -1
            best = max(cs, key=sc)
            stats[rv][0] += best["model"] == rv
            stats[rv][1] += len(own) / len(cs)
            stats[rv][2] += 1
    return {rv: {"picked_own": a, "expected": round(b, 2), "n": n} for rv, (a, b, n) in stats.items()}


def peer_by_reviewer(pool: dict) -> dict:
    """심판별 · 작성자별 평균 점수 (자기 것 포함) — 자기 선호 편향 표."""
    acc = defaultdict(list)
    for c in pool["candidates"]:
        for s in c.get("peer_scores", []):
            acc[(s["reviewer"], c["model"])].append(sum(FE.PEER_WEIGHTS[k] * (s[k] - 1) / 4 for k in FE.PEER_WEIGHTS))
    return {f"{a}>{b}": round(st.mean(v), 3) for (a, b), v in acc.items()}


# ─── 묶기 ──────────────────────────────────────────────────────────────────────────────────

def load_runs(paths: list[Path], split: str | None) -> list[dict]:
    runs = []
    for p in paths:
        for f in sorted(p.glob("*.json")) if p.is_dir() else [p]:
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(r, dict) or "deck" not in r or "rep" not in r:
                continue                       # 집계 결과 파일 등 판이 아닌 것
            if split and r.get("split") != split:
                continue
            runs.append(r)
    return runs


def noise_width(per_run: list[tuple[str, int, float]]) -> float | None:
    """같은 덱 반복 사이 표준편차의 덱 평균."""
    by = defaultdict(list)
    for deck, _, v in per_run:
        if v is not None:
            by[deck].append(v)
    sds = [st.pstdev(v) for v in by.values() if len(v) >= 2]
    return round(st.mean(sds), 3) if sds else None


def aggregate(runs: list[dict]) -> dict:
    rows = [r for run in runs for r in run_rows(run)]
    ex = [(run["deck"], run["rep"], run_extras(run)) for run in runs]
    sets = {s: set_summary([r for r in rows if r["set"] == s]) for s in ("release", "ensemble", "voice")}
    # 판마다 세트 평균 → 잡음 폭 · 짝 차이
    per = defaultdict(dict)
    for run in runs:
        rr = [r for r in rows if r["deck"] == run["deck"] and r["rep"] == run["rep"]]
        for s in ("release", "ensemble", "voice"):
            per[(run["deck"], run["rep"])][s] = set_summary([r for r in rr if r["set"] == s])
    paired = {}
    for key in ("core", "core_index", "open_book", "micro", "transplant", "deep", "spec", "thesis_claim", "grounded"):
        diffs = [v["ensemble"].get(key) - v["release"].get(key) for v in per.values()
                 if v.get("ensemble") and v.get("release") and v["ensemble"].get(key) is not None
                 and v["release"].get(key) is not None]
        noise = {s: noise_width([(d, rp, v[s].get(key)) for (d, rp), v in per.items() if v.get(s)])
                 for s in ("release", "ensemble")}
        paired[key] = {"diff_mean": mean(diffs), "ci95": boot_ci(diffs), "n": len(diffs), "noise": noise}
    # 모델 강약: 작성 모델별(앙상블 후보 전체가 아니라 심판에 들어간 세트 질문) · 패턴별 · 덱별
    by_author = defaultdict(list)
    for r in rows:
        if r["set"] in ("ensemble", "voice"):
            by_author[r.get("author")].append(r)
    authors = {a: set_summary(v) for a, v in by_author.items()}
    by_pattern = defaultdict(list)
    for run in runs:
        for c in (run.get("ensemble") or {}).get("pool", {}).get("candidates", []):
            by_pattern[(c["model"], c["pattern"])].append(c["peer"])
    # 심판별 core 평균 (세트별) — 심판 성향
    judge_core = defaultdict(lambda: defaultdict(list))
    for r in rows:
        for j, v in (r.get("per_judge") or {}).items():
            if isinstance(v, (int, float)):
                judge_core[j][r["set"]].append(v)
    return {"runs": len(runs), "sets": sets, "paired": paired, "extras": ex, "authors": authors,
            "pattern_peer": {f"{m}:{p}": (round(st.mean(v), 3), len(v)) for (m, p), v in sorted(by_pattern.items())},
            "judge_core": {j: {s: mean(v) for s, v in d.items()} for j, d in judge_core.items()}, "rows": rows}


def sum_counter(xs):
    c = Counter()
    for x in xs:
        c.update(x or {})
    return dict(c)


def criteria(agg: dict) -> list[dict]:
    """PLAN.md 기준표 → 실측 · 통과/미달. 잡음 폭은 짝 비교 지표에만."""
    S = agg["sets"]
    E = [e for _, _, e in agg["extras"]]
    P = agg["paired"]
    tot = lambda k: sum(e.get(k, 0) or 0 for e in E)  # noqa: E731
    ens = S.get("ensemble") or {}
    rel = S.get("release") or {}
    voice = S.get("voice") or {}
    pool_sec = [e.get("pool_sec") for e in E if e.get("pool_sec") is not None]
    open_ms = [e.get("opening_ms") for e in E if e.get("opening_ms") is not None]
    pick3 = [x for e in E for x in (e.get("pick3_sec") or []) if x is not None]
    winners = sum_counter([e.get("winner_by_model") for e in E])
    wn = sum(winners.values()) or 1
    sb = defaultdict(lambda: [0, 0.0, 0])
    for e in E:
        for rv, d in (e.get("self_bias") or {}).items():
            sb[rv][0] += d["picked_own"]
            sb[rv][1] += d["expected"]
            sb[rv][2] += d["n"]
    bias = {rv: round((a - b) / n, 3) for rv, (a, b, n) in sb.items() if n}
    calls_model = sum_counter([e.get("calls_by_model") for e in E])
    n_runs = len([e for e in E if e.get("pool_sec") is not None]) or 1
    rows = [
        ("1", "지저분한 모범답 0 / 30문항+", "=0", tot("gist_dirty"), f"n={tot('gist_n')}"),
        ("1", "모범답 그대로 → good ≥95%", ">=0.95", _r(tot("gist_good"), tot("gist_n")), ""),
        ("1", "모범답 1~3문장", ">=1.0", _r(tot("gist_sent_ok"), tot("gist_n")), ""),
        ("1", "외운 답(근거 줄 그대로) vs 이해한 답(모범답) 판정이 갈림 ≥90%", ">=0.9", _r(tot("memo_diff"), tot("memo_n")), f"n={tot('memo_n')}"),
        ("2a", "thesis·claim 비율 ≥60% (앙상블 5문항)", ">=0.6", ens.get("thesis_claim"), f"release {rel.get('thesis_claim')}"),
        ("2a", "같은 덱 반복에서 1·2번 노드가 같은 비율 (기록)", ">=0.0", node_stability(agg), "목표 ≥0.7"),
        ("2a", "잎 concept 비율 ≤25%", "<=0.25", ens.get("leaf"), f"release {rel.get('leaf')}"),
        ("2", "특이도 0(뻔함 바닥) 비율", "<=0.1", ens.get("spec_zero"), f"release {rel.get('spec_zero')}"),
        ("2", "핵심성 core(심판, 작성 계열 뺌) — release 이상", f">={rel.get('core') or 0}", ens.get("core"), f"release {rel.get('core')} · 차 {P['core']['diff_mean']} CI{P['core']['ci95']} 잡음 {P['core']['noise']}"),
        ("2", "핵심성 합성 지표 — release 이상", f">={rel.get('core_index') or 0}", ens.get("core_index"), f"release {rel.get('core_index')} · 차 {P['core_index']['diff_mean']} CI{P['core_index']['ci95']}"),
        ("2", "열린 책 시험 통과(찾아 읽기로 못 답함) ≥85%", ">=0.85", _inv(ens.get("open_book")), f"release {_inv(rel.get('open_book'))}"),
        ("2", "깊은 질문 ≥80%", ">=0.8", ens.get("deep"), f"release {rel.get('deep')}"),
        ("2", "미시 확인 ≤5%", "<=0.05", ens.get("micro"), f"release {rel.get('micro')}"),
        ("2", "뻔한 질문(옮겨심기) ≤10%", "<=0.1", ens.get("transplant"), f"release {rel.get('transplant')}"),
        ("2", "템플릿으로 바뀐 질문 0%", "=0", 0, f"release {tot('release_template')}/{tot('release_n')} (앙상블은 구조상 0 — 버림)"),
        ("2", "애매한 지시어 0", "=0", ens.get("deixis"), f"release {rel.get('deixis')}"),
        ("2", "이중 질문 0", "=0", ens.get("double"), f"release {rel.get('double')}"),
        ("2", "형태: 질문 문장 25~70자 ≥90%", ">=0.9", ens.get("len_ok"), f"release {rel.get('len_ok')}"),
        ("2", "1·2번 중 P1/P2 ≥1 (판 비율)", ">=1.0", _r(sum(1 for e in E if e.get("opening_core_pattern")), n_runs), ""),
        ("2", "같은 노드+각도 중복 0", "=0", tot("dup_node_angle"), ""),
        ("2", "방어형(P7·P9) ≤2 · 확장형(P10) ≥1 (판 비율)", ">=1.0",
         _r(sum(1 for e in E if e.get("defensive", 0) <= 2 and e.get("expansive", 0) >= 1), n_runs), ""),
        ("2", "선택 질문 작성 모델 — 한 모델 ≤90%", "<=0.9", round(max(winners.values()) / wn, 3) if winners else None, json.dumps(winners)),
        ("2", "자기 선호(1등을 자기 것으로 − 기대) ≤+10%p", "<=0.1", max(bias.values()) if bias else None, json.dumps(bias)),
        ("2", "발표 끝 → 1번 (pick_opening) p95 ≤2초", "<=2000", pct(open_ms, 0.95), "ms"),
        ("2", "후보 묶음 완성 p95 ≤90초", "<=90", pct(pool_sec, 0.95), f"p50 {pct(pool_sec, 0.5)}"),
        ("2", "덱당 호출 수(모델별, 묶음)", "<=4", round(max(calls_model.values()) / n_runs, 2) if calls_model else None, json.dumps(calls_model)),
        ("2", "실패 호출(재시도 뒤) 0", "=0", tot("calls_fail"), f"재시도 {tot('calls_retry')}"),
        ("3", "3번+ 핵심 이해 신호 사용 ≥70%", ">=0.7", _r(tot("voice_signal"), tot("voice_n")), ""),
        ("3", "3번+ 미시 차이 질문 0", "=0", tot("voice_micro"), f"심판 micro {voice.get('micro')}"),
        ("3", "1·2번 답만 바꾸면 3번이 바뀜 ≥60%", ">=0.6", _r(sum(e.get("q3_distinct", 1) - 1 for e in E),
                                                             sum(max(0, e.get("flows_n", 1) - 1) for e in E)), ""),
        ("3", "3번 고르기 p95 ≤3초", "<=3", pct(pick3, 0.95), f"p50 {pct(pick3, 0.5)}"),
        ("3", "대신 낸 비율(3·4번) ≤20%", "<=0.2", _r(tot("substituted"), tot("voice_n")),
         f"30초 답 기준 준비 {tot('ready30')}/{tot('flows_n')} · 10초 {tot('ready10')}/{tot('flows_n')}"),
    ]
    out = []
    for stage, name, rule, val, note in rows:
        out.append({"stage": stage, "criterion": name, "rule": rule, "value": val, "pass": _pass(rule, val, rel), "note": note})
    return out


def node_stability(agg: dict) -> float | None:
    """같은 덱의 반복 판끼리 1·2번 노드 집합의 겹침(자카드) 평균."""
    by = defaultdict(list)
    for deck, rep, e in agg["extras"]:
        if e.get("opening_nodes") is not None:
            by[deck].append(set(e["opening_nodes"]))
    vals = []
    for sets in by.values():
        for i in range(len(sets)):
            for j in range(i + 1, len(sets)):
                u = sets[i] | sets[j]
                vals.append(len(sets[i] & sets[j]) / len(u) if u else 1.0)
    return round(st.mean(vals), 3) if vals else None


def _r(a, b):
    return round(a / b, 3) if b else None


def _inv(x):
    return round(1 - x, 3) if x is not None else None


def _pass(rule: str, val, rel: dict) -> str:
    if val is None:
        return "측정 없음"
    try:
        op, th = re.match(r"(>=|<=|=)(.+)", rule).groups()
        th = float(th)
        ok = val >= th if op == ">=" else val <= th if op == "<=" else val == th
        return "통과" if ok else "미달"
    except (AttributeError, ValueError):
        return "?"


def render(agg: dict, crit: list[dict]) -> str:
    L = [f"# Q&A 앙상블 실험 집계 — 판 {agg['runs']}개", "", "## 기준표", "", "| 단계 | 기준 | 규칙 | 실측 | 판정 | 비고 |", "|---|---|---|---|---|---|"]
    for c in crit:
        L.append(f"| {c['stage']} | {c['criterion']} | `{c['rule']}` | {c['value']} | {c['pass']} | {c['note']} |")
    L += ["", "## 세트별 지표", "", "| 세트 | n | core | 합성 | 열린책 | 뻔함 | 미시 | 깊음 | 단일 | 근거 | 요약답 | 특이도 | 특이도0 | thesis·claim | 잎 | 지시어 | 25~70자 |",
          "|" + "---|" * 17]
    for s, v in agg["sets"].items():
        if v:
            L.append(f"| {s} | {v['n']} | {v['core']} | {v['core_index']} | {v['open_book']} | {v['transplant']} | {v['micro']} | "
                     f"{v['deep']} | {v['single']} | {v['grounded']} | {v['summary_ok']} | {v['spec']} | {v['spec_zero']} | "
                     f"{v['thesis_claim']} | {v['leaf']} | {v['deixis']} | {v['len_ok']} |")
    L += ["", "## 짝 차이 (ensemble − release, 같은 덱·같은 반복)", "", "| 지표 | 평균 차 | 95% 구간 | n | 잡음 폭(release/ensemble) |", "|---|---|---|---|---|"]
    for k, v in agg["paired"].items():
        L.append(f"| {k} | {v['diff_mean']} | {v['ci95']} | {v['n']} | {v['noise']} |")
    L += ["", "## 작성 모델별 (앙상블·음성 세트에 뽑힌 질문)", "", "| 모델 | n | core | 합성 | 열린책 | 미시 | 뻔함 | 근거 |", "|---|---|---|---|---|---|---|---|"]
    for a, v in sorted(agg["authors"].items(), key=lambda x: str(x[0])):
        if v:
            L.append(f"| {a} | {v['n']} | {v['core']} | {v['core_index']} | {v['open_book']} | {v['micro']} | {v['transplant']} | {v['grounded']} |")
    L += ["", "## 심판별 core 평균 (세트별)", "", "| 심판 | release | ensemble | voice |", "|---|---|---|---|"]
    for j, d in agg["judge_core"].items():
        L.append(f"| {j} | {d.get('release')} | {d.get('ensemble')} | {d.get('voice')} |")
    E = [e for _, _, e in agg["extras"]]
    L += ["", "## 묶음 · 거르기", "", f"- 후보 통과 {sum(e.get('cands', 0) for e in E)} · 버림 {sum(e.get('dropped', 0) for e in E)}",
          f"- 버린 까닭: {json.dumps(sum_counter([e.get('drop_reasons') for e in E]), ensure_ascii=False)}",
          f"- 모델별 버림: {json.dumps(sum_counter([e.get('drop_by_model') for e in E]))} · 통과: {json.dumps(sum_counter([e.get('kept_by_model') for e in E]))}",
          f"- 음성 버린 까닭: {json.dumps(sum_counter([e.get('voice_drop') for e in E]), ensure_ascii=False)}",
          f"- 짝 비교(release 1·2 vs ensemble 1·2): {json.dumps(sum_counter([e.get('pair') for e in E]))} · A 자리를 고른 비율 "
          f"{_r(sum(e.get('pair_pos_A', 0) for e in E), sum(e.get('pair_n', 0) for e in E))}",
          "", "## 패턴별 서로 평가 점수 (모델:패턴 → 평균, n)", "", json.dumps(agg["pattern_peer"], ensure_ascii=False)]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--split")
    ap.add_argument("--md", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    runs = load_runs(a.paths, a.split)
    agg = aggregate(runs)
    crit = criteria(agg)
    md = render(agg, crit)
    print(md)
    if a.md:
        a.md.write_text(md, encoding="utf-8")
    if a.json:
        a.json.write_text(json.dumps({"criteria": crit, **{k: v for k, v in agg.items() if k != "rows"},
                                      "extras": [(d, r, {k: (dict(v) if isinstance(v, Counter) else v) for k, v in e.items()})
                                                 for d, r, e in agg["extras"]]},
                                     ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        (a.json.with_suffix(".rows.json")).write_text(json.dumps(agg["rows"], ensure_ascii=False, indent=1, default=str),
                                                      encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
