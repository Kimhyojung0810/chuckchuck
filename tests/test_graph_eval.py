"""graph_eval 의 결정론적 지표 — 그래프·정합이 자료·발화에 뿌리내렸는지 잰다. LLM 없음."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from chuckchuck.contracts import AlignmentDoc, ConceptGraph, SlideDoc, Transcript

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("graph_eval", ROOT / "examples" / "graph_eval.py")
ge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ge)


def _slide(no, text):
    return {"slide_no": no, "title": "", "blocks": [{"category": "paragraph", "text": text}]}


SLIDES = SlideDoc.from_dict({"file_name": "a.pdf", "total_slides": 4, "slides": [
    _slide(1, "표지"),                                                     # 본문 아님 (짧다)
    _slide(2, "알림 확인은 잠깐이 아니라 집중 손실을 일으킨다. 작업 맥락이 흔들린다."),
    _slide(3, "작업 흐름 끊김 뒤 복귀 시간은 평균 이십삼 분이 걸린다는 연구가 있다."),
    _slide(4, "환경 설계 전략: 알림 차단, 집중 시간 블록, 상태 표시."),
]})


def _graph(nodes, edges=()):
    return ConceptGraph.from_dict({"file_name": "a.pdf", "total_slides": 4, "nodes": nodes,
                                   "edges": [{"from": a, "to": b, "kind": k} for a, b, k in edges], "sections": []})


def _node(id, label, slides, summary="", importance="core", weight=0.5):
    return {"id": id, "label": label, "slide_nos": slides, "summary": summary, "importance": importance, "weight": weight}


def test_graph_metrics_on_a_well_grounded_graph():
    g = _graph([
        _node("n1", "집중 손실", [2], "알림 확인이 집중 손실을 일으킨다", weight=1.0),
        _node("n2", "복귀 시간", [3], "복귀 시간은 평균 이십삼 분"),
        _node("n3", "환경 설계 전략", [4], "알림 차단과 집중 시간 블록"),
    ], edges=[("n1", "n2", "parent"), ("n1", "n3", "relates")])
    m = ge.graph_metrics(g, SLIDES)
    assert m["content_slides"] == 3 and m["slide_coverage"] == 1.0
    assert m["anchored_ratio"] == 1.0 and m["label_grounded"] == 1.0
    assert m["summary_grounding"] >= 0.8
    assert m["orphan_ratio"] == 0.0 and m["dangling_edges"] == 0 and m["dup_label_pairs"] == 0
    assert m["nodes_per_slide"] == 1.0 and m["depth_max"] == 1 and m["top_weight_count"] == 1


def test_graph_metrics_catch_invented_orphan_and_duplicate_nodes():
    g = _graph([
        _node("n1", "집중 손실", [2]),
        _node("n2", "양자 컴퓨팅", [], "자료에 없는 개념"),          # 지어낸 이름 · 근거 장 없음 · 고립
        _node("n3", "집중 손실 문제", [2]),                          # n1 과 거의 같은 이름
    ], edges=[("n1", "n3", "parent"), ("n1", "ghost", "relates")])   # ghost 는 없는 노드
    m = ge.graph_metrics(g, SLIDES)
    assert m["slide_coverage"] == pytest.approx(1 / 3, abs=0.01)
    assert m["anchored_ratio"] == pytest.approx(2 / 3, abs=0.01)
    assert m["label_grounded"] == pytest.approx(2 / 3, abs=0.01)
    assert m["orphan_ratio"] == pytest.approx(1 / 3, abs=0.01)
    assert m["dangling_edges"] == 1 and m["dup_label_pairs"] == 1


def _transcript(text_by_slide):
    return Transcript.from_dict({"full_text": " ".join(text_by_slide.values()), "words": [], "by_slide": [
        {"slide_no": no, "visit": 1, "start_sec": 0, "end_sec": 1, "text": t} for no, t in text_by_slide.items()]})


def test_alignment_metrics_flag_invented_evidence_and_wrong_verdicts():
    g = _graph([_node("n1", "집중 손실", [2]), _node("n2", "복귀 시간", [3]), _node("n3", "환경 설계 전략", [4])])
    tr = _transcript({2: "알림을 보면 집중 손실이 생겨요", 3: "복귀 시간이 꽤 걸려요"})
    al = AlignmentDoc.from_dict({"file_name": "a.pdf", "total_slides": 4, "items": [
        {"node_id": "n1", "verdict": "aligned", "evidence": "알림을 보면 집중 손실이 생겨요"},   # 인용이 발화에 있다
        {"node_id": "n2", "verdict": "missing", "evidence": ""},                                # 발화에 있는데 누락 판정
        {"node_id": "n3", "verdict": "aligned", "evidence": "환경 설계가 핵심이라고 했어요"},  # 발화에 없는 인용 + 이름도 없음
    ], "summary": {"coverage": 0.6}})
    a = ge.alignment_metrics(al, g, tr)
    assert a["items"] == 3 and a["verdicts"] == {"aligned": 2, "missing": 1}
    assert a["evidence_found"] == 0.5
    assert a["false_missing"] == 1 and a["false_aligned"] == 1
    assert a["coverage"] == 0.6


def test_compare_graph_uses_regression_rule():
    before = {"slide_coverage": 0.9, "orphan_ratio": 0.1, "dangling_edges": 0, "align": {"evidence_found": 0.8}}
    after_better = {"slide_coverage": 1.0, "orphan_ratio": 0.1, "dangling_edges": 0, "align": {"evidence_found": 0.8}}
    after_mixed = {"slide_coverage": 1.0, "orphan_ratio": 0.1, "dangling_edges": 2, "align": {"evidence_found": 0.8}}
    assert ge.compare_graph(before, after_better)["verdict"] == "IMPROVED"
    assert ge.compare_graph(before, after_mixed)["verdict"] == "REGRESSED"
    assert ge.compare_graph(before, before)["verdict"] == "NOISE"


def test_measure_reads_the_real_fixture_without_llm():
    art = ge.load_artifacts(ROOT / "fixtures" / "live_qa_run.json")
    s = ge.measure(art)
    assert s["nodes"] > 0 and 0 <= s["slide_coverage"] <= 1
    assert "align" in s and s["align"]["items"] > 0


def test_stage_graph_drops_stale_alignment(monkeypatch):
    """--stage graph 면 저장된 정합(옛 node_id)을 버린다 — 새 그래프와 맞춰 재면 거짓 숫자다."""
    art = ge.load_artifacts(ROOT / "fixtures" / "live_qa_run.json")
    fake_graph = ConceptGraph.from_dict(art["concept_graph"])
    import chuckchuck
    monkeypatch.setattr(chuckchuck, "extract_concepts", lambda *a, **k: "concept_doc")
    monkeypatch.setattr(chuckchuck, "build_graph", lambda *a, **k: fake_graph)
    monkeypatch.setattr(chuckchuck, "align_speech", lambda *a, **k: (_ for _ in ()).throw(AssertionError("align 은 안 불러야 한다")))
    import chuckchuck.providers.llm_impl as impl
    class _Stub:
        name = "stub"
        def complete(self, **k): return "{}"
    monkeypatch.setattr(impl, "get_llm", lambda *a, **k: _Stub())
    class _CD:  # concept_doc 흉내 — to_dict 만 있으면 된다
        def to_dict(self): return {}
    monkeypatch.setattr(chuckchuck, "extract_concepts", lambda *a, **k: _CD())
    out, calls = ge.rebuild(art, None, stage="graph")
    assert "alignment_doc" not in out and "concept_graph" in out
    s = ge.measure(out)
    assert "align" not in s
