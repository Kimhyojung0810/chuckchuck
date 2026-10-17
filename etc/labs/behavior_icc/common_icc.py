"""사람 검증(ICC) 키트 공통 — 경로 · 1초 라벨 규약 · 라벨 → 영상별 지표 · CSV 읽고 쓰기.

라벨은 1초에 하나다(초 s = 영상의 [s, s+1) 구간). 사람(coder.html)과 엔진(engine_run.py)이 **같은 모양**으로 남기고,
영상별 지표도 **같은 함수**(clip_metrics)로 낸다 — 정의가 달라서 생기는 차이를 엔진 탓으로 돌리지 않으려고.

  gaze  : screen(화면 쪽) · away(다른 곳) · down(아래) · absent(자리 없음) · ''(모름 — 엔진이 그 초에 본 프레임이 없을 때)
  hand  : 1(손 움직임 있음) · 0(없음)   — 자리 없음이면 0
  sway  : 1(몸 흔들림 있음) · 0(없음)   — 자리 없음이면 0
"""
from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = Path(os.environ.get("BEHAVIOR_ICC_DIR", "/data/models/_runs/behavior-icc"))
CLIPS = OUT / "clips"          # 팀이 녹화 파일을 넣는 곳 (p1_c1.mov …) + manifest.csv
RATINGS = OUT / "ratings"      # coder.html 에서 받은 CSV 를 넣는 곳
ENGINE = OUT / "engine"        # engine_run.py 결과 (<run>/preds · labels · engine_metrics.csv)
REPORTS = OUT / "report"       # analyze.py 결과 (<run>/report.md …)
PY_EXTRA = [Path("/data/models/_runs/behavior-cv/pylib")]   # scipy · numpy · cv2 (venv 에 scipy 가 없다)
BEHAVIOR_CV = HERE.parent / "behavior_cv"                    # 정답 실험실 — 브라우저 어댑터를 그대로 빌려 쓴다

for _p in PY_EXTRA:
    if _p.exists() and str(_p) not in sys.path:
        sys.path.append(str(_p))

FPS = 15                       # 엔진에 넣는 영상은 모두 15fps 로 맞춘다 (합성 실험실과 같게)
GAZE = ["screen", "away", "down", "absent"]
GAZE_KO = {"screen": "화면 쪽", "away": "다른 곳", "down": "아래", "absent": "자리 없음", "": "모름"}
PRESENT = {"screen", "away", "down"}
LONG_AWAY_SEC = 4              # 「3초 넘게」 = 1초 라벨이 4칸 넘게 이어짐(≥ 4) — 엔진 lookAwayMs 3000 과 같은 뜻을 1초 단위로

# 엔진 줄의 orient → 1초 라벨
ORIENT2GAZE = {"front": "screen", "left": "away", "right": "away", "away": "away", "down": "down", "none": "absent",
               "정면": "screen", "왼쪽": "away", "오른쪽": "away", "아래": "down", "없음": "absent"}

# 영상별 지표 — (키, 한국어 이름, 단위)
METRICS = [
    ("screen_ratio", "화면 쪽 비율", "비율"),
    ("down_sec", "아래 본 시간", "초"),
    ("hand_ratio", "손 움직임 비율", "비율"),
    ("sway_sec", "몸 흔들림 시간", "초"),
    ("long_away_n", "긴 이탈 횟수(3초 넘게)", "번"),
]
METRIC_KO = {k: ko for k, ko, _ in METRICS}
METRIC_UNIT = {k: u for k, _, u in METRICS}

# 구간 사건 — (키, 이름, 그 초가 사건인가, 최소 길이 초)
EVENTS = [
    ("long_away", "긴 이탈(3초 넘게)", lambda r: r["gaze"] in ("away", "down"), LONG_AWAY_SEC),
    ("down", "아래 보기(2초 이상)", lambda r: r["gaze"] == "down", 2),
    ("sway", "몸 흔들림(2초 이상)", lambda r: r["gaze"] in PRESENT and r["sway"] == 1, 2),
    ("hand", "손 움직임(2초 이상)", lambda r: r["gaze"] in PRESENT and r["hand"] == 1, 2),
]

SITUATIONS = {1: "① 평소처럼", 2: "② 원고 자주 보기", 3: "③ 몸 흔들기", 4: "④ 손짓 많이", 5: "⑤ 화면 밖 자주 보기", 6: "⑥ 자유"}
CLIP_RE = re.compile(r"(p\d+_c\d+|train\d+)", re.I)
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".y4m"}

RATING_FIELDS = ["rater", "clip", "sec", "gaze", "hand", "sway", "file", "dur", "coded_at"]
LABEL_FIELDS = ["clip", "sec", "gaze", "hand", "sway", "n_rows"]


def clip_id(name: str) -> str:
    """파일 이름 → 영상 id. p1_c3_1020.mov → p1_c3 · 규칙에 안 맞으면 확장자 뺀 이름 그대로"""
    stem = Path(name).stem
    m = CLIP_RE.search(stem)
    return m.group(1).lower() if m else stem


