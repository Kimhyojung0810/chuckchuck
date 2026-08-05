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
    ExtraConcept,
    FlowDiff,
    FlowIssue,
    QaTriage,
    QuestionDoc,
    QuestionError,
    Section,
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


def make_alignment(
    verdicts: dict[str, str],
    graph: ConceptGraph | None = None,
    speech_weights: dict[str, float] | None = None,
    extras: list[tuple[str, str, int | None]] | None = None,
) -> AlignmentDoc:
    """
    node_id → verdict. 안 준 노드는 aligned 로 채운다.

    speech_weight 는 기본으로 doc_weight 를 따라간다 — '정합인데 발화 비중 0' 은
    F-11 이 만들 수 없는 조합이고, 그대로 두면 모든 노드가 under_spoken 으로 잡힌다.
    격차를 시험할 때만 speech_weights 로 낮춰 준다.
    """
    graph = graph or make_graph()
    speech_weights = speech_weights or {}
    return AlignmentDoc(
        file_name=graph.file_name,
        total_slides=graph.total_slides,
        items=[
            AlignmentItem(
                node_id=n.id,
                verdict=verdicts.get(n.id, "aligned"),
                doc_weight=n.weight,
                speech_weight=speech_weights.get(n.id, n.weight),
                evidence="모의 근거 발화",
            )
            for n in graph.nodes
        ],
        extra_concepts=[
            ExtraConcept(label=label, quote=quote, slide_no=no)
            for label, quote, no in (extras or [])
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

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False) -> str:
        self.calls += 1
        self.prompts.append(user)
        return self.payload


class SequenceLLM(LLMProvider):
    """호출 순서대로 정해 둔 응답을 준다. 재시도 경로 검증용."""

    name = "sequence"

    def __init__(self, *payloads: str):
        self.payloads = list(payloads)
        self.calls = 0

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False) -> str:
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


# ---------------------------------------------------------------------------
# 기대 답 골자(answer_gist)
#
# 되묻기가 끝날 때 "그래서 뭐라고 답했어야 하나" 를 보여 주는 재료다.
# 대화가 끝났는데 답을 모른 채면 코칭이 실패한 것이므로 절대 비어선 안 된다.
# ---------------------------------------------------------------------------

def gist_of(doc: QuestionDoc, node_id: str) -> str:
    """node_id 로 질문을 찾아 골자만 꺼낸다. 질문 id 는 rank 에 따라 달라진다."""
    found = next(q for q in doc.questions if q.node_id == node_id)
    return found.answer_gist


def test_llm_이_준_골자를_쓴다():
    doc = doc_of(questions_payload(
        {"node_id": "c1", "question": "질문", "answer_gist": "20명 실측으로 평균 23초"}
    ))
    assert gist_of(doc, "c1") == "20명 실측으로 평균 23초"


def test_골자가_비면_자료로_채운다():
    """LLM 이 빠뜨려도 비워 두지 않는다. 개념 요약과 근거 장은 이미 코드가 갖고 있다."""
    doc = doc_of(questions_payload({"node_id": "c1", "question": "질문"}))
    assert gist_of(doc, "c1").strip()


def test_골자_폴백은_개념_요약을_담는다():
    doc = doc_of(questions_payload())
    assert "개념1 한 줄" in gist_of(doc, "c1")


def test_모든_질문이_골자를_갖는다():
    """하나라도 비면 그 질문만 되묻기 종료가 허전해진다."""
    doc = doc_of(questions_payload(), track="10")
    assert all(q.answer_gist.strip() for q in doc.questions)


def test_골자도_길이_상한을_지킨다():
    doc = doc_of(questions_payload(
        {"node_id": "c1", "question": "질문", "answer_gist": "긴 골자 " * 200}
    ))
    assert len(gist_of(doc, "c1")) <= QA_TEXT_MAX


def test_골자가_왕복해도_남는다():
    doc = doc_of(questions_payload(
        {"node_id": "c1", "question": "질문", "answer_gist": "왕복 확인용 골자"}
    ))
    assert gist_of(QuestionDoc.from_dict(doc.to_dict()), "c1") == "왕복 확인용 골자"


def test_골자_요청이_프롬프트_스키마에_들어간다():
    """출력 스키마에 없으면 LLM 이 낼 이유가 없다."""
    from chuckchuck.f08_questions import QUESTION_SYSTEM_PROMPT

    assert "answer_gist" in QUESTION_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# 후보 선정이 ConceptGraph 를 실제로 읽는가
