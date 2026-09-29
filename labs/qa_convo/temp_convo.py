"""
/temp 통화 배치 Q&A 대화 감사 — labs/temp_flow 의 흐름(업로드 → 발표 → 분석 → #/qa 통화 배치)을 따라가되,
Q&A 에서 한 번만 답하지 않고 여러 턴을 주고받으며 말풍선·버튼·배치를 턴마다 남긴다. 실 LLM·STT 과금.

    LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu .venv/bin/python labs/qa_convo/temp_convo.py --file ppt/_held_ir_banchan/ir_banchan.pptx
결과: labs/qa_convo/out/temp_<stamp>/turns.json · *.png
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
sys.path.insert(0, str(ROOT / "labs/qa_call"))
from fakecam import build as build_cam  # noqa: E402

spec = importlib.util.spec_from_file_location("temp_flow_run", ROOT / "labs/temp_flow/run.py")
TF = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TF)

# 반찬 덱 답 은행 (answers/_held_ir_banchan_t10.json 과 같은 글)
BANK = json.loads((HERE / "answers/_held_ir_banchan_t10.json").read_text(encoding="utf-8"))
KEYS = {"1": "한끼곳간 차별 동네 정기구독", "2": "월 반복 매출 구독자 수 지표", "3": "반드시 0개 마감 후 남는",
        "4": "도입 후 3,200", "5": "늘립니다 폐기 손실", "6": "53%", "7": "첫 달 이탈 유지"}


def pick(text: str) -> dict:
    best, score = BANK["2"], 0
    for k, keys in KEYS.items():
        s = sum(1 for w in keys.split() if w in text)
        if s > score:
            best, score = BANK[k], s
    return best


def run(args) -> Path:
    from playwright.sync_api import sync_playwright

    out = OUT / f"temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    cam = build_cam(out / "fakecam.mjpeg")
    audio = TF.fake_audio(args.rec_sec + 20)
    rec: dict = {"file": str(args.file), "turns": [], "layout": {}, "console": [], "net": []}
    n = [0]
    t_req: dict = {}

    with sync_playwright() as p:
        flags = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                 f"--use-file-for-fake-video-capture={cam}", "--autoplay-policy=no-user-gesture-required"]
        if audio:
            flags.append(f"--use-file-for-fake-audio-capture={audio}")
        b = p.chromium.launch(args=flags)
        ctx = b.new_context(viewport={"width": 1280, "height": 800}, permissions=["camera", "microphone"])
        page = ctx.new_page()
        page.on("console", lambda m: rec["console"].append(f"{m.type}: {m.text}"[:300]) if m.type == "error" else None)
        page.on("pageerror", lambda e: rec["console"].append(f"pageerror: {e}"[:300]))
        page.on("request", lambda r: t_req.__setitem__(r, time.time()) if "/api/" in r.url else None)

        def on_resp(r):
            if "/api/" not in r.url:
                return
            row = {"path": r.url.split("/api/")[-1][:70], "status": r.status, "sec": round(time.time() - t_req.get(r.request, time.time()), 1)}
            if "/qa/judge" in r.url:
                try:
                    row["res"] = r.json()
                except Exception:
                    pass
            rec["net"].append(row)
        page.on("response", on_resp)

        def shot(name: str) -> str:
            n[0] += 1
            f = f"{n[0]:02d}_{name}.png"
            page.screenshot(path=str(out / f))
            return f

        def stream_texts() -> list[str]:
            return page.evaluate("Array.from(document.querySelectorAll('#stream > *')).map(e => e.innerText)")

        def act(kind: str, text: str = "") -> dict:
            before = len(stream_texts())
            nn = len(rec["net"])
            t0 = time.time()
            if kind == "answer":
                page.fill("#liveAnswer", text)
                page.click("#liveSend")
            elif kind == "hint":
                page.click("#liveHint")
            elif kind == "stuck":
                page.click("#liveStuck")
            page.wait_for_function("() => qa.live && !qa.live.busy", timeout=180000)
            page.wait_for_timeout(1500)
            new = stream_texts()[before:]
            j = next((c.get("res") for c in reversed(rec["net"][nn:]) if c.get("res")), None)
            lay = page.evaluate(TF.LAYOUT_JS)
            row = {"action": kind, "input": text, "new": new, "judge": j, "sec": round(time.time() - t0, 1),
                   "counter": page.evaluate("(document.getElementById('cfQaCount')||{}).textContent"),
                   "buttons": page.evaluate("Array.from(document.querySelectorAll('.qa-live-input button')).filter(b => b.offsetParent).map(b => b.id + '|' + b.textContent.trim())"),
                   "layout": {k: lay.get(k) for k in ("mode", "main", "self", "hscroll", "clickable")}, "shot": shot(f"qa_{kind}")}
            rec["turns"].append(row)
            v = j or {}
            print(f"  {kind:6s} {text[:30]!r:34s} → {v.get('verdict', '-')}/{v.get('score', '-')} {v.get('coach_stage') or v.get('probe_tier') or ''} {row['sec']}s", flush=True)
            (out / "turns.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
            return row

        try:
            page.goto(f"{args.base}/temp", wait_until="networkidle")
            page.wait_for_selector("#file", state="attached")
            page.set_input_files("#file", str(args.file))
            page.wait_for_selector("#next, .accident", timeout=300000)
            page.click("#next")
            page.wait_for_selector("#go")
            page.fill("#ctx", "스타트업 경진대회 결선에서 심사위원 5명 앞에서 7분 투자 발표를 해요")
            page.click("#go")
            page.wait_for_selector("#cfCall #recStart", timeout=30000)
            page.wait_for_timeout(2000)
            page.click("#recStart")
            page.wait_for_selector("#recEnd", timeout=20000)
            nsl = page.evaluate("rehearsalCount()")
            step = max(3, args.rec_sec // max(1, min(nsl, 8)))
            waited = 0
            while waited < args.rec_sec:
                page.wait_for_timeout(step * 1000)
                waited += step
                if page.is_visible('.cf-dock [data-slide-nav="1"]'):
                    page.click('.cf-dock [data-slide-nav="1"]')
            shot("present_live")
            page.click("#recEnd")
            t0 = time.time()
            while time.time() - t0 < args.pipe_timeout:
                if page.evaluate("typeof pipelineQaReady === 'function' && pipelineQaReady()") or page.evaluate("nf.pipelinePhase") == "error":
                    break
                page.wait_for_timeout(2000)
            rec["analysis_sec"] = round(time.time() - t0, 1)
            rec["phase"] = page.evaluate("nf.pipelinePhase")
            page.evaluate("location.hash = '#/qa'")
            page.wait_for_timeout(800)
            if page.is_visible("#qaGateStart"):
                page.click(f'.qa-mode[data-mode="{args.track}"]')
                page.wait_for_timeout(300)
                shot("qa_gate")
                page.click("#qaGateStart")
            page.wait_for_selector("#cfCall #liveAnswer, .accident", timeout=240000)
            page.wait_for_timeout(2000)
            rec["questions"] = page.evaluate("qa.live ? qa.live.questions : []")
            rec["opening"] = stream_texts()
            shot("qa_open")
            for vw, vh in [(390, 844)]:
                page.set_viewport_size({"width": vw, "height": vh})
                page.wait_for_timeout(700)
                rec["layout"][f"open_{vw}"] = page.evaluate(TF.LAYOUT_JS)
                shot(f"qa_open_{vw}")
            page.set_viewport_size({"width": 1280, "height": 800})
            q0 = rec["questions"][0]["question"] if rec["questions"] else ""
            a = pick(q0)
            act("answer", a["partial"])
            act("answer", a["addon"])
            if page.is_visible("#liveHint"):
                act("hint")
            act("stuck")
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(700)
            rec["layout"]["after_stuck_390"] = page.evaluate(TF.LAYOUT_JS)
            shot("qa_after_stuck_390")
            page.set_viewport_size({"width": 1280, "height": 800})
            if page.locator("#stream .msg.q").last.locator(".qa-choice-chip").count():
                page.locator("#stream .msg.q").last.locator(".qa-choice-chip").first.click()
                page.wait_for_timeout(300)
                page.click("#liveSend")
                page.wait_for_function("() => qa.live && !qa.live.busy", timeout=180000)
                page.wait_for_timeout(1200)
                rec["turns"].append({"action": "choice", "new": stream_texts()[-4:], "shot": shot("qa_choice")})
            act("answer", a["good"])
            # 두 번째 질문 하나 더 — 좋은 답 한 번
            if rec["questions"] and len(rec["questions"]) > 1 and page.evaluate("qa.live.qi") == 1:
                a2 = pick(rec["questions"][1]["question"])
                act("answer", a2["good"])
            page.click("#liveFinish")
            page.wait_for_timeout(1500)
            rec["finish_stream"] = stream_texts()[-3:] if page.query_selector("#stream") else []
            if page.is_visible("#liveSeeResult"):
                page.click("#liveSeeResult")
                page.wait_for_timeout(1500)
            rec["result_text"] = page.inner_text("#app")[:3000]
            shot("qa_result")
            page.evaluate("location.hash = '#/report'")
            page.wait_for_timeout(5000)
            rec["report_text"] = page.inner_text("#app")[:12000]
            page.screenshot(path=str(out / "report_full.png"), full_page=True)
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"[:500]
            print("  ✕", rec["error"])
            try:
                shot("error")
            except Exception:
                pass
        finally:
            (out / "turns.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
            b.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8799")
    ap.add_argument("--file", type=Path, default=ROOT / "ppt/_held_ir_banchan/ir_banchan.pptx")
    ap.add_argument("--rec-sec", type=int, default=40)
    ap.add_argument("--track", default="5")
    ap.add_argument("--pipe-timeout", type=int, default=600)
    args = ap.parse_args()
    t = time.time()
    out = run(args)
    print(f"끝 {time.time() - t:.0f}s → {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
