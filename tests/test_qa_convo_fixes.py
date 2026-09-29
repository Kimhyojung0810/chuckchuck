"""
#/qa 대화 감사(2026-09-30, docs/review/2026-09-29_QA_근거검증/convo/report.md) 로 고친 결함의 회귀 테스트.

LLM 은 ScriptedLLM(정해 둔 응답)이고, 시험하는 것은 **코드**다 — 가드·결손 정리·react 다듬기·힌트 사다리·함정 재료.
규칙은 구조로만 짰다(조사·어미·숫자·인용 부호·자료 줄과의 겹침). 그래서 예시는 **처음 보는 여러 분야**(카페·물류·식물·도서관·
헬스)로 먼저 쓰고, 감사에서 실제로 걸린 문장은 「감사 회귀」 라고 이름 붙여 따로 둔다.
"""

import json

import pytest

from chuckchuck import _grounding as grounding
from chuckchuck import _traps as traps
from chuckchuck import build_hint_ladder, coach_stuck, judge_answer
from chuckchuck._deck_claims import Num, build_deck, conflicts, direction, negated, numbers, opposes
from chuckchuck._evidence import _noun_like
from chuckchuck._judge_post import (
    beyond_deck_terms,
    cap_length,
    clean_points,
    point_covered,
    point_supported,
    praise_ungrounded,
    real_either_or,
    says_not_in_deck,
    scrub,
    to_noun_phrase,
)
from chuckchuck._speech import plain_to_haeyo, to_haeyo
from chuckchuck.contracts import (
    QA_MAX_ROUNDS,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    QaJudgement,
    Question,
    Slide,
    SlideBlock,
    SlideDoc,
    TrapPremise,
    qa_mastered,
    qa_passed,
)
from chuckchuck.f09_judge import _HONORIFIC_RE, _llm_choice_ok, _plain, asks_back, looks_stuck
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


def deck_of(*slides_):
    return build_deck((s.slide_no, s.raw_text) for s in slides_)


# ---------------------------------------------------------------------------
# 처음 보는 분야 — 카페 운영 · 물류 · 식물
# ---------------------------------------------------------------------------

CAFE = SlideDoc(file_name="cafe.pdf", total_slides=4, slides=[
    slide(1, "동네 카페 운영 개선안\n2026 가을"),
    slide(2, "대기 시간\n무인 주문기 도입 후 평균 대기 시간이 12분에서 7분으로 줄었습니다.\n"
             "병목은 좌석 수가 아니라 회전율이다"),
    slide(3, "메뉴별 판매\n| 메뉴 | 주간 판매 |\n| --- | --- |\n| 아메리카노 | 420 |\n| 카페라테 | 310 |\n| 과일 스무디 | 95 |\n"
             "판매 요약\n아메리카노 주간 418잔 · 라테 312잔"),
    slide(4, "단골\n적립 쿠폰이 재방문을 늘립니다.\n재방문 고객은 월 평균 3.4회 옵니다."),
])
CAFE_GRAPH = ConceptGraph(file_name="cafe.pdf", total_slides=4, nodes=[
    ConceptNode(id="root", label="카페 운영", slide_nos=[1, 2, 3, 4], weight=1.0, depth=1,
                summary="동네 카페의 대기 시간과 단골을 늘리는 운영 개선"),
    ConceptNode(id="turn", label="회전율", slide_nos=[2], weight=0.6, depth=2, parent_id="root",
                summary="손님이 자리를 비우고 다음 손님이 앉는 속도 — 매장의 진짜 병목"),
    ConceptNode(id="kiosk", label="무인 주문기", slide_nos=[2], weight=0.5, depth=2, parent_id="root",
                summary="주문 대기 시간을 줄인 무인 주문 장비"),
    ConceptNode(id="coupon", label="적립 쿠폰", slide_nos=[4], weight=0.5, depth=2, parent_id="root",
                summary="방문마다 도장을 찍어 재방문을 늘리는 쿠폰 제도"),
], edges=[ConceptEdge(from_id="root", to_id=n, kind="parent") for n in ("turn", "kiosk", "coupon")])
CAFE_Q = Question(id="q1", node_id="turn", label="회전율", slide_nos=[2], evidence_slide_no=2,
                  question="매장의 병목이 무엇이라고 했나요?", answer_gist="병목은 좌석 수가 아니라 회전율이에요.")

