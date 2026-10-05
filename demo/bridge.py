"""
로컬 데모용 얇은 서버입니다.
YEHS_demo 화면과 chuckchuck 모듈을 HTTP API(/api/v1/*)와 SDK(/sdk/*)로 연결합니다.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tempfile
import traceback
import unicodedata
import zipfile
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "demo" / "YEHS_demo"
SDK_DIR = ROOT / "chuckchuck" / "sdk"

sys.path.insert(0, str(ROOT))

from chuckchuck.config import settings  # noqa: E402

from chuckchuck import (  # noqa: E402
    Context,
    analyze_pace,
    build_graph,
    compose_report,
    extract_concepts,
    extract_habits,
    merge_slidedocs,
    parse_document,
    transcribe,
)
from chuckchuck.contracts import ConceptDoc, ConceptGraph, HabitDoc, PaceDoc, SlideDoc, SlideMark, Transcript  # noqa: E402
from chuckchuck.providers.stt_impl import media_tool  # noqa: E402

from demo.learning_jobs import refresh_learning_assets  # noqa: E402
from demo.rate_limit import RateLimiter  # noqa: E402
from demo import shield  # noqa: E402
from demo.session_archive import SessionArchive, git_sha  # noqa: E402
from demo.session_store import ARTIFACT_KEYS, SessionStore, fingerprint  # noqa: E402
from demo import clova_transcript  # noqa: E402
from demo.static_assets import IMMUTABLE, REVALIDATE, COMPRESSIBLE, MIN_GZIP_BYTES, AssetCache, Minifier, accepts_gzip, content_digest, etag_matches  # noqa: E402


#: 세션 아티팩트 + triage 캐시. 프로세스 메모리라 재시작하면 사라진다 —
#: 클라이언트는 session_missing 을 받으면 다시 등록하고 재시도한다.
STORE = SessionStore()


def _env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() not in ("", "0", "false", "off", "no")


#: 업로드·파싱본·받아쓰기·분석 산출물이 남는 자리. git 이 무시하는 var/ 아래가 기본이고,
#: systemd 유닛에서 DEMO_DATA_DIR 로 바꿀 수 있다. 예전의 fixtures/raw 는 더 쓰지 않는다 —
#: 파일명으로 덮어쓰고, 언제 올렸는지 모르고, 실제 발표 자료가 git 에 커밋됐다.
DATA_DIR = Path(os.environ.get("DEMO_DATA_DIR", "").strip() or (ROOT / "var" / "data"))
ARCHIVE = SessionArchive(
    DATA_DIR,
    cache_ttl_sec=float(os.environ.get("DEMO_CACHE_TTL_HOURS", "24") or 24) * 3600,
    stage_ttl_sec=float(os.environ.get("DEMO_STAGE_CACHE_TTL_HOURS", "72") or 72) * 3600,
    retention_sec=float(os.environ.get("DEMO_RETENTION_DAYS", "365") or 365) * 86400,
    code_version=git_sha(ROOT),
)

#: 저장된 세션 **목록**을 주는 경로(/api/v1/cached-takes, #/replay). 개발자 화면이라
#: 기본은 닫는다 — 열려 있으면 주소를 아는 누구나 남의 발표 기록을 본다.
DEV_ROUTES = _env_flag("DEMO_DEV_ROUTES")
#: #/test/qa 가 훑는 발표자료 폴더 (저장소 ppt/). 폴더 하나 = 덱 하나. 개발용 — DEV_ROUTES 뒤에만 연다.
DECKS_DIR = ROOT / "ppt"
DECK_EXTS = (".pptx", ".pdf")
DECK_AUDIO_EXTS = (".m4a", ".mp3", ".wav", ".webm", ".ogg", ".aac", ".flac", ".mp4")

#: 만료 세션을 훑는 주기. 시작할 때 한 번, 그 뒤 하루에 한 번. 같은 스레드가 학습 자산도 갱신한다.
PRUNE_INTERVAL_SEC = 24 * 3600
#: 동의 세션에서 자동으로 만드는 학습 자산. `exports/`(손으로 만든 평가 묶음)와 섞이지 않게 데이터 폴더 아래.
DERIVED_DIR = DATA_DIR / "derived"

#: 과금 호출(파싱·STT·LLM)이 붙은 엔드포인트의 IP당 분당 상한.
#: 0 이하면 제한을 끈다 (오프라인 시연·자동화).
PAID_RATE_LIMIT = int(os.environ.get("DEMO_RATE_LIMIT_PER_MIN", "30"))
#: 같은 IP 전체의 분당 천장 — 남용 방지용. 세션 상한(PAID_RATE_LIMIT)보다 넉넉하다 (아래 PaidLimiter).
PAID_RATE_LIMIT_IP = int(os.environ.get("DEMO_RATE_LIMIT_IP_PER_MIN", str(6 * PAID_RATE_LIMIT)))


class PaidLimiter:
    """
    과금 경로 요청 제한 — **세션마다** PAID_RATE_LIMIT, **IP 전체**로는 PAID_RATE_LIMIT_IP (09-30 H-15).

    예전엔 IP 하나에 분당 30회였다. held-out UI 감사에서 한 IP 의 세션 다섯이 동시에 판정하자 97회 중 67회가 429 였고,
    부스는 여러 기기가 공유기 하나(NAT) 뒤에 있어 실전에서 그대로 난다. 그래서 세는 칸을 세션으로 바꾸고, IP 는 넉넉한
    천장만 둔다. 세션 id 가 없는 요청(자료 업로드·답변 받아쓰기)은 IP 칸(세션 상한)으로 센다.
    열쇠가 "ip:" 로 시작하면 천장, 나머지는 세션 칸 — `allow(key)` 하나로 두 층을 다 센다 (테스트가 allow 를 바꿔 끈다).
    """

    def __init__(self, *, limit: int, ip_limit: int, window_sec: float = 60.0, clock=time.monotonic) -> None:
        self.session = RateLimiter(limit=limit, window_sec=window_sec, clock=clock)
        self.ip = RateLimiter(limit=ip_limit, window_sec=window_sec, clock=clock)

    def _tier(self, key: str) -> RateLimiter:
        return self.ip if str(key).startswith("ip:") else self.session

    def allow(self, key: str) -> bool:
        return self._tier(key).allow(key)

    def retry_after(self, key: str) -> int:
        return self._tier(key).retry_after(key)


LIMITER = PaidLimiter(limit=PAID_RATE_LIMIT, ip_limit=PAID_RATE_LIMIT_IP, window_sec=60.0)

#: 제한을 거는 경로. 전부 외부 API 를 부르거나 GPU 를 태운다.
PAID_PATHS = frozenset({
    "/api/v1/parse",
    "/api/v1/concepts",
    "/api/v1/transcribe",
    "/api/v1/graph",
    "/api/v1/alignment",
    "/api/v1/chatter",
    "/api/v1/habits",
    "/api/v1/report",
    "/api/v1/questions",
    # F-14 는 묶음마다 LLM 을 부른다 (최대 4콜) — 레이트 리밋 대상이다
    "/api/v1/rubric",
    # F-09 판정·F-20 전략도 턴마다 LLM 을 부른다 — 무제한이면 rubric 만 막는
    # 비대칭이 된다. 사람이 분당 30턴을 못 넘으므로 정상 사용엔 안 걸린다.
    # (세션 경로 /api/v1/sessions/{id}/qa/judge 는 아래 endswith 검사가 잡는다)
    "/api/v1/qa/judge",
    "/api/v1/strategy",
    # F-24 는 학술 검색 API(+검색어 번역 LLM 1콜)를 부른다
    "/api/v1/papers",
    "/api/v1/papers/search",
    # F-26 주장 그래프도 LLM 1콜이다 (세션에 한 번 — 캐시가 받지만 입력을 바꿔 가며 두드리면 매번 부른다)
    "/api/v1/claims",
    # F-25 기억은 과금이 없지만 요청마다 보관소의 manifest 를 전부 훑는다 (related_sessions) — 무제한이면
    # 새로고침 루프 하나가 디스크를 긁는다 (09-30 B-18). 사람이 분당 30번 부를 일은 없다.
    "/api/v1/memory",
})

#: CORS 허용 origin. 기본은 브리지 자신(같은 출처)이라 헤더가 필요 없고,
#: 다른 포트에서 UI 를 띄울 때만 DEMO_ALLOWED_ORIGINS 로 열어 준다 (쉼표 구분).
ALLOWED_ORIGINS = frozenset(
    o.strip().rstrip("/")
    for o in os.environ.get("DEMO_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
)


MAX_UPLOAD_BYTES = 30 * 1024 * 1024  # UI 안내와 동일 (원본 파일 기준)
# JSON 본문은 오디오를 base64 로 실어 4/3 로 부푼다. 원본 30MB 를 그대로 받으려면
# 본문 한도도 그만큼 키워야 한다 — 안 그러면 정상 크기 녹음이 413 으로 막힌다.
MAX_BODY_BYTES = MAX_UPLOAD_BYTES * 4 // 3 + 2 * 1024 * 1024

# ─── 과금 폭주 상한 (보안 점검 2026-09-23) ──────────────────────────────────────
# 요청 제한은 **횟수**만 센다. 본문 크기를 안 보면 분당 30회 안에서도 42MB 짜리 텍스트가
# LLM 프롬프트에 실린다. 큰 본문이 정당한 곳은 녹음(base64)·자료 업로드 둘뿐이다.
#: 나머지 JSON 경로의 기본 상한. 실측 최대 slide_doc 이 450KB 다.
JSON_BODY_MAX = int(float(os.environ.get("DEMO_JSON_MAX_MB", "2") or 2) * 1024 * 1024)
#: 파이프라인 산출물을 묶어 보내는 경로 — slide_doc·transcript·graph·alignment 를 한꺼번에 싣는다.
JSON_BODY_MAX_BUNDLE = 3 * JSON_BODY_MAX
BUNDLE_PATHS = frozenset({
    "/api/v1/concepts", "/api/v1/graph", "/api/v1/alignment", "/api/v1/rubric",
    "/api/v1/questions", "/api/v1/session/artifacts", "/api/v1/chatter", "/api/v1/flow",
    "/api/v1/report", "/api/v1/strategy",
})
#: 본문 상한을 MAX_BODY_BYTES 로 두는 경로 (녹음 base64 · multipart 업로드).
BIG_BODY_PATHS = frozenset({"/api/v1/transcribe", "/api/v1/parse"})
#: F-09 판정 입력의 길이 상한. 사람이 한 질문에 말하는 양을 넉넉히 넘는다.
ANSWER_MAX_CHARS = 4000
HISTORY_MAX_ITEMS = 40
HISTORY_MAX_CHARS = 40000
PRIOR_ANSWERS_MAX = 10


def _body_limit(path: str) -> int:
    if path in BIG_BODY_PATHS:
        return MAX_BODY_BYTES
    if path in BUNDLE_PATHS or path.endswith("/qa/judge"):
        return JSON_BODY_MAX_BUNDLE
    return JSON_BODY_MAX


# ─── 앞단 확인 (Access · Host) ─────────────────────────────────────────────────
#: 1 이면 Cloudflare Access 가 붙이는 `Cf-Access-Jwt-Assertion` 헤더가 없는 요청을 전부 403 으로 막는다
#: (정적 파일 포함). 터널 앞단 설정 하나가 빠져도 브리지가 무방비로 열리지 않게 하는 두 번째 자물쇠다.
#: 서명 검증은 하지 않는다 — 브리지는 루프백에만 묶이고(아래 main), 그 앞은 cloudflared 뿐이다.
REQUIRE_ACCESS = _env_flag("DEMO_REQUIRE_ACCESS")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
#: Host 헤더 허용 목록 (DNS rebinding 방지). 포트는 보지 않는다 — 공격자 도메인이 127.0.0.1 로
#: 풀려도 Host 에는 그 도메인이 실린다. 터널 호스트명·추가 호스트는 환경변수로 연다.
ALLOWED_HOSTS = frozenset(
    h.strip().lower()
    for h in [*LOOPBACK_HOSTS, os.environ.get("TUNNEL_HOSTNAME", ""),
              *os.environ.get("DEMO_ALLOWED_HOSTS", "").split(",")]
    if h.strip()
)


#: 팀 인증 (/auth). 공개 사이트는 누구나 쓰고, 개발용 경로(세션 목록·ppt/ 덱·벤치 모델 선택)만
#: /auth 에서 이 코드를 넣은 브라우저에 연다. 비어 있으면 /auth 도 닫힌다 (DEV_ROUTES 만 남는다).
#: 값은 .env 에 둔다 — 저장소에 적지 않는다.
TEAM_CODE = os.environ.get("DEMO_TEAM_CODE", "").strip()
TEAM_COOKIE = "cc_team"
TEAM_COOKIE_MAX_AGE = 7 * 24 * 3600
#: 코드 맞히기를 막는다 — IP당 분당 5번. 과금 제한(LIMITER)과 통을 나누지 않는다.
AUTH_LIMITER = RateLimiter(limit=5, window_sec=60.0)
#: 요청 하나 = 스레드 하나(ThreadingHTTPServer)라, 핸들러 밖의 함수(_dev_choice)도 이 요청이 팀인지 안다.
_REQ = threading.local()


def _team_token() -> str:
    """쿠키에 싣는 값. 코드 자체는 싣지 않는다 — 코드를 바꾸면 이전 쿠키가 모두 풀린다."""
    return _team_token_for(TEAM_CODE)


@functools.lru_cache(maxsize=4)
def _team_token_for(code: str) -> str:
    # 방패(2026-10-05)가 **모든 요청**에서 팀인지 본다 — 요청마다 HMAC 을 새로 계산하지 않게 코드별로 한 번만
    return hmac.new(code.encode("utf-8"), b"chuckchuck-team-v1", hashlib.sha256).hexdigest()


# ─── 방패 — 트래픽 급증·공격 대응 (2026-10-05, AI Festa 부스 전날) ─────────────────────
# 부품은 demo/shield.py, 운영 절차는 docs/DEPLOYMENT.md §10-6. 모든 값은 환경변수로 바꾼다 (systemd drop-in shield.conf).
# 원칙: **팀 쿠키 요청과 이 VM 안에서 곧장 온 요청은 막지 않는다** — 부스 노트북이 공개 방문자에게 밀려나면 안 된다.

#: Cloudflare 가 붙이는 비밀 머리글(X-Edge-Auth)의 값. 대시보드 Transform Rule 로 넣는다 — 값은 .env 에만 둔다.
#: 있으면 이 머리글이 맞는 요청만 CF-Connecting-IP 를 믿는다 (shield.resolve_client).
EDGE_SECRET = os.environ.get("DEMO_EDGE_SECRET", "").strip()
#: 1 이면 비밀 머리글 없는 공개 요청(= ts.net 주소로 바로 온 요청)을 403 으로 막는다. 팀 쿠키와 /auth 는 연다 —
#: 도메인이 죽었을 때 부스 노트북이 ts.net 으로 /auth 를 거쳐 들어올 길이다. 비밀이 없으면 켜지지 않는다 (전부 막힌다).
EDGE_LOCK = _env_flag("DEMO_EDGE_LOCK") and bool(EDGE_SECRET)
#: 원본 잠금에서도 여는 경로 — 쿠키를 받는 /auth, 바깥 상태 확인용 /api/health (과금·데이터 없음)
EDGE_LOCK_OPEN = frozenset({"/auth", "/api/health"})

#: 과금 경로를 **동시에** 몇 개까지 돌리나 · 그중 팀 몫으로 비워 두는 칸 · 칸이 빌 때까지 기다리는 초 · 503 의 다시 시도 안내(초).
PAID_CONCURRENCY = shield.env_int("DEMO_PAID_CONCURRENCY", 16)
TEAM_RESERVED = shield.env_int("DEMO_TEAM_RESERVED", 4)
PAID_QUEUE_SEC = shield.env_float("DEMO_PAID_QUEUE_SEC", 10.0)
PAID_RETRY_SEC = shield.env_int("DEMO_PAID_RETRY_SEC", 5)
GATE = shield.PaidGate(capacity=PAID_CONCURRENCY, reserved=TEAM_RESERVED)

#: 공개(팀 아님) 과금 호출의 시간당 천장 — 크레딧 지갑을 지키는 마지막 줄. 0 이면 끈다.
PAID_PER_HOUR = shield.env_int("DEMO_PAID_PER_HOUR", 1500)
SPEND = RateLimiter(limit=PAID_PER_HOUR, window_sec=3600.0)
#: 시간당 천장에 세지 않는 과금 경로 — F-25 기억은 외부 호출이 없다 (디스크만 훑는다, 분당 상한은 그대로)
SPEND_EXEMPT = frozenset({"/api/v1/memory"})

#: 모든 요청의 IP(칸)당 분당 상한. 정적 파일은 대부분 Cloudflare 가 받아서 원본엔 HTML·API 만 온다 — 넉넉히.
IP_RPM = shield.env_int("DEMO_IP_RPM", 1200)
FLOOD = shield.FloodLimiter(limit=IP_RPM, window_sec=60.0)
#: 창(DEMO_BAN_WINDOW_SEC) 안에 막힌(429) 횟수가 이만큼이면 DEMO_BAN_SEC 동안 가둔다. 0 이면 안 가둔다.
BAN_STRIKES = shield.env_int("DEMO_BAN_STRIKES", 300)
JAIL = shield.Jail(strikes=BAN_STRIKES, window_sec=shield.env_float("DEMO_BAN_WINDOW_SEC", 60.0),
                   ban_sec=shield.env_float("DEMO_BAN_SEC", 600.0))

#: 손으로 막는 IP·주소대 목록, 점검 깃발 — 둘 다 파일이라 재시작 없이 켜고 끈다.
_VAR = ROOT / "var"
BLOCKLIST = shield.Blocklist(os.environ.get("DEMO_BLOCKLIST_FILE", "").strip() or (_VAR / "blocklist.txt"))
LOCKDOWN = shield.FlagFile(os.environ.get("DEMO_LOCKDOWN_FILE", "").strip() or (_VAR / "lockdown"))

#: 연결 단계별 시한 (초). SOCKET_TIMEOUT 은 recv·send **한 번**의 시한, 나머지는 단계 **전체**의 시한이다 (shield.Watchdog).
#: KEEPALIVE 는 다음 요청을 기다리는 시간 — Funnel(Go) 의 유휴 연결 정리(90초)보다 길게 둬서 우리가 먼저 끊는 경합을 피한다.
SOCKET_TIMEOUT = shield.env_float("DEMO_SOCKET_TIMEOUT", 30.0)
KEEPALIVE_SEC = shield.env_float("DEMO_KEEPALIVE_SEC", 120.0)
HEADER_TIMEOUT = shield.env_float("DEMO_HEADER_TIMEOUT", 15.0)
#: 본문은 크기에 따라 — SOCKET_TIMEOUT + 크기 ÷ 이 속도(KB/s). 40MB 녹음도 32KB/s 면 ~22분 안에 다 와야 한다 (실측 회선 ~330KB/s).
MIN_BODY_KBPS = shield.env_float("DEMO_MIN_BODY_KBPS", 32.0)
#: 한 IP(칸)가 동시에 올리는 큰 본문(1MB 넘는 녹음·자료) 수. 느린 업로드 수백 개로 연결 상한을 채우는 공격을 막는다.
IP_UPLOADS = shield.env_int("DEMO_IP_UPLOADS", 4)
BIG_BODY_BYTES = 1024 * 1024
_UPLOADS: dict[str, int] = {}
_UPLOADS_LOCK = threading.Lock()
#: 동시에 붙잡는 연결(=스레드) 상한과 listen 대기열. 넘치면 스레드를 만들지 않고 바로 503 을 쓰고 닫는다.
MAX_CONNECTIONS = shield.env_int("DEMO_MAX_CONNECTIONS", 256)
LISTEN_BACKLOG = shield.env_int("DEMO_LISTEN_BACKLOG", 128)

WATCHDOG = shield.Watchdog()
EVENTS = shield.EventCounter()
SHIELD_LOG = shield.LogThrottle(every=10.0)
#: 최근 공개 요청 20개가 어느 길로 왔나 (via·X-Forwarded-For 마지막 칸·비밀 머리글 유무) — /api/v1/ops/shield 가 보여 준다.
#: 비밀 머리글 **값**은 남기지 않는다 (ok·bad·none 만).
EDGE_SAMPLES: deque = deque(maxlen=20)


def _paid_path(path: str) -> bool:
    """과금 경로인가 — PAID_PATHS + 세션 경로의 판정(/api/v1/sessions/{id}/qa/judge)."""
    return path in PAID_PATHS or (path.endswith("/qa/judge") and "/api/v1/sessions/" in path)


def _dev_open() -> bool:
    """개발용 경로를 여는가 — 브리지를 DEMO_DEV_ROUTES=1 로 띄웠거나, 이 요청이 /auth 를 거친 팀 브라우저다."""
    return DEV_ROUTES or bool(getattr(_REQ, "team", False))


def _host_name(raw: str) -> str:
    """Host 헤더에서 포트를 뗀 이름. `[::1]:8799` 도 처리한다."""
    h = (raw or "").strip().lower()
    if h.startswith("["):
        return h[1:].split("]", 1)[0]
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


# ─── 모델 선택 (llm · provider) ────────────────────────────────────────────────
# 실 API 모드에서는 요청 본문의 llm/provider 를 **무시**하고 환경변수(REASONING_BACKEND ·
# STT_PROVIDER · HABIT_PROVIDER)만 쓴다. 본문을 믿으면 아무나 시간 과금 dedicated 엔드포인트를
# 부르거나 `mock` 결과를 실제 산출물로 보관시킬 수 있다. 벤치용 선택은 DEMO_DEV_ROUTES 에서만.
DEV_LLM_CHOICES = frozenset({"solar", "ax", "midm", "exaone"})
DEV_STT_CHOICES = frozenset({"skt-ax", "ax"})
DEV_HABIT_CHOICES = frozenset({"lora", "heuristic"})


def _dev_choice(value, allowed: frozenset[str]) -> str | None:
    """개발용 경로가 열렸을 때만(_dev_open), 허용 목록에 있는 값만 통과. `a+b`(주+예비) 꼴은 양쪽 다 허용돼야 한다."""
    if not _dev_open() or not isinstance(value, str):
        return None
    v = value.strip().lower()
    parts = [p.strip() for p in v.split("+")]
    return v if v and all(p in allowed for p in parts) else None


def _pick_llm(body: dict) -> str | None:
    """이번 요청의 LLM 이름. None 이면 모듈이 REASONING_BACKEND(+REASONING_FALLBACK) 를 따른다."""
    if _mock():
        return "mock"
    return _dev_choice(body.get("llm"), DEV_LLM_CHOICES)


def _pick_stt_provider(body: dict) -> str | None:
    """STT 제공자. None 이면 f05 가 STT_PROVIDER 환경변수를 따른다."""
    if _mock():
        return "mock"
    return _dev_choice(body.get("provider"), DEV_STT_CHOICES)


def _pick_habit_provider(body: dict) -> str | None:
    """습관 분석 제공자. 과금은 없지만(로컬 LoRA) 실 모드에서는 같은 규칙으로 환경변수만 따른다.
    mock 모드는 예전처럼 본문 값을 받는다 (extract_habits 가 모르는 값은 HabitError)."""
    if _mock():
        return body.get("provider")
    return _dev_choice(body.get("provider"), DEV_HABIT_CHOICES)


def _count_pages(data: bytes, ext: str) -> int | None:
    """
    업로드 문서의 장수를 **로컬에서** 센다. Upstage 는 페이지 단위로 과금하고, 파서의 MAX_SLIDES 검사는
    파싱이 끝난 뒤에 돈다 — 그 전에 막아야 청구가 안 나간다. 못 세면 None (파서 쪽 검사가 남는다).
    """
    try:
        if ext == ".pdf":
            try:
                from pypdf import PdfReader

                return len(PdfReader(io.BytesIO(data), strict=False).pages)
            except ImportError:
                # pypdf 가 없는 환경의 근사치: 페이지 객체 수. `/Type /Pages`(트리 노드)는 빼고 센다.
                n = len(re.findall(rb"/Type\s*/Page(?!s)", data))
                return n or None
        if ext == ".pptx":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                return sum(1 for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n))
    except Exception as e:  # noqa: BLE001 — 깨진 파일은 파서가 사실대로 말한다
        sys.stderr.write(f"[bridge] 장수 사전 확인 실패(파서에 맡김): {type(e).__name__}\n")
        return None
    return None


#: 500/502 응답에 그대로 실어도 되는 파서 오류 (사용자가 고칠 수 있는 사실만). 괄호 안 부가 정보는 뗀다.
_PUBLIC_PARSE_ERROR = re.compile(r"^\d+장입니다|^파일이 [\d.]+MB|지원하지 않습니다|초 안에 끝나지 않았습니다")
GENERIC_ERROR_MESSAGE = "요청을 처리하지 못했어요. 잠시 뒤 다시 해 주세요."


def _public_message(e: Exception) -> str:
    """응답에 싣는 오류 문구. 벤더 응답 본문·서버 경로가 섞일 수 있어 기본은 일반 문구다 — 상세는 stderr."""
    from chuckchuck.contracts import ParseError

    msg = str(e)
    if isinstance(e, ParseError) and _PUBLIC_PARSE_ERROR.search(msg):
        return re.sub(r"\s*\([^)]*\)", "", msg).strip()
    return GENERIC_ERROR_MESSAGE


PAPER_QUERY_MAX_CHARS = 300


def _max_slides() -> int:
    from chuckchuck.f01_parse import MAX_SLIDES

    return MAX_SLIDES


#: 판정 기록(history) 한 줄에서 받는 키 — QaTurn.from_dict 가 읽는 것만 (한글·영문 둘 다).
HISTORY_ITEM_KEYS = ("질문", "답변", "판정", "포기", "question_id", "question", "answer", "verdict", "gave_up")


def _clip_history_item(item: dict) -> dict:
    """
    기록 한 줄을 판정이 읽는 키만, 글자는 ANSWER_MAX_CHARS 까지 (09-30 B-18).

    예전엔 줄 수·전체 길이만 봐서, 한 줄에 3만 자짜리 「답변」 이나 모르는 키를 실어도 그대로 프롬프트까지 갔다.
    """
    out: dict = {}
    for key in HISTORY_ITEM_KEYS:
        if key not in item:
            continue
        value = item[key]
        out[key] = value if value is None or isinstance(value, (bool, int, float)) else str(value)[:ANSWER_MAX_CHARS]
    return out


def _clip_judge_inputs(body: dict) -> tuple[dict, str]:
    """
    F-09 판정 프롬프트에 실리는 필드의 길이를 제한한다 → (다듬은 본문, 거절 문구 또는 "").

    답변 한 개가 상한을 넘으면 거절한다 (사람이 한 질문에 하는 말은 수백 자다).
    기록류(history·prior_answers·hints_shown)는 부스 한 판 동안 계속 쌓이므로 거절하지 않고
    **오래된 것부터 잘라** 최근 것만 싣는다 — 막힘 코칭은 같은 질문의 최근 턴만 본다.
    """
    if len(str(body.get("answer", "") or "")) > ANSWER_MAX_CHARS:
        return body, f"답변은 {ANSWER_MAX_CHARS}자까지 판정할 수 있어요. 핵심만 줄여서 다시 답해 주세요."
    history = [_clip_history_item(h) for h in (body.get("history") or []) if isinstance(h, dict)][-HISTORY_MAX_ITEMS:] \
        if isinstance(body.get("history"), list) else []
    while history and len(json.dumps(history, ensure_ascii=False)) > HISTORY_MAX_CHARS:
        history = history[1:]
    prior = body.get("prior_answers") if isinstance(body.get("prior_answers"), list) else []
    hints = body.get("hints_shown") if isinstance(body.get("hints_shown"), list) else []
    return {
        **body,
        "history": history,
        "prior_answers": [str(a)[:ANSWER_MAX_CHARS] for a in prior][-PRIOR_ANSWERS_MAX:],
        "hints_shown": [str(h)[:ANSWER_MAX_CHARS] for h in hints][:PRIOR_ANSWERS_MAX],
    }, ""

ALLOWED_AUDIO_EXTS = frozenset(
    {".webm", ".m4a", ".mp4", ".mp3", ".wav", ".ogg", ".oga", ".flac", ".aac"}
)
DEFAULT_AUDIO_EXT = ".webm"


# f08 로 옮겼다 (FastAPI 라우트도 같은 사다리를 실어야 해서 단일 출처화).
# 테스트·기존 코드가 demo.bridge 에서 import 하므로 재수출로 남긴다.
from chuckchuck.f08_questions import with_hint_ladders  # noqa: E402, F401


def prior_answers_from(body: dict) -> list[str]:
    """
    이 질문에 앞서 낸 답변들. 비거나 공백뿐인 항목은 버린다.

    f09 는 되묻기로 나눠 낸 답을 합쳐 판정하는 기능(_answer_block)을 갖고 있고
    FastAPI 서버(server/app.py)도 이 필드를 넘긴다. 브리지만 버리면 되묻기에
    증분("네, 지연 시간이요")으로 답한 사용자가 그 조각만으로 판정받아
    unknown 에 갇힌다 — 2026-08-07 사용자 실측.
    """
    return [str(a) for a in (body.get("prior_answers") or []) if str(a).strip()]


def _safe_audio_ext(raw: str | None) -> str:
    """
    클라이언트가 준 확장자를 임시 파일 suffix 로 쓰기 전에 좁힌다.

    경로 조각이 섞여 들어오면 임시 파일 이름이 오염되므로 화이트리스트만 통과시킨다.
    모르는 값은 녹음 기본값으로 떨어뜨린다.
    """
    ext = (raw or "").strip().lower()
    if not ext.startswith("."):
        ext = f".{ext}" if ext else ""
    return ext if ext in ALLOWED_AUDIO_EXTS else DEFAULT_AUDIO_EXT


def _probe_audio_sec(path: Path) -> float:
    """ffprobe 로 재는 오디오 길이(초). ffprobe 가 없거나 실패하면 0 — 브라우저가 대신 잰다."""
    exe = media_tool("ffprobe") or "ffprobe"
    if not Path(exe).exists():
        return 0.0
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=20, check=False,
        ).stdout.strip()
        return round(float(out), 2) if out else 0.0
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def _cache_stem(file_name: str) -> str:
    """캐시 파일 이름으로 쓸 안전한 stem. 경로 조각·구분자를 모두 없앤다."""
    stem = Path(file_name or "").stem
    safe = "".join(ch for ch in stem if ch.isalnum() or ch in "-_ ").strip()
    return safe[:80] or "upload"


PDF_MAGIC = b"%PDF"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
IMAGE_EXTS = (".png", ".jpg")


def _multipart_files(raw: bytes, boundary: bytes) -> list[tuple[str, bytes]]:
    """
    multipart 본문에서 파일 파트를 올린 순서대로 (이름, 내용) 으로 돌려준다.

    예전에는 첫 파트에서 멈췄다. 부스 체험은 화면 캡처를 여러 장 올리므로 전부 모은다.
    내용 끝의 `\r\n` 은 파트 구분자에 붙은 것이라 정확히 한 번만 뗀다 — rstrip 은
    이진 파일의 실제 마지막 바이트까지 깎는다.
    """
    files: list[tuple[str, bytes]] = []
    for part in raw.split(b"--" + boundary):
        if b"filename=" not in part:
            continue
        header, _, content = part.partition(b"\r\n\r\n")
        if content.endswith(b"--"):
            content = content[:-2]
        if content.endswith(b"\r\n"):
            content = content[:-2]
        m = re.search(r'filename="([^"]+)"', header.decode(errors="ignore"))
        files.append((m.group(1) if m else "upload.pdf", content))
    return files


def _sniff_document(data: bytes) -> str | None:
    """
    업로드 내용으로 형식을 판별한다. 확장자는 사용자가 붙인 이름일 뿐이다.

    PDF 는 머리 1KB 안에 `%PDF`, PPTX 는 zip 이면서 `ppt/presentation.xml` 을 품는다.
    둘 다 아니면 None — 디스크에 쓰기 전에 거절한다.
    """
    if not data:
        return None
    if PDF_MAGIC in data[:1024]:
        return ".pdf"
    # 부스 체험용 화면 캡처. 확장자를 .jpg 로 통일한다 — f01 은 둘 다 받는다.
    if data.startswith(PNG_MAGIC):
        return ".png"
    if data.startswith(JPEG_MAGIC):
        return ".jpg"
    if data[:2] != b"PK":
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if "ppt/presentation.xml" in z.namelist():
                return ".pptx"
    except (zipfile.BadZipFile, OSError, RuntimeError):
        return None
    return None


def _session_id_of(body: dict) -> str:
    """본문의 session_id. 모양이 틀리면 빈 문자열 — 보관소가 거절하니 여기서 조용히 비운다."""
    return ARCHIVE.safe_id(body.get("session_id")) or ""


def _optional_alignment(body: dict):
    """
    /pace·/report 본문의 정합(선택). 녹음이 이 자료의 발표인지만 읽는다 (09-30 REC-10) — 없거나 모양이 깨졌으면 None.
    예전엔 이 칸이 없었던 요청이라, 곁다리 칸 하나가 깨졌다고 속도·리포트까지 500 으로 죽이지 않는다. 깨진 건 로그로 남긴다.
    """
    from chuckchuck.contracts import AlignmentDoc

    raw = body.get("alignment")
    if not isinstance(raw, dict):
        return None
    try:
        return AlignmentDoc.from_dict(raw)
    except (KeyError, TypeError, ValueError) as e:
        sys.stderr.write(f"[bridge] alignment 본문을 못 읽어 정합 없이 진행: {type(e).__name__}: {e}\n")
        return None


# LibreOffice 는 macOS 앱 번들·snap 설치에서 PATH 에 링크를 만들지 않는다.
# PATH 만 보면 설치돼 있어도 못 찾아 PPTX 원본 미리보기가 조용히 텍스트로 떨어진다.
_SOFFICE_FALLBACK_PATHS = (
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",  # macOS (brew cask 포함)
    "/opt/homebrew/bin/soffice",
    "/usr/local/bin/soffice",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
    "/snap/bin/libreoffice",
    os.path.expanduser("~/.local/bin/soffice"),  # sudo 없는 머신: AppImage 를 풀어 링크 (scripts/run_bridge_local.sh)
)


def _soffice_bin() -> str | None:
    import shutil

    override = os.environ.get("SOFFICE_BIN", "").strip()
    if override:
        if os.access(override, os.X_OK):
            return override
        sys.stderr.write(f"[bridge] SOFFICE_BIN 이 실행 가능하지 않음: {override}\n")

    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found

    for path in _SOFFICE_FALLBACK_PATHS:
        if os.access(path, os.X_OK):
            return path
    return None


def _pptx_to_preview_pdf(pptx_path: Path) -> bytes | None:
    """
    PPTX → PDF (LibreOffice headless). 발표 화면이 원본 슬라이드를 그리도록
    렌더한 PDF 바이트를 돌려준다. 어디에 남길지는 호출부(세션 보관소)가 정한다.
    """
    import shutil
    import subprocess

    soffice = _soffice_bin()
    if not soffice:
        sys.stderr.write(
            "[bridge] soffice 없음 — PPTX 원본 슬라이드를 그릴 수 없어 자리표시자로 떨어짐.\n"
            "[bridge]   설치: brew install --cask libreoffice "
            "(다른 경로면 SOFFICE_BIN=/path/to/soffice)\n"
        )
        return None
    out_dir = Path(tempfile.mkdtemp(prefix="chuckchuck-pdf-"))
    # 변환마다 사용자 프로필을 따로 둔다 — 공유 프로필은 동시 변환이 서로 막고, 남의 파일이 남긴 설정을 잇는다.
    profile_dir = Path(tempfile.mkdtemp(prefix="chuckchuck-lo-"))
    try:
        proc = subprocess.run(
            [
                soffice,
                f"-env:UserInstallation={profile_dir.as_uri()}",
                "--headless",
                "--nologo",
                "--nofirststartwizard",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(out_dir),
                str(pptx_path),
            ],
            check=False,
            timeout=240,
            capture_output=True,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or b"").decode(errors="replace")[:400]
            sys.stderr.write(f"[bridge] pptx→pdf failed rc={proc.returncode}: {err}\n")
            return None
        produced = list(out_dir.glob("*.pdf"))
        if not produced:
            sys.stderr.write("[bridge] pptx→pdf: 출력 PDF 없음\n")
            return None
        data = produced[0].read_bytes()
        sys.stderr.write(f"[bridge] preview PDF 렌더 ({len(data)} bytes)\n")
        return data
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[bridge] pptx→pdf exception: {e!r}\n")
        return None
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
        shutil.rmtree(profile_dir, ignore_errors=True)


def _mock() -> bool:
    return settings.mock_external


#: mock 모드에서 각 분석 단계에 끼워 넣는 인위 지연(초). 0 이면 끈다.
#:
#: mock 은 모든 단계가 즉시 끝나서 **대기 화면을 검증할 수 없다** — 실 API 로만 확인하면
#: 한 번에 7분과 과금이 든다. 이 노브로 실 API 를 태우지 않고 진행률·리빌 대기 씬을
#: 반복해서 볼 수 있다. 실 API 경로에는 절대 걸리지 않는다 (_mock() 일 때만 잔다).
FAKE_STAGE_DELAY_SEC = float(os.environ.get("DEMO_FAKE_STAGE_DELAY_SEC", "0") or 0)

#: 단계별 상대 무게 — 실측 비율 그대로다 (STT 30초 · F-06 1분43초 · F-07 2분40초 · F-11 2분27초).
#: 지연 1초를 주면 이 비율대로 나눠 잔다. 어느 단계가 긴지까지 재현해야 대기 화면이 진짜처럼 보인다.
FAKE_DELAY_WEIGHT = {
    "/api/v1/transcribe": 0.30,
    "/api/v1/concepts": 1.03,
    "/api/v1/graph": 1.60,
    "/api/v1/alignment": 1.47,
}


def _fake_delay(path: str) -> None:
    if not FAKE_STAGE_DELAY_SEC or not _mock():
        return
    weight = FAKE_DELAY_WEIGHT.get(path)
    if not weight:
        return
    time.sleep(FAKE_STAGE_DELAY_SEC * weight)


# ─── 단계 결과 디스크 캐시 (F-06 · F-07) ──────────────────────────────────────
#
# 실측 7분 30초 중 F-06(1분43초) + F-07(2분40초) = 4분 23초는 **발표자료만** 보고 만든다.
# 부스에서 같은 자료로 열 번 시연하면 그 4분 23초를 열 번 다시 태운다.
#
# 파일 이름이 아니라 **내용 해시**로 건다. SlideDoc 캐시는 파일명 stem 을 쓰는데,
# 이름이 같은 다른 자료가 조용히 붙을 수 있어서 그쪽은 근사 매치 폴백을 금지해 뒀다.
# 여기서는 아예 내용이 1비트라도 다르면 다른 키가 되게 한다 — 근사 매치가 존재할 수 없다.
STAGE_CACHE_ON = os.environ.get("DEMO_STAGE_CACHE", "1").lower() not in ("0", "false", "off")
#: 단계 캐시 폴더. None 이면 **지금의** 보관소(ARCHIVE.stage_dir)를 따른다 — 보관소를 바꿔 끼우면(테스트·DEMO_DATA_DIR)
#: 캐시도 따라간다. 예전엔 시작 때 경로를 굳혀서, 보관소만 임시 폴더로 바꾼 테스트가 실제 var/data 캐시를 읽고 썼다.
STAGE_CACHE_DIR: Path | None = None


def _stage_dir() -> Path:
    return STAGE_CACHE_DIR or ARCHIVE.stage_dir


# ─── 코드 판 — 캐시 키가 **지금 돌고 있는 코드**를 가리키게 (09-30 B-02·G-A4/A5/A34) ─────────────────────
#
# 2026-09-28: F-07 위계를 고쳤는데 캐시가 같은 자료에 옛 그래프를 그대로 돌려줬다 → 키에 모듈 소스 해시를 넣었다(7756058).
# 09-30 감사에서 그 해시에 구멍이 둘 더 나왔다.
#  ① 키에 넣은 모듈이 **손으로 적은 목록**이었다. F-26 키는 f26 하나뿐이라 대조 규칙(_claim_rules·_claim_quote·_evidence·
#     _match)을 고쳐도 옛 주장이 나왔고, F-06 키는 받아쓰기 조각(f05)을, F-07 키는 _match·_json_text 를 빠뜨렸다.
#     → 단계의 진입 모듈에서 import 를 따라가 닫힌 목록을 **자동으로** 모은다 (함수 안의 지연 import 까지 — ast 로 본다).
#  ② 해시를 **요청 때 디스크에서** 읽었다. 이 VM 에서는 8799 가 도는 동안 다른 세션이 파일을 고친다 — 그러면 새 소스의
#     키 자리를 **메모리에 올라 있는 옛 코드**의 결과가 채우고, 재시작한 새 코드가 그 옛 결과를 제 것인 줄 알고 쓴다.
#     → 소스는 브리지가 뜰 때(= 모듈을 올린 직후) 한 번만 읽어 둔다. 키는 언제나 지금 돌고 있는 코드의 판이다.

import chuckchuck as _chuckchuck_pkg  # noqa: E402

#: 단계 → 그 단계의 출력을 만드는 진입 모듈. 키에 넣을 모듈 목록은 여기서 import 를 따라가 모은다.
#: 새 단계 캐시를 만들면 여기에 한 줄 — tests/test_bridge_stage_cache.py 가 진입 함수가 이 모듈에 있는지 검사한다.
STAGE_ENTRY_MODULES: dict[str, tuple[str, ...]] = {
    "parse": ("chuckchuck.f01_parse",),                  # parse_document·merge_slidedocs — 디스크 캐시 (올린 파일 sha256)
    "concepts": ("chuckchuck.f06_concepts",),            # extract_concepts — 디스크 캐시
    "graph": ("chuckchuck.f07_graph",),                  # build_graph — 디스크 캐시
    "claims": ("chuckchuck.f26_claims",),                # build_claims — 디스크 캐시
    "papers": ("chuckchuck.f24_papers",),                # build_papers — 보관소
    "memory": ("chuckchuck.f25_memory",),                # build_memory
    "triage": ("chuckchuck.f08_questions",),             # triage_questions
    # 질문 묶음은 주장·문헌·기억을 재료로 먹는다 — 그 모듈이 바뀌어도 옛 질문을 안 쓴다
    "questions": ("chuckchuck.f08_questions", "chuckchuck.f26_claims", "chuckchuck.f24_papers", "chuckchuck.f25_memory"),
    "judge": ("chuckchuck.f09_judge",),                  # judge_answer
    "chatter": ("chuckchuck.f12_chatter",),              # build_chatter — 디스크 캐시 (세션 id + 재료 해시, 09-30 REC-19)
    # 부스는 덱 3개 × 녹음 2개로 정해져 있다 (10-06 사용자: 「새로운 ppt 없으니 로딩 시간 줄일 수 있는 게 많다」).
    # 같은 녹음 → 같은 받아쓰기 → 같은 정합 · 질문이 되도록 받아쓰기와 정합도 내용 해시로 디스크에 둔다
    "transcribe": ("chuckchuck.f05_stt",),               # transcribe — 디스크 캐시 (녹음 sha256 + 장 표시 + 제공자)
    "alignment": ("chuckchuck.f11_align",),              # align_speech — 디스크 캐시 (그래프 · 받아쓰기 · 본문 · 상황)
}


def _snapshot_sources(pkg_dir: Path) -> dict[str, tuple[str, bytes, bool]]:
    """패키지 폴더 아래 모든 모듈의 소스를 **지금** 한 번 읽는다 → {모듈 이름: (sha1 앞 12자, 소스, 패키지 __init__ 인가)}."""
    out: dict[str, tuple[str, bytes, bool]] = {}
    for path in sorted(pkg_dir.rglob("*.py")):
        parts = path.relative_to(pkg_dir.parent).with_suffix("").parts
        is_pkg = parts[-1] == "__init__"
        name = ".".join(parts[:-1] if is_pkg else parts)
        try:
            src = path.read_bytes()
        except OSError:
            continue
        out[name] = (hashlib.sha1(src).hexdigest()[:12], src, is_pkg)
    return out


def _imports_of(name: str, source: bytes, is_pkg: bool, known) -> set[str]:
    """
    모듈 소스가 import 하는 **같은 패키지** 모듈들. 함수 안의 지연 import(`from ._deck_claims import clauses`)도 센다.

    `from . import _graph_items` 는 하위 모듈, `from .contracts import X` 는 contracts 모듈을 가리킨다.
    `from 패키지 import 이름` 에서 이름이 하위 모듈이 아니면 그 패키지 __init__ 자체를 넣는다 (넓게 잡는 쪽이 안전하다).
    """
    import ast

    pkg = name if is_pkg else name.rpartition(".")[0]
    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names if a.name in known)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg.split(".")
                if node.level > 1:
                    base = base[: len(base) - (node.level - 1)]
                mod = ".".join([*base, node.module] if node.module else base)
            else:
                mod = node.module or ""
            for a in node.names:
                if f"{mod}.{a.name}" in known:
                    out.add(f"{mod}.{a.name}")
                elif mod in known:
                    out.add(mod)
    return out


def _import_closure(entries, sources: dict[str, tuple[str, bytes, bool]]) -> frozenset[str]:
    """진입 모듈들에서 import 를 따라가 닿는 같은 패키지 모듈 전부 (자기 자신 포함)."""
    seen: set[str] = set()
    stack = [e for e in entries if e in sources]
    while stack:
        mod = stack.pop()
        if mod in seen:
            continue
        seen.add(mod)
        _, src, is_pkg = sources[mod]
        stack.extend(_imports_of(mod, src, is_pkg, sources) - seen)
    return frozenset(seen)


def _version_of(modules, hashes: dict[str, str]) -> str:
    h = hashlib.sha1()
    for mod in sorted(modules):
        h.update(f"{mod}={hashes.get(mod, '')}\n".encode("utf-8"))
    return h.hexdigest()[:12]


_PKG_DIR = Path(_chuckchuck_pkg.__file__).resolve().parent
_SOURCES_AT_START = _snapshot_sources(_PKG_DIR)
#: 브리지가 뜰 때 읽은 모듈 소스 해시. 이후 디스크가 바뀌어도 이 값은 안 바뀐다 — 돌고 있는 코드가 안 바뀌니까.
SOURCE_HASHES: dict[str, str] = {name: h for name, (h, _, _) in _SOURCES_AT_START.items()}
#: 단계 → 키에 들어가는 모듈 (import 닫힘).
STAGE_MODULES: dict[str, frozenset[str]] = {
    stage: _import_closure(entries, _SOURCES_AT_START) for stage, entries in STAGE_ENTRY_MODULES.items()
}
#: 단계 → 코드 판. 키에는 이것만 넣는다.
STAGE_VERSIONS: dict[str, str] = {stage: _version_of(mods, SOURCE_HASHES) for stage, mods in STAGE_MODULES.items()}
del _SOURCES_AT_START   # 소스 본문(≈1MB)은 닫힘을 셀 때만 필요하다

# 닫힘 안의 모듈이 아직 안 올라왔으면(함수 안에서 늦게 import 하는 것) 지금 올린다 — 해시를 읽은 소스와 같은 판이 돌게.
import importlib  # noqa: E402

for _mod in sorted(set().union(*STAGE_MODULES.values())):
    if _mod not in sys.modules:
        importlib.import_module(_mod)

#: 디스크 소스가 브리지 시작 뒤 바뀌었는지 다시 볼 간격(초). 캐시 키와는 무관하다 — 사람에게 재시작하라고 알리는 용도.
SOURCE_DRIFT_CHECK_SEC = 30.0
_DRIFT_STATE = {"checked_at": 0.0, "warned": set()}
_DRIFT_LOCK = threading.Lock()


def _warn_source_drift(modules) -> None:
    """돌고 있는 코드와 디스크 소스가 갈라졌으면 한 번 알린다. 키는 그대로 **돌고 있는 코드**의 판이다."""
    now = time.monotonic()
    with _DRIFT_LOCK:
        if now - _DRIFT_STATE["checked_at"] < SOURCE_DRIFT_CHECK_SEC:
            return
        _DRIFT_STATE["checked_at"] = now
    for mod in sorted(modules):
        if mod in _DRIFT_STATE["warned"]:
            continue
        parts = mod.split(".")
        base = _PKG_DIR.parent.joinpath(*parts)
        path = base / "__init__.py" if (base / "__init__.py").is_file() else base.with_suffix(".py")
        try:
            now_hash = hashlib.sha1(path.read_bytes()).hexdigest()[:12]
        except OSError:
            continue
        if now_hash != SOURCE_HASHES.get(mod):
            _DRIFT_STATE["warned"].add(mod)
            sys.stderr.write(f"[bridge] ⚠ {mod} 소스가 브리지를 띄운 뒤 바뀌었어요 — 돌고 있는 건 옛 코드예요. "
                             "캐시 키도 옛 코드 판으로 남기니, 새 코드를 쓰려면 브리지를 다시 띄워요.\n")


def _stage_version(stage: str) -> str:
    """단계의 코드 판 — 그 단계 진입 모듈의 import 닫힘 전체를 브리지 시작 때 읽은 소스로 센 해시."""
    _warn_source_drift(STAGE_MODULES[stage])
    return STAGE_VERSIONS[stage]


def _code_version(module_name: str) -> str:
    """모듈 하나의 소스 해시 (브리지 시작 때 읽은 것). 키에는 `_stage_version` 을 쓴다 — 모듈 하나로는 닫히지 않는다."""
    return SOURCE_HASHES.get(module_name, "")


def _llm_identity(llm) -> str:
    """
    키에 넣을 LLM. 본문이 고른 것(개발 경로)이 없으면 환경변수가 정한 주·예비다.

    예전엔 실 모드의 llm(None)을 그대로 넣어, REASONING_BACKEND 를 바꿔 다시 띄워도 옛 모델의 그래프·주장을 돌려줬다.
    """
    if llm:
        return str(llm)
    primary = (os.environ.get("REASONING_BACKEND") or "solar").strip().lower()   # llm_impl.get_llm 의 기본값과 같다
    return f"env:{primary}+{(os.environ.get('REASONING_FALLBACK') or '').strip().lower()}"


def _canon(cls, raw):
    """계약 모양(cls.from_dict → to_dict). 단계가 실제로 읽는 것만 남긴다 — 세션 표시·프론트가 붙인 키는 빠진다. 못 읽으면 날 것."""
    if raw is None:
        return None
    try:
        return cls.from_dict(raw).to_dict() if isinstance(raw, dict) else raw.to_dict()
    except Exception:  # noqa: BLE001 — 키 계산이 요청을 죽이면 안 된다. 날 것으로 세면 캐시가 덜 맞을 뿐이다
        return raw


def _stage_key(*parts) -> str:
    """출력에 영향을 주는 것 전부를 넣은 내용 해시. 하나라도 빠지면 캐시가 거짓말을 한다."""
    h = hashlib.sha1()
    for p in parts:
        h.update(json.dumps(p, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:20]


#: 만드는 중인 질문 (q_key → Event). 미리 만들기와 실제 요청이 겹치면 한쪽만 LLM 을 부른다.
_QUESTIONS_INFLIGHT: dict[str, threading.Event] = {}
_QUESTIONS_LOCK = threading.Lock()
#: 만드는 중인 것을 기다리는 최대 초. 질문 생성은 보통 20~30초 — 넘기면 기다리던 쪽이 직접 만든다.
QUESTIONS_INFLIGHT_WAIT_SEC = 150


def _questions_ready(q_key: str):
    """만든 질문 — 메모리에 없으면 디스크(정상 재료로 만든 것만 남는다). 재시작해도 부스 덱 질문을 다시 안 만든다 (10-06)."""
    got = STORE.get_triage(q_key)
    if got is None:
        got = _stage_cache_get("questions", _questions_disk_key(q_key))
        if got is not None:
            STORE.set_triage(q_key, got)
    return got


def _questions_disk_key(q_key: str) -> str:
    return hashlib.sha1(q_key.encode("utf-8")).hexdigest()[:20]


def _claim_questions(q_key: str) -> threading.Event | None:
    """내가 만들 차례면 Event(끝나면 set), 누가 이미 만드는 중이면 None."""
    with _QUESTIONS_LOCK:
        if q_key in _QUESTIONS_INFLIGHT:
            return None
        ev = threading.Event()
        _QUESTIONS_INFLIGHT[q_key] = ev
        return ev


def _wait_questions(q_key: str) -> None:
    with _QUESTIONS_LOCK:
        ev = _QUESTIONS_INFLIGHT.get(q_key)
    if ev is not None:
        ev.wait(QUESTIONS_INFLIGHT_WAIT_SEC)


def _release_questions(q_key: str, ev: threading.Event) -> None:
    with _QUESTIONS_LOCK:
        if _QUESTIONS_INFLIGHT.get(q_key) is ev:
            _QUESTIONS_INFLIGHT.pop(q_key, None)
    ev.set()


#: 만드는 중인 객석 수다 (key → Event). 결과 화면을 열며 미리 받기 시작한 것과 리포트를 새로 열어 부른 것이 겹치면 한쪽만 LLM 을
#: 부르고 다른 쪽은 끝나길 기다렸다가 캐시에서 읽는다 (09-30 녹음 대화 감사 REC-19 — 브라우저가 끊은 요청도 끝까지 만들어 캐시에 남는다).
_CHATTER_INFLIGHT: dict[str, threading.Event] = {}
_CHATTER_LOCK = threading.Lock()
#: 기다리는 최대 초 — 라운드 둘 × 병아리 상한(f12 CHATTER_SPEAKER_TIMEOUT_SEC 45초) + 여유. 넘기면 기다리던 쪽이 직접 만든다.
CHATTER_INFLIGHT_WAIT_SEC = 120
#: 못 온 병아리가 있던 수다 (key → (시각, payload)). 디스크 캐시에는 안 쓴다 — 실패를 성공처럼 굳히지 않는다. 다만 방금 45초를 태우고
#: 죽은 모델을 곧바로 다시 부르면 또 죽는다(09-30 실측: 믿:음·엑사원이 두 번 연속 결석, 그사이 LLM 7콜씩). 이 초 안에는 방금 결과를
#: 결석 표시 그대로 돌려주고, 지나면 다시 부른다.
_CHATTER_PARTIAL: dict[str, tuple[float, dict]] = {}
CHATTER_RETRY_AFTER_SEC = 90


def _recent_partial_chatter(key: str) -> dict | None:
    """방금(CHATTER_RETRY_AFTER_SEC 안) 결석이 있던 수다 — 오래된 것은 지운다."""
    now = time.monotonic()
    with _CHATTER_LOCK:
        for k in [k for k, (at, _) in _CHATTER_PARTIAL.items() if now - at >= CHATTER_RETRY_AFTER_SEC]:
            _CHATTER_PARTIAL.pop(k, None)
        got = _CHATTER_PARTIAL.get(key)
    return got[1] if got else None


def _remember_chatter(key: str, payload: dict, complete: bool) -> None:
    """전원 등장이면 디스크 캐시, 결석이 있으면 잠깐만 기억한다 (다시 부를 때까지)."""
    if complete:
        _stage_cache_put("chatter", key, payload)
        with _CHATTER_LOCK:
            _CHATTER_PARTIAL.pop(key, None)
    else:
        with _CHATTER_LOCK:
            _CHATTER_PARTIAL[key] = (time.monotonic(), payload)


def _claim_chatter(key: str) -> threading.Event | None:
    """내가 만들 차례면 Event(끝나면 set), 누가 이미 만드는 중이면 None."""
    with _CHATTER_LOCK:
        if key in _CHATTER_INFLIGHT:
            return None
        ev = threading.Event()
        _CHATTER_INFLIGHT[key] = ev
        return ev


def _wait_chatter(key: str) -> None:
    with _CHATTER_LOCK:
        ev = _CHATTER_INFLIGHT.get(key)
    if ev is not None:
        ev.wait(CHATTER_INFLIGHT_WAIT_SEC)


def _release_chatter(key: str, ev: threading.Event) -> None:
    with _CHATTER_LOCK:
        if _CHATTER_INFLIGHT.get(key) is ev:
            _CHATTER_INFLIGHT.pop(key, None)
    ev.set()


def _chatter_key(sid: str, body: dict) -> str:
    """
    객석 수다 캐시 키 — 세션 id + 재료(그래프·정합·흐름, 계약 모양) 해시 + f12 코드 판 + 어느 모델로 부르나(목업이면 목업).

    재료가 하나라도 바뀌면(다시 분석) 새 키다. 세션 id 가 없으면(옛 화면) 재료만으로 — 같은 재료면 같은 수다를 돌려줘도 된다.
    """
    from chuckchuck.contracts import AlignmentDoc, FlowDiff

    return _stage_key(
        "chatter", _stage_version("chatter"), sid or "",
        _canon(ConceptGraph, body.get("graph")), _canon(AlignmentDoc, body.get("alignment")),
        _canon(FlowDiff, body.get("flow")), _llm_identity(None), _mock(),
    )


def _stage_cache_get(stage: str, key: str):
    if not STAGE_CACHE_ON:
        return None
    try:
        raw = (_stage_dir() / f"{stage}-{key}.json").read_text(encoding="utf-8")
        return json.loads(raw)
    except (OSError, ValueError):
        return None


def _stage_cache_put(stage: str, key: str, payload: dict) -> None:
    if not STAGE_CACHE_ON:
        return
    try:
        _stage_dir().mkdir(parents=True, exist_ok=True)
        # tmp 에 쓰고 rename — 두 트랙이 같은 단계를 동시에 끝내도 반쪽 JSON 이 남지 않는다.
        # tmp 도 .json 으로 끝나게 둔다 — 쓰다 죽어 남으면 보관소 청소(prune, mtime)가 같이 지운다
        path = _stage_dir() / f"{stage}-{key}.json"
        tmp = path.with_name(f"{path.stem}.{threading.get_ident()}.tmp.json")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        # 캐시 저장 실패는 분석 실패가 아니다. 삼키되 조용히는 안 한다
        sys.stderr.write(f"[bridge] {stage} 캐시 저장 실패(무시): {e}\n")


def _slidedoc_kw(fn, slidedoc) -> dict:
    """F-08 1차 심사에 본문을 넘길 kwargs — 받는 쪽 시그니처에 `slidedoc` 이 있을 때만 (가짜 triage(**_) 에는 싣지 않는다)."""
    if not slidedoc:
        return {}
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}
    return {"slidedoc": slidedoc} if "slidedoc" in params else {}


# 함정 질문의 화면 사본 규칙(뺄 칸 · 언제 다시 실을지)은 FastAPI 서버와 같은 것을 쓴다 — `chuckchuck._client_payload`.
# 09-30 WP-J2 에 여기서 먼저 넣었는데 server/app.py 는 사실 칸을 그대로 내보냈다. 규칙이 두 벌이면 두 서버가 다시 갈라진다.
from chuckchuck._client_payload import (  # noqa: E402
    TRAP_WITHHELD,  # noqa: F401 — 예전처럼 bridge.TRAP_WITHHELD 로도 읽힌다 (labs/qa_verify 가 이름을 말한다)
    client_judgement,
    client_questions,
    reveal_due,  # noqa: F401 — 판정 응답은 client_judgement 가 부른다. 이름은 두 서버가 같은 규칙을 쓰는지 테스트가 본다
    reveal_fields,
)


def _claims_kw(fn, claims) -> dict:
    """
    F-08 에 주장(F-26)을 넘길 kwargs. 받는 쪽 시그니처에 `claims` 가 있을 때만 싣는다.

    F-08 의 claims 인자는 다른 갈래(P1/P3/P4)가 붙이는 중이다 — 합쳐지기 전 트리에서도 브리지가
    TypeError 없이 돌아야 한다. 테스트가 끼워 넣는 가짜 build_questions(**_) 에도 싣지 않는다.
    """
    if claims is None:
        return {}
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}
    return {"claims": claims.to_dict()} if "claims" in params else {}


# ─── 세션 id — 메모리 저장소와 디스크 보관소 (09-30 B-06) ─────────────────────────────────────────────
#
# 프론트는 서버가 발급한 id 가 없으면(샘플·mock·보관소 쓰기 실패) 'flat' 하나로 질문·판정을 주고받는다
# (app.js FLAT_QA_SESSION_ID · chuckchuck_bridge.js judgeQaAnswer). 그런데 등록(/session/artifacts)은 발급 모양만 받아
# 'flat' 을 400 으로 거절하고, 판정의 _resolve 는 날 문자열로 찾았다 — 그래서 flat 판정은 409(세션 없음) → 재등록 400 으로
# **언제나** 실패했다. 이제 메모리 저장소 쪽은 발급 모양 + 'flat' 을 같은 규칙으로 받고, 디스크 보관소는 발급 모양만 받는다.

#: 서버가 발급하지 않은 세션의 자리표시자. 메모리 저장소에만 쓰고 디스크에는 절대 안 쓴다.
FLAT_SESSION_ID = "flat"
#: 큰 본문에서 요청 제한 칸(session_id)만 찾는 표식. 값 모양은 _store_sid 가 다시 거른다.
_SESSION_ID_RE = re.compile(rb'"session_id"\s*:\s*"([A-Za-z0-9_]{1,64})"')


def _store_sid(raw) -> str:
    """메모리 저장소(STORE) 열쇠. 발급 모양의 id 또는 'flat'. 그 밖은 빈 문자열 — 아무 문자열이나 받으면 자리를 채워 남의 세션을 민다."""
    if raw == FLAT_SESSION_ID:
        return FLAT_SESSION_ID
    return ARCHIVE.safe_id(raw) or ""


# ─── 같은 일은 한 번만 (09-30 B-04) ─────────────────────────────────────────────────────────────────────
#
# 분석이 끝나면 프론트가 10분 트랙을 미리 만들고, 시간을 고르면 5분 트랙도 미리 만든다 — 둘이 겹치면 트랙과 무관한
# 주장(F-26)·문헌(F-24)·1차 심사(triage)를 **두 번씩** 돌렸다 (LLM 3콜 + 학술 검색 한 벌이 헛돈다).
# 질문 묶음 단위의 기다림(_QUESTIONS_INFLIGHT)은 트랙이 다르면 서로를 모른다 — 재료 단위로 한 번 더 묶는다.

class _Flights:
    """열쇠가 같은 일을 동시에 두 번 하지 않는다. 먼저 온 쪽이 뒤 스레드에서 돌리고, 나머지는 같은 Future 를 받는다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, "Future"] = {}

    def run(self, key: str, fn) -> "Future":
        from concurrent.futures import Future

        with self._lock:
            fut = self._jobs.get(key)
            if fut is not None:
                return fut
            fut = Future()
            self._jobs[key] = fut

        def work() -> None:
            try:
                fut.set_result(fn())
            except BaseException as e:  # noqa: BLE001 — 기다리는 쪽에 그대로 넘긴다
                fut.set_exception(e)
            finally:
                with self._lock:
                    if self._jobs.get(key) is fut:
                        self._jobs.pop(key, None)

        # 데몬 스레드 — 기다리는 요청이 제한 시간에 먼저 떠나도 일은 끝까지 해서 캐시를 채운다
        threading.Thread(target=work, name=f"flight:{key[:40]}", daemon=True).start()
        return fut

    def busy(self) -> list[str]:
        with self._lock:
            return list(self._jobs)


