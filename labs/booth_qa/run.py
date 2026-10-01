"""
부스 Q&A 무대 실험실 — 주소창 /booth/qa 로 들어가 시작 → 발표 고르기 → 훑어보기+질문 준비 → Q&A 무대 →
답 하나 → 판정 → 마무리 → 처음으로 를 **실 API 브리지**로 한 번 태우고 화면마다 사진을 남긴다.

가짜 카메라에는 **얼굴이 있는 영상**을 물린다 — 이 서버엔 웹캠이 없고, 부스 무대의 카메라 판단(OpenCV Haar)이
실제로 얼굴을 잡는지 봐야 해서다. 얼굴은 OpenCV 시험 자료의 모나리자(퍼블릭 도메인)를 방 사진에 붙여 쓴다.
영상은 빈 방 1.5초 → 가운데 얼굴 6초 → 왼쪽 가장자리 얼굴 2.5초 를 되풀이한다 (다가옴 인사 · 구도 안내 둘 다 보려고).

    .venv/bin/python labs/booth_qa/run.py --base http://127.0.0.1:8802
    .venv/bin/python labs/booth_qa/run.py --base http://127.0.0.1:8802 --deck 수면발표 --until prep
    .venv/bin/python labs/booth_qa/run.py --base http://127.0.0.1:8803 --route call --role 회사 상사   # 화상판 /booth/call

결과: labs/booth_qa/out/<stamp>/*.png + report.json (단계 시간 · 카메라 판단 표본 · 배치 검사 · 콘솔 오류)
실 LLM 과금이 난다 (개념·그래프·질문 3개 + 판정 1회). 브리지는 DEMO_DEV_ROUTES=1 이거나 /auth 쿠키가 있어야 목록이 열린다.
libasound 가 없는 서버면 LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu (labs/qa_call/README.md).
"""
from __future__ import annotations

import argparse
import io
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
FACE_URL = "https://raw.githubusercontent.com/opencv/opencv_extra/4.x/testdata/cv/cascadeandhog/images/mona-lisa.png"

UNTIL = ["attract", "pick", "prep", "qa", "finale"]
ANSWERS = {
    "수익률격차": "개인투자자는 잦은 매매와 추격 매수 같은 행동 때문에 시장보다 수익률이 낮아져요. 종목을 잘못 고른 것보다 거래 행동이 격차를 만든다는 게 결론이에요.",
    "수면발표": "잠은 깊은 수면과 REM 수면이 번갈아 오는 여러 단계라서, 단계마다 기억을 정리하는 역할이 달라요.",
    "focus_notification": "알림을 보는 몇 초보다 원래 작업으로 돌아오는 재집중 시간이 더 길어서 집중이 크게 끊겨요.",
}

