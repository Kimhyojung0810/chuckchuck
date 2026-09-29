"""
WP-C 평가 — **같은 LLM 응답**(얼린 것)에서 코드만 바꿔 F-07 후처리 → F-26 주장 → 탐침을 잰다 (2026-09-30).

F-07 은 실행마다 노드가 8개도 21개도 나온다 (09-29 graph_ab 남은 문제 3). 그래서 그래프 **한 벌**로 주장·탐침을 재면
운이 섞인다. 여기서는 덱마다 그래프 여러 벌에 같은 코드를 태운다:

    bench     벤치 캐시 out/<덱>/graph.json 그대로 (int3 후처리까지 끝난 그래프) — F-26 만
    audit     held-out 감사(09-30 00:20, 브리지 8799) 세션 그래프 그대로 — F-26 만. 감사에서 긴장 T1 을 놓친 바로 그 그래프
    audit_re  위 그래프를 F-07 응답인 척 다시 넣어 **이 코드의 후처리**까지
    ab_s0/1   09-29 graph_ab 가 얼린 F-07 원응답(main 프롬프트, 표본 2개)을 이 코드의 build_graph 로 — 후처리 짝 비교
    p5        P5 최종 평가(ecf9a16)의 성긴 그래프(건강 8노드)를 응답인 척 — 성긴 실행에서 후처리가 받쳐 주는가

같은 명령을 코드 뿌리만 바꿔 두 번 돌리면 전후 비교다 (`--code-root` — 기준 커밋은 `git archive` 로 풀어 둔다).
F-07 프롬프트를 바꿨어도 ab·p5 는 **기준 프롬프트로 되써서** 후처리만 잰다 (`--base-root` 의 SYSTEM_PROMPT·_build_user_prompt).
F-26 LLM 주장은 얼린 응답(out/<덱>/claims_llm.json · out/_wpc/llm_claims.json)을 쓰고, 프롬프트가 바뀌어 없으면
`--live-claims` 일 때만 부른다 (예산 `--budget`). 안 부르면 그 칸은 규칙 주장만이고 `llm: miss` 로 적는다.

    .venv/bin/python labs/qa_bench/wpc_eval.py run --code-root <풀어 둔 기준> --out out/_wpc/before.json
    .venv/bin/python labs/qa_bench/wpc_eval.py run --out out/_wpc/after.json --live-claims --budget 30
    .venv/bin/python labs/qa_bench/wpc_eval.py compare out/_wpc/before.json out/_wpc/after.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
WPC = HERE / "out" / "_wpc"
HELDOUT_T1 = ("health_glucose", "ir_banchan", "policy_jeonse", "lib_reopen", "hum_novel")
CONTROLS = ("sci_led", "prod_tumsae")
VARIANTS = ("bench", "audit", "audit_re", "ab_s0", "ab_s1", "p5")


def _boot(code_root: Path):
    """대상 코드의 chuckchuck 을 **먼저** 올린다 — run.py 가 sys.path 앞에 이 작업 트리를 넣어도 이미 올린 패키지를 쓴다."""
    sys.path.insert(0, str(code_root))
    import chuckchuck  # noqa: F401

    got = Path(chuckchuck.__file__).resolve()
    if code_root.resolve() not in got.parents:
        raise SystemExit(f"대상 코드가 아니라 {got} 를 올렸어요")
    sys.path.insert(1, str(HERE))
    import run as B  # noqa: E402
    import metrics as M  # noqa: E402
    from chuckchuck.providers.llm_base import LLMProvider

    # 가짜 제공자는 **대상 코드의** LLMProvider 여야 한다 — build_graph 가 isinstance 로 가른다
    global _Store, _Fixed, _Claims, _LiveStore
    _Store, _Fixed, _Claims, _LiveStore = (type(c.__name__, (c, LLMProvider), {})
                                           for c in (_Store, _Fixed, _Claims, _LiveStore))
    return B, M


def _base_f07(base_root: Path):
    """기준 f07 의 프롬프트 두 개 — 얼린 F-07 응답의 열쇠(system·user)를 맞춘다."""
    spec = importlib.util.spec_from_file_location("chuckchuck._wpc_base_f07", base_root / "chuckchuck" / "f07_graph.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.SYSTEM_PROMPT, mod._build_user_prompt


class _Store:
    """(tag, system, user) → 얼린 응답. 없으면 links 는 빈 응답, 그 밖은 실패 (그래프 재생은 LLM 을 부르지 않는다)."""

    def __init__(self, B, path: Path, tag: str):
        self.B, self.store, self.tag = B, B.read_json(path) or {}, tag
        self.name = "store"
        self.miss = 0

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        got = self.store.get(self.B.h(self.tag, system, user))
        if got is not None:
            self.name = got.get("model", "store")
            return got["text"]
        self.miss += 1
        if "concept-links" in user:
            return '{"links": []}'
        raise RuntimeError("얼린 F-07 응답이 없어요")


class _Fixed:
    """완성된 그래프를 F-07 응답인 척 — 이 코드의 후처리만 다시 태운다 (연결 보강은 빈 응답)."""
    name = "fixed"

    def __init__(self, g: dict):
        self.payload = json.dumps({
            "nodes": [{"id": n["id"], "label": n["label"], "slide_nos": n["slide_nos"], "summary": n.get("summary", ""),
                       "importance": n.get("importance", "core"), "parent": n.get("parent_id")} for n in g["nodes"]],
            "edges": [e for e in g.get("edges") or [] if e.get("kind") == "relates"],
            "sections": g.get("sections") or []}, ensure_ascii=False)

    def complete(self, *, system, user, **_k):
        return self.payload if "concept-links" not in user else '{"links": []}'


class _Claims:
    """F-26 응답 — 얼린 것 먼저 (덱 저장소 → 이 평가 저장소), 없으면 --live-claims 일 때만 부른다."""

    def __init__(self, B, deck: str, live: bool):
        self.B, self.deck, self.live = B, deck, live
        self.frozen = B.read_json(B.OUT / deck / "claims_llm.json") or {}
        # 09-29 graph_ab 가 abd 갈래 표본 0 그래프로 부른 F-26 응답 — 열쇠에 태그 「c」 가 붙어 있다
        self.ab = B.read_json(B.OUT / "_graph_ab" / deck / "llm_claims.json") or {}
        self.path = WPC / "llm_claims.json"
        self.name = "frozen"
        self.status = "none"

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        key = self.B.h(system, user)
        mine = self.B.read_json(self.path) or {}
        got = self.frozen.get(key) or mine.get(key) or self.ab.get(self.B.h("c", system, user))
        if got is not None:
            self.status = "frozen"
            self.name = got.get("model", "frozen")
            return got["text"]
        if not self.live:
            self.status = "miss"
            raise RuntimeError("얼린 F-26 응답이 없어요 (--live-claims 로 부른다)")
        eng = self.B.engine(self.deck, "wpc_claims")
        text = eng.complete(system=system, user=user, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
        mine = self.B.read_json(self.path) or {}
        mine[key] = {"model": eng.name, "text": text}
        self.B.write_json(self.path, mine)
        self.status = "live"
        self.name = eng.name
        return text


def _graphs(B, deck: str, spec: dict, variants: list[str], base_prompts) -> dict[str, dict]:
    """변형 이름 → 그래프 dict. 만들 재료가 없는 변형은 빠진다."""
    from chuckchuck import f07_graph as F7
    from chuckchuck.contracts import ConceptDoc, Context, SlideDoc

    out: dict[str, dict] = {}
    d = B.OUT / deck
    cd, sd = B.read_json(d / "concept_doc.json"), B.read_json(d / "slide_doc.json")
    ctx = Context.from_dict(spec.get("context") or {})

    def rebuild(llm) -> dict:
        saved = F7.SYSTEM_PROMPT, F7._build_user_prompt
        if base_prompts is not None:
            F7.SYSTEM_PROMPT, F7._build_user_prompt = base_prompts
        try:
            return F7.build_graph(ConceptDoc.from_dict(cd), ctx, slide_doc=SlideDoc.from_dict(sd), llm=llm).to_dict()
        finally:
            F7.SYSTEM_PROMPT, F7._build_user_prompt = saved

    if "bench" in variants and (d / "graph.json").exists():
        out["bench"] = B.read_json(d / "graph.json")
    audit = B.read_json(WPC / "audit" / f"{deck}.json")
    if audit and "audit" in variants:
        out["audit"] = audit
    if audit and "audit_re" in variants and cd:
        out["audit_re"] = rebuild(_Fixed(audit))
    store = B.OUT / "_graph_ab" / deck / "llm_graph.json"
    for k in (0, 1):
        name = f"ab_s{k}"
        if name in variants and store.exists() and cd:
            try:
                out[name] = rebuild(_Store(B, store, f"s{k}"))
            except Exception as e:  # noqa: BLE001 — 표본이 없거나 코드가 깨지면 그 칸만 빠진다
                out[name] = {"error": f"{type(e).__name__}: {e}"}
    p5 = B.read_json(B.OUT / "_p5_before" / deck / "graph.json")
    if p5 and "p5" in variants and cd:
        out["p5"] = rebuild(_Fixed(p5))
    return out


def _formula_pieces_ok(q: str, raw: str, M) -> bool:
    """식 인용이 도식 캡션을 건너 이은 것이면 조각마다 원문에 있는가 (연산 기호로 나눈 조각)."""
    import re
    pieces = [p for p in re.split(r"\s*[=×✕*÷+]\s*", q) if p.strip()]
    return len(pieces) >= 2 and all(M.verbatim(p, raw) for p in pieces)


def _measure(B, M, deck: str, spec: dict, g: dict, sd: dict, llm_claims) -> dict:
    from chuckchuck._probes import derive_probes
    from chuckchuck.contracts import ClaimDoc, ConceptGraph
    from chuckchuck.f26_claims import build_claims

    truth = spec.get("truth")
    rows = {}
    for mode in ("rule", "llm"):
        if mode == "llm" and llm_claims is None:
            continue
        try:
            c = build_claims(g, sd, llm="none" if mode == "rule" else llm_claims).to_dict()
        except Exception as e:  # noqa: BLE001
            rows[mode] = {"error": f"{type(e).__name__}: {e}"}
            continue
        probes = [p.to_dict() for p in derive_probes(ConceptGraph.from_dict(g), ClaimDoc.from_dict(c))]
        cm, pm = M.claim_metrics(c, sd, truth), M.probe_metrics(probes, g, truth)
        raw = M.slide_raw(sd)
        quotes = [(e["slide_no"], e["quote"]) for cl in c["claims"] for e in cl["evidence"]]
        strict = sum(1 for no, q in quotes if M.verbatim(q, raw.get(no, "")))
        pieces = sum(1 for no, q in quotes if M.verbatim(q, raw.get(no, "")) or _formula_pieces_ok(q, raw.get(no, ""), M))
        by = {n["id"]: n["label"] for n in g["nodes"]}
        rows[mode] = {
            "model": c.get("model"), "status": getattr(llm_claims, "status", "") if mode == "llm" else "",
            "claims": cm["n"], "dropped": cm["dropped"], "by_kind": cm["by_kind"],
            "planted_claims": [cm.get("planted_hit"), cm.get("planted")], "planted_miss": cm.get("planted_miss"),
            "quotes": len(quotes), "verbatim": strict, "verbatim_pieces": pieces,
            "absolute_no_marker": cm.get("absolute_no_marker"),
            "probes": pm["n"], "probe_kinds": pm["by_kind"], "recall": pm.get("recall_by_id"),
            "precision": [pm.get("plantable_tp"), pm.get("plantable_probes")], "neg_fp": pm.get("negative_fp"),
            "false_tension": pm.get("false_tension"), "natural": pm["natural"],
            "tension": [f"{p['target']}⊃{p['nodes'][1:] }" for p in pm["list"] if p["kind"] == "tension"],
            "unplanted": [f"{p['kind']}:{p['target']}" for p in pm.get("unplanted") or []],
            "claim_list": [f"{cl['kind']} {by.get(cl['subject_id'], cl['subject_id'])} → "
                           f"{[by.get(o, o) for o in cl['object_ids']]} | S{cl['evidence'][0]['slide_no']} "
                           f"«{cl['evidence'][0]['quote'][:60]}»" for cl in c["claims"]],
        }
    return rows


def cmd_run(ns) -> int:
    B, M = _boot(Path(ns.code_root))
    B.BUDGET.limit = ns.budget
    specs = B.load_decks(B.DEFAULT_REPO, set())
    decks = [d for d in (ns.decks.split(",") if ns.decks else specs) if d in specs]
    variants = ns.variants.split(",")
    base_prompts = _base_f07(Path(ns.base_root)) if ns.base_root else None
    result: dict = {"code_root": ns.code_root, "decks": {}}
    for deck in decks:
        spec = specs[deck]
        sd = B.read_json(B.OUT / deck / "slide_doc.json")
        if sd is None:
            continue
        graphs = _graphs(B, deck, spec, variants, base_prompts)
        row: dict = {"group": spec["group"], "truth": bool(spec.get("truth"))}
        for name, g in graphs.items():
            if "error" in g:
                row[name] = {"error": g["error"]}
                continue
            llm = _Claims(B, deck, ns.live_claims) if name in ns.llm_variants.split(",") else None
            row[name] = {"nodes": len(g["nodes"]), "labels": [n["label"] for n in g["nodes"]],
                         **_measure(B, M, deck, spec, g, sd, llm)}
            if ns.save_graphs:
                B.write_json(WPC / "graphs" / Path(ns.out).stem / f"{deck}__{name}.json", g)
        result["decks"][deck] = row
        t1 = {k: (v.get("rule", {}).get("recall") or {}).get("T1") for k, v in row.items() if isinstance(v, dict) and "rule" in v}
        print(f"[{deck}] " + " ".join(f"{k}:{'T1✓' if t else ('T1✗' if t is False else '·')}" for k, t in t1.items()), flush=True)
    result["llm_calls"] = B.BUDGET.used
    out = Path(ns.out)
    B.write_json(out if out.is_absolute() else ROOT / out, result)
    print(f"LLM 호출 {B.BUDGET.used} · {out}")
    return 0


def _frac(xs) -> str:
    xs = [x for x in xs if x is not None]
    return f"{sum(1 for x in xs if x)}/{len(xs)}"


def summarize(res: dict, mode: str) -> dict:
    """변형마다: 긴장 T1 재현(held-out 5) · 대조군 거짓 긴장 · 심은 주장 · 탐침 재현·정밀도 · 음성 오탐 · 인용 원문."""
    table: dict = {}
    for v in VARIANTS:
        t1, ft, pc, pr, prec, neg, verb, quotes, pieces = [], 0, [0, 0], [0, 0], [0, 0], 0, 0, 0, 0
        seen = False
        for deck, row in res["decks"].items():
            r = (row.get(v) or {}).get(mode)
            if not r or "error" in r:
                continue
            seen = True
            if deck in HELDOUT_T1:
                t1.append((r.get("recall") or {}).get("T1"))
            if deck in CONTROLS:
                ft += r.get("false_tension") or 0
            if r["planted_claims"][1]:
                pc[0] += r["planted_claims"][0] or 0
                pc[1] += r["planted_claims"][1]
            rec = r.get("recall") or {}
            pr[0] += sum(1 for x in rec.values() if x)
            pr[1] += len(rec)
            prec[0] += r["precision"][0] or 0
            prec[1] += r["precision"][1] or 0
            neg += len(r.get("neg_fp") or [])
            verb += r["verbatim"]
            pieces += r["verbatim_pieces"]
            quotes += r["quotes"]
        if seen:
            table[v] = {"T1": _frac(t1), "false_tension": ft, "planted_claims": f"{pc[0]}/{pc[1]}",
                        "probe_recall": f"{pr[0]}/{pr[1]}", "precision": f"{prec[0]}/{prec[1]}", "neg_fp": neg,
                        "verbatim": f"{verb}/{quotes}", "verbatim_pieces": f"{pieces}/{quotes}"}
    return table


def cmd_compare(ns) -> int:
    runs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in ns.files]
    for mode in ("rule", "llm"):
        print(f"\n## {mode}")
        cols = ["T1", "false_tension", "planted_claims", "probe_recall", "precision", "neg_fp", "verbatim", "verbatim_pieces"]
        print("| 변형 | 실행 | " + " | ".join(cols) + " |")
        print("|---|---|" + "---|" * len(cols))
        for v in VARIANTS:
            for p, res in zip(ns.files, runs):
                s = summarize(res, mode).get(v)
                if s:
                    print(f"| {v} | {Path(p).stem} | " + " | ".join(str(s[c]) for c in cols) + " |")
    if ns.detail:
        for deck in runs[-1]["decks"]:
            for v in VARIANTS:
                cells = []
                for res in runs:
                    r = ((res["decks"].get(deck) or {}).get(v) or {}).get(ns.detail_mode) or {}
                    cells.append(f"{r.get('recall')} prec={r.get('precision')} fp={r.get('neg_fp')} tension={r.get('tension')}")
                if any(c != cells[0] for c in cells):
                    print(f"\n{deck}/{v}\n  " + "\n  ".join(cells))
    return 0


class _LiveStore:
    """F-07 새 프롬프트 표본 — (tag, system, user) 로 얼리고, 없으면 부른다 (예산 안에서). 연결 보강도 같은 저장소."""

    def __init__(self, B, deck: str, path: Path, tag: str):
        self.B, self.deck, self.path, self.tag = B, deck, path, tag
        self.name = "store"
        self.calls = 0

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        key = self.B.h(self.tag, system, user)
        store = self.B.read_json(self.path) or {}
        if key in store:
            self.name = store[key].get("model", "store")
            return store[key]["text"]
        eng = self.B.engine(self.deck, "wpc_graph")
        text = eng.complete(system=system, user=user, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
        self.calls += 1
        self.name = eng.name
        store = self.B.read_json(self.path) or {}
        store[key] = {"model": eng.name, "text": text}
        self.B.write_json(self.path, store)
        return text


def _label_key(label: str) -> str:
    from chuckchuck import _graph_items as GI
    return GI.label_keys(label)[1]


def _stability(a: dict, b: dict) -> dict:
    """두 표본의 이름 자카드와 부모 일치율 (같은 이름 노드의 부모 이름이 같은 비율) — graph_ab 와 같은 잣대."""
    ka = {_label_key(n["label"]): n for n in a["nodes"]}
    kb = {_label_key(n["label"]): n for n in b["nodes"]}
    common = set(ka) & set(kb)
    la = {n["id"]: _label_key(n["label"]) for n in a["nodes"]}
    lb = {n["id"]: _label_key(n["label"]) for n in b["nodes"]}
    same = sum(1 for k in common if la.get(ka[k].get("parent_id")) == lb.get(kb[k].get("parent_id")))
    return {"jaccard": round(len(common) / max(1, len(set(ka) | set(kb))), 3),
            "parent_agree": round(same / max(1, len(common)), 3), "common": len(common)}


def _shape(g: dict) -> dict:
    roots = [n for n in g["nodes"] if not n.get("parent_id")]
    return {"nodes": len(g["nodes"]), "roots": len(roots), "depth3": sum(1 for n in g["nodes"] if n["depth"] == 3),
            "relates": sum(1 for e in g["edges"] if e["kind"] == "relates")}


def cmd_prompt_ab(ns) -> int:
    """
    F-07 프롬프트 A/B — 기준 프롬프트(얼린 graph_ab 응답 s0·s1)와 지금 프롬프트(새로 부른 n0·n1)를 **같은 후처리**로 조립해
    표본 두 번의 위계 일치율(부모 일치)·이름 자카드·노드 수를 견준다. 09-29 A/B 가 예시 id 를 바꾸자 부모 일치가
    0.61 → 0.43 으로 떨어진 전례가 있어서, 떨어짐이 0.05 를 넘으면 되돌린다 (판단은 사람이 표를 보고).
    """
    B, M = _boot(Path(ns.code_root))
    B.BUDGET.limit = ns.budget
    specs = B.load_decks(B.DEFAULT_REPO, set())
    base_prompts = _base_f07(Path(ns.base_root))
    from chuckchuck import f07_graph as F7
    from chuckchuck.contracts import ConceptDoc, Context, SlideDoc

    rows: dict = {}
    for deck in ns.decks.split(","):
        d = B.OUT / deck
        cd, sd = B.read_json(d / "concept_doc.json"), B.read_json(d / "slide_doc.json")
        spec = specs[deck]
        ctx = Context.from_dict(spec.get("context") or {})
        arms: dict[str, list[dict]] = {"base": [], "new": []}
        for k in range(ns.samples):
            saved = F7.SYSTEM_PROMPT, F7._build_user_prompt
            F7.SYSTEM_PROMPT, F7._build_user_prompt = base_prompts
            try:
                g = F7.build_graph(ConceptDoc.from_dict(cd), ctx, slide_doc=SlideDoc.from_dict(sd),
                                   llm=_Store(B, B.OUT / "_graph_ab" / deck / "llm_graph.json", f"s{k}")).to_dict()
                arms["base"].append(g)
            except Exception as e:  # noqa: BLE001
                print(f"[{deck}] base s{k} 없음: {e}")
            finally:
                F7.SYSTEM_PROMPT, F7._build_user_prompt = saved
            live = _LiveStore(B, deck, WPC / "llm_graph_new" / f"{deck}.json", f"n{k}")
            try:
                arms["new"].append(F7.build_graph(ConceptDoc.from_dict(cd), ctx, slide_doc=SlideDoc.from_dict(sd), llm=live).to_dict())
            except Exception as e:  # noqa: BLE001
                print(f"[{deck}] new n{k} 실패: {type(e).__name__}: {e}")
        row: dict = {}
        for arm, gs in arms.items():
            t1 = []
            for g in gs:
                B.write_json(WPC / "graphs" / "prompt_ab" / f"{deck}__{arm}{len(t1)}.json", g)
                r = _measure(B, M, deck, spec, g, sd, None)["rule"]
                t1.append((r.get("recall") or {}).get("T1"))
            row[arm] = {"shapes": [_shape(g) for g in gs], "T1": t1,
                        "false_tension": [(_measure(B, M, deck, spec, g, sd, None)["rule"].get("false_tension")) for g in gs],
                        "stab": _stability(gs[0], gs[1]) if len(gs) >= 2 else None}
        rows[deck] = row
        print(f"[{deck}] " + " · ".join(f"{a}: 부모일치 {(r['stab'] or {}).get('parent_agree')} 자카드 {(r['stab'] or {}).get('jaccard')} "
                                         f"노드 {[x['nodes'] for x in r['shapes']]} T1 {r['T1']}" for a, r in row.items()), flush=True)
    out = WPC / "prompt_ab.json"
    B.write_json(out, rows)
    for arm in ("base", "new"):
        st = [r[arm]["stab"] for r in rows.values() if r[arm]["stab"]]
        if st:
            pa = sum(x["parent_agree"] for x in st) / len(st)
            ja = sum(x["jaccard"] for x in st) / len(st)
            print(f"{arm}: 부모 일치 평균 {pa:.3f} · 자카드 평균 {ja:.3f} · 덱 {len(st)}")
    print(f"LLM 호출 {B.BUDGET.used}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="labs/qa_bench/wpc_eval.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--code-root", default=str(ROOT))
    r.add_argument("--base-root", default="", help="얼린 F-07 응답의 프롬프트를 가져올 기준 코드 뿌리 (프롬프트를 바꿨을 때)")
    r.add_argument("--out", required=True)
    r.add_argument("--decks", default="")
    r.add_argument("--variants", default=",".join(VARIANTS))
    r.add_argument("--llm-variants", default="bench,audit", help="F-26 LLM 주장까지 잴 변형 (나머지는 규칙 주장만)")
    r.add_argument("--live-claims", action="store_true")
    r.add_argument("--budget", type=int, default=0)
    r.add_argument("--save-graphs", action="store_true")
    a = sub.add_parser("prompt_ab")
    a.add_argument("--code-root", default=str(ROOT))
    a.add_argument("--base-root", required=True)
    a.add_argument("--decks", default="health_glucose,ir_banchan,policy_jeonse,lib_reopen,hum_novel,prod_tumsae")
    a.add_argument("--samples", type=int, default=2)
    a.add_argument("--budget", type=int, default=30)
    c = sub.add_parser("compare")
    c.add_argument("files", nargs="+")
    c.add_argument("--detail", action="store_true")
    c.add_argument("--detail-mode", default="rule")
    ns = ap.parse_args(argv)
    return {"run": cmd_run, "prompt_ab": cmd_prompt_ab, "compare": cmd_compare}[ns.cmd](ns)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
