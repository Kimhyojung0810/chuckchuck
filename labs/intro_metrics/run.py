"""
/hi 랜딩 지표 실험실 (2026-10-12) — 「취향 말고 잰 값으로」 고치려고 만든다.
393×852 아이폰 에뮬레이션 + CDP 쓰로틀(Fast 4G: RTT 165ms · 내려받기 9Mbps×0.9 · 올리기 1.5Mbps×0.9, CPU 4배 느리게)로
/hi 를 N번 새로 열어 LCP · CLS · 전송량 · 요청 수의 가운데 값을 잰다. 캐시는 매번 비운 새 컨텍스트.
그리고 쓰로틀 없이 히어로 낱말 수 · 360×640 에서 주 버튼이 스크롤 없이 보이나 · 가장 작은 터치 대상 ·
첫 화면에서 초록(브랜드)이 차지하는 넓이 % · 브랜드 색 대비(WCAG · APCA Lc)를 잰다.

    LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu .venv/bin/python labs/intro_metrics/run.py --base http://127.0.0.1:8987 --runs 3

결과: labs/intro_metrics/out/<stamp>/report.json + first_393.png
"""
from __future__ import annotations

import argparse
import colorsys
import io
import json
import statistics
from datetime import datetime
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1")
FAST_4G = {"offline": False, "latency": 165, "downloadThroughput": 9_000_000 * 0.9 / 8,
           "uploadThroughput": 1_500_000 * 0.9 / 8}

OBSERVE = """() => {
  window.__lcp = 0; window.__cls = 0; window.__lcpEl = '';
  new PerformanceObserver((l) => { for (const e of l.getEntries()) { window.__lcp = e.startTime;
    const n = e.element; window.__lcpEl = n ? (n.tagName + '.' + (n.className && n.className.baseVal === undefined ? n.className : '')).slice(0, 60) : ''; } })
    .observe({ type: 'largest-contentful-paint', buffered: true });
  new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; })
    .observe({ type: 'layout-shift', buffered: true });
  // 제목 · 주 버튼이 실제로 보이게(조상까지 곱한 불투명도 ≥ .99) 된 시각 — 크롬 LCP 는 투명한 글을 후보에서 빼서 연출에 가린 시간을 못 본다
  window.__vis = {};
  (function poll() {
    const now = performance.now();
    for (const [k, sel] of [['h1', '#hero-title'], ['cta', '#explore-btn']]) {
      if (window.__vis[k]) continue;
      const el = document.querySelector(sel); if (!el) continue;
      let o = 1, n = el; while (n && n.nodeType === 1) { o *= parseFloat(getComputedStyle(n).opacity); n = n.parentElement; }
      if (o >= 0.99) window.__vis[k] = Math.round(now);
    }
    if (now < 8000) requestAnimationFrame(poll);
  })();
}"""

STATIC = """() => {
  const hero = document.querySelector('.hero');
  const txt = [...hero.querySelectorAll('h1, p, a')].filter(n => !n.closest('[aria-hidden="true"]') && !n.classList.contains('fly-caption'))
    .map(n => n.innerText).join(' ');
  const words = txt.split(/\\s+/).filter(Boolean).length;
  const taps = [...document.querySelectorAll('a[href], button')]
    .filter(e => e.offsetParent !== null && !e.closest('[hidden]') && !e.classList.contains('skip'))
    .map(e => { const r = e.getBoundingClientRect(); return { t: (e.textContent || '').trim().slice(0, 20), w: Math.round(r.width), h: Math.round(r.height) }; })
    .filter(x => x.w > 0);
  const minH = taps.reduce((a, b) => (b.h < a.h ? b : a));
  const minW = taps.reduce((a, b) => (b.w < a.w ? b : a));
  const dock = document.querySelector('.dock .btn-primary').getBoundingClientRect();
  const own = document.getElementById('own-link-1').getBoundingClientRect();
  return { hero_words: words, hero_text: txt, min_tap_h: minH, min_tap_w: minW,
           cta_visible: dock.top >= 0 && dock.bottom <= innerHeight, cta_bottom: Math.round(dock.bottom),
           own_link_visible: own.bottom <= innerHeight - dock.height, own_link_bottom: Math.round(own.bottom), vh: innerHeight };
}"""


