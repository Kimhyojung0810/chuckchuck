"""
페르소나 대화 — 얼린 세션(sessionStorage)으로 #/qa 를 열고, 질문마다 자동 페르소나 하나를 화면의 버튼으로 끝까지 민다.
턴마다 말풍선 · 판정 JSON · 태그를 남기고, 질문마다 페르소나의 기대(personas.py 머리말)를 채점한다.

판정 호출은 질문당 MAX_JUDGE 까지. 페르소나 대본이 끝났는데도 안 닫혔으면 LLM 없이 나간다 — 「답 보고 다시 말해보기」
(해설 없이 답 펼침 → 다시 말하기) 또는 실험실 건너뛰기.
"""

from __future__ import annotations

import time
from pathlib import Path

from . import common as C
from . import personas as P
from . import tags as TG
from .ui import Driver, launch

MAX_JUDGE = 4
ORDER = ("GOOD", "WRONG", "DUNNO", "OFFTOPIC", "ONEWORD", "PARTIAL", "HINTS")
#: 페르소나별 판정 호출 어림 (계획용) — 대본이 짧게 끝나면 덜 쓴다
COST = {"GOOD": 2, "WRONG": 2, "DUNNO": 3, "PARTIAL": 2, "OFFTOPIC": 2, "HINTS": 2, "ONEWORD": 2, "TRAP": 2}


def available(name: str, pack: dict, q: dict) -> bool:
    a = pack.get("answers") or {}
    if name == "TRAP":
        return bool(pack.get("trap") and a.get("trap_agree") and a.get("trap_correct"))
    if pack.get("trap"):
        return name in ("DUNNO", "HINTS") and bool(a.get("good"))
    return {"GOOD": bool(a.get("good")), "WRONG": bool(a.get("wrong")), "DUNNO": True,
            "PARTIAL": bool(a.get("partial")) and a.get("partial") != a.get("good"),
            "OFFTOPIC": bool(a.get("offtopic")), "HINTS": bool(q.get("hints")) and bool(a.get("good")),
            "ONEWORD": bool(a.get("one_word"))}.get(name, False)


def assign(questions: list[dict], packs: list[dict], budget: int, start: int = 0) -> tuple[list[str], int]:
    """
    질문마다 페르소나 하나 (예산이 모자라면 "SKIP"). 함정 질문의 TRAP 을 먼저 담는다 — 5분 트랙에 하나뿐이라 회전에 맡기면 빠진다.
    나머지는 ORDER 를 돌린다. 덱 사이에 이어 돌도록 회전 시작점(start)을 받고 돌려준다.
    """
    names: list[str] = [""] * len(questions)
    cost = 0
    for i, (q, pack) in enumerate(zip(questions, packs)):
        if pack.get("trap") and available("TRAP", pack, q) and cost + COST["TRAP"] <= budget:
            names[i], cost = "TRAP", cost + COST["TRAP"]
    rot = start
    for i, (q, pack) in enumerate(zip(questions, packs)):
        if names[i]:
            continue
        name = next((ORDER[(rot + k) % len(ORDER)] for k in range(len(ORDER))
                     if available(ORDER[(rot + k) % len(ORDER)], pack, q)), "SKIP")
        rot += 1
        if name == "SKIP" or cost + COST.get(name, 0) > budget:
            names[i] = "SKIP"
            continue
        names[i], cost = name, cost + COST[name]
    return names, rot


def _judged(turns: list[dict]) -> list[dict]:
    return [t for t in turns if t.get("judge")]