LOGI = SlideDoc(file_name="logi.pdf", total_slides=3, slides=[
    slide(1, "물류 거점 운영 보고"),
    slide(2, "거점별 지표\n| 지표 | 수도권 | 지방 |\n| --- | --- | --- |\n| 배송 건수 | 42 | 17 |\n| 반품률(%) | 3 | 6 |"),
    slide(3, "원인\n| 원인 | 건수 |\n| --- | --- |\n| 주소 오류 | 88 |\n| 포장 파손 | 31 |\n| 배송 지연 | 12 |"),
])


# ---------------------------------------------------------------------------
# §2 가드가 맞는 답을 강등하지 않는다
# ---------------------------------------------------------------------------

def test_대조_X_아니라_Y_는_부정_어긋남이_아니다():
    d = deck_of(*CAFE.slides)
    assert conflicts("병목은 좌석 수가 아니라 회전율이라고 돼 있어요", d) == []
    assert conflicts("좌석 수가 아니고 회전율이 병목이에요", d) == []           # 「아니고」 도 대조 (레드팀)
    assert negated("좌석 수가 아니라 회전율") is False
    assert negated("회전율이 아니라고 했어요") is True                          # 인용의 부정은 부정이다


def test_감사_회귀_수익률_함정Q3_38만원이_아니라_48만원은_부정_어긋남이_아니다():
    d = deck_of(slide(4, "복리 효과\n핵심 요지\n1년차 48만원\n체감하기 어려운 수준의 차이\n5년차 307만원\n"
                          "이 시점부터 격차가 눈에 보이기 시작\n10년차 838만원\n원금의 84%에 해당하는 금액"))
    ans = ("자료 4장에는 38만원이 아니라 48만원이라고 돼 있어요. 1,000만원 넣었을 때 1년차엔 48만원 차이라 "
           "체감이 안 되지만, 5년차 307만원, 10년차 838만원으로 복리처럼 커진다는 걸 보여 줘요.")
    assert conflicts(ans, d) == []


def test_반올림한_같은_값은_같은_사실이다():
    assert Num(8.7, None, False, 0, 0, 1).close_value(Num(9, None, False, 0, 0, 0))
    assert Num(7.9, None, False, 0, 0, 1).close_value(Num(8, None, False, 0, 0, 0))
    assert not Num(8, None, False, 0, 0, 0).close_value(Num(9, None, False, 0, 0, 0))
    assert not Num(1.2, None, False, 0, 0, 1).close_value(Num(1.6, None, False, 0, 0, 1))
    d = deck_of(*CAFE.slides)
    # 표 「아메리카노 | 420」 ↔ 본문 「418잔」 은 같은 것을 다른 정밀도로 말한 게 아니지만, 표 값 420 을 말해도 어긋남이 아니다
    assert conflicts("아메리카노는 주간 420잔 팔렸어요", d) == []


def test_OCR_로_한_글자_틀린_표_행_이름도_그_숫자의_주인이다():
    d = deck_of(slide(2, "비교\n| 항목 | 상위 | 하위 |\n| --- | --- | --- |\n| 재배 먼적 | 30 | 10 |\n"),
                slide(5, "기타\n| 항목 | 값 |\n| --- | --- |\n| 재배 기간 | 90 |\n| 토양 | 7 |\n| 수확 | 3 |"))
    assert conflicts("상위는 재배 면적 30 대 10으로 차이가 컸어요", d) == []


def test_감사_회귀_수익률_Q6_종목_수_12_대_3():
    d = deck_of(slide(8, "원인 상세\n| Category | Value |\n| --- | --- |\n| 수익 종목 | 52 |\n| 손실 종목 | 187 |"),
                slide(11, "성공 요인\n| Category | 상위 25% | 하위 25% |\n| --- | --- | --- |\n| 회전율(회) | 1 | 12 |\n"
                          "| 보유(월) | 19 | 3 |\n| 중목수 | 12 | 3 |\n| 적립식(%) | 68 | 12 |"))
    assert conflicts("상위·하위 25%를 비교하면 보유 기간 19개월 대 3개월, 종목 수 12 대 3으로 차이가 컸어요.", d) == []


def test_진짜_어긋남은_여전히_잡는다():
    d = deck_of(*LOGI.slides)
    found = conflicts("원인 가운데 배송 지연이 88건으로 가장 많았어요", d)
    assert found and any(c.kind in ("number", "order") for c in found)


def test_자료를_옮긴_인용_절은_자기모순_대조에서_뺀다():
    assert opposes("자료는 병목이 좌석 수가 아니라고 했어요", "병목은 좌석 수다") == ""
    # 감사 회귀 — 녹음 수면 Q2 · focus Q6
    assert opposes("자료는 반대로 잠은 하나의 상태가 아니라고 했어요. 밤새 여러 단계가 반복돼요",
                   "잠은 하나의 상태가 아니다는 점을 정확히 짚었어요") == ""
    assert opposes("알림은 확인 안 해도 주의를 끌고, 폰이 가까이만 있어도 자원을 쓰기 때문에",
                   "알림 확인 없이도 주의가 끌리고 폰이 가까이 있으면 자원을 쓴다는 점은 맞아요") == ""


