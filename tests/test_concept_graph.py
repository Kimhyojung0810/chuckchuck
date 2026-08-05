"""
F-07 개념 그래프(build_graph)가 계약 불변식을 지키는지 검사하는 테스트입니다.
SCHEMA.md 6-B 의 '보증' 항목이 여기 그대로 대응됩니다.

LLM 은 전부 가짜라서 네트워크·API 키가 필요하지 않습니다.
"""

import pytest

from chuckchuck.contracts import (
    EDGE_KINDS,
    SLIDE_ROLES,
    ConceptDoc,
    ConceptGraph,
    GraphError,
    Slide,
    SlideBlock,
    SlideConcepts,
    SlideDoc,
)
from chuckchuck.f07_graph import MAX_GRAPH_DEPTH, MAX_ROOTS, build_graph
from chuckchuck.providers.llm_base import LLMProvider


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def make_doc(n_slides: int = 5) -> ConceptDoc:
    """작은 ConceptDoc. 1~3장은 core, 그 뒤는 support."""
    return ConceptDoc(
        file_name="sample.pdf",
        total_slides=n_slides,
        model="mock",
        slides=[
            SlideConcepts(
                slide_no=i,
                title=f"슬라이드 {i}",
                topic=f"주제 {i}",
                keywords=[f"kw{i}"],
                concepts=[f"개념{i}: 한 줄 설명"],
                raw_text=f"본문 {i}",
                importance="core" if i <= 3 else "support",
            )
            for i in range(1, n_slides + 1)
        ],
    )


def make_slide_doc(n_slides: int = 5) -> SlideDoc:
    """밀도 신호가 있는 SlideDoc. 2장만 글자가 많고 도식이 있다."""
    return SlideDoc(
        file_name="sample.pdf",
        total_slides=n_slides,
        slides=[
            Slide(
                slide_no=i,
                title=f"슬라이드 {i}",
                blocks=[SlideBlock(category="paragraph", text="가" * (500 if i == 2 else 20))],
                total_char_count=500 if i == 2 else 20,
                has_visual=(i == 2),
                visual_type=["figure"] if i == 2 else [],
            )
            for i in range(1, n_slides + 1)
        ],
    )


class ScriptedLLM(LLMProvider):
    """정해 둔 문자열만 돌려주는 가짜 LLM. 후처리 로직만 시험한다."""

    name = "scripted"

    def __init__(self, payload: str):
        self.payload = payload

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False) -> str:
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


def graph_of(payload: str, *, doc=None, slide_doc=None) -> ConceptGraph:
    return build_graph(doc or make_doc(), slide_doc=slide_doc, llm=ScriptedLLM(payload))


_NO_EDGES = """
{"nodes": [
  {"id": "a", "label": "A", "slide_nos": [1]},
  {"id": "b", "label": "B", "slide_nos": [2]},
  {"id": "c", "label": "C", "slide_nos": [3]}
], "edges": [], "sections": [{"name": "본론", "slide_role": "body", "slide_nos": [1, 2, 3]}]}
"""

_WITH_EDGES = """
{"nodes": [
  {"id": "a", "label": "A", "slide_nos": [1]},
  {"id": "b", "label": "B", "slide_nos": [2]},
  {"id": "c", "label": "C", "slide_nos": [3]}
], "edges": [
  {"from": "a", "to": "b", "kind": "parent"},
  {"from": "a", "to": "c", "kind": "parent"}
], "sections": [{"name": "본론", "slide_role": "body", "slide_nos": [1, 2, 3]}]}
"""


# ---------------------------------------------------------------------------
# mock 파이프라인 · 왕복
# ---------------------------------------------------------------------------

def test_build_graph_mock_runs_without_api_key():
    graph = build_graph(make_doc(), llm="mock")

    assert isinstance(graph, ConceptGraph)
    assert graph.model == "mock"
    assert graph.total_slides == 5
    assert graph.nodes and graph.edges and graph.sections


def test_accepts_dict_inputs():
    """dict 로 들어와도 입구에서 from_dict 한다 (프론트 JSON 직결)."""
    graph = build_graph(
        make_doc().to_dict(),
        {"situation": "대회·IR 피칭", "audience": "심사위원"},
        slide_doc=make_slide_doc().to_dict(),
        llm="mock",
    )
    assert graph.total_slides == 5


