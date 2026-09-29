"""
녹음 경로 신호를 **쓰는 쪽** — 09-30 WP-S2 회귀 테스트.

WP-A(7c20d6b)가 정합에 코드 대조를 얹었다 — `AlignmentDoc.speech_match·basis·skipped_slides·speech_usable`, `items[].decided_by·
deck_quote·deck_slide_no`, `RubricScore.cap·faults`. 여기서는 그걸 읽는 모듈이 **정직하게** 읽는지 본다:
F-08 질문(모순 먼저 · 자료 쪽 값은 질문에 안 나옴 · 건너뛴 핵심 장 · 짐작 missing 무시 · 녹음을 못 쓰면 자료만 + 문서 단위 신호 하나),
F-12 객석 수다·F-13 옛 점수(다른 발표·짐작이면 내용 칭찬·발화 주장 없음), F-19 규칙 폴백(해요체), F-05 장 나누기(조사·이음은 문장 끝이 아님).

**여러 분야의 새 덱으로 본다** — 동네 전기차 충전소 · 공원 산책로 · 동네 서점 · 요가 수업(다른 발표 녹음). 튜닝·실측에 쓴 덱(혈당·수면·
집중·반찬)의 문장·낱말은 넣지 않는다: 규칙이 그 덱 낱말로 맞춘 것이면 여기서 떨어져야 한다.
"""

import ast
import inspect
import json
import re
import textwrap

import pytest

import chuckchuck.f08_questions as f08
import chuckchuck.f12_chatter as f12
from chuckchuck import build_questions, score_presentation, triage_questions
from chuckchuck.contracts import (
    QA_SOURCES,
    AlignmentDoc,
    AlignmentItem,
    AlignmentSummary,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    FlowDiff,
    HabitDoc,
    PaceDoc,
    QuestionDoc,
    SkippedSlide,
    Slide,
    SlideBlock,
    SlideDoc,
    SlideMark,
    SlidePace,
    SlideSpeech,
    SpeechBasis,
    Transcript,
    Word,
)
from chuckchuck.f05_stt import _sentence_end, split_by_slide
from chuckchuck.f19_report import _fallback_report, compose_report
from chuckchuck.providers.llm_base import LLMProvider


class ScriptedLLM(LLMProvider):
    """triage 는 주어진 marks(기본 빈 것), 질문은 payload 그대로. 받은 프롬프트를 남긴다."""

    name = "scripted"

    def __init__(self, questions: list[dict] | None = None, marks: list[dict] | None = None):
        self.questions = questions or []
        self.marks = marks or []
        self.prompts: list[str] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.prompts.append(user)
        if "[TASK] qa-triage" in user:
            return json.dumps({"marks": self.marks})
        return json.dumps({"questions": self.questions}, ensure_ascii=False)


def slide(no: int, text: str) -> Slide:
    return Slide(slide_no=no, title=f"{no}장", blocks=[SlideBlock(category="paragraph", text=text)])


def node(id, label, nos, depth=2, parent="root", summary="", weight=0.5, importance="core"):
    return ConceptNode(id=id, label=label, slide_nos=nos, summary=summary, weight=weight, depth=depth,
                       importance=importance, parent_id=None if depth == 1 else parent)


def speech(by: dict[int, str]) -> Transcript:
    return Transcript(full_text=" ".join(by.values()), duration_sec=150.0,
                      by_slide=[SlideSpeech(slide_no=k, visit=1, start_sec=(k - 1) * 30.0, end_sec=k * 30.0, text=v)
                                for k, v in by.items()])


def item(nid, verdict, *, by="llm", evidence="", deck_quote="", deck_slide_no=None, note="", doc_weight=0.5, speech_weight=0.5):
    return AlignmentItem(node_id=nid, verdict=verdict, decided_by=by, evidence=evidence, deck_quote=deck_quote,
                         deck_slide_no=deck_slide_no, note=note, doc_weight=doc_weight, speech_weight=speech_weight,
                         speech_basis=SpeechBasis(mention_count=1 if verdict == "aligned" else 0))


# ---------------------------------------------------------------------------
# 덱 1 — 동네 전기차 충전소: 4장 수치를 다르게 말함(40% → 「육십 퍼센트」) · 3장 계산식은 말로 건너뜀 · 5장은 LLM 판정이 비어 짐작
# ---------------------------------------------------------------------------

