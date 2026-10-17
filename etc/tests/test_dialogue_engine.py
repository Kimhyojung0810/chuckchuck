"""
꼬리질문 엔진(f09_dialogue) · 갇힘 출구 · 외운 답 가드 (2026-10-17 Q&A 개편 5단계). LLM 은 전부 가짜 — 네트워크 없이.
"""

import json

from pipeline import f09_dialogue as DLG
from pipeline._recital import deep_question, recital
from pipeline.contracts import QaJudgement, QaTurn, Question
from pipeline.f09_judge import judge_answer
from pipeline.providers.llm_base import LLMProvider


class JudgeLLM(LLMProvider):
    name = "judge-fake"

    def __init__(self, payload: dict):
        self.payload = payload

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        return json.dumps(self.payload, ensure_ascii=False)


class TalkLLM(LLMProvider):
    """읽기+말하기 · 다시 말하기 가짜 — 부른 system 을 남긴다."""
    name = "talk-fake"

    def __init__(self, talk: dict, respeak: dict | None = None):
        self.talk, self.respeak, self.systems = talk, respeak or {}, []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.systems.append(system)
        return json.dumps(self.respeak if "이미 정해졌다" in system else self.talk, ensure_ascii=False)


def q(**kw) -> Question:
    base = dict(id="q01-c1", node_id="c1", label="2C 충전 열화", question="2C 충전이 용량을 깎았다는 주장이 충분한가요?",
                answer_gist="속도와 온도만 바꿨으니 속도 효과로 읽을 수 있지만 셀이 적어 단정은 어려워요.", severity=1,
                evidence_slide_no=2)
    base.update(kw)
    return Question(**base)


ANSWER = "실험실에서 한 거라서 상황마다 좀 다를 것 같아요."


def ti(**kw) -> DLG.TalkInput:
    return DLG.talk_input(q(), kw.pop("answer", ANSWER), **kw)


def judged(**kw) -> QaJudgement:
    base = dict(question_id="q01-c1", node_id="c1", verdict="partial", score=55, react="옛 반응", followup="옛 꼬리질문",
                evidence_slide_no=2)
    base.update(kw)
    return QaJudgement(**base)


# ─── 정책 ──────────────────────────────────────────────────────────────────────────────────

def test_정책은_코드가_정한다_순서가_우선순위():
    assert DLG.policy("partial", "", {"unknown": True}) == "hint"
    assert DLG.policy("partial", "deck", {}) == "challenge"                      # 가드가 찾은 어긋남
    assert DLG.policy("wrong", "", {"conflict": "높은 온도에서만"}) == "challenge"
    assert DLG.policy("partial", "", {"disagree": "중요하지 않다"}) == "explore"
    assert DLG.policy("good", "", {"idea": "x"}) == "deepen"
    assert DLG.policy("partial", "recital", {}) == "recite"
    assert DLG.policy("partial", "", {"vague": "좀 다를 것"}) == "clarify"
    assert DLG.policy("partial", "", {"idea": "x", "skipped": "왜 속도 탓인지"}) == "connect"
    assert DLG.policy("partial", "", {}, closing=True) == "explain"


# ─── 검사 ──────────────────────────────────────────────────────────────────────────────────

def test_말투_검사는_반말_높임_칭찬_길이_수치흘림_미시를_잡는다():
    t = ti()
    ok = DLG.check_turn("「상황마다 좀 다를 것」이라고 했죠. 어떤 조건이 다른지는 아직 빠졌어요.", "그 조건은 실사용과 어디서 달라요?", t)
    assert ok == []
    assert "not_haeyo" in DLG.check_turn("「상황마다」라고 했다. 조건이 빠졌다.", "어디서 달라?", t)
    assert "honorific" in DLG.check_turn("말씀하신 부분을 짚어 주시겠어요.", "조건이 무엇인지 말해 주시겠어요?", t)
    assert "praise" in DLG.check_turn("좋은 답이에요. 조건이 빠졌어요.", "어디서 달라요?", t)
    assert "sentence_long" in DLG.check_turn("「상황마다」라고 했죠. " + "가" * 50 + "요.", "어디서 달라요?", t)
    assert "number_leak" in DLG.check_turn("자료는 76%라고 해요.", "그 조건은 어디서 달라요?", t)
    assert "micro" in DLG.check_turn("조건이 빠졌어요.", "셀은 몇 개였나요?", t)
    assert "repeats_question" in DLG.check_turn("조건이 빠졌어요.", "2C 충전이 용량을 깎았다는 주장이 충분한가요?", t)


