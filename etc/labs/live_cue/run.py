"""
발표 중 자세 알림(js/behavior_cue.js) 실험실 — 정답 영상을 가짜 카메라로 흘려 리허설(/rehearsal) 비전 리허설에서 실제로 발표(녹음)하고,
알림이 뜬 순간을 찍고, 그 순간 엔진이 본 영상 프레임(바코드)을 정답 구간과 맞춘다.

이 서버엔 웹캠이 없다. 카메라 = 정답 실험실 영상(.y4m, 오른쪽 위 프레임 번호 바코드), 마이크 = 덱 녹음(rehearsal_flow 와 같은 것) —
삐약이 목소리 반응도 같이 떠서 「겹치지 않는가」 를 본다. 받아쓰기는 rehearsal_flow 의 가짜 WebSocket(__fakeSay). 과금 없음:
브리지는 mock(MOCK_EXTERNAL_APIS=true)으로 띄운다 — 이 실험은 발표 화면까지만 쓰고 분석 결과는 보지 않는다.

    # 준비 — mock 브리지는 시연 덱을 미리 파싱하지 않아서 고르기 화면에 덱이 안 뜬다: 실 브리지가 남긴 파싱본 보관소를 복사해 쓴다.
    #        덱 녹음(가짜 마이크)은 main/decks/<덱> 이 있어야 한다 — 본 저장소 것을 링크하고, 커밋 전엔 지운다
    #        (링크가 있으면 etc/tests/test_booth_qa_1006.py 가 덱 녹음을 찾아 다른 길로 가서 깨진다)
    cp -r /data/models/_runs/behavior-cv/var/data /data/models/_runs/live-cue/var/data
    ln -s ~/project/chuckchuck/main/decks/배달앱별점인플레이션A main/decks/
    # 브리지 (mock · 이 worktree 의 main/web · 팀 경로 열기)
    cd main && MOCK_EXTERNAL_APIS=true DEMO_DEV_ROUTES=1 DEMO_PORT=8851 DEMO_DATA_DIR=/data/models/_runs/live-cue/var/data python -m server.bridge
    # 한 편
    LD_LIBRARY_PATH=$HOME/.local/lib/pwlibs ~/project/chuckchuck/.venv/bin/python etc/labs/live_cue/run.py \
        --clip /data/models/_runs/live-cue/clips/c01_live_cue.y4m --tag c01
    # 스위치를 끄고 (알림이 하나도 없어야 하고, 새로 고쳐도 꺼져 있어야 한다)
    ... run.py --clip .../s03_lookaway.y4m --cue-off --tag s03_off

결과: /data/models/_runs/live-cue/runs/<시각>_<tag>/ — 알림마다 사진(cue_NN_<종류>.png) · report.json(알림 · 영상 시각 · 정답 구간 ·
보인 시간 · 목소리 반응과 겹친 표본 수 · 마친 뒤 nf.behavior.present.liveCues).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = Path("/data/models/_runs/live-cue/runs")
LABTAP = ROOT / "etc/labs/behavior_cv/web/labtap.js"


def _rf():
    spec = importlib.util.spec_from_file_location("rehearsal_flow_run", ROOT / "etc/labs/rehearsal_flow/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RF = _rf()

# 0.1초마다 — 자세 알림 알약 · 삐약이 목소리 말풍선 · 녹음 시계
MON_JS = """() => {
  const vis = (el) => !!el && !el.hidden && el.getClientRects().length > 0;
  const bc = document.getElementById('vrBcue'); const line = document.getElementById('vrLine');
  const sw = document.getElementById('vrBcueSwitch');
  return { perf: performance.now(), bc: vis(bc) ? { text: bc.textContent, type: bc.dataset.cue || '', box: bc.getBoundingClientRect().toJSON() } : null,
    line: vis(line) ? line.textContent : null, mic: (typeof nf !== 'undefined' && nf) ? nf.mic : null,
    sec: (typeof nf !== 'undefined' && nf) ? nf.sec : null, slide: (typeof nf !== 'undefined' && nf) ? nf.slide : null,
    sw: sw ? { hidden: sw.hidden, checked: sw.getAttribute('aria-checked') } : null,
    frame: window.LabTap && LabTap.cur ? LabTap.cur.frame : null, cv: window.BehaviorCV ? BehaviorCV.snapshot().rows : null };
}"""


def gt_segments(gt: dict) -> dict:
    s = gt["segments"]
    deg = gt.get("degrade") or {}
    return {
        "away": [x for x in s["lookaway"] if x.get("dir") != "down"],
        "down": s["down"],
        "sway": s["sway"],
        "frame": s["absent"],
        "backlit": [{"t0": 0, "t1": gt["duration"]}] if deg.get("backlit") else [],
        "far": [{"t0": 0, "t1": gt["duration"]}] if gt["name"].startswith("d7") else [],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8851")
    ap.add_argument("--clip", required=True, help="정답 영상 .y4m (옆에 .gt.json)")
    ap.add_argument("--deck", default="배달앱별점인플레이션A")
    ap.add_argument("--sec", type=float, default=0, help="발표(녹음) 길이 — 0 이면 영상 길이 + 3초")
    ap.add_argument("--no-audio", action="store_true", help="가짜 마이크를 조용하게 (삐약이 목소리 반응 없이)")
    ap.add_argument("--cue-off", action="store_true", help="시작 전 「발표 중 자세 알림」 스위치를 끈다")
    ap.add_argument("--no-align", action="store_true", help="영상 첫 프레임에 맞춰 녹음을 시작하지 않는다")
    ap.add_argument("--viewport", default="1512x860")
    ap.add_argument("--dpr", type=float, default=1)
    ap.add_argument("--mobile", action="store_true")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    clip = Path(args.clip)
    gt = json.loads(clip.with_suffix(".gt.json").read_text())
    fps = gt["fps"]
    n_frames = gt["n_frames"]
    rec_sec = args.sec or gt["duration"] + 3
    out = OUT / (datetime.now().strftime("%Y%m%dT%H%M%S") + (f"_{args.tag}" if args.tag else ""))
    out.mkdir(parents=True, exist_ok=True)
    VW, VH = (int(x) for x in args.viewport.split("x"))
    audio = None if args.no_audio else RF.deck_audio(args.deck, int(rec_sec) + 90)
    R: dict = {"args": vars(args), "clip": gt["name"], "audio": str(audio) if audio else None, "console": [], "samples": 0}
    shots: list = []
    t_start = time.time()

    with sync_playwright() as p:
        flags = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", f"--use-file-for-fake-video-capture={clip}",
                 "--autoplay-policy=no-user-gesture-required"]
        if audio:
            flags.append(f"--use-file-for-fake-audio-capture={audio}")
        b = p.chromium.launch(args=flags)
        ctx = b.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=args.dpr, locale="ko-KR",
                            permissions=["camera", "microphone"], is_mobile=args.mobile, has_touch=args.mobile)
        ctx.add_init_script(RF.FAKE_SPEECH_JS)
        ctx.add_init_script(LABTAP.read_text())
        ctx.route("**/api/v1/chatter", lambda route: route.fulfill(status=503, content_type="application/json", body='{"error":"lab"}'))
        page = ctx.new_page()
        page.on("console", lambda m: R["console"].append(f"{m.type}: {m.text}"[:300]) if m.type in ("error", "warning") and "GL Driver" not in m.text else None)
        page.on("pageerror", lambda e: R["console"].append(f"pageerror: {e}"[:300]))

        def shot(name: str) -> str:
            png = out / f"{len(shots) + 1:02d}_{name}.png"
            page.screenshot(path=str(png))
            shots.append(png.name)
            return png.name

        # ── 고르기 → 상황 → 비전 리허설 ──
        page.goto(f"{args.base}/rehearsal", wait_until="load")
        page.wait_for_selector(f"#bqStage .bq-deck[data-deck='{args.deck}']", timeout=40000)
        page.click(f"#bqStage .bq-deck[data-deck='{args.deck}']")
        page.wait_for_selector("#bqStage[data-screen='occ'] #rhGoVision", timeout=60000)
        page.wait_for_timeout(600)
        if not page.evaluate("nf.occ"):
            page.click('#bqStage .bq-role[data-occ="학교 프로젝트 (교수 대상)"]')
        page.click("#rhGoVision")
        page.wait_for_selector("#vrCall #recStart", timeout=60000)
        page.wait_for_selector("#vrCall #vrBcueSwitch", timeout=20000)
        page.wait_for_function("document.getElementById('vrSelfVideo') && document.getElementById('vrSelfVideo').videoWidth > 0", timeout=30000)
        page.evaluate("LabTap.watch(document.getElementById('vrSelfVideo'))")
        R["switch_before"] = page.evaluate(MON_JS)["sw"]
        if args.cue_off:
            page.click("#vrBcueSwitch")
            page.wait_for_timeout(300)
            R["switch_after_click"] = page.evaluate("({ sw: document.getElementById('vrBcueSwitch').getAttribute('aria-checked'), pref: localStorage.getItem('cheokcheok:behavior-cue') })")
            # 새로 고쳐도 꺼져 있나 — 같은 화면으로 다시 들어온다
            page.reload(wait_until="load")
            page.wait_for_selector("#vrCall #vrBcueSwitch", timeout=60000)
            page.wait_for_function("document.getElementById('vrSelfVideo') && document.getElementById('vrSelfVideo').videoWidth > 0", timeout=30000)
            page.evaluate("LabTap.watch(document.getElementById('vrSelfVideo'))")
            R["switch_after_reload"] = page.evaluate("document.getElementById('vrBcueSwitch').getAttribute('aria-checked')")
        # 엔진 · 도구가 먼저 받아지게 (녹음 전 load)
        try:
            page.wait_for_function("window.BehaviorCV && BehaviorCV.status() === 'ready'", timeout=60000)
        except Exception:  # noqa: BLE001
            R["cv_status_before"] = page.evaluate("window.BehaviorCV ? BehaviorCV.status() : 'none'")
        page.wait_for_timeout(800)
        shot("vision_idle")
        # 영상 첫 프레임에 맞춰 시작 — 알림 순서가 대본 순서대로 나오게(가짜 카메라는 영상을 되풀이한다)
        if not args.no_align:
            deadline = time.time() + gt["duration"] + 10
            while time.time() < deadline:
                f = page.evaluate("window.LabTap && LabTap.cur ? LabTap.cur.frame : -1")
                if f >= n_frames - int(fps * 1.2):
                    break
                page.wait_for_timeout(100)
            while time.time() < deadline:
                f = page.evaluate("window.LabTap && LabTap.cur ? LabTap.cur.frame : -1")
                if 0 <= f < int(fps * 0.6):
                    break
                page.wait_for_timeout(30)
        R["frame_at_start"] = page.evaluate("window.LabTap && LabTap.cur ? LabTap.cur.frame : -1")
        page.click("#recStart")
        page.wait_for_selector("#recEnd", timeout=30000)
        perf0 = page.evaluate("performance.now()")
        R["switch_recording"] = page.evaluate(MON_JS)["sw"]

        # ── 발표하는 동안 0.1초마다 엿본다 ──
        mons = []
        seen = None
        said = 0
        t_rec = time.time()
        while time.time() - t_rec < rec_sec:
            m = page.evaluate(MON_JS)
            m["wall"] = round(time.time() - t_rec, 2)
            mons.append(m)
            if m["bc"] and (seen is None or seen != (m["bc"]["type"], m["bc"]["text"])):
                seen = (m["bc"]["type"], m["bc"]["text"])
                page.wait_for_timeout(260)   # 들어오는 움직임(0.24초)이 끝난 뒤
                m["shot"] = shot(f"cue_{m['bc']['type']}")
            elif not m["bc"]:
                seen = None
            if int(m["wall"] // 6) > said:   # 6초마다 한 문장 — 받아쓰기 글자가 늘어 삐약이 빠르기 반응이 돈다
                said = int(m["wall"] // 6)
                page.evaluate("(t) => window.__fakeSay(t)", RF.VISION_SAYS[said % len(RF.VISION_SAYS)])
            page.wait_for_timeout(100)
        R["samples"] = len(mons)
        peek = page.evaluate("BehaviorCue.peek()")
        joined = page.evaluate("LabTap.joined().map(j => ({ t: j.t, frame: j.frame, row: j.row }))")
        # 엔진 줄 + 영상 프레임 — replay.mjs 로 브라우저 없이 다시 돌려 볼 수 있게 (row._frame)
        (out / "engine_rows.json").write_text(json.dumps([{**j["row"], "_frame": j["frame"]} for j in joined if j.get("row")], ensure_ascii=False))
        snap = page.evaluate("BehaviorCV.snapshot()")
        R["engine"] = {"status": snap.get("status"), "rows": snap.get("rows"), "tickMs": snap.get("tickMs"), "badBar": page.evaluate("LabTap.badBar")}

        # ── 마치기 → nf.behavior.present.liveCues ──
        page.click("#recEnd")
        page.wait_for_timeout(800)
        sheet = page.query_selector("text=이대로 마치기")
        if sheet:
            sheet.click()
        try:
            page.wait_for_function("typeof nf !== 'undefined' && nf.behavior && nf.behavior.present", timeout=30000)
            R["live_cues_saved"] = page.evaluate("nf.behavior.present.liveCues || null")
            R["summary_keys"] = page.evaluate("Object.keys((nf.behavior.present.summary) || {})")
        except Exception as e:  # noqa: BLE001
            R["finish_error"] = str(e)[:200]
        b.close()

    # ── 맞춰 보기 ──
    def frame_of(t_ms: float):
        best = None
        for j in joined:
            if j["t"] is None or j["frame"] is None or j["frame"] < 0:
                continue
            if best is None or abs(j["t"] - t_ms) < abs(best["t"] - t_ms):
                best = j
        return best["frame"] if best else None

    segs = gt_segments(gt)
    cues = []
    for c in peek["list"]:
        fr = frame_of(c["t"] * 1000)
        clip_t = fr / fps if fr is not None else None
        hit = None
        if clip_t is not None:
            hit = next((s for s in segs.get(c["type"], []) if s["t0"] - 0.5 <= clip_t <= s["t1"] + 0.5), None)
        cues.append({**c, "clip_frame": fr, "clip_sec": round(clip_t, 2) if clip_t is not None else None,
                     "in_gt": hit is not None, "gt_seg": hit})
    # 보인 구간(벽시계) · 목소리 말풍선과 겹친 표본
    shown, cur = [], None
    for m in mons:
        if m["bc"] and cur is None:
            cur = {"type": m["bc"]["type"], "text": m["bc"]["text"], "from": m["wall"], "perf": round(m["perf"] - perf0)}
        elif not m["bc"] and cur is not None:
            cur["to"] = m["wall"]
            cur["dur"] = round(cur["to"] - cur["from"], 2)
            shown.append(cur)
            cur = None
    if cur:
        shown.append(cur)
    overlap = [m["wall"] for m in mons if m["bc"] and m["line"]]
    vruns, vc = [], None   # 삐약이 목소리 말풍선이 떠 있던 구간
    for m in mons:
        if m["line"] and (vc is None or vc["text"] != m["line"]):
            if vc:
                vc["to"] = m["wall"]
                vruns.append(vc)
            vc = {"text": m["line"], "from": m["wall"]}
        elif not m["line"] and vc is not None:
            vc["to"] = m["wall"]
            vruns.append(vc)
            vc = None
    if vc:
        vc["to"] = mons[-1]["wall"]
        vruns.append(vc)
    R["voice_runs"] = vruns
    # 「겹침」 = 자세 알림이 떠 있는 동안 말풍선이 새로 뜨거나 바뀜, 또는 말풍선이 바뀐 지 3초 안에 자세 알림이 뜸 (behavior_cue.js voiceGate).
    # 같은 말풍선이 오래 떠 있는 채 자세 알림이 뜬 표본(co_visible)은 따로 센다 — 막지 않기로 한 경우
    R["fresh_overlap"] = []
    for sh in shown:
        for v in vruns:
            if sh["from"] - 2.8 <= v["from"] < sh["from"]:          # 말풍선이 바뀐 지 3초 안에 자세 알림이 떴다 (0.2초는 엿보기 간격)
                R["fresh_overlap"].append({"why": "too_soon", "cue": sh["text"], "voice": v["text"], "voice_from": v["from"], "cue_from": sh["from"]})
            elif sh["from"] <= v["from"] < sh.get("to", 1e9) and sh.get("to", 1e9) - v["from"] > 0.35:   # 새 말풍선이 떴는데 안 걷혔다
                R["fresh_overlap"].append({"why": "not_hidden", "cue": sh["text"], "voice": v["text"], "voice_from": v["from"], "cue_to": sh.get("to")})
    R["voice_hid_cue"] = [{"cue": sh["text"], "voice": v["text"], "at": v["from"]} for sh in shown for v in vruns
                          if sh["from"] <= v["from"] <= sh.get("to", 1e9) and sh.get("to", 1e9) - v["from"] <= 0.35]
    voice = sum(1 for m in mons if m["line"])
    R.update({"cues": cues, "shown": shown, "co_visible_samples": overlap, "voice_samples": voice, "shots": shots,
              "gt_segments": segs, "secs": round(time.time() - t_start, 1)})
    gaps = [round(b["t"] - a["t"], 1) for a, b in zip(peek["list"], peek["list"][1:])]
    R["gaps"] = gaps
    (out / "report.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
    print(f"\n{gt['name']} → {out}")
    print(f"  스위치 시작 전 {R['switch_before']} · 녹음 중 {R['switch_recording']}" + (f" · 끈 뒤 {R.get('switch_after_click')} · 새로 고친 뒤 {R.get('switch_after_reload')}" if args.cue_off else ""))
    print(f"  엔진 {R['engine']} · 시작 프레임 {R['frame_at_start']} · 표본 {R['samples']} · 목소리 말풍선 보인 표본 {voice} · "
          f"같이 보인 표본 {len(overlap)} · 새 말풍선과 겹침 {len(R['fresh_overlap'])} {R['fresh_overlap']} · 말풍선이 걷어 낸 알림 {R['voice_hid_cue']}")
    for c in cues:
        print(f"  ▶ 기록 {c['t']:5.1f}s (녹음 {c['sec']}s · {c['slide']}장)  영상 {c['clip_sec']}s  {c['type']:7s} {c['text']}  정답 구간 안={c['in_gt']} {c['gt_seg'] or ''}{'  (말풍선에 밀려 걷힘)' if c.get('cut') else ''}")
    for s in shown:
        print(f"  ◻ 보임 {s['from']:.1f}~{s.get('to', '…')}s ({s.get('dur', '…')}초) {s['text']}")
    print(f"  간격 {gaps} · 마친 뒤 liveCues {json.dumps(R.get('live_cues_saved'), ensure_ascii=False)[:300]}")
    print("  목소리 말풍선:", " · ".join(f"{v['text']} {v['from']:.1f}~{v['to']:.1f}" for v in vruns)[:600])
    if R["console"]:
        print("  콘솔:", R["console"][:5])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
