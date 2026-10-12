"""
공개 정적 서빙 허용 목록 회귀 (2026-10-02 정리안 「막기」) — main/server/static_assets.py static_access.

예전엔 main/web 폴더 전체가 공개 주소로 열려서 내부 문서(MVP_SPEC.md 등)·실제 받아쓰기와 서버 경로가 든
data/voice_report_live.json·git 에 없는 sample-deck.pdf 가 누구에게나 200 이었다. 두 방향을 다 잡는다:
막아야 할 것이 404 인지, 그리고 앱이 실제로 받는 경로(index.html·booth.html·리빌이 참조하는 파일)를 하나도 막지 않았는지.
"""

from __future__ import annotations

import re

import pytest

import server.bridge as bridge
from server.static_assets import AssetCache, static_access
from tests.test_static_assets import RawHandler

WEB = bridge.DEMO_DIR


# ─── 순수 함수 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "/", "/index.html", "/f11_reveal.html", "/booth.html", "/intro.html", "/favicon.ico",
    "/css/app.css", "/js/app.js", "/js/booth_cv_worker.js", "/js/vendor/motion.min.js",
    "/js/vendor/opencv.js", "/js/vendor/haarcascade_frontalface_default.xml",
    "/assets/chuckchuck-app-icon-64.png", "/sdk/index.js", "/sdk/rehearsal-recorder.js",
    "/css/./app.css", "/js/../css/app.css",
    # 10-02 뒤 main 에 생긴 것 — 방패의 robots.txt · PDF 보기 · /rehearsal 시연 덱 표지와 장 그림
    "/robots.txt", "/js/vendor/pdfjs/pdf.min.js", "/js/vendor/pdfjs/pdf.worker.min.js",
    "/assets/deck-covers/battery-fastcharge.webp", "/assets/deck-slides/battery-fastcharge/1.webp",
])
def test_앱이_쓰는_종류는_공개다(url):
    assert static_access(url) == "public", url


@pytest.mark.parametrize("url", [
    "/MVP_SPEC.md", "/UI_POLISH_TODO.md", "/UX_ITERATION_LOG.md", "/.gitignore",
    "/prototype-landing.html", "/prototype-report.html", "/chatter_preview.html",
    "/landing.html", "/landing-v2.html", "/sample-deck.pdf",
    "/assets/samples/rehearsal_sample.mp3", "/assets/slides/imu2clip/slide-01.webp",
    "/css/", "/js", "/data/", "/js/vendor/", "/assets/samples/",
    "/css/app.css.map", "/js/app.js.bak", "/js/sub/x.js", "/.env", "/../.env", "/js/%00.js",
])
def test_목록_밖은_아무에게도_안_연다(url):
    assert static_access(url) is None, url


@pytest.mark.parametrize("url", ["/data/voice_report_live.json", "/assets/samples/investor_preview.pdf"])
def test_샘플_데모_자료는_팀_전용이다(url):
    assert static_access(url) == "team"


# ─── 브리지: 막은 경로는 404, 팀 전용은 팀에만 ──────────────────────────────