def test_되풀이_금지_R9():
    t = ti(avoid=["그 조건은 실사용과 어디서 달라요?"])
    assert "repeats_before" in DLG.check_turn("조건이 빠졌어요.", "그 조건은 실사용과 어디서 달라요?", t)


def test_인용은_답_원문_그대로만():
    assert DLG.verbatim("상황마다 좀 다를 것", ANSWER) == "상황마다 좀 다를 것"
    assert DLG.verbatim("상황마다좀다를것", ANSWER) == "상황마다 좀 다를 것"           # 띄어쓰기만 다름
    assert DLG.verbatim("배터리 화학이 문제", ANSWER) == ""                           # 지어낸 구절은 버린다
    assert DLG.quoted_anchor("「실험실에서 한 거라서」라고 했죠.", ANSWER) == "실험실에서 한 거라서"


def test_수치는_말하기_콜에_가려서_싣는다():
    t = DLG.talk_input(q(), "셀이 4개라 얇아요.", deck_lines=["[2장] 군당 셀 4개 · 표준편차 ±3.2%p · 유지율 76%"])
    u = DLG.talk_user(t)
    assert "76%" not in u and "3.2" not in u and "4개" in u          # 발표자가 먼저 말한 수치(4개)는 둔다


def test_긴_평가_문장은_뒤_마디만_남긴다():
    out = DLG.soft_trim("「표본이 적어서」라고 했죠. 표본이 적다는 점은 짚었지만, 표준편차가 커서 차이를 말하기 어려운지는 안 이어졌어요.")
    assert out.endswith("표준편차가 커서 차이를 말하기 어려운지는 안 이어졌어요.") and "짚었지만" not in out


# ─── 입히기 ─────────────────────────────────────────────────────────────────────────────────

GOOD_TALK = {"idea": "", "vague": "상황마다 좀 다를 것", "conflict": "", "disagree": "", "recite": False, "unknown": False,
             "skipped": "속도 효과로 읽는 까닭", "move": "clarify", "anchor": "상황마다 좀 다를 것",
             "react": "「상황마다 좀 다를 것」이라고 했죠. 어떤 조건이 다른지는 아직 흐려요.", "ask": "그 상황은 실사용과 어디서 달라요?"}


def test_같은_수로_쓰고_검사를_통과하면_LLM_문장을_쓴다():
    t = ti()
    talk = DLG.dialogue_talk(t, llm=TalkLLM(GOOD_TALK))
    out = DLG.apply(judged(), t, talk, respeak=False)
    assert out.move == "clarify" and out.dialogue["source"] == "llm"
    assert out.react.startswith("「상황마다 좀 다를 것」") and out.followup == "그 상황은 실사용과 어디서 달라요?"
    assert out.anchor == "상황마다 좀 다를 것"
    assert out.verdict == "partial" and out.score == 55          # 판정은 그대로


def test_수가_다르면_정해진_수로_다시_말한다():
    t = ti()
    talk = DLG.dialogue_talk(t, llm=TalkLLM({**GOOD_TALK, "move": "deepen"}))     # LLM 은 deepen 을 골랐다
    llm = TalkLLM(GOOD_TALK, respeak={"react": "「상황마다 좀 다를 것」이라고 했죠. 기준이 아직 흐려요.",
                                       "ask": "어떤 조건에서 그렇다는 말이에요?"})
    out = DLG.apply(judged(), t, talk, llm=llm)
    assert out.move == "clarify" and out.dialogue["source"] == "respeak"
    assert any("이미 정해졌다: clarify" in s for s in llm.systems)


def test_LLM_이_다_실패하면_코드_틀_그다음_판정_문장():
    t = ti()
    out = DLG.apply(judged(), t, DLG.TalkResult(error="boom"), respeak=False)
    assert out.dialogue["source"] == "template" and out.followup.endswith("?")
    assert out.react != "옛 반응"


def test_닫힌_질문은_꼬리질문이_없다():
    t = ti()
    talk = DLG.dialogue_talk(t, llm=TalkLLM({**GOOD_TALK, "vague": "", "idea": "실험실에서 한 거라서", "skipped": "",
                                             "move": "deepen", "anchor": "실험실에서 한 거라서",
                                             "react": "「실험실에서 한 거라서」라고 했죠. 조건과 결론을 이었어요."}))
    out = DLG.apply(judged(verdict="good", score=85), t, talk, respeak=False)
    assert out.mastered and out.followup == "" and out.move == "deepen"


