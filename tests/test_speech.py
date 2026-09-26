"""chuckchuck/_speech.py — 합쇼체→해요체(to_haeyo) · 지어낸 숫자(ungrounded_numbers).

2026-09-26 실험대 실측(solar): 판정 총평·코칭 해설·골자가 매번 「~했습니다」 였고(CLAUDE.md §3-1 해요체 규칙),
숫자가 하나도 없는 자료에 골자가 "정확도 70~80%"·"전환율 15%" 를 썼다. 말투도 근거도 코드가 지킨다."""
import pytest

from chuckchuck._speech import to_haeyo, ungrounded_numbers


@pytest.mark.parametrize("raw, expected", [
    ("핵심 주장을 뒷받침하지 못했습니다.", "핵심 주장을 뒷받침하지 못했어요."),
    ("타당성 검증에 활용될 수 있습니다.", "타당성 검증에 활용될 수 있어요."),
    ("고민된다고 했습니다. Mencarelli et al. (2014)는 연구했는데", "고민된다고 했어요. Mencarelli et al. (2014)는 연구했는데"),
    ("무료로 제공합니다", "무료로 제공해요"),
    ("데이터로 활용됩니다.", "데이터로 활용돼요."),
    ("전략적 선택입니다.", "전략적 선택이에요."),          # 받침 → 이에요
    ("핵심 구조입니다.", "핵심 구조예요."),                # 받침 없음 → 예요
    ("타깃은 B2C입니다.", "타깃은 B2C이에요."),            # 로마자 → 이에요
    ("근거는 무엇입니까?", "근거는 무엇인가요?"),
    ("반영했습니까?", "반영했나요?"),
    ("설명해 드릴 수 있습니다.", "설명해 드릴 수 있어요."),   # 겸양(드릴)은 _HONORIFIC_RE 몫, 어미만 푼다
    ("구조로 설계했습니다. 특히 스토리 구조가 중요합니다.", "구조로 설계했어요. 특히 스토리 구조가 중요해요."),
    ("설명 능력을 향상시킵니다.", "설명 능력을 향상시켜요."),        # 모음 어간 + ㅂ니다 (일반 규칙)
    ("결과를 보여 줍니다.", "결과를 보여 줘요."),
    ("기능을 배웁니다.", "기능을 배워요."),
    ("데이터를 모아 둡니다.", "데이터를 모아 둬요."),
    ("이 방식을 씁니다.", "이 방식을 써요."),
    ("무엇을 시킵니까?", "무엇을 시키나요?"),
])
def test_hapsyo_becomes_haeyo(raw, expected):
    assert to_haeyo(raw) == expected


@pytest.mark.parametrize("already", [
    "요지는 잡았어요. 한 가지만 더 짚어 주세요.",
    "질문의 전제부터 확인해 보세요 — 자료는 그렇게 말하지 않아요.",
    "",
    "입니다만 그렇다고 봐요",                      # 어절 가운데는 어미가 아니다
    "자료 2장은 이렇게 말해요: «검토하고 있습니다.»",   # 인용 «…» 안은 자료 원문 — 손대지 않는다
    "「무료 체험 구조를 설계해야 합니다」 라고 적혀 있어요",
])
def test_haeyo_or_quoted_text_is_untouched(already):
    assert to_haeyo(already) == already


def test_unknown_stem_is_left_alone():
    """표에 없는 어간은 틀리게 바꾸지 않고 둔다 — 실험대의 합쇼체 표식이 센다."""
    assert to_haeyo("아침에 밥을 먹습니다.") == "아침에 밥을 먹습니다."
    assert to_haeyo("그 뜻을 모릅니다.") == "그 뜻을 모릅니다."      # 르 불규칙은 손대지 않는다


def test_idempotent():
    once = to_haeyo("핵심 주장을 뒷받침하지 못했습니다. 구조입니다.")
    assert to_haeyo(once) == once


# --- 지어낸 숫자 ---------------------------------------------------------------

DECK = ["무료 체험-유료 전환 구조와 적절한 과금 단위를 어떻게 설계해야 할지 자문받고 싶습니다", "2024년 3월 창업, 매출 1,200만 원"]


def test_numbers_missing_from_deck_are_reported():
    made = ungrounded_numbers("정확도는 70~80% 수준이며 전환율 15%를 목표로 3회 진단 뒤 제안한다", DECK)
    # "3회" 는 자료의 "3월" 과 숫자가 같아 통과한다 — 한 자리 수는 어디에나 있어 판단 재료가 약하다 (의도한 관대함)
    assert made == ["70", "80%", "15%"]


def test_numbers_present_in_deck_or_cite_years_are_fine():
    assert ungrounded_numbers("Boyle et al. (2022)는 2024년 3월 창업과 1200만 원 매출을 봤다", DECK) == []


def test_structural_and_name_numbers_are_skipped():
    # 장 번호·차수·낱말에 붙은 숫자(B2C·q01)·단위 없는 한 자리 수는 사실 주장이 아니다
    assert ungrounded_numbers("2장에서 B2C 와 q01 을 1차로 봤고 3 가지를 들었다", DECK) == []


def test_no_sources_means_no_judgement():
    assert ungrounded_numbers("정확도 70%", []) == []
    assert ungrounded_numbers("정확도 70%", ["", "   "]) == []
