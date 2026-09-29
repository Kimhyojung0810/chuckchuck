"""개념 그래프 JSON → PNG (네트워크 배치). 위계·relates 를 가리지 않고 모든 선이 같은 힘으로 당긴다. LLM 없음.
    python render_network_png.py GRAPH.json OUT.png "제목"
render_graph_png.py 는 위계로 뼈대를 잡은 트리 뷰, 이건 그래프 뷰다 — 여러 개념과 얽힌 허브가 가운데로 모인다.
Fruchterman–Reingold, 시드 고정이라 같은 입력이면 같은 그림이다. 헤드리스 크로미움 필요 (LD_LIBRARY_PATH 는 labs 와 같다)."""
import html, json, math, random, sys
from playwright.sync_api import sync_playwright

src, out, title = sys.argv[1], sys.argv[2], sys.argv[3]
g = json.load(open(src))
nodes = [n for n in g["nodes"]]
idx = {n["id"]: i for i, n in enumerate(nodes)}
raw = [(idx[e["from"]], idx[e["to"]], e["kind"]) for e in g["edges"] if e["from"] in idx and e["to"] in idx]
# relates 가 위계와 같은 쌍을 다시 적은 것은 새 정보가 아니다 — 그리면 실선 밑에 숨어 개수만 틀리게 보인다.
parent_pairs = {frozenset((a, b)) for a, b, k in raw if k == "parent"}
edges = [(a, b, k) for a, b, k in raw if k == "parent" or frozenset((a, b)) not in parent_pairs]
dup_rel = len(raw) - len(edges)
N = len(nodes)
deg = [0] * N
for a, b, _ in edges:
    deg[a] += 1; deg[b] += 1
parent = {e["to"]: e["from"] for e in g["edges"] if e["kind"] == "parent"}
def depth(i):
    d, cur = 0, i
    while cur in parent and d < 10: cur = parent[cur]; d += 1
    return d

# --- Fruchterman–Reingold ---
Wd, Ht = 1400.0, 1000.0
rnd = random.Random(7)
pos = [[rnd.uniform(-Wd / 4, Wd / 4), rnd.uniform(-Ht / 4, Ht / 4)] for _ in range(N)]
k = 0.9 * math.sqrt(Wd * Ht / max(N, 1))
temp = Wd / 8
for it in range(600):
    disp = [[0.0, 0.0] for _ in range(N)]
    for i in range(N):
        for j in range(i + 1, N):
            dx, dy = pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]
            d = math.hypot(dx, dy) or 0.01
            f = k * k / d
            disp[i][0] += dx / d * f; disp[i][1] += dy / d * f
            disp[j][0] -= dx / d * f; disp[j][1] -= dy / d * f
    for a, b, _ in edges:
        dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
        d = math.hypot(dx, dy) or 0.01
        f = d * d / k
        disp[a][0] -= dx / d * f; disp[a][1] -= dy / d * f
        disp[b][0] += dx / d * f; disp[b][1] += dy / d * f
    for i in range(N):                                   # 가운데로 살짝 — 떨어진 조각이 날아가지 않게
        disp[i][0] -= pos[i][0] * 0.02 * k / 10; disp[i][1] -= pos[i][1] * 0.02 * k / 10
        d = math.hypot(*disp[i]) or 0.01
        step = min(d, temp)
        pos[i][0] += disp[i][0] / d * step; pos[i][1] += disp[i][1] / d * step
    temp = max(1.0, temp * 0.992)

# --- 그리기 ---
PAD, TOP, LEGEND_H = 90, 120, 40
xs = [p[0] for p in pos]; ys = [p[1] for p in pos]
sx = (Wd - 2 * PAD) / ((max(xs) - min(xs)) or 1); sy = (Ht - 2 * PAD) / ((max(ys) - min(ys)) or 1)
s = min(sx, sy)
X = lambda i: PAD + (pos[i][0] - min(xs)) * s
Y = lambda i: TOP + (pos[i][1] - min(ys)) * s
width = int(Wd); height = int(TOP + (max(ys) - min(ys)) * s + PAD + LEGEND_H)
top_w = max(n["weight"] for n in nodes) or 1
FILL = {0: "#155C46", 1: "#3FB98A", 2: "#B9E6D2"}
parts = []
for a, b, kind in edges:
    cls = "pe" if kind == "parent" else "re"
    parts.append(f'<line x1="{X(a):.1f}" y1="{Y(a):.1f}" x2="{X(b):.1f}" y2="{Y(b):.1f}" class="{cls}"/>')