def test_모순_함정_가드의_반응은_덮지_않는다():
    out = DLG.apply(judged(guard="contra_dispute", react="코드가 쓴 반응"), ti(), DLG.dialogue_talk(ti(), llm=TalkLLM(GOOD_TALK)))
    assert out.react == "코드가 쓴 반응" and out.dialogue["source"] == "guard"


def test_노드_이해_상태():
    s1 = DLG.node_state(None, judged(move="connect", dialogue={"read": {"skipped": "속도 효과로 읽는 까닭"}}))
    assert s1["state"] == "gap" and s1["skipped"] == "속도 효과로 읽는 까닭" and s1["tries"] == 1
    s2 = DLG.node_state(s1, judged(verdict="good", score=85, move="deepen"))
    assert s2["state"] == "understood" and s2["tries"] == 2
    assert DLG.node_state(None, judged(move="challenge"))["state"] == "misread"


# ─── 갇힘 출구 · 외운 답 (판정) ───────────────────────────────────────────────────────────────

def test_셋째_답에도_안_닫히면_해설로_닫는다():
    question = q()
    hist = [QaTurn(question=question.question, answer="엉뚱한 답 하나", verdict="wrong", question_id=question.id),
            QaTurn(question="꼬리질문", answer="엉뚱한 답 둘", verdict="wrong", question_id=question.id)]
    llm = JudgeLLM({"verdict": "wrong", "score": 30, "react": "아직이에요.", "summary_sentence": "s", "missing_points": ["x"],
                    "followup": "다시 볼래요?", "claim": ""})
    v = judge_answer(question, "물류 창고 재고 회전율 이야기예요", history=hist, prior_answers=["엉뚱한 답 하나", "엉뚱한 답 둘"], llm=llm)
    assert v.closed and v.mastered and v.coach_stage == "explain" and v.followup == ""
    assert v.close_reason == "explained" and v.explanation
    v2 = judge_answer(question, "물류 창고 재고 회전율 이야기예요", history=hist[:1], prior_answers=["엉뚱한 답 하나"], llm=llm)
    assert not v2.mastered and v2.followup                        # 둘째 답은 아직 붙든다


def test_외운_답_가리기():
    deck = ["충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었다", "군당 셀 4개 · 표준편차 ±3.2%p"]
    assert recital("충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었다", deck)
    assert recital("자료에는 「충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었다」라고 나와 있어요.", deck)
    assert not recital("충전 속도와 온도만 바꾸고 나머지를 묶었기 때문에 2C 효과만 보인다고 봐요.", deck)
    assert not recital("셀이 적어서 단정하긴 어려워요.", deck)
    assert deep_question("", "P2") and not deep_question("", "P1") and deep_question("이 결론은 어디까지 맞나요?")


def test_인용이_없으면_첫_문장을_답_구절_인용으로():
    r = DLG.with_quote("실험실 이야기를 했죠. 조건이 아직 흐려요.", "실험실에서 한 거라서", ANSWER, "clarify")
    assert r == "「실험실에서 한 거라서」라고 했죠. 조건이 아직 흐려요."
    assert DLG.with_quote("조건이 흐려요.", "지어낸 구절", ANSWER, "clarify") == "조건이 흐려요."     # 원문에 없으면 손대지 않는다
    assert DLG.with_quote("괜찮아요.", "실험실에서", ANSWER, "hint") == "괜찮아요."


def test_자료_줄을_대신_말하면_누설이다():
    t = DLG.talk_input(q(), "높은 온도에서만 측정했어요.", deck_lines=["[2장] 충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었다"])
    bad = DLG.check_turn("「높은 온도에서만」이라고 했죠. 자료는 충전 속도와 온도만 바꾸고 나머지 조건은 모두 묶었다고 해요.",
                         "자료 2장은 어떻게 말해요?", t)
    assert "deck_leak" in bad


# ─── 10-17 tune: 판정 가드가 못 잡은 어긋남 ─────────────────────────────────────────────────

PREMISE = "실험실에서 한 거라서 오히려 실사용에서 더 크게 깎여요."
CONFLICT_TALK = {"idea": "", "vague": "", "conflict": "실사용에서 더 크게 깎여요", "conflict_slide": 2, "disagree": "",
                 "recite": False, "unknown": False, "skipped": "", "move": "challenge", "anchor": "실사용에서 더 크게 깎여요",
                 "react": "「실사용에서 더 크게 깎여요」라고 했죠. 자료 2장과 방향이 달라요.", "ask": "자료 2장은 실사용을 어떻게 말해요?"}