def test_양보의_부정은_명제의_부정이_아니다():
    assert negated("확인 안 해도 주의를 끈다") is False
    assert negated("가까이 없어도 자원을 쓴다") is False
    assert negated("쓰레기를 없애는 방법") is False                       # 레드팀: 「없애다」 는 동사
    assert negated("주의를 끌지 않는다") is True


def test_함정_정답_단서는_반올림과_활용이_바뀐_부정을_받는다():
    num = TrapPremise(kind="number", premise="표에서 시장지수의 값이 11", fact="표에서 시장지수의 값은 9",
                      slide_no=3, wrong=["11"], right=["9"])
    assert traps.premise_stance("8.7", num) == "correct"                   # 감사 회귀 — 수익률 Q4 (P8 「8.7」)
    assert traps.premise_stance("11이 맞아요, 11이라서 높아요", num) == "agree"
    neg = TrapPremise(kind="negation", premise="매장 문제는 회전율이다", fact="매장 문제는 회전율이 아니다",
                      slide_no=2, wrong=["회전율이다|"], right=["회전율이 아니다|"])
    assert traps.hits("자료는 회전율이 아니라고 했어요", neg.right, "negation", tolerant=True)
    assert not traps.hits("자료는 회전율이 아니라고 했어요", neg.right, "negation")
    d = TrapPremise(kind="direction", premise="수면의 연속성을 이어 주는 요인", fact="수면의 연속성을 끊는 요인",
                    slide_no=5, wrong=["이어 주는|"], right=["끊는|"])
    assert traps.premise_stance("끊는", d) == "correct"                    # 감사 회귀 — 수면 Q4 (P8 「끊는」)


def test_한_단어로_함정을_바로잡은_답은_wrong_이_아니다():
    tp = TrapPremise(kind="direction", premise="적립 쿠폰이 재방문을 줄입니다", fact="적립 쿠폰이 재방문을 늘립니다",
                     slide_no=4, wrong=["줄입니다|"], right=["늘립니다|"])
    q = Question(id="q1", node_id="coupon", label="적립 쿠폰", slide_nos=[4], trap=True, trap_premise=tp,
                 question=traps.trap_question(tp), answer_gist=traps.trap_gist(tp), evidence_slide_no=4)
    v = judge_answer(q, "늘립니다", slidedoc=CAFE, llm=ScriptedLLM(judged(verdict="wrong", score=30)))
    assert v.verdict == "partial" and 55 <= v.score <= 65 and not v.passed


def test_가드만_막고_있으면_3라운드에서_닫고_정직하게_말한다():
    d_q = Question(id="q9", node_id="cause", label="반품 원인", slide_nos=[3], evidence_slide_no=3,
                   question="반품의 가장 큰 원인은 무엇인가요?", answer_gist="주소 오류가 88건으로 가장 많아요.")
    wrong_pair = "원인 가운데 배송 지연이 88건으로 가장 많았어요"
    v1 = judge_answer(d_q, wrong_pair, slidedoc=LOGI, llm=ScriptedLLM(judged()))
    assert not v1.mastered and v1.guard_reason.startswith("자료 3장과 어긋난 곳")
    v3 = judge_answer(d_q, wrong_pair, slidedoc=LOGI, prior_answers=["배송 지연이요", "배송 지연이 제일 커요"],
                      llm=ScriptedLLM(judged()))
    assert v3.round_no == QA_MAX_ROUNDS and v3.mastered and v3.close_reason == "guard" and not v3.passed
    assert "마무리" in v3.react and v3.missing_points == [] and v3.followup == ""
    # LLM 도 안 통과시킨 답은 가드 출구가 없다
    v3b = judge_answer(d_q, wrong_pair, slidedoc=LOGI, prior_answers=["a 요인", "b 요인"],
                       llm=ScriptedLLM(judged(verdict="partial", score=50)))
    assert not v3b.mastered


def test_qa_mastered_계약():
    assert qa_mastered("partial", 55, QA_MAX_ROUNDS, guard_blocked=True)
    assert not qa_mastered("partial", 55, QA_MAX_ROUNDS)
    assert not qa_mastered("partial", 55, 2, guard_blocked=True)
    # 레드팀: 점수는 등급 구간 안으로 잘라 본다
    assert not qa_passed("wrong", 80) and not qa_passed("unknown", 75) and qa_passed("partial", 85)
    j = QaJudgement(question_id="q", verdict="partial", score=75, round_no=3)
    assert j.to_dict()["close_reason"] == "rounds"
    assert QaJudgement.from_dict({"question_id": "q", "verdict": "partial", "score": 55, "round_no": 3,
                                  "guard_blocked": True}).mastered is False   # 요청 바디로 출구를 못 연다


