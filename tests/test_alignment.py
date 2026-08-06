"""
F-11 정합 판정(align_speech)이 계약 불변식을 지키는지 검사하는 테스트입니다.
SCHEMA.md §7 의 '보증' 항목이 여기 그대로 대응됩니다.

LLM 은 전부 가짜라서 네트워크·API 키가 필요하지 않습니다.
"""

import json

import pytest

from chuckchuck.contracts import (
    ALIGN_VERDICTS,
    AlignError,
    AlignmentDoc,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    SlideSpeech,
    Transcript,
    Word,
)
from chuckchuck.f11_align import align_speech
from chuckchuck.providers.llm_base import LLMProvider


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def make_graph(n: int = 3, edges: list[ConceptEdge] | None = None) -> ConceptGraph:
    """작은 ConceptGraph. c1 이 최상위(weight 1.0), 뒤로 갈수록 가볍다."""
    nodes = [
        ConceptNode(
            id=f"c{i}",
            label=f"개념{i}",
            slide_nos=[i],
            summary=f"개념{i} 한 줄",
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


def make_transcript(texts: dict[int, str], *, with_words: bool = False) -> Transcript:
    """슬라이드 번호 → 발화 텍스트. 장마다 10초씩 말한 것으로 둔다."""
    by_slide = []
    words: list[Word] = []
    cursor = 0.0
    for no in sorted(texts):
        seg_words = []
        if with_words:
            t = cursor
            for token in texts[no].split():
                seg_words.append(Word(text=token, start_sec=t, end_sec=t + 0.5))
                t += 1.0
        by_slide.append(SlideSpeech(
            slide_no=no,
            visit=1,
            start_sec=cursor,
            end_sec=cursor + 10.0,
            text=texts[no],
            words=seg_words,
        ))
        words.extend(seg_words)
        cursor += 10.0
    return Transcript(
        full_text=" ".join(texts[no] for no in sorted(texts)),
        words=words,
        by_slide=by_slide,
        provider="mock",
        duration_sec=cursor,
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


def payload(items=None, speech_edges=None, extra_concepts=None) -> str:
    return json.dumps({
        "items": items or [],
        "speech_edges": speech_edges or [],
        "extra_concepts": extra_concepts or [],
    }, ensure_ascii=False)


def align_of(llm_payload: str, *, graph=None, transcript=None) -> AlignmentDoc:
    return align_speech(
        graph or make_graph(),
        transcript or make_transcript({1: "개념1 설명", 2: "개념2 설명", 3: "개념3 설명"}),
        llm=ScriptedLLM(llm_payload),
    )


_ALL_ALIGNED = payload(items=[
    {"node_id": "c1", "verdict": "aligned", "evidence": "개념1 설명"},
    {"node_id": "c2", "verdict": "aligned", "evidence": "개념2 설명"},
    {"node_id": "c3", "verdict": "aligned", "evidence": "개념3 설명"},
])


# ---------------------------------------------------------------------------
# mock 파이프라인 · 왕복
# ---------------------------------------------------------------------------

def test_mock_llm_end_to_end():
    doc = align_speech(
        make_graph(),
        make_transcript({1: "개념1 설명", 2: "개념2 설명", 3: "이건 다른 얘기"}),
        llm="mock",
    )
    assert doc.model == "mock"
    assert len(doc.items) == 3
    assert doc.summary.verdict_counts["aligned"] >= 1


def test_roundtrip():
    doc = align_of(_ALL_ALIGNED)
    again = AlignmentDoc.from_dict(doc.to_dict())
    assert [i.node_id for i in again.items] == [i.node_id for i in doc.items]
    assert again.summary.coverage == doc.summary.coverage
    assert again.items[0].speech_basis.mention_count == doc.items[0].speech_basis.mention_count


def test_scatter_points_and_lookup():
    doc = align_of(_ALL_ALIGNED)
    pts = doc.scatter_points
    assert len(pts) == 3
    assert pts[0] == ("c1", 1.0, doc.item("c1").speech_weight)
    assert doc.item("없는id") is None
    assert len(doc.by_verdict("aligned")) == 3


def test_transcript_text_for_slide_merges_revisits():
    t = Transcript(
        full_text="a b",
        by_slide=[
            SlideSpeech(slide_no=1, visit=1, start_sec=0, end_sec=5, text="a"),
            SlideSpeech(slide_no=2, visit=1, start_sec=5, end_sec=8, text="x"),
            SlideSpeech(slide_no=1, visit=2, start_sec=8, end_sec=10, text="b"),
        ],
    )
    assert t.text_for_slide(1) == "a b"


# ---------------------------------------------------------------------------
# 불변식 1~3 : 모든 노드에 item 정확히 1개
# ---------------------------------------------------------------------------

def test_every_node_gets_exactly_one_item():
    doc = align_of(payload(items=[{"node_id": "c1", "verdict": "aligned", "evidence": "e"}]))
    assert sorted(i.node_id for i in doc.items) == ["c1", "c2", "c3"]


def test_unknown_node_id_dropped():
    doc = align_of(payload(items=[
        {"node_id": "ghost", "verdict": "contradiction", "evidence": "e"},
    ] + json.loads(_ALL_ALIGNED)["items"]))
    assert doc.item("ghost") is None
    assert len(doc.items) == 3


def test_duplicate_node_id_first_wins():
    doc = align_of(payload(items=[
        {"node_id": "c1", "verdict": "aligned", "evidence": "첫 번째"},
        {"node_id": "c1", "verdict": "contradiction", "evidence": "두 번째"},
    ]))
    assert doc.item("c1").verdict == "aligned"
    assert doc.item("c1").evidence == "첫 번째"


def test_fallback_when_llm_omits_node():
    # c3 판정 누락. 발화에 '개념3' 언급이 없으면 missing, 있으면 aligned
    t = make_transcript({1: "개념1 설명", 2: "개념2 설명", 3: "딴 얘기"})
    doc = align_speech(make_graph(), t, llm=ScriptedLLM(payload(items=[
        {"node_id": "c1", "verdict": "aligned", "evidence": "e"},
        {"node_id": "c2", "verdict": "aligned", "evidence": "e"},
    ])))
    assert doc.item("c3").verdict == "missing"

    # MENTION_MIN=2 — 한 번 스친 것은 설명이 아니다. 두 번 말해야 정합이다
    t2 = make_transcript({1: "개념1 설명", 2: "개념2 설명", 3: "개념3 도 말했다 개념3 은 이렇다"})
    doc2 = align_speech(make_graph(), t2, llm=ScriptedLLM(payload(items=[
        {"node_id": "c1", "verdict": "aligned", "evidence": "e"},
        {"node_id": "c2", "verdict": "aligned", "evidence": "e"},
    ])))
    assert doc2.item("c3").verdict == "aligned"


def test_invalid_verdict_replaced_by_fallback():
    doc = align_of(payload(items=[
        {"node_id": "c1", "verdict": "완벽함", "evidence": "e"},
    ]))
    assert doc.item("c1").verdict in ALIGN_VERDICTS


# ---------------------------------------------------------------------------
# 불변식 4~5 : 판정을 결정적 신호로 다듬는다
# ---------------------------------------------------------------------------

def test_missing_corrected_when_label_actually_spoken():
    # 발화에 '개념1' 이 MENTION_MIN(2)회 이상 있는데 LLM 이 missing 이라고 우기면 aligned 로 정정
    doc = align_of(
        payload(items=[{"node_id": "c1", "verdict": "missing"}]),
        transcript=make_transcript({
            1: "개념1 설명 개념1 은 이런 것이다", 2: "개념2 설명", 3: "개념3 설명",
        }),
    )
    assert doc.item("c1").verdict == "aligned"


def test_single_mention_does_not_override_missing():
    """한 번 스친 언급으로는 LLM 의 '누락' 판정을 뒤집지 않는다.

    이게 빠져 있어서 리포트가 전부 초록으로 떴다 — 슬라이드 제목 낱말을
    한 번 말한 것만으로 "설명했다"가 됐다 (2026-08-07 지시로 조임).
    """
    doc = align_of(
        payload(items=[{"node_id": "c1", "verdict": "missing"}]),
        transcript=make_transcript({1: "개념1 설명", 2: "개념2 설명", 3: "개념3 설명"}),
    )
    assert doc.item("c1").verdict == "missing"


def test_missing_kept_when_label_not_spoken():
    t = make_transcript({1: "전혀 다른 이야기", 2: "개념2 설명", 3: "개념3 설명"})
    doc = align_speech(make_graph(), t, llm=ScriptedLLM(payload(items=[
        {"node_id": "c1", "verdict": "missing"},
    ])))
    assert doc.item("c1").verdict == "missing"


def test_contradiction_without_evidence_demoted():
    doc = align_of(payload(items=[
        {"node_id": "c1", "verdict": "contradiction", "evidence": ""},
    ]))
    assert doc.item("c1").verdict != "contradiction"


def test_contradiction_with_evidence_kept():
    doc = align_of(payload(items=[
        {"node_id": "c1", "verdict": "contradiction", "evidence": "개념1 은 반대라고 말함"},
    ]))
    assert doc.item("c1").verdict == "contradiction"


def test_justified_skip_respected():
    doc = align_of(payload(items=[
        {"node_id": "c3", "verdict": "justified_skip", "note": "보조 개념"},
    ]))
    assert doc.item("c3").verdict == "justified_skip"


def test_justified_skip_demoted_for_heavy_unspoken_concept():
    # 자료가 힘준 개념(c1, w=1.0)을 한 번도 안 말했는데 LLM 이 정당생략이라 하면 누락으로 강등
    t = make_transcript({1: "전혀 다른 이야기", 2: "개념2 설명", 3: "개념3 설명"})
    doc = align_speech(make_graph(), t, llm=ScriptedLLM(payload(items=[
        {"node_id": "c1", "verdict": "justified_skip", "note": "생략해도 됨"},
    ])))
    assert doc.item("c1").verdict == "missing"


def test_justified_skip_kept_for_light_unspoken_concept():
    # 가벼운 개념(c5, w=0.2 < SKIP_GUARD_WEIGHT 0.35)은 무언급이어도 정당생략을 존중한다
    t = make_transcript({
        1: "개념1 설명", 2: "개념2 설명", 3: "개념3 설명", 4: "개념4 설명", 5: "다른 얘기",
    })
    doc = align_speech(make_graph(5), t, llm=ScriptedLLM(payload(items=[
        {"node_id": "c5", "verdict": "justified_skip", "note": "보조 개념"},
    ])))
    assert doc.item("c5").verdict == "justified_skip"


def test_justified_skip_demoted_at_tightened_guard():
    """w=0.4 는 예전 기준(0.5)에서는 정당생략이었지만 조인 기준(0.35)에서는 누락이다.

    이 경계가 움직였다는 사실 자체를 못 박아 둔다 — 기준을 되돌리면 여기서 걸린다.
    """
    t = make_transcript({1: "개념1 설명", 2: "개념2 설명", 3: "개념3 설명", 4: "다른 얘기"})
    doc = align_speech(make_graph(4), t, llm=ScriptedLLM(payload(items=[
        {"node_id": "c4", "verdict": "justified_skip", "note": "보조 개념"},
    ])))
    assert doc.item("c4").verdict == "missing"


# ---------------------------------------------------------------------------
# 불변식 6 : speech_edges
# ---------------------------------------------------------------------------

def test_speech_edges_validated_and_deduped():
    doc = align_of(payload(items=json.loads(_ALL_ALIGNED)["items"], speech_edges=[
        {"from": "c1", "to": "c2", "cue": "그래서"},
        {"from": "c2", "to": "c1", "cue": "방향만 다른 중복"},
        {"from": "c1", "to": "c1", "cue": "자기 간선"},
        {"from": "c1", "to": "ghost", "cue": "없는 노드"},
    ]))
    assert len(doc.speech_edges) == 1
    assert doc.speech_edges[0].cue == "그래서"


def test_speech_edge_in_graph_derived():
    doc = align_of(payload(items=json.loads(_ALL_ALIGNED)["items"], speech_edges=[
        {"from": "c2", "to": "c1", "cue": "문서에도 있는 연결 (방향 무시)"},
        {"from": "c2", "to": "c3", "cue": "문서에 없는 연결"},
    ]))
    by_pair = {frozenset((e.from_id, e.to_id)): e.in_graph for e in doc.speech_edges}
    assert by_pair[frozenset(("c1", "c2"))] is True
    assert by_pair[frozenset(("c2", "c3"))] is False


# ---------------------------------------------------------------------------
# 불변식 7 : extra_concepts
# ---------------------------------------------------------------------------

def test_extra_concept_already_in_graph_dropped():
    doc = align_of(payload(items=json.loads(_ALL_ALIGNED)["items"], extra_concepts=[
        {"label": "개념1", "quote": "이미 그래프에 있다"},
        {"label": "정말 새로운 것", "quote": "인용", "slide_no": 2},
    ]))
    assert [c.label for c in doc.extra_concepts] == ["정말 새로운 것"]
    assert doc.extra_concepts[0].slide_no == 2


def test_extra_concept_empty_label_and_bad_slide_no():
    doc = align_of(payload(items=json.loads(_ALL_ALIGNED)["items"], extra_concepts=[
        {"label": "", "quote": "버려짐"},
        {"label": "새 개념 하나", "slide_no": 99},
        {"label": "새 개념 하나", "slide_no": 1},  # 토큰 중복 — 첫 번째만
    ]))
    assert len(doc.extra_concepts) == 1
    assert doc.extra_concepts[0].slide_no is None


# ---------------------------------------------------------------------------
# 불변식 9~11 : 재시도·실패
# ---------------------------------------------------------------------------

def test_broken_json_retried_once():
    llm = SequenceLLM("이건 JSON 이 아니다", _ALL_ALIGNED)
    doc = align_speech(
        make_graph(),
        make_transcript({1: "개념1", 2: "개념2", 3: "개념3"}),
        llm=llm,
    )
    assert llm.calls == 2
    assert len(doc.items) == 3


def test_broken_json_twice_raises():
    llm = SequenceLLM("깨짐", "또 깨짐")
    with pytest.raises(AlignError):
        align_speech(
            make_graph(),
            make_transcript({1: "개념1", 2: "개념2", 3: "개념3"}),
            llm=llm,
        )


def test_empty_items_retried_then_used():
    llm = SequenceLLM(payload(), _ALL_ALIGNED)
    doc = align_speech(
        make_graph(),
        make_transcript({1: "개념1", 2: "개념2", 3: "개념3"}),
        llm=llm,
    )
    assert llm.calls == 2
    assert doc.item("c1").verdict == "aligned"
    assert doc.item("c1").evidence


def test_empty_items_twice_falls_back_deterministically():
    llm = SequenceLLM(payload(), payload())
    # MENTION_MIN=2 — 정합을 기대하는 개념은 두 번 말한 것으로 둔다
    t = make_transcript({
        1: "개념1 설명 개념1 정리", 2: "딴 얘기", 3: "개념3 설명 개념3 정리",
    })
    doc = align_speech(make_graph(), t, llm=llm)
    assert doc.item("c1").verdict == "aligned"
    assert doc.item("c2").verdict == "missing"
    assert doc.item("c3").verdict == "aligned"


def test_empty_graph_raises():
    empty = ConceptGraph(file_name="x.pdf", total_slides=0, nodes=[], edges=[])
    with pytest.raises(AlignError):
        align_speech(empty, make_transcript({1: "말"}), llm=ScriptedLLM(_ALL_ALIGNED))


def test_empty_transcript_raises():
    with pytest.raises(AlignError):
        align_speech(
            make_graph(),
            Transcript(full_text="", by_slide=[]),
            llm=ScriptedLLM(_ALL_ALIGNED),
        )


# ---------------------------------------------------------------------------
# 발화 축 — 결정적 신호
# ---------------------------------------------------------------------------

def test_speech_basis_time_and_mentions():
    # 장마다 10초. c1 근거 장(1)에서만 '개념1' 을 세 번 말했다
    t = make_transcript({1: "개념1 그리고 개념1 또 개념1", 2: "개념2", 3: "개념3"})
    doc = align_of(_ALL_ALIGNED, transcript=t)
    b = doc.item("c1").speech_basis
    assert b.speech_sec == 10.0
    assert b.time_share == pytest.approx(10.0 / 30.0, abs=1e-3)
    assert b.mention_count == 3
    assert b.mentioned_slide_count == 1


def test_speech_weight_relative_top_is_one():
    t = make_transcript({1: "개념1 개념1 개념1", 2: "개념2 개념2", 3: "개념3"})
    doc = align_of(_ALL_ALIGNED, transcript=t)
    weights = {i.node_id: i.speech_weight for i in doc.items}
    assert weights["c1"] == 1.0
    assert weights["c1"] > weights["c2"] > weights["c3"] > 0.0


def test_first_mention_sec_needs_words():
    without = align_of(_ALL_ALIGNED)
    assert without.item("c1").speech_basis.first_mention_sec is None

    t = make_transcript({1: "서론 후에 개념1 등장", 2: "개념2", 3: "개념3"}, with_words=True)
    doc = align_of(_ALL_ALIGNED, transcript=t)
    first = doc.item("c1").speech_basis.first_mention_sec
    assert first is not None and first > 0.0


def test_revisit_time_summed():
    t = Transcript(
        full_text="개념1 개념2 개념3 개념1",
        by_slide=[
            SlideSpeech(slide_no=1, visit=1, start_sec=0, end_sec=10, text="개념1"),
            SlideSpeech(slide_no=2, visit=1, start_sec=10, end_sec=20, text="개념2 개념3"),
            SlideSpeech(slide_no=1, visit=2, start_sec=20, end_sec=25, text="개념1 재방문"),
        ],
        duration_sec=25.0,
    )
    doc = align_of(_ALL_ALIGNED, transcript=t)
    assert doc.item("c1").speech_basis.speech_sec == 15.0


# ---------------------------------------------------------------------------
# 요약 지표
# ---------------------------------------------------------------------------

def test_coverage_weighted_and_skip_excluded():
    # c1(1.0) 정합, c2(0.8) 정당생략 — 언급은 했으므로 무언급 가드에 안 걸린다,
    # c3(0.6) 누락(발화에 없음)
    t = make_transcript({1: "개념1 설명", 2: "개념2 는 넘어갈게요", 3: "또 딴 얘기"})
    doc = align_speech(make_graph(), t, llm=ScriptedLLM(payload(items=[
        {"node_id": "c1", "verdict": "aligned", "evidence": "개념1 설명"},
        {"node_id": "c2", "verdict": "justified_skip"},
        {"node_id": "c3", "verdict": "missing"},
    ])))
    # 분모 = 1.0 + 0.6 (정당생략 제외), 분자 = 1.0
    assert doc.summary.coverage == pytest.approx(1.0 / 1.6, abs=1e-3)
    assert doc.summary.verdict_counts["justified_skip"] == 1


def test_rank_correlation_perfect_order():
    t = make_transcript({1: "개념1 개념1 개념1", 2: "개념2 개념2", 3: "개념3"})
    doc = align_of(_ALL_ALIGNED, transcript=t)
    assert doc.summary.rank_correlation == 1.0


def test_rank_correlation_none_when_degenerate():
    # 발화가 어떤 label 도 안 담으면 speech_weight 가 전부 동률 → 상관 정의 불가
    t = make_transcript({1: "전혀", 2: "다른", 3: "이야기"})
    doc = align_of(_ALL_ALIGNED, transcript=t)
    assert doc.summary.rank_correlation is None


def test_edge_coverage():
    graph = make_graph(3, edges=[
        ConceptEdge(from_id="c1", to_id="c2", kind="parent"),
        ConceptEdge(from_id="c2", to_id="c3", kind="relates"),
    ])
    doc = align_speech(
        graph,
        make_transcript({1: "개념1", 2: "개념2", 3: "개념3"}),
        llm=ScriptedLLM(payload(
            items=json.loads(_ALL_ALIGNED)["items"],
            speech_edges=[{"from": "c2", "to": "c1", "cue": "그래서"}],
        )),
    )
    assert doc.summary.edge_coverage == 0.5


def test_edge_coverage_none_without_graph_edges():
    graph = make_graph(2, edges=[])
    doc = align_speech(
        graph,
        make_transcript({1: "개념1", 2: "개념2"}),
        llm=ScriptedLLM(payload(items=[
            {"node_id": "c1", "verdict": "aligned", "evidence": "e"},
            {"node_id": "c2", "verdict": "aligned", "evidence": "e"},
        ])),
    )
    assert doc.summary.edge_coverage is None


def test_summary_totals():
    doc = align_of(_ALL_ALIGNED)
    assert doc.summary.speech_total_sec == 30.0
    assert sum(doc.summary.verdict_counts.values()) == 3


# ---------------------------------------------------------------------------
# dict 입력 허용 (프론트 JSON 직결)
# ---------------------------------------------------------------------------

def test_accepts_dict_inputs():
    graph = make_graph()
    t = make_transcript({1: "개념1", 2: "개념2", 3: "개념3"})
    doc = align_speech(
        graph.to_dict(),
        t.to_dict(),
        {"situation": "수업 발표"},
        llm=ScriptedLLM(_ALL_ALIGNED),
    )
    assert len(doc.items) == 3
