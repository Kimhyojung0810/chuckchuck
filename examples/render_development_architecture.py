from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SVG_OUT = ROOT / "docs" / "chuckchuck-development-architecture.svg"
W, H, VIEW_X, VIEW_Y = 1800, 930, 21, 62
parts = []

INK, MUTED, BLUE = "#202124", "#62666b", "#3478a8"
YELLOW, BLUE_FILL, GREEN = "#fff0c2", "#dceaf7", "#dcebd4"
PURPLE, PINK, GRAY = "#eadff3", "#f6dfdf", "#f2f3f4"


def add(value):
    parts.append(value)


def rect(x, y, w, h, fill="#ffffff", stroke="#30343a", width=1.5, rx=8, dash=None):
    dashed = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"{dashed}/>')


def text(x, y, value, size=14, weight=400, fill=INK, anchor="middle", line_height=19):
    family = '"NanumGothic", "Malgun Gothic", "Noto Sans KR", sans-serif'
    add(f'<text x="{x}" y="{y}" font-family=\'{family}\' font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">')
    for index, line_value in enumerate(value.split("\n")):
        add(f'<tspan x="{x}" dy="{0 if index == 0 else line_height}">{escape(line_value)}</tspan>')
    add("</text>")


def arrow(points, color=INK, width=1.8, dash=None):
    coords = " ".join(f"{x},{y}" for x, y in points)
    dashed = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"{dashed}/>')
    x1, y1 = points[-2]
    x2, y2 = points[-1]
    size, half = 9, 4.5
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        tip = [(x2, y2), (x2 - direction * size, y2 - half), (x2 - direction * size, y2 + half)]
    else:
        direction = 1 if y2 > y1 else -1
        tip = [(x2, y2), (x2 - half, y2 - direction * size), (x2 + half, y2 - direction * size)]
    add('<polygon points="' + " ".join(f"{x},{y}" for x, y in tip) + f'" fill="{color}"/>')


def line(points, color=INK, width=1.6, dash=None):
    coords = " ".join(f"{x},{y}" for x, y in points)
    dashed = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"{dashed}/>')


def estimated_width(value, size=16):
    return sum(size * 0.34 if char.isspace() else size * 0.54 if char.isascii() else size for char in value)


def group(x, y, w, h, label, fill="#ffffff"):
    rect(x, y, w, h, fill, "#5f6b76", 1.7, 20, "9 7")
    label_w = estimated_width(label, 25) + 46
    label_x = x + (w - label_w) / 2
    add(f'<rect x="{x + 20}" y="{y - 2}" width="{w - 40}" height="4" fill="{fill}"/>')
    add(f'<line x1="{x + 20}" y1="{y}" x2="{label_x - 5}" y2="{y}" stroke="#5f6b76" stroke-width="1.7" stroke-dasharray="9 7"/>')
    add(f'<line x1="{label_x + label_w + 5}" y1="{y}" x2="{x + w - 20}" y2="{y}" stroke="#5f6b76" stroke-width="1.7" stroke-dasharray="9 7"/>')
    add(f'<rect x="{label_x}" y="{y - 20}" width="{label_w}" height="42" rx="9" fill="#ffffff"/>')
    text(x + w / 2, y + 13, label, 25, 700)


def node(x, y, w, h, title, fill="#ffffff", stroke="#30343a", dash=None):
    rect(x, y, w, h, fill, stroke, 1.4, 8, dash)
    lines = title.count("\n") + 1
    title_y = y + h / 2 - (lines - 1) * 10.5 + 6
    text(x + w / 2, title_y, title, 17, 700, line_height=21)


def module(x, y, w, h, module_id, title, fill, stroke="#30343a", dash=None):
    node(x, y, w, h, title, fill, stroke, dash)
    badge_w = max(42, estimated_width(module_id, 12) + 14)
    add(f'<rect x="{x - 7}" y="{y - 9}" width="{badge_w}" height="23" rx="11.5" fill="#3c57a6" stroke="#ffffff" stroke-width="1.5"/>')
    text(x - 7 + badge_w / 2, y + 7, module_id, 12, 700, "#ffffff")


def brand_card(x, y, w, h, name, mark, color, fill):
    rect(x, y, w, h, fill, color, 1.4, 8)
    add(f'<circle cx="{x + 25}" cy="{y + h / 2}" r="14" fill="{color}"/>')
    text(x + 25, y + h / 2 + 4, mark, 10.5, 700, "#ffffff")
    text(x + 45, y + h / 2 + 5, name, 13.5, 700, anchor="start")


