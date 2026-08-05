"""
F-09 답변 판정(judge_answer)이 계약 불변식을 지키는지 검사합니다.
SCHEMA.md §8 의 '보증' 항목이 여기 그대로 대응됩니다.

LLM 은 전부 가짜라서 네트워크·API 키가 필요하지 않습니다.
"""

import json

import pytest

from chuckchuck.contracts import (
    QA_VERDICT_SCORES,
    QA_VERDICTS,
    AlignmentDoc,
    AlignmentItem,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    JudgeError,
    QaJudgement,
    QaTurn,
    Question,
    SlideSpeech,
    Transcript,
)
from chuckchuck.f09_judge import judge_answer
from chuckchuck.providers.llm_base import LLMProvider

GOOD_ANSWER = "두 벡터를 같은 공간에 놓고 대조 손실로 정렬합니다"


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def make_question(**kwargs) -> Question:
    base = dict(
        id="q01-c1",
        node_id="c1",
        label="개념1",
        question="개념1을 설명해 주시겠어요?",
        why="자료가 비중을 둔 핵심이에요",
        hint="1장을 떠올려 보세요",
        severity=1,
        trap=False,
        source="core_weight",
        slide_nos=[1],
        doc_weight=1.0,
    )
    base.update(kwargs)
    return Question(**base)


def make_graph() -> ConceptGraph:
    """c1 아래 c2(parent), 그리고 c1–c3 는 relates. 트리 ⊂ 그래프를 한 번에 본다."""
    return ConceptGraph(
        file_name="sample.pdf",
        total_slides=3,
        nodes=[
            ConceptNode(id="c1", label="개념1", slide_nos=[1], summary="개념1 한 줄",
                        weight=1.0, parent_id=None, depth=1),
            ConceptNode(id="c2", label="개념2", slide_nos=[2], summary="개념2 한 줄",
                        weight=0.6, parent_id="c1", depth=2),
            ConceptNode(id="c3", label="개념3", slide_nos=[3], summary="개념3 한 줄",
                        weight=0.4, parent_id=None, depth=1),
        ],
        edges=[
            ConceptEdge(from_id="c1", to_id="c2", kind="parent"),
            ConceptEdge(from_id="c1", to_id="c3", kind="relates"),
        ],
    )


def make_transcript(text: str = "발표 때 이렇게 말했습니다") -> Transcript:
    return Transcript(
        full_text="",
        by_slide=[
            SlideSpeech(slide_no=1, visit=1, start_sec=0.0, end_sec=10.0, text=text)
        ],
    )


def make_alignment() -> AlignmentDoc:
    return AlignmentDoc(
        file_name="sample.pdf",
        total_slides=1,
        items=[AlignmentItem(node_id="c1", verdict="missing", evidence="발표에서 한 말")],
    )


class ScriptedLLM(LLMProvider):
    """정해 둔 문자열만 돌려주는 가짜 LLM. 후처리 로직만 시험한다."""

    name = "scripted"

    def __init__(self, payload: str):
        self.payload = payload
        self.calls = 0
        self.prompts: list[str] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False) -> str:
        self.calls += 1
        self.prompts.append(user)
        return self.payload


class SequenceLLM(LLMProvider):
    """호출 순서대로 정해 둔 응답을 준다. 재시도 경로 검증용."""

    name = "sequence"

    def __init__(self, *payloads: str):
        self.payloads = list(payloads)
        self.calls = 0

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False) -> str:
        self.calls += 1
        return self.payloads[min(self.calls - 1, len(self.payloads) - 1)]


class ExplodingLLM(LLMProvider):
    """부르면 터진다. '이 경로는 LLM 을 안 탄다' 를 증명할 때 쓴다."""

    name = "exploding"

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False) -> str:
        raise AssertionError("LLM 을 부르면 안 되는 경로입니다")


def payload(**fields) -> str:
    return json.dumps(fields, ensure_ascii=False)


