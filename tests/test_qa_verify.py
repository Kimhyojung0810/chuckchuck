"""
labs/qa_verify 하네스의 순수 함수 — 자동 페르소나 · 턴 태그 · 레드팀 공격 답 · 점수판 · 회귀 사례 데이터.

하네스가 대상 저장소를 재는 잣대라서, 잣대 자체가 흔들리면 회귀를 못 잡거나 헛회귀를 낸다. 여기서 고정한다.
덱은 **여러 분야의 합성 덱**(물류·동네 카페·교육·원예·건강)이다 — 특정 발표의 낱말에 기대는 규칙이 없는지 본다.
LLM·브라우저·브리지 없이 돈다.
"""

import json

import pytest

from labs.qa_verify import personas as P
from labs.qa_verify import redteam as R
from labs.qa_verify import regress as RG
from labs.qa_verify import scoreboard as S
from labs.qa_verify import tags as TG
from labs.qa_verify import textkit as T


def deck(*slides: str) -> dict:
    return {"file_name": "t.pptx", "total_slides": len(slides),
            "slides": [{"slide_no": i, "title": s.split("\n")[0], "raw_text": s} for i, s in enumerate(slides, 1)]}


LOGI = deck(
    "오배송은 왜 줄지 않나\n인력 부족이 아니라 검수 동선의 문제다",
    "원인은 인력이 아니다\n· 작업자 수와 오배송률의 상관은\n약함\n· 이동 거리 상위 구간 오배송률 3.4%\n몇 명이 일하느냐가 아니라, 몇 걸음을 걷느냐가 오배송을 갈랐다",
    "현황\n월 오배송률은 1년 새 0.8%에서 1.9%로 상승\n반품 비용 월 2,400만 원",
    "제안\n검수대를 출고 동선 가운데로 옮긴다\n시범 창고 두 곳에서 먼저 운영한다",
)
CAFE = deck(
    "동네 카페 재방문 분석\n재방문은 가격이 아니라 대기 시간에서 갈린다",
    "대기 시간\n주문 앱 도입 뒤 평균 대기 시간은 12분에서 7분으로 줄었다\n같은 기간 재방문율은 18% 늘었다",
    "가격\n아메리카노 가격은 그대로 3,500원이다\n경쟁 카페 네 곳도 가격이 비슷하다",
)
PLANT = deck(
    "실내 원예 관찰\n화분 위치와 생장",
    "빛과 생장\n화분이 창에서 멀어질수록 잎의 생장이 느려지는 경향\n관찰 기간 8주",
    "물 주기\n흙 겉면이 마른 뒤에 물을 준다\n받침에 고인 물은 바로 버린다",
)
EDU = deck(
    "참여 분석\n결론: 참여 감소는 과제량이 아니라 피드백 지연에서 온다",
    "원인\n피드백 지연 일수는 참여율과 뚜렷한 역상관\n출석률은 한 학기 새 92%에서 81%로 떨어졌다",
    "제안\n과제를 낸 다음 날 안에 짧은 피드백을 돌려준다",
)
HEALTH = deck(
    "식사 순서와 혈당",
    "실험 결과\n채소를 먼저 먹으면 식후 혈당 상승 폭이 30% 줄었다\n채소 → 단백질 → 탄수화물 순서로 먹는다",
    "주의\n개인에 따라 반응이 다를 수 있다",
)


def q(**kw) -> dict:
    base = {"id": "q01", "node_id": "n1", "label": "", "question": "", "answer_gist": "", "slide_nos": [],
            "evidence_quote": "", "evidence_slide_no": 0, "basis": None, "trap_premise": None, "hints": []}
    base.update(kw)
    return base


CAFE_Q = q(id="q01-wait", label="대기 시간", question="대기 시간이 재방문에 어떤 영향을 줬나요?",
           answer_gist="대기 시간이 12분에서 7분으로 줄자 재방문율이 18% 늘었어요.", slide_nos=[2],
           evidence_quote="주문 앱 도입 뒤 평균 대기 시간은 12분에서 7분으로 줄었다", evidence_slide_no=2)


# ---------------------------------------------------------------------------
# 입말 · textkit
# ---------------------------------------------------------------------------

def test_자료_줄의_끝을_평서형으로_풀고_옮겨_말하는_꼴로_만든다():
    assert T.plain_form("검수 동선의 문제입니다.")[0] == "검수 동선의 문제이다"
    assert T.plain_form("시범 창고에서 먼저 운영합니다")[0] == "시범 창고에서 먼저 운영한다"
    assert T.plain_form("상관은 약함") == ("상관은 약하다", False)
    assert T.plain_form("반품 비용 월 2,400만 원")[1] is True          # 명사로 끝난 줄
    assert T.reported("몇 걸음을 걷느냐가 오배송을 갈랐다") == "몇 걸음을 걷느냐가 오배송을 갈랐다고"
    assert T.reported("관리할 것은 사용 시간이 아니라 끊기는 횟수다") == "관리할 것은 사용 시간이 아니라 끊기는 횟수라고"
    assert T.reported("재방문율 18% 증가") == "재방문율 18% 증가라고"


