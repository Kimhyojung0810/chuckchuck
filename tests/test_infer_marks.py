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
