"""
근거를 묻는 질문의 골자·「모르겠어요」 보기를 **주장 그래프 먼저, 장의 절 구조로 폴백** 해서 만든다 (qa/reason, 2026-09-30).

09-30 부스 실측 두 가지를 고친 코드의 회귀 테스트다. LLM 은 ScriptedLLM(정해 둔 응답)이고 시험하는 것은 코드 규칙이다.
1. 「…라고 결론지은 근거」 의 골자가 같은 장의 **배경 절**(현상이 있다·규모)과 **이유 절**을 섞고 가장 곧은 줄을 뺐다.
2. 「모르겠어요」 보기가 인용 한 줄의 낱말에서 나와 둘 다 틀렸다(자료가 세운 대비를 몰랐다).

덱은 **처음 보는 여러 분야**(물류·교육·동네 카페·건강·제품)로 짰다. 끝의 회귀 테스트 하나만 실제 부스 덱의 2장 구조를 옮긴 것이다.
"""

import json

from chuckchuck import _reason as RS
from chuckchuck import build_questions, judge_answer
from chuckchuck.contracts import (
    ClaimQuote,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    QaTriage,
    Question,
    QuestionBasis,
    Slide,
    SlideBlock,
    SlideDoc,
    TriageMark,
    qa_passed,
)
from chuckchuck.f09_judge import _narrow_followup, _reason_missed, _scaffold_judgement
from chuckchuck.f26_claims import build_claims, rule_contrast, rule_correlation
from chuckchuck.providers.llm_base import LLMProvider


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, payload: dict):
        self.payload = payload
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.prompts.append(user)
        self.systems.append(system)
        return json.dumps(self.payload, ensure_ascii=False)


def slide(no: int, text: str) -> Slide:
    return Slide(slide_no=no, title=f"{no}장", blocks=[SlideBlock(category="paragraph", text=text)])


def node(id, label, nos, depth=2, parent="root", weight=0.5):
    return ConceptNode(id=id, label=label, slide_nos=nos, summary="", weight=weight, depth=depth,
                       parent_id=None if depth == 1 else parent)


def graph_of(name: str, nodes: list[ConceptNode]) -> ConceptGraph:
    return ConceptGraph(file_name=name, total_slides=3, nodes=nodes,
                        edges=[ConceptEdge(from_id="root", to_id=n.id, kind="parent") for n in nodes if n.id != "root"])


# ---------------------------------------------------------------------------
# 물류 — 배경 절(오배송이 늘었다) ↔ 이유 절(원인은 인력이 아니다). 줄 모양은 PPT 파싱처럼 꺾인 낱말·글머리표만 있는 줄.
# ---------------------------------------------------------------------------

LOGI = SlideDoc(file_name="logi.pptx", total_slides=3, slides=[
    slide(1, "오배송은 왜 줄지 않나\n인력 부족이 아니라 검수 동선의 문제다"),
    slide(2, "요약\n결론: 오배송 증가는 인력 부족이 아니라 검수 동선에서 생긴다\n01\n02\n오배송은 늘고 있다\n"
             "· 월 오배송률은 1년 새 0.8%에서\n1.9%로 상승\n· 반품 비용도 두 배로\n증가\n"
             "원인은 인력이 아니다\n· 작업자 수와 오배송률의 상관은\n약함\n· 검수대까지 이동 거리는 오배송률과 뚜렷한\n비례\n·\n"
             "이동 거리 상위 구간 오배송률 3.4%\n몇 명이 일하느냐가 아니라, 몇 걸음을 걷느냐가 오배송을 갈랐다"),
    slide(3, "현황\n월 오배송률 1.9%\n반품 비용 월 2,400만 원"),
])
LOGI_GRAPH = graph_of("logi.pptx", [
    node("root", "오배송", [1, 2, 3], depth=1, weight=1.0),
    node("route", "검수 동선", [1, 2]),
    node("staff", "인력 부족", [1, 2]),
    node("distance", "이동 거리", [2]),
    node("rate", "오배송률", [2, 3]),
])
LOGI_Q = "오배송 증가가 인력 부족이 아니라 검수 동선에서 생긴다고 결론지은 근거는 무엇인가요?"
LOGI_MIXED = ("월 오배송률이 0.8%에서 1.9%로 오르고 반품 비용도 두 배로 늘었으며, "
              "작업자 수와 오배송률의 상관은 약해요.")
