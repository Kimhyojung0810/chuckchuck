"""
부스 모바일 한 바퀴 실험실 (2026-10-12) — QR 을 찍은 폰이 따라가는 길 전체를 폰 세로 네 폭으로 헤드리스 크롬에 태워 찍는다.

    /hi 첫 화면 → 팀원 카드 한 장씩 → 「척척발표 살펴보기」 → #/tour 시작 → 자료 → 발표(터치 밀기) → 분석
    → 질문(잘 답한 답 · 엉성한 답, 질문 수만큼) → 리포트 → 끝 → 「내 자료로 직접 해 보기」 → 「팀 소개로 돌아가기」(/hi)

이 서버(VMware VM)엔 폰이 없다. 모바일 에뮬레이션(터치 · DPR · UA · is_mobile)으로 열고, 누르기는 tap(터치),
장 넘기기는 CDP Input.dispatchTouchEvent 로 진짜 터치 사슬을 흘린다(10-08 pan-y → pointercancel 사고를 잡으려고).
사진은 사람이 Read 로 직접 본다 — 이 도구는 「어디서 무엇이 깨졌나」 표를 같이 남길 뿐이다.

    .venv/bin/python labs/mobile_tour/run.py 8992                    # 360 · 375 · 393 · 412 × 기본 UA(안드로이드 크롬 · iOS 사파리)
    .venv/bin/python labs/mobile_tour/run.py 8992 --ua kakao         # 카카오톡 인앱 UA — 끝 화면에서 바깥 브라우저 안내 시트
    .venv/bin/python labs/mobile_tour/run.py 8992 --widths 375 --deck battery-fastcharge

브리지는 팀 쿠키 없이(DEMO_DEV_ROUTES=0) 띄운 공개 모드로 본다 — 공개 방문자에게 404 가 나는 파일을 잡으려고.
투어는 녹화 응답만 재생하므로 과금이 없다. /api/ 요청은 퍼널 신호 POST /api/v1/tour/event 와 앱 첫 GET v1/team 뿐이어야 한다.

결과: labs/mobile_tour/out/<시각>/
  <ua>_<폭>/NN_<화면>.png                — 화면마다 한 장 (본문이 길면 _full.png 도)
  report.json                            — 폭마다 단계별 측정 · 콘솔 오류 · 실패 요청 · 가로 넘침 · 작은 누를 곳 · 퍼널 신호
  종료 코드 0 = 문제 없음, 1 = 문제 있음(요약을 표준 출력에)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

UA_BASE = {
    "ios": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "android": "Mozilla/5.0 (Linux; Android 14; SM-S921N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36",
}
INAPP_SUFFIX = {"kakao": " KAKAOTALK 10.8.5", "naver": " NAVER(inapp; search; 2000; 12.6.3)", "instagram": " Instagram 350.0.0.0.0"}
# 폭 → (보이는 높이, DPR, 플랫폼) — 갤럭시 S24 · 아이폰 SE(가장 낮은 화면) · 아이폰 15 · 픽셀 8 프로
DEVICES = {360: (740, 3, "android"), 375: (667, 2, "ios"), 393: (760, 3, "ios"), 412: (820, 2.625, "android")}
MIN_TARGET = 44
#: 이 VM 의 크롬 헤드리스는 libasound.so.2 가 없어 못 뜬다 — labs/intro_flow 와 같은 자리에 풀어 둔 라이브러리를 쓴다(있으면)
PW_LIBS = Path(os.environ.get("PW_LIBS", "/tmp/pwlibs/usr/lib/x86_64-linux-gnu"))
#: 투어 동안 불러도 되는 API — 퍼널 신호 · 앱 첫 팀 확인 · 연결 감시(conn_watch.js 15초 health). 과금 경로는 하나도 없어야 한다
OK_API = ("POST /api/v1/tour/event", "GET /api/v1/team", "GET /api/health")
#: 공개 방문자에게 원래 404 인 요청(퍼널 계약상 무시) — 없음. 여기 넣기 전에 진짜 무시해도 되는지 먼저 따진다.
ALLOWED_FAIL: tuple[str, ...] = ()

#: 화면 하나를 잰다 — 가로 넘침(안쪽 가로 스크롤 칸은 뺀다) · 작은 누를 곳 · 아래 고정 주 버튼이 다 보이는가
MEASURE_JS = """() => {
  const W = innerWidth, H = innerHeight;
  const vis = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && el.closest('[hidden]') === null; };
  const scroller = (el) => { for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX; if (ox === 'auto' || ox === 'scroll' || ox === 'hidden' || ox === 'clip') return true; } return false; };
  const over = [];
  document.querySelectorAll('body *').forEach((el) => {
    if (!vis(el) || scroller(el)) return;
    const r = el.getBoundingClientRect();
    if (r.right > W + 1 || r.left < -1) over.push(`${el.tagName.toLowerCase()}.${String(el.className).slice(0, 32)} ${Math.round(r.left)}..${Math.round(r.right)}`);
  });
  const small = [];
  document.querySelectorAll('button, a[href], input:not([type=radio]):not([type=checkbox]), label.tour-deck, [role=button]').forEach((el) => {
    if (!vis(el)) return;
    const r = el.getBoundingClientRect();
    if (r.bottom < 0 || r.top > H) return;   // 지금 화면 밖은 그 화면을 찍을 때 잰다
    if (r.width < MIN || r.height < MIN) small.push(`${el.tagName.toLowerCase()}[${(el.getAttribute('aria-label') || el.textContent || el.className).trim().replace(/\\s+/g, ' ').slice(0, 22)}] ${Math.round(r.width)}x${Math.round(r.height)}`);
  });
  const stage = document.getElementById('tourStage');
  const cta = stage ? stage.querySelector('[data-tour-foot]:not([hidden]) .tour-cta') : document.querySelector('.dock .btn-primary');
  const cr = cta ? cta.getBoundingClientRect() : null;
  return {
    url: location.pathname + location.hash, screen: stage ? stage.dataset.screen : 'hi',
    vw: W, vh: H, page_scroll_w: document.scrollingElement.scrollWidth,
    hscroll: document.scrollingElement.scrollWidth > W + 1, overflow: over.slice(0, 10), small_targets: small.slice(0, 10),
    cta: cta ? (cta.textContent || '').trim().slice(0, 24) : null,
    cta_visible: cr ? (cr.top >= 0 && cr.bottom <= H + 0.5) : null,
    title: ((stage || document).querySelector('h1') || {}).textContent || null,
    slide_no: stage ? ((stage.querySelector('[data-no-label]') || {}).textContent || null) : null,
  };
}""".replace("MIN", str(MIN_TARGET))


def run_device(browser, base: str, width: int, ua_kind: str, deck: str, out: Path, full: bool) -> dict:
    h, dpr, plat = DEVICES[width]
    ua = UA_BASE[plat] + INAPP_SUFFIX.get(ua_kind, "")
    ctx = browser.new_context(viewport={"width": width, "height": h}, device_scale_factor=dpr, is_mobile=True,
                              has_touch=True, user_agent=ua, locale="ko-KR")
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    rep: dict = {"ua": ua_kind or plat, "viewport": f"{width}x{h}@{dpr}", "shots": [], "steps": {}, "console": [],
                 "failed": [], "api": [], "funnel": [], "checks": {}}
    short = lambda u: u.split(base, 1)[-1]   # noqa: E731
    page.on("console", lambda m: rep["console"].append(f"{m.type}: {m.text}"[:240]) if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: rep["console"].append(f"pageerror: {e}"[:240]))
    funnel_by_req: dict = {}

    def on_request(q) -> None:
        # 퍼널 신호는 요청 때 적는다 — 「팀 소개로 돌아가기」 처럼 누르자마자 페이지가 바뀌면 응답 이벤트가 이 페이지에 안 온다
        if q.url.endswith("/api/v1/tour/event") and q.method == "POST":
            item = {"body": q.post_data, "status": None}
            funnel_by_req[id(q)] = item
            rep["funnel"].append(item)

    def on_failed(q) -> None:
        if q.url.startswith(("kakaotalk:", "intent:")):
            return
        # keepalive fetch 는 서버가 204 를 줘도 크롬이 ERR_ABORTED 로 알린다 — 상태는 응답·서버 로그로 본다
        if q.url.endswith("/api/v1/tour/event") and "ERR_ABORTED" in str(q.failure):
            return
        rep["failed"].append(f"FAIL {q.method} {short(q.url)} {q.failure}"[:200])

    def on_response(r) -> None:
        if r.status >= 400 and not short(r.url).startswith(ALLOWED_FAIL):
            rep["failed"].append(f"{r.status} {r.request.method} {short(r.url)}")
        if "/api/" in r.url:
            rep["api"].append(f"{r.request.method} {short(r.url).split('?')[0]} {r.status}")
            if id(r.request) in funnel_by_req:
                funnel_by_req[id(r.request)]["status"] = r.status
    page.on("request", on_request)
    page.on("requestfailed", on_failed)
    page.on("response", on_response)

    d = out / f"{ua_kind or plat}_{width}"
    d.mkdir(parents=True, exist_ok=True)
    n = [0]

    def shot(name: str, settle: int = 350, long: bool = False) -> dict:
        page.wait_for_timeout(settle)
        n[0] += 1
        tag = f"{n[0]:02d}_{name}"
        info = page.evaluate(MEASURE_JS)
        rep["steps"][tag] = info
        page.screenshot(path=str(d / f"{tag}.png"))
        rep["shots"].append(str((d / f"{tag}.png").relative_to(out)))
        if long or full:
            extra = page.evaluate("() => { const b = document.querySelector('[data-tour-body]'); return b ? b.scrollHeight - b.clientHeight : 0; }")
            if extra > 4:
                page.set_viewport_size({"width": width, "height": h + extra})
                page.wait_for_timeout(250)
                page.screenshot(path=str(d / f"{tag}_full.png"))
                page.set_viewport_size({"width": width, "height": h})
                page.wait_for_timeout(150)
        return info

    def tap(sel: str, wait: int = 150) -> None:
        page.locator(sel).first.tap()
        page.wait_for_timeout(wait)

    def screen(name: str, timeout: int = 15000) -> None:
        page.wait_for_selector(f"#tourStage[data-screen='{name}']", timeout=timeout)

    def swipe(sel: str, dx: int, dy: int = 0) -> None:
        box = page.locator(sel).first.bounding_box()
        x0, y0 = box["x"] + box["width"] * 0.6, box["y"] + box["height"] * 0.5
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": y0}]})
        for i in range(1, 9):
            cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x0 + dx * i / 8, "y": y0 + dy * i / 8}]})
            page.wait_for_timeout(16)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        page.wait_for_timeout(400)

    try:
        # ── /hi 랜딩 ──
        page.goto(f"{base}/hi", wait_until="networkidle")
        shot("hi_first", 700)
        page.evaluate("document.getElementById('team').scrollIntoView({block:'start'})")
        page.wait_for_selector(".team-row[data-id]", timeout=10000)
        # 팀 소개는 한 사람 한 줄 목록(10-12) — 넘기기 없이 한 장으로
        rep["checks"]["team_cards"] = page.locator(".team-row[data-id]").count()
        shot("team_list", 450)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        shot("hi_bottom", 400)
        # ── 「척척발표 살펴보기」 → 투어 ──
        tap("#explore-btn", 0)
        screen("intro")
        rep["checks"]["explore_url"] = page.evaluate("location.pathname + location.hash")
        shot("tour_intro", 400, long=True)
        # 주 버튼 두 번 빠르게(300ms) — 다음 화면 주 버튼이 같은 자리라 화면을 건너뛰었다 (10-12 2차 flow-regression-inapp-r2-2)
        bb = page.locator("#tourStage [data-tour-foot] .tour-cta").first.bounding_box()
        page.touchscreen.tap(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
        page.wait_for_timeout(300)
        page.touchscreen.tap(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
        page.wait_for_timeout(700)
        rep["checks"]["double_tap_screen"] = page.evaluate("(document.getElementById('tourStage') || {}).dataset?.screen")
        screen("deck")
        if deck:
            page.locator(f"input[name='tourDeck'][value='{deck}']").first.evaluate("(r) => r.closest('label').click()")
            page.wait_for_selector(f"input[name='tourDeck'][value='{deck}']:checked", timeout=5000)
        shot("tour_deck", 500, long=True)
        rep["checks"]["deck"] = page.evaluate("(document.querySelector(\"input[name='tourDeck']:checked\") || {}).value || ''")
        tap("[data-next]")
        screen("present")
        shot("tour_present_play", 1600)
        tap("[data-play]")   # 멈추고 민다 — 재생이 장을 바꾸지 않게
        before = page.evaluate(MEASURE_JS)["slide_no"]
        swipe("[data-stage]", -150, 14)
        after = page.evaluate(MEASURE_JS)["slide_no"]
        shot("tour_present_swiped", 200)
        swipe("[data-stage]", 150, -10)
        back = page.evaluate(MEASURE_JS)["slide_no"]
        rep["checks"]["swipe"] = {"before": before, "after_left": after, "after_right": back, "ok": before != after and back == before}
        tap("[data-next]")
        screen("analysis")
        shot("tour_analysis", 2400, long=True)
        tap("[data-next]")
        screen("qa")
        q = 0
        while q < 8 and page.evaluate("(document.getElementById('tourStage') || {}).dataset?.screen") == "qa":
            q += 1
            shot(f"tour_qa{q}", 500)
            tap("[data-pick='good']", 500)
            shot(f"tour_qa{q}_good", 200, long=True)
            tap("[data-pick='rough']", 500)
            shot(f"tour_qa{q}_rough", 200, long=True)
            tap("[data-next]", 500)
        rep["checks"]["questions"] = q
        screen("report")
        shot("tour_report", 500, long=True)
        tap("[data-next]")
        screen("done")
        shot("tour_done", 500)
        # ── 끝: 실제 흐름 ──
        tap("[data-real]", 600)
        if ua_kind:
            shot("done_inapp_sheet", 200)
            rep["checks"]["inapp_sheet"] = page.locator(".tour-sheet[role='dialog']").count() == 1
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
            # 시트가 떠 있을 때 폰 뒤로는 시트만 닫는다 — 끝 화면을 잃고 리포트로 갔다 (10-12 2차 flow-regression-inapp-r2-6)
            tap("[data-real]", 600)
            page.go_back()
            page.wait_for_timeout(600)
            rep["checks"]["sheet_back"] = page.evaluate(
                "({url: location.hash, sheet: !!document.querySelector('.tour-sheet-wrap')})")
        else:
            page.wait_for_function("location.hash.startsWith('#/rehearsal')", timeout=8000)
            page.wait_for_timeout(900)
            rep["checks"]["real_url"] = page.evaluate("location.pathname + location.hash")
            rep["checks"]["tour_layer_gone"] = page.locator("#tourStage").count() == 0
            shot("rehearsal_landing", 300)
            # 리허설 첫 화면 「나가기」 → 끝 화면, 그 뒤 「팀 소개로 돌아가기」 가 /hi 로 가야 한다 — 리허설로 되돌아갔다 (10-12 2차 r2-1)
            tap("[data-rh-exit]", 0)
            screen("done")
            rep["checks"]["rh_exit_url"] = page.evaluate("location.pathname + location.hash")
        # ── 끝: 팀 소개로 돌아가기 ──
        tap("[data-back-team]", 0)
        page.wait_for_url("**/hi", timeout=10000)
        page.wait_for_load_state("networkidle")
        rep["checks"]["back_team_url"] = page.evaluate("location.pathname + location.hash")
        shot("back_to_hi", 500)
        # 옛 링크 #/hi 도 랜딩으로
        page.goto(f"{base}/index.html#/hi", wait_until="load")
        page.wait_for_url("**/hi", timeout=10000)
        rep["checks"]["hash_hi_redirect"] = page.evaluate("location.pathname")
    except Exception as e:   # 어디서 멈췄는지 사진으로 남긴다
        rep["error"] = f"{type(e).__name__}: {e}"[:500]
        try:
            page.screenshot(path=str(d / "zz_error.png"))
        except Exception:   # noqa: BLE001 — 사진도 못 찍으면 표에만 남긴다
            pass
    ctx.close()
    return rep


#: 팀 카드 칸 길이 내성 — 팀원이 직접 채울 칸이라 띄어쓰기 없는 긴 영문 덩어리(파일 이름 · 기술 나열)가 들어올 수 있다 (10-12 점검)
LONG_TOKENS = {
    "headline": "vision_rehearsal.js·booth_overlay_state.js 정리",
    "name": "SuperLongEnglishTokenWithoutAnySpacesAtAllAnywhere",
}

CARD_JS = """() => { const W = innerWidth;
  // 팀 소개 줄(10-12 한 사람 한 줄) — 긴 덩어리가 줄 밖으로 삐져나가는가
  return Array.from(document.querySelectorAll('.team-row[data-id]')).map((c) => {
    const r = c.getBoundingClientRect();
    const clipped = Array.from(c.querySelectorAll('*')).some((e) => e.getBoundingClientRect().right > r.right + 1);
    return { id: c.dataset.id, w: c.offsetWidth, h: c.offsetHeight, vw: W, clipped };
  }); }"""


def run_stress(browser, base: str, width: int, out: Path) -> dict:
    """줄을 벗어난 데이터 · 끊긴 망에서 버티는가 — 팀 카드 긴 덩어리 · 장 그림을 못 받을 때 대체 화면."""
    h, dpr, plat = DEVICES[width]
    ctx = browser.new_context(viewport={"width": width, "height": h}, device_scale_factor=dpr, is_mobile=True,
                              has_touch=True, user_agent=UA_BASE[plat], locale="ko-KR")
    page = ctx.new_page()
    d = out / f"stress_{width}"
    d.mkdir(parents=True, exist_ok=True)
    res: dict = {}
    try:
        team = json.loads((HERE.parents[1] / "demo" / "YEHS_demo" / "data" / "team.json").read_text(encoding="utf-8"))
        normal = len(team["members"])
        team["members"][1]["headline"] = LONG_TOKENS["headline"]
        team["members"][min(2, normal - 1)]["name"] = LONG_TOKENS["name"]
        body = json.dumps(team, ensure_ascii=False)
        page.route("**/data/team.json", lambda r: r.fulfill(status=200, content_type="application/json", body=body))
        page.goto(f"{base}/hi", wait_until="networkidle")
        page.wait_for_selector(".team-row[data-id]", timeout=10000)
        page.evaluate("document.getElementById('team').scrollIntoView({block:'start', behavior:'instant'})")
        page.wait_for_timeout(300)
        res["cards_long"] = page.evaluate(CARD_JS)
        page.screenshot(path=str(d / "01_team_long.png"))
        page.unroute("**/data/team.json")
        # 장 그림 · 표지를 못 받으면 — 깨진 그림 아이콘 대신 장 제목 카드
        page.route("**/assets/deck-slides/**", lambda r: r.abort())
        page.route("**/assets/deck-covers/**", lambda r: r.abort())
        broken_js = """() => Array.from(document.querySelectorAll('#tourStage img')).filter((i) => {
            const r = i.getBoundingClientRect(); return r.width > 0 && getComputedStyle(i).visibility !== 'hidden' && i.complete && !i.naturalWidth; }).length"""
        res["img_fail"] = {}
        for name in ("deck", "present", "qa"):
            page.goto(f"{base}/index.html#/tour/{name}", wait_until="load")
            page.wait_for_selector(f"#tourStage[data-screen='{name}']", timeout=15000)
            page.wait_for_timeout(1200)
            res["img_fail"][name] = {"broken_visible": page.evaluate(broken_js),
                                     "fallback": page.locator("#tourStage .tour-img-fallback").count()}
            page.screenshot(path=str(d / f"1{len(res['img_fail'])}_imgfail_{name}.png"))
    except Exception as e:   # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {e}"[:300]
    ctx.close()
    return res


def stress_problems(res: dict) -> list[str]:
    out: list[str] = []
    if res.get("error"):
        out.append(f"버팀 검사 멈춤: {res['error']}")
    cards = res.get("cards_long") or []
    if cards:
        base_w = min(c["w"] for c in cards)
        for c in cards:
            if c["w"] > base_w + 1 or c["clipped"]:
                out.append(f"팀 줄 {c['id']}: 긴 덩어리로 줄이 넓어지거나 잘림 (폭 {c['w']} · 보통 {base_w} · 화면 {c['vw']})")
    for name, v in (res.get("img_fail") or {}).items():
        if v["broken_visible"] or not v["fallback"]:
            out.append(f"그림 못 받은 {name}: 깨진 그림 {v['broken_visible']}개 · 대체 카드 {v['fallback']}개")
    return out


def problems(rep: dict) -> list[str]:
    out: list[str] = []
    out += stress_problems(rep.get("stress") or {})
    if rep.get("error"):
        out.append(f"멈춤: {rep['error']}")
    for tag, s in rep["steps"].items():
        if s.get("hscroll") or s.get("overflow"):
            out.append(f"{tag}: 가로 넘침 scrollW={s.get('page_scroll_w')} {s.get('overflow')[:3]}")
        if s.get("small_targets"):
            out.append(f"{tag}: {MIN_TARGET}px 보다 작은 누를 곳 {s['small_targets'][:4]}")
        if s.get("cta_visible") is False:
            out.append(f"{tag}: 주 버튼이 화면 밖 ({s.get('cta')})")
    out += [f"콘솔: {c}" for c in rep["console"]]
    out += [f"요청 실패: {f}" for f in rep["failed"]]
    bad_api = [a for a in rep["api"] if not a.startswith(OK_API)]
    out += [f"투어에서 부르면 안 되는 API: {a}" for a in bad_api]
    out += [f"퍼널 신호 거절: {f}" for f in rep["funnel"] if f["status"] not in (204, None)]
    c = rep["checks"]
    if c.get("swipe") and not c["swipe"].get("ok"):
        out.append(f"밀어서 장 넘기기 실패 {c['swipe']}")
    if c.get("explore_url") and not c["explore_url"].startswith("/index.html#/tour"):
        out.append(f"살펴보기가 투어로 안 감: {c['explore_url']}")
    if "back_team_url" in c and c["back_team_url"] != "/hi":
        out.append(f"팀 소개로 돌아가기가 /hi 로 안 감: {c['back_team_url']}")
    if "hash_hi_redirect" in c and c["hash_hi_redirect"] != "/hi":
        out.append(f"#/hi 가 /hi 로 안 감: {c['hash_hi_redirect']}")
    if "double_tap_screen" in c and c["double_tap_screen"] != "deck":
        out.append(f"주 버튼 두 번 누르기가 화면을 건너뜀: {c['double_tap_screen']}")
    if "rh_exit_url" in c and c["rh_exit_url"] != "/index.html#/tour/done":
        out.append(f"리허설 나가기가 끝 화면으로 안 감: {c['rh_exit_url']}")
    if c.get("sheet_back") and (c["sheet_back"]["sheet"] or c["sheet_back"]["url"] != "#/tour/done"):
        out.append(f"시트에서 폰 뒤로가 끝 화면을 떠남: {c['sheet_back']}")
    if c.get("inapp_sheet") is False:
        out.append("인앱 UA 인데 바깥 브라우저 안내 시트가 안 뜸")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="부스 모바일 /hi → #/tour 한 바퀴를 폰 네 폭으로 찍는다")
    ap.add_argument("port", type=int, help="브리지 포트 (127.0.0.1)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--widths", default="360,375,393,412")
    ap.add_argument("--ua", default="", choices=["", *INAPP_SUFFIX], help="인앱 브라우저 UA (기본: 폭마다 안드로이드 크롬 · iOS 사파리)")
    ap.add_argument("--deck", default="", help="자료 화면에서 고를 투어 id (기본: index.json 의 default)")
    ap.add_argument("--full", action="store_true", help="모든 화면의 본문 전체 높이 사진도 찍는다")
    ap.add_argument("--no-stress", action="store_true", help="버팀 검사(긴 팀 카드 · 그림 못 받기)를 건너뛴다")
    args = ap.parse_args(argv)

    from playwright.sync_api import sync_playwright

    base = f"http://{args.host}:{args.port}"
    out = OUT / datetime.now().strftime("%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"base": base, "ua": args.ua, "deck": args.deck, "devices": {}}
    with sync_playwright() as p:
        env = dict(os.environ)
        if PW_LIBS.is_dir() and str(PW_LIBS) not in env.get("LD_LIBRARY_PATH", ""):
            env["LD_LIBRARY_PATH"] = ":".join(x for x in (str(PW_LIBS), env.get("LD_LIBRARY_PATH", "")) if x)
        browser = p.chromium.launch(env=env)
        for w in [int(x) for x in args.widths.split(",") if x]:
            report["devices"][str(w)] = run_device(browser, base, w, args.ua, args.deck, out, args.full)
            if not args.no_stress:
                report["devices"][str(w)]["stress"] = run_stress(browser, base, w, out)
        browser.close()
    for rep in report["devices"].values():
        rep["problems"] = problems(rep)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    bad = False
    for w, rep in report["devices"].items():
        steps = [json.loads(f["body"] or "{}").get("step") for f in rep["funnel"]]
        print(f"[{rep['ua']} {w}] 사진 {len(rep['shots'])}장 · 카드 {rep['checks'].get('team_cards')} · 질문 {rep['checks'].get('questions')}"
              f" · 밀기 {rep['checks'].get('swipe', {}).get('ok')} · 퍼널 {steps}")
        for pr in rep["problems"]:
            bad = True
            print("   !", pr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
