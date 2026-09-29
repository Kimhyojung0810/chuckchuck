"""
판정(F-09)·코칭 사다리(F-08 힌트 · F-09 「모르겠어요」)의 WP-J3 회귀 테스트 — 대화 내용에서 찾은 결함들. LLM 은 대본이다.

- 골자 바닥: 우리 골자(「이렇게 말하면 완성이에요」)를 담은 답은 good 밑으로 내리지 않는다 · 결론 뒤집기·나열·덧붙인 주장은 예외
- 골자 자체 점검(`gist_self_check`): 우리 골자를 첫 답으로 넣으면 코드 가드가 막지 않아야 한다
- 빈틈 탐침: 골자가 「자료에 없다」 고 한 것을 결손으로 요구하지 않고, 정직한 인정의 점수는 코드가 정한다(실행마다 같다)
- 이미 말한 것을 되묻지 않는다 · 따지는 단정/함정 전제를 되물음이 사실로 깔지 않는다
- react: 자료 밖 요구 · 칭찬한 점을 다시 탓하는 문장 · 통과한 답의 물음 · 결론 뒤집기 문구
- 입장 둘 중 하나(contracts.PROBE_STANCES) — 두 사다리 공용 · 칩 답은 코드가 읽는다
- 빈칸은 질문이 이미 보여 준 말이 아니다 · 틀 골자는 가리지 않는다 · 함정 빈칸 뒤 조사

**예시는 전부 처음 보는 분야**(도서관·빵집·배터리·공유 자전거·배달·원예)로 쓴다 — 규칙은 구조로만 짰다.
"""

import json
from dataclasses import replace

import pytest

from chuckchuck import coach_stuck, judge_answer
from chuckchuck._judge_guard import covers_gist
from chuckchuck._judge_post import critique_beyond_deck, critique_of_praised, mechanism_beyond, sentences
from chuckchuck._deck_claims import deck_from_slidedoc
from chuckchuck._probe_stance import (
    demands_gap,
    plans_gap,
    presupposes_claim,
    probe_scaffold,
    restates_line,
    shown_in_question,
    stance_of,
    stance_pick,
    stance_prompt,
)
from chuckchuck.contracts import (
    PROBE_KINDS,
    PROBE_STANCES,
    ClaimQuote,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    Probe,
    QaTurn,
    Question,
    QuestionBasis,
    Slide,
    SlideBlock,
    SlideDoc,
    TrapPremise,
)
from chuckchuck.f08_questions import build_hint_ladder
from chuckchuck.f09_judge import (
    _FLIPPED_REACT,
    _narrow_followup,
    _scaffold_judgement,
    clear_judge_cache,
    gist_self_check,
)
from chuckchuck.providers.llm_base import LLMProvider


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.calls += 1
        return json.dumps(self.payload, ensure_ascii=False)


class ForbidLLM(LLMProvider):
    """불리면 실패 — 코드만으로 끝나야 하는 경로."""
    name = "forbid"

    def complete(self, **kw):
        raise AssertionError("LLM 을 부르면 안 되는 경로다")


def judged(**kw) -> dict:
    base = dict(verdict="partial", score=70, react="요지는 잡았어요.", summary_sentence="요지를 말했어요.",
                missing_points=[], followup="")
    base.update(kw)
    return base


def slide(no: int, text: str) -> Slide:
    return Slide(slide_no=no, title=f"{no}장", blocks=[SlideBlock(category="paragraph", text=text)])


def doc(*slides: Slide) -> SlideDoc:
    return SlideDoc(file_name="deck.pdf", total_slides=len(slides), slides=list(slides))


def node(nid: str, label: str, nos: list[int], parent: str | None = "root", depth: int = 2, weight: float = 0.5) -> ConceptNode:
    return ConceptNode(id=nid, label=label, slide_nos=nos, weight=weight, depth=depth, parent_id=parent)


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_judge_cache()
    yield
    clear_judge_cache()


# ---------------------------------------------------------------------------
# 처음 보는 분야의 덱 — 빵집 (탐침 넷)
# ---------------------------------------------------------------------------

BAKERY = doc(
    slide(1, "동네 빵집 살리기\n매장 경험보다 중요한 재방문율"),
    slide(2, "재방문율 = 맛 평가 × 대기 시간 × 매장 경험"),
    slide(3, "해결해야 할 문제\n대기 줄이 길고 포장이 느립니다.\n키오스크를 두면 포장을 빠르게 할 수 있습니다."),
    slide(4, "아침 할인\n아침 할인을 하면 출근길 손님이 늘어납니다."),
    slide(5, "재료 원칙\n유기농 밀가루만 쓰면 모든 손님이 만족합니다."),
    slide(6, "주의\n동네마다 입맛이 다를 수 있으니 시식을 권합니다."),
)
BAKERY_GRAPH = ConceptGraph(file_name="deck.pdf", total_slides=6, nodes=[
    node("root", "동네 빵집", [1], None, 1, 1.0), node("revisit", "재방문율", [1, 2]), node("wait", "대기 줄", [3]),
    node("pack", "포장 속도", [3]), node("morning", "아침 할인", [4]), node("flour", "유기농 밀가루", [5]),
    node("taste", "맛 평가", [2]), node("store", "매장 경험", [1, 2]),
], edges=[ConceptEdge(from_id="root", to_id=n, kind="parent")
          for n in ("revisit", "wait", "pack", "morning", "flour", "taste", "store")])