def person_of(cid: str) -> str:
    m = re.match(r"(p\d+)_c\d+", cid)
    return m.group(1) if m else ""


def situation_of(cid: str) -> int | None:
    m = re.match(r"p\d+_c(\d+)", cid)
    return int(m.group(1)) if m else None


def norm_label(r: dict) -> dict:
    """CSV 한 줄 → {sec, gaze, hand, sway} (자리 없음이면 손 · 흔들림 0)"""
    g = (r.get("gaze") or "").strip().lower()
    g = {"화면 쪽": "screen", "다른 곳": "away", "아래": "down", "자리 없음": "absent"}.get(g, g)
    if g not in GAZE:
        g = ""
    h = 1 if str(r.get("hand", "")).strip() in ("1", "true", "있음") else 0
    s = 1 if str(r.get("sway", "")).strip() in ("1", "true", "있음") else 0
    if g == "absent":
        h = s = 0
    return {"sec": int(float(r["sec"])), "gaze": g, "hand": h, "sway": s}


def runs(seq: list[dict], pred, min_len: int) -> list[tuple[int, int]]:
    """1초 라벨 줄(초 순서, 빈 초 없이) → pred 가 참인 연속 구간 [s0, s1) 중 길이 ≥ min_len. 빠진 초(라벨 없음)는 끊는다"""
    out: list[tuple[int, int]] = []
    s0: int | None = None
    prev: int | None = None

    def close() -> None:
        nonlocal s0
        if s0 is not None and prev is not None and prev + 1 - s0 >= min_len:
            out.append((s0, prev + 1))
        s0 = None

    for r in seq:
        if prev is not None and r["sec"] != prev + 1:
            close()
        if r["gaze"] != "" and pred(r):
            if s0 is None:
                s0 = r["sec"]
        else:
            close()
        prev = r["sec"]
    close()
    return out


def clip_metrics(seq: list[dict]) -> dict:
    """1초 라벨 → 영상별 지표 5개. 분모 = 자리 있는 초(화면 쪽 · 다른 곳 · 아래). 자리 있는 초가 없으면 비율은 None"""
    pres = [r for r in seq if r["gaze"] in PRESENT]
    n = len(pres)
    return {
        "screen_ratio": (sum(r["gaze"] == "screen" for r in pres) / n) if n else None,
        "down_sec": float(sum(r["gaze"] == "down" for r in pres)),
        "hand_ratio": (sum(r["hand"] for r in pres) / n) if n else None,
        "sway_sec": float(sum(r["sway"] for r in pres)),
        "long_away_n": float(len(runs(seq, lambda r: r["gaze"] in ("away", "down"), LONG_AWAY_SEC))),
        "n_sec": len(seq), "n_present": n,
    }


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def load_ratings(folder: Path) -> dict[str, dict[str, list[dict]]]:
    """ratings/*.csv 전부 → {clip: {rater: [라벨 줄(초 순서)]}}. 같은 (rater, clip, sec) 가 여러 번이면 coded_at 이 늦은 것"""
    best: dict[tuple[str, str, int], tuple[str, dict]] = {}
    for p in sorted(Path(folder).glob("*.csv")):
        for r in read_csv(p):
            if not r.get("rater") or not r.get("clip") or r.get("sec") in (None, ""):
                continue
            rater = r["rater"].strip().lower()
            cid = clip_id(r["clip"].strip())
            lab = norm_label(r)
            if lab["gaze"] == "":
                continue
            key = (cid, rater, lab["sec"])
            stamp = r.get("coded_at") or ""
            if key not in best or stamp >= best[key][0]:
                best[key] = (stamp, lab)
    out: dict[str, dict[str, list[dict]]] = {}
    for (cid, rater, _), (_, lab) in best.items():
        out.setdefault(cid, {}).setdefault(rater, []).append(lab)
    for cid in out:
        for rater in out[cid]:
            out[cid][rater].sort(key=lambda x: x["sec"])
    return out


def load_engine_labels(folder: Path) -> dict[str, list[dict]]:
    out = {}
    for p in sorted(Path(folder).glob("*.csv")):
        rows = [norm_label(r) | {"n_rows": int(r.get("n_rows") or 0)} for r in read_csv(p)]
        if rows:
            out[clip_id(p.name)] = sorted(rows, key=lambda x: x["sec"])
    return out


def load_manifest(path: Path) -> dict[str, dict]:
    """clips/manifest.csv(있으면) → {clip: {person, situation, split, glasses, light, device, note}}"""
    if not path or not Path(path).exists():
        return {}
    out = {}
    for r in read_csv(Path(path)):
        cid = clip_id(r.get("clip") or r.get("file") or "")
        if cid:
            out[cid] = {k: (v or "").strip() for k, v in r.items()}
    return out


def is_train(cid: str, manifest: dict) -> bool:
    m = manifest.get(cid, {})
    return cid.startswith("train") or (m.get("split", "").lower() in ("train", "훈련"))