# ---------------------------------------------------------------------------
# §3 느슨한 통과
# ---------------------------------------------------------------------------

def test_한_단어_답은_통과선_아래다():
    v = judge_answer(CAFE_Q, "회전율", slidedoc=CAFE, llm=ScriptedLLM(judged(verdict="good", score=80)))
    assert v.verdict == "partial" and v.score <= 65 and not v.passed and not v.mastered


def test_딴_얘기가_질문_낱말_하나로_초점_가드를_비켜가지_않는다():
    q = Question(id="q2", node_id="coupon", label="적립 쿠폰", slide_nos=[4], evidence_slide_no=4,
                 question="적립 쿠폰이 재방문에 어떤 효과를 냈나요?", answer_gist="적립 쿠폰이 재방문을 늘렸어요.")
    v = judge_answer(q, "쿠폰 디자인은 초록색이 제일 예쁘다고 친구들이 말해요", slidedoc=CAFE, graph=CAFE_GRAPH,
                     llm=ScriptedLLM(judged(verdict="partial", score=75)))
    assert not v.passed and v.guard_reason.startswith("질문이 묻는 것")


def test_모르겠어요_되물음에_고른_답은_질문을_닫지_못한다():
    history = [{"질문": CAFE_Q.question, "답변": "(모르겠어요)", "판정": "unknown", "포기": True, "question_id": "q1"}]
    v = judge_answer(CAFE_Q, "회전율 쪽이요 병목 회전율", slidedoc=CAFE, history=history,
                     llm=ScriptedLLM(judged(verdict="good", score=85)))
    assert not v.mastered and v.score <= 69
    llm = ScriptedLLM(judged())
    judge_answer(CAFE_Q, "회전율", slidedoc=CAFE, history=history, llm=llm)
    assert "되물음(둘 중 하나·빈칸)에 대한 답" in llm.prompts[0]


def test_말하지_않은_것을_칭찬한_react_는_빼고_말한_것_칭찬은_둔다():
    assert praise_ungrounded("쿠폰이 재방문을 늘린다는 점은 맞아요.", "좌석이 부족해서요.")
    assert not praise_ungrounded("쿠폰이 재방문을 늘린다는 점은 맞아요.", "쿠폰 덕분에 재방문이 늘었어요.")
    assert not praise_ungrounded("좋아요.", "아무 말")
    v = judge_answer(CAFE_Q, "좌석이 너무 적어서 사람들이 오래 기다려요",
                     slidedoc=CAFE, llm=ScriptedLLM(judged(verdict="partial", score=55,
                                                           react="적립 쿠폰이 재방문을 늘린다는 점은 맞아요.")))
    assert "쿠폰" not in v.react


# ---------------------------------------------------------------------------
# §4·§5 결손은 자료로 받쳐지고, 이미 말한 것은 또 요구하지 않는다
# ---------------------------------------------------------------------------

def test_자료에_없는_결손은_버린다():
    d = deck_of(*CAFE.slides)
    assert not point_supported(to_noun_phrase("원두 로스팅 온도를 낮추는 구체적인 실천 방안"), d)
    assert not point_supported(to_noun_phrase("측정 방법(예: 실험 절차, 정량적 지표 등)"), d)
    assert not point_supported("아메리카노가 카페라테보다 재방문에 더 큰 영향을 준다는 비교", d)   # 자료에 그런 비교 줄이 없다
    assert point_supported("무인 주문기 도입 후 대기 시간이 줄었다는 점", d)
    kept, dropped = clean_points(["원두 로스팅 온도 관리 방안", "무인 주문기 도입 후 대기 시간 감소"], deck=d, said="")
    assert kept == ["무인 주문기 도입 후 대기 시간 감소"] and dropped == 1


def test_이미_말한_결손은_버린다():
    said = "무인 주문기를 들인 뒤 평균 대기 시간이 12분에서 7분으로 줄었어요"
    assert point_covered("무인 주문기 도입 후 대기 시간 감소", said)
    assert point_covered("대기 시간의 정확한 수치(7분)", said)
    assert not point_covered("적립 쿠폰의 재방문 효과", said)
    # 반대 방향은 말한 게 아니다
    assert not point_covered("적립 쿠폰이 단골 손님의 재방문을 줄인다는 점", "적립 쿠폰이 단골 손님의 재방문을 늘린다고 봤어요")


