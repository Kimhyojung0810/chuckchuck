"""팀 녹화 영상에 행동 엔진을 돌린다 → 1초 라벨 CSV + 영상별 지표 CSV.

정답 실험실(etc/labs/behavior_cv)의 브라우저 어댑터를 그대로 빌려 쓴다 — 헤드리스 크롬 가짜 카메라
(`--use-file-for-fake-video-capture`)로 엔진을 **실제 카메라 경로 그대로** 돌린다. 다만 팀 영상에는 프레임 번호
바코드가 없으니, ffmpeg 로 640폭 · 15fps · y4m 으로 바꾸면서 오른쪽 위 80×6px 에 바코드를 새겨 넣는다(합성 영상과 같은 규칙).
엔진이 본 프레임 번호 ÷ 15 = 원본 영상의 초 → 사람이 매긴 1초 라벨과 같은 시각에 맞는다.

    PY=/home/yehschuck/project/chuckchuck/.venv/bin/python
    $PY etc/labs/behavior_icc/engine_run.py --run real_1101                       # clips/ 의 영상 전부
    $PY etc/labs/behavior_icc/engine_run.py --run real_1101 --only p1_c1,p2_c3 --jobs 2
    $PY etc/labs/behavior_icc/engine_run.py --run x --clips /some/folder --web /data/models/_wt/wt-behavior-cv/main/web

결과: /data/models/_runs/behavior-icc/engine/<run>/
  preds/<clip>.json   어댑터가 돌려준 것 그대로(엔진 줄 · 엔진 자체 집계 · 콘솔)
  labels/<clip>.csv   1초 라벨 (clip, sec, gaze, hand, sway, n_rows)
  engine_metrics.csv  영상별 지표 — 1초 라벨로 낸 값(사람과 같은 함수) + 엔진 자체 값(native_*)
  meta.json           엔진 커밋 · 어댑터 · 시각
포트: 127.0.0.1:8841~8844 (8799 · 8800 · 정답 실험실 8835~8839 는 안 건드린다). 영상 길이만큼 실시간으로 돈다.
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np

from common_icc import (BEHAVIOR_CV, CLIPS, ENGINE, FPS, LABEL_FIELDS, METRICS, ORIENT2GAZE, PRESENT, REPO, VIDEO_EXT,
                        clip_id, clip_metrics, write_csv)

ENGINE_WT = Path("/data/models/_wt/wt-behavior-cv")
PORTS = (8841, 8844)
BAR_BITS = 16
WIDTH = 640


def default_web() -> Path:
    for w in (REPO / "main" / "web", ENGINE_WT / "main" / "web"):
        if (w / "js" / "behavior_cv.js").exists():
            return w
    raise SystemExit("엔진(main/web/js/behavior_cv.js)을 못 찾았어요 — --web 으로 알려 줘요")


def default_adapter(web: Path) -> Path:
    for a in (web.parents[1] / "etc/labs/behavior_cv/web/adapter_default.js", BEHAVIOR_CV / "web/adapter_default.js"):
        if a.exists():
            return a
    raise SystemExit("어댑터를 못 찾았어요")


def find_clips(folder: Path, only: str) -> list[Path]:
    vids = sorted(p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXT and not p.name.startswith("."))
    if only:
        want = {w.strip().lower() for w in only.split(",") if w.strip()}
        vids = [v for v in vids if clip_id(v.name) in want]
    seen: dict[str, Path] = {}
    for v in vids:
        cid = clip_id(v.name)
        if cid in seen:
            print(f"  ! 같은 id 가 두 파일: {seen[cid].name} · {v.name} — 앞의 것만 써요")
            continue
        seen[cid] = v
    return list(seen.values())


# ── 1) 영상 → 640폭 15fps y4m + 바코드 ───────────────────────────────────────
def to_y4m(src: Path, dst: Path) -> dict:
    """ffmpeg 로 바꾸고(회전 메타는 ffmpeg 가 풀어 준다) 바코드를 새긴다. 돌려줌: {w, h, n_frames, duration}"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-an",
           "-vf", f"fps={FPS},scale={WIDTH}:-2:flags=area,format=yuv420p", "-pix_fmt", "yuv420p", "-f", "yuv4mpegpipe", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 실패: " + r.stderr[-400:])
    with open(dst, "rb") as f:
        head = f.readline().decode()
        hdr = f.tell()
    parts = head.split()
    w = int(next(x[1:] for x in parts if x.startswith("W")))
    h = int(next(x[1:] for x in parts if x.startswith("H")))
    fsize = w * h * 3 // 2
    # ffmpeg 의 yuv4mpegpipe 는 프레임마다 "FRAME\n" 만 쓴다 — 아니면 멈춘다(크롬도 같은 가정)
    with open(dst, "rb") as f:
        f.seek(hdr)
        if f.read(6) != b"FRAME\n":
            raise RuntimeError("y4m 프레임 머리가 예상과 달라요")
    stride = 6 + fsize
    n = (dst.stat().st_size - hdr) // stride
    mm = np.memmap(dst, dtype=np.uint8, mode="r+", offset=hdr, shape=(n, stride))
    cs = max(4, w // 160)
    nb = BAR_BITS + 4
    x0 = w - cs * nb
    for i in range(n):
        bits = [1, 0] + [(i >> (BAR_BITS - 1 - k)) & 1 for k in range(BAR_BITS)]
        bits += [sum(bits[2:]) % 2, 1]
        fr = mm[i, 6:]
        yp = fr[: w * h].reshape(h, w)
        for k, b in enumerate(bits):
            yp[0:cs + 2, x0 + k * cs:x0 + (k + 1) * cs] = 255 if b else 0
        cw, ch = w // 2, h // 2
        u = fr[w * h: w * h + cw * ch].reshape(ch, cw)
        v = fr[w * h + cw * ch:].reshape(ch, cw)
        u[0:(cs + 3) // 2, x0 // 2:] = 128
        v[0:(cs + 3) // 2, x0 // 2:] = 128
    mm.flush()
    del mm
    return {"w": w, "h": h, "n_frames": int(n), "duration": n / FPS}


# ── 2) 엔진 줄 → 1초 라벨 ──────────────────────────────────────────────────
def per_second(rows: list[dict], n_sec: int, fps: float = FPS) -> list[dict]:
    """초 s = 프레임 [s·fps, (s+1)·fps). 시선 = 그 초 줄들의 다수(동점이면 초 가운데에 가까운 줄),
    손 · 흔들림 = 자리 있는 줄의 절반 이상이 켜짐. 줄이 없거나 방향을 모르면(예비 모드 'face') gaze=''"""
    by: dict[int, list[dict]] = {}
    for r in rows:
        f = r.get("frame")
        if f is None or not (f >= 0):
            continue
        s = int(f // fps)
        if 0 <= s < n_sec:
            by.setdefault(s, []).append(r)
    out = []
    for s in range(n_sec):
        rs = by.get(s, [])
        gs = [(ORIENT2GAZE.get(r.get("orient") or "", ""), r) for r in rs]
        gs = [(g, r) for g, r in gs if g]
        if not gs:
            out.append({"sec": s, "gaze": "", "hand": 0, "sway": 0, "n_rows": len(rs)})
            continue
        cnt = Counter(g for g, _ in gs)
        top = max(cnt.values())
        tied = {g for g, c in cnt.items() if c == top}
        mid = (s + 0.5) * fps
        gaze = min((abs(r["frame"] - mid), g) for g, r in gs if g in tied)[1]
        pres = [r for g, r in gs if g in PRESENT]
        hand = int(bool(pres) and sum(bool(r.get("gesture")) for r in pres) * 2 >= len(pres))
        sway = int(bool(pres) and sum(bool((r.get("sway") or {}).get("active")) for r in pres) * 2 >= len(pres))
        if gaze == "absent":
            hand = sway = 0
        out.append({"sec": s, "gaze": gaze, "hand": hand, "sway": sway, "n_rows": len(rs)})
    return out


def native_metrics(pred: dict) -> dict:
    """엔진이 리포트에 실제로 내는 값(engine_view.metrics) — 1초 라벨로 다시 낸 값과 견주려고"""
    ev = (pred.get("engine_view") or {})
    m = ev.get("metrics") or {}
    q = ev.get("quality") or {}
    dur_s = (q.get("dur") or 0) / 1000
    pres = q.get("presence")

    def val(k):
        x = m.get(k) or {}
        return x.get("value") if x.get("ok") else None

    down_share = val("down")
    lk = m.get("lookaway") or {}
    return {
        "native_status": ev.get("status"),
        "native_screen_ratio": val("gaze"),
        "native_down_sec": round(down_share * pres * dur_s, 2) if down_share is not None and pres is not None else None,
        "native_hand_ratio": val("gesture"),
        "native_sway_share": val("sway"),
        "native_long_away_n": lk.get("n") if lk.get("ok") else None,
        "native_fps": q.get("fps"), "native_presence": pres,
    }


_PORT = 0


def _init_worker(q) -> None:
    """프로세스마다 포트 하나를 쥔다 — 끝나는 순서가 섞여도 두 편이 같은 포트를 쓰지 않게"""
    global _PORT
    _PORT = q.get()


def run_one(src: str, out_dir: str, web: str, adapter: str, port: int, keep_y4m: bool, work: str) -> dict:
    port = port or _PORT
    sys.path.insert(0, str(BEHAVIOR_CV))
    from browser_adapter import run_clip_browser  # 정답 실험실 것 그대로

    src_p = Path(src)
    cid = clip_id(src_p.name)
    out = Path(out_dir)
    y4m = Path(work) / f"{cid}.y4m"
    t0 = time.time()
    info = to_y4m(src_p, y4m)
    n_sec = int(math.floor(info["duration"] + 1e-6))
    gt = {"w": info["w"], "h": info["h"], "fps": FPS, "n_frames": info["n_frames"], "duration": info["duration"],
          "slides": [{"i": 0, "t0": 0, "t1": info["duration"]}]}
    pred = run_clip_browser(y4m, gt, Path(web), Path(adapter), port=port)
    pred.update(clip=cid, source=src_p.name, conv=info, conv_s=round(time.time() - t0, 1))
    (out / "preds").mkdir(parents=True, exist_ok=True)
    (out / "preds" / f"{cid}.json").write_text(json.dumps(pred, ensure_ascii=False))
    labels = per_second(pred.get("rows") or [], n_sec)
    write_csv(out / "labels" / f"{cid}.csv", [{"clip": cid, **r} for r in labels], LABEL_FIELDS)
    if not keep_y4m:
        y4m.unlink(missing_ok=True)
    got = [r for r in labels if r["gaze"]]
    cm = clip_metrics(got)
    row = {"clip": cid, "file": src_p.name, "dur": round(info["duration"], 2), "n_sec": n_sec, "n_sec_labeled": len(got),
           "rows": len(pred.get("rows") or []), "error": pred.get("error") or "",
           **{k: (round(cm[k], 4) if cm[k] is not None else None) for k, _, _ in METRICS}, **native_metrics(pred)}
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description="팀 영상에 행동 엔진 돌리기 → 1초 라벨 · 영상별 지표")
    ap.add_argument("--run", required=True, help="결과 폴더 이름 (engine/<run>)")
    ap.add_argument("--clips", type=Path, default=CLIPS, help=f"영상 폴더 (기본 {CLIPS})")
    ap.add_argument("--only", default="", help="몇 개만: p1_c1,p2_c3")
    ap.add_argument("--web", type=Path, default=None, help="엔진 main/web (기본: 이 저장소 → 없으면 wt-behavior-cv)")
    ap.add_argument("--adapter", type=Path, default=None)
    ap.add_argument("--jobs", type=int, default=1, help="동시에 몇 개(최대 4) — 많이 돌리면 엔진 fps 가 떨어질 수 있다")
    ap.add_argument("--keep-y4m", action="store_true", help="바꾼 y4m 을 지우지 않는다(한 편 ≈ 0.5GB)")
    ap.add_argument("--skip-done", action="store_true", help="labels/<clip>.csv 가 있으면 건너뛴다")
    a = ap.parse_args()

    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg 가 PATH 에 없어요 (~/.local/bin)")
    web = (a.web or default_web()).resolve()
    adapter = (a.adapter or default_adapter(web)).resolve()
    out = ENGINE / a.run
    work = out / "_y4m"
    clips = find_clips(a.clips, a.only)
    if a.skip_done:
        clips = [c for c in clips if not (out / "labels" / f"{clip_id(c.name)}.csv").exists()]
    if not clips:
        raise SystemExit(f"영상이 없어요: {a.clips}")
    out.mkdir(parents=True, exist_ok=True)
    try:
        commit = subprocess.run(["git", "-C", str(web), "log", "-1", "--format=%h %s"], capture_output=True, text=True).stdout.strip()
    except Exception:
        commit = ""
    meta = {"web": str(web), "engine_commit": commit, "adapter": str(adapter), "clips": [c.name for c in clips],
            "started": datetime.now().isoformat(timespec="seconds"), "fps": FPS, "width": WIDTH}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"엔진 {commit} · {len(clips)}편 → {out}")

    jobs = max(1, min(a.jobs, PORTS[1] - PORTS[0] + 1))
    rows: list[dict] = []
    old = out / "engine_metrics.csv"
    if a.skip_done and old.exists():
        from common_icc import read_csv
        rows = [r for r in read_csv(old)]
    t0 = time.time()
    q = multiprocessing.Manager().Queue()
    for p in range(PORTS[0], PORTS[0] + jobs):
        q.put(p)
    with ProcessPoolExecutor(max_workers=jobs, initializer=_init_worker, initargs=(q,)) as ex:
        futs = {ex.submit(run_one, str(c), str(out), str(web), str(adapter), 0, a.keep_y4m, str(work)): c for c in clips}
        for fu in as_completed(futs):
            c = futs[fu]
            try:
                r = fu.result()
                rows = [x for x in rows if x.get("clip") != r["clip"]] + [r]
                print(f"  {r['clip']:<14} {r['dur']:>6.1f}s 줄 {r['rows']:>4} · 라벨 {r['n_sec_labeled']}/{r['n_sec']}초"
                      f" · 화면 쪽 {r['screen_ratio']} · {r['error'][:80]}")
            except Exception as err:
                print(f"  ! {c.name}: {err}")
    fields = list(rows[0].keys()) if rows else []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    write_csv(out / "engine_metrics.csv", sorted(rows, key=lambda r: r["clip"]), fields)
    if not a.keep_y4m:
        shutil.rmtree(work, ignore_errors=True)
    print(f"끝 {time.time() - t0:.0f}s → {out / 'engine_metrics.csv'}")


if __name__ == "__main__":
    main()
