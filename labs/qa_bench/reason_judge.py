"""
근거 질문 판정 표본 (qa/reason, 2026-09-30) — 정답(truth.reason)이 있는 덱의 심은 근거 질문에 답 셋을 **실 LLM 판정**으로.

    .venv/bin/python labs/qa_bench/reason_judge.py            # 덱마다 3콜 (이유를 댄 답 · 배경만 되풀이한 답 · 골자 그대로)

기대: 이유를 댄 답·골자는 통과, 배경만 되풀이한 답은 통과 못 함(partial). 질문은 `reason_metrics.planted_row` 와 같은 방법으로
ScriptedLLM 을 거쳐 F-08 이 만든다 (근거 묶음에 이유 줄·배경 줄이 실린다). 답 문장은 정답 줄에서 코드가 만든다 — LLM 이 안 쓴다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))

from chuckchuck.config import load_dotenv  # noqa: E402

load_dotenv()

import reason_metrics as RM  # noqa: E402
import run as RN  # noqa: E402


def build_question(name: str, truth_reason: dict):
    from chuckchuck import build_questions
    from chuckchuck.contracts import ConceptGraph, QaTriage, TriageMark
    from chuckchuck.providers.llm_base import LLMProvider

    d = RN.OUT / name
    sd = RN.read_json(d / "slide_doc.json")
    g = ConceptGraph.from_dict(RN.read_json(d / "graph.json"))
    claims = RN.read_json(d / "claims.json")
    conc = truth_reason["conclusion"]
    target = max((n for n in g.nodes if truth_reason["slide"] in (n.slide_nos or [])),
                 key=lambda n: (len(RM._words(n.label) & RM._words(conc)), -n.depth, n.weight))
    mixed = f"{truth_reason['background_lines'][0]}이고, {truth_reason['reason_lines'][0]}이에요."

    class Scripted(LLMProvider):
        name = "scripted"

        def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
            return json.dumps({"questions": [{"node_id": target.id, "question": truth_reason["question"],
                                              "answer_gist": mixed}]}, ensure_ascii=False)

    triage = QaTriage(file_name=sd.get("file_name", ""), marks=[
        TriageMark(node_id=target.id, rank=1, source="core_weight", severity=1, doc_weight=1.0)])
    q = build_questions(g, triage, track="1", slidedoc=sd, claims=claims, llm=Scripted()).questions[0]
    return q, g, sd


def main() -> int:
    from chuckchuck import judge_answer
    from chuckchuck.contracts import qa_passed

    rows = []
    for name, truth in RM.load_truths().items():
        tr = (truth or {}).get("reason")
        if not tr or not (RN.OUT / name / "graph.json").exists():
            continue
        q, g, sd = build_question(name, tr)
        answers = {
            "reason": f"{tr['strongest'].rstrip('.')}고, {tr['reason_lines'][0]}이라서 그렇게 봤어요.",
            "background": f"{tr['background_lines'][0]}이고 {tr['background_lines'][1]}이라서 그렇게 결론 냈어요.",
            "gist": q.answer_gist,
        }
        for kind, text in answers.items():
            j = judge_answer(q, text, graph=g, slidedoc=sd, llm=RN.engine(name, f"reason_judge:{kind}"))
            ok = qa_passed(j.verdict, j.score) == (kind != "background")
            rows.append({"deck": name, "kind": kind, "answer": text, "verdict": j.verdict, "score": j.score,
                         "passed": qa_passed(j.verdict, j.score), "expected_pass": kind != "background", "ok": ok,
                         "react": j.react, "missing": j.missing_points[:2]})
            print(f"{name:12s} {kind:10s} → {j.verdict} {j.score} {'✓' if ok else '✗'} · {j.react[:60]}")
    RN.write_json(RN.OUT / "reason_judge.json", rows)
    print(f"맞음 {sum(r['ok'] for r in rows)}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
