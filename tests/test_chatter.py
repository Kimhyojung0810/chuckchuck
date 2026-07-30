"""
삐약 청중석(build_chatter)이 계약 불변식을 지키는지 검사하는 테스트입니다.
AUDIENCE_CHATTER_PLAN.md Phase 2 의 불변식 11개가 여기 그대로 대응됩니다.

전부 MockLLM 또는 테스트 안에서 만든 가짜 프로바이더로 돌아갑니다 —
네트워크·API 키가 전혀 필요 없습니다.
"""

import json

import pytest

from chuckchuck.contracts import (
    CHATTER_MOODS,
    CHATTER_SPEAKERS,
    AlignmentDoc,
    AlignmentItem,
    AlignmentSummary,
    ChatterDoc,
    ChatterError,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    ExtraConcept,
    SpeechBasis,
    SpeechEdge,
)
from chuckchuck.f11_flow import build_flow_diff
from chuckchuck.f12_chatter import (
    MAX_TURNS,
    SMALLTALK_RATIO,
    allowed_refs,
    build_chatter,
    pick_talking_points,
)
from chuckchuck.providers.llm_impl import MockLLM


# ---------------------------------------------------------------------------
# 헬퍼 — 노드 4개짜리 소형 픽스처 (aligned / missing / contradiction / ghost)
# ---------------------------------------------------------------------------

def make_graph() -> ConceptGraph:
    nodes = [
        ConceptNode(id="c1", label="대조 학습", slide_nos=[1], weight=1.0, depth=1),
        ConceptNode(id="c2", label="공동 임베딩", slide_nos=[2], weight=0.8,
                    parent_id="c1", depth=2),
        ConceptNode(id="c3", label="온도 파라미터", slide_nos=[3], weight=0.6,
                    parent_id="c1", depth=2),
        ConceptNode(id="c4", label="평가 지표", slide_nos=[4], weight=0.4,
                    parent_id="c1", depth=2),
    ]
    edges = [
        ConceptEdge(from_id="c1", to_id="c2", kind="parent"),
        ConceptEdge(from_id="c1", to_id="c3", kind="parent"),
        ConceptEdge(from_id="c1", to_id="c4", kind="parent"),
    ]
    return ConceptGraph(file_name="sample.pdf", total_slides=4, nodes=nodes, edges=edges)


def make_alignment(graph: ConceptGraph) -> AlignmentDoc:
    """c1 정합 · c2 정합 · c3 누락 · c4 모순. c3 는 첫 언급이 없어 ghost 가 된다."""
    spec = {
        "c1": ("aligned", 3, 1.0, 2.0, "그래서 대조 학습으로 정렬합니다"),
        "c2": ("aligned", 2, 0.7, 12.0, "공동 임베딩 공간을 만듭니다"),
        "c3": ("missing", 0, 0.0, None, ""),
        "c4": ("contradiction", 1, 0.2, 30.0, "평가 지표는 정확도 하나만 봤습니다"),
    }
    items = []
    for node in graph.nodes:
        verdict, mentions, sw, first, evidence = spec[node.id]
        items.append(AlignmentItem(
            node_id=node.id,
            verdict=verdict,
            speech_weight=sw,
            doc_weight=node.weight,
            evidence=evidence,
            speech_basis=SpeechBasis(
                speech_sec=10.0,
                time_share=0.25,
                mention_count=mentions,
                mentioned_slide_count=1 if mentions else 0,
                first_mention_sec=first,
            ),
        ))
    return AlignmentDoc(
        file_name=graph.file_name,
        total_slides=graph.total_slides,
        items=items,
        speech_edges=[SpeechEdge(from_id="c1", to_id="c2",
                                 cue="이걸 바탕으로", in_graph=True)],
        extra_concepts=[ExtraConcept(label="하드 네거티브",
                                     quote="하드 네거티브가 중요한데", slide_no=2)],
        summary=AlignmentSummary(coverage=0.5, speech_total_sec=185.0),
    )


@pytest.fixture
def bundle():
    graph = make_graph()
    alignment = make_alignment(graph)
    flow = build_flow_diff(graph, alignment)
    return graph, alignment, flow


def mock_factory(_speaker: str) -> MockLLM:
    return MockLLM()