# 배치 검사 — 층이 떠 있는지, 주인공 칸들이 화면 안에 있는지, 버튼이 실제로 눌리는지
LAYOUT_JS = """() => {
  const L = document.getElementById('bqStage');
  if (!L) return { layer: false };
  const r = (el) => { if (!el) return null; const b = el.getBoundingClientRect();
    return [Math.round(b.left), Math.round(b.top), Math.round(b.width), Math.round(b.height)]; };
  const hit = (sel) => { const b = document.querySelector(sel); if (!b || b.hidden || !b.offsetParent) return null;
    const q = b.getBoundingClientRect(); const h = document.elementFromPoint(q.left + q.width / 2, q.top + q.height / 2);
    return !!h && (h === b || b.contains(h)); };
  const inView = (sel) => { const el = document.querySelector(sel); if (!el) return null; const b = el.getBoundingClientRect();
    return b.top >= -1 && b.left >= -1 && b.bottom <= innerHeight + 1 && b.right <= innerWidth + 1; };
  const vids = [...document.querySelectorAll('#bqStage video[data-bq-cam]')];
  // 화상판(/booth/call) — 얼굴 가운데(가로 38~62% · 세로 18~62%)를 덮는 글라스가 있는지
  const cx0 = innerWidth * .38, cx1 = innerWidth * .62, cy0 = innerHeight * .18, cy1 = innerHeight * .62;
  const covers = (el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.right > cx0 && b.left < cx1 && b.bottom > cy0 && b.top < cy1; };
  const callParts = ['.bc-host', '.bc-dock', '.bc-side', '.bc-hint:not([hidden])', '.bc-prog', '#stream > *'];
  const center_cover = L.dataset.variant === 'call' && L.dataset.screen === 'qa'
    ? callParts.flatMap((sel) => [...L.querySelectorAll(sel)].filter(covers).map((el) => sel + (el.className ? '.' + String(el.className).split(' ')[0] : ''))) : null;
  return { layer: true, screen: L.dataset.screen, variant: L.dataset.variant, present: L.dataset.present, W: innerWidth, H: innerHeight,
    center_cover, host: r(L.querySelector('.bc-host')), talk: r(L.querySelector('.bc-talk')), dock: r(L.querySelector('.bc-dock')),
    now_q: r(L.querySelector('#stream .msg.is-now .msg-bubble')),
    glass: (() => { const g = L.querySelector('.bc-glass'); return g ? getComputedStyle(g).backdropFilter || getComputedStyle(g).webkitBackdropFilter : null; })(),
    // 넘침은 층 안의 스크롤 칸(.bq-body)에서 난다 — 층·문서만 보면 폰 폭 마무리 화면 넘침을 놓쳤다 (09-30)
    hscroll: document.documentElement.scrollWidth > innerWidth || L.scrollWidth > L.clientWidth
      || [...L.querySelectorAll('.bq-body')].some((b) => b.scrollWidth > b.clientWidth + 1),
    sidenav_hidden: getComputedStyle(document.querySelector('.sidenav')).visibility === 'hidden',
    video_live: vids.some((v) => v.srcObject && v.videoWidth > 0),
    spot: r(document.getElementById('bqSpot')), answer: r(document.querySelector('.bq-answer')),
    slide: r(document.getElementById('bqSlide')), self: r(document.querySelector('.bq-self')),
    face_box: (() => { const f = document.getElementById('bqFace'); return f && !f.hidden ? r(f) : null; })(),
    hint: (document.getElementById('bqHint') || {}).textContent || '',
    in_view: Object.fromEntries(['#bqStart', '#bqGo', '#liveSend', '#liveAnswer', '[data-bq-home]'].map((s) => [s, inView(s)])),
    clickable: Object.fromEntries(['#bqStart', '#bqGo', '#liveSend', '#liveMic', '#liveFinish', '#bqCamToggle', '[data-bq-home]']
      .map((s) => [s, hit(s)])) };
}"""


def face_cam(path: Path) -> Path:
    """얼굴이 있는 가짜 카메라 MJPEG. 모나리자 사진은 out/ 에 한 번만 받아 둔다(git 에 안 올린다)"""
    from PIL import Image, ImageDraw, ImageFilter

    face_png = OUT / "mona-lisa.png"
    if not face_png.exists():
        face_png.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(FACE_URL, face_png)
    portrait = Image.open(face_png).convert("RGB").crop((0, 0, 520, 440))
    portrait = portrait.resize((int(520 * 1.4), int(440 * 1.4)))

    def room() -> Image.Image:
        im = Image.new("RGB", (1280, 720))
        d = ImageDraw.Draw(im)
        for y in range(720):
            t = y / 720
            d.line([(0, y), (1280, y)], fill=(int(214 - 40 * t), int(196 - 50 * t), int(178 - 60 * t)))
        d.rectangle([60, 60, 260, 600], fill=(122, 96, 72))
        d.rectangle([980, 60, 1240, 380], fill=(225, 238, 250))
        return im

    frames = []
    plan = [("empty", 45), ("center", 180), ("edge", 75)]
    k = 0
    for kind, count in plan:
        for _ in range(count):
            im = room()
            dx = int(4 * ((k % 4) - 1.5))
            if kind == "center":
                im.paste(portrait, (276 + dx, 110))
            elif kind == "edge":
                im.paste(portrait, (-120 + dx, 110))
            im = im.filter(ImageFilter.GaussianBlur(0.6))
            b = io.BytesIO()
            im.save(b, "JPEG", quality=82)
            frames.append(b.getvalue())
            k += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(frames))
    return path


