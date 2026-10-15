"""
실시간 받아쓰기 중계 — 브라우저 ⇄ 브리지(/api/v1/stt/live) ⇄ SKT A.X realtime STT (2026-10-15).

왜 — 크롬의 Web Speech(webkitSpeechRecognition)는 음성을 구글 서버로 보낸다. 국내 AI 트랙 규정(「AI 모델 · API 는
100% 국내 AI」)에 걸려서, 같은 「말하는 대로 글자가 뜨는」 자리를 A.X 실시간 STT 로 바꾼다. 키는 브라우저에 절대 안 간다.

길: 브라우저 WebSocket 하나(크롬 · 사파리 · 파이어폭스) — 오디오는 16kHz mono PCM16 이진 프레임, 브리지가 base64 JSON 으로
바꿔 A.X 로 보낸다. 짧은 POST + SSE 를 안 고른 까닭은 설계 문서 §11 결정(실측) 참고 — 100ms 마다 POST 하나면 부스 와이파이(한 IP)에서
방패의 홍수 제한(분당 1200)에 몇 명 만에 닿고, 요청마다 Cloudflare→Funnel→브리지 왕복 · 스레드가 새로 생긴다.

브라우저 쪽 말 (JSON 글자 프레임)
  → {"type":"stop"} 다 말했다 — A.X 에 stop, 남은 문장을 받은 뒤 done
  → {"type":"cancel"} 버린다 — A.X 에 delete
  ← {"type":"ready"} · {"type":"speech","on":bool} (A.X vad bos/eos) · {"type":"text","text":…,"seq":n} (문장 확정)
  ← {"type":"done","reason":"stop|limit|idle"} · {"type":"error","code":…,"message":해요체}

지키는 것: 세션 수 상한(전체 · IP) · 세션 길이 상한 · 오디오가 끊기면 끝 · 어떻게 끝나든 A.X 에 stop/delete 를 보내고 닫는다 ·
세션 하나 = 호출 로그 한 건(pipeline/_ai_calllog.record_live_session).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import select
import sys
import threading
import time
import uuid

RATE = 16000
BYTES_PER_SEC = RATE * 2
FRAME_MAX = 64 * 1024
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, "") or default))
    except ValueError:
        return default


#: 동시 세션 상한 (브리지 전체). 세션 하나가 스레드 하나 · A.X 연결 하나를 문다
LIVE_MAX = _env_int("DEMO_LIVE_STT_MAX", 16)
#: 팀(쿠키) · VM 안 요청 몫 — 공개 방문자가 다 차지해도 부스 노트북은 듣는다
LIVE_TEAM_RESERVED = _env_int("DEMO_LIVE_STT_TEAM_RESERVED", 3)
#: IP(칸) 하나의 동시 세션 — 부스 와이파이 뒤 여러 폰을 생각해 넉넉히
LIVE_IP_MAX = _env_int("DEMO_LIVE_STT_IP", 4)
#: 세션 길이 상한 — Q&A 답은 짧다. 발표 중 받아쓰기(비전 리허설 purpose=present)만 길게
ANSWER_MAX_SEC = _env_int("DEMO_LIVE_STT_MAX_SEC", 300)
PRESENT_MAX_SEC = _env_int("DEMO_LIVE_STT_PRESENT_SEC", 1200)
#: 오디오가 이만큼 안 오면 끝낸다 (탭이 잠들었거나 마이크가 빠졌다)
IDLE_SEC = _env_int("DEMO_LIVE_STT_IDLE_SEC", 20)
#: A.X 가 created 를 줄 때까지 · stop 뒤 stopped 를 줄 때까지 기다리는 시간
OPEN_TIMEOUT = 8.0
FLUSH_TIMEOUT = 5.0
#: created 전에 온 오디오를 쥐고 있는 양 (초)
PENDING_SEC = 10

MSG = {
    "busy": "지금 받아쓰기를 쓰는 사람이 많아요. 잠시 뒤에 다시 눌러 주세요.",
    "upstream": "받아쓰기 서버에 닿지 못했어요.",
    "unavailable": "지금은 실시간 받아쓰기를 쓸 수 없어요.",
    "bad_audio": "소리를 받지 못했어요. 마이크를 다시 켜 주세요.",
}


def accept_value(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode("ascii")).digest()).decode("ascii")


def handshake_problem(headers) -> str:
    """WebSocket 열기 요청이 맞는가. 맞으면 빈 문자열."""
    if "websocket" not in (headers.get("Upgrade") or "").lower():
        return "Upgrade: websocket 이 아니에요"
    if "upgrade" not in (headers.get("Connection") or "").lower():
        return "Connection: Upgrade 가 아니에요"
    if (headers.get("Sec-WebSocket-Version") or "").strip() != "13":
        return "Sec-WebSocket-Version 13 만 받아요"
    key = (headers.get("Sec-WebSocket-Key") or "").strip()
    try:
        if len(base64.b64decode(key, validate=True)) != 16:
            return "Sec-WebSocket-Key 가 이상해요"
    except ValueError:
        return "Sec-WebSocket-Key 가 이상해요"
    return ""


def upstream_url(base: str) -> str:
    b = (base or "https://awf-gw.adot.ai").rstrip("/")
    if b.startswith("https://"):
        b = "wss://" + b[len("https://"):]
    elif b.startswith("http://"):
        b = "ws://" + b[len("http://"):]
    return b + "/v1/stt/realtime"


def connect_ax(url: str, key: str):
    """A.X 실시간 STT 에 붙는다 (websockets sync 클라이언트). 키는 머리글로만 — 로그 · 브라우저로 안 간다."""
    from websockets.sync.client import connect  # noqa: PLC0415 — 브리지가 websockets 없이도 뜨게

    return connect(url, additional_headers={"X-API-Key": key}, user_agent_header="chuckchuck/1.0",
                   open_timeout=OPEN_TIMEOUT, close_timeout=1, max_size=2 ** 20, ping_interval=20, ping_timeout=20)


class Slots:
    """세션 칸. 전체 LIVE_MAX 중 LIVE_TEAM_RESERVED 는 팀 · VM 안 요청 몫, IP 칸마다 LIVE_IP_MAX."""

    def __init__(self, capacity: int = LIVE_MAX, reserved: int = LIVE_TEAM_RESERVED, per_ip: int = LIVE_IP_MAX) -> None:
        self.capacity, self.reserved, self.per_ip = capacity, min(reserved, capacity), per_ip
        self._lock = threading.Lock()
        self.active = 0
        self.by_ip: dict[str, int] = {}
        self.total = 0
        self.refused = 0

    def acquire(self, bucket: str, trusted: bool) -> bool:
        with self._lock:
            cap = self.capacity if trusted else self.capacity - self.reserved
            if self.active >= cap or (not trusted and self.per_ip > 0 and self.by_ip.get(bucket, 0) >= self.per_ip):
                self.refused += 1
                return False
            self.active += 1
            self.total += 1
            self.by_ip[bucket] = self.by_ip.get(bucket, 0) + 1
            return True

    def release(self, bucket: str) -> None:
        with self._lock:
            self.active = max(0, self.active - 1)
            n = self.by_ip.get(bucket, 1) - 1
            if n > 0:
                self.by_ip[bucket] = n
            else:
                self.by_ip.pop(bucket, None)

    def snapshot(self) -> dict:
        with self._lock:
            return {"active": self.active, "capacity": self.capacity, "reserved_team": self.reserved,
                    "per_ip": self.per_ip, "total": self.total, "refused": self.refused}


class Relay:
    """세션 하나 — 핸들러 스레드 하나에서 브라우저 소켓과 A.X 연결을 번갈아 본다 (select 50ms)."""

    def __init__(self, sock, *, connect, url: str, model: str, max_sec: float, idle_sec: float | None = None,
                 calllog=None, clock=time.monotonic) -> None:
        from websockets.frames import Opcode  # noqa: PLC0415
        from websockets.protocol import Protocol, Side, State  # noqa: PLC0415

        self.sock = sock
        self.connect, self.url, self.model = connect, url, model
        self.max_sec, self.clock = max_sec, clock
        self.idle_sec = IDLE_SEC if idle_sec is None else idle_sec
        self.calllog = calllog
        self.Opcode, self.State = Opcode, State
        self.proto = Protocol(Side.SERVER, state=State.OPEN, max_size=FRAME_MAX)
        self.up = None
        self.ready = False
        self.stopping = ""          # stop 을 보낸 까닭 (stop · limit · idle)
        self.stop_sent = False
        self.delete_sent = False
        self.deadline = 0.0
        self.end = None             # A.X 가 마지막으로 준 끝 말 (stopped · deleted · error)
        self.error = ""
        self.done = False
        self.pending: list[bytes] = []
        self.pending_bytes = 0
        self.frag: list[bytes] = []
        self.frag_op = None
        self.transcripts: list[dict] = []
        self.vad = 0
        self.create = {"message_type": "create", "speech_model": model, "audio_format": "pcm",
                       "tr_id": f"cc-{uuid.uuid4().hex[:16]}"}
        self.digest = None
        self.audio_bytes = 0

    # ── 브라우저로 ──────────────────────────────────────────────
    def tell(self, obj: dict) -> None:
        if self.proto.state is self.State.OPEN:
            self.proto.send_text(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
        self.flush()

    def flush(self) -> None:
        for data in self.proto.data_to_send():
            if data:
                try:
                    self.sock.sendall(data)
                except OSError:
                    self.done = True
                    return

    def fail(self, code: str, log: str = "") -> None:
        if log:
            sys.stderr.write(f"[live-stt] {code}: {log[:200]}\n")
        self.error = code
        self.tell({"type": "error", "code": code, "message": MSG.get(code, MSG["upstream"])})
        self.done = True

    # ── A.X 로 ─────────────────────────────────────────────────
    def up_send(self, obj: dict) -> bool:
        try:
            self.up.send(json.dumps(obj))
            return True
        except Exception as e:  # noqa: BLE001
            self.fail("upstream", f"A.X 로 보내지 못함 {type(e).__name__}")
            return False

    def audio(self, pcm: bytes) -> None:
        if not pcm or len(pcm) % 2 or len(pcm) > FRAME_MAX:
            return self.fail("bad_audio", f"오디오 프레임 {len(pcm)}바이트")
        self.last_audio = self.clock()
        if self.stopping:
            return None                     # 멈추는 중에 온 꼬리 — A.X 는 이미 stop 을 받았다
        if self.audio_bytes + len(pcm) > (self.max_sec + 5) * BYTES_PER_SEC:
            return self.begin_stop("limit")
        self.audio_bytes += len(pcm)
        self.digest.add(pcm)
        if not self.ready:
            if self.pending_bytes + len(pcm) <= PENDING_SEC * BYTES_PER_SEC:
                self.pending.append(pcm)
                self.pending_bytes += len(pcm)
            return None
        self.up_send({"message_type": "audio", "data": base64.b64encode(pcm).decode("ascii")})
        return None

    def begin_stop(self, why: str) -> None:
        if self.stopping:
            return
        self.stopping = why
        self.deadline = self.clock() + FLUSH_TIMEOUT
        if self.ready:
            self.stop_sent = self.up_send({"message_type": "stop"})

    def on_browser(self, ev) -> None:
        op = ev.opcode
        if op is self.Opcode.CONT:
            self.frag.append(bytes(ev.data))
            if not ev.fin:
                return
            data, self.frag = b"".join(self.frag), []
            op = self.frag_op
        elif not ev.fin:
            self.frag, self.frag_op = [bytes(ev.data)], op
            return
        else:
            data = bytes(ev.data)
        if op is self.Opcode.BINARY:
            self.audio(data)
        elif op is self.Opcode.TEXT:
            try:
                kind = (json.loads(data.decode("utf-8")) or {}).get("type")
            except (ValueError, UnicodeDecodeError, AttributeError):
                kind = None
            if kind == "stop":
                self.begin_stop("stop")
            elif kind == "cancel":
                self.cancel()
        elif op is self.Opcode.CLOSE:
            self.cancel()

    def cancel(self) -> None:
        if self.up is not None and self.ready and not self.end and not self.delete_sent:
            self.delete_sent = True
            self.up_send({"message_type": "delete"})
        self.done = True

    def on_upstream(self, raw) -> None:
        try:
            msg = json.loads(raw)
        except (TypeError, ValueError):
            return
        kind = msg.get("message_type")
        if msg.get("type") == "error" or (kind is None and msg.get("code")):
            self.end = msg
            return self.fail("upstream", f"A.X 오류 code={msg.get('code')} {msg.get('message', '')}")
        if kind == "created":
            self.ready = True
            self.tell({"type": "ready"})
            for pcm in self.pending:
                if not self.up_send({"message_type": "audio", "data": base64.b64encode(pcm).decode("ascii")}):
                    return None
            self.pending, self.pending_bytes = [], 0
            if self.stopping and not self.stop_sent:
                self.stop_sent = self.up_send({"message_type": "stop"})
        elif kind == "vad":
            self.vad += 1
            on = msg.get("detect_type") == "bos"
            self.tell({"type": "speech", "on": on})
        elif kind == "transcript":
            self.transcripts.append(msg)
            text = str(msg.get("text") or "").strip()
            if text:
                self.tell({"type": "text", "text": text, "seq": msg.get("seq"), "final": bool(msg.get("final", True))})
        elif kind in ("stopped", "deleted"):
            self.end = msg
            if kind == "stopped":
                self.tell({"type": "done", "reason": self.stopping or "stop"})
            self.done = True
        return None

    # ── 한 바퀴 ────────────────────────────────────────────────
    def run(self) -> dict:
        from websockets.exceptions import ConnectionClosed  # noqa: PLC0415
        from pipeline import _ai_calllog as AC  # noqa: PLC0415

        self.digest = AC.audio_digest()
        t0 = AC.now_kst()
        started = self.clock()
        self.last_audio = started
        try:
            try:
                self.up = self.connect(self.url)
            except Exception as e:  # noqa: BLE001
                self.fail("upstream", f"A.X 연결 실패 {type(e).__name__}: {str(e)[:120]}")
                return self.summary()
            if not self.up_send(self.create):
                return self.summary()
            while not self.done:
                now = self.clock()
                if not self.ready and now - started > OPEN_TIMEOUT:
                    self.fail("upstream", "A.X 가 created 를 주지 않음")
                    break
                if self.stopping and now > self.deadline:
                    self.tell({"type": "done", "reason": self.stopping, "late": True})
                    break
                if not self.stopping and now - started > self.max_sec:
                    self.begin_stop("limit")
                elif not self.stopping and now - self.last_audio > self.idle_sec:
                    self.begin_stop("idle")
                r, _, _ = select.select([self.sock], [], [], 0.05)
                if r:
                    try:
                        data = self.sock.recv(65536)
                    except OSError:
                        data = b""
                    if not data:
                        self.cancel()
                        break
                    self.proto.receive_data(data)
                    for ev in self.proto.events_received():
                        self.on_browser(ev)
                        if self.done:
                            break
                    self.flush()
                    if self.proto.state is not self.State.OPEN:
                        self.cancel()
                        break
                while not self.done:
                    try:
                        msg = self.up.recv(timeout=0)
                    except TimeoutError:
                        break
                    except ConnectionClosed:
                        if not self.end:
                            self.fail("upstream", "A.X 가 연결을 닫음")
                        break
                    self.on_upstream(msg)
        finally:
            self._close()
            if self.calllog is not None:
                ok = not self.error and bool(self.end) and self.end.get("message_type") in ("stopped", "deleted") \
                    and not self.end.get("code")
                self.calllog(endpoint=self.url, model=self.model, create=self.create,
                             audio=self.digest.summary(RATE), transcripts=self.transcripts, t0=t0, t1=AC.now_kst(),
                             closed=self.end or {"reason": self.error or self.stopping or "browser_closed"}, ok=ok)
        return self.summary()

    def _close(self) -> None:
        # 브라우저 먼저 닫는다 — A.X 의 닫기 응답(close_timeout)을 기다리느라 화면이 2초 늦게 끝나지 않게
        try:
            if self.proto.state is self.State.OPEN:
                self.proto.send_close(1000)
            self.flush()
        except Exception:  # noqa: BLE001
            pass
        if self.up is not None:
            if self.ready and not self.end and not self.delete_sent:
                try:
                    self.up.send(json.dumps({"message_type": "delete"}))
                except Exception:  # noqa: BLE001
                    pass
            try:
                self.up.close()
            except Exception:  # noqa: BLE001
                pass

    def summary(self) -> dict:
        return {"ready": self.ready, "end": (self.end or {}).get("message_type"), "error": self.error,
                "stopping": self.stopping, "audio_sec": round(self.audio_bytes / BYTES_PER_SEC, 2),
                "texts": sum(1 for t in self.transcripts if str(t.get("text") or "").strip())}
