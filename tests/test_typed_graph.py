"""
종류 있는 개념 추출(F-06) → 자료 구조 뼈대 그래프(F-07) 회귀 테스트 (2026-10-01).
docs/review/2026-10-01_개념그래프_일반원인 의 실패를 하나씩 재현한다:
질문 루트 · 수치/조건 루트 · F-06 항목 누락 · 앞 장 사슬 위계 · 억지 연결 · 다른 장 문장 끌어오기 · 깨진 주장 줄임.
"""

from __future__ import annotations

import json

from chuckchuck import _typed_graph as TG
from chuckchuck.contracts import ConceptDoc, SlideConcepts, SlideDoc, Transcript
from chuckchuck.f06_concepts import _typed_slide, headline, is_claim_sentence
from chuckchuck.f07_graph import build_graph
from chuckchuck.providers.llm_base import LLMProvider


class ScriptedLLM(LLMProvider):
    """뼈대 판단 응답을 정해 둔 가짜 LLM — 호출 수를 센다."""

    def __init__(self, reply: dict | str):
        self.reply = reply
        self.calls = 0

    @property
    def name(self) -> str:
        return "scripted"

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False) -> str:
        self.calls += 1
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply, ensure_ascii=False)


# 반찬 IR 꼴의 작은 덱 — 표지 비교 주장 · 문제 목록 · 해결 · 파일럿 수치 · 상세 장
RAW = {
    1: "한끼곳간\n동네 반찬 정기구독\n구독자 수보다 중요한 월 반복 매출",
    2: "수익성을 가로막는 세 가지 문제\n① 높은 배송비\n② 반찬 폐기 손실\n세 문제가 모두 공헌이익을 깎습니다.",
    3: "해결책\n권역 묶음 배송 — 같은 아파트 단지 주문을 한 번에 배송해 배송비를 낮춥니다.",
    4: "파일럿 결과 (성수동 3개 단지, 12주)\n묶음 배송 도입 후 건당 배송비가 3,200원에서 1,900원으로 41% 줄었습니다.",
    5: "원인 상세\n높은 배송비 — 주문이 흩어져 차량이 빈 채로 돈다",
}


def _slide(no, title, kind, claims, concepts, evidence=(), of=None):
    return SlideConcepts(slide_no=no, title=title, topic="", concepts=list(concepts), raw_text=RAW[no],
                         title_kind=kind, claims=list(claims), evidence=list(evidence), concept_of=dict(of or {}))


def make_doc() -> ConceptDoc:
    return ConceptDoc(file_name="ir.pdf", total_slides=5, slides=[
        _slide(1, "한끼곳간", "topic", ["구독자 수보다 중요한 월 반복 매출"], ["월 반복 매출: 매달 반복되는 매출"]),
        _slide(2, "수익성을 가로막는 세 가지 문제", "topic", ["세 문제가 모두 공헌이익을 깎습니다."],
               ["높은 배송비", "반찬 폐기 손실", "공헌이익: 매출에서 변동비를 뺀 이익"],
               of={"높은 배송비": "공헌이익"}),
        _slide(3, "해결책", "topic", ["권역 묶음 배송 — 같은 아파트 단지 주문을 한 번에 배송해 배송비를 낮춥니다."],
               ["권역 묶음 배송: 같은 단지 주문을 한 번에"]),
        _slide(4, "파일럿 결과", "topic", ["묶음 배송 도입 후 건당 배송비가 3,200원에서 1,900원으로 41% 줄었습니다."],
               ["건당 배송비"], evidence=["성수동 3개 단지, 12주", "건당 배송비 3,200원 → 1,900원"]),
        _slide(5, "원인 상세", "topic", ["높은 배송비 — 주문이 흩어져 차량이 빈 채로 돈다"], ["높은 배송비", "빈 차량 운행"]),
    ])


def make_slidedoc() -> SlideDoc | None:
    return None                                    # weight 는 거칠게 — 구조만 본다


def _graph(reply):
    llm = ScriptedLLM(reply)
    return build_graph(make_doc(), {}, slide_doc=make_slidedoc(), llm=llm), llm


def _by_label(g):
    return {n.label: n for n in g.nodes}


# --- 루트 ---------------------------------------------------------------------------------------

def test_root_is_single_claim_from_candidates_not_question():
    g, _ = _graph({"thesis_from": "c1.1", "slides": [], "links": [], "sections": []})
    assert len(g.roots) == 1
    root = g.roots[0]
    assert root.kind == "thesis" and root.label == "구독자 수보다 중요한 월 반복 매출"
    assert g.thesis == root.id


