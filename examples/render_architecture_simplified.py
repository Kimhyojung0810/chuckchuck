from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "chuckchuck-system-architecture-final.svg"
W, H, VIEW_X, VIEW_Y = 1660, 840, 5, 70
parts = []

INK, MUTED, BLUE = "#202124", "#62666b", "#3478a8"
YELLOW, BLUE_FILL, GREEN = "#fff0c2", "#dceaf7", "#dcebd4"
PURPLE, PINK, GRAY = "#eadff3", "#f6dfdf", "#f2f3f4"


def add(value):
    parts.append(value)


def rect(x, y, w, h, fill="#ffffff", stroke="#30343a", width=1.5, rx=8, dash=None):
    dashed = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"{dashed}/>')


def text(x, y, value, size=14, weight=400, fill=INK, anchor="middle", line_height=19, serif=False):
    family = '"NanumMyeongjo", "Times New Roman", serif' if serif else '"NanumGothic", "Malgun Gothic", "Noto Sans KR", sans-serif'
    add(f'<text x="{x}" y="{y}" font-family=\'{family}\' font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">')
    for index, line_value in enumerate(value.split("\n")):
        add(f'<tspan x="{x}" dy="{0 if index == 0 else line_height}">{escape(line_value)}</tspan>')
    add("</text>")


def arrow(points, color=INK, width=1.9, dash=None):
    coords = " ".join(f"{x},{y}" for x, y in points)
    dashed = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"{dashed}/>')
    x1, y1 = points[-2]
    x2, y2 = points[-1]
    size, half = 10, 5
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        tip = [(x2, y2), (x2 - direction * size, y2 - half), (x2 - direction * size, y2 + half)]
    else:
        direction = 1 if y2 > y1 else -1
        tip = [(x2, y2), (x2 - half, y2 - direction * size), (x2 + half, y2 - direction * size)]
    add('<polygon points="' + " ".join(f"{x},{y}" for x, y in tip) + f'" fill="{color}"/>')


def group(x, y, w, h, label, fill="#ffffff"):
    rect(x, y, w, h, fill, "#5f6b76", 1.7, 20, "9 7")
    label_lines = label.split("\n")
    label_text_w = max(
        sum(8.5 if char.isspace() else 13.3 if char.isascii() else 25 for char in line_value)
        for line_value in label_lines
    )
    label_w = label_text_w + 20
    label_x = x + (w - label_w) / 2
    add(f'<rect x="{x + 20}" y="{y - 2}" width="{w - 40}" height="4" fill="{fill}"/>')
    if label_x - 5 > x + 20:
        add(f'<line x1="{label_x - 5}" y1="{y}" x2="{x + 20}" y2="{y}" stroke="#5f6b76" stroke-width="1.7" stroke-dasharray="9 7"/>')
    if label_x + label_w + 5 < x + w - 20:
        add(f'<line x1="{label_x + label_w + 5}" y1="{y}" x2="{x + w - 20}" y2="{y}" stroke="#5f6b76" stroke-width="1.7" stroke-dasharray="9 7"/>')
    if len(label_lines) == 1:
        add(f'<rect x="{label_x}" y="{y - 20}" width="{label_w}" height="42" rx="9" fill="#ffffff"/>')
        text(x + w / 2, y + 13, label, 25, 700)
    else:
        add(f'<rect x="{label_x}" y="{y - 34}" width="{label_w}" height="66" rx="9" fill="#ffffff"/>')
        text(x + w / 2, y - 7, label, 25, 700, line_height=28)


def node(x, y, w, h, title, subtitle="", fill="#ffffff", number=None):
    rect(x, y, w, h, fill, "#30343a", 1.4, 8)
    if number is not None:
        add(f'<circle cx="{x + 1}" cy="{y + 1}" r="13" fill="#3c57a6" stroke="#ffffff" stroke-width="2"/>')
        text(x + 1, y + 6, str(number), 13, 700, "#ffffff")
    title_lines = title.count("\n") + 1
    title_y = y + h / 2 - (title_lines - 1) * 10.5 + 6
    text(x + w / 2, title_y, title, 20, 700, line_height=23)


add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="{VIEW_X} {VIEW_Y} {W} {H}">')
add(f'<rect x="{VIEW_X}" y="{VIEW_Y}" width="{W}" height="{H}" fill="#ffffff"/>')

group(35, 105, 300, 770, "사용자 학습 루프")
group(375, 105, 940, 770, "멀티모달 분석 및 피드백")
group(1355, 105, 280, 770, "API 호출")