def test_자료_밖을_묻는_질문에_자료에_없다고_답하면_받아_준다():
    q = Question(id="q3", node_id="kiosk", label="무인 주문기", slide_nos=[2], evidence_slide_no=2,
                 question="무인 주문기의 고객 만족도는 어떻게 측정했나요?",
                 answer_gist="자료에는 만족도 측정 방법이 나오지 않아요. 대기 시간이 12분에서 7분으로 줄었다는 결과만 있어요.")
    llm = ScriptedLLM(judged(verdict="wrong", score=20, missing_points=["만족도 설문 문항과 표본 수"]))
    v = judge_answer(q, "만족도 측정은 자료에 없어요. 자료가 말하는 건 대기 시간이 12분에서 7분으로 줄었다는 결과예요",
                     slidedoc=CAFE, llm=llm)
    assert v.passed and v.missing_points == []
    assert "측정" in beyond_deck_terms(q.question, deck_of(*CAFE.slides), q.label)
    for a in ("측정 방법까지는 발표에 안 넣었어요", "그건 자료에 따로 나오진 않았어요", "순위를 매기지는 않았어요"):
        assert says_not_in_deck(a), a
    assert not says_not_in_deck("대기 시간이 줄었어요")


def test_닫힌_질문은_결손을_비우고_다만을_뗀다():
    v = judge_answer(CAFE_Q, "병목은 좌석 수가 아니라 회전율이라서 손님이 빨리 빠져야 해요", slidedoc=CAFE,
                     llm=ScriptedLLM(judged(react="회전율을 정확히 짚었어요. 다만 무인 주문기 효과가 빠져 있어요.",
                                            missing_points=["무인 주문기 효과"])))
    if v.mastered:
        assert v.missing_points == [] and "다만" not in v.react and v.react.strip()


# ---------------------------------------------------------------------------
# §6 되물음 — 가드 사유는 따로, 결손은 명사구, 결손 없는 오답은 근거 장으로
# ---------------------------------------------------------------------------

def test_결손은_명사구로_다듬는다():
    assert to_noun_phrase("재방문 효과에 대한 구체적인 설명이 부족합니다.") == "재방문 효과에 대한 구체적인 설명"
    assert to_noun_phrase("반품 원인 순서가 빠져 있어요") == "반품 원인 순서"
    assert to_noun_phrase("측정 방법(예: 실험 절차, 표본 등)") == "측정 방법"
    assert to_noun_phrase("병목은 좌석 수가 아니다") == "병목은 좌석 수가 아니라는 점"
    assert to_noun_phrase("회전율은 손님이 머무는 시간으로 정의돼요") == "회전율은 손님이 머무는 시간으로 정의된다는 점"
    assert to_noun_phrase("구체적인 운영 전략(좌석 줄이기, 쿠폰 발행 등)") == "구체적인 운영 전략"


def test_가드_사유는_결손과_되물음_틀에_끼지_않는다():
    v = judge_answer(CAFE_Q, "요즘 원두 값이 너무 올라서 걱정이에요 정말로 비싸요", slidedoc=CAFE, graph=CAFE_GRAPH,
                     llm=ScriptedLLM(judged(verdict="partial", score=72)))
    assert v.guard_reason and not any(p.startswith("질문이 묻는 것") for p in v.missing_points)
    assert "질문이 묻는 것:" not in v.followup and "2장" in v.followup


def test_결손_없는_오답의_되물음은_근거_장을_가리킨다():
    v = judge_answer(CAFE_Q, "병목은 좌석 수라서 의자를 더 놓아야 해요 넓게", slidedoc=CAFE,
                     llm=ScriptedLLM(judged(verdict="wrong", score=20, followup="")))
    assert "뒷받침할 근거" not in v.followup and "자료 2장" in v.followup


# ---------------------------------------------------------------------------
# §7 함정 누설 · 표기 지적 · 근거 장에 없는 인용
# ---------------------------------------------------------------------------

def _cafe_trap():
    tp = TrapPremise(kind="number", premise="무인 주문기 도입 후 평균 대기 시간이 12분에서 9분으로 줄었습니다",
                     fact="무인 주문기 도입 후 평균 대기 시간이 12분에서 7분으로 줄었습니다",
                     slide_no=2, wrong=["9분"], right=["7분"])
    return Question(id="qt", node_id="kiosk", label="무인 주문기", slide_nos=[2], trap=True, trap_premise=tp,
                    question=traps.trap_question(tp), answer_gist=traps.trap_gist(tp), evidence_slide_no=2,
                    evidence_quote=tp.fact)


