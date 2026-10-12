"""
부스 퍼널 신호 — `POST /api/v1/tour/event` 의 검사·제한·로그 한 줄 (2026-10-11, 결선 부스 QR).

왜 — 10/7 QR 실측은 과금 API 로만 단계를 어림했다(덱 선택 = cached-slidedoc …). 투어(#/tour/*)는 녹화 응답만 재생해서
API 를 하나도 안 부르고, 화면 파일은 Cloudflare 캐시라 원본 로그에 안 찍힌다 → 단계가 보이지 않는다.
그래서 화면이 단계마다 작은 신호 하나를 보내고, 브리지는 **저장하지 않고** 접근 로그와 같은 모양의 한 줄만 남긴다.
집계는 `etc/scripts/booth_funnel.py` 가 journalctl 출력에서 한다. 계약: docs/booth-mobile/funnel-events.md.

막는 것 (공개 · 로그인 없음 · 팀 쿠키 불필요)
- 본문: 512바이트 이하 JSON 객체, 열쇠는 step · deck · t 만. step 은 허용 목록, deck 은 투어 id 모양, t 는 0~86400 초.
  값이 모두 허용 목록·정규식을 통과해야 로그에 쓴다 → 줄바꿈·따옴표로 로그 줄을 꾸미는 길(log injection)이 없다.
- 속도: IP(칸)당 분당 TOUR_EVENT_RPM · 서버 전체 분당 두 칸. 넘으면 429 를 주되 로그는 10초에 한 줄.
  전체 칸은 둘로 나눈다(10-12 점검 perf-security-copy-r1-1): (IP 칸, 단계) 의 **첫 신호**는 TOUR_EVENT_FIRST_RPM 칸,
  같은 쌍의 **반복**은 TOUR_EVENT_GLOBAL_RPM 칸. 한 칸이었을 때는 IP 11개가 같은 단계를 560번씩 되풀이해 전체 상한을
  1분 내내 채우면 진짜 방문객 신호가 모두 429 로 버려졌다(퍼널 측정이 통째로 빈다). 첫 신호 칸이 차면 반복 칸으로 넘어간다.
  CF-Connecting-IP 를 바꿔 가며 첫 신호만 쏟는 길(DEMO_EDGE_SECRET 꺼짐)은 두 칸의 합에서 멈춘다 — 결선 전에 EDGE_SECRET 을 켠다.
  IP 는 bridge `_client_key`(= shield.resolve_client) 로 센다 — CF-Connecting-IP 를 바꿔 보내도 칸이 안 갈린다(10/5 구멍).
  사람으로 셀 수 없는 칸(Cloudflare 서버·설비 IP)은 IP 칸 대신 전체 칸만 센다 — 섞인 칸을 막으면 그 뒤 방문자가 다 막힌다.
- 감옥(Jail)에는 넣지 않는다 — 행사장 와이파이 하나 뒤의 폰 수십 대가 같은 IP 다. 홍수는 방패 첫 줄(FLOOD)이 이미 센다.

표준 라이브러리 + server.rate_limit 만 쓴다. 시계는 주입할 수 있다(테스트).
"""

from __future__ import annotations

import json
import math
import os
import re
import time

from server.rate_limit import RateLimiter

PATH = "/api/v1/tour/event"
#: 본문 상한. {"step":"tour_analysis","deck":"microplastic-daphnia","t":86400} 가 70바이트 남짓이다.
BODY_MAX = 512

#: 퍼널 단계 — 화면 차례대로. 이름을 바꾸면 etc/scripts/booth_funnel.py · docs/booth-mobile/funnel-events.md 를 같이 바꾼다.
STEPS: tuple[str, ...] = (
    "hi",             # /hi 랜딩이 그려졌다 (서버는 GET /hi 302 로도 센다 — 둘 중 하나만 와도 1명)
    "intro",          # 척척발표 소개 카드를 봤다
    "team",           # 팀원 카드 첫 장을 봤다
    "team_end",       # 팀원 카드 마지막 장까지 넘겼다
    "explore",        # 「척척발표 살펴보기」 를 눌렀다
    "tour_deck",      # #/tour/deck
    "tour_present",   # #/tour/present
    "tour_analysis",  # #/tour/analysis
    "tour_qa",        # #/tour/qa
    "tour_report",    # #/tour/report
    "try_real",       # 「내 자료로 직접 해 보기」 를 눌렀다 (→ #/rehearsal)
    "inapp_notice",   # 인앱 브라우저라 「Safari/Chrome 으로 열기」 안내를 띄웠다
    "back_team",      # 「팀 소개로 돌아가기」 를 눌렀다
)
STEP_SET = frozenset(STEPS)
#: 투어 녹화 id 모양 — main/server/schema/booth-mobile/tour.schema.json 의 id(파일 이름)와 같은 글자. `_example` 같은 예시도 받는다.
DECK_RE = re.compile(r"^_?[a-z0-9][a-z0-9-]{0,39}$")
T_MAX = 86400.0
_KEYS = frozenset({"step", "deck", "t"})


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