_FLIGHTS = _Flights()


# ─── 폴백은 폴백이라고 말한다 (09-30 B-03·G-A13/A19) ────────────────────────────────────────────────────
#
# 주장 LLM 이 죽어 규칙 주장만 나온 것, 학술 검색이 429·시간 초과로 빈 문헌, 지난 리허설을 못 읽은 것 —
# 셋 다 예외를 삼키고 **성공처럼** 캐시·보관돼 같은 세션 끝까지 반쪽 질문을 만들었고, 응답에는 아무 표시가 없었다.
# 이제 응답에 degraded(코드)·degraded_notes(사람 말)를 싣고, 폴백 결과는 짧게만 들고 있다가 다시 시도한다.

#: 폴백 결과(규칙 주장·실패한 문헌·그걸로 만든 질문 묶음)를 들고 있는 초. 미리 만들기 → 시작 한 쌍은 이 안에서 나눠 쓴다.
FALLBACK_TTL_SEC = float(os.environ.get("DEMO_FALLBACK_TTL_SEC", "120") or 120)
#: 질문 생성이 문헌을 기다리는 최대 초 (주장과 **같이** 돌리므로 주장이 더 오래 걸리면 그만큼 더 기다린 셈이다).
#: 09-30 실측(G-A9): 검색 통로가 막히면 /questions 가 ~60초 서 있었다 — 프론트 제한이 60초라 질문이 통째로 실패했다.
PAPERS_DEADLINE_SEC = float(os.environ.get("DEMO_PAPERS_DEADLINE_SEC", "6") or 6)
#: 검색 통로가 실패하면 이 초 동안은 부르지 않고 자료 인용만 쓴다 (4갈래 arXiv 가 줄줄이 429 를 받던 것 — B-14/B-15).
PAPERS_NEGATIVE_TTL_SEC = float(os.environ.get("DEMO_PAPERS_NEGATIVE_TTL_SEC", "180") or 180)
#: 주장(F-26) 을 기다리는 최대 초. LLM 한 콜 + 재시도 — 넘기면 주장 없이 간다.
CLAIMS_WAIT_SEC = float(os.environ.get("DEMO_CLAIMS_WAIT_SEC", "90") or 90)

