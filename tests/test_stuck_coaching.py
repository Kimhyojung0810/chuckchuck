"""
'모르겠어요' 코칭(F-09 파생)이 계약을 지키는지 검사합니다.

두 가지를 봅니다:
1. looks_stuck — 포기 의사 감지. **규칙이 코드에 있으므로 표로 검사한다.**
   오탐(진짜 답변을 포기로 오인)이 가장 비싼 실패라 반례를 넉넉히 둔다.
2. coach_stuck — 단계적 코칭. 1차는 쉬운 되물음, 2차는 해설하고 닫는다.

LLM 은 전부 가짜라서 네트워크·API 키가 필요하지 않습니다.
"""

import json

import pytest

from chuckchuck.contracts import QA_COACH_STAGES, QaJudgement, QaTurn, Question
from chuckchuck.f09_judge import coach_stuck, judge_answer, looks_stuck
from chuckchuck.providers.llm_base import LLMProvider


def make_question(**kwargs) -> Question:
    base = dict(
        id="q01-c1",
        node_id="c1",
        label="지연 시간",
        question="지연 시간이 왜 문제였는지 설명해 주시겠어요?",
        why="자료가 비중을 둔 핵심이에요",
        hint="3장을 떠올려 보세요",
        answer_gist="사용자 이탈로 이어지기 때문입니다",
        severity=1,
    )
    base.update(kwargs)
    return Question(**base)


class CoachLLM(LLMProvider):
    """코칭 프롬프트에 정해진 JSON 을 돌려주는 가짜 LLM. 호출 기록을 남긴다."""

    name = "coach-fake"

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.calls.append((system, user))
        return json.dumps(self.payload, ensure_ascii=False)


class RecordingLLM(LLMProvider):
    """complete() 에 어떤 인자가 왔는지 기록하는 가짜 LLM."""

    name = "recording"

    def __init__(self):
        self.kwargs: list[dict] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.kwargs.append({"json_mode": json_mode})
        return json.dumps({"react": "네", "followup": "좁혀볼게요"}, ensure_ascii=False)


class ExplodingLLM(LLMProvider):
    """불리면 안 되는 자리를 지키는 가짜 LLM."""

    name = "exploding"

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        raise AssertionError("LLM 을 부르면 안 되는 경로입니다")


# ---------------------------------------------------------------------------
# looks_stuck — 포기 감지
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("answer", [
    "모르겠어요",
    "정말 모르겠어요",
    "잘 모르겠습니다",
    "모름",
    "모르겠네요",
    "생각 안 나요",
    "기억 안 나요",
    "패스",
    "스킵",
])
def test_give_up_phrases_detected(answer):
    assert looks_stuck(answer) is True


@pytest.mark.parametrize("answer", [
    # 시도한 흔적이 있으면 포기가 아니다 — 오탐이 가장 비싼 실패다
    "잘 모르겠는데 지연 시간 아닐까요?",
    "이 부분은 잘 모르겠지만 제 생각엔 지연 시간이 문제입니다",
    "모르겠지만 사용자 이탈과 관련 있어 보입니다",
    "정확히는 모르겠고 캐시 문제인 것 같아요",
    # 포기 표현이 아예 없는 평범한 답변
    "사용자가 이탈하기 때문입니다",
    "3장에서 말한 대로 응답이 느리면 이탈률이 올라갑니다",
])
def test_real_attempts_not_treated_as_give_up(answer):
    assert looks_stuck(answer) is False


@pytest.mark.parametrize("answer", ["", "   ", None])
def test_blank_is_not_give_up(answer):
    """빈 답변은 _empty_answer 가 따로 다룬다 — 여기서 가로채면 경로가 겹친다."""
    assert looks_stuck(answer) is False


# ---------------------------------------------------------------------------
# coach_stuck — 단계적 코칭
# ---------------------------------------------------------------------------

