"""
F-11 파생 FlowDiff(build_flow_diff)가 계약 불변식을 지키는지 검사하는 테스트입니다.
FLOW_DIFF_PLAN.md §3 의 불변식이 여기 그대로 대응됩니다.

build_flow_diff 는 순수 함수라 LLM·네트워크·API 키가 전혀 필요 없습니다.
"""

import json
from pathlib import Path

import pytest

from chuckchuck.contracts import (
    FLOW_ISSUE_KINDS,
    AlignError,
    AlignmentDoc,
    AlignmentItem,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    ExtraConcept,
    FlowDiff,
    SpeechBasis,
    SpeechEdge,
    Transcript,
)
from chuckchuck.f11_flow import build_flow_diff

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def make_graph(n: int = 3, edges: list[ConceptEdge] | None = None) -> ConceptGraph:
    """작은 ConceptGraph. c1 이 최상위(weight 1.0, 슬라이드 1), 뒤로 갈수록 가볍다."""
    nodes = [
        ConceptNode(
            id=f"c{i}",
            label=f"개념{i}",
            slide_nos=[i],
            weight=round(1.0 - 0.2 * (i - 1), 3),
            parent_id="c1" if i > 1 else None,
            depth=1 if i == 1 else 2,
        )
        for i in range(1, n + 1)
    ]
    if edges is None:
        edges = [
            ConceptEdge(from_id="c1", to_id=f"c{i}", kind="parent")
            for i in range(2, n + 1)
        ]
    return ConceptGraph(
        file_name="sample.pdf",
        total_slides=n,
        nodes=nodes,
        edges=edges,
    )


def make_alignment(
    graph: ConceptGraph,
    *,
    first: dict[str, float | None] | None = None,
    mentions: dict[str, int] | None = None,
    speech_edges: list[SpeechEdge] | None = None,
    extras: list[str] | None = None,
) -> AlignmentDoc:
    """
    그래프의 모든 노드에 item 1개씩 손으로 만든 AlignmentDoc.

    first: node_id → first_mention_sec (없으면 None)
    mentions: node_id → mention_count (없으면 first 가 있으면 1, 없으면 0)
    """
    first = first or {}
    mentions = mentions or {}
    items = []
    for node in graph.nodes:
        f = first.get(node.id)
        m = mentions.get(node.id, 1 if f is not None else 0)
        items.append(AlignmentItem(
            node_id=node.id,
            verdict="aligned" if m else "missing",
            doc_weight=node.weight,
            speech_basis=SpeechBasis(mention_count=m, first_mention_sec=f),
        ))
    return AlignmentDoc(
        file_name=graph.file_name,
        total_slides=graph.total_slides,
        items=items,
        speech_edges=speech_edges or [],
        extra_concepts=[ExtraConcept(label=x) for x in (extras or [])],
    )


def flow_of(graph=None, **kwargs) -> FlowDiff:
    g = graph or make_graph()
    return build_flow_diff(g, make_alignment(g, **kwargs))


def issues_of(flow: FlowDiff, kind: str):
    return [i for i in flow.issues if i.kind == kind]


# ---------------------------------------------------------------------------
# 왕복 · 불변식 1 : steps 는 모든 노드를 정확히 1개씩
# ---------------------------------------------------------------------------

def test_roundtrip():
    flow = flow_of(first={"c1": 1.0, "c2": 5.0}, extras=["새 개념"])
    again = FlowDiff.from_dict(flow.to_dict())
    assert again.to_dict() == flow.to_dict()
    assert [s.node_id for s in again.steps] == [s.node_id for s in flow.steps]


def test_steps_cover_all_nodes_exactly_once():
    flow = flow_of()
    assert sorted(s.node_id for s in flow.steps) == ["c1", "c2", "c3"]


def test_doc_order_follows_slide_order():
    # 노드 순서를 섞어도 doc_order 는 근거 슬라이드 순이다
    g = make_graph()
    g.nodes = [g.nodes[2], g.nodes[0], g.nodes[1]]  # c3, c1, c2
    flow = build_flow_diff(g, make_alignment(g))
    by_id = {s.node_id: s.doc_order for s in flow.steps}
    assert by_id == {"c1": 1, "c2": 2, "c3": 3}


# ---------------------------------------------------------------------------
# 불변식 2 : speech_order 는 first_mention 있는 노드에만, 1..k 연속
# ---------------------------------------------------------------------------

