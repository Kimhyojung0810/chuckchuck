"""
[F-25] 리허설 기억 — 같은 사람이 같은 발표를 다시 연습할 때, 지난 답변 과정을 되짚어 다음 Q&A 를 더 낫게 만드는 모듈입니다.
지난 세션들의 qa_turns 기록(+ConceptGraph) → MemoryDoc.  MemoryDoc + 이번 ConceptGraph → {node_id: ConceptMemory}.

    from chuckchuck.f25_memory import build_memory, link_memory
    memory = build_memory(rehearsals, file_name="deck.pdf", learner_key="learner:ab12")   # 세션에 한 번
    memory = build_memory(rehearsals, ..., graph=graph, slidedoc=slidedoc)                 # 이번 발표를 알면 더 좁힌다
    by_node = link_memory(memory, graph)                                                    # 이번 그래프의 노드에 잇기
    triage = triage_questions(graph, ..., memory=memory)      # 못 넘긴 개념이 먼저
    doc = build_questions(graph, triage, ..., memory=memory)  # "지난번엔 여기서 반쯤 왔어요" 를 알고 묻는다
    judgement = judge_answer(question, answer, ..., memory=memory)   # 지난번 빠진 점이 이번엔 나왔는지 본다

**전부 기록에서 센다.** LLM 이 채우는 필드는 없다 — 기억은 사실이어야 하고, "지난번에 이랬죠" 를 지어내면 사람을 억울하게 한다.

무엇을 기억하나 (개념 단위, 이름으로 잇는다 — 노드 id 는 세션마다 다르다):
- 몇 번 물었고 몇 번 답했고 몇 번 포기했나, 판정 분포, 마지막·최고 판정, 마지막 점수, 통과선을 넘은 턴 수, 닫힌 까닭
- 최근 판정이 짚은 「빠진 점」 (최신 3개) — 다음 질문이 그 빈틈을 겨냥하고, 판정이 「이번엔 짚었다」 를 알아본다
- 힌트를 몇 개까지 봤나 — 코칭 시작 단계를 정한다
- 그 기억이 나온 발표의 지문(물은 개념 이름들) — 다른 발표의 같은 이름에 잇지 않으려고

무엇을 기억하지 않나: 답변 원문(프롬프트에 싣지 않는다 — 지난 답을 이번 답으로 착각하게 한다), 오디오, 동의 없는 세션.
같은 파일 이름만으로는 잇지 않는다 (호출자 규칙 — 같은 이름의 남의 자료가 붙는다). 오래된 리허설은 MEMORY_SESSIONS_MAX 까지만.

09-30 감사 G-A23 (docs/review/2026-09-29_QA_근거검증/redteam/report.md):
(a) 자료 밖 결손이 다음 리허설로 넘어갔다 — 판정은 이제 자료가 받치지 않는 결손을 버리지만, 기억은 판정이 자료와 대조했는지
    묻지 않고 missing_points 를 옮겼다(옛 판정·자료 본문 없이 채점한 턴까지). 이제 **서버가 만든 질문으로 채점한 턴**
    (question_source)만 세고, 결손은 **자료와 대조한 판정**(grounded_on_deck)의 것만 — 이번 자료 본문을 주면 그걸로 다시 본다.
(b) `stalled` 가 good 만 통과로 쳤다 — 판정은 70~79 partial 도 통과(qa_passed)인데 기억은 「못 넘긴 개념」 으로 맨 앞에 세웠다.
    이제 통과 턴 수(passes)와 닫힌 까닭(close_reason)을 따로 센다. 3라운드 출구(rounds·guard)는 설득(good)이 아니다.
(c) 이름 잇기가 「부족」↔「부족 해소」 같은 반대 개념을 이었다 — contracts.memory_similarity 가 글자 차이를 따진다.
(d) 이름 하나가 같으면 다른 발표의 기억이 붙었다 — 지난 리허설을 **발표별로 묶고**(물은 개념 이름·근거 인용이 겹치는 세션끼리)
    기억마다 그 발표의 지문(deck_keys)을 싣는다. MemoryDoc.by_node 가 이번 그래프와 지문을 견준다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ._deck_claims import Deck, content_stems, deck_from_slidedoc, numbers
from .contracts import (
    MEMORY_DECK_KEYS_MAX,
    MEMORY_LINK_MIN,
    MEMORY_MISSING_MAX,
    MEMORY_PRESENTATION_KEYS_MIN,
    MEMORY_PRESENTATION_MIN,
    MEMORY_SESSIONS_MAX,
    MEMORY_VERDICT_ORDER,
    ConceptGraph,
    ConceptMemory,
    MemoryDoc,
    RehearsalSummary,
    SlideDoc,
    memory_key,
    memory_similarity,
    qa_passed,
)

#: 서버가 만든 질문으로 채점한 턴의 출처 — 브리지가 qa_turns 에 적는 question_source (b675afd). 그 밖(client·빈 값 = 옛 기록)은
#: 채점 기준을 믿을 수 없다: 09-30 R4 실측 — 본문의 함정 표시·전제를 지워 보내면 wrong 0 이 partial 70 이 됐고, 그 턴이 기억으로 흘렀다.
TRUSTED_SOURCES = frozenset({"server", "archive", "mismatch"})
#: 닫힌 까닭 (QaJudgement.close_reason). 판정 기록에 실린 값만 받는다.
_CLOSE_REASONS = frozenset({"good", "rounds", "guard"})
#: 근거 인용을 발표 지문으로 쓸 최소 길이 (공백 뺀 글자). 짧은 조각(「비용」「1장」)은 다른 발표에도 있다.
QUOTE_MIN = 8
#: 물은 개념 이름이 이만큼 겹치면 비율과 상관없이 같은 발표다 — 5분·10분 트랙은 같은 덱에서도 서로 다른 개념을 묻는다
#: (09-30 실측 모사: 10개씩 물은 두 리허설이 3개만 겹치자 다른 발표로 갈라져 기억이 조각났다). 다른 발표가 개념 이름 셋을 나누기는 어렵다.
SAME_DECK_KEYS = 3
#: 결손 낱말 가운데 이번 자료에 있어야 할 몫 — 판정의 결손 자료 지지(_judge_post POINT_DECK_MIN)와 같은 기준.
POINT_ON_DECK_MIN = 0.6
#: 결손 문장에서 **내용이 아닌** 판정 어휘 (앞머리). 이것만 겹쳐서는 자료가 받친다고 볼 수 없다. 어느 발표에나 쓰는 말만.
_POINT_META = (
    "구체", "명확", "정확", "직접", "추가", "제시", "언급", "명시", "인용", "예시", "사례", "방안", "필요", "연결", "논리",
    "측면", "관점", "요소", "항목", "포인트", "강조", "보완", "확인", "비교", "전체", "각각", "실제", "해당",
)
_WS_RE = re.compile(r"\s+")


def _verdict_rank(v: str) -> int:
    return MEMORY_VERDICT_ORDER.index(v) if v in MEMORY_VERDICT_ORDER else len(MEMORY_VERDICT_ORDER)


def _better(a: str, b: str) -> str:
    """둘 중 좋은 verdict. 빈 것은 진다."""
    if not a:
        return b
    if not b:
        return a
    return a if _verdict_rank(a) <= _verdict_rank(b) else b


# ---------------------------------------------------------------------------
# 턴 한 줄 읽기
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Turn:
    """qa_turns 한 줄에서 기억이 쓰는 것만. trusted 가 거짓이면 발표 지문(이름·인용)에만 쓴다."""
    question_id: str
    node_id: str
    label: str
    verdict: str
    score: int
    gave_up: bool
    passed: bool
    close_reason: str
    missing: tuple[str, ...]
    deck_checked: bool
    hints: int
    at: float
    trusted: bool
    quotes: frozenset[str]


def _fold_quote(text: str) -> str:
    return _WS_RE.sub("", unicodedata.normalize("NFKC", str(text or "")).lower())


def _question_quotes(q: dict) -> frozenset[str]:
    """질문이 근거로 든 자료 줄(원문 그대로 옮긴 것) — 같은 발표를 알아보는 지문. 서버가 원문과 대조해 확인한 인용만 실린다."""
    basis = q.get("basis") if isinstance(q.get("basis"), dict) else {}
    texts = [q.get("evidence_quote")]
    for part in ("evidence", "reason", "background"):
        texts += [c.get("quote") for c in (basis.get(part) or []) if isinstance(c, dict)]
    folded = (_fold_quote(t) for t in texts if t)
    return frozenset(t for t in folded if len(t) >= QUOTE_MIN)


def _read_turn(ev: dict) -> _Turn:
    q = ev.get("question") if isinstance(ev.get("question"), dict) else {}
    j = ev.get("judgement") if isinstance(ev.get("judgement"), dict) else {}
    verdict = str(j.get("verdict", "") or "unknown")
    try:
        score = int(j.get("score", 0) or 0)
    except (TypeError, ValueError):
        score = 0
    gave_up = bool(ev.get("give_up")) or (verdict == "unknown" and bool(j.get("coach_stage")))
    close = str(j.get("close_reason", "") or "")
    return _Turn(
        question_id=str(ev.get("question_id") or q.get("id") or ""),
        node_id=str(q.get("node_id", "") or ""),
        label=str(q.get("label", "") or ""),
        verdict=verdict, score=score, gave_up=gave_up,
        # 통과는 지금 규칙(등급 구간으로 자른 점수)으로 다시 센다 — 기록의 passed 는 그때 규칙이다
        passed=not gave_up and qa_passed(verdict, score),
        close_reason=close if close in _CLOSE_REASONS else ("good" if verdict == "good" else ""),
        missing=tuple(str(m).strip() for m in (j.get("missing_points") or []) if str(m).strip()),
        deck_checked=j.get("grounded_on_deck") is True,
        hints=len([h for h in (ev.get("hints_shown") or []) if str(h).strip()]),
        at=float(ev.get("at", 0.0) or 0.0),
        trusted=str(ev.get("question_source", "") or "") in TRUSTED_SOURCES,
        quotes=_question_quotes(q),
    )


# ---------------------------------------------------------------------------
# 지난 리허설 한 번 · 발표로 묶기
# ---------------------------------------------------------------------------

@dataclass
class _Past:
    session: dict
    at: float
    turns: list[_Turn]            # at 순
    keys: tuple[str, ...]         # 물은 개념 이름 열쇠 (지문, 정렬)
    quotes: frozenset[str]        # 질문 근거 인용 (지문)

    @property
    def trusted(self) -> list[_Turn]:
        return [t for t in self.turns if t.trusted]


def _read_past(session: dict) -> _Past:
    raw = [t for t in (session.get("turns") or []) if isinstance(t, dict)]
    turns = sorted((_read_turn(ev) for ev in raw), key=lambda t: t.at)
    keys = tuple(sorted({k for k in (memory_key(t.label) for t in turns) if k}))
    quotes = frozenset(q for t in turns for q in t.quotes)
    return _Past(session=session, at=float(session.get("at", 0.0) or 0.0), turns=turns, keys=keys, quotes=quotes)


def _names_overlap(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[int, int]:
    """두 지문의 이름 겹침 → (겹친 수, 작은 쪽 크기). 이름 대조는 contracts.memory_similarity (반대말은 0)."""
    small = min(len(a), len(b))
    matched = sum(1 for k in a if any(k == j or memory_similarity(k, j) >= MEMORY_LINK_MIN for j in b))
    return min(matched, small), small


def _same_presentation(a: _Past, b: _Past) -> bool:
    """
    두 리허설이 같은 발표인가. ① 근거 인용(자료 줄 그대로)을 하나라도 나누면 같다 — 다른 발표가 같은 문장을 가질 일은 드물다.
    ② 아니면 물은 개념 이름이 작은 쪽의 절반 이상·두 개 이상 겹쳐야 한다. 이름 하나(「비용」)로는 가르지 못한다.
    """
    if a.quotes & b.quotes:
        return True
    matched, small = _names_overlap(a.keys, b.keys)
    if matched >= SAME_DECK_KEYS:
        return True
    return small >= MEMORY_PRESENTATION_KEYS_MIN and matched >= MEMORY_PRESENTATION_KEYS_MIN \
        and matched / small >= MEMORY_PRESENTATION_MIN


def _presentations(pasts: list[_Past]) -> list[list[_Past]]:
    """최신 리허설부터 발표별로 묶는다 (한 줄 이음 — 묶음의 누구와든 같은 발표면 그 묶음). 결정적."""
    groups: list[list[_Past]] = []
    for p in pasts:
        if not p.turns:
            continue
        home = next((g for g in groups if any(_same_presentation(p, q) for q in g)), None)
        if home is None:
            groups.append([p])
        else:
            home.append(p)
    return groups


# ---------------------------------------------------------------------------
# 결손 — 자료가 받치는 것만
# ---------------------------------------------------------------------------

def _stem_in(stem: str, pool) -> bool:
    """같은 낱말인가 — 같거나, 한글 두 글자 이상끼리 앞머리 포함(활용·합성 꼬리)."""
    if stem in pool:
        return True
    if len(stem) < 2 or not ("가" <= stem[0] <= "힣"):
        return False
    return any(len(s) >= 2 and (s.startswith(stem) or stem.startswith(s)) for s in pool)


def point_on_deck(point: str, deck: Deck) -> bool:
    """
    결손 한 줄이 이 자료로 받쳐지는가 — 판정 어휘를 뺀 내용 낱말의 POINT_ON_DECK_MIN 이상이 자료에 있고, 숫자는 모두 자료에 있다.
    판정 모듈을 부르지 않는다(판정 내부 규칙이 바뀌어도 기억은 그대로 돈다) — 자료 대조 헬퍼(_deck_claims)만 쓴다.
    """
    nums = numbers(point)
    if any(not deck.has_number(n) for n in nums):
        return False
    stems = [s for s in dict.fromkeys(content_stems(point)) if not s.startswith(_POINT_META)]
    if not stems:
        return bool(nums)
    hit = sum(1 for s in stems if _stem_in(s, deck.stems))
    return hit / len(stems) >= POINT_ON_DECK_MIN


def _kept_points(turn: _Turn, deck: Deck | None) -> list[str]:
    """이 턴의 결손 가운데 기억에 남길 것. 이번 자료가 있으면 그걸로 다시 보고, 없으면 자료와 대조한 판정의 것만."""
    if not turn.missing:
        return []
    if deck is not None and not deck.empty:
        return [p for p in turn.missing if point_on_deck(p, deck)]
    return list(turn.missing) if turn.deck_checked else []


# ---------------------------------------------------------------------------
# 개념 기억 · 요약
# ---------------------------------------------------------------------------

def _summarize(past: _Past) -> RehearsalSummary:
    """리허설 한 번의 요약 — 채점 기준을 믿을 수 있는 턴만 센다."""
    best: dict[str, str] = {}
    scores: list[int] = []
    give_ups = 0
    for t in past.trusted:
        if t.gave_up:
            give_ups += 1
            continue
        best[t.question_id] = _better(best.get(t.question_id, ""), t.verdict)
        scores.append(t.score)
    s = past.session
    return RehearsalSummary(
        session_id=str(s.get("session_id", "") or ""), at=past.at, title=str(s.get("title", "") or ""),
        questions=len({t.question_id for t in past.trusted}),
        good=sum(1 for v in best.values() if v == "good"),
        partial=sum(1 for v in best.values() if v == "partial"),
        wrong=sum(1 for v in best.values() if v == "wrong"),
        give_ups=give_ups,
        score_mean=round(sum(scores) / len(scores), 1) if scores else 0.0,
    )


def _add_turn(cm: ConceptMemory, t: _Turn, points: list[str], fallback_at: float) -> None:
    cm.label = t.label or cm.label
    if t.node_id and t.node_id not in cm.node_ids:
        cm.node_ids.append(t.node_id)
    cm.attempts += 1
    cm.last_at = max(cm.last_at, t.at or fallback_at)
    if t.gave_up:
        cm.give_ups += 1
        return
    cm.verdicts[t.verdict] = cm.verdicts.get(t.verdict, 0) + 1
    cm.last_verdict = t.verdict
    cm.last_score = t.score
    cm.best_verdict = _better(cm.best_verdict, t.verdict)
    cm.passes += 1 if t.passed else 0
    if t.close_reason:
        cm.closes[t.close_reason] = cm.closes.get(t.close_reason, 0) + 1
    for m in points:
        if m in cm.missing_points:
            cm.missing_points.remove(m)
        cm.missing_points.insert(0, m)
    del cm.missing_points[MEMORY_MISSING_MAX:]


def _concepts_of(group: list[_Past], deck: Deck | None) -> list[ConceptMemory]:
    """한 발표 묶음의 리허설들 → 개념 기억 (이름 열쇠마다). 오래된 리허설부터 쌓아야 last_* 가 정말 마지막 것이 된다."""
    deck_keys = sorted({k for p in group for k in p.keys})[:MEMORY_DECK_KEYS_MAX]
    concepts: dict[str, ConceptMemory] = {}
    for past in sorted(group, key=lambda p: p.at):
        asked_here: set[str] = set()
        hints_here: dict[str, int] = {}
        for t in past.trusted:
            key = memory_key(t.label)
            if not key:
                continue
            cm = concepts.get(key)
            if cm is None:
                cm = concepts[key] = ConceptMemory(key=key, label=t.label, deck_keys=list(deck_keys))
            if key not in asked_here:
                asked_here.add(key)
                cm.asked += 1
            hints_here[key] = max(hints_here.get(key, 0), t.hints)
            cm.hints_max = max(cm.hints_max, hints_here[key])
            _add_turn(cm, t, _kept_points(t, deck), past.at)
    return list(concepts.values())


def _as_graph(graph) -> ConceptGraph | None:
    return ConceptGraph.from_dict(graph) if isinstance(graph, dict) else graph


def _as_slidedoc(slidedoc) -> SlideDoc | None:
    return SlideDoc.from_dict(slidedoc) if isinstance(slidedoc, dict) else slidedoc


def _as_deck(slidedoc: SlideDoc | None) -> Deck | None:
    if slidedoc is None:
        return None
    deck = deck_from_slidedoc(slidedoc)
    return None if deck.empty else deck


def _deck_text(slidedoc: SlideDoc | None) -> str:
    """이번 자료 본문을 인용 대조용으로 접은 것 (공백 뺀 NFKC 소문자)."""
    return _fold_quote(" ".join(s.raw_text or "" for s in slidedoc.slides)) if slidedoc is not None else ""


def _fits_current(group: list[_Past], graph: ConceptGraph, deck_text: str, deck: Deck | None) -> bool:
    """
    이 발표 묶음이 이번 발표인가 — ① 지난 질문의 근거 인용(자료 줄 그대로)이 이번 자료 본문에 있다, 또는
    ② 이번 그래프에 이어지는 개념이 있다 (MemoryDoc.by_node 의 지문 대조 — 다른 이름의 절반 이상·둘 이상).
    ①은 한 개념만 물은 리허설도 알아본다 (지문에 다른 이름이 없어 ②로는 못 잇는다).
    """
    if deck_text and any(q in deck_text for p in group for q in p.quotes):
        return True
    return bool(MemoryDoc(concepts=_concepts_of(group, deck)).by_node(graph))


def build_memory(rehearsals: list[dict], *, file_name: str = "", learner_key: str = "",
                 graph: ConceptGraph | dict | None = None, slidedoc: SlideDoc | dict | None = None) -> MemoryDoc:
    """
    지난 리허설들 → MemoryDoc. 결정적 — 같은 기록이면 같은 기억.

    rehearsals 의 항목: {"session_id", "at", "title", "turns": [qa_turns 한 줄…]}. 최신이 먼저가 아니어도 된다 —
    여기서 at 으로 정렬해 최신 MEMORY_SESSIONS_MAX 개만 쓴다. turns 가 빈 리허설(질문만 받고 답 안 함)은 요약에는
    남기되 개념 기억에는 아무것도 더하지 않는다.

    - 개념 기억은 **서버가 만든 질문으로 채점한 턴**(question_source)만 센다. 옛 기록·본문 질문 턴은 발표 지문에만 쓴다.
    - 지난 리허설을 발표별로 묶어 (발표, 이름)마다 기억 하나. 기억마다 그 발표의 지문(deck_keys)을 싣는다.
    - graph(이번 발표)를 주면 이번 발표로 알아본 묶음(근거 인용이 이번 자료에 있거나 이번 그래프에 이어짐)만 남겨 하나로 합치고,
      다른 발표의 리허설은 요약까지 뺀다 → scoped=True (이름만으로 찾아도 안전하다).
    - slidedoc(이번 자료 본문)을 주면 빠진 점을 이번 자료와 다시 대조한다. 안 주면 자료와 대조한 판정의 결손만 남긴다.
    """
    ordered = sorted((r for r in rehearsals if isinstance(r, dict)), key=lambda r: -float(r.get("at", 0.0) or 0.0))
    pasts = [_read_past(r) for r in ordered[:MEMORY_SESSIONS_MAX]]
    doc = _as_slidedoc(slidedoc)
    deck = _as_deck(doc)
    graph = _as_graph(graph)
    scoped = graph is not None and bool(graph.nodes)
    groups = _presentations(pasts)
    # 턴 없는 리허설은 어느 발표인지 알 수 없다 — 이번 발표만 남길 때(graph)는 뺀다
    kept: list[_Past] = [] if scoped else [p for p in pasts if not p.turns]
    other_decks = 0
    if scoped:
        # 이번 발표로 알아본 묶음은 하나로 합쳐 개념마다 기억 하나로 (5분·10분 트랙이 서로 다른 개념을 물어도)
        text = _deck_text(doc)
        fitting = [g for g in groups if _fits_current(g, graph, text, deck)]
        other_decks = sum(len(g) for g in groups if g not in fitting)
        groups = [[p for g in fitting for p in g]] if fitting else []
    concepts: list[ConceptMemory] = [c for g in groups for c in _concepts_of(g, deck)]
    kept += [p for g in groups for p in g]
    kept.sort(key=lambda p: -p.at)
    ordered_concepts = sorted(concepts, key=lambda c: (0 if c.stalled else 1, -c.last_at, c.key, c.deck_keys))
    return MemoryDoc(learner_key=learner_key, file_name=file_name, sessions=[_summarize(p) for p in kept],
                     concepts=ordered_concepts, note=_note(pasts, other_decks), scoped=scoped)


def _note(pasts: list[_Past], other_decks: int) -> str:
    if not pasts:
        return "지난 리허설 없음"
    bits = []
    untrusted = sum(1 for p in pasts for t in p.turns if not t.trusted)
    if untrusted:
        bits.append(f"채점 기준을 확인할 수 없는 기록 {untrusted}턴(옛 기록·화면 질문)은 기억에 넣지 않았어요")
    if other_decks:
        bits.append(f"다른 발표의 리허설 {other_decks}번은 잇지 않았어요")
    return " · ".join(bits)


# ---------------------------------------------------------------------------
# 이번 그래프에 잇기 — 로직은 계약(MemoryDoc.by_node)에 있다. F-08·F-09 가 f25 를 import 하지 않고도 쓰게.
# ---------------------------------------------------------------------------

def link_memory(memory: MemoryDoc | dict | None, graph: ConceptGraph | dict | None) -> dict[str, ConceptMemory]:
    """MemoryDoc + 이번 ConceptGraph → {node_id: ConceptMemory}. memory 나 graph 가 없으면 빈 dict."""
    if memory is None or graph is None:
        return {}
    if isinstance(memory, dict):
        memory = MemoryDoc.from_dict(memory)
    if isinstance(graph, dict):
        graph = ConceptGraph.from_dict(graph)
    return memory.by_node(graph)


def memory_line(cm: ConceptMemory) -> str:
    return cm.prompt_line
