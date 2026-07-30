"""
F-13 점수 산식의 성질을 고정합니다.

점수는 제품의 대표 숫자라, "0~100 이 나온다" 정도로는 부족합니다.
설계에서 정한 판단들이 실제로 지켜지는지를 검사합니다:
누락 이중청구 금지 · 모순은 별도 감점 · 정당한 생략은 무영향 ·
없는 지표는 0 이 아니라 제외 · 역순은 중립보다 낮음.
"""

from __future__ import annotations

import pytest

from chuckchuck.contracts import (
    AlignmentDoc,
    AlignmentItem,
    AlignmentSummary,
    FlowDiff,
)
from chuckchuck.f13_score import (
    MAX_CONTRADICTION_PENALTY,
    score_presentation,
)


def make_doc(
    *,
    coverage: float = 0.8,
    rank: float | None = 0.6,
    edge: float | None = 0.5,
    items: list[AlignmentItem] | None = None,
) -> AlignmentDoc:
    return AlignmentDoc(
        file_name="deck.pdf",
        total_slides=5,
        items=list(items or []),
        summary=AlignmentSummary(
            coverage=coverage,
            rank_correlation=rank,
            edge_coverage=edge,
        ),
    )


def make_flow(order_tau: float | None = 0.5) -> FlowDiff:
    return FlowDiff(file_name="deck.pdf", order_tau=order_tau)


# ---------------------------------------------------------------------------
# 범위·기본 성질
# ---------------------------------------------------------------------------


def test_점수는_0에서_100_사이다() -> None:
    for cov in (0.0, 0.25, 0.5, 0.75, 1.0):
        s = score_presentation(make_doc(coverage=cov), make_flow())
        assert 0 <= s.score <= 100


def test_완벽한_발표는_만점이다() -> None:
    doc = make_doc(coverage=1.0, rank=1.0, edge=1.0)
    assert score_presentation(doc, make_flow(1.0)).score == 100


def test_coverage_가_오르면_점수도_오른다() -> None:
    """단조성 — 더 많이 설명했는데 점수가 떨어지면 산식이 틀린 것이다."""
    scores = [
        score_presentation(make_doc(coverage=c), make_flow()).score
        for c in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    ]
    assert scores == sorted(scores)
    assert scores[0] < scores[-1]


# ---------------------------------------------------------------------------
# 4-class 가 점수에 반영되는 방식
# ---------------------------------------------------------------------------


def test_정당한_생략은_점수를_바꾸지_않는다() -> None:
    """4-class 를 나눈 이유. 안 다뤄도 되는 개념을 건너뛴 걸 벌하면 안 된다."""
    plain = make_doc()
    skipped = make_doc(items=[
        AlignmentItem(node_id="n1", verdict="justified_skip", doc_weight=0.9),
        AlignmentItem(node_id="n2", verdict="justified_skip", doc_weight=0.7),
    ])
    assert score_presentation(skipped, make_flow()).score == \
        score_presentation(plain, make_flow()).score


def test_누락은_따로_깎지_않는다() -> None:
    """missing 은 coverage 에 이미 반영돼 있다 — 여기서 또 깎으면 이중청구다."""
    plain = make_doc()
    with_missing = make_doc(items=[
        AlignmentItem(node_id="n1", verdict="missing", doc_weight=1.0),
        AlignmentItem(node_id="n2", verdict="missing", doc_weight=0.8),
    ])
    assert score_presentation(with_missing, make_flow()).score == \
        score_presentation(plain, make_flow()).score


def test_모순은_누락보다_낮은_점수를_받는다() -> None:
    """'안 말한 것'보다 '틀리게 말한 것'이 더 나쁘다."""
    missing = make_doc(items=[
        AlignmentItem(node_id="n1", verdict="missing", doc_weight=1.0),
    ])
    contradiction = make_doc(items=[
        AlignmentItem(node_id="n1", verdict="contradiction", doc_weight=1.0),
    ])
    assert score_presentation(contradiction, make_flow()).score < \
        score_presentation(missing, make_flow()).score


def test_핵심_개념의_모순이_곁가지_모순보다_크게_깎인다() -> None:
    core = make_doc(items=[
        AlignmentItem(node_id="n1", verdict="contradiction", doc_weight=1.0),
    ])
    minor = make_doc(items=[
        AlignmentItem(node_id="n1", verdict="contradiction", doc_weight=0.0),
    ])
    assert score_presentation(core, make_flow()).score < \
        score_presentation(minor, make_flow()).score


