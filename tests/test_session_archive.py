"""
디스크 세션 보관소(`demo/session_archive.py`)의 규칙을 고정합니다.

- id 는 날짜 접두 형식만 받고, 경로는 id 안의 날짜로만 만든다 (입력으로 경로를 안 만든다)
- 동의가 없으면 원본·분석 산출물을 남기지 않는다. 파싱본·받아쓰기만 캐시로 남긴다
- 만료는 동의 여부에 따라 다른 시계로 센다
"""

from __future__ import annotations

import json

import pytest

from chuckchuck.contracts import FeedbackEvent, SessionRecord
from demo.session_archive import MAX_STREAM_LINES, SessionArchive

T0 = 1_757_500_000.0  # 2025-09-10 근처 UTC


class Clock:
    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def archive(tmp_path, clock) -> SessionArchive:
    return SessionArchive(
        tmp_path / "data", cache_ttl_sec=24 * 3600, stage_ttl_sec=72 * 3600,
        retention_sec=365 * 24 * 3600, clock=clock, code_version="abc1234",
    )


def _open(archive: SessionArchive, *, consent: bool, upload: bytes = b"%PDF-1.4 x") -> str:
    sid = archive.new_id()
    rec = archive.open(sid, consent=consent, file_name="발표.pdf", ext=".pdf", upload=upload, title="발표")
    assert rec is not None
    return sid


# ── id · 경로 ────────────────────────────────────────────────────────────────

def test_new_id_는_날짜_접두_형식이다(archive):
    sid = archive.new_id()
    assert SessionArchive.safe_id(sid) == sid
    assert sid.startswith("20250910T")


@pytest.mark.parametrize("bad", [
    "flat", "", None, "../x", "20250910T101010Z_ABCDEF01",          # 대문자
    "20250910T101010Z_abcdef0",                                    # 7 hex
    "20251310T101010Z_abcdef01",                                   # 13월
    "20250910T101010Z_abcdef01/../../etc",
])
def test_safe_id_는_날짜_접두_형식만_받는다(bad):
    assert SessionArchive.safe_id(bad) is None


def test_path_는_id_안의_날짜로_샤드를_고른다(archive):
    p = archive.path("20250910T101010Z_abcdef01")
    assert p is not None
    assert p.relative_to(archive.sessions_dir).parts == ("2025", "09", "10", "20250910T101010Z_abcdef01")
    assert archive.path("../../etc") is None


# ── 동의 ─────────────────────────────────────────────────────────────────────

def test_동의_없으면_원본과_파생_산출물을_남기지_않는다(archive):
    sid = _open(archive, consent=False)
    p = archive.path(sid)
    assert not (p / "original.pdf").exists()
    assert archive.put_artifact(sid, "concept_graph", {"nodes": [], "model": "solar"}) is False
    assert not (p / "artifacts").exists()
    assert archive.append(sid, "qa_turns", {"q": 1}) is False
    rec = archive.manifest(sid)
    assert rec.consent_learning is False and rec.consent_at is None
    assert "concept_graph" not in rec.artifacts


def test_slide_doc_과_transcript_는_동의_없이도_캐시로_남는다(archive):
    sid = _open(archive, consent=False)
    assert archive.put_artifact(sid, "slide_doc", {"file_name": "발표.pdf", "slides": [1]}) is True
    assert archive.put_artifact(sid, "transcript", {"full_text": "안녕", "provider": "skt-ax"}) is True
    assert archive.read_artifact(sid, "slide_doc")["slides"] == [1]
    assert archive.manifest(sid).models["transcript"] == "skt-ax"


def test_동의하면_원본과_산출물을_남긴다(archive):
    sid = _open(archive, consent=True, upload=b"%PDF-1.4 hello")
    p = archive.path(sid)
    assert (p / "original.pdf").read_bytes() == b"%PDF-1.4 hello"
    assert archive.put_artifact(sid, "concept_graph", {"nodes": [], "model": "solar"}) is True
    assert (p / "artifacts" / "concept_graph.json").is_file()
    rec = archive.manifest(sid)
    assert rec.consent_learning is True and rec.consent_at == T0
    assert rec.artifacts["concept_graph"] == "artifacts/concept_graph.json"
    assert rec.models["concept_graph"] == "solar"
    assert rec.code_version == "abc1234"
    assert rec.upload_bytes == len(b"%PDF-1.4 hello")


