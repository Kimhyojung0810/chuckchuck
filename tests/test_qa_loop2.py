"""
QA 두 번째 자가 루프 (qa/loop2, 2026-09-29) — P5 최종 평가(docs/review/2026-09-29_QA_근거검증/final_report.md)가 찾은
문제를 고친 코드의 회귀 테스트. LLM 은 ScriptedLLM(정해 둔 응답)이고, 시험하는 것은 **코드 가드·규칙**이다.

1. [치명] 판정이 탐침 질문을 거꾸로 채점하지 않는다 — 따져 묻는 자료 줄은 대조 원본이 아니고, 그 줄을 되풀이·수긍만 한 답은
   통과하지 못한다. 판정 프롬프트에 질문이 무엇을 따지는지 싣는다.
2. [높음] 함정 문장 — 비교는 명사구째 바꾸고, 표 극값은 열 이름·행 이름을 싣고, 수치는 믿을 만한 값으로, LLM 문장은 함정을
   드러내거나 딴 질문을 붙이면 버린다. 함정의 첫 「모르겠어요」 는 장만 가리킨다.
3. [높음] 형제 우선순위는 자료가 순위·맞바꿈을 말할 때만.
4. [중간] 골자 해요체·내부 장 표기·영문 차트 설명.
5. [중간] 해결 장의 계획 줄은 근거 없는 인과가 아니다.

덱은 **처음 보는 여러 분야**(물류·교육·동네 가게·원예·전시 기획)로 짰다. 끝의 두 테스트만 P5 held-out 실제 사례다.
"""

import inspect
import json

from chuckchuck import _grounding as grounding
from chuckchuck import _probe_stance as stance
from chuckchuck import _probes as probes_mod
from chuckchuck import _traps as traps
from chuckchuck import coach_stuck, judge_answer
from chuckchuck._evidence import slide_units, strip_chart_descriptions
from chuckchuck._probes import derive_probes
from chuckchuck.contracts import (
    Claim,
    ClaimDoc,
    ClaimQuote,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    Probe,
    Question,
    QuestionBasis,
    Slide,
    SlideBlock,
    SlideDoc,
    TrapPremise,
    qa_passed,
)
from chuckchuck.f08_questions import _polite_statement, _slide_tags
from chuckchuck.f26_claims import build_claims
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


def node(id, label, nos, depth=2, parent="root", summary="", weight=0.5):
    return ConceptNode(id=id, label=label, slide_nos=nos, summary=summary, weight=weight, depth=depth,
                       parent_id=None if depth == 1 else parent)


def judged(**kw) -> dict:
    base = dict(verdict="good", score=85, react="네, 그 설명이면 충분해요.", summary_sentence="총평이에요.",
                missing_points=[], followup="")
    base.update(kw)
    return base


def probe_question(qid, label, text, kind, quotes, gist="", nos=(1,)):
    ev = [ClaimQuote(slide_no=no, quote=q) for no, q in quotes]
    return Question(id=qid, node_id=qid, label=label, question=text, answer_gist=gist, slide_nos=list(nos),
                    source=kind, evidence_slide_no=ev[0].slide_no, evidence_quote=ev[0].quote,
                    basis=QuestionBasis(source=kind, probe=Probe(kind=kind, node_ids=[qid], claim_ids=["c01"],
                                                                  angle="", evidence=ev), evidence=ev))


# ---------------------------------------------------------------------------
# 1. 판정 — 탐침 질문을 거꾸로 채점하지 않는다
# ---------------------------------------------------------------------------

