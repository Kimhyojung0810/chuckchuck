"""
모순 질문(「발표에서 “…”라고 했는데, 자료 N장의 수치와 달라요. 어느 쪽이 맞나요?」)의 판정·코칭 회귀 테스트 — 09-30 WP-CONTRA.
녹음 대화 감사 REC-04·08·09 (docs/review/2026-09-30_QA_녹음대화감사/report.md). LLM 은 대본이다.

- REC-04: 발표 쪽 값을 다시 우긴 답은 까닭을 달아도 wrong 35 · 첫 반응·되물음·결손이 자료 쪽 값을 먼저 말하지 않는다 ·
  자료 쪽 값을 댄 답은 숫자 짝 가드로 깎지 않는다(로마자 단위 · 다른 장 줄과의 가짜 어긋남) · 닫는 말은 질문의 장
- REC-08: 「모르겠어요」 1·2단은 발표 쪽 인용과 장 번호만 — 보기는 (자료 값, 발표 값), 값을 모르면 (자료 쪽, 발표 쪽) · 칩 답은 코드가 읽는다
- REC-09: 까닭 있는 반박(「자료가 오타고 발표가 맞다, 출처는 …」)엔 「그 근거는 확인할 수 없고, 자료 안의 숫자로는 …」 · 되풀이해도 안 오른다

**예시는 전부 처음 보는 분야**(동네 텃밭 물 아끼기 · 마을버스 노선)로 쓴다 — 감사의 교실 환기 덱 낱말은 쓰지 않는다. 규칙은 구조로만 짰다.
"""

import json
from dataclasses import replace

import pytest

from chuckchuck import coach_stuck, judge_answer
from chuckchuck._contra import leaks, sides_of, table_support, take_of
from chuckchuck._deck_claims import deck_from_slidedoc
from chuckchuck._probe_stance import stance_of, stance_pick, stance_prompt
from chuckchuck.contracts import (
    PROBE_STANCES,
    QaJudgement,
    QaTurn,
    Question,
    QuestionBasis,
    Slide,
    SlideBlock,
    SlideDoc,
)
from chuckchuck.f09_judge import _narrow_followup, _scaffold_judgement, clear_judge_cache
from chuckchuck.providers.llm_base import LLMProvider


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.calls += 1
        return json.dumps(self.payload, ensure_ascii=False)


class ForbidLLM(LLMProvider):
    name = "forbid"

    def complete(self, **kw):
        raise AssertionError("LLM 을 부르면 안 되는 경로다")


def judged(**kw) -> dict:
    base = dict(verdict="partial", score=70, react="요지는 잡았어요.", summary_sentence="요지를 말했어요.", missing_points=[], followup="")
    base.update(kw)
    return base


def slide(no: int, text: str) -> Slide:
    return Slide(slide_no=no, title=f"{no}장", blocks=[SlideBlock(category="paragraph", text=line) for line in text.split("\n")])


def doc(*slides: Slide) -> SlideDoc:
    return SlideDoc(file_name="deck.pdf", total_slides=len(slides), slides=list(slides))


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_judge_cache()
    yield
    clear_judge_cache()


# ---------------------------------------------------------------------------
# 동네 텃밭 — 수치 모순 (자료 4장 35% ↔ 발표 「오십 퍼센트나」). 표의 전·후 값(800L → 520L)이 35% 로 계산된다.
# ---------------------------------------------------------------------------

