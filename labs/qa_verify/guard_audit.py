"""
판정 가드 감사 — LLM 자리에 **「무엇이든 good 85, 결손 없음, 전제 바로잡음」** 이라고 답하는 대본(Permissive)을 넣고
대상 `judge_answer` 를 돌린다. LLM 없이 결정적이다 (자식 프로세스, 실제 제공자는 막혀 있다).

LLM 이 가장 무르게 굴 때 **코드 가드만으로** 무엇이 막히고 무엇이 새는지를 잰다:
- 좋은 답(자료 줄을 입말로 · 함정 정정)이 가드에 떨어지면 → 맞는 답 강등 (감사 §2)
- 나쁜 답(뒤집은 사실 · 무관한 줄 · 한 낱말 · 함정 동의 · 레드팀 공격)이 통과하면 → 코드 방어의 빈틈 (감사 §3 · 레드팀)
- 「모르겠어요」 두 번 → 발판·해설로 가는가, 보기가 명사구이고 자료가 세운 쪽이 들어 있는가 (감사 §8)
- 가드가 내린 판정에 칭찬 react 가 남는가 · 되물음에 가드 사유가 새는가 (감사 §6) · 코드 문장의 말투
"""

from __future__ import annotations

import json
from pathlib import Path

from . import common as C
from . import personas as P
from . import redteam as R
from . import scoreboard as S
from . import tags as TG
from . import textkit as T

PERMISSIVE_REACT = "좋아요, 핵심을 잘 짚었어요."
#: 가드 감사에 거는 페르소나 단계와 기대 (pass = 통과해야, fail = 통과 못 해야)
STEPS = (("good", "pass"), ("wrong", "fail"), ("offtopic", "fail"), ("one_word", "fail"))
TRAP_STEPS = (("trap_correct", "pass"), ("trap_agree", "fail"))


def make_permissive(q: dict):
    from chuckchuck.providers.llm_base import LLMProvider

    parts = q.get("answer_gist_parts") or []
    judge = {"verdict": "good", "score": 85, "react": PERMISSIVE_REACT, "summary_sentence": "핵심을 자기 말로 설명했어요.",
             "missing_points": [], "followup": "", "covered_parts": [True] * len(parts), "premise_corrected": True}
    coach = {"react": "괜찮아요. 같이 짚어 볼게요.", "followup": "", "choices": [], "explanation": ""}

    class Permissive(LLMProvider):
        name = "permissive"

        def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
            return json.dumps(coach if "코치" in (system or "")[:60] else judge, ensure_ascii=False)

    return Permissive()


def _judge(q: dict, answer: str, env: dict, *, prior=None, history=None, give_up=False) -> dict:
    from chuckchuck import judge_answer

    j = judge_answer(q, answer, graph=env["graph"], context=env["context"], slidedoc=env["slide_doc"],
                     prior_answers=list(prior or []), history=list(history or []), give_up=give_up,
                     llm=make_permissive(q))
    return j.to_dict()


def _row(deck, track, q, step, expect, answer, j, ctx) -> dict:
    turn = {"judge": j, "bubbles": [], "input": answer}
    tags = TG.turn_tags(turn, dict(ctx, step=step, cumulative=answer))
    keep = {k: j.get(k) for k in ("verdict", "score", "passed", "mastered", "react", "followup", "missing_points",
                                  "choices", "coach_stage", "round_no", "explanation")}
    return {"deck": deck, "track": track, "qid": q.get("id", ""), "step": step, "expect": expect, "answer": answer,
            "judge": keep, "passed": TG.passed(j), "tags": tags}


def audit_question(deck: str, track: str, q: dict, pack: dict, packs: list[dict], env: dict) -> list[dict]:
    rows = []
    others = [f"{o.get('question', '')} {o.get('answer_gist', '')}" for o in env["questions"] if o is not q]
    ctx = {"question": q, "deck_lines": env["lines"], "deck_raw": env["raw"], "deck_text": "\n".join(env["raw"].values()),
           "others": others, "corrected": False}
    a = pack.get("answers") or {}
    steps = TRAP_STEPS if pack.get("trap") else STEPS
    for step, expect in steps:
        text = a.get(step, "")
        if not text:
            continue
        j = _judge(q, text, env)
        rows.append(_row(deck, track, q, step, expect, text, j, dict(ctx, corrected=step == "trap_correct")))
    for atk in R.attacks_for(q, pack, packs):
        if atk["expect"] != "fail":
            continue
        prior, hist, js = [], [], []
        for ans in atk["rounds"]:
            j = _judge(q, ans, env, prior=prior, history=hist)
            js.append(j)
            prior.append(ans)
            hist.append({"질문": q.get("question", ""), "답변": ans, "판정": j.get("verdict"), "question_id": q.get("id", "")})
        row = _row(deck, track, q, "attack:" + atk["attack"], "fail", atk["rounds"][-1], js[-1], ctx)
        row["passed"] = any(TG.passed(x) for x in js)
        rows.append(row)
    # 「모르겠어요」 → 또 → 또 — 위치(보기) → 발판 → 해설
    hist = []
    for i in range(3):
        j = _judge(q, "모르겠어요", env, history=hist, give_up=True)
        rows.append(_row(deck, track, q, f"dunno{i + 1}", "coach", "모르겠어요", j, ctx))
        hist.append({"질문": q.get("question", ""), "답변": "(모르겠어요)", "판정": j.get("verdict") or "unknown", "포기": True,
                     "question_id": q.get("id", "")})
    return rows


def _examples(rows: list[dict], pred, k: int = 5) -> list[str]:
    out = []
    for r in rows:
        if pred(r):
            j = r["judge"]
            out.append(f"{r['deck']}/t{r['track']}/{r['qid']} {r['step']}: {j.get('verdict')}/{j.get('score')} "
                       f"react «{str(j.get('react'))[:70]}» — 답 «{r['answer'][:70]}»")
        if len(out) >= k:
            break
    return out