TEXTS = {s.slide_no: s.raw_text for s in LOGI.slides}


def test_꺾인_글머리표와_절_제목을_읽는다():
    us = RS.units(2, TEXTS[2])
    texts = [u.text for u in us]
    assert "월 오배송률은 1년 새 0.8%에서 1.9%로 상승" in texts
    assert "작업자 수와 오배송률의 상관은 약함" in texts
    assert "이동 거리 상위 구간 오배송률 3.4%" in texts                     # 글머리표만 있는 줄 다음 줄
    heads = {u.text for u in us if u.kind == "heading"}
    assert heads == {"오배송은 늘고 있다", "원인은 인력이 아니다"}


def test_이유_절과_배경_절을_가른다():
    us = RS.units(2, TEXTS[2])
    role = {u.text: RS.role_of(u, us) for u in us}
    assert role["월 오배송률은 1년 새 0.8%에서 1.9%로 상승"] == "background"
    assert role["반품 비용도 두 배로 증가"] == "background"
    assert role["작업자 수와 오배송률의 상관은 약함"] == "reason"
    assert role["이동 거리 상위 구간 오배송률 3.4%"] == "reason"             # 말투는 없어도 이유 절 안이다
    assert role["몇 명이 일하느냐가 아니라, 몇 걸음을 걷느냐가 오배송을 갈랐다"] == "reason"
    # 절이 없는 현황 장은 장 제목이 배경이다
    us3 = RS.units(3, TEXTS[3])
    assert {RS.role_of(u, us3) for u in us3} == {"background"}


def test_근거_질문의_골자에서_배경을_빼고_가장_곧은_이유를_붙인다():
    ev = RS.evidence(LOGI_Q, [1, 2, 3], TEXTS)
    assert ev is not None and ev.strongest.text.startswith("몇 명이 일하느냐가 아니라")
    assert ev.conclusion is not None and "검수 동선에서 생긴다" in ev.conclusion.text
    gist, checks = RS.check_gist(LOGI_MIXED, ev)
    assert checks == ["gist_background_dropped", "gist_reason_rebuilt"]
    assert "0.8%" not in gist and "두 배" not in gist
    assert gist.startswith("작업자 수와 오배송률의 상관은 약해요.")
    assert "몇 걸음을 걷느냐가 오배송을 갈랐다" in gist and "3.4%" in gist


def test_배경만_말한_골자는_이유_줄로_다시_쓴다():
    ev = RS.evidence(LOGI_Q, [1, 2, 3], TEXTS)
    gist, checks = RS.check_gist("월 오배송률이 1.9%로 올랐고, 반품 비용도 두 배로 늘었어요.", ev)
    assert "gist_background_dropped" in checks and "gist_reason_rebuilt" in checks
    assert gist.startswith("자료는 이렇게 말해요 — 몇 명이 일하느냐가 아니라") and gist.endswith("(2장)")
    assert "1.9%" not in gist


def test_이유를_제대로_쓴_골자는_그대로_둔다():
    ev = RS.evidence(LOGI_Q, [1, 2, 3], TEXTS)
    good = "몇 명이 일하느냐가 아니라 몇 걸음을 걷느냐가 오배송을 갈랐고, 이동 거리 상위 구간 오배송률은 3.4%예요."
    assert RS.check_gist(good, ev) == (good, [])


def test_규칙_주장_대비는_세운_쪽이_주어_부정한_쪽이_목적어():
    claims = rule_contrast(LOGI_GRAPH, LOGI)
    pairs = {(c.subject_id, tuple(c.object_ids)) for c in claims}
    assert ("route", ("staff",)) in pairs
    # 양쪽이 개념에 닿지 않는 대비 줄(「몇 명이 일하느냐가 아니라 …」)은 주장이 아니다 — 그래프 밖 구절을 노드로 만들지 않는다
    assert all("몇 명이" not in c.text for c in claims)