def chatter_of(bundle, **kwargs) -> ChatterDoc:
    graph, alignment, flow = bundle
    kwargs.setdefault("llm_factory", mock_factory)
    return build_chatter(graph, alignment, flow, **kwargs)


class ScriptedLLM:
    """지정한 JSON 문자열을 그대로 돌려주는 가짜 프로바이더."""

    name = "scripted"

    def __init__(self, payload: str):
        self.payload = payload

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096) -> str:
        return self.payload


class DeadLLM:
    """호출하면 터지는 프로바이더 — 결석한 청중을 흉내낸다."""

    name = "dead"

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096) -> str:
        raise RuntimeError("endpoint down")


# ---------------------------------------------------------------------------
# 불변식 1 : 4명 전원 최소 1턴
# ---------------------------------------------------------------------------

def test_every_speaker_appears(bundle):
    doc = chatter_of(bundle)
    for speaker in CHATTER_SPEAKERS:
        assert doc.turns_of(speaker), f"{speaker} 가 한 마디도 안 했다"


# ---------------------------------------------------------------------------
# 불변식 2 : refs 의 node_id 는 그래프에 실존
# ---------------------------------------------------------------------------

def test_refs_node_ids_exist(bundle):
    graph, _, _ = bundle
    known = {n.id for n in graph.nodes}
    doc = chatter_of(bundle)
    for turn in doc.turns:
        for ref in turn.refs:
            assert ref.node_id in known


# ---------------------------------------------------------------------------
# 불변식 3 : refs 는 그 병아리에게 배정된 talking point 안에서만
# ---------------------------------------------------------------------------

def test_refs_within_talking_points(bundle):
    graph, alignment, flow = bundle
    points = pick_talking_points(graph, alignment, flow)
    allowed = {sp: allowed_refs(pts) for sp, pts in points.items()}

    doc = chatter_of(bundle)
    for turn in doc.turns:
        for ref in turn.refs:
            assert ref.node_id in allowed[turn.speaker], (
                f"{turn.speaker} 가 배정 밖 노드 {ref.node_id} 를 언급했다"
            )


def test_refs_outside_assignment_are_dropped(bundle):
    """LLM 이 남의 담당 노드나 없는 노드를 가리켜도 어댑터가 떼어낸다."""
    graph, alignment, flow = bundle
    payload = json.dumps({"turns": [
        {"text": "어... 그 뭐였더라, 아무튼 그거.", "mood": "curious",
         "ref_node_ids": ["없는노드", "c2"]},
    ]}, ensure_ascii=False)

    doc = build_chatter(graph, alignment, flow,
                        llm_factory=lambda s: ScriptedLLM(payload), rounds=1)
    points = pick_talking_points(graph, alignment, flow)
    for turn in doc.turns:
        for ref in turn.refs:
            assert ref.node_id in allowed_refs(points[turn.speaker])
            assert ref.node_id != "없는노드"


# ---------------------------------------------------------------------------
# 불변식 4 : 스몰토크 비율 상한
# ---------------------------------------------------------------------------

def test_smalltalk_ratio(bundle):
    doc = chatter_of(bundle)
    smalltalk = sum(1 for t in doc.turns if t.is_smalltalk)
    # 각 병아리의 마지막 한 턴은 지우지 않으므로 speaker 수만큼은 초과할 수 있다
    assert smalltalk <= int(len(doc.turns) * SMALLTALK_RATIO) + len(CHATTER_SPEAKERS)


# ---------------------------------------------------------------------------
# 불변식 5 : mood 는 enum 안. 밖이면 neutral
# ---------------------------------------------------------------------------

def test_mood_fallback(bundle):
    graph, alignment, flow = bundle
    payload = json.dumps({"turns": [
        {"text": "오홍, 그거 뭐였지.", "mood": "황당함", "ref_node_ids": []},
    ]}, ensure_ascii=False)

    doc = build_chatter(graph, alignment, flow,
                        llm_factory=lambda s: ScriptedLLM(payload), rounds=1)
    assert doc.turns, "대사가 하나도 안 나왔다"
    for turn in doc.turns:
        assert turn.mood in CHATTER_MOODS
    assert any(t.mood == "neutral" for t in doc.turns)


