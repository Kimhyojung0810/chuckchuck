"""
정적 파일 캐시 회귀 — 오래 캐시해도 옛 판이 남지 않아야 한다 (demo/static_assets.py).

공개 경로는 요청 하나에 ~0.2초, 새 연결에 ~1초가 들어서 첫 화면 파일을 캐시하게 했다. 캐시의 대가는
"고쳤는데 옛 app.js 가 뜬다" 사고라서, 해시가 내용을 따라가는지와 해시가 틀린 요청은 캐시되지 않는지를 잡는다.
"""

from __future__ import annotations

import gzip
import io
import re
from email.message import Message

import pytest

import demo.bridge as bridge
from demo.static_assets import IMMUTABLE, REVALIDATE, AssetCache, accepts_gzip, etag_matches


@pytest.fixture
def site(tmp_path):
    web = tmp_path / "web"
    sdk = tmp_path / "sdk"
    (web / "js").mkdir(parents=True)
    (web / "css").mkdir()
    sdk.mkdir()
    (web / "css" / "app.css").write_text("body{color:red}" * 200)
    (web / "js" / "app.js").write_text("function route(){}\nroute();\n")
    (web / "js" / "bridge.js").write_text("import { A } from '/sdk/index.js';\nexport const B = A;\n")
    (sdk / "index.js").write_text("export { A } from './a.js';\n")
    (sdk / "a.js").write_text("export const A = 1;\n")
    (web / "index.html").write_text(
        '<link rel="stylesheet" href="css/app.css?v=ql9">\n'
        '<script src="js/app.js?v=ql23"></script>\n'
        '<script type="module" src="js/bridge.js?v=qkx7"></script>\n'
        '<script src="https://cdn.example/x.js?v=1"></script>\n'
        '<script src="js/missing.js?v=q1"></script>\n'
    )
    (tmp_path / "secret.env").write_text("KEY=1")
    return tmp_path, AssetCache({"/": web, "/sdk/": sdk})


def _v(html: str, name: str) -> str:
    return re.search(re.escape(name) + r"\?v=([^\"']+)", html).group(1)


def test_HTML_의_v_는_내용_해시로_바뀌고_밖의_주소와_없는_파일은_그대로다(site):
    _, c = site
    html = c.served("/index.html")[0].decode()
    assert _v(html, "css/app.css").startswith("h") and _v(html, "css/app.css") != "ql9"
    assert "https://cdn.example/x.js?v=1" in html
    assert "js/missing.js?v=q1" in html


def test_파일이_바뀌면_HTML_의_해시도_바뀐다(site):
    root, c = site
    before = _v(c.served("/index.html")[0].decode(), "js/app.js")
    (root / "web" / "js" / "app.js").write_text("function route(){ /* 고침 */ }\nroute();\n")
    after = _v(c.served("/index.html")[0].decode(), "js/app.js")
    assert before != after
    assert c.served("/js/app.js")[1] == after


def test_모듈_사슬의_끝이_바뀌면_부모_모듈과_HTML_해시까지_바뀐다(site):
    root, c = site
    html1 = c.served("/index.html")[0].decode()
    bridge1 = _v(html1, "js/bridge.js")
    src = c.served("/js/bridge.js")[0].decode()
    assert re.search(r"from '/sdk/index\.js\?v=h[0-9a-f]{10}'", src)
    (root / "sdk" / "a.js").write_text("export const A = 2;\n")  # 손자만 고친다
    html2 = c.served("/index.html")[0].decode()
    assert _v(html2, "js/bridge.js") != bridge1


def test_일반_스크립트는_import_처럼_보이는_글이_있어도_바꾸지_않는다(site):
    root, c = site
    (root / "web" / "js" / "app.js").write_text("const s = \"import x from './y.js'\";\n")
    body, _ = c.served("/js/app.js")
    assert body.decode() == "const s = \"import x from './y.js'\";\n"


@pytest.mark.parametrize("url", ["/../secret.env", "/sdk/../../secret.env", "/%2e%2e/secret.env", "/js/\x00.js"])
def test_마운트_밖은_열지_않는다(site, url):
    _, c = site
    assert c.served(url) is None


def test_gzip_수락과_ETag_비교():
    assert accepts_gzip("gzip, deflate, br")
    assert accepts_gzip("br;q=1.0, gzip;q=0.8")
    assert not accepts_gzip("gzip;q=0")
    assert not accepts_gzip("br")
    assert etag_matches('"h1", W/"h2"', '"h2"')
    assert not etag_matches('"h1"', '"h2"')


# ─── 브리지 핸들러: 캐시 머리글 ─────────────────────────────────────────────