def test_speech_order_consecutive_and_only_when_first_mention():
    flow = flow_of(first={"c1": 10.0, "c3": 2.0})
    by_id = {s.node_id: s for s in flow.steps}
    assert by_id["c3"].speech_order == 1     # 2초 — 먼저 말함
    assert by_id["c1"].speech_order == 2
    assert by_id["c2"].speech_order is None  # 언급 시각 없음
    orders = sorted(s.speech_order for s in flow.steps if s.speech_order is not None)
    assert orders == [1, 2]


def test_ghost_nodes_listed():
    flow = flow_of(first={"c1": 1.0})
    assert flow.ghost_node_ids == ["c2", "c3"]
    assert flow.spoken_node_count == 1


# ---------------------------------------------------------------------------
# order_tau : 문서 순서 vs 발화 순서 일치도
# ---------------------------------------------------------------------------

def test_order_tau_perfect():
    flow = flow_of(first={"c1": 1.0, "c2": 2.0, "c3": 3.0})
    assert flow.order_tau == 1.0


def test_order_tau_fully_inverted():
    flow = flow_of(first={"c1": 3.0, "c2": 2.0, "c3": 1.0})
    assert flow.order_tau == -1.0


def test_order_tau_none_when_fewer_than_two_spoken():
    assert flow_of(first={"c1": 1.0}).order_tau is None
    assert flow_of().order_tau is None


# ---------------------------------------------------------------------------
# order_jump : 위계상 부모→자식 역행만
# ---------------------------------------------------------------------------

def test_order_jump_child_spoken_before_parent():
    flow = flow_of(first={"c1": 10.0, "c2": 1.0, "c3": 20.0})
    jumps = issues_of(flow, "order_jump")
    assert len(jumps) == 1
    assert jumps[0].node_ids == ["c1", "c2"]
    assert jumps[0].slide_nos == [1, 2]
    assert jumps[0].note


def test_no_order_jump_when_order_matches():
    flow = flow_of(first={"c1": 1.0, "c2": 2.0, "c3": 3.0})
    assert issues_of(flow, "order_jump") == []


def test_no_order_jump_without_first_mention():
    # c2 는 언급됐지만 시각이 없다 (words 없는 Transcript) → 순서 판정 불가
    flow = flow_of(first={"c1": 5.0}, mentions={"c2": 1})
    assert issues_of(flow, "order_jump") == []


def test_no_order_jump_when_child_slide_earlier_in_doc():
    # 자료 자체가 자식을 먼저 두면 (드묾) 역행이 아니다
    g = make_graph()
    g.nodes[0].slide_nos = [3]   # c1(부모)이 슬라이드 3
    g.nodes[2].slide_nos = [1]   # c3 이 슬라이드 1
    flow = build_flow_diff(g, make_alignment(g, first={"c1": 10.0, "c3": 1.0}))
    assert issues_of(flow, "order_jump") == []


# ---------------------------------------------------------------------------
# missing_link : 둘 다 말했는데 잇는 멘트가 없다
# ---------------------------------------------------------------------------

def test_missing_link_both_mentioned_but_unspoken():
    flow = flow_of(first={"c1": 1.0, "c2": 2.0}, mentions={"c1": 1, "c2": 1})
    links = issues_of(flow, "missing_link")
    assert ["c1", "c2"] in [i.node_ids for i in links]
    # c3 은 언급이 없으므로 (c1,c3) 은 missing_link 가 아니다
    assert ["c1", "c3"] not in [i.node_ids for i in links]


def test_missing_link_not_when_spoken_either_direction():
    flow = flow_of(
        first={"c1": 1.0, "c2": 2.0},
        speech_edges=[SpeechEdge(from_id="c2", to_id="c1", cue="그래서", in_graph=True)],
    )
    assert ["c1", "c2"] not in [i.node_ids for i in issues_of(flow, "missing_link")]


def test_missing_link_undirected_pair_deduped():
    g = make_graph(2, edges=[
        ConceptEdge(from_id="c1", to_id="c2", kind="parent"),
        ConceptEdge(from_id="c2", to_id="c1", kind="relates"),
    ])
    flow = build_flow_diff(g, make_alignment(g, first={"c1": 1.0, "c2": 2.0}))
    assert len(issues_of(flow, "missing_link")) == 1


# ---------------------------------------------------------------------------
# good_link : 말로 이은 연결이 문서에도 있다
# ---------------------------------------------------------------------------

def test_good_link_from_in_graph_edge_with_cue():
    flow = flow_of(
        first={"c1": 1.0, "c2": 2.0},
        speech_edges=[SpeechEdge(from_id="c1", to_id="c2", cue="그래서 이어서", in_graph=True)],
    )
    goods = issues_of(flow, "good_link")
    assert len(goods) == 1
    assert goods[0].cue == "그래서 이어서"
    assert goods[0].node_ids == ["c1", "c2"]


