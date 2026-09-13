"""
데모 브리지가 업로드 녹음의 확장자를 어떻게 정하는지 고정합니다.

확장자가 실제 포맷과 다르면 STT 가 파일을 못 읽으므로, 프런트가 파일명에서 뽑아
보낸 값을 살리되 모르는·위험한 값은 녹음 기본값으로 떨어뜨려야 합니다.
"""

from __future__ import annotations

import pytest

from demo.bridge import (
    DEFAULT_AUDIO_EXT,
    MAX_BODY_BYTES,
    MAX_UPLOAD_BYTES,
    _cache_stem,
    _safe_audio_ext,
)


@pytest.mark.parametrize("raw", [".m4a", ".mp3", ".wav", ".ogg", ".webm", ".flac"])
def test_허용_확장자는_그대로_통과한다(raw: str) -> None:
    assert _safe_audio_ext(raw) == raw


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("M4A", ".m4a"),  # 대문자
        ("mp3", ".mp3"),  # 점 없음
        ("  .WAV  ", ".wav"),  # 공백
    ],
)
def test_표기가_달라도_같은_확장자로_정규화된다(raw: str, expected: str) -> None:
    assert _safe_audio_ext(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        ".exe",  # 오디오가 아님
        ".sh",
        "../../etc/passwd",  # 경로 조각
        ".m4a/../evil",
        "..",
    ],
)
def test_모르거나_위험한_값은_기본_확장자로_떨어진다(raw: str | None) -> None:
    assert _safe_audio_ext(raw) == DEFAULT_AUDIO_EXT


def test_본문_한도는_base64_팽창분을_감당한다() -> None:
    """원본 30MB 녹음은 base64 로 40MB — 본문 한도가 그보다 커야 413 이 안 난다."""
    base64_size = MAX_UPLOAD_BYTES * 4 / 3
    assert MAX_BODY_BYTES > base64_size


# ---------------------------------------------------------------------------
# SlideDoc 캐시 파일 이름
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("내_발표자료.pdf", "내_발표자료"),
        ("deck.pptx", "deck"),
        ("My Deck v2.pdf", "My Deck v2"),
    ],
)
def test_같은_자료는_같은_캐시_이름을_갖는다(file_name: str, expected: str) -> None:
    assert _cache_stem(file_name) == expected


@pytest.mark.parametrize(
    "file_name",
    ["../../etc/passwd", "a/b/c.pdf", "..", "/etc/shadow"],
)
def test_경로_조각은_캐시_이름에_남지_않는다(file_name: str) -> None:
    stem = _cache_stem(file_name)
    assert "/" not in stem
    assert ".." not in stem


def test_이름이_비면_기본값으로_떨어진다() -> None:
    assert _cache_stem("") == "upload"
    assert _cache_stem("***.pdf") == "upload"


def test_다른_자료는_다른_캐시_이름을_갖는다() -> None:
    """이름이 겹치면 엉뚱한 발표자료가 붙어 정합 판정이 통째로 거짓말이 된다."""
    assert _cache_stem("발표A.pdf") != _cache_stem("발표B.pdf")


def test_빈_인식_결과는_장애가_아니라_말소리_없음으로_알린다(monkeypatch) -> None:
    """2026-09-13: 톤만 든 WAV 를 올리면 벤더가 '인식 결과가 비어 있습니다' 를 내고 화면엔 STT 장애처럼 떴다."""
    import io, json
    from email.message import Message
    import demo.bridge as bridge
    from chuckchuck.contracts import STTError

    class H(bridge.Handler):
        def __init__(self):  # noqa: D107
            self.sent = []; self.headers = Message(); self.client_address = ("127.0.0.1", 1); self.wfile = io.BytesIO()
        def _json(self, code, payload): self.sent.append((code, payload))
        def send_response(self, *a, **k): pass
        def send_header(self, *a, **k): pass
        def end_headers(self): pass

    monkeypatch.setattr(bridge, "_mock", lambda: False)
    monkeypatch.setattr(bridge, "transcribe", lambda *a, **k: (_ for _ in ()).throw(STTError("[skt-ax] 인식 결과가 비어 있습니다.")))
    h = H()
    h._handle_transcribe(json.dumps({"marks": [], "audio_base64": "AAAA", "ext": "webm"}).encode())
    code, out = h.sent[-1]
    assert code == 422 and out["error"] == "no_speech"
    assert "타이핑" in out["message"] and "실패" not in out["message"]

    monkeypatch.setattr(bridge, "transcribe", lambda *a, **k: (_ for _ in ()).throw(STTError("A.X STT upload 응답을 읽지 못했어요")))
    h._handle_transcribe(json.dumps({"marks": [], "audio_base64": "AAAA", "ext": "webm"}).encode())
    assert h.sent[-1][0] == 502            # 진짜 장애는 그대로 502
