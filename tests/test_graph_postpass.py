"""
F-07 후처리(`_graph_items` + f07 `_add_items`·겹친 이름 합치기)와 F-26 `_resolve_id` 이름 풀기 테스트.

여러 분야의 가상 덱으로 본다 — 특정 발표의 낱말이 규칙에 박혀 있으면 다른 분야에서 깨진다.
LLM 은 전부 가짜라 네트워크·키가 필요 없다.
"""

import json

import pytest

from chuckchuck import _graph_items as GI
from chuckchuck.contracts import (
    ConceptDoc,
    ConceptGraph,
    ConceptNode,
    Slide,
    SlideBlock,
    SlideConcepts,
    SlideDoc,
)
from chuckchuck.f07_graph import MAX_GRAPH_DEPTH, build_graph
from chuckchuck.f26_claims import _resolve_id, build_claims
from chuckchuck.providers.llm_base import LLMProvider


@pytest.fixture(autouse=True)
def _no_links_backfill(monkeypatch):
    from chuckchuck import f07_graph
    monkeypatch.setattr(f07_graph, "MIN_CROSS_RATIO", 0.0)


class Scripted(LLMProvider):
    name = "scripted"

    def __init__(self, payload: dict):
        self.payload = json.dumps(payload, ensure_ascii=False)

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False) -> str:
        return self.payload


def _docs(texts: dict[int, str]) -> tuple[ConceptDoc, SlideDoc]:
    n = max(texts)
    cd = ConceptDoc(file_name="d.pptx", total_slides=n, model="mock", slides=[
        SlideConcepts(slide_no=i, title="", topic="", keywords=[], concepts=[f"개념{i}: 설명"], raw_text=texts.get(i, ""),
                      importance="core") for i in range(1, n + 1)])
    sd = SlideDoc(file_name="d.pptx", total_slides=n, slides=[
        Slide(slide_no=i, title="", blocks=[SlideBlock(category="paragraph", text=line)
                                            for line in texts.get(i, "").split("\n") if line],
              total_char_count=len(texts.get(i, "")))
        for i in range(1, n + 1)])
    return cd, sd


def _node(i, label, slides, parent=None):
    return {"id": i, "label": label, "slide_nos": slides, "summary": "", "importance": "core", "parent": parent}


# ---------------------------------------------------------------------------
# 자료 줄 → 식·목록 묶음
# ---------------------------------------------------------------------------

def test_formula_split_across_boxes_skips_caption_questions():
    """식 조각 사이에 도식 캡션(물음 줄)이 끼어도 마지막 항까지 잇는다."""
    raw = "생산성 = 가동률 ×\n얼마나 돌았는가\n수율 ×\n품질 지수 얼마나\n좋았는가"
    lines = GI.deck_lines(raw)
    assert lines[0] == "생산성 = 가동률 × 수율 × 품질 지수 얼마나"
    groups = GI.item_groups([(3, raw)])
    assert [(g.kind, g.head, g.items) for g in groups] == [("formula", "생산성", ["가동률", "수율", "품질 지수"])]


def test_formula_with_operator_only_lines():
    raw = "고객 가치 =\n편익\n÷\n비용"
    assert GI.item_groups([(1, raw)])[0].items == ["편익", "비용"]


def test_list_heading_with_count_needs_matching_item_count():
    ok = "배포를 막는 세 가지 병목\n느린 빌드\n불안정한 테스트\n수동 승인"
    bad = "배포를 막는 세 가지 병목\n느린 빌드\n불안정한 테스트"
    assert GI.item_groups([(2, ok)])[0].items == ["느린 빌드", "불안정한 테스트", "수동 승인"]
    assert GI.item_groups([(2, bad)]) == []


def test_table_first_cells_are_items_but_column_header_row_is_not():
    """표 첫 칸은 항목이다. 다만 머리 행이 열 이름(아래 행에만 숫자)이면 뺀다."""
    items_table = "민원이 느는 원인\n| 소음 | 야간 공사 |\n| --- | --- |\n| 주차 | 방문 차량 |\n| 악취 | 음식물 |"
    assert GI.item_groups([(4, items_table)])[0].items == ["소음", "주차", "악취"]
    data_table = "사업 성과 두 가지\n| 지표 | 전 | 후 |\n| --- | --- | --- |\n| 처리 시간 | 5일 | 2일 |\n| 재방문율 | 30% | 12% |"
    assert GI.item_groups([(4, data_table)])[0].items == ["처리 시간", "재방문율"]


