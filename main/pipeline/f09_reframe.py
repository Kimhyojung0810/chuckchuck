"""
F-09 관점 바꾸기 — 같은 개념 · 같은 자료 근거로 **관점만 바꾼** 질문 하나 (2026-10-13 Q&A 「다른 주제로 → 같은 주제, 다른 관점」).

질문 생성(F-08)은 개념마다 질문 하나를 묶음으로 만든다 — 개념 하나를 다른 관점으로 다시 묻는 길이 없었다. 여기서는
이미 만든 질문(서버 색인의 원본, 채점 기준)을 받아 LLM 한 번으로 새 문장과 그 기대 답 요지를 쓰고, 계약은 코드가 지킨다:
- 관점은 정해진 다섯 중 하나(사례 · 근거 · 반례 · 원인 · 결과)
- 자료 줄(질문의 근거 장)에 기대어 쓴다 — 자료 밖 지식을 묻지 않게
- 새 질문은 물음으로 끝나고, 원래 질문과 같지 않고, 기대 답 요지를 그대로 흘리지 않는다
- 새 id 는 `{원래 id}~{관점}` — 서버 질문 색인에 올리면 `/qa/judge` 가 이 질문으로 채점한다(bridge `_handle_qa_reframe`)
함정 질문(trap)은 관점을 바꾸지 않는다 — 함정의 전제 · 사실을 새 문장에 옮기다 흘릴 수 있다.
"""
from __future__ import annotations

import re
from dataclasses import replace

from ._json_text import extract_json_object
from .contracts import Question
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm

#: 관점 — 키 · 화면 이름 · 프롬프트에 주는 뜻
PERSPECTIVES: dict[str, tuple[str, str]] = {
    "example": ("실제 사례", "이 개념이 실제로 나타나는 구체적인 사례나 장면을 들어 설명하게 하는 질문"),
    "evidence": ("근거", "이 주장을 뒷받침하는 자료 속 근거(수치 · 실험 · 관찰)를 대게 하는 질문"),
    "counter": ("반례", "이 주장이 성립하지 않는 경우나 한계를 생각하게 하는 질문"),
    "cause": ("원인", "왜 그렇게 되는지 원인이나 작동 원리를 설명하게 하는 질문"),
    "effect": ("결과", "그래서 무엇이 달라지는지 결과나 영향을 설명하게 하는 질문"),
}

REFRAME_MAX = 120
_DECK_LINES_MAX = 24

SYSTEM_PROMPT = """당신은 발표 심사위원이다. 발표자에게 이미 한 질문이 있고, 발표자가 같은 개념을 **다른 관점**에서 생각해 보게
새 질문 하나를 쓴다.

규칙:
1. 같은 개념을 묻는다. 다른 개념으로 넘어가지 마라.
2. 주어진 관점으로 묻는다. 원래 질문과 같은 것을 다른 말로 되풀이하지 마라.
3. **<deck> 의 자료 줄만 근거로 쓴다.** 자료에 없는 수치 · 사실을 묻거나 지어내지 마라. 자료로 답할 수 없는 관점이면 question 을 빈 문자열로 둔다.
4. 해요체 한 문장, 물음표로 끝난다. 답을 질문 안에 흘리지 마라.
5. answer_gist 는 자료 줄에 기대어 쓴 기대 답의 요지 한두 문장이다. why 는 이 관점으로 묻는 까닭 한 문장(해요체)이다.

출력은 JSON 객체 하나:
{"question": "<새 질문>", "answer_gist": "<기대 답 요지>", "why": "<까닭>"}
"""


class ReframeError(RuntimeError):
    """관점 바꾼 질문을 만들지 못했다(LLM 실패 · 계약 위반)."""


def _deck_lines(slidedoc, slide_nos: list[int]) -> list[str]:
    """질문의 근거 장의 글 줄 — slidedoc(dict 또는 SlideDoc)에서."""
    if not slidedoc:
        return []
    d = slidedoc.to_dict() if hasattr(slidedoc, "to_dict") else slidedoc
    want = set(slide_nos or [])
    out: list[str] = []
    for s in d.get("slides") or []:
        if want and int(s.get("slide_no") or 0) not in want:
            continue
        no = s.get("slide_no")
        if s.get("title"):
            out.append(f"[{no}장] {str(s['title']).strip()}")
        for b in s.get("blocks") or []:
            t = str((b or {}).get("text") or "").strip()
            if t:
                out.append(f"[{no}장] {t}")
    return out[:_DECK_LINES_MAX]


_SQUASH = re.compile(r"[\s\W_]+", re.UNICODE)


def _norm(t: str) -> str:
    return _SQUASH.sub("", t or "")


def valid_reframe(text: str, original: str, gist: str) -> bool:
    """새 질문 계약 — 물음으로 끝남 · 길이 · 원래 질문과 다름 · 기대 답 요지를 통째로 흘리지 않음."""
    t = (text or "").strip()
    if not t or len(t) > REFRAME_MAX or not t.endswith("?"):
        return False
    if _norm(t) == _norm(original):
        return False
    g = _norm(gist)
    if len(g) >= 12 and g in _norm(t):
        return False
    return True


def reframe_question(
    question: Question,
    perspective: str,
    *,
    slidedoc=None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> Question:
    """원래 질문 → 같은 개념을 관점만 바꾼 Question. 실패하면 ReframeError."""
    if perspective not in PERSPECTIVES:
        raise ReframeError(f"모르는 관점: {perspective}")
    if question.trap:
        raise ReframeError("함정 질문은 관점을 바꾸지 않아요")
    name, meaning = PERSPECTIVES[perspective]
    nos = [n for n in [*question.slide_nos, question.evidence_slide_no] if n]
    lines = _deck_lines(slidedoc, nos)
    if question.evidence_quote:
        lines = [f"[{question.evidence_slide_no or '?'}장] {question.evidence_quote}", *lines]
    if not lines:
        raise ReframeError("근거 자료 줄이 없어요")
    user = "\n".join([
        f"<concept>{question.label}</concept>",
        f"<original_question>{question.question}</original_question>",
        f"<perspective>{name} — {meaning}</perspective>",
        "<deck>", *lines, "</deck>",
    ])
    engine = llm if isinstance(llm, LLMProvider) else get_llm(llm, **(llm_kwargs or {}))
    try:
        raw = engine.complete(system=SYSTEM_PROMPT, user=user, temperature=0.4, max_tokens=800, json_mode=True)
        data = extract_json_object(raw)
    except Exception as e:  # noqa: BLE001 — 공급자 오류 · 파싱 실패 모두 같은 실패다
        raise ReframeError(f"LLM 응답을 읽지 못했어요: {e}") from e
    text = str(data.get("question") or "").strip()
    gist = str(data.get("answer_gist") or "").strip()
    why = str(data.get("why") or "").strip()
    if not valid_reframe(text, question.question, gist or question.answer_gist):
        raise ReframeError("새 질문이 계약에 맞지 않아요")
    return replace(
        question,
        id=f"{question.id}~{perspective}",
        question=text,
        why=why[:160] or f"같은 개념을 {name}의 관점에서 다시 물어요.",
        hint="",
        answer_gist=gist or question.answer_gist,
        answer_gist_parts=[],
    )
