"""
녹음 모드 질문의 꼴과 자리 — 09-30 녹음 대화 감사(docs/review/2026-09-30_QA_녹음대화감사) REC-05·REC-07·REC-11·REC-18·REC-02(번트 Q6).

- 건너뛴 핵심 장 질문은 그 장의 **내용**을 묻는다 — 건너뛴 까닭·그 장의 수치·자료 조각을 실은 LLM 문장은 명세 문장으로 (REC-05)
- 건너뛴 장 하나에 질문 하나 — 대표는 장에서 맡은 자리(식 머리·장 제목)가 먼저, 나머지 개념은 골자에 접고, 그 장에는 함정이 없다 (REC-11)
- 근거가 확인된 약점 질문(모순·건너뛴 장·탐침)이 밀려 있는 동안 함정이 자리를 차지하지 않는다 — 5분·10분 (REC-07 조정자 주)
- 녹음 모드의 「…라고 했는데」 는 녹음에 있는 말만 발표자에게 붙인다 — 자료에서 온 말은 「자료 N장에서 …」 (REC-02 번트 Q6)
- 건너뛴 장 질문의 「발표에서 한 말」 은 건너뛴다는 그 말이다 — 옆 장 문장이 아니라 (REC-18)

**감사에 쓴 덱(교실 환기·어르신 주문 기계·사회인 야구)의 낱말은 넣지 않는다** — 동네 텃밭 물 주기 · 동네 제과점 반죽 발효 · 마을 수영장
강습으로 본다. 규칙이 감사 덱 낱말에 맞춘 것이면 여기서 떨어져야 한다 (마지막 테스트가 규칙 문자열을 훑는다).
"""

import ast
import inspect
import json
import re
import textwrap

import pytest

import chuckchuck.f08_questions as f08
from chuckchuck import build_questions, triage_questions
from chuckchuck.contracts import (
    AlignmentDoc,
    AlignmentItem,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    Probe,
    ClaimQuote,
    SkippedSlide,
    Slide,
    SlideBlock,
    SlideDoc,
    SlideSpeech,
    SpeechBasis,
    Transcript,
    TriageMark,
)
from chuckchuck.providers.llm_base import LLMProvider


class ScriptedLLM(LLMProvider):
    """triage 는 빈 심사(결정적 폴백), 질문은 payload 그대로. 받은 프롬프트를 남긴다."""

    name = "scripted"

    def __init__(self, questions: list[dict] | None = None):
        self.questions = questions or []
        self.prompts: list[str] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.prompts.append(user)
        if "[TASK] qa-triage" in user:
            return json.dumps({"marks": []})
        return json.dumps({"questions": self.questions}, ensure_ascii=False)


def slide(no: int, text: str) -> Slide:
    return Slide(slide_no=no, title="", blocks=[SlideBlock(category="paragraph", text=text)])


def node(id, label, nos, depth=2, parent="root", summary="", weight=0.5, importance="core"):
    return ConceptNode(id=id, label=label, slide_nos=nos, summary=summary, weight=weight, depth=depth,
                       importance=importance, parent_id=None if depth == 1 else parent)


def graph_of(file_name: str, total: int, nodes: list[ConceptNode]) -> ConceptGraph:
    return ConceptGraph(file_name=file_name, total_slides=total, nodes=nodes,
                        edges=[ConceptEdge(from_id=n.parent_id, to_id=n.id, kind="parent") for n in nodes if n.parent_id])


def speech(by: dict[int, str]) -> Transcript:
    return Transcript(full_text=" ".join(by.values()), duration_sec=30.0 * len(by),
                      by_slide=[SlideSpeech(slide_no=k, visit=1, start_sec=(k - 1) * 30.0, end_sec=k * 30.0, text=v)
                                for k, v in by.items()])


def item(nid, verdict, *, by="llm", evidence="", deck_quote="", deck_slide_no=None, doc_weight=0.5, speech_weight=0.5):
    return AlignmentItem(node_id=nid, verdict=verdict, decided_by=by, evidence=evidence, deck_quote=deck_quote,
                         deck_slide_no=deck_slide_no, doc_weight=doc_weight, speech_weight=speech_weight,
                         speech_basis=SpeechBasis(mention_count=1 if verdict == "aligned" else 0))


# ---------------------------------------------------------------------------
# 덱 A — 동네 텃밭 물 주기. 3장 식은 말로 건너뜀(식의 한 칸 「텃밭 면적」 이 식 머리보다 무겁다) · 4장 수치를 다르게 말함
# ---------------------------------------------------------------------------

GARDEN = SlideDoc(file_name="garden.pdf", total_slides=6, slides=[
    slide(1, "동네 텃밭 물 주기\n물을 언제 주느냐가 수확을 가릅니다"),
    slide(2, "왜 물 주기인가\n여름철 텃밭 20곳 중 12곳에서 채소가 시들었습니다"),
    slide(3, "물 사용량 계산\n물 사용량 = 텃밭 면적 × 하루 증발량 × 물 주는 날\n한 번 줄 때 평균 25리터를 씁니다"),
    slide(4, "아침 물 주기 효과\n아침에 물을 준 텃밭은 저녁에 준 텃밭보다 수확량이 30% 많았습니다"),
    slide(5, "한계\n관찰한 텃밭이 8곳뿐입니다"),
    slide(6, "정리\n아침에 물을 주면 같은 물로 더 많이 거둡니다"),
])


