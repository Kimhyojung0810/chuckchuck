"""
메인 앱 흐름 실험실 — index.html 을 업로드부터 리포트까지 **실 API 브리지**로 한 번 태우고 단계별 사진을 남긴다.

왜 — 시연 모드(SHOWCASE_DEMO)가 켜져 있던 동안 올린 자료·녹음이 어느 단계에서도 실 API 를 안 타고
더미(sample-investor)로 떨어졌는데, 화면만 봐서는 구분이 안 됐다. 이 실험실은 요청 로그(경로·상태·걸린 시간)와
화면 문구를 같이 남겨 "내 자료로 도는가" 를 사진과 숫자로 확인한다. 실 LLM·STT 과금이 난다.

    .venv/bin/python labs/app_flow/run.py                          # PPTX(집중 알림 발표) 로 끝까지
    .venv/bin/python labs/app_flow/run.py --file labs/qa_call/fixture_slide1.jpg
    .venv/bin/python labs/app_flow/run.py --no-preview             # PPTX 미리보기 PDF 를 막는다 (soffice 없는 서버 흉내 → 자리표시자)
    .venv/bin/python labs/app_flow/run.py --until rehearsal        # 리허설 화면(종료 버튼 가림 검사)까지만
    .venv/bin/python labs/app_flow/run.py --base http://127.0.0.1:8799 --rec-sec 45

가짜 마이크는 fixtures/live/chuckchuck_rehearsal.m4a 앞부분을 wav 로 바꿔 크롬에 물린다
(--use-file-for-fake-audio-capture) — 삐 소리가 아니라 그 자료를 실제로 읽는 목소리라 STT·정합이 의미가 있다.
ffmpeg 가 없으면 삐 소리 가짜 장치로 간다(STT 결과가 비어 분석이 실패로 끝나는 게 정상이다).

결과: labs/app_flow/out/<stamp>/*.png + report.json (요청 로그·단계 시간·화면 검사·콘솔 오류)
libasound 가 없는 서버면 LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu (labs/qa_call/README.md).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
DEFAULT_FILE = ROOT / "fixtures/focus_notification_demo_designed.pptx"
AUDIO_SRC = ROOT / "fixtures/live/chuckchuck_rehearsal.m4a"
ANSWER = "알림을 잠깐 보는 5초가 문제가 아니라, 원래 작업으로 돌아오는 데 드는 재집중 시간이 더 커서 집중이 크게 끊겨요"
UNTIL = ["upload", "rehearsal", "analysis", "qa", "report"]
# 데모 질문 코칭(js/data.js)·쇼케이스 리포트에만 있는 문구 — 실제 세션 화면에 뜨면 더미로 떨어진 것이다
DEMO_MARKERS = ["sample-investor", "개인 투자자", "과잉 매매", "손실 회피", "사전 매도 규칙", "샘플 데이터", "샘플 데모 분석"]
PIPE_DONE = ("done", "partial", "error")


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg") or next((str(p) for p in [Path.home() / ".local/bin/ffmpeg"] if p.exists()), None)


def fake_audio(sec: int) -> Path | None:
    ff = find_ffmpeg()
    if not ff or not AUDIO_SRC.exists():
        return None
    dst = OUT / f"rehearsal_{sec}s.wav"
    if not dst.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        subprocess.run([ff, "-y", "-loglevel", "error", "-t", str(sec), "-i", str(AUDIO_SRC),
                        "-ac", "1", "-ar", "48000", "-sample_fmt", "s16", str(dst)], check=True)
    return dst


def run(args) -> Path:
    from playwright.sync_api import sync_playwright

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S") + ("_nopreview" if args.no_preview else "")
    out = OUT / stamp
    out.mkdir(parents=True, exist_ok=True)
    want = UNTIL[: UNTIL.index(args.until) + 1]
    report: dict = {"base": args.base, "file": str(args.file), "stages": {}, "checks": {}, "requests": [], "console": []}
    audio = fake_audio(args.rec_sec + 20)
    report["fake_audio"] = str(audio) if audio else "beep (ffmpeg 없음)"
    n = {"i": 0}

    def shot(name: str, full: bool = False) -> None:
        n["i"] += 1
        page.screenshot(path=str(out / f"{n['i']:02d}_{name}.png"), full_page=full)

    def mark(name: str, t0: float, extra: dict | None = None) -> None:
        report["stages"][name] = {"sec": round(time.time() - t0, 1), **(extra or {})}
        print(f"  {name:14s} {report['stages'][name]['sec']:6.1f}s  {json.dumps(extra or {}, ensure_ascii=False)[:160]}")

    def save() -> None:
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))

    def demo_hits(text: str) -> list[str]:
        return [m for m in DEMO_MARKERS if m in text]

    def button_clickable(sel: str) -> dict:
        """버튼 중심점을 실제로 누가 받는지 — 다른 층이 덮고 있으면 hit 이 버튼 밖이다."""
        return page.evaluate("""(sel) => {
            const b = document.querySelector(sel);
            if (!b) return { found: false };
            b.scrollIntoView({ block: 'nearest' });
            const r = b.getBoundingClientRect();
            const x = r.left + r.width / 2, y = r.top + r.height / 2;
            const hit = document.elementFromPoint(x, y);
            const desc = (el) => el ? `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : ''}` : null;
            return { found: true, ok: !!hit && (hit === b || b.contains(hit)), hit: desc(hit),
                     rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
                     inViewport: r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth };
        }""", sel)

    with sync_playwright() as p:
        flags = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                 "--autoplay-policy=no-user-gesture-required"]
        if audio:
            flags.append(f"--use-file-for-fake-audio-capture={audio}")
        b = p.chromium.launch(args=flags)
        ctx = b.new_context(viewport={"width": 1280, "height": 860}, device_scale_factor=1,
                            permissions=["camera", "microphone"])
        page = ctx.new_page()
        page.on("console", lambda m: report["console"].append(f"{m.type}: {m.text}"[:400]) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: report["console"].append(f"pageerror: {e}"[:400]))
        t_req: dict = {}
        page.on("request", lambda r: t_req.__setitem__(r, time.time()) if "/api/" in r.url else None)

        def on_resp(r):
            if "/api/" not in r.url:
                return
            row = {"path": r.url.split(args.base)[-1][:120], "status": r.status,
                   "sec": round(time.time() - t_req.get(r.request, time.time()), 1)}
            try:
                if "json" in (r.headers.get("content-type") or ""):
                    body = r.json()
                    if isinstance(body, dict):
                        for k in ("model", "provider", "mock", "total_slides", "preview_pdf", "session_id"):
                            if k in body:
                                row[k] = body[k] if k != "session_id" else "…" + str(body[k])[-6:]
                        if "questions" in body:
                            row["n_questions"] = len(body.get("questions") or [])
                            row["q0"] = str((body.get("questions") or [{}])[0].get("question", ""))[:80]
                        if "verdict" in body:
                            row["verdict"] = body["verdict"]
                        if "full_text" in body:
                            row["stt_preview"] = str(body["full_text"])[:60]
            except Exception:
                pass
            report["requests"].append(row)
            print(f"    · {row['status']} {row['path'][:60]:60s} {row['sec']:5.1f}s {row.get('model') or row.get('provider') or ''}")

        page.on("response", on_resp)
        if args.fail_questions:
            # 질문 생성이 실패하면 실패 화면이 떠야 한다 — 데모 질문(js/data.js)으로 바꿔치기하면 안 된다
            page.route("**/api/v1/questions", lambda route: route.fulfill(status=502, content_type="application/json",
                                                                         body='{"error": "lab: questions forced failure"}'))
        if args.no_preview:
            page.route("**/api/v1/preview-pdf**", lambda route: route.fulfill(status=404, body="no soffice (lab)"))

        try:
            # ── 1. 업로드 ────────────────────────────────────────────────
            t0 = time.time()
            page.goto(f"{args.base}/index.html#/new", wait_until="networkidle")
            page.evaluate("sessionStorage.clear()")
            page.goto(f"{args.base}/index.html#/new/reset", wait_until="networkidle")
            page.wait_for_selector("#file", state="attached")
            shot("upload_empty")
            page.set_input_files("#file", str(args.file))
            page.wait_for_timeout(2500)
            shot("upload_parsing")
            page.wait_for_selector("#next, .gate-fail, .accident", timeout=300000)
            txt = page.inner_text("#app")
            shot("upload_done")
            ok = page.is_visible("#next")
            mark("upload", t0, {"ok": ok, "gate": page.evaluate("nf.gate"), "useSample": page.evaluate("nf.useSample"),
                                "slides": page.evaluate("(nf.slideTitles||[]).length"), "pdf": page.evaluate("!!uploadedPdf"),
                                "demo_hits": demo_hits(txt)})
            if not ok:
                return out

            # ── 2. 발표 정보 → 리허설 화면 ───────────────────────────────
            t0 = time.time()
            page.click("#next")
            page.wait_for_selector("#go")
            page.fill("#ctx", "대학 교양 수업에서 학생 30명 앞에서 발표해요")
            shot("info")
            page.click("#go")   # 선분석(startPrecompute) 시작
            page.wait_for_selector("#recStart")
            page.wait_for_timeout(1500)
            shot("rehearsal_idle")
            report["checks"]["recStart_1280x860"] = button_clickable("#recStart")
            page.click("#recStart")
            page.wait_for_selector("#recEnd", timeout=20000)
            page.wait_for_timeout(1200)
            # 슬라이드 전환 기록을 펼친 채로 잰다 — 이 팝오버가 종료 버튼을 덮던 것이 9/23 제보다
            page.click(".rehearsal-nav-next")
            page.wait_for_timeout(600)
            page.click(".rec-log-fold summary")
            page.wait_for_timeout(300)
            checks = {}
            for vw, vh in [(1280, 860), (1440, 780), (1366, 768), (1024, 768), (390, 844)]:
                page.set_viewport_size({"width": vw, "height": vh})
                page.wait_for_timeout(500)
                checks[f"recEnd_{vw}x{vh}"] = button_clickable("#recEnd")
                checks[f"nextSlide_{vw}x{vh}"] = button_clickable(".rehearsal-nav-next") if page.is_visible(".rehearsal-nav-next") else {"hidden": True}
                shot(f"rehearsal_live_{vw}x{vh}")
            page.set_viewport_size({"width": 1280, "height": 860})
            report["checks"].update(checks)
            bad = {k: v for k, v in checks.items() if k.startswith("recEnd") and not v.get("ok")}
            mark("rehearsal", t0, {"pdf": page.evaluate("!!uploadedPdf"), "recEnd_blocked": list(bad)})
            if "analysis" not in want:
                return out

            # 슬라이드를 넘기며 말한다 (가짜 마이크가 실제 발표 음성을 흘린다)
            n_slides = page.evaluate("rehearsalCount()")
            step = max(3, args.rec_sec // max(1, min(n_slides, 6)))
            waited = 0
            while waited < args.rec_sec:
                page.wait_for_timeout(step * 1000)
                waited += step
                if waited < args.rec_sec:
                    page.click(".rehearsal-nav-next") if page.is_visible(".rehearsal-nav-next") else None
            shot("rehearsal_before_end")
            report["checks"]["precompute_state"] = page.evaluate("precompute ? {conceptsReady: precompute.state?.conceptsReady, graphReady: precompute.state?.graphReady, failed: precompute.state?.failed} : null")

            # ── 3. 리허설 종료 → 분석 리빌 ───────────────────────────────
            t0 = time.time()
            page.click("#recEnd")
            page.wait_for_timeout(4500)   # 커튼콜 3초
            shot("reveal_start")
            if args.early_qa:
                # 분석이 끝나기 전에 #/qa 로 가도 데모 질문이 뜨면 안 된다 — 기다리는 화면이 떠야 한다
                page.evaluate("location.hash = '#/qa'")
                page.wait_for_timeout(800)
                if page.is_visible("#qaGateStart"):
                    page.click("#qaGateStart")
                page.wait_for_timeout(1500)
                txt = page.inner_text("#app")
                shot("qa_early")
                report["checks"]["qa_early"] = {"demo_hits": demo_hits(txt), "text": txt[:300]}
                print("    early #/qa:", txt[:120].replace("\n", " / "))
            last_phase = None
            shots_at = {20, 60, 120}
            deadline = time.time() + args.pipe_timeout
            while time.time() < deadline:
                ph = page.evaluate("nf.pipelinePhase")
                qa_ready = page.evaluate("typeof pipelineQaReady === 'function' && pipelineQaReady()")
                if ph != last_phase:
                    print(f"    phase={ph} qaReady={qa_ready} +{time.time() - t0:.0f}s")
                    last_phase = ph
                el = int(time.time() - t0)
                for s in list(shots_at):
                    if el >= s:
                        shots_at.discard(s)
                        shot(f"reveal_{s}s")
                if ph in PIPE_DONE or (qa_ready and args.until == "analysis"):
                    break
                if qa_ready and ph not in PIPE_DONE and not args.wait_report:
                    break
                page.wait_for_timeout(2000)
            shot("reveal_ready")
            out_keys = page.evaluate("Object.keys(nf.pipelineOut || {})")
            tr = page.evaluate("(nf.pipelineOut && nf.pipelineOut.transcript) ? {provider: nf.pipelineOut.transcript.provider, words: (nf.pipelineOut.transcript.words||[]).length, text: String(nf.pipelineOut.transcript.full_text||'').slice(0,80)} : null")
            mark("analysis", t0, {"phase": page.evaluate("nf.pipelinePhase"), "error": page.evaluate("nf.pipelineError"),
                                  "out": out_keys, "transcript": tr,
                                  "graph_nodes": page.evaluate("((nf.pipelineOut||{}).graph||{}).nodes ? nf.pipelineOut.graph.nodes.length : 0")})
            if "qa" not in want:
                return out

            # ── 4. 질문 코칭 — 리빌 우회 경로(#/qa 직접)로 들어가도 실제 질문이 떠야 한다 ──
            t0 = time.time()
            page.evaluate("location.hash = '#/qa'")
            page.wait_for_timeout(800)
            if page.is_visible("#qaGateStart"):
                shot("qa_gate")
                page.click("#qaGateStart")
            page.wait_for_timeout(1500)
            shot("qa_building")
            page.wait_for_selector("#liveAnswer, .accident, .qa-notice, #stream", timeout=180000)
            page.wait_for_timeout(1200)
            txt = page.inner_text("#app")
            shot("qa_first_question")
            live = page.evaluate("qaLiveActive()")
            qs = page.evaluate("qa.live ? qa.live.questions.map(q => q.question) : []")
            mark("qa", t0, {"live": live, "n_questions": len(qs), "q0": qs[0][:100] if qs else None,
                            "demo_hits": demo_hits(txt), "notice": page.evaluate("qa.liveNotice || ''")})
            if not live:
                shot("qa_not_live")
                return out

            # 타이핑으로 답하기 — 마이크를 켜 둔 채로 쳐서 보내도 보내져야 한다
            t0 = time.time()
            mic_state = None
            if page.is_visible("#liveMic"):
                page.click("#liveMic")
                page.wait_for_timeout(1500)
                mic_state = page.evaluate("document.querySelector('#liveMic') && document.querySelector('#liveMic').innerText")
            ta_disabled = page.evaluate("document.querySelector('#liveAnswer').disabled || document.querySelector('#liveAnswer').readOnly")
            page.click("#liveAnswer")
            page.keyboard.type(ANSWER, delay=5)
            shot("qa_typed_while_mic")
            page.click("#liveSend")
            page.wait_for_timeout(800)
            shot("qa_judging")
            page.wait_for_function("qa.live && !qa.live.busy", timeout=180000)
            page.wait_for_timeout(1500)
            shot("qa_judged")
            last = page.evaluate("qa.live.lastJudgement ? {verdict: qa.live.lastJudgement.verdict, score: qa.live.lastJudgement.score} : null")
            mark("qa_answer", t0, {"mic_state_when_typing": mic_state, "textarea_locked_while_mic": ta_disabled,
                                   "sent": page.evaluate("qa.turns.filter(t => t.who==='me').length"),
                                   "judgement": last, "failed": page.evaluate("!!qa.live.judgeFailed")})
            if "report" not in want:
                return out

            # ── 5. 여기까지 하고 저장 → 결과 → 리포트 ────────────────────
            t0 = time.time()
            if page.is_visible("#liveFinish"):
                page.click("#liveFinish")
                page.wait_for_timeout(1500)
                if page.is_visible("#liveSeeResult"):
                    page.click("#liveSeeResult")
                    page.wait_for_timeout(1500)
            shot("qa_result")
            page.evaluate("location.hash = '#/report'")
            page.wait_for_timeout(4000)
            txt = page.inner_text("#app")
            shot("report_top")
            shot("report_full", full=True)
            mark("report", t0, {"hash": page.evaluate("location.hash"), "demo_hits": demo_hits(txt),
                                "live": page.evaluate("isLiveReportSession()")})
        except Exception as e:  # 사진은 남긴다
            report["error"] = f"{type(e).__name__}: {e}"[:600]
            print("  실패:", report["error"])
            try:
                shot("error")
            except Exception:
                pass
        finally:
            save()
            b.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8799")
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--until", choices=UNTIL, default="report")
    ap.add_argument("--rec-sec", type=int, default=50, help="리허설 녹음 길이(초)")
    ap.add_argument("--pipe-timeout", type=int, default=900, help="분석을 기다리는 최대 초")
    ap.add_argument("--wait-report", action="store_true", help="질문 준비가 끝나도 리포트 축까지 다 기다린다")
    ap.add_argument("--no-preview", action="store_true", help="PPTX 미리보기 PDF 를 막는다 (soffice 없는 서버 흉내)")
    ap.add_argument("--fail-questions", action="store_true", help="/api/v1/questions 를 502 로 막는다 (실패 화면 확인)")
    ap.add_argument("--early-qa", action="store_true", help="분석이 끝나기 전에 #/qa 로 간다 (대기 화면 확인)")
    args = ap.parse_args()
    os.environ.setdefault("LD_LIBRARY_PATH", "/tmp/pwlibs/usr/lib/x86_64-linux-gnu")
    t = time.time()
    out = run(args)
    print(f"끝 {time.time() - t:.0f}s → {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
