"""일치도 통계 — 손으로 구현(공식은 아래 출처), pingouin 과 Shrout & Fleiss(1979) 표로 맞춰 봤다(test_stats.py).

ICC(2,1) 절대 일치 = McGraw & Wong(1996)의 ICC(A,1) = Shrout & Fleiss(1979)의 ICC(2,1)
  two-way random · absolute agreement · single rater
  ICC = (MSR − MSE) / (MSR + (k−1)·MSE + k·(MSC − MSE)/n)
  95% CI: McGraw & Wong(1996) 표 7 (Satterthwaite 자유도 v) — pingouin.intraclass_corr 와 같은 식
ICC(1,1) = 한 방향 무작위(코더 짝이 영상마다 다를 때의 보수적 값)
Bland–Altman: 차이 = 앞 − 뒤, 평균 차(치우침) · 95% 일치 한계 = 평균 ± 1.96·SD, 치우침의 95% CI(t 분포)
Cohen κ: (po − pe) / (1 − pe)
구간 F1: 시작 · 끝이 둘 다 ±tol 초 안이면 맞음(일대일, 가까운 것부터)
"""
from __future__ import annotations

import math

import numpy as np

try:
    from scipy import stats as _st
except Exception:  # pragma: no cover — scipy 가 없으면 CI 없이
    _st = None


def _fq(p: float, d1: float, d2: float) -> float:
    return float(_st.f.ppf(p, d1, d2))


def icc(data, alpha: float = 0.05) -> dict:
    """data: n(영상) × k(평가자) 행렬. NaN 이 있는 행은 뺀다.
    돌려줌: {icc2, lo, hi, icc1, icc1_lo, icc1_hi, n, k, msr, msc, mse, F}"""
    x = np.asarray(data, dtype=float)
    if x.ndim != 2:
        raise ValueError("n × k 행렬이어야 해요")
    x = x[~np.isnan(x).any(axis=1)]
    n, k = x.shape
    nan = {"icc2": math.nan, "lo": math.nan, "hi": math.nan, "icc1": math.nan, "icc1_lo": math.nan, "icc1_hi": math.nan,
           "n": int(n), "k": int(k), "why": ""}
    if n < 3 or k < 2:
        return nan | {"why": f"영상이 {n}개라 잴 수 없어요(3개 이상)"}
    gm = x.mean()
    ss_tot = ((x - gm) ** 2).sum()
    ssr = k * ((x.mean(axis=1) - gm) ** 2).sum()
    ssc = n * ((x.mean(axis=0) - gm) ** 2).sum()
    sse = ss_tot - ssr - ssc
    msr = ssr / (n - 1)
    msc = ssc / (k - 1)
    mse = sse / ((n - 1) * (k - 1))
    msw = (ssc + sse) / (n * (k - 1))
    if ss_tot <= 1e-12:
        return nan | {"why": "모든 영상 · 평가자 값이 같아요(흩어짐이 없어 ICC 를 정의할 수 없어요)"}
    den2 = msr + (k - 1) * mse + k * (msc - mse) / n
    icc2 = (msr - mse) / den2 if den2 > 0 else math.nan
    den1 = msr + (k - 1) * msw
    icc1 = (msr - msw) / den1 if den1 > 0 else math.nan
    out = {"icc2": float(icc2), "icc1": float(icc1), "n": int(n), "k": int(k), "msr": float(msr), "msc": float(msc),
           "mse": float(mse), "F": float(msr / mse) if mse > 0 else math.inf, "why": ""}
    lo = hi = lo1 = hi1 = math.nan
    if _st is not None and mse > 0 and math.isfinite(icc2) and icc2 < 1:
        # McGraw & Wong (1996) — ICC(A,1)
        a = k * icc2 / (n * (1 - icc2))
        b = 1 + k * icc2 * (n - 1) / (n * (1 - icc2))
        v = (a * msc + b * mse) ** 2 / ((a * msc) ** 2 / (k - 1) + (b * mse) ** 2 / ((n - 1) * (k - 1)))
        fl = _fq(1 - alpha / 2, n - 1, v)
        fu = _fq(1 - alpha / 2, v, n - 1)
        lo = n * (msr - fl * mse) / (fl * (k * msc + (k * n - k - n) * mse) + n * msr)
        hi = n * (fu * msr - mse) / (k * msc + (k * n - k - n) * mse + n * fu * msr)
    elif mse <= 0 and math.isfinite(icc2):
        lo = hi = icc2   # 평가자가 영상마다 똑같이 어긋나지 않음 = 완전 일치
    if _st is not None and msw > 0:
        f1 = msr / msw
        fl1 = f1 / _fq(1 - alpha / 2, n - 1, n * (k - 1))
        fu1 = f1 * _fq(1 - alpha / 2, n * (k - 1), n - 1)
        lo1 = (fl1 - 1) / (fl1 + k - 1)
        hi1 = (fu1 - 1) / (fu1 + k - 1)
    out.update(lo=float(lo), hi=float(hi), icc1_lo=float(lo1), icc1_hi=float(hi1))
    return out


