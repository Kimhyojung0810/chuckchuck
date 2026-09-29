"""
녹음 ↔ 자료 대조 규칙 (09-30 녹음 대화 감사 REC-01·02·03·04②·12) — LLM 없이 도는 합성 자료·발표로 검사한다.
F-11 한 벌(모순 갈래·건너뛴 장·지어낸 인용)은 test_rec_align_f11.py.

- 비교를 (주어, 비교 대상, 잣대, 서술 방향) 으로 읽는다: 맞바꾼 주어 · 반의어 서술 · 수 없이 방향만 뒤집은 비교는 모순,
  바꿔 말하기 · 맞바꾸고 반의어로 말하기(같은 뜻)는 모순이 아니다 (`_compare`)
- 방향 낱말: 「-지다·-가다」 활용 · 바뀜 명사 + 크기 말(「증가 폭이 작았다」)은 한 서술로 접는다 (`signed_directions`)
- 「A에서 B로/까지」 는 앞뒤 값의 짝 · 「N 정도」 어림은 주어가 가리키는 값과만, %는 %p 폭
- 「N도 안 되는」「N에 못 미치는」 은 부정이 아니라 「N 미만」 · 「이 할」 은 2할
- 로마자 단위(ppm·kg·MB…) · 답이 부른 장
- LLM 인용의 문장마다 발화 확인 — 녹음에 없는 문장은 「이 슬라이드에서 한 말」 이 되지 않는다
- 건너뛰는 말: 빼고·제외하고·다루지 않을게요·안 볼게요 (발표의 이 자리를 가리킬 때만) · 건너뛴 장은 「정당한 생략」 이 아니다
- 모순의 갈래(수치·방향·맞다아니다)를 AlignmentItem.contra_kind 에 싣는다

자료·발표는 감사 덱(교실 공기·키오스크·번트)과 겹치지 않는 분야에서 새로 지었다 — 놀이터 그늘막 · 빨래방 · 마을버스 · 캠핑장 ·
공공 수영장 · 빗물 저금통 · 전통시장 카드 결제 · 청소년 합창단. 규칙에 특정 발표 낱말이 없음을 보이려고.
"""

from __future__ import annotations

import pytest

from chuckchuck._compare import comparison_relation, read_comparison
from chuckchuck._deck_claims import (
    build_deck,
    conflict_family,
    conflicts,
    direction,
    directions,
    from_to_pairs,
    negated,
    numbers,
    quantity_bounds,
    signed_directions,
)
from chuckchuck._spoken import skip_cue, spoken_numbers


def deck_of(*slides: str):
    return build_deck((i, text) for i, text in enumerate(slides, start=1))


def rel(said: str, deck_line: str) -> str:
    a, b = read_comparison(said), read_comparison(deck_line)
    assert a is not None and b is not None, (a, b)
    return comparison_relation(a, b)


# ---------------------------------------------------------------------------
# 방향 낱말 — 「-지다·-가다」 활용 · 바뀜 명사
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("word, want", [
    ("내려갔습니다", "down"), ("올라간", "up"), ("올라간다", "up"), ("떨어질", "down"), ("떨어진다", "down"),
    ("짧아졌어요", "down"), ("증가세", "up"), ("감소율이", "down"), ("내려감", "down"),
    ("줄간격", ""), ("낮잠", ""), ("긴장", ""), ("개선안", ""),
])
def test_direction_reads_jida_gada_forms_and_change_nouns(word, want):
    assert direction(word) == want


@pytest.mark.parametrize("text, want", [
    ("수영장 이용객 증가 폭이 작았습니다", {"up"}),          # 비교가 아니면 — 늘었다(조금)
    ("대기 시간 감소 폭이 컸어요", {"down"}),
    ("이용객이 많이 줄었어요", {"down"}),                    # 크기 부사는 방향을 안 바꾼다
    ("빗물 저금통을 단 집은 수도 요금이 크게 떨어졌어요", {"down"}),
])
def test_modifier_directions_fold_into_one_statement(text, want):
    assert directions(text) == want


