"""모바일 체험 투어 #/tour/* 라우트 스모크 (2026-10-11, docs/booth-mobile/).

브라우저 없이 「QR → /tour/… 주소가 투어 화면까지 닿는가」 를 잡는다.
 · 주소창 /tour · /tour/<단계> 가 앱 해시 주소로 302 되는가 (bridge.hash_route_for)
 · 투어 화면 파일(js · css · 녹화 데이터)이 팀 쿠키 없이 공개로 열리는가 (static_access)
 · app.js 가 tour 라우트를 등록하고, 베타 잠금(BETA_ROUTES)에 넣지 않았고, lazy 번들을 받게 했는가
 · index.html #lazyAssets 의 tour 번들 파일이 실제로 있는가
화면 속 판단(시각 → 장 · 자막 · 칩, 인앱 판별)은 etc/tests/js/tour.smoke.mjs 가 본다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import server.bridge as bridge
from server.static_assets import static_access

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "main" / "web"
APP_JS = (WEB / "js" / "app.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")

# js/funnel.js — 퍼널 신호 ccFunnel (ops/booth-qr-1011). 투어 셸이 단계마다 부른다 (10-12 통합)
TOUR_FILES = ["js/funnel.js", "js/tour_logic.js", "js/tour.js", "js/tour_play.js", "css/tour.css"]


@pytest.mark.parametrize("path, expect", [
    ("/tour", "#/tour"),
    ("/tour/deck", "#/tour/deck"),
    ("/tour/present", "#/tour/present"),
    ("/tour/analysis", "#/tour/analysis"),
    ("/tour/qa", "#/tour/qa"),
    ("/tour/report", "#/tour/report"),
    ("/tour/done", "#/tour/done"),
])
def test_주소창_투어_주소는_해시_화면으로_간다(path, expect):
    assert bridge.hash_route_for(path, bridge.STATIC.locate) == expect


@pytest.mark.parametrize("rel", TOUR_FILES + ["data/tour/index.json", "data/tour/delivery-rating.json"])
def test_투어_파일은_공개다(rel):
    assert (WEB / rel).is_file(), f"{rel} 가 없어요"
    assert static_access("/" + rel) == "public", f"/{rel} 가 공개가 아니면 공개 사이트에서 404 다"


def test_app_js_가_투어_라우트를_등록한다():
    assert re.search(r"^\s*'tour':\s*\(\)\s*=>.*renderTour", APP_JS, re.M), "routes 에 'tour' 가 없어요"
    assert re.search(r"tourOnRoute\(key\)", APP_JS), "route() 가 투어 층을 걷지 않아요 — 투어 밖으로 나가도 층이 남는다"


def test_투어는_베타_잠금이_아니다():
    m = re.search(r"const BETA_ROUTES = new Set\(\[([^\]]*)\]\)", APP_JS)
    assert m
    assert "'tour'" not in m.group(1), "투어는 공개 화면이다 — 베타 잠금에 넣으면 QR 방문객이 잠금 화면을 본다"


def test_투어_번들을_받는다():
    m = re.search(r"const LAZY_ROUTE_BUNDLES = \{([^}]*)\}", APP_JS)
    assert m and re.search(r"tour:\s*\['tour'\]", m.group(1)), "LAZY_ROUTE_BUNDLES 에 tour 가 없어요"
    tpl = re.search(r'<template id="lazyAssets">([\s\S]*?)</template>', INDEX).group(1)
    listed = re.findall(r'(?:src|href)="([^"?]+)\?v=[^"]*" data-bundle="tour"', tpl)
    assert sorted(listed) == sorted(TOUR_FILES), f"tour 번들 파일이 달라요: {listed}"
    scripts = [x for x in listed if x.endswith(".js")]
    # 적은 차례대로 실행된다(lazy.js async=false) — 셸은 TourLogic · ccFunnel 을, 화면은 셸의 TourScreens 를 쓴다
    assert scripts == ["js/funnel.js", "js/tour_logic.js", "js/tour.js", "js/tour_play.js"], scripts