#: 응답의 degraded 코드 → 화면에 그대로 띄워도 되는 한 문장 (프론트 몫은 따로 — 여기서는 사실만 싣는다).
DEGRADED_NOTES = {
    "slide_doc_missing": "자료 본문을 찾지 못해 자료와 대조하지 않고 진행했어요. 자료를 다시 올리면 대조해요.",
    "question_unverified": "서버가 만든 질문을 찾지 못해 화면의 질문으로 판정했어요. 이 판정은 기록에 남기지 않아요.",
    "question_mismatch": "화면의 질문이 서버가 만든 질문과 달라서 서버의 질문으로 판정했어요.",
    "claims_rule_only": "주장 그래프를 AI 로 만들지 못해 규칙으로 찾은 주장만 썼어요.",
    "claims_failed": "주장 그래프를 만들지 못해 주장 없이 질문을 만들었어요.",
    "claims_timeout": "주장 그래프가 늦어져 주장 없이 질문을 만들었어요.",
    "papers_timeout": "문헌 검색이 늦어져 자료가 인용한 문헌만으로 질문을 만들었어요.",
    "papers_unavailable": "문헌 검색이 잠시 안 돼서 자료가 인용한 문헌만으로 질문을 만들었어요.",
    "papers_partial": "문헌 검색 일부가 실패해서 찾은 문헌만으로 질문을 만들었어요.",
    "papers_failed": "문헌을 불러오지 못해 문헌 없이 질문을 만들었어요.",
    "memory_failed": "지난 리허설 기억을 읽지 못해 기억 없이 진행했어요.",
    # /concepts · /graph (09-30 WP-Q2 — F-06 이 끝내 못 받은 장 · F-07 이 떨군 단계, `ConceptGraph.degraded`)
    "concepts_missing": "AI 가 개념을 돌려주지 않은 장이 있어서 그 장은 개념 없이 분석했어요. 다시 분석하면 채울 수 있어요.",
    "links": "개념 사이 연결을 보강하지 못해 처음 그린 연결로 개념 그래프를 만들었어요. 다시 분석하면 연결을 채울 수 있어요.",
}
#: 잠깐 뒤 다시 하면 나아질 수 있는 것 — 이걸로 만든 질문 묶음은 FALLBACK_TTL_SEC 만 들고 있는다.
#: slide_doc_missing 은 안 넣는다 (다시 해도 본문이 생기지 않는다 — 짧게 들면 같은 질문을 LLM 으로 계속 다시 만든다).
TRANSIENT_DEGRADED = frozenset({
    "claims_rule_only", "claims_failed", "claims_timeout",
    "papers_timeout", "papers_unavailable", "papers_partial", "papers_failed", "memory_failed",
})


def _with_degraded(payload: dict, degraded: list[str]) -> dict:
    """응답에 degraded(코드 목록)·degraded_notes(같은 순서의 문장)를 싣는다. 폴백이 없으면 빈 목록 — 키는 언제나 있다."""
    codes = list(dict.fromkeys(degraded))
    return {**payload, "degraded": codes, "degraded_notes": [DEGRADED_NOTES.get(c, c) for c in codes]}


#: 학술 검색이 실패했을 때 f24 가 note 에 남기는 표식 (_search_many · MultiScholar). 코드가 아니라 문장이라 여기 모아 둔다.
_PAPERS_FAIL_MARKS = ("검색 실패", "검색 오류", "모든 통로 실패")
PAPERS_RESTING_NOTE = "검색 통로가 최근 실패해서 잠시 쉬어요 — 자료가 인용한 문헌만"
PAPERS_TIMEOUT_NOTE = "문헌 검색이 제한 시간을 넘겨 자료가 인용한 문헌만 — 검색은 뒤에서 마저 해요"
#: 보관한 paper_doc 에 붙이는 그래프 지문 키 (09-30 B-11). PaperDoc.from_dict 는 모르는 키를 무시한다.
PAPERS_GRAPH_FP_KEY = "graph_fp"
_PAPERS_DOWN: dict[str, float] = {}
_PAPERS_DOWN_LOCK = threading.Lock()


def _papers_spec(scholar) -> str:
    """부정 캐시 열쇠 — 어떤 검색 통로 묶음인가 (SCHOLAR_PROVIDER). none 이면 실패할 게 없다."""
    return str(scholar) if scholar else (os.environ.get("SCHOLAR_PROVIDER") or "none").strip().lower()


def _papers_down_left(spec: str) -> float:
    """이 통로를 앞으로 몇 초 더 쉬나. 0 이면 불러도 된다."""
    with _PAPERS_DOWN_LOCK:
        return max(0.0, _PAPERS_DOWN.get(spec, 0.0) - time.monotonic())


def _mark_papers_down(spec: str, why: str) -> None:
    if not spec or spec == "none":
        return
    with _PAPERS_DOWN_LOCK:
        _PAPERS_DOWN[spec] = time.monotonic() + PAPERS_NEGATIVE_TTL_SEC
    sys.stderr.write(f"[bridge] F-24 검색 통로 {spec} 를 {PAPERS_NEGATIVE_TTL_SEC:.0f}초 쉬어요 ({why})\n")


def _papers_degraded(papers) -> str:
    """PaperDoc 이 폴백인가 → degraded 코드. 정상이면 "". 검색을 끈 것(none)·결과가 없던 것은 폴백이 아니다."""
    note = str(getattr(papers, "note", "") or "")
    if PAPERS_TIMEOUT_NOTE in note:
        return "papers_timeout"
    if PAPERS_RESTING_NOTE in note:
        return "papers_unavailable"
    if any(m in note for m in _PAPERS_FAIL_MARKS):
        return "papers_partial" if getattr(papers, "scholar_refs", None) else "papers_unavailable"
    return ""


def _deck_only_papers(graph_raw: dict, slidedoc, note: str):
    """검색 없이 자료가 인용한 문헌만 (scholar=none — LLM·네트워크 0). 이마저 안 되면 None."""
    from chuckchuck import build_papers

    try:
        doc = build_papers(graph_raw, slidedoc, scholar="none")
    except Exception as e:  # noqa: BLE001 — 폴백의 폴백. 없으면 문헌 없이 간다
        sys.stderr.write(f"[bridge] F-24 자료 인용 폴백 실패: {type(e).__name__}: {e}\n")
        return None
    doc.note = note
    return doc


def _claims_rule_only(claims, graph_raw, slidedoc) -> bool:
    """LLM 을 불렀어야 했는데 규칙 주장만 나왔나 (f26: LLM 이 죽으면 model='rule'). 노드·장이 없으면 원래 규칙뿐이다."""
    if claims is None or getattr(claims, "model", "") != "rule":
        return False
    return bool((graph_raw or {}).get("nodes")) and bool((slidedoc or {}).get("slides"))


#: 기억(F-25)을 못 읽었다는 표시. 「지난 리허설 없음」({}) 과 구분한다 — 예전엔 실패도 {} 로 6시간 담아 없던 일처럼 됐다.
MEMORY_FAILED_MARK = {"__memory_failed__": True}


def _memory_failed(sid: str) -> bool:
    return bool(sid) and STORE.get_triage("memory:" + sid) == MEMORY_FAILED_MARK


# ─── 외부 AI·검색 장애는 장애라고 말한다 (09-30 J25) ────────────────────────────────────────────────────

def _upstream_error(e: BaseException) -> tuple[int, dict] | None:
    """
    외부 LLM·검색 호출이 죽어서 난 예외 → (상태, 본문). 우리 코드의 버그면 None (500 으로 남긴다).

    09-30 실측(J25): 판정 중 LLM 게이트웨이가 읽기 타임아웃을 내면 requests.ReadTimeout·ConceptError 가 그대로 올라와
    500 「요청을 처리하지 못했어요」 가 됐다 — 서버 버그처럼 보이고, 잠깐 뒤 다시 하면 되는 일인지 알 길이 없었다.
    프론트(qaApi·buildQuestions·booth)는 상태와 무관하게 {error, message} 를 읽어 message 를 그대로 띄운다.
    벤더 응답 본문은 싣지 않는다 (stderr 에만) — ConceptError 문구에는 벤더 본문이 섞여 있다.
    """
    import requests

    from chuckchuck.contracts import ConceptError, PaperError

    seen: list[BaseException] = []
    x: BaseException | None = e
    while x is not None and len(seen) < 6 and x not in seen:
        seen.append(x)
        x = x.__cause__ or x.__context__
    if any(isinstance(x, (requests.Timeout, TimeoutError)) for x in seen):
        return 503, {"error": "upstream_timeout", "retry_after": 10,
                     "message": "AI 서버가 제시간에 답하지 않았어요. 잠시 뒤 다시 해 주세요."}
    if any(isinstance(x, requests.ConnectionError) for x in seen) or (
            isinstance(e, ConceptError) and "연결 실패" in str(e)):
        return 503, {"error": "upstream_unavailable", "retry_after": 10,
                     "message": "AI 서버에 연결하지 못했어요. 잠시 뒤 다시 해 주세요."}
    if isinstance(e, (ConceptError, PaperError, requests.RequestException)):
        return 502, {"error": "upstream_failed",
                     "message": "AI 서버가 오류로 답했어요. 잠시 뒤 다시 해 주세요."}
    return None


# ─── 개념·그래프 분석이 실패하거나 반쪽이면 무엇이 그런지 말한다 (09-30 WP-Q2) ──────────────────────────────────

#: F-06 이 장 개념을 너무 많이 못 받았을 때의 ConceptError 문구 (`f06_concepts._fill_missing`: 「F-06 이 4/12장의 개념을 돌려주지
#: 않았습니다 (장 [2, 5, 9, 11]).」). 문구가 바뀌면 tests/test_lines_q2.py 가 실제 F-06 으로 잡아 준다.
_CONCEPTS_MISSING_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*장의 개념을 돌려주지 않았")
_MISSING_SLIDES_RE = re.compile(r"장\s*\[([\d,\s]*)\]")
#: F-07 이 노드를 하나도 못 만들었을 때의 GraphError 문구 (`f07_graph.build_graph`, 09-30 G-A7) · 개념 문서에 장이 없을 때.
_GRAPH_EMPTY_RE = re.compile(r"노드를 하나도")
_GRAPH_NO_SLIDES_RE = re.compile(r"슬라이드가 없습니다")


def _analysis_failure(e: BaseException) -> tuple[int, dict] | None:
    """
    /concepts · /graph 의 분석 실패 → (상태, 본문). 외부 AI 지연·끊김(503)은 `_upstream_error` 그대로 — 여기는 **AI 가 답은 했는데
    분석이 안 된** 경우다. 09-30 WP-C 가 올린 두 실패(노드 0개 GraphError · 빠진 장이 많은 ConceptError)가 예전엔 500 「요청을
    처리하지 못했어요」·502 「AI 서버가 오류로 답했어요」 로만 보여서 무엇이 안 됐는지 알 수 없었다. 프론트(`extractConcepts`·
    `buildGraph`)는 상태와 무관하게 message 를 그대로 띄운다. 모르는 실패면 None — 일반 처리(`_upstream_error`·500)로 간다.
    """
    from chuckchuck.contracts import ConceptError, GraphError

    upstream = _upstream_error(e)
    if upstream is not None and upstream[0] == 503:
        return upstream
    msg = str(e)
    if isinstance(e, ConceptError):
        m = _CONCEPTS_MISSING_RE.search(msg)
        if m is None:
            return None
        sm = _MISSING_SLIDES_RE.search(msg)
        nos = [int(x) for x in re.findall(r"\d+", sm.group(1))] if sm else []
        where = f"({', '.join(str(x) for x in nos)}장)" if nos else ""
        return 502, {"error": "concepts_incomplete", "missing_slides": nos, "retry_after": 10,
                     "message": f"자료 {m.group(2)}장 가운데 {m.group(1)}장{where}의 개념을 AI 가 끝내 돌려주지 않아 분석을 멈췄어요. "
                                "잠시 뒤 다시 분석하면 채울 수 있어요."}
    if isinstance(e, GraphError):
        if _GRAPH_NO_SLIDES_RE.search(msg):
            return 400, {"error": "bad_request", "message": "개념 추출 결과에 장이 없어요. 자료를 다시 올리면 분석할 수 있어요."}
        if _GRAPH_EMPTY_RE.search(msg):
            return 502, {"error": "graph_empty", "retry_after": 10,
                         "message": "AI 가 자료에서 개념을 하나도 찾지 못해 개념 그래프를 만들지 못했어요. "
                                    "잠시 뒤 다시 분석하면 만들 수 있어요."}
        return 502, {"error": "graph_failed", "retry_after": 10,
                     "message": "AI 가 개념 그래프를 알아볼 수 있는 모양으로 돌려주지 않았어요. 잠시 뒤 다시 분석하면 만들 수 있어요."}
    return None


def _concepts_missing(concept_doc: dict) -> list[int]:
    """F-06 이 끝내 못 받은 장 번호 (`SlideConcepts.missing`, 4a7b750) — 조금이면 F-06 이 실패 대신 빈 개념으로 두고 표시만 한다."""
    return [int(s.get("slide_no") or 0) for s in (concept_doc or {}).get("slides") or []
            if isinstance(s, dict) and s.get("missing")]


def _analysis_response(payload: dict, degraded: list[str], **extra) -> dict:
    """분석 응답 — 반쪽이면 degraded·degraded_notes(와 extra)를 싣는다. 온전하면 **payload 그대로** (응답 모양·지문이 예전과 같다)."""
    if not degraded:
        return payload
    return {**_with_degraded(payload, degraded), **extra}


# ─── 판정의 채점 기준은 서버가 정한다 (09-30 R4·B-07·B-12) ─────────────────────────────────────────────

#: 서버에 없는 질문(클라이언트 본문)을 판정 프롬프트에 실을 때의 상한. 서버 질문의 대사 상한(QA_TEXT_MAX 200)보다 넉넉하다.
CLIENT_TEXT_MAX = 600
CLIENT_LIST_MAX = 12
#: Question → basis → probe → evidence[] → {quote} 가 다섯 겹이다. 그보다 깊은 것은 버린다.
CLIENT_DEPTH_MAX = 6


def _capped(value, depth: int = 0):
    """클라이언트가 보낸 JSON 을 판정 프롬프트에 실어도 되는 크기로 — 글자·목록·깊이를 자른다 (너무 깊은 것은 뺀다)."""
    if isinstance(value, str):
        return value[:CLIENT_TEXT_MAX]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if depth >= CLIENT_DEPTH_MAX:
        return None
    if isinstance(value, list):
        items = (_capped(v, depth + 1) for v in value[:CLIENT_LIST_MAX])
        return [v for v in items if v is not None]
    if isinstance(value, dict):
        return {str(k)[:64]: _capped(v, depth + 1) for k, v in list(value.items())[:40]}
    return str(value)[:CLIENT_TEXT_MAX]


#: 정적 파일 해시·gzip 기억 (demo/static_assets.py). 첫 화면 파일을 오래 캐시해도 옛 판이 안 남게 한다.
STATIC = AssetCache({"/": DEMO_DIR, "/sdk/": SDK_DIR})
CDN_HTML_CACHE = "max-age=60, stale-while-revalidate=86400"


def _minifier() -> Minifier:
    """
    공개 서비스(TUNNEL_HOSTNAME 이 있을 때)에서만 JS·CSS 주석·공백을 걷는다 — 개발 브리지(8800)는 원본 그대로라
    개발자 도구에서 읽기 쉽다. DEMO_MINIFY=1/0 으로 강제. 바이너리는 ESBUILD_BIN · tools/bin/esbuild · PATH 순
    (scripts/get_esbuild.sh 가 받는다). 없으면 원본을 보낸다.
    """
    flag = os.environ.get("DEMO_MINIFY", "").strip()
    on = flag == "1" or (flag != "0" and bool(os.environ.get("TUNNEL_HOSTNAME", "").strip()))
    if not on:
        return Minifier(None)
    cand = [os.environ.get("ESBUILD_BIN", "").strip(), str(ROOT / "tools" / "bin" / "esbuild"), shutil.which("esbuild") or ""]
    binary = next((c for c in cand if c and os.path.isfile(c) and os.access(c, os.X_OK)), None)
    if not binary:
        sys.stderr.write("[bridge] esbuild 가 없어 JS·CSS 를 줄이지 않고 보내요 — scripts/get_esbuild.sh\n")
    return Minifier(binary)


MINIFY = _minifier()



#: 주소창 경로 중 화면이 아닌 것 — API·로그인·SDK 모듈. 이 아래는 해시로 돌려보내지 않는다.
_NOT_SCREEN_PREFIXES = ("/api/", "/sdk/", "/auth")
#: 화면 주소로 받는 글자 — 앱 해시 주소는 영문·숫자·-·_ 마디뿐이다. %00 같은 이상한 주소는 예전처럼 404.
_SCREEN_PATH = re.compile(r"^(/[A-Za-z0-9_-]+)+$")


def hash_route_for(url_path: str, locate) -> str | None:
    """
    주소창 경로 → 앱 해시 주소(``#/booth/call``). 화면 주소가 아니면 None.

    파일(마지막 마디에 점이 있음)이나 실제로 있는 파일·폴더, API·로그인 경로는 그대로 둔다.
    대소문자는 앱 해시 규칙에 맞춰 소문자로 (주소창에 /test/QA 라고 쳐도 열리게). ``locate`` 는 STATIC.locate.
    """
    path = (url_path or "").rstrip("/")
    if not path or path == "/index.html":
        return None
    if any(path == p.rstrip("/") or path.startswith(p) for p in _NOT_SCREEN_PREFIXES):
        return None
    if not _SCREEN_PATH.match(path):
        return None
    if locate(url_path) is not None:
        return None
    return "#" + path.lower()

#: 화면 폴더에 같이 놓인 팀 문서 · 손으로 둔 파일은 공개 사이트에 내지 않는다 (10-02 서비스 플로우 정리안 — MVP_SPEC.md ·
#: UI_POLISH_TODO.md · UX_ITERATION_LOG.md · sample-deck.pdf 가 chuckchuck-present.com 에서 200 이었다). 지우지 않고 막기만 한다.
_STATIC_HIDDEN_SUFFIXES = {".md"}
_STATIC_HIDDEN_NAMES = {"sample-deck.pdf"}


def _static_hidden(path: Path) -> bool:
    return path.is_file() and (path.suffix.lower() in _STATIC_HIDDEN_SUFFIXES or path.name in _STATIC_HIDDEN_NAMES
                               or path.name.startswith("."))


