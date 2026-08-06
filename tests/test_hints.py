"""
힌트 사다리(build_hint_ladder)가 계약을 지키는지 검사합니다.

**LLM 을 부르지 않는 순수 함수입니다.** 이미 계산된 신호(질문의 근거 슬라이드,
판정이 짚은 빠진 포인트)만 재료로 쓰기 때문에, 사용자가 힌트를 눌렀을 때
기다림 없이 나와야 합니다. 그래서 이 파일에는 가짜 LLM 조차 없습니다.

단계는 갈수록 구체적입니다 — 방향 → 범위 → 접근 → 근접.
어느 단계에서도 답을 그대로 말해 주지 않습니다.

앞의 세 단계는 질문만으로 만들어지고, 마지막 근접 단계만 판정을 필요로 합니다.
"""

from __future__ import annotations

import pytest

from chuckchuck.contracts import QA_TEXT_MAX, QaJudgement, Question
from chuckchuck.f08_questions import build_hint_ladder


def make_question(**kwargs) -> Question:
    base = dict(
        id="q01-c1",
        node_id="c1",
        label="개념1",
        question="개념1을 설명해 주시겠어요?",
        why="자료가 비중을 둔 핵심이에요",
        hint="측정 방법을 중심으로 답해 보세요",
        severity=1,
        trap=False,
        source="core_weight",
        slide_nos=[3, 5],
        doc_weight=1.0,
        answer_gist="20명 대상 화면 기록으로 평균 23초를 실측했다",
    )
    base.update(kwargs)
    return Question(**base)


def make_judgement(**kwargs) -> QaJudgement:
    base = dict(
        question_id="q01-c1",
        node_id="c1",
        verdict="partial",
        score=55,
        react="절반은 맞습니다",
        summary_sentence="근거가 얕아요",
        missing_points=["측정 도구", "표본 수"],
    )
    base.update(kwargs)
    return QaJudgement(**base)


# ---------------------------------------------------------------------------
# 단계 구성
# ---------------------------------------------------------------------------

def test_판정_전에도_세_단계가_나온다():
    """
    방향 · 범위 · 접근은 질문만으로 만들 수 있다. 답하기 전에 두 단계에서
    끊기면 화면의 힌트 버튼이 금방 사라져 사다리 구실을 못 한다.
    """
    assert len(build_hint_ladder(make_question())) == 3


def test_판정이_있으면_네_단계():
    """
    4단계(근접)만 판정이 있어야 성립한다 — 아직 답하지도 않은 사람에게
    '뭘 빠뜨렸다' 고 말할 수 없다.
    """
    assert len(build_hint_ladder(make_question(), make_judgement())) == 4


def test_삼단계는_기대_답의_앞_조각():
    """판정 없이 만들 수 있는 마지막 단계. 골자를 통째로 노출하지 않는다."""
    question = make_question()
    ladder = build_hint_ladder(question)
    assert ladder[2].startswith("이 방향입니다")
    assert question.answer_gist not in ladder[2]


def test_일단계는_질문이_들고_온_힌트():
    ladder = build_hint_ladder(make_question())
    assert ladder[0] == "측정 방법을 중심으로 답해 보세요"


def test_이단계는_근거_슬라이드를_짚는다():
    ladder = build_hint_ladder(make_question())
    assert "3" in ladder[1] and "5" in ladder[1]


def test_근거_슬라이드가_많으면_다_나열하지_않는다():
    """
    실측에서 개념 하나가 12장에 걸쳐 '1,2,3,…,12장에서' 가 나왔다.
    전부 나열하면 범위를 좁혀 주기는커녕 아무 정보도 주지 못한다.
    """
    ladder = build_hint_ladder(make_question(slide_nos=list(range(1, 13))))
    assert "12장에서" not in ladder[1]
    assert ladder[1].count(",") <= 2


def test_사단계는_빠진_포인트를_짚는다():
    ladder = build_hint_ladder(make_question(), make_judgement())
    assert "측정 도구" in ladder[3] and "표본 수" in ladder[3]


def test_단계가_갈수록_구체적이다():
    """방향 → 범위 → 접근 → 근접. 뒤 단계가 앞을 그대로 반복하면 사다리가 아니다."""
    ladder = build_hint_ladder(make_question(), make_judgement())
    assert len(set(ladder)) == len(ladder)


# ---------------------------------------------------------------------------
# 폴백 — 재료가 없을 때
# ---------------------------------------------------------------------------

def test_질문에_힌트가_없어도_일단계가_빈칸이_아니다():
    ladder = build_hint_ladder(make_question(hint=""))
    assert ladder[0].strip()


def test_근거_슬라이드가_없어도_이단계가_빈칸이_아니다():
    ladder = build_hint_ladder(make_question(slide_nos=[]))
    assert ladder[1].strip()


def test_빠진_포인트가_없으면_사단계가_삼단계를_되풀이하지_않는다():
    """
    포인트가 없을 때 4단계는 골자 조각으로 떨어지는데, 그건 이미 3단계다.
    같은 말을 두 번 하면 사다리가 아니라 제자리걸음이다.
    """
    ladder = build_hint_ladder(make_question(), make_judgement(missing_points=[]))
    assert len(ladder) == 3
    assert len(set(ladder)) == 3


def test_기대_답_조각은_골자_전체를_노출하지_않는다():
    """조각도 방향만 준다. 골자를 통째로 보여 주면 그건 힌트가 아니라 정답 공개다."""
    question = make_question()
    ladder = build_hint_ladder(question, make_judgement(missing_points=[]))
    assert question.answer_gist not in ladder[2]


def test_재료가_아무것도_없으면_두_단계로_줄어든다():
    ladder = build_hint_ladder(
        make_question(answer_gist=""), make_judgement(missing_points=[])
    )
    assert len(ladder) == 2


# ---------------------------------------------------------------------------
# 계약
# ---------------------------------------------------------------------------

def test_모든_단계가_길이_상한을_지킨다():
    long_points = ["아주 긴 포인트 " * 40, "또 다른 긴 포인트 " * 40]
    ladder = build_hint_ladder(
        make_question(hint="긴 힌트 " * 100),
        make_judgement(missing_points=long_points),
    )
    assert all(len(step) <= QA_TEXT_MAX for step in ladder)


def test_dict_입력도_받는다():
    """프론트가 보낸 JSON 을 그대로 넘겨도 동작해야 한다."""
    ladder = build_hint_ladder(
        make_question().to_dict(), make_judgement().to_dict()
    )
    assert len(ladder) == 4


def test_같은_입력이면_같은_사다리():
    """LLM 이 없으므로 결정적이어야 한다."""
    q, j = make_question(), make_judgement()
    assert build_hint_ladder(q, j) == build_hint_ladder(q, j)


def test_빈_문자열_단계는_나오지_않는다():
    ladder = build_hint_ladder(make_question(hint="", slide_nos=[]), make_judgement())
    assert all(step.strip() for step in ladder)


@pytest.mark.parametrize("points", [["측정 도구"], ["a", "b", "c", "d", "e", "f"]])
def test_빠진_포인트_개수가_달라도_한_줄로_묶인다(points):
    ladder = build_hint_ladder(make_question(), make_judgement(missing_points=points))
    assert len(ladder) == 4
    assert "\n" not in ladder[3]
