"""
[F-11 파생] 자료 흐름과 발표 흐름의 차이를 계산하는 모듈입니다.
ConceptGraph + AlignmentDoc → FlowDiff. LLM 호출이 없는 순수 함수입니다.

발표 흐름을 위해 발화 그래프를 독립 추출하지 않습니다 (F-11 설계 결정 — 추출
분산이 두 배가 되어 diff 가 노이즈를 측정합니다). 이미 F-11 이 결정적으로 계산한
신호(first_mention_sec·mention_count·speech_edges)만 재배열합니다.

    from chuckchuck.f11_flow import build_flow_diff
    flow = build_flow_diff(graph, alignment)

판정 3종 (MVP 스펙 '논리 흐름' 탭):
- missing_link  문서 간선의 두 개념을 각각 말했지만 잇는 멘트가 없었다
- order_jump    자식 개념을 부모 개념보다 먼저 말했다 (자료 순서 역행)
- good_link     말로 이은 연결이 문서에도 있다 — cue 인용과 함께 칭찬
"""

from __future__ import annotations

from .contracts import (
    AlignError,
    AlignmentDoc,
    AlignmentItem,
    ConceptGraph,
    ConceptNode,
    FlowDiff,
    FlowIssue,
    FlowStep,
)

#: slide_nos 가 빈 노드는 흐름상 맨 뒤로 보낸다.
_NO_SLIDE = 10 ** 9


# ---------------------------------------------------------------------------
# 순서 축
# ---------------------------------------------------------------------------

def _doc_orders(graph: ConceptGraph) -> dict[str, int]:
    """근거 슬라이드 순 → 1..n. 동률은 무거운 개념 먼저, 그다음 그래프 순서."""
    keyed = sorted(
        enumerate(graph.nodes),
        key=lambda pair: (
            min(pair[1].slide_nos) if pair[1].slide_nos else _NO_SLIDE,
            -pair[1].weight,
            pair[0],
        ),
    )
    return {node.id: rank for rank, (_, node) in enumerate(keyed, start=1)}


def _speech_orders(
    items: dict[str, AlignmentItem], doc_order: dict[str, int]
) -> dict[str, int]:
    """첫 언급 시각 순 → 1..k. 시각을 못 잡은 노드는 순서를 받지 않는다."""
    timed = [
        (item.speech_basis.first_mention_sec, doc_order[nid], nid)
        for nid, item in items.items()
        if item.speech_basis.first_mention_sec is not None
    ]
    timed.sort()
    return {nid: rank for rank, (_, _, nid) in enumerate(timed, start=1)}


def _kendall_tau(pairs: list[tuple[int, int]]) -> float | None:
    """(doc_order, speech_order) 쌍들의 Kendall tau. 표본 2개 미만이면 None."""
    n = len(pairs)
    if n < 2:
        return None
    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            sign = (pairs[i][0] - pairs[j][0]) * (pairs[i][1] - pairs[j][1])
            if sign > 0:
                concordant += 1
            elif sign < 0:
                discordant += 1
    total = n * (n - 1) / 2
    return round((concordant - discordant) / total, 3)


# ---------------------------------------------------------------------------
# 판정 3종
# ---------------------------------------------------------------------------

def _pair_slides(a: ConceptNode, b: ConceptNode) -> list[int]:
    return sorted(set(a.slide_nos) | set(b.slide_nos))


def _order_jumps(
    graph: ConceptGraph,
    by_id: dict[str, ConceptNode],
    doc_order: dict[str, int],
    speech_order: dict[str, int],
) -> list[FlowIssue]:
    """parent 간선에서 자식을 부모보다 먼저 말한 경우. 문서 순서도 역행이어야 한다."""
    out: list[FlowIssue] = []
    for edge in graph.edges:
        if edge.kind != "parent":
            continue
        p, c = edge.from_id, edge.to_id
        if p not in speech_order or c not in speech_order:
            continue
        if doc_order[p] < doc_order[c] and speech_order[p] > speech_order[c]:
            parent, child = by_id[p], by_id[c]
            out.append(FlowIssue(
                kind="order_jump",
                node_ids=[p, c],
                slide_nos=_pair_slides(parent, child),
                note=(
                    f"'{child.label}' 을(를) 상위 개념 '{parent.label}' 보다 먼저 "
                    "말했어요 — 자료 순서와 반대예요"
                ),
            ))
    return out


