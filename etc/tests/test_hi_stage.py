"""
/hi/stage — 결선 부스 QR 랜딩 새 시안 A 「들어오자마자 채점당한다」 (2026-10-13).

지키는 것
 · 주소: /hi/stage 는 intro_stage.html, /hi · /hi/<팀원 id> 는 그대로 intro.html
 · 공개: 공개 방문자가 페이지 · 움직임 좌표(data/hi_stage/*.json)를 받는다 — 허용 목록에 있다
 · 정직성: 칩 숫자 · 문장이 녹화 투어(delivery-rating.json)와 같고 「미리 녹화한 발표」 라벨이 붙는다.
           사람 그래프는 녹화가 아니라서(절차적 움직임) 그래프 쪽 문구에 「녹화」가 없다
 · 무게: 좌표 JSON 이 작고, 모양(프레임 수 · 노드 수)이 맞으며, JS 없이 보이는 정지 그림이 HTML 에 들어 있다
"""
from __future__ import annotations

import json
import re

import pytest

import server.bridge as bridge
from server.static_assets import static_access
from tests.test_static_assets import RawHandler

WEB = bridge.DEMO_DIR
HTML = (WEB / "intro_stage.html").read_text(encoding="utf-8")
POSE = json.loads((WEB / "data" / "hi_stage" / "pose.json").read_text(encoding="utf-8"))
TOUR = json.loads((WEB / "data" / "tour" / "delivery-rating.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("path,expect", [("/hi/stage", "/intro_stage.html"), ("/hi/stage/", "/intro_stage.html"),
                                         ("/HI/Stage", "/intro_stage.html"), ("/hi", "/intro.html"),
                                         ("/hi/hyojung", "/intro.html"), ("/hi/stage/x", None), ("/hi/stages2/a", None)])
def test_주소창_hi_stage_는_시안_페이지다(path, expect):
    assert bridge.standalone_page_for(path) == expect


@pytest.mark.parametrize("path,expect", [("/intro_stage.html", "public"), ("/data/hi_stage/pose.json", "public"),
                                         ("/css/intro_stage.css", "public"), ("/js/intro_stage.js", "public"),
                                         ("/data/hi_stage/sub/x.json", None), ("/data/hi_stage/x.txt", None)])
def test_시안_파일은_공개_허용_목록에_있다(path, expect):
    assert static_access(path) == expect


def test_공개_방문자가_hi_stage_에서_시안을_받는다(monkeypatch):
    monkeypatch.setattr(bridge, "REQUIRE_ACCESS", False)
    monkeypatch.setattr(bridge, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(bridge, "DEV_ROUTES", False)
    monkeypatch.setattr(bridge, "TEAM_CODE", "")
    h = RawHandler("/hi/stage")
    h.do_GET()
    status, _, body = h.response()
    assert status == 200
    html = body.decode("utf-8")
    assert "발표, 미리" in html and 'href="/index.html#/tour"' in html and 'href="/index.html#/rehearsal"' in html
    # 캐시 버전 — /hi 와 같이 브리지가 ?v= 를 내용 해시로 바꿔 준다
    assert re.search(r'/css/intro_stage\.css\?v=h[0-9a-f]+', html) and re.search(r'/js/intro_stage\.js\?v=h[0-9a-f]+', html)
    for ref in re.findall(r'(?:href|src)="([^"#]+)"', html):
        if not re.match(r"^(?:https?:)?//", ref):
            assert ref.startswith("/"), ref   # /hi/stage 아래라 상대 경로면 /hi/css/… 로 샌다


def test_칩_숫자와_문장은_녹화_투어_값이다():
    cpm = round(TOUR["analysis"]["pace"]["cpm"])
    cg = TOUR["analysis"]["claim_graph"]
    claim = next(n for n in cg["nodes"] if n["id"] == cg["root"])
    assert f'<span data-f="cpm">{cpm}</span>' in HTML
    assert f'<span data-f="claim-slide">{claim["slide_no"]}</span>장 핵심 주장' in HTML
    assert TOUR["analysis"]["pace"]["level"] == "practice" and 'st-no">더 연습' in HTML
    assert claim["status"] == "missing" and 'st-om">말하지 않았어요' in HTML
    assert TOUR["qa"]["questions"][0]["answers"]["good"]["verdict"] == "good" and 'st-ok">좋아요' in HTML
    assert "미리 녹화한 발표에서 나온 값이에요" in HTML
    assert TOUR["deck"]["title"] in HTML


def test_사람_그래프는_녹화라고_부르지_않는다():
    fig = HTML[HTML.index('id="fig-hit"'):HTML.index("</button>", HTML.index('id="fig-hit"'))]
    assert "녹화" not in fig
    assert "녹화" not in POSE["note"].replace("녹화한 좌표가 아니에요", "")
    js = (WEB / "js" / "intro_stage.js").read_text(encoding="utf-8")
    assert "gaze" not in js.split("const MOMENT")[1].split("};")[0], "시선 무리는 빛내지 않는다"


def test_좌표_JSON_모양과_무게():
    raw = (WEB / "data" / "hi_stage" / "pose.json").read_bytes()
    assert len(raw) <= 80_000
    n = len(POSE["nodes"])
    assert POSE["schema"] == "chuckchuck.hi-stage-pose" and POSE["fps"] * 8 == len(POSE["frames"])
    assert all(len(f) == 2 * n for f in POSE["frames"]) and len(POSE["still"]) == 2 * n
    assert all(0 <= a < n and 0 <= b < n for a, b in POSE["edges"])
    assert all(0 <= POSE["anchors"][k] < n for k in ("voice", "hand", "head"))


def test_JS_없이도_정지_그림이_있다():
    m = re.search(r"<!-- stage-svg:start[^>]*-->(.*?)<!-- stage-svg:end -->", HTML, re.S)
    assert m and m.group(1).startswith('<svg class="fig-svg"') and 'aria-hidden="true"' in m.group(1)
