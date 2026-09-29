"""클로바노트 전사(.txt) + 슬라이드별 대본(.docx) → Transcript JSON (슬라이드별로 나눔). LLM 없음.
    python make_transcript.py TXT DOCX OUT.json
문장마다 대본의 어느 슬라이드와 낱말이 가장 겹치는지로 배정하고, 슬라이드 번호는 앞으로만 간다 (DP).
시각은 클로바 구간(MM:SS) 안에서 글자 수 비례로 나눈다 — 음성 정렬이 아니라 근사다."""
import json, re, sys, zipfile

txt, docx, out = sys.argv[1:4]
raw = open(txt, encoding="utf-8-sig").read()
blocks, cur = [], None
for line in raw.splitlines():
    m = re.fullmatch(r"(\d{2}):(\d{2})", line.strip())
    if m:
        cur = [int(m.group(1)) * 60 + int(m.group(2)), []]; blocks.append(cur); continue
    if cur is not None and line.strip() and "clovanote" not in line:
        cur[1].append(line.strip())
total = 8 * 60 + 15                       # 머리말 「8분 15초」
sents = []                                # (start, end, text)
for i, (t0, lines) in enumerate(blocks):
    t1 = blocks[i + 1][0] if i + 1 < len(blocks) else total
    ss = [s for l in lines for s in re.split(r"(?<=[.?!])\s+", l) if s.strip()]
    n = sum(len(s) for s in ss) or 1; t = t0
    for s in ss:
        d = (t1 - t0) * len(s) / n; sents.append((t, t + d, s)); t += d

xml = zipfile.ZipFile(docx).read("word/document.xml").decode()
paras = [''.join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)) for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S)]
script, no = {}, None
for p in paras:
    m = re.match(r"(\d+)번 슬라이드", p)
    if m: no = int(m.group(1)); script[no] = ""; continue
    if no and not p.startswith(("데모 실제 시간", "의도된 문제")): script[no] += " " + p
tok = lambda s: {w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", s)}
slides = sorted(script); stoks = {k: tok(v) for k, v in script.items()}
def score(s, k):
    a = tok(s); return len(a & stoks[k]) / (len(a) or 1)
# DP: 슬라이드 번호가 줄지 않게 하는 최대 점수 배정
N, K = len(sents), len(slides)
best = [[-1e9] * K for _ in range(N)]; back = [[0] * K for _ in range(N)]
for k in range(K): best[0][k] = score(sents[0][2], slides[k]) - (0 if k == 0 else 5)
for i in range(1, N):
    for k in range(K):
        j = max(range(k + 1), key=lambda j: best[i - 1][j])
        best[i][k] = best[i - 1][j] + score(sents[i][2], slides[k]); back[i][k] = j
k = max(range(K), key=lambda k: best[N - 1][k]); path = [k]
for i in range(N - 1, 0, -1): k = back[i][k]; path.append(k)
path.reverse()
by, words = [], []
for (t0, t1, s), k in zip(sents, path):
    ws = s.split(); step = (t1 - t0) / max(len(ws), 1)
    wl = [{"text": w, "start_sec": round(t0 + i * step, 2), "end_sec": round(t0 + (i + 1) * step, 2)} for i, w in enumerate(ws)]
    words += wl
    no = slides[k]
    if by and by[-1]["slide_no"] == no:
        by[-1]["end_sec"] = round(t1, 2); by[-1]["text"] += " " + s; by[-1]["words"] += wl
    else:
        by.append({"slide_no": no, "visit": 1, "start_sec": round(t0, 2), "end_sec": round(t1, 2), "text": s, "words": wl})
doc = {"full_text": " ".join(s for _, _, s in sents), "words": words, "by_slide": by,
       "provider": "clovanote-txt(근사 정렬)", "duration_sec": total}
json.dump(doc, open(out, "w"), ensure_ascii=False, indent=1)
for b in by:
    print(f"S{b['slide_no']} {b['start_sec']:6.1f}~{b['end_sec']:6.1f} ({b['end_sec']-b['start_sec']:5.1f}s) {b['text'][:50]}")
