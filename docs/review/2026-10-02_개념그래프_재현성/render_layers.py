"""개념 그래프 JSON → 층 지도 PNG. 열이 곧 층이다: 핵심 주장 | 핵심 개념 | 하위 개념(단계만큼) | 주장 | 근거.
주장·근거는 부모가 어느 깊이든 자기 열에 줄 맞춰 선다 — 그래프만 보고 「개념 → 주장 → 근거」 가 읽히게 (10-02).
근거는 노드마다 카드 하나에 원문 문구로 (3줄까지, 넘치면 「외 N」). 위계 = 실선, 그 밖의 연결 = 보라 점선. LLM 없음.
    LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu python render_layers.py GRAPH.json OUT.png "제목"
"""
import html, json, sys, textwrap
from playwright.sync_api import sync_playwright

src, out, title = sys.argv[1], sys.argv[2], sys.argv[3]
# 선택: F-06 개념 목록(JSON) — 장 띠 제목을 단다
slide_titles = {}
if len(sys.argv) > 4:
    for sl in json.load(open(sys.argv[4]))["slides"]:
        slide_titles[sl["slide_no"]] = sl.get("title") or ""
g = json.load(open(src))
nodes = {n["id"]: n for n in g["nodes"]}
kids = {}
for n in g["nodes"]:
    if n.get("parent_id") in nodes:
        kids.setdefault(n["parent_id"], []).append(n["id"])
ORDER = {"concept": 0, "claim": 1}
roots = [i for i in nodes if nodes[i].get("parent_id") not in nodes]

# 잎 개념 묶기 — 자식도 근거도 없는 개념은 같은 부모·같은 장끼리 상자 하나로 (그림만, 데이터는 그대로)
def is_leaf_concept(i):
    n = nodes[i]
    return (n.get("kind") or "concept") == "concept" and not kids.get(i) and not n.get("evidence")
for pid, ch in list(kids.items()):
    groups, rest = {}, []
    for i in ch:
        if is_leaf_concept(i):
            groups.setdefault(min(nodes[i]["slide_nos"] or [0]), []).append(i)
        else:
            rest.append(i)
    merged = []
    for no, ids in groups.items():
        if len(ids) == 1:
            merged.append(ids[0])
            continue
        gid = f"__group_{pid}_{no}"
        nodes[gid] = {"id": gid, "label": " · ".join(nodes[i]["label"] for i in ids), "slide_nos": [no],
                      "kind": "concept", "parent_id": pid, "evidence": [], "group": True}
        for i in ids:
            nodes[i]["hidden"] = True
        merged.append(gid)
    kids[pid] = rest + merged
nodes = {i: n for i, n in nodes.items() if not n.get("hidden")}
for k in kids.values():
    k.sort(key=lambda i: (min(nodes[i]["slide_nos"] or [99]), ORDER.get(nodes[i].get("kind"), 0)))   # 같은 장끼리 붙게

def kind(i):
    return nodes[i].get("kind") or "concept"

# 개념 깊이 → 열. 핵심 주장 0, 개념은 1.., 주장·근거는 개념 열 다음 고정 열
depth = {}
def walk(i, d):
    depth[i] = d
    for c in kids.get(i, []):
        walk(c, d + 1)
for r in roots:
    walk(r, 0)
concept_cols = max([depth[i] for i in nodes if kind(i) == "concept"] or [1])
CLAIM_COL, EV_COL = concept_cols + 1, concept_cols + 2
def col(i):
    k = kind(i)
    return 0 if k == "thesis" else (CLAIM_COL if k == "claim" else depth[i])

COLW = {"thesis": 250, "concept": 210, "claim": 330, "ev": 340}
GAP, PADY, LINE, VGAP, TOP, LEFT = 46, 9, 17, 10, 170, 30
xs, x = [], LEFT
for c in range(EV_COL + 1):
    xs.append(x)
    w = COLW["thesis"] if c == 0 else COLW["claim"] if c == CLAIM_COL else COLW["ev"] if c == EV_COL else COLW["concept"]
    x += w + GAP
WIDTH = x
def wpx(i):
    return COLW[kind(i)] if kind(i) in COLW else COLW["concept"]
def wrap(t, w):
    return textwrap.wrap(t, max(8, int(w / 14.5)))
def lines(i):
    return wrap(nodes[i]["label"], wpx(i) - 20)[:7 if nodes[i].get("group") else 4] or [""]
def box_h(nl):
    return PADY * 2 + LINE * nl + 2
