"""
WP-P (09-30 감사 G-A9·G-A23·G-A31·G-A32) — 문헌 검색(F-24)·리허설 기억(F-25)이 맞고, 아무 덱에나 통하고, 정직한가.
네트워크·LLM 없이 돈다. 덱은 여러 분야의 가상 덱이다 (공유 자전거 · 동네 도서관 · 고객 상담 RAG · 도시 농업) —
튜닝에 쓴 덱의 낱말은 쓰지 않는다.

- F-25 (G-A23): (a) 서버가 만든 질문으로 채점한 턴·자료와 대조한 결손만 (b) stalled 는 qa_passed·close_reason 에 맞춘다
  (c) 반대 개념(「부족」↔「부족 해소」)은 잇지 않는다 (d) 이름 하나(「비용」)가 같다고 다른 발표의 기억을 잇지 않는다
- F-24 (G-A31) 상투어(연구·효과·방법 / research·impact·effect)만 겹친 논문은 버린다
- F-24 (G-A32) 번역 응답을 순서로 붙이지 않는다 — 못 맞춘 개념은 검색하지 않고 까닭을 status 에
- 통로 (G-A9) 통로마다 동시 요청 수·간격, 429 는 다 같이 쉼, 시간 예산 안의 부분 결과 + status
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from chuckchuck._deck_claims import deck_from_slidedoc
from chuckchuck.contracts import (
    ConceptGraph,
    ConceptMemory,
    ConceptNode,
    MemoryDoc,
    PaperDoc,
    PaperError,
    PaperRef,
    Slide,
    SlideBlock,
    SlideDoc,
    memory_key,
    memory_similarity,
)
from chuckchuck.f24_papers import QUERY_SYSTEM_PROMPT, _korean_floor, _profile_of, _query_floor, _translate_queries, build_papers
from chuckchuck.f25_memory import build_memory, point_on_deck
from chuckchuck.providers import scholar_impl as si
from chuckchuck.providers.llm_base import LLMProvider
from chuckchuck.providers.scholar_base import ScholarCallError, ScholarProvider, SearchHits, deadline_scope


# ---------------------------------------------------------------------------
# 헬퍼 — 기억
# ---------------------------------------------------------------------------

def turn(label, verdict="partial", score=55, *, qid="", node_id="", at=1.0, missing=(), give_up=False,
         source="server", grounded=True, close_reason="", quote="", hints=()):
    """브리지(b675afd~)가 qa_turns 에 적는 한 줄. source=""·grounded=None 이면 옛 기록 모양."""
    qid = qid or f"q-{memory_key(label)}"
    q = {"id": qid, "node_id": node_id or f"n-{memory_key(label)}", "label": label, "question": f"{label}은 왜 그런가요?"}
    if quote:
        q["evidence_quote"] = quote
    j = {"verdict": verdict, "score": score, "missing_points": list(missing), "coach_stage": "narrow" if give_up else ""}
    if grounded is not None:
        j["grounded_on_deck"] = grounded
    if close_reason:
        j["close_reason"] = close_reason
    ev = {"at": at, "question_id": qid, "give_up": give_up, "hints_shown": list(hints), "question": q, "answer": "…",
          "prior_answers": [], "judgement": j}
    if source:
        ev["question_source"] = source
    return ev


def named(m, label):
    """만든 기억에서 이름으로 꺼내 본다 (검사용 — `MemoryDoc.concept` 은 scoped 가 아니면 지문 있는 기억을 이름만으로 안 준다)."""
    return next(c for c in m.concepts if c.label == label)


def session(sid, at, *turns_, title="발표"):
    return {"session_id": sid, "at": at, "title": title, "turns": list(turns_)}


def graph_of(*labels, file_name="deck.pdf"):
    return ConceptGraph(file_name=file_name, total_slides=10, nodes=[
        ConceptNode(id=f"n-{memory_key(lab)}", label=lab, slide_nos=[i + 1], weight=1.0 - i * 0.05) for i, lab in enumerate(labels)])


def slide(no, *lines):
    return Slide(slide_no=no, title=lines[0] if lines else "", blocks=[SlideBlock(category="paragraph", text="\n".join(lines))])


BIKE = ("대여소 부족", "이용 요금", "출퇴근 수요", "비용", "안전 사고")          # 공유 자전거 활성화
LIBRARY = ("비용", "야간 이용자", "사서 인력", "운영 시간", "안전 관리")       # 동네 도서관 야간 개방


# ---------------------------------------------------------------------------
# F-25 (a) — 믿을 수 있는 턴 · 자료가 받치는 결손만
# ---------------------------------------------------------------------------

def test_옛_기록과_본문_질문_턴은_기억에_넣지_않고_요약에는_세션만_남는다():
    m = build_memory([session("s1", 100.0,
                              turn("이용 요금", "good", 85, source=""),              # 옛 기록 — 출처 없음
                              turn("출퇴근 수요", "good", 90, source="client"),      # 본문 질문으로 채점 (R4 변조 가능)
                              turn("대여소 부족", "partial", 55, missing=["대여소 간 거리"]))])
    assert [c.label for c in m.concepts] == ["대여소 부족"]
    assert m.concept("이용 요금") is None and m.concept("출퇴근 수요") is None
    s = m.sessions[0]
    assert (s.questions, s.good, s.partial) == (1, 0, 1)                    # 변조될 수 있던 good 두 개를 세지 않는다
    assert "확인할 수 없는 기록 2턴" in m.note


def test_결손은_자료와_대조한_판정의_것만_남는다():
    m = build_memory([session("s1", 100.0,
                              turn("대여소 부족", "partial", 50, missing=["대여소 간 거리"], grounded=True, at=1),
                              turn("이용 요금", "partial", 50, missing=["정기권 할인 폭"], grounded=False, at=2),
                              turn("안전 사고", "wrong", 20, missing=["헬멧 착용률"], grounded=None, at=3))])
    assert named(m, "대여소 부족").missing_points == ["대여소 간 거리"]
    assert named(m, "이용 요금").missing_points == []                         # 본문 없이 채점 — 대조 못 한 결손
    assert named(m, "안전 사고").missing_points == []                         # 대조 여부를 모르는 결손
    assert named(m, "이용 요금").attempts == 1                                # 판정 자체는 센다


def test_이번_자료를_주면_결손을_그_자료와_다시_대조한다():
    deck = SlideDoc(file_name="bike.pdf", total_slides=3, slides=[
        slide(1, "공유 자전거 대여소 부족", "대여소 간 거리가 평균 900m 로 멀다"),
        slide(2, "이용 요금", "정기권은 월 5,000원"),
    ])
    rehearsals = [session("s1", 100.0,
                          turn("대여소 부족", "partial", 50, missing=["대여소 간 거리", "야간 조명 설치 계획"], at=1),
                          turn("이용 요금", "partial", 50, missing=["정기권 월 5,000원", "정기권 월 9,000원"], at=2))]
    m = build_memory(rehearsals, slidedoc=deck)
    assert named(m, "대여소 부족").missing_points == ["대여소 간 거리"]       # 자료에 없는 계획은 버린다
    assert named(m, "이용 요금").missing_points == ["정기권 월 5,000원"]      # 자료에 없는 숫자는 버린다
    assert point_on_deck("대여소 간 거리를 구체적으로 언급", deck_from_slidedoc(deck))       # 판정 어휘(구체·언급)는 내용이 아니다


# ---------------------------------------------------------------------------
# F-25 (b) — stalled 는 통과(qa_passed)에, cleared 는 설득(close_reason good)에
# ---------------------------------------------------------------------------

def test_70점대_통과는_막힌_개념이_아니고_3라운드_출구는_설득이_아니다():
    m = build_memory([session("s1", 100.0,
                              turn("이용 요금", "partial", 74, at=1),                                  # 통과 (70~79)
                              turn("안전 사고", "partial", 72, at=2, close_reason="rounds"),           # 3라운드 통과선 출구
                              turn("출퇴근 수요", "partial", 55, at=3, close_reason="guard"),          # 가드에 막힌 채 닫힘
                              turn("대여소 부족", "good", 85, at=4, close_reason="good"),
                              turn("비용", "wrong", 80, at=5))])                                       # 등급 구간: wrong 은 39 까지
    by = {c.label: c for c in m.concepts}
    assert not by["이용 요금"].stalled and not by["이용 요금"].cleared and by["이용 요금"].passes == 1
    assert not by["안전 사고"].stalled and not by["안전 사고"].cleared and by["안전 사고"].closes == {"rounds": 1}
    assert by["출퇴근 수요"].stalled and by["출퇴근 수요"].closes == {"guard": 1}
    assert by["대여소 부족"].cleared and not by["대여소 부족"].stalled and by["대여소 부족"].closes == {"good": 1}
    assert by["비용"].stalled and by["비용"].passes == 0
    assert {c.label for c in m.stalled} == {"출퇴근 수요", "비용"}
    assert [c.label for c in m.concepts][:2] == ["비용", "출퇴근 수요"]          # 막힌 개념이 앞 (최근 순)


def test_passes_가_없는_옛_기억은_예전_규칙이다():
    old = ConceptMemory.from_dict({"key": "비용", "label": "비용", "attempts": 2, "best_verdict": "partial"})
    assert old.stalled and old.passes == 0 and old.deck_keys == []
    again = ConceptMemory.from_dict(json.loads(json.dumps(old.to_dict())))
    assert again.to_dict() == old.to_dict()


# ---------------------------------------------------------------------------
# F-25 (c) — 반대 개념은 잇지 않는다 (글자 차이의 성격을 본다)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("a,b,linked", [
    ("알림의 주의 비용", "알림 주의 비용", True),           # 조사만 다르다
    ("도서관의 운영 시간", "도서관 운영 시간", True),
    ("야간 이용자", "야간 이용자들", True),
    ("Retrieval latency", "Retrieval latencies", True),
    ("Attention residue", "attention residue task", True),   # 내용 덧붙임 — 겹침이 충분
    ("대여소 부족", "대여소 부족 해소", False),               # 부족 ↔ 부족 해소
    ("인력 부족", "인력 부족 해결", False),
    ("사서 인력", "사서 인력 감축", False),
    ("상위 10% 이용자", "하위 10% 이용자", False),           # 한 낱말 치환 = 반대말
    ("손실 노선", "수익 노선", False),
    ("비대면 상담", "대면 상담", False),                      # 부정 접두
    ("불확실성", "확실성", False),
    ("단기 효과", "장기 효과", False),
    ("온라인 수업", "오프라인 수업", False),
    ("supervised retrieval", "unsupervised retrieval", False),
    ("linear cost model", "nonlinear cost model", False),
    ("hallucination rate", "hallucination rate reduction", False),
])
def test_이름_잇기는_표기_차이만_넘고_반대_개념은_막는다(a, b, linked):
    assert (memory_similarity(memory_key(a), memory_key(b)) >= 0.6) is linked
    assert (memory_similarity(a, b) >= 0.6) is linked            # 이름을 그대로 넣어도 같다


def test_지난번_부족_기억이_이번_부족_해소_노드로_가지_않는다():
    m = build_memory([session("s1", 100.0,
                              turn("대여소 부족", "wrong", 20, at=1, missing=["대여소 간 거리"]),
                              turn("이용 요금", "partial", 50, at=2), turn("출퇴근 수요", "partial", 50, at=3),
                              turn("비용", "partial", 50, at=4))])
    g = graph_of("대여소 부족 해소", "이용 요금", "출퇴근 수요", "비용", "안전 사고")      # 이번 그래프에는 「부족 해소」 만 있다
    by = m.by_node(g)
    assert "n-대여소부족해소" not in by
    assert by["n-이용요금"].label == "이용 요금"


# ---------------------------------------------------------------------------
# F-25 (d) — 같은 이름이라도 다른 발표의 기억은 잇지 않는다
# ---------------------------------------------------------------------------

def two_decks():
    return [
        session("bike1", 100.0, *(turn(lab, "partial", 50, at=100 + i, missing=["대여소 간 거리"] if lab == "비용" else ())
                                  for i, lab in enumerate(BIKE[:4]))),
        session("lib1", 200.0, *(turn(lab, "good" if lab == "비용" else "partial", 85 if lab == "비용" else 50, at=200 + i)
                                 for i, lab in enumerate(LIBRARY[:4]))),
    ]


def test_두_발표가_비용을_같이_물어도_기억은_발표마다_따로다():
    m = build_memory(two_decks())
    costs = [c for c in m.concepts if c.key == memory_key("비용")]
    assert len(costs) == 2 and {tuple(c.deck_keys) for c in costs} == {
        tuple(sorted(memory_key(x) for x in BIKE[:4])), tuple(sorted(memory_key(x) for x in LIBRARY[:4]))}
    assert m.concept("비용") is None                                   # 이름만으로는 어느 발표의 것인지 모른다

    lib = m.by_node(graph_of(*LIBRARY))["n-비용"]
    assert lib.cleared and lib.missing_points == []                     # 도서관 발표의 「비용」 은 설득했다
    bike = m.by_node(graph_of(*BIKE))["n-비용"]
    assert bike.stalled and bike.missing_points == ["대여소 간 거리"]
    other = graph_of("비용", "수확량", "옥상 텃밭", "물 사용량", "토양 관리")    # 처음 보는 발표 — 「비용」 하나만 같다
    assert m.by_node(other) == {}


def test_이번_발표를_알려_주면_다른_발표의_리허설은_요약까지_뺀다():
    m = build_memory(two_decks(), graph=graph_of(*LIBRARY))
    assert [s.session_id for s in m.sessions] == ["lib1"]
    assert m.concept("비용").cleared and all(memory_key("대여소 부족") not in c.deck_keys for c in m.concepts)
    assert "다른 발표의 리허설 1번" in m.note


def test_자료를_고친_판도_핵심_개념_이름이_남으면_잇는다():
    m = build_memory([session("bike1", 100.0, *(turn(lab, "partial", 50, at=100 + i) for i, lab in enumerate(BIKE)))])
    revised = graph_of("대여소 부족", "이용 요금", "출퇴근 시간대 수요", "비용", "안전 사고 예방 교육")   # 둘은 이름이 바뀌었다
    by = m.by_node(revised)
    assert {by[k].label for k in ("n-대여소부족", "n-이용요금", "n-비용")} == {"대여소 부족", "이용 요금", "비용"}


def test_한_개념만_물은_리허설은_이름만으로_잇지_않고_근거_인용이_이번_자료에_있으면_잇는다():
    # 09-30 리뷰: 노드 id 는 LLM 이 붙인 영문 슬러그라(「비용」→ cost) 다른 발표와 겹친다 — 지문에 다른 이름이 없으면 안 잇는다
    line = "야간 개방 시 월 운영 비용이 1,200만 원 늘어난다"
    m = build_memory([session("s1", 100.0, turn("비용", "wrong", 20, node_id="cost", quote=line))])
    assert m.concepts[0].deck_keys == [memory_key("비용")] and not m.scoped
    lib = ConceptGraph(file_name="lib.pdf", total_slides=3, nodes=[ConceptNode(id="cost", label="비용")])
    assert m.by_node(lib) == {} and m.concept("비용") is None
    deck = SlideDoc(file_name="lib.pdf", total_slides=3, slides=[slide(2, "운영 비용", line)])
    scoped = build_memory([session("s1", 100.0, turn("비용", "wrong", 20, node_id="cost", quote=line))], graph=lib, slidedoc=deck)
    assert scoped.scoped and scoped.by_node(lib)["cost"].label == "비용" and scoped.concept("비용").stalled
    other = SlideDoc(file_name="farm.pdf", total_slides=3, slides=[slide(2, "비용", "텃밭 조성 비용은 평당 3만 원")])
    assert build_memory([session("s1", 100.0, turn("비용", "wrong", 20, node_id="cost", quote=line))],
                        graph=lib, slidedoc=other).concepts == []

def test_근거_인용이_같은_리허설은_물은_개념이_달라도_한_발표로_묶는다():
    line = "야간 개방 시 월 운영 비용이 1,200만 원 늘어난다"
    m = build_memory([session("a", 100.0, turn("비용", "partial", 50, quote=line, at=1)),
                      session("b", 200.0, turn("운영 시간", "partial", 50, quote=line, at=2))])
    assert {tuple(c.deck_keys) for c in m.concepts} == {tuple(sorted([memory_key("비용"), memory_key("운영 시간")]))}


def test_같은_덱에서_서로_다른_개념을_물은_리허설도_이름_셋이_겹치면_한_발표다():
    ten = ["노선 A", "노선 B", "노선 C", "환승역", "배차 간격", "혼잡도", "요금 체계", "심야 버스", "정류장 간격", "승객 수"]
    first = session("t5", 100.0, *(turn(lab, "partial", 50, at=100 + i) for i, lab in enumerate(ten[:6])))
    second = session("t10", 200.0, *(turn(lab, "partial", 50, at=200 + i) for i, lab in enumerate(ten[3:])))   # 셋만 겹친다
    m = build_memory([first, second])
    assert len({tuple(c.deck_keys) for c in m.concepts}) == 1 and named(m, "환승역").asked == 2


def test_이번_그래프에_이어지는_묶음은_하나로_합친다():
    # 근거 인용도 이름 셋도 안 겹쳐 두 묶음으로 갈렸지만, 둘 다 이번 발표의 그래프에 이어진다
    a = session("a", 100.0, *(turn(lab, "partial", 50, at=100 + i) for i, lab in enumerate(["야간 이용자", "사서 인력", "비용"])))
    b = session("b", 200.0, *(turn(lab, "wrong", 20, at=200 + i) for i, lab in enumerate(["비용", "운영 시간", "안전 관리"])))
    assert len({tuple(c.deck_keys) for c in build_memory([a, b]).concepts}) == 2
    m = build_memory([a, b], graph=graph_of(*LIBRARY))
    assert len({tuple(c.deck_keys) for c in m.concepts}) == 1
    cost = m.concept("비용")
    assert cost.asked == 2 and cost.verdicts == {"partial": 1, "wrong": 1} and [s.session_id for s in m.sessions] == ["b", "a"]


def test_판정은_다른_발표의_같은_이름_기억으로_코칭_단계를_바꾸지_않는다():
    # 09-30 리뷰 HIGH: f09 는 그래프로 못 이은 노드를 이름(concept)으로 다시 찾는다 — 자전거 발표에서 포기한 「비용」 이
    # 도서관 발표의 「비용」 질문을 발판(scaffold)부터 시작하게 했다. 이번 발표에 맞춰 거르지 않은 기억은 이름만으로 안 준다.
    from chuckchuck.contracts import Question
    from chuckchuck.f09_judge import coach_stuck

    bike = build_memory([session("bike1", 100.0, turn("비용", "unknown", 0, give_up=True, at=101),
                                 turn("대여소 부족", "partial", 50, at=102), turn("이용 요금", "partial", 50, at=103))])
    q = Question(id="q01-n-비용", node_id="n-비용", label="비용", question="야간 개방 비용은 어떻게 마련하나요?", why="w",
                 hint="h", answer_gist="구청 예산과 기부금으로 마련해요", severity=2)
    assert coach_stuck(q, graph=graph_of(*LIBRARY), memory=bike, llm="mock").coach_stage == "narrow"
    assert coach_stuck(q, graph=graph_of(*BIKE[:3], "비용"), memory=bike, llm="mock").coach_stage == "scaffold"


def test_빈_이름끼리는_잇지_않고_자기_이름의_표기_변형은_다른_이름으로_세지_않는다():
    from chuckchuck.contracts import memory_presentation_fit
    m = MemoryDoc.from_dict({"concepts": [{"key": "", "label": "…", "attempts": 1}]})
    assert m.by_node(ConceptGraph(file_name="x", total_slides=1, nodes=[ConceptNode(id="dots", label="---")])) == {}
    # 「비용」 과 「비용의」 만 물은 발표는 한 개념만 물은 것이다
    assert memory_presentation_fit(["비용", "비용의"], "비용", ["비용"]) == (0, 0)
    assert memory_presentation_fit(["비용", "운영시간"], "비용", ["비용", "운영시간"]) == (1, 1)


def test_지문이_없는_옛_기억은_예전처럼_이름으로_잇는다():
    old = MemoryDoc.from_dict({"concepts": [{"key": "비용", "label": "비용", "attempts": 1, "best_verdict": "wrong"}]})
    assert old.by_node(graph_of("비용", "수확량"))["n-비용"].label == "비용"


# ---------------------------------------------------------------------------
# F-24 (G-A31) — 상투어만 겹친 논문은 버린다
# ---------------------------------------------------------------------------

def ref(title, abstract="", **kw):
    return PaperRef(id="", kind="scholar", title=title, abstract=abstract, **kw)


FARM = ConceptNode(id="rooftop", label="옥상 텃밭 수확량", slide_nos=[3], summary="옥상 텃밭의 상추 수확량을 비교했다")
FARM_TEXT = {3: "옥상 텃밭 상추 수확량 비교\n햇빛 노출 시간이 긴 구역이 1.4배 많았다"}


def test_한글_논문이_연구_효과_방법만_겹치면_버린다():
    prof = _profile_of(FARM, FARM_TEXT)
    generic = ref("청소년 스마트 기기 교육의 효과 분석 연구", "본 연구는 방법과 결과를 비교 분석하였다")
    assert not _korean_floor(generic, prof)
    context_only = ref("상추 재배 환경과 햇빛 노출 시간", "노출 시간이 길수록 잎이 컸다")         # 라벨 낱말이 없다
    assert not _korean_floor(context_only, prof)
    good = ref("도시 옥상 텃밭의 채소 수확량 비교", "상추 수확량은 햇빛 노출 시간에 따라 달랐다")
    assert _korean_floor(good, prof)
    deck_line = ref("옥상 구역별 햇빛 노출 비교", "구역마다 노출 시간을 쟀다")                  # 라벨 한 낱말 + 근거 장 자료 줄 낱말
    assert _korean_floor(deck_line, prof)
    assert not _korean_floor(deck_line, _profile_of(FARM))                              # 자료 줄 없이는 라벨 한 낱말뿐


def test_영문_논문이_학술_상투어만_겹치면_버린다():
    q = "rooftop garden lettuce yield sunlight exposure"
    generic = ref("The impact of research methods on study outcomes: an analysis of effects",
                  "We review approaches and findings across many studies.")
    assert not _query_floor(generic, q)
    one_word = ref("Sunlight and mood", "exposure to daylight")                     # 변별 어간의 절반이 안 된다
    assert not _query_floor(one_word, q)
    good = ref("Lettuce yield in rooftop gardens under varying sunlight", "Rooftop lettuce yield rose with sunlight exposure.")
    assert _query_floor(good, q)
    assert not _query_floor(good, "research impact effect method study")           # 상투어뿐인 검색어는 근거가 없다


def test_build_papers_는_개념마다_변별_낱말로_거르고_status_에_남긴다():
    g = ConceptGraph(file_name="farm.pdf", total_slides=5, nodes=[
        ConceptNode(id="rooftop", label="Rooftop garden yield", slide_nos=[3], weight=1.0),
        ConceptNode(id="water", label="Irrigation water use", slide_nos=[4], weight=0.9),
    ])
    hits = {
        "Rooftop garden yield": [ref("Rooftop garden yield under shade", "rooftop garden yield"),
                                 ref("The impact of research on garden policy", "An analysis of effects")],
        "Irrigation water use": [ref("Irrigation water use efficiency in rooftop farms", "irrigation water use")],
    }
    doc = build_papers(g, None, scholar=Fake(hits), llm=NoLLM())
    rows = {r["node_id"]: r for r in doc.status if r["kind"] == "concept"}
    assert (rows["rooftop"]["kept"], rows["rooftop"]["dropped"]) == (1, 1)
    assert rows["water"]["state"] == "ok" and rows["water"]["query_source"] == "label"
    assert [r.node_ids for r in doc.scholar_refs] == [["rooftop"], ["water"]]
    assert "관련성 없음 1건 버림" in doc.note and "검색 실패" not in doc.note


def test_같은_논문이_두_개념에서_나와도_관련된_개념에만_붙는다():
    g = ConceptGraph(file_name="rag.pdf", total_slides=5, nodes=[
        ConceptNode(id="lat", label="Retrieval latency budget", slide_nos=[2], weight=1.0),
        ConceptNode(id="hal", label="Answer hallucination rate", slide_nos=[3], weight=0.9),
    ])
    paper = ref("Reducing retrieval latency budgets in RAG pipelines", "retrieval latency budget", doi="10.1/lat")
    hits = {"Retrieval latency budget": [paper], "Answer hallucination rate": [paper]}
    doc = build_papers(g, None, scholar=Fake(hits), llm=NoLLM())
    assert [r.node_ids for r in doc.scholar_refs] == [["lat"]]
    again = build_papers(g, None, scholar=Fake(hits), llm=NoLLM())
    assert again.to_dict() == doc.to_dict()                                         # 같은 응답이면 같은 문서 (결정적)


# ---------------------------------------------------------------------------
# F-24 (G-A32) — 번역 응답은 id·이름으로만, 못 맞추면 검색하지 않고 까닭을 남긴다
# ---------------------------------------------------------------------------

class Scripted(LLMProvider):
    name = "scripted"

    def __init__(self, reply=None, fail=False):
        self.reply, self.fail, self.users = reply, fail, []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.users.append(user)
        if self.fail:
            raise RuntimeError("llm down")
        return json.dumps(self.reply or {}, ensure_ascii=False)


class NoLLM(Scripted):
    def complete(self, **kw):
        raise AssertionError("영문 개념은 번역하지 않는다")


class Fake(ScholarProvider):
    name = "fake"

    def __init__(self, hits=None, delay=None, errors=None):
        self.hits, self.delay, self.errors, self.queries = hits or {}, delay or {}, errors or {}, []

    def search(self, query, *, limit=5):
        self.queries.append(query)
        time.sleep(self.delay.get(query, 0.0))
        if query in self.errors:
            raise self.errors[query]
        return [PaperRef.from_dict(r.to_dict()) for r in self.hits.get(query, [])][:limit]


LIB_GRAPH = ConceptGraph(file_name="lib.pdf", total_slides=6, nodes=[
    ConceptNode(id="night", label="야간 이용자", slide_nos=[2], summary="퇴근 뒤 이용자가 늘었다", weight=1.0),
    ConceptNode(id="staff", label="사서 인력", slide_nos=[3], summary="야간 사서 배치", weight=0.9),
])


def test_순서를_바꾼_번역_응답은_다른_개념에_검색어를_붙이지_않는다():
    llm = Scripted({"queries": [{"node_id": "c1", "query": "library staffing night shift"},       # 예시 id — 주인 모름
                                {"node_id": "c2", "query": "public library evening visitors"}]})
    fake = Fake({"library staffing night shift": [ref("Night shift staffing in public libraries", "library staffing night shift")]})
    doc = build_papers(LIB_GRAPH, None, scholar=fake, llm=llm)
    assert fake.queries == [] and doc.scholar_refs == []                             # 순서로 짐작해 붙이지 않았다
    rows = {r["node_id"]: r for r in doc.status if r["kind"] == "concept"}
    assert {r["state"] for r in rows.values()} == {"no_query"} and {r["reason"] for r in rows.values()} == {"unmatched"}
    assert "검색어 번역 실패로 개념 2개 검색 실패" in doc.note                          # 브리지가 폴백으로 알아본다


def test_번역은_id_또는_표기만_다른_이름으로_받는다():
    out, failed = _translate_queries(
        [("night", "야간 이용자 — 요약"), ("staff", "사서 인력 — 요약")],
        Scripted({"queries": [{"node_id": "staff", "query": "library night staffing"},
                              {"node_id": "zz", "label": "야간의 이용자", "query": "evening library visitors"}]}), None)
    assert out == {"staff": "library night staffing", "night": "evening library visitors"} and failed == {}


def test_LLM_이_죽으면_개념마다_까닭이_남고_영문_낱말이_넉넉한_개념만_대신_검색한다():
    g = ConceptGraph(file_name="rag.pdf", total_slides=4, nodes=[
        ConceptNode(id="rag", label="RAG 파이프라인 지연", summary="LLM 응답 전 retrieval 단계가 느리다", slide_nos=[1], weight=1.0),
        ConceptNode(id="cs", label="상담 만족도", summary="상담 뒤 설문 점수", slide_nos=[2], weight=0.9),
    ])
    fake = Fake()
    doc = build_papers(g, None, scholar=fake, llm=Scripted(fail=True))
    rows = {r["node_id"]: r for r in doc.status if r["kind"] == "concept"}
    assert rows["rag"]["query_source"] == "ascii" and rows["rag"]["reason"] == "llm_error"
    assert rows["cs"]["query_source"] == "none" and rows["cs"]["state"] == "no_query"
    assert len(fake.queries) == 1 and "검색 실패" in doc.note


# ---------------------------------------------------------------------------
# 통로 (G-A9) — 동시 요청 수·간격, 429 는 다 같이 쉼, 마감 안에서만
# ---------------------------------------------------------------------------

class Res:
    def __init__(self, status=200, payload=None, content=b"", headers=None, text=""):
        self.status_code, self._payload, self.content, self.headers, self.text = status, payload, content, headers or {}, text

    def json(self):
        return self._payload


@pytest.fixture
def lanes(monkeypatch):
    """요청 줄 간격을 짧게(테스트 시간) — 규칙은 같다."""
    monkeypatch.setattr(si, "LANES", {"arxiv": (1, 0.08), "openalex": (2, 0.0), "semanticscholar": (1, 0.08),
                                      "europepmc": (2, 0.0), "crossref": (2, 0.0)})
    si.reset_lanes()
    yield
    si.reset_lanes()


def test_arxiv_는_몇_스레드가_불러도_한_번에_하나씩_간격을_두고_간다(monkeypatch, lanes):
    starts, active, peak = [], [0], [0]
    lock = threading.Lock()

    def get(url, params=None, timeout=None, headers=None):
        with lock:
            starts.append(time.monotonic())
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.02)
        with lock:
            active[0] -= 1
        return Res(content=b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>')

    monkeypatch.setattr(si.requests, "get", get)
    threads = [threading.Thread(target=lambda: si.ArxivScholar().search("dense retrieval", limit=1)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 1                                     # 09-30 G-A9: 예전엔 4병렬
    gaps = [b - a for a, b in zip(sorted(starts), sorted(starts)[1:])]
    assert len(starts) >= 4 and min(gaps) >= 0.07


def test_429_를_받으면_그_통로를_부르는_모두가_쉰다(monkeypatch, lanes):
    monkeypatch.setattr(si.time, "sleep", lambda s: None)          # 백오프 자체는 건너뛴다 — 줄(cool_down)이 남는지만 본다
    calls = []
    monkeypatch.setattr(si.requests, "get", lambda url, params=None, timeout=None, headers=None:
                        calls.append(time.monotonic()) or Res(429, headers={"Retry-After": "0.3"}, text="slow"))
    with pytest.raises(ScholarCallError) as e:
        si.SemanticScholarScholar().search("evening library visitors")
    assert e.value.kind == "rate_limited" and len(calls) == 2
    t0 = time.monotonic()
    monkeypatch.setattr(si.requests, "get", lambda *a, **k: Res(payload={"data": []}))
    si.SemanticScholarScholar().search("evening library visitors")
    assert time.monotonic() - t0 >= 0.2                             # 다른 호출도 Retry-After 만큼 줄에서 기다렸다


def test_429_뒤_재시도도_통로_간격을_지킨다(monkeypatch, lanes):
    # 09-30 리뷰 HIGH: 백오프를 마친 재시도가 간격까지 건너뛰어, 네 스레드의 재시도가 arXiv 에 0.05초 간격으로 몰렸다
    monkeypatch.setattr(si.time, "sleep", lambda s: None)
    starts = []
    lock = threading.Lock()

    def get(url, params=None, timeout=None, headers=None):
        with lock:
            starts.append(time.monotonic())
        return Res(429, headers={"Retry-After": "0.1"}, text="slow")

    monkeypatch.setattr(si.requests, "get", get)

    def one():
        with pytest.raises(ScholarCallError):
            si.ArxivScholar().search("retrieval")

    threads = [threading.Thread(target=one) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    gaps = [b - a for a, b in zip(sorted(starts), sorted(starts)[1:])]
    assert len(starts) == 8 and min(gaps) >= 0.07


def test_몇_시간_쉬라는_429_는_다시_묻지_않고_그동안_그_통로에_보내지_않는다(monkeypatch, lanes):
    # 09-30 실측: 키 없는 OpenAlex 가 하루 한도를 다 써 Retry-After 19517 — 예전 코드는 4초 뒤 다시 묻고 다른 검색도 보내 9번 다 429.
    monkeypatch.setattr(si.time, "sleep", lambda s: pytest.fail("몇 시간을 요청 안에서 자면 안 된다"))
    sent = []
    monkeypatch.setattr(si.requests, "get", lambda *a, **k: sent.append(1) or Res(429, headers={"Retry-After": "19517"}, text="budget"))
    for q in ("evening library visitors", "library night staffing"):
        with pytest.raises(ScholarCallError) as e:
            si.OpenAlexScholar().search(q)
        assert e.value.kind == "rate_limited"
    assert len(sent) == 1                                          # 둘째 검색은 보내지도 않았다 (벤더가 쉬라고 한 동안)


def test_줄이_마감보다_길면_보내지_않고_throttled_로_알린다(monkeypatch, lanes):
    monkeypatch.setattr(si, "LANES", {"arxiv": (1, 5.0)})
    si.reset_lanes()
    sent = []
    monkeypatch.setattr(si.requests, "get", lambda *a, **k: sent.append(1) or Res(content=b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'))
    si.ArxivScholar().search("retrieval")                          # 첫 요청 — 다음 자리는 5초 뒤
    with deadline_scope(2.0):
        with pytest.raises(ScholarCallError) as e:
            si.ArxivScholar().search("sparse retrieval")
    assert e.value.kind == "throttled" and len(sent) == 1


def test_마감이_지났으면_요청을_보내지_않는다(monkeypatch, lanes):
    monkeypatch.setattr(si.requests, "get", lambda *a, **k: pytest.fail("보내면 안 된다"))
    with deadline_scope(0.0):
        with pytest.raises(ScholarCallError) as e:
            si.OpenAlexScholar().search("evening library visitors")
    assert e.value.kind == "timeout"


class Slow(ScholarProvider):
    def __init__(self, name, refs, delay=0.0, error=None):
        self.name, self.refs, self.delay, self.error = name, refs, delay, error

    def search(self, query, *, limit=5):
        time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return [PaperRef.from_dict(r.to_dict()) for r in self.refs]


def test_여러_통로는_늦은_통로를_기다리지_않고_받은_것과_사정을_돌려준다(capsys):
    q = "evening library visitors"
    fast = Slow("openalex", [ref("Evening library visitors", "evening library visitors", query=q, source="openalex", cited_by=3)])
    slow = Slow("arxiv", [], delay=1.5)
    limited = Slow("europepmc", [], error=ScholarCallError("europepmc 응답 429", kind="rate_limited", provider="europepmc"))
    t0 = time.monotonic()
    with deadline_scope(0.4):
        hits = si.MultiScholar([fast, slow, limited]).search(q, limit=3)
    assert time.monotonic() - t0 < 1.0
    assert isinstance(hits, SearchHits) and [r.title for r in hits] == ["Evening library visitors"]
    assert {s["provider"]: s["state"] for s in hits.status} == {"openalex": "ok", "arxiv": "timeout", "europepmc": "rate_limited"}
    with pytest.raises(ScholarCallError) as e:
        si.MultiScholar([limited, Slow("crossref", [], error=PaperError("boom"))]).search(q)
    assert "모든 통로 실패" in str(e.value) and e.value.kind == "rate_limited" and len(e.value.status) == 2


def test_시간_예산을_넘긴_개념은_기다리지_않고_부분_결과와_까닭을_남긴다():
    g = ConceptGraph(file_name="rag.pdf", total_slides=4, nodes=[
        ConceptNode(id="lat", label="Retrieval latency budget", slide_nos=[1], weight=1.0),
        ConceptNode(id="hal", label="Answer hallucination rate", slide_nos=[2], weight=0.9),
    ])
    fake = Fake({"Retrieval latency budget": [ref("Retrieval latency budget in RAG", "retrieval latency budget")]},
                delay={"Answer hallucination rate": 2.0})
    t0 = time.monotonic()
    doc = build_papers(g, None, scholar=fake, llm=NoLLM(), budget_sec=0.4)
    assert time.monotonic() - t0 < 1.5
    rows = {r["node_id"]: r for r in doc.status if r["kind"] == "concept"}
    assert rows["lat"]["state"] == "ok" and rows["hal"]["state"] == "timeout"
    assert [r.title for r in doc.scholar_refs] == ["Retrieval latency budget in RAG"]
    assert "검색 실패" in doc.note                                  # 브리지가 짧게만 든다 (papers_partial)
    prov = next(r for r in doc.status if r["kind"] == "provider")
    assert (prov["calls"], prov["ok"], prov["timeout"]) == (2, 1, 1)


def test_요청_한도로_아무것도_못_받은_검색은_다시_하게_하고_다른_통로가_답했으면_알림만():
    from demo.bridge import _papers_degraded

    g = ConceptGraph(file_name="rag.pdf", total_slides=4, nodes=[
        ConceptNode(id="lat", label="Retrieval latency budget", slide_nos=[1], weight=1.0),
        ConceptNode(id="hal", label="Answer hallucination rate", slide_nos=[2], weight=0.9),
    ])
    hit = ref("Retrieval latency budget in RAG", "retrieval latency budget")
    # 통로가 하나뿐이고 그 통로가 줄에 밀려 한 개념을 못 물었다 — 결과 없음이 아니라 다시 할 일이다 (09-30 리뷰)
    fake = Fake({"Retrieval latency budget": [hit]},
                errors={"Answer hallucination rate": ScholarCallError("fake 요청 한도", kind="throttled", provider="fake")})
    doc = build_papers(g, None, scholar=fake, llm=NoLLM())
    rows = {r["node_id"]: r for r in doc.status if r["kind"] == "concept"}
    assert rows["hal"]["state"] == "throttled" and "요청 한도로 1건 검색 실패" in doc.note
    assert _papers_degraded(doc) == "papers_partial"
    # 여러 통로 중 하나만 참았고 다른 통로가 답했다 — 알림만, 실패 아님
    q = "Answer hallucination rate"
    multi = si.MultiScholar([
        Slow("openalex", [ref("Answer hallucination rate in RAG", "answer hallucination rate", query=q, cited_by=4)]),
        Slow("arxiv", [], error=ScholarCallError("arxiv 요청 한도", kind="throttled", provider="arxiv")),
    ])
    doc = build_papers(ConceptGraph(file_name="rag.pdf", total_slides=4, nodes=[g.nodes[1]]), None, scholar=multi, llm=NoLLM())
    assert "요청 한도로 1건 건너뜀" in doc.note and "검색 실패" not in doc.note and _papers_degraded(doc) == ""
    # 다른 통로는 「결과 없음」 인데 한 통로가 막혔다 — 개념은 empty 가 아니라 그 까닭으로
    multi = si.MultiScholar([Slow("openalex", []), Slow("arxiv", [], error=ScholarCallError("arxiv 응답 429", kind="rate_limited",
                                                                                              provider="arxiv"))])
    doc = build_papers(ConceptGraph(file_name="rag.pdf", total_slides=4, nodes=[g.nodes[1]]), None, scholar=multi, llm=NoLLM())
    assert [r["state"] for r in doc.status if r["kind"] == "concept"] == ["rate_limited"]


class Odd(ScholarProvider):
    """다른 라이브러리처럼 구는 통로 — None 을 돌려주거나, status 가 정수인 예외를 던진다."""
    name = "odd"

    def search(self, query, *, limit=5):
        if "rate" in query:
            e = RuntimeError("upstream 503")
            e.status = 503
            raise e
        return None


def test_이상한_통로가_있어도_문헌_만들기는_예외를_던지지_않는다():
    g = ConceptGraph(file_name="rag.pdf", total_slides=4, nodes=[
        ConceptNode(id="lat", label="Retrieval latency budget", slide_nos=[1], weight=1.0),
        ConceptNode(id="hal", label="Answer hallucination rate", slide_nos=[2], weight=0.9),
    ])
    doc = build_papers(g, None, scholar=Odd(), llm=NoLLM())
    rows = {r["node_id"]: r["state"] for r in doc.status if r["kind"] == "concept"}
    assert rows == {"lat": "empty", "hal": "error"} and "검색 실패" in doc.note
    from chuckchuck.f24_papers import search_papers
    assert search_papers("Answer hallucination rate", scholar=Odd()).refs == []

def test_PaperDoc_status_는_왕복하고_옛_문서는_빈_목록이다():
    doc = build_papers(LIB_GRAPH, None, scholar=Fake(), llm=Scripted({"queries": [
        {"node_id": "night", "query": "public library evening visitors"}, {"node_id": "staff", "query": "library night staffing"}]}))
    kinds = [r["kind"] for r in doc.status]
    assert kinds.count("concept") == 2 and kinds[-1] == "provider"
    assert PaperDoc.from_dict(json.loads(json.dumps(doc.to_dict(), ensure_ascii=False))).to_dict() == doc.to_dict()
    assert PaperDoc.from_dict({"file_name": "x", "refs": []}).status == []


# ---------------------------------------------------------------------------
# 프롬프트 — 튜닝에 쓴 덱의 낱말이 없다 (과적합 검사와 같은 목록)
# ---------------------------------------------------------------------------

def test_문헌_검색어_프롬프트에_알려진_덱_낱말이_없고_과적합_검사가_깨끗하다():
    from labs.qa_bench.overfit_scan import DECK_WORDS, scan

    words = [w for ws in DECK_WORDS.values() for w in ws]
    assert not [w for w in words if w in QUERY_SYSTEM_PROMPT]
    mine = ("f24_papers.py", "f25_memory.py", "scholar_impl.py", "scholar_base.py", "contracts.py")
    assert not [h for h in scan() if h["file"].endswith(mine)]
