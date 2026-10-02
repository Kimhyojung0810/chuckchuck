"""
F-11 정합 판정의 **결정적 대조** — LLM 판정 뒤에 코드가 발화와 자료 원문을 직접 견준다. f11_align 의 비공개 도우미다
(`_rubric_det` 가 f14 의 도우미인 것과 같은 자리, DEV_POLICY §4-1).

09-30 held-out 감사 C-06(혈당 녹음) 실측: aligned 18 · missing 2 · contradiction 0.
- 6장 29% 를 「49퍼센트」로 말한 문장이 식사 순서·채소 먼저·Shukla 연구의 **정합 근거**였다 → `contradictions`
- 「시간 관계상 그냥 넘어갈게요」 가 혈당 지수의 정합 근거, 두 장 발화를 이은 가짜 인용이 탄수화물 양의 근거였다 → `resolve_evidence`
  (건너뛴 장 가리기는 F-17 도 같이 써서 `_spoken.skip_targets` 에 있다)
- 실제로 말한 「첫째는 식후 졸림이고, 둘째는 … 잦은 허기」 가 missing 이었다(추정한 장 경계가 한 장 밀려 LLM 이 다른 장 발화를 봤다)
  → `spoken_sentence` : 개념 이름과 그 개념의 자료 줄 낱말을 **같이** 담은 문장이면 말한 것이다.

규칙은 전부 구조로만 — 숫자·단위·주어(`_deck_claims`), 방향 낱말, 개념 이름 토큰, 자료 줄 낱말. 덱 낱말을 규칙에 넣지 않는다.
놓치는 쪽이 안전하다(「자료와 어긋나요」 를 잘못 말하면 맞게 말한 사람이 깎인다).
"""

from __future__ import annotations

from dataclasses import dataclass

from ._deck_claims import Conflict, Deck, DeckLine, clauses, conflict_family, conflicts, content_stems, num_label, numbers
from ._match import contains_tokens, label_tokens, norm_tokens
from ._spoken import Utterance, split_sentences, spoken_numbers
from ._spoken import count_hits as _count_hits
from ._spoken import hit as _hit
from .contracts import ConceptGraph, ConceptNode, SlideDoc

# ---------------------------------------------------------------------------
# 장 글 — 자료 원문이 있으면 그것, 없으면 개념 이름·요약
# ---------------------------------------------------------------------------

def slide_texts(graph: ConceptGraph, slide_doc: SlideDoc | None) -> dict[int, str]:
    """장 번호 → 그 장의 글. 건너뛴 장을 가려낼 때 쓴다."""
    if slide_doc is not None and slide_doc.slides:
        return {s.slide_no: f"{s.title or ''} {s.raw_text or ''}".strip() for s in slide_doc.slides}
    out: dict[int, list[str]] = {}
    for n in graph.nodes:
        for no in n.slide_nos:
            out.setdefault(no, []).append(f"{n.label} {n.summary}")
    return {no: " ".join(parts) for no, parts in out.items()}


# ---------------------------------------------------------------------------
# 근거 인용 — 한 구간 안의 이어진 문장만 (09-30: 두 장을 이은 가짜 인용 · 건너뛰기 말 인용)
# ---------------------------------------------------------------------------

#: 인용이 발화에 "있다" 로 보는 낱말 포함 비율. 이 아래면 발화 원문 문장으로 바꾼다.
EVIDENCE_VERBATIM_MIN = 0.8
#: 원문 문장을 인용으로 채택하는 최소 겹침. 이 아래면 인용을 버린다 — 빈 문자열로 바꿔 "근거 없는 aligned/contradiction"
#: 강등 규칙이 받게 한다. 2026-09-13: 백스톱 뒤에도 23% 가 남았고, 그 인용이 「이렇게 말했어요」 로 화면에 나가는 건 신뢰 문제(P4)다.
#: 예전엔 0.15~0.35(「애매」)면 LLM 글을 그대로 뒀는데 그 글에 녹음에 없는 문장이 섞여 나갔다(09-30 녹음 감사 REC-06).
EVIDENCE_WINDOW_MIN = 0.35
#: 인용 창에 잇는 문장 수 상한 — 한 구간 안에서도 이보다 길면 인용이 아니라 문단이다.
EVIDENCE_MAX_SENTENCES = 3


