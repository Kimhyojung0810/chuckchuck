"""
F-14 채점표 채점 테스트입니다.

**집계 공식은 반드시 고정한다.** 이게 틀리면 리포트 전체가 거짓말이 된다.

어느 함수를 때리는지가 중요하다:

- 집계 불변식은 `_aggregate(situation, items)` 를 **직접** 부른다. 항목 점수를 손으로
  만들어 넣는다. `score_rubric` 으로 돌리면 25·26 번이 영구 `unmeasured` 이고
  MockLLM 이 65~85 만 돌려줘서 만점·정확 비교가 아예 불가능하다.
- LLM 정규화와 퇴화 경로만 `score_rubric` 을 쓴다.
"""

from __future__ import annotations

import json

import pytest

from chuckchuck import rubric_v3
from chuckchuck.contracts import RubricItemScore, RubricScore, Transcript, Word
from chuckchuck.f13_score import PresentationScore, ScoreComponent
from chuckchuck.f14_rubric import (
    _aggregate,
    _normalize_llm,
    from_legacy_score,
    score_rubric,
)
from chuckchuck.providers.llm_base import LLMProvider

SITUATIONS = tuple(rubric_v3.SITUATIONS)


def make_items(
    situation: str,
    *,
    scores: dict[int, int] | None = None,
    default: int = 100,
    unmeasured: set[int] | None = None,
) -> list[RubricItemScore]:
    """
    39개 항목을 손으로 만든다.

    가중치 0 인 항목은 자동으로 `situation_excluded`, `unmeasured` 에 넣은 번호는
    `unmeasured`, 나머지는 `scored` 다. n/a 항목(25·26)은 기본으로 못 잰 것으로 둔다.
    """
    scores = scores or {}
    unmeasured = set(unmeasured or set())
    unmeasured |= {i.no for i in rubric_v3.ITEMS if i.source == "na"}

    out: list[RubricItemScore] = []
    for item in rubric_v3.ITEMS:
        weight = item.weight_for(situation)
        if weight == 0:
            status, score = "situation_excluded", 0
        elif item.no in unmeasured:
            status, score = "unmeasured", 0
        else:
            status, score = "scored", scores.get(item.no, default)
        out.append(RubricItemScore(
            no=item.no, cluster=item.cluster, name=item.name, status=status,
            score=score, weight=weight, source=item.source,
            evidence="근거" if status == "scored" else "",
        ))
    return out


# ---------------------------------------------------------------------------
# 채점표 자체
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("situation", SITUATIONS)
def test_채점표_가중치_합이_100이다(situation):
    total = sum(rubric_v3.cluster_weight(c, situation) for c in rubric_v3.CLUSTERS)
    assert total == 100


def test_39개_항목이_전부_정의됐다():
    assert len(rubric_v3.ITEMS) == 39
    assert {i.no for i in rubric_v3.ITEMS} == set(range(1, 40))
    assert all(i.cluster in rubric_v3.CLUSTERS for i in rubric_v3.ITEMS)
    assert all(i.source in rubric_v3.ITEM_SOURCES for i in rubric_v3.ITEMS)
    assert all(i.description for i in rubric_v3.ITEMS), "평가 설명이 비면 LLM 기준이 사라진다"


def test_결정_채점기가_채점표의_det_항목과_정확히_맞는다():
    from chuckchuck._rubric_det import DET_SCORERS

    assert {i.no for i in rubric_v3.ITEMS if i.source == "det"} == set(DET_SCORERS)


# ---------------------------------------------------------------------------
# 집계 공식 — _aggregate 직접 호출
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("situation", SITUATIONS)
def test_모든_항목이_만점이면_100점이다(situation):
    assert _aggregate(situation, make_items(situation, default=100)).score == 100


@pytest.mark.parametrize("situation", SITUATIONS)
def test_모든_항목이_0점이면_0점이다(situation):
    assert _aggregate(situation, make_items(situation, default=0)).score == 0


@pytest.mark.parametrize("situation", SITUATIONS)
def test_클러스터_가중치_합계가_1로_정규화된다(situation):
    got = _aggregate(situation, make_items(situation))
    live = [c for c in got.clusters if c.status == "scored"]
    assert abs(sum(c.effective_weight for c in live) - 1.0) < 1e-9

    # 클러스터가 통째로 빠져도 남은 것들의 합은 여전히 1.0 이어야 한다
    dead = {i.no for i in rubric_v3.ITEMS if i.cluster == "delivery"}
    dropped = _aggregate(situation, make_items(situation, unmeasured=dead))
    live2 = [c for c in dropped.clusters if c.status == "scored"]
    assert abs(sum(c.effective_weight for c in live2) - 1.0) < 1e-9