SHIP = SlideDoc(file_name="ship.pdf", total_slides=3, slides=[
    slide(1, "당일 출고 도입\n당일 출고를 하면 배송 지연은 완전히 사라집니다."),
    slide(2, "현장 인터뷰\n토론 수업이 학생의 발표 자신감을 높였습니다."),
    slide(3, "지역 거점\n지역 거점 창고는 물류 비용을 늘립니다."),
])
SHIP_GRAPH = ConceptGraph(file_name="ship.pdf", total_slides=3, nodes=[
    node("root", "배송 개선", [1, 2, 3], depth=1, weight=1.0),
    node("sameday", "당일 출고", [1]),
    node("debate", "토론 수업", [2]),
    node("hub", "지역 거점 창고", [3]),
], edges=[ConceptEdge(from_id="root", to_id=n, kind="parent") for n in ("sameday", "debate", "hub")])

ABS_Q = probe_question("sameday", "당일 출고", "당일 출고에 대해 단정적으로 말했는데, 이 말이 들어맞지 않는 경우도 있나요?",
                       "absolute_boundary", [(1, "당일 출고를 하면 배송 지연은 완전히 사라집니다.")],
                       gist="주문이 몰리는 날이나 운송사 사정이 있으면 당일 출고를 해도 배송 지연이 생길 수 있어요.")
CAUSE_Q = probe_question("debate", "토론 수업", "「토론 수업이 학생의 발표 자신감을 높였습니다.」라고 했는데, 그렇게 볼 수 있는 근거는 무엇인가요?",
                         "unsupported_cause", [(2, "토론 수업이 학생의 발표 자신감을 높였습니다.")], nos=(2,),
                         gist="자료에는 수치나 출처가 없어서, 전후 설문으로 보강해야 해요.")


def _judge(q, answer, **payload):
    llm = ScriptedLLM(judged(**payload))
    return judge_answer(q, answer, graph=SHIP_GRAPH, slidedoc=SHIP, llm=llm), llm


def test_단정의_경계를_말한_답은_따져_묻는_줄과_반대여도_깎이지_않는다():
    # 판정 react 가 자료의 단정을 되풀이해도(= LLM 이 그 줄을 정답으로 읽음) 자기모순 가드가 모범답을 내리지 않는다
    j, _ = _judge(ABS_Q, "당일 출고를 해도 배송 지연이 완전히 사라지지는 않아요. 주문이 몰리는 날엔 늦어질 수 있어요.",
                  react="자료는 당일 출고를 하면 배송 지연이 완전히 사라진다고 해요. 잘 짚었어요.")
    assert qa_passed(j.verdict, j.score), (j.verdict, j.score, j.react)


def test_단정을_그대로_받아들인_답은_통과하지_못한다():
    j, _ = _judge(ABS_Q, "당일 출고를 하면 배송 지연이 완전히 없어지는데, 창고가 바로 움직이기 때문이에요.")
    # 「없어지는데」 는 부정 표지 「없」 을 담는다 — 경계 표지로 보고 LLM 에 맡긴다(놓치는 쪽이 안전하다)
    j2, _ = _judge(ABS_Q, "당일 출고를 하면 배송 지연은 완전히 사라지는데, 창고가 바로 움직이기 때문이에요.")
    assert not qa_passed(j2.verdict, j2.score) and j2.react == stance.RESTATE_REACT["absolute_boundary"]
    assert j2.followup == stance.RESTATE_FOLLOWUP["absolute_boundary"]
    assert j.verdict in ("good", "partial")      # 앞의 것은 코드가 판단하지 않는다


def test_근거_없는_인과에_근거가_명확하다고만_한_답은_통과하지_못한다():
    j, _ = _judge(CAUSE_Q, "토론 수업이 발표 자신감을 높였다는 건 근거가 명확하게 제시되어 있어서 믿을 만해요.")
    assert not qa_passed(j.verdict, j.score) and j.react == stance.RESTATE_REACT["unsupported_cause"]
    j2, _ = _judge(CAUSE_Q, "토론 수업이 학생의 발표 자신감을 높였어요.")
    assert not qa_passed(j2.verdict, j2.score)


