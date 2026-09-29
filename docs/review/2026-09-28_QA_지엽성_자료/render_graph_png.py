"""개념 그래프 JSON → PNG (좌→우 나무 배치). 부모-자식 = 실선, relates = 점선. LLM 없음.
    python render_graph_png.py GRAPH.json OUT.png "제목"
헤드리스 크로미움이 필요하다 (labs 와 같이 LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu)."""
import html, json, sys
from playwright.sync_api import sync_playwright

src, out, title = sys.argv[1], sys.argv[2], sys.argv[3]
g = json.load(open(src))
nodes = {n["id"]: n for n in g["nodes"]}
kids: dict[str, list[str]] = {}
parent = {}
for e in g["edges"]:
    if e["kind"] == "parent":
        kids.setdefault(e["from"], []).append(e["to"]); parent[e["to"]] = e["from"]
roots = [i for i in nodes if i not in parent]
roots.sort(key=lambda i: -nodes[i]["weight"])
for k in kids.values():
    k.sort(key=lambda i: (min(nodes[i]["slide_nos"] or [99]), -nodes[i]["weight"]))

COL, ROW, W, H, PAD, TOP = 300, 46, 250, 34, 30, 110
pos, row = {}, [0]
def place(i, d):
    ch = kids.get(i, [])
    for c in ch: place(c, d + 1)
    if ch:
        y = (pos[ch[0]][1] + pos[ch[-1]][1]) / 2
    else:
        y = row[0] * ROW; row[0] += 1
    pos[i] = (d * COL, y)
for r in roots:
    place(r, 0); row[0] += 0.6
maxd = max(x for x, _ in pos.values()) // COL
width = PAD * 2 + maxd * COL + W + 160
height = TOP + row[0] * ROW + PAD
X = lambda i: PAD + pos[i][0]
Y = lambda i: TOP + pos[i][1]

top_w = max(n["weight"] for n in g["nodes"])
parts = []
for e in g["edges"]:
    a, b = e["from"], e["to"]
    if a not in pos or b not in pos: continue
    if e["kind"] == "parent":
        x1, y1, x2, y2 = X(a) + W, Y(a) + H / 2, X(b), Y(b) + H / 2
        mx = (x1 + x2) / 2
        parts.append(f'<path d="M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}" class="pe"/>')
for e in g["edges"]:
    a, b = e["from"], e["to"]
    if e["kind"] != "relates" or a not in pos or b not in pos: continue
    x1, y1, x2, y2 = X(a) + W - 10, Y(a) + H / 2, X(b) + W - 10, Y(b) + H / 2
    bend = 60 + abs(y2 - y1) * 0.25
    parts.append(f'<path d="M{x1},{y1} C{x1+bend},{y1} {x2+bend},{y2} {x2},{y2}" class="re"/>')
for i, n in nodes.items():
    if i not in pos: continue
    depth = pos[i][0] // COL
    cls = "root" if depth == 0 else ("d1" if depth == 1 else "d2")
    wpx = max(6, (W - 12) * n["weight"] / top_w)
    lab = html.escape(n["label"] if len(n["label"]) <= 17 else n["label"][:16] + "…")
    sl = ",".join(map(str, n["slide_nos"]))
    parts.append(
        f'<g transform="translate({X(i)},{Y(i)})"><rect class="n {cls}" width="{W}" height="{H}" rx="8"/>'
        f'<rect class="w" x="6" y="{H-5}" width="{wpx:.1f}" height="3" rx="1.5"/>'
        f'<text x="10" y="20" class="lab">{lab}</text><text x="{W-8}" y="20" class="sl" text-anchor="end">S{sl} · {n["weight"]:.2f}</text></g>')
roots_txt = " · ".join(nodes[r]["label"] for r in roots)
n_par = sum(e["kind"] == "parent" for e in g["edges"]); n_rel = len(g["edges"]) - n_par
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
text{{font-family:"Noto Sans KR","NanumGothic",sans-serif}}
.t{{font-size:22px;font-weight:700;fill:#17261F}} .m{{font-size:14px;fill:#4D5E56}}
.n{{stroke-width:1.5}} .root{{fill:#155C46;stroke:#155C46}} .d1{{fill:#E3F5EC;stroke:#8CCBAE}} .d2{{fill:#FFFFFF;stroke:#CFD8D3}}
.lab{{font-size:14px;font-weight:600;fill:#17261F}} .root~.lab{{fill:#FFFFFF}}
.sl{{font-size:11px;fill:#7A8A82;font-family:monospace}} .root~.sl{{fill:#BFE5D3}}
.w{{fill:#08B879;opacity:.8}} .pe{{fill:none;stroke:#7A8A82;stroke-width:1.6}} .re{{fill:none;stroke:#8A6FD6;stroke-width:1.2;stroke-dasharray:4 4;opacity:.55}}
</style>
<rect width="100%" height="100%" fill="#FFFDF7"/>
<text x="{PAD}" y="40" class="t">{html.escape(title)}</text>
<text x="{PAD}" y="66" class="m">노드 {len(nodes)} · 위계(실선) {n_par} · 그 밖의 연결(보라 점선) {n_rel} · 최상위 {len(roots)}개: {html.escape(roots_txt)}</text>
<text x="{PAD}" y="88" class="m">상자 오른쪽 = 나온 슬라이드 · weight(자료 비중) — 아래 초록 막대 길이도 weight</text>
{"".join(parts)}
</svg>'''
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": int(width), "height": int(height)}, device_scale_factor=2)
    pg.set_content(f"<html><body style='margin:0'>{svg}</body></html>")
    pg.screenshot(path=out, full_page=True)
    b.close()
print(out, int(width), "x", int(height))
