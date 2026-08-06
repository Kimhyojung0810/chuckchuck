"""
발표 평가 채점표 v3 — 숫자 원본입니다.

`docs/발표평가_상황별_채점표_v3.xlsx` 를 코드로 동결한 것입니다. 로직은 없고 데이터만 있습니다.

**런타임에 xlsx 를 읽지 않습니다.** openpyxl 이 설치돼 있지 않고 파일명이 NFD 정규화라
리터럴 경로 open 이 실패합니다. 채점표를 고칠 때는 xlsx 와 이 파일을 같이 고칩니다
(xlsx 는 사람이 보는 원본, 이 파일은 코드가 읽는 원본).

구성은 세 층입니다:

- **상황 4종** — 같은 발표라도 학교 프로젝트와 업무 보고는 잘한 것의 정의가 다르다.
- **클러스터 7종** — 항목을 묶는 단위. 상황별 가중치 합이 100 이다.
- **세부 항목 39종** — 실제 채점 단위. 클러스터 안에서의 상대적 중요도를 갖는다.
  가중치 0 은 "그 상황에서는 평가하지 않는다" 는 뜻이다 (0점이 아니다).
"""

from __future__ import annotations

from dataclasses import dataclass

RUBRIC_VERSION = "v3"

#: 발표 상황. key 는 API·프론트가 주고받는 값, 값은 화면에 그대로 나가는 한글 라벨이다.
SITUATIONS: dict[str, str] = {
    "school_project": "학교 프로젝트 (교수 대상)",
    "product_launch": "신제품 설명 (대중 대상)",
    "work_report": "업무 보고 (상사 대상)",
    "casual_peer": "동료 간 캐주얼 PR",
}

#: 매칭에 실패했을 때 떨어질 상황. 가장 항목이 많이 살아 있는 열이라 정보 손실이 적다.
DEFAULT_SITUATION = "school_project"

#: 클러스터. 삽입 순서가 곧 리포트 표시 순서다.
CLUSTERS: dict[str, str] = {
    "content": "내용 충실도",
    "logic": "논리 구조",
    "audience": "목적·청중 적합성",
    "clarity": "언어적 명료성",
    "delivery": "음성적 전달",
    "visual": "시각자료 활용",
    "time": "시간 관리",
}

#: 클러스터 가중치(%). 상황별 합계 100.
CLUSTER_WEIGHTS: dict[str, dict[str, int]] = {
    "content": {"school_project": 26, "product_launch": 17, "work_report": 19, "casual_peer": 28},
    "logic": {"school_project": 23, "product_launch": 15, "work_report": 23, "casual_peer": 20},
    "audience": {"school_project": 8, "product_launch": 19, "work_report": 15, "casual_peer": 8},
    "clarity": {"school_project": 10, "product_launch": 12, "work_report": 8, "casual_peer": 11},
    "delivery": {"school_project": 7, "product_launch": 12, "work_report": 6, "casual_peer": 9},
    "visual": {"school_project": 13, "product_launch": 17, "work_report": 11, "casual_peer": 12},
    "time": {"school_project": 13, "product_launch": 8, "work_report": 18, "casual_peer": 12},
}

#: 항목 산출 방식.
#: det = 코드가 계산 (LLM 없음) · llm = LLM 이 채점 · na = 이 파이프라인에서 측정 불가
ITEM_SOURCES = ("det", "llm", "na")


@dataclass(frozen=True)
class RubricItem:
    """채점표의 한 줄. 불변이다 — 런타임에 기준이 바뀌면 점수가 거짓말이 된다."""

    no: int
    cluster: str
    name: str
    description: str          # 채점표 '평가 설명' 열. LLM 프롬프트에 그대로 들어간다.
    source: str               # ITEM_SOURCES 중 하나
    weights: dict[str, int]   # 상황 key → 내부 가중치 (0 이면 그 상황에서 평가 안 함)

    def weight_for(self, situation: str) -> int:
        return self.weights.get(situation, 0)


# 가중치 순서는 (학교 프로젝트, 신제품 설명, 업무 보고, 캐주얼 PR) 이다.
_SITUATION_ORDER = ("school_project", "product_launch", "work_report", "casual_peer")

