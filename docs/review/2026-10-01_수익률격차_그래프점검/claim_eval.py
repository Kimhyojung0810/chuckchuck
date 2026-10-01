"""주장 노드 점검 — 덱마다 F-07 을 N번: 루트 수 · 루트 이름(주장 문장인가) · 노드 수 · 가지 간 연결. 실 과금 (Solar).
    python claim_eval.py [runs]"""
import json, re, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from chuckchuck import build_graph
from chuckchuck.contracts import ConceptDoc, SlideDoc
H = Path(__file__).parent; Q = Path('docs/review/2026-09-28_QA_지엽성_자료')
DECKS = {
    "수익률격차": (H / 'concepts.json', H / 'slidedoc_수익률격차.json'),
    "수면": (Q / 'concepts_0926_수면.json', Q / 'slidedoc_수면.json'),
    "소개": (Q / 'concepts_form2장.json', None),
}
QUESTION = re.compile(r"[?？]|(?:는가|은가|일까|ㄹ까|을까|할까|나요|까요)\s*$|^왜\s|\s왜\s")
runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
def one(name):
    cd, sd = DECKS[name]
    g = build_graph(ConceptDoc.from_dict(json.loads(cd.read_text())), {"situation": "school_project", "duration_min": 10},
                    slide_doc=SlideDoc.from_dict(json.loads(sd.read_text())) if sd else None, llm='solar')
    roots = [n.label for n in g.roots]
    return {"deck": name, "roots": roots, "question": any(QUESTION.search(r) for r in roots), "nodes": len(g.nodes),
            "relates": len(g.relates_edges), "thesis_summary": g.roots[0].summary[:80] if g.roots else ""}
jobs = [d for d in DECKS for _ in range(runs)]
with ThreadPoolExecutor(6) as ex:
    res = list(ex.map(one, jobs))
(H / 'claim_eval.json').write_text(json.dumps(res, ensure_ascii=False, indent=1))
for r in res:
    print(f"{r['deck']:<6} 루트 {len(r['roots'])} {'질문!' if r['question'] else '     '} 노드 {r['nodes']:>2} 연결 {r['relates']:>2} | {' / '.join(r['roots'])}")