@pytest.mark.parametrize("text, want", [
    ("평일 이용객은 주말보다 증가 폭이 작았습니다", [-1]),   # 비교면 곱 — 덜 늘었다
    ("평일 이용객이 주말보다 더 많이 늘었어요", [1]),
    ("평일 이용객이 주말보다 적게 줄었어요", [1]),           # 덜 줄었다
    ("평일 이용객이 주말보다 2배 빨리 줄었어요", [-1]),
])
def test_comparative_directions_multiply(text, want):
    assert signed_directions(text) == want


# ---------------------------------------------------------------------------
# 비교 세 칸 — 맞바꿈 · 반의어 · 방향만 · 같은 뜻 (REC-01)
# ---------------------------------------------------------------------------

SHADE = "그늘막을 친 놀이터는 맨땅 놀이터보다 한낮 지면 온도가 2배 빨리 내려갔습니다."
CAMP = "앱으로 예약한 캠핑장은 전화로 예약한 캠핑장보다 노쇼 비율 감소 폭이 컸습니다."
BUS = "배차를 늘린 마을버스 노선은 그대로 둔 노선보다 이용객이 1.5배 많았습니다."
RAIN = "비 오는 날에는 빨래방 이용이 맑은 날보다 2배 많았습니다."
CHOIR = "파트 연습을 먼저 한 합창단보다 더 중요한 것은 호흡 훈련입니다."


@pytest.mark.parametrize("said, deck_line, want", [
    # 주어·대상 맞바꿈 (수는 그대로)
    ("맨땅 놀이터가 그늘막 친 놀이터보다 지면 온도가 두 배 빨리 내려갔어요.", SHADE, "swapped"),
    ("전화로 예약한 캠핑장이 앱으로 예약한 캠핑장보다 노쇼 비율이 더 많이 줄었어요.", CAMP, "swapped"),
    ("그대로 둔 노선이 배차를 늘린 노선보다 이용객이 더 많았어요.", BUS, "swapped"),         # 수 없이 방향만
    ("맑은 날이 비 오는 날보다 빨래방 이용이 더 많았어요.", RAIN, "swapped"),               # 「…날에는 … 맑은 날보다」
    # 같은 두 쪽, 반의어 서술
    ("앱으로 예약한 캠핑장이 전화로 예약한 캠핑장보다 노쇼 비율이 덜 줄었어요.", CAMP, "reversed"),
    ("배차를 늘린 마을버스 노선은 그대로 둔 노선에 비해 이용객이 적었어요.", BUS, "reversed"),
    # 같은 뜻 — 바꿔 말하기 · 맞바꾸고 반의어
    ("그늘막을 친 놀이터는 맨땅 놀이터보다 지면 온도가 두 배 빨리 내려갔어요.", SHADE, "same"),
    ("맨땅 놀이터는 그늘막 친 놀이터보다 지면 온도가 느리게 내려갔어요.", SHADE, "same"),
    ("앱으로 예약한 캠핑장은 전화로 예약한 캠핑장보다 노쇼 비율이 더 많이 줄었어요.", CAMP, "same"),
    ("그대로 둔 노선은 배차를 늘린 노선보다 이용객이 적었어요.", BUS, "same"),
    ("비 오는 날은 맑은 날보다 빨래방 이용이 두 배 많았어요.", RAIN, "same"),
])
def test_comparison_relation(said, deck_line, want):
    assert rel(said, deck_line) == want


def test_pseudo_cleft_swap_and_its_paraphrase():
    assert rel("호흡 훈련보다 더 중요한 것은 파트 연습이에요.", "파트 연습보다 더 중요한 것은 호흡 훈련입니다.") == "swapped"
    assert rel("파트 연습보다 호흡 훈련이 더 중요해요.", "파트 연습보다 더 중요한 것은 호흡 훈련입니다.") == "same"


