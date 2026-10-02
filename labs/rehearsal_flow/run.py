"""
리허설 한 줄 흐름 실험실 — 주소창 /rehearsal 로 들어가 발표 고르기 → 비전 리허설(가짜 카메라 · 가짜 마이크로 몇 장 발표) →
분석 기다림(부스 「질문 준비」 모양) → 글라스 화상판(자동 받아쓰기로 답) → 상세 리포트(#/report) 까지 헤드리스 크롬으로 한 번 태운다.

이 서버엔 웹캠 · 마이크가 없다. 카메라는 부스 실험실의 얼굴 영상(labs/booth_qa face_cam), 마이크는 고른 덱의 실제 발표 녹음을
앞에서 잘라 쓴다(ffmpeg). 받아쓰기(Web Speech)는 크롬 헤드리스에 없어서 가짜 webkitSpeechRecognition 을 심는다 —
window.__fakeSay("말") 을 부르면 그 말이 확정 전 조각 → 확정으로 흘러 들어온다(비전 리허설의 삐약이 반응 · 화상판 자동 받아쓰기 둘 다).

    # 실 API 한 번 — 받아쓰기 · 개념 · 그래프 · 정합 · 흐름 · 질문 · 판정 응답을 --record 폴더에 남긴다 (과금)
    LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu .venv/bin/python labs/rehearsal_flow/run.py \
        --base http://127.0.0.1:8805 --record labs/rehearsal_flow/out/rec_income
    # 그 뒤로는 과금 없이 — 남긴 응답을 재생하고 판정은 가짜(--fake-judge)
    .venv/bin/python labs/rehearsal_flow/run.py --base http://127.0.0.1:8805 --replay labs/rehearsal_flow/out/rec_income --fake-judge
    # 새로고침 · 뒤로 가기 · 나간 뒤 표시가 남는지 (재생 + 가짜 판정)
    .venv/bin/python labs/rehearsal_flow/run.py --base http://127.0.0.1:8805 --replay labs/rehearsal_flow/out/rec_income --fake-judge --reload

결과: labs/rehearsal_flow/out/<stamp>/*.png + report.json (단계 시간 · 배치 · 자료 창 상자 · 표시 · 콘솔 오류 · 글자 대비)
사진은 단계마다 --viewport(기본 1512x860 · DPR 2)와 --sizes(기본 1180x820 아이패드)로 찍는다.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"


def _booth():
    spec = importlib.util.spec_from_file_location("booth_qa_run", ROOT / "labs/booth_qa/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _booth()

DECK_AUDIO = {   # 덱의 실제 발표 녹음 (ppt/<덱>/ — git 에 안 올린다)
    "수익률격차": "최종녹음본_척척발표.m4a",
    "미세플라스틱물벼룩번식A": "B-1 녹음.m4a",
    "배달앱별점인플레이션A": "C-1 녹음.m4a",
}
# 비전 리허설 동안 가짜 받아쓰기로 흘릴 말 — 삐약이가 빠르기에 반응하는지 본다 (녹음 · 분석에는 안 쓰인다: 분석은 가짜 마이크 소리를 받아쓴다)
VISION_SAYS = [
    "오늘은 개인 투자자가 왜 시장 수익률을 따라가지 못하는지 이야기하겠습니다",
    "핵심은 종목 선택보다 잦은 매매와 추격 매수 같은 행동이 격차를 만든다는 점입니다",
    "다음 장에서는 그 근거가 되는 연구 결과를 보겠습니다",
]
# 화상판에서 말로 할 답 (자동 받아쓰기 → 2.2초 조용 → 3초 초읽기 → 자동 보내기)
SPOKEN = {
    "수익률격차": "개인 투자자는 잦은 매매와 추격 매수 때문에 시장보다 수익률이 낮아요. 종목보다 거래 행동이 격차를 만들어요.",
    "배달앱별점인플레이션A": "별점이 4.7 근처에 몰리는 건 낮은 별점을 주기 부담스러워서 다들 높게 주기 때문이에요. 그래서 별점만으로는 가게 차이를 구별하기 어려워요.",
}
RECORD_PATHS = {
    "/api/v1/transcribe": "transcribe.json", "/api/v1/concepts": "concepts.json", "/api/v1/graph": "graph.json",
    "/api/v1/alignment": "alignment.json", "/api/v1/flow": "flow.json", "/api/v1/pace": "pace.json",
    "/api/v1/habits": "habits.json", "/api/v1/rubric": "rubric.json", "/api/v1/report": "voice_report.json",
    "/api/v1/questions": "questions.json",
}

FAKE_SPEECH_JS = """
(() => {
  const live = new Set();
  window.__fakeRecCount = 0;
  window.__fakeSay = (text) => { live.forEach((r) => r.__say(String(text))); return live.size; };
  window.__fakeListening = () => live.size;
  class FakeRecognition {
    constructor() { this.lang = ''; this.continuous = false; this.interimResults = false; this._on = false; this._done = []; }
    start() { if (this._on) return; this._on = true; live.add(this); window.__fakeRecCount += 1; }
    stop() { if (!this._on) return; this._on = false; live.delete(this); setTimeout(() => this.onend && this.onend(), 10); }
    abort() { this.stop(); }
    __say(text) {
      const words = text.split(' ');
      const idx = this._done.length;
      let i = 0;
      const emit = () => {
        if (!this._on) return;
        i += 1;
        const fin = i >= words.length;
        const cur = Object.assign([{ transcript: (idx ? ' ' : '') + words.slice(0, i).join(' ') }], { isFinal: fin });
        const results = this._done.slice();
        results[idx] = cur;
        if (fin) this._done[idx] = cur;
        if (this.onresult) this.onresult({ resultIndex: idx, results });
        if (!fin) setTimeout(emit, 110);
      };
      emit();
    }
  }
  window.SpeechRecognition = FakeRecognition;
  window.webkitSpeechRecognition = FakeRecognition;
})();
"""

LAYOUT_JS = """() => {
  const L = document.getElementById('bqStage');
  const r = (el) => { if (!el || !el.getBoundingClientRect) return null; const b = el.getBoundingClientRect();
    return [Math.round(b.left), Math.round(b.top), Math.round(b.width), Math.round(b.height)]; };
  const hit = (sel) => { const b = document.querySelector(sel); if (!b || b.hidden || !b.offsetParent) return null;
    const q = b.getBoundingClientRect(); const h = document.elementFromPoint(q.left + q.width / 2, q.top + q.height / 2);
    return !!h && (h === b || b.contains(h)); };
  const box = (sel) => { const el = document.querySelector(sel); if (!el || !el.offsetParent) return null; const q = el.getBoundingClientRect();
    const st = el.closest('#stream'); if (!st) return q; const c = st.getBoundingClientRect(); const top = Math.max(q.top, c.top), bottom = Math.min(q.bottom, c.bottom);
    return bottom <= top ? null : { left: q.left, right: q.right, top, bottom }; };
  const over = (a, b) => { const x = box(a), y = box(b); return !!x && !!y && x.right > y.left + 1 && x.left < y.right - 1 && x.bottom > y.top + 1 && x.top < y.bottom - 1; };
  const pairs = [['#vrSlide', '.bc-dock'], ['#vrSlide', '.bc-host'], ['#vrSlide', '.bc-ask'], ['#vrSlide', '.bc-prog .bq-prog'],
    ['.bc-dock', '.bc-host'], ['.bc-talk', '.bc-dock'], ['.bc-ask', '.bq-top .bq-ghost'], ['.bc-ask', '.bq-brand'], ['#stream > .msg:last-child', '.bc-host']];
  const flags = {}; ['cheokcheok:rehearsal-flow', 'cheokcheok:vision-flow', 'cheokcheok:call-flow', 'cheokcheok:booth-qa', 'cheokcheok:booth-variant']
    .forEach((k) => { flags[k.split(':')[1]] = sessionStorage.getItem(k); });
  return { hash: location.hash, W: innerWidth, H: innerHeight, layer: !!L, screen: L ? L.dataset.screen : null, flow: L ? L.dataset.flow || '' : null,
    variant: L ? L.dataset.variant : null, vision: !!document.getElementById('vrCall'), flags,
    hscroll: document.documentElement.scrollWidth > innerWidth || (!!L && L.scrollWidth > L.clientWidth)
      || [...document.querySelectorAll('#bqStage .bq-body')].some((b) => b.scrollWidth > b.clientWidth + 1),
    overlaps: pairs.filter(([a, b]) => over(a, b)).map(([a, b]) => `${a} × ${b}`),
    cut_off: innerWidth <= 900 || !L ? [] : [...L.querySelectorAll('button')].filter((b) => b.offsetParent).filter((b) => { const q = b.getBoundingClientRect();
      const sc = b.closest('.bq-body'); const scrolls = sc && /auto|scroll/.test(getComputedStyle(sc).overflowY) && sc.scrollHeight > sc.clientHeight + 1;
      return q.width > 0 && !scrolls && (q.bottom > innerHeight + 1 || q.right > innerWidth + 1); }).map((b) => (b.id || b.textContent.trim()).slice(0, 24)),
    slide: r(document.querySelector('#bqStage #vrSlide')), slot: r(document.querySelector('#bqStage .rh-slide-slot')),
    slide_alpha: (() => { const s = document.querySelector('#bqStage #vrSlide'); return s ? getComputedStyle(s).getPropertyValue('--vr-slide-alpha').trim() : null; })(),
    vision_slide: r(document.querySelector('#vrCall #vrSlide')),
    ask: r(document.getElementById('bcAsk')), dock: r(document.querySelector('.bc-dock')), host: r(document.getElementById('bcHost')),
    glass: (() => { const g = document.querySelector('#bqStage .bc-glass'); if (!g) return null; const c = getComputedStyle(g);
      return { bg: c.backgroundColor, bgi: c.backgroundImage.slice(0, 40), filter: c.backdropFilter || c.webkitBackdropFilter }; })(),
    say: (document.getElementById('bqJudgeSay') || {}).textContent || '',
    videos: [...document.querySelectorAll('#bqStage video, #vrCall video')].map((v) => ({ w: v.videoWidth, paused: v.paused, vis: getComputedStyle(v).visibility,
      tracks: v.srcObject ? v.srcObject.getVideoTracks().map((t) => `${t.readyState}:${t.enabled}:${t.muted}`) : null })),
    cam_box: (document.querySelector('#bqStage [data-bq-cam-box]') || {}).dataset?.camera || null,
    slide_cap: (() => { const c = document.querySelector('#bqStage #vrSlide figcaption'); if (!c) return null; const p = c.offsetParent;
      return { box: r(c), parent: p ? (p.id || p.className) : null, pos: getComputedStyle(c).position, fig: getComputedStyle(c.parentElement).position }; })(),
    clickable: Object.fromEntries(['#bqGo', '#liveSend', '#liveMic', '#liveFinish', '#bqCamToggle', '[data-rh-exit]', '#vrSlideDrag', '#vrSlideAlpha', '#recStart', '#recEnd']
      .map((s) => [s, hit(s)])) };
}"""

FLAGS_JS = """() => Object.fromEntries(['rehearsal-flow', 'vision-flow', 'call-flow', 'booth-qa', 'booth-variant'].map((k) => [k, sessionStorage.getItem('cheokcheok:' + k)]))"""


class _Until(Exception):
    """--until 에서 멈춘다"""


def deck_audio(deck: str, sec: int) -> Path | None:
    name = DECK_AUDIO.get(deck)
    src = ROOT / "ppt" / deck / name if name else None
    ff = B.__dict__.get("find_ffmpeg")
    ff = (ff() if ff else None) or next((str(p) for p in [Path.home() / ".local/bin/ffmpeg"] if p.exists()), None)
    if not src or not src.exists() or not ff:
        return None
    dst = OUT / f"{deck}_{sec}s.wav"
    if not dst.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        subprocess.run([ff, "-y", "-loglevel", "error", "-t", str(sec), "-i", str(src), "-ac", "1", "-ar", "48000", "-sample_fmt", "s16", str(dst)], check=True)
    return dst


def _slow_replayer(body: str, delay: float):
    # 인자 하나짜리여야 한다 — playwright 는 인자가 둘인 처리기에 (route, request) 를 넘긴다
    def handle(route):
        time.sleep(delay)
        route.fulfill(status=200, content_type="application/json", body=body)
    return handle


def install(page, args, state: dict) -> None:
    rec = Path(args.replay) if args.replay else None
    if rec:
        for path, name in RECORD_PATHS.items():
            f = rec / name
            if not f.exists():
                continue
            if path == "/api/v1/questions" and args.replay_delay:
                # 재생은 순식간이라 기다림 화면을 못 본다 — 질문 생성만 실제처럼 몇 초 늦춘다
                page.route(f"**{path}", _slow_replayer(f.read_text(), args.replay_delay))
            else:
                page.route(f"**{path}", B._replayer(f.read_text()))
    if not args.fake_judge:
        return

    def judge(route):
        state["judge_calls"] += 1
        req = json.loads(route.request.post_data or "{}")
        q = req.get("question") or {}
        if req.get("reveal"):
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps({"answer_gist": "자료가 말한 바로잡힌 사실이에요 (실험실 가짜 골자)."}, ensure_ascii=False))
        time.sleep(0.6)
        body = B._fake_judge_body(q, "coach", "narrow") if req.get("give_up") else B._fake_judge_body(q, "good")
        state["judge_log"].append({"qid": req.get("question_id") or q.get("id"), "verdict": body["verdict"]})
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))
    page.route("**/qa/judge", judge)


def run(args) -> Path:
    from playwright.sync_api import sync_playwright

    out = OUT / (datetime.now().strftime("%Y%m%dT%H%M%S") + (f"_{args.tag}" if args.tag else ""))
    out.mkdir(parents=True, exist_ok=True)
    VW, VH = (int(x) for x in args.viewport.split("x"))
    sizes = [tuple(int(x) for x in s.split("x")) for s in (args.sizes or "").split(",") if s]
    cam = B.face_cam(B.OUT / "facecam.mjpeg")
    if args.cam == "white":
        cam = B.plain_cam(B.OUT / "whitecam.mjpeg", (246, 246, 242))
    elif args.cam == "dark":
        cam = B.plain_cam(B.OUT / "darkcam.mjpeg", (22, 24, 28))
    audio = deck_audio(args.deck, args.rec_sec + 30)
    R: dict = {"args": vars(args), "audio": str(audio) if audio else None, "stages": {}, "layout": {}, "console": [], "requests": [],
               "contrast": {}, "turns": [], "flags": {}}
    state: dict = {"judge_calls": 0, "judge_log": []}
    n = {"i": 0}
    t_start = time.time()
    rec_dir = Path(args.record) if args.record else None

    with sync_playwright() as p:
        flags = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", f"--use-file-for-fake-video-capture={cam}",
                 "--autoplay-policy=no-user-gesture-required"]
        if audio:
            flags.append(f"--use-file-for-fake-audio-capture={audio}")
        b = p.chromium.launch(args=flags)
        ctx = b.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=args.dpr, locale="ko-KR",
                            permissions=["camera", "microphone"])
        ctx.add_init_script(FAKE_SPEECH_JS)
        page = ctx.new_page()
        page.on("console", lambda m: R["console"].append(f"{m.type}: {m.text}"[:300])
                if m.type == "error" or (m.type == "warning" and "GL Driver" not in m.text) else None)
        page.on("pageerror", lambda e: R["console"].append(f"pageerror: {e}"[:300]))

        def on_resp(r):
            if "/api/" not in r.url:
                return
            R["requests"].append({"path": r.url.split(args.base)[-1][:90], "status": r.status, "t": round(time.time() - t_start, 1)})
            if rec_dir and r.status == 200:
                for path, name in RECORD_PATHS.items():
                    if r.url.split("?")[0].endswith(path):
                        try:
                            rec_dir.mkdir(parents=True, exist_ok=True)
                            (rec_dir / name).write_bytes(r.body())
                        except Exception as e:  # noqa: BLE001
                            print("  기록 실패", name, e)
        page.on("response", on_resp)
        install(page, args, state)

        def shot(name: str) -> Path:
            n["i"] += 1
            png = out / f"{n['i']:02d}_{name}.png"
            page.screenshot(path=str(png))
            if args.cam != "face" and page.evaluate("(document.getElementById('bqStage')||{dataset:{}}).dataset.screen === 'qa'"):
                R["contrast"][name] = B.glass_contrast(page, png)
            return png

        def lay(tag: str) -> dict:
            L = page.evaluate(LAYOUT_JS)
            R["layout"][tag] = L
            return L

        def sweep(tag: str, settle: int = 700) -> None:
            lay(f"{tag}_{VW}x{VH}")
            shot(f"{tag}_{VW}x{VH}")
            for w, h in sizes:
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(settle)
                lay(f"{tag}_{w}x{h}")
                shot(f"{tag}_{w}x{h}")
            if sizes:
                page.set_viewport_size({"width": VW, "height": VH})
                page.wait_for_timeout(500)

        def mark(name: str, t0: float, extra: dict | None = None) -> None:
            R["stages"][name] = {"sec": round(time.time() - t0, 1), **(extra or {})}
            print(f"  {name:12s} {R['stages'][name]['sec']:6.1f}s  {json.dumps(extra or {}, ensure_ascii=False)[:300]}", flush=True)

        def rehearse() -> None:
            # ── 2. 비전 리허설 ────────────────────────────────────────────
            t0 = time.time()
            page.click(f"#bqStage .bq-deck[data-deck='{args.deck}']")
            # 어떤 발표인가요 — 추정(F-23)이 골라 둔 상황이 있으면 그대로, 없으면 --occ 를 누른다
            page.wait_for_selector("#bqStage[data-screen='occ'] #rhGoVision", timeout=60000)
            page.wait_for_timeout(600)
            suggested = page.evaluate("nf.occ")
            if args.occ or not suggested:
                page.click(f'#bqStage .bq-role[data-occ="{args.occ or "학교 프로젝트 (교수 대상)"}"]')
            sweep("occ")
            mark("occ", t0, {"suggested": suggested, "note": page.evaluate("document.getElementById('rhOccNote').textContent"),
                             "occ": page.evaluate("nf.occ"), "aud": page.evaluate("qaAudienceWord()")})
            page.click("#rhGoVision")
            page.wait_for_selector("#vrCall #recStart", timeout=60000)
            page.wait_for_timeout(2500)
            sweep("vision_idle")
            mark("vision", t0, {"hash": page.evaluate("location.hash"), "flags": page.evaluate(FLAGS_JS),
                                "slides": page.evaluate("(nf.slideTitles||[]).length"), "session": page.evaluate("nf.sessionId"),
                                "dock": page.evaluate("[...document.querySelectorAll('#vrCall .vr-dock button')].filter(b => b.offsetParent).map(b => b.textContent.trim())"),
                                "deck_rec": page.evaluate("nf.rehearsalDeck")})
            if args.path == "rec":
                finish_with_recording(live=False)
                return
            if args.move_slide:
                # 발표하면서 자료 창을 오른쪽 위로 작게 옮기고 불투명도를 낮춘다 — 화상판이 같은 자리 · 불투명도로 이어 쓰는지 본다
                rz = page.locator("#vrSlideResize").bounding_box()
                page.mouse.move(rz["x"] + 4, rz["y"] + 4)
                page.mouse.down()
                page.mouse.move(rz["x"] - int(VW * .2), rz["y"] - int(VH * .3), steps=8)
                page.mouse.up()
                grip = page.locator("#vrSlideDrag").bounding_box()
                page.mouse.move(grip["x"] + 6, grip["y"] + 6)
                page.mouse.down()
                page.mouse.move(VW - 420, grip["y"] - int(VH * .25), steps=8)
                page.mouse.up()
                page.fill("#vrSlideAlpha", "55")
                page.dispatch_event("#vrSlideAlpha", "input")
                page.dispatch_event("#vrSlideAlpha", "change")
                page.wait_for_timeout(500)
                R["vision_slide_saved"] = page.evaluate("JSON.parse(sessionStorage.getItem('cheokcheok:vision-slide')||'null')")
            page.click("#recStart")
            page.wait_for_selector("#recEnd", timeout=30000)
            if args.path == "rec-partial":
                page.wait_for_timeout(6000)
                page.evaluate("(t) => window.__fakeSay(t)", VISION_SAYS[0])
                page.wait_for_timeout(4000)
                lay("vision_partial")
                shot("vision_partial")
                finish_with_recording(live=True)
                return
            cues = set()
            per = max(4, args.rec_sec // max(1, args.slides))
            t_rec = time.time()
            said = 0
            while time.time() - t_rec < args.rec_sec:
                el = time.time() - t_rec
                if said < len(VISION_SAYS) and el > 3 + said * 6:
                    page.evaluate("(t) => window.__fakeSay(t)", VISION_SAYS[said])
                    said += 1
                cues.add(page.evaluate("(document.getElementById('vrBird')||{}).dataset?.cue || ''"))
                if int(el) and int(el) % per == 0 and page.evaluate("Number(nf.slide)") < args.slides and page.is_visible('.vr-dock [data-slide-nav="1"]'):
                    page.click('.vr-dock [data-slide-nav="1"]')
                    page.wait_for_timeout(1000)
                page.wait_for_timeout(400)
                if el > 8 and "vision_rec" not in R["layout"]:
                    lay("vision_rec")
                    shot("vision_recording")
            mark("rehearse", t_rec, {"cues": sorted(cues), "slide": page.evaluate("nf.slide"), "sec": page.evaluate("nf.sec"),
                                     "vision_cues": page.evaluate("(nf.visionCues||[]).length")})
            if args.until == "rehearse":
                raise _Until()
            page.click("#recEnd")

        def finish_with_recording(live: bool) -> None:
            # 「녹음본을 넣어서 발표 마치기」 → 시트(이 발표의 녹음 m:ss) → 분석
            t0 = time.time()
            page.click("#rhRecFinish")
            page.wait_for_selector("#rhRecSheet [data-sheet='use']", timeout=5000)
            page.wait_for_timeout(400)
            lay("rec_sheet")
            shot("rec_sheet" + ("_after_live" if live else ""))
            sheet = page.evaluate("document.getElementById('rhRecSheet').innerText")
            page.click("#rhRecSheet [data-sheet='use']")
            page.wait_for_selector("#bqStage[data-screen='wait']", timeout=90000)
            mark("rec_finish", t0, {"sheet": sheet[:300], "uploaded": page.evaluate("nf.uploadedTake"), "mic": page.evaluate("nf.mic"),
                                    "cues": page.evaluate("(nf.visionCues||[]).length"), "hash": page.evaluate("location.hash")})

        def wait_and_qa() -> None:
            # ── 3. 분석 기다림 ───────────────────────────────────────────
            t0 = time.time()
            page.wait_for_selector("#bqStage[data-screen='wait']", timeout=90000)
            page.wait_for_timeout(2500)
            sweep("wait_early")
            steps_seen = []
            while time.time() - t0 < args.wait_timeout:
                st = page.evaluate("Object.fromEntries([...document.querySelectorAll('#bqBuildSteps li')].map(l => [l.dataset.step, l.dataset.state]))")
                if not steps_seen or steps_seen[-1][1] != st:
                    steps_seen.append((round(time.time() - t0, 1), st))
                    print("   ", steps_seen[-1], flush=True)
                if page.evaluate("location.hash === '#/qa'") or "fail" in st.values():
                    break
                if all(v == "done" for v in st.values()) and "wait_ready" not in R["layout"]:
                    lay("wait_ready")
                    shot("wait_ready")
                page.wait_for_timeout(1000)
            mark("wait", t0, {"steps": steps_seen,
                              "phase": page.evaluate("nf.pipelinePhase"), "reveal": page.evaluate("!!document.getElementById('f11RevealWrap')"),
                              "fail": page.evaluate("(document.getElementById('bqPrepFail')||{}).innerText || ''"),
                              "n_questions": page.evaluate("qa.live ? qa.live.questions.length : 0"), "hash": page.evaluate("location.hash")})
            if args.until == "wait" or page.evaluate("location.hash !== '#/qa'"):
                raise _Until()

            # ── 4. 글라스 화상판 (기다림에서 저절로 들어온다) ───────────────────────
            t0 = time.time()
            page.wait_for_selector("#bqStage[data-screen='qa'][data-flow='rehearsal'] #stream .msg.q", timeout=30000, state="attached")
            page.wait_for_timeout(3000)
            sweep("qa_ask1", settle=1200)
            mark("qa_enter", t0, {"hash": page.evaluate("location.hash"), "flags": page.evaluate(FLAGS_JS),
                                  "slide": R["layout"][f"qa_ask1_{VW}x{VH}"].get("slide"), "alpha": R["layout"][f"qa_ask1_{VW}x{VH}"].get("slide_alpha"),
                                  "saved": page.evaluate("JSON.parse(sessionStorage.getItem('cheokcheok:vision-slide')||'null')"),
                                  "idle_timer": page.evaluate("!!bqOps.idleTimer"), "ask": page.evaluate("(document.getElementById('bcAskQ')||{}).textContent||''")[:120],
                                  "mic_auto": page.evaluate("!!(typeof liveMic !== 'undefined' && liveMic)"), "aud": page.evaluate("qa.aud"),
                                  "host": page.evaluate("(document.querySelector('#bcHost .bc-host-text b')||{}).textContent||''"), "rec_listen": page.evaluate("window.__fakeListening()")})
            questions = page.evaluate("qa.live.questions.map(q => ({id: q.id, label: q.label, trap: !!q.trap, gist: q.answer_gist || ''}))")
            R["questions"] = questions
            guard, qi_prev = 0, -1
            while guard < 14:
                guard += 1
                st = page.evaluate("({qi: qa.live.qi, n: qa.live.questions.length, end: !!qa.live.awaitEnd, retell: !!qa.live.retell})")
                if st["end"] or st["qi"] >= st["n"]:
                    break
                qi = st["qi"]
                if qi != qi_prev and qi > 0:
                    page.wait_for_timeout(1500)
                    sweep(f"qa_ask{qi + 1}", settle=900)
                first = qi != qi_prev
                qi_prev = qi
                tj = time.time()
                q = questions[qi] if qi < len(questions) else {}
                if st["retell"]:
                    page.click("#liveSkipRetell") if page.is_visible("#liveSkipRetell") else page.click("#liveSend")
                    action = "skipretell"
                elif args.answer == "dictate" and first:
                    # 자동 받아쓰기 — 마이크가 저절로 켜지기를 기다렸다 말한다. 멈추면 2.2초 + 초읽기 3초 뒤 자동으로 보낸다
                    page.wait_for_function("window.__fakeListening() > 0", timeout=15000)
                    text = (q.get("gist") if q.get("gist") and not q.get("trap") else None) or SPOKEN.get(args.deck) or B.ANSWERS.get(args.deck, B.ANSWERS["수익률격차"])
                    page.evaluate("(t) => window.__fakeSay(t)", text)
                    page.wait_for_timeout(3600)
                    if qi == 0:
                        lay("qa_countdown")
                        shot("qa_countdown")
                    page.wait_for_function("qa.live.busy || qa.live.qi !== %d || (qa.live.turns||[]).length > 0" % qi, timeout=20000)
                    action = "dictate"
                else:
                    page.fill("#liveAnswer", SPOKEN.get(args.deck, "자료의 핵심은 이렇습니다."))
                    page.click("#liveSend")
                    action = "type"
                page.wait_for_timeout(400)
                page.wait_for_function("qa.live && !qa.live.busy", timeout=180000)
                page.wait_for_timeout(1500)
                turn = {"qi": qi + 1, "action": action, "sec": round(time.time() - tj, 1),
                        "say": page.evaluate("(document.getElementById('bqJudgeSay')||{}).textContent||''"),
                        "verdict": page.evaluate("qa.live.lastJudgement ? qa.live.lastJudgement.verdict : null"),
                        "buttons": page.evaluate("[...document.querySelectorAll('#bqStage .qa-live-input button')].filter(b=>b.offsetParent).map(b=>b.textContent.trim())")}
                R["turns"].append(turn)
                print(f"  Q{qi + 1} {action} {turn['sec']}s {turn['verdict']} → {turn['buttons']}", flush=True)
                if action != "skipretell" and qi == 0:
                    lay(f"q{qi + 1}_judged")
                    shot(f"q{qi + 1}_judged")
                if not st["retell"] and page.evaluate("qa.live.qi === %d && !qa.live.awaitEnd && !qa.live.retell" % qi):
                    # 되묻기 — 두 번째부터는 「모르겠어요」 → 답 보고 넘어가기로 빠져나간다 (판정 과금을 묶는다)
                    if page.is_visible("#liveReveal"):
                        page.click("#liveReveal")
                    elif page.is_visible("#liveStuck"):
                        page.click("#liveStuck")
                    page.wait_for_function("qa.live && !qa.live.busy", timeout=120000)
                    page.wait_for_timeout(800)
            page.wait_for_timeout(1500)
            sweep("qa_end", settle=900)
            mark("qa", t0, {"turns": len(R["turns"]), "end": page.evaluate("!!qa.live.awaitEnd"),
                            "see": page.evaluate("(document.getElementById('liveSeeResult')||{}).textContent||''"),
                            "finish": page.evaluate("(document.getElementById('liveFinish')||{}).textContent||''"),
                            "auto_end_timer": page.evaluate("!!bqOps.endTimer")})
            if args.until == "qa":
                raise _Until()

            # ── 5. 리포트 ────────────────────────────────────────────────
            t0 = time.time()
            page.wait_for_timeout(13000)   # 부스라면 12초 뒤 마무리 화면으로 넘어간다 — 리허설은 그대로 있어야 한다
            stayed = page.evaluate("location.hash === '#/qa' && !!document.querySelector('#bqStage[data-screen=qa]')")
            page.click("#liveSeeResult")
            page.wait_for_function("location.hash.startsWith('#/report')", timeout=20000)
            page.wait_for_timeout(3000)
            sweep("report")
            mark("report", t0, {"stayed_on_end_card_13s": stayed, "hash": page.evaluate("location.hash"), "flags": page.evaluate(FLAGS_JS),
                                "layer_gone": page.evaluate("!document.getElementById('bqStage')"), "cam_off": page.evaluate("!bq.cam.stream"),
                                "listening": page.evaluate("window.__fakeListening()"), "history": page.evaluate("(JSON.parse(localStorage.getItem('cheokcheok:qa-history')||'[]')).length"),
                                "title": page.evaluate("(document.querySelector('#app h1, #app .page-title')||{}).textContent||''")[:80]})
            # 리허설을 마친 뒤 일반 #/new · #/qa · 부스가 리허설에 끌려가지 않는지
            page.evaluate("location.hash = '#/qa'")
            page.wait_for_timeout(1500)
            after_qa = page.evaluate("({hash: location.hash, layer: !!document.getElementById('bqStage'), app: (document.getElementById('app')||{}).innerText.slice(0, 60)})")
            page.goto(f"{args.base}/booth/qa", wait_until="load")
            page.wait_for_selector("#bqStage #bqStart", timeout=20000)
            R["stages"]["after"] = {"qa": after_qa, "booth_flow": page.evaluate("(document.getElementById('bqStage')||{}).dataset.flow || ''"),
                                    "booth_flags": page.evaluate(FLAGS_JS), "booth_top": page.evaluate("document.querySelector('#bqStage .bq-brand small').textContent")}
            print("  after       ", R["stages"]["after"], flush=True)
        try:
            # ── 1. 발표 고르기 ─────────────────────────────────────────────
            t0 = time.time()
            page.goto(f"{args.base}/rehearsal", wait_until="load")
            page.wait_for_selector("#bqStage[data-flow='rehearsal'][data-screen='pick'] .bq-deck[data-deck]", timeout=30000)
            try:
                page.wait_for_function("[...document.querySelectorAll('#bqStage .bq-cover canvas')].every(c => c.parentElement.classList.contains('ready'))", timeout=40000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(500)
            sweep("pick")
            mark("pick", t0, {"hash": page.evaluate("location.hash"), "flags": page.evaluate(FLAGS_JS),
                              "cards": page.evaluate("[...document.querySelectorAll('#bqStage .bq-deck')].map(b => b.dataset.deck || 'upload')")})
            if args.until == "pick":
                return out

            rehearse()
            wait_and_qa()
        except _Until:
            pass
        except Exception as e:  # noqa: BLE001
            R["error"] = f"{type(e).__name__}: {e}"[:600]
            print("  실패:", R["error"], flush=True)
            try:
                shot("error")
                R["error_layout"] = page.evaluate(LAYOUT_JS)
            except Exception:  # noqa: BLE001
                pass
        finally:
            R["judge"] = state
            R["total_sec"] = round(time.time() - t_start, 1)
            (out / "report.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
            b.close()
    return out


RELOAD_JS = """() => { const L = document.getElementById('bqStage');
  return { hash: location.hash, layer: L ? (L.dataset.flow || 'booth') + ':' + L.dataset.screen : null, vision: !!document.getElementById('vrCall'),
    general: (() => { const a = document.getElementById('app'); return !!a && !!a.offsetParent && !L && !document.getElementById('vrCall') ? a.innerText.slice(0, 50) : ''; })(),
    flags: Object.fromEntries(['rehearsal-flow', 'vision-flow', 'call-flow', 'booth-qa'].map((k) => [k, sessionStorage.getItem('cheokcheok:' + k)])) }; }"""


def run_reload(args) -> Path:
    """단계마다 새로고침 · 뒤로 가기 · 나가기 — 리허설 안에서 다시 열리는지, 나간 뒤 표시가 남지 않는지 (재생 + 가짜 판정 전제)"""
    from playwright.sync_api import sync_playwright

    out = OUT / (datetime.now().strftime("%Y%m%dT%H%M%S") + "_reload" + (f"_{args.tag}" if args.tag else ""))
    out.mkdir(parents=True, exist_ok=True)
    VW, VH = (int(x) for x in args.viewport.split("x"))
    cam = B.face_cam(B.OUT / "facecam.mjpeg")
    audio = deck_audio(args.deck, args.rec_sec + 30)
    R: dict = {"args": vars(args), "checks": {}, "console": []}
    state: dict = {"judge_calls": 0, "judge_log": []}
    with sync_playwright() as p:
        flags = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", f"--use-file-for-fake-video-capture={cam}",
                 "--autoplay-policy=no-user-gesture-required"] + ([f"--use-file-for-fake-audio-capture={audio}"] if audio else [])
        b = p.chromium.launch(args=flags)
        ctx = b.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=1, locale="ko-KR", permissions=["camera", "microphone"])
        ctx.add_init_script(FAKE_SPEECH_JS)
        page = ctx.new_page()
        page.on("pageerror", lambda e: R["console"].append(f"pageerror: {e}"[:300]))
        page.on("console", lambda m: R["console"].append(f"{m.type}: {m.text}"[:300]) if m.type == "error" else None)
        install(page, args, state)

        def check(tag: str, *, reload: bool = True, expect: str = "") -> dict:
            if reload:
                page.reload(wait_until="load")
            page.wait_for_timeout(3500)
            c = page.evaluate(RELOAD_JS)
            c["expect"] = expect
            c["ok"] = (expect in (c["layer"] or "")) if expect and expect != "vision" else (c["vision"] if expect == "vision" else True)
            R["checks"][tag] = c
            page.screenshot(path=str(out / f"{len(R['checks']):02d}_{tag}.png"))
            print(f"  {tag:24s} {'✓' if c['ok'] else '✗'} {json.dumps(c, ensure_ascii=False)[:230]}", flush=True)
            return c

        try:
            page.goto(f"{args.base}/rehearsal", wait_until="load")
            page.wait_for_selector("#bqStage .bq-deck[data-deck]", timeout=30000)
            check("pick_reload", expect="rehearsal:pick")
            page.wait_for_selector("#bqStage .bq-deck[data-deck]", timeout=30000)
            page.click(f"#bqStage .bq-deck[data-deck='{args.deck}']")
            page.wait_for_selector("#bqStage #rhGoVision", timeout=60000)
            page.click("#rhGoVision")
            page.wait_for_selector("#vrCall #recStart", timeout=60000)
            check("vision_reload", expect="vision")
            page.wait_for_selector("#vrCall #recStart", timeout=30000)
            page.go_back()
            check("vision_back", reload=False, expect="rehearsal:pick")
            page.go_forward()
            check("vision_forward", reload=False, expect="vision")
            page.wait_for_selector("#vrCall #recStart", timeout=30000)
            page.click("#recStart")
            page.wait_for_selector("#recEnd", timeout=30000)
            page.wait_for_timeout(args.rec_sec * 1000)
            page.click("#recEnd")
            page.wait_for_selector("#bqStage[data-screen='wait']", timeout=60000)
            page.wait_for_timeout(1500)
            check("wait_reload", expect="rehearsal:")   # 새로고침이면 파이프라인이 끊긴다 — 기다림(재료가 모였으면 곧 화상판)이나 화상판이어야 한다
            page.wait_for_function("location.hash === '#/qa' || !!(document.getElementById('rhResume') && !document.getElementById('rhResume').hidden)",
                                   timeout=args.wait_timeout * 1000)
            R["checks"]["wait_reload_then"] = {"auto_entered": page.evaluate("location.hash === '#/qa'")}
            if page.evaluate("location.hash !== '#/qa'"):
                page.click("#rhResume")
            page.wait_for_selector("#bqStage[data-screen='qa']", timeout=30000)
            page.fill("#liveAnswer", SPOKEN.get(args.deck, "자료의 핵심은 이렇습니다."))
            page.click("#liveSend")
            page.wait_for_function("qa.live && !qa.live.busy", timeout=60000)
            check("qa_reload", expect="rehearsal:qa")
            page.go_back()
            c = check("qa_back", reload=False, expect="rehearsal:wait")
            c["resume_button"] = page.evaluate("!document.getElementById('rhResume').hidden")
            page.go_forward()
            check("qa_forward", reload=False, expect="rehearsal:qa")
            page.keyboard.press("Escape")
            page.keyboard.press("Escape")
            page.wait_for_timeout(600)
            R["checks"]["esc_twice"] = {"sheet": page.evaluate("!!document.getElementById('bqSheet')"), "hash": page.evaluate("location.hash"),
                                        "ok": page.evaluate("!document.getElementById('bqSheet') && location.hash === '#/qa'")}
            print("  esc_twice              ", R["checks"]["esc_twice"], flush=True)
            # 질문 상태를 잃은 채 새로고침 — 일반 질문 코칭(트랙 고르기)이 아니라 리허설 자리로
            page.evaluate("sessionStorage.removeItem('cheokcheok:qa-flow')")
            check("qa_state_lost", expect="rehearsal:wait")
            # 나가기 — 시트 → 홈. 표시가 다 꺼져야 한다
            page.goto(f"{args.base}/#/qa", wait_until="load")
            page.wait_for_timeout(2500)
            if page.query_selector("#bqStage [data-rh-exit]"):
                page.click("#bqStage [data-rh-exit]")
                page.wait_for_timeout(400)
                R["checks"]["exit_sheet"] = page.evaluate("[...document.querySelectorAll('#bqSheet button')].map(b => b.textContent.trim())")
                page.click("#bqSheet [data-sheet='leave']")
            else:
                page.evaluate("location.hash = '#/'")
            page.wait_for_timeout(1500)
            c = check("left_home", reload=False)
            c["ok"] = not any(c["flags"].values()) and not c["layer"]
            page.evaluate("location.hash = '#/qa'")
            c2 = check("qa_after_leave", reload=False)
            c2["ok"] = not c2["layer"] and not c2["flags"].get("rehearsal-flow")
            page.goto(f"{args.base}/vision", wait_until="load")
            page.wait_for_timeout(2500)
            c3 = check("vision_after_leave", reload=False)
            c3["ok"] = c3["flags"].get("rehearsal-flow") is None
            page.goto(f"{args.base}/booth/qa", wait_until="load")
            page.wait_for_selector("#bqStage #bqStart", timeout=20000)
            c4 = check("booth_after_leave", reload=False, expect="booth:attract")
        except Exception as e:  # noqa: BLE001
            R["error"] = f"{type(e).__name__}: {e}"[:500]
            print("  실패:", R["error"], flush=True)
            page.screenshot(path=str(out / "error.png"))
        finally:
            (out / "report.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
            b.close()
    bad = [k for k, c in R["checks"].items() if isinstance(c, dict) and not c.get("ok", True)]
    print(f"어긋난 단계 {len(bad)}개 {bad} · 오류 {len(R['console'])}건 → {out.relative_to(ROOT)}")
    return out


def summarize(out: Path) -> None:
    R = json.loads((out / "report.json").read_text())
    bad = []
    for tag, L in R.get("layout", {}).items():
        if not isinstance(L, dict):
            continue
        for k in ("overlaps", "cut_off"):
            if L.get(k):
                bad.append(f"{tag}: {k}={L[k]}")
        if L.get("hscroll"):
            bad.append(f"{tag}: 가로 넘침")
    errs = [c for c in R.get("console", []) if c.startswith(("error", "pageerror"))]
    if R.get("contrast"):
        allv = [(t, s, v) for t, d in R["contrast"].items() for s, v in d.items()]
        low = [x for x in allv if x[2] < 4.5]
        print(f"글자 대비(사진) {len(allv)}곳 · 최저 {min(v for *_, v in allv) if allv else '-'} · 4.5 아래 {len(low)}곳")
        for x in low[:12]:
            print("  ▽", x)
    print(f"배치 문제 {len(bad)}건 · 콘솔 오류 {len(errs)}건 · 판정 {R.get('judge', {}).get('judge_calls')}번 · 오류 {R.get('error', '-')}")
    for x in bad[:30]:
        print("  -", x)
    for x in errs[:10]:
        print("  !", x)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8805")
    ap.add_argument("--deck", default="배달앱별점인플레이션A")
    ap.add_argument("--rec-sec", type=int, default=45, help="발표(녹음) 길이 초")
    ap.add_argument("--slides", type=int, default=4, help="발표하며 넘길 장 수")
    ap.add_argument("--wait-timeout", type=int, default=600)
    ap.add_argument("--viewport", default="1512x860")
    ap.add_argument("--dpr", type=float, default=2)
    ap.add_argument("--sizes", default="1180x820", help="단계마다 더 찍을 크기 (아이패드 가로)")
    ap.add_argument("--cam", default="face", help="face · white · dark (white/dark 면 화상판 글자 대비를 잰다)")
    ap.add_argument("--answer", choices=["dictate", "type"], default="dictate")
    ap.add_argument("--no-move-slide", dest="move_slide", action="store_false", help="발표 중 자료 창을 옮기지 않는다 (화상판 기본 자리 확인)")
    ap.add_argument("--record", default="")
    ap.add_argument("--replay", default="")
    ap.add_argument("--fake-judge", action="store_true")
    ap.add_argument("--replay-delay", type=float, default=8, help="--replay: 질문 생성 응답을 이 초만큼 늦춘다 (기다림 화면 사진)")
    ap.add_argument("--until", choices=["pick", "rehearse", "wait", "qa", "report"], default="report")
    ap.add_argument("--occ", default="", help="발표 상황 (OCC_LABEL 의 값, 예: 업무 보고 (상사 대상)) — 비우면 추정을 그대로, 추정이 없으면 수업")
    ap.add_argument("--path", choices=["live", "rec", "rec-partial"], default="live",
                    help="live = 발표 마치고 질문 준비하기 · rec = 녹음 없이 「녹음본을 넣어서 발표 마치기」 · rec-partial = 몇 초 녹음하다가 녹음본으로")
    ap.add_argument("--reload", action="store_true")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    os.environ.setdefault("LD_LIBRARY_PATH", "/tmp/pwlibs/usr/lib/x86_64-linux-gnu")
    t = time.time()
    if args.reload:
        run_reload(args)
        return 0
    out = run(args)
    print(f"끝 {time.time() - t:.0f}s → {out.relative_to(ROOT)}")
    summarize(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
