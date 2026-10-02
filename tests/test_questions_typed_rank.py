"""
층 그래프(F-07 종류 있는 길)의 질문 후보 순서 — 깊이 대신 자료 반복도, 개념·주장 교차, 재정렬이 그 순서를 지킨다 (2026-10-02).
옛 실패: 핵심 주장 바로 밑 잎 개념(차트 범례 「시장지수」 「적립식」)이 핵심 요인과 같은 깊이라 weight 순으로 후보 창을 채웠고,
기둥 주장(「…사전에 정해둔 규칙이었다」)은 후보에도 없었다. 후보 순서를 고쳐도 `_rerank` 가 옛 키(깊이 → severity)로 되돌렸다.
"""
from chuckchuck import f08_questions as F8
from chuckchuck.contracts import ConceptGraph, ConceptNode, ConceptEdge, Section, TriageMark


def _n(i, label, kind, parent, slides, w=0.5):
    return ConceptNode(id=i, label=label, kind=kind, parent_id=parent, slide_nos=slides, weight=w, summary="s",
                       depth=1 if parent is None else 2)


def graph():
    nodes = [
        _n("t", "실력이 아니라 행동의 문제다", "thesis", None, [1]),
        _n("leaf", "시장지수", "concept", "t", [3], w=0.99),           # 차트 범례 — weight 는 높다
        _n("turn", "회전율", "concept", "t", [2, 6], w=0.6),
        _n("rule", "상위 그룹을 가른 것은 사전에 정해둔 규칙이었다", "claim", "t", [11], w=0.2),
        _n("over", "과잉 매매", "concept", "t", [5], w=0.5),
        _n("c6", "과잉 매매 — 거래를 늘릴수록 성과가 낮아졌다", "claim", "over", [6], w=0.3),
    ]
    for n in nodes:
        if n.parent_id == "over":
            n.depth = 3
    edges = [ConceptEdge(from_id=n.parent_id, to_id=n.id, kind="parent") for n in nodes if n.parent_id]
    return ConceptGraph(file_name="d", total_slides=14, nodes=nodes, edges=edges,
                        sections=[Section(name="본론", slide_role="body", slide_nos=list(range(1, 15)))])


SLIDES = {1: "실력이 아니라 행동의 문제다", 2: "매매 회전율은 수익률과 역상관", 3: "시장지수 9 기관 8",
          5: "과잉 매매 타이밍 실패", 6: "과잉 매매 — 거래를 늘릴수록 성과가 낮아졌다 회전율 구간",
          11: "상위 그룹을 구분한 것은 판단력이 아니라 사전에 정해둔 규칙이었다 회전율",
          13: "회전율은 가장 강한 역상관 변수", 14: "상하위 그룹을 가른 것은 사전에 정해둔 규칙"}


def test_repeated_concepts_beat_heavy_leaf_and_claims_interleave():
    order = [n.id for n, _ in F8._ordered_candidates(graph(), None, None, slides=SLIDES)]
    assert order[0] == "t"
    assert order.index("turn") < order.index("leaf")             # 4장에서 되풀이된 「회전율」 > weight 만 큰 차트 범례
    assert order.index("over") < order.index("leaf")             # 자식(상세 장)을 거느린 개념 > 잎
    assert order[2] in ("rule", "c6")                            # 개념 다음엔 주장 — 후보 창이 개념으로만 차지 않는다


def test_rerank_keeps_candidate_order_on_typed_graph():
    g = graph()
    pairs = F8._ordered_candidates(g, None, None, slides=SLIDES)
    marks = [TriageMark(node_id=n.id, severity=1 if n.id == "leaf" else 3, trap=False, angle="", source=src, rank=0,
                        doc_weight=n.weight) for n, src in pairs]
    out = [m.node_id for m in F8._rerank(marks, pairs, g)]
    assert out[:2] == ["t", "turn"]                              # LLM 이 잎에 「치명」 을 줘도 자료 구조 순서가 이긴다
    assert out.index("leaf") > out.index("over")
    assert out[-1] == "c6"                                       # 「과잉 매매」 를 물었으면 그 이름을 품은 주장은 맨 뒤 (같은 개념 두 번 X)


def test_same_name_nodes_do_not_take_two_slots():
    marks = [TriageMark(node_id=i, severity=2, trap=False, angle="", source="core_weight", rank=0, doc_weight=0.5)
             for i in ("a", "b", "c")]
    labels = {"a": "통제 가능한 변수", "b": "통제 가능한 변수부터", "c": "매도 규칙"}
    assert [m.node_id for m in F8._spread_same_name(marks, labels)] == ["a", "c", "b"]


def test_root_children_are_not_one_chunk_on_typed_graph():
    g = graph()
    marks = [TriageMark(node_id=i, severity=2, trap=False, angle="", source="core_weight", rank=0, doc_weight=0.5)
             for i in ("turn", "rule", "over")]
    out = [m.node_id for m in F8._spread_adjacent(marks, g)]
    assert out == ["turn", "rule", "over"]                       # 핵심 주장 밑 형제는 발표의 갈래 — 서로 밀어내지 않는다