GARDEN = doc(
    slide(1, "동네 텃밭 물 아끼기\n물을 덜 쓰고도 수확은 그대로"),
    slide(2, "왜 물인가\n여름철 텃밭 물값이 공동 운영비의 절반을 넘습니다.\n물을 아끼면 채소 수확량이 늘어납니다."),
    slide(3, "조사 방법\n텃밭 12곳 · 6주 동안 계량기 기록"),
    slide(4, "결과\n| 방식 | 하루 물 사용량 |\n| --- | --- |\n| 스프링클러 | 800L |\n| 점적 관수 | 520L |\n"
             "점적 관수로 바꾸자 물 사용량이 35% 줄었습니다."),
    slide(5, "결론\n점적 관수를 텃밭 전체로 넓힙니다."),
)
GARDEN_Q = Question(
    id="q01-water", node_id="water", label="물 사용량", source="contradiction", slide_nos=[2, 4],
    question="발표에서 “물 사용량이 오십 퍼센트나 줄었어요”라고 했는데, 자료 4장의 수치와 달라요. 어느 쪽이 맞나요?",
    why="발표에서 말한 수치가 자료 4장과 달라서, 어느 쪽이 맞는지 짚어 보는 질문이에요",
    hint="자료 4장의 수치를 발표에서 한 말과 나란히 놓고 견줘 보세요",
    answer_gist="자료 4장은 “점적 관수로 바꾸자 물 사용량이 35% 줄었습니다.”라고 해요. 발표에서 한 “물 사용량이 오십 퍼센트나 줄었어요”는 "
                "이 수치로 바로잡아야 해요.",
    evidence_slide_no=4, evidence_quote="점적 관수로 바꾸자 물 사용량이 35% 줄었습니다.",
    speech_quote="그래서 물 사용량이 오십 퍼센트나 줄었어요.",
    basis=QuestionBasis(source="contradiction", slot="weak", rank=1,
                        checks=["contradiction_reconcile", "gist_template", "gist_contradiction_code", "basis_quote_hidden"]),
)
SAID_AGAIN = "아니요, 발표에서 말한 오십 퍼센트가 맞아요. 물이 확 줄었거든요."
SAID_REASON = "50퍼센트가 맞다고 생각해요. 제가 직접 계량기를 봤어요."
DISPUTE = "자료 쪽이 오타고 발표 수치가 맞아요. 출처는 저희 계량기 기록 원본인데, 거기엔 50%로 나와 있어요. 자료 만들 때 잘못 옮겼어요."
DISPUTE_AGAIN = "원본 기록에서 50%가 맞으니까 자료 4장을 고칠게요."
FIXED = "다시 보니 자료가 맞아요. 4장 표에서 800L가 520L로 줄었으니 35% 줄어든 거예요. 발표에서 잘못 말했어요."
LEAKY = judged(verdict="wrong", score=0, react="자료에서는 점적 관수로 바꾸자 물 사용량이 35% 줄었다고 명시되어 있어요.",
               followup="자료 4장에서 물 사용량은 35% 줄었는데, 왜 50%라고 했나요?", missing_points=["자료 4장의 35% 감소"])


@pytest.mark.parametrize("answer, side", [
    ("발표에서 말한 50퍼센트가 맞아요.", "said"),
    ("자료가 맞아요. 제가 발표에서 잘못 말했어요. 35%예요.", "deck"),
    ("50%가 아니라 35%예요.", "deck"),
    ("35%가 아니라 50%예요.", "said"),
    ("발표를 자료 4장에 맞춰 35%로 고칠게요.", "deck"),
    ("자료 4장을 50%로 고칠게요.", "said"),
    ("처음엔 발표가 맞다고 생각했는데, 다시 보니 자료가 맞아요.", "deck"),
    ("자료에는 35%로 나와 있지만 50%가 맞아요.", "said"),
    ("발표에서 50%라고 했는데 자료는 35%예요.", "deck"),
    ("자료를 잘못 봤어요. 35%가 맞네요.", "deck"),
    ("맞는 건 자료예요.", "deck"),
    ("삼십오 퍼센트예요", "deck"),
    ("물 사용량이 오십 퍼센트 줄었어요.", "said"),
    ("자료 쪽이요", "deck"),
    ("잘 모르겠어요 둘 다 맞는 것 같아요", ""),
    ("네, 맞아요.", ""),
])
def test_답이_고른_쪽은_구조_낱말과_서술어와_두_값으로_읽는다(answer, side):
    assert take_of(answer, sides_of(GARDEN_Q)).side == side


def test_두_쪽은_질문의_인용에서_읽고_칩_글에는_로마자_단위를_붙인다():
    s = sides_of(GARDEN_Q)
    assert (s.slide_no, s.deck_label, s.said_label) == (4, "35%", "50%") and s.numeric
    assert s.said_clause == "물 사용량이 오십 퍼센트나 줄었어요"
    # 단위를 파서가 읽든 안 읽든(09-30 WP-A 가 로마자 단위를 고치는 중) 칩 글은 「520L」 이다
    q = replace(GARDEN_Q, evidence_quote="점적 관수로 바꾸자 하루 물 사용량이 520L로 내려갔습니다.",
                speech_quote="하루 물 사용량이 사백 리터, 아니 420L로 내려갔어요.",
                question="발표에서 “하루 물 사용량이 420L로 내려갔어요”라고 했는데, 자료 4장의 수치와 달라요. 어느 쪽이 맞나요?")
    s2 = sides_of(q)
    assert (s2.deck_label, s2.said_label) == ("520L", "420L")


