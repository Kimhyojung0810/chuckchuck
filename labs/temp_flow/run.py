"""
통화 배치 흐름 실험실 — 주소창 /temp 로 들어가 업로드 → 발표(자료 정면 + 내 모습 오른쪽 아래) → 분석 →
Q&A(내 모습 가운데) → 결과 → 리포트를 **실 API 브리지**로 한 번 태우고 단계별 사진을 남긴다.

가짜 카메라(labs/qa_call/fakecam.py 의 사람 실루엣 MJPEG)와 가짜 마이크(실제 발표 음성 wav, labs/app_flow 와 같은 것)를
크롬에 물린다. 실 LLM·STT 과금이 난다.

    .venv/bin/python labs/temp_flow/run.py                         # 기본: 8799, 집중 알림 PPTX
    .venv/bin/python labs/temp_flow/run.py --base http://127.0.0.1:8811 --until rehearsal

결과: labs/temp_flow/out/<stamp>/*.png + report.json (단계 시간·배치 검사·콘솔 오류)
libasound 가 없는 서버면 LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu (labs/qa_call/README.md).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
sys.path.insert(0, str(ROOT / "labs/qa_call"))

from fakecam import build as build_cam  # noqa: E402


def _app_flow():
    """labs/app_flow/run.py — 이 파일도 run.py 라 이름으로 import 하면 자기 자신을 잡는다"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("app_flow_run", ROOT / "labs/app_flow/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_AF = _app_flow()
DEFAULT_FILE, DEMO_MARKERS, fake_audio = _AF.DEFAULT_FILE, _AF.DEMO_MARKERS, _AF.fake_audio

UNTIL = ["rehearsal", "analysis", "qa", "report"]
ANSWER = "알림을 잠깐 보는 5초가 문제가 아니라, 원래 작업으로 돌아오는 데 드는 재집중 시간이 더 커서 집중이 크게 끊겨요"

# 배치 검사 — 무엇이 메인이고 작은 창이 어디 있는지, 조작 버튼이 실제로 눌리는지
LAYOUT_JS = """() => {
  const L = document.getElementById('cfCall');
  if (!L) return { layer: false };
  const r = (el) => { if (!el) return null; const b = el.getBoundingClientRect();
    return [Math.round(b.left), Math.round(b.top), Math.round(b.width), Math.round(b.height)]; };
  const hit = (sel) => { const b = document.querySelector(sel); if (!b || b.hidden || !b.offsetParent) return null;
    const q = b.getBoundingClientRect(); const h = document.elementFromPoint(q.left + q.width / 2, q.top + q.height / 2);
    return !!h && (h === b || b.contains(h)); };
  const self = document.getElementById('cfSelf'), slides = document.getElementById('cfSlides');
  const v = document.getElementById('cfSelfVideo');
  return { layer: true, mode: L.dataset.mode, main: L.dataset.main, W: innerWidth, H: innerHeight,
    self: r(self), slides: r(slides), camera: self && self.dataset.camera,
    video_live: !!(v && v.srcObject && v.videoWidth > 0), video_wh: v ? [v.videoWidth, v.videoHeight] : null,
    self_note: (document.getElementById('cfSelfNote') || {}).textContent || '',
    canvas: r(document.getElementById('slidePdfCanvas')),
    hscroll: document.documentElement.scrollWidth > innerWidth,
    clickable: Object.fromEntries(['#recStart', '#recEnd', '#liveSend', '#liveMic', '#cfCamToggle', '.cf-dock [data-slide-nav="1"]']
      .map((s) => [s, hit(s)])) };
}"""