def _ev_stems(text: str) -> list[str]:
    """인용 대조용 줄기 — 조사를 떼고 앞머리로 맞춘다(「조명과」 = 「조명」). 날 토큰 일치는 바꿔 말한 인용을 거의 못 찾았다."""
    return list(dict.fromkeys(content_stems(text or "")))


def _coverage(ev: list[str], text: str) -> float:
    return _count_hits(ev, content_stems(text)) / len(ev) if ev else 0.0


def _spans(utts: list[Utterance]):
    """같은 구간 안에서 이어진 문장 1~3개 — 건너뛰기·미루기 말은 끊는 자리다(창에 넣지 않는다)."""
    by_seg: dict[int, list[Utterance]] = {}
    for u in utts:
        by_seg.setdefault(u.seg, []).append(u)
    for seg_utts in by_seg.values():
        for i in range(len(seg_utts)):
            for k in range(1, EVIDENCE_MAX_SENTENCES + 1):
                run = seg_utts[i:i + k]
                if len(run) < k or any(not usable(u) for u in run):
                    break
                yield run


def usable(u: Utterance) -> bool:
    """근거가 될 수 있는 문장인가 — 건너뛰기(「넘어갈게요」)·미루기(「나중에 설명할게요」) 말은 아니다."""
    return not (u.skip or u.defer)


#: 인용이 건너뛰기·미루기 말과 이만큼(글자) 이어 겹치면 그 말을 인용한 것이다.
_CUE_OVERLAP_CHARS = 10


def _touches_cue(ev_text: str, u: Utterance) -> bool:
    """인용이 이 (근거가 될 수 없는) 문장의 일부를 품었나 — 문장 전체가 인용 안이거나, 인용이 문장 안이거나, 10글자 이상 겹친다."""
    if ev_text in u.text or u.text in ev_text:
        return True
    step = 3
    return any(u.text[i:i + _CUE_OVERLAP_CHARS] in ev_text
               for i in range(0, max(1, len(u.text) - _CUE_OVERLAP_CHARS + 1), step))


def _squash(text: str) -> str:
    return "".join((text or "").split()).rstrip(".?!")


def _verify_sentence(sentence: str, utts: list[Utterance]) -> tuple[str, int]:
    """
    LLM 인용의 한 문장이 발화에 **거의 그대로** 있으면 (그 발화 원문 — 한 구간 안의 이어진 문장 1~3개, 구간 번호), 없으면 ("", -1).
    거의 그대로 = 글자째 들어 있거나, 그 문장 낱말의 EVIDENCE_VERBATIM_MIN 이상이 한 창에 있다.
    """
    flat = _squash(sentence)
    if len(flat) < 2:
        return "", -1
    for u in utts:
        if usable(u) and flat in _squash(u.text):
            return u.text, u.seg
    stems = _ev_stems(sentence)
    if not stems:
        return "", -1
    best: list[Utterance] = []
    best_score = 0.0
    for run in _spans(utts):
        score = _coverage(stems, " ".join(u.text for u in run))
        if score > best_score + 1e-9 or (abs(score - best_score) <= 1e-9 and best and len(run) < len(best)):
            best, best_score = run, score
    if best_score < EVIDENCE_VERBATIM_MIN or not best:
        return "", -1
    return " ".join(u.text for u in best), best[0].seg


def _supports(node: ConceptNode, text: str) -> bool:
    """이 발화가 개념을 받치는가 — 개념 이름을 부르거나, 이름·요약 낱말을 SPOKEN_SUPPORT_MIN 개 이상 같이 말한다."""
    if label_hit(norm_tokens(text), label_tokens(node.label)):
        return True
    wanted = content_stems(f"{node.label} {node.summary}")
    return _count_hits(wanted, content_stems(text)) >= SPOKEN_SUPPORT_MIN