def test_상관_줄_약한_상관은_인과가_아니고_뚜렷한_비례는_인과다():
    claims = rule_correlation(LOGI_GRAPH, LOGI)
    assert [(c.subject_id, c.object_ids) for c in claims] == [("distance", ["rate"])]
    assert RS.correlation("작업자 수와 오배송률의 상관은 약함") == "weak"
    assert RS.correlation("검수 시간은 오배송률과 뚜렷한 역상관") == "inverse"


def test_build_claims_가_대비_주장을_남기고_보기_쌍의_재료가_된다():
    doc = build_claims(LOGI_GRAPH, LOGI, llm="none")
    contrast = [c for c in doc.claims if c.kind == "contrast"]
    assert contrast and contrast[0].subject_id == "route"
    got = RS.contrast_choice(doc, "route", LOGI_GRAPH.nodes, LOGI_Q, [1, 2], TEXTS)
    assert got is not None and (got.affirmed, got.negated, got.source) == ("검수 동선", "인력 부족", "graph")


def _logi_questions(gist: str, question: str = LOGI_Q):
    triage = QaTriage(file_name="logi.pptx", marks=[
        TriageMark(node_id="route", rank=1, source="core_weight", severity=1, doc_weight=1.0)])
    llm = ScriptedLLM({"questions": [{"node_id": "route", "question": question, "answer_gist": gist}]})
    claims = build_claims(LOGI_GRAPH, LOGI, llm="none")
    doc = build_questions(LOGI_GRAPH, triage, track="1", slidedoc=LOGI, claims=claims.to_dict(), llm=llm)
    return next(q for q in doc.questions if q.node_id == "route"), llm


def test_F08_근거_질문_골자_검사와_근거_묶음():
    q, llm = _logi_questions(LOGI_MIXED)
    assert "0.8%" not in q.answer_gist and "몇 걸음을 걷느냐가" in q.answer_gist
    assert {"gist_background_dropped", "gist_reason_rebuilt", "contrast_graph"} <= set(q.basis.checks)
    assert q.basis.reason and q.basis.reason[0].quote.startswith("몇 명이 일하느냐가 아니라")
    assert any("0.8%" in b.quote for b in q.basis.background)
    assert q.basis.contrast == ["검수 동선", "인력 부족"]
    # 이유 구조가 있는 덱에만 골자 규칙을 덧붙인다
    assert "근거·이유를 묻는 질문의 골자" in llm.systems[-1]
    # 근거 묶음은 세션을 오간다 (프론트가 질문 dict 를 그대로 판정에 돌려보낸다)
    again = Question.from_dict(q.to_dict())
    assert again.basis.contrast == q.basis.contrast and again.basis.reason == q.basis.reason


def test_F08_근거를_묻지_않는_질문은_골자를_건드리지_않는다():
    q, _ = _logi_questions("검수 동선은 검수대까지 걷는 길이에요.", question="검수 동선은 무엇을 뜻하나요?")
    assert q.answer_gist == "검수 동선은 검수대까지 걷는 길이에요."
    assert not q.basis.reason and "gist_reason_rebuilt" not in q.basis.checks


# ---------------------------------------------------------------------------
# F-09 — 「모르겠어요」 보기 · 채점 기준
# ---------------------------------------------------------------------------

def _reason_question() -> Question:
    q, _ = _logi_questions(LOGI_MIXED)
    return q


def test_모르겠어요_보기는_자료가_세운_대비_쌍():
    q = _reason_question()
    followup, choices = _narrow_followup({}, q, LOGI_GRAPH, " ".join(TEXTS.values()))
    assert choices == sorted(["검수 동선", "인력 부족"])
    assert "인력 부족이 아니라 검수 동선" in followup and "쪽인가요" in followup
    # LLM 이 자료 낱말로 그럴듯한 보기를 줘도 대비 쌍이 먼저다 — LLM 보기는 어느 쪽이 맞는지 모른다
    _, choices2 = _narrow_followup({"followup": "반품 쪽인가요, 비용 쪽인가요?", "choices": ["반품", "비용"]},
                                   q, LOGI_GRAPH, " ".join(TEXTS.values()))
    assert choices2 == choices


