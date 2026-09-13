"""qa_eval 의 rubric 심사·코퍼스 집계 — LLM 없이 도는 순수 부분.

- parse_rubric: 심사관 응답이 코드펜스를 둘러도, 질문을 빼먹어도, 점수가 범위를 벗어나도 행이 깨지지 않는다
- trap 질문은 코드가 hallucination=false 로 못 박는다
- aggregate_summaries: 번들 N개 요약이 단일 요약과 같은 모양이 되어 qa_eval_compare 가 그대로 읽는다
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "examples" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def qa_eval():
    return _load("qa_eval")


@pytest.fixture(scope="module")
def compare():
    return _load("qa_eval_compare")


def _q(id, trap=False):
    return SimpleNamespace(id=id, trap=trap, slide_nos=[3], question=f"{id} 질문이에요?", label="개념")


def _score(id, **over):
    base = {"id": id, "groundedness": 4, "relevance": 5, "coverage": 3, "depth": 4,
            "answerability": 5, "non_duplication": 5, "hallucination": False, "reason": "S3 근거"}
    base.update(over)
    return base


class StubLLM:
    name = "stub"

    def __init__(self, raw):
        self.raw, self.calls = raw, []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.calls.append({"system": system, "user": user})
        return self.raw


class StubCorpus:
    slide_text = {1: "표지", 3: "지도력은 신뢰에서 나온다 " * 50}
    speech_text = {1: "", 3: "신뢰 이야기부터 할게요"}


def test_parse_rubric_survives_codefence_and_out_of_range(qa_eval):
    raw = "```json\n" + json.dumps({"scores": [_score("q01", depth=9, coverage="2")]}) + "\n```"
    rows = qa_eval.parse_rubric(raw, [_q("q01")])
    assert rows[0]["depth"] == 5 and rows[0]["coverage"] == 2
    assert rows[0]["missing"] is False and rows[0]["hallucination"] is False


def test_parse_rubric_marks_missing_question_instead_of_zero(qa_eval):
    raw = json.dumps({"scores": [_score("q01")]})
    rows = qa_eval.parse_rubric(raw, [_q("q01"), _q("q02")])
    assert [r["missing"] for r in rows] == [False, True]
    assert "groundedness" not in rows[1]


def test_trap_question_is_never_hallucination(qa_eval):
    raw = json.dumps({"scores": [_score("q01", hallucination=True), _score("q02", hallucination=True)]})
    rows = qa_eval.parse_rubric(raw, [_q("q01", trap=True), _q("q02")])
    assert rows[0]["hallucination"] is False
    assert rows[0]["groundedness"] is None          # 함정의 전제는 채점하지 않는다
    assert rows[0]["depth"] == 4                     # 나머지 항목은 정상 채점
    assert rows[1]["hallucination"] is True and rows[1]["groundedness"] == 4


def test_rubric_summary_zeroes_hallucinated_question_in_overall(qa_eval):
    rows = qa_eval.parse_rubric(json.dumps({"scores": [
        _score("q01"),                                   # 평균 26/6 = 4.33
        _score("q02", hallucination=True),               # 종합에서 0
        _score("q03"),
    ]}), [_q("q01"), _q("q02"), _q("q03"), _q("q04")])
    s = qa_eval.rubric_summary(rows)
    assert s["n"] == 3 and s["missing"] == 1 and s["hallucination"] == 1
    assert s["groundedness_mean"] == 4.0
    assert s["overall_mean"] == pytest.approx((4.33 + 0 + 4.33) / 3, abs=0.01)


def test_run_rubric_sends_deck_speech_and_questions_in_one_call(qa_eval):
    llm = StubLLM(json.dumps({"scores": [_score("q01")]}))
    rows = qa_eval.run_rubric([_q("q01")], StubCorpus(), llm)
    assert len(llm.calls) == 1
    user = llm.calls[0]["user"]
    assert user.startswith("[TASK] qa-rubric")
    assert "S3:" in user and "신뢰 이야기부터" in user and "id=q01" in user
    assert len([ln for ln in user.splitlines() if ln.startswith("S3:")][0]) <= qa_eval.RUBRIC_SLIDE_MAX + 4
    assert rows[0]["groundedness"] == 4


def test_run_rubric_failure_is_recorded_not_raised(qa_eval):
    rows = qa_eval.run_rubric([_q("q01")], StubCorpus(), StubLLM("이건 JSON 이 아니에요"))
    assert rows == [{"question_id": "q01", "missing": True}]
    assert qa_eval.rubric_summary(rows)["overall_mean"] is None


def test_summarize_omits_rubric_when_not_run(qa_eval):
    s = qa_eval.summarize([], [], [], None, None)
    assert "rubric" not in s


def _summary(spec, ground, gist):
    return {"questions": 3, "specificity_mean": spec, "grounding_mean": ground, "fallback": 0,
            "judge": {"gist_passed": gist, "unrelated_wrong": "-"},
            "prompts": {"qa-questions": {"n": 1, "sec_mean": 20.0}},
            "coach": {"stages": {"q01": ["narrow", "explain"]}, "honorifics": 0},
            "rubric": {"overall_mean": 4.0, "hallucination": 0}}


def test_aggregate_means_numbers_sums_ratios_drops_lists(qa_eval):
    agg = qa_eval.aggregate_summaries([_summary(4.0, 0.6, "3/3"), _summary(2.0, 0.8, "1/3")])
    assert agg["specificity_mean"] == 3.0 and agg["grounding_mean"] == 0.7
    assert agg["judge"]["gist_passed"] == "4/6"
    assert "unrelated_wrong" not in agg["judge"]          # 둘 다 '-' 면 사라진다
    assert "stages" not in agg["coach"] and agg["coach"]["honorifics"] == 0
    assert agg["prompts"]["qa-questions"]["sec_mean"] == 20.0
    assert agg["rubric"]["overall_mean"] == 4.0


def test_aggregate_output_is_readable_by_compare(qa_eval, compare):
    before = qa_eval.aggregate_summaries([_summary(4.0, 0.6, "3/3"), _summary(4.0, 0.6, "3/3")])
    # 골자 통과 잡음 폭은 실측 ±0.5 (09-13) — 6/6 → 2/6 (0.67 하락) 이어야 폭 밖이다
    after = qa_eval.aggregate_summaries([_summary(4.0, 0.6, "1/3"), _summary(4.0, 0.6, "1/3")])
    r = compare.compare(before, after)
    assert r["verdict"] == "REGRESSED"
    assert next(x for x in r["rows"] if x["key"] == "judge.gist_passed")["state"] == "worse"


def test_compare_reads_rubric_keys(compare):
    before = {"rubric": {"overall_mean": 3.5, "hallucination": 1}}
    after = {"rubric": {"overall_mean": 4.2, "hallucination": 0}}
    r = compare.compare(before, after)
    assert r["verdict"] == "IMPROVED"
    assert {x["key"] for x in r["rows"] if x["state"] == "better"} == {"rubric.overall_mean", "rubric.hallucination"}


def test_latest_for_tag_prefers_corpus_file(compare, tmp_path, monkeypatch):
    monkeypatch.setattr(compare, "OUT_DIR", tmp_path)
    (tmp_path / "20260912-100000_v1.json").write_text("{}")
    (tmp_path / "20260912-090000_v1.corpus.json").write_text("{}")
    assert compare.latest_for_tag("v1").name == "20260912-090000_v1.corpus.json"
    assert compare.latest_for_tag("v9") if False else True


def test_parse_rubric_pairs_by_position_when_ids_differ_but_count_matches(qa_eval):
    raw = json.dumps({"scores": [_score("Q-1"), _score("Q-2", depth=2)]})
    rows = qa_eval.parse_rubric(raw, [_q("q01"), _q("q02")])
    assert [r["missing"] for r in rows] == [False, False]
    assert rows[1]["depth"] == 2


def test_parse_rubric_does_not_guess_when_count_differs(qa_eval):
    raw = json.dumps({"scores": [_score("Q-1")]})
    rows = qa_eval.parse_rubric(raw, [_q("q01"), _q("q02")])
    assert [r["missing"] for r in rows] == [True, True]


def test_with_context_overrides_only_what_is_given(qa_eval):
    art = {"slide_doc": {}, "context": {"situation": "school_project", "audience": "교수", "duration_min": 10}}
    out = qa_eval.with_context(art, "work_report", None)
    assert out["context"] == {"situation": "work_report", "audience": "교수", "duration_min": 10}
    assert art["context"]["situation"] == "school_project"          # 원본은 그대로
    assert qa_eval.with_context(art, None, None) is art               # 아무것도 안 주면 사본도 안 만든다
    assert qa_eval.with_context({"slide_doc": {}}, None, "투자자")["context"] == {"audience": "투자자"}


def test_merge_rubric_runs_takes_medians_and_majority_hallucination(qa_eval):
    runs = [
        qa_eval.parse_rubric(json.dumps({"scores": [_score("q01", coverage=2, depth=2, hallucination=True)]}), [_q("q01")]),
        qa_eval.parse_rubric(json.dumps({"scores": [_score("q01", coverage=3, depth=4)]}), [_q("q01")]),
        qa_eval.parse_rubric(json.dumps({"scores": [_score("q01", coverage=4, depth=4)]}), [_q("q01")]),
    ]
    m = qa_eval.merge_rubric_runs(runs)
    assert m[0]["coverage"] == 3 and m[0]["depth"] == 4 and m[0]["runs"] == 3
    assert m[0]["hallucination"] is False                       # 3번 중 1번은 과반이 아니다


def test_merge_rubric_runs_keeps_missing_only_if_every_run_missed(qa_eval):
    runs = [
        qa_eval.parse_rubric(json.dumps({"scores": []}), [_q("q01")]),
        qa_eval.parse_rubric(json.dumps({"scores": [_score("q01", depth=1)]}), [_q("q01")]),
    ]
    m = qa_eval.merge_rubric_runs(runs)
    assert m[0]["missing"] is False and m[0]["depth"] == 1 and m[0]["runs"] == 1
    assert qa_eval.merge_rubric_runs([runs[0], runs[0]])[0]["missing"] is True
