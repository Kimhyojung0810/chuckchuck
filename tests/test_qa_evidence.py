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
    assert q.answer_gist.endswith("장 근거)")


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