def test_발판_빈칸도_세운_쪽을_가린다():
    q = _reason_question()
    j = _scaffold_judgement(q, LOGI_GRAPH, " ".join(TEXTS.values()))
    assert j is not None and sorted(j.choices) == sorted(["검수 동선", "인력 부족"])


def test_대비_쌍이_없는_옛_질문은_인용_한_줄의_대비로_간다():
    q = Question(id="q", node_id="route", label="검수 동선", question=LOGI_Q, answer_gist="검수 동선에서 생겨요.",
                 evidence_slide_no=1, evidence_quote="인력 부족이 아니라 검수 동선의 문제다")
    _, choices = _narrow_followup({}, q, LOGI_GRAPH, " ".join(TEXTS.values()))
    assert set(choices) == {"검수", "인력 부족"}          # aadf68f 폴백 — 세운 쪽이 보기 안에 있다


def test_판정_배경만_되풀이한_답은_통과하지_못하고_이유를_댄_답은_통과한다():
    q = _reason_question()
    llm = ScriptedLLM({"verdict": "good", "score": 85, "react": "좋아요.", "summary_sentence": "총평",
                       "missing_points": [], "followup": ""})
    bg = judge_answer(q, "월 오배송률이 0.8%에서 1.9%로 올랐고 반품 비용도 두 배로 늘었으니까요.",
                      graph=LOGI_GRAPH, slidedoc=LOGI, llm=llm)
    assert bg.verdict == "partial" and not qa_passed(bg.verdict, bg.score)
    # 가드 사유는 결손 목록이 아니라 guard_reason 으로 간다 (qa/convo §6 — 사유가 되물음 템플릿에 끼면 문장이 깨졌다)
    assert "결론을 받치는 이유" in bg.guard_reason and not any("결론을 받치는 이유" in p for p in bg.missing_points)
    assert "이 질문의 근거 줄" in llm.prompts[-1] and "배경 줄" in llm.prompts[-1]
    ok = judge_answer(q, "사람 수와는 상관이 약했고, 검수대까지 걷는 거리가 길수록 오배송이 많았어요.",
                      graph=LOGI_GRAPH, slidedoc=LOGI, llm=llm)
    assert qa_passed(ok.verdict, ok.score), (ok.verdict, ok.score)


def test_이유_가드는_근거_묶음이_없으면_아무것도_안_한다():
    q = Question(id="q", node_id="route", label="검수 동선", question=LOGI_Q, answer_gist="…")
    assert _reason_missed("월 오배송률이 올랐어요", q) is None
    q2 = Question(id="q", node_id="route", label="검수 동선", question=LOGI_Q, answer_gist="…",
                  basis=QuestionBasis(reason=[ClaimQuote(2, "작업자 수와 오배송률의 상관은 약함")]))
    assert _reason_missed("월 오배송률이 올랐어요", q2) is None       # 배경 줄이 없으면 배경을 되풀이했는지 모른다


# ---------------------------------------------------------------------------
# 다른 분야 — 대비 말투 · 질문 판별 · 그래프가 빈 덱
# ---------------------------------------------------------------------------