def test_발표_쪽을_다시_고른_답은_까닭을_달아도_wrong_35_이고_자료_쪽_값을_말하지_않는다():
    v1 = judge_answer(GARDEN_Q, SAID_AGAIN, slidedoc=GARDEN, llm=ScriptedLLM(LEAKY))
    assert v1.verdict == "wrong" and v1.score == 35 and v1.guard == "contra_said" and not v1.passed
    v2 = judge_answer(GARDEN_Q, SAID_REASON, slidedoc=GARDEN, prior_answers=[SAID_AGAIN],
                      llm=ScriptedLLM(judged(verdict="partial", score=75, react="직접 봤다는 근거가 있네요. 자료 4장에는 35%로 나와 있어요.")))
    assert v2.verdict == "wrong" and v2.score == 35 and not v2.passed and v2.guard == "contra_dispute"       # 예전 75 통과
    for v in (v1, v2):
        for text in (v.react, v.followup, *v.missing_points):
            assert "35%" not in text and "점적 관수로 바꾸자" not in text, text
        # 힌트 사다리(F-08 `build_hint_ladder` — 발표자가 눌러 여는 칸)의 빈칸 칸은 자료 줄에서 값만 가린다
        assert not any("35%" in h for h in v.hints)
        assert "자료 4장" in v.react


def test_반박에는_확인할_수_없다는_말과_자료_안의_숫자로_확인한_말_되풀이해도_안_오른다():
    v1 = judge_answer(GARDEN_Q, DISPUTE, slidedoc=GARDEN, llm=ScriptedLLM(judged(verdict="wrong", score=35)))
    v2 = judge_answer(GARDEN_Q, DISPUTE_AGAIN, slidedoc=GARDEN, prior_answers=[DISPUTE],
                      llm=ScriptedLLM(judged(verdict="partial", score=65, react="원본 기록을 기준으로 고치겠다는 방향은 좋아요.")))
    assert v1.guard == v2.guard == "contra_dispute" and v1.score == v2.score == 35      # 예전 35 → 65
    assert "확인할 수 없어요" in v1.react and "표 값으로 계산하면 자료에 적힌 값" in v1.react and "한쪽을 고쳐" in v1.react
    assert "조금 멀어요" not in v1.react + v2.react and "35%" not in v1.react + v1.followup
    assert "표 값으로 직접 계산" in v1.followup


def test_자료_안의_숫자가_발표_값으로_계산되면_반박을_받아_준다():
    typo = doc(*GARDEN.slides[:3], slide(4, "결과\n| 방식 | 하루 물 사용량 |\n| --- | --- |\n| 스프링클러 | 800L |\n| 점적 관수 | 400L |\n"
                                             "점적 관수로 바꾸자 물 사용량이 35% 줄었습니다."), GARDEN.slides[4])
    assert table_support(sides_of(GARDEN_Q), deck_from_slidedoc(typo)) == ("said", True)
    assert table_support(sides_of(GARDEN_Q), deck_from_slidedoc(GARDEN)) == ("deck", True)
    v = judge_answer(GARDEN_Q, DISPUTE, slidedoc=typo, llm=ScriptedLLM(judged(verdict="wrong", score=35)))
    assert v.verdict == "partial" and v.score == 70 and v.passed and "발표에서 한 값이 나와요" in v.react


def test_자료_쪽_값을_대고_발표를_고친_답은_숫자_가드로_안_깎이고_모범답이다():
    # LLM 이 부분 점수를 줘도 — 모범답(「자료 4장은 … 35% … 발표에서 한 …는 이 수치로 바로잡아야 해요」) 그대로다
    v = judge_answer(GARDEN_Q, FIXED, slidedoc=GARDEN, prior_answers=[SAID_AGAIN, SAID_REASON],
                     llm=ScriptedLLM(judged(verdict="partial", score=60, react="자료 4장의 수치로 바로잡았어요. 다만 근거가 조금 부족해요.")))
    assert v.verdict == "good" and v.score >= 85 and v.mastered and v.guard == ""
    assert "다만" not in v.react
    first = judge_answer(GARDEN_Q, FIXED, slidedoc=GARDEN, llm=ScriptedLLM(judged(verdict="good", score=85, react="맞게 바로잡았어요.")))
    assert first.verdict == "good" and first.guard == ""


