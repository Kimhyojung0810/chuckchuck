"""
주장 그래프 → 탐침 → 질문 (P1·P3·P4) 회귀 테스트 — 2026-09-29 수면 발표.

- derive_probes: 종류마다 하나씩 걸리게 짠 손 그래프·주장 (tension·unsolved·unsupported_cause·absolute_boundary·sibling_priority)
- 자료만 경로(근거 전부 core_weight)에서 claims 를 주면 weak 자리가 탐침을 받는다 · theme 은 루트 긴장
- 모든 질문에 basis(근거·자리·순위·탐침·인용·검사)가 채워지고 직렬화로 왕복한다
- 탐침 개념을 빼먹은 LLM 질문은 탐침 템플릿으로 · 힌트 인용은 탐침 근거 원문에서
- claims=None 이면 예전과 같다
"""

import json

from chuckchuck.contracts import (
    Claim,
    ClaimDoc,
    ClaimQuote,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    Probe,
    QaTriage,
    Question,
    QuestionBasis,
    Slide,
    SlideBlock,
    SlideDoc,
)
from chuckchuck.f08_questions import (
    _build_question_prompt,
    _pick_marks,
    build_questions,
    derive_probes,
    triage_questions,
)
from chuckchuck.providers.llm_base import LLMProvider


class ScriptedLLM(LLMProvider):
    """task 마다 정해 둔 응답. triage 는 빈 marks(전부 결정적 폴백), 질문은 payload."""

    name = "scripted"

    def __init__(self, questions: list[dict] | None = None):
        self.questions = questions or []
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.prompts.append(user)
        self.systems.append(system)
        if "[TASK] qa-triage" in user:
            return json.dumps({"marks": []})
        return json.dumps({"questions": self.questions}, ensure_ascii=False)


def slide(no: int, text: str) -> Slide:
    return Slide(slide_no=no, title=f"{no}장", blocks=[SlideBlock(category="paragraph", text=text)])


S1 = "수면의 질\n분명 잤는데 왜 피곤할까?\n수면 시간보다 중요한 수면의 질\n잠을 오래 잤다고 반드시 개운한 것은 아닙니다."
S2 = "충분한 시간\n하루 7시간 이상 잠자리에 머무는 계획을 세웁니다."
S4 = "충분히 자도 피곤한 진짜 이유\n수면의 질 =\n시간\n×\n연속성\n×\n규칙성\n얼마나 잤는가 얼마나 끊기지 않았는가"
S5 = "끊기는 잠\n카페인은 수면 주기를 끊어 연속성을 떨어뜨립니다."
S6 = "규칙적인 리듬\n매일 같은 시각에 일어나면 규칙성이 돌아옵니다.\n주말에 몰아 자면 리듬은 반드시 무너집니다."
# 문제 목록 장 — unsolved 는 식(4장)이 아니라 문제 목록에서만 찾는다 (09-29 벤치: 해결 축 식을 문제 목록으로 읽었다)
S7 = "잠을 망치는 세 가지 문제\n시간 부족\n연속성 저하\n규칙성 저하"

DECK = SlideDoc(file_name="sleep.pdf", total_slides=7,
                slides=[slide(1, S1), slide(2, S2), slide(3, "정리 없음 그림 위주 장입니다"), slide(4, S4), slide(5, S5), slide(6, S6),
                        slide(7, S7)])

GRAPH = ConceptGraph(
    file_name="sleep.pdf", total_slides=6,
    nodes=[
        ConceptNode(id="quality", label="수면의 질", slide_nos=[1, 4], summary="시간 × 연속성 × 규칙성", weight=1.0, depth=1),
        ConceptNode(id="sufficient-time", label="시간", slide_nos=[2, 4], summary="얼마나 잤는가", weight=0.7, depth=2, parent_id="quality"),
        ConceptNode(id="continuity", label="연속성", slide_nos=[4, 5], summary="얼마나 끊기지 않았는가", weight=0.5, depth=2, parent_id="quality"),
        ConceptNode(id="regularity", label="규칙성", slide_nos=[4, 6], summary="언제 자고 일어났는가", weight=0.4, depth=2, parent_id="quality"),
        ConceptNode(id="caffeine", label="카페인", slide_nos=[5], summary="수면 주기를 끊는 요인", weight=0.3, depth=3, parent_id="continuity"),
        ConceptNode(id="wake", label="일정한 기상", slide_nos=[6], summary="매일 같은 시각에 일어나기", weight=0.3, depth=3, parent_id="regularity"),
        ConceptNode(id="plan", label="수면 계획", slide_nos=[2], summary="7시간 이상 잠자리에 머무는 계획", weight=0.3, depth=3, parent_id="sufficient-time"),
    ],
    edges=[
        ConceptEdge(from_id="quality", to_id="sufficient-time", kind="parent"),
        ConceptEdge(from_id="quality", to_id="continuity", kind="parent"),
        ConceptEdge(from_id="quality", to_id="regularity", kind="parent"),
        ConceptEdge(from_id="continuity", to_id="caffeine", kind="parent"),
        ConceptEdge(from_id="regularity", to_id="wake", kind="parent"),
        ConceptEdge(from_id="sufficient-time", to_id="plan", kind="parent"),
    ],
)


