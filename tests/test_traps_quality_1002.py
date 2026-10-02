"""
함정 질문 품질 (2026-10-02 질문 코치 벤치) — 함정은 발표자가 당연히 알아야 할 사실을 뒤집어야 공정하다.
옛 실패: 차트 축 눈금 「- 80」 + 축 이름 「회전율(회)」 이 사실 「80 회전율(회)」 이 됐고, 차트에서 읽은 표 값 -0.4 를 -0.5 로 바꿨다.
"""
from chuckchuck import _grounding as G
from chuckchuck import _traps as T
from chuckchuck._evidence import noise_lines
from chuckchuck.contracts import ConceptNode, Slide, SlideBlock

CHART = ("성공 요인\n상위 25% vs 하위 25% 행동 지표\n![image](/image/placeholder)\n- Chart Type: bar\n- 막대 그래프입니다.\n"
         "- 80\n70\n60\n0\n회전율(회)\n보유(월)\n|  | 회전율(회) | 보유(월) |\n| --- | --- | --- |\n| 상위 25% | 1 | 19 |\n"
         "| 하위 25% | 12 | 3 |\n핵심 요지\n회전율 8.4배 차이\n연 1.4회 vs 11.8회")


def _idx(text, label="회전율"):
    sl = Slide(slide_no=11, title="", blocks=[SlideBlock(category="paragraph", text=text)])
    cover = Slide(slide_no=1, title="", blocks=[SlideBlock(category="paragraph", text="격차는 행동에서 만들어진다.")])
    return G.build_index({1: cover, 11: sl}, [ConceptNode(id="t", label=label, slide_nos=[11], kind="concept", parent_id="r", depth=2)])


def test_bullet_axis_tick_is_noise():
    assert "- 80" in noise_lines(CHART)


def test_axis_label_and_chart_table_are_not_number_trap_facts():
    cands = T.candidates("회전율", [11], _idx(CHART))
    facts = [c.premise.fact for c in cands]
    assert facts and not any("80 회전율" in f for f in facts)
    assert not any(c.premise.kind == "number" and c.premise.fact.startswith("표에서") for c in cands)   # 차트 표 칸 값 바꾸기 X
    assert any("8.4배" in f for f in facts)                                                            # 서술한 사실은 재료다


def test_repeated_number_gets_emphasis():
    text = "현황\n개인 평균은 지수 대비 연 4.8%p 낮음\n연 4.8%p는 10년 뒤 원금 규모의 차이가 된다\n상위 25% 그룹도 지수를 2.6%p 하회"
    cands = T.candidates("개인 평균", [11], _idx(text, "개인 평균"))
    assert cands and "4.8%p" in cands[0].premise.fact
