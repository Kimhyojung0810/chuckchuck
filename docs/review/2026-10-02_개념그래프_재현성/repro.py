"""같은 덱을 N번 처음부터(F-06 → F-07) 돌려 재현성·의미 정확성을 잰다. 실 과금 (Solar).
    python repro.py OUT N deck1,deck2,...        # 돌리고 재기 (이미 있는 회차는 건너뜀)
    python repro.py OUT --score                  # 재기만
재현성: 회차 쌍마다 노드(이름 열쇠)·위계 쌍(부모 이름, 자식 이름)·관계 쌍의 Jaccard 평균, 핵심 주장이 최빈 문장과 같은 비율.
의미 정확성: 노드 이름이 **자기 장** 원문에 근거한 비율(낱말 60%), 가지를 넘는 관계 중 양끝이 한 장에 같이 나오거나 원문 문장이 둘을 함께 부르는 비율."""
import json, re, sys, itertools, statistics as st
from collections import Counter
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from chuckchuck import extract_concepts, build_graph
from chuckchuck.contracts import SlideDoc, ConceptGraph
from chuckchuck import _graph_items as GI
from chuckchuck.f06_concepts import grounded_share
from chuckchuck import _claim_rules as R

DIAG = Path('docs/review/2026-10-01_개념그래프_일반원인')
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
CTX = {"situation": "school_project", "duration_min": 10}
key = lambda l: GI.label_keys(re.sub(r"\s*[(（][^)）]*[)）]", " ", l or "").strip() or l)[1]


def sd_of(name):
    return SlideDoc.from_dict(json.loads((DIAG / f'slidedoc_{name}.json').read_text()))


def run(name, n):
    def one(i):
        p = OUT / f'graph_{name}_{i}.json'
        if p.exists():
            return
        sd = sd_of(name)
        cd = extract_concepts(sd, CTX, llm='solar')
        (OUT / f'concepts_{name}_{i}.json').write_text(json.dumps(cd.to_dict(), ensure_ascii=False))
        p.write_text(json.dumps(build_graph(cd, CTX, slide_doc=sd, llm='solar').to_dict(), ensure_ascii=False))
    with ThreadPoolExecutor(5) as ex:
        list(ex.map(one, range(n)))


def jac(a, b):
    return len(a & b) / len(a | b) if a | b else 1.0


def skeleton(g):
    """뼈대 노드 — 핵심 주장 · 주장 · 하위 개념이나 주장을 거느린 개념 (잎 개념 빼고)."""
    parents = {n.parent_id for n in g.nodes if n.parent_id}
    return {key(n.label) for n in g.nodes if n.kind in ("thesis", "claim") or n.id in parents}


def stable_share(gs):
    """한 회차 노드 중 10회의 80% 이상에 나오는 노드의 몫 (회차 평균)."""
    cnt = Counter(k for g in gs for k in {key(n.label) for n in g.nodes})
    need = 0.8 * len(gs)
    return st.mean(sum(cnt[key(n.label)] >= need for n in g.nodes) / max(1, len(g.nodes)) for g in gs)


def facts(g):
    by = {n.id: n for n in g.nodes}
    nodes = {key(n.label) for n in g.nodes}
    parents = {(key(by[n.parent_id].label), key(n.label)) for n in g.nodes if n.parent_id in by}
    rel = {frozenset((key(by[e.from_id].label), key(by[e.to_id].label))) for e in g.relates_edges
           if e.from_id in by and e.to_id in by}
    return nodes, parents, rel


