"""
F-26 주장 그래프 — LLM 이 낸 주장 후보를 **자료 원문과 대조**해서만 남기는지, 뻔한 구조(식·「보다」)는
LLM 없이도 잡히는지 (2026-09-29 수면 덱: 1장 「수면 시간보다 중요한 수면의 질」 ↔ 4장 「수면의 질 = 시간 × 연속성 × 규칙성」).
"""
from __future__ import annotations

import json
import re

import pytest

from chuckchuck.contracts import (
    ClaimDoc,
    ConceptGraph,
    ConceptNode,
    Slide,
    SlideBlock,
    SlideDoc,
)
from chuckchuck.f26_claims import (
    build_claims,
    has_support,
    resolve_label,
    rule_compare,
    rule_compose,
    slide_lines,
    verify_quote,
)
from chuckchuck.providers.llm_base import LLMProvider


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, payload):
        self.payload = payload
        self.prompts: list[str] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.prompts.append(user)
        return self.payload if isinstance(self.payload, str) else json.dumps(self.payload, ensure_ascii=False)


class BrokenLLM(LLMProvider):
    name = "broken"

    def complete(self, **_):
        raise RuntimeError("연결 끊김")


def slide(no: int, *lines: str) -> Slide:
    return Slide(slide_no=no, title=lines[0], blocks=[SlideBlock(category="paragraph", text=t) for t in lines])


DECK = SlideDoc(
    file_name="sleep.pptx", total_slides=7,
    slides=[
        slide(1, "01 / 08", "수면의 질", "수면 시간보다 중요한 수면의 질", "5시간 미만", "7시간 이상"),
        slide(4, "충분히 자도 피곤한 진짜 이유", "수면의 질은 단순한 “시간”보다 넓은 개념입니다.",
              "수면의 질 =", "시간", "×", "연속성", "×", "규칙성"),
        slide(5, "자다가 깨는 대표적인 원인", "연속성을 끊는 요인은 생각보다 일상적입니다.",
              "| 카페인 | 오후·<br>저녁 섭취 |", "| 음주 | 수면 후반 각성 |"),
        slide(7, "수면의 질을 높이는 방법", "해결책은 4번 슬라이드의 세 가지 문제와 직접 연결됩니다.",
              "필요한 수면 시간 확보", "카페인·음주·빛·소음 줄이기", "일정한 기상 시간 유지로 규칙성을 지킵니다"),
    ],
)


def node(nid, label, slides, parent=None, weight=0.5):
    return ConceptNode(id=nid, label=label, slide_nos=slides, parent_id=parent, weight=weight,
                       depth=1 if parent is None else 2)


GRAPH = ConceptGraph(
    file_name="sleep.pptx", total_slides=7,
    nodes=[
        node("sq", "수면의 질", [1, 4], weight=1.0),
        node("time", "충분한 시간", [7], "sq", 0.4),
        node("cont", "연속성", [4, 5], "sq", 0.8),
        node("reg", "규칙성", [4, 7], "sq", 0.7),
        node("caf", "카페인", [5], "cont", 0.3),
        node("alc", "음주", [5], "cont", 0.3),
        node("fix", "일정한 기상", [7], "sq", 0.3),
    ],
)


# ---------------------------------------------------------------------------
# 순수 함수
# ---------------------------------------------------------------------------

def test_식_줄은_글상자마다_나뉘어도_한_줄로_잇는다():
    assert "수면의 질 = 시간 × 연속성 × 규칙성" in slide_lines(DECK.slides[1].raw_text)


def test_인용_대조는_공백_따옴표_표칸을_무시하고_지어낸_말은_버린다():
    raw4 = DECK.slides[1].raw_text
    assert verify_quote('수면의 질은 단순한 "시간"보다 넓은 개념입니다.', raw4)
    assert verify_quote("수면의질 = 시간×연속성×규칙성", raw4)
    assert verify_quote("음주 수면 후반 각성", DECK.slides[2].raw_text) == "음주 수면 후반 각성"
    assert verify_quote("| 음주 | 수면 후반 각성 |", DECK.slides[2].raw_text) == "음주 | 수면 후반 각성"
    assert verify_quote("수면의 질은 시간보다 훨씬 중요한 유일한 지표다", raw4) == ""
    assert verify_quote("시간", raw4) == ""              # 너무 짧다 — 어디에나 있다


