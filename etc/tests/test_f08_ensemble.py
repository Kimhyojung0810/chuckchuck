"""
네 모델 Q&A 앙상블(f08_ensemble · _ens_slots) — 가짜 엔진으로 흐름과 규율만 본다 (실 API 실험은 etc/bench/qa_ensemble_bench.py).

- 슬롯: 루트(thesis) P1 이 맨 앞 · 참고문헌·그림 캡션 노드는 안 묻는다 · 한 패턴이 슬롯을 다 먹지 않는다
- 거르기: 미시 확인 · 가리킬 게 없는 지시어 · 반말 · 이중 질문은 **버린다**(템플릿으로 바꾸지 않는다)
- 서로 평가: 작성자를 가린다(K01…) · 자기 후보 표는 점수에서 뺀다
- 1·2번: LLM 없이 · 다른 노드 · P1/P2 하나 이상 · 음성 후보가 없으면 묶음에서 대신 낸다
"""
from __future__ import annotations

import json
import re

from pipeline import _ens_slots as ES
from pipeline import f08_ensemble as FE
from pipeline.contracts import ConceptGraph, ConceptNode, Slide, SlideBlock, SlideDoc
from pipeline.providers.llm_base import LLMProvider


def _slide(no: int, text: str, title: str) -> Slide:
    return Slide(slide_no=no, title=title, blocks=[SlideBlock(category="paragraph", text=t) for t in text.split("\n")])


def deck():
    slides = [
        _slide(1, "급속충전은 배터리 수명을 깎는가\n2C 충전은 500 사이클에서 용량의 4분의 1을 깎았다", "급속충전"),
        _slide(2, "실험 설계\n충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었다\n셀 24개를 3수준 × 2수준에 4개씩 배정했다", "설계"),
        _slide(3, "결과\n2C 충전 후 유지율은 76%였다\n온도를 45도로 올리면 유지율이 더 떨어졌다", "결과"),
        _slide(4, "한계\n가속 조건에서 나온 값이라 실사용과는 다르다\nLeroy (2009) Why is it so hard", "한계"),
    ]
    nodes = [
        ConceptNode(id="root", label="2C 충전은 500 사이클에서 용량의 4분의 1을 깎았다", slide_nos=[1, 3], kind="thesis", weight=1.0),
        ConceptNode(id="design", label="충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었다", slide_nos=[2], kind="claim",
                    parent_id="root", depth=2, weight=0.6),
        ConceptNode(id="limit", label="가속 조건에서 나온 값이라 실사용과는 다르다", slide_nos=[4], kind="claim", parent_id="root",
                    depth=2, weight=0.5),
        ConceptNode(id="ref", label="Leroy (2009)", slide_nos=[4], kind="concept", parent_id="limit", depth=3, weight=0.3),
    ]
    graph = ConceptGraph(file_name="a.pptx", total_slides=4, nodes=nodes)
    return graph, SlideDoc(file_name="a.pptx", total_slides=4, slides=slides)


class FakeGen(LLMProvider):
    """슬롯마다 같은 꼴의 후보를 쓰는 가짜 생성 모델 + 서로 평가(모든 후보 4점) + 고르기(첫 후보)."""

    def __init__(self, name: str, question: str = "{label}이라는 결론은 왜 그렇게 나왔나요?"):
        self.name = name
        self.q = question
        self.users: list[str] = []

    def complete(self, *, system: str, user: str, **kw) -> str:
        self.users.append(user)
        if "[TASK] qa-ensemble-generate" in user:
            items = []
            for m in re.finditer(r"^(T\d+) · P\d+ .*?대상: 「([^」]+)」.*?관련 줄: ([^\n]*)", user, re.M):
                ref = m.group(3).split(",")[0].strip()
                items.append({"slot": m.group(1), "question": self.q.format(label=m.group(2)[:20]),
                              "answer": "충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었기 때문이에요.", "lines": [ref]})
            return json.dumps({"items": items}, ensure_ascii=False)
        if "[TASK] qa-ensemble-peer-review" in user:
            ids = re.findall(r"^(K\d+) ", user, re.M)
            return json.dumps({"scores": [{"id": k, "core": 4, "grounded": 5, "specific": 4, "clear": 5, "answer_ok": True}
                                          for k in ids]})
        if "[TASK] qa-ensemble-pick" in user:
            return json.dumps({"pick": "C1", "reason": "핵심 논리를 묻는 질문이에요."}, ensure_ascii=False)
        return "{}"


