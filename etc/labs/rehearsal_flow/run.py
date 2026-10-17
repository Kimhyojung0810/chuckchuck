"""
리허설 한 줄 흐름 실험실 — 주소창 /rehearsal 로 들어가 발표 고르기 → 비전 리허설(가짜 카메라 · 가짜 마이크로 몇 장 발표) →
분석 기다림(부스 「질문 준비」 모양) → 글라스 화상판(자동 받아쓰기로 답) → 상세 리포트(#/rehearsal/report) 까지 헤드리스 크롬으로 한 번 태운다.

이 서버엔 웹캠 · 마이크가 없다. 카메라는 부스 실험실의 얼굴 영상(etc/labs/booth_qa face_cam), 마이크는 고른 덱의 실제 발표 녹음을
앞에서 잘라 쓴다(ffmpeg). 실시간 받아쓰기(브리지 /api/v1/stt/live → A.X, 10-15)는 기본은 흉내 낸다 — 그 WebSocket 만 가짜로 바꿔
window.__fakeSay("말") 을 부르면 말소리 시작 → 문장 확정으로 흘러 들어온다(비전 리허설의 삐약이 반응 · 화상판 자동 받아쓰기 둘 다).
--real-stt 면 흉내 없이 가짜 마이크 소리(덱 녹음 앞 --say-sec 초 + 조용함)를 진짜 A.X 가 받아쓴다(과금):

    LD_LIBRARY_PATH=~/.local/lib/pwlibs .venv/bin/python etc/labs/rehearsal_flow/run.py --base http://127.0.0.1:8812 --real-stt --no-chatter

    # 실 API 한 번 — 받아쓰기 · 개념 · 그래프 · 정합 · 흐름 · 질문 · 판정 응답을 --record 폴더에 남긴다 (과금)
    LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu .venv/bin/python etc/labs/rehearsal_flow/run.py \
        --base http://127.0.0.1:8805 --record etc/labs/rehearsal_flow/out/rec_income
    # 그 뒤로는 과금 없이 — 남긴 응답을 재생하고 판정은 가짜(--fake-judge)
    .venv/bin/python etc/labs/rehearsal_flow/run.py --base http://127.0.0.1:8805 --replay etc/labs/rehearsal_flow/out/rec_income --fake-judge
    # 새로고침 · 뒤로 가기 · 나간 뒤 표시가 남는지 (재생 + 가짜 판정)
    .venv/bin/python etc/labs/rehearsal_flow/run.py --base http://127.0.0.1:8805 --replay etc/labs/rehearsal_flow/out/rec_income --fake-judge --reload

결과: etc/labs/rehearsal_flow/out/<stamp>/*.png + report.json (단계 시간 · 배치 · 자료 창 상자 · 표시 · 콘솔 오류 · 글자 대비)
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
ROOT = HERE.parents[2]
OUT = HERE / "out"


def _booth():
    spec = importlib.util.spec_from_file_location("booth_qa_run", ROOT / "etc/labs/booth_qa/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _booth()

DECK_AUDIO = {   # 덱의 실제 발표 녹음 (main/decks/<덱>/ — git 에 안 올린다)
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
# 비전 리허설에서 잴 글자 — 카메라 위 이름표 · 위 알약 · 조작줄 · 자료 창 자막 (--cam white|dark)
VISION_TEXT = ["#vrCall .vr-name", "#vrCall .vr-status", "#vrCall .vr-pill:not(.rh-brand)", "#vrCall .rh-brand > span", "#vrCall .rh-brand small", "#vrCall .vr-rec .rec-copy > span", "#vrCall .vr-rec .rec-live",
               "#vrCall .vr-rec .rec-clock", "#vrCall .vr-nav[data-slide-nav='1']", "#vrCall .vr-caption", "#vrCall .vr-hear"]
RECORD_PATHS = {
    "/api/v1/transcribe": "transcribe.json", "/api/v1/concepts": "concepts.json", "/api/v1/graph": "graph.json",
    "/api/v1/alignment": "alignment.json", "/api/v1/flow": "flow.json", "/api/v1/pace": "pace.json",
    "/api/v1/habits": "habits.json", "/api/v1/rubric": "rubric.json", "/api/v1/report": "voice_report.json",
    "/api/v1/questions": "questions.json", "/api/v1/chatter": "chatter.json",
}

# Report 2.0 재료 — 리포트가 읽는 브라우저 상태 그대로(nf · qa · 마지막 리포트 · Q&A 기록). docs/report-v2/DATA_MAPPING.md
STATE_JS = """() => {
  const j = (s, k) => { try { return JSON.parse(s.getItem(k) || 'null'); } catch (_) { return null; } };
  return { newFlow: j(sessionStorage, 'cheokcheok:new-flow'), qaFlow: j(sessionStorage, 'cheokcheok:qa-flow'),
           lastReport: j(localStorage, 'cheokcheok:last-report'), qaHistory: j(localStorage, 'cheokcheok:qa-history'),
           liveQa: (typeof qa !== 'undefined' && qa.live) ? qa.live : null };
}"""

# 실시간 받아쓰기 흉내 (2026-10-15 부터 받아쓰기는 브리지 /api/v1/stt/live → A.X 실시간 STT 다 — 예전 Web Speech 흉내를 바꿨다).
# 그 주소로 여는 WebSocket 만 가짜로 바꾼다: 열리면 ready, window.__fakeSay("말") 이면 말소리 시작(speech on) → 문장(text) → 끝(speech off).
# 과금 없이 화면 흐름만 본다. 진짜 A.X 로 보려면 --real-stt (가짜 마이크 소리를 실제로 받아쓴다 — 과금).
FAKE_SPEECH_JS = """
(() => {
  const Real = window.WebSocket;
  const live = new Set();
  window.__fakeRecCount = 0;
  class FakeLive {
    constructor(url) {
      this.url = url; this.readyState = 0; this.binaryType = 'blob'; this.frames = 0;
      live.add(this); window.__fakeRecCount += 1;
      setTimeout(() => { if (this.readyState) return; this.readyState = 1; if (this.onopen) this.onopen({}); this._emit({ type: 'ready' }); }, 30);
    }
    send(data) {
      if (typeof data !== 'string') { this.frames += 1; return; }
      let m = {}; try { m = JSON.parse(data); } catch (_) { return; }
      if (m.type === 'stop') setTimeout(() => { this._emit({ type: 'done', reason: 'stop' }); this.close(); }, 60);
      else if (m.type === 'cancel') this.close();
    }
    close() {
      if (this.readyState === 3) return;
      this.readyState = 3; live.delete(this);
      setTimeout(() => { if (this.onclose) this.onclose({ code: 1000 }); }, 10);
    }
    _emit(m) { if (this.readyState === 1 && this.onmessage) this.onmessage({ data: JSON.stringify(m) }); }
    __say(text) {
      this._emit({ type: 'speech', on: true });
      setTimeout(() => { this._emit({ type: 'speech', on: false }); this._emit({ type: 'text', text }); }, 150 + text.length * 8);
    }
  }
  const Wrapped = function (url, protocols) { return String(url).includes('/api/v1/stt/live') ? new FakeLive(url) : new Real(url, protocols); };
  Object.assign(Wrapped, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3, prototype: Real.prototype });
  window.WebSocket = Wrapped;
  window.__fakeSay = (text) => { live.forEach((s) => s.__say(String(text))); return live.size; };
  window.__fakeListening = () => live.size;
})();
"""
# --real-stt: 진짜 받아쓰기 — 흉내 대신 「지금 받아쓰기가 열려 있나」 만 같은 이름으로 둔다 (qa_live.js liveMic)
REAL_STT_JS = """
window.__fakeSay = () => 0;
window.__fakeListening = () => (typeof liveMic !== 'undefined' && liveMic && liveMic.dictation) ? 1 : 0;
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
    hscroll: document.documentElement.scrollWidth > innerWidth || (!!L && L.scrollWidth > L.clientWidth),
    wide: [...document.querySelectorAll('#bqStage *, #vrCall *')].filter((e) => { const b = e.getBoundingClientRect(); return b.width && b.right > innerWidth + 1 && getComputedStyle(e).position !== 'fixed'; })
      .slice(0, 8).map((e) => (e.id ? '#' + e.id : e.tagName.toLowerCase() + '.' + String(e.className || '').split(' ')[0]) + '@' + Math.round(e.getBoundingClientRect().right))
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


