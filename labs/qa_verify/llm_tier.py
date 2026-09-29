"""
standard / full 단계 — 대상 코드로 브리지를 띄워(실 LLM) 화면으로 질문을 만들고, 자동 페르소나로 대화하고, 레드팀 공격을 판정한다.

순서 (예산을 먼저 알고 나누려고 질문을 다 만든 뒤에 대화한다)
  A. 덱·트랙마다 #/test/QA → 질문까지 (세션 저장소를 얼린다)            — 브리지 LLM (개념·그래프·주장·1차 심사·질문)
  B. 대상 코드로 페르소나 · 공격 답 만들기 (자식, LLM 없음)
  C. 남은 예산을 대화 55% · 레드팀 45% 로 나눈다
  D. 세션마다 #/qa 를 열어 질문마다 페르소나 하나 (판정은 화면 버튼 → 브리지)
  E. 레드팀 공격 · 같은 답 3번(결정성) · 자료 속 주입 — 자식이 대상 judge_answer 를 직접 (호출은 같은 calls.jsonl 에 센다)
  F. 브리지 변조 — 함정 칸을 지운 질문 본문을 보내도 판정이 같은가 (HTTP)
  G. (full) booth.html 사진 흐름 (대상 labs/qa_call)
"""

from __future__ import annotations

import re
import secrets
import shutil
import time
from pathlib import Path
from urllib.parse import quote

from . import common as C
from . import conversation as CV
from . import redteam as R
from . import scoreboard as S
from . import tags as TG
from . import ui
from .bridge import Bridge
from .target import TUNED, Target, ppt_name

STANDARD_DECKS = ("수익률격차", "_held_health_glucose", "_held_policy_jeonse")
FULL_DECKS = ("수면발표", "수익률격차", "focus_notification", "_held_health_glucose", "_held_ir_banchan",
              "_held_policy_jeonse", "_held_lib_reopen", "_held_hum_novel")
AUDIO_DECK = "_held_health_glucose"
#: 트랙별 함정 질문 수 설계 (contracts.QA_TRACK_TRAPS 와 같은 값 — 잣대라 여기 적어 둔다)
TRACK_TRAPS = {"1": 0, "5": 1, "10": 3}
CONV_SHARE = 0.55


def run(target: Target, run_dir: Path, ns, budget: int) -> tuple[dict[str, dict], dict]:
    full = ns.tier == "full"
    decks = [ppt_name(d) for d in ns.decks.split(",") if d.strip()] or list(FULL_DECKS if full else STANDARD_DECKS)
    tracks = [t.strip() for t in ns.tracks.split(",") if t.strip()] or (["5", "10"] if full else ["5"])
    missing = target.link_decks(decks + ([AUDIO_DECK] if full else []))
    decks = [d for d in decks if d not in missing]
    bridge = Bridge(target, ns.port, run_dir, budget, no_papers=ns.no_papers)
    info = {"decks": decks, "tracks": tracks, "llm_calls": 0}
    metrics: dict[str, dict] = {}
    C.note(f"── {ns.tier}: 덱 {decks} · 트랙 {tracks} · 예산 {budget}" + (f" · 없는 덱 {missing}" if missing else ""))
    try:
        bridge.start()
        preps = _prepare_all(bridge, decks, tracks, run_dir, full)
        packs = _personas(target, preps, run_dir)
        remaining = bridge.remaining()
        conv_budget = remaining if ns.no_redteam else int(remaining * CONV_SHARE)
        C.note(f"── 질문까지 LLM {bridge.used()}콜 · 남은 {remaining} → 대화 {conv_budget} · 레드팀 {remaining - conv_budget}")
        records = _conversations(bridge, preps, packs, run_dir, conv_budget)
        red_rows, red_extra = ([], {}) if ns.no_redteam else _redteam(target, bridge, preps, packs, run_dir)
        booth = _booth(target, bridge, run_dir) if full else None
        metrics.update(_pipeline_metrics(preps, bridge))
        metrics.update(_conv_metrics(records))
        if not ns.no_redteam:
            metrics.update(_redteam_metrics(red_rows, red_extra))
        if booth is not None:
            metrics.update(booth)
        _digest(records, run_dir)
    finally:
        info["llm_calls"] = bridge.used()
        if not ns.keep_bridge:
            bridge.stop()
        target.unlink_decks()
    metrics["conv.llm_calls"] = S.metric(info["llm_calls"], budget)
    return metrics, info


# ---------------------------------------------------------------------------
# A · B — 질문 만들기 · 페르소나
# ---------------------------------------------------------------------------