def semantic(g, sd):
    text = {s.slide_no: s.raw_text or "" for s in sd.slides}
    by = {n.id: n for n in g.nodes}
    own = [max((grounded_share(n.label, text.get(no, "")) for no in n.slide_nos), default=0) >= 0.6
           for n in g.nodes if n.kind != 'thesis']
    deck_lines = [l for s in sd.slides for l in GI.deck_lines(s.raw_text or "")]
    rel_ok = []
    for e in g.relates_edges:
        a, b = by.get(e.from_id), by.get(e.to_id)
        if not a or not b:
            continue
        same_slide = bool(set(a.slide_nos) & set(b.slide_nos))
        hit = lambda lab, l: grounded_share(lab, l) >= 0.6 or R.names_variable(lab, l)
        one_line = any(hit(a.label, l) and hit(b.label, l) for l in deck_lines)
        rel_ok.append(same_slide or one_line)
    # 위계 쌍 근거: 핵심 주장 밑 직속은 늘 받는다(발표 전체의 받침), 그 밖은 두 끝이 한 장에 같이 나오거나 한 줄이 둘을 부른다
    par_ok = []
    for n in g.nodes:
        p = by.get(n.parent_id)
        if p is None or p.parent_id is None:
            continue
        hit = lambda lab, l: grounded_share(lab, l) >= 0.6 or R.names_variable(lab, l)
        par_ok.append(bool(set(p.slide_nos) & set(n.slide_nos)) or any(hit(p.label, l) and hit(n.label, l) for l in deck_lines))
    th = next((n for n in g.nodes if n.kind == 'thesis'), g.roots[0] if g.roots else None)
    deck = " ".join(text.values())
    return {"node_own_slide_grounded": sum(own) / max(1, len(own)),
            "relates_grounded": (sum(rel_ok) / len(rel_ok)) if rel_ok else None, "relates": len(rel_ok),
            "parent_grounded": (sum(par_ok) / len(par_ok)) if par_ok else 1.0,
            "thesis_grounded": grounded_share(th.label, deck) if th else 0}


def score():
    decks = sorted({p.stem.split('_', 1)[1].rsplit('_', 1)[0] for p in OUT.glob('graph_*.json')})
    res = {}
    for name in decks:
        sd = sd_of(name)
        gs = [ConceptGraph.from_dict(json.loads(p.read_text())) for p in sorted(OUT.glob(f'graph_{name}_*.json'))]
        fs = [facts(g) for g in gs]
        pair = list(itertools.combinations(range(len(gs)), 2))
        theses = [key(g.roots[0].label) if g.roots else "" for g in gs]
        sem = [semantic(g, sd) for g in gs]
        rg = [s["relates_grounded"] for s in sem if s["relates_grounded"] is not None]
        res[name] = {
            "runs": len(gs),
            "node_jaccard": round(st.mean(jac(fs[i][0], fs[j][0]) for i, j in pair), 3) if pair else None,
            "parent_jaccard": round(st.mean(jac(fs[i][1], fs[j][1]) for i, j in pair), 3) if pair else None,
            "relates_jaccard": round(st.mean(jac(fs[i][2], fs[j][2]) for i, j in pair), 3) if pair else None,
            "thesis_mode_share": round(Counter(theses).most_common(1)[0][1] / len(gs), 2),
            "skeleton_jaccard": round(st.mean(jac(skeleton(gs[i]), skeleton(gs[j])) for i, j in pair), 3) if pair else None,
            "stable_node_share": round(stable_share(gs), 3),
            "nodes_min_max": [min(len(g.nodes) for g in gs), max(len(g.nodes) for g in gs)],
            "node_own_slide_grounded": round(st.mean(s["node_own_slide_grounded"] for s in sem), 3),
            "relates_grounded": round(st.mean(rg), 3) if rg else None,
            "relates_mean": round(st.mean(s["relates"] for s in sem), 1),
            "parent_grounded": round(st.mean(s["parent_grounded"] for s in sem), 3),
            "thesis_grounded": round(st.mean(s["thesis_grounded"] for s in sem), 3),
            "theses": Counter(g.roots[0].label for g in gs if g.roots).most_common(3),
        }
    (OUT / 'repro.json').write_text(json.dumps(res, ensure_ascii=False, indent=1))
    for name, r in res.items():
        print(name, {k: v for k, v in r.items() if k != 'theses'})
        print('   핵심 주장:', r['theses'])


if '--score' not in sys.argv:
    run_decks = sys.argv[3].split(',')
    for d in run_decks:
        run(d, int(sys.argv[2]))
score()
