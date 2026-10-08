"""질문 기록표 — 질문마다 대상 노드 · 선택 이유 · 사용자 상태 · 생성된 질문 · 걸린 근거 검사. score.py 가 태그마다 records.md 로 쓴다."""
from __future__ import annotations

from common import FOLLOW_UPS, keys_of, load_tag
from score import Deck, first_session, grounding

#: 기록표 「근거」 칸에 실패로 적는 검사 (g_node 는 노드 이름 칸이 대신 보여 준다)
SHOWN_CHECKS = ("g_num", "g_anchor", "g_target", "g_vocab", "g_quote")


def _question_rows(qs: list[dict], keys: dict, deck: Deck) -> list[str]:
    rows = ["| # | 대상 노드 | K | 선택 이유 (source·rank·why) | 질문 | 근거 |", "|---|---|---|---|---|---|"]
    for n, q in enumerate(qs, 1):
        basis = q.get("basis") or {}
        why = f"{q.get('source')}·r{basis.get('rank', '')} — {q.get('why', '')}"
        gr = grounding(q, deck)
        bad = [k for k in SHOWN_CHECKS if not gr[k]]
        rows.append(f"| {n} | {q['label']} | {','.join(sorted(keys_of(q['label'], keys)))} | {why} | "
                    f"{q['question']} | {'ok' if not bad else ' '.join(bad)} |")
    return rows


def _answer_lines(sc: str, rep: dict) -> list[str]:
    """B·C·D — 첫 질문에 한 답, 판정, 코치가 바로 이어 한 말."""
    j = rep[sc]["judgement"]
    nxt = rep[sc]["next"] or {}
    lines = [f"\n- 답: {rep[sc].get('answer', '(모르겠어요)')}",
             f"- 판정: {j['verdict']} {j['score']} · passed={j['passed']} · mastered={j['mastered']} · "
             f"stage={j.get('coach_stage') or '-'}",
             f"- 코치의 다음 말: {nxt.get('question') or nxt.get('followup') or '-'}"
             + (f" · 보기 {nxt.get('choices')}" if nxt.get("choices") else "")]
    if sc == "D":
        j2 = rep["D"]["judgement2"]
        lines.append(f"- 두 번째 모르겠어요: stage={j2.get('coach_stage')} · {j2.get('followup') or j2.get('explanation', '')[:120]}")
    return lines


def records_md(tag: str, keys: dict, deck: Deck) -> str:
    lines = [f"# {tag} — 질문 기록", ""]
    for i, rep in enumerate(load_tag(tag)):
        lines.append(f"## rep{i}")
        sets = [("A", rep["A"]["state"], first_session(rep))]
        sets += [(sc, rep[sc]["state"] + " → 다음 리허설", rep[sc]["session2"]["questions"]) for sc in FOLLOW_UPS]
        for sc, state, qs in sets:
            lines.append(f"### {sc} · {state}")
            lines += _question_rows(qs, keys, deck)
            if sc in ("B", "C", "D"):
                lines += _answer_lines(sc, rep)
            lines.append("")
    return "\n".join(lines)
