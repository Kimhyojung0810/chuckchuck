"""개념 그래프 요약판 PNG — 핵심 주장 + 장마다 카드 하나(장 제목 · 헤드라인 주장 · 대표 개념 최대 3개) + 장을 잇는 선.
장을 잇는 선 = 같은 개념이 두 장 이상에 나온다(이름 라벨) · 그래프의 relates 간선(보라). 트리가 아니라 「장들이 어떤 개념으로 엮이나」 를 본다.
    LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu python render_summary.py GRAPH.json CONCEPTS.json OUT.png "제목"
"""
import html, json, sys, textwrap
from playwright.sync_api import sync_playwright

gpath, cpath, out, title = sys.argv[1:5]
g = json.load(open(gpath))
cd = json.load(open(cpath))
nodes = {n["id"]: n for n in g["nodes"]}
kids = {}
for n in g["nodes"]:
    if n.get("parent_id"):
        kids.setdefault(n["parent_id"], []).append(n["id"])


def desc(i, seen=None):
    seen = seen if seen is not None else set()
    for c in kids.get(i, []):
        if c not in seen:
            seen.add(c)
            desc(c, seen)
    return seen


thesis = next(n for n in g["nodes"] if n.get("kind") == "thesis")
slides = [s for s in cd["slides"] if s.get("title_kind") != "structural" and not s.get("missing")]
concepts = [n for n in g["nodes"] if n.get("kind") == "concept"]
home = {n["id"]: min(n["slide_nos"]) for n in concepts if n["slide_nos"]}

cards = []
for s in slides:
    no = s["slide_no"]
    head = (s.get("claims") or [""])[0]
    mine = sorted((n for n in concepts if home.get(n["id"]) == no), key=lambda n: (-len(desc(n["id"])), -len(n["slide_nos"]), n["label"]))
    cards.append({"no": no, "title": s.get("title") or "", "head": head, "concepts": [n["label"] for n in mine[:3]],
                  "more": max(0, len(mine) - 3), "thesis": no in thesis["slide_nos"]})

# 장을 잇는 선 — 여러 장에 나온 개념 (홈 장 → 다른 장), relates 간선 (두 끝의 첫 장끼리)
links = {}
for n in concepts:
    for no in n["slide_nos"]:
        if no != home[n["id"]]:
            links.setdefault((home[n["id"]], no), set()).add(n["label"])
rel = set()
for e in g["edges"]:
    if e["kind"] == "relates" and e["from"] in nodes and e["to"] in nodes:
        a, b = min(nodes[e["from"]]["slide_nos"] or [0]), min(nodes[e["to"]]["slide_nos"] or [0])
        if a != b and a and b:
            rel.add((min(a, b), max(a, b)))
card_nos = {c["no"] for c in cards}
links = {k: v for k, v in links.items() if k[0] in card_nos and k[1] in card_nos}
rel = {k for k in rel if k[0] in card_nos and k[1] in card_nos}

W_TH, W_CARD, X_TH, X_CARD, TOP, GAP = 300, 520, 30, 380, 120, 14
LINE = 18
pos, y = {}, TOP
for c in cards:
    lines = textwrap.wrap(c["head"], 34)[:3] if c["head"] else []
    h = 34 + LINE * len(lines) + (26 if c["concepts"] else 0) + 12
    c["lines"], c["h"] = lines, h
    pos[c["no"]] = (y, h)
    y += h + GAP
HEIGHT = y + 40
X_LINK = X_CARD + W_CARD
span_max = max((abs(cards.index(next(c for c in cards if c["no"] == b)) - cards.index(next(c for c in cards if c["no"] == a)))
                for a, b in list(links) + list(rel)), default=1)
WIDTH = X_LINK + 60 + 26 * max(4, span_max) + 260
parts = []
# 핵심 주장
th_lines = textwrap.wrap(thesis["label"], 18)[:6]
th_h = 30 + LINE * len(th_lines)
th_y = (TOP + HEIGHT - 40) / 2 - th_h / 2
parts.append(f'<rect x="{X_TH}" y="{th_y}" width="{W_TH}" height="{th_h}" rx="10" class="th"/>')
parts += [f'<text x="{X_TH + 14}" y="{th_y + 24 + k * LINE}" class="tht">{html.escape(t)}</text>' for k, t in enumerate(th_lines)]
for c in cards:
    cy, h = pos[c["no"]]
    parts.append(f'<path d="M{X_TH + W_TH},{th_y + th_h / 2} C{X_TH + W_TH + 30},{th_y + th_h / 2} {X_CARD - 30},{cy + h / 2} {X_CARD},{cy + h / 2}" class="pe"/>')
