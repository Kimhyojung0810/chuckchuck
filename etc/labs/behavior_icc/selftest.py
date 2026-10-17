"""처음부터 끝까지 스스로 점검 — 합성 영상(정답 실험실) + 가짜 코더 두 명으로 촬영 → 코딩 → 실행 → 결과 흐름 전체를 돌린다.
팀은 진짜 영상과 진짜 CSV 만 넣으면 된다는 것을 확인하려는 것이다(수치 자체는 합성이라 의미 없음).

    PY=/home/yehschuck/project/chuckchuck/.venv/bin/python
    PATH=$HOME/.local/bin:$PATH $PY etc/labs/behavior_icc/selftest.py               # 엔진까지 (합성 26편 실시간 ≈ 10분, --jobs 3)
    $PY etc/labs/behavior_icc/selftest.py --reuse-engine                          # 엔진 결과는 그대로, 코더 흉내 · 분석만
    $PY etc/labs/behavior_icc/selftest.py --coder-only                            # 코딩판(coder.html)만 헤드리스 크롬으로

하는 일
 1. 합성 영상(/data/models/_runs/behavior-cv/lab/clips/*.y4m)을 「팀 녹화」 폴더에 이어 붙이고 engine_run.py 로 돌린다
    (ffmpeg 변환 · 바코드 새기기 · 가짜 카메라 · 1초 라벨 — 진짜 영상과 같은 길).
 2. 정답(.gt.json)에서 1초 참값을 내고, 잡음 · 경계 늦음 · 치우침이 다른 가짜 코더 sim1 · sim2 를 만든다 → coder.html 과 같은 CSV.
    d0_clean 은 훈련 영상으로 두고 sim1~3 이 코딩한다(analyze --train 점검).
 3. analyze.py 로 보고서. 4. 음성 대조: 엔진 라벨을 영상끼리 뒤섞으면 판정이 「총점 후보」로 나오면 안 된다.
 5. coder.html 을 헤드리스 크롬으로 열어 키로 코딩 · CSV 받기 · 다시 읽기까지 확인(화면 캡처 남김).
결과: /data/models/_runs/behavior-icc/selftest/ (clips · ratings · manifest) · engine/selftest · report/selftest(_shuffled · _train)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from common_icc import ENGINE, HERE, OUT, RATING_FIELDS, REPORTS, write_csv

LAB_CLIPS = Path("/data/models/_runs/behavior-cv/lab/clips")
ST = OUT / "selftest"
PY = sys.executable
F2G = {"front": "screen", "left": "away", "right": "away", "down": "down", "none": "absent"}

# 가짜 코더 — (시선 뒤바꿈, 손 뒤바꿈, 흔들림 뒤바꿈, 바뀐 순간 늦게 알아챔, 손 「있음」 놓침(치우침), 씨앗)
RATERS = {
    "sim1": dict(pg=0.04, ph=0.05, ps=0.02, edge=0.35, miss_hand=0.00, seed=11),
    "sim2": dict(pg=0.07, ph=0.08, ps=0.03, edge=0.45, miss_hand=0.15, seed=22),
    "sim3": dict(pg=0.10, ph=0.10, ps=0.05, edge=0.50, miss_hand=0.05, seed=33),
}


def truth_seconds(gt: dict) -> list[dict]:
    """정답 프레임 → 1초 참값(다수결)"""
    by: dict[int, list[dict]] = {}
    for fr in gt["frames"]:
        by.setdefault(int(fr["t"] + 1e-6), []).append(fr)
    n = int(gt["duration"] + 1e-6)
    out = []
    for s in range(n):
        fs = by.get(s, [])
        if not fs:
            continue
        g = Counter(F2G.get(f["label"], "absent") for f in fs).most_common(1)[0][0]
        h = int(sum(1 for f in fs if f.get("gesture")) * 2 >= len(fs))
        w = int(sum(1 for f in fs if f.get("sway")) * 2 >= len(fs))
        if g == "absent":
            h = w = 0
        out.append({"sec": s, "gaze": g, "hand": h, "sway": w})
    return out


def simulate(truth: list[dict], p: dict, rng: random.Random) -> list[dict]:
    out = []
    conf = {"screen": [("away", 0.7), ("down", 0.3)], "away": [("screen", 0.8), ("down", 0.2)],
            "down": [("screen", 0.6), ("away", 0.4)], "absent": [("away", 1.0)]}
    for i, t in enumerate(truth):
        r = dict(t)
        prev = truth[i - 1] if i else None
        for k in ("gaze", "hand", "sway"):
            if prev and prev[k] != t[k] and rng.random() < p["edge"]:
                r[k] = prev[k]          # 바뀐 순간을 1초 늦게 알아챔
        if rng.random() < (p["pg"] / 3 if r["gaze"] == "absent" else p["pg"]):
            opts = conf[r["gaze"]]
            x = rng.random()
            acc = 0.0
            for lab, w in opts:
                acc += w
                if x <= acc:
                    r["gaze"] = lab
                    break
        if rng.random() < p["ph"]:
            r["hand"] = 1 - r["hand"]
        if r["hand"] and rng.random() < p["miss_hand"]:
            r["hand"] = 0
        if rng.random() < p["ps"]:
            r["sway"] = 1 - r["sway"]
        if r["gaze"] == "absent":
            r["hand"] = r["sway"] = 0
        out.append(r)
    return out


def write_rating(path: Path, rater: str, clip: str, labs: list[dict], dur: float) -> None:
    rows = [{"rater": rater, "clip": clip, "sec": r["sec"], "gaze": r["gaze"], "hand": r["hand"], "sway": r["sway"],
             "file": f"{clip}.y4m", "dur": f"{dur:.2f}", "coded_at": "2026-10-17T00:00:00Z"} for r in labs]
    write_csv(path, rows, RATING_FIELDS)


def sh(cmd: list[str], **kw) -> None:
    print("$", " ".join(cmd))
    r = subprocess.run(cmd, cwd=HERE, **kw)
    if r.returncode != 0:
        raise SystemExit(f"실패({r.returncode}): {' '.join(cmd)}")


def stage_clips(sel: str) -> list[Path]:
    clips = sorted(LAB_CLIPS.glob("*.y4m"))
    if sel:
        want = [w.strip() for w in sel.split(",") if w.strip()]
        clips = [c for c in clips if any(c.stem.startswith(w) for w in want)]
    d = ST / "clips"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    for c in clips:
        (d / c.name).symlink_to(c)
    return clips


def coder_e2e() -> dict:
    """coder.html 을 헤드리스 크롬으로 — 영상 열기 → 키로 6초 코딩 → 새로 고침 뒤 이어짐 → CSV 받기 → load_ratings 로 읽기"""
    sys.path.insert(0, str(HERE.parent / "behavior_cv"))
    from common import ensure_chrome_libs  # 정답 실험실의 크롬 라이브러리 경로
    from playwright.sync_api import sync_playwright

    ensure_chrome_libs()
    work = ST / "coder"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    vid = work / "p1_c4_selftest.webm"   # 이름 규칙 확인: id 는 p1_c4
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(LAB_CLIPS / "s08_gesture.y4m"), "-t", "12", "-c:v", "libvpx", "-b:v", "1M", str(vid)],
                   check=True)
    port = 8849
    srv = subprocess.Popen([PY, str(HERE / "serve.py"), "--port", str(port), "--no-open"], stdout=subprocess.PIPE, text=True)
    line = srv.stdout.readline()
    url = line.split("코딩판: ")[1].split()[0]
    res: dict = {"url": url}
    try:
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            ctx = br.new_context(viewport={"width": 1366, "height": 860}, accept_downloads=True)
            page = ctx.new_page()
            errs: list[str] = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.goto(url)
            page.fill("#rater", "p3")
            page.press("#rater", "Tab")
            page.set_input_files("#fileIn", str(vid))
            page.wait_for_function("window.__coder && window.__coder.state.n > 0", timeout=15000)
            st = page.evaluate("({n: __coder.state.n, clip: __coder.state.clip, cur: __coder.state.cur})")
            res["loaded"] = st
            page.mouse.click(5, 5)
            plan = [("Digit1", []), ("Digit1", ["KeyH"]), ("Digit2", []), ("Digit3", ["KeyS"]), ("Digit4", ["KeyH"]), (None, [])]
            for g, extra in plan:
                if g:
                    page.keyboard.press(g)
                for k in extra:
                    page.keyboard.press(k)
                page.keyboard.press("Space")
                page.wait_for_timeout(150)
            page.wait_for_timeout(300)
            page.screenshot(path=str(work / "coder.png"))
            res["after_keys"] = page.evaluate("JSON.parse(JSON.stringify(__coder.state.labels))")
            # 새로 고침 → 같은 파일을 다시 열면 이어짐
            page.reload()
            page.set_input_files("#fileIn", str(vid))
            page.wait_for_function("window.__coder && window.__coder.state.n > 0", timeout=15000)
            res["resumed_at"] = page.evaluate("__coder.state.cur")
            res["resumed_n"] = page.evaluate("Object.keys(__coder.state.labels).length")
            with page.expect_download() as dl:
                page.click("#exportBtn")
            p = work / "ratings" / dl.value.suggested_filename
            p.parent.mkdir(parents=True, exist_ok=True)
            dl.value.save_as(str(p))
            res["csv"] = str(p)
            res["errors"] = errs
            br.close()
    finally:
        srv.terminate()
        srv.wait(timeout=5)
    from common_icc import load_ratings

    got = load_ratings(work / "ratings")
    labs = got.get("p1_c4", {}).get("p3", [])
    res["parsed"] = [(r["sec"], r["gaze"], r["hand"], r["sway"]) for r in labs]
    want = [(0, "screen", 0, 0), (1, "screen", 1, 0), (2, "away", 1, 0), (3, "down", 1, 1), (4, "absent", 0, 0), (5, "absent", 0, 0)]
    # 2초: 앞 초(손 있음)를 이어받고 시선만 바꿈 → 손 1 · 3초: 이어받은 손 1 + S → 흔들림 1 · 4초: 자리 없음이면 손 · 흔들림 0(H 는 무시)
    # 5초: 키 없이 Space → 앞 초(자리 없음)를 이어받아 저장
    res["ok"] = res["parsed"] == want and res["resumed_n"] == 6 and res["resumed_at"] == 6 and not res["errors"]
    res["want"] = want
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description="ICC 키트 스스로 점검")
    ap.add_argument("--clips", default="", help="합성 영상 일부만 (예: s03,s05,s08)")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--reuse-engine", action="store_true")
    ap.add_argument("--coder-only", action="store_true")
    ap.add_argument("--no-coder", action="store_true")
    a = ap.parse_args()
    env = dict(os.environ, PATH=f"{Path.home() / '.local/bin'}:{os.environ.get('PATH', '')}")
    checks: dict[str, bool] = {}

    if not a.coder_only:
        clips = stage_clips(a.clips)
        print(f"합성 영상 {len(clips)}편")
        if not a.reuse_engine:
            sh([PY, "engine_run.py", "--run", "selftest", "--clips", str(ST / "clips"), "--jobs", str(a.jobs)], env=env)
        # 가짜 코더
        rdir = ST / "ratings"
        if rdir.exists():
            shutil.rmtree(rdir)
        man = []
        assign = []
        for c in clips:
            gt = json.loads(c.with_suffix(".gt.json").read_text())
            truth = truth_seconds(gt)
            train = c.stem == "d0_clean"
            who = ["sim1", "sim2", "sim3"] if train else ["sim1", "sim2"]
            for r in who:
                rng = random.Random(f"{RATERS[r]['seed']}-{c.stem}")
                write_rating(rdir / f"icc_{r}_{c.stem}.csv", r, c.stem, simulate(truth, RATERS[r], rng), gt["duration"])
            write_rating(ST / "truth" / f"{c.stem}.csv", "truth", c.stem, truth, gt["duration"])
            man.append({"clip": c.stem, "split": "train" if train else "eval", "note": "합성"})
            if not train:
                assign.append({"clip": c.stem, "rater_a": "sim1", "rater_b": "sim2"})
        write_csv(ST / "manifest.csv", man, ["clip", "split", "note"])
        write_csv(ST / "배정표.csv", assign, ["clip", "rater_a", "rater_b"])
        common = ["--ratings", str(rdir), "--manifest", str(ST / "manifest.csv"), "--assign", str(ST / "배정표.csv")]
        sh([PY, "analyze.py", "--engine", "selftest", "--out", "selftest", *common, "--title", "스스로 점검 — 합성 영상 · 가짜 코더",
            "--note", "합성 영상(한 사람 3D 스캔)과 정답에서 만든 가짜 코더로 흐름만 점검한 것 — 수치로 판정하지 않는다."])
        sh([PY, "analyze.py", "--out", "selftest_train", "--train", *common])
        # 음성 대조 — 엔진 라벨을 영상끼리 돌려 붙인다
        src = ENGINE / "selftest" / "labels"
        dst = ENGINE / "selftest_shuffled" / "labels"
        if dst.parent.exists():
            shutil.rmtree(dst.parent)
        dst.mkdir(parents=True)
        files = sorted(src.glob("*.csv"))
        names = [f.stem for f in files]
        rot = names[len(names) // 2:] + names[: len(names) // 2]
        for f, other in zip(files, rot):
            txt = f.read_text().replace(f"{f.stem},", f"{other},")
            (dst / f"{other}.csv").write_text(txt)
        sh([PY, "analyze.py", "--engine", "selftest_shuffled", "--out", "selftest_shuffled", *common, "--title", "음성 대조 — 엔진 라벨을 영상끼리 뒤섞음"])
        s1 = json.loads((REPORTS / "selftest" / "summary.json").read_text())
        s2 = json.loads((REPORTS / "selftest_shuffled" / "summary.json").read_text())
        rr = s1["metrics"]["screen_ratio"]["rater_vs_rater"]
        checks["가짜 코더끼리 화면 쪽 비율 ICC 하한 ≥ .75"] = rr["lo"] >= 0.75
        checks["뒤섞은 엔진은 어느 지표도 「총점 후보」가 아님"] = all(m["verdict"] != "총점 후보" for m in s2["metrics"].values())
        checks["뒤섞은 엔진 화면 쪽 비율 ICC < 원래"] = s2["metrics"]["screen_ratio"]["engine_vs_mean"]["icc2"] < s1["metrics"]["screen_ratio"]["engine_vs_mean"]["icc2"]
        checks["훈련 점검 파일"] = (REPORTS / "selftest_train" / "train_check.md").exists()
        checks["보고서"] = (REPORTS / "selftest" / "report.md").exists()
        for k, m in s1["metrics"].items():
            er = m["engine_vs_mean"]
            print(f"  {m['label']:<18} 엔진↔사람 {er['icc2']:.2f} [{er['lo']:.2f}, {er['hi']:.2f}] → {m['verdict']}"
                  f" · 사람끼리 {m['rater_vs_rater']['icc2']:.2f} · 뒤섞음 {s2['metrics'][k]['engine_vs_mean']['icc2']:.2f} → {s2['metrics'][k]['verdict']}")
    if not a.no_coder:
        r = coder_e2e()
        print("코딩판:", json.dumps({k: r[k] for k in ("loaded", "parsed", "resumed_at", "resumed_n", "errors", "csv")}, ensure_ascii=False))
        checks["코딩판 키 · 이어받기 · 이어 하기 · CSV"] = r["ok"]
        (ST / "coder_check.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
    print()
    for k, ok in checks.items():
        print(("  통과 " if ok else "  실패 ") + k)
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
