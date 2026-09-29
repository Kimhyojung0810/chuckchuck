"""
질문 코칭의 **근거 구성** 회귀 테스트 (2026-09-10 실측에서 나온 것들).

- anchor 장: 12장짜리 개념도 본문이 실제로 그 개념을 말하는 3장으로 좁혀진다
- 이웃 상세: 그래프가 이름 한 줄이 아니라 요약·간선 종류로 실린다
- 판정 본문: F-09 가 자료 근거 장 본문을 받는다 (안 주면 예전 그대로)
- 코드 가드: 무관한 답 → wrong · 함정 동의 → wrong · 「모르겠어요」 빈 답 → 코칭
"""

import json
import re

from chuckchuck import build_questions, judge_answer
from chuckchuck._evidence import anchor_slides, neighbor_lines, section_line
from chuckchuck.contracts import (
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    QaTriage,
    Question,
    Section,
    Slide,
    SlideBlock,
    SlideDoc,
    TriageMark,
)
from chuckchuck.providers.llm_base import LLMProvider


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, payload: dict):
        self.payload = payload
        self.prompts: list[str] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.prompts.append(user)
        return json.dumps(self.payload, ensure_ascii=False)


def slide(no: int, text: str) -> Slide:
    return Slide(slide_no=no, title=f"{no}장", blocks=[SlideBlock(category="paragraph", text=text)])


#: 12장 덱. 「주의 전환」은 2·3장에서만 실제로 말하고, 「환경 설계」는 9장에서만.
DECK = SlideDoc(
    file_name="focus.pdf", total_slides=12,
    slides=[
        slide(1, "척척발표 데모용 10분 발표. 알림 하나를 확인했을 뿐인데 왜 다시 집중하기 어려울까"),
        slide(2, "주의 전환은 알림이 주의를 다른 대상으로 이동시키는 인지 과정이다 ![image](/i.png)"),
        slide(3, "주의 전환 뒤 복귀에는 맥락 복구 비용이 든다 <figcaption><p>A modern desk with a laptop</p></figcaption>"),
        *[slide(n, f"{n}장 배경 설명 그림 위주") for n in range(4, 9)],
        slide(9, "환경 설계: 스마트폰을 시야 밖에 두고 메신저를 닫는다 — 물리적·디지털 환경을 의도적으로 구성"),
        slide(10, "집중 루틴은 전환 전에 한 줄 메모를 남기는 반복 실천이다"),
        slide(11, "정리"), slide(12, "질문 받겠습니다"),
    ],
)
TEXTS = {s.slide_no: s.raw_text for s in DECK.slides}

GRAPH = ConceptGraph(
    file_name="focus.pdf", total_slides=12,
    nodes=[
        ConceptNode(id="switch", label="주의 전환", slide_nos=list(range(1, 13)),
                    summary="외부 자극이 집중을 다른 대상으로 옮기는 인지 과정", weight=1.0, depth=1),
        ConceptNode(id="env", label="환경 설계", slide_nos=[9],
                    summary="집중을 돕도록 물리적·디지털 환경을 의도적으로 구성하는 접근",
                    weight=0.6, depth=2, parent_id="switch"),
        ConceptNode(id="routine", label="집중 루틴", slide_nos=[10],
                    summary="집중을 회복하기 위해 반복 적용하는 실천", weight=0.5, depth=2, parent_id="switch"),
    ],
    edges=[
        ConceptEdge(from_id="switch", to_id="env", kind="parent"),
        ConceptEdge(from_id="switch", to_id="routine", kind="parent"),
        ConceptEdge(from_id="env", to_id="routine", kind="relates"),
    ],
    sections=[Section(name="본론 — 대책", slide_role="body", slide_nos=[9, 10])],
)


# ---------------------------------------------------------------------------
# anchor 장
# ---------------------------------------------------------------------------

def test_12장_개념은_본문이_그_개념을_말하는_장으로_좁혀진다():
    nos = anchor_slides("주의 전환", "외부 자극이 집중을 옮기는 인지 과정", list(range(1, 13)), TEXTS)
    assert len(nos) <= 3
    assert 2 in nos and 3 in nos
    assert 12 not in nos and 7 not in nos


