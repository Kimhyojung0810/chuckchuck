"""장면 대본 — 영상 하나 = 함수 하나. 사람(Actor)의 고개 · 위치 · 흔들림 · 손 · 장 넘김을 시간표로 적는다.

규약
- yaw(도) +: 코가 **영상 오른쪽**(보는 사람 기준). 라벨 right = yaw ≥ 35, left = yaw ≤ -35, 사이(20~35)는 채점 제외.
- pitch(도) -: 숙임. down = pitch ≤ -25, -25~-12 는 채점 제외.
- cx: 목 축의 가로 위치(화면 폭 배수). 0 미만 · 1 초과면 화면 밖(자리 비움).
- fw: 얼굴 폭(화면 폭 배수) — 정면 Haar 상자 폭과 맞춰 둔 값.
- 흔들림 진폭 a: 얼굴 폭 배수(사인 진폭). 손 모드: rest(화면 아래로 내림) · hold(가슴 앞에 가만히) · gesture(움직임).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from timeline import blinks, jitter, mask, steps
from timeline import sway as sway_disp

# 피부 톤 — 밝은 스캔 텍스처에 곱하는 BGR 배수. 고정 YCrCb 피부 문턱이 톤에 따라 얼마나 갈리는지 재려고 (근거조사 §3)
TONES = {"light": None, "medium": (0.73, 0.79, 0.88), "deep": (0.42, 0.48, 0.60)}
SHIRTS = [(70, 60, 50), (40, 70, 150), (120, 120, 120), (30, 30, 30), (150, 110, 60), (60, 120, 70)]  # BGR


@dataclass
class Actor:
    t: np.ndarray
    fw: float = 0.13
    cx: float = 0.5
    cy_face: float = 0.36           # 정면일 때 얼굴 가운데 세로 위치(화면 높이 배수)
    seed: int = 0
    shirt: tuple = (70, 60, 50)
    tint: tuple | None = None       # 둘째 사람 얼굴 색 바꾸기 (B,G,R 곱)
    jitter_deg: float = 2.0
    glasses: bool = False
    _roll: list = field(default_factory=lambda: [(0.0, 0.0)])
    _yaw: list = field(default_factory=lambda: [(0.0, 0.0)])
    _pitch: list = field(default_factory=lambda: [(0.0, 0.0)])
    _cx: list = field(default_factory=list)
    _ramp: dict = field(default_factory=dict)
    sways: list = field(default_factory=list)
    drift_sways: list = field(default_factory=list)   # 대역 밖(느린) 흔들림 — 정답 sway 아님
    hand_segs: list = field(default_factory=list)
    walks: list = field(default_factory=list)

    def look(self, t0: float, yaw: float, pitch: float = 0.0, ramp: float = 0.35, dur: float | None = None):
        """t0 부터 이 자세. dur 를 주면 dur 뒤 정면으로 돌아온다"""
        self._yaw.append((t0, yaw))
        self._pitch.append((t0, pitch))
        if dur is not None:
            self._yaw.append((t0 + dur, 0.0))
            self._pitch.append((t0 + dur, 0.0))
        return self

    def tilt(self, t0: float, roll: float, dur: float | None = None):
        """화면 안 기울기(roll, 도) — Haar 정면은 ±15° 언저리까지 (근거조사 §3)"""
        self._roll.append((t0, roll))
        if dur is not None:
            self._roll.append((t0 + dur, 0.0))
        return self

    def move(self, t0: float, cx: float, dur: float = 1.2):
        self.walks.append((t0, cx, dur))
        return self

    def sway(self, t0: float, t1: float, f: float, a: float):
        self.sways.append((t0, t1, f, a))
        return self

    def slow(self, t0: float, t1: float, f: float, a: float):
        self.drift_sways.append((t0, t1, f, a))
        return self

    def hands(self, t0: float, t1: float, mode: str):
        self.hand_segs.append((t0, t1, mode))
        return self

    def build(self) -> dict:
        t = self.t
        yaw = steps(t, self._yaw, 0.35) + jitter(t, self.jitter_deg, 0.5, self.seed + 1)
        pitch = steps(t, self._pitch, 0.35) + jitter(t, self.jitter_deg * 0.6, 0.5, self.seed + 2)
        roll = steps(t, self._roll, 0.35) + jitter(t, 1.5, 0.3, self.seed + 3)
        # 걷기: 위치는 dur 동안 부드럽게
        cx = np.full_like(t, self.cx, dtype=float)
        cur = self.cx
        for t0, c, dur in sorted(self.walks):
            r = np.clip((t - t0) / dur, 0, 1)
            r = 0.5 - 0.5 * np.cos(np.pi * r)
            cx = np.where(t >= t0, cur + (c - cur) * r, cx)
            cur = c
        sw = sway_disp(t, self.sways)                     # 얼굴 폭 배수
        sl = sway_disp(t, self.drift_sways, fade=2.0)
        xj = jitter(t, 0.03, 0.6, self.seed + 4)
        roll = roll + 6.0 * sw                            # 몸이 흔들리면 고개도 조금 기운다
        modes = np.array(["rest"] * len(t), dtype=object)
        for t0, t1, m in self.hand_segs:
            modes[mask(t, [(t0, t1)])] = m
        return {"yaw": yaw, "pitch": pitch, "roll": roll, "cx": cx, "sway_fw": sw, "slow_fw": sl, "xj_fw": xj,
                "blink": blinks(t, self.seed), "hand_mode": modes, "fw": self.fw, "cy_face": self.cy_face,
                "shirt": self.shirt, "tint": self.tint, "glasses": self.glasses, "seed": self.seed, "sway_segs": list(self.sways),
                "drift_segs": list(self.drift_sways)}


@dataclass
class Scene:
    name: str
    desc: str
    dur: float
    fps: int = 15
    size: tuple = (640, 360)
    seed: int = 0
    slides: list = field(default_factory=lambda: [0.0])
    actors: list = field(default_factory=list)
    room: dict = field(default_factory=dict)
    degrade: dict = field(default_factory=dict)
    poster: dict | None = None
    tags: list = field(default_factory=list)

    @property
    def t(self) -> np.ndarray:
        return np.arange(int(round(self.dur * self.fps))) / self.fps


def _scene(name, desc, dur, **kw) -> tuple[Scene, np.ndarray]:
    s = Scene(name, desc, dur, **kw)
    return s, s.t


# ── 장면들 ─────────────────────────────────────────────────────────────

def s01_front_steady():
    s, t = _scene("s01_front_steady", "정면 고정 · 잔떨림 · 깜박임 · 손 내림 — 기본 정면율 · 오탐 기준", 30, seed=1,
                  slides=[0, 10, 20], tags=["orient", "base"])
    s.actors = [Actor(t, seed=11).build()]
    return s


def s02_turns():
    s, t = _scene("s02_turns", "좌우 고개 돌림 반복 — 45 · 60 · 75 · 90° (90° 는 Haar 가 못 잡는 완전 옆모습)", 48, seed=2,
                  slides=[0, 12, 24, 36], tags=["orient"])
    a = Actor(t, seed=12)
    mags = [45, 60, 75, 90, 45, 60, 75, 90]
    for k, m in enumerate(mags):
        t0 = 3 + k * 5.6
        a.look(t0, (-m if k % 2 == 0 else m), 0, dur=1.6 + 0.2 * (k % 3))
    s.actors = [a.build()]
    return s


def s03_lookaway():
    s, t = _scene("s03_lookaway", "긴 시선 이탈(>3초) 4~6초 vs 짧은 이탈 2~2.5초", 52, seed=3, slides=[0, 12, 25, 37], tags=["lookaway", "orient"])
    a = Actor(t, seed=13)
    a.look(5, -55, dur=5.0).look(15, 60, dur=4.2).look(24, 0, -40, dur=6.0).look(34, -50, dur=2.0) \
     .look(40, 55, dur=2.5).look(45.5, -45, dur=4.0)
    s.actors = [a.build()]
    return s


def s04_down_reading():
    s, t = _scene("s04_down_reading", "원고 보기 — 아래 보기 1~5초 묶음 + 살짝 끄덕임(-15°, 채점 제외)", 46, seed=4, slides=[0, 15, 30], tags=["down"])
    a = Actor(t, seed=14)
    for t0, d, p in [(4, 1.5, -35), (9, 3.0, -45), (16, 2.0, -30), (22, 5.0, -40), (31, 1.0, -38), (36, 4.0, -50)]:
        a.look(t0, 0, p, dur=d)
    a.look(28, 0, -15, dur=1.5).look(43, 0, -15, dur=1.2)
    s.actors = [a.build()]
    return s


def s05_sway_freq():
    s, t = _scene("s05_sway_freq", "몸 흔들림 주파수 — 0.5Hz(진폭 .3) · 1.0Hz(.2) · 1.4Hz(.15) · 사이 정지", 50, seed=5,
                  slides=[0, 20, 40], tags=["sway"])
    a = Actor(t, seed=15).sway(4, 19, 0.5, 0.30).sway(25, 39, 1.0, 0.20).sway(42, 49.5, 1.4, 0.15)
    s.actors = [a.build()]
    return s


def s06_sway_amp():
    s, t = _scene("s06_sway_amp", "몸 흔들림 진폭 — 0.7Hz 에서 .06 · .15 · .40 얼굴 폭", 45, seed=6, slides=[0, 15, 30], tags=["sway"])
    a = Actor(t, seed=16).sway(3, 13, 0.7, 0.06).sway(16, 26, 0.7, 0.15).sway(30, 41, 0.7, 0.40)
    s.actors = [a.build()]
    return s


def s07_drift():
    s, t = _scene("s07_drift", "느린 이동 · 0.12Hz 느린 흔들림 · 한 걸음 옮김 — 흔들림으로 세면 안 됨", 45, seed=7, slides=[0, 15, 30], tags=["sway", "drift"])
    a = Actor(t, seed=17, cx=0.4).move(2, 0.62, 13).move(17, 0.40, 12).slow(24, 40, 0.12, 0.6).move(36, 0.55, 0.9)
    s.actors = [a.build()]
    return s


def s08_gesture():
    s, t = _scene("s08_gesture", "손짓 묶음 vs 가슴 앞 가만한 손 vs 손 내림", 50, seed=8, slides=[0, 12, 25, 38], tags=["gesture"])
    a = Actor(t, seed=18).hands(5, 12, "gesture").hands(12, 18, "hold").hands(18, 22, "gesture") \
        .hands(28, 38, "gesture").hands(38, 44, "hold").hands(44, 48, "gesture")
    a.look(31, -45, dur=1.5)
    s.actors = [a.build()]
    return s


def s09_leave():
    s, t = _scene("s09_leave", "자리 비움 — 옆으로 걸어 나감 · 빈 방 · 돌아옴 · 화면 가장자리 반쯤 걸침", 46, seed=9, slides=[0, 15, 30], tags=["presence"])
    a = Actor(t, seed=19).move(8, 1.45, 1.6).move(18, 0.5, 1.6).move(27, 0.97, 1.5).move(31, 0.5, 1.0) \
        .move(35, -0.45, 1.6).move(41, 0.5, 1.6)
    a.look(28.5, 40, dur=1.5)
    s.actors = [a.build()]
    return s


def s10_empty():
    s, t = _scene("s10_empty", "빈 방(사람 없음) — 얼굴 오탐 · 자리 있음 오탐", 24, seed=10, slides=[0, 12], tags=["presence"])
    s.actors = []
    return s


def s11_two_people():
    s, t = _scene("s11_two_people", "두 사람 — 가운데 발표자(채점 대상) + 오른쪽 작은 사람(고개 돌림 · 30초에 나감)", 45, seed=11,
                  slides=[0, 15, 30], tags=["multi", "orient"])
    a = Actor(t, seed=21, cx=0.42).look(10, -55, dur=2.0).look(18, 55, dur=2.0).look(24, 0, -40, dur=3.0).look(36, -60, dur=4.0)
    b = Actor(t, seed=22, cx=0.82, fw=0.085, cy_face=0.42, shirt=SHIRTS[1], tint=(0.85, 0.95, 1.08)) \
        .look(5, 50, dur=3).look(14, -40, dur=2).move(30, 1.4, 2.0)
    s.actors = [a.build(), b.build()]
    return s


def s12_poster():
    s, t = _scene("s12_poster", "벽에 얼굴 포스터(모나리자, 정면 실사) — 발표자가 옆을 볼 때 포스터를 잡으면 안 됨", 40, seed=12,
                  slides=[0, 13, 26], tags=["distractor", "orient"])
    a = Actor(t, seed=23, cx=0.6).look(6, -55, dur=4.0).look(15, 55, dur=2.0).look(22, -80, dur=4.5).look(32, 0, -42, dur=3.0)
    s.actors = [a.build()]
    s.poster = {"x": 0.08, "y": 0.10, "h": 0.42}
    return s


def s13_yaw_sweep():
    s, t = _scene("s13_yaw_sweep", "각도 곡선 — yaw ±20/35/50/70 각 2.5초 · roll ±8/15 · pitch -15/-25/-35 (정면 사이 1.5초)", 60, seed=13,
                  slides=[0, 20, 40], tags=["orient", "curve"])
    a = Actor(t, seed=24, jitter_deg=0.8)
    k = 2.0
    for y in (-20, 20, -35, 35, -50, 50, -70, 70):
        a.look(k, y, dur=2.5)
        k += 4.0
    for r in (-8, 8, -15, 15):
        a.tilt(k, r, dur=2.5)
        k += 4.0
    for p in (-15, -25, -35):
        a.look(k, 0, p, dur=2.5)
        k += 4.0
    s.actors = [a.build()]
    return s


def mixed(name: str, desc: str, *, fw: float = 0.13, seed: int = 30, tone: str = "light", glasses: bool = False, **kw) -> Scene:
    """품질 변형용 공통 대본 — 돌림 · 숙임 · 흔들림 · 손짓 · 긴 이탈이 다 들어 있다"""
    s, t = _scene(name, desc, 40, seed=seed, slides=[0, 10, 20, 30], **kw)
    a = Actor(t, seed=seed + 1, fw=fw, tint=TONES[tone], glasses=glasses)
    a.look(4, -55, dur=1.8).look(8, 55, dur=1.5).look(11.5, 0, -40, dur=2.5).look(25, -60, dur=4.5).look(31, 0, -42, dur=4.0)
    a.sway(16, 24, 0.6, 0.30).hands(18, 23, "gesture").hands(36, 39.5, "gesture")
    s.actors = [a.build()]
    return s


def d_variants() -> list:
    out = [
        mixed("d0_clean", "공통 대본 · 깨끗함(비교 기준)", tags=["degrade"]),
        mixed("d1_dim45", "어두운 방 — 평균 밝기 약 45 + 센서 잡음", degrade={"gain": 0.32, "noise": 5}, tags=["degrade"]),
        mixed("d2_dim30", "아주 어두운 방 — 평균 밝기 약 30 + 잡음", degrade={"gain": 0.21, "noise": 6}, tags=["degrade"]),
        mixed("d3_blur", "초점 흐림 — 가우시안 σ≈2.5px(640폭)", degrade={"blur": 2.5}, tags=["degrade"]),
        mixed("d4_noise", "센서 잡음 σ=14", degrade={"noise": 14}, tags=["degrade"]),
        mixed("d5_backlit", "역광 — 뒤 창이 밝고 사람은 어두움", degrade={"backlit": True}, room={"window": "center"}, tags=["degrade"]),
        mixed("d6_jpeg", "강한 압축 — JPEG q=12 블록", degrade={"jpeg": 12}, tags=["degrade"]),
        mixed("d7_small", "멀리 앉음 — 얼굴 폭 화면의 6%", fw=0.06, tags=["degrade"]),
        mixed("d8_hd30", "1280x720 · 30fps 깨끗함(처리 시간 비교)", fps=30, size=(1280, 720), tags=["degrade", "perf"]),
        mixed("d9_glasses", "안경(테 있는) — 눈 캐스케이드 · 정면 검출", glasses=True, tags=["degrade", "glasses"]),
        mixed("t1_tone_medium", "피부 톤 중간 — 얼굴 · 손 같이", tone="medium", tags=["tone"]),
        mixed("t2_tone_deep", "피부 톤 짙음 — 얼굴 · 손 같이 (고정 YCrCb 피부 문턱 공정성)", tone="deep", tags=["tone"]),
        mixed("t3_tone_deep_dim", "피부 톤 짙음 + 어두운 방(밝기 약 45)", tone="deep", degrade={"gain": 0.32, "noise": 5}, tags=["tone", "degrade"]),
    ]
    return out


def all_scenes() -> list[Scene]:
    return [s01_front_steady(), s02_turns(), s03_lookaway(), s04_down_reading(), s05_sway_freq(), s06_sway_amp(),
            s07_drift(), s08_gesture(), s09_leave(), s10_empty(), s11_two_people(), s12_poster(), s13_yaw_sweep(), *d_variants()]