class RawHandler(bridge.Handler):
    """실제 send_response/end_headers 를 태워 날 응답 바이트를 잡는다."""

    def __init__(self, path: str, headers: dict | None = None, command: str = "GET") -> None:  # noqa: D107
        self.path = path
        self.headers = Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v
        self.rfile = io.BytesIO()
        self.wfile = io.BytesIO()
        self.client_address = ("127.0.0.1", 1)
        self.request_version = "HTTP/1.1"
        self.requestline = f"{command} {path} HTTP/1.1"
        self.command = command
        self.close_connection = False

    def log_message(self, *a) -> None:  # noqa: D102
        pass

    def response(self) -> tuple[int, dict, bytes]:
        raw = self.wfile.getvalue()
        head, _, body = raw.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        status = int(lines[0].split()[1])
        hdrs: dict[str, str] = {}
        for ln in lines[1:]:
            k, _, v = ln.partition(": ")
            hdrs[k.lower()] = hdrs[k.lower()] + ", " + v if k.lower() in hdrs else v
        return status, hdrs, body


@pytest.fixture
def served_site(site, monkeypatch):
    root, c = site
    monkeypatch.setattr(bridge, "STATIC", c)
    monkeypatch.setattr(bridge, "REQUIRE_ACCESS", False)
    monkeypatch.setattr(bridge, "ALLOWED_HOSTS", set())
    return root, c


def _get(path: str, headers: dict | None = None) -> tuple[int, dict, bytes]:
    h = RawHandler(path, headers)
    h.do_GET()
    return h.response()


def test_해시가_맞는_요청만_immutable_이고_틀리면_no_cache(served_site):
    _, c = served_site
    good = c.served("/js/app.js")[1]
    assert _get(f"/js/app.js?v={good}")[1]["cache-control"] == IMMUTABLE
    assert _get("/js/app.js?v=ql23")[1]["cache-control"] == REVALIDATE
    assert _get("/js/app.js")[1]["cache-control"] == REVALIDATE
    # 입구 HTML 은 늘 재검증 — 새 판의 해시 주소를 바로 물어야 한다
    assert _get("/")[1]["cache-control"] == REVALIDATE
    assert _get("/index.html")[1]["cache-control"] == REVALIDATE


def test_캐시_머리글은_하나뿐이고_API_는_no_store_로_남는다(served_site):
    status, hdrs, _ = _get("/css/app.css")
    assert status == 200 and hdrs["cache-control"] == REVALIDATE  # 둘이면 ", " 로 붙어 드러난다
    status, hdrs, _ = _get("/api/health")
    assert hdrs["cache-control"] == "no-store"


def test_ETag_가_같으면_304_이고_본문이_없다(served_site):
    _, hdrs, _ = _get("/css/app.css")
    status, hdrs2, body = _get("/css/app.css", {"If-None-Match": hdrs["etag"]})
    assert status == 304 and body == b"" and hdrs2["etag"] == hdrs["etag"]


def test_gzip_을_받는_브라우저에는_줄여_보내고_내용은_같다(served_site):
    root, _ = served_site
    status, hdrs, body = _get("/css/app.css", {"Accept-Encoding": "gzip"})
    assert hdrs.get("content-encoding") == "gzip" and "accept-encoding" in hdrs["vary"].lower()
    assert gzip.decompress(body) == (root / "web" / "css" / "app.css").read_bytes()
    assert int(hdrs["content-length"]) == len(body)
    _, plain, _ = _get("/css/app.css")
    assert "content-encoding" not in plain and plain["etag"] != hdrs["etag"]


def test_SDK_는_sdk_마운트에서_오고_마운트_밖은_404(served_site):
    status, hdrs, body = _get("/sdk/index.js")
    assert status == 200 and "./a.js?v=h" in body.decode()
    assert hdrs["content-type"].startswith("text/javascript")
    assert _get("/sdk/../../secret.env")[0] == 404


def test_HTML_만_Cloudflare_에_잠깐_맡기고_파일과_API_에는_안_붙인다(served_site):
    assert _get("/")[1].get("cdn-cache-control") == bridge.CDN_HTML_CACHE
    assert "cdn-cache-control" not in _get("/css/app.css")[1]
    assert "cdn-cache-control" not in _get("/api/health")[1]


# ─── 주석·공백 걷기 (esbuild) ───────────────────────────────────────────────

from demo.static_assets import Minifier  # noqa: E402


def _fake_esbuild(tmp_path, body: str) -> str:
    """esbuild 흉내 — 부를 때마다 calls 파일에 한 줄 남긴다."""
    exe = tmp_path / "fake_esbuild"
    exe.write_text(f"#!/bin/sh\necho x >> {tmp_path}/calls\ncat > /dev/null\n{body}\n")
    exe.chmod(0o755)
    return str(exe)