def ev_lines(i):
    ev = nodes[i].get("evidence") or []
    out = []
    for e in ev[:3]:
        out += ["· " + l if k == 0 else "  " + l for k, l in enumerate(wrap(e, COLW["ev"] - 24)[:2])]
    if len(ev) > 3:
        out.append(f"외 {len(ev) - 3}개")
    return out

pos, cur = {}, [TOP]
ev_y = {}           # 근거 상자 y (없으면 노드 y)
bands = []          # (y 시작, 장 번호) — 핵심 주장 바로 밑 자식을 장마다 띠로 나눈다 (그림만; 장이라는 묶음은 자료 구조다)
def place(i):
    ch = kids.get(i, [])
    h = box_h(len(lines(i)))
    evh = box_h(len(ev_lines(i))) if ev_lines(i) else 0
    if ch:
        if evh:                                    # 자식이 있는 노드의 근거는 자식들 위에 제 줄을 잡는다 — 자식 근거와 겹치지 않게
            ev_y[i] = cur[0]
            cur[0] += evh + VGAP
        start = cur[0]
        last = None
        for c in ch:
            if kind(i) == "thesis":
                no = min(nodes[c]["slide_nos"] or [0])
                if no != last:
                    cur[0] += 26 if last is not None else 10
                    bands.append((cur[0] - 8, no))
                    cur[0] += 16
                    last = no
            place(c)
        mid = (pos[ch[0]][0] + pos[ch[-1]][0] + pos[ch[-1]][1]) / 2
        y = max(start, mid - h / 2)
    else:
        y = cur[0]
        cur[0] += max(h, evh) + VGAP
    pos[i] = (y, h)
for r in roots:
    place(r)
    cur[0] += 16
HEIGHT = int(cur[0] + 40)

LANES = ["핵심 주장"] + [("핵심 개념" if c == 1 else "하위 개념") for c in range(1, concept_cols + 1)] + ["주장", "근거"]
LANE_FILL = ["#EAF4EF", "#F3F7F5", "#F7F9F8", "#F7F9F8", "#F7F9F8", "#F7F9F8", "#F7F9F8"]
parts = []
for c, name in enumerate(LANES):
    w = COLW["thesis"] if c == 0 else COLW["claim"] if c == CLAIM_COL else COLW["ev"] if c == EV_COL else COLW["concept"]
    fill = "#EEF6F1" if c == CLAIM_COL else "#FBF3E9" if c == EV_COL else ("#E6F1EB" if c == 0 else "#F4F7F5")
    parts.append(f'<rect x="{xs[c]-12}" y="{TOP-44}" width="{w+24}" height="{HEIGHT-TOP+30}" rx="10" fill="{fill}"/>')
    parts.append(f'<text x="{xs[c]}" y="{TOP-18}" class="lane">{html.escape(name)}</text>')

for k, (y, no) in enumerate(bands):
    y_end = bands[k + 1][0] - 4 if k + 1 < len(bands) else HEIGHT - 30
    if k % 2 == 1:
        parts.append(f'<rect x="{xs[1]-12}" y="{y}" width="{WIDTH - xs[1] - 20}" height="{y_end - y}" fill="#000" opacity=".025"/>')
    t = slide_titles.get(no, "")
    parts.append(f'<text x="{xs[1]}" y="{y + 10}" class="band">S{no}{(" · " + html.escape(t[:40])) if t else ""}</text>')
X = lambda i: xs[col(i)]
Y = lambda i: pos[i][0]
H = lambda i: pos[i][1]
for i in nodes:
    p = nodes[i].get("parent_id")
    if p in pos and i in pos:
        x1, y1 = X(p) + wpx(p), Y(p) + H(p) / 2
        x2, y2 = X(i), Y(i) + H(i) / 2
        mx = x1 + 20
        parts.append(f'<path d="M{x1},{y1} L{mx},{y1} L{mx},{y2} L{x2},{y2}" class="pe"/>')
for i in nodes:
    if ev_lines(i):
        x1, y1 = X(i) + wpx(i), Y(i) + min(H(i), 30) / 2
        y2 = ev_y.get(i, Y(i)) + 14
        parts.append(f'<path d="M{x1},{y1} L{x1 + 14},{y1} L{x1 + 14},{y2} L{xs[EV_COL]},{y2}" class="ee"/>')
pairs = {frozenset((i, nodes[i].get("parent_id"))) for i in nodes}
for e in g["edges"]:
    a, b = e["from"], e["to"]
    if e["kind"] != "relates" or a not in pos or b not in pos or frozenset((a, b)) in pairs:
        continue
    x1, y1, x2, y2 = X(a) + 8, Y(a) + H(a) / 2, X(b) + 8, Y(b) + H(b) / 2
    bend = 40 + abs(y2 - y1) * 0.12
    parts.append(f'<path d="M{x1},{y1} C{x1-bend},{y1} {x2-bend},{y2} {x2},{y2}" class="re"/>')