def test_pdf_원본은_곧_미리보기다(archive):
    sid = _open(archive, consent=True)
    assert archive.preview_path(sid).name == "original.pdf"
    assert archive.put_file(sid, "preview.pdf", b"%PDF rendered") is True
    assert archive.preview_path(sid).name == "preview.pdf"
    assert archive.put_file(sid, "../evil.pdf", b"x") is False


# ── 왕복 · 원자성 · 스트림 ───────────────────────────────────────────────────

def test_모르는_kind_와_없는_세션은_저장하지_않는다(archive):
    sid = _open(archive, consent=True)
    assert archive.put_artifact(sid, "audio", {"x": 1}) is False
    assert archive.put_artifact("20250910T101010Z_deadbeef", "slide_doc", {"x": 1}) is False
    assert archive.read_artifact(sid, "audio") is None


def test_manifest_는_원자적으로_쓴다(archive):
    sid = _open(archive, consent=True)
    p = archive.path(sid)
    archive.put_artifact(sid, "slide_doc", {"slides": []})
    assert not list(p.glob("*.tmp"))
    rec = SessionRecord.from_dict(json.loads((p / "manifest.json").read_text(encoding="utf-8")))
    assert rec.session_id == sid


def test_append_는_상한을_넘기지_않는다(archive):
    sid = _open(archive, consent=True)
    for i in range(MAX_STREAM_LINES):
        assert archive.append(sid, "feedback", {"i": i}) is True
    assert archive.append(sid, "feedback", {"i": "overflow"}) is False
    assert archive.manifest(sid).feedback_count == MAX_STREAM_LINES
    assert len(archive.read_stream(sid, "feedback")) == MAX_STREAM_LINES
    assert archive.append(sid, "audio", {"x": 1}) is False


def test_context_는_manifest_에_붙는다(archive):
    sid = _open(archive, consent=False)
    assert archive.set_context(sid, {"situation": "학회", "audience": "심사위원", "duration_min": 10}) is True
    assert archive.manifest(sid).context["situation"] == "학회"


# ── 삭제 · 만료 ───────────────────────────────────────────────────────────────

def test_delete_는_디렉터리를_통째로_지운다(archive):
    sid = _open(archive, consent=True)
    p = archive.path(sid)
    archive.put_artifact(sid, "concept_graph", {"nodes": []})
    assert archive.delete(sid) is True
    assert not p.exists()
    assert not p.parent.exists()          # 비어 버린 일 폴더도 걷어낸다
    assert archive.sessions_dir.is_dir()  # sessions/ 자체는 남는다
    assert archive.delete(sid) is False


def test_prune_은_캐시_TTL_과_보관_기간을_따로_센다(archive, clock):
    cached = _open(archive, consent=False)
    kept = _open(archive, consent=True)
    stage = archive.stage_dir
    stage.mkdir(parents=True)
    old = stage / "concepts-aaaa.json"
    old.write_text("{}")
    import os
    os.utime(old, (T0 - 100 * 3600, T0 - 100 * 3600))

    clock.t = T0 + 25 * 3600                       # 하루 하고 한 시간 뒤
    assert archive.prune() == [cached]
    assert archive.manifest(kept) is not None
    assert not old.exists()

    clock.t = T0 + 366 * 24 * 3600                 # 1년 하루 뒤
    assert archive.prune() == [kept]


def test_iter_consented_는_날짜순으로_동의_세션만_준다(archive, clock):
    clock.t = T0 + 2 * 86400
    later = _open(archive, consent=True)
    clock.t = T0
    earlier = _open(archive, consent=True)
    _open(archive, consent=False)
    assert [r.session_id for r in archive.iter_consented()] == [earlier, later]
    rows = archive.list_sessions()
    assert [r["session_id"] for r in rows][0] == later      # 목록은 최신 먼저
    assert {r["consent"] for r in rows} == {True, False}


# ── 계약 ─────────────────────────────────────────────────────────────────────

def test_feedback_event_왕복과_거부():
    ev = FeedbackEvent.from_dict({
        "kind": "question_vote", "target_id": "q1", "value": "down", "at": 1.0,
        "comment": "x" * 500, "payload": {"question": "왜?"},
    })
    assert len(ev.comment) == 200
    assert FeedbackEvent.from_dict(ev.to_dict()) == ev
    with pytest.raises(ValueError):
        FeedbackEvent.from_dict({"kind": "applause", "target_id": "q1", "value": "up"})
    with pytest.raises(ValueError):
        FeedbackEvent.from_dict({"kind": "rubric_dispute", "target_id": "3", "value": "up"})
    with pytest.raises(ValueError):
        FeedbackEvent.from_dict({"kind": "habit_dispute", "target_id": "", "value": "not_habit"})