def bland_altman(a, b) -> dict:
    """차이 = a − b (엔진 − 사람 평균 등). NaN 짝은 뺀다"""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    ok = ~(np.isnan(a) | np.isnan(b))
    d = a[ok] - b[ok]
    n = int(d.size)
    if n < 2:
        return {"n": n, "bias": math.nan, "sd": math.nan, "loa_lo": math.nan, "loa_hi": math.nan, "bias_lo": math.nan, "bias_hi": math.nan}
    bias = float(d.mean())
    sd = float(d.std(ddof=1))
    t = float(_st.t.ppf(0.975, n - 1)) if _st is not None else 1.96
    se = sd / math.sqrt(n)
    return {"n": n, "bias": bias, "sd": sd, "loa_lo": bias - 1.96 * sd, "loa_hi": bias + 1.96 * sd,
            "bias_lo": bias - t * se, "bias_hi": bias + t * se, "mean_abs": float(np.abs(d).mean())}


def kappa(x: list, y: list, labels: list | None = None) -> dict:
    """Cohen κ — 같은 길이의 범주 줄 두 개. 돌려줌: {kappa, po, pe, n, cm(라벨 순 혼동 행렬, 행=x 열=y)}"""
    if len(x) != len(y):
        raise ValueError("길이가 달라요")
    labels = labels or sorted(set(x) | set(y))
    idx = {l: i for i, l in enumerate(labels)}
    m = np.zeros((len(labels), len(labels)), int)
    for a, b in zip(x, y):
        if a in idx and b in idx:
            m[idx[a], idx[b]] += 1
    n = int(m.sum())
    if n == 0:
        return {"kappa": math.nan, "po": math.nan, "pe": math.nan, "n": 0, "cm": m.tolist(), "labels": labels}
    po = float(np.trace(m) / n)
    pe = float((m.sum(axis=1) * m.sum(axis=0)).sum() / n ** 2)
    k = (po - pe) / (1 - pe) if pe < 1 else math.nan
    return {"kappa": float(k), "po": po, "pe": pe, "n": n, "cm": m.tolist(), "labels": labels}


def seg_match(ref: list[tuple[float, float]], pred: list[tuple[float, float]], tol: float = 1.0, iou: float | None = None) -> dict:
    """구간 맞추기. 기본: 시작 · 끝 모두 ±tol 초. iou 를 주면 대신 IoU ≥ iou. 일대일, 가까운 것부터 짝짓는다"""
    cands = []
    for i, (r0, r1) in enumerate(ref):
        for j, (p0, p1) in enumerate(pred):
            if iou is None:
                if abs(r0 - p0) <= tol and abs(r1 - p1) <= tol:
                    cands.append((abs(r0 - p0) + abs(r1 - p1), i, j))
            else:
                inter = max(0.0, min(r1, p1) - max(r0, p0))
                uni = max(r1, p1) - min(r0, p0)
                v = inter / uni if uni > 0 else 0.0
                if v >= iou:
                    cands.append((1 - v, i, j))
    cands.sort()
    used_r, used_p = set(), set()
    tp = 0
    for _, i, j in cands:
        if i in used_r or j in used_p:
            continue
        used_r.add(i)
        used_p.add(j)
        tp += 1
    return {"tp": tp, "n_ref": len(ref), "n_pred": len(pred)}


def f1_of(tp: int, n_ref: int, n_pred: int) -> dict:
    p = tp / n_pred if n_pred else math.nan
    r = tp / n_ref if n_ref else math.nan
    if n_ref == 0 and n_pred == 0:
        f = math.nan
    elif (p or 0) + (r or 0) == 0 or math.isnan(p) or math.isnan(r):
        f = 0.0
    else:
        f = 2 * p * r / (p + r)
    return {"precision": p, "recall": r, "f1": f, "tp": tp, "n_ref": n_ref, "n_pred": n_pred}


def verdict(lo: float) -> tuple[str, str]:
    """95% CI 하한 → (판정, 설명). 근거조사 §6-1 · Koo & Li(2016)"""
    if lo is None or not math.isfinite(lo):
        return "잴 수 없음", "ICC 를 낼 수 없어요(영상 수 · 흩어짐 부족)"
    if lo >= 0.75:
        return "총점 후보", "하한 ≥ .75"
    if lo >= 0.50:
        return "베타", "하한 .50 ~ .75 — 참고로만, 「베타」 표시"
    return "숨김", "하한 < .50 — 화면에서 숨겨요"
