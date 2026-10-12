"""
팀 인증(/auth) 회귀 — 공개 사이트(chuckchuck-present.com)는 누구나 자기 자료로 쓰고,
이미 있는 데이터(세션 목록·main/decks/ 덱·샘플 받아쓰기)는 /auth 를 거친 팀 브라우저에만 연다.
"""

from __future__ import annotations

import json

import pytest

import server.bridge as bridge
from tests.test_bridge_security import JSON, FakeHandler, real  # noqa: F401 — real 은 fixture

CODE = "team-code-for-test"


class CookieHandler(FakeHandler):
    """Set-Cookie 와 HTML 본문을 잡는다."""

    def __init__(self, *a, **kw) -> None:  # noqa: D107
        super().__init__(*a, **kw)
        self.headers_out: dict[str, str] = {}

    def send_header(self, k, v):
        self.headers_out[k] = v

    @property
    def html(self) -> str:
        return self.wfile.getvalue().decode("utf-8")


@pytest.fixture
def team(real, monkeypatch):  # noqa: F811
    monkeypatch.setattr(bridge, "TEAM_CODE", CODE)
    monkeypatch.setattr(bridge.AUTH_LIMITER, "allow", lambda key: True)
    return real


def _form(path: str, body: str, headers: dict | None = None) -> CookieHandler:
    raw = body.encode()
    h = CookieHandler(path, headers={"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}, body=raw)
    h.do_POST()
    return h


def _cookie_value(h: CookieHandler) -> str:
    return h.headers_out["Set-Cookie"].split(";", 1)[0].split("=", 1)[1]


def _get(path: str, cookie: str = "") -> CookieHandler:
    h = CookieHandler(path, headers={"Cookie": f"{bridge.TEAM_COOKIE}={cookie}"} if cookie else {})
    h.do_GET()
    return h


def test_코드가_맞으면_쿠키를_주고_코드_자체는_싣지_않는다(team):
    h = _form("/auth", f"code={CODE}")
    assert h.status == 200
    set_cookie = h.headers_out["Set-Cookie"]
    assert "HttpOnly" in set_cookie and "SameSite=Lax" in set_cookie
    assert CODE not in set_cookie
    tok = _cookie_value(h)
    assert tok.startswith("v2.") and bridge._team_token_ok(tok)


def test_코드가_틀리면_401_이고_쿠키가_없다(team):
    h = _form("/auth", "code=wrong")
    assert h.status == 401 and "Set-Cookie" not in h.headers_out
    assert "코드가 맞지 않아요" in h.html


def test_https_뒤에서는_Secure_쿠키다(team):
    h = _form("/auth", f"code={CODE}", headers={"Cf-Visitor": '{"scheme":"https"}'})
    assert "Secure" in h.headers_out["Set-Cookie"]


def test_코드_맞히기는_분당_제한에_걸린다(team, monkeypatch):
    monkeypatch.setattr(bridge.AUTH_LIMITER, "allow", lambda key: False)
    monkeypatch.setattr(bridge.AUTH_LIMITER, "retry_after", lambda key: 42)
    h = _form("/auth", f"code={CODE}")
    assert h.status == 429 and "Set-Cookie" not in h.headers_out


def test_코드가_비어_있으면_auth_가_닫힌다(real, monkeypatch):  # noqa: F811
    monkeypatch.setattr(bridge, "TEAM_CODE", "")
    h = _get("/auth")
    assert h.last[0] == 404
    h = _form("/auth", "code=")
    assert h.last[0] == 404
    # 빈 코드로 만든 쿠키도 통하지 않는다
    h = _get("/api/v1/team", cookie=bridge._team_token())
    assert h.last == (200, {"team": False})


def test_공개_방문자는_이미_있는_데이터를_못_연다(team):
    for path in ("/api/v1/cached-takes",):
        assert _get(path).last[0] == 404, path
        assert _get(path, cookie="forged").last[0] == 404, path
    assert _get("/api/v1/team").last == (200, {"team": False})


def _fake_decks(monkeypatch):
    rows = [{"key": "배달A", "name": "배달A", "deck": "d.pdf", "audio": "a.m4a", "clova_txt": ""},
            {"key": "_held_x", "name": "_held_x", "deck": "x.pdf", "audio": "", "clova_txt": ""},
            {"key": "수익률격차", "name": "수익률격차", "deck": "s.pdf", "audio": "s.m4a", "clova_txt": ""}]
    manifest = {"groups": [{"id": "booth"}, {"id": "demo"}, {"id": "held"}],
                "decks": {"배달A": {"group": "booth"}, "_held_x": {"group": "held"}, "수익률격차": {"group": "demo"}}}
    monkeypatch.setattr(bridge.Handler, "_deck_entries", staticmethod(lambda: [dict(r) for r in rows]))
    monkeypatch.setattr(bridge.Handler, "_deck_manifest", staticmethod(lambda: manifest))


def test_발표_리허설_덱은_인증_없이_열리고_나머지는_팀_뒤다(team, monkeypatch):
    """10-04 사용자: 「rehearsal 은 auth 제외」 — 부스 시연 세트(group booth)만 공개, 보류·데모 덱과 서버 경로는 팀 뒤."""
    _fake_decks(monkeypatch)
    h = _get("/api/v1/dev/decks")
    status, body = h.last
    assert status == 200 and [r["key"] for r in body["decks"]] == ["배달A"] and "dir" not in body
    assert _get("/api/v1/dev/decks/file?deck=_held_x&kind=deck").last[0] == 404
    assert _get("/api/v1/dev/decks/file?deck=수익률격차&kind=audio").last[0] == 404
    tok = _cookie_value(_form("/auth", f"code={CODE}"))
    status, body = _get("/api/v1/dev/decks", cookie=tok).last
    assert status == 200 and len(body["decks"]) == 3 and "dir" in body


def test_팀_쿠키가_있으면_개발용_경로가_열린다(team):
    tok = _cookie_value(_form("/auth", f"code={CODE}"))
    assert _get("/api/v1/team", cookie=tok).last == (200, {"team": True})
    assert _get("/api/v1/cached-takes", cookie=tok).last[0] == 200
    assert bridge._dev_choice("solar", bridge.DEV_LLM_CHOICES) == "solar"


def test_다른_요청의_팀_표시가_남지_않는다(team):
    tok = _cookie_value(_form("/auth", f"code={CODE}"))
    _get("/api/v1/team", cookie=tok)
    assert _get("/api/v1/cached-takes").last[0] == 404


def test_코드를_바꾸면_이전_쿠키가_풀린다(team, monkeypatch):
    tok = _cookie_value(_form("/auth", f"code={CODE}"))
    monkeypatch.setattr(bridge, "TEAM_CODE", "new-code")
    assert _get("/api/v1/team", cookie=tok).last == (200, {"team": False})


def test_인증_풀기는_쿠키를_지운다(team):
    h = _form("/auth", "logout=1", headers={"Origin": "http://127.0.0.1:8799", "Host": "127.0.0.1:8799"})
    assert h.status == 200 and "Max-Age=0" in h.headers_out["Set-Cookie"]


# ─── 2026-10-02 보안 3건: 쿠키 7일 서버 검사 · 공개 도메인 Secure · 끄기 출처 확인 ──────────

def test_쿠키는_발급_시각을_싣고_서버가_7일을_검사한다(team):
    now = 1_800_000_000
    fresh = bridge._team_token(now - 60)
    assert bridge._team_token_ok(fresh, now=now)
    almost = bridge._team_token(now - bridge.TEAM_COOKIE_MAX_AGE + 5)
    assert bridge._team_token_ok(almost, now=now)
    old = bridge._team_token(now - bridge.TEAM_COOKIE_MAX_AGE - 1)
    assert not bridge._team_token_ok(old, now=now)
    future = bridge._team_token(now + 3600)
    assert not bridge._team_token_ok(future, now=now)


def test_만료된_쿠키로는_팀_경로가_안_열린다(team, monkeypatch):
    tok = bridge._team_token(int(bridge.time.time()) - bridge.TEAM_COOKIE_MAX_AGE - 10)
    assert _get("/api/v1/team", cookie=tok).last == (200, {"team": False})
    assert _get("/api/v1/cached-takes", cookie=tok).last[0] == 404


def test_발급_시각을_고치면_서명이_안_맞는다(team):
    tok = bridge._team_token()
    _, ts, sig = tok.split(".")
    forged = f"v2.{int(ts) + 86400}.{sig}"
    assert not bridge._team_token_ok(forged)
    assert _get("/api/v1/team", cookie=forged).last == (200, {"team": False})


def test_옛_형식_v1_쿠키는_더_통하지_않는다(team):
    import hashlib
    import hmac
    v1 = hmac.new(CODE.encode(), b"chuckchuck-team-v1", hashlib.sha256).hexdigest()
    assert _get("/api/v1/team", cookie=v1).last == (200, {"team": False})


@pytest.mark.parametrize("bad", ["", "v2", "v2.abc.def", "v2.1.2.3", "v1.123.abc", "v2.99999999999999.x"])
def test_모양이_틀린_쿠키는_거절(team, bad):
    assert not bridge._team_token_ok(bad)


def test_ASCII_가_아닌_쿠키도_터지지_않고_거절(team):
    # 방패가 모든 요청에서 팀인지 본다 — 여기서 예외가 나면 요청이 방패 앞에서 터진다 (10-05 방패의 바이트 비교를 v2 에도)
    ts = str(int(bridge.time.time()))
    assert not bridge._team_token_ok(f"v2.{ts}.서명")
    assert not bridge._team_token_ok("v2.²³.abc")  # str.isdigit 은 참인데 int() 는 터지는 글자


def test_공개_도메인으로_오면_헤더가_없어도_Secure(team, monkeypatch):
    monkeypatch.setattr(bridge, "ALLOWED_HOSTS", frozenset({*bridge.LOOPBACK_HOSTS, "chuckchuck-present.com"}))
    h = _form("/auth", f"code={CODE}", headers={"Host": "chuckchuck-present.com"})
    assert "Secure" in h.headers_out["Set-Cookie"]
    h = _form("/auth", f"code={CODE}", headers={"Host": "127.0.0.1:8799"})
    assert "Secure" not in h.headers_out["Set-Cookie"]  # 로컬 http 에서 붙이면 브라우저가 쿠키를 버린다
    h = _form("/auth", f"code={CODE}", headers={"Host": "127.0.0.1:8799", "X-Forwarded-Proto": "https"})
    assert "Secure" in h.headers_out["Set-Cookie"]
    h = _form("/auth", f"code={CODE}", headers={"Host": "127.0.0.1:8799", "Tailscale-Funnel-Request": "?1"})
    assert "Secure" in h.headers_out["Set-Cookie"]


@pytest.mark.parametrize("headers", [
    {"Host": "127.0.0.1:8799"},                                             # 출처 정보 없음
    {"Host": "127.0.0.1:8799", "Origin": "https://evil.example"},
    {"Host": "127.0.0.1:8799", "Origin": "null"},
    {"Host": "127.0.0.1:8799", "Origin": "http://127.0.0.1:9999"},           # 같은 기계의 다른 앱
    {"Host": "127.0.0.1:8799", "Referer": "https://evil.example/page"},
])
def test_다른_출처의_끄기_POST_는_403_이고_쿠키를_안_건드린다(team, headers):
    h = _form("/auth", "logout=1", headers=headers)
    assert h.status == 403
    assert "Set-Cookie" not in h.headers_out


def test_같은_출처의_끄기는_Referer_나_공개_이름으로도_된다(team, monkeypatch):
    h = _form("/auth", "logout=1", headers={"Host": "127.0.0.1:8799", "Referer": "http://127.0.0.1:8799/auth"})
    assert h.status == 200 and "Max-Age=0" in h.headers_out["Set-Cookie"]
    # Cloudflare 가 chuckchuck-present.com 을 ts.net 으로 넘기면 Host 와 Origin 이 다르다
    monkeypatch.setattr(bridge, "ALLOWED_HOSTS", frozenset({*bridge.LOOPBACK_HOSTS, "chuckchuck-present.com", "x.ts.net"}))
    h = _form("/auth", "logout=1", headers={"Host": "x.ts.net", "Origin": "https://chuckchuck-present.com"})
    assert h.status == 200 and "Max-Age=0" in h.headers_out["Set-Cookie"]


def test_공개_방문자는_샘플_받아쓰기를_못_받는다(team):
    h = FakeHandler("/api/v1/transcribe", headers=JSON, body=json.dumps({"fixture": True}).encode())
    h.do_POST()
    assert h.last[0] == 400 and h.last[1]["error"] == "fixture_disabled"


def test_저장된_받아쓰기는_공개_방문자가_세션_id_로_못_읽는다(team):
    """10-08 보안 점검: 공개 /api/v1/dev/decks 가 부스 덱의 세션 id 를 싣고, 같은 덱을 다시 올리면 그 id 가 올린 사람의
    세션으로 바뀐다 — id 만으로 남의 리허설 받아쓰기를 읽었다. 팀 브라우저 · 이 VM 안의 요청만 연다."""
    from tests.test_bridge_security import _open

    sid = _open(team, consent=False, learner="visitor_a")
    team.put_artifact(sid, "transcript", {"full_text": "남의 발표 받아쓰기", "by_slide": []})
    public = {"X-Forwarded-For": "203.0.113.9"}   # Funnel 이 붙이는 흔적 — 바깥 요청

    def get(cookie=""):
        h = CookieHandler(f"/api/v1/cached-transcript?session_id={sid}",
                          headers={**public, **({"Cookie": f"{bridge.TEAM_COOKIE}={cookie}"} if cookie else {})})
        h.do_GET()
        return h.last

    assert get()[0] == 404
    reuse = FakeHandler("/api/v1/transcribe", headers={**JSON, **public},
                        body=json.dumps({"reuse": True, "session_id": sid}).encode())
    reuse.do_POST()
    assert reuse.last[0] == 404 and "남의" not in json.dumps(reuse.last[1], ensure_ascii=False)
    tok = _cookie_value(_form("/auth", f"code={CODE}"))
    assert get(tok) == (200, {"full_text": "남의 발표 받아쓰기", "by_slide": []})
    local = CookieHandler(f"/api/v1/cached-transcript?session_id={sid}")   # 이 VM 안에서 곧장(실험실 · 운영 curl)
    local.do_GET()
    assert local.last[0] == 200


# ─── 2026-10-02 auth 플로우: next 돌려보내기 · 돌아가는 문 · 도구 목록 · DEV_ROUTES 같은 판정 ─────────

def test_코드가_맞고_next_가_있으면_가려던_화면으로_303(team):
    h = _form("/auth", f"code={CODE}&next=%23%2Fbooth%2Fcall")
    assert h.status == 303
    assert h.headers_out["Location"] == "/index.html#/booth/call"
    assert bridge._team_token_ok(_cookie_value(h))


@pytest.mark.parametrize("nxt", [
    "https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "#/../../etc",
    "#/booth/call?x=//evil", "#/unknown", "#/test", "%23%2F" + "a" * 80, "#//evil.example",
])
def test_허용_목록_밖의_next_는_무시하고_도구_목록을_보인다(team, nxt):
    from urllib.parse import quote
    h = _form("/auth", f"code={CODE}&next={quote(nxt, safe='')}")
    assert h.status == 200
    assert "Location" not in h.headers_out
    assert "팀 모드가 켜져 있어요" in h.html


def test_next_는_해시만_받고_늘_index_html_뒤에_붙는다():
    assert bridge._safe_next("#/booth/call") == "#/booth/call"
    assert bridge._safe_next("#/Test/QA") == "#/test/qa"
    assert bridge._safe_next("#/") == "#/"
    assert bridge._safe_next("#/report/sample-investor") == "#/report/sample-investor"
    for bad in ("", "/index.html#/", "http://x", "#/booth/call/../../x", "#/booth\n/call", "#/vision?a=1"):
        assert bridge._safe_next(bad) == "", bad


def test_틀린_코드면_next_를_폼에_그대로_품는다(team):
    h = _form("/auth", "code=wrong&next=%23%2Ftest%2Fqa")
    assert h.status == 401
    assert 'name="next" value="#/test/qa"' in h.html


def test_이미_팀이면_next_로_바로_보낸다(team):
    tok = bridge._team_token()
    h = CookieHandler("/auth?next=%23%2Fbooth%2Fqa", headers={"Cookie": f"{bridge.TEAM_COOKIE}={tok}"})
    h.do_GET()
    assert h.status == 303 and h.headers_out["Location"] == "/index.html#/booth/qa"


def test_auth_화면에는_돌아가는_문이_있고_목록에_부스가_있고_샘플_거짓이_없다(team):
    h = _get("/auth?next=%23%2Fvision")
    assert "서비스로 돌아가기" in h.html and 'href="/index.html#/"' in h.html
    assert 'name="next" value="#/vision"' in h.html
    assert "개발자 모드" not in h.html
    tok = bridge._team_token()
    h = _get("/auth", cookie=tok)
    for href in ("#/booth/call", "#/booth/qa", "#/test/qa", "#/replay", "#/vision", "#/temp"):
        assert f'href="/index.html{href}"' in h.html, href
    assert "샘플 발표·샘플 리포트가 보여요" not in h.html
    assert "서비스로 돌아가기" in h.html and "팀 모드 끄기" in h.html


def test_끄기_성공_문구는_중립_색이고_탭의_베타_표시를_지운다(team):
    h = _form("/auth", "logout=1", headers={"Origin": "http://127.0.0.1:8799", "Host": "127.0.0.1:8799"})
    assert '<p class="note" role="status">팀 모드를 껐어요' in h.html
    assert 'class="err"' not in h.html
    for k in ("cheokcheok:call-flow", "cheokcheok:vision-flow", "cheokcheok:booth-qa", "cheokcheok:team-ok"):
        assert k in h.html


def test_DEV_ROUTES_면_auth_와_team_API_가_같은_판정이다(real, monkeypatch):  # noqa: F811
    monkeypatch.setattr(bridge, "DEV_ROUTES", True)
    monkeypatch.setattr(bridge, "TEAM_CODE", "")
    assert _get("/api/v1/team").last == (200, {"team": True, "dev": True})
    h = _get("/auth")
    assert h.status == 200 and "팀 모드가 켜져 있어요" in h.html
    assert "팀 모드 끄기" not in h.html and "DEMO_DEV_ROUTES=1" in h.html
    h = CookieHandler("/auth?next=%23%2Ftest%2Fqa")
    h.do_GET()
    assert h.status == 303 and h.headers_out["Location"] == "/index.html#/test/qa"


def test_팀_도구_목록은_앱의_알약_메뉴와_같다():
    """js/app.js TEAM_TOOLS 와 브리지 TEAM_TOOLS 의 해시가 같은 순서여야 한다 — 한쪽만 고치면 두 목록이 달라진다."""
    import re
    src = (bridge.DEMO_DIR / "js" / "app.js").read_text(encoding="utf-8")
    block = re.search(r"const TEAM_TOOLS = \[(.*?)\];", src, re.S).group(1)
    assert re.findall(r"'(#/[a-z/]+)'", block) == [t[0] for t in bridge.TEAM_TOOLS]