def test_닫는_말은_질문의_장이다():
    # 3라운드에 가드만 막는다(LLM 은 통과) — 자료 쪽 값을 댔지만 2장 줄과 방향이 거꾸로다. 닫는 말은 모순의 장(4장)을 가리킨다.
    answer = "자료가 맞아요, 35%예요. 물을 아끼면 채소 수확량이 줄어들어요."
    v = judge_answer(GARDEN_Q, answer, slidedoc=GARDEN, prior_answers=[SAID_AGAIN, "음 잘 모르겠지만 둘 다 물이 줄었다는 말이에요."],
                     llm=ScriptedLLM(judged(verdict="partial", score=75, react="자료 쪽을 골랐어요.")))
    assert v.guard == "deck" and v.guard_blocked and v.mastered
    assert "자료 4장" in v.react and "자료 2장" not in v.react


def test_쪽을_고른_답은_초점_가드에_걸리지_않는다():
    v = judge_answer(GARDEN_Q, "자료가 틀렸고 발표 쪽이 맞아요. 원본엔 50%예요.", slidedoc=GARDEN,
                     llm=ScriptedLLM(judged(verdict="partial", score=50)))
    assert v.guard != "focus_miss" and "조금 멀어요" not in v.react


def test_쪽을_안_고른_답의_반응이_자료_쪽_값을_흘리면_코드_문장으로():
    v = judge_answer(GARDEN_Q, "음 둘이 다르긴 한데 잘 모르겠어요 물을 아낀 건 맞아요", slidedoc=GARDEN, llm=ScriptedLLM(LEAKY))
    assert "35%" not in v.react + v.followup + " ".join(v.missing_points)
    assert leaks("자료 4장에는 35%라고 나와요", sides_of(GARDEN_Q)) and not leaks("자료 4장에는 35%라고 나와요", sides_of(GARDEN_Q),
                                                                              said="35%예요")


def test_모르겠어요_1단_2단은_발표_쪽_인용과_장만_보이고_보기는_두_값이다():
    deck_text = " ".join(s.raw_text for s in GARDEN.slides)
    fu, choices = _narrow_followup({"followup": "자료가 말하는 35% 쪽인가요, 발표의 50% 쪽인가요?", "choices": ["35%", "50%"]},
                                   GARDEN_Q, None, deck_text, hide_quote=True)
    assert choices == ["35%", "50%"] and "“물 사용량이 오십 퍼센트나 줄었어요”" in fu and "자료 4장" in fu
    assert "35%" not in fu and "점적 관수" not in fu
    llm = ScriptedLLM({"react": "자료가 말하는 대로 35% 줄었다고 보면 돼요.", "followup": "", "choices": [],
                       "explanation": "자료 4장은 35% 줄었다고 해요."})
    j1 = coach_stuck(GARDEN_Q, slidedoc=GARDEN, llm=llm)
    assert j1.coach_stage == "narrow" and j1.choices == ["35%", "50%"] and j1.evidence_quote == ""
    assert "35%" not in j1.react + j1.followup
    turn = QaTurn(question_id=GARDEN_Q.id, question=GARDEN_Q.question, answer="(모르겠어요)", gave_up=True)
    j2 = coach_stuck(GARDEN_Q, slidedoc=GARDEN, history=[turn], llm=ForbidLLM())
    assert j2.coach_stage == "scaffold" and j2.evidence_quote == "" and j2.choices == ["35%", "50%"]
    assert "“물 사용량이 ___ 줄었어요”" in j2.followup and "점적 관수" not in j2.followup
    j3 = coach_stuck(GARDEN_Q, slidedoc=GARDEN, history=[turn, turn], llm=llm)
    assert j3.coach_stage == "explain" and "점적 관수로 바꾸자" in j3.evidence_quote        # 자료 쪽 줄은 해설에서 연다


