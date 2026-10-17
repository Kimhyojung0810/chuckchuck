"""통계 맞춰 보기 — ① Shrout & Fleiss(1979) 표 2 (6 대상 × 4 평가자: ICC(1,1)=.17 · ICC(2,1)=.29)
② pingouin 0.7 intraclass_corr 와 무작위 행렬 40개(있으면 — /data/models/_runs/behavior-icc/pylib) ③ κ · 구간 F1 · runs 손계산.

    PY=/home/yehschuck/project/chuckchuck/.venv/bin/python
    $PY etc/labs/behavior_icc/test_stats.py            # 그냥 돌려도 되고 pytest 로 돌려도 된다
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_icc import clip_metrics, runs  # noqa: E402
from stats_icc import bland_altman, f1_of, icc, kappa, seg_match, verdict  # noqa: E402

SF = [[9, 2, 5, 8], [6, 1, 3, 2], [8, 4, 6, 8], [7, 1, 2, 6], [10, 5, 6, 9], [6, 2, 4, 7]]
PG_LIB = Path(os.environ.get("BEHAVIOR_ICC_PGLIB", "/data/models/_runs/behavior-icc/pylib"))


def test_shrout_fleiss():
    r = icc(SF)
    assert round(r["icc2"], 2) == 0.29, r
    assert round(r["icc1"], 2) == 0.17, r
    # pingouin 0.7 이 같은 자료에서 낸 CI (손으로 옮겨 적음): ICC(A,1) [0.02, 0.76] · ICC(1,1) [-0.13, 0.72]
    assert round(r["lo"], 2) == 0.02 and round(r["hi"], 2) == 0.76, r
    assert round(r["icc1_lo"], 2) == -0.13 and round(r["icc1_hi"], 2) == 0.72, r


def test_edges():
    assert math.isnan(icc([[1, 1], [1, 1], [1, 1]])["icc2"])            # 흩어짐 없음
    assert math.isnan(icc([[1, 2], [2, 3]])["icc2"])                    # 영상 2개
    r = icc([[0.1, 0.1], [0.5, 0.5], [0.9, 0.9], [0.3, 0.3]])          # 완전 일치
    assert abs(r["icc2"] - 1) < 1e-9 and r["lo"] == 1
    r = icc([[0.1, np.nan], [0.5, 0.5], [0.9, 0.8], [0.3, 0.3], [0.2, 0.25]])  # NaN 행은 빠진다
    assert r["n"] == 4
    assert verdict(0.8)[0] == "총점 후보" and verdict(0.6)[0] == "베타" and verdict(0.2)[0] == "숨김" and verdict(math.nan)[0] == "잴 수 없음"


def test_pingouin_random():
    if not (PG_LIB / "pingouin").exists():
        print("pingouin 없음 — 건너뜀")
        return
    rng = np.random.default_rng(7)
    mats = []
    for i in range(40):
        n = int(rng.integers(5, 40))
        k = int(rng.integers(2, 4))
        true = rng.normal(0, 1, n)[:, None]
        bias = rng.normal(0, 0.5, k)[None, :] * (i % 3)
        mats.append((true + bias + rng.normal(0, 0.3 + (i % 5) * 0.3, (n, k))).round(4).tolist())
    code = r"""
import json, sys, warnings
warnings.filterwarnings('ignore')
import pandas as pd, pingouin as pg
out = []
for m in json.load(sys.stdin):
    rows = [(i, j, v) for i, r in enumerate(m) for j, v in enumerate(r)]
    t = pg.intraclass_corr(pd.DataFrame(rows, columns=['t', 'r', 'v']), 't', 'r', 'v').set_index('Type')
    a = t.loc['ICC(A,1)']; o = t.loc['ICC(1,1)']
    out.append([float(a['ICC']), float(a['CI95'][0]), float(a['CI95'][1]), float(o['ICC']), float(o['CI95'][0]), float(o['CI95'][1])])
print(json.dumps(out))
"""
    env = dict(os.environ, PYTHONPATH=str(PG_LIB))
    res = subprocess.run([sys.executable, "-c", code], input=json.dumps(mats),
                         capture_output=True, text=True, env=env, timeout=300)
    assert res.returncode == 0, res.stderr[-2000:]
    ref = json.loads(res.stdout.strip().splitlines()[-1])
    worst = 0.0
    for m, (a, alo, ahi, o, olo, ohi) in zip(mats, ref):
        r = icc(m)
        worst = max(worst, abs(r["icc2"] - a), abs(r["icc1"] - o))
        # pingouin 은 CI 를 소수 둘째 자리로 반올림해 준다
        assert abs(r["lo"] - alo) <= 0.0051 and abs(r["hi"] - ahi) <= 0.0051, (r, alo, ahi)
        assert abs(r["icc1_lo"] - olo) <= 0.0051 and abs(r["icc1_hi"] - ohi) <= 0.0051, (r, olo, ohi)
    assert worst < 1e-9, worst
    print(f"pingouin 과 {len(mats)}개 행렬 일치 (ICC 최대 차 {worst:.1e}, CI 는 반올림 범위 안)")


def test_kappa_ba_f1_runs():
    k = kappa(list("aabbab"), list("aabbba"))           # po=4/6, pe=.5 → κ=1/3
    assert abs(k["kappa"] - 1 / 3) < 1e-9
    ba = bland_altman([1, 2, 3, 4], [1, 1, 2, 3])
    assert abs(ba["bias"] - 0.75) < 1e-9 and abs(ba["loa_hi"] - (0.75 + 1.96 * ba["sd"])) < 1e-9
    m = seg_match([(0, 5), (10, 14)], [(1, 6), (10, 18), (20, 22)])
    assert m == {"tp": 1, "n_ref": 2, "n_pred": 3}
    m2 = seg_match([(0, 5), (10, 14)], [(1, 6), (10, 18)], iou=0.5)
    assert m2["tp"] == 2
    f = f1_of(1, 2, 3)
    assert abs(f["f1"] - 2 * (1 / 3) * 0.5 / (1 / 3 + 0.5)) < 1e-9
    seq = [{"sec": i, "gaze": g, "hand": 0, "sway": 0} for i, g in enumerate("SAAAASDDDSAAAAA" + "N" + "AAAA")]
    G = {"S": "screen", "A": "away", "D": "down", "N": "absent"}
    for r in seq:
        r["gaze"] = G[r["gaze"]]
    lr = runs(seq, lambda r: r["gaze"] in ("away", "down"), 4)
    assert lr == [(1, 5), (10, 15), (16, 20)], lr
    cm = clip_metrics(seq)
    assert cm["long_away_n"] == 3 and cm["down_sec"] == 3 and cm["n_present"] == 19
    # 빠진 초는 구간을 끊는다
    gap = [r for r in seq if r["sec"] != 12]
    assert runs(gap, lambda r: r["gaze"] in ("away", "down"), 4) == [(1, 5), (16, 20)]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