def test_후보는_F07_의_slide_nos_안에서만_고른다():
    """조인 키를 바꾸지 않는다 — 9장이 「환경 설계」를 말해도 후보 밖이면 안 뽑는다."""
    nos = anchor_slides("환경 설계", "환경을 구성", [1, 2], TEXTS)
    assert set(nos) <= {1, 2}


def test_본문이_없으면_앞_k장이다():
    assert anchor_slides("개념", "", [5, 6, 7, 8], {}) == [5, 6, 7]
    assert anchor_slides("개념", "", [], {}) == []


def test_어느_장에도_안_나오는_개념은_F07_순서대로_앞_k장():
    nos = anchor_slides("양자 얽힘", "물리학", [4, 5, 6, 7], TEXTS)
    assert nos == [4, 5, 6]


# ---------------------------------------------------------------------------
# 그래프 상세
# ---------------------------------------------------------------------------

def test_이웃은_요약과_간선_종류와_근거_장을_달고_나온다():
    lines = neighbor_lines(GRAPH.node("env"), GRAPH, TEXTS)
    joined = "\n".join(lines)
    assert "상위 · 주의 전환" in joined
    assert "관련 · 집중 루틴: 집중을 회복하기 위해" in joined
    assert "[S10]" in joined


def test_상위_개념의_이웃_근거_장도_anchor_로_좁혀진다():
    """「주의 전환」은 12장을 들고 있지만 이웃 줄에는 anchor 만 붙는다."""
    line = next(ln for ln in neighbor_lines(GRAPH.node("env"), GRAPH, TEXTS) if "주의 전환" in ln)
    nos = [int(n) for n in re.search(r"\[S([\d,]+)\]", line).group(1).split(",")]
    assert len(nos) <= 3 and 2 in nos and 3 in nos and 12 not in nos


def test_구간_줄():
    assert section_line(GRAPH.node("env"), GRAPH) == "구간=본론 — 대책 (body)"
    assert section_line(GRAPH.node("switch"), GRAPH) == ""   # 1장은 어느 구간에도 없다


# ---------------------------------------------------------------------------
# F-08: 질문의 근거 장·프롬프트
# ---------------------------------------------------------------------------

def triage() -> QaTriage:
    return QaTriage(
        file_name="focus.pdf", total_slides=12, model="scripted",
        marks=[
            TriageMark(node_id="switch", rank=1, severity=1, trap=False, source="core", doc_weight=1.0),
            TriageMark(node_id="env", rank=2, severity=2, trap=False, source="core", doc_weight=0.6),
        ],
    )


def test_질문의_slide_nos_는_anchor_다():
    llm = ScriptedLLM({"questions": [
        {"node_id": "switch", "question": "주의 전환 뒤 복귀 비용은 어디서 커지나요", "why": "", "hint": "",
         "answer_gist": "맥락 복구에서 커진다"},
    ]})
    doc = build_questions(GRAPH, triage(), track="5", slidedoc=DECK, llm=llm)
    q = next(q for q in doc.questions if q.node_id == "switch")
    assert len(q.slide_nos) <= 3 and 2 in q.slide_nos
    # 프롬프트도 같은 장을 실었다
    assert "자료 본문(S" in llm.prompts[-1]
    body = next(ln for ln in llm.prompts[-1].splitlines() if "자료 본문(S" in ln and "switch" not in ln)
    assert "주의 전환" in body and "modern desk" not in body


def test_프롬프트에_이웃_요약과_구간이_실린다():
    llm = ScriptedLLM({"questions": []})
    build_questions(GRAPH, triage(), track="5", slidedoc=DECK, llm=llm)
    prompt = llm.prompts[-1]
    assert "이웃 하위 · 환경 설계: 집중을 돕도록" in prompt
    assert "구간=본론 — 대책 (body)" in prompt