def garden_graph(usage_depth: int = 2) -> ConceptGraph:
    parent_of_usage = "root" if usage_depth == 2 else "plan"
    nodes = [
        node("root", "텃밭 물 주기", [1, 6], depth=1, weight=1.0, summary="물을 언제 주느냐가 수확을 가른다"),
        node("need", "채소 시듦", [2], weight=0.6, summary="여름철 20곳 중 12곳"),
        node("usage", "물 사용량", [3], depth=usage_depth, parent=parent_of_usage, weight=0.5),
        node("area", "텃밭 면적", [3], depth=usage_depth + 1, parent="usage", weight=0.8),
        node("evap", "하루 증발량", [3], depth=usage_depth + 1, parent="usage", weight=0.4),
        node("morning", "아침 물 주기", [4], weight=0.9, summary="아침이 저녁보다 수확량 30% 많음"),
        node("limit", "관찰 범위", [5], weight=0.3, importance="support"),
    ]
    if usage_depth == 3:
        nodes.append(node("plan", "물 주기 계획", [3, 6], weight=0.4))
    return graph_of("garden.pdf", 6, nodes)


GARDEN_CUE = "이 장은 물 사용량을 계산한 건데요, 시간 관계상 그냥 넘어갈게요."
GARDEN_SAID = {
    1: "안녕하세요 오늘은 동네 텃밭 물 주기 이야기를 할게요. 물을 언제 주느냐가 수확을 가르거든요.",
    2: "여름에 텃밭 20곳 중 12곳에서 채소가 시들었어요.",
    # 앞 장 끝 문장이 이 장 구간에 들어왔다 (장 경계 추정이 문장 가운데를 자른 경우 — REC-18)
    3: f"그래서 물 주기가 중요해요. {GARDEN_CUE}",
    4: "아침에 물을 준 텃밭이 저녁보다 수확량이 오십 퍼센트나 많았어요.",
    5: "관찰 범위가 좁다는 한계가 있어요.",
    6: "정리하면 아침에 물을 주면 같은 물로 더 많이 거둬요. 감사합니다.",
}
GARDEN_CONTRA = item("morning", "contradiction", by="code", evidence=GARDEN_SAID[4],
                     deck_quote="아침에 물을 준 텃밭은 저녁에 준 텃밭보다 수확량이 30% 많았습니다", deck_slide_no=4,
                     doc_weight=0.9)
# 건너뛴 장의 개념은 무거운 순이 아니라 F-11 이 적은 순서다 — 대표는 자리로 골라야 한다
GARDEN_SKIP = SkippedSlide(slide_no=3, cue=GARDEN_CUE, node_ids=["area", "usage", "evap"])


def garden_alignment(graph: ConceptGraph, **over) -> AlignmentDoc:
    verdicts = {"root": "aligned", "need": "aligned", "usage": "missing", "area": "missing", "evap": "missing",
                "limit": "aligned", "plan": "aligned"}
    items = [GARDEN_CONTRA] + [item(n.id, verdicts[n.id], by="code" if verdicts[n.id] == "missing" else "llm",
                                    evidence=GARDEN_SAID[n.slide_nos[0]] if verdicts[n.id] == "aligned" else "",
                                    doc_weight=n.weight, speech_weight=0.0 if verdicts[n.id] == "missing" else n.weight)
                               for n in graph.nodes if n.id != "morning"]
    doc = AlignmentDoc(file_name="garden.pdf", total_slides=6, items=items, model="scripted", speech_match="matched",
                       speech_overlap=0.45, basis="llm", skipped_slides=[GARDEN_SKIP])
    for k, v in over.items():
        setattr(doc, k, v)
    return doc


def garden_build(track="10", *, questions=None, traps=False, usage_depth=2, transcript=None, alignment=None,
                 slidedoc=GARDEN):
    graph = garden_graph(usage_depth)
    alignment = garden_alignment(graph) if alignment is None else alignment
    transcript = speech(GARDEN_SAID) if transcript is None else transcript
    llm = ScriptedLLM(questions)
    tri = triage_questions(graph, alignment, None, None, transcript=transcript, slidedoc=slidedoc, llm=llm)
    saved = f08.QA_TRACK_TRAPS
    if not traps:
        f08.QA_TRACK_TRAPS = {k: 0 for k in saved}
    try:
        doc = build_questions(graph, tri, track=track, alignment=alignment, transcript=transcript, slidedoc=slidedoc,
                              llm=llm)
    finally:
        f08.QA_TRACK_TRAPS = saved
    return doc, tri, llm


def q_of(doc, node_id):
    return next((q for q in doc.questions if q.node_id == node_id), None)


