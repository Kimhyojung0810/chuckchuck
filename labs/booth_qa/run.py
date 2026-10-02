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

── 끝까지 모드 (--full, 2026-10-01 점검 P0 뒤) ──────────────────────────────────────────────
옛 실험실은 답 하나만 보내고 「남은 질문 건너뛰고 결과 보기」 로 나가서, 마지막 질문을 **닫는** 경로(끝 카드 · 12초 자동 결과)를
한 번도 못 밟았다 — 그 자리에서 탭이 멈추는 무한 고리(bqArmAutoEnd ↔ 답 칸 감시)를 놓친 까닭이다. --full 은
질문 3개를 끝까지 받고(질문마다 답 전략 --plan) → 끝 카드에서 고리 계측(bqArmAutoEnd · bcSync 호출 수, 멈춤 감지) →
12초 자동 결과 → (--wait-home) 40초 자동 처음으로 까지 간다. 폭마다(--sizes) 배치 검사·사진을 남긴다.

    # 실 API 한 번 — 개념·그래프·질문 응답을 --record 폴더에 남긴다
    .venv/bin/python labs/booth_qa/run.py --full --route call --base http://127.0.0.1:8803 --record labs/booth_qa/out/rec_income
    # 그 뒤로는 과금 없이 — 남긴 응답을 재생하고 판정은 가짜(--fake-judge)로, 화면만 본다
    .venv/bin/python labs/booth_qa/run.py --full --route call --base http://127.0.0.1:8803 \
        --replay labs/booth_qa/out/rec_income --fake-judge --viewport 1280x720 --plan good,stuck,partial --wait-home

  --plan     질문마다 답 전략 (쉼표): good(골자) · partial(관람객 답 → 되묻기 → 골자) · stuck(모르겠어요 → 답 보고 넘어가기)
             · trapyes(전제에 동의) · off(딴소리). 가짜 판정은 good → 바로 닫힘, partial → 한 번 되묻고 닫힘으로 답한다.
  --fail     judge503(첫 판정 503) · judgeabort · questions500 · camdeny(카메라 권한 없음)
  --fake-judge  /qa/judge 를 가짜 응답으로(과금 없음). 「모르겠어요」는 막힘 1·2·3단, reveal 은 가짜 골자.
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
  // 카메라가 꺼지면 자료 창이 화면 공유처럼 가운데를 쓴다(의도) — 그때는 재지 않는다. 폰(≤900)은 얼굴이 위쪽 띠에 있어 따로 잰다(phone_cover)
  const camOn = (L.querySelector('[data-bq-cam-box]') || {}).dataset?.camera === 'on';
  const isCallQa = L.dataset.variant === 'call' && L.dataset.screen === 'qa';
  const coverList = (fn) => callParts.flatMap((sel) => [...L.querySelectorAll(sel)].filter(fn).map((el) => sel + (el.className ? '.' + String(el.className).split(' ')[0] : '')));
  const center_cover = isCallQa && camOn && innerWidth > 900 ? coverList(covers) : null;
  const px0 = innerWidth * .34, px1 = innerWidth * .66, py0 = innerHeight * .08, py1 = innerHeight * .22;
  const phone_cover = isCallQa && camOn && innerWidth <= 900
    ? coverList((el) => { const b = el.getBoundingClientRect(); return b.width > 0 && b.right > px0 && b.left < px1 && b.bottom > py0 && b.top < py1; }) : null;
  // 겹침 — 진행 칩 · 사생활 알약 · 자료 창 · 답 칸이 서로 덮는지
  const box = (sel) => { const el = L.querySelector(sel); if (!el || !el.offsetParent) return null; const r = el.getBoundingClientRect();
    const st = el.closest('#stream'); if (!st) return r;   // 대화 칸 안의 말은 칸이 보여 주는 만큼만
    const c = st.getBoundingClientRect(); const top = Math.max(r.top, c.top), bottom = Math.min(r.bottom, c.bottom);
    return bottom <= top ? null : { left: r.left, right: r.right, top, bottom }; };
  const hit2 = (a, b) => !!a && !!b && a.right > b.left && a.left < b.right && a.bottom > b.top && a.top < b.bottom;
  const overlaps = isCallQa ? [['.bc-prog .bq-prog', '.bc-privacy'], ['.bc-prog .bq-prog', '#bqSlide'], ['.bc-dock', '#bqSlide'], ['.bc-dock', '.bc-privacy'],
    ['.bc-dock', '.bc-prog .bq-prog'], ['.bc-host', '.bc-dock'], ['.bc-talk', '.bc-dock'], ['.bc-hint:not([hidden])', '#bqSlide'],
    ['.bc-talk', '.bc-host'], ['#stream > .msg.is-now', '.bc-host']]
    .filter(([a, b]) => hit2(box(a), box(b))).map(([a, b]) => `${a} × ${b}`) : null;
  return { layer: true, screen: L.dataset.screen, variant: L.dataset.variant, present: L.dataset.present, W: innerWidth, H: innerHeight,
    center_cover, phone_cover, overlaps, cam_on: camOn,
    // 아래로 잘린 버튼 — 화면(층) 밖으로 나간 눌러야 할 것
    // 폰(≤900)은 화면이 스크롤로 이어져서 재지 않는다
    // 스크롤로 닿는 칸(.bq-body 가 스크롤된다) 안이면 잘린 게 아니다
    cut_off: innerWidth <= 900 ? [] : [...L.querySelectorAll('button, .bq-deck-go')].filter((b) => b.offsetParent).filter((b) => { const r = b.getBoundingClientRect();
      const sc = b.closest('.bq-body'); const scrolls = sc && /auto|scroll/.test(getComputedStyle(sc).overflowY) && sc.scrollHeight > sc.clientHeight + 1;
      return r.width > 0 && !scrolls && (r.bottom > innerHeight + 1 || r.right > innerWidth + 1); }).map((b) => (b.id || b.textContent.trim()).slice(0, 24)),
    host: r(L.querySelector('.bc-host')), talk: r(L.querySelector('.bc-talk')), dock: r(L.querySelector('.bc-dock')),
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
    // 방금 판정 말풍선이 대화 칸 안에 얼마나 보이나 (0~1) — 폰에서 되묻기에 밀려 위로 사라졌다 (10-01 점검)
    react_visible: (() => { const st = document.getElementById('stream'); const rs = st ? st.querySelectorAll(':scope > .msg.ai.react:not(.is-past)') : [];
      if (!rs.length) return null; const a = rs[rs.length - 1].getBoundingClientRect(); const c = st.getBoundingClientRect();
      const vis = Math.max(0, Math.min(a.bottom, c.bottom, innerHeight) - Math.max(a.top, c.top, 0)); return a.height ? Math.round(vis / a.height * 100) / 100 : null; })(),
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
            page.wait_for_timeout(450)   # 화면이 바뀐 뒤 0.38초는 마우스 클릭을 안 받는다 (P1-1)
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


# ── 끝까지 모드 (--full) ───────────────────────────────────────────────────────────────────────

VISITOR = {
    "수익률격차": "개인투자자는 정보가 부족하고 감정적으로 매매해서 그런 것 같아요.",
    "수면발표": "잠을 오래 자도 수면의 질이 낮으면 피곤한 거라고 생각해요.",
    "focus_notification": "알림 때문에 집중이 끊겨서 그런 것 같아요.",
}
OFF = "점심은 김치찌개가 맛있었어요. 오늘 날씨도 좋네요."
RECORD_PATHS = {"/api/v1/concepts": "concepts.json", "/api/v1/graph": "graph.json", "/api/v1/questions": "questions.json"}

# 고리 계측 — 원래 함수를 감싸 부른 수만 센다 (막지 않는다: 계측 없이도 멈추지 않아야 한다)
COUNT_JS = """() => {
  if (window.__bqCount) return;
  window.__bqCount = { arm: 0, sync: 0, relabel: 0 };
  const wrap = (name, key) => { const f = window[name]; if (typeof f !== 'function') return;
    window[name] = function () { window.__bqCount[key] += 1; return f.apply(this, arguments); }; };
  wrap('bqArmAutoEnd', 'arm'); wrap('bcSync', 'sync'); wrap('bqRelabelInput', 'relabel');
}"""

FONT_JS = """() => {
  const fs = (sel) => { const el = document.querySelector(sel); if (!el || !el.offsetParent) return null;
    const c = getComputedStyle(el); return { px: parseFloat(c.fontSize), text: (el.textContent || '').trim().slice(0, 40) }; };
  return { now_q: fs('#stream .msg.is-now .msg-q'), chip: fs('#stream > :not(.is-past) .react-head .chip'),
    react: fs('#stream > .msg.ai.react:not(.is-past) .msg-bubble > p'), ground_head: fs('#stream > :not(.is-past) .qa-ground > span'),
    say: fs('#bqJudgeSay'), role: fs('#bcHost .bc-host-text b'), count: fs('#bcCount'),
    past: fs('#stream > .is-past .msg-bubble'), past_q: fs('#stream > .is-past .msg-q') };
}"""


def _fake_judge_body(q: dict, kind: str, stage: str = "") -> dict:
    """가짜 판정 응답 — 실 응답(10-01 점검 기록)의 모양 그대로. 글은 실험실 표시를 단다"""
    slide = int((q.get("slide_nos") or [0])[0] or 0) or int(q.get("evidence_slide_no") or 0)
    base = {"question_id": q.get("id"), "node_id": q.get("node_id"), "verdict": "unknown", "score": 0, "react": "",
            "summary_sentence": f"{q.get('label', '')} — (실험실 가짜 판정) 정리 한 줄이에요.", "missing_points": [], "model": "fake",
            "followup": "", "hints": q.get("hints") or ["자료를 떠올려 보세요.", "그 장을 같이 볼게요", "빈칸을 채워 보세요: ___"],
            "coach_stage": "", "explanation": "", "round_no": 1, "probe_tier": "", "choices": [], "evidence_quote": "",
            "evidence_slide_no": 0, "guard_reason": "", "guard": "", "grounds": [], "passed": False, "mastered": False,
            "close_reason": "", "grounded_on_server": True, "grounded_on_deck": True, "degraded": [], "degraded_notes": []}
    quote = "자료의 한 줄이에요 (실험실)"
    if kind == "good":
        return {**base, "verdict": "good", "score": 84, "passed": True, "mastered": True, "close_reason": "good",
                "react": "핵심 근거를 자료 그대로 짚었어요. 숫자까지 정확해요. (실험실 가짜 판정)",
                "grounds": [{"slide_no": slide or 2, "quote": quote, "role": "covered", "note": "이 줄이 답이에요.", "ref": "S2-1"}]}
    if kind == "partial":
        return {**base, "verdict": "partial", "score": 55, "probe_tier": "probe",
                "react": "방향은 맞는데 자료가 든 근거가 아직 빠졌어요. 그 부분을 한 문장 더 말해 보세요. (실험실)",
                "missing_points": ["자료가 든 근거"], "followup": "자료가 든 근거는 무엇이었나요? (실험실 되묻기)",
                "grounds": [{"slide_no": slide or 2, "quote": quote, "role": "missing", "note": "아직 안 나온 것", "ref": "S2-1"}]}
    if kind == "wrong":
        return {**base, "verdict": "wrong", "score": 20, "probe_tier": "probe",
                "react": "질문의 전제부터 확인해 보세요 — 자료는 그렇게 말하지 않아요. (실험실)",
                "followup": "자료가 실제로 말한 것은 무엇인가요? (실험실 되묻기)"}
    # 막힘 사다리
    if stage == "explain":
        return {**base, "coach_stage": "explain", "react": "괜찮아요. 이번엔 답을 같이 볼게요.",
                "explanation": "자료는 이렇게 설명해요 — 실험실 가짜 해설 한 문장이에요.", "evidence_quote": quote, "evidence_slide_no": slide}
    if stage == "scaffold":
        return {**base, "coach_stage": "scaffold", "react": "괜찮아요. 한 칸만 채우면 돼요.",
                "followup": "빈칸을 채워 보세요: 자료는 ___ 라고 해요. — 'ㄱ' 인가요, 'ㄴ' 인가요?", "choices": ["ㄱ", "ㄴ"],
                "evidence_quote": quote, "evidence_slide_no": slide}
    return {**base, "coach_stage": "narrow", "react": f"괜찮아요. 여기서 같이 짚어 볼게요. 자료 {slide}장은 이렇게 말해요: «{quote}»",
            "followup": f"자료 {slide}장은 «{quote}» 라고 해요. 이 장이 말하는 건 'ㄱ' 쪽인가요, 'ㄴ' 쪽인가요?", "choices": ["ㄱ", "ㄴ"],
            "evidence_quote": quote, "evidence_slide_no": slide}


def _replayer(body: str):
    # 인자 하나짜리여야 한다 — playwright 는 인자가 둘인 처리기에 (route, request) 를 넘긴다
    def handle(route):
        route.fulfill(status=200, content_type="application/json", body=body)
    return handle


def plain_cam(path: Path, rgb: tuple[int, int, int]) -> Path:
    """흰 벽 · 어두운 방 — 글라스 대비를 가장 나쁜 배경에서 잰다 (10-02). 얼굴 영상 왼쪽 반에 판을 덮는 것과 같은 바탕"""
    from PIL import Image
    frames = []
    for k in range(30):
        im = Image.new("RGB", (1280, 720), rgb)
        b = io.BytesIO()
        im.save(b, "JPEG", quality=85)
        frames.append(b.getvalue())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(frames))
    return path


