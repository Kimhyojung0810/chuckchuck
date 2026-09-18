"""가짜 카메라 영상(MJPEG)을 만든다 — 사람 실루엣이 있는 방. 크롬의 --use-file-for-fake-video-capture 가 읽는다.

    python labs/qa_call/fakecam.py            # labs/qa_call/out/fakecam.mjpeg
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent / "out"


def frame(k: int) -> bytes:
    im = Image.new("RGB", (1280, 720))
    d = ImageDraw.Draw(im)
    for y in range(720):
        t = y / 720
        d.line([(0, y), (1280, y)], fill=(int(214 - 40 * t), int(196 - 50 * t), int(178 - 60 * t)))
    d.rectangle([80, 60, 420, 600], fill=(122, 96, 72))
    for i in range(6):
        d.rectangle([100, 90 + i * 85, 400, 140 + i * 85], fill=(160 + i * 8, 120, 90))
    d.rectangle([860, 40, 1240, 420], fill=(200, 222, 240))
    d.rectangle([880, 60, 1220, 400], fill=(225, 238, 250))
    dx = int(6 * ((k % 3) - 1))  # 살짝 흔들려야 영상으로 보인다
    d.ellipse([440 + dx, 520, 840 + dx, 900], fill=(58, 64, 92))
    d.ellipse([540 + dx, 180, 740 + dx, 420], fill=(232, 190, 160))
    d.ellipse([530 + dx, 150, 750 + dx, 300], fill=(60, 40, 30))
    im = im.filter(ImageFilter.GaussianBlur(0.8))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=85)
    return b.getvalue()


def build(path: Path | None = None) -> Path:
    path = path or OUT / "fakecam.mjpeg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(frame(k) for k in range(6)))
    return path


if __name__ == "__main__":
    print(build())
