"""
[F-06] 슬라이드 내용과 발표 맥락으로 핵심 개념을 뽑는 모듈입니다.
SlideDoc(+Context) → ConceptDoc. 개념 트리(위계)는 F-07 몫입니다.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .contracts import (
    ConceptDoc,
    ConceptError,
    Context,
    SlideConcepts,
    SlideDoc,
    Transcript,
)
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm
from .f05_stt import speech_for_slide

# 한 번에 너무 많은 장을 넣으면 LLM JSON 이 잘려 ConceptError 가 난다.
BATCH_SIZE = int(os.environ.get("CHUCKCHUCK_CONCEPT_BATCH_SIZE", "8"))
MAX_SLIDE_CHARS = int(os.environ.get("CHUCKCHUCK_CONCEPT_MAX_SLIDE_CHARS", "1200"))
MAX_TOKENS = int(os.environ.get("CHUCKCHUCK_CONCEPT_MAX_TOKENS", "8192"))

SYSTEM_PROMPT = """당신은 발표자료 분석가다.
주어진 슬라이드 원문과 발표 맥락을 보고, 슬라이드별로 핵심 개념만 추출한다.

규칙:
1. 자료에 없는 내용을 지어내지 마라.
2. concepts 항목은 "개념명: 한 줄 설명" 형식.
3. importance 는 core(청중/상황에 꼭 전달해야 함) 또는 support(보조·예시).
4. 글자가 거의 없는 슬라이드(text_sparse)는 speech_hint 가 있으면 그걸로 보완하고,
   없으면 topic/concepts 를 비워도 된다.
5. 부모-자식 관계(트리)는 만들지 마라. 그건 다음 단계 일이다.
6. 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.
7. 요청된 모든 slide_no 를 slides 배열에 포함하라.

출력 스키마:
{
  "slides": [
    {
      "slide_no": 1,
      "title": "슬라이드 제목",
      "topic": "이 슬라이드가 통으로 무엇에 관한지 한 줄",
      "keywords": ["키워드1", "키워드2"],
      "concepts": ["개념A: 한 줄 설명", "개념B: 한 줄 설명"],
      "importance": "core"
    }
  ]
}
"""


def _clip(text: str, limit: int = MAX_SLIDE_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n…(이하 생략)"


def _build_user_prompt(
    slides: list,
    doc: SlideDoc,
    ctx: Context,
    transcript: Transcript | None = None,
    *,
    batch_note: str = "",
) -> str:
    parts = [
        ctx.to_prompt_block(),
        "",
        f"파일명: {doc.file_name}",
        f"총 슬라이드: {doc.total_slides}",
    ]
    if batch_note:
        parts.append(batch_note)
    parts += ["", "아래 슬라이드들을 분석하라. 출력 JSON 의 slides 에 아래 번호만 포함."]
    for s in slides:
        parts.append(f"### 슬라이드 {s.slide_no}: {s.title or '(제목 없음)'}")
        if s.text_sparse:
            parts.append("[경고] text_sparse=true — 글자가 거의 없음")
        if s.image_only:
            parts.append("[경고] image_only=true — 도식/이미지 위주")
        raw = _clip(s.raw_text) or "(텍스트 없음)"
        parts.append(raw)
        if transcript is not None:
            speech = _clip(speech_for_slide(transcript, s.slide_no), 600)
            if speech.strip():
                parts.append(f"[speech_hint] {speech}")
        parts.append("")
    return "\n".join(parts)


def _repair_json_text(text: str) -> str:
    """잘린/느슨한 JSON 을 최대한 복구."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    # 흔한 trailing comma
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # 첫 { 부터
    start = text.find("{")
    if start > 0:
        text = text[start:]

    # 닫히지 않은 문자열/괄호를 잘라 마지막 완전한 객체까지만
    if text.count("{") > text.count("}"):
        # 마지막 완전한 슬라이드 객체까지만 유지 시도
        last_complete = text.rfind("}")
        if last_complete > 0:
            chunk = text[: last_complete + 1]
            # slides 배열이 열려 있으면 닫기
            if '"slides"' in chunk and chunk.count("[") > chunk.count("]"):
                chunk += "]" * (chunk.count("[") - chunk.count("]"))
            if chunk.count("{") > chunk.count("}"):
                chunk += "}" * (chunk.count("{") - chunk.count("}"))
            text = chunk

    # 배열/객체 균형 맞추기
    if text.count("[") > text.count("]"):
        text += "]" * (text.count("[") - text.count("]"))
    if text.count("{") > text.count("}"):
        text += "}" * (text.count("{") - text.count("}"))

    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    candidates = [text]
    repaired = _repair_json_text(text)
    if repaired != text:
        candidates.append(repaired)
    m = re.search(r"\{.*\}", repaired, flags=re.S)
    if m:
        candidates.append(m.group(0))

    last_err: Exception | None = None
    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError as e:
            last_err = e
            continue

    # 슬라이드 객체만 주워 담기
    objs = re.findall(
        r"\{\s*\"slide_no\"\s*:\s*\d+\s*,.*?\}\s*(?=,|\])",
        repaired,
        flags=re.S,
    )
    slides = []
    for o in objs:
        try:
            slides.append(json.loads(_repair_json_text(o)))
        except json.JSONDecodeError:
            continue
    if slides:
        return {"slides": slides}

    raise ConceptError(
        f"LLM 응답 JSON 파싱 실패: {last_err}. preview={text[:400]!r}"
    )


