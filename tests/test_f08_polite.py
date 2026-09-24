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
    ("실제 인지 비용은 어떻게 다른가", "실제 인지 비용은 어떻게 다른가요"),   # 루프 3 에서 놓친 어미 (ㄴ받침 + 가)
    ("두 방식 중 어느 쪽이 더 큰가?", "두 방식 중 어느 쪽이 더 큰가요?"),
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
    "이 항목의 평가?",     # 명사 '평가' 로 끝나는 건 의문 어미가 아니다
])
def test_polite_text_is_untouched(already):
    assert _polite_question(already) == already


def test_only_the_ending_changes():
    raw = "'잠깐'이라고 표현한 이유는 무엇이며, 실제 인지 비용은 어떻게 되는가?"
    out = _polite_question(raw)
    assert out.startswith("'잠깐'이라고 표현한 이유는 무엇이며,")
    assert out.endswith("어떻게 되나요?")


# ---------------------------------------------------------------------------
# _plain_speech — 문장 가운데 높임 (2026-09-24 실측: "인용하셨는데 … 판단하신 근거는")
# ---------------------------------------------------------------------------

from chuckchuck.f08_questions import _plain_speech  # noqa: E402


@pytest.mark.parametrize("raw, expected", [
    ("Leroy (2009)를 인용하셨는데, 왜 그런가요?", "Leroy (2009)를 인용했는데, 왜 그런가요?"),
    ("핵심이라고 판단하신 근거는 무엇인가요?", "핵심이라고 판단한 근거는 무엇인가요?"),
    ("이 방식을 선택하셨을 때 무엇을 봤나요?", "이 방식을 선택했을 때 무엇을 봤나요?"),
    ("결과가 어떻게 되셨나요?", "결과가 어떻게 됐나요?"),
    ("설명하시는 방식은 무엇인가요?", "설명하는 방식은 무엇인가요?"),
    ("어떻게 적용하실 건가요?", "어떻게 적용할 건가요?"),
    ("발표에서 말씀하신 수치는 어디서 왔나요?", "발표에서 말한 수치는 어디서 왔나요?"),
    ("그때 학생이셨나요?", "그때 학생이었나요?"),
    ("담당이 누구이셨나요?", "담당이 누구였나요?"),
    ("사용자께 어떤 가치를 주나요?", "사용자에게 어떤 가치를 주나요?"),
])
def test_plain_speech_lowers_mid_sentence_honorifics(raw, expected):
    assert _plain_speech(raw) == expected


@pytest.mark.parametrize("already", [
    "교수님께서 무엇을 물었나요?",          # '께서' 는 건드리지 않는다
    "두 기능을 함께 쓰면 어떤가요?",        # '함께' 의 '께' 는 조사가 아니다
    "그저께 측정한 값인가요?",
    "왜 그렇게 판단했나요?",                 # 이미 평서
    "설명해 주세요.",
    "",
])
def test_plain_speech_leaves_plain_text_alone(already):
    assert _plain_speech(already) == already


def test_plain_speech_then_polite_question():
    assert _polite_question(_plain_speech("판단하신 근거는 무엇인가?")) == "판단한 근거는 무엇인가요?"
