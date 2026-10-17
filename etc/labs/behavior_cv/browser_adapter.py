"""브라우저 어댑터 — 엔진 worktree 의 main/web 를 작은 정적 서버(127.0.0.1:8835~8839)로 내주고,
헤드리스 크롬에 합성 영상을 가짜 카메라로 물려 엔진을 실제 카메라 경로 그대로 돌린다.

    run.py browser --web /data/models/_wt/wt-behavior-cv/main/web [--adapter web/adapter_x.js] [--cpu-throttle 4]

서버 경로
  /                           → <web>          (엔진 파일 · vendor opencv.js · 캐스케이드)
  /behavior_lab_harness.html  → web/harness.html (엔진과 같은 폴더 높이 — 상대 경로가 앱과 같게 풀린다)
  /__lab/adapter.js           → --adapter 파일
  /__lab/                     → 이 실험실 web/
크롬: --use-fake-device-for-media-stream --use-fake-ui-for-media-stream --use-file-for-fake-video-capture=<clip>.y4m
LabTap(web/labtap.js)을 init script 로 먼저 심어 워커로 가는 프레임의 바코드를 푼다 → 줄마다 영상 프레임 번호.
8799(공개 서비스)는 건드리지 않는다.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from common import HERE, ensure_chrome_libs, free_port, serve


def run_clip_browser(clip: Path, gt: dict, web: Path, adapter: Path, throttle: float = 1.0, port: int = 0,
                     shots: Path | None = None, timeout_pad: float = 90.0) -> dict:
    ensure_chrome_libs()
    from playwright.sync_api import sync_playwright

    port = port or free_port()
    httpd = serve({"/": web, "/behavior_lab_harness.html": HERE / "web" / "harness.html",
                   "/__lab/adapter.js": adapter, "/__lab/": HERE / "web"}, port)
    console: list[str] = []
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch(args=[
                "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                f"--use-file-for-fake-video-capture={clip}", "--autoplay-policy=no-user-gesture-required",
                "--disable-background-timer-throttling", "--disable-renderer-backgrounding"])
            ctx = br.new_context(viewport={"width": 900, "height": 700})
            ctx.add_init_script(path=str(HERE / "web" / "labtap.js"))
            page = ctx.new_page()
            page.on("console", lambda m: console.append(f"{m.type}: {m.text}"[:300]))
            page.on("pageerror", lambda e: console.append(f"pageerror: {e}"[:300]))
            if throttle and throttle != 1.0:
                cdp = ctx.new_cdp_session(page)
                cdp.send("Emulation.setCPUThrottlingRate", {"rate": throttle})
            page.goto(f"http://127.0.0.1:{port}/behavior_lab_harness.html")
            cfg = {"w": gt["w"], "h": gt["h"], "fps": gt["fps"], "nFrames": gt["n_frames"], "durMs": int(gt["duration"] * 1000),
                   "slides": gt["slides"]}
            page.set_default_timeout(int((gt["duration"] * 2.2 + timeout_pad) * 1000))
            t0 = time.time()
            res = page.evaluate("cfg => window.labRun(cfg)", cfg)
            res["wall_s"] = round(time.time() - t0, 1)
            if shots:
                shots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shots / f"{clip.stem}.png"))
            br.close()
    except Exception as err:  # 채점기가 이유를 남기게
        res = {"rows": [], "error": str(err)[:500]}
    finally:
        httpd.shutdown()
    res["engine"] = "browser"
    res["clip"] = clip.stem
    res["console"] = console[-40:]
    res["adapter"] = str(adapter)
    return res


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("clip", type=Path)
    ap.add_argument("--web", type=Path, required=True)
    ap.add_argument("--adapter", type=Path, default=HERE / "web" / "adapter_default.js")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    gt = json.loads(a.clip.with_suffix(".gt.json").read_text())
    r = run_clip_browser(a.clip, gt, a.web, a.adapter)
    (a.out or a.clip.with_suffix(".browser.pred.json")).write_text(json.dumps(r, ensure_ascii=False))
    print(len(r.get("rows", [])), r.get("adapter_note"), r.get("error"), r.get("tap"), "\n".join(r.get("console", [])[-10:]))
