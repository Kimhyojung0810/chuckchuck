"""
저장된 세션을 지금 코드로 다시 돌려 그때 결과와 견준다 — 프롬프트를 고친 뒤의 회귀 검사.

    python examples/replay_sessions.py --stage rubric                  # 채점표 항목별 점수 델타
    python examples/replay_sessions.py --stage judge --limit 3         # 저장된 답을 다시 판정, verdict 뒤집힘
    python examples/replay_sessions.py --stage questions --since 2026-09-01
    → exports/replay/<시각>_<stage>[_<tag>].json + .md

왜 — 「좋아진 것 같다」 는 측정이 아니다. 동의 세션에는 그때의 입력(자료·발화·그래프)과
출력(채점·판정·질문)이 함께 남아 있어, 같은 입력을 새 프롬프트로 다시 돌리면 무엇이 어떻게
바뀌었는지 항목 단위로 보인다. `manifest.code_version` 이 "그때" 가 어느 커밋인지 말한다.

LLM 을 실제로 부른다 (과금). 기본 `--limit 5`, 최신 세션부터.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chuckchuck.config import load_dotenv  # noqa: E402

load_dotenv()

from chuckchuck import build_questions, judge_answer, score_rubric, triage_questions  # noqa: E402
from chuckchuck.contracts import Question  # noqa: E402
from demo.session_archive import SessionArchive  # noqa: E402

OUT_DIR = ROOT / "exports" / "replay"
STAGES = ("rubric", "judge", "questions")


def _since_epoch(text: str | None) -> float:
    return time.mktime(time.strptime(text, "%Y-%m-%d")) if text else 0.0


def _load(archive: SessionArchive, sid: str, *kinds: str) -> dict:
    return {k: archive.read_artifact(sid, k) for k in kinds}


# ── 단계별 재생 ────────────────────────────────────────────────────────────────

def replay_rubric(archive: SessionArchive, rec, llm) -> dict | None:
    art = _load(archive, rec.session_id, "rubric_score", "slide_doc", "concept_doc", "concept_graph",
                "transcript", "alignment_doc", "flow_diff", "pace_doc", "habit_doc")
    before = art["rubric_score"]
    if before is None:
        return None
    after = score_rubric(
        situation=before.get("situation"), context=rec.context, slides=art["slide_doc"],
        concepts=art["concept_doc"], graph=art["concept_graph"], transcript=art["transcript"],
        alignment=art["alignment_doc"], flow=art["flow_diff"], pace=art["pace_doc"],
        habits=art["habit_doc"], llm=llm,
    ).to_dict()
    b_items = {it["no"]: it for it in before.get("items", [])}
    deltas = []
    for it in after.get("items", []):
        old = b_items.get(it["no"])
        if old is None:
            continue
        deltas.append({"no": it["no"], "name": it["name"], "before": old["score"], "after": it["score"],
                       "delta": round(it["score"] - old["score"], 1),
                       "status": f"{old['status']}→{it['status']}" if old["status"] != it["status"] else it["status"]})
    return {"session_id": rec.session_id, "title": rec.title, "code_before": rec.code_version,
            "total_before": before.get("score"), "total_after": after.get("score"),
            "model_before": before.get("model"), "model_after": after.get("model"), "items": deltas}


def replay_judge(archive: SessionArchive, rec, llm) -> dict | None:
    turns = archive.read_stream(rec.session_id, "qa_turns")
    if not turns:
        return None
    art = _load(archive, rec.session_id, "concept_graph", "alignment_doc", "transcript", "slide_doc")
    rows = []
    for t in turns:
        old = t.get("judgement") or {}
        new = judge_answer(
            Question.from_dict(t["question"]), t.get("answer", ""),
            graph=art["concept_graph"], alignment=art["alignment_doc"], transcript=art["transcript"],
            context=rec.context, give_up=bool(t.get("give_up")), prior_answers=t.get("prior_answers") or [],
            hints_shown=t.get("hints_shown") or [], slidedoc=art["slide_doc"], llm=llm,
        ).to_dict()
        rows.append({"question_id": t.get("question_id"), "answer": (t.get("answer") or "")[:60],
                     "verdict_before": old.get("verdict"), "verdict_after": new.get("verdict"),
                     "score_before": old.get("score"), "score_after": new.get("score"),
                     "flipped": old.get("verdict") != new.get("verdict")})
    return {"session_id": rec.session_id, "title": rec.title, "code_before": rec.code_version, "turns": rows}


def replay_questions(archive: SessionArchive, rec, llm) -> dict | None:
    art = _load(archive, rec.session_id, "question_doc", "concept_graph", "alignment_doc", "flow_diff",
                "transcript", "slide_doc")
    before = art["question_doc"]
    if before is None or art["concept_graph"] is None:
        return None
    triage = triage_questions(art["concept_graph"], art["alignment_doc"], art["flow_diff"], rec.context,
                              transcript=art["transcript"], llm=llm)
    after = build_questions(art["concept_graph"], triage, track=before.get("track", "5"),
                            alignment=art["alignment_doc"], flow=art["flow_diff"], transcript=art["transcript"],
                            slidedoc=art["slide_doc"], context=rec.context, llm=llm).to_dict()
    b_nodes = {q.get("node_id") for q in before.get("questions", [])}
    a_nodes = {q.get("node_id") for q in after.get("questions", [])}
    return {"session_id": rec.session_id, "title": rec.title, "code_before": rec.code_version,
            "n_before": len(before.get("questions", [])), "n_after": len(after.get("questions", [])),
            "kept_nodes": sorted(b_nodes & a_nodes), "dropped_nodes": sorted(b_nodes - a_nodes),
            "new_nodes": sorted(a_nodes - b_nodes),
            "questions_after": [q.get("question") for q in after.get("questions", [])]}


REPLAY = {"rubric": replay_rubric, "judge": replay_judge, "questions": replay_questions}


# ── 요약 ────────────────────────────────────────────────────────────────────────

def summarize(stage: str, results: list[dict]) -> dict:
    if stage == "rubric":
        deltas = [it["delta"] for r in results for it in r["items"]]
        totals = [(r["total_after"] or 0) - (r["total_before"] or 0) for r in results]
        return {"sessions": len(results), "items": len(deltas),
                "item_delta_mean": round(statistics.fmean(deltas), 2) if deltas else None,
                "item_delta_sd": round(statistics.pstdev(deltas), 2) if len(deltas) > 1 else None,
                "total_delta_mean": round(statistics.fmean(totals), 2) if totals else None,
                "status_changes": sum(1 for r in results for it in r["items"] if "→" in it["status"])}
    if stage == "judge":
        turns = [t for r in results for t in r["turns"]]
        return {"sessions": len(results), "turns": len(turns),
                "flipped": sum(1 for t in turns if t["flipped"]),
                "score_delta_mean": round(statistics.fmean([(t["score_after"] or 0) - (t["score_before"] or 0) for t in turns]), 2) if turns else None}
    return {"sessions": len(results),
            "n_before": sum(r["n_before"] for r in results), "n_after": sum(r["n_after"] for r in results),
            "kept": sum(len(r["kept_nodes"]) for r in results), "dropped": sum(len(r["dropped_nodes"]) for r in results),
            "new": sum(len(r["new_nodes"]) for r in results)}


def to_markdown(stage: str, summary: dict, results: list[dict], llm: str | None) -> str:
    lines = [f"# 재생 diff · {stage} · {datetime.now():%Y-%m-%d %H:%M} · llm={llm or 'env'}", "",
             "| " + " | ".join(summary) + " |", "|" + "---|" * len(summary),
             "| " + " | ".join(str(v) for v in summary.values()) + " |", ""]
    for r in results:
        lines.append(f"## {r['session_id']} — {r['title']} (그때 코드 {r['code_before'] or '?'})")
        if stage == "rubric":
            lines += [f"총점 {r['total_before']} → {r['total_after']}", "",
                      "| no | 항목 | 전 | 후 | Δ | 상태 |", "|---|---|---|---|---|---|"]
            lines += [f"| {it['no']} | {it['name']} | {it['before']} | {it['after']} | {it['delta']:+} | {it['status']} |"
                      for it in r["items"] if it["delta"] or "→" in it["status"]]
        elif stage == "judge":
            lines += ["| 질문 | 답 | 전 | 후 | 점수 |", "|---|---|---|---|---|"]
            lines += [f"| {t['question_id']} | {t['answer']} | {t['verdict_before']} | {t['verdict_after']}{' ⚠' if t['flipped'] else ''} | {t['score_before']}→{t['score_after']} |"
                      for t in r["turns"]]
        else:
            lines += [f"질문 {r['n_before']} → {r['n_after']} · 유지 {len(r['kept_nodes'])} · 빠짐 {r['dropped_nodes']} · 새로 {r['new_nodes']}"]
            lines += [f"- {q}" for q in r["questions_after"]]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=STAGES, required=True)
    ap.add_argument("--data-dir", type=Path, default=ROOT / "var" / "data")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD 이후 업로드만")
    ap.add_argument("--limit", type=int, default=5, help="최신부터 몇 세션 (LLM 과금)")
    ap.add_argument("--llm", default=None)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    archive = SessionArchive(args.data_dir)
    recs = [r for r in archive.iter_consented() if r.uploaded_at >= _since_epoch(args.since)]
    recs = list(reversed(recs))[: args.limit]
    results = []
    for rec in recs:
        t0 = time.time()
        out = REPLAY[args.stage](archive, rec, args.llm)
        if out is None:
            print(f"  - {rec.session_id} 건너뜀 (그때 산출물이 없어요)")
            continue
        results.append(out)
        print(f"  ✓ {rec.session_id} {rec.title[:24]:<24} {time.time() - t0:.1f}s")
    summary = summarize(args.stage, results)
    print(json.dumps(summary, ensure_ascii=False))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = OUT_DIR / f"{stamp}_{args.stage}{'_' + args.tag if args.tag else ''}"
    base.with_suffix(".json").write_text(json.dumps({"stage": args.stage, "llm": args.llm, "summary": summary,
                                                     "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    base.with_suffix(".md").write_text(to_markdown(args.stage, summary, results, args.llm), encoding="utf-8")
    print(f"저장: {base.relative_to(ROOT)}.md / .json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
