"""
F-07 **위계 안정성 잣대** (2026-09-30, WP-C2) — 같은 덱·같은 개념 입력으로 두 번 만든 개념 그래프의 위계가 얼마나 같은가.

왜 새 잣대인가: graph_ab(09-29)·wpc_eval prompt_ab(09-30)의 「부모 일치율」 은 이름이 같은 노드끼리 부모 **이름**이 같은지 셌다.
루트 이름 하나가 바뀌면(제품 대조군 「공강」↔「틈새」) 그 밑 자식 전부가 불일치가 되어 덱 하나가 0 이 된다 — 위계는 그대로인데.
표본 2개 A/B 에서 예시 낱말 교체가 0.707 → 0.473 으로 「떨어진」 것에 이 몫이 섞여 있었다 (09-30 실측: 제품 대조군 0.917 → 0.0 이
루트 이름 한 번 바뀐 것뿐). 여기서는 노드를 먼저 짝짓고 **짝의 부모가 짝인지** 센다:

    ① 같은 이름 (`_graph_items.label_keys` — 조사 「의」·띄어쓰기만 다른 이름)
    ② 비슷한 이름 — 머리말이 통하고(`head_match` ≥ NEAR_MIN) 극성이 같다. 「집중력」·「집중력 저하」 는 규칙 D 가 부모·자식으로
       두는 다른 개념이라 짝이 아니다.
    ③ 이름 바뀜 — 남은 노드끼리 **짝지은 자식이 둘 이상, 적은 쪽 자식의 절반 이상** 겹치면 같은 자리의 노드다. 루트 이름 바뀜은
       여기서 짝이 되어 「이름 바꿈 1건」 이 된다 (자식 전부 불일치가 아니다). 짝이 늘면 위로 한 번 더 돈다 (손자 → 자식 → 루트).

두 그래프마다 재는 것:
    apa     정렬 부모 일치 — 짝 (x, y) 중 부모도 서로 짝이거나 둘 다 루트인 비율. **위계 안정성의 주 지표.**
    anc     조상 집합 자카드 평균 — 짝마다 조상(짝으로 옮긴) 집합의 자카드. 한 단 옮김은 부분 점수를 받는다.
    cover   짝 덮음 = 2·짝 / (a 노드 + b 노드). 노드 **집합**이 얼마나 같은가 — 위계와 따로 본다.
    tes     편집 유사도 = 1 − (지운 노드 + 더한 노드 + 이름 바꿈(③) + 옮김(부모 불일치)) / (a 노드 + b 노드).
            루트 이름 바뀜은 1건, 자식 5개가 딴 부모로 가면 5건.
    pa_old  옛 부모 일치율 (graph_ab·wpc_eval 과 같은 잣대) — 견주기용.

LLM·파일 없이 도는 순수 함수다 (tests/test_hier_stab.py). A/B 하네스는 `graph_ab2.py`.
"""

from __future__ import annotations

import math
from collections import defaultdict
from itertools import combinations

from chuckchuck import _claim_rules as R
from chuckchuck import _graph_items as GI

#: ② 비슷한 이름으로 짝지을 문턱 — `head_match` 는 두 쪽 변별 낱말이 서로 덮는 비율의 작은 값 (「대출 권수」↔「도서관 대출 권수」 0.67).
NEAR_MIN = 0.6
#: ③ 이름 바뀜 — 겹친 자식이 이만큼 이상이고, 적은 쪽 자식 수의 이 비율 이상.
RENAME_MIN_CHILDREN = 2
RENAME_MIN_SHARE = 0.5


def _key(label: str) -> str:
    return GI.label_keys(label or "")[1]


class _Tree:
    """그래프 dict → id·이름·부모·자식. 목록 밖 부모는 루트로 본다 (그래프 계약상 없지만 방어)."""

    def __init__(self, g: dict):
        nodes = [n for n in g.get("nodes") or [] if isinstance(n, dict) and n.get("id")]
        self.ids = [n["id"] for n in nodes]
        self.label = {n["id"]: str(n.get("label") or "") for n in nodes}
        self.slides = {n["id"]: set(n.get("slide_nos") or []) for n in nodes}
        known = set(self.ids)
        self.parent = {n["id"]: (n.get("parent_id") if n.get("parent_id") in known else None) for n in nodes}
        self.children: dict[str, list[str]] = defaultdict(list)
        for c, p in self.parent.items():
            if p is not None:
                self.children[p].append(c)

    def ancestors(self, nid: str) -> list[str]:
        out, cur, seen = [], self.parent.get(nid), {nid}
        while cur is not None and cur not in seen:
            out.append(cur)
            seen.add(cur)
            cur = self.parent.get(cur)
        return out


