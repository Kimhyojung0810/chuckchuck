"""
F-08 질문 생성(triage_questions·build_questions)이 계약 불변식을 지키는지 검사합니다.
SCHEMA.md §8 의 '보증' 항목이 여기 그대로 대응됩니다.

LLM 은 전부 가짜라서 네트워크·API 키가 필요하지 않습니다.
"""

import json

import pytest

from chuckchuck.contracts import (
    QA_SEVERITIES,
    QA_TEXT_MAX,
    QA_TRACK_LIMITS,
    QA_TRACK_TRAPS,
    AlignmentDoc,
    AlignmentItem,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    FlowDiff,
    FlowIssue,
    QaTriage,
    QuestionDoc,
    QuestionError,
    SlideSpeech,
    Transcript,
    TriageMark,
)
from chuckchuck.f08_questions import build_questions, triage_questions
from chuckchuck.providers.llm_base import LLMProvider


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def make_graph(n: int = 3) -> ConceptGraph:
    """작은 ConceptGraph. c1 이 가장 무겁고 뒤로 갈수록 가볍다."""
    nodes = [
        ConceptNode(
            id=f"c{i}",
            label=f"개념{i}",
            slide_nos=[i],
            summary=f"개념{i} 한 줄",
            weight=round(max(0.0, 1.0 - 0.01 * (i - 1)), 3),
            parent_id="c1" if i > 1 else None,
            depth=1 if i == 1 else 2,
        )
        for i in range(1, n + 1)
    ]
    edges = [ConceptEdge(from_id="c1", to_id=f"c{i}", kind="parent") for i in range(2, n + 1)]
    return ConceptGraph(file_name="sample.pdf", total_slides=n, nodes=nodes, edges=edges)


def make_alignment(verdicts: dict[str, str], graph: ConceptGraph | None = None) -> AlignmentDoc:
    """node_id → verdict. 안 준 노드는 aligned 로 채운다."""
    graph = graph or make_graph()
    return AlignmentDoc(
        file_name=graph.file_name,
        total_slides=graph.total_slides,
        items=[
            AlignmentItem(
                node_id=n.id,
                verdict=verdicts.get(n.id, "aligned"),
                doc_weight=n.weight,
                evidence="모의 근거 발화",
            )
            for n in graph.nodes
        ],
    )


def make_flow(*pairs: tuple[str, str], kind: str = "missing_link") -> FlowDiff:
    return FlowDiff(
        file_name="sample.pdf",
        issues=[FlowIssue(kind=kind, node_ids=list(pair)) for pair in pairs],
    )


class ScriptedLLM(LLMProvider):
    """정해 둔 문자열만 돌려주는 가짜 LLM. 후처리 로직만 시험한다."""

    name = "scripted"

    def __init__(self, payload: str):
        self.payload = payload
        self.calls = 0
        self.prompts: list[str] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096) -> str:
        self.calls += 1
        self.prompts.append(user)
        return self.payload


class SequenceLLM(LLMProvider):
    """호출 순서대로 정해 둔 응답을 준다. 재시도 경로 검증용."""

    name = "sequence"

    def __init__(self, *payloads: str):
        self.payloads = list(payloads)
        self.calls = 0

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096) -> str:
        self.calls += 1
        return self.payloads[min(self.calls - 1, len(self.payloads) - 1)]


def marks_payload(*marks: dict) -> str:
    return json.dumps({"marks": list(marks)}, ensure_ascii=False)


def questions_payload(*questions: dict) -> str:
    return json.dumps({"questions": list(questions)}, ensure_ascii=False)


def triage_of(payload: str, *, graph=None, alignment=None, flow=None) -> QaTriage:
    return triage_questions(
        graph or make_graph(), alignment, flow, llm=ScriptedLLM(payload)
    )


def make_triage(graph: ConceptGraph | None = None, **kwargs) -> QaTriage:
    """LLM 이 아무것도 안 준 경우의 triage — 전부 결정적 폴백으로 채워진다."""
    return triage_of(marks_payload(), graph=graph, **kwargs)