CAUSE = Probe(kind="unsupported_cause", node_ids=["morning"], evidence=[ClaimQuote(4, "아침 할인을 하면 출근길 손님이 늘어납니다.")])
CAUSE_GIST = "자료 4장의 「아침 할인을 하면 출근길 손님이 늘어납니다」에는 아직 수치나 출처가 없어요. 설문이나 통계, 비교 자료로 보강할게요."
CAUSE_Q = Question(
    id="q-cause", node_id="morning", label="아침 할인", slide_nos=[4], evidence_slide_no=4,
    evidence_quote="아침 할인을 하면 출근길 손님이 늘어납니다.",
    question="「아침 할인을 하면 출근길 손님이 늘어납니다」라고 했는데, 그렇게 볼 수 있는 근거는 무엇인가요?",
    answer_gist=CAUSE_GIST,
    basis=QuestionBasis(source="unsupported_cause", probe=CAUSE, checks=["probe_evidence_quote", "gist_template", "gist_probe_code"]),
)
UNSOLVED = Probe(kind="unsolved", node_ids=["wait", "pack"],
                 evidence=[ClaimQuote(3, "해결해야 할 문제"), ClaimQuote(3, "키오스크를 두면 포장을 빠르게 할 수 있습니다.")])
UNSOLVED_GIST = ("대기 줄을 개선하는 방법은 아직 자료에 없어요 — 포장 속도에는 「키오스크를 두면 포장을 빠르게 할 수 있습니다」라는 해결책을 "
                 "냈지만 대기 줄은 아직 비어 있어요. 이 부분은 앞으로 보완할게요.")
UNSOLVED_Q = Question(
    id="q-unsolved", node_id="wait", label="대기 줄", slide_nos=[3], evidence_slide_no=3, evidence_quote="해결해야 할 문제",
    question="대기 줄을 개선하기 위한 구체적 방안은 무엇인가요?", answer_gist=UNSOLVED_GIST,
    basis=QuestionBasis(source="unsolved", probe=UNSOLVED, checks=["probe_evidence_quote", "gist_probe_code"]),
)
ABS = Probe(kind="absolute_boundary", node_ids=["flour"], evidence=[ClaimQuote(5, "유기농 밀가루만 쓰면 모든 손님이 만족합니다.")])
ABS_GIST = ("자료 5장의 「유기농 밀가루만 쓰면 모든 손님이 만족합니다」는 모든 경우에 그렇다고 단정할 수는 없어요. "
            "자료 6장에도 「동네마다 입맛이 다를 수 있으니 시식을 권합니다」라고 적었어요. 자료가 보여 준 범위 안에서만 그렇게 말할 수 있어요.")
ABS_Q = Question(
    id="q-abs", node_id="flour", label="유기농 밀가루", slide_nos=[5], evidence_slide_no=5,
    evidence_quote="유기농 밀가루만 쓰면 모든 손님이 만족합니다.",
    question="유기농 밀가루만 쓰면 모든 손님이 만족한다는 단정이 맞지 않는 경우는 무엇인가요?", answer_gist=ABS_GIST,
    basis=QuestionBasis(source="absolute_boundary", probe=ABS, checks=["probe_evidence_quote", "gist_probe_code"]),
)
TENSION = Probe(kind="tension", node_ids=["revisit", "store"],
                evidence=[ClaimQuote(1, "매장 경험보다 중요한 재방문율"), ClaimQuote(2, "재방문율 = 맛 평가 × 대기 시간 × 매장 경험")])
TENSION_GIST = ("매장 경험도 재방문율의 요소예요 — 「재방문율 = 맛 평가 × 대기 시간 × 매장 경험」. 그래서 「매장 경험보다 중요한 재방문율」은 "
                "매장 경험 하나만 보지 말고 요소 전체를 함께 봐야 한다는 뜻이에요.")
TENSION_Q = Question(
    id="q-tension", node_id="revisit", label="재방문율", slide_nos=[1, 2], evidence_slide_no=2,
    evidence_quote="재방문율 = 맛 평가 × 대기 시간 × 매장 경험",
    question="매장 경험도 재방문율의 요소인데, 재방문율이 매장 경험보다 중요하다는 건 어떤 뜻인가요?", answer_gist=TENSION_GIST,
    basis=QuestionBasis(source="tension", probe=TENSION, checks=["probe_evidence_quote", "gist_probe_code"]),
)


# ---------------------------------------------------------------------------
# A1. 골자 바닥 · 골자 자체 점검
# ---------------------------------------------------------------------------

