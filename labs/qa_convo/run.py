"""
#/qa 대화 내용 감사 실험실 — 질문 코칭 화면 **안에서 오가는 말**을 사람처럼 눌러 보고 턴마다 남긴다.

왜 — labs/test_qa 는 #/qa 에 닿는지까지만 본다. 정작 중요한 것은 그 안에서 코치가 무엇을 되묻고,
무엇을 칭찬하고, 언제 놓아 주는가다. 이 실험실은 실 API 브리지에서 진짜 화면을 띄우고, 질문마다
정해 둔 발표자 유형(페르소나)대로 답칸에 치고 버튼을 누른 뒤, 새로 붙은 말풍선 전문 · 판정 요청/응답 ·
사진 · 지연을 턴 단위로 적는다. 실 LLM 과금이 난다(판정 1회 = LLM 1콜 안팎).

두 단계로 돈다. 질문을 보기 전에는 답을 쓸 수 없어서다.

    # 1) 준비 — #/test/qa 로 덱을 태워 질문까지 만들고, 질문 목록과 브라우저 세션(sessionStorage)을 얼린다
    .venv/bin/python labs/qa_convo/run.py prepare --deck 수면발표 --mode deck --track 10
    # 2) 답안 — labs/qa_convo/answers/<덱>_t<트랙>.json 에 질문별 답(good·partial·addon·wrong·off·short·long·trap_agree)을 쓴다
    # 3) 대화 — 얼린 세션을 되살려 #/qa 에서 페르소나대로 누른다. --rot 을 바꾸면 질문마다 다른 페르소나가 걸린다
    .venv/bin/python labs/qa_convo/run.py play --deck 수면발표 --mode deck --track 10 --rot 0
    .venv/bin/python labs/qa_convo/run.py play --deck 수면발표 --track 10 --persona P3 --only 2   # 한 질문·한 페르소나만
    # 4) 요약 — 모든 play 결과를 모아 표·자동 태그를 뽑는다 · 질문별 줄인 대화록
    .venv/bin/python labs/qa_convo/run.py summarize
    .venv/bin/python labs/qa_convo/run.py digest > /tmp/digest.md

결과: labs/qa_convo/out/<stamp>_<덱>_<mode>_t<트랙>/prepared.json · storage.json
      labs/qa_convo/out/<prep>/play_<stamp>_r<rot>/turns.json · q<N>_<P>.md · *.png
libasound 가 없는 서버면 LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu (labs/qa_call/README.md).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
ANS = HERE / "answers"
PIPE_TIMEOUT = 1800
ACT_TIMEOUT = 150_000
MAX_JUDGE = 4            # 한 질문에서 판정을 이 이상 부르지 않는다 — 과금 상한 겸 「안 놓아 주는 루프」 관측선
PERSONAS = ["P1", "P2", "P3", "P4", "P5", "P6", "P8"]   # P7(함정)은 함정 질문에만 건다
PERSONA_NAME = {
    "P1": "좋은 답 한 번", "P2": "절반 → 보완", "P3": "그럴듯한 오답 → 정정", "P4": "모르겠어요 → 선택 → 또 모르겠어요",
    "P5": "힌트 1→2→3 → 답", "P6": "딴 얘기 → 정답", "P7": "함정 전제에 동의 → 정정", "P8": "한 단어 → 장황한 정답",
}


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


# ── 자동 태그 (최종 판단은 사람이 한다 — 여기서는 후보만 뽑는다) ──────────────────────
HONORIFIC_RE = re.compile(r"하신|계신|계시|주실|주시|하셨|셨어요|셨나요|시겠|께서|여쭈|드릴게요|십시오")
HAPSYO_RE = re.compile(r"(?:습니다|입니다|합니다|됩니다|습니까|십시오)(?=[.\s?!]|$)")
INTERNAL_RE = re.compile(r"「S\d+」|(?<![A-Za-z0-9])S\d{1,2}(?![0-9])|\b[a-z]+_[a-z_]+\b|\bnode[_-]?\d+|\bq\d+\b|\bslide_no\b|질문이 묻는 것:|어긋난 곳:")
#: 화면 머리말(qa_live.js TIER_META) — LLM 말투와 따로 센다
UI_META_RE = re.compile(r"(이어서 묻습니다|좁혀서 다시 묻습니다)")
ENGLISH_RE = re.compile(r"Chart Type|Figure Type|The (?:bar |line )?chart|[A-Za-z]{3,}(?:\s+[A-Za-z]{2,}){3,}")
TRUNC_RE = re.compile(r"(?:…|\.\.\.)\s*$")
PRAISE_RE = re.compile(r"정확해요|정확합니다|맞아요|맞습니다|잘 짚|훌륭|좋은 답|잘 설명|제대로 설명|좋아요")


def strip_quotes(text: str) -> str:
    return re.sub(r"«[^»]*»|“[^”]*”|\"[^\"]*\"|「[^」]*」|'[^']*'", "", text or "")


def auto_tags(turn: dict) -> list[str]:
    """한 턴의 새 말풍선·판정 응답에서 규칙으로 잡히는 후보 문제."""
    tags: list[str] = []
    texts = [b["text"] for b in turn.get("bubbles", []) if b.get("who") != "me"]
    joined = "\n".join(texts)
    if UI_META_RE.search(joined):
        tags.append("tone:ui_meta_hapsyo " + UI_META_RE.search(joined).group(0))
        joined = UI_META_RE.sub("", joined)
    if HONORIFIC_RE.search(joined):
        tags.append("tone:honorific " + ",".join(sorted(set(HONORIFIC_RE.findall(joined)))))
    hs = HAPSYO_RE.findall(strip_quotes(joined))
    if hs:
        tags.append("tone:hapsyo " + ",".join(sorted(set(hs))))
    ii = [m for m in INTERNAL_RE.findall(joined) if m not in ("slide_no",)]
    if ii:
        tags.append("tone:internal_id " + ",".join(sorted(set(ii)))[:80])
    if ENGLISH_RE.search(joined):
        tags.append("tone:english " + ENGLISH_RE.search(joined).group(0)[:50])
    for t in texts:
        for line in t.splitlines():
            if TRUNC_RE.search(line.strip()):
                tags.append("tone:truncated " + line.strip()[-40:])
                break
    v = turn.get("judge") or {}
    if v:
        react = v.get("react") or ""
        score = v.get("score") or 0
        done = v.get("mastered") if v.get("mastered") is not None else v.get("passed")
        missing = [m for m in (v.get("missing_points") or []) if m]
        if not v.get("coach_stage") and (v.get("verdict") in ("wrong", "unknown") or score < 70) and PRAISE_RE.search(react):
            tags.append(f"consistency:praise_on_fail score={score} «{PRAISE_RE.search(react).group(0)}»")
        if "반쯤" in react and not missing:
            tags.append("consistency:half_without_missing")
        if done and v.get("followup"):
            tags.append("consistency:pass_but_followup")
        if done and missing:
            tags.append("consistency:pass_with_missing " + " / ".join(missing)[:80])
        if not done and v.get("passed"):
            tags.append(f"consistency:passed_not_mastered score={score}")
        # 09-30: 가드 사유는 결손이 아니라 guard_reason 으로 온다 — 가드가 건 답은 결손이 비어도 까닭이 있다
        if not done and not missing and not v.get("coach_stage") and not v.get("guard_reason"):
            tags.append("relevance:fail_without_missing")
        if len(react) > 160:
            tags.append(f"ux:long_react {len(react)}자")
        for c in v.get("choices") or []:
            if len(str(c)) <= 2:
                tags.append(f"relevance:bound_choice «{c}»")
    if turn.get("latency_sec", 0) > 25:
        tags.append(f"latency:slow {turn['latency_sec']}s")
    return tags


# ── 브라우저 ──────────────────────────────────────────────────────────────────────
def launch(p):
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
    return b, ctx


def find_deck_key(page, deck: str) -> str | None:
    cards = page.evaluate("Array.from(document.querySelectorAll('[data-deck]')).map(c => c.dataset.deck)")
    return next((c for c in cards if nfc(c) == nfc(deck)), None)


def prepare(args) -> Path:
    """#/test/qa → 덱 → (자료만|녹음까지) → 시간 고르기 → 질문이 뜰 때까지. 질문과 세션을 얼린다."""
    from playwright.sync_api import sync_playwright

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUT / f"{stamp}_{nfc(args.deck)}_{args.mode}_t{args.track}"
    out.mkdir(parents=True, exist_ok=True)
    log: dict = {"deck": args.deck, "mode": args.mode, "track": args.track, "requests": [], "console": []}
    with sync_playwright() as p:
        b, ctx = launch(p)
        page = ctx.new_page()
        page.on("pageerror", lambda e: log["console"].append(f"pageerror: {e}"[:300]))
        page.on("response", lambda r: log["requests"].append(f"{r.status} {r.url.split(args.base)[-1][:90]}") if "/api/" in r.url else None)
        try:
            page.goto(f"{args.base}/index.html#/", wait_until="networkidle")
            page.evaluate("sessionStorage.clear()")
            page.goto(f"{args.base}/test/QA", wait_until="networkidle")
            page.wait_for_selector("[data-run]", timeout=20000)
            key = find_deck_key(page, args.deck)
            if not key:
                print("  ✕ 덱이 없어요:", args.deck)
                return out
            t0 = time.time()
            page.click(f'[data-deck="{key}"] [data-run="{args.mode}"]')
            gated = False
            while time.time() - t0 < PIPE_TIMEOUT:
                page.wait_for_timeout(3000)
                h = page.evaluate("location.hash")
                if page.is_visible("#qaGateStart") and not gated:
                    page.click(f'.qa-mode[data-mode="{args.track}"]')
                    page.wait_for_timeout(400)
                    page.screenshot(path=str(out / "gate.png"))
                    page.click("#qaGateStart")
                    gated = True
                    print(f"    {time.time() - t0:5.0f}s 시간 {args.track}분 고르고 시작", flush=True)
                if page.evaluate("typeof qaLiveActive === 'function' && qaLiveActive()") and page.is_visible("#liveAnswer"):
                    break
                if h.startswith("#/qa") and not gated and page.evaluate("!!(qa && qa.started)") is False:
                    continue
                # 리빌이 떠 있고 재료가 모였으면 CTA 를 눌러 준다 (labs/test_qa 와 같다)
                if page.evaluate("!!document.getElementById('f11RevealWrap') && typeof pipelineQaReady==='function' && pipelineQaReady()"):
                    try:
                        page.frame_locator("#f11RevealWrap iframe").locator("button:visible, a.btn:visible").first.click(timeout=3000)
                    except Exception:
                        pass
                if page.evaluate("nf.gate === 'fail' || nf.pipelinePhase === 'error'"):
                    page.screenshot(path=str(out / "failed.png"))
                    print("  ✕ 파이프라인 실패")
                    return out
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out / "qa_first.png"), full_page=True)
            qs = page.evaluate("qa.live.questions")
            mode = page.evaluate("qa.mode")
            storage = page.evaluate("Object.fromEntries(Object.keys(sessionStorage).map(k => [k, sessionStorage.getItem(k)]))")
            (out / "storage.json").write_text(json.dumps(storage, ensure_ascii=False), encoding="utf-8")
            (out / "prepared.json").write_text(json.dumps({
                "deck": args.deck, "mode": args.mode, "track": args.track, "qa_mode": mode,
                "session_id": page.evaluate("qa.live.sessionId"), "questions": qs,
                "sec": round(time.time() - t0, 1)}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  질문 {len(qs)}개 (qa.mode={mode}) {time.time() - t0:.0f}s")
            for i, q in enumerate(qs, 1):
                print(f"    Q{i}{' [함정]' if q.get('trap') else ''} {q.get('label')}: {q.get('question')[:110]}")
        finally:
            (out / "prepare_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
            b.close()
    return out


def latest_prep(deck: str, mode: str, track: str) -> Path | None:
    cands = sorted(d for d in OUT.glob(f"*_{nfc(deck)}_{mode}_t{track}") if (d / "prepared.json").exists())
    return cands[-1] if cands else None


class Driver:
    """얼린 세션으로 #/qa 를 열고, 한 동작마다 새 말풍선·판정 왕복·사진을 적는다."""

    def __init__(self, page, out: Path, base: str):
        self.page, self.out, self.base = page, out, base
        self.net: list[dict] = []
        self.t_req: dict = {}
        self.shots = 0
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
            row["req"] = json.loads(r.request.post_data or "{}")
            for k in ("history",):
                row["req"].pop(k, None)
            row["res"] = r.json()
        except Exception as e:  # noqa: BLE001
            row["err"] = str(e)[:200]
        self.net.append(row)

    def n_turns(self) -> int:
        return self.page.evaluate("qa.turns.length")

    def state(self) -> dict:
        return self.page.evaluate("""() => { const L = qa.live || {}; return {qi: L.qi, busy: !!L.busy, retell: !!L.retell,
            awaitEnd: !!L.awaitEnd, turn: L.turn, hintLevel: L.hintLevel, nhints: (typeof liveHints==='function') ? liveHints().length : 0,
            buttons: Array.from(document.querySelectorAll('.qa-live-input button')).filter(b => b.offsetParent).map(b => b.id + '|' + b.textContent.trim())}; }""")

    def wait_idle(self) -> None:
        self.page.wait_for_function("() => qa.live && !qa.live.busy && !document.getElementById('coachThinking')", timeout=ACT_TIMEOUT)
        self.page.wait_for_timeout(700)

    def act(self, qn: int, pid: str, kind: str, text: str = "", chip: int | None = None) -> dict:
        page = self.page
        before_turns, before_net = self.n_turns(), len(self.net)
        before_children = page.evaluate("document.getElementById('stream').children.length")
        t0 = time.time()
        if kind in ("answer", "retell"):
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
        elif kind == "skip_retell":
            page.click("#liveSkipRetell")
        self.wait_idle()
        new = page.evaluate("(n) => qa.turns.slice(n)", before_turns)
        texts = page.evaluate("(n) => Array.from(document.getElementById('stream').children).slice(n).map(e => e.innerText)", before_children)
        bubbles = []
        for i, t in enumerate(new):
            bubbles.append({"who": t.get("who"), "kind": t.get("kind"), "meta": t.get("meta") or t.get("coach") or "",
                            "text": texts[i] if i < len(texts) else re.sub("<[^>]+>", "", str(t.get("text") or ""))})
        calls = self.net[before_net:]
        judge = calls[-1]["res"] if calls and isinstance(calls[-1].get("res"), dict) else None
        self.shots += 1
        shot = f"q{qn}_{pid}_{self.shots:02d}_{kind}.png"
        page.screenshot(path=str(self.out / shot))
        turn = {"q": qn, "persona": pid, "action": kind, "input": text, "bubbles": bubbles,
                "judge": judge, "judge_req": ({k: calls[-1]["req"].get(k) for k in ("answer", "give_up", "prior_answers", "hints_shown")}
                                              if calls and calls[-1].get("req") else None),
                "calls": [{"status": c["status"], "sec": c["sec"]} for c in calls],
                "latency_sec": round(time.time() - t0, 1), "judge_sec": calls[-1]["sec"] if calls else None,
                "state": self.state(), "shot": shot}
        turn["auto_tags"] = auto_tags(turn)
        return turn


def pick_chip(page, q: dict) -> int:
    """「모르겠어요」 선택지 중 자료(완성 문장)와 낱말이 더 겹치는 쪽을 고른다. 맞았는지는 사람이 본다."""
    chips = page.locator("#stream .msg.q").last.locator(".qa-choice-chip").all_inner_texts()
    ref = nfc((q.get("answer_gist") or "") + " " + " ".join(q.get("answer_gist_parts") or []))
    best, idx = -1, 0
    for i, c in enumerate(chips):
        toks = [t for t in re.findall(r"[가-힣A-Za-z0-9.%]+", c) if len(t) >= 2]
        score = sum(1 for t in toks if t in ref) + (2 if c.strip() in ref else 0)
        if score > best:
            best, idx = score, i
    return idx


def play_question(d: Driver, qn: int, q: dict, pid: str, a: dict) -> list[dict]:
    """페르소나 하나로 질문 하나를 끝까지 민다. 닫히지 않으면 출구(답 보기·해설)로 나간다."""
    turns: list[dict] = []
    start_qi = d.state()["qi"]
    judged = [0]

    def closed() -> bool:
        s = d.state()
        return s["qi"] != start_qi or s["awaitEnd"]

    def do(kind: str, text: str = "", chip: int | None = None) -> dict:
        t = d.act(qn, pid, kind, text, chip)
        judged[0] += len(t["calls"])
        turns.append(t)
        v = t["judge"] or {}
        print(f"      [{pid}] {kind:6s} {text[:40]!r:44s} → {v.get('verdict', '-')}/{v.get('score', '-')} "
              f"stage={v.get('coach_stage') or v.get('probe_tier') or '-'} {t['judge_sec'] or ''}s "
              f"{'CLOSED' if closed() else ''} {'RETELL' if d.state()['retell'] else ''}", flush=True)
        return t

    good, addon = a.get("good", ""), a.get("addon") or a.get("good", "")
    if pid == "P1":
        do("answer", good)
        if not closed():
            do("answer", addon)
    elif pid == "P2":
        do("answer", a.get("partial") or good)
        if not closed():
            do("answer", addon)
        if not closed() and judged[0] < MAX_JUDGE:
            do("answer", good)
    elif pid == "P3":
        do("answer", a.get("wrong") or good)
        if not closed():
            do("answer", good)
        if not closed() and judged[0] < MAX_JUDGE:
            do("answer", addon)
    elif pid == "P4":
        t = do("stuck")
        if not closed() and not d.state()["retell"]:
            chips = (t["judge"] or {}).get("choices") or []
            if chips:
                do("choice", chip=pick_chip(d.page, q))
            else:
                do("answer", a.get("short") or good)
        if not closed() and not d.state()["retell"]:
            do("stuck")
        if not closed() and not d.state()["retell"] and judged[0] < MAX_JUDGE:
            do("answer", good)
    elif pid == "P5":
        for _ in range(3):
            if "liveHint" in " ".join(d.state()["buttons"]):
                do("hint")
        do("answer", good)
        if not closed():
            do("answer", addon)
    elif pid == "P6":
        do("answer", a.get("off") or "잘 모르겠지만 발표 준비는 열심히 했어요.")
        if not closed():
            do("answer", good)
        if not closed() and judged[0] < MAX_JUDGE:
            do("answer", addon)
    elif pid == "P7":
        do("answer", a.get("trap_agree") or "네, 질문에서 말한 대로예요.")
        if not closed():
            do("answer", good)
        if not closed() and judged[0] < MAX_JUDGE:
            do("answer", addon)
    elif pid == "P8":
        do("answer", a.get("short") or "네")
        if not closed():
            do("answer", a.get("long") or good)
        if not closed() and judged[0] < MAX_JUDGE:
            do("answer", addon)
    # 출구 — 닫히지 않았으면 사람이 할 법한 순서로 빠져나간다
    guard = 0
    while not closed() and guard < 4:
        guard += 1
        s = d.state()
        btns = " ".join(s["buttons"])
        if s["retell"]:
            do("retell", good)
        elif "liveReveal" in btns:
            do("reveal")
        elif "liveStuck" in btns:
            do("stuck")
        else:
            break
    return turns


def md_transcript(q: dict, qn: int, pid: str, turns: list[dict]) -> str:
    lines = [f"# Q{qn} · {PERSONA_NAME.get(pid, pid)} ({pid})", "",
             f"- 질문: {q.get('question')}", f"- 라벨: {q.get('label')} · 함정: {bool(q.get('trap'))} · 장: {q.get('slide_nos')}",
             f"- answer_gist: {q.get('answer_gist')}", f"- answer_gist_parts: {q.get('answer_gist_parts')} · evidence: {q.get('evidence_slide_no')}장 «{q.get('evidence_quote')}»", ""]
    for t in turns:
        v = t["judge"] or {}
        lines.append(f"## {t['action']}" + (f" — 「{t['input']}」" if t["input"] else ""))
        if v:
            lines.append(f"- 판정: {v.get('verdict')} · {v.get('score')}점 · passed={v.get('passed')} mastered={v.get('mastered')} "
                         f"· stage={v.get('coach_stage') or ''} tier={v.get('probe_tier') or ''} · {t['judge_sec']}s")
            if v.get("missing_points"):
                lines.append(f"- missing_points: {v.get('missing_points')}")
            if v.get("choices"):
                lines.append(f"- choices: {v.get('choices')}")
        for bub in t["bubbles"]:
            if bub["who"] == "me":
                continue
            body = bub["text"].replace("\n", " ⏎ ")
            lines.append(f"  - **{bub['kind']}** {body}")
        if t["auto_tags"]:
            lines.append(f"- 자동 태그: {t['auto_tags']}")
        lines.append(f"- 사진: {t['shot']}")
        lines.append("")
    return "\n".join(lines)


def assign(qs: list[dict], rot: int, force: str | None) -> list[str]:
    out = []
    for i, q in enumerate(qs):
        if force:
            out.append(force)
        elif q.get("trap") and rot % 2 == 0:
            out.append("P7")
        else:
            out.append(PERSONAS[(i + rot * 3) % len(PERSONAS)])
    return out


def play(args) -> Path | None:
    from playwright.sync_api import sync_playwright

    prep = Path(args.prep) if args.prep else latest_prep(args.deck, args.mode, args.track)
    if not prep:
        print("  ✕ 얼린 세션이 없어요 — prepare 부터")
        return None
    meta = json.loads((prep / "prepared.json").read_text(encoding="utf-8"))
    storage = json.loads((prep / "storage.json").read_text(encoding="utf-8"))
    qs = meta["questions"]
    afile = Path(args.answers) if args.answers else ANS / f"{nfc(args.deck)}_t{args.track}.json"
    answers = json.loads(afile.read_text(encoding="utf-8")) if afile.exists() else {}
    plan = assign(qs, args.rot, args.persona)
    only = {int(x) for x in args.only.split(",")} if args.only else None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = prep / f"play_{stamp}_r{args.rot}{'_' + args.persona if args.persona else ''}"
    out.mkdir(parents=True, exist_ok=True)
    print(f"  세션 {prep.name} · 질문 {len(qs)}개 · 배정 {plan} · 답안 {afile.name if answers else '없음'}")
    record = {"prep": prep.name, "deck": meta["deck"], "mode": meta["mode"], "track": meta["track"], "rot": args.rot,
              "plan": plan, "questions": qs, "turns": [], "console": []}

    def save() -> None:
        (out / "turns.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    with sync_playwright() as p:
        b, ctx = launch(p)
        # 얼린 sessionStorage 를 앱이 뜨기 전에 한 번만 심는다 (이후 탐색에서는 앱이 쓴 값이 이긴다)
        ctx.add_init_script(f"""(() => {{ try {{ if (sessionStorage.getItem('__qa_convo_seeded')) return;
            const s = {json.dumps(storage, ensure_ascii=False)}; for (const k in s) sessionStorage.setItem(k, s[k]);
            sessionStorage.setItem('__qa_convo_seeded', '1'); }} catch (e) {{}} }})();""")
        page = ctx.new_page()
        page.on("pageerror", lambda e: record["console"].append(f"pageerror: {e}"[:300]))
        page.on("console", lambda m: record["console"].append(f"{m.type}: {m.text}"[:300]) if m.type == "error" else None)
        d = Driver(page, out, args.base)
        try:
            page.goto(f"{args.base}/index.html#/qa", wait_until="networkidle")
            page.wait_for_selector("#liveAnswer", timeout=60000)
            page.wait_for_timeout(1200)
            page.screenshot(path=str(out / "00_entry.png"))
            first_q = page.evaluate("qa.turns.filter(t => t.kind==='question'||t.kind==='claim').map(t => t.text)")
            record["opening"] = first_q
            for i, q in enumerate(qs):
                qn = i + 1
                s = d.state()
                if s["qi"] != i:
                    print(f"  ! 화면 질문 위치 {s['qi']} ≠ {i}")
                a = answers.get(str(qn)) or answers.get(q.get("id") or "") or {}
                pid = plan[i]
                if only and qn not in only or not a:
                    # 이 질문은 대화하지 않는다 — 과금 없이 넘긴다 (답 보기 → 건너뛰기는 판정을 안 부른다)
                    if not a:
                        print(f"    Q{qn} 답안 없음 — 건너뛰어요")
                    page.evaluate("""() => { const L = qa.live; const q = L.questions[L.qi];
                        closeLiveQuestion({id: q.id, label: q.label, question: q.question, answer: '(lab skip)', verdict: 'skipped',
                          score: 0, passed: false, mastered: false, summary: ''}); advanceLiveStream(); }""")
                    page.wait_for_timeout(500)
                    continue
                print(f"    Q{qn} {pid} {PERSONA_NAME[pid]} — {q.get('question')[:70]}")
                turns = play_question(d, qn, q, pid, a)
                record["turns"].extend(turns)
                (out / f"q{qn}_{pid}.md").write_text(md_transcript(q, qn, pid, turns), encoding="utf-8")
                save()
            page.wait_for_timeout(800)
            page.screenshot(path=str(out / "99_end.png"), full_page=False)
            if page.is_visible("#liveSeeResult"):
                page.click("#liveSeeResult")
                page.wait_for_timeout(1500)
                record["result_text"] = page.inner_text("#app")[:3000]
                page.screenshot(path=str(out / "99_result.png"), full_page=True)
                # 상세 리포트(#/report) — Q&A 결과를 정직하게 옮기는지 본다 (2026-09-30 held-out 감사)
                try:
                    page.click('a[href="#/report"]')
                    page.wait_for_timeout(4000)
                    # 접힌 「질문 코칭 내역」과 그 안의 질문별 줄을 모두 편다
                    page.evaluate("() => document.querySelectorAll('details.qa-log-fold, details.qa-log-item').forEach(d => d.open = true)")
                    page.wait_for_timeout(500)
                    record["report_qa_log"] = page.evaluate("() => { const f = document.querySelector('.qa-log-fold'); return f ? f.innerText : null; }")
                    record["report_text"] = page.inner_text("#app")[:12000]
                    page.screenshot(path=str(out / "99_report.png"), full_page=True)
                    tabs = page.locator("[data-tab], .rep-tab, .tab").all()
                    record["report_tabs"] = [t.inner_text()[:40] for t in tabs][:12]
                except Exception as e:  # noqa: BLE001
                    record["report_error"] = str(e)[:200]
        except Exception as e:  # noqa: BLE001
            record["error"] = f"{type(e).__name__}: {e}"[:500]
            print("  ✕", record["error"])
            try:
                page.screenshot(path=str(out / "error.png"))
            except Exception:
                pass
        finally:
            save()
            b.close()
    n_calls = sum(len(t["calls"]) for t in record["turns"])
    print(f"  판정 호출 {n_calls}회 → {out.relative_to(ROOT)}")
    return out


def summarize(args) -> None:
    rows, tags, lat = [], {}, []
    for f in sorted(OUT.glob("*/play_*/turns.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        by_q: dict = {}
        for t in rec["turns"]:
            by_q.setdefault((t["q"], t["persona"]), []).append(t)
            for tag in auto_tags(t):
                tags.setdefault(tag.split(" ")[0], []).append(f"{rec['deck']} t{rec['track']} Q{t['q']} {t['persona']} {t['action']}: {tag}")
            if t.get("judge_sec"):
                lat.append(t["judge_sec"])
        for (qn, pid), ts in by_q.items():
            path = " → ".join(f"{t['action']}:{(t['judge'] or {}).get('verdict', '-')}/{(t['judge'] or {}).get('score', '-')}" for t in ts)
            closed_by = "retell" if any(t["action"] == "retell" for t in ts) else ("reveal" if any(t["action"] == "reveal" for t in ts) else "judge")
            rows.append(f"| {rec['deck']} | t{rec['track']} {rec['mode']} | Q{qn} | {pid} | {sum(len(t['calls']) for t in ts)} | {path} | {closed_by} |")
    print("| 덱 | 트랙 | 질문 | 페르소나 | 판정수 | 경로 | 닫힘 |\n|---|---|---|---|---|---|---|")
    print("\n".join(rows))
    print("\n## 자동 태그")
    for k, v in sorted(tags.items(), key=lambda kv: -len(kv[1])):
        print(f"### {k} ({len(v)})")
        for x in v[:40]:
            print("-", x)
    if lat:
        lat.sort()
        print(f"\n판정 지연 n={len(lat)} 중앙 {lat[len(lat)//2]}s p90 {lat[int(len(lat)*0.9)]}s 최대 {lat[-1]}s")


def digest(args) -> None:
    """모든 play 결과를 질문별로 줄인 대화록(마크다운)으로 뽑는다 — 보고서 부록용."""
    def cut(s: str, n: int = 150) -> str:
        s = re.sub(r"\s+", " ", s or "").strip()
        return s if len(s) <= n else s[: n - 1] + "…"

    by_q: dict = {}
    for f in sorted(OUT.glob("*/play_*/turns.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        for t in rec["turns"]:
            key = (rec["deck"], rec["mode"], rec["track"], t["q"])
            by_q.setdefault(key, {"q": rec["questions"][t["q"] - 1], "runs": {}})
            by_q[key]["runs"].setdefault((f.parent.name, t["persona"]), []).append(t)
    out = []
    for (deck, mode, track, qn), item in sorted(by_q.items()):
        q = item["q"]
        out.append(f"#### {deck} · {mode} · t{track} · Q{qn}{' [함정]' if q.get('trap') else ''} — {q.get('label')}")
        out.append(f"> 질문: {cut(q.get('question'), 200)}  ")
        out.append(f"> 완성 문장(gist): {cut(q.get('answer_gist'), 200)}")
        for (run, pid), ts in item["runs"].items():
            out.append(f"- **{pid}** ({run.split('_')[-1]})")
            for t in ts:
                v = t["judge"] or {}
                said = f"「{cut(t['input'], 70)}」" if t["input"] else ""
                if not v:
                    extra = " / ".join(cut(b["text"], 90) for b in t["bubbles"] if b["who"] != "me" and b["kind"] in ("hint", "gist"))
                    out.append(f"  - {t['action']} {said} → {extra}")
                    continue
                head = f"{v.get('coach_stage') or v.get('verdict')}/{v.get('score')}{' ✓닫힘' if v.get('mastered') else ''}"
                line = f"  - {t['action']} {said} → **{head}** react「{cut(v.get('react'), 110)}」"
                if v.get("missing_points"):
                    line += f" · 빠짐「{cut(' | '.join(v['missing_points']), 100)}」"
                if v.get("followup"):
                    line += f" · 되물음「{cut(v.get('followup'), 100)}」"
                if v.get("choices"):
                    line += f" · 선택지 {v.get('choices')}"
                out.append(line)
        out.append("")
    print("\n".join(out))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("prepare", "play", "summarize", "digest"))
    ap.add_argument("--base", default="http://127.0.0.1:8799")
    ap.add_argument("--deck", default="수면발표")
    ap.add_argument("--mode", choices=("deck", "audio"), default="deck")
    ap.add_argument("--track", default="10", choices=("1", "5", "10"))
    ap.add_argument("--rot", type=int, default=0, help="페르소나 회전 — 0 과 1 을 돌리면 질문마다 다른 페르소나 둘이 걸린다")
    ap.add_argument("--persona", choices=sorted(PERSONA_NAME), help="모든 질문에 이 페르소나만")
    ap.add_argument("--only", help="이 질문 번호만 (예: 1,3)")
    ap.add_argument("--prep", help="얼린 세션 폴더 (없으면 덱·모드·트랙의 최신)")
    ap.add_argument("--answers", help="답안 JSON (기본 answers/<덱>_t<트랙>.json)")
    args = ap.parse_args()
    os.environ.setdefault("LD_LIBRARY_PATH", "/tmp/pwlibs/usr/lib/x86_64-linux-gnu")
    t = time.time()
    if args.cmd == "prepare":
        out = prepare(args)
        print(f"끝 {time.time() - t:.0f}s → {out.relative_to(ROOT)}")
    elif args.cmd == "play":
        play(args)
        print(f"끝 {time.time() - t:.0f}s")
    elif args.cmd == "digest":
        digest(args)
    else:
        summarize(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