def test_안_풀린_함정에서_정답이_새지_않는다():
    q = _cafe_trap()
    llm = ScriptedLLM(judged(verdict="partial", score=50, react="자료에는 7분이라고 나와 있어요.",
                             missing_points=["실제 대기 시간은 7분"], followup="7분인데 왜 9분이라고 했나요?",
                             summary_sentence="대기 시간은 7분이에요."))
    v = judge_answer(q, "대기 시간이 줄어서 손님이 좋아해요 주문기 덕분에", slidedoc=CAFE, llm=llm)
    blob = " ".join([v.react, v.followup, v.summary_sentence, *v.missing_points])
    assert "7분" not in blob
    assert "2장" in v.followup


def test_표기를_고치라는_말과_근거_장에_없는_인용은_빼다():
    d = deck_of(*CAFE.slides)
    kept, _ = clean_points(["'아메리카노'가 '아메리까노'로 표기된 점 확인", "'블루베리 스무디'의 판매량"],
                           deck=d, said="", anchor_text="메뉴별 판매 아메리카노 420 카페라테 310 과일 스무디 95")
    assert kept == []


# ---------------------------------------------------------------------------
# §8 「모르겠어요」 선택지
# ---------------------------------------------------------------------------

def test_활용형_꼬리는_보기가_아니다():
    src = "측정 방법을 제시하지 않았다. 수행이 좋아지는 경향. 강아지가 짖는다. 방해 요인. 복구해야 한다"
    for w in ("제시하지", "좋아지", "복구해야"):
        assert not _noun_like(w, src), w
    assert _noun_like("강아지", src) and _noun_like("방해", src)


def test_진짜_양자택일만_선택형으로_받는다():
    assert real_either_or("이 장이 말하는 건 '회전율' 쪽인가요, '좌석 수' 쪽인가요?", ["회전율", "좌석 수"])
    assert real_either_or("이건 확인하는 순간 이야기인가요, 돌아오는 과정 이야기인가요?", ["확인하는 순간", "돌아오는 과정"])
    # 감사 회귀 — 수면 t10 Q1: 「…수면 시간은 어떤 요소인가요, 연속성은 어떤 요소인가요?」
    assert not real_either_or("공식에서 수면 시간은 어떤 요소인가요, 연속성은 어떤 요소인가요?", ["수면 시간", "연속성"])
    src = " ".join(s.raw_text for s in CAFE.slides)
    assert not _llm_choice_ok("무인 주문기는 어떤 효과인가요, 쿠폰은 어떤 효과인가요?", ["무인 주문기", "적립 쿠폰"], src)
    assert _llm_choice_ok("병목은 '회전율' 쪽인가요, '좌석 수' 쪽인가요?", ["회전율", "좌석 수"], src)


# ---------------------------------------------------------------------------
# §9 말투 · §10 react
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src,want", [
    ("그건 아닙니다.", "그건 아니에요."), ("차이가 보입니다.", "차이가 보여요."), ("중요한 것입니다.", "중요한 거예요."),
    ("조금 아쉽습니다.", "조금 아쉬워요."), ("꽤 어렵습니다.", "꽤 어려워요."),
])
def test_to_haeyo_불규칙(src, want):
    assert to_haeyo(src) == want


@pytest.mark.parametrize("src,want", [
    ("수면 주기를 정확히 설명했다.", "수면 주기를 정확히 설명했어요."), ("근거가 부족하다.", "근거가 부족해요."),
    ("핵심은 회전율이다.", "핵심은 회전율이에요."), ("차이가 크다.", "차이가 커요."), ("잡습니다.", "잡아요."), ("괜찮습니다.", "괜찮아요."),
    ("…했다는 점이 중요하다", "…했다는 점이 중요해요"), ("「자료는 아니다」라고 했다.", "「자료는 아니다」라고 했어요."),
])
def test_해라체_총평을_해요체로(src, want):
    assert plain_to_haeyo(to_haeyo(src)) == want


def test_내부_장_표기와_3인칭을_지운다():
    assert scrub("발표자는 S4, S7, S8의 실험을 [S3]에서 설명했어요.") == "자료 4, 7, 8장의 실험을 자료 3장에서 설명했어요."
    assert scrub("발표자의 답변은 좋아요") == "방금 답변은 좋아요"
    assert scrub("Galaxy S23 사용자") == "Galaxy S23 사용자"                 # 영문 이름 뒤의 S+숫자는 제품 이름이다