def test_폴백_골자는_근거_장을_세_개까지만_적는다():
    llm = ScriptedLLM({"questions": []})   # 전부 폴백
    doc = build_questions(GRAPH, triage(), track="5", slidedoc=DECK, llm=llm)
    q = next(q for q in doc.questions if q.node_id == "switch")
    assert "12장" not in q.answer_gist
    # 09-29: 폴백 골자는 개념 요약이 아니라 근거 장의 자료 줄이다 (요약은 답이 아니었다 — 기준선 §5-8)
    assert q.answer_gist.startswith("자료는 이렇게 말해요 — ") and q.answer_gist.endswith("장)")


# ---------------------------------------------------------------------------
# F-09: 자료 본문 블록 · 가드
# ---------------------------------------------------------------------------

def question(**kw) -> Question:
    base = dict(id="q01-switch", node_id="switch", label="주의 전환",
                question="주의 전환 뒤 복귀 비용은 어디서 커지나요?", severity=1, trap=False,
                slide_nos=[2, 3], answer_gist="화면을 본 시간이 아니라 맥락을 복구하는 과정에서 커진다")
    base.update(kw)
    return Question(**base)


def judge_payload(**kw) -> dict:
    base = dict(verdict="partial", score=70, react="요지까지는 정확합니다",
                summary_sentence="총평", missing_points=[], followup="그럼 복구 비용은요?")
    base.update(kw)
    return base


def test_판정_프롬프트에_자료_근거_장_본문이_실린다():
    llm = ScriptedLLM(judge_payload())
    judge_answer(question(), "맥락 복구에서 커집니다", graph=GRAPH, slidedoc=DECK, llm=llm)
    prompt = llm.prompts[0]
    assert "## 자료 근거 장 본문" in prompt
    assert "[S2] 주의 전환은" in prompt and "[S3]" in prompt
    assert "modern desk" not in prompt


def test_slidedoc_을_안_주면_예전_그대로다():
    llm = ScriptedLLM(judge_payload())
    judge_answer(question(), "맥락 복구에서 커집니다", graph=GRAPH, llm=llm)
    assert "자료 근거 장 본문" not in llm.prompts[0]


def test_옛_세션의_12장_질문도_판정에서_다시_좁힌다():
    llm = ScriptedLLM(judge_payload())
    judge_answer(question(slide_nos=list(range(1, 13))), "맥락 복구", graph=GRAPH, slidedoc=DECK, llm=llm)
    body = [ln for ln in llm.prompts[0].splitlines() if ln.startswith("[S")]
    assert 1 <= len(body) <= 3


def test_무관한_답은_LLM_이_partial_을_줘도_wrong_이다():
    """물류 창고 재고 이야기에 partial 75 — 자료 본문을 답변으로 착각한 실측."""
    llm = ScriptedLLM(judge_payload(verdict="partial", score=75, react="스마트폰 시야 밖 두기까지는 정확합니다"))
    v = judge_answer(
        question(), "저희 팀은 물류 창고 세 곳의 재고 회전율을 비교했고 배송 지연이 반품률을 올렸습니다",
        graph=GRAPH, slidedoc=DECK, llm=llm,
    )
    assert v.verdict == "wrong" and v.score <= 35 and not v.passed
    assert "질문과 다른 이야기예요" in v.react
    assert v.missing_points[0].startswith("질문이 묻는 것")


def test_낱말_하나만_겹쳐도_무관_가드는_비켜선다():
    llm = ScriptedLLM(judge_payload(verdict="partial", score=72))
    v = judge_answer(question(), "알림 때문에요", graph=GRAPH, slidedoc=DECK, llm=llm)
    assert v.verdict == "partial" and v.score == 72


