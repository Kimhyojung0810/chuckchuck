"""
Q&A 생각 엮기(2026-10-13) — 서버 쪽 계약.

- 판정의 `claim`(내 핵심 발언)은 답 원문에 실제로 있는 구절일 때만 남는다 (f09 `_answer_claim`) — 화면이 지어낸 발언을 잇지 않게
- 「같은 주제, 다른 관점」 (f09_reframe) 은 같은 개념 · 자료 근거로 관점만 바꾼 질문을 만들고, 계약을 코드가 지킨다
"""
import json

import pytest

from pipeline.contracts import QaJudgement, Question
from pipeline.f09_judge import _answer_claim
from pipeline.f09_reframe import PERSPECTIVES, ReframeError, reframe_question, valid_reframe
from pipeline.providers.llm_base import LLMProvider


class FakeLLM(LLMProvider):
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def complete(self, system="", user="", temperature=0.0, max_tokens=0, json_mode=False, **kw):  # noqa: D401
        self.calls.append(user)
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply, ensure_ascii=False)


ANSWER = "네, 충전 속도와 온도 말고 나머지는 전부 묶었습니다. 셀도 같은 로트에서 뽑았고요."


def test_claim_kept_when_in_answer():
    assert _answer_claim("나머지는 전부 묶었습니다", ANSWER) == "나머지는 전부 묶었습니다"


def test_claim_ignores_spacing_and_quotes():
    assert _answer_claim("“같은 로트에서  뽑았고요”", ANSWER) == "같은 로트에서  뽑았고요"


def test_claim_dropped_when_invented():
    assert _answer_claim("온도가 가장 큰 원인이다", ANSWER) == ""


def test_claim_paraphrased_from_deck_maps_to_users_own_sentence():
    """LLM 이 자료 줄 말로 바꿔 쓰면(10-13 실측) 닮은 원문 문장을 그대로 — 사용자가 한 말만 나간다"""
    answer = "리뷰 이벤트를 한 매장이 별점이 더 높았어요. 그래서 이벤트가 별점을 끌어올린 거라고 봤어요."
    got = _answer_claim("이벤트를 운영한 매장의 평균 별점이 +0.34점 높았다", answer)
    assert got == "리뷰 이벤트를 한 매장이 별점이 더 높았어요."
    assert got in answer


def test_claim_long_sentence_uses_clause():
    """한 문장이 상한보다 길면 마디(쉼표 · 「…며」 뒤)로 나눠 닮은 마디를 단다"""
    answer = "2024년 1월부터 2025년 6월까지 수도권 매장 수천 곳의 리뷰 십만여 건을 분석했으며, 이벤트 운영 여부는 리뷰 텍스트로 추정했어요"
    got = _answer_claim("수도권 매장 3,200곳의 리뷰 124,380건을 분석했다", answer)
    assert got and got in answer and len(got) <= 60


def test_claim_dropped_when_too_short_or_empty():
    assert _answer_claim("네", ANSWER) == ""
    assert _answer_claim("", ANSWER) == ""
    assert _answer_claim("충전 속도", "") == ""


def test_claim_round_trips_in_contract():
    j = QaJudgement(question_id="q1", claim="나머지는 전부 묶었습니다")
    d = j.to_dict()
    assert d["claim"] == "나머지는 전부 묶었습니다"
    assert QaJudgement.from_dict(d).claim == "나머지는 전부 묶었습니다"


def _question(**kw):
    base = dict(id="q01-node", node_id="node", label="실험 설계", question="나머지 조건은 어떻게 통제했나요?",
                answer_gist="충전 속도와 온도만 바꾸고 나머지는 묶었다", slide_nos=[2], evidence_slide_no=2,
                evidence_quote="충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었다")
    base.update(kw)
    return Question(**base)


SLIDEDOC = {"file_name": "a.pptx", "total_slides": 2, "slides": [
    {"slide_no": 2, "title": "실험 설계", "blocks": [{"text": "셀 24개, 0.5C·1C·2C × 25°C·45°C"}, {"text": "동일 로트에서 뽑은 셀"}]},
]}


def test_reframe_makes_same_concept_new_id():
    llm = FakeLLM({"question": "실험에서 변수를 묶은 실제 장면을 하나 들어 설명해 볼래요?",
                   "answer_gist": "같은 로트의 셀 24개를 같은 방전 조건으로 돌렸다", "why": "사례로 설명하게 해요."})
    q = reframe_question(_question(), "example", slidedoc=SLIDEDOC, llm=llm)
    assert q.id == "q01-node~example"
    assert q.node_id == "node" and q.label == "실험 설계"
    assert q.question.endswith("?")
    assert q.answer_gist.startswith("같은 로트")
    assert "동일 로트에서 뽑은 셀" in llm.calls[0]          # 자료 줄을 근거로 준다


def test_reframe_rejects_bad_output():
    with pytest.raises(ReframeError):
        reframe_question(_question(), "counter", slidedoc=SLIDEDOC, llm=FakeLLM({"question": "", "answer_gist": ""}))
    with pytest.raises(ReframeError):
        reframe_question(_question(), "counter", slidedoc=SLIDEDOC, llm=FakeLLM("JSON 아님"))


def test_reframe_refuses_trap_and_unknown_perspective():
    with pytest.raises(ReframeError):
        reframe_question(_question(trap=True), "example", slidedoc=SLIDEDOC, llm=FakeLLM({}))
    with pytest.raises(ReframeError):
        reframe_question(_question(), "joke", slidedoc=SLIDEDOC, llm=FakeLLM({}))


def test_valid_reframe_contract():
    orig = "나머지 조건은 어떻게 통제했나요?"
    assert valid_reframe("그 통제가 깨지면 결과가 어떻게 달라질까요?", orig, "충전 속도와 온도만 바꾸고 나머지는 묶었다")
    assert not valid_reframe("나머지 조건은 어떻게 통제했나요?", orig, "")          # 같은 질문
    assert not valid_reframe("설명해 주세요", orig, "")                              # 물음 아님
    assert not valid_reframe("충전 속도와 온도만 바꾸고 나머지는 묶었다는 거죠?", orig, "충전 속도와 온도만 바꾸고 나머지는 묶었다")  # 답을 흘림


def test_perspectives_are_five():
    assert set(PERSPECTIVES) == {"example", "evidence", "counter", "cause", "effect"}


def test_claim_vague_answer_keeps_users_vague_words():
    """LLM 이 흐릿한 답을 자료 수치로 「고쳐」 옮겨도, 칩에는 사용자가 실제로 한 흐릿한 말이 그대로 (군말 「음…」 은 뗀다)"""
    answer = "음… 어느 정도월부터 어느 정도월까지 수도권 매장 어느 정도의 리뷰 어느 정도를 분석했으며… 정확한 숫자랑 나머지는 기억이 안 나요."
    got = _answer_claim("2024년 1월부터 2025년 6월까지 수도권 매장 3,200곳의 리뷰 124,380건을 분석했다", answer)
    assert got.startswith("어느 정도월부터") and got in answer