# 장 사이 선 (오른쪽 호)
order = [c["no"] for c in cards]
for k, ((a, b), labs) in enumerate(sorted(links.items(), key=lambda kv: abs(order.index(kv[0][1]) - order.index(kv[0][0])))):
    ya, yb = pos[a][0] + pos[a][1] / 2, pos[b][0] + pos[b][1] / 2
    d = abs(order.index(b) - order.index(a))
    xo = X_LINK + 30 + 26 * d
    parts.append(f'<path d="M{X_LINK},{ya} C{xo},{ya} {xo},{yb} {X_LINK},{yb}" class="lk"/>')
    lab = " · ".join(sorted(labs))[:28]
    parts.append(f'<text x="{xo + 4}" y="{(ya + yb) / 2 + 4}" class="lkt">{html.escape(lab)}</text>')
for a, b in rel:
    ya, yb = pos[a][0] + pos[a][1] / 2, pos[b][0] + pos[b][1] / 2
    xo = X_LINK + 30 + 26 * abs(order.index(b) - order.index(a)) + 12
    parts.append(f'<path d="M{X_LINK},{ya + 6} C{xo},{ya + 6} {xo},{yb + 6} {X_LINK},{yb + 6}" class="re"/>')
# 카드
for c in cards:
    cy, h = pos[c["no"]]
    cls = "card th2" if c["thesis"] else "card"
    parts.append(f'<rect x="{X_CARD}" y="{cy}" width="{W_CARD}" height="{h}" rx="9" class="{cls}"/>')
    parts.append(f'<text x="{X_CARD + 12}" y="{cy + 20}" class="ct">S{c["no"]} · {html.escape(c["title"][:36])}'
                 + ('  <tspan class="tag">핵심 주장 장</tspan>' if c["thesis"] else "") + "</text>")
    for k, t in enumerate(c["lines"]):
        parts.append(f'<text x="{X_CARD + 12}" y="{cy + 40 + k * LINE}" class="hd">{html.escape(t)}</text>')
    if c["concepts"]:
        yy = cy + 40 + LINE * len(c["lines"]) + 4
        x = X_CARD + 12
        for lab in c["concepts"]:
            w = 14 + 13 * len(lab)
            parts.append(f'<rect x="{x}" y="{yy - 13}" width="{w}" height="20" rx="10" class="chip"/>'
                         f'<text x="{x + 7}" y="{yy + 1}" class="chipt">{html.escape(lab)}</text>')
            x += w + 6
        if c["more"]:
            parts.append(f'<text x="{x + 2}" y="{yy + 1}" class="more">+{c["more"]}</text>')
n_links = sum(len(v) for v in links.values())
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">
<style>
text{{font-family:"Noto Sans KR","NanumGothic",sans-serif}}
.t{{font-size:22px;font-weight:700;fill:#17261F}} .m{{font-size:13.5px;fill:#4D5E56}}
.th{{fill:#155C46}} .tht{{font-size:15px;font-weight:700;fill:#fff}}
.card{{fill:#FFFFFF;stroke:#B9D9C9;stroke-width:1.4}} .th2{{fill:#F1F8F4;stroke:#5E9C80}}
.ct{{font-size:12.5px;font-weight:700;fill:#5E7268}} .tag{{fill:#155C46;font-size:11px}}
.hd{{font-size:14px;font-weight:600;fill:#17261F}}
.chip{{fill:#E3F2EA;stroke:#9CCDB5}} .chipt{{font-size:12px;fill:#1F4D3B;font-weight:600}} .more{{font-size:12px;fill:#7A8A82}}
.pe{{fill:none;stroke:#9AA8A1;stroke-width:1.2}}
.lk{{fill:none;stroke:#D08A3C;stroke-width:1.6;opacity:.75}} .lkt{{font-size:11.5px;fill:#9A5B1A;font-weight:600}}
.re{{fill:none;stroke:#8A6FD6;stroke-width:1.4;stroke-dasharray:4 4}}
</style>
<rect width="100%" height="100%" fill="#FFFDF7"/>
<text x="30" y="42" class="t">{html.escape(title)}</text>
<text x="30" y="68" class="m">장 {len(cards)}개 · 카드 = 장 제목 · 헤드라인 주장 · 대표 개념(하위가 많은 순 3개) · 주황 선 = 같은 개념이 다른 장에 다시 나옴(이름 표시) {n_links}개 · 보라 점선 = 자료가 밝힌 연결 {len(rel)}개</text>
<text x="30" y="88" class="m">전체 그래프: 노드 {len(g["nodes"])} — 상세는 층 지도(png_현재) 참고</text>
{"".join(parts)}
</svg>'''
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": int(WIDTH), "height": int(HEIGHT)}, device_scale_factor=1.5)
    pg.set_content(f"<html><body style='margin:0'>{svg}</body></html>")
    pg.screenshot(path=out, full_page=True)
    b.close()
print(out, int(WIDTH), "x", int(HEIGHT))
