"""수익률격차 덱 — 1-1(PPT 그래프)·1-2(발표 대조) 점검 입력을 만든다. 실 과금 (Upstage 파싱 · STT 14분 · Solar).
파싱·그래프·대조는 chuckchuck 모듈을 직접, 받아쓰기는 브리지 /api/v1/transcribe 로 (F-04 장 구간 추정까지 화면과 같은 길).
    python build_inputs.py http://127.0.0.1:8813
결과(같은 폴더): slidedoc.json · transcript.json (둘 다 .gitignore — 덱 본문·음성 전문) · concepts.json · graph.json"""
import base64, glob, json, sys, unicodedata, urllib.request
from pathlib import Path
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from chuckchuck import parse_document, extract_concepts, build_graph
from chuckchuck.contracts import SlideDoc

H = Path(__file__).parent
base = sys.argv[1]
folder = [Path(p) for p in glob.glob('ppt/*') if unicodedata.normalize('NFC', Path(p).name) == '수익률격차'][0]
pptx = next(folder.glob('*.pptx')); m4a = next(folder.glob('*.m4a'))
ctx = {"situation": "school_project", "duration_min": 10}

sd_path = H / 'slidedoc_수익률격차.json'
if sd_path.exists():
    slide = SlideDoc.from_dict(json.loads(sd_path.read_text()))
else:
    slide = parse_document(str(pptx)); sd_path.write_text(json.dumps(slide.to_dict(), ensure_ascii=False, indent=1))
print('파싱', slide.total_slides, '장')

tr_path = H / 'transcript_수익률격차.json'
if not tr_path.exists():
    body = json.dumps({"audio_base64": base64.b64encode(m4a.read_bytes()).decode(), "ext": ".m4a",
                       "slidedoc": slide.to_dict()}).encode()
    req = urllib.request.Request(base + '/api/v1/transcribe', data=body, headers={"Content-Type": "application/json"})
    out = json.loads(urllib.request.urlopen(req, timeout=1500).read())
    tr_path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
tr = json.loads(tr_path.read_text())
print('전사', round(tr.get('duration_sec', 0)), '초 · 장 구간', len(tr.get('by_slide', [])), '· 추정', tr.get('marks_estimated'), tr.get('marks_confidence'))

concepts = extract_concepts(slide, ctx, llm='solar')
(H / 'concepts.json').write_text(json.dumps(concepts.to_dict(), ensure_ascii=False, indent=1))
graph = build_graph(concepts, ctx, slide_doc=slide, llm='solar')
(H / 'graph.json').write_text(json.dumps(graph.to_dict(), ensure_ascii=False, indent=1))
print('그래프 노드', len(graph.nodes), '루트', [n.label for n in graph.roots], 'relates', len(graph.relates_edges))
