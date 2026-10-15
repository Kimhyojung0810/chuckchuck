"""
실시간 받아쓰기 중계(/api/v1/stt/live · main/server/live_stt.py) — 가짜 A.X 로 진짜 소켓을 태운다.

- 브라우저 PCM 이진 프레임 → A.X 에는 base64 JSON audio, create 에 스트리밍 모델 · stop 뒤 남은 문장을 받아 done
- 키는 A.X 연결 머리글로만 — 브라우저가 받는 말 어디에도 없다 · 다른 출처 화면은 403
- 칸이 다 차면 열고 나서 busy 를 말하고 닫는다 · 세션 길이 상한 · 오디오가 끊기면 끝 · 브라우저가 끊으면 A.X 에 delete
- 세션 하나 = 호출 로그 한 건 (F-05-live)
"""
from __future__ import annotations

import base64
import json
import queue
import threading
import time

import pytest

import server.bridge as bridge
from server import live_stt
from tests.test_bridge_shield import live  # noqa: F401 — fixture
from tests.test_bridge_security import real  # noqa: F401 — fixture

ws_client = pytest.importorskip("websockets.sync.client")
FAKE_KEY = "awf" + "_" + "FAKELIVEKEY0123456789abcdef"


class FakeAX:
    """A.X realtime 흉내 — create→created, 오디오 0.5초가 쌓이면 bos, stop 이면 eos · 문장 · stopped, delete 면 deleted."""

    def __init__(self, text: str = "준호입니다", fail_create: bool = False) -> None:
        self.inbox: queue.Queue = queue.Queue()
        self.sent: list[dict] = []
        self.audio = b""
        self.closed = False
        self.text = text
        self.fail_create = fail_create
        self.spoke = False

    def send(self, raw: str) -> None:
        m = json.loads(raw)
        self.sent.append(m)
        kind = m["message_type"]
        if kind == "create":
            if self.fail_create:
                self.inbox.put(json.dumps({"code": 4001, "message": "잘못된 요청", "type": "error"}))
            else:
                self.inbox.put(json.dumps({"message_type": "created", "tr_id": m["tr_id"], "code": 0}))
        elif kind == "audio":
            self.audio += base64.b64decode(m["data"])
            if len(self.audio) >= 16000 and not self.spoke:
                self.spoke = True
                self.inbox.put(json.dumps({"message_type": "vad", "detect_type": "bos", "time_offset": 0.3}))
        elif kind == "stop":
            self.inbox.put(json.dumps({"message_type": "vad", "detect_type": "eos", "time_offset": 1.0}))
            self.inbox.put(json.dumps({"message_type": "transcript", "text": self.text, "start_time": 0.3,
                                       "end_time": 1.0, "final": True, "seq": 0, "words": []}))
            self.inbox.put(json.dumps({"message_type": "stopped", "code": 0}))
        elif kind == "delete":
            self.inbox.put(json.dumps({"message_type": "deleted", "code": 0}))

    def recv(self, timeout=None):
        try:
            if timeout is not None and timeout <= 0:
                return self.inbox.get_nowait()
            return self.inbox.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError from None

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def ax(real, monkeypatch, tmp_path):  # noqa: F811
    fake = FakeAX()
    seen = {}

    def connect(url, key):
        seen.update(url=url, key=key)
        return fake

    monkeypatch.setattr(live_stt, "connect_ax", connect)
    monkeypatch.setattr(bridge.settings, "ax_stt_api_key", FAKE_KEY)
    monkeypatch.setattr(bridge.settings, "ax_stt_base_url", "https://awf-gw.adot.ai")
    monkeypatch.setattr(bridge, "LIVE_SLOTS", live_stt.Slots(capacity=4, reserved=1, per_ip=2))
    monkeypatch.setenv("AI_CALLLOG", "all")
    monkeypatch.setenv("AI_CALLLOG_DIR", str(tmp_path / "calllog"))
    fake.seen = seen
    return fake


