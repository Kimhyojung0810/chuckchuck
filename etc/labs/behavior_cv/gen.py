"""합성 영상 + 프레임 단위 정답 만들기.

    PYTHONPATH=/data/models/_runs/behavior-cv/pylib .venv/bin/python etc/labs/behavior_cv/gen.py            # 전부
    ... gen.py --only s03_lookaway,d1_dim45      # 몇 개만
    ... gen.py --list                             # 장면 목록

먼저 render_heads.py(아틀라스) → validate_atlas.py(calib.json) 를 한 번 돌려 둔다.
결과(/data/models/_runs/behavior-cv/lab/clips/):
  <name>.y4m        — 크롬 --use-file-for-fake-video-capture 에 그대로 물린다 (4:2:0, 헤더의 F 가 fps)
  <name>.gt.json    — 프레임 단위 정답 + 구간 + 장(슬라이드) (형식은 README.md)
  <name>.sheet.jpg  — 눈으로 확인하는 낱장 모음(정답 라벨 찍힘)
영상 오른쪽 위 구석에 **프레임 번호 바코드**(20칸)를 찍는다 — 브라우저 채점에서 엔진이 본 프레임 시각을
영상 시간에 맞추는 데 쓴다 (framesync.js). 끄려면 --no-barcode.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np

from common import ASSETS, ATLAS, CLIPS, PITCH_DOWN, YAW_FRONT, PITCH_FRONT, pose_label

import cv2  # noqa: E402

from scenarios import TONES, Scene, all_scenes  # noqa: E402
from timeline import runs  # noqa: E402

LOOKAWAY_MIN = 3.0
BAR_BITS = 16


# ── 아틀라스 ────────────────────────────────────────────────────────────
class Atlas:
    def __init__(self) -> None:
        self.idx = json.loads((ATLAS / "index.json").read_text())
        self.cal = json.loads((ATLAS / "calib.json").read_text())
        keys = [tuple(k.split(",")) for k in self.idx["poses"]]
        self.yaws = sorted({int(k[0]) for k in keys})
        self.pitches = sorted({int(k[1]) for k in keys})
        self.cache: dict = {}
        self._img: dict = {}
        # 정면 그림의 머리 상자 가운데 ↔ Haar 얼굴 가운데 차이 (얼굴 상자 정답을 머리 상자에서 끌어낸다)
        e = self.idx["poses"]["0,0,open"]
        bx = e["box"]
        hc = np.array([(bx[2] - bx[0]) / 2, (bx[3] - bx[1]) / 2]) - np.array(e["anchor"])
        self.face_from_head = np.array([self.cal["face_dx"], self.cal["face_dy"]]) - hc

    def _load(self, name: str) -> np.ndarray:
        if name not in self._img:
            self._img[name] = cv2.imread(str(ATLAS / name), cv2.IMREAD_UNCHANGED)
        return self._img[name]

    def snap(self, yaw: float, pitch: float) -> tuple[int, int]:
        y = int(np.clip(5 * round(yaw / 5), self.yaws[0], self.yaws[-1]))
        p = int(np.clip(5 * round(pitch / 5), self.pitches[0], self.pitches[-1]))
        return y, p

    def head(self, yaw, pitch, eyes, scale, roll=0.0, tint=None):
        y, p = self.snap(yaw, pitch)
        r = int(round(roll))
        key = ("h", y, p, eyes, round(scale, 3), r, tint)
        if key in self.cache:
            return self.cache[key]
        e = self.idx["poses"][f"{y},{p},{eyes}"]
        im = self._load(e["file"])
        sm = cv2.resize(im, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        ax, ay = e["anchor"][0] * scale, e["anchor"][1] * scale
        if tint is not None:
            sm = sm.astype(np.float32)
            sm[..., :3] *= np.array(tint, np.float32)
            sm = np.clip(sm, 0, 255).astype(np.uint8)
        if r:
            pad = int(max(sm.shape[:2]) * 0.3)
            big = cv2.copyMakeBorder(sm, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(0, 0, 0, 0))
            M = cv2.getRotationMatrix2D((ax + pad, ay + pad), -r, 1.0)
            sm = cv2.warpAffine(big, M, (big.shape[1], big.shape[0]), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
            ax, ay = ax + pad, ay + pad
        # 머리 상자 가운데(자른 그림 기준) — 얼굴 상자 정답에 쓴다
        bw, bh = (e["box"][2] - e["box"][0]) * scale, (e["box"][3] - e["box"][1]) * scale
        hc = (bw / 2 - e["anchor"][0] * scale, bh / 2 - e["anchor"][1] * scale)
        out = (sm, (ax, ay), hc)
        if len(self.cache) > 4000:
            self.cache.clear()
        self.cache[key] = out
        return out

    def body(self, scale, shirt, tint=None):
        key = ("b", round(scale, 3), tuple(shirt), tint)
        if key in self.cache:
            return self.cache[key]
        e = self.idx["body"]
        im = self._load(e["file"]).copy()
        ax, ay = e["anchor"]
        if tint is not None:   # 목 · 가슴 피부도 같은 톤으로
            im[..., :3] = np.clip(im[..., :3].astype(np.float32) * np.array(tint, np.float32), 0, 255).astype(np.uint8)
        im, off = dress(im, ax, ay, shirt)
        sm = cv2.resize(im, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        out = (sm, ((ax + off) * scale, ay * scale))
        self.cache[key] = out
        return out


def dress(im: np.ndarray, ax: float, ay: float, shirt) -> np.ndarray:
    """맨 흉상에 셔츠를 입힌다 — 목 축 아래 둥근 깃선 밑을 셔츠 색으로(밝기 무늬는 남긴다)"""
    a = im[..., 3]
    row = np.where(a[int(min(max(ay + 2, 0), a.shape[0] - 1))] > 0)[0]
    nh = max(10.0, (row.max() - row.min()) / 2) if len(row) else 30.0
    nh = min(nh, 60.0)
    H, W = a.shape
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    u = (xx - ax) / (1.15 * nh)
    collar = np.where(np.abs(u) < 1, ay - 0.1 * nh + 0.45 * nh * (1 - u ** 2), ay - 0.1 * nh)   # 둥근 목 깃
    m = (yy > collar) & (a > 0)
    g = cv2.cvtColor(im[..., :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
    lum = np.clip(g / max(1.0, float(np.median(g[m])) if m.any() else 1.0), 0.45, 1.35)
    out = im.copy()
    for c in range(3):
        ch = out[..., c].astype(np.float32)
        ch[m] = np.clip(shirt[c] * lum[m] ** 0.9, 0, 255)
        out[..., c] = ch.astype(np.uint8)
    edge = m & ~cv2.erode(m.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & (yy < ay + 1.2 * nh)
    out[..., :3][edge] = (out[..., :3][edge] * 0.6).astype(np.uint8)
    # 흉상 아래를 몸통으로 늘린다 (스캔은 가슴에서 잘려 있다) — 아래로 흉상 높이의 3배, 살짝 넓어지는 사다리꼴
    ys = np.where(a.any(axis=1))[0]
    r = int(ys.min() + 0.8 * (ys.max() - ys.min()))
    xs = np.where(a[r] > 0)[0]
    xl, xr = int(xs.min()), int(xs.max())
    ext = 3 * H
    big = np.zeros((H + ext, W + 2 * int(0.1 * W), 4), np.uint8)
    off = int(0.1 * W)
    tor = np.array([[xl + off, r], [xr + off, r], [xr + off + int(0.08 * W), H + ext], [xl + off - int(0.08 * W), H + ext]], np.int32)
    sh = tuple(int(c * 0.85) for c in shirt) + (255,)
    cv2.fillPoly(big, [tor], sh, cv2.LINE_AA)
    # 몸통 가운데가 조금 밝게 (둥근 몸 느낌)
    g2 = np.exp(-(((np.arange(big.shape[1]) - (xl + xr) / 2 - off) / (0.45 * (xr - xl))) ** 2))[None, :, None]
    big[..., :3] = np.clip(big[..., :3].astype(np.float32) * (0.85 + 0.25 * g2), 0, 255).astype(np.uint8)
    sub = big[0:H, off:off + W]
    al = out[..., 3:4].astype(np.float32) / 255
    sub[..., :3] = (out[..., :3] * al + sub[..., :3] * (1 - al)).astype(np.uint8)
    sub[..., 3] = np.maximum(sub[..., 3], out[..., 3])
    # 기준점(목 축)은 off 만큼 오른쪽으로 옮겨졌다 — 부르는 쪽에서 맞춘다
    return big, off


# ── 그리기 ──────────────────────────────────────────────────────────────
def blend(canvas: np.ndarray, pmask: np.ndarray | None, rgba: np.ndarray, x: float, y: float) -> None:
    x, y = int(round(x)), int(round(y))
    h, w = rgba.shape[:2]
    H, W = canvas.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    s = rgba[y0 - y:y1 - y, x0 - x:x1 - x]
    a = s[..., 3:4].astype(np.float32) / 255.0
    canvas[y0:y1, x0:x1] = s[..., :3] * a + canvas[y0:y1, x0:x1] * (1 - a)
    if pmask is not None:
        pmask[y0:y1, x0:x1] = np.maximum(pmask[y0:y1, x0:x1], a[..., 0])


def room(W: int, H: int, seed: int, window: str = "left") -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = np.array(rng.choice([(196, 204, 212), (178, 196, 206), (206, 200, 188), (190, 186, 200)]), np.float32)
    yy = np.linspace(1.05, 0.82, H)[:, None, None]
    img = np.broadcast_to(base * yy, (H, W, 3)).astype(np.float32).copy()
    s = W / 640
    # 바닥 걸레받이
    cv2.rectangle(img, (0, int(H * 0.93)), (W, H), (90, 100, 110), -1)
    # 창
    if window == "center":
        x0, x1 = int(W * 0.25), int(W * 0.75)
        cv2.rectangle(img, (x0, int(H * 0.05)), (x1, int(H * 0.85)), (250, 250, 250), -1)
        cv2.rectangle(img, (x0, int(H * 0.05)), (x1, int(H * 0.85)), (230, 230, 225), int(6 * s))
        cv2.line(img, ((x0 + x1) // 2, int(H * 0.05)), ((x0 + x1) // 2, int(H * 0.85)), (235, 235, 235), int(5 * s))
    else:
        x0 = int(W * (0.03 if window == "left" else 0.72))
        cv2.rectangle(img, (x0, int(H * 0.08)), (x0 + int(W * 0.22), int(H * 0.55)), (245, 232, 214), -1)
        cv2.rectangle(img, (x0, int(H * 0.08)), (x0 + int(W * 0.22), int(H * 0.55)), (120, 110, 100), int(5 * s))
        cv2.line(img, (x0 + int(W * 0.11), int(H * 0.08)), (x0 + int(W * 0.11), int(H * 0.55)), (120, 110, 100), int(4 * s))
    # 책장
    bx = int(W * (0.80 if window != "right" else 0.04))
    cv2.rectangle(img, (bx, int(H * 0.2)), (bx + int(W * 0.17), int(H * 0.93)), (60, 80, 105), -1)
    for shelf in range(4):
        y1 = int(H * (0.2 + 0.18 * (shelf + 1)))
        cv2.line(img, (bx, y1), (bx + int(W * 0.17), y1), (40, 55, 75), int(4 * s))
        xb = bx + int(4 * s)
        while xb < bx + int(W * 0.16):
            bw = int(rng.integers(5, 12) * s)
            bh = int(H * rng.uniform(0.09, 0.15))
            col = tuple(int(c) for c in rng.integers(30, 220, 3))
            cv2.rectangle(img, (xb, y1 - bh), (xb + bw, y1 - 2), col, -1)
            xb += bw + 1
    # 액자
    fx = int(W * rng.uniform(0.3, 0.45))
    if window != "center":
        cv2.rectangle(img, (fx, int(H * 0.08)), (fx + int(W * 0.12), int(H * 0.22)), (50, 50, 50), int(3 * s))
        cv2.rectangle(img, (fx + int(4 * s), int(H * 0.08) + int(4 * s)), (fx + int(W * 0.12) - int(4 * s), int(H * 0.22) - int(4 * s)),
                      tuple(int(c) for c in rng.integers(80, 200, 3)), -1)
    # 화분
    px = int(W * (0.12 if window != "left" else 0.30))
    cv2.rectangle(img, (px, int(H * 0.8)), (px + int(30 * s), int(H * 0.93)), (40, 70, 140), -1)
    for _ in range(9):
        cv2.ellipse(img, (px + int(15 * s + rng.normal(0, 12 * s)), int(H * 0.8 - rng.uniform(5, 50) * s)),
                    (int(14 * s), int(6 * s)), float(rng.uniform(0, 180)), 0, 360, (40, int(rng.integers(100, 150)), 50), -1)
    # 벽 질감 잡음
    tex = cv2.GaussianBlur(rng.normal(0, 6, (H, W)).astype(np.float32), (0, 0), 1.5 * s)
    img += tex[..., None]
    return np.clip(cv2.GaussianBlur(img, (0, 0), 0.7 * s), 0, 255)


def skin_of(atlas: Atlas) -> np.ndarray:
    im = atlas._load(atlas.idx["poses"]["0,0,open"]["file"])
    a = im[..., 3] > 200
    h = im.shape[0]
    sel = a.copy()
    sel[: int(h * 0.45)] = False
    sel[int(h * 0.75):] = False
    return np.median(im[..., :3][sel], axis=0).astype(np.float32)


def draw_arm(canvas, pmask, base, wrist, fw, skin, sleeve, ang_open=0.5, H=None):
    """팔(소매) + 손바닥 + 손가락 다섯 — 2D 로 그린다. 피부색은 머리 텍스처에서 뽑은 값"""
    lay = np.zeros(canvas.shape[:2] + (4,), np.uint8)
    bx, by = base
    wx, wy = wrist
    th = max(3, int(0.42 * fw))
    sl = tuple(int(c) for c in sleeve) + (255,)
    cv2.line(lay, (int(bx), int(by)), (int(wx), int(wy)), sl, th, cv2.LINE_AA)
    d = np.array([wx - bx, wy - by], float)
    n = d / (np.linalg.norm(d) + 1e-6)
    ang = math.degrees(math.atan2(n[1], n[0]))
    sk = tuple(int(c) for c in skin) + (255,)
    dk = tuple(int(c * 0.75) for c in skin) + (255,)
    # 손목 → 손바닥 가운데
    pc = (wx + n[0] * 0.18 * fw, wy + n[1] * 0.18 * fw)
    cv2.ellipse(lay, (int(pc[0]), int(pc[1])), (max(2, int(0.2 * fw)), max(2, int(0.16 * fw))), ang, 0, 360, dk, -1, cv2.LINE_AA)
    cv2.ellipse(lay, (int(pc[0]), int(pc[1])), (max(2, int(0.18 * fw)), max(2, int(0.14 * fw))), ang, 0, 360, sk, -1, cv2.LINE_AA)
    spread = 12 + 28 * ang_open
    for k in range(4):
        a = math.radians(ang + (k - 1.5) * spread / 1.5)
        L = 0.24 * fw * (1.0 if k in (1, 2) else 0.85)
        s0 = (pc[0] + math.cos(a) * 0.12 * fw, pc[1] + math.sin(a) * 0.12 * fw)
        s1 = (s0[0] + math.cos(a) * L, s0[1] + math.sin(a) * L)
        cv2.line(lay, (int(s0[0]), int(s0[1])), (int(s1[0]), int(s1[1])), dk, max(2, int(0.075 * fw)), cv2.LINE_AA)
        cv2.line(lay, (int(s0[0]), int(s0[1])), (int(s1[0]), int(s1[1])), sk, max(1, int(0.055 * fw)), cv2.LINE_AA)
    a = math.radians(ang - 70)
    s0 = (pc[0] + math.cos(a) * 0.1 * fw, pc[1] + math.sin(a) * 0.1 * fw)
    s1 = (s0[0] + math.cos(a + 0.5) * 0.18 * fw, s0[1] + math.sin(a + 0.5) * 0.18 * fw)
    cv2.line(lay, (int(s0[0]), int(s0[1])), (int(s1[0]), int(s1[1])), sk, max(2, int(0.07 * fw)), cv2.LINE_AA)
    blend(canvas, pmask, lay, 0, 0)


class Hands:
    """손 두 개의 손목 궤적 — 용수철로 목표를 따라간다. 목표는 모드마다 다르다"""

    def __init__(self, seed: int):
        self.rng = np.random.default_rng(seed + 99)
        self.pos = None
        self.vel = np.zeros((2, 2))
        self.tgt = None
        self.next_change = 0.0

    def step(self, t: float, dt: float, mode: str, cx: float, fcy: float, fw: float, H: int) -> np.ndarray:
        rest = np.array([[cx - 1.7 * fw, H + 1.2 * fw], [cx + 1.7 * fw, H + 1.2 * fw]])
        hold = np.array([[cx - 0.3 * fw, fcy + 2.0 * fw], [cx + 0.3 * fw, fcy + 2.05 * fw]])
        if self.pos is None:
            self.pos = rest.copy() if mode == "rest" else hold.copy()
            self.tgt = self.pos.copy()
        if mode == "rest":
            self.tgt = rest
        elif mode == "hold":
            self.tgt = hold + self.rng.normal(0, 0.01 * fw, (2, 2))
        else:
            if t >= self.next_change or self.tgt is None or self.tgt[0, 1] > H:
                side = np.array([-1, 1])
                xs = cx + side * self.rng.uniform(0.35, 1.9, 2) * fw
                ys = fcy + self.rng.uniform(1.15, 2.3, 2) * fw
                self.tgt = np.stack([xs, ys], 1)
                self.next_change = t + float(self.rng.uniform(0.3, 0.7))
        k = 70.0
        c = 2 * math.sqrt(k) * 0.9
        acc = k * (self.tgt - self.pos) - c * self.vel
        self.vel = self.vel + acc * dt
        self.pos = self.pos + self.vel * dt
        return self.pos.copy()


def barcode(img: np.ndarray, idx: int) -> None:
    """오른쪽 위 20칸: [1,0] + 16비트(위 비트부터) + 짝수 패리티 + 1 — framesync.js 와 같은 규칙"""
    W = img.shape[1]
    cs = max(4, W // 160)
    bits = [1, 0] + [(idx >> (BAR_BITS - 1 - k)) & 1 for k in range(BAR_BITS)]
    bits += [sum(bits[2:]) % 2, 1]
    x0 = W - cs * len(bits)
    for k, b in enumerate(bits):
        img[0:cs + 2, x0 + k * cs:x0 + (k + 1) * cs] = 255 if b else 0


def bar_box(W: int) -> tuple[int, int, int, int]:
    cs = max(4, W // 160)
    return W - cs * (BAR_BITS + 4), 0, cs * (BAR_BITS + 4), cs + 2


# ── 장면 → 프레임 ─────────────────────────────────────────────────────────
def render_scene(sc: Scene, atlas: Atlas, out_dir: Path, bar: bool = True, sheet: bool = True) -> dict:
    W, H = sc.size
    t = sc.t
    n = len(t)
    dt = 1.0 / sc.fps
    bg = room(W, H, sc.seed, sc.room.get("window", "left"))
    if sc.poster:
        ml = cv2.imread(str(ASSETS / "real/mona-lisa.png"), cv2.IMREAD_GRAYSCALE)
        ph = int(H * sc.poster["h"])
        pw = int(ph * ml.shape[1] / ml.shape[0])
        ml = cv2.resize(ml, (pw, ph), interpolation=cv2.INTER_AREA)
        x0, y0 = int(W * sc.poster["x"]), int(H * sc.poster["y"])
        cv2.rectangle(bg, (x0 - 6, y0 - 6), (x0 + pw + 6, y0 + ph + 6), (35, 35, 35), -1)
        bg[y0:y0 + ph, x0:x0 + pw] = ml[..., None].astype(np.float32) * np.array([0.92, 0.98, 1.05])
    skin = skin_of(atlas)
    deg = sc.degrade
    rng = np.random.default_rng(sc.seed + 5)
    actors = sc.actors
    hands = [Hands(a["seed"]) for a in actors]
    cal = atlas.cal
    gt_frames = []
    per_actor = [dict(face=[], present=[], hands_vis=[], hand_speed=[], head_speed=[]) for _ in actors]
    y4m = out_dir / f"{sc.name}.y4m"
    f = open(y4m, "wb")
    f.write(f"YUV4MPEG2 W{W} H{H} F{sc.fps}:1 Ip A1:1 C420jpeg\n".encode())
    sheet_frames = []
    sheet_at = set(np.linspace(0, n - 1, 12).astype(int).tolist())
    prev_face = [None] * len(actors)
    prev_wr = [None] * len(actors)
    t0 = time.time()
    for i in range(n):
        canvas = bg.copy()
        pmask = np.zeros((H, W), np.float32)
        frame_people = []
        for k, a in enumerate(actors):
            fwpx = a["fw"] * W
            s = fwpx / cal["haar_fw"]
            ax = a["cx"][i] * W + (a["sway_fw"][i] + a["slow_fw"][i] + a["xj_fw"][i]) * fwpx
            ay = a["cy_face"] * H - cal["face_dy"] * s       # 목 축 y (정면 얼굴 가운데가 cy_face 에 오도록)
            yaw, pitch, roll = float(a["yaw"][i]), float(a["pitch"][i]), float(a["roll"][i])
            eyes = "closed" if (a["blink"][i] or pitch <= -30) else ("half" if pitch <= -16 else "open")
            if a.get("glasses"):
                eyes += "g"
            body, (bax, bay) = atlas.body(s, a["shirt"], a["tint"])
            blend(canvas, pmask, body, ax - bax, ay - bay)
            head, (hax, hay), hc = atlas.head(yaw, pitch, eyes, s, roll, a["tint"])
            blend(canvas, pmask, head, ax - hax, ay - hay)
            # 얼굴 상자 정답: 머리 상자 가운데 + (정면 기준 보정) — 폭은 고정 fw
            fcx = ax + hc[0] + atlas.face_from_head[0] * s
            fcy = ay + hc[1] + atlas.face_from_head[1] * s
            face = [fcx - fwpx / 2, fcy - fwpx / 2, fwpx, fwpx]
            # 손 — 정면 얼굴 가운데 기준 위치로 움직인다(숙여도 손 자리는 그대로)
            front_cy = a["cy_face"] * H
            wr = hands[k].step(float(t[i]), dt, a["hand_mode"][i], ax, front_cy, fwpx, H)
            sleeve = tuple(int(c * 0.8) for c in a["shirt"])
            for j, side in enumerate((-1, 1)):
                base = (ax + side * 1.9 * fwpx, H + 2.5 * fwpx)
                draw_arm(canvas, pmask, base, wr[j], fwpx, skin * (np.array(a["tint"]) if a["tint"] else 1), sleeve,
                         ang_open=0.7 if a["hand_mode"][i] == "gesture" else 0.2)
            vis = bool(min(wr[0][1], wr[1][1]) < H - 0.05 * fwpx)
            hs = 0.0 if prev_wr[k] is None else float(np.mean(np.linalg.norm(wr - prev_wr[k], axis=1))) / dt / fwpx
            prev_wr[k] = wr
            hsp = 0.0 if prev_face[k] is None else float(math.hypot(fcx - prev_face[k][0], fcy - prev_face[k][1])) / dt / fwpx
            prev_face[k] = (fcx, fcy)
            present = bool(0.03 * W <= fcx <= 0.97 * W)
            edge = bool(min(fcx, W - fcx) < 0.5 * fwpx + 0.03 * W) and present
            frame_people.append(dict(face=face, present=present, edge=edge, hands_vis=vis, hand_speed=hs if vis else 0.0,
                                     head_speed=hsp, mode=a["hand_mode"][i], yaw=yaw, pitch=pitch, roll=roll))
        img = canvas
        # ── 품질 변형 ──
        if deg.get("backlit"):
            # 창 밝게 + 사람 어둡게 (카메라 자동 노출이 창에 맞춘 상황)
            img = img * (1 - pmask[..., None]) * 1.12 + img * pmask[..., None] * 0.42
        if "gain" in deg:
            img = img * deg["gain"]
        if deg.get("blur"):
            img = cv2.GaussianBlur(img, (0, 0), deg["blur"] * W / 640)
        if deg.get("noise"):
            img = img + rng.normal(0, deg["noise"], img.shape).astype(np.float32)
        img = np.clip(img, 0, 255).astype(np.uint8)
        if deg.get("jpeg"):
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(deg["jpeg"])])
            img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if bar:
            barcode(img, i)
        f.write(b"FRAME\n")
        f.write(cv2.cvtColor(img, cv2.COLOR_BGR2YUV_I420).tobytes())
        # ── 정답 한 줄 ──
        main = frame_people[0] if frame_people else None
        if main and main["present"]:
            lab, ign = pose_label(main["yaw"], main["pitch"])
            ign = ign or main["edge"]
        else:
            lab, ign = "none", False
        row = {"i": i, "t": round(float(t[i]), 4), "present": int(bool(main and main["present"])), "label": lab, "ignore": int(ign),
               "n_people": int(sum(p["present"] for p in frame_people))}
        if main:
            fx, fy, fwd, fh = main["face"]
            row.update({"yaw": round(main["yaw"], 1), "pitch": round(main["pitch"], 1), "roll": round(main["roll"], 1),
                        "face": [round(fx / W, 4), round(fy / H, 4), round(fwd / W, 4), round(fh / H, 4)],
                        "hands_visible": int(main["hands_vis"]), "gesture": int(main["mode"] == "gesture" and main["hands_vis"]),
                        "hand_speed": round(main["hand_speed"], 3), "head_speed": round(main["head_speed"], 3)})
        row["bright"] = round(float(img.mean()), 1)
        gt_frames.append(row)
        if sheet and i in sheet_at:
            sm = cv2.resize(img, (320, int(320 * H / W)))
            txt = f"{i} t={t[i]:.1f} {lab}{'?' if ign else ''} p={row['present']}"
            cv2.putText(sm, txt, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3)
            cv2.putText(sm, txt, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)
            if main and main["present"]:
                fx, fy, fwd, fh = [v * 320 / W for v in main["face"]]
                cv2.rectangle(sm, (int(fx), int(fy)), (int(fx + fwd), int(fy + fh)), (0, 255, 0), 1)
            sheet_frames.append(sm)
    f.close()
    if sheet and sheet_frames:
        rows_ = [np.hstack(sheet_frames[k:k + 4]) for k in range(0, len(sheet_frames), 4) if len(sheet_frames[k:k + 4]) == 4]
        cv2.imwrite(str(out_dir / f"{sc.name}.sheet.jpg"), np.vstack(rows_), [cv2.IMWRITE_JPEG_QUALITY, 82])
    gt = build_gt(sc, gt_frames)
    (out_dir / f"{sc.name}.gt.json").write_text(json.dumps(gt, ensure_ascii=False, separators=(",", ":")))
    print(f"  {sc.name:18s} {n:5d}프레임 {W}x{H}@{sc.fps}  {time.time() - t0:5.1f}s  → {y4m.name} ({y4m.stat().st_size / 1e6:.0f}MB)")
    return gt


def build_gt(sc: Scene, frames: list[dict]) -> dict:
    t = np.array([r["t"] for r in frames])
    dt = 1.0 / sc.fps
    present = np.array([r["present"] for r in frames], bool)
    lab = np.array([r["label"] for r in frames])
    yaw = np.array([r.get("yaw", 0.0) for r in frames])
    pitch = np.array([r.get("pitch", 0.0) for r in frames])
    # 「정면 아님」 = 정면 문턱 밖 (채점 제외 각도 포함). 사람 없음은 이탈이 아니라 자리 비움.
    notfront = present & ~((np.abs(yaw) < YAW_FRONT) & (pitch > PITCH_FRONT))
    slides = sorted(sc.slides)
    sl_edges = slides + [sc.dur]
    slide_of = np.searchsorted(np.array(slides), t, side="right") - 1
    for r, s in zip(frames, slide_of):
        r["slide"] = int(s)
    look = []
    for t0, t1 in runs(notfront, t, LOOKAWAY_MIN, dt):
        m = (t >= t0) & (t < t1)
        vals, cnt = np.unique(lab[m], return_counts=True)
        look.append({"t0": t0, "t1": t1, "dir": str(vals[np.argmax(cnt)])})
    down = [{"t0": a, "t1": b} for a, b in runs(present & (pitch <= PITCH_DOWN), t, 0.0, dt)]
    absent = [{"t0": a, "t1": b} for a, b in runs(~present, t, 0.0, dt)]
    gest = [{"t0": a, "t1": b} for a, b in runs(np.array([r.get("gesture", 0) for r in frames], bool), t, 0.0, dt)]
    main = sc.actors[0] if sc.actors else None
    sway = []
    if main:
        for t0, t1, fr, amp in main["sway_segs"]:
            # 서서히 들어오고 나가는 0.8초를 빼고 「흔들리는 중」으로 친다
            sway.append({"t0": round(t0 + 0.6, 3), "t1": round(t1 - 0.6, 3), "freq": fr, "amp_fw": amp})
    for r in frames:
        r["sway"] = int(any(s["t0"] <= r["t"] < s["t1"] for s in sway))
    per_slide = []
    for k in range(len(slides)):
        a, b = sl_edges[k], sl_edges[k + 1]
        m = (t >= a) & (t < b)
        pm = m & present
        scored = pm & np.array([not r["ignore"] for r in frames])
        per_slide.append({
            "i": k, "t0": a, "t1": b,
            "presence_ratio": round(float(pm.sum() / max(1, m.sum())), 4),
            "front_ratio": round(float((scored & (lab == "front")).sum() / max(1, scored.sum())), 4) if scored.any() else None,
            "down_sec": round(float((pm & (pitch <= PITCH_DOWN)).sum() * dt), 3),
            "lookaway_n": sum(1 for s in look if a <= s["t0"] < b),
            "lookaway_sec": round(sum(max(0.0, min(b, s["t1"]) - max(a, s["t0"])) for s in look), 3),
            "gesture_ratio": round(float(np.mean([frames[j].get("gesture", 0) for j in np.where(pm)[0]])) if pm.any() else 0.0, 4),
            "sway_sec": round(float(np.sum([frames[j]["sway"] for j in np.where(m)[0]]) * dt), 3),
        })
    return {
        "version": 1, "name": sc.name, "desc": sc.desc, "tags": sc.tags, "fps": sc.fps, "w": sc.size[0], "h": sc.size[1],
        "n_frames": len(frames), "duration": sc.dur, "degrade": sc.degrade, "poster": sc.poster,
        "conventions": {
            "yaw": "+ = 코가 영상 오른쪽(보는 사람 기준, 좌우 안 뒤집은 원본 프레임)",
            "label": "front: |yaw|<20 & pitch>-12 · left/right: |yaw|>=35 · down: pitch<=-25 · 사이 각도와 화면 가장자리는 ignore=1",
            "lookaway": "사람 있음 & 정면 아님(ignore 각도 포함)이 3초 넘게 이어진 구간",
            "face": "[x, y, w, h] 화면 비율, 정면 Haar 상자 크기에 맞춘 근사",
            "barcode": f"오른쪽 위 {bar_box(sc.size[0])} 픽셀(x,y,w,h): [1,0]+16비트 프레임 번호+짝수 패리티+1",
        },
        "slides": [{"i": k, "t0": sl_edges[k], "t1": sl_edges[k + 1]} for k in range(len(slides))],
        "segments": {"lookaway": look, "down": down, "absent": absent, "gesture": gest, "sway": sway,
                     "drift": [{"t0": a, "t1": b, "freq": f_, "amp_fw": am} for a, b, f_, am in (main["drift_segs"] if main else [])]},
        "per_slide": per_slide,
        "frames": frames,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="쉼표로 장면 이름(앞부분만 써도 됨)")
    ap.add_argument("--out", type=Path, default=CLIPS)
    ap.add_argument("--no-barcode", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    scenes = all_scenes()
    if args.list:
        for s in scenes:
            print(f"{s.name:18s} {s.dur:4.0f}s {s.size[0]}x{s.size[1]}@{s.fps}  {s.desc}")
        return
    if args.only:
        want = [w.strip() for w in args.only.split(",") if w.strip()]
        scenes = [s for s in scenes if any(s.name.startswith(w) for w in want)]
    args.out.mkdir(parents=True, exist_ok=True)
    atlas = Atlas()
    manifest = []
    for s in scenes:
        gt = render_scene(s, atlas, args.out, bar=not args.no_barcode)
        manifest.append({"name": s.name, "desc": s.desc, "tags": s.tags, "duration": s.dur, "fps": s.fps, "size": list(s.size),
                         "tone": next((k for k, v in TONES.items() if s.actors and v == s.actors[0]["tint"]), None),
                         "glasses": bool(s.actors and s.actors[0].get("glasses"))})
    old = {}
    mp = args.out / "manifest.json"
    if mp.exists():
        old = {m["name"]: m for m in json.loads(mp.read_text())}
    old.update({m["name"]: m for m in manifest})
    mp.write_text(json.dumps(sorted(old.values(), key=lambda m: m["name"]), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
