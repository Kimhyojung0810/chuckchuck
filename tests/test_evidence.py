"""
`_evidence.clean_slide_text` — 슬라이드 본문에서 LLM 이 읽을 글만 남기는지.

Upstage 출력 모양(이미지 마크다운 + <figcaption> 블록 + HTML)을 고정해 둔다.
이 정제가 무너지면 개념당 400자 예산이 다시 캡션으로 채워진다 (2026-09-10 실측 70%).
"""

from chuckchuck._evidence import clean_slide_text, markup_ratio

UPSTAGE_LIKE = (
    "집중은 “시선”이 아니라 “작업 맥락”이다\n"
    "알림은 눈길만 빼앗는 것이 아니라 , 머릿속 작업 상태를 바꾼다 .\n"
    "![image](/image/placeholder)\n\n"
    "  <figcaption>\n"
    '    <p class="figure-type">natural image,table,product photography</p>\n'
    '    <p class="figure-description">A well-lit, modern wooden desk setup is captured '
    "in a natural indoor setting with a laptop and a phone.</p>\n"
    "  </figcaption>\n"
    "| 목표 | 지금 무엇을 끝내려 했는가 |\n"
)


def test_캡션과_이미지_마크다운을_지운다():
    out = clean_slide_text(UPSTAGE_LIKE)
    assert "figcaption" not in out
    assert "figure-description" not in out
    assert "![image]" not in out
    assert "wooden desk" not in out


def test_본문과_표는_남긴다():
    out = clean_slide_text(UPSTAGE_LIKE)
    assert "작업 맥락" in out
    assert "머릿속 작업 상태를 바꾼다" in out
    assert "| 목표 | 지금 무엇을 끝내려 했는가 |" in out


def test_줄바꿈을_한_줄로_접는다():
    assert "\n" not in clean_slide_text(UPSTAGE_LIKE)


def test_태그_없이_새어_나온_긴_영문_설명도_지운다():
    raw = "알림 발생 소리 · 진동 · 팝업 A smartphone lying on a desk with a glowing notification banner on screen 주의 포획"
    out = clean_slide_text(raw)
    assert "smartphone lying" not in out
    assert "알림 발생" in out and "주의 포획" in out


def test_짧은_영문_용어는_살린다():
    out = clean_slide_text("Deep Work 상태에서 GPU 사용률은 92% 였다")
    assert "Deep Work" in out and "GPU" in out and "92%" in out


def test_빈_입력은_빈_문자열():
    assert clean_slide_text("") == ""
    assert clean_slide_text(None) == ""
    assert markup_ratio("") == 0.0


def test_잡음_비율은_캡션이_많을수록_커진다():
    assert markup_ratio("순수 본문 한 줄") == 0.0
    assert markup_ratio(UPSTAGE_LIKE) > 0.5
