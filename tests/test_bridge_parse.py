"""
브리지의 업로드·세션 경로를 소켓 없이 고정합니다.

- 형식은 확장자가 아니라 내용(매직바이트)으로 판별한다
- 파싱은 세션 id 를 발급하고, 동의가 없으면 원본을 남기지 않는다
- cached-* 는 session_id 로만 찾고 최신본으로 대체하지 않는다
- 목록 경로는 DEMO_DEV_ROUTES 가 꺼져 있으면 404
- DELETE 는 있든 없든 204, feedback 은 계약이 거른다
"""

from __future__ import annotations

import io
import json
import zipfile
from email.message import Message
from pathlib import Path
from urllib.parse import urlparse

import pytest

import demo.bridge as bridge
from chuckchuck.contracts import SlideDoc
from demo.session_archive import SessionArchive

ROOT = Path(__file__).resolve().parent.parent
PPTX = ROOT / "tests" / "focus_notification_demo_designed.pptx"


class FakeHandler(bridge.Handler):
    """소켓 없이 응답만 잡는다."""

    def __init__(self, path: str = "/", content_type: str = "") -> None:  # noqa: D107 — super 호출 안 함
        self.path = path
        self.headers = Message()
        if content_type:
            self.headers["Content-Type"] = content_type
        self.client_address = ("127.0.0.1", 1)
        self.sent: list[tuple[int, dict]] = []
        self.status: int | None = None
        self.out = io.BytesIO()
        self.wfile = self.out

    def _json(self, code: int, payload: dict):
        self.sent.append((code, payload))

    def send_response(self, code, message=None):
        self.status = code

    def send_header(self, k, v):
        pass

    def end_headers(self):
        pass

    @property
    def last(self) -> tuple[int, dict]:
        return self.sent[-1]


@pytest.fixture
def archive(tmp_path, monkeypatch) -> SessionArchive:
    a = SessionArchive(tmp_path / "data")
    monkeypatch.setattr(bridge, "ARCHIVE", a)
    monkeypatch.setattr(bridge, "DEV_ROUTES", False)
    monkeypatch.setattr(bridge, "_mock", lambda: False)
    return a


def _pptx_bytes() -> bytes:
    if PPTX.is_file():
        return PPTX.read_bytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ppt/presentation.xml", "<p/>")
    return buf.getvalue()


def _plain_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "x")
    return buf.getvalue()


# ── 매직바이트 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("data", "expected"), [
    (b"%PDF-1.7\n%\xe2\xe3", ".pdf"),
    (b"\xef\xbb\xbf   %PDF-1.4", ".pdf"),          # BOM·공백 뒤
    (_pptx_bytes(), ".pptx"),
    (_plain_zip(), None),                           # zip 이지만 PPTX 아님
    (b"MZ\x90\x00 fake.exe", None),                 # .pdf 로 개명한 실행 파일
    (b"", None),
    (b"PK\x03\x04 broken", None),
])
def test_형식은_내용으로_판별한다(data: bytes, expected: str | None) -> None:
    assert bridge._sniff_document(data) == expected


# ── 파싱 → 세션 발급 ─────────────────────────────────────────────────────────