#
# 조인 키는 slide_nos 다 (SCHEMA §6-B). weight·summary·edges·sections[].slide_role
# 넷이 순위에 실제로 반영되는지 — 전부 코드가 결정하고 LLM 은 관여하지 않는다.
# ---------------------------------------------------------------------------

def _roled_graph(roles: dict[int, str], weights: dict[str, float]) -> ConceptGraph:
    """slide_no → 구획 역할, node_id → weight 로 그래프를 짓는다. 간선은 없다."""
    nodes = [
        ConceptNode(id=nid, label=nid, slide_nos=[no], summary=f"{nid} 요약", weight=w)
        for no, (nid, w) in enumerate(weights.items(), start=1)
    ]
    sections = [
        Section(name=role, slide_role=role, slide_nos=[no])
        for no, role in roles.items()
    ]
    return ConceptGraph(
        file_name="t.pdf", total_slides=len(nodes), nodes=nodes, sections=sections
    )


def _ids(graph, **kw):
    return [m.node_id for m in make_triage(graph, **kw).marks]


def test_표지_개념은_더_무거워도_본론_개념에_밀린다():
    """'감사합니다' 장의 개념은 자료가 크게 다뤄도 심사 질문 대상이 아니다."""
    graph = _roled_graph({1: "cover", 2: "body"}, {"cover_c": 1.0, "body_c": 0.1})
    assert _ids(graph) == ["body_c", "cover_c"]


def test_맺음말은_서론보다_뒤다():
    graph = _roled_graph({1: "closing", 2: "intro"}, {"close_c": 1.0, "intro_c": 1.0})
    assert _ids(graph) == ["intro_c", "close_c"]


def test_본론과_결론은_같은_순위라_weight_가_정한다():
    """구획은 '물어볼 만한 구획인가' 만 가른다. 그 안의 서열은 weight 다."""
    graph = _roled_graph({1: "body", 2: "conclusion"}, {"body_c": 0.2, "concl_c": 0.9})
    assert _ids(graph) == ["concl_c", "body_c"]


def test_구획이_없으면_전부_본론으로_보고_weight_순이다():
    """F-07 이 sections 를 못 만든 발표에서 질문이 이상해지면 안 된다."""
    graph = make_graph()          # sections 없음
    assert _ids(graph) == ["c1", "c2", "c3"]


def test_여러_구획에_걸치면_가장_앞선_구획으로_본다():
    """한 장이라도 본론에서 다뤘으면 물어볼 거리가 있다."""
    from chuckchuck.f08_questions import _role_rank_of

    node = ConceptNode(id="x", label="x", slide_nos=[1, 2], weight=1.0)
    graph = ConceptGraph(
        file_name="t.pdf", total_slides=2, nodes=[node],
        sections=[
            Section(name="표지", slide_role="cover", slide_nos=[1]),
            Section(name="본론", slide_role="body", slide_nos=[2]),
        ],
    )
    assert _role_rank_of(graph, node) == 0


def test_요약이_빈_개념은_같은_조건에서_뒤로_밀린다():
    """질문 문장을 쓸 재료가 없으면 사전식 정의 질문밖에 안 나온다."""
    graph = ConceptGraph(
        file_name="t.pdf", total_slides=2,
        nodes=[
            ConceptNode(id="empty", label="e", slide_nos=[1], summary="", weight=0.5),
            ConceptNode(id="full", label="f", slide_nos=[2], summary="한 줄", weight=0.5),
        ],
    )
    assert _ids(graph) == ["full", "empty"]


def test_같은_근거_안에서_연결된_개념은_뒤로_밀린다():
    """edges 가 인접을 안다 — 한 답으로 커버되는 질문을 나란히 내지 않는다."""
    nodes = [
        ConceptNode(id="a", label="a", slide_nos=[1], summary="a", weight=0.9),
        ConceptNode(id="b", label="b", slide_nos=[2], summary="b", weight=0.8),
        ConceptNode(id="far", label="far", slide_nos=[3], summary="far", weight=0.7),
    ]
    graph = ConceptGraph(
        file_name="t.pdf", total_slides=3, nodes=nodes,
        edges=[ConceptEdge(from_id="a", to_id="b", kind="relates")],
    )
    # a 와 붙은 b 는 far 뒤로 밀린다. weight 만 보면 b 가 far 보다 앞이다.
    assert _ids(graph) == ["a", "far", "b"]