class Handler(SimpleHTTPRequestHandler):
    # 큰 PDF 파싱 중에도 다른 요청(정적 파일)이 안 막히게
    protocol_version = "HTTP/1.1"
    #: recv·send 한 번의 시한 (StreamRequestHandler.setup 이 소켓에 건다). 없으면 응답을 안 읽는 연결이 스레드를 영원히 붙잡는다.
    timeout = SOCKET_TIMEOUT or None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DEMO_DIR), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def address_string(self) -> str:
        # 접근 로그에 127.0.0.1(Funnel) 대신 실제 방문자 IP — 공격 IP 를 로그에서 바로 찾게 (방패 2026-10-05)
        return getattr(self, "_client_ip", None) or super().address_string()

    def log_request(self, code="-", size="-") -> None:
        if getattr(self, "_quiet", False):
            return  # 방패가 막은 요청은 한 줄씩 남기지 않는다 — 홍수 중에 로그가 디스크를 채운다 (SHIELD_LOG 가 10초에 한 줄)
        super().log_request(code, size)

    def log_error(self, fmt: str, *args) -> None:
        if fmt.startswith("Request timed out"):
            SHIELD_LOG.write("timeout", "소켓 시한 초과로 연결을 닫았어요")
            return
        super().log_error(fmt, *args)

    # ── 연결 단계별 시한 (방패 2026-10-05) ──────────────────────────────────────
    # 요청 줄을 기다리는 동안 → 첫 요청은 HEADER_TIMEOUT, keep-alive 다음 요청은 KEEPALIVE_SEC.
    # 요청 줄이 오면(parse_request) → 머리글 전체가 HEADER_TIMEOUT 안에. _gate 에 닿으면 감시를 푼다 (본문은 do_POST 가 따로).

    def handle_one_request(self):
        first = not getattr(self, "_served", False)
        self._served = True
        self._req_gen = getattr(self, "_req_gen", 0) + 1
        self._quiet = False
        self._extra_headers = []
        self._client_ip = None
        self._reaped = None
        wait = HEADER_TIMEOUT if first else KEEPALIVE_SEC
        try:
            self.connection.settimeout(wait or None)
        except (OSError, AttributeError):
            pass
        WATCHDOG.watch(self, wait, "idle")
        try:
            return super().handle_one_request()
        finally:
            WATCHDOG.unwatch(self)

    def parse_request(self):
        try:
            self.connection.settimeout(SOCKET_TIMEOUT or None)
        except (OSError, AttributeError):
            pass
        WATCHDOG.watch(self, HEADER_TIMEOUT, "headers")
        return super().parse_request()

    def _read_body(self, length: int) -> bytes:
        """본문을 읽는다 — 크기에 맞춘 전체 시한을 건다 (한 바이트씩 흘려보내는 연결이 스레드를 붙잡지 않게)."""
        if length <= 0:
            return b""
        if MIN_BODY_KBPS > 0:
            WATCHDOG.watch(self, SOCKET_TIMEOUT + length / (MIN_BODY_KBPS * 1024), "body")
        try:
            return self.rfile.read(length)
        finally:
            WATCHDOG.unwatch(self)

    def _read_big_body(self, length: int) -> bytes | None:
        """1MB 넘는 공개 본문 — IP(칸)당 동시에 IP_UPLOADS 개까지만 받는다. 넘으면 읽지 않고 429 로 닫는다 (None)."""
        bucket = shield.ip_bucket(self._client_key())
        with _UPLOADS_LOCK:
            n = _UPLOADS.get(bucket, 0)
            if n >= IP_UPLOADS:
                full = True
            else:
                full = False
                _UPLOADS[bucket] = n + 1
        if full:
            EVENTS.add("upload_429")
            SHIELD_LOG.write("uploads", f"동시 업로드 상한 {IP_UPLOADS} — {bucket}")
            self._quiet = True
            self.close_connection = True
            self._add_header("Retry-After", "10")
            self._json(429, {"error": "rate_limited", "rate_limited": True, "scope": "uploads", "retry_after": 10,
                             "message": "올리는 중인 파일이 많아요. 10초 뒤에 다시 시도해 주세요."})
            return None
        try:
            return self._read_body(length)
        finally:
            with _UPLOADS_LOCK:
                left = _UPLOADS.get(bucket, 1) - 1
                if left > 0:
                    _UPLOADS[bucket] = left
                else:
                    _UPLOADS.pop(bucket, None)

    def _gate(self) -> bool:
        """
        모든 요청의 첫 관문. 통과 못 하면 응답을 보내고 False.

        ① Host 허용 목록 — 다른 사이트가 DNS rebinding 으로 브리지를 부르는 길을 막는다.
           DEMO_HOST 가 와일드카드(mock 모드에서만 가능)면 LAN IP 로 접속하므로 건너뛴다.
        ② DEMO_REQUIRE_ACCESS=1 이면 Cloudflare Access 헤더가 없는 요청을 정적 파일까지 403.
        """
        if getattr(self, "_reaped", None):
            # 감시(Watchdog)가 시한을 넘긴 연결을 끊었다 — 반쯤 받은 머리글로 요청을 처리하지 않는다
            self.close_connection = True
            return False
        WATCHDOG.unwatch(self)
        host = _host_name(self.headers.get("Host") or "")
        wildcard = settings.demo_host in ("0.0.0.0", "::", "")
        if host and not wildcard and host not in ALLOWED_HOSTS and host != settings.demo_host.lower():
            sys.stderr.write("[bridge] Host 거절 (허용 목록 밖)\n")
            self._json(403, {"error": "forbidden_host", "message": "이 주소로는 열 수 없어요."})
            return False
        if REQUIRE_ACCESS and not (self.headers.get("Cf-Access-Jwt-Assertion") or "").strip():
            self._json(403, {"error": "access_required", "message": "로그인한 뒤에 열 수 있어요."})
            return False
        _REQ.team = self._team_ok()
        self._local = shield.is_local_direct(self._peer(), self.headers)
        _REQ.trusted = _REQ.team or self._local
        try:
            return self._shield_gate()
        except OSError:
            # 막는 답을 쓰다 상대가 끊었다 — 통과가 아니라 끝이다
            self.close_connection = True
            return False
        except Exception as e:  # noqa: BLE001 — 방패의 버그로 사이트가 멈추면 안 된다. 열어 두고(fail-open) 알린다
            if getattr(self, "_quiet", False):
                return False  # 이미 막는 답을 쓰기 시작했다 — 통과시키면 막힌 요청이 처리된다
            SHIELD_LOG.write("shield_error", f"방패 오류 — 이번 요청은 통과시킴: {e!r}")
            return True

    # ── 방패 첫 줄 (2026-10-05) ────────────────────────────────────────────────
    # 차단 목록 → 감옥 → 전체 홍수 제한 → 원본 잠금. 팀 쿠키·VM 안 요청은 건너뛴다. 막으면 본문을 읽지 않고 짧게 답한다.

    def _peer(self) -> str:
        try:
            return str(self.client_address[0])
        except Exception:  # noqa: BLE001
            return ""

    def _shield_gate(self) -> bool:
        if not self._local:
            self._note_edge()
        if _REQ.trusted:
            return True
        ip = self._client_key()
        bucket = shield.ip_bucket(ip)
        path = urlparse(self.path).path
        if BLOCKLIST.blocked(ip):
            EVENTS.add("blocked")
            SHIELD_LOG.write("blocked", f"차단 목록 {ip} {self.command} {path[:80]}")
            return self._shield_reply(403, {"error": "forbidden"})
        counted = self._counted()
        left = JAIL.remaining(bucket) if counted else 0
        if left:
            EVENTS.add("jailed")
            return self._shield_reply(429, {"error": "banned", "rate_limited": True, "retry_after": left,
                                            "message": f"요청이 너무 많아 잠시 막았어요. {left}초 뒤에 다시 시도해 주세요."},
                                      retry_after=left)
        if counted and not FLOOD.allow(bucket):
            wait = FLOOD.retry_after(bucket)
            EVENTS.add("flood_429")
            self._strike(bucket)
            SHIELD_LOG.write("flood", f"홍수 제한 {bucket} (분당 {IP_RPM}) {self.command} {path[:80]}")
            return self._shield_reply(429, {"error": "rate_limited", "rate_limited": True, "scope": "flood",
                                            "retry_after": wait,
                                            "message": f"요청이 너무 잦아요. {wait}초 뒤에 다시 시도해 주세요."},
                                      retry_after=wait)
        if EDGE_LOCK and not shield.edge_ok(self.headers, EDGE_SECRET) and path.rstrip("/") not in EDGE_LOCK_OPEN:
            EVENTS.add("edge_locked")
            SHIELD_LOG.write("edge_lock", f"원본 잠금 — 비밀 머리글 없는 요청 {ip} {self.command} {path[:80]}")
            return self._shield_reply(403, {"error": "forbidden"})
        return True

    def _counted(self) -> bool:
        """
        이 요청의 IP 칸을 홍수 제한·IP 천장에 세도 되나. Cloudflare 서버·설비 IP 는 여러 사람이 섞인 칸이라 안 센다
        (세면 그 뒤의 방문자 전원이 같이 막힌다). 단 비밀을 정했는데 비밀 없이 Cloudflare 주소에서 온 것(`xff`)은
        WARP·Worker 로 ts.net 에 바로 온 것이라 그 출구 IP 를 센다.
        """
        ip = self._client_key()
        if shield.attributable(ip):
            return True
        return bool(EDGE_SECRET) and getattr(self, "_client_via", "") == "xff" and shield.parse_ip(ip) not in shield.INFRA_NETS

    def _strike(self, bucket: str) -> None:
        """막힌 요청 하나 = 위반 하나. 쌓이면 감옥 (shield.Jail).

        `cf`·`legacy` 로 센 칸(CF-Connecting-IP 를 믿은 칸)은 가두지 않는다 — 비밀이 없으면 WARP 로 ts.net 에 와서 그 값을
        행사장 IP 로 꾸며 행사장을 가두게 할 수 있다. 분당 상한(429)은 그대로 건다. 비밀을 정하면(`edge`) 감옥도 켜진다."""
        if getattr(self, "_client_via", "") in ("cf", "legacy"):
            return
        if JAIL.strike(bucket):
            EVENTS.add("ban")
            SHIELD_LOG.write("ban", f"감옥 {bucket} {JAIL.ban_sec:.0f}초 — 막혀도 계속 두드림 "
                                    f"({JAIL.window:.0f}초에 {BAN_STRIKES}번)")

    def _note_edge(self) -> None:
        """도메인·ts.net 요청이 어떤 길로 왔는지 센다 — 배포 뒤 /api/v1/ops/shield 로 Funnel 동작을 눈으로 확인하는 자리."""
        self._client_key()
        via = getattr(self, "_client_via", "?")
        EVENTS.add("via_" + via)
        EDGE_SAMPLES.append({
            "at": round(time.time(), 1), "via": via, "client": self._client_ip,
            "xff_last": shield.last_hop(self.headers.get("X-Forwarded-For") or "")[:64],
            "cf_ip": bool((self.headers.get("CF-Connecting-IP") or "").strip()),
            "edge_auth": ("ok" if shield.edge_ok(self.headers, EDGE_SECRET)
                          else "bad" if (self.headers.get("X-Edge-Auth") or "").strip() else "none"),
            "funnel": bool(self.headers.get("Tailscale-Funnel-Request")),
            "host": _host_name(self.headers.get("Host") or "")[:80],
        })

    def _add_header(self, k: str, v: str) -> None:
        if getattr(self, "_extra_headers", None) is None:
            self._extra_headers = []
        self._extra_headers.append((k, v))

    def _shield_reply(self, code: int, payload: dict, retry_after: int | None = None) -> bool:
        """방패가 막은 요청의 짧은 답. 접근 로그를 남기지 않고, 작은 본문만 비워 읽고(큰 건 그냥) 연결을 닫는다."""
        self._quiet = True
        if retry_after:
            self._add_header("Retry-After", str(int(retry_after)))
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if 0 < n <= 64 * 1024:
                self._read_body(n)  # 안 읽고 닫으면 커널이 RST 를 보내 상대가 답 대신 연결 오류를 본다
        except (ValueError, OSError):
            pass
        self.close_connection = True
        try:
            self._json(code, payload)
        except OSError:
            pass  # 상대가 이미 끊었다 — 그래도 막은 것이다 (False)
        return False

    # ── 팀 인증 (/auth) ─────────────────────────────────────────────────────────
    # 공개 사이트(chuckchuck-present.com)는 로그인 없이 누구나 자기 자료로 쓴다. 팀이 쓰는 개발용 경로만
    # 이 쿠키 뒤에 둔다. 코드는 .env 의 DEMO_TEAM_CODE — 비어 있으면 /auth 가 404 다.

    def _cookie(self, name: str) -> str:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v.strip()
        return ""

    def _team_ok(self) -> bool:
        tok = self._cookie(TEAM_COOKIE)
        # 바이트로 비교한다 — str 끼리면 ASCII 가 아닌 쿠키 값에서 TypeError 가 나 요청이 방패 앞에서 터진다
        return bool(TEAM_CODE and tok) and hmac.compare_digest(tok.encode("utf-8", "replace"), _team_token().encode("ascii"))

    def _https(self) -> bool:
        """터널 뒤면 Cloudflare 가 붙인 헤더로 안다 — 로컬 http 에서 Secure 쿠키는 안 남는다."""
        return "https" in (self.headers.get("Cf-Visitor") or "") or \
            (self.headers.get("X-Forwarded-Proto") or "").lower() == "https"

    def _auth_page(self, code: int, *, team: bool, note: str = "", cookie: str | None = None):
        esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
        if team:
            body = """<p class="ok">개발자 모드가 켜져 있어요. 이 브라우저에서 베타 화면이 열려요.</p>
<ul><li><a href="/index.html#/vision">#/vision — 얼굴과 삐약이를 보며 발표하는 비전 리허설</a></li>
<li><a href="/index.html#/temp">#/temp — 통화 배치로 도는 전체 흐름</a></li>
<li><a href="/index.html#/test/qa">#/test/qa — ppt/ 덱으로 질문 코칭</a></li>
<li><a href="/index.html#/replay">#/replay — 저장된 세션 다시 보기</a></li>
<li><a href="/index.html#/">홈 — 샘플 발표·샘플 리포트가 보여요</a></li></ul>
<form method="post" action="/auth"><input type="hidden" name="logout" value="1"><button class="ghost">개발자 모드 끄기</button></form>"""
        else:
            body = f"""<form method="post" action="/auth">
<label for="code">팀 코드</label>
<input id="code" name="code" type="password" autocomplete="current-password" autofocus required>
<button>개발자 모드 켜기</button></form>{f'<p class="err">{esc(note)}</p>' if note else ''}"""
        html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>개발자 모드 · 척척발표</title><style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f5f1;color:#1d1d1b;
