"""개념 그래프 JSON → PNG (좌→우 나무). 종류별 색: 핵심 주장(진초록) · 주장(연초록) · 개념(흰색). 상자 안 「근거 N」 = 노드에 붙은 수치·결과·조건 수.
부모-자식 = 실선, relates = 보라 점선. 옛 그래프(kind 없음)는 깊이로 색칠한다. LLM 없음.
    LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu python render_tree.py GRAPH.json OUT.png "제목"
"""
import html, json, sys, textwrap
from playwright.sync_api import sync_playwright

src, out, title = sys.argv[1], sys.argv[2], sys.argv[3]
g = json.load(open(src))
nodes = {n["id"]: n for n in g["nodes"]}
kids, parent = {}, {}
for e in g["edges"]:
    if e["kind"] == "parent":
        kids.setdefault(e["from"], []).append(e["to"]); parent[e["to"]] = e["from"]
roots = sorted((i for i in nodes if i not in parent), key=lambda i: -nodes[i]["weight"])
for k in kids.values():
    k.sort(key=lambda i: ({"claim": 0, "concept": 1}.get(nodes[i].get("kind"), 1), min(nodes[i]["slide_nos"] or [99])))

COL, W, LINE, PADY, GAP, PAD, TOP = 330, 290, 17, 9, 10, 30, 110
def lines(n):
    return textwrap.wrap(n["label"], 19)[:3] or [""]
def h_of(i):
    return PADY * 2 + LINE * len(lines(nodes[i])) + 4
pos, cur = {}, [0.0]
def place(i, d):
    ch = kids.get(i, [])
    for c in ch: place(c, d + 1)
    h = h_of(i)
    if ch:
        y = (pos[ch[0]][1] + pos[ch[0]][2] / 2 + pos[ch[-1]][1] + pos[ch[-1]][2] / 2) / 2 - h / 2
        y = max(y, cur[0] - h - GAP) if False else y
    else:
        y = cur[0]; cur[0] += h + GAP
    pos[i] = (d * COL, y, h)
for r in roots:
    place(r, 0); cur[0] += 20
maxd = max(x for x, _, _ in pos.values()) // COL
width = int(PAD * 2 + maxd * COL + W + 40)
height = int(TOP + cur[0] + PAD + 30)
X = lambda i: PAD + pos[i][0]
Y = lambda i: TOP + pos[i][1]
H = lambda i: pos[i][2]
parts = []
for e in g["edges"]:
    a, b = e["from"], e["to"]
    if e["kind"] == "parent" and a in pos and b in pos:
        x1, y1, x2, y2 = X(a) + W, Y(a) + H(a) / 2, X(b), Y(b) + H(b) / 2
        mx = (x1 + x2) / 2
        parts.append(f'<path d="M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}" class="pe"/>')
pairs = {frozenset((e["from"], e["to"])) for e in g["edges"] if e["kind"] == "parent"}
for e in g["edges"]:
    a, b = e["from"], e["to"]
    if e["kind"] != "relates" or a not in pos or b not in pos or frozenset((a, b)) in pairs: continue
    x1, y1, x2, y2 = X(a) + W - 8, Y(a) + H(a) / 2, X(b) + W - 8, Y(b) + H(b) / 2
    bend = 50 + abs(y2 - y1) * 0.2
    parts.append(f'<path d="M{x1},{y1} C{x1+bend},{y1} {x2+bend},{y2} {x2},{y2}" class="re"/>')
for i, n in nodes.items():
    if i not in pos: continue
    kind = n.get("kind") or ("thesis" if i in roots else ("claim" if pos[i][0] == COL else "concept"))
    tx = "".join(f'<text x="10" y="{PADY + 13 + k * LINE}" class="lab {kind}">{html.escape(t)}</text>' for k, t in enumerate(lines(n)))
    ev = len(n.get("evidence") or [])
    badge = f'<text x="{W-8}" y="{H(i)-6}" class="ev {kind}" text-anchor="end">근거 {ev}</text>' if ev else ""
    sl = ",".join(map(str, n["slide_nos"]))
    parts.append(f'<g transform="translate({X(i)},{Y(i)})"><rect class="n {kind}" width="{W}" height="{H(i)}" rx="8"/>{tx}'
                 f'<text x="{W-8}" y="{PADY + 11}" class="sl {kind}" text-anchor="end">S{sl}</text>{badge}</g>')
n_par = sum(e["kind"] == "parent" for e in g["edges"]); n_rel = sum(e["kind"] == "relates" for e in g["edges"])
kc = {k: sum(1 for n in g["nodes"] if n.get("kind") == k) for k in ("thesis", "claim", "concept")}
evs = sum(len(n.get("evidence") or []) for n in g["nodes"])
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
text{{font-family:"Noto Sans KR","NanumGothic",sans-serif}}
.t{{font-size:22px;font-weight:700;fill:#17261F}} .m{{font-size:14px;fill:#4D5E56}}
.n{{stroke-width:1.4}} .n.thesis{{fill:#155C46;stroke:#155C46}} .n.claim{{fill:#E3F5EC;stroke:#8CCBAE}} .n.concept{{fill:#FFFFFF;stroke:#C9D3CE}}
.lab{{font-size:13.5px;font-weight:600;fill:#17261F}} .lab.thesis{{fill:#FFFFFF}} .lab.concept{{font-weight:500}}
.sl{{font-size:10.5px;fill:#7A8A82;font-family:monospace}} .sl.thesis{{fill:#BFE5D3}}
.ev{{font-size:10.5px;fill:#B5651D;font-weight:700}} .ev.thesis{{fill:#FFD9A8}}
.pe{{fill:none;stroke:#7A8A82;stroke-width:1.5}} .re{{fill:none;stroke:#8A6FD6;stroke-width:1.2;stroke-dasharray:4 4;opacity:.6}}
</style>
<rect width="100%" height="100%" fill="#FFFDF7"/>
<text x="{PAD}" y="40" class="t">{html.escape(title)}</text>
<text x="{PAD}" y="66" class="m">노드 {len(nodes)} (핵심 주장 {kc["thesis"]} · 주장 {kc["claim"]} · 개념 {kc["concept"]}) · 위계(실선) {n_par} · 그 밖의 연결(보라 점선) {n_rel} · 노드에 붙은 근거 {evs}</text>
<text x="{PAD}" y="88" class="m">진초록 = 핵심 주장(루트) · 연초록 = 장의 주장 · 흰색 = 개념 · S = 나온 장 · 「근거 N」 = 붙은 수치·결과·조건</text>
{"".join(parts)}
</svg>'''
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": width, "height": height}, device_scale_factor=1.5)
    pg.set_content(f"<html><body style='margin:0'>{svg}</body></html>")
    pg.screenshot(path=out, full_page=True)
    b.close()
print(out, width, "x", height)