def test_모순_감점에는_상한이_있다() -> None:
    """모순이 쏟아져도 잘한 나머지까지 통째로 지우지는 않는다."""
    many = make_doc(items=[
        AlignmentItem(node_id=f"n{i}", verdict="contradiction", doc_weight=1.0)
        for i in range(50)
    ])
    s = score_presentation(many, make_flow())
    assert s.contradiction_penalty == MAX_CONTRADICTION_PENALTY
    assert s.contradiction_count == 50


# ---------------------------------------------------------------------------
# 상관계수 매핑
# ---------------------------------------------------------------------------


def test_역순으로_말하면_중립보다_낮다() -> None:
    """-1 이 0 으로 잘려 신호를 잃으면 안 된다."""
    reverse = score_presentation(make_doc(rank=-1.0), make_flow(-1.0)).score
    neutral = score_presentation(make_doc(rank=0.0), make_flow(0.0)).score
    forward = score_presentation(make_doc(rank=1.0), make_flow(1.0)).score
    assert reverse < neutral < forward


# ---------------------------------------------------------------------------
# 지표가 없을 때 (작은 자료)
# ---------------------------------------------------------------------------


def test_지표가_전부_없으면_coverage_만으로_매긴다() -> None:
    """작은 덱에서는 순위·간선·순서가 동시에 None 일 수 있다. 낙제시키면 안 된다."""
    doc = make_doc(coverage=0.9, rank=None, edge=None)
    s = score_presentation(doc, flow=None)
    assert s.basis == "coverage-only"
    assert s.omitted == ["edge", "order", "rank"]
    assert s.score == 90  # coverage 가 100% 가중치를 가져간다
    assert [c.key for c in s.components] == ["coverage"]


def test_없는_지표는_0점_처리되지_않는다() -> None:
    """0 으로 치면 멀쩡한 발표가 무너진다 — 가중치를 재분배해야 한다."""
    full = score_presentation(make_doc(coverage=1.0, rank=1.0, edge=1.0), make_flow(1.0))
    partial = score_presentation(make_doc(coverage=1.0, rank=None, edge=None), flow=None)
    assert partial.score == full.score == 100


def test_flow_가_없으면_흐름_항이_빠진다() -> None:
    s = score_presentation(make_doc(), flow=None)
    assert "order" in s.omitted
    assert s.basis == "partial"
    assert all(c.key != "order" for c in s.components)


def test_order_tau_가_None_이면_흐름_항이_빠진다() -> None:
    s = score_presentation(make_doc(), make_flow(order_tau=None))
    assert "order" in s.omitted


# ---------------------------------------------------------------------------
# 설명 가능성 — UI 가 '왜 이 점수인지' 그릴 수 있어야 한다
# ---------------------------------------------------------------------------


def test_가중치는_항상_1로_정규화된다() -> None:
    for flow in (make_flow(), None):
        s = score_presentation(make_doc(), flow)
        assert sum(c.weight for c in s.components) == pytest.approx(1.0)


def test_기여도의_합이_감점_전_점수와_같다() -> None:
    doc = make_doc(coverage=0.8, rank=0.4, edge=0.6, items=[
        AlignmentItem(node_id="n1", verdict="contradiction", doc_weight=0.5),
    ])
    s = score_presentation(doc, make_flow(0.2))
    base = sum(c.contribution for c in s.components)
    assert s.score == round(base - s.contradiction_penalty)


def test_직렬화가_계약을_지킨다() -> None:
    s = score_presentation(make_doc(), make_flow()).to_dict()
    assert set(s) == {
        "score", "components", "omitted",
        "contradiction_penalty", "contradiction_count", "basis",
    }
    assert set(s["components"][0]) == {"key", "label", "raw", "weight", "contribution"}


# ---------------------------------------------------------------------------
# 빈 입력
# ---------------------------------------------------------------------------


def test_빈_발표는_터지지_않고_0점이다() -> None:
    doc = AlignmentDoc(file_name="empty.pdf", total_slides=0)
    s = score_presentation(doc, flow=None)
    assert s.score == 0
    assert 0 <= s.score <= 100