def test_폭으로_꺾인_한_낱말과_열린_줄은_잇는다():
    lines = [x for _, x in T.deck_lines(LOGI) if _ == 2]
    assert "작업자 수와 오배송률의 상관은 약함" in lines
    assert "몇 명이 일하느냐가 아니라, 몇 걸음을 걷느냐가 오배송을 갈랐다" in lines


def test_대비_쪽과_명사구_판별():
    assert T.contrast_sides("재방문은 가격이 아니라 대기 시간에서 갈린다") == ("가격", "대기 시간")
    assert T.contrast_sides("핵심은 과제의 양이 아니라 피드백 속도다") == ("과제의 양", "피드백 속도")
    assert T.contrast_sides("왜 가격이 아니라 대기 시간인가?") is None               # 물음 줄
    assert T.noun_phrase_ok("기능 수") and not T.noun_phrase_ok("가지") and not T.noun_phrase_ok("시간을 훔치는 게")
    assert not T.noun_like("제시하지") and T.noun_like("방해")


def test_숫자_뒤집기는_자료에_없는_값으로_크기_단위를_먼저():
    new, old, to = T.number_flip("월 오배송률은 1년 새 0.8%에서 1.9%로 상승", avoid="1.9% 0.8% 1.2% 3.4%")
    assert old == "0.8%" and to not in ("0.8%", "1.2%") and to.endswith("%")
    assert T.antonym_flip("화분이 창에서 멀어질수록 잎의 생장이 느려지는 경향")[1:] == ("멀어질수록", "가까울수록")
    assert T.contrast_swap("재방문은 가격이 아니라 대기 시간에서 갈린다") is None          # Y 가 두 낱말이면 안 바꾼다


# ---------------------------------------------------------------------------
# 자동 페르소나
# ---------------------------------------------------------------------------

def test_좋은_답은_근거_줄을_입말로_잇고_골자가_아니라_자료를_따른다():
    wrong_gist = dict(CAFE_Q, answer_gist="대기 시간이 12분에서 3분으로 줄자 재방문율이 40% 늘었어요.")   # 골자가 틀렸다
    p = P.build(wrong_gist, CAFE)
    good = p["answers"]["good"]
    assert "12분에서 7분" in good and "3분" not in good and "40%" not in good
    assert good.endswith("해요.") and p["good_source"] in ("units", "ranked_quotes")


def test_오답은_좋은_답에서_사실_하나만_뒤집는다():
    p = P.build(CAFE_Q, CAFE)
    good, wrong = p["answers"]["good"], p["answers"]["wrong"]
    assert p["wrong_flip"]["kind"] == "number"
    diff = set(T.numbers(good)) ^ set(T.numbers(wrong))
    assert len(diff) == 2 and p["wrong_flip"]["from"] in diff and p["wrong_flip"]["to"] in diff
    assert p["wrong_flip"]["to"] not in "\n".join(T.slide_texts(CAFE).values())        # 뒤집은 값은 자료에 없다


def test_숫자가_없으면_방향_낱말을_뒤집는다():
    qq = q(label="창과의 거리", question="창과의 거리는 잎의 생장과 어떤 관계인가요?", slide_nos=[2],
           answer_gist="창에서 멀어질수록 생장이 느려져요.")
    p = P.build(qq, PLANT)
    assert "멀어질수록" in p["answers"]["good"]
    assert p["wrong_flip"]["kind"] == "direction" and "가까울수록" in p["answers"]["wrong"]


def test_대상의_함정_전제_생성기가_있으면_그걸_먼저_쓴다():
    seen = {}

    def fake_candidates(label, anchors, slide_doc):
        seen["args"] = (label, anchors)
        return [{"kind": "number", "premise": "같은 기간 재방문율은 27% 늘었다", "fact": "같은 기간 재방문율은 18% 늘었다",
                 "line": "같은 기간 재방문율은 18% 늘었다"}]

    p = P.build(CAFE_Q, CAFE, helpers=P.Helpers(trap_candidates=fake_candidates))
    assert seen["args"] == ("대기 시간", [2])
    assert "18%" in p["answers"]["good"]
    assert p["wrong_flip"]["via"] == "traps" and "27%" in p["answers"]["wrong"] and "18%" not in p["answers"]["wrong"]


