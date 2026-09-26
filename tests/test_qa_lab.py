"""labs/qa_lab/checks.py — QA 실험대의 순수 검사. LLM·파일 없이 표식 규칙을 고정한다."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "labs" / "qa_lab"))

import checks  # noqa: E402


def q(**kw) -> dict:
    base = {"id": "q01-c1", "node_id": "c1", "label": "개념1", "question": "개념1의 근거는 무엇인가요?",
            "why": "", "hint": "", "answer_gist": "골자", "trap": False, "paper_ids": [], "evidence_quote": "자료 문장"}
    base.update(kw)
    return base


def j(**kw) -> dict:
    base = {"verdict": "partial", "score": 60, "react": "요지는 잡았어요.", "summary_sentence": "", "followup": "",
            "explanation": "", "hints": [], "coach_stage": "", "model": "solar"}
    base.update(kw)
    return base


# --- 질문 표식 -------------------------------------------------------------

def test_clean_question_has_no_bang_flags():
    assert not [f for f in checks.question_flags(q()) if f.endswith("!")]


def test_clipped_question_is_flagged_not_as_impolite():
    """09-24 모바일 실측 — 200자에서 잘려 '이…' 로 끝난 질문. 물음이 통째로 사라진 것이라 '잘림!' 하나로 잡는다."""
    flags = checks.question_flags(q(question="B2C와 B2B 중 어디에 집중해야 하는지 고민된다고 했습니다. Mencarelli et al. (2014)는 연구했는데, 이…"))
    assert "잘림!" in flags
    assert "반말끝!" not in flags
    assert "합쇼체1" in flags


def test_bnida_counts_as_hapsyo():
    assert "합쇼체2" in checks.question_flags(q(answer_gist="설명 능력을 향상시킵니다. 결과를 보여 줍니다."))


def test_impolite_ending_flagged():
    assert "반말끝!" in checks.question_flags(q(question="개념1의 근거는 무엇인가?"))


def test_honorific_in_question_flagged():
    flags = checks.question_flags(q(question="판단하신 근거는 무엇인가요?"))
    assert any(f.startswith("높임") and f.endswith("!") for f in flags)


def test_node_id_leak():
    assert "노드id노출" in checks.question_flags(q(node_id="concept-graph", label="개념 그래프",
                                                   question="concept-graph가 핵심 주장을 지탱하는 이유는 무엇인가요?"))
    # 라벨과 id 가 같거나, id 가 한글이면 노출이 아니다
    assert "노드id노출" not in checks.question_flags(q(node_id="개념1", question="개념1은 무엇인가요?"))


def test_presenter_cited_claim_on_scholar_only_papers():
    papers = {"refs": [{"id": "p1", "kind": "scholar"}]}
    flags = checks.question_flags(q(question="O'Reilly et al. (2026)를 인용했는데, 근거는 무엇인가요?"), papers)
    assert "인용주장!" in flags
    # 자료가 실제로 인용한 문헌(deck)이 있으면 거짓 전제가 아니다
    papers_deck = {"refs": [{"id": "p1", "kind": "deck"}]}
    assert "인용주장!" not in checks.question_flags(q(question="O'Reilly et al. (2026)를 인용했는데, 근거는 무엇인가요?"), papers_deck)


def test_fallback_and_trap_and_cite_markers():
    flags = checks.question_flags(q(question="개념1: 이 개념의 핵심과 자료에 넣은 근거를 설명해 주세요.", trap=True, paper_ids=["a", "b"]))
    assert "폴백" in flags and "함정" in flags and "인용2" in flags


def test_numbers_missing_from_deck_flagged():
    """09-26 실측(브리지 경로) — 골자에 '정확도 70~80%' · '전환율 15%' · '3회' 가 나왔는데 자료(멘토링 신청 폼)에는 숫자가 없다.
    포기하면 「정답 요지」 로 화면에 나가는 문장이라 지어낸 숫자는 막아야 한다."""
    deck = ["무료 체험-유료 전환 구조와 적절한 과금 단위를 어떻게 설계해야 할지", "2024년 3월 창업"]
    flags = checks.question_flags(q(answer_gist="정확도는 70~80% 수준이며 전환율 15% 를 목표로 3회 진단 뒤 제안한다"), None, deck)
    made = [f for f in flags if f.startswith("자료밖숫자!")]
    assert made and "70" in made[0] and "15%" in made[0]
    # 자료에 있는 숫자·인용 연도는 지어낸 것이 아니다
    assert not [f for f in checks.question_flags(q(answer_gist="Boyle et al. (2022)는 2024년 3월 창업을 봤다"), None, deck) if f.startswith("자료밖숫자")]
    # 자료 글이 없으면 판단하지 않는다
    assert not [f for f in checks.question_flags(q(answer_gist="70% 수준"), None, []) if f.startswith("자료밖숫자")]


# --- 판정 표식 -------------------------------------------------------------

def test_guard_reacts_detected():
    assert "가드:무관" in checks.judgement_flags(j(react="질문과 다른 이야기예요. 개념1에 대해 자료에 있는 대로 말해 보세요."))
    assert "가드:함정동의" in checks.judgement_flags(j(react="질문의 전제부터 확인해 보세요 — 자료는 그렇게 말하지 않아요."))
    assert "react폴백" in checks.judgement_flags(j(react="그 부분은 자료와 맞지 않아요."))
    assert "가드:질문벗어남" in checks.judgement_flags(j(react="개념1에 대한 답으로는 조금 멀어요. 질문이 묻는 것에 맞춰 다시 말해 보세요."))


def test_hapsyo_counted_outside_quotes_only():
    flags = checks.judgement_flags(j(summary_sentence="핵심 주장을 뒷받침하지 못했습니다.",
                                     explanation="자료 2장은 이렇게 말해요: «검토하고 있습니다.»"))
    assert "합쇼체1" in flags   # 인용 «…» 안의 합쇼체는 자료 원문이라 세지 않는다


def test_coach_stage_and_clipped_followup():
    flags = checks.judgement_flags(j(coach_stage="narrow", followup="이 부분은 어떻게 보…"))
    assert "코칭:narrow" in flags and "되묻기잘림!" in flags


# --- 실제값 검사 -------------------------------------------------------------

def bundle(**kw) -> dict:
    base = {
        "meta": {"source": "session:x", "models": {"concepts": "solar"}},
        "slide_doc": {"file_name": "화면 2장", "slides": [{"slide_no": 1, "title": "척척발표",
                      "blocks": [{"text": "슬라이드·발화 정합성 기반 AI 발표 학습 트레이너"}]}]},
        "question_doc": {"model": "solar", "questions": [q(evidence_quote="슬라이드·발화 정합성 기반 AI 발표 학습 트레이너")]},
        "papers": {"provider": "openalex", "refs": [{"id": "p1", "kind": "scholar"}], "note": ""},
        "judgements": [j()],
    }
    base.update(kw)
    return base


def grades(rows):
    return {item: grade for grade, item, _ in rows}


def test_real_bundle_passes():
    g = grades(checks.real_value_checks(bundle()))
    assert "FAIL" not in g.values(), g
    assert g["질문 근거"] == "PASS" and g["모델:F-08"] == "PASS" and g["모델:F-09"] == "PASS"


def test_mock_model_fails():
    g = grades(checks.real_value_checks(bundle(question_doc={"model": "mock", "questions": [q()]})))
    assert g["모델:F-08"] == "FAIL"


def test_sample_deck_marker_fails():
    b = bundle()
    b["slide_doc"]["slides"][0]["blocks"][0]["text"] = "IMU2CLIP 소개"
    assert grades(checks.real_value_checks(b))["자료"] == "FAIL"


def test_ungrounded_quotes_fail():
    b = bundle(question_doc={"model": "solar", "questions": [q(evidence_quote="자료에 없는 문장이에요 전혀")]})
    assert grades(checks.real_value_checks(b))["질문 근거"] == "FAIL"


def test_all_fallback_questions_fail():
    b = bundle(question_doc={"model": "solar", "questions": [q(question="개념1: 이 개념의 핵심과 자료에 넣은 근거를 설명해 주세요.")]})
    assert grades(checks.real_value_checks(b))["질문 폴백"] == "FAIL"


# --- probe ---------------------------------------------------------------------

def test_probe_plan_adds_agree_for_trap_only():
    names = [n for n, _, _ in checks.probe_plan(q(trap=True))]
    assert names == ["골자그대로", "함정동의", "무관한답", "포기"]
    assert [n for n, _, _ in checks.probe_plan(q())] == ["골자그대로", "무관한답", "포기"]


def test_probe_outcome():
    assert checks.probe_outcome(j(verdict="good", score=90)) == "pass"
    assert checks.probe_outcome(j(verdict="partial", score=75)) == "pass"     # 통과선 70 (contracts.qa_passed)
    assert checks.probe_outcome(j(verdict="partial", score=60)) == "partial"
    assert checks.probe_outcome(j(verdict="wrong", score=30)) == "wrong"
    assert checks.probe_outcome(j(verdict="unknown", coach_stage="narrow")) == "coach"
