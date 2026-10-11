"""
부스 퍼널 신호 `POST /api/v1/tour/event` 회귀 (2026-10-11, demo/tour_events.py · docs/booth-mobile/funnel-events.md).

- 본문: 작은 JSON 객체 · 열쇠 셋 · step 허용 목록 · deck 모양 · t 범위 — 통과한 값만 로그 한 줄에 쓴다(줄 꾸미기 불가)
- 속도: IP 칸 · 전체 칸. IP 칸은 shield.resolve_client 로 센다 — ts.net 으로 바로 와 CF-Connecting-IP 를 바꿔도 한 칸 (10/5 구멍)
- 공개: 팀 쿠키 없이 204. 과금 관문(GATE·SPEND)을 안 거친다
- /hi 는 302 + no-store — Cloudflare 가 저장하지 않으니 QR 진입마다 원본 접근 로그에 한 줄씩 남는다
"""

from __future__ import annotations

import json

import pytest

import demo.bridge as bridge
from demo import shield, tour_events
from tests.test_bridge_security import JSON, FakeHandler, real  # noqa: F401 — real 은 fixture
from tests.test_bridge_shield import ATTACKER, CF_EDGE, VISITOR, Clock

PATH = tour_events.PATH


class HeaderHandler(FakeHandler):
    """보낸 머리글까지 잡는다 (302 Location · Cache-Control 확인용)."""

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.hdrs: list[tuple[str, str]] = []
        self.logged: list[str] = []

    def send_header(self, k, v):
        self.hdrs.append((k, str(v)))
        if k.lower() == "cache-control":
            self._cache_header_sent = True

    def end_headers(self):
        # bridge.Handler.end_headers 처럼 — 캐시 규칙을 따로 정하지 않은 응답엔 no-store
        if not getattr(self, "_cache_header_sent", False):
            self.hdrs.append(("Cache-Control", "no-store"))
        self._cache_header_sent = False

    def log_message(self, fmt, *args):
        self.logged.append(f"{self.address_string()} - - [d] " + (fmt % args))

    def header(self, name: str) -> str | None:
        vals = [v for k, v in self.hdrs if k.lower() == name.lower()]
        return vals[-1] if vals else None


def _send(payload, headers: dict | None = None) -> HeaderHandler:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    h = HeaderHandler(PATH, headers={**JSON, **(headers or {})}, body=raw)
    h.command = "POST"
    h.do_POST()
    return h


@pytest.fixture
def tour(real, monkeypatch):  # noqa: F811
    """방패 부품 초기화 + 작은 신호 상한(IP 3 · 전체 50). 과금 관문이 불리면 실패."""
    clock = Clock()
    monkeypatch.setattr(bridge, "EDGE_SECRET", "")
    monkeypatch.setattr(bridge, "EDGE_LOCK", False)
    monkeypatch.setattr(bridge, "FLOOD", shield.FloodLimiter(limit=1000, clock=clock))
    monkeypatch.setattr(bridge, "JAIL", shield.Jail(strikes=1000, window_sec=60, ban_sec=600, clock=clock))
    monkeypatch.setattr(tour_events, "LIMITER", tour_events.TourEventLimiter(per_ip=3, global_limit=50, clock=clock))
    monkeypatch.setattr(bridge.Handler, "_handle_paid", lambda *a, **k: pytest.fail("퍼널 신호가 과금 관문을 탔다"))
    return clock


def via_cf(visitor: str) -> dict:
    """도메인 경유 — Cloudflare → Funnel. X-Forwarded-For 마지막 칸이 Cloudflare 서버."""
    return {"X-Forwarded-For": CF_EDGE, "CF-Connecting-IP": visitor, "Host": "127.0.0.1"}


# ─── 1. 본문 검사 (순수 함수) ─────────────────────────────────────────────────


def test_맞는_신호는_세_칸만_돌려준다():
    assert tour_events.parse_event(b'{"step":"tour_qa","deck":"battery-fastcharge","t":42.7}') == \
        {"step": "tour_qa", "deck": "battery-fastcharge", "t": 42}
    assert tour_events.parse_event(b'{"step":"hi"}') == {"step": "hi", "deck": None, "t": None}
    assert tour_events.parse_event(b'{"step":"tour_deck","deck":"_example"}')["deck"] == "_example"