def test_first_give_up_narrows_instead_of_revealing():
    """1차는 답을 주지 않는다. 쉬운 되물음으로 한 발 끌어준다."""
    llm = CoachLLM({"react": "괜찮아요, 같이 짚어볼게요.", "followup": "3장에서 응답이 느리면 사용자는 어떻게 하죠?"})
    j = coach_stuck(make_question(), llm=llm)

    assert j.coach_stage == "narrow"
    assert j.followup == "3장에서 응답이 느리면 사용자는 어떻게 하죠?"
    assert j.explanation == ""
    assert j.passed is False


def test_second_give_up_explains_and_closes():
    """같은 질문에서 또 포기하면 해설한다 — 계속 되물으면 그냥 괴롭히는 것이다."""
    history = [QaTurn(question=make_question().question, answer="모르겠어요", verdict="unknown")]
    llm = CoachLLM({"react": "여기까지 같이 볼게요.", "explanation": "핵심은 지연이 이탈로 이어진다는 점입니다."})
    j = coach_stuck(make_question(), history=history, llm=llm)

    assert j.coach_stage == "explain"
    assert j.explanation == "핵심은 지연이 이탈로 이어진다는 점입니다."
    assert j.followup == ""      # 닫을 질문에 되물음을 남기면 화면이 모순된다
    assert j.passed is False


def test_second_give_up_with_whitespace_variant_still_explains():
    """질문 문면에 공백 변형이 있어도 같은 질문의 포기로 센다.

    단계 판정이 문면 완전일치면, 질문을 trim 해 보내는 외부 클라이언트에서
    prior=0 이 되어 explain 단계로 영영 못 올라간다.
    """
    history = [QaTurn(
        question="  " + make_question().question + " ",
        answer="모르겠어요",
        verdict="unknown",
    )]
    llm = CoachLLM({"react": "여기까지 같이 볼게요.", "explanation": "핵심은 지연이 이탈로 이어진다는 점입니다."})
    j = coach_stuck(make_question(), history=history, llm=llm)

    assert j.coach_stage == "explain"


def test_coach_stage_is_always_in_enum():
    llm = CoachLLM({"react": "네", "followup": "다시 볼까요?"})
    assert coach_stuck(make_question(), llm=llm).coach_stage in QA_COACH_STAGES


def test_explain_falls_back_to_answer_gist():
    """LLM 이 해설을 안 주면 F-08 이 만들어 둔 answer_gist 로 메운다."""
    history = [QaTurn(question=make_question().question, answer="모르겠어요", verdict="unknown")]
    llm = CoachLLM({"react": "네"})
    j = coach_stuck(make_question(), history=history, llm=llm)

    assert j.coach_stage == "explain"
    assert "사용자 이탈" in j.explanation


def test_narrow_falls_back_to_question_hint():
    llm = CoachLLM({"react": "네"})
    j = coach_stuck(make_question(), llm=llm)

    assert j.coach_stage == "narrow"
    assert j.followup


def test_judgement_roundtrips_coaching_fields():
    """프론트가 sessionStorage 에 넣었다 꺼내도 단계가 살아 있어야 한다."""
    llm = CoachLLM({"react": "네", "followup": "좁혀볼게요"})
    j = coach_stuck(make_question(), llm=llm)

    back = QaJudgement.from_dict(j.to_dict())
    assert back.coach_stage == j.coach_stage
    assert back.explanation == j.explanation


# ---------------------------------------------------------------------------
# judge_answer 와의 배선
# ---------------------------------------------------------------------------

def test_give_up_flag_routes_to_coaching():
    """버튼 경로 — 본문이 무엇이든 give_up 이면 판정하지 않고 코칭한다."""
    llm = CoachLLM({"react": "괜찮아요", "followup": "좁혀볼게요"})
    j = judge_answer(make_question(), "(모르겠어요)", give_up=True, llm=llm)

    assert j.coach_stage == "narrow"
    assert j.verdict == "unknown"


def test_typed_give_up_routes_to_coaching():
    """자동 감지 경로 — 버튼을 안 눌러도 같은 곳으로 간다."""
    llm = CoachLLM({"react": "괜찮아요", "followup": "좁혀볼게요"})
    j = judge_answer(make_question(), "정말 모르겠어요", llm=llm)

    assert j.coach_stage == "narrow"