def _trim_unsaid(ev_text: str, node: ConceptNode, utts: list[Utterance]) -> str | None:
    """
    여러 문장 인용을 문장마다 발화와 대조한다 (09-30 녹음 감사 REC-06).
    일부만 확인되면 **확인된 문장의 발화 원문만** 남기고, 남은 말이 개념을 못 받치면 빈 문자열이다.
    전부 확인되거나 하나도 확인되지 않으면 None — 원래 규칙(가장 겹치는 발화 창으로 바꾸기)대로 간다: 통째로 바꿔 말한 인용은
    발화 원문으로 바뀌고, 발화와 애매하게만 겹치는 인용은 버려진다.
    실측: 「앞문까지 다 열 필요는 없다는 거죠. 맞통풍은 한쪽 환기보다 농도가 2배 빨리 떨어집니다.」 — 뒤 문장은 녹음에 없었고
    (발표자는 반대로 말했다) 전체 겹침이 0.15~0.35 라 LLM 글이 그대로 「이 슬라이드에서 한 말」 이 됐다.
    """
    sents = split_sentences(ev_text)
    if len(sents) < 2:
        return None
    found = [_verify_sentence(x, utts) for x in sents]
    hits = [(text, seg) for text, seg in found if text]
    if not hits or len(hits) == len(found):
        return None
    # 한 구간 안의 말만 — 확인된 문장이 여러 구간에 흩어졌으면 가장 많이 남은 구간 하나
    segs = [seg for _, seg in hits]
    top = max(set(segs), key=segs.count)
    kept = list(dict.fromkeys(text for text, seg in hits if seg == top))
    remain = " ".join(kept)
    return remain if _supports(node, remain) else ""


def resolve_evidence(evidence: str, node: ConceptNode, utts: list[Utterance],
                     deck_texts: list[str] | None = None) -> str:
    """
    LLM 이 낸 인용을 **한 구간 안의 이어진 발화 문장**으로 맞춘다.

    - 인용이 한 구간 안에 그대로 있고 건너뛰기·미루기 말과 안 겹치면 그대로 둔다.
    - 여러 문장 인용은 문장마다 발화와 대조한다 — 발화에 없는 문장(지어낸 말)은 빼고, 남은 말이 개념을 못 받치면 빈 문자열 (09-30 REC-06).
    - 아니면 그 개념의 근거 장 구간(없으면 전체)에서 가장 겹치는 문장 1~3개로 바꾼다 — 구간을 넘어 잇지 않는다.
      09-30 실측: 24어절 창이 1장 끝과 3장 머리를 이어 「…먹었느냐보다 그러니까 졸린 건 …」 가 탄수화물 양의 근거가 됐다.
    - 건너뛰기 말을 인용했으면 빈 문자열 — 근거가 아니다(혈당 지수 ← 「시간 관계상 그냥 넘어갈게요」).
    - 발화가 아니라 **자료 글**을 옮긴 인용(「혈당 부하 = 혈당 지수 × 탄수화물 양 ÷ 100」)이면 빈 문자열 — 발표자가 한 말이 아니다.
    - 발화와 애매하게만 겹치는(EVIDENCE_WINDOW_MIN 아래) 인용은 빈 문자열 — 확인하지 못한 글을 「발표에서 한 말」 로 보이지 않는다.
    짧은 인용(낱말 3개 미만)은 판단할 근거가 없어 그대로 둔다.
    """
    ev_text = " ".join((evidence or "").split())
    if not ev_text or not utts:
        return ev_text
    # 근거가 될 수 있는 문장 **하나 안에** 그대로 있으면 건너뛰기 말과 낱말이 겹쳐도 그 문장의 인용이다 (「혈당 부하」 는 1장에서도 말했다)
    in_usable = any(ev_text in u.text for u in utts if usable(u))
    if not in_usable and any(not usable(u) and _touches_cue(ev_text, u) for u in utts):
        return ""
    ev = _ev_stems(ev_text)
    if len(ev) < 3:
        return ev_text
    seg_texts: dict[int, str] = {}
    for u in utts:
        seg_texts[u.seg] = f"{seg_texts.get(u.seg, '')} {u.text}".strip()
    if any(ev_text in t for t in seg_texts.values()):
        return ev_text
    trimmed = _trim_unsaid(ev_text, node, utts)
    if trimmed is not None:
        return trimmed
    own = [u for u in utts if u.slide_no in node.slide_nos]
    best, best_score, best_len = "", 0.0, 0
    for pool in (own, utts):
        for run in _spans(pool):
            text = " ".join(u.text for u in run)
            score = _coverage(ev, text)
            # 같은 점수면 짧은 쪽 — 앞에 붙은 딴 말(「아 그리고 장표 색이 좀 이상하게…」)을 인용에 싣지 않는다
            if score > best_score + 1e-9 or (abs(score - best_score) <= 1e-9 and best and len(run) < best_len):
                best, best_score, best_len = text, score, len(run)
        if best_score >= EVIDENCE_VERBATIM_MIN:
            return best
    if best_score >= EVIDENCE_WINDOW_MIN:
        return best
    # 발화와 애매하게만 겹치는데 **자료 글**과는 거의 같다 — 슬라이드 글을 옮겨 놓고 「발화 인용」 이라 한 것이다
    # (09-30 혈당 3장 식 「혈당 부하 = 혈당 지수 × 탄수화물 양 ÷ 100」). 예전처럼 LLM 글을 그대로 두면 안 한 말이 인용부호에 들어간다.
    if deck_texts and any(_coverage(ev, t) >= EVIDENCE_VERBATIM_MIN for t in deck_texts):
        return ""
    # 확인하지 못한 글은 인용으로 쓰지 않는다 — 예전엔 0.15~0.35 겹침을 「애매」 로 보고 LLM 글을 그대로 둬서 녹음에 없는 문장이
    # 「이 슬라이드에서 한 말」 로 보였다(09-30 REC-06).
    return ""