def test_대비_말투_여러_꼴():
    # 동네 카페 · 건강 · 제품 · 교육
    assert RS.choice_pair("재방문은 가격이 아니라 대기 시간에서 갈린다") == ("대기 시간", "가격")
    assert RS.choice_pair("운동량보다 수면 규칙성이 회복을 갈랐다") == ("수면 규칙성", "운동량")
    assert RS.choice_pair("기능 수가 아닌 첫 화면 이해도") == ("첫 화면 이해도", "기능 수")
    assert RS.choice_pair("핵심은 과제의 양이 아니라 피드백 속도다") == ("피드백 속도", "과제의 양")
    # 대비지만 보기감이 아닌 것 — 물음꼴·부사 쪽
    assert RS.contrast_sides("무엇을 내느냐가 아니라, 언제 돌려받느냐가 참여를 갈랐다") is not None
    assert RS.choice_pair("무엇을 내느냐가 아니라, 언제 돌려받느냐가 참여를 갈랐다") is None
    # 「보다」 는 결과를 가른 말이 있을 때만 대비다 (「A보다 B가 더 크다」 는 비교 주장 몫)
    assert RS.contrast_sides("상반기보다 하반기 매출이 더 크다") is None
    assert RS.contrast_sides("왜 가격이 아니라 대기 시간인가?") is None                  # 물음 줄


def test_근거를_묻는_질문인가():
    assert RS.asks_reason("참여율이 떨어진 이유는 무엇인가요?")
    assert RS.asks_reason("피드백 속도가 핵심이라고 판단한 근거를 설명해 주세요")
    assert RS.asks_reason("왜 대기 시간이 재방문을 좌우한다고 보나요?")
    assert not RS.asks_reason("대기 시간이 이 발표에서 왜 중요한지 설명해 주세요")     # 중요성 — 규모·현황이 답이다
    assert not RS.asks_reason("첫 화면 이해도는 어떻게 측정했나요?")


def test_교육_덱_그래프가_비어도_절_구조로_이유를_고른다():
    texts = {1: "참여 분석\n결론: 참여 감소는 과제량이 아니라 피드백 지연에서 온다\n참여는 줄었다\n· 출석률은 한 학기 새 92%에서\n81%로\n"
                "· 토론 발언 수 절반으로\n감소\n원인은 과제량이 아니다\n· 과제량과 참여율의 상관은\n약함\n"
                "· 피드백 지연 일수는 참여율과 뚜렷한\n역상관\n무엇을 내느냐가 아니라, 언제 돌려받느냐가 참여를 갈랐다"}
    q = "참여 감소가 과제량이 아니라 피드백 지연에서 온다고 결론지은 근거는 무엇인가요?"
    ev = RS.evidence(q, [1], texts, graph_lines=[])
    assert ev is not None and not any(ln.graph for ln in ev.lines)
    assert ev.strongest.text.startswith("무엇을 내느냐가 아니라")
    gist, checks = RS.check_gist("출석률이 92%에서 81%로 떨어지고 토론 발언 수도 절반으로 줄었어요.", ev)
    assert "92%" not in gist and "언제 돌려받느냐가" in gist and "gist_reason_rebuilt" in checks
    got = RS.contrast_choice(None, "x", [], q, [1], texts)
    assert got is not None and (got.affirmed, got.negated, got.source) == ("피드백 지연", "과제량", "line")


def test_절_구조가_없는_신청서_사진_덱은_건드리지_않는다():
    # 09-29 부스 사진 덱(Upstage OCR) 꼴 — 칸 제목과 긴 글, 주장 0개. 이유 줄을 지어내지 않는다.
    texts = {1: "타겟 고객 및 비즈니스 모델을 기재해 주세요 *\n초기 타깃은 대학생이며, 이후 기업 교육으로 확장하고자 합니다.\n"
                "개인 구독과 기관 도입을 주요 수익모델로 검토하고 있습니다."}
    q = "개인 구독과 기관 도입을 함께 검토한 근거는 무엇인가요?"
    ev = RS.evidence(q, [1], texts, graph_lines=[])
    assert ev is None
    assert RS.contrast_choice(None, "x", [], q, [1], texts) is None
    assert not RS.has_reason_structure(texts[1])


