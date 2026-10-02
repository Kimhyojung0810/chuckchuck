"""개념 그래프 구조 벤치 — 덱 11개, 새 길(종류 있는 F-06 → 뼈대 F-07)과 옛 길(f209e54, 진단 폴더의 그래프)을 같은 잣대로.
    python bench.py OUT [f06_runs=2] [f07_runs=2]     # 실 과금 (Solar). 파싱본은 진단 폴더 것을 쓴다
    python bench.py OUT --score                        # 이미 돌린 결과로 표만
결과: OUT/concepts_<덱>_<i>.json · OUT/graph_<덱>_<i>_<j>.json · OUT/bench.json · 표."""
import json, re, sys, statistics
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from chuckchuck import extract_concepts, build_graph
from chuckchuck.contracts import ConceptDoc, SlideDoc, ConceptGraph
from chuckchuck import _graph_items as GI
from chuckchuck.f06_concepts import grounded_share, is_claim_sentence, _is_figure, _META_NAME_RE, _GENERIC_NAMES

DIAG = Path('docs/review/2026-10-01_개념그래프_일반원인')
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
SCORE_ONLY = '--score' in sys.argv
args = [a for a in sys.argv[2:] if not a.startswith('--')]
R06 = int(args[0]) if args else 2
R07 = int(args[1]) if len(args) > 1 else 2
CTX = {"situation": "school_project", "duration_min": 10}
DECKS = sorted(p.stem[len('slidedoc_'):] for p in DIAG.glob('slidedoc_*.json'))
QUESTION = re.compile(r"[?？]|(?:는가|은가|일까|ㄹ까|을까|할까|나요|까요)\s*$|^왜\s|\s왜\s")
norm = lambda t: re.sub(r"[\s·:\-—]+", "", (t or "").lower())


def sd_of(name):
    return SlideDoc.from_dict(json.loads((DIAG / f'slidedoc_{name}.json').read_text()))


def items_of(cd):
    """F-06 이 뽑은 노드 후보 — 새 길은 주장 + 개념, 옛 길은 개념 이름 (키워드 제외)."""
    out = []
    for s in cd.slides:
        if s.title_kind == 'structural':
            continue
        out += [(s.slide_no, c) for c in s.claims]
        out += [(s.slide_no, str(c).partition(':')[0].strip()) for c in s.concepts]
    return [(n, x) for n, x in out if x]


def metrics(sd, cd, g):
    by = {n.id: n for n in g.nodes}
    kids = {}
    for n in g.nodes:
        if n.parent_id:
            kids.setdefault(n.parent_id, []).append(n)
    deck = " ".join(s.raw_text or "" for s in sd.slides)
    titles = {norm(s.title) for s in cd.slides if s.title} | {norm(s.title) for s in sd.slides if s.title}
    root = g.roots[0] if g.roots else None
    labels = [n.label for n in g.nodes]
    thesis_src = [x for n in g.nodes if n.kind == 'thesis' for x in n.summary.split(' / ')]
    its = items_of(cd)
    lost = [x for _, x in its if not GI.item_present(x, labels + thesis_src)]
    def anc(n):
        out, p = set(), n.parent_id
        while p and p in by and p not in out:
            out.add(p); p = by[p].parent_id
        return out
    cross = [e for e in g.relates_edges if e.from_id in by and e.to_id in by]
    return {
        "nodes": len(g.nodes), "roots": len(g.roots), "root": root.label if root else "",
        "root_question": bool(root and QUESTION.search(root.label)),
        "root_claim": bool(root and is_claim_sentence(root.label)),
        "depth": max((n.depth for n in g.nodes), default=0),
        "widest": max((len(v) for v in kids.values()), default=0),
        "figure_nodes": sum(1 for n in g.nodes if _is_figure(n.label) or _META_NAME_RE.match(n.label)),
        "title_generic_nodes": sum(1 for n in g.nodes if n.kind not in ("thesis", "claim") and (norm(n.label) in titles or n.label in _GENERIC_NAMES)),
        "label_grounded": round(sum(grounded_share(l, deck) >= 0.6 for l in labels) / max(1, len(labels)), 3),
        "f06_items": len(its), "f06_lost": len(lost), "lost_eg": lost[:4],
        "evidence": sum(len(n.evidence) for n in g.nodes),
        "relates": len(cross),
        "kinds": {k: sum(1 for n in g.nodes if n.kind == k) for k in ("thesis", "claim", "concept")},
    }


