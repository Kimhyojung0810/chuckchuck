"""
/hi 부스 랜딩 실험실 (2026-10-11) — 폰 세로 4폭(360·375·393·412)을 헤드리스 크롬 모바일 에뮬레이션(터치 · DPR · UA)으로 열어
첫 화면 · 팀 카드 1번째 · 마지막 카드 · 아래 고정 버튼을 찍고, 가로 스크롤 · 콘솔 오류 · 전송량 · 버튼 위치 · 터치 대상 크기를 잰다.
카카오톡 인앱 UA 로 「바로 내 자료로 해 보기」 를 눌렀을 때 안내 시트가 뜨는지도 한 번.

이 서버엔 폰이 없다 — 사진을 Read 로 직접 보고 고친다. API 는 부르지 않는다(정적 페이지).

    LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu .venv/bin/python etc/labs/intro_flow/run.py --base http://127.0.0.1:8981

결과: etc/labs/intro_flow/out/<stamp>/*.png + report.json
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1")
ANDROID_UA = ("Mozilla/5.0 (Linux; Android 14; SM-S921N) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36")
KAKAO_UA = ANDROID_UA + " KAKAOTALK 10.8.5"

# (폭, 높이, DPR, UA) — 높이는 주소창을 뺀 실제 보이는 높이에 가깝게
DEVICES = [
    (360, 740, 3, ANDROID_UA),   # 갤럭시 S 계열
    (375, 667, 2, IPHONE_UA),    # 아이폰 SE — 제일 낮은 화면
    (393, 760, 3, IPHONE_UA),    # 아이폰 15 (사파리 주소창 포함)
    (412, 820, 2.625, ANDROID_UA),  # 픽셀 계열
]

MEASURE = """() => {
  const de = document.documentElement;
  const dock = document.querySelector('.dock .btn-primary').getBoundingClientRect();
  const small = [...document.querySelectorAll('a[href], button')]
    .filter(e => e.offsetParent !== null && getComputedStyle(e).visibility !== 'hidden')
    .map(e => ({ t: (e.getAttribute('aria-label') || e.textContent || '').trim().slice(0, 24), r: e.getBoundingClientRect() }))
    .filter(x => x.r.width > 0 && (x.r.height < 44 || x.r.width < 24))
    .map(x => `${x.t} ${Math.round(x.r.width)}x${Math.round(x.r.height)}`);
  return {
    hscroll: de.scrollWidth > innerWidth + 1, scrollWidth: de.scrollWidth, innerWidth,
    dock: { top: Math.round(dock.top), bottom: Math.round(dock.bottom), h: Math.round(dock.height), vh: innerHeight },
    heroBottom: Math.round(document.querySelector('.hero-lead').getBoundingClientRect().bottom),
    rows: document.querySelectorAll('.team-row[data-id]').length,
    active: document.querySelector('.team-row[data-active]')?.dataset.id || null,
    small,
  };
}"""


def run(base: str, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"base": base, "devices": []}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for w, h, dpr, ua in DEVICES:
            tag = f"{w}x{h}"
            ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=dpr, is_mobile=True,
                                has_touch=True, user_agent=ua, locale="ko-KR")
            page = ctx.new_page()
            errs: list[str] = []
            sizes: list[tuple[str, int]] = []
            page.on("console", lambda m: errs.append(f"{m.type}: {m.text}"[:200]) if m.type in ("error", "warning") else None)
            page.on("pageerror", lambda e: errs.append(f"pageerror: {e}"[:200]))
            page.on("requestfinished", lambda r: sizes.append((r.url[-70:], r.sizes()["responseBodySize"])))
            page.goto(f"{base}/hi", wait_until="networkidle")
            # 첫 방문 연출(삐약이 날아와 앉기 · 약 2.1초)이 끝난 뒤의 첫 화면을 찍는다 — 900ms 에선 글이 아직 숨어 있었다
            page.wait_for_timeout(2600)
            first = page.evaluate(MEASURE)
            page.screenshot(path=str(out / f"{tag}_1_first.png"))
            page.locator("#team").scroll_into_view_if_needed()
            page.evaluate("document.getElementById('team').scrollIntoView({block:'start'})")
            page.wait_for_timeout(500)
            page.screenshot(path=str(out / f"{tag}_2_team.png"))
            # 팀 소개는 한 사람 한 줄 목록(10-12) — 넘기기 없이 목록 전체가 한 화면에 보이는가
            page.wait_for_selector(".team-row[data-id]", timeout=10000)
            page.evaluate("document.querySelector('.team-list').scrollIntoView({block:'start'})")
            page.wait_for_timeout(300)
            last = page.evaluate(MEASURE)
            page.screenshot(path=str(out / f"{tag}_3_team_list.png"))
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(400)
            page.screenshot(path=str(out / f"{tag}_4_bottom.png"))
            page.screenshot(path=str(out / f"{tag}_5_full.png"), full_page=True)
            report["devices"].append({
                "device": tag, "dpr": dpr, "first": first, "team_list": last,
                "bytes_total": sum(s for _, s in sizes), "bytes": sizes, "console": errs,
            })
            ctx.close()

        # 카카오톡 인앱 — 투어 버튼은 그대로, 실제 흐름 링크만 안내 시트
        ctx = b.new_context(viewport={"width": 375, "height": 667}, device_scale_factor=2, is_mobile=True,
                            has_touch=True, user_agent=KAKAO_UA, locale="ko-KR")
        page = ctx.new_page()
        page.goto(f"{base}/hi/seonho", wait_until="networkidle")
        page.wait_for_timeout(700)
        deep = page.evaluate(MEASURE)
        page.screenshot(path=str(out / "kakao_1_deeplink_seonho.png"))
        page.evaluate("window.scrollTo(0,0)")
        page.wait_for_timeout(300)
        page.locator("#own-link-1").tap()
        page.wait_for_timeout(500)
        sheet_open = page.evaluate("!document.getElementById('inapp').hidden")
        btn = page.locator("#inapp-open").text_content()
        page.screenshot(path=str(out / "kakao_2_sheet.png"))
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        sheet_closed = page.evaluate("document.getElementById('inapp').hidden")
        tour_href = page.locator(".dock .btn-primary").get_attribute("href")
        report["kakao"] = {"deeplink": deep, "sheet_open": sheet_open, "open_button": btn,
                           "esc_closes": sheet_closed, "tour_href": tour_href}
        ctx.close()

        # team.json 이 실패해도 히어로·버튼은 그대로인가
        ctx = b.new_context(viewport={"width": 360, "height": 740}, device_scale_factor=2, is_mobile=True,
                            has_touch=True, user_agent=ANDROID_UA)
        page = ctx.new_page()
        page.route("**/data/team.json*", lambda r: r.fulfill(status=500, body="x"))
        page.goto(f"{base}/hi", wait_until="networkidle")
        page.evaluate("document.getElementById('team').scrollIntoView({block:'start'})")
        page.wait_for_timeout(2600)   # 첫 방문 연출이 끝나야 글이 보인다
        report["team_fail"] = page.evaluate("({err: !document.getElementById('team-error').hidden,"
                                            " dock: !!document.querySelector('.dock .btn-primary').offsetParent})")
        page.screenshot(path=str(out / "fail_team_json.png"))
        ctx.close()

        # JS 를 끈 첫 화면
        ctx = b.new_context(viewport={"width": 360, "height": 740}, device_scale_factor=2, is_mobile=True,
                            has_touch=True, user_agent=ANDROID_UA, java_script_enabled=False)
        page = ctx.new_page()
        page.goto(f"{base}/hi", wait_until="networkidle")
        page.screenshot(path=str(out / "nojs_first.png"))
        ctx.close()
        b.close()
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8981")
    args = ap.parse_args()
    out = OUT / datetime.now().strftime("%m%d_%H%M%S")
    rep = run(args.base, out)
    for d in rep["devices"]:
        print(d["device"], "hscroll", d["first"]["hscroll"], "dock", d["first"]["dock"], "rows", d["team_list"]["rows"],
              "bytes", d["bytes_total"], "console", d["console"][:3], "small", d["first"]["small"][:6])
    print("kakao", {k: v for k, v in rep["kakao"].items() if k != "deeplink"}, "deeplink active", rep["kakao"]["deeplink"]["active"])
    print("team_fail", rep["team_fail"])
    print(out)


if __name__ == "__main__":
    main()
