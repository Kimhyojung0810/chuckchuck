"""
F-19(종합 리포트 조립)·F-06(개념 추출) 의 LLM 을 뺀 순수 로직 감사 테스트입니다.

F-19: LLM 은 문장만 쓰고 숫자는 PaceDoc·HabitDoc·RubricScore 에서 그대로 옮긴다 — LLM 이
쓰레기를 줘도 숫자가 지어지거나 사라지면 안 된다. F-06: 배치 경계·클리핑·발화 보완·JSON 복구·
병합. 지배 규칙은 docs/PROMPT_DESIGN.md §1 원칙 1("자료에 없는 내용을 지어내지 마라").
잘못된 동작은 `xfail(strict=True, reason="BUG: …")` 로 스펙대로 적어 둔다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from chuckchuck._evidence import clean_slide_text
from chuckchuck.contracts import (
    ConceptError, Context, HabitDoc, PaceDoc, RubricClusterScore, RubricItemScore,
    RubricScore, Slide, SlideBlock, SlideDoc, SlideHabits, SlidePace, SlideSpeech, Transcript,
)
from chuckchuck.f06_concepts import (
    MAX_SLIDE_CHARS, _build_user_prompt, _call_batch, _clip, _extract_json, extract_concepts,
)
from chuckchuck.f19_report import _facts_block, _fallback_report, _parse_json, compose_report
from chuckchuck.providers.llm_base import LLMProvider

ROOT = Path(__file__).resolve().parents[1]
BUG = pytest.mark.xfail


class ScriptedLLM(LLMProvider):
    """정해 둔 문자열(또는 예외)만 돌려주는 가짜 LLM. test_voice_report 와 같은 패턴."""

    name = "scripted"

    def __init__(self, payload: str | Exception):
        self.payload = payload
        self.prompts: list[str] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False) -> str:
        self.prompts.append(user)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


# F-19 재료
def _pace() -> PaceDoc:
    return PaceDoc(
        target_sec=600.0, actual_sec=590.0, avg_chars_per_min=312.0,
        avg_syllable_per_sec=4.7, max_chars_per_min=421.0, max_slide_no=2,
        slides=[SlidePace(slide_no=n, title=t, importance=imp, actual_sec=a, recommended_sec=r,
                          chars_per_min=c, status=st, note=note)
                for n, t, imp, a, r, c, st, note in (
                    (1, "도입", "support", 50.0, 31.0, 300.0, "long", "n1"),
                    (2, "핵심 A", "core", 28.0, 88.0, 421.0, "short", "n2"),
                    (3, "핵심 B", "core", 90.0, 88.0, 310.0, "ok", ""))],
        tips=["2번은 핵심인데 권장 88초 중 28초만 썼어요."],
    )


def _habits() -> HabitDoc:
    return HabitDoc(
        by_slide=[SlideHabits(slide_no=1, repeat_cnt=2, filler_cnt=5, pause_cnt=1, note="h1"),
                  SlideHabits(slide_no=2), SlideHabits(slide_no=3)],
        repeat_cnt=2, filler_cnt=5, pause_cnt=1, provider="heuristic",
        tips=["1번: 간투어 5회 · 긴 휴지 1회"],
    )


def _rubric() -> RubricScore:
    return RubricScore(
        score=64, situation="lecture", situation_label="학회·수업 발표",
        clusters=[RubricClusterScore(key="c1", name="구조", average=70.4, status="scored"),
                  RubricClusterScore(key="c2", name="상호작용", average=0.0, status="omitted")],
        items=[RubricItemScore(no=n, name=nm, score=sc, evidence=f"e{n}") for n, nm, sc in
               ((1, "논리", 80), (2, "속도", 40), (3, "시선", 55), (4, "반복", 90))]
              + [RubricItemScore(no=5, name="질문", status="unmeasured")],
        unmeasured=[5],
    )


def _fixture():
    d = json.loads((ROOT / "fixtures/focus_voice_report.json").read_text(encoding="utf-8"))
    return (PaceDoc.from_dict(d["pace"]), HabitDoc.from_dict(d["habits"]),
            Context.from_dict(d["context"]), d["report"])


def _numbers(text: str) -> set[str]: return set(re.findall(r"\d+(?:\.\d+)?", text))


# F-19 — 사실 블록: 숫자는 원본 그대로, 재계산 없음
def test_facts_block_carries_every_source_number_verbatim():
    pace, habits, rubric = _pace(), _habits(), _rubric()
    block = _facts_block(pace, habits, Context(situation="수업", audience="교수", duration_min=10), rubric)
    for expected in ("목표초=600.0", "실제초=590.0", "평균자분=312.0", "평균SPS=4.7",
                     "최대자분=421.0(슬라이드 2)", "권장=31.0s 실제=50.0s", "cpm=421.0",
                     "REP=2 FIL=5 PAUSE=1 provider=heuristic", "- 1번 REP=2 FIL=5 PAUSE=1 h1",
                     "상황=수업 / 청중=교수 / 목표분=10", "총점 64점", "구조 70점",
                     "약한 항목: 속도 40점 — e2", "측정 못 한 항목 번호: [5]"):
        assert expected in block, expected
    assert "상호작용" not in block                 # omitted 클러스터는 싣지 않는다
    assert "- 2번 REP=0" not in block               # 습관 0 인 슬라이드는 줄을 만들지 않는다
    weak = [ln for ln in block.splitlines() if "약한 항목" in ln]
    assert [w.split()[3] for w in weak] == ["속도", "시선", "논리"]   # 낮은 점수 3개, 오름차순
    block = _facts_block(_pace(), _habits(), None, None)
    assert "상황=" not in block and "채점 기준" not in block
    block = _facts_block(_pace(), _habits(), Context(), None)
    assert "상황=- / 청중=- / 목표분=-" in block


# F-19 — 조립: 점수는 채점표만, 입력 dict 허용, 폴백 경로
def test_dict_inputs_and_rubric_score_are_carried_not_guessed():
    llm = ScriptedLLM(json.dumps({"one_liner": "좋아요", "score": 99, "strengths": ["a"]}))
    report = compose_report(_pace().to_dict(), _habits().to_dict(), Context(situation="s").to_dict(),
                            rubric=_rubric().to_dict(), llm=llm)
    assert report.score == 64 and report.grade == ""
    assert report.one_liner == "좋아요" and report.model == "scripted"
    assert "상황=s" in llm.prompts[0]
    assert compose_report(_pace(), _habits(), llm=ScriptedLLM("{}")).score == 0   # 채점표 없으면 0


def test_mock_backend_short_circuits_to_fallback(monkeypatch):
    monkeypatch.setenv("REASONING_BACKEND", "mock")
    report = compose_report(_pace(), _habits(), rubric=_rubric())        # llm=None → env
    assert report.model == "mock" and report.score == 64
    assert compose_report(_pace(), _habits(), llm="mock").model == "mock"


@pytest.mark.parametrize("payload", [RuntimeError("timeout"), "죄송합니다. 답할 수 없어요.", "```json\n{잘림"])
def test_llm_failure_falls_back_without_losing_numbers(payload):
    report = compose_report(_pace(), _habits(), rubric=_rubric(), llm=ScriptedLLM(payload))
    assert report.model == "scripted-fallback"
    assert report.score == 64
    assert report.one_liner == "2번은 핵심인데 권장 88초 중 28초만 썼어요."
    assert report.actions[0] == "1번(보조) 설명을 한 문장으로 줄여 목표 시간을 맞추세요."
    assert report.actions[1] == "2번(핵심)에 예시 한 줄을 추가해 권장 88초에 가깝게."
    assert report.actions[2] == "1번에서 반복한 구절을 한 번만 말하고 다음으로 넘기세요."


@pytest.mark.parametrize("raw", [
    '```json\n{"one_liner": "펜스"}\n```',
    '결과입니다.\n{"one_liner": "펜스"}\n감사합니다.',
])
def test_fenced_or_prose_wrapped_json_is_parsed(raw):
    assert _parse_json(raw)["one_liner"] == "펜스"
    report = compose_report(_pace(), _habits(), llm=ScriptedLLM(raw))
    assert report.one_liner == "펜스" and report.model == "scripted"
    assert report.pace_summary == "2번은 핵심인데 권장 88초 중 28초만 썼어요."   # 빈 키는 팁으로
    llm = ScriptedLLM(json.dumps({"strengths": list("abcdefg"), "actions": [1, 2]}))
    report = compose_report(_pace(), _habits(), llm=llm)
    assert report.strengths == list("abcde") and report.actions == ["1", "2"]   # 5개 상한·str 화


# F-19 — 폴백 리포트: 습관 0·휴지 0·팁 없음, 그리고 숫자 출처 속성
def test_fallback_with_zero_habits_and_no_tips_uses_defaults():
    pace = PaceDoc(avg_chars_per_min=320.0, slides=[
        SlidePace(slide_no=1, importance="core", status="ok", recommended_sec=60.0)])
    report = _fallback_report(pace, HabitDoc(), model="m", score=0)
    assert report.strengths == ["평균 말 속도 320자/분이 권장 구간에 가깝습니다.",
                                "1번 핵심 슬라이드 시간 배분이 안정적입니다."]
    assert report.weaknesses == ["특별히 큰 배분·습관 문제는 보이지 않습니다."]
    assert len(report.actions) == 3 and len(set(report.actions)) == 1      # 3개로 채움
    assert report.one_liner == "시간 배분과 음성 습관을 함께 점검했어요."
    assert report.habit_summary == "" and report.pace_summary == ""
    empty = _fallback_report(PaceDoc(), HabitDoc(), model="m")
    assert empty.strengths == ["슬라이드 전환과 발화 기록이 남아 코칭 근거를 만들 수 있습니다."]


def test_fallback_numbers_all_come_from_source_docs():
    """리포트 문장에 나오는 모든 숫자는 PaceDoc·HabitDoc 어딘가에 있는 값이어야 한다."""
    pace, habits, ctx, _ = _fixture()
    report = compose_report(pace, habits, ctx, rubric=RubricScore(score=45),
                            llm=ScriptedLLM(RuntimeError("down")))
    allowed: set[str] = set()
    for s in pace.slides:
        allowed |= {str(s.slide_no), f"{s.recommended_sec:.0f}", f"{s.actual_sec:.0f}"}
    allowed.add(f"{pace.avg_chars_per_min:.0f}")
    for tip in pace.tips + habits.tips:
        allowed |= _numbers(tip)
    allowed.add("3")   # 고정 문구 "3초 쉬어" 의 상수
    prose = " ".join([report.one_liner, report.pace_summary, report.habit_summary,
                      *report.strengths, *report.weaknesses, *report.actions])
    assert _numbers(prose) <= allowed, _numbers(prose) - allowed
    assert report.score == 45


def test_fixture_report_reassembles_from_llm_prose_with_score_from_rubric_only():
    pace, habits, ctx, saved = _fixture()
    report = compose_report(pace, habits, ctx, llm=ScriptedLLM(json.dumps(saved, ensure_ascii=False)))
    assert report.strengths == saved["strengths"] and report.actions == saved["actions"]
    assert report.score == 0                # 저장본의 45 는 LLM 값 취급 → 채점표 없으면 0


# F-19 — 스펙 위반 (strict xfail)
# (2026-09-13 고침 — 예전엔 xfail 이었다)
@pytest.mark.parametrize("raw", ["[]", "42", '"문자열"', '[{"one_liner": "x"}]'])
def test_non_object_json_from_llm_falls_back(raw):
    report = compose_report(_pace(), _habits(), rubric=_rubric(), llm=ScriptedLLM(raw))
    assert report.model == "scripted-fallback" and report.score == 64


# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_string_valued_list_field_is_wrapped_not_split():
    llm = ScriptedLLM(json.dumps({"one_liner": "x", "strengths": "말 속도가 좋아요"}, ensure_ascii=False))
    assert compose_report(_pace(), _habits(), llm=llm).strengths == ["말 속도가 좋아요"]


# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_empty_object_from_llm_does_not_produce_blank_report():
    report = compose_report(_pace(), _habits(), rubric=_rubric(), llm=ScriptedLLM("{}"))
    assert report.one_liner and report.actions


# F-06 재료
def _slides_json(nos, **override) -> str:
    return json.dumps({"slides": [dict({"slide_no": n, "title": f"T{n}", "topic": f"주제{n}",
                                        "keywords": [f"k{n}"], "concepts": [f"개념{n}: 설명"],
                                        "importance": "support"}, **override) for n in nos]},
                      ensure_ascii=False)


class EchoLLM(LLMProvider):
    """프롬프트에 적힌 슬라이드 번호만 돌려준다. `stray` 를 주면 그 번호도 끼워 넣는다."""

    name = "echo"

    def __init__(self, stray: dict | None = None):
        self.prompts: list[str] = []
        self.stray = stray

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False) -> str:
        self.prompts.append(user)
        nos = [int(ln.split("슬라이드 ")[1].split(":")[0])
               for ln in user.splitlines() if ln.startswith("### 슬라이드 ")]
        data = json.loads(_slides_json(nos))
        if self.stray and self.stray["slide_no"] not in nos:
            data["slides"].append(self.stray)
        return json.dumps(data, ensure_ascii=False)


def _doc(n: int, texts: dict[int, str] | None = None, sparse: set[int] = frozenset()) -> SlideDoc:
    texts = texts or {}
    return SlideDoc(file_name="deck.pdf", total_slides=n, slides=[
        Slide(slide_no=i, title=f"슬라이드 {i}", text_sparse=i in sparse, image_only=i in sparse,
              blocks=[SlideBlock("paragraph", texts.get(i, f"{i}번 내용"))] if i not in sparse else [])
        for i in range(1, n + 1)])


def _transcript(speech: dict[int, str]) -> Transcript:
    return Transcript(full_text=" ".join(speech.values()), by_slide=[
        SlideSpeech(slide_no=n, visit=1, start_sec=0.0, end_sec=1.0, text=t) for n, t in speech.items()])


def _headers(prompt: str) -> list[int]:
    return [int(ln.split()[2].rstrip(":")) for ln in prompt.splitlines() if ln.startswith("### 슬라이드 ")]


# F-06 — 배치 경계·병합·맥락
def test_batch_size_exactly_n_is_one_call_without_batch_note():
    llm = EchoLLM()
    out = extract_concepts(_doc(8), llm=llm, batch_size=8)
    assert len(llm.prompts) == 1 and "배치" not in llm.prompts[0]
    assert [s.slide_no for s in out.slides] == list(range(1, 9))
    assert out.model == "echo" and out.slides[0].topic == "주제1" and out.slides[0].importance == "support"


def test_batch_size_n_plus_one_splits_and_merges_in_order():
    llm = EchoLLM()
    out = extract_concepts(_doc(9), context={"situation": "수업"}, llm=llm, batch_size=8)
    assert len(llm.prompts) == 2
    by_note = {p.split("배치 ")[1][:3]: _headers(p) for p in llm.prompts}
    assert by_note == {"1/2": list(range(1, 9)), "2/2": [9]}
    assert all("발표 상황: 수업" in p for p in llm.prompts)
    assert [s.topic for s in out.slides] == [f"주제{i}" for i in range(1, 10)]


def test_batch_size_zero_uses_default_negative_becomes_one_and_context_none():
    llm = EchoLLM()
    extract_concepts(_doc(3), llm=llm, batch_size=0)          # 0 → BATCH_SIZE(8) → 1회
    assert len(llm.prompts) == 1 and "(입력 없음" in llm.prompts[0]
    llm = EchoLLM()
    extract_concepts(_doc(3), llm=llm, batch_size=-4)         # 음수 → max(1, …) → 장마다 1회
    assert len(llm.prompts) == 3
    assert extract_concepts(SlideDoc("e.pdf", 0), llm=EchoLLM()).slides == []   # 빈 자료: 호출 없음


def test_call_batch_rejects_non_list_and_missing_slide_keeps_source_title():
    out = extract_concepts(_doc(2), llm=ScriptedLLM(_slides_json([1])))   # 2번을 안 돌려줌
    assert out.slides[1].title == "슬라이드 2" and out.slides[1].topic == ""
    assert out.slides[1].concepts == [] and out.slides[1].raw_text == "2번 내용"
    doc = _doc(2)
    with pytest.raises(ConceptError, match="slides 배열"):
        _call_batch(ScriptedLLM('{"slides": {"slide_no": 1}}'), doc.slides, doc, Context(), None,
                    batch_i=1, batch_n=1)
    got = _call_batch(ScriptedLLM('{"slides": [{"slide_no": 1}, {"title": "x"}, "y"]}'),
                      doc.slides, doc, Context(), None, batch_i=1, batch_n=1)
    assert got == [{"slide_no": 1}]


# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_stray_slide_from_another_batch_cannot_overwrite_owner_batch():
    llm = EchoLLM(stray={"slide_no": 1, "topic": "STRAY", "keywords": [], "concepts": []})
    out = extract_concepts(_doc(2), llm=llm, batch_size=1)
    assert out.slides[0].topic == "주제1"


@BUG(strict=True, reason="BUG: importance 를 검증하지 않아 'high' 같은 값이 그대로 저장된다. "
     "F-17 은 == 'core' 로만 보므로 조용히 보조 취급된다. 수정: core|support 아니면 기본값")
def test_importance_outside_contract_is_normalized():
    out = extract_concepts(_doc(1), llm=ScriptedLLM(_slides_json([1], importance="high")))
    assert out.slides[0].importance in ("core", "support")


# F-06 — 프롬프트 조립: 클리핑·빈 슬라이드·발화 보완·캡션
def test_clip_boundary_at_max_slide_chars():
    assert MAX_SLIDE_CHARS == 1200
    assert _clip("가" * 1200) == "가" * 1200
    clipped = _clip("가" * 1201)
    assert clipped.endswith("\n…(이하 생략)") and len(clipped) <= 1200
    assert clipped.startswith("가" * 1180)
    assert _clip("  x  ", 10) == "x" and _clip(None) == ""


def test_prompt_marks_empty_and_sparse_slides_and_clips_speech_hint_to_600():
    doc = _doc(2, texts={1: ""}, sparse={2})
    prompt = _build_user_prompt(doc.slides, doc, Context())
    assert "### 슬라이드 1: 슬라이드 1\n(텍스트 없음)" in prompt
    assert "[경고] text_sparse=true" in prompt and "[경고] image_only=true" in prompt
    assert "[speech_hint]" not in prompt                       # transcript 없음
    doc = _doc(2, sparse={1})
    t = _transcript({1: "발화 " * 400})                          # 2번 슬라이드 발화 없음
    prompt = _build_user_prompt(doc.slides, doc, Context(), t)
    assert prompt.count("[speech_hint]") == 1
    body = prompt.split("[speech_hint] ", 1)[1].split("\n\n", 1)[0]
    assert body.endswith("\n…(이하 생략)") and len(body) <= 600


@BUG(strict=True, reason="SPEC MISMATCH: docstring·규칙 4 는 text_sparse 장에만 speech_hint 를 "
     "허용하는데 코드는 모든 장에 붙인다. 발화에만 있는 개념이 뽑히면 §1 원칙 1 경계가 흐려진다")
def test_speech_hint_is_not_attached_to_text_rich_slides():
    doc = _doc(1)
    prompt = _build_user_prompt(doc.slides, doc, Context(), _transcript({1: "발화에만 있는 개념"}))
    assert "[speech_hint]" not in prompt


CAPTIONED = ("- 알림은 흐름을 끊는다\n- 복귀에 23분\n<figure><img src='x.png'>"
             "<figcaption><p class=\"figure-description\">A well-lit, modern wooden desk with a laptop "
             "and a phone showing a notification</p></figcaption></figure>\n| 조건 | 복귀시간 |\n| 알림 | 23분 |")


def test_evidence_clean_slide_text_keeps_bullets_and_table_drops_captions():
    """f06 이 캡션 제거를 붙일 때 쓸 공용 헬퍼(_evidence)가 옳게 자르는지 먼저 확인한다."""
    cleaned = clean_slide_text(CAPTIONED)
    assert "알림은 흐름을 끊는다" in cleaned and "복귀에 23분" in cleaned
    assert "| 조건 | 복귀시간 |" in cleaned
    assert "well-lit" not in cleaned and "<" not in cleaned and "figcaption" not in cleaned


@BUG(strict=True, reason="NOT IMPLEMENTED: WORKLOG 09-12 G4(캡션 제거 뒤 클립)는 REGRESSED 로 "
     "미채택. f06 은 raw_text 를 그대로 싣는다 — 캡션이 1200자 예산을 먹는다")
def test_f06_prompt_drops_image_captions_before_clipping():
    doc = _doc(1, texts={1: CAPTIONED})
    prompt = _build_user_prompt(doc.slides, doc, Context())
    assert "알림은 흐름을 끊는다" in prompt and "| 알림 | 23분 |" in prompt
    assert "well-lit" not in prompt and "<figcaption>" not in prompt


# F-06 — 자체 JSON 복구 (_extract_json)
def test_extract_json_handles_fence_prose_and_truncated_slides_array():
    assert _extract_json("```json\n" + _slides_json([1]) + "\n```")["slides"][0]["slide_no"] == 1
    assert _extract_json("결과:\n" + _slides_json([1, 2]))["slides"][1]["slide_no"] == 2
    truncated = _slides_json([1, 2, 3])[:-40]          # 3번 객체 중간에서 잘림
    got = _extract_json(truncated)["slides"]
    assert [s["slide_no"] for s in got] == [1, 2]      # 완전한 객체만, 반쪽은 버림
    assert all(s["concepts"] == [f"개념{s['slide_no']}: 설명"] for s in got)
    assert _extract_json('{"a": [1, 2')["a"] == [1, 2]      # 완전한 객체가 없을 때의 괄호 보정


def test_extract_json_scavenges_intact_slide_objects_when_one_is_broken():
    raw = _slides_json([1, 2]).replace('"T2"', '"T "따옴표" 2"')   # 2번만 깨짐
    got = _extract_json(raw)
    assert [s["slide_no"] for s in got["slides"]] == [1]
    with pytest.raises(ConceptError, match="파싱 실패"):
        _extract_json("답할 수 없습니다")
    with pytest.raises(ConceptError, match="파싱 실패"):
        _extract_json("[1, 2]")


# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_extract_json_recovers_newline_inside_concept_string():
    raw = '{"slides": [{"slide_no": 1, "concepts": ["개념: 첫 줄\n둘째 줄"]}]}'
    assert _extract_json(raw)["slides"][0]["concepts"] == ["개념: 첫 줄\n둘째 줄"]