def _multipart(filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = "XBOUNDARYX"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def _fake_parse(monkeypatch) -> None:
    def parse(path: str) -> SlideDoc:
        return SlideDoc.from_dict({"file_name": Path(path).name, "total_slides": 1,
                                   "slides": [{"slide_no": 1, "title": "t", "blocks": []}]})
    monkeypatch.setattr(bridge, "parse_document", parse)


def test_개명한_실행파일은_디스크에_닿기_전에_거절한다(archive):
    body, ctype = _multipart("악성.pdf", b"MZ\x90\x00 not a pdf")
    h = FakeHandler("/api/v1/parse", ctype)
    h._handle_parse(body)
    code, payload = h.last
    assert code == 415 and payload["error"] == "unsupported_type"
    assert not archive.sessions_dir.exists()


def test_파싱은_세션을_발급하고_동의_없으면_원본을_안_남긴다(archive, monkeypatch):
    _fake_parse(monkeypatch)
    body, ctype = _multipart("발표.pdf", b"%PDF-1.4 hello")
    h = FakeHandler("/api/v1/parse", ctype)
    h._handle_parse(body)
    code, payload = h.last
    assert code == 200
    sid = payload["session_id"]
    assert SessionArchive.safe_id(sid) == sid
    assert payload["file_name"] == "발표.pdf"
    assert payload["consent_learning"] is False
    assert payload["preview_pdf"] == f"/api/v1/preview-pdf?session_id={sid}"
    p = archive.path(sid)
    assert not (p / "original.pdf").exists()
    assert (p / "preview.pdf").read_bytes() == b"%PDF-1.4 hello"
    assert archive.read_artifact(sid, "slide_doc")["file_name"] == "발표.pdf"
    # 예전 자리에는 아무것도 생기지 않는다
    assert not list((ROOT / "fixtures" / "raw").glob("발표*"))


def test_동의하면_원본을_남기고_그것이_곧_미리보기다(archive, monkeypatch):
    _fake_parse(monkeypatch)
    body, ctype = _multipart("발표.pdf", b"%PDF-1.4 hello")
    h = FakeHandler("/api/v1/parse?consent_learning=1", ctype)
    h._handle_parse(body)
    code, payload = h.last
    sid = payload["session_id"]
    assert payload["consent_learning"] is True
    rec = archive.manifest(sid)
    assert rec.consent_learning is True and rec.upload_ext == ".pdf" and rec.upload_bytes == 14
    assert archive.preview_path(sid).name == "original.pdf"
    assert not (archive.path(sid) / "preview.pdf").exists()


# ── cached-* ─────────────────────────────────────────────────────────────────

def test_cached_slidedoc_은_id_로만_찾고_최신본으로_대체하지_않는다(archive):
    sid = archive.new_id()
    archive.open(sid, consent=False, file_name="a.pdf", ext=".pdf", upload=None)
    archive.put_artifact(sid, "slide_doc", {"file_name": "a.pdf", "slides": [1]})

    h = FakeHandler()
    h._handle_cached_slidedoc(urlparse(f"/api/v1/cached-slidedoc?session_id={sid}"))
    assert h.last[0] == 200 and h.last[1]["file_name"] == "a.pdf"

    for q in ("", "?session_id=", "?session_id=flat", "?session_id=../../etc/passwd",
              "?session_id=20250101T000000Z_deadbeef", "?file=a"):
        h = FakeHandler()
        h._handle_cached_slidedoc(urlparse("/api/v1/cached-slidedoc" + q))
        assert h.last[0] == 404, q


def test_cached_transcript_과_preview_도_같은_규칙(archive):
    sid = archive.new_id()
    archive.open(sid, consent=False, file_name="a.pdf", ext=".pdf", upload=None)
    h = FakeHandler()
    h._handle_cached_transcript(urlparse(f"/api/v1/cached-transcript?session_id={sid}"))
    assert h.last[0] == 404
    archive.put_artifact(sid, "transcript", {"full_text": "안녕"})
    h = FakeHandler()
    h._handle_cached_transcript(urlparse(f"/api/v1/cached-transcript?session_id={sid}"))
    assert h.last[0] == 200 and h.last[1]["full_text"] == "안녕"

    h = FakeHandler()
    h._handle_preview_pdf(urlparse(f"/api/v1/preview-pdf?session_id={sid}"))
    assert h.last[0] == 404
    archive.put_file(sid, "preview.pdf", b"%PDF x")
    h = FakeHandler()
    h._handle_preview_pdf(urlparse(f"/api/v1/preview-pdf?session_id={sid}"))
    assert h.status == 200 and h.out.getvalue() == b"%PDF x"


def test_목록은_개발_경로가_꺼져_있으면_404(archive, monkeypatch):
    h = FakeHandler()
    h._handle_cached_takes()
    assert h.last[0] == 404
    monkeypatch.setattr(bridge, "DEV_ROUTES", True)
    sid = archive.new_id()
    archive.open(sid, consent=False, file_name="a.pdf", ext=".pdf", upload=None, title="a")
    h = FakeHandler()
    h._handle_cached_takes()
    assert h.last[0] == 200 and h.last[1]["takes"][0]["session_id"] == sid


# ── DELETE · feedback ────────────────────────────────────────────────────────

def test_delete_는_있든_없든_204_이고_보관소와_메모리를_같이_비운다(archive):
    sid = archive.new_id()
    archive.open(sid, consent=True, file_name="a.pdf", ext=".pdf", upload=b"%PDF")
    bridge.STORE.put_artifacts(sid, {"graph": {"nodes": []}})

    h = FakeHandler(f"/api/v1/sessions/{sid}")
    h.do_DELETE()
    assert h.status == 204
    assert archive.manifest(sid) is None
    assert bridge.STORE.artifacts(sid) == {}

    h = FakeHandler(f"/api/v1/sessions/{sid}")
    h.do_DELETE()
    assert h.status == 204                       # 두 번째도 같다 — 존재 여부를 알려 주지 않는다

    h = FakeHandler("/api/v1/sessions/flat")
    h.do_DELETE()
    assert h.status == 204 and h.sent == []       # 모양이 틀린 id 는 그냥 무시

    h = FakeHandler("/api/v1/sessions/../../x")
    h.do_DELETE()
    assert h.last[0] == 404                      # 경로 모양 자체가 다르면 404


def test_feedback_은_동의_세션에만_쌓이고_계약이_거른다(archive):
    sid = archive.new_id()
    archive.open(sid, consent=True, file_name="a.pdf", ext=".pdf", upload=b"%PDF")
    good = {"events": [
        {"kind": "question_vote", "target_id": "q1", "value": "down", "payload": {"question": "왜?"}},
        {"kind": "habit_dispute", "target_id": "span:12.5", "value": "not_habit"},
    ]}
    h = FakeHandler()
    h._handle_feedback(f"/api/v1/sessions/{sid}/feedback", json.dumps(good).encode())
    assert h.last == (200, {"session_id": sid, "accepted": 2})
    rows = archive.read_stream(sid, "feedback")
    assert [r["kind"] for r in rows] == ["question_vote", "habit_dispute"]
    assert rows[0]["at"] > 0

    h = FakeHandler()
    h._handle_feedback(f"/api/v1/sessions/{sid}/feedback",
                       json.dumps({"events": [{"kind": "applause", "target_id": "q1", "value": "up"}]}).encode())
    assert h.last[0] == 400

    other = archive.new_id()
    archive.open(other, consent=False, file_name="b.pdf", ext=".pdf", upload=None)
    h = FakeHandler()
    h._handle_feedback(f"/api/v1/sessions/{other}/feedback", json.dumps(good).encode())
    assert h.last[1]["accepted"] == 0
    assert archive.read_stream(other, "feedback") == []