def run_new():
    def f06(job):
        name, i = job
        p = OUT / f'concepts_{name}_{i}.json'
        if not p.exists():
            p.write_text(json.dumps(extract_concepts(sd_of(name), CTX, llm='solar').to_dict(), ensure_ascii=False, indent=1))
        return name, i
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(f06, [(n, i) for n in DECKS for i in range(R06)]))
    def f07(job):
        name, i, j = job
        p = OUT / f'graph_{name}_{i}_{j}.json'
        if not p.exists():
            cd = ConceptDoc.from_dict(json.loads((OUT / f'concepts_{name}_{i}.json').read_text()))
            p.write_text(json.dumps(build_graph(cd, CTX, slide_doc=sd_of(name), llm='solar').to_dict(), ensure_ascii=False, indent=1))
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(f07, [(n, i, j) for n in DECKS for i in range(R06) for j in range(R07)]))


def score():
    res = {}
    for name in DECKS:
        sd = sd_of(name)
        old_cd = ConceptDoc.from_dict(json.loads((DIAG / f'concepts_{name}.json').read_text()))
        old = [metrics(sd, old_cd, ConceptGraph.from_dict(json.loads(p.read_text())))
               for p in sorted(DIAG.glob(f'graph_{name}_[0-9].json'))]
        new = []
        for p in sorted(OUT.glob(f'graph_{name}_*_*.json')):
            i = p.stem.split('_')[-2]
            cd = ConceptDoc.from_dict(json.loads((OUT / f'concepts_{name}_{i}.json').read_text()))
            new.append(metrics(sd, cd, ConceptGraph.from_dict(json.loads(p.read_text()))))
        res[name] = {"old": old, "new": new}
    (OUT / 'bench.json').write_text(json.dumps(res, ensure_ascii=False, indent=1))
    keys = ["nodes", "roots", "root_question", "root_claim", "depth", "widest", "figure_nodes", "title_generic_nodes",
            "label_grounded", "f06_lost", "relates"]
    print(f"{'덱':<16}{'':>4} " + " ".join(f"{k[:9]:>9}" for k in keys))
    agg = {"old": {k: [] for k in keys}, "new": {k: [] for k in keys}}
    for name, v in res.items():
        for side in ("old", "new"):
            rows = v[side]
            if not rows:
                continue
            cells = []
            for k in keys:
                vals = [float(r[k]) for r in rows]
                agg[side][k] += vals
                cells.append(f"{min(vals):g}-{max(vals):g}" if min(vals) != max(vals) else f"{vals[0]:g}")
            print(f"{name[:15]:<16}{side:>4} " + " ".join(f"{c:>9}" for c in cells))
    print("평균")
    for side in ("old", "new"):
        print(f"{'':<16}{side:>4} " + " ".join(f"{statistics.mean(agg[side][k]) if agg[side][k] else 0:>9.2f}" for k in keys))
    # 실행 간 흔들림 — 같은 덱 안 노드 수 범위·루트 이름 가짓수
    print("\n흔들림 (노드 수 max/min · 루트 이름 가짓수)")
    for name, v in res.items():
        line = []
        for side in ("old", "new"):
            rows = v[side]
            if rows:
                ns = [r['nodes'] for r in rows]
                line.append(f"{side} {max(ns)}/{min(ns)}={max(ns)/max(1,min(ns)):.2f} 루트{len({r['root'] for r in rows})}")
        print(f"  {name[:15]:<16} " + " | ".join(line))


if not SCORE_ONLY:
    run_new()
score()
