"""
F-22 또래 기준의 규칙을 고정합니다.

- 백분위는 선형 보간이고, n 이 최소치 미만인 버킷은 아예 나오지 않는다
- 기준이 없으면 숫자를 지어내지 않고 「아직 비교할 만큼 모이지 않았어요」 라고 한다
- 방향(클수록 좋은가)이 지표마다 맞다
"""

from __future__ import annotations

import pytest

from chuckchuck.contracts import PeerNorm
from chuckchuck.f22_peer_norm import (
    MIN_N,
    NOT_ENOUGH,
    bucket_key,
    build_norms,
    describe,
    duration_band,
    load_norms,
    lookup,
    percentile,
    percentile_of,
    save_norms,
    session_metrics,
)


def test_백분위는_선형_보간이다():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(xs, 50) == 3.0
    assert percentile(xs, 25) == 2.0
    assert percentile(xs, 10) == pytest.approx(1.4)
    assert percentile([7.0], 90) == 7.0
    with pytest.raises(ValueError):
        percentile([], 50)


@pytest.mark.parametrize(("dur", "band"), [(None, "any"), (0, "any"), (1, "short"), (3, "short"), (5, "mid"), (10, "long"), (30, "xl")])
def test_발표_길이_구간(dur, band):
    assert duration_band(dur) == band


def test_버킷은_상황과_길이다():
    assert bucket_key({"situation": "학회", "duration_min": 10}) == "학회|long"
    assert bucket_key({}) == "any|any"
    assert bucket_key(None) == "any|any"


def test_세션_지표는_구할_수_있는_것만_낸다():
    m = session_metrics(
        transcript={"duration_sec": 120}, pace={"avg_chars_per_min": 300},
        habits={"filler_cnt": 6, "repeat_cnt": 2, "pause_cnt": 0},
        alignment={"summary": {"coverage": 0.8}}, flow={"order_tau": 0.5},
    )
    assert m == {"chars_per_min": 300.0, "filler_per_min": 3.0, "repeat_per_min": 1.0,
                 "pause_per_min": 0.0, "coverage": 0.8, "order_tau": 0.5}
    assert session_metrics(habits={"filler_cnt": 6}) == {}          # 길이를 모르면 분당 지표를 안 낸다
    assert session_metrics(pace={"avg_chars_per_min": 0}) == {}     # 0 은 "없음" 이다


def test_n_이_모자란_버킷은_나오지_않는다():
    many = [("학회|long", {"filler_per_min": float(i)}) for i in range(MIN_N)]
    few = [("면접|short", {"filler_per_min": 1.0})] * (MIN_N - 1)
    norms = build_norms(many + few, built_at=1.0)
    assert [(n.bucket, n.metric, n.n) for n in norms] == [("학회|long", "filler_per_min", MIN_N)]
    n = norms[0]
    assert (n.p10, n.p50, n.p90) == (pytest.approx(1.9), pytest.approx(9.5), pytest.approx(17.1))
    assert lookup(norms, "면접|short", "filler_per_min") is None
    assert lookup(norms, "학회|xl", "filler_per_min") is None       # 다른 길이 구간으로 넘어가지 않는다


def test_길이_구간이_없으면_같은_상황의_any_로_떨어진다():
    norms = build_norms([("학회|any", {"coverage": i / 20}) for i in range(MIN_N)], built_at=1.0)
    assert lookup(norms, "학회|long", "coverage") is not None


def test_percentile_of_와_describe_방향():
    n = PeerNorm(metric="filler_per_min", bucket="b", n=30, p10=1, p25=2, p50=3, p75=4, p90=5)
    assert percentile_of(n, 3) == 50
    assert percentile_of(n, 2.5) == 38
    assert percentile_of(n, 0) == 5 and percentile_of(n, 9) == 95
    # 간투어는 적을수록 좋다 → p10 (적은 쪽) 이 상위 10%
    assert describe([n], "b", "filler_per_min", 1) == "또래 상위 10% (같은 조건 30명 기준)"
    good = PeerNorm(metric="coverage", bucket="b", n=30, p10=.2, p25=.4, p50=.6, p75=.8, p90=.9)
    assert describe([good], "b", "coverage", 0.9) == "또래 상위 10% (같은 조건 30명 기준)"
    assert describe([good], "b", "coverage", None) == NOT_ENOUGH
    assert describe([], "b", "coverage", 0.9) == NOT_ENOUGH


def test_저장_왕복(tmp_path):
    norms = build_norms([("a|any", {"coverage": i / 20}) for i in range(MIN_N)], built_at=1.0)
    path = tmp_path / "norms" / "percentile_table.json"
    save_norms(path, norms, sessions=MIN_N, buckets={"a|any": MIN_N})
    assert [n.to_dict() for n in load_norms(path)] == [n.to_dict() for n in norms]
    assert load_norms(tmp_path / "없음.json") == []