def test_읽기_콜이_어긋남을_찾으면_판정이_good_이어도_짚고_통과를_막는다():
    t = ti(answer=PREMISE)
    talk = DLG.dialogue_talk(t, llm=TalkLLM(CONFLICT_TALK))
    out = DLG.apply(judged(verdict="good", score=85, react="", followup=""), t, talk, respeak=False)
    assert out.move == "challenge" and out.dialogue["read_conflict_cap"] is True
    assert out.verdict == "partial" and out.score <= DLG.READ_CONFLICT_SCORE_MAX and not out.passed and not out.mastered
    assert out.guard == "read_conflict" and out.followup.endswith("?")          # 닫지 않고 견주게 묻는다


def test_수를_challenge_로_골랐는데_어긋난_구절을_idea_칸에_두면_conflict_로_읽는다():
    t = ti(answer=PREMISE)
    talk = DLG.dialogue_talk(t, llm=TalkLLM({**CONFLICT_TALK, "conflict": "", "idea": "실사용에서 더 크게 깎여요"}))
    assert talk.read["conflict"] == "실사용에서 더 크게 깎여요" and talk.read.get("conflict_from_move")
    assert DLG.policy("wrong", "", talk.read) == "challenge"


def test_어긋남_신호가_없으면_good_판정은_그대로_닫힌다():
    t = ti()
    talk = DLG.dialogue_talk(t, llm=TalkLLM({**GOOD_TALK, "vague": "", "idea": "실험실에서 한 거라서", "skipped": "",
                                             "move": "deepen", "anchor": "실험실에서 한 거라서",
                                             "react": "「실험실에서 한 거라서」라고 했죠. 조건과 결론을 이었어요."}))
    out = DLG.apply(judged(verdict="good", score=85), t, talk, respeak=False)
    assert out.verdict == "good" and out.mastered and not out.dialogue["read_conflict_cap"]


def test_판정과_상관없는_검사에_걸리면_판정을_기다리지_않고_미리_다시_말한다(monkeypatch):
    long_react = "「상황마다 좀 다를 것」이라고 했죠. 그 말이 실험실의 가속 조건과 실제 사용자의 충전 조건 차이를 어떻게 설명하는지는 아직 빠졌어요."
    llm = TalkLLM({**GOOD_TALK, "react": long_react},
                  respeak={"react": "「상황마다 좀 다를 것」이라고 했죠. 기준이 아직 흐려요.", "ask": "어떤 조건에서 그렇다는 말이에요?"})
    monkeypatch.setattr(DLG, "_llm", lambda name=None: llm)
    t = ti()
    talk = DLG._talk_with(t, "fake")
    assert talk.early is not None and talk.early[0] == "clarify"           # 판정 전에 이미 띄웠다
    out = DLG.apply(judged(), t, [talk])
    assert out.dialogue["source"] == "respeak" and out.dialogue["respeak_early"] is True
    assert sum("이미 정해졌다" in s for s in llm.systems) == 1               # 다시 말하기는 한 번만


def test_challenge_반응이_자료_내용을_먼저_말하면_다시_말하게_한다():
    assert DLG.deck_claim("「정상관」이라고 했죠. 자료 13장은 역상관이라고 말해요.")
    assert not DLG.deck_claim("「정상관」이라고 했죠. 자료 13장은 그 말과 부딪혀요.")
    assert not DLG.deck_claim("「정상관」이라고 했죠. 자료 13장은 그걸 어떻게 말해요?")
    assert DLG.quote_problem("「정상관」이라고 했죠. 자료 13장은 역상관이라고 말해요.", "회전율은 정상관이에요", "challenge") == ["deck_claim"]
    assert DLG.quote_problem("「정상관」이라고 했죠. 자료 13장은 역상관이라고 말해요.", "회전율은 정상관이에요", "connect") == []


def test_가벼운_판정은_엔진이_켜진_판정에만_react_followup_을_비우라고_한다(monkeypatch):
    from pipeline import f09_judge as J
    seen = []

    class Rec(LLMProvider):
        name = "rec"

        def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
            seen.append(system)
            return json.dumps({"verdict": "partial", "score": 60, "react": "", "summary_sentence": "s", "missing_points": [],
                               "followup": "", "claim": "", "grounds": []}, ensure_ascii=False)

    J.clear_judge_cache()
    judge_answer(q(), ANSWER, llm=Rec(), dialogue=False)                      # 엔진 끔 — 예전 출력 그대로
    assert "출력 줄이기" not in seen[-1]
    assert J.judge_lean_on()
    monkeypatch.setenv("QA_JUDGE_LEAN", "0")
    assert not J.judge_lean_on()
