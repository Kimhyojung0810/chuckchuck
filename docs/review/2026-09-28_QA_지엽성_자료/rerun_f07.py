import json, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from chuckchuck import f07_graph as g
from chuckchuck.contracts import ConceptDoc
doc = ConceptDoc.from_dict(json.load(open('var/data/stage_cache/concepts-a34d51be123a3ba8a6fa.json')))
orig = g._clamp_roots
def spy(nodes, edges, doc, sd):
    roots = sorted([n for n in nodes if n.parent_id is None], key=lambda n: -n.weight)
    print('PRE-CLAMP roots', len(roots), [(n.label, n.weight) for n in roots])
    lab = {n.id: n.label for n in nodes}
    print('PRE-CLAMP parent edges', [(lab.get(e.from_id), lab.get(e.to_id)) for e in edges if e.kind == 'parent'])
    return orig(nodes, edges, doc, sd)
g._clamp_roots = spy
graph = g.build_graph(doc, {"situation": "school_project", "duration_min": 5}, llm="solar")
by = {n.id: n for n in graph.nodes}
print('POST roots', [n.label for n in graph.nodes if n.parent_id is None])
for n in graph.nodes:
    if '질' in n.label: print('  질 node:', n.label, n.weight, 'parent=', by[n.parent_id].label if n.parent_id else None)
json.dump(graph.to_dict(), open(sys.argv[1], 'w'), ensure_ascii=False, indent=1)