def test_인용이_조사_하나_다르면_원문_쪽_줄을_남긴다():
    kept = verify_quote("해결책은 4번 슬라이드의 세 가지 문제와 직접 연결된다.", DECK.slides[3].raw_text)
    assert kept == "해결책은 4번 슬라이드의 세 가지 문제와 직접 연결됩니다."


def test_근거_표시는_수치_출처_연구_언급이_있을_때만():
    assert has_support("7시간 이상")
    assert has_support("응답자의 42%")
    assert has_support("Walker et al. (2017)")
    assert has_support("수면 연구에 따르면")
    assert not has_support("해결책은 4번 슬라이드의 세 가지 문제와 직접 연결됩니다.")  # 자료 안 참조는 수치가 아니다
    assert not has_support("01 / 08 카페인 오후 저녁 섭취")


def test_개념_이름_대조는_맞은편과_겹치는_낱말을_빼고_본다():
    assert resolve_label("수면의 질", GRAPH.nodes).id == "sq"
    assert resolve_label("“연속성”", GRAPH.nodes).id == "cont"
    # 「수면 시간」 의 「수면」 은 맞은편 「수면의 질」 에도 있다 — 변별 낱말 「시간」 으로 찾는다
    assert resolve_label("수면 시간", GRAPH.nodes, exclude="수면의 질").id == "time"
    assert resolve_label("시간", GRAPH.nodes, exclude="수면의 질").id == "time"
    assert resolve_label("스트레스", GRAPH.nodes) is None


def test_규칙_compose_와_compare_가_같은_시간_개념을_가리킨다():
    compose = rule_compose(GRAPH, DECK)
    assert [(c.kind, c.subject_id, c.object_ids) for c in compose] == [("compose", "sq", ["time", "cont", "reg"])]
    assert compose[0].evidence[0].slide_no == 4
    compare = rule_compare(GRAPH, DECK)
    assert {(c.subject_id, tuple(c.object_ids), c.evidence[0].slide_no) for c in compare} == {
        ("sq", ("time",), 1), ("sq", ("time",), 4),
    }


# ---------------------------------------------------------------------------
# build_claims
# ---------------------------------------------------------------------------

LLM_OUT = {"claims": [
    # 통과 — 원문 그대로
    {"slide_no": 5, "kind": "cause", "subject_id": "caf", "object_ids": ["cont"],
     "quote": "| 카페인 | 오후· 저녁 섭취 |", "text": "카페인이 연속성을 끊는다"},
    # 지어낸 인용 — 버린다
    {"slide_no": 5, "kind": "cause", "subject_id": "alc", "object_ids": ["cont"],
     "quote": "음주는 수면 효율을 30% 떨어뜨린다", "text": "음주가 연속성을 끊는다"},
    # 인용이 다른 장에 있다 — 그 장 원문에 없으면 버린다
    {"slide_no": 1, "kind": "solve", "subject_id": "fix", "object_ids": ["reg"],
     "quote": "일정한 기상 시간 유지로 규칙성을 지킵니다", "text": "기상 시간 고정이 규칙성을 해결한다"},
    # 그래프 밖 id — 버린다
    {"slide_no": 7, "kind": "solve", "subject_id": "ghost", "object_ids": ["reg"],
     "quote": "일정한 기상 시간 유지로 규칙성을 지킵니다"},
    # 모르는 kind — 버린다
    {"slide_no": 7, "kind": "implies", "subject_id": "fix", "object_ids": ["reg"],
     "quote": "일정한 기상 시간 유지로 규칙성을 지킵니다"},
    # 괄호로 감싼 id·옛 evidence 모양 — 받는다
    {"kind": "solve", "subject_id": "(fix)", "object_ids": ["(reg)"],
     "evidence": [{"slide_no": 7, "quote": "일정한 기상 시간 유지로 규칙성을 지킵니다"}]},
    # 규칙이 잡은 것과 같은 compose 의 부분집합 — 규칙 쪽(셋)에 합쳐진다
    {"slide_no": 4, "kind": "compose", "subject_id": "sq", "object_ids": ["cont", "reg"],
     "quote": "수면의 질 = 시간 × 연속성 × 규칙성"},
]}