for i, n in enumerate(nodes):
    r = 9 + 17 * (n["weight"] / top_w)
    d = min(depth(n["id"]), 2)
    parts.append(f'<circle cx="{X(i):.1f}" cy="{Y(i):.1f}" r="{r:.1f}" fill="{FILL[d]}" class="nd"/>')
for i, n in enumerate(nodes):
    r = 9 + 17 * (n["weight"] / top_w)
    lab = html.escape(n["label"] if len(n["label"]) <= 16 else n["label"][:15] + "…")
    fw = 700 if depth(n["id"]) == 0 else 500
    parts.append(f'<text x="{X(i):.1f}" y="{Y(i) + r + 17:.1f}" text-anchor="middle" class="lab" style="font-weight:{fw}">{lab}'
                 f'<tspan class="dg"> {deg[i]}</tspan></text>')
n_par = sum(k == "parent" for *_, k in edges); n_rel = len(edges) - n_par
hubs = sorted(range(N), key=lambda i: -deg[i])[:3]
hub_txt = " · ".join(f"{nodes[i]['label']}({deg[i]})" for i in hubs)
ly = height - 28
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
text{{font-family:"Noto Sans KR","NanumGothic",sans-serif}}
.t{{font-size:24px;font-weight:700;fill:#17261F}} .m{{font-size:15px;fill:#4D5E56}}
.pe{{stroke:#6F7F77;stroke-width:1.8}} .re{{stroke:#8A6FD6;stroke-width:1.4;stroke-dasharray:5 4;opacity:.7}}
.nd{{stroke:#FFFDF7;stroke-width:2.5}}
.lab{{font-size:14px;fill:#17261F;paint-order:stroke;stroke:#FFFDF7;stroke-width:4px;stroke-linejoin:round}}
.dg{{font-size:11px;fill:#7A8A82;font-family:monospace}}
</style>
<rect width="100%" height="100%" fill="#FFFDF7"/>
<text x="40" y="44" class="t">{html.escape(title)}</text>
<text x="40" y="72" class="m">노드 {N} · 위계(회색 실선) {n_par} · 가지를 넘는 연결(보라 점선) {n_rel} (위계와 같은 쌍을 다시 적은 {dup_rel}개는 뺌) · 연결 많은 개념: {html.escape(hub_txt)}</text>
<text x="40" y="94" class="m">원 크기 = weight(자료 비중) · 이름 옆 숫자 = 연결 수 · 배치는 선의 힘으로만 정했다 (위계로 줄 세우지 않음)</text>
{"".join(parts)}
<g transform="translate(40,{ly})" class="m">
  <circle cx="8" cy="-5" r="8" fill="{FILL[0]}"/><text x="22" y="0">최상위</text>
  <circle cx="98" cy="-5" r="8" fill="{FILL[1]}"/><text x="112" y="0">둘째 층</text>
  <circle cx="198" cy="-5" r="8" fill="{FILL[2]}"/><text x="212" y="0">셋째 층</text>
  <line x1="300" y1="-5" x2="336" y2="-5" class="pe"/><text x="344" y="0">위계</text>
  <line x1="400" y1="-5" x2="436" y2="-5" class="re"/><text x="444" y="0">그 밖의 연결</text>
</g>
</svg>'''
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": width, "height": height}, device_scale_factor=2)
    pg.set_content(f"<html><body style='margin:0'>{svg}</body></html>")
    pg.screenshot(path=out, full_page=True)
    b.close()
print(out, width, "x", height, "허브", hub_txt)
