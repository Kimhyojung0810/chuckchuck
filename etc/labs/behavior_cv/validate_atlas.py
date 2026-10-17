"""아틀라스 검증 — 그린 머리를 OpenCV Haar 가 「기대대로」 잡는지, 각도 · 얼굴 크기별로 잰다.

    PYTHONPATH=/data/models/_runs/behavior-cv/pylib .venv/bin/python etc/labs/behavior_cv/validate_atlas.py

결과
- assets/atlas/calib.json — 정면 Haar 상자 폭(512 그림 단위) · 목 축 기준 얼굴 가운데 위치. gen.py 가 얼굴 폭(GT)을 맞출 때 쓴다.
- lab/atlas_validation.md · .json — yaw × pitch × 얼굴 폭(px) 별 검출률: frontal(default · alt2) · profile(원본=코가 왼쪽, 뒤집음=코가 오른쪽) · eye
"""
from __future__ import annotations

import json

import numpy as np

from common import ATLAS, LAB

import cv2  # noqa: E402  (common 이 pylib 경로를 붙인 뒤)

HC = cv2.data.haarcascades


def load_index() -> dict:
    return json.loads((ATLAS / "index.json").read_text())


def sprite(idx: dict, yaw: int, pitch: int, eyes: str = "open", tint=None) -> tuple[np.ndarray, np.ndarray]:
    e = idx["poses"][f"{yaw},{pitch},{eyes}"]
    im = cv2.imread(str(ATLAS / e["file"]), cv2.IMREAD_UNCHANGED)
    if tint is not None:
        im = im.copy()
        im[..., :3] = np.clip(im[..., :3].astype(np.float32) * np.array(tint, np.float32), 0, 255).astype(np.uint8)
    return im, np.array(e["anchor"], float)


def put(bg: np.ndarray, rgba: np.ndarray, x: int, y: int) -> None:
    h, w = rgba.shape[:2]
    H, W = bg.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    s = rgba[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32)
    a = s[..., 3:4] / 255.0
    bg[y0:y1, x0:x1] = (s[..., :3] * a + bg[y0:y1, x0:x1] * (1 - a)).astype(np.uint8)


def calibrate(idx: dict) -> dict:
    im, anc = sprite(idx, 0, 0)
    body = cv2.imread(str(ATLAS / idx["body"]["file"]), cv2.IMREAD_UNCHANGED)
    ban = np.array(idx["body"]["anchor"], float)
    can = np.full((700, 700, 3), 150, np.uint8)
    ax, ay = 350, 420
    put(can, body, int(ax - ban[0]), int(ay - ban[1]))
    put(can, im, int(ax - anc[0]), int(ay - anc[1]))
    g = cv2.equalizeHist(cv2.cvtColor(can, cv2.COLOR_BGR2GRAY))
    f = cv2.CascadeClassifier(HC + "haarcascade_frontalface_default.xml").detectMultiScale(g, 1.05, 4, minSize=(60, 60))
    if not len(f):
        raise SystemExit("정면 그림에서 얼굴을 못 잡았어요 — 아틀라스를 다시 그려 보세요")
    x, y, w, h = max(f, key=lambda r: r[2])
    cal = {"haar_fw": float(w), "face_dx": float(x + w / 2 - ax), "face_dy": float(y + h / 2 - ay), "haar_fh": float(h)}
    (ATLAS / "calib.json").write_text(json.dumps(cal, indent=1))
    return cal


