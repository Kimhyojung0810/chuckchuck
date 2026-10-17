"""사람 코딩 × 엔진 → 일치도 보고서(한국어 markdown) + CSV.

    PY=/home/yehschuck/project/chuckchuck/.venv/bin/python
    $PY etc/labs/behavior_icc/analyze.py --engine real_1101 --out real_1101            # 본 분석
    $PY etc/labs/behavior_icc/analyze.py --engine real_1101 --out train --train        # 훈련 영상 맞춰 보기(어디서 갈렸나)

읽는 것
  ratings/*.csv                    coder.html 에서 받은 CSV (몇 개든, 겹치면 늦게 코딩한 것)
  engine/<run>/labels/*.csv        engine_run.py 의 1초 라벨 · engine/<run>/engine_metrics.csv(엔진 자체 값)
  clips/manifest.csv (있으면)      split=train 인 영상은 본 분석에서 뺀다 · 안경 · 조명 같은 메모
  배정표.csv (있으면)              코더 순서(1차 · 2차)와 빠진 코딩 · 본인 영상 코딩 점검
쓰는 것: report/<out>/report.md · clip_metrics.csv · seconds.csv · summary.json

판정(근거조사 §6-1): 지표마다 「엔진 ↔ 사람 두 명 평균」 ICC(2,1) 절대 일치의 95% CI **하한**으로
  ≥ .75 총점 후보 · .50~.75 베타 · < .50 숨김. 사람끼리 ICC 하한이 .50 아래면 엔진 탓 전에 정의부터 고친다.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

from common_icc import (CLIPS, ENGINE, EVENTS, GAZE, GAZE_KO, METRIC_KO, METRIC_UNIT, METRICS, OUT, PRESENT, RATINGS,
                        REPORTS, SITUATIONS, clip_metrics, is_train, load_engine_labels, load_manifest, load_ratings,
                        person_of, read_csv, runs, situation_of, write_csv)
from stats_icc import bland_altman, f1_of, icc, kappa, seg_match, verdict

NATIVE = {"screen_ratio": "native_screen_ratio", "down_sec": "native_down_sec", "hand_ratio": "native_hand_ratio",
          "long_away_n": "native_long_away_n"}


def f(x, nd=2) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "–"
    return f"{x:.{nd}f}"


def fci(r: dict, key="icc2", lo="lo", hi="hi") -> str:
    if not math.isfinite(r.get(key, math.nan)):
        return "–"
    return f"{r[key]:.2f} [{f(r[lo])}, {f(r[hi])}]"


def load_assign(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    out = {}
    for r in read_csv(path):
        out[r["clip"].strip().lower()] = [x.strip().lower() for x in (r.get("rater_a"), r.get("rater_b")) if x and x.strip()]
    return out


def to_map(seq: list[dict]) -> dict[int, dict]:
    return {r["sec"]: r for r in seq if r["gaze"]}


def sub(m: dict[int, dict], secs: list[int]) -> list[dict]:
    return [m[s] for s in secs]


def analyze(a) -> Path:
    manifest = load_manifest(a.manifest)
    assign = load_assign(a.assign)
    ratings = load_ratings(a.ratings)
    eng_dir = ENGINE / a.engine if a.engine else None
    eng = load_engine_labels(eng_dir / "labels") if eng_dir else {}
    native = {}
    if eng_dir and (eng_dir / "engine_metrics.csv").exists():
        native = {r["clip"]: r for r in read_csv(eng_dir / "engine_metrics.csv")}
    eng_meta = json.loads((eng_dir / "meta.json").read_text()) if eng_dir and (eng_dir / "meta.json").exists() else {}
    out = REPORTS / a.out
    out.mkdir(parents=True, exist_ok=True)
    warns: list[str] = []

    clips_all = sorted(set(ratings) | set(eng) | set(assign))
    if a.train:
        return train_check(ratings, manifest, out, clips_all)
    clips = [c for c in clips_all if not is_train(c, manifest)]
    skipped_train = [c for c in clips_all if is_train(c, manifest)]

    per_clip: list[dict] = []
    sec_rows: list[dict] = []
    pooled = defaultdict(lambda: {"x": [], "y": []})      # (label, pair) → 줄
    segs = defaultdict(lambda: [0, 0, 0])                  # (event, pair, mode) → tp, n_ref, n_pred
    for c in clips:
        rs = ratings.get(c, {})
        order = [r for r in assign.get(c, []) if r in rs] + sorted(r for r in rs if r not in assign.get(c, []))
        if len(order) > 2:
            warns.append(f"{c}: 코더가 {len(order)}명이에요({', '.join(order)}) — 앞의 두 명({order[0]}, {order[1]})만 써요")
        A = to_map(rs[order[0]]) if len(order) > 0 else None
        B = to_map(rs[order[1]]) if len(order) > 1 else None
        E = to_map(eng[c]) if c in eng else None
        p = person_of(c)
        for r in order:
            if p and r == p:
                warns.append(f"{c}: 본인({r})이 코딩했어요 — 기대 효과가 섞여요")
        if c in assign:
            miss = [r for r in assign[c] if r not in rs]
            if miss:
                warns.append(f"{c}: 배정된 코더 {', '.join(miss)} 의 CSV 가 아직 없어요")
        if E is None:
            warns.append(f"{c}: 엔진 라벨이 없어요(engine_run.py 를 이 영상에 안 돌렸어요)")
        srcs = {k: m for k, m in (("A", A), ("B", B), ("E", E)) if m is not None}
        if not srcs:
            continue
        secs = sorted(set.intersection(*[set(m) for m in srcs.values()]))
        n_full = max(len(m) for m in srcs.values())
        for k, m in srcs.items():
            if k in ("A", "B") and E is not None and len(m) < 0.9 * len(E):
                who = order[0] if k == "A" else order[1]
                warns.append(f"{c}: {who} 가 {len(m)}/{len(E)}초만 코딩했어요 — 겹치는 초로만 셈")
        row = {"clip": c, "person": p, "situation": situation_of(c) or "", "rater_a": order[0] if order else "",
               "rater_b": order[1] if len(order) > 1 else "", "n_sec": len(secs), "n_sec_max": n_full,
               "note": "; ".join(f"{k}={v}" for k, v in manifest.get(c, {}).items() if k in ("glasses", "light", "device", "note") and v)}
        mets = {k: clip_metrics(sub(m, secs)) for k, m in srcs.items()}
        for key, _, _ in METRICS:
            va = mets["A"][key] if "A" in mets else None
            vb = mets["B"][key] if "B" in mets else None
            ve = mets["E"][key] if "E" in mets else None
            vals = [x for x in (va, vb) if x is not None]
            row[f"{key}_a"] = va
            row[f"{key}_b"] = vb
            row[f"{key}_mean"] = (sum(vals) / len(vals)) if vals else None
            row[f"{key}_engine"] = ve
            nk = NATIVE.get(key)
            nv = native.get(c, {}).get(nk) if nk else None
            row[f"{key}_native"] = float(nv) if nv not in (None, "") else None
        per_clip.append(row)
        # 1초 표
        for s in secs:
            sec_rows.append({"clip": c, "sec": s, **{f"{k}_{x}": srcs[k][s][x] for k in srcs for x in ("gaze", "hand", "sway")}})
        # κ 줄 모으기
        pairs = [("A", "B")] + [("E", k) for k in ("A", "B") if k in srcs]
        for x, y in pairs:
            if x not in srcs or y not in srcs:
                continue
            tag = "사람A↔사람B" if x == "A" else "엔진↔사람"
            for s in secs:
                rx, ry = srcs[x][s], srcs[y][s]
                pooled[("gaze", tag)]["x"].append(rx["gaze"])
                pooled[("gaze", tag)]["y"].append(ry["gaze"])
                if rx["gaze"] in PRESENT and ry["gaze"] in PRESENT:
                    for lab in ("hand", "sway"):
                        pooled[(lab, tag)]["x"].append(rx[lab])
                        pooled[(lab, tag)]["y"].append(ry[lab])
        if "A" in srcs and "B" in srcs and "E" in srcs:
            for s in secs:
                ra, rb, re_ = srcs["A"][s], srcs["B"][s], srcs["E"][s]
                if ra["gaze"] == rb["gaze"]:
                    pooled[("gaze", "엔진↔사람 합의")]["x"].append(re_["gaze"])
                    pooled[("gaze", "엔진↔사람 합의")]["y"].append(ra["gaze"])
                for lab in ("hand", "sway"):
                    if ra["gaze"] in PRESENT and rb["gaze"] in PRESENT and re_["gaze"] in PRESENT and ra[lab] == rb[lab]:
                        pooled[(lab, "엔진↔사람 합의")]["x"].append(re_[lab])
                        pooled[(lab, "엔진↔사람 합의")]["y"].append(ra[lab])
        # 구간 F1 (1초 라벨 → 구간; 기준 = 사람)
        seg_pairs = [(ref, "E", "엔진↔사람") for ref in ("A", "B") if ref in srcs and "E" in srcs]
        if "A" in srcs and "B" in srcs:
            seg_pairs.append(("A", "B", "사람A↔사람B"))
        for ev, _, pred, mn in EVENTS:
            seg = {k: runs(sub(m, secs), pred, mn) for k, m in srcs.items()}
            for ref, other, tag in seg_pairs:
                for mode, kw in (("±1초", {"tol": 1.0}), ("IoU≥.5", {"iou": 0.5})):
                    m = seg_match(seg[ref], seg[other], **kw)
                    acc = segs[(ev, tag, mode)]
                    acc[0] += m["tp"]
                    acc[1] += m["n_ref"]
                    acc[2] += m["n_pred"]

    # ── 지표별 ICC · Bland–Altman ──
    summary = {"made": datetime.now().isoformat(timespec="seconds"), "engine": eng_meta.get("engine_commit", ""),
               "n_clips": len(per_clip), "train_skipped": skipped_train, "metrics": {}}
    for key, ko, unit in METRICS:
        col = lambda suf: np.array([r[f"{key}_{suf}"] if r[f"{key}_{suf}"] is not None else np.nan for r in per_clip], float)  # noqa: E731
        A_, B_, M_, E_, N_ = col("a"), col("b"), col("mean"), col("engine"), col("native")
        rr = icc(np.c_[A_, B_])
        er = icc(np.c_[E_, M_])
        nr = icc(np.c_[N_, M_]) if key in NATIVE else None
        ba_e = bland_altman(E_, M_)
        ba_r = bland_altman(A_, B_)
        v, why = verdict(er.get("lo"))
        notes = []
        if math.isfinite(rr.get("lo", math.nan)) and rr["lo"] < 0.5:
            notes.append("사람끼리도 하한 .50 아래 — 엔진 탓 전에 정의부터 고쳐요")
        if er["n"] and er["n"] < 20:
            notes.append(f"영상 {er['n']}개 — CI 가 넓어요(20개 이상 권장)")
        if er.get("why"):
            notes.append(er["why"])
        summary["metrics"][key] = {"label": ko, "unit": unit, "verdict": v, "verdict_why": why, "engine_vs_mean": er,
                                   "rater_vs_rater": rr, "native_vs_mean": nr, "ba_engine": ba_e, "ba_raters": ba_r, "notes": notes}

    # ── κ ──
    kap = {}
    for (lab, tag), d in pooled.items():
        labels = GAZE if lab == "gaze" else [0, 1]
        kap[f"{lab}|{tag}"] = kappa(d["x"], d["y"], labels) | {"label": lab, "pair": tag}
    summary["kappa"] = kap
    seg_out = {}
    for (ev, tag, mode), (tp, nr_, np_) in segs.items():
        seg_out[f"{ev}|{tag}|{mode}"] = f1_of(tp, nr_, np_) | {"event": ev, "pair": tag, "mode": mode}
    summary["segments"] = seg_out
    summary["warnings"] = sorted(set(warns))

    # ── 파일 ──
    fields = list(per_clip[0].keys()) if per_clip else ["clip"]
    write_csv(out / "clip_metrics.csv", per_clip, fields)
    sf = sorted({k for r in sec_rows for k in r}, key=lambda k: (k not in ("clip", "sec"), k))
    write_csv(out / "seconds.csv", sec_rows, sf)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=float))
    (out / "report.md").write_text(report_md(a, summary, per_clip, eng_meta), encoding="utf-8")
    return out / "report.md"


# ── 보고서 ─────────────────────────────────────────────────────────────────
def report_md(a, S: dict, per_clip: list[dict], meta: dict) -> str:
    L = []
    title = a.title or "행동 지표 사람 검증 — 예비 신뢰도 점검"
    L += [f"# {title}", "",
          f"만든 때 {S['made']} · 엔진 `{meta.get('engine_commit', '?')}` · 분석 영상 {S['n_clips']}개"
          + (f" (훈련 영상 {len(S['train_skipped'])}개는 뺌)" if S["train_skipped"] else ""), ""]
    if a.note:
        L += [f"> {a.note}", ""]
    L += ["## 0. 판정", "",
          "| 지표 | 엔진 ↔ 사람 평균 ICC(2,1) [95% CI] | **판정** | 사람끼리 ICC(2,1) [95% CI] | 엔진 − 사람 평균 차 · 95% 일치 한계 | 영상 |",
          "|---|---|---|---|---|---|"]
    for key, ko, unit in METRICS:
        m = S["metrics"][key]
        er, rr, ba = m["engine_vs_mean"], m["rater_vs_rater"], m["ba_engine"]
        pct = unit == "비율"
        sc = 100 if pct else 1
        u = "%p" if pct else unit
        bas = "–" if not math.isfinite(ba["bias"]) else f"{ba['bias'] * sc:+.1f}{u} [{ba['loa_lo'] * sc:+.1f}, {ba['loa_hi'] * sc:+.1f}]"
        L.append(f"| {ko} | {fci(er)} | **{m['verdict']}** | {fci(rr)} | {bas} | {er['n']} |")
    L += ["", "판정은 **95% CI 하한**으로 정한다(점 추정치가 아니다): ≥ .75 **총점 후보** · .50~.75 **베타**(참고로만, 가중치 0) · < .50 **숨김**.",
          "사람끼리 ICC 하한이 .50 아래인 지표는 엔진보다 **정의(코딩 기준)** 를 먼저 고친다.", ""]
    notes = [(METRIC_KO[k], n) for k in S["metrics"] for n in S["metrics"][k]["notes"]]
    if notes:
        L += ["주의:", ""] + [f"- {k}: {n}" for k, n in notes] + [""]

    L += ["## 1. 읽는 법", "",
          "- **ICC(2,1) 절대 일치** — 영상 사이 차이 중 평가자(엔진 · 사람)가 「같은 값」을 낸 몫. 1 이면 완전히 같고, 0 이면 영상 차이를 못 가린다. "
          "순위만 같고 값이 일정하게 어긋나도(치우침) 깎인다. Koo & Li(2016): .50 아래 나쁨 · .50~.75 보통 · .75~.90 좋음 · .90 넘으면 아주 좋음.",
          "- **엔진 ↔ 사람 평균**: 사람 두 명 값의 평균을 기준으로 엔진을 잰다(사람 한 명보다 덜 흔들린다). 그래서 사람끼리 ICC 보다 높게 나올 수 있다.",
          "- **Bland–Altman**: 엔진 − 사람 평균의 평균(치우침)과 95% 일치 한계(평균 ± 1.96 SD). 한계 안에 영상 95% 가 든다는 뜻이다. 비율 지표는 %p 로 적었다.",
          "- 지표는 사람과 엔진 모두 **같은 1초 라벨에서 같은 함수**(common_icc.clip_metrics)로 냈다. 세 출처(사람 A · 사람 B · 엔진)가 모두 라벨을 가진 초만 쓴다.",
          "- 코더 짝이 영상마다 다르다(배정표). 그래서 ICC(2,1) 의 「평가자」는 1차 코더 · 2차 코더 자리다. 더 보수적인 한 방향 ICC(1,1) 도 §2 에 같이 적었다.",
          "- 한계: 화자 5명 · 팀원이 코더(기대 효과) · 대본 상황이라 실제 발표보다 행동이 크다. 「검증」이 아니라 **예비 신뢰도 점검**으로 부른다. "
          "문턱을 이 자료로 고치면 그 뒤의 수치는 「같은 자료로 맞춘 값」이라고 적는다.", ""]

    L += ["## 2. 지표별 자세히", "",
          "| 지표 | 엔진↔사람 ICC(2,1) | ICC(1,1) | 엔진 자체 값↔사람 ICC(2,1) | 사람끼리 ICC(2,1) | ICC(1,1) | 치우침 [95% CI] | 평균 |차| | 사람끼리 치우침 · 일치 한계 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for key, ko, unit in METRICS:
        m = S["metrics"][key]
        er, rr, nr, ba, bar = m["engine_vs_mean"], m["rater_vs_rater"], m["native_vs_mean"], m["ba_engine"], m["ba_raters"]
        sc = 100 if unit == "비율" else 1
        bias = "–" if not math.isfinite(ba["bias"]) else f"{ba['bias'] * sc:+.1f} [{ba['bias_lo'] * sc:+.1f}, {ba['bias_hi'] * sc:+.1f}]"
        mad = "–" if not math.isfinite(ba.get("mean_abs", math.nan)) else f"{ba['mean_abs'] * sc:.1f}"
        rbias = "–" if not math.isfinite(bar["bias"]) else f"{bar['bias'] * sc:+.1f} [{bar['loa_lo'] * sc:+.1f}, {bar['loa_hi'] * sc:+.1f}]"
        L.append(f"| {ko} | {fci(er)} | {fci(er, 'icc1', 'icc1_lo', 'icc1_hi')} | {fci(nr) if nr else '–'} | {fci(rr)} | "
                 f"{fci(rr, 'icc1', 'icc1_lo', 'icc1_hi')} | {bias} | {mad} | {rbias} |")
    L += ["", "「엔진 자체 값」 = 엔진이 리포트 카드에 실제로 내는 값(프레임 단위 · engine_metrics.csv 의 native_*). "
          "1초 라벨로 다시 낸 값과 크게 다르면 집계 방식 차이를 먼저 본다. 흔들림은 엔진이 「창 비율」로 내서 초와 견줄 수 없어 비웠다. 비율 지표의 차이는 %p.", ""]

    L += ["## 3. 1초 라벨 일치 (Cohen κ)", "",
          "모든 영상의 초를 모아 잰다. 손 · 흔들림은 둘 다 「자리 있음」인 초만. 「엔진↔사람 합의」 = 두 사람이 같은 라벨을 준 초에서 엔진이 맞았나.", "",
          "| 라벨 | 짝 | κ | 일치율 | 초 |", "|---|---|---|---|---|"]
    name = {"gaze": "시선(4갈래)", "hand": "손 움직임", "sway": "몸 흔들림"}
    for lab in ("gaze", "hand", "sway"):
        for tag in ("사람A↔사람B", "엔진↔사람", "엔진↔사람 합의"):
            k = S["kappa"].get(f"{lab}|{tag}")
            if k:
                L.append(f"| {name[lab]} | {tag} | {f(k['kappa'])} | {f(k['po'] * 100 if math.isfinite(k['po']) else math.nan, 1)}% | {k['n']} |")
    k = S["kappa"].get("gaze|엔진↔사람 합의")
    if k and k["n"]:
        L += ["", "시선 혼동 행렬 — 행 = 엔진, 열 = 사람 합의 (초)", "",
              "| 엔진 \\ 사람 | " + " | ".join(GAZE_KO[g] for g in GAZE) + " |", "|---|" + "---|" * len(GAZE)]
        for i, g in enumerate(GAZE):
            L.append(f"| {GAZE_KO[g]} | " + " | ".join(str(x) for x in k["cm"][i]) + " |")
    L += ["", "κ 읽기(Landis & Koch 1977): .41~.60 보통 · .61~.80 상당 · .81 넘으면 거의 완벽. 근거조사의 비교값: Wörtwein 2015 프레임 눈맞춤 α = .751.", ""]

    L += ["## 4. 구간 사건 F1", "",
          "1초 라벨에서 구간을 뽑아(긴 이탈 = 다른 곳 · 아래가 4초 이상, 나머지는 2초 이상) 사람 구간을 기준으로 엔진 구간을 맞춘다. "
          "「±1초」 = 시작 · 끝이 둘 다 1초 안(근거조사 §6-1), 「IoU≥.5」 = 겹침이 절반 넘음(느슨한 기준). 사람끼리는 A 를 기준으로 B 를 맞춘 값.", "",
          "| 사건 | 짝 | 기준 | F1 | 정밀도 | 재현율 | 사람 구간 | 엔진(또는 B) 구간 |", "|---|---|---|---|---|---|---|---|"]
    evname = {e[0]: e[1] for e in EVENTS}
    for ev, _, _, _ in EVENTS:
        for tag in ("엔진↔사람", "사람A↔사람B"):
            for mode in ("±1초", "IoU≥.5"):
                s = S["segments"].get(f"{ev}|{tag}|{mode}")
                if s:
                    L.append(f"| {evname[ev]} | {tag} | {mode} | {f(s['f1'])} | {f(s['precision'])} | {f(s['recall'])} | {s['n_ref']} | {s['n_pred']} |")
    L += ["", "엔진의 흔들림은 8초 창으로 재서 켜짐이 늦다 — ±1초 F1 이 낮고 IoU F1 이 높으면 「있다는 건 맞는데 시작 · 끝이 밀린다」는 뜻이다.", ""]

    # 상황별
    L += ["## 5. 상황별 차이 (엔진 − 사람 평균, 영상 평균)", "",
          "| 상황 | 영상 | " + " | ".join(METRIC_KO[k] for k, _, _ in METRICS) + " |", "|---|---|" + "---|" * len(METRICS)]
    by = defaultdict(list)
    for r in per_clip:
        by[r["situation"] or "기타"].append(r)
    for sit in sorted(by, key=lambda x: (isinstance(x, str), x)):
        rows = by[sit]
        cells = []
        for k, _, unit in METRICS:
            d = [r[f"{k}_engine"] - r[f"{k}_mean"] for r in rows if r[f"{k}_engine"] is not None and r[f"{k}_mean"] is not None]
            sc = 100 if unit == "비율" else 1
            cells.append(f"{np.mean(d) * sc:+.1f}" if d else "–")
        L.append(f"| {SITUATIONS.get(sit, sit)} | {len(rows)} | " + " | ".join(cells) + " |")
    L += ["", "비율은 %p, 나머지는 초 · 번. 상황 하나에서만 크게 어긋나면 그 행동(예: ③ 흔들기)에서 엔진이 약한 것이다.", ""]

    L += ["## 6. 영상별 값", "", "칸 = 사람 A / 사람 B / **엔진**. 비율은 %.", "",
          "| 영상 | 코더 | 초 | " + " | ".join(METRIC_KO[k] for k, _, _ in METRICS) + " |", "|---|---|---|" + "---|" * len(METRICS)]
    for r in per_clip:
        cells = []
        for k, _, unit in METRICS:
            sc = 100 if unit == "비율" else 1
            nd = 0
            g = lambda x: "–" if x is None else f"{x * sc:.{nd}f}"  # noqa: E731
            cells.append(f"{g(r[f'{k}_a'])} / {g(r[f'{k}_b'])} / **{g(r[f'{k}_engine'])}**")
        L.append(f"| {r['clip']} | {r['rater_a']} · {r['rater_b']} | {r['n_sec']} | " + " | ".join(cells) + " |")
    L.append("")
    if S["warnings"]:
        L += ["## 7. 점검할 것", ""] + [f"- {w}" for w in S["warnings"]] + [""]
    L += ["## 8. 재현", "", "```bash", "PY=/home/yehschuck/project/chuckchuck/.venv/bin/python",
          f"$PY etc/labs/behavior_icc/analyze.py --engine {a.engine} --out {a.out}"
          + (f" --ratings {a.ratings}" if Path(a.ratings) != RATINGS else "")
          + (f" --manifest {a.manifest}" if Path(a.manifest) != CLIPS / "manifest.csv" else "")
          + (f" --assign {a.assign}" if Path(a.assign) != OUT / "배정표.csv" else ""),
          "```", "",
          f"- 엔진: `{meta.get('web', '?')}` · `{meta.get('engine_commit', '?')}` · 어댑터 `{meta.get('adapter', '?')}`",
          f"- 파일: `clip_metrics.csv`(영상 × 지표 × 출처) · `seconds.csv`(1초 라벨 나란히) · `summary.json`(모든 수치)",
          "- 공식: ICC(2,1) 와 95% CI 는 McGraw & Wong(1996) — pingouin 0.7 · Shrout & Fleiss(1979) 표와 맞춰 봤다(`test_stats.py`).", ""]
    return "\n".join(L)


# ── 훈련 영상: 어디서 갈렸나 ─────────────────────────────────────────────────
def train_check(ratings: dict, manifest: dict, out: Path, clips_all: list[str]) -> Path:
    L = ["# 훈련 영상 맞춰 보기", "", "같은 영상을 코딩한 사람끼리 어디서 갈렸는지 본다. 갈린 초를 같이 다시 보고 기준을 맞춘 뒤 본 코딩을 시작한다.", ""]
    for c in [c for c in clips_all if is_train(c, manifest)]:
        rs = ratings.get(c, {})
        names = sorted(rs)
        L += [f"## {c} — 코더 {', '.join(names) or '없음'}", ""]
        if len(names) < 2:
            L += ["두 명 넘게 코딩해야 견줄 수 있어요.", ""]
            continue
        maps = {n: to_map(rs[n]) for n in names}
        secs = sorted(set.intersection(*[set(m) for m in maps.values()]))
        L += ["| 짝 | 시선 κ | 손 κ | 흔들림 κ |", "|---|---|---|---|"]
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                x, y = maps[names[i]], maps[names[j]]
                kg = kappa([x[s]["gaze"] for s in secs], [y[s]["gaze"] for s in secs], GAZE)["kappa"]
                both = [s for s in secs if x[s]["gaze"] in PRESENT and y[s]["gaze"] in PRESENT]
                kh = kappa([x[s]["hand"] for s in both], [y[s]["hand"] for s in both], [0, 1])["kappa"]
                ks = kappa([x[s]["sway"] for s in both], [y[s]["sway"] for s in both], [0, 1])["kappa"]
                L.append(f"| {names[i]} · {names[j]} | {f(kg)} | {f(kh)} | {f(ks)} |")
        L += ["", "갈린 초 (시선 · 손 · 흔들림):", "", "| 초 | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
        for s in secs:
            vals = [(maps[n][s]["gaze"], maps[n][s]["hand"], maps[n][s]["sway"]) for n in names]
            if len(set(vals)) > 1:
                L.append(f"| {s} | " + " | ".join(f"{GAZE_KO[g]} · 손{'○' if h else '–'} · 흔{'○' if w else '–'}" for g, h, w in vals) + " |")
        L.append("")
    p = out / "train_check.md"
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main() -> None:
    ap = argparse.ArgumentParser(description="사람 코딩 × 엔진 일치도 보고서")
    ap.add_argument("--engine", default="", help="engine/<run> 이름 (engine_run.py --run 과 같게)")
    ap.add_argument("--ratings", type=Path, default=RATINGS)
    ap.add_argument("--manifest", type=Path, default=CLIPS / "manifest.csv")
    ap.add_argument("--assign", type=Path, default=OUT / "배정표.csv")
    ap.add_argument("--out", required=True, help="report/<out>")
    ap.add_argument("--train", action="store_true", help="훈련 영상만 — 코더끼리 갈린 초 보기")
    ap.add_argument("--title", default="")
    ap.add_argument("--note", default="", help="보고서 머리에 붙일 한 줄")
    a = ap.parse_args()
    p = analyze(a)
    print(p)
    if not a.train:
        s = json.loads((p.parent / "summary.json").read_text())
        for k, m in s["metrics"].items():
            er = m["engine_vs_mean"]
            print(f"  {m['label']:<18} ICC {f(er['icc2'])} [{f(er['lo'])}, {f(er['hi'])}] → {m['verdict']}"
                  f"  · 사람끼리 {f(m['rater_vs_rater']['icc2'])} · n={er['n']}")


if __name__ == "__main__":
    main()
