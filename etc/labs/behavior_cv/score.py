"""채점기 — 엔진 로그(프레임 줄) × 정답(gt.json) → 지표. 엔진 종류(파이썬 참조 · 브라우저)는 상관없다.

엔진 로그 모양(README 「엔진 계약」):
  {"engine": "...", "rows": [{"frame"|"vt"|"t", "present", "orient", "sway"?, "gesture"?, "motion"?, "ms"?, ...}],
   "summary"?: {"slides": [...], "lookaways": [...]}}
- 줄의 영상 시각은 frame(영상 프레임 번호) > vt(영상 시각 초) > t 순으로 쓴다.
- orient 는 영어 코드(front/left/right/down/none/away) 또는 한국어(정면/왼쪽/오른쪽/아래/없음)를 받는다.

    .venv/bin/python etc/labs/behavior_cv/score.py --gt clips/s03_lookaway.gt.json --pred preds/full/s03_lookaway.json
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from common import CLASSES, KO2EN

PRED_CLASSES = CLASSES + ["away"]
LOOKAWAY_MIN = 3.0
MERGE_GAP = 0.6
IOU_MIN = 0.5
TOL_S = 0.5


def norm_orient(v) -> str:
    if v is None:
        return "none"
    v = str(v).strip()
    v = KO2EN.get(v, v).lower()
    if v in ("unknown", "away", "side", "옆", "모름", "notfront"):
        return "away"
    return v if v in CLASSES else "away"


def swap_lr(v: str) -> str:
    return {"left": "right", "right": "left"}.get(v, v)


def row_frame(r: dict, fps: float) -> int | None:
    if r.get("frame") is not None:
        return int(r["frame"])
    if r.get("vt") is not None:
        return int(round(float(r["vt"]) * fps))
    if r.get("t") is not None:
        return int(round(float(r["t"]) * fps))
    return None


def prepare(gt: dict, log: dict, yaw_convention: str = "image") -> list[dict]:
    fps = gt["fps"]
    n = gt["n_frames"]
    out = []
    for r in log.get("rows", []):
        f = row_frame(r, fps)
        if f is None or f < 0 or f >= n:
            continue
        o = norm_orient(r.get("orient"))
        if yaw_convention == "subject":
            o = swap_lr(o)
        pres = r.get("present")
        pres = (o != "none") if pres is None else bool(pres)
        sw = r.get("sway") or {}
        if not isinstance(sw, dict):
            sw = {"active": bool(sw)}
        out.append({"f": f, "t": f / fps, "orient": o, "present": pres, "sway": bool(sw.get("active")),
                    "sway_freq": sw.get("freq"), "sway_amp": sw.get("amp_fw"), "gesture": bool(r.get("gesture")),
                    "motion": r.get("motion"), "ms": r.get("ms"),
                    "box": r.get("face") or (r.get("raw") or {}).get("box")})
    out.sort(key=lambda r: r["f"])
    # 같은 프레임 두 줄이면 마지막 것
    ded = {}
    for r in out:
        ded[r["f"]] = r
    return list(ded.values())


def seg_runs(rows: list[dict], key, min_len: float, gap: float, dt: float) -> list[tuple[float, float]]:
    segs = []
    cur = None
    for r in rows:
        if key(r):
            if cur and r["t"] - cur[1] <= gap + dt * 1.01:
                cur[1] = r["t"] + dt
            else:
                if cur:
                    segs.append(tuple(cur))
                cur = [r["t"], r["t"] + dt]
        # 아니면 그대로 — gap 안에 다시 참이 오면 이어 붙인다
    if cur:
        segs.append(tuple(cur))
    return [(round(a, 3), round(b, 3)) for a, b in segs if b - a >= min_len]


def seg_iou(a, b) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    return inter / max(1e-6, (a[1] - a[0]) + (b[1] - b[0]) - inter)


def match_segments(gt_s, pr_s, thr=IOU_MIN) -> dict:
    used = set()
    tp = 0
    pairs = []
    for g in gt_s:
        best, bj = 0.0, None
        for j, p in enumerate(pr_s):
            if j in used:
                continue
            v = seg_iou(g, p)
            if v > best:
                best, bj = v, j
        if bj is not None and best >= thr:
            used.add(bj)
            tp += 1
            pairs.append((g, pr_s[bj], round(best, 3)))
    P = tp / len(pr_s) if pr_s else (1.0 if not gt_s else 0.0)
    R = tp / len(gt_s) if gt_s else (1.0 if not pr_s else 0.0)
    F = 2 * P * R / (P + R) if P + R else 0.0
    return {"gt": len(gt_s), "pred": len(pr_s), "tp": tp, "precision": round(P, 3), "recall": round(R, 3), "f1": round(F, 3)}


def spearman(a, b) -> float | None:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 5 or a.std() == 0 or b.std() == 0:
        return None
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


def per_slide_pred(rows, slides, dt) -> list[dict]:
    out = []
    lk = seg_runs(rows, lambda r: r["present"] and r["orient"] != "front", LOOKAWAY_MIN, MERGE_GAP, dt)
    for s in slides:
        a, b = s["t0"], s["t1"]
        rr = [r for r in rows if a <= r["t"] < b]
        pr = [r for r in rr if r["present"]]
        out.append({
            "i": s["i"],
            "presence_ratio": round(len(pr) / max(1, len(rr)), 4),
            "front_ratio": round(sum(r["orient"] == "front" for r in pr) / len(pr), 4) if pr else None,
            "down_sec": round(sum(r["orient"] == "down" for r in pr) * dt, 3),
            "lookaway_n": sum(1 for x in lk if a <= x[0] < b),
            "lookaway_sec": round(sum(max(0.0, min(b, x[1]) - max(a, x[0])) for x in lk), 3),
            "gesture_ratio": round(sum(r["gesture"] for r in pr) / len(pr), 4) if pr else 0.0,
            "sway_sec": round(sum(r["sway"] for r in rr) * dt, 3),
        })
    return out


YAW_BINS = [(0, 10, "0"), (10, 27, "20"), (27, 42, "35"), (42, 60, "50"), (60, 80, "70"), (80, 181, "90")]
PITCH_BINS = [(-8, 100, "0"), (-20, -8, "-15"), (-30, -20, "-25"), (-42, -30, "-35"), (-181, -42, "-45+")]
ROLL_BINS = [(0, 5, "0"), (5, 11, "8"), (11, 30, "15")]


def curve(rows, G) -> dict:
    out = {"yaw": {}, "pitch": {}, "roll": {}}
    for r in rows:
        g = G[r["f"]]
        if not g["present"] or "yaw" not in g:
            continue
        ay, p, ar = abs(g["yaw"]), g["pitch"], abs(g.get("roll", 0))
        side = "right" if g["yaw"] > 0 else "left"
        o = r["orient"]
        tag = "front" if o == "front" else ("side_ok" if o == side else ("side_wrong" if o in ("left", "right") else o))
        if p > -8 and ar < 5:
            for lo, hi, name in YAW_BINS:
                if lo <= ay < hi:
                    out["yaw"].setdefault(name, {}).setdefault(tag, 0)
                    out["yaw"][name][tag] += 1
        if ay < 10 and ar < 5:
            for lo, hi, name in PITCH_BINS:
                if lo <= p < hi:
                    out["pitch"].setdefault(name, {}).setdefault(o, 0)
                    out["pitch"][name][o] += 1
        if ay < 10 and p > -8:
            for lo, hi, name in ROLL_BINS:
                if lo <= ar < hi:
                    out["roll"].setdefault(name, {}).setdefault(o, 0)
                    out["roll"][name][o] += 1
    return out


def score_clip(gt: dict, log: dict, yaw_convention: str = "image") -> dict:
    fps = gt["fps"]
    G = gt["frames"]
    rows = prepare(gt, log, yaw_convention)
    res: dict = {"clip": gt["name"], "tags": gt.get("tags", []), "rows": len(rows)}
    if not rows:
        res["error"] = "엔진 줄이 없음"
        return res
    fs = np.array([r["f"] for r in rows])
    dt = float(np.median(np.diff(fs))) / fps if len(fs) > 1 else 1.0 / fps
    res["proc_fps"] = round(1 / dt, 2)
    # ── 방향 ──
    cm = {g: {p: 0 for p in PRED_CLASSES} for g in CLASSES}
    tol = int(round(TOL_S * fps))
    ok = ok_tol = tot = 0
    fb_ok = fb_tot = 0
    for r in rows:
        g = G[r["f"]]
        if g["ignore"]:
            continue
        cm[g["label"]][r["orient"]] += 1
        tot += 1
        ok += g["label"] == r["orient"]
        win = G[max(0, r["f"] - tol): r["f"] + tol + 1]
        ok_tol += any(w["label"] == r["orient"] for w in win)
        if g["present"]:
            fb_tot += 1
            fb_ok += (g["label"] == "front") == (r["orient"] == "front")
    per = {}
    for c in CLASSES:
        tp = cm[c][c]
        pp = sum(cm[g][c] for g in CLASSES)
        gp = sum(cm[c].values())
        if gp == 0 and pp == 0:
            continue
        P = tp / pp if pp else None
        R = tp / gp if gp else None
        if gp and not pp:
            P = 0.0          # 한 번도 그 방향이라고 안 했다 — F1 = 0 으로 친다
        F = (2 * P * R / (P + R) if P and R else 0.0) if R is not None else None
        per[c] = {"n": gp, "precision": None if P is None else round(P, 3), "recall": None if R is None else round(R, 3),
                  "f1": None if F is None else round(F, 3)}
    f1s = [v["f1"] for v in per.values() if v["n"] > 0 and v["f1"] is not None]
    res["orient"] = {"acc": round(ok / tot, 4) if tot else None, "acc_tol": round(ok_tol / tot, 4) if tot else None,
                     "front_vs_not_acc": round(fb_ok / fb_tot, 4) if fb_tot else None,
                     "macro_f1": round(float(np.mean(f1s)), 4) if f1s else None, "n": tot, "per_class": per, "confusion": cm}
    # ── 정면율(있을 때만) ──
    sc = [(G[r["f"]], r) for r in rows if not G[r["f"]]["ignore"] and G[r["f"]]["present"]]
    if sc:
        gfr = np.mean([g["label"] == "front" for g, _ in sc])
        prs = [r for _, r in sc if r["present"]]
        pfr = np.mean([r["orient"] == "front" for r in prs]) if prs else 0.0
        res["front_ratio"] = {"gt": round(float(gfr), 4), "pred": round(float(pfr), 4), "abs_err": round(abs(float(gfr) - float(pfr)), 4)}
    # ── 자리 ──
    pa = [(G[r["f"]]["present"] == 1) == r["present"] for r in rows]
    tp = sum(1 for r in rows if r["present"] and G[r["f"]]["present"])
    fp = sum(1 for r in rows if r["present"] and not G[r["f"]]["present"])
    fn = sum(1 for r in rows if not r["present"] and G[r["f"]]["present"])
    res["presence"] = {"acc": round(float(np.mean(pa)), 4), "fp_rows": fp, "fn_rows": fn,
                       "precision": round(tp / (tp + fp), 4) if tp + fp else None, "recall": round(tp / (tp + fn), 4) if tp + fn else None}
    # ── 얼굴 자리 — 엔진이 고른 얼굴이 정답 발표자 얼굴인가 (책장 · 포스터 헛얼굴에 붙으면 방향이 맞아도 틀린 것) ──
    fh = [r for r in rows if r["box"] and G[r["f"]]["present"] and G[r["f"]].get("face")]
    if fh:
        def hit(r):
            gx, gy, gw, gh = G[r["f"]]["face"]
            px, py, pw, ph = r["box"]
            return abs(px + pw / 2 - gx - gw / 2) < 0.6 * gw and abs(py + ph / 2 - gy - gh / 2) < 0.6 * gh * 1.0 + 0.4 * gh
        hits = [hit(r) for r in fh]
        res["face"] = {"hit": round(float(np.mean(hits)), 4), "n": len(fh),
                       "wrong_face_rows": int(len(hits) - sum(hits))}
    # ── 긴 이탈 ──
    gl = [(s["t0"], s["t1"]) for s in gt["segments"]["lookaway"]]
    pl = seg_runs(rows, lambda r: r["present"] and r["orient"] != "front", LOOKAWAY_MIN, MERGE_GAP, dt)
    res["lookaway"] = match_segments(gl, pl)
    res["lookaway"]["pred_segments"] = pl
    if isinstance(log.get("summary"), dict) and log["summary"].get("lookaways") is not None:
        es = [(float(s.get("t0", s.get("start", 0))), float(s.get("t1", s.get("end", 0)))) for s in log["summary"]["lookaways"]]
        res["lookaway_engine"] = match_segments(gl, es)
    # ── 아래 본 시간 ──
    gd = sum(s["t1"] - s["t0"] for s in gt["segments"]["down"])
    pd = sum(r["orient"] == "down" for r in rows) * dt
    res["down"] = {"gt_sec": round(gd, 2), "pred_sec": round(pd, 2), "abs_err_sec": round(abs(gd - pd), 2)}
    gdn = np.array([G[r["f"]]["label"] == "down" and not G[r["f"]]["ignore"] for r in rows])
    pdn = np.array([r["orient"] == "down" for r in rows])
    if gdn.any() or pdn.any():
        tp_ = int((gdn & pdn).sum())
        res["down"].update({"precision": round(tp_ / max(1, pdn.sum()), 3), "recall": round(tp_ / max(1, gdn.sum()), 3)})
    # ── 흔들림 ──
    sw = gt["segments"]["sway"]
    segs = []
    for s in sw:
        a, b = s["t0"] + 1.0, s["t1"] + 3.0      # 창(8초)만큼 늦게 켜지고 꺼지는 것을 봐준다
        rr = [r for r in rows if a <= r["t"] < b]
        act = [r for r in rr if r["sway"]]
        frac = len(act) / max(1, len(rr))
        fq = [r["sway_freq"] for r in act if r["sway_freq"] is not None]
        am = [r["sway_amp"] for r in act if r["sway_amp"] is not None]
        mf = float(np.median(fq)) if fq else None
        ma = float(np.median(am)) if am else None
        segs.append({"freq": s["freq"], "amp_fw": s["amp_fw"], "active_frac": round(frac, 3), "detected": frac >= 0.5,
                     "pred_freq": None if mf is None else round(mf, 3), "freq_err": None if mf is None else round(abs(mf - s["freq"]), 3),
                     "pred_amp": None if ma is None else round(ma, 3),
                     "amp_rel_err": None if ma is None else round(abs(ma - s["amp_fw"]) / s["amp_fw"], 3)})
    covered = lambda t: any(s["t0"] - 0.5 <= t < s["t1"] + 5.0 for s in sw)  # noqa: E731
    outside = [r for r in rows if not covered(r["t"]) and r["t"] >= 8.0]
    res["sway"] = {"segments": segs, "false_active_frac": round(sum(r["sway"] for r in outside) / max(1, len(outside)), 4),
                   "false_sec": round(sum(r["sway"] for r in outside) * dt, 2)}
    # ── 손짓 ──
    # 손을 올리고 내리는 사이(정답 손짓 아님 · 손은 실제로 움직임)는 손짓 채점에서 뺀다
    pres_rows = [r for r in rows if G[r["f"]]["present"]
                 and not (not G[r["f"]].get("gesture") and G[r["f"]].get("hands_visible") and G[r["f"]].get("hand_speed", 0) > 0.5)]
    if pres_rows:
        gg = np.array([G[r["f"]].get("gesture", 0) for r in pres_rows], bool)
        pg = np.array([r["gesture"] for r in pres_rows], bool)
        tp_ = int((gg & pg).sum())
        P = tp_ / pg.sum() if pg.sum() else None
        R = tp_ / gg.sum() if gg.sum() else None
        res["gesture"] = {"gt_ratio": round(float(gg.mean()), 4), "pred_ratio": round(float(pg.mean()), 4),
                          "abs_err": round(abs(float(gg.mean()) - float(pg.mean())), 4),
                          "precision": None if P is None else round(P, 3), "recall": None if R is None else round(R, 3)}
        # 가슴 앞 가만한 손(hold)에서 손짓으로 센 비율 — 「보이기만 하는 손」 오탐
        hold = [r for r in pres_rows if G[r["f"]].get("hands_visible") and not G[r["f"]].get("gesture")]
        res["gesture"]["false_on_visible_still"] = round(sum(r["gesture"] for r in hold) / len(hold), 3) if hold else None
    # ── 움직임 ──
    mv = [(r["motion"], G[r["f"]].get("head_speed", 0) + G[r["f"]].get("hand_speed", 0)) for r in rows
          if r["motion"] is not None and G[r["f"]]["present"]]
    if mv:
        res["motion"] = {"spearman": None if spearman(*zip(*mv)) is None else round(spearman(*zip(*mv)), 3), "n": len(mv)}
    # ── 장별 ──
    ps = per_slide_pred(rows, gt["slides"], dt)
    errs = {}
    for k in ["presence_ratio", "front_ratio", "down_sec", "lookaway_n", "gesture_ratio", "sway_sec"]:
        e = [abs(p[k] - g[k]) for p, g in zip(ps, gt["per_slide"]) if p[k] is not None and g[k] is not None]
        errs[k] = round(float(np.mean(e)), 4) if e else None
    res["per_slide"] = {"mae": errs, "pred": ps, "gt": gt["per_slide"]}
    if isinstance(log.get("summary"), dict) and isinstance(log["summary"].get("slides"), list):
        res["per_slide"]["engine_summary"] = log["summary"]["slides"]
    # ── 각도 곡선 — |yaw| · pitch · |roll| 구간별로 엔진이 뭐라고 했나 (근거조사 §3: Haar 정면 ±45° · roll ±15°) ──
    res["curve"] = curve(rows, G)
    # ── 시간 ──
    ms = [r["ms"] for r in rows if r["ms"] is not None]
    if ms:
        res["ms"] = {"mean": round(float(np.mean(ms)), 2), "p50": round(float(np.median(ms)), 2), "p95": round(float(np.percentile(ms, 95)), 2)}
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", type=Path, required=True)
    ap.add_argument("--pred", type=Path, required=True)
    ap.add_argument("--yaw-convention", default="image", choices=["image", "subject"])
    a = ap.parse_args()
    r = score_clip(json.loads(a.gt.read_text()), json.loads(a.pred.read_text()), a.yaw_convention)
    r.get("per_slide", {}).pop("pred", None)
    print(json.dumps(r, ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