def test_roundtrip_to_dict_from_dict():
    graph = build_graph(make_doc(), slide_doc=make_slide_doc(), llm="mock")
    again = ConceptGraph.from_dict(graph.to_dict())

    assert again.to_dict() == graph.to_dict()


def test_edge_serializes_from_as_reserved_word_safe_key():
    """파이썬 필드는 from_id 지만 JSON 키는 'from' 이어야 한다."""
    graph = graph_of(_WITH_EDGES)
    raw = graph.to_dict()["edges"][0]

    assert set(raw) == {"from", "to", "kind"}
    assert raw["kind"] in EDGE_KINDS


# ---------------------------------------------------------------------------
# 노드 불변식
# ---------------------------------------------------------------------------

def test_duplicate_ids_are_made_unique():
    payload = """
    {"nodes": [
      {"id": "a", "label": "첫째", "slide_nos": [1]},
      {"id": "a", "label": "둘째", "slide_nos": [2]}
    ], "edges": [], "sections": []}
    """
    graph = graph_of(payload)
    ids = [n.id for n in graph.nodes]

    assert len(ids) == len(set(ids)) == 2
    assert {n.label for n in graph.nodes} == {"첫째", "둘째"}


def test_out_of_range_slide_nos_are_dropped():
    payload = """
    {"nodes": [{"id": "a", "label": "A", "slide_nos": [0, 2, 99, 3]}],
     "edges": [],
     "sections": [{"name": "본론", "slide_role": "body", "slide_nos": [2, 3, 400]}]}
    """
    graph = graph_of(payload, doc=make_doc(5))

    assert graph.node("a").slide_nos == [2, 3]
    assert graph.sections[0].slide_nos == [2, 3]


def test_unknown_slide_role_falls_back_to_body():
    payload = """
    {"nodes": [], "edges": [], "sections": [
      {"name": "이상한 구획", "slide_role": "결론부", "slide_nos": [1]},
      {"name": "정상 구획", "slide_role": "intro", "slide_nos": [2]}
    ]}
    """
    graph = graph_of(payload)

    assert graph.sections[0].slide_role == "body"
    assert graph.sections[1].slide_role == "intro"
    assert all(s.slide_role in SLIDE_ROLES for s in graph.sections)


def test_importance_inherited_from_concept_doc():
    payload = """
    {"nodes": [
      {"id": "core-one", "label": "핵심", "slide_nos": [1]},
      {"id": "sup-one", "label": "보조", "slide_nos": [4, 5]}
    ], "edges": [], "sections": []}
    """
    graph = graph_of(payload, doc=make_doc(5))

    assert graph.node("core-one").importance == "core"
    assert graph.node("sup-one").importance == "support"


# ---------------------------------------------------------------------------
# 간선 불변식
# ---------------------------------------------------------------------------

def test_edge_to_missing_node_is_dropped():
    payload = """
    {"nodes": [{"id": "a", "label": "A", "slide_nos": [1]}],
     "edges": [{"from": "a", "to": "없는놈", "kind": "parent"},
               {"from": "유령", "to": "a", "kind": "relates"}],
     "sections": []}
    """
    graph = graph_of(payload)

    assert graph.edges == []
    assert graph.node("a").parent_id is None


def test_self_edge_is_dropped():
    payload = """
    {"nodes": [{"id": "a", "label": "A", "slide_nos": [1]}],
     "edges": [{"from": "a", "to": "a", "kind": "parent"}], "sections": []}
    """
    graph = graph_of(payload)

    assert graph.edges == []
    assert graph.node("a").depth == 1


def test_duplicate_edge_is_deduped():
    payload = """
    {"nodes": [{"id": "a", "label": "A", "slide_nos": [1]},
               {"id": "b", "label": "B", "slide_nos": [2]}],
     "edges": [{"from": "a", "to": "b", "kind": "parent"},
               {"from": "a", "to": "b", "kind": "parent"}],
     "sections": []}
    """
    graph = graph_of(payload)

    assert len(graph.edges) == 1


def test_unknown_edge_kind_falls_back_to_relates():
    payload = """
    {"nodes": [{"id": "a", "label": "A", "slide_nos": [1]},
               {"id": "b", "label": "B", "slide_nos": [2]}],
     "edges": [{"from": "a", "to": "b", "kind": "때려맞춤"}], "sections": []}
    """
    graph = graph_of(payload)

    assert len(graph.relates_edges) == 1
    assert graph.node("b").parent_id is None, "relates 는 위계가 아니다"


