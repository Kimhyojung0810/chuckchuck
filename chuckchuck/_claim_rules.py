"""
주장(F-26)과 탐침(_probes)이 함께 쓰는 **자료 말투 규칙** — 인용 한 줄이 주장을 받치는지 코드가 가른다.

`_match.py`·`_evidence.py` 와 같은 자리다 — 기능 모듈이 아니라 유틸이라 F-26 과 `_probes` 가 같이
import 해도 정책 위반이 아니다 (DEV_POLICY §4-1). LLM 을 부르지 않고 문자열만 본다.

왜 따로 두나 (2026-09-29 일반화 벤치, held-out 8덱):
- 인용이 원문에 **있는지**만 보고 인용이 주장을 **받치는지**는 안 봐서, 단정 표지 없는 줄이 absolute 로
  (held-out absolute 의 75%), 물음 줄 「몇 명이 구독하는가」 가 absolute 로, 표지 제목이 compose 로 들어갔다.
- 규칙은 전부 **구조**다 — 특정 발표의 낱말이 아니라 한국어 말투(단정 부사·부정·물음 어미·식 기호·
  목록 제목·「X보다」)와 개념 이름 토큰의 겹침만 본다. 새 덱이 들어와도 같은 잣대가 선다.
"""

from __future__ import annotations

import re

from ._match import norm_tokens

# ---------------------------------------------------------------------------
# 개념 이름 토큰 — 조사가 붙어도 같은 낱말
# ---------------------------------------------------------------------------

#: 이보다 짧은 토큰은 이름 대조에 쓰지 않는다 — 「수」「양」「질」 한 글자는 어디에나 있다.
TOKEN_MIN = 2
#: 개념 이름이 한 줄에 「나왔다」고 볼 변별 토큰 비율. 「사전 예방」 ↔ 「예방 체계」 는 1/2 로 통과한다.
MENTION_MIN = 0.5

_HANGUL_RE = re.compile(r"^[가-힣]+$")


def content_tokens(text: str) -> list[str]:
    """대조에 쓰는 토큰 — 두 글자 이상만 (한 글자 토큰·숫자 하나는 우연히 다 걸린다)."""
    return [t for t in norm_tokens(text) if len(t) >= TOKEN_MIN]


def tok_match(text_tok: str, label_tok: str) -> bool:
    """
    본문 토큰 하나가 이름 토큰 하나와 같은 낱말인가.

    - 한글은 조사·어미가 붙으므로 포함이면 같다 (「배송비를」 ∋ 「배송비」).
    - 이름 쪽 토큰에 붙은 관형격 「의」 는 떼고 본다 (「품질의 향상」 의 「품질의」 ↔ 본문 「품질」).
      그 밖에 본문 쪽이 짧은 경우는 다른 낱말이다 (「구독」 ≠ 「구독자」).
    - 영문·숫자는 통째로 같아야 한다 (「ai」 가 「detail」 안에서 걸리면 오탐이다).
    """
    if text_tok == label_tok:
        return True
    if not (_HANGUL_RE.match(text_tok) and _HANGUL_RE.match(label_tok)):
        return False
    if label_tok in text_tok:
        return True
    return len(label_tok) > TOKEN_MIN and label_tok.endswith("의") and label_tok[:-1] in text_tok


def distinct_tokens(label: str, exclude: str | list[str] = "") -> list[str]:
    """
    이름의 **변별 토큰** — 맞은편 이름(exclude)에도 있는 토큰은 뺀다 (「수면 시간」 ↔ 「수면의 질」 의 「수면」).
    다 빠지면 원래 토큰을 쓴다 (한쪽 이름이 다른 쪽을 품는 경우).
    """
    toks = content_tokens(label)
    ex_list = [exclude] if isinstance(exclude, str) else list(exclude)
    ex = [t for e in ex_list for t in content_tokens(e)]
    kept = [t for t in toks if not any(tok_match(x, t) or tok_match(t, x) for x in ex)]
    return kept or toks


def mention_score(label: str, text: str, exclude: str | list[str] = "") -> float:
    """이름의 변별 토큰 가운데 본문에 나온 비율 (0.0~1.0). 토큰이 없으면 0."""
    toks = distinct_tokens(label, exclude)
    if not toks:
        return 0.0
    body = norm_tokens(text)
    return sum(1 for t in toks if any(tok_match(b, t) for b in body)) / len(toks)


def mentioned(label: str, text: str, exclude: str | list[str] = "", min_score: float = MENTION_MIN) -> bool:
    return mention_score(label, text, exclude) >= min_score