def test_바이너리가_없으면_원본_그대로(tmp_path):
    assert Minifier(None)(b"/* a */ x", "js") == b"/* a */ x"


def test_줄인_결과를_쓰고_같은_내용은_다시_부르지_않는다(tmp_path):
    m = Minifier(_fake_esbuild(tmp_path, "printf 'MIN'"))
    assert m("/* 주석 */ let a = 1;".encode(), "js", "a.js") == b"MIN"
    assert m("/* 주석 */ let a = 1;".encode(), "js", "a.js") == b"MIN"
    assert (tmp_path / "calls").read_text().count("x") == 1


def test_esbuild_가_실패하거나_빈_결과면_원본을_보낸다(tmp_path):
    assert Minifier(_fake_esbuild(tmp_path, "exit 1"))(b"let a;", "js") == b"let a;"
    assert Minifier(_fake_esbuild(tmp_path, "true"))(b"let b;", "js") == b"let b;"


def test_이미_줄인_파일과_HTML_은_건드리지_않는다(tmp_path):
    m = Minifier(_fake_esbuild(tmp_path, "printf 'MIN'"))
    assert m(b"x", "js", "motion.min.js") == b"x"
    assert m(b"<p>", "html", "index.html") == b"<p>"


def test_브리지는_줄인_본문을_보내도_주소_해시는_원본_기준이다(served_site, monkeypatch, tmp_path):
    _, c = served_site
    monkeypatch.setattr(bridge, "MINIFY", Minifier(_fake_esbuild(tmp_path, "printf 'MIN'")))
    good = c.served("/js/app.js")[1]
    status, hdrs, body = _get(f"/js/app.js?v={good}")
    assert body == b"MIN" and hdrs["cache-control"] == IMMUTABLE
    _, _, css = _get("/css/app.css")
    assert css == b"MIN"
    _, _, html = _get("/index.html")
    assert html.startswith(b"<link")  # HTML 은 그대로


@pytest.mark.skipif(not (bridge.ROOT / "tools/bin/esbuild").exists(), reason="scripts/get_esbuild.sh 로 받은 esbuild 없음")
def test_진짜_esbuild_는_한글_주석을_걷고_한글_문자열은_그대로_둔다():
    m = Minifier(str(bridge.ROOT / "tools/bin/esbuild"))
    src = "/* 한국어 주석 */\nconst 말 = `해요 ${1 + 1}`; // 끝\nconst re = /\\/\\/not-comment/;\n".encode()
    out = m(src, "js", "t.js").decode()
    assert "주석" not in out and "끝" not in out
    assert "`해요 ${1+1}`" in out and "/\\/\\/not-comment/" in out


# ─── 검토에서 나온 것 (2026-10-01) ─────────────────────────────────────────


def test_import_고리_안의_모듈에는_해시를_넣지_않아_두_주소로_두_번_실행되지_않는다(site):
    root, c = site
    web = root / "web"
    (web / "js" / "a.js").write_text("import { b } from './b.js?v=m1';\nexport const a = 1;\n")
    (web / "js" / "b.js").write_text("import { a } from './a.js?v=m1';\nexport const b = 2;\n")
    (web / "cyc.html").write_text('<script type="module" src="js/a.js?v=m1"></script>\n')
    html = c.served("/cyc.html")[0].decode()
    a_body = c.served("/js/a.js")[0].decode()
    b_body = c.served("/js/b.js")[0].decode()
    assert 'src="js/a.js?v=m1"' in html  # 예전 주소 그대로
    assert "./b.js?v=m1" in a_body and "./a.js?v=m1" in b_body
    # 고리 밖의 모듈은 여전히 해시를 받는다
    assert re.search(r"/sdk/index\.js\?v=h", c.served("/js/bridge.js")[0].decode())


def test_파일이_바뀌면_읽은_바이트의_해시로_낸다(site):
    root, c = site
    c.served("/js/app.js")  # 기억을 채운다
    (root / "web" / "js" / "app.js").write_text("changed();\n")
    body, digest = c.served("/js/app.js")
    from demo.static_assets import content_digest
    assert digest == content_digest(body)


@pytest.mark.parametrize("url", ["/js/app.js%00.png", "/%00", "/js/%2500"])
def test_NUL_이_섞인_주소는_500_이_아니라_404(served_site, url):
    assert _get(url)[0] == 404
    h = RawHandler(url, command="HEAD")
    h.do_HEAD()
    assert h.response()[0] == 404