def test_슬롯은_루트_P1_이_먼저이고_참고문헌_노드는_안_묻는다():
    graph, sd = deck()
    d = FE.Deck.build(graph, sd)
    slots = ES.build_slots(graph, None, d.slides, d.lines, d.idx)
    assert slots[0].pattern == "P1" and slots[0].node_id == "root"
    assert all(s.node_id != "ref" for s in slots)
    assert len({(s.node_id, s.pattern) for s in slots}) == len(slots)
    assert ES.path_to_root(graph, "limit") == [graph.nodes[2].label, graph.nodes[0].label]


def test_거르기는_미시_지시어_반말_이중질문을_버린다():
    graph, sd = deck()
    d = FE.Deck.build(graph, sd)
    slot = ES.build_slots(graph, None, d.slides, d.lines, d.idx)[0]
    kw = dict(lines_by_id=d.lines_by_id, idx=d.idx, deck_tokens=d.deck_tokens, sources=d.sources)
    base = {"answer": "충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었기 때문이에요.", "lines": [slot.lines[0]]}
    assert "micro" in ES.check_candidate({**base, "question": "2C 충전 후 유지율은 몇 %였나요?"}, slot, **kw)[1]
    assert "vague_deixis" in ES.check_candidate({**base, "question": "이 조건이 결론을 바꾸나요?"}, slot, **kw)[1]
    assert "impolite" in ES.check_candidate({**base, "question": "2C 충전이 왜 용량을 깎았는가?"}, slot, **kw)[1]
    assert "multi_ask" in ES.check_candidate({**base, "question": "2C 충전은 왜 깎았나요? 온도는요?"}, slot, **kw)[1]
    ok, why = ES.check_candidate({**base, "question": "2C 충전이 용량을 깎았다는 결론은 충전 속도만 바꾼 설계로 충분히 받쳐지나요?"},
                                 slot, **kw)
    assert ok is not None and not why


def test_묶음_서로평가_가림과_자기표_빼기(monkeypatch):
    graph, sd = deck()
    llms = {n: FakeGen(n) for n in ("solar", "ax")}
    pool = FE.build_pool(graph, sd, models=["solar", "ax"], llms=llms, peer_self=True)
    assert pool.candidates and not any(d["reasons"] == ["skipped"] for d in pool.dropped)
    peer_users = [u for l in llms.values() for u in l.users if "peer-review" in u]
    assert peer_users and all("solar" not in u.split("## 질문 후보")[1] for u in peer_users)   # 작성자 이름이 안 실린다
    c = pool.candidates[0]
    assert any(s["self"] for s in c["peer_scores"]) and FE.peer_score(c["peer_scores"]) == FE.peer_score(
        [s for s in c["peer_scores"] if not s["self"]])


def test_1_2번은_LLM_없이_다른_노드_P1P2_포함_그리고_대신_내기():
    graph, sd = deck()
    llms = {n: FakeGen(n) for n in ("solar", "ax")}
    pool = FE.build_pool(graph, sd, models=["solar", "ax"], llms=llms)
    opening = FE.pick_opening(pool)
    assert len(opening) == 2 and opening[0]["node_id"] != opening[1]["node_id"]
    assert any(o["pattern"] in ("P1", "P2") for o in opening)
    nxt = FE.choose_next(pool, None, [{"question": o["question"], "node_id": o["node_id"]} for o in opening])
    assert nxt.get("substituted") is True
    q = FE.to_question(opening[0], 1)
    assert q.answer_gist and q.basis is not None and "ensemble" in q.basis.checks


def test_꺼져_있으면_기본값은_0(monkeypatch):
    monkeypatch.delenv("QA_ENSEMBLE", raising=False)
    assert FE.enabled() is False
    monkeypatch.setenv("QA_ENSEMBLE", "1")
    assert FE.enabled() is True


def test_모범답_정리_대상은_지저분한_골자만():
    from pipeline.contracts import Question

    dirty = Question(id="q1", node_id="a", label="a", question="왜요?",
                     answer_gist="자료는 이렇게 말해요 — 1 군당 셀이 4개뿐이다 · 한계: 그래서 / 다음 단계 (4장)")
    clean = Question(id="q2", node_id="a", label="a", question="왜요?", answer_gist="가속 조건이라 실사용과 달라요.")
    assert FE.dirty_gist(dirty) and not FE.dirty_gist(clean)
