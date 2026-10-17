"""발표 중 자세 알림(js/behavior_cue.js)용 정답 영상 하나 — 정답 실험실(etc/labs/behavior_cv)의 장면 도구로 만든다.

    PYTHONPATH=/data/models/_runs/behavior-cv/pylib ~/project/chuckchuck/.venv/bin/python etc/labs/live_cue/scene.py

실험실 영상(s03 · s04 · s05)은 이탈 4~6초 · 아래 1~5초 · 흔들림 6~14초로 「리포트」 문턱(3초 · 2초)에 맞춰 지었다 —
실시간 알림 문턱(다른 곳 4초 · 아래 8초 · 흔들림 ≈10초)은 거기서 거의 안 걸린다. 그래서 알림마다 걸릴 것과 안 걸릴 것을 한 영상에:

  0~6   정면                      6~13  왼쪽 -55° 7초  → 「화면 쪽으로 돌아와요」 (≈10.5초)
  13~18 정면                      18~24 오른쪽 55° 6초 → 문턱은 넘지만 20초 간격 안이라 조용 (간격 확인)
  24~26.5 아래 -40° 2.5초(자료 보기 — 조용)   30~41 아래 -45° 11초 → 「고개를 들고 말해 봐요」 (≈38.5초)
  44~60 몸 흔들림 0.6Hz · 얼굴 폭 .3, 16초 → 「두 발에 무게를 나눠 서 봐요」 (≈55~58초)
  64~66 아래 2초(조용)            그 밖 정면.  70초, 장 넘김 0 · 15 · 30 · 45 · 60초
결과: /data/models/_runs/live-cue/clips/c01_live_cue.{y4m,gt.json,sheet.jpg}
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "behavior_cv"))

from common import LAB  # noqa: E402,F401  (pylib 경로를 붙인다)
from gen import Atlas, render_scene  # noqa: E402
from scenarios import Actor, _scene  # noqa: E402

OUT = Path("/data/models/_runs/live-cue/clips")


def c01_live_cue():
    s, t = _scene("c01_live_cue", "실시간 자세 알림 — 7초 이탈 · 간격 안 6초 이탈 · 11초 아래 · 16초 흔들림 · 짧은 아래 둘", 70, seed=41,
                  slides=[0, 15, 30, 45, 60], tags=["live_cue"])
    a = Actor(t, seed=51)
    a.look(6, -55, dur=7.0).look(18, 55, dur=6.0).look(24, 0, -40, dur=2.5).look(30, 0, -45, dur=11.0).look(64, 0, -40, dur=2.0)
    a.sway(44, 60, 0.6, 0.30)
    s.actors = [a.build()]
    return s


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    gt = render_scene(c01_live_cue(), Atlas(), OUT, bar=True)
    seg = gt["segments"]
    print({k: seg[k] for k in ("lookaway", "down", "sway")})
