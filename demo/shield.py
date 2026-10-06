"""
공개 데모 서버의 **방패** — 트래픽 급증·남용·공격 대응 (2026-10-05, AI Festa 부스 전날).

chuckchuck-present.com 은 로그인 없이 열려 있고(09-30 결정), 과금 경로(파싱·STT·LLM)를 누구나 부른다.
그 앞을 지키던 것은 Host 허용 목록 · 본문 상한 · 세션/IP 분당 상한(PaidLimiter) · /auth 코드 맞히기 제한뿐이었다.
그걸로는 아래가 안 막힌다 — 이 모듈은 그 빈칸을 메우는 부품만 모아 둔다 (배선은 demo/bridge.py).

- **IP 위조**: Funnel 도 루프백으로 들어온다. 예전 `_client_key` 는 루프백이면 CF-Connecting-IP 를 그대로 믿어서,
  ts.net 주소로 바로 와 그 헤더를 매번 바꾸면 IP 상한이 전부 풀렸다 → `resolve_client` (+ X-Edge-Auth 비밀).
- **동시 폭주**: 분당 상한은 「몇 번」 만 센다. 몇 초 안에 수백 개가 동시에 오면 스레드 수백 개가 LLM 을 동시에 부른다
  → `PaidGate` (동시 실행 칸 + 팀 몫 예약).
- **느린 연결·연결 폭주**: 머리글을 한 줄씩 늦게 보내는 연결(slowloris)이 스레드를 붙잡는다 → bridge 의 소켓 시한 + `Watchdog`.
- **반복 남용**: 막혀도 계속 두드리는 IP 는 잠깐 감옥(`Jail`), 사람이 손으로 막는 목록(`Blocklist`).
- **돈**: 시간당 천장(bridge 의 SPEND) · 점검 깃발 파일(`FlagFile`, `touch var/lockdown`).
- **기억이 끝없이 자라는 것**: 세션 id 를 바꿔 가며 두드리면 요청 제한 표가 끝없이 커졌다 → `FloodLimiter` 는 키당 숫자 셋,
  `RateLimiter`(demo/rate_limit.py) 는 오래된 키를 주기적으로 지운다.

모두 표준 라이브러리만 쓴다. 시계는 주입할 수 있다 (테스트가 만료를 기다리지 않는다).
"""

from __future__ import annotations

import hmac
import ipaddress
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path

# ─── 클라이언트 IP ────────────────────────────────────────────────────────────

#: Cloudflare 가장자리(edge) 서버의 주소대 — https://www.cloudflare.com/ips-v4 · ips-v6 (2026-10-05 받아 옴, 몇 년째 그대로다).
#: 도메인으로 온 요청은 Cloudflare → Funnel 을 거치는데, Funnel 은 자기에게 TCP 를 건 상대(= 이 주소대의 Cloudflare 서버)를
#: X-Forwarded-For 에 적는다. 그 마지막 칸이 이 주소대일 때만 CF-Connecting-IP(방문자 IP)를 믿는다. 바뀌면 DEMO_CF_RANGES 로 더한다.
CLOUDFLARE_RANGES = (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18",
    "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17",
    "162.158.0.0/15", "104.16.0.0/13", "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
    "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32", "2405:b500::/32", "2405:8100::/32",
    "2a06:98c0::/29", "2c0f:f248::/32",
)
#: 「사람」 이 아니라 우리 쪽 설비인 주소 — 루프백 · 사설망 · Tailscale(100.64/10, fd7a:115c:a1e0::/48) · 링크 로컬.
#: X-Forwarded-For 마지막 칸이 이쪽이면 방문자 IP 로 쓰지 않는다 (전원이 한 칸에 몰려 사이트 전체가 막힌다).
INFRA_RANGES = (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16",
    "::1/128", "fc00::/7", "fe80::/10", "fd7a:115c:a1e0::/48",
)
LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1", ""})
#: 이 중 하나라도 있으면 VM 안에서 곧장 온 요청이 아니다 (is_local_direct)
_PROXY_TRACES = ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded", "Via", "X-Real-IP",
                 "CF-Connecting-IP", "CF-Ray", "Tailscale-Funnel-Request", "X-Edge-Auth")


