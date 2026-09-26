"""
#/test/qa 실험실 — ppt/ 폴더의 덱을 골라 질문 코칭까지 **실 API 브리지**로 한 번 태우고 단계별 사진을 남긴다.

왜 — #/test/qa 는 업로드·발표 정보·녹음 화면의 클릭을 코드가 대신 누른다. 그 사이 상태(nf.gate·step·pipelinePhase)가
업로드 흐름과 같은 길을 가는지, 끝에 실제 질문(데모 질문이 아닌)이 뜨는지를 사진과 요청 로그로 확인한다.
실 LLM·STT 과금이 난다. 브리지는 DEMO_DEV_ROUTES=1 로 떠 있어야 한다.

    .venv/bin/python labs/test_qa/run.py                       # 수면발표 · 녹음까지
    .venv/bin/python labs/test_qa/run.py --mode deck           # 자료만으로
    .venv/bin/python labs/test_qa/run.py --deck 수면발표 --base http://127.0.0.1:8799 --pipe-timeout 1800

결과: labs/test_qa/out/<stamp>/*.png + report.json (요청 로그·단계 시간·질문·콘솔 오류)
libasound 가 없는 서버면 LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu (labs/qa_call/README.md).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
DEMO_MARKERS = ["sample-investor", "개인 투자자", "과잉 매매", "손실 회피", "사전 매도 규칙", "샘플 데이터", "샘플 데모 분석"]
PIPE_DONE = ("done", "partial", "error")


def run(args) -> Path:
    from playwright.sync_api import sync_playwright

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUT / f"{stamp}_{args.mode}"
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"base": args.base, "deck": args.deck, "mode": args.mode, "steps": [], "requests": [], "console": [], "checks": {}}
    n = [0]

    def save() -> None:
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def demo_hits(text: str) -> list[str]:
        return [m for m in DEMO_MARKERS if m in text]

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 860}, device_scale_factor=1)
        page = ctx.new_page()

        def shot(name: str) -> None:
            n[0] += 1
            page.screenshot(path=str(out / f"{n[0]:02d}_{name}.png"))

        def mark(name: str, t0: float, extra: dict | None = None) -> None:
            report["steps"].append({"step": name, "sec": round(time.time() - t0, 1), **(extra or {})})
            save()

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
                        for k in ("model", "provider", "mock", "total_slides", "session_id"):
                            if k in body:
                                row[k] = body[k] if k != "session_id" else "…" + str(body[k])[-6:]
                        if "questions" in body:
                            row["n_questions"] = len(body.get("questions") or [])
                            row["q0"] = str((body.get("questions") or [{}])[0].get("question", ""))[:80]
                        if "full_text" in body:
                            row["stt_preview"] = str(body["full_text"])[:60]
                        if "decks" in body:
                            row["decks"] = [d.get("name") for d in body["decks"]]
            except Exception:
                pass
            report["requests"].append(row)
            print(f"    · {row['status']} {row['path'][:60]:60s} {row['sec']:5.1f}s {row.get('model') or row.get('provider') or ''}", flush=True)

        page.on("response", on_resp)

        try:
            # ── 1. 목록 ─────────────────────────────────────────────────
            t0 = time.time()
            page.goto(f"{args.base}/index.html#/", wait_until="networkidle")
            page.evaluate("sessionStorage.clear()")
            page.goto(f"{args.base}/test/QA", wait_until="networkidle")   # 302 → /index.html#/test/qa
            page.wait_for_selector("[data-run], .qa-flag", timeout=20000)
            page.wait_for_timeout(500)
            shot("deck_list")
            cards = page.evaluate("Array.from(document.querySelectorAll('[data-deck]')).map(c => c.dataset.deck)")
            print("  덱:", cards)
            key = next((c for c in cards if unicodedata.normalize("NFC", c) == unicodedata.normalize("NFC", args.deck)), None)
            mark("list", t0, {"hash": page.evaluate("location.hash"), "decks": cards, "picked": key})
            if key is None:
                print("  ✕ 덱을 못 찾았어요:", args.deck)
                return out

            # ── 2. 클릭 → 파싱·선분석·(녹음)·분석 ────────────────────────
            t0 = time.time()
            page.click(f'[data-deck="{key}"] [data-run="{args.mode}"]')
            last = None
            deadline = time.time() + args.pipe_timeout
            while time.time() < deadline:
                page.wait_for_timeout(3000)
                st = page.evaluate("""() => ({hash: location.hash, gate: nf.gate, step: nf.step, phase: nf.pipelinePhase,
                    detail: nf.pipelineDetail, err: nf.pipelineError, sid: nf.sessionId ? '…' + String(nf.sessionId).slice(-6) : null,
                    qaReady: typeof pipelineQaReady === 'function' && pipelineQaReady(),
                    pre: precompute ? {c: !!precompute.state.conceptsReady, g: !!precompute.state.graphReady, f: !!precompute.state.failed} : null,
                    reveal: !!document.getElementById('f11RevealWrap')})""")
                sig = (st["hash"], st["gate"], st["step"], st["phase"], st["reveal"])
                if sig != last:
                    print(f"    {time.time() - t0:5.0f}s hash={st['hash']} gate={st['gate']} step={st['step']} phase={st['phase']} pre={st['pre']} reveal={st['reveal']}", flush=True)
                    shot(f"t{int(time.time() - t0):04d}_{(st['phase'] or st['gate'] or 'start')}")
                    last = sig
                if st["hash"].startswith("#/qa"):
                    break
                if st["gate"] == "fail" or st["phase"] == "error":
                    txt = page.inner_text("#app")
                    shot("failed")
                    mark("run", t0, {**st, "text": txt[:400]})
                    print("  ✕ 실패:", (st["err"] or txt[:200]).replace("\n", " / "))
                    return out
                # 리빌이 떠 있고 질문 재료가 다 모였는데 안 넘어가면 리빌 CTA 를 눌러 준다 (사람이 누르는 버튼)
                if st["reveal"] and st["qaReady"]:
                    page.wait_for_timeout(4000)
                    if page.evaluate("location.hash").startswith("#/qa"):
                        break
                    try:
                        fr = page.frame_locator("#f11RevealWrap iframe")
                        btn = fr.locator("button:visible, a.btn:visible").first
                        if btn.count():
                            btn.click(timeout=3000)
                    except Exception:
                        pass
            mark("run", t0, {"hash": page.evaluate("location.hash"), "phase": page.evaluate("nf.pipelinePhase"),
                             "out_keys": page.evaluate("Object.keys(nf.pipelineOut || {})"),
                             "graph_nodes": page.evaluate("((nf.pipelineOut||{}).graph||{}).nodes ? nf.pipelineOut.graph.nodes.length : 0"),
                             "slides": page.evaluate("(nf.slideTitles||[]).length"), "pdf": page.evaluate("!!uploadedPdf")})
            if not page.evaluate("location.hash").startswith("#/qa"):
                shot("not_at_qa")
                print("  ✕ 시간 안에 #/qa 로 못 갔어요")
                return out

            # ── 3. 질문 코칭 ─────────────────────────────────────────────
            t0 = time.time()
            page.wait_for_timeout(1000)
            shot("qa_entry")
            if page.is_visible("#qaGateStart"):
                page.click("#qaGateStart")
            page.wait_for_timeout(1500)
            shot("qa_building")
            page.wait_for_selector("#liveAnswer, .accident, .qa-notice, #stream", timeout=420000)
            page.wait_for_timeout(1500)
            txt = page.inner_text("#app")
            shot("qa_first_question")
            live = page.evaluate("qaLiveActive()")
            qs = page.evaluate("qa.live ? qa.live.questions.map(q => q.question) : []")
            mark("qa", t0, {"live": live, "n_questions": len(qs), "questions": [q[:140] for q in qs],
                            "demo_hits": demo_hits(txt), "notice": page.evaluate("qa.liveNotice || ''"),
                            "text_head": txt[:300]})
            print(f"  질문 코칭: live={live} 질문 {len(qs)}개 demo_hits={demo_hits(txt)}")
            for i, q in enumerate(qs, 1):
                print(f"    Q{i}. {q[:120]}")
        finally:
            report["console"] = report["console"][:80]
            save()
            b.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8799")
    ap.add_argument("--deck", default="수면발표", help="ppt/ 아래 폴더 이름")
    ap.add_argument("--mode", choices=("audio", "deck"), default="audio", help="audio=녹음까지 · deck=자료만으로")
    ap.add_argument("--pipe-timeout", type=int, default=1800, help="#/qa 에 닿기까지 기다리는 최대 초")
    args = ap.parse_args()
    os.environ.setdefault("LD_LIBRARY_PATH", "/tmp/pwlibs/usr/lib/x86_64-linux-gnu")
    t = time.time()
    out = run(args)
    print(f"끝 {time.time() - t:.0f}s → {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