def q(no: int, text: str) -> ClaimQuote:
    return ClaimQuote(slide_no=no, quote=text)


CLAIMS = ClaimDoc(file_name="sleep.pdf", claims=[
    Claim(id="c01", kind="compose", subject_id="quality", object_ids=["sufficient-time", "continuity", "regularity"],
          text="수면의 질 = 시간 × 연속성 × 규칙성", evidence=[q(4, "수면의 질 = 시간 × 연속성 × 규칙성")]),
    Claim(id="c02", kind="compare", subject_id="quality", object_ids=["sufficient-time"],
          text="수면의 질이 시간보다 중요하다", evidence=[q(1, "수면 시간보다 중요한 수면의 질")]),
    Claim(id="c03", kind="solve", subject_id="plan", object_ids=["sufficient-time"],
          evidence=[q(2, "하루 7시간 이상 잠자리에 머무는 계획을 세웁니다.")]),
    Claim(id="c04", kind="solve", subject_id="wake", object_ids=["regularity"],
          evidence=[q(6, "매일 같은 시각에 일어나면 규칙성이 돌아옵니다.")]),
    Claim(id="c05", kind="cause", subject_id="caffeine", object_ids=["continuity"], has_support=False,
          evidence=[q(5, "카페인은 수면 주기를 끊어 연속성을 떨어뜨립니다.")]),
    Claim(id="c06", kind="absolute", subject_id="regularity",
          evidence=[q(6, "주말에 몰아 자면 리듬은 반드시 무너집니다.")]),
    Claim(id="c07", kind="compose", subject_id="quality", object_ids=["sufficient-time", "continuity", "regularity"],
          text="잠을 망치는 세 가지 문제", evidence=[q(7, "잠을 망치는 세 가지 문제")]),
])


def kinds_by_target(probes: list[Probe]) -> dict[str, str]:
    return {p.kind: p.node_ids[0] for p in probes}


# ---------------------------------------------------------------------------
# derive_probes
# ---------------------------------------------------------------------------

def test_종류마다_탐침이_하나씩_걸리고_대상이_맞다():
    probes = derive_probes(GRAPH, CLAIMS)
    assert kinds_by_target(probes) == {
        "tension": "quality",
        "unsolved": "continuity",
        "unsupported_cause": "caffeine",
        "absolute_boundary": "regularity",
        "sibling_priority": "sufficient-time",
    }
    # QA_SOURCES 우선순위 순으로 정렬돼 있다 — probe_for 가 가장 앞선 탐침을 준다
    assert [p.kind for p in probes] == ["tension", "unsolved", "unsupported_cause", "absolute_boundary", "sibling_priority"]


def test_긴장_탐침은_두_주장의_인용을_합치고_각도를_코드가_조립한다():
    tension = derive_probes(GRAPH, CLAIMS)[0]
    assert tension.node_ids == ["quality", "sufficient-time"]
    assert tension.claim_ids == ["c02", "c01"]
    assert [(e.slide_no, e.quote) for e in tension.evidence] == [
        (1, "수면 시간보다 중요한 수면의 질"), (4, "수면의 질 = 시간 × 연속성 × 규칙성")]
    assert tension.angle == "「수면 시간보다 중요한 수면의 질」라면서 시간을 수면의 질의 요소로 둔다 — 두 말이 함께 성립하는 뜻을 묻는다"