# ===========================================================================
# REC-11 — 대표는 장의 자리로 · 건너뛴 장 하나에 질문 하나 · 나머지 개념은 골자에 접는다
# ===========================================================================

def test_건너뛴_장의_대표는_무거운_칸이_아니라_식_머리다():
    graph = garden_graph()
    slides = {s.slide_no: s.raw_text for s in GARDEN.slides}
    assert set(f08._skipped_core(garden_alignment(graph), graph, slides)) == {"usage"}      # 식 「물 사용량 = …」 의 좌변
    # 자료 원문이 없어도 그래프의 상위 개념이 대표다 (식의 칸은 식 머리의 하위 개념이다)
    assert set(f08._skipped_core(garden_alignment(graph), graph)) == {"usage"}


def test_식이_없는_장은_장_제목의_개념이_대표다():
    dough = SlideDoc(file_name="dough.pdf", total_slides=3, slides=[
        slide(1, "동네 제과점 반죽\n발효를 지키면 빵이 부풉니다"),
        slide(2, "발효 온도\n반죽은 27도에서 가장 잘 부풉니다\n부피가 두 배가 될 때까지 기다립니다"),
        slide(3, "정리\n온도를 지키면 실패가 줄어듭니다"),
    ])
    graph = graph_of("dough.pdf", 3, [
        node("root", "반죽 관리", [1, 3], depth=1, weight=1.0),
        node("temp", "발효 온도", [2], weight=0.4),
        node("volume", "반죽 부피", [2], weight=0.9),          # 더 무겁지만 장 제목이 부르는 개념이 아니다
    ])
    a = AlignmentDoc(file_name="dough.pdf", total_slides=3, skipped_slides=[
        SkippedSlide(slide_no=2, cue="이 장은 건너뛸게요.", node_ids=["volume", "temp"])],
        items=[item("root", "aligned"), item("temp", "missing", by="code"), item("volume", "missing", by="code")])
    slides = {s.slide_no: s.raw_text for s in dough.slides}
    assert set(f08._skipped_core(a, graph, slides)) == {"temp"}


def test_대표는_그_장이_이름을_부르는_개념에서_고르고_여러_장에_걸친_큰_개념은_접지_않는다():
    """
    F-11 이 건너뛴 장에 적어 준 개념(node_ids)은 「그 장을 근거 장으로 가진 missing 개념」 이라, 여러 장에 걸친 큰 개념이 그 장에 이름도
    없이 들어온다. 대표는 **그 장 글이 부르는** 개념 가운데 자리로 — 식 머리가 가벼운 「생략이 합리적」 개념이어도 그것이 그 장이다.
    그 장이 부르지 않는 큰 개념은 접지 않는다(제 질문을 잃지 않는다). 한 개념이 두 장의 대표가 되지 않는다.
    """
    bakery = SlideDoc(file_name="bakery.pdf", total_slides=4, slides=[
        slide(1, "동네 제과점 반죽 관리\n발효를 지키면 빵이 부풉니다"),
        slide(2, "발효 시간 계산\n발효 시간 = 반죽 무게 × 온도 계수 ÷ 효모 양"),
        slide(3, "보관 방법\n밀폐 용기에 담아 냉장 보관합니다\n3일 안에 씁니다"),
        slide(4, "정리\n발효와 보관을 지키면 버리는 반죽이 줄어듭니다"),
    ])
    graph = graph_of("bakery.pdf", 4, [
        node("root", "반죽 관리", [1, 4], depth=1, weight=1.0),
        node("loss", "버리는 반죽", [1, 2, 3, 4], weight=0.9),                      # 여러 장에 걸친 큰 개념 — 2·3장이 이름을 안 부른다
        node("ftime", "발효 시간", [2], weight=0.12, importance="support"),        # 식 머리 — 가볍고 「생략이 합리적」 판정
        node("weight", "반죽 무게", [2], depth=3, parent="ftime", weight=0.4),
        node("keep", "보관 방법", [3], weight=0.1, importance="support"),          # 3장 제목의 개념
        node("fridge", "냉장 보관", [3], depth=3, parent="keep", weight=0.3),
    ])
    a = AlignmentDoc(file_name="bakery.pdf", total_slides=4, items=[
        item("root", "aligned"), item("loss", "missing", by="code"), item("ftime", "justified_skip"),
        item("weight", "missing", by="code"), item("keep", "justified_skip"), item("fridge", "missing", by="code")],
        skipped_slides=[SkippedSlide(slide_no=2, cue="이 계산은 넘어갈게요.", node_ids=["loss", "weight"]),
                        SkippedSlide(slide_no=3, cue="보관은 건너뛸게요.", node_ids=["loss", "fridge"])])
    slides = {s.slide_no: s.raw_text for s in bakery.slides}
    reps = f08._skipped_core(a, graph, slides)
    assert {rep: s.slide_no for rep, s in reps.items()} == {"ftime": 2, "keep": 3}     # 식 머리 · 장 제목의 개념
    folded = f08._skip_folded(a, graph, reps, None, slides)
    assert folded == {"weight", "fridge"}                                            # 「버리는 반죽」 은 접지 않는다