def test_골자를_글자_그대로_말한_답은_LLM_이_부분_점수를_줘도_good():
    # 09-30 standard 실측의 꼴: 「…다만 구체적인 수치나 출처가 아직 제시되지 않아 근거가 부족해요」 partial 70 (골자를 그대로 말했다)
    llm = ScriptedLLM(judged(score=70, react="아침 할인 설명은 정확해요. 다만 구체적인 수치나 출처가 아직 제시되지 않아 근거가 부족해요.",
                             missing_points=["구체적인 수치나 출처"], followup="어떤 통계가 있나요?"))
    v = judge_answer(CAUSE_Q, CAUSE_GIST, graph=BAKERY_GRAPH, slidedoc=BAKERY, llm=llm)
    assert v.verdict == "good" and v.score >= 80 and v.mastered and not v.followup
    assert "다만" not in v.react and "부족" not in v.react and v.missing_points == []


def test_단정_탐침의_골자는_인용_안의_때마다에서_갈라져도_되풀이로_막히지_않는다():
    # 09-30 standard 3d12c92: 「「매매할 때마다 수수료·세금은 반드시 발생」은 …단정할 수는 없어요」 가 「자료의 단정을 다시 말했어요」 55
    probe = Probe(kind="absolute_boundary", node_ids=["x"], evidence=[ClaimQuote(2, "주문할 때마다 포장 용기는 반드시 새로 쓴다")])
    gist = "자료 2장의 「주문할 때마다 포장 용기는 반드시 새로 쓴다」는 모든 경우에 그렇다고 단정할 수는 없어요."
    assert restates_line(gist, probe) == ""
    assert restates_line("주문할 때마다 포장 용기는 반드시 새로 쓴다고 해요. 이건 추가 확인이 필요해요.", probe) == "absolute_boundary"
    assert restates_line("주문할 때마다 포장 용기는 반드시 새로 쓴다고 단정할 수는 없어요.", probe) == ""   # 인용절을 받는 서술어가 경계다


def test_골자를_담아도_결론을_뒤집거나_낱말만_늘어놓거나_지어낸_주장을_보태면_바닥이_없다():
    llm = ScriptedLLM(judged(score=70))
    flipped = judge_answer(CAUSE_Q, CAUSE_GIST + " 그러니까 결론은 반대예요 — 아침 할인은 이 결과와 관계가 없어요.",
                           graph=BAKERY_GRAPH, slidedoc=BAKERY, llm=llm)
    assert not flipped.passed and flipped.guard == "self_opposed" and flipped.react == _FLIPPED_REACT
    listed = judge_answer(CAUSE_Q, "아침, 할인, 출근길, 손님, 수치, 출처, 설문, 통계, 비교, 보강", graph=BAKERY_GRAPH, slidedoc=BAKERY, llm=llm)
    assert not listed.passed
    extra = judge_answer(CAUSE_Q, CAUSE_GIST + " 그리고 경쟁 업체들이 가격 담합을 해서 우리 매출이 세 배 늘었어요.",
                         graph=BAKERY_GRAPH, slidedoc=BAKERY, llm=llm)
    assert extra.verdict != "good"                     # 골자 밖 주장을 더 한 답은 LLM 판정에 맡긴다


def test_LLM_이_wrong_을_주면_골자를_거의_그대로_담아야_바닥이_선다():
    llm = ScriptedLLM(judged(verdict="wrong", score=30))
    half = judge_answer(CAUSE_Q, "그 말에는 아직 수치나 출처가 없어요. 설문으로 보강할게요.", graph=BAKERY_GRAPH, slidedoc=BAKERY, llm=llm)
    whole = judge_answer(CAUSE_Q, CAUSE_GIST, graph=BAKERY_GRAPH, slidedoc=BAKERY, llm=llm)
    assert whole.verdict == "good"
    assert half.verdict in ("good", "partial")         # 빈틈 인정 + 다짐 — 빈틈 탐침 규칙이 정한다(아래)


def test_골자를_덮는가_잣대는_부정을_뒤집으면_덮은_것이_아니다():
    assert covers_gist(CAUSE_GIST, CAUSE_GIST)
    assert covers_gist("그 말에는 아직 수치나 출처가 없어요. 설문이나 통계로 보강할게요.", CAUSE_GIST)
    assert not covers_gist("그 말에는 수치나 출처가 충분히 있어요. 설문이나 통계, 비교 자료로 보강했어요.", CAUSE_GIST)
    assert not covers_gist("아침 할인을 하면 출근길 손님이 늘어난다고 해요. 이건 추가 확인이 필요해요.", CAUSE_GIST)


def test_골자_자체_점검은_코드_골자에_가드가_안_걸리고_되풀이_골자에는_걸린다():
    for q in (CAUSE_Q, UNSOLVED_Q, ABS_Q, TENSION_Q):
        assert gist_self_check(q, slidedoc=BAKERY, graph=BAKERY_GRAPH) == "", q.id
    # 탐침이 따지는 줄을 되풀이한 LLM 골자(코드 골자가 아니다) — 우리가 보여 주면 우리 가드가 떨군다: 그것을 센다
    bad = Question(id="q-bad", node_id="flour", label="유기농 밀가루", slide_nos=[5], evidence_slide_no=5,
                   evidence_quote=ABS_Q.evidence_quote, question=ABS_Q.question,
                   answer_gist="유기농 밀가루만 쓰면 모든 손님이 만족해요.",
                   basis=QuestionBasis(source="absolute_boundary", probe=ABS, checks=["probe_evidence_quote"]))
    assert gist_self_check(bad, slidedoc=BAKERY, graph=BAKERY_GRAPH) == "restated"


