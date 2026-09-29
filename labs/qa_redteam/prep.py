"""덱 묶음을 얼린 벤치 산출물(wt-qa-final)에서 가져와 HEAD 코드로 10분 트랙 질문만 다시 만든다 (덱마다 LLM 1콜)."""
from __future__ import annotations
import sys
from common import FROZEN, OUT, Counted, rj, wj

CTX = {"sleep": {"situation": "school_project", "duration_min": 5},
       "yield_gap": {"situation": "competition", "duration_min": 10},
       "policy_jeonse": None}

for deck in sys.argv[1:]:
    src = FROZEN / deck
    d = OUT / "decks" / deck
    sd, graph, claims, triage = (rj(src / f) for f in ("slide_doc.json", "graph.json", "claims.json", "triage.json"))
    ctx = CTX.get(deck) or rj(FROZEN.parent / "corpus" / deck / "truth.json").get("context") if False else (CTX.get(deck) or {"situation": "school_project", "duration_min": 5})
    for f, v in (("slide_doc.json", sd), ("graph.json", graph), ("claims.json", claims), ("triage.json", triage)):
        wj(d / f, v)
    wj(d / "context.json", ctx)
    from chuckchuck import build_questions
    doc = build_questions(graph, triage, track="10", slidedoc=sd, context=ctx, claims=claims, llm=Counted(f"q:{deck}"))
    wj(d / "questions_t10.json", doc.to_dict())
    print(deck, len(doc.questions))
    for i, q in enumerate(doc.questions, 1):
        b = q.basis.to_dict() if q.basis else {}
        print(f" [{i}] {q.source} trap={bool(q.trap_premise)} probe={(b.get('probe') or {}).get('kind','')}\n   Q {q.question}\n   G {q.answer_gist}\n   E {q.evidence_slide_no} «{q.evidence_quote}»")