def _call_batch(
    engine: LLMProvider,
    slides: list,
    doc: SlideDoc,
    ctx: Context,
    transcript: Transcript | None,
    *,
    batch_i: int,
    batch_n: int,
) -> list[dict]:
    note = ""
    if batch_n > 1:
        note = f"배치 {batch_i}/{batch_n}: 이 응답에는 이 배치의 슬라이드만 포함."
    raw = engine.complete(
        system=SYSTEM_PROMPT,
        user=_build_user_prompt(slides, doc, ctx, transcript, batch_note=note),
        temperature=0.2,
        max_tokens=MAX_TOKENS,
    )
    data = _extract_json(raw)
    out = data.get("slides", [])
    if not isinstance(out, list):
        raise ConceptError(f"slides 배열이 없습니다: {type(out)}")
    return [s for s in out if isinstance(s, dict) and "slide_no" in s]


def extract_concepts(
    doc: SlideDoc,
    context: Context | dict | None = None,
    *,
    transcript: Transcript | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
    batch_size: int | None = None,
) -> ConceptDoc:
    """
    SlideDoc(+Context, 선택적 Transcript) → ConceptDoc.

    transcript 를 넘기면 text_sparse 슬라이드를 발화로 보완한다.
    장수가 많으면 batch_size 단위로 나눠 호출한다.
    """
    if context is None:
        ctx = Context()
    elif isinstance(context, dict):
        ctx = Context.from_dict(context)
    else:
        ctx = context

    engine = (
        llm
        if isinstance(llm, LLMProvider)
        else get_llm(llm, **(llm_kwargs or {}))
    )

    size = batch_size or BATCH_SIZE
    size = max(1, size)
    chunks = [doc.slides[i : i + size] for i in range(0, len(doc.slides), size)]
    merged: list[dict] = []
    for i, chunk in enumerate(chunks, start=1):
        merged.extend(
            _call_batch(
                engine,
                chunk,
                doc,
                ctx,
                transcript,
                batch_i=i,
                batch_n=len(chunks),
            )
        )

    by_no = {int(s["slide_no"]): s for s in merged if "slide_no" in s}

    slides: list[SlideConcepts] = []
    for src in doc.slides:
        got = by_no.get(src.slide_no, {})
        slides.append(SlideConcepts(
            slide_no=src.slide_no,
            title=got.get("title") or src.title,
            topic=got.get("topic", ""),
            keywords=list(got.get("keywords", [])),
            concepts=list(got.get("concepts", [])),
            raw_text=src.raw_text,
            importance=got.get("importance", "core"),
        ))

    return ConceptDoc(
        file_name=doc.file_name,
        total_slides=doc.total_slides,
        slides=slides,
        model=engine.name,
    )
