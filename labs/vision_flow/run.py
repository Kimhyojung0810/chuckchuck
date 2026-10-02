"""
비전 리허설 실험실 — #/vision(카메라가 바탕, 그 앞에 발표 자료와 삐약이)을 헤드리스 크롬으로 띄워 사진과 배치 검사를 남긴다.

서버의 지난 파싱본(ppt/<덱> 을 /test/qa 로 한 번 연 것)을 되살려 자료로 쓰고, 가짜 카메라(labs/qa_call/fakecam.py)와
가짜 마이크(실제 발표 음성 wav, labs/app_flow 와 같은 것)를 크롬에 물린다. 녹음을 켜고 몇 초 말한 뒤 일반 배치로 바꾸기만 하고
「발표 끝내기」는 누르지 않는다 — 받아쓰기·분석 — LLM 과금 없음 (자료 되살리기는 캐시, 선분석 개념·그래프만 돈다).

    .venv/bin/python labs/vision_flow/run.py --base http://127.0.0.1:8803
    .venv/bin/python labs/vision_flow/run.py --base http://127.0.0.1:8803 --deck 수면발표

결과: labs/vision_flow/out/<stamp>/*.png + report.json (배치 · 카메라 · 삐약이 반응 · 끌기/크기/불투명도 · 콘솔 오류)
libasound 가 없는 서버면 LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu (labs/qa_call/README.md).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
sys.path.insert(0, str(ROOT / "labs/qa_call"))

from fakecam import build as build_cam  # noqa: E402


def _app_flow():
    spec = importlib.util.spec_from_file_location("app_flow_run", ROOT / "labs/app_flow/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fake_audio = _app_flow().fake_audio

LAYOUT_JS = """() => {
  const L = document.getElementById('vrCall');
  if (!L) return { layer: false, hash: location.hash, app: (document.getElementById('app')||{}).innerText?.slice(0, 120) };
  const r = (el) => { if (!el) return null; const b = el.getBoundingClientRect();
    return [Math.round(b.left), Math.round(b.top), Math.round(b.width), Math.round(b.height)]; };
  const hit = (sel) => { const b = document.querySelector(sel); if (!b || b.hidden || !b.offsetParent) return null;
    const q = b.getBoundingClientRect(); const h = document.elementFromPoint(q.left + q.width / 2, q.top + q.height / 2);
    return !!h && (h === b || b.contains(h)); };
  const v = document.getElementById('vrSelfVideo');
  const bird = document.getElementById('vrBird');
  const slide = document.getElementById('vrSlide');
  return { layer: true, W: innerWidth, H: innerHeight, hash: location.hash,
    hscroll: document.documentElement.scrollWidth > innerWidth || L.scrollWidth > L.clientWidth,
    sidenav_hidden: getComputedStyle(document.querySelector('.sidenav')).visibility === 'hidden',
    camera: (document.getElementById('vrSelf') || {}).dataset?.camera, video_live: !!(v && v.srcObject && v.videoWidth > 0),
    self_note: (document.getElementById('vrSelfNote') || {}).textContent || '',
    slide: r(slide), slide_alpha: slide ? getComputedStyle(slide).getPropertyValue('--vr-slide-alpha').trim() : null,
    canvas: r(document.getElementById('slidePdfCanvas')), slide_no: (document.getElementById('slideNo') || {}).textContent,
    bird: r(bird), cue: bird && bird.dataset.cue, status: (document.getElementById('vrStatus') || {}).textContent,
    hear: (document.getElementById('vrHear') || {}).hidden === false ? document.getElementById('vrHear').textContent : '',
    overlap_bird_slide: (() => { if (!bird || !slide) return null; const a = bird.getBoundingClientRect(), b = slide.getBoundingClientRect();
      return !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top); })(),
    clickable: Object.fromEntries(['#recStart', '#recEnd', '#vrCamToggle', '#vrClassic', '#vrLeave', '#vrEar', '#vrSlideDrag', '#vrSlideResize',
      '.vr-dock [data-slide-nav="1"]'].map((s) => [s, hit(s)])) };
}"""

LOAD_DECK_JS = """async (sid) => {
  resetNf(); resetQa();
  nf.sessionId = sid;
  nf.fileName = sid;
  if (typeof setUploadedPdf === 'function') setUploadedPdf(null);
  const doc = await ensureSlideDoc();
  if (!doc) return { ok: false };
  applySlideDoc(doc, { keepDemoImages: false });
  nf.fileName = doc.file_name || sid;
  nf.gate = 'done';
  nf.occ = TEST_DECK_OCC; nf.occTouched = true;
  nf.step = 1; startPrecompute(); nf.step = 2;
  saveSession('new-flow', nf);
  renderVisionEntry({ keepDeck: true });
  return { ok: true, slides: (nf.slideTitles || []).length, pdf: !!uploadedPdf };
}"""


def run(args) -> Path:
    from playwright.sync_api import sync_playwright

    out = OUT / datetime.now().strftime("%Y%m%dT%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    cam = build_cam(OUT / "fakecam.mjpeg")
    audio = fake_audio(60)
    report: dict = {"base": args.base, "deck": args.deck, "fake_audio": str(audio) if audio else None,
                    "stages": {}, "layout": {}, "console": []}
    n = {"i": 0}

    def shot(name: str) -> None:
        n["i"] += 1
        page.screenshot(path=str(out / f"{n['i']:02d}_{name}.png"))

    def layout(name: str) -> dict:
        lay = page.evaluate(LAYOUT_JS)
        report["layout"][name] = lay
        return lay

    def mark(name: str, extra: dict) -> None:
        report["stages"][name] = extra
        print(f"  {name:12s} {json.dumps(extra, ensure_ascii=False)[:300]}", flush=True)

    with urllib.request.urlopen(f"{args.base}/api/v1/dev/decks") as res:
        decks = {d["key"]: d for d in json.load(res)["decks"]}
    sid = (decks.get(args.deck) or {}).get("cached_session_id")
    if not sid:
        raise SystemExit(f"{args.deck} 의 지난 파싱본이 없어요 — /test/qa 에서 한 번 여세요")

    with sync_playwright() as p:
        flags = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                 f"--use-file-for-fake-video-capture={cam}", "--autoplay-policy=no-user-gesture-required"]
        if audio:
            flags.append(f"--use-file-for-fake-audio-capture={audio}")
        b = p.chromium.launch(args=flags)
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, permissions=["camera", "microphone"])
        page = ctx.new_page()
        if args.replay:
            # 선분석(개념 · 그래프) 응답을 다른 실험실이 남긴 기록으로 재생한다 — 과금 없이 (예: labs/booth_qa/out/rec_focus)
            for path, name in (("/api/v1/concepts", "concepts.json"), ("/api/v1/graph", "graph.json")):
                f = Path(args.replay) / name
                if f.exists():
                    page.route(f"**{path}", _replayer(f.read_text()))
        page.on("console", lambda m: report["console"].append(f"{m.type}: {m.text}"[:300])
                if m.type == "error" or (m.type == "warning" and "GL Driver" not in m.text) else None)
        page.on("pageerror", lambda e: report["console"].append(f"pageerror: {e}"[:300]))
        try:
            # ── 1. 주소창 /vision (자료 없음) → 새 연습 업로드 화면으로 가는가 ──
            page.goto(f"{args.base}/vision", wait_until="load")
            page.wait_for_timeout(1500)
            mark("entry_empty", {"hash": page.evaluate("location.hash"), "flag": page.evaluate("visionFlowOn()"),
                                 "upload": page.evaluate("!!document.getElementById('file')")})
            shot("entry_empty")

            # ── 2. 자료를 되살려 비전 리허설 ─────────────────────────────
            r = page.evaluate(LOAD_DECK_JS, sid)
            page.wait_for_selector("#vrCall #recStart", timeout=20000)
            page.wait_for_timeout(3000)
            lay = layout("idle_1440")
            shot("idle_1440")
            mark("vision", {**r, "camera": lay.get("camera"), "video_live": lay.get("video_live"), "cue": lay.get("cue"),
                            "status": lay.get("status"), "overlap": lay.get("overlap_bird_slide"), "hear": lay.get("hear")})
            for vw, vh in [(1920, 1080), (1280, 800), (390, 844)]:
                page.set_viewport_size({"width": vw, "height": vh})
                page.wait_for_timeout(800)
                layout(f"idle_{vw}")
                shot(f"idle_{vw}")
            page.set_viewport_size({"width": 1440, "height": 900})
            page.wait_for_timeout(600)

            # ── 3. 녹음 — 가짜 마이크가 말하면 삐약이가 반응하는가 ──────────
            page.click("#recStart")
            page.wait_for_selector("#recEnd", timeout=20000)
            cues = []
            for _ in range(24):
                page.wait_for_timeout(500)
                cues.append(page.evaluate("(document.getElementById('vrBird')||{}).dataset?.cue || ''"))
            page.click('.vr-dock [data-slide-nav="1"]')
            page.wait_for_timeout(1200)
            lay = layout("recording")
            shot("recording")
            mark("recording", {"mic": page.evaluate("nf.mic"), "cues_seen": sorted(set(cues)), "slide_no": lay.get("slide_no"),
                               "caption": page.evaluate("(document.getElementById('vrCaption')||{}).textContent || ''")[:60]})

            # ── 4. 자료 창 — 끌기 · 크기 · 불투명도 · 두 번 눌러 제자리 ────────
            before = page.evaluate("(() => { const b = document.getElementById('vrSlide').getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; })()")
            grip = page.locator("#vrSlideDrag").bounding_box()
            page.mouse.move(grip["x"] + 5, grip["y"] + 5)
            page.mouse.down()
            page.mouse.move(grip["x"] + 185, grip["y"] + 85, steps=6)
            page.mouse.up()
            rz = page.locator("#vrSlideResize").bounding_box()
            page.mouse.move(rz["x"] + 4, rz["y"] + 4)
            page.mouse.down()
            page.mouse.move(rz["x"] - 116, rz["y"] - 76, steps=6)
            page.mouse.up()
            page.fill("#vrSlideAlpha", "45")
            page.dispatch_event("#vrSlideAlpha", "input")
            page.dispatch_event("#vrSlideAlpha", "change")
            page.wait_for_timeout(700)
            after = page.evaluate("(() => { const b = document.getElementById('vrSlide').getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; })()")
            shot("slide_moved")
            saved = page.evaluate("sessionStorage.getItem('cheokcheok:vision-slide')")
            page.dblclick("#vrSlideDrag")
            page.wait_for_timeout(600)
            back = page.evaluate("(() => { const b = document.getElementById('vrSlide').getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; })()")
            mark("slide_box", {"before": [round(x) for x in before], "after": [round(x) for x in after],
                               "back": [round(x) for x in back], "saved": saved,
                               "alpha": page.evaluate("getComputedStyle(document.getElementById('vrSlide')).getPropertyValue('--vr-slide-alpha').trim()")})

            # ── 5. 녹음 중 「일반 리허설」 → 확인창 뒤 일반 배치로 (녹음은 이어진다 · 분석은 안 태운다) ──
            page.once("dialog", lambda d: d.accept())
            page.click("#vrClassic")
            page.wait_for_timeout(1500)
            shot("classic")
            mark("classic", {"hash": page.evaluate("location.hash"), "flag": page.evaluate("visionFlowOn()"),
                             "layer": page.evaluate("!!document.getElementById('vrCall')"), "mic": page.evaluate("nf.mic"),
                             # vision 은 질문 코칭을 통화 배치로 잇느라 통화 흐름을 켜 둔다 — 일반 리허설은 통화 배치(#cfCall) 발표 화면이다
                             "call_layer": page.evaluate("!!document.getElementById('cfCall')"),
                             "rec_panel": page.evaluate("!!document.getElementById('recPanel')"),
                             "cam_off": page.evaluate("!visionCam.stream")})
            page.evaluate("location.hash = '#/'")
            page.wait_for_timeout(800)
            leave_flag = page.evaluate("visionFlowOn()")
            # ── 6. vision·통화 흐름이 꺼진 일반 리허설은 예전 그대로인가 (팀이면 「얼굴이랑 삐약이랑 같이 보기」 버튼) ──
            page.evaluate("""async (sid) => {
              if (typeof stopLiveRehearsal === 'function') stopLiveRehearsal();
              callFlowSet(false); visionFlowSet(false);
              resetNf(); resetQa(); nf.sessionId = sid; setUploadedPdf(null);
              const doc = await ensureSlideDoc(); applySlideDoc(doc, { keepDemoImages: false });
              nf.gate = 'done'; nf.occ = TEST_DECK_OCC; nf.step = 2; saveSession('new-flow', nf);
              location.hash = '#/new';
            }""", sid)
            page.wait_for_selector("#app #recPanel", timeout=15000)
            page.wait_for_timeout(1200)
            shot("plain_rehearsal")
            mark("plain", {"vision_layer": page.evaluate("!!document.getElementById('vrCall')"),
                           "call_layer": page.evaluate("!!document.getElementById('cfCall')"),
                           "open_vision_btn": page.evaluate("!!document.getElementById('openVision')")})
            if page.query_selector("#openVision"):
                page.click("#openVision")
                page.wait_for_selector("#vrCall #recStart", timeout=15000)
                page.wait_for_timeout(1500)
                shot("open_vision_from_plain")
                mark("open_vision", {"flag": page.evaluate("visionFlowOn()"), "slides": page.evaluate("(nf.slideTitles||[]).length"),
                                     "slide_no": page.evaluate("(document.getElementById('slideNo')||{}).textContent")})
            page.evaluate("location.hash = '#/'")
            page.wait_for_timeout(800)
            mark("leave", {"flag_off_first": not leave_flag, "flag_off": not page.evaluate("visionFlowOn()"), "layer_gone": page.evaluate("!document.getElementById('vrCall')"),
                           "cam_off": page.evaluate("!visionCam.stream")})
        except Exception as e:  # 사진은 남긴다
            report["error"] = f"{type(e).__name__}: {e}"[:600]
            print("  실패:", report["error"], flush=True)
            try:
                shot("error")
            except Exception:
                pass
        finally:
            (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            b.close()
    return out


def _replayer(body: str):
    def handle(route):
        route.fulfill(status=200, content_type="application/json", body=body)
    return handle


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8799")
    ap.add_argument("--deck", default="focus_notification")
    ap.add_argument("--replay", default="", help="개념 · 그래프 응답 기록 폴더 (labs/booth_qa/out/rec_focus) — 과금 없이")
    args = ap.parse_args()
    os.environ.setdefault("LD_LIBRARY_PATH", "/tmp/pwlibs/usr/lib/x86_64-linux-gnu")
    t = time.time()
    out = run(args)
    rep = json.loads((out / "report.json").read_text())
    errs = [c for c in rep["console"] if c.startswith(("error", "pageerror"))]
    print(f"끝 {time.time() - t:.0f}s → {out.relative_to(ROOT)} · 콘솔 오류 {len(errs)}건")
    for e in errs[:8]:
        print("   ", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