def test_건너뛴_장은_질문이_하나고_나머지_개념은_골자에_접힌다():
    doc, tri, llm = garden_build("10")
    assert {m.node_id for m in tri.marks} & {"area", "evap"} == set()        # 같은 장의 나머지는 후보에서 빠진다
    on3 = [q for q in doc.questions if 3 in q.slide_nos]
    assert [q.node_id for q in on3] == ["usage"] and on3[0].source == "skipped_slide"
    q = on3[0]
    assert q.slide_nos == [3]                                               # 그 장을 묻는다
    assert "skip_folded" in q.basis.checks
    assert "텃밭 면적" in q.answer_gist and "하루 증발량" in q.answer_gist     # 접은 개념이 골자에 있다
    # 질문 프롬프트도 접은 개념을 이 질문 하나로 묻게 한다
    assert "같은 장의 「텃밭 면적」·「하루 증발량」 도 따로 묻지 않고 이 질문 하나로 묻는다" in llm.prompts[-1]
    assert not {"area", "evap"} & {q.node_id for q in doc.questions}


def test_캐시된_triage_가_다른_대표를_골랐어도_질문은_자리로_고른_대표_하나다():
    graph = garden_graph()
    a = garden_alignment(graph)
    llm = ScriptedLLM()
    old = triage_questions(graph, a, None, None, transcript=speech(GARDEN_SAID), llm=llm)     # 자료 원문 없이 만든 triage
    # 옛 규칙(비중 순)이 고른 대표를 흉내 낸다 — 「텃밭 면적」 이 skipped_slide, 식 머리는 missing
    marks = [TriageMark(node_id=m.node_id, severity=m.severity, trap=False, angle=m.angle,
                        source={"usage": "missing"}.get(m.node_id, m.source), rank=m.rank, doc_weight=m.doc_weight)
             for m in old.marks]
    marks.append(TriageMark(node_id="area", severity=1, trap=False, angle="", source="skipped_slide", rank=0, doc_weight=0.8))
    old.marks = sorted(marks, key=lambda m: m.rank)
    saved = f08.QA_TRACK_TRAPS
    f08.QA_TRACK_TRAPS = {k: 0 for k in saved}
    try:
        doc = build_questions(graph, old, track="10", alignment=a, transcript=speech(GARDEN_SAID), slidedoc=GARDEN, llm=llm)
    finally:
        f08.QA_TRACK_TRAPS = saved
    on3 = [q.node_id for q in doc.questions if set(q.slide_nos) == {3}]
    assert on3 == ["usage"] and q_of(doc, "usage").source == "skipped_slide"


def test_같은_장_같은_틀의_덜_말함은_한_번만_묻는다():
    swim = SlideDoc(file_name="swim.pdf", total_slides=3, slides=[
        slide(1, "마을 수영장 강습\n강습 시간표를 바꾸면 대기가 줄어듭니다"),
        slide(2, "초급반 결과\n초급반 수강생의 완주율이 60%에서 85%로 올랐습니다\n| 반 | 완주율 |\n| 초급 | 85% |\n| 중급 | 70% |"),
        slide(3, "정리\n시간표 조정이 먼저입니다"),
    ])
    graph = graph_of("swim.pdf", 3, [
        node("root", "수영 강습", [1, 3], depth=1, weight=1.0),
        node("finish", "완주율", [2], weight=0.9),
        node("beginner", "초급반", [2], weight=0.8),
        node("table", "시간표 조정", [1, 3], weight=0.5),
    ])
    said = {1: "오늘은 마을 수영장 강습 이야기를 할게요.", 2: "초급반은 좋아졌어요.", 3: "시간표 조정이 먼저예요."}
    a = AlignmentDoc(file_name="swim.pdf", total_slides=3, speech_match="matched", speech_overlap=0.4, basis="llm", items=[
        item("root", "aligned", evidence=said[1], doc_weight=1.0, speech_weight=0.9),
        item("finish", "aligned", evidence=said[2], doc_weight=0.9, speech_weight=0.1),     # 덜 말함
        item("beginner", "aligned", evidence=said[2], doc_weight=0.8, speech_weight=0.1),   # 덜 말함 — 같은 2장
        item("table", "aligned", evidence=said[3], doc_weight=0.5, speech_weight=0.5)])
    llm = ScriptedLLM()
    tri = triage_questions(graph, a, None, None, transcript=speech(said), slidedoc=swim, llm=llm)
    assert {m.node_id: m.source for m in tri.marks}["beginner"] == "under_spoken"
    doc = build_questions(graph, tri, track="10", alignment=a, transcript=speech(said), slidedoc=swim, llm=llm)
    under = [q for q in doc.questions if q.source == "under_spoken"]
    assert len(under) == 1 and under[0].node_id == "finish"
    assert "beginner" in doc.deferred_node_ids


# ===========================================================================
# REC-05 — 건너뛴 장 질문의 꼴: 내용을 묻고, 장·개념을 부르고, 그 장의 답을 싣지 않는다
# ===========================================================================

