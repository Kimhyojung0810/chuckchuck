"""
labs/qa_bench/hier_stab — F-07 위계 안정성 잣대 (WP-C2, 2026-09-30).

잣대가 흔들리면 프롬프트 A/B 가 헛결론을 낸다 — 09-30 표본 2개 A/B 에서 루트 이름 하나가 바뀐 덱의 옛 부모 일치율이 0 이 됐다.
여기서 잣대의 약속을 고정한다: 루트 이름 바뀜은 한 건, 서브트리 옮김은 옮긴 부모 관계만큼, 규칙 D 의 「X 저하」 는 「X」 와 짝이 아니다.
덱은 여러 분야의 합성 이름(물류·원예·도서관)이다.
"""

import copy

from labs.qa_bench import hier_stab as H


def graph(*rows):
    """(id, 이름, 부모 id|None, 장들)."""
    return {"nodes": [{"id": i, "label": lab, "parent_id": p, "slide_nos": list(s)} for i, lab, p, s in rows]}


BASE = graph(
    ("r", "물류 혁신", None, [1]),
    ("a", "거점 통합", "r", [2]), ("b", "배송 경로", "r", [3]), ("c", "재고 회전", "r", [4]),
    ("a1", "창고 수", "a", [2]), ("a2", "적재율", "a", [2]),
)


def relabel(g, old, new):
    g = copy.deepcopy(g)
    for n in g["nodes"]:
        if n["label"] == old:
            n["label"] = new
    return g


def test_같은_그래프는_모두_1():
    r = H.compare(BASE, copy.deepcopy(BASE))
    assert r["apa"] == r["anc"] == r["cover"] == r["tes"] == r["pa_old"] == 1.0
    assert r["renamed"] == 0 and r["moved"] == 0


def test_루트_이름_바뀜은_한_건이지_자식_전부_불일치가_아니다():
    other = relabel(BASE, "물류 혁신", "배송 효율화")          # 낱말이 하나도 안 겹치는 새 루트 이름
    r = H.compare(BASE, other)
    assert r["pa_old"] == 2 / 5                                  # 옛 잣대: 루트 자식 셋이 전부 불일치
    assert r["apa"] == 1.0 and r["anc"] == 1.0                   # 새 잣대: 위계는 그대로
    assert r["renamed"] == 1 and r["tes"] == 1 - 1 / 12          # 이름 바꿈 1건
    assert r["cover"] == 1.0


def test_중간_노드_이름_바뀜도_자식이_겹치면_짝이다():
    r = H.compare(BASE, relabel(BASE, "거점 통합", "센터 집약"))
    assert r["apa"] == 1.0 and r["renamed"] == 1


def test_자식이_하나뿐인_노드의_이름_바뀜은_짝이_안_된다():
    g = graph(("r", "물류 혁신", None, [1]), ("a", "거점 통합", "r", [2]), ("a1", "창고 수", "a", [2]),
              ("b", "배송 경로", "r", [3]))
    r = H.compare(g, relabel(g, "거점 통합", "센터 집약"))
    assert r["renamed"] == 0 and r["pairs"] == 3 and r["cover"] == 6 / 8
    assert r["apa"] == 2 / 3                                     # 「창고 수」 의 부모가 짝이 없다


def test_서브트리를_옮기면_옮긴_부모_관계만큼_떨어진다():
    moved = copy.deepcopy(BASE)
    for n in moved["nodes"]:
        if n["id"] == "a1":
            n["parent_id"] = "b"
    r = H.compare(BASE, moved)
    assert r["apa"] == 5 / 6 and r["moved"] == 1
    assert r["anc"] < 1.0 and r["tes"] == 1 - 1 / 12


def test_납작하게_펴면_깊이_관계가_모두_불일치():
    flat = copy.deepcopy(BASE)
    for n in flat["nodes"]:
        if n["parent_id"] not in (None, "r"):
            n["parent_id"] = "r"
    r = H.compare(BASE, flat)
    assert r["apa"] == 4 / 6 and r["moved"] == 2


def test_비슷한_이름은_짝이고_규칙D_저하는_짝이_아니다():
    a = graph(("r", "독서 경험", None, [1]), ("x", "대출 권수", "r", [2]), ("y", "집중력", "r", [3]))
    b = graph(("r", "독서 경험", None, [1]), ("x", "도서관 대출 권수", "r", [2]), ("y", "집중력 저하", "r", [3]))
    al = H.align(a, b)
    assert al["kind"].get("x") == "near"                         # 수식어 하나 더 붙은 같은 개념
    assert "y" not in al["pairs"]                                # 극성이 다르다 — 규칙 D 의 다른 개념


def test_머리말이_다르면_비슷해도_짝이_아니다():
    a = graph(("r", "혈당 부하", None, [1]))
    b = graph(("r", "혈당 스파이크", None, [1]))
    assert H.align(a, b)["pairs"] == {}


def test_겹치는_노드가_없으면_위계_지표는_없다():
    r = H.compare(graph(("r", "원예 가꾸기", None, [1])), graph(("s", "도서관 재개관", None, [1])))
    assert r["apa"] is None and r["cover"] == 0.0 and r["pa_old"] is None


def test_목록_밖_부모는_루트로_본다():
    g = graph(("r", "물류 혁신", "없는-노드", [1]), ("a", "거점 통합", "r", [2]))
    assert H.compare(g, graph(("r", "물류 혁신", None, [1]), ("a", "거점 통합", "r", [2])))["apa"] == 1.0


def test_잭나이프_분산은_같은_표본이면_0_흔들리면_양수():
    same = [BASE] * 4
    pairs = H.within(same)
    assert len(pairs) == 6 and H.jackknife_var(pairs, 4, "apa") == 0.0
    moved = copy.deepcopy(BASE)
    for n in moved["nodes"]:
        if n["id"] == "a1":
            n["parent_id"] = "b"
    mixed = H.within([BASE, BASE, BASE, moved])
    assert H.jackknife_var(mixed, 4, "apa") > 0
    m, se = H.arm_mean_se({"d1": (pairs, 4), "d2": (mixed, 4)}, "apa")
    assert 0.9 < m < 1.0 and se > 0


def test_갈래_사이_쌍은_모든_조합():
    assert len(H.cross([BASE, BASE], [BASE, BASE, BASE])) == 6
