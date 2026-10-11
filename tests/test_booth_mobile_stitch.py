"""부스 모바일 이어 붙이기 회귀 (2026-10-12, web/booth-mobile-1011 통합).

랜딩(/hi, web/intro-1011) · 녹화 데이터(lab/tour-fixtures-1011) · 투어 화면(web/tour-1011) · 퍼널 신호(ops/booth-qr-1011)는
따로 만들어져서 서로 맞물리는 자리가 각자 테스트에 없다. 그 이음매만 브라우저 없이 잡는다.

 · /hi 「척척발표 살펴보기」 → #/tour, 「바로 내 자료로 해 보기」 → #/rehearsal
 · 투어의 「팀 소개로 돌아가기」 · 닫기는 앱 해시(#/hi)가 아니라 /hi 랜딩으로 (앱에는 hi 화면이 없다)
 · app.js route() 가 옛 #/hi 링크를 /hi 로 넘긴다
 · 투어 목록이 index.json(B 의 스키마)을 읽고, 그 목록의 투어가 다 공개 파일이다
 · 퍼널: intro.html · tour 번들이 js/funnel.js 를 싣고, 화면이 부르는 단계 이름이 전부 서버 허용 목록 안에 있다
 · 화면이 쓰는 공개 파일이 모두 _PUBLIC_PATH 안이다 (팀 쿠키 없는 폰에서 404 0)
화면 속 이름 매핑(funnelStep)은 tests/js/tour.smoke.mjs 가 본다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from demo.static_assets import static_access
from demo.tour_events import STEPS

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "demo" / "YEHS_demo"
INTRO = (WEB / "intro.html").read_text(encoding="utf-8")
INTRO_JS = (WEB / "js" / "intro.js").read_text(encoding="utf-8")
TOUR_JS = (WEB / "js" / "tour.js").read_text(encoding="utf-8")
TOUR_PLAY = (WEB / "js" / "tour_play.js").read_text(encoding="utf-8")
APP_JS = (WEB / "js" / "app.js").read_text(encoding="utf-8")
INDEX = (WEB / "index.html").read_text(encoding="utf-8")


def test_랜딩_주_버튼은_투어로_간다():
    dock = re.search(r'<div class="dock">(.*?)</div>', INTRO, re.S)
    assert dock, "아래 고정 주 버튼 칸이 없어요"
    assert 'href="/index.html#/tour"' in dock.group(1)
    assert "척척발표 살펴보기" in dock.group(1)


def test_랜딩_내_자료_링크는_실제_리허설로_간다():
    links = re.findall(r'<a[^>]*data-needs-camera[^>]*>', INTRO)
    assert len(links) >= 1
    assert all('href="/index.html#/rehearsal"' in a for a in links)


@pytest.mark.parametrize("src", [TOUR_JS, TOUR_PLAY], ids=["tour.js", "tour_play.js"])
def test_투어는_앱_해시_hi_로_보내지_않는다(src):
    # 앱(index.html)엔 hi 화면이 없다 — #/hi 는 홈으로 떨어졌다. 팀 소개는 /hi 랜딩(intro.html)이다
    assert "'#/hi'" not in src and '"#/hi"' not in src and 'href="#/hi"' not in src


def test_투어_끝_화면에_팀_소개와_직접_해_보기가_있다():
    assert TOUR_JS.count('href="/hi" data-back-team') >= 1
    assert "내 자료로 직접 해 보기" in TOUR_JS + TOUR_PLAY
    assert "location.hash = '#/rehearsal'" in TOUR_JS


def test_app_route_는_옛_hash_hi_를_랜딩으로_넘긴다():
    body = APP_JS[APP_JS.index("function route()"):]
    body = body[: body.index("\n}\n")]
    assert "rawKey === 'hi'" in body
    assert "location.replace(" in body and "'/hi'" in body


def _tour_index() -> dict:
    return json.loads((WEB / "data" / "tour" / "index.json").read_text(encoding="utf-8"))


def test_투어_목록은_화면이_읽는_모양이고_파일이_다_공개다():
    idx = _tour_index()
    ids = [t["id"] for t in idx["tours"]]
    assert ids and idx["default"] in ids
    for i in ids:
        assert (WEB / "data" / "tour" / f"{i}.json").is_file(), i
        assert static_access(f"/data/tour/{i}.json") == "public", i
        assert re.fullmatch(r"_?[a-z0-9][a-z0-9-]{0,39}", i), f"{i} 는 퍼널 deck 칸 정규식에 안 맞아 신호가 400 이에요"
    assert static_access("/data/tour/index.json") == "public"


def test_투어_목록의_표지와_장_그림이_공개다():
    for t in _tour_index()["tours"]:
        tour = json.loads((WEB / "data" / "tour" / f"{t['id']}.json").read_text(encoding="utf-8"))
        imgs = [t.get("cover")] + [s.get("image") for s in tour.get("deck", {}).get("slides", [])]
        for p in filter(None, imgs):
            assert (WEB / p).is_file(), p
            assert static_access("/" + p) == "public", p


def test_랜딩과_투어_번들이_funnel_js_를_싣는다():
    assert re.search(r'<script src="/js/funnel\.js\?v=[^"]+" defer></script>', INTRO)
    assert INTRO.index("/js/funnel.js") < INTRO.index("/js/intro.js"), "intro.js 보다 먼저 와야 ccFunnel 이 있다"
    tpl = INDEX[INDEX.index('<template id="lazyAssets">'):]
    assert re.search(r'<script src="js/funnel\.js\?v=[^"]+" data-bundle="tour"></script>', tpl)
    assert static_access("/js/funnel.js") == "public"


def test_화면이_부르는_퍼널_단계가_서버_허용_목록_안이다():
    called = set(re.findall(r"funnel\('([a-z_]+)'\)", INTRO_JS + TOUR_JS))
    assert {"hi", "intro", "team", "team_end", "explore", "inapp_notice", "try_real", "back_team"} <= called
    assert called <= set(STEPS), called - set(STEPS)


@pytest.mark.parametrize("ref", sorted(set(re.findall(r'(?:src|href)="(/[^"#?]+)', INTRO))))
def test_랜딩이_부르는_로컬_파일은_공개다(ref):
    if ref in ("/", "/hi", "/index.html"):
        return
    assert static_access(ref) == "public", ref


def test_투어_번들_파일은_공개다():
    tpl = INDEX[INDEX.index('<template id="lazyAssets">'):]
    files = re.findall(r'(?:src|href)="([^"?]+)\?v=[^"]+" data-bundle="tour"', tpl)
    assert {"css/tour.css", "js/tour.js", "js/tour_logic.js", "js/tour_play.js", "js/funnel.js"} <= set(files)
    for f in files:
        assert (WEB / f).is_file(), f
        assert static_access("/" + f) == "public", f


def test_투어_제목은_표지_머리줄이_아니다():
    # 「배 터 리 공 학 과 … · 2 0 2 6 .」 같은 글자마다 띄운 머리줄이 덱 고르기 카드 제목으로 나가던 것 (10-12 통합에서 잡음)
    def spaced(s: str) -> bool:
        words = s.split()
        singles = sum(1 for w in words if len(w) == 1 and re.match(r"[가-힣0-9]", w))
        return singles >= 5 and singles >= 0.7 * len(words)

    for t in _tour_index()["tours"]:
        tour = json.loads((WEB / "data" / "tour" / f"{t['id']}.json").read_text(encoding="utf-8"))
        titles = [t["title"], tour["deck"]["title"]] + [s["title"] for s in tour["deck"]["slides"]]
        assert not [x for x in titles if spaced(x)], t["id"]