def module_icon(cx, cy, title, color):
    stroke = f'stroke="{color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"'
    if title == "자료 읽기":
        add(f'<path d="M{cx-16} {cy-20} H{cx+8} L{cx+17} {cy-11} V{cy+20} H{cx-16} Z" fill="none" {stroke}/>')
        add(f'<path d="M{cx+8} {cy-20} V{cy-11} H{cx+17} M{cx-9} {cy-3} H{cx+10} M{cx-9} {cy+6} H{cx+10}" fill="none" {stroke}/>')
    elif title == "발표 맥락":
        add(f'<circle cx="{cx}" cy="{cy}" r="18" fill="none" {stroke}/><circle cx="{cx}" cy="{cy}" r="7" fill="none" {stroke}/>')
        add(f'<path d="M{cx} {cy-25} V{cy-18} M{cx+25} {cy} H{cx+18} M{cx} {cy+25} V{cy+18} M{cx-25} {cy} H{cx-18}" fill="none" {stroke}/>')
    elif title == "녹음":
        add(f'<rect x="{cx-8}" y="{cy-20}" width="16" height="30" rx="8" fill="none" {stroke}/>')
        add(f'<path d="M{cx-16} {cy+2} Q{cx-16} {cy+18} {cx} {cy+18} Q{cx+16} {cy+18} {cx+16} {cy+2} M{cx} {cy+18} V{cy+25} M{cx-9} {cy+25} H{cx+9}" fill="none" {stroke}/>')
    elif title == "슬라이드 마크":
        add(f'<rect x="{cx-21}" y="{cy-16}" width="42" height="29" rx="3" fill="none" {stroke}/>')
        add(f'<path d="M{cx+7} {cy-16} V{cy+5} L{cx+14} {cy} L{cx+21} {cy+5} M{cx-10} {cy+21} H{cx+10}" fill="none" {stroke}/>')
    elif title == "받아쓰기":
        add(f'<path d="M{cx-22} {cy} H{cx-16} L{cx-11} {cy-12} L{cx-5} {cy+13} L{cx+1} {cy-8} L{cx+7} {cy+8} L{cx+13} {cy-4} H{cx+22}" fill="none" {stroke}/>')
        add(f'<path d="M{cx-18} {cy+21} H{cx+18}" fill="none" {stroke}/>')
    elif title == "구간 추정":
        add(f'<path d="M{cx-24} {cy} H{cx+24}" fill="none" {stroke}/>')
        for offset in (-20, -7, 7, 20):
            add(f'<circle cx="{cx+offset}" cy="{cy}" r="4" fill="#ffffff" {stroke}/>')
        add(f'<path d="M{cx-20} {cy-14} V{cy-7} M{cx+20} {cy+7} V{cy+14}" fill="none" {stroke}/>')
    elif title == "개념 정리":
        add(f'<rect x="{cx-20}" y="{cy-18}" width="34" height="12" rx="3" fill="none" {stroke}/>')
        add(f'<rect x="{cx-14}" y="{cy-3}" width="34" height="12" rx="3" fill="none" {stroke}/>')
        add(f'<rect x="{cx-20}" y="{cy+12}" width="34" height="12" rx="3" fill="none" {stroke}/>')
    elif title == "개념 그래프":
        add(f'<path d="M{cx-15} {cy-12} L{cx+15} {cy-12} L{cx} {cy+17} Z" fill="none" {stroke}/>')
        add(f'<circle cx="{cx-15}" cy="{cy-12}" r="6" fill="#ffffff" {stroke}/><circle cx="{cx+15}" cy="{cy-12}" r="6" fill="#ffffff" {stroke}/><circle cx="{cx}" cy="{cy+17}" r="6" fill="#ffffff" {stroke}/>')
    elif title == "예상 질문":
        add(f'<path d="M{cx-22} {cy-15} H{cx+22} V{cy+12} H{cx+3} L{cx-8} {cy+22} V{cy+12} H{cx-22} Z" fill="none" {stroke}/>')
        text(cx + 5, cy + 7, "?", 24, 700, color)
    elif title == "답변 판정":
        add(f'<circle cx="{cx}" cy="{cy}" r="22" fill="none" {stroke}/>')
        add(f'<path d="M{cx-12} {cy} L{cx-3} {cy+10} L{cx+14} {cy-10}" fill="none" {stroke}/>')
    elif title == "정합 분석":
        add(f'<rect x="{cx-22}" y="{cy-18}" width="16" height="36" rx="3" fill="none" {stroke}/><rect x="{cx+6}" y="{cy-18}" width="16" height="36" rx="3" fill="none" {stroke}/>')
        add(f'<path d="M{cx-4} {cy-7} H{cx+4} M{cx-4} {cy+7} H{cx+4}" fill="none" {stroke}/>')
    elif title == "흐름 비교":
        add(f'<path d="M{cx-22} {cy-12} H{cx+10} L{cx+18} {cy-4} M{cx+10} {cy-12} L{cx+18} {cy-4} L{cx+10} {cy+4}" fill="none" {stroke}/>')
        add(f'<path d="M{cx+22} {cy+12} H{cx-10} L{cx-18} {cy+4} M{cx-10} {cy+12} L{cx-18} {cy+4} L{cx-10} {cy-4}" fill="none" {stroke}/>')
    elif title == "삐약이 청중":
        for dx in (-16, 0, 16):
            add(f'<circle cx="{cx+dx}" cy="{cy-8}" r="7" fill="none" {stroke}/>')
            add(f'<path d="M{cx+dx-9} {cy+15} Q{cx+dx} {cy+3} {cx+dx+9} {cy+15}" fill="none" {stroke}/>')
    elif title == "평가·채점":
        add(f'<rect x="{cx-17}" y="{cy-21}" width="34" height="42" rx="4" fill="none" {stroke}/>')
        add(f'<path d="M{cx-7} {cy+2} L{cx-1} {cy+9} L{cx+11} {cy-7} M{cx-8} {cy-13} H{cx+8}" fill="none" {stroke}/>')
    elif title == "속도·시간":
        add(f'<circle cx="{cx}" cy="{cy}" r="22" fill="none" {stroke}/>')
        add(f'<path d="M{cx} {cy} L{cx+12} {cy-10} M{cx} {cy} V{cy-13}" fill="none" {stroke}/>')
    elif title == "발화 습관":
        add(f'<path d="M{cx-23} {cy-15} H{cx+23} V{cy+10} H{cx+5} L{cx-6} {cy+21} V{cy+10} H{cx-23} Z" fill="none" {stroke}/>')
        add(f'<path d="M{cx-15} {cy-2} H{cx-9} L{cx-5} {cy-9} L{cx} {cy+7} L{cx+5} {cy-6} L{cx+10} {cy+3} H{cx+16}" fill="none" {stroke}/>')
    elif title == "통합 리포트":
        add(f'<rect x="{cx-20}" y="{cy-22}" width="40" height="44" rx="4" fill="none" {stroke}/>')
        add(f'<path d="M{cx-11} {cy+12} V{cy+2} M{cx} {cy+12} V{cy-8} M{cx+11} {cy+12} V{cy-15}" fill="none" {stroke}/>')
    else:
        add(f'<path d="M{cx-23} {cy+14} H{cx-8} V{cy+4} H{cx+7} V{cy-6} H{cx+22}" fill="none" {stroke}/>')
        add(f'<path d="M{cx+14} {cy-14} L{cx+22} {cy-6} L{cx+14} {cy+2}" fill="none" {stroke}/>')