EV = SlideDoc(file_name="ev.pdf", total_slides=5, slides=[
    slide(1, "동네 전기차 충전소\n충전 대기가 길수록 이용이 줄어듭니다"),
    slide(2, "이용 현황\n평일 저녁 충전 대기는 평균 25분입니다"),
    slide(3, "대기 시간 계산\n대기 시간 = 도착 간격 × 충전 시간 ÷ 충전기 수"),
    slide(4, "개선 효과\n충전기를 2대 늘리자 대기 시간이 40% 줄었습니다"),
    slide(5, "정리\n충전기 배치가 이용률을 바꿉니다"),
])
EV_GRAPH = ConceptGraph(file_name="ev.pdf", total_slides=5, nodes=[
    node("root", "충전소 이용", [1, 5], depth=1, weight=1.0, summary="대기가 이용을 가른다"),
    node("wait", "충전 대기", [1, 2], weight=0.8, summary="평일 저녁 평균 25분"),
    node("formula", "대기 시간 계산", [3], weight=0.7, summary="도착 간격 × 충전 시간 ÷ 충전기 수"),
    node("interval", "도착 간격", [3], depth=3, parent="formula", weight=0.4),
    node("effect", "충전기 증설 효과", [4], weight=0.9, summary="2대 늘리자 40% 감소"),
    node("place", "충전기 배치", [5], weight=0.5),
], edges=[ConceptEdge(from_id="root", to_id=n, kind="parent") for n in ("wait", "formula", "effect", "place")]
   + [ConceptEdge(from_id="formula", to_id="interval", kind="parent")])
EV_SAID = {
    1: "안녕하세요 오늘은 동네 전기차 충전소 이야기를 할게요. 충전 대기가 길면 이용이 줄어들어요.",
    2: "평일 저녁에는 충전 대기가 평균 이십오 분이에요.",
    3: "음 이 계산식은 시간 관계상 그냥 넘어갈게요.",
    4: "충전기를 두 대 늘리니까 대기 시간이 육십 퍼센트나 줄었어요.",
    5: "정리하면 충전기 배치가 이용률을 바꿔요. 감사합니다.",
}
EV_CONTRA = item("effect", "contradiction", by="code", evidence=EV_SAID[4],
                 deck_quote="충전기를 2대 늘리자 대기 시간이 40% 줄었습니다", deck_slide_no=4,
                 note="발표에서는 60%라고 했는데 자료 4장은 40%예요", doc_weight=0.9)
EV_SKIP = SkippedSlide(slide_no=3, cue=EV_SAID[3], node_ids=["formula", "interval"])


def ev_alignment(**over) -> AlignmentDoc:
    doc = AlignmentDoc(file_name="ev.pdf", total_slides=5, items=[
        item("root", "aligned", evidence=EV_SAID[1], doc_weight=1.0, speech_weight=1.0),
        item("wait", "aligned", evidence=EV_SAID[2], doc_weight=0.8, speech_weight=0.7),
        item("formula", "missing", by="code", doc_weight=0.7, speech_weight=0.1),
        item("interval", "missing", by="code", doc_weight=0.4, speech_weight=0.0),
        EV_CONTRA,
        item("place", "missing", by="fallback", doc_weight=0.5, speech_weight=0.4),
    ], model="scripted", speech_match="matched", speech_overlap=0.41, basis="llm", skipped_slides=[EV_SKIP])
    for k, v in over.items():
        setattr(doc, k, v)
    return doc


def ev_build(track="5", *, questions=None, alignment=None, transcript=None, traps=False):
    """triage → 질문. 함정은 테스트가 볼 때만 켠다 (코드가 고르는 함정이 끼어들지 않게)."""
    alignment = ev_alignment() if alignment is None else alignment
    transcript = speech(EV_SAID) if transcript is None else transcript
    llm = ScriptedLLM(questions)
    tri = triage_questions(EV_GRAPH, alignment, None, None, transcript=transcript, llm=llm)
    saved = f08.QA_TRACK_TRAPS
    if not traps:
        f08.QA_TRACK_TRAPS = {k: 0 for k in saved}
    try:
        doc = build_questions(EV_GRAPH, tri, track=track, alignment=alignment, transcript=transcript, slidedoc=EV, llm=llm)
    finally:
        f08.QA_TRACK_TRAPS = saved
    return doc, tri, llm