def test_근거를_대거나_빈틈을_인정한_답은_그대로_둔다():
    for answer in ("학기 전후 설문에서 자신감 점수가 12점 올랐어요.",
                   "자료에는 수치가 없어서, 다음에는 전후 설문으로 보강하겠어요."):
        j, _ = _judge(CAUSE_Q, answer, score=80)
        assert qa_passed(j.verdict, j.score), (answer, j.verdict, j.score)


def test_따져_묻는_줄은_자료_대조에서_빠지고_다른_줄은_그대로다():
    # 탐침이 아닌 질문이면 같은 반대 답이 자료와 어긋난다고 걸린다 — 가드 자체는 살아 있다
    plain = Question(id="q1", node_id="sameday", label="당일 출고", question="당일 출고의 효과는 무엇인가요?", slide_nos=[1])
    j, _ = _judge(plain, "당일 출고를 하면 배송 지연은 완전히 사라지지 않아요.")
    assert not qa_passed(j.verdict, j.score) and "어긋" in j.react
    # 탐침 질문에서도 **다른 줄**(3장 지역 거점)과 어긋나면 여전히 걸린다
    j2, _ = _judge(ABS_Q, "주문이 몰리면 늦어질 수 있어요. 지역 거점 창고는 물류 비용을 줄입니다.")
    assert not qa_passed(j2.verdict, j2.score)


def test_판정_프롬프트에_질문이_따지는_자료_줄을_싣는다():
    _, llm = _judge(ABS_Q, "주문이 몰리면 늦어질 수 있어요.")
    assert "예외·경계를 묻는다" in llm.prompts[0] and "완전히 사라집니다" in llm.prompts[0]
    _, llm2 = _judge(CAUSE_Q, "설문으로 보강하겠어요.")
    assert "근거(수치·출처·사례)를 묻는다" in llm2.prompts[0]
    plain = Question(id="q1", node_id="hub", label="지역 거점 창고", question="지역 거점 창고는 무엇인가요?", slide_nos=[3])
    _, llm3 = _judge(plain, "재고를 가까이 두는 창고예요.")
    assert "따지는 자료 줄" not in llm3.prompts[0]


def test_긴장_질문에_한쪽_말만_되풀이한_답은_통과하지_못한다():
    q = probe_question("root", "전시 만족도", "관람 동선도 전시 만족도의 요소인데, 전시 만족도가 관람 동선보다 중요하다는 건 어떤 뜻인가요?",
                       "tension", [(1, "관람 동선보다 중요한 전시 만족도"), (2, "전시 만족도 = 작품 수 × 관람 동선")])
    deck = SlideDoc(file_name="x.pdf", total_slides=2, slides=[slide(1, "관람 동선보다 중요한 전시 만족도"),
                                                               slide(2, "구성\n전시 만족도 = 작품 수 × 관람 동선")])
    j = judge_answer(q, "관람 동선보다 전시 만족도가 중요해요.", slidedoc=deck, llm=ScriptedLLM(judged()))
    assert not qa_passed(j.verdict, j.score) and j.react == stance.RESTATE_REACT["tension"]
    ok = judge_answer(q, "동선은 만족도를 이루는 한 요소일 뿐이라, 동선만 좋아서는 만족도가 오르지 않는다는 뜻이에요.",
                      slidedoc=deck, llm=ScriptedLLM(judged()))
    assert qa_passed(ok.verdict, ok.score)


# P5 held-out 실제 사례 (final_report.md 「나쁜 것 5」) — 건강 단정 · 인문 근거 없는 인과

HEALTH = SlideDoc(file_name="h.pdf", total_slides=5, slides=[
    slide(5, "식사 순서\n식사 순서만 바꾸면 혈당 스파이크는 완전히 막을 수 있습니다.")])
HEALTH_Q = probe_question(
    "meal-order", "식사 순서", "식사 순서만 바꾸면 혈당 스파이크는 완전히 막을 수 있다고 했는데, 이 말이 들어맞지 않는 경우는 어떤 상황인가요?",
    "absolute_boundary", [(5, "식사 순서만 바꾸면 혈당 스파이크는 완전히 막을 수 있습니다.")], nos=(5,),
    gist="식사 순서만 바꾸면 혈당 스파이크는 완전히 막을 수 없다는 것은, 혈당 스파이크가 식사 순서 외에도 다른 요인에 의해 발생할 수 있음을 의미해요.")


