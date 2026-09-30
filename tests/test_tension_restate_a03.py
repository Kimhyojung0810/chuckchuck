"""
긴장 탐침의 한쪽 되풀이 (2026-10-01 · 점검 A-03, docs/review/2026-10-01_QA_점검.md) — 새 낱말로 되풀이 가드를 비켜 가지 못한다.

사용자 보고(수면 덱): 「수면 시간도 수면의 질의 요소인데, 수면의 질이 수면 시간보다 중요하다는 건 어떤 뜻인가요?」 에 1장 주장만 되풀이한 답
(「…수면의 질이 매우 중요하다 … 아무리 잠을 많이 자더라도 질적이 미흡하면 피곤하다」)이 실 solar 로 partial 75 — 통과선(70) 위였다.
예전 규칙은 질문·탐침 줄에 없는 새 낱말 2개(피곤·미흡·많이)로 곧바로 「되풀이 아님」 이었다.
"""

from __future__ import annotations

import json

from chuckchuck import judge_answer
from chuckchuck._probe_stance import RESTATE_REACT, restates_line
from chuckchuck.contracts import ClaimQuote, Probe, Question, QuestionBasis, Slide, SlideBlock, SlideDoc, qa_passed
from chuckchuck.providers.llm_base import LLMProvider


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, payload: dict):
        self.payload = payload

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        return json.dumps(self.payload, ensure_ascii=False)


def slide(no: int, text: str) -> Slide:
    return Slide(slide_no=no, title=f"{no}장", blocks=[SlideBlock(category="paragraph", text=text)])


DECK = SlideDoc(file_name="sleep.pdf", total_slides=4, slides=[
    slide(1, "수면 시간보다 중요한 수면의 질\n잠을 오래 잤다고 반드시 개운한 것은 아닙니다."),
    slide(4, "수면의 질은 단순한 “시간”보다 넓은 개념입니다.\n수면의 질 =\n시간\n×\n연속성\n×\n규칙성"),
])
PROBE = Probe(kind="tension", node_ids=["sleep-quality", "sleep-time"],
              evidence=[ClaimQuote(1, "수면 시간보다 중요한 수면의 질"), ClaimQuote(4, "수면의 질 = 시간 × 연속성 × 규칙성")])
Q = Question(
    id="q01-sleep-quality", node_id="sleep-quality", label="수면의 질", slide_nos=[1, 4], evidence_slide_no=4,
    evidence_quote="수면의 질은 단순한 “시간”보다 넓은 개념입니다.",
    question="수면 시간도 수면의 질의 요소인데, 수면의 질이 수면 시간보다 중요하다는 건 어떤 뜻인가요?",
    answer_gist="수면 시간도 수면의 질의 요소예요 — 「수면의 질 = 시간 × 연속성 × 규칙성」. 그래서 「수면 시간보다 중요한 수면의 질」은"
                " 수면 시간 하나만 보지 말고 요소 전체를 함께 봐야 한다는 뜻이에요.",
    basis=QuestionBasis(source="tension", probe=PROBE, checks=["probe_evidence_quote", "gist_probe_code"]),
)
USER = ("한 번 수면을 진행했을 때 그 수면의 질이 매우 중요하다는 이유다. 아무리 잠을 많이 자더라도 수면의 질적이 미흡하게 된다면"
        " 사람은 피곤함을 느낄수밖에 없다.")


def llm_75(missing: list[str]) -> ScriptedLLM:
    """실 solar 가 이 답에 준 모양 — partial 75, 「정확히 짚었어요」 칭찬, 결손은 요소 관계."""
    return ScriptedLLM(dict(verdict="partial", score=75,
                            react="수면의 질이 중요하다는 점은 정확히 짚었어요. 다만, 자료에서 제시한 관계를 함께 언급하면 더 완전해요.",
                            summary_sentence="요지는 맞췄어요.", missing_points=missing, followup="식에서 시간은 어떤 자리에 있나요?"))


def test_보고된_답은_판정이_요소_관계를_결손으로_짚으면_되풀이로_막힌다():
    for missing in (["수면의 질 = 시간 × 연속성 × 규칙성이라는 공식"], ["수면 시간이 질 요소 중 하나라는 점"]):
        v = judge_answer(Q, USER, slidedoc=DECK, llm=llm_75(missing))
        assert not qa_passed(v.verdict, v.score), (missing, v.verdict, v.score)
        assert v.guard == "restated" and v.react == RESTATE_REACT["tension"]
        assert "정확히 짚었어요" not in v.react


def test_새_낱말로_풀어_말한_답은_판정이_다른_쪽을_짚지_않으면_그대로다():
    """새 낱말 탈출은 남는다 — 판정이 건드리지 않은 쪽을 결손으로 짚지 않았으면 풀어 말한 것으로 믿는다."""
    paraphrase = "수면 시간보다 질이 중요하다는 건 오래 자도 중간에 깨거나 매일 자는 시간이 다르면 피곤하다는 거예요."
    good = ScriptedLLM(dict(verdict="good", score=85, react="네, 그 설명이면 충분해요.", summary_sentence="s", missing_points=[],
                            followup=""))
    assert qa_passed(*(lambda v: (v.verdict, v.score))(judge_answer(Q, paraphrase, slidedoc=DECK, llm=good)))
    assert restates_line(paraphrase, PROBE, Q.question, missing="") == ""
    assert restates_line(paraphrase, PROBE, Q.question, missing="연속성과 규칙성") == "tension"


def test_부분_전체_표지나_두_쪽_낱말을_다_말한_답은_되풀이가_아니다():
    for answer in ("수면 시간은 수면의 질을 이루는 한 부분일 뿐이라, 오래 자도 질이 낮으면 피곤해요.",
                   "수면의 질은 시간 × 연속성 × 규칙성이라서 시간은 세 요소 가운데 하나예요."):
        assert restates_line(answer, PROBE, Q.question, missing="수면의 질 = 시간 × 연속성 × 규칙성") == "", answer


def test_활용만_다른_되풀이도_한쪽_되풀이다():
    assert restates_line("수면 시간보다 수면의 질이 중요하다.", PROBE, Q.question, missing="") == "tension"


def test_골자_점검은_예전_규칙_그대로다():
    """missing 을 안 주는 호출(F-08 골자 점검)은 새 낱말 탈출을 그대로 쓴다 — 질문 만들기가 바뀌지 않게."""
    assert restates_line(USER, PROBE, Q.question) == ""