def test_인접_강등은_근거_우선순위를_넘지_않는다():
    """
    별 모양 그래프에서 루트가 무너지면 안 된다.

    c1 은 c2·c3 의 부모라 모든 자식과 인접하다. 자식 하나가 '누락' 으로 먼저 뽑혔다고
    자료에서 가장 무거운 개념이 맨 뒤로 밀리면 리포트와 질문이 어긋난다.
    """
    graph = make_graph()
    ids = _ids(graph, alignment=make_alignment({"c3": "missing"}, graph))
    assert ids[0] == "c3"          # 누락이 최우선
    assert ids[1] == "c1"          # 루트가 인접을 이유로 밀리지 않는다


def test_모순_누락_근거는_인접해도_강등되지_않는다():
    graph = make_graph()
    ids = _ids(
        graph,
        alignment=make_alignment({"c2": "missing", "c3": "contradiction"}, graph),
    )
    assert ids[:2] == ["c3", "c2"], "모순 > 누락 이고, 둘 다 인접 강등 면제다"


def test_같은_그래프면_순위가_언제나_같다():
    graph = _roled_graph({1: "body", 2: "intro", 3: "cover"},
                         {"a": 0.9, "b": 0.9, "c": 0.9})
    assert _ids(graph) == _ids(graph)


# ---------------------------------------------------------------------------
# under_spoken — 자료 축(doc_weight) vs 발화 축(speech_weight) 격차
#
# 두 축이 이미 같은 node_id 로 조인돼 있어 뺄셈 한 번이면 나온다. LLM 이 필요 없다.
# ---------------------------------------------------------------------------

def _sources(graph, **kw) -> dict[str, str]:
    return {m.node_id: m.source for m in make_triage(graph, **kw).marks}


def test_중요한데_설명이_짧았던_개념은_under_spoken():
    graph = make_graph()
    src = _sources(
        graph,
        alignment=make_alignment({}, graph, speech_weights={"c2": 0.0}),
    )
    assert src["c2"] == "under_spoken"
    assert src["c1"] == "core_weight", "격차가 없는 개념은 그대로다"


def test_격차가_임계_이하면_under_spoken_이_아니다():
    from chuckchuck.contracts import QA_UNDER_SPOKEN_GAP

    graph = make_graph()
    # doc_weight 는 make_graph 에서 c2=0.99. 임계보다 조금 덜 벌린다.
    barely = 0.99 - QA_UNDER_SPOKEN_GAP + 0.01
    src = _sources(graph, alignment=make_alignment({}, graph, speech_weights={"c2": barely}))
    assert src["c2"] == "core_weight"


def test_정당생략은_격차가_커도_under_spoken_이_아니다():
    """리포트가 '생략이 합리적' 이라 해 놓고 질문에서 캐물으면 두 화면이 어긋난다."""
    graph = make_graph()
    src = _sources(
        graph,
        alignment=make_alignment(
            {"c2": "justified_skip"}, graph, speech_weights={"c2": 0.0}
        ),
    )
    assert src["c2"] == "justified_skip"


def test_정당생략은_자료_비중이_커도_서열_맨_뒤다():
    """weight 0.99 인 정당생략이 0.98 인 정합 개념보다 먼저 질문받으면 안 된다."""
    graph = make_graph()   # c1=1.0 > c2=0.99 > c3=0.98
    marks = make_triage(
        graph, alignment=make_alignment({"c2": "justified_skip"}, graph)
    ).marks
    order = [m.node_id for m in marks]
    assert order == ["c1", "c3", "c2"]


def test_정당생략은_흐름_결손을_덮는다():
    """생략이 합리적이면 그 개념의 연결 결손도 캐물을 일이 아니다."""
    graph = make_graph()
    src = _sources(
        graph,
        alignment=make_alignment({"c2": "justified_skip"}, graph),
        flow=make_flow(("c1", "c2")),
    )
    assert src["c2"] == "justified_skip"
    assert src["c1"] == "weak_flow"     # 정합 개념의 흐름 결손은 그대로 남는다