GLASS_TEXT = [".bc-draft p", ".bc-prog-topic", "#stream > .msg.ai.gist:not(.is-past) .msg-bubble > p", "#stream > .msg.ai.miss:not(.is-past) .msg-meta",
              "#stream > .msg.ai.hint:not(.is-past) .msg-bubble", "#stream > .msg.is-now .msg-q", "#stream > .msg.ai.react:not(.is-past) .msg-bubble > p", "#stream > .msg.me:not(.is-past) .msg-bubble",
              "#bqJudgeSay", "#bcHost .bc-host-text b", "#bqSlide figcaption", ".bc-dock .qa-input-label b", "#stream > .is-past .msg-bubble",
              "#stream > .qa-flag:not(.is-past)", ".bc-privacy", "#stream > .qa-finale:not(.is-past) b", "#stream > .qa-finale:not(.is-past) p"]


def glass_contrast(page, png: Path, sels: list[str] | None = None) -> dict:
    """사진에서 글자 대비를 잰다 — 글자 심(밝은 픽셀)과 그 바로 둘레(2~4px 띠, 심 제외)의 밝은 쪽 75% 값.
    판 · 흐림 · 글자 둘레 테를 다 거친 화면 그대로라, 「글자 쪽으로 읽힘을 지킨다」 가 실제로 4.5:1 을 넘는지 본다.
    sels 를 주면 그 글자들을 잰다 (기본은 화상판 GLASS_TEXT — 리허설 실험실이 비전 리허설 글자를 넘긴다)"""
    sels = list(sels or GLASS_TEXT)
    import numpy as np
    from PIL import Image
    dpr = page.evaluate("devicePixelRatio")
    boxes = page.evaluate("""(sels) => sels.map((s) => { const el = document.querySelector(s); if (!el || !el.offsetParent) return null;
      let r = el.getBoundingClientRect(); const st = el.closest('#stream');
      // 대화 칸 안의 말은 칸이 잘라 보이는 부분만 (위로 밀려 가려진 부분까지 재면 위 띠 · 영상이 섞인다)
      if (st) { const c = st.getBoundingClientRect(); const top = Math.max(r.top, c.top), bot = Math.min(r.bottom, c.bottom);
        if (bot - top < 16) return null; return [r.left, top, r.width, bot - top]; }
      return [r.left, r.top, r.width, r.height]; })""", sels)
    im = np.asarray(Image.open(png).convert("RGB")).astype(float) / 255
    lin = np.where(im <= 0.04045, im / 12.92, ((im + 0.055) / 1.055) ** 2.4)
    lum = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
    out = {}
    for sel, bx in zip(sels, boxes):
        if not bx or bx[2] < 4 or bx[3] < 4:
            continue
        x0, y0 = int(bx[0] * dpr), int(bx[1] * dpr)
        x1, y1 = int((bx[0] + bx[2]) * dpr), int((bx[1] + bx[3]) * dpr)
        crop = lum[max(0, y0):y1, max(0, x0):x1]
        if crop.size < 50:
            continue
        # 글자가 밝은지(어두운 판 · 흰 글자) 어두운지(연한 판 · 진한 글자) — 판 가운데 값으로 가른다
        dark_text = float(np.median(crop)) > 0.35
        core = crop <= min(0.08, np.percentile(crop, 3) * 1.5 + 0.01) if dark_text else crop >= max(0.6, np.percentile(crop, 97) * 0.92)
        if core.sum() < 10:
            continue

        def dil(m, r):
            o = m.copy()
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    o |= np.roll(np.roll(m, dy, 0), dx, 1)
            return o
        r1, r2 = max(1, round(2 * dpr)), max(2, round(4 * dpr))
        ring = dil(core, r2) & ~dil(core, r1 - 1 if r1 > 1 else 1)
        if ring.sum() < 10:
            continue
        lt = float(np.median(crop[core]))
        lb = float(np.percentile(crop[ring], 25 if dark_text else 75))   # 둘레의 글자 쪽에 가까운 값(보수적으로)
        out[sel] = round((max(lt, lb) + 0.05) / (min(lt, lb) + 0.05), 2)
    return out


