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
#: Upstage 차트 설명 블록 — 「- Chart Type: bar chart」 줄과 바로 뒤 「- The bar chart …」 설명 줄. `_LONG_LATIN_RE` 는 한글
#: 따옴표에서 끊겨 조각(「A red line connects the top of the "법인세차감순이익" bar」)을 남겼고, 그게 힌트 인용이 됐다
#: (2026-09-29 일반화 벤치 §9). 표시 줄이 있을 때만 지운다 — 영문 발표의 「- 」 글머리는 본문이라 건드리지 않는다.
_CHART_DESC_RE = re.compile(r"^[ \t]*-[ \t]*(?:Chart|Figure|Graph|Diagram|Image)[ \t]+Type[ \t]*:.*(?:\n[ \t]*-[ \t].*)?$", re.M | re.I)

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
    text = strip_chart_descriptions(text)
    text = _FIGCAPTION_RE.sub(" ", text)
    text = _IMAGE_MD_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = _LONG_LATIN_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


#: 그림 설명으로 볼 영문 줄 — 이만큼 길고, 글자 가운데 한글이 이 몫보다 적다.
CAPTION_LINE_MIN = 30
CAPTION_HANGUL_MAX = 0.3
_HANGUL_RE = re.compile(r"[가-힣]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _hangul_share(line: str) -> float:
    h, a = len(_HANGUL_RE.findall(line)), len(_LATIN_RE.findall(line))
    return h / (h + a) if h + a else 1.0


def strip_chart_descriptions(raw_text: str) -> str:
    """
    Upstage 그림·차트 설명을 지운 원문. 줄 구조는 그대로 둔다 — 줄 단위로 보는 호출자용.

    - 「- Chart Type: …」「- Figure Type: …」 표시 줄과 바로 뒤 설명 줄.
    - **한글 자료에서** 한글이 30% 도 안 되는 30자 넘는 줄(표 행 빼고). 09-29 P5 최종 평가(SK): 표시 줄 뒤에 이어진
      「- “영업이익” (Operating Profit): 60,543 (orange bar)」「An orange line connects the top of the “영업이익” bar…」 가
      남아 골자·힌트 인용이 됐다. 한글 따옴표가 섞여 `_LONG_LATIN_RE` 도 조각만 지웠다.
      영문 발표(한글 본문 줄이 하나도 없는 장)는 건드리지 않는다 — 그 줄들이 본문이다.
    """
    text = _CHART_DESC_RE.sub("", raw_text or "")
    lines = text.split("\n")
    korean_body = any(_hangul_share(ln) >= 0.5 and len(_HANGUL_RE.findall(ln)) >= 4 for ln in lines)
    if not korean_body:
        return text
    kept = [ln for ln in lines
            if ln.lstrip().startswith("|") or len(ln.strip()) < CAPTION_LINE_MIN or _hangul_share(ln) >= CAPTION_HANGUL_MAX]
    return "\n".join(kept)


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


#: 쪽 번호("01 / 08")처럼 숫자·구분자만 있는 줄 — 글이 아니다.
_PAGE_NO_RE = re.compile(r"^[\d\s/|.·-]+$")
#: 식을 잇는 기호로 끝나는 줄 — 다음 줄과 한 식이다 ("수면의 질 =" "시간" "×" "연속성").
_OPERATOR_END_RE = re.compile(r"[=×+→÷]$")
#: 문장이 이어지는 줄 — 쉼표·조사·연결 어미로 끝나면 줄바꿈이 문장 가운데서 난 것이다.
_CONTINUES_END_RE = re.compile(r"(,|보다|아니라|는데|지만|으며|면서|에서|으로|에게|은|는|이|을|를|와|과|의|고|며)$")
#: 사진 OCR·PDF 본문은 **글자 폭에서 줄을 꺾는다** — 낱말 한가운데서도 (09-29 부스: 「취약 개념 기」 / 「반 Q&A를 통해…」).
#: 그 장에서 가장 긴 줄 폭의 이 비율 이상인 줄이 문장 끝으로 안 끝나면 다음 줄과 한 문장이다. 폭보다 짧게 끝난 줄
#: (제목 「… 학습 트레이너」)은 거기서 끝난 것이다. 폭 자체가 짧은 장(글 상자 칸)은 WRAP_MIN 밑이라 꺾임으로 보지 않는다.
WRAP_MIN = 30
WRAP_WIDTH_SHARE = 0.7
#: 문장이 끝난 줄 — 마침표·물음표·느낌표·콜론·필수 표시(*)·닫는 따옴표, 또는 종결 어미.
_SENTENCE_END_RE = re.compile(r"([.?!:*」』”\"')\]]|다|요|죠|음|함|됨|임)$")
#: 앞 장에서 넘어온 문장의 꼬리 — 조사나 닫는 괄호로 시작한다 (「(B2C)와 대학·기업 …」). 인용 첫째로 쓰지 않는다.
_FRAGMENT_START_RE = re.compile(r"^(\([^()]{1,12}\)[와과를을이가은는의도로에]|[와과를을이가은는의도로에](\s|$)|[)\]」』])")


def slide_units(raw_text: str) -> list[str]:
    """
    슬라이드 원문을 **글 상자 줄 단위**로 나눈 인용 후보 (각 QUOTE_MIN 자 이상).

    `clean_slide_text` 는 줄을 접어 한 줄로 만든다 — 인용이 그 위에서 마침표로만 자르면
    제목·설문 보기·본문이 한 "문장" 으로 붙는다 (09-29 수면 1장 힌트: 「수면 시간보다 중요한
    수면의 질 “어젯밤 몇 시간 잤나요?” 5시간 미만 5–7시간 7시간 이상 잠을 오래 잤다고…」).
    그래서 줄을 먼저 나누고, 다음 줄과는 이럴 때만 잇는다.

    - 식 기호로 끝나거나 식 기호만 있는 줄 — 칸마다 나뉜 식을 다시 한 식으로
    - 쉼표·조사·연결 어미로 끝난 줄 — 한 문장이 두 줄로 접힌 것
    - 아직 QUOTE_MIN 보다 짧은 덩이에 짧은 줄 — 낱말 칸들
    """
    lines = [clean_slide_text(line) for line in strip_chart_descriptions(raw_text).split("\n")]
    lines = [line for line in lines if line and not _PAGE_NO_RE.match(line)]
    width = max((len(line) for line in lines), default=0)
    wrap_at = max(WRAP_MIN, int(width * WRAP_WIDTH_SHARE))
    runs: list[list[str]] = []
    for line in lines:
        prev = runs[-1] if runs else None
        joined = " ".join(prev) if prev else ""
        wrapped = prev is not None and len(prev[-1]) >= wrap_at and not _SENTENCE_END_RE.search(prev[-1])
        joins = prev is not None and (
            bool(_OPERATOR_END_RE.search(prev[-1]) or _OPERATOR_END_RE.fullmatch(line))
            # 이어짐을 먼저 본다 — "보다" 는 "다" 로 끝나도 문장 끝이 아니다
            or bool(_CONTINUES_END_RE.search(prev[-1]))
            or wrapped
            or (len(joined) < QUOTE_MIN and len(line) < QUOTE_MIN)
        )
        if joins and wrapped and _HANGUL_END_START(prev[-1], line) and not _CONTINUES_END_RE.search(prev[-1]):
            # 폭에서 꺾인 줄은 낱말 한가운데일 수 있다 — 한글끼리면 붙여 쓴다 (「기」+「반」 → 「기반」).
            prev[-1] = prev[-1] + line
        elif joins:
            prev.append(line)
        else:
            runs.append([line])
    return [s for run in runs for s in _sentences(" ".join(run))]


def _HANGUL_END_START(prev: str, line: str) -> bool:
    return bool(prev and line and "가" <= prev[-1] <= "힣" and "가" <= line[0] <= "힣")


def _overlap(query: list[str], tokens: list[str]) -> int:
    """query 낱말 중 tokens 에 있는 수. 한글은 조사가 붙어도 같은 낱말로 본다 ("시간보다" ∋ "시간")."""
    return sum(
        1 for q in set(query)
        if any(q == t or (q in t or t in q) and min(len(q), len(t)) >= 2 and q.isalpha() and t.isalpha()
               for t in tokens)
    )


#: 질문 문장에서 인용 대조에 안 쓰는 물음 낱말 (앞머리로 본다). 「무엇·어떻게·근거·설명」 은 어느 질문에나 있어서,
#: 세면 제목 줄이 「근거」 한 낱말로 이긴다. 발표 내용과 무관한 물음의 뼈대만 둔다.
_QUESTION_FRAME = ("무엇", "어떻", "어떤", "어느", "설명", "발표", "자료", "근거", "이유", "구체", "주장", "생각",
                   "인가", "있나", "되나", "하나", "대해", "통해", "위해", "관련", "때문", "경우", "정도", "실제")


def _asked_tokens(question: str) -> list[str]:
    return [t for t in _content_tokens(question) if not t.startswith(_QUESTION_FRAME)]


def ranked_quotes(
    label: str,
    summary: str,
    texts: list[tuple[int, str]],
    question: str = "",
    k: int = 1,
    max_len: int = QUOTE_MAX,
) -> list[tuple[int, str]]:
    """
    근거 장의 줄을 **이 질문을 받치는 순서로** k 개. (장 번호, 인용). `best_quote` 가 첫째를 쓴다.

    점수는 (질문 낱말 겹침, 개념 이름·요약 겹침 + 이름이 통째로 든 줄 +3) 순서로 견준다 — **질문이 먼저다.**
    09-29 기준선: 예전엔 질문 낱말 가운데 개념 이름·요약에 든 것을 빼고 셌고, 이름 줄 +3 이 더해져서 「58%」 를
    묻는 질문에 같은 장의 «상위 2개가 전체의 58%» 가 아니라 제목 줄이 이겼다 (질문과 겹치는 낱말 0개인 인용 3건).
    질문과 한 낱말이라도 겹치는 줄이 있으면 겹치지 않는 줄은 절대 이기지 못한다. 동점이면 앞 장·앞 줄이다.
    """
    name = _content_tokens(label)
    base = set(_content_tokens(f"{label} {summary}"))
    asked = _asked_tokens(question)
    scored: list[tuple[tuple[int, int, int, int, int], int, str]] = []
    seen: set[str] = set()
    for order, (no, raw) in enumerate(texts):
        for pos, sentence in enumerate(slide_units(raw)):
            if sentence in seen:
                continue
            seen.add(sentence)
            tokens = _content_tokens(sentence)
            present = set(tokens)
            base_score = sum(1 for t in base if t in present)
            if name and contains_tokens(tokens, name):
                base_score += 3
            # 앞 장에서 넘어온 꼬리 조각은 질문과 겹쳐도 뒤로 — 화면에 「(B2C)와 …」 로 시작하는 인용이 뜬다 (09-29 부스).
            whole = 0 if _FRAGMENT_START_RE.match(sentence) else 1
            scored.append(((whole, _overlap(asked, tokens), base_score, -order, -pos), no, sentence))
    scored.sort(key=lambda s: s[0], reverse=True)
    out: list[tuple[int, str]] = []
    for _, no, quote in scored[:max(1, k)]:
        if len(quote) > max_len:
            quote = quote[: max_len - 1].rstrip() + "…"
        out.append((no, quote))
    return out


def best_quote(
    label: str,
    summary: str,
    texts: list[tuple[int, str]],
    question: str = "",
    max_len: int = QUOTE_MAX,
) -> tuple[int, str]:
    """
    여러 근거 장 가운데 **이 질문을 가장 잘 받치는 한 줄**. (장 번호, 인용). 없으면 (0, "").

    `texts` 는 (장 번호, 원문 raw_text) — 줄 구조가 살아 있어야 한다 (`slide_units`).
    예전엔 장을 앞에서부터 보고 첫 장의 문장을 썼다. 표지(1장)가 늘 먼저 걸려서, 질문이
    4장의 식을 묻는데 힌트는 1장 설문 보기를 보여 줬다 (09-29 수면). 이제 모든 장의 줄을
    한 줄 세워 점수로 고른다 — 점수 순서는 `ranked_quotes`.
    """
    found = ranked_quotes(label, summary, texts, question, k=1, max_len=max_len)
    return found[0] if found else (0, "")


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


#: 명사 줄기로 볼 수 없는 꼬리 — 활용·연결 어미·명사형. 자료에 낱말로 있어도 가리지 않는다.
#: 09-29 두 덱 기준선: 「모르겠어요」 선택지 6건 중 5건이 '중요함'·'차지해'·'설명할'·'발생했음'·'늘릴수록' 이었다.
_VERBAL_END_RE = re.compile(r"(수록|도록|는지|적인|적으로|하는|되는|하게|되게|하며|하고|해서|하여|되어|(?:했|었|았|였|겠|됐)[음다고지어]?|니다|요)$")
#: 명사에도 흔한 꼬리 — 두 글자 명사(역할·이해·포함·제한)는 자료에 낱말로 있을 때만, 세 글자 이상은 활용형으로 본다
#: ('설명할'·'차지해'·'중요함'·'일정한').
_SHORT_NOUN_END_RE = re.compile(r"(함|해|할|한|된|될|됨|인|적|운|여)$")
#: 명사에도 있는 꼬리 — 자료에 낱말로 있으면 명사다(주기·소음·광고), 없으면 활용형이다(들기·높여).
_ATTESTED_END_RE = re.compile(r"(기|음|임|짐|게|고|서|면|며|려|러|져|워|어|아)$")
#: 두 글자 영문 조각(et·al)은 용어가 아니다.
_LATIN_MIN = 3


def _attested(stem: str, source: str) -> bool:
    """줄기가 source 에 **낱말로** 있는가 — 앞은 낱말 경계, 뒤는 조사 또는 경계."""
    if not stem or not source:
        return False
    # 서술격(「회전율이다·회전율입니다」)도 그 명사다 — 09-30: 자료 줄 끝의 「…이다」 명사가 「자료에 없는 말」 로 읽혀 보기에서 빠졌다.
    return bool(re.search(rf"(?<![가-힣]){re.escape(stem)}(?:이다|입니다|이에요|예요|이고|이며|{_PARTICLE_END_RE.pattern[1:-2]})?(?![가-힣])", source))


#: 연결·보조 활용 꼬리 — 「제시하지(않았다)」「복구해야」「좋아지(는)」. 09-30 대화 감사 §8: 「모르겠어요」 보기 12세트 중
#: 「'방해' 쪽인가요, '제시하지' 쪽인가요?」「방해/좋아지」「복구해야/자원」 처럼 활용형이 보기가 됐다.
#: 명사에도 드물게 이 꼴이 있어서(「강아지」) 자료에 **명사 조사**를 달고 나온 적이 있으면 명사로 둔다.
_AUX_TAIL_RE = re.compile(r"(하지|되지|해야|돼야|되야|아지|어지|여지|워지|와지|해져|아져|어져|워져)$")
_NOUN_JOSA = r"(?:이|가|을|를|의|와|과|로|으로|에서|에게|도|만)(?![가-힣])"


def _noun_particle_attested(stem: str, source: str) -> bool:
    """줄기가 source 에 **명사 조사**를 달고 나오는가 — 「강아지가」 는 명사, 「좋아지는」 은 활용이다(「는」 은 어미와 겹쳐 뺀다)."""
    return bool(stem and source and re.search(rf"(?<![가-힣]){re.escape(stem)}{_NOUN_JOSA}", source))


def _noun_like(stem: str, source: str) -> bool:
    """가려도 답이 되는 명사 줄기인가. 영문·숫자 용어는 그대로 받는다(두 글자 영문은 뺀다)."""
    if re.search(r"[0-9]", stem):
        return True
    if re.fullmatch(r"[A-Za-z]+", stem):
        return len(stem) >= _LATIN_MIN
    if _VERBAL_END_RE.search(stem):
        return False
    if _AUX_TAIL_RE.search(stem):
        return _noun_particle_attested(stem, source)
    if _SHORT_NOUN_END_RE.search(stem):
        return len(stem) <= 2 and _attested(stem, source)
    if _ATTESTED_END_RE.search(stem):
        return _attested(stem, source)
    return True


#: 세는 단위·의존 명사 — 명사지만 「이 장이 말하는 건 A 쪽인가요」 의 보기가 못 된다
#: (09-29 부스: 「'가지' 쪽인가요, '종목' 쪽인가요?」 — 「다섯 가지 원인」 의 '가지').
_BOUND_NOUNS = frozenset({
    "가지", "개", "명", "번", "회", "곳", "점", "등", "것", "수", "때", "중", "개월", "년", "주", "일", "분", "초",
    "배", "차", "쪽", "부분", "경우", "정도", "이상", "이하", "대비", "위", "편",
})
#: 「X(이/가) 아니라 Y」 — 자료가 X 를 부정하고 Y 를 세운다. X 는 앞 두 낱말까지, Y 는 뒤 첫 낱말.
_CONTRAST_RE = re.compile(r"((?:[가-힣A-Za-z0-9·]+\s+)?[가-힣A-Za-z0-9·]+?)(?:이|가)?\s+아니라[,\s]+([가-힣A-Za-z0-9·]+)")
#: 대비 자리에 와도 보기가 못 되는 말 — 의문·정도 부사.
_NOT_CHOICE = frozenset({"얼마", "얼마나", "어떻게", "무엇", "무엇을", "누가", "언제", "어디", "가장", "매우", "더욱"})
#: 물음꼴로 끝난 구절(「샀는가」·「되는지」)은 명사가 아니다.
_QUESTION_END_RE = re.compile(r"(는가|은가|인가|는지|은지|던가)(가|이)?$")
#: 부정 꼴 — 이 앞 절에 든 낱말은 자료가 **아니라고** 한 쪽이다.
_NEGATION_RE = re.compile(r"아니라|아닌|아니다|아닙니다|않")


def _contrast_pair(quote: str) -> tuple[str, str]:
    """인용의 「X 아니라 Y」 → (Y 줄기, X 구절). 없으면 ("", "")."""
    m = _CONTRAST_RE.search(quote or "")
    if not m:
        return "", ""
    neg_words = [w for w in m.group(1).split() if w not in ("은", "는")]
    # 앞 낱말이 주제(「격차는」)면 부정된 것은 뒤 낱말뿐이다
    if len(neg_words) == 2 and re.search(r"(은|는)$", neg_words[0]):
        neg_words = neg_words[1:]
    if not neg_words:
        return "", ""
    neg_head = _stem(neg_words[-1])
    pos = _stem(m.group(2))
    # 둘 다 명사 줄기여야 보기가 된다 — 「무엇을 샀는가가 아니라, 얼마나 …」 · 「잠이 아니라, 몸과 뇌가 …」 는 대비지만 보기감이 아니다
    for stem, word in ((neg_head, neg_words[-1]), (pos, m.group(2))):
        if (not stem or len(stem) < MASK_MIN or stem in _BOUND_NOUNS or stem in _NOT_CHOICE
                or _QUESTION_END_RE.search(word) or not _noun_like(stem, quote)):
            return "", ""
    neg = " ".join(neg_words[:-1] + [neg_head])
    return ("", "") if neg == pos else (pos, neg)


def _negated_in(stem: str, quote: str) -> bool:
    """stem 이 인용에서 부정된 절(「… 아니라」 앞) 안에 있는가."""
    for m in _NEGATION_RE.finditer(quote or ""):
        clause = re.split(r"[:.·,]", quote[: m.start()])[-1]
        if _attested(stem, clause):
            return True
    return False


def mask_gist(
    gist: str, label: str, distractor_pool: list[str], *, quote: str = "", deck_text: str = ""
) -> tuple[str, str, str]:
    """
    골자에서 낱말 하나를 가린 **빈칸 문장**과 (정답, 오답).

    가리는 낱말은 **명사 줄기**만이다 — 활용형('중요함'·'차지해')을 가리면 발판이 아니라 말장난이다.
    개념 이름은 가리지 않는다(질문이 곧 답이다). 고르는 순서는 ① 자료 인용(quote)에 있는 낱말
    ② 자료 본문(deck_text)에 있는 낱말 ③ 긴 낱말 ④ 문장 뒤쪽 — 골자가 자료 밖 말(논문 저자 이름 등)을 담아도
    화면이 보여 주는 인용에서 확인할 수 있는 낱말이 답이 된다.

    오답은 distractor_pool 을 **앞에서부터** 보고 고른다 — 호출자가 이웃 개념 **이름**을 먼저 넣는다(같은 종류의 말).
    한 글 안에서는 뒤쪽 명사(한국어 합성어의 머리)를 먼저 본다. 골자·인용에 있는 낱말, 정답과 종류(숫자/말)가
    다른 낱말은 오답이 될 수 없다 — 인용에 둘 다 있으면 「이 장이 말하는 건 어느 쪽」 이 성립하지 않는다.
    재료가 없으면 ("", "", "") — 억지로 만들지 않는다.
    """
    text = (gist or "").strip()
    if not text:
        return "", "", ""
    source = f"{quote} {deck_text}"
    exclude = set(_content_tokens(label))
    flat_label = re.sub(r"\s+", "", label or "").lower()
    candidates = [(w, s) for w, s in _mask_candidates(text, exclude)
                  if _noun_like(s, source) and s.lower() not in flat_label
                  and s not in _BOUND_NOUNS and not _negated_in(s, quote)]
    # 인용이 「X 아니라 Y」 면 보기는 그 둘이다 — 자료가 스스로 세운 대비라 「어느 쪽」 이 그대로 성립한다.
    pos, neg = _contrast_pair(quote)
    if pos and neg:
        hit = next(((w, s) for w, s in candidates if s == pos), None)
        if hit:
            return text.replace(hit[0], "___", 1), pos, neg
        # 골자에 Y 가 없으면 빈칸 문장은 아래 규칙으로 만들고 보기만 대비 쌍이다 — 빈칸 없는 골자를 내면 답이 통째로 보인다
        masked, _, _ = mask_gist(gist, label, [], deck_text=deck_text)
        return masked, pos, neg
    if not candidates:
        return "", "", ""
    # 동률 규칙이 있어야 같은 골자면 언제나 같은 빈칸이다.
    word, answer = max(candidates, key=lambda c: (
        _attested(c[1], quote), _attested(c[1], deck_text), len(c[1]), text.rfind(c[0]),
    ))
    masked = text.replace(word, "___", 1)
    taken = {s.lower() for _, s in _mask_candidates(text, set())} | {answer.lower()}
    numeric = bool(re.search(r"[0-9]", answer))
    # 자료에 낱말로 있는 오답을 먼저 — 자료 밖 말(이웃 요약에만 있는 말)은 「자료가 말하는 쪽」 과 견줄 거리가 못 된다.
    for need_deck in ((True, False) if deck_text else (False,)):
        for item in distractor_pool or []:
            for _, stem in reversed(_mask_candidates(item or "", exclude)):
                if (stem.lower() in taken or stem in _BOUND_NOUNS or bool(re.search(r"[0-9]", stem)) != numeric
                        or stem.lower() in flat_label or _attested(stem, quote)
                        or not _noun_like(stem, f"{deck_text} {item}")
                        or (need_deck and not _attested(stem, deck_text))):
                    continue
                return masked, answer, stem
    return masked, answer, ""


def term_in(term: str, source: str) -> bool:
    """term 이 source 에 **낱말로** 있는가(뒤에 조사 허용). 코칭 선택지가 자료의 말인지 볼 때 쓴다."""
    return _attested((term or "").strip(), source)


# ---------------------------------------------------------------------------
# 자료가 인용한 문헌 — 결정론 (F-24 · F-08 · F-23 공용)
#
# "교수는 당신이 낸 참고문헌으로 묻는다" 의 재료다. 슬라이드 본문에서 「저자 (연도)」
# 꼴과 REFERENCES 장을 정규식으로만 뽑는다. LLM 이 논문 이름을 지어내는 것을 막는
# 유일한 방법은 **목록을 코드가 만드는 것**이라, 여기에는 모델이 없다.
# ---------------------------------------------------------------------------

#: 「Stothart et al. (2015)」 「Stothart, Mitchum & Yehnert (2015)」 「Peng et al. (CHI 2021)」
#: 「Leroy (2009)」. 연도 앞의 낱말(CHI·NeurIPS)은 학회명이라 버린다.
_LATIN_NAME = r"[A-Z][A-Za-z'’\-]+"
_CITE_LATIN_RE = re.compile(
    rf"(?P<authors>{_LATIN_NAME}(?:\s*,\s*{_LATIN_NAME})*(?:\s*(?:&|and)\s*{_LATIN_NAME})?)"
    rf"\s*(?P<etal>et\s+al\.?)?\s*\(\s*(?:[A-Za-z]+\s+)?(?P<year>(?:19|20)\d{{2}})[a-z]?\s*\)"
)
#: 「김철수(2021)」 「김철수 등(2021)」 「이영희 외 (2020)」.
_CITE_KO_RE = re.compile(
    r"(?P<authors>[가-힣]{2,4})\s*(?P<etal>등|외)?\s*\(\s*(?P<year>(?:19|20)\d{2})\s*\)"
)
#: 「[3] Author, Title, 2019」 꼴의 번호 참고문헌 줄 (참고문헌 장 안에서만).
_NUMBERED_REF_RE = re.compile(r"^\s*\[(?P<n>\d{1,3})\]\s*(?P<body>.+?)\s*$")
_DOI_RE = re.compile(r"10\.\d{2,9}(?:\s\d{1,6})?/[^\s\"<>)\]]+")
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
#: 참고문헌 장 판별 — 제목이나 첫 줄.
_REFERENCES_HEAD_RE = re.compile(r"references|bibliography|참고\s*문헌|참고\s*연구|참고\s*자료", re.I)

#: 문헌 제목으로 볼 줄의 최소 길이. 이보다 짧으면 저자 줄이거나 잘린 꼬리다.
_TITLE_MIN = 18
_AUTHOR_MAX = 3


def _split_authors(text: str) -> list[str]:
    parts = re.split(r"\s*(?:,|&|\band\b)\s*", text.strip())
    return [p.strip() for p in parts if p.strip()][:_AUTHOR_MAX]


def _is_reference_slide(slide) -> bool:
    head = " ".join([(slide.title or ""), (slide.raw_text or "").split("\n", 1)[0]])
    return bool(_REFERENCES_HEAD_RE.search(head))


def _looks_like_title(line: str) -> bool:
    s = line.strip()
    if len(s) < _TITLE_MIN or _DOI_RE.search(s) and len(_DOI_RE.sub("", s)) < _TITLE_MIN:
        return False
    if _CITE_LATIN_RE.search(s) or _CITE_KO_RE.search(s):
        return False
    return True


def _title_and_venue(line: str) -> tuple[str, str]:
    """「제목. 학술지. DOI: …」 한 줄을 제목·학술지로 가른다. DOI 는 따로 뽑는다."""
    s = _DOI_RE.sub("", line)
    s = re.sub(r"\bDOI\s*:?\s*$", "", s, flags=re.I).strip()
    # 마침표만 문장 경계다 — 제목에 「?」 가 흔하다 ("No task left behind? Examining…").
    sentences = [x.strip() for x in re.split(r"(?<=\.)\s+", s) if x.strip()]
    if not sentences:
        return "", ""
    title = sentences[0].rstrip(".")
    venue = sentences[1].rstrip(".") if len(sentences) > 1 else ""
    if venue and re.fullmatch(r"(?i)doi:?", venue):
        venue = ""
    return title, venue


def _is_author_line(line: str) -> bool:
    return bool(_CITE_LATIN_RE.search(line) or _CITE_KO_RE.search(line))


def _clean_doi(raw: str) -> str:
    return re.sub(r"\s+", "", raw).rstrip(".,;")


def _enrich_from_segment(ref, lines: list[str], at: int) -> None:
    """참고문헌 장에서 저자 줄 `at` 의 제목·학술지·DOI 를 찾는다.

    저자 줄 사이가 한 항목의 구간이다. 뒤 구간(저자 → 제목 → DOI 가 정상 순서)을 먼저
    보고, 거기 제목이 없으면 앞 구간의 **마지막** 제목 줄을 본다 — Upstage 가 줄 순서를
    흔들어 「제목 → DOI → 저자」 로 오는 항목이 실제로 있다 (live_qa_run 픽스처 12장).
    DOI 는 제목 줄과 그 뒤 다음 제목 줄 전까지만 본다 — 옆 항목의 DOI 를 집지 않게."""
    n = len(lines)
    fwd_end = at + 1
    while fwd_end < n and not _is_author_line(lines[fwd_end]):
        fwd_end += 1
    forward = list(range(at + 1, fwd_end))
    bwd_start = at - 1
    while bwd_start >= 0 and not _is_author_line(lines[bwd_start]):
        bwd_start -= 1
    backward = list(range(bwd_start + 1, at))

    title_at = next((i for i in forward if _looks_like_title(lines[i])), None)
    if title_at is None:
        title_at = next((i for i in reversed(backward) if _looks_like_title(lines[i])), None)
    if title_at is None:
        return
    segment = forward if title_at in forward else backward
    if not ref.title:
        ref.title, ref.venue = _title_and_venue(lines[title_at])
    if not ref.doi:
        for i in segment[segment.index(title_at):]:
            if i != title_at and _looks_like_title(lines[i]):
                break
            m = _DOI_RE.search(lines[i])
            if m:
                ref.doi = _clean_doi(m.group(0))
                break


def find_citations(text: str) -> list[tuple[str, int]]:
    """문장 속 「저자 (연도)」 인용을 (첫 저자 성 소문자, 연도) 로 뽑는다. F-08 이 질문의 인용을 검사할 때 쓴다."""
    out: list[tuple[str, int]] = []
    for pat in (_CITE_LATIN_RE, _CITE_KO_RE):
        for m in pat.finditer(text or ""):
            authors = _split_authors(m.group("authors"))
            if authors:
                out.append((authors[0].lower(), int(m.group("year"))))
    return out


def citation_lines(slidedoc) -> list:
    """
    SlideDoc → 자료가 인용한 문헌 `PaperRef` 목록 (kind="deck"). **LLM 0.**

    - 본문의 「저자 (연도)」 는 어느 장이든 잡는다 — 그 장이 `slide_no` 가 된다
      (교수는 "3장에서 인용한 …" 으로 묻는다). 같은 (첫 저자, 연도) 는 하나로 합친다.
    - 참고문헌 장(REFERENCES/참고문헌)에서는 저자 줄 주변에서 제목·학술지·DOI 까지 채운다.
      번호 참고문헌(`[3] …`)도 그 장에서만 항목으로 본다.
    - id 는 첫 등장 순서로 d01, d02… — 같은 자료면 같은 id 다.

    슬라이드가 없거나 인용이 없으면 빈 목록이다. 한글 자료의 「김철수(2021)」 도 잡는다.
    """
    from .contracts import PaperRef  # 순환 import 회피 — contracts 는 이 파일을 모른다

    if slidedoc is None:
        return []
    slides = getattr(slidedoc, "slides", None) or []
    found: dict[tuple[str, int], PaperRef] = {}
    order: list[tuple[str, int]] = []

    def take(key: tuple[str, int], make) -> PaperRef:
        ref = found.get(key)
        if ref is None:
            ref = make()
            found[key] = ref
            order.append(key)
        return ref

    for slide in sorted(slides, key=lambda s: s.slide_no):
        text = slide.raw_text or ""
        is_ref_slide = _is_reference_slide(slide)
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

        for at, line in enumerate(lines):
            for pat in (_CITE_LATIN_RE, _CITE_KO_RE):
                for m in pat.finditer(line):
                    authors = _split_authors(m.group("authors"))
                    if not authors:
                        continue
                    year = int(m.group("year"))
                    key = (authors[0].lower(), year)
                    et_al = bool(m.group("etal"))
                    ref = take(key, lambda: PaperRef(
                        id="", kind="deck", authors=authors, year=year, slide_no=slide.slide_no,
                        et_al=et_al,
                    ))
                    if len(authors) > len(ref.authors):
                        ref.authors = authors
                    ref.et_al = ref.et_al or et_al
                    if is_ref_slide:
                        _enrich_from_segment(ref, lines, at)

            if is_ref_slide:
                m = _NUMBERED_REF_RE.match(line)
                if m and not (_CITE_LATIN_RE.search(line) or _CITE_KO_RE.search(line)):
                    body = m.group("body")
                    ym = _YEAR_RE.search(body)
                    year = int(ym.group(1)) if ym else 0
                    head = re.split(r"[,.]", body, 1)[0].strip()
                    key = (f"[{m.group('n')}]", year)
                    ref = take(key, lambda: PaperRef(
                        id="", kind="deck", authors=_split_authors(head)[:1] if head else [],
                        year=year, slide_no=slide.slide_no,
                    ))
                    title, venue = _title_and_venue(body)
                    if not ref.title and len(title) >= _TITLE_MIN:
                        ref.title, ref.venue = title, venue
                    dm = _DOI_RE.search(body)
                    if dm and not ref.doi:
                        ref.doi = _clean_doi(dm.group(0))

    refs = [found[k] for k in order]
    for i, ref in enumerate(refs, 1):
        ref.id = f"d{i:02d}"
        if ref.doi and not ref.url:
            ref.url = f"https://doi.org/{ref.doi}"
    return refs
