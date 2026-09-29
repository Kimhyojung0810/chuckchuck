"""
F-09 판정·막힘 코칭 회귀 테스트 — 2026-09-29 두 덱 기준선(docs/review/2026-09-29_QA_근거검증/baseline.md)의
실제 질문·답을 그대로 쓴다. LLM 은 ScriptedLLM(정해 둔 응답)이고, 시험하는 것은 **코드 가드**다.

1. 함정 표시가 틀린 질문(전제 없음)에 자료대로 답하면 함정 가드가 내리지 않는다 — 동의한 답만 내린다.
2. 자료와 수치·표 서열·방향이 어긋난 답은 통과하지 못하고, react 가 그 주장을 칭찬하지 않는다 — 바꿔 말한 정답은 그대로.
3. 판정의 원본은 자료다 — 자료로 안 받쳐지는 골자는 「참고」 로 싣고 그 요소는 체크리스트에서 뺀다.
4. 「모르겠어요」 선택지는 명사 줄기만, 프롬프트 예시를 베낀 되물음·자료에 없는 선택지는 버린다.
5. 「하신·계신·주실」 높임이 새지 않는다.

덱 문장은 실제 자료에서 옮겼지만, 규칙은 덱 낱말을 모른다 — 끝의 「처음 보는 분야」 테스트가 그걸 확인한다.
"""

import json

from chuckchuck import coach_stuck, judge_answer
from chuckchuck._deck_claims import build_deck, conflicts, explicit_agreement, states_reference, support
from chuckchuck._evidence import _negated_in, mask_gist
from chuckchuck.contracts import ConceptEdge, ConceptGraph, ConceptNode, Question, Slide, SlideBlock, SlideDoc
from chuckchuck.f09_judge import _HONORIFIC_RE, _plain
from chuckchuck.providers.llm_base import LLMProvider


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, payload: dict):
        self.payload = payload
        self.prompts: list[str] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.prompts.append(user)
        return json.dumps(self.payload, ensure_ascii=False)


def slide(no: int, text: str) -> Slide:
    return Slide(slide_no=no, title=f"{no}장", blocks=[SlideBlock(category="paragraph", text=text)])


def judged(**kw) -> dict:
    base = dict(verdict="good", score=85, react="네, 그 설명이면 충분해요.", summary_sentence="총평이에요.",
                missing_points=[], followup="")
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# 수익률격차 덱 (15장 중 판정에 쓰이는 장만 — 원문 그대로)
# ---------------------------------------------------------------------------

GAP = SlideDoc(file_name="gap.pdf", total_slides=15, slides=[
    slide(1, "개인 투자자는 왜\n시장을 이기지 못하는가\n실력의 문제가 아니라 행동의 문제다 — 수익률 격차의 다섯 가지 원인"),
    slide(2, "결론부터: 격차는 종목 선택이 아니라 행동에서 만들어진다\n01\n02\n격차는 실재한다\n"
             "· 개인 평균은 지수 대비 연 4.8%p\n낮음\n· 상위 25% 그룹도 지수를 2.6%p\n하회\n·\n일부의 실수가 아닌 전반적 현상\n"
             "원인은 종목이 아니다\n· 종목 선정 능력과 수익률의 상관은\n약함\n· 매매 회전율은 수익률과 뚜렷한\n역상관\n·\n"
             "최상위 회전율 구간 평균 −3.6%\n무엇을 샀는가가 아니라, 얼마나 자주 사고팔았는가가 결과를 갈랐다"),
    slide(3, "현황 진단\n연평균 수익률 비교 (2016–2025, %)\n- Chart Type: bar chart\n| Category | Value |\n| --- | --- |\n"
             "| 시장지수 | 9 |\n| 기관 | 8 |\n| 개인 상위25% | 6 |\n| 개인 평균 | 4 |\n| 개인 하위25% | -1 |\n"
             "핵심 요지\n지수 대비 −4.8%p\n개인 평균과 시장지수의 연간 격차\n기관과의 차이는 작다\n"
             "지수 8.7% vs 기관 7.9% — 0.8%p\n상위 25%도 못 넘었다\n6.1%로 지수를 2.6%p 하회"),
    slide(5, "원인 구조\n격차를 만든 다섯 가지 행동 요인\n| Category | Profit Margin (p.p., Annual) |\n| --- | --- |\n"
             "| 거래 비용 | -0.2 |\n| 집중 투자 | -0.6 |\n| 손실 희망 | -0.8 |\n| 타이밍 실패 | -1.2 |\n| 과잉 매매 | -1.6 |\n"
             "핵심 요지\n상위 2개가 전체의 58%\n과잉 매매와 타이밍 실패에 집중\n요인 간 상호작용 존재\n과잉 매매는 거래 비용도 함께 증가"),
    slide(6, "01. 과잉 매매 — 거래를 늘릴수록 성과가 낮아졌다\n연간 회전율 구간별 평균 수익률 (%)"),
    slide(11, "반대로, 상위 성과 그룹은 무엇이 달랐는가\n상위 25% vs 하위 25% 행동 지표\n"
              "| Category | 상위 25% | 하위 25% |\n| --- | --- | --- |\n| 회전율(회) | 1 | 12 |\n| 보유(월) | 19 | 3 |\n"
              "| 중목수 | 12 | 3 |\n| 매도규칙(%) | 71 | 18 |\n핵심 요지\n회전율 8.4배 차이\n연 1.4회 vs 11.8회\n매도규칙 71% vs 18%"),
])