@pytest.mark.parametrize("said, deck_line", [
    ("그늘막 놀이터는 맨땅 놀이터보다 이용 시간이 길었어요.", SHADE),                 # 다른 잣대 (이용 시간 ↔ 지면 온도)
    ("맨땅 놀이터가 그늘막 놀이터보다 지면 온도가 빨리 내려가지는 않았어요.", SHADE),   # 부정 서술 — 견주지 않는다
    ("모래 놀이터는 맨땅 놀이터보다 지면 온도가 느리게 내려갔어요.", SHADE),           # 다른 주어
])
def test_comparisons_that_are_not_comparable(said, deck_line):
    assert rel(said, deck_line) == ""


def test_idiomatic_than_is_not_a_comparison():
    assert read_comparison("생각보다 대기 줄이 길지 않았어요") is None
    assert read_comparison("예상보다 이용객이 많았어요") is None


def test_conflicts_report_comparison_kinds_with_relation():
    d = deck_of("마을버스 배차\n" + BUS, "빨래방\n" + RAIN)
    swapped = conflicts("그대로 둔 노선이 배차를 늘린 노선보다 이용객이 더 많았어요.", d)
    assert [(c.kind, c.relation, c.slide_no) for c in swapped] == [("order", "swapped", 1)]
    reversed_ = conflicts("배차를 늘린 마을버스 노선은 그대로 둔 노선에 비해 이용객이 적었어요.", d)
    assert [(c.kind, c.relation) for c in reversed_] == [("direction", "reversed")]
    assert conflicts("그대로 둔 노선은 배차를 늘린 노선보다 이용객이 적었어요.", d) == []
    assert conflict_family("order") == conflict_family("direction") == "direction"


def test_question_that_quotes_the_line_is_exempt():
    """질문이 자료 줄을 옮겨 와 따지는 중이면(탐침) 그 줄은 방향 대조에서 뺀다 — 예전 규칙과 같다."""
    d = deck_of("마을버스 배차\n" + BUS)
    q = "배차를 늘린 마을버스 노선이 그대로 둔 노선보다 이용객이 1.5배 많았다는데, 정말 배차 때문인가요?"
    assert conflicts("그대로 둔 노선이 배차를 늘린 노선보다 이용객이 더 많았어요.", d, q) == []


# ---------------------------------------------------------------------------
# 수치 — 앞뒤 값 짝 · 어림 · 로마자 단위 · 부른 장 (REC-02 · REC-04②)
# ---------------------------------------------------------------------------

POOL = deck_of(
    "공공 수영장 레인 예약",
    "예약제 결과 (이용 회원 214명)\n| 지표 | 도입 전 | 도입 후 |\n| --- | --- | --- |\n| 레인 혼잡 민원 | 42건 | 9건 |\n"
    "| 평균 대기 시간 | 18분 | 6분 |\n예약제 도입 뒤 혼잡 민원이 크게 줄었습니다.",
    "자유 수영 만족도\n자유 수영 회원 만족도는 67%입니다.\n강습 회원(88%)보다 21%p 낮습니다.",
)


def test_from_to_pair_second_value_wrong_is_a_number_conflict():
    said = "레인 혼잡 민원이 도입 전 42건에서 도입 후 19건까지 줄었어요."
    found = [c for c in conflicts(said, POOL) if c.kind == "number"]
    assert found and found[0].slide_no == 2 and (found[0].said, found[0].deck_value) == ("19건", "9건")


def test_from_to_pair_said_right_is_fine_and_pairs_are_read():
    assert conflicts("레인 혼잡 민원이 도입 전 42건에서 도입 후 9건으로 줄었어요.", POOL) == []
    assert conflicts("평균 대기 시간도 18분에서 6분으로 줄었고요.", POOL) == []
    assert [(a.value, b.value) for a, b in from_to_pairs("대기가 18분에서 6분으로 줄었어요")] == [(18, 6)]
    assert from_to_pairs("민원 42건, 대기 18분이었어요") == []


def test_approximation_compares_with_the_value_the_subject_owns():
    # 67% 의 주인은 자유 수영 회원, 88% 는 강습 회원 — 「77% 정도」 는 88% 옆이라도 통과가 아니다
    wrong = conflicts("자유 수영 회원 만족도가 77% 정도 되는데요", POOL)
    assert [(c.kind, c.said, c.deck_value) for c in wrong] == [("number_unsupported", "77%", "67%")]
    assert conflicts("자유 수영 회원 만족도가 70% 정도 되는데요", POOL) == []     # 둥근 수 ±5%p
    assert conflicts("자유 수영 회원 만족도가 약 65%예요", POOL) == []


