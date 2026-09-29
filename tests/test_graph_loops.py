"""
F-07 반복 루프·겹친 이름 후처리 (WP-C2, 2026-09-30) — 프롬프트 갈래(예시 낱말·예시 id)가 달라도 결정적으로 접힌다.

09-29 graph_ab 한 실행은 같은 이름을 98번 되풀이한 113노드를 냈다. 여기서는 루프의 여러 꼴을 LLM 없이 넣는다:
같은 이름 되풀이(예시 id 를 따라 쓴 id·사슬 부모), 조사·띄어쓰기만 다른 이름, max_tokens 에 잘린 루프, 스키마 예시 이름 + 번호.
예시 id·이름 거르기(`_example_ids`·`_example_labels`)는 SYSTEM_PROMPT 를 따라가므로, 예시 id 를 바꾼 프롬프트에서도 같게 본다.
덱은 물류 합성 이름이다. LLM 은 전부 가짜다.
"""

import json

import pytest

from chuckchuck import _graph_items as GI
from chuckchuck import f07_graph as F7
from chuckchuck.contracts import ConceptDoc, Slide, SlideBlock, SlideConcepts, SlideDoc
from chuckchuck.providers.llm_base import LLMProvider


@pytest.fixture(autouse=True)
def _no_links_backfill(monkeypatch):
    monkeypatch.setattr(F7, "MIN_CROSS_RATIO", 0.0)


def _neutral_ids(prompt: str) -> str:
    """스키마 예시 id 를 다른 중립 id 로 — 갈래 I 처럼 예시 id 가 바뀐 프롬프트."""
    for k, old in enumerate(sorted(F7._example_ids())):
        prompt = prompt.replace(f'"{old}"', f'"slot-{chr(97 + k)}"')
    return prompt


PROMPTS = {"지금 프롬프트": lambda p: p, "예시 id 를 바꾼 프롬프트": _neutral_ids}


@pytest.fixture(params=list(PROMPTS))
def prompt(request, monkeypatch):
    monkeypatch.setattr(F7, "SYSTEM_PROMPT", PROMPTS[request.param](F7.SYSTEM_PROMPT))
    return request.param


class Raw(LLMProvider):
    name = "raw"

    def __init__(self, text: str):
        self.text = text

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False) -> str:
        return self.text


def _docs(n: int) -> tuple[ConceptDoc, SlideDoc]:
    cd = ConceptDoc(file_name="d.pptx", total_slides=n, model="mock", slides=[
        SlideConcepts(slide_no=i, title="", topic="", keywords=[], concepts=[f"개념{i}: 설명"], raw_text="본문",
                      importance="core") for i in range(1, n + 1)])
    sd = SlideDoc(file_name="d.pptx", total_slides=n, slides=[
        Slide(slide_no=i, title="", blocks=[SlideBlock(category="paragraph", text="본문")], total_char_count=2)
        for i in range(1, n + 1)])
    return cd, sd


def _node(i, label, slides, parent=None):
    return {"id": i, "label": label, "slide_nos": slides, "summary": "", "importance": "core", "parent": parent}


BASE = [_node("logi", "물류 혁신", [1]), _node("hub", "거점 통합", [2], "logi"), _node("route", "배송 경로", [3], "logi")]


def _build(payload, n: int = 4):
    cd, sd = _docs(n)
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return F7.build_graph(cd, slide_doc=sd, llm=Raw(text))


def _sound(g) -> None:
    """루프를 접은 뒤에도 그래프 불변식 — 이름 겹침 0, 제 조상이 되는 노드 0, 깊이 상한."""
    keys = [GI.label_keys(n.label)[1] for n in g.nodes]
    assert len(keys) == len(set(keys))
    by = {n.id: n for n in g.nodes}
    for n in g.nodes:
        seen, cur = {n.id}, n.parent_id
        while cur is not None:
            assert cur not in seen and cur in by
            seen.add(cur)
            cur = by[cur].parent_id
        assert n.depth <= F7.MAX_GRAPH_DEPTH


def test_같은_이름_98번_되풀이는_예시_id_를_따라_써도_한_노드로(prompt):
    copied = sorted(F7._example_ids())[0]
    loop = [_node(f"{copied}-{k}", "적재율", [4], "hub" if k == 0 else f"{copied}-{k - 1}") for k in range(98)]
    g = _build({"thesis": "logi", "nodes": BASE + loop, "edges": []})
    _sound(g)
    by = {n.label: n for n in g.nodes}
    assert len(g.nodes) == 4 and by["적재율"].parent_id == "hub"
    assert by["적재율"].id == GI.slug_id("적재율", set())          # 예시 id 는 뜻이 없다 — 이름에서 만든 안정 id


def test_조사_띄어쓰기만_다른_이름이_번갈아_되풀이돼도_한_노드(prompt):
    spell = ["거점 통합", "거점의 통합", "거점통합"]
    loop = [_node(f"h{k}", spell[k % 3], [2 + k % 2], "logi") for k in range(30)]
    g = _build({"thesis": "logi", "nodes": BASE + loop, "edges": []})
    _sound(g)
    assert [n.label for n in g.nodes] == ["물류 혁신", "거점 통합", "배송 경로"]
    assert {n.label: n for n in g.nodes}["거점 통합"].slide_nos == [2, 3]


def test_max_tokens_에_잘린_루프도_접히고_앞_노드는_남는다(prompt):
    loop = [_node(f"n{k}", "적재율", [4], "hub") for k in range(98)]
    full = json.dumps({"thesis": "logi", "nodes": BASE + loop, "edges": [], "sections": []}, ensure_ascii=False)
    g = _build(full[: int(len(full) * 0.6)])                          # 루프 가운데서 끊긴 응답
    _sound(g)
    assert [n.label for n in g.nodes] == ["물류 혁신", "거점 통합", "배송 경로", "적재율"]


def test_예시_이름에_번호를_붙인_루프는_자리표지로_빠지고_뒤_노드가_상한에_안_잘린다(prompt):
    placeholder = sorted(F7._example_labels())[0]
    loop = [_node(f"d{k}", f"{placeholder} {k}", [4], "hub") for k in range(1, 99)]
    tail = [_node("load", "적재율", [4], "hub"), _node("cost", "물류 비용", [4], "logi")]
    g = _build({"thesis": "logi", "nodes": BASE + loop + tail, "edges": []})
    _sound(g)
    assert [n.label for n in g.nodes] == ["물류 혁신", "거점 통합", "배송 경로", "적재율", "물류 비용"]


def test_번호가_붙은_진짜_단계_이름은_남는다(prompt):
    steps = [_node(f"s{k}", f"{k}단계", [4], "hub") for k in range(1, 6)]
    g = _build({"thesis": "logi", "nodes": BASE + steps, "edges": []})
    assert [n.label for n in g.nodes][3:] == [f"{k}단계" for k in range(1, 6)]