def deck_audio(deck: str, sec: int, src: Path | None = None) -> Path | None:
    name = DECK_AUDIO.get(deck)
    if src is None:
        src = ROOT / "main" / "decks" / deck / name if name else None
        if src is not None and not src.exists():   # 맥에서 온 파일 이름은 한글이 NFD 라 이름으로는 못 찾는다
            src = next((ROOT / "main" / "decks" / deck).glob("*.m4a"), None)
    ff = B.__dict__.get("find_ffmpeg")
    ff = (ff() if ff else None) or next((str(p) for p in [Path.home() / ".local/bin/ffmpeg"] if p.exists()), None)
    if not src or not src.exists() or not ff:
        return None
    dst = OUT / f"{deck}_{src.stem}_{sec}s.wav"
    if not dst.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        subprocess.run([ff, "-y", "-loglevel", "error", "-t", str(sec), "-i", str(src), "-ac", "1", "-ar", "48000", "-sample_fmt", "s16", str(dst)], check=True)
    return dst


def answer_audio(deck: str, say_sec: int, quiet_sec: int = 25) -> Path | None:
    """--real-stt 의 가짜 마이크 — 덱 녹음 앞 say_sec 초 + 조용함 quiet_sec 초. 크롬이 되풀이해 틀어서, 화상판 자동 받아쓰기가
    말 → 쉼(2.2초) → 초읽기(3초) → 자동 보내기로 한 바퀴 돈다. 조용함이 없으면 녹음이 쉼 없이 이어져 자동 보내기가 안 걸린다."""
    name = DECK_AUDIO.get(deck)
    src = ROOT / "main" / "decks" / deck / name if name else None
    if src is not None and not src.exists():   # 파일 이름의 한글이 NFD 로 저장돼 있으면 이름으로는 못 찾는다
        src = next((ROOT / "main" / "decks" / deck).glob("*.m4a"), None)
    ff = next((str(p) for p in [Path.home() / ".local/bin/ffmpeg"] if p.exists()), None) or "ffmpeg"
    if not src or not src.exists():
        return None
    dst = OUT / f"{deck}_answer_{say_sec}s_quiet{quiet_sec}s.wav"
    if not dst.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        subprocess.run([ff, "-y", "-loglevel", "error", "-t", str(say_sec), "-i", str(src), "-f", "lavfi", "-t", str(quiet_sec),
                        "-i", "anullsrc=r=48000:cl=mono", "-filter_complex", "[0:a]aresample=48000,aformat=channel_layouts=mono[a];[a][1:a]concat=n=2:v=0:a=1",
                        "-ac", "1", "-ar", "48000", "-sample_fmt", "s16", str(dst)], check=True)
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
        # 객석 삐약이(/api/v1/chatter)는 기다림 화면이 재료가 모이자마자 부르는 실 LLM(모델 넷 · 라운드 둘)이다 — 재생 실행이 이것만
        # 실제로 불러 과금이 났다 (10-03 수정 1회차에서 발견). 기록이 없으면 503 으로 막는다(리포트 객석은 결석으로 보인다)
        if not (rec / "chatter.json").exists():
            page.route("**/api/v1/chatter", lambda route: route.fulfill(
                status=503, content_type="application/json", body='{"error":"lab_replay","message":"실험실 재생 — 객석 호출 막음"}'))
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
    if args.cam_file:
        cam = Path(args.cam_file)
    audio = (answer_audio(args.deck, args.say_sec) if args.real_stt and not args.audio
             else deck_audio(args.deck, args.rec_sec + 30, Path(args.audio) if args.audio else None))
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
                            permissions=["camera", "microphone"], is_mobile=args.mobile, has_touch=args.mobile)
        if args.report_v2:   # 리포트 2.0 (docs/report-v2/) — 팀 플래그로 켠다. /VRShow 갈래는 리포트 단계 끝에서 따로 본다
            # /VRShow 안(정면 창 iframe 포함)에선 켜지 않는다 — 그 갈래는 플래그 없이 rhShowcase 로 켜져야 한다
            ctx.add_init_script("""try { const vr = /\\/vrshow/i.test(location.pathname) || (window.parent !== window && /\\/vrshow/i.test(window.parent.location.pathname));
              if (!vr) localStorage.setItem('cheokcheok:report-v2', '1'); } catch (_) {}""")
        ctx.add_init_script(REAL_STT_JS if args.real_stt else FAKE_SPEECH_JS)
        if args.studio_skin:
            # /studio 정면 창(ui/Frame.jsx)이 iframe 문서에 입히는 것과 같이 — <html class="sx-studio"> + css/studio-skin.css
            ctx.add_init_script("""document.addEventListener('DOMContentLoaded', () => {
              document.documentElement.classList.add('sx-studio');
              const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = '/css/studio-skin.css?v=lab'; document.head.appendChild(l); });""")
        if args.no_chatter:
            # 객석 삐약이(실 LLM 넷)는 막는다 — 리포트 객석은 결석으로 보인다 (과금 절약)
            ctx.route("**/api/v1/chatter", lambda route: route.fulfill(
                status=503, content_type="application/json", body='{"error":"lab_no_chatter","message":"실험실 — 객석 호출 막음"}'))
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
                        if path == "/api/v1/questions" and '"track":"10"' in (r.request.post_data or "").replace(" ", ""):
                            name = "questions_10.json"   # 「다른 개념」 묶음(--weave) — 화상판 질문 기록을 덮지 않게
                        try:
                            rec_dir.mkdir(parents=True, exist_ok=True)
                            (rec_dir / name).write_bytes(r.body())
                        except Exception as e:  # noqa: BLE001
                            print("  기록 실패", name, e)
        page.on("response", on_resp)
        # 지나간 주소 — 흐름 안에서 #/rehearsal 밖(#/new · #/qa · #/report)으로 빠지면 summarize 가 잡는다 (10-03 사용자)
        R["hash_trail"] = []

        def on_nav(frame):
            if frame != page.main_frame:
                return
            h = "#" + frame.url.split("#", 1)[1] if "#" in frame.url else ""
            if not R["hash_trail"] or R["hash_trail"][-1] != h:
                R["hash_trail"].append(h)
        page.on("framenavigated", on_nav)
        install(page, args, state)
        if args.rubric_via:
            # 채점 본문(behavior 포함)을 남기고 다른 브리지로 넘긴다 — 같은 본문에서 behavior 만 뺀 것도 채점해 총점이 같은지 본다 (발표 태도는 가중치 0)
            import urllib.request

            def _post(url: str, body: dict) -> dict:
                req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    return json.loads(r.read())

            def rubric_via(route):
                body = json.loads(route.request.post_data or "{}")
                (out / "rubric_req.json").write_text(json.dumps(body, ensure_ascii=False, indent=1))
                url = args.rubric_via.rstrip("/") + "/api/v1/rubric"
                with_b = _post(url, body)
                without = _post(url, {k: v for k, v in body.items() if k != "behavior"})
                (out / "rubric_with_behavior.json").write_text(json.dumps(with_b, ensure_ascii=False, indent=1))
                (out / "rubric_without_behavior.json").write_text(json.dumps(without, ensure_ascii=False, indent=1))
                R["rubric_check"] = {"has_behavior": bool(body.get("behavior")), "behavior_status": (body.get("behavior") or {}).get("status"),
                                     "score_with": with_b.get("score"), "score_without": without.get("score"),
                                     "beta": [(b.get("no"), b.get("status"), b.get("weight", None), b.get("score")) for b in with_b.get("beta", [])],
                                     "beta_without": [(b.get("no"), b.get("status")) for b in without.get("beta", [])]}
                print("  rubric_check", R["rubric_check"], flush=True)
                route.fulfill(status=200, content_type="application/json", body=json.dumps(with_b, ensure_ascii=False))
            page.route("**/api/v1/rubric", rubric_via)

        def dump_state() -> None:
            (out / "state.json").write_text(json.dumps(page.evaluate(STATE_JS), ensure_ascii=False, indent=1))

        def shot(name: str) -> Path:
            n["i"] += 1
            png = out / f"{n['i']:02d}_{name}.png"
            page.screenshot(path=str(png))
            if args.cam != "face":
                where = page.evaluate("document.getElementById('vrCall') ? 'vision' : (document.getElementById('bqStage')||{dataset:{}}).dataset.screen")
                if where == "qa":
                    R["contrast"][name] = B.glass_contrast(page, png)
                elif where == "vision":   # 비전 리허설 글자도 같은 잣대로 (10-03 점검 V-R2-1 — 화상판만 재서 흰 벽 앞 삐약이 이름이 안 잡혔다)
                    R["contrast"][name] = B.glass_contrast(page, png, VISION_TEXT)
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
            if args.upload:
                # 공개 방문자 — 내 자료 올리기 (10-08: 공개 리허설은 시연 덱 없이 올린 자료로만)
                page.set_input_files("#rhUpFile", args.upload)
                page.wait_for_timeout(1200)
                shot("upload_busy")
            else:
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
            if args.path in ("rec-partial", "rec-file"):
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
            # 「녹음 파일로 대신하기」 → 시트(이 발표의 녹음 m:ss · 내 녹음 파일) → 분석
            t0 = time.time()
            # 10-07: 발표 화면에 들어오자마자 누를 수 있다 (예전 10-04 는 마지막 장까지 넘겨야 열렸다) — 넘기지 않고 바로 연다
            gate = {"slide_before": page.evaluate("Number(nf.slide)"), "last": page.evaluate("rehearsalCount()"),
                    "open_now": not page.evaluate("document.getElementById('rhRecFinish').disabled")}
            page.click("#rhRecFinish")
            page.wait_for_selector("#rhRecSheet [data-sheet='file']", timeout=5000)
            page.wait_for_timeout(400)
            lay("rec_sheet")
            shot("rec_sheet" + ("_after_live" if live else ""))
            sheet = page.evaluate("document.getElementById('rhRecSheet').innerText")
            if args.path == "rec-file":
                # 내 녹음 파일 — 헤드리스 크로미움은 AAC(m4a) 길이를 못 읽어서 덱 녹음 앞 40초를 wav 로 바꿔 고른다 (재생 모드라 내용은 녹화 응답이 대신한다)
                wav = out / "my_take.wav"
                src = next((ROOT / "main" / "decks" / args.deck).glob("*.m4a"))   # 파일 이름의 한글이 NFD 로 저장돼 있어 이름으로는 못 찾는다
                subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-t", "40", "-i", str(src), "-ac", "1", "-ar", "16000", str(wav)], check=True)
                page.set_input_files("#rhRecFile", str(wav))
            else:
                # 같은 자료를 다르게 발표한 녹음이 둘이면 --take 번째(0 = 1번 녹음)
                page.click(f"#rhRecSheet [data-sheet='use'][data-take='{args.take}']")
            page.wait_for_selector("#bqStage[data-screen='wait']", timeout=90000)
            mark("rec_finish", t0, {"gate": gate, "sheet": sheet[:300], "uploaded": page.evaluate("nf.uploadedTake"), "mic": page.evaluate("nf.mic"),
                                    "cues": page.evaluate("(nf.visionCues||[]).length"), "hash": page.evaluate("location.hash")})

        # 10-13 Q&A 무대 「띠 · 틀 · 레일」(js/qa_stage.js) — 순간 · 띠 글 · 행동 줄 · 웹캠 틀 자리, 얼굴 구역(틀 가운데 44%)에 겹친 것
        WEAVE_JS = """() => { const $ = (s) => document.querySelector(s); const vis = (el) => !!el && !el.hidden && !!el.offsetParent && getComputedStyle(el).visibility !== 'hidden';
          const L = qa.live; const st = $('#bqStage'); const R = (el) => el ? (({left, top, width, height}) => ({left: Math.round(left), top: Math.round(top), w: Math.round(width), h: Math.round(height)}))(el.getBoundingClientRect()) : null;
          const video = $('#bqStage .bc-self video'); const v = video ? video.getBoundingClientRect() : null;
          const face = v ? { l: v.left + v.width * .28, r: v.left + v.width * .72, t: v.top + v.height * .1, b: v.bottom } : null;
          const over = face ? [...document.querySelectorAll('#bqStage .bc-call *')].filter((el) => vis(el) && !el.closest('.bc-self') && getComputedStyle(el).position !== 'static' || (vis(el) && el.matches('.qs-pop, .qs-zoom, .bc-talk, .bc-dock'))).filter((el) => {
            const b = el.getBoundingClientRect(); return b.width > 2 && b.height > 2 && b.left < face.r && b.right > face.l && b.top < face.b && b.bottom > face.t; }).map((el) => (el.id || el.className || el.tagName).toString().slice(0, 40)) : [];
          const txt = (s) => (($(s)||{}).textContent || '').replace(/\\s+/g, ' ').trim();
          return { qi: L.qi, n: L.questions.length, label: (L.questions[L.qi]||{}).label || '', phase: st.dataset.qsPhase || '',
            q: txt('#qsQ'), meta: txt('#qsMeta'), from: vis($('#qsFrom')) ? txt('#qsFromQ') : '', say: txt('#qsSay'),
            act: txt('#qsAct'), alt: txt('#qsAlt'), deck: txt('#qsDeckNo') + ' ' + txt('#qsDeckCap'),
            claim: vis($('#qsFrom')) ? txt('#qsFromQ') : '', beam: false, me: ((qa.turns||[]).filter((t) => t.who === 'me').slice(-1)[0] || {}).text || '',
            judgement: L.lastJudgement ? { verdict: L.lastJudgement.verdict, claim: L.lastJudgement.claim || '', followup: L.lastJudgement.followup || '', coach: L.lastJudgement.coach_stage || '' } : null,
            results: (L.results||[]).map((x) => ({ id: x.id, setAside: x.setAside || '', to: x.switchedTo || '', verdict: x.verdict, trail: x.trail })),
            face_overlap: over, rect: { video: R(video), band: R($('.qs-band')), rail: R($('.qs-rail')), strip: R($('.qs-strip')) } }; }"""

        def wv(tag: str) -> dict:
            st = page.evaluate(WEAVE_JS)
            R.setdefault("weave", {})[tag] = st
            print(f"  weave {tag:16s} qi={st['qi']}/{st['n']} phase={st['phase']} from={st['from'][:30]!r} video={st['rect']['video']} over={st['face_overlap']} meta={st['meta'][:40]!r} act={st['act'][:24]!r}", flush=True)
            return st

        def weak_answer() -> None:
            # 반쯤만 맞힌 답 — 엉성한 답의 첫 문장만 (통째로 보내면 바로 닫혀 꼬리질문이 안 나온다)
            text = page.evaluate("((liveWeakAnswer(qa.live.questions[qa.live.qi]) || '').split(/(?<=[.!?。])\\s+/)[0]) || '자료에 나온 내용이 핵심이라고 생각해요.'")
            if page.evaluate("typeof liveMic !== 'undefined' && !!liveMic"):
                page.evaluate("dropLiveMic()")
            # 받아쓴 것처럼 숨은 답 칸에 글을 넣고, 행동 줄의 「다 말했어요」(원래 #liveSend 를 누른다)로 보낸다
            page.evaluate("(t) => { const ta = document.getElementById('liveAnswer'); ta.value = t; ta.dispatchEvent(new Event('input', { bubbles: true })); }", text)
            page.wait_for_selector("#qsAct [data-qs-act='send']", timeout=5000)
            shot(f"stage_listening_{page.evaluate('qa.live.qi')}")
            page.click("#qsAct [data-qs-act='send']")
            page.wait_for_timeout(500)
            if page.evaluate("qa.live.busy"):
                shot(f"stage_thinking_{page.evaluate('qa.live.qi')}")
            page.wait_for_function("qa.live && !qa.live.busy", timeout=180000)
            page.wait_for_timeout(250); shot(f"stage_weave_a_{page.evaluate('qa.live.qi')}")
            page.wait_for_timeout(900); shot(f"stage_weave_b_{page.evaluate('qa.live.qi')}")
            page.wait_for_timeout(900)

        def menu(choice: str, chip: str = "") -> float:
            page.click("#qsAlt [data-qs-act='switch']")
            page.wait_for_selector("#qsPop:not([hidden])", timeout=5000)
            page.wait_for_timeout(500)
            if choice == "perspective":
                page.click("#qsPop [data-qs-sw='perspective']")
                page.wait_for_selector("#qsPop .qs-chips:not([hidden])", timeout=3000)
                page.wait_for_timeout(300)
                shot("weave_menu_persp")
                qi = page.evaluate("qa.live.qi")
                t = time.time()
                page.click(f"#qsPop [data-qs-p='{chip}']")
            else:
                if choice == "concept":
                    shot("weave_menu")
                qi = page.evaluate("qa.live.qi")
                t = time.time()
                page.click(f"#qsPop [data-qs-sw='{choice}']")
            page.wait_for_timeout(150)
            if page.evaluate("!!qa.live.switching"):
                shot(f"weave_{choice}_wait")
            page.wait_for_function("qa.live && !qa.live.busy && !qa.live.switching", timeout=240000)
            if page.evaluate(f"qa.live.qi === {qi}"):
                print(f"  weave {choice}: 질문이 그대로예요 —", page.evaluate("[...document.querySelectorAll('#stream .qa-note-line')].slice(-1).map(e=>e.textContent)[0]||''"), flush=True)
            sec = round(time.time() - t, 1)
            page.wait_for_timeout(450)
            shot(f"weave_{choice}_topic")
            page.wait_for_timeout(1400)
            return sec

        def weave() -> None:
            t0 = time.time()
            wv("enter")
            dbg = os.environ.get("WEAVE_DOCK_DBG")
            if dbg:
                print(json.dumps(page.evaluate(Path(dbg).read_text()), ensure_ascii=False, indent=1))
                raise _Until()
            # 1. 엉성한 답 → 판정(실 API) → 내 발언 칩 · 빛줄기 · 꼬리질문 (바로 닫히면 다음 질문에서 다시 — 세 번까지)
            for _ in range(3):
                qi0 = page.evaluate("qa.live.qi")
                weak_answer()
                if page.evaluate(f"qa.live.qi === {qi0} && !!(qa.live.lastJudgement && qa.live.lastJudgement.followup)"):
                    break
            st = wv("answer1")
            shot("weave_claim")
            for w, h in sizes:
                page.set_viewport_size({"width": w, "height": h}); page.wait_for_timeout(900)
                wv(f"answer1_{w}x{h}"); shot(f"weave_claim_{w}x{h}")
            if sizes:
                page.set_viewport_size({"width": VW, "height": VH}); page.wait_for_timeout(600)
            # 기록 서랍 · 자료 크게 보기 · 막혔어요 메뉴
            page.click("#qsHist"); page.wait_for_timeout(600); shot("stage_hist_open"); page.click("#qsHist"); page.wait_for_timeout(300)
            page.click("#qsZoomBtn"); page.wait_for_timeout(900); wv("zoom"); shot("stage_zoom"); page.click("#qsZoom [data-qs-z='close']"); page.wait_for_timeout(300)
            if page.query_selector("#qsAlt [data-qs-act='stuck']"):
                page.click("#qsAlt [data-qs-act='stuck']"); page.wait_for_timeout(400); shot("stage_stuck_menu")
                page.keyboard.press("Escape"); page.wait_for_timeout(300)
            # 2. 같은 주제, 다른 관점 (실 /qa/reframe)
            sec_b = menu("perspective", "example")
            st = wv("perspective")
            # 3. 그 질문에 답 → 내 발언
            weak_answer()
            wv("answer2")
            shot("weave_claim2")
            # 4. 다른 핵심 개념으로
            sec_a = menu("concept")
            wv("concept")
            # 5. 건너뛰기
            sec_c = menu("skip")
            wv("skip")
            shot("weave_after_skip")
            mark("weave", t0, {"sec_perspective": sec_b, "sec_concept": sec_a, "sec_skip": sec_c,
                               "pool": page.evaluate("Array.isArray(qa.live.conceptPool) ? qa.live.conceptPool.length : null")})
            # 6. 여기서 마치기 → 리포트 · 기록
            page.evaluate("finishLiveQaEarly()")
            page.wait_for_function("location.hash.startsWith('#/rehearsal/report')", timeout=30000)
            page.wait_for_timeout(3000)
            hist = page.evaluate("(() => { const all = JSON.parse(localStorage.getItem('cheokcheok:qa-history')||'{}'); return all[qa.live.sessionId] || null; })()")
            R["weave_history"] = hist
            rec = hist or {}
            beats = rec.get("beats") or []
            print("  history weak:", rec.get("weak"), "| total:", rec.get("total"), "| beats:", [(b.get("label"), b.get("bucket"), b.get("setAside")) for b in beats], flush=True)
            shot("weave_report")
            dump_state()

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
                if page.evaluate("location.hash === '#/rehearsal/qa'") or "fail" in st.values():
                    break
                if all(v == "done" for v in st.values()) and "wait_ready" not in R["layout"]:
                    lay("wait_ready")
                    shot("wait_ready")
                page.wait_for_timeout(1000)
            mark("wait", t0, {"steps": steps_seen,
                              "phase": page.evaluate("nf.pipelinePhase"), "reveal": page.evaluate("!!document.getElementById('f11RevealWrap')"),
                              "fail": page.evaluate("(document.getElementById('bqPrepFail')||{}).innerText || ''"),
                              "n_questions": page.evaluate("qa.live ? qa.live.questions.length : 0"), "hash": page.evaluate("location.hash")})
            if args.until == "wait" or page.evaluate("location.hash !== '#/rehearsal/qa'"):
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
            if args.weave:
                weave()
                return
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
                if first and args.qa_dwell:
                    page.wait_for_timeout(int(args.qa_dwell * 1000))
                tj = time.time()
                q = questions[qi] if qi < len(questions) else {}
                if st["retell"]:
                    page.evaluate("() => { const b = document.getElementById('liveSkipRetell') || document.getElementById('liveSend'); if (b) b.click(); }")
                    action = "skipretell"
                elif args.answer == "try" and first:
                    # 체험 줄 — 엉성하게 답해 보기 → 코치의 되묻기 → 정답 보기 → 이 답으로 보내기 (qa_live.js liveTryHtml · 10-06)
                    page.wait_for_selector("#liveTryWeak:not([disabled])", timeout=20000)
                    page.click("#liveTryWeak")
                    page.wait_for_timeout(400)
                    page.wait_for_function("qa.live && !qa.live.busy", timeout=180000)
                    page.wait_for_timeout(1200)
                    weak = {"sent": page.evaluate("(qa.turns||[]).filter(t=>t.who==='me').slice(-1).map(t=>t.text)[0]||''"),
                            "verdict": page.evaluate("qa.live.lastJudgement ? qa.live.lastJudgement.verdict : null"),
                            "followup": page.evaluate("qa.live.lastJudgement ? (qa.live.lastJudgement.followup||'') : ''"),
                            "coach": page.evaluate("[...document.querySelectorAll('#stream .msg.ai')].slice(-2).map(e=>e.innerText.trim().slice(0,240))")}
                    print(f"  Q{qi + 1} weak → {weak['verdict']} | {weak['sent'][:80]} | {weak['followup'][:120]}", flush=True)
                    if qi == 0:
                        shot("try_weak_judged")
                    R.setdefault("try", []).append({"qi": qi + 1, "weak": weak})
                    if page.evaluate("qa.live.qi === %d && !qa.live.awaitEnd && !qa.live.retell" % qi) and page.is_visible("#liveTryModel"):
                        page.click("#liveTryModel")
                        page.wait_for_function("(document.getElementById('liveTryText')||{}).dataset && document.getElementById('liveTryText').dataset.qid", timeout=20000)
                        model = page.evaluate("document.getElementById('liveTryText').textContent")
                        if qi == 0:
                            shot("try_model_open")
                        R["try"][-1]["model"] = model
                        if page.is_visible("#liveTrySend"):
                            page.click("#liveTrySend")
                            page.wait_for_timeout(400)
                            page.wait_for_function("qa.live && !qa.live.busy", timeout=180000)
                            last = page.evaluate("(qa.live.results||[]).slice(-1)[0] || null")
                            R["try"][-1]["model_result"] = last
                            print(f"  Q{qi + 1} model → {json.dumps(last, ensure_ascii=False)[:200]}", flush=True)
                    action = "try"
                elif args.real_stt and not first:
                    # 진짜 받아쓰기는 꼬리질문에도 저절로 다시 듣는다 — 같은 녹음을 또 보내면 판정만 쌓이므로 첫 답 하나만 받고
                    # 「여기까지 하고 리포트 보기」 로 나간다 (판정 과금을 묶는다)
                    R["real_stt_finish"] = True
                    break
                elif args.answer == "dictate" and first:
                    # 자동 받아쓰기 — 마이크가 저절로 켜지기를 기다렸다 말한다. 멈추면 2.2초 + 초읽기 3초 뒤 자동으로 보낸다
                    page.wait_for_function("window.__fakeListening() > 0", timeout=15000)
                    if args.real_stt:
                        # 진짜 A.X — 가짜 마이크가 덱 녹음을 말하고 쉰다. 「듣고 있어요…」 → 문장이 칸에 담김 → 쉼 → 초읽기 → 자동 보내기
                        seen = {"hearing": False, "box": ""}
                        n_me = page.evaluate("(qa.turns||[]).filter(t => t.who === 'me').length")
                        t_dict = time.time()
                        while time.time() - t_dict < 75:
                            st2 = page.evaluate("""() => ({ box: (document.getElementById('liveAnswer')||{}).value || '',
                                hearing: !!(typeof liveMic !== 'undefined' && liveMic && liveMic.speaking),
                                stage: (document.querySelector('#qsSay .qs-int')||{}).textContent || '',
                                sent: (qa.turns||[]).filter(t => t.who === 'me').length, busy: !!qa.live.busy })""")
                            if st2["hearing"] and not seen["hearing"]:
                                seen["hearing"] = True
                                seen["stage_hearing"] = st2["stage"]
                                if qi == 0:
                                    shot("qa_hearing")
                            if len(st2["box"]) > len(seen["box"]):
                                seen["box"] = st2["box"]
                                if qi == 0 and "box_shot" not in seen:
                                    seen["box_shot"] = True
                                    shot("qa_box_filled")
                            if st2["sent"] > n_me or st2["busy"]:
                                break
                            page.wait_for_timeout(250)
                        seen["sent"] = page.evaluate("(qa.turns||[]).filter(t => t.who === 'me').slice(-1).map(t => t.text)[0] || ''")
                        seen["sec"] = round(time.time() - t_dict, 1)
                        R.setdefault("real_stt", []).append({"qi": qi + 1, **{k: v for k, v in seen.items() if k != "box_shot"}})
                        print(f"  Q{qi + 1} 실시간 받아쓰기 {seen['sec']}s · 듣고 있어요={seen['hearing']} · 칸: {seen['box'][:90]}", flush=True)
                    else:
                        text = (q.get("gist") if q.get("gist") and not q.get("trap") else None) or SPOKEN.get(args.deck) or B.ANSWERS.get(args.deck, B.ANSWERS["수익률격차"])
                        page.evaluate("(t) => window.__fakeSay(t)", text)
                        page.wait_for_timeout(3600)
                        if qi == 0:
                            lay("qa_countdown")
                            shot("qa_countdown")
                    page.wait_for_function("qa.live.busy || qa.live.qi !== %d || (qa.live.turns||[]).length > 0" % qi, timeout=20000)
                    action = "dictate"
                else:
                    # 10-13 Q&A 무대(qa_stage.js)는 답 칸 · 보내기를 「글로 쓰기」 뒤에 숨긴다 — 칸에 바로 넣고 보내기 함수를 부른다
                    page.evaluate("""(t) => { if (typeof dropLiveMic === 'function') dropLiveMic();
                        const ta = document.getElementById('liveAnswer'); ta.value = t; submitLiveAnswer(); }""",
                                  SPOKEN.get(args.deck, "자료의 핵심은 이렇습니다."))
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
                    # 10-13 무대는 이 버튼들을 행동 줄 뒤에 숨기기도 한다 — 보이든 말든 DOM 의 버튼을 누른다
                    page.evaluate("() => { if (typeof dropLiveMic === 'function') dropLiveMic();"
                                  " const b = document.getElementById('liveReveal') || document.getElementById('liveStuck'); if (b) b.click(); }")
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
            stayed = page.evaluate("location.hash === '#/rehearsal/qa' && !!document.querySelector('#bqStage[data-screen=qa]')")
            # Q&A 무대(qa_stage.js, 10-13)는 원래 단추를 숨기고 자기 단추로 누른다 — 숨은 원래 단추를 직접 누른다
            page.evaluate("document.getElementById('liveSeeResult').click()")
            # 끝까지 왔으면 「결과 보기」, 아니면(진짜 받아쓰기는 첫 답 하나만) 「여기까지 하고 저장」 — 무대가 숨겨도 DOM 버튼을 누른다
            page.evaluate("() => { if (typeof dropLiveMic === 'function') dropLiveMic();"
                          " const b = document.getElementById('liveSeeResult') || document.getElementById('liveFinish'); if (b) b.click(); }")
            page.wait_for_function("location.hash.startsWith('#/rehearsal/report')", timeout=20000)
            page.wait_for_timeout(3000)
            sweep("report")
            dump_state()
            mark("report", t0, {"stayed_on_end_card_13s": stayed, "hash": page.evaluate("location.hash"), "flags": page.evaluate(FLAGS_JS),
                                "layer_gone": page.evaluate("!document.getElementById('bqStage')"), "cam_off": page.evaluate("!bq.cam.stream"),
                                "listening": page.evaluate("window.__fakeListening()"), "history": page.evaluate("(JSON.parse(localStorage.getItem('cheokcheok:qa-history')||'[]')).length"),
                                "title": page.evaluate("(document.querySelector('#app h1, #app .page-title')||{}).textContent||''")[:80]})
            if args.report_v2:
                R["report_v2"] = page.evaluate("""() => ({ on: !!document.querySelector('#app.rv2'), screens: document.querySelectorAll('.rv2 .nv-screen').length,
                  issues: document.querySelectorAll('.rv2 .nv-screen:last-child .nv-row[data-push^="issue:"]').length, title: (document.querySelector('.rv2 .nv-headline')||{}).textContent || '' })""")
                print("  report_v2   ", R["report_v2"], flush=True)
                # iOS 스택 — 홈에서 화면을 밀어 넣고(push) ‹ 로 돌아온다
                for route in ("issue", "replay", "audience", "practice"):
                    sel = ".rv2 .nv-screen:last-child [data-push^='issue:']" if route == "issue" else f".rv2 .nv-screen:last-child [data-push='{route}']"
                    page.click(sel); page.wait_for_timeout(800); shot(f"rv2_{route}")
                    page.click(".rv2 .nv-screen:last-child [data-back]"); page.wait_for_timeout(700)
                # Q&A 돌아보기 (10-17 리포트 개편) — 홈 카드의 첫 질문 화면: 질문 주제 · 내 답 · 판정 근거 · 30초 뼈대
                if page.query_selector(".rv2 .nv-screen:last-child [data-push^='qa:']"):
                    page.click(".rv2 .nv-screen:last-child [data-push^='qa:']"); page.wait_for_timeout(800); shot("rv2_qa")
                    R["report_v2"]["qa"] = page.evaluate("""() => ({ better: !!document.querySelector('.rv2 .nv-screen:last-child .rq-better'),
                      grounds: document.querySelectorAll('.rv2 .nv-screen:last-child .rq-ground').length, turns: document.querySelectorAll('.rv2 .nv-screen:last-child .rq-t').length })""")
                    R["report_v2"]["qa"]["beh_fact"] = page.evaluate("(document.querySelector('.rv2 .nv-screen:last-child .rq-beh')||{}).textContent || ''").strip()
                    page.click(".rv2 .nv-screen:last-child [data-back]"); page.wait_for_timeout(700)
                # 발표 태도(베타) — 홈 줄 하나 → 화면 (10-17 통합)
                R["report_v2"]["attitude_row"] = page.evaluate("(document.querySelector('.rv2 .nv-screen:last-child .hm-beh')||{}).innerText || ''")
                if page.query_selector(".rv2 .nv-screen:last-child [data-push='attitude']"):
                    page.click(".rv2 .nv-screen:last-child [data-push='attitude']"); page.wait_for_timeout(900); shot("rv2_attitude")
                    R["report_v2"]["attitude"] = page.evaluate("""() => ({ banner: document.querySelectorAll('.rv2 .nv-screen:last-child .hm-betabanner').length,
                      rows: [...document.querySelectorAll('.rv2 .nv-screen:last-child .bh-arow')].map((r) => r.innerText.replace(/\\s+/g, ' ').trim()),
                      head: (document.querySelector('.rv2 .nv-screen:last-child .bh-head')||{}).textContent || '' })""")
                    page.click(".rv2 .nv-screen:last-child [data-back]"); page.wait_for_timeout(700)
                R["behavior"] = page.evaluate("""() => { const b = nf.behavior || null; const pick = (v) => v ? { status: v.status, why: v.why, areas: (v.areas||[]).map(a => [a.key, a.word]),
                  first: v.first ? v.first.text : null, segs: (v.segs||[]).map(s => [s.seg, Math.round((s.dur||0)/100)/10, s.gaze]) } : null; return b ? { present: pick(b.present), qa: pick(b.qa) } : null; }""")
                print("  behavior    ", json.dumps(R.get("behavior"), ensure_ascii=False)[:600], flush=True)
                # 「질문은 이렇게 골랐어요」 (네 모델 후보 판, 10-17) — 홈 Q&A 카드 → 고른 과정 → 자리 · 3번+ 질문. 판은 /api/v1/qa/board 로 늦게 온다
                try:
                    page.wait_for_selector(".rv2 .nv-screen:last-child [data-push='board']", timeout=8000)
                    page.click(".rv2 .nv-screen:last-child [data-push='board']"); page.wait_for_timeout(1500); shot("rv2_board")
                    R["qa_board"] = page.evaluate("""() => ({ asked: document.querySelectorAll('.rv2 .nv-screen:last-child .qb-hit').length,
                      funnel: [...document.querySelectorAll('.rv2 .qb-funnel b')].map(b => b.textContent), rounds: document.querySelectorAll('.rv2 .nv-screen:last-child [data-push^="round:"]').length })""")
                    for pre in ("slot:", "round:"):
                        if page.query_selector(f".rv2 .nv-screen:last-child .nv-group [data-push^='{pre}']"):
                            page.click(f".rv2 .nv-screen:last-child .nv-group [data-push^='{pre}']"); page.wait_for_timeout(900); shot(f"rv2_board_{pre[:-1]}")
                            page.click(".rv2 .nv-screen:last-child [data-back]"); page.wait_for_timeout(700)
                except Exception as e:  # noqa: BLE001 — 판이 없는 리허설(QA_ENSEMBLE=0)은 진입 줄이 「한 모델이 골랐어요」
                    R["qa_board"] = {"error": str(e)[:120], "entry": page.evaluate("(document.querySelector('.rv2 .qb-entry')||{}).innerText || ''")}
                print("  qa_board    ", R.get("qa_board"), flush=True)
                # /VRShow 갈래 — 플래그 없이도 정면 창 안에선 리포트 2.0 인가 (마지막 리포트로 연다)
                vr = page.context.new_page()
                vr.set_viewport_size({"width": 1512, "height": 860})
                vr.goto(f"{args.base}/VRShow", wait_until="load")
                vr.evaluate("localStorage.removeItem('cheokcheok:report-v2')")
                vr.wait_for_timeout(4000)
                fr = next((f for f in vr.frames if 'index.html' in f.url), None)
                if fr:
                    fr.evaluate("location.hash = '#/rehearsal/report/last'")
                    vr.wait_for_timeout(5000)
                    R["vrshow_v2"] = fr.evaluate("""() => ({ on: !!document.querySelector('#app.rv2'), issues: document.querySelectorAll('.rv2 .nv-screen:last-child .nv-row[data-push^="issue:"]').length, legacy: !!document.querySelector('.rv2 [data-legacy]') })""")
                    vr.screenshot(path=str(out / "vrshow_report_v2.png"))
                    if True:   # 다시 연 리포트(#/report/last)도 판을 세션 메모리 · 저장본에서 다시 얹는다
                        vr.wait_for_timeout(2500)
                        fr.evaluate("rv2Handle && rv2Handle.open('board')"); vr.wait_for_timeout(1600)
                        vr.screenshot(path=str(out / "vrshow_board.png"))
                        R["vrshow_board"] = fr.evaluate("(document.querySelector('.rv2 .nv-screen:last-child .nv-large')||{}).textContent || ''")
                        fr.evaluate("(() => { const b = document.querySelector('.rv2 .nv-screen:last-child .nv-group [data-push^=\"slot:\"]'); if (b) b.click(); })()"); vr.wait_for_timeout(1200)
                        vr.screenshot(path=str(out / "vrshow_board_slot.png"))
                print("  vrshow_v2   ", R.get("vrshow_v2"), flush=True)
                vr.close()
                page.evaluate("try { localStorage.setItem('cheokcheok:report-v2', '1'); } catch (_) {}")
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
            page.wait_for_selector("#bqStage[data-flow='rehearsal'][data-screen='pick'] " + ("#rhUpPick" if args.upload else ".bq-deck[data-deck]"), timeout=30000)
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
            if args.storage_out:
                try:
                    ctx.storage_state(path=args.storage_out)
                except Exception as e:  # noqa: BLE001
                    print("  저장소 저장 실패", e)
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
    audio = deck_audio(args.deck, args.rec_sec + 30, Path(args.audio) if args.audio else None)
    R: dict = {"args": vars(args), "checks": {}, "console": []}
    state: dict = {"judge_calls": 0, "judge_log": []}
    with sync_playwright() as p:
        flags = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", f"--use-file-for-fake-video-capture={cam}",
                 "--autoplay-policy=no-user-gesture-required"] + ([f"--use-file-for-fake-audio-capture={audio}"] if audio else [])
        b = p.chromium.launch(args=flags)
        ctx = b.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=1, locale="ko-KR", permissions=["camera", "microphone"])
        ctx.add_init_script(REAL_STT_JS if args.real_stt else FAKE_SPEECH_JS)
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
            # 흐름 안 화면은 주소도 #/rehearsal 아래여야 한다 — 예전엔 #/new · #/qa 로 빠졌다 (10-03 사용자)
            if expect.startswith(("rehearsal", "vision")):
                c["hash_ok"] = str(c.get("hash") or "").startswith("#/rehearsal")
                c["ok"] = c["ok"] and c["hash_ok"]
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
            # 「어떤 발표인가요」 는 제 주소(#/rehearsal/occ) — 새로고침해도 고른 발표 그대로 (10-03 F7)
            check("occ_reload", expect="rehearsal:occ")
            page.wait_for_selector("#bqStage #rhGoVision", timeout=60000)
            page.click("#rhGoVision")
            page.wait_for_selector("#vrCall #recStart", timeout=60000)
            check("vision_reload", expect="vision")
            page.wait_for_selector("#vrCall #recStart", timeout=30000)
            page.go_back()
            check("vision_back", reload=False, expect="rehearsal:occ")   # 발표하기 전이면 「어떤 발표인가요」 로 돌아간다
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
            page.wait_for_function("location.hash === '#/rehearsal/qa' || !!(document.getElementById('rhResume') && !document.getElementById('rhResume').hidden)",
                                   timeout=args.wait_timeout * 1000)
            R["checks"]["wait_reload_then"] = {"auto_entered": page.evaluate("location.hash === '#/rehearsal/qa'")}
            if page.evaluate("location.hash !== '#/rehearsal/qa'"):
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
                                        "ok": page.evaluate("!document.getElementById('bqSheet') && location.hash === '#/rehearsal/qa'")}
            print("  esc_twice              ", R["checks"]["esc_twice"], flush=True)
            # 질문 상태를 잃은 채 새로고침 — 일반 질문 코칭(트랙 고르기)이 아니라 리허설 자리로
            page.evaluate("sessionStorage.removeItem('cheokcheok:qa-flow')")
            check("qa_state_lost", expect="rehearsal:wait")
            # 주소창 /rehearsal/qa 로 바로 들어와도(브리지 302 → #/rehearsal/qa) 리허설 화상판 (10-03 사용자: 주소는 /rehearsal 아래)
            page.goto(f"{args.base}/rehearsal/qa", wait_until="load")
            c = check("qa_direct_path", reload=False, expect="rehearsal:")
            c["ok"] = c["ok"] and c["hash"] in ("#/rehearsal/qa", "#/rehearsal/new")
            # 나가기 — 시트 → 홈. 표시가 다 꺼져야 한다
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
            bad.append(f"{tag}: 가로 넘침 {L.get('wide') or ''}")
    errs = [c for c in R.get("console", []) if c.startswith(("error", "pageerror"))]
    if R.get("contrast"):
        allv = [(t, s, v) for t, d in R["contrast"].items() for s, v in d.items()]
        low = [x for x in allv if x[2] < 4.5]
        print(f"글자 대비(사진) {len(allv)}곳 · 최저 {min(v for *_, v in allv) if allv else '-'} · 4.5 아래 {len(low)}곳")
        for x in low[:12]:
            print("  ▽", x)
    trail = R.get("hash_trail") or []
    if trail:
        # 리포트에 닿기 전까지(그 뒤는 일부러 흐름 밖 #/qa · 부스로 나가 본다) 주소가 늘 #/rehearsal 아래였나
        upto = next((i for i, h in enumerate(trail) if h.startswith("#/rehearsal/report")), len(trail) - 1)
        leaked = [h for h in trail[:upto + 1] if h and not h.startswith("#/rehearsal")]
        print(f"지나간 주소 {' → '.join(trail[:upto + 1])}")
        print(f"흐름 밖으로 빠진 주소 {len(leaked)}개 {leaked}")
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
    ap.add_argument("--answer", choices=["dictate", "type", "try"], default="dictate")
    ap.add_argument("--no-move-slide", dest="move_slide", action="store_false", help="발표 중 자료 창을 옮기지 않는다 (화상판 기본 자리 확인)")
    ap.add_argument("--record", default="")
    ap.add_argument("--replay", default="")
    ap.add_argument("--fake-judge", action="store_true")
    ap.add_argument("--replay-delay", type=float, default=8, help="--replay: 질문 생성 응답을 이 초만큼 늦춘다 (기다림 화면 사진)")
    ap.add_argument("--until", choices=["pick", "rehearse", "wait", "qa", "report"], default="report")
    ap.add_argument("--occ", default="", help="발표 상황 (OCC_LABEL 의 값, 예: 업무 보고 (상사 대상)) — 비우면 추정을 그대로, 추정이 없으면 수업")
    ap.add_argument("--path", choices=["live", "rec", "rec-partial", "rec-file"], default="live",
                    help="live = 발표 마치기 · rec = 발표 없이 「녹음 파일로 대신하기」(이 발표의 녹음) · rec-partial = 몇 초 발표하다가 이 발표의 녹음으로 · rec-file = 몇 초 발표하다가 내 녹음 파일로")
    ap.add_argument("--take", type=int, default=0, help="녹음 파일로 대신할 때 고를 녹음 (0 = 1번, 1 = 2번 — 부스 세트는 주제마다 둘)")
    ap.add_argument("--reload", action="store_true")
    ap.add_argument("--tag", default="")
    ap.add_argument("--upload", default="", help="공개 방문자처럼 이 자료(PDF · PPTX)를 올려서 시작한다 (시연 덱 대신)")
    ap.add_argument("--audio", default="", help="가짜 마이크로 흘릴 녹음 파일 (기본: main/decks/<덱>/ 의 녹음)")
    ap.add_argument("--real-stt", action="store_true", help="실시간 받아쓰기를 흉내 내지 않고 진짜 A.X 로 (가짜 마이크 소리를 받아쓴다 — 과금)")
    ap.add_argument("--say-sec", type=int, default=12, help="--real-stt: 가짜 마이크의 말 길이 (그 뒤 25초 조용함, 되풀이)")
    ap.add_argument("--mobile", action="store_true", help="폰처럼 — is_mobile · has_touch")
    ap.add_argument("--no-chatter", action="store_true", help="객석 삐약이(/api/v1/chatter, 실 LLM 넷)를 막는다")
    ap.add_argument("--studio-skin", action="store_true", help="스튜디오 정면 창처럼 sx-studio 옷을 입힌다 (--viewport 를 창 크기로, 예: 1361x757)")
    ap.add_argument("--report-v2", dest="report_v2", action="store_true", help="리포트 2.0 으로 리포트를 그리고(팀 플래그) /VRShow 정면 창 갈래도 본다 (docs/report-v2/)")
    ap.add_argument("--cam-file", default="", help="가짜 카메라로 흘릴 영상(y4m · mjpeg) — 발표 태도(카메라 분석)를 재려면 실제 얼굴이 든 정답 영상 (예: /data/models/_runs/behavior-cv/lab/clips/d0_clean.y4m)")
    ap.add_argument("--rubric-via", default="", help="채점(/api/v1/rubric) 본문을 이 브리지(예: mock 모드 http://127.0.0.1:8846)로 넘기고 behavior 를 뺀 본문으로도 한 번 더 — 베타 항목 · 총점 불변을 과금 없이 본다")
    ap.add_argument("--qa-dwell", type=float, default=0, help="질문마다 답하기 전에 이만큼(초) 화상판에 머문다 — 질문별 카메라 값(8초 넘게 머문 질문만)을 남기려고")
    ap.add_argument("--storage-out", default="", help="끝난 뒤 브라우저 저장소(localStorage)를 이 파일로 — 다른 크기로 리포트를 다시 열어 찍을 때")
    ap.add_argument("--weave", action="store_true", help="Q&A 생각 엮기(10-13) — 엉성한 답 → 내 발언 · 꼬리질문 → 관점 바꾸기 → 다른 개념 → 건너뛰기 → 리포트 기록")
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