def first_position(label: str, text: str) -> int:
    """본문에서 이름 토큰이 처음 나오는 토큰 위치 (못 찾으면 큰 수) — 「먼저 나온 쪽이 원인」 같은 순서 판단에 쓴다."""
    toks = content_tokens(label)
    body = norm_tokens(text)
    for i, b in enumerate(body):
        if any(tok_match(b, t) for t in toks):
            return i
    return 10_000


#: 양·방향만 말하는 수식어 — 「충분한 시간」·「시간 부족」 은 같은 개념(시간)을 가리킨다.
_POLARITY_RE = re.compile(
    r"^(?:부족|충분|충분한|충분히|저하|향상|감소|증가|개선|악화|높은|낮은|많은|적은|큰|작은|문제|결핍|과다|과잉|"
    r"확보|유지|부재|상승|하락|강화|약화|관리|제한|정도|수준)$"
)


def concept_key(label: str) -> frozenset[str]:
    """개념 이름에서 양·방향 수식어를 뺀 토큰 집합 — 둘이 같으면 한 개념의 두 이름이다."""
    toks = [t[:-1] if len(t) > 2 and t.endswith("의") else t for t in content_tokens(label)]
    return frozenset(t for t in toks if not _POLARITY_RE.match(t))


def same_concept(a: str, b: str) -> bool:
    """두 이름이 같은 개념인가 — 통째로 같거나, 수식어를 뺀 토큰 집합이 같다 (「충분한 시간」 = 「시간 부족」)."""
    if not a or not b:
        return False
    if a == b:
        return True
    ka, kb = concept_key(a), concept_key(b)
    return bool(ka) and ka == kb


# ---------------------------------------------------------------------------
# 줄의 말투
# ---------------------------------------------------------------------------

#: 단정 표지. 규칙 추출(rule_absolute)은 STRONG 만, LLM 후보 검사는 ANY 를 받는다.
ABSOLUTE_STRONG = (
    r"반드시|완전히|완벽하게|완벽히|항상|언제나|절대로|절대|결코|전혀|하나도|아무도|아무것도|아무런|"
    r"예외\s*(?:없이|없는|없다|없습니다)|무조건|100\s*%|틀림없이|누구나|영원히"
)
ABSOLUTE_ANY = ABSOLUTE_STRONG + r"|모든|완전한|(?<![가-힣])늘(?=\s)"
_ABS_STRONG_RE = re.compile(ABSOLUTE_STRONG)
_ABS_ANY_RE = re.compile(ABSOLUTE_ANY)
#: 부정과 함께 써야 단정이 되는 표지 — 「절대 … 않는다」「하나도 없었다」 는 부정된 단정이 아니라 단정이다.
_NEG_POLARITY_RE = re.compile(r"^(?:절대|절대로|결코|전혀|하나도|아무도|아무것도|아무런)$")
#: 단정을 뒤집는 말 — 「반드시 …는 아니다」「완전히 …되지는 않는다」「완전한 회복이 어렵다」 는 유보다.
_NEGATION_RE = re.compile(r"아니|아닙|아닌|아님|않|어렵|없지|수는\s*없|수\s*없|못\s|못하|못한|힘들")
#: 부정을 찾는 거리 (표지 뒤 글자 수). 쉼표·마침표를 넘지 않는다.
_NEGATION_SPAN = 24


def absolute_marker(line: str, strong_only: bool = False) -> str:
    """줄에 **부정되지 않은** 단정 표지가 있으면 그 표지, 없으면 ""."""
    rx = _ABS_STRONG_RE if strong_only else _ABS_ANY_RE
    for m in rx.finditer(line or ""):
        word = m.group(0)
        tail = re.split(r"[.,!?;]", line[m.end():m.end() + _NEGATION_SPAN], maxsplit=1)[0]
        if _NEG_POLARITY_RE.match(word) or not _NEGATION_RE.search(tail):
            return word
    return ""


_QUESTION_END_RE = re.compile(r"(?:[?？]|(?:는가|은가|인가|던가|을까|일까|할까|될까|볼까|까요|나요|는지|을지|니까)\s*[.]?)\s*$")


#: 가설·예상·물음을 머리에 단 줄 — 「가설: A가 높을수록 B가 는다」 는 검증할 말이지 주장이 아니다.
_POSED_RE = re.compile(r"^\s*(?:가설|예상|예측|추측|질문|탐구\s*질문|연구\s*질문|hypothesis|question)\s*\d*\s*[:：)]", re.I)


def is_question(line: str) -> bool:
    """물음 줄인가 — 「…는가」「…일까?」 나 「가설: …」 는 자료가 던진 물음이지 주장이 아니다."""
    line = (line or "").strip()
    return bool(_QUESTION_END_RE.search(line) or _POSED_RE.match(line))