def test_P5_건강_단정_골자는_통과하고_동의한_오답은_막힌다():
    gist = judge_answer(HEALTH_Q, HEALTH_Q.answer_gist, slidedoc=HEALTH,
                        llm=ScriptedLLM(judged(react="자료는 식사 순서만 바꾸면 혈당 스파이크를 완전히 막을 수 있다고 해요.")))
    assert qa_passed(gist.verdict, gist.score), (gist.verdict, gist.score, gist.react)
    wrong = judge_answer(HEALTH_Q, "식사 순서만 바꾸면 혈당 스파이크가 완전히 사라지는데, 이는 다른 요인들의 영향을 무시했기 때문이에요.",
                         slidedoc=HEALTH, llm=ScriptedLLM(judged()))
    assert not qa_passed(wrong.verdict, wrong.score)


def test_P5_인문_근거_없는_인과_골자는_통과하고_근거가_명확하다는_오답은_막힌다():
    deck = SlideDoc(file_name="n.pdf", total_slides=3, slides=[slide(3, "독자층\n상업 발달이 한글 소설 독자층을 넓혔습니다.")])
    q = probe_question("commerce", "상업 발달", "상업 발달이 한글 소설 독자층을 넓혔다는 인과 관계를 뒷받침하는 수치나 출처는 무엇인가요",
                       "unsupported_cause", [(3, "상업 발달이 한글 소설 독자층을 넓혔습니다.")], nos=(3,))
    gist = judge_answer(q, "상업 발달이 한글 소설 독자층을 넓혔다는 주장이 있으나, 구체적인 수치나 출처는 제시되지 않았어요.",
                        slidedoc=deck, llm=ScriptedLLM(judged(score=80)))
    assert qa_passed(gist.verdict, gist.score)
    wrong = judge_answer(q, "상업 발달이 한글 소설 독자층을 넓혔다는 주장은 수치와 출처가 명확히 제시되어 있어 신빙성이 높아요.",
                         slidedoc=deck, llm=ScriptedLLM(judged(verdict="partial", score=75)))
    assert not qa_passed(wrong.verdict, wrong.score)


# ---------------------------------------------------------------------------
# 2. 함정 문장
# ---------------------------------------------------------------------------

SHOP = SlideDoc(file_name="shop.pdf", total_slides=6, slides=[
    slide(1, "동네 가게 운영\n배송 속도보다 더 중요한 것은 포장 품질입니다."),
    slide(2, "매장 비교\n소형 매장은 대형 매장보다 임대료가 낮습니다.\n비용은 고객이 느낀 불편보다, 다시 주문하는 과정에서 커진다"),
    slide(3, "연도별 방문\n| 연도 | 연간 방문객 | 1회 구매 금액 |\n| --- | --- | --- |\n| 2023 | 12,400명 | 8,200원 |\n"
             "| 2024 | 11,100명 | 7,900원 |\n| 2025 | 9,800명 | 7,300원 |"),
    slide(4, "시범 운영\n| 지표 | 시범 전 | 시범 후 |\n| --- | --- | --- |\n| 평균 대기 | 21분 | 8분 |\n| 반품률 | 9% | 4% |\n"
             "하루 영업 16시간 · 직원 4명\n재방문 고객 비율이 64% 늘었습니다.\n가격 지수 = 원가 × 1.2 ÷ 100"),
    slide(5, "요약 없음\n| 항목 | 값 |\n| --- | --- |\n| 2023 | 12 |\n| 2024 | 15 |\n| 2025 | 9 |"),
    slide(6, "지표 모음\n| 지표 | 상위 | 하위 |\n| --- | --- | --- |\n| 방문(회) | 4 | 1 |\n| 체류(분) | 30 | 12 |\n"
             "| 구매(건) | 3 | 2 |"),
])
SHOP_GRAPH = ConceptGraph(file_name="shop.pdf", total_slides=6, nodes=[
    node("root", "가게 운영", [1, 2, 3, 4, 5, 6], depth=1, weight=1.0),
    node("pack", "포장 품질", [1]), node("speed", "배송 속도", [1]),
    node("small", "소형 매장", [2]), node("big", "대형 매장", [2]),
    node("visit", "연간 방문객", [3]), node("pilot", "시범 운영", [4]), node("misc", "지표 모음", [5, 6]),
], edges=[ConceptEdge(from_id="root", to_id=n, kind="parent") for n in ("pack", "speed", "small", "big", "visit", "pilot", "misc")])