@pytest.mark.parametrize("raw,code", [
    (b"", "bad_body"),
    (b"x" * (tour_events.BODY_MAX + 1), "bad_body"),
    (b"not json", "bad_json"),
    (b"[1,2]", "bad_keys"),
    (b"{}", "bad_keys"),
    (b'{"step":"hi","ua":"x"}', "bad_keys"),              # 모르는 열쇠 — 아무거나 실어 로그를 키우지 못하게
    (b'{"step":"admin"}', "bad_step"),
    (b'{"step":"hi\\nFAKE - - [x] \\"GET /hi\\""}', "bad_step"),  # 줄바꿈으로 가짜 접근 로그 줄 만들기
    (b'{"step":1}', "bad_step"),
    (b'{"step":"tour_deck","deck":"../../etc"}', "bad_deck"),
    (b'{"step":"tour_deck","deck":"A B"}', "bad_deck"),
    (b'{"step":"tour_deck","deck":"' + b"a" * 41 + b'"}', "bad_deck"),
    (b'{"step":"hi","t":-1}', "bad_t"),
    (b'{"step":"hi","t":86401}', "bad_t"),
    (b'{"step":"hi","t":true}', "bad_t"),                 # bool 은 int 의 하위형 — 막는다
    (b'{"step":"hi","t":NaN}', "bad_t"),                  # json.loads 는 NaN·Infinity 를 받는다
    (b'{"step":"hi","t":Infinity}', "bad_t"),
    (b'{"step":"hi","t":"3"}', "bad_t"),
])
def test_틀린_본문은_이유와_함께_거절한다(raw, code):
    with pytest.raises(tour_events.TourEventError) as e:
        tour_events.parse_event(raw)
    assert e.value.code == code


def test_로그_몸통은_빈_값을_대시로_쓰고_한_줄이다():
    assert tour_events.log_fields({"step": "hi", "deck": None, "t": None}) == "tour step=hi deck=- t=-"
    line = tour_events.log_fields(tour_events.parse_event(b'{"step":"tour_report","deck":"sleep","t":0}'))
    assert line == "tour step=tour_report deck=sleep t=0" and "\n" not in line


def test_단계_목록은_화면_차례이고_겹치지_않는다():
    assert tour_events.STEPS[0] == "hi" and tour_events.STEPS.index("explore") < tour_events.STEPS.index("tour_deck")
    assert len(set(tour_events.STEPS)) == len(tour_events.STEPS)


# ─── 2. 브리지 배선 ──────────────────────────────────────────────────────────


def test_공개_신호는_204_이고_방문자_IP_로_한_줄만_남긴다(tour):
    h = _send({"step": "explore", "deck": "battery-fastcharge", "t": 12}, via_cf(VISITOR))
    assert h.status == 204 and h.sent == []
    assert h.logged == [f"{VISITOR} - - [d] tour step=explore deck=battery-fastcharge t=12"]
    assert h._quiet is True  # 접근 로그 줄(POST … 204)을 따로 남기지 않는다 — 같은 정보가 두 줄이 되지 않게
    assert not bridge._paid_path(PATH)


def test_틀린_본문은_400_이고_로그_줄을_쓰지_않는다(tour):
    h = _send({"step": "nope"}, via_cf(VISITOR))
    assert h.last == (400, {"error": "bad_event", "reason": "bad_step"})
    assert h.logged == []


def test_큰_본문은_읽지_않고_413(tour):
    h = _send(b'{"step":"hi","pad":"' + b"x" * 600 + b'"}', via_cf(VISITOR))
    code, body = h.last
    assert code == 413 and "512바이트" in body["message"]


def test_JSON_이_아니면_415_교차_출처_폼은_preflight_없이_못_온다(tour):
    h = HeaderHandler(PATH, headers={"Content-Type": "text/plain", **via_cf(VISITOR)}, body=b'{"step":"hi"}')
    h.do_POST()
    assert h.last[0] == 415


def test_ts_net_으로_바로_와서_CF_Connecting_IP_를_바꿔도_한_칸으로_막힌다(tour):
    codes = []
    for i in range(6):
        h = _send({"step": "hi"}, {"X-Forwarded-For": ATTACKER, "CF-Connecting-IP": f"1.2.3.{i}", "Host": "127.0.0.1"})
        codes.append(h.status if h.status == 204 else h.last[0])
    assert codes == [204, 204, 204, 429, 429, 429]
    h = _send({"step": "hi"}, {"X-Forwarded-For": ATTACKER, "CF-Connecting-IP": "9.9.9.9", "Host": "127.0.0.1"})
    code, body = h.last
    assert code == 429 and body["scope"] == "tour_ip" and body["retry_after"] >= 1
    assert ("Retry-After", str(body["retry_after"])) in h._extra_headers  # 실제 end_headers 가 얹는다
    assert h.logged == []