def parse_ip(raw) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """헤더·소켓 주소 → IP. `[::1]`·`::ffff:1.2.3.4`(IPv4 를 담은 IPv6)·`%eth0`(zone) 도 받는다. 아니면 None."""
    s = str(raw or "").strip().strip("[]")
    if not s or len(s) > 64:
        return None
    s = s.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(s)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


class NetSet:
    """주소대 묶음. 몇십 개라 차례로 본다 — 요청마다 마이크로초 단위다."""

    def __init__(self, cidrs=()) -> None:
        self.nets: list = []
        for c in cidrs:
            c = str(c).strip()
            if not c:
                continue
            try:
                self.nets.append(ipaddress.ip_network(c, strict=False))
            except ValueError:
                sys.stderr.write(f"[shield] 주소대 무시: {c[:60]!r}\n")

    def __contains__(self, ip) -> bool:
        if not isinstance(ip, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            ip = parse_ip(ip)
            if ip is None:
                return False
        return any(ip.version == n.version and ip in n for n in self.nets)

    def __len__(self) -> int:
        return len(self.nets)


CF_NETS = NetSet([*CLOUDFLARE_RANGES, *os.environ.get("DEMO_CF_RANGES", "").split(",")])
INFRA_NETS = NetSet(INFRA_RANGES)


def ip_bucket(key: str) -> str:
    """홍수 제한·감옥이 세는 칸. IPv6 는 /64 로 묶는다 — 집 하나가 /64 를 통째로 받아 주소를 마음대로 바꿀 수 있다."""
    ip = parse_ip(key)
    if ip is None:
        return str(key)[:64]
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def header_last(headers, name: str) -> str:
    """같은 머리글이 여러 줄이면 **마지막** 줄 — 앞줄은 요청자가 넣은 것일 수 있다 (프록시는 뒤에 붙이거나 덮어쓴다)."""
    get_all = getattr(headers, "get_all", None)
    if get_all is not None:
        vals = get_all(name) or []
        return str(vals[-1]) if vals else ""
    return str(headers.get(name) or "")


def header_single(headers, name: str) -> str:
    """한 줄이어야 하는 머리글(CF-Connecting-IP). 여러 줄이면 위조로 보고 빈 값."""
    get_all = getattr(headers, "get_all", None)
    if get_all is not None:
        vals = get_all(name) or []
        return str(vals[0]) if len(vals) == 1 else ""
    return str(headers.get(name) or "")


def last_hop(xff: str) -> str:
    """X-Forwarded-For 의 **마지막** 칸 — 바로 앞 프록시(Funnel)가 적은 것. 앞쪽 칸은 요청자가 마음대로 적을 수 있다.
    Funnel 은 이 헤더를 덮어쓰지만(append 가 아니라 set), 덧붙이는 프록시여도 마지막 칸은 그 프록시가 본 상대다."""
    parts = [p.strip() for p in (xff or "").split(",") if p.strip()]
    return parts[-1] if parts else ""


def edge_ok(headers, secret: str) -> bool:
    """X-Edge-Auth 가 비밀과 같은가 (상수 시간 비교). 비밀이 없으면 늘 거짓."""
    if not secret:
        return False
    got = (headers.get("X-Edge-Auth") or "").strip()
    return bool(got) and hmac.compare_digest(got.encode("utf-8", "replace"), secret.encode("utf-8"))


def resolve_client(peer, headers, secret: str = "") -> tuple[str, str]:
    """
    요청을 보낸 **사람의** IP 와, 그걸 어디서 알았는지(via). 요청 제한·감옥·차단 목록이 모두 이 값으로 센다.

    길은 셋이다 — ① 도메인: 방문자 → Cloudflare → Funnel → 127.0.0.1 · ② ts.net 직접: 방문자 → Funnel → 127.0.0.1 ·
    ③ 이 VM 안(실험실·curl). ①②가 다 루프백이라 소켓 주소로는 못 가른다. 그래서:

    - 루프백이 아닌 소켓(mock 모드 LAN) → 소켓 주소 그대로 (`peer`). 헤더는 위조일 수 있어 안 읽는다.
    - DEMO_EDGE_SECRET 이 있고 X-Edge-Auth 가 맞다 → Cloudflare 가 붙인 것이 확실하다 → CF-Connecting-IP (`edge`).
    - X-Forwarded-For 마지막 칸(Funnel 이 적은 TCP 상대)이 Cloudflare 주소대이고 비밀을 아직 안 정했다 → CF-Connecting-IP (`cf`).
      우리 도메인을 거쳤다면 Cloudflare 가 덮어쓴 값이다. 단 WARP(Cloudflare VPN)·Worker 로 ts.net 에 바로 와도 TCP 상대가
      Cloudflare 주소라 이 값을 위조할 수 있다 — 그래서 `cf` 로 센 칸은 감옥에 넣지 않고(bridge), 비밀을 정하면 아래처럼 안 믿는다.
      **대시보드 규칙(X-Edge-Auth)을 먼저 넣고 비밀을 정한다** (§10-6) — 반대 순서면 그 사이 도메인 방문자가 Cloudflare 서버 IP 몇 개로 묶인다.
    - 마지막 칸이 공인 IP 인데 Cloudflare 가 아니다 → ts.net 으로 바로 온 사람이다. 그 사람이 적은 CF-Connecting-IP 는
      위조다 — 마지막 칸이 그 사람이다 (`xff`). **예전 구멍(헤더를 바꿔 가며 IP 상한 피하기)이 여기서 닫힌다.**
    - X-Forwarded-For 가 없거나 마지막 칸이 우리 설비(루프백·사설·Tailscale) → 예전 그대로 CF-Connecting-IP 를 믿는다
      (`legacy` — cloudflared 터널·로컬 시험). 둘 다 없으면 소켓 주소 (`local`).
    """
    peer_ip = parse_ip(peer)
    if peer_ip is None:
        return (str(peer or "unknown")[:64] or "unknown"), "peer"
    if not peer_ip.is_loopback:
        return str(peer_ip), "peer"
    cf = parse_ip(header_single(headers, "CF-Connecting-IP"))
    hop = parse_ip(last_hop(header_last(headers, "X-Forwarded-For")))
    if secret and edge_ok(headers, secret):
        if cf is not None:
            return str(cf), "edge"
        return str(hop or peer_ip), "edge"
    if hop is not None and hop in CF_NETS:
        if cf is not None and not secret:
            return str(cf), "cf"
        # 비밀을 정했는데 안 맞는다 — 우리 도메인이 아니라 남의 Cloudflare(WARP·Worker)를 거쳐 ts.net 으로 온 것일 수 있다.
        # 그 경로는 CF-Connecting-IP 를 마음대로 적을 수 있으니 TCP 상대(Cloudflare 출구 IP)로 센다 (bridge 는 이 칸도 센다).
        return str(hop), "xff"
    if hop is not None and hop not in INFRA_NETS:
        return str(hop), "xff"
    if secret:
        # 비밀을 정해 뒀으면 비밀 없는 CF-Connecting-IP 는 이 VM 안에서 온 것이라도 믿지 않는다
        return str(hop or peer_ip), "local"
    if cf is not None:
        return str(cf), "legacy"
    return str(hop or peer_ip), "local"


def attributable(ip) -> bool:
    """이 IP 를 「한 사람」 으로 세도 되나. Cloudflare 서버·우리 설비 주소는 여러 사람이 섞인 칸이라 홍수 제한·감옥에 넣지 않는다
    (넣으면 그 칸 뒤의 방문자 전원이 같이 막힌다). 차단 목록·원본 잠금은 그대로 건다."""
    parsed = parse_ip(ip)
    return parsed is not None and parsed not in CF_NETS and parsed not in INFRA_NETS


def is_local_direct(peer, headers) -> bool:
    """
    이 VM 안에서 브리지로 **곧장** 온 요청인가 (실험실·운영 curl·warm 스크립트). 방패의 홍수 제한·감옥·점검 깃발·
    시간당 천장은 이 요청을 세지 않는다 — 팀 쿠키와 같은 대접이다.

    Funnel 은 늘 X-Forwarded-For 를 붙이고 Host 를 공개 이름으로 넘기므로 바깥 요청은 여기에 들 수 없다.
    """
    ip = parse_ip(peer)
    if ip is None or not ip.is_loopback:
        return False
    # 프록시를 거친 흔적이 하나라도 있으면 바깥이다 — Funnel(Go)은 X-Forwarded-For·Host·Proto 를 붙인다. 하나를 지우는 꼼수가
    # 있더라도 나머지가 남는다 (Go 프록시가 빈 Host 를 127.0.0.1:8799 로 채워도 이 흔적들은 남는다).
    for name in _PROXY_TRACES:
        if (headers.get(name) or "").strip():
            return False
    host = (headers.get("Host") or "").strip().lower()
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    return host in LOOPBACK_NAMES


# ─── 전체 요청 홍수 제한 ──────────────────────────────────────────────────────


class FloodLimiter:
    """
    IP(칸)당 분당 요청 수 — **모든** 요청에 건다. 정적 파일 대부분은 Cloudflare 가 받으므로 원본까지 오는 건 HTML·API 뿐이라
    상한은 넉넉하게 둔다 (부스·행사장 와이파이는 수십 명이 공인 IP 하나를 나눠 쓴다).

    RateLimiter(타임스탬프 deque)는 키당 상한만큼 float 을 쌓는다 — 600/분 × 공격 IP 수만 개면 수백 MB 다.
    여기는 「지난 창 개수 · 이번 창 개수 · 창 시작」 숫자 셋으로 미끄러지는 창을 근사한다 (Cloudflare 의 방식과 같다).
    """

    def __init__(self, *, limit: int, window_sec: float = 60.0, clock=time.monotonic, max_keys: int = 200_000) -> None:
        self.limit = limit
        self.window = float(window_sec)
        self._clock = clock
        self._lock = threading.Lock()
        self._slots: dict[str, list] = {}       # key → [창 시작, 이번 창, 지난 창]
        self.max_keys = max_keys
        self._next_prune = clock() + self.window

    def _estimate(self, slot: list, now: float) -> float:
        start, cur, prev = slot
        if now - start >= 2 * self.window:
            slot[:] = [now - (now - start) % self.window, 0, 0]
        elif now - start >= self.window:
            slot[:] = [start + self.window, 0, cur]
        start, cur, prev = slot
        return prev * max(0.0, 1.0 - (now - start) / self.window) + cur

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        now = self._clock()
        with self._lock:
            if now >= self._next_prune or len(self._slots) > self.max_keys:
                self._prune(now)
            slot = self._slots.get(key)
            if slot is None:
                slot = self._slots[key] = [now, 0, 0]
            if self._estimate(slot, now) + 1 > self.limit:
                return False
            slot[1] += 1
            return True

    def retry_after(self, key: str) -> int:
        """다시 될 때까지 대략 몇 초. 지난 창의 무게가 빠지는 속도로 어림한다 (1~창 길이)."""
        if self.limit <= 0:
            return 0
        now = self._clock()
        with self._lock:
            slot = self._slots.get(key)
            if not slot:
                return 0
            return max(1, int(self.window - (now - slot[0]) + 0.999))

    def _prune(self, now: float) -> None:
        stale = [k for k, s in self._slots.items() if now - s[0] >= 2 * self.window]
        for k in stale:
            del self._slots[k]
        if len(self._slots) > self.max_keys:
            # 그래도 넘치면(수십만 IP 가 동시에) 가장 오래 조용했던 절반을 버린다 — 버려진 칸은 0 부터 다시 센다
            keep = sorted(self._slots.items(), key=lambda kv: kv[1][0], reverse=True)[: self.max_keys // 2]
            self._slots = dict(keep)
        self._next_prune = now + self.window

    def __len__(self) -> int:
        return len(self._slots)


# ─── 감옥 (반복 위반 → 잠깐 차단) ────────────────────────────────────────────


class Jail:
    """
    막혀도(429) 계속 두드리는 칸을 잠깐 가둔다. 창(window_sec) 안에 위반(strike)이 strikes 번이면 ban_sec 동안,
    본문도 안 읽고 바로 429 다. 사람은 429 를 받으면 멈추고 기계는 안 멈춘다 — 그 차이로 가른다.

    기본 문턱(DEMO_BAN_STRIKES=300/분)은 「상한을 두 배 넘게 두드린 칸」 이다. 행사장 와이파이처럼 많은 사람이
    IP 하나를 나눠 쓰다 잠깐 상한을 넘는 정도로는 안 걸리게 높게 둔다 — 그 IP 를 가두면 행사장 전체가 10분 막힌다.
    """

    def __init__(self, *, strikes: int, window_sec: float = 60.0, ban_sec: float = 600.0,
                 clock=time.monotonic, max_keys: int = 100_000) -> None:
        self.strikes = strikes
        self.window = float(window_sec)
        self.ban_sec = float(ban_sec)
        self._clock = clock
        self._lock = threading.Lock()
        self._bans: dict[str, float] = {}           # key → 풀리는 시각
        self._hits = FloodLimiter(limit=max(1, strikes), window_sec=window_sec, clock=clock, max_keys=max_keys)
        self.max_keys = max_keys
        self.total_bans = 0

    def remaining(self, key: str) -> int:
        """갇혀 있으면 남은 초(≥1), 아니면 0."""
        if not self._bans:
            return 0
        now = self._clock()
        with self._lock:
            until = self._bans.get(key)
            if until is None:
                return 0
            if until <= now:
                del self._bans[key]
                return 0
            return max(1, int(until - now + 0.999))

    def strike(self, key: str) -> bool:
        """위반 하나를 센다. 이번에 새로 가뒀으면 True."""
        if self.strikes <= 0 or self.ban_sec <= 0:
            return False
        if self._hits.allow(key):
            return False
        self.ban(key, self.ban_sec)
        return True

    def ban(self, key: str, sec: float) -> None:
        now = self._clock()
        with self._lock:
            if len(self._bans) >= self.max_keys:
                for k in [k for k, t in self._bans.items() if t <= now]:
                    del self._bans[k]
            if len(self._bans) < self.max_keys or key in self._bans:
                self._bans[key] = now + sec
                self.total_bans += 1

    def active(self, limit: int = 50) -> list[dict]:
        now = self._clock()
        with self._lock:
            for k in [k for k, t in self._bans.items() if t <= now]:
                del self._bans[k]
            items = sorted(self._bans.items(), key=lambda kv: kv[1], reverse=True)
        return [{"key": k, "remaining_sec": int(t - now + 0.999)} for k, t in items[:limit]]

    def __len__(self) -> int:
        return len(self._bans)


# ─── 파일로 켜고 끄는 것 (재시작 없이) ────────────────────────────────────────


class Blocklist:
    """
    사람이 손으로 막는 IP·주소대 목록 (기본 var/blocklist.txt). 한 줄에 하나, `#` 뒤는 주석.
    `203.0.113.7` · `198.51.100.0/24` · `2001:db8::/48`. 파일의 수정 시각이 바뀌면 다시 읽는다 — 재시작이 필요 없다.
    파일 확인은 check_every 초에 한 번 (요청마다 stat 을 하지 않는다).
    """

    def __init__(self, path, *, check_every: float = 2.0, clock=time.monotonic) -> None:
        self.path = Path(path)
        self.check_every = check_every
        self._clock = clock
        self._lock = threading.Lock()
        self._mtime: float | None = None
        self._next_check = 0.0
        self.nets = NetSet()

    def _refresh(self) -> None:
        now = self._clock()
        if now < self._next_check:
            return
        with self._lock:
            if now < self._next_check:
                return
            self._next_check = now + self.check_every
            try:
                mtime = self.path.stat().st_mtime
            except OSError:
                mtime = None
            if mtime == self._mtime:
                return
            self._mtime = mtime
            lines: list[str] = []
            if mtime is not None:
                try:
                    text = self.path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                lines = [ln.split("#", 1)[0].strip() for ln in text.splitlines()]
            self.nets = NetSet([ln for ln in lines if ln])
            sys.stderr.write(f"[shield] 차단 목록 다시 읽음: {len(self.nets)}개 ({self.path.name})\n")

    def blocked(self, ip) -> bool:
        self._refresh()
        return len(self.nets) > 0 and ip in self.nets

    def __len__(self) -> int:
        self._refresh()
        return len(self.nets)


class FlagFile:
    """있으면 켜진 깃발 (기본 var/lockdown). `touch` 로 켜고 `rm` 으로 끈다. 확인은 check_every 초에 한 번."""

    def __init__(self, path, *, check_every: float = 1.0, clock=time.monotonic) -> None:
        self.path = Path(path)
        self.check_every = check_every
        self._clock = clock
        self._next_check = 0.0
        self._on = False

    def on(self) -> bool:
        now = self._clock()
        if now >= self._next_check:
            self._on = self.path.exists()
            self._next_check = now + self.check_every
        return self._on


# ─── 과금 경로 동시 실행 칸 ───────────────────────────────────────────────────


class PaidGate:
    """
    과금 경로(LLM·STT·파싱)를 **동시에** 몇 개까지 돌릴지. 칸이 다 차면 queue_sec 만큼 기다렸다가, 그래도 안 나면 거절(503 busy).

    분당 상한은 「한 사람이 몇 번」 이고, 이건 「서버 전체가 한꺼번에 몇 개」 다. 수백 명이 동시에 누르면 스레드 수백 개가
    외부 API 를 동시에 부르고, 공급자 쪽 429·시간 초과로 **모두가** 실패한다 — 일부를 빨리 돌려보내는 편이 낫다.

    팀(쿠키) 요청은 capacity 칸을 다 쓸 수 있고, 공개 요청은 capacity - reserved 칸까지만 쓴다. 그래서 공개 방문자가
    아무리 몰려도 부스 노트북 몫 reserved 칸은 늘 남는다. capacity <= 0 이면 끈다 (세기만 한다).
    """

    def __init__(self, *, capacity: int, reserved: int = 0) -> None:
        self.capacity = capacity
        self.reserved = max(0, min(reserved, capacity - 1)) if capacity > 0 else 0
        self._cond = threading.Condition()
        self._inflight = 0
        self._inflight_team = 0
        self._waiting = 0
        self.peak = 0

    def limit_for(self, team: bool) -> int:
        return self.capacity if team else self.capacity - self.reserved

    def acquire(self, team: bool, timeout: float) -> tuple[bool, float]:
        """칸을 얻으면 (True, 기다린 초). 못 얻으면 (False, 기다린 초). 얻었으면 **반드시** release(team) 를 부른다 (finally)."""
        t0 = time.monotonic()
        with self._cond:
            if self.capacity > 0:
                limit = self.limit_for(team)
                deadline = t0 + max(0.0, timeout)
                while self._inflight >= limit:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        return False, time.monotonic() - t0
                    self._waiting += 1
                    try:
                        self._cond.wait(left)
                    finally:
                        self._waiting -= 1
            self._inflight += 1
            if team:
                self._inflight_team += 1
            self.peak = max(self.peak, self._inflight)
            return True, time.monotonic() - t0

    def release(self, team: bool) -> None:
        with self._cond:
            self._inflight = max(0, self._inflight - 1)
            if team:
                self._inflight_team = max(0, self._inflight_team - 1)
            self._cond.notify_all()

    def snapshot(self) -> dict:
        with self._cond:
            return {"inflight": self._inflight, "inflight_team": self._inflight_team, "waiting": self._waiting,
                    "capacity": self.capacity, "reserved_team": self.reserved,
                    "public_limit": self.limit_for(False) if self.capacity > 0 else 0, "peak": self.peak}


# ─── 느린 연결 감시 ───────────────────────────────────────────────────────────


class Watchdog:
    """
    연결마다 「이때까지 끝내야 한다」 를 걸어 두고, 넘기면 소켓을 끊는다 (1초마다 훑는다).

    소켓 시한(settimeout)은 recv **한 번**의 시한이라, 머리글을 10초에 한 줄씩 보내는 연결(slowloris)은 영원히 안 끊긴다.
    그래서 단계마다 **전체** 시한을 따로 건다 — 요청 줄 대기(keep-alive) · 머리글 · 본문. 처리 중(LLM 대기)에는 걸지 않는다.
    끊을 때는 핸들러에 표시(`_reaped`)를 남긴다 — 반쯤 받은 머리글로 요청이 처리되지 않게 (bridge `_gate` 가 본다).
    """

    def __init__(self, *, tick: float = 1.0, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._items: dict[int, tuple[object, float, str, object]] = {}
        self.tick = tick
        self.reaped = 0
        self.reaped_by_phase: dict[str, int] = {}
        self._thread: threading.Thread | None = None

    def watch(self, handler, seconds: float, phase: str) -> None:
        if seconds <= 0:
            return self.unwatch(handler)
        with self._lock:
            # 요청 번호(_req_gen)를 같이 적는다 — 끊으러 갔을 때 그 연결이 이미 다음 요청으로 넘어갔으면 건드리지 않는다
            self._items[id(handler)] = (handler, self._clock() + seconds, phase, getattr(handler, "_req_gen", None))

    def unwatch(self, handler) -> None:
        with self._lock:
            self._items.pop(id(handler), None)

    def sweep(self) -> int:
        now = self._clock()
        with self._lock:
            due = [(k, h, ph, gen) for k, (h, t, ph, gen) in self._items.items() if t <= now]
            for k, _, _, _ in due:
                del self._items[k]
        for _, h, ph, gen in due:
            if getattr(h, "_req_gen", None) != gen:
                continue
            try:
                h._reaped = ph
                h.close_connection = True
                conn = getattr(h, "connection", None)
                if conn is not None:
                    import socket

                    conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.reaped += 1
            self.reaped_by_phase[ph] = self.reaped_by_phase.get(ph, 0) + 1
        return len(due)

    def start(self) -> None:
        if self._thread is not None:
            return

        def loop() -> None:
            while True:
                time.sleep(self.tick)
                try:
                    self.sweep()
                except Exception as e:  # noqa: BLE001 — 감시가 죽으면 서버는 돌지만 느린 연결을 못 끊는다. 알리고 계속
                    sys.stderr.write(f"[shield] 감시 오류: {e!r}\n")

        self._thread = threading.Thread(target=loop, name="shield-watchdog", daemon=True)
        self._thread.start()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


# ─── 관측 ─────────────────────────────────────────────────────────────────────


class EventCounter:
    """종류별 사건 수를 10초 칸으로 센다 — 「최근 5분에 429 몇 번」. 칸 수가 고정이라 홍수에도 기억이 늘지 않는다."""

    def __init__(self, *, bucket_sec: float = 10.0, keep_sec: float = 300.0, clock=time.monotonic) -> None:
        self.bucket = bucket_sec
        self.n = int(keep_sec // bucket_sec) + 1
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: deque = deque()          # (칸 번호, {종류: 수})
        self.totals: dict[str, int] = {}

    def add(self, kind: str, n: int = 1) -> None:
        idx = int(self._clock() // self.bucket)
        with self._lock:
            if not self._buckets or self._buckets[-1][0] != idx:
                self._buckets.append((idx, {}))
                while len(self._buckets) > self.n or (self._buckets and self._buckets[0][0] <= idx - self.n):
                    self._buckets.popleft()
            b = self._buckets[-1][1]
            b[kind] = b.get(kind, 0) + n
            self.totals[kind] = self.totals.get(kind, 0) + n

    def recent(self, window_sec: float = 300.0) -> dict[str, int]:
        idx = int(self._clock() // self.bucket)
        lo = idx - int(window_sec // self.bucket)
        out: dict[str, int] = {}
        with self._lock:
            for i, b in self._buckets:
                if i > lo:
                    for k, v in b.items():
                        out[k] = out.get(k, 0) + v
        return out


class LogThrottle:
    """같은 종류의 로그는 every 초에 한 줄만 — 공격 중에 로그가 디스크·journald 를 채우지 않게. 묵힌 줄 수를 같이 찍는다."""

    def __init__(self, *, every: float = 10.0, clock=time.monotonic) -> None:
        self.every = every
        self._clock = clock
        self._lock = threading.Lock()
        self._last: dict[str, float] = {}
        self._muted: dict[str, int] = {}

    def write(self, kind: str, line: str) -> bool:
        now = self._clock()
        with self._lock:
            last = self._last.get(kind)
            if last is not None and now - last < self.every:
                self._muted[kind] = self._muted.get(kind, 0) + 1
                return False
            muted = self._muted.pop(kind, 0)
            self._last[kind] = now
            if len(self._last) > 1000:          # 종류에 IP 를 넣는 쪽이 있어도 무한히 안 자라게
                self._last = {kind: now}
        sys.stderr.write(f"[shield] {line}" + (f" (그사이 같은 일 {muted}번 더)" if muted else "") + "\n")
        return True


def env_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, "").strip() or default))
    except ValueError:
        sys.stderr.write(f"[shield] {name} 값이 숫자가 아니라 기본값 {default} 을 쓴다\n")
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        sys.stderr.write(f"[shield] {name} 값이 숫자가 아니라 기본값 {default} 을 쓴다\n")
        return default


# ─── 봇 (2026-10-06) ───────────────────────────────────────────────────────────
# 사용자 「외부 트래픽도 허용은 시켜줘, 봇들만 막고」. 나라로 막지 않는다 — 브라우저가 아닌 수집기 · 스크립트 · 취약점 탐색기를 입구에서 끊는다.
# 링크 미리보기(카카오톡 · 슬랙 · 페이스북 …)는 공유한 링크의 카드를 그리는 것이라 화면 주소(GET, /api 밖)만 열어 둔다.
# 헤드리스 크롬은 막지 않는다 — 우리 실험실(labs/*)이 공개 도메인을 그 이름으로 연다. VM 안 요청 · 팀 쿠키는 여기까지 오지 않는다.
import re as _re

BOT_UA_RE = _re.compile(
    r"bot\b|bot/|crawl|spider|slurp|scrapy|python-requests|python-urllib|aiohttp|httpx|go-http-client|"
    r"\bcurl/|\bwget/|libwww|java/|okhttp|apache-httpclient|node-fetch|axios/|phantomjs|"
    r"gptbot|claudebot|anthropic-ai|ccbot|bytespider|petalbot|ahrefs|semrush|mj12|dotbot|dataforseo|"
    r"masscan|zgrab|nmap|nikto|sqlmap|nuclei|censys|expanse",
    _re.IGNORECASE,
)
PREVIEW_UA_RE = _re.compile(
    r"kakaotalk-scrap|facebookexternalhit|slackbot|twitterbot|discordbot|telegrambot|linkedinbot|whatsapp|line/",
    _re.IGNORECASE,
)


def bot_verdict(user_agent: str | None, path: str, method: str) -> str:
    """'' 이면 통과, 'bot' 이면 막는다. 머리글이 없거나 빈 UA 도 봇이다 (브라우저는 늘 보낸다). robots.txt 는 누구에게나 연다."""
    if path == "/robots.txt":
        return ""
    ua = (user_agent or "").strip()
    if not ua:
        return "bot"
    if PREVIEW_UA_RE.search(ua):
        return "" if method in ("GET", "HEAD") and not path.startswith("/api/") else "bot"
    return "bot" if BOT_UA_RE.search(ua) else ""