def test_second_parent_is_demoted_to_relates():
    """개념이 두 상위에 걸리면 정보를 버리지 않고 relates 로 남긴다."""
    payload = """
    {"nodes": [
      {"id": "svc", "label": "링글 AI 서비스", "slide_nos": [1]},
      {"id": "data", "label": "데이터 자산", "slide_nos": [2]},
      {"id": "cafp", "label": "CAFP 분석", "slide_nos": [3]}
    ], "edges": [
      {"from": "svc", "to": "cafp", "kind": "parent"},
      {"from": "data", "to": "cafp", "kind": "parent"}
    ], "sections": []}
    """
    graph = graph_of(payload)

    assert graph.node("cafp").parent_id == "svc", "첫 부모만 위계로"
    assert len(graph.parent_edges) == 1
    assert [(e.from_id, e.to_id) for e in graph.relates_edges] == [("data", "cafp")]
    # 그래프 뷰에서는 둘 다 이웃이다
    assert {n.id for n in graph.neighbors_of("cafp")} == {"svc", "data"}


def test_parent_cycle_is_broken():
    payload = """
    {"nodes": [{"id": "a", "label": "A", "slide_nos": [1]},
               {"id": "b", "label": "B", "slide_nos": [2]}],
     "edges": [{"from": "a", "to": "b", "kind": "parent"},
               {"from": "b", "to": "a", "kind": "parent"}],
     "sections": []}
    """
    graph = graph_of(payload)

    assert len(graph.roots) >= 1, "순환을 못 끊으면 루트가 하나도 없다"
    for node in graph.nodes:
        assert graph.path_of(node.id), "경로를 못 만들면 순환이 남아 있다"


def test_edges_never_contradict_derived_parent_id():
    """edges 가 진실이고 parent_id 는 파생이다. 둘이 어긋나면 안 된다."""
    graph = graph_of(_WITH_EDGES)
    from_edges = {e.to_id: e.from_id for e in graph.parent_edges}

    for node in graph.nodes:
        assert node.parent_id == from_edges.get(node.id)


# ---------------------------------------------------------------------------
# depth 파생 · 클램프
# ---------------------------------------------------------------------------

_DEEP = """
{"nodes": [
  {"id": "d1", "label": "1층", "slide_nos": [1]},
  {"id": "d2", "label": "2층", "slide_nos": [2]},
  {"id": "d3", "label": "3층", "slide_nos": [3]},
  {"id": "d4", "label": "4층", "slide_nos": [4]},
  {"id": "d5", "label": "5층", "slide_nos": [5]}
], "edges": [
  {"from": "d1", "to": "d2", "kind": "parent"},
  {"from": "d2", "to": "d3", "kind": "parent"},
  {"from": "d3", "to": "d4", "kind": "parent"},
  {"from": "d4", "to": "d5", "kind": "parent"}
], "sections": []}
"""


def test_depth_is_derived_from_parent_edges():
    graph = graph_of(_WITH_EDGES)

    assert graph.node("a").depth == 1
    assert graph.node("b").depth == 2
    assert graph.node("c").depth == 2


def test_model_supplied_depth_is_ignored():
    """모델이 depth 를 적어 보내도 간선에서 다시 센다."""
    payload = """
    {"nodes": [{"id": "a", "label": "A", "depth": 9, "slide_nos": [1]},
               {"id": "b", "label": "B", "depth": 1, "slide_nos": [2]}],
     "edges": [{"from": "a", "to": "b", "kind": "parent"}], "sections": []}
    """
    graph = graph_of(payload)

    assert graph.node("a").depth == 1
    assert graph.node("b").depth == 2


def test_depth_is_clamped_to_max():
    graph = graph_of(_DEEP)

    assert max(n.depth for n in graph.nodes) <= MAX_GRAPH_DEPTH
    assert graph.node("d1").depth == 1, "얕은 쪽은 건드리지 않는다"
    assert graph.node("d2").depth == 2


def test_clamped_graph_still_satisfies_invariants():
    graph = graph_of(_DEEP)

    for node in graph.nodes:
        assert node.depth == len(graph.path_of(node.id))
        assert node.parent_id is None or graph.node(node.parent_id) is not None
    assert len(graph.roots) >= 1


