"""
합성 덱 → **실제 .pptx 파일** (라이브 경로 벤치용). 제품이 받는 것과 같은 파일을 만들어 f01(Upstage 파싱)부터 태운다.

실제 덱처럼 짠다 — 글 상자는 줄마다 따로, 식은 칸마다 따로(「혈당 부하 =」「혈당 지수」「×」 … 가로로 나란히),
표는 진짜 표 도형, 설문 보기는 나란한 상자, 쪽 번호는 오른쪽 아래 작은 상자.

python-pptx 는 .venv 에 없다 — 격리된 곳에 깔아 쓴다 (저장소 환경을 안 바꾼다):

    .venv/bin/python -m pip install --target labs/qa_bench/out/_pylib python-pptx
    PYTHONPATH=labs/qa_bench/out/_pylib .venv/bin/python labs/qa_bench/corpus/build_pptx.py ir_banchan policy_jeonse hum_novel health_glucose
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Pt

HERE = Path(__file__).resolve().parent
W, H = Emu(12192000), Emu(6858000)          # 16:9
MARGIN = Emu(600000)
PAGE_RE = re.compile(r"^[\d\s/|.·-]+$")
OP_RE = re.compile(r"^(?:[=×+÷→·*]|÷\s*\d+)")
POLL_RE = re.compile(r"^(?:[①②③④]|\d시|\d시 이후|\d+시간)")


def _box(slide, x, y, w, h, text, size=18, bold=False, color=(0x22, 0x22, 0x22)):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(*color)
    return tb


def _groups(blocks: list[dict]) -> list[tuple[str, list[str]]]:
    """블록 → (종류, 줄들). 종류: title · page · table · formula · poll · text. 연속한 표 줄·식 조각·설문 보기는 한 무리."""
    out: list[tuple[str, list[str]]] = []
    for b in blocks:
        t = b["text"]
        if b["category"] == "heading1":
            kind = "title"
        elif PAGE_RE.match(t) or re.fullmatch(r"\d{2}", t):
            kind = "page"
        elif t.startswith("| "):
            kind = "table"
        elif t.rstrip().endswith("=") or (out and out[-1][0] == "formula" and (OP_RE.match(t) or len(t) <= 8)):
            kind = "formula"
        elif POLL_RE.match(t) and len(t) <= 12:
            kind = "poll"
        else:
            kind = "text"
        if out and out[-1][0] == kind and kind in ("table", "formula", "poll"):
            out[-1][1].append(t)
        else:
            out.append((kind, [t]))
    return out


def build(name: str) -> Path:
    doc = json.loads((HERE / name / "slidedoc.json").read_text(encoding="utf-8"))
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    blank = prs.slide_layouts[6]
    for s in doc["slides"]:
        slide = prs.slides.add_slide(blank)
        y = MARGIN
        titled = False
        for kind, lines in _groups(s["blocks"]):
            if kind == "page":
                _box(slide, W - Emu(1800000), H - Emu(500000), Emu(1500000), Emu(350000), lines[0], size=11,
                     color=(0x88, 0x88, 0x88))
                continue
            if kind == "title":
                _box(slide, MARGIN, y, W - 2 * MARGIN, Emu(700000), lines[0], size=30 if not titled else 22, bold=True)
                titled = True
                y += Emu(800000)
            elif kind == "formula":
                # 식은 칸마다 따로 — PPT 에서 흔한 꼴. 가로로 나란히 둔다.
                n = len(lines)
                cw = (W - 2 * MARGIN) // max(n, 1)
                for i, part in enumerate(lines):
                    _box(slide, MARGIN + i * cw, y, cw, Emu(600000), part, size=24, bold=part.endswith("="))
                y += Emu(700000)
            elif kind == "poll":
                n = len(lines)
                cw = (W - 2 * MARGIN) // max(n, 1)
                for i, opt in enumerate(lines):
                    _box(slide, MARGIN + i * cw, y, cw - Emu(100000), Emu(450000), opt, size=16)
                y += Emu(550000)
            elif kind == "table":
                rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
                cols = max(len(r) for r in rows)
                rh = Emu(380000)
                shape = slide.shapes.add_table(len(rows), cols, MARGIN, y, W - 2 * MARGIN, rh * len(rows))
                for r, row in enumerate(rows):
                    for c in range(cols):
                        cell = shape.table.cell(r, c)
                        cell.text = row[c] if c < len(row) else ""
                        for p in cell.text_frame.paragraphs:
                            for run in p.runs:
                                run.font.size = Pt(14)
                y += rh * len(rows) + Emu(150000)
            else:
                size = 18 if len(lines[0]) > 30 else 20
                h = Emu(450000) if len(lines[0]) <= 40 else Emu(800000)
                _box(slide, MARGIN, y, W - 2 * MARGIN, h, lines[0], size=size)
                y += h + Emu(80000)
            if y > H - Emu(700000):   # 넘치면 오른쪽 단으로 (좁은 덱에서 드물다)
                y = Emu(1400000)
    out = HERE / name / "deck.pptx"
    prs.save(out)
    return out


if __name__ == "__main__":
    for name in sys.argv[1:] or ["ir_banchan", "policy_jeonse", "hum_novel", "health_glucose"]:
        print(build(name).relative_to(HERE.parent.parent.parent))
