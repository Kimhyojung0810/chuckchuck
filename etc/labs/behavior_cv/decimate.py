"""영상 솎기 — 같은 영상을 낮은 입력 fps 로 (예: d8_hd30 1280x720@30 → d8_hd15 @15). 정답은 원래 것을 그대로 쓴다.

    PY=/home/yehschuck/project/chuckchuck/.venv/bin/python
    PYTHONPATH=/data/models/_runs/behavior-cv/pylib $PY etc/labs/behavior_cv/decimate.py d8_hd30 2 d8_hd15

「같은 장면을 15 vs 30fps 카메라로 보면 장별 값이 5%p 안에서 같아야 한다」(바퀴 3) 를 브라우저 가짜 카메라 그대로 재려고.
정답은 원래 영상 것을 그대로 쓴다 — 바코드가 원래 장 번호라서 같은 시계로 채점된다.
"""
from __future__ import annotations

import json
import sys

from common import CLIPS


def main() -> None:
    src, k, dst = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    a = CLIPS / f"{src}.y4m"
    b = CLIPS / f"{dst}.y4m"
    with open(a, "rb") as f:
        head = f.readline().decode()
        tok = head.split()
        w = int(next(x[1:] for x in tok if x.startswith("W")))
        h = int(next(x[1:] for x in tok if x.startswith("H")))
        num, den = next(x[1:] for x in tok if x.startswith("F")).split(":")
        fps = float(num) / float(den)
        out_fps = fps / k
        new_head = " ".join(f"F{int(round(out_fps))}:1" if x.startswith("F") else x for x in tok) + "\n"
        fsize = w * h * 3 // 2
        n = 0
        with open(b, "wb") as g:
            g.write(new_head.encode())
            i = 0
            while True:
                marker = f.readline()
                if not marker:
                    break
                buf = f.read(fsize)
                if len(buf) < fsize:
                    break
                if i % k == 0:
                    g.write(marker)
                    g.write(buf)
                    n += 1
                i += 1
    # 정답은 원래 fps 번호 그대로 둔다 — 영상 오른쪽 위 바코드가 원래 장 번호라, 채점 · 장 표시가 원래 정답과 같은 시계로 맞는다
    gt = json.loads((CLIPS / f"{src}.gt.json").read_text())
    gt.update({"name": dst, "note": f"{src} 를 {k}장마다 하나로 솎은 영상({out_fps}fps) — 정답 · 바코드는 원래 {fps}fps 번호 (decimate.py)"})
    (CLIPS / f"{dst}.gt.json").write_text(json.dumps(gt, ensure_ascii=False))
    print(f"{b} · {n}장 · {out_fps}fps")


if __name__ == "__main__":
    main()