def _cands(nos):
    idx = grounding.build_index({s.slide_no: s for s in SHOP.slides}, SHOP_GRAPH.nodes)
    return [c.premise for c in traps.candidates("", nos, idx)], idx


def test_비교는_명사구째_바꾼다():
    got, _ = _cands([1, 2])
    orders = {tp.fact: tp.premise for tp in got if tp.kind == "order"}
    assert orders["배송 속도보다 더 중요한 것은 포장 품질입니다"] == "포장 품질보다 더 중요한 것은 배송 속도입니다"
    assert orders["소형 매장은 대형 매장보다 임대료가 낮습니다"] == "대형 매장은 소형 매장보다 임대료가 낮습니다"
    # 「고객이 느낀 불편보다」 — 꾸밈을 받는 명사는 바꾸지 않는다 (예전: 「불편은 고객이 느낀 비용보다」)
    assert not any("느낀" in f for f in orders)


def test_표의_극값은_열_이름과_행_이름을_싣고_모르면_만들지_않는다():
    got, _ = _cands([3, 5, 6])
    ext = [tp for tp in got if tp.kind == "extreme"]
    by_slide = {tp.slide_no: tp for tp in ext}
    # 열 이름에 숫자가 있어도(「1회 구매 금액」) 머리 행은 데이터가 아니다 — 열 이름이 실리고 첫 열 이름(「연도」)이 행 이름이다
    assert by_slide[3].premise in ("표에서 「연간 방문객」 값이 가장 큰 연도는 2025", "표에서 「1회 구매 금액」 값이 가장 큰 연도는 2025")
    assert 5 not in by_slide or "「값」" in by_slide[5].premise
    assert 6 not in by_slide          # 행마다 단위가 다른 표(「방문(회)」「체류(분)」)는 견줄 수 없다


def test_수치는_믿을_만한_값으로_바꾼다():
    got, idx = _cands([4])
    nums = [tp for tp in got if tp.kind == "number"]
    row = next(tp for tp in nums if "평균 대기" in tp.premise)
    assert row.wrong == ["21분"]                       # 같은 행 다른 열(시범 전)의 값 — 헷갈릴 만한 값
    pct = next(tp for tp in nums if "재방문" in tp.premise)
    w = float(pct.wrong[0].rstrip("%"))
    assert w != 64 and 64 * 0.5 <= w <= 64 * 1.5 and w <= 100
    hours = [tp for tp in nums if "16시간" in tp.fact]
    assert all(float(grounding.numbers(tp.wrong[0])[0]) <= 24 for tp in hours)
    assert not [tp for tp in nums if "가격 지수" in tp.fact]         # 식의 상수는 뒤집지 않는다
    for tp in nums:
        assert traps.verify(tp, idx)


def test_범위의_한_끝은_바꾸지_않는다():
    deck = SlideDoc(file_name="r.pdf", total_slides=1, slides=[slide(1, "주기\n한 번의 주기는 약 90–110분 이어집니다.")])
    idx = grounding.build_index({s.slide_no: s for s in deck.slides}, SHOP_GRAPH.nodes)
    assert not [c for c in traps.candidates("", [1], idx) if c.premise.kind == "number"]


