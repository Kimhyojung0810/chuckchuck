"""
외운 답(자료 문장 옮기기) 가리기 — 2026-10-17 Q&A 개편 5단계 (계획 §0-1 핵심 원칙 · 시장조사 A6).

「이 질문에 잘 답하려면 핵심 논리를 이해해야 하나, 자료를 외우기만 해도 되나」 — 판정도 같은 잣대로 본다. 왜 · 충분한가 · 어떻게
이어지나 · 어디까지 맞나를 묻는 질문에 **자료 문장을 거의 그대로 옮겨 놓기만** 하고 자기 말로 잇지 않은 답은 이해한 답이 아니다.
1~3단계 test 측정: 근거 줄을 그대로 읽은 답이 모범답과 같은 판정을 받은 비율 25%(판별 0.75, 기준 ≥ 0.90).

LLM 없이 글자로 본다 — 답의 글자 4개 조각이 자료에 거의 다(RECITAL_COVER) 있고, 자료에 없는 **잇는 말**(때문 · 그래서 · 지만 …)이 없다.
"""
from __future__ import annotations

import re

#: 답 글자 4개 조각 중 자료에도 있는 몫이 이 이상이면 「자료 문장 옮기기」 후보다.
RECITAL_COVER = 0.82
#: 너무 짧은 답은 보지 않는다 (짧은 답 가드가 따로 본다).
RECITAL_MIN_CHARS = 12
#: 깊은 질문의 패턴 (P1 핵심 주장 · P3 빈 고리 · P9 함정은 근거 줄을 대는 것 자체가 답일 수 있어 뺀다).
DEEP_PATTERNS = frozenset({"P2", "P4", "P5", "P6", "P7", "P8", "P10"})
_DEEP_Q_RE = re.compile(r"충분|어떻게\s*이어|이어지|왜\s|어디까지|의미|함의|제약|약화|옮기면|적용하|달라지|바뀌면|해석|뜻하")
_WRAP_RE = re.compile(r"자료(?:\s*\d+\s*장)?(?:에는|에서는|에|는|은)?|라고\s*(?:나와\s*있어요|나와요|해요|했어요|적혀\s*있어요|돼\s*있어요)|"
                      r"이라고|[「」『』“”\"'|]|Chart Type:\s*\w+|Figure Type:\s*\w+")
_CONNECT_RE = re.compile(r"때문|니까|므로|그래서|따라서|즉\s|라서|여서|해서|덕분|탓|결국|반면|오히려|그러니|그렇다면|만큼|수록|려면|"
                         r"지만|는데|으니|이므로|라는\s*점|뜻이|의미|셈이|이니")
_SQ_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def _sq(t: str) -> str:
    return _SQ_RE.sub("", t or "")


def deep_question(question: str, pattern: str = "") -> bool:
    if pattern:
        return pattern in DEEP_PATTERNS
    return bool(_DEEP_Q_RE.search(question or ""))


def recital(answer: str, deck_texts: list[str] | tuple[str, ...]) -> bool:
    """답이 자료 문장을 거의 그대로 옮기기만 했나 (자료에 없는 잇는 말이 없다)."""
    body = _WRAP_RE.sub(" ", answer or "")
    a = _sq(body)
    if len(a) < RECITAL_MIN_CHARS:
        return False
    deck = _sq(" ".join(deck_texts))
    if not deck:
        return False
    grams = {a[i:i + 4] for i in range(len(a) - 3)}
    dgrams = {deck[i:i + 4] for i in range(len(deck) - 3)}
    if not grams or len(grams & dgrams) / len(grams) < RECITAL_COVER:
        return False
    for m in _CONNECT_RE.finditer(body):
        around = _sq(body[max(0, m.start() - 4): m.end() + 2])
        if around and around not in deck:
            return False
    return True


__all__ = ["recital", "deep_question", "RECITAL_COVER", "DEEP_PATTERNS"]
