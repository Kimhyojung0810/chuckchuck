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
    assert "건당 배송비 3,200원 → 1,900원" in pilot.evidence      # 근거는 낱말이 겹치는 그 장 주장에
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
    """10-01 수익률격차: 모델이 장마다 바로 앞 장 주장을 부모로 적어 7단 사슬이 됐다. 이제 주장의 부모는 그 문장이 부르는 개념이다."""
    g, _ = _graph({"thesis_from": "c1.1",
                   "slides": [{"slide_no": 3, "parent": "c2.1"}, {"slide_no": 4, "parent": "c3.1"}]})
    by = _by_label(g)
    sol = by["권역 묶음 배송 — 같은 아파트 단지 주문을 한 번에 배송해 배송비를 낮춥니다."]
    pilot = by["묶음 배송 도입 후 건당 배송비가 3,200원에서 1,900원으로 41% 줄었습니다."]
    assert sol.parent_id == by["권역 묶음 배송"].id
    assert pilot.parent_id == by["건당 배송비"].id


def test_layers_concept_over_claim_over_evidence():
    """10-02 사용자: 그래프만 보고 「핵심 개념 → 하위 개념 → 주장 → 근거」 가 읽혀야 한다 — 주장 밑에 개념·주장이 오지 않는다."""
    g, _ = _graph({"thesis_from": "c1.1", "slides": [{"slide_no": 4, "parent": "c3.1"}]})
    by = {n.id: n for n in g.nodes}
    for n in g.nodes:
        if n.parent_id:
            assert by[n.parent_id].kind != "claim", f"{n.label} 가 주장 밑"
    assert any(n.evidence for n in g.nodes if n.kind == "claim")


def test_detail_slide_headline_nests_under_earlier_concept():
    """「X — 주장」 헤드라인은 앞 장 개념 X 를 푸는 장이다 (수익률격차 「과잉 매매 — …」 → 「과잉 매매」 밑)."""
    g, _ = _graph({"thesis_from": "c1.1"})
    by = _by_label(g)
    detail = by["높은 배송비 — 주문이 흩어져 차량이 빈 채로 돈다"]
    assert detail.parent_id == by["높은 배송비"].id
    assert by["빈 차량 운행"].parent_id == by["높은 배송비"].id   # 그 장 중심 개념(높은 배송비) 밑 하위 개념
    assert 5 in by["높은 배송비"].slide_nos           # 같은 개념은 장을 넘어 한 노드


def test_concept_of_inside_slide_is_kept():
    g, _ = _graph({"thesis_from": "c1.1"})
    by = _by_label(g)
    assert by["높은 배송비"].parent_id == by["공헌이익"].id
    assert by["세 문제가 모두 공헌이익을 깎습니다."].parent_id == by["공헌이익"].id   # 주장은 문장이 부르는 개념 밑


# --- 연결 ---------------------------------------------------------------------------------------

def test_links_need_reason_and_different_slides_and_no_backfill_call():
    g, llm = _graph({"thesis_from": "c1.1", "links": [
        {"from": "k3.1", "to": "k4.1"},                                  # 근거 표현 없음 → 버림
        {"from": "k2.1", "to": "k2.2", "why": "같은 장"},                  # 같은 장 → 버림
        {"from": "k3.1", "to": "k1.1", "why": "묶음 배송이 월 반복 매출을 지킨다"},  # 근거 표현이 원문에 없음 → 버림
        {"from": "k3.1", "to": "k2.1", "why": "한 번에 배송해 배송비를 낮춥니다"},     # 받음
    ]})
    by = _by_label(g)
    pairs = {frozenset((e.from_id, e.to_id)) for e in g.relates_edges}
    assert frozenset((by["권역 묶음 배송"].id, by["월 반복 매출"].id)) not in pairs
    assert frozenset((by["권역 묶음 배송"].id, by["높은 배송비"].id)) in pairs
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
    raw = RAW[2] + "\n12주 · 분석 기간 2024.1~2025.6 · Ward, Duke (2017)"
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


# --- 다수결 (10-02 재현성) ------------------------------------------------------------------------

def _sc(concepts, claims, of=None, evidence=()):
    return SlideConcepts(slide_no=1, title="t", topic="", concepts=list(concepts), raw_text="", title_kind="topic",
                         claims=list(claims), evidence=list(evidence), concept_of=dict(of or {}))


