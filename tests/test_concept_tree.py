"""
F-07 개념 트리(build_tree)가 계약 불변식을 지키는지 검사하는 테스트입니다.
SCHEMA.md 6-B 의 '보증' 6가지가 여기 그대로 대응됩니다.
"""

import pytest

from chuckchuck.contracts import (
    ConceptDoc,
    ConceptTree,
    SLIDE_ROLES,
    SlideConcepts,
    TreeError,
)
from chuckchuck.f07_tree import build_tree
from chuckchuck.providers.llm_base import LLMProvider


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def make_doc(n_slides: int = 5) -> ConceptDoc:
    """작은 ConceptDoc 하나."""
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


class ScriptedLLM(LLMProvider):
    """정해 둔 문자열만 돌려주는 가짜 LLM. 후처리 로직만 시험한다."""

    name = "scripted"

    def __init__(self, payload: str):
        self.payload = payload

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096) -> str:
        return self.payload


# ---------------------------------------------------------------------------
# mock 파이프라인
# ---------------------------------------------------------------------------

def test_build_tree_mock_runs_without_api_key():
    """키 없이 mock 만으로 F-07 파이프라인이 돈다."""
    tree = build_tree(make_doc(), llm="mock")

    assert isinstance(tree, ConceptTree)
    assert tree.model == "mock"
    assert tree.file_name == "sample.pdf"
    assert tree.total_slides == 5
    assert tree.nodes, "mock 이 노드를 하나도 못 만들면 파이프라인 검증이 안 된다"
    assert tree.sections


def test_accepts_dict_input():
    """dict 로 들어와도 입구에서 from_dict 한다 (프론트 JSON 직결)."""
    tree = build_tree(make_doc().to_dict(), llm="mock")
    assert tree.total_slides == 5


def test_roundtrip_to_dict_from_dict():
    """ours 타입은 to_dict / from_dict 왕복이 가능해야 한다."""
    tree = build_tree(make_doc(), llm="mock")
    again = ConceptTree.from_dict(tree.to_dict())

    assert again.to_dict() == tree.to_dict()


# ---------------------------------------------------------------------------
# 불변식 1·2 — id 유일 / parent_id 는 존재하는 id 나 None
# ---------------------------------------------------------------------------

def test_duplicate_ids_are_made_unique():
    payload = """
    {"nodes": [
      {"id": "a", "label": "첫째", "parent_id": null, "slide_nos": [1]},
      {"id": "a", "label": "둘째", "parent_id": null, "slide_nos": [2]}
    ], "sections": []}
    """
    tree = build_tree(make_doc(), llm=ScriptedLLM(payload))

    ids = [n.id for n in tree.nodes]
    assert len(ids) == len(set(ids)) == 2
    assert {n.label for n in tree.nodes} == {"첫째", "둘째"}


def test_dangling_parent_becomes_root():
    payload = """
    {"nodes": [
      {"id": "child", "label": "고아", "parent_id": "없는놈", "slide_nos": [1]}
    ], "sections": []}
    """
    tree = build_tree(make_doc(), llm=ScriptedLLM(payload))

    node = tree.node("child")
    assert node is not None
    assert node.parent_id is None
    assert node.depth == 1


# ---------------------------------------------------------------------------
# 불변식 3·4 — 순환 없음 / depth = 체인 길이
# ---------------------------------------------------------------------------

def test_cycle_is_broken():
    """a → b → a 순환이 오면 고리를 끊어 루트를 만든다."""
    payload = """
    {"nodes": [
      {"id": "a", "label": "A", "parent_id": "b", "slide_nos": [1]},
      {"id": "b", "label": "B", "parent_id": "a", "slide_nos": [2]}
    ], "sections": []}
    """
    tree = build_tree(make_doc(), llm=ScriptedLLM(payload))

    assert len(tree.roots) >= 1, "순환을 못 끊으면 루트가 하나도 없다"
    for node in tree.nodes:
        assert tree.path_of(node.id), "경로를 못 만들면 순환이 남아 있다"


def test_depth_is_recomputed_from_parent_chain():
    """모델이 준 depth 는 무시하고 parent_id 체인으로 다시 센다."""
    payload = """
    {"nodes": [
      {"id": "root", "label": "루트", "depth": 9, "parent_id": null, "slide_nos": [1]},
      {"id": "mid", "label": "중간", "depth": 1, "parent_id": "root", "slide_nos": [2]},
      {"id": "leaf", "label": "잎", "depth": 7, "parent_id": "mid", "slide_nos": [3]}
    ], "sections": []}
    """
    tree = build_tree(make_doc(), llm=ScriptedLLM(payload))

    assert tree.node("root").depth == 1
    assert tree.node("mid").depth == 2
    assert tree.node("leaf").depth == 3