_SENTENCE_END_RE = re.compile(r"(?:[.!。]|다|요|죠|음|함|됨|임)\s*[.!]?\s*$")


def is_sentence(line: str) -> bool:
    """문장으로 끝나는 줄인가 (마침표·「다」「요」). 아니면 제목·낱말 칸·접힌 줄이다."""
    return bool(_SENTENCE_END_RE.search((line or "").strip()))


#: 비교 표지 — compare 는 이게 있을 때만 (F-26 프롬프트에 적힌 규칙을 코드가 지킨다).
COMPARE_RE = re.compile(r"보다|대비|(?<![a-z])vs\.?(?![a-z])|비해|than|더\s", re.I)
#: 인과 표지 — 원인·결과를 잇는 말(때문에·해서·수록), 바꾸는 동사의 줄기(늘리·넓히·떨어지 …). 「→」 도 인과로 쓴다.
CAUSE_RE = re.compile(
    r"때문|→|->|수록|해서|하여|[가-힣](?:아|어)서\s|(?:으로|로)\s*인해|탓|일으|야기|유발|초래|이어지|이어집|이어져|가져오|가져와|좌우|영향|"
    r"늘었|줄었|높았|낮았|컸|올랐|"
    r"만든|만듭|만들|늘리|늘려|늘렸|늘립|늘어|늘고|줄이|줄여|줄였|줄입|줄어|줄고|높이|높여|높였|높입|높아|"
    r"낮추|낮춰|낮췄|낮춥|낮아|넓히|넓혀|넓혔|좁히|좁혀|좁혔|키우|키워|키웠|키웁|커지|커져|커졌|작아|많아|적어|"
    r"바꾸|바꿔|바꿨|올리|올려|올렸|내리|내려|내렸|늦추|늦춰|앞당|깎|해치|해쳐|빼앗|방해|"
    r"떨어|끊|증가|감소|촉진|억제|확대|축소|향상|저하|강화|약화|악화|막(?:는|아|습|을|았|기|지|힌|혀)"
)
#: 원인 절과 결과 절을 가르는 연결 어미 — 「A가 부족해서 B가 는다」「A할수록 B가 떨어진다」「A 때문에 B」.
CAUSE_SPLIT_RE = re.compile(r"(?:해서|하여서?|[가-힣](?:아|어)서|때문에|(?:으로|로)\s*인해|탓에|수록)\s")
#: 식 — 「A = B × C」. 좌변이 짧고 우변에 연산 기호가 있다.
FORMULA_RE = re.compile(r"^(?P<lhs>[^=]{1,40}?)\s*=\s*(?P<rhs>.*[×✕*+·÷x].*)$")
#: 목록 제목의 개수 말 — 「세 가지 문제」「5대 요인」「네 단계」.
_COUNT_RE = re.compile(r"(?:두|세|네|다섯|여섯|일곱|여덟|아홉|열|\d{1,2})\s*(?:가지|개|대|단계|요소|요인|조건|축|원칙)")
#: 문제 목록 제목 — 줄이 문제 명사로 끝난다 (「해결해야 할 세 가지 문제」). 「…문제와 연결됩니다」 는 아니다.
_PROBLEM_HEAD_RE = re.compile(r"(?:문제|문제점|원인|이유|한계|한계점|위험|장벽|걸림돌|어려움|병목|취약점|약점|고충|불편)(?:들)?\s*[.:!]?\s*$")
#: 문제 낱말 — 개념 이름·목록 항목이 문제를 가리키는가 (「연속성 저하」「보증 가입 장벽」).
_PROBLEM_WORD_RE = re.compile(r"문제|원인|저하|부족|위험|한계|장벽|지연|손실|불일치|부담|실패|결핍|과잉|과다|악화|방해|이탈|취소|낭비|오류|누락")
#: 해결 쪽 제목·낱말.
SOLVE_HEAD_RE = re.compile(r"해결|해소|대책|방안|방법|개선|전략|제안|솔루션|처방|실천|기능")
#: 해결 말투 — 문제를 줄이거나 없애는 동사·명사. 「높인다·늘린다」 는 인과에도 쓰여서 넣지 않는다.
SOLVE_RE = re.compile(
    r"해결|해소|개선|완화|방지|예방|대책|방안|차단|극복|보완|덜어|줄이|줄입|줄여|줄였|줄어|줄었|낮추|낮춥|낮춰|낮췄|"
    r"없애|없앱|없앴|막(?:는|아|습|을|기|았)|확보|지원|도입|유지|지키|지킵|지켜"
)
#: 「A가 B를 <바꾸는 동사>」 — 조사로 원인(주어)·결과(목적어)가 갈린 한 문장.
CAUSE_SVO_RE = re.compile(r"^(?P<a>[^,.?!]{2,30}?)(?:이|가)\s+(?P<b>[^,.?!]{2,30}?)(?:을|를)\s+(?P<v>\S+)\s*$")
#: 해결 칸의 말 — 무엇을 하는 칸인가 (「…확보」「…줄이기」「…유지」). 현황 칸(「평균 1년 이상」)과 가른다.
SOLVE_ACT_RE = re.compile(
    r"확보|유지|줄이|줄임|낮추|낮춤|없애|막기|막는|방지|예방|해소|개선|도입|지원|설정|정하|관리|늘리|높이|바꾸|"
    r"기르|만들|두기|하기|제공|공개|연동|인증|점검|제한|[가-힣]기\s*$"
)
#: 요소가 **함께** 필요하다는 말 — 이게 있으면 「하나만 챙긴다면」 은 자료가 부정한 선택이다.
BOTH_NEEDED_RE = re.compile(
    r"둘\s*다|모두\s*(?:필요|중요|갖춰|챙겨|있어야)|함께\s*(?:필요|중요|갖춰|챙겨|작용|있어야)|하나만으로는|"
    r"하나만\s*\S+?(?:서는|로는)|만으로는|만으로\s+[^.,]{0,15}?(?:않|어렵|부족|못)|뿐\s*(?:만\s*)?아니라|동시에|"
    r"만큼\s[^.]{0,30}?도\s*중요|어느\s*하나(?:도|만)"
)