def install_routes(page, args, state: dict) -> None:
    """실패 주입 · 기록 재생 · 가짜 판정. state 에 판정 호출 수와 받은 요청을 남긴다"""
    fails = set(filter(None, (args.fail or "").split(",")))
    rec = Path(args.replay) if args.replay else None
    if "questions500" in fails:
        page.route("**/api/v1/questions", lambda r: r.fulfill(status=500, content_type="application/json", body='{"error":"upstream timeout"}'))
    elif rec:
        for path, name in RECORD_PATHS.items():
            f = rec / name
            if f.exists():
                page.route(f"**{path}", _replayer(f.read_text()))
    if "decks500" in fails:
        page.route("**/api/v1/dev/decks", lambda r: r.fulfill(status=500, body="{}"))
    if not (args.fake_judge or "judge503" in fails or "judgeabort" in fails):
        return
    plan = (args.plan or "").split(",")

    def judge(route):
        state["judge_calls"] += 1
        n = state["judge_calls"]
        if "judge503" in fails and n == 1:
            return route.fulfill(status=503, content_type="application/json", body='{"error":"LLM upstream 503"}')
        if "judgeabort" in fails and n <= 2:
            return route.abort("internetdisconnected")
        if not args.fake_judge:
            return route.continue_()
        req = json.loads(route.request.post_data or "{}")
        q = req.get("question") or {}
        qid = req.get("question_id") or q.get("id") or "?"
        if req.get("reveal"):
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps({"answer_gist": "자료가 말한 바로잡힌 사실이에요 (실험실 가짜 골자)."}, ensure_ascii=False))
        order = state.setdefault("order", [])
        if qid not in order:
            order.append(qid)
        strat = plan[order.index(qid)] if order.index(qid) < len(plan) else "stuck"
        st = state.setdefault("per_q", {}).setdefault(qid, {"answers": 0, "give": 0})
        time.sleep(0.6)   # 판정 기다림 말풍선이 한 번은 보이게
        if req.get("give_up"):
            st["give"] += 1
            body = _fake_judge_body(q, "coach", ["narrow", "scaffold", "explain"][min(st["give"], 3) - 1])
        else:
            st["answers"] += 1
            kind = "good"
            if strat in ("partial", "trapyes", "off") and st["answers"] == 1:
                kind = "wrong" if strat in ("trapyes", "off") else "partial"
            body = _fake_judge_body(q, kind)
        state["judge_log"].append({"qid": qid, "give_up": bool(req.get("give_up")), "verdict": body["verdict"], "stage": body["coach_stage"]})
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))
    page.route("**/qa/judge", judge)