def test_부분_답과_보완_답은_좋은_답을_나눈다():
    p = P.build(CAFE_Q, CAFE)
    a = p["answers"]
    assert a["partial"] != a["good"] and a["complete"].startswith("그리고")
    assert len(p["lines"]) >= 2


def test_무관한_답은_근거_장_밖이고_근거_장뿐이면_다른_덱의_말():
    p = P.build(CAFE_Q, CAFE)
    assert p["offtopic_source"] == "same_deck" and T.overlap(p["answers"]["offtopic"], CAFE_Q["question"]) == 0
    one = deck("대기 시간\n평균 대기 시간은 12분에서 7분으로 줄었다")
    p2 = P.build(dict(CAFE_Q, slide_nos=[1]), one)
    assert p2["offtopic_source"] == "other_deck" and p2["answers"]["offtopic"] in P.FOREIGN


def test_한_낱말은_개념_이름이고_두_낱말은_이름에_자료_낱말_하나():
    p = P.build(CAFE_Q, CAFE)
    assert p["answers"]["one_word"] == "대기 시간"
    assert p["answers"]["two_word"].startswith("대기 시간 ") and len(p["answers"]["two_word"].split()) == 3


def test_함정_질문은_전제_동의와_정정_답을_만든다():
    tp = {"kind": "number", "premise": "평균 대기 시간은 12분에서 3분으로 줄었다", "fact": "주문 앱 도입 뒤 평균 대기 시간은 12분에서 7분으로 줄었다",
          "slide_no": 2, "wrong": ["3분"], "right": ["7분"]}
    trap = dict(CAFE_Q, trap=True, trap_premise=tp, question="자료에서 「평균 대기 시간은 12분에서 3분으로 줄었다」라고 했는데, …")
    p = P.build(trap, CAFE)
    a = p["answers"]
    assert "3분" in a["trap_agree"] and not any(m in a["trap_agree"] for m in ("아니", "않", "달리", "사실은", "반대"))
    assert "7분" in a["trap_correct"] and "달리" in a["trap_correct"]
    assert a["good"] == a["trap_correct"] and "wrong" not in a and p["trap"]


def test_자료_밖_질문의_좋은_답은_자료에_없다고_말한다():
    qq = dict(CAFE_Q, question="단골 고객의 연령대는 어떻게 되나요?", answer_gist="자료에 나와 있지 않아요.",
              basis={"checks": ["gist_out_of_deck"]})
    p = P.build(qq, CAFE)
    assert p["out_of_deck"] and p["answers"]["good"].startswith("자료에는 그 내용이 나와 있지 않아요")


def test_주입된_이유_줄을_근거_질문의_좋은_답에_쓴다():
    qq = q(label="검수 동선", question="오배송이 검수 동선 때문이라고 결론지은 근거는 무엇인가요?", slide_nos=[2, 3],
           answer_gist="월 오배송률이 1.9%로 올랐어요.")
    helpers = P.Helpers(reason_lines=lambda question, texts, anchors: [(2, "몇 명이 일하느냐가 아니라, 몇 걸음을 걷느냐가 오배송을 갈랐다")])
    p = P.build(qq, LOGI, helpers=helpers)
    assert p["good_source"] == "reason_evidence" and "몇 걸음을 걷느냐가" in p["answers"]["good"]
    assert p["answers"]["good"].endswith("그래서 그렇게 결론 낸 거예요.")


def test_모르겠어요_보기는_자료가_세운_쪽을_고른다():
    qq = q(label="재방문", question="재방문을 가른 것은 무엇인가요?", slide_nos=[1],
           evidence_quote="재방문은 가격이 아니라 대기 시간에서 갈린다", evidence_slide_no=1)
    p = P.build(qq, CAFE)
    assert (p["dunno_affirmed"], p["dunno_negated"]) == ("대기 시간", "가격")
    assert P.pick_chip(["가격", "대기 시간"], p) == 1
    p2 = P.build(dict(qq, basis={"contrast": ["피드백 지연", "과제량"]}), EDU)
    assert P.pick_chip(["과제량", "피드백 지연"], p2) == 1


# ---------------------------------------------------------------------------
# 턴 태그
# ---------------------------------------------------------------------------

def tags_of(judge=None, bubbles=None, step="good", **ctx):
    base = {"question": ctx.pop("question", CAFE_Q), "step": step, "deck_lines": [x for _, x in T.deck_lines(CAFE)],
            "deck_text": "\n".join(T.slide_texts(CAFE).values()), "deck_raw": T.slide_texts(CAFE), "cumulative": "",
            "others": [], "corrected": False}
    base.update(ctx)
    return {t["tag"] for t in TG.turn_tags({"judge": judge, "bubbles": bubbles or [], "input": "답"}, base)}


