"""
모바일 체험 투어 실험실 — #/tour/* 를 폰 세로 네 폭(360 · 375 · 393 · 412)으로 헤드리스 크롬에 태워 단계마다 찍는다.

이 서버(VMware VM)엔 폰이 없다. 그래서 모바일 에뮬레이션(터치 · DPR · UA · is_mobile)으로 열고, 장 넘기기 밀기는
CDP Input.dispatchTouchEvent 로 진짜 터치 사슬(touchStart → touchMove… → touchEnd)을 흘린다 — 마우스 클릭으로는
touch-action · pointercancel 사고(10-08 public-rh)를 못 잡는다.

    .venv/bin/python etc/labs/tour_flow/run.py --base http://127.0.0.1:8986
    .venv/bin/python etc/labs/tour_flow/run.py --base http://127.0.0.1:8986 --widths 375 --inapp kakao   # 카카오톡 UA → 끝 화면 시트

투어는 녹화 응답만 재생하므로 과금이 없다(/api/ 요청은 퍼널 신호 POST /api/v1/tour/event 하나뿐이어야 한다 — report 가 센다).
결과: etc/labs/tour_flow/out/<stamp>/<폭>_<단계>.png (+ _full.png 는 본문 전체 높이) + report.json
  · overflow: 창보다 오른쪽으로 삐져나간 요소(자료 미리 보기 띠 안쪽은 뺀다)
  · small_targets: 44px 보다 작은 누를 곳
  · cta_visible: 아래 고정 주 버튼이 화면 안에 다 보이는가
  · swipe: 밀기 전후 장 번호 · reload/back: 새로 고침 · 뒤로 가기 뒤 단계와 고른 답이 남는가
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

UA = {
    "ios": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "android": "Mozilla/5.0 (Linux; Android 14; SM-S921N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36",
}
INAPP_SUFFIX = {
    "kakao": " KAKAOTALK 10.8.5",
    "naver": " NAVER(inapp; search; 2000; 12.6.3)",
    "instagram": " Instagram 350.0.0.0.0",
}
# 폭 → (높이, DPR, 플랫폼) — 갤럭시 S24 · 아이폰 SE(가장 낮은 화면) · 아이폰 15 · 픽셀 8 프로
DEVICES = {
    360: (780, 3, "android"),
    375: (667, 2, "ios"),
    393: (852, 3, "ios"),
    412: (915, 2.625, "android"),
}

CHECK_JS = """() => {
  const W = innerWidth, H = innerHeight;
  const root = document.getElementById('tourStage');
  if (!root) return { error: 'no #tourStage' };
  const vis = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const over = [];
  root.querySelectorAll('*').forEach((el) => {
    if (el.closest('.tour-strip') || el.closest('.tp-track') || el.closest('.tour-sheet-wrap:not(.is-open)')) return;   // 안쪽 스크롤 · 잘라 낸 장은 페이지를 안 민다
    const r = el.getBoundingClientRect();
    if (r.width && (r.right > W + 1 || r.left < -1)) over.push(`${el.tagName.toLowerCase()}.${String(el.className).slice(0, 40)} ${Math.round(r.left)}..${Math.round(r.right)}`);
  });
  const small = [];
  root.querySelectorAll('button, a[href], input, label.tour-deck').forEach((el) => {
    if (!vis(el) || (el.tagName === 'INPUT' && el.type === 'radio')) return;
    const r = el.getBoundingClientRect();
    if (r.width < 44 || r.height < 44) small.push(`${el.tagName.toLowerCase()}[${(el.textContent || el.getAttribute('aria-label') || el.className).trim().slice(0, 24)}] ${Math.round(r.width)}x${Math.round(r.height)}`);
  });
  const foot = root.querySelector('[data-tour-foot]');
  const fr = foot && !foot.hidden ? foot.getBoundingClientRect() : null;
  const body = root.querySelector('[data-tour-body]');
  return {
    hash: location.hash, screen: root.dataset.screen, tone: root.dataset.tone,
    page_scroll_w: document.scrollingElement.scrollWidth, vw: W, vh: H,
    overflow: over.slice(0, 12), small_targets: small,
    cta_visible: fr ? (fr.top >= 0 && fr.bottom <= H + 0.5) : null,
    body_scroll_h: body ? body.scrollHeight : 0, body_client_h: body ? body.clientHeight : 0,
    slide_no: (root.querySelector('[data-no-label]') || {}).textContent || null,
    chip: (root.querySelector('[data-chip]') || {}).textContent || null,
    title: (root.querySelector('h1') || {}).textContent || null,
  };
}"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8986")
    ap.add_argument("--widths", default="360,375,393,412")
    ap.add_argument("--inapp", default="", choices=["", *INAPP_SUFFIX])
    ap.add_argument("--full", action="store_true", help="본문 전체 높이 사진도 찍는다")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    stamp = datetime.now().strftime("%m%d_%H%M%S")
    out = OUT / stamp
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"base": args.base, "inapp": args.inapp, "devices": {}}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for w in [int(x) for x in args.widths.split(",") if x]:
            h, dpr, plat = DEVICES[w]
            ua = UA[plat] + INAPP_SUFFIX.get(args.inapp, "")
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=dpr,
                                      is_mobile=True, has_touch=True, user_agent=ua, locale="ko-KR")
            page = ctx.new_page()
            cdp = ctx.new_cdp_session(page)
            rep: dict = {"console": [], "api": [], "steps": {}, "http_404": []}
            page.on("response", lambda r, rp=rep: rp["http_404"].append(r.url.split(args.base)[-1]) if r.status == 404 else None)
            page.on("console", lambda m, r=rep: r["console"].append(f"{m.type}: {m.text}"[:240]) if m.type in ("error", "warning") else None)
            page.on("pageerror", lambda e, r=rep: r["console"].append(f"pageerror: {e}"[:240]))
            page.on("request", lambda q, r=rep: r["api"].append(f"{q.method} {q.url.split('/api/')[-1]}") if "/api/" in q.url else None)

            def check(tag: str) -> dict:
                info = page.evaluate(CHECK_JS)
                rep["steps"][tag] = info
                return info

            def shot(tag: str, full: bool = False) -> None:
                page.wait_for_timeout(350)
                check(tag)
                page.screenshot(path=str(out / f"{w}_{tag}.png"))
                if full or args.full:
                    sh = page.evaluate("() => { const b = document.querySelector('[data-tour-body]'); return b ? b.scrollHeight - b.clientHeight : 0; }")
                    if sh > 4:
                        page.set_viewport_size({"width": w, "height": h + sh})
                        page.wait_for_timeout(250)
                        page.screenshot(path=str(out / f"{w}_{tag}_full.png"))
                        page.set_viewport_size({"width": w, "height": h})
                        page.wait_for_timeout(150)

            def tap(sel: str) -> None:
                page.locator(sel).first.tap()
                page.wait_for_timeout(120)

            def swipe(sel: str, dx: int, dy: int = 0) -> None:
                box = page.locator(sel).first.bounding_box()
                x0, y0 = box["x"] + box["width"] * 0.6, box["y"] + box["height"] * 0.5
                cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": y0}]})
                for i in range(1, 9):
                    cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x0 + dx * i / 8, "y": y0 + dy * i / 8}]})
                    page.wait_for_timeout(16)
                cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
                page.wait_for_timeout(380)

            try:
                page.goto(f"{args.base}/tour", wait_until="load")
                page.wait_for_selector("#tourStage[data-screen='intro']", timeout=15000)
                shot("1_intro", full=True)
                tap("[data-next]")
                page.wait_for_selector("#tourStage[data-screen='deck']")
                shot("2_deck", full=True)
                tap("[data-next]")
                page.wait_for_selector("#tourStage[data-screen='present']")
                page.wait_for_timeout(1600)
                shot("3_present_play")
                # 밀어서 다음 장(왼쪽으로) — 몸짓이 pointercancel 로 새지 않는지
                tap("[data-play]")   # 멈추고 민다(재생이 장을 바꾸지 않게)
                before = check("3_present_before_swipe")["slide_no"]
                swipe("[data-stage]", -150, 14)   # 손가락이 살짝 세로로 흔들린 밀기
                after = check("3_present_after_swipe")["slide_no"]
                swipe("[data-stage]", 150, -10)
                back = check("3_present_after_swipe_back")["slide_no"]
                rep["swipe"] = {"before": before, "after_left": after, "after_right": back}
                # 코칭 칩이 뜬 순간(46초 「조금 빨라요」) 으로 끌어 놓고 찍는다
                page.evaluate("() => { const s = document.querySelector('[data-seek]'); s.value = '47'; s.dispatchEvent(new Event('input', { bubbles: true })); }")
                shot("3_present_chip")
                tap("[data-next]")
                page.wait_for_selector("#tourStage[data-screen='analysis']")
                page.wait_for_timeout(500)
                shot("4_analysis_reveal")
                page.wait_for_timeout(1700)
                shot("4_analysis", full=True)
                # 뒤로 가기(브라우저) → 발표, 다시 앞으로
                page.go_back()
                page.wait_for_selector("#tourStage[data-screen='present']")
                rep["back"] = check("back_to_present")["hash"]
                page.go_forward()
                page.wait_for_selector("#tourStage[data-screen='analysis']")
                rep["reveal_once"] = page.locator("[data-reveal]").count() == 0
                tap("[data-next]")
                page.wait_for_selector("#tourStage[data-screen='qa']")
                shot("5_qa1")
                tap("[data-pick='good']")
                page.wait_for_timeout(500)
                shot("5_qa1_good", full=True)
                tap("[data-pick='rough']")
                page.wait_for_timeout(500)
                shot("5_qa1_rough", full=True)
                tap("[data-next]")
                page.wait_for_selector("#tourStage[data-screen='qa']")
                tap("[data-pick='rough']")
                page.wait_for_timeout(400)
                # 새로 고침해도 그 질문 · 고른 답이 남는가
                page.reload(wait_until="load")
                page.wait_for_selector("#tourStage[data-screen='qa'] [data-verdict]", timeout=15000)
                rep["reload"] = check("5_qa2_after_reload")["hash"]
                shot("5_qa2_rough")
                tap("[data-next]")
                page.wait_for_timeout(300)
                tap("[data-pick='good']")
                page.wait_for_timeout(400)
                shot("5_qa3_good")
                tap("[data-next]")
                page.wait_for_selector("#tourStage[data-screen='report']")
                shot("6_report", full=True)
                tap("[data-next]")
                page.wait_for_selector("#tourStage[data-screen='done']")
                shot("7_done")
                tap("[data-real]")
                page.wait_for_timeout(600)
                if args.inapp:
                    shot("8_sheet")
                    rep["sheet"] = page.locator(".tour-sheet[role='dialog']").count()
                else:
                    page.wait_for_timeout(800)
                    rep["real_hash"] = page.evaluate("location.hash")
                    rep["tour_layer_gone"] = page.locator("#tourStage").count() == 0
            except Exception as e:   # 어디서 멈췄는지 사진으로 남긴다
                rep["error"] = f"{type(e).__name__}: {e}"[:400]
                page.screenshot(path=str(out / f"{w}_error.png"))
            report["devices"][str(w)] = rep
            ctx.close()
        browser.close()

    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    for w, rep in report["devices"].items():
        bad = {k: v for k, v in rep["steps"].items() if v.get("overflow") or v.get("small_targets") or v.get("cta_visible") is False
               or v.get("page_scroll_w", 0) > v.get("vw", 0)}
        print(f"[{w}] error={rep.get('error')} swipe={rep.get('swipe')} back={rep.get('back')} reload={rep.get('reload')} "
              f"reveal_once={rep.get('reveal_once')} api={sorted(set(rep['api']))} console={len(rep['console'])} 404={sorted(set(rep['http_404']))}")
        for k, v in bad.items():
            print(f"   ! {k}: overflow={v.get('overflow')[:3]} small={v.get('small_targets')[:5]} cta={v.get('cta_visible')} sw={v.get('page_scroll_w')}")
        for c in rep["console"][:6]:
            print("   console:", c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
