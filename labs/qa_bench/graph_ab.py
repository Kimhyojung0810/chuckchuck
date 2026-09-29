"""
F-07 그래프 후처리 **A/B** — 같은 개념(F-06 캐시)에서 F-07 만 바꿔, 그래프 모양과 그 아래(F-26 주장 → 탐침)를 잰다.

F-07 프롬프트를 고칠 때마다 위계가 흔들린 전례가 있어서(19b66ea 노드 links 칸), 후처리만 바꾼 쪽과 프롬프트까지
바꾼 쪽을 따로 잰다. 세 갈래:

    base  main(ecf9a16) 의 f07·f26 그대로 (git show 로 읽어 따로 올린다)
    abd   새 f07 후처리(항목 메우기 A·겹친 이름 합치기 B) + 새 f26 _resolve_id(D), 프롬프트는 main 그대로
    abcd  위 + 프롬프트 예시 id 중립화(C)

abd 는 **base 와 같은 LLM 응답을 되쓴다** (프롬프트가 같으니 응답 저장소의 같은 칸) — 그래서 base↔abd 차이는
후처리 탓만 남는다(짝 비교). abcd 는 프롬프트가 달라 새로 부른다. 저장: out/_graph_ab/<덱>/.

    .venv/bin/python labs/qa_bench/graph_ab.py run --samples 2 --budget 140
    .venv/bin/python labs/qa_bench/graph_ab.py report          # LLM 0콜 — 저장된 그래프에서 표만 다시
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import run as B  # noqa: E402 — load_dotenv·예산·호출 기록을 그대로 쓴다
import metrics as M  # noqa: E402
from chuckchuck import _graph_items as GI  # noqa: E402
from chuckchuck._claim_rules import same_concept  # noqa: E402
from chuckchuck.contracts import ConceptDoc, ConceptGraph, Context, SlideDoc  # noqa: E402
from chuckchuck.providers.llm_base import LLMProvider  # noqa: E402

AB = B.OUT / "_graph_ab"
BASE_REV = "ecf9a16"
ARMS = ("base", "abd", "abcd")
DECKS = ("ir_banchan", "sci_led", "policy_jeonse", "hum_novel", "prod_tumsae", "health_glucose",
         "focus", "sk_hynix", "lib_reopen", "sleep", "yield_gap")
TUNED = ("sleep", "yield_gap")          # 튜닝에 쓴 덱은 한 번씩만 (확인용)


# ---------------------------------------------------------------------------
# 모듈 세 벌
# ---------------------------------------------------------------------------

def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _base_module(stem: str):
    AB.mkdir(parents=True, exist_ok=True)
    path = AB / f"_base_{stem}.py"
    path.write_bytes(subprocess.check_output(["git", "show", f"{BASE_REV}:chuckchuck/{stem}.py"], cwd=ROOT))
    return _load(f"chuckchuck._ab_base_{stem}", path)


def c_prompt(prompt: str) -> str:
    """C: 예시 id 를 예시 이름의 뜻으로 바꾸고, 예시 id 를 따라 쓰지 말라고 한 줄."""
    for old, new in (('"contrast"', '"main-topic"'), ('"joint"', '"element"'), ('"encoder"', '"detail"'),
                     ('"baseline"', '"other-element"')):
        prompt = prompt.replace(old, new)
    return prompt.replace("7. id 는 영소문자·숫자·하이픈만 쓴다. 짧고 의미 있게. 유일해야 한다.",
                          "7. id 는 영소문자·숫자·하이픈만 쓴다. 그 노드 label 의 뜻을 옮긴 짧은 영어 낱말로, 유일하게."
                          " 출력 스키마의 예시 id 를 따라 쓰지 마라.")


def modules() -> dict[str, tuple]:
    f07_base, f26_base = _base_module("f07_graph"), _base_module("f26_claims")
    f07_path, f26_path = ROOT / "chuckchuck" / "f07_graph.py", ROOT / "chuckchuck" / "f26_claims.py"
    p0 = _load("chuckchuck._ab_new_f07_p0", f07_path)
    p0.SYSTEM_PROMPT = f07_base.SYSTEM_PROMPT
    p1 = _load("chuckchuck._ab_new_f07_p1", f07_path)
    p1.SYSTEM_PROMPT = c_prompt(f07_base.SYSTEM_PROMPT)
    f26_new = _load("chuckchuck._ab_new_f26", f26_path)
    return {"base": (f07_base, f26_base), "abd": (p0, f26_new), "abcd": (p1, f26_new)}


# ---------------------------------------------------------------------------
# 응답 저장소 — 같은 (표본 번호, system, user) 면 되쓴다
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()


class Store(LLMProvider):
    def __init__(self, deck: str, stage: str, path: Path, tag: str, live: bool = True):
        self.deck, self.stage, self.path, self.tag, self.live = deck, stage, path, tag, live
        self.name = "store"
        self.hits = self.calls = 0

    def complete(self, *, system: str, user: str, temperature: float = 0.2, max_tokens: int = 4096,
                 json_mode: bool = False) -> str:
        key = B.h(self.tag, system, user)
        with _LOCK:
            store = B.read_json(self.path) or {}
        if key in store:
            self.hits += 1
            self.name = store[key].get("model", "store")
            return store[key]["text"]
        if not self.live:
            raise RuntimeError(f"{self.deck}: 저장된 응답이 없어요 ({self.stage})")
        eng = B.engine(self.deck, self.stage)
        text = eng.complete(system=system, user=user, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
        self.calls += 1
        self.name = eng.name
        with _LOCK:
            store = B.read_json(self.path) or {}
            store[key] = {"model": eng.name, "text": text}
            B.write_json(self.path, store)
        return text


# ---------------------------------------------------------------------------
# 한 덱 돌리기
# ---------------------------------------------------------------------------

def _capture(f07):
    """_assemble 이 고른 thesis 와 _add_items 가 더한 수를 잡는다 (그래프 계약엔 thesis 칸이 없다)."""
    box = threading.local()
    orig_asm = f07._assemble

    def asm(*a, **k):
        out = orig_asm(*a, **k)
        box.thesis = out[3]
        return out
    f07._assemble = asm
    if hasattr(f07, "_add_items"):
        orig_add = f07._add_items

        def add(nodes, *a, **k):
            before = len(nodes)
            out = orig_add(nodes, *a, **k)
            box.added = len(nodes) - before
            return out
        f07._add_items = add
    return box


def run_deck(deck: str, spec: dict, mods: dict, samples: int, live: bool) -> None:
    d = B.OUT / deck
    cd, sd = B.read_json(d / "concept_doc.json"), B.read_json(d / "slide_doc.json")
    if cd is None or sd is None:
        B.note(f"[{deck}] 캐시 없음 — 건너뜀")
        return
    out = AB / deck
    out.mkdir(parents=True, exist_ok=True)
    ctx = Context.from_dict(spec["context"])
    n = 1 if deck in TUNED else samples
    for arm in ARMS:
        f07, f26 = mods[arm]
        for k in range(n):
            fg = out / f"{arm}_s{k}.json"
            if fg.exists():
                continue
            box = mods["_boxes"][arm]
            box.thesis, box.added = None, 0
            eng = Store(deck, f"graph:{arm}", out / "llm_graph.json", f"s{k}", live=live)
            g = f07.build_graph(ConceptDoc.from_dict(cd), ctx, slide_doc=SlideDoc.from_dict(sd), llm=eng)
            B.write_json(fg, {"graph": g.to_dict(), "thesis": box.thesis, "added": getattr(box, "added", 0),
                              "calls": eng.calls, "hits": eng.hits})
            B.note(f"[{deck}] {arm} s{k} 노드 {len(g.nodes)} (더함 {getattr(box, 'added', 0)}) 호출 {eng.calls} 되씀 {eng.hits}")
        # 주장: 표본마다 규칙만(0콜), 표본 0 은 LLM 주장까지
        for k in range(n):
            g = B.read_json(out / f"{arm}_s{k}.json")["graph"]
            fr = out / f"{arm}_s{k}_claims_rule.json"
            if not fr.exists():
                B.write_json(fr, f26.build_claims(g, sd, llm="none").to_dict())
        fl = out / f"{arm}_s0_claims_llm.json"
        if not fl.exists():
            g = B.read_json(out / f"{arm}_s0.json")["graph"]
            eng = Store(deck, f"claims:{arm}", out / "llm_claims.json", "c", live=live)
            B.write_json(fl, f26.build_claims(g, sd, llm=eng).to_dict())


# ---------------------------------------------------------------------------
# 지표
# ---------------------------------------------------------------------------

def _key(label: str) -> str:
    return GI.label_keys(label)[1]


def _subtree(g: dict) -> dict[str, int]:
    size = {n["id"]: 1 for n in g["nodes"]}
    par = {n["id"]: n.get("parent_id") for n in g["nodes"]}
    for nid in par:
        cur, seen = par[nid], set()
        while cur and cur in size and cur not in seen:
            seen.add(cur)
            size[cur] += 1
            cur = par.get(cur)
    return size


def formula_cover(g: dict, sd: dict, f26) -> tuple[int, int]:
    """식의 항 중 노드 이름에 있는 수 — f26 의 줄 읽기(slide_lines·_formula_parts)로 따로 센다 (후처리와 다른 길)."""
    labels = [M.norm(n["label"]) for n in g["nodes"]]
    raw_labels = [n["label"] for n in g["nodes"]]
    hit = tot = 0
    for s in sd["slides"]:
        for line in f26.slide_lines(s.get("raw_text") or ""):
            parsed = f26._formula_parts(line)
            if not parsed:
                continue
            for p in parsed[1]:
                q = M.norm(p)
                if len(q) < 2 or any(ch.isdigit() for ch in q):
                    continue
                tot += 1
                hit += any(q == lab or (len(q) >= 2 and q in lab and len(lab) - len(q) <= 3) for lab in labels) \
                    or any(same_concept(p, lab) for lab in raw_labels)
    return hit, tot


def graph_stats(rec: dict, sd: dict, truth: dict | None, f26) -> dict:
    g = rec["graph"]
    nodes = g["nodes"]
    keys = [_key(n["label"]) for n in nodes]
    by = {n["id"]: n for n in nodes}
    size = _subtree(g)
    roots = [n for n in nodes if not n.get("parent_id")]
    top_root = max(roots, key=lambda n: (size[n["id"]], n["weight"]))["id"] if roots else None
    th = rec.get("thesis")
    planted = [t for t in (truth or {}).get("planted") or [] if t["expect"] == "probe" and t.get("labels_any")]
    fh, ft = formula_cover(g, sd, f26)
    depth = {d: sum(1 for n in nodes if n["depth"] == d) for d in (1, 2, 3)}
    return {
        "nodes": len(nodes), "added": rec.get("added", 0), "dup_exact": len(keys) - len(set(keys)),
        "dup_near": sum(1 for a, b in combinations([n["label"] for n in nodes], 2) if GI.same_label(a, b) or same_concept(a, b)),
        "roots": len(roots), "depth": depth,
        "thesis": by.get(th, {}).get("label", "") if th else "", "thesis_root": bool(th in by and not by[th].get("parent_id")),
        "thesis_top": bool(th and th == top_root),
        "planted_nodes": sum(1 for t in planted if any(M._has_any(n["label"], t["labels_any"]) for n in nodes)),
        "planted_n": len(planted), "formula_hit": fh, "formula_n": ft,
        "ids_example": sum(1 for n in nodes if n["id"].split("-")[0] in ("contrast", "joint", "encoder", "baseline")),
        "relates": sum(1 for e in g["edges"] if e["kind"] == "relates"),
    }


def stability(a: dict, b: dict) -> dict:
    ka = {_key(n["label"]): n for n in a["graph"]["nodes"]}
    kb = {_key(n["label"]): n for n in b["graph"]["nodes"]}
    common = set(ka) & set(kb)
    la = {n["id"]: _key(n["label"]) for n in a["graph"]["nodes"]}
    lb = {n["id"]: _key(n["label"]) for n in b["graph"]["nodes"]}
    same_parent = sum(1 for k in common if la.get(ka[k].get("parent_id")) == lb.get(kb[k].get("parent_id")))
    return {"jaccard": round(len(common) / max(1, len(set(ka) | set(kb))), 3),
            "parent_agree": round(same_parent / max(1, len(common)), 3), "common": len(common)}


def downstream(claims: dict, g: dict, sd: dict, truth: dict | None) -> dict:
    from chuckchuck._probes import derive_probes

    cm = M.claim_metrics(claims, sd, truth)
    probes = [p.to_dict() for p in derive_probes(ConceptGraph.from_dict(g), claims)]
    pm = M.probe_metrics(probes, g, truth)
    return {"claims": cm["n"], "dropped": cm["dropped"], "planted_claims": cm.get("planted_hit"),
            "planted_claims_n": cm.get("planted"), "probes": pm["n"], "probe_kinds": pm["by_kind"],
            "probe_hit": pm.get("planted_hit"), "probe_n": pm.get("planted"),
            "plantable": pm.get("plantable_probes"), "plantable_tp": pm.get("plantable_tp"),
            "neg_fp": len(pm.get("negative_fp") or []), "natural": pm["natural"],
            "recall_by_id": pm.get("recall_by_id")}


def collect(decks: list[str], specs: dict, mods: dict) -> dict:
    rows: dict = {}
    for deck in decks:
        out = AB / deck
        sd = B.read_json(B.OUT / deck / "slide_doc.json")
        truth = specs[deck].get("truth")
        for arm in ARMS:
            f26 = mods[arm][1]
            recs = sorted(out.glob(f"{arm}_s[0-9].json"))
            if not recs:
                continue
            gs, rule_ds = [], []
            for p in recs:
                rec = B.read_json(p)
                gs.append(graph_stats(rec, sd, truth, f26))
                cl = B.read_json(p.with_name(p.stem + "_claims_rule.json"))
                rule_ds.append(downstream(cl, rec["graph"], sd, truth) if cl else None)
            llm = B.read_json(out / f"{arm}_s0_claims_llm.json")
            llm_d = downstream(llm, B.read_json(out / f"{arm}_s0.json")["graph"], sd, truth) if llm else None
            stab = [stability(B.read_json(a), B.read_json(b)) for a, b in combinations(recs, 2)]
            rows.setdefault(deck, {})[arm] = {"graphs": gs, "rule": rule_ds, "llm": llm_d, "stab": stab,
                                              "group": specs[deck]["group"]}
    return rows


def _mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def summarize(rows: dict) -> dict:
    """갈래별 합계 — 표본 평균을 덱마다 낸 뒤 덱을 더한다 (tuned 덱은 따로)."""
    out: dict = {}
    for scope, keep in (("heldout+new", lambda g: g != "tuned"), ("tuned", lambda g: g == "tuned")):
        for arm in ARMS:
            decks = [d for d, r in rows.items() if arm in r and keep(r[arm]["group"])]
            if not decks:
                continue
            R = [rows[d][arm] for d in decks]

            def tot(field, src="graphs"):
                return round(sum(_mean([x[field] for x in r[src] if x]) or 0 for r in R), 2)

            def tot_llm(field):
                return sum((r["llm"] or {}).get(field) or 0 for r in R)
            out.setdefault(scope, {})[arm] = {
                "decks": len(decks),
                "nodes": tot("nodes"), "added": tot("added"), "dup_exact": tot("dup_exact"), "dup_near": tot("dup_near"),
                "roots": tot("roots"), "thesis_root": tot("thesis_root"), "thesis_top": tot("thesis_top"),
                "planted_nodes": f"{tot('planted_nodes')}/{tot('planted_n')}",
                "formula": f"{tot('formula_hit')}/{tot('formula_n')}",
                "ids_example": tot("ids_example"),
                "jaccard": _mean([s["jaccard"] for r in R for s in r["stab"]]),
                "parent_agree": _mean([s["parent_agree"] for r in R for s in r["stab"]]),
                "rule_claims": tot("claims", "rule"),
                "rule_planted_claims": f"{tot('planted_claims', 'rule')}/{tot('planted_claims_n', 'rule')}",
                "rule_probe_hit": f"{tot('probe_hit', 'rule')}/{tot('probe_n', 'rule')}",
                "rule_precision": f"{tot('plantable_tp', 'rule')}/{tot('plantable', 'rule')}",
                "llm_claims": tot_llm("claims"), "llm_dropped": tot_llm("dropped"),
                "llm_planted_claims": f"{tot_llm('planted_claims')}/{tot_llm('planted_claims_n')}",
                "llm_probe_hit": f"{tot_llm('probe_hit')}/{tot_llm('probe_n')}",
                "llm_precision": f"{tot_llm('plantable_tp')}/{tot_llm('plantable')}",
                "llm_neg_fp": tot_llm("neg_fp"), "llm_probes": tot_llm("probes"), "llm_natural": tot_llm("natural"),
            }
    return out


class _Fixed(LLMProvider):
    """P5 그래프를 F-07 응답인 척 돌려준다 — 후처리만 다시 태운다 (연결 보강은 빈 응답)."""
    name = "p5-replay"

    def __init__(self, payload: str):
        self.payload = payload

    def complete(self, *, system: str, user: str, **_k) -> str:
        return self.payload if "concept-links" not in user else '{"links": []}'


def run_p5(decks: list[str], specs: dict, mods: dict) -> dict:
    """
    P5 최종 평가(ecf9a16)가 **실제로 낸** 그래프로 짝 비교 — base = 그 그래프 그대로, abd = 그 그래프에 새 후처리.
    P5 는 노드가 적게 나온 실행이라(건강 8노드) 항목 메우기가 필요한 바로 그 경우다. 주장 LLM 은 P5 응답 저장소
    (out/<덱>/claims_llm.json)를 되쓰고, 그래프가 바뀐 덱만 새로 부른다. thesis 는 P5 그래프에 없어 모른다.
    """
    rows: dict = {}
    for deck in decks:
        d = B.OUT / deck
        g0, cd, sd = B.read_json(d / "graph.json"), B.read_json(d / "concept_doc.json"), B.read_json(d / "slide_doc.json")
        if g0 is None:
            continue
        payload = json.dumps({"nodes": [{"id": n["id"], "label": n["label"], "slide_nos": n["slide_nos"],
                                         "summary": n["summary"], "importance": n["importance"],
                                         "parent": n.get("parent_id")} for n in g0["nodes"]],
                              "edges": [e for e in g0["edges"] if e["kind"] == "relates"],
                              "sections": g0.get("sections") or []}, ensure_ascii=False)
        truth = specs[deck].get("truth")
        out = AB / deck
        for arm in ("base", "abd"):
            f07, f26 = mods[arm]
            fg = out / f"p5_{arm}.json"
            if not fg.exists():
                box = mods["_boxes"][arm]
                box.added = 0
                if arm == "base":
                    g = g0
                else:
                    g = f07.build_graph(ConceptDoc.from_dict(cd), Context.from_dict(specs[deck]["context"]),
                                        slide_doc=SlideDoc.from_dict(sd), llm=_Fixed(payload)).to_dict()
                rule = f26.build_claims(g, sd, llm="none").to_dict()
                llm = f26.build_claims(g, sd, llm=B.Replay(deck, f"claims:p5:{arm}", d / "claims_llm.json")).to_dict()
                B.write_json(fg, {"graph": g, "added": getattr(box, "added", 0), "rule": rule, "llm": llm})
            rec = B.read_json(fg)
            rows.setdefault(deck, {})[arm] = {
                "graph": graph_stats({"graph": rec["graph"], "added": rec["added"]}, sd, truth, f26),
                "rule": downstream(rec["rule"], rec["graph"], sd, truth),
                "llm": downstream(rec["llm"], rec["graph"], sd, truth), "group": specs[deck]["group"]}
    B.write_json(AB / "p5_rows.json", rows)
    return rows


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("run", "report", "p5"))
    ap.add_argument("--decks", default=",".join(DECKS))
    ap.add_argument("--samples", type=int, default=2)
    ap.add_argument("--budget", type=int, default=140)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--repo-root", default=str(B.DEFAULT_REPO))
    args = ap.parse_args(argv)
    B.BUDGET.limit = args.budget
    specs = B.load_decks(Path(args.repo_root), set())
    decks = [d for d in args.decks.split(",") if d in specs]
    mods = modules()
    mods["_boxes"] = {arm: _capture(mods[arm][0]) for arm in ARMS}
    if args.cmd == "p5":
        rows = run_p5(decks, specs, mods)
        for deck, r in rows.items():
            print(deck, {arm: (x["graph"]["nodes"], x["graph"]["added"], x["llm"]["claims"], x["llm"]["planted_claims"],
                               x["llm"]["probe_hit"], x["llm"]["plantable_tp"], x["llm"]["plantable"]) for arm, x in r.items()})
        B.note(f"LLM 호출 {B.BUDGET.used}")
        return 0
    if args.cmd == "run":
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(run_deck, d, specs[d], mods, args.samples, True): d for d in decks}
            for f, d in futs.items():
                try:
                    f.result()
                except Exception as e:  # noqa: BLE001 — 한 덱이 죽어도 나머지는 잰다
                    B.note(f"[{d}] 실패: {type(e).__name__}: {e}")
        B.note(f"LLM 호출 {B.BUDGET.used}")
    rows = collect(decks, specs, mods)
    summ = summarize(rows)
    B.write_json(AB / "rows.json", rows)
    B.write_json(AB / "summary.json", summ)
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
