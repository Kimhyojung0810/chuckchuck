"""파이썬 참조 엔진 — 브라우저 엔진(behavior_cv_worker.js)과 **같은 고전 OpenCV 순서**를 opencv-python 으로.

목적: 엔진이 아직 없을 때 실험실 · 채점기를 돌려 보고, 어떤 기법(옆얼굴 캐스케이드 · 눈 캐스케이드 ·
CamShift 메움 · 평활 · 흐름 기반 손짓)이 합성 정답에서 실제로 먹히는지 숫자로 본다. 문턱은 CFG 한곳에.

한 프레임 → 한 줄(채점기 계약과 같은 모양, README 「엔진 계약」):
  t · frame · present · orient(front/left/right/down/none/away) · orient_raw · face[x,y,w,h](0~1) · src ·
  scores{frontal,profile_l,profile_r} · eyes · dy_fw · sway{active,freq,amp_fw,ratio} · motion · motion_level ·
  gesture · gesture_score · quality{bright,sharp,face_w} · ms
「away」= 정면은 아닌데 방향을 모름(얼굴을 놓쳤지만 CamShift 로 머리는 있음). 방향 채점에선 틀림, 이탈 구간에선 「정면 아님」.

    PYTHONPATH=/data/models/_runs/behavior-cv/pylib .venv/bin/python etc/labs/behavior_cv/ref_engine.py CLIP.y4m --variant full
"""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

import common  # noqa: F401
import cv2  # noqa: E402

from y4m import Y4MReader  # noqa: E402

HC = cv2.data.haarcascades


@dataclass
class Cfg:
    proc_fps: float = 5.0          # 엔진 목표 5fps
    proc_w: int = 320              # 메인이 워커로 보내는 폭
    frontal: str = "haarcascade_frontalface_default.xml"
    frontal_neighbors: int = 4
    scale_factor: float = 1.1
    min_face_frac: float = 0.06    # 처리 폭 대비 최소 얼굴 폭
    eq: str = "hist"               # hist | clahe | none
    use_profile: bool = True
    profile_neighbors: int = 3
    profile_margin: float = 0.0    # 옆 점수 - 정면 점수 > margin 이면 옆
    use_down_dy: bool = True
    down_dy: float = 0.22          # 얼굴 가운데가 기준보다 얼굴 폭의 몇 배 내려가면 아래
    use_eyes: bool = False         # 눈 0개면 아래로 치는 단서 (얼굴이 원본에서 60px 넘을 때만)
    use_track: bool = True         # 얼굴을 놓치면 CamShift 로 머리 덩어리를 따라간다
    track_max_s: float = 6.0
    side_hold_s: float = 1.5       # 놓치기 직전 옆이 보였으면 그 방향을 이 시간만큼 유지
    absent_after_s: float = 1.0    # 아무 증거 없이 이만큼 지나면 없음
    smooth_k: int = 3              # 최근 k 개 다수결
    continuity: bool = True        # 놓친 직후 멀리 떨어진 작은 얼굴(포스터)로 갈아타지 않기
    sway_win_s: float = 8.0
    sway_band: tuple = (0.3, 1.5)
    sway_amp: float = 0.10         # 얼굴 폭 배수
    sway_ratio: float = 0.55
    flow_w: int = 160
    motion_still: float = 0.15     # fw/s
    motion_much: float = 0.60
    gest_thr: float = 0.035        # 움직이는 피부 화소 / 얼굴 넓이
    gest_flow: float = 0.6         # 흐름 크기 문턱(160폭 px/프레임)
    frontal_only: bool = False     # 지금 main 부스 방식(정면 검출 = 정면, 아니면 없음)
    gest_rel: bool = True          # 몸통 중앙 흐름을 뺀 상대 흐름으로 손짓
    gest_open: bool = True         # 3x3 열기로 점 잡음 지우기
    gest_face_pad: float = 0.6     # 얼굴 상자 좌우로 얼굴 폭의 이만큼 빼기
    gest_neck: float = 1.0         # 얼굴 아래로 얼굴 폭의 이만큼(목 · 깃)까지 빼기
    gest_bgskin: bool = False      # 오래 그 자리에 있는 피부색(화분 · 나무 · 책)을 배경 피부로 빼기 + 손 크기 덩어리만
    static_reject: bool = False    # 3초 넘게 꼼짝 않는 얼굴(포스터 · 책장 헛얼굴)은 발표자로 고르지 않는다