@pytest.mark.parametrize("situation", SITUATIONS)
def test_기여도의_합이_최종점수와_같다(situation):
    got = _aggregate(situation, make_items(situation, default=73, scores={1: 20, 8: 95}))
    assert got.score == round(sum(c.contribution for c in got.clusters))


def test_아무것도_안_빠지면_채점표_시트와_같은_가중치다():
    """빠진 게 없으면 유효 가중치가 채점표의 클러스터 가중치 ÷ 100 과 정확히 같다."""
    got = _aggregate("school_project", make_items("school_project"))
    for c in got.clusters:
        if c.status == "scored":
            assert abs(c.effective_weight - c.weight / 100) < 1e-9


def test_상황별로_다른_점수가_나온다():
    """같은 항목 점수인데 상황이 다르면 최종도 달라야 한다 — 가중치가 진짜 붙었는지."""
    scores = {i.no: (i.no * 7) % 101 for i in rubric_v3.ITEMS}
    got = {s: _aggregate(s, make_items(s, scores=scores)).score for s in SITUATIONS}
    assert len(set(got.values())) > 1, f"상황이 점수에 반영되지 않는다: {got}"


def test_상황_제외_항목은_점수에_영향이_없다():
    """6번(선행연구)은 신제품 설명에서 가중치 0 이라 0점이든 100점이든 최종이 같아야 한다."""
    situation = "product_launch"
    low = _aggregate(situation, make_items(situation, scores={6: 0}))
    high = _aggregate(situation, make_items(situation, scores={6: 100}))
    assert low.score == high.score
    assert 6 in low.excluded and 6 not in low.unmeasured


def test_측정불가는_0점이_아니다():
    """25·26 을 빼도 음성 전달 평균이 떨어지지 않는다 — 가중치에서 빠질 뿐이다."""
    got = _aggregate("school_project", make_items("school_project", default=80))
    delivery = got.cluster("delivery")
    assert delivery.status == "scored"
    assert delivery.average == pytest.approx(80.0), "못 잰 항목이 0점으로 섞이면 평균이 내려간다"
    assert delivery.item_nos == [22, 23, 24]


def test_제외와_측정불가는_다른_필드다():
    got = _aggregate("school_project", make_items("school_project", unmeasured={1}))
    assert 1 in got.unmeasured and 1 not in got.excluded
    assert set(got.excluded) == {12, 15, 16}    # 학교 프로젝트에서 평가하지 않는 항목
    assert not set(got.excluded) & set(got.unmeasured)


def test_음성_클러스터가_통째로_빠져도_점수가_나온다():
    """모의 STT 시나리오 — 22·23·24 까지 못 재면 delivery 가 빠지고 나머지 6개로 재분배된다."""
    dead = {i.no for i in rubric_v3.ITEMS if i.cluster == "delivery"}
    got = _aggregate("school_project", make_items("school_project", default=90, unmeasured=dead))
    assert got.cluster("delivery").status == "omitted"
    assert got.cluster("delivery").effective_weight == 0.0
    assert got.score == 90, "남은 클러스터가 전부 90점이면 재분배 후에도 90점이어야 한다"
    assert got.basis == "partial"


def test_잴_수_있는_건_다_쟀으면_basis_가_full_이다():
    """25·26 만 못 쟀을 때는 full — 영구 측정 불가가 basis 를 영영 묶으면 경고가 소음이 된다."""
    got = _aggregate("school_project", make_items("school_project"))
    assert set(got.unmeasured) == {25, 26}
    assert got.basis == "full"


def test_잴_수_있었어야_할_걸_못_쟀으면_partial_이다():
    got = _aggregate("school_project", make_items("school_project", unmeasured={1}))
    assert got.basis == "partial"


def test_한_항목만_남아도_그_항목이_클러스터_평균이_된다():
    others = {i.no for i in rubric_v3.ITEMS if i.cluster == "time" and i.no != 31}
    got = _aggregate("school_project", make_items("school_project", scores={31: 40}, unmeasured=others))
    assert got.cluster("time").average == pytest.approx(40.0)
    assert got.cluster("time").item_nos == [31]