def _open(srv, origin: str | None = None):
    port = srv.server_address[1]
    return ws_client.connect(f"ws://127.0.0.1:{port}/api/v1/stt/live?purpose=answer",
                             origin=origin or f"http://127.0.0.1:{port}", open_timeout=5, close_timeout=2)


def _drain(ws, until: str = "done", limit: float = 5.0) -> list[dict]:
    got = []
    end = time.monotonic() + limit
    while time.monotonic() < end:
        try:
            m = json.loads(ws.recv(timeout=max(0.05, end - time.monotonic())))
        except TimeoutError:
            break
        except Exception:  # noqa: BLE001 — 닫힘
            break
        got.append(m)
        if m.get("type") in (until, "error"):
            break
    return got


PCM = (b"\x10\x00\xf0\xff" * 800)          # 100ms = 3200 바이트


def test_말하고_멈추면_문장이_오고_done(live, ax, tmp_path):  # noqa: F811
    srv = live()
    with _open(srv) as ws:
        first = _drain(ws, until="ready")
        assert first == [{"type": "ready"}]
        for _ in range(10):
            ws.send(PCM)
        time.sleep(0.2)
        ws.send(json.dumps({"type": "stop"}))
        got = _drain(ws)
    assert {"type": "speech", "on": True} in got and {"type": "speech", "on": False} in got
    assert {"type": "text", "text": "준호입니다", "seq": 0, "final": True} in got
    assert got[-1] == {"type": "done", "reason": "stop"}
    create = ax.sent[0]
    assert create["message_type"] == "create" and create["speech_model"] == bridge.settings.ax_stt_streaming_model
    assert create["audio_format"] == "pcm" and create["tr_id"].startswith("cc-")
    assert ax.audio == PCM * 10 and ax.sent[-1]["message_type"] == "stop"
    assert ax.seen == {"url": "wss://awf-gw.adot.ai/v1/stt/realtime", "key": FAKE_KEY}
    assert FAKE_KEY not in json.dumps(got) and ax.closed
    # 호출 로그 한 건 (F-05-live) — 키 · 머리글 없음, 오디오는 지문만
    [path] = list((tmp_path / "calllog").rglob("F-05-live.jsonl"))
    [rec] = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert rec["feature"] == "답변_실시간_받아쓰기" and rec["ok"] is True and rec["provider"] == "SKT"
    assert rec["request"]["body"]["audio"]["bytes"] == len(PCM) * 10 and rec["request"]["body"]["audio"]["duration_sec"] == 1.0
    assert rec["response"]["body"]["messages"][0]["text"] == "준호입니다"
    assert FAKE_KEY not in path.read_text(encoding="utf-8")


def test_ready_전에_보낸_오디오도_잃지_않는다(live, ax):  # noqa: F811
    srv = live()
    with _open(srv) as ws:
        ws.send(PCM)
        ws.send(PCM)
        ws.send(json.dumps({"type": "stop"}))
        got = _drain(ws)
    assert got[-1]["type"] == "done" and ax.audio == PCM * 2


def test_브라우저가_끊으면_A_X_에_delete(live, ax):  # noqa: F811
    srv = live()
    with _open(srv) as ws:
        _drain(ws, until="ready")
        ws.send(PCM)
    for _ in range(40):
        if ax.closed:
            break
        time.sleep(0.05)
    assert ax.closed and ax.sent[-1]["message_type"] == "delete"


def test_cancel_도_delete(live, ax):  # noqa: F811
    srv = live()
    with _open(srv) as ws:
        _drain(ws, until="ready")
        ws.send(json.dumps({"type": "cancel"}))
        time.sleep(0.3)
    assert [m["message_type"] for m in ax.sent] == ["create", "delete"]


def test_다른_출처_화면은_403(live, ax):  # noqa: F811
    srv = live()
    with pytest.raises(Exception) as ei:
        _open(srv, origin="https://evil.example")
    assert "403" in str(ei.value)
    assert ax.sent == []


