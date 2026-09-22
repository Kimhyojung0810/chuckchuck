"""
[F-25] 리허설 기억 — 같은 사람이 같은 발표를 다시 연습할 때, 지난 답변 과정을 되짚어 다음 Q&A 를 더 낫게 만드는 모듈입니다.
지난 세션들의 qa_turns 기록(+ConceptGraph) → MemoryDoc.  MemoryDoc + 이번 ConceptGraph → {node_id: ConceptMemory}.

    from chuckchuck.f25_memory import build_memory, link_memory
    memory = build_memory(rehearsals, file_name="deck.pdf", learner_key="learner:ab12")   # 세션에 한 번
    by_node = link_memory(memory, graph)                                                    # 이번 그래프의 노드에 잇기
    triage = triage_questions(graph, ..., memory=memory)      # 못 넘긴 개념이 먼저
    doc = build_questions(graph, triage, ..., memory=memory)  # "지난번엔 여기서 반쯤 왔어요" 를 알고 묻는다
    judgement = judge_answer(question, answer, ..., memory=memory)   # 지난번 빠진 점이 이번엔 나왔는지 본다

**전부 기록에서 센다.** LLM 이 채우는 필드는 없다 — 기억은 사실이어야 하고, "지난번에 이랬죠" 를 지어내면 사람을 억울하게 한다.

무엇을 기억하나 (개념 단위, 이름으로 잇는다 — 노드 id 는 세션마다 다르다):
- 몇 번 물었고 몇 번 답했고 몇 번 포기했나, 판정 분포, 마지막·최고 판정, 마지막 점수
- 최근 판정이 짚은 「빠진 점」 (최신 3개) — 다음 질문이 그 빈틈을 겨냥하고, 판정이 「이번엔 짚었다」 를 알아본다
- 힌트를 몇 개까지 봤나 — 코칭 시작 단계를 정한다

무엇을 기억하지 않나: 답변 원문(프롬프트에 싣지 않는다 — 지난 답을 이번 답으로 착각하게 한다), 오디오, 동의 없는 세션.
같은 파일 이름만으로는 잇지 않는다 (호출자 규칙 — 같은 이름의 남의 자료가 붙는다). 오래된 리허설은 MEMORY_SESSIONS_MAX 까지만.
"""

from __future__ import annotations

from .contracts import (
    MEMORY_MISSING_MAX,
    MEMORY_SESSIONS_MAX,
    MEMORY_VERDICT_ORDER,
    ConceptGraph,
    ConceptMemory,
    MemoryDoc,
    RehearsalSummary,
    memory_key,
)

def _verdict_rank(v: str) -> int:
    return MEMORY_VERDICT_ORDER.index(v) if v in MEMORY_VERDICT_ORDER else len(MEMORY_VERDICT_ORDER)


def _better(a: str, b: str) -> str:
    """둘 중 좋은 verdict. 빈 것은 진다."""
    if not a:
        return b
    if not b:
        return a
    return a if _verdict_rank(a) <= _verdict_rank(b) else b


def _turn_fields(ev: dict) -> tuple[str, str, str, str, int, bool, list[str], int, float]:
    """qa_turns 한 줄 → (question_id, node_id, label, verdict, score, gave_up, missing_points, hints, at)."""
    q = ev.get("question") if isinstance(ev.get("question"), dict) else {}
    j = ev.get("judgement") if isinstance(ev.get("judgement"), dict) else {}
    verdict = str(j.get("verdict", "") or "unknown")
    gave_up = bool(ev.get("give_up")) or (verdict == "unknown" and bool(j.get("coach_stage")))
    missing = [str(m).strip() for m in (j.get("missing_points") or []) if str(m).strip()]
    hints = len([h for h in (ev.get("hints_shown") or []) if str(h).strip()])
    return (
        str(ev.get("question_id") or q.get("id") or ""),
        str(q.get("node_id", "") or ""),
        str(q.get("label", "") or ""),
        verdict, int(j.get("score", 0) or 0), gave_up, missing, hints, float(ev.get("at", 0.0) or 0.0),
    )


