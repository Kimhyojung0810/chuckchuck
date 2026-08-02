"""
F-06 배치 병렬 호출을 고정합니다.

실측(12장·실 Solar)에서 배치 2개를 순차로 돌려 150초가 걸렸습니다.
배치는 서로 독립이라 동시에 띄울 수 있는데, 병렬로 바꾸면서 지켜야 할 것이
둘 있습니다 — 결과가 호출 순서에 흔들리지 않을 것, 그리고 한 배치가 실패하면
조용히 빠지지 말 것(개념이 비면 F-07 그래프에 구멍이 나고 F-11 이 오판한다).
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from chuckchuck.contracts import ConceptError, Context, Slide, SlideBlock, SlideDoc
from chuckchuck.f06_concepts import extract_concepts
from chuckchuck.providers.llm_base import LLMProvider


def make_doc(n_slides: int) -> SlideDoc:
    return SlideDoc(
        file_name="deck.pdf",
        total_slides=n_slides,
        slides=[
            Slide(
                slide_no=i,
                title=f"슬라이드 {i}",
                blocks=[SlideBlock(category="paragraph", text=f"{i}번 내용")],
                total_char_count=20,
            )
            for i in range(1, n_slides + 1)
        ],
    )


class SlowLLM(LLMProvider):
    """배치마다 잠깐 자면서 동시 실행 수를 기록하는 가짜 LLM."""

    name = "slow-fake"

    def __init__(self, delay: float = 0.25):
        self.delay = delay
        self._lock = threading.Lock()
        self.live = 0
        self.max_live = 0
        self.calls = 0

    def complete(self, *, system: str, user: str, **kwargs) -> str:
        with self._lock:
            self.calls += 1
            self.live += 1
            self.max_live = max(self.max_live, self.live)
        try:
            time.sleep(self.delay)
        finally:
            with self._lock:
                self.live -= 1
        # 프롬프트에 적힌 슬라이드 번호만 돌려준다 (배치 계약 그대로)
        nos = [
            int(line.split("슬라이드 ")[1].split(":")[0])
            for line in user.splitlines()
            if line.startswith("### 슬라이드 ")
        ]
        return json.dumps({"slides": [
            {"slide_no": n, "title": f"슬라이드 {n}", "topic": f"주제{n}",
             "keywords": [f"kw{n}"], "concepts": [f"개념{n}: 설명"], "importance": "core"}
            for n in nos
        ]}, ensure_ascii=False)


def test_배치가_동시에_돈다():
    """순차였다면 max_live 가 1 을 넘지 못한다."""
    llm = SlowLLM()
    doc = make_doc(24)  # batch_size=8 → 배치 3개
    extract_concepts(doc, Context(), llm=llm, batch_size=8)
    assert llm.calls == 3
    assert llm.max_live > 1


def test_병렬이어도_모든_슬라이드가_다_들어온다():
    doc = make_doc(24)
    out = extract_concepts(doc, Context(), llm=SlowLLM(delay=0.01), batch_size=8)
    assert [s.slide_no for s in out.slides] == list(range(1, 25))
    assert all(s.concepts for s in out.slides)


def test_배치가_하나면_스레드를_안_쓴다():
    llm = SlowLLM(delay=0.01)
    extract_concepts(make_doc(5), Context(), llm=llm, batch_size=8)
    assert llm.calls == 1
    assert llm.max_live == 1


class FlakyLLM(SlowLLM):
    """두 번째 배치만 깨진 응답을 주는 가짜 LLM."""

    def complete(self, *, system: str, user: str, **kwargs) -> str:
        if "배치 2/" in user:
            return "이건 JSON 이 아니다"
        return super().complete(system=system, user=user, **kwargs)


def test_한_배치가_실패하면_조용히_넘어가지_않는다():
    """개념이 빠진 채 흘러가면 F-07 그래프에 구멍이 나고 F-11 이 '누락' 으로 오판한다."""
    with pytest.raises(ConceptError):
        extract_concepts(make_doc(24), Context(), llm=FlakyLLM(delay=0.01), batch_size=8)


def test_결과가_호출_순서에_흔들리지_않는다():
    """배치가 끝나는 순서는 매번 달라도 출력은 같아야 한다."""
    doc = make_doc(24)
    runs = [
        [(s.slide_no, s.topic) for s in
         extract_concepts(doc, Context(), llm=SlowLLM(delay=0.01), batch_size=8).slides]
        for _ in range(3)
    ]
    assert runs[0] == runs[1] == runs[2]