VARIANTS = {
    "booth_v0": Cfg(frontal_only=True, use_profile=False, use_down_dy=False, use_track=False, smooth_k=1, continuity=False),
    "prof_raw": Cfg(use_down_dy=False, use_track=False, smooth_k=1, continuity=False),
    "full": Cfg(),
    "full_notrack": Cfg(use_track=False),
    "full_nosmooth": Cfg(smooth_k=1),
    "full_alt2": Cfg(frontal="haarcascade_frontalface_alt2.xml", frontal_neighbors=3),
    "full_clahe": Cfg(eq="clahe"),
    "full_eyes": Cfg(use_eyes=True),
    "full_w480": Cfg(proc_w=480),
    "full_gest_v0": Cfg(gest_rel=False, gest_open=False, gest_face_pad=0.4, gest_neck=0.5),   # 손짓 첫 판(절대 흐름)
    "v2": Cfg(frontal="haarcascade_frontalface_alt2.xml", frontal_neighbors=3, static_reject=True, gest_bgskin=True),
    "v2_clahe": Cfg(frontal="haarcascade_frontalface_alt2.xml", frontal_neighbors=3, static_reject=True, gest_bgskin=True, eq="clahe"),
    "v2_nobgskin": Cfg(frontal="haarcascade_frontalface_alt2.xml", frontal_neighbors=3, static_reject=True),
}


def iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x0, y0, x1, y1 = max(ax, bx), max(ay, by), min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    return inter / max(1e-6, aw * ah + bw * bh - inter)