def _near_score(a: str, b: str) -> float:
    if R.polarity(a) != R.polarity(b):
        return 0.0
    return GI.head_match(a, b)


def _slide_jac(x: set, y: set) -> float:
    return len(x & y) / len(x | y) if (x or y) else 0.0


def align(ga: dict, gb: dict) -> dict:
    """
    두 그래프의 노드 짝 → {"pairs": {a id: b id}, "kind": {a id: same|near|renamed}}. 한 노드는 많아야 한 짝이다.
    같은 점수면 걸친 장이 더 겹치는 쪽, 그다음 앞에 적힌 쪽 (결정적).
    """
    A, B = _Tree(ga), _Tree(gb)
    pairs: dict[str, str] = {}
    kind: dict[str, str] = {}
    used_b: set[str] = set()

    # ① 같은 이름
    b_by_key: dict[str, list[str]] = defaultdict(list)
    for y in B.ids:
        b_by_key[_key(B.label[y])].append(y)
    for x in A.ids:
        k = _key(A.label[x])
        if not k:
            continue
        free = [y for y in b_by_key.get(k, []) if y not in used_b]
        if free:
            y = max(free, key=lambda v: (_slide_jac(A.slides[x], B.slides[v]), -B.ids.index(v)))
            pairs[x], kind[x] = y, "same"
            used_b.add(y)

    # ② 비슷한 이름 — 남은 것끼리 점수 순으로
    cands = []
    for i, x in enumerate(A.ids):
        if x in pairs:
            continue
        for j, y in enumerate(B.ids):
            if y in used_b:
                continue
            sc = _near_score(A.label[x], B.label[y])
            if sc >= NEAR_MIN:
                cands.append((-sc, -_slide_jac(A.slides[x], B.slides[y]), i, j, x, y))
    for *_, x, y in sorted(cands):
        if x not in pairs and y not in used_b:
            pairs[x], kind[x] = y, "near"
            used_b.add(y)

    # ③ 이름 바뀜 — 짝지은 자식이 겹치는 남은 노드끼리. 짝이 늘면 한 단 위를 다시 본다
    while True:
        best = []
        for i, x in enumerate(A.ids):
            if x in pairs or not A.children.get(x):
                continue
            mapped = {pairs[c] for c in A.children[x] if c in pairs}
            if len(mapped) < RENAME_MIN_CHILDREN:
                continue
            for j, y in enumerate(B.ids):
                if y in used_b or not B.children.get(y):
                    continue
                ov = len(mapped & set(B.children[y]))
                small = min(len(A.children[x]), len(B.children[y]))
                if ov >= RENAME_MIN_CHILDREN and ov >= RENAME_MIN_SHARE * small:
                    best.append((-ov, -_slide_jac(A.slides[x], B.slides[y]), i, j, x, y))
        added = False
        for *_, x, y in sorted(best):
            if x not in pairs and y not in used_b:
                pairs[x], kind[x] = y, "renamed"
                used_b.add(y)
                added = True
        if not added:
            break
    return {"pairs": pairs, "kind": kind}


def pa_old(ga: dict, gb: dict) -> float | None:
    """옛 부모 일치율 — 이름이 같은 노드 중 부모 **이름**이 같은 비율 (graph_ab.stability 와 같은 잣대)."""
    ka = {_key(n["label"]): n for n in ga.get("nodes") or []}
    kb = {_key(n["label"]): n for n in gb.get("nodes") or []}
    common = set(ka) & set(kb)
    la = {n["id"]: _key(n["label"]) for n in ga.get("nodes") or []}
    lb = {n["id"]: _key(n["label"]) for n in gb.get("nodes") or []}
    if not common:
        return None
    same = sum(1 for k in common if la.get(ka[k].get("parent_id")) == lb.get(kb[k].get("parent_id")))
    return same / len(common)