def test_절_없는_명사구_골자를_그대로_말한_답은_나열로_깎지_않고_낱말만_늘어놓으면_깎는다():
    # 09-30 WP-J3 quick 골자 자체 점검: 「…을 직관적으로 표현한 프로젝트명」 같은 명사구 골자가 나열 가드(절 없음)에 걸렸다
    q = Question(id="q-np", node_id="revisit", label="재방문율", slide_nos=[2], evidence_slide_no=2,
                 evidence_quote="재방문율 = 맛 평가 × 대기 시간 × 매장 경험", question="이 발표에서 재방문율은 무엇인가요?",
                 answer_gist="맛 평가·대기 시간·매장 경험을 곱한 값으로 매기는 재방문 지표")
    assert gist_self_check(q, slidedoc=BAKERY, graph=BAKERY_GRAPH) == ""
    llm = ScriptedLLM(judged(score=75))
    same = judge_answer(q, q.answer_gist, graph=BAKERY_GRAPH, slidedoc=BAKERY, llm=llm)
    assert same.verdict == "good" and same.guard == ""
    for listed in ("맛 평가, 대기 시간, 매장 경험, 재방문 지표", "맛 평가, 대기 시간, 매장 경험, 곱한 값, 재방문 지표"):
        v = judge_answer(q, listed, graph=BAKERY_GRAPH, slidedoc=BAKERY, llm=llm)
        assert v.guard == "list" and not v.passed, listed


# ---------------------------------------------------------------------------
# A2. 빈틈 탐침 — 자료에 없는 것을 요구하지 않고, 정직한 인정은 코드가 매긴다
# ---------------------------------------------------------------------------

HONEST = "자료에는 그 내용이 나와 있지 않아요. 자료가 말하는 건 키오스크로 포장을 빠르게 한다는 데까지예요."
HONEST_PLAN = HONEST + " 그래서 줄 서는 시간을 재서 보완할게요."


def test_빈칸_탐침에서_골자가_없다고_한_해결책은_결손으로_요구하지_않는다():
    assert demands_gap("대기 줄을 개선하기 위한 구체적 방안", UNSOLVED_Q, ["포장 속도"])
    assert not demands_gap("대기 줄을 앞으로 어떻게 보완할지", UNSOLVED_Q, ["포장 속도"])      # 채울 계획은 요구해도 된다
    assert not demands_gap("포장 속도 해결 방안", UNSOLVED_Q, ["포장 속도"])                    # 해결책이 붙은 다른 요소
    assert not demands_gap("대기 줄 방법이 없다는 점", UNSOLVED_Q, ["포장 속도"])              # 빈틈 인정
    assert demands_gap("구체적인 사례나 비교 자료", CAUSE_Q)
    llm = ScriptedLLM(judged(score=70, missing_points=["대기 줄을 개선하기 위한 구체적 방안"],
                             followup="대기 줄을 개선하기 위한 구체적 방안 — 이 부분은 어떻게 봐요?"))
    v = judge_answer(UNSOLVED_Q, HONEST, graph=BAKERY_GRAPH, slidedoc=BAKERY, llm=llm)
    assert not any("구체적 방안" in p for p in v.missing_points)
    assert not any("구체적 방안" in h for h in v.hints)


def test_정직한_빈틈_인정의_점수는_LLM_점수와_상관없이_같다():
    got = set()
    for score in (50, 55, 70, 75):
        v = judge_answer(UNSOLVED_Q, HONEST, graph=BAKERY_GRAPH, slidedoc=BAKERY,
                         llm=ScriptedLLM(judged(score=score, missing_points=["대기 줄을 개선하기 위한 구체적 방안"])))
        got.add((v.verdict, v.score))
        assert "보완" in v.followup and "있었나요" not in v.followup       # 인정은 했다 — 채울 계획을 묻는다
    assert got == {("partial", 70)}
    plan = {judge_answer(UNSOLVED_Q, HONEST_PLAN, graph=BAKERY_GRAPH, slidedoc=BAKERY,
                         llm=ScriptedLLM(judged(score=s))).verdict for s in (50, 75)}
    assert plan == {"good"}
    assert plans_gap("다음 달부터 번호표를 도입해 볼 거예요.") and not plans_gap("어떤 자료로 보강할지 말하는 게 답이에요.")


# ---------------------------------------------------------------------------
# A3·A4. 되물음 — 이미 말한 것을 되묻지 않는다 · 따지는 단정/함정 전제를 깔지 않는다
# ---------------------------------------------------------------------------

