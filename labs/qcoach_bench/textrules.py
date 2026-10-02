"""채점이 쓰는 글자 규칙 — 정규화 · 낱말(조사 한 겹 떼기) · 덱 대조 · 수치. 형태소 분석기 없이 문자열로만."""
from __future__ import annotations

import re
import unicodedata

JOSA = ("으로써", "으로서", "에서는", "에서도", "이라는", "이라고", "라는", "라고", "으로", "에서", "에게", "에는", "까지", "부터",
        "처럼", "보다", "이나", "이란", "은", "는", "이", "가", "을", "를", "의", "에", "도", "로", "와", "과", "만", "나", "란")
#: 질문의 뼈대 말 — 어느 덱의 질문에나 나오는 묻는 말이라 근거 대조에서 뺀다
FUNC = {"왜", "어떻게", "무엇", "무엇인가요", "어떤", "설명", "설명해", "설명해주세요", "생각", "생각하나요", "이유",
        "의미", "근거", "말씀", "발표", "발표에서", "자료", "자료에서", "슬라이드", "그렇다면", "그러면", "그런데", "이것", "그것",
        "어느", "어디", "얼마나", "가요", "나요", "인가요", "있나요", "한다고", "했는데", "했어요", "말했는데", "보면", "때문",
        "결과", "차이", "관계", "연결", "구체적", "구체적으로", "실제로", "정말", "다른", "같은", "모두", "가장", "있다", "없다",
        "한다", "된다", "합니다", "인데", "하는", "되는", "있는", "없는", "다고", "라면", "이라면", "경우", "부분"}
_WORD_RE = re.compile(r"[가-힣A-Za-z][가-힣A-Za-z0-9%]*")
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
#: 「자료 11장」 의 장 번호는 내용 수치가 아니다 (2026-10-02 채점기 버그 — baseline 채점 전에 고침)
_SLIDE_REF_RE = re.compile(r"\d+\s*장")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def squash(s: str) -> str:
    """공백을 다 빼고 소문자 — 띄어쓰기가 달라도 같은 글로 본다."""
    return re.sub(r"\s+", "", nfc(s)).lower()


def _strip_josa(word: str) -> str:
    for j in JOSA:
        if len(word) > len(j) + 1 and word.endswith(j):
            return word[: -len(j)]
    return word


def tokens(text: str) -> list[str]:
    """내용어 — 끝 조사 한 겹을 떼고, 두 글자 미만·뼈대 말·홀로 떨어진 조사(「…」라고)는 뺀다."""
    words = (_strip_josa(w) for w in _WORD_RE.findall(nfc(text)))
    return [w for w in words if len(w) >= 2 and w not in FUNC and w not in JOSA]


def found(tok: str, text_sq: str) -> bool:
    """낱말이 (공백 뺀) 글에 있는가 — 네 글자 이상은 끝 두 글자(어미)를 떼고 본다."""
    stem = tok if len(tok) <= 3 else tok[: max(3, len(tok) - 2)]
    return stem.lower() in text_sq


def numbers(text: str) -> set[str]:
    """글 속 수치 — 천 단위 쉼표와 소수 끝 0 을 떼어 같은 수는 같은 글자로. 장 번호는 뺀다."""
    out = set()
    for n in _NUMBER_RE.findall(_SLIDE_REF_RE.sub(" ", nfc(text))):
        n = n.replace(",", "").rstrip(".")
        out.add(n.rstrip("0").rstrip(".") if "." in n else n)
    return out