def test_말투_태그는_인용_밖만_보고_변환_오류와_높임을_잡는다():
    got = {t["tag"] for t in TG.tone_tags(["그건 아녀요. 자료는 «잘 보입니다» 라고 해요.", "좋은 질문 주셔서 고마워요."])}
    assert {"tone.haeyo_broken", "tone.honorific"} <= got and "tone.hapsyo" not in got
    got = {t["tag"] for t in TG.tone_tags(["발표자는 S4 에서 설명했습니다.", "The bar chart compares five categories here",
                                           "이 부분은 자료 2장에서…"])}
    assert {"tone.third_person", "tone.internal_id", "tone.hapsyo", "tone.english", "tone.truncated"} <= got
    assert TG.tone_tags(["네, 그 설명이면 충분해요."]) == []


def test_되물음에_가드_사유나_문장_조각이_틀에_끼면_잡는다():
    assert "relevance.followup_glue" in tags_of({"verdict": "partial", "score": 60, "react": "음",
                                                "followup": "질문이 묻는 것: 대기 시간 — 이 부분은 어떻게 봐요?"})
    assert "relevance.followup_glue" in tags_of({"verdict": "partial", "score": 60, "react": "음",
                                                "followup": "설명이 조금 부족했어요. — 이 부분은 어떻게 봐요?"})
    assert "relevance.followup_support_wrong" in tags_of({"verdict": "wrong", "score": 20, "react": "음",
                                                        "followup": "대기 시간 — 이걸 뒷받침할 근거를 하나만 더 들어 주세요."})
    assert not {t for t in tags_of({"verdict": "partial", "score": 60, "react": "음",
                                    "followup": "대기 시간 — 이 부분은 어떻게 봐요?"}) if t.startswith("relevance.followup")}


def test_느슨한_통과와_틀린_답_칭찬과_맞는_답_강등():
    ok = {"verdict": "good", "score": 85, "passed": True, "mastered": True, "react": "좋아요, 맞아요."}
    assert "consistency.loose_pass" in tags_of(ok, step="offtopic")
    assert "consistency.loose_pass" not in tags_of(ok, step="good")
    bad = {"verdict": "wrong", "score": 20, "passed": False, "react": "그 부분은 정확해요."}
    assert "consistency.praise_on_fail" in tags_of(bad, step="wrong")
    guard = {"verdict": "partial", "score": 55, "passed": False, "react": "자료 2장과 어긋나는 부분이 있어요. 다시 볼 곳: 수치."}
    assert "consistency.good_demoted_guard" in tags_of(guard, step="good")
    assert "consistency.good_demoted_guard" not in tags_of(guard, step="wrong")


def test_결손은_자료에_없거나_이미_말했으면_잡는다():
    j = {"verdict": "partial", "score": 60, "react": "음", "missing_points": ["고객 설문 결과와 만족도 점수", "대기 시간 7분 단축"]}
    got = tags_of(j, cumulative="평균 대기 시간이 12분에서 7분으로 단축됐어요")
    assert {"relevance.missing_not_in_deck", "consistency.missing_already_said"} <= got
    closed = {"verdict": "good", "score": 90, "passed": True, "mastered": True, "react": "좋아요", "missing_points": ["대기 시간"]}
    assert "consistency.pass_with_missing" in tags_of(closed)


def test_보기는_명사구이고_자료에_있고_인용이_세운_쪽을_담아야_한다():
    followup = "자료 1장은 «재방문은 가격이 아니라 대기 시간에서 갈린다» 라고 해요. 이 장이 말하는 건 '가지' 쪽인가요, '가격' 쪽인가요?"
    got = TG.choice_tags(["가지", "가격"], "\n".join(T.slide_texts(CAFE).values()), followup)
    details = " ".join(t["detail"] for t in got)
    assert "세는 단위" in details and "대기 시간" in details
    got = TG.choice_tags(["줄이는", "우주선"], "\n".join(T.slide_texts(CAFE).values()))
    assert {t["detail"] for t in got} == {"활용형 꼬리", "자료에 없는 말"}
    assert TG.choice_tags(["가격", "대기 시간"], "\n".join(T.slide_texts(CAFE).values()), followup) == []


def test_화면_순번이_서버_라운드와_다르면_잡는다():
    j = {"verdict": "partial", "score": 60, "react": "음", "round_no": 1, "followup": "대기 시간은 몇 분이었나요?"}
    bubble = [{"who": "ai", "kind": "question", "meta": "이어서 묻습니다 · 3번째 답변", "text": "대기 시간은 몇 분이었나요?"}]
    assert "ux.counter_mismatch" in tags_of(j, bubble)
    bubble[0]["meta"] = "이어서 묻습니다 · 2번째 답변"
    assert "ux.counter_mismatch" not in tags_of(j, bubble)