# (no, cluster, name, source, 가중치 4개, description)
_ROWS: tuple[tuple, ...] = (
    (1, "content", "핵심 개념 커버리지", "det", (9, 8, 8, 6),
     "발표자료의 핵심 개념을 발화에서 실제로 다뤘는가"),
    (2, "content", "설명 깊이", "llm", (10, 6, 6, 5),
     "용어를 읽는 데 그치지 않고 의미·원리·관계까지 설명했는가"),
    (3, "content", "근거·수치·사례 제시", "llm", (9, 7, 8, 5),
     "주장에 필요한 근거·수치·사례가 제시됐는가"),
    (4, "content", "자료-발화 일치성", "det", (8, 6, 7, 4),
     "슬라이드 자료와 실제 발화 사이 모순·누락이 없는가"),
    (5, "content", "근거 없는 추가 발화", "det", (7, 5, 6, 3),
     "자료에 없는 내용을 근거 없이 임의로 덧붙이지 않았는가"),
    (6, "content", "선행연구·이론적 근거 인용", "llm", (7, 0, 0, 0),
     "관련 이론이나 선행 연구를 적절히 인용했는가"),

    (7, "logic", "핵심 주장 제시 시점", "llm", (6, 8, 9, 5),
     "발표 목적과 핵심 주장이 도입부에서 분명히 드러나는가"),
    (8, "logic", "주장-근거-결론 연결", "llm", (9, 8, 9, 6),
     "문제-원인-해결, 주장-근거-해석 관계가 논리적으로 유지되는가"),
    (9, "logic", "전제 생략·결론 점프·모순", "llm", (8, 7, 8, 5),
     "전제를 건너뛰거나 갑자기 결론으로 점프하지 않는가"),
    (10, "logic", "전환의 자연스러움", "llm", (6, 6, 6, 4),
     "슬라이드와 구간 사이 전환과 연결 표현이 논리 관계와 맞는가"),
    (11, "logic", "결론의 핵심 회수", "llm", (6, 6, 7, 4),
     "결론에서 앞의 핵심 내용을 다시 회수하는가"),
    (12, "logic", "두괄식 구조", "llm", (0, 0, 8, 0),
     "결론과 핵심 메시지를 먼저 제시하고 근거를 뒤에 배치했는가"),

    (13, "audience", "청중 수준 맞춤 설명", "llm", (7, 9, 7, 5),
     "청중의 배경지식 수준에 맞게 설명 깊이를 조절했는가"),
    (14, "audience", "목적에 맞는 강조점", "llm", (6, 9, 8, 5),
     "발표 목적(정보 전달·설득·보고 등)에 맞게 강조할 내용을 선택했는가"),
    (15, "audience", "흥미 유발·스토리텔링", "llm", (0, 9, 0, 0),
     "청중의 관심을 끄는 도입·사례·스토리 요소가 있는가"),
    (16, "audience", "실행 가능한 제안 명확성", "llm", (0, 0, 9, 0),
     "보고의 결론이 구체적인 액션 아이템으로 제시되는가"),

    (17, "clarity", "지시어 남용 여부", "det", (4, 4, 4, 3),
     "이것·저것·이런 부분 같은 불명확한 지시어 반복이 없는가"),
    (18, "clarity", "전문용어 설명 동반", "llm", (6, 8, 5, 4),
     "전문용어와 약어를 설명 없이 사용하지 않았는가"),
    (19, "clarity", "문장 길이·완결성", "det", (4, 5, 4, 3),
     "문장이 지나치게 길거나 끝맺지 못하지 않는가"),
    (20, "clarity", "표현의 의미 없는 반복", "det", (3, 4, 3, 3),
     "같은 단어나 구를 의미 없이 반복하지 않는가"),
    (21, "clarity", "핵심 구조 신호어 사용", "det", (5, 6, 5, 3),
     "첫째·반면·따라서 같은 신호어로 구조를 알려주는가"),

    (22, "delivery", "말속도 적절성", "det", (4, 6, 5, 4),
     "본인 평균 대비 급격한 과속이나 감속 없이 안정적인가"),
    (23, "delivery", "필러 빈도·위치", "det", (4, 5, 5, 4),
     "어·음·그 같은 필러가 핵심 구간 근처에 몰려 있지 않은가"),
    (24, "delivery", "휴지·침묵의 위치", "det", (3, 5, 4, 3),
     "정적이 의미 단위 전환에서 자연스럽게 쓰였는가"),
    (25, "delivery", "음량 안정성", "na", (3, 5, 4, 3),
     "음량이 일관되고 안정적인가"),
    (26, "delivery", "핵심 구간 강조", "na", (4, 7, 5, 3),
     "핵심 내용 구간에서 속도와 톤 변화로 강조했는가"),

    (27, "visual", "낭독 vs 실제 설명 구분", "det", (6, 6, 5, 3),
     "화면 문장을 그대로 읽지 않고 실제로 설명했는가"),
    (28, "visual", "슬라이드별 설명시간 균형", "det", (5, 6, 6, 3),
     "중요도 대비 슬라이드별 설명 시간 배분이 적절한가"),
    (29, "visual", "그래프·표 설명", "llm", (6, 7, 6, 3),
     "그래프의 축과 핵심 수치, 변화 방향을 말로 설명했는가"),
    (30, "visual", "슬라이드-발화 강조 일치", "det", (5, 6, 5, 3),
     "슬라이드 핵심과 발화의 강조점이 일치하는가"),

    (31, "time", "제한시간 준수", "det", (5, 6, 8, 4),
     "전체 제한시간을 지켰는가"),
    (32, "time", "구간별 시간 배분", "det", (5, 6, 7, 4),
     "도입·본론·결론의 시간 비중이 적절한가"),
    (33, "time", "핵심 슬라이드 체류시간", "det", (4, 5, 6, 3),
     "핵심 슬라이드와 보조 슬라이드의 체류 시간이 중요도에 맞는가"),

    (34, "visual", "슬라이드 정보 밀도", "det", (5, 6, 5, 3),
     "한 슬라이드에 텍스트가 과도하게 몰려 가독성을 해치지 않는가"),
    (35, "visual", "제목-본문 일치성", "llm", (5, 6, 6, 3),
     "슬라이드 제목이 본문 핵심 내용을 정확히 요약하는가"),
    (36, "visual", "목차·로드맵 슬라이드", "det", (4, 5, 5, 2),
     "청중이 전체 발표 구조를 미리 파악할 수 있게 안내했는가"),
    (37, "visual", "데이터 시각화 적절성", "llm", (6, 6, 6, 3),
     "차트와 그래프 유형이 전달하려는 데이터 성격에 적합한가"),
    (38, "visual", "출처·근거 표기", "det", (7, 4, 5, 2),
     "통계와 인용 자료에 출처가 명시되어 있는가"),
    (39, "visual", "오탈자·맞춤법", "llm", (4, 5, 5, 3),
     "슬라이드 텍스트에 오탈자나 맞춤법 오류가 없는가"),
)