def test_견준_대상이_다른_노드여도_라벨이_겹치면_긴장이다():
    g = ConceptGraph.from_dict(GRAPH.to_dict())
    g.nodes.append(ConceptNode(id="hours", label="수면 시간", slide_nos=[1], weight=0.2, depth=2, parent_id="quality"))
    claims = ClaimDoc.from_dict(CLAIMS.to_dict())
    claims.claims[1].object_ids = ["hours"]
    tension = derive_probes(g, claims)[0]
    assert tension.kind == "tension" and tension.node_ids == ["quality", "sufficient-time"]


def test_해결책이_하나도_없는_발표에는_해결_빠짐_탐침이_없다():
    claims = ClaimDoc(file_name="x", claims=[c for c in CLAIMS.claims if c.kind != "solve"])
    assert "unsolved" not in kinds_by_target(derive_probes(GRAPH, claims))


def test_근거가_있는_인과는_탐침이_아니다():
    claims = ClaimDoc.from_dict(CLAIMS.to_dict())
    claims.claims[4].has_support = True
    assert "unsupported_cause" not in kinds_by_target(derive_probes(GRAPH, claims))


def test_그래프_밖_id_는_걷어내고_주장이_없으면_빈_목록():
    claims = ClaimDoc(file_name="x", claims=[Claim(id="z", kind="absolute", subject_id="ghost", evidence=[q(1, "없는 개념")])])
    assert derive_probes(GRAPH, claims) == []
    assert derive_probes(GRAPH, None) == []
    assert derive_probes(GRAPH, {"file_name": "x", "claims": []}) == []
    # dict 도 받는다
    assert derive_probes(GRAPH, CLAIMS.to_dict()) == derive_probes(GRAPH, CLAIMS)


# ---------------------------------------------------------------------------
# 순위·배합 자리 (자료만 경로)
# ---------------------------------------------------------------------------

def test_claims_를_주면_탐침_대상의_근거가_탐침이고_triage_에_실린다():
    triage = triage_questions(GRAPH, llm=ScriptedLLM())
    assert {m.source for m in triage.marks} == {"core_weight"} and triage.probes == []

    triage = triage_questions(GRAPH, claims=CLAIMS, llm=ScriptedLLM())
    source = {m.node_id: m.source for m in triage.marks}
    assert source["quality"] == "tension"
    assert source["continuity"] == "unsolved"
    assert source["caffeine"] == "unsupported_cause"
    assert source["plan"] == "core_weight"
    assert triage.probe_for("continuity").kind == "unsolved"
    assert QaTriage.from_dict(triage.to_dict()).probes == triage.probes


def test_triage_프롬프트에_탐침_줄이_붙고_claims_없으면_안_붙는다():
    with_llm, without_llm = ScriptedLLM(), ScriptedLLM()
    triage_questions(GRAPH, claims=CLAIMS, llm=with_llm)
    triage_questions(GRAPH, llm=without_llm)
    assert "탐침(tension): 「수면 시간보다 중요한 수면의 질」라면서" in with_llm.prompts[0]
    assert "탐침(" not in without_llm.prompts[0]


def test_자료만_경로에서_weak_자리는_탐침이_받고_theme_은_루트_긴장이다():
    triage = triage_questions(GRAPH, claims=CLAIMS, llm=ScriptedLLM())
    slots: dict[str, str] = {}
    depth_of = {n.id: n.depth for n in GRAPH.nodes}
    picked, _ = _pick_marks(triage.marks, "5", depth_of, set(), slots)
    assert [m.node_id for m in picked][:3] == ["quality", "continuity", "caffeine"]
    assert slots == {"quality": "theme", "continuity": "part", "caffeine": "weak"}


def test_claims_없으면_weak_자리는_맞는_개념이_없어_자리를_안_적는다():
    triage = triage_questions(GRAPH, llm=ScriptedLLM())
    slots: dict[str, str] = {}
    picked, _ = _pick_marks(triage.marks, "5", {n.id: n.depth for n in GRAPH.nodes}, set(), slots)
    assert slots == {"quality": "theme", "sufficient-time": "part"}
    assert len(picked) == 5          # 여유분(_twin_slack) 까지 — 개수는 예전과 같다


# ---------------------------------------------------------------------------
# 질문 — 근거 묶음·프롬프트·템플릿·힌트 인용
# ---------------------------------------------------------------------------

