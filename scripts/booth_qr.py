#!/usr/bin/env python3
"""
결선 부스 QR — https://chuckchuck-present.com/hi 하나를 PNG(1024px) · SVG · A4 인쇄 HTML/PDF 로 만들고, 다시 읽어 주소를 확인한다.

왜 꼬리표(?src=booth)를 안 붙이나 — Cloudflare 캐시 열쇠가 주소마다 갈라져 첫 방문이 느려지고, 진입은 이미 서버 로그의
`GET /hi` 줄로 센다(scripts/booth_funnel.py). 로고를 안 넣는 이유 — 가운데를 가리면 오류 정정 몫을 깎아 먹는다. 인쇄물은
구겨지고 조명이 번들거리니 오류 정정 Q(25%) · 여백 4칸 · 검정/흰색.

    # 1) 만들기 + 읽어 보기 — segno 필요 (zxing-cpp·Pillow 가 있으면 PNG 를 다시 읽어 주소를 확인한다)
    python3 -m pip install --user segno zxing-cpp pillow pypdfium2   # PEP 668 이면 venv 에서
    python3 scripts/booth_qr.py --out ~/meetings/2026-10-11_결선_QR
    # 2) A4 PDF · 인쇄면 사진 — playwright(Chromium) 가 있는 파이썬으로
    .venv/bin/python scripts/booth_qr.py --out ~/meetings/2026-10-11_결선_QR --pdf
    # 3) 인쇄면 사진도 읽어 보기
    python3 scripts/booth_qr.py --out ~/meetings/2026-10-11_결선_QR --verify-only

PNG 는 표준 라이브러리(zlib)로 직접 쓴다 — 칸 하나를 정수 픽셀로 그려 1024px 에 맞추고 남는 픽셀은 흰 여백으로 (흐린 가장자리 없음).
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from datetime import datetime
from pathlib import Path

URL = "https://chuckchuck-present.com/hi"
CAPTION = "QR 을 찍으면 척척발표를 바로 만나요"
SUB = "chuckchuck-present.com/hi"
BORDER = 4
PNG_SIZE = 1024


def make_qr(url: str = URL, error: str = "q"):
    import segno

    return segno.make_qr(url, error=error, boost_error=False)


def write_png(matrix: list[list[int]], path: Path, size: int = PNG_SIZE, border: int = BORDER) -> dict:
    """1 = 검정 칸. 칸 하나 = scale×scale 픽셀(정수), 바깥은 흰색. 회색조 8비트 PNG."""
    n = len(matrix)
    scale = size // (n + 2 * border)
    if scale < 1:
        raise ValueError("그림이 너무 작아요")
    off = (size - scale * n) // 2          # ≥ border*scale — 여백 4칸 이상
    rows = []
    white_row = b"\x00" + b"\xff" * size
    for y in range(size):
        my = (y - off) // scale
        if y < off or my >= n:
            rows.append(white_row)
            continue
        line = bytearray(b"\xff" * size)
        for mx, dark in enumerate(matrix[my]):
            if dark:
                x0 = off + mx * scale
                line[x0:x0 + scale] = b"\x00" * scale
        rows.append(b"\x00" + bytes(line))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")
    path.write_bytes(png)
    return {"modules": n, "scale_px": scale, "quiet_zone_modules": off // scale}


def svg_markup(qr, border: int = BORDER) -> str:
    """SVG 문자열 — 크기는 viewBox 만(인쇄 HTML 이 mm 로 정한다). 검정/흰 바탕."""
    import io

    buf = io.BytesIO()
    qr.save(buf, kind="svg", border=border, dark="#000", light="#fff", xmldecl=False, svgns=True,
            omitsize=True, nl=False, title="척척발표 QR — " + URL, encoding="utf-8")
    return buf.getvalue().decode("utf-8")


PRINT_HTML = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>척척발표 부스 QR</title>
<style>
  @page {{ size: A4; margin: 0; }}
  html, body {{ margin: 0; background: #fff; }}
  body {{ font-family: "Pretendard", "Noto Sans KR", "NanumGothic", system-ui, sans-serif; color: #1d1d1b; }}
  .page {{ width: 210mm; height: 297mm; box-sizing: border-box; padding: 30mm 20mm 24mm;
          display: flex; flex-direction: column; align-items: center; justify-content: space-between; }}
  .brand {{ font-size: 15mm; font-weight: 800; letter-spacing: -0.3mm; color: #155C46; margin: 0; }}
  .lead {{ font-size: 6.4mm; font-weight: 500; color: #4a4a46; margin: 4mm 0 0; text-align: center; }}
  .qr {{ width: 140mm; height: 140mm; }}
  .qr svg {{ width: 100%; height: 100%; display: block; shape-rendering: crispEdges; }}
  .cap {{ font-size: 9mm; font-weight: 700; margin: 0; text-align: center; letter-spacing: -0.2mm; }}
  .url {{ font-size: 5mm; color: #6b6b66; margin: 3mm 0 0; letter-spacing: 0.1mm; }}
  .foot {{ font-size: 3.6mm; color: #9a9a94; }}
</style></head>
<body><main class="page">
  <header style="text-align:center">
    <p class="brand">척척발표</p>
    <p class="lead">AI 와 함께하는 발표 리허설</p>
  </header>
  <div class="qr" role="img" aria-label="척척발표 QR 코드 — {url}">{svg}</div>
  <div style="text-align:center">
    <p class="cap">{caption}</p>
    <p class="url">{sub}</p>
  </div>
  <p class="foot">카메라 앱으로 찍어 주세요 · 로그인 없이 바로 열려요</p>
</main></body></html>
"""