def test_good_link_requires_cue():
    flow = flow_of(
        speech_edges=[SpeechEdge(from_id="c1", to_id="c2", cue="", in_graph=True)],
    )
    assert issues_of(flow, "good_link") == []


def test_not_good_link_when_not_in_graph():
    flow = flow_of(
        speech_edges=[SpeechEdge(from_id="c2", to_id="c3", cue="말로만 이음", in_graph=False)],
    )
    assert issues_of(flow, "good_link") == []


def test_issue_kinds_all_valid():
    flow = flow_of(
        first={"c1": 10.0, "c2": 1.0},
        speech_edges=[SpeechEdge(from_id="c1", to_id="c3", cue="그래서", in_graph=True)],
    )
    assert all(i.kind in FLOW_ISSUE_KINDS for i in flow.issues)
    assert all(i.note or i.cue for i in flow.issues)


# ---------------------------------------------------------------------------
# 그 밖의 요약 필드 · 결정성 · 입력 검증
# ---------------------------------------------------------------------------

def test_extra_labels_carried():
    flow = flow_of(extras=["발화 전용 개념"])
    assert flow.extra_labels == ["발화 전용 개념"]


def test_deterministic_same_input_same_output():
    g = make_graph()
    a = make_alignment(g, first={"c1": 3.0, "c2": 1.0, "c3": 2.0})
    assert build_flow_diff(g, a).to_dict() == build_flow_diff(g, a).to_dict()


def test_accepts_dict_inputs():
    g = make_graph()
    a = make_alignment(g, first={"c1": 1.0})
    flow = build_flow_diff(g.to_dict(), a.to_dict())
    assert len(flow.steps) == 3


def test_empty_graph_raises():
    empty = ConceptGraph(file_name="x.pdf", total_slides=0, nodes=[], edges=[])
    with pytest.raises(AlignError):
        build_flow_diff(empty, AlignmentDoc(file_name="x.pdf", total_slides=0))


def test_alignment_missing_node_item_raises():
    g = make_graph()
    bad = make_alignment(g)
    bad.items = bad.items[:2]  # c3 판정 없음
    with pytest.raises(AlignError):
        build_flow_diff(g, bad)


# ---------------------------------------------------------------------------
# Transcript fixture — 실데이터 스왑 지점의 더미
# ---------------------------------------------------------------------------

FIXTURE = ROOT / "fixtures" / "sample_transcript.json"


def test_fixture_transcript_schema_roundtrip():
    t = Transcript.from_dict(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert t.provider == "fixture"
    assert t.full_text.strip()
    assert t.words, "실 A.X 스키마처럼 단어별 시각이 있어야 한다"
    assert t.duration_sec > 0
    assert sorted({s.slide_no for s in t.by_slide}) == [1, 2, 3, 4, 5]
    again = Transcript.from_dict(t.to_dict())
    assert again.to_dict() == t.to_dict()


def test_fixture_scenario_end_to_end_mock_pipeline():
    """완료 기준: mock 파이프라인 + fixture 로 플로우 피드백 3종이 전부 검출된다."""
    from chuckchuck import Context, align_speech, build_graph, extract_concepts
    from chuckchuck.contracts import SlideDoc

    slide_doc = SlideDoc.from_dict(json.loads(
        (ROOT / "fixtures" / "sample_slidedoc.json").read_text(encoding="utf-8")
    ))
    transcript = Transcript.from_dict(json.loads(FIXTURE.read_text(encoding="utf-8")))
    ctx = Context(situation="수업 발표", audience="교수님", duration_min=10)

    concepts = extract_concepts(slide_doc, ctx, llm="mock")
    graph = build_graph(concepts, ctx, slide_doc=slide_doc, llm="mock")
    alignment = align_speech(graph, transcript, ctx, llm="mock")
    flow = build_flow_diff(graph, alignment)

    assert issues_of(flow, "order_jump"), "자식을 부모보다 먼저 말한 시나리오가 걸려야 한다"
    assert issues_of(flow, "missing_link"), "잇는 멘트 없는 문서 간선이 걸려야 한다"
    assert issues_of(flow, "good_link"), "말로 이은 문서 간선이 걸려야 한다"
    assert flow.ghost_node_ids, "한 번도 말하지 않은 개념이 유령 노드로 남아야 한다"
    assert flow.order_tau is not None