def test_latin_units_are_units_and_the_named_slide_wins():
    assert [(n.value, n.unit) for n in numbers("1,200kg에서 950kg으로 · 48MB · 3D 프린터 · 5GHz")] == [
        (1200, "kg"), (950, "kg"), (48, "mb"), (3, None), (5, "ghz")]
    tank = deck_of("빗물 저금통", "지붕 면적 1㎡당 연간 700L를 모읍니다.",
                   "설치 결과\n| 집 | 수돗물 사용 |\n| --- | --- |\n| 설치 전 | 1,200L |\n| 설치 후 | 950L |")
    right = "3장 표에서 1,200L가 950L로 줄었으니 수돗물을 아낀 거예요."
    assert conflicts(right, tank) == []


# ---------------------------------------------------------------------------
# 수량의 한계 · 「N할」 (REC-03)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "카드 결제 비율이 2할도 안 되는 가게", "카드 결제 비율이 20%에 못 미치는 가게", "카드 결제가 열 곳도 안 되는 시장",
    "한 시간도 안 걸려요", "대기 인원이 30명을 넘지 않는 날",
])
def test_quantity_bounds_are_not_negations(text):
    assert not negated(text), quantity_bounds(text)


@pytest.mark.parametrize("text", ["카드 결제가 안 되는 가게", "10명이 안 왔어요", "확인이 안 되는 정보"])
def test_real_negations_stay_negated(text):
    assert negated(text)


def test_spoken_hal_is_a_ratio_only_before_a_particle():
    assert spoken_numbers("결제 비율이 이 할도 안 되는") == "결제 비율이 2할도 안 되는"
    assert spoken_numbers("삼 할이 넘는 가게") == "3할이 넘는 가게"
    assert spoken_numbers("이 할 일은 많아요") == "이 할 일은 많아요"
    assert spoken_numbers("오늘 이 할 수 있어요") == "오늘 이 할 수 있어요"


def test_bound_said_like_the_deck_is_not_a_contradiction():
    market = deck_of("전통시장 카드 결제", "카드 결제 비율 2할 미만 가게는 손님이 줄었습니다.")
    said = spoken_numbers("카드 결제 비율이 이 할도 안 되는 가게는 손님이 줄었어요.")
    assert conflicts(said, market) == []
    assert conflicts(spoken_numbers("카드 결제 비율이 이 할이 안 되는 가게는 손님이 줄었어요."), market) == []


# ---------------------------------------------------------------------------
# 건너뛰는 말 (REC-12)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sentence, want", [
    ("예외인 경우는 오늘은 빼고 바로 마무리로 가겠습니다.", True),
    ("여기는 제외하고 요약만 말씀드릴게요.", True),
    ("이 부분은 오늘 다루지 않을게요.", True),
    ("이 표는 오늘은 안 볼게요.", True),
    ("나머지는 빼고 핵심만 볼게요.", True),
    ("자세한 설명은 안 할게요.", True),
    ("이 부분은 빼겠습니다.", True),
    # 발표 내용 속 빼기·제외·다루지 않기
    ("세제를 빼고 헹구면 옷감이 덜 상해요.", False),
    ("오늘은 세제를 빼고 돌려 볼게요.", False),
    ("외국인 회원은 제외하고 집계했어요.", False),
    ("이 조사는 주말 이용객을 제외하고 분석했어요.", False),
    ("이 부분은 제외하고 계산했어요.", False),
    ("그 연구는 초등학생을 다루지 않았어요.", False),
    ("오늘은 연습을 안 할게요.", False),
])
def test_skip_cue_removal_verbs(sentence, want):
    assert skip_cue(sentence) is want