def test_도메인으로_온_방문자는_서로_다른_칸이다(tour):
    for _ in range(3):
        assert _send({"step": "team"}, via_cf(VISITOR)).status == 204
    assert _send({"step": "team"}, via_cf(VISITOR)).last[0] == 429
    assert _send({"step": "team"}, via_cf("203.0.113.77")).status == 204   # 다른 방문자는 그대로


def test_섞인_칸과_VM_안_요청은_IP_칸_대신_전체_칸만_센다(tour, monkeypatch):
    monkeypatch.setattr(tour_events, "LIMITER", tour_events.TourEventLimiter(per_ip=1, global_limit=4, clock=tour))
    # Cloudflare 서버 IP 로만 잡힌 칸(CF-Connecting-IP 없음) — 여러 사람이 섞였으니 IP 칸에 넣지 않는다
    assert [_send({"step": "hi"}, {"X-Forwarded-For": CF_EDGE, "Host": "127.0.0.1"}).status for _ in range(2)] == [204, 204]
    # VM 안 곧장(실험실·벤치) — 팀 대접, IP 칸 없음. 전체 칸 4 에서 멈춘다
    assert [_send({"step": "hi"}).status for _ in range(2)] == [204, 204]
    h = _send({"step": "hi"})
    assert h.last[0] == 429 and h.last[1]["scope"] == "tour_global"


def test_전체_칸에_막히면_IP_칸을_되돌린다():
    clock = Clock()
    lim = tour_events.TourEventLimiter(per_ip=5, global_limit=1, clock=clock)
    assert lim.allow("a")[0] is True
    assert lim.allow("a")[:2] == (False, "global")
    assert lim.per_ip.count("a") == 1   # 막힌 한 번은 IP 칸에서 빠졌다
    clock.t += 61
    assert lim.allow("a")[0] is True


def test_반복_신호가_전체_칸을_채워도_새_방문자의_첫_신호는_받는다():
    """perf-security-copy-r1-1 — IP 11개가 같은 단계를 되풀이해 전체 상한을 1분 내내 채우자 진짜 방문객 신호가 다 429 였다.
    (IP 칸, 단계) 의 첫 신호는 반복과 다른 칸(first)에서 센다. 반복은 전체 칸에서만."""
    clock = Clock()
    lim = tour_events.TourEventLimiter(per_ip=100, global_limit=5, first_limit=50, clock=clock)
    attackers = [f"45.33.{i}.7" for i in range(3)]
    results = [lim.allow(ip, "tour_deck")[0] for _ in range(10) for ip in attackers]
    assert results.count(True) == 3 + 5          # 첫 신호 셋(first 칸) + 반복 다섯(전체 칸)
    assert lim.allow("52.79.10.20", "hi") == (True, "", 0)          # 새 방문자 첫 단계
    assert lim.allow("52.79.10.20", "tour_deck") == (True, "", 0)   # 같은 방문자의 다음 단계도 첫 신호
    assert lim.allow("52.79.10.20", "hi")[:2] == (False, "global")  # 같은 단계를 되풀이하면 반복이라 막힌다
    assert lim.per_ip.count("52.79.10.20") == 2                     # 막힌 한 번은 IP 칸에서 빠졌다


def test_첫_신호_칸도_상한이_있다():
    """CF-Connecting-IP 를 바꿔 가며(DEMO_EDGE_SECRET 꺼짐) 첫 신호만 쏟아도 로그 줄은 first + 전체 상한을 못 넘는다."""
    clock = Clock()
    lim = tour_events.TourEventLimiter(per_ip=100, global_limit=2, first_limit=4, clock=clock)
    ok = [lim.allow(f"10.0.{i}.1", "hi")[0] for i in range(10)]
    assert ok.count(True) == 4 + 2               # first 칸 4 가 차면 전체 칸으로 넘어가 2 더
    assert lim.allow("10.9.9.9", "hi")[:2] == (False, "global")
    clock.t += 61
    assert lim.allow("10.9.9.9", "hi")[0] is True