def test_모순_칩_답은_코드가_읽는다():
    right = judge_answer(GARDEN_Q, "35%", slidedoc=GARDEN, llm=ForbidLLM())
    assert right.verdict == "partial" and right.score == 65 and "자료 4장에 맞춰 고쳐서" in right.followup
    wrong = judge_answer(GARDEN_Q, "50%", slidedoc=GARDEN, llm=ForbidLLM())
    assert wrong.verdict == "wrong" and wrong.score == 35 and "35%" not in wrong.react + wrong.followup
    assert stance_pick("35%요", GARDEN_Q) == "correct" and stance_pick("50%", GARDEN_Q) == "wrong"


# ---------------------------------------------------------------------------
# 마을버스 — 방향 모순 (값이 같고 비교가 거꾸로). 보기는 표의 「자료 쪽이에요 / 발표 쪽이에요」.
# ---------------------------------------------------------------------------

BUS = doc(
    slide(1, "마을버스 노선 다시 짜기"),
    slide(2, "만족도 조사\n새벽 노선은 낮 노선보다 이용객 만족도가 높았습니다."),
    slide(3, "제안\n새벽 배차를 늘립니다."),
)
BUS_Q = Question(
    id="q01-dawn", node_id="dawn", label="새벽 노선", source="contradiction", slide_nos=[2],
    question="발표에서 “낮 노선이 새벽 노선보다 만족도가 높았어요”라고 했는데, 자료 2장의 내용과 달라요. 어느 쪽이 맞나요?",
    answer_gist="자료 2장은 “새벽 노선은 낮 노선보다 이용객 만족도가 높았습니다.”라고 해요. 발표에서 한 “낮 노선이 새벽 노선보다 만족도가 "
                "높았어요”는 이 내용으로 바로잡아야 해요.",
    evidence_slide_no=2, evidence_quote="새벽 노선은 낮 노선보다 이용객 만족도가 높았습니다.",
    speech_quote="낮 노선이 새벽 노선보다 만족도가 높았어요.",
    basis=QuestionBasis(source="contradiction", checks=["contradiction_reconcile", "basis_quote_hidden"]),
)


def test_값을_모르는_모순은_표의_자료_쪽_발표_쪽_칩이다():
    st = stance_of(BUS_Q)
    assert st.choices == PROBE_STANCES["contradiction"].choices and st.correct == "자료 쪽이에요"
    text, chips = stance_prompt(BUS_Q)
    assert "“낮 노선이 새벽 노선보다 만족도가 높았어요”" in text and "자료 2장" in text and "이용객" not in text
    right = judge_answer(BUS_Q, "자료 쪽이에요", slidedoc=BUS, llm=ForbidLLM())
    assert right.verdict == "partial" and right.score == 65
    sj = _scaffold_judgement(BUS_Q, None, " ".join(s.raw_text for s in BUS.slides))
    assert sj.choices == ["자료 쪽이에요", "발표 쪽이에요"] and "이용객" not in sj.followup and sj.evidence_quote == ""


def test_방향_모순에_발표_쪽을_고른_답은_wrong_35():
    v = judge_answer(BUS_Q, "발표가 맞아요. 낮 노선 만족도가 더 높았어요.", slidedoc=BUS,
                     llm=ScriptedLLM(judged(verdict="partial", score=72, react="자료 2장은 새벽 노선이 더 높았다고 해요.")))
    assert v.verdict == "wrong" and v.score == 35 and "새벽 노선은 낮 노선보다" not in v.react


def test_모순이_아닌_질문은_그대로다():
    plain = replace(GARDEN_Q, source="core_weight", basis=QuestionBasis(source="core_weight"))
    assert sides_of(plain) is None and stance_of(plain) is None
    v = judge_answer(plain, SAID_AGAIN, slidedoc=GARDEN, llm=ScriptedLLM(judged(verdict="partial", score=72)))
    assert v.guard not in ("contra_said", "contra_dispute")


def test_판정_응답의_가드_이름이_계약을_지난다():
    v = judge_answer(GARDEN_Q, SAID_AGAIN, slidedoc=GARDEN, llm=ScriptedLLM(LEAKY))
    assert QaJudgement.from_dict(v.to_dict()).guard == "contra_said"
