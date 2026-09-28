"""9/28 위계 수정 검증 — 수면발표 PPTX 를 실제 파싱해 slide_doc 을 넣고(버그 조건) F-07 → F-08 을 돈다. 실 과금."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from chuckchuck import parse_document, build_graph, triage_questions, build_questions
from chuckchuck.contracts import ConceptDoc, SlideDoc

OUT = Path(__file__).parent
sd_path = OUT / 'slidedoc_수면.json'
if sd_path.exists():
    slide_doc = SlideDoc.from_dict(json.loads(sd_path.read_text()))
else:
    slide_doc = parse_document(str(next(p for p in Path('ppt').glob('*/*.pptx'))))
    sd_path.write_text(json.dumps(slide_doc.to_dict(), ensure_ascii=False, indent=1))
doc = ConceptDoc.from_dict(json.load(open(OUT / 'concepts_0926_수면.json')))
ctx = {"situation": "school_project", "duration_min": 5}
tag = sys.argv[1] if len(sys.argv) > 1 else 'run'

g = build_graph(doc, ctx, slide_doc=slide_doc, llm='solar')
(OUT / f'graph_fixed_{tag}.json').write_text(json.dumps(g.to_dict(), ensure_ascii=False, indent=1))
lab = {n.id: n.label for n in g.nodes}
print(f'[{tag}] roots:', [n.label for n in g.nodes if n.parent_id is None])
tri = triage_questions(g, None, None, ctx, llm='solar')
print(f'[{tag}] triage top10:', [(lab.get(m.node_id, m.node_id), m.severity) for m in tri.marks[:10]])
for track in ('5', '10'):
    qd = build_questions(g, tri, track=track, slidedoc=slide_doc, llm='solar')
    print(f'[{tag}] track {track}:')
    for q in qd.questions:
        print(f'    - {q.label} | {q.question}')
