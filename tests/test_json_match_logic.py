"""
`_json_text`(LLM JSON 복구)·`_match`(label 토큰 대조) 순수 로직 감사 테스트입니다.

두 유틸은 LLM 을 부르는 모든 모듈(F-06~F-20)이 지나가는 길목이라, 여기서 조용히
틀리면 "LLM 이 불안정하다"로 보입니다. 한국어 LLM(A.X·Solar)이 실제로 뱉는 모양을
전부 넣고, (1) 정상 JSON 은 그대로 (2) 복구 가능한 건 의도한 객체 (3) 복구 불가는
문서화된 예외(ValueError) — 엉뚱한 객체를 조용히 돌려주지 않음 — 를 확인합니다.
잘못된 동작은 `xfail(strict=True, reason="BUG: …")` 로 스펙대로 적어 둡니다.
"""

from __future__ import annotations

import json
import logging

import pytest

from chuckchuck._json_text import extract_json_object, repair_json_text
from chuckchuck._match import (
    MIN_MATCH_LEN,
    contains_tokens,
    count_occurrences,
    first_match_index,
    label_tokens,
    norm_tokens,
)

BUG = pytest.mark.xfail  # 아래 각 케이스에 strict=True 로 붙인다


# ---------------------------------------------------------------------------
# _json_text — 정상 JSON 은 손대지 않는다
# ---------------------------------------------------------------------------

VALID = [
    {"questions": []},
    {"a": [[1, 2], [3, [4]]], "b": {"c": {"d": None}}},
    {"verdict": "aligned", "evidence": "그는 \"안녕\" 이라고, 했다 [3]"},
    {"한글": "값, 쉼표 ] 괄호 } 중괄호"},
]


@pytest.mark.parametrize("obj", VALID, ids=["empty_questions", "nested", "quotes", "brackets"])
def test_valid_json_roundtrips_unchanged(obj):
    raw = json.dumps(obj, ensure_ascii=False)
    assert extract_json_object(raw) == obj
    assert repair_json_text(raw) == raw


# ---------------------------------------------------------------------------
# _json_text — 복구 가능한 모양은 의도한 객체가 나와야 한다
# ---------------------------------------------------------------------------

REPAIRABLE = {
    "fence_json": ('```json\n{"a": 1}\n```', {"a": 1}),
    "fence_nolang": ('```\n{"a": 1}\n```', {"a": 1}),
    "fence_upper": ('```JSON\n{"a": 1}\n```', {"a": 1}),
    "prose_then_fence": ('다음은 결과입니다:\n```json\n{"a": 1}\n```', {"a": 1}),
    "fence_then_commentary": ('```json\n{"a": 1}\n```\n이상입니다.', {"a": 1}),
    "trailing_commentary": ('{"a": 1}\n이상으로 답변을 마칩니다.', {"a": 1}),
    "trailing_commas": ('{"a": [1, 2,], "b": {"c": 1,},}', {"a": [1, 2], "b": {"c": 1}}),
    "bom": ('﻿{"a": 1}', {"a": 1}),
    "bom_and_fence": ('﻿```json\n{"a": 1}\n```', {"a": 1}),
    "trunc_mid_array": (
        '{"questions": [{"question": "A"}, {"question": "B',
        {"questions": [{"question": "A"}]},
    ),
    "trunc_after_comma": ('{"questions": [{"question": "A"},', {"questions": [{"question": "A"}]}),
    "trunc_top_key": ('{"items": [{"a": 1}, {"b": 2}], "summary": "잘린', {"items": [{"a": 1}, {"b": 2}]}),
    "unbalanced_bracket_in_string_fenced": (
        '```json\n{"evidence": "슬라이드 [3 에서 말함"}\n```',
        {"evidence": "슬라이드 [3 에서 말함"},
    ),
}


@pytest.mark.parametrize("raw,expected", list(REPAIRABLE.values()), ids=list(REPAIRABLE))
def test_repairable_shapes_yield_intended_object(raw, expected):
    assert extract_json_object(raw) == expected


