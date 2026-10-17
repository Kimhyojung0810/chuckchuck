"""행동 추적 실험실 공통 — 경로 · 라벨 · 작은 정적 서버 · 크롬 실행 옵션.

이 실험실의 파일은 전부 이 폴더 안에 있고, 만든 자료(영상 · 정답 · 결과)는 루트 디스크가 아니라
/data/models/_runs/behavior-cv/lab/ 아래로 간다 (루트 98%). OpenCV-python 은 venv 에 없어서
/data/models/_runs/behavior-cv/pylib 에 --target 으로 깔았다 — 아래 sys.path 에 붙인다.
"""
from __future__ import annotations

import functools
import http.server
import os
import socketserver
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LAB = Path(os.environ.get("BEHAVIOR_LAB_DIR", "/data/models/_runs/behavior-cv/lab"))
PYLIB = Path(os.environ.get("BEHAVIOR_PYLIB", "/data/models/_runs/behavior-cv/pylib"))
ASSETS = LAB / "assets"
ATLAS = ASSETS / "atlas"
CLIPS = LAB / "clips"
RUNS = LAB / "runs"

if PYLIB.exists() and str(PYLIB) not in sys.path:
    sys.path.insert(0, str(PYLIB))

# 방향 라벨 — 엔진(behavior_cv_logic)의 상태 낱말과 맞춘다. 정답 파일에는 영어 코드로 둔다.
#   front=정면 · left=왼쪽 · right=오른쪽 · down=아래 · none=없음(사람 없음)
# 왼쪽/오른쪽은 **카메라 영상 기준**(보는 사람 기준, 좌우 뒤집지 않은 원본 프레임에서 코가 향한 쪽)이다.
# 발표자 기준(발표자가 자기 왼쪽을 봄)은 영상 기준 right 다 — 채점기 --yaw-convention subject 로 바꿔 잰다.
CLASSES = ["front", "left", "right", "down", "none"]
KO = {"front": "정면", "left": "왼쪽", "right": "오른쪽", "down": "아래", "none": "없음"}
KO2EN = {v: k for k, v in KO.items()}
KO2EN.update({"앞": "front", "왼": "left", "오른": "right", "숙임": "down", "자리비움": "none"})

# 정답 각도 → 라벨 문턱 (도). 사이 각도는 ignore(채점 제외)로 둔다 — 경계에서 엔진을 탓하지 않으려고.
YAW_FRONT = 20.0     # |yaw| < 20 이면 정면 후보
YAW_SIDE = 35.0      # |yaw| >= 35 이면 옆
PITCH_DOWN = -25.0   # pitch <= -25 이면 아래
PITCH_FRONT = -12.0  # pitch > -12 이면 숙이지 않음


def pose_label(yaw: float, pitch: float) -> tuple[str, bool]:
    """(라벨, ignore) — yaw +: 코가 영상 오른쪽, pitch -: 숙임"""
    if pitch <= PITCH_DOWN:
        return "down", abs(yaw) >= YAW_SIDE  # 숙이면서 크게 돌린 건 애매 → 제외
    if pitch > PITCH_FRONT:
        if abs(yaw) < YAW_FRONT:
            return "front", False
        if abs(yaw) >= YAW_SIDE:
            return ("right" if yaw > 0 else "left"), False
        return ("right" if yaw > 0 else "left"), True
    # -25 < pitch <= -12 : 살짝 숙임 — 가장 가까운 라벨이지만 채점 제외
    if abs(yaw) < YAW_FRONT:
        return "front", True
    return ("right" if yaw > 0 else "left"), True


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401 — 조용히
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        # opencv.js 가 SharedArrayBuffer 를 쓰는 빌드도 있어 격리 헤더를 붙여 둔다(없어도 동작)
        super().end_headers()


class _MultiRoot(_Quiet):
    roots: dict[str, Path] = {}

    def translate_path(self, path: str) -> str:
        p = path.split("?", 1)[0].split("#", 1)[0]
        for prefix, root in sorted(self.roots.items(), key=lambda kv: -len(kv[0])):
            if p == prefix.rstrip("/") or p.startswith(prefix):
                if root.is_file():
                    return str(root) if p == prefix else str(Path("/nonexistent") / p.lstrip("/"))
                rel = p[len(prefix):].lstrip("/")
                return str((root / rel).resolve())
        return str(Path("/nonexistent") / p.lstrip("/"))


class _TS(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(roots: dict[str, Path], port: int) -> _TS:
    """prefix → 폴더 여러 개를 한 포트로. 127.0.0.1 에만 붙는다 (실험실 포트 8835~8839)."""
    handler = type("H", (_MultiRoot,), {"roots": {k: Path(v) for k, v in roots.items()}})
    httpd = _TS(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def free_port(lo: int = 8835, hi: int = 8839) -> int:
    import socket

    for p in range(lo, hi + 1):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError(f"{lo}~{hi} 포트가 다 쓰이고 있어요")


def chrome_env() -> dict:
    env = dict(os.environ)
    pw = str(Path.home() / ".local/lib/pwlibs")
    env["LD_LIBRARY_PATH"] = pw + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    return env


def ensure_chrome_libs() -> None:
    """playwright 가 띄우는 크롬은 이 프로세스의 환경을 물려받는다 — libasound 경로를 미리 넣는다"""
    pw = str(Path.home() / ".local/lib/pwlibs")
    cur = os.environ.get("LD_LIBRARY_PATH", "")
    if pw not in cur.split(":"):
        os.environ["LD_LIBRARY_PATH"] = pw + (":" + cur if cur else "")