def _nums(text: str) -> set[str]:
    return set(re.findall(r"\d+", text or ""))


# ===========================================================================
# F-08 ① 코드가 확인한 모순 — 맨 앞, 「어느 쪽이 맞나」, 자료 쪽 값은 질문·이유·힌트 1단에 없다
# ===========================================================================

def test_확인된_모순은_맨_앞_질문이고_자료_쪽_값을_말하지_않는다():
    doc, tri, _ = ev_build("5")
    first = doc.questions[0]
    assert first.node_id == "effect" and first.source == "contradiction" and not first.trap
    # 발표에서 한 말은 따옴표로 들고, 자료 4장을 가리키며 어느 쪽이 맞는지 묻는다
    assert "육십 퍼센트" in first.question and "자료 4장" in first.question and first.question.endswith("?")
    assert "어느 쪽이 맞나요" in first.question
    # 답(40)은 질문·이유·힌트 1단(방향)·「이 질문의 근거」 어디에도 없다
    for text in (first.question, first.why, first.hint):
        assert "40" not in _nums(text), text
    assert all(e.quote == "" for e in first.basis.evidence) and first.basis.evidence[0].slide_no == 4
    # 골자는 두 인용을 다 든다 — 자료 쪽(40%)이 맞고 발표에서 한 말을 바로잡는다
    assert "40%" in first.answer_gist and "육십 퍼센트" in first.answer_gist
    assert {"contradiction_reconcile", "contradiction_template", "gist_contradiction_code"} <= set(first.basis.checks)
    assert first.speech_quote == EV_SAID[4] and first.evidence_slide_no == 4


def test_모순_질문의_힌트_사다리는_어긋난_값만_가린다():
    from chuckchuck.f08_questions import build_hint_ladder
    first = ev_build("5")[0].questions[0]
    ladder = build_hint_ladder(first)
    assert ladder == ["자료 4장의 수치를 발표에서 한 말과 나란히 놓고 견줘 보세요",
                      "4장을 같이 볼게요 — 여기서 이 개념을 어떻게 설명했는지 짚어 보세요",
                      "빈칸을 채워 보세요: 자료 4장은 「충전기를 2대 늘리자 대기 시간이 ___ 줄었습니다」라고 해요."]
    assert not any("40" in step for step in ladder)          # 곁가지 수(2대)는 남기고 답의 값만 가린다


def test_1분_트랙의_한_질문은_확인된_모순이다():
    doc, _, _ = ev_build("1")
    assert [q.node_id for q in doc.questions] == ["effect"]


def test_10분_트랙도_모순이_먼저고_모순의_자료_장에는_함정을_만들지_않는다():
    doc, _, _ = ev_build("10", traps=True)
    assert doc.questions[0].node_id == "effect"
    assert all(not (q.trap and q.trap_premise and q.trap_premise.slide_no == 4) for q in doc.questions)
    assert not any(q.trap for q in doc.questions if q.node_id in ("effect", "formula"))


def test_LLM_질문이_자료_쪽_값을_흘리면_정해진_문장으로_바꾼다():
    leak = {"node_id": "effect", "question": "자료 4장에는 40%라고 되어 있는데 발표에서는 왜 다르게 말했나요?",
            "why": "자료에는 40%라고 나와 있어서 묻는 질문이에요.", "hint": "자료에는 40%라고 나와 있어요.",
            "answer_gist": "자료는 40% 감소라고 해요."}
    q = ev_build("5", questions=[leak])[0].questions[0]
    assert "contradiction_value_leak" in q.basis.checks and "contradiction_template" in q.basis.checks
    assert "40" not in _nums(q.question + q.why + q.hint)


def test_LLM_질문이_자료_장을_들어_바로잡게_물으면_그대로_둔다():
    good = {"node_id": "effect",
            "question": "발표에서 말한 대기 시간 감소율이 자료 4장의 수치와 다른데, 어느 쪽이 맞나요?",
            "why": "발표에서 말한 수치를 자료와 견줘 보는 질문이에요.", "hint": "4장을 다시 보세요.",
            "answer_gist": "자료가 맞아요."}
    q = ev_build("5", questions=[good])[0].questions[0]
    assert q.question == good["question"] and "contradiction_llm_worded" in q.basis.checks
    # 이유·힌트·골자는 여전히 코드 문장 — LLM 이 흘리기 쉬운 자리다
    assert q.why.startswith("발표에서 말한 수치가 자료 4장과 달라서") and "40%" in q.answer_gist


