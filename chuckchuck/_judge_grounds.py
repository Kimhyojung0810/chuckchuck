"""
[F-09 보조] 판정 근거 줄 — 자료 줄에 번호를 매기고, LLM 이 고른 **번호**를 자료 글로 되찾는다 (2026-10-01 · qa/judge-grounds).

사용자 보고(2026-10-01, 수면 덱): 「자료에서 제시한 '시간 × 연속성 × 규칙성'이라는 구체적인 구성 요소와 그 관계를 함께 설명하면…」 —
분명 자료에서 온 말인데 몇 장의 어느 줄인지, 그 줄이 왜 이 질문의 답인지가 화면에 없었다. 판정이 기댄 줄을 **보이게** 한다.

어떻게 (09-29 논문 대조의 교훈을 그대로 — 인용을 LLM 이 베껴 쓰게 하지 않는다)
----------------------------------------------------------------------------------
1. `index_lines` — 자료 줄(`_deck_claims.build_deck` 의 줄: 글 상자 한 줄 · 표 한 행 · 식은 한 줄로 이은 것)에 장마다 `S{장}-{k}` 번호를
   매긴다. 장 안의 순서는 본문에 나온 차례다. 같은 자료면 같은 번호다(판정 캐시·재현에 필요하다).
2. 판정 프롬프트의 자료 블록(`f09_judge._slide_block` · `_deck_line_block`)이 줄마다 `[S4-2]` 를 달고, LLM 은
   `"grounds": [{"ref": "S4-2", "role": "missing", "note": "…"}]` 로 **번호만** 돌려준다.
3. `parse_grounds` → `resolve_grounds` — 번호를 자료 글로 되찾는다. 모르는 번호는 버리되, 장은 맞고 줄 번호만 어긋났으면(「S4」·「S4-9」)
   그 장에서 설명(note)·반응과 가장 많이 겹치는 줄로 잇는다. 겹치는 줄이 없으면 버린다 — 짐작한 줄을 근거라고 보이지 않는다.
4. `finalize_grounds` — 최종 판정과 맞춘다: 코드 가드가 찾은 어긋남(`Conflict`)은 그 자료 줄을 맨 앞 conflict 로, 가드가 답의 내용을
   인정하지 않은 판정(무관·되읊기·나열·주입·어긋남…)에서는 「짚은 줄(covered)」 을 빼고, good 이면 「빠진 줄(missing)」 을 뺀다.
   정답이 새면 안 되는 질문(안 풀린 함정·모순 질문)은 호출자가 준 `leaks` 로 거른다. LLM 이 하나도 안 줬는데 결손이 있거나 반응이
   자료를 들면 코드가 가장 가까운 줄을 고른다(`nearest_lines`, 근거 장 먼저).
5. `cite_slides` — 반응·총평의 맨 「자료에서/자료의 …」 에 장 번호를 끼운다(「자료 4장에서」). 프롬프트로 부탁만 하면 solar 가 자주 빼먹는다.

정답 누설과의 관계 (규칙 3 「골자를 react 에 옮겨 흘리지 마라」)
------------------------------------------------------------------
빠진 줄(missing)의 **자료 글**은 보여 준다 — 사용자가 원한 것이 그것이고, 발표자 자신의 슬라이드 글이라 힌트 사다리 1단(「자료 N장은
이렇게 말해요 — «…»」)·코칭 인용 카드와 같은 층의 공개다. 대신 설명(note)은 **가리키기**까지만: 골자를 거의 그대로(`GIST_ECHO_MIN`)
옮긴 설명은 호출자의 `clean_note` 가 지운다(줄은 남는다). 함정·모순처럼 자료 줄 자체가 정답인 질문은 풀기 전까지 그 줄을 싣지 않는다.

어느 발표에나 같은 규칙이다 — 덱 낱말·예시를 쓰지 않는다. 줄 번호·겹침·역할만 본다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

from ._deck_claims import Conflict, Deck, content_stems, nearest_lines
from ._judge_post import _has as _stem_in
from ._judge_post import cap_length, sentences
from .contracts import QA_GROUND_ROLES, QA_GROUNDS_MAX, JudgeGround

#: 프롬프트에 싣는 자료 줄 한 줄의 상한 (자) — 넘치면 「…」. 되찾는 글(quote)은 자르지 않은 원문이다.
PROMPT_LINE_MAX = 160
#: 화면 카드의 인용 상한 (자). 표 한 행이 길게 붙은 줄이 카드를 덮지 않게.
QUOTE_MAX = 140
#: 설명(note) 상한 (자) — 한 문장.
NOTE_MAX = 110
#: LLM 이 준 근거 항목을 이만큼까지만 본다 (그 뒤는 버린다 — 늘어놓은 목록은 근거가 아니다).
RAW_MAX = 8
#: 줄 번호로 못 되찾은 항목(장만 맞음)을 그 장의 줄에 이을 때 필요한 겹친 낱말 수.
REMAP_MIN_OVERLAP = 2
#: 번호 매긴 줄이 장 본문(정리한 글)의 이만큼을 못 덮으면 장 본문 전체도 같이 싣는다 — 줄로 못 읽은 글(영문 긴 줄 등)을 판정이 잃지 않게.
LINE_COVER_MIN = 0.6


@dataclass(frozen=True)
class LineRef:
    """번호 매긴 자료 줄 하나."""
    ref: str        # "S4-2"
    slide_no: int
    text: str


class LineIndex:
    """자료 줄 번호표 — 번호 → 줄, (장, 글) → 번호, 장 → 줄들."""

    def __init__(self, refs: Iterable[LineRef] = ()):
        self._refs: dict[str, LineRef] = {}
        self._by_key: dict[tuple[int, str], LineRef] = {}
        self._slides: dict[int, list[LineRef]] = {}
        for r in refs:
            self._refs[r.ref] = r
            self._by_key.setdefault((r.slide_no, r.text), r)
            self._slides.setdefault(r.slide_no, []).append(r)

    @property
    def empty(self) -> bool:
        return not self._refs

    def get(self, ref: str) -> LineRef | None:
        return self._refs.get(ref)

    def of_line(self, slide_no: int, text: str) -> LineRef | None:
        return self._by_key.get((slide_no, text))

    def in_slide(self, slide_no: int) -> list[LineRef]:
        return list(self._slides.get(slide_no, []))

    def slides(self) -> list[int]:
        return sorted(self._slides)

    def __len__(self) -> int:
        return len(self._refs)


def _position(body: str, text: str) -> int:
    """줄이 장 본문 어디에 처음 나오나 — 표 행(「a | b」)은 첫 칸으로 찾는다. 못 찾으면 -1."""
    head = text.split(" | ")[0].strip()
    for probe in (text, head[:24], head[:10]):
        if probe:
            i = body.find(probe)
            if i >= 0:
                return i
    return -1


def index_lines(deck: Deck, slide_texts: dict[int, str] | None = None) -> LineIndex:
    """
    자료 줄마다 `S{장}-{k}` 번호. k 는 장 본문(slide_texts — 정리한 글)에 나온 차례(못 찾은 줄은 뒤로, 원래 차례대로).
    `build_deck` 은 표 행을 글줄보다 먼저 쌓는다 — 번호가 표부터 매겨지면 LLM 이 읽는 차례와 번호가 어긋난다.
    """
    per_slide: dict[int, list[str]] = {}
    for ln in deck.lines:
        texts = per_slide.setdefault(ln.slide_no, [])
        if ln.text and ln.text not in texts:
            texts.append(ln.text)
    refs: list[LineRef] = []
    for no in sorted(per_slide):
        texts = per_slide[no]
        body = (slide_texts or {}).get(no, "")
        if body:
            big = len(body) + 1
            keyed = [(_position(body, t), i, t) for i, t in enumerate(texts)]
            texts = [t for _, _, t in sorted(keyed, key=lambda x: (x[0] if x[0] >= 0 else big + x[1], x[1]))]
        refs.extend(LineRef(f"S{no}-{k}", no, t) for k, t in enumerate(texts, start=1))
    return LineIndex(refs)


def _squash(text: str) -> int:
    return len(re.sub(r"[\s|•·\-–—]+", "", text or ""))


def numbered_slide(index: LineIndex, slide_no: int, body: str, budget: int, fence: Callable[[str], str]) -> list[str]:
    """
    판정 프롬프트의 근거 장 한 장 — 줄마다 `[S4-2] 글`. 번호 매긴 줄이 없으면 빈 목록(호출자가 예전 모양으로 싣는다).
    번호 줄이 본문을 덜 덮으면(LINE_COVER_MIN) 본문 전체를 `[S4] …` 로 먼저 싣는다 — 번호는 줄로 읽힌 것만 단다.
    예산(budget, 자)은 장 하나의 몫이다 — 넘치면 뒤 줄은 싣지 않는다(첫 줄은 잘라서라도 싣는다).
    """
    refs = index.in_slide(slide_no)
    if not refs:
        return []
    out: list[str] = []
    used = 0
    covered = sum(_squash(r.text) for r in refs)
    if body and covered < LINE_COVER_MIN * _squash(body):
        whole = body if len(body) <= budget else body[: max(1, budget - 1)].rstrip() + "…"
        out.append(f"[S{slide_no}] {fence(whole)}")
        used += len(whole)
    for r in refs:
        text = r.text if len(r.text) <= PROMPT_LINE_MAX else r.text[: PROMPT_LINE_MAX - 1].rstrip() + "…"
        if out and used + len(text) > budget:
            break
        out.append(f"[{r.ref}] {fence(text)}")
        used += len(text)
    return out


# ---------------------------------------------------------------------------
# LLM 이 준 근거 → 자료 줄
# ---------------------------------------------------------------------------

_REF_RE = re.compile(r"(?<![A-Za-z0-9])S?\s*(\d{1,3})\s*[-–—_.]\s*(\d{1,3})(?!\d)", re.I)
_SLIDE_REF_RE = re.compile(r"^\s*\[?\s*(?:S\s*)?(\d{1,3})\s*(?:장)?\s*\]?\s*$", re.I)
_ROLE_ALIASES = {
    "covered": "covered", "cover": "covered", "hit": "covered", "ok": "covered", "correct": "covered",
    "맞힌": "covered", "맞힌 것": "covered", "짚은": "covered", "짚은 것": "covered",
    "missing": "missing", "miss": "missing", "gap": "missing", "빠진": "missing", "빠진 것": "missing",
    "conflict": "conflict", "contradiction": "conflict", "wrong": "conflict", "어긋난": "conflict", "어긋난 것": "conflict",
}


@dataclass(frozen=True)
class RawGround:
    """LLM 이 준 근거 한 항목 — 다듬은 번호(「S4-2」·장만이면 「S4」) · 역할(모르면 "") · 설명."""
    ref: str
    role: str
    note: str


def _norm_role(raw: object) -> str:
    key = str(raw or "").strip().lower()
    return _ROLE_ALIASES.get(key, key if key in QA_GROUND_ROLES else "")


def parse_grounds(raw: object) -> list[RawGround]:
    """LLM 응답의 grounds 칸 → RawGround 목록. 모양이 달라도(문자열 목록·dict 하나·「[S4-2]」) 번호만 읽히면 받는다."""
    if isinstance(raw, (dict, str)):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    out: list[RawGround] = []
    for item in raw[:RAW_MAX]:
        if isinstance(item, str):
            ref_raw, role, note = item, "", ""
        elif isinstance(item, dict):
            ref_raw = item.get("ref") or item.get("id") or item.get("line") or item.get("slide") or ""
            role, note = _norm_role(item.get("role")), str(item.get("note", "") or "").strip()
        else:
            continue
        ref_raw = str(ref_raw)
        m = _REF_RE.search(ref_raw)
        if m:
            ref = f"S{int(m.group(1))}-{int(m.group(2))}"
        else:
            s = _SLIDE_REF_RE.match(ref_raw)
            if not s:
                continue
            ref = f"S{int(s.group(1))}"
        out.append(RawGround(ref, role, note))
    return out


def _overlap(a: str, b_stems: list[str]) -> int:
    return sum(1 for s in dict.fromkeys(content_stems(a)) if _stem_in(b_stems, s))


def _best_in_slide(index: LineIndex, slide_no: int, clue: str) -> LineRef | None:
    """장 안에서 단서(설명·반응)와 가장 많이 겹치는 줄 — REMAP_MIN_OVERLAP 밑이면 None (짐작한 줄을 근거로 보이지 않는다)."""
    clue_stems = content_stems(clue)
    if not clue_stems:
        return None
    best, best_n = None, 0
    for r in index.in_slide(slide_no):
        n = _overlap(r.text, clue_stems)
        if n > best_n:
            best, best_n = r, n
    return best if best_n >= REMAP_MIN_OVERLAP else None


def _clip_quote(text: str) -> str:
    text = (text or "").strip()
    return text if len(text) <= QUOTE_MAX else text[: QUOTE_MAX - 1].rstrip() + "…"


#: 번호가 가리킨 줄과 설명이 거의 안 겹치는데(RECOUNT_HIT_MAX 이하) 다른 줄이 설명과 이만큼 겹치면 LLM 이 번호를 잘못 센 것이다.
RECOUNT_MIN_OVERLAP = 3
RECOUNT_HIT_MAX = 1


def _recount(index: LineIndex, hit: LineRef, note: str) -> LineRef:
    """
    LLM 이 줄 번호를 잘못 센 경우를 고친다 — 설명(note)이 가리킨 줄과는 낱말 하나 겨우 겹치는데 다른 줄과는 셋 넘게 겹치면 그 줄이다.
    2026-10-01 실측(solar): 「침대에 누워 있던 시간과 실제 회복 시간이 다를 수 있음」 을 설명하며 번호는 다른 장의 「잠을 오래 잤다고 …」
    를 댔다. 설명이 짧거나 줄을 풀어 말해 겹침이 적으면 번호를 그대로 믿는다(RECOUNT_MIN_OVERLAP).
    """
    stems = content_stems(note)
    if not stems or _overlap(hit.text, stems) > RECOUNT_HIT_MAX:
        return hit
    best, best_n = hit, _overlap(hit.text, stems)
    for no in index.slides():
        for r in index.in_slide(no):
            n = _overlap(r.text, stems)
            if n > best_n:
                best, best_n = r, n
    return best if best is not hit and best_n >= RECOUNT_MIN_OVERLAP and best_n >= _overlap(hit.text, stems) + 2 else hit


def resolve_grounds(raw: list[RawGround], index: LineIndex, *, clue: str = "") -> list[JudgeGround]:
    """
    번호 → 자료 줄. 모르는 번호는 버리고, 장만 맞으면 그 장에서 설명·단서와 겹치는 줄로 잇는다. 번호를 잘못 센 것이 설명으로 드러나면
    설명이 가리키는 줄로 고친다(`_recount`). 역할은 아직 비어 있을 수 있다.
    """
    out: list[JudgeGround] = []
    for g in raw:
        hit = index.get(g.ref)
        if hit is None:
            m = re.match(r"S(\d+)", g.ref)
            hit = _best_in_slide(index, int(m.group(1)), f"{g.note} {clue}") if m else None
        elif g.note:
            hit = _recount(index, hit, g.note)
        if hit is None:
            continue
        out.append(JudgeGround(slide_no=hit.slide_no, quote=hit.text, role=g.role, note=g.note, ref=hit.ref))
    return out


# ---------------------------------------------------------------------------
# 최종 판정과 맞추기
# ---------------------------------------------------------------------------

#: 코드 가드가 **답의 내용을 인정하지 않은** 판정 — 이때 「짚은 줄」 을 보이면 가드의 말(「질문과 다른 이야기예요」)과 싸운다.
DROP_COVERED_GUARDS = frozenset({
    "trap", "trap_misfixed", "trap_open", "injection", "off_topic", "focus_miss", "list", "echo", "ungrounded",
    "language", "restated", "self_opposed", "contra_said", "deck", "number_unsupported",
})
_ROLE_ORDER = {"conflict": 0, "covered": 1, "missing": 2}


def _line_of_conflict(conflict: Conflict, index: LineIndex) -> JudgeGround | None:
    """가드가 찾은 어긋남의 자료 줄 → 번호 매긴 줄. 표 칸·두 줄 이은 영역이면 그 장에서 그 글을 품은 줄·가장 겹치는 줄."""
    hit = index.of_line(conflict.slide_no, conflict.deck_line)
    if hit is None:
        inside = [r for r in index.in_slide(conflict.slide_no)
                  if r.text and (r.text in conflict.deck_line or conflict.deck_line in r.text)]
        if inside:
            stems = content_stems(conflict.claim)
            hit = max(inside, key=lambda r: _overlap(r.text, stems))
    if hit is None:
        hit = _best_in_slide(index, conflict.slide_no, f"{conflict.deck_line} {conflict.claim}")
    quote = hit.text if hit is not None else conflict.deck_line
    if not quote.strip():
        return None
    what = (conflict.what or "").strip()
    note = f"다시 볼 곳: {what} — 이 줄과 방금 한 말을 나란히 놓고 견줘 보세요." if what else "이 줄과 방금 한 말을 나란히 놓고 견줘 보세요."
    return JudgeGround(slide_no=conflict.slide_no, quote=quote, role="conflict", note=note, ref=hit.ref if hit else "")


def _sub_deck(deck: Deck, nos: set[int]) -> Deck:
    lines = tuple(ln for ln in deck.lines if ln.slide_no in nos)
    return Deck(lines, (), (), frozenset(s for ln in lines for s in ln.stems), ())


def _nearest(text: str, deck: Deck, anchors: set[int], index: LineIndex, *, skip: set[str] = frozenset(),
             avoid_stems: list[str] | None = None) -> LineRef | None:
    """글과 가장 가까운 자료 줄(번호 있는 것) — 근거 장 먼저, 없으면 자료 전체. avoid_stems(답)를 거의 다 담은 줄은 「빠진 줄」 이 아니다."""
    for pool in ((_sub_deck(deck, anchors) if anchors else None), deck):
        if pool is None or pool.empty:
            continue
        for ln in nearest_lines(text, pool, k=4):
            ref = index.of_line(ln.slide_no, ln.text)
            if ref is None or ref.ref in skip:
                continue
            if avoid_stems is not None:
                mine = list(dict.fromkeys(content_stems(ln.text)))
                if mine and sum(1 for s in mine if _stem_in(avoid_stems, s)) >= 0.8 * len(mine):
                    continue
            return ref
    return None


def finalize_grounds(
    candidates: list[JudgeGround],
    *,
    index: LineIndex,
    deck: Deck | None,
    said: str,
    verdict: str,
    passed: bool,
    guard: str = "",
    conflict: Conflict | None = None,
    points: list[str] | tuple[str, ...] = (),
    react: str = "",
    anchors: Iterable[int] = (),
    leaks: Callable[[str], bool] | None = None,
    clean_note: Callable[[str], str] | None = None,
    fallback: bool = True,
) -> list[JudgeGround]:
    """
    LLM 이 준 근거(되찾은 것)를 최종 판정에 맞춰 다듬고, 없으면 코드가 고른다. 결과는 conflict → covered → missing 차례, 많아야
    QA_GROUNDS_MAX. 한 줄은 한 번만(역할은 conflict > missing > covered 가 이긴다).
    """
    if index.empty:
        return []
    said_stems = content_stems(said)
    leaky = leaks or (lambda _t: False)
    tidy = clean_note or (lambda t: t)
    out: list[JudgeGround] = []

    if conflict is not None:
        g = _line_of_conflict(conflict, index)
        if g is not None and not leaky(g.quote):
            out.append(g)

    for g in candidates:
        role = g.role
        if not role:
            mine = list(dict.fromkeys(content_stems(g.quote)))
            hit = sum(1 for s in mine if _stem_in(said_stems, s))
            role = "covered" if mine and (hit >= 2 or hit >= 0.5 * len(mine)) else "missing"
        if role == "covered" and not _said_enough(g.quote, said_stems):
            continue                    # 답과 낱말 한둘만 겹치는 줄을 「짚었다」 고 보이지 않는다
        if role == "conflict" and (passed or conflict is not None):
            continue                    # 통과한 답엔 어긋남이 없다 · 가드가 찾은 어긋남이 있으면 그 줄이 먼저다
        if role == "covered" and guard in DROP_COVERED_GUARDS:
            continue
        if role == "missing" and verdict == "good":
            continue
        out.append(JudgeGround(g.slide_no, g.quote, role, g.note, g.ref))

    anchor_set = {int(n) for n in anchors if n}
    # 결손마다 근거 줄이 있어야 한다(규칙 11) — LLM 이 결손을 적고 그 줄을 안 댔으면 첫 결손의 줄을 코드가 고른다.
    # 짚은 줄은 LLM 이 아무 줄도 안 댔고 통과한 답일 때만 고른다(무엇을 짚었는지 짐작이 적을수록 좋다).
    if fallback and deck is not None and not deck.empty:
        taken = {g.ref for g in out if g.ref}
        if points and verdict != "good" and not any(g.role == "missing" for g in out):
            ref = _nearest(points[0], deck, anchor_set, index, skip=taken, avoid_stems=said_stems)
            if ref is not None:
                out.append(JudgeGround(ref.slide_no, ref.text, "missing", f"아직 안 나온 «{points[0]}» — 이 줄에서 찾을 수 있어요.",
                                       ref.ref))
        elif not out and passed and guard not in DROP_COVERED_GUARDS and said.strip():
            ref = _nearest(said, deck, anchor_set, index, skip=taken)
            if ref is not None:
                out.append(JudgeGround(ref.slide_no, ref.text, "covered", "", ref.ref))

    # 한 줄은 한 번 — 역할이 센 쪽이 이긴다
    best: dict[tuple[int, str], JudgeGround] = {}
    for g in out:
        key = (g.slide_no, g.quote)
        prev = best.get(key)
        strength = {"conflict": 2, "missing": 1, "covered": 0}
        if prev is None or strength[g.role] > strength[prev.role]:
            best[key] = g
    kept = [g for g in out if best.get((g.slide_no, g.quote)) is g]
    kept = [g for g in kept if not leaky(g.quote)]

    finals: list[JudgeGround] = []
    for g in kept:
        note = tidy(g.note or "")
        if note and (leaky(note) or _echoes_quote(note, g.quote)):
            note = ""
        finals.append(JudgeGround(g.slide_no, _clip_quote(g.quote), g.role, cap_length(note, NOTE_MAX) if note else "", g.ref))

    # 어긋난 줄 하나 · 짚은 줄 하나 · 빠진 줄 둘까지. 빠진 줄이 없으면 짚은 줄을 하나 더(둘까지) — 좋은 답에 카드 셋은 무겁다 (실측).
    by_role = {r: [g for g in finals if g.role == r] for r in QA_GROUND_ROLES}
    picked = by_role["conflict"][:1] + by_role["covered"][:1] + by_role["missing"][:2]
    if not by_role["missing"]:
        picked += by_role["covered"][1:COVERED_MAX]
    picked = picked[:QA_GROUNDS_MAX]
    return sorted(picked, key=lambda g: _ROLE_ORDER.get(g.role, 3))


#: 설명 끝의 명사형 종결(「…정의함」「…다를 수 있음」「…핵심임」) — solar 가 note 를 개조식으로 자주 끝낸다. 해요체로 푼다.
_EUM_END_RE = re.compile(r"(해야\s?함|있음|없음|됨|함|줌|냄|임)([.。]?)\s*$")
_EUM_TO_HAEYO = {"해야 함": "해야 해요", "해야함": "해야 해요", "있음": "있어요", "없음": "없어요", "됨": "돼요", "함": "해요",
                 "줌": "줘요", "냄": "내요"}


def note_haeyo(text: str) -> str:
    """설명 문장마다 끝의 명사형 종결을 해요체로 (「…정의함」 → 「…정의해요.」, 「…요소임」 → 「…요소예요.」)."""
    out: list[str] = []
    for sent in sentences(text or ""):
        m = _EUM_END_RE.search(sent)
        if m is None:
            out.append(sent)
            continue
        end, head = m.group(1), sent[:m.start()]
        if end == "함" and head.endswith("포"):
            rep = "함해요"                    # 「…를 포함」 — 「포함」 은 명사다 (「포해요」 가 아니다)
        elif end == "임":
            last = head[-1:] if head else ""
            batchim = bool(last) and "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
            rep = "이에요" if batchim else "예요"
        else:
            rep = _EUM_TO_HAEYO.get(end, _EUM_TO_HAEYO.get(end.replace(" ", ""), end))
        out.append(f"{head}{rep}.")
    return " ".join(out)


#: 짚은 줄로 보이려면 답과 겹쳐야 하는 낱말 수 (줄의 낱말이 이보다 적으면 그 줄의 낱말 수). 「시간」 한 낱말로 엉뚱한 줄이 「짚은 것」 이 됐다 (실측).
COVERED_MIN_OVERLAP = 2
#: 짚은 줄은 많아야 둘.
COVERED_MAX = 2


def _said_enough(quote: str, said_stems: list[str]) -> bool:
    mine = list(dict.fromkeys(content_stems(quote)))
    if not mine:
        return False
    return _overlap(quote, said_stems) >= min(COVERED_MIN_OVERLAP, len(mine))


def _echoes_quote(note: str, quote: str) -> bool:
    """설명이 줄을 되풀이만 했나 — 설명의 낱말이 거의 다 그 줄의 낱말이고 새 낱말이 둘 밑이면 설명이 아니다."""
    n = list(dict.fromkeys(content_stems(note)))
    if not n:
        return True
    q = content_stems(quote)
    new = [s for s in n if not _stem_in(q, s)]
    return len(new) < 2


# ---------------------------------------------------------------------------
# 반응·총평의 맨 「자료」 에 장 번호
# ---------------------------------------------------------------------------

#: 장 번호 없이 「자료」 를 부른 자리 — 조사가 붙었거나 낱말이 거기서 끝난다(「자료들」「자료집」 은 아니다).
_BARE_DECK_RE = re.compile(r"자료(?!\s*\d)(에서는|에서|에는|에선|에|의|가|는|를|와|엔|로는|로)?(?![가-힣])")
#: 장 번호 뒤로 옮기면 받침(「장」)에 맞춰 바뀌는 조사.
_JOSA_AFTER_JANG = {"가": "이", "는": "은", "를": "을", "와": "과", "로": "으로", "로는": "으로는"}
_SLIDE_NO_RE = re.compile(r"\d+\s*장")
#: 문장이 따옴표로 옮긴 자료 글 — 「'…'」「“…”」「‘…’」「"…"」「«…»」「「…」」.
_QUOTED_RE = re.compile(r"'([^']{4,})'|‘([^’]{4,})’|“([^”]{4,})”|\"([^\"]{4,})\"|«([^»]{4,})»|「([^」]{4,})」")
#: 옮긴 글이 근거 줄의 글이라고 볼 겹침 — 옮긴 글 낱말의 이만큼이 그 줄에 있다.
QUOTED_RECALL = 0.6


def _quoted_ground(span: str, grounds: list[JudgeGround]) -> JudgeGround | None:
    stems = list(dict.fromkeys(content_stems(span)))
    if not stems:
        return None
    best, best_r = None, 0.0
    for g in grounds:
        q = content_stems(g.quote)
        r = sum(1 for s in stems if _stem_in(q, s)) / len(stems)
        if r > best_r:
            best, best_r = g, r
    return best if best_r >= QUOTED_RECALL else None


def _cite_quotes(sent: str, grounds: list[JudgeGround]) -> str:
    """장 번호 없는 문장이 근거 줄을 따옴표로 옮겼으면 닫는 따옴표 뒤에 「(자료 N장)」 — 같은 장은 한 번만."""
    done: set[int] = set()
    out, last = [], 0
    for m in _QUOTED_RE.finditer(sent):
        span = next(x for x in m.groups() if x is not None)
        g = _quoted_ground(span, grounds)
        if g is None or g.slide_no in done:
            continue
        done.add(g.slide_no)
        out.append(sent[last:m.end()] + f"(자료 {g.slide_no}장)")
        last = m.end()
    return "".join(out) + sent[last:] if out else sent


def cite_slides(text: str, grounds: list[JudgeGround], *, only: Iterable[str] | None = None, ignore: str = "") -> str:
    """
    「자료에서 제시한 …」 처럼 장 번호 없이 자료를 든 문장에 **근거 줄의 장 번호**를 끼운다(문장마다 첫 자리 하나). 이미 「N장」 이
    있는 문장은 두지 않는다. 어느 장인지는 그 문장과 가장 많이 겹치는 근거 줄로 — 동률이면 conflict·missing 줄이 먼저다. 어느 근거 줄과도
    낱말이 안 겹치는 문장(「자료의 한쪽 말만 다시 했어요」)은 근거 줄이 아닌 자료를 말할 수 있어 그대로 둔다.
    「자료」 라는 말 없이 근거 줄을 따옴표로 옮긴 문장(「'…'이라는 관계를 …」)은 옮긴 글 뒤에 「(자료 N장)」 을 단다.
    only 를 주면 그 문장들(LLM 이 쓴 문장)에만 단다. ignore(개념 이름)의 낱말은 겹침에서 뺀다 — 개념 이름은 거의 모든 줄에 있다.
    """
    if not text or not grounds:
        return text
    order = sorted(grounds, key=lambda g: {"conflict": 0, "missing": 1, "covered": 2}.get(g.role, 3))
    out: list[str] = []
    changed = False
    allowed = set(only) if only is not None else None
    skip = content_stems(ignore)
    for sent in sentences(text):
        if _SLIDE_NO_RE.search(sent) or (allowed is not None and sent not in allowed):
            out.append(sent)
            continue
        m = _BARE_DECK_RE.search(sent)
        if m is None:
            quoted = _cite_quotes(sent, grounds)   # 따옴표 안은 자료 글 그대로라 개념 이름도 센다
            changed = changed or quoted != sent
            out.append(quoted)
            continue
        stems = [x for x in content_stems(sent) if not x.startswith("자료") and not _stem_in(skip, x)]
        pick = max(order, key=lambda g: _overlap(g.quote, stems))   # max 는 동률이면 앞(order 순)을 준다
        if _overlap(pick.quote, stems) == 0:
            # 문장이 어느 근거 줄과도 낱말이 안 겹친다 — 「자료의 한쪽 말만 다시 했어요」(코드 문장)처럼 근거 줄이 아닌 자료를 말한다
            out.append(sent)
            continue
        josa = m.group(1) or ""
        josa = _JOSA_AFTER_JANG.get(josa, josa)
        out.append(f"{sent[:m.start()]}자료 {pick.slide_no}장{josa}{sent[m.end():]}")
        changed = True
    return " ".join(out) if changed else text