# ---------------------------------------------------------------------------
# 2차 — 처음 보는 덱(held-out 1차)에서 드러난 한국어 꼴 (고유어 수 · 띄어 쓴 돈 · 드리다 · 꼴로 부른 장 · 한계 표지 ·
# 따옴표 말 · 한 글자 명사 · 머리 행 · 단정 아닌 제목 · 「N명 중 M명」 · 절 머리의 수)
# 분야: 목공 공방 · 수목원 해설 · 야간 소음 민원 · 해변 봉사단 (held-out 덱과 겹치지 않는다)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, want", [
    ("열두 명 중에 아홉 명이 남았어요", "12명 중에 9명이 남았어요"),
    ("해설사 여섯 분이 맡았고요", "해설사 6명이 맡았고요"),              # 고유어 수 + 분 = 사람
    ("석 달 동안 모았어요", "3개월 동안 모았어요"),
    ("스물아홉 명으로 늘었어요", "29명으로 늘었어요"),
    ("두 배 반 정도로 늘었죠", "2.5배 정도로 늘었죠"),
    ("사십 퍼센트입니다", "40%입니다"),
    ("세 가지를 바꿔요", "세 가지를 바꿔요"),                             # 단위로 못 읽는 세는 말은 두고
    ("나무를 심을 때 열 때를 맞춰요", "나무를 심을 때 열 때를 맞춰요"),
    ("네, 두 번 했어요", "네, 두 번 했어요"),
])
def test_native_numerals_with_counters(text, want):
    assert spoken_numbers(text) == want


def test_spaced_money_units_and_far_approximation():
    assert [(n.value, n.unit) for n in numbers("장비 예산 1,200만 원 · 공구 3억 원")] == [(1200, "만원"), (3, "억원")]
    shop = deck_of("목공 공방 예산", "공구 교체와 환기 설비 공사비 1,200만 원입니다.")
    said = spoken_numbers("공구 교체랑 환기 설비 공사비까지 해서 약 이천만 원입니다.")   # 절 머리의 수 — 주어는 앞 절에
    assert [(c.kind, c.said, c.deck_value) for c in conflicts(said, shop)] == [("number_unsupported", "2000만원", "1200만원")]
    assert conflicts(spoken_numbers("공구 교체랑 환기 설비 공사비까지 해서 약 천이백만 원입니다."), shop) == []


def test_humble_explain_forms_are_skip_cues():
    assert skip_cue("여기 계산식이 있는데요, 이 부분은 오늘 따로 설명드리지 않겠습니다.")
    assert skip_cue("이 표는 설명해 드리지 않을게요.")
    assert not skip_cue("이 계산식을 간단히 설명드리겠습니다.")


def test_quoted_words_do_not_end_clauses_and_quoted_adnominals_join_the_noun():
    from chuckchuck._deck_claims import clauses
    line = "'시끄럽다' 민원이 '조용하다' 민원보다 3배 많았습니다."
    assert clauses(line) == [line.rstrip(".")]
    noise = deck_of("야간 소음 민원\n" + line)
    assert conflicts("조용하다는 민원은 시끄럽다는 민원보다 훨씬 적었던 거죠.", noise) == []      # 맞바꾸고 반의어 — 같은 말
    assert [c.relation for c in conflicts("조용하다는 민원이 시끄럽다는 민원보다 더 많았어요.", noise)] == ["swapped"]


def test_one_syllable_nouns_split_the_two_sides():
    noise = deck_of("시간대별 소음\n낮 시간대에 비해 밤 시간대 소음이 12데시벨 높았습니다.")
    assert conflicts("그러니까 낮 시간대는 밤 시간대보다 소음이 낮았던 겁니다.", noise) == []
    assert [c.relation for c in conflicts("낮 시간대가 밤 시간대보다 소음이 더 높았어요.", noise)] == ["swapped"]


def test_header_row_is_not_another_row_and_one_syllable_row_names_own_their_values():
    noise = deck_of("측정값\n| 시간대 | 평균 소음 |\n| --- | --- |\n| 밤 22~24시 | 58% |\n| 낮 12~14시 | 31% |\n"
                    "민원의 70%가 밤 시간대에 들어왔습니다.")
    assert conflicts("낮 시간대는 평균 소음이 31%였고요.", noise) == []


