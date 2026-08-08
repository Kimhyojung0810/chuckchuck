"""F-04 파생 — 업로드 녹음의 슬라이드 구간 추정 (LLM 없음, 결정적)."""

from __future__ import annotations

import pytest

from chuckchuck.contracts import Slide, SlideDoc, Word
from chuckchuck.f04_infer_marks import (
    MIN_CONFIDENCE,
    even_slide_marks,
    infer_slide_marks,
)


def make_doc(pairs: list[tuple[str, str]]) -> SlideDoc:
    return SlideDoc(
        file_name="t.pdf",
        total_slides=len(pairs),
        slides=[
            Slide(
                slide_no=i + 1, title=title,
                blocks=[{"category": "paragraph", "text": body}],
                categories=["paragraph"], total_char_count=len(body), line_count=1,
                has_visual=False, visual_type=[], alignment=None,
                text_sparse=False, image_only=False,
            )
            for i, (title, body) in enumerate(pairs)
        ],
    )


def speak(segments: list[tuple[str, float, float]]) -> list[Word]:
    """구간 [a, b) 동안 그 문장을 1초에 한 낱말씩 반복해 말한다."""
    words: list[Word] = []
    for text, a, b in segments:
        toks = text.split()
        t = float(a)
        while t < b - 0.5:
            for tok in toks:
                if t >= b - 0.5:
                    break
                words.append(Word(text=tok, start_sec=round(t, 2), end_sec=round(t + 0.8, 2)))
                t += 1.0
    return words


DOC = make_doc([
    ("알림과 집중", "알림이 작업 맥락을 끊는다 주의 전환"),
    ("수면 주기", "깊은 수면과 렘수면 90분 주기"),
    ("환경 설계", "의지가 아니라 환경 설계 폰을 시야 밖으로"),
])


def test_even_split_is_uniform():
    marks = even_slide_marks(120, 3)
    assert [m.slide_no for m in marks] == [1, 2, 3]
    assert marks[0].end_sec == pytest.approx(40, abs=0.01)
    assert marks[-1].end_sec == pytest.approx(120, abs=0.01)


def test_uneven_speech_beats_even_split():
    """실제 60/20/40 초를 균등 분할(40/40/40)보다 가깝게 되짚어야 한다."""
    words = speak([
        ("알림이 작업 맥락을 끊는다 주의 전환이 일어난다", 0, 60),
        ("깊은 수면과 렘수면 90분 주기", 60, 80),
        ("의지가 아니라 환경 설계다 폰을 시야 밖으로", 80, 120),
    ])
    got = infer_slide_marks(DOC, words, duration_sec=120)
    assert got.estimated is True
    assert got.confidence >= MIN_CONFIDENCE

    truth = [60.0, 20.0, 40.0]
    lens = [m.end_sec - m.start_sec for m in got.marks]
    err_infer = sum(abs(a - b) for a, b in zip(lens, truth))
    err_even = sum(abs((m.end_sec - m.start_sec) - b)
                   for m, b in zip(even_slide_marks(120, 3), truth))
    assert err_infer < err_even, f"추정 {lens} 이 균등 분할보다 나빠졌다"


def test_marks_are_contiguous_and_ordered():
    words = speak([
        ("알림이 작업 맥락을 끊는다", 0, 40),
        ("깊은 수면과 렘수면 주기", 40, 80),
        ("의지가 아니라 환경 설계", 80, 120),
    ])
    marks = infer_slide_marks(DOC, words, duration_sec=120).marks
    assert [m.slide_no for m in marks] == [1, 2, 3]
    for a, b in zip(marks, marks[1:]):
        assert a.end_sec <= b.start_sec + 0.01, "구간이 겹치면 안 된다"
    assert marks[-1].end_sec == pytest.approx(120, abs=0.5)


def test_never_goes_backwards():
    """발표는 앞으로 간다. 구간 시작이 뒤로 가면 안 된다."""
    words = speak([
        ("환경 설계 의지가 아니라", 0, 30),
        ("알림이 작업 맥락을 끊는다", 30, 60),
    ])
    marks = infer_slide_marks(DOC, words, duration_sec=60).marks
    starts = [m.start_sec for m in marks]
    assert starts == sorted(starts), "구간 시작이 단조 증가해야 한다"


def test_silence_does_not_move_the_slide():
    """말이 없는 구간에서 전환이 일어난 것으로 잡으면 안 된다."""
    words = speak([("알림이 작업 맥락을 끊는다", 0, 20)])   # 20초 뒤로는 침묵
    marks = infer_slide_marks(DOC, words, duration_sec=120).marks
    assert marks[0].end_sec >= 20, "말이 이어진 구간까지는 1장에 머물러야 한다"


def test_falls_back_when_content_does_not_match():
    """자료와 발화가 딴판이면 추정을 버리고 균등 분할로 물러난다."""
    words = speak([("김치찌개 레시피 돼지고기 두부 파", 0, 120)])
    got = infer_slide_marks(DOC, words, duration_sec=120)
    assert got.estimated is False
    assert "균등" in got.reason


def test_no_words_falls_back():
    got = infer_slide_marks(DOC, [], duration_sec=90)
    assert got.estimated is False
    assert got.confidence == 0.0
    assert len(got.marks) == 3


# ---------------------------------------------------------------------------
# 자료와 다른 녹음 — 점수는 넘는데 여러 장이 통째로 비는 경우
#
# 2026-08-08 사용자 제보: "PPT 와 다른 내용의 녹음본을 올리면 아예 인식을 못 한다".
# 실측(수면 자료 8장 + 집중·알림 녹음)에서 confidence 0.1931 로 MIN_CONFIDENCE 를
# 넘고 쓰인 장도 5개라 개수 가드까지 통과했는데, 2·3·4 장이 폭 0 이라 그 장들의
# by_slide 가 통째로 비었다. F-11 은 그걸 "말한 적 없음" 으로 읽는다.
# ---------------------------------------------------------------------------

