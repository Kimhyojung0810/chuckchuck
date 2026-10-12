"""
부스 랜딩·투어 화면은 과금 API 를 부르지 않는다 (2026-10-11, docs/booth-mobile/README.md 「API 호출 0」).

투어는 녹화 응답만 재생한다. 화면 코드에 과금 경로(bridge.PAID_PATHS · /qa/judge) 문자열이 들어오면 — 실수로 실제 판정을
부르게 되면 — 부스 방문객 수십 명이 팀 크레딧을 태우고 공개 시간당 천장(1500)을 먼저 써 버린다. 화면 파일이 합쳐지면
이 검사가 바로 그 파일을 집는다(이름 규칙: js/tour*.js · js/intro*.js · intro.html · js/funnel.js).
"""

from __future__ import annotations

import re
from pathlib import Path

import server.bridge as bridge

WEB = Path(bridge.DEMO_DIR)
_API = re.compile(r"""/api/v1/[A-Za-z0-9_./{}${}-]*""")


def booth_files() -> list[Path]:
    pats = ("js/tour*.js", "js/tour*.mjs", "js/intro*.js", "intro.html", "js/funnel.js")
    return sorted({p for pat in pats for p in WEB.glob(pat) if p.is_file()})


def test_검사할_파일이_있다():
    assert WEB / "js" / "funnel.js" in booth_files()


def test_부스_화면은_과금_경로를_부르지_않는다():
    bad = []
    for f in booth_files():
        for m in _API.finditer(f.read_text(encoding="utf-8", errors="replace")):
            path = m.group(0).rstrip("/.")
            if bridge._paid_path(path) or "/qa/judge" in path or path.startswith(("/api/v1/parse", "/api/v1/transcribe")):
                bad.append(f"{f.relative_to(WEB)}: {path}")
    assert bad == [], "부스 랜딩·투어가 과금 API 를 부른다 — 녹화 응답(data/tour/*.json)을 써야 한다:\n" + "\n".join(bad)


def test_퍼널_신호_경로는_과금이_아니다():
    from server import tour_events

    assert not bridge._paid_path(tour_events.PATH)
    assert tour_events.PATH not in bridge.PAID_PATHS