add('<circle cx="88" cy="190" r="30" fill="#edf6fa" stroke="#3478a8" stroke-width="1.8"/>')
add('<circle cx="88" cy="180" r="8" fill="#3478a8"/>')
add('<path d="M69 206 Q88 189 107 206" fill="#3478a8"/>')
text(88, 235, "발표자", 15, 700)
node(135, 152, 165, 82, "발표 입력", "PDF·PPTX\n상황·청중·목표시간", YELLOW, 1)
arrow([(118, 190), (134, 190)])
node(72, 278, 228, 90, "발표 리허설", "음성 녹음 · 화면 전환\n재방문·시간축 기록", BLUE_FILL, 2)
node(72, 462, 228, 90, "맞춤형 Q&A", "답변 판정 · 힌트 · 재질문\n자기 말로 재설명", GREEN, 3)
node(72, 625, 228, 96, "통합 리포트", "개념·흐름·음성·점수\n삐약이 · 발표 구성 교정", PURPLE, 4)
node(72, 790, 228, 55, "다음 리허설", "분석 → 학습 → 재연습", GREEN)
arrow([(217, 234), (217, 255), (186, 255), (186, 277)])
arrow([(186, 368), (186, 461)])
arrow([(186, 552), (186, 624)])
arrow([(186, 722), (186, 789)], "#3a7f62", 2)
arrow([(72, 817), (52, 817), (52, 323), (71, 323)], "#3a7f62", 1.8, "5 4")

group(415, 160, 390, 225, "자료 분석 경로", "#fff9e8")
node(440, 225, 108, 88, "구조 분석", "제목·본문·표", YELLOW)
node(573, 225, 108, 88, "개념 추출", "주제·키워드", YELLOW)
node(706, 225, 74, 88, "그래프", "위계·연결", YELLOW)
arrow([(548, 269), (572, 269)])
arrow([(681, 269), (705, 269)])
group(415, 455, 390, 225, "발화 분석 경로", "#f1f7fc")
node(440, 520, 95, 88, "음성인식", "단어별 시각", BLUE_FILL)
node(550, 520, 95, 88, "STT 분석", "슬라이드 구간", BLUE_FILL)
node(660, 520, 120, 88, "언어적 특징\n분석", "속도·반복", BLUE_FILL)
arrow([(535, 564), (549, 564)])
arrow([(645, 564), (659, 564)])
arrow([(300, 192), (390, 192), (390, 269), (439, 269)])
arrow([(300, 323), (380, 323), (380, 564), (439, 564)])

node(850, 330, 205, 160, "자료–발화 정합", "정합 · 정당한 생략\n누락 · 모순 · 설명 순서", GREEN, 5)
arrow([(780, 269), (820, 269), (820, 380), (849, 380)])
arrow([(780, 564), (820, 564), (820, 440), (849, 440)])
node(1100, 205, 175, 112, "질문·답변 코칭", "질문 우선순위\n판정 · 힌트 · 재질문", PURPLE, 6)
node(1100, 455, 175, 112, "평가·음성 분석", "39개 평가 항목\n시간 · 속도 · 발화 습관", PINK, 7)
node(1038, 665, 237, 110, "통합 코칭 결과", "근거 기반 리포트 · 삐약이\n발표 구성 원리 부분 교정", GREEN, 8)
arrow([(1055, 370), (1075, 370), (1075, 261), (1099, 261)])
arrow([(1055, 450), (1075, 450), (1075, 511), (1099, 511)])
arrow([(1275, 261), (1288, 261), (1288, 720), (1276, 720)])
arrow([(1188, 567), (1188, 664)])
arrow([(1038, 720), (350, 720), (350, 673), (301, 673)], "#3a7f62", 2)

node(415, 790, 860, 70, "공통 AI 어댑터", "Document Parse · STT · LLM · 재요청 · 타임아웃 · 폴백", GRAY)
arrow([(1156, 775), (1156, 789)], BLUE, 1.8, "5 4")
arrow([(1275, 827), (1335, 827), (1335, 620), (1374, 620)], BLUE, 2, "5 4")

group(1375, 175, 240, 650, "국내 인공지능\n모델", "#f8f3fb")
node(1395, 220, 200, 88, "Upstage Solar", "Document Parse · Solar Pro 3", YELLOW)
node(1395, 340, 200, 88, "SKT A.X", "STT · A.X-K1", BLUE_FILL)
node(1395, 460, 200, 88, "KT Mi:dm 2.0", "로컬 추론 · LoRA 발화 태거", GREEN)
node(1395, 580, 200, 88, "LG EXAONE", "의미 판단 · 가상 청중", PURPLE)
node(1395, 700, 200, 88, "AI Hub 공적말하기\n데이터", "LoRA 학습 · 내부 성능 검증", PINK)

add("</svg>")
svg = "".join(parts)
OUTPUT.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + svg.replace("><", ">\n<"), encoding="utf-8")
print(f"생성 완료: {OUTPUT}")
