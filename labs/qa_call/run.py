"""
통화형 Q&A 실험실 — booth.html 의 흐름을 단계별로 따로 돌리고 사진을 남긴다.

왜 — 부스 통화 화면(카메라·마이크·말풍선)은 이 서버에 브라우저가 없어 손으로 못 누른다.
헤드리스 크롬 + 가짜 카메라로 **실 API 브리지**에 붙여 단계마다 스크린샷과 보고(JSON)를 남긴다.
앱(index.html)은 건드리지 않고 booth.html 만 본다 — "QA 시스템만" 떼어 시험하는 자리다.

    python labs/qa_call/run.py all                      # 담기→분석→질문→답→판정→힌트→포기→마침 전부
    python labs/qa_call/run.py call-answer --mobile     # 폰 화면(390×844)으로 답·판정까지만
    python labs/qa_call/run.py freeze                   # 지금 booth 파일 3개를 out/snapshots/<stamp>/ 에 얼린다
    python labs/qa_call/run.py all --base http://127.0.0.1:8799

단계(--stage): capture · analyze · call-ask · call-answer · call-hint · call-giveup · finish · all
결과: labs/qa_call/out/<stamp>/*.png + report.json (걸린 시간·말풍선 본문·콘솔 오류)

준비: .venv 에 `pip install playwright pillow && python -m playwright install chromium`.
libasound 이 없으면 `python -m playwright install-deps` (sudo) 또는 README 의 무루트 우회.
브리지는 새 코드로 떠 있어야 한다 (이미지 파싱은 9/16 이후 코드).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
BOOTH = ROOT / "demo/YEHS_demo"
BOOTH_FILES = ["booth.html", "js/booth.js", "js/booth_logic.js", "css/booth.css"]
STAGES = ["capture", "analyze", "call-ask", "call-answer", "call-hint", "call-giveup", "finish"]
ANSWER = "초기 타깃은 발표를 준비하는 대학생과 취업준비생이고, 이후 기업 보고와 사내교육으로 넓힐 계획이에요"


def freeze() -> Path:
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    dst = OUT / "snapshots" / stamp
    for rel in BOOTH_FILES:
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BOOTH / rel, dst / rel)
    print(f"얼림: {dst.relative_to(ROOT)} ({len(BOOTH_FILES)}개)")
    return dst


def run(stage: str, base: str, mobile: bool, photos: list[Path]) -> Path:
    from playwright.sync_api import sync_playwright
    from fakecam import build as build_cam

    want = STAGES if stage == "all" else STAGES[: STAGES.index(stage) + 1]
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S") + ("_mobile" if mobile else "")
    out = OUT / stamp
    out.mkdir(parents=True, exist_ok=True)
    cam = build_cam(OUT / "fakecam.mjpeg")
    report: dict = {"base": base, "mobile": mobile, "stages": {}, "console": [], "bubbles": []}
    t_all = time.time()

    def shot(name: str) -> None:
        page.screenshot(path=str(out / f"{name}.png"))

    def bubbles() -> list[dict]:
        return page.evaluate(
            "Array.from(document.querySelectorAll('#call-log .call-bubble')).map(b => ({cls: b.className, v: b.dataset.v || '', text: b.innerText.trim().slice(0, 300)}))"
        )

    def mark(name: str, t0: float, extra: dict | None = None) -> None:
        report["stages"][name] = {"sec": round(time.time() - t0, 1), **(extra or {})}
        print(f"  {name:12s} {report['stages'][name]['sec']:5.1f}s")

    with sync_playwright() as p:
        b = p.chromium.launch(args=[
            "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-video-capture={cam}", "--autoplay-policy=no-user-gesture-required",
        ])
        ctx = b.new_context(
            viewport={"width": 390, "height": 844} if mobile else {"width": 1280, "height": 860},
            device_scale_factor=2, has_touch=mobile, permissions=["camera", "microphone"],
        )
        page = ctx.new_page()
        page.on("console", lambda m: report["console"].append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: report["console"].append(f"pageerror: {e}"))
        try:
            t0 = time.time()
            page.goto(f"{base}/booth.html", wait_until="networkidle")
            page.set_input_files("#file-shots", [str(x) for x in photos])
            page.wait_for_function(f"document.querySelectorAll('.booth-shot').length==={len(photos)}")
            shot("1_capture")
            mark("capture", t0, {"shots": len(photos)})
            if "analyze" not in want:
                return out

            t0 = time.time()
            page.click("#btn-go")
            page.wait_for_selector("#step-progress:not([hidden])")
            page.wait_for_timeout(1500)
            shot("2_analyze_progress")
            page.wait_for_selector("#call:not([hidden]), #progress-error:not([hidden])", timeout=180000)
            if page.is_visible("#progress-error"):
                shot("2_analyze_error")
                report["stages"]["analyze"] = {"sec": round(time.time() - t0, 1), "error": page.inner_text("#progress-error-text")}
                print("  분석 실패:", report["stages"]["analyze"]["error"])
                return out
            stages = page.evaluate("Array.from(document.querySelectorAll('#stages li')).map(li => [li.dataset.stage, li.querySelector('.st-time').textContent])")
            mark("analyze", t0, {"bridge_stages": stages, "questions": page.evaluate("document.querySelectorAll('#qa-count')[0].textContent")})
            if "call-ask" not in want:
                return out

            t0 = time.time()
            page.wait_for_selector("#call-log .call-bubble.is-question", timeout=10000)
            page.wait_for_timeout(2000)
            shot("3_call_ask")
            mark("call-ask", t0, {"camera": page.get_attribute("#call-self", "data-camera"), "mic": page.get_attribute("#btn-mic", "data-state"),
                                  "mood": page.get_attribute("#call-partner-seat", "data-mood")})
            if "call-answer" not in want:
                return out

            t0 = time.time()
            page.fill("#qa-answer", ANSWER)
            page.click("#btn-answer")
            page.wait_for_selector("#call-log .call-bubble.is-verdict, #call-log .call-bubble.is-error", timeout=90000)
            page.wait_for_timeout(1200)
            shot("4_call_answer")
            v = page.evaluate("(() => { const b = document.querySelector('#call-log .call-bubble.is-verdict'); return b ? b.dataset.v : 'error'; })()")
            mark("call-answer", t0, {"verdict": v, "mood": page.get_attribute("#call-partner-seat", "data-mood")})
            if "call-hint" not in want:
                return out

            t0 = time.time()
            if page.is_enabled("#btn-hint"):
                page.click("#btn-hint")
                page.wait_for_selector("#call-log .call-bubble.is-hint", timeout=5000)
                page.wait_for_timeout(600)
                shot("5_call_hint")
                mark("call-hint", t0, {"mood": page.get_attribute("#call-partner-seat", "data-mood")})
            else:
                mark("call-hint", t0, {"skipped": "힌트 없음"})
            if "call-giveup" not in want:
                return out

            t0 = time.time()
            page.click("#btn-next")
            page.wait_for_timeout(1500)
            if page.is_visible("#call") and page.is_enabled("#btn-giveup"):
                page.click("#btn-giveup")
                page.wait_for_selector("#call-log .call-bubble.is-explain, #call-log .call-bubble.is-error", timeout=90000)
                page.wait_for_timeout(1000)
                shot("6_call_giveup")
                mark("call-giveup", t0, {"mood": page.get_attribute("#call-partner-seat", "data-mood")})
            else:
                mark("call-giveup", t0, {"skipped": "질문이 하나뿐"})
            if "finish" not in want:
                return out

            t0 = time.time()
            report["bubbles"] = bubbles()
            page.click("#btn-leave")
            page.wait_for_selector("#qa-done:not([hidden])", timeout=5000)
            page.wait_for_timeout(500)
            shot("7_finish")
            mark("finish", t0, {"tally": page.evaluate("Array.from(document.querySelectorAll('#qa-tally li')).map(li => li.textContent)")})
            return out
        finally:
            if not report["bubbles"]:
                try:
                    report["bubbles"] = bubbles()
                except Exception:
                    pass
            report["total_sec"] = round(time.time() - t_all, 1)
            (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            b.close()
            errs = [c for c in report["console"] if not c.startswith("warning")]
            print(f"결과: {out.relative_to(ROOT)}  콘솔 오류 {len(errs)}개" + (" — " + errs[0][:120] if errs else ""))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="labs/qa_call/run.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=STAGES + ["all", "freeze"])
    ap.add_argument("--base", default="http://127.0.0.1:8801")
    ap.add_argument("--mobile", action="store_true")
    ap.add_argument("--photos", nargs="*", default=[str(HERE / "fixture_slide1.jpg"), str(HERE / "fixture_slide2.jpg")])
    ns = ap.parse_args(argv)
    if ns.stage == "freeze":
        freeze()
        return 0
    sys.path.insert(0, str(HERE))
    run(ns.stage, ns.base, ns.mobile, [Path(x) for x in ns.photos])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