def test_items_that_are_sentences_numbers_or_questions_end_the_list():
    raw = "실패하는 이유\n“왜 그만두셨나요?”\n1시간 미만"
    assert GI.item_groups([(1, raw)]) == []


def test_clause_items_and_two_item_notes_are_not_lists():
    """명사형 서술 절(「…항목은 없음」)은 이름이 아니고, 개수 말 없는 둘짜리 목록은 메모 상자와 구별이 안 된다."""
    assert GI.item_groups([(5, "결국 속도의 문제\n해당하는 사례를 찾는 항목은 없음\n요인 간 상호작용 존재")]) == []
    assert GI.item_groups([(5, "창고가 막히는 원인\n좁은 통로\n낡은 선반\n잦은 반품")])[0].items == ["좁은 통로", "낡은 선반", "잦은 반품"]


def test_interleaved_column_layout_with_wrong_count_is_skipped():
    raw = "좋은 팀의 세 가지 조건\n명확한 목표\n신뢰\n서로 아는 목표\n빠른 피드백\n실수를 말할 수 있음\n짧은 주기"
    assert GI.item_groups([(2, raw)]) == []


# ---------------------------------------------------------------------------
# 이름 대조
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("item,labels,expected", [
    ("가동률", ["가동률 저하"], True),                 # 수식어만 다르다
    ("낡은 결제 시스템", ["결제 시스템"], True),       # 노드 이름 + 앞 수식어
    ("단가", ["평균 단가"], True),                     # 이름이 낱말 하나 더
    ("병원 방문 감소", ["병원"], False),               # 절반도 못 덮는다 — 다른 개념
    ("수율", ["품질 지수"], False),
    ("탄소의 배출", ["탄소 배출"], True),              # 조사 「의」
])
def test_item_present(item, labels, expected):
    assert GI.item_present(item, labels) is expected


def test_same_label_ignores_spacing_and_genitive_but_not_polarity():
    assert GI.same_label("온라인예약", "온라인 예약")
    assert GI.same_label("고객의 만족", "고객 만족")
    assert not GI.same_label("회의", "회")                      # 두 글자 낱말 끝 「의」 는 조사가 아닐 수 있다
    assert not GI.same_label("협업", "협업 부족")


def test_romanized_slug_ids_are_stable_ascii_and_unique():
    used = {"gadongryul"}
    assert GI.romanize("가동률") == "gadongryul"
    assert GI.slug_id("가동률", used) == "gadongryul-2"
    assert GI.slug_id("CPU 사용률", set()) == "cpu-sayongryul"


# ---------------------------------------------------------------------------
# f07 — 겹친 이름 합치기(B)
# ---------------------------------------------------------------------------

def test_repetition_loop_collapses_to_one_node():
    cd, sd = _docs({1: "표지", 2: "본문", 3: "본문"})
    nodes = [_node("root", "물류 혁신", [1]), _node("hub", "거점 통합", [2], "root")]
    nodes += [_node(f"hub-{k}", "거점 통합", [3], "root") for k in range(40)]
    g = build_graph(cd, slide_doc=sd, llm=Scripted({"thesis": "root", "nodes": nodes, "edges": []}))
    assert [n.label for n in g.nodes] == ["물류 혁신", "거점 통합"]
    assert g.nodes[1].slide_nos == [2, 3]


def test_merged_node_children_and_edges_move_to_survivor():
    cd, sd = _docs({1: "a", 2: "b", 3: "c", 4: "d"})
    nodes = [_node("t", "학습 성과", [1]), _node("m", "수업 몰입", [2], "t"), _node("m2", "수업의 몰입", [3], "t"),
             _node("c", "질문 빈도", [4], "m2")]
    g = build_graph(cd, slide_doc=sd, llm=Scripted({"thesis": "t", "nodes": nodes, "edges": []}))
    by = {n.label: n for n in g.nodes}
    assert "수업의 몰입" not in by
    assert by["질문 빈도"].parent_id == by["수업 몰입"].id
    assert by["수업 몰입"].slide_nos == [2, 3]


