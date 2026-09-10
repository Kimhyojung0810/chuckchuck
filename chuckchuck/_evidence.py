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
- 그래프는 "경로=A > B · 연결=C, D" 이름 한 줄로만 실렸다. 이웃의 요약·간선 종류가
  없으면 모델은 관계를 캐묻지 못하고 정의를 묻는다.

이 파일은 순수 함수만 둔다. LLM 을 부르지 않고, contracts 타입만 받는다.
"""

from __future__ import annotations

import os
import re

from ._match import contains_tokens, norm_tokens

#: 이미지 자리표시자와 캡션 블록. Upstage document-parse 의 markdown 출력 모양이다.
_FIGCAPTION_RE = re.compile(r"<figcaption>.*?</figcaption>", re.S | re.I)
_IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
#: 남은 태그(<p>, <br>, <table> 안쪽 등). 표의 `|` 구분은 문자라 살아남는다.
_TAG_RE = re.compile(r"<[^>]+>")
#: 캡션을 걷어내고 남는 영문 문장 조각 — 캡션 밖으로 새어 나온 설명문을 잡는다.
#: 한글 자료에서 40자 넘는 순수 영문 구절은 본문이 아니라 이미지 설명이다.
_LONG_LATIN_RE = re.compile(r"(?<![가-힣])[A-Za-z][A-Za-z0-9 ,.'\"()-]{40,}")
_WS_RE = re.compile(r"\s+")

#: 한 개념에 붙일 근거 장 수. F-07 이 12장을 다 붙여도 여기서 이만큼만 남는다.
#: f08 `HINT_SLIDE_MAX` 와 같은 값 — 힌트가 가리키는 장과 프롬프트에 실린 장이 같아야 한다.
ANCHOR_MAX = int(os.environ.get("CHUCKCHUCK_QA_ANCHOR_SLIDES", "3"))
#: 이웃 개념 상세 줄 수. f08 `NEIGHBOR_MAX` 와 같은 값.
NEIGHBOR_DETAIL_MAX = 5


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


def _content_tokens(text: str) -> list[str]:
    """대조용 토큰. 한 글자는 우연히 다 걸리므로 버린다."""
    return [t for t in norm_tokens(text) if len(t) >= 2]


def anchor_slides(
    label: str,
    summary: str,
    slide_nos: list[int],
    texts: dict[int, str],
    k: int = ANCHOR_MAX,
) -> list[int]:
    """
    이 개념을 **실제로 뒷받침하는 장** 을 최대 k 개 고른다 (장 번호 오름차순).

    후보는 F-07 이 준 `slide_nos` 다 — 그래프의 조인 키를 바꾸지 않고 그 안에서
    좁힌다. 점수는 개념 이름·요약의 낱말이 그 장 본문에 몇 개 있는가이고, 이름이
    통째로 나오는 장은 가산한다. 본문에 이름도 요약도 안 나오면(그림뿐인 장)
    F-07 순서대로 앞 k 장을 쓴다 — 예전 힌트가 하던 그대로다.

    `texts` 는 slide_no → 정제 본문(`clean_slide_text`). 비어 있으면 자를 근거가
    없으니 slide_nos 앞 k 장이다.
    """
    wanted = list(slide_nos or [])
    candidates = [n for n in (wanted or sorted(texts)) if n in texts]
    if not candidates:
        return wanted[:k]
    query = set(_content_tokens(f"{label} {summary}"))
    name = _content_tokens(label)
    scored: list[tuple[int, int]] = []
    for no in candidates:
        tokens = _content_tokens(texts[no])
        present = set(tokens)
        score = sum(1 for t in query if t in present)
        if name and contains_tokens(tokens, name):
            score += 2
        scored.append((score, no))
    scored.sort(key=lambda s: (-s[0], s[1]))
    top = [no for score, no in scored if score > 0][:k]
    return sorted(top or candidates[:k])


def neighbor_lines(node, graph, texts: dict[int, str] | None = None) -> list[str]:
    """
    이웃 개념을 **요약·간선 종류·근거 장**과 함께 한 줄씩.

    "연결=환경 설계, 집중 루틴" 만으로는 모델이 두 개념이 내용상 어떤 관계인지
    모른다. 요약이 나란히 있어야 "A 가 B 를 줄이는가" 같은 관계 질문이 나온다.
    간선 방향은 발표자가 고른 것이 아니라 우리가 추론한 배치라(f08 규칙 3-1),
    상위/하위/관련으로만 적고 그 배치를 묻지 않게 하는 문구는 호출자가 붙인다.
    """
    kinds: dict[str, str] = {}
    for e in graph.edges:
        if e.from_id == node.id:
            kinds[e.to_id] = "하위" if e.kind == "parent" else "관련"
        elif e.to_id == node.id:
            kinds[e.from_id] = "상위" if e.kind == "parent" else "관련"
    ranked = sorted(graph.neighbors_of(node.id), key=lambda n: (-n.weight, n.id))
    lines: list[str] = []
    for other in ranked[:NEIGHBOR_DETAIL_MAX]:
        line = f"{kinds.get(other.id, '관련')} · {other.label}"
        if other.summary:
            line += f": {other.summary}"
        nos = anchor_slides(other.label, other.summary, other.slide_nos, texts or {})
        if nos:
            line += f" [S{','.join(str(n) for n in nos)}]"
        lines.append(line)
    return lines


def section_line(node, graph) -> str:
    """이 개념이 발표의 어느 구간(도입·본론·결론)에 있는지 한 줄. 없으면 빈 문자열."""
    if not node.slide_nos:
        return ""
    section = graph.section_of(min(node.slide_nos))
    if section is None:
        return ""
    return f"구간={section.name} ({section.slide_role})"


# ---------------------------------------------------------------------------
# 인용 · 빈칸 — 「모르겠어요」 사다리의 재료. LLM 을 부르지 않는다.
# ---------------------------------------------------------------------------

#: 문장 경계. 마침표·물음표 뒤, 표의 칸(|), 가운뎃점 나열, 줄바꿈.
_SENT_SPLIT_RE = re.compile(r"(?<=[.?!])\s+|\s*\|\s*|\s+·\s+|\n")
#: 인용 한 구절의 길이. 너무 짧으면 표 칸 조각이고, 너무 길면 화면 한 줄을 넘는다.
QUOTE_MIN = 12
QUOTE_MAX = 120
#: 빈칸으로 가릴 낱말. 조사를 뗀 줄기가 이 길이 이상이어야 답이 된다.
MASK_MIN = 2
_WORD_RE = re.compile(r"[가-힣A-Za-z0-9%]+")
#: 서술어·연결 어미로 끝나는 낱말은 가리지 않는다 — "때문입니다" 를 가리면 발판이 아니라 말장난이다.
_PREDICATE_END_RE = re.compile(r"(니다|습니다|입니다|이다|된다|한다|진다|하는|되는|이는|으며|면서|지만|어서|아서|도록|하게|되게|지기|기|고|며|다|요|라)$")
#: 명사 뒤에 붙는 조사. 떼고 줄기만 답으로 보여 준다.
_PARTICLE_END_RE = re.compile(r"(에서는|으로는|에서|으로|에게|부터|까지|처럼|보다|이나|나|은|는|이|가|을|를|의|도|에|와|과|로)$")


def _sentences(text: str) -> list[str]:
    parts = (s.strip(" |·-—") for s in _SENT_SPLIT_RE.split(text or ""))
    return [s for s in parts if len(s) >= QUOTE_MIN]


def quote_for(label: str, summary: str, text: str, max_len: int = QUOTE_MAX) -> str:
    """
    본문에서 **이 개념을 말하는 한 문장**을 그대로 옮긴다.

    개념 이름이 통째로 나오는 문장을 가장 먼저, 다음은 이름·요약 낱말이 많이 겹치는
    문장. 아무 문장도 안 겹치면 첫 문장이다 — "자료 N장은 이렇게 말해요" 가 빈손이면
    사다리 1단이 통째로 사라진다. 본문이 없으면 빈 문자열.
    """
    sentences = _sentences(text)
    if not sentences:
        return ""
    query = set(_content_tokens(f"{label} {summary}"))
    name = _content_tokens(label)
    best, best_score = sentences[0], -1
    for sentence in sentences:
        tokens = _content_tokens(sentence)
        present = set(tokens)
        score = sum(1 for t in query if t in present)
        if name and contains_tokens(tokens, name):
            score += 3
        if score > best_score:
            best, best_score = sentence, score
    if len(best) > max_len:
        best = best[: max_len - 1].rstrip() + "…"
    return best


def _stem(word: str) -> str:
    """조사를 뗀 줄기. 떼고 나서 두 글자 미만이면("밖으로"→"밖") 명사 후보가 아니라 빈 문자열."""
    m = _PARTICLE_END_RE.search(word)
    if not m:
        return word
    stem = word[: -len(m.group(1))]
    return stem if len(stem) >= MASK_MIN else ""


def _mask_candidates(text: str, exclude: set[str]) -> list[tuple[str, str]]:
    """
    (원래 낱말, 줄기) 목록. 서술어는 뺀다. 순서는 문장 순서다.
    영문·숫자(수치·용어)는 어미 검사 없이 그대로 후보다.
    """
    out: list[tuple[str, str]] = []
    for word in _WORD_RE.findall(text or ""):
        if _PREDICATE_END_RE.search(word) and not re.search(r"[A-Za-z0-9]", word):
            continue
        stem = _stem(word)
        if len(stem) < MASK_MIN or stem.lower() in exclude or word.lower() in exclude:
            continue
        out.append((word, stem))
    return out


def mask_gist(gist: str, label: str, distractor_pool: list[str]) -> tuple[str, str, str]:
    """
    골자에서 낱말 하나를 가린 **빈칸 문장**과 (정답, 오답).

    가리는 낱말은 개념 이름이 아닌 것 중 가장 긴 것 — 이름을 가리면 질문이 곧 답이고,
    짧은 낱말은 조사가 섞여 답이 안 된다. 오답은 이웃 개념 요약에서 같은 방식으로
    고른다 (골자에 없는 낱말). 재료가 없으면 ("", "", "") — 억지로 만들지 않는다.
    """
    text = (gist or "").strip()
    if not text:
        return "", "", ""
    exclude = set(_content_tokens(label))
    candidates = _mask_candidates(text, exclude)
    if not candidates:
        return "", "", ""
    # 줄기가 긴 것, 같으면 문장에서 **뒤에** 있는 것 — 한국어 골자는 결론이 뒤에 오므로
    # 뒤쪽 명사가 답에 더 가깝다. 동률 규칙이 있어야 같은 골자면 언제나 같은 빈칸이다.
    word, answer = max(candidates, key=lambda c: (len(c[1]), text.rfind(c[0])))
    masked = text.replace(word, "___", 1)
    gist_stems = {s.lower() for _, s in candidates}
    pool = " ".join(s for s in distractor_pool if s)
    others = [s for _, s in _mask_candidates(pool, exclude) if s.lower() not in gist_stems]
    distractor = max(others, key=len) if others else ""
    return masked, answer, distractor