font-family:"Pretendard",system-ui,-apple-system,"Apple SD Gothic Neo",sans-serif}}
main{{width:min(360px,calc(100vw - 32px));background:#fff;border-radius:16px;padding:28px 24px;box-shadow:0 6px 24px #0000000f}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{margin:0 0 20px;color:#6b6b66;font-size:14px}}
label{{display:block;font-size:13px;color:#6b6b66;margin-bottom:6px}}
input{{width:100%;box-sizing:border-box;font-size:16px;padding:12px;border:1px solid #d9d7d0;border-radius:10px}}
button{{margin-top:12px;width:100%;padding:12px;font-size:15px;font-weight:600;border:0;border-radius:10px;background:#0f8a55;color:#fff;cursor:pointer}}
button.ghost{{background:#eeede8;color:#1d1d1b}} .err{{color:#c0392b;font-size:14px}} .ok{{color:#0f8a55}}
ul{{padding-left:18px;line-height:1.9}} a{{color:#0f8a55}}
</style></head><body><main><h1>개발자 모드</h1><p class="sub">척척발표 팀이 쓰는 베타 화면을 여는 곳이에요.</p>
{body}</main></body></html>""".encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.send_header("X-Robots-Tag", "noindex")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(html)

    def _team_cookie(self, value: str, max_age: int) -> str:
        return (f"{TEAM_COOKIE}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"
                + ("; Secure" if self._https() else ""))

    def _handle_auth_get(self):
        if not TEAM_CODE:
            return self._json(404, {"error": "not found"})
        return self._auth_page(200, team=self._team_ok())

    def _handle_auth_post(self, raw: bytes):
        if not TEAM_CODE:
            return self._json(404, {"error": "not found"})
        form = parse_qs(raw.decode("utf-8", "replace"))
        if (form.get("logout") or [""])[0]:
            return self._auth_page(200, team=False, note="개발자 모드를 껐어요.", cookie=self._team_cookie("", 0))
        key = self._client_key()
        if not AUTH_LIMITER.allow(key):
            wait = AUTH_LIMITER.retry_after(key)
            return self._auth_page(429, team=False, note=f"너무 많이 시도했어요. {wait}초 뒤에 다시 해 주세요.")
        code = (form.get("code") or [""])[0].strip()
        if not hmac.compare_digest(code.encode("utf-8"), TEAM_CODE.encode("utf-8")):
            sys.stderr.write("[bridge] /auth 실패\n")
            return self._auth_page(401, team=False, note="코드가 맞지 않아요.")
        sys.stderr.write("[bridge] /auth 성공\n")
        return self._auth_page(200, team=True, cookie=self._team_cookie(_team_token(), TEAM_COOKIE_MAX_AGE))

    def _handle_ops_shield(self):
        """
        GET /api/v1/ops/shield — 방패 상태 (팀 쿠키 또는 이 VM 안에서만. 나머지는 404 — 있다는 것도 알리지 않는다).

        부스 중에 「지금 막히는 게 있나」 를 한눈에 본다: 과금 동시 실행·대기, 최근 5분 429·503, 감옥, 차단 목록,
        점검 깃발, 시간당 사용량, 연결 수, 그리고 최근 공개 요청이 어느 길(via)로 왔는지. VM 에서는
        `curl -s http://127.0.0.1:8799/api/v1/ops/shield | python3 -m json.tool`.
        """
        if not getattr(_REQ, "trusted", False):
            return self._json(404, {"error": "not found"})
        srv = getattr(self, "server", None)
        return self._json(200, {
            "at": round(time.time(), 1),
            "paid": {**GATE.snapshot(), "queue_sec": PAID_QUEUE_SEC, "retry_sec": PAID_RETRY_SEC},
            "spend": {"per_hour_limit": PAID_PER_HOUR, "public_last_hour": SPEND.count("public"),
                      "exempt": sorted(SPEND_EXEMPT)},
            "recent_5min": EVENTS.recent(300),
            "totals": dict(EVENTS.totals),
            "bans": {"active": JAIL.active(), "count": len(JAIL), "total": JAIL.total_bans,
                     "strikes": BAN_STRIKES, "window_sec": JAIL.window, "ban_sec": JAIL.ban_sec},
            "blocklist": {"file": str(BLOCKLIST.path), "entries": len(BLOCKLIST)},
            "lockdown": {"on": LOCKDOWN.on(), "file": str(LOCKDOWN.path)},
            "edge": {"secret_set": bool(EDGE_SECRET), "lock": EDGE_LOCK, "recent": list(EDGE_SAMPLES)},
            "flood": {"ip_rpm": IP_RPM, "keys": len(FLOOD)},
            "limiter_keys": {"paid_session": len(LIMITER.session), "paid_ip": len(LIMITER.ip)}
            if isinstance(LIMITER, PaidLimiter) else {},
            "connections": {
                "active": getattr(srv, "active_connections", None), "peak": getattr(srv, "peak_connections", None),
                "refused": getattr(srv, "refused_connections", None), "max": MAX_CONNECTIONS,
                "watched": len(WATCHDOG), "reaped": WATCHDOG.reaped, "reaped_by_phase": dict(WATCHDOG.reaped_by_phase),
                "timeouts": {"socket": SOCKET_TIMEOUT, "keepalive": KEEPALIVE_SEC, "header": HEADER_TIMEOUT,
                             "min_body_kbps": MIN_BODY_KBPS},
            },
        })

    def list_directory(self, path):  # noqa: D102 — 정적 서빙의 디렉터리 목록은 끈다 (MVP_SPEC·로그·실측 JSON 이 보였다)
        self.send_error(404)
        return None

    def do_GET(self):
        if not self._gate():
            return
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                return self._json(200, {"ok": True, "mock": _mock()})
            if parsed.path.rstrip("/") == "/auth":
                return self._handle_auth_get()
            if parsed.path == "/api/v1/team":
                return self._json(200, {"team": _dev_open()})
            if parsed.path == "/api/v1/ops/shield":
                return self._handle_ops_shield()
            if parsed.path == "/api/v1/cached-slidedoc":
                return self._handle_cached_slidedoc(parsed)
            if parsed.path == "/api/v1/cached-transcript":
                return self._handle_cached_transcript(parsed)
            if parsed.path == "/api/v1/cached-takes":
                return self._handle_cached_takes()
            if parsed.path == "/api/v1/preview-pdf":
                return self._handle_preview_pdf(parsed)
            if parsed.path == "/api/v1/dev/decks":
                return self._handle_dev_decks()
            if parsed.path == "/api/v1/dev/decks/file":
                return self._handle_dev_deck_file(parsed)
            if parsed.path == "/api/v1/dev/questions":
                return self._handle_dev_questions(parsed)
            # 주소창의 화면 주소(/booth/call · /test/QA · /temp …)는 앱의 해시 주소로 자동으로 돌려보낸다 — 앱이 해시 라우팅이라.
            # 예전엔 고정 표(/test/qa · /temp · /vision · /booth/qa)라 새 화면을 만들 때마다 여기를 고치고 8799 를 재시작해야 했고,
            # 그걸 빠뜨리면 404 가 났다 (2026-10-01 /booth/call). 이제 파일이 아닌 주소면 다 해시로 간다 — 앱이 모르는 화면은 홈이 그린다.
            hash_route = hash_route_for(parsed.path, STATIC.locate)
            if hash_route:
                self.send_response(302)
                self.send_header("Location", "/index.html" + hash_route)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            return self._serve_static(parsed)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            try:
                self._json(500, {"error": "internal", "message": "GET failed"})
            except Exception:  # noqa: BLE001
                return

    def do_HEAD(self):
        if not self._gate():
            return
        try:
            parsed = urlparse(self.path)
            return self._serve_static(parsed, head_only=True)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception:  # noqa: BLE001 — HEAD 도 GET 처럼 연결을 끊지 않고 500 으로 답한다
            traceback.print_exc()
            try:
                self.send_error(500)
            except Exception:  # noqa: BLE001
                return

    def do_POST(self):
        parsed = urlparse(self.path)
        if not self._gate():
            return
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length < 0:
                return self._json(400, {"error": "bad content-length"})
            limit = _body_limit(parsed.path)
            if length > limit:
                return self._json(413, {
                    "error": "too_large",
                    "message": f"최대 {limit // (1024 * 1024)}MB까지 보낼 수 있어요.",
                })
            # JSON 경로는 Content-Type 이 application/json 이어야 한다. 그래야 다른 사이트가 보낸
            # 교차 출처 요청에 preflight 가 붙어 막힌다 (text/plain·form 은 preflight 없이 날아온다).
            # 자료 업로드(/parse)만 multipart 를 받는다.
            ctype = (self.headers.get("Content-Type") or "").lower()
            # /auth 는 HTML 폼이라 JSON 이 아니다. 교차 출처 폼 제출로 할 수 있는 건 코드 맞히기뿐이고
            # 그건 AUTH_LIMITER 가 막는다 (쿠키는 SameSite=Lax 라 남의 사이트에서 로그인시켜도 쓸모가 없다).
            if parsed.path.rstrip("/") == "/auth":
                return self._handle_auth_post(self._read_body(min(length, 4096)))
            if parsed.path != "/api/v1/parse" and "application/json" not in ctype:
                return self._json(415, {"error": "json_required", "message": "Content-Type: application/json 으로 보내 주세요."})
            if length > BIG_BODY_BYTES and not getattr(_REQ, "trusted", False) and IP_UPLOADS > 0:
                raw = self._read_big_body(length)
                if raw is None:
                    return None
            else:
                raw = self._read_body(length)
            if getattr(self, "_reaped", None):
                return None  # 본문이 시한 안에 다 오지 않았다 — 감시가 이미 연결을 끊었다

            # 과금 경로는 점검 깃발 → 세션/IP 분당 상한 → 동시 실행 칸 → 시간당 천장을 거친다 (_handle_paid).
            # 본문을 다 읽은 뒤에 막는다 — 안 읽고 끊으면 클라이언트가 응답 대신 연결 오류를 본다.
            if _paid_path(parsed.path):
                return self._handle_paid(parsed, raw)
            return self._route_post(parsed, raw)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            sys.stderr.write(f"[bridge] client disconnected during {parsed.path}\n")
            return
        except Exception as e:  # noqa: BLE001 — 데모 브리지
            return self._post_failed(parsed, e)

    def _handle_paid(self, parsed, raw: bytes):
        """
        과금 경로의 관문 (방패 2026-10-05). 순서가 중요하다 — 싼 검사부터, 돈이 나가는 건 마지막에.

        ① 점검 깃발(var/lockdown) — 공개 요청은 503 maintenance. 팀·VM 안 요청은 통과.
        ② 세션/IP 분당 상한(PaidLimiter, 예전 그대로) — 429. 위반은 감옥 점수로도 센다.
        ③ 동시 실행 칸(GATE) — PAID_QUEUE_SEC 기다려도 안 나면 503 busy. 팀은 예약 칸까지 쓴다.
        ④ 공개 요청의 시간당 천장(SPEND) — 503 budget_exceeded. 칸을 얻은 뒤에 세서, 실제로 도는 호출만 센다.
        칸은 **어떤 예외가 나도** finally 에서 돌려준다 — 새면 칸이 하나씩 줄어 결국 모두가 busy 를 본다.
        """
        trusted = bool(getattr(_REQ, "trusted", False))
        if not trusted and LOCKDOWN.on():
            EVENTS.add("lockdown_503")
            SHIELD_LOG.write("lockdown", f"점검 깃발({LOCKDOWN.path.name}) — 공개 과금 요청을 503 으로 돌려보냄 {parsed.path}")
            self._add_header("Retry-After", "60")
            return self._json(503, {"error": "maintenance", "maintenance": True, "retry_after": 60,
                                    "message": "지금 잠시 점검 중이에요. 조금 뒤에 다시 시도해 주세요."})
        limited = self._rate_limited(parsed.path, raw)
        if limited is not None:
            EVENTS.add("paid_429")
            self._add_header("Retry-After", str(limited.get("retry_after") or 1))
            return self._json(429, limited)
        ok, waited = GATE.acquire(trusted, PAID_QUEUE_SEC)
        if not ok:
            EVENTS.add("busy_503")
            snap = GATE.snapshot()
            SHIELD_LOG.write("busy", f"동시 실행 칸이 다 찼어요 ({snap['inflight']}/{snap['capacity']}, 팀 몫 {snap['reserved_team']}) "
                                     f"→ 503 busy {parsed.path}")
            return self._busy_reply()
        try:
            if waited >= 0.05:
                EVENTS.add("queued")
            if not trusted and PAID_PER_HOUR > 0 and parsed.path not in SPEND_EXEMPT and not SPEND.allow("public"):
                wait = max(60, SPEND.retry_after("public"))
                EVENTS.add("budget_503")
                SHIELD_LOG.write("budget", f"시간당 천장 {PAID_PER_HOUR}회 도달 — 공개 과금 요청을 503 으로 돌려보냄 {parsed.path}")
                self._add_header("Retry-After", str(wait))
                return self._json(503, {"error": "budget_exceeded", "busy": True, "retry_after": wait,
                                        "message": f"지금 이용이 많아 잠시 쉬어 가요. {-(-wait // 60)}분쯤 뒤에 다시 시도해 주세요."})
            EVENTS.add("paid_ok")
            return self._route_post(parsed, raw)
        finally:
            GATE.release(trusted)

    def _busy_reply(self):
        """동시 실행 칸이 다 찼을 때. rate_limited=True 를 같이 실어 프론트의 판정 재시도(judgeRetryPlan)가 그대로 기다렸다
        다시 보내고, 「넘긴 질문」 으로 세지 않게 한다 (liveJudgeFailure). 다른 화면은 message 를 그대로 띄운다."""
        n = PAID_RETRY_SEC
        self._add_header("Retry-After", str(n))
        return self._json(503, {"error": "busy", "busy": True, "rate_limited": True, "scope": "busy", "retry_after": n,
                                "message": f"지금 사용자가 많아요. {n}초 뒤에 다시 시도해 주세요."})

    def _route_post(self, parsed, raw: bytes):
        """POST 경로 → 핸들러. 관문(do_POST·_handle_paid)을 다 지난 요청만 온다."""
        if parsed.path == "/api/v1/session/artifacts":
            return self._handle_session_artifacts(raw)
        if parsed.path.endswith("/feedback") and parsed.path.startswith("/api/v1/sessions/"):
            return self._handle_feedback(parsed.path, raw)
        if parsed.path == "/api/v1/parse":
            return self._handle_parse(raw)
        if parsed.path == "/api/v1/suggest-context":
            return self._handle_suggest_context(raw)
        if parsed.path == "/api/v1/deck-gaps":
            return self._handle_deck_gaps(raw)
        if parsed.path == "/api/v1/concepts":
            return self._handle_concepts(raw)
        if parsed.path == "/api/v1/transcribe":
            return self._handle_transcribe(raw)
        if parsed.path == "/api/v1/graph":
            return self._handle_graph(raw)
        if parsed.path == "/api/v1/alignment":
            return self._handle_alignment(raw)
        if parsed.path == "/api/v1/flow":
            return self._handle_flow(raw)
        if parsed.path == "/api/v1/chatter":
            return self._handle_chatter(raw)
        if parsed.path == "/api/v1/score":
            return self._handle_score(raw)
        if parsed.path == "/api/v1/rubric":
            return self._handle_rubric(raw)
        if parsed.path == "/api/v1/pace":
            return self._handle_pace(raw)
        if parsed.path == "/api/v1/habits":
            return self._handle_habits(raw)
        if parsed.path == "/api/v1/report":
            return self._handle_report(raw)
        if parsed.path == "/api/v1/questions":
            return self._handle_questions(raw)
        if parsed.path == "/api/v1/memory":
            return self._handle_memory(raw)
        if parsed.path == "/api/v1/papers":
            return self._handle_papers(raw)
        if parsed.path == "/api/v1/papers/search":
            return self._handle_papers_search(raw)
        if parsed.path == "/api/v1/claims":
            return self._handle_claims(raw)
        if parsed.path == "/api/v1/strategy":
            return self._handle_strategy(raw)
        # F-09: /api/v1/sessions/{id}/qa/judge — 채점 기준은 서버가 만든 질문, 없으면 body.question (표시를 달고)
        if parsed.path.endswith("/qa/judge") and "/api/v1/sessions/" in parsed.path:
            return self._handle_qa_judge(raw, path_sid=self._path_segment_after(parsed.path, "sessions"))
        if parsed.path == "/api/v1/qa/judge":
            return self._handle_qa_judge(raw)
        return self._json(404, {"error": "not found"})

    def _post_failed(self, parsed, e: Exception):
        # 상세(벤더 응답 본문·서버 경로)는 stderr 에만. 응답에는 사용자가 고칠 수 있는 사실만 싣는다.
        traceback.print_exc()
        # 외부 AI·검색이 죽은 것은 우리 버그(500)가 아니라 「잠시 뒤 다시」 다 — 502/503 으로 가른다 (J25)
        upstream = _upstream_error(e)
        try:
            if upstream is not None:
                sys.stderr.write(f"[bridge] {parsed.path} 외부 호출 실패 → {upstream[0]} {upstream[1]['error']}\n")
                self._json(*upstream)
            else:
                self._json(500, {"error": type(e).__name__, "message": _public_message(e)})
        except Exception:  # noqa: BLE001
            return

    @staticmethod
    def _query_session_id(parsed) -> str:
        from urllib.parse import parse_qs

        qs = parse_qs(parsed.query or "")
        return ARCHIVE.safe_id((qs.get("session_id") or [""])[0]) or ""

    def _handle_cached_slidedoc(self, parsed):
        """세션에 남긴 파싱본 (재파싱 없이 발표 화면 복구). session_id 가 곧 열쇠다.

        **최신본으로 대체하지 않는다.** 예전에는 이름을 못 찾으면 가장 최근 업로드를
        줬는데, 그게 남의 발표자료였다. 없으면 없다고 한다."""
        sid = self._query_session_id(parsed)
        doc = ARCHIVE.read_artifact(sid, "slide_doc") if sid else None
        if doc is None:
            return self._json(404, {"error": "no_cache", "message": "저장된 자료 파싱본이 없어요. 자료를 다시 올리면 돼요."})
        return self._json(200, doc)

    def _handle_cached_transcript(self, parsed):
        """세션에 남긴 받아쓰기 (재녹음·재과금 없이 이어서). 규칙은 위와 같다."""
        sid = self._query_session_id(parsed)
        doc = ARCHIVE.read_artifact(sid, "transcript") if sid else None
        if doc is None:
            return self._json(404, {"error": "no_cache", "message": "저장된 받아쓰기가 없어요. 한 번은 실제로 말해야 남아요."})
        sys.stderr.write(f"[bridge] Transcript 캐시 사용 {sid}\n")
        return self._json(200, doc)

    def _handle_cached_takes(self):
        """
        저장된 세션 목록. #/replay 가 「무엇으로 이어갈 수 있나」를 그리는 재료다.

        **개발자용이라 DEMO_DEV_ROUTES=1 일 때만 연다.** 목록은 곧 남의 발표 기록이다.
        """
        if not _dev_open():
            return self._json(404, {"error": "not found"})
        return self._json(200, {"takes": ARCHIVE.list_sessions()})

    # ── #/test/qa — ppt/ 폴더의 덱을 골라 질문 코칭까지 바로 (개발용) ──────────
    #
    # 왜: 발표자료 하나를 QA 까지 태우려면 업로드 → 발표 정보 → 녹음(또는 녹음 업로드) → 분석을
    # 손으로 거쳐야 했다. 팀이 모델을 자주 돌려보게 ppt/<덱>/ 을 목록으로 보여 주고 한 번에 태운다.
    # 파싱·분석은 화면과 **같은 경로**(/api/v1/parse 등)를 그대로 탄다 — 여기서는 파일만 내려준다.
    # cached-takes 와 같은 이유로 DEMO_DEV_ROUTES=1 일 때만 연다: 목록은 곧 이 서버의 로컬 파일이고,
    # 클릭 한 번이 실 API 과금이다.

    @staticmethod
    def _deck_entries() -> list[dict]:
        """ppt/ 아래 폴더(또는 낱개 pptx·pdf)마다 한 줄. 이름순."""
        rows: list[dict] = []
        if not DECKS_DIR.is_dir():
            return rows
        for entry in sorted(DECKS_DIR.iterdir(), key=lambda q: q.name):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                files = sorted(q for q in entry.iterdir() if q.is_file())
                deck = next((q for q in files if q.suffix.lower() in DECK_EXTS), None)
                audio = next((q for q in files if q.suffix.lower() in DECK_AUDIO_EXTS), None)
            elif entry.suffix.lower() in DECK_EXTS:
                deck, audio = entry, None
            else:
                continue
            if deck is None:
                continue
            row = {
                # macOS 에서 온 폴더 이름은 자모가 풀린 NFD 다 — 화면용 이름만 모아 쓴다 (key 는 파일시스템 그대로)
                "name": unicodedata.normalize("NFC", entry.stem if entry.is_file() else entry.name),
                "key": entry.name,
                "deck": deck.name, "deck_bytes": deck.stat().st_size,
                "audio": audio.name if audio else None,
                "audio_bytes": audio.stat().st_size if audio else 0,
                # 길이는 브라우저가 재는데, 헤드리스 크로미움은 AAC(m4a) 를 못 읽는다 — ffprobe 가 있으면 여기서 잰다
                "audio_sec": _probe_audio_sec(audio) if audio else 0,
                "cached_session_id": None,
            }
            # 오디오 없이 클로바 전사(.txt)만 있으면 그걸 녹음처럼 쓴다 — 받을 땐 표식 박힌 무음 WAV,
            # /transcribe 가 그 표식을 보면 STT 대신 전사로 Transcript 를 만든다 (demo/clova_transcript.py).
            if audio is None and entry.is_dir():
                clova = clova_transcript.find_clova_txt(files)
                if clova is not None:
                    row["audio"] = clova.stem + " (전사).wav"
                    row["audio_sec"] = clova_transcript.duration_of(clova)
                    row["audio_bytes"] = int(row["audio_sec"] * 8000)
                    row["clova_txt"] = clova.name
            try:
                sha = hashlib.sha256(deck.read_bytes()).hexdigest()
                row["cached_session_id"] = ARCHIVE.find_by_sha256(sha)
            except OSError:
                pass
            rows.append(row)
        return rows

    def _handle_dev_questions(self, parsed):
        """
        ?session_id=<id>&id=<질문 id> → 이 세션에서 서버가 만든 그 질문의 **채점 기준 사본**(함정의 전제·사실·골자 포함), 트랙마다.

        화면 사본(`client_questions`)은 함정의 사실 칸을 뺀다 (09-30 WP-J2) — 검증 하네스(labs/qa_verify)는 이 사본으로 함정 페르소나
        (전제 동의·정정 답)와 사실 누설 태그를 짓는다. 곧 정답지라 **DEMO_DEV_ROUTES=1 로 띄운 브리지에서만** 연다(팀 브라우저 /auth 로도
        안 연다 — 부스 기기가 팀 인증을 거쳤어도 참가자가 정답을 못 꺼내게).
        """
        if not DEV_ROUTES:
            return self._json(404, {"error": "not found"})
        qs = parse_qs(parsed.query)
        sid = _store_sid((qs.get("session_id") or [""])[0])
        qid = (qs.get("id") or [""])[0]
        if not sid or not qid:
            return self._json(400, {"error": "bad_request", "message": "session_id 와 id 가 필요합니다."})
        return self._json(200, {"session_id": sid, "id": qid, "questions": STORE.find_questions(sid, qid)})

    @staticmethod
    def _deck_manifest() -> dict:
        """
        ppt/decks.json — #/test/qa 목록의 묶음·이름표. 폴더 이름은 부스 화면·검증 도구가 키로 쓰니 바꾸지 않고
        보이는 이름만 여기서 단다 (2026-10-01: 「급속충전배터리열화A」 만으로는 어떤 발표 버전인지 안 보였다).
        없거나 깨졌으면 빈 설명서 — 목록은 예전처럼 폴더 이름으로 뜬다.
        """
        try:
            data = json.loads((DECKS_DIR / "decks.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"groups": [], "decks": {}}
        groups = [g for g in (data.get("groups") or []) if isinstance(g, dict) and g.get("id")]
        decks = {unicodedata.normalize("NFC", str(k)): v for k, v in (data.get("decks") or {}).items() if isinstance(v, dict)}
        return {"groups": groups, "decks": decks}

    def _public_deck(self, key: str, manifest: dict | None = None) -> bool:
        """
        팀 인증 없이 내주는 덱인가 — 부스 시연 세트(ppt/decks.json 의 group "booth")만. 발표 리허설(#/rehearsal)은 공개 화면이라
        (10-04 사용자: 「rehearsal 은 auth 제외」) 그 덱 셋과 녹음을 쓰게 한다. 검증용 보류 덱 · 데모 덱 · 목록 경로는 그대로 팀 뒤다.
        """
        manifest = manifest or self._deck_manifest()
        meta = manifest["decks"].get(unicodedata.normalize("NFC", key or ""), {})
        return meta.get("group") == "booth"

    def _handle_dev_decks(self):
        manifest = self._deck_manifest()
        team = _dev_open()
        rows = self._deck_entries()
        if not team:
            rows = [r for r in rows if self._public_deck(r["key"], manifest)]
        for row in rows:
            meta = manifest["decks"].get(unicodedata.normalize("NFC", row["key"]), {})
            row["group"] = str(meta.get("group") or ("held" if row["key"].startswith("_") else "other"))
            row["title"] = str(meta.get("title") or row["name"])
            row["version"] = str(meta.get("version") or "")
            row["order"] = meta.get("order") if isinstance(meta.get("order"), (int, float)) else 999
            # 같은 자료를 여러 버전으로 발표한 덱 — 화면이 한 카드로 묶는다 (부스 세트 A-1·A-2 …)
            for key in ("topic", "topic_title", "label"):
                if meta.get(key):
                    row[key] = str(meta[key])
        if not team:   # 공개 응답엔 서버 경로 · 다른 묶음 이름을 싣지 않는다
            return self._json(200, {"decks": rows, "groups": [g for g in manifest["groups"] if g.get("id") == "booth"]})
        return self._json(200, {"dir": str(DECKS_DIR), "decks": rows, "groups": manifest["groups"]})

    def _handle_dev_deck_file(self, parsed):
        """?deck=<폴더 이름>&kind=deck|audio → 파일 그대로. ppt/ 밖으로는 못 나간다."""
        from urllib.parse import parse_qs

        qs = parse_qs(parsed.query or "")
        key = (qs.get("deck") or [""])[0]
        kind = (qs.get("kind") or ["deck"])[0]
        if not _dev_open() and not self._public_deck(key):
            return self._json(404, {"error": "not found"})
        row = next((r for r in self._deck_entries() if r["key"] == key), None)
        if row is None:
            return self._json(404, {"error": "no_deck", "message": "그 이름의 발표자료 폴더가 없어요."})
        base = DECKS_DIR / key
        if kind == "audio" and row.get("clova_txt"):
            data = clova_transcript.marked_silence(key, float(row["audio_sec"] or 0))
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        fname = row["deck"] if kind == "deck" else row["audio"]
        if not fname:
            return self._json(404, {"error": "no_audio", "message": "이 덱에는 녹음 파일이 없어요."})
        path = (base / fname if base.is_dir() else base).resolve()
        if not str(path).startswith(str(DECKS_DIR.resolve())) or not path.is_file():
            return self._json(404, {"error": "no_file"})
        data = path.read_bytes()
        ctype = {
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".pdf": "application/pdf", ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".mp3": "audio/mpeg",
            ".wav": "audio/wav", ".webm": "audio/webm", ".ogg": "audio/ogg", ".aac": "audio/aac", ".flac": "audio/flac",
        }.get(path.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_preview_pdf(self, parsed):
        """발표 원본 미리보기 PDF (PPTX 렌더본 또는 업로드한 PDF 그대로)."""
        sid = self._query_session_id(parsed)
        path = ARCHIVE.preview_path(sid) if sid else None
        if path is None:
            return self._json(404, {"error": "no_preview", "message": "원본 미리보기 PDF가 없어요."})
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, parsed, head_only: bool = False):
        """
        데모 화면 파일과 /sdk/ 모듈 (demo/static_assets.py). HTML·ES 모듈은 참조 주소에 내용 해시를 넣어 내고,
        요청의 v 가 지금 해시와 같으면 1년 immutable, 아니면 no-cache + ETag.
        폴더 주소에 / 가 없으면 SimpleHTTPRequestHandler 의 리다이렉트에 맡긴다.
        """
        url = parsed.path
        path = STATIC.locate(url)
        if path is not None and _static_hidden(path):
            self.send_error(404)
            return None
        if path is not None and path.is_dir():
            if not url.endswith("/"):
                return super().do_HEAD() if head_only else super().do_GET()
            url += "index.html"
        got = STATIC.served(url)
        if got is None:
            self.send_error(404)
            return None
        data, digest = got
        path = STATIC.locate(url)
        ctype = self.guess_type(str(path))
        if ctype.startswith("text/") and "charset" not in ctype:
            ctype += "; charset=utf-8"
        suffix = path.suffix.lower()
        if suffix in (".js", ".mjs", ".css"):
            data = MINIFY(data, "css" if suffix == ".css" else "js", path.name)
        extra = []
        if suffix == ".html":
            cache = REVALIDATE  # 입구는 늘 재검증 — 새 판의 해시 주소를 바로 물게
            # Cloudflare 에게만: 60초 들고 있다가 그 뒤엔 가진 걸 먼저 내주며 뒤에서 새로 받는다. HTML 은 누구에게나
            # 같아서(팀 여부는 /api/v1/team) 나눠 써도 되고, 첫 방문의 VM 왕복(0.2~1.8초)이 빠진다.
            # Cloudflare 는 HTML 을 기본으로 저장하지 않아서 캐시 규칙을 켜야 쓰인다 (docs/DEPLOYMENT.md §10-5)
            extra.append(("CDN-Cache-Control", CDN_HTML_CACHE))
        else:
            v = (parse_qs(parsed.query).get("v") or [""])[0]
            cache = IMMUTABLE if v and v == digest else REVALIDATE
        self._send_static_bytes(path, data, ctype, cache, head_only, extra)
        return None

    def _send_static_bytes(self, path: Path, data: bytes, ctype: str, cache: str, head_only: bool,
                           extra: list[tuple[str, str]] = ()) -> None:
        compressible = path.suffix.lower() in COMPRESSIBLE and len(data) >= MIN_GZIP_BYTES
        gz = compressible and accepts_gzip(self.headers.get("Accept-Encoding") or "")
        etag = f'"{content_digest(data)}{"-gz" if gz else ""}"'
        headers = [("ETag", etag), ("Cache-Control", cache), *extra]
        if compressible:
            headers.append(("Vary", "Accept-Encoding"))
        if etag_matches(self.headers.get("If-None-Match") or "", etag):
            self.send_response(304)
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()
            return
        body = STATIC.gzipped(path, data) if gz else data
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Last-Modified", self.date_time_string(int(path.stat().st_mtime)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _handle_parse(self, raw: bytes):
        ctype = self.headers.get("Content-Type", "")
        if "application/json" in ctype:
            body = json.loads(raw or b"{}")
            if _mock():
                fixture = ROOT / "fixtures" / "sample_slidedoc.json"
                doc = SlideDoc.from_dict(json.loads(fixture.read_text(encoding="utf-8")))
                return self._json(200, doc.to_dict())
            if body.get("fixture"):
                return self._json(
                    400,
                    {
                        "error": "fixture_disabled",
                        "message": "MOCK_EXTERNAL_APIS=false 입니다. PDF/PPTX 파일을 업로드하세요.",
                    },
                )
            return self._json(400, {"error": "file required"})

        boundary = None
        if "boundary=" in ctype:
            boundary = ctype.split("boundary=")[-1].strip().encode()
        if not boundary:
            return self._json(400, {"error": "multipart required"})

        uploads = _multipart_files(raw, boundary)
        if not uploads:
            return self._json(400, {"error": "document field missing"})
        if sum(len(b) for _, b in uploads) > MAX_UPLOAD_BYTES:
            return self._json(413, {"error": "too_large", "message": "최대 30MB까지 올릴 수 있어요."})
        # 확장자가 아니라 내용으로 판별한다. 아니면 디스크에 쓰지 않는다.
        exts = [_sniff_document(b) for _, b in uploads]
        if any(e is None for e in exts):
            return self._json(415, {"error": "unsupported_type", "message": "PDF·PPTX·PNG·JPG 파일만 올릴 수 있어요."})
        # 여러 장은 화면 캡처(이미지)만 — 문서 두 개를 한 자료로 섞는 길은 열지 않는다.
        if len(uploads) > 1 and any(e not in IMAGE_EXTS for e in exts):
            return self._json(415, {"error": "unsupported_type", "message": "여러 장은 화면 캡처(PNG·JPG)만 함께 올릴 수 있어요."})
        filename, file_bytes = uploads[0]
        ext = exts[0]
        if len(uploads) > 1:
            filename = f"화면 {len(uploads)}장"
        # 장수는 Upstage 에 보내기 **전에** 로컬에서 센다 — 파서의 MAX_SLIDES 검사는 전 페이지 과금 뒤에 돈다.
        pages = len(uploads) if len(uploads) > 1 else _count_pages(file_bytes, ext)
        if pages is not None and pages > _max_slides():
            sys.stderr.write(f"[bridge] F-01 parse 거절: {pages}장 > {_max_slides()}장\n")
            return self._json(413, {
                "error": "too_many_pages",
                "message": f"{pages}장이에요. 지금은 {_max_slides()}장까지 올릴 수 있어요. 나눠서 올려 주세요.",
            })

        if _mock():
            fixture = ROOT / "fixtures" / "sample_slidedoc.json"
            doc = SlideDoc.from_dict(json.loads(fixture.read_text(encoding="utf-8")))
            doc.file_name = filename
            return self._json(200, doc.to_dict())

        # 학습 동의는 업로드 때 한 번만 받는다 (쿼리). 이후 호출은 이 값을 못 올린다.
        from urllib.parse import parse_qs

        qs = parse_qs(urlparse(self.path).query or "")
        consent = (qs.get("consent_learning") or ["0"])[0].strip().lower() in ("1", "true", "yes", "on")
        # 익명 학습자 id (F-25) — 브라우저 localStorage 의 난수. 같은 사람의 지난 리허설을 잇는 열쇠다.
        learner_id = ARCHIVE.safe_learner((qs.get("learner") or [""])[0])

        sys.stderr.write(
            f"[bridge] F-01 parse start file={filename!r} files={len(uploads)} "
            f"bytes={sum(len(b) for _, b in uploads)} consent={consent}\n"
        )
        tmp_paths: list[str] = []
        for (_, data), e in zip(uploads, exts):
            with tempfile.NamedTemporaryFile(suffix=e, delete=False) as tmp:
                tmp.write(data)
                tmp_paths.append(tmp.name)
        try:
            # 같은 파일(바이트)을 다시 올리면 Upstage 를 다시 안 부른다 (09-30 M-14). 09-30 실측: 8799 보관소에서 같은 파일을
            # 여러 번 올린 5묶음(13세션) 중 2묶음은 파싱 결과가 달랐다 — 그러면 개념·그래프 캐시(내용 해시)도 빗나가 4분을 다시 태운다.
            # 열쇠는 올린 바이트의 sha256 + 파서 설정 + 코드 판이라, 파일이 1비트라도 다르면 다른 키다 (근사 매치 없음).
            parse_key = self._parse_cache_key(uploads, exts)
            cached_doc = _stage_cache_get("parse", parse_key)
            if cached_doc is not None:
                doc = SlideDoc.from_dict(cached_doc)
                sys.stderr.write(f"[bridge] F-01 parse 캐시 적중 {parse_key}\n")
            elif len(tmp_paths) == 1:
                doc = parse_document(tmp_paths[0])
            else:
                # 캡처 한 장 = 1페이지 문서. 올린 순서대로 번호를 다시 매겨 한 자료로 만든다.
                doc = merge_slidedocs([parse_document(tp) for tp in tmp_paths], file_name=filename)
            if cached_doc is None:
                _stage_cache_put("parse", parse_key, doc.to_dict())
            sys.stderr.write(f"[bridge] F-01 parse done slides={doc.total_slides}\n")
            # 파서는 임시 경로 이름을 그대로 담는다. 원래 업로드 이름으로 되돌린다.
            doc.file_name = filename
            payload = doc.to_dict()
            # 세션 발급 — 이후 모든 호출이 이 id 를 실어 보낸다. 저장 실패는 파싱 실패가 아니다.
            sid = ARCHIVE.new_id()
            rec = ARCHIVE.open(
                sid, consent=consent, file_name=filename, ext=ext, upload=file_bytes,
                sha256=hashlib.sha256(file_bytes).hexdigest(), title=_cache_stem(filename),
                learner_id=learner_id,
            )
            if rec is not None:
                payload["session_id"] = sid
                payload["consent_learning"] = consent
                # 동의한 캡처 묶음은 2장째부터 따로 남긴다 (original 은 1장째다)
                if consent and len(uploads) > 1:
                    for i, ((_, data), e) in enumerate(zip(uploads, exts)):
                        if i:
                            ARCHIVE.put_file(sid, f"original_{i + 1}{e}", data)
                # 발표 화면용 원본 미리보기 (PPTX 는 LibreOffice 렌더, PDF 는 원본이 곧 미리보기).
                # 이미지는 미리보기가 없다 — PNG 를 preview.pdf 로 두면 pdf.js 가 죽는다.
                if ext == ".pptx":
                    rendered = _pptx_to_preview_pdf(Path(tmp_paths[0]))
                    if rendered:
                        ARCHIVE.put_file(sid, "preview.pdf", rendered)
                elif ext == ".pdf" and not consent:
                    ARCHIVE.put_file(sid, "preview.pdf", file_bytes)
                if ARCHIVE.preview_path(sid) is not None:
                    payload["preview_pdf"] = f"/api/v1/preview-pdf?session_id={sid}"
                ARCHIVE.put_artifact(sid, "slide_doc", payload)
            return self._json(200, payload)
        finally:
            for tp in tmp_paths:
                Path(tp).unlink(missing_ok=True)

    @staticmethod
    def _parse_cache_key(uploads: list[tuple[str, bytes]], exts: list[str | None]) -> str:
        """파싱 캐시 열쇠 — 올린 파일들의 sha256(순서대로)·형식 + 파서 설정(모델·모드·OCR·출력·좌표) + F-01 코드 판."""
        from chuckchuck import f01_parse as F01

        return _stage_key(
            "f01", _stage_version("parse"), [hashlib.sha256(b).hexdigest() for _, b in uploads], list(exts),
            F01.MODEL, F01.MODE, F01.OCR, F01.OUTPUT_FORMATS, F01.COORDINATES,
        )

    def _handle_suggest_context(self, raw: bytes):
        """[F-23] 자료만 보고 발표 상황을 추정한다. 결정론·호출 0 — 과금 경로가 아니다.
        화면은 이 값으로 #/new 폼을 미리 채우기만 하고, 사용자가 고른 값이 이긴다."""
        from chuckchuck.f23_context import suggest_context

        body = json.loads(raw or b"{}")
        if not body.get("slide_doc"):
            return self._json(400, {"error": "slide_doc 이 필요해요"})
        return self._json(200, suggest_context(body["slide_doc"]).to_dict())

    def _handle_deck_gaps(self, raw: bytes):
        """[F-23 · 내용 제안] 이 청중이 기대하는데 자료에 없는 것. 결정론·호출 0. 상황이 없으면 F-23 추정값을 쓴다."""
        from chuckchuck.f23_context import deck_gaps, suggest_context

        body = json.loads(raw or b"{}")
        if not body.get("slide_doc"):
            return self._json(400, {"error": "slide_doc 이 필요해요"})
        situation = str(body.get("situation") or "")
        if not situation:
            situation = suggest_context(body["slide_doc"]).situation
        if not situation:
            return self._json(200, {"situation": "", "items": [], "summary": {},
                                    "message": "발표 상황을 골라 주면 청중이 기대하는 항목을 맞춰 볼 수 있어요"})
        return self._json(200, deck_gaps(body["slide_doc"], situation))

    def _handle_concepts(self, raw: bytes):
        from chuckchuck.contracts import Transcript

        body = json.loads(raw or b"{}")
        doc = SlideDoc.from_dict(body["slide_doc"])
        # 파싱을 거치지 않은 slide_doc 도 들어올 수 있다 — 장수 상한을 여기서도 지킨다 (장마다 LLM 을 부른다).
        if len(doc.slides) > _max_slides():
            return self._json(413, {"error": "too_many_pages",
                                    "message": f"{_max_slides()}장까지 분석할 수 있어요."})
        ctx = Context.from_dict(body.get("context") or {})
        llm = _pick_llm(body)
        transcript = None
        if body.get("transcript"):
            transcript = Transcript.from_dict(body["transcript"])
        # 같은 자료·같은 발표 정보면 결과가 같다. 부스 2회차부터 1분 43초를 안 태운다.
        # 코드 판은 f06 의 import 닫힘 전체다 (09-30: 예전엔 f06 하나라 발화 조각을 만드는 f05 를 고쳐도 옛 개념이 나왔다).
        # 입력은 **계약 모양**(from_dict→to_dict)으로 센다 (09-30 M-14). /parse 응답에는 session_id·preview_pdf·consent_learning 이
        # 붙어 있고 프론트는 그걸 그대로 보낸다 — 날 본문을 키에 넣으면 같은 덱을 다시 올릴 때마다(새 세션) 키가 달라져
        # 개념·그래프(합 4분)를 다시 돌렸다. F-06 이 실제로 읽는 것도 이 계약 모양뿐이다.
        key = _stage_key("f06", _stage_version("concepts"), _llm_identity(llm), doc.to_dict(), ctx.to_dict(),
                         transcript.to_dict() if transcript is not None else None)
        # 발표 정보는 manifest 에 붙인다 — 또래 기준(상황×시간) 을 만들 때의 버킷 키다.
        if not _mock() and _session_id_of(body) and body.get("context"):
            ARCHIVE.set_context(_session_id_of(body), body["context"])
        cached = _stage_cache_get("concepts", key)
        if cached is not None:
            sys.stderr.write(f"[bridge] F-06 concepts 캐시 적중 {key}\n")
            self._archive(body, "concept_doc", cached)
            missing = _concepts_missing(cached)
            return self._json(200, _analysis_response(cached, ["concepts_missing"] if missing else [], missing_slides=missing))

        sys.stderr.write(
            f"[bridge] F-06 concepts start slides={doc.total_slides} "
            f"has_transcript={transcript is not None} mock={_mock()}\n"
        )
        _fake_delay("/api/v1/concepts")
        try:
            result = extract_concepts(doc, ctx, transcript=transcript, llm=llm)
        except Exception as e:  # noqa: BLE001 — 분석 실패는 무엇이 안 됐는지 말한다 (모르는 실패는 일반 처리로 다시 던진다)
            failed = _analysis_failure(e)
            if failed is None:
                raise
            sys.stderr.write(f"[bridge] F-06 concepts 실패 → {failed[0]} {failed[1]['error']}: {e}\n")
            return self._json(*failed)
        payload = result.to_dict()
        # 끝내 못 받은 장이 조금 있으면 F-06 은 빈 개념으로 두고 표시만 한다 — 응답·로그에 싣고, 단계 캐시에는 담지 않는다
        # (다음 분석이 그 장을 다시 받게. 반쪽 결과를 같은 자료의 모든 세션에 물리지 않는다 — B-03 과 같은 규율).
        missing = _concepts_missing(payload)
        sys.stderr.write(f"[bridge] F-06 concepts done model={result.model}"
                         f"{f' 빠진 장={missing} (캐시에 안 담음)' if missing else ''}\n")
        if not missing:
            _stage_cache_put("concepts", key, payload)
        self._archive(body, "concept_doc", payload)
        return self._json(200, _analysis_response(payload, ["concepts_missing"] if missing else [], missing_slides=missing))

    def _handle_strategy(self, raw: bytes):
        """F-20 · 분석 결과 → 발표 구성 제안 하나 + 대안 요약."""
        from chuckchuck.contracts import StrategyError
        from chuckchuck.f20_strategy import suggest_strategy

        body = json.loads(raw or b"{}")
        analysis = body.get("analysis")
        if not isinstance(analysis, dict) or not analysis:
            return self._json(
                400,
                {"error": "bad_request", "message": "analysis 가 필요합니다. 리포트 분석 결과를 보내세요."},
            )
        llm = _pick_llm(body)
        sys.stderr.write(
            f"[bridge] F-20 strategy start concepts={len(analysis.get('concepts') or [])} "
            f"quotes={len(analysis.get('quotes') or [])} mock={_mock()}\n"
        )
        try:
            result = suggest_strategy(analysis, llm=llm)
        except StrategyError as e:
            # 환각을 걸러낸 결과 남는 게 없을 수 있다. 그건 500 이 아니라 "이번엔 못 냈다" 다.
            sys.stderr.write(f"[bridge] F-20 strategy rejected: {e}\n")
            return self._json(502, {"error": "strategy_failed",
                                    "message": "이번엔 구성 제안을 만들지 못했어요. 잠시 뒤 다시 해 주세요."})
        sys.stderr.write(
            f"[bridge] F-20 strategy done type={result['chosen']['type']} "
            f"climax={result['chosen']['climax']}\n"
        )
        return self._json(200, result)

    def _handle_graph(self, raw: bytes):
        """F-07 · ConceptDoc(+선택 SlideDoc) → ConceptGraph."""
        body = json.loads(raw or b"{}")
        if not body.get("concept_doc"):
            return self._json(
                400,
                {"error": "bad_request", "message": "concept_doc 이 필요합니다. F-06 결과를 보내세요."},
            )
        doc = ConceptDoc.from_dict(body["concept_doc"])
        ctx = Context.from_dict(body.get("context") or {})
        # slide_doc 은 선택. 주면 weight 가 글자 수·시각자료까지 반영한다.
        slide_doc = SlideDoc.from_dict(body["slide_doc"]) if body.get("slide_doc") else None
        llm = _pick_llm(body)
        # F-07 은 Transcript 를 안 받는다 — 입력이 concept_doc·slide_doc·context 뿐이라
        # 같은 자료면 결과가 같다. 실측 2분 40초로 파이프라인에서 가장 긴 단계다
        # 09-29: F-07 후처리(식·목록 항목 메우기·겹친 이름 합치기)가 유틸 _graph_items·_claim_rules 에 있다.
        # f07 소스만 해시하면 그쪽을 고쳐도 옛 그래프가 나온다 (7756058 과 같은 함정). 09-30 부터는 손으로 적지 않고
        # f07 의 import 닫힘 전체(_match·_json_text·contracts·LLM 제공자까지)를 브리지 시작 때 판으로 센다.
        # 입력은 계약 모양으로 센다 — /concepts 와 같은 이유 (M-14: slide_doc 에 붙은 session_id 가 키를 세션마다 갈랐다)
        key = _stage_key("f07", _stage_version("graph"), _llm_identity(llm), doc.to_dict(),
                         slide_doc.to_dict() if slide_doc is not None else None, ctx.to_dict())
        cached = _stage_cache_get("graph", key)
        if cached is not None:
            sys.stderr.write(f"[bridge] F-07 graph 캐시 적중 {key}\n")
            self._archive(body, "concept_graph", cached)
            return self._json(200, _analysis_response(cached, list(cached.get("degraded") or [])))

        sys.stderr.write(
            f"[bridge] F-07 graph start slides={doc.total_slides} "
            f"has_slide_doc={slide_doc is not None} mock={_mock()}\n"
        )
        _fake_delay("/api/v1/graph")
        try:
            graph = build_graph(doc, ctx, slide_doc=slide_doc, llm=llm)
        except Exception as e:  # noqa: BLE001 — 노드 0개 등 분석 실패는 무엇이 안 됐는지 말한다 (모르는 실패는 일반 처리로)
            failed = _analysis_failure(e)
            if failed is None:
                raise
            sys.stderr.write(f"[bridge] F-07 graph 실패 → {failed[0]} {failed[1]['error']}: {e}\n")
            return self._json(*failed)
        # 만들다 떨어진 단계(ConceptGraph.degraded — 예: 연결 보강 「links」)는 응답·로그에 싣는다. 그 그래프는 단계 캐시에 담지
        # 않는다 — 일시 실패로 반쪽이 된 그래프를 같은 자료의 모든 세션에 물리지 않게 (B-03 과 같은 규율).
        degraded = [str(x) for x in (getattr(graph, "degraded", None) or [])]
        sys.stderr.write(
            f"[bridge] F-07 graph done nodes={len(graph.nodes)} "
            f"edges={len(graph.edges)} sections={len(graph.sections)} thesis={getattr(graph, 'thesis', None) or '-'}"
            f"{f' 폴백={degraded} (캐시에 안 담음)' if degraded else ''}\n"
        )
        payload = graph.to_dict()
        if not degraded:
            _stage_cache_put("graph", key, payload)
        self._archive(body, "concept_graph", payload)
        return self._json(200, _analysis_response(payload, degraded))

    def _handle_alignment(self, raw: bytes):
        """F-11 · ConceptGraph + Transcript(+선택 Context) → AlignmentDoc."""
        from chuckchuck import align_speech
        from chuckchuck.contracts import ConceptGraph, Transcript

        body = json.loads(raw or b"{}")
        if not body.get("graph") or not body.get("transcript"):
            return self._json(
                400,
                {
                    "error": "bad_request",
                    "message": "graph 와 transcript 가 필요합니다. F-07·F-05 결과를 보내세요.",
                },
            )
        graph = ConceptGraph.from_dict(body["graph"])
        transcript = Transcript.from_dict(body["transcript"])
        ctx = Context.from_dict(body.get("context") or {})
        llm = _pick_llm(body)
        # 09-30 held-out C-06·C-07: 정합이 발화의 숫자·방향을 **자료 원문**과 견주고(모순), 녹음이 다른 발표면 판정을 건너뛴다.
        # 프론트는 slidedoc·marks_match 를 이 요청에 안 싣는다 — /questions 처럼 세션 보관소(동의 무관 캐시)에서 id 로 찾는다.
        sid = _session_id_of(body)
        slidedoc = ARCHIVE.read_artifact(sid, "slide_doc") if sid else None
        saved_tr = ARCHIVE.read_artifact(sid, "transcript") if sid else None
        speech_match = (body["transcript"].get("marks_match") if isinstance(body["transcript"], dict) else None) or (
            (saved_tr or {}).get("marks_match"))
        sys.stderr.write(
            f"[bridge] F-11 alignment start nodes={len(graph.nodes)} "
            f"slides={graph.total_slides} slide_doc={slidedoc is not None} marks_match={speech_match} mock={_mock()}\n"
        )
        _fake_delay("/api/v1/alignment")
        # 입력이 같으면 결과도 같다 — 부스의 같은 덱 · 같은 녹음은 두 번째부터 LLM 을 안 부른다 (계약 모양으로 센다, 세션 id 는 안 넣는다)
        al_key = None if _mock() else _stage_key(
            "f11", _stage_version("alignment"), _llm_identity(llm), graph.to_dict(), transcript.to_dict(), ctx.to_dict(),
            slidedoc, speech_match)
        cached_al = _stage_cache_get("alignment", al_key) if al_key else None
        if cached_al is not None:
            sys.stderr.write(f"[bridge] F-11 alignment 캐시 적중 {al_key}\n")
            self._archive(body, "alignment_doc", cached_al)
            return self._json(200, cached_al)
        alignment = align_speech(graph, transcript, ctx, llm=llm, slide_doc=slidedoc, speech_match=speech_match)
        s = alignment.summary
        sys.stderr.write(
            f"[bridge] F-11 alignment done coverage={s.coverage} "
            f"verdicts={s.verdict_counts} speech_match={alignment.speech_match} basis={alignment.basis} "
            f"skipped={[x.slide_no for x in alignment.skipped_slides]}\n"
        )
        payload = alignment.to_dict()
        if al_key and alignment.basis == "llm":   # LLM 이 판정을 비운 짐작(fallback)은 굳히지 않는다 — 다음엔 다시 부른다
            _stage_cache_put("alignment", al_key, payload)
        self._archive(body, "alignment_doc", payload)
        return self._json(200, payload)

    def _handle_flow(self, raw: bytes):
        """F-11 파생 · ConceptGraph + AlignmentDoc → FlowDiff. LLM 호출 없음."""
        from chuckchuck import build_flow_diff

        body = json.loads(raw or b"{}")
        if not body.get("graph") or not body.get("alignment"):
            return self._json(
                400,
                {
                    "error": "bad_request",
                    "message": "graph 와 alignment 가 필요합니다. F-07·F-11 결과를 보내세요.",
                },
            )
        flow = build_flow_diff(body["graph"], body["alignment"])
        sys.stderr.write(
            f"[bridge] F-11 flow done issues={len(flow.issues)} "
            f"tau={flow.order_tau} ghosts={len(flow.ghost_node_ids)}\n"
        )
        payload = flow.to_dict()
        self._archive(body, "flow_diff", payload)
        return self._json(200, payload)


    def _handle_chatter(self, raw: bytes):
        """
        삐약 청중석 · ConceptGraph + AlignmentDoc + FlowDiff → ChatterDoc.

        세션 id + 재료 해시로 단계 캐시에 둔다 (09-30 녹음 대화 감사 REC-19) — 예전엔 결과·리포트 화면을 열 때마다 네 모델(라운드 둘,
        최대 8콜)을 다시 불렀다: 감사 LLM 230콜 중 101콜이 객석, 그중 약 55콜이 이미 분석한 세션의 재렌더였다.
        못 온 병아리가 있으면(LLM 실패 — absent) 캐시에 두지 않는다. 대타 대사를 성공처럼 굳히면 다음에 열어도 계속 결석이다.
        """
        from chuckchuck import build_chatter

        body = json.loads(raw or b"{}")
        missing = [k for k in ("graph", "alignment", "flow") if not body.get(k)]
        if missing:
            return self._json(
                400,
                {
                    "error": "bad_request",
                    "message": (
                        f"{', '.join(missing)} 가 필요합니다. "
                        "F-07·F-11 결과를 함께 보내세요."
                    ),
                },
            )
        key = _chatter_key(_session_id_of(body), body)
        payload = _stage_cache_get("chatter", key) or _recent_partial_chatter(key)
        claim = None
        if payload is None:
            claim = _claim_chatter(key)
            if claim is None:                     # 같은 수다를 누가 만드는 중 — 끝나길 기다렸다가 캐시를 본다
                _wait_chatter(key)
                payload = _stage_cache_get("chatter", key) or _recent_partial_chatter(key)
        if payload is not None:
            absent = payload.get("absent") or []
            sys.stderr.write(f"[bridge] chatter {'recent partial (결석 ' + ','.join(absent) + ')' if absent else 'cache hit'} "
                             f"turns={len(payload.get('turns') or [])}\n")
        else:
            try:
                chatter = build_chatter(body["graph"], body["alignment"], body["flow"])
                payload = chatter.to_dict()
                _remember_chatter(key, payload, complete=not chatter.absent)
            finally:
                if claim is not None:
                    _release_chatter(key, claim)
            speakers = sorted({t.speaker for t in chatter.turns})
            sys.stderr.write(
                f"[bridge] chatter done turns={len(chatter.turns)} "
                f"speakers={len(speakers)} refs={len(chatter.referenced_node_ids)} "
                f"{'absent=' + ','.join(chatter.absent) + f' (캐시 안 함 · {CHATTER_RETRY_AFTER_SEC}초 뒤 다시 부름)' if chatter.absent else 'cached'}\n"
            )
        self._archive(body, "chatter_doc", payload)
        return self._json(200, payload)

    def _handle_score(self, raw: bytes):
        """F-13 · AlignmentDoc(+선택 FlowDiff) → 0~100 점. LLM 호출 없음."""
        from chuckchuck import score_presentation
        from chuckchuck.contracts import AlignmentDoc, FlowDiff

        body = json.loads(raw or b"{}")
        if not body.get("alignment"):
            return self._json(
                400,
                {"error": "bad_request", "message": "alignment 가 필요합니다. F-11 결과를 보내세요."},
            )
        alignment = AlignmentDoc.from_dict(body["alignment"])
        flow = FlowDiff.from_dict(body["flow"]) if body.get("flow") else None
        result = score_presentation(alignment, flow)
        sys.stderr.write(
            f"[bridge] F-13 score={result.score} basis={result.basis} "
            f"omitted={result.omitted} contradictions={result.contradiction_count}\n"
        )
        return self._json(200, result.to_dict())

    def _handle_rubric(self, raw: bytes):
        """
        F-14 · 채점표 v3 로 0~100 점. 파이프라인 산출물을 모아서 보낸다.

        **바디가 전부 optional 이다.** 없는 자료에 기대는 항목만 '못 쟀다'가 되고
        나머지는 정상 채점된다 — 부스에서 앞 단계 하나가 죽어도 점수는 뜬다.
        """
        from chuckchuck import from_legacy_score, score_presentation, score_rubric
        from chuckchuck.contracts import AlignmentDoc, FlowDiff

        body = json.loads(raw or b"{}")
        llm = _pick_llm(body)
        try:
            result = score_rubric(
                situation=body.get("situation"),
                context=body.get("context"),
                slides=body.get("slides"),
                concepts=body.get("concepts"),
                graph=body.get("graph"),
                transcript=body.get("transcript"),
                alignment=body.get("alignment"),
                flow=body.get("flow"),
                pace=body.get("pace"),
                habits=body.get("habits"),
                llm=llm,
            )
        except Exception as e:  # noqa: BLE001
            # 채점표가 죽었을 때 마지막 방어선 — 정합 판정이 있으면 예전 방식으로라도 매긴다.
            # 부스에서 점수가 아예 안 뜨는 것보다 낫고, 폴백인 건 숨기지 않는다.
            sys.stderr.write(f"[bridge] F-14 실패, F-13 폴백: {e}\n")
            if not body.get("alignment"):
                return self._json(
                    502,
                    {"error": "rubric_failed", "message": "채점표로 매기지 못했어요. 잠시 뒤 다시 해 주세요."},
                )
            legacy = score_presentation(
                AlignmentDoc.from_dict(body["alignment"]),
                FlowDiff.from_dict(body["flow"]) if body.get("flow") else None,
            )
            result = from_legacy_score(legacy, body.get("situation"))

        sys.stderr.write(
            f"[bridge] F-14 score={result.score} situation={result.situation} "
            f"basis={result.basis} 제외={result.excluded} 못잼={result.unmeasured}\n"
        )
        payload = result.to_dict()
        self._archive(body, "rubric_score", payload)
        return self._json(200, payload)

    def _handle_pace(self, raw: bytes):
        """F-17 · Transcript(+ConceptDoc/Context/AlignmentDoc) → PaceDoc. LLM 없음."""
        from chuckchuck.contracts import Transcript

        body = json.loads(raw or b"{}")
        if not body.get("transcript"):
            return self._json(
                400,
                {"error": "bad_request", "message": "transcript 가 필요합니다. F-05 결과를 보내세요."},
            )
        transcript = Transcript.from_dict(body["transcript"])
        ctx = Context.from_dict(body.get("context") or {})
        concept_doc = ConceptDoc.from_dict(body["concept_doc"]) if body.get("concept_doc") else None
        # 정합(F-11)이 「녹음이 이 자료의 발표가 아니다」 라면 F-17 은 재지 않는다 — 빈 PaceDoc (09-30 녹음 대화 감사 REC-10)
        alignment = _optional_alignment(body)
        pace = analyze_pace(transcript, ctx, concept_doc, alignment)
        unmeasured = " · 녹음이 이 자료의 발표가 아니라 재지 않음" if alignment is not None and not pace.slides else ""
        sys.stderr.write(
            f"[bridge] F-17 pace done slides={len(pace.slides)} "
            f"actual={pace.actual_sec}s target={pace.target_sec}s{unmeasured}\n"
        )
        payload = pace.to_dict()
        self._archive(body, "pace_doc", payload)
        # 질문 생성(F-08)이 장 단위 시간 배분을 약점으로 쓴다. 동의 없는 세션은 보관소가 pace_doc 을
        # 안 남기므로, 트리아지 캐시처럼 메모리에만 세션 id 로 들고 있는다.
        if _session_id_of(body):
            STORE.set_triage("pace:" + _session_id_of(body), payload)
        return self._json(200, payload)

    def _handle_habits(self, raw: bytes):
        """F-18 · Transcript → HabitDoc."""
        from chuckchuck.contracts import Transcript

        body = json.loads(raw or b"{}")
        if not body.get("transcript"):
            return self._json(
                400,
                {"error": "bad_request", "message": "transcript 가 필요합니다. F-05 결과를 보내세요."},
            )
        transcript = Transcript.from_dict(body["transcript"])
        # 기본은 LoRA (HABIT_PROVIDER / extract_habits 기본값). mock 이어도 강제하지 않음.
        provider = _pick_habit_provider(body)  # None → HABIT_PROVIDER → lora 기본
        spans = body.get("spans")
        habits = extract_habits(transcript, provider=provider, spans=spans)
        sys.stderr.write(
            f"[bridge] F-18 habits done REP={habits.repeat_cnt} FIL={habits.filler_cnt} "
            f"PAUSE={habits.pause_cnt} provider={habits.provider}\n"
        )
        payload = habits.to_dict()
        self._archive(body, "habit_doc", payload)
        return self._json(200, payload)

    def _handle_report(self, raw: bytes):
        """F-19 · PaceDoc + HabitDoc → ReportDoc (LLM, mock 이면 규칙 폴백)."""
        body = json.loads(raw or b"{}")
        if not body.get("pace") or not body.get("habits"):
            return self._json(
                400,
                {
                    "error": "bad_request",
                    "message": "pace 와 habits 가 필요합니다. F-17·F-18 결과를 보내세요.",
                },
            )
        pace = PaceDoc.from_dict(body["pace"])
        habits = HabitDoc.from_dict(body["habits"])
        ctx = Context.from_dict(body.get("context") or {})
        llm = _pick_llm(body)
        # 점수는 채점표(F-14)가 진실이다. rubric 을 같이 보내면 그 점수를 싣고,
        # 안 보내면 0 으로 둔다 — 여기서 두 번째 점수를 만들지 않는다.
        # alignment 는 녹음이 이 자료의 발표인지만 본다 — 다른 발표면 LLM 없이 「재지 않았어요」 리포트 (09-30 REC-10)
        report = compose_report(pace, habits, ctx, rubric=body.get("rubric"), alignment=_optional_alignment(body), llm=llm)
        sys.stderr.write(
            f"[bridge] F-19 report done score={report.score} model={report.model}\n"
        )
        payload = report.to_dict()
        self._archive(body, "report_doc", payload)
        return self._json(200, payload)

    def _handle_transcribe(self, raw: bytes):
        body = json.loads(raw or b"{}")

        # 실데이터 스왑 지점의 더미 — 시나리오가 심긴 Transcript fixture 를 그대로 준다.
        # 실 녹음이 들어오면 이 분기를 안 타고 아래 provider 경로로 흐른다 (코드 수정 0줄).
        # 샘플 받아쓰기는 이미 있는 데이터다 — 공개 방문자에게는 주지 않는다 (mock 이거나 팀일 때만).
        if body.get("fixture") and not (_mock() or _dev_open()):
            return self._json(400, {"error": "fixture_disabled", "message": "녹음을 올리거나 직접 말하면 분석할 수 있어요."})
        if body.get("fixture"):
            name = body.get("fixture_name") or "sample_transcript.json"
            # 경로 탈출 방지
            fixture = (ROOT / "fixtures" / Path(name).name).resolve()
            if not str(fixture).startswith(str((ROOT / "fixtures").resolve())):
                return self._json(400, {"error": "bad_fixture"})
            if not fixture.exists():
                return self._json(
                    404,
                    {"error": "no_fixture", "message": f"{fixture.name} 이 없습니다."},
                )
            sys.stderr.write(f"[bridge] F-05 transcribe → fixture {fixture.name}\n")
            return self._json(200, json.loads(fixture.read_text(encoding="utf-8")))

        # 저장해 둔 녹음으로 이어서 — 화면을 고쳐 가며 반복 테스트할 때 매번 다시
        # 말하지 않기 위한 길이다 (2026-08-08 사용자 요청). 없으면 404 로 분명히
        # 알린다. 조용히 실 STT 로 흘리면 아낀 줄 알았던 과금이 그대로 나간다.
        if body.get("reuse"):
            sid = _session_id_of(body)
            saved = ARCHIVE.read_artifact(sid, "transcript") if sid else None
            if saved is None:
                return self._json(
                    404,
                    {
                        "error": "no_cache",
                        "message": "이 발표로 저장된 받아쓰기가 없어요. 한 번은 실제로 말해야 남아요.",
                    },
                )
            sys.stderr.write(f"[bridge] F-05 transcribe → 저장본 재사용 {sid}\n")
            return self._json(200, saved)

        # 서버 파일 경로는 받지 않는다 (보안 점검 2026-09-23 CRITICAL). 예전에는 본문의 audio_path 를
        # 그대로 STT 에 넘겨서, 인증 없는 요청 하나로 서버 안의 아무 파일이나 외부 벤더로 올라갈 수 있었다.
        # 오디오는 audio_base64 로만 받는다. 조용히 무시하지 않고 거절해서 잘못된 호출부를 드러낸다.
        if body.get("audio_path") is not None:
            sys.stderr.write("[bridge] F-05 transcribe 거절: audio_path 는 받지 않음\n")
            return self._json(400, {
                "error": "audio_path_unsupported",
                "message": "녹음 파일은 audio_base64 로 보내 주세요.",
            })

        marks = [SlideMark.from_dict(m) for m in body.get("marks", [])]
        provider = _pick_stt_provider(body)
        _fake_delay("/api/v1/transcribe")

        audio_b64 = body.get("audio_base64")
        audio_path: str | None = None
        clova_out: dict | None = None
        if audio_b64:
            import base64
            import binascii

            try:
                audio_bytes = base64.b64decode(audio_b64, validate=False)
            except (binascii.Error, ValueError, TypeError):
                return self._json(400, {"error": "bad_audio", "message": "녹음 데이터를 읽지 못했어요. 다시 녹음해 주세요."})
            if len(audio_bytes) > MAX_UPLOAD_BYTES:
                return self._json(
                    413,
                    {
                        "error": "too_large",
                        "message": f"녹음은 최대 30MB까지예요. (받은 파일 {len(audio_bytes) / 1024 / 1024:.1f}MB)",
                    },
                )
            # 확장자가 실제 포맷과 다르면 STT 가 파일을 못 읽는다 — 프런트가 파일명에서 뽑아 보낸다
            ext = _safe_audio_ext(body.get("ext"))
            sys.stderr.write(f"[bridge] F-05 transcribe audio bytes={len(audio_bytes)} ext={ext}\n")
            # 개발용: #/test/qa 가 내려준 표식 박힌 무음 WAV 면 STT 대신 그 덱 폴더의 클로바 전사를 쓴다.
            marked = clova_transcript.marked_deck_key(audio_bytes) if _dev_open() else None
            if marked is not None:
                row = next((r for r in self._deck_entries() if r["key"] == marked and r.get("clova_txt")), None)
                if row is not None:
                    clova_out = clova_transcript.transcript_dict(DECKS_DIR / marked / row["clova_txt"])
                    sys.stderr.write(f"[bridge] F-05 transcribe → 클로바 전사 {row['clova_txt']} (개발용)\n")
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(audio_bytes)
                audio_path = tmp.name
        if not audio_path:
            # 예전에는 빈 파일을 만들어 그대로 STT 에 올렸다. 그러면 "녹음이 비었다"
            # 라는 사실이 벤더 오류로 번역돼 화면에 뜬다 — 2026-08-08 실제로
            # `A.X STT upload-token 실패 400: fileSize parameter empty` 가 502 로
            # 올라왔고, 마이크가 안 잡힌 것을 STT 장애처럼 읽게 만들었다.
            # 유료 호출도 한 번 나간다. 여기서 끊고 사실대로 말한다.
            if not _mock():
                sys.stderr.write("[bridge] F-05 transcribe 거절: 오디오가 없음\n")
                return self._json(
                    400,
                    {
                        "error": "no_audio",
                        "message": "녹음이 비어 있어요. 마이크 권한을 허용했는지 확인하고 다시 녹음해주세요.",
                    },
                )
            audio_path = str(ROOT / "fixtures" / ".keep")
            Path(audio_path).write_text("", encoding="utf-8")

        try:
            stt_key = None
            if not clova_out and audio_b64 and not _mock():
                stt_key = _stage_key("f05", _stage_version("transcribe"), hashlib.sha256(audio_bytes).hexdigest(), ext,
                                     [m.to_dict() for m in marks], provider or os.environ.get("STT_PROVIDER", ""))
            cached_tr = _stage_cache_get("transcribe", stt_key) if stt_key else None
            if cached_tr is not None:
                sys.stderr.write(f"[bridge] F-05 transcribe 캐시 적중 {stt_key}\n")
                t = Transcript.from_dict(cached_tr)
            else:
                t = Transcript.from_dict(clova_out) if clova_out else transcribe(audio_path, marks, provider=provider)
                if stt_key and t.words:
                    _stage_cache_put("transcribe", stt_key, t.to_dict())
            out = t.to_dict()

            # 업로드본에는 슬라이드 전환 기록이 없어 프런트가 균등 분할 marks 를
            # 보낸다. 그대로 두면 엉뚱한 발화가 엉뚱한 슬라이드에 붙는다.
            # 자료를 같이 받았으면 발화 내용으로 구간을 되짚는다 (F-04 파생).
            # STT 는 이미 끝났으므로 재분할만 한다 — 과금 호출이 늘지 않는다.
            slidedoc = body.get("slidedoc")
            if slidedoc and t.words:
                from chuckchuck.contracts import SlideDoc
                from chuckchuck.f04_infer_marks import infer_slide_marks
                from chuckchuck.f05_stt import split_by_slide

                doc = SlideDoc.from_dict(slidedoc) if isinstance(slidedoc, dict) else slidedoc
                got = infer_slide_marks(doc, t.words, t.duration_sec)
                if got.estimated:
                    out["by_slide"] = [s.to_dict() for s in split_by_slide(t.words, got.marks)]
                    out["marks"] = [m.to_dict() for m in got.marks]
                # 추정했든 물러섰든 사실대로 알린다 — 화면이 「추정값」을 표시해야 한다
                out["marks_estimated"] = got.estimated
                out["marks_confidence"] = got.confidence
                out["marks_reason"] = got.reason
                # "구간을 못 맞췄다" 와 "아예 다른 파일을 올렸다" 는 다른 사실이다.
                # 화면이 후자를 경고로 세우려면 문장이 아니라 판정값이 필요하다.
                out["marks_match"] = got.match
                sys.stderr.write(
                    f"[bridge] F-04 구간 추정 estimated={got.estimated} "
                    f"confidence={got.confidence}\n"
                )
            # 재분할까지 끝난 뒤에 저장한다 — 저장본을 그대로 다시 쓸 때 화면이
            # 방금 본 것과 같아야 한다. mock 결과는 남기지 않는다 (남의 자료를
            # 내 녹음으로 착각하게 만드는 것과 같은 종류의 거짓이다).
            # 질문 코칭 답변 한 마디(purpose=qa_answer)는 발표 받아쓰기가 아니다 — 보관하면 그 세션의 리허설 받아쓰기(transcript)를
            # 덮어 새로고침 복구·「저장해 둔 녹음으로 이어서」·기억(F-25)이 답변 한 줄을 발표로 읽는다 (09-30 qa/front: 그래서 답변
            # 받아쓰기에 session_id 를 못 싣고, 요청 제한이 IP 칸 하나로 몰렸다).
            if str(body.get("purpose") or "") != "qa_answer":
                self._archive(body, "transcript", out)
            return self._json(200, out)
        except Exception as e:  # noqa: BLE001
            from chuckchuck.contracts import STTError

            msg = str(e) or e.__class__.__name__
            sys.stderr.write(f"[bridge] F-05 transcribe failed: {msg}\n")
            # "인식 결과가 비어 있습니다" 는 장애가 아니라 말소리가 없었던 것이다 (2026-09-13 실측: 톤만 든 WAV).
            # 벤더 문구를 그대로 내보내면 사용자는 STT 가 고장 난 줄 안다 — 무엇을 하면 되는지로 바꿔 말한다.
            if isinstance(e, STTError) and "인식 결과가 비어" in msg:
                return self._json(422, {
                    "error": "no_speech",
                    "message": "말소리를 못 알아들었어요. 마이크에 조금 더 가까이 다시 말하거나 타이핑으로 답해 주세요.",
                })
            # 벤더 응답 본문·서버 경로가 섞일 수 있어 상세는 위 stderr 에만 남긴다.
            code = 502 if isinstance(e, STTError) else 500
            return self._json(
                code,
                {
                    "error": "stt_failed",
                    "message": "음성 인식이 이번엔 안 됐어요. 잠시 뒤 다시 녹음하거나 타이핑으로 답해 주세요.",
                },
            )
        finally:
            if audio_b64 and audio_path:
                Path(audio_path).unlink(missing_ok=True)


    def _client_key(self) -> str:
        """
        요청 제한을 셀 단위. 데모는 인증이 없으니 IP 가 최선이다.

        Cloudflare Tunnel 뒤에서는 모든 요청이 127.0.0.1 에서 온다 — 그대로 세면
        심사위원 전원이 30회/분 한 통을 나눠 쓰고 세 명째부터 429 가 난다.
        **루프백에서 온 요청에 한해** 터널이 붙인 CF-Connecting-IP 를 믿는다.
        바깥에서 온 요청의 헤더는 위조일 수 있어 안 읽는다 (DEMO_HOST=0.0.0.0 금지와 같은 이유).

        2026-10-05 방패: Funnel 도 루프백으로 들어와서, ts.net 주소로 바로 와 CF-Connecting-IP 를 바꿔 가며 보내면
        IP 상한이 다 풀렸다. 이제 X-Forwarded-For 마지막 칸(Funnel 이 적는 TCP 상대)이 Cloudflare 일 때만, 그리고
        DEMO_EDGE_SECRET 을 정했으면 X-Edge-Auth 가 맞을 때만 그 헤더를 믿는다 — 규칙 전체는 shield.resolve_client.
        요청마다 한 번만 계산한다 (keep-alive 다음 요청은 handle_one_request 가 비운다).
        """
        cached = getattr(self, "_client_ip", None)
        if cached:
            return cached
        try:
            peer = self.client_address[0]
        except Exception:  # noqa: BLE001
            return "unknown"
        ip, via = shield.resolve_client(peer, self.headers, EDGE_SECRET)
        self._client_ip, self._client_via = ip, via
        return ip

    def _rate_bucket(self, path: str, raw: bytes) -> str:
        """
        요청 제한 칸. 세션 id(본문 → /sessions/{id}/ 경로)가 발급 모양이면 그 세션, 아니면 IP (`_client_key`).

        'flat' 은 발급 id 가 없는 모든 사람이 나눠 쓰는 자리라 세션으로 세지 않는다 — IP 칸이다.
        본문을 여기서 한 번 더 읽는다 (핸들러도 읽는다). 과금 경로 본문은 수 MB 안이라 LLM 한 콜에 비하면 공짜다.
        """
        sid_raw = None
        if path != "/api/v1/parse" and raw:
            if len(raw) <= JSON_BODY_MAX:
                try:
                    body = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    body = None
                if isinstance(body, dict):
                    sid_raw = body.get("session_id")
            else:
                # 녹음(base64)처럼 큰 본문은 다 풀지 않고 열쇠 자리만 찾는다 — 42MB 를 칸 하나 정하려고 두 번 풀 수는 없다
                m = _SESSION_ID_RE.search(raw)
                sid_raw = m.group(1).decode("ascii") if m else None
        if not sid_raw and "/api/v1/sessions/" in path:
            sid_raw = self._path_segment_after(path, "sessions")
        sid = _store_sid(sid_raw)
        if sid and sid != FLAT_SESSION_ID:
            return "session:" + sid
        return "client:" + self._client_key()

    def _rate_limited(self, path: str, raw: bytes) -> dict | None:
        """과금 경로 요청 제한 → 막으면 429 본문, 통과면 None. IP 천장을 먼저 보고, 그다음 세션 칸 (H-15)."""
        client = "ip:" + self._client_key()
        # IP 천장은 사람으로 셀 수 있는 칸에만 — 팀(부스 노트북)은 행사장 와이파이의 방문자와 IP 를 나눠 써도 안 걸리고,
        # Cloudflare 서버·설비 IP 로 잡힌 공개 칸(여러 사람이 섞임)은 천장 대신 세션 칸만 센다. VM 안 요청은 예전처럼 센다 (방패 2026-10-05)
        ceiling = not getattr(_REQ, "team", False) and (getattr(self, "_local", False) or self._counted())
        if ceiling and not LIMITER.allow(client):
            key, scope = client, "ip"
        else:
            key = self._rate_bucket(path, raw)
            if LIMITER.allow(key):
                return None
            scope = "session" if key.startswith("session:") else "ip"
        if not getattr(_REQ, "trusted", False) and self._counted():
            self._strike(shield.ip_bucket(self._client_key()))  # 막혀도 계속 보내면 감옥 (방패)
        wait = LIMITER.retry_after(key)
        sys.stderr.write(f"[bridge] 요청 제한 {path} scope={scope} retry_after={wait}\n")
        # error·message·retry_after 는 예전 그대로 (프론트 qaApi 가 error→code, message 를 띄운다). rate_limited·scope 는
        # 프론트가 자동 재시도·출구 조건에서 이 턴을 뺄 때 쓰라고 더한 기계용 표시다.
        return {
            "error": "rate_limited",
            "rate_limited": True,
            "scope": scope,
            "retry_after": wait,
            "message": f"요청이 너무 잦아요. {wait}초 뒤에 다시 시도해 주세요.",
        }

    @staticmethod
    def _archive(body: dict, kind: str, payload: dict) -> None:
        """
        분석 산출물을 세션 보관소에 남긴다 (write-behind — 요청 결과에 영향 없음).

        mock 결과는 남기지 않는다 — 남의 자료를 내 결과로 착각하게 만드는 것과 같은
        종류의 거짓이다. 동의 없는 세션은 보관소가 거른다 (캐시 종류만 남긴다).
        """
        if _mock():
            return
        sid = _session_id_of(body)
        if sid:
            ARCHIVE.put_artifact(sid, kind, payload)

    def _handle_session_artifacts(self, raw: bytes):
        """
        세션 아티팩트 등록 · {session_id, graph?, alignment?, flow?, transcript?, context?}.

        한 번 올려 두면 이후 질문 생성·판정은 session_id 만 보내면 된다.
        판정마다 그래프·발화를 통째로 재업로드하던 것을 없애는 자리다.
        """
        body = json.loads(raw or b"{}")
        # 파싱 때 발급한 모양의 id 와 'flat'(발급 id 가 없는 경로의 자리표시자)만 받는다. 아무 문자열이나 받으면 로그에
        # 가짜 줄을 심거나, 한도(세션 32개)를 채워 남의 세션을 밀어낼 수 있다. 크기는 do_POST 의 경로별 상한이 막는다.
        # 판정(_resolve)도 같은 _store_sid 로 찾는다 — 둘이 다르게 거르면 flat 판정이 409 → 재등록 400 에 갇힌다 (B-06).
        session_id = _store_sid(body.get("session_id"))
        if not session_id:
            return self._json(400, {"error": "bad_request", "message": "session_id 가 필요합니다."})

        # 본문에 있는 키만 넘긴다 — body.get() 으로 전부 채우면 "안 보낸 키" 와
        # "null 로 지우겠다는 키" 가 구분되지 않는다 (put_artifacts 의 계약).
        stored = STORE.put_artifacts(session_id, {k: body[k] for k in ARTIFACT_KEYS if k in body})
        sys.stderr.write(f"[bridge] session artifacts sid={session_id} stored={stored}\n")
        return self._json(200, {"session_id": session_id, "stored": stored})

    @staticmethod
    def _path_session_id(path: str) -> str:
        """`/api/v1/sessions/{id}/…` 의 id. 모양이 틀리면 빈 문자열."""
        return ARCHIVE.safe_id(Handler._path_segment_after(path, "sessions")) or ""

    @staticmethod
    def _path_segment_after(path: str, name: str) -> str:
        """경로에서 name 바로 뒤 조각 (검사 없음 — 쓰는 쪽이 _store_sid·safe_id 로 거른다)."""
        parts = path.split("/")
        try:
            return parts[parts.index(name) + 1]
        except (ValueError, IndexError):
            return ""

    def _handle_feedback(self, path: str, raw: bytes):
        """
        POST /api/v1/sessions/{id}/feedback · {events:[FeedbackEvent…]}

        사용자가 누른 👍/👎·「이 판정은 아닌 것 같아요」·「이건 반복이 아니에요」.
        이것만이 라벨이다. 동의 세션에만 쌓이고, 종류·값·길이는 계약이 거른다.
        """
        from chuckchuck.contracts import FeedbackEvent

        sid = self._path_session_id(path)
        if not sid:
            return self._json(400, {"error": "bad_request", "message": "session_id 모양이 맞지 않아요."})
        body = json.loads(raw or b"{}")
        events = body.get("events")
        if not isinstance(events, list) or not events:
            return self._json(400, {"error": "bad_request", "message": "events 가 필요해요."})
        accepted = 0
        for item in events[:50]:
            try:
                ev = FeedbackEvent.from_dict(item if isinstance(item, dict) else {})
            except ValueError as e:
                return self._json(400, {"error": "bad_request", "message": str(e)})
            if not ev.at:
                ev.at = time.time()
            if ARCHIVE.append(sid, "feedback", ev.to_dict()):
                accepted += 1
        sys.stderr.write(f"[bridge] feedback sid={sid} accepted={accepted}/{len(events)}\n")
        return self._json(200, {"session_id": sid, "accepted": accepted})

    def do_DELETE(self):
        """DELETE /api/v1/sessions/{id} — 서버에 남은 그 발표의 모든 것을 지운다.

        있든 없든 204 다. 존재 여부를 알려 주는 것 자체가 정보이기 때문이다."""
        parsed = urlparse(self.path)
        if not self._gate():
            return
        try:
            if not (parsed.path.startswith("/api/v1/sessions/") and parsed.path.count("/") == 4):
                return self._json(404, {"error": "not found"})
            sid = self._path_session_id(parsed.path)
            if sid:
                removed = ARCHIVE.delete(sid)
                STORE.forget(sid)
                sys.stderr.write(f"[bridge] session delete sid={sid} removed={removed}\n")
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            try:
                self._json(500, {"error": "internal", "message": GENERIC_ERROR_MESSAGE})
            except Exception:  # noqa: BLE001
                return

    def _resolve(self, body: dict, *keys: str) -> dict:
        """
        본문에 없는 아티팩트를 세션 저장소에서 채운다.

        본문이 이긴다 — 방금 만든 결과를 들고 온 요청이 오래된 캐시에 밀리면 안 된다.
        **키가 없는 것과 null 은 다르다** (put_artifacts 와 같은 계약, 09-30 B-13). null 은 「이번 발표엔 이게 없다」 는
        선언이라 채우지 않는다 — 채우면 지운 줄 알았던 옛 발표의 flow·정합이 질문·판정 근거로 되살아난다.
        빈 값({}·[]·"")은 예전처럼 「안 보냄」 으로 보고 채운다.
        """
        found = {k: body.get(k) for k in keys}
        missing = [k for k in keys if not found[k] and not (k in body and body[k] is None)]
        if not missing:
            return found
        stored = STORE.artifacts(_store_sid(body.get("session_id")))
        for key in missing:
            found[key] = stored.get(key)
        return found

    def _handle_questions(self, raw: bytes):
        """F-08 · {graph, alignment?, flow?, transcript?, context, track} → QuestionDoc."""
        from chuckchuck.contracts import (
            QA_TRACK_FALLBACK,
            QA_TRACKS,
            AlignmentDoc,
            ConceptGraph,
            FlowDiff,
            QuestionError,
            Transcript,
        )

        body = json.loads(raw or b"{}")
        found = self._resolve(body, "graph", "alignment", "flow", "transcript", "context")
        if not found["graph"]:
            if body.get("session_id"):
                return self._json(409, {
                    "error": "session_missing",
                    "message": "세션 아티팩트가 없어요. 다시 등록하고 시도해 주세요.",
                })
            return self._json(400, {"error": "bad_request", "message": "graph 가 필요합니다."})
        graph = ConceptGraph.from_dict(found["graph"])
        alignment = AlignmentDoc.from_dict(found["alignment"]) if found["alignment"] else None
        flow = FlowDiff.from_dict(found["flow"]) if found["flow"] else None
        transcript = Transcript.from_dict(found["transcript"]) if found["transcript"] else None
        ctx = Context.from_dict(found["context"] or body.get("context") or {})
        track = str(body.get("track") or QA_TRACK_FALLBACK)
        if track not in QA_TRACKS:
            track = QA_TRACK_FALLBACK
        llm = _pick_llm(body)

        # triage 는 트랙과 무관하다 (f08_questions 모듈 주석). 같은 입력이면 1차 심사를
        # 재사용해 트랙만 바꾼 재요청이 LLM 1콜로 끝나게 한다 — 매번 다시 돌리면
        # temperature 탓에 1분 트랙 질문이 5분 트랙의 부분집합이라는 보장도 깨진다.
        # 근거 장 본문. 없으면 None 이고 F-08 은 예전 프롬프트로 돈다 (조용히 죽지 않는다).
        # 세션 아티팩트가 아니라 파싱 때 남긴 디스크 보관소에서 session_id 로 찾는다 —
        # 프론트는 slidedoc 을 안 들고 있고, 아티팩트 키를 늘리면 프론트 계약이 깨진다.
        # id 로만 찾으니 남의 자료가 붙을 길이 구조적으로 없다.
        slidedoc = ARCHIVE.read_artifact(_session_id_of(body), "slide_doc")
        # 장 단위 시간 배분 (F-17). 방금 /pace 가 concept_doc 과 함께 남긴 것만 쓴다 — 발화만으로 다시 재면
        # 장 중요도가 없어 보조 장(원인·사례)이 '덜 쓴 핵심 장' 으로 잘못 잡힌다 (09-29 수면 전사: 5·6장 0.37·0.46).
        pace = body.get("pace") or STORE.get_triage("pace:" + str(_session_id_of(body) or ""))

        # 미리 만든 질문 (2026-09-29 사용자 "매 요청 때 새로 만들지 말고 미리 준비"). 프론트가 분석이 끝나는 순간
        # 같은 요청을 body.prefetch=true 로 먼저 보내 둔다. 입력이 같으면 그 결과를 그대로 돌려주고, 아직 만드는 중이면
        # 새로 만들지 않고 그걸 기다린다. body.fresh=true 면 새로 만든다.
        # **지문은 문헌 검색 전에 정한다** — 문헌(F-24)은 외부 검색이라 동시에 두 번 돌면 결과가 달라서(09-29 실측
        # 4편 vs 3편), 문헌을 지문에 넣었더니 미리 만들기와 실제 요청이 서로를 못 알아보고 둘 다 LLM 을 불렀다.
        # 문헌·기억은 이 입력(그래프·본문·세션)에서 나오므로 세션 id 와 문헌 끄기 여부로 대신한다.
        q_key = "questions:" + fingerprint(
            found["graph"], found["alignment"], found["flow"], found["transcript"], ctx.to_dict(), track, str(llm),
            str(_session_id_of(body) or ""), bool(slidedoc), pace, body.get("papers") is False, body.get("memory") is False,
            # 코드 판 — F-08 과 재료(주장 F-26·문헌 F-24·기억 F-25)의 import 닫힘 전체. 주장·문헌의 **결과**는 넣지 않는다
            # (위 주석 — 넣으면 미리 만들기와 실제 요청이 서로를 못 알아본다). 대신 폴백으로 만든 묶음은 짧게만 든다.
            _stage_version("questions"), body.get("claims") is False,
        )
        label = "미리 만들기" if body.get("prefetch") else "요청"
        sys.stderr.write(f"[bridge] F-08 questions key={q_key[10:22]} track={track} ({label}) parts="
                         + ",".join(fingerprint(x)[:6] for x in (found["graph"], found["alignment"], found["flow"], found["transcript"],
                                                                  ctx.to_dict(), str(_session_id_of(body) or ""), pace)) + "\n")
        mine = None
        if not body.get("fresh"):
            ready = _questions_ready(q_key)
            if ready is not None:
                sys.stderr.write(f"[bridge] F-08 questions track={track} 미리 만든 질문을 씀 ({label})\n")
                self._index_questions(body, track, ready)
                return self._json(200, client_questions(ready))
            mine = _claim_questions(q_key)
            if mine is None:
                # 누가 같은 질문을 만드는 중이다 — 끝나길 기다렸다가 그 결과를 쓴다. 실패했으면 아래에서 직접 만든다.
                t0 = time.time()
                _wait_questions(q_key)
                ready = _questions_ready(q_key)
                if ready is not None:
                    sys.stderr.write(f"[bridge] F-08 questions track={track} 만들던 것을 {time.time() - t0:.1f}초 기다려 씀 ({label})\n")
                    self._index_questions(body, track, ready)
                    return self._json(200, client_questions(ready))
        try:
            papers, memory, claims, degraded = self._question_inputs(body, found["graph"], slidedoc, llm)
            if not slidedoc:
                # 본문이 없으면 근거 인용·주장·함정 전제가 전부 빠진다 — 조용히 옛 프롬프트로 가지 않고 표시한다
                degraded.insert(0, "slide_doc_missing")
            # 1차 심사(triage)의 입력 전부. 09-30: 예전 키에 context·transcript 가 빠져, 발표 상황을 바꿔 다시 만들어도
            # 옛 상황으로 고른 후보를 그대로 썼다 (triage 프롬프트는 둘 다 싣는다).
            # 본문도 1차 심사의 입력이다 (09-30 WP-J2 — WP-Q 요청: 탐침을 덱 전체로 검증하고 다른 발표 녹음을 거른다). 지문에 넣는다.
            cache_key = fingerprint(found["graph"], found["alignment"], found["flow"], found["transcript"], ctx.to_dict(),
                                    str(llm), memory.to_dict() if memory else None, pace,
                                    claims.to_dict() if claims else None, _stage_version("triage"),
                                    fingerprint(slidedoc) if slidedoc else None)
            return self._build_questions_payload(
                q_key, graph, alignment, flow, transcript, ctx, track, llm, body, found, slidedoc, papers, memory, pace, cache_key,
                claims=claims, degraded=degraded,
            )
        finally:
            if mine is not None:
                _release_questions(q_key, mine)

    def _index_questions(self, body: dict, track: str, payload: dict) -> None:
        """서버가 만든(또는 들고 있던) 질문을 이 세션의 채점 기준으로 남긴다 — 캐시로 돌려준 요청도 빠짐없이 (R4)."""
        sid = _store_sid(body.get("session_id"))
        if not sid:
            return
        STORE.remember_questions(sid, track, payload)
        # 질문마다 basis(근거·자리·탐침·인용·검사)가 실려 있다 — 세션에 트랙별로 붙여 두어 나중에 되짚는다 (P1).
        STORE.put_questions(sid, track, payload)

    def _question_inputs(self, body: dict, graph_raw: dict, slidedoc, llm) -> tuple:
        """
        질문의 재료 셋 — 문헌(F-24)·주장(F-26)·기억(F-25) → (papers, memory, claims, degraded).

        09-30 전엔 문헌 → 기억 → 주장을 **차례로** 불렀다. 학술 검색이 막히면 문헌만 ~60초 서 있었고(G-A9, 프론트 제한 60초),
        그 뒤에야 주장 LLM 이 돌았다. 이제 문헌과 주장을 **같이** 띄우고, 문헌은 PAPERS_DEADLINE_SEC(주장이 더 걸리면 그만큼)
        안에 안 오면 자료가 인용한 문헌만으로 간다 — 검색은 뒤에서 마저 끝나 캐시를 채우고, 다음 요청이 그걸 쓴다.
        같은 재료를 두 트랙이 동시에 만들면 한 번만 돈다 (_FLIGHTS, B-04). 못 쓴 재료는 degraded 에 코드로 남긴다.

        body.papers / body.memory / body.claims = false 면 끈다 (비교 벤치용) — 끈 것은 폴백이 아니다.
        """
        degraded: list[str] = []
        t0 = time.monotonic()
        sid = _session_id_of(body)
        # 부스 덱은 자료가 인용한 문헌이 없고, 학술 검색은 막히면 6초를 기다린 뒤 「폴백」 표시를 남겨 질문 캐시를 2분짜리로 만든다 — 건너뛴다
        want_papers = body.get("papers") is not False and not _booth_session(sid)
        # 주장은 본문이 있어야 인용을 원문과 대조할 수 있다 — 본문이 없으면 안 만든다 (slide_doc_missing 이 따로 알린다)
        want_claims = body.get("claims") is not False and bool(slidedoc)
        # 열쇠에 세션을 안 넣는다 — 메모리 캐시(papers:·claims:)가 원래 세션과 무관하게 입력으로 걸려 있다.
        # 부스처럼 여러 사람이 같은 샘플을 동시에 올리면 한 번만 검색한다.
        papers_fut = _FLIGHTS.run(
            "papers:" + fingerprint(graph_raw, bool(slidedoc), str(llm)),
            lambda: self._papers_for(body, graph_raw, slidedoc, llm),
        ) if want_papers else None
        claims_fut = _FLIGHTS.run(
            "claims:" + fingerprint(_canon(ConceptGraph, graph_raw), _canon(SlideDoc, slidedoc), str(llm)),
            lambda: self._claims_for(body, graph_raw, slidedoc, llm),
        ) if want_claims else None

        memory = None
        if body.get("memory") is not False:
            memory = self._memory_for(body)
            if memory is None and _memory_failed(sid):
                degraded.append("memory_failed")

        claims = None
        if claims_fut is not None:
            try:
                claims = claims_fut.result(timeout=CLAIMS_WAIT_SEC)
            except TimeoutError:
                sys.stderr.write(f"[bridge] F-26 claims {CLAIMS_WAIT_SEC:.0f}초 안에 안 끝남 — 주장 없이 진행\n")
                degraded.append("claims_timeout")
            except Exception as e:  # noqa: BLE001 — 주장은 재료다. 없으면 없다고 적고 간다
                sys.stderr.write(f"[bridge] F-26 claims 실패, 주장 없이 진행: {type(e).__name__}: {e}\n")
                degraded.append("claims_failed")
            else:
                if claims is None:
                    degraded.append("claims_failed")
                elif _claims_rule_only(claims, graph_raw, slidedoc):
                    degraded.append("claims_rule_only")

        papers = None
        if papers_fut is not None:
            wait = max(0.0, PAPERS_DEADLINE_SEC - (time.monotonic() - t0))
            try:
                papers = papers_fut.result(timeout=wait)
            except TimeoutError:
                sys.stderr.write(f"[bridge] F-24 papers {time.monotonic() - t0:.1f}초 — 제한({PAPERS_DEADLINE_SEC:.0f}초)을 넘겨 "
                                 "자료 인용만으로 진행 (검색은 뒤에서 마저 한다)\n")
                papers = _deck_only_papers(graph_raw, slidedoc, PAPERS_TIMEOUT_NOTE)
                degraded.append("papers_timeout")
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"[bridge] F-24 papers 실패, 문헌 없이 진행: {type(e).__name__}: {e}\n")
                degraded.append("papers_failed")
            else:
                if papers is None:
                    degraded.append("papers_failed")
                elif _papers_degraded(papers):
                    degraded.append(_papers_degraded(papers))
        return papers, memory, claims, degraded

    def _triage_for(self, cache_key: str, graph, alignment, flow, ctx, transcript, memory, pace, llm, claims, slidedoc=None):
        """
        1차 심사 — 캐시 → 같은 입력으로 도는 중이면 그걸 기다림 → 새로. 두 트랙이 동시에 불러도 LLM 은 한 번 (B-04).
        본문(slidedoc)을 넘긴다 (09-30 WP-J2, WP-Q 요청) — 탐침을 덱 전체의 해결 줄로 검증하고(`_probes.validate_probes`), 녹음이 자료와
        다른 발표면 녹음·정합을 버린다(`speech_matches_deck`). 예전엔 build_questions 만 본문을 받아 1차 심사는 탐침을 덱 없이 골랐다.
        """
        from chuckchuck import triage_questions

        triage = STORE.get_triage(cache_key)
        if triage is not None:
            sys.stderr.write("[bridge] F-08 triage cache hit\n")
            return triage

        def work():
            hit = STORE.get_triage(cache_key)       # 앞선 일이 막 끝났으면 그걸 쓴다
            if hit is not None:
                return hit
            fresh = triage_questions(
                graph, alignment, flow, ctx, transcript=transcript, memory=memory, pace=pace, llm=llm,
                **_claims_kw(triage_questions, claims), **_slidedoc_kw(triage_questions, slidedoc),
            )
            STORE.set_triage(cache_key, fresh)
            return fresh

        return _FLIGHTS.run("triage:" + cache_key, work).result()

    def _build_questions_payload(self, q_key, graph, alignment, flow, transcript, ctx, track, llm, body, found,
                                 slidedoc, papers, memory, pace, cache_key, claims=None, degraded=None):
        from chuckchuck import build_questions
        from chuckchuck.contracts import QuestionError

        degraded = list(degraded or [])
        try:
            triage = self._triage_for(cache_key, graph, alignment, flow, ctx, transcript, memory, pace, llm, claims,
                                      slidedoc=slidedoc)
            doc = build_questions(
                graph,
                triage,
                track=track,
                alignment=alignment,
                # flow 를 빼면 order_jump 개념의 질문이 missing_link 문구를 쓴다
                # (f08 _fallback_text 의 flow_issue 분기가 죽는다). 서버 라우트
                # (server/app.py)는 넘기는데 브리지만 빠져 있었다.
                flow=flow,
                transcript=transcript,
                # 근거 장 본문 — 모범답이 자료 밖 지식으로 살 붙이는 것을 막는다
                slidedoc=slidedoc,
                context=ctx,
                papers=papers,
                memory=memory,
                pace=pace,
                llm=llm,
                **_claims_kw(build_questions, claims),
            )
        except QuestionError as e:
            sys.stderr.write(f"[bridge] F-08 questions failed: {e}\n")
            return self._json(502, {"error": "questions_failed",
                                    "message": "예상 질문을 만들지 못했어요. 잠시 뒤 다시 해 주세요."})
        # 본문 유무를 남긴다. 조용히 빠지면 "왜 여전히 자료에 없는 말을 쓰지?" 를
        # 디버깅할 수 없다 (_handle_qa_judge 의 근거= 표시와 같은 이유).
        cited = sum(1 for q in doc.questions if q.paper_ids)
        remembered = len(memory.by_node(graph)) if memory else 0
        sys.stderr.write(
            f"[bridge] F-08 questions track={doc.track} n={len(doc.questions)} "
            f"model={doc.model} 본문={'yes' if slidedoc else '-'} "
            f"문헌={len(papers.refs) if papers else '-'} 인용질문={cited} "
            f"기억={remembered if memory else '-'} 주장={len(claims.claims) if claims else '-'}"
            f"{(' 폴백=' + ','.join(degraded)) if degraded else ''}\n"
        )
        payload = _with_degraded(with_hint_ladders(doc.to_dict(), doc.questions), degraded)
        # 폴백 재료로 만든 묶음은 짧게만 든다 — 미리 만들기 → 시작 한 쌍은 나눠 쓰고, 그 뒤 요청은 재료부터 다시 시도한다 (B-03)
        transient = [c for c in degraded if c in TRANSIENT_DEGRADED]
        STORE.set_triage(q_key, payload, ttl=FALLBACK_TTL_SEC if transient else None)
        if not transient and not degraded:
            _stage_cache_put("questions", _questions_disk_key(q_key), payload)
        # 색인·보관은 서버 사본(전제·기대 답 포함) — 채점 기준이다. 화면으로는 함정의 사실 칸을 뺀 사본만 (WP-J2).
        self._index_questions(body, track, payload)
        self._archive(body, "question_doc", payload)
        return self._json(200, client_questions(payload))

    def _memory_for(self, body: dict):
        """
        F-25 MemoryDoc. 메모리 캐시 → 보관소의 지난 세션(qa_turns)에서 새로 만들기. 지난 리허설이 없으면 None.

        같은 사람(learner_id)·같은 파일(sha256)의 **동의한** 세션만 잇는다 — session_archive.related_sessions 가 거른다.
        만든 기억은 이 세션의 memory_doc 아티팩트로 남긴다 (동의 세션만 저장된다). 실패해도 None — 기억은 있으면 좋은 재료다.
        단 실패는 「지난 리허설 없음」 과 다르게 남긴다 (MEMORY_FAILED_MARK, 짧게) — 질문 응답의 degraded 가 읽는다 (B-03).
        """
        from chuckchuck import build_memory

        sid = _session_id_of(body)
        if not sid or _mock():
            return None
        # 이번 발표의 그래프·자료를 넘겨야 다른 발표의 리허설이 기억·요약에서 빠지고(scoped), 지난 결손이 지금 자료로 다시
        # 확인된다 (09-30 WP-P). 그래프가 나중에 생기는 세션도 있어 캐시 열쇠에 그래프 지문을 넣는다 — 그래프 없이 만든
        # 기억(scoped=False)이 그래프를 가진 요청에 재사용되지 않게.
        graph = self._resolve(body, "graph").get("graph") or None
        slidedoc = ARCHIVE.read_artifact(sid, "slide_doc")
        # 실패 표시는 세션 열쇠에 둔다 — `_memory_failed(sid)` 가 degraded 를 알릴 때 그 열쇠를 본다
        fail_key = "memory:" + sid
        if STORE.get_triage(fail_key) == MEMORY_FAILED_MARK:
            return None                    # 방금 실패했다 — FALLBACK_TTL_SEC 뒤에 다시 읽어 본다
        key = fail_key + ":" + (fingerprint(graph)[:8] if graph else "nograph")
        cached = STORE.get_triage(key)
        if cached is not None:
            return cached or None          # 빈 dict 는 「지난 리허설 없음」 을 캐시한 것
        try:
            rehearsals, learner_key = ARCHIVE.rehearsals_for(sid)
            if not rehearsals:
                STORE.set_triage(key, {})
                return None
            me = ARCHIVE.manifest(sid)
            memory = build_memory(rehearsals, file_name=(me.file_name if me else ""), learner_key=learner_key,
                                  graph=graph, slidedoc=slidedoc)
        except Exception as e:  # noqa: BLE001 — 기억 없이도 질문·판정은 나와야 한다
            sys.stderr.write(f"[bridge] F-25 memory 실패, 기억 없이 진행: {type(e).__name__}: {e}\n")
            # 예전엔 {}(「지난 리허설 없음」)로 6시간 담아 실패가 없던 일이 됐다
            STORE.set_triage(fail_key, dict(MEMORY_FAILED_MARK), ttl=FALLBACK_TTL_SEC)
            return None
        sys.stderr.write(
            f"[bridge] F-25 memory key={memory.learner_key} sessions={len(memory.sessions)} "
            f"concepts={len(memory.concepts)} stalled={len(memory.stalled)}\n"
        )
        STORE.set_triage(key, memory)
        self._archive(body, "memory_doc", memory.to_dict())
        return memory

    def _handle_memory(self, raw: bytes):
        """F-25 · {session_id} → MemoryDoc. 지난 리허설이 없으면 빈 문서(note 에 사유). 화면이 「지난번보다」 를 그릴 때."""
        from chuckchuck.contracts import MemoryDoc

        body = json.loads(raw or b"{}")
        if not _session_id_of(body):
            return self._json(400, {"error": "bad_request", "message": "session_id 가 필요합니다."})
        memory = self._memory_for(body)
        if memory is None and _memory_failed(_session_id_of(body)):
            # 못 읽은 것을 「지난 리허설 없음」 으로 말하면 거짓이다 (CLAUDE.md §4 — 실패는 실패로)
            return self._json(503, {"error": "memory_failed", "retry_after": int(FALLBACK_TTL_SEC),
                                    "message": "지난 리허설 기억을 읽지 못했어요. 잠시 뒤 다시 해 주세요."})
        if memory is None:
            return self._json(200, MemoryDoc(note="지난 리허설 없음 — 학습 동의를 켠 지난 세션이 있어야 이어져요").to_dict())
        return self._json(200, memory.to_dict())

    def _papers_for(self, body: dict, graph_raw: dict | None, slidedoc, llm):
        """
        F-24 PaperDoc. 보관소(paper_doc, **같은 그래프로 만든 것만**) → 메모리 캐시 → 새로 만들기 순.

        mock 모드에서는 검색을 부르지 않는다 (scholar="none") — 자료 인용(deck)만 나온다.
        실 API 모드의 provider 는 SCHOLAR_PROVIDER 환경변수가 정한다 (기본 none).
        실패해도 None 을 돌려주고 질문 생성은 그대로 간다 — 문헌은 있으면 좋은 재료지 필수가 아니다.

        09-30 (B-03·B-11·B-14): ① 보관본은 그래프 지문이 같을 때만 쓴다 — 같은 세션에서 그래프를 다시 만들면 옛 문헌의
        node_ids 가 새 그래프와 안 맞았다. ② 검색이 실패한 문헌(429·시간 초과로 자료 인용만 남은 것)은 **보관하지 않고**
        짧게만 든다 — 보관본은 다음 요청이 그대로 다시 써서 세션 끝까지 빈 문헌이었다. ③ 실패한 통로는 잠시 쉰다
        (PAPERS_NEGATIVE_TTL_SEC) — 그동안은 부르지 않고 자료 인용만 쓴다 (note 로 알린다).
        """
        from chuckchuck import build_papers
        from chuckchuck.contracts import PaperDoc

        if not graph_raw:
            return None
        sid = _session_id_of(body)
        graph_fp = fingerprint(graph_raw, bool(slidedoc))
        stored = ARCHIVE.read_artifact(sid, "paper_doc") if sid else None
        if stored and stored.get(PAPERS_GRAPH_FP_KEY) == graph_fp:
            return PaperDoc.from_dict(stored)
        if stored:
            sys.stderr.write("[bridge] F-24 보관된 문헌은 다른 그래프(또는 옛 판)로 만든 것 — 새로 만든다\n")
        scholar = "none" if _mock() else None
        key = "papers:" + fingerprint(graph_raw, bool(slidedoc), str(scholar), str(llm))
        cached = STORE.get_triage(key)   # 지문별 캐시 — triage 와 같은 통을 쓴다 (키 접두어로 구분)
        if cached is not None:
            return cached
        spec = _papers_spec(scholar)
        resting = _papers_down_left(spec)
        if resting > 0:
            sys.stderr.write(f"[bridge] F-24 검색 통로 {spec} 쉬는 중({resting:.0f}초 남음) — 자료 인용만\n")
            return _deck_only_papers(graph_raw, slidedoc, PAPERS_RESTING_NOTE)
        try:
            papers = build_papers(graph_raw, slidedoc, scholar=scholar, llm=llm)
        except Exception as e:  # noqa: BLE001 — 문헌 없이도 질문은 나와야 한다
            sys.stderr.write(f"[bridge] F-24 papers 실패, 문헌 없이 진행: {type(e).__name__}: {e}\n")
            _mark_papers_down(spec, type(e).__name__)
            return None
        degraded = _papers_degraded(papers)
        sys.stderr.write(
            f"[bridge] F-24 papers provider={papers.provider} deck={len(papers.deck_refs)} "
            f"scholar={len(papers.scholar_refs)}{(' · ' + papers.note) if papers.note else ''}"
            f"{(' → 폴백 ' + degraded) if degraded else ''}\n"
        )
        if degraded:
            if degraded == "papers_unavailable":
                _mark_papers_down(spec, papers.note[:80])
            STORE.set_triage(key, papers, ttl=FALLBACK_TTL_SEC)
            return papers
        STORE.set_triage(key, papers)
        self._archive(body, "paper_doc", {**papers.to_dict(), PAPERS_GRAPH_FP_KEY: graph_fp})
        return papers

    def _claims_for(self, body: dict, graph_raw: dict | None, slidedoc, llm):
        """
        F-26 ClaimDoc. 메모리 캐시 → 디스크 단계 캐시 → 새로 만들기 순. 본문(slidedoc)이 없으면 None.

        보관소(claim_doc)에서 되읽지 않는다 — 그래프가 다시 만들어지면 옛 주장의 id 가 안 맞는다. 키는 그래프·본문·
        코드 판(`_stage_version` — f26 의 import 닫힘: 대조 규칙 _claim_rules·_claim_quote·_evidence·_match 까지)이라
        프롬프트·대조 규칙을 고치면 저절로 새로 만든다 (7756058 과 같은 규율 — 09-30 전엔 f26 파일 하나만 셌다).
        LLM 이 죽어 규칙 주장만 나온 것(model="rule")은 디스크에 남기지 않고 메모리에도 FALLBACK_TTL_SEC 만 든다 —
        09-30 전엔 메모리에 6시간 담겨, 다음 요청이 LLM 을 다시 불러 볼 기회가 세션 끝까지 없었다 (B-03).
        실패해도 None — 주장은 질문의 재료지 필수가 아니다 (질문 응답의 degraded 가 알린다).
        """
        from chuckchuck import build_claims
        from chuckchuck.contracts import ClaimDoc

        if not graph_raw or not slidedoc:
            return None
        # 계약 모양으로 센다 — 보관된 slide_doc 에는 파싱 때 붙인 session_id·preview_pdf 가 있어 날 본문이면 세션마다 키가 갈린다 (M-14)
        key = _stage_key("f26", _stage_version("claims"), _llm_identity(llm), _canon(ConceptGraph, graph_raw),
                         _canon(SlideDoc, slidedoc))
        cached = STORE.get_triage("claims:" + key)
        if cached is not None:
            return cached
        disk = _stage_cache_get("claims", key)
        if disk is not None:
            claims = ClaimDoc.from_dict(disk)
            sys.stderr.write(f"[bridge] F-26 claims 캐시 적중 {key} n={len(claims.claims)}\n")
        else:
            try:
                claims = build_claims(graph_raw, slidedoc, llm=llm)
            except Exception as e:  # noqa: BLE001 — 주장 없이도 질문은 나와야 한다
                sys.stderr.write(f"[bridge] F-26 claims 실패, 주장 없이 진행: {type(e).__name__}: {e}\n")
                return None
            sys.stderr.write(
                f"[bridge] F-26 claims n={len(claims.claims)} dropped={claims.dropped} model={claims.model}\n"
            )
            if claims.model != "rule":
                _stage_cache_put("claims", key, claims.to_dict())
        rule_only = _claims_rule_only(claims, graph_raw, slidedoc)
        STORE.set_triage("claims:" + key, claims, ttl=FALLBACK_TTL_SEC if rule_only else None)
        self._archive(body, "claim_doc", claims.to_dict())
        return claims

    def _handle_claims(self, raw: bytes):
        """F-26 · {graph | session_id} → ClaimDoc. 본문(slide_doc)은 파싱 보관소에서 session_id 로 찾는다 (body.slide_doc 도 받는다)."""
        body = json.loads(raw or b"{}")
        found = self._resolve(body, "graph")
        if not found["graph"]:
            return self._json(400, {"error": "bad_request", "message": "graph 또는 session_id 가 필요합니다."})
        slidedoc = body.get("slide_doc") or ARCHIVE.read_artifact(_session_id_of(body), "slide_doc")
        if not slidedoc:
            return self._json(409, {"error": "slide_doc_missing",
                                    "message": "자료 본문이 있어야 주장을 원문과 대조할 수 있어요. 자료를 다시 올려 주세요."})
        claims = self._claims_for(body, found["graph"], slidedoc, _pick_llm(body))
        if claims is None:
            return self._json(502, {"error": "claims_failed", "message": "주장 그래프를 만들지 못했어요."})
        rule_only = _claims_rule_only(claims, found["graph"], slidedoc)
        return self._json(200, _with_degraded(claims.to_dict(), ["claims_rule_only"] if rule_only else []))

    def _handle_papers(self, raw: bytes):
        """F-24 · {graph | session_id} → PaperDoc. 화면이 「교수가 읽고 온 문헌」 카드를 그릴 때."""
        body = json.loads(raw or b"{}")
        found = self._resolve(body, "graph")
        if not found["graph"]:
            return self._json(400, {"error": "bad_request", "message": "graph 또는 session_id 가 필요합니다."})
        slidedoc = ARCHIVE.read_artifact(_session_id_of(body), "slide_doc")
        llm = _pick_llm(body)
        papers = self._papers_for(body, found["graph"], slidedoc, llm)
        if papers is None:
            return self._json(502, {"error": "papers_failed", "message": "문헌을 만들지 못했어요."})
        code = _papers_degraded(papers)
        return self._json(200, _with_degraded(papers.to_dict(), [code] if code else []))

    def _handle_papers_search(self, raw: bytes):
        """F-24 · {query, limit?} → PaperDoc. 자유 질문에 대한 논문 검색 (품질 순)."""
        from chuckchuck import search_papers
        from chuckchuck.contracts import PAPER_SEARCH_MAX

        body = json.loads(raw or b"{}")
        query = str(body.get("query") or "").strip()
        if not query:
            return self._json(400, {"error": "bad_request", "message": "query 가 필요합니다."})
        if len(query) > PAPER_QUERY_MAX_CHARS:
            return self._json(413, {"error": "too_large", "message": f"검색어는 {PAPER_QUERY_MAX_CHARS}자까지 쓸 수 있어요."})
        try:
            limit = max(1, min(int(body.get("limit") or PAPER_SEARCH_MAX), 20))
        except (TypeError, ValueError):
            limit = PAPER_SEARCH_MAX
        scholar = "none" if _mock() else None
        llm = _pick_llm(body)
        papers = search_papers(query, limit=limit, scholar=scholar, llm=llm)
        sys.stderr.write(
            f"[bridge] F-24 search provider={papers.provider} n={len(papers.refs)}"
            f"{(' · ' + papers.note) if papers.note else ''}\n"
        )
        return self._json(200, papers.to_dict())

    def _handle_qa_judge(self, raw: bytes, path_sid: str = ""):
        """F-09 · {session_id?, question_id, answer, history?, question?, give_up?} → QaJudgement (+근거 표시).

        **채점 기준(질문)은 서버가 정한다** (09-30 감사 R4·B-07·B-12). 예전엔 프론트가 보낸 question 본문으로 판정해서,
        본문의 trap·trap_premise·basis 를 지우거나 answer_gist 를 고쳐 보내는 것만으로 채점이 바뀌었다 — HTTP 재현:
        함정에 동의한 답이 wrong 0 → good 80 (labs/qa_redteam bridge_tamper2). 그리고 그 턴이 qa_turns 에 남아 F-25 기억과
        학습 묶음으로 흘러갔다.

        이제 이 세션에서 서버가 만든 질문(질문 색인 → 동의 세션의 보관본)을 question_id 로 찾아 **그걸로** 판정한다.
        본문의 question 은 트랙이 여럿일 때 어느 판인지 고르는 데만 쓴다 (문장이 같은 것). 서버에 없는 질문일 때만 본문으로
        판정하되 길이를 자르고 grounded_on_server=false 로 알리며, 그 턴은 기록에 남기지 않는다.

        응답에는 판정과 함께 grounded_on_server · grounded_on_deck(자료 본문 대조 여부) · degraded · degraded_notes 가 실린다.
        세션 id 는 본문이 먼저, 없으면 경로(/sessions/{id}/qa/judge)의 것. 발급 모양 또는 'flat' 만 받는다 (B-06).
        """
        from chuckchuck import judge_answer
        from chuckchuck.contracts import (
            AlignmentDoc,
            ConceptGraph,
            JudgeError,
            Transcript,
        )

        body = json.loads(raw or b"{}")
        raw_sid = body.get("session_id") if body.get("session_id") is not None else (path_sid or None)
        store_sid = _store_sid(raw_sid)
        if raw_sid and not store_sid:
            return self._json(400, {"error": "bad_request", "message": "session_id 모양이 맞지 않아요."})
        # 이후 _resolve·_session_id_of·_memory_for 가 모두 이 id 를 본다 ('flat' 은 보관소 쪽에서 저절로 빈 id 가 된다)
        body = {**body, "session_id": store_sid or None}
        body, too_long = _clip_judge_inputs(body)
        if too_long:
            return self._json(413, {"error": "too_large", "message": too_long})

        qraw = body.get("question") if isinstance(body.get("question"), dict) else None
        qid = str(body.get("question_id") or (qraw or {}).get("id") or "")
        try:
            question, qsrc = self._resolve_question(store_sid, _session_id_of(body), qid, qraw)
        except (AttributeError, KeyError, TypeError, ValueError):   # 본문 질문의 모양이 계약과 다르다
            return self._json(400, {"error": "bad_request", "message": "질문 형식이 맞지 않아요."})
        if question is None:
            return self._json(400, {"error": "bad_request",
                                    "message": "판정할 질문이 없어요. question_id 와 question 을 같이 보내 주세요."})
        if not question.question.strip():
            return self._json(400, {"error": "bad_request", "message": "질문 문장이 비어 있어요."})
        if body.get("reveal") is True:
            # 「답 보고 다시 말해보기」 — 화면에 없는 함정의 기대 답을 **사용자가 펼치겠다고 할 때만** 준다 (09-30 WP-J2, `client_questions`).
            # 판정이 아니다: LLM 을 부르지 않고, 기록(qa_turns)에도 남기지 않는다. 서버가 만든 질문으로만 — 본문 질문이면 그 본문 그대로다.
            on_server = qsrc in ("server", "archive", "mismatch")
            sys.stderr.write(f"[bridge] F-09 reveal q={question.id} 질문={qsrc}\n")
            return self._json(200, {"question_id": question.id, "reveal": True, "grounded_on_server": on_server,
                                    **reveal_fields(question)})
        # 자료 근거 없이 판정하면 '자료와 어긋난다'(wrong)를 대조할 원본이 없고
        # 함정 질문의 핵심 규칙도 짐작이 된다. 본문에 없으면 세션에서 끌어온다.
        found = self._resolve(body, "graph", "alignment", "transcript", "context")
        # session_id 를 들고 왔는데 근거가 통째로 비었다면 세션이 날아간 것이다
        # (브리지 재시작). 조용히 근거 없이 판정하지 말고 다시 등록하게 알린다.
        if store_sid and not any(found[k] for k in ("graph", "alignment", "transcript")):
            return self._json(409, {
                "error": "session_missing",
                "message": "세션 아티팩트가 없어요. 다시 등록하고 시도해 주세요.",
            })
        graph = ConceptGraph.from_dict(found["graph"]) if found["graph"] else None
        alignment = AlignmentDoc.from_dict(found["alignment"]) if found["alignment"] else None
        transcript = Transcript.from_dict(found["transcript"]) if found["transcript"] else None
        ctx = Context.from_dict(found["context"] or body.get("context") or {})
        llm = _pick_llm(body)
        # 자료 본문 — 판정이 "자료와 어긋난다" 를 대조할 원본. F-08 과 같은 디스크
        # 보관소에서 session_id 로 찾는다 (프론트는 slidedoc 을 안 들고 있다).
        slidedoc = ARCHIVE.read_artifact(_session_id_of(body), "slide_doc")
        degraded: list[str] = []
        if not slidedoc:
            # 09-30: 세션 id 를 들고 왔는데 본문이 없으면(하루 캐시 만료·보관 실패·flat) 예전엔 로그의 doc=- 한 글자로만
            # 남기고 조용히 대조 없이 판정했다. 409 로 막지 않는다 — 판정 화면은 409 를 「자료 정보가 사라졌다」 로 보여
            # 이어서 연습할 길을 끊는다(qa_live·booth). 판정은 하되 응답이 대조하지 않았다고 말한다.
            degraded.append("slide_doc_missing")
        if qsrc == "mismatch":
            degraded.append("question_mismatch")
        elif qsrc == "client":
            degraded.append("question_unverified")
        memory = self._memory_for(body)
        if memory is None and _memory_failed(_session_id_of(body)):
            degraded.append("memory_failed")
        try:
            judgement = judge_answer(
                question,
                str(body.get("answer", "") or ""),
                graph=graph,
                alignment=alignment,
                transcript=transcript,
                history=body.get("history") or [],
                context=ctx,
                give_up=bool(body.get("give_up")),
                # 이 질문에 앞서 낸 답변들. 판정은 누적 전체를 본다 (f09._answer_block).
                prior_answers=prior_answers_from(body),
                # 보여준 힌트 — 안 실으면 힌트를 따라온 답에 코치가 맥락 없이 반응한다
                hints_shown=[str(h) for h in (body.get("hints_shown") or []) if str(h).strip()],
                llm=llm,
                slidedoc=slidedoc,
                # 지난 리허설 기억 (F-25) — 지난번에 빠졌던 점이 이번엔 나왔는지 본다. 포기하면 코칭 단계도 이것이 정한다
                memory=memory,
            )
        except JudgeError as e:
            sys.stderr.write(f"[bridge] F-09 judge failed: {e}\n")
            return self._json(502, {"error": "judge_failed",
                                    "message": "답변을 판정하지 못했어요. 잠시 뒤 다시 답해 주세요."})
        on_server = qsrc in ("server", "archive", "mismatch")
        sys.stderr.write(
            f"[bridge] F-09 judge q={question.id} verdict={judgement.verdict} "
            f"passed={judgement.passed} stage={judgement.coach_stage!r} 질문={qsrc} "
            f"근거={'graph' if graph else '-'}/{'align' if alignment else '-'}"
            f"/{'stt' if transcript else '-'}/{'doc' if slidedoc else '-'}"
            f"{(' 폴백=' + ','.join(degraded)) if degraded else ''}\n"
        )
        # 화면 사본에서 뺀 기대 답(`client_questions`)은 **바로잡았거나(통과)·닫혔거나·해설 단계일 때** 판정 응답으로 준다 — 화면의
        # 「빠진 절반·완성 문장」(revealHalf)·마무리 카드(finishLiveQuestion)·해설 뒤 다시 말하기가 이것을 읽는다 (09-30 WP-J2).
        # 그 전의 함정 질문은 판정 근거 줄(grounds)에서도 사실 줄·빠진 줄을 뺀다 (`client_judgement`, 2026-10-01).
        payload = _with_degraded(
            {**client_judgement(question, judgement), "grounded_on_server": on_server, "grounded_on_deck": bool(slidedoc)},
            degraded)
        # 질문·답·판정 한 턴을 남긴다 (동의 세션만). 사람이 고친 판정과 짝을 맞출 원본이다.
        # **서버가 만든 질문으로 채점한 턴만** 남긴다 — 본문 질문으로 채점한 턴은 기준을 믿을 수 없고, 남기면 F-25 기억과
        # 학습 묶음(learning_jobs)으로 흘러가 다음 리허설의 질문·판정 프롬프트에 실린다.
        if not _mock() and _session_id_of(body) and on_server:
            ARCHIVE.append(_session_id_of(body), "qa_turns", {
                "at": time.time(),
                "question_id": question.id,
                "question": question.to_dict(),
                "answer": str(body.get("answer", "") or ""),
                "prior_answers": prior_answers_from(body),
                "hints_shown": [str(h) for h in (body.get("hints_shown") or [])],
                "give_up": bool(body.get("give_up")),
                "judgement": payload,
                "question_source": qsrc,
            })
        elif not on_server and _session_id_of(body):
            sys.stderr.write(f"[bridge] F-09 판정 기록 안 함 — 서버가 만든 질문이 아님 (q={question.id})\n")
        return self._json(200, payload)

    def _resolve_question(self, store_sid: str, archive_sid: str, qid: str, qraw: dict | None):
        """
        채점 기준이 될 질문 → (Question | None, 출처).

        출처: server(이 세션 질문 색인) · archive(동의 세션의 question_doc 보관본 — 브리지를 다시 띄운 뒤) ·
        mismatch(서버 것이 있지만 화면 문장과 달라 서버의 최신 판으로 채점) · client(서버에 없어 본문 그대로, 길이 자름) ·
        missing(아무것도 없음).

        같은 id 가 트랙마다 있으면(트랙끼리 triage 를 나눠 써 id 가 같다) **문장이 같은 판**을 고른다. 'flat' 은 모두가 나눠 쓰는
        자리라 다른 덱의 같은 id(q01-c1 …)가 있을 수 있다 — flat 에서는 문장까지 같을 때만 서버 판을 쓴다.
        """
        from chuckchuck.contracts import Question

        client_text = str((qraw or {}).get("question") or "").strip()
        src = "server"
        candidates = STORE.find_questions(store_sid, qid) if store_sid and qid else []
        if not candidates and archive_sid and qid:
            doc = ARCHIVE.read_artifact(archive_sid, "question_doc") or {}
            candidates = [q for q in (doc.get("questions") or []) if isinstance(q, dict) and str(q.get("id", "")) == qid]
            src = "archive"
        if candidates and store_sid != FLAT_SESSION_ID and not client_text:
            return Question.from_dict(candidates[0]), src          # 본문 질문 없이 id 만 — 서버의 최신 판 (고를 문장이 없다)
        exact = next((q for q in candidates if str(q.get("question") or "").strip() == client_text), None)
        if exact is not None and client_text:
            return Question.from_dict(exact), src
        if candidates and store_sid != FLAT_SESSION_ID:
            return Question.from_dict(candidates[0]), "mismatch"
        if not qraw:
            return None, "missing"
        capped = _capped(qraw)
        capped["id"] = str(capped.get("id") or qid or "q-client")[:120]
        return Question.from_dict(capped), "client"

    def _json(self, code: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def send_header(self, keyword, value):
        if keyword.lower() == "cache-control":
            self._cache_header_sent = True
        super().send_header(keyword, value)

    def end_headers(self):
        for k, v in getattr(self, "_extra_headers", None) or ():
            self.send_header(k, v)  # Retry-After 등 방패가 얹는 머리글 (_add_header)
        self._extra_headers = []
        # 캐시 규칙을 따로 정하지 않은 응답(API·오류·리다이렉트)은 저장하지 않는다.
        # 정적 파일은 _serve_static 이 정한다 — 주소에 내용 해시가 있어 오래 캐시해도 옛 판이 안 남는다
        if not getattr(self, "_cache_header_sent", False):
            self.send_header("Cache-Control", "no-store")
        self._cache_header_sent = False  # keep-alive 로 이어지는 다음 응답은 처음부터
        # CORS 는 허용 목록에 있는 origin 에만 연다. 브리지가 UI 를 같이 서빙하므로
        # 기본 경로는 같은 출처라 헤더가 아예 필요 없다 — '*' 는 브리지를 외부에
        # 노출했을 때 아무 페이지나 과금 API 를 부를 수 있게 하는 문이었다.
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if origin and origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        if not self._gate():
            return
        self.send_response(204)
        self.end_headers()


def _deck_shas() -> dict[str, dict]:
    """저장소 ppt/ 덱 원본 sha256 → 그 덱 줄(Handler._deck_entries). A·B 버전처럼 바이트가 같은 자료는 한 줄로 모인다."""
    out: dict[str, dict] = {}
    for row in Handler._deck_entries():
        try:
            sha = hashlib.sha256(_deck_path(row).read_bytes()).hexdigest()
        except OSError:
            continue
        out.setdefault(sha, row)
    return out


_BOOTH_SHAS: dict = {"at": 0.0, "shas": frozenset()}
BOOTH_SHAS_TTL_SEC = 600


def _booth_session(sid: str | None) -> bool:
    """이 세션의 자료가 부스 시연 세트(ppt/decks.json group "booth")의 덱 원본인가 — 올린 파일 sha256 으로 본다.
    부스는 고정 덱 · 고정 녹음이라 문헌 검색을 기다릴 까닭이 없다 (10-06 사용자: 「부스용은 새로운 ppt 없으니 로딩 시간 줄이기」)."""
    if not sid:
        return False
    now = time.monotonic()
    if now - _BOOTH_SHAS["at"] > BOOTH_SHAS_TTL_SEC:
        manifest = Handler._deck_manifest()
        shas = frozenset(sha for sha, row in _deck_shas().items()
                         if (manifest["decks"].get(unicodedata.normalize("NFC", row["key"])) or {}).get("group") == "booth")
        _BOOTH_SHAS.update(at=now, shas=shas)
    rec = ARCHIVE.manifest(sid)
    return bool(rec and rec.upload_sha256 and rec.upload_sha256 in _BOOTH_SHAS["shas"])


def _deck_path(row: dict) -> Path:
    base = DECKS_DIR / row["key"]
    return base / row["deck"] if base.is_dir() else base


def _prune_once() -> None:
    try:
        # 시연 덱 파싱본은 남긴다 — 하루 청소가 지우면 /rehearsal · /booth/qa 발표 목록이 빈다 (10-05)
        gone = ARCHIVE.prune(keep_sha256=_deck_shas().keys())
    except Exception as e:  # noqa: BLE001 — 청소 실패로 브리지를 죽이지 않는다
        sys.stderr.write(f"[bridge] 만료 세션 정리 실패: {e}\n")
        return
    sys.stderr.write(f"[bridge] 만료 세션 정리: {len(gone)}건 지움\n")


def _refresh_learning_once() -> None:
    """동의 세션 → 평가 묶음(var/data/derived/eval_bundles) + 또래 표. 0건이면 아무것도 쓰지 않는다."""
    try:
        r = refresh_learning_assets(ARCHIVE, bundles_dir=DERIVED_DIR / "eval_bundles",
                                    norms_path=DERIVED_DIR / "norms" / "percentile_table.json")
    except Exception as e:  # noqa: BLE001 — 자산 갱신 실패로 브리지를 죽이지 않는다
        sys.stderr.write(f"[bridge] 학습 자산 갱신 실패: {e}\n")
        return
    if not r["written"]:
        sys.stderr.write("[bridge] 학습 자산: 동의 세션 0건 — 건너뜀\n")
        return
    sys.stderr.write(f"[bridge] 학습 자산: 동의 세션 {r['consented']}건 → 평가 묶음 {r['bundles']}건 · "
                     f"또래 표 {r['norm_sessions']}건/{r['norm_rows']}줄\n")


#: 서버가 뜰 때 파싱본이 없으면 미리 파싱해 두는 덱 묶음(ppt/decks.json group). 0/빈 값이면 끈다.
WARM_DECK_GROUPS = frozenset(g.strip() for g in os.environ.get("DEMO_WARM_DECK_GROUPS", "booth,demo").split(",") if g.strip())


def _warm_decks_once(port: int) -> None:
    """
    부스 · 데모 덱 중 파싱본이 없는 것을 이 브리지의 /api/v1/parse 로 올려 둔다 (10-05).

    발표 고르기 화면(rehearsal.js · booth_qa.js bqDeckReady)은 파싱본(cached_session_id)이 있는 덱만 보여 준다. 예전엔 누가
    #/test/qa 에서 한 번 열어야 생겼고, 청소가 지우면 아무도 모른 채 목록이 비었다. 같은 파일은 단계 캐시가 받아 Upstage 를
    다시 부르지 않을 수도 있다. 실패해도 브리지는 그대로 — 로그만 남긴다.
    """
    import urllib.request

    if _mock() or not WARM_DECK_GROUPS:
        return
    groups = Handler._deck_manifest()["decks"]
    for sha, row in _deck_shas().items():
        meta = groups.get(unicodedata.normalize("NFC", row["key"]), {})
        if meta.get("group") not in WARM_DECK_GROUPS or ARCHIVE.find_by_sha256(sha):
            continue
        path = _deck_path(row)
        boundary = "chuckchuck-warm-" + sha[:16]
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{path.name}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/parse", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=300) as res:
                res.read()
            ok = ARCHIVE.find_by_sha256(sha)
            sys.stderr.write(f"[bridge] 시연 덱 미리 파싱 {row['key']} → {ok or '세션 없음'} ({time.monotonic() - t0:.1f}초)\n")
        except Exception as e:  # noqa: BLE001 — 미리 파싱 실패로 브리지를 죽이지 않는다
            sys.stderr.write(f"[bridge] 시연 덱 미리 파싱 실패 {row['key']}: {e}\n")


def _start_prune_loop() -> None:
    """시작할 때 한 번, 그 뒤 하루에 한 번. About 화면의 「1년 뒤 지워요」를 이 스레드가 지키고,
    지운 뒤의 동의 세션으로 학습 자산을 다시 만든다 (지운 세션이 묶음에 남지 않게 순서가 중요하다)."""
    def loop():
        while True:
            _prune_once()
            _refresh_learning_once()
            _warm_decks_once(settings.demo_port)
            time.sleep(PRUNE_INTERVAL_SEC)
    threading.Thread(target=loop, name="archive-prune", daemon=True).start()


def _busy_raw(retry: int) -> bytes:
    """연결 상한을 넘었을 때 핸들러 스레드 없이 바로 쓰는 응답 — 요청을 읽지도 않는다 (방패)."""
    body = json.dumps({"error": "busy", "busy": True, "rate_limited": True, "scope": "connections",
                       "retry_after": retry, "message": f"지금 사용자가 많아요. {retry}초 뒤에 다시 시도해 주세요."},
                      ensure_ascii=False).encode("utf-8")
    head = (f"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json; charset=utf-8\r\n"
            f"Retry-After: {retry}\r\nCache-Control: no-store\r\nConnection: close\r\n"
            f"Content-Length: {len(body)}\r\n\r\n").encode("ascii")
    return head + body


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    """
    요청 하나 = 스레드 하나(ThreadingHTTPServer) + 방패의 연결 상한 (2026-10-05).

    예전엔 연결이 오는 대로 스레드를 만들었다 — 느린 연결 수천 개면 스레드 수천 개다. 이제 동시에 붙잡는 연결이
    max_connections 를 넘으면 스레드를 만들지 않고 짧은 503 을 쓰고 바로 닫는다. listen 대기열(request_queue_size)은
    기본 5 라 순간 몰림에 SYN 이 버려졌다 — 넉넉히 둔다. 느린 연결 감시(WATCHDOG)도 여기서 켠다.
    """

    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = max(5, LISTEN_BACKLOG)

    def __init__(self, *args, max_connections: int | None = None, **kwargs) -> None:
        self.max_connections = MAX_CONNECTIONS if max_connections is None else max_connections
        self._conn_lock = threading.Lock()
        self.active_connections = 0
        self.peak_connections = 0
        self.refused_connections = 0
        super().__init__(*args, **kwargs)
        WATCHDOG.start()

    def process_request(self, request, client_address):
        with self._conn_lock:
            full = 0 < self.max_connections <= self.active_connections
            if full:
                self.refused_connections += 1
            else:
                self.active_connections += 1
                self.peak_connections = max(self.peak_connections, self.active_connections)
        if full:
            EVENTS.add("conn_refused")
            SHIELD_LOG.write("conn_full", f"연결 상한 {self.max_connections} — 새 연결을 503 으로 돌려보냄")
            return self._refuse(request)
        try:
            return super().process_request(request, client_address)
        except BaseException:
            self._release_conn()  # 스레드를 못 만들었다 — 센 것을 되돌린다 (BaseServer 가 소켓을 닫는다)
            raise

    def process_request_thread(self, request, client_address):
        try:
            return super().process_request_thread(request, client_address)
        finally:
            self._release_conn()

    def _release_conn(self) -> None:
        with self._conn_lock:
            self.active_connections = max(0, self.active_connections - 1)

    def _refuse(self, request) -> None:
        try:
            request.setblocking(False)
            request.send(_busy_raw(PAID_RETRY_SEC))
        except OSError:
            pass
        self.shutdown_request(request)

    def handle_error(self, request, client_address):
        # 끊긴 연결·시한 초과는 버그가 아니다 — 추적을 통째로 찍지 않고 10초에 한 줄
        if isinstance(sys.exc_info()[1], OSError):
            SHIELD_LOG.write("conn_error", f"연결 오류 {type(sys.exc_info()[1]).__name__}")
            return
        super().handle_error(request, client_address)


def bind_refusal(host: str, mock: bool) -> str:
    """
    이 주소로 띄우면 안 되는 이유. 괜찮으면 빈 문자열.

    실 API 모드에서 루프백이 아닌 주소는 **시작을 거부한다** (예전에는 경고만 찍고 떴다).
    브리지에는 인증이 없어서, IP 만 알면 누구든 팀 계정으로 파싱·STT·LLM 을 과금시킨다.
    바깥에서 볼 일이 있으면 SSH 터널이나 demo/run_tunnel.sh(Cloudflare Access) 를 쓴다.
    """
    if mock or host in LOOPBACK_HOSTS:
        return ""
    return (
        f"DEMO_HOST={host} 로는 실 API 모드(MOCK_EXTERNAL_APIS=false)를 띄울 수 없어요. "
        "브리지에는 인증이 없어 주소만 알면 누구든 과금 API 를 부릅니다. "
        "DEMO_HOST=127.0.0.1 로 띄우고, 바깥에서는 SSH 터널이나 demo/run_tunnel.sh 로 보면 돼요."
    )


def main():
    host = settings.demo_host
    port = settings.demo_port
    refusal = bind_refusal(host, _mock())
    if refusal:
        print(f"척척발표 demo bridge 시작 거부: {refusal}", file=sys.stderr, flush=True)
        raise SystemExit(2)
    print(f"척척발표 demo bridge → http://{host}:{port}/", flush=True)
    print(f"  SDK:  http://{host}:{port}/sdk/index.js", flush=True)
    print(f"  MOCK_EXTERNAL_APIS={_mock()}", flush=True)
    print(f"  요청 제한: 세션당 {PAID_RATE_LIMIT}회/분 · IP 천장 {PAID_RATE_LIMIT_IP}회/분 (0=끔) · "
          f"CORS 허용={sorted(ALLOWED_ORIGINS) or '없음(같은 출처만)'}", flush=True)
    print(f"  Access 헤더 필수={'예' if REQUIRE_ACCESS else '아니오'} · Host 허용={sorted(ALLOWED_HOSTS)}", flush=True)
    print(f"  방패: 과금 동시 {PAID_CONCURRENCY}(팀 몫 {GATE.reserved}, 대기 {PAID_QUEUE_SEC:g}초) · 공개 시간당 {PAID_PER_HOUR or '무제한'} · "
          f"IP 분당 {IP_RPM or '무제한'} · 감옥 {BAN_STRIKES}번/{JAIL.window:g}초→{JAIL.ban_sec:g}초 · 연결 {MAX_CONNECTIONS} · "
          f"시한 recv {SOCKET_TIMEOUT:g}/머리글 {HEADER_TIMEOUT:g}/유휴 {KEEPALIVE_SEC:g}초", flush=True)
    print(f"  원본 잠금: 비밀 머리글 {'있음' if EDGE_SECRET else '없음'} · 잠금 {'켜짐' if EDGE_LOCK else '꺼짐'}"
          f" · 차단 목록 {BLOCKLIST.path} · 점검 깃발 {LOCKDOWN.path}"
          f"{' (지금 켜짐)' if LOCKDOWN.on() else ''}", flush=True)
    if _env_flag("DEMO_EDGE_LOCK") and not EDGE_SECRET:
        print("  ⚠ DEMO_EDGE_LOCK=1 인데 DEMO_EDGE_SECRET 이 비어 있어요 — 잠그면 전부 막히므로 잠금을 켜지 않았어요.", flush=True)
    if host not in LOOPBACK_HOSTS:
        print(
            f"  ⚠ {host} 로 열려 있습니다 (mock 모드라 허용). 같은 망의 누구든 접속할 수 있어요.",
            flush=True,
        )
    print(settings.masked(), flush=True)
    print(f"  세션 보관: {DATA_DIR} · 개발 목록 경로={'열림' if DEV_ROUTES else '닫힘'}"
          f" · 팀 인증(/auth)={'켜짐' if TEAM_CODE else '꺼짐'}", flush=True)
    if not _mock() and not media_tool("ffmpeg"):
        # A.X 앞단 WAF 는 10MiB 미만 업로드를 검사하다 막을 수 있고, 그 우회(PCM WAV 로 키우기)는 ffmpeg 이 있어야 돈다.
        # 질문 코칭의 답변 녹음은 10초 안팎(수백 KB)이라 정확히 그 구간이다 — 조용히 넘어가면 부스에서 "받아쓰기 실패" 로 나타난다.
        print("  ⚠ ffmpeg 이 없어요. 10MB 미만 녹음(질문 코칭 답변)의 WAF 우회가 꺼져 받아쓰기가 실패할 수 있어요 — "
              "`sudo apt-get install ffmpeg` (docs/DEPLOYMENT.md §STT)", flush=True)
    # 소켓을 먼저 묶는다 — 청소 스레드의 시연 덱 미리 파싱(_warm_decks_once)이 이 서버에 요청을 보낸다
    server = ReusableThreadingHTTPServer((host, port), Handler)
    _start_prune_loop()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nshutting down", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