# ---------------------------------------------------------------------------
# 말한 문장 찾기 — 개념 이름 + 그 개념 자료 줄의 다른 낱말
# ---------------------------------------------------------------------------

#: 개념 이름을 붙여 말한 문장이 그 개념 자료 줄의 **다른** 낱말·수(값+단위)를 이만큼 같이 담으면 설명한 것으로 본다.
#: 이름만 한 번 스친 것(「개념1 설명」)은 못 넘는다 — MENTION_MIN 이 막으려던 「제목 낱말 한 번 = 설명함」 과 다르다.
SPOKEN_SUPPORT_MIN = 2
#: 자료 줄이 짧아(이름 말고 낱말·수가 둘 이하 — 「보증 가입률은 18%에 그칩니다」) 둘을 요구할 수 없을 때는 하나.
SHORT_LINE_ITEMS = 2
#: 이름 토큰이 문장 안에 흩어져 있을 때(「채소를 먼저, 그다음 … 단백질」)는 한 개 더 요구한다.
SPOKEN_LOOSE_EXTRA = 1


@dataclass(frozen=True)
class NodeLine:
    """개념 자료 줄 하나 — 이름을 뺀 줄기와 수(값+단위)."""

    stems: tuple[str, ...]
    nums: tuple = ()


def node_lines(node: ConceptNode, deck: Deck) -> list[NodeLine]:
    """개념의 자료 줄 — 근거 장의 줄 중 이름 낱말이 든 줄, 없으면 근거 장 전부, 자료가 없으면 요약."""
    name = content_stems(node.label)
    lines = [ln for ln in deck.lines if ln.slide_no in node.slide_nos]
    named = [ln for ln in lines if name and _count_hits(name, ln.stems)]
    picked = [(list(ln.stems), [n for n in ln.nums if n.unit]) for ln in (named or lines)]
    if not picked and node.summary:
        picked = [(content_stems(node.summary), [n for n in numbers(node.summary) if n.unit])]
    out = []
    for stems, nums in picked:
        rest = tuple(dict.fromkeys(x for x in stems if not _hit(name, x)))
        if rest or nums:
            out.append(NodeLine(rest, tuple(nums)))
    return out


def label_hit(u_tokens: list[str], label: list[str]) -> str:
    """'strong' — 이름 토큰이 붙어서 · 'loose' — 한 문장 안에 다 있지만 흩어져서 · '' — 없음."""
    if not label:
        return ""
    if contains_tokens(u_tokens, label):
        return "strong"
    if all(contains_tokens(u_tokens, [t]) for t in label):
        return "loose"
    return ""