def test_truncation_keeps_only_complete_items_never_partial_garbage():
    """잘린 배열 복구는 완전한 항목만 남긴다 — 반쪽 문자열이 항목으로 섞이면 안 된다."""
    raw = '{"questions": [{"question": "첫째"}, {"question": "둘째 질문이 여기서 잘'
    out = extract_json_object(raw)
    assert out == {"questions": [{"question": "첫째"}]}


# ---------------------------------------------------------------------------
# _json_text — 복구 불가는 ValueError. 엉뚱한 객체를 조용히 주지 않는다
# ---------------------------------------------------------------------------

UNREPAIRABLE = {
    "empty": "",
    "whitespace": "   \n ",
    "non_json_korean": "죄송합니다, 답변할 수 없습니다.",
    "single_quotes": "{'a': 1}",
    "top_level_array": '[{"a": 1}, {"b": 2}]',
    "top_level_number": "42",
    "two_objects": '{"a": 1}\n{"b": 2}',
    "trunc_mid_string_no_complete_item": '{"questions": [{"question": "왜 집중',
    "unescaped_inner_quote": '{"a": "그는 "안녕" 이라고"}',
    "prose_with_braces_before_json": '결과 {요약}: {"a": 1}',
}


@pytest.mark.parametrize("raw", list(UNREPAIRABLE.values()), ids=list(UNREPAIRABLE))
def test_unrepairable_raises_value_error(raw):
    with pytest.raises(ValueError):
        extract_json_object(raw)


@BUG(strict=True, reason="BUG(low): 원소 1개짜리 최상위 배열은 바깥 {...} 정규식이 첫 원소를 "
     "조용히 꺼내 준다. 원소 2개면 ValueError — 같은 모양이 원소 수에 따라 다르게 처리된다. "
     "최상위가 배열이면 일관되게 ValueError('객체가 아닙니다') 여야 한다")
def test_single_element_top_level_array_is_not_silently_unwrapped():
    with pytest.raises(ValueError, match="객체가 아닙니다"):
        extract_json_object('[{"questions": []}]')


def test_failure_message_is_bounded_and_full_text_goes_to_log(caplog):
    """예외 문구는 화면까지 흘러가므로 200자 미리보기만, 원문은 서버 로그에 남는다."""
    raw = ("잘못된 응답 " * 200).strip()
    with caplog.at_level(logging.WARNING, logger="chuckchuck.json"):
        with pytest.raises(ValueError) as ei:
            extract_json_object(raw)
    assert len(str(ei.value)) < 400
    assert raw not in str(ei.value)
    assert any(raw in rec.getMessage() for rec in caplog.records)


def test_repair_never_raises_on_garbage():
    """repair_json_text 는 '최선의 결과'를 줄 뿐 예외를 던지지 않는다 (문서화된 계약)."""
    for raw in ("", None, "}}}", "[[[", "```", "{", "﻿"):
        assert isinstance(repair_json_text(raw), str)


# ---------------------------------------------------------------------------
# _json_text — 스펙과 어긋나는 구멍 (strict xfail)
# ---------------------------------------------------------------------------

# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_unescaped_newline_inside_string_is_recovered():
    raw = '{"verdict": "correct", "evidence": "첫 줄\n둘째 줄"}'
    assert extract_json_object(raw) == {"verdict": "correct", "evidence": "첫 줄\n둘째 줄"}


# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_tab_inside_string_is_recovered():
    assert extract_json_object('{"a": "x\ty"}') == {"a": "x\ty"}


# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_brace_inside_string_with_fence_is_recovered():
    raw = '```json\n{"evidence": "수식 {x 에서"}\n```'
    assert extract_json_object(raw) == {"evidence": "수식 {x 에서"}


# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_trailing_comma_regex_must_not_edit_string_contents():
    raw = '```json\n{"a": ["x, ]"],}\n```'
    assert extract_json_object(raw) == {"a": ["x, ]"]}


# ---------------------------------------------------------------------------
# _match — 토큰화
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,tokens", [
    ("AI 기반추천", ["ai", "기반추천"]),
    ("AI기반", ["ai", "기반"]),
    ("  GPT-4  ", ["gpt", "4"]),
    ("피보팅(근거)", ["피보팅", "근거"]),
    ("", []),
    (None, []),
    ("!!!", []),
])
def test_norm_tokens(value, tokens):
    assert norm_tokens(value) == tokens


@pytest.mark.parametrize("label,expected", [
    ("A", []),                 # 한 글자 영문: 우연히 다 걸리므로 버린다
    ("가", []),                 # 한 글자 한글
    ("AI", ["ai"]),            # 경계: 정확히 MIN_MATCH_LEN
    ("집중", ["집중"]),
    ("a b", ["a", "b"]),       # 합이 2 → 유지 (경계 규칙 그대로)
    ("  ", []),
])
def test_label_tokens_min_length_boundary(label, expected):
    assert MIN_MATCH_LEN == 2
    assert label_tokens(label) == expected


# ---------------------------------------------------------------------------
# _match — 대조 규칙: 영문·숫자 정확 일치, 한글은 합성어 포함
# ---------------------------------------------------------------------------

def _t(s: str) -> list[str]:
    return norm_tokens(s)


@pytest.mark.parametrize("text,label,hit", [
    ("오늘은 집중력 이야기", "집중력", True),
    ("오늘은 집중력이 떨어진다", "집중력", True),        # 조사 붙음
    ("집중력을 높이는 법", "집중력", True),
    ("장시간 앉아 있으면", "시간", True),                # 합성어 포함(설계상 허용)
    ("Ai 기반 추천", "AI 기반", True),                    # 대소문자
    ("AI   기반\n추천", "AI 기반", True),                 # 공백·줄바꿈
    ("detail 을 보자", "ai", False),                      # 영문은 부분 일치 금지
    ("2024년 계획", "202", False),                         # 숫자도 정확 일치
    ("기반 AI 추천", "AI 기반", False),                    # 순서가 다르면 연속 부분열이 아니다
    ("집중 이야기", "집중력", False),                      # 한글 포함은 label⊂text 한 방향
    ("집중력 저하", "집중력의 저하", False),               # label 쪽 조사는 안 벗긴다 (현재 규칙)
])
def test_contains_tokens_rules(text, label, hit):
    assert contains_tokens(_t(text), label_tokens(label)) is hit


def test_contains_tokens_empty_and_too_long():
    assert contains_tokens([], ["a"]) is False
    assert contains_tokens(["a"], []) is False
    assert contains_tokens(["a"], ["a", "b"]) is False
    assert contains_tokens([], []) is False


def test_first_match_index_positions_and_none():
    outer = _t("서론 다음 집중력 저하 그리고 집중력")
    assert first_match_index(outer, ["집중력", "저하"]) == 2
    assert first_match_index(outer, ["없는말"]) is None
    assert first_match_index(outer, []) is None
    assert first_match_index(["a"], ["a", "b"]) is None


def test_count_occurrences_non_overlapping():
    outer = _t("집중력 집중력이 그리고 집중력 저하")
    assert count_occurrences("집중력", outer) == 3
    assert count_occurrences("집중력 저하", outer) == 1
    assert count_occurrences("A", outer) == 0          # 짧은 label → 0
    assert count_occurrences("집중력", []) == 0
    assert count_occurrences("집중력 저하 심화 원인", _t("집중력 저하")) == 0


def test_count_occurrences_does_not_double_count_repeated_tokens():
    """'ab ab ab' 에서 'ab ab' 는 겹침 없이 1번이다."""
    outer = ["ab", "ab", "ab"]
    assert count_occurrences("ab ab", outer) == 1