class RefEngine:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg
        self.cf = cv2.CascadeClassifier(HC + cfg.frontal)
        self.cp = cv2.CascadeClassifier(HC + "haarcascade_profileface.xml")
        self.ce = cv2.CascadeClassifier(HC + "haarcascade_eye.xml")
        self.clahe = cv2.createCLAHE(2.0, (4, 4))
        self.last_box = None          # 처리 해상도 px
        self.last_seen_t = -1e9
        self.last_any_t = -1e9
        self.last_side = None
        self.last_side_t = -1e9
        self.base_cy = None           # 정면일 때 얼굴 가운데 y (fw 단위 비교)
        self.fw_hist = deque(maxlen=50)
        self.raw_hist = deque(maxlen=max(1, cfg.smooth_k))
        self.x_hist = deque()         # (t, cx px, fw px)
        self.prev_small = None
        self.prev_t = None
        self.hist = None              # CamShift 색 히스토그램
        self.track_win = None
        self.gest_hist = deque(maxlen=3)
        self.state = "none"
        self.skin_ema = None
        self.spots = []               # [(t, cx, cy, w)] 최근 정면 검출 — 꼼짝 않는 헛얼굴 찾기

    # ── 검출 ──
    def _detect(self, eq):
        c = self.cfg
        h, w = eq.shape
        mn = max(16, int(c.min_face_frac * w))
        out = []
        r = self.cf.detectMultiScale3(eq, c.scale_factor, c.frontal_neighbors, minSize=(mn, mn), outputRejectLevels=True)
        for b, wt in zip(r[0], r[2]):
            out.append({"box": tuple(int(v) for v in b), "kind": "frontal", "w": float(np.ravel(wt)[0])})
        if c.use_profile:
            r = self.cp.detectMultiScale3(eq, c.scale_factor, c.profile_neighbors, minSize=(mn, mn), outputRejectLevels=True)
            for b, wt in zip(r[0], r[2]):
                out.append({"box": tuple(int(v) for v in b), "kind": "profile_l", "w": float(np.ravel(wt)[0])})
            fl = cv2.flip(eq, 1)
            r = self.cp.detectMultiScale3(fl, c.scale_factor, c.profile_neighbors, minSize=(mn, mn), outputRejectLevels=True)
            for b, wt in zip(r[0], r[2]):
                x, y, bw, bh = (int(v) for v in b)
                out.append({"box": (w - x - bw, y, bw, bh), "kind": "profile_r", "w": float(np.ravel(wt)[0])})
        return out

    def _cluster(self, dets):
        """겹치는 정면 · 옆 상자를 한 얼굴로 묶고, 종류별 최고 점수를 남긴다"""
        groups = []
        for d in sorted(dets, key=lambda d: -d["box"][2]):
            for g in groups:
                if iou(g["box"], d["box"]) > 0.25 or (abs((g["box"][0] + g["box"][2] / 2) - (d["box"][0] + d["box"][2] / 2)) < 0.5 * g["box"][2]
                                                    and abs((g["box"][1] + g["box"][3] / 2) - (d["box"][1] + d["box"][3] / 2)) < 0.5 * g["box"][3]):
                    g["scores"][d["kind"]] = max(g["scores"].get(d["kind"], -9), d["w"])
                    if d["kind"] == "frontal":
                        g["box"] = d["box"]
                    break
            else:
                groups.append({"box": d["box"], "scores": {d["kind"]: d["w"]}})
        return groups

    def _static(self, g, t) -> bool:
        """이 상자 자리에 최근 3초 넘게 거의 같은 상자가 있었나 (중심 표준편차 < 얼굴 폭의 1%)"""
        x, y, w, h = g["box"]
        cx, cy = x + w / 2, y + h / 2
        near = [s for s in self.spots if abs(s[1] - cx) < 0.5 * w and abs(s[2] - cy) < 0.5 * w and abs(s[3] - w) < 0.3 * w]
        if len(near) < 12 or t - near[0][0] < 3.0:
            return False
        xs = np.array([[s[1], s[2]] for s in near])
        return float(xs.std(axis=0).max()) < 0.01 * w

    def _pick(self, groups, t, W):
        if not groups:
            return None
        c = self.cfg
        if c.static_reject:
            for g in groups:
                if "frontal" in g["scores"]:
                    x, y, w, h = g["box"]
                    self.spots.append((t, x + w / 2, y + h / 2, w))
            self.spots = [s for s in self.spots if s[0] > t - 6.0]
            live = [g for g in groups if not self._static(g, t)]
            if self.last_box is not None and not live:
                return None
            groups = live or groups
        if self.last_box is not None and c.continuity and t - self.last_seen_t < 2.0:
            lx, ly, lw, lh = self.last_box
            lc = (lx + lw / 2, ly + lh / 2)

            def near(g):
                x, y, w, h = g["box"]
                d = math.hypot(x + w / 2 - lc[0], y + h / 2 - lc[1]) / max(lw, 1)
                return d, w / max(lw, 1)
            ok = [(near(g)[0], g) for g in groups if near(g)[0] < 1.6 and 0.55 < near(g)[1] < 1.8]
            if ok:
                return min(ok, key=lambda x: x[0])[1]
            return None   # 멀리 있는 다른 얼굴로 갈아타지 않는다 (포스터 · 옆사람)
        # 처음: 크고 가운데 가까운 얼굴
        return max(groups, key=lambda g: g["box"][2] * (1.2 - abs(g["box"][0] + g["box"][2] / 2 - W / 2) / W))

    # ── CamShift ──
    def _track_init(self, hsv, box):
        x, y, w, h = box
        roi = hsv[y:y + h, x:x + w]
        m = cv2.inRange(roi, (0, 40, 40), (180, 255, 255))
        self.hist = cv2.calcHist([roi], [0, 1], m, [24, 16], [0, 180, 0, 256])
        cv2.normalize(self.hist, self.hist, 0, 255, cv2.NORM_MINMAX)
        self.track_win = (x, y, w, h)

    def _track(self, hsv):
        if self.hist is None or self.track_win is None:
            return None
        bp = cv2.calcBackProject([hsv], [0, 1], self.hist, [0, 180, 0, 256], 1)
        x, y, w, h = self.track_win
        H, W = bp.shape
        crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 1)
        try:
            rot, win = cv2.CamShift(bp, (max(0, x), max(0, y), max(4, w), max(4, h)), crit)
        except cv2.error:
            return None
        wx, wy, ww, wh = win
        if ww < 4 or wh < 4:
            return None
        mass = float(bp[wy:wy + wh, wx:wx + ww].mean()) if ww * wh > 0 else 0.0
        lw = self.last_box[2] if self.last_box is not None else w
        if mass < 25 or not (0.4 * lw < ww < 2.5 * lw):
            return None
        self.track_win = (wx, wy, ww, wh)
        # CamShift 상자는 머리+목까지 늘어나기 쉬워 정사각형 얼굴 상자로 줄여 쓴다
        cx, cy = rot[0]
        return (int(cx - lw / 2), int(cy - lw / 2), int(lw), int(lw))

    # ── 흔들림 ──
    def _sway(self, t):
        c = self.cfg
        while self.x_hist and self.x_hist[0][0] < t - c.sway_win_s:
            self.x_hist.popleft()
        if len(self.x_hist) < 0.7 * c.sway_win_s * c.proc_fps:
            return {"active": False, "freq": None, "amp_fw": None, "ratio": None}
        ts = np.array([p[0] for p in self.x_hist])
        xs = np.array([p[1] for p in self.x_hist])
        fw = float(np.median([p[2] for p in self.x_hist]))
        if ts[-1] - ts[0] < 0.7 * c.sway_win_s:
            return {"active": False, "freq": None, "amp_fw": None, "ratio": None}
        fs = c.proc_fps
        tu = np.arange(ts[0], ts[-1], 1 / fs)
        xu = np.interp(tu, ts, xs) / max(fw, 1)
        xu = xu - np.polyval(np.polyfit(tu - tu[0], xu, 2), tu - tu[0])   # 느린 이동(2차) 빼기
        n = len(xu)
        nf = 1 << max(8, int(math.ceil(math.log2(n * 4))))
        spec = np.abs(np.fft.rfft(xu * np.hanning(n), nf)) ** 2
        fr = np.fft.rfftfreq(nf, 1 / fs)
        tot = spec[(fr >= 0.05) & (fr <= fs / 2)].sum() + 1e-12
        band = (fr >= c.sway_band[0]) & (fr <= c.sway_band[1])
        ratio = float(spec[band].sum() / tot)
        f0 = float(fr[band][np.argmax(spec[band])])
        # 대역 성분만 남겨 진폭(사인 진폭 ≈ √2·표준편차)
        X = np.fft.rfft(xu, nf)
        fr2 = np.fft.rfftfreq(nf, 1 / fs)
        X[~((fr2 >= c.sway_band[0]) & (fr2 <= c.sway_band[1]))] = 0
        bp = np.fft.irfft(X, nf)[:n]
        amp = float(math.sqrt(2) * bp.std())
        return {"active": bool(amp >= c.sway_amp and ratio >= c.sway_ratio), "freq": round(f0, 3), "amp_fw": round(amp, 3),
                "ratio": round(ratio, 3)}

    # ── 한 프레임 ──
    def process(self, bgr: np.ndarray, t: float, frame: int) -> dict:
        c = self.cfg
        t_start = time.perf_counter()
        H0, W0 = bgr.shape[:2]
        sc = c.proc_w / W0
        small = cv2.resize(bgr, (c.proc_w, int(round(H0 * sc))), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        bright = float(gray.mean())
        sharp = float(cv2.Laplacian(gray, cv2.CV_32F).var())
        eq = cv2.equalizeHist(gray) if c.eq == "hist" else (self.clahe.apply(gray) if c.eq == "clahe" else gray)
        H, W = gray.shape
        dets = self._detect(eq)
        groups = self._cluster(dets)
        g = self._pick(groups, t, W)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV) if c.use_track else None
        src, box, scores, eyes, dy = "none", None, {}, None, None
        raw = None
        if g is not None:
            box = g["box"]
            scores = g["scores"]
            f_ = scores.get("frontal", -9)
            pl, pr = scores.get("profile_l", -9), scores.get("profile_r", -9)
            if c.frontal_only:
                raw, src = ("front", "frontal") if "frontal" in scores else (None, "none")
            elif "frontal" in scores and max(pl, pr) - f_ <= c.profile_margin:
                raw, src = "front", "frontal"
            elif pl >= pr and pl > -9:
                raw, src = "left", "profile_l"
            elif pr > -9:
                raw, src = "right", "profile_r"
            else:
                raw, src = "front", "frontal"
            if raw is not None:
                self.last_box = box
                self.last_seen_t = t
                self.last_any_t = t
                self.fw_hist.append(box[2])
                if raw in ("left", "right"):
                    self.last_side, self.last_side_t = raw, t
                if c.use_track and raw == "front":
                    self._track_init(hsv, box)
        if raw is None and c.use_track and t - self.last_seen_t < c.track_max_s:
            tb = self._track(hsv)
            if tb is not None:
                box, src = tb, "track"
                self.last_any_t = t
                if self.last_side and t - self.last_side_t < c.side_hold_s:
                    raw = self.last_side
                else:
                    raw = "away"
        fwm = float(np.median(self.fw_hist)) if self.fw_hist else None
        if box is not None and fwm:
            cy = box[1] + box[3] / 2
            if self.base_cy is not None:
                dy = (cy - self.base_cy) / fwm
            if raw == "front" and (dy is None or dy < c.down_dy * 0.5):
                self.base_cy = cy if self.base_cy is None else 0.95 * self.base_cy + 0.05 * cy
            if c.use_down_dy and dy is not None and dy > c.down_dy and raw in ("front", "away"):
                raw = "down"
        # 눈 단서 — 원본 해상도 얼굴 자르기를 120px 로 키워 눈 캐스케이드
        if c.use_eyes and raw == "front" and box is not None:
            x, y, w, h = [int(v / sc) for v in box]
            if w >= 60:
                roi = cv2.cvtColor(bgr[max(0, y):y + int(h * 0.6), max(0, x):x + w], cv2.COLOR_BGR2GRAY)
                if roi.size:
                    up = cv2.equalizeHist(cv2.resize(roi, (120, max(1, int(120 * roi.shape[0] / roi.shape[1])))))
                    eyes = int(len(self.ce.detectMultiScale(up, 1.1, 3, minSize=(14, 14))))
                    if eyes == 0 and dy is not None and dy > c.down_dy * 0.5:
                        raw = "down"
        if raw is None:
            raw = "none" if t - self.last_any_t >= c.absent_after_s else (self.raw_hist[-1] if self.raw_hist else "none")
        self.raw_hist.append(raw)
        vals = list(self.raw_hist)
        orient = max(set(vals), key=lambda v: (vals.count(v), max(i for i, x in enumerate(vals) if x == v)))
        present = orient != "none"
        # 흔들림 — 얼굴 가운데 x 시계열 (검출 + 추적)
        if box is not None and fwm:
            self.x_hist.append((t, box[0] + box[2] / 2, fwm))
        sway = self._sway(t)
        # 움직임 · 손짓 — 저해상도 Farneback
        fsm = cv2.resize(gray, (c.flow_w, int(round(H * c.flow_w / W))), interpolation=cv2.INTER_AREA)
        motion, mlevel, gscore, gest = None, None, 0.0, False
        if self.prev_small is not None and self.prev_small.shape == fsm.shape:
            flow = cv2.calcOpticalFlowFarneback(self.prev_small, fsm, None, 0.5, 2, 9, 2, 5, 1.1, 0)
            mag = np.linalg.norm(flow, axis=2)
            k = c.flow_w / W
            dtp = max(1e-3, t - self.prev_t)
            ref = self.last_box if self.last_box is not None else None
            if ref is not None and present:
                x, y, w, h = [v * k for v in ref]
                fwk = max(4.0, w)
                hh, ww = mag.shape
                y0 = int(min(hh - 1, y + h + 0.3 * fwk))
                x0, x1 = int(max(0, x + w / 2 - 2.2 * fwk)), int(min(ww, x + w / 2 + 2.2 * fwk))
                body = mag[y0:, x0:x1]
                motion = float(body.mean() / dtp / fwk) if body.size else 0.0
                mlevel = "still" if motion < c.motion_still else ("much" if motion > c.motion_much else "normal")
                # 손짓: 움직이는 피부(YCrCb), 얼굴 · 목 자리는 뺀다
                sm2 = cv2.resize(small, (ww, hh), interpolation=cv2.INTER_AREA)
                ycc = cv2.cvtColor(sm2, cv2.COLOR_BGR2YCrCb)
                skin = cv2.inRange(ycc, (0, 135, 85), (255, 180, 135)) > 0
                if c.gest_rel:
                    # 몸통(얼굴 아래 가운데)의 중앙 흐름을 빼고 「몸과 따로」 움직인 점만 — 흔들림 · 걷기로 손짓이 켜지지 않게
                    ty0 = int(min(hh - 1, y + h + 0.9 * fwk))
                    tx0, tx1 = int(max(0, x + w / 2 - 0.9 * fwk)), int(min(ww, x + w / 2 + 0.9 * fwk))
                    tor = flow[ty0:, tx0:tx1].reshape(-1, 2)
                    bm = np.median(tor, axis=0) if len(tor) else np.zeros(2)
                    mv = np.linalg.norm(flow - bm, axis=2) > c.gest_flow
                else:
                    mv = mag > c.gest_flow
                if c.gest_bgskin:
                    if self.skin_ema is None or self.skin_ema.shape != skin.shape:
                        self.skin_ema = skin.astype(np.float32)
                    self.skin_ema = 0.95 * self.skin_ema + 0.05 * skin
                    skin = skin & (self.skin_ema < 0.6)
                m = skin & mv
                fx0, fx1 = int(max(0, x - c.gest_face_pad * w)), int(min(ww, x + (1 + c.gest_face_pad) * w))
                m[: int(min(hh, y + h + c.gest_neck * fwk)), fx0:fx1] = False
                m[: int(max(0, y)), :] = False
                if c.gest_open:
                    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
                if c.gest_bgskin and m.any():
                    n_, lab_, st_, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
                    keep = [k for k in range(1, n_) if 0.04 * fwk * fwk <= st_[k, cv2.CC_STAT_AREA] <= 1.2 * fwk * fwk]
                    m = np.isin(lab_, keep)
                gscore = float(m.sum() / (fwk * fwk))
            self.gest_hist.append(gscore > c.gest_thr)
            gest = sum(self.gest_hist) >= 2
        self.prev_small, self.prev_t = fsm, t
        ms = (time.perf_counter() - t_start) * 1000
        return {
            "t": round(t, 3), "frame": frame, "present": present, "orient": orient, "orient_raw": raw, "src": src,
            "face": [round(box[0] / W, 4), round(box[1] / H, 4), round(box[2] / W, 4), round(box[3] / H, 4)] if box is not None else None,
            "scores": {k: round(v, 2) for k, v in scores.items()}, "eyes": eyes, "dy_fw": round(dy, 3) if dy is not None else None,
            "sway": sway, "motion": round(motion, 3) if motion is not None else None, "motion_level": mlevel,
            "gesture": bool(gest), "gesture_score": round(gscore, 4),
            "quality": {"bright": round(bright, 1), "sharp": round(sharp, 1), "face_w": round(box[2] / W, 4) if box is not None else None},
            "ms": round(ms, 2),
        }


def run_clip(path: Path, cfg: Cfg) -> dict:
    r = Y4MReader(path)
    eng = RefEngine(cfg)
    step = max(1, int(round(r.fps / cfg.proc_fps)))
    rows = []
    for i in range(0, r.n, step):
        rows.append(eng.process(r.read(i), i / r.fps, i))
    return {"engine": "py-ref", "cfg": asdict(cfg), "clip": path.stem, "fps": r.fps, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", type=Path)
    ap.add_argument("--variant", default="full", choices=list(VARIANTS))
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    log = run_clip(a.clip, VARIANTS[a.variant])
    log["variant"] = a.variant
    out = a.out or a.clip.with_suffix(f".{a.variant}.pred.json")
    out.write_text(json.dumps(log, ensure_ascii=False))
    from collections import Counter
    print(out, Counter(r["orient"] for r in log["rows"]), f"{np.mean([r['ms'] for r in log['rows']]):.1f}ms")


if __name__ == "__main__":
    main()