def main() -> None:
    idx = load_index()
    cal = calibrate(idx)
    print("calib", cal)
    C = {k: cv2.CascadeClassifier(HC + f) for k, f in {
        "frontal": "haarcascade_frontalface_default.xml", "alt2": "haarcascade_frontalface_alt2.xml",
        "profile": "haarcascade_profileface.xml", "eye": "haarcascade_eye.xml"}.items()}
    body = cv2.imread(str(ATLAS / idx["body"]["file"]), cv2.IMREAD_UNCHANGED)
    ban = np.array(idx["body"]["anchor"], float)
    yaws = list(range(-90, 91, 15))
    pitches = [-50, -40, -30, -20, -10, 0, 10, 20]
    fws = [40, 64, 100]  # 처리 해상도(320~640 폭)에서의 얼굴 폭 px
    rows = []
    for fw in fws:
        s = fw / cal["haar_fw"]
        W, H = int(fw * 6), int(fw * 4)
        bsm = cv2.resize(body, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        for p in pitches:
            for yw in yaws:
                im, anc = sprite(idx, yw, p)
                sm = cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                yy = np.linspace(170, 120, H)[:, None, None]
                can = np.broadcast_to(yy, (H, W, 3)).astype(np.uint8).copy()
                ax, ay = W // 2, int(H * 0.38 - cal["face_dy"] * s)
                put(can, bsm, int(ax - ban[0] * s), int(ay - ban[1] * s))
                put(can, sm, int(ax - anc[0] * s), int(ay - anc[1] * s))
                g = cv2.equalizeHist(cv2.cvtColor(can, cv2.COLOR_BGR2GRAY))
                mn = (max(20, int(fw * 0.5)),) * 2
                fr = C["frontal"].detectMultiScale(g, 1.1, 4, minSize=mn)
                a2 = C["alt2"].detectMultiScale(g, 1.1, 3, minSize=mn)
                pl = C["profile"].detectMultiScale(g, 1.1, 3, minSize=mn)
                pr = C["profile"].detectMultiScale(cv2.flip(g, 1), 1.1, 3, minSize=mn)
                eyes = 0
                if len(fr):
                    x, y, w, h = max(fr, key=lambda r: r[2])
                    roi = g[y:y + int(h * 0.6), x:x + w]
                    eyes = len(C["eye"].detectMultiScale(roi, 1.1, 3, minSize=(max(8, w // 8),) * 2))
                    # 큰 얼굴 자르기에서 다시 (원본 해상도 쪽이 클 때 쓰는 방법) — 120px 로 키워 본다
                eyes_up = 0
                if len(fr):
                    x, y, w, h = max(fr, key=lambda r: r[2])
                    roi = can[y:y + int(h * 0.6), x:x + w]
                    if roi.size:
                        up = cv2.resize(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), (120, int(120 * roi.shape[0] / roi.shape[1])))
                        eyes_up = len(C["eye"].detectMultiScale(cv2.equalizeHist(up), 1.1, 3, minSize=(14, 14)))
                rows.append({"fw": fw, "yaw": yw, "pitch": p, "frontal": int(len(fr) > 0), "alt2": int(len(a2) > 0),
                             "prof_noseleft": int(len(pl) > 0), "prof_noseright": int(len(pr) > 0),
                             "eyes": eyes, "eyes_up120": eyes_up})
    (LAB / "atlas_validation.json").write_text(json.dumps({"calib": cal, "rows": rows}, indent=0))
    lines = ["# 아틀라스 Haar 검증", "", f"calib: {cal}", "",
             "칸 = F(정면 default) a(alt2) L(profile 원본: 코가 영상 왼쪽) R(profile 뒤집음: 코가 영상 오른쪽) e(눈 2개, 키운 자르기) · '.' = 아무것도", ""]
    for fw in fws:
        lines += [f"## 얼굴 폭 {fw}px", "", "| pitch \\ yaw | " + " | ".join(str(y) for y in yaws) + " |", "|---" * (len(yaws) + 1) + "|"]
        for p in pitches:
            cells = []
            for yw in yaws:
                r = next(r for r in rows if r["fw"] == fw and r["yaw"] == yw and r["pitch"] == p)
                c = ("F" if r["frontal"] else "") + ("a" if r["alt2"] else "") + ("L" if r["prof_noseleft"] else "") + \
                    ("R" if r["prof_noseright"] else "") + ("e" if r["eyes_up120"] >= 2 else "")
                cells.append(c or ".")
            lines.append(f"| {p} | " + " | ".join(cells) + " |")
        lines.append("")
    # 눈 캐스케이드: 안경 · 피부 톤 / 정면 검출: 피부 톤 (얼굴 폭 64 · 100px, yaw -15~15 · pitch 0~10)
    from scenarios import TONES
    extra = []
    for fw in (64, 100):
        s = fw / cal["haar_fw"]
        W, H = int(fw * 6), int(fw * 4)
        bsm = cv2.resize(body, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        for tone, tint in TONES.items():
            for eyes in ("open", "openg"):
                fr_n = ey_n = n = raw_n = cl_n = 0
                for p in (0, 5, 10):
                    for yw in (-15, -10, -5, 0, 5, 10, 15):
                        im, anc = sprite(idx, yw, p, eyes, tint)
                        sm = cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                        yy = np.linspace(170, 120, H)[:, None, None]
                        can = np.broadcast_to(yy, (H, W, 3)).astype(np.uint8).copy()
                        ax, ay = W // 2, int(H * 0.38 - cal["face_dy"] * s)
                        put(can, bsm, int(ax - ban[0] * s), int(ay - ban[1] * s))
                        put(can, sm, int(ax - anc[0] * s), int(ay - anc[1] * s))
                        g = cv2.equalizeHist(cv2.cvtColor(can, cv2.COLOR_BGR2GRAY))
                        fr = C["frontal"].detectMultiScale(g, 1.1, 4, minSize=(int(fw * 0.5),) * 2)
                        g0 = cv2.cvtColor(can, cv2.COLOR_BGR2GRAY)
                        raw_n += len(C["frontal"].detectMultiScale(g0, 1.1, 4, minSize=(int(fw * 0.5),) * 2)) > 0
                        gc = cv2.createCLAHE(2.0, (4, 4)).apply(g0)
                        cl_n += len(C["frontal"].detectMultiScale(gc, 1.1, 4, minSize=(int(fw * 0.5),) * 2)) > 0
                        n += 1
                        if len(fr):
                            fr_n += 1
                            x, y, w, h = max(fr, key=lambda r: r[2])
                            roi = can[y:y + int(h * 0.6), x:x + w]
                            up = cv2.equalizeHist(cv2.resize(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), (120, int(120 * roi.shape[0] / roi.shape[1]))))
                            ey_n += len(C["eye"].detectMultiScale(up, 1.1, 3, minSize=(14, 14))) >= 2
                extra.append({"fw": fw, "tone": tone, "glasses": eyes.endswith("g"), "frontal": round(fr_n / n, 3), "frontal_noeq": round(raw_n / n, 3), "frontal_clahe": round(cl_n / n, 3), "eyes2_given_face": round(ey_n / max(1, fr_n), 3)})
    lines += ["## 피부 톤 · 안경 (정면 근처 21자세)", "", "| 얼굴 폭 | 톤 | 안경 | 정면 검출(equalizeHist) | 평활 없음 | CLAHE | 눈 2개(검출된 얼굴 중) |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {e['fw']} | {e['tone']} | {'예' if e['glasses'] else '아니오'} | {e['frontal']:.0%} | {e['frontal_noeq']:.0%} | {e['frontal_clahe']:.0%} | {e['eyes2_given_face']:.0%} |" for e in extra]
    (LAB / "atlas_validation.json").write_text(json.dumps({"calib": cal, "rows": rows, "tone_glasses": extra}, indent=0))
    (LAB / "atlas_validation.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