def test_자료에_없다고_한_사람에게_자료에_있었는지_되묻지_않는다():
    q = Question(id="q-plain", node_id="pack", label="포장 속도", slide_nos=[3], evidence_slide_no=3,
                 evidence_quote="키오스크를 두면 포장을 빠르게 할 수 있습니다.", question="포장 속도는 어떻게 높이나요?",
                 answer_gist="키오스크를 두면 포장을 빠르게 할 수 있어요.")
    prior = ["키오스크를 두면 포장이 빨라진다고 봐요."]
    llm = ScriptedLLM(judged(score=60, missing_points=["포장 인력 배치"], followup=""))
    v = judge_answer(q, "인력 배치 이야기는 자료에 없어요.", graph=BAKERY_GRAPH, slidedoc=BAKERY, prior_answers=prior, llm=llm)
    assert "있었나요, 없었나요" not in v.followup


def test_단정_탐침의_되물음은_그_단정을_사실로_깔지_않는다():
    fu = "유기농 밀가루 외에 모든 손님이 만족하도록 하기 위해 고려해야 할 다른 조건은 무엇인가요?"
    assert presupposes_claim(fu, ABS_Q)
    assert not presupposes_claim("모든 손님이 만족한다는 말이 늘 맞을까요?", ABS_Q)
    assert not presupposes_claim("모든 손님이 만족하지 않는 경우는 언제인가요?", ABS_Q)
    v = judge_answer(ABS_Q, "밀가루가 좋아도 입맛이 다른 손님이 있어요.", graph=BAKERY_GRAPH, slidedoc=BAKERY,
                     llm=ScriptedLLM(judged(score=65, followup=fu)))
    assert v.followup != fu and "위해" not in v.followup


def test_함정_질문의_되물음은_틀린_전제를_사실로_깔지_않는다():
    tp = TrapPremise(kind="number", premise="아침 할인율이 30%", fact="아침 할인율은 20%", slide_no=4, wrong=["30%"], right=["20%"])
    q = Question(id="q-trap", node_id="morning", label="아침 할인", slide_nos=[4], evidence_slide_no=4,
                 question="자료에서 「아침 할인율이 30%」라고 했는데, 이 수치가 무엇을 보여 주는지 설명해 주세요.",
                 answer_gist="질문의 전제와 달리, 자료 4장은 「아침 할인율은 20%」라고 해요.", trap=True, trap_premise=tp)
    v = judge_answer(q, "할인 덕분에 손님이 많아졌어요.", graph=BAKERY_GRAPH, slidedoc=BAKERY,
                     llm=ScriptedLLM(judged(score=60, followup="30% 할인이 손님 수에 어떤 영향을 줬나요?")))
    assert "30%" not in v.followup


# ---------------------------------------------------------------------------
# A5·A6·(d). react — 자료 밖 요구 · 칭찬한 점을 다시 탓하기 · 통과한 답의 물음 · 결론 뒤집기
# ---------------------------------------------------------------------------

def test_react_의_지적_문장이_자료_밖을_요구하면_빼고_칭찬은_남긴다():
    deck = deck_from_slidedoc(BAKERY)
    assert critique_beyond_deck("다만 대기 줄과 포장 속도 간의 상호작용에 대한 설명이 조금 더 구체적이면 좋겠어요.", deck, "대기 줄")
    assert not critique_beyond_deck("키오스크로 포장을 빠르게 한다는 점은 정확히 짚었어요.", deck, "키오스크 포장")
    llm = ScriptedLLM(judged(score=60, react="키오스크로 포장을 빠르게 한다는 점은 정확히 짚었어요. 다만 직원 복지와 형평성 문제에 대한 "
                                             "설명이 부족해요."))
    v = judge_answer(UNSOLVED_Q, "키오스크를 두면 포장이 빨라져요.", graph=BAKERY_GRAPH, slidedoc=BAKERY, llm=llm)
    assert "형평성" not in v.react and "키오스크" in v.react


def test_칭찬한_점을_다시_탓하는_지적은_뺀다():
    react = ("모든 손님이 만족한다는 말에 조건이 붙는다는 점은 정확히 짚었어요. 다만 모든 손님이 만족한다는 말에 조건이 붙는다는 점을 "
             "구체적으로 설명하지 않아 아쉬워요.")
    said = "모든 손님이 만족한다는 말에는 조건이 붙어요. 입맛이 다를 수 있어요."
    ss = sentences(react)
    assert [critique_of_praised(s, ss, said) for s in ss] == [False, True]
    assert not critique_of_praised("다만 가격 이야기는 하지 않았어요.", ss, said)


def test_통과한_답의_react_에는_물음이_없다():
    llm = ScriptedLLM(judged(verdict="good", score=85,
                             react="요소를 정확히 짚었어요. 그럼 재방문율이 더 중요하다는 건 어떤 뜻인지 설명해 줄래요?"))
    v = judge_answer(TENSION_Q, TENSION_GIST, graph=BAKERY_GRAPH, slidedoc=BAKERY, llm=llm)
    assert v.passed and "?" not in v.react and v.react