# ---------------------------------------------------------------------------
# 불변식 6 : 턴 수 상한
# ---------------------------------------------------------------------------

def test_turn_cap(bundle):
    doc = chatter_of(bundle, rounds=8)
    assert len(doc.turns) <= MAX_TURNS


# ---------------------------------------------------------------------------
# 불변식 7 : JSON 왕복
# ---------------------------------------------------------------------------

def test_roundtrip(bundle):
    doc = chatter_of(bundle)
    again = ChatterDoc.from_dict(doc.to_dict())
    assert again.to_dict() == doc.to_dict()
    assert [t.speaker for t in again.turns] == [t.speaker for t in doc.turns]


def test_badges_and_names_are_carried(bundle):
    """모델 배지는 심사위원 어필 포인트라 항상 실려 나간다."""
    doc = chatter_of(bundle)
    assert doc.speaker_models["midm"] == "KT 믿:음"
    assert doc.speaker_models["ax"] == "SKT A.X"
    assert set(doc.speaker_models) == set(CHATTER_SPEAKERS)
    assert doc.speaker_names["exaone"] == "엑사원"


# ---------------------------------------------------------------------------
# 불변식 8 : 프로바이더가 죽어도 그 병아리만 조는 대사로 대체
# ---------------------------------------------------------------------------

def test_provider_failure_fallback(bundle):
    graph, alignment, flow = bundle

    def factory(speaker):
        return DeadLLM() if speaker == "exaone" else MockLLM()

    doc = build_chatter(graph, alignment, flow, llm_factory=factory)
    assert len(doc.turns_of("exaone")) == 1
    assert "못 왔어요" in doc.turns_of("exaone")[0].text
    # 결석은 프론트가 추측하면 안 된다 — 대타를 받은 speaker 가 곧 absent 다
    assert doc.absent == ["exaone"]
    for speaker in CHATTER_SPEAKERS:
        assert doc.turns_of(speaker)


def test_absent_is_empty_when_every_model_answers(bundle):
    """refs 가 빈 대사를 냈다고 결석이 아니다. 멀쩡히 답한 병아리는 absent 에 없다."""
    graph, alignment, flow = bundle
    doc = build_chatter(graph, alignment, flow, llm_factory=lambda s: MockLLM())
    assert doc.absent == []
    # 실제로 refs 없는 턴이 섞여 있어도(엑씨의 애드립·발표 시간은 node_ids 가 없다)
    # 그것 때문에 결석 처리되면 안 된다
    assert set(t.speaker for t in doc.turns) == set(CHATTER_SPEAKERS)


def test_provider_construction_failure_is_absorbed(bundle):
    """API 키가 없어 프로바이더 생성부터 실패해도 청중석은 열린다."""
    graph, alignment, flow = bundle

    def factory(speaker):
        if speaker == "midm":
            raise RuntimeError("no api key")
        return MockLLM()

    doc = build_chatter(graph, alignment, flow, llm_factory=factory)
    assert len(doc.turns_of("midm")) == 1
    assert doc.turns_of("midm")[0].is_smalltalk


# ---------------------------------------------------------------------------
# 불변식 9 : 입력이 비면 ChatterError
# ---------------------------------------------------------------------------

def test_empty_alignment_raises(bundle):
    graph, alignment, flow = bundle
    alignment.items = []
    with pytest.raises(ChatterError):
        build_chatter(graph, alignment, flow, llm_factory=mock_factory)


def test_empty_graph_raises(bundle):
    graph, alignment, flow = bundle
    graph.nodes = []
    with pytest.raises(ChatterError):
        build_chatter(graph, alignment, flow, llm_factory=mock_factory)


# ---------------------------------------------------------------------------
# 불변식 10 : 성격이 배정에서 나온다 — 각 모델이 실제로 한 일과 담당 데이터가 일치
# ---------------------------------------------------------------------------

def test_midm_only_references_broken_concepts(bundle):
    """믿:음 = 신뢰. 어긋난 개념만 물고 늘어진다."""
    graph, alignment, flow = bundle
    points = pick_talking_points(graph, alignment, flow)
    broken = {
        i.node_id for i in alignment.items
        if i.verdict in ("missing", "contradiction")
        or i.doc_weight - i.speech_weight > 0.4
    }
    assert allowed_refs(points["midm"]) <= broken
    assert "c3" in allowed_refs(points["midm"])   # 누락된 개념은 반드시 포함