def _answer_for(strat: str, q: dict, deck: str) -> tuple[str, str]:
    """처음 답할 때 — (동작, 글)"""
    if strat == "good":
        if q.get("trap") or q.get("gist_withheld"):
            return "type", "질문에 깔린 전제가 자료와 달라요. 자료에서는 그 반대로 말하고 있어요."
        return "type", (q.get("answer_gist") or ANSWERS.get(deck, ANSWERS["수익률격차"]))
    if strat == "partial":
        return "type", VISITOR.get(deck, "자료의 핵심 때문인 것 같아요.")
    if strat == "trapyes":
        return "type", "네, 질문에서 말한 그대로예요. 그래서 그 결론이 나온 거예요."
    if strat == "off":
        return "type", OFF
    return "stuck", ""


def run_full(args) -> Path:
    from playwright.sync_api import sync_playwright

    out = OUT / (datetime.now().strftime("%Y%m%dT%H%M%S") + (f"_{args.tag}" if args.tag else ""))
    out.mkdir(parents=True, exist_ok=True)
    fails = set(filter(None, (args.fail or "").split(",")))
    plan = (args.plan or "good,stuck,partial").split(",")
    VW, VH = (int(x) for x in args.viewport.split("x"))
    sizes = [tuple(int(x) for x in s.split("x")) for s in (args.sizes or "").split(",") if s]
    cam = face_cam(OUT / "facecam.mjpeg")
    if args.cam == "white":
        cam = plain_cam(OUT / "whitecam.mjpeg", (246, 246, 242))
    elif args.cam == "dark":
        cam = plain_cam(OUT / "darkcam.mjpeg", (22, 24, 28))
    elif args.cam.endswith(".mjpeg"):
        cam = Path(args.cam)   # 다른 실험실이 만든 영상(역광 · 밝은 방 등)
    R: dict = {"args": vars(args), "stages": {}, "layout": {}, "fonts": {}, "turns": [], "console": [], "requests": [],
               "loop": {}, "texts": {}, "contrast": {}}
    state: dict = {"judge_calls": 0, "judge_log": []}
    n = {"i": 0}
    t_start = time.time()
    with sync_playwright() as p:
        flags = ["--use-fake-device-for-media-stream", f"--use-file-for-fake-video-capture={cam}", "--autoplay-policy=no-user-gesture-required"]
        if "camdeny" not in fails:
            flags.insert(0, "--use-fake-ui-for-media-stream")
        b = p.chromium.launch(args=flags)
        ctx = b.new_context(viewport={"width": VW, "height": VH}, permissions=[] if "camdeny" in fails else ["camera", "microphone"],
                            locale="ko-KR", is_mobile=VW < 600, has_touch=VW < 600, device_scale_factor=args.dpr)
        if args.css:
            # 글라스 값 실험 — 파일의 CSS 를 문서 끝에 얹는다 (원본 CSS 는 그대로)
            css = Path(args.css).read_text()
            ctx.add_init_script("document.addEventListener('DOMContentLoaded', () => { const s = document.createElement('style'); s.id = 'labCss'; s.textContent = %s; document.head.appendChild(s); });" % json.dumps(css))
        page = ctx.new_page()

        def shot(name: str) -> None:
            n["i"] += 1
            png = out / f"{n['i']:02d}_{name}.png"
            page.screenshot(path=str(png))
            if args.cam != "face" and page.evaluate("(document.getElementById('bqStage')||{dataset:{}}).dataset.screen === 'qa'"):
                R["contrast"][name] = glass_contrast(page, png)

        def lay(tag: str) -> dict:
            L = page.evaluate(LAYOUT_JS)
            R["layout"][tag] = L
            R["fonts"][tag] = page.evaluate(FONT_JS)
            return L

        def sweep(tag: str) -> None:
            lay(f"{tag}_{VW}x{VH}")
            shot(f"{tag}_{VW}x{VH}")
            for w, h in sizes:
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(700)
                lay(f"{tag}_{w}x{h}")
                shot(f"{tag}_{w}x{h}")
            if sizes:
                page.set_viewport_size({"width": VW, "height": VH})
                page.wait_for_timeout(500)

        def mark(name: str, t0: float, extra: dict | None = None) -> None:
            R["stages"][name] = {"sec": round(time.time() - t0, 1), **(extra or {})}
            print(f"  {name:12s} {R['stages'][name]['sec']:6.1f}s  {json.dumps(extra or {}, ensure_ascii=False)[:260]}", flush=True)

        def visible(sel: str) -> bool:
            return page.evaluate(f"(()=>{{const b=document.querySelector({json.dumps(sel)}); return !!b && !!b.offsetParent && !b.disabled}})()")

        page.on("console", lambda m: R["console"].append(f"{m.type}: {m.text}"[:300])
                if m.type == "error" or (m.type == "warning" and "GL Driver" not in m.text) else None)
        page.on("pageerror", lambda e: R["console"].append(f"pageerror: {e}"[:300]))
        rec_dir = Path(args.record) if args.record else None

        def on_resp(r):
            if "/api/" not in r.url:
                return
            R["requests"].append({"path": r.url.split(args.base)[-1][:90], "status": r.status, "t": round(time.time() - t_start, 1)})
            if rec_dir:
                for path, name in RECORD_PATHS.items():
                    if r.url.endswith(path) and r.status == 200:
                        try:
                            rec_dir.mkdir(parents=True, exist_ok=True)
                            (rec_dir / name).write_bytes(r.body())
                        except Exception as e:  # noqa: BLE001
                            print("  기록 실패", name, e)
        page.on("response", on_resp)
        install_routes(page, args, state)
        route = args.route
        try:
            t0 = time.time()
            page.goto(f"{args.base}/booth/{route}", wait_until="load")
            page.wait_for_selector("#bqStage #bqStart", timeout=20000)
            try:
                page.wait_for_function("window.BoothCV && ['ready','failed'].includes(BoothCV.status())", timeout=60000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(2500)
            sweep("attract")
            mark("attract", t0, {"cam_note": page.evaluate("(document.getElementById('bqCamNote')||{}).textContent||''"),
                                 "h1": page.evaluate("(document.querySelector('#bqStage h1')||{}).textContent||''")})
            t0 = time.time()
            page.click("#bqStart")
            page.wait_for_selector("#bqStage .bq-deck", timeout=30000)
            if route == "call":
                page.click(f'#bqStage .bq-role[data-role="{args.role}"]')
            try:
                page.wait_for_function("[...document.querySelectorAll('#bqStage .bq-cover')].every(c => c.classList.contains('ready'))", timeout=40000)
            except Exception:  # noqa: BLE001
                pass
            sweep("pick")
            mark("pick", t0)
            t0 = time.time()
            page.click(f'#bqStage .bq-deck[data-deck="{args.deck}"]')
            page.wait_for_selector("#bqStage #bqSkimCanvas")
            while time.time() - t0 < args.prep_timeout:
                if page.evaluate("!document.getElementById('bqGo').disabled") or page.evaluate("!!document.querySelector('#bqPrepFail .bq-fail')"):
                    break
                page.wait_for_timeout(500)
            sweep("prep")
            R["texts"]["prep"] = page.evaluate("(document.querySelector('.bq-build')||{}).innerText||''")
            mark("prep", t0, {"live": page.evaluate("qaLiveActive()"), "go": page.evaluate("(document.getElementById('bqGo')||{}).textContent||''"),
                              "fail": page.evaluate("(document.getElementById('bqPrepFail')||{}).innerText||''")})
            if not page.evaluate("qaLiveActive()"):
                return out
            questions = page.evaluate("qa.live.questions.map(q => ({id: q.id, label: q.label, trap: !!q.trap, answer_gist: q.answer_gist || '', gist_withheld: !!q.gist_withheld, slide_nos: q.slide_nos || [], evidence_slide_no: q.evidence_slide_no || 0}))")
            R["questions"] = questions
            t0 = time.time()
            page.click("#bqGo")
            page.wait_for_selector("#bqStage[data-screen='qa'] #stream .msg.q", timeout=20000, state="attached")   # 무대판은 질문 줄을 숨긴다
            page.evaluate(COUNT_JS)
            page.wait_for_timeout(2500)
            sweep("qa_ask1")
            mark("qa_enter", t0, {"say": page.evaluate("(document.getElementById('bqJudgeSay')||{}).textContent||''"),
                                  "slide": page.evaluate("(document.querySelector('#bqSlide figcaption')||{}).textContent||''")})
            if args.until == "qa":   # --full --until qa — 첫 질문 화면까지만 (글라스 값 실험)
                return out
            qi_prev, guard = -1, 0
            clicks: dict[int, int] = {}
            while guard < 16:
                guard += 1
                st = page.evaluate("({qi: qa.live.qi, n: qa.live.questions.length, end: !!qa.live.awaitEnd, retell: !!qa.live.retell, turn: qa.live.turn || 0, gave: (qa.live.turns||[]).filter(t => t.gaveUp).length})")
                if st["end"] or st["qi"] >= st["n"]:
                    break
                qi = st["qi"]
                q = questions[qi] if qi < len(questions) else {}
                strat = plan[qi] if qi < len(plan) else "stuck"
                if qi != qi_prev and qi > 0:
                    page.wait_for_timeout(1200)
                    sweep(f"qa_ask{qi + 1}")
                    R["texts"][f"say_q{qi + 1}"] = page.evaluate("(document.getElementById('bqJudgeSay')||{}).textContent||''")
                first = qi != qi_prev
                qi_prev = qi
                typed = sum(1 for t in R["turns"] if t["qi"] == qi + 1 and t["action"] == "type")
                if st["retell"]:
                    action, text = ("skipretell", "") if visible("#liveSkipRetell") else ("retell", "핵심은 자료에 나온 대로예요.")
                elif first:
                    action, text = _answer_for(strat, q, args.deck)
                elif visible("#liveReveal") and (strat == "stuck" or typed >= 2):
                    action, text = "reveal", ""
                elif strat == "stuck" or typed >= 2 or not visible("#liveSend"):
                    action, text = "stuck", ""   # 두 번 답해도 안 닫히면 막힘 사다리로 빠져나간다 (실 판정 과금을 묶어 둔다)
                else:
                    action, text = _answer_for("good", q, args.deck)
                clicks[qi] = clicks.get(qi, 0) + 1
                tj = time.time()
                if action == "type" or action == "retell":
                    page.fill("#liveAnswer", text)
                    page.click("#liveSend")
                elif action == "stuck":
                    page.click("#liveStuck")
                elif action == "reveal":
                    page.click("#liveReveal")
                elif action == "skipretell":
                    page.click("#liveSkipRetell")
                page.wait_for_timeout(500)
                page.wait_for_function("qa.live && !qa.live.busy", timeout=150000)
                page.wait_for_timeout(1200)
                turn = {"qi": qi + 1, "strategy": strat, "action": action, "sec": round(time.time() - tj, 1),
                        "say": page.evaluate("(document.getElementById('bqJudgeSay')||{}).textContent||''"),
                        "alert": page.evaluate("(document.getElementById('bcAlert')||{}).textContent||''"),
                        "buttons": page.evaluate("[...document.querySelectorAll('#bqStage .qa-live-input button')].filter(b=>b.offsetParent).map(b=>b.textContent.trim())"),
                        "slide": page.evaluate("(document.querySelector('#bqSlide figcaption')||{}).textContent||''")}
                R["turns"].append(turn)
                print(f"  Q{qi + 1} {strat}/{action} {turn['sec']}s → {turn['buttons']}", flush=True)
                if action in ("type", "stuck", "reveal"):
                    tag = f"q{qi + 1}_{action}{clicks[qi]}"
                    if args.sweep_each:
                        sweep(tag)
                    else:
                        lay(tag)
                        shot(tag)
            R["clicks_per_question"] = {str(k + 1): v for k, v in clicks.items()}
            # ── 끝 카드: 고리 계측 · 멈춤 감지 ──
            c0 = page.evaluate("JSON.parse(JSON.stringify(window.__bqCount||{}))")
            frozen = False
            try:
                page.wait_for_function("new Promise(r => requestAnimationFrame(() => r(true)))", timeout=5000)
            except Exception:  # noqa: BLE001
                frozen = True
            page.wait_for_timeout(3000)
            c1 = page.evaluate("JSON.parse(JSON.stringify(window.__bqCount||{}))") if not frozen else {}
            R["loop"] = {"frozen": frozen, "before": c0, "after_3s": c1,
                         "arm_per_3s": (c1.get("arm", 0) - c0.get("arm", 0)) if c1 else None,
                         "sync_per_3s": (c1.get("sync", 0) - c0.get("sync", 0)) if c1 else None,
                         "end_note": page.evaluate("(document.querySelector('#bqStage .qa-end-note')||{}).textContent||''") if not frozen else ''}
            print("  loop", R["loop"], flush=True)
            sweep("qa_end")
            t0 = time.time()
            page.wait_for_selector("#bqStage[data-screen='finale']", timeout=30000)
            mark("auto_finale", t0, {"after_sec": round(time.time() - t0, 1)})
            page.wait_for_timeout(1200)
            sweep("finale")
            R["texts"]["finale"] = page.evaluate("document.getElementById('bqStage').innerText")
            if args.wait_home:
                t0 = time.time()
                page.wait_for_selector("#bqStage[data-screen='attract']", timeout=70000)
                mark("auto_home", t0, {"after_sec": round(time.time() - t0, 1)})
                shot("home_auto")
        except Exception as e:  # noqa: BLE001
            R["error"] = f"{type(e).__name__}: {e}"[:600]
            print("  실패:", R["error"])
            try:
                shot("error")
                R["error_text"] = page.evaluate("document.getElementById('bqStage') ? document.getElementById('bqStage').innerText.slice(0, 800) : ''")
            except Exception:  # noqa: BLE001
                pass
        finally:
            R["judge"] = state
            R["total_sec"] = round(time.time() - t_start, 1)
            R["llm_calls"] = sum(1 for x in R["requests"] if x["status"] == 200 and (x["path"].endswith(("/concepts", "/graph", "/questions")) or "/qa/judge" in x["path"])) - (state.get("judge_calls", 0) if args.fake_judge else 0)
            (out / "report.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
            b.close()
    return out


RELOAD_CHECK_JS = """() => {
  const L = document.getElementById('bqStage');
  const appVisible = (sel) => { const el = document.querySelector('#app ' + sel); return !!el && !!el.offsetParent; };
  return { hash: location.hash, layer: !!L, screen: L ? L.dataset.screen : null, variant: L ? L.dataset.variant : null,
    // 일반 앱 화면이 보이면 안 된다 — 질문 코칭(트랙 고르기·대화) · 홈
    general_qa: appVisible('.qa-shell') || appVisible('.coach-nav') || appVisible('.qa-mode-gate') || appVisible('.mode-gate'),
    app_text: (document.getElementById('app') || {}).innerText ? document.getElementById('app').innerText.slice(0, 80) : '',
    flag: sessionStorage.getItem('cheokcheok:booth-qa'), live: typeof qaLiveActive === 'function' ? qaLiveActive() : null,
    qi: (window.qa && qa.live) ? qa.live.qi : null };
}"""


def run_reload(args) -> Path:
    """부스 탭 새로고침 · 뒤로 가기 — 어느 단계에서도 일반 앱 화면이 안 보이는지 (10-02 사용자 버그)"""
    from playwright.sync_api import sync_playwright
    import subprocess

    out = OUT / (datetime.now().strftime("%Y%m%dT%H%M%S") + f"_reload_{args.route}" + (f"_{args.tag}" if args.tag else ""))
    out.mkdir(parents=True, exist_ok=True)
    VW, VH = (int(x) for x in args.viewport.split("x"))
    cam = face_cam(OUT / "facecam.mjpeg")
    R: dict = {"args": vars(args), "checks": {}, "console": []}
    state: dict = {"judge_calls": 0, "judge_log": []}
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                    f"--use-file-for-fake-video-capture={cam}", "--autoplay-policy=no-user-gesture-required"])
        ctx = b.new_context(viewport={"width": VW, "height": VH}, permissions=["camera", "microphone"], locale="ko-KR", device_scale_factor=args.dpr)
        page = ctx.new_page()
        page.on("pageerror", lambda e: R["console"].append(f"pageerror: {e}"[:300]))
        page.on("console", lambda m: R["console"].append(f"{m.type}: {m.text}"[:300]) if m.type == "error" else None)
        for rel in filter(None, (args.old_js or "").split(",")):
            # 옛 코드로 재현 — 지정한 파일을 HEAD~ 판으로 바꿔 낸다 (예: --old-js js/booth_qa.js,js/app.js --old-rev HEAD)
            body = subprocess.run(["git", "show", f"{args.old_rev}:demo/YEHS_demo/{rel}"], cwd=ROOT, capture_output=True, text=True).stdout
            page.route(f"**/{rel}*", _js_server(body))
        install_routes(page, args, state)

        def check(tag: str, *, reload: bool = True) -> dict:
            if reload:
                page.reload(wait_until="load")
            page.wait_for_timeout(3500)
            c = page.evaluate(RELOAD_CHECK_JS)
            R["checks"][tag] = c
            page.screenshot(path=str(out / f"{len(R['checks']):02d}_{tag}.png"))
            bad = c["general_qa"] or not c["layer"]
            print(f"  {tag:22s} {'✗ 일반 화면' if bad else '✓ 부스'}  {json.dumps(c, ensure_ascii=False)[:220]}", flush=True)
            return c

        try:
            page.goto(f"{args.base}/booth/{args.route}", wait_until="load")
            page.wait_for_selector("#bqStage #bqStart", timeout=20000)
            check("attract")
            page.click("#bqStart")
            page.wait_for_selector("#bqStage .bq-deck", timeout=30000)
            check("pick")
            page.wait_for_selector("#bqStage #bqStart", timeout=20000)
            page.wait_for_timeout(450)   # 화면이 바뀐 뒤 0.38초는 마우스 클릭을 안 받는다 (P1-1)
            page.click("#bqStart")
            page.wait_for_selector("#bqStage .bq-deck", timeout=30000)
            page.click(f'#bqStage .bq-deck[data-deck="{args.deck}"]')
            page.wait_for_selector("#bqStage #bqSkimCanvas")
            page.wait_for_function("!document.getElementById('bqGo').disabled", timeout=args.prep_timeout * 1000)
            check("prep_ready")
            # 다시 준비해서 질문 화면으로
            page.wait_for_selector("#bqStage #bqStart", timeout=20000)
            page.wait_for_timeout(450)   # 화면이 바뀐 뒤 0.38초는 마우스 클릭을 안 받는다 (P1-1)
            page.click("#bqStart")
            page.wait_for_selector("#bqStage .bq-deck", timeout=30000)
            page.click(f'#bqStage .bq-deck[data-deck="{args.deck}"]')
            page.wait_for_function("!document.getElementById('bqGo') || !document.getElementById('bqGo').disabled", timeout=args.prep_timeout * 1000)
            page.click("#bqGo")
            page.wait_for_selector("#bqStage[data-screen='qa']", timeout=20000)
            check("qa_ask1")
            page.fill("#liveAnswer", ANSWERS.get(args.deck, ANSWERS["수익률격차"]))
            page.click("#liveSend")
            page.wait_for_function("qa.live && !qa.live.busy", timeout=60000)
            check("qa_after_answer")
            # 질문 상태를 비운 채 새로고침 — 되살릴 수 없으면 부스 처음 화면이어야 한다
            page.evaluate("sessionStorage.removeItem('cheokcheok:qa-flow')")
            check("qa_state_lost")
            # 뒤로 가기 — 부스 처음 화면에서 뒤로 가도 부스 안
            page.goto(f"{args.base}/#/about", wait_until="load")
            page.goto(f"{args.base}/booth/{args.route}", wait_until="load")
            page.wait_for_selector("#bqStage #bqStart", timeout=20000)
            page.go_back()
            check("back_from_attract", reload=False)
            page.go_back()
            check("back_twice", reload=False)
        except Exception as e:  # noqa: BLE001
            R["error"] = f"{type(e).__name__}: {e}"[:500]
            print("  실패:", R["error"])
            page.screenshot(path=str(out / "error.png"))
        finally:
            (out / "report.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
            b.close()
    leaks = [k for k, c in R["checks"].items() if c.get("general_qa") or not c.get("layer")]
    print(f"일반 화면으로 샌 단계 {len(leaks)}개 {leaks} · 오류 {len(R['console'])}건 → {out.relative_to(ROOT)}")
    return out


def _js_server(body: str):
    def handle(route):
        route.fulfill(status=200, content_type="application/javascript", body=body)
    return handle


def summarize(out: Path) -> None:
    R = json.loads((out / "report.json").read_text())
    bad = []
    for tag, L in R.get("layout", {}).items():
        if not isinstance(L, dict) or not L.get("layer"):
            continue
        for k in ("center_cover", "overlaps", "cut_off"):
            if L.get(k):
                bad.append(f"{tag}: {k}={L[k]}")
        if L.get("hscroll"):
            bad.append(f"{tag}: 가로 넘침")
    errs = [c for c in R.get("console", []) if c.startswith(("error", "pageerror"))]
    if R.get("contrast"):
        allv = [(tag, sel, v) for tag, d in R["contrast"].items() for sel, v in d.items()]
        low = [x for x in allv if x[2] < 4.5]
        print(f"글자 대비(사진) {len(allv)}곳 · 최저 {min(v for *_, v in allv) if allv else '-'} · 4.5 아래 {len(low)}곳")
        for x in low[:12]:
            print("  ▽", x)
    print(f"배치 문제 {len(bad)}건 · 콘솔 오류 {len(errs)}건 · 고리 {R.get('loop')} · 질문별 누름 {R.get('clicks_per_question')}")
    for x in bad[:40]:
        print("  -", x)
    for x in errs[:10]:
        print("  !", x)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8799")
    ap.add_argument("--deck", default="수익률격차")
    ap.add_argument("--route", choices=["qa", "call"], default="qa", help="qa = /booth/qa 무대 · call = /booth/call 화상판")
    ap.add_argument("--role", default="교수님", help="call 일 때 발표 고르기에서 누를 역할 (BOOTH_ROLES 의 aud)")
    ap.add_argument("--until", choices=UNTIL, default="finale")
    ap.add_argument("--prep-timeout", type=int, default=240)
    ap.add_argument("--full", action="store_true", help="질문 3개 끝까지 → 끝 카드 고리 계측 → 12초 자동 결과 (위 설명)")
    ap.add_argument("--plan", default="good,stuck,partial", help="--full: 질문마다 답 전략")
    ap.add_argument("--viewport", default="1440x900", help="--full: 처음부터 이 크기로 돈다")
    ap.add_argument("--sizes", default="", help="--full: 화면마다 더 찍을 크기 (예: 1920x1080,1366x768,390x844)")
    ap.add_argument("--sweep-each", action="store_true", help="--full: 판정마다도 --sizes 로 찍는다")
    ap.add_argument("--fail", default="", help="--full: judge503,judgeabort,questions500,decks500,camdeny")
    ap.add_argument("--fake-judge", action="store_true", help="--full: /qa/judge 를 가짜 응답으로 (과금 없음)")
    ap.add_argument("--record", default="", help="--full: 개념·그래프·질문 응답을 이 폴더에 남긴다")
    ap.add_argument("--replay", default="", help="--full: --record 로 남긴 응답을 재생한다 (과금 없음)")
    ap.add_argument("--wait-home", action="store_true", help="--full: 결과 화면에서 40초 자동 처음으로까지 기다린다")
    ap.add_argument("--dpr", type=float, default=1, help="--full: devicePixelRatio (맥북 레티나는 2)")
    ap.add_argument("--cam", default="face", help="--full: 가짜 카메라 — 얼굴 · 흰 벽 · 어두운 방 (white/dark 면 글자 대비를 사진에서 잰다)")
    ap.add_argument("--reload", action="store_true", help="단계마다 새로고침·뒤로 가기 — 일반 앱 화면으로 새는지 (10-02)")
    ap.add_argument("--old-js", default="", help="--reload: 이 파일들을 --old-rev 판으로 내 옛 코드를 재현 (예: js/booth_qa.js,js/app.js)")
    ap.add_argument("--old-rev", default="HEAD")
    ap.add_argument("--css", default="", help="--full: 이 CSS 파일을 문서 끝에 얹어 찍는다 (글라스 값 실험 — 원본은 그대로)")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    os.environ.setdefault("LD_LIBRARY_PATH", "/tmp/pwlibs/usr/lib/x86_64-linux-gnu")
    t = time.time()
    if args.reload:
        run_reload(args)
        return 0
    if args.full:
        out = run_full(args)
        print(f"끝 {time.time() - t:.0f}s → {out.relative_to(ROOT)}")
        summarize(out)
        return 0
    out = run(args)
    print(f"끝 {time.time() - t:.0f}s → {out.relative_to(ROOT)}")
    print(f"콘솔 오류 {len([c for c in json.loads((out / 'report.json').read_text())['console'] if c.startswith(('error', 'pageerror'))])}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