def test_numbers_and_conditions_never_become_nodes():
    """반찬 IR 옛 그래프: 「성수동」「3개 단지」「12주」 가 루트였다. 이제 근거로 노드에 붙는다."""
    g, _ = _graph({"thesis_from": "c1.1"})
    labels = {n.label for n in g.nodes}
    assert not labels & {"성수동", "3개 단지", "12주", "성수동 3개 단지, 12주"}
    pilot = next(n for n in g.nodes if n.label.startswith("묶음 배송 도입 후"))
    attached = {e for n in g.nodes for e in n.evidence}
    assert "성수동 3개 단지, 12주" in attached
    assert "건당 배송비 3,200원 → 1,900원" in _by_label(g)["건당 배송비"].evidence  # 이름을 부르는 근거는 그 개념에
    assert pilot.kind == "claim"


def test_long_composed_thesis_is_not_chopped_into_broken_sentence():
    """10-01: 80자 넘는 thesis_claim 을 「주어 + 마지막 마디」 로 잘라 「별점은 4.7은 …」 같은 비문이 루트가 됐다."""
    long = "별점은 " + "리뷰 수집 방식과 이벤트 운영과 플랫폼 노출 방식이 함께 만든 결과로서 " * 3 + "4.7에 몰린다"
    g, _ = _graph({"thesis_from": None, "thesis_claim": long})
    assert g.roots[0].label == "구독자 수보다 중요한 월 반복 매출"     # 자르지 않고 후보로 물러선다


# --- 누락 없음 ------------------------------------------------------------------------------------

def test_every_f06_item_is_in_graph():
    doc = make_doc()
    g = build_graph(doc, {}, slide_doc=make_slidedoc(), llm=ScriptedLLM({"thesis_from": "c1.1"}))
    cov = TG.coverage(doc, g.nodes)
    assert cov["total"] > 0 and cov["lost"] == 0, cov["missing"]


def test_structure_call_failure_still_gives_full_single_root_graph():
    g, llm = _graph("이건 JSON 이 아니다")
    assert llm.calls == 2                          # 한 번 다시 묻고
    assert "skeleton" in g.degraded                # 깨졌다고 적고
    assert len(g.roots) == 1 and TG.coverage(make_doc(), g.nodes)["lost"] == 0


# --- 위계 ---------------------------------------------------------------------------------------

def test_slide_chain_parents_without_textual_basis_are_rejected():
    """10-01 수익률격차: 모델이 장마다 바로 앞 장 주장을 부모로 적어 7단 사슬이 됐다."""
    g, _ = _graph({"thesis_from": "c1.1",
                   "slides": [{"slide_no": 3, "parent": "c2.1"}, {"slide_no": 4, "parent": "c3.1"}]})
    by = _by_label(g)
    root = g.roots[0].id
    assert by["권역 묶음 배송 — 같은 아파트 단지 주문을 한 번에 배송해 배송비를 낮춥니다."].parent_id == root
    assert by["묶음 배송 도입 후 건당 배송비가 3,200원에서 1,900원으로 41% 줄었습니다."].parent_id == root


def test_detail_slide_headline_nests_under_earlier_concept():
    """「X — 주장」 헤드라인은 앞 장 개념 X 를 푸는 장이다 (수익률격차 「과잉 매매 — …」 → 「과잉 매매」 밑)."""
    g, _ = _graph({"thesis_from": "c1.1"})
    by = _by_label(g)
    detail = by["높은 배송비 — 주문이 흩어져 차량이 빈 채로 돈다"]
    assert detail.parent_id == by["높은 배송비"].id
    assert by["빈 차량 운행"].parent_id == detail.id
    assert 5 in by["높은 배송비"].slide_nos           # 같은 개념은 장을 넘어 한 노드


def test_concept_of_inside_slide_is_kept():
    g, _ = _graph({"thesis_from": "c1.1"})
    by = _by_label(g)
    assert by["높은 배송비"].parent_id == by["공헌이익"].id
    assert by["공헌이익"].parent_id == by["세 문제가 모두 공헌이익을 깎습니다."].id


# --- 연결 ---------------------------------------------------------------------------------------

def test_links_need_reason_and_different_slides_and_no_backfill_call():
    g, llm = _graph({"thesis_from": "c1.1", "links": [
        {"from": "k3.1", "to": "k4.1"},                                  # 근거 표현 없음 → 버림
        {"from": "k2.1", "to": "k2.2", "why": "같은 장"},                  # 같은 장 → 버림
        {"from": "k3.1", "to": "k1.1", "why": "묶음 배송이 월 반복 매출을 지킨다"},  # 받음
    ]})
    by = _by_label(g)
    pairs = {frozenset((e.from_id, e.to_id)) for e in g.relates_edges}
    assert frozenset((by["권역 묶음 배송"].id, by["월 반복 매출"].id)) in pairs
    assert frozenset((by["권역 묶음 배송"].id, by["건당 배송비"].id)) not in pairs
    assert frozenset((by["높은 배송비"].id, by["반찬 폐기 손실"].id)) not in pairs
    assert llm.calls == 1                          # 연결 개수를 채우려 또 묻지 않는다