def test_node_cap_after_dedupe(monkeypatch):
    monkeypatch.setattr(GI, "MAX_NODES", 5)
    cd, sd = _docs({1: "a"})
    nodes = [_node("r", "주제", [1])] + [_node(f"n{k}", f"개념 {chr(0xAC00 + k)}", [1], "r") for k in range(12)]
    g = build_graph(cd, slide_doc=sd, llm=Scripted({"thesis": "r", "nodes": nodes, "edges": []}))
    assert len(g.nodes) == 5


# ---------------------------------------------------------------------------
# f07 — 식·목록 항목 메우기(A)
# ---------------------------------------------------------------------------

_FACTORY = {
    1: "설비 효율이 원가보다 중요합니다",
    2: "설비 효율 = 가동률 × 수율 × 속도 지수",
    3: "공장을 멈추는 세 가지 문제\n잦은 고장\n부품 부족\n숙련 인력 이탈",
}


def _factory_graph():
    cd, sd = _docs(_FACTORY)
    nodes = [_node("oee", "설비 효율", [1, 2]), _node("rate", "가동률", [2], "oee"),
             _node("fault", "잦은 고장", [3], "oee"), _node("parts", "부품 부족", [3], "oee")]
    return build_graph(cd, slide_doc=sd, llm=Scripted({"thesis": "oee", "nodes": nodes, "edges": []})), cd, sd


def test_missing_formula_terms_become_children_of_lhs_node():
    g, _, _ = _factory_graph()
    by = {n.label: n for n in g.nodes}
    assert {"수율", "속도 지수"} <= set(by)
    assert by["수율"].parent_id == by["설비 효율"].id
    assert by["수율"].slide_nos == [2] and by["수율"].summary.startswith("설비 효율 =")
    assert all(n.id.isascii() for n in g.nodes)


def test_missing_list_item_joins_its_present_siblings():
    g, _, _ = _factory_graph()
    by = {n.label: n for n in g.nodes}
    assert by["숙련 인력 이탈"].parent_id == by["잦은 고장"].parent_id


def test_added_nodes_keep_invariants_and_llm_weights():
    g, _, _ = _factory_graph()
    ids = {n.id for n in g.nodes}
    parents = {e.to_id: e.from_id for e in g.edges if e.kind == "parent"}
    for n in g.nodes:
        assert n.parent_id == parents.get(n.id)
        assert 1 <= n.depth <= MAX_GRAPH_DEPTH
        assert 0.0 <= n.weight <= 1.0
    assert all(e.from_id in ids and e.to_id in ids for e in g.edges)
    assert max(n.weight for n in g.nodes if n.label == "설비 효율") == 1.0


def test_unresolved_formula_lhs_is_added_under_the_thesis():
    cd, sd = _docs({1: "도시 재생", 2: "상권 활력 = 유동 인구 × 체류 시간"})
    nodes = [_node("t", "도시 재생", [1]), _node("x", "골목 상점", [2], "t")]
    g = build_graph(cd, slide_doc=sd, llm=Scripted({"thesis": "t", "nodes": nodes, "edges": []}))
    by = {n.label: n for n in g.nodes}
    assert by["상권 활력"].parent_id == "t"
    assert by["유동 인구"].parent_id == by["상권 활력"].id


def test_added_node_cap_skips_whole_groups(monkeypatch):
    from chuckchuck import _graph_items
    monkeypatch.setattr(_graph_items, "MAX_ADDED", 1)
    g, _, _ = _factory_graph()
    labels = {n.label for n in g.nodes}
    assert "숙련 인력 이탈" in labels            # 1개짜리 묶음은 들어간다
    assert not ({"수율", "속도 지수"} & labels)   # 2개가 모자란 식은 통째로 건너뛴다


