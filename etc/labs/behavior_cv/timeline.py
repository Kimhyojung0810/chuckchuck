"""대본(타임라인) 도구 — 시간에 따라 바뀌는 값(고개 각도 · 위치 · 손 모드)을 프레임 배열로 푼다.

    steps([(0, 0), (4, -50), (6, 0)], ramp=0.4)   # 4초에 -50 으로 0.4초 동안 부드럽게, 6초에 다시 0
    sway(t, [(10, 25, 0.5, 0.3)])                  # 10~25초 0.5Hz · 진폭 0.3(얼굴 폭 배수) 사인, 앞뒤 0.8초 서서히
    jitter(t, sd, hz, seed)                        # 사람다운 잔떨림(부드러운 무작위)
"""
from __future__ import annotations

import numpy as np


def ease(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * x)


def steps(t: np.ndarray, keys: list[tuple[float, float]], ramp: float = 0.4) -> np.ndarray:
    """keys[i] = (시작 시각, 값). 시작 시각부터 ramp 초 동안 앞 값에서 이 값으로 넘어간다."""
    keys = sorted(keys)
    out = np.full_like(t, float(keys[0][1]), dtype=float)
    prev = float(keys[0][1])
    for t0, v in keys[1:]:
        r = ease((t - t0) / max(ramp, 1e-6))
        out = np.where(t >= t0, prev + (float(v) - prev) * r, out)
        prev = float(v)
    return out


def envelope(t: np.ndarray, t0: float, t1: float, fade: float = 0.8) -> np.ndarray:
    return ease((t - t0) / fade) * ease((t1 - t) / fade)


def sway(t: np.ndarray, segs: list[tuple[float, float, float, float]], fade: float = 0.8) -> np.ndarray:
    """segs = (t0, t1, 주파수 Hz, 진폭[얼굴 폭 배수]) → 얼굴 폭 배수 단위 변위"""
    out = np.zeros_like(t, dtype=float)
    for t0, t1, f, a in segs:
        out += a * envelope(t, t0, t1, fade) * np.sin(2 * np.pi * f * (t - t0))
    return out


def jitter(t: np.ndarray, sd: float, hz: float = 0.4, seed: int = 0) -> np.ndarray:
    """저역 통과한 무작위 걸음 — 평균 0, 표준편차 sd, 대략 hz 아래 성분만"""
    rng = np.random.default_rng(seed)
    if len(t) < 2:
        return np.zeros_like(t)
    dt = float(t[1] - t[0])
    n = len(t)
    x = rng.normal(size=n + 200)
    k = max(1, int(round(1.0 / (hz * dt) / 2)))
    ker = np.hanning(2 * k + 1)
    ker /= ker.sum()
    y = np.convolve(x, ker, mode="same")[100:100 + n]
    s = y.std()
    return (y / s * sd) if s > 0 else y


def blinks(t: np.ndarray, seed: int = 0, every: tuple[float, float] = (2.5, 6.0), dur: float = 0.15) -> np.ndarray:
    rng = np.random.default_rng(seed + 7)
    out = np.zeros_like(t, dtype=bool)
    s = float(rng.uniform(*every))
    end = float(t[-1]) if len(t) else 0.0
    while s < end:
        out |= (t >= s) & (t < s + dur)
        s += float(rng.uniform(*every))
    return out


def mask(t: np.ndarray, segs: list[tuple[float, float]]) -> np.ndarray:
    m = np.zeros_like(t, dtype=bool)
    for t0, t1 in segs:
        m |= (t >= t0) & (t < t1)
    return m


def runs(flags: np.ndarray, t: np.ndarray, min_len: float = 0.0, dt: float | None = None) -> list[tuple[float, float]]:
    """참인 연속 구간 [(t0, t1)] (t1 = 마지막 참 프레임 끝)"""
    if dt is None:
        dt = float(t[1] - t[0]) if len(t) > 1 else 0.0
    out = []
    i, n = 0, len(flags)
    while i < n:
        if flags[i]:
            j = i
            while j + 1 < n and flags[j + 1]:
                j += 1
            t0, t1 = float(t[i]), float(t[j]) + dt
            if t1 - t0 >= min_len:
                out.append((round(t0, 3), round(t1, 3)))
            i = j + 1
        else:
            i += 1
    return out