def compact_module(x, y, title, fill):
    accent = {YELLOW: "#b47a16", BLUE_FILL: "#3478a8", GREEN: "#3a7f62", PURPLE: "#7652a8", PINK: "#b65a5a"}[fill]
    module_icon(x + 82.5, y + 22, title, accent)
    text(x + 82.5, y + 73, title, 20, 700)


def provider(x, y, name, role, mark, color, fill):
    add(f'<circle cx="{x+117.5}" cy="{y+22}" r="32" fill="{color}"/>')
    text(x + 117.5, y + 28, mark, 14, 700, "#ffffff")
    text(x + 117.5, y + 90, name, 20, 700)
    text(x + 117.5, y + 119, role, 15, 500, MUTED)


add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="{VIEW_X} {VIEW_Y} {W} {H}">')
add(f'<rect x="{VIEW_X}" y="{VIEW_Y}" width="{W}" height="{H}" fill="#ffffff"/>')

# Left-side user, screen, and server topology
add('<circle cx="115" cy="425" r="38" fill="#edf6fa" stroke="#3478a8" stroke-width="2"/>')
add('<circle cx="115" cy="413" r="11" fill="#3478a8"/>')
add('<path d="M89 449 Q115 425 141 449" fill="#3478a8"/>')
text(115, 488, "발표자", 20, 700)
rect(220, 380, 160, 90, PURPLE, "#5f58c7", 1.8, 8)
add('<polyline points="247,432 267,411 285,437 307,405 330,433 353,412" fill="none" stroke="#ffffff" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>')
add('<rect x="278" y="478" width="44" height="7" rx="3.5" fill="#5f58c7"/>')
text(300, 517, "웹 데모 화면", 20, 700)
rect(440, 385, 130, 24, GREEN, "#3b8f65", 1.4, 6)
rect(440, 418, 130, 24, GREEN, "#3b8f65", 1.4, 6)
rect(440, 451, 130, 24, GREEN, "#3b8f65", 1.4, 6)
add('<circle cx="457" cy="397" r="4.5" fill="#3b8f65"/>')
add('<circle cx="457" cy="430" r="4.5" fill="#3b8f65"/>')
add('<circle cx="457" cy="463" r="4.5" fill="#3b8f65"/>')
text(505, 517, "API 오케스트레이션", 20, 700)
arrow([(153, 425), (219, 425)])
arrow([(220, 455), (146, 455)])
arrow([(380, 425), (439, 425)])
arrow([(440, 455), (381, 455)])