def test_바꾼_값_고르기():
    assert traps._grain("84,200") == 100 and traps._grain("15") == 5 and traps._grain("2.6") == 0.1
    w = traps._wrong_value("90", "", "%", set(), seed=0)
    assert w and float(w) <= 100 and float(w) != 90
    assert traps._wrong_value("20", "", "시간", set(), seed=0) in ("", *[str(x) for x in range(1, 25)])


def test_LLM_함정_문장은_드러내거나_딴_질문을_붙이면_버린다():
    tp = TrapPremise(kind="number", premise="표에서 평균 대기의 「시범 후」 값이 21분", fact="표에서 평균 대기의 「시범 후」 값은 8분",
                     slide_no=4, wrong=["21분"], right=["8분"])
    base = "표에서 평균 대기의 「시범 후」 값이 21분이라고 했는데, "
    assert traps.question_carries(base + "이 수치가 무엇을 보여 주는지 설명해 주세요.", tp, "시범 운영")
    assert traps.question_carries(base + "그게 무슨 뜻인가요?", tp, "시범 운영")
    assert not traps.question_carries(base + "이 주장은 자료와 어떻게 다른가요?", tp, "시범 운영")
    assert not traps.question_carries(base + "직원 4명과 반품률 9%의 관계가 매출 전략에 미치는 의미는 무엇인가요?", tp, "시범 운영")


def test_LLM_함정_문장은_전제를_발표자의_말로_얹고_다른_대상을_묻지_않는다():
    tp = TrapPremise(kind="number", premise="표에서 평균 대기의 「시범 후」 값이 21분", fact="표에서 평균 대기의 「시범 후」 값은 8분",
                     slide_no=4, wrong=["21분"], right=["8분"])
    deck = " ".join(s.raw_text for s in SHOP.slides)
    # 전제를 「…라는 주장」 으로만 두면 발표자가 한 말로 얹은 것이 아니다
    assert not traps.question_carries("평균 대기의 시범 후 값이 21분이라는 주장은 무엇인가요?", tp, "시범 운영", deck)
    # 꼬리의 새 낱말이 자료의 다른 대상(「반품률」)이면 하나여도 딴 질문이다 — 자료에 없는 말(「비결」)은 둔다
    assert not traps.question_carries("표에서 평균 대기의 「시범 후」 값이 21분이라고 했는데, 반품률은 얼마인가요?", tp, "시범 운영", deck)
    assert traps.question_carries("표에서 평균 대기의 「시범 후」 값이 21분이라고 했는데, 비결이 뭔가요?", tp, "시범 운영", deck)


def test_장_제목은_방향을_뒤집지_않는다():
    deck = SlideDoc(file_name="t.pdf", total_slides=1, slides=[slide(1, "방문을 늘리는 세 단계\n쿠폰 발송이 재방문을 늘립니다.")])
    idx = grounding.build_index({s.slide_no: s for s in deck.slides}, SHOP_GRAPH.nodes)
    facts = [c.premise.fact for c in traps.candidates("", [1], idx) if c.premise.kind == "direction"]
    assert facts == ["쿠폰 발송이 재방문을 늘립니다"]


def test_함정의_첫_모르겠어요는_장만_가리키고_사실을_말하지_않는다():
    tp = TrapPremise(kind="number", premise="재방문 고객 비율이 40% 늘었습니다", fact="재방문 고객 비율이 64% 늘었습니다",
                     slide_no=4, wrong=["40%"], right=["64%"])
    q = Question(id="q1", node_id="pilot", label="시범 운영", question=traps.trap_question(tp), trap=True, trap_premise=tp,
                 answer_gist=traps.trap_gist(tp), evidence_slide_no=4, evidence_quote=tp.fact, slide_nos=[4])
    llm = ScriptedLLM({"react": "괜찮아요. 자료는 64% 늘었다고 해요.", "followup": "64% 인가요, 40% 인가요?",
                       "choices": ["64%", "40%"]})
    j = coach_stuck(q, slidedoc=SHOP, llm=llm)
    assert j.coach_stage == "narrow" and j.evidence_quote == "" and j.evidence_slide_no == 4
    assert "64" not in j.react and "64" not in j.followup and j.choices == [] and "4장" in j.followup


