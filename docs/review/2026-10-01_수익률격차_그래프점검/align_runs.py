"""1-2 — 같은 1-1 그래프·전사로 F-11 대조를 N번. 개념마다 판정이 흔들리는지 본다. 실 과금 (Solar).
    python align_runs.py [runs]   → align_runs.json"""
import json, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from chuckchuck import align_speech
from chuckchuck.contracts import ConceptGraph, SlideDoc, Transcript
H = Path(__file__).parent
g = ConceptGraph.from_dict(json.loads((H / 'graph.json').read_text()))
sd = SlideDoc.from_dict(json.loads((H / 'slidedoc_수익률격차.json').read_text()))
tr = Transcript.from_dict(json.loads((H / 'transcript_수익률격차.json').read_text()))
ctx = {"situation": "school_project", "duration_min": 10}
runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
with ThreadPoolExecutor(runs) as ex:
    docs = list(ex.map(lambda _: align_speech(g, tr, ctx, llm='solar', slide_doc=sd), range(runs)))
out = [d.to_dict() for d in docs]
(H / 'align_runs.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
lab = {n.id: n for n in g.nodes}
print('run별 요약:', [(d.summary.coverage if d.summary else None, {v: sum(i.verdict == v for i in d.items) for v in ('aligned', 'missing', 'contradiction', 'justified_skip')}) for d in docs])
print('발표에만 나온 개념:', [[e.label for e in d.extra_concepts] for d in docs])
print()
for n in g.nodes:
    vs = [next((i for i in d.items if i.node_id == n.id), None) for d in docs]
    marks = ' '.join((i.verdict[:4] if i else '----') for i in vs)
    flag = '' if len({i.verdict for i in vs if i}) <= 1 else '  ← 흔들림'
    print(f"S{','.join(map(str, n.slide_nos)):<8} {n.label[:22]:<22} w={n.weight:.2f} | {marks}{flag}")