@pytest.fixture
def leaky_site(tmp_path, monkeypatch):
    """예전에 새던 파일을 다 갖춘 가짜 화면 폴더 — 파일이 «있는데도» 404 인지 본다."""
    web = tmp_path / "web"
    for rel, body in {
        "index.html": "<p>home</p>", "booth.html": "<p>booth</p>", "css/app.css": "body{}",
        "js/app.js": "route();", "MVP_SPEC.md": "# 내부", "prototype-landing.html": "<p>x</p>",
        "chatter_preview.html": "<p>x</p>", "landing.html": "<p>x</p>", ".gitignore": "tmp/",
        "data/voice_report_live.json": '{"transcript_preview":"실제 받아쓰기"}',
        "assets/samples/investor_preview.pdf": "%PDF-1.4", "assets/samples/rehearsal_sample.mp3": "ID3",
        "assets/slides/imu2clip/slide-01.webp": "RIFF", "sample-deck.pdf": "%PDF-1.4",
    }.items():
        p = web / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    monkeypatch.setattr(bridge, "STATIC", AssetCache({"/": web}))
    monkeypatch.setattr(bridge, "REQUIRE_ACCESS", False)
    monkeypatch.setattr(bridge, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(bridge, "DEV_ROUTES", False)
    monkeypatch.setattr(bridge, "TEAM_CODE", "")
    return web


def _get(path: str, command: str = "GET") -> tuple[int, dict, bytes]:
    h = RawHandler(path, command=command)
    (h.do_HEAD if command == "HEAD" else h.do_GET)()
    return h.response()


@pytest.mark.parametrize("url", [
    "/MVP_SPEC.md", "/prototype-landing.html", "/chatter_preview.html", "/landing.html", "/.gitignore",
    "/data/voice_report_live.json", "/assets/samples/investor_preview.pdf", "/assets/samples/rehearsal_sample.mp3",
    "/assets/slides/imu2clip/slide-01.webp", "/sample-deck.pdf", "/data/", "/css/", "/assets/samples/",
])
def test_공개_방문자에게_막은_경로는_404(leaky_site, url):
    assert _get(url)[0] == 404, url
    assert _get(url, "HEAD")[0] == 404, url


def test_열어_둔_경로는_그대로_200(leaky_site):
    for url in ("/", "/index.html", "/booth.html", "/css/app.css", "/js/app.js"):
        assert _get(url)[0] == 200, url


def test_팀_브라우저는_샘플_데모_자료를_받고_캐시에_안_남는다(leaky_site, monkeypatch):
    monkeypatch.setattr(bridge, "DEV_ROUTES", True)
    for url in ("/data/voice_report_live.json", "/assets/samples/investor_preview.pdf"):
        status, hdrs, _ = _get(url)
        assert status == 200, url
        assert hdrs["cache-control"] == "private, no-store", url
    # 팀이어도 내부 문서·시안·git 밖 파일은 안 연다
    for url in ("/MVP_SPEC.md", "/landing.html", "/sample-deck.pdf"):
        assert _get(url)[0] == 404, url


# ─── 앱이 실제로 받는 경로를 막지 않았는가 (진짜 화면 폴더) ──────────────────

_REF = re.compile(r'\b(?:href|src|data-worker)="([^"#?]+)')
_JS_LITERAL = re.compile(r"""['"`]((?:js|css|assets)/[A-Za-z0-9_./-]+\.[a-z0-9]+)""")


def _local(ref: str) -> bool:
    return not re.match(r"^(?:[a-z]+:|//|#)", ref) and not ref.startswith("/api/")


@pytest.mark.parametrize("page", ["index.html", "booth.html", "f11_reveal.html", "intro.html"])
def test_HTML_이_참조하는_로컬_파일은_모두_공개다(page):
    html = (WEB / page).read_text(encoding="utf-8")
    refs = [r for r in _REF.findall(html) if _local(r)]
    assert refs, page
    for ref in refs:
        url = ref if ref.startswith("/") else "/" + ref
        assert static_access(url) == "public", f"{page} → {ref} 가 허용 목록 밖"


def test_JS_가_문자열로_부르는_로컬_파일은_공개거나_팀_전용이다():
    """워커·OpenCV·리빌·샘플 PDF 처럼 JS 안에 박힌 경로. 샘플 데모 자료만 팀 전용이 허용된다."""
    found = {}
    for js in sorted((WEB / "js").glob("*.js")):
        for ref in _JS_LITERAL.findall(js.read_text(encoding="utf-8")):
            found.setdefault(ref, js.name)
    assert found
    for ref, where in found.items():
        assert static_access("/" + ref) in ("public", "team"), f"{where} → {ref} 가 허용 목록 밖"


def test_공개로_여는_실제_파일에는_git_밖_파일이나_문서가_없다():
    """진짜 화면 폴더를 훑어 허용 목록을 통과하는 파일이 앱 파일 종류뿐인지 — 새 .md·.json 이 공개로 새지 않게."""
    for p in WEB.rglob("*"):
        if not p.is_file():
            continue
        rel = "/" + p.relative_to(WEB).as_posix()
        if static_access(rel) == "public":
            # 부스 모바일 계약 파일(docs/booth-mobile/ — 팀 카드 · 녹화 투어 · 팀 사진)만 .json · .jpg 를 연다 (2026-10-11)
            if re.fullmatch(r"/data/team\.json|/data/tour/[A-Za-z0-9_.-]+\.json|/assets/team/[A-Za-z0-9_.-]+\.(?:webp|png|jpg)", rel):
                continue
            # 부스 스캔 화면의 MediaPipe 모델 사본(etc/scripts/get_mediapipe.sh, git 밖)만 .task 를 연다 (2026-10-12)
            if re.fullmatch(r"/js/vendor/mediapipe/[A-Za-z0-9_.-]+\.task", rel):
                continue
            assert p.suffix.lower() in {".html", ".css", ".js", ".mjs", ".png", ".ico", ".svg", ".webp", ".xml", ".wasm", ".txt", ".woff2"}, rel
            assert not rel.endswith(".md")