def test_함정_사실을_바로잡기_전에_흘리면_잡는다():
    tp = {"kind": "number", "premise": "평균 대기 시간은 12분에서 3분으로 줄었다", "fact": "주문 앱 도입 뒤 평균 대기 시간은 12분에서 7분으로 줄었다",
          "right": ["7분"], "wrong": ["3분"]}
    trapq = dict(CAFE_Q, trap_premise=tp)
    leak = {"verdict": "wrong", "score": 20, "react": "자료는 7분이라고 해요.", "followup": ""}
    assert "ground.trap_leak" in tags_of(leak, question=trapq, step="trap_agree")
    assert "ground.trap_leak" not in tags_of(leak, question=trapq, step="trap_correct", corrected=True)


def test_다른_질문의_글이_react_에_새면_잡는다():
    j = {"verdict": "partial", "score": 60, "react": "아메리카노 가격은 그대로라는 점도 같이 말해 보세요.", "followup": ""}
    other = "아메리카노 가격은 그대로 3,500원인데 왜 경쟁 카페와 비슷한가요?"
    assert "relevance.cross_question_leak" in tags_of(j, others=[other], deck_text="", deck_lines=[])
    assert "relevance.cross_question_leak" not in tags_of(j, others=["출석률이 떨어진 까닭은 무엇인가요?"], deck_text="", deck_lines=[])


def test_완성_문장이_자료와_방향이_거꾸로면_잡고_상관_줄을_통째로_뒤집은_말은_둔다():
    lines = [x for _, x in T.deck_lines(PLANT)]
    assert TG.inverted_against("화분이 창에서 가까울수록 잎의 생장이 느려지는 경향이에요", lines)
    assert TG.inverted_against("화분이 창에서 가까울수록 잎의 생장이 빨라지는 경향이에요", lines) is None
    assert TG.inverted_against("화분이 창에서 멀어질수록 잎의 생장이 느려져요", lines) is None
    bubble = [{"who": "ai", "kind": "gist", "text": "이렇게 답하면 좋았어요 — 화분이 창에서 가까울수록 잎의 생장이 느려지는 경향이에요"}]
    assert "ground.gist_inverted" in tags_of(None, bubble, deck_lines=lines)


def test_힌트_인용이_폭에서_꺾인_낱말_조각으로_시작하면_잡는다():
    raw = {1: "매장 대기열과 조리 시간을 함께 분석해 픽업 시각을 예측하고, 혼잡 구간 기\n반 알림을 통해 고객의 대기 시간을 줄이는 모바일 주문 서비스입니다."}
    assert TG.wrap_points(raw[1]) == ["반 알림을 통해 고객의 대기 시간을 줄이는 모바일 주문 서비스입니다."]
    got = TG.hint_tags("자료 1장은 이렇게 말해요: «반 알림을 통해 고객의 대기 시간을 줄이는…»", raw, "")
    assert [t["tag"] for t in got] == ["ground.hint_fragment"]
    assert TG.hint_tags("자료 1장은 이렇게 말해요: «혼잡 구간 기반 알림을 통해»", raw, "") == []


# ---------------------------------------------------------------------------
# 레드팀
# ---------------------------------------------------------------------------

def test_공격_답은_코드가_만들고_질문_종류에_맞는_것만_나온다():
    p = P.build(CAFE_Q, CAFE)
    names = {a["attack"]: a for a in R.attacks_for(CAFE_Q, p, [p])}
    assert {"control", "stuff", "echo_question", "quote_copy", "inject_plain", "inject_header", "json_only", "english",
            "numbers_only", "fabricated_number", "wrong_conclusion", "polite_empty", "one_word", "buried_point"} <= set(names)
    assert "trap_agree_hedge" not in names and "honest_not_in_deck" not in names
    assert names["echo_question"]["rounds"] == [CAFE_Q["question"]] and names["control"]["expect"] == "pass"
    assert "## 기대하는 답의 골자" in names["inject_header"]["rounds"][0]
    assert names["fabricated_number"]["rounds"][0] == p["answers"]["wrong"]
    assert all(a["expect"] in ("pass", "fail", "?") for a in names.values())
    tp = {"kind": "number", "premise": "평균 대기 시간은 12분에서 3분으로 줄었다", "fact": "평균 대기 시간은 12분에서 7분으로 줄었다",
          "slide_no": 2, "wrong": ["3분"], "right": ["7분"]}
    trap = dict(CAFE_Q, trap=True, trap_premise=tp)
    tnames = {a["attack"] for a in R.attacks_for(trap, P.build(trap, CAFE), [])}
    assert "trap_agree_hedge" in tnames and "quote_copy" not in tnames