def test_자료_쪽_인용이_없는_모순은_앞에_세우지_않고_예전_근거로만_남는다():
    llm_only = item("effect", "contradiction", evidence=EV_SAID[4], doc_weight=0.9)      # deck_quote 없음 — LLM 이 말한 모순
    a = ev_alignment(items=[i if i.node_id != "effect" else llm_only for i in ev_alignment().items])
    doc, _, _ = ev_build("5", alignment=a)
    assert doc.questions[0].node_id == "root"                  # 배합 그대로 — 주제가 먼저
    q = next(x for x in doc.questions if x.node_id == "effect")
    assert q.source == "contradiction" and "contradiction_reconcile" not in q.basis.checks
    assert q.question.startswith("충전기 증설 효과는 발표에서 한 설명이 자료와 조금 달랐어요")


# ===========================================================================
# F-08 ② 말로 건너뛴 핵심 장 — 장마다 대표 하나가 skipped_slide 근거 · 이유 줄에 건너뛰는 말
# ===========================================================================

def test_건너뛴_핵심_장은_장마다_대표_개념_하나가_근거를_받는다():
    _, tri, llm = ev_build("10")
    src = {m.node_id: m.source for m in tri.marks}
    assert "skipped_slide" in QA_SOURCES and QA_SOURCES.index("skipped_slide") < QA_SOURCES.index("missing")
    assert src["formula"] == "skipped_slide"       # 3장에서 가장 무거운 개념
    assert src["interval"] == "missing"            # 같은 장의 나머지는 누락 그대로 — 한 장을 두 질문이 캐묻지 않게
    triage_prompt = next(p for p in llm.prompts if "[TASK] qa-triage" in p)
    assert "건너뜀: 발표에서 3장을 <speech>이 계산식은 시간 관계상 그냥 넘어갈게요</speech>" in triage_prompt


def test_건너뛴_장_질문의_이유는_건너뛰는_말을_들고_질문은_내용을_묻는다():
    doc, _, llm = ev_build("5")
    q = next(q for q in doc.questions if q.node_id == "formula")
    assert q.source == "skipped_slide" and q.basis.slot in ("part", "weak")
    assert q.why == "“이 계산식은 시간 관계상 그냥 넘어갈게요”라고 하고 넘어간 3장의 핵심이라, 그 내용을 설명할 수 있는지 확인하는 질문이에요"
    assert "why_from_skip" in q.basis.checks
    assert q.question == "발표에서 3장은 넘어갔는데, 그 장의 대기 시간 계산을 설명해 주세요."   # LLM 문장이 없을 때의 폴백
    prompt = llm.prompts[-1]
    assert "건너뛴 까닭을 묻지 말고" in prompt
    # 건너뛰는 말은 「발표에서 한 말」 로 실리지 않는다 — LLM 이 설명한 개념으로 읽지 않게
    assert "발표에서 한 말(missing) : <speech>음 이 계산식은" not in prompt
    assert "<speech>음 이 계산식은 시간 관계상 그냥 넘어갈게요.</speech>" not in prompt


def test_코드가_확인한_사실은_LLM_이_가볍다고_해도_치명이다():
    llm = ScriptedLLM(marks=[{"node_id": "formula", "severity": 3}, {"node_id": "effect", "severity": 3},
                             {"node_id": "wait", "severity": 3}])
    tri = triage_questions(EV_GRAPH, ev_alignment(), None, None, transcript=speech(EV_SAID), llm=llm)
    sev = {m.node_id: m.severity for m in tri.marks}
    assert sev["formula"] == 1 and sev["effect"] == 1     # 건너뛴 핵심 장 · 자료와 다른 수치
    assert sev["wait"] == 3                               # 그 밖은 LLM 심사 그대로


def test_가벼운_개념뿐인_건너뛴_장은_핵심_장이_아니다():
    light = SkippedSlide(slide_no=5, cue="이건 시간 관계상 넘어갈게요.", node_ids=["tiny"])
    g = ConceptGraph(file_name="x", total_slides=5, nodes=[
        node("root", "주제", [1], depth=1, weight=1.0), node("tiny", "곁가지", [5], weight=0.1, importance="support")])
    a = AlignmentDoc(file_name="x", total_slides=5, items=[item("root", "aligned"), item("tiny", "missing", by="code")],
                     skipped_slides=[light])
    assert f08._skipped_core(a, g) == {}