# ---------------------------------------------------------------------------
# 3. 형제 우선순위 — 자료가 순위를 말할 때만
# ---------------------------------------------------------------------------

def _garden(extra_quote: str = ""):
    g = ConceptGraph(file_name="g.pdf", total_slides=2, nodes=[
        node("root", "화단 생육", [1, 2], depth=1, weight=1.0),
        node("light", "일조량", [1, 2], parent="root", weight=0.6),
        node("water", "물 주기", [1, 2], parent="root", weight=0.5),
    ], edges=[ConceptEdge(from_id="root", to_id=n, kind="parent") for n in ("light", "water")])
    ev = [ClaimQuote(1, "화단 생육 = 일조량 × 물 주기")] + ([ClaimQuote(2, extra_quote)] if extra_quote else [])
    return g, ClaimDoc(file_name="g.pdf", claims=[Claim(id="c01", kind="compose", subject_id="root",
                                                        object_ids=["light", "water"], evidence=ev)])


def test_나란히_둔_요소에는_우선순위를_묻지_않는다():
    g, doc = _garden()
    assert not [p for p in derive_probes(g, doc) if p.kind == "sibling_priority"]


def test_자료가_맞바꿈을_말하면_우선순위를_묻는다():
    g, doc = _garden("그늘진 화단은 물 주기 대신 일조량 확보를 먼저 챙깁니다.")
    assert [p.node_ids for p in derive_probes(g, doc) if p.kind == "sibling_priority"] == [["light", "water"]]


# ---------------------------------------------------------------------------
# 4. 화면 글 — 해요체 · 장 표기 · 영문 차트 설명
# ---------------------------------------------------------------------------

def test_골자의_한다체_과거형도_해요체로():
    assert _polite_statement("전시 관람객 증가에 기여했다") == "전시 관람객 증가에 기여했어요"
    assert _polite_statement("구체적인 수치는 제시되지 않았다.") == "구체적인 수치는 제시되지 않았어요."
    assert _polite_statement("대기 비용이 더 크다.") == "대기 비용이 더 커요."
    assert _polite_statement("두 조건은 서로 다르다") == "두 조건은 서로 달라요"
    assert _polite_statement("측정이 어렵다") == "측정이 어려워요"
    assert _polite_statement("이미 해요체예요.") == "이미 해요체예요."


def test_목록으로_온_골자는_문장으로_잇는다():
    from chuckchuck import build_questions
    from chuckchuck.contracts import QaTriage, TriageMark
    triage = QaTriage(file_name="shop.pdf", marks=[TriageMark(node_id="pilot", rank=1, source="core_weight", severity=1, doc_weight=1.0)])
    llm = ScriptedLLM({"questions": [{"node_id": "pilot", "question": "시범 운영에서 대기 시간은 어떻게 바뀌었나요?",
                                      "answer_gist": ["평균 대기가 21분에서 8분으로 줄었다", "반품률도 9%에서 4%로 낮아졌다"]}]})
    doc = build_questions(SHOP_GRAPH, triage, track="1", slidedoc=SHOP, llm=llm)      # 1분 트랙 — 함정 없음
    q = next(x for x in doc.questions if x.node_id == "pilot")
    assert "['" not in q.answer_gist and "21분에서 8분으로" in q.answer_gist


