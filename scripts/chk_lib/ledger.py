"""
장부(docs/*_BENCH_LEDGER.md)의 IMPROVED 줄을 이어 결선 그래프를 만든다 — AUTONOMOUS_LOOP §5 의
「Baseline → Prompt → Context → Fine-tuning → Festa」 그래프의 원자료.

    scripts/chk ledger-chart                       # QA 장부 → exports/ledger_chart/qa_<날짜>.svg + .md
    scripts/chk ledger-chart --graph               # 그래프·정합 장부
    scripts/chk ledger-chart --metrics specificity_mean,grounding_mean

지표마다 패널 하나(작은 다중 그래프). 축은 하나씩 — 스케일이 다른 지표(0~1 인용률 · 1~5 rubric)를 한 축에
겹치지 않는다. 값은 장부의 「핵심 델타」 열 `이름 전→후` 에서 읽는다. 어떤 줄이 지표를 안 적었으면
그 지표는 안 바뀐 것이므로 앞 값을 이어 쓴다. 기준선은 그 지표가 처음 등장한 줄의 「전」 값.
채택되지 않은 줄(REGRESSED·NOISE)은 표에만 남기고 선에는 넣지 않는다 — 코드에 남은 것만 이력이다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

from . import common as C
from .brief import table_rows

DEFAULT_METRICS = {
    "qa": ["specificity_mean", "grounding_mean", "rubric.overall_mean"],
    "graph": ["label_grounded", "align.evidence_found", "align.coverage"],
}
DELTA_RE = re.compile(r"([A-Za-z_.]+)\s+([-\d.]+)→([-\d.]+)")
INK, INK2, GRID, LINE = "#191F28", "#6B7684", "#E5E8EB", "#08B879"


def parse_rows(md: str) -> list[dict]:
    out = []
    for cells in table_rows(md, "| 시각 | 전 | 후"):
        if len(cells) < 7:
            continue
        deltas = {m.group(1): (float(m.group(2)), float(m.group(3))) for m in DELTA_RE.finditer(cells[4])}
        out.append({"time": cells[0], "verdict": cells[3], "deltas": deltas, "head": cells[5], "note": cells[6]})
    return out


def series(rows: list[dict], metric: str) -> list[tuple[str, float]]:
    """(라벨, 값) 점 목록. 첫 점은 기준선, 이후 IMPROVED 줄마다 한 점."""
    pts: list[tuple[str, float]] = []
    current: float | None = None
    for r in rows:
        d = r["deltas"].get(metric)
        if current is None and d is not None:
            current = d[0]
            pts.append(("Baseline", current))
        if r["verdict"] != "IMPROVED" or current is None:
            continue
        if d is not None:
            current = d[1]
        pts.append((r["note"].split()[0][:18] if r["note"] else r["time"][5:], current))
    return pts


def _panel(metric: str, pts: list[tuple[str, float]], y0: int, w: int, h: int) -> str:
    left, right, top, bottom = 150, 40, 28, 30
    xs = [left + (w - left - right) * (i / max(1, len(pts) - 1)) for i in range(len(pts))]
    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.25 or (abs(hi) * 0.1 or 0.5)
    lo, hi = lo - pad, hi + pad
    ys = [y0 + top + (h - top - bottom) * (1 - (v - lo) / (hi - lo)) for v in vals]
    g = [f'<text x="{left - 12}" y="{y0 + top + 4}" text-anchor="end" font-size="12" font-weight="600" fill="{INK}">{metric}</text>']
    for frac in (0, 0.5, 1):
        gy = y0 + top + (h - top - bottom) * (1 - frac)
        g.append(f'<line x1="{left}" x2="{w - right}" y1="{gy:.1f}" y2="{gy:.1f}" stroke="{GRID}" stroke-width="1"/>')
        g.append(f'<text x="{left - 12}" y="{gy + 4:.1f}" text-anchor="end" font-size="10" fill="{INK2}">{lo + (hi - lo) * frac:.2f}</text>')
    if len(pts) > 1:
        g.append('<polyline fill="none" stroke="%s" stroke-width="2" stroke-linejoin="round" points="%s"/>'
                 % (LINE, " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))))
    for (label, v), x, y in zip(pts, xs, ys):
        g.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{LINE}" stroke="#fff" stroke-width="2"/>')
        g.append(f'<text x="{x:.1f}" y="{y - 10:.1f}" text-anchor="middle" font-size="11" fill="{INK}">{v:.2f}</text>')
        g.append(f'<text x="{x:.1f}" y="{y0 + h - 8}" text-anchor="middle" font-size="10" fill="{INK2}">{label}</text>')
    return "\n".join(g)


def render_svg(title: str, rows: list[dict], metrics: list[str]) -> str:
    w, ph = 760, 150
    panels = [(m, series(rows, m)) for m in metrics]
    panels = [(m, p) for m, p in panels if p]
    total_h = 44 + ph * max(1, len(panels))
    body = [f'<text x="20" y="26" font-size="15" font-weight="700" fill="{INK}">{title}</text>']
    for i, (m, pts) in enumerate(panels):
        body.append(_panel(m, pts, 44 + i * ph, w, ph))
    if not panels:
        body.append(f'<text x="20" y="80" font-size="12" fill="{INK2}">IMPROVED 줄이 없어 그릴 점이 없어요.</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{total_h}" viewBox="0 0 {w} {total_h}" '
            f'font-family="Pretendard, system-ui, sans-serif"><rect width="{w}" height="{total_h}" fill="#FFFDF7"/>\n'
            + "\n".join(body) + "\n</svg>\n")


def render_md(rows: list[dict], metrics: list[str]) -> str:
    lines = ["| 시각 | 판정 | HEAD | " + " | ".join(metrics) + " | 메모 |", "|---|---|---|" + "---|" * len(metrics) + "---|"]
    for r in rows:
        cells = [f"{r['deltas'][m][0]:g}→{r['deltas'][m][1]:g}" if m in r["deltas"] else "" for m in metrics]
        lines.append(f"| {r['time']} | {r['verdict']} | {r['head']} | " + " | ".join(cells) + f" | {r['note'][:70]} |")
    improved = [r for r in rows if r["verdict"] == "IMPROVED"]
    return (f"IMPROVED {len(improved)} / 전체 {len(rows)}줄. 선에는 IMPROVED 만 들어간다.\n\n" + "\n".join(lines) + "\n")


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="scripts/chk ledger-chart", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", action="store_true", help="GRAPH_BENCH_LEDGER 를 그린다 (기본 QA)")
    ap.add_argument("--metrics", help="쉼표로 구분한 지표 이름")
    ap.add_argument("--out", type=Path, help="출력 경로(.svg). 같은 이름의 .md 도 만든다")
    ns = ap.parse_args(argv)
    kind = "graph" if ns.graph else "qa"
    ledger = C.ROOT / ("docs/GRAPH_BENCH_LEDGER.md" if ns.graph else "docs/QA_BENCH_LEDGER.md")
    rows = parse_rows(ledger.read_text(encoding="utf-8"))
    metrics = [m.strip() for m in ns.metrics.split(",")] if ns.metrics else DEFAULT_METRICS[kind]
    out = ns.out or C.ROOT / "exports/ledger_chart" / f"{kind}_{dt.date.today():%Y%m%d}.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    title = ("그래프·정합" if ns.graph else "Q&A") + f" 벤치마크 — 채택(IMPROVED) 이력 · {dt.date.today()}"
    out.write_text(render_svg(title, rows, metrics), encoding="utf-8")
    out.with_suffix(".md").write_text(render_md(rows, metrics), encoding="utf-8")
    improved = sum(1 for r in rows if r["verdict"] == "IMPROVED")
    shown = out.relative_to(C.ROOT) if out.is_relative_to(C.ROOT) else out
    print(C.ok(f"{shown} · {out.with_suffix('.md').name} — 장부 {len(rows)}줄 중 IMPROVED {improved}"))
    return 0