# ---------------------------------------------------------------------------
# B7. 입장 둘 중 하나 (contracts.PROBE_STANCES) — 두 사다리 공용 · 칩 답은 코드가 읽는다
# ---------------------------------------------------------------------------

def test_입장_표는_탐침_종류만_쓰고_보기_둘에_맞는_쪽이_하나다():
    assert set(PROBE_STANCES) <= set(PROBE_KINDS) and "sibling_priority" not in PROBE_STANCES
    for kind, st in PROBE_STANCES.items():
        assert len(st.choices) == 2 and st.correct in st.choices and st.wrong in st.choices and st.wrong != st.correct, kind
        assert st.ask.endswith("?") and all(c.endswith("요") for c in st.choices), kind       # 해요체 칩


@pytest.mark.parametrize("q, correct", [(ABS_Q, "조건이 붙어요"), (UNSOLVED_Q, "아직 비어 있었어요"),
                                        (CAUSE_Q, "아직 비어 있었어요"), (TENSION_Q, "전체와 일부예요")])
def test_탐침_질문의_모르겠어요_첫_단계는_입장_둘_중_하나(q, correct):
    deck_text = " ".join(s.raw_text for s in BAKERY.slides)
    followup, choices = _narrow_followup({"followup": "'부하' 쪽인가요, '완전히' 쪽인가요?", "choices": ["부하", "완전히"]},
                                         q, BAKERY_GRAPH, deck_text)
    assert correct in choices and len(choices) == 2 and "쪽인가요" not in followup
    j = coach_stuck(q, graph=BAKERY_GRAPH, slidedoc=BAKERY, llm=ScriptedLLM({"react": "괜찮아요.", "followup": "", "choices": []}))
    assert j.choices == choices


def test_입장_칩_답은_LLM_없이_맞는_쪽은_다음_걸음_틀린_쪽은_바로잡음():
    turns = [QaTurn(question_id=ABS_Q.id, question=ABS_Q.question, answer="(모르겠어요)", gave_up=True)]
    right = judge_answer(ABS_Q, "조건이 붙어요", graph=BAKERY_GRAPH, slidedoc=BAKERY, history=turns, llm=ForbidLLM())
    assert right.verdict == "partial" and not right.passed and right.react.startswith("맞아요")
    assert "자료 6장" in right.followup and "완전히" not in right.followup          # 제한 조건이 적힌 장을 가리킨다(줄은 말하지 않는다)
    wrong = judge_answer(ABS_Q, "늘 맞아요", graph=BAKERY_GRAPH, slidedoc=BAKERY, history=turns, llm=ForbidLLM())
    assert wrong.verdict == "wrong" and "조건이 붙어요" in wrong.react
    gap = judge_answer(UNSOLVED_Q, "아직 비어 있었어요", graph=BAKERY_GRAPH, slidedoc=BAKERY, llm=ForbidLLM())
    assert gap.react.startswith("맞아요") and "보완" in gap.followup and "있었나요" not in gap.followup
    assert stance_pick("네 조건이 붙어요", ABS_Q) == "correct" and stance_pick("조건이 붙는 말인데 입맛이 달라요", ABS_Q) == ""


def test_형제_우선순위_탐침은_입장이_없고_가린_낱말_쌍도_쓰지_않는다():
    sib = Probe(kind="sibling_priority", node_ids=["taste", "store"], evidence=[ClaimQuote(2, "재방문율 = 맛 평가 × 대기 시간 × 매장 경험")])
    q = Question(id="q-sib", node_id="taste", label="맛 평가", slide_nos=[2], evidence_slide_no=2,
                 evidence_quote="재방문율 = 맛 평가 × 대기 시간 × 매장 경험", question="맛 평가와 매장 경험 중 하나만 챙길 수 있다면 어느 쪽인가요?",
                 answer_gist="맛 평가와 매장 경험은 둘 다 필요해요.", hint="자료가 두 요소 사이의 우선순위를 직접 말한 곳이 있는지부터 찾아보세요.",
                 basis=QuestionBasis(source="sibling_priority", probe=sib, checks=["gist_probe_code"]))
    assert stance_of(q) is None and stance_prompt(q) is None
    followup, choices = _narrow_followup({"followup": "'대기' 쪽인가요, '맛' 쪽인가요?", "choices": ["대기", "맛"]}, q, BAKERY_GRAPH, "")
    assert choices == [] and followup == q.hint


# ---------------------------------------------------------------------------
# B8·B9. 빈칸 — 질문이 보여 준 말은 가리지 않는다 · 탐침은 제한 조건·식의 나머지·입장 · 틀 골자는 안 가린다 · 조사
# ---------------------------------------------------------------------------

def _blanked(followup: str, gist_or_line: str) -> str:
    body = followup.split("빈칸을 채워 보세요: ", 1)[1]
    return body


