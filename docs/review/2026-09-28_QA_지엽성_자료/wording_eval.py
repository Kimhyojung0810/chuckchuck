"""F-08 질문 문장 점검 — 고정 그래프(graph_fixed_c)로 triage+질문을 N번 만들고 3인칭·순서 질문을 센다. 실 과금 (회당 Solar 2~3콜).
    python wording_eval.py [runs]"""
import json, re, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from chuckchuck import triage_questions, build_questions
from chuckchuck.contracts import ConceptGraph, SlideDoc

HERE = Path(__file__).parent
graph = ConceptGraph.from_dict(json.load(open(HERE / 'graph_fixed_c.json')))
slide = SlideDoc.from_dict(json.load(open(HERE / 'slidedoc_수면.json')))
ctx = {"situation": "school_project", "duration_min": 5}
THIRD = re.compile(r"발표자(?:는|가|께서)\s")
ORDER = re.compile(r"(먼저|나중에|앞서|순서).{0,20}(언급|설명|말|다룬|배치|제시)")

def one(_):
    tri = triage_questions(graph, None, None, ctx, llm='solar')
    qd = build_questions(graph, tri, track='10', slidedoc=slide, llm='solar')
    return [q.question for q in qd.questions]

runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
with ThreadPoolExecutor(runs) as ex:
    allq = [q for qs in ex.map(one, range(runs)) for q in qs]
third = [q for q in allq if THIRD.search(q)]
order = [q for q in allq if ORDER.search(q)]
print(f"질문 {len(allq)}개 · 3인칭 {len(third)} · 순서 질문 {len(order)}")
for q in third + order:
    print("  -", q)