def doc_of(payload: str, *, graph=None, triage=None, track="10", **kwargs) -> QuestionDoc:
    graph = graph or make_graph()
    return build_questions(
        graph,
        triage if triage is not None else make_triage(graph),
        track=track,
        llm=ScriptedLLM(payload),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# mock 파이프라인 · 왕복
# ---------------------------------------------------------------------------

def test_mock_llm_end_to_end():
    graph = make_graph()
    triage = triage_questions(graph, llm="mock")
    doc = build_questions(graph, triage, track="10", llm="mock")

    assert doc.model == "mock"
    assert doc.file_name == "sample.pdf"
    assert len(doc.questions) == 3
    assert all(q.question for q in doc.questions)


def test_triage_roundtrip():
    triage = triage_of(marks_payload(
        {"node_id": "c1", "severity": 1, "trap": True, "angle": "각도"}
    ))
    assert QaTriage.from_dict(triage.to_dict()).to_dict() == triage.to_dict()


def test_question_doc_roundtrip():
    doc = doc_of(questions_payload({"node_id": "c1", "question": "질문?"}))
    assert QuestionDoc.from_dict(doc.to_dict()).to_dict() == doc.to_dict()


def test_accepts_dict_inputs():
    graph = make_graph()
    triage = make_triage(graph)
    doc = build_questions(
        graph.to_dict(), triage.to_dict(), track="5", llm=ScriptedLLM(questions_payload())
    )
    assert len(doc.questions) == QA_TRACK_LIMITS["5"]


# ---------------------------------------------------------------------------
# 후보 선정 — 근거(source) 우선순위. 전부 코드가 정한다
# ---------------------------------------------------------------------------

def test_graph_only_gives_core_weight_candidates():
    """녹음 없이 자료만 올린 경로 — alignment·flow 가 없어도 질문이 나와야 한다."""
    doc = doc_of(questions_payload())
    assert doc.questions
    assert {q.source for q in doc.questions} == {"core_weight"}


def test_contradiction_outranks_everything():
    graph = make_graph()
    triage = make_triage(graph, alignment=make_alignment({"c3": "contradiction"}, graph))
    assert triage.marks[0].node_id == "c3"
    assert triage.marks[0].source == "contradiction"


def test_missing_outranks_weak_flow_and_core_weight():
    graph = make_graph()
    triage = make_triage(
        graph,
        alignment=make_alignment({"c3": "missing"}, graph),
        flow=make_flow(("c2", "c1")),
    )
    assert [m.node_id for m in triage.marks] == ["c3", "c1", "c2"]
    assert [m.source for m in triage.marks] == ["missing", "weak_flow", "weak_flow"]


def test_weak_flow_outranks_core_weight():
    graph = make_graph()
    triage = make_triage(graph, flow=make_flow(("c3", "c3")))
    assert triage.marks[0].node_id == "c3"
    assert triage.marks[0].source == "weak_flow"


def test_source_priority_full_order():
    """모순 > 누락 > 흐름 결손 > 자료 비중. 겹치면 높은 근거가 이긴다."""
    graph = make_graph(4)
    triage = make_triage(
        graph,
        alignment=make_alignment({"c4": "contradiction", "c3": "missing"}, graph),
        # c4 는 흐름 결손이기도 하지만 모순이 이겨야 한다
        flow=make_flow(("c2", "c4")),
    )
    assert [m.source for m in triage.marks] == [
        "contradiction", "missing", "weak_flow", "core_weight"
    ]
    assert [m.node_id for m in triage.marks] == ["c4", "c3", "c2", "c1"]


def test_good_link_is_not_a_question_reason():
    """말로 잘 이은 연결은 칭찬거리지 질문 근거가 아니다."""
    graph = make_graph()
    triage = make_triage(graph, flow=make_flow(("c3", "c2"), kind="good_link"))
    assert {m.source for m in triage.marks} == {"core_weight"}


def test_candidate_order_deterministic_on_weight_ties():
    """weight 동률이면 앞 슬라이드 → id 순. 같은 그래프면 언제나 같은 순서다."""
    nodes = [
        ConceptNode(id="zz", label="z", slide_nos=[5], weight=0.5),
        ConceptNode(id="aa", label="a", slide_nos=[2], weight=0.5),
        ConceptNode(id="mm", label="m", slide_nos=[2], weight=0.5),
    ]
    graph = ConceptGraph(file_name="t.pdf", total_slides=5, nodes=nodes)
    assert [m.node_id for m in make_triage(graph).marks] == ["aa", "mm", "zz"]


# ---------------------------------------------------------------------------
# 1차 심사가 트랙 나누기를 실제로 움직이는가 — triage 를 따로 부르는 이유
# ---------------------------------------------------------------------------

def flat_graph() -> ConceptGraph:
    """근거(source)가 전부 같고 weight 만 다른 그래프. severity 효과만 본다."""
    return ConceptGraph(file_name="t.pdf", total_slides=3, nodes=[
        ConceptNode(id="A", label="개념A", slide_nos=[1], weight=1.0),
        ConceptNode(id="B", label="개념B", slide_nos=[2], weight=0.8),
        ConceptNode(id="C", label="개념C", slide_nos=[3], weight=0.6),
    ])


SEVERITY_FLIPPED = marks_payload(
    {"node_id": "A", "severity": 3},   # 자료 weight 는 1위인데 LLM 은 '가벼움'
    {"node_id": "B", "severity": 2},
    {"node_id": "C", "severity": 1},   # weight 는 꼴찌인데 LLM 은 '치명'
)


def test_llm_severity_drives_rank():
    """LLM 이 치명이라 한 개념이 rank 1 이어야 한다 (자료 weight 를 뒤집어서라도)."""
    triage = triage_of(SEVERITY_FLIPPED, graph=flat_graph())
    assert [m.node_id for m in triage.marks] == ["C", "B", "A"]
    assert [m.rank for m in triage.marks] == [1, 2, 3]


def test_one_minute_track_asks_the_most_severe_concept():
    """
    1분 트랙은 '가장 치명적인 개념 하나' 다.

    이게 깨지면 1차 LLM 호출이 화면 표시용 장식이 된다 — 트랙을 나누려고 부른 것이다.
    """
    graph = flat_graph()
    triage = triage_of(SEVERITY_FLIPPED, graph=graph)
    doc = doc_of(questions_payload(), graph=graph, triage=triage, track="1")
    assert [q.node_id for q in doc.questions] == ["C"]
    assert doc.questions[0].severity == 1


def test_tracks_fill_in_severity_order():
    graph = flat_graph()
    triage = triage_of(SEVERITY_FLIPPED, graph=graph)
    picked = {
        track: [q.severity for q in doc_of(
            questions_payload(), graph=graph, triage=triage, track=track
        ).questions]
        for track in ("1", "5", "10")
    }
    assert picked["1"] == [1]
    assert picked["5"] == [1, 2, 3]
    assert picked["10"] == [1, 2, 3]
    for severities in picked.values():
        assert severities == sorted(severities), "치명도 순으로 채워야 한다"


def test_confirmed_source_outranks_llm_severity():
    """
    모순·누락은 **확인된 사실**이고 severity 는 LLM 의 짐작이다.

    짐작이 확인된 사실을 밀어내면 리포트가 '누락' 이라 말한 개념을 안 묻게 되어
    두 화면이 어긋난다.
    """
    graph = flat_graph()
    alignment = AlignmentDoc(
        file_name="t.pdf",
        total_slides=3,
        items=[
            AlignmentItem(node_id="A", verdict="missing", evidence="e"),
            AlignmentItem(node_id="B", verdict="aligned", evidence="e"),
            AlignmentItem(node_id="C", verdict="aligned", evidence="e"),
        ],
    )
    triage = triage_of(SEVERITY_FLIPPED, graph=graph, alignment=alignment)
    assert triage.marks[0].node_id == "A"            # LLM 은 A 를 '가벼움' 이라 했는데도
    assert triage.marks[0].source == "missing"
    assert triage.marks[0].severity == 3


def test_severity_only_reorders_within_the_same_source():
    """같은 근거 안에서는 severity 가 순위를 정한다."""
    graph = flat_graph()
    alignment = AlignmentDoc(
        file_name="t.pdf",
        total_slides=3,
        items=[AlignmentItem(node_id=n, verdict="missing", evidence="e") for n in "ABC"],
    )
    triage = triage_of(SEVERITY_FLIPPED, graph=graph, alignment=alignment)
    assert {m.source for m in triage.marks} == {"missing"}
    assert [m.node_id for m in triage.marks] == ["C", "B", "A"]


def test_rerank_is_deterministic():
    """severity 가 같으면 자료 weight → 앞 슬라이드 → id 로 동률을 깬다."""
    graph = flat_graph()
    same = marks_payload(*[{"node_id": n, "severity": 2} for n in "ABC"])
    first = triage_of(same, graph=graph)
    second = triage_of(same, graph=graph)
    assert first.to_dict() == second.to_dict()
    assert [m.node_id for m in first.marks] == ["A", "B", "C"]   # weight 내림차순


# ---------------------------------------------------------------------------
# triage 후처리 — LLM 은 severity·trap·angle 만 만진다
# ---------------------------------------------------------------------------

def test_every_candidate_gets_exactly_one_mark():
    triage = triage_of(marks_payload({"node_id": "c1", "severity": 1}))
    assert [m.node_id for m in triage.marks] == ["c1", "c2", "c3"]


def test_unknown_node_id_dropped_from_triage():
    triage = triage_of(marks_payload(
        {"node_id": "nope", "severity": 3, "trap": True},
        {"node_id": "c1", "severity": 1},
    ))
    assert "nope" not in [m.node_id for m in triage.marks]
    assert triage.mark("c1").severity == 1


def test_duplicate_node_id_first_wins_in_triage():
    triage = triage_of(marks_payload(
        {"node_id": "c1", "severity": 1},
        {"node_id": "c1", "severity": 3},
    ))
    assert triage.mark("c1").severity == 1


def test_invalid_severity_falls_back_by_source():
    graph = make_graph()
    triage = triage_of(
        marks_payload(
            {"node_id": "c1", "severity": 99},
            {"node_id": "c2", "severity": "글자"},
        ),
        graph=graph,
        alignment=make_alignment({"c1": "missing"}, graph),
    )
    assert triage.mark("c1").severity == 1        # missing → 치명
    assert triage.mark("c2").severity in QA_SEVERITIES


def test_core_weight_severity_splits_on_heavy_weight():
    nodes = [
        ConceptNode(id="heavy", label="무거움", slide_nos=[1], weight=0.9),
        ConceptNode(id="light", label="가벼움", slide_nos=[2], weight=0.1),
    ]
    graph = ConceptGraph(file_name="t.pdf", total_slides=2, nodes=nodes)
    triage = make_triage(graph)
    assert triage.mark("heavy").severity == 2
    assert triage.mark("light").severity == 3


def test_triage_derives_rank_and_doc_weight_from_code():
    """rank·doc_weight·source 는 LLM 값을 쓰지 않는다."""
    triage = triage_of(marks_payload(
        {"node_id": "c1", "rank": 99, "doc_weight": 0.01, "source": "contradiction"},
    ))
    mark = triage.mark("c1")
    assert (mark.rank, mark.doc_weight, mark.source) == (1, 1.0, "core_weight")


def test_triage_angle_clipped():
    triage = triage_of(marks_payload({"node_id": "c1", "angle": "각" * (QA_TEXT_MAX + 50)}))
    assert len(triage.mark("c1").angle) <= QA_TEXT_MAX


def test_candidate_limit_caps_triage():
    """가장 긴 트랙 상한의 두 배까지만 심사에 올린다."""
    graph = make_graph(40)
    assert len(make_triage(graph).marks) == max(QA_TRACK_LIMITS.values()) * 2


# ---------------------------------------------------------------------------
# 트랙 상한 · 함정 예산
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("track", sorted(QA_TRACK_LIMITS))
def test_track_limit_respected(track):
    graph = make_graph(20)
    doc = doc_of(questions_payload(), graph=graph, track=track)
    assert len(doc.questions) == QA_TRACK_LIMITS[track]


@pytest.mark.parametrize("track", sorted(QA_TRACK_TRAPS))
def test_trap_budget_respected(track):
    """LLM 이 전부 함정이라고 해도 트랙 허용치를 넘지 않는다. 1분 트랙은 0개."""
    graph = make_graph(20)
    triage = triage_of(
        marks_payload(*[{"node_id": n.id, "trap": True} for n in graph.nodes]),
        graph=graph,
    )
    doc = doc_of(questions_payload(), graph=graph, triage=triage, track=track)
    assert sum(q.trap for q in doc.questions) == QA_TRACK_TRAPS[track]


def test_unknown_track_falls_back():
    doc = doc_of(questions_payload(), track="7")
    assert doc.track == "10"


def test_deferred_holds_pushed_out_candidates():
    graph = make_graph(20)
    triage = make_triage(graph)
    doc = doc_of(questions_payload(), graph=graph, triage=triage, track="1")

    asked = {q.node_id for q in doc.questions}
    candidates = [m.node_id for m in triage.marks]
    assert doc.deferred_node_ids == [n for n in candidates if n not in asked]


def test_build_does_not_mutate_cached_triage():
    """triage 는 세션 캐시다 — 트랙을 바꿔 가며 재사용해도 원본이 변하면 안 된다."""
    graph = make_graph(20)
    triage = triage_of(
        marks_payload(*[{"node_id": n.id, "trap": True} for n in graph.nodes]),
        graph=graph,
    )
    before = triage.to_dict()
    doc_of(questions_payload(), graph=graph, triage=triage, track="1")
    assert triage.to_dict() == before


# ---------------------------------------------------------------------------
# 질문 후처리
# ---------------------------------------------------------------------------

def test_question_ids_unique_and_node_ids_not_repeated():
    doc = doc_of(questions_payload(), graph=make_graph(20), track="10")
    ids = [q.id for q in doc.questions]
    node_ids = [q.node_id for q in doc.questions]
    assert len(set(ids)) == len(ids)
    assert len(set(node_ids)) == len(node_ids)


def test_same_triage_and_track_gives_identical_doc():
    """'같은 triage 면 결과가 같다' — 질문 id 까지 같아야 한다 (uuid 금지)."""
    graph = make_graph(20)
    triage = make_triage(graph)
    payload = questions_payload({"node_id": "c1", "question": "질문?"})
    first = build_questions(graph, triage, track="5", llm=ScriptedLLM(payload))
    second = build_questions(graph, triage, track="5", llm=ScriptedLLM(payload))
    assert first.to_dict() == second.to_dict()


def test_unknown_node_id_dropped_from_questions():
    doc = doc_of(questions_payload(
        {"node_id": "nope", "question": "지어낸 질문"},
        {"node_id": "c1", "question": "진짜 질문"},
    ))
    assert "지어낸 질문" not in [q.question for q in doc.questions]
    assert doc.questions[0].question == "진짜 질문"


def test_duplicate_node_id_first_wins_in_questions():
    doc = doc_of(questions_payload(
        {"node_id": "c1", "question": "첫 번째"},
        {"node_id": "c1", "question": "두 번째"},
    ))
    assert "두 번째" not in [q.question for q in doc.questions]
    assert doc.questions[0].question == "첫 번째"


def test_omitted_target_filled_with_deterministic_fallback():
    """LLM 이 빠뜨린 개념도 질문이 나와야 한다 — 세트에 구멍을 내지 않는다."""
    doc = doc_of(questions_payload({"node_id": "c1", "question": "진짜 질문"}))
    filled = [q for q in doc.questions if q.node_id == "c2"][0]
    assert filled.question
    assert filled.why
    assert filled.hint


def test_fallback_question_uses_triage_angle():
    graph = make_graph()
    triage = triage_of(
        marks_payload({"node_id": "c1", "angle": "왜 이 방식을 골랐는지"}), graph=graph
    )
    doc = doc_of(questions_payload(), graph=graph, triage=triage)
    assert "왜 이 방식을 골랐는지" in doc.questions[0].question


def test_fallback_why_explains_the_source():
    graph = make_graph()
    triage = make_triage(graph, alignment=make_alignment({"c1": "contradiction"}, graph))
    doc = doc_of(questions_payload(), graph=graph, triage=triage)
    assert doc.questions[0].source == "contradiction"
    assert "어긋난" in doc.questions[0].why


def test_long_text_clipped_to_qa_text_max():
    doc = doc_of(questions_payload({
        "node_id": "c1",
        "question": "질" * (QA_TEXT_MAX + 100),
        "why": "왜" * (QA_TEXT_MAX + 100),
        "hint": "힌" * (QA_TEXT_MAX + 100),
    }))
    q = doc.questions[0]
    assert len(q.question) <= QA_TEXT_MAX
    assert len(q.why) <= QA_TEXT_MAX
    assert len(q.hint) <= QA_TEXT_MAX


def test_question_carries_graph_fields():
    doc = doc_of(questions_payload())
    q = doc.questions[0]
    assert q.label == "개념1"
    assert q.slide_nos == [1]
    assert q.doc_weight == 1.0


def test_severity_always_in_enum():
    doc = doc_of(questions_payload(), graph=make_graph(20))
    assert all(q.severity in QA_SEVERITIES for q in doc.questions)


# ---------------------------------------------------------------------------
# 그래프 구조 · 발화를 프롬프트에 싣는다
# ---------------------------------------------------------------------------
# edges 가 진실이다. 경로는 parent 간선만 따라간 트리 뷰(노드당 parent 최대 1개),
# 연결은 relates 까지 포함한 그래프 뷰 — 트리는 그래프의 부분집합이다.

def prompt_of(*, graph=None, transcript=None, alignment=None, flow=None) -> str:
    llm = ScriptedLLM(marks_payload())
    triage_questions(graph or make_graph(), alignment, flow, transcript=transcript, llm=llm)
    return llm.prompts[0]


def test_triage_prompt_carries_parent_path():
    """트리 뷰 — parent 간선만 따라간 경로."""
    assert "경로=개념1 > 개념2" in prompt_of()


def test_triage_prompt_carries_relates_neighbors():
    """그래프 뷰 — relates 간선도 연결로 실린다."""
    graph = make_graph()
    graph.edges.append(ConceptEdge(from_id="c2", to_id="c3", kind="relates"))
    text = prompt_of(graph=graph)
    assert "연결=" in text
    line = [ln for ln in text.splitlines() if ln.strip().startswith("연결=")][0]
    assert "개념3" in line or "개념2" in line


def test_demoted_second_parent_reaches_the_prompt():
    """
    둘째 부모는 버려지지 않고 relates 로 내려간다 (F-07 계약).
    그렇게 보존된 정보가 질문 프롬프트까지 실제로 도달하는지 본다 —
    도달하지 않으면 '정보를 보존한다' 가 말뿐이 된다.
    """
    from chuckchuck.f07_graph import build_graph

    payload = json.dumps({
        "nodes": [
            {"id": "svc", "label": "서비스", "slide_nos": [1]},
            {"id": "data", "label": "데이터 자산", "slide_nos": [2]},
            {"id": "cafp", "label": "CAFP 분석", "slide_nos": [3]},
        ],
        "edges": [
            {"from": "svc", "to": "cafp", "kind": "parent"},
            {"from": "data", "to": "cafp", "kind": "parent"},   # 둘째 부모
        ],
        "sections": [],
    }, ensure_ascii=False)
    graph = build_graph(
        {"file_name": "t.pdf", "total_slides": 3,
         "slides": [{"slide_no": i, "concepts": ["x: y"]} for i in (1, 2, 3)]},
        llm=ScriptedLLM(payload),
    )
    assert [(e.from_id, e.to_id) for e in graph.relates_edges] == [("data", "cafp")]

    line = [ln for ln in prompt_of(graph=graph).splitlines() if "경로=" in ln][0]
    # 트리 뷰(경로)에는 첫 부모만, 그래프 뷰(연결)에는 강등된 둘째 부모까지
    assert "경로=서비스 > CAFP 분석" in line
    assert "데이터 자산" in line.split("연결=")[1], "relates 로 내려간 둘째 부모가 프롬프트에 없다"


def test_neighbors_capped_with_visible_count():
    """이웃이 상한을 넘으면 조용히 자르지 않고 '외 N개' 로 알린다."""
    from chuckchuck.f08_questions import NEIGHBOR_MAX

    n = NEIGHBOR_MAX + 3
    nodes = [ConceptNode(id="hub", label="허브", slide_nos=[1], weight=1.0)]
    nodes += [
        ConceptNode(id=f"n{i}", label=f"이웃{i}", slide_nos=[1], weight=round(0.9 - i * 0.01, 3))
        for i in range(n)
    ]
    edges = [ConceptEdge(from_id="hub", to_id=f"n{i}", kind="relates") for i in range(n)]
    graph = ConceptGraph(file_name="t.pdf", total_slides=1, nodes=nodes, edges=edges)

    line = [ln for ln in prompt_of(graph=graph).splitlines() if "연결=" in ln][0]
    assert f"외 {n - NEIGHBOR_MAX}개" in line
    assert "이웃0" in line and f"이웃{n - 1}" not in line   # 무거운 쪽부터 남는다


def test_triage_prompt_carries_slide_speech():
    """Transcript.by_slide 를 slide_no 로 조인해 근거 장 발화를 싣는다."""
    transcript = Transcript(
        full_text="",
        by_slide=[SlideSpeech(slide_no=1, visit=1, start_sec=0, end_sec=10, text="개념1 발화입니다")],
    )
    assert "개념1 발화입니다" in prompt_of(transcript=transcript)


def test_question_prompt_carries_path_and_speech():
    graph = make_graph()
    transcript = Transcript(
        full_text="",
        by_slide=[SlideSpeech(slide_no=1, visit=1, start_sec=0, end_sec=10, text="개념1 발화입니다")],
    )
    llm = ScriptedLLM(questions_payload())
    build_questions(graph, make_triage(graph), track="10", transcript=transcript, llm=llm)
    assert "경로=개념1 > 개념2" in llm.prompts[0]
    assert "개념1 발화입니다" in llm.prompts[0]


def test_speech_excerpt_clipped():
    from chuckchuck.f08_questions import SPEECH_EXCERPT_MAX

    transcript = Transcript(
        full_text="",
        by_slide=[
            SlideSpeech(slide_no=1, visit=1, start_sec=0, end_sec=10, text="말" * 2000)
        ],
    )
    for line in prompt_of(transcript=transcript).splitlines():
        assert len(line) <= max(SPEECH_EXCERPT_MAX + 40, 200)


def test_works_without_transcript():
    """녹음이 없어도 프롬프트가 만들어지고 질문이 나온다."""
    doc = doc_of(questions_payload(), track="10")
    assert doc.questions


# ---------------------------------------------------------------------------
# 재시도 · 실패
# ---------------------------------------------------------------------------

def test_broken_json_retried_once():
    llm = SequenceLLM("이건 JSON 이 아니다", marks_payload({"node_id": "c1", "severity": 1}))
    triage = triage_questions(make_graph(), llm=llm)
    assert llm.calls == 2
    assert triage.mark("c1").severity == 1


def test_broken_json_twice_raises():
    llm = SequenceLLM("깨짐", "또 깨짐")
    with pytest.raises(QuestionError):
        triage_questions(make_graph(), llm=llm)


def test_build_questions_broken_json_twice_raises():
    graph = make_graph()
    with pytest.raises(QuestionError):
        build_questions(graph, make_triage(graph), llm=SequenceLLM("깨짐", "또 깨짐"))


def test_empty_graph_raises():
    empty = ConceptGraph(file_name="x.pdf", total_slides=0)
    with pytest.raises(QuestionError):
        triage_questions(empty, llm=ScriptedLLM(marks_payload()))


def test_triage_from_other_graph_raises():
    """triage 의 개념이 그래프에 하나도 없으면 조인이 불가능하다."""
    stranger = QaTriage(file_name="other.pdf", marks=[TriageMark(node_id="x1", rank=1)])
    with pytest.raises(QuestionError):
        build_questions(make_graph(), stranger, llm=ScriptedLLM(questions_payload()))