def test_빈칸_탐침의_힌트는_질문이_부른_개념_이름을_가리지_않는다():
    ladder = build_hint_ladder(UNSOLVED_Q)
    blank = next(h for h in ladder if h.startswith("빈칸을 채워 보세요"))
    assert "___을 개선하는" not in blank and "대기 줄" in blank
    assert "'나와 있었어요' 인가요, '아직 비어 있었어요' 인가요?" in blank          # 입장 칩이 들어가는 빈칸 — 표와 같은 보기


def test_단정_탐침의_발판은_따지는_단정이_아니라_자료가_단_제한_조건을_가린다():
    deck_text = " ".join(s.raw_text for s in BAKERY.slides)
    j = _scaffold_judgement(ABS_Q, BAKERY_GRAPH, deck_text)
    assert "「___마다 입맛이 다를 수 있으니 시식을 권합니다」" in j.followup and "동네" in j.choices
    assert "모든 ___" not in j.followup and "___ 손님이 만족" not in j.followup
    text, word, _ = probe_scaffold(ABS_Q)
    assert word == "동네" and not shown_in_question("동네", ABS_Q)
    # 조건 낱말이 질문에 이미 보이면 그 낱말을 가리지 않는다 — 입장 빈칸(칩이 들어가는 틀)으로 물러선다
    shown = replace(ABS_Q, question="동네마다 다르다는 점에서, 유기농 밀가루만 쓰면 모든 손님이 만족한다는 단정이 맞지 않는 경우는 무엇인가요?")
    text2, word2, chips2 = probe_scaffold(shown)
    assert word2 != "동네" and "___마다" not in text2 and chips2 == ["늘 맞아요", "조건이 붙어요"]
    assert build_hint_ladder(ABS_Q)[-2].startswith("빈칸을 채워 보세요: 자료 6장은 「___마다")


def test_긴장_탐침의_발판은_질문에_없는_식의_요소를_가린다():
    deck_text = " ".join(s.raw_text for s in BAKERY.slides)
    j = _scaffold_judgement(TENSION_Q, BAKERY_GRAPH, deck_text)
    assert "「재방문율 = ___ × 대기 시간 × 매장 경험」" in j.followup and "맛 평가" in j.choices and len(j.choices) == 2
    assert not shown_in_question("맛 평가", TENSION_Q, quotes=False)
    assert not {"대기 시간", "매장 경험"} & set(j.choices)          # 오답이 빈칸 옆에 이미 보이는 요소면 고를 거리가 아니다


def test_보통_질문의_발판도_질문의_낱말을_가리지_않는다():
    q = Question(id="q-plain2", node_id="pack", label="포장 속도", slide_nos=[3], evidence_slide_no=3,
                 evidence_quote="키오스크를 두면 포장을 빠르게 할 수 있습니다.", question="키오스크는 포장에 어떤 도움이 되나요?",
                 answer_gist="키오스크를 두면 포장을 빠르게 할 수 있고 대기 줄도 줄어들어요.")
    j = _scaffold_judgement(q, BAKERY_GRAPH, " ".join(s.raw_text for s in BAKERY.slides))
    if j is not None:
        body = j.followup.split("빈칸을 채워 보세요: ", 1)[1]
        before, after = body.split("___", 1)
        filled = next((c for c in j.choices if (before + c + after.split(" — ")[0]).replace(" ", "")
                       in q.answer_gist.replace(" ", "")), "")
        assert filled and not shown_in_question(filled, q)
    blank = next((h for h in build_hint_ladder(q) if h.startswith("빈칸을 채워 보세요")), "")
    assert "___를 두면" not in blank and "___ 두면" not in blank


def test_보통_질문의_발판_정답은_자료에서_찾을_수_있는_명사다():
    # 09-30 WP-J3 quick: 질문 낱말을 빼고 나면 골자에만 있는 말(「독서 경험의 ___을 결정해요」 의 「수준」)·용언(「두면」)이 빈칸에 남았다
    deck_text = " ".join(s.raw_text for s in BAKERY.slides)
    for gist in ("키오스크 덕분에 포장 속도의 효율이 올라가요.", "키오스크를 두면 포장이 빨라지고 대기 줄도 짧아져요."):
        q = Question(id="q-deck", node_id="pack", label="포장 속도", slide_nos=[3], evidence_slide_no=3,
                     evidence_quote="키오스크를 두면 포장을 빠르게 할 수 있습니다.", question="키오스크와 포장 속도는 어떤 관계인가요?",
                     answer_gist=gist)
        j = _scaffold_judgement(q, BAKERY_GRAPH, deck_text)
        if j is not None:
            assert not ({"효율", "덕분", "두면", "빠르게"} & set(j.choices)), j.choices
            assert all(c.replace(" ", "") in deck_text.replace(" ", "") for c in j.choices), j.choices


