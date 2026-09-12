"""
F-22 · 또래 기준 — 세션 코퍼스에서 뽑은 백분위로 "또래 상위 N%" 를 말한다.

라벨이 필요 없는 순수 통계다. 동의한 세션의 F-05·F-11·F-17·F-18 산출물에서 지표를
뽑아 (발표 상황 × 발표 길이) 버킷별 p10/p25/p50/p75/p90 을 만든다.

**n 이 MIN_N 미만인 버킷은 만들지 않는다.** 세 명의 평균을 "또래" 라고 부르면 리포트가
거짓말이 된다 — 그때는 `NOT_ENOUGH` 문장을 그대로 화면에 낸다.

DEV_POLICY §4: 다른 F-모듈을 import 하지 않는다. 입력은 contracts 의 dict/dataclass.

    samples = [(bucket_key(ctx), session_metrics(transcript=t, pace=p, habits=h, alignment=a, flow=f)), ...]
    norms = build_norms(samples)
    describe(norms, bucket_key(ctx), "filler_per_min", 3.2, higher_is_better=False)
    → "또래 상위 30%" | "아직 비교할 만큼 모이지 않았어요"
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from chuckchuck.contracts import Context, PeerNorm

#: 지표 이름과 "클수록 좋은가". 리포트 카피가 방향을 틀리면 칭찬과 지적이 뒤바뀐다.
METRICS: dict[str, bool] = {
    "chars_per_min": True,     # 말 속도 (F-17). 빠르다고 좋은 건 아니지만 백분위는 위치만 말한다
    "filler_per_min": False,   # 간투어/분 (F-18)
    "repeat_per_min": False,   # 반복/분 (F-18)
    "pause_per_min": False,    # 긴 쉼/분 (F-18)
    "coverage": True,          # 자료 개념을 말로 다룬 비율 (F-11)
    "order_tau": True,         # 자료 순서와 발화 순서의 일치 (F-11 파생)
}

#: 이 밑이면 버킷을 만들지 않는다.
MIN_N = 20

NOT_ENOUGH = "아직 비교할 만큼 모이지 않았어요"

PERCENTILES = (10, 25, 50, 75, 90)


def duration_band(duration_min: int | float | None) -> str:
    """발표 길이 구간. 1분 발표와 15분 발표의 간투어/분은 같은 잣대가 아니다."""
    if not duration_min or duration_min <= 0:
        return "any"
    if duration_min <= 3:
        return "short"
    if duration_min <= 7:
        return "mid"
    if duration_min <= 15:
        return "long"
    return "xl"


def bucket_key(context: Context | dict | None) -> str:
    """버킷 = 상황|길이구간. 상황이 비면 'any'."""
    if isinstance(context, Context):
        situation, dur = context.situation, context.duration_min
    else:
        d = context or {}
        situation, dur = str(d.get("situation") or ""), d.get("duration_min")
    return f"{situation.strip() or 'any'}|{duration_band(dur)}"


def _get(obj, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def session_metrics(*, transcript=None, pace=None, habits=None, alignment=None, flow=None) -> dict[str, float]:
    """세션 하나의 지표. 못 구하는 지표는 빼고 돌려준다 (0 으로 채우면 분포가 거짓이 된다)."""
    out: dict[str, float] = {}
    minutes = float(_get(transcript, "duration_sec", 0) or _get(pace, "actual_sec", 0) or 0) / 60.0
    cpm = _get(pace, "avg_chars_per_min")
    if cpm:
        out["chars_per_min"] = float(cpm)
    if minutes > 0 and habits is not None:
        for metric, key in (("filler_per_min", "filler_cnt"), ("repeat_per_min", "repeat_cnt"),
                            ("pause_per_min", "pause_cnt")):
            cnt = _get(habits, key)
            if cnt is not None:
                out[metric] = round(float(cnt) / minutes, 3)
    summary = _get(alignment, "summary")
    cov = _get(summary, "coverage")
    if cov is not None:
        out["coverage"] = float(cov)
    tau = _get(flow, "order_tau")
    if tau is not None:
        out["order_tau"] = float(tau)
    return out


def percentile(sorted_xs: list[float], p: float) -> float:
    """선형 보간 백분위. 정렬된 입력을 받는다."""
    if not sorted_xs:
        raise ValueError("빈 표본")
    if len(sorted_xs) == 1:
        return sorted_xs[0]
    pos = (len(sorted_xs) - 1) * p / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(sorted_xs) - 1)
    frac = pos - lo
    return sorted_xs[lo] + (sorted_xs[hi] - sorted_xs[lo]) * frac


def build_norms(samples: list[tuple[str, dict]], *, min_n: int = MIN_N, built_at: float | None = None) -> list[PeerNorm]:
    """(버킷, 지표 dict) 목록 → PeerNorm 목록. n < min_n 인 (버킷, 지표) 는 내지 않는다."""
    built_at = time.time() if built_at is None else built_at
    pool: dict[tuple[str, str], list[float]] = {}
    for bucket, metrics in samples:
        for metric, value in (metrics or {}).items():
            if metric in METRICS and value is not None:
                pool.setdefault((bucket, metric), []).append(float(value))
    norms: list[PeerNorm] = []
    for (bucket, metric), xs in sorted(pool.items()):
        if len(xs) < min_n:
            continue
        xs.sort()
        ps = [round(percentile(xs, p), 3) for p in PERCENTILES]
        norms.append(PeerNorm(metric=metric, bucket=bucket, n=len(xs),
                              p10=ps[0], p25=ps[1], p50=ps[2], p75=ps[3], p90=ps[4], built_at=built_at))
    return norms


def lookup(norms: list[PeerNorm], bucket: str, metric: str) -> PeerNorm | None:
    """버킷 그대로 → 없으면 같은 상황의 'any' 길이 → 없으면 None. 더 멀리 가지 않는다."""
    by = {(n.bucket, n.metric): n for n in norms}
    if (bucket, metric) in by:
        return by[(bucket, metric)]
    situation = bucket.split("|", 1)[0]
    return by.get((f"{situation}|any", metric))


def percentile_of(norm: PeerNorm, value: float) -> int:
    """값이 분포의 몇 번째 백분위인가 (0~100). 다섯 점 사이는 선형 보간, 밖은 5/95 로 자른다."""
    knots = [(10, norm.p10), (25, norm.p25), (50, norm.p50), (75, norm.p75), (90, norm.p90)]
    if value <= knots[0][1]:
        return 5 if value < knots[0][1] else 10
    if value >= knots[-1][1]:
        return 95 if value > knots[-1][1] else 90
    for (p_lo, v_lo), (p_hi, v_hi) in zip(knots, knots[1:]):
        if v_lo <= value <= v_hi:
            if v_hi == v_lo:
                return p_lo
            return int(round(p_lo + (p_hi - p_lo) * (value - v_lo) / (v_hi - v_lo)))
    return 50


def describe(norms: list[PeerNorm], bucket: str, metric: str, value: float | None) -> str:
    """리포트 한 줄. 기준이 없거나 값이 없으면 NOT_ENOUGH — 숫자를 지어내지 않는다."""
    norm = lookup(norms, bucket, metric)
    if norm is None or value is None:
        return NOT_ENOUGH
    pct = percentile_of(norm, float(value))
    higher_is_better = METRICS.get(metric, True)
    top = 100 - pct if higher_is_better else pct
    top = max(5, min(95, top))
    return f"또래 상위 {top}% (같은 조건 {norm.n}명 기준)"


def save_norms(path: Path, norms: list[PeerNorm], *, sessions: int, buckets: dict[str, int], min_n: int = MIN_N) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "built_at": time.time(), "min_n": min_n, "sessions": sessions, "buckets": buckets,
        "norms": [n.to_dict() for n in norms],
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def load_norms(path: Path) -> list[PeerNorm]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [PeerNorm.from_dict(d) for d in raw.get("norms", [])]