# ---------------------------------------------------------------------------
# weight — 슬라이드 축 우선순위
# ---------------------------------------------------------------------------

def test_weight_is_relative_with_top_concept_at_one():
    graph = graph_of(_WITH_EDGES)

    assert all(0.0 <= n.weight <= 1.0 for n in graph.nodes)
    assert max(n.weight for n in graph.nodes) == 1.0


def test_core_outranks_support():
    payload = """
    {"nodes": [{"id": "core-one", "label": "핵심", "slide_nos": [1]},
               {"id": "sup-one", "label": "보조", "slide_nos": [5]}],
     "edges": [], "sections": []}
    """
    graph = graph_of(payload, doc=make_doc(5))

    assert graph.node("core-one").weight > graph.node("sup-one").weight


def test_by_weight_gives_priority_order():
    graph = graph_of(_WITH_EDGES)
    weights = [n.weight for n in graph.by_weight]

    assert weights == sorted(weights, reverse=True)


def test_weight_basis_is_filled_without_slide_doc():
    graph = graph_of(_WITH_EDGES)
    basis = graph.node("a").weight_basis

    assert basis.slide_count == 1
    assert basis.char_share == 0.0, "slide_doc 없으면 글자 신호를 모른다"
    assert basis.has_visual is False
    assert basis.position == "early"


def test_slide_doc_feeds_char_share_and_visual():
    """밀도 신호가 있으면 글자 많은 장을 근거로 둔 개념이 올라간다."""
    payload = """
    {"nodes": [{"id": "dense", "label": "글자많은장", "slide_nos": [2]},
               {"id": "thin", "label": "글자적은장", "slide_nos": [3]}],
     "edges": [], "sections": []}
    """
    graph = graph_of(payload, doc=make_doc(5), slide_doc=make_slide_doc(5))

    dense = graph.node("dense")
    thin = graph.node("thin")
    assert dense.weight_basis.char_share > thin.weight_basis.char_share
    assert dense.weight_basis.has_visual is True
    assert thin.weight_basis.has_visual is False
    assert dense.weight > thin.weight


def test_position_reflects_first_slide():
    payload = """
    {"nodes": [{"id": "front", "label": "앞", "slide_nos": [1]},
               {"id": "mid", "label": "중간", "slide_nos": [5]},
               {"id": "back", "label": "뒤", "slide_nos": [9]}],
     "edges": [], "sections": []}
    """
    graph = graph_of(payload, doc=make_doc(9))

    assert graph.node("front").weight_basis.position == "early"
    assert graph.node("mid").weight_basis.position == "middle"
    assert graph.node("back").weight_basis.position == "late"


# ---------------------------------------------------------------------------
# 루트 클램프 — 실측에서 루트 13/28 로 평평했다. 상한을 넘으면 붙인다
# ---------------------------------------------------------------------------

# 루트 6개. 무게 서열: a·d(3장·core) > b·c·f(2장·core) > e(1장·support).
# 상한 4개면 a·d 와 (id 순으로) b·c 가 남고 f·e 가 강등된다.
_MANY_ROOTS_BASE = """
    {"nodes": [
      {"id": "a", "label": "가장 큰 개념", "slide_nos": [1, 2, 3]},
      {"id": "b", "label": "둘째 개념", "slide_nos": [1, 2]},
      {"id": "c", "label": "셋째 개념", "slide_nos": [2, 3]},
      {"id": "d", "label": "넷째 개념", "slide_nos": [3, 4, 5]},
      {"id": "e", "label": "막내 개념", "slide_nos": [5]},
      {"id": "f", "label": "다섯째 개념", "slide_nos": [1, 3]}
    ], "edges": [%s], "sections": []}
"""


def test_too_many_roots_are_clamped():
    payload = _MANY_ROOTS_BASE % '{"from": "a", "to": "b", "kind": "relates"}'
    graph = graph_of(payload, doc=make_doc(5))

    assert len(graph.roots) <= MAX_ROOTS
    assert len(graph.parent_edges) >= 2, "강등된 루트는 parent 간선으로 붙는다"