def test_다른_개념_이야기를_길게_한_답은_자료_낱말이_겹쳐도_wrong_이다():
    """2026-09-26 실험대 실측: 개념 그래프 질문에 타깃 시장 이야기가 partial 75 — 자료 본문과 「발표」 가 겹쳐 무관 가드를 비켜 갔다.
    「알림」 은 근거 장(S2)에 있지만 이 질문(복귀 비용)·골자·개념 자리에는 없다."""
    llm = ScriptedLLM(judge_payload(verdict="partial", score=75))
    v = judge_answer(
        question(), "알림이 계속 와서 저희 팀은 회의 중에 알림을 전부 끄기로 정했고 그 뒤로 훨씬 편해졌어요",
        graph=GRAPH, slidedoc=DECK, llm=llm,
    )
    # 자료와 무관하다고까지는 못 박지 않는다 — 통과만 막고 되묻기로 보낸다
    assert v.verdict == "partial" and v.score <= 65 and not v.passed
    assert "답으로는 조금 멀어요" in v.react
    assert v.missing_points[0].startswith("질문이 묻는 것")


def test_짧은_바꿔_말하기는_집중_대조를_걸지_않는다():
    """"빠진 개념을 찾아 주는 거예요" — 낱말은 안 겹치지만 뜻은 맞을 수 있다. 짧은 답은 LLM 판정 그대로."""
    llm = ScriptedLLM(judge_payload(verdict="partial", score=72))
    # 「알림」 은 근거 장에 있어 무관 가드는 비켜 가고, 짧아서 집중 대조도 걸지 않는다
    v = judge_answer(question(), "알림이 계속 와서 그래요", graph=GRAPH, slidedoc=DECK, llm=llm)
    assert v.verdict == "partial" and v.score == 72


def test_함정_동의는_무관_가드보다_먼저다():
    """"네, 맞아요. 그 전제가 정확해요" 는 질문에 답한 것이다 — 무관 문구가 아니라 함정 문구가 붙어야 한다."""
    llm = ScriptedLLM(judge_payload(verdict="partial", score=70, premise_corrected=False))
    v = judge_answer(question(trap=True), "네, 맞아요. 질문하신 대로예요. 그 전제가 정확해요. 저도 그렇게 봐요",
                     graph=GRAPH, slidedoc=DECK, llm=llm)
    assert v.verdict == "wrong"
    assert v.react.startswith("질문의 전제부터 확인해 보세요")


def test_골자를_바꿔_말한_긴_답은_집중_대조를_통과한다():
    llm = ScriptedLLM(judge_payload(verdict="partial", score=72))
    v = judge_answer(
        question(), "화면 자체를 오래 봐서가 아니라 하던 일의 맥락을 다시 복구하느라 비용이 커지는 거라고 생각해요",
        graph=GRAPH, slidedoc=DECK, llm=llm,
    )
    assert v.verdict == "partial" and v.score == 72


def test_근거가_얇으면_무관_가드를_걸지_않는다():
    """질문 한 줄뿐인 호출(테스트·flat 판정)에서 안 겹치는 것은 신호가 아니다."""
    llm = ScriptedLLM(judge_payload(verdict="good", score=85))
    v = judge_answer(question(answer_gist=""), "두 벡터를 같은 공간에 놓고 정렬합니다", llm=llm)
    assert v.verdict == "good"


def test_함정에_동의한_답은_premise_corrected_false_면_wrong():
    llm = ScriptedLLM(judge_payload(verdict="partial", score=70, premise_corrected=False))
    v = judge_answer(question(trap=True), "네 맞습니다, 주의 전환은 그렇게 커집니다",
                     graph=GRAPH, slidedoc=DECK, llm=llm)
    assert v.verdict == "wrong" and v.score <= 35
    assert v.react.startswith("질문의 전제부터")
    assert v.missing_points[0] == "질문의 전제가 자료와 다르다는 점"


def test_함정을_바로잡은_답은_그대로_통과한다():
    llm = ScriptedLLM(judge_payload(verdict="good", score=85, premise_corrected=True))
    v = judge_answer(question(trap=True), "그 전제는 자료와 달라요. 맥락 복구에서 커집니다",
                     graph=GRAPH, slidedoc=DECK, llm=llm)
    assert v.verdict == "good" and v.passed


def test_premise_corrected_가_없으면_함정_가드는_손대지_않는다():
    llm = ScriptedLLM(judge_payload(verdict="partial", score=70))
    v = judge_answer(question(trap=True), "주의 전환은 맥락 복구에서 커집니다", graph=GRAPH, slidedoc=DECK, llm=llm)
    assert v.verdict == "partial"