def run(args) -> Path:
    from playwright.sync_api import sync_playwright

    out = OUT / datetime.now().strftime("%Y%m%dT%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    want = UNTIL[: UNTIL.index(args.until) + 1]
    cam = build_cam(OUT / "fakecam.mjpeg")
    audio = fake_audio(args.rec_sec + 20)
    report: dict = {"base": args.base, "file": str(args.file), "stages": {}, "layout": {}, "console": [], "requests": []}
    n = {"i": 0}

    def shot(name: str) -> None:
        n["i"] += 1
        page.screenshot(path=str(out / f"{n['i']:02d}_{name}.png"))

    def mark(name: str, t0: float, extra: dict | None = None) -> None:
        report["stages"][name] = {"sec": round(time.time() - t0, 1), **(extra or {})}
        print(f"  {name:12s} {report['stages'][name]['sec']:6.1f}s  {json.dumps(extra or {}, ensure_ascii=False)[:220]}")

    def layout(name: str) -> dict:
        lay = page.evaluate(LAYOUT_JS)
        report["layout"][name] = lay
        return lay

    def at_sizes(tag: str) -> None:
        for vw, vh in [(1280, 800), (1440, 900), (390, 844)]:
            page.set_viewport_size({"width": vw, "height": vh})
            page.wait_for_timeout(700)
            layout(f"{tag}_{vw}x{vh}")
            shot(f"{tag}_{vw}x{vh}")
        page.set_viewport_size({"width": 1280, "height": 800})
        page.wait_for_timeout(400)

    with sync_playwright() as p:
        flags = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                 f"--use-file-for-fake-video-capture={cam}", "--autoplay-policy=no-user-gesture-required"]
        if audio:
            flags.append(f"--use-file-for-fake-audio-capture={audio}")
        b = p.chromium.launch(args=flags)
        ctx = b.new_context(viewport={"width": 1280, "height": 800}, permissions=["camera", "microphone"])
        page = ctx.new_page()
        page.on("console", lambda m: report["console"].append(f"{m.type}: {m.text}"[:300])
                if m.type == "error" or (m.type == "warning" and "GL Driver" not in m.text) else None)
        page.on("pageerror", lambda e: report["console"].append(f"pageerror: {e}"[:300]))
        page.on("response", lambda r: report["requests"].append({"path": r.url.split(args.base)[-1][:90], "status": r.status})
                if "/api/" in r.url else None)
        try:
            # ── 1. /temp 입구 → 업로드 ─────────────────────────────────
            t0 = time.time()
            page.goto(f"{args.base}/temp", wait_until="networkidle")
            entry_hash = page.evaluate("location.hash")
            flag = page.evaluate("callFlowOn()")
            page.wait_for_selector("#file", state="attached")
            page.set_input_files("#file", str(args.file))
            page.wait_for_selector("#next, .accident", timeout=300000)
            mark("upload", t0, {"entry_hash": entry_hash, "call_flow": flag, "slides": page.evaluate("(nf.slideTitles||[]).length"),
                                "pdf": page.evaluate("!!uploadedPdf")})
            page.click("#next")
            page.wait_for_selector("#go")
            page.fill("#ctx", "대학 교양 수업에서 학생 30명 앞에서 발표해요")
            page.click("#go")

            # ── 2. 발표 — 자료 정면, 내 모습 오른쪽 아래 ───────────────
            t0 = time.time()
            page.wait_for_selector("#cfCall #recStart")
            page.wait_for_timeout(2500)
            at_sizes("present_idle")
            page.click("#recStart")
            page.wait_for_selector("#recEnd", timeout=20000)
            page.wait_for_timeout(1500)
            page.click('.cf-dock [data-slide-nav="1"]')
            page.wait_for_timeout(1200)
            at_sizes("present_live")
            # 작은 창을 누르면 자리가 바뀌고, 다시 누르면 돌아온다
            page.click("#cfSelf")
            page.wait_for_timeout(700)
            swapped = layout("present_swapped")
            shot("present_swapped")
            page.click("#cfSlides")
            page.wait_for_timeout(700)
            mark("rehearsal", t0, {"slide": page.evaluate("nf.slide"), "mic": page.evaluate("nf.mic"),
                                   "swap_main": swapped.get("main")})
            if "analysis" not in want:
                return out
            n_slides = page.evaluate("rehearsalCount()")
            step = max(3, args.rec_sec // max(1, min(n_slides, 6)))
            waited = 0
            while waited < args.rec_sec:
                page.wait_for_timeout(step * 1000)
                waited += step
                if waited < args.rec_sec and page.is_visible('.cf-dock [data-slide-nav="1"]'):
                    page.click('.cf-dock [data-slide-nav="1"]')

            # ── 3. 발표 마치기 → 분석 ─────────────────────────────────
            t0 = time.time()
            page.click("#recEnd")
            page.wait_for_timeout(4500)
            shot("after_end")
            layer_after_end = page.evaluate("!!document.getElementById('cfCall')")
            deadline = time.time() + args.pipe_timeout
            while time.time() < deadline:
                if page.evaluate("typeof pipelineQaReady === 'function' && pipelineQaReady()"):
                    break
                if page.evaluate("nf.pipelinePhase") in ("error",):
                    break
                page.wait_for_timeout(2000)
            shot("analysis_ready")
            mark("analysis", t0, {"phase": page.evaluate("nf.pipelinePhase"), "error": page.evaluate("nf.pipelineError"),
                                  "layer_gone_after_end": not layer_after_end,
                                  "cam_kept": page.evaluate("!!(callCam.stream)")})
            if "qa" not in want:
                return out

            # ── 4. Q&A — 내 모습 가운데 ───────────────────────────────
            t0 = time.time()
            page.evaluate("location.hash = '#/qa'")
            page.wait_for_timeout(800)
            if page.is_visible("#qaGateStart"):
                shot("qa_gate")
                page.click("#qaGateStart")
            page.wait_for_selector("#cfCall #liveAnswer, .accident", timeout=240000)
            page.wait_for_timeout(2000)
            txt = page.inner_text("#cfCall") if page.query_selector("#cfCall") else page.inner_text("#app")
            at_sizes("qa_ask")
            mark("qa", t0, {"live": page.evaluate("qaLiveActive()"), "n_questions": page.evaluate("qa.live ? qa.live.questions.length : 0"),
                            "counter": page.evaluate("(document.getElementById('cfQaCount')||{}).textContent"),
                            "demo_hits": [m for m in DEMO_MARKERS if m in txt]})
            page.click("#cfQuestList")
            page.wait_for_timeout(500)
            shot("qa_quest_list")
            page.click("#cfQuestList")
            page.click("#liveAnswer")
            page.keyboard.type(ANSWER, delay=4)
            page.click("#liveSend")
            page.wait_for_timeout(700)
            shot("qa_judging")
            page.wait_for_function("qa.live && !qa.live.busy", timeout=180000)
            page.wait_for_timeout(1500)
            at_sizes("qa_judged")
            mark("qa_answer", time.time(), {"judgement": page.evaluate("qa.live.lastJudgement ? {verdict: qa.live.lastJudgement.verdict, score: qa.live.lastJudgement.score} : null"),
                                            "counter": page.evaluate("(document.getElementById('cfQaCount')||{}).textContent")})
            if "report" not in want:
                return out

            # ── 5. 여기까지 → 결과(일반 배치) → 리포트 ────────────────
            t0 = time.time()
            page.click("#liveFinish")
            page.wait_for_timeout(1500)
            if page.is_visible("#liveSeeResult"):
                page.click("#liveSeeResult")
                page.wait_for_timeout(1500)
            shot("qa_result")
            res = {"layer_gone": page.evaluate("!document.getElementById('cfCall')"),
                   "cam_stopped": page.evaluate("!callCam.stream")}
            page.evaluate("location.hash = '#/report'")
            page.wait_for_timeout(4000)
            shot("report")
            txt = page.inner_text("#app")
            page.evaluate("location.hash = '#/'")
            page.wait_for_timeout(800)
            mark("report", t0, {**res, "demo_hits": [m for m in DEMO_MARKERS if m in txt],
                                "flag_cleared_home": not page.evaluate("callFlowOn()")})
        except Exception as e:  # 사진은 남긴다
            report["error"] = f"{type(e).__name__}: {e}"[:600]
            print("  실패:", report["error"])
            try:
                shot("error")
            except Exception:
                pass
        finally:
            (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            b.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8799")
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--until", choices=UNTIL, default="report")
    ap.add_argument("--rec-sec", type=int, default=40)
    ap.add_argument("--pipe-timeout", type=int, default=600)
    args = ap.parse_args()
    os.environ.setdefault("LD_LIBRARY_PATH", "/tmp/pwlibs/usr/lib/x86_64-linux-gnu")
    t = time.time()
    out = run(args)
    print(f"끝 {time.time() - t:.0f}s → {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