def _summarize(session: dict, turns: list[dict]) -> RehearsalSummary:
    best: dict[str, str] = {}
    scores: list[int] = []
    give_ups = 0
    for ev in turns:
        qid, _, _, verdict, score, gave_up, _, _, _ = _turn_fields(ev)
        if gave_up:
            give_ups += 1
            continue
        best[qid] = _better(best.get(qid, ""), verdict)
        scores.append(score)
    return RehearsalSummary(
        session_id=str(session.get("session_id", "") or ""), at=float(session.get("at", 0.0) or 0.0),
        title=str(session.get("title", "") or ""),
        questions=len({_turn_fields(ev)[0] for ev in turns}),
        good=sum(1 for v in best.values() if v == "good"),
        partial=sum(1 for v in best.values() if v == "partial"),
        wrong=sum(1 for v in best.values() if v == "wrong"),
        give_ups=give_ups,
        score_mean=round(sum(scores) / len(scores), 1) if scores else 0.0,
    )


def build_memory(rehearsals: list[dict], *, file_name: str = "", learner_key: str = "") -> MemoryDoc:
    """
    지난 리허설들 → MemoryDoc. 결정적 — 같은 기록이면 같은 기억.

    rehearsals 의 항목: {"session_id", "at", "title", "turns": [qa_turns 한 줄…]}. 최신이 먼저가 아니어도 된다 —
    여기서 at 으로 정렬해 최신 MEMORY_SESSIONS_MAX 개만 쓴다. turns 가 빈 리허설(질문만 받고 답 안 함)은 요약에는
    남기되 개념 기억에는 아무것도 더하지 않는다.
    """
    ordered = sorted((r for r in rehearsals if isinstance(r, dict)), key=lambda r: -float(r.get("at", 0.0) or 0.0))
    ordered = ordered[:MEMORY_SESSIONS_MAX]
    concepts: dict[str, ConceptMemory] = {}
    summaries: list[RehearsalSummary] = []
    # 오래된 리허설부터 누적해야 last_* 가 정말 마지막 것이 된다.
    for session in reversed(ordered):
        turns = [t for t in (session.get("turns") or []) if isinstance(t, dict)]
        summaries.append(_summarize(session, turns))
        asked_here: set[str] = set()
        hints_here: dict[str, int] = {}
        for ev in sorted(turns, key=lambda e: float(e.get("at", 0.0) or 0.0)):
            _, node_id, label, verdict, score, gave_up, missing, hints, at = _turn_fields(ev)
            key = memory_key(label)
            if not key:
                continue
            cm = concepts.get(key)
            if cm is None:
                cm = concepts[key] = ConceptMemory(key=key, label=label)
            cm.label = label or cm.label
            if node_id and node_id not in cm.node_ids:
                cm.node_ids.append(node_id)
            if key not in asked_here:
                asked_here.add(key)
                cm.asked += 1
            cm.attempts += 1
            hints_here[key] = max(hints_here.get(key, 0), hints)
            cm.hints_max = max(cm.hints_max, hints_here[key])
            cm.last_at = max(cm.last_at, at or float(session.get("at", 0.0) or 0.0))
            if gave_up:
                cm.give_ups += 1
                continue
            cm.verdicts[verdict] = cm.verdicts.get(verdict, 0) + 1
            cm.last_verdict = verdict
            cm.last_score = score
            cm.best_verdict = _better(cm.best_verdict, verdict)
            for m in missing:
                if m in cm.missing_points:
                    cm.missing_points.remove(m)
                cm.missing_points.insert(0, m)
            del cm.missing_points[MEMORY_MISSING_MAX:]
    summaries.reverse()   # 최신이 먼저
    ordered_concepts = sorted(concepts.values(), key=lambda c: (0 if c.stalled else 1, -c.last_at, c.key))
    note = "" if ordered else "지난 리허설 없음"
    return MemoryDoc(learner_key=learner_key, file_name=file_name, sessions=summaries, concepts=ordered_concepts, note=note)


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