def judge_of(llm_payload: str, *, answer=GOOD_ANSWER, question=None, **kwargs) -> QaJudgement:
    return judge_answer(
        question or make_question(),
        answer,
        llm=ScriptedLLM(llm_payload),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# mock 파이프라인 · 왕복
# ---------------------------------------------------------------------------

def test_mock_llm_end_to_end():
    judgement = judge_answer(make_question(), GOOD_ANSWER, llm="mock")
    assert judgement.model == "mock"
    assert judgement.verdict in QA_VERDICTS
    assert judgement.question_id == "q01-c1"


def test_roundtrip():
    judgement = judge_of(
        payload(verdict="partial", score=55, react="반응", summary_sentence="총평")
    )
    assert QaJudgement.from_dict(judgement.to_dict()).to_dict() == judgement.to_dict()


def test_accepts_dict_question():
    judgement = judge_answer(
        make_question().to_dict(), GOOD_ANSWER, llm=ScriptedLLM(payload(verdict="good"))
    )
    assert judgement.question_id == "q01-c1"


def test_accepts_dict_graph_and_alignment():
    judgement = judge_of(
        payload(verdict="good"),
        graph=make_graph().to_dict(),
        alignment=make_alignment().to_dict(),
    )
    assert judgement.verdict == "good"


# ---------------------------------------------------------------------------
# verdict — 4-class 안으로 밀어 넣는다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("verdict", QA_VERDICTS)
def test_valid_verdict_kept(verdict):
    assert judge_of(payload(verdict=verdict)).verdict == verdict


def test_unknown_verdict_replaced_by_fallback():
    assert judge_of(payload(verdict="excellent")).verdict == "unknown"


def test_missing_verdict_replaced_by_fallback():
    assert judge_of(payload(react="반응만 왔다")).verdict == "unknown"


@pytest.mark.parametrize("raw, expected", [
    ("Good", "good"),
    ("PARTIAL", "partial"),
    (" wrong ", "wrong"),
    ("Unknown", "unknown"),
])
def test_verdict_case_and_whitespace_normalized(raw, expected):
    """표기만 다른 verdict 는 enum 으로 정규화한다.

    안 하면 "Good"+score 85 가 unknown 으로 떨어지는데 score 는 살아 있어,
    '판정 보류' 배지를 달고 통과하는 모순 화면이 된다 (qa_passed 는 score 도 본다).
    """
    assert judge_of(payload(verdict=raw, score=85)).verdict == expected


def test_skipped_is_not_a_valid_verdict():
    """'skipped' 는 프론트가 로컬로 붙이는 값이라 서버 판정에는 없다."""
    assert judge_of(payload(verdict="skipped")).verdict == "unknown"


# ---------------------------------------------------------------------------
# score — 없으면 기본값, 있으면 clamp
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("verdict", QA_VERDICTS)
def test_score_defaults_by_verdict(verdict):
    assert judge_of(payload(verdict=verdict)).score == QA_VERDICT_SCORES[verdict]


def test_score_kept_when_given():
    assert judge_of(payload(verdict="partial", score=63)).score == 63


def test_score_clamped_above_100():
    assert judge_of(payload(verdict="good", score=9999)).score == 100


def test_score_clamped_below_zero():
    assert judge_of(payload(verdict="wrong", score=-40)).score == 0


def test_unreadable_score_falls_back_to_verdict_default():
    assert judge_of(payload(verdict="good", score="높음")).score == QA_VERDICT_SCORES["good"]


def test_score_zero_is_kept_not_replaced():
    """0 은 '값 없음' 이 아니다 — verdict 기본값으로 덮어쓰면 안 된다."""
    assert judge_of(payload(verdict="good", score=0)).score == 0


# ---------------------------------------------------------------------------
# node_id 승계 — 조인 키가 흔들리면 리포트가 엉뚱한 개념에 총평을 붙인다
# ---------------------------------------------------------------------------

def test_node_id_inherited_from_question():
    assert judge_of(payload(verdict="good", node_id="다른개념")).node_id == "c1"


def test_question_id_inherited_from_question():
    assert judge_of(payload(verdict="good", question_id="q99-x")).question_id == "q01-c1"


# ---------------------------------------------------------------------------
# react · summary_sentence — 프론트가 이 둘로 말풍선을 그린다
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("verdict", QA_VERDICTS)
def test_react_and_summary_never_empty(verdict):
    judgement = judge_of(payload(verdict=verdict))
    assert judgement.react.strip()
    assert judgement.summary_sentence.strip()


def test_llm_react_and_summary_kept():
    judgement = judge_of(payload(verdict="good", react="좋습니다", summary_sentence="총평입니다"))
    assert judgement.react == "좋습니다"
    assert judgement.summary_sentence == "총평입니다"


def test_blank_react_replaced():
    judgement = judge_of(payload(verdict="good", react="   ", summary_sentence="  "))
    assert judgement.react.strip()
    assert judgement.summary_sentence.strip()


def test_fallback_summary_names_the_concept():
    assert "개념1" in judge_of(payload(verdict="wrong")).summary_sentence


def test_missing_points_cleaned():
    judgement = judge_of(payload(verdict="partial", missing_points=["  근거  ", "", "   "]))
    assert judgement.missing_points == ["근거"]


def test_missing_points_default_empty():
    assert judge_of(payload(verdict="good")).missing_points == []


# ---------------------------------------------------------------------------
# 빈 답변 — LLM 을 부르지 않는다
# ---------------------------------------------------------------------------

def test_empty_answer_is_unknown_without_llm_call():
    judgement = judge_answer(make_question(), "   ", llm=ExplodingLLM())
    assert judgement.verdict == "unknown"
    assert judgement.score == 0
    assert judgement.react.strip()


def test_empty_answer_still_carries_join_keys():
    judgement = judge_answer(make_question(), "", llm=ExplodingLLM())
    assert (judgement.question_id, judgement.node_id) == ("q01-c1", "c1")


# ---------------------------------------------------------------------------
# history — 프론트는 한글 키로 보낸다
# ---------------------------------------------------------------------------

def test_korean_key_history_accepted():
    llm = ScriptedLLM(payload(verdict="good"))
    judge_answer(
        make_question(),
        GOOD_ANSWER,
        history=[{"질문": "앞 질문", "답변": "앞 답변", "판정": "partial"}],
        llm=llm,
    )
    assert "앞 질문" in llm.prompts[0]
    assert "앞 답변" in llm.prompts[0]


def test_english_key_history_accepted():
    llm = ScriptedLLM(payload(verdict="good"))
    judge_answer(
        make_question(),
        GOOD_ANSWER,
        history=[{"question": "앞 질문", "answer": "앞 답변", "verdict": "wrong"}],
        llm=llm,
    )
    assert "앞 질문" in llm.prompts[0]


def test_qaturn_objects_accepted():
    llm = ScriptedLLM(payload(verdict="good"))
    judge_answer(
        make_question(),
        GOOD_ANSWER,
        history=[QaTurn(question="앞 질문", answer="앞 답변", verdict="good")],
        llm=llm,
    )
    assert "앞 질문" in llm.prompts[0]


def test_history_trimmed_to_recent_turns():
    from chuckchuck.f09_judge import HISTORY_TURNS

    llm = ScriptedLLM(payload(verdict="good"))
    turns = [
        {"질문": f"질문{i}", "답변": f"답변{i}", "판정": "good"}
        for i in range(HISTORY_TURNS + 3)
    ]
    judge_answer(make_question(), GOOD_ANSWER, history=turns, llm=llm)
    assert "질문0" not in llm.prompts[0]
    assert f"질문{HISTORY_TURNS + 2}" in llm.prompts[0]


# ---------------------------------------------------------------------------
# 프롬프트 — 판정에 필요한 근거가 실린다
# ---------------------------------------------------------------------------

def test_prompt_marks_trap_question():
    llm = ScriptedLLM(payload(verdict="good"))
    judge_answer(make_question(trap=True), GOOD_ANSWER, llm=llm)
    assert "함정 질문인가: 예" in llm.prompts[0]


def test_prompt_includes_graph_summary():
    llm = ScriptedLLM(payload(verdict="good"))
    judge_answer(make_question(), GOOD_ANSWER, graph=make_graph(), llm=llm)
    assert "개념1 한 줄" in llm.prompts[0]


def test_prompt_includes_relates_neighbors():
    """edges 가 진실 — relates 로 이은 개념도 '연결된 개념' 으로 실린다."""
    llm = ScriptedLLM(payload(verdict="good"))
    judge_answer(make_question(), GOOD_ANSWER, graph=make_graph(), llm=llm)
    line = [ln for ln in llm.prompts[0].splitlines() if ln.startswith("연결된 개념:")][0]
    assert "개념2" in line and "개념3" in line


def test_prompt_includes_parent_path_for_child_concept():
    """트리 뷰는 parent 간선만 따라간다 — c2 의 경로는 개념1 > 개념2."""
    llm = ScriptedLLM(payload(verdict="good"))
    judge_answer(
        make_question(node_id="c2", label="개념2", slide_nos=[2]),
        GOOD_ANSWER,
        graph=make_graph(),
        llm=llm,
    )
    assert "경로(위계): 개념1 > 개념2" in llm.prompts[0]


def test_prompt_includes_alignment_evidence():
    llm = ScriptedLLM(payload(verdict="good"))
    judge_answer(make_question(), GOOD_ANSWER, alignment=make_alignment(), llm=llm)
    assert "발표에서 한 말" in llm.prompts[0]


def test_prompt_includes_slide_speech():
    """Transcript.by_slide 를 질문의 slide_nos 로 조인한다."""
    llm = ScriptedLLM(payload(verdict="good"))
    judge_answer(make_question(), GOOD_ANSWER, transcript=make_transcript(), llm=llm)
    assert "발표 때 이렇게 말했습니다" in llm.prompts[0]


def test_speech_excerpt_clipped():
    from chuckchuck.f09_judge import SPEECH_EXCERPT_MAX

    llm = ScriptedLLM(payload(verdict="good"))
    judge_answer(
        make_question(), GOOD_ANSWER, transcript=make_transcript("말" * 2000), llm=llm
    )
    tail = llm.prompts[0].split("## 발표 때 이 개념의 근거 장에서 한 말\n", 1)[1]
    said = tail.split("\n", 1)[0]
    assert len(said) <= SPEECH_EXCERPT_MAX
    assert said.endswith("…")


def test_speech_block_omitted_when_that_slide_was_never_spoken():
    """
    발표자가 그 장까지 못 갔으면 발화 블록이 빠진다.

    누락(missing) 개념이 바로 이 경우다 — 없는 발화를 '한 말' 로 실으면
    판정이 헛돈다. 그래프 위치는 그래도 실려야 한다.
    """
    llm = ScriptedLLM(payload(verdict="good"))
    judge_answer(
        make_question(node_id="c3", label="개념3", slide_nos=[3]),  # 발화는 1장뿐
        GOOD_ANSWER,
        graph=make_graph(),
        transcript=make_transcript(),
        llm=llm,
    )
    assert "근거 장에서 한 말" not in llm.prompts[0]
    assert "연결된 개념:" in llm.prompts[0]


def test_works_without_graph_or_transcript():
    """녹음·그래프 없이 질문만으로도 판정된다."""
    assert judge_of(payload(verdict="good")).verdict == "good"


# ---------------------------------------------------------------------------
# 재시도 · 실패
# ---------------------------------------------------------------------------

def test_broken_json_retried_once():
    llm = SequenceLLM("이건 JSON 이 아니다", payload(verdict="good"))
    judgement = judge_answer(make_question(), GOOD_ANSWER, llm=llm)
    assert llm.calls == 2
    assert judgement.verdict == "good"


def test_broken_json_twice_raises():
    with pytest.raises(JudgeError):
        judge_answer(make_question(), GOOD_ANSWER, llm=SequenceLLM("깨짐", "또 깨짐"))


def test_empty_question_raises():
    with pytest.raises(JudgeError):
        judge_answer(make_question(question="  "), GOOD_ANSWER, llm=ExplodingLLM())


# ---------------------------------------------------------------------------
# 정답 계열 판정(passed) — 되묻기를 멈출지 정하는 유일한 출구다.
#
# 턴 상한이 없으므로 이 임계 하나가 대화의 끝을 결정한다. 임계가 너무 높으면
# 대화가 실제로 안 끝나고, 너무 낮으면 얕은 답이 통과한다.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("score", [70, 71, 85, 100])
def test_임계_이상이면_정답_계열(score):
    assert judge_of(payload(verdict="partial", score=score)).passed


@pytest.mark.parametrize("score", [0, 55, 69])
def test_임계_미만이면_되묻는다(score):
    assert not judge_of(payload(verdict="partial", score=score)).passed


def test_good_은_점수와_무관하게_정답_계열():
    """
    verdict 와 score 가 어긋나면 verdict 를 믿는다 —
    '설득 완료' 라고 판정해 놓고 되묻는 화면은 사용자가 이해할 수 없다.
    """
    assert judge_of(payload(verdict="good", score=10)).passed


@pytest.mark.parametrize("verdict", ["wrong", "unknown"])
def test_낮은_등급은_기본_점수로도_통과하지_못한다(verdict):
    assert not judge_of(payload(verdict=verdict)).passed


def test_빈_답변은_정답_계열이_아니다():
    assert not judge_answer(make_question(), "   ", llm=ExplodingLLM()).passed


def test_passed_는_직렬화에_실린다():
    """프론트가 임계를 다시 계산하지 않도록 서버가 계산해 내려보낸다."""
    assert judge_of(payload(verdict="partial", score=75)).to_dict()["passed"] is True


def test_passed_는_왕복하면_다시_계산된다():
    """
    바디에 passed=true 를 실어 보내도 규칙이 흔들리면 안 된다.
    임계는 계약이 정하는 것이지 요청이 정하는 것이 아니다.
    """
    forged = QaJudgement.from_dict(
        {"question_id": "q01-c1", "verdict": "wrong", "score": 10, "passed": True}
    )
    assert not forged.passed


# ---------------------------------------------------------------------------
# 후속 질문(followup) — 되물을 때 원래 질문을 반복하지 않게 하는 재료
# ---------------------------------------------------------------------------

def test_llm_이_준_후속_질문을_쓴다():
    judgement = judge_of(
        payload(verdict="partial", followup="표본 수는 몇 명이었나요?")
    )
    assert judgement.followup == "표본 수는 몇 명이었나요?"


def test_후속_질문이_비면_빠진_포인트로_채운다():
    """LLM 이 빠뜨려도 되묻기가 멈추면 안 된다. 근거는 이미 코드가 갖고 있다."""
    judgement = judge_of(
        payload(verdict="partial", missing_points=["측정 도구", "표본 수"])
    )
    assert "측정 도구" in judgement.followup


def test_재료가_없어도_후속_질문이_비지_않는다():
    judgement = judge_of(payload(verdict="wrong"))
    assert judgement.followup.strip()


def test_정답_계열이면_후속_질문이_없다():
    """통과한 답에 되묻는 질문을 남기면 프론트가 잘못 이어 붙인다."""
    judgement = judge_of(payload(verdict="good", followup="그래도 더 물어볼까요?"))
    assert judgement.followup == ""


def test_빈_답변도_후속_질문을_받는다():
    """LLM 을 안 부르는 경로라 폴백이 유일한 공급원이다."""
    judgement = judge_answer(make_question(), "", llm=ExplodingLLM())
    assert judgement.followup.strip()


def test_후속_질문도_길이_상한을_지킨다():
    from chuckchuck.contracts import QA_TEXT_MAX

    judgement = judge_of(payload(verdict="partial", followup="긴 질문 " * 200))
    assert len(judgement.followup) <= QA_TEXT_MAX


# ---------------------------------------------------------------------------
# 힌트 사다리 — 판정에 함께 실려 나간다 (추가 왕복 없이 즉시 보여 주려고)
# ---------------------------------------------------------------------------

def test_판정에_힌트_사다리가_실린다():
    judgement = judge_of(payload(verdict="partial", missing_points=["측정 도구"]))
    assert len(judgement.hints) == 3


def test_힌트_사다리가_직렬화에_실린다():
    assert "hints" in judge_of(payload(verdict="partial")).to_dict()


def test_빈_답변에도_힌트_사다리가_실린다():
    """첫 답을 못 쓰고 막힌 사람이야말로 힌트가 필요하다."""
    judgement = judge_answer(make_question(), "", llm=ExplodingLLM())
    assert len(judgement.hints) >= 2


# ---------------------------------------------------------------------------
# [D2] 누적 판정 — 이 질문에 대한 답변 전체를 함께 본다
#
# 되묻기는 "빠진 지점 하나를 콕 집어" 물어 사용자를 증분 답변으로 유도한다.
# 그런데 판정이 마지막 증분만 채점하면, 1턴에 A·2턴에 B 를 말한 사람은
# A+B 를 다 말하고도 B 만으로 평가된다. 그래서 누적이 판정 대상이어야 한다.
# ---------------------------------------------------------------------------

def test_이전_답변이_판정_대상으로_실린다():
    llm = ScriptedLLM(payload(verdict="good"))
    judge_answer(
        make_question(),
        "그리고 온도 파라미터는 0.07 을 썼습니다",
        prior_answers=["두 벡터를 같은 공간에 놓고 정렬합니다"],
        llm=llm,
    )
    prompt = llm.prompts[0]
    assert "두 벡터를 같은 공간에 놓고 정렬합니다" in prompt
    assert "그리고 온도 파라미터는 0.07 을 썼습니다" in prompt


def test_누적_답변은_판정_대상_블록에_들어간다():
    """맥락(지난 대화)이 아니라 '판정하라' 블록 안에 있어야 한다."""
    llm = ScriptedLLM(payload(verdict="good"))
    judge_answer(make_question(), "이번 답", prior_answers=["앞선 답"], llm=llm)
    prompt = llm.prompts[0]
    head = prompt.index("판정하라")
    assert prompt.index("앞선 답") > head, "앞 답변이 판정 대상 블록 밖에 있다"


def test_누적_답변이_없으면_이번_답변만_실린다():
    llm = ScriptedLLM(payload(verdict="good"))
    judge_answer(make_question(), GOOD_ANSWER, llm=llm)
    assert GOOD_ANSWER in llm.prompts[0]


def test_누적_답변은_상한까지만_실린다():
    from chuckchuck.f09_judge import PRIOR_ANSWERS_MAX

    llm = ScriptedLLM(payload(verdict="good"))
    priors = [f"앞선답{i}" for i in range(PRIOR_ANSWERS_MAX + 3)]
    judge_answer(make_question(), GOOD_ANSWER, prior_answers=priors, llm=llm)
    assert "앞선답0" not in llm.prompts[0]
    assert f"앞선답{PRIOR_ANSWERS_MAX + 2}" in llm.prompts[0]


def test_빈_누적_답변은_버려진다():
    llm = ScriptedLLM(payload(verdict="good"))
    judge_answer(make_question(), GOOD_ANSWER, prior_answers=["", "   "], llm=llm)
    assert "1턴" not in llm.prompts[0]


def test_누적이_있어도_빈_이번_답변은_LLM_을_안_부른다():
    """빈 답변 단축 경로가 누적 때문에 뚫리면 비용이 샌다."""
    judgement = judge_answer(
        make_question(), "  ", prior_answers=["앞선 답"], llm=ExplodingLLM()
    )
    assert judgement.verdict == "unknown"


# ---------------------------------------------------------------------------
# [D7] 뉘앙스가 맞는 답에 출구를 준다
#
# good 은 정의상 근거를 요구하고 partial 기본 점수는 55 인데 통과선은 70 이다.
# 요지를 맞혀도 나갈 길이 없었다. 밴드를 쪼개 그 모순을 없앤다.
# ---------------------------------------------------------------------------

def test_점수_밴드가_요지만_맞은_구간을_분리한다():
    from chuckchuck.contracts import QA_PASS_SCORE
    from chuckchuck.f09_judge import SYSTEM_PROMPT

    assert "70~79" in SYSTEM_PROMPT, "요지가 맞을 때 통과 가능한 구간이 명시돼야 한다"
    assert f"{QA_PASS_SCORE}점 이상" in SYSTEM_PROMPT, \
        "통과선을 프롬프트가 알아야 밴드와 임계가 안 싸운다"


def test_결손은_통과를_막는_하나만_요구한다():
    from chuckchuck.f09_judge import SYSTEM_PROMPT

    assert "하나만" in SYSTEM_PROMPT


def test_요지가_맞으면_통과_점수를_받아_넘어간다():
    """D7 의 목적 — 근거가 얕아도 요지를 맞혔으면 갇히지 않는다."""
    judgement = judge_of(payload(verdict="partial", score=72))
    assert judgement.passed
    assert judgement.followup == "", "통과한 답에 되묻는 질문이 남으면 화면이 모순된다"


def test_partial_반응이_절반이라고_깎지_않는다():
    """요지를 맞힌 사람에게 '절반' 은 과소평가로 읽힌다."""
    from chuckchuck.f09_judge import _REACT_BY_VERDICT

    assert "절반" not in _REACT_BY_VERDICT["partial"]