def summarize(rows: list[dict], errors: list[str], n_questions: int) -> dict[str, dict]:
    good = [r for r in rows if r["expect"] == "pass"]
    out = {"guard.good_demoted": S.ratio(sum(not r["passed"] for r in good), len(good), _examples(good, lambda r: not r["passed"]))}
    for step in ("offtopic", "wrong", "one_word", "trap_agree"):
        rs = [r for r in rows if r["step"] == step]
        out[f"guard.catch.{step}"] = S.ratio(sum(not r["passed"] for r in rs), len(rs), _examples(rs, lambda r: r["passed"]))
    atk = [r for r in rows if r["step"].startswith("attack:")]
    by: dict[str, list[int]] = {}
    for r in atk:
        s = by.setdefault(r["step"][7:], [0, 0])
        s[0] += 0 if r["passed"] else 1
        s[1] += 1
    out["guard.redteam.code_block"] = S.ratio(sum(not r["passed"] for r in atk), len(atk), _examples(atk, lambda r: r["passed"]),
                                              by_attack={k: f"{v[0]}/{v[1]}" for k, v in sorted(by.items())})
    demoted = [r for r in rows if not r["passed"] and not r["judge"].get("coach_stage")]
    out["guard.praise_kept"] = S.ratio(sum(TG.PRAISE_RE.search(str(r["judge"].get("react") or "")) is not None for r in demoted),
                                       len(demoted), _examples(demoted, lambda r: TG.PRAISE_RE.search(str(r["judge"].get("react") or ""))))
    judged = [r for r in rows if not r["judge"].get("coach_stage")]
    glue = lambda r: any(t["tag"].startswith("relevance.followup") for t in r["tags"])  # noqa: E731
    out["guard.followup_glue"] = S.ratio(sum(glue(r) for r in judged), len(judged),
                                         [f"{r['deck']}/{r['qid']} {r['step']}: «{r['judge'].get('followup')}»" for r in judged if glue(r)][:5])
    chosen = [r for r in rows if r["step"].startswith("dunno") and r["judge"].get("choices")]
    bad = lambda r: any(t["tag"] == "relevance.choice_invalid" for t in r["tags"])  # noqa: E731
    out["guard.choice_invalid"] = S.ratio(sum(bad(r) for r in chosen), len(chosen),
                                          [f"{r['deck']}/{r['qid']} {r['step']}: {r['judge'].get('choices')} — "
                                           + "; ".join(t["detail"] for t in r["tags"] if t["tag"] == "relevance.choice_invalid")
                                           for r in chosen if bad(r)][:5])
    ladder_ok = ladder_n = 0
    stages: dict[str, list[str]] = {}
    for r in rows:
        if r["step"].startswith("dunno"):
            stages.setdefault(f"{r['deck']}/{r['track']}/{r['qid']}", []).append(r["judge"].get("coach_stage") or "-")
    bad_ladders = []
    for key, st in stages.items():
        ladder_n += 1
        ok = len(st) == 3 and st[1] in ("scaffold", "explain") and st[2] == "explain"
        ladder_ok += ok
        if not ok:
            bad_ladders.append(f"{key}: {' → '.join(st)}")
    out["guard.dunno_ladder_ok"] = S.ratio(ladder_ok, ladder_n, bad_ladders)
    tone = lambda r: [t for t in r["tags"] if t["tag"].startswith("tone.")]  # noqa: E731
    out["guard.tone"] = S.ratio(sum(bool(tone(r)) for r in rows), len(rows),
                                [f"{r['deck']}/{r['qid']} {r['step']}: {t['tag']} {t['detail']} «{t['quote'][:80]}»"
                                 for r in rows for t in tone(r)][:5])
    out["guard.errors"] = S.metric(len(errors), None, errors)
    out["guard.n_questions"] = S.metric(n_questions)
    out["guard.n_rows"] = S.metric(len(rows))
    return out


def run(cache: Path, decks: list[str] | None, tracks: tuple[str, ...], helpers_for) -> dict:
    names = [d.name for d in sorted(cache.iterdir()) if d.is_dir() and not d.name.startswith("_")
             and (d / "questions_t5.json").exists() and (d / "slide_doc.json").exists()]
    if decks:
        names = [n for n in names if n in decks]
    rows: list[dict] = []
    errors: list[str] = []
    n_q = 0
    for name in names:
        d = cache / name
        sd, graph = C.read_json(d / "slide_doc.json"), C.read_json(d / "graph.json")
        truth = C.read_json(C.HARNESS_ROOT / "labs" / "qa_bench" / "corpus" / name / "truth.json") or {}
        env = {"slide_doc": sd, "graph": graph, "context": truth.get("context") or {"situation": "school_project", "duration_min": 5},
               "lines": [x for _, x in T.deck_lines(sd)], "raw": T.slide_texts(sd)}
        helpers = helpers_for(graph)
        for t in tracks:
            qs = (C.read_json(d / f"questions_t{t}.json") or {}).get("questions") or []
            env["questions"] = qs
            try:
                packs = P.build_all(qs, sd, helpers)
            except Exception as e:  # noqa: BLE001
                errors.append(f"personas {name} t{t}: {type(e).__name__}: {str(e)[:120]}")
                continue
            for q, pack in zip(qs, packs):
                n_q += 1
                try:
                    rows += audit_question(name, t, q, pack, packs, env)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{name} t{t} {q.get('id')}: {type(e).__name__}: {str(e)[:160]}")
    return {"metrics": summarize(rows, errors, n_q), "rows": rows[:600], "decks": names}
