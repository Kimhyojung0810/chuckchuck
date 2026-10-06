#!/usr/bin/env python3
"""
덱 고르기 카드(/booth/qa · /rehearsal)의 표지와 모든 장의 그림 — 각 덱 미리보기 PDF 를 WebP 로 떠 둔다.

iPad Safari 에서 pdf.js 로 그린 표지 · 슬라이드가 안 뜨는 일이 있어서(10-06), 화면은 이 그림을 먼저 쓰고
그림이 없는 덱만 예전처럼 pdf.js 로 그린다 (js/booth_qa.js BOOTH_DECK_COVERS · BOOTH_DECK_SLIDES).

  LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu \\
    .venv/bin/python scripts/render_deck_covers.py --base http://127.0.0.1:8800

하는 일
  1. 브리지의 /api/v1/dev/decks 에서 덱마다 파싱본 세션을 찾고 /api/v1/preview-pdf 로 PDF 를 받는다
     (DEV_ROUTES=1 인 개발 브리지가 떠 있어야 한다)
  2. 헤드리스 Chromium 에서 저장소의 pdf.js(js/vendor/pdfjs)로 1장(표지, 가로 WIDTH px)과
     모든 장(가로 SLIDE_WIDTH px)을 그린다
  3. 표지는 demo/YEHS_demo/assets/deck-covers/<slug>.webp, 장은 assets/deck-slides/<slug>/<n>.webp 로 저장하고,
     js/booth_qa.js 의 `// <deck-covers>` ~ `// </deck-covers>` 사이 표(BOOTH_DECK_COVERS · BOOTH_DECK_SLIDES)를 다시 쓴다.
     장 그림은 파싱본 파일 이름 · 장 수 · 1장 제목이 같을 때만 쓴다 (applySlideDoc → bqStaticSlidesFor)
     (주소에 내용 해시 ?v= 를 붙여서 그림을 바꾸면 캐시도 같이 바뀐다)
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo" / "YEHS_demo"
OUT_DIR = DEMO / "assets" / "deck-covers"
SLIDES_DIR = DEMO / "assets" / "deck-slides"
BOOTH_QA_JS = DEMO / "js" / "booth_qa.js"
DECKS_JSON = ROOT / "ppt" / "decks.json"

WIDTH = 800
QUALITY = 80
SLIDE_WIDTH = 960
SLIDE_QUALITY = 78

#: 덱 폴더 이름(한글) → 파일 이름. A·B 버전은 자료(pptx)가 같아서 같은 그림을 쓴다.
SLUGS = {
    "급속충전배터리열화A": "battery-fastcharge",
    "급속충전배터리열화B": "battery-fastcharge",
    "미세플라스틱물벼룩번식A": "microplastic-daphnia",
    "미세플라스틱물벼룩번식B": "microplastic-daphnia",
    "배달앱별점인플레이션A": "delivery-rating",
    "배달앱별점인플레이션B": "delivery-rating",
    "수면발표": "sleep",
    "수익률격차": "investor-gap",
    "focus_notification": "focus-notification",
}
#: 표지를 떠 둘 묶음 (ppt/decks.json groups) — held(검증용)는 화면에 안 나온다
GROUPS = ("booth", "demo")

PAGE_JS = """
async ([pdfB64, coverWidth, slideWidth]) => {
  const bin = atob(pdfB64);
  const data = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) data[i] = bin.charCodeAt(i);
  const pdf = await pdfjsLib.getDocument({ data }).promise;
  const shot = async (no, width) => {
    const page = await pdf.getPage(no);
    const base = page.getViewport({ scale: 1 });
    const vp = page.getViewport({ scale: width / base.width });
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(vp.width);
    canvas.height = Math.round(vp.height);
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    await page.render({ canvasContext: ctx, viewport: vp }).promise;
    return { png: canvas.toDataURL('image/png'), w: canvas.width, h: canvas.height };
  };
  const cover = await shot(1, coverWidth);
  const slides = [];
  for (let no = 1; no <= pdf.numPages; no++) slides.push(await shot(no, slideWidth));
  const out = { ...cover, pages: pdf.numPages, slides };
  await pdf.destroy();
  return out;
}
"""


def slug_for(key: str) -> str:
    return SLUGS.get(key) or "deck-" + hashlib.sha1(key.encode()).hexdigest()[:8]


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 — 로컬 브리지
        return r.read()


def wanted_keys() -> list[str]:
    cfg = json.loads(DECKS_JSON.read_text(encoding="utf-8"))
    decks = cfg.get("decks", {})
    keys = [k for k, v in decks.items() if (v or {}).get("group") in GROUPS]
    return sorted(set(keys) | set(SLUGS))


def webp(png_data_url: str, quality: int) -> bytes:
    from PIL import Image

    png = base64.b64decode(png_data_url.split(",", 1)[1])
    buf = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGB").save(buf, "WEBP", quality=quality, method=6)
    return buf.getvalue()


def save(path: Path, data: bytes) -> str:
    """파일로 쓰고 데모 폴더 기준 주소 + 내용 해시(?v=) 를 돌려준다 — 브리지가 해시가 맞으면 1년 캐시한다"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f"{path.relative_to(DEMO).as_posix()}?v=h{hashlib.sha1(data).hexdigest()[:10]}"


def first_title(base: str, sid: str) -> str:
    """파싱본 1장 제목(slides[0].title) — 같은 파일 이름 · 장 수의 다른 자료에 그림을 잘못 붙이지 않게 대조한다"""
    body = json.loads(get(f"{base}/api/v1/cached-slidedoc?session_id={urllib.parse.quote(sid)}"))
    doc = body.get("slidedoc", body) if isinstance(body, dict) else {}
    slides = doc.get("slides") or []
    return str((slides[0] or {}).get("title") or "") if slides else ""