#: 두 장은 발화가 또렷이 맞고 나머지 여섯 장은 전혀 안 맞는 8장짜리 자료.
#: 맞는 장이 있어 confidence 는 살아 있지만 빈 장 비율이 상한을 넘는다.
PARTIAL_DOC = make_doc([
    ("알림과 집중", "알림이 작업 맥락을 끊는다 주의 전환"),
    ("수면 주기", "깊은 수면과 렘수면 90분 주기"),
    ("호흡 훈련", "복식 호흡 들숨 날숨 횡격막 이완"),
    ("영양 설계", "단백질 지방 탄수화물 비율 식단"),
    ("운동 처방", "유산소 근력 인터벌 회복일 강도"),
    ("조명 환경", "색온도 조도 눈부심 간접 조명"),
    ("소음 관리", "백색소음 차음재 데시벨 방음"),
    ("환경 설계", "의지가 아니라 환경 설계 폰을 시야 밖으로"),
])

#: 8장 중 두 장에만 맞는 발화. 새 가드가 잡아야 하는 입력이다.
PARTIAL_SPEECH = [
    ("알림이 작업 맥락을 끊는다 주의 전환", 0, 60),
    ("의지가 아니라 환경 설계 폰을 시야 밖으로", 60, 120),
]


def test_rejects_estimate_when_too_many_slides_get_no_speech():
    """빈 장이 상한을 넘으면 점수가 임계를 넘었어도 추정을 버린다."""
    got = infer_slide_marks(PARTIAL_DOC, speak(PARTIAL_SPEECH), duration_sec=120)
    assert got.confidence >= MIN_CONFIDENCE, "이 경우는 점수 가드로는 안 걸린다"
    assert got.estimated is False
    assert "맞지 않아" in got.reason, "왜 물러섰는지 사실대로 말해야 한다"


def test_fallback_leaves_no_empty_slide():
    """물러선 뒤에는 모든 장에 구간이 생긴다 — 화면이 통째로 비지 않는다."""
    got = infer_slide_marks(PARTIAL_DOC, speak(PARTIAL_SPEECH), duration_sec=120)
    widths = [m.end_sec - m.start_sec for m in got.marks]
    assert all(w > 0 for w in widths), f"폭 0 인 장이 남았다: {widths}"


def test_good_match_still_survives_the_empty_guard():
    """새 가드가 멀쩡한 추정까지 버리면 안 된다 — 세 장을 다 말하면 추정이 산다."""
    words = speak([
        ("알림이 작업 맥락을 끊는다", 0, 40),
        ("깊은 수면과 렘수면 주기", 40, 80),
        ("의지가 아니라 환경 설계", 80, 120),
    ])
    assert infer_slide_marks(DOC, words, duration_sec=120).estimated is True


# ---------------------------------------------------------------------------
# 「아예 다른 내용」 판정 (match)
#
# 2026-08-08 제보: 자료와 무관한 녹음을 올리면 "잘 맞지 않아요" 만 나와서
# 애매한 분석 결과를 붙잡고 원인을 찾게 된다. 구간을 못 맞춘 것(weak)과
# 다른 파일을 올린 것(unrelated)을 갈라 말해야 한다. 임계는 실측으로 정했다
# (f04 UNRELATED_* 주석의 표) — 겹침·커버 둘 다 낮을 때만 단정한다.
# ---------------------------------------------------------------------------


def test_unrelated_speech_gets_a_decisive_verdict():
    """자료 어휘와 거의 안 겹치는 발화는 「아예 다른 내용」으로 판정한다."""
    words = speak([("김치찌개 레시피 돼지고기 두부 파", 0, 120)])
    got = infer_slide_marks(DOC, words, duration_sec=120)
    assert got.match == "unrelated"
    assert "다른 내용" in got.reason, "판정을 화면 문장에도 담아야 한다"
    assert got.estimated is False


def test_partial_match_stays_weak_not_unrelated():
    """자료 일부와는 또렷이 겹치면 단정하지 않는다 — 기존 안내로 남는다."""
    got = infer_slide_marks(PARTIAL_DOC, speak(PARTIAL_SPEECH), duration_sec=120)
    assert got.estimated is False, "구간 추정은 여전히 버려야 한다"
    assert got.match == "weak"
    assert "다른 내용" not in got.reason


def test_good_match_is_labeled_matched():
    words = speak([
        ("알림이 작업 맥락을 끊는다", 0, 40),
        ("깊은 수면과 렘수면 주기", 40, 80),
        ("의지가 아니라 환경 설계", 80, 120),
    ])
    assert infer_slide_marks(DOC, words, duration_sec=120).match == "matched"


def test_no_speech_is_unknown_not_unrelated():
    """발화가 없으면 판정 자체가 불가능하다 — 없는 근거로 단정하지 않는다."""
    assert infer_slide_marks(DOC, [], duration_sec=90).match == "unknown"


def test_deterministic():
    """같은 입력이면 늘 같은 결과다 — LLM 을 쓰지 않는 이유."""
    words = speak([
        ("알림이 작업 맥락을 끊는다", 0, 40),
        ("깊은 수면과 렘수면 주기", 40, 80),
        ("의지가 아니라 환경 설계", 80, 120),
    ])
    a = infer_slide_marks(DOC, words, duration_sec=120)
    b = infer_slide_marks(DOC, words, duration_sec=120)
    assert [(m.slide_no, m.start_sec, m.end_sec) for m in a.marks] == \
           [(m.slide_no, m.start_sec, m.end_sec) for m in b.marks]
    assert a.confidence == b.confidence
