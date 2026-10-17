"""스튜디오(/VRShow) 사진 배경 — Poly Haven CC0 360° 사진을 정면 쪽만 잘라 webp 로 만든다.

시점이 고정이라(design/SPACE.md v3) 뒤쪽은 한 번도 안 보인다 — 앞쪽 200° × 위아래 100° 만 남겨
같은 파일 크기에 두 배 선명하게 쓴다. 셰이더(studio-app/src/scene/Environment.jsx)가 같은 범위(ENV_YAW · ENV_PITCH)로 읽는다.

    .venv/bin/python etc/scripts/make_studio_env.py <받은 폴더>

<받은 폴더> 에는 Poly Haven 의 Tonemapped JPG(8192×4096)를 둔다:
    https://dl.polyhaven.org/file/ph-assets/HDRIs/extra/Tonemapped%20JPG/alps_field.jpg
    https://dl.polyhaven.org/file/ph-assets/HDRIs/extra/Tonemapped%20JPG/theater_01.jpg
둘 다 CC0 (https://polyhaven.com/license) — 출처 표시 없이 써도 된다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

OUT = Path(__file__).resolve().parents[2] / "main/web/assets/env"
YAW = 200      # 가로 범위(°) — Environment.jsx ENV_YAW 와 같아야 한다
PITCH = 100    # 세로 범위(°) — ENV_PITCH
#: 이름 → (원본 파일, 정면으로 둘 원본 가로 위치 0~1, 출력 이름)
SOURCES = {
    "alps": ("alps_field.jpg", 0.47),       # 산 능선이 정면
    "theater": ("theater_01.jpg", 0.0),     # 무대에서 객석을 본다 (원본은 무대를 보고 찍었다 — 뒤쪽이 객석)
}
SIZES = {"": 4096, "-sm": 2048}


def crop(src: Image.Image, center_u: float) -> Image.Image:
    w, h = src.size
    cw = round(w * YAW / 360)
    ch = round(h * PITCH / 180)
    x0 = round(center_u * w - cw / 2)
    y0 = round(h / 2 - ch / 2)
    # 가로는 한 바퀴 이어진다 — 두 장을 나란히 붙인 띠에서 자르면 이음매를 넘어도 한 번에 잘린다
    band = Image.new("RGB", (w * 2, ch))
    strip = src.crop((0, y0, w, y0 + ch))
    band.paste(strip, (0, 0))
    band.paste(strip, (w, 0))
    x0 %= w
    return band.crop((x0, 0, x0 + cw, ch))


def main(folder: str) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (file, cu) in SOURCES.items():
        src = Image.open(Path(folder) / file).convert("RGB")
        part = crop(src, cu)
        for suffix, width in SIZES.items():
            img = part.resize((width, width // 2), Image.LANCZOS)
            dest = OUT / f"{name}{suffix}.webp"
            img.save(dest, "WEBP", quality=82, method=6)
            print(f"{dest.relative_to(OUT.parents[2])}  {img.size}  {dest.stat().st_size // 1024}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