def test_purpose_and_question_titles_are_not_assertions():
    guide = deck_of("해설 참여자, 한 번 더 오게 하려면\n수목원 해설 프로그램 운영 보고")
    assert conflicts("주제는 해설 참여자가 한 번 더 못 오고 끊기는 문제예요.", guide) == []


@pytest.mark.parametrize("said, flagged", [
    ("평균 대기 시간은 삼십 분 넘게 걸렸어요.", False),       # 자료 34분 — 30분 넘게는 맞다
    ("평균 대기 시간은 사십 분 가까이 걸렸어요.", False),
    ("평균 대기 시간은 십 분 넘게 걸렸어요.", True),           # 34분을 「십 분 넘게」 — 한계 폭(1.5배) 밖
    ("평균 대기 시간은 십오 분 정도 걸렸어요.", True),
])
def test_bound_markers_on_numbers(said, flagged):
    guide = deck_of("해설 대기\n수목원 해설 평균 대기 시간은 34분입니다.")
    got = [c.kind for c in conflicts(spoken_numbers(said), guide)]
    assert bool(got) is flagged, got


def test_part_of_whole_pairs_follow_the_row():
    beach = deck_of("봉사단 잔류",
                    "| 조 | 인원 | 석 달 뒤 남은 인원 |\n| --- | --- | --- |\n| 도우미 있음 | 12명 | 9명 |\n| 도우미 없음 | 30명 | 9명 |")
    wrong = conflicts(spoken_numbers("도우미가 있는 조는 열두 명 중에 네 명이 남았어요."), beach)
    assert [(c.kind, c.said, c.deck_value) for c in wrong] == [("number", "4명", "9명")]
    assert conflicts(spoken_numbers("도우미가 있는 조는 열두 명 중에 아홉 명이 남았어요."), beach) == []
    assert conflicts(spoken_numbers("도우미가 없는 조는 서른 명 중에 아홉 명이 남았어요."), beach) == []


def test_skip_target_by_slide_shape_and_previous_sentence():
    from chuckchuck._spoken import Utterance, skip_targets
    texts = {3: "대기 현황\n평일 34분", 4: "대기 시간 계산\n대기 시간 = 도착 간격 ×\n해설 시간 ÷ 해설사 수", 5: "개선안\n예약제",
             6: "하반기 계획\n해설사 2명 증원\n야간 해설 시범", 7: "정리\n감사합니다"}
    cue = Utterance(5, 5, 0, "여기 계산식이 있는데요, 이 부분은 오늘 따로 설명드리지 않겠습니다.", skip=True)
    assert list(skip_targets([cue], texts)) == [4]                      # 식이 있는 장 — 말이 놓인 구간(5장)이 아니라
    prev = Utterance(6, 6, 0, "하반기 계획은 단톡방에 따로 올려 둘게요.")
    cue2 = Utterance(7, 7, 0, "여기는 스킵하고 바로 정리할게요.", skip=True)
    assert list(skip_targets([prev, cue2], texts)) == [6]               # 앞 문장이 그 장을 불렀다 — 「정리」 는 가는 곳


def test_unitless_value_against_a_named_row_with_the_unit_in_the_header():
    """표 단위가 머리 칸에만 있으면 답도 단위를 뺀다 — 행 이름을 부른 값이 그 행 값과 다르면 어긋남 (09-30 standard 실행, 조정자)."""
    bakery = deck_of("손실 요인\n| 요인 | 월 손실 (만 원) |\n| --- | --- |\n| 재고 폐기 | -120 |\n| 포장재 | -45 |\n| 배달 수수료 | -80 |")
    got = conflicts("재고 폐기의 값이 -90이라고 나와요.", bakery)
    assert [(c.kind, c.said, c.deck_value) for c in got] == [("number", "-90", "-120만원")]
    assert conflicts("재고 폐기는 -120이에요.", bakery) == []
    assert conflicts("재고 폐기는 120 정도 손해예요.", bakery) == []            # 부호를 빼고 말해도 크기가 같으면 맞다
    assert conflicts("재고 폐기와 배달 수수료 차이는 40이에요.", bakery) == []  # 두 행을 부른 계산
