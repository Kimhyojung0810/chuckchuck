"""
비교 문장을 네 칸 — (주어, 비교 대상, 잣대, 서술 방향) — 으로 읽고 자료 줄의 비교와 견주는 결정적 헬퍼입니다. LLM 을 부르지 않습니다.
`_deck_claims` 의 낱말·방향 도구를 쓰는 유틸이라 기능 모듈 어디서 import 해도 정책 위반이 아닙니다 (DEV_POLICY §4-1).
F-11 정합(`_align_checks.contradictions` → `_deck_claims.conflicts`)과 F-09 판정 가드가 이 대조를 같이 쓰고,
F-08 전제 검사도 `read_comparison`·`comparison_relation` 을 그대로 불러 쓸 수 있습니다.

왜 (09-30 녹음 감사 REC-01 — 처음 보는 덱 셋에서 방향 모순 0/3):
- 「한쪽 창문만 열었을 때가 맞통풍보다 두 배 빨리 떨어졌어요」 (자료: 맞통풍이 한쪽보다 2배 빨리) — 주어와 비교 대상을 맞바꿨는데,
  예전 대조는 「보다」 앞 두 줄기를 한 덩어리로 잡아(「강공은 번트보다」 → [강공, 번트]) 주어와 대상을 못 갈랐다.
- 「큰 글씨 모드만 켠 매장이 교육한 매장보다 성공률이 더 많이 올랐어요」 (자료: 상승 폭이 작았다) — 반의어 서술.
- 「번트를 했을 때가 강공보다 득점 확률이 더 높게 나왔어요」 — 수 없이 방향만 뒤집은 비교.

읽는 법 — 한국어 비교 구문의 구조만 쓴다 (덱 낱말을 규칙에 넣지 않는다).
- 비교 대상: 「X보다(는/도)」「X에 비해」 의 X 와 그 앞 꾸밈말(관형형·목적어·맨 명사). 주어·화제 표지(은·는·이·가)·
  자리 부사어(…에서)·쉼표·이음 어미·말머리 부사에서 멈춘다.
- 주어: 비교 대상 앞의 말 — 자리·수단 부사어(「무사 1루에서(는)」「…으로」)와 말머리 부사는 뺀다. 앞에 없으면 뒤의 첫 주어·화제
  표지 말, 그게 「것은」 이면(「X보다 더 중요한 것은 Y입니다」) 끝의 「Y(이)다」 가 주어다.
- 서술 방향: 비교 뒤 말의 방향 — 꾸미는 방향 낱말(「상승 폭」「많이」「빨리」「덜」)은 곱으로 접는다(`signed_directions`).
  방향 낱말이 없으면 서술어 머리(「중요하다」)로 같은 서술인지만 본다.
- 두 비교의 관계: 대상 쪽 핵심 줄기가 서로 같은 쪽에 있으면 +1, 반대 쪽(주어 쪽)에 있으면 맞바꿈 −1.
  관계 × 두 서술 방향의 곱이 −1 이면 어긋남이다 — 맞바꾸고 반의어로 말한 것(「B는 A보다 낮다」 = 「A는 B보다 높다」)은 같은 말이다.

놓치는 쪽이 안전하다: 주어·대상을 못 가르거나, 잣대가 다르거나(「가격」↔「무게」), 서술이 부정(「높지 않다」)이면 견주지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from ._deck_claims import (
    Conflict,
    Deck,
    _has,
    _quoted_by_question,
    clauses,
    content_stems,
    direction,
    negated,
    quantity_bounds,
    signed_directions,
)

__all__ = ["Comparison", "read_comparison", "comparison_relation", "comparison_check", "comparison_conflicts"]

#: 「X보다」「X보다는」「X보다도」「X보단」 — 한 어절.
_THAN_WORD_RE = re.compile(r"^(?P<head>.+?)(?:보다는|보다도|보단|보다)$")
#: 「X에 비해(서)」 의 둘째 어절.
_BIHAE_WORD_RE = re.compile(r"^비(?:해|해서|해선|하면|하여|해도)$")
#: 비교 대상이 마음속 잣대인 말 — 「생각보다」「예상보다」 는 두 대상을 견주는 비교가 아니다.
_IDIOM_HEADS = ("생각", "예상", "기대", "짐작", "상상")
#: 주어·화제 표지 (어절 끝).
_SUBJ_END_RE = re.compile(r"(?:은|는|이|가|께서)$")
#: 「은·는」 으로 끝나지만 관형형인 말 — 동사 줄기 + 는(하는·여는·켜는…) · 형용사 + 은(많은·높은…) · 받침 동사 + 은(받은·먹은…).
_ADNOMINAL_RE = re.compile(
    r"(?:[하되있없않여켜쓰가오보주받드지치우추르먹읽찾쉬내]는|[같많적높낮작좋넓좁짧깊얕맑밝붉검굵얇젊늦짙옅싫]은"
    r"|[먹받읽찾얻잃넣놓앉닫]은"
    # 인용 관형형 — 「덥다는 민원」「춥다는 민원」「쉽다는 평」 (held-out 지하철 덱)
    r"|[다라냐자]는)$"
)
#: 「이」 로 끝나는 부사 — 주어 표지가 아니다.
_ADVERB_I = frozenset({"많이", "같이", "높이", "깊이", "굳이", "없이", "일찍이", "틈틈이", "일일이"})
#: 이음 어미 — 명사구가 여기서 끝난다.
_CONNECTIVE_RE = re.compile(r"(?:고|며|면서|는데|은데|지만|니까|므로|거나|어서|아서|해서|라서|더니)$")
#: 자리·수단·때의 부사어 — 주어 쪽 줄기에서 빼고, 비교 대상 명사구도 여기서 멈춘다.
_ADVERBIAL_RE = re.compile(r"(?:에서는|에서도|에서|에는|에게는|에게|으로는|로는|으로|부터|까지|처럼|마다|에도|엔)$")
#: 「…했을 때가」「…인 경우에는」 — 조건이지만 비교의 주어 자리다.
_CONDITION_RE = re.compile(r"^(?:때|경우)")
#: 말머리 부사·접속사 — 비교의 어느 쪽도 아니다.
_DISCOURSE = frozenset({"사실", "의외로", "실제로", "특히", "그리고", "그러니까", "그래서", "근데", "그런데", "하지만", "오히려",
                        "역시", "결국", "또", "또한", "먼저", "우선", "반면", "반대로", "다만", "즉", "참고로", "정리하면", "일단",
                        "그럼", "그러면", "게다가", "무엇보다"})
#: 정도 부사·어림 말 — 잣대 줄기가 아니다.
_FILLER = frozenset({"더", "훨씬", "조금", "약간", "좀", "매우", "아주", "너무", "가장", "제일", "거의", "무려", "대략", "정도",
                     "한참", "꽤", "상당히", "비교적", "훨"})
#: 비교 대상 머리가 이음 어미로 끝나면(「작아서보다」「가면보다」) 대상이 명사가 아니라 절이다 — 두 쪽을 못 가른다.
_CLAUSE_HEAD_RE = re.compile(r"(?:서|고|면|며|니까)$")
#: 자리·수단의 **화제**(「…만으로는」「…에서는」) — 다른 주어가 없을 때만 비교의 주어로 본다.
_TOPIC_ADVERBIAL_RE = re.compile(r"(?:으로는|로는|에서는|에는)$")
#: 가짜 주어 — 「X보다 더 중요한 것은 Y다」 의 「것은」.
_PSEUDO_CLEFT_RE = re.compile(r"^(?:것|거|건|게)(?:은|이|는|가)?$")
_COPULA_RE = re.compile(r"(?:이었습니다|였습니다|입니다|이에요|예요|이었어요|였어요|이었다|였다|이다|이죠|인데요|이라고|라고)$")
#: 한 글자 의존·시간 명사 + 조사 · 가벼운 동사 — 어느 쪽 줄기에도 넣지 않는다 (「때가」「날에는」「했을」「하는」).
#: 한 글자 형용사의 관형형(「맑은」「넓은」)은 내용이라 남긴다.
_ONE_SYLLABLE_RE = re.compile(
    r"^(?:때|날|것|거|곳|쪽|수|데|줄|적|번|분|해|달|주|편|측|폭)"
    r"(?:은|는|이|가|을|를|의|도|에|로|와|과|만|에서|에서는|에는|에도|으로|부터|까지|보다)?$"
)
_LIGHT_RE = re.compile(r"^(?:했|하|되|됐|돼|있|없|않|한|된|할|될)(?:을|던|는|은|다|고|어|아|었|았|던)?$")


def _bare(word: str) -> str:
    return re.sub(r"^[^가-힣A-Za-z0-9%]+|[^가-힣A-Za-z0-9%]+$", "", word or "")


#: 한 글자 내용 명사(「낮」「밤」「봄」「돈」) — 줄기는 두 글자부터라 버려지는데, 비교의 두 쪽을 가르는 말일 때가 많다
#: (「낮 시간대에 비해 출근 시간대」 — held-out 지하철 덱). 한 글자 기능어·세는 말은 뺀다.
_ONE_SYLLABLE_STOP = frozenset("더덜좀약그이저한두세네수것거때등및또안못잘꼭딱쭉확뚝싹왜뭐어음아예응제내곧늘다참막꽤훨첫새헌온전각매몇여총반배번명개분초년월일원층칸줄쪽곳날달해주시점중뒤앞위옆속밖간")
_ONE_WORD_RE = re.compile(r"^([가-힣])(?:은|는|이|가|을|를|의|도|에|에는|에서|에서는|만|과|와|로|으로|보다)?$")


def _side_stems(words: list[str]) -> tuple[str, ...]:
    """한 쪽(주어·대상·잣대)의 내용 줄기 — 말머리 부사·정도 부사·한 글자 머리·가벼운 동사·방향 낱말은 뺀다. 한 글자 내용 명사는 넣는다."""
    kept = [w for w in words if _bare(w) not in _DISCOURSE and _bare(w) not in _FILLER]
    out = [s for s in content_stems(" ".join(kept), drop_units=True)
           if not _ONE_SYLLABLE_RE.match(s) and not _LIGHT_RE.match(s) and not direction(s)]
    for w in kept:
        m = _ONE_WORD_RE.match(_bare(w))
        if m and m.group(1) not in _ONE_SYLLABLE_STOP:
            out.append(m.group(1))
    return tuple(dict.fromkeys(out))


def _is_subject_word(word: str) -> bool:
    b = _bare(word)
    return bool(_SUBJ_END_RE.search(b)) and not _ADNOMINAL_RE.search(b) and b not in _ADVERB_I


def _adnominal_verb(word: str) -> bool:
    """관형형 동사·형용사인가 — 끝 음절 받침이 ㄴ·ㄹ(「예약한」「켠」「열」「할」) 이거나 「…는/…은」 관형형(`_ADNOMINAL_RE`)."""
    b = _bare(word)
    if not b or not ("가" <= b[-1] <= "힣"):
        return False
    if _ADNOMINAL_RE.search(b):
        return True
    if b.endswith(("은", "는")):
        return False                                # 명사 + 화제 조사일 수 있다 — 위 목록에 있는 것만
    return (ord(b[-1]) - 0xAC00) % 28 in (4, 8)


def _in_comparand(word: str, next_word: str = "") -> bool:
    """
    비교 대상 명사구 안에 드는 말인가 (「보다」 어절에서 뒤로 걸어가며). 부사어라도 바로 뒤가 관형형이면(「전화로 예약한 캠핑장보다」)
    그 관형절 안의 말이라 명사구에 든다.
    """
    b = _bare(word)
    if not b or re.search(r"[,，;:]$", word) or b in _DISCOURSE:
        return False
    if _is_subject_word(word) or _CONNECTIVE_RE.search(b):
        return False
    if _ADVERBIAL_RE.search(b) and not _adnominal_verb(next_word):
        return False
    return True


def _without_adverbials(words: list[str], keep_topic: bool = False, parallel: str = "") -> list[str]:
    """
    주어 쪽에서 자리·수단 부사어 덩어리를 뺀다 — 덩어리는 조사가 붙은 어절에서 끝난다(앞의 맨 명사는 그 덩어리의 꾸밈말).
    keep_topic 이면 「…만으로는」「…에서는」 같은 화제 덩어리는 남긴다(다른 주어가 없을 때 그것이 견주는 쪽이다).
    parallel(비교 대상 머리 명사)과 머리가 같은 부사어는 **견주는 쪽**이라 남긴다 — 「비 오는 날에는 … 맑은 날보다」 는 날과 날을 견준다.
    """
    out: list[str] = []
    chunk: list[str] = []
    for i, w in enumerate(words):
        b = _bare(w)
        if b in _DISCOURSE:
            continue
        chunk.append(w)
        adverbial = _ADVERBIAL_RE.search(b)
        if adverbial and i + 1 < len(words) and _adnominal_verb(words[i + 1]):
            continue                                # 「앱으로 예약한 캠핑장은」 — 관형절 안의 부사어는 명사구의 일부다
        if adverbial and parallel and b[:adverbial.start()] and b[:adverbial.start()].endswith(parallel):
            out += chunk
            chunk = []
        elif keep_topic and _TOPIC_ADVERBIAL_RE.search(b):
            out += chunk
            chunk = []
        elif adverbial and not _CONDITION_RE.match(b):
            chunk = []                              # 「무사 1루에서(는)」 — 통째로 뺀다
        elif _is_subject_word(w) or re.search(r"(?:을|를|의|과|와|도|만)$", b):
            out += chunk
            chunk = []
    return out + chunk


@dataclass(frozen=True)
class Comparison:
    """비교 한 개 — 주어·비교 대상·잣대 줄기와 서술 방향(+1 더하다 · −1 덜하다 · 0 방향 낱말 없음)."""

    subject: tuple[str, ...]
    other: tuple[str, ...]
    measure: tuple[str, ...]
    sign: int
    pred: str                 # 방향 낱말이 없을 때 같은 서술인지 볼 서술어 머리(두 글자)
    negated: bool
    text: str

    @property
    def own_subject(self) -> tuple[str, ...]:
        """주어 쪽에만 있는 줄기 (대상 쪽에도 나오는 줄기는 어느 쪽인지 못 가른다)."""
        return tuple(s for s in self.subject if not _has(self.other, s))

    @property
    def own_other(self) -> tuple[str, ...]:
        return tuple(s for s in self.other if not _has(self.subject, s))


def _head_noun(head: str) -> str:
    """비교 대상 머리 명사 — 「날」「때」「매장」 (조사를 뗀 끝 낱말)."""
    return re.sub(r"(?:에서|에|의|을|를|은|는|이|가)$", "", head.split()[-1]) if head.strip() else ""


def _modifies_short_head(word: str, adjacent: bool, head: str) -> bool:
    """
    「맑은 날보다」「넓은 곳보다」 — 한 글자 머리 명사(날·때·곳·쪽·것) 바로 앞의 「…은/는」 은 화제가 아니라 그 명사를 꾸미는 말이다.
    두 글자 넘는 머리 앞(「강공은 번트보다」)은 화제다.
    """
    return adjacent and len(_head_noun(head)) == 1 and bool(re.search(r"(?:은|는)$", _bare(word)))


def _marker(words: list[str]) -> tuple[int, str, int] | None:
    """(비교 대상 머리 어절 자리, 머리 글, 뒤 말이 시작하는 자리). 비교 표지가 없거나 둘 이상이면 None."""
    found: list[tuple[int, str, int]] = []
    for i, w in enumerate(words):
        b = _bare(w)
        m = _THAN_WORD_RE.match(b)
        if m and _bare(m.group("head")):
            found.append((i, _bare(m.group("head")), i + 1))
        elif _BIHAE_WORD_RE.match(b) and i > 0 and _bare(words[i - 1]).endswith("에") and len(_bare(words[i - 1])) > 1:
            found.append((i - 1, _bare(words[i - 1])[:-1], i + 1))
    if len(found) != 1:
        return None
    return found[0]


def _subject_after(rest: list[str]) -> tuple[tuple[str, ...], list[str]]:
    """
    주어가 비교 대상 뒤에 올 때 — 「B보다 A가 …」 는 뒤의 첫 주어·화제 표지 말, 「B보다 더 중요한 것은 A다」 는 끝의 「A(이)다」.
    (주어 줄기, 나머지 서술 어절). 못 찾으면 (빈 줄기, rest 그대로).
    """
    m = next((i for i, w in enumerate(rest) if _is_subject_word(w)), None)
    if m is None:
        return (), rest
    if _PSEUDO_CLEFT_RE.match(_bare(rest[m])):
        tail = rest[m + 1:]
        if not tail:
            return (), rest
        subject = _side_stems([*tail[:-1], _COPULA_RE.sub("", _bare(tail[-1]))])
        return (subject, rest[:m]) if subject else ((), rest)
    subject = _side_stems(rest[:m + 1])
    return (subject, rest[m + 1:]) if subject else ((), rest)


def _pred_key(word: str) -> str:
    b = _COPULA_RE.sub("", _bare(word))
    b = re.sub(r"[^가-힣]", "", b)
    return b[:2] if len(b) >= 2 else ""


@lru_cache(maxsize=8192)
def read_comparison(text: str) -> Comparison | None:
    """
    한 절의 비교 — 「A는 B보다 C가 높다」「B보다 A가 …」「B에 비해 A는 …」「B보다 더 중요한 것은 A다」. 비교가 아니거나 못 읽으면 None.
    """
    words = [w for w in quantity_bounds(text or "").split() if _bare(w)]
    mk = _marker(words)
    if mk is None:
        return None
    k, head, rest_at = mk
    if head.startswith(_IDIOM_HEADS) or _CLAUSE_HEAD_RE.search(head):
        return None
    j = k
    while j - 1 >= 0 and (_in_comparand(words[j - 1], words[j] if j < k else head)
                          or _modifies_short_head(words[j - 1], j - 1 == k - 1, head)):
        j -= 1
    other = _side_stems([*words[j:k], head])
    subject = _side_stems(_without_adverbials(words[:j], parallel=_head_noun(head)))
    rest = words[rest_at:]
    if not subject:
        subject, rest = _subject_after(rest)
    if not subject:
        subject = _side_stems(_without_adverbials(words[:j], keep_topic=True))
    if not subject or not other or not rest:
        return None
    rest_text = " ".join(rest)
    signs = signed_directions(rest_text, comparative=True)
    return Comparison(
        subject=subject,
        other=other,
        # 잣대는 서술어(끝 어절) 앞의 말 — 「득점 확률이 더 높았다」 의 득점 확률
        measure=_side_stems(rest[:-1]),
        sign=signs[0] if len(signs) == 1 else 0,
        pred=_pred_key(rest[-1]),
        negated=negated(rest_text),
        text=text,
    )


def _lands(stems: tuple[str, ...], near: tuple[str, ...], far: tuple[str, ...]) -> bool:
    """stems 가운데 near 쪽에만 있는(far 쪽에는 없는) 줄기가 있는가."""
    return any(_has(near, s) and not _has(far, s) for s in stems)


def _orientation(a: Comparison, b: Comparison) -> int:
    """
    +1 — 두 비교가 같은 두 쪽을 같은 자리에 둔다 · −1 — 주어와 대상을 맞바꿨다 · 0 — 모른다(다른 비교이거나 못 가른다).
    같은 자리(+1)는 주어 쪽도 서로 닿아야 한다 — 대상만 같고 주어가 다른 비교(「A는 B보다」 ↔ 「C는 B보다」)는 다른 말이다.
    """
    a_same, a_cross = _lands(a.own_other, b.other, b.subject), _lands(a.own_other, b.subject, b.other)
    b_same, b_cross = _lands(b.own_other, a.other, a.subject), _lands(b.own_other, a.subject, a.other)
    subj = _lands(a.own_subject, b.subject, b.other) and _lands(b.own_subject, a.subject, a.other)
    if a_same and b_same and not (a_cross or b_cross) and subj:
        return 1
    if a_cross and b_cross and not (a_same or b_same):
        return -1
    return 0


def comparison_relation(said: Comparison, deck: Comparison) -> str:
    """
    두 비교의 관계 — "same"(같은 말) · "swapped"(주어·대상을 맞바꿔 반대가 됨) · "reversed"(같은 두 쪽인데 방향이 반대) · ""(견줄 수 없음).
    """
    o = _orientation(said, deck)
    if not o or said.negated or deck.negated:
        return ""
    if said.measure and deck.measure and not any(_has(deck.measure, m) for m in said.measure):
        return ""                                   # 잣대가 다르다 — 「가격이 높다」 와 「무게가 가볍다」
    if said.sign and deck.sign:
        prod = said.sign * deck.sign
    elif not said.sign and not deck.sign and said.pred and said.pred == deck.pred:
        prod = 1                                    # 방향 낱말 없이 같은 서술(「더 중요하다」)
    else:
        return ""
    if o * prod > 0:
        return "same"
    return "swapped" if o < 0 else "reversed"


@lru_cache(maxsize=4096)
def _line_comparisons(text: str) -> tuple[Comparison, ...]:
    return tuple(c for c in (read_comparison(x) for x in clauses(text)) if c is not None)


def comparison_check(clause: str, deck: Deck, question_stems: tuple[str, ...] = ()) -> tuple[list[Conflict], bool]:
    """
    (어긋남, 짝을 찾았나). 절의 비교가 자료 줄의 비교와 맞바꿈·반대 방향이면 어긋남 하나 — 맞바꿈은 kind "order"(무엇이 더한지가
    반대), 반대 방향은 kind "direction" 이고, 어느 꼴인지는 relation 에 남는다(예전 `_swapped_comparison` 과 같은 kind 이름).
    같은 비교를 같은 방향으로 말한 자료 줄이 하나라도 있으면 어긋남이 아니다. 질문이 옮겨 와 따지는 줄은 뺀다.
    짝을 찾았으면(같은 말이든 어긋남이든) 이 절의 방향은 비교로 읽은 것이 답이다 — 부르는 쪽은 방향 낱말만 세는 대조를 건너뛴다
    (「그대로 둔 노선은 배차를 늘린 노선보다 이용객이 적었어요」 는 자료 「…늘린 노선은 …둔 노선보다 많았습니다」 와 같은 말이다).
    """
    mine = read_comparison(clause)
    if mine is None or deck.empty:
        return [], False
    found: Conflict | None = None
    for line in deck.lines:
        if line.is_row or _quoted_by_question(line, question_stems):
            continue
        for theirs in _line_comparisons(line.text):
            rel = comparison_relation(mine, theirs)
            if rel == "same":
                return [], True
            if rel and found is None:
                kind, what = ("order", "무엇보다 무엇이 더한지") if rel == "swapped" else ("direction", "높고 낮은 방향")
                found = Conflict(kind, line.slide_no, line.text, clause, what, relation=rel)
    return ([found], True) if found is not None else ([], False)


def comparison_conflicts(clause: str, deck: Deck, question_stems: tuple[str, ...] = ()) -> list[Conflict]:
    """`comparison_check` 의 어긋남만."""
    return comparison_check(clause, deck, question_stems)[0]