def test_해결_방법을_물으면_해결_주장도_이유로_본다():
    class C:
        def __init__(self, kind, s, o, q):
            self.kind, self.subject_id, self.object_ids, self.evidence = kind, s, o, [ClaimQuote(2, q)]

    class Doc:
        claims = [C("solve", "fix", ["pain"], "| 긴 대기 | 번호표 알림 도입 |"), C("cause", "pain", ["churn"], "긴 대기 때문에 손님이 떠난다")]

    nodes = [node("pain", "긴 대기", [2]), node("fix", "번호표 알림", [2])]
    got = RS.graph_lines(Doc, "pain", nodes, "긴 대기를 줄이는 방법의 근거는 무엇인가요?", [2], remedy=True)
    assert {k for _, _, k in got} == {"solve", "cause"}
    got2 = RS.graph_lines(Doc, "pain", nodes, "긴 대기가 생긴 이유는 무엇인가요?", [2], remedy=False)
    assert {k for _, _, k in got2} == {"cause"}


# ---------------------------------------------------------------------------
# 회귀 — 09-29 부스 실측 덱(개인 투자자 수익률 격차) 2장의 **구조**를 그대로 옮겼다. 규칙에는 이 덱의 낱말이 없다.
# ---------------------------------------------------------------------------

BOOTH_SLIDE2 = ("EXECUTIVE SUMMARY\n결론부터: 격차는 종목 선택이 아니라 행동에서 만들어진다\n01\n02\n격차는 실재한다\n"
                "· 개인 평균은 지수 대비 연 4.8%p\n낮음\n· 상위 25% 그룹도 지수를 2.6%p\n하회\n·\n일부의 실수가 아닌 전반적 현상\n"
                "원인은 종목이 아니다\n· 종목 선정 능력과 수익률의 상관은\n약함\n· 매매 회전율은 수익률과 뚜렷한\n역상관\n·\n"
                "최상위 회전율 구간 평균 −3.6%\n무엇을 샀는가가 아니라, 얼마나 자주 사고팔았는가가 결과를 갈랐다\n03\n통제 가능한 변수다\n"
                "· 빈도·기간·종목수·비용은 본인이\n결정\n·\n격차의 상당 부분은 좁힐 수 있음")


def test_회귀_부스_덱_2장_배경과_이유를_가르고_보기는_행동_대_종목_선택():
    texts = {2: BOOTH_SLIDE2}
    q = "개인 투자자의 수익률 격차가 종목 선택이 아닌 행동에서 발생한다고 결론지은 근거는 무엇인가요?"
    ev = RS.evidence(q, [2], texts)
    mixed = ("개인 평균은 지수 대비 연 4.8%p 낮고 상위 25% 그룹도 2.6%p 하회하며, "
             "종목 선정 능력과 수익률의 상관은 약하고 매매 회전율은 수익률과 뚜렷한 역상관이에요.")
    gist, checks = RS.check_gist(mixed, ev)
    assert "4.8%p" not in gist and "2.6%p" not in gist
    assert "무엇을 샀는가가 아니라, 얼마나 자주 사고팔았는가가 결과를 갈랐다" in gist and "−3.6%" in gist
    assert checks == ["gist_background_dropped", "gist_reason_rebuilt"]
    # 「'가지' 쪽인가요, '종목' 쪽인가요?」 → 자료가 세운 대비
    got = RS.contrast_choice(None, "x", [], q, [2], texts)
    assert got is not None and (got.affirmed, got.negated) == ("행동", "종목 선택")


# ---------------------------------------------------------------------------
# 골자 근거 검사 보강 (09-30 대화 감사 §1) — 방향이 반대인 말 · 함께 묶인 표 머리 · 표 항목의 지어낸 순위 · 자료에 없는 것
# ---------------------------------------------------------------------------

def _idx(no: int, text: str):
    from chuckchuck import _grounding as G
    return G, G.build_index({no: slide(no, text)}, [])


def test_방향이_반대인_골자는_자료와_어긋난다():
    # 원예 — 화분과 창의 거리
    G, idx = _idx(4, "빛과 생장\n화분이 창에서 멀어질수록 잎의 생장이 느려지는 경향")
    assert G.gist_problems("화분이 창에서 가까울수록 잎의 생장이 느려지는 경향이 있어요.", idx) == ["direction"]
    assert G.gist_problems("화분이 창에서 멀어질수록 잎의 생장이 느려져요.", idx) == []
    # 매장 — 늘다/줄다, 부정이 든 절은 보지 않는다
    G, idx = _idx(2, "셀프 계산대 도입 뒤 계산 대기 시간이 줄었다")
    assert G.gist_problems("셀프 계산대 도입 뒤 계산 대기 시간이 늘었어요.", idx) == ["direction"]
    assert G.gist_problems("셀프 계산대 도입 뒤 계산 대기 시간이 늘지 않았어요.", idx) == []


