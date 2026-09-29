"""
화면 구동 — 실제 앱(index.html)을 헤드리스 크로미움으로 띄워 #/test/QA → 덱 → 시간 → #/qa 까지 가고, 한 동작마다
새 말풍선 전문 · 판정 요청/응답 JSON · 지연을 남긴다. labs/qa_convo/run.py 의 선택자·흐름을 옮겨 왔다 (그쪽이 09-29~30 에
실 브리지로 검증한 것). 프론트까지 덮는 것이 목적이라 판정은 반드시 화면의 버튼으로 보낸다.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from . import common as C

PIPE_TIMEOUT = 1500
ACT_TIMEOUT = 150_000


def ensure_pw_env() -> None:
    """헤드리스 크로미움이 libasound 를 찾게 — sync_playwright() **전에** 불러야 드라이버가 물려받는다."""
    cur = os.environ.get("LD_LIBRARY_PATH", "")
    if Path(C.PW_LIBS).is_dir() and C.PW_LIBS not in cur.split(":"):
        os.environ["LD_LIBRARY_PATH"] = f"{C.PW_LIBS}:{cur}" if cur else C.PW_LIBS


ensure_pw_env()


def launch(p):
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
    return b, ctx


def find_deck_key(page, deck: str) -> str | None:
    cards = page.evaluate("Array.from(document.querySelectorAll('[data-deck]')).map(c => c.dataset.deck)")
    return next((c for c in cards if C.nfc(c) == C.nfc(deck)), None)


def prepare(base: str, deck: str, mode: str, track: str, out: Path) -> dict:
    """#/test/QA 로 덱을 태워 질문이 뜰 때까지. 질문 · 자료 · 그래프 · 세션 저장소를 얼려 돌려준다."""
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    log: dict = {"deck": deck, "mode": mode, "track": track, "requests": [], "console": []}
    result: dict = {"deck": deck, "mode": mode, "track": track, "ok": False}
    t0 = time.time()
    with sync_playwright() as p:
        b, ctx = launch(p)
        page = ctx.new_page()
        page.on("pageerror", lambda e: log["console"].append(f"pageerror: {e}"[:300]))
        page.on("response", lambda r: log["requests"].append(f"{r.status} {r.url.split(base)[-1][:90]}") if "/api/" in r.url else None)
        try:
            page.goto(f"{base}/index.html#/", wait_until="networkidle")
            page.evaluate("sessionStorage.clear()")
            page.goto(f"{base}/test/QA", wait_until="networkidle")
            page.wait_for_selector("[data-run]", timeout=20000)
            key = find_deck_key(page, deck)
            if not key:
                result["error"] = f"#/test/QA 에 덱이 없어요: {deck}"
                return result
            page.click(f'[data-deck="{key}"] [data-run="{mode}"]')
            gated = False
            while time.time() - t0 < PIPE_TIMEOUT:
                page.wait_for_timeout(3000)
                if page.is_visible("#qaGateStart") and not gated:
                    page.click(f'.qa-mode[data-mode="{track}"]')
                    page.wait_for_timeout(400)
                    page.click("#qaGateStart")
                    gated = True
                if page.evaluate("typeof qaLiveActive === 'function' && qaLiveActive()") and page.is_visible("#liveAnswer"):
                    break
                if page.evaluate("!!document.getElementById('f11RevealWrap') && typeof pipelineQaReady==='function' && pipelineQaReady()"):
                    try:
                        page.frame_locator("#f11RevealWrap iframe").locator("button:visible, a.btn:visible").first.click(timeout=3000)
                    except Exception:  # noqa: BLE001
                        pass
                if page.evaluate("nf.gate === 'fail' || nf.pipelinePhase === 'error'"):
                    page.screenshot(path=str(out / "failed.png"))
                    result["error"] = "파이프라인 실패 (nf.gate/pipelinePhase)"
                    return result
            else:
                result["error"] = f"{PIPE_TIMEOUT}초 안에 질문이 안 떴어요"
                page.screenshot(path=str(out / "timeout.png"))
                return result
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out / "qa_first.png"))
            result.update(
                ok=True, sec=round(time.time() - t0, 1),
                questions=page.evaluate("qa.live.questions"), qa_mode=page.evaluate("qa.mode"),
                session_id=page.evaluate("qa.live.sessionId"),
                slide_doc=page.evaluate("typeof nfSlideDoc !== 'undefined' ? nfSlideDoc : null"),
                graph=page.evaluate("(nf && nf.pipelineOut && nf.pipelineOut.graph) || null"),
                context=page.evaluate("({situation: nf.occ || '', audience: nf.ctx || '', duration_min: nf.min})"),
                storage=page.evaluate("Object.fromEntries(Object.keys(sessionStorage).map(k => [k, sessionStorage.getItem(k)]))"),
            )
        except Exception as e:  # noqa: BLE001
            result["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            try:
                page.screenshot(path=str(out / "error.png"))
            except Exception:  # noqa: BLE001
                pass
        finally:
            C.write_json(out / "prepare_log.json", log)
            b.close()
    return result


class Driver:
    """얼린 세션으로 연 #/qa — 한 동작마다 새 말풍선·판정 왕복을 적는다 (labs/qa_convo Driver 와 같은 틀)."""

    def __init__(self, page, out: Path):
        self.page, self.out = page, out
        self.net: list[dict] = []
        self.t_req: dict = {}
        page.on("request", self._on_req)
        page.on("response", self._on_resp)

    def _on_req(self, r):
        if "/api/" in r.url:
            self.t_req[r] = time.time()

    def _on_resp(self, r):
        if "/qa/judge" not in r.url:
            return
        row = {"status": r.status, "sec": round(time.time() - self.t_req.get(r.request, time.time()), 2)}
        try:
            req = json.loads(r.request.post_data or "{}")
            row["req"] = {k: req.get(k) for k in ("answer", "give_up", "prior_answers", "hints_shown", "question_id")}
            row["res"] = r.json()
        except Exception as e:  # noqa: BLE001
            row["err"] = str(e)[:200]
        self.net.append(row)

    def state(self) -> dict:
        return self.page.evaluate("""() => { const L = qa.live || {}; return {qi: L.qi, busy: !!L.busy, retell: !!L.retell,
            awaitEnd: !!L.awaitEnd, turn: L.turn, hintLevel: L.hintLevel, judgeFailed: !!L.judgeFailed,
            buttons: Array.from(document.querySelectorAll('.qa-live-input button')).filter(b => b.offsetParent).map(b => b.id + '|' + b.textContent.trim())}; }""")

    def wait_idle(self) -> None:
        self.page.wait_for_function("() => qa.live && !qa.live.busy && !document.getElementById('coachThinking')", timeout=ACT_TIMEOUT)
        self.page.wait_for_timeout(600)

    def chips(self) -> list[str]:
        return self.page.locator("#stream .msg.q").last.locator(".qa-choice-chip").all_inner_texts()

    def act(self, kind: str, text: str = "", chip: int | None = None) -> dict:
        page = self.page
        before_turns, before_net = page.evaluate("qa.turns.length"), len(self.net)
        before_children = page.evaluate("document.getElementById('stream').children.length")
        t0 = time.time()
        if kind == "answer" or kind == "retell":
            page.fill("#liveAnswer", text)
            page.click("#liveSend")
        elif kind == "choice":
            chips = page.locator("#stream .msg.q").last.locator(".qa-choice-chip")
            text = chips.nth(chip or 0).inner_text().strip()
            chips.nth(chip or 0).click()
            page.wait_for_timeout(200)
            page.click("#liveSend")
        elif kind == "stuck":
            page.click("#liveStuck")
        elif kind == "hint":
            page.click("#liveHint")
        elif kind == "reveal":
            page.click("#liveReveal")
        self.wait_idle()
        new = page.evaluate("(n) => qa.turns.slice(n).map(t => ({who: t.who, kind: t.kind, meta: t.meta || t.coach || '', "
                            "text: t.text || '', level: t.level || 0, total: t.total || 0, choices: t.choices || [], "
                            "points: t.points || []}))", before_turns)
        texts = page.evaluate("(n) => Array.from(document.getElementById('stream').children).slice(n).map(e => e.innerText)",
                              before_children)
        bubbles = []
        for i, t in enumerate(new):
            body = texts[i] if i < len(texts) else re.sub("<[^>]+>", "", str(t.get("text") or ""))
            bubbles.append({"who": t.get("who"), "kind": t.get("kind"), "meta": t.get("meta") or "", "text": body,
                            "level": t.get("level"), "total": t.get("total")})
        calls = self.net[before_net:]
        judge = calls[-1]["res"] if calls and isinstance(calls[-1].get("res"), dict) else None
        return {"action": kind, "input": text, "bubbles": bubbles, "judge": judge,
                "judge_req": calls[-1].get("req") if calls else None,
                "calls": [{"status": c["status"], "sec": c["sec"]} for c in calls],
                "latency_sec": round(time.time() - t0, 1), "judge_sec": calls[-1]["sec"] if calls else None,
                "state": self.state()}

    def skip_question(self) -> None:
        """이 질문은 대화하지 않는다 — 판정 없이 닫는다 (labs/qa_convo 와 같은 실험실 건너뛰기, LLM 0콜)."""
        self.page.evaluate("""() => { const L = qa.live; const q = L.questions[L.qi];
            closeLiveQuestion({id: q.id, label: q.label, question: q.question, answer: '(verify skip)', verdict: 'skipped',
              score: 0, passed: false, mastered: false, summary: ''}); advanceLiveStream(); }""")
        self.page.wait_for_timeout(500)