GAP_GRAPH = ConceptGraph(file_name="gap.pdf", total_slides=15, nodes=[
    ConceptNode(id="contrast", label="수익률 격차", slide_nos=[1, 2, 3], summary="개인 투자자와 지수의 수익률 차이", weight=1.0),
    ConceptNode(id="behavior", label="행동 요인", slide_nos=[5, 6], summary="격차를 만든 다섯 가지 행동", weight=0.8,
                parent_id="contrast"),
    ConceptNode(id="top25", label="상위 25%", slide_nos=[2, 3, 11], summary="개인 투자자 상위 그룹", weight=0.6,
                parent_id="contrast"),
    ConceptNode(id="turnover", label="회전율", slide_nos=[6], summary="매매 빈도", weight=0.5, parent_id="behavior"),
], edges=[
    ConceptEdge(from_id="contrast", to_id="behavior", kind="parent"),
    ConceptEdge(from_id="contrast", to_id="top25", kind="parent"),
    ConceptEdge(from_id="behavior", to_id="turnover", kind="parent"),
])

#: 기준선 수익률 deck_t5 1번 — 함정 표시가 붙었지만 질문에 거짓 전제가 없다.
Q_CONTRAST = Question(
    id="q01-contrast", node_id="contrast", label="수익률 격차", trap=True, slide_nos=[1, 2, 3],
    question="수익률 격차가 실력보다 행동에서 비롯되었다는 주장을 뒷받침하는 실증적 근거는 무엇인가요?",
    answer_gist="개인 평균 수익률은 시장 지수 대비 연 4.8%p 낮고, 상위 25% 그룹도 지수를 2.6%p 하회하며, "
                "종목 선정 능력과 수익률 상관이 약하다는 점이 행동 요인에서 격차가 발생했음을 실증적으로 보여줘요.",
    evidence_slide_no=1, evidence_quote="실력의 문제가 아니라 행동의 문제다 — 수익률 격차의 다섯 가지 원인",
)
Q_BEHAVIOR = Question(
    id="q02-behavior", node_id="behavior", label="행동 요인", slide_nos=[5, 6],
    question="다섯 가지 행동 요인 중 과잉 매매와 타이밍 실패가 수익률 격차에 미치는 영향의 상대적 크기는 어떻게 측정되었나요?",
    answer_gist="과잉 매매는 연간 수익률에 -1.6%p, 타이밍 실패는 -1.2%p의 영향을 미치며, 두 요인이 전체 격차의 58%를 차지해 "
                "가장 큰 영향을 보였어요.",
    evidence_slide_no=5, evidence_quote="격차를 만든 다섯 가지 행동 요인",
)
Q_TOP25 = Question(
    id="q03-top25", node_id="top25", label="상위 25%", slide_nos=[2, 3, 11],
    question="발표에서 상위 25% 개인 투자자의 수익률 격차가 어떤 행동적 요인으로 설명되는지 연결지어 설명할 수 있나요?",
    answer_gist="상위 25%는 연 1.4회만 거래하고 매도규칙을 71% 갖고 있었지만, 그래도 지수를 2.6%p 하회했어요.",
    evidence_slide_no=11, evidence_quote="상위 25% vs 하위 25% 행동 지표",
)

# probes_manual.json 의 사람이 쓴 탐침 (자료 원문만 보고 썼다)
CONTRAST_D = ("두 가지예요. 하나는 몇몇만의 문제가 아니라는 것 — 개인 평균이 지수보다 해마다 4.8%p 뒤졌고 잘한다는 윗쪽 4분의 1도 "
              "2.6%p 못 미쳤어요. 다른 하나는 원인인데, 종목을 잘 고르는 능력과 성과는 별 관계가 없었고 오히려 사고파는 횟수가 "
              "늘수록 성과가 뚜렷하게 떨어졌어요.")
CONTRAST_C = ("종목 선정 능력과 수익률의 상관이 강하게 나왔고, 회전율이 높은 구간일수록 평균 수익률이 올라가서, 좋은 종목을 "
              "자주 갈아타면 격차가 줄어든다는 게 근거예요.")