def test_함정_아닌_질문은_premise_corrected_를_무시한다():
    llm = ScriptedLLM(judge_payload(verdict="good", score=85, premise_corrected=False))
    v = judge_answer(question(trap=False), "맥락 복구에서 커집니다", graph=GRAPH, slidedoc=DECK, llm=llm)
    assert v.verdict == "good"


def test_모르겠어요_버튼은_답이_비어_있어도_코칭으로_간다():
    """빈 답 검사가 먼저면 버튼을 누른 사람이 '아직 답변이 없습니다' 를 받았다."""
    llm = ScriptedLLM({"react": "괜찮아요", "followup": "복구 비용은 화면을 본 시간에 드나요, 돌아올 때 드나요?"})
    v = judge_answer(question(), "", give_up=True, graph=GRAPH, slidedoc=DECK, llm=llm)
    assert v.coach_stage == "narrow"
    assert "아직 답변이 없습니다" not in v.react


def test_결정적_후속_질문에_띄어_붙은_조사와_시겠어요_가_없다():
    from chuckchuck.f09_judge import _FOLLOWUP_BY_POINT, _FOLLOWUP_GENERIC
    for tpl in (_FOLLOWUP_BY_POINT.format(point="인지 자원"), _FOLLOWUP_GENERIC.format(label="인지 자원")):
        assert " 를 " not in tpl and " 에 " not in tpl
        assert "시겠어요" not in tpl and "보시나요" not in tpl


# ---------------------------------------------------------------------------
# 「모르겠어요」 사다리 — 인용·빈칸·3단
# ---------------------------------------------------------------------------

from chuckchuck import build_hint_ladder, coach_stuck
from chuckchuck._evidence import mask_gist, quote_for
from chuckchuck.contracts import QaTurn


def test_인용은_개념_이름이_든_문장을_그대로_옮긴다():
    text = "알림 하나를 확인했을 뿐인데 왜 다시 집중하기 어려울까. 주의 전환은 알림이 주의를 다른 대상으로 이동시키는 인지 과정이다. 정리."
    q = quote_for("주의 전환", "인지 과정", text)
    assert q == "주의 전환은 알림이 주의를 다른 대상으로 이동시키는 인지 과정이다."


def test_인용은_표_칸과_짧은_조각을_건너뛴다():
    assert quote_for("개념", "", "| 5 초 | ≠ 5 초 | 손실은 화면을 본 시간보다 돌아오는 과정에서 커진다") \
        == "손실은 화면을 본 시간보다 돌아오는 과정에서 커진다"
    assert quote_for("개념", "", "짧다") == ""


def test_인용은_120자에서_자른다():
    q = quote_for("개념", "", "가" * 300)
    assert len(q) == 120 and q.endswith("…")


def test_빈칸은_개념_이름이_아닌_가장_긴_낱말을_가린다():
    masked, answer, distractor = mask_gist(
        "화면을 본 시간이 아니라 맥락을 복구하는 과정에서 커진다", "주의 전환",
        ["집중을 돕도록 물리적·디지털 환경을 의도적으로 구성하는 접근"],
    )
    assert "___" in masked and answer not in masked
    assert answer in ("화면", "시간", "맥락", "과정")     # 명사 줄기 — 서술어·조사는 답이 아니다
    assert distractor and distractor not in masked
    assert not distractor.endswith(("다", "는", "을", "를"))


def test_빈칸은_서술어를_가리지_않는다():
    masked, answer, _ = mask_gist("알림 확인 후 작업 맥락 복구에 더 큰 인지 비용이 들기 때문입니다", "알림", [])
    assert answer not in ("때문입니다", "들기", "복구에", "비용이")
    assert answer in ("복구", "비용", "작업", "맥락", "확인", "인지")
    assert "때문입니다" in masked


