"""녹음 경로 끝까지 — 고정 ConceptDoc + 클로바 전사로 F-07 → F-11 → 흐름 → F-24 → F-08 (1·5·10분). cwd 저장소 코드로 돈다. 실 과금.
    python audio_path_eval.py OUT.json [runs]"""
import json, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from chuckchuck import align_speech, analyze_pace, build_flow_diff, build_graph, build_papers, build_questions, triage_questions
import inspect
from chuckchuck.contracts import ConceptDoc, SlideDoc, Transcript

H = Path(__file__).parent
doc = ConceptDoc.from_dict(json.load(open(H / 'concepts_0926_수면.json')))
slide = SlideDoc.from_dict(json.load(open(H / 'slidedoc_수면_세션.json')))
tr = Transcript.from_dict(json.load(open(H / 'transcript_수면_clova.json')))
ctx = {"situation": "school_project", "duration_min": 5}

def one(i):
    g = build_graph(doc, ctx, slide_doc=slide, llm='solar')
    al = align_speech(g, tr, ctx, llm='solar')
    fl = build_flow_diff(g, al)
    try:
        pp = build_papers(g, slide, llm='solar')
    except Exception as e:                      # 문헌은 없어도 질문은 나와야 한다
        pp = None
    # 화면과 같이 concept_doc 을 넣은 pace. 옛 코드(pace 인자 없음)에서는 안 넘긴다.
    pace = analyze_pace(tr, ctx, doc)
    kw = {"pace": pace} if "pace" in inspect.signature(triage_questions).parameters else {}
    tri = triage_questions(g, al, fl, ctx, transcript=tr, llm='solar', **kw)
    lab = {n.id: n for n in g.nodes}
    res = {"run": i, "roots": [n.label for n in g.roots],
           "verdicts": {it.node_id and lab[it.node_id].label if it.node_id in lab else it.node_id: it.verdict for it in al.items},
           "tracks": {}}
    for t in ("1", "5", "10"):
        qd = build_questions(g, tri, track=t, alignment=al, flow=fl, transcript=tr, slidedoc=slide, papers=pp, llm='solar', **kw)
        res["tracks"][t] = [{"label": q.label, "slides": q.slide_nos, "source": q.source,
                             "cited": bool(q.paper_ids), "q": q.question} for q in qd.questions]
    return res

runs = int(sys.argv[2]) if len(sys.argv) > 2 else 2
with ThreadPoolExecutor(runs) as ex:
    out = list(ex.map(one, range(runs)))
json.dump(out, open(sys.argv[1], 'w'), ensure_ascii=False, indent=1)
for r in out:
    print(f"== run {r['run']} 루트 {r['roots']}")
    miss = [k for k, v in r['verdicts'].items() if v in ('missing', 'contradiction')]
    print(f"   누락·모순 {len(miss)}/{len(r['verdicts'])}: {miss[:8]}")
    for t, qs in r['tracks'].items():
        print(f"   [{t}분]")
        for q in qs:
            print(f"     {'📄' if q['cited'] else '  '} {q['label']} S{q['slides']} ({q['source']}) — {q['q']}")
