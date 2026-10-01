"""10-01 수익률격차 녹음 — 「틀리게 말함」 오판 넷을 거르고, 진짜 모순은 그대로 잡는다 (_align_checks · _deck_claims)."""

from chuckchuck import _align_checks as chk
from chuckchuck._deck_claims import Conflict, conflicts, deck_from_slidedoc
from chuckchuck._spoken import spoken_numbers
from chuckchuck.contracts import Slide, SlideBlock, SlideDoc


def _deck(*texts):
    """장마다 줄(\n)을 문단 블록 하나씩으로 — tests/test_claims_general.py 의 deck() 과 같은 꼴."""
    return deck_from_slidedoc(SlideDoc(file_name="d.pptx", total_slides=len(texts), slides=[
        Slide(slide_no=i, title=t.split("\n")[0], blocks=[SlideBlock(category="paragraph", text=x) for x in t.split("\n")])
        for i, t in enumerate(texts, 1)]))


def test_퍼센트와_퍼센트포인트가_다른_같은_값은_모순이_아니다():
    deck = _deck("기관과의 차이는 작다\n지수 8.7% vs 기관 7.9% — 0.8%p")
    c = Conflict("number", 1, "지수 8.7% vs 기관 7.9% — 0.8%p", "이 차이가 0.8% 8% 밖에 안 됩니다", "", "0.8%", "8.7%")
    assert chk._said_on_slide(c, deck)


def test_받아쓰기가_소수점을_놓친_값은_모순이_아니다():
    deck = _deck("개인 평균은 지수 대비 연 4.8%p 낮음\n상위 25% 그룹도 지수를 2.6%p 하회")
    c = Conflict("number_unsupported", 1, "개인 평균은 지수 대비 연 4.8%p 낮음", "여전히 지수를 26%p 밑돕니다", "", "26%p", "4.8%p")
    assert chk._said_on_slide(c, deck)


def test_자료_값이_없는_수_모순은_내지_않는다():
    c = Conflict("number", 1, "다섯 가지 행동 요인", "나머지 4개는 결심이 필요하지만", "", "4개", "")
    assert chk._said_on_slide(c, _deck("다섯 가지 행동 요인"))


def test_같은_장의_다른_값을_말한_진짜_모순은_거르지_않는다():
    deck = _deck("A 그룹 30%, B 그룹 50%")
    c = Conflict("number", 1, "A 그룹 30%, B 그룹 50%", "A 그룹은 50%였습니다", "", "50%", "30%")
    assert not chk._said_on_slide(c, deck)


def test_못_넘었다는_못_미쳤다와_같은_방향이다():
    deck = _deck("성과 상위 그룹조차 지수에 못 미쳤다 — 개인 투자 방식 자체를 봐야 한다는 신호")
    said = spoken_numbers("상위 그룹도 못 넘었다면 개인 투자 방식 자체를 봐야 된다는 신호가 됩니다")
    assert not [c for c in conflicts(said, deck) if c.kind == "direction"]


def test_진짜_반대_방향은_계속_잡는다():
    """방향 판정이 살아 있는지 — _polarity_one 머리말의 09-29 실측 사례 (상관이 약함 ↔ 강하게)."""
    deck = _deck("종목 선정 능력과 수익률의 상관은 약함")
    said = spoken_numbers("종목 선정 능력과 수익률의 상관이 강하게 나왔고")
    assert [c for c in conflicts(said, deck) if c.kind == "direction"]