def test_few_roots_are_left_alone():
    graph = graph_of(_NO_EDGES)

    assert len(graph.roots) == 3, "상한 이하면 손대지 않는다"
    assert graph.edges == []


def test_demoted_root_attaches_to_relates_neighbor():
    """강등된 루트에 relates 이웃이 있으면 남의 밑이 아니라 그 이웃 밑으로 간다."""
    payload = _MANY_ROOTS_BASE % '{"from": "e", "to": "b", "kind": "relates"}'
    graph = graph_of(payload, doc=make_doc(5))

    assert graph.node("e").parent_id == "b"
    assert graph.node("e").depth == 2
    # relates 간선은 정보 보존을 위해 그대로 남는다
    assert ("e", "b") in [(x.from_id, x.to_id) for x in graph.relates_edges]


def test_demoted_root_attaches_by_slide_overlap():
    """relates 이웃이 없으면 슬라이드가 겹치는 루트 밑으로 간다. e[5] ∩ d[4,5] = {5}."""
    payload = _MANY_ROOTS_BASE % '{"from": "a", "to": "b", "kind": "relates"}'
    graph = graph_of(payload, doc=make_doc(5))

    assert graph.node("e").parent_id == "d"


def test_flat_graph_after_failed_retry_is_still_clamped():
    """재시도까지 평평하게 오면(전부 루트) 후처리가 위계를 만들어 계약을 지킨다."""
    payload = _MANY_ROOTS_BASE % ""
    engine = SequenceLLM(payload, payload)
    graph = build_graph(make_doc(5), llm=engine)

    assert engine.calls == 2
    assert len(graph.roots) <= MAX_ROOTS
    assert len(graph.parent_edges) >= 2


def test_root_clamp_does_not_duplicate_edge_pairs():
    """relates 가 b→e 방향으로 있을 때 e 를 b 밑에 붙이면 (b,e) 쌍이 겹치면 안 된다.

    실측(Solar·RINGLE)에서 잡힌 회귀: parent 간선을 새로 만들 때 같은 방향
    relates 가 남아 (from,to) 중복 불변식이 깨졌다.
    """
    payload = _MANY_ROOTS_BASE % '{"from": "b", "to": "e", "kind": "relates"}'
    graph = graph_of(payload, doc=make_doc(5))
    pairs = [(x.from_id, x.to_id) for x in graph.edges]

    assert graph.node("e").parent_id == "b"
    assert len(pairs) == len(set(pairs)), "같은 (from,to) 는 한 번만"


def test_root_clamp_keeps_all_invariants():
    payload = _MANY_ROOTS_BASE % '{"from": "e", "to": "b", "kind": "relates"}'
    graph = graph_of(payload, doc=make_doc(5))
    derived = {e.to_id: e.from_id for e in graph.parent_edges}

    assert max(n.weight for n in graph.nodes) == 1.0, "클램프 후에도 weight 재정규화"
    for node in graph.nodes:
        assert node.parent_id == derived.get(node.id), "parent_id 는 edges 파생"
        assert node.depth == len(graph.path_of(node.id))
        assert node.depth <= MAX_GRAPH_DEPTH


# ---------------------------------------------------------------------------
# weight 동률 해소 — slide_nos 가 같아도 개념 단위 신호로 서열이 갈린다
# ---------------------------------------------------------------------------

def make_mention_doc() -> ConceptDoc:
    """'피보팅' 이 세 번 언급되는 문서. 다른 개념은 한 번씩만 나온다."""
    return ConceptDoc(
        file_name="mention.pdf",
        total_slides=2,
        model="mock",
        slides=[
            SlideConcepts(
                slide_no=1,
                title="타겟 피보팅",
                topic="전략",
                keywords=["피보팅"],
                concepts=["타겟 피보팅 전략: 직군 중심으로 전환", "구매력: 지불 의사"],
                importance="core",
            ),
            SlideConcepts(
                slide_no=2,
                title="근거",
                topic="근거",
                keywords=[],
                concepts=["피보팅 근거: 실측 데이터"],
                importance="core",
            ),
        ],
    )


_TIE_NODES = """
{"nodes": [
  {"id": "pivot", "label": "피보팅", "slide_nos": [1, 2]},
  {"id": "buy", "label": "구매력", "slide_nos": [1, 2]}
], "edges": [{"from": "pivot", "to": "buy", "kind": "relates"}], "sections": []}
"""