def test_정당생략은_누락을_덮지_못한다():
    """확인된 문제(모순·누락)는 정당생략이 강등할 수 없다 — 중복 항목 방어."""
    graph = make_graph()
    alignment = make_alignment({"c2": "missing"}, graph)
    alignment.items.append(
        AlignmentItem(node_id="c2", verdict="justified_skip",
                      doc_weight=0.99, speech_weight=0.0)
    )
    assert _sources(graph, alignment=alignment)["c2"] == "missing"


def test_정당생략이_먼저_와도_누락이_이긴다():
    """중복 항목의 처리 순서와 무관하게 확인된 문제가 이긴다 (claim 의 rank 최소화)."""
    graph = make_graph()
    alignment = make_alignment({"c2": "justified_skip"}, graph)
    alignment.items.append(
        AlignmentItem(node_id="c2", verdict="missing",
                      doc_weight=0.99, speech_weight=0.0)
    )
    assert _sources(graph, alignment=alignment)["c2"] == "missing"


def test_정당생략의_폴백_severity_는_가벼움이다():
    graph = make_graph()
    marks = make_triage(
        graph, alignment=make_alignment({"c2": "justified_skip"}, graph)
    ).marks
    skip = next(m for m in marks if m.node_id == "c2")
    assert skip.severity == 3


def test_누락이_under_spoken_을_이긴다():
    graph = make_graph()
    src = _sources(
        graph,
        alignment=make_alignment({"c2": "missing"}, graph, speech_weights={"c2": 0.0}),
    )
    assert src["c2"] == "missing"


def test_under_spoken_은_흐름_결손보다_앞이다():
    graph = make_graph()
    marks = make_triage(
        graph,
        alignment=make_alignment({}, graph, speech_weights={"c3": 0.0}),
        flow=make_flow(("c2", "c1")),
    ).marks
    order = [m.source for m in marks]
    assert order.index("under_spoken") < order.index("weak_flow")


# ---------------------------------------------------------------------------
# 흐름 이슈 상세 — 순서·구조 질문의 재료
# ---------------------------------------------------------------------------

def _order_jump_flow(note: str = "") -> FlowDiff:
    """c1(부모)보다 c2(자식)를 먼저 말한 order_jump. note 는 F-11 이 만드는 문장."""
    return FlowDiff(
        file_name="sample.pdf",
        issues=[FlowIssue(kind="order_jump", node_ids=["c1", "c2"], note=note)],
    )


def test_순서_역행_상세가_triage_프롬프트에_실린다():
    graph = make_graph()
    llm = ScriptedLLM('{"marks": []}')
    triage_questions(
        graph,
        flow=_order_jump_flow(note="'개념2' 을(를) 상위 개념 '개념1' 보다 먼저 말했어요"),
        llm=llm,
    )
    assert "흐름(order_jump)" in llm.prompts[0]
    assert "먼저 말했어요" in llm.prompts[0]


def test_흐름_상세는_weak_flow_근거_개념에만_붙는다():
    """누락으로 뽑힌 개념에 흐름 이슈까지 얹으면 LLM 이 근거를 섞어 각도를 잡는다."""
    graph = make_graph()
    llm = ScriptedLLM('{"marks": []}')
    triage_questions(
        graph,
        alignment=make_alignment({"c2": "missing"}, graph),
        flow=_order_jump_flow(),   # c1·c2 둘 다 이슈에 걸리지만 c2 는 근거가 missing
        llm=llm,
    )
    prompt = llm.prompts[0]
    # 개념 줄에 붙는 상세는 c1(weak_flow) 하나뿐이어야 한다 (머리말 설명 제외).
    assert prompt.count("흐름(order_jump)") == 1


def test_질문_프롬프트에도_흐름_상세가_실린다():
    graph = make_graph()
    flow = _order_jump_flow(note="'개념2' 을(를) 상위 개념 '개념1' 보다 먼저 말했어요")
    triage = make_triage(graph, flow=flow)
    llm = ScriptedLLM('{"questions": []}')
    build_questions(graph, triage, track="10", flow=flow, llm=llm)
    assert "흐름(order_jump)" in llm.prompts[0]


def test_weak_flow_why_폴백은_이슈_종류를_따른다():
    """순서 역행에 '연결이 안 드러났다' 를 붙이면 질문 의도를 오해한다."""
    graph = make_graph()
    flow = _order_jump_flow()
    triage = make_triage(graph, flow=flow)
    doc = doc_of('{"questions": []}', graph=graph, triage=triage, flow=flow)
    jump = next(q for q in doc.questions if q.source == "weak_flow")
    assert "순서" in jump.why