def test_코치는_포기한_사람을_칭찬하지_않는다():
    llm = ScriptedLLM({"react": "지금 핵심을 잘 짚으셨어요", "followup": "A인가요, B인가요?", "choices": ["A", "B"]})
    j = coach_stuck(question(**EVQ), graph=GRAPH, llm=llm)
    assert "짚으셨" not in j.react and j.react.startswith("괜찮아요")


def test_빈칸_재료가_없으면_빈_값():
    assert mask_gist("", "개념", []) == ("", "", "")
    assert mask_gist("주의 전환", "주의 전환", []) == ("", "", "")


def test_F08_이_인용과_발화를_질문에_저장한다():
    from chuckchuck.contracts import Transcript
    words = [{"text": w, "start_sec": i, "end_sec": i + 1}
             for i, w in enumerate(["5초만", "봤는데", "왜", "오래", "남을까요"])]
    tr = Transcript.from_dict({"full_text": "5초만 봤는데 왜 오래 남을까요", "words": words,
                               "by_slide": [{"slide_no": 2, "start_sec": 0, "end_sec": 5, "words": words,
                                             "text": "5초만 봤는데 왜 오래 남을까요"}],
                               "provider": "fixture", "duration_sec": 5})
    llm = ScriptedLLM({"questions": []})
    doc = build_questions(GRAPH, triage(), track="5", slidedoc=DECK, transcript=tr, llm=llm)
    q = next(q for q in doc.questions if q.node_id == "switch")
    assert q.evidence_slide_no in (2, 3)
    assert "주의 전환" in q.evidence_quote
    assert "5초만 봤는데" in q.speech_quote
    # 왕복해도 남는다
    back = Question.from_dict(q.to_dict())
    assert back.evidence_quote == q.evidence_quote and back.speech_quote == q.speech_quote


def test_인용이_있으면_사다리_첫_칸이_자료_인용이고_빈칸_칸이_생긴다():
    q = question(evidence_slide_no=2, evidence_quote="주의 전환은 알림이 주의를 다른 대상으로 이동시키는 인지 과정이다")
    ladder = build_hint_ladder(q)
    assert ladder[0] == "자료 2장은 이렇게 말해요: «주의 전환은 알림이 주의를 다른 대상으로 이동시키는 인지 과정이다»"
    assert any(step.startswith("빈칸을 채워 보세요: ") for step in ladder)


def test_인용이_없으면_사다리는_예전_그대로다():
    ladder = build_hint_ladder(question())
    assert not any("이렇게 말해요" in s or "빈칸" in s for s in ladder)


EVQ = dict(evidence_slide_no=2, evidence_quote="주의 전환은 알림이 주의를 다른 대상으로 이동시키는 인지 과정이다",
           speech_quote="5초만 봤는데 왜 오래 남을까요")


def test_1단은_인용을_react_에_붙이고_선택지_둘을_준다():
    llm = ScriptedLLM({"react": "괜찮아요.", "followup": "이건 확인하는 순간 이야기인가요, 돌아오는 과정 이야기인가요?",
                       "choices": ["확인하는 순간", "돌아오는 과정"]})
    j = coach_stuck(question(**EVQ), graph=GRAPH, llm=llm)
    assert j.coach_stage == "narrow"
    assert "자료 2장은 이렇게 말해요: «주의 전환은" in j.react
    assert j.choices == ["확인하는 순간", "돌아오는 과정"]
    assert "2장" in j.followup                      # 화면이 장 그림을 붙일 번호
    assert j.evidence_quote == EVQ["evidence_quote"] and j.evidence_slide_no == 2
    # 프롬프트에도 인용·발화가 실렸다
    assert "자료 인용: 자료 2장 — «" in llm.prompts[0] and "발표 때 한 말: «5초만" in llm.prompts[0]


def test_1단에서_LLM_이_선택형을_안_쓰면_코드가_둘_중_하나를_만든다():
    llm = ScriptedLLM({"react": "괜찮아요.", "followup": "주의 전환이 왜 문제인지 설명해 보세요"})
    j = coach_stuck(question(**EVQ), graph=GRAPH, llm=llm)
    assert len(j.choices) == 2
    assert "쪽인가요" in j.followup and "«주의 전환은" in j.followup


