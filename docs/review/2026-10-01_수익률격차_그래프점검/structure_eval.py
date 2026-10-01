"""1-1 구조 점검 — 덱의 F-07 을 N번: 노드 수 · 깊이 · 장 제목 노드 · 핵심 개념 커버 · 세부 자리. 실 과금 (Solar).
    python structure_eval.py [runs] [deck=수익률격차|수면]
세부 자리: 같은 부모 밑 형제 A·B 에서 A 의 장이 B 의 장에 다 들어가고(A ⊂ B) B 가 그 장의 주인(장 수가 더 적은 쪽이 아닌)이면,
A 는 B 밑이어야 할 세부가 형제로 올라온 것으로 센다 (예: 회전율[6,11] 이 과잉 매매[5,6,14] 와 형제)."""
import json, re, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from chuckchuck import build_graph
from chuckchuck._match import label_tokens
from chuckchuck.contracts import ConceptDoc, SlideDoc
H = Path(__file__).parent; Q = Path('docs/review/2026-09-28_QA_지엽성_자료')
DECKS = {"수익률격차": (H / 'concepts.json', H / 'slidedoc_수익률격차.json'),
         "수면": (Q / 'concepts_0926_수면.json', Q / 'slidedoc_수면.json')}
runs = int(sys.argv[1]) if len(sys.argv) > 1 else 6
deck = sys.argv[2] if len(sys.argv) > 2 else "수익률격차"
cdp, sdp = DECKS[deck]
cd = ConceptDoc.from_dict(json.loads(cdp.read_text())); sd = SlideDoc.from_dict(json.loads(sdp.read_text()))
norm = lambda t: re.sub(r"[\s·:\-—]+", "", (t or "").lower())
titles = {norm(s.title) for s in cd.slides if s.title}
core_names = [c.split(":")[0].strip() for s in cd.slides if s.importance == "core" for c in s.concepts]

def covered(name, labels):
    want = set(w for w in label_tokens(name) if len(w) >= 2)
    if not want: return True
    return any(len(want & set(label_tokens(l))) >= max(1, 0.6 * len(want)) for l in labels)

def one(_):
    g = build_graph(cd, {"situation": "school_project", "duration_min": 10}, slide_doc=sd, llm='solar')
    by = {n.id: n for n in g.nodes}; labels = [n.label for n in g.nodes]
    has_kids = {n.parent_id for n in g.nodes if n.parent_id}
    # 장 제목 그대로인 노드 중 자식 없이 끝난 것 (자식을 거느리면 묶음으로 제 역할을 한다)
    title_nodes = [n.label for n in g.nodes if n.parent_id and norm(n.label) in titles and n.id not in has_kids]
    misplaced = []
    kids = {}
    for n in g.nodes:
        if n.parent_id: kids.setdefault(n.parent_id, []).append(n)
    for sibs in kids.values():
        for a in sibs:
            for b in sibs:
                broad = len(b.slide_nos) > max(3, cd.total_slides // 3)     # 덱 전체에 걸친 배경 노드와는 견주지 않는다
                if a is not b and not broad and a.slide_nos and set(a.slide_nos) < set(b.slide_nos):
                    misplaced.append(f"{a.label}⊂{b.label}"); break
    cov = sum(covered(c, labels) for c in core_names) / max(1, len(core_names))
    return {"nodes": len(g.nodes), "depth": max(n.depth for n in g.nodes), "roots": [n.label for n in g.roots],
            "title_nodes": title_nodes, "misplaced": misplaced, "core_cover": round(cov, 2),
            "widest": max((len(v) for v in kids.values()), default=0)}
with ThreadPoolExecutor(runs) as ex:
    res = list(ex.map(one, range(runs)))
(H / f'structure_eval_{deck}.json').write_text(json.dumps(res, ensure_ascii=False, indent=1))
print(f"{deck} · 핵심 개념 {len(core_names)}개")
for r in res:
    print(f" 노드 {r['nodes']:>2} 깊이 {r['depth']} 최대가지 {r['widest']:>2} 핵심커버 {r['core_cover']:.2f} 빈장제목노드 {len(r['title_nodes'])} 세부자리틀림 {len(r['misplaced'])} | {r['title_nodes']} {r['misplaced'][:4]}")