def test_mention_frequency_breaks_weight_tie():
    """slide_nos 가 같으면 예전엔 무조건 동률이었다. 언급 빈도가 서열을 가른다."""
    graph = graph_of(_TIE_NODES, doc=make_mention_doc())
    pivot = graph.node("pivot")
    buy = graph.node("buy")

    assert pivot.weight_basis.mention_count >= 3
    assert buy.weight_basis.mention_count == 1
    assert pivot.weight > buy.weight


def test_title_hit_is_recorded_and_boosts_weight():
    payload = """
    {"nodes": [
      {"id": "pivot", "label": "피보팅", "slide_nos": [1]},
      {"id": "etc", "label": "기타 개념", "slide_nos": [1]}
    ], "edges": [{"from": "pivot", "to": "etc", "kind": "relates"}], "sections": []}
    """
    graph = graph_of(payload, doc=make_mention_doc())

    assert graph.node("pivot").weight_basis.title_hit is True
    assert graph.node("etc").weight_basis.title_hit is False
    assert graph.node("pivot").weight > graph.node("etc").weight


def test_latin_label_needs_token_boundary():
    """'AI' 가 'Detail'·'Container' 안의 부분 문자열로 걸리면 안 된다 (리뷰에서 잡힌 오탐).

    영문·숫자는 토큰 단위로 정확히 일치해야 언급으로 친다.
    한글 합성어(피보팅근거)는 붙여 쓰므로 포함 일치를 유지한다.
    """
    doc = ConceptDoc(
        file_name="ai.pdf",
        total_slides=1,
        model="mock",
        slides=[
            SlideConcepts(
                slide_no=1,
                title="Detail 페이지",
                topic="개선",
                keywords=["Container 배포 자동화"],
                concepts=["Detail 페이지 개선: 이탈 감소", "AI 기반 추천: 개인화"],
                importance="core",
            ),
        ],
    )
    payload = """
    {"nodes": [
      {"id": "ai", "label": "AI", "slide_nos": [1]},
      {"id": "detail", "label": "Detail 페이지", "slide_nos": [1]}
    ], "edges": [{"from": "ai", "to": "detail", "kind": "relates"}], "sections": []}
    """
    graph = graph_of(payload, doc=doc)

    assert graph.node("ai").weight_basis.mention_count == 1, "'AI 기반 추천' 만 언급이다"
    assert graph.node("ai").weight_basis.title_hit is False, "'Detail 페이지' 제목에 AI 없음"
    assert graph.node("detail").weight_basis.mention_count == 1
    assert graph.node("detail").weight_basis.title_hit is True


def test_hangul_compound_still_matches_by_containment():
    """한글은 붙여 쓴 합성어가 흔하다 — '피보팅' 은 '피보팅근거' 에 걸려야 한다."""
    doc = ConceptDoc(
        file_name="compound.pdf",
        total_slides=1,
        model="mock",
        slides=[
            SlideConcepts(
                slide_no=1,
                title="전략",
                topic="전략",
                keywords=["피보팅근거"],
                concepts=[],
                importance="core",
            ),
        ],
    )
    payload = """
    {"nodes": [{"id": "pivot", "label": "피보팅", "slide_nos": [1]}],
     "edges": [], "sections": []}
    """
    graph = graph_of(payload, doc=doc)

    assert graph.node("pivot").weight_basis.mention_count == 1


def test_weight_basis_new_fields_roundtrip():
    graph = graph_of(_TIE_NODES, doc=make_mention_doc())
    basis = graph.node("pivot").weight_basis
    again = type(basis).from_dict(basis.to_dict())

    assert again == basis
    assert again.mention_count == basis.mention_count
    assert again.title_hit is basis.title_hit


# ---------------------------------------------------------------------------
# 퇴화 감지 재시도 — 실제 Solar 가 간선 0개를 뱉는 실행이 있었다
# ---------------------------------------------------------------------------

def test_no_edges_triggers_one_retry_and_uses_it():
    engine = SequenceLLM(_NO_EDGES, _WITH_EDGES)
    graph = build_graph(make_doc(), llm=engine)

    assert engine.calls == 2, "간선 0개인데 재시도하지 않았다"
    assert graph.node("b").parent_id == "a"


