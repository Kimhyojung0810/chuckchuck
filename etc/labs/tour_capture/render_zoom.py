"""
투어 「자료 크게 보기」 용 장 그림 — 부스 덱 PPTX 를 가로 1920px WebP 로 뜬다 (2026-10-12, layout-touch-a11y-r2-3).

    LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu \\
      .venv/bin/python etc/labs/tour_capture/render_zoom.py            # → assets/deck-slides/<덱>/<n>-2x.webp

왜 — 화면 안 자료 칸 그림(<n>.webp)은 가로 960px 이라 「2배로 보기」(폰 폭 × 2 = 720~824 CSS px)를 DPR 3 폰에서 보면
2160 기기 픽셀로 2.25배 늘어나 표 · 그래프 글자가 번졌다. 크게 보기만 이 그림을 쓰고, 없으면 960px 그림으로 돌아간다(js/tour.js openZoom).

어떻게 — PPTX 는 git 에 없다(capture.ppt_root: 이 작업 폴더에 없으면 주 작업 폴더의 main/decks/). LibreOffice(soffice)로 PDF 를 만들고
etc/scripts/render_deck_covers.py 와 같은 방법(저장소 pdf.js · 헤드리스 Chromium)으로 그린다. 장 수가 지금 <n>.webp 와 다르면 쓰지 않는다.
과금 · 브리지 없음. 파일 이름은 공개 허용 목록(assets/deck-slides/{이름}/{이름}.webp)에 맞춰 「-2x」.
"""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEMO = ROOT / "main" / "web"
SLIDES = DEMO / "assets" / "deck-slides"
sys.path.insert(0, str(HERE))
from capture import BOOTH_DECKS, ppt_root  # noqa: E402

ZOOM_WIDTH = 1920
QUALITY = 0.8

PAGE_JS = """
async ([pdfB64, width, quality]) => {
  const bin = atob(pdfB64);
  const data = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) data[i] = bin.charCodeAt(i);
  const pdf = await pdfjsLib.getDocument({ data }).promise;
  const out = [];
  for (let no = 1; no <= pdf.numPages; no++) {
    const page = await pdf.getPage(no);
    const vp = page.getViewport({ scale: width / page.getViewport({ scale: 1 }).width });
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(vp.width);
    canvas.height = Math.round(vp.height);
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    await page.render({ canvasContext: ctx, viewport: vp }).promise;
    out.push(canvas.toDataURL('image/webp', quality));
  }
  await pdf.destroy();
  return out;
}
"""


def to_pdf(pptx: Path, tmp: Path) -> Path:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise SystemExit("soffice(LibreOffice)가 없어요")
    subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(tmp), str(pptx)],
                   check=True, capture_output=True, timeout=240)
    return tmp / (pptx.stem + ".pdf")


def main() -> int:
    from playwright.sync_api import sync_playwright

    root = ppt_root()
    with tempfile.TemporaryDirectory() as td, sync_playwright() as p:
        tmp = Path(td)
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("<!doctype html><html><body></body></html>")
        page.add_script_tag(path=str(DEMO / "js" / "vendor" / "pdfjs" / "pdf.min.js"))
        worker = (DEMO / "js" / "vendor" / "pdfjs" / "pdf.worker.min.js").read_text(encoding="utf-8")
        page.evaluate("(src) => { pdfjsLib.GlobalWorkerOptions.workerSrc = URL.createObjectURL(new Blob([src], {type: 'text/javascript'})); }", worker)
        for key, slug in BOOTH_DECKS.items():
            pptx = sorted((root / key).glob("*.pptx"))
            if not pptx:
                print(f"  건너뜀 {key}: PPTX 가 없어요", file=sys.stderr)
                continue
            pdf = to_pdf(pptx[0], tmp)
            shots = page.evaluate(PAGE_JS, [base64.b64encode(pdf.read_bytes()).decode(), ZOOM_WIDTH, QUALITY])
            have = sorted(SLIDES.glob(f"{slug}/[0-9].webp")) + sorted(SLIDES.glob(f"{slug}/[0-9][0-9].webp"))
            if len(shots) != len(have):
                print(f"  건너뜀 {slug}: 장 수가 달라요 (PPTX {len(shots)} · 지금 그림 {len(have)})", file=sys.stderr)
                continue
            total = 0
            for no, url in enumerate(shots, start=1):
                data = base64.b64decode(url.split(",", 1)[1])
                (SLIDES / slug / f"{no}-2x.webp").write_bytes(data)
                total += len(data)
            print(f"  {slug}: {len(shots)}장 · {total // 1024}KB")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