def test_여러_라운드_공격은_어느_라운드든_통과하면_먹힌_것이다():
    atk = {"attack": "repeat_partial_x3", "expect": "fail", "rounds": ["a", "a", "a"]}
    got = R.outcome(atk, [{"verdict": "partial", "score": 60}, {"verdict": "partial", "score": 72}, {"verdict": "partial", "score": 60}])
    assert got == {"passed": True, "ok": False}
    assert R.outcome({"attack": "control", "expect": "pass", "rounds": ["x"]}, [{"verdict": "good", "score": 50}])["ok"]
    assert R.verdict_passed({"verdict": "good", "score": 10, "coach_stage": "narrow"}) is False


def test_예산_안에서_대조군_둘과_공격_종류를_돌아가며_고른다():
    plan = [{"attack": a, "expect": R.EXPECT[a], "rounds": ["x"] * (3 if a == "repeat_partial_x3" else 1), "qid": f"q{i}"}
            for i in range(3) for a in ("control", "stuff", "json_only", "repeat_partial_x3", "one_word")]
    picked = R.pick_budgeted(plan, 7)
    assert sum(len(r["rounds"]) for r in picked) <= 7
    assert [r["attack"] for r in picked][:2] == ["control", "control"]
    assert len({r["attack"] for r in picked}) >= 4


def test_요약은_공격_통과율과_대조군_통과율을_따로_센다():
    rows = [{"attack": "stuff", "expect": "fail", "passed": True}, {"attack": "json_only", "expect": "fail", "passed": False},
            {"attack": "control", "expect": "pass", "passed": True}, {"attack": "buried_point", "expect": "?", "passed": True}]
    s = R.summarize(rows)
    assert (s["attack_pass_rate"], s["attack_n"], s["control_pass_rate"]) == (0.5, 2, 1.0)
    injected = R.slide_injected(CAFE, 2)
    assert R.SLIDE_INJECT in injected["slides"][1]["raw_text"] and R.SLIDE_INJECT not in CAFE["slides"][1]["raw_text"]


# ---------------------------------------------------------------------------
# 점수판
# ---------------------------------------------------------------------------

def board(metrics, base=None, cases=()):
    return S.assemble({"tier": "quick", "label": "t"}, metrics, list(cases), {"metrics": base or {}} if base is not None else None)


def test_결정적_지표는_조금만_나빠져도_회귀이고_좋아지면_아니다():
    b = board({"replay.f08.gist_inverted": S.ratio(2, 100)}, {"replay.f08.gist_inverted": S.ratio(1, 100)})
    assert b["regressions"] == ["replay.f08.gist_inverted"] and b["exit_code"] == 1
    b = board({"replay.probes.recall": S.ratio(20, 25)}, {"replay.probes.recall": S.ratio(19, 25)})
    assert b["regressions"] == [] and b["metrics"]["replay.probes.recall"]["improved"] and b["exit_code"] == 0


def test_LLM_지표는_표본_오차만큼_넓게_본다():
    small = board({"conv.good_pass": S.ratio(3, 5)}, {"conv.good_pass": S.ratio(4, 5)})
    assert small["regressions"] == []                                    # 5개 중 하나 차이는 흔들림
    big = board({"conv.good_pass": S.ratio(40, 100)}, {"conv.good_pass": S.ratio(90, 100)})
    assert big["regressions"] == ["conv.good_pass"]


def test_hard_지표와_회귀_사례_실패는_기준선이_없어도_exit_1():
    assert board({"quick.pytest.failed": S.metric(2)})["exit_code"] == 1
    assert board({"quick.pytest.failed": S.metric(0)})["exit_code"] == 0
    assert board({}, cases=[{"id": "c", "status": "fail"}])["failed_cases"] == ["c"]
    assert board({}, cases=[{"id": "c", "status": "skip"}])["exit_code"] == 0
    assert S.threshold_status(S.spec_for("replay.f08.hint_verbatim"), 0.9) == "fail"
    assert S.spec_for("tags.tone.hapsyo").direction == "lower"


