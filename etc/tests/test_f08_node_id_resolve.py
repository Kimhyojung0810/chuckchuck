"""F-08 가 모델의 흔한 형식 실수를 코드로 받는다 — node_id 에 라벨을 적거나, 참/거짓을 문자열로 (10-16 엑사원 실측)."""
from __future__ import annotations

import pipeline.f08_questions as f08


def test_label_written_as_node_id_is_mapped_back_to_the_one_target():
    label_of = {"n1": "4.7은 품질이 아니라 리뷰 수집 방식의 결과다", "n2": "가설 A"}
    raw = [{"node_id": "4.7은 품질이 아니라 리뷰 수집 방식의 결과다", "question": "q"},
           {"node_id": "가설a", "question": "q2"},            # 띄어쓰기·대소문자만 다르면 같은 이름
           {"node_id": "n2", "question": "q3"}]
    out = f08._resolve_node_ids(raw, label_of)
    assert [q["node_id"] for q in out] == ["n1", "n2", "n2"]
    assert raw[0]["node_id"].startswith("4.7")             # 원본은 건드리지 않는다


def test_ambiguous_or_unknown_label_is_left_alone():
    label_of = {"n1": "수면", "n2": "수면"}
    out = f08._resolve_node_ids([{"node_id": "수면"}, {"node_id": "모르는 것"}], label_of)
    assert [q["node_id"] for q in out] == ["수면", "모르는 것"]   # 대상 밖 id 는 어댑터가 버린다


def test_string_booleans_are_parsed_not_truthy():
    assert f08._as_bool("true") and f08._as_bool(True) and f08._as_bool("Yes")
    assert not f08._as_bool("false") and not f08._as_bool("") and not f08._as_bool(None) and not f08._as_bool(0)


class _OnceLabelLLM:
    name = "fake"

    def __init__(self, text):
        self.text, self.calls = text, 0

    def complete(self, **kw):
        self.calls += 1
        return self.text


def test_questions_with_retry_accepts_label_ids_without_a_second_call():
    mark = f08.TriageMark(node_id="n1", severity=2, trap=False, angle="", source="core_weight", rank=1, doc_weight=1.0)
    llm = _OnceLabelLLM('{"questions": [{"node_id": "핵심 주장", "question": "왜 그런가요?"}]}')
    raw = f08._questions_with_retry(llm, "p", [mark], label_of={"n1": "핵심 주장"})
    assert raw[0]["node_id"] == "n1" and llm.calls == 1


def test_fragment_question_goes_to_template_but_short_real_questions_stay():
    assert f08._fit_question("세 가지 가설 중 왜?") == ""
    assert f08._fit_question("왜 가설 A는 기각되었나요?") == "왜 가설 A는 기각되었나요?"
    assert f08._fit_question("혈당 지수는 어떻게 정의되나요?") == "혈당 지수는 어떻게 정의되나요?"
