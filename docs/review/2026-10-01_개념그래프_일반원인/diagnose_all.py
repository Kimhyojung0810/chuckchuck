"""여러 PPT 로 개념 그래프 실패의 일반 원인 찾기. 덱마다 F-06 1번 · F-07 N번 → 단계별 진단. 실 과금 (Upstage 파싱 · Solar).
    python diagnose_all.py [runs]
파싱본·개념 목록은 이 폴더에 얼린다 (slidedoc_* 는 .gitignore). 결과: diagnose.json · 화면 표."""
import json, re, sys, unicodedata
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from chuckchuck import parse_document, extract_concepts, build_graph
from chuckchuck._match import label_tokens
from chuckchuck.contracts import ConceptDoc, SlideDoc

H = Path(__file__).parent
nfc = lambda s: unicodedata.normalize('NFC', s)
SEEN = set(); DECKS = {}
for d in sorted(Path('ppt').iterdir()):
    if not d.is_dir(): continue
    f = next((p for p in sorted(d.iterdir()) if p.suffix.lower() in ('.pptx', '.pdf')), None)
    if f is None or nfc(f.name) in SEEN: continue          # 부스 A·B 버전은 같은 PPTX — 한 번만
    SEEN.add(nfc(f.name)); DECKS[nfc(d.name).rstrip('AB') if nfc(d.name)[-1] in 'AB' and not nfc(d.name).startswith('_') else nfc(d.name)] = f
KNOWN = {"수면발표": Path('docs/review/2026-09-28_QA_지엽성_자료/slidedoc_수면.json'),
         "수익률격차": Path('docs/review/2026-10-01_수익률격차_그래프점검/slidedoc_수익률격차.json'),
         "focus_notification": Path('fixtures/raw/focus_notification_demo_designed.slidedoc.json')}
CTX = {"situation": "school_project", "duration_min": 10}
QUESTION = re.compile(r"[?？]|(?:는가|은가|일까|ㄹ까|을까|할까|나요|까요)\s*$|^왜\s|\s왜\s")
norm = lambda t: re.sub(r"[\s·:\-—]+", "", (t or "").lower())
runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3

def prepare(name):
    sd_path = H / f'slidedoc_{name}.json'; cd_path = H / f'concepts_{name}.json'
    if not sd_path.exists():
        src = KNOWN.get(name)
        sd = SlideDoc.from_dict(json.loads(src.read_text())) if src and src.exists() else parse_document(str(DECKS[name]))
        sd_path.write_text(json.dumps(sd.to_dict(), ensure_ascii=False))
    sd = SlideDoc.from_dict(json.loads(sd_path.read_text()))
    if not cd_path.exists():
        cd_path.write_text(json.dumps(extract_concepts(sd, CTX, llm='solar').to_dict(), ensure_ascii=False, indent=1))
    return name, sd, ConceptDoc.from_dict(json.loads(cd_path.read_text()))

def f06_diag(cd):
    items = [(s, c) for s in cd.slides for c in s.concepts]
    names = [c.split(':')[0].strip() for _, c in items]
    titles = {norm(s.title) for s in cd.slides if s.title}
    return {"slides": cd.total_slides, "items": len(items),
            "question": sum(bool(QUESTION.search(n)) for n in names),
            "title_copy": sum(norm(n) in titles for n in names),
            "numeric": sum(bool(re.search(r"\d", n)) for n in names),
            "no_desc": sum(':' not in c for _, c in items),
            "long_name": sum(len(n) > 25 for n in names)}

def f07_diag(sd, cd, g):
    by = {n.id: n for n in g.nodes}
    kids = {}
    for n in g.nodes:
        if n.parent_id: kids.setdefault(n.parent_id, []).append(n)
    titles = {norm(s.title) for s in cd.slides if s.title}
    def anc(n):
        out, p = set(), n.parent_id
        while p and p in by and p not in out: out.add(p); p = by[p].parent_id
        return out
    misplaced = 0
    for sibs in kids.values():
        for a in sibs:
            if any(a is not b and len(b.slide_nos) <= max(3, cd.total_slides // 3) and a.slide_nos
                   and set(a.slide_nos) < set(b.slide_nos) for b in sibs): misplaced += 1
    body = [s.slide_no for s in cd.slides if s.importance == 'core']
    touched = {no for n in g.nodes for no in n.slide_nos}
    root = g.roots[0].label if g.roots else ''
    return {"nodes": len(g.nodes), "roots": len(g.roots), "root": root,
            "root_question": bool(QUESTION.search(root)), "root_short": len(label_tokens(root)) <= 2,
            "depth": max((n.depth for n in g.nodes), default=0),
            "widest": max((len(v) for v in kids.values()), default=0),
            "title_childless": sum(1 for n in g.nodes if n.parent_id and norm(n.label) in titles and n.id not in kids),
            "misplaced": misplaced,
            "core_slide_cover": round(len(set(body) & touched) / max(1, len(body)), 2),
            "cross": sum(1 for e in g.relates_edges if e.from_id in by and e.to_id in by
                         and e.from_id not in anc(by[e.to_id]) and e.to_id not in anc(by[e.from_id]))}

import time
def prepare_retry(name):
    for wait in (0, 20, 60, 120):
        time.sleep(wait)
        try:
            return prepare(name)
        except Exception as e:                       # Upstage 429 — 한 덱씩, 기다렸다 다시
            if '429' not in str(e) or wait == 120: raise
prepped = [prepare_retry(n) for n in DECKS]      # 파싱은 한 번에 하나 (Upstage 요청 한도)
jobs = [(name, sd, cd) for name, sd, cd in prepped for _ in range(runs)]
def run(j):
    name, sd, cd = j
    g = build_graph(cd, CTX, slide_doc=sd, llm='solar')
    return name, g.to_dict(), f07_diag(sd, cd, g)
with ThreadPoolExecutor(9) as ex:
    graphs = list(ex.map(run, jobs))
out = {name: {"f06": f06_diag(cd), "f07": [d for n, _, d in graphs if n == name]} for name, sd, cd in prepped}
(H / 'diagnose.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
for i, (n, g, _) in enumerate(graphs):
    (H / f'graph_{n}_{i % runs}.json').write_text(json.dumps(g, ensure_ascii=False))
print(f"{'덱':<20} 장 F06항목 질문 제목복사 숫자 설명없음 | 노드 루트 루트질문/짧음 깊이 최대가지 빈제목 세부틀림 본문덮음 가지간")
for name, v in out.items():
    f = v['f06']
    for d in v['f07']:
        print(f"{name[:18]:<20} {f['slides']:>2} {f['items']:>4} {f['question']:>3} {f['title_copy']:>4} {f['numeric']:>3} {f['no_desc']:>4}   | "
              f"{d['nodes']:>3} {d['roots']:>2} {'Q' if d['root_question'] else '-'}{'S' if d['root_short'] else '-'} {d['depth']:>3} {d['widest']:>5} {d['title_childless']:>4} {d['misplaced']:>5} {d['core_slide_cover']:>6} {d['cross']:>4} | {d['root'][:28]}")