def test_retry_also_without_edges_keeps_first_result():
    """재시도도 간선이 없으면 1차 결과를 쓴다. 실패로 만들지 않는다."""
    engine = SequenceLLM(_NO_EDGES, _NO_EDGES)
    graph = build_graph(make_doc(), llm=engine)

    assert engine.calls == 2
    assert len(graph.nodes) == 3
    assert graph.edges == []


def test_good_result_does_not_retry():
    engine = SequenceLLM(_WITH_EDGES)
    build_graph(make_doc(), llm=engine)

    assert engine.calls == 1, "멀쩡한 그래프인데 돈을 두 번 썼다"


def test_single_node_without_edges_is_not_degenerate():
    engine = SequenceLLM(
        '{"nodes": [{"id": "solo", "label": "혼자", "slide_nos": [1]}],'
        ' "edges": [], "sections": []}'
    )
    build_graph(make_doc(), llm=engine)

    assert engine.calls == 1


def test_broken_retry_falls_back_to_first_result():
    """재시도가 파싱 실패로 터져도 1차 결과를 살린다."""
    engine = SequenceLLM(_NO_EDGES, "JSON 아님")
    graph = build_graph(make_doc(), llm=engine)

    assert engine.calls == 2
    assert len(graph.nodes) == 3


# ---------------------------------------------------------------------------
# 조회 헬퍼 (F-08~10 이 쓸 표면)
# ---------------------------------------------------------------------------

def test_path_of_gives_root_to_leaf_labels():
    graph = graph_of(_WITH_EDGES)

    assert [n.label for n in graph.path_of("b")] == ["A", "B"]
    assert graph.path_of("없는id") == []


def test_children_and_roots():
    graph = graph_of(_WITH_EDGES)

    assert [n.id for n in graph.roots] == ["a"]
    assert {n.id for n in graph.children_of("a")} == {"b", "c"}


def test_edges_from_and_to():
    graph = graph_of(_WITH_EDGES)

    assert {e.to_id for e in graph.edges_from("a")} == {"b", "c"}
    assert [e.from_id for e in graph.edges_to("b")] == ["a"]


def test_lookup_by_slide_and_section():
    payload = """
    {"nodes": [{"id": "a", "label": "A", "slide_nos": [2, 3]}],
     "edges": [],
     "sections": [{"name": "서론", "slide_role": "intro", "slide_nos": [1, 2]}]}
    """
    graph = graph_of(payload)

    assert [n.id for n in graph.nodes_for_slide(2)] == ["a"]
    assert graph.nodes_for_slide(5) == []
    assert graph.section_of(1).name == "서론"
    assert graph.section_of(5) is None


# ---------------------------------------------------------------------------
# 실패 처리
# ---------------------------------------------------------------------------

def test_unparseable_llm_output_raises_graph_error():
    with pytest.raises(GraphError):
        graph_of("이건 JSON 이 아니라 그냥 말입니다")


def test_unparseable_first_response_retries_once_and_uses_it():
    """실측(Solar·RINGLE)에서 복구 불가능한 JSON 이 한 번씩 온다. 한 번은 다시 묻는다."""
    engine = SequenceLLM("깨진 응답 {no json", _WITH_EDGES)
    graph = build_graph(make_doc(), llm=engine)

    assert engine.calls == 2
    assert graph.node("b").parent_id == "a"


def test_unparseable_twice_raises_after_two_calls():
    """재요청도 깨지면 실패다. 무한히 다시 묻지 않는다."""
    engine = SequenceLLM("깨진 응답 1", "깨진 응답 2")
    with pytest.raises(GraphError):
        build_graph(make_doc(), llm=engine)

    assert engine.calls == 2


def test_empty_concept_doc_raises_graph_error():
    with pytest.raises(GraphError):
        build_graph(ConceptDoc(file_name="empty.pdf", total_slides=0, slides=[]), llm="mock")


def test_json_wrapped_in_code_fence_is_recovered():
    payload = """```json
    {"nodes": [{"id": "a", "label": "A", "slide_nos": [1]},
               {"id": "b", "label": "B", "slide_nos": [2]}],
     "edges": [{"from": "a", "to": "b", "kind": "parent"}],
     "sections": [{"name": "서론", "slide_role": "intro", "slide_nos": [1]}]}
    ```"""
    graph = graph_of(payload)

    assert graph.node("b").parent_id == "a"