def test_점수판_마크다운에_회귀와_예시가_나온다(tmp_path, monkeypatch):
    b = board({"replay.f08.gist_inverted": S.ratio(2, 10, ["q1: «가까울수록…»"])}, {"replay.f08.gist_inverted": S.ratio(0, 10)})
    md = S.to_markdown(b)
    assert "**회귀**" in md and "«가까울수록…»" in md and "exit 1" in md
    monkeypatch.setattr(S.C, "HISTORY", tmp_path / "history.jsonl")
    monkeypatch.setattr(S.C, "OUT", tmp_path)
    (tmp_path / "run1").mkdir()
    b["meta"].update(dir="run1", decks=["a"], tracks=["5"], tier="quick")
    (tmp_path / "run1" / "scoreboard.json").write_text(json.dumps(b), encoding="utf-8")
    S.record(b)
    assert S.find_baseline("latest", {"tier": "quick", "decks": ["a"], "tracks": ["5"]})["meta"]["dir"] == "run1"
    assert S.find_baseline("latest", {"tier": "quick", "decks": ["b"], "tracks": ["5"]}) is None
    assert S.find_baseline("latest-any", {"tier": "quick", "decks": ["b"], "tracks": ["5"]}) is not None


# ---------------------------------------------------------------------------
# 회귀 사례 데이터
# ---------------------------------------------------------------------------

def test_회귀_사례_데이터는_코드_없이_입력과_기대만_갖는다():
    cases = RG.load_cases()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)) and len(cases) >= 6
    by = {c["id"]: c for c in cases}
    for c in cases:
        assert c["kind"] in RG.KINDS, c["id"]
        src = c["source"]
        assert src.get("file") or src.get("inline") or src.get("inline_from") in by, c["id"]
        assert c.get("title") and isinstance(c.get("args"), dict)
    for need in ("hint_quote_ocr_wrap", "formula_quote_not_poll", "dunno_pair_contrast", "reason_gist_drops_background",
                 "undercut_question_rewritten", "antonym_gist_rejected"):
        assert need in by


def test_WP_J3_회귀_사례는_처음_보는_분야_쌍둥이가_있다():
    by = {c["id"]: c for c in RG.load_cases()}
    for need in ("gist_floor_probe_gist", "gist_not_restated_quote_split", "gap_absence_not_missing", "no_reask_after_absence",
                 "probe_stance_choices", "scaffold_blank_not_in_question", "hint_blank_not_label"):
        assert need in by and f"{need}_neutral" in by, need
        assert by[need]["kind"] == by[f"{need}_neutral"]["kind"]


@pytest.mark.parametrize("chips,kind,right", [
    (["늘 맞아요", "조건이 붙어요"], "absolute_boundary", "조건이 붙어요"),
    (["나와 있었어요", "아직 비어 있었어요"], "unsolved", "아직 비어 있었어요"),
    (["전체와 일부예요", "서로 다른 둘이에요"], "tension", "전체와 일부예요"),
])
def test_입장_보기_쌍_잣대는_세_종류를_다_알아본다(chips, kind, right):
    # 09-30 WP-J3 quick: 「아직 비어 있었어요」 가 틀린 쪽 표지 「있었」 에도 걸려 빈틈 입장 쌍을 못 알아봤다 — 보기 부적절로 셌다
    assert T.stance_pair(chips) == kind
    assert T.stance_correct(chips, kind) == right
    assert T.stance_correct(chips, "unsupported_cause" if kind == "unsolved" else kind) == right
    assert TG.choice_tags(chips, "") == []
    assert T.stance_pair(["시간", "연속성"]) == "" and T.stance_pair(["늘 맞아요", "늘 달라요"]) == ""


@pytest.mark.parametrize("word,question,shown", [
    ("완전히", "화분만 옮기면 잎이 완전히 자란다는 단정이 맞지 않는 경우는?", True),
    ("야간도난", "야간 도난을 개선하기 위한 구체적 방안은 무엇인가요?", True),   # _fill 이 띄어쓰기를 지운 꼴
    ("행동", "행동이 왜 중요한가요?", True),
    ("물주기간격", "물 주기에서 흙이 하는 역할은 무엇인가요?", False),      # 복합어의 앞 낱말만 질문에 있다
    ("대기 시간", "재방문율이 매장 경험보다 중요하다는 건 어떤 뜻인가요?", False),
])
def test_빈칸_잣대는_질문에_보인_말만_센다(word, question, shown):
    from labs.qa_verify import replay as RP
    assert RP._shown(word, {"question": question, "label": ""}) is shown


def test_inline_자료와_장_고르기_이어받기():
    cases = {c["id"]: c for c in RG.load_cases()}
    doc, where = RG.load_source({"id": "x", "source": {"inline_from": "dunno_pair_contrast", "slides": [2]}}, cases)
    assert where == "inline" and [s["slide_no"] for s in doc["slides"]] == [2]


@pytest.mark.parametrize("question,hit", [
    ("수면의 질이 시간보다 중요한 이유를 세 가지 요소(시간, 연속성, 규칙성)를 바탕으로 설명해 주세요.", "시간"),
    ("시간도 수면의 질의 요소인데, 수면의 질이 시간보다 중요하다는 건 어떤 뜻인가요?", ""),
    ("가격보다 대기 시간이 중요한 이유(대기 시간, 좌석 수)는 무엇인가요?", ""),
])
def test_자기모순_질문_잣대(question, hit):
    assert RG.self_contradicting(question) == hit