def test_without_slide_doc_nothing_is_added():
    cd, _ = _docs(_FACTORY)
    nodes = [_node("oee", "설비 효율", [1, 2])]
    g = build_graph(cd, llm=Scripted({"thesis": "oee", "nodes": nodes, "edges": []}))
    assert [n.label for n in g.nodes] == ["설비 효율"]


def test_added_terms_let_rule_claims_find_the_formula_tension():
    """식 항이 노드가 되면 규칙 주장이 compose 를 적고, 앞 장 비교와 같은 id 로 만난다 (긴장 탐침 재료)."""
    g, _, sd = _factory_graph()
    claims = build_claims(g, sd, llm="none").claims
    compose = [c for c in claims if c.kind == "compose" and c.evidence[0].slide_no == 2]
    assert compose and len(compose[0].object_ids) == 3


# ---------------------------------------------------------------------------
# F-26 _resolve_id (D)
# ---------------------------------------------------------------------------

def _nodes():
    return [ConceptNode(id="n1", label="배송비", slide_nos=[2]), ConceptNode(id="n2", label="재구매율", slide_nos=[3]),
            ConceptNode(id="n3", label="고객 이탈", slide_nos=[3])]


def test_resolve_id_accepts_label_phrases_by_distinctive_tokens():
    nodes = _nodes()
    ids, by_label = {n.id for n in nodes}, {n.label: n.id for n in nodes}
    assert _resolve_id("n1", ids, by_label, nodes) == "n1"
    assert _resolve_id("높은 배송비", ids, by_label, nodes) == "n1"
    assert _resolve_id("신규 고객 이탈", ids, by_label, nodes) == "n3"
    assert _resolve_id("품질 관리", ids, by_label, nodes) == ""


def test_resolve_id_refuses_whole_sentences_and_keeps_old_signature():
    nodes = _nodes()
    ids, by_label = {n.id for n in nodes}, {n.label: n.id for n in nodes}
    assert _resolve_id("배송비를 줄이면 고객 이탈이 반드시 줄어듭니다", ids, by_label, nodes) == ""
    assert _resolve_id("높은 배송비", ids, by_label) == ""       # nodes 없이 부르면 예전처럼 통째 일치만


def test_graph_payload_roundtrips_through_contract():
    g, _, _ = _factory_graph()
    again = ConceptGraph.from_dict(g.to_dict())
    assert [n.id for n in again.nodes] == [n.id for n in g.nodes]


def test_thesis_written_as_a_label_is_resolved_to_its_node():
    """thesis 칸에 id 대신 이름이 와도 주제 노드를 찾아 루트로 지킨다."""
    cd, sd = _docs({1: "a", 2: "b", 3: "c", 4: "d", 5: "e"})
    # 주제는 자식이 없는 짧은 표지 개념이고, 자식을 거느린 루트가 넷 더 있다 — 주제를 모르면 클램프가 주제를 강등한다
    nodes = [_node("core", "고객 신뢰 회복", [1])]
    for k, (a, b) in enumerate([("응답 속도", "대기 시간"), ("환불 정책", "환불 기간"), ("상담 품질", "상담 교육"),
                                ("재방문", "재방문 주기")], start=2):
        nodes += [_node(f"r{k}", a, [k]), _node(f"c{k}", b, [k], f"r{k}")]
    payload = {"nodes": nodes, "edges": []}
    lost = build_graph(cd, slide_doc=sd, llm=Scripted({**payload, "thesis": "없는 이름"}))
    kept = build_graph(cd, slide_doc=sd, llm=Scripted({**payload, "thesis": "고객 신뢰"}))
    assert {n.id: n for n in lost.nodes}["core"].parent_id is not None
    assert {n.id: n for n in kept.nodes}["core"].parent_id is None


def test_thesis_label_matching_nothing_stays_unresolved():
    from chuckchuck.f07_graph import _thesis_by_label
    nodes = [ConceptNode(id="a", label="응답 속도"), ConceptNode(id="b", label="환불 정책")]
    assert _thesis_by_label("탄소 중립 전환", nodes, {}) is None
    assert _thesis_by_label("환불 정책", nodes, {}) == "b"
