"""
질문 코칭(F-08·F-09)이 LLM 에 실을 **자료 근거**를 고르고 정제하는 공용 헬퍼입니다.
`_match.py` 와 같은 자리다 — 기능 모듈(fXX_*)이 아니라 유틸이라, 어느 모듈에서
import 해도 정책 위반이 아닙니다 (DEV_POLICY §4-1 은 F-모듈끼리를 말한다).

왜 따로 두나 (2026-09-10 실측):
- Upstage 가 돌려준 `Slide.raw_text` 는 70% 가 이미지 캡션·HTML 이었다
  (`<figcaption><p class="figure-description">A well-lit, modern wooden desk…`).
  개념당 400자 예산이 그 잡음으로 채워져 정작 본문이 안 실렸다.
- F-07 이 핵심 개념에 근거 장을 12장 전부 붙여서, "근거 장 본문" 이 덱 전체가 됐다.
  같은 400자를 세 개념이 똑같이 받으니 질문이 사전 정의처럼 나왔다.

이 파일은 순수 함수만 둔다. LLM 을 부르지 않고, contracts 타입만 받는다.
"""

from __future__ import annotations

import re

#: 이미지 자리표시자와 캡션 블록. Upstage document-parse 의 markdown 출력 모양이다.
_FIGCAPTION_RE = re.compile(r"<figcaption>.*?</figcaption>", re.S | re.I)
_IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
#: 남은 태그(<p>, <br>, <table> 안쪽 등). 표의 `|` 구분은 문자라 살아남는다.
_TAG_RE = re.compile(r"<[^>]+>")
#: 캡션을 걷어내고 남는 영문 문장 조각 — 캡션 밖으로 새어 나온 설명문을 잡는다.
#: 한글 자료에서 40자 넘는 순수 영문 구절은 본문이 아니라 이미지 설명이다.
_LONG_LATIN_RE = re.compile(r"(?<![가-힣])[A-Za-z][A-Za-z0-9 ,.'\"()-]{40,}")
_WS_RE = re.compile(r"\s+")


def clean_slide_text(raw_text: str) -> str:
    """
    슬라이드 본문에서 LLM 이 읽을 글만 남긴다.

    - 이미지 마크다운·`<figcaption>` 블록·HTML 태그를 지운다
    - 긴 영문 설명 조각을 지운다 (캡션이 태그 없이 새어 나온 경우)
    - 줄바꿈을 접어 한 줄로 만든다 — 프롬프트의 한 줄짜리 개념 항목 구조를 지킨다
      (f08 `_slide_body` · f14 `_slides_block` 과 같은 처리)

    표는 `| a | b |` 꼴 그대로 둔다. 수치 비교 질문의 근거가 거기 있다.
    """
    text = raw_text or ""
    if not text.strip():
        return ""
    text = _FIGCAPTION_RE.sub(" ", text)
    text = _IMAGE_MD_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = _LONG_LATIN_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def markup_ratio(raw_text: str) -> float:
    """
    본문 중 잡음(이미지·캡션·태그)이 차지하는 비율 0.0~1.0. 측정 도구가 쓴다 —
    "프롬프트에 실린 400자 중 몇 자가 글이었나" 를 숫자로 남기기 위해서다.
    """
    text = raw_text or ""
    if not text:
        return 0.0
    kept = len(clean_slide_text(text))
    return max(0.0, 1.0 - kept / max(1, len(_WS_RE.sub(" ", text).strip())))