# ---------------------------------------------------------------------------
# 불변식 5·6 — slide_nos 범위 / slide_role enum
# ---------------------------------------------------------------------------

def test_out_of_range_slide_nos_are_dropped():
    payload = """
    {"nodes": [
      {"id": "a", "label": "A", "parent_id": null, "slide_nos": [0, 2, 99, 3]}
    ], "sections": [
      {"name": "본론", "slide_role": "body", "slide_nos": [2, 3, 400]}
    ]}
    """
    tree = build_tree(make_doc(n_slides=5), llm=ScriptedLLM(payload))

    assert tree.node("a").slide_nos == [2, 3]
    assert tree.sections[0].slide_nos == [2, 3]


def test_unknown_slide_role_falls_back_to_body():
    payload = """
    {"nodes": [], "sections": [
      {"name": "이상한 구획", "slide_role": "결론부", "slide_nos": [1]},
      {"name": "정상 구획", "slide_role": "intro", "slide_nos": [2]}
    ]}
    """
    tree = build_tree(make_doc(), llm=ScriptedLLM(payload))

    assert tree.sections[0].slide_role == "body"
    assert tree.sections[1].slide_role == "intro"
    for s in tree.sections:
        assert s.slide_role in SLIDE_ROLES


# ---------------------------------------------------------------------------
# 승계 · 가중치
# ---------------------------------------------------------------------------

def test_importance_inherited_from_concept_doc():
    """근거 슬라이드가 전부 support 면 노드도 support."""
    payload = """
    {"nodes": [
      {"id": "core-one", "label": "핵심", "parent_id": null, "slide_nos": [1]},
      {"id": "sup-one", "label": "보조", "parent_id": null, "slide_nos": [4, 5]}
    ], "sections": []}
    """
    tree = build_tree(make_doc(n_slides=5), llm=ScriptedLLM(payload))

    assert tree.node("core-one").importance == "core"
    assert tree.node("sup-one").importance == "support"


def test_weight_within_unit_range_and_core_outranks_support():
    payload = """
    {"nodes": [
      {"id": "core-one", "label": "핵심", "parent_id": null, "slide_nos": [1]},
      {"id": "sup-one", "label": "보조", "parent_id": null, "slide_nos": [5]}
    ], "sections": []}
    """
    tree = build_tree(make_doc(n_slides=5), llm=ScriptedLLM(payload))

    for node in tree.nodes:
        assert 0.0 <= node.weight <= 1.0
    assert tree.node("core-one").weight > tree.node("sup-one").weight


# ---------------------------------------------------------------------------
# 조회 헬퍼 (F-08~10 이 쓸 표면)
# ---------------------------------------------------------------------------

def test_path_of_gives_root_to_leaf_labels():
    payload = """
    {"nodes": [
      {"id": "root", "label": "루트", "parent_id": null, "slide_nos": [1]},
      {"id": "leaf", "label": "잎", "parent_id": "root", "slide_nos": [2]}
    ], "sections": []}
    """
    tree = build_tree(make_doc(), llm=ScriptedLLM(payload))

    assert [n.label for n in tree.path_of("leaf")] == ["루트", "잎"]
    assert tree.path_of("없는id") == []


def test_lookup_by_slide_and_section():
    payload = """
    {"nodes": [
      {"id": "a", "label": "A", "parent_id": null, "slide_nos": [2, 3]}
    ], "sections": [
      {"name": "서론", "slide_role": "intro", "slide_nos": [1, 2]}
    ]}
    """
    tree = build_tree(make_doc(), llm=ScriptedLLM(payload))

    assert [n.id for n in tree.nodes_for_slide(2)] == ["a"]
    assert tree.nodes_for_slide(5) == []
    assert tree.section_of(1).name == "서론"
    assert tree.section_of(5) is None


# ---------------------------------------------------------------------------
# 실패 처리
# ---------------------------------------------------------------------------

def test_unparseable_llm_output_raises_tree_error():
    with pytest.raises(TreeError):
        build_tree(make_doc(), llm=ScriptedLLM("이건 JSON 이 아니라 그냥 말입니다"))


def test_empty_concept_doc_raises_tree_error():
    empty = ConceptDoc(file_name="empty.pdf", total_slides=0, slides=[])
    with pytest.raises(TreeError):
        build_tree(empty, llm="mock")


def test_json_wrapped_in_code_fence_is_recovered():
    payload = """```json
    {"nodes": [{"id": "a", "label": "A", "parent_id": null, "slide_nos": [1]}],
     "sections": [{"name": "서론", "slide_role": "intro", "slide_nos": [1]}]}
    ```"""
    tree = build_tree(make_doc(), llm=ScriptedLLM(payload))

    assert tree.node("a") is not None
