"""
부스 「사람 그래프」 스캔 화면(/booth/scan) 헤드리스 실험실 (2026-10-12) — 이 서버엔 웹캠이 없어서 가짜 카메라 · 마이크로 화면을 태우고 사진을 남긴다.

가짜 카메라는 getUserMedia 를 페이지 안에서 바꿔 치운다(eval-lab 10-08 과 같은 방식) — 모나리자(퍼블릭 도메인) 그림을 4:3 캔버스(960×720)에
그려 스트림으로 내보낸다. 4:3 을 16:9 · 16:10 화면에 cover 로 깔게 되므로 위아래 잘림 + 거울 좌표가 맞는지 사진으로 드러난다.
사람을 화면 한쪽(dx)으로 비켜 세워서 거울을 빼먹으면 그래프가 반대쪽에 뜨게 한다. 시험이 window.__fake 로 사람 수 · 숨기기 · 기울임 · 고개 돌림을 바꾼다.
소리는 부스 덱 녹음(16kHz wav)을 WebAudio 로 흘린다 — 「목소리·쉼」 이 켜지는지 본다.

찍는 장면 (화면 크기마다 1920×1080 · 1280×800):
  idle(아무도 없음) → assembling(점이 날아와 모임) → tracking(한 사람, 기울임·고개 돌림) → two(두 사람) → lost(얼굴이 빠져 흩어짐)
  → camera-denied(카메라를 막음) · model-failed(모델 주소를 막음, 1920 만)

    DEMO_PORT=9021 DEMO_DEV_ROUTES=1 DEMO_WARM_DECK_GROUPS= MOCK_EXTERNAL_APIS=false .venv/bin/python -m demo.bridge &   # PID 를 적어 둔다
    LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu .venv/bin/python labs/booth_scan/run.py --base http://localhost:9021 --media <mona.png · speech.wav 폴더>

결과: labs/booth_scan/out/<stamp>/*.png + report.json (장면마다 window.__boothScan() 상태 · 겹침 검사 · 콘솔 오류). 과금 없음(API 를 안 부른다).
getUserMedia 는 보안 출처에서만 열리므로 http://localhost 로 연다.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
SIZES = [(1920, 1080), (1280, 800)]

FAKE_JS = r"""
(() => {
  const F = window.__fake = { count: 1, hidden: true, dx: -0.16, roll: 0, rollAmp: 0, rollHz: 0.5, yaw: 0, yawAmp: 0, yawHz: 0.4,
                              persp: 0.45, deny: false, gain: 1 };
  const md = navigator.mediaDevices;
  const real = md.getUserMedia.bind(md);
  let img = null;
  async function canvasStream() {
    if (!img) { img = new Image(); img.src = '/__fake/mona.png'; await img.decode(); }
    const cv = document.createElement('canvas'); cv.width = 960; cv.height = 720;
    const ctx = cv.getContext('2d');
    const one = (cx, H, t) => {
      const W = H * img.width / img.height;
      const roll = (F.roll + F.rollAmp * Math.sin(2 * Math.PI * F.rollHz * t)) * Math.PI / 180;
      const yaw = (F.yaw + F.yawAmp * Math.sin(2 * Math.PI * F.yawHz * t)) * Math.PI / 180;
      const f = F.persp * W;
      ctx.save(); ctx.translate(cx, 720 - H / 2 + 40); ctx.rotate(roll);
      if (Math.abs(yaw) > 0.008) {
        for (let sx = 0; sx < img.width; sx += 2) {
          const u = (sx / img.width - 0.5) * W, x3 = u * Math.cos(yaw), z3 = u * Math.sin(yaw), s = f / (f + z3);
          const h = H * s;
          ctx.drawImage(img, sx, 0, 2, img.height, x3 * s, -h / 2, (2 * W / img.width) * Math.cos(yaw) * s + 0.8, h);
        }
      } else {
        ctx.drawImage(img, -W / 2, -H / 2, W, H);
      }
      ctx.restore();
    };
    const draw = () => {
      const t = performance.now() / 1000;
      ctx.fillStyle = '#8f8a80'; ctx.fillRect(0, 0, 960, 720);
      ctx.fillStyle = '#6f6a60'; ctx.fillRect(0, 560, 960, 160);
      if (F.hidden) return;
      if (F.count >= 2) { one(250, 600, t); one(700, 640, t + 0.7); }
      else one(480 + F.dx * 960, 760, t);
    };
    setInterval(draw, 33);
    draw();
    return cv.captureStream(30);
  }
  async function micStream() {
    const ac = new AudioContext();
    const ab = await ac.decodeAudioData(await (await fetch('/__fake/speech.wav')).arrayBuffer());
    const src = ac.createBufferSource(); src.buffer = ab; src.loop = true;
    const g = ac.createGain(); F.gainNode = g;
    const dest = ac.createMediaStreamDestination();
    src.connect(g).connect(dest); src.start();
    return dest.stream;
  }
  md.getUserMedia = async (c) => {
    if (F.deny) throw new DOMException('Permission denied', 'NotAllowedError');
    if (c && c.video) return canvasStream();
    if (c && c.audio) return micStream();
    return real(c);
  };
})();
"""

#: 머리글 · 판 · QR · 안내가 서로 겹치거나 화면 밖으로 나가지 않는지
LAYOUT_JS = """() => {
  const r = (s) => { const e = document.querySelector(s); if (!e) return null; const b = e.getBoundingClientRect();
    return { x0: Math.round(b.left), y0: Math.round(b.top), x1: Math.round(b.right), y1: Math.round(b.bottom) }; };
  const boxes = { head: r('.bs-head .bs-title'), panel: r('.bs-panel'), qr: r('.bs-qr'), privacy: r('.bs-privacy'), center: r('.bs-center') };
  const hit = (a, b) => a && b && a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
  const names = Object.keys(boxes), overlaps = [];
  for (let i = 0; i < names.length; i++) for (let j = i + 1; j < names.length; j++) {
    const a = names[i], b = names[j];
    if (a === 'center' || b === 'center') continue;
    if (hit(boxes[a], boxes[b])) overlaps.push(a + '×' + b);
  }
  const out = names.filter((n) => boxes[n] && (boxes[n].x0 < 0 || boxes[n].y0 < 0 || boxes[n].x1 > innerWidth || boxes[n].y1 > innerHeight));
  return { boxes, overlaps, offscreen: out, hscroll: document.documentElement.scrollWidth > innerWidth,
           font: getComputedStyle(document.body).fontFamily.split(',')[0] };
}"""

STATE_JS = "() => (window.__boothScan ? window.__boothScan() : null)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:9021")
    ap.add_argument("--media", required=True, help="mona.png · speech.wav 가 든 폴더")
    ap.add_argument("--only", choices=["1920", "1280"], default=None)
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    out = OUT / f"{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    media = Path(args.media)
    R: dict = {"base": args.base, "console": [], "shots": {}}
    flags = ["--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required", "--enable-unsafe-swiftshader"]

    with sync_playwright() as p:
        b = p.chromium.launch(args=flags)

        def context(w: int, h: int, deny: bool = False, block_model: bool = False):
            ctx = b.new_context(viewport={"width": w, "height": h}, permissions=["camera", "microphone"])
            ctx.add_init_script(FAKE_JS + ("window.__fake.deny = true;" if deny else ""))
            ctx.route("**/__fake/mona.png", lambda r: r.fulfill(path=str(media / "mona.png"), content_type="image/png"))
            ctx.route("**/__fake/speech.wav", lambda r: r.fulfill(path=str(media / "speech.wav"), content_type="audio/wav"))
            if block_model:
                ctx.route("**/vendor/mediapipe/**", lambda r: r.fulfill(status=404, body=""))
                ctx.route("https://cdn.jsdelivr.net/npm/@mediapipe/**", lambda r: r.abort())
            page = ctx.new_page()
            tag = f"{w}x{h}"
            page.on("console", lambda m: R["console"].append(f"[{tag}] {m.type}: {m.text}"[:300]) if m.type in ("error", "warning") else None)
            page.on("pageerror", lambda e: R["console"].append(f"[{tag}] pageerror: {e}"[:300]))
            return ctx, page

        def shot(page, name: str) -> None:
            path = out / f"{name}.png"
            page.screenshot(path=str(path))
            R["shots"][name] = {"state": page.evaluate(STATE_JS), "layout": page.evaluate(LAYOUT_JS), "t": round(time.time(), 1)}
            print(f"  찍음 {path.name}  {json.dumps(R['shots'][name]['state'], ensure_ascii=False)[:220]}")

        def fake(page, **kw) -> None:
            page.evaluate("(kw) => Object.assign(window.__fake, kw)", kw)

        def wait_state(page, cond: str, timeout_ms: int) -> bool:
            try:
                page.wait_for_function(f"(() => {{ const s = window.__boothScan && window.__boothScan(); return !!s && ({cond}); }})()",
                                       timeout=timeout_ms, polling=50)
                return True
            except Exception:  # noqa: BLE001 — 시간 안에 안 되면 그 상태 그대로 찍는다
                return False

        for w, h in SIZES:
            if args.only and str(w) != args.only:
                continue
            tag = f"{w}x{h}"
            print(f"== {tag}")
            ctx, page = context(w, h)
            t0 = time.time()
            page.goto(f"{args.base}/booth/scan", wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            shot(page, f"{tag}_0_loading")
            wait_state(page, "s.model === 'ready' || s.model === 'failed'", 240000)
            R[f"{tag}_ready_sec"] = round(time.time() - t0, 1)
            wait_state(page, "s.msg === 'idle'", 20000)
            page.wait_for_timeout(1500)
            shot(page, f"{tag}_1_idle")
            fake(page, hidden=False)
            ok = wait_state(page, "s.phases.includes('assemble')", 60000)
            page.wait_for_timeout(320)
            shot(page, f"{tag}_2_assembling" + ("" if ok else "_MISSED"))
            fake(page, rollAmp=6, rollHz=0.35, yawAmp=18, yawHz=0.25)
            wait_state(page, "s.phases.includes('track')", 20000)
            page.wait_for_timeout(4500)
            shot(page, f"{tag}_3_tracking")
            fake(page, rollAmp=0, yawAmp=0, count=2)
            wait_state(page, "s.people >= 2", 30000)
            page.wait_for_timeout(3500)
            shot(page, f"{tag}_4_two")
            fake(page, count=1, hidden=True)
            ok = wait_state(page, "s.phases.includes('scatter')", 30000)
            page.wait_for_timeout(180)
            shot(page, f"{tag}_5_lost" + ("" if ok else "_MISSED"))
            wait_state(page, "s.msg === 'idle' && s.phases.length === 0", 20000)
            page.wait_for_timeout(1200)
            shot(page, f"{tag}_6_idle_again")
            ctx.close()

            ctx, page = context(w, h, deny=True)
            page.goto(f"{args.base}/booth/scan", wait_until="domcontentloaded")
            wait_state(page, "s.cam === 'denied'", 20000)
            page.wait_for_timeout(1500)
            shot(page, f"{tag}_7_camera_denied")
            ctx.close()

        if not args.only or args.only == "1920":
            ctx, page = context(1920, 1080, block_model=True)
            page.goto(f"{args.base}/booth/scan", wait_until="domcontentloaded")
            wait_state(page, "s.model === 'failed'", 60000)
            page.wait_for_timeout(1500)
            shot(page, "1920x1080_8_model_failed")
            ctx.close()
        b.close()

    (out / "report.json").write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = {k: v["layout"]["overlaps"] + v["layout"]["offscreen"] for k, v in R["shots"].items() if v["layout"]["overlaps"] or v["layout"]["offscreen"]}
    print(f"\n결과 {out}\n겹침·밖: {bad or '없음'}\n콘솔 오류 {len(R['console'])}개")
    for line in R["console"][:15]:
        print("  ", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