# ===========================================================================
# F-08 ③ 짐작 missing(decided_by fallback)은 누락이 아니다 · 프롬프트에 판정 꼬리표도 없다
# ===========================================================================

def test_짐작으로_채운_missing_은_누락_근거가_아니다():
    _, tri, llm = ev_build("10")
    src = {m.node_id: m.source for m in tri.marks}
    assert src["place"] != "missing"
    assert "(place) (missing)" not in next(p for p in llm.prompts if "[TASK] qa-triage" in p)


# ===========================================================================
# F-08 ④ 녹음을 못 쓰면 자료만으로 — 문서 단위 신호는 QuestionDoc.speech_unused 하나
# ===========================================================================

YOGA_SAID = {
    1: "오늘은 아침 요가 수업을 소개할게요 호흡부터 천천히 맞추는 게 중요해요",
    2: "매트는 두께가 육 밀리미터 정도면 무릎이 편하고 미끄럼 방지가 있으면 좋아요",
    3: "고양이 자세와 소 자세를 번갈아 하면 척추가 부드럽게 풀려요 열 번씩 반복해요",
    4: "수업이 끝나면 오 분 동안 누워서 쉬는 사바사나로 마무리해요 몸의 긴장을 내려놓아요",
    5: "꾸준히 나오는 수강생은 어깨 결림이 줄었다고 말해요 들어 주셔서 고마워요",
}


def unrelated_alignment() -> AlignmentDoc:
    note = "녹음이 이 자료의 발표가 아니라서 판정하지 않았어요 (발화 낱말이 자료와 겹치는 비중 4%)"
    return AlignmentDoc(file_name="ev.pdf", total_slides=5, model="code", speech_match="unrelated", speech_overlap=0.04,
                        basis="skipped", items=[item(n.id, "missing", by="fallback", note=note) for n in EV_GRAPH.nodes],
                        summary=AlignmentSummary(speech_total_sec=150.0))


def test_다른_발표의_녹음이면_자료만으로_묻고_문서에_까닭을_한_번_싣는다():
    doc, tri, llm = ev_build("5", alignment=unrelated_alignment(), transcript=speech(YOGA_SAID))
    assert doc.speech_unused == "unrelated_speech"
    assert doc.speech_note.startswith("녹음이 이 자료와 다른 발표라서 자료만 보고 질문을 만들었어요")
    assert all("speech_mismatch_deck_only" in q.basis.checks for q in doc.questions)
    assert all(m.source not in ("missing", "skipped_slide", "contradiction") for m in tri.marks)
    for p in llm.prompts:                 # triage·질문 둘 다 녹음을 안 싣는다 (브리지는 triage 에 slidedoc 을 안 넘긴다)
        assert "<speech>" not in p and "요가" not in p and "건너뜀" not in p
    back = QuestionDoc.from_dict(json.loads(json.dumps(doc.to_dict(), ensure_ascii=False)))
    assert (back.speech_unused, back.speech_note) == (doc.speech_unused, doc.speech_note)


def test_정합이_전부_짐작이면_자료만으로_묻고_까닭이_다르다():
    a = ev_alignment(basis="fallback", skipped_slides=[],
                     items=[item(n.id, "missing", by="fallback") for n in EV_GRAPH.nodes])
    doc, _, llm = ev_build("5", alignment=a)
    assert doc.speech_unused == "align_fallback" and doc.speech_note.startswith("발표 내용을 자료와 맞춰 보지 못해서")
    assert all("align_fallback_deck_only" in q.basis.checks for q in doc.questions)
    assert all("<speech>" not in p for p in llm.prompts)


def test_녹음을_쓴_묶음과_녹음이_없던_묶음은_신호가_비어_있다():
    used, _, _ = ev_build("5")
    assert used.speech_unused == "" and used.speech_note == ""
    deck_only = build_questions(EV_GRAPH, triage_questions(EV_GRAPH, llm=ScriptedLLM()), track="5", slidedoc=EV,
                                llm=ScriptedLLM())
    assert deck_only.speech_unused == "" and deck_only.to_dict()["speech_unused"] == ""