def lum(hexc: str) -> float:
    c = [int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def wcag(fg: str, bg: str) -> float:
    a, b = sorted((lum(fg), lum(bg)), reverse=True)
    return round((a + 0.05) / (b + 0.05), 2)


def apca(fg: str, bg: str) -> float:
    """APCA-W3 0.0.98G-4g Lc (글자 fg, 바탕 bg)."""
    def y(h):
        r, g, b = [(int(h[i:i + 2], 16) / 255) ** 2.4 for i in (1, 3, 5)]
        v = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
        return v if v > 0.022 else v + (0.022 - v) ** 1.414
    yt, yb = y(fg), y(bg)
    if abs(yb - yt) < 0.0005:
        return 0.0
    if yb > yt:
        s = (yb ** 0.56 - yt ** 0.57) * 1.14
        lc = 0 if s < 0.1 else s - 0.027
    else:
        s = (yb ** 0.65 - yt ** 0.62) * 1.14
        lc = 0 if s > -0.1 else s + 0.027
    return round(lc * 100, 1)


def accent_ratio(png: bytes) -> float:
    """첫 화면 픽셀 가운데 초록 계열(색상 95~175° · 채도 ≥ .30 · 명도 ≥ .25) 비율 %."""
    im = Image.open(io.BytesIO(png)).convert("RGB")
    im = im.resize((im.width // 3, im.height // 3))
    n = hit = 0
    for r, g, b in zip(*[iter(im.tobytes())] * 3):
        n += 1
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if 95 / 360 <= h <= 175 / 360 and s >= 0.30 and v >= 0.25:
            hit += 1
    return round(hit * 100 / n, 2)


def tokens(page) -> dict:
    return page.evaluate("""() => { const s = getComputedStyle(document.documentElement);
      const o = {}; for (const k of ['--brand','--brand-strong','--brand-weak','--navy','--canvas','--surface','--text-2','--text-3'])
        o[k] = s.getPropertyValue(k).trim(); return o; }""")


def throttled_run(b, base: str) -> dict:
    ctx = b.new_context(viewport={"width": 393, "height": 852}, device_scale_factor=3, is_mobile=True,
                        has_touch=True, user_agent=IPHONE_UA, locale="ko-KR")
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
    cdp.send("Network.emulateNetworkConditions", FAST_4G)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
    sizes: dict[str, int] = {}
    cdp.on("Network.loadingFinished", lambda e: sizes.__setitem__(e["requestId"], e.get("encodedDataLength", 0)))
    page.add_init_script("(" + OBSERVE + ")()")
    page.goto(f"{base}/hi", wait_until="load", timeout=90000)
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(4000)
    m = page.evaluate("({lcp: window.__lcp, cls: window.__cls, el: window.__lcpEl, vis: window.__vis})")
    ctx.close()
    return {"lcp_ms": round(m["lcp"]), "lcp_el": m["el"], "cls": round(m["cls"], 4),
            "h1_visible_ms": m["vis"].get("h1"), "cta_visible_ms": m["vis"].get("cta"),
            "kb": round(sum(sizes.values()) / 1024, 1), "requests": len(sizes)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8987")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    out = HERE / "out" / (datetime.now().strftime("%m%d_%H%M%S") + (("_" + a.tag) if a.tag else ""))
    out.mkdir(parents=True, exist_ok=True)
    rep: dict = {"base": a.base, "throttle": {"net": FAST_4G, "cpu": 4}, "runs": []}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for _ in range(a.runs):
            rep["runs"].append(throttled_run(b, a.base))
        for k in ("lcp_ms", "cls", "kb", "requests", "h1_visible_ms", "cta_visible_ms"):
            rep[k] = statistics.median(r[k] for r in rep["runs"])
        # 첫 화면(연출 끝난 뒤) — 초록 넓이
        ctx = b.new_context(viewport={"width": 393, "height": 852}, device_scale_factor=1, is_mobile=True,
                            has_touch=True, user_agent=IPHONE_UA, locale="ko-KR")
        page = ctx.new_page()
        page.goto(f"{a.base}/hi", wait_until="networkidle")
        page.wait_for_timeout(3500)
        png = page.screenshot()
        (out / "first_393.png").write_bytes(png)
        rep["accent_pct_393"] = accent_ratio(png)
        rep["static_393"] = page.evaluate(STATIC)
        tk = tokens(page)
        ctx.close()
        # 360×640 — 주 버튼이 스크롤 없이 보이나
        ctx = b.new_context(viewport={"width": 360, "height": 640}, device_scale_factor=2, is_mobile=True,
                            has_touch=True, user_agent=IPHONE_UA, locale="ko-KR")
        page = ctx.new_page()
        page.goto(f"{a.base}/hi", wait_until="networkidle")
        page.wait_for_timeout(3500)
        page.screenshot(path=str(out / "first_360x640.png"))
        rep["static_360x640"] = page.evaluate(STATIC)
        ctx.close()
        b.close()
    pairs = [("#FFFFFF", "--brand"), ("#FFFFFF", "--brand-strong"), ("--brand-strong", "#FFFFFF"), ("--brand-strong", "--canvas"),
             ("--brand-ink", "#FFFFFF"), ("--brand-ink", "--brand-weak"), ("--brand-ink", "--brand-tint"), ("--navy", "--brand-weak"),
             ("--brand-strong", "--brand-weak"), ("--mint", "--navy"), ("--text-2", "#FFFFFF"), ("--text-3", "#FFFFFF")]
    res = tk.get
    rep["tokens"] = tk
    rep["contrast"] = []
    for fg, bg in pairs:
        f = res(fg, fg) if fg.startswith("--") else fg
        g = res(bg, bg) if bg.startswith("--") else bg
        if len(f) == 7 and len(g) == 7:
            rep["contrast"].append({"fg": f"{fg} {f}", "bg": f"{bg} {g}", "wcag": wcag(f, g), "apca_lc": apca(f, g)})
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    s3, s6 = rep["static_393"], rep["static_360x640"]
    print(json.dumps({k: rep[k] for k in ("lcp_ms", "h1_visible_ms", "cta_visible_ms", "cls", "kb", "requests", "accent_pct_393")}, ensure_ascii=False))
    print("runs", rep["runs"])
    print("hero_words", s3["hero_words"], "| 360x640 cta_visible", s6["cta_visible"], "own_link_visible", s6["own_link_visible"],
          "| min tap h", s3["min_tap_h"], "w", s3["min_tap_w"])
    for c in rep["contrast"]:
        print("contrast", c)
    print(out)


if __name__ == "__main__":
    main()