def test_exaone_only_references_praiseworthy(bundle):
    """EXAONE = 전문가 AI. 칭찬할 것만 본다."""
    graph, alignment, flow = bundle
    points = pick_talking_points(graph, alignment, flow)
    aligned = {i.node_id for i in alignment.items if i.verdict == "aligned"}
    assert allowed_refs(points["exaone"]) <= aligned


def test_solar_reads_flow_and_ax_reads_speech(bundle):
    """쏠라=자료를 읽은 모델이라 흐름, 엑씨=발표를 들은 모델이라 발화 축."""
    graph, alignment, flow = bundle
    points = pick_talking_points(graph, alignment, flow)
    assert points["solar"] and all(p.source == "flow" for p in points["solar"])
    facts = " ".join(p.fact for p in points["ax"])
    assert "하드 네거티브" in facts        # 자료에 없던 애드립을 들었다


def test_talking_points_are_deterministic(bundle):
    graph, alignment, flow = bundle
    assert pick_talking_points(graph, alignment, flow) == pick_talking_points(
        graph, alignment, flow
    )


# ---------------------------------------------------------------------------
# 불변식 11 : 톤 가이드 — 발표자 인신 평가는 내보내지 않는다
# ---------------------------------------------------------------------------

def test_tone_filter_drops_personal_remarks(bundle):
    graph, alignment, flow = bundle
    payload = json.dumps({"turns": [
        {"text": "목소리가 좀 별로였어.", "mood": "grumpy", "ref_node_ids": []},
        {"text": "발표 못 하는 것 같은데.", "mood": "grumpy", "ref_node_ids": []},
    ]}, ensure_ascii=False)

    doc = build_chatter(graph, alignment, flow,
                        llm_factory=lambda s: ScriptedLLM(payload), rounds=1)
    for turn in doc.turns:
        assert "목소리" not in turn.text
        assert "발표 못" not in turn.text
    # 전부 걸러졌으니 네 마리 다 결정적 대타로 채워졌다
    assert len(doc.turns) == len(CHATTER_SPEAKERS)


def test_long_and_empty_turns_are_dropped(bundle):
    graph, alignment, flow = bundle
    payload = json.dumps({"turns": [
        {"text": "아" * 300, "mood": "neutral", "ref_node_ids": []},
        {"text": "   ", "mood": "happy", "ref_node_ids": []},
    ]}, ensure_ascii=False)

    doc = build_chatter(graph, alignment, flow,
                        llm_factory=lambda s: ScriptedLLM(payload), rounds=1)
    assert len(doc.turns) == len(CHATTER_SPEAKERS)   # 전부 대타
    for turn in doc.turns:
        assert 0 < len(turn.text) <= 200


def test_emoji_is_stripped(bundle):
    graph, alignment, flow = bundle
    payload = json.dumps({"turns": [
        {"text": "히히 좋았어 \U0001f423\U0001f496", "mood": "happy", "ref_node_ids": []},
    ]}, ensure_ascii=False)

    doc = build_chatter(graph, alignment, flow,
                        llm_factory=lambda s: ScriptedLLM(payload), rounds=1)
    spoken = [t for t in doc.turns if "좋았어" in t.text]
    assert spoken, "이모지만 지우고 대사는 살아야 한다"
    assert "\U0001f423" not in spoken[0].text


def test_broken_json_falls_back(bundle):
    """JSON 이 두 번 다 깨지면 그 병아리는 대타로 간다 — 전체는 성공."""
    graph, alignment, flow = bundle
    doc = build_chatter(graph, alignment, flow,
                        llm_factory=lambda s: ScriptedLLM("이건 JSON이 아니야"),
                        rounds=1)
    assert len(doc.turns) == len(CHATTER_SPEAKERS)


# ---------------------------------------------------------------------------
# 따로 놀지 않음 — 리포트와 같은 사실을 말하는가
# ---------------------------------------------------------------------------

def test_chatter_references_stay_in_report(bundle):
    graph, alignment, flow = bundle
    doc = chatter_of(bundle)
    judged = {i.node_id for i in alignment.items}
    assert set(doc.referenced_node_ids) <= judged
