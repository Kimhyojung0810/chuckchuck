"""F-07 이 발표 주제를 최상위에 세우는지 잰다. 실행한 저장소(cwd)의 코드로 돈다. 실 과금 (덱당 runs 콜).
    python thesis_eval.py OUT.json [runs]"""
import json, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from chuckchuck import f07_graph as g
from chuckchuck.contracts import ConceptDoc, SlideDoc

HERE = Path(__file__).parent
DECKS = {
    # 이름: (concept_doc, slide_doc, 주제 판정, 요소 판정)
    "수면": ("concepts_0926_수면.json", "slidedoc_수면.json",
             lambda l: l.replace(" ", "").startswith(("수면의질", "수면질")),
             lambda l: any(k in l for k in ("연속성", "규칙성", "시간 부족", "충분한 시간", "규칙적인 리듬"))),
    "form": ("concepts_form2장.json", None,
             lambda l: any(k in l for k in ("척척발표", "코칭 서비스", "발표 코칭", "학습 트레이너")),
             lambda l: any(k in l for k in ("B2B", "B2C", "SaaS", "수익"))),
}
runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
pre = {}
orig = g._clamp_roots
def spy(nodes, edges, doc, sd, *rest):
    pre[doc.file_name + str(id(nodes))] = sum(1 for n in nodes if n.parent_id is None)
    nodes[0].__dict__['_pre_roots'] = pre[doc.file_name + str(id(nodes))]
    return orig(nodes, edges, doc, sd, *rest)
g._clamp_roots = spy

def one(name):
    cd, sd, is_thesis, is_part = DECKS[name]
    doc = ConceptDoc.from_dict(json.load(open(HERE / cd)))
    slide = SlideDoc.from_dict(json.load(open(HERE / sd))) if sd else None
    graph = g.build_graph(doc, {"situation": "school_project", "duration_min": 5}, slide_doc=slide, llm="solar")
    by = {n.id: n for n in graph.nodes}
    def ancestors(n):
        out, p = [], n.parent_id
        while p and p in by:
            out.append(by[p]); p = by[p].parent_id
        return out
    roots = [n.label for n in graph.nodes if n.parent_id is None]
    parts = [n for n in graph.nodes if is_part(n.label) and not is_thesis(n.label)]
    under = sum(1 for n in parts if any(is_thesis(a.label) for a in ancestors(n)))
    return {
        "deck": name, "pre_roots": graph.nodes[0].__dict__.get('_pre_roots'),
        "roots": roots, "thesis_is_root": any(is_thesis(l) for l in roots),
        "parts_under_thesis": f"{under}/{len(parts)}", "nodes": len(graph.nodes),
    }

jobs = [n for n in DECKS for _ in range(runs)]
with ThreadPoolExecutor(6) as ex:
    res = list(ex.map(one, jobs))
for r in res:
    print(json.dumps(r, ensure_ascii=False))
json.dump(res, open(sys.argv[1], 'w'), ensure_ascii=False, indent=1)