def test_반복_신호_폭주_중에도_새_방문자의_첫_신호는_204(tour, monkeypatch):
    monkeypatch.setattr(tour_events, "LIMITER", tour_events.TourEventLimiter(per_ip=100, global_limit=6, first_limit=50, clock=tour))
    codes = [_send({"step": "tour_deck"}, via_cf(f"45.33.{i}.7")).status or 0 for _ in range(6) for i in range(3)]
    assert codes.count(204) == 3 + 6
    h = _send({"step": "tour_deck"}, via_cf("45.33.0.7"))
    assert h.last[0] == 429 and h.last[1]["scope"] == "tour_global"
    assert _send({"step": "hi"}, via_cf("52.79.10.20")).status == 204
    # 틀린 본문도 여전히 상한에 먼저 걸린다 — 400 접근 로그로 디스크를 채우는 길이 없다
    assert _send({"step": "nope"}, via_cf("45.33.1.7")).last[0] == 429


def test_차단_목록_IP_는_신호도_못_보낸다(tour, monkeypatch, tmp_path):
    f = tmp_path / "blocklist.txt"
    f.write_text(f"{VISITOR}\n")
    monkeypatch.setattr(bridge, "BLOCKLIST", shield.Blocklist(f, check_every=0))
    h = _send({"step": "hi"}, via_cf(VISITOR))
    assert h.last[0] == 403 and h.logged == []


# ─── 3. /hi 는 원본까지 온다 ─────────────────────────────────────────────────


def test_hi_는_원본까지_오고_접근_로그에_남는다(tour):
    """지금은 302(→ #/hi, no-store). 랜딩 페이지가 따로 서면(intro.html) 200 + 브라우저 no-cache 다 — 어느 쪽이든
    확장자 없는 주소라 Cloudflare 가 기본으로 저장하지 않아 QR 진입마다 원본 접근 로그에 한 줄씩 남는다."""
    h = HeaderHandler("/hi", headers=via_cf(VISITOR))
    h.do_GET()
    assert h.status in (200, 302)
    if h.status == 302:
        assert h.header("Location") == "/index.html#/hi"
        assert h.header("Cache-Control") == "no-store"
    else:
        assert h.header("Cache-Control") in ("no-cache", "no-store")
    assert not getattr(h, "_quiet", False)  # 접근 로그 줄(GET /hi …)이 남는다 — booth_funnel 이 이 줄로 /hi 진입을 센다


# ─── 4. 투어 파일은 Cloudflare 에 잠깐 맡긴다 ────────────────────────────────

from tests.test_static_assets import RawHandler  # noqa: E402


def _raw_get(path: str) -> tuple[int, dict]:
    h = RawHandler(path)
    h.do_GET()
    status, hdrs, _ = h.response()
    return status, hdrs


@pytest.mark.parametrize("path", [
    "/data/team.json", "/data/tour/_example.json",
    "/assets/deck-slides/battery-fastcharge/1.webp", "/assets/deck-covers/battery-fastcharge.webp",
])
def test_화면이_v_없이_받는_투어_파일은_브라우저는_재검증_Cloudflare_는_60초(real, monkeypatch, path):  # noqa: F811
    monkeypatch.setattr(bridge, "ALLOWED_HOSTS", set())
    status, hdrs = _raw_get(path)
    assert status == 200, path
    assert hdrs["cache-control"] == "no-cache" and hdrs.get("etag")
    assert hdrs.get("cdn-cache-control") == bridge.CDN_HTML_CACHE


def test_해시_주소는_그대로_1년이고_팀_전용과_다른_파일엔_안_붙인다(real, monkeypatch):  # noqa: F811
    monkeypatch.setattr(bridge, "ALLOWED_HOSTS", set())
    digest = bridge.STATIC.served("/data/tour/_example.json")[1]
    _, hdrs = _raw_get(f"/data/tour/_example.json?v={digest}")
    assert hdrs["cache-control"] == bridge.IMMUTABLE and "cdn-cache-control" not in hdrs
    _, hdrs = _raw_get("/js/app.js")
    assert "cdn-cache-control" not in hdrs
    # 팀 전용 data/*.json — 공개 방문자에게 404, Cloudflare 에 맡길 일이 없다
    status, hdrs = _raw_get("/data/voice_report_live.json")
    assert status == 404 and "cdn-cache-control" not in hdrs
    from demo.static_assets import edge_short
    assert not edge_short("/data/voice_report_live.json") and not edge_short("/data/tour/../voice_report_live.json")
    assert edge_short("/data/tour/battery-fastcharge.json") and edge_short("/assets/team/hyojung.webp")
