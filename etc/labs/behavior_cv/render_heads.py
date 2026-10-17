"""3D 머리 스캔 → 자세별 투명 PNG 묶음(아틀라스).

같은 사람의 정면 · 옆 · 3/4 · 숙임을 **각도 정답과 함께** 얻으려고, 자유 라이선스 3D 머리 스캔
(Lee Perry-Smith, Infinite-Realities, CC BY 3.0 — SOURCES.md)을 헤드리스 크롬 WebGL(three.js r160)로 그린다.

    PYTHONPATH=/data/models/_runs/behavior-cv/pylib .venv/bin/python etc/labs/behavior_cv/render_heads.py
    ... render_heads.py --quick          # 몇 장만 (눈으로 확인)

결과: /data/models/_runs/behavior-cv/lab/assets/atlas/y{yaw}_p{pitch}.png + index.json (목 축 위치 · 크기)
자산(모델 · 텍스처 · three.js)은 fetch_assets() 가 처음 한 번 받는다 (git 에 안 올린다).
"""
from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.request
from pathlib import Path

from common import ASSETS, ATLAS, HERE, ensure_chrome_libs, free_port, serve

THREE = "https://cdn.jsdelivr.net/npm/three@0.160.0"
LPS = "https://raw.githubusercontent.com/mrdoob/three.js/r160/examples/models/gltf/LeePerrySmith"
FILES = {
    "three/three.module.js": f"{THREE}/build/three.module.js",
    "three/jsm/loaders/GLTFLoader.js": f"{THREE}/examples/jsm/loaders/GLTFLoader.js",
    "three/jsm/utils/BufferGeometryUtils.js": f"{THREE}/examples/jsm/utils/BufferGeometryUtils.js",
    "lps/LeePerrySmith.glb": f"{LPS}/LeePerrySmith.glb",
    "lps/LeePerrySmith_License.txt": f"{LPS}/LeePerrySmith_License.txt",
    "lps/Map-COL.jpg": f"{LPS}/Map-COL.jpg",
    "lps/Infinite-Level_02_Tangent_SmoothUV.jpg": f"{LPS}/Infinite-Level_02_Tangent_SmoothUV.jpg",
}

YAWS = list(range(-90, 91, 5))
PITCHES = list(range(-50, 26, 5))
EYES = ["open", "half", "closed", "openg", "halfg", "closedg"]   # g = 안경

# 텍스처(1024²)의 눈 자리 — 스캔은 눈을 감고 찍혀서, 뜬 눈을 그려 넣는다 (CC BY 3.0 변경 표시: SOURCES.md)
#   (안쪽 끝 x, 바깥 끝 x, 가운데 y) — 이미지 좌표
EYE_UP, EYE_DN = 24, 4   # 눈매 위 · 아래 높이(텍스처 px)
EYE_SPOTS = [((475, 406), 301), ((553, 620), 301)]
MARKS = [(464, 300), (558, 299)]   # 스캔 표식(빨간 점) — 지운다


def make_textures() -> None:
    """눈 뜸 · 반쯤 · 감음 세 벌. 반쯤/감음은 아래를 볼 때(눈꺼풀이 내려옴)와 깜박임에 쓴다"""
    import cv2
    import numpy as np

    base = cv2.imread(str(ASSETS / "lps/Map-COL.jpg"))
    mask = np.zeros(base.shape[:2], np.uint8)
    for (x, y) in MARKS:
        cv2.circle(mask, (x, y), 7, 255, -1)
    clean = cv2.inpaint(base, mask, 5, cv2.INPAINT_TELEA)
    for name, open_ in (("open", 1.0), ("half", 0.45), ("closed", 0.0)):
        im = clean.copy()
        if open_ > 0:
            for (xa, xb), cy in EYE_SPOTS:
                x0, x1 = min(xa, xb), max(xa, xb)
                w = x1 - x0
                # 눈꺼풀 자리 UV 는 주름선(cy) 위쪽이 화면에서 크게 늘어난다 — 눈매를 주름선 위로 얹고 세로를 눌러 그린다
                up, dn = EYE_UP * open_, EYE_DN * open_
                cx = (x0 + x1) / 2
                xs = np.arange(x0, x1 + 1)
                t = (xs - x0) / w
                top = cy - up * np.sin(np.pi * t) ** 0.8
                bot = cy + dn * np.sin(np.pi * t) ** 1.1
                poly = np.array([[x, y] for x, y in zip(xs, top)] + [[x, y] for x, y in zip(xs[::-1], bot[::-1])], np.int32)
                eye = np.zeros(base.shape[:2], np.uint8)
                cv2.fillPoly(eye, [poly], 255)
                layer = im.copy()
                cv2.fillPoly(layer, [poly], (196, 204, 210))
                icx = int(cx)
                icy = int(cy - up * 0.5)
                cv2.ellipse(layer, (icx, icy), (12, max(3, int(up * 0.42))), 0, 0, 360, (40, 52, 72), -1)
                cv2.ellipse(layer, (icx, icy), (5, max(2, int(up * 0.2))), 0, 0, 360, (12, 12, 14), -1)
                im = np.where(eye[..., None] > 0, layer, im)
                # 위 눈꺼풀 선(속눈썹) · 아래 그림자
                cv2.polylines(im, [np.array(list(zip(xs, top)), np.int32)], False, (30, 34, 44), 3, cv2.LINE_AA)
                cv2.polylines(im, [np.array(list(zip(xs, bot)), np.int32)], False, (90, 100, 120), 1, cv2.LINE_AA)
        cv2.imwrite(str(ASSETS / f"lps/Map-COL-{name}.jpg"), im, [cv2.IMWRITE_JPEG_QUALITY, 94])
        # 안경 — 테(어두운 타원) · 다리 · 코받침. 눈 캐스케이드가 안경에서 얼마나 떨어지는지 보려고 (근거조사 §3)
        g = im.copy()
        cys = []
        for (xa, xb), cy in EYE_SPOTS:
            x0, x1 = min(xa, xb), max(xa, xb)
            ccx, ccy = (x0 + x1) // 2, int(cy - EYE_UP * 0.45)
            cys.append((ccx, ccy, (x1 - x0)))
            cv2.ellipse(g, (ccx, ccy), (int((x1 - x0) * 0.7), 40), 0, 0, 360, (25, 25, 30), 6, cv2.LINE_AA)
        (ax_, ay_, aw), (bx_, by_, bw) = cys
        cv2.line(g, (ax_ + int(aw * 0.7), ay_ - 4), (bx_ - int(bw * 0.7), by_ - 4), (25, 25, 30), 5, cv2.LINE_AA)
        cv2.line(g, (ax_ - int(aw * 0.7), ay_), (ax_ - int(aw * 0.7) - 70, ay_ + 10), (25, 25, 30), 5, cv2.LINE_AA)
        cv2.line(g, (bx_ + int(bw * 0.7), by_), (bx_ + int(bw * 0.7) + 70, by_ + 10), (25, 25, 30), 5, cv2.LINE_AA)
        cv2.imwrite(str(ASSETS / f"lps/Map-COL-{name}g.jpg"), g, [cv2.IMWRITE_JPEG_QUALITY, 94])