ITEMS: tuple[RubricItem, ...] = tuple(
    RubricItem(
        no=no,
        cluster=cluster,
        name=name,
        description=description,
        source=source,
        weights=dict(zip(_SITUATION_ORDER, weights)),
    )
    for no, cluster, name, source, weights, description in _ROWS
)

#: 번호로 바로 찾을 때 쓴다.
ITEM_BY_NO: dict[int, RubricItem] = {item.no: item for item in ITEMS}


# ---------------------------------------------------------------------------
# 자체 검증 — 표를 손으로 고치다 어긋나면 import 시점에 바로 터지게 한다.
# 채점표가 틀린 채로 돌아가는 것보다 안 뜨는 게 낫다.
# ---------------------------------------------------------------------------

def _self_check() -> None:
    assert len(ITEMS) == 39, f"항목이 39개여야 하는데 {len(ITEMS)}개입니다"
    assert [i.no for i in ITEMS] == sorted(i.no for i in ITEMS), "항목 번호가 오름차순이 아닙니다"
    assert set(ITEM_BY_NO) == set(range(1, 40)), "항목 번호 1~39 가 빠짐없이 있어야 합니다"

    for item in ITEMS:
        assert item.cluster in CLUSTERS, f"{item.no}번 클러스터 '{item.cluster}' 가 없습니다"
        assert item.source in ITEM_SOURCES, f"{item.no}번 source '{item.source}' 가 없습니다"
        assert set(item.weights) == set(_SITUATION_ORDER), f"{item.no}번 상황 key 가 어긋납니다"

    for situation in SITUATIONS:
        total = sum(CLUSTER_WEIGHTS[c][situation] for c in CLUSTERS)
        assert total == 100, f"'{situation}' 클러스터 가중치 합이 {total} 입니다 (100 이어야 합니다)"
        # 상황마다 최소 한 항목은 살아 있어야 한다
        assert any(i.weight_for(situation) > 0 for i in ITEMS), f"'{situation}' 에 평가 항목이 없습니다"

    assert set(CLUSTER_WEIGHTS) == set(CLUSTERS), "클러스터 가중치 표와 클러스터 목록이 어긋납니다"


