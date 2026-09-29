"""
대상 저장소 코드로 도는 자식 프로세스의 진입점 — JSON 을 받아 JSON 을 쓴다.

    <대상 python> labs/qa_verify/target_probe.py <명령> <입력.json> <출력.json>      (환경: QA_VERIFY_REPO=<대상>)

`chuckchuck` 은 **대상의 것**을 먼저 올리고(sys.modules 에 박힌다), 그 뒤에 하네스 뿌리를 sys.path 앞에 둔다 — 잣대
(labs.qa_verify · labs/qa_bench 의 metrics 따위)는 하네스 것이고, 재는 대상 코드는 대상 것이다.

명령
- info            대상에 있는 공개 함수 목록
- regress         회귀 사례 (regression/cases.json)
- replay          벤치 캐시 결정적 재생 지표 (LLM 없음)
- guard           판정 가드 감사 — LLM 자리에 정해 둔 응답 (LLM 없음)
- personas        질문 목록 → 자동 페르소나 · 공격 답 (LLM 없음)
- judge           정해진 답들을 실 LLM 으로 판정 (standard/full — calls.jsonl 에 세고 예산에서 끊는다)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def _bootstrap() -> tuple[Path, Path]:
    here = Path(__file__).resolve().parent
    harness_root = here.parents[1]
    repo = Path(os.environ.get("QA_VERIFY_REPO") or harness_root).resolve()
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != here]
    sys.path.insert(0, str(repo))
    import chuckchuck  # noqa: F401 — 대상 패키지를 먼저 올린다

    got = Path(chuckchuck.__file__).resolve().parents[1]
    if got != repo:
        raise SystemExit(f"대상이 아닌 chuckchuck 을 올렸어요: {got} ≠ {repo}")
    sys.path.insert(0, str(harness_root))
    return repo, harness_root


REPO, HARNESS_ROOT = _bootstrap()

from labs.qa_verify import common as C  # noqa: E402
from labs.qa_verify import llm_guard  # noqa: E402
from labs.qa_verify import personas as P  # noqa: E402
from labs.qa_verify import redteam as R  # noqa: E402


def target_helpers(graph: dict | None = None) -> P.Helpers:
    """대상에 있는 함수로 페르소나 도우미를 채운다 — 없는 것은 비워 둔다(페르소나가 제 규칙으로)."""
    h = P.Helpers()
    try:
        from chuckchuck import _evidence as E

        h.slide_units = E.slide_units
        if hasattr(E, "ranked_quotes"):
            h.ranked_quotes = lambda label, summary, texts, question, k: E.ranked_quotes(label, summary, texts, question=question, k=k)
    except ImportError:
        pass
    try:
        from chuckchuck import _reason as RS

        h.asks_reason = RS.asks_reason

        def reason_lines(q: dict, texts: dict, anchors: list[int]):
            ev = RS.evidence(q.get("question", ""), anchors, texts)
            if ev is None or ev.strongest is None:
                return []
            out = [(ev.strongest.slide_no, ev.strongest.text)]
            num = next((ln for ln in ev.reasons if ln is not ev.strongest and RS.has_number(ln.text)), None)
            if num is not None:
                out.append((num.slide_no, num.text))
            return out

        h.reason_lines = reason_lines
    except ImportError:
        pass
    try:
        from chuckchuck import _grounding as G
        from chuckchuck import _traps as TR
        from chuckchuck.contracts import ConceptGraph, SlideDoc

        nodes = ConceptGraph.from_dict(graph).nodes if graph else []

        def trap_candidates(label: str, anchors: list[int], slide_doc: dict):
            sd = SlideDoc.from_dict(slide_doc)
            idx = G.build_index({s.slide_no: s for s in sd.slides}, nodes)
            return [{"kind": c.premise.kind, "premise": c.premise.premise, "fact": c.premise.fact, "line": c.line}
                    for c in TR.candidates(label, anchors, idx)]

        h.trap_candidates = trap_candidates
    except ImportError:
        pass
    return h


def cmd_info(_: dict) -> dict:
    found = {}
    for mod, names in (("chuckchuck._evidence", ("slide_units", "ranked_quotes", "best_quote", "mask_gist")),
                       ("chuckchuck._reason", ("evidence", "check_gist", "choice_pair", "contrast_choice")),
                       ("chuckchuck._traps", ("candidates", "premise_stance", "leaks_fact")),
                       ("chuckchuck._grounding", ("gist_problems", "direction_conflicts")),
                       ("chuckchuck.f09_judge", ("judge_answer", "_narrow_followup", "_scaffold_judgement")),
                       ("chuckchuck.f08_questions", ("build_questions", "build_hint_ladder", "_undercut_question"))):
        try:
            m = __import__(mod, fromlist=["x"])
            found[mod] = [n for n in names if hasattr(m, n)]
        except ImportError:
            found[mod] = None
    return {"repo": str(REPO), "has": found}


def cmd_regress(inp: dict) -> dict:
    llm_guard.install("forbid")
    from labs.qa_verify import regress

    return {"cases": regress.run_cases(Path(inp["cases"]) if inp.get("cases") else regress.CASES,
                                       set(inp["only"]) if inp.get("only") else None)}


def cmd_replay(inp: dict) -> dict:
    llm_guard.install("forbid")
    from labs.qa_verify import replay

    return replay.run(Path(inp["cache"]), inp.get("decks") or None, tuple(inp.get("tracks") or ("5", "10")))


def cmd_guard(inp: dict) -> dict:
    llm_guard.install("forbid")
    from labs.qa_verify import guard_audit

    return guard_audit.run(Path(inp["cache"]), inp.get("decks") or None, tuple(inp.get("tracks") or ("5",)),
                           helpers_for=target_helpers)


def cmd_personas(inp: dict) -> dict:
    llm_guard.install("forbid")
    qs, sd = inp["questions"], inp["slide_doc"]
    helpers = target_helpers(inp.get("graph"))
    packs = P.build_all(qs, sd, helpers)
    attacks = []
    for q, pack in zip(qs, packs):
        for a in R.attacks_for(q, pack, packs):
            attacks.append(dict(a, qid=q.get("id", "")))
    return {"personas": packs, "attacks": attacks}


def cmd_judge(inp: dict) -> dict:
    """items: [{"key","question","rounds":[답…],"slide_doc","graph","context","give_up"?}] → 라운드마다 판정 dict (실 LLM)."""
    calls = Path(inp["calls"])
    llm_guard.install("count", calls, int(inp["budget"]), stage=inp.get("stage", "judge"))
    from chuckchuck import judge_answer

    rows = []
    for item in inp["items"]:
        prior, history, got = [], [], []
        q = item["question"]
        for answer in item["rounds"]:
            t0 = time.time()
            try:
                j = judge_answer(q, answer, graph=item.get("graph"), context=item.get("context"),
                                 slidedoc=item.get("slide_doc"), prior_answers=list(prior), history=list(history)).to_dict()
            except llm_guard.BudgetExceeded as e:
                got.append({"error": f"budget: {e}"})
                rows.append({"key": item["key"], "judgements": got, "budget_stop": True})
                return {"rows": rows, "budget_stop": True}
            except Exception as e:  # noqa: BLE001
                j = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            j["sec"] = round(time.time() - t0, 2)
            got.append(j)
            prior.append(answer)
            history.append({"질문": q.get("question", ""), "답변": answer, "판정": j.get("verdict") or "unknown",
                            "question_id": q.get("id", "")})
        rows.append({"key": item["key"], "judgements": got})
    return {"rows": rows}


COMMANDS = {"info": cmd_info, "regress": cmd_regress, "replay": cmd_replay, "guard": cmd_guard,
            "personas": cmd_personas, "judge": cmd_judge}


def main(argv: list[str]) -> int:
    cmd, inp_path, out_path = argv[0], Path(argv[1]), Path(argv[2])
    inp = C.read_json(inp_path, {}) or {}
    t0 = time.time()
    try:
        out = COMMANDS[cmd](inp)
        out["ok"] = True
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — 부모가 읽을 수 있게 남긴다
        import traceback

        out = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-2000:]}
    out["sec"] = round(time.time() - t0, 2)
    C.write_json(out_path, out)
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
