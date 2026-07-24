"""
슬라이드 marks와 단어 시각으로 발화를 나누는 로직(unit test)입니다.
"""

from chuckchuck.contracts import SlideMark, Word
from chuckchuck.f05_stt import split_by_slide


def test_split_assigns_words_to_marks():
    marks = [
        SlideMark(slide_no=1, start_sec=0.0, end_sec=5.0, visit=1),
        SlideMark(slide_no=2, start_sec=5.0, end_sec=10.0, visit=1),
    ]
    words = [
        Word("안녕", 0.0, 0.5),
        Word("하세요", 0.5, 1.0),
        Word("다음", 5.2, 5.5),
        Word("슬라이드입니다", 5.5, 6.2),
    ]
    out = split_by_slide(words, marks)
    assert len(out) == 2
    assert out[0].slide_no == 1
    assert "안녕" in out[0].text
    assert out[1].slide_no == 2
    assert "다음" in out[1].text


def test_sentence_lock_keeps_words_on_start_slide():
    marks = [
        SlideMark(slide_no=1, start_sec=0.0, end_sec=3.0, visit=1),
        SlideMark(slide_no=2, start_sec=3.0, end_sec=8.0, visit=1),
    ]
    # 문장이 슬라이드 경계를 넘어감 — "입니다" 전까지 1번에 잠금
    words = [
        Word("이것은", 2.5, 2.8),
        Word("이어지는", 3.1, 3.4),
        Word("문장입니다", 3.4, 3.9),
        Word("새문장요", 4.0, 4.5),
    ]
    out = split_by_slide(words, marks)
    assert "이것은" in out[0].text
    assert "이어지는" in out[0].text
    assert "문장입니다" in out[0].text
    assert "새문장요" in out[1].text


def test_revisit_preserved():
    marks = [
        SlideMark(slide_no=1, start_sec=0.0, end_sec=2.0, visit=1),
        SlideMark(slide_no=2, start_sec=2.0, end_sec=4.0, visit=1),
        SlideMark(slide_no=1, start_sec=4.0, end_sec=6.0, visit=2),
    ]
    # 어미(요/다)로 문장을 끝내야 잠금이 풀리고 다음 구간으로 넘어간다
    words = [
        Word("첫번째요", 0.5, 0.8),
        Word("두번째요", 2.5, 2.8),
        Word("다시첫번째요", 4.5, 4.9),
    ]
    out = split_by_slide(words, marks)
    assert out[0].visit == 1 and out[0].slide_no == 1
    assert "첫번째요" in out[0].text
    assert out[1].slide_no == 2 and "두번째요" in out[1].text
    assert out[2].visit == 2 and out[2].slide_no == 1
    assert "다시첫번째요" in out[2].text