def fetch_assets() -> None:
    for rel, url in FILES.items():
        p = ASSETS / rel
        if p.exists() and p.stat().st_size > 0:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "chuckchuck-behavior-lab/0.1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            p.write_bytes(r.read())
        print("  받음", rel)


def save(out: Path, name: str, r: dict) -> dict:
    """알파 상자로 잘라 저장 — 목 축(anchor)은 자른 그림 기준으로 옮겨 적는다"""
    import io

    from PIL import Image

    im = Image.open(io.BytesIO(base64.b64decode(r["png"].split(",", 1)[1]))).convert("RGBA")
    box = im.getchannel("A").getbbox() or (0, 0, 1, 1)
    im.crop(box).save(out / name)
    ax, ay = r["anchor"]
    return {"file": name, "anchor": [round(ax - box[0], 2), round(ay - box[1], 2)], "box": list(box)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="대표 자세 몇 장만")
    ap.add_argument("--out", type=Path, default=ATLAS)
    args = ap.parse_args()
    fetch_assets()
    make_textures()
    ensure_chrome_libs()
    from playwright.sync_api import sync_playwright

    port = free_port()
    httpd = serve({"/three/": ASSETS / "three", "/lps/": ASSETS / "lps", "/": HERE / "web"}, port)
    args.out.mkdir(parents=True, exist_ok=True)
    poses = [(y, p, e) for p in PITCHES for y in YAWS for e in EYES]
    if args.quick:
        poses = [(y, p, "open") for y, p in [(0, 0), (-30, 0), (30, 0), (-60, 0), (60, 0), (-90, 0), (90, 0), (0, -20), (0, -35), (0, -50), (0, 15)]]
    index = {"size": 512, "poses": {}}
    t0 = time.time()
    with sync_playwright() as pw:
        br = pw.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = br.new_page(viewport={"width": 512, "height": 512})
        msgs = []
        page.on("console", lambda m: msgs.append(m.text))
        page.goto(f"http://127.0.0.1:{port}/render.html")
        try:
            page.wait_for_function("window.ready === true", timeout=60000)
        except Exception:
            print("\n".join(msgs[-20:]))
            raise
        index["head"] = page.evaluate("window.headInfo")
        r = page.evaluate("window.renderPose(0, 0, 0, 'body', 'open')")
        index["body"] = save(args.out, "body.png", r)
        for yaw, pitch, eyes in poses:
            part = "both" if args.quick else "head"
            r = page.evaluate(f"window.renderPose({yaw}, {pitch}, 0, '{part}', '{eyes}')")
            index["poses"][f"{yaw},{pitch},{eyes}"] = save(args.out, f"y{yaw:+03d}_p{pitch:+03d}_{eyes}.png", r)
        br.close()
    httpd.shutdown()
    (args.out / "index.json").write_text(json.dumps(index, indent=1))
    print(f"자세 {len(poses)}장 → {args.out}  ({time.time() - t0:.1f}s)")


if __name__ == "__main__":
    main()
