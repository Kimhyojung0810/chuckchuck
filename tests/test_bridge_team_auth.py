"""
팀 인증(/auth) 회귀 — 공개 사이트(chuckchuck-present.com)는 누구나 자기 자료로 쓰고,
이미 있는 데이터(세션 목록·ppt/ 덱·샘플 받아쓰기)는 /auth 를 거친 팀 브라우저에만 연다.
"""

from __future__ import annotations

import json

import pytest

import demo.bridge as bridge
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
    assert _cookie_value(h) == bridge._team_token()


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
    h = _form("/auth", "logout=1")
    assert "Max-Age=0" in h.headers_out["Set-Cookie"]


def test_공개_방문자는_샘플_받아쓰기를_못_받는다(team):
    h = FakeHandler("/api/v1/transcribe", headers=JSON, body=json.dumps({"fixture": True}).encode())
    h.do_POST()
    assert h.last[0] == 400 and h.last[1]["error"] == "fixture_disabled"