TEMPLATE = "발표에서 3장은 넘어갔는데, 그 장의 물 사용량을 설명해 주세요."


@pytest.mark.parametrize("asked", [
    "왜 3장을 생략하고 바로 결과로 넘어갔는지 설명해 주세요.",
    "3장을 건너뛴 이유는 무엇인가요?",
    "시간이 없어서 3장을 넘겼는데, 그 이유를 설명해 주세요.",
    "그 장은 왜 넘어갔나요?",
])
def test_건너뛴_까닭을_묻는_질문은_명세_문장으로_바뀐다(asked):
    q = q_of(garden_build("10", questions=[{"node_id": "usage", "question": asked, "why": "넘어간 까닭을 확인하는 질문이에요.",
                                             "hint": "시간이 부족했는지 떠올려 보세요.", "answer_gist": "시간이 부족했어요."}])[0],
             "usage")
    assert q.question == TEMPLATE
    assert {"skip_why_asked", "skip_template"} <= set(q.basis.checks)
    assert "시간이 부족" not in q.answer_gist and "시간이 부족" not in q.hint     # 버린 문장의 골자·힌트도 버린다
    assert q.why.startswith("“시간 관계상 그냥 넘어갈게요”라고 하고 넘어간 3장의 핵심이라")       # 이유 줄은 건너뛴다고 한 절


@pytest.mark.parametrize("asked,why", [
    # 빠뜨린 까닭을 묻는다 (태도) — 생략·누락·건너뜀·다루지 않음 + 까닭 말
    ("반죽 발효 단계가 발표에서 생략된 이유는 무엇인가요?", True),
    ("강습 시간표 설명이 발표에서 누락된 이유는 무엇인가요?", True),
    ("왜 하루 증발량은 발표에서 다루지 않았나요?", True),
    ("시간이 없어서 5장을 넘겼는데 이유가 무엇인가요?", True),
    ("그 장은 왜 넘어갔나요?", True),
    ("완주율과 시간표를 잇는 멘트가 없었던 이유는 무엇인가요?", True),       # 말하기(멘트·설명)가 없었던 까닭
    ("왜 두 개념을 잇는 설명이 없었나요?", True),
    ("부작용이 없었던 이유는 무엇인가요?", False),                          # 내용의 「없다」
    ("결말이 없던 이유는 무엇인가요?", False),
    # 내용을 묻는다 — 빠뜨림을 가리키기만 하거나, 수량의 「넘어가다」, 관형 「생략된 N장」
    ("발표에서 3장은 넘어갔는데, 그 장의 물 사용량을 설명해 주세요.", False),
    ("왜 수온이 기준을 넘어가면 강습을 멈추나요?", False),
    ("반죽 온도가 30도를 넘어간 이유는 무엇인가요?", False),
    ("생략된 3장의 식에서 왜 하루 증발량을 곱하나요?", False),
    ("3장은 넘어갔는데 그 장의 식은 왜 곱셈인가요?", False),
    ("발표에서 생략했는데, 누가 물으면 한 문장으로 어떻게 답할 건가요?", False),
    ("왜 누락 신고가 늘어났나요?", False),
])
def test_빠뜨린_까닭을_묻는지_가른다(asked, why):
    assert f08._asks_why_skipped(asked) is why


def test_다른_근거의_질문도_빠뜨린_까닭을_물으면_정해진_문장이다():
    # 관찰 범위(5장) — 누락이 아닌 개념이지만 LLM 이 「…설명하지 않은 이유」 를 물었다
    q = q_of(garden_build("10", questions=[{"node_id": "limit", "question": "관찰 범위를 발표에서 자세히 설명하지 않은 이유는 무엇인가요?",
                                             "answer_gist": "시간이 부족했어요."}])[0], "limit")
    assert "why_omitted_asked" in q.basis.checks and "이유는 무엇인가요" not in q.question
    assert "시간이 부족" not in q.answer_gist


@pytest.mark.parametrize("asked,problem", [
    # 그 장의 수치(= 답)를 실음
    ("물 사용량은 한 번 줄 때 평균 25리터인데, 이 값이 수확과 어떤 관계인가요?", "skip_value_leak"),
    # 그 장의 식을 되읊음
    ("물 사용량을 텃밭 면적 × 하루 증발량 × 물 주는 날로 계산하면 무엇을 알 수 있나요?", "skip_value_leak"),
    # 장도 개념도 부르지 않음
    ("아침에 물을 주면 왜 더 좋은가요?", "skip_not_named"),
])
def test_건너뛴_장의_답을_싣거나_장을_안_부르는_질문은_명세_문장으로_바뀐다(asked, problem):
    q = q_of(garden_build("10", questions=[{"node_id": "usage", "question": asked, "answer_gist": "물 사용량이 중요해요."}])[0],
             "usage")
    assert q.question == TEMPLATE and problem in q.basis.checks, q.basis.checks
    assert "25" not in q.question