# Right-side stacked architecture panels
group(640, 105, 1125, 430, "마이크로 모듈", "#fff9e9")
module_specs = [
    ("자료 읽기", YELLOW), ("발표 맥락", YELLOW),
    ("녹음", BLUE_FILL), ("슬라이드 마크", BLUE_FILL),
    ("받아쓰기", BLUE_FILL), ("구간 추정", BLUE_FILL),
    ("개념 정리", YELLOW), ("개념 그래프", YELLOW),
    ("예상 질문", PURPLE), ("답변 판정", PURPLE),
    ("정합 분석", GREEN), ("흐름 비교", GREEN),
    ("삐약이 청중", PURPLE), ("평가·채점", PINK),
    ("속도·시간", PINK), ("발화 습관", PINK),
    ("통합 리포트", GREEN), ("발표 구성", GREEN),
]
module_x = [675, 850, 1025, 1200, 1375, 1550]
module_y = [145, 285, 425]
for index, (title, fill) in enumerate(module_specs):
    compact_module(module_x[index % 6], module_y[index // 6], title, fill)

group(640, 575, 1125, 220, "국내 인공지능 연동", "#fff4f6")
provider(675, 620, "Upstage", "Document Parse · Solar 추론", "U", "#e36a3d", "#fff4df")
provider(945, 620, "SKT A.X", "음성인식 · 공통 추론", "A.X", "#d92578", "#f8e2ef")
provider(1215, 620, "KT Mi:dm 2.0", "공통 추론 · AI Hub LoRA", "M", "#d83434", "#f7e3e3")
provider(1485, 620, "LG EXAONE", "공통 추론 · 가상 청중", "X", "#9d174d", "#eee3f2")

group(640, 825, 1125, 130, "저장소", "#f2f9ef")
add('<ellipse cx="970" cy="864" rx="35" ry="10" fill="#a8c8e2" stroke="#4f83aa" stroke-width="1.4"/>')
add('<rect x="935" y="864" width="70" height="35" fill="#dceaf7" stroke="#4f83aa" stroke-width="1.4"/>')
add('<ellipse cx="970" cy="899" rx="35" ry="10" fill="#a8c8e2" stroke="#4f83aa" stroke-width="1.4"/>')
text(970, 932, "세션·작업 기록", 19, 700)
rect(1400, 852, 72, 18, PINK, "#b84a4a", 1.2, 5)
rect(1400, 877, 72, 18, PINK, "#b84a4a", 1.2, 5)
rect(1400, 902, 72, 18, PINK, "#b84a4a", 1.2, 5)
text(1436, 944, "업로드·녹음·캐시 파일", 19, 700)

# Server connections preserve the original development-architecture topology
arrow([(570, 397), (620, 397), (620, 320), (640, 320)])
arrow([(570, 430), (610, 430), (610, 685), (640, 685)], BLUE, 1.8, "5 4")
arrow([(505, 540), (505, 890), (640, 890)])

add("</svg>")
svg = "".join(parts)
SVG_OUT.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + svg.replace("><", ">\n<"), encoding="utf-8")
print(f"생성 완료: {SVG_OUT}")