def test_원문_대조를_통과한_주장만_남고_버린_수를_센다():
    llm = ScriptedLLM(LLM_OUT)
    doc = build_claims(GRAPH, DECK, llm=llm)
    assert len(llm.prompts) == 1 and "[TASK] claim-graph" in llm.prompts[0]
    assert "id: sq · 이름: 수면의 질" in llm.prompts[0]
    keys = {(c.kind, c.subject_id, tuple(c.object_ids)) for c in doc.claims}
    assert ("cause", "caf", ("cont",)) in keys
    assert ("solve", "fix", ("reg",)) in keys
    assert ("compose", "sq", ("time", "cont", "reg")) in keys
    assert ("compose", "sq", ("cont", "reg")) not in keys         # 부분집합은 합쳐졌다
    assert ("compare", "sq", ("time",)) in keys                   # 규칙 주장
    assert not any(c.subject_id == "alc" or c.subject_id == "ghost" for c in doc.claims)
    assert doc.dropped == 4                                       # 지어낸 인용·다른 장·밖 id·모르는 kind
    assert doc.model == "scripted"
    # 09-30 G-A21: id 는 순번이 아니라 「c<장>-<내용 해시>」 — 장 순서로 정렬되고, 같은 주장은 다시 만들어도 같은 id
    ids = [c.id for c in doc.claims]
    assert all(re.fullmatch(r"c\d{2}-[0-9a-f]{6}(-\d+)?", i) for i in ids) and len(set(ids)) == len(ids)
    assert [i[:3] for i in ids] == sorted(i[:3] for i in ids)          # 장 번호 머리 — id 로 정렬해도 장 순서
    for c in doc.claims:
        raw = next(s.raw_text for s in DECK.slides if s.slide_no == c.evidence[0].slide_no)
        assert all(verify_quote(q.quote, raw) for q in c.evidence if q.slide_no == c.evidence[0].slide_no)


def test_has_support_는_코드가_채운다():
    doc = build_claims(GRAPH, DECK, llm=ScriptedLLM(LLM_OUT))
    by = {(c.kind, c.subject_id): c for c in doc.claims}
    assert by[("cause", "caf")].has_support is False             # 5장엔 수치·출처가 없다 → unsupported_cause 재료
    # 1장 「5시간 미만」「7시간 이상」 은 설문 보기다 — 비교 줄의 근거가 아니다 (09-29 벤치: 장 전체를 보던 때는 참이었다)
    assert by[("compare", "sq")].has_support is False
    assert by[("solve", "fix")].has_support is False             # 「4번 슬라이드」 는 수치가 아니다


def test_compare_인용은_1장과_4장이_합쳐진다():
    doc = build_claims(GRAPH, DECK, llm="none")
    cmp_ = next(c for c in doc.claims if c.kind == "compare")
    assert [q.slide_no for q in cmp_.evidence] == [1, 4]


@pytest.mark.parametrize("llm", [BrokenLLM(), ScriptedLLM("이건 JSON 이 아니다"), "none"])
def test_LLM_이_죽어도_규칙_주장은_남는다(llm):
    doc = build_claims(GRAPH, DECK, llm=llm)
    assert doc.model == "rule"
    kinds = sorted((c.kind, c.subject_id, tuple(c.object_ids)) for c in doc.claims)
    assert kinds == [("compare", "sq", ("time",)), ("compose", "cont", ("caf", "alc")),
                     ("compose", "sq", ("time", "cont", "reg"))]     # 5장 「…원인」 제목 + 표 항목 → 목록 compose


def test_깨진_JSON_이면_한_번_더_묻는다():
    class Flaky(ScriptedLLM):
        def complete(self, **kw):
            self.prompts.append(kw["user"])
            return "앗" if len(self.prompts) == 1 else json.dumps(LLM_OUT, ensure_ascii=False)
    llm = Flaky(None)
    doc = build_claims(GRAPH, DECK, llm=llm)
    assert len(llm.prompts) == 2 and doc.model == "scripted"