def compare(ga: dict, gb: dict) -> dict:
    """두 그래프의 위계·노드 안정성 (모듈 docstring 의 지표). 짝이 하나도 없으면 apa·anc 는 None."""
    A, B = _Tree(ga), _Tree(gb)
    al = align(ga, gb)
    pairs, kind = al["pairs"], al["kind"]
    na, nb = len(A.ids), len(B.ids)
    agree, anc = 0, []
    for x, y in pairs.items():
        px, py = A.parent[x], B.parent[y]
        if (px is None and py is None) or (px is not None and pairs.get(px) == py):
            agree += 1
        sa = {pairs.get(u, ("a", u)) for u in A.ancestors(x)}
        sb = set(B.ancestors(y))
        anc.append(1.0 if not sa and not sb else len(sa & sb) / len(sa | sb))
    m = len(pairs)
    renamed = sum(1 for v in kind.values() if v == "renamed")
    moved = m - agree
    edits = (na - m) + (nb - m) + renamed + moved
    ka = {_key(A.label[x]) for x in A.ids}
    kb = {_key(B.label[y]) for y in B.ids}
    return {
        "apa": agree / m if m else None,
        "anc": sum(anc) / m if m else None,
        "cover": 2 * m / (na + nb) if na + nb else None,
        "tes": 1 - edits / (na + nb) if na + nb else None,
        "pa_old": pa_old(ga, gb),
        "jaccard": len(ka & kb) / len(ka | kb) if ka | kb else None,
        "pairs": m, "same": sum(1 for v in kind.values() if v == "same"),
        "near": sum(1 for v in kind.values() if v == "near"), "renamed": renamed, "moved": moved,
        "nodes": (na, nb),
    }


# ---------------------------------------------------------------------------
# 묶음 — 한 갈래 표본들 · 두 갈래 사이 · 잭나이프 표준오차
# ---------------------------------------------------------------------------

FIELDS = ("apa", "anc", "cover", "tes", "pa_old", "jaccard")


def within(samples: list[dict]) -> list[tuple[int, int, dict]]:
    """한 갈래 표본끼리 모든 쌍 (i < j)."""
    return [(i, j, compare(samples[i], samples[j])) for i, j in combinations(range(len(samples)), 2)]


def cross(xs: list[dict], ys: list[dict]) -> list[tuple[int, int, dict]]:
    """두 갈래 표본 사이 모든 쌍 — 갈래가 위계를 **바꿨는지** 본다 (같은 분포면 갈래 안 일치와 같아야 한다)."""
    return [(i, j, compare(x, y)) for i, x in enumerate(xs) for j, y in enumerate(ys)]


def mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def sd(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def pair_mean(pairs: list[tuple[int, int, dict]], field: str, drop: int | None = None) -> float | None:
    return mean(r[field] for i, j, r in pairs if drop not in (i, j))


def jackknife_var(pairs: list[tuple[int, int, dict]], n: int, field: str) -> float | None:
    """
    쌍 평균(U-통계량)의 잭나이프 분산 — 표본 하나씩 빼고 남은 쌍의 평균이 얼마나 흔들리나. 표본 n 개가 한 덱 한 갈래다.
    쌍끼리는 표본을 나눠 가져 독립이 아니라서, 쌍 값의 SD/√쌍수 는 흔들림을 작게 잰다.
    """
    if n < 3:
        return None
    loo = [pair_mean(pairs, field, drop=k) for k in range(n)]
    loo = [x for x in loo if x is not None]
    if len(loo) < 2:
        return None
    m = sum(loo) / len(loo)
    return (len(loo) - 1) / len(loo) * sum((x - m) ** 2 for x in loo)


def arm_mean_se(per_deck: dict[str, tuple[list, int]], field: str) -> tuple[float | None, float | None]:
    """덱마다 쌍 평균 → 덱 평균. 표준오차는 덱마다 잭나이프 분산을 더해 √ / 덱 수 (덱은 두 갈래가 같아 짝 비교에서 빠진다)."""
    means, vars_ = [], []
    for pairs, n in per_deck.values():
        m = pair_mean(pairs, field)
        if m is None:
            continue
        means.append(m)
        vars_.append(jackknife_var(pairs, n, field))
    if not means:
        return None, None
    se = math.sqrt(sum(v for v in vars_ if v is not None)) / len(means) if all(v is not None for v in vars_) else None
    return sum(means) / len(means), se