@dataclass(frozen=True)
class Spoken:
    utterance: Utterance
    support: int
    strong: bool


def _support(line: NodeLine, said: list[str], said_nums: list) -> tuple[int, int]:
    """(맞은 수, 요구 수) — 이름 말고 줄기·수 중 문장에 나온 것. 짧은 줄은 하나면 된다."""
    got = _count_hits(line.stems, said) + sum(1 for n in line.nums if any(n.close_value(m) for m in said_nums))
    items = len(line.stems) + len(line.nums)
    return got, (SPOKEN_SUPPORT_MIN if items > SHORT_LINE_ITEMS else 1)


def spoken_sentence(node: ConceptNode, utts: list[Utterance], lines: list[NodeLine],
                    exclude: set[str] | None = None) -> Spoken | None:
    """이 개념을 말로 설명한 문장 하나 — 없으면 None. exclude 는 쓰지 말아야 할 문장(자료와 어긋난 문장 등)."""
    label = label_tokens(node.label)
    if not label or not lines:
        return None
    best: tuple | None = None
    for u in utts:
        if not usable(u) or (exclude and u.text in exclude):
            continue
        kind = label_hit(norm_tokens(u.text), label)
        if not kind:
            continue
        said = content_stems(u.text)
        said_nums = [n for n in numbers(spoken_numbers(u.text)) if n.unit]
        extra = 0 if kind == "strong" else SPOKEN_LOOSE_EXTRA
        scored = [(got, need + extra) for got, need in (_support(ln, said, said_nums) for ln in lines)]
        passing = [got for got, need in scored if got >= need]
        if not passing:
            continue
        support = max(passing)
        near = 0 if u.slide_no in node.slide_nos else 1 if any(abs(u.slide_no - n) <= 1 for n in node.slide_nos) else 2
        key = (kind != "strong", near, -support, u.start_sec if u.start_sec is not None else 0.0)
        if best is None or key < best[0]:
            best = (key, Spoken(u, support, kind == "strong"))
    return None if best is None else best[1]


# ---------------------------------------------------------------------------
# 자료와 어긋난 발화 — 숫자·방향
# ---------------------------------------------------------------------------

#: 발화에서 받는 어긋남 종류. 숫자(자료에 있는 수를 다른 주어에 · 자료에 없는 수를 자료가 다른 값을 붙인 주어에 · 앞뒤 값 짝)·
#: 표 서열·글줄 비교(맞바꿈·반대 방향 — `_compare`)·방향·부정.
CONTRA_KINDS = ("number", "number_unsupported", "order", "direction", "negation")
_NUMBER_KINDS = ("number", "number_unsupported")
#: 숫자가 아닌 어긋남은 발화 절이 그 자료 줄과 **같은 말**일 때만 — 자료 줄 낱말의 절반 이상, 두 개 이상.
#: 09-30 실측(집중 녹음 A.X): 「…복구 과정에서 생각보다 많은 시간이 필요합니다」 가 「손실은 화면을 본 시간보다, 다시 돌아오는
#: 과정에서 커진다」 의 맞바꾼 비교로 잡혔다 — 「생각보다」 는 비교가 아니고 겹친 낱말은 셋(7개 중)뿐이었다.
SAME_STATEMENT_RATIO = 0.5
SAME_STATEMENT_MIN = 2


@dataclass(frozen=True)
class Contra:
    node_id: str
    utterance: Utterance
    kind: str
    slide_no: int
    deck_line: str
    said: str = ""        # 발화 쪽 수치 (숫자 어긋남일 때)
    deck_said: str = ""   # 자료 쪽 수치
    relation: str = ""    # 비교 어긋남의 꼴 — "swapped"(두 쪽을 맞바꿈) · "reversed"(방향 반대)
    #: 발화 쪽 인용 — 어긋난 절부터 문장 끝까지(발화 원문 그대로). 앞 절이 딴 말이면 뗀다(`clause_quote`).
    quote: str = ""

    @property
    def family(self) -> str:
        """모순의 갈래 — "number" · "direction" · "polarity" (`AlignmentItem.contra_kind`)."""
        return conflict_family(self.kind)


