"""논문 경로 진단 — 같은 그래프·같은 문헌으로 질문을 만들고 대체 문구·인용 수·가드별 탈락 이유를 센다."""
import json, re, sys, glob, os
from pathlib import Path
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from chuckchuck import triage_questions, build_questions, build_papers
from chuckchuck import f08_questions as f
from chuckchuck.contracts import ConceptGraph, SlideDoc, PaperDoc
S = Path(sys.argv[1]); runs = int(sys.argv[2]); tag = sys.argv[3]
graph = ConceptGraph.from_dict(json.load(open('var/data/stage_cache/graph-d3a0c081b9d34520a8e7.json')))
slide = SlideDoc.from_dict(json.load(open(S / 'sd_sleep.json')))
pp = S / 'papers_sleep.json'
if pp.exists():
    papers = PaperDoc.from_dict(json.load(open(pp)))
else:
    papers = build_papers(graph, slide, llm='solar'); pp.write_text(json.dumps(papers.to_dict(), ensure_ascii=False))
print('문헌', len(papers.refs), [r.cite_key for r in papers.refs])
FB = re.compile(r"— 설명해 주세요\.$|이 개념의 핵심과 자료에 넣은 근거를 설명해 주세요\.$")
why = []
orig_norm = f._normalize_questions
def spy(raw, marks, by_id, flow_of, by_no, transcript, papers_, *a, **k):
    ns = f._number_sources(by_no, transcript, papers_)
    for q in raw:
        t = str(q.get('question', '') or '')
        r = []
        if f._ungrounded_citation(t, papers_): r.append('목록밖인용')
        if f._claims_presenter_cited(t, papers_): r.append('인용전제')
        if ns and f.ungrounded_numbers(t, ns): r.append('자료밖숫자')
        if len(t) > f.QA_TEXT_MAX: r.append('길이')
        if r: why.append((q.get('node_id'), r, t[:90]))
    return orig_norm(raw, marks, by_id, flow_of, by_no, transcript, papers_, *a, **k)
f._normalize_questions = spy
ctx = {"situation": "school_project", "duration_min": 5}
tri = triage_questions(graph, None, None, ctx, llm='solar')
tot = fb = cited = 0; keys = []
for i in range(runs):
    for track in ('5', '10'):
        qd = build_questions(graph, tri, track=track, slidedoc=slide, papers=papers, llm='solar')
        for q in qd.questions:
            tot += 1; fb += bool(FB.search(q.question)); cited += bool(q.paper_ids); keys += q.paper_ids
        print(tag, i, track, [('📄' if q.paper_ids else '') + ('✗' if FB.search(q.question) else '') + q.label for q in qd.questions])
from collections import Counter
print(f'{tag}: 질문 {tot} · 대체 {fb} · 인용 {cited} · 논문 재사용 {sum(c-1 for c in Counter(keys).values() if c>1)}')
for w in why: print('  탈락', w)
