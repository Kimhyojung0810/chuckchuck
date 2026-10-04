"""
방패(2026-10-05, AI Festa 부스 전날) 회귀 — demo/shield.py 부품과 bridge 배선.

- IP 위조: ts.net 으로 바로 와 CF-Connecting-IP 를 바꿔 보내도 IP 상한을 못 피한다 (X-Forwarded-For 마지막 칸 · 비밀 머리글)
- 원본 잠금: 비밀 머리글 없는 공개 요청 403 — 팀 쿠키·/auth·VM 안 요청은 연다
- 과금 동시 실행 칸: 다 차면 503 busy(+Retry-After), 팀 몫 칸은 공개 요청이 못 쓴다, 예외가 나도 칸이 샌다
- 감옥: 막혀도 계속 두드리면 가두고, 시간이 지나면 풀린다 · 차단 목록(주소대 포함)은 파일만 고치면 다시 읽는다
- 점검 깃발 · 시간당 천장 · 요청 제한 표 정리 · /api/v1/ops/shield 는 팀만
- 실제 소켓: 연결 상한 넘으면 503 · 머리글을 늦게 보내는 연결은 끊긴다
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time

import pytest

import demo.bridge as bridge
from demo import shield
from demo.rate_limit import RateLimiter
from tests.test_bridge_security import JSON, FakeHandler, real  # noqa: F401 — real 은 fixture

TEAM = "team-code-for-shield"
CF_EDGE = "172.70.1.2"          # Cloudflare 주소대(172.64.0.0/13) 안
VISITOR = "203.0.113.50"
ATTACKER = "198.51.100.7"


class Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def H(**headers) -> dict:
    return {k.replace("_", "-"): v for k, v in headers.items()}


# ─── 1. 클라이언트 IP ─────────────────────────────────────────────────────────


def test_ts_net_으로_바로_와서_CF_Connecting_IP_를_위조해도_자기_IP_로_센다():
    ip, via = shield.resolve_client("127.0.0.1", H(X_Forwarded_For=ATTACKER, CF_Connecting_IP="1.2.3.4"))
    assert (ip, via) == (ATTACKER, "xff")
    # X-Forwarded-For 앞쪽 칸을 꾸며도 마지막 칸(Funnel 이 적은 것)이 이긴다
    ip, _ = shield.resolve_client("127.0.0.1", H(X_Forwarded_For=f"{CF_EDGE}, {ATTACKER}", CF_Connecting_IP="1.2.3.4"))
    assert ip == ATTACKER


def test_Cloudflare_를_거쳐_온_요청은_방문자_IP_로_센다():
    assert shield.resolve_client("127.0.0.1", H(X_Forwarded_For=CF_EDGE, CF_Connecting_IP=VISITOR)) == (VISITOR, "cf")
    v6 = shield.resolve_client("::1", H(X_Forwarded_For="2606:4700:10::1", CF_Connecting_IP="2001:db8::5"))
    assert v6 == ("2001:db8::5", "cf")


def test_비밀을_정하면_머리글이_맞을_때만_CF_Connecting_IP_를_믿는다():
    secret = "s3cret-value"
    ok = shield.resolve_client("127.0.0.1", H(X_Forwarded_For=CF_EDGE, CF_Connecting_IP=VISITOR, X_Edge_Auth=secret), secret)
    assert ok == (VISITOR, "edge")
    # 비밀이 틀려도 Cloudflare 를 거쳐 왔으면 방문자 IP — 대시보드 규칙을 넣기 전에 비밀부터 정해도 방문자가 한 칸에 안 묶인다
    bad = shield.resolve_client("127.0.0.1", H(X_Forwarded_For=CF_EDGE, CF_Connecting_IP=VISITOR, X_Edge_Auth="nope"), secret)
    assert bad == (VISITOR, "cf")
    # Cloudflare 를 거쳤는데 CF-Connecting-IP 가 없으면 그 서버 IP — 그런 칸은 홍수 제한·감옥에 안 넣는다
    assert shield.resolve_client("127.0.0.1", H(X_Forwarded_For=CF_EDGE), secret) == (CF_EDGE, "xff")
    assert not shield.attributable(CF_EDGE) and not shield.attributable("100.100.1.1") and shield.attributable(VISITOR)
    none = shield.resolve_client("127.0.0.1", H(X_Forwarded_For=ATTACKER, CF_Connecting_IP=VISITOR), secret)
    assert none == (ATTACKER, "xff")
    # VM 안에서 머리글만 붙여 보내도 비밀 없이는 안 믿는다
    assert shield.resolve_client("127.0.0.1", H(CF_Connecting_IP=VISITOR), secret) == ("127.0.0.1", "local")


def test_X_Forwarded_For_가_없거나_우리_설비면_예전처럼_믿는다():
    assert shield.resolve_client("127.0.0.1", H(CF_Connecting_IP=VISITOR)) == (VISITOR, "legacy")
    assert shield.resolve_client("127.0.0.1", H(X_Forwarded_For="100.101.1.2", CF_Connecting_IP=VISITOR)) == (VISITOR, "legacy")
    assert shield.resolve_client("127.0.0.1", H()) == ("127.0.0.1", "local")
    assert shield.resolve_client("10.0.0.7", H(CF_Connecting_IP=VISITOR)) == ("10.0.0.7", "peer")


def test_이상한_머리글은_IP_로_쓰지_않는다():
    ip, via = shield.resolve_client("127.0.0.1", H(X_Forwarded_For="not-an-ip", CF_Connecting_IP="<script>"))
    assert (ip, via) == ("127.0.0.1", "local")
    assert shield.parse_ip("::ffff:203.0.113.9") == shield.parse_ip("203.0.113.9")
    assert shield.parse_ip("[2001:db8::1]") is not None


def test_IPv6_는_64_칸으로_묶는다():
    assert shield.ip_bucket("2001:db8:1:2::5") == shield.ip_bucket("2001:db8:1:2:ffff::9") == "2001:db8:1:2::/64"
    assert shield.ip_bucket("203.0.113.9") == "203.0.113.9"


def test_핸들러의_요청_제한_키도_위조를_무시한다():
    h = FakeHandler("/", headers=H(X_Forwarded_For=ATTACKER, CF_Connecting_IP="9.9.9.9"))
    assert h._client_key() == ATTACKER


# ─── 공통 fixture ─────────────────────────────────────────────────────────────


@pytest.fixture
def sh(real, monkeypatch, tmp_path):  # noqa: F811
    """새 방패 부품 + 팀 코드 + 과금 경로 대역(_route_post). 공개 요청은 X-Forwarded-For 로 흉내 낸다."""
    clock = Clock()
    monkeypatch.setattr(bridge, "TEAM_CODE", TEAM)
    monkeypatch.setattr(bridge, "EDGE_SECRET", "")
    monkeypatch.setattr(bridge, "EDGE_LOCK", False)
    monkeypatch.setattr(bridge, "FLOOD", shield.FloodLimiter(limit=1000, clock=clock))
    monkeypatch.setattr(bridge, "JAIL", shield.Jail(strikes=1000, window_sec=60, ban_sec=600, clock=clock))
    monkeypatch.setattr(bridge, "GATE", shield.PaidGate(capacity=4, reserved=2))
    monkeypatch.setattr(bridge, "PAID_QUEUE_SEC", 0.05)
    monkeypatch.setattr(bridge, "SPEND", RateLimiter(limit=1000, window_sec=3600, clock=clock))
    monkeypatch.setattr(bridge, "PAID_PER_HOUR", 1000)
    monkeypatch.setattr(bridge, "BLOCKLIST", shield.Blocklist(tmp_path / "blocklist.txt", check_every=0))
    monkeypatch.setattr(bridge, "LOCKDOWN", shield.FlagFile(tmp_path / "lockdown", check_every=0))
    monkeypatch.setattr(bridge, "EVENTS", shield.EventCounter(clock=clock))
    calls: list[str] = []

    def route(self, parsed, raw):
        calls.append(parsed.path)
        if parsed.path == "/api/v1/boom":
            raise RuntimeError("boom")
        return self._json(200, {"ok": True, "inflight": bridge.GATE.snapshot()["inflight"]})

    monkeypatch.setattr(bridge.Handler, "_route_post", route)
    return clock, calls, tmp_path


def team_cookie() -> str:
    return f"{bridge.TEAM_COOKIE}={bridge._team_token()}"


def public(ip: str = VISITOR, **extra) -> dict:
    return {"X-Forwarded-For": CF_EDGE, "CF-Connecting-IP": ip, **extra}


def post(path: str, headers: dict, payload: dict | None = None) -> FakeHandler:
    raw = json.dumps(payload or {}).encode()
    h = FakeHandler(path, headers={**JSON, **headers}, body=raw)
    h.command = "POST"
    h.do_POST()
    return h


def get(path: str, headers: dict) -> FakeHandler:
    h = FakeHandler(path, headers=headers)
    h.do_GET()
    return h


def retry_after(h: FakeHandler) -> str | None:
    return dict(getattr(h, "_extra_headers", []) or []).get("Retry-After")


# ─── 2. 원본 잠금 ─────────────────────────────────────────────────────────────


def test_원본_잠금은_비밀_머리글_없는_공개_요청만_막는다(sh, monkeypatch):
    monkeypatch.setattr(bridge, "EDGE_SECRET", "edge-secret")
    monkeypatch.setattr(bridge, "EDGE_LOCK", True)
    # ts.net 직접 — 비밀 없음 → 403, 본문은 짧다
    h = get("/api/v1/team", {"X-Forwarded-For": ATTACKER})
    assert h.last == (403, {"error": "forbidden"})
    # 도메인 경유 — Cloudflare 가 비밀을 붙였다
    h = get("/api/v1/team", {**public(), "X-Edge-Auth": "edge-secret"})
    assert h.last[0] == 200
    # 팀 쿠키면 ts.net 으로 바로 와도 연다 (도메인이 죽었을 때 부스 노트북의 길)
    h = get("/api/v1/team", {"X-Forwarded-For": ATTACKER, "Cookie": team_cookie()})
    assert h.last == (200, {"team": True})
    # /auth 는 연다 — 쿠키를 받으러 오는 곳
    h = get("/auth", {"X-Forwarded-For": ATTACKER})
    assert h.status == 200 and not h.sent
    # VM 안 요청(머리글 없음)은 상관없다
    assert get("/api/v1/team", {}).last[0] == 200


def test_비밀이_없으면_잠금은_켜지지_않는다(sh, monkeypatch):
    monkeypatch.setattr(bridge, "EDGE_LOCK", False)
    assert get("/api/v1/team", {"X-Forwarded-For": ATTACKER}).last[0] == 200


# ─── 3. 과금 동시 실행 칸 ─────────────────────────────────────────────────────


def test_PaidGate_공개는_예약_칸을_못_쓰고_팀은_쓴다():
    g = shield.PaidGate(capacity=4, reserved=2)
    assert g.acquire(False, 0)[0] and g.acquire(False, 0)[0]
    assert g.acquire(False, 0.02)[0] is False               # 공개 몫(2) 다 참
    assert g.acquire(True, 0)[0] and g.acquire(True, 0)[0]  # 팀은 예약 칸까지
    assert g.acquire(True, 0.02)[0] is False                # 전체(4)가 다 참
    g.release(False)
    assert g.acquire(False, 0)[0] is False                  # 아직 4칸 중 3칸이 차 있어 공개 한도(2) 위
    g.release(True)
    assert g.acquire(False, 0)[0] is False
    g.release(True)
    assert g.acquire(False, 0)[0]
    assert g.snapshot()["inflight"] == 2


def test_PaidGate_는_기다리는_사이_칸이_비면_들어간다():
    g = shield.PaidGate(capacity=1, reserved=0)
    assert g.acquire(False, 0)[0]
    threading.Timer(0.05, g.release, args=(False,)).start()
    ok, waited = g.acquire(False, 2.0)
    assert ok and 0.03 < waited < 1.5


def test_칸이_다_차면_503_busy_와_Retry_After(sh):
    for _ in range(2):
        bridge.GATE.acquire(False, 0)
    h = post("/api/v1/questions", public())
    code, body = h.last
    assert code == 503 and body["error"] == "busy" and body["busy"] is True
    assert body["rate_limited"] is True                     # 프론트 judgeRetryPlan 이 기다렸다 다시 보낸다
    assert "지금 사용자가 많아요" in body["message"] and retry_after(h) == str(body["retry_after"])
    # 같은 순간 팀(부스)은 예약 칸으로 들어간다
    h = post("/api/v1/questions", {**public(), "Cookie": team_cookie()})
    assert h.last[0] == 200 and h.last[1]["inflight"] == 3
    assert bridge.GATE.snapshot()["inflight"] == 2          # 끝나면 돌려준다


def test_세션_경로_판정도_칸을_탄다(sh):
    for _ in range(2):
        bridge.GATE.acquire(False, 0)
    assert post("/api/v1/sessions/s_abc/qa/judge", public()).last[0] == 503


def test_핸들러가_터져도_칸이_새지_않는다(sh, monkeypatch):
    monkeypatch.setattr(bridge, "PAID_PATHS", bridge.PAID_PATHS | {"/api/v1/boom"})
    h = post("/api/v1/boom", public())
    assert h.last[0] == 500
    assert bridge.GATE.snapshot()["inflight"] == 0


def test_칸_밖_경로는_칸을_안_쓴다(sh):
    for _ in range(4):
        bridge.GATE.acquire(True, 0)
    assert post("/api/v1/session/artifacts", public()).last[0] == 200


# ─── 4. 홍수 제한 · 감옥 · 차단 목록 ──────────────────────────────────────────


def test_분당_상한을_넘기면_429_계속_두드리면_감옥_시간이_지나면_풀린다(sh, monkeypatch):
    clock, _, _ = sh
    monkeypatch.setattr(bridge, "FLOOD", shield.FloodLimiter(limit=5, clock=clock))
    monkeypatch.setattr(bridge, "JAIL", shield.Jail(strikes=3, window_sec=60, ban_sec=600, clock=clock))
    codes = [get("/api/v1/team", public(ATTACKER)).last for _ in range(12)]
    assert [c for c, _ in codes[:5]] == [200] * 5
    assert codes[5][0] == 429 and codes[5][1]["scope"] == "flood"
    assert codes[-1][0] == 429 and codes[-1][1]["error"] == "banned"
    assert bridge.JAIL.remaining(ATTACKER) > 0
    # 다른 방문자는 멀쩡하다
    assert get("/api/v1/team", public(VISITOR)).last[0] == 200
    # 팀 쿠키는 같은 IP 여도 안 막는다
    assert get("/api/v1/team", {**public(ATTACKER), "Cookie": team_cookie()}).last[0] == 200
    clock.t += 601
    assert bridge.JAIL.remaining(ATTACKER) == 0
    clock.t += 120                                          # 홍수 창도 비워 준다
    assert get("/api/v1/team", public(ATTACKER)).last[0] == 200


def test_감옥_단위_시계(sh):
    clock = Clock()
    j = shield.Jail(strikes=2, window_sec=60, ban_sec=10, clock=clock)
    assert [j.strike("k") for _ in range(3)] == [False, False, True]
    assert j.remaining("k") == 10 and len(j) == 1
    clock.t += 10.5
    assert j.remaining("k") == 0 and len(j) == 0
    assert shield.Jail(strikes=0, clock=clock).strike("k") is False   # 0 이면 안 가둔다


def test_과금_429_도_감옥_점수로_센다(sh, monkeypatch):
    clock, _, _ = sh
    monkeypatch.setattr(bridge, "LIMITER", bridge.PaidLimiter(limit=1, ip_limit=100, clock=clock))
    monkeypatch.setattr(bridge, "JAIL", shield.Jail(strikes=2, window_sec=60, ban_sec=600, clock=clock))
    results = [post("/api/v1/questions", public(ATTACKER)).last[0] for _ in range(5)]
    assert results[0] == 200 and 429 in results[1:]
    assert bridge.JAIL.remaining(ATTACKER) > 0


def test_차단_목록은_파일을_고치면_다시_읽는다_주소대_포함(sh):
    _, _, tmp = sh
    path = tmp / "blocklist.txt"
    assert get("/api/v1/team", public(ATTACKER)).last[0] == 200        # 파일 없음 = 아무도 안 막음
    path.write_text("# 부스 전날 공격\n198.51.100.0/24   # 대역 통째로\n2001:db8:bad::/48\n잘못된 줄\n")
    assert get("/api/v1/team", public(ATTACKER)).last == (403, {"error": "forbidden"})
    assert get("/api/v1/team", public("2001:db8:bad:1::9")).last[0] == 403
    assert get("/api/v1/team", public(VISITOR)).last[0] == 200
    assert get("/api/v1/team", {**public(ATTACKER), "Cookie": team_cookie()}).last[0] == 200
    path.write_text("")
    os.utime(path, (time.time() + 5, time.time() + 5))      # 같은 초 안의 수정도 확실히 다른 mtime 으로
    assert get("/api/v1/team", public(ATTACKER)).last[0] == 200


# ─── 5. 점검 깃발 · 시간당 천장 ───────────────────────────────────────────────


def test_점검_깃발이면_공개_과금만_503_팀과_정적은_그대로(sh):
    _, calls, tmp = sh
    (tmp / "lockdown").touch()
    h = post("/api/v1/questions", public())
    assert h.last[0] == 503 and h.last[1]["error"] == "maintenance" and "점검" in h.last[1]["message"]
    assert calls == []
    assert post("/api/v1/questions", {**public(), "Cookie": team_cookie()}).last[0] == 200
    assert get("/api/v1/team", public()).last[0] == 200     # 과금 아닌 경로는 그대로
    (tmp / "lockdown").unlink()
    assert post("/api/v1/questions", public()).last[0] == 200


def test_시간당_천장을_넘으면_공개만_503(sh, monkeypatch):
    clock, _, _ = sh
    monkeypatch.setattr(bridge, "SPEND", RateLimiter(limit=2, window_sec=3600, clock=clock))
    assert [post("/api/v1/questions", public(f"203.0.113.{i}")).last[0] for i in range(2)] == [200, 200]
    h = post("/api/v1/questions", public("203.0.113.9"))
    assert h.last[0] == 503 and h.last[1]["error"] == "budget_exceeded" and "다시 시도해 주세요" in h.last[1]["message"]
    assert bridge.GATE.snapshot()["inflight"] == 0          # 칸을 얻은 뒤 거절해도 돌려준다
    assert post("/api/v1/memory", public("203.0.113.9")).last[0] == 200        # 기억은 과금이 아니다
    assert post("/api/v1/questions", {**public(), "Cookie": team_cookie()}).last[0] == 200
    clock.t += 3601
    assert post("/api/v1/questions", public("203.0.113.9")).last[0] == 200


# ─── 6. 표가 끝없이 자라지 않는다 ─────────────────────────────────────────────


def test_RateLimiter_는_오래된_키를_지운다():
    clock = Clock()
    lim = RateLimiter(limit=5, window_sec=60, clock=clock, max_keys=1000)
    for i in range(500):
        lim.allow(f"session:{i}")
    assert len(lim) == 500
    clock.t += 61
    lim.allow("session:new")
    assert len(lim) == 1
    for i in range(1500):                                   # 한 창 안에 상한을 넘으면 절반을 버린다
        lim.allow(f"burst:{i}")
    assert len(lim) <= 1001
    assert lim.count("burst:1499") == 1


def test_FloodLimiter_는_키당_숫자_셋이고_오래된_키를_지운다():
    clock = Clock()
    f = shield.FloodLimiter(limit=3, window_sec=60, clock=clock)
    assert [f.allow("a") for _ in range(4)] == [True, True, True, False]
    assert f.retry_after("a") >= 1
    clock.t += 60                                           # 다음 창 — 지난 창 무게가 남아 있다
    assert f.allow("a") is False
    clock.t += 60
    assert f.allow("a") is True
    for i in range(100):
        f.allow(f"ip{i}")
    clock.t += 200
    f.allow("z")
    assert len(f) == 1


# ─── 7. 관측 ──────────────────────────────────────────────────────────────────


def test_ops_shield_는_팀과_VM_안에서만_보인다(sh):
    assert get("/api/v1/ops/shield", public()).last == (404, {"error": "not found"})
    assert get("/api/v1/ops/shield", {"X-Forwarded-For": ATTACKER}).last[0] == 404
    code, body = get("/api/v1/ops/shield", {**public(), "Cookie": team_cookie()}).last
    assert code == 200
    for k in ("paid", "spend", "recent_5min", "bans", "blocklist", "lockdown", "edge", "connections"):
        assert k in body
    assert body["edge"]["recent"] and body["edge"]["recent"][-1]["via"] == "cf"
    assert get("/api/v1/ops/shield", {}).last[0] == 200     # VM 안 curl


def test_ops_shield_는_비밀_머리글_값을_싣지_않는다(sh, monkeypatch):
    monkeypatch.setattr(bridge, "EDGE_SECRET", "edge-secret-xyz")
    get("/api/v1/team", {**public(), "X-Edge-Auth": "edge-secret-xyz"})
    _, body = get("/api/v1/ops/shield", {**public(), "Cookie": team_cookie(), "X-Edge-Auth": "edge-secret-xyz"}).last
    assert "edge-secret-xyz" not in json.dumps(body)
    assert body["edge"]["recent"][-1]["edge_auth"] == "ok"


def test_사건_수는_5분_창으로_센다():
    clock = Clock()
    ev = shield.EventCounter(clock=clock)
    ev.add("busy_503", 3)
    clock.t += 200
    ev.add("busy_503")
    assert ev.recent(300)["busy_503"] == 4
    clock.t += 200
    assert ev.recent(300) == {"busy_503": 1}
    assert ev.totals["busy_503"] == 4


def test_같은_로그는_묵힌다(capsys):
    clock = Clock()
    log = shield.LogThrottle(every=10, clock=clock)
    assert log.write("busy", "a") and not log.write("busy", "b") and not log.write("busy", "c")
    clock.t += 11
    assert log.write("busy", "d")
    err = capsys.readouterr().err
    assert "a" in err and "그사이 같은 일 2번 더" in err


# ─── 8. 느린 연결 감시 ────────────────────────────────────────────────────────


def test_감시는_시한을_넘긴_연결을_끊고_핸들러가_요청을_처리하지_않는다(real):  # noqa: F811
    clock = Clock()
    wd = shield.Watchdog(clock=clock)
    h = FakeHandler("/api/v1/team")
    wd.watch(h, 5, "headers")
    clock.t += 4
    assert wd.sweep() == 0
    clock.t += 2
    assert wd.sweep() == 1 and h._reaped == "headers" and wd.reaped_by_phase == {"headers": 1}
    h.do_GET()
    assert h.sent == []                                     # _gate 가 반쯤 받은 요청을 버렸다


# ─── 9. 실제 소켓 — 연결 상한 · slowloris ────────────────────────────────────


@pytest.fixture
def live(real, monkeypatch):  # noqa: F811
    servers = []

    def start(**kw):
        srv = bridge.ReusableThreadingHTTPServer(("127.0.0.1", 0), bridge.Handler, **kw)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        servers.append(srv)
        return srv

    yield start
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def _recv_all(sock: socket.socket, timeout: float = 5.0) -> bytes:
    sock.settimeout(timeout)
    out = b""
    try:
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            out += chunk
    except (socket.timeout, ConnectionResetError):
        pass
    return out


def test_연결_상한을_넘으면_스레드_없이_503(live):
    srv = live(max_connections=2)
    port = srv.server_address[1]
    idle = [socket.create_connection(("127.0.0.1", port)) for _ in range(2)]
    time.sleep(0.2)
    assert srv.active_connections == 2
    s = socket.create_connection(("127.0.0.1", port))
    data = _recv_all(s)
    assert data.startswith(b"HTTP/1.1 503") and b"Retry-After" in data and "사용자가 많아요".encode() in data
    assert srv.refused_connections == 1
    for c in idle + [s]:
        c.close()
    deadline = time.time() + 3
    while srv.active_connections and time.time() < deadline:
        time.sleep(0.05)
    assert srv.active_connections == 0
    s = socket.create_connection(("127.0.0.1", port))
    s.sendall(b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
    assert _recv_all(s).startswith(b"HTTP/1.1 200")
    s.close()


def test_머리글을_늦게_보내는_연결은_끊긴다(live, monkeypatch):
    monkeypatch.setattr(bridge, "HEADER_TIMEOUT", 1.0)
    monkeypatch.setattr(bridge.WATCHDOG, "tick", 0.2)
    srv = live()
    port = srv.server_address[1]
    s = socket.create_connection(("127.0.0.1", port))
    s.sendall(b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\n")
    t0 = time.time()
    closed = False
    try:
        for _ in range(20):                                 # 한 줄씩 0.3초마다 — recv 한 번의 시한(30초)에는 안 걸린다
            time.sleep(0.3)
            s.sendall(b"X-Slow: 1\r\n")
    except OSError:
        closed = True
    if not closed:
        closed = _recv_all(s, 2.0) == b""
    assert closed and time.time() - t0 < 5
    assert bridge.WATCHDOG.reaped_by_phase.get("headers", 0) >= 1
    s.close()


def test_Cloudflare_서버_IP_칸은_홍수_제한에_안_묶인다(sh, monkeypatch):
    clock, _, _ = sh
    monkeypatch.setattr(bridge, "FLOOD", shield.FloodLimiter(limit=2, clock=clock))
    assert [get("/api/v1/team", {"X-Forwarded-For": CF_EDGE}).last[0] for _ in range(5)] == [200] * 5


def test_방패가_터지면_막지_않고_통과시킨다(sh, monkeypatch):
    class Broken:
        def blocked(self, ip):
            raise RuntimeError("bug")

    monkeypatch.setattr(bridge, "BLOCKLIST", Broken())
    assert get("/api/v1/team", public()).last[0] == 200
