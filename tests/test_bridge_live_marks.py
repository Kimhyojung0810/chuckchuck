"""직접 발표한 녹음의 실제 슬라이드 전환 기록은 F-04 추정으로 덮지 않는다 (10-08).

예전엔 /api/v1/transcribe 가 자료(slidedoc)만 같이 오면 무조건 발화 내용으로 구간을 되짚어 by_slide · marks 를 바꿨다.
그래서 폰에서 발표하며 넘긴 전환 시각이 추정값으로 바뀌었다. 업로드 녹음(균등 분할 marks)만 되짚어야 한다.
"""

from __future__ import annotations

from engine.contracts import SlideMark, Transcript
from engine.f04_infer_marks import even_slide_marks
from engine.f05_stt import split_by_slide
from demo.bridge import _marks_are_live, _marks_look_even, _resegment_transcript
from tests.test_infer_marks import DOC, speak

# 실제로는 60/20/40 초를 말했다 — 내용으로 되짚으면 이 구간이 나온다
WORDS = speak([
    ("알림이 작업 맥락을 끊는다 주의 전환이 일어난다", 0, 60),
    ("깊은 수면과 렘수면 90분 주기", 60, 80),
    ("의지가 아니라 환경 설계다 폰을 시야 밖으로", 80, 120),
])
# 발표자가 실제로 넘긴 기록 — 내용과 다르게 30초 · 90초에 넘겼다(일부러 어긋나게)
LIVE = [SlideMark(1, 0.0, 30.0, 1), SlideMark(2, 30.0, 90.0, 1), SlideMark(3, 90.0, 120.0, 1)]


def _transcript(marks: list[SlideMark]) -> Transcript:
    return Transcript(full_text=" ".join(w.text for w in WORDS), words=WORDS,
                      by_slide=split_by_slide(WORDS, marks), provider="t", duration_sec=120.0)


def test_균등_분할은_업로드본으로_본다() -> None:
    assert _marks_look_even(even_slide_marks(120, 3), 3)
    assert _marks_look_even(even_slide_marks(97.3, 3), 3)   # 끝 장이 반올림 꼬리를 먹어도
    assert not _marks_look_even(LIVE, 3)
    assert not _marks_look_even(even_slide_marks(120, 3)[:2], 3)   # 장 수가 다르면 균등 분할이 아니다


def test_프런트가_말한_출처가_모양보다_먼저다() -> None:
    assert _marks_are_live(even_slide_marks(120, 3), 3, "live")   # 우연히 고르게 넘겼어도 실제 기록
    assert not _marks_are_live(LIVE, 3, "even")
    assert _marks_are_live(LIVE, 3, None)                          # 옛 화면 — 모양으로 가린다
    assert not _marks_are_live(even_slide_marks(120, 3), 3, None)
    assert not _marks_are_live([], 3, None)


def test_직접_발표한_녹음은_전환_기록을_그대로_둔다() -> None:
    t = _transcript(LIVE)
    out = t.to_dict()
    before = [dict(s) for s in out["by_slide"]]
    _resegment_transcript(out, t, DOC, LIVE, "live")
    assert out["by_slide"] == before
    assert "marks" not in out or [m["start_sec"] for m in out["marks"]] == [0.0, 30.0, 90.0]
    assert out["marks_source"] == "live"
    assert out["marks_estimated"] is False
    assert out["marks_match"] == "matched"   # 「다른 발표인가」 판정은 그대로 계산한다


def test_옛_화면이_출처를_안_보내도_실제_기록은_지킨다() -> None:
    t = _transcript(LIVE)
    out = t.to_dict()
    before = [dict(s) for s in out["by_slide"]]
    _resegment_transcript(out, t, DOC, LIVE, None)
    assert out["by_slide"] == before
    assert out["marks_source"] == "live"


def test_업로드_녹음은_예전처럼_내용으로_되짚는다() -> None:
    even = even_slide_marks(120, 3)
    t = _transcript(even)
    out = t.to_dict()
    _resegment_transcript(out, t, DOC, even, "even")
    assert out["marks_source"] == "even"
    assert out["marks_estimated"] is True
    starts = [m["start_sec"] for m in out["marks"]]
    assert abs(starts[1] - 60) <= 10 and abs(starts[2] - 80) <= 10


def test_자료가_없으면_아무것도_안_바꾼다() -> None:
    t = _transcript(LIVE)
    out = t.to_dict()
    snap = dict(out)
    _resegment_transcript(out, t, None, LIVE, "live")
    assert out == snap