def clause_quote(text: str, claim: str) -> str:
    """
    발화 문장에서 어긋난 절(claim)부터 문장 끝까지 — 원문 그대로. 앞에 붙은 딴 절(「그리고 여는 방법도 비교했는데요,」)을 뗀다.
    09-30 실측(녹음 모드 화면): 모순 질문이 문장 첫 절을 따옴표로 들어 「발표에서 “여는 방법도 비교했는데요”라고 했는데 … 달라요」 가
    됐다. claim 은 수를 자료 표기로 바꾼 글에서 나온 절이라, 원문을 같은 규칙(`clauses`)으로 갈라 낱말이 가장 많이 겹치는 절을 고른다.
    """
    parts = clauses(text)
    if len(parts) < 2:
        return text
    want = content_stems(claim)
    best = max(range(len(parts)), key=lambda i: (_count_hits(want, content_stems(spoken_numbers(parts[i]))), -i))
    if best == 0:
        return text
    head = " ".join(parts[best].split()[:2])
    i = text.find(head)
    return text[i:].strip() if i > 0 else text


def _same_statement(claim: str, deck_line: str) -> bool:
    line = list(dict.fromkeys(content_stems(deck_line, drop_units=True)))
    if not line:
        return False
    hits = _count_hits(line, content_stems(claim, drop_units=True))
    return hits >= SAME_STATEMENT_MIN and hits >= SAME_STATEMENT_RATIO * len(line)


def _precise_line(c: Conflict, deck: Deck) -> DeckLine | None:
    """Conflict 의 자료 쪽(「줄+다음 줄」 로 이은 영역일 수 있다)에서 주장과 가장 가까운 한 줄."""
    said = content_stems(c.claim)
    inside = [ln for ln in deck.lines if ln.slide_no == c.slide_no and ln.text and ln.text in c.deck_line]
    if not inside:
        return None
    return max(inside, key=lambda ln: (_count_hits(list(ln.stems), said), bool(ln.nums), -len(ln.text)))


def _num_label(n) -> str:
    return num_label(n)


def _number_pair(claim: str, deck_line: str, c: Conflict | None = None) -> tuple[str, str]:
    """
    발화 수치와 자료 수치. 대조가 어느 수끼리 어긋났는지 알면(`Conflict.said·deck_value`) 그것, 아니면 같은 단위이면서
    **한쪽에만 있는** 첫 짝 — 「31%에서 88%까지」 ↔ 「31% | 78%」 는 (88%, 78%) 다(예전엔 같은 31% 를 발화 쪽으로 골랐다).
    """
    if c is not None and c.said and c.deck_value:
        return c.said, c.deck_value
    mine, theirs = numbers(claim), numbers(deck_line)
    mine_only = [n for n in mine if n.unit and not any(n.close_value(d) for d in theirs)]
    theirs_only = [d for d in theirs if d.unit and not any(d.close_value(n) for n in mine)]
    for n in mine_only:
        for d in theirs_only:
            if d.unit == n.unit:
                return _num_label(n), _num_label(d)
    return "", ""


def node_for(graph: ConceptGraph, slide_no: int, text: str, taken: set[str] | frozenset[str] = frozenset()) -> ConceptNode | None:
    """
    어긋난 자료 줄의 주인 개념 — 그 장 개념 중 이름·요약 낱말이 가장 많이 겹치는 것(이름은 두 배). 비기면 무거운 쪽.
    taken(이미 다른 모순을 받은 개념)은 빼고 고른다 — 여러 장에 걸친 개념 하나가 앞 장 모순을 받으면 뒤 장 모순이 통째로 버려졌다.
    """
    said = content_stems(text)
    cands = [n for n in graph.nodes if slide_no in n.slide_nos and n.id not in taken]
    if not cands:
        return None

    def score(n: ConceptNode) -> tuple:
        return (2 * _count_hits(content_stems(n.label), said) + _count_hits(content_stems(n.summary), said), n.weight)

    return max(cands, key=score)


