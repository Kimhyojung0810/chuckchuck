"""
실API 연결을 증명하는 통합 테스트입니다.

tests/ 의 나머지 테스트는 모두 llm="mock" 을 못박아 두어서
"실제로 LLM 에 붙어 있는가" 를 증명하지 못합니다. 이 파일이 그 빈칸을 메웁니다.

    RUN_LIVE_TESTS=1 python -m pytest tests/test_live_pipeline.py -v -s

기본값은 skip 입니다. 실제 과금·네트워크를 타므로 기본 테스트 경로에 넣지 않습니다.

이 테스트가 증거로서 의미를 가지려면 "가짜일 때 실패" 해야 합니다.
그래서 두 축으로 판별력을 함께 검증합니다.

    REASONING_BACKEND=mock  → 개념 추출 테스트가 실패해야 한다 (LLM 판별)
    UPSTAGE_API_KEY=invalid → 파싱 테스트가 실패해야 한다 (DocParse 판별)

두 경우에 실패한다는 사실이, 통과했을 때 그 통과를 실연결 증거로 읽을 근거입니다.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from chuckchuck import Context, SlideDoc, extract_concepts, parse_document
from chuckchuck.contracts import ConceptDoc

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "demo" / "YEHS_demo" / "assets" / "samples" / "imu2clip_sample.pdf"
PPTX = ROOT / "fixtures" / "live_sample.pptx"

# examples/make_live_pptx_fixture.py 가 PPTX 본문에 심어 둔 희귀 문자열.
# DocParse 가 실제로 그 파일을 읽었을 때만 응답에 존재할 수 있다.
PPTX_SENTINEL = "ZEPHYRLOCK-7742"

# MockLLM(chuckchuck/providers/llm_impl.py)이 내는 고정 문구들.
# 실제 LLM 응답에 이 문구가 섞일 확률은 사실상 0 이다.
MOCK_SIGNATURES = (
    "슬라이드 핵심 한 줄",
    "모의 개념",
    "모의 판정",
    "모의 최상위 개념",
    "모의 하위 개념",
    "모의 근거 발화 인용",
)

# 자료의 주제어. 실제 파싱·추론을 거쳤다면 이 중 하나는 등장해야 한다.
PDF_TOPIC_TERMS = ("IMU", "imu", "관성", "센서", "sensor", "multimodal", "contrastive")
PPTX_TOPIC_TERMS = ("관성", "IMU", "센서", "대조학습", "행동")

_RUN = os.environ.get("RUN_LIVE_TESTS", "").strip().lower() in ("1", "true", "yes")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _RUN,
        reason="실API 테스트입니다. RUN_LIVE_TESTS=1 을 주면 실행합니다.",
    ),
]


def _backend() -> str:
    """RED 검증 때 mock 으로 갈아끼울 수 있도록 env 를 그대로 따른다."""
    return os.environ.get("REASONING_BACKEND", "solar").strip() or "solar"


def _all_text(doc: SlideDoc) -> str:
    return "\n".join(s.raw_text or "" for s in doc.slides)


def _all_concept_text(cd: ConceptDoc) -> str:
    parts: list[str] = []
    for s in cd.slides:
        parts += [s.title or "", s.topic or "", *s.keywords, *s.concepts]
    return "\n".join(parts)


def _assert_no_mock_text(text: str, where: str) -> None:
    hits = [sig for sig in MOCK_SIGNATURES if sig in text]
    assert not hits, f"{where}: mock LLM 서명 문구가 섞여 있습니다 → {hits}"


def _show_slides(doc: SlideDoc, limit: int = 3) -> None:
    print(f"\n[DocParse 실응답] {doc.file_name} / {doc.total_slides}장")
    for s in doc.slides[:limit]:
        head = (s.raw_text or "").strip().replace("\n", " ")[:160]
        print(f"  - {s.slide_no}장 title={s.title!r} chars={s.total_char_count}")
        print(f"      {head}")


def _show_concepts(cd: ConceptDoc, limit: int = 3) -> None:
    print(f"\n[LLM 실응답] model={cd.model} / {cd.total_slides}장")
    for s in cd.slides[:limit]:
        print(f"  - {s.slide_no}장 topic={s.topic!r}")
        print(f"      keywords={s.keywords}")
        for c in s.concepts[:3]:
            print(f"      · {c}")


# --------------------------------------------------------------------------
# F-01 : 문서 → 실제 Upstage DocParse
# --------------------------------------------------------------------------


def test_pdf_reaches_real_docparse() -> None:
    """PDF 를 올리면 실제 DocParse 가 슬라이드별 원문을 돌려준다."""
    assert PDF.is_file(), f"샘플 PDF 가 없습니다: {PDF}"

    doc = parse_document(PDF)
    _show_slides(doc)

    assert doc.total_slides >= 10, f"23쪽 자료인데 {doc.total_slides}장만 나왔습니다."
    assert len(doc.slides) == doc.total_slides

    text = _all_text(doc)
    assert len(text) > 500, f"본문이 {len(text)}자뿐입니다. 빈 응답이 의심됩니다."
    assert any(t in text for t in PDF_TOPIC_TERMS), (
        f"자료 주제어가 하나도 없습니다. 실제 파싱이 아닐 수 있습니다: {PDF_TOPIC_TERMS}"
    )


def test_pptx_reaches_real_docparse() -> None:
    """PPTX 를 올리면 실제 DocParse 가 본문 텍스트를 그대로 돌려준다."""
    assert PPTX.is_file(), (
        f"픽스처가 없습니다: {PPTX}\n"
        "python examples/make_live_pptx_fixture.py 로 생성하세요."
    )

    doc = parse_document(PPTX)
    _show_slides(doc)

    assert doc.total_slides == 3, f"3장 자료인데 {doc.total_slides}장이 나왔습니다."

    text = _all_text(doc)
    assert PPTX_SENTINEL in text, (
        f"sentinel {PPTX_SENTINEL!r} 이 응답에 없습니다. "
        "DocParse 가 실제로 이 파일을 읽지 않았다는 뜻입니다."
    )
    assert any(t in text for t in PPTX_TOPIC_TERMS)


# --------------------------------------------------------------------------
# F-06 : 슬라이드 → 실제 LLM 개념 추출
# --------------------------------------------------------------------------


def test_pptx_concepts_come_from_real_llm() -> None:
    """PPTX 슬라이드가 실제 LLM 으로 넘어가 자료 기반 개념이 돌아온다."""
    doc = parse_document(PPTX)
    ctx = Context(
        situation="학회 발표 리허설",
        audience="머신러닝 연구자",
        duration_min=5,
    )

    cd = extract_concepts(doc, ctx, llm=_backend())
    _show_concepts(cd)

    assert cd.model != "mock", f"mock LLM 이 응답했습니다 (model={cd.model})."
    assert cd.total_slides == doc.total_slides

    text = _all_concept_text(cd)
    _assert_no_mock_text(text, "PPTX 개념 추출")

    assert any(s.concepts for s in cd.slides), "어느 장에도 개념이 없습니다."
    assert any(t in text for t in PPTX_TOPIC_TERMS), (
        "개념에 자료 주제어가 없습니다. 자료를 안 읽고 답한 것일 수 있습니다."
    )


def test_pdf_concepts_come_from_real_llm() -> None:
    """PDF 슬라이드도 같은 경로로 실제 LLM 응답을 받는다."""
    doc = parse_document(PDF)
    ctx = Context(
        situation="연구 논문 소개 발표",
        audience="머신러닝 연구자",
        duration_min=10,
    )

    cd = extract_concepts(doc, ctx, llm=_backend())
    _show_concepts(cd)

    assert cd.model != "mock", f"mock LLM 이 응답했습니다 (model={cd.model})."

    text = _all_concept_text(cd)
    _assert_no_mock_text(text, "PDF 개념 추출")

    filled = [s for s in cd.slides if s.concepts]
    assert len(filled) >= 5, f"개념이 채워진 장이 {len(filled)}장뿐입니다."
    assert any(t in text for t in PDF_TOPIC_TERMS)
