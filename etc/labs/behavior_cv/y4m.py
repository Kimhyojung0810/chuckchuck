"""y4m(4:2:0) 읽기 · 쓰기 — OpenCV 빌드에 따라 y4m 을 못 여는 경우가 있어 직접 읽는다."""
from __future__ import annotations

from pathlib import Path

import numpy as np

import common  # noqa: F401  (pylib 경로)
import cv2  # noqa: E402


class Y4MReader:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.f = open(self.path, "rb")
        head = self.f.readline().decode().split()
        self.w = int(next(x[1:] for x in head if x.startswith("W")))
        self.h = int(next(x[1:] for x in head if x.startswith("H")))
        fr = next(x[1:] for x in head if x.startswith("F")).split(":")
        self.fps = float(fr[0]) / float(fr[1])
        self.hdr = self.f.tell()
        self.fsize = self.w * self.h * 3 // 2
        self.stride = len(b"FRAME\n") + self.fsize
        self.n = (self.path.stat().st_size - self.hdr) // self.stride

    def read(self, i: int) -> np.ndarray:
        self.f.seek(self.hdr + i * self.stride + 6)
        buf = np.frombuffer(self.f.read(self.fsize), np.uint8).reshape(self.h * 3 // 2, self.w)
        return cv2.cvtColor(buf, cv2.COLOR_YUV2BGR_I420)

    def __iter__(self):
        for i in range(self.n):
            yield i, self.read(i)