def test_2단은_LLM_없이_빈칸과_선택지를_준다():
    llm = ScriptedLLM({"react": "안 불러야 한다"})
    history = [QaTurn(question_id="q01-switch", question="q", answer="(모르겠어요)", verdict="unknown", gave_up=True)]
    j = coach_stuck(question(**EVQ), graph=GRAPH, history=history, llm=llm)
    assert j.coach_stage == "scaffold"
    assert j.followup.startswith("빈칸을 채워 보세요: ") and "___" in j.followup
    assert len(j.choices) == 2 and any(c in ("화면", "시간", "맥락", "과정") for c in j.choices)
    assert llm.prompts == []


def test_3단_해설에는_출처가_붙는다():
    llm = ScriptedLLM({"react": "여기까지 볼게요.", "explanation": "손실은 돌아오는 과정에서 커집니다."})
    history = [QaTurn(question_id="q01-switch", question="q", answer="(모르겠어요)", verdict="unknown", gave_up=True)] * 2
    j = coach_stuck(question(**EVQ), graph=GRAPH, history=history, llm=llm)
    assert j.coach_stage == "explain"
    assert j.explanation.startswith("손실은 돌아오는 과정에서 커져요.")   # 해설의 합쇼체는 코드가 해요체로 푼다 (_speech.to_haeyo)
    assert "자료 2장: «주의 전환은" in j.explanation
    assert "발표에서는 «5초만 봤는데" in j.explanation
    assert len(j.explanation) <= 500


def test_판정_직렬화에_선택지와_인용이_실린다():
    from chuckchuck.contracts import QaJudgement
    j = QaJudgement(question_id="q", choices=["a", "b"], evidence_quote="인용", evidence_slide_no=3)
    d = j.to_dict()
    assert d["choices"] == ["a", "b"] and d["evidence_slide_no"] == 3
    back = QaJudgement.from_dict(d)
    assert back.choices == ["a", "b"] and back.evidence_quote == "인용"
    assert QaJudgement.from_dict({"question_id": "q"}).choices == []     # 옛 세션


# ---------------------------------------------------------------------------
# 09-29 수면 발표 — 힌트가 1장 설문 보기를 붙여 보여 주고, 주제 질문이 자기모순이던 것
# ---------------------------------------------------------------------------

from chuckchuck._evidence import best_quote, slide_units
from chuckchuck.f08_questions import _undercut_question

SLEEP_S1 = ("01 / 08\n수면의 질\n분명 잤는데\n왜 피곤할까?\n수면 시간보다 중요한 수면의 질\n“어젯밤 몇 시간 잤나요?”\n"
            "5시간 미만\n5–7시간\n7시간 이상\n잠을 오래 잤다고 반드시 개운한 것은 아닙니다.")
SLEEP_S4 = ("충분히 자도 피곤한 진짜 이유\n수면의 질은 단순한 “시간”보다 넓은 개념입니다.\n수면의 질 =\n시간\n×\n연속성\n×\n규칙성\n"
            "얼마나 잤는가\n얼마나 끊기지 않았는가\n언제 자고 일어났는가")
SLEEP_Q = "수면의 질이 시간보다 중요한 이유를 발표에서 제시한 세 가지 요소(시간, 연속성, 규칙성)를 바탕으로 설명해 주세요."


def test_인용_후보는_글_상자_줄을_지키고_칸마다_나뉜_식은_잇는다():
    units = slide_units(SLEEP_S1) + slide_units(SLEEP_S4)
    assert "수면 시간보다 중요한 수면의 질" in units              # 제목이 설문 보기와 붙지 않는다
    assert not any("5시간 미만" in u and "개운한" in u for u in units)
    assert "수면의 질 = 시간 × 연속성 × 규칙성" in units
    assert not any(u.startswith("01 / 08") for u in units)        # 쪽 번호는 글이 아니다
    assert slide_units("핵심은 원인의 개수보다\n“수면 주기가 끊긴다”는 점입니다.") \
        == ["핵심은 원인의 개수보다 “수면 주기가 끊긴다”는 점입니다."]