def test_real_answer_still_judged_normally():
    """오탐 방지의 최종 방어선 — 진짜 답변은 코칭으로 새면 안 된다."""
    llm = CoachLLM({"verdict": "good", "score": 90, "react": "정확해요"})
    j = judge_answer(make_question(), "잘 모르겠는데 사용자가 이탈해서 문제입니다", llm=llm)

    assert j.coach_stage == ""
    assert j.verdict == "good"


def test_llm_is_asked_for_structured_json():
    """
    422 재발 방지. 프롬프트로만 'JSON 만 내라' 고 부탁하면 모델이 한 줄 JSON 안에
    이스케이프 안 된 따옴표를 넣어 파싱이 깨졌고, 그것이 사용자에게 422 로 보였다.
    제공자에게 구조를 강제하는 json_mode 가 실제로 전달되는지 못 박아 둔다.
    """
    llm = RecordingLLM()
    coach_stuck(make_question(), llm=llm)
    assert llm.kwargs and all(k["json_mode"] is True for k in llm.kwargs)

    llm2 = RecordingLLM()
    judge_answer(make_question(), "사용자가 이탈하기 때문입니다", llm=llm2)
    assert llm2.kwargs and all(k["json_mode"] is True for k in llm2.kwargs)


def test_empty_answer_still_skips_llm():
    """빈 답변 경로는 그대로다 — 코칭이 끼어들어 비용을 태우면 안 된다."""
    j = judge_answer(make_question(), "   ", llm=ExplodingLLM())

    assert j.verdict == "unknown"
    assert j.coach_stage == ""


def test_second_give_up_explains_when_history_carries_followup_text():
    """프론트가 실제로 보내는 모양에서도 explain 으로 오른다.

    app.js(submitLiveAnswer)는 2턴째부터 원래 질문이 아니라 **직전 후속 질문**을
    그 턴의 question 으로 적는다 — 좁혀 물은 쪽이 손해 보지 않게 하려는 의도다.
    단계 판정이 문면 비교면 이 턴은 다른 질문으로 읽혀 prior=0 이 되고,
    한 번이라도 답을 시도한 뒤 막힌 사용자는 되물음만 무한히 받는다.
    문면이 아니라 질문 id 로 세야 한다.
    """
    q = make_question()
    history = [
        # 1턴: 정상 답변 (원래 질문 문면)
        QaTurn(question_id=q.id, question=q.question, answer="지연이 늘면 사용자가 떠납니다", verdict="partial"),
        # 2턴: 되물음에 포기 — question 은 followup 문면이다
        QaTurn(question_id=q.id, question="3장에서 응답이 느리면 사용자는 어떻게 하죠?",
               answer="모르겠어요", verdict="unknown"),
    ]
    llm = CoachLLM({"react": "여기까지 같이 볼게요.", "explanation": "핵심은 지연이 이탈로 이어진다는 점입니다."})
    j = coach_stuck(q, history=history, llm=llm)

    assert j.coach_stage == "explain"
    assert j.followup == ""


def test_other_question_give_up_does_not_count():
    """다른 질문에서 포기한 것은 이 질문의 단계를 올리지 않는다."""
    q = make_question()
    history = [QaTurn(question_id="q02-c2", question="다른 질문입니다", answer="모르겠어요", verdict="unknown")]
    llm = CoachLLM({"react": "괜찮아요.", "followup": "3장을 떠올려 볼까요?"})
    j = coach_stuck(q, history=history, llm=llm)

    assert j.coach_stage == "narrow"


def test_qaturn_roundtrips_question_id():
    """조인 키가 to_dict/from_dict 를 왕복해야 프론트가 보낸 id 가 살아남는다."""
    t = QaTurn(question_id="q01-c1", question="질문", answer="답", verdict="partial")
    assert QaTurn.from_dict(t.to_dict()).question_id == "q01-c1"
    # 옛 클라이언트(한글 3키)는 id 없이 온다 — 빈 문자열로 떨어지고 문면 비교로 폴백한다
    assert QaTurn.from_dict({"질문": "질문", "답변": "답", "판정": "partial"}).question_id == ""