BEHAVIOR_C = "타이밍 실패가 연 1.6%p로 가장 컸고 과잉 매매는 0.2%p 정도라 영향이 작았어요. 그래서 과잉 매매보다 타이밍이 핵심이라고 봤어요."
BEHAVIOR_D = ("5장 막대그래프에서 요인마다 연 수익률을 몇 %p 깎았는지 나눠 봤어요. 너무 자주 사고판 게 1.6%p로 제일 컸고 사고팔 때를 "
              "놓친 게 1.2%p라, 이 둘을 합친 2.8%p가 전체 4.8%p 격차의 58% 정도예요.")
TOP25_C = "상위 25% 그룹은 종목 분석을 더 많이 해서 좋은 종목을 고른 덕분에 기관보다 높은 수익을 냈고, 매매 횟수는 하위 그룹과 비슷했어요."
TOP25_D = ("윗쪽 4분의 1과 아랫쪽 4분의 1은 습관이 달랐어요. 잘한 쪽은 1년에 한 번 남짓만 거래하고 19개월쯤 들고 있었고, "
           "12종목 정도로 나눠 담았고, 71%가 미리 정해 둔 팔 기준이 있었어요. 못한 쪽은 한 해 12번 가까이 거래하고 3개월만 "
           "들고 있었죠. 다만 잘한 쪽도 지수보다는 2.6%p 낮았어요.")
AGREE = "네, 맞아요. 질문한 대로예요. 그 전제가 정확해요."


# ---------------------------------------------------------------------------
# 1. 함정 — 표시가 아니라 동의를 본다
# ---------------------------------------------------------------------------