def test_높임은_풀고_react_를_통째로_버리지_않는다():
    for src, want in (("핵심을 정확히 짚으셨어요.", "핵심을 정확히 짚었어요."), ("확인해 주셔서 좋아요.", "확인해 줘서 좋아요."),
                      ("말해 주시면 돼요.", "말해 주면 돼요.")):
        assert _plain(src) == want
    v = judge_answer(CAFE_Q, "병목은 좌석 수가 아니라 회전율이에요. 손님이 빨리 순환해야 매출이 나요",
                     slidedoc=CAFE, llm=ScriptedLLM(judged(react="회전율을 병목으로 정확히 짚으셨어요.")))
    assert v.react == "회전율을 병목으로 정확히 짚었어요."
    # 레드팀: 「함께·마시면」 은 높임이 아니다
    assert not _HONORIFIC_RE.search("함께 보면 좋아요") and not _HONORIFIC_RE.search("커피를 마시면 잠이 깨요")


def test_react_길이_상한():
    long = "첫 문장은 짧아요. " + "둘째 문장은 꽤 길어서 " * 12 + "끝나요."
    out = cap_length(long)
    assert len(out) <= 120 and out == "첫 문장은 짧아요."


def test_레드팀_되물음·포기_오탐():
    assert not asks_back("다시 설명하면 회전율이 병목이에요")
    assert asks_back("다시 설명해 주세요")
    assert not looks_stuck("패스트푸드요")
    assert looks_stuck("패스")


def test_레드팀_방향_낱말은_줄기와_활용_꼬리까지():
    for w in ("낮잠", "줄거리", "긴장", "개선안"):
        assert direction(w) == "", w
    assert direction("낮아졌다") == "down" and direction("늘립니다") == "up" and direction("줄이는") == "down"


# ---------------------------------------------------------------------------
# §11 힌트 사다리
# ---------------------------------------------------------------------------

def _ladder_q(**kw):
    base = dict(id="q1", node_id="turn", label="회전율", question="병목은 무엇인가요?", hint="병목이 어디서 생기는지부터 보세요",
                slide_nos=[2], answer_gist="손님이 자리를 비우는 속도, 곧 회전율이 병목이라서 좌석을 늘려도 소용없어요.",
                evidence_slide_no=2, evidence_quote="무인 주문기 도입 후 평균 대기 시간이 12분에서 7분으로 줄었습니다.")
    base.update(kw)
    return Question(**base)


def test_사다리는_방향_범위_인용_조각_빈칸_순서다():
    ladder = build_hint_ladder(_ladder_q())
    assert ladder[0] == "병목이 어디서 생기는지부터 보세요"
    assert "장을 같이 볼게요" in ladder[1]
    assert ladder[2].startswith("자료 2장은 이렇게 말해요")
    assert ladder[3].startswith("이 방향이에요") and ladder[4].startswith("빈칸을 채워 보세요")


def test_답과_같은_인용·조각_인용·이름표_인용은_사다리에서_뺀다():
    same = _ladder_q(evidence_quote="손님이 자리를 비우는 속도, 곧 회전율이 병목이라서 좌석을 늘려도 소용없어요.")
    assert not any("이렇게 말해요" in s for s in build_hint_ladder(same))
    frag = _ladder_q(evidence_quote="좌석을 아무리 늘려도 손님이 자주 머물면")
    assert not any("이렇게 말해요" in s for s in build_hint_ladder(frag))
    title = _ladder_q(evidence_quote="동네 카페 운영 개선안 핵심 메시지")
    assert not any("이렇게 말해요" in s for s in build_hint_ladder(title))


def test_판정이_와도_사다리_분모가_그대로다():
    q = _ladder_q()
    j = QaJudgement(question_id="q1", verdict="partial", score=55, missing_points=["회전율"])
    before, after = build_hint_ladder(q), build_hint_ladder(q, j)
    assert len(before) == len(after)
    assert after[3].startswith("아직 안 나온 것")


# ---------------------------------------------------------------------------
# §12 함정 재료
# ---------------------------------------------------------------------------

def _idx(deck, graph):
    return grounding.build_index({s.slide_no: s for s in deck.slides}, graph.nodes)


def _node(id, label, nos, depth=2):
    return ConceptNode(id=id, label=label, slide_nos=nos, weight=0.5, depth=depth, parent_id=None if depth == 1 else "root")


