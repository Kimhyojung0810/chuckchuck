"""
데모 브리지의 **디스크 세션 보관소**입니다.

업로드 한 건이 세션 하나다. 브리지가 파싱 때 id 를 발급하고, 이후 호출은 `session_id`
를 실어 보낸다. 디스크 모양:

    var/data/                                   ← DEMO_DATA_DIR (기본, git 이 무시하는 var/)
      sessions/2026/09/10/20260910T143512Z_3f9a2c7e/
        manifest.json          SessionRecord
        original.pdf|pptx      동의한 세션만
        preview.pdf            PPTX 렌더본 (PDF 는 original 이 곧 미리보기)
        slide_doc.json         동의 무관 — 하루 캐시
        transcript.json        동의 무관 — 하루 캐시
        artifacts/<kind>.json  동의한 세션만
        qa_turns.jsonl         동의한 세션만
        feedback.jsonl         동의한 세션만
      stage_cache/<stage>-<sha1>.json   내용 해시 캐시 (세션 무관)

**왜 파일명이 아니라 id 인가.** 예전에는 `fixtures/raw/{파일명}.slidedoc.json` 이었다.
두 사람이 `발표.pdf` 를 올리면 서로 덮어썼고, 언제 올렸는지도 몰랐고, git 에 실제
발표 자료가 커밋됐다. id 앞의 UTC 타임스탬프 덕에 `ls` 만으로 시간순이고, 일 단위
폴더라 보관 만료를 폴더째 지운다.

**동의가 규칙이다.** `consent_learning` 이 없으면 원본·분석 산출물을 쓰지 않는다 —
핸들러가 분기하지 않고 이 클래스가 거른다. 어떤 저장 실패도 요청을 죽이지 않는다.

DEV_POLICY §4: F-모듈을 import 하지 않는다. contracts 만 쓴다.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from chuckchuck.contracts import (
    SESSION_ARTIFACT_KINDS,
    SESSION_CACHE_KINDS,
    SessionRecord,
)

#: id 모양. 날짜 접두는 사람·배치용이고 추측 불가능성은 뒤 8 hex 가 담당한다.
ID_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z_[0-9a-f]{8}$")

#: 세션당 jsonl 한 줄 상한. 넘치면 버린다 — 무한히 밀어 넣는 클라이언트 방어.
MAX_STREAM_LINES = 500

#: put_file 로 쓸 수 있는 이름. 그 밖은 거부한다.
ALLOWED_FILES = frozenset({"preview.pdf"})

STREAMS = ("qa_turns", "feedback")

DEFAULT_CACHE_TTL_SEC = 24 * 3600
DEFAULT_STAGE_TTL_SEC = 72 * 3600
DEFAULT_RETENTION_SEC = 365 * 24 * 3600


def _log(msg: str) -> None:
    sys.stderr.write(f"[archive] {msg}\n")


def _write_atomic(path: Path, data: bytes) -> None:
    """tmp 에 쓰고 rename. 쓰다 죽어도 반쪽짜리 파일이 남지 않는다."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def git_sha(root: Path) -> str:
    """현재 코드 버전. git 이 없거나 실패하면 빈 문자열 — 없다고 죽지 않는다."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


class SessionArchive:
    """스레드 안전. manifest 만 가변이고 나머지는 write-once 또는 append."""

    def __init__(
        self,
        root: Path,
        *,
        cache_ttl_sec: float = DEFAULT_CACHE_TTL_SEC,
        stage_ttl_sec: float = DEFAULT_STAGE_TTL_SEC,
        retention_sec: float = DEFAULT_RETENTION_SEC,
        clock=time.time,
        code_version: str = "",
    ) -> None:
        self.root = Path(root)
        self.sessions_dir = self.root / "sessions"
        self.stage_dir = self.root / "stage_cache"
        self._cache_ttl = cache_ttl_sec
        self._stage_ttl = stage_ttl_sec
        self._retention = retention_sec
        self._clock = clock
        self._code_version = code_version
        self._lock = threading.Lock()

    # -- id ----------------------------------------------------------------

    def new_id(self, now: float | None = None) -> str:
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(self._clock() if now is None else now))
        return f"{stamp}_{secrets.token_hex(4)}"

    @staticmethod
    def safe_id(sid: object) -> str | None:
        """정규식을 통과하고 날짜가 실제로 존재하는 id 만. 그 밖은 None."""
        if not isinstance(sid, str):
            return None
        m = ID_RE.match(sid)
        if not m:
            return None
        try:
            time.strptime(sid[:16], "%Y%m%dT%H%M%SZ")
        except ValueError:
            return None
        return sid

    def path(self, sid: str) -> Path | None:
        """세션 디렉터리. 경로는 id 안의 날짜로만 만든다 — 입력으로 경로를 조립하지 않는다."""
        sid = self.safe_id(sid)
        if sid is None:
            return None
        p = self.sessions_dir / sid[:4] / sid[4:6] / sid[6:8] / sid
        if not str(p.resolve()).startswith(str(self.sessions_dir.resolve())):
            return None
        return p

    # -- manifest ----------------------------------------------------------

    def manifest(self, sid: str) -> SessionRecord | None:
        p = self.path(sid)
        if p is None:
            return None
        try:
            return SessionRecord.from_dict(json.loads((p / "manifest.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return None

    def _save_manifest(self, p: Path, rec: SessionRecord) -> None:
        rec.updated_at = self._clock()
        _write_atomic(p / "manifest.json", json.dumps(rec.to_dict(), ensure_ascii=False, indent=1).encode("utf-8"))

    def open(
        self,
        sid: str,
        *,
        consent: bool,
        file_name: str,
        ext: str,
        upload: bytes | None,
        sha256: str = "",
        title: str = "",
    ) -> SessionRecord | None:
        """세션을 만든다. 동의했을 때만 원본을 남긴다. 실패하면 None (요청은 계속 간다)."""
        p = self.path(sid)
        if p is None:
            return None
        now = self._clock()
        rec = SessionRecord(
            session_id=sid, uploaded_at=now, updated_at=now,
            consent_learning=bool(consent), consent_at=now if consent else None,
            title=title, file_name=file_name, upload_ext=ext, upload_sha256=sha256,
            upload_bytes=len(upload or b""), code_version=self._code_version,
        )
        try:
            with self._lock:
                p.mkdir(parents=True, exist_ok=True)
                if consent and upload:
                    _write_atomic(p / f"original{ext}", upload)
                self._save_manifest(p, rec)
        except OSError as e:
            _log(f"세션 생성 실패(무시) {sid}: {e}")
            return None
        return rec

    def set_context(self, sid: str, context: dict) -> bool:
        return self._update(sid, lambda rec: rec.context.update(dict(context or {})))

    def _update(self, sid: str, mutate) -> bool:
        """manifest 를 읽어 고쳐 쓴다. 세션이 없으면 False."""
        p = self.path(sid)
        if p is None:
            return False
        try:
            with self._lock:
                rec = self.manifest(sid)
                if rec is None:
                    return False
                mutate(rec)
                self._save_manifest(p, rec)
        except OSError as e:
            _log(f"manifest 갱신 실패(무시) {sid}: {e}")
            return False
        return True

    # -- 산출물 --------------------------------------------------------------

    def put_artifact(self, sid: str, kind: str, payload: dict) -> bool:
        """
        산출물 저장. 캐시 종류(slide_doc·transcript)는 동의 무관, 나머지는 동의 세션만.
        모르는 kind·없는 세션·mock 결과는 호출부가 아니라 여기서 거른다.
        """
        if kind not in SESSION_ARTIFACT_KINDS or not isinstance(payload, dict):
            return False
        p = self.path(sid)
        if p is None:
            return False
        rel = f"{kind}.json" if kind in SESSION_CACHE_KINDS else f"artifacts/{kind}.json"
        try:
            with self._lock:
                rec = self.manifest(sid)
                if rec is None:
                    return False
                if kind not in SESSION_CACHE_KINDS and not rec.consent_learning:
                    return False
                (p / rel).parent.mkdir(parents=True, exist_ok=True)
                _write_atomic(p / rel, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                rec.artifacts[kind] = rel
                model = payload.get("model") or payload.get("provider")
                if model:
                    rec.models[kind] = str(model)
                self._save_manifest(p, rec)
        except OSError as e:
            _log(f"{kind} 저장 실패(무시) {sid}: {e}")
            return False
        return True

    def read_artifact(self, sid: str, kind: str) -> dict | None:
        p = self.path(sid)
        if p is None or kind not in SESSION_ARTIFACT_KINDS:
            return None
        rel = f"{kind}.json" if kind in SESSION_CACHE_KINDS else f"artifacts/{kind}.json"
        try:
            doc = json.loads((p / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return doc if isinstance(doc, dict) else None

    def put_file(self, sid: str, name: str, data: bytes) -> bool:
        """이름이 정해진 파일(미리보기 PDF)만. 임의 이름은 거부한다."""
        p = self.path(sid)
        if p is None or name not in ALLOWED_FILES or not data:
            return False
        try:
            with self._lock:
                if not (p / "manifest.json").is_file():
                    return False
                _write_atomic(p / name, data)
        except OSError as e:
            _log(f"{name} 저장 실패(무시) {sid}: {e}")
            return False
        return True

    def preview_path(self, sid: str) -> Path | None:
        """발표 화면용 PDF. 렌더본이 없고 원본이 PDF 면 원본이 곧 미리보기다."""
        p = self.path(sid)
        if p is None:
            return None
        for name in ("preview.pdf", "original.pdf"):
            if (p / name).is_file():
                return p / name
        return None

    # -- append 스트림 ----------------------------------------------------

    def append(self, sid: str, stream: str, event: dict) -> bool:
        """qa_turns / feedback 에 한 줄. 동의 세션만, 세션당 MAX_STREAM_LINES."""
        if stream not in STREAMS or not isinstance(event, dict):
            return False
        p = self.path(sid)
        if p is None:
            return False
        counter = "qa_turn_count" if stream == "qa_turns" else "feedback_count"
        try:
            with self._lock:
                rec = self.manifest(sid)
                if rec is None or not rec.consent_learning:
                    return False
                if getattr(rec, counter) >= MAX_STREAM_LINES:
                    return False
                with (p / f"{stream}.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
                setattr(rec, counter, getattr(rec, counter) + 1)
                self._save_manifest(p, rec)
        except OSError as e:
            _log(f"{stream} 추가 실패(무시) {sid}: {e}")
            return False
        return True

    def read_stream(self, sid: str, stream: str) -> list[dict]:
        p = self.path(sid)
        if p is None or stream not in STREAMS:
            return []
        try:
            lines = (p / f"{stream}.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    # -- 삭제 · 만료 --------------------------------------------------------

    def delete(self, sid: str) -> bool:
        p = self.path(sid)
        if p is None or not p.is_dir():
            return False
        with self._lock:
            shutil.rmtree(p, ignore_errors=True)
            self._drop_empty_parents(p)
        return True

    def _drop_empty_parents(self, p: Path) -> None:
        """일·월·년 폴더가 비면 걷어낸다. sessions/ 자체는 남긴다."""
        cur = p.parent
        while cur != self.sessions_dir and cur.is_dir():
            try:
                cur.rmdir()
            except OSError:
                return
            cur = cur.parent

    def _manifests(self) -> Iterator[tuple[Path, SessionRecord]]:
        """날짜순(오래된 것부터). 경로가 곧 정렬 키다."""
        if not self.sessions_dir.is_dir():
            return
        for mpath in sorted(self.sessions_dir.glob("*/*/*/*/manifest.json")):
            try:
                rec = SessionRecord.from_dict(json.loads(mpath.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
            if self.safe_id(rec.session_id) and mpath.parent.name == rec.session_id:
                yield mpath.parent, rec

    def prune(self, now: float | None = None) -> list[str]:
        """
        만료 세션을 지운다. 동의 없음 → cache_ttl, 동의 → retention (About 화면의 약속),
        stage_cache 는 mtime 으로 stage_ttl. 지운 id 를 돌려주니 로그에 남길 것.
        """
        now = self._clock() if now is None else now
        gone: list[str] = []
        for p, rec in list(self._manifests()):
            limit = self._retention if rec.consent_learning else self._cache_ttl
            if now - rec.updated_at > limit:
                if self.delete(rec.session_id):
                    gone.append(rec.session_id)
        if self.stage_dir.is_dir():
            for f in self.stage_dir.glob("*.json"):
                try:
                    if now - f.stat().st_mtime > self._stage_ttl:
                        f.unlink()
                except OSError:
                    continue
        return gone

    # -- 조회 ------------------------------------------------------------------

    def iter_consented(self) -> Iterator[SessionRecord]:
        """학습에 써도 되는 세션만, 날짜순."""
        for _, rec in self._manifests():
            if rec.consent_learning:
                yield rec

    def list_sessions(self) -> list[dict]:
        """개발용 목록 (#/replay). 최신이 먼저."""
        rows = []
        for p, rec in self._manifests():
            rows.append({
                "session_id": rec.session_id,
                "title": rec.title or rec.file_name,
                "slides": "slide_doc" in rec.artifacts,
                "transcript": "transcript" in rec.artifacts,
                "preview": self.preview_path(rec.session_id) is not None,
                "consent": rec.consent_learning,
                "at": int(rec.uploaded_at),
            })
        rows.reverse()
        return rows