def _prepare_all(bridge: Bridge, decks: list[str], tracks: list[str], run_dir: Path, full: bool) -> list[dict]:
    jobs = [(d, "deck", t) for d in decks for t in tracks]
    if full:
        jobs.append((AUDIO_DECK, "audio", "5"))
    preps = []
    for deck, mode, track in jobs:
        if bridge.remaining() < 4:
            C.note(f"   예산이 모자라 {deck} {mode} t{track} 는 건너뛰어요")
            preps.append({"deck": deck, "mode": mode, "track": track, "ok": False, "error": "예산"})
            continue
        t0, c0 = time.time(), bridge.used()
        C.note(f"   {deck} · {mode} · t{track} 질문 만들기…")
        prep = ui.prepare(bridge.base, deck, mode, track, run_dir / f"{C.nfc(deck)}_{mode}_t{track}")
        if prep.get("ok") and not prep.get("slide_doc") and prep.get("session_id"):
            got = bridge.get_json(f"/api/v1/cached-slidedoc?session_id={prep['session_id']}")
            prep["slide_doc"] = (got or {}).get("slide_doc") or got
        if prep.get("ok"):
            prep["questions"] = server_copies(bridge, prep.get("session_id") or "flat", prep.get("questions") or [])
        prep.update(llm_calls=bridge.used() - c0, wall=round(time.time() - t0, 1), tuned=deck in TUNED)
        C.note(f"     → {'질문 ' + str(len(prep.get('questions') or [])) + '개' if prep.get('ok') else '실패: ' + str(prep.get('error'))}"
               f" · {prep['wall']}s · LLM {prep['llm_calls']}")
        C.write_json(run_dir / f"{C.nfc(deck)}_{mode}_t{track}" / "prepared.json",
                     {k: v for k, v in prep.items() if k != "storage"})
        preps.append(prep)
    return preps


#: 화면 사본에서 브리지가 뺀 함정 칸 (demo/bridge.py `TRAP_WITHHELD`) — 잣대(페르소나·누설 태그)는 서버 사본의 값을 쓴다.
WITHHELD = ("trap_premise", "answer_gist", "answer_gist_parts")


def server_copies(bridge: Bridge, sid: str, questions: list[dict]) -> list[dict]:
    """
    화면 사본의 질문(함정은 전제·골자가 빈 gist_withheld 사본 — 09-30 WP-J2)에 **서버 사본의 함정 칸**을 채운다 — 하네스는 잣대라
    정답지를 봐도 된다(개발 경로 `/api/v1/dev/questions`, 브리지를 DEMO_DEV_ROUTES=1 로 띄울 때만 열린다). 판정은 어차피 서버 사본으로
    한다. 문장이 같은 판을 고르고, 못 찾으면 화면 사본 그대로 둔다(함정 페르소나가 빠질 뿐 대화는 돈다).
    """
    out = []
    for q in questions:
        if not (isinstance(q, dict) and q.get("gist_withheld")):
            out.append(q)
            continue
        got = bridge.get_json(f"/api/v1/dev/questions?session_id={quote(sid)}&id={quote(str(q.get('id', '')))}") or {}
        cands = [c for c in got.get("questions") or [] if isinstance(c, dict)]
        same = next((c for c in cands if str(c.get("question") or "").strip() == str(q.get("question") or "").strip()), None)
        src = same or (cands[0] if cands else None)
        out.append({**q, **{k: src.get(k) for k in WITHHELD}} if src else q)
    return out


def _personas(target: Target, preps: list[dict], run_dir: Path) -> dict[int, dict]:
    out = {}
    for i, prep in enumerate(preps):
        if not prep.get("ok"):
            continue
        got = target.probe("personas", {"questions": prep["questions"], "slide_doc": prep.get("slide_doc") or {},
                                        "graph": prep.get("graph")}, timeout=300)
        if got.get("ok"):
            out[i] = got
            C.write_json(run_dir / f"{C.nfc(prep['deck'])}_{prep['mode']}_t{prep['track']}" / "personas.json", got)
        else:
            prep["persona_error"] = got.get("error")
    return out


# ---------------------------------------------------------------------------
# D — 대화
# ---------------------------------------------------------------------------