# ---------------------------------------------------------------------------
# 퇴화 경로
# ---------------------------------------------------------------------------

def test_아무것도_못_재면_0으로_나누지_않는다():
    dead = {i.no for i in rubric_v3.ITEMS}
    got = _aggregate("school_project", make_items("school_project", unmeasured=dead))
    assert got.score == 0
    assert all(c.status == "omitted" for c in got.clusters)
    assert all(c.effective_weight == 0.0 for c in got.clusters)
    assert got.note, "왜 0점인지 안내가 있어야 한다"


def test_입력이_아무것도_없어도_터지지_않는다():
    got = score_rubric(llm="mock")
    assert got.score == 0
    assert got.basis == "partial"
    assert all(c.status == "omitted" for c in got.clusters)
    assert got.note


def test_알_수_없는_상황은_기본값으로_떨어지고_기록된다():
    key, note = rubric_v3.resolve_situation("아무거나")
    assert key == rubric_v3.DEFAULT_SITUATION
    assert note, "조용히 기본값을 쓰면 어느 기준으로 매겼는지 알 수 없다"

    assert rubric_v3.resolve_situation("school_project") == ("school_project", "")
    assert rubric_v3.resolve_situation("사내 보고")[0] == "work_report"
    assert rubric_v3.resolve_situation(None)[0] == rubric_v3.DEFAULT_SITUATION


def test_상황을_못_알아들으면_결과_note_에_남는다():
    got = score_rubric(situation="듣도보도 못한 상황", llm="mock")
    assert "듣도보도" in got.note


# ---------------------------------------------------------------------------
# LLM 응답 정규화
# ---------------------------------------------------------------------------

def test_근거_없는_LLM_점수는_버려진다():
    got = _normalize_llm({"items": [
        {"no": 2, "score": 90, "evidence": "", "note": "근거 없음"},
        {"no": 3, "score": 80, "evidence": "실제 발화에서 가져온 문장이에요", "note": "좋아요"},
    ]}, [2, 3])
    assert 2 not in got, "근거 없는 숫자는 안 매긴 것만 못하다"
    assert got[3][0] == 80


def test_범위_밖_점수는_클램프된다():
    got = _normalize_llm({"items": [
        {"no": 2, "score": 150, "evidence": "발표에서 그대로 가져온 문장이에요"},
        {"no": 3, "score": -20, "evidence": "발표에서 그대로 가져온 문장이에요"},
    ]}, [2, 3])
    assert got[2][0] == 100 and got[3][0] == 0


def test_모르는_항목번호는_버려진다():
    got = _normalize_llm({"items": [
        {"no": 99, "score": 100, "evidence": "발표에서 그대로 가져온 문장이에요"},
        {"no": 2, "score": 70, "evidence": "발표에서 그대로 가져온 문장이에요"},
    ]}, [2, 3])
    assert set(got) == {2}


def test_망가진_응답은_조용히_버린다():
    assert _normalize_llm({}, [2]) == {}
    assert _normalize_llm({"items": ["문자열"]}, [2]) == {}
    assert _normalize_llm({"items": [{"no": "둘", "score": 70, "evidence": "발표에서 그대로 가져온 문장이에요"}]}, [2]) == {}
    assert _normalize_llm({"items": [{"no": 2, "score": "높음", "evidence": "발표에서 그대로 가져온 문장이에요"}]}, [2]) == {}


# ---------------------------------------------------------------------------
# LLM 부분 실패
# ---------------------------------------------------------------------------

class _HalfBrokenLLM(LLMProvider):
    """논리 묶음만 계속 망가진 응답을 내는 가짜 LLM."""

    name = "half-broken"

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        nos = [
            int(line[3:line.index(")")])
            for line in user.splitlines()
            if line.startswith("- (") and ")" in line and line[3:line.index(")")].isdigit()
        ]
        if 8 in nos:                       # 논리 묶음
            return "JSON 아님, 미안해요"
        return json.dumps(
            {"items": [{"no": n, "score": 77, "evidence": f"{n}번 근거 인용"} for n in nos]},
            ensure_ascii=False,
        )


