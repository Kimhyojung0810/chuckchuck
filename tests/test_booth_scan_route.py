"""
부스 「사람 그래프」 스캔 화면(/booth/scan, booth_scan.html) 문지기 회귀 (2026-10-12).

팀 모드에서만 열린다 — 공개 방문자는 /booth/scan 에서 /auth 로 가고(팀 코드가 없는 브리지면 404), /booth_scan.html 을 바로 쳐도 404.
팀 브라우저(쿠키 · DEMO_DEV_ROUTES)에는 그 자리에서 주고, Cloudflare 가 들고 있다가 남에게 내주지 않게 private, no-store.
화면이 부르는 로컬 파일(css · js · QR · MediaPipe 사본)은 공개 허용 목록 안이어야 한다 — 막히면 팀이 열어도 화면이 빈다.
"""

from __future__ import annotations

import re

import pytest

import demo.bridge as bridge
from demo.static_assets import AssetCache, static_access
from tests.test_static_assets import RawHandler

WEB = bridge.DEMO_DIR
CODE = "team-code-for-test"


@pytest.fixture
def site(monkeypatch):
    monkeypatch.setattr(bridge, "STATIC", AssetCache({"/": WEB}))
    monkeypatch.setattr(bridge, "REQUIRE_ACCESS", False)
    monkeypatch.setattr(bridge, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(bridge, "DEV_ROUTES", False)
    monkeypatch.setattr(bridge, "TEAM_CODE", CODE)
    return WEB


def _get(path: str, *, team: bool = False, command: str = "GET") -> tuple[int, dict, bytes]:
    headers = {"Cookie": f"{bridge.TEAM_COOKIE}={bridge._team_token()}"} if team else {}
    h = RawHandler(path, headers=headers, command=command)
    (h.do_HEAD if command == "HEAD" else h.do_GET)()
    return h.response()


def test_주소표():
    assert bridge.team_page_for("/booth/scan") == "/booth_scan.html"
    assert bridge.team_page_for("/booth/scan/") == "/booth_scan.html"
    assert bridge.team_page_for("/Booth/Scan") == "/booth_scan.html"
    for other in ("/booth/scanx", "/booth/scan/a", "/booth/call", "/booth_scan.html", "/hi"):
        assert bridge.team_page_for(other) is None, other
    # /hi 처럼 아무나 여는 독립 페이지 표에는 없다
    assert bridge.standalone_page_for("/booth/scan") is None


def test_파일은_팀_전용이고_부르는_파일은_공개다():
    assert static_access("/booth_scan.html") == "team"
    for url in ("/css/booth_scan.css", "/js/booth_scan.js", "/js/booth_scan_logic.js", "/js/booth_scan_draw.js",
                "/js/booth_scan_worker.js", "/assets/booth-qr-hi.svg",
                "/js/vendor/mediapipe/vision_bundle.mjs", "/js/vendor/mediapipe/face_landmarker.task",
                "/js/vendor/mediapipe/pose_landmarker_lite.task", "/js/vendor/mediapipe/wasm/vision_wasm_module_internal.wasm",
                "/js/vendor/mediapipe/wasm/vision_wasm_module_internal.js"):
        assert static_access(url) == "public", url
    # mediapipe 밖에서는 .task 를 안 연다 · 더 깊은 폴더도
    for url in ("/js/vendor/x.task", "/js/vendor/mediapipe/a/b/c.wasm", "/js/vendor/mediapipe/x.md"):
        assert static_access(url) is None, url


def test_HTML_이_참조하는_로컬_파일은_모두_공개다():
    html = (WEB / "booth_scan.html").read_text(encoding="utf-8")
    refs = [r for r in re.findall(r'\b(?:href|src)="([^"#?]+)', html) if r.startswith("/")]
    assert len(refs) >= 6
    for ref in refs:
        assert static_access(ref) == "public", ref


def test_공개_방문자는_auth_로_간다(site):
    status, hdrs, _ = _get("/booth/scan")
    assert status == 302
    assert hdrs["location"] == "/auth?next=/booth/scan"
    assert hdrs["cache-control"] == "no-store"
    status, hdrs, _ = _get("/booth/scan", command="HEAD")
    assert status == 302


def test_팀_코드가_없는_브리지면_있다는_것도_알리지_않는다(site, monkeypatch):
    monkeypatch.setattr(bridge, "TEAM_CODE", "")
    assert _get("/booth/scan")[0] == 404


def test_파일_주소로_바로_와도_공개_방문자에게는_404(site):
    assert _get("/booth_scan.html")[0] == 404
    assert _get("/booth_scan.html", command="HEAD")[0] == 404


def test_팀_쿠키면_그_자리에서_주고_캐시에_안_남긴다(site):
    status, hdrs, body = _get("/booth/scan", team=True)
    assert status == 200
    assert hdrs["cache-control"] == "private, no-store"
    assert "cdn-cache-control" not in hdrs
    assert "척척발표는 발표하는 당신을 이렇게 읽어요".encode() in body
    assert _get("/booth/scan", team=True, command="HEAD")[0] == 200


def test_DEV_ROUTES_브리지면_코드_없이_열린다(site, monkeypatch):
    monkeypatch.setattr(bridge, "DEV_ROUTES", True)
    monkeypatch.setattr(bridge, "TEAM_CODE", "")
    status, hdrs, _ = _get("/booth/scan")
    assert status == 200 and hdrs["cache-control"] == "private, no-store"


def test_auth_next_는_이_페이지만_주소_그대로_받는다():
    assert bridge._safe_next("/booth/scan") == "/booth/scan"
    assert bridge._safe_next("/BOOTH/SCAN") == "/booth/scan"
    for bad in ("/booth/scan/", "/booth/scan?x=1", "//booth/scan", "/booth/scan/../../x", "/booth_scan.html", "/hi"):
        assert bridge._safe_next(bad) == "", bad


def test_코드를_넣으면_스캔_화면으로_돌아간다(site, monkeypatch):
    import io
    monkeypatch.setattr(bridge.AUTH_LIMITER, "allow", lambda key: True)
    body = f"code={CODE}&next=%2Fbooth%2Fscan".encode()
    h = RawHandler("/auth", headers={"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(body))},
                   command="POST")
    h.rfile = io.BytesIO(body)
    h.do_POST()
    status, hdrs, _ = h.response()
    assert status == 303
    assert hdrs["location"] == "/booth/scan"
    assert "cc_team=v2." in hdrs["set-cookie"]