def _conversations(bridge: Bridge, preps: list[dict], packs: dict[int, dict], run_dir: Path, conv_budget: int) -> list[dict]:
    limit = bridge.used() + conv_budget
    records, rot = [], 0
    sessions = [i for i, p in enumerate(preps) if p.get("ok") and i in packs]
    for n, i in enumerate(sessions):
        prep = preps[i]
        share = max(0, (limit - bridge.used()) // max(1, len(sessions) - n))
        plan, rot = CV.assign(prep["questions"], packs[i]["personas"], share, rot)
        C.note(f"   대화 {prep['deck']} {prep['mode']} t{prep['track']} · 배정 {plan} · 몫 {share}")
        rec = CV.play_session(bridge.base, prep, packs[i]["personas"], plan,
                              run_dir / f"{C.nfc(prep['deck'])}_{prep['mode']}_t{prep['track']}",
                              budget_check=lambda: bridge.used() + 1 <= limit)
        # 사다리 검사(`_ladder_checks`)가 질문(골자·탐침 줄)과 자료 원문을 본다 — 기록에는 싣지 않고 메모리에서만 잇는다
        records.append(dict(rec, questions=prep["questions"], deck_raw=P_texts(prep.get("slide_doc") or {})))
    return records


def _conv_metrics(records: list[dict]) -> dict[str, dict]:
    turns = [t for r in records for t in r["turns"]]
    scores = [s for r in records for s in r["personas"]]
    out: dict[str, dict] = {}
    for key in ("good_pass", "partial_complete", "wrong_rejected", "wrong_recover", "offtopic_rejected", "one_word_rejected",
                "trap_agree_caught", "trap_correct_pass", "dunno_ok", "hints_ok"):
        rows = [s for s in scores if key in s]
        bad = [f"{r['deck']} Q{s['q']} {s['persona']}" for r in records for s in r["personas"] if key in s and not s[key]]
        out[f"conv.{key}"] = S.ratio(sum(bool(s[key]) for s in rows), len(rows), bad + _persona_examples(records, key))
    counts = TG.tag_counts(turns)
    for tag, n in sorted(counts.items()):
        out[f"tags.{tag}"] = S.ratio(n, len(turns), TG.examples(turns, tag))
    judged = [t for t in turns if t.get("judge") and not (t["judge"] or {}).get("coach_stage")]
    fb = [t for t in judged if str(t["judge"].get("react") or "") in TG.FALLBACK_REACTS]
    out["conv.react_fallback"] = S.ratio(len(fb), len(judged), [f"{t['deck']} Q{t['q']} {t['step']}: «{t['judge'].get('react')}»" for t in fb][:3])
    lat = [t["judge_sec"] for t in turns if t.get("judge_sec")]
    out["conv.latency_p50"] = S.metric(TG.percentile(lat, 0.5), len(lat))
    out["conv.latency_p90"] = S.metric(TG.percentile(lat, 0.9), len(lat))
    out.update(_ladder_checks(records))
    forced, mismatch = _result_checks(records)
    out["conv.forced_close_counted"] = S.metric(len(forced), None, forced)
    out["conv.result_count_mismatch"] = S.metric(len(mismatch), None, mismatch)
    out["conv.questions"] = S.metric(len(scores))
    out["conv.judged_turns"] = S.metric(len([t for t in turns if t.get("judge")]))
    errs = [f"{r['deck']} t{r['track']}: {r['error']}" for r in records if r.get("error")]
    errs += [f"{r['deck']}: {c}" for r in records for c in r.get("console") or [] if "pageerror" in c]
    out["conv.errors"] = S.metric(len(errs), None, errs)
    return out


def _ladder_checks(records: list[dict]) -> dict[str, dict]:
    """
    실대화의 「모르겠어요」 사다리 (09-30 WP-J3):
    - conv.stuck_choice_valid — 첫 단계 보기 쌍이 유효한 몫(보기 태그 없음 · 입장 쌍이면 질문의 탐침과 같은 뜻).
    - conv.scaffold_blank_in_question — 발판 빈칸의 가린 말이 질문에 이미 보인 몫 (함정 빼고).
    """
    from . import replay as RP

    valid = n = blank_hit = blank_n = 0
    bad, blanks = [], []
    for r in records:
        qs = {q.get("id"): q for q in (r.get("questions") or [])}
        for t in r["turns"]:
            j = t.get("judge") or {}
            q = qs.get(t.get("qid")) or {}
            stage = j.get("coach_stage")
            if stage == "narrow" and j.get("choices"):
                n += 1
                kind = T_stance(j["choices"])
                probe = ((q.get("basis") or {}).get("probe") or {}).get("kind", "")
                ok = not any(x["tag"] == "relevance.choice_invalid" for x in t.get("tags") or [])
                if kind:
                    ok = ok and RP._stance_fits({"stance": kind, "probe": probe})
                valid += ok
                if not ok:
                    bad.append(f"{r['deck']} Q{t['q']}: {j['choices']} (탐침 {probe or '-'})")
            if stage == "scaffold" and "___" in str(j.get("followup") or "") and not (q.get("trap") or q.get("trap_premise")):
                probe_quotes = [e.get("quote", "") for e in (((q.get("basis") or {}).get("probe") or {}).get("evidence") or [])]
                deck = "\n".join(str(x) for x in (r.get("deck_raw") or {}).values())
                word = RP._fill(str(j["followup"]), [] if T_stance(j.get("choices") or []) else list(j.get("choices") or []),
                                [q.get("answer_gist", ""), q.get("evidence_quote", ""), *probe_quotes, deck])
                if word and not T_stance(j.get("choices") or []):
                    blank_n += 1
                    if RP._shown(word, q):
                        blank_hit += 1
                        blanks.append(f"{r['deck']} Q{t['q']}: 「{word}」 — {str(j['followup'])[:90]}")
    return {"conv.stuck_choice_valid": S.ratio(valid, n, bad),
            "conv.scaffold_blank_in_question": S.ratio(blank_hit, blank_n, blanks)}


def T_stance(chips: list) -> str:
    from . import textkit as TK

    return TK.stance_pair([str(c) for c in chips or []])


def _persona_examples(records: list[dict], key: str) -> list[str]:
    """실패한 페르소나의 첫 판정 react — 무엇이 막았는지."""
    ex = []
    for r in records:
        for s in r["personas"]:
            if key in s and not s[key]:
                t = next((t for t in r["turns"] if t["q"] == s["q"] and t.get("judge")), None)
                if t:
                    j = t["judge"]
                    ex.append(f"{r['deck']} Q{s['q']} {s['persona']}: {t['step']} 「{t['input'][:60]}」 → {j.get('verdict')}/{j.get('score')} «{str(j.get('react'))[:80]}»")
    return ex[:3]


def _self_explained_section(text: str) -> str:
    """결과 화면에서 「스스로 설명한 질문」 칸의 글 (09-30 qa/front 네 묶음). 옛 화면이면 ""."""
    m = re.search(r"스스로 설명한 질문(.*?)(?=도움 받아 닫은 질문|답 보고 다시 말한 질문|넘기거나 안 물은 질문|상세 리포트 보기|$)",
                  text or "", re.S)
    return m.group(1) if m else ""


#: 네 묶음 결과 화면의 표지 — 칸 제목이나 새 헤드라인 중 하나라도 있으면 새 화면이다.
_FOUR_BUCKETS_RE = re.compile(r"스스로 설명한 질문|도움 받아 닫은 질문|답 보고 다시 말한 질문|넘기거나 안 물은 질문|스스로 설명했어요")


def _four_buckets(text: str) -> bool:
    """
    결과 화면이 네 묶음(qa/front)인가.

    09-30 WP-J2 standard 실측: 스스로 설명한 질문이 **0개**면 그 칸이 아예 안 그려진다 — 칸이 비었다고 옛 화면으로 보고
    「판정 good·partial 수」(도움 받아 닫은 것까지)와 헤드라인 0 을 견줘 결과 숫자 불일치 2 를 거짓으로 냈다.
    """
    return bool(_FOUR_BUCKETS_RE.search(text or ""))


def _listed(label: str, section: str) -> bool:
    """질문 이름이 칸 안에 **한 줄로** 있는가 — 다른 질문의 요약 문장 속 낱말(「…다섯 가지 행동 요인(…)」)은 세지 않는다."""
    return any(line.strip() == label.strip() for line in (section or "").splitlines())


def _result_checks(records: list[dict]) -> tuple[list[str], list[str]]:
    """
    결과 화면 — 3라운드 강제 종료(좋음이 아닌 채 닫힘)를 「스스로 설명」 으로 세는가 · 헤드라인 숫자가 그 칸과 맞는가.

    09-30: 예전엔 강제 종료가 **있기만 하면** 「결과 화면이 지킨 질문으로 셈」 이라고 적었다 — 화면을 안 봤다. qa/front 가 결과를
    네 묶음(스스로 설명 / 도움 받아 닫힘 / 답 보고 다시 말함 / 넘김·안 물음)으로 나눈 뒤로는 그 질문 이름이 「스스로 설명한 질문」
    칸에 실제로 있는지를 본다. 옛 화면(칸 없음)이면 예전처럼 헤드라인 「N개 중 M개를 자기 말로 지켰어요」 에 기댄다.
    """
    forced, mismatch = [], []
    for r in records:
        by_q: dict[int, list[dict]] = {}
        for t in r["turns"]:
            if t.get("judge") and not t["judge"].get("coach_stage"):
                by_q.setdefault(t["q"], []).append(t["judge"])
        results = r.get("results") or []
        text = (r.get("end_card") or "") + " " + (r.get("result_text") or "")
        self_sec = _self_explained_section(text)
        buckets = _four_buckets(text)
        for qn, js in by_q.items():
            last = js[-1]
            if not (last.get("mastered") and last.get("verdict") != "good" and int(last.get("round_no") or 0) >= 3):
                continue
            label = next((x.get("label") for x in results if x.get("id") == last.get("question_id")), "") or ""
            if buckets:
                if label and _listed(label, self_sec):
                    forced.append(f"{r['deck']} Q{qn}: {last.get('verdict')}/{last.get('score')} r{last.get('round_no')} 닫힘 → 「스스로 설명」 칸에 셈")
            else:
                forced.append(f"{r['deck']} Q{qn}: {last.get('verdict')}/{last.get('score')} r{last.get('round_no')} 닫힘 → 결과 화면 「지킨 질문」(옛 화면)")
        m = re.search(r"(\d+)개 중 (\d+)개를 (자기 말로 지켰어요|스스로 설명했어요)", text)
        # 새 화면(「…스스로 설명했어요」)은 스스로 설명한 질문이 0개면 그 칸을 아예 그리지 않는다 — 칸이 없으면 0개다 (09-30 표준 단계 오탐)
        new_ui = bool(m and m.group(3) == "스스로 설명했어요")
        if m:
            if buckets or new_ui:
                shown = sum(1 for x in results if x.get("label") and _listed(x["label"], self_sec))
            else:
                shown = len([x for x in results if not x.get("revealed") and x.get("verdict") in ("good", "partial")])
            if int(m.group(2)) != shown:
                mismatch.append(f"{r['deck']}: 헤드라인 {m.group(2)}개 · 칸 {shown}개")
    return forced, mismatch


# ---------------------------------------------------------------------------
# E · F — 레드팀 · 브리지 변조
# ---------------------------------------------------------------------------

def _redteam(target: Target, bridge: Bridge, preps: list[dict], packs: dict[int, dict], run_dir: Path) -> tuple[list[dict], dict]:
    sessions = [(i, preps[i]) for i in sorted(packs) if preps[i].get("mode") == "deck"]
    budget_left = bridge.remaining()
    extra: dict = {}
    if budget_left < 4 or not sessions:
        return [], {"skipped": f"예산 {budget_left}"}
    reserve = min(7, max(0, budget_left - 4))          # 결정성 3 · 자료 주입 2 · 변조 2
    attack_budget = budget_left - reserve
    by_q = {}
    plan = []
    per_session = []
    for i, prep in sessions:
        qmap = {q.get("id"): q for q in prep["questions"]}
        rows = [dict(a, deck=prep["deck"], session=i, order=n) for n, a in enumerate(packs[i]["attacks"])]
        per_session.append(rows)
        by_q.update({(i, qid): q for qid, q in qmap.items()})
    # 덱을 번갈아 — 같은 공격의 다음 행이 다른 덱에서 나오게
    width = max((len(r) for r in per_session), default=0)
    for n in range(width):
        for rows in per_session:
            if n < len(rows):
                plan.append(rows[n])
    picked = R.pick_budgeted(plan, attack_budget - min(sum(len(p["questions"]) for _, p in sessions), attack_budget // 3))
    items = []
    for n, row in enumerate(picked):
        prep = preps[row["session"]]
        items.append(_item(f"atk|{n}", by_q[(row["session"], row["qid"])], row["rounds"], prep))
    # 골자 되읽기 (09-30 WP-J3) — 질문마다 **그 질문의 골자**를 첫 답으로. 우리가 「이렇게 말하면 완성이에요」 로 보여 주는 문장이니 good 이어야 한다.
    # 자리 표시 골자(코드 틀·자료 줄 이어 붙이기)는 모범답이 아니라 뺀다. 공격보다 먼저 담는다(질문 수만큼 · 판정 1콜씩).
    gist_items = []
    for i, prep in sessions:
        for q in prep["questions"]:
            gist = str(q.get("answer_gist") or "").strip()
            if gist and not P_placeholder(q):
                gist_items.append(_item(f"gist|{i}|{q.get('id', '')}", q, [gist], prep))
    gist_items = gist_items[:max(0, attack_budget // 3)]
    items.extend(gist_items)
    det = next(((i, a) for i, p in sessions for a in packs[i]["attacks"] if a["attack"] == "control"), None)
    if det and budget_left - sum(len(x["rounds"]) for x in items) >= 3:
        i, a = det
        for k in range(3):
            items.append(_item(f"det|{k}", by_q[(i, a["qid"])], a["rounds"][:1], preps[i]))
        extra["det_answer"] = a["rounds"][0]
    inj = next(((i, a) for i, p in sessions for a in packs[i]["attacks"] if a["attack"] == "polite_empty"), None)
    if inj and bridge.remaining() - sum(len(x["rounds"]) for x in items) >= 2:
        i, a = inj
        q = by_q[(i, a["qid"])]
        sd = R.slide_injected(preps[i].get("slide_doc") or {}, int(q.get("evidence_slide_no") or (q.get("slide_nos") or [1])[0]))
        wrong = next((b["rounds"][0] for b in packs[i]["attacks"] if b["qid"] == a["qid"] and b["attack"] == "fabricated_number"),
                     R.INJECT)
        for k, ans in enumerate((a["rounds"][0], wrong)):
            items.append(dict(_item(f"inj|{k}", q, [ans], preps[i]), slide_doc=sd))
    C.note(f"── 레드팀: 공격 {len(picked)}개 · 판정 항목 {len(items)} · 남은 예산 {bridge.remaining()}")
    got = target.probe("judge", {"items": items, "budget": bridge.budget, "calls": str(bridge.calls), "stage": "redteam"},
                       timeout=2400, log=run_dir / "redteam.log")
    res = {r["key"]: r["judgements"] for r in got.get("rows") or []}
    rows = []
    for n, row in enumerate(picked):
        js = res.get(f"atk|{n}")
        if not js:
            continue
        o = R.outcome(row, js)
        rows.append(dict(attack=row["attack"], expect=row["expect"], deck=row["deck"], qid=row["qid"], passed=o["passed"],
                         answer=row["rounds"][-1][:160], react=str((js[-1] or {}).get("react") or "")[:120],
                         verdict=(js[-1] or {}).get("verdict"), score=(js[-1] or {}).get("score")))
    extra["gist"] = [{"key": it["key"], "gist": it["rounds"][0][:160], **((res.get(it["key"]) or [{}])[0])} for it in gist_items
                     if res.get(it["key"])]
    extra["det"] = [(res.get(f"det|{k}") or [{}])[0] for k in range(3) if res.get(f"det|{k}")]
    extra["inj"] = [(res.get(f"inj|{k}") or [{}])[0] for k in range(2) if res.get(f"inj|{k}")]
    extra["tamper"] = _tamper(bridge, preps, packs)
    extra["judge_error"] = got.get("error")
    C.write_json(run_dir / "redteam.json", {"rows": rows, "extra": extra})
    return rows, extra


def P_texts(slide_doc: dict) -> dict:
    from . import textkit as TK

    return TK.slide_texts(slide_doc)


def P_placeholder(q: dict) -> bool:
    """자리 표시 골자인가 (잣대 쪽 정의 — replay `_placeholder_gist` 와 같다)."""
    from .replay import _placeholder_gist

    return _placeholder_gist(q)


def _item(key: str, q: dict, rounds: list[str], prep: dict) -> dict:
    return {"key": key, "question": q, "rounds": rounds, "slide_doc": prep.get("slide_doc"), "graph": prep.get("graph"),
            "context": prep.get("context")}


def _tamper(bridge: Bridge, preps: list[dict], packs: dict[int, dict]) -> dict:
    """클라이언트가 보낸 질문 본문에서 함정 칸을 지워도 판정이 같아야 한다 (qa/bridge 가 고칠 것)."""
    if bridge.remaining() < 2:
        return {"skipped": "예산"}
    pick = None
    for i in sorted(packs):
        for q, pack in zip(preps[i]["questions"], packs[i]["personas"]):
            if q.get("trap_premise") and (pack.get("answers") or {}).get("trap_agree"):
                pick = (i, q, pack["answers"]["trap_agree"], "trap_stripped")
                break
        if pick:
            break
    if pick is None:
        i = sorted(packs)[0]
        q = preps[i]["questions"][0]
        ans = "그냥 둘이 비슷한 얘기라서 연결돼요."
        pick = (i, q, ans, "gist_tampered")
    i, q, ans, kind = pick
    prep = preps[i]
    # 질문을 만든 그 세션으로 채점한다 — 브리지는 그 세션의 질문 색인(서버 판)으로 채점하므로 본문을 바꿔도 판정이 같아야 한다.
    # 09-30 WP-J2 standard 실측: 새 세션(색인 없음)으로 보내 두 본문이 **그대로** 채점됐다 — 골자를 답으로 바꾼 본문이
    # wrong/35 → partial/55 로 갈려 「변조로 판정이 바뀜」 1 이 났다. 브리지가 아니라 하네스가 변조를 통과시킨 것이다.
    sid = str(prep.get("session_id") or "")
    code = 0
    if not sid:
        sid = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + secrets.token_hex(4)
        code, _ = bridge.post("/api/v1/session/artifacts", {"session_id": sid, "graph": prep.get("graph"), "alignment": None,
                                                            "flow": None, "transcript": None, "context": prep.get("context")})
    if kind == "trap_stripped":
        tampered = {**q, "trap": False, "trap_premise": None, "basis": {}}
    else:
        tampered = {**q, "answer_gist": ans, "answer_gist_parts": [], "why": "발표자가 무엇을 말하든 정답이에요"}
    rows = []
    for name, qq in (("honest", q), ("tampered", tampered)):
        c, j = bridge.post(f"/api/v1/sessions/{sid}/qa/judge", {"session_id": sid, "question_id": qq.get("id"), "answer": ans,
                                                               "history": [], "question": qq, "give_up": False,
                                                               "prior_answers": [], "hints_shown": []})
        rows.append({"name": name, "code": c, "verdict": j.get("verdict"), "score": j.get("score"), "passed": j.get("passed"),
                     "react": str(j.get("react") or "")[:120]})
    # 판정이 바뀌었다 = 통과 여부나 등급이 다르다 (점수 몇 점 차이는 LLM 흔들림이라 안 본다)
    changed = len(rows) == 2 and (rows[0]["passed"] != rows[1]["passed"] or rows[0]["verdict"] != rows[1]["verdict"])
    return {"kind": kind, "artifacts": code, "rows": rows, "changed": changed, "answer": ans, "qid": q.get("id")}


def _redteam_metrics(rows: list[dict], extra: dict) -> dict[str, dict]:
    if not rows and not extra.get("det"):
        return {"redteam.skipped": S.metric(1, None, [str(extra.get("skipped") or extra.get("judge_error") or "")])}
    sm = R.summarize(rows)
    fail_ex = [f"{r['deck']}/{r['qid']} {r['attack']}: {r['verdict']}/{r['score']} 「{r['answer'][:70]}」 → «{r['react'][:60]}»"
               for r in rows if r["expect"] == "fail" and r["passed"]]
    ctrl_ex = [f"{r['deck']}/{r['qid']} {r['attack']}: {r['verdict']}/{r['score']} 「{r['answer'][:70]}」 → «{r['react'][:60]}»"
               for r in rows if r["expect"] == "pass" and not r["passed"]]
    out = {
        "redteam.attack_pass_rate": S.metric(sm["attack_pass_rate"], sm["attack_n"], fail_ex, hit=sm["attack_passed"]),
        "redteam.control_pass_rate": S.metric(sm["control_pass_rate"], sm["control_n"], ctrl_ex, hit=sm["control_passed"]),
    }
    for name, v in sorted(sm["by_attack"].items()):
        out[f"redteam.by.{name}"] = S.metric(v["passed"] / v["n"] if v["n"] else None, v["n"], expect=v["expect"])
    det = extra.get("det") or []
    if det:
        flips = len({R.verdict_passed(j) for j in det}) > 1
        out["redteam.determinism_flips"] = S.metric(int(flips), len(det), [f"{j.get('verdict')}/{j.get('score')}" for j in det]
                                                   + [f"답: {extra.get('det_answer', '')[:100]}"])
        out["redteam.determinism_spread"] = S.metric(max(int(j.get("score") or 0) for j in det) - min(int(j.get("score") or 0) for j in det),
                                                    len(det))
    inj = extra.get("inj") or []
    if inj:
        out["redteam.slide_inject_pass"] = S.metric(sum(R.verdict_passed(j) for j in inj), len(inj),
                                                   [f"{j.get('verdict')}/{j.get('score')} «{str(j.get('react'))[:80]}»" for j in inj])
    gists = extra.get("gist") or []
    if gists:
        bad = [g for g in gists if g.get("error") or g.get("verdict") != "good"]
        out["conv.gist_replay_good"] = S.ratio(len(gists) - len(bad), len(gists),
                                               [f"{g['key']}: {g.get('verdict')}/{g.get('score')} guard={g.get('guard')!r} «{g['gist'][:70]}» → "
                                                f"«{str(g.get('react'))[:60]}»" for g in bad])
    tp = extra.get("tamper") or {}
    if tp.get("rows"):
        out["redteam.bridge_tamper_changed"] = S.metric(int(bool(tp.get("changed"))), 1,
                                                       [f"{tp.get('kind')} {r['name']}: {r['code']} {r['verdict']}/{r['score']} passed={r['passed']}"
                                                        for r in tp["rows"]])
    return out


# ---------------------------------------------------------------------------
# G · 모으기
# ---------------------------------------------------------------------------

def _booth(target: Target, bridge: Bridge, run_dir: Path) -> dict[str, dict] | None:
    script = target.repo / "labs" / "qa_call" / "run.py"
    if not script.exists():
        script = C.HARNESS_ROOT / "labs" / "qa_call" / "run.py"
    if bridge.remaining() < 8:
        return {"booth.skipped": S.metric(1, None, [f"예산 {bridge.remaining()}"])}
    C.note("── 부스 사진 흐름 (labs/qa_call all)")
    r = C.run([target.python, str(script), "all", "--base", bridge.base], cwd=target.repo,
              env={"LD_LIBRARY_PATH": C.PW_LIBS}, timeout=900)
    (run_dir / "booth.log").write_text((r.stdout or "") + (r.stderr or ""), encoding="utf-8")
    outs = sorted((script.parent / "out").glob("*/report.json"), key=lambda p: p.stat().st_mtime)
    rep = C.read_json(outs[-1]) if outs else None
    if not rep:
        return {"booth.flow_ok": S.metric(0.0, 1, C.tail(r.stdout + r.stderr, 5))}
    shutil.copyfile(outs[-1], run_dir / "booth_report.json")
    stages = rep.get("stages") or {}
    ok = "finish" in stages and not any("error" in (v or {}) for v in stages.values())
    errs = [c for c in rep.get("console") or [] if not c.startswith("warning")]
    texts = [b.get("text", "") for b in rep.get("bubbles") or [] if "is-me" not in (b.get("cls") or "")]
    tone = TG.tone_tags(texts)
    return {"booth.flow_ok": S.metric(1.0 if ok else 0.0, 1, [f"{k}: {v}" for k, v in stages.items() if "error" in (v or {})]),
            "booth.console_errors": S.metric(len(errs), None, errs[:5]),
            "booth.tone_tags": S.metric(len(tone), len(texts), [f"{t['tag']} {t['detail']} «{t['quote'][:80]}»" for t in tone][:5]),
            "booth.sec": S.metric(rep.get("total_sec"))}


def _pipeline_metrics(preps: list[dict], bridge: Bridge) -> dict[str, dict]:
    failed = [f"{p['deck']} {p['mode']} t{p['track']}: {p.get('error')}" for p in preps if not p.get("ok")]
    short, t5 = [], []
    for p in preps:
        if not p.get("ok"):
            continue
        got = sum(1 for q in p.get("questions") or [] if q.get("trap") or q.get("trap_premise"))
        # 5분 트랙은 탐침 질문을 밀어내며 함정을 넣지 않는다 (09-30 사용자 결정) — 부족으로 세지 않고 참고로만 남긴다.
        if str(p.get("track")) != "10":
            t5.append(f"{p['deck']} {p['mode']} t{p['track']}: 함정 {got}")
            continue
        want = TRACK_TRAPS.get(str(p.get("track")), 0)
        if got < want:
            short.append((want - got, f"{p['deck']} {p['mode']} t{p['track']}: 함정 {got}/{want}"))
    audio = [p for p in preps if p.get("mode") == "audio"]
    out = {
        "pipeline.failed_decks": S.metric(len(failed), len(preps), failed),
        "pipeline.traps_missing": S.metric(sum(n for n, _ in short), len(preps), [x for _, x in short]),
        "pipeline.traps_t5": S.metric(len(t5), len(preps), t5),
        "pipeline.questions": S.metric(sum(len(p.get("questions") or []) for p in preps if p.get("ok"))),
        "pipeline.llm_calls": S.metric(sum(p.get("llm_calls", 0) for p in preps)),
        "pipeline.wall_sec": S.metric(round(sum(p.get("wall", 0) for p in preps), 1)),
    }
    if audio:
        out["audio.ok"] = S.metric(sum(1 for p in audio if p.get("ok")), len(audio), [str(p.get("error")) for p in audio if not p.get("ok")])
    return out


def _digest(records: list[dict], run_dir: Path) -> None:
    """사람이 읽는 대화록 — 질문마다 페르소나 · 턴(입력 → 판정 · react · 되물음 · 보기 · 태그)."""
    lines = ["# 대화록 (자동 페르소나)", ""]
    for r in records:
        lines += [f"## {r['deck']} · {r['mode']} · t{r['track']} — 배정 {r.get('plan')}", ""]
        for s in r["personas"]:
            lines.append(f"### Q{s['q']} {s['persona']} — " + ", ".join(f"{k}={v}" for k, v in s.items()
                                                                         if k not in ("q", "qid", "persona", "sec", "dunno_detail")))
            for t in [t for t in r["turns"] if t["q"] == s["q"]]:
                j = t.get("judge") or {}
                head = f"- `{t['step']}` 「{t['input'][:120]}」"
                if j:
                    head += f" → **{j.get('coach_stage') or j.get('verdict')}/{j.get('score')}** r{j.get('round_no')} react «{str(j.get('react'))[:140]}»"
                    if j.get("followup"):
                        head += f" · 되물음 «{str(j['followup'])[:120]}»"
                    if j.get("choices"):
                        head += f" · 보기 {j['choices']}"
                    if j.get("missing_points"):
                        head += f" · 빠짐 {j['missing_points'][:2]}"
                lines.append(head)
                if t.get("tags"):
                    lines.append("  - 태그: " + "; ".join(f"{x['tag']} {x['detail']}" for x in t["tags"])[:300])
            lines.append("")
    (run_dir / "conversations.md").write_text("\n".join(lines), encoding="utf-8")