def test_인용은_앞_장이_아니라_질문을_받치는_장에서_고른다():
    no, quote = best_quote("수면의 질", "시간 × 연속성 × 규칙성", [(1, SLEEP_S1), (4, SLEEP_S4)], SLEEP_Q)
    assert (no, quote) == (4, "수면의 질 = 시간 × 연속성 × 규칙성")
    assert best_quote("개념", "", []) == (0, "")


def test_견준_대상을_요소로_다시_넣은_질문은_그_모순을_묻는다():
    node = ConceptNode(id="sleep-quality", label="수면의 질", slide_nos=[1, 4], summary="")
    assert _undercut_question(SLEEP_Q, node) == "시간도 수면의 질의 요소인데, 수면의 질이 시간보다 중요하다는 건 어떤 뜻인가요?"
    plain = "시간보다 연속성이 더 중요한 이유는 무엇인가요?"
    assert _undercut_question(plain, node) == plain


def test_폭에서_꺾인_OCR_줄은_잇고_앞_장_꼬리_조각은_인용으로_쓰지_않는다():
    # 09-29 부스 실측 꼴 — 사진 OCR 이 낱말 한가운데서 줄을 꺾었다 (도메인 중립 문장)
    raw = ("신청서 한 줄 소개를 적어 주세요 *\n"
           "주문 앱 - 매장 대기열 예측 기반 픽업 알림 서비스\n"
           "매장 대기열과 조리 시간을 함께 분석해 픽업 시각을 예측하고, 혼잡 구간 기\n"
           "반 알림을 통해 고객의 대기 시간을 줄이는 모바일 주문 서비스입니다.")
    units = slide_units(raw)
    assert "주문 앱 - 매장 대기열 예측 기반 픽업 알림 서비스" in units          # 폭보다 짧은 제목 줄은 그대로
    assert any("혼잡 구간 기반 알림을 통해" in u for u in units)                 # 낱말 한가운데 꺾임은 붙인다
    assert not any(u.startswith("반 알림") for u in units)
    tail = "(매장)과 본사 대상 구독형 도입을 주요 수익모델로 검토하고 있습니다.\n본사 대상 구독형 도입이 가장 빠른 수익 경로입니다."
    no, quote = best_quote("본사 구독", "", [(2, tail)], "본사 대상 구독형 도입이 왜 유리한가요?")
    assert quote.startswith("본사 대상")


def test_모르겠어요_보기는_인용이_세운_대비_쌍이고_세는_단위는_쓰지_않는다():
    # 09-29 부스 실측: 「격차는 종목 선택이 아니라 행동에서」 에 보기가 '가지'·'종목' 으로 나왔다 (둘 다 틀린 보기)
    from chuckchuck._evidence import mask_gist
    quote = "결론부터: 매출 차이는 메뉴 구성이 아니라 회전율에서 만들어진다"
    gist = "평균 매출이 상권 대비 낮고, 메뉴 구성과 매출의 상관은 약하며 회전율이 매출과 뚜렷하게 연결돼요"
    _, answer, distractor = mask_gist(gist, "매출 차이", ["다섯 가지 원인", "좌석 수"], quote=quote)
    assert (answer, distractor) == ("회전율", "메뉴 구성")
    # 대비가 없으면 부정된 쪽 낱말은 정답이 못 되고, 세는 단위는 오답이 못 된다
    _, answer, distractor = mask_gist("대기 시간이 길면 재방문이 줄어요", "재방문", ["세 가지 요인"],
                                      quote="재방문을 줄이는 것은 가격이 아닌 대기 시간이다")
    assert answer != "가격" and distractor != "가지"
    # 물음꼴·부사 대비는 보기감이 아니다
    from chuckchuck._evidence import _contrast_pair
    assert _contrast_pair("무엇을 샀는가가 아니라, 얼마나 자주 사고팔았는가가 결과를 갈랐다") == ("", "")
