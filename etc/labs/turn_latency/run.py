#!/usr/bin/env python3
"""
말 끝 → 다음 말 첫 글자 실험실 (2026-10-17 tune) — 화상판(/booth/call)에 가짜 실시간 받아쓰기로 답을 **말하고**, 브라우저가 찍은
턴 시각(js/qa_turn.js → window.__qaTurns)을 모은다. 판정은 실 브리지 · 실 API(기본) 또는 가짜(--fake-judge, 자름 실험용).

가짜 받아쓰기는 진짜 A.X 의 사건 순서 그대로다(stt_trace.py 로 잰 값): 말소리 시작(bos) → 말 → 말소리 끝 뒤 --eos-lag 초에 eos →
--text-lag 초 뒤 문장 확정(text). 답은 질문의 모범답(또는 --say)을 문장으로 나눠 문장마다 글자 수 ÷ --cps 초 동안 말하고, 문장 사이에
--gap 초 쉰다(진짜 발표 녹음의 문장 사이 쉼 p50 0.75초 — sim.py). 사람 말이 실제로 끝난 때(마지막 문장 소리 끝)를 페이지 시계로 남겨서
「진짜 말 끝 → 다음 말」 도 낸다.

    LD_LIBRARY_PATH=~/.local/lib/pwlibs .venv/bin/python etc/labs/turn_latency/run.py --base http://127.0.0.1:8824 \\
        --query "" --tag base --turns 6          # 지금 기본값
        --query "qa_turn=fast" --tag fast        # 권고안
        --fake-judge --gap 2.5 --tag cut          # 자름만 (판정 과금 없음)

결과: /data/models/_runs/wt-qa-tune/turn_latency/<stamp>_<tag>/report.json (턴마다 요약 + 원시 시각) · 첫 화면 사진
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
ROOT = HERE.parents[2]
OUT = Path("/data/models/_runs/wt-qa-tune/turn_latency")


def _booth():
    spec = importlib.util.spec_from_file_location("booth_qa_run", ROOT / "etc/labs/booth_qa/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _booth()

FAKE_STT_JS = """
(() => {
  const Real = window.WebSocket;
  const live = new Set();
  const LAG = { eos: %(eos)s, text: %(text)s };
  window.__fakeLog = [];
  class FakeLive {
    constructor(url) {
      this.url = url; this.readyState = 0; this.binaryType = 'blob';
      live.add(this);
      setTimeout(() => { if (this.readyState) return; this.readyState = 1; if (this.onopen) this.onopen({}); this._emit({ type: 'ready' }); }, 30);
    }
    send(data) {
      if (typeof data !== 'string') return;
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
  }
  const Wrapped = function (url, protocols) { return String(url).includes('/api/v1/stt/live') ? new FakeLive(url) : new Real(url, protocols); };
  Object.assign(Wrapped, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3, prototype: Real.prototype });
  window.WebSocket = Wrapped;
  const emit = (m) => live.forEach((s) => s._emit(m));
  // segments: [{text, ms, gap}] — 문장마다 말소리 시작 → ms 동안 말 → (진짜 끝) → eos 늦음 → 문장 확정 → gap 쉼
  window.__fakeSpeak = (segments) => {
    let at = 0;
    const log = { start: performance.now(), segs: [] };
    window.__fakeLog.push(log);
    segments.forEach((sg, i) => {
      const s0 = at, s1 = at + sg.ms;
      setTimeout(() => { log.segs[i] = { on: performance.now(), n: live.size }; emit({ type: 'speech', on: true }); }, s0);
      setTimeout(() => { log.segs[i].end = performance.now(); }, s1);
      setTimeout(() => { emit({ type: 'speech', on: false }); }, s1 + LAG.eos * 1000);
      setTimeout(() => { emit({ type: 'text', text: sg.text }); log.segs[i].text = performance.now(); }, s1 + (LAG.eos + LAG.text) * 1000);
      at = s1 + (LAG.eos + LAG.text) * 1000 + (sg.gap || 0) * 1000;
    });
    log.total = at;
    return segments.length;
  };
  window.__fakeListening = () => live.size;
})();
"""

STATE_JS = """() => ({ qi: qa.live ? qa.live.qi : -1, n: qa.live ? qa.live.questions.length : 0, busy: !!(qa.live && qa.live.busy),
  end: !!(qa.live && qa.live.awaitEnd), turn: qa.live ? (qa.live.turn || 0) : 0, listening: window.__fakeListening ? window.__fakeListening() : 0,
  sendAt: (typeof bc !== 'undefined' && bc.sendAt) ? 1 : 0, turns: (window.__qaTurns || []).length,
  ask: ((document.querySelector('#stream .msg.is-now .msg-q') || document.querySelector('#stream .msg.ai:last-of-type .msg-bubble') || {}).textContent || '').trim().slice(0, 160),
  cur: (window.QaTurn && QaTurn.current()) ? QaTurn.current().key : '' })"""


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.?!요다])\s+", (text or "").strip()) if p.strip()]
    return parts or [text]


def plan_answer(q: dict, attempt: int, args) -> list[dict]:
    """질문 하나에 낼 말 — 첫 답은 모범답 앞 문장 + 흐린 말(꼬리질문을 받게), 둘째부터 모범답 전체."""
    gist = (q.get("answer_gist") or "").strip() or "자료가 말한 핵심 근거 때문이에요. 그래서 결론이 그렇게 나와요."
    if args.say:
        sents = sentences(args.say)
    elif attempt == 0 and args.partial_first:
        sents = [sentences(gist)[0], "그 밖에는 상황마다 좀 다를 것 같아요."]
    else:
        sents = sentences(gist)
    segs = []
    for i, s in enumerate(sents):
        segs.append({"text": s, "ms": int(max(600, len(s) / args.cps * 1000)), "gap": args.gap if i < len(sents) - 1 else 0})
    return segs


def install_fake_judge(page, state: dict) -> None:
    def judge(route):
        req = json.loads(route.request.post_data or "{}")
        if req.get("speculative"):
            state["spec"] += 1
            return route.fulfill(status=202, content_type="application/json", body='{"speculative": true, "started": true}')
        state["judge"] += 1
        q = req.get("question") or {}
        time.sleep(state["delay"])
        body = B._fake_judge_body(q, "good")
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))
    page.route("**/qa/judge", judge)


def run(args) -> Path:
    from playwright.sync_api import sync_playwright

    out = OUT / (datetime.now().strftime("%Y%m%dT%H%M%S") + (f"_{args.tag}" if args.tag else ""))
    out.mkdir(parents=True, exist_ok=True)
    cam = B.face_cam(B.OUT / "facecam.mjpeg")
    R: dict = {"args": vars(args), "turns": [], "spoken": [], "console": [], "stages": {}}
    state = {"spec": 0, "judge": 0, "delay": args.fake_delay}
    t_all = time.time()
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                    f"--use-file-for-fake-video-capture={cam}", "--autoplay-policy=no-user-gesture-required"])
        ctx = b.new_context(viewport={"width": 1280, "height": 800}, permissions=["camera", "microphone"], locale="ko-KR")
        ctx.add_init_script(FAKE_STT_JS % {"eos": args.eos_lag, "text": args.text_lag})
        page = ctx.new_page()
        page.on("console", lambda m: R["console"].append(f"{m.type}: {m.text}"[:400]) if (m.type == "error" or "[qa-turn]" in m.text) else None)
        page.on("pageerror", lambda e: R["console"].append(f"pageerror: {e}"[:300]))
        if args.fake_judge:
            install_fake_judge(page, state)
        q = f"?{args.query}" if args.query else ""
        try:
            t0 = time.time()
            # 해시 주소로 바로 — 옛 브리지는 /booth/call 을 돌려보낼 때 쿼리를 버렸다(10-17 tune 에서 qa_* 만 실어 가게 고침)
            page.goto(f"{args.base}/index.html{q}#/booth/call", wait_until="load")
            page.wait_for_selector("#bqStage", timeout=30000)
            # 화면 상태를 보며 나아간다 — 시작 → 고르기(역할 · 발표) → 훑어보기(질문 준비). 누른 것이 안 먹으면 다시
            scr = lambda: page.evaluate("(document.getElementById('bqStage')||{dataset:{}}).dataset.screen || ''")  # noqa: E731
            for _ in range(40):
                s0 = scr()
                if s0 == "prep" or s0 == "qa":
                    break
                try:
                    if s0 == "pick":
                        page.wait_for_timeout(1500)
                        page.click(f'#bqStage .bq-role[data-role="{args.role}"]', timeout=5000)
                        page.click(f'#bqStage .bq-deck[data-deck="{args.deck}"]', timeout=5000)
                    elif page.evaluate("!!document.getElementById('bqStart')"):
                        page.click("#bqStart", timeout=5000)
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(1500)
            while time.time() - t0 < args.prep_timeout:
                if page.evaluate("!!document.getElementById('bqGo') && !document.getElementById('bqGo').disabled"):
                    break
                page.wait_for_timeout(500)
            R["stages"]["prep_sec"] = round(time.time() - t0, 1)
            R["turn_cfg"] = page.evaluate("window.QaTurn ? QaTurn.cfg() : null")
            questions = page.evaluate("qa.live.questions.map(q => ({id: q.id, label: q.label, answer_gist: q.answer_gist || '', trap: !!q.trap}))")
            R["questions"] = questions
            page.click("#bqGo")
            page.wait_for_selector("#bqStage[data-screen='qa']", timeout=20000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out / "01_qa.png"))
            attempts: dict[int, int] = {}
            guard = 0
            while len(R["spoken"]) < args.turns and guard < args.turns * 4:
                guard += 1
                # 듣기 시작할 때까지 (자동 마이크) — 판정 중 · 끝 카드면 기다린다
                ok = False
                for _ in range(200):
                    st = page.evaluate(STATE_JS)
                    if st["end"] or st["qi"] >= st["n"]:
                        break
                    if not st["busy"] and st["listening"] > 0 and not st["sendAt"]:
                        ok = True
                        break
                    page.wait_for_timeout(300)
                if not ok:
                    break
                page.wait_for_timeout(int(args.think * 1000))   # 질문을 읽고 생각하는 틈
                st = page.evaluate(STATE_JS)
                qi = st["qi"]
                qd = questions[qi] if qi < len(questions) else {}
                segs = plan_answer(qd, attempts.get(qi, 0), args)
                attempts[qi] = attempts.get(qi, 0) + 1
                n_before = st["turns"]
                page.evaluate("(s) => window.__fakeSpeak(s)", segs)
                total = sum(s["ms"] for s in segs) / 1000 + (args.eos_lag + args.text_lag) * len(segs) + sum(s["gap"] for s in segs)
                # 판정 · 다음 말까지
                t_wait = time.time()
                while time.time() - t_wait < total + 60:
                    st = page.evaluate(STATE_JS)
                    if st["turns"] > n_before:
                        break
                    page.wait_for_timeout(250)
                page.wait_for_timeout(600)
                log = page.evaluate("window.__fakeLog[window.__fakeLog.length - 1]")
                turns = page.evaluate("(window.__qaTurns || []).map(t => ({key: t.key, t: t.t, sum: t.sum, reason: t.reason, specHit: t.specHit, eotKind: t.eotKind}))")
                new = [t for t in turns[n_before:] if t["t"].get("send") is not None]
                rec = {"qi": qi + 1, "attempt": attempts[qi], "segs": segs, "fake": log, "turn": new[-1] if new else None}
                if rec["turn"] and log:
                    tt = rec["turn"]["t"]
                    true_end = log["segs"][-1].get("end") if log["segs"] and log["segs"][-1] else None
                    rec["true_end_to_next"] = round(tt["next"] - true_end) if tt.get("next") is not None and true_end else None
                    rec["true_end_to_ack"] = round(tt["ack"] - true_end) if tt.get("ack") is not None and true_end else None
                    rec["cut"] = bool(true_end is None or (tt.get("send") is not None and tt["send"] < true_end))
                R["spoken"].append(rec)
                s = (rec["turn"] or {}).get("sum") or {}
                print(f"  Q{qi + 1}#{attempts[qi]} 말끝→보내기 {s.get('eot_to_send')} · →첫반응 {s.get('eot_to_ack')} · →다음말 {s.get('eot_to_next')} "
                      f"(진짜 끝→다음말 {rec.get('true_end_to_next')}) 미리판정 {s.get('spec_hit')} 자름 {rec.get('cut')}", flush=True)
            page.screenshot(path=str(out / "02_end.png"))
        except Exception as e:  # noqa: BLE001
            R["error"] = f"{type(e).__name__}: {e}"[:600]
            print("  실패:", R["error"])
            try:
                page.screenshot(path=str(out / "error.png"))
            except Exception:  # noqa: BLE001
                pass
        finally:
            R["fake_judge"] = state
            R["total_sec"] = round(time.time() - t_all, 1)
            (out / "report.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
            b.close()
    summarize(out)
    return out


def summarize(out: Path) -> dict:
    R = json.loads((out / "report.json").read_text())
    rows = [r for r in R["spoken"] if r.get("turn")]

    def pct(xs, p):
        xs = sorted(x for x in xs if x is not None)
        return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None

    keys = ["eot_to_final", "eot_to_quiet", "eot_to_spec", "eot_to_send", "eot_to_ack", "eot_to_judged", "eot_to_next", "judge_wait"]
    S = {"n": len(rows), "cut": sum(1 for r in rows if r.get("cut")), "spec_hit": sum(1 for r in rows if (r["turn"].get("sum") or {}).get("spec_hit") is not None)}
    for k in keys:
        S[k] = {"p50": pct([r["turn"]["sum"].get(k) for r in rows], .5), "p90": pct([r["turn"]["sum"].get(k) for r in rows], .9)}
    S["true_end_to_next"] = {"p50": pct([r.get("true_end_to_next") for r in rows], .5), "p90": pct([r.get("true_end_to_next") for r in rows], .9)}
    S["true_end_to_ack"] = {"p50": pct([r.get("true_end_to_ack") for r in rows], .5), "p90": pct([r.get("true_end_to_ack") for r in rows], .9)}
    (out / "summary.json").write_text(json.dumps(S, ensure_ascii=False, indent=1))
    print(json.dumps(S, ensure_ascii=False))
    return S


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8824")
    ap.add_argument("--query", default="", help="주소 쿼리 (qa_turn=fast · qa_eot=ending&qa_send_ms=1200 …)")
    ap.add_argument("--deck", default="수익률격차")
    ap.add_argument("--role", default="심사위원")
    ap.add_argument("--turns", type=int, default=6)
    ap.add_argument("--cps", type=float, default=7.0, help="말 빠르기 (글자/초)")
    ap.add_argument("--gap", type=float, default=0.75, help="문장 사이 쉼 (초) — 진짜 발표 녹음 p50")
    ap.add_argument("--eos-lag", type=float, default=0.71, help="진짜 말 끝 → eos (A.X 실측 p50)")
    ap.add_argument("--text-lag", type=float, default=0.05)
    ap.add_argument("--think", type=float, default=1.5, help="질문이 뜬 뒤 말 시작까지")
    ap.add_argument("--say", default="")
    ap.add_argument("--partial-first", action="store_true", default=True)
    ap.add_argument("--fake-judge", action="store_true")
    ap.add_argument("--fake-delay", type=float, default=0.3)
    ap.add_argument("--prep-timeout", type=float, default=240)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    out = run(args)
    print("결과:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