def score_persona(name: str, turns: list[dict]) -> dict:
    """페르소나 기대 채점 — 지표 conv.* 의 분자·분모."""
    js = _judged(turns)
    first = js[0]["judge"] if js else {}
    out: dict = {"persona": name}
    if not js:
        out["incomplete"] = True          # 예산이 떨어져 한 번도 판정을 못 받았다 — 채점하지 않는다 (실패로 세면 거짓말이다)
        return out
    passed = lambda t: TG.passed(t.get("judge"))  # noqa: E731
    if name == "GOOD":
        out["good_pass"] = any(passed(t) for t in js[:2] if t["step"] in ("good", "good_more"))
    elif name == "PARTIAL":
        hit = next((t for t in js[:2] if passed(t)), None)
        out["partial_complete"] = bool(hit)       # 통과면 된다 — 70~79 에서 한 걸음 더 묻는 것은 설계다 (contracts.qa_mastered)
        out["partial_early_pass"] = bool(js) and passed(js[0])
    elif name == "WRONG":
        out["wrong_rejected"] = bool(js) and not passed(js[0]) and not TG.PRAISE_RE.search(str(first.get("react") or ""))
        out["wrong_recover"] = any(passed(t) for t in js[1:3])
    elif name == "OFFTOPIC":
        # 통과하지 못했고 칭찬도 없으면 막은 것이다 — 같은 덱의 다른 장 줄은 「질문과 다른 이야기」 가 아니라 「조금 멀어요」(초점 가드)로
        # 막히는 게 맞다 (09-30 표준 단계: partial/65 「…에 대한 답으로는 조금 멀어요」 를 실패로 셌다).
        out["offtopic_rejected"] = bool(js) and not passed(js[0]) and not TG.PRAISE_RE.search(str(first.get("react") or ""))
    elif name == "ONEWORD":
        out["one_word_rejected"] = bool(js) and not passed(js[0])
    elif name == "TRAP":
        out["trap_agree_caught"] = bool(js) and not passed(js[0]) and TG.TRAP_AGREED_LEAD in str(first.get("react") or "")
        out["trap_correct_pass"] = any(passed(t) for t in js[1:3])
    elif name == "DUNNO":
        stucks = [t for t in turns if t["action"] == "stuck"]
        j1 = (stucks[0].get("judge") or {}) if stucks else {}
        chips_ok = len(j1.get("choices") or []) >= 2 and not any(x["tag"] == "relevance.choice_invalid" for x in stucks[0]["tags"]) if stucks else False
        second = (stucks[1].get("judge") or {}).get("coach_stage") if len(stucks) >= 2 else ""
        out["dunno_ok"] = bool(chips_ok) and second in ("scaffold", "explain")
        out["dunno_detail"] = {"choices": j1.get("choices"), "second_stage": second}
    elif name == "HINTS":
        opened = sum(1 for t in turns if t["action"] == "hint")
        out["hints_ok"] = opened >= 1 and any(passed(t) for t in js[:2])
        out["hints_opened"] = opened
    return out


class Player:
    def __init__(self, driver: Driver, deck: str, questions: list[dict], deck_doc: dict, budget_check):
        self.d, self.deck, self.questions = driver, deck, questions
        self.lines = [x for _, x in P.T.deck_lines(deck_doc)]
        self.raw = P.T.slide_texts(deck_doc)
        self.deck_text = "\n".join(self.raw.values())
        self.budget_check = budget_check           # () -> bool : 판정 한 번 더 불러도 되나

    def play(self, qn: int, q: dict, name: str, pack: dict) -> tuple[list[dict], dict]:
        d = self.d
        turns: list[dict] = []
        start_qi = d.state()["qi"]
        others = [f"{o.get('question', '')} {o.get('answer_gist', '')}" for o in self.questions if o is not q]
        said: list[str] = []
        state = {"corrected": False, "judge_calls": 0}
        a = pack.get("answers") or {}

        def closed() -> bool:
            s = d.state()
            return s["qi"] != start_qi or s["awaitEnd"]

        def do(kind: str, step: str, text: str = "", chip: int | None = None) -> dict | None:
            if kind in ("answer", "stuck", "choice") and (state["judge_calls"] >= MAX_JUDGE or not self.budget_check()):
                return None
            if step == "trap_correct":
                state["corrected"] = True
            t = d.act(kind, text, chip)
            state["judge_calls"] += len(t["calls"])
            if kind in ("answer", "choice") and t["input"]:
                said.append(t["input"])
            ctx = {"question": q, "step": step, "deck_lines": self.lines, "deck_raw": self.raw, "deck_text": self.deck_text,
                   "cumulative": " ".join(said), "others": others, "corrected": state["corrected"]}
            t.update(deck=self.deck, q=qn, qid=q.get("id", ""), persona=name, step=step, tags=TG.turn_tags(t, ctx))
            turns.append(t)
            v = t.get("judge") or {}
            C.note(f"      [{name}] {step:12s} {text[:34]!r:38s} → {v.get('coach_stage') or v.get('verdict', '-')}/{v.get('score', '-')}"
                   f" {t['judge_sec'] or ''}s {'CLOSED' if closed() else ''} {' '.join(x['tag'] for x in t['tags'])[:80]}")
            return t

        if name == "GOOD":
            do("answer", "good", a["good"])
            if not closed():
                do("answer", "good_more", a.get("good_more") or a["good"])
        elif name == "PARTIAL":
            do("answer", "partial", a["partial"])
            if not closed():
                do("answer", "complete", a.get("complete") or a["good"])
            if not closed():
                do("answer", "good", a["good"])
        elif name == "WRONG":
            do("answer", "wrong", a["wrong"])
            if not closed():
                do("answer", "good", a["good"])
            if not closed():
                do("answer", "good_more", a.get("good_more") or a["good"])
        elif name == "OFFTOPIC":
            do("answer", "offtopic", a["offtopic"])
            if not closed():
                do("answer", "good", a["good"])
        elif name == "ONEWORD":
            do("answer", "one_word", a["one_word"])
            if not closed():
                do("answer", "good", a["good"])
        elif name == "TRAP":
            do("answer", "trap_agree", a["trap_agree"])
            if not closed():
                do("answer", "trap_correct", a["trap_correct"])
            if not closed():
                do("answer", "trap_correct", a["trap_correct"])
        elif name == "DUNNO":
            t = do("stuck", "stuck")
            if t and not closed() and not d.state()["retell"]:
                chips = (t.get("judge") or {}).get("choices") or []
                if chips:
                    idx = P.pick_chip(d.chips() or chips, pack)
                    do("choice", "choice", chip=idx)
            if not closed() and not d.state()["retell"]:
                do("stuck", "stuck")
        elif name == "HINTS":
            for _ in range(3):
                if "liveHint" in " ".join(d.state()["buttons"]):
                    do("hint", "hint")
            do("answer", "good", a["good"])
            if not closed():
                do("answer", "good_more", a.get("good_more") or a["good"])
        self._exit(closed, do, a)
        return turns, score_persona(name, turns)

    def _exit(self, closed, do, a: dict) -> None:
        """닫히지 않았으면 LLM 없이 나간다 — 다시 말하기 · 답 펼치기 → 다시 말하기 · 실험실 건너뛰기."""
        for _ in range(3):
            if closed():
                return
            s = self.d.state()
            btns = " ".join(s["buttons"])
            if s["retell"]:
                do("retell", "retell", a.get("good") or "다시 말해 볼게요.")
            elif "liveReveal" in btns:
                do("reveal", "reveal")
            else:
                break
        if not closed():
            self.d.skip_question()