def run(args) -> Path:
    from playwright.sync_api import sync_playwright

    out = OUT / datetime.now().strftime("%Y%m%dT%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    want = UNTIL[: UNTIL.index(args.until) + 1]
    cam = face_cam(OUT / "facecam.mjpeg")
    report: dict = {"base": args.base, "deck": args.deck, "stages": {}, "layout": {}, "cv": [], "console": [], "requests": []}
    n = {"i": 0}

    def shot(name: str) -> None:
        n["i"] += 1
        page.screenshot(path=str(out / f"{n['i']:02d}_{name}.png"))

    def mark(name: str, t0: float, extra: dict | None = None) -> None:
        report["stages"][name] = {"sec": round(time.time() - t0, 1), **(extra or {})}
        print(f"  {name:10s} {report['stages'][name]['sec']:6.1f}s  {json.dumps(extra or {}, ensure_ascii=False)[:240]}")

    def layout(name: str) -> dict:
        lay = page.evaluate(LAYOUT_JS)
        report["layout"][name] = lay
        return lay

    def cv_sample(tag: str) -> dict:
        s = page.evaluate("window.BoothCV ? BoothCV.snapshot() : null")
        report["cv"].append({"tag": tag, "t": round(time.time(), 1), **(s or {})})
        return s or {}

    def at_sizes(tag: str, sizes=((1920, 1080), (1440, 900), (390, 844))) -> None:
        for vw, vh in sizes:
            page.set_viewport_size({"width": vw, "height": vh})
            page.wait_for_timeout(700)
            layout(f"{tag}_{vw}x{vh}")
            shot(f"{tag}_{vw}x{vh}")
        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_timeout(400)

    with sync_playwright() as p:
        flags = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                 f"--use-file-for-fake-video-capture={cam}", "--autoplay-policy=no-user-gesture-required"]
        b = p.chromium.launch(args=flags)
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, permissions=["camera", "microphone"])
        page = ctx.new_page()
        page.on("console", lambda m: report["console"].append(f"{m.type}: {m.text}"[:300])
                if m.type == "error" or (m.type == "warning" and "GL Driver" not in m.text) else None)
        page.on("pageerror", lambda e: report["console"].append(f"pageerror: {e}"[:300]))
        page.on("response", lambda r: report["requests"].append({"path": r.url.split(args.base)[-1][:90], "status": r.status})
                if "/api/" in r.url else None)
        try:
            # ── S0 시작 — 주소창 /booth/qa ─────────────────────────────
            t0 = time.time()
            page.goto(f"{args.base}/booth/{args.route}", wait_until="load")   # 카메라·판단 워커가 돌면 networkidle 이 안 온다
            entry_hash = page.evaluate("location.hash")
            page.wait_for_selector("#bqStage #bqStart", timeout=20000)
            page.wait_for_function("window.BoothCV && ['ready','failed'].includes(BoothCV.status())", timeout=90000)
            cv_status = page.evaluate("BoothCV.status()")
            cv_ms = round(time.time() - t0, 1)
            greeted = False
            deadline = time.time() + 20
            while time.time() < deadline:
                s = cv_sample("attract")
                if page.evaluate("(document.getElementById('bqGreet')||{}).dataset?.greeting === '1'"):
                    greeted = True
                    break
                page.wait_for_timeout(400)
            page.wait_for_timeout(600)
            shot("attract_greet")
            at_sizes("attract")
            mark("attract", t0, {"entry_hash": entry_hash, "flag": page.evaluate("boothQaOn()"), "cv": cv_status,
                                 "cv_ready_sec": cv_ms, "greeted": greeted, "present": s.get("present"),
                                 "greet_text": page.evaluate("(document.getElementById('bqGreetText')||{}).textContent")})
            if "pick" not in want:
                return out

            # ── S1 발표 고르기 ─────────────────────────────────────────
            t0 = time.time()
            page.click("#bqStart")
            page.wait_for_selector("#bqStage .bq-deck", timeout=30000)
            if args.route == "call":
                page.click(f'#bqStage .bq-role[data-role="{args.role}"]')
            page.wait_for_function("document.querySelectorAll('#bqStage .bq-cover.ready').length === document.querySelectorAll('#bqStage .bq-cover').length",
                                   timeout=60000)
            at_sizes("pick")
            decks = page.evaluate("[...document.querySelectorAll('#bqStage .bq-deck')].map(d => ({key: d.dataset.deck, kind: d.querySelector('.bq-deck-kind').textContent}))")
            mark("pick", t0, {"decks": decks, "foot": page.evaluate("(document.getElementById('bqDeckFoot')||{}).textContent"),
                              "roles": page.evaluate("[...document.querySelectorAll('#bqStage .bq-role')].map(b => b.dataset.role + (b.getAttribute('aria-checked') === 'true' ? '*' : ''))")})
            if "prep" not in want:
                return out

            # ── S2 훑어보기 + 질문 준비 ─────────────────────────────────
            t0 = time.time()
            page.click(f'#bqStage .bq-deck[data-deck="{args.deck}"]')
            page.wait_for_selector("#bqStage #bqSkimCanvas")
            page.wait_for_timeout(4000)
            shot("prep_skim")
            steps_seen = []
            deadline = time.time() + args.prep_timeout
            while time.time() < deadline:
                st = page.evaluate("Object.fromEntries([...document.querySelectorAll('#bqBuildSteps li')].map(l => [l.dataset.step, l.dataset.state]))")
                stamp = round(time.time() - t0, 1)
                if not steps_seen or steps_seen[-1][1] != st:
                    steps_seen.append((stamp, st))
                if page.evaluate("!document.getElementById('bqGo').disabled") or "fail" in st.values():
                    break
                page.wait_for_timeout(700)
            skim_no = page.evaluate("(document.getElementById('bqSkimNo')||{}).textContent")
            at_sizes("prep_ready")
            mark("prep", t0, {"steps": steps_seen, "skim_no": skim_no, "live": page.evaluate("qaLiveActive()"),
                              "n_questions": page.evaluate("qa.live ? qa.live.questions.length : 0"),
                              "fail": page.evaluate("(document.getElementById('bqPrepFail')||{}).textContent.trim()")})
            if "qa" not in want or not page.evaluate("qaLiveActive()"):
                return out

            # ── S3 Q&A 무대 ────────────────────────────────────────────
            t0 = time.time()
            page.click("#bqGo")
            call = args.route == "call"
            page.wait_for_selector("#bqStage[data-screen='qa'] " + ("#stream .msg.q" if call else "#bqSpot"), timeout=20000)
            page.wait_for_timeout(2500)
            cv_sample("qa_center")
            at_sizes("qa_ask")
            if call:
                mark("qa", t0, {"hash": page.evaluate("location.hash"), "variant": page.evaluate("boothQaVariant()"),
                                "host": page.inner_text("#bcHost")[:120], "aud": page.evaluate("qa.aud"),
                                "now_q": page.evaluate("(document.querySelector('#stream .msg.is-now .msg-q')||{}).textContent || ''")[:200]})
            else:
                mark("qa", t0, {"hash": page.evaluate("location.hash"), "spot": page.inner_text("#bqSpot")[:200],
                                "stream_q_hidden": page.evaluate("[...document.querySelectorAll('#stream .msg.q')].every(m => !m.offsetParent)")})
            # 구도 안내가 켜지는지 — 영상이 가장자리 얼굴로 넘어갈 때까지 기다린다
            hint_seen = ""
            deadline = time.time() + 14
            while time.time() < deadline:
                h = page.evaluate("(document.getElementById('bqHint')||{}).hidden === false ? document.getElementById('bqHint').textContent : ''")
                if h:
                    hint_seen = h
                    shot("qa_hint")
                    break
                page.wait_for_timeout(300)
            cv_sample("qa_edge")
            t0 = time.time()
            page.click("#liveAnswer")
            page.keyboard.type(ANSWERS.get(args.deck, ANSWERS["수익률격차"]), delay=3)
            page.click("#liveSend")
            page.wait_for_timeout(800)
            shot("qa_judging")
            page.wait_for_function("qa.live && !qa.live.busy", timeout=180000)
            page.wait_for_timeout(1800)
            at_sizes("qa_judged", sizes=((1920, 1080), (1440, 900), (390, 844)) if call else ((1920, 1080), (1440, 900)))
            mark("qa_answer", t0, {"hint_seen": hint_seen,
                                   "judgement": page.evaluate("qa.live.lastJudgement ? {verdict: qa.live.lastJudgement.verdict, score: qa.live.lastJudgement.score} : null"),
                                   "judge_mood": page.evaluate("(document.querySelector('#bqStage .bq-judge .bq-bird, #bcHost .bq-bird')||{}).dataset?.mood || ''"),
                                   "stream_kinds": page.evaluate("[...document.querySelectorAll('#stream > *')].map(e => e.className.split(' ').slice(0, 3).join('.'))"),
                                   "prog": page.inner_text("#bqProg"), "finish_label": page.evaluate("(document.getElementById('liveFinish')||{}).textContent"),
                                   "gaze": page.evaluate("BoothCV.readGaze()")})
            # ── 운영 장치 (10-01) — 처음으로 확인 시트 · 자리 비움 알림 ─────────────
            ops = {}
            page.click("#bqStage [data-bq-home]")
            page.wait_for_timeout(300)
            ops["sheet_open"] = page.evaluate("!!document.getElementById('bqSheet')")
            ops["sheet_buttons"] = page.evaluate("[...document.querySelectorAll('#bqSheet button')].map(b => b.textContent.trim())")
            shot("ops_sheet")
            page.click("#bqSheet [data-sheet='close']")
            page.wait_for_timeout(200)
            ops["sheet_closed_still_qa"] = page.evaluate("!document.getElementById('bqSheet') && bq.screen === 'qa'")
            page.evaluate("bqIdleWarn()")
            page.wait_for_timeout(1300)
            ops["idle_toast"] = page.evaluate("(document.getElementById('bqIdleText')||{}).textContent || ''")
            shot("ops_idle")
            page.click("#bqIdleStay")
            page.wait_for_timeout(200)
            ops["idle_cancelled"] = page.evaluate("!document.getElementById('bqIdleToast') && bq.screen === 'qa'")
            ops["live_region"] = page.evaluate("(document.getElementById('bcLive')||{}).textContent || ''")[:200]
            ops["answer_described"] = page.evaluate("(document.getElementById('liveAnswer')||{}).getAttribute?.('aria-describedby') || ''")
            ops["focus_slide"] = page.evaluate("(document.querySelector('#bqSlide figcaption')||{}).textContent || ''")
            ops["workers"] = len(page.workers)
            page.click("#bqCamToggle")                       # 카메라 끄기 — 화상판은 자료 창이 커진다
            page.wait_for_timeout(900)
            ops["cam_off"] = page.evaluate("(document.querySelector('[data-bq-cam-box]')||{}).dataset?.camera || ''")
            shot("ops_camoff")
            page.click("#bqCamToggle")
            page.wait_for_timeout(1200)
            ops["cam_back"] = page.evaluate("(document.querySelector('[data-bq-cam-box]')||{}).dataset?.camera || ''")
            report["ops"] = ops
            print("  ops       ", json.dumps(ops, ensure_ascii=False)[:400])
            if "finale" not in want:
                return out

            # ── S4 마무리 → 처음으로 ───────────────────────────────────
            t0 = time.time()
            page.click("#liveFinish")
            page.wait_for_selector("#bqStage[data-screen='finale']", timeout=20000)
            page.wait_for_timeout(1500)
            at_sizes("finale")
            ret1 = page.inner_text("#bqReturn")
            page.wait_for_timeout(2200)
            ret2 = page.inner_text("#bqReturn")
            fin = {"head": page.inner_text(".bq-fin-head"), "rows": page.inner_text(".bq-fin-list")[:300],
                   "gaze_card": page.evaluate("(document.querySelector('.bq-gaze b')||{}).textContent || null"),
                   "countdown": [ret1, ret2], "history_untouched": page.evaluate("(JSON.parse(localStorage.getItem('cheokcheok:qa-history')||'[]')).length")}
            page.click("#bqStage [data-bq-home]")
            page.wait_for_selector("#bqStage[data-screen='attract']", timeout=10000)
            page.wait_for_timeout(800)
            shot("home_again")
            mark("finale", t0, {**fin, "reset_live": page.evaluate("!qa.live"), "hash": page.evaluate("location.hash"),
                                "flag": page.evaluate("boothQaOn()")})
            # 부스 흐름을 벗어나면 플래그·카메라가 꺼지는지
            page.evaluate("location.hash = '#/'")
            page.wait_for_timeout(800)
            report["stages"]["leave"] = {"flag_off": not page.evaluate("boothQaOn()"),
                                         "layer_gone": page.evaluate("!document.getElementById('bqStage')"),
                                         "cam_off": page.evaluate("!bq.cam.stream")}
            print("  leave     ", report["stages"]["leave"])
            # Esc 두 번 — 발표 고르기에서 묻지 않고 처음으로 (스태프 키)
            page.goto(f"{args.base}/booth/{args.route}", wait_until="load")
            page.wait_for_selector("#bqStage #bqStart", timeout=20000)
            page.click("#bqStart")
            page.wait_for_selector("#bqStage[data-screen='pick']", timeout=10000)
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            page.keyboard.press("Escape")
            page.wait_for_timeout(600)
            report["stages"]["esc_reset"] = {"screen": page.evaluate("bq.screen"), "workers": len(page.workers)}
            print("  esc       ", report["stages"]["esc_reset"])
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
    ap.add_argument("--deck", default="수익률격차")
    ap.add_argument("--route", choices=["qa", "call"], default="qa", help="qa = /booth/qa 무대 · call = /booth/call 화상판")
    ap.add_argument("--role", default="교수님", help="call 일 때 발표 고르기에서 누를 역할 (BOOTH_ROLES 의 aud)")
    ap.add_argument("--until", choices=UNTIL, default="finale")
    ap.add_argument("--prep-timeout", type=int, default=240)
    args = ap.parse_args()
    os.environ.setdefault("LD_LIBRARY_PATH", "/tmp/pwlibs/usr/lib/x86_64-linux-gnu")
    t = time.time()
    out = run(args)
    print(f"끝 {time.time() - t:.0f}s → {out.relative_to(ROOT)}")
    print(f"콘솔 오류 {len([c for c in json.loads((out / 'report.json').read_text())['console'] if c.startswith(('error', 'pageerror'))])}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