def test_내용을_묻는_LLM_문장은_두고_힌트가_그_장의_값을_말하면_버린다():
    asked = "3장의 물 사용량은 어떤 요소로 정해지나요?"
    q = q_of(garden_build("10", questions=[{"node_id": "usage", "question": asked,
                                             "hint": "한 번 줄 때 쓰는 25리터를 떠올려 보세요.",
                                             "answer_gist": "텃밭 면적과 하루 증발량과 물 주는 날을 곱한 값이 물 사용량이에요."}])[0],
             "usage")
    assert q.question == asked and "skip_llm_worded" in q.basis.checks
    assert "25" not in q.hint and "hint_skip_leak" in q.basis.checks
    # 골자가 자료로 받쳐지고 접은 개념(텃밭 면적·하루 증발량)을 다 부르니 LLM 골자를 둔다
    assert q.answer_gist.startswith("텃밭 면적과 하루 증발량") and "gist_skip_code" not in q.basis.checks


def test_LLM_골자가_접은_개념을_빠뜨리면_그_장_자료_줄로_다시_쓴다():
    asked = "3장의 물 사용량은 어떤 요소로 정해지나요?"
    q = q_of(garden_build("10", questions=[{"node_id": "usage", "question": asked,
                                             "answer_gist": "물 사용량은 물 주는 날이 많을수록 늘어나요."}])[0], "usage")
    assert "gist_skip_code" in q.basis.checks
    assert "텃밭 면적" in q.answer_gist and "하루 증발량" in q.answer_gist and q.answer_gist.endswith("(3장)")


def test_건너뛴_장_질문의_발표에서_한_말은_건너뛴다는_그_말이다():
    q = q_of(garden_build("10")[0], "usage")
    assert q.speech_quote == GARDEN_CUE                         # 옆 장 끝 문장(「그래서 물 주기가 중요해요」)이 아니다
    assert "그래서 물 주기가" not in q.speech_quote


def test_건너뛴_장에는_함정이_없다():
    doc, _, _ = garden_build("10", traps=True)
    for q in doc.questions:
        if q.trap:
            assert q.trap_premise.slide_no not in (3, 4), q.trap_premise      # 건너뛴 장 · 모순의 자료 장
    assert not any(q.trap for q in doc.questions if 3 in q.slide_nos)
    # 뒤집을 수치(합 줄)가 건너뛴 장에만 있는 덱 — 예전엔 같은 장의 누락 개념에 그 장의 합 줄로 함정을 만들었다
    # (09-30 REC-11: 건너뛴 장 질문 뒤에 같은 장 합 줄 함정 「… = 140초」)
    only3 = SlideDoc(file_name="garden.pdf", total_slides=6, slides=[
        s if s.slide_no in (1, 4, 6) else slide(s.slide_no, {
            2: "왜 물 주기인가\n여름철 채소 관리",
            3: "물 사용량 계산\n물 사용량 = 텃밭 면적 × 하루 증발량 × 물 주는 날\n아침 10분 + 점심 8분 + 저녁 7분 = 25분",
            5: "한계\n관찰 기록"}[s.slide_no])
        for s in GARDEN.slides])
    doc, _, _ = garden_build("10", traps=True, slidedoc=only3)
    assert not any(q.trap for q in doc.questions), [q.question for q in doc.questions if q.trap]


# ===========================================================================
# REC-07 — 근거가 확인된 약점 질문이 밀려 있는 동안 함정은 자리를 차지하지 않는다 (5분 · 10분)
# ===========================================================================

def test_5분_트랙_건너뛴_장_질문이_밀리면_함정_대신_그_질문이_자리를_받는다():
    # 대표(물 사용량)가 깊이 3 이라 요소(part) 자리에 안 맞는다 — 배합만으로는 밀린다
    doc, _, _ = garden_build("5", traps=True, usage_depth=3)
    ids = [q.node_id for q in doc.questions]
    assert ids[0] == "morning"                                 # 확인된 모순이 맨 앞
    assert "usage" in ids                                      # 건너뛴 장 질문이 들어왔다
    assert not any(q.trap for q in doc.questions)             # 그 자리에 함정이 없다 (허용치 1 은 상한이다)
    assert q_of(doc, "usage").basis.slot == "weak"


def test_5분_트랙_밀린_약점_질문이_없으면_함정은_예전처럼_든다():
    graph = garden_graph(usage_depth=3)
    a = garden_alignment(graph, skipped_slides=[], items=[i for i in garden_alignment(graph).items])
    doc, _, _ = garden_build("5", traps=True, usage_depth=3, alignment=a)
    assert sum(q.trap for q in doc.questions) == 1