def test_틀_골자는_가리지_않고_모르겠어요_첫_단계는_위치_단계다():
    q = Question(id="q-tpl", node_id="store", label="매장 경험", slide_nos=[1, 2], evidence_slide_no=1,
                 evidence_quote="매장 경험보다 중요한 재방문율", question="매장 경험이 이 발표에서 왜 중요한지 설명해 주세요.",
                 answer_gist="자료는 이렇게 말해요 — 매장 경험보다 중요한 재방문율 · 재방문율 = 맛 평가 × 대기 시간 × 매장 경험 (1, 2장)",
                 hint="1, 2장에 이 개념을 둔 이유부터 떠올려 보세요",
                 basis=QuestionBasis(source="core_weight", checks=["fallback_template", "gist_template"]))
    deck_text = " ".join(s.raw_text for s in BAKERY.slides)
    followup, choices = _narrow_followup({"followup": "'순서' 쪽인가요, '재방문' 쪽인가요?", "choices": ["순서", "재방문"]},
                                         q, BAKERY_GRAPH, deck_text)
    assert choices == [] and followup == q.hint
    j = _scaffold_judgement(q, BAKERY_GRAPH, deck_text)
    assert j is None or ("이렇게 말해요" not in j.followup and "(1, 2장)" not in j.followup and "「" in j.followup)
    assert not any(h.startswith("빈칸을 채워 보세요") for h in build_hint_ladder(q))


def test_함정_힌트_빈칸_뒤_조사는_사실_줄의_받침을_따른다():
    tp = TrapPremise(kind="number", premise="포장 불량률은 연 3.1%p 낮음", fact="포장 불량률은 연 4.8%p 낮음", slide_no=3,
                     wrong=["3.1%p"], right=["4.8%p"])
    q = Question(id="q-trap2", node_id="pack", label="포장 속도", slide_nos=[3], evidence_slide_no=3,
                 question="자료에서 「포장 불량률은 연 3.1%p 낮음」이라고 했는데, 이 수치가 무엇을 보여 주는지 설명해 주세요.",
                 answer_gist="질문의 전제와 달리, 자료 3장은 「포장 불량률은 연 4.8%p 낮음」이라고 해요.", trap=True, trap_premise=tp)
    blank = next(h for h in build_hint_ladder(q) if h.startswith("빈칸을 채워 보세요"))
    assert blank.endswith("「포장 불량률은 연 ___ 낮음」이라고 해요.")


# ---------------------------------------------------------------------------
# (c) 원리·메커니즘 요구 · 결론 줄만 옮긴 근거 답
# ---------------------------------------------------------------------------

def test_자료에_없는_원리_설명을_요구하는_결손과_되물음은_버린다():
    deck = deck_from_slidedoc(BAKERY)
    assert mechanism_beyond("키오스크가 포장을 빠르게 하는 구체적인 메커니즘", deck) == "메커니즘"
    q = Question(id="q-plain3", node_id="pack", label="포장 속도", slide_nos=[3], evidence_slide_no=3,
                 evidence_quote="키오스크를 두면 포장을 빠르게 할 수 있습니다.", question="포장 속도는 어떻게 높이나요?",
                 answer_gist="키오스크를 두면 포장을 빠르게 할 수 있어요.")
    llm = ScriptedLLM(judged(score=60, missing_points=["키오스크가 포장을 빠르게 하는 구체적인 메커니즘"],
                             followup="키오스크가 왜 포장을 빠르게 하는지, 그 원리를 설명해 줄래요?"))
    v = judge_answer(q, "키오스크를 두면 빨라져요.", graph=BAKERY_GRAPH, slidedoc=BAKERY, llm=llm)
    assert not any("메커니즘" in p for p in v.missing_points) and "원리" not in v.followup


def test_근거_질문에_자료의_결론_줄만_옮긴_답은_통과하지_못한다():
    from chuckchuck.contracts import QuestionBasis as QB

    q = Question(id="q-reason", node_id="revisit", label="재방문율", slide_nos=[1, 2], evidence_slide_no=1,
                 evidence_quote="결론부터: 손님은 가격이 아니라 기다림 때문에 떠난다",
                 question="재방문율이 가격보다 기다림에 달렸다는 주장의 근거는 무엇인가요?",
                 answer_gist="줄이 길수록 다시 오는 손님이 줄었다는 조사가 근거예요.",
                 basis=QB(source="core_weight", reason=[ClaimQuote(2, "줄이 10분을 넘은 날은 재방문이 절반으로 줄었다")],
                          contrast=["기다림", "가격"], contrast_quote=ClaimQuote(1, "결론부터: 손님은 가격이 아니라 기다림 때문에 떠난다")))
    deck = doc(slide(1, "결론부터: 손님은 가격이 아니라 기다림 때문에 떠난다"), slide(2, "줄이 10분을 넘은 날은 재방문이 절반으로 줄었다"))
    v = judge_answer(q, "결론부터: 손님은 가격이 아니라 기다림 때문에 떠난다", graph=BAKERY_GRAPH, slidedoc=deck,
                     llm=ScriptedLLM(judged(score=70)))
    assert not v.passed and v.guard == "reason" and v.react.startswith("자료의 결론 줄을 그대로 옮겼어요")
    ok = judge_answer(q, "줄이 10분을 넘은 날은 재방문이 절반으로 줄었어요.", graph=BAKERY_GRAPH, slidedoc=deck,
                      llm=ScriptedLLM(judged(score=75)))
    assert ok.passed