_self_check()


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------

def items_for(situation: str) -> list[RubricItem]:
    """그 상황에서 실제로 평가하는 항목만 (가중치 0 은 제외)."""
    return [i for i in ITEMS if i.weight_for(situation) > 0]


def items_in_cluster(cluster: str, situation: str) -> list[RubricItem]:
    """클러스터 안에서 그 상황에 살아 있는 항목."""
    return [i for i in items_for(situation) if i.cluster == cluster]


def cluster_weight(cluster: str, situation: str) -> int:
    """클러스터 가중치(%). 모르는 조합이면 0."""
    return CLUSTER_WEIGHTS.get(cluster, {}).get(situation, 0)


def situation_label(situation: str) -> str:
    return SITUATIONS.get(situation, SITUATIONS[DEFAULT_SITUATION])


#: 예전 UI 가 보내던 자유 텍스트 → 채점표 상황. 캐시된 옛 프론트와 저장된 세션 때문에 남긴다.
_LEGACY_SITUATION_ALIASES: dict[str, str] = {
    "사내 보고": "work_report",
    "업무 보고": "work_report",
    "학회·수업 발표": "school_project",
    "학회 수업 발표": "school_project",
    "학교 프로젝트": "school_project",
    "대회·ir 피칭": "product_launch",
    "대회 ir 피칭": "product_launch",
    "신제품 설명": "product_launch",
    "동료 간 캐주얼 pr": "casual_peer",
    "캐주얼 pr": "casual_peer",
}


def resolve_situation(raw: str | None) -> tuple[str, str]:
    """
    자유 텍스트나 라벨을 상황 key 로 옮긴다.

    정상 경로는 프론트가 key 를 그대로 보내는 것이다. 그래도 예전 자유 텍스트와
    한글 라벨을 받아 준다 — 캐시된 옛 JS 와 저장된 세션이 있기 때문이다.

    Returns:
        (상황 key, 안내 문구). 안내 문구는 매칭에 실패해 기본값으로 떨어졌을 때만
        채워진다. **조용히 기본값을 쓰지 않는다** — 어느 기준으로 매겼는지 화면에 남긴다.
    """
    text = str(raw or "").strip()
    if not text:
        return DEFAULT_SITUATION, (
            f"발표 상황을 안 골라서 '{situation_label(DEFAULT_SITUATION)}' 기준으로 매겼어요"
        )

    if text in SITUATIONS:
        return text, ""

    # 한글 라벨 그대로 온 경우
    for key, label in SITUATIONS.items():
        if text == label:
            return key, ""

    lowered = text.lower()
    for alias, key in _LEGACY_SITUATION_ALIASES.items():
        if alias in lowered:
            return key, ""

    # 라벨의 앞머리만 온 경우 ("학교 프로젝트" 처럼 괄호가 빠진 형태)
    for key, label in SITUATIONS.items():
        if label.split(" (")[0] in text:
            return key, ""

    return DEFAULT_SITUATION, (
        f"'{text}' 는 채점표에 없는 상황이라 '{situation_label(DEFAULT_SITUATION)}' 기준으로 매겼어요"
    )