def _missing_links(
    graph: ConceptGraph,
    by_id: dict[str, ConceptNode],
    items: dict[str, AlignmentItem],
    spoken_pairs: set[frozenset],
) -> list[FlowIssue]:
    """문서 간선의 두 개념을 각각 말했는데 잇는 멘트가 없는 경우 (방향 무시)."""
    out: list[FlowIssue] = []
    seen: set[frozenset] = set()
    for edge in graph.edges:
        pair = frozenset((edge.from_id, edge.to_id))
        if len(pair) < 2 or pair in seen:
            continue
        seen.add(pair)
        if pair in spoken_pairs:
            continue
        a, b = by_id[edge.from_id], by_id[edge.to_id]
        if items[a.id].speech_basis.mention_count < 1:
            continue
        if items[b.id].speech_basis.mention_count < 1:
            continue
        out.append(FlowIssue(
            kind="missing_link",
            node_ids=[edge.from_id, edge.to_id],
            slide_nos=_pair_slides(a, b),
            note=(
                f"'{a.label}' 와(과) '{b.label}' 를 각각 말했지만 "
                "둘을 잇는 멘트가 없었어요"
            ),
        ))
    return out


def _good_links(
    alignment: AlignmentDoc, by_id: dict[str, ConceptNode]
) -> list[FlowIssue]:
    """말로 이은 연결이 문서에도 있는 경우. 근거 인용(cue)이 있어야 칭찬한다."""
    out: list[FlowIssue] = []
    for edge in alignment.speech_edges:
        if not edge.in_graph or not edge.cue.strip():
            continue
        a, b = by_id[edge.from_id], by_id[edge.to_id]
        out.append(FlowIssue(
            kind="good_link",
            node_ids=[edge.from_id, edge.to_id],
            cue=edge.cue.strip(),
            slide_nos=_pair_slides(a, b),
            note=f"'{a.label}' 와(과) '{b.label}' 를 말로 잘 이었어요",
        ))
    return out


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------

def build_flow_diff(
    graph: ConceptGraph | dict,
    alignment: AlignmentDoc | dict,
) -> FlowDiff:
    """
    ConceptGraph + AlignmentDoc → FlowDiff.

    순수 함수다 — 같은 입력이면 언제나 같은 출력이고, LLM·네트워크를 쓰지 않는다.
    STT 가 mock 이든 실제든 Transcript 이후 단계는 이 함수 그대로다.
    """
    if isinstance(graph, dict):
        graph = ConceptGraph.from_dict(graph)
    if isinstance(alignment, dict):
        alignment = AlignmentDoc.from_dict(alignment)
    if not graph.nodes:
        raise AlignError("ConceptGraph 에 노드가 없습니다. F-07 결과를 먼저 확인하세요.")

    by_id = {n.id: n for n in graph.nodes}
    items = {i.node_id: i for i in alignment.items}
    absent = [nid for nid in by_id if nid not in items]
    if absent:
        raise AlignError(
            f"AlignmentDoc 에 판정이 없는 노드가 있습니다: {', '.join(absent)}. "
            "F-11 결과가 이 그래프에서 나온 것인지 확인하세요."
        )

    doc_order = _doc_orders(graph)
    speech_order = _speech_orders(items, doc_order)

    steps = sorted(
        (
            FlowStep(
                node_id=nid,
                doc_order=doc_order[nid],
                speech_order=speech_order.get(nid),
                first_mention_sec=items[nid].speech_basis.first_mention_sec,
            )
            for nid in by_id
        ),
        key=lambda s: s.doc_order,
    )

    spoken_pairs = {
        frozenset((e.from_id, e.to_id))
        for e in alignment.speech_edges
        if e.from_id != e.to_id
    }

    issues = (
        _order_jumps(graph, by_id, doc_order, speech_order)
        + _missing_links(graph, by_id, items, spoken_pairs)
        + _good_links(alignment, by_id)
    )

    tau = _kendall_tau([
        (s.doc_order, s.speech_order) for s in steps if s.speech_order is not None
    ])

    return FlowDiff(
        file_name=graph.file_name,
        steps=steps,
        issues=issues,
        order_tau=tau,
        spoken_node_count=sum(
            1 for i in items.values() if i.speech_basis.mention_count >= 1
        ),
        ghost_node_ids=[s.node_id for s in steps if s.speech_order is None],
        extra_labels=[c.label for c in alignment.extra_concepts],
    )
