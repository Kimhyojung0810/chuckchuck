"""
첫 화면 로딩 실험실 — 공개 사이트가 느린 이유를 숫자로 본다.

왜 — 공개 경로(Cloudflare → Tailscale Funnel 도쿄 입구 → DERP 홍콩 → VM)는 새 연결 하나에 ~1초,
이어 쓰는 연결의 요청 하나에 ~0.2초가 든다 (2026-10-01 실측). 그 길을 몇 번 타느냐가 체감 속도다.
이 실험실은 헤드리스 크롬으로 페이지를 두 번(처음 방문 · 다시 방문) 열고 첫 그림(FCP) · 앱이 첫 화면을 그린 시각(app) ·
요청 수 · 받은 바이트 · 캐시에서 온 수 · 화면이 뜬 시각 · 가장 긴 요청 사슬을 남긴다.

    .venv/bin/python labs/load_perf/run.py --base http://127.0.0.1:8810                  # 로컬 그대로
    .venv/bin/python labs/load_perf/run.py --base http://127.0.0.1:8810 --latency 200    # 요청마다 200ms 더 (공개 경로 흉내)
    .venv/bin/python labs/load_perf/run.py --base https://chuckchuck-present.com --runs 3

--latency·--down 은 크롬 DevTools 네트워크 흉내라 같은 출처 요청에만 걸고 싶어도 CDN 에도 걸린다.
결과: labs/load_perf/out/<stamp>/report.json + 요약 표(표준 출력).
libasound 가 없는 서버면 LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu (labs/qa_call/README.md).
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

# 앱이 첫 화면을 그렸다는 표시 — route() 가 #app 을 채운다
READY_JS = "() => { const a = document.querySelector('#app'); return !!(a && a.childElementCount); }"

# 페이지 안에서 잰다 — #app 이 처음 채워진 시각(앱이 첫 화면을 그림)
INIT_JS = """(() => {
  window.__ccAppAt = 0;
  const tick = () => {
    const a = document.querySelector('#app');
    if (a && a.childElementCount) { window.__ccAppAt = performance.now(); return; }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
})();"""

PERF_JS = """() => {
  const nav = performance.getEntriesByType('navigation')[0] || {};
  const res = performance.getEntriesByType('resource').map(r => ({
    name: r.name, type: r.initiatorType, start: r.startTime, end: r.responseEnd,
    transfer: r.transferSize, body: r.encodedBodySize, decoded: r.decodedBodySize,
  }));
  const fcp = (performance.getEntriesByName('first-contentful-paint')[0] || {}).startTime || 0;
  return { dcl: nav.domContentLoadedEventEnd, load: nav.loadEventEnd, html_ttfb: nav.responseStart, res,
           fcp, app_at: window.__ccAppAt || 0 };
}"""


def one_visit(page, url: str, same_origin: str) -> dict:
    seen: list[dict] = []

    def on_response(resp):
        try:
            h = resp.headers
            seen.append({"url": resp.url, "status": resp.status, "cf": h.get("cf-cache-status", ""),
                         "cc": h.get("cache-control", ""), "enc": h.get("content-encoding", "")})
        except Exception:  # noqa: BLE001
            pass

    page.on("response", on_response)
    t0 = time.perf_counter()
    page.goto(url, wait_until="load", timeout=120_000)
    t_load = time.perf_counter() - t0
    try:
        page.wait_for_function(READY_JS, timeout=60_000)
    except Exception:  # noqa: BLE001
        pass
    t_ready = time.perf_counter() - t0
    # 모듈·늦은 fetch 가 끝나기를 잠깐 기다린다
    try:
        page.wait_for_load_state("networkidle", timeout=30_000)
    except Exception:  # noqa: BLE001
        pass
    t_idle = time.perf_counter() - t0
    perf = page.evaluate(PERF_JS)
    page.remove_listener("response", on_response)

    res = perf["res"]
    mine = [r for r in res if urlparse(r["name"]).netloc == same_origin]
    net = [r for r in mine if r["transfer"] > 0]           # 망을 탄 것 (304 도 헤더만큼 transfer>0)
    cached = [r for r in mine if r["transfer"] == 0 and r["decoded"] > 0]  # 브라우저 캐시에서 바로
    revalidated = [r for r in mine if 0 < r["transfer"] < 600 and r["decoded"] > 2000]
    app_at = perf["app_at"] or 0
    return {
        "fcp_ms": round(perf["fcp"]), "app_ms": round(app_at),
        "load_ms": round(perf["load"] or 0),
        "before_app": len([r for r in mine if r["start"] <= app_at]) + 1,
        "load_s": round(t_load, 3), "ready_s": round(t_ready, 3), "idle_s": round(t_idle, 3),
        "dcl_ms": round(perf["dcl"] or 0), "html_ttfb_ms": round(perf["html_ttfb"] or 0),
        "requests_same_origin": len(mine) + 1, "net_same_origin": len(net) + 1,
        "from_browser_cache": len(cached), "revalidated_304ish": len(revalidated),
        "bytes_same_origin": sum(r["transfer"] for r in mine),
        "bytes_all": sum(r["transfer"] for r in res),
        "last_same_origin_end_ms": round(max((r["end"] for r in mine), default=0)),
        "cf_status": sorted({s["cf"] for s in seen if s["cf"] and urlparse(s["url"]).netloc == same_origin}),
        "slowest": sorted(({"url": r["name"].split("/", 3)[-1][:70], "ms": round(r["end"] - r["start"]),
                            "start": round(r["start"])} for r in mine), key=lambda x: -x["ms"])[:6],
        "resources": res, "headers": seen,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8810")
    ap.add_argument("--route", default="#/")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--latency", type=int, default=0, help="요청마다 더할 지연(ms) — DevTools 흉내")
    ap.add_argument("--down", type=int, default=0, help="내려받기 속도 KB/s (0=제한 없음)")
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    from playwright.sync_api import sync_playwright

    url = a.base.rstrip("/") + "/index.html" + a.route
    origin = urlparse(a.base).netloc
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{a.label}" if a.label else "")
    out = OUT / stamp
    out.mkdir(parents=True, exist_ok=True)
    runs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for i in range(a.runs):
            ctx = b.new_context(viewport={"width": 1280, "height": 860})
            ctx.add_init_script(INIT_JS)
            page = ctx.new_page()
            if a.latency or a.down:
                cdp = ctx.new_cdp_session(page)
                cdp.send("Network.enable")
                cdp.send("Network.emulateNetworkConditions", {
                    "offline": False, "latency": a.latency,
                    "downloadThroughput": (a.down * 1024) if a.down else -1, "uploadThroughput": -1})
            first = one_visit(page, url, origin)
            # 다시 방문 — 같은 브라우저(캐시 유지)에서 새 탭으로 연다. reload 는 캐시를 재검증하므로 쓰지 않는다
            page2 = ctx.new_page()
            if a.latency or a.down:
                cdp2 = ctx.new_cdp_session(page2)
                cdp2.send("Network.enable")
                cdp2.send("Network.emulateNetworkConditions", {
                    "offline": False, "latency": a.latency,
                    "downloadThroughput": (a.down * 1024) if a.down else -1, "uploadThroughput": -1})
            again = one_visit(page2, url, origin)
            runs.append({"first": first, "again": again})
            ctx.close()
        b.close()

    keys = ["fcp_ms", "app_ms", "load_ms", "before_app", "idle_s", "requests_same_origin", "net_same_origin", "from_browser_cache",
            "revalidated_304ish", "bytes_same_origin", "last_same_origin_end_ms"]
    summary = {}
    for kind in ("first", "again"):
        summary[kind] = {k: statistics.median(r[kind][k] for r in runs) for k in keys}
        summary[kind]["cf_status"] = runs[-1][kind]["cf_status"]
        summary[kind]["slowest"] = runs[-1][kind]["slowest"]
    report = {"url": url, "latency_ms": a.latency, "down_kbps": a.down, "runs": a.runs, "summary": summary, "detail": runs}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{url}  latency+{a.latency}ms  down={a.down or '∞'}KB/s  runs={a.runs}  → {out}")
    cols = ("fcp_ms", "app_ms", "load_ms", "reqs<app", "reqs", "net", "cache", "KB")
    print(f"{'':8}" + "".join(f"{k:>10}" for k in cols))
    for kind in ("first", "again"):
        s = summary[kind]
        vals = [round(s["fcp_ms"]), round(s["app_ms"]), round(s["load_ms"]), s["before_app"], s["requests_same_origin"],
                s["net_same_origin"], s["from_browser_cache"], round(s["bytes_same_origin"] / 1024)]
        print(f"{kind:8}" + "".join(f"{v:>10}" for v in vals), " cf=", ",".join(s["cf_status"]) or "-")
    print("slowest (first):", ", ".join(f"{x['url']} {x['ms']}ms@{x['start']}" for x in summary["first"]["slowest"][:4]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