def test_solution_sentence_links_to_problem_concept_by_rule():
    g, _ = _graph({"thesis_from": "c1.1"})
    by = _by_label(g)
    sol = by["권역 묶음 배송 — 같은 아파트 단지 주문을 한 번에 배송해 배송비를 낮춥니다."]
    pairs = {frozenset((e.from_id, e.to_id)) for e in g.relates_edges}
    assert frozenset((sol.id, by["높은 배송비"].id)) in pairs


def test_relates_never_duplicate_hierarchy():
    g, _ = _graph({"thesis_from": "c1.1", "links": [{"from": "c2.1", "to": "k2.3", "why": "x"}]})
    parent = {n.id: n.parent_id for n in g.nodes}

    def anc(i):
        out = set()
        while parent.get(i):
            i = parent[i]
            out.add(i)
        return out
    for e in g.relates_edges:
        assert e.from_id not in anc(e.to_id) and e.to_id not in anc(e.from_id)


# --- F-06 종류 다시 검사 --------------------------------------------------------------------------

def test_f06_moves_noun_phrase_claims_and_figures_and_drops_foreign_sentences():
    raw = RAW[2]
    got = {"claims": ["높은 배송비", "세 문제가 모두 공헌이익을 깎습니다.",
                      "묶음 배송 도입 후 건당 배송비가 3,200원에서 1,900원으로 41% 줄었습니다."],   # 마지막은 다른 장 문장
           "concepts": [{"name": "12주", "desc": "기간"}, {"name": "분석 기간", "desc": "2024.1~2025.6"},
                        {"name": "Ward, Duke (2017)", "desc": "연구"}, {"name": "공헌이익", "desc": "이익"}]}
    out = _typed_slide(got, "수익성을 가로막는 세 가지 문제", raw)
    assert out["claims"] == ["세 문제가 모두 공헌이익을 깎습니다."]
    assert "높은 배송비" in out["concepts"]
    names = [c.partition(":")[0] for c in out["concepts"]]
    assert "12주" not in names and "분석 기간" not in names and not any("Ward" in n for n in names)
    assert any(e.startswith("12주") for e in out["evidence"]) and any("Ward" in e for e in out["evidence"])


def test_f06_headline_is_first_claim_verbatim():
    out = _typed_slide({"claims": ["예외 없는 단조 감소"]}, "원인 상세",
                       "원인 상세\n01. 과잉 매매 — 거래를 늘릴수록 성과가 낮아졌다\n예외 없는 단조 감소")
    assert out["claims"][0] == "과잉 매매 — 거래를 늘릴수록 성과가 낮아졌다"
    assert "과잉 매매" in [c.partition(":")[0] for c in out["concepts"]]


def test_headline_ignores_list_items_and_spaced_kickers():
    assert headline("오해와 사실\n자주 나오는 세 가지 오해\n오해\n공부하면 시장을 이길 수 있다") == ("", "")
    assert headline("경 영 정 보 학 과 서 비 스 데 이 터 · 2 0 2 6 . 1 0 . 6 .\n별점은 왜 4.7에 몰리는가", cover=True) == ("", "")
    assert headline("결과\n4.7은 품질이 아니라 리뷰 수집 방식의 결과다")[0] == "4.7은 품질이 아니라 리뷰 수집 방식의 결과다"


def test_question_title_is_not_a_claim():
    assert not is_claim_sentence("개인 투자자는 왜 시장을 이기지 못하는가")
    assert is_claim_sentence("수면 시간보다 중요한 수면의 질")
    out = _typed_slide({"claims": ["개인 투자자는 왜 시장을 이기지 못하는가"]}, "개인 투자자는 왜 시장을 이기지 못하는가",
                       "개인 투자자는 왜\n시장을 이기지 못하는가")
    assert out["claims"] == [] and out["title_kind"] == "question"


# --- 옛 저장본 · F-11 --------------------------------------------------------------------------

def test_old_untyped_doc_is_not_typed():
    doc = ConceptDoc.from_dict({"file_name": "x", "total_slides": 1,
                                "slides": [{"slide_no": 1, "title": "t", "topic": "", "concepts": ["a: b"]}]})
    assert not TG.is_typed(doc)
    assert "claims" not in doc.slides[0].to_dict()          # 옛 모양 그대로 직렬화


def test_claim_nodes_are_counted_as_mentioned_by_sentence():
    from chuckchuck.f11_align import _speech_bases
    g, _ = _graph({"thesis_from": "c1.1"})
    tr = Transcript.from_dict({"full_text": "세 가지 문제가 모두 공헌이익을 깎아요. 그래서 묶음 배송을 했습니다.",
                               "by_slide": [{"slide_no": 2, "start_sec": 0, "end_sec": 5,
                                             "text": "세 가지 문제가 모두 공헌이익을 깎아요. 그래서 묶음 배송을 했습니다."}]})
    bases = _speech_bases(g, tr, None)
    claim = _by_label(g)["세 문제가 모두 공헌이익을 깎습니다."]
    assert bases[claim.id].mention_count >= 1