def _trap_fixture(n_backed_deferred: int, track: str):
    """10분 트랙 7자리 + 밀린 약점 질문 n 개. 약점이 아닌 자리의 개념마다 자료 줄에 뒤집을 수치가 있다."""
    slides = {i: Slide(slide_no=i, title="", blocks=[SlideBlock(category="paragraph",
                                                                  text=f"강습반{i} 소개\n강습반{i}의 등록 인원은 {20 + i}명입니다")])
              for i in range(1, 13)}
    nodes = [ConceptNode(id="root", label="수영 강습 운영", slide_nos=[1], depth=1, weight=1.0)]
    nodes += [ConceptNode(id=f"n{i}", label=f"강습반{i}", slide_nos=[i], depth=2, parent_id="root", weight=0.5)
              for i in range(2, 13)]
    by_id = {n.id: n for n in nodes}
    head = [TriageMark(node_id="root", severity=1, source="core_weight", rank=1, doc_weight=1.0)]
    head += [TriageMark(node_id=f"n{i}", severity=2, source="core_weight", rank=i, doc_weight=0.5) for i in range(2, 8)]
    backed = [TriageMark(node_id=f"n{i}", severity=1, source="skipped_slide", rank=20 + i, doc_weight=0.5)
              for i in range(8, 8 + n_backed_deferred)]
    rest = [TriageMark(node_id=f"n{i}", severity=2, source="core_weight", rank=40 + i, doc_weight=0.5)
            for i in range(8 + n_backed_deferred, 13)]
    pool = head + backed + rest
    slot_of = {"root": "theme"}
    marks, deferred, trap_of = f08._assign_traps(head, [m.node_id for m in backed + rest], pool, track, by_id, slides, {},
                                                 slot_of, keep={m.node_id for m in backed})
    return marks, deferred, trap_of, backed


@pytest.mark.parametrize("n_backed,traps_left", [(0, 3), (1, 2), (2, 1), (3, 0), (4, 0)])
def test_10분_트랙_함정_허용치는_밀린_약점_질문이_먼저_쓴다(n_backed, traps_left):
    marks, deferred, trap_of, backed = _trap_fixture(n_backed, "10")
    placed = [m.node_id for m in marks[:7] if m.node_id in {b.node_id for b in backed}]
    assert len(placed) == min(n_backed, 3)                     # 함정 자리 셋을 약점 질문이 먼저 받는다
    assert len(trap_of) == traps_left                          # 남은 자리만 함정 (허용치 3 은 상한)
    assert all(m.node_id not in trap_of for m in marks if m.node_id in placed)
    assert marks[0].node_id == "root"                          # 주제 자리는 비키지 않는다
    assert len(marks) == 7 and len(set(m.node_id for m in marks)) == 7


def test_탐침에_묶인_개념도_밀려_있으면_함정보다_먼저다():
    slides = {i: Slide(slide_no=i, title="", blocks=[SlideBlock(category="paragraph",
                                                                  text=f"강습반{i} 소개\n강습반{i}의 등록 인원은 {20 + i}명입니다")])
              for i in range(1, 6)}
    nodes = [ConceptNode(id="root", label="수영 강습 운영", slide_nos=[1], depth=1, weight=1.0)]
    nodes += [ConceptNode(id=f"n{i}", label=f"강습반{i}", slide_nos=[i], depth=2, parent_id="root", weight=0.5)
              for i in range(2, 6)]
    by_id = {n.id: n for n in nodes}
    head = [TriageMark(node_id="root", severity=1, source="core_weight", rank=1, doc_weight=1.0),
            TriageMark(node_id="n2", severity=2, source="core_weight", rank=2, doc_weight=0.5),
            TriageMark(node_id="n3", severity=2, source="core_weight", rank=3, doc_weight=0.5)]
    probe = TriageMark(node_id="n4", severity=1, source="unsupported_cause", rank=4, doc_weight=0.5)
    probes = {"n4": Probe(kind="unsupported_cause", node_ids=["n4"], evidence=[ClaimQuote(4, "강습반4의 등록 인원은 24명입니다")])}
    marks, _, trap_of = f08._assign_traps(head, ["n4", "n5"], head + [probe], "5", by_id, slides, probes,
                                          {"root": "theme"}, keep=set())
    assert "n4" in [m.node_id for m in marks[:3]] and not trap_of


# ===========================================================================
# REC-02 번트 Q6 — 녹음 모드의 「…라고 했는데」 는 녹음에 있는 말만 발표자에게
# ===========================================================================

def test_녹음에_없고_자료에만_있는_말은_자료_장에_붙인다():
    asked = "관찰한 텃밭이 8곳뿐이라고 했는데, 이 한계가 결론에 어떤 영향을 주나요?"
    q = q_of(garden_build("10", questions=[{"node_id": "limit", "question": asked,
                                             "answer_gist": "관찰한 텃밭이 8곳뿐이라 일반화에 한계가 있어요."}])[0], "limit")
    assert q.question == "자료 5장에서 관찰한 텃밭이 8곳뿐이라고 했는데, 이 한계가 결론에 어떤 영향을 주나요?"
    assert "attribution_deck" in q.basis.checks


def test_녹음에_있는_말은_발표자에게_붙인_그대로_둔다():
    asked = "텃밭 20곳 중 12곳에서 채소가 시들었다고 했는데, 무엇이 가장 큰 원인인가요?"
    q = q_of(garden_build("10", questions=[{"node_id": "need", "question": asked,
                                             "answer_gist": "여름철 물 부족으로 채소가 시들었어요."}])[0], "need")
    assert q.question == asked and "attribution_deck" not in q.basis.checks