def test_함께_묶인_표_머리에_한_행의_값을_붙이면_어긋난다():
    # 전시 기획 — 관람 이탈 요인 표
    G, idx = _idx(5, "관람을 끊는 요인\n| 대기 행렬 | 입장 전 이탈 |\n| 어두운 조명 | 작품 앞 체류 감소 |\n| 소음 | 해설 청취 방해 |")
    assert G.gist_problems("대기 행렬과 소음은 해설 청취 방해를 일으켜요.", idx) == ["table"]
    assert G.gist_problems("소음은 해설 청취를 방해해요.", idx) == []


def test_표_항목끼리_자료에_없는_순위를_지으면_어긋난다():
    G, idx = _idx(5, "관람을 끊는 요인\n| 대기 행렬 | 입장 전 이탈 |\n| 어두운 조명 | 작품 앞 체류 감소 |\n| 소음 | 해설 청취 방해 |")
    assert "compare" in G.gist_problems("대기 행렬과 소음이 가장 큰 영향을 줘요.", idx)


def test_F08_방향이_반대인_골자는_자료_줄로_다시_쓰고_검사를_남긴다():
    deck = SlideDoc(file_name="plant.pptx", total_slides=2, slides=[
        slide(1, "실내 원예 관찰\n화분 위치와 생장"),
        slide(2, "빛과 생장\n화분이 창에서 멀어질수록 잎의 생장이 느려지는 경향\n관찰 기간 8주"),
    ])
    g = graph_of("plant.pptx", [node("root", "실내 원예", [1, 2], depth=1, weight=1.0), node("light", "창과의 거리", [2])])
    triage = QaTriage(file_name="plant.pptx", marks=[TriageMark(node_id="light", rank=1, source="core_weight", severity=1, doc_weight=1.0)])
    llm = ScriptedLLM({"questions": [{"node_id": "light", "question": "창과의 거리는 잎의 생장과 어떤 관계인가요?",
                                      "answer_gist": "화분이 창에서 가까울수록 잎의 생장이 느려지는 경향이 있어요."}]})
    q = build_questions(g, triage, track="1", slidedoc=deck, llm=llm).questions[0]
    assert "가까울수록" not in q.answer_gist and "멀어질수록" in q.answer_gist
    assert {"gist_rebuilt", "gist_direction_flipped"} <= set(q.basis.checks)


def test_F08_이유가_자료에_없다고_하면_기대_답도_자료_범위에서():
    deck = SlideDoc(file_name="plant.pptx", total_slides=1, slides=[slide(1, "관찰 결과\n8주 동안 잎 수가 두 배로 늘었다")])
    g = graph_of("plant.pptx", [node("root", "관찰 결과", [1], depth=1, weight=1.0), node("leaf", "잎 수", [1])])
    triage = QaTriage(file_name="plant.pptx", marks=[TriageMark(node_id="leaf", rank=1, source="core_weight", severity=1, doc_weight=1.0)])
    llm = ScriptedLLM({"questions": [{"node_id": "leaf", "question": "잎 수는 어떤 방법으로 셌나요?",
                                      "why": "측정 방법이 자료에 명시되지 않아 확인이 필요해요.",
                                      "answer_gist": "매주 같은 시간에 잎을 하나씩 세고 사진으로 기록했어요."}]})
    q = build_questions(g, triage, track="1", slidedoc=deck, llm=llm).questions[0]
    assert "자료에 나와 있지 않아요" in q.answer_gist and "사진으로 기록" not in q.answer_gist
    assert "gist_out_of_deck" in q.basis.checks