def test_WebSocket_이_아니면_426(real):  # noqa: F811
    from tests.test_bridge_security import FakeHandler

    h = FakeHandler("/api/v1/stt/live")
    h.do_GET()
    assert h.last[0] == 426


def test_칸이_다_차면_열고_까닭을_말한_뒤_닫는다(live, ax, monkeypatch):  # noqa: F811
    monkeypatch.setattr(bridge, "LIVE_SLOTS", live_stt.Slots(capacity=0, reserved=0))
    srv = live()
    with _open(srv) as ws:
        got = _drain(ws)
    assert got and got[0]["type"] == "error" and got[0]["code"] == "busy" and "많아요" in got[0]["message"]
    assert ax.sent == []


def test_A_X_가_create_를_거절하면_오류를_알린다(live, ax):  # noqa: F811
    ax.fail_create = True
    srv = live()
    with _open(srv) as ws:
        got = _drain(ws)
    assert got[-1]["type"] == "error" and got[-1]["code"] == "upstream"
    assert "잘못된 요청" not in json.dumps(got, ensure_ascii=False)       # 벤더 문구는 브라우저로 안 보낸다


def test_세션_길이_상한(live, ax, monkeypatch):  # noqa: F811
    monkeypatch.setattr(live_stt, "ANSWER_MAX_SEC", 0.4)
    srv = live()
    with _open(srv) as ws:
        _drain(ws, until="ready")
        for _ in range(8):
            try:
                ws.send(PCM)
            except Exception:  # noqa: BLE001 — 상한에 닿아 브리지가 닫았다
                break
            time.sleep(0.1)
        got = _drain(ws)
    assert got[-1] == {"type": "done", "reason": "limit"}
    assert [m for m in ax.sent if m["message_type"] == "stop"]


def test_오디오가_끊기면_idle_로_끝(live, ax, monkeypatch):  # noqa: F811
    monkeypatch.setattr(live_stt, "IDLE_SEC", 0.3)
    srv = live()
    with _open(srv) as ws:
        got = _drain(ws, limit=3)
    assert got[-1] == {"type": "done", "reason": "idle"}


def test_칸은_IP_마다_세고_팀은_예약_칸까지_쓴다():
    s = live_stt.Slots(capacity=3, reserved=1, per_ip=1)
    assert s.acquire("a", False) and not s.acquire("a", False)       # IP 하나에 하나
    assert s.acquire("b", False) and not s.acquire("c", False)       # 공개 몫 2칸이 다 찼다
    assert s.acquire("t", True)                                      # 팀은 예약 칸
    s.release("a")
    assert s.snapshot()["active"] == 2 and not s.acquire("c", False)   # 팀이 쓰는 칸도 전체에 센다
    s.release("t")
    assert s.acquire("c", False)


def test_handshake_와_주소():
    ok = {"Upgrade": "websocket", "Connection": "keep-alive, Upgrade", "Sec-WebSocket-Version": "13",
          "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="}
    assert live_stt.handshake_problem(ok) == ""
    assert live_stt.accept_value("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="   # RFC 6455 예시
    assert live_stt.handshake_problem({**ok, "Sec-WebSocket-Key": "짧다"})
    assert live_stt.upstream_url("https://awf-gw.adot.ai/") == "wss://awf-gw.adot.ai/v1/stt/realtime"
    assert live_stt.upstream_url("http://127.0.0.1:9") == "ws://127.0.0.1:9/v1/stt/realtime"


def test_실시간_받아쓰기는_세션_하나에_스레드_하나(live, ax):  # noqa: F811
    srv = live()
    before = threading.active_count()
    with _open(srv) as ws:
        _drain(ws, until="ready")
        during = threading.active_count()
        ws.send(json.dumps({"type": "stop"}))
        _drain(ws)
    # 핸들러 스레드 하나 + 테스트 클라이언트의 수신 스레드 — 브리지가 세션마다 스레드를 더 만들지 않는다
    assert during - before <= 3