def play_session(base: str, prep: dict, packs: list[dict], plan: list[str], out: Path, budget_check) -> dict:
    """한 세션(덱·트랙)의 대화 전부. {"turns","personas","results","result_text","console"}."""
    from playwright.sync_api import sync_playwright

    record: dict = {"deck": prep["deck"], "track": prep["track"], "mode": prep["mode"], "plan": plan, "turns": [],
                    "personas": [], "console": []}
    qs = prep["questions"]
    with sync_playwright() as p:
        b, ctx = launch(p)
        storage = prep.get("storage") or {}
        ctx.add_init_script(f"""(() => {{ try {{ if (sessionStorage.getItem('__qa_verify_seeded')) return;
            const s = {C.json_dumps(storage)}; for (const k in s) sessionStorage.setItem(k, s[k]);
            sessionStorage.setItem('__qa_verify_seeded', '1'); }} catch (e) {{}} }})();""")
        page = ctx.new_page()
        page.on("pageerror", lambda e: record["console"].append(f"pageerror: {e}"[:300]))
        page.on("console", lambda m: record["console"].append(f"{m.type}: {m.text}"[:300]) if m.type == "error" else None)
        d = Driver(page, out)
        player = Player(d, prep["deck"], qs, prep.get("slide_doc") or {}, budget_check)
        try:
            page.goto(f"{base}/index.html#/qa", wait_until="networkidle")
            page.wait_for_selector("#liveAnswer", timeout=60000)
            page.wait_for_timeout(1000)
            for i, q in enumerate(qs):
                qn = i + 1
                name = plan[i] if i < len(plan) else "SKIP"
                if name == "SKIP" or not budget_check():
                    d.skip_question()
                    continue
                C.note(f"    Q{qn} {name} — {q.get('question', '')[:70]}")
                t0 = time.time()
                turns, score = player.play(qn, q, name, packs[i])
                record["turns"] += turns
                record["personas"].append(dict(score, q=qn, qid=q.get("id", ""), sec=round(time.time() - t0, 1)))
                page.screenshot(path=str(out / f"q{qn}_{name}.png"))
                C.write_json(out / "turns.json", record)
            page.wait_for_timeout(800)
            record["results"] = page.evaluate("(qa.live && qa.live.results) || []")
            if page.is_visible("#liveSeeResult"):
                record["end_card"] = page.inner_text(".qa-input-label.is-end") if page.is_visible(".qa-input-label.is-end") else ""
                page.click("#liveSeeResult")
                page.wait_for_timeout(1500)
                record["result_text"] = page.inner_text("#app")[:3000]
                page.screenshot(path=str(out / "result.png"), full_page=True)
        except Exception as e:  # noqa: BLE001
            record["error"] = f"{type(e).__name__}: {str(e)[:400]}"
            C.note(f"    ✕ {record['error']}")
            try:
                page.screenshot(path=str(out / "error.png"))
            except Exception:  # noqa: BLE001
                pass
        finally:
            C.write_json(out / "turns.json", record)
            b.close()
    return record