def test_내부_장_표기는_자료_N장으로():
    assert _slide_tags("S5에서 밝힌 좌석 수와 S2의 표 (S3)", 9) == "자료 5장에서 밝힌 좌석 수와 자료 2장의 표 (자료 3장)"
    assert _slide_tags("모델 S24 는 신형이다", 9) == "모델 S24 는 신형이다"
    assert _slide_tags("S12에서", 9) == "S12에서"          # 장 수를 넘는 번호는 장 표기가 아니다
    assert _slide_tags("S3 슬라이드에 적힌 문장", 9) == "자료 3장에 적힌 문장"


def test_한글_장의_영문_그림_설명은_인용_후보에서_빠진다():
    raw = ("매출 구조\n![image](/image/placeholder)\n- Figure Type: chart\n- This is a Korean-language infographic about sales.\n"
           "- “영업이익” (Operating Profit): 60,543 (orange bar)\n"
           "An orange line connects the top of the “영업이익” bar to the next bar with an arrow.\n"
           "영업이익률은 전년보다 크게 올랐습니다.")
    units = slide_units(raw)
    assert "영업이익률은 전년보다 크게 올랐습니다." in units
    assert not any("orange" in u or "Operating" in u for u in units)
    english = "Quarterly review\nRevenue grew because the new product line shipped early in the quarter."
    assert strip_chart_descriptions(english) == english          # 영문 발표의 본문은 건드리지 않는다


# ---------------------------------------------------------------------------
# 5. 해결 장의 계획 줄은 근거 없는 인과가 아니다
# ---------------------------------------------------------------------------

def test_해결_장의_계획_줄은_인과로_받지_않는다():
    deck = SlideDoc(file_name="m.pdf", total_slides=2, slides=[
        slide(1, "현황\n주차 공간이 부족해서 방문객이 줄었습니다."),
        slide(2, "제안\n주차장 확충 — 공영 주차면을 30면 늘립니다.\n셔틀 운행을 하면 주차 수요가 줄어들기 때문에 혼잡이 준다"),
    ])
    g = ConceptGraph(file_name="m.pdf", total_slides=2, nodes=[
        node("root", "방문객", [1, 2], depth=1, weight=1.0), node("park", "주차 공간", [1, 2]),
        node("expand", "주차장 확충", [2]), node("shuttle", "셔틀 운행", [2]), node("jam", "혼잡", [2]),
    ], edges=[ConceptEdge(from_id="root", to_id=n, kind="parent") for n in ("park", "expand", "shuttle", "jam")])
    llm = ScriptedLLM({"claims": [
        {"kind": "cause", "subject_id": "expand", "object_ids": ["park"], "slide_no": 2,
         "quote": "주차장 확충 — 공영 주차면을 30면 늘립니다."},
        {"kind": "cause", "subject_id": "shuttle", "object_ids": ["jam"], "slide_no": 2,
         "quote": "셔틀 운행을 하면 주차 수요가 줄어들기 때문에 혼잡이 준다"},
    ]})
    doc = build_claims(g, deck, llm=llm)
    causes = {c.subject_id for c in doc.claims if c.kind == "cause"}
    assert "expand" not in causes          # 계획 줄 — 인과를 잇는 말이 없다
    assert "shuttle" in causes             # 해결 장이어도 「때문에」 로 이은 줄은 인과다


# ---------------------------------------------------------------------------
# 6. 규칙에 발표 낱말이 없다
# ---------------------------------------------------------------------------

BENCH_WORDS = ("수면", "수익률", "혈당", "탄수화물", "반찬", "전세", "상추", "소설", "알림", "도서관", "대출", "열람",
               "하이닉스", "공강", "적색", "청색", "배송", "주차", "화단", "매장")


def test_새_규칙에_발표_낱말이_없다():
    for mod in (stance, traps, probes_mod):
        code = "\n".join(line.split("#", 1)[0] for line in inspect.getsource(mod).splitlines())
        code_wo_docs = code.replace('"""', "\x00").split("\x00")[::2]
        leaked = [w for w in BENCH_WORDS if any(w in part for part in code_wo_docs)]
        assert not leaked, (mod.__name__, leaked)