def write_print_html(svg: str, path: Path) -> None:
    path.write_text(PRINT_HTML.format(svg=svg, url=URL, caption=CAPTION, sub=SUB), encoding="utf-8")


def render_pdf(html: Path, pdf: Path, shot: Path) -> None:
    """Chromium(playwright)으로 A4 PDF 와, 같은 면을 찍은 PNG(디코드 확인용)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 794, "height": 1123}, device_scale_factor=2)
        page.goto(html.resolve().as_uri())
        page.wait_for_timeout(300)
        page.pdf(path=str(pdf), format="A4", print_background=True, margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
        page.screenshot(path=str(shot), full_page=False)
        browser.close()


def decode(path: Path) -> list[str]:
    """그림 → 읽힌 글자들. zxing-cpp + Pillow 가 없으면 빈 목록."""
    try:
        import zxingcpp
        from PIL import Image
    except ImportError:
        return []
    img = Image.open(path).convert("L")
    found = [r.text for r in zxingcpp.read_barcodes(img)]
    # 작게 줄인 그림(멀리서 찍은 폰 흉내)도 읽혀야 한다
    small = img.resize((max(1, img.width // 6), max(1, img.height // 6)))
    found += [r.text for r in zxingcpp.read_barcodes(small)]
    return found


def decode_pdf(path: Path) -> list[str]:
    """PDF 첫 장을 150dpi·72dpi 로 그려 읽는다 — 인쇄소에 넘길 파일 자체가 읽히는지. pypdfium2 가 없으면 빈 목록."""
    try:
        import pypdfium2 as pdfium
        import zxingcpp
    except ImportError:
        return []
    page = pdfium.PdfDocument(str(path))[0]
    return [r.text for dpi in (150, 72) for r in zxingcpp.read_barcodes(page.render(scale=dpi / 72).to_pil())]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="결선 부스 QR 만들기")
    ap.add_argument("--out", type=Path, default=Path.home() / "meetings" / "2026-10-11_결선_QR")
    ap.add_argument("--error", default="q", choices=["m", "q", "h"], help="오류 정정 단계 (기본 q · 최소 m)")
    ap.add_argument("--pdf", action="store_true", help="이미 만든 HTML 로 A4 PDF·인쇄면 사진만 (playwright 필요)")
    ap.add_argument("--verify-only", action="store_true", help="만든 PNG 들을 다시 읽어 주소만 확인")
    a = ap.parse_args(argv)
    out: Path = a.out.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    png, svg_path, html = out / "chuckchuck_hi_qr_1024.png", out / "chuckchuck_hi_qr.svg", out / "chuckchuck_hi_qr_A4.html"
    pdf, shot = out / "chuckchuck_hi_qr_A4.pdf", out / "chuckchuck_hi_qr_A4_preview.png"

    if a.pdf:
        render_pdf(html, pdf, shot)
        print(f"PDF {pdf}\n인쇄면 사진 {shot}")
        return 0

    report: dict = {"url": URL, "made_at": datetime.now().isoformat(timespec="seconds")}
    if not a.verify_only:
        qr = make_qr(URL, a.error)
        matrix = [list(row) for row in qr.matrix]
        report.update({"version": qr.version, "error": qr.error, "border_modules": BORDER,
                       **write_png(matrix, png)})
        svg = svg_markup(qr)
        svg_path.write_text(svg, encoding="utf-8")
        write_print_html(svg, html)

    checks = {}
    for f in (png, shot):
        if f.exists():
            got = decode(f)
            checks[f.name] = {"read": sorted(set(got)), "ok": bool(got) and set(got) == {URL}}
    if pdf.exists():
        got = decode_pdf(pdf)
        if got:
            checks[pdf.name] = {"read": sorted(set(got)), "ok": set(got) == {URL}}
    report["decode"] = checks
    meta = out / "qr_report.json"
    old = json.loads(meta.read_text()) if meta.exists() and a.verify_only else {}
    meta.write_text(json.dumps({**old, **report}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    bad = [k for k, v in checks.items() if not v["ok"]]
    if bad:
        print(f"⚠ 다시 읽은 주소가 다르거나 못 읽었어요: {bad}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