def is_formula(line: str) -> bool:
    return bool(FORMULA_RE.match((line or "").strip()))


def formula_sides(line: str) -> tuple[str, str] | None:
    m = FORMULA_RE.match((line or "").strip())
    return (m.group("lhs").strip(), m.group("rhs").strip()) if m else None


#: 문장이어도 목록을 여는 줄 — 「문제는 세 가지입니다」「원인은 다음과 같습니다」.
_LIST_SENTENCE_RE = re.compile(r"(?:가지|개|단계|요인|조건|원칙|다음과\s*같)\S*\s*(?:입니다|이다|있습니다|있다|같습니다|같다)\s*[.:]?$")


def is_list_heading(line: str) -> bool:
    """
    목록을 여는 제목 줄인가 — 개수 말이 있거나 문제 명사로 끝나고, 식·물음·긴 줄이 아니다.
    문장은 목록을 소개하는 꼴(「…세 가지입니다」)일 때만 — 「해결책은 세 가지 문제와 연결됩니다」 는 제목이 아니다.
    """
    line = (line or "").strip()
    if not line or len(line) > 40 or is_formula(line) or is_question(line):
        return False
    if is_sentence(line) and not _LIST_SENTENCE_RE.search(line):
        return False
    return bool(_COUNT_RE.search(line) or _PROBLEM_HEAD_RE.search(line))


def is_problem_head(line: str) -> bool:
    return bool(_PROBLEM_HEAD_RE.search((line or "").strip()))


def is_problem_label(label: str) -> bool:
    return bool(_PROBLEM_WORD_RE.search(label or ""))


def both_needed(line: str) -> bool:
    return bool(BOTH_NEEDED_RE.search(line or ""))


# ---------------------------------------------------------------------------
# 목록 항목
# ---------------------------------------------------------------------------

_ITEM_MARK_RE = re.compile(r"^(?:[①-⑳]|\(?\d{1,2}[.)]|[-•▪■◦·*>]|[a-zA-Z][.)])\s*")


def table_cells(line: str) -> list[str]:
    """「| a | b |」 → ["a", "b"]. 표 행이 아니면 []."""
    line = (line or "").strip()
    if not line.startswith("|"):
        return []
    return [c.strip() for c in line.strip("|").split("|") if c.strip()]


def item_text(line: str) -> str:
    """목록 한 칸의 글 — 번호·글머리표를 떼고, 표 행이면 첫 칸."""
    cells = table_cells(line)
    text = cells[0] if cells else (line or "").strip()
    return _ITEM_MARK_RE.sub("", text).strip()


def is_item_line(line: str) -> bool:
    """목록 항목처럼 생긴 줄 — 표 행, 번호·글머리표 줄, 또는 문장이 아닌 짧은 줄."""
    line = (line or "").strip()
    if not line:
        return False
    if table_cells(line) or _ITEM_MARK_RE.match(line):
        return True
    return len(line) <= 30 and not is_sentence(line) and not is_question(line)
