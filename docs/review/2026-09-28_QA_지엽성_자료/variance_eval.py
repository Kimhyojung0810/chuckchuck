"""F-07 노드 수 흔들림 — F-06 결과를 고정하고 F-07 만 N번. 실행한 저장소(cwd) 코드로 돈다. 실 과금.
    python variance_eval.py [runs]   (첫 실행이 알림 덱 F-06 을 한 번 만들어 concepts_알림12장.json 에 얼린다)"""
import json, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '.'); sys.path.insert(0, 'examples')
from dotenv import load_dotenv; load_dotenv('.env')
import graph_eval as ge
from chuckchuck import extract_concepts, build_graph
from chuckchuck.contracts import ConceptDoc, Context, SlideDoc

HERE = Path(__file__).parent
art = ge.load_artifacts(ge.RUN_FIXTURE)
slide = SlideDoc.from_dict(art["slide_doc"])
ctx = Context.from_dict(art.get("context") or {})
frozen = HERE / "concepts_알림12장.json"
if not frozen.exists():
    frozen.write_text(json.dumps(extract_concepts(slide, ctx, llm="solar").to_dict(), ensure_ascii=False, indent=1))
doc = ConceptDoc.from_dict(json.loads(frozen.read_text()))
lines = sum(len(s.concepts[:6]) + len(s.keywords) for s in doc.slides)

def one(_):
    g = build_graph(doc, ctx, slide_doc=slide, llm="solar")
    m = ge.graph_metrics(g, slide)
    return m["nodes"], m["dup_label_pairs"], m["summary_grounding"], m["depth_max"], len(g.roots)

runs = int(sys.argv[1]) if len(sys.argv) > 1 else 5
with ThreadPoolExecutor(runs) as ex:
    res = list(ex.map(one, range(runs)))
print(f"개념 목록 줄 {lines} · (노드, 중복쌍, 요약근거, 깊이, 루트) ×{runs}")
for r in res: print("  ", r)
ns = [r[0] for r in res]
print(f"노드 평균 {sum(ns)/len(ns):.1f} · 범위 {min(ns)}~{max(ns)}")
