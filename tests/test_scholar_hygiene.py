"""
학술 검색 통로의 키·연락 메일 위생 (qa/tidy — 09-30 WP-M 보안 검토가 남긴 둘).

1. Semantic Scholar 키(`x-api-key` 머리)는 **다른 곳으로 넘어가는 되돌리기(3xx)** 에 실리지 않는다. requests 는 Authorization 만
   스스로 떼고 그 밖의 머리는 새 호스트로 그대로 보낸다 — 키를 실은 요청은 되돌리기를 손으로 따라가며 떼어 낸다 (`scholar_impl._send`).
2. 연락 메일은 **받기로 한 곳에만** 간다 — OpenAlex 는 `mailto` 쿼리(OPENALEX_MAILTO, 없으면 SCHOLAR_MAILTO), Crossref 는 `mailto`
   쿼리와 User-Agent(SCHOLAR_MAILTO 만). 09-30 까지는 User-Agent 에 메일을 박아 arXiv·Semantic Scholar·Europe PMC 까지 다섯 통로 모두에
   보냈고, 「OpenAlex 에만」 이라던 OPENALEX_MAILTO 가 Crossref 와 모든 User-Agent 로 넘어갔다.

키·메일 값은 가짜다 — 실제 키 꼴이 아니고 네트워크는 부르지 않는다(requests.get 을 가짜로). 값이 로그·오류 문구에 안 나오는지도 본다.
"""

from __future__ import annotations

import json

import pytest

from chuckchuck.providers import scholar_impl as si
from chuckchuck.providers.scholar_base import ScholarCallError

FAKE_S2 = "s2-fake-1111"
FAKE_MAIL = "lab@example.org"
FAKE_OA_MAIL = "oa-only@example.net"
QUERY = "sourdough starter fermentation"
S2_BASE = "https://api.semanticscholar.org/graph/v1"


class Res:
    def __init__(self, status=200, payload=None, content=b"", headers=None, url=""):
        self.status_code, self._payload, self.content = status, payload, content
        self.headers = headers or {}
        self.url = url
        self.text = json.dumps(payload) if payload is not None else content.decode("utf-8", "replace")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture
def env(monkeypatch):
    """학술 검색 설정을 비우고(.env 가 넣었을 수 있다) 통로 줄 간격을 0 으로."""
    for name in ("OPENALEX_API_KEY", "OPENALEX_MAILTO", "SCHOLAR_MAILTO", "S2_API_KEY", "OPENALEX_BASE_URL", "S2_BASE_URL",
                 "CROSSREF_BASE_URL", "ARXIV_BASE_URL", "EUROPEPMC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(si, "LANES", {n: (slots, 0.0) for n, (slots, _) in si.LANES.items()})
    monkeypatch.setattr(si, "_OPENALEX_NOTED", set())
    si.reset_lanes()
    yield monkeypatch
    si.reset_lanes()


def fake_get(monkeypatch, route):
    """route(url) → Res. 호출마다 주소·쿼리·머리·allow_redirects 를 남긴다."""
    calls: list[dict] = []

    def _get(url, params=None, timeout=None, headers=None, **kw):
        calls.append({"url": url, "params": dict(params or {}), "headers": dict(headers or {}),
                      "allow_redirects": kw.get("allow_redirects", True)})
        return route(url)

    monkeypatch.setattr(si.requests, "get", _get)
    return calls


def s2_hops(*hops):
    """Semantic Scholar 검색 → 되돌리기 hops(Location 들) → 빈 결과."""
    seq = list(hops)

    def route(url):
        if seq:
            return Res(302, headers={"Location": seq.pop(0)}, url=url)
        return Res(payload={"data": []}, url=url)

    return route


def _sent_anywhere(calls, value: str) -> bool:
    return any(value in json.dumps(c, ensure_ascii=False) for c in calls)


# ===========================================================================
# 1. Semantic Scholar 키 — 다른 곳으로 넘어가는 되돌리기에는 싣지 않는다
# ===========================================================================

def test_1_다른_호스트로_되돌리면_키_머리를_떼고_간다(env, capsys):
    calls = fake_get(env, s2_hops("https://mirror.example.com/graph/v1/paper/search?q=x"))
    assert si.SemanticScholarScholar(api_key=FAKE_S2).search(QUERY) == []
    first, second = calls
    assert first["headers"]["x-api-key"] == FAKE_S2 and first["allow_redirects"] is False    # 되돌리기는 손으로 따라간다
    assert second["url"] == "https://mirror.example.com/graph/v1/paper/search?q=x"
    assert "x-api-key" not in {k.lower() for k in second["headers"]} and FAKE_S2 not in json.dumps(second)
    out = capsys.readouterr()
    assert FAKE_S2 not in out.out + out.err                                                     # 값은 어디에도 찍지 않는다


def test_1_같은_호스트로_되돌리면_키를_그대로_싣는다(env):
    calls = fake_get(env, s2_hops("/graph/v1/paper/search?offset=0"))      # 상대 주소 — 같은 곳
    si.SemanticScholarScholar(api_key=FAKE_S2).search(QUERY)
    assert calls[1]["url"].startswith("https://api.semanticscholar.org/graph/v1/paper/search")
    assert calls[1]["headers"]["x-api-key"] == FAKE_S2


def test_1_한_번_넘어간_뒤에는_되돌아와도_다시_싣지_않는다(env):
    calls = fake_get(env, s2_hops("https://cdn.example.com/hop", f"{S2_BASE}/paper/search?again=1"))
    si.SemanticScholarScholar(api_key=FAKE_S2).search(QUERY)
    assert [c["headers"].get("x-api-key") for c in calls] == [FAKE_S2, None, None]


@pytest.mark.parametrize("target,keeps", [
    ("http://api.semanticscholar.org/graph/v1/paper/search", False),     # https → http 내림은 평문이다
    ("https://api.semanticscholar.org:8443/graph/v1/paper/search", False),  # 포트가 다르면 다른 곳
    ("https://API.SemanticScholar.org/graph/v1/x", True),                  # 호스트 대소문자는 같은 곳
])
def test_1_스킴_포트가_다르면_다른_곳이다(env, target, keeps):
    calls = fake_get(env, s2_hops(target))
    si.SemanticScholarScholar(api_key=FAKE_S2).search(QUERY)
    assert ("x-api-key" in calls[1]["headers"]) is keeps


def test_1_http_에서_https_로_올리는_같은_호스트는_같은_곳이다():
    assert si._same_place("http://a.example.org/x", "https://a.example.org/y")
    assert not si._same_place("https://a.example.org/x", "http://a.example.org/y")
    assert not si._same_place("https://a.example.org/x", "https://b.example.org/x")


def test_1_되돌리기가_끝없이_이어지면_http_실패로_끝나고_문구에_키가_없다(env):
    loop = [f"https://hop{i}.example.com/x" for i in range(si.MAX_REDIRECTS + 3)]
    calls = fake_get(env, s2_hops(*loop))
    with pytest.raises(ScholarCallError) as ei:
        si.SemanticScholarScholar(api_key=FAKE_S2).search(QUERY)
    assert ei.value.kind == "http" and "302" in str(ei.value) and FAKE_S2 not in str(ei.value)
    assert len(calls) == si.MAX_REDIRECTS + 1
    assert all("x-api-key" not in c["headers"] for c in calls[1:])


def test_1_키가_없는_요청은_예전처럼_requests_가_되돌리기를_따라간다(env):
    calls = fake_get(env, lambda url: Res(payload={"data": []}, url=url))
    si.SemanticScholarScholar(api_key="").search(QUERY)
    assert calls[0]["allow_redirects"] is True and "x-api-key" not in calls[0]["headers"]


# ===========================================================================
# 2. 연락 메일 — OpenAlex(쿼리)·Crossref(쿼리 + User-Agent)에만
# ===========================================================================

EMPTY = {
    "openalex": Res(payload={"results": []}),
    "semanticscholar": Res(payload={"data": []}),
    "crossref": Res(payload={"message": {"items": []}}),
    "europepmc": Res(payload={"resultList": {"result": []}}),
    "arxiv": Res(content=b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>'),
}


def _each_provider(monkeypatch) -> dict[str, list[dict]]:
    """다섯 통로로 검색 한 번씩 — 통로별 호출 기록."""
    out: dict[str, list[dict]] = {}
    for name in EMPTY:
        calls = fake_get(monkeypatch, lambda url, name=name: EMPTY[name])
        si.get_scholar(name).search(QUERY, limit=1)
        out[name] = calls
    return out


def test_2_두_메일이_다_있으면_각자_받기로_한_곳에만_간다(env):
    env.setenv("SCHOLAR_MAILTO", FAKE_MAIL)
    env.setenv("OPENALEX_MAILTO", FAKE_OA_MAIL)
    sent = _each_provider(env)
    for name in ("semanticscholar", "arxiv", "europepmc"):
        assert not _sent_anywhere(sent[name], FAKE_MAIL) and not _sent_anywhere(sent[name], FAKE_OA_MAIL), name
        assert "mailto" not in sent[name][0]["headers"]["User-Agent"], name
    oa = sent["openalex"][0]
    assert oa["params"]["mailto"] == FAKE_OA_MAIL and "mailto" not in oa["headers"]["User-Agent"]
    assert not _sent_anywhere(sent["openalex"], FAKE_MAIL)                   # 전용 메일이 앞선다 — 팀 메일은 안 간다
    cr = sent["crossref"][0]
    assert cr["params"]["mailto"] == FAKE_MAIL and cr["headers"]["User-Agent"].endswith(f"mailto:{FAKE_MAIL})")
    assert not _sent_anywhere(sent["crossref"], FAKE_OA_MAIL)                # 「OpenAlex 에만」 인 메일은 Crossref 로 안 넘어간다


def test_2_OpenAlex_전용_메일만_있으면_Crossref_에는_메일이_없다(env):
    env.setenv("OPENALEX_MAILTO", FAKE_OA_MAIL)
    sent = _each_provider(env)
    assert sent["openalex"][0]["params"]["mailto"] == FAKE_OA_MAIL
    for name in ("crossref", "semanticscholar", "arxiv", "europepmc"):
        assert not _sent_anywhere(sent[name], FAKE_OA_MAIL), name
    assert si._mailto() == ""


def test_2_Crossref_의_메일_달린_User_Agent_도_다른_호스트로는_안_넘어간다(env):
    env.setenv("SCHOLAR_MAILTO", FAKE_MAIL)
    hops = ["https://elsewhere.example.com/works?rows=1"]

    def route(url):
        if hops:
            return Res(301, headers={"location": hops.pop(0)}, url=url)
        return Res(payload={"message": {"items": []}}, url=url)

    calls = fake_get(env, route)
    si.CrossrefScholar().resolve("Sourdough starter fermentation", doi="10.1/x")
    assert calls[0]["allow_redirects"] is False and FAKE_MAIL in calls[0]["headers"]["User-Agent"]
    assert calls[1]["headers"]["User-Agent"] == si._UA_BASE and not _sent_anywhere(calls[1:], FAKE_MAIL)


def test_2_메일이_없으면_User_Agent_는_기본값이고_머리_값은_ASCII_다(env):
    sent = _each_provider(env)
    for name, calls in sent.items():
        ua = calls[0]["headers"]["User-Agent"]
        assert ua == si._UA_BASE and ua.isascii(), name
        assert "mailto" not in calls[0]["params"], name