#: IP(칸)당 분당 신호 수. 한 사람의 투어 한 바퀴가 신호 11~13개 — 행사장 와이파이(NAT) 하나 뒤에서 폰 50대가 같은 1분에 돌아도
#: (etc/labs/booth_load --same-ip: 550개) 안 걸린다. 한 IP 가 꽉 채워도 로그는 초당 10줄이다.
TOUR_EVENT_RPM = _env_int("DEMO_TOUR_EVENT_RPM", 600)
#: 서버 전체 분당 **반복** 신호 수 — 같은 (IP 칸, 단계) 를 되풀이한 신호. 행사장 NAT 하나 뒤 폰 50대가 같은 1분에 돌아도 540개 남짓.
TOUR_EVENT_GLOBAL_RPM = _env_int("DEMO_TOUR_EVENT_GLOBAL_RPM", 3000)
#: 서버 전체 분당 **첫** 신호 수 — (IP 칸, 단계) 마다 창 안 첫 번째. 한 사람 한 바퀴가 11~13개라 분당 새 방문자 230명분.
#: 두 칸의 합(6000)이 로그 줄 상한이다 — 봇넷이 IP 를 바꿔 가며 보내도 분당 이 줄 수를 못 넘는다. 부스 최고(10/7 10분에 13명)의 수백 배.
TOUR_EVENT_FIRST_RPM = _env_int("DEMO_TOUR_EVENT_FIRST_RPM", 3000)


class TourEventError(ValueError):
    """본문이 계약에 맞지 않는다 — 400 으로 돌려보낸다. code 는 기계용 이름."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def parse_event(raw: bytes) -> dict:
    """본문 → {step, deck|None, t|None}. 틀리면 TourEventError. 돌려준 값은 그대로 로그에 써도 안전하다."""
    if not raw or len(raw) > BODY_MAX:
        raise TourEventError("bad_body")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise TourEventError("bad_json") from None
    if not isinstance(body, dict) or not body or not set(body) <= _KEYS:
        raise TourEventError("bad_keys")
    step = body.get("step")
    if not isinstance(step, str) or step not in STEP_SET:
        raise TourEventError("bad_step")
    deck = body.get("deck")
    if deck is not None and (not isinstance(deck, str) or not DECK_RE.match(deck)):
        raise TourEventError("bad_deck")
    t = body.get("t")
    if t is not None:
        # bool 은 int 의 하위형이라 True 가 1 로 통과한다 — 막는다
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or not 0 <= t <= T_MAX:
            raise TourEventError("bad_t")
        t = int(t)
    return {"step": step, "deck": deck, "t": t}


def log_fields(ev: dict) -> str:
    """로그 한 줄의 몸통 — `tour step=tour_qa deck=battery-fastcharge t=42`. 빈 값은 `-` (접근 로그처럼)."""
    deck = ev.get("deck") or "-"
    t = ev.get("t")
    return f"tour step={ev['step']} deck={deck} t={'-' if t is None else t}"


class TourEventLimiter:
    """IP(칸)당 · 전체 분당 상한. 전체는 첫 신호 칸과 반복 칸 둘. 모두 server.rate_limit.RateLimiter(오래된 키를 지운다)."""

    def __init__(self, *, per_ip: int = TOUR_EVENT_RPM, global_limit: int = TOUR_EVENT_GLOBAL_RPM,
                 first_limit: int = TOUR_EVENT_FIRST_RPM, window_sec: float = 60.0, clock=time.monotonic) -> None:
        self.per_ip = RateLimiter(limit=per_ip, window_sec=window_sec, clock=clock, max_keys=50_000)
        self.total = RateLimiter(limit=global_limit, window_sec=window_sec, clock=clock, max_keys=4)
        self.first_total = RateLimiter(limit=first_limit, window_sec=window_sec, clock=clock, max_keys=4)
        #: (IP 칸, 단계) 를 이 창에서 봤는가 — limit=1 이라 처음 한 번만 allow 가 참이다. 키 상한은 IP 칸 × 단계 13개
        self.seen = RateLimiter(limit=1, window_sec=window_sec, clock=clock, max_keys=50_000 * 4)

    def allow(self, bucket: str | None, step: str | None = None) -> tuple[bool, str, int]:
        """(통과?, 막힌 층 'ip'|'global'|'', 다시 시도까지 초).

        bucket=None 이면 IP 층을 건너뛰고(섞인 칸) 반복 칸만 센다. step 이 없으면(본문이 틀림) 반복으로 센다.
        """
        if bucket is not None and not self.per_ip.allow(bucket):
            return False, "ip", self.per_ip.retry_after(bucket)
        if bucket is not None and step and self.seen.allow(f"{bucket}\x00{step}"):
            if self.first_total.allow("all"):
                return True, "", 0
        if not self.total.allow("all"):
            if bucket is not None:
                self.per_ip.refund(bucket)
            return False, "global", self.total.retry_after("all")
        return True, "", 0


LIMITER = TourEventLimiter()