GOOD = [
    {"node_id": "quality", "question": "시간도 수면의 질을 이루는데, 수면의 질이 시간보다 중요하다는 건 어떤 뜻인가요?",
     "why": "수면의 질과 시간이 부딪혀요", "hint": "1장과 4장을 같이 보세요", "answer_gist": "시간은 수면의 질의 한 요소일 뿐이라는 뜻이에요"},
    {"node_id": "continuity", "question": "발표 전체 흐름을 한 문장으로 정리해 주세요.",
     "why": "", "hint": "", "answer_gist": "카페인을 줄여 끊김을 줄여요"},
    {"node_id": "caffeine", "question": "카페인이 연속성을 떨어뜨린다고 볼 근거는 무엇인가요?",
     "why": "카페인 인과의 근거가 없어요", "hint": "5장", "answer_gist": "자료에는 근거가 없어요"},
]


def build(**kw):
    llm = ScriptedLLM(kw.pop("questions", GOOD))
    triage = kw.pop("triage", None) or triage_questions(GRAPH, claims=kw.get("claims", CLAIMS), llm=ScriptedLLM())
    doc = build_questions(GRAPH, triage, track="5", slidedoc=DECK, llm=llm, **kw)
    return doc, llm


def test_모든_질문에_근거_묶음이_채워지고_배합_자리가_적힌다():
    doc, _ = build(claims=CLAIMS)
    by = {q.node_id: q for q in doc.questions}
    assert set(by) == {"quality", "continuity", "caffeine"}
    b = by["quality"].basis
    assert (b.source, b.slot, b.probe.kind) == ("tension", "theme", "tension")
    assert b.rank >= 1
    assert by["continuity"].basis.slot == "part" and by["caffeine"].basis.slot == "weak"
    assert [(e.slide_no, e.quote) for e in b.evidence][:2] == [
        (1, "수면 시간보다 중요한 수면의 질"), (4, "수면의 질 = 시간 × 연속성 × 규칙성")]
    assert "mentions_probe_nodes" in b.checks


def test_질문_프롬프트에_탐침_각도와_근거_원문이_실리고_시스템_규칙이_붙는다():
    _, llm = build(claims=CLAIMS)
    prompt, system = llm.prompts[-1], llm.systems[-1]
    assert "탐침(unsolved): 수면의 질의 요소 가운데 시간에는 해결책이 있는데 연속성을 개선하는 방법은 자료에 없다" in prompt
    assert "근거 원문: S1 «수면 시간보다 중요한 수면의 질» · S4 «수면의 질 = 시간 × 연속성 × 규칙성»" in prompt
    assert "「연속성」·「시간」 를 문장에 넣고" in prompt
    assert "## 탐침 — 이 요청에만 붙는 규칙" in system


def test_탐침_개념을_빼먹은_질문은_탐침_템플릿으로_바뀐다():
    doc, _ = build(claims=CLAIMS)
    cont = next(q for q in doc.questions if q.node_id == "continuity")
    assert cont.question == "시간에는 해결책을 제시했는데, 연속성은 어떻게 개선하나요?"
    assert {"probe_nodes_missing", "probe_template", "why_from_probe"} <= set(cont.basis.checks)
    assert cont.why == "다른 요소에는 해결책을 냈는데 이 요소는 비어 있어서 묻는 질문이에요"
    assert cont.trap is False


def test_LLM_이_비워도_탐침_템플릿이다_종류별_문장():
    doc, _ = build(claims=CLAIMS, questions=[])
    text = {q.node_id: q.question for q in doc.questions}
    assert text["quality"] == "시간도 수면의 질의 요소인데, 수면의 질이 시간보다 중요하다는 건 어떤 뜻인가요?"
    assert text["continuity"] == "시간에는 해결책을 제시했는데, 연속성은 어떻게 개선하나요?"
    assert all("probe_template" in q.basis.checks and "probe_nodes_missing" not in q.basis.checks for q in doc.questions)


def test_단정과_형제_우선순위_템플릿():
    from chuckchuck._probes import probe_question
    probes = {p.kind: p for p in derive_probes(GRAPH, CLAIMS)}
    labels = {n.id: n.label for n in GRAPH.nodes}
    by = {n.id: n for n in GRAPH.nodes}
    assert probe_question(probes["absolute_boundary"], labels, by, CLAIMS) == \
        "규칙성에 대해 「주말에 몰아 자면 리듬은 반드시 무너집니다.」라고 했는데, 이 말이 들어맞지 않는 경우도 있나요?"
    assert probe_question(probes["sibling_priority"], labels, by, CLAIMS) == \
        "시간과 연속성 중 하나만 챙길 수 있다면, 수면의 질에는 어느 쪽이 더 중요한가요?"
    assert probe_question(probes["unsupported_cause"], labels, by, CLAIMS) == \
        "「카페인은 수면 주기를 끊어 연속성을 떨어뜨립니다.」라고 했는데, 그렇게 볼 수 있는 근거는 무엇인가요?"


