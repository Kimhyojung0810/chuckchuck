"""
/hi/stage 시안 A 캡처 실험실 (2026-10-13) — 390×844 첫 화면 · 연출 프레임(0.3/0.8/1.6/3.0초) · 근거 펼침 · 스크롤 뒤 · 움직임 줄이기 · 360폭 · 데스크톱 1280.

    LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu ../chuckchuck/.venv/bin/python etc/labs/hi_stage/capture.py --base http://127.0.0.1:9044

결과: etc/labs/hi_stage/out/<stamp>/*.png + report.json(콘솔 오류 · 겹침 · 터치 대상)
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1")
FLAGS = ["--enable-gpu-rasterization", "--ignore-gpu-blocklist", "--enable-unsafe-swiftshader"]

CHECK = """() => {
  const r = (s) => { const n = document.querySelector(s); if (!n) return null; const b = n.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.top), Math.round(b.right), Math.round(b.bottom)]; };
  const inter = (a, b) => a && b && a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
  const taps = [...document.querySelectorAll('a[href], button')].filter(e => e.offsetParent !== null && !e.closest('[hidden]') && !e.classList.contains('skip'))
    .map(e => { const b = e.getBoundingClientRect(); return { t: (e.textContent || e.getAttribute('aria-label') || '').trim().slice(0, 16), w: Math.round(b.width), h: Math.round(b.height) }; })
    .filter(x => x.w > 0 && (x.w < 44 || x.h < 44));
  return { vw: innerWidth, title: r('#hero-title'), verdicts: r('.verdicts'), judge: r('.judge'), bubble: r('.judge-bubble'), dock: r('.dock'),
           titleBelowFold: (r('#hero-title') || [0,0,0,0])[3] > innerHeight - 76,
           bubbleOverVerdicts: inter(r('.judge-bubble'), r('.verdicts')), smallTaps: taps,
           live: !!document.querySelector('.fig-live'),
           cpm: (document.querySelector('[data-f=cpm]') || {}).textContent, docW: document.documentElement.scrollWidth };
}"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:9044")
    ap.add_argument("--path", default="/hi/stage", help="/hi 도 같은 세트로 찍을 수 있다")
    ap.add_argument("--axe", default="", help="axe.min.js 경로 — 주면 첫 화면 · 시트 열림에서 axe 위반을 센다")
    a = ap.parse_args()
    out = HERE / "out" / (datetime.now().strftime("%Y%m%dT%H%M%S") + a.path.replace("/", "_"))
    out.mkdir(parents=True, exist_ok=True)
    rep: dict = {"errors": []}
    url = a.base + a.path
    axe_src = Path(a.axe).read_text(encoding="utf-8") if a.axe else ""

    def axe(pg, name):
        if not axe_src:
            return
        pg.add_script_tag(content=axe_src)
        v = pg.evaluate("async () => (await axe.run(document, {resultTypes: ['violations']})).violations.map(v => ({id: v.id, impact: v.impact, n: v.nodes.length, t: v.nodes.slice(0,3).map(n => n.target.join(' '))}))")
        rep.setdefault("axe", {})[name] = v
    with sync_playwright() as p:
        b = p.chromium.launch(args=FLAGS)

        def page(w, h, *, mobile=True, reduce=False, dpr=2):
            ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=dpr, is_mobile=mobile, has_touch=mobile,
                                user_agent=UA if mobile else None, reduced_motion="reduce" if reduce else "no-preference")
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and rep["errors"].append(m.text[:200]))
            pg.on("pageerror", lambda e: rep["errors"].append("pageerror: " + str(e)[:200]))
            return pg

        def at(pg, ms):
            now = pg.evaluate("performance.now()")
            if ms > now:
                pg.wait_for_timeout(ms - now)

        # 연출 프레임 — 페이지가 열린 때부터 잰 시각
        pg = page(390, 844)
        pg.goto(url, wait_until="commit")
        for ms, name in [(300, "anim-0.3s"), (800, "anim-0.8s"), (1600, "anim-1.6s"), (3000, "anim-3.0s")]:
            at(pg, ms + 60)
            pg.screenshot(path=str(out / f"{name}.png"))
        at(pg, 4200)
        pg.screenshot(path=str(out / "first_390.png"))
        rep["390"] = pg.evaluate(CHECK)
        axe(pg, "first_390")
        if pg.query_selector("#fig-hit"):
            pg.click("#fig-hit", position={"x": 60, "y": 200})
            pg.wait_for_timeout(500)
            pg.screenshot(path=str(out / "ground_390.png"))
            rep["ground"] = pg.evaluate("() => ({ open: !document.getElementById('ground').hidden, k: document.getElementById('ground-k').textContent, main: document.getElementById('ground-main').textContent })")
            axe(pg, "ground_390")
            pg.keyboard.press("Escape")
        pg.evaluate("scrollTo(0, innerHeight * 0.6)")
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(out / "scroll_mid_390.png"))
        pg.evaluate("scrollTo(0, document.getElementById('what').offsetTop - 40)")
        pg.wait_for_timeout(900)
        pg.screenshot(path=str(out / "scroll_what_390.png"))
        pg.screenshot(path=str(out / "full_390.png"), full_page=True)
        pg.context.close()

        # 인앱 브라우저(카카오톡) — 「내 자료로 직접 해 보기」 를 누르면 시트가 뜨고 뒤는 inert
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                            user_agent=UA + " KAKAOTALK 10.8.0")
        pg = ctx.new_page()
        pg.on("console", lambda m: m.type == "error" and rep["errors"].append(m.text[:200]))
        pg.on("pageerror", lambda e: rep["errors"].append("pageerror: " + str(e)[:200]))
        pg.goto(url, wait_until="networkidle")
        at(pg, 4200)
        pg.click("#own-link-1")
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(out / "inapp_sheet_390.png"))
        rep["inapp"] = pg.evaluate("() => ({ open: !document.getElementById('inapp').hidden, inert: [...document.body.children].filter(n => n.inert).map(n => n.className || n.tagName) })")
        axe(pg, "inapp_sheet_390")
        ctx.close()

        pg = page(390, 844, reduce=True)
        pg.goto(url, wait_until="networkidle")
        pg.wait_for_timeout(600)
        pg.screenshot(path=str(out / "reduced_390.png"))
        rep["reduced"] = pg.evaluate(CHECK)
        pg.context.close()

        pg = page(360, 640)
        pg.goto(url, wait_until="networkidle")
        at(pg, 4200)
        pg.screenshot(path=str(out / "first_360.png"))
        rep["360"] = pg.evaluate(CHECK)
        pg.context.close()

        pg = page(1280, 800, mobile=False, dpr=1)
        pg.goto(url, wait_until="networkidle")
        at(pg, 4200)
        pg.screenshot(path=str(out / "desktop_1280.png"))
        rep["1280"] = pg.evaluate(CHECK)
        pg.context.close()
        b.close()
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(out)
    print(json.dumps(rep, ensure_ascii=False)[:2500])


if __name__ == "__main__":
    main()
