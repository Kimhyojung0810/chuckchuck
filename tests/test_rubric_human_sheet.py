"""사람 채점표·일치율 도구 — 심사관 점수는 숨은 열에, 일치율은 사람 칸이 찬 행만."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("rhs", ROOT / "examples" / "rubric_human_sheet.py")
rhs = importlib.util.module_from_spec(spec); spec.loader.exec_module(rhs)


def _result(tmp_path):
    p = tmp_path / "20260912-000000_x.json"
    p.write_text(json.dumps({"context": {"situation": "work_report"},
        "questions": [{"id": "q01", "question": "왜요?", "gist": "골자"}, {"id": "q02", "question": "어떻게요?", "gist": ""}],
        "rubric": [{"question_id": "q01", "missing": False, "groundedness": 4, "relevance": 5, "coverage": 3, "depth": 4,
                    "answerability": 5, "non_duplication": 5, "hallucination": False},
                   {"question_id": "q02", "missing": True}]}, ensure_ascii=False), encoding="utf-8")
    return p


def test_sheet_has_blank_human_columns_and_hidden_llm_scores(tmp_path):
    rows = rhs.build_rows([_result(tmp_path)])
    assert [r["question_id"] for r in rows] == ["q01", "q02"]
    assert rows[0]["human_depth"] == "" and rows[0]["llm_depth"] == 4 and rows[0]["llm_hallucination"] == 0
    assert rows[1]["llm_depth"] == ""                      # 심사관이 누락한 질문은 빈칸
    out = tmp_path / "s.csv"; rhs.write_sheet(rows, out)
    back = rhs.read_sheet(out)
    assert back[0]["situation"] == "work_report" and back[0]["llm_relevance"] == "5"


def test_agreement_counts_only_filled_rows():
    rows = [
        {"human_depth": "4", "llm_depth": "4", "human_coverage": "2", "llm_coverage": "4"},
        {"human_depth": "3", "llm_depth": "4", "human_coverage": "", "llm_coverage": "3"},
        {"human_depth": "", "llm_depth": "5", "human_coverage": "5", "llm_coverage": "5"},
    ]
    a = rhs.agreement(rows)
    assert a["depth"] == {"n": 2, "exact": 0.5, "within1": 1.0, "bias": -0.5}
    assert a["coverage"]["n"] == 2 and a["coverage"]["within1"] == 0.5
    assert a["relevance"] == {"n": 0}