#: % 와 %p 는 받아쓰기·말에서 섞인다 (「0.8%」 라고 읽은 자료 「0.8%p」). 값 대조에서는 같은 단위로 본다.
_PCT_UNITS = {"%", "%p", "p.p", "p.p.", "pct", "pp"}   # numbers() 는 % → pct · %p → pp 로 적는다


def _units_match(a: str | None, b: str | None) -> bool:
    return a == b or (a in _PCT_UNITS and b in _PCT_UNITS)


def _said_on_slide(c: Conflict, deck: Deck) -> bool:
    """
    수 모순인데 오판으로 볼 근거가 분명한가. 10-01 수익률 녹음 오판 셋을 **그 꼴로만** 거른다 — 같은 장에 그 수가 있다는 것만으로는
    거르지 않는다(자료 「A 30%, B 50%」 에 「A는 50%」 는 진짜 모순이다).
    ① 같은 줄에 %↔%p 만 다른 같은 값: 「이 차이가 0.8% 8% 밖에」 ↔ 「8.7% vs 7.9% — 0.8%p」
    ② 같은 장에 소수점만 빠진 값: 「26%p 밑돕니다」 ↔ 「상위 25% 그룹도 지수를 2.6%p 하회」 (받아쓰기가 소수점을 놓쳤다)
    ③ 자료 쪽 값이 없다: 「나머지 4개는」 ↔ 견줄 자료 수 없음
    """
    if not c.deck_value:
        return True
    said = [n for n in (numbers(c.said) if c.said else numbers(c.claim)) if n.unit]
    if not said:
        return False
    line_nums = numbers(c.deck_line)
    for s in said:
        for d in line_nums:
            if (s.unit != d.unit and s.unit in _PCT_UNITS and d.unit in _PCT_UNITS
                    and abs(s.value - d.value) <= 1e-9):
                return True
    slide_nums = [n for ln in deck.lines if ln.slide_no == c.slide_no for n in numbers(ln.text)]
    for s in said:
        for d in slide_nums:
            if (_units_match(s.unit, d.unit) and d.decimals and not s.decimals
                    and abs(s.value - d.value * 10 ** d.decimals) <= 1e-9):
                return True
    return False


def contradictions(graph: ConceptGraph, utts: list[Utterance], deck: Deck) -> list[Contra]:
    """
    발화 문장마다 자료 원문과 숫자·방향을 견준다 (`_deck_claims.conflicts`). 받아쓰기 수 표기(「49퍼센트」)는 먼저 자료 표기로 바꾼다.
    장 구간은 추정일 수 있어 자료 **전체** 와 견주고, 어긋난 줄이 있는 장의 개념에 붙인다. 개념 하나에 첫 어긋남만.
    """
    if deck.empty:
        return []
    out: list[Contra] = []
    taken: set[str] = set()
    for u in utts:
        if not usable(u):
            continue
        text = spoken_numbers(u.text)
        for c in conflicts(text, deck):
            if c.kind not in CONTRA_KINDS:
                continue
            # 같은 말인지 따로 본다 — 비교 대조(relation 이 있다)는 주어·대상 두 쪽이 서로 맞아야만 어긋남을 내므로 이미 같은 비교다.
            if c.kind not in _NUMBER_KINDS and not c.relation and not _same_statement(c.claim, c.deck_line):
                continue
            if c.kind in _NUMBER_KINDS and _said_on_slide(c, deck):
                continue
            precise = _precise_line(c, deck)
            deck_line = precise.text if precise is not None else c.deck_line
            node = node_for(graph, c.slide_no, f"{deck_line} {c.claim}", taken)
            if node is None:
                continue
            said, deck_said = _number_pair(c.claim, deck_line, c) if c.kind in _NUMBER_KINDS else ("", "")
            taken.add(node.id)
            out.append(Contra(node.id, u, c.kind, c.slide_no, deck_line, said, deck_said, c.relation,
                              clause_quote(u.text, c.claim)))
            break                               # 문장 하나에 모순 하나 — 같은 문장이 두 개념의 모순이 되지 않게
    return out