def test_힌트_인용은_탐침_근거_원문에서_고른다():
    doc, _ = build(claims=CLAIMS)
    by = {q.node_id: q for q in doc.questions}
    assert (by["caffeine"].evidence_slide_no, by["caffeine"].evidence_quote) == (5, "카페인은 수면 주기를 끊어 연속성을 떨어뜨립니다.")
    quality = by["quality"]
    assert (quality.evidence_slide_no, quality.evidence_quote) in {
        (1, "수면 시간보다 중요한 수면의 질"), (4, "수면의 질 = 시간 × 연속성 × 규칙성")}
    assert "probe_evidence_quote" in quality.basis.checks


def test_탐침_없는_옛_triage_에_claims_만_와도_탐침을_쓴다():
    old = triage_questions(GRAPH, llm=ScriptedLLM())
    doc, _ = build(claims=CLAIMS, triage=old)
    # 순위는 옛 triage 그대로(1차 심사를 버리지 않는다) — 근거만 올라가서 자리마다 탐침 개념이 들어간다
    assert [(q.node_id, q.basis.slot, q.source) for q in doc.questions] == [
        ("quality", "theme", "tension"), ("sufficient-time", "part", "sibling_priority"), ("continuity", "weak", "unsolved")]
    assert all(q.basis.probe is not None for q in doc.questions)
    assert old.probes == [] and {m.source for m in old.marks} == {"core_weight"}   # 캐시된 원본은 그대로


def test_claims_없으면_질문과_프롬프트가_예전과_같고_근거만_붙는다():
    triage = triage_questions(GRAPH, llm=ScriptedLLM())
    llm = ScriptedLLM(GOOD)
    doc = build_questions(GRAPH, triage, track="5", slidedoc=DECK, llm=llm)
    assert "탐침" not in llm.prompts[-1] and "## 탐침" not in llm.systems[-1]
    assert [q.node_id for q in doc.questions][:2] == ["quality", "sufficient-time"]
    assert all(q.basis is not None and q.basis.probe is None for q in doc.questions)
    assert doc.questions[0].basis.slot == "theme"
    fallback = next(q for q in doc.questions if q.node_id == "sufficient-time")
    assert "fallback_template" in fallback.basis.checks


def test_자기모순_고쳐쓰기는_검사_이름으로_남는다():
    triage = triage_questions(GRAPH, llm=ScriptedLLM())
    questions = [{"node_id": "quality", "question": "수면의 질이 시간보다 중요한 이유를 세 가지 요소(시간, 연속성, 규칙성)를 바탕으로 설명해 주세요.",
                  "why": "주제", "hint": "4장", "answer_gist": "시간은 요소 가운데 하나예요"}]
    doc = build_questions(GRAPH, triage, track="1", slidedoc=DECK, llm=ScriptedLLM(questions))
    assert "undercut_rewritten" in doc.questions[0].basis.checks


def test_질문마다_근거_로그_한_줄(capsys):
    build(claims=CLAIMS)
    err = capsys.readouterr().err
    assert "[f08] 질문 1: slot=theme node=quality source=tension probe=tension" in err
    assert "근거=S5 «카페인은 수면 주기를 끊어 연속성을 떨어뜨립니다.»" in err


def test_근거_묶음은_직렬화로_왕복한다():
    doc, _ = build(claims=CLAIMS)
    for question in doc.questions:
        back = Question.from_dict(json.loads(json.dumps(question.to_dict(), ensure_ascii=False)))
        assert back.basis == question.basis
    assert Question.from_dict({**doc.questions[0].to_dict(), "basis": None}).basis is None
    assert QuestionBasis.from_dict({"source": "nope"}).source == "core_weight"


def test_프롬프트_함수는_탐침을_안_주면_글자까지_같다():
    triage = triage_questions(GRAPH, llm=ScriptedLLM())
    by_id = {n.id: n for n in GRAPH.nodes}
    from chuckchuck.contracts import Context
    a = _build_question_prompt(GRAPH, triage.marks[:3], by_id, None, None, Context())
    b = _build_question_prompt(GRAPH, triage.marks[:3], by_id, None, None, Context(), probe_of={})
    assert a == b and "탐침" not in a