def test_flow_없이_만든_질문의_why_는_기존_문구다():
    """flow 를 안 주는 기존 호출 경로는 일반 weak_flow 문구로 그대로 동작한다."""
    graph = make_graph()
    flow = _order_jump_flow()
    triage = make_triage(graph, flow=flow)   # triage 는 flow 로 순위만 잡고
    doc = doc_of('{"questions": []}', graph=graph, triage=triage)  # 질문은 flow 없이
    jump = next(q for q in doc.questions if q.source == "weak_flow")
    assert jump.why == "다른 개념과의 연결이 발표에서 드러나지 않았어요"


# ---------------------------------------------------------------------------
# extra_concepts — 발화에만 나온 개념
#
# 새 그래프를 만들지 않는다. `extra:` 네임스페이스로 기존 node_id 축에 얹는다.
# ---------------------------------------------------------------------------

def test_발화에만_나온_개념도_질문_후보가_된다():
    graph = make_graph()
    alignment = make_alignment({}, graph, extras=[("온도 파라미터", "온도를 낮추면…", 4)])
    ids = _ids(graph, alignment=alignment)
    assert "extra:온도 파라미터" in ids


def test_합성_노드는_접두사로_그래프_노드와_구분된다():
    """리포트가 이 접두사로 개념 판정과 발화 개념을 갈라 본다."""
    from chuckchuck.f08_questions import EXTRA_ID_PREFIX

    graph = make_graph()
    alignment = make_alignment({}, graph, extras=[("온도", "인용", None)])
    doc = build_questions(
        graph, make_triage(graph, alignment=alignment), track="10",
        alignment=alignment, llm="mock",
    )
    synth = [q for q in doc.questions if q.node_id.startswith(EXTRA_ID_PREFIX)]
    assert len(synth) == 1
    assert synth[0].label == "온도"
    assert synth[0].source == "extra"
    assert not any(n.id.startswith(EXTRA_ID_PREFIX) for n in graph.nodes), \
        "그래프 자체는 오염되지 않는다"


def test_발화_개념은_자료_결손보다_뒤다():
    graph = make_graph()
    alignment = make_alignment({"c3": "missing"}, graph, extras=[("온도", "인용", None)])
    ids = _ids(graph, alignment=alignment)
    assert ids.index("c3") < ids.index("extra:온도")


def test_발화_개념은_자료_비중보다_앞이다():
    """발표자가 실제로 입 밖에 낸 개념이라 되물을 근거가 확실하다."""
    graph = make_graph()
    alignment = make_alignment({}, graph, extras=[("온도", "인용", None)])
    ids = _ids(graph, alignment=alignment)
    assert ids.index("extra:온도") < ids.index("c1")


def test_발화_개념은_상한까지만_올라온다():
    from chuckchuck.contracts import QA_EXTRA_MAX

    graph = make_graph()
    alignment = make_alignment(
        {}, graph, extras=[(f"개념{i}", "인용", None) for i in range(QA_EXTRA_MAX + 3)]
    )
    ids = _ids(graph, alignment=alignment)
    assert len([i for i in ids if i.startswith("extra:")]) == QA_EXTRA_MAX


def test_빈_라벨과_중복_발화_개념은_버려진다():
    graph = make_graph()
    alignment = make_alignment(
        {}, graph, extras=[("", "인용", None), ("온도", "a", None), ("온도", "b", None)]
    )
    ids = [i for i in _ids(graph, alignment=alignment) if i.startswith("extra:")]
    assert ids == ["extra:온도"]


def test_발화_개념은_인용을_요약으로_들고_온다():
    """질문 문장을 쓸 재료다. 비면 사전식 정의 질문밖에 안 나온다."""
    from chuckchuck.f08_questions import _extra_nodes

    alignment = make_alignment({}, make_graph(), extras=[("온도", "온도를 낮추면…", 4)])
    node = _extra_nodes(alignment)[0]
    assert node.summary == "온도를 낮추면…"
    assert node.slide_nos == [4]
    assert node.weight == 0.0, "자료가 배분한 양이 없는 개념이다"


def test_정합_문서가_없으면_발화_개념도_없다():
    assert _ids(make_graph()) == ["c1", "c2", "c3"]
