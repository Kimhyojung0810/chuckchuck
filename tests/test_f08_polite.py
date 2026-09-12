"""f08 `_polite_question` — LLM 이 반말 어미로 낸 질문을 해요체로 바로잡는다.

2026-09-12 /improve-qa 첫 루프: 두 변형 모두 질문 3/3 이 "~되는가." · "~무엇인가?" 였다.
프롬프트 규칙 5 는 있었지만 지켜지지 않았다. 화면 말투(CLAUDE.md §3-1)는 코드가 지킨다."""
import pytest

from chuckchuck.f08_questions import _polite_question


@pytest.mark.parametrize("raw, expected", [
    ("실제 인지 비용은 어떻게 되는가.", "실제 인지 비용은 어떻게 되나요."),
    ("어떤 메커니즘으로 설명되는가?", "어떤 메커니즘으로 설명되나요?"),
    ("다른 환경 설계 전략은 있는가", "다른 환경 설계 전략은 있나요"),   # 문장부호는 안 붙인다
    ("측정 근거는 무엇인가?", "측정 근거는 무엇인가요?"),
    ("이 가정은 타당한가?", "이 가정은 타당한가요?"),
    ("복귀 시간이 더 길어질까?", "복귀 시간이 더 길어질까요?"),
    ("근거가 있느냐?", "근거가 있나요?"),
    ("그 차이를 설명하라.", "그 차이를 설명해 주세요."),
])
def test_impolite_endings_become_haeyo(raw, expected):
    assert _polite_question(raw) == expected


@pytest.mark.parametrize("already", [
    "이유는 무엇인가요?",
    "어떻게 되나요?",
    "설명해 주세요.",
    "왜 그렇게 봤을까요?",
    "근거는 무엇입니까?",
    "",
    "진짜 질문",          # 반말 어미가 아니면 손대지 않는다 — 문장부호도 안 붙인다
])
def test_polite_text_is_untouched(already):
    assert _polite_question(already) == already


def test_only_the_ending_changes():
    raw = "'잠깐'이라고 표현한 이유는 무엇이며, 실제 인지 비용은 어떻게 되는가?"
    out = _polite_question(raw)
    assert out.startswith("'잠깐'이라고 표현한 이유는 무엇이며,")
    assert out.endswith("어떻게 되나요?")
