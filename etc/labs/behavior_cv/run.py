"""행동 추적 실험실 — 한 번에 돌리기: 참조 엔진(파이썬) · 브라우저 엔진 → 채점 → 보고서.

    PY=/home/yehschuck/project/chuckchuck/.venv/bin/python
    $PY etc/labs/behavior_cv/run.py ref --run baseline                         # 참조 엔진 여러 변형 × 모든 영상
    $PY etc/labs/behavior_cv/run.py ref --variants full --clips s03,d1 --run quick
    $PY etc/labs/behavior_cv/run.py browser --web /data/models/_wt/wt-behavior-cv/main/web --run engine1
    $PY etc/labs/behavior_cv/run.py score --run baseline                       # 남은 예측으로 다시 채점 · 보고서만

결과: /data/models/_runs/behavior-cv/lab/runs/<run>/
  preds/<variant>/<clip>.json — 엔진 줄  ·  scores.json — 영상별 지표  ·  report.md — 읽는 보고서
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np

from common import CLASSES, CLIPS, KO, RUNS

PRIMARY = "v2"


def clip_list(sel: str) -> list[Path]:
    allc = sorted(CLIPS.glob("*.y4m"))
    if not sel:
        return allc
    want = [w.strip() for w in sel.split(",") if w.strip()]
    return [c for c in allc if any(c.stem.startswith(w) for w in want)]


def _ref_job(args):
    clip, variant, out = args
    import cv2

    cv2.setNumThreads(1)
    from ref_engine import VARIANTS, run_clip

    log = run_clip(Path(clip), VARIANTS[variant])
    log["variant"] = variant
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(log, ensure_ascii=False))
    return clip, variant


def cmd_ref(a) -> Path:
    from ref_engine import VARIANTS

    run = RUNS / a.run
    variants = [v.strip() for v in a.variants.split(",")] if a.variants else list(VARIANTS)
    clips = clip_list(a.clips)
    jobs = [(str(c), v, str(run / "preds" / v / f"{c.stem}.json")) for v in variants for c in clips]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for k, (c, v) in enumerate(ex.map(_ref_job, jobs), 1):
            print(f"  [{k}/{len(jobs)}] {v:14s} {Path(c).stem}  ({time.time() - t0:.0f}s)", flush=True)
    meta = {"engine": "py-ref", "variants": variants, "clips": [c.stem for c in clips], "created": datetime.now().isoformat(timespec="seconds"),
            "yaw_convention": "image", "note": "참조 엔진은 프로세스 여러 개로 동시에 돌려 ms 가 실제보다 클 수 있다 (cv2 스레드 1)"}
    (run / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    return cmd_score(argparse.Namespace(run=a.run, yaw_convention="image", primary=a.primary))


def cmd_browser(a) -> Path:
    from browser_adapter import run_clip_browser

    run = RUNS / a.run
    clips = clip_list(a.clips)
    variant = a.label or "browser"
    for c in clips:
        if c.stem == "d8_hd30" and not a.include_hd:
            continue   # 1.6GB · 40초 — 처리 시간 비교가 필요할 때만 (--include-hd)
        out = run / "preds" / variant / f"{c.stem}.json"
        if out.exists() and not a.force:
            print("  있음 —", out.name)
            continue
        gt = json.loads(c.with_suffix(".gt.json").read_text())
        t0 = time.time()
        log = run_clip_browser(c, gt, Path(a.web), adapter=Path(a.adapter), throttle=a.cpu_throttle, port=a.port,
                               shots=run / "shots" if a.shots else None)
        log["variant"] = variant
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(log, ensure_ascii=False))
        print(f"  {c.stem:18s} 줄 {len(log.get('rows', [])):4d}  {time.time() - t0:5.1f}s  {log.get('adapter_note', '')}", flush=True)
    import subprocess

    def git(*args):
        try:
            return subprocess.run(["git", "-C", a.web, *args], capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return ""
    meta = {"engine": "browser", "web": a.web, "adapter": a.adapter, "engine_commit": git("rev-parse", "--short", "HEAD"),
            "engine_dirty": bool(git("status", "--porcelain", "--", ".")), "variants": [variant], "clips": [c.stem for c in clips],
            "created": datetime.now().isoformat(timespec="seconds"), "yaw_convention": a.yaw_convention, "cpu_throttle": a.cpu_throttle}
    (run / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    return cmd_score(argparse.Namespace(run=a.run, yaw_convention=a.yaw_convention, primary=variant))


def cmd_score(a) -> Path:
    from score import score_clip

    run = RUNS / a.run
    meta = json.loads((run / "meta.json").read_text()) if (run / "meta.json").exists() else {}
    yc = a.yaw_convention or meta.get("yaw_convention", "image")
    scores: dict = {}
    for vdir in sorted((run / "preds").iterdir()):
        for pf in sorted(vdir.glob("*.json")):
            gtp = CLIPS / f"{pf.stem}.gt.json"
            if not gtp.exists():
                continue
            gt = json.loads(gtp.read_text())
            scores.setdefault(vdir.name, {})[pf.stem] = score_clip(gt, json.loads(pf.read_text()), yc)
    (run / "scores.json").write_text(json.dumps(scores, ensure_ascii=False))
    md = report(scores, meta, a.primary if a.primary in scores else next(iter(scores)), run)
    if (run / "notes.md").exists():   # 사람이 쓴 해석 · 권고 — 다시 채점해도 남는다
        md += "\n" + (run / "notes.md").read_text()
    (run / "report.md").write_text(md)
    print(f"→ {run / 'report.md'}")
    return run / "report.md"


# ── 보고서 ───────────────────────────────────────────────────────────────
def f(v, k=3, pct=False):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "–"
    return f"{v * 100:.1f}%" if pct else f"{v:.{k}f}" if isinstance(v, float) else str(v)


def summarize(sc: dict) -> dict:
    """변형 하나의 영상 전체 요약"""
    def mean(key_fn, clips=None):
        vals = [key_fn(r) for n, r in sc.items() if (clips is None or n in clips) and "error" not in r]
        vals = [v for v in vals if v is not None]
        return float(np.mean(vals)) if vals else None

    def get(*ks):
        def fn(r):
            x = r
            for k in ks:
                if not isinstance(x, dict) or k not in x:
                    return None
                x = x[k]
            return x
        return fn
    # 방향 혼동 · 이탈은 사람이 있는 영상 전체에서 모아 센다
    cm = {g: {p: 0 for p in CLASSES + ["away"]} for g in CLASSES}
    lk = {"gt": 0, "pred": 0, "tp": 0}
    for r in sc.values():
        if "orient" in r:
            for g, row in r["orient"]["confusion"].items():
                for p, n in row.items():
                    cm[g][p] += n
        if "lookaway" in r:
            for k in lk:
                lk[k] += r["lookaway"][k]
    tot = sum(sum(v.values()) for v in cm.values())
    acc = sum(cm[c][c] for c in CLASSES) / tot if tot else None
    P = lk["tp"] / lk["pred"] if lk["pred"] else None
    R = lk["tp"] / lk["gt"] if lk["gt"] else None
    F = 2 * P * R / (P + R) if P and R else 0.0
    sw = [s for r in sc.values() for s in r.get("sway", {}).get("segments", [])]
    drift = [n for n, r in sc.items() if "drift" in r.get("tags", [])]
    gest_clips = [n for n, r in sc.items() if "gesture" in r and r["gesture"]["gt_ratio"] > 0]
    ms = [r["ms"]["mean"] for r in sc.values() if "ms" in r]
    p95 = [r["ms"]["p95"] for r in sc.values() if "ms" in r]
    return {
        "orient_acc": acc, "confusion": cm,
        "macro_f1": mean(get("orient", "macro_f1")),
        "front_vs_not": mean(get("orient", "front_vs_not_acc")),
        "front_ratio_err": mean(get("front_ratio", "abs_err")),
        "lookaway": {**lk, "precision": P, "recall": R, "f1": F},
        "down_err": mean(get("down", "abs_err_sec")),
        "down_p": mean(get("down", "precision")), "down_r": mean(get("down", "recall")),
        "sway_det": float(np.mean([s["detected"] for s in sw])) if sw else None,
        "sway_det_big": float(np.mean([s["detected"] for s in sw if s["amp_fw"] >= 0.15])) if sw else None,
        "sway_freq_err": float(np.median([s["freq_err"] for s in sw if s["freq_err"] is not None])) if any(s["freq_err"] is not None for s in sw) else None,
        "sway_amp_err": float(np.median([s["amp_rel_err"] for s in sw if s["amp_rel_err"] is not None])) if any(s["amp_rel_err"] is not None for s in sw) else None,
        "false_sway_drift": mean(get("sway", "false_sec"), drift),
        "false_sway_all": mean(get("sway", "false_active_frac")),
        "gest_err": mean(get("gesture", "abs_err"), gest_clips),
        "gest_p": mean(get("gesture", "precision"), gest_clips), "gest_r": mean(get("gesture", "recall"), gest_clips),
        "gest_false_still": mean(get("gesture", "false_on_visible_still")),
        "presence": mean(get("presence", "acc")),
        "face_hit": mean(get("face", "hit")),
        "gest_false_nohands": mean(get("gesture", "pred_ratio"), [n for n, r in sc.items() if "gesture" in r and r["gesture"]["gt_ratio"] == 0]),
        "slide_front": mean(get("per_slide", "mae", "front_ratio")),
        "slide_down": mean(get("per_slide", "mae", "down_sec")),
        "slide_gest": mean(get("per_slide", "mae", "gesture_ratio")),
        "slide_look": mean(get("per_slide", "mae", "lookaway_n")),
        "motion_rho": mean(get("motion", "spearman")),
        "ms": float(np.mean(ms)) if ms else None, "ms_p95": float(np.mean(p95)) if p95 else None,
    }


def report(scores: dict, meta: dict, primary: str, run: Path) -> str:
    S = {v: summarize(sc) for v, sc in scores.items()}
    L = [f"# 행동 추적 실험실 보고서 — {run.name}", "",
         f"- 만든 때: {meta.get('created', '')} · 엔진: {meta.get('engine', '')} · 좌우 규약: {meta.get('yaw_convention', 'image')}",
         f"- 영상 {len(next(iter(scores.values())))}개 · 변형 {', '.join(scores)} · 기준 변형 **{primary}**",
         "- 정답·영상: /data/models/_runs/behavior-cv/lab/clips (합성, 자유 라이선스 3D 머리 스캔 + 그린 손 — README 「한계」)", ""]
    if meta.get("note"):
        L += [f"> {meta['note']}", ""]
    L += ["## 1. 변형 비교 (영상 전체)", "",
          "| 지표 | " + " | ".join(scores) + " |", "|---" * (len(scores) + 1) + "|"]
    rows = [
        ("방향 정확도(5갈래, 제외 프레임 뺌)", "orient_acc", True), ("방향 macro-F1(영상 평균)", "macro_f1", False),
        ("정면/정면 아님 정확도", "front_vs_not", True), ("정면율 절대 오차", "front_ratio_err", True),
        ("긴 이탈 F1 (IoU≥0.5)", ("lookaway", "f1"), False), ("긴 이탈 정밀도", ("lookaway", "precision"), False), ("긴 이탈 재현율", ("lookaway", "recall"), False),
        ("아래 본 시간 오차(초/영상)", "down_err", False), ("아래 정밀도 · 재현율", ("down_p", "down_r"), False),
        ("흔들림 구간 검출률(전체)", "sway_det", True), ("흔들림 검출률(진폭≥.15)", "sway_det_big", True),
        ("흔들림 주파수 오차(Hz, 중앙)", "sway_freq_err", False), ("흔들림 진폭 상대 오차(중앙)", "sway_amp_err", False),
        ("느린 이동에서 흔들림 오탐(초/영상)", "false_sway_drift", False), ("흔들림 밖 오탐 비율(전체)", "false_sway_all", True),
        ("손짓 시간 비율 오차(손짓 영상)", "gest_err", True), ("손짓 정밀도 · 재현율", ("gest_p", "gest_r"), False),
        ("가만한 손을 손짓으로 셈", "gest_false_still", True), ("손이 안 보이는 영상의 손짓 비율(오탐)", "gest_false_nohands", True), ("움직임 순위상관(ρ)", "motion_rho", False),
        ("자리 있음 정확도", "presence", True), ("고른 얼굴이 발표자 얼굴(얼굴 자리 맞음)", "face_hit", True),
        ("장별 정면율 MAE", "slide_front", True), ("장별 아래 시간 MAE(초)", "slide_down", False),
        ("장별 손짓 비율 MAE", "slide_gest", True), ("장별 이탈 횟수 MAE", "slide_look", False),
        ("처리 ms 평균 · p95", ("ms", "ms_p95"), False),
    ]
    for name, key, pct in rows:
        cells = []
        for v in scores:
            s = S[v]
            if isinstance(key, tuple) and key[0] == "lookaway":
                cells.append(f(s["lookaway"][key[1]]))
            elif isinstance(key, tuple):
                cells.append(" · ".join(f(s[k], 2) for k in key))
            else:
                cells.append(f(s[key], 3, pct))
        L.append(f"| {name} | " + " | ".join(cells) + " |")
    L.append("")
    sc = scores[primary]
    L += [f"## 2. 영상별 — {primary}", "",
          "| 영상 | 방향 정확도 | ±0.5s | 얼굴 자리 | 정면율 오차 | 이탈 GT/예측/맞음 | 아래 GT→예측(초) | 흔들림 검출 | 손짓 GT→예측 | 자리 | ms |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, r in sc.items():
        if "error" in r:
            L.append(f"| {n} | {r['error']} |||||||||")
            continue
        o = r["orient"]
        sw = r["sway"]["segments"]
        swc = f"{sum(s['detected'] for s in sw)}/{len(sw)}" if sw else (f"오탐 {r['sway']['false_sec']}s" if r['sway']['false_sec'] else "–")
        g = r.get("gesture", {})
        L.append(f"| {n} | {f(o['acc'], pct=True)} | {f(o['acc_tol'], pct=True)} | {f(r.get('face', {}).get('hit'), pct=True)} | {f(r.get('front_ratio', {}).get('abs_err'), pct=True)} | "
                 f"{r['lookaway']['gt']}/{r['lookaway']['pred']}/{r['lookaway']['tp']} | {r['down']['gt_sec']}→{r['down']['pred_sec']} | {swc} | "
                 f"{f(g.get('gt_ratio'), pct=True)}→{f(g.get('pred_ratio'), pct=True)} | {f(r['presence']['acc'], pct=True)} | {f(r.get('ms', {}).get('mean'), 1)} |")
    L.append("")
    cm = S[primary]["confusion"]
    L += [f"## 3. 혼동 행렬 — {primary} (행=정답, 열=예측, 모든 영상 합)", "",
          "| 정답 \\ 예측 | " + " | ".join(KO.get(p, p) for p in CLASSES + ["away"]) + " | 재현율 |", "|---" * 8 + "|"]
    for g in CLASSES:
        n = sum(cm[g].values())
        if not n:
            continue
        L.append(f"| {KO[g]} | " + " | ".join(str(cm[g][p]) for p in CLASSES + ["away"]) + f" | {f(cm[g][g] / n, pct=True)} |")
    prec = []
    for p in CLASSES:
        col = sum(cm[g][p] for g in CLASSES)
        prec.append(f(cm[p][p] / col, pct=True) if col else "–")
    L += ["| 정밀도 | " + " | ".join(prec) + " | – | |", ""]
    # 각도 곡선
    curves = {"yaw": {}, "pitch": {}, "roll": {}}
    for r in sc.values():
        for k in curves:
            for b, d in r.get("curve", {}).get(k, {}).items():
                for t, n in d.items():
                    curves[k].setdefault(b, {}).setdefault(t, 0)
                    curves[k][b][t] += n
    L += [f"## 4. 각도 곡선 — {primary}", "", "고개 각도 구간별로 엔진이 낸 답의 비율 (yaw 표의 side_ok = 맞는 쪽 옆, side_wrong = 반대쪽).", ""]
    for k, order in (("yaw", ["0", "20", "35", "50", "70", "90"]), ("pitch", ["0", "-15", "-25", "-35", "-45+"]), ("roll", ["0", "8", "15"])):
        d = curves[k]
        tags = sorted({t for b in d.values() for t in b})
        if not d:
            continue
        L += [f"**{k}**", "", f"| {k} | n | " + " | ".join(tags) + " |", "|---" * (len(tags) + 2) + "|"]
        for b in order:
            if b not in d:
                continue
            n = sum(d[b].values())
            L.append(f"| {b} | {n} | " + " | ".join(f(d[b].get(t, 0) / n, pct=True) for t in tags) + " |")
        L.append("")
    # 흔들림 세부
    L += [f"## 5. 흔들림 구간 — {primary}", "", "| 영상 | 주파수 | 진폭(fw) | 켜진 비율 | 예측 주파수 | 예측 진폭 |", "|---|---|---|---|---|---|"]
    for n, r in sc.items():
        for s in r.get("sway", {}).get("segments", []):
            L.append(f"| {n} | {s['freq']} | {s['amp_fw']} | {f(s['active_frac'], pct=True)} | {f(s['pred_freq'], 2)} | {f(s['pred_amp'], 2)} |")
    L.append("")
    # 품질 변형 · 톤
    deg = [n for n in sc if n.startswith(("d", "t"))]
    if deg:
        L += [f"## 6. 품질 변형 · 피부 톤 — {primary} (공통 대본, d0_clean 이 기준)", "",
              "| 영상 | 방향 정확도 | 정면/아님 | 이탈 F1 | 아래 오차(초) | 손짓 정밀도 · 재현율 | 자리 | ms |", "|---|---|---|---|---|---|---|---|"]
        for n in sorted(deg):
            r = sc[n]
            if "orient" not in r:
                continue
            g = r.get("gesture", {})
            L.append(f"| {n} | {f(r['orient']['acc'], pct=True)} | {f(r['orient']['front_vs_not_acc'], pct=True)} | {f(r['lookaway']['f1'])} | "
                     f"{r['down']['abs_err_sec']} | {f(g.get('precision'), 2)} · {f(g.get('recall'), 2)} | {f(r['presence']['acc'], pct=True)} | {f(r.get('ms', {}).get('mean'), 1)} |")
        L.append("")
    # 변형별 영상 정확도 한눈에
    L += ["## 7. 변형 × 영상 방향 정확도", "", "| 영상 | " + " | ".join(scores) + " |", "|---" * (len(scores) + 1) + "|"]
    for n in sc:
        L.append(f"| {n} | " + " | ".join(f(scores[v].get(n, {}).get("orient", {}).get("acc"), pct=True) for v in scores) + " |")
    L.append("")
    return "\n".join(L)


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("ref")
    r.add_argument("--run", default=datetime.now().strftime("ref_%m%d_%H%M"))
    r.add_argument("--variants", default="")
    r.add_argument("--clips", default="")
    r.add_argument("--jobs", type=int, default=min(12, os.cpu_count() or 4))
    r.add_argument("--primary", default=PRIMARY)
    b = sub.add_parser("browser")
    b.add_argument("--web", required=True, help="엔진이 든 worktree 의 main/web")
    b.add_argument("--adapter", default=str(Path(__file__).resolve().parent / "web" / "adapter_default.js"))
    b.add_argument("--run", default=datetime.now().strftime("browser_%m%d_%H%M"))
    b.add_argument("--label", default="browser")
    b.add_argument("--clips", default="")
    b.add_argument("--port", type=int, default=0)
    b.add_argument("--cpu-throttle", type=float, default=1.0)
    b.add_argument("--yaw-convention", default="subject", choices=["image", "subject"],
                   help="엔진의 왼쪽/오른쪽이 발표자 기준이면 subject (behavior_cv_logic.rawDir 주석)")
    b.add_argument("--shots", action="store_true")
    b.add_argument("--force", action="store_true")
    b.add_argument("--include-hd", action="store_true")
    s = sub.add_parser("score")
    s.add_argument("--run", required=True)
    s.add_argument("--yaw-convention", default=None, choices=["image", "subject"])
    s.add_argument("--primary", default=PRIMARY)
    a = ap.parse_args()
    {"ref": cmd_ref, "browser": cmd_browser, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    main()
