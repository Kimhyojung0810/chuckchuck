"""
[F-13] 발표 점수 산식입니다.

F-11 정합 판정(AlignmentDoc)과 파생 흐름 비교(FlowDiff)를 0~100 점 하나로 합칩니다.
LLM 을 부르지 않는 순수 함수 — 같은 입력이면 항상 같은 점수가 나옵니다.

설계에서 정한 것 넷:

1. **누락은 coverage 가 이미 값을 매긴다.** verdict_counts 의 missing 으로 다시
   깎으면 같은 실수를 두 번 청구하는 셈이라, 개념 하나 빠뜨렸을 때 점수가
   과민하게 무너진다. missing 은 coverage 로만 반영한다.
2. **contradiction 만 따로 뺀다.** '안 말한 것'과 '틀리게 말한 것'은 다른 실패고,
   후자는 coverage 의 분자에도 분모에도 안 잡힌다. 그래서 감점 항으로 분리하되,
   해당 개념이 자료에서 차지하던 비중(doc_weight)에 비례시킨다.
3. **justified_skip 은 가점도 감점도 아니다.** 4-class 를 나눈 이유가 그것이다.
4. **없는 지표는 0 이 아니라 '없음'이다.** 작은 자료에서는 순위상관·간선·순서가
   동시에 전부 None 일 수 있다. 0 으로 치면 멀쩡한 발표가 낙제한다. 빠진 항의
   가중치는 남은 항들에 다시 나눠준다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import AlignmentDoc, FlowDiff

#: 모든 지표가 있을 때의 배합. 합은 1.0
COMPONENT_WEIGHTS: dict[str, float] = {
    "coverage": 0.45,   # 자료가 힘준 개념을 실제로 말했나 — 가장 직접적인 신호
    "rank": 0.20,       # 자료의 비중 순위대로 발표에서도 힘을 실었나
    "edge": 0.20,       # 개념 사이 연결을 말로도 이었나 ("각각 말했지만 안 이음")
    "order": 0.15,      # 자료 순서대로 풀어냈나
}

COMPONENT_LABELS: dict[str, str] = {
    "coverage": "핵심 개념 설명",
    "rank": "비중 일치",
    "edge": "개념 연결",
    "order": "흐름 순서",
}

#: contradiction 1건의 기본 감점(점). doc_weight 로 비례 조정된다.
CONTRADICTION_UNIT_PENALTY = 12.0
#: 모순이 아무리 많아도 여기까지만 깎는다 — 나머지 잘한 것까지 지우지 않기 위해
MAX_CONTRADICTION_PENALTY = 25.0


@dataclass
class ScoreComponent:
    """점수를 이루는 항 하나. UI 가 '왜 86점인지' 그대로 설명할 수 있게 다 내보낸다."""
    key: str
    label: str
    raw: float           # 원지표 (0~1 로 정규화된 값)
    weight: float        # 재분배 후 실제 적용된 가중치
    contribution: float  # raw * weight * 100 — 이 항이 최종 점수에 보탠 점수

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "raw": round(self.raw, 4),
            "weight": round(self.weight, 4),
            "contribution": round(self.contribution, 2),
        }


@dataclass
class PresentationScore:
    """0~100 점과 그 근거."""
    score: int
    components: list[ScoreComponent] = field(default_factory=list)
    omitted: list[str] = field(default_factory=list)      # 계산 못 한 지표
    contradiction_penalty: float = 0.0
    contradiction_count: int = 0
    basis: str = "full"                                    # full | partial | coverage-only

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "components": [c.to_dict() for c in self.components],
            "omitted": list(self.omitted),
            "contradiction_penalty": round(self.contradiction_penalty, 2),
            "contradiction_count": self.contradiction_count,
            "basis": self.basis,
        }


def _from_correlation(value: float) -> float:
    """
    상관계수(-1~1)를 0~1 로 옮긴다.

    역순으로 말했으면(-1) 0 에 가깝게 떨어져야지 0 으로 잘려 신호를 잃으면 안 된다.
    """
    return max(0.0, min(1.0, (float(value) + 1.0) / 2.0))


def _unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _contradiction_penalty(doc: AlignmentDoc) -> tuple[float, int]:
    """
    모순 감점. 자료에서 비중이 컸던 개념을 틀리게 말했을수록 크게 깎는다.

    doc_weight 는 최상위가 1.0 인 상대값이라, 곁가지 개념의 모순은 자연히 가볍다.
    """
    items = [i for i in doc.items if i.verdict == "contradiction"]
    if not items:
        return 0.0, 0
    # weight 가 0 인 노드도 모순은 모순이라 최소 절반은 매긴다
    penalty = sum(
        CONTRADICTION_UNIT_PENALTY * max(0.5, _unit(i.doc_weight))
        for i in items
    )
    return min(MAX_CONTRADICTION_PENALTY, penalty), len(items)


def score_presentation(
    alignment: AlignmentDoc,
    flow: FlowDiff | None = None,
) -> PresentationScore:
    """
    정합 판정(+선택 흐름 비교) → 0~100 점.

    flow 를 주면 '흐름 순서' 항이 살아난다. 안 주면 그 가중치는 나머지에 재분배된다.
    """
    summary = alignment.summary

    # 원지표 수집 — None 은 '계산 불가'라 항 자체를 뺀다 (0 점 처리가 아니다)
    raw: dict[str, float | None] = {
        "coverage": _unit(summary.coverage),
        "rank": None if summary.rank_correlation is None
        else _from_correlation(summary.rank_correlation),
        "edge": None if summary.edge_coverage is None
        else _unit(summary.edge_coverage),
        "order": None if flow is None or flow.order_tau is None
        else _from_correlation(flow.order_tau),
    }

    present = {k: v for k, v in raw.items() if v is not None}
    omitted = sorted(k for k, v in raw.items() if v is None)

    if not present:
        # coverage 는 항상 float 이라 여기 오지 않지만, 계약이 바뀌어도 안 터지게
        return PresentationScore(score=0, omitted=omitted, basis="coverage-only")

    # 빠진 항의 가중치를 남은 항에 비례 재분배
    total_weight = sum(COMPONENT_WEIGHTS[k] for k in present)
    components: list[ScoreComponent] = []
    base = 0.0
    for key in COMPONENT_WEIGHTS:  # 표시 순서를 배합표 순서로 고정
        if key not in present:
            continue
        weight = COMPONENT_WEIGHTS[key] / total_weight
        contribution = present[key] * weight * 100.0
        base += contribution
        components.append(ScoreComponent(
            key=key,
            label=COMPONENT_LABELS[key],
            raw=present[key],
            weight=weight,
            contribution=contribution,
        ))

    penalty, n_contradiction = _contradiction_penalty(alignment)
    score = int(round(max(0.0, min(100.0, base - penalty))))

    if not omitted:
        basis = "full"
    elif list(present) == ["coverage"]:
        basis = "coverage-only"
    else:
        basis = "partial"

    return PresentationScore(
        score=score,
        components=components,
        omitted=omitted,
        contradiction_penalty=penalty,
        contradiction_count=n_contradiction,
        basis=basis,
    )