for i, n in nodes.items():
    k = kind(i)
    tx = "".join(f'<text x="10" y="{PADY + 13 + j * LINE}" class="lab {k}">{html.escape(t)}</text>' for j, t in enumerate(lines(i)))
    sl = ",".join(map(str, n["slide_nos"]))
    grp = " grp" if n.get("group") else ""
    parts.append(f'<g transform="translate({X(i)},{Y(i)})"><rect class="n {k}{grp}" width="{wpx(i)}" height="{H(i)}" rx="8"/>{tx}'
                 f'<text x="{wpx(i)-7}" y="{H(i)-6}" class="sl {k}" text-anchor="end">S{sl}</text></g>')
    ev = ev_lines(i)
    if ev:
        eh = box_h(len(ev))
        et = "".join(f'<text x="10" y="{PADY + 12 + j * LINE}" class="evt">{html.escape(t)}</text>' for j, t in enumerate(ev))
        parts.append(f'<g transform="translate({xs[EV_COL]},{ev_y.get(i, Y(i))})"><rect class="evb" width="{COLW["ev"]}" height="{eh}" rx="6"/>{et}</g>')

kc = {k: sum(1 for n in g["nodes"] if n.get("kind") == k) for k in ("thesis", "claim", "concept")}
evs = sum(len(n.get("evidence") or []) for n in g["nodes"])
n_rel = sum(1 for e in g["edges"] if e["kind"] == "relates")
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">
<style>
text{{font-family:"Noto Sans KR","NanumGothic",sans-serif}}
.t{{font-size:22px;font-weight:700;fill:#17261F}} .m{{font-size:14px;fill:#4D5E56}} .lane{{font-size:15px;font-weight:800;fill:#3D5249;letter-spacing:.5px}}
.n{{stroke-width:1.4}} .n.thesis{{fill:#155C46;stroke:#155C46}} .n.concept{{fill:#FFFFFF;stroke:#5E9C80;stroke-width:1.8}} .n.claim{{fill:#DDF1E6;stroke:#9CCDB5}} .n.grp{{stroke-dasharray:5 3;fill:#FAFCFB}}
.lab{{font-size:13.5px;fill:#17261F}} .lab.thesis{{fill:#FFFFFF;font-weight:700}} .lab.concept{{font-weight:700}} .lab.claim{{font-weight:500}}
.sl{{font-size:10px;fill:#8A9A92;font-family:monospace}} .sl.thesis{{fill:#BFE5D3}}
.evb{{fill:#FFFFFF;stroke:#E2C9A6;stroke-width:1.2}} .evt{{font-size:12px;fill:#6B4A22}}
.pe{{fill:none;stroke:#7A8A82;stroke-width:1.4}} .ee{{fill:none;stroke:#E2C9A6;stroke-width:1.2;stroke-dasharray:2 3}}
.re{{fill:none;stroke:#8A6FD6;stroke-width:1.2;stroke-dasharray:4 4;opacity:.55}}
.band{{font-size:11.5px;font-weight:700;fill:#7A8A82;letter-spacing:.3px}}
</style>
<rect width="100%" height="100%" fill="#FFFDF7"/>
<text x="{LEFT}" y="40" class="t">{html.escape(title)}</text>
<text x="{LEFT}" y="66" class="m">핵심 주장 {kc["thesis"]} · 개념 {kc["concept"]} · 주장 {kc["claim"]} · 근거 {evs} · 그 밖의 연결(보라 점선) {n_rel} · S = 나온 장</text>
<text x="{LEFT}" y="106" class="m">점선 상자 = 같은 장에서 함께 나온 개념 묶음(하위 개념·주장이 없는 것들)</text>
<text x="{LEFT}" y="86" class="m">왼쪽에서 오른쪽으로 읽는다: 무엇에 관한 발표인가(개념) → 그 개념에 대해 무엇을 말하나(주장) → 무엇으로 받치나(근거)</text>
{"".join(parts)}
</svg>'''
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1.5 if HEIGHT * 1.5 < 15000 else max(0.6, 14000 / HEIGHT))
    pg.set_content(f"<html><body style='margin:0'>{svg}</body></html>")
    pg.screenshot(path=out, full_page=True)
    b.close()
print(out, WIDTH, "x", HEIGHT)