def test_전제_없는_함정_질문에_골자대로_답하면_함정_가드가_내리지_않는다():
    """기준선: 골자 그대로(a) 4/4 가 wrong 35 — LLM 이 「바로잡은 전제 없음」 으로 premise_corrected=false 를 줬다."""
    llm = ScriptedLLM(judged(premise_corrected=False))
    v = judge_answer(Q_CONTRAST, Q_CONTRAST.answer_gist, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert v.verdict == "good" and v.passed
    assert "전제" not in v.react


def test_전제_없는_함정_질문에_자료대로_바꿔_말한_정답도_내리지_않는다():
    """기준선 수익률 1번 (d) — 사람이 자료 원문만 보고 쓴 정답이 함정 가드에 wrong 35."""
    llm = ScriptedLLM(judged(verdict="partial", score=75, premise_corrected=False))
    v = judge_answer(Q_CONTRAST, CONTRAST_D, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert v.verdict == "partial" and v.score == 75 and v.passed


def test_함정_동의는_여전히_wrong_이다():
    """기준선 (t) 4/4 통과 못 함 — 그대로 지킨다."""
    llm = ScriptedLLM(judged(verdict="partial", score=70, premise_corrected=False))
    v = judge_answer(Q_CONTRAST, AGREE, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert v.verdict == "wrong" and v.score <= 35 and not v.passed
    assert v.react.startswith("질문의 전제부터")


def test_premise_corrected_가_없어도_말로_동의하면_함정_문구다():
    """기준선 수익률 rec 1번 (t): LLM 이 값을 안 줘서 함정 가드를 건너뛰고 무관 문구가 나갔다."""
    llm = ScriptedLLM(judged(verdict="partial", score=70))
    v = judge_answer(Q_CONTRAST, AGREE, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert v.verdict == "wrong" and v.react.startswith("질문의 전제부터")


def test_거짓_전제의_숫자를_되풀이한_답은_동의다():
    llm = ScriptedLLM(judged(verdict="good", score=80))          # premise_corrected 없음
    v = judge_answer(Q_TRUE_TRAP, "80%를 차지하는 건 과잉 매매가 워낙 커서 그래요", graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert v.verdict == "wrong" and not v.passed


#: 진짜 함정 — 질문에 자료와 다른 수치(80%)가 있고, 골자가 그 전제를 바로잡는다.
Q_TRUE_TRAP = Question(id="q9", node_id="behavior", label="행동 요인", trap=True, slide_nos=[5],
                       question="과잉 매매와 타이밍 실패가 격차의 80%를 차지한다고 했는데, 그 계산 근거는 무엇인가요?",
                       answer_gist="질문의 전제가 자료와 달라요 — 두 요인은 전체의 58%예요.")


def test_진짜_함정에서_바로잡지도_기대_답을_말하지도_않은_답은_함정_가드가_내린다():
    llm = ScriptedLLM(judged(verdict="partial", score=72, premise_corrected=False))
    v = judge_answer(Q_TRUE_TRAP, "두 요인이 워낙 커서 그렇다고 봤어요", graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert v.verdict == "wrong" and not v.passed and v.react.startswith("질문의 전제부터")


def test_진짜_함정을_바로잡은_답은_LLM_이_false_라고_해도_내리지_않는다():
    llm = ScriptedLLM(judged(verdict="good", score=85, premise_corrected=False))
    v = judge_answer(Q_TRUE_TRAP, "80%가 아니라 두 요인을 합쳐 전체의 58%예요", graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert v.verdict == "good" and v.passed


def test_골자가_전제를_안_바로잡는_함정_표시는_가드를_켜지_않는다():
    """09-29 벤치 held-out: 함정 질문 21/21 의 골자가 전제를 안 바로잡았다 — 거짓 전제가 없는 질문이다.
    그런 질문에서 「바로잡지 않았다」 는 흠이 아니고, 등급은 LLM 판정과 다른 가드가 정한다."""
    from chuckchuck._deck_claims import gist_corrects_premise
    assert not gist_corrects_premise(Q_CONTRAST.answer_gist, Q_CONTRAST.question)
    assert gist_corrects_premise(Q_TRUE_TRAP.answer_gist, Q_TRUE_TRAP.question)
    # 질문에도 있는 부정(「맞지 않을」)은 바로잡는 말로 세지 않는다
    assert not gist_corrects_premise("단정이 맞지 않을 수 있는 경우는 결제 방식이 섞일 때예요",
                                     "단정이 실제 결제 구조와 맞지 않을 수 있는 경우는 무엇인가요?")
    llm = ScriptedLLM(judged(verdict="partial", score=60, premise_corrected=False))
    v = judge_answer(Q_CONTRAST, "시장이 원래 개인에게 불리하게 짜여 있어서 어쩔 수 없다고 봤어요",
                     graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert v.verdict == "partial" and v.score == 60 and "전제" not in v.react


def test_기대_답_사실_판별은_질문_낱말_되읊기를_세지_않는다():
    ref = Q_CONTRAST.answer_gist
    assert states_reference(Q_CONTRAST.answer_gist, Q_CONTRAST.question, ref)
    assert states_reference(CONTRAST_D, Q_CONTRAST.question, ref)
    assert not states_reference("수익률 격차는 실력보다 행동에서 비롯됐다는 주장이 맞아요", Q_CONTRAST.question, ref)
    assert explicit_agreement(AGREE) and explicit_agreement("네, 맞아요. 질문하신 대로예요")
    assert not explicit_agreement("네, 그런데 자료는 그렇게 말하지 않아요")


def test_판정_프롬프트는_함정_표시가_틀릴_수_있다고_알린다():
    llm = ScriptedLLM(judged())
    judge_answer(Q_CONTRAST, Q_CONTRAST.answer_gist, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    from chuckchuck.f09_judge import SYSTEM_PROMPT
    assert "틀릴 수 있다" in SYSTEM_PROMPT and "premise_corrected 는 null" in SYSTEM_PROMPT
    assert "함정 질문인가: 예" in llm.prompts[0]


# ---------------------------------------------------------------------------
# 2. 자료와 어긋난 주장 — 수치 짝 · 표 서열 · 방향
# ---------------------------------------------------------------------------

def test_요인의_수치를_바꿔_붙인_답은_통과하지_못한다():
    """기준선 수익률 2번 (c) partial 75 통과 — 자료 5장 표: 타이밍 −1.2 · 과잉 매매 −1.6 · 거래 비용 −0.2."""
    llm = ScriptedLLM(judged(verdict="partial", score=75, react="요지는 잡았어요. 타이밍 실패가 크다는 점은 정확해요."))
    v = judge_answer(Q_BEHAVIOR, BEHAVIOR_C, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert not v.passed and v.score <= 55
    assert "정확" not in v.react and "자료 5장" in v.react
    assert v.guard_reason.startswith("자료 5장과 어긋난 곳")     # 09-30 §6: 가드 사유는 결손과 따로
    assert "5장" in v.followup


def test_표에서_더_낮은_쪽을_더_높다고_한_답은_통과하지_못한다():
    """기준선 수익률 3번 (c) partial 70 통과 + react 「…부분은 정확해요」 — 자료 3장 표: 기관 8 · 개인 상위25% 6."""
    llm = ScriptedLLM(judged(verdict="partial", score=70,
                             react="종목 분석을 더 많이 해서 기관보다 높은 수익을 냈다는 부분은 정확해요."))
    v = judge_answer(Q_TOP25, TOP25_C, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert not v.passed
    assert "정확" not in v.react and "자료 3장" in v.react


def test_자료와_방향이_반대인_답은_통과하지_못한다():
    llm = ScriptedLLM(judged(verdict="partial", score=72, premise_corrected=True))
    v = judge_answer(Q_CONTRAST, CONTRAST_C, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert not v.passed and "자료 2장" in v.react


def test_바꿔_말한_정답은_어긋남_가드에_걸리지_않는다():
    """기준선 (d) — 자료의 숫자를 다른 말로 짝지어 말하거나, 계산한 합(2.8%p)을 말해도 어긋남이 아니다."""
    for q, answer in ((Q_BEHAVIOR, BEHAVIOR_D), (Q_TOP25, TOP25_D), (Q_CONTRAST, CONTRAST_D)):
        llm = ScriptedLLM(judged(verdict="good", score=85, premise_corrected=True))
        v = judge_answer(q, answer, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
        assert v.verdict == "good" and v.passed, (q.id, v.react)


def test_골자를_그대로_말한_답은_어긋남_가드에_걸리지_않는다():
    for q in (Q_CONTRAST, Q_BEHAVIOR, Q_TOP25):
        assert conflicts(q.answer_gist, build_deck((s.slide_no, s.raw_text) for s in GAP.slides)) == [], q.id


def test_wrong_판정의_칭찬_react_는_버린다():
    llm = ScriptedLLM(judged(verdict="wrong", score=30, react="과잉 매매가 크다는 점은 정확해요."))
    v = judge_answer(Q_BEHAVIOR, "잘 모르겠지만 비용이 제일 컸던 것 같아요", graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert v.verdict == "wrong" and "정확" not in v.react


# ---------------------------------------------------------------------------
# 3. 자료가 원본 — 골자는 참고
# ---------------------------------------------------------------------------

SLEEP = SlideDoc(file_name="sleep.pdf", total_slides=8, slides=[
    slide(1, "수면 시간보다 중요한 수면의 질\n잠을 오래 잤다고 반드시 개운한 것은 아닙니다."),
    slide(4, "수면의 질은 단순한 “시간”보다 넓은 개념입니다.\n수면의 질 =\n시간\n×\n연속성\n×\n규칙성\n"
             "얼마나 잤는가\n얼마나 끊기지 않았는가\n언제 자고 일어났는가"),
    slide(6, "주말 몰아자기는 해결책일까\n잠을 보충할 수는 있어도 리듬까지 완전히 회복되지는 않습니다.\n평일\n02:00 취침\n"
             "사회적 시차\n평일과 주말의 수면 시간이 크게 달라질 때 생기는 리듬 차이"),
    slide(7, "수면의 질을 높이는 방법\n| 시간 부족 | 필요한 수면 시간 확보 |\n| --- | --- |\n| 규칙성 저하 | 일정한 기상 시간 유지 |"),
])
#: 기준선 수면 deck_t5 3번 — 인용하지 않은 논문 질문, 골자는 초록 문구(「건강에 긍정적 영향」).
Q_REG = Question(
    id="q03-regularity", node_id="regularity", label="규칙성", slide_nos=[4, 7],
    question="Chaput et al. (2020)의 연구에서 일정한 기상 시간 유지가 수면 질에 미치는 영향에 대해 어떻게 설명했나요?",
    answer_gist="Chaput et al. (2020)은 일정한 기상 시간 유지가 수면 패턴의 규칙성을 높여 건강에 긍정적인 영향을 미친다고 보고했어요.",
    answer_gist_parts=["일정한 기상 시간 유지가 수면 패턴 규칙성 향상", "규칙성이 건강에 긍정적 영향"],
    evidence_slide_no=4, evidence_quote="수면의 질 = 시간 × 연속성 × 규칙성",
)
REG_C = "일정한 기상 시간은 잠자는 시간을 늘려 주기 때문에 효과가 있고, 주말에 늦잠으로 채우면 리듬까지 완전히 돌아온다고 설명했어요."


def test_자료로_안_받쳐지는_골자는_참고로_싣고_그_요소는_체크리스트에서_뺀다():
    llm = ScriptedLLM(judged(verdict="good", score=85, covered_parts=[True]))
    v = judge_answer(Q_REG, "일정한 기상 시간을 지키라고 했고, 규칙성은 언제 자고 일어났는가예요", slidedoc=SLEEP, llm=llm)
    prompt = llm.prompts[0]
    assert "기대하는 답의 골자 (참고만" in prompt and "(채점 기준" not in prompt
    assert "규칙성이 건강에 긍정적 영향" not in prompt          # 자료 밖 요소는 요구하지 않는다
    assert v.verdict == "good"                                   # 남은 요소가 하나라 요소 가드도 안 건다


def test_자료로_받쳐지는_골자는_채점_기준으로_싣는다():
    llm = ScriptedLLM(judged())
    judge_answer(Q_BEHAVIOR, Q_BEHAVIOR.answer_gist, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert "기대하는 답의 골자 (채점 기준" in llm.prompts[0]


def test_근거_장_밖의_반박_줄도_판정_프롬프트에_실린다():
    """기준선 수면 3번 (c) partial 75 「맞아요」 — 반박하는 6장이 근거 장(4·7)이 아니라 프롬프트에 없었다."""
    llm = ScriptedLLM(judged(verdict="partial", score=60))
    judge_answer(Q_REG, REG_C, slidedoc=SLEEP, llm=llm)
    assert "## 답변과 맞닿은 자료 줄" in llm.prompts[0]
    assert "- 6장: 잠을 보충할 수는 있어도 리듬까지 완전히 회복되지는 않습니다." in llm.prompts[0]


def test_골자_근거_판정():
    deck = build_deck((s.slide_no, s.raw_text) for s in SLEEP.slides)
    assert not support(Q_REG.answer_gist, deck).grounded
    assert support("수면의 질은 시간, 연속성, 규칙성의 곱이에요", deck).grounded


# ---------------------------------------------------------------------------
# 4. 「모르겠어요」 — 명사 선택지 · 예시 베낌 거절
# ---------------------------------------------------------------------------

INFLECTED = {"중요함", "차지해", "설명할", "발생했음", "늘릴수록"}


def test_빈칸은_활용형이_아니라_명사_줄기를_가린다():
    deck_text = " ".join(s.raw_text for s in GAP.slides)
    for q in (Q_CONTRAST, Q_BEHAVIOR):
        _, answer, distractor = mask_gist(q.answer_gist, q.label, ["수익률 격차", "회전율", "보유 기간"],
                                          quote=q.evidence_quote, deck_text=deck_text)
        assert answer and answer not in INFLECTED and distractor not in INFLECTED
        assert answer in q.evidence_quote                    # 화면에 보이는 인용에서 확인할 수 있는 낱말이 먼저다
        # 인용이 「X 아니라 Y」 로 스스로 대비를 세우면 보기는 그 둘이다(09-29 부스) — 아니면 오답은 인용 밖 말이다
        if " 아니라" in q.evidence_quote:
            assert distractor and _negated_in(distractor.split()[-1], q.evidence_quote)
        else:
            assert distractor and distractor not in q.evidence_quote
    # 기준선에서 활용형이 나온 골자들
    for gist in ("수면의 질이 수면 시간보다 회복에 더 중요함을 보여줘요",
                 "두 요인이 전체 격차의 58%를 차지해 가장 큰 영향을 보였어요",
                 "행동 요인이 구조적 요인 외에 격차를 설명할 수 있음을 보여줘요"):
        _, answer, _ = mask_gist(gist, "개념", [], deck_text=deck_text)
        assert answer not in INFLECTED, answer


def test_오답_선택지는_이웃_개념_이름에서_고른다():
    _, answer, distractor = mask_gist(Q_BEHAVIOR.answer_gist, Q_BEHAVIOR.label, ["회전율", "매매 빈도"],
                                      quote=Q_BEHAVIOR.evidence_quote,
                                      deck_text=" ".join(s.raw_text for s in GAP.slides))
    assert distractor == "회전율"


def test_프롬프트_예시를_베낀_되물음은_버리고_코드가_선택형을_만든다():
    """기준선 수면 1번 (e): 「…무엇인가요? A인가요, B인가요? (자료 1장)」 가 화면에 나갔다."""
    llm = ScriptedLLM({"react": "괜찮아요.", "followup": "근거는 무엇인가요? A인가요, B인가요?",
                       "choices": ["수면의 질은 시간, 연속성, 규칙성의 곱으로 정의되며 연속성과 규칙성이 회복에 더 큰 영향을 미친다",
                                   "수면 시간은 침대에 누운 시간과 실제 회복 시간의 차이를 의미한다"]})
    j = coach_stuck(Q_BEHAVIOR, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert "A인가요" not in j.followup and "쪽인가요" in j.followup
    assert len(j.choices) == 2 and not INFLECTED & set(j.choices)


def test_자료에_없는_활용형_선택지는_버린다():
    """기준선 수면 2번 (e): 선택지 '스트레스' vs '중요함' — 자료에는 「중요한」 만 있다."""
    llm = ScriptedLLM({"react": "괜찮아요.", "followup": "이 장이 말하는 건 과잉 매매 쪽인가요, 중요함 쪽인가요?",
                       "choices": ["과잉 매매", "중요함"]})
    j = coach_stuck(Q_BEHAVIOR, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert "중요함" not in j.choices and len(j.choices) == 2


def test_자료의_말로_쓴_LLM_선택지는_그대로_쓴다():
    llm = ScriptedLLM({"react": "괜찮아요.", "followup": "가장 큰 요인은 과잉 매매 쪽인가요, 거래 비용 쪽인가요?",
                       "choices": ["과잉 매매", "거래 비용"]})
    j = coach_stuck(Q_BEHAVIOR, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert j.choices == ["과잉 매매", "거래 비용"]


# ---------------------------------------------------------------------------
# 5. 높임 누수 — 「하신·계신·주실」
# ---------------------------------------------------------------------------

def test_높임_정규식이_관형형_높임을_잡는다():
    for text in ("추정하신 부분이 정확해요", "정량화하신 부분", "측정 기준을 찾고 계신 것 같아요", "설명해 주실 수 있나요?"):
        assert _HONORIFIC_RE.search(text), text
    for text in ("자신의 말로 설명했어요", "혁신 사례예요", "최신 자료를 봤어요", "신뢰 구간이에요"):
        assert not _HONORIFIC_RE.search(text), text


def test_높임은_풀어서_살린다():
    assert _plain("세 요소를 곱해 실제 회복 시간을 추정하신 부분이 정확해요.") == "세 요소를 곱해 실제 회복 시간을 추정한 부분이 정확해요."
    assert _plain("측정 기준을 찾고 계신 것 같아요.") == "측정 기준을 찾고 있는 것 같아요."
    assert _plain("설명해 주실 수 있나요?") == "설명해 줄 수 있나요?"


def test_판정과_코칭_문장에_높임이_남지_않는다():
    llm = ScriptedLLM(judged(verdict="partial", score=60, react="정량화하신 부분은 좋아요.",
                             followup="그 차이를 설명해 주실 수 있나요?"))
    v = judge_answer(Q_BEHAVIOR, Q_BEHAVIOR.answer_gist, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert not _HONORIFIC_RE.search(v.react) and not _HONORIFIC_RE.search(v.followup)
    llm = ScriptedLLM({"react": "측정 기준을 찾고 계신 것 같아요.", "followup": "과잉 매매 쪽인가요, 거래 비용 쪽인가요?",
                       "choices": ["과잉 매매", "거래 비용"]})
    j = coach_stuck(Q_BEHAVIOR, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert not _HONORIFIC_RE.search(j.react) and "찾고 있는" in j.react


# ---------------------------------------------------------------------------
# 처음 보는 분야 — 규칙이 덱 낱말을 모른다는 확인
# ---------------------------------------------------------------------------

BATTERY = SlideDoc(file_name="battery.pdf", total_slides=3, slides=[
    slide(1, "전기차 배터리 수명 비교\n| 셀 종류 | 충전 횟수 |\n| --- | --- |\n| 리튬인산철 | 3000 |\n| 삼원계 | 1500 |\n"
             "| 전고체 | 5000 |\n| 나트륨이온 | 2000 |"),
    slide(2, "급속 충전은 셀 온도를 높인다\n고온에서는 수명이 짧아진다\n권장 충전 상한 80%"),
    slide(3, "셀 온도와 열화 속도의 상관은 강함"),
])
Q_BAT = Question(id="qb", node_id="life", label="배터리 수명", slide_nos=[1, 2],
                 question="셀 종류에 따라 수명이 어떻게 다른가요?",
                 answer_gist="전고체가 5000회로 가장 길고, 리튬인산철 3000회, 삼원계가 1500회로 가장 짧아요.")


def test_처음_보는_분야에서도_같은_구조_규칙이_돈다():
    deck = build_deck((s.slide_no, s.raw_text) for s in BATTERY.slides)
    assert conflicts(Q_BAT.answer_gist, deck) == []
    assert [c.kind for c in conflicts("삼원계가 리튬인산철보다 충전 횟수가 많아요", deck)] == ["order"]
    assert [c.kind for c in conflicts("삼원계가 가장 오래 가요 — 삼원계가 가장 많이 충전돼요", deck)] == ["order"]
    assert [c.kind for c in conflicts("리튬인산철은 5000회 정도 충전할 수 있어요", deck)] == ["number"]
    assert [c.kind for c in conflicts("셀 온도와 열화 속도의 상관은 약해요", deck)] == ["direction"]
    # 바꿔 말한 정답 · 계산한 숫자는 건드리지 않는다
    assert conflicts("전고체는 삼원계보다 충전을 훨씬 많이 버텨요", deck) == []
    assert conflicts("리튬인산철은 삼원계의 두 배인 3000번쯤 버텨요", deck) == []
    llm = ScriptedLLM(judged(verdict="partial", score=75, react="삼원계가 더 오래 간다는 점은 정확해요."))
    v = judge_answer(Q_BAT, "삼원계가 리튬인산철보다 충전 횟수가 많아요", slidedoc=BATTERY, llm=llm)
    assert not v.passed and "정확" not in v.react


# ---------------------------------------------------------------------------
# 재실행·벤치에서 나온 것 (09-29 실 LLM)
# ---------------------------------------------------------------------------

SLEEP2 = SlideDoc(file_name="sleep.pdf", total_slides=3, slides=[
    slide(2, "잠은 하나의 상태가 아니다\n밤새 얕은 수면, 깊은 수면, REM 수면이 반복됩니다."),
    slide(3, "깊은 수면과 REM 수면\n둘 중 하나만 충분해서는 완전한 회복이 어렵습니다."),
])


def test_자료가_정의형으로_부정한_말을_긍정한_답은_통과하지_못한다():
    """재실행 수면 1번 (c) partial 75 통과 — 자료 2장 제목 「잠은 하나의 상태가 아니다」 ↔ 답 「잠은 한 가지 상태로 쭉 이어지기」."""
    q = Question(id="q1", node_id="n", label="수면의 질", slide_nos=[2, 3], question="회복에 무엇이 중요한가요?",
                 answer_gist="얕은·깊은·REM 수면이 반복되는 주기가 이어져야 회복돼요.")
    llm = ScriptedLLM(judged(verdict="partial", score=75, react="깊은 수면이 중요하다는 점은 맞아요."))
    v = judge_answer(q, "잠은 한 가지 상태로 쭉 이어지기 때문에, 깊은 수면에 빨리 들어가기만 하면 회복된다고 봤어요.",
                     slidedoc=SLEEP2, llm=llm)
    assert not v.passed and "자료 2장" in v.react and "맞아요" not in v.react
    # 바로잡는 말(「아니라」)이 있으면 정의형 부정에 동의한 것이다
    deck = build_deck((s.slide_no, s.raw_text) for s in SLEEP2.slides)
    assert conflicts("잠은 한 가지 상태가 아니라 여러 단계가 반복돼요", deck) == []


def test_질문이_따져_묻는_자료_줄에_반대로_답하는_것은_어긋남이_아니다():
    """벤치 health_glucose: 자료가 과하게 말한 문장을 질문이 인용해 경계를 물었다 — 골자는 그 문장과 부정이 다르다."""
    deck = build_deck([(5, "식사 순서 바꾸기\n식사 순서만 바꾸면 혈당 스파이크는 완전히 막을 수 있습니다.")])
    q = "「식사 순서만 바꾸면 혈당 스파이크는 완전히 막을 수 있습니다.」라고 했는데, 이 말이 들어맞지 않는 경우도 있나요?"
    gist = "식사 순서만 바꾸면 혈당 스파이크를 완전히 막을 수는 없어요"
    assert conflicts(gist, deck, q) == []
    assert conflicts(gist, deck) != []      # 질문 없이 보면 부정이 다르다 — 질문이 그 줄을 따지는 중인지가 갈림길이다


def test_판정이_스스로_반대_명제를_들고_통과를_주면_막는다():
    """벤치 held-out: 답 「부담은 매칭 시도를 늘리는 효과」 에 missing 「부담이 매칭 시도를 줄인다는 핵심 근거가 빠져」 로 partial 75."""
    q = Question(id="q1", node_id="n", label="낯선 사람 부담", question="낯선 사람에 대한 부담이 공강에 영향을 준다는 근거는?",
                 answer_gist="낯선 사람에 대한 부담이 매칭 시도 자체를 줄여요.")
    llm = ScriptedLLM(judged(verdict="partial", score=75, react="방향은 잡았어요.",
                             missing_points=["낯선 사람에 대한 부담이 매칭 시도를 줄인다는 핵심 근거가 빠져 있어요"]))
    v = judge_answer(q, "낯선 사람에 대한 부담은 매칭 시도를 늘리는 효과가 있으므로 공강에 긍정적이에요", llm=llm)
    assert not v.passed and v.score <= 60
    # 답과 같은 방향이면 건드리지 않는다
    llm = ScriptedLLM(judged(verdict="partial", score=75, react="요지는 잡았어요.",
                             missing_points=["낯선 사람에 대한 부담이 매칭 시도를 줄인다는 근거의 출처"]))
    assert judge_answer(q, "낯선 사람에 대한 부담이 매칭 시도를 줄여서 그래요", llm=llm).passed


def test_답을_평하는_부정은_반대_명제로_세지_않는다():
    """벤치 yield_gap: react 「…예시가 구체적으로 제시되지 않았어요」 는 답에 대한 평이지 명제가 아니다."""
    from chuckchuck._deck_claims import opposes
    assert opposes("1,000만원 투자 시 누적 평가액 예시에서 연평균 수익률이 누적 수익을 결정한다는 점을 경계로 삼는다",
                   "1,000만원 투자 시 누적 평가액 예시가 구체적으로 제시되지 않았어요") == ""


def test_높임을_먼저_풀고_해요체로_바꾼다():
    """재실행: 「정확히 말씀하셨습니다」 가 해요체 변환 뒤 높임만 풀려 「말했습니다」 로 화면에 나갔다."""
    from chuckchuck.f09_judge import _haeyo_data
    assert _haeyo_data({"react": "정확히 말씀하셨습니다."})["react"] == "정확히 말했어요."
    assert _haeyo_data({"react": "추가로 설명해 주시면 좋겠습니다."})["react"] == "추가로 설명해 주면 좋겠어요."
    assert _HONORIFIC_RE.search("잠깐, 발표자님. 자료를 볼게요")