def test_LLM_실패한_묶음만_빠진다():
    transcript = Transcript(
        full_text="오늘은 세 가지를 말씀드릴게요. 첫째 문제입니다. 따라서 이렇게 정리했어요.",
        words=[Word(text=w, start_sec=i, end_sec=i + 1) for i, w in enumerate("가 나 다 라".split())],
        provider="ax",
        duration_sec=120.0,
    )
    got = score_rubric(situation="school_project", transcript=transcript, llm=_HalfBrokenLLM())

    logic = {i.no for i in rubric_v3.ITEMS if i.cluster == "logic"}
    for item in got.items:
        if item.no in logic and item.weight > 0:
            assert item.status == "unmeasured", f"{item.no}번은 묶음이 죽었으니 못 잰 것이어야 한다"
    assert got.item(2).status == "scored" and got.item(2).score == 77   # 내용 묶음은 살아남는다
    assert got.cluster("logic").status == "omitted"
    assert got.score > 0


# ---------------------------------------------------------------------------
# 직렬화 · 폴백
# ---------------------------------------------------------------------------

def test_직렬화가_계약을_지킨다():
    got = _aggregate("school_project", make_items("school_project"))
    d = got.to_dict()
    assert set(d) == {
        "score", "situation", "situation_label", "rubric_version", "clusters",
        "items", "excluded", "unmeasured", "basis", "model", "note",
    }
    assert set(d["clusters"][0]) == {
        "key", "name", "weight", "effective_weight", "average",
        "contribution", "item_nos", "status",
    }
    assert set(d["items"][0]) == {
        "no", "cluster", "name", "status", "score", "weight", "source", "evidence", "note",
    }
    # JSON 으로 나갔다 돌아와도 같아야 한다 — 프론트가 그대로 받는 모양이다
    assert RubricScore.from_dict(json.loads(json.dumps(d))).to_dict() == d


def test_폴백_변환이_프론트_계약을_지킨다():
    legacy = PresentationScore(
        score=71,
        components=[
            ScoreComponent(key="coverage", label="핵심 개념 설명", raw=0.8, weight=0.55, contribution=44.0),
            ScoreComponent(key="rank", label="비중 일치", raw=0.6, weight=0.45, contribution=27.0),
        ],
        basis="partial",
    )
    got = from_legacy_score(legacy, "school_project")
    assert got.score == 71
    assert got.rubric_version == "v3-fallback", "폴백인 걸 숨기면 안 된다"
    assert [c.average for c in got.clusters] == [80.0, 60.0], "0~1 을 0~100 으로 안 바꾸면 막대가 1% 로 그려진다"
    assert abs(sum(c.effective_weight for c in got.clusters) - 1.0) < 1e-9
    assert set(got.unmeasured) == set(range(1, 40))
    assert got.basis == "partial"
    assert got.note


# ---------------------------------------------------------------------------
# 실 LLM(solar) 응답에서 실제로 나온 실패 모양들
# ---------------------------------------------------------------------------

def test_score_키가_없으면_버린다():
    """
    예전에는 없는 score 를 0 으로 채웠다. 그러면 모델이 판단조차 안 한 항목이
    '0점 = 아예 안 했다' 로 둔갑해서, 안 매긴 것보다 나쁜 거짓말이 된다.
    """
    got = _normalize_llm({"items": [
        {"no": 2, "evidence": "발표에서 그대로 가져온 문장이에요", "note": "판단 못 함"},
        {"no": 3, "score": 0, "evidence": "발표에서 그대로 가져온 문장이에요"},
    ]}, [2, 3])
    assert 2 not in got, "score 가 없으면 채점한 게 아니다"
    assert got[3][0] == 0, "0점은 '안 했다'는 진짜 판정이라 살려 둔다"


def test_항목_설명을_되뱉은_근거는_버린다():
    """solar 가 프롬프트의 항목 설명을 근거 자리에 복사하고 0점을 준 적이 있다."""
    item = rubric_v3.ITEM_BY_NO[7]
    got = _normalize_llm({"items": [
        {"no": 7, "score": 0, "evidence": f"{item.name}: {item.description}"},
        {"no": 8, "score": 85, "evidence": "안녕하세요 오늘은 IMU2CLIP 논문 리뷰를 시작하겠습니다"},
    ]}, [7, 8])
    assert 7 not in got, "프롬프트 메아리는 근거가 아니다"
    assert got[8][0] == 85


def test_너무_짧은_근거는_버린다():
    got = _normalize_llm({"items": [
        {"no": 2, "score": 90, "evidence": "좋음"},
        {"no": 3, "score": 90, "evidence": "발표에서 그대로 가져온 문장이에요"},
    ]}, [2, 3])
    assert set(got) == {3}