# ---------------------------------------------------------------------------
# 대화 배정 · 페르소나 채점 (브라우저 없이 — 턴 기록만)
# ---------------------------------------------------------------------------

def test_배정은_함정_질문의_TRAP_을_먼저_담고_예산을_넘지_않는다():
    from labs.qa_verify import conversation as CV

    plain = {"trap": False, "answers": {"good": "g", "wrong": "w", "one_word": "o", "offtopic": "x", "partial": "p"}}
    trap = {"trap": True, "answers": {"good": "c", "trap_agree": "a", "trap_correct": "c"}}
    plan, _ = CV.assign([{}, {}, {}], [plain, trap, plain], 4)
    assert plan == ["GOOD", "TRAP", "SKIP"]
    plan, rot = CV.assign([{}, {}], [plain, plain], 99, start=1)
    assert plan == ["WRONG", "DUNNO"] and rot == 3
    assert CV.assign([{}], [trap], 1)[0] == ["SKIP"]


def test_페르소나_채점은_판정_턴만_보고_판정이_없으면_채점하지_않는다():
    from labs.qa_verify import conversation as CV

    def turn(step, verdict, score, react="음", **kw):
        return {"step": step, "action": "answer", "judge": dict(verdict=verdict, score=score, react=react,
                                                                 passed=verdict == "good" or score >= 70, **kw), "tags": []}

    assert CV.score_persona("GOOD", [turn("good", "partial", 60), turn("good_more", "good", 85)])["good_pass"]
    got = CV.score_persona("WRONG", [turn("wrong", "wrong", 20, "정확해요"), turn("good", "good", 85)])
    assert got["wrong_rejected"] is False and got["wrong_recover"] is True          # 틀린 답에 칭찬하면 기대 실패
    got = CV.score_persona("TRAP", [turn("trap_agree", "wrong", 30, TG.TRAP_AGREED_LEAD + " — 자료는…"),
                                    turn("trap_correct", "good", 85)])
    assert got["trap_agree_caught"] and got["trap_correct_pass"]
    assert CV.score_persona("GOOD", []) == {"persona": "GOOD", "incomplete": True}


# ---------------------------------------------------------------------------
# 결정적 재생 잣대 — 코드가 자료 줄로 지은 골자는 겹침·방향 잣대에서 뺀다 (10-01 점검: 하네스 오탐)
# ---------------------------------------------------------------------------

def test_replay_rows_skip_code_built_gists_in_ground_and_direction_checks():
    from labs.qa_verify import replay as RP

    class _M:
        @staticmethod
        def _drop_expected_numbers(flags, q, n):
            return flags

        @staticmethod
        def verbatim(quote, raw):
            return True

    sd = {"slides": [
        {"slide_no": 5, "raw_text": "휴대폰 알림을 받은 조건에서 과제 수행이 나빠지는 결과가 나타났다 ."},
        {"slide_no": 6, "raw_text": "스마트폰 위치가 멀어질수록 인지 과제 수행이 좋아지는 경향"},
        {"slide_no": 7, "raw_text": "야식이 다음 날 아침 공복 혈당을 높입니다"},
    ]}
    wrapped = {"id": "w", "question": "알림을 어떻게 설명했나요?",
               "answer_gist": "자료는 이렇게 말해요 — 휴대폰 알림을 받은 조건에서 과제 수행이 나빠지는 결과가 나타났다 (5장)"}
    probe = {"id": "p", "question": "그렇게 볼 수 있는 근거는 무엇인가요?", "basis": {"checks": ["gist_probe_code"]},
             "answer_gist": "자료 7장의 「야식이 다음 날 아침 공복 혈당을 높입니다」에는 아직 수치나 출처가 없어요. 설문이나 통계, 비교 자료로 보강할게요."}
    llm = dict(probe, id="l", basis={"checks": []})
    rows = {r["id"]: r for r in RP.question_rows([wrapped, probe, llm], sd, {}, lambda q, a, t: [], lambda q: False, _M)}
    assert rows["w"]["inverted"] is None                # 자료 줄 그대로 — 다른 줄(주어가 다름)과 부딪혀도 골자 탓이 아니다
    assert rows["p"]["ungrounded"] is False             # 탐침 코드 골자 — 틀 말 때문에 겹침이 낮을 뿐이다
    assert rows["l"]["ungrounded"] is True              # 같은 글이라도 LLM 골자면 여전히 잰다 (잣대가 죽지 않았다)