def test_표지와_차트_반올림_값과_개념과_무관한_줄은_함정_재료가_아니다():
    deck = SlideDoc(file_name="gym.pdf", total_slides=4, slides=[
        slide(1, "헬스장 회원 유지 전략\n10분 발표 · 운영팀"),
        slide(2, "월별 이탈\n| 지표 | 값 |\n| --- | --- |\n| 이탈률 | 9 |\n| 재등록률 | 42 |\n"
                 "본문 요약\n이탈률은 8.7%로 집계됐습니다."),
        slide(3, "헬스장 이용 요약\n헬스장 평일 이용객이 주말보다 30% 많았습니다."),
        slide(4, "PT 효과\nPT 등록 회원의 재등록률은 61%입니다."),
    ])
    graph = ConceptGraph(file_name="gym.pdf", total_slides=4, nodes=[
        _node("root", "헬스장", [1, 2, 3, 4], depth=1), _node("churn", "이탈률", [2]), _node("pt", "PT 효과", [3, 4]),
        _node("cover", "회원 유지", [1])], edges=[ConceptEdge(from_id="root", to_id=n, kind="parent") for n in ("churn", "pt", "cover")])
    idx = _idx(deck, graph)
    assert traps.candidates("회원 유지", [1], idx) == []                                   # 표지
    churn = traps.candidates("이탈률", [2], idx)
    assert not any("표에서 이탈률" in c.premise.premise for c in churn)                      # 차트 반올림 값(9 ↔ 8.7)
    pt = traps.candidates("PT 효과", [3, 4], idx)
    assert pt and all("PT" in c.line for c in pt)                                          # 「헬스장」 은 덱 주제어 — 3장은 PT 사실이 아니다


# ---------------------------------------------------------------------------
# 1차 재실행(8812, 09-30)에서 나온 것
# ---------------------------------------------------------------------------

def test_틀린_단서를_말하고_오히려만_붙인_답은_바로잡은_게_아니다():
    """감사 재실행 회귀 — focus Q2 P7: 「알림이 와서 오히려 작업 흐름을 이어 주는 신호」 가 「오히려」 하나로 바로잡은 답이 됐다."""
    tp = TrapPremise(kind="direction", premise="적립 쿠폰이 재방문을 줄여 주는 방식", fact="적립 쿠폰이 재방문을 늘려 주는 방식",
                     slide_no=4, wrong=["줄여 주는|"], right=["늘려 주는|"])
    assert traps.premise_stance("쿠폰이 오히려 재방문을 줄여 주는 신호예요", tp) == "agree"
    assert traps.premise_stance("줄여 주는 게 아니라 늘려 주는 방식이에요", tp) == "correct"


def test_표_행_이름이_숫자_구간이면_표_제목이_값의_주인이다():
    """감사 재실행 회귀 — 수익률 Q2: 「회전율 구간이 올라갈수록 7%에서 −4%까지」 가 2장 「최상위 회전율 구간 평균 −3.6%」 와 짝지어졌다."""
    d = deck_of(slide(2, "요약\n최상위 배송 구간 평균 −3.6%"),
                slide(6, "원인 상세\n연간 배송 구간별 평균 지연 (%)\n| Category | Value |\n| --- | --- |\n| 50km 미만 | 7 |\n"
                         "| 50~150km | 6 |\n| 150km 초과 | -4 |"))
    assert conflicts("배송 구간이 멀어질수록 7%에서 −4%까지 줄었어요", d) == []
    # 같은 표의 **다른 행** 을 부르며 그 값을 붙이면 여전히 어긋남이다
    bat = deck_of(slide(1, "수명 비교\n| 셀 종류 | 충전 횟수 |\n| --- | --- |\n| 리튬인산철 | 3000 |\n| 삼원계 | 1500 |\n| 전고체 | 5000 |"))
    assert [c.kind for c in conflicts("리튬인산철은 5000회 정도 충전할 수 있어요", bat)] == ["number"]


def test_문장으로_안_닫힌_react_조각과_골자를_읽어_준_react_는_버린다():
    gist = "무인 주문기 도입 후 평균 대기 시간이 12분에서 7분으로 줄어 회전율이 올라갔기 때문이에요"
    q = Question(id="q1", node_id="kiosk", label="무인 주문기", slide_nos=[2], evidence_slide_no=2,
                 question="무인 주문기가 매장에 준 효과는 무엇인가요?", answer_gist=gist)
    v = judge_answer(q, "주문이 좀 빨라졌어요 손님들이 좋아해요", slidedoc=CAFE,
                     llm=ScriptedLLM(judged(verdict="partial", score=60, react=gist + ".")))
    assert "12분" not in v.react
    v2 = judge_answer(q, "주문이 좀 빨라졌어요 손님들이 좋아해요", slidedoc=CAFE,
                      llm=ScriptedLLM(judged(verdict="partial", score=60, react="답변에서")))
    assert v2.react != "답변에서" and v2.react.strip()