def test_ClaimDoc_왕복():
    doc = build_claims(GRAPH.to_dict(), DECK.to_dict(), llm=ScriptedLLM(LLM_OUT))
    again = ClaimDoc.from_dict(json.loads(json.dumps(doc.to_dict(), ensure_ascii=False)))
    assert again.to_dict() == doc.to_dict()
    assert again.claim(doc.claims[0].id) is not None


# ---------------------------------------------------------------------------
# 브리지 — 세션에 한 번 만들고, F-08 이 claims 를 받을 때만 넘긴다
# ---------------------------------------------------------------------------

import io  # noqa: E402
from email.message import Message  # noqa: E402

import chuckchuck  # noqa: E402
import demo.bridge as bridge  # noqa: E402
from chuckchuck.contracts import QaTriage, QuestionDoc  # noqa: E402
from demo.session_store import SessionStore  # noqa: E402


class FakeHandler(bridge.Handler):
    def __init__(self) -> None:  # noqa: D107 — 소켓 없이 응답만 잡는다
        self.path = "/api/v1/questions"
        self.headers = Message()
        self.client_address = ("127.0.0.1", 1)
        self.sent: list[tuple[int, dict]] = []
        self.wfile = io.BytesIO()

    def _json(self, code: int, payload: dict):
        self.sent.append((code, payload))


@pytest.fixture
def wired(monkeypatch):
    seen: dict = {"triage": [], "build": [], "claims_calls": 0}

    def triage_with_claims(graph, alignment=None, flow=None, ctx=None, *, claims=None, **_):
        seen["triage"].append(claims)
        return QaTriage(file_name="sleep.pptx")

    def build_with_claims(graph, triage, *, track, claims=None, **_):
        seen["build"].append(claims)
        return QuestionDoc(file_name="sleep.pptx", track=track, model="fake")

    def fake_build_claims(graph, slidedoc, *, llm=None, **_):
        seen["claims_calls"] += 1
        return build_claims(graph, slidedoc, llm="none")

    monkeypatch.setattr(chuckchuck, "triage_questions", triage_with_claims)
    monkeypatch.setattr(chuckchuck, "build_questions", build_with_claims)
    monkeypatch.setattr(chuckchuck, "build_claims", fake_build_claims)
    monkeypatch.setattr(bridge, "STORE", SessionStore())
    monkeypatch.setattr(bridge, "STAGE_CACHE_ON", False)
    monkeypatch.setattr(bridge.ARCHIVE, "read_artifact", lambda sid, kind: DECK.to_dict() if kind == "slide_doc" else None)
    monkeypatch.setattr(bridge.Handler, "_papers_for", lambda self, *a: None)
    monkeypatch.setattr(bridge.Handler, "_memory_for", lambda self, *a: None)
    monkeypatch.setattr(bridge.Handler, "_archive", staticmethod(lambda *a: None))
    return seen


def ask(**kw) -> tuple[int, dict]:
    h = FakeHandler()
    h._handle_questions(json.dumps({"graph": GRAPH.to_dict(), "context": {}, "track": "10",
                                    "session_id": "s1", **kw}).encode())
    return h.sent[-1]


def test_브리지는_주장을_한_번_만들어_F08_두_단계에_넘긴다(wired):
    assert ask()[0] == 200
    assert ask(track="5")[0] == 200
    assert wired["claims_calls"] == 1                               # 트랙이 달라도 주장은 세션에 한 번
    got = wired["build"][0]
    assert isinstance(got, dict) and any(c["kind"] == "compose" for c in got["claims"])
    assert wired["triage"][0] == got


def test_claims_false_면_끈다(wired):
    ask(claims=False)
    assert wired["claims_calls"] == 0 and wired["build"] == [None]


def test_F08_이_claims_를_모르면_싣지_않는다(wired, monkeypatch):
    monkeypatch.setattr(chuckchuck, "build_questions",
                        lambda graph, triage, *, track, **_: QuestionDoc(file_name="x", track=track, model="old"))
    assert ask()[0] == 200                                          # **_ 가짜에는 claims 를 싣지 않는다 (TypeError 없음)
    assert bridge._claims_kw(lambda *, track: None, ClaimDoc(file_name="x")) == {}


def test_주장이_죽어도_질문은_나온다(wired, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(chuckchuck, "build_claims", boom)
    assert ask()[0] == 200 and wired["build"] == [None]