def test_옮긴_말_끝의_서술어_조각은_녹음과_글자가_달라도_녹음에_있는_말이다():
    # 발표자는 「…높아진 거예요」 라고 했다 — 질문의 「높아졌다고」 의 「높아졌」 은 서술어라 명사로 세지 않는다
    # (예전: 「녹음에 없는 말」 이 되어 모순 질문이 정해진 문장으로 떨어졌다)
    from chuckchuck._deck_claims import numbers
    from chuckchuck._spoken import spoken_numbers
    said = "초급반은 좋아졌어요. 완주율이 60퍼센트에서 85퍼센트로 높아진 거예요."
    heard = (numbers(spoken_numbers(said)), f08._stems_of(said))
    asked = "완주율이 85%로 높아졌다고 했는데, 무엇이 달라졌나요?"
    assert f08._attribution_fix(asked, heard, None) == (asked, "")
    # 녹음에 없는 값이면 여전히 발표자의 말이 아니다
    assert f08._attribution_fix("완주율이 95%로 높아졌다고 했는데, 무엇이 달라졌나요?", heard, None) == ("", "attribution_unspoken")


def test_자료만_올린_경로는_했는데_가_자료를_가리키므로_그대로다():
    asked = "관찰한 텃밭이 8곳뿐이라고 했는데, 이 한계가 결론에 어떤 영향을 주나요?"
    graph = garden_graph()
    llm = ScriptedLLM([{"node_id": "limit", "question": asked, "answer_gist": "관찰한 텃밭이 8곳뿐이라 일반화에 한계가 있어요."}])
    tri = triage_questions(graph, llm=llm)
    doc = build_questions(graph, tri, track="10", slidedoc=GARDEN, llm=llm)
    q = q_of(doc, "limit")
    assert q is not None and q.question == asked


def test_녹음_모드_함정을_발표자에게_붙이면_자료에_붙인다():
    # 1차 — 코드가 고른 함정 전제를 알아낸다
    doc, _, _ = garden_build("10", traps=True)
    trap = next(q for q in doc.questions if q.trap)
    premise = trap.trap_premise.premise
    if premise.startswith("표에서 "):
        pytest.skip("표에서 읽은 전제는 이 덱에 없다")
    asked = f"「{premise}」라고 했는데, 이 수치가 무엇을 보여 주는지 설명해 주세요."
    doc2, _, _ = garden_build("10", traps=True, questions=[{"node_id": trap.node_id, "question": asked}])
    q = q_of(doc2, trap.node_id)
    assert q.trap and q.question.startswith(f"자료에서 「{premise}」")
    assert {"trap_llm_worded", "trap_attribution_deck"} <= set(q.basis.checks)


def test_LLM_모순_질문이_녹음에_없는_말을_발표자에게_붙이면_정해진_문장이다():
    # 발표자는 「오십 퍼센트」 라고 했다 — 「70%」 는 어디에도 없는 값이지만 모순 꼴은 갖췄다
    asked = "아침 물 주기로 수확량이 20% 많았다고 했는데, 자료 4장과 어느 쪽이 맞나요?"
    q = q_of(garden_build("10", questions=[{"node_id": "morning", "question": asked}])[0], "morning")
    assert q.question.startswith("발표에서 “아침에 물을 준 텃밭이 저녁보다 수확량이 오십 퍼센트나 많았어요”라고 했는데")
    assert "contradiction_template" in q.basis.checks


# ===========================================================================
# 규칙에 덱 낱말이 없다 — 감사 덱과 이 파일 덱의 낱말이 새 규칙·문장 틀에 있으면 덱에 맞춘 것이다
# ===========================================================================

def _literals(fn) -> str:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    body = tree.body[0].body
    doc = body[0].value if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) else None
    return " ".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n is not doc)


def test_새_규칙과_문장_틀에_발표_낱말이_없다():
    src = " ".join(_literals(fn) for fn in (
        f08._skipped_core, f08._slide_heading, f08._formula_heads, f08._skip_role, f08._skip_folded, f08._asks_why_skipped,
        f08._skip_leaks, f08._skip_problem, f08._skip_speech, f08._speech_attribution, f08._spoken_premise, f08._deck_home,
        f08._deck_attributed, f08._attribution_fix, f08._with_skip_reps, f08._one_per_slide, f08._assign_traps,
        f08._recording_backed))
    src += " ".join(r.pattern for r in (f08._OMIT_REASON_RE, f08._OMIT_FINITE_RE, f08._SKIP_OBJECT_VERB_RE, f08._REASON_ASK_RE,
                                        f08._REASON_ANAPHOR_RE, f08._ATTRIB_TAIL_RE, f08._DECK_SOURCE_RE,
                                        f08._SPEECH_SOURCE_RE))
    for word in ("환기", "이산화탄소", "교실", "창문", "키오스크", "어르신", "주문", "번트", "강공", "야구", "타율",
                 "텃밭", "물 사용량", "증발", "반죽", "발효", "수영", "강습"):
        assert word not in src, word