def test_정합이_겹침을_못_잰_옛_정합이면_받아쓰기_겹침으로_가른다():
    old = ev_alignment(speech_overlap=None, skipped_slides=[],
                       items=[item(n.id, "missing", by="llm") for n in EV_GRAPH.nodes])
    assert f08.speech_unused_reason(EV, speech(YOGA_SAID), old)[0] == "unrelated_speech"
    assert f08.speech_unused_reason(EV, speech(EV_SAID), old)[0] == ""
    # 정합이 겹침을 재고 같은 발표라 했으면 그 판정을 따른다 — 리포트·채점표와 같은 판정
    assert f08.speech_unused_reason(EV, speech(EV_SAID), ev_alignment()) == ("", 0.41)
    assert f08.speech_unused_reason(None, None, None) == ("", None)


# ===========================================================================
# F-08 ⑤ 규칙에 덱 낱말이 없다 — 이 파일의 덱 낱말이 새 규칙·문장 틀에 들어 있으면 덱에 맞춘 것이다
# ===========================================================================

def _literals(fn) -> str:
    """함수 본문의 문자열 상수(규칙·문장 틀)만 — 독스트링·주석의 날짜 붙은 실측 메모는 빼고 본다."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    body = tree.body[0].body
    doc = body[0].value if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) else None
    return " ".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n is not doc)


def test_새_규칙과_문장_틀에_발표_낱말이_없다():
    src = " ".join(_literals(fn) for fn in (
        f08._contra_question, f08._contra_gist, f08._contra_why, f08._contra_hint, f08._contra_line, f08._skip_line,
        f08._skip_why, f08._cue_clause, f08._said_clause, f08._skipped_core, f08.speech_unused_reason, f12._unusable_points,
        f12._unusable_lines))
    src += json.dumps(f08.SPEECH_UNUSED_NOTES, ensure_ascii=False) + f08._RECONCILE_RE.pattern + f05_rules()
    for word in ("충전", "대기", "산책", "서점", "요가", "혈당", "수면", "알림", "반찬", "매출"):
        assert word not in src, word


def f05_rules() -> str:
    import chuckchuck.f05_stt as f05
    return " ".join(r.pattern for r in (f05._PUNCT_END_RE, f05._ENDING_RE, f05._CONTINUES_RE, f05._NIKKA_RE, f05._EUM_RE,
                                        f05._JOINED_NEXT_RE))


# ===========================================================================
# F-12 객석 수다 — 다른 발표·짐작이면 내용 칭찬·발화 주장 없음
# ===========================================================================

def _facts(points) -> str:
    return " ".join(p.fact for pts in points.values() for p in pts)


def test_다른_발표_녹음이면_병아리가_투덜대거나_칭찬하지_않는다():
    a = unrelated_alignment()
    flow = FlowDiff(file_name="ev.pdf", ghost_node_ids=[n.id for n in EV_GRAPH.nodes])
    pts = f12.pick_talking_points(EV_GRAPH, a, flow)
    text = _facts(pts)
    assert "다루지 않았다" not in text and "제대로 설명했다" not in text and "입에 오르지 않았다" not in text
    assert "이 자료의 발표가 아니었다" in text and "2분 30초" in text


def test_정합이_전부_짐작이면_누락·칭찬_사실을_만들지_않는다():
    a = ev_alignment(basis="fallback", items=[item(n.id, "missing" if n.id != "root" else "aligned", by="fallback")
                                               for n in EV_GRAPH.nodes])
    text = _facts(f12.pick_talking_points(EV_GRAPH, a, FlowDiff(file_name="ev.pdf")))
    assert "다루지 않았다" not in text and "제대로 설명했다" not in text and "판정이 비었다" in text


def test_쓸_수_있는_녹음이면_짐작_판정만_빼고_모순은_자료_쪽까지_든다():
    pts = f12.pick_talking_points(EV_GRAPH, ev_alignment(), FlowDiff(file_name="ev.pdf"))
    midm = " ".join(p.fact for p in pts["midm"])
    assert "충전기 배치" not in midm                               # 짐작 missing(fallback)은 투덜대지 않는다
    assert '자료 4장에는 "충전기를 2대 늘리자 대기 시간이 40% 줄었습니다"라고 적혀 있다' in midm


def test_출력_형식_예시를_베낀_대사는_버린다():
    assert f12._normalize_turn({"text": "대사", "mood": "neutral"}, "exaone", set(), {}) is None
    assert f12._normalize_turn({"text": "이 자료로 한 발표를 들려줘!", "mood": "happy"}, "exaone", set(), {}) is not None


def test_녹음을_못_쓰면_LLM_을_부르지_않고_넷이_정해진_말로_선다():
    def boom(speaker):
        raise AssertionError(f"LLM 을 부르면 안 된다: {speaker}")

    for a in (unrelated_alignment(),
              ev_alignment(basis="fallback", items=[item(n.id, "missing", by="fallback") for n in EV_GRAPH.nodes])):
        doc = f12.build_chatter(EV_GRAPH, a, FlowDiff(file_name="ev.pdf"), llm_factory=boom)
        assert [t.speaker for t in doc.turns] == list(f12.CHATTER_SPEAKERS) and doc.absent == []
        for t in doc.turns:
            assert t.text.startswith(f12.SIGNATURES[t.speaker]) and len(t.text) <= f12.MAX_TEXT_LEN
            assert not re.search(r"빠졌|빠져|부족|잘했|제대로|다루지 않|입에 오르지", t.text), t.text
        named = [t for t in doc.turns if "'충전소 이용' (슬라이드 1)" in t.text]
        assert named and all(r.node_id == "root" for t in named for r in t.refs)
    ax = next(t for t in f12.build_chatter(EV_GRAPH, unrelated_alignment(), FlowDiff(file_name="ev.pdf"),
                                           llm_factory=boom).turns if t.speaker == "ax")
    assert ax.text == "헐, 2분 30초 동안 들었는데 이 자료랑은 다른 이야기였어."


# ===========================================================================
# F-13 옛 점수(채점표 폴백) — 녹음을 못 쓰면 그 판정으로 잰 항은 0 이 아니라 「없음」
# ===========================================================================

def _summary(coverage=0.2, rank=0.1, edge=0.0):
    return AlignmentSummary(coverage=coverage, rank_correlation=rank, edge_coverage=edge)


def test_옛_점수는_다른_발표_녹음이면_잰_항이_없다():
    a = unrelated_alignment()
    a.summary = _summary()
    s = score_presentation(a, FlowDiff(file_name="ev.pdf", order_tau=0.2))
    assert s.score == 0 and s.basis == "none" and s.components == []
    assert s.omitted == ["coverage", "edge", "order", "rank"] and s.contradiction_count == 0


def test_옛_점수는_정합이_짐작이면_순서만_남기고_확인된_모순만_깎는다():
    a = ev_alignment(basis="fallback")
    a.summary = _summary()
    s = score_presentation(a, FlowDiff(file_name="ev.pdf", order_tau=1.0))
    assert [c.key for c in s.components] == ["order"] and s.omitted == ["coverage", "edge", "rank"]
    assert s.contradiction_count == 1 and s.score == round(100 - s.contradiction_penalty)
    usable = score_presentation(ev_alignment(summary=_summary()), FlowDiff(file_name="ev.pdf", order_tau=1.0))
    assert [c.key for c in usable.components] == ["coverage", "rank", "edge", "order"]    # 쓸 수 있으면 예전과 같다


# ===========================================================================
# F-19 규칙 폴백 — 해요체
# ===========================================================================

_HAPSYO_RE = re.compile(r"(?:습니다|입니다|합니다|됩니다|십시오|습니까)[.!?]?$")


def test_규칙_폴백_리포트는_해요체다():
    pace = PaceDoc(avg_chars_per_min=320.0, tips=["2번은 핵심인데 권장 60초 중 20초만 썼어요."], slides=[
        SlidePace(slide_no=1, importance="support", status="long", recommended_sec=30.0, actual_sec=70.0),
        SlidePace(slide_no=2, importance="core", status="short", recommended_sec=60.0, actual_sec=20.0),
        SlidePace(slide_no=3, importance="core", status="ok", recommended_sec=40.0, actual_sec=41.0)])
    report = _fallback_report(pace, HabitDoc(), model="m")
    for line in (*report.strengths, *report.weaknesses, *report.actions):
        assert not _HAPSYO_RE.search(line.strip()), line
    assert all(a.endswith("보세요.") for a in report.actions)
    assert _fallback_report(PaceDoc(), HabitDoc(), model="m").weaknesses == ["특별히 큰 배분·습관 문제는 보이지 않아요."]
    # LLM 이 죽어 폴백으로 가도 같은 말투다
    down = compose_report(pace, HabitDoc(), llm=ScriptedLLM())      # 빈 질문 JSON 은 리포트 JSON 이 아니다 → 폴백
    assert down.model.endswith("-fallback") and not any(_HAPSYO_RE.search(x.strip()) for x in down.actions)


# ===========================================================================
# F-05 장 나누기 — 조사·이음 어미·명사는 문장 끝이 아니다
# ===========================================================================

@pytest.mark.parametrize("word,nxt,end", [
    ("늘렸느냐보다", "", False),        # 비교 조사 (예전: 끝)
    ("그러니까", "", False),            # 이음 (예전: 끝)
    ("많으니까", "", False),
    ("다음", "장", False),              # 명사 (예전: 끝)
    ("처음", "", False),
    ("음", "그러면", False),            # 군말
    ("책방마다", "", False),
    ("다", "같이", False),              # 부사
    ("주요", "원인은", False),
    ("설명인데요", "", False),          # 이음 — 「…인데요, 넘어갈게요」 는 한 문장
    ("준비하다", "보면", False),        # V-다 보면
    ("늦을까", "봐", False),            # V-ㄹ까 봐
    ("합니까", "", True), ("있습니까?", "", True), ("해요", "", True), ("넘어갈게요.", "", True),
    ("했음", "", True), ("없음", "", True), ("많다", "", True), ("그렇죠", "", True), ("할까", "", True),
    ("“좋아요.”", "", True), ("쉼표,", "", False),
    # 안긴 물음 — 「A일까 B일까가 주제예요」 의 앞 반쪽은 끝이 아니다 (09-30 REC-18)
    ("손해일까", "이득일까가", False), ("늘었을까", "줄었을까를", False), ("비쌀까", "쌀까요?", False),
    ("비쌀까", "그래서", True),
])
def test_문장_끝_판정(word, nxt, end):
    assert _sentence_end(word, nxt) is end


def _words(text: str, t0: float, step: float = 1.0) -> list[Word]:
    return [Word(w, t0 + i * step, t0 + (i + 1) * step) for i, w in enumerate(text.split())]


def test_비교_조사에서_문장을_끊지_않아_한_문장이_두_장으로_갈리지_않는다():
    marks = [SlideMark(slide_no=1, start_sec=0.0, end_sec=6.0, visit=1),
             SlideMark(slide_no=2, start_sec=6.0, end_sec=20.0, visit=1)]
    # 부호 없는 받아쓰기(A.X 꼴) — 「…늘렸느냐보다」 가 1장 끝에 걸치고 문장은 2장 구간에서 끝난다
    words = _words("오늘은 산책로를 얼마나 늘렸느냐보다 어디에 이었느냐가 더 중요하다는 얘기예요 먼저 지도부터 볼게요", 0.0)
    out = split_by_slide(words, marks)
    assert out[0].text == "오늘은 산책로를 얼마나 늘렸느냐보다 어디에 이었느냐가 더 중요하다는 얘기예요"
    assert out[1].text == "먼저 지도부터 볼게요"


def test_끝을_못_읽어도_한_문장은_다음_장까지만_걸친다():
    marks = [SlideMark(slide_no=n, start_sec=(n - 1) * 3.0, end_sec=n * 3.0, visit=1) for n in (1, 2, 3)]
    # 종결 어미도 부호도 없는 말이 세 장 구간을 이어 간다 — 셋째 장 구간부터는 제 장으로 간다
    words = _words("서점 이야기 그리고 동네 책방 그런 곳 손님 줄 선 모습", 0.0)
    out = split_by_slide(words, marks)
    assert out[0].text == "서점 이야기 그리고 동네 책방 그런"
    assert out[1].text == "" and out[2].text == "곳 손님 줄 선 모습"


def test_이음_어미로_이어진_건너뛰는_말은_시작한_장에_남는다():
    marks = [SlideMark(slide_no=3, start_sec=0.0, end_sec=3.0, visit=1),
             SlideMark(slide_no=4, start_sec=3.0, end_sec=20.0, visit=1)]
    words = _words("이건 요금 계산표인데요, 시간 관계상 그냥 넘어갈게요. 다음 장에서는 이용 후기를 볼게요.", 0.0)
    out = split_by_slide(words, marks)
    assert out[0].text == "이건 요금 계산표인데요, 시간 관계상 그냥 넘어갈게요."
    assert out[1].text.startswith("다음 장에서는")