def render_one(page, base: str, sid: str, slug: str, file_name: str) -> dict:
    pdf = get(f"{base}/api/v1/preview-pdf?session_id={urllib.parse.quote(sid)}")
    got = page.evaluate(PAGE_JS, [base64.b64encode(pdf).decode(), WIDTH, SLIDE_WIDTH])
    cover = webp(got["png"], QUALITY)
    out = {"src": save(OUT_DIR / f"{slug}.webp", cover), "w": got["w"], "h": got["h"], "pages": got["pages"],
           "slug": slug, "file": file_name, "first": first_title(base, sid), "slides": [], "bytes": len(cover)}
    old = SLIDES_DIR / slug
    if old.is_dir():
        for f in old.glob("*.webp"):
            f.unlink()
    for no, shot in enumerate(got["slides"], start=1):
        data = webp(shot["png"], SLIDE_QUALITY)
        out["slides"].append(save(old / f"{no}.webp", data))
        out["bytes"] += len(data)
        out["sw"], out["sh"] = shot["w"], shot["h"]
    print(f"  {slug}: 표지 {got['w']}x{got['h']} {len(cover) // 1024}KB · 장 {got['pages']}개 "
          f"{out['sw']}x{out['sh']} · 합계 {out['bytes'] // 1024}KB  ← {file_name}")
    return out


def render(base: str) -> dict[str, dict]:
    from playwright.sync_api import sync_playwright

    rows = json.loads(get(f"{base}/api/v1/dev/decks")).get("decks", [])
    by_key = {str(r.get("key") or ""): r for r in rows}
    table: dict[str, dict] = {}
    done: dict[str, dict] = {}   # slug → 그린 결과 (A·B 가 같은 그림)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("<!doctype html><html><body></body></html>")
        page.add_script_tag(path=str(DEMO / "js" / "vendor" / "pdfjs" / "pdf.min.js"))
        worker = (DEMO / "js" / "vendor" / "pdfjs" / "pdf.worker.min.js").read_text(encoding="utf-8")
        page.evaluate(
            "(src) => { pdfjsLib.GlobalWorkerOptions.workerSrc = URL.createObjectURL(new Blob([src], {type: 'text/javascript'})); }",
            worker,
        )
        for key in wanted_keys():
            row = by_key.get(key)
            sid = row and row.get("cached_session_id")
            if not sid:
                print(f"  건너뜀 {key}: 파싱본 세션이 없어요 (/test/qa 에서 한 번 열어 두면 생겨요)", file=sys.stderr)
                continue
            slug = slug_for(key)
            if slug not in done:
                done[slug] = render_one(page, base, sid, slug, str(row.get("deck") or ""))
            table[key] = done[slug]
        browser.close()
    total = sum(d["bytes"] for d in done.values())
    print(f"  합계 {len(done)}개 자료 · {total // 1024}KB")
    return table


def js_str(v: str) -> str:
    return json.dumps(unicodedata.normalize("NFC", v), ensure_ascii=False)


def write_table(table: dict[str, dict]) -> None:
    lines = ["// <deck-covers> scripts/render_deck_covers.py 가 다시 쓴다 — 손으로 고치지 말고 스크립트를 다시 돌린다",
             "/** 덱 고르기 카드의 표지 그림(미리보기 PDF 1장). 없는 덱만 pdf.js 로 그린다 — iPad 에서 pdf.js 표지가 안 떴다 (10-06) */",
             "const BOOTH_DECK_COVERS = {"]
    for key in sorted(table, key=lambda k: (table[k]["src"], k)):
        c = table[key]
        lines.append(f"  {js_str(key)}: {{ src: '{c['src']}', w: {c['w']}, h: {c['h']}, pages: {c['pages']}, slides: '{c['slug']}' }},")
    lines += ["};",
              "/** 장마다 미리 찍은 그림 — 파싱본의 파일 이름 · 장 수 · 1장 제목이 같을 때만 쓴다 (bqStaticSlidesFor). 없으면 pdf.js */",
              "const BOOTH_DECK_SLIDES = {"]
    seen = {}
    for c in table.values():
        seen.setdefault(c["slug"], c)
    for slug in sorted(seen):
        c = seen[slug]
        srcs = ",\n".join(f"    '{x}'" for x in c["slides"])
        lines.append(f"  {js_str(slug)}: {{ file: {js_str(c['file'])}, first: {js_str(c['first'])}, w: {c['sw']}, h: {c['sh']}, pages: [\n{srcs},\n  ] }},")
    lines += ["};", "// </deck-covers>"]
    block = "\n".join(lines)
    src = BOOTH_QA_JS.read_text(encoding="utf-8")
    pat = re.compile(r"// <deck-covers>.*?// </deck-covers>", re.S)
    if not pat.search(src):
        sys.exit("js/booth_qa.js 에 // <deck-covers> ~ // </deck-covers> 표시가 없어요")
    BOOTH_QA_JS.write_text(pat.sub(lambda _m: block, src, count=1), encoding="utf-8")
    print(f"  js/booth_qa.js BOOTH_DECK_COVERS {len(table)}개 덱 · BOOTH_DECK_SLIDES {len(seen)}개 자료")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--base", default="http://127.0.0.1:8800", help="DEV_ROUTES=1 개발 브리지 주소")
    args = ap.parse_args()
    table = render(args.base.rstrip("/"))
    if not table:
        sys.exit("그린 표지가 없어요")
    write_table(table)


if __name__ == "__main__":
    main()