def test_vote_keeps_majority_nodes_and_moves_minority_to_evidence():
    from chuckchuck.f06_concepts import vote_slides
    runs = [[_sc(["별점 구간: 구간", "리뷰 비중: 비중"], ["4.7은 품질이 아니라 수집 방식의 결과다"], {"리뷰 비중": "별점 구간"})],
            [_sc(["별점 구간: 구간", "리뷰 비중"], ["4.7은 품질이 아니라 수집 방식의 결과다", "덧붙인 주장이다"], {"리뷰 비중": "별점 구간"})],
            [_sc(["별점 구간별 리뷰 비중: 한 덩어리"], ["4.7은 품질이 아니라 수집 방식의 결과다"])]]
    out = vote_slides(runs)[0]
    assert [c.partition(":")[0] for c in out.concepts] == ["별점 구간", "리뷰 비중"]
    assert out.concept_of == {"리뷰 비중": "별점 구간"}
    assert out.claims == ["4.7은 품질이 아니라 수집 방식의 결과다"]
    assert "별점 구간별 리뷰 비중: 한 덩어리" in out.evidence and "덧붙인 주장이다" in out.evidence   # 버리지 않는다


def test_vote_structure_takes_majority_thesis_and_links():
    runs = [{"thesis_from": "c2.1", "links": [{"from": "k1.1", "to": "k3.1", "why": "a"}], "slides": [{"slide_no": 3, "parent": "k1.1"}]},
            {"thesis_from": "c2.1", "links": [{"from": "k3.1", "to": "k1.1", "why": "b"}], "slides": [{"slide_no": 3, "parent": "thesis"}]},
            {"thesis_from": "c1.1", "links": [{"from": "k2.1", "to": "k3.1", "why": "c"}], "slides": [{"slide_no": 3, "parent": "k1.1"}]}]
    v = TG.vote_structure(runs)
    assert v["thesis_from"] == "c2.1"
    assert [frozenset((x["from"], x["to"])) for x in v["links"]] == [frozenset(("k1.1", "k3.1"))]
    assert v["slides"] == [{"slide_no": "3", "parent": "k1.1"}]


def test_extract_concepts_votes_three_times_in_parallel(monkeypatch):
    from chuckchuck import f06_concepts as F6
    monkeypatch.setenv("CHUCKCHUCK_CONCEPT_VOTES", "3")
    replies = iter([{"slides": [{"slide_no": 1, "concepts": ["공헌이익: 이익", "배송비"]}]},
                    {"slides": [{"slide_no": 1, "concepts": ["공헌이익: 이익"]}]},
                    {"slides": [{"slide_no": 1, "concepts": ["공헌이익: 이익", "배송비"]}]}])

    class Seq(ScriptedLLM):
        def complete(self, **kw):
            self.calls += 1
            return json.dumps(next(replies), ensure_ascii=False)
    sd = SlideDoc.from_dict({"file_name": "d", "total_slides": 1, "slides": [
        {"slide_no": 1, "title": "문제", "blocks": [{"category": "paragraph", "text": "공헌이익 배송비"}]}]})
    llm = Seq({})
    doc = F6.extract_concepts(sd, llm=llm)
    assert llm.calls == 3
    assert [c.partition(":")[0] for c in doc.slides[0].concepts] == ["공헌이익", "배송비"]


def test_f06_drops_evidence_and_descriptions_not_in_source():
    """10-02: 근거 열에 모델이 덧붙인 풀이(「공헌이익: 매출에서 변동비를 제외한 이익」)가 원문처럼 섰다."""
    out = _typed_slide({"claims": ["세 문제가 모두 공헌이익을 깎습니다."],
                        "concepts": [{"name": "공헌이익", "desc": "매출에서 변동비를 제외한 이익"}],
                        "evidence": ["배송비는 연간 2억 원의 적자를 만든다고 추정된다", "① 높은 배송비"]},
                       "수익성을 가로막는 세 가지 문제", RAW[2])
    assert "공헌이익" in out["concepts"]                                   # 이름은 원문에 있다 — 설명만 비운다
    assert out["evidence"] == ["① 높은 배송비"]
