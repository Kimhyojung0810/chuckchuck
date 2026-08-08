"""
Q&A 판정이 얼마나 무른지 재는 측정 도구입니다 (F-08 → F-09).

**고치기 전에 재려고 만들었습니다.** "정답 판정이 너무 광범위하다" 는 체감을
숫자로 바꾸지 않으면, 프롬프트를 조인 뒤에 그게 나아진 것인지 그냥 다르게
틀어진 것인지 구분할 수 없습니다.

재는 것은 **답변의 깊이별 판정 분포** 하나입니다. 같은 질문에 깊이가 다른
답을 넣고 verdict·score·mastered 가 어디서 갈리는지 봅니다.

    full      기대 답의 골자를 그대로 — good 이 나와야 맞다
    shallow   골자의 앞 절반만. 방향은 맞고 근거는 없다  ← **여기가 논점이다**
    direction 개념 이름만 부르고 내용이 없다 — wrong 이나 낮은 partial 이 맞다
    sibling   **다른 질문**의 골자. good 이 많이 나오면 판정이 무른 게 아니라
              F-08 이 답이 겹치는 질문을 만든 것이다 (질문 다양성 지표)
    unrelated 이 발표와 아무 상관 없는 문단 — wrong 이 나와야 맞다.
              여기서 good/partial 이 나오면 그게 "판정이 광범위하다" 의 실체다

`f09_judge.SYSTEM_PROMPT` 규칙 8 이 shallow 를 **70~79(통과 구간)** 으로
명시하고 있습니다. 그 지시가 실제로 몇 점을 만드는지, 그리고 그게 곧바로
`mastered`(되묻기 종료)로 이어지는지가 이 도구의 답입니다.

**주의: verdict='good' 은 점수를 우회합니다.** `qa_passed`·`qa_mastered` 가
둘 다 `verdict == "good"` 에서 단락되므로, good 이 1턴에 나오면 QA_PASS_SCORE
를 아무리 올려도 대화가 그 자리에서 끝납니다. 그래서 이 표는 score 뿐 아니라
**verdict 와 1턴 mastered 비율**을 같이 냅니다.

실행 (저장소 루트에서):

    python examples/qa_judge_probe.py                   # 질문 3개 × 답 4벌 = 12 판정
    python examples/qa_judge_probe.py --limit 2         # 더 싸게
    python examples/qa_judge_probe.py --reuse q.json    # 이미 뽑아 둔 질문 재사용

실 LLM 을 부릅니다. `.env` 가 있어야 하고 판정 한 번에 5~8초 걸립니다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chuckchuck.config import load_dotenv  # noqa: E402

load_dotenv()

from chuckchuck.contracts import (  # noqa: E402
    QA_MAX_ROUNDS,
    QA_PASS_SCORE,
    AlignmentDoc,
    ConceptGraph,
    QaTriage,
    Question,
    QuestionDoc,
    Transcript,
    qa_mastered,
)
from chuckchuck.f08_questions import build_questions  # noqa: E402
from chuckchuck.f09_judge import judge_answer  # noqa: E402

#: 측정에 쓰는 실행 기록. 그래프·정합·전사가 한 벌로 들어 있어 F-06·F-07·F-11 을
#: 다시 돌리지 않아도 된다 — 이 도구가 부르는 LLM 은 F-08 한 번과 F-09 뿐이다.
RUN_FIXTURE = ROOT / "fixtures" / "live_qa_run.json"

#: 골자를 앞 절반만 남길 때 쓰는 비율. `f08_questions._gist_fragment` 와 같은
#: 규칙이라, 화면이 3단계 힌트로 보여 주는 그 조각이 곧 이 답변이다.
SHALLOW_RATIO = 2

#: 규칙 8 이 "요지는 맞고 근거만 얕다" 에 배정한 구간의 위쪽 끝(미만).
SHALLOW_BAND_TOP = 80

DEPTHS = ("full", "shallow", "direction", "sibling", "unrelated")

#: 어느 발표에도 안 맞는 답. 문장은 그럴듯하되 이 자료의 개념과 겹치는 낱말이
#: 없어야 한다 — "판정이 내용을 보는가, 한국어 문장 꼴을 보는가" 를 가른다.
UNRELATED_ANSWER = (
    "저희 팀은 지난 분기에 물류 창고 세 곳의 재고 회전율을 비교했고, "
    "동절기 배송 지연이 반품률을 끌어올린다는 결론을 얻었습니다."
)


def _shallow(gist: str) -> str:
    """골자의 앞 절반. 방향은 맞고 근거는 없는 답 — 규칙 8 의 70~79 구간 후보다."""
    text = (gist or "").strip()
    return text[: max(1, len(text) // SHALLOW_RATIO)].rstrip()


def _answers(
    q: Question,
    others: list[Question],
    want: tuple[str, ...] = DEPTHS,
) -> list[tuple[str, str]]:
    """이 질문에 넣을 (깊이, 답변) 목록. 골자가 없는 질문은 건너뛴다."""
    gist = (q.answer_gist or "").strip()
    if not gist:
        return []
    sibling = next(
        (o.answer_gist.strip() for o in others if o.id != q.id and o.answer_gist),
        "",
    )
    by_depth = {
        "full": gist,
        "shallow": _shallow(gist),
        "direction": f"{q.label} 이 중요하다고 생각합니다",
        "sibling": sibling,
        "unrelated": UNRELATED_ANSWER,
    }
    return [(d, by_depth[d]) for d in want if by_depth.get(d)]


def _load_artifacts() -> dict:
    if not RUN_FIXTURE.exists():
        raise SystemExit(f"측정 기록이 없어요: {RUN_FIXTURE}")
    return json.loads(RUN_FIXTURE.read_text(encoding="utf-8"))["session"]["artifacts"]


def _fresh_questions(art: dict, track: str) -> QuestionDoc:
    """
    저장된 그래프·심사로 질문을 다시 뽑는다.

    기록에 든 question_doc 은 `answer_gist` 가 생기기 전 것이라 그대로 쓰면
    shallow 답을 만들 수가 없다. 채점 기준(골자)이 없는 질문으로 잰 판정은
    지금 코드의 판정이 아니다.
    """
    return build_questions(
        ConceptGraph.from_dict(art["concept_graph"]),
        QaTriage.from_dict(art["qa_triage"]),
        track=track,
        alignment=art.get("alignment_doc"),
        flow=art.get("flow_diff"),
        transcript=art.get("transcript"),
    )


def _print_table(rows: list[dict]) -> None:
    head = f"깊이별 판정 분포  (통과 임계 {QA_PASS_SCORE}점 · 되묻기 상한 {QA_MAX_ROUNDS}라운드)"
    print(f"\n{'=' * 70}\n{head}\n{'=' * 70}")
    print(f"{'깊이':<11}{'n':>3}  {'good':>5}{'partial':>8}{'wrong':>7}{'unknown':>9}  {'평균점':>7}  {'1턴에 닫힘':>10}")
    for depth in DEPTHS:
        sub = [r for r in rows if r["depth"] == depth]
        if not sub:
            continue
        n = len(sub)
        cnt = {v: sum(1 for r in sub if r["verdict"] == v) for v in ("good", "partial", "wrong", "unknown")}
        avg = sum(r["score"] for r in sub) / n
        closed = sum(1 for r in sub if r["mastered"])
        print(
            f"{depth:<11}{n:>3}  {cnt['good']:>5}{cnt['partial']:>8}{cnt['wrong']:>7}"
            f"{cnt['unknown']:>9}  {avg:>7.1f}  {closed:>5}/{n:<4}"
        )


def _print_verdict_on_shallow(rows: list[dict]) -> None:
    shallow = [r for r in rows if r["depth"] == "shallow"]
    if not shallow:
        return
    closed = sum(1 for r in shallow if r["mastered"])
    band = sum(1 for r in shallow if QA_PASS_SCORE <= r["score"] < SHALLOW_BAND_TOP)
    print(
        f"\n논점: 얕은 답 {len(shallow)}개 중 **{closed}개가 1턴에 닫혔다** — 되묻기가 안 돌았다.\n"
        f"      그중 {band}개가 규칙 8 이 지시한 {QA_PASS_SCORE}~{SHALLOW_BAND_TOP - 1} 구간에 들어왔다."
    )
    by_good = sum(1 for r in shallow if r["verdict"] == "good")
    if by_good:
        print(
            f"      ⚠ {by_good}개는 verdict='good' 으로 닫혔다 — **QA_PASS_SCORE 를 올려도"
            f" 이건 안 막힌다** (qa_mastered 가 good 에서 단락된다)."
        )


def _print_verdict_on_unrelated(rows: list[dict]) -> None:
    """무관한 답과 형제 골자는 성격이 다른 신호라 따로 읽는다."""
    for depth, label, blame in (
        ("unrelated", "무관한 답", "판정이 내용을 안 보고 있다"),
        ("sibling", "형제 골자", "F-08 이 답이 겹치는 질문을 만들었다"),
    ):
        sub = [r for r in rows if r["depth"] == depth]
        if not sub:
            continue
        passed = sum(1 for r in sub if r["passed"])
        closed = sum(1 for r in sub if r["mastered"])
        mark = "⚠ " if passed else "✓ "
        print(
            f"{mark}{label} {len(sub)}개 중 통과 {passed}개 · 1턴에 닫힘 {closed}개"
            + (f" — {blame}" if passed else "")
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="Q&A 판정 관대함 측정")
    ap.add_argument("--limit", type=int, default=3, help="측정할 질문 수 (기본 3)")
    ap.add_argument("--track", default="5", help="질문 트랙 (기본 5)")
    ap.add_argument("--reuse", help="이전에 저장한 QuestionDoc JSON 을 다시 쓴다")
    ap.add_argument("--save-questions", default="", help="뽑은 질문을 JSON 으로 남긴다")
    ap.add_argument("--out", default="", help="측정 결과를 JSON 으로 저장할 경로")
    ap.add_argument(
        "--depths",
        default=",".join(DEPTHS),
        help=f"측정할 깊이 (쉼표로 구분). 기본 {','.join(DEPTHS)}",
    )
    args = ap.parse_args()

    want = tuple(d.strip() for d in args.depths.split(",") if d.strip() in DEPTHS)
    if not want:
        raise SystemExit(f"깊이 이름이 잘못됐어요. 쓸 수 있는 값: {', '.join(DEPTHS)}")

    art = _load_artifacts()

    if args.reuse:
        doc = QuestionDoc.from_dict(json.loads(Path(args.reuse).read_text(encoding="utf-8")))
        print(f"[재사용] 질문 {len(doc.questions)}개 — {args.reuse}")
    else:
        print("[F-08] 질문을 다시 뽑는 중… (골자가 있어야 얕은 답을 만들 수 있어요)")
        doc = _fresh_questions(art, args.track)
        print(f"[F-08] 질문 {len(doc.questions)}개 · model={doc.model}")

    if args.save_questions:
        Path(args.save_questions).write_text(
            json.dumps(doc.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"       질문을 남겼어요: {args.save_questions}")

    qs = doc.questions[: args.limit]
    without_gist = [q.id for q in qs if not (q.answer_gist or "").strip()]
    if without_gist:
        print(f"  ⚠ 골자 없는 질문 {len(without_gist)}개는 건너뜁니다: {without_gist}")

    graph = ConceptGraph.from_dict(art["concept_graph"])
    alignment = AlignmentDoc.from_dict(art["alignment_doc"]) if art.get("alignment_doc") else None
    transcript = Transcript.from_dict(art["transcript"]) if art.get("transcript") else None

    rows: list[dict] = []
    for q in qs:
        for depth, answer in _answers(q, doc.questions, want):
            v = judge_answer(
                q,
                answer,
                graph=graph,
                alignment=alignment,
                transcript=transcript,
                # 1턴째다. 되묻기 없이 곧장 닫히는지가 이 측정의 논점이라
                # prior_answers 를 일부러 주지 않는다.
                prior_answers=None,
            )
            rows.append({
                "question_id": q.id,
                "label": q.label,
                "depth": depth,
                "answer": answer,
                "verdict": v.verdict,
                "score": v.score,
                "passed": v.passed,
                "mastered": v.mastered,
                "followup": bool(v.followup),
                "missing": len(v.missing_points),
                "hints": len(v.hints),
            })
            print(
                f"  {q.id:<24} {depth:<10} {v.verdict:<8} {v.score:>3}점  "
                f"{'닫힘' if v.mastered else '되물음'}"
            )

    if not rows:
        print("\n측정할 답이 없어요 — 질문에 골자(answer_gist)가 하나도 없습니다.")
        return 1

    _print_table(rows)
    _print_verdict_on_shallow(rows)
    print()
    _print_verdict_on_unrelated(rows)

    # 표의 mastered 가 서버 계약과 같은 값인지 검산한다. 어긋나면 표를 못 믿는다.
    bad = [r for r in rows if r["mastered"] != qa_mastered(r["verdict"], r["score"], 1)]
    if bad:
        print(f"\n⚠ mastered 가 qa_mastered() 와 어긋난 행 {len(bad)}개 — 계약을 먼저 확인하세요.")

    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n저장했어요: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
