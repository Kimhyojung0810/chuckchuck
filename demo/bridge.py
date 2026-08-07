"""
로컬 데모용 얇은 서버입니다.
YEHS_demo 화면과 chuckchuck 모듈을 HTTP API(/api/v1/*)와 SDK(/sdk/*)로 연결합니다.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import tempfile
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

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
    parse_document,
    transcribe,
)
from chuckchuck.contracts import ConceptDoc, HabitDoc, PaceDoc, SlideDoc, SlideMark  # noqa: E402

from demo.rate_limit import RateLimiter  # noqa: E402
from demo.session_store import ARTIFACT_KEYS, SessionStore, fingerprint  # noqa: E402


#: 세션 아티팩트 + triage 캐시. 프로세스 메모리라 재시작하면 사라진다 —
#: 클라이언트는 session_missing 을 받으면 다시 등록하고 재시도한다.
STORE = SessionStore()

#: 과금 호출(파싱·STT·LLM)이 붙은 엔드포인트의 IP당 분당 상한.
#: 0 이하면 제한을 끈다 (오프라인 시연·자동화).
PAID_RATE_LIMIT = int(os.environ.get("DEMO_RATE_LIMIT_PER_MIN", "30"))
LIMITER = RateLimiter(limit=PAID_RATE_LIMIT, window_sec=60.0)

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


def _cache_stem(file_name: str) -> str:
    """캐시 파일 이름으로 쓸 안전한 stem. 경로 조각·구분자를 모두 없앤다."""
    stem = Path(file_name or "").stem
    safe = "".join(ch for ch in stem if ch.isalnum() or ch in "-_ ").strip()
    return safe[:80] or "upload"


def _save_slidedoc_cache(doc_dict: dict, file_name: str) -> None:
    """
    파싱 결과를 fixtures/raw 에 남긴다.

    같은 자료로 녹음만 바꿔가며 반복 테스트할 때 재파싱(느리고 유료)을 건너뛰기 위한 것.
    실패해도 파싱 자체는 성공이므로 삼키되 로그는 남긴다.
    """
    try:
        raw_dir = ROOT / "fixtures" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        path = raw_dir / f"{_cache_stem(file_name)}.slidedoc.json"
        path.write_text(json.dumps(doc_dict, ensure_ascii=False), encoding="utf-8")
        sys.stderr.write(f"[bridge] SlideDoc 캐시 저장 {path.name}\n")
    except OSError as e:
        sys.stderr.write(f"[bridge] SlideDoc 캐시 저장 실패(무시): {e}\n")



# LibreOffice 는 macOS 앱 번들·snap 설치에서 PATH 에 링크를 만들지 않는다.
# PATH 만 보면 설치돼 있어도 못 찾아 PPTX 원본 미리보기가 조용히 텍스트로 떨어진다.
_SOFFICE_FALLBACK_PATHS = (
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",  # macOS (brew cask 포함)
    "/opt/homebrew/bin/soffice",
    "/usr/local/bin/soffice",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
    "/snap/bin/libreoffice",
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


def _pptx_to_preview_pdf(pptx_path: Path, file_name: str) -> Path | None:
    """
    PPTX → PDF (LibreOffice headless). 발표 화면이 원본 슬라이드를 그리도록
    fixtures/raw/{stem}.preview.pdf 로 저장한다.
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
    stem = _cache_stem(file_name)
    raw_dir = ROOT / "fixtures" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir = Path(tempfile.mkdtemp(prefix="chuckchuck-pdf-"))
    try:
        proc = subprocess.run(
            [
                soffice,
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
        dest = raw_dir / f"{stem}.preview.pdf"
        shutil.copy2(produced[0], dest)
        sys.stderr.write(f"[bridge] preview PDF 저장 {dest.name} ({dest.stat().st_size} bytes)\n")
        return dest
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[bridge] pptx→pdf exception: {e!r}\n")
        return None
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def _save_pdf_preview(pdf_path: Path, file_name: str) -> Path | None:
    """업로드 PDF 원본을 preview 캐시로 복사 (세션 복구·통일 경로)."""
    import shutil

    try:
        raw_dir = ROOT / "fixtures" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        dest = raw_dir / f"{_cache_stem(file_name)}.preview.pdf"
        shutil.copy2(pdf_path, dest)
        return dest
    except OSError as e:
        sys.stderr.write(f"[bridge] pdf preview 복사 실패: {e}\n")
        return None


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
STAGE_CACHE_DIR = ROOT / "fixtures" / "raw" / "stage_cache"


def _stage_key(*parts) -> str:
    """출력에 영향을 주는 것 전부를 넣은 내용 해시. 하나라도 빠지면 캐시가 거짓말을 한다."""
    h = hashlib.sha1()
    for p in parts:
        h.update(json.dumps(p, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:20]


def _stage_cache_get(stage: str, key: str):
    if not STAGE_CACHE_ON:
        return None
    try:
        raw = (STAGE_CACHE_DIR / f"{stage}-{key}.json").read_text(encoding="utf-8")
        return json.loads(raw)
    except (OSError, ValueError):
        return None


def _stage_cache_put(stage: str, key: str, payload: dict) -> None:
    if not STAGE_CACHE_ON:
        return
    try:
        STAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (STAGE_CACHE_DIR / f"{stage}-{key}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as e:
        # 캐시 저장 실패는 분석 실패가 아니다. 삼키되 조용히는 안 한다
        sys.stderr.write(f"[bridge] {stage} 캐시 저장 실패(무시): {e}\n")


class Handler(SimpleHTTPRequestHandler):
    # 큰 PDF 파싱 중에도 다른 요청(정적 파일)이 안 막히게
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DEMO_DIR), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/sdk/"):
                return self._serve_sdk(parsed.path[len("/sdk/") :])
            if parsed.path == "/api/health":
                return self._json(200, {"ok": True, "mock": _mock()})
            if parsed.path == "/api/v1/cached-slidedoc":
                return self._handle_cached_slidedoc(parsed)
            if parsed.path == "/api/v1/preview-pdf":
                return self._handle_preview_pdf(parsed)
            return super().do_GET()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            try:
                self._json(500, {"error": "internal", "message": "GET failed"})
            except Exception:  # noqa: BLE001
                return

    def do_HEAD(self):
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/sdk/"):
                return self._serve_sdk(parsed.path[len("/sdk/") :], head_only=True)
            return super().do_HEAD()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length < 0:
                return self._json(400, {"error": "bad content-length"})
            if length > MAX_BODY_BYTES:
                return self._json(413, {"error": "too_large", "message": "최대 30MB까지 올릴 수 있어요."})
            raw = self.rfile.read(length) if length else b""

            # 과금 경로는 IP당 분당 상한을 건다. 본문을 다 읽은 뒤에 막는다 —
            # 안 읽고 끊으면 클라이언트가 응답 대신 연결 오류를 본다.
            if ((parsed.path in PAID_PATHS
                 or (parsed.path.endswith("/qa/judge") and "/api/v1/sessions/" in parsed.path))
                    and not LIMITER.allow(self._client_key())):
                wait = LIMITER.retry_after(self._client_key())
                return self._json(429, {
                    "error": "rate_limited",
                    "message": f"요청이 너무 잦아요. {wait}초 뒤에 다시 시도해 주세요.",
                    "retry_after": wait,
                })

            if parsed.path == "/api/v1/session/artifacts":
                return self._handle_session_artifacts(raw)
            if parsed.path == "/api/v1/parse":
                return self._handle_parse(raw)
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
            if parsed.path == "/api/v1/strategy":
                return self._handle_strategy(raw)
            # F-09: /api/v1/sessions/{id}/qa/judge — 세션 없이도 body.question 으로 판정
            if parsed.path.endswith("/qa/judge") and "/api/v1/sessions/" in parsed.path:
                return self._handle_qa_judge(raw)
            if parsed.path == "/api/v1/qa/judge":
                return self._handle_qa_judge(raw)
            return self._json(404, {"error": "not found"})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            sys.stderr.write(f"[bridge] client disconnected during {parsed.path}\n")
            return
        except Exception as e:  # noqa: BLE001 — 데모 브리지
            traceback.print_exc()
            try:
                self._json(500, {"error": type(e).__name__, "message": str(e)})
            except Exception:  # noqa: BLE001
                return

    def _handle_cached_slidedoc(self, parsed):
        """fixtures/raw 에 저장된 *.slidedoc.json 을 재사용 (재파싱 없이 발표 화면 복구)."""
        from urllib.parse import parse_qs

        qs = parse_qs(parsed.query or "")
        hint = (qs.get("file") or [""])[0]
        raw_dir = ROOT / "fixtures" / "raw"
        cands = sorted(raw_dir.glob("*.slidedoc.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not cands:
            return self._json(404, {"error": "no_cache", "message": "저장된 SlideDoc이 없습니다."})
        if hint:
            # 이름을 지정했는데 못 찾으면 최신본으로 대체하지 않는다 —
            # 다른 발표자료가 조용히 붙으면 정합 판정이 통째로 거짓말이 된다.
            want = _cache_stem(hint)
            chosen = next((p for p in cands if p.stem == f"{want}.slidedoc" or want in p.name), None)
            if chosen is None:
                return self._json(
                    404,
                    {"error": "no_cache", "message": f"'{hint}' 에 맞는 저장본이 없습니다."},
                )
        else:
            chosen = cands[0]
        doc = json.loads(chosen.read_text(encoding="utf-8"))
        return self._json(200, doc)


    def _handle_preview_pdf(self, parsed):
        """발표 원본 미리보기 PDF (PPTX 변환본 또는 업로드 PDF 캐시)."""
        from urllib.parse import parse_qs

        qs = parse_qs(parsed.query or "")
        hint = (qs.get("file") or [""])[0]
        stem = _cache_stem(hint)
        path = (ROOT / "fixtures" / "raw" / f"{stem}.preview.pdf").resolve()
        raw_root = (ROOT / "fixtures" / "raw").resolve()
        if not str(path).startswith(str(raw_root)) or not path.is_file():
            return self._json(404, {"error": "no_preview", "message": "원본 미리보기 PDF가 없어요."})
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _serve_sdk(self, rel: str, head_only: bool = False):
        path = (SDK_DIR / rel).resolve()
        if not str(path).startswith(str(SDK_DIR.resolve())) or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

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

        parts = raw.split(b"--" + boundary)
        file_bytes = None
        filename = "upload.pdf"
        for part in parts:
            if b"filename=" not in part:
                continue
            header, _, content = part.partition(b"\r\n\r\n")
            content = content.rstrip(b"\r\n")
            if content.endswith(b"--"):
                content = content[:-2]
            fn = header.decode(errors="ignore")
            import re

            m = re.search(r'filename="([^"]+)"', fn)
            if m:
                filename = m.group(1)
            file_bytes = content
            break

        if file_bytes is None:
            return self._json(400, {"error": "document field missing"})
        if len(file_bytes) > MAX_UPLOAD_BYTES:
            return self._json(413, {"error": "too_large", "message": "최대 30MB까지 올릴 수 있어요."})

        if _mock():
            fixture = ROOT / "fixtures" / "sample_slidedoc.json"
            doc = SlideDoc.from_dict(json.loads(fixture.read_text(encoding="utf-8")))
            doc.file_name = filename
            return self._json(200, doc.to_dict())

        sys.stderr.write(f"[bridge] F-01 parse start file={filename!r} bytes={len(file_bytes)}\n")
        with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix or ".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            doc = parse_document(tmp_path)
            sys.stderr.write(f"[bridge] F-01 parse done slides={doc.total_slides}\n")
            # 파서는 임시 경로 이름을 그대로 담는다. 원래 업로드 이름으로 되돌린다.
            doc.file_name = filename
            payload = doc.to_dict()
            # 발표 화면용 원본 미리보기 PDF (PPTX는 LibreOffice 변환)
            ext = Path(filename).suffix.lower()
            preview = None
            if ext == ".pptx":
                preview = _pptx_to_preview_pdf(Path(tmp_path), filename)
            elif ext == ".pdf":
                preview = _save_pdf_preview(Path(tmp_path), filename)
            if preview is not None:
                payload["preview_pdf"] = f"/api/v1/preview-pdf?file={_cache_stem(filename)}"
            _save_slidedoc_cache(payload, filename)
            return self._json(200, payload)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def _handle_concepts(self, raw: bytes):
        from chuckchuck.contracts import Transcript

        body = json.loads(raw or b"{}")
        doc = SlideDoc.from_dict(body["slide_doc"])
        ctx = Context.from_dict(body.get("context") or {})
        llm = "mock" if _mock() else body.get("llm")
        transcript = None
        if body.get("transcript"):
            transcript = Transcript.from_dict(body["transcript"])
        # 같은 자료·같은 발표 정보면 결과가 같다. 부스 2회차부터 1분 43초를 안 태운다
        key = _stage_key("f06", body["slide_doc"], body.get("context") or {}, llm,
                         body.get("transcript") or None)
        cached = _stage_cache_get("concepts", key)
        if cached is not None:
            sys.stderr.write(f"[bridge] F-06 concepts 캐시 적중 {key}\n")
            return self._json(200, cached)

        sys.stderr.write(
            f"[bridge] F-06 concepts start slides={doc.total_slides} "
            f"has_transcript={transcript is not None} mock={_mock()}\n"
        )
        _fake_delay("/api/v1/concepts")
        result = extract_concepts(doc, ctx, transcript=transcript, llm=llm)
        sys.stderr.write(f"[bridge] F-06 concepts done model={result.model}\n")
        payload = result.to_dict()
        _stage_cache_put("concepts", key, payload)
        return self._json(200, payload)

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
        llm = "mock" if _mock() else body.get("llm")
        sys.stderr.write(
            f"[bridge] F-20 strategy start concepts={len(analysis.get('concepts') or [])} "
            f"quotes={len(analysis.get('quotes') or [])} mock={_mock()}\n"
        )
        try:
            result = suggest_strategy(analysis, llm=llm)
        except StrategyError as e:
            # 환각을 걸러낸 결과 남는 게 없을 수 있다. 그건 500 이 아니라 "이번엔 못 냈다" 다.
            sys.stderr.write(f"[bridge] F-20 strategy rejected: {e}\n")
            return self._json(502, {"error": "strategy_failed", "message": str(e)})
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
        llm = "mock" if _mock() else body.get("llm")
        # F-07 은 Transcript 를 안 받는다 — 입력이 concept_doc·slide_doc·context 뿐이라
        # 같은 자료면 결과가 같다. 실측 2분 40초로 파이프라인에서 가장 긴 단계다
        key = _stage_key("f07", body["concept_doc"], body.get("slide_doc") or None,
                         body.get("context") or {}, llm)
        cached = _stage_cache_get("graph", key)
        if cached is not None:
            sys.stderr.write(f"[bridge] F-07 graph 캐시 적중 {key}\n")
            return self._json(200, cached)

        sys.stderr.write(
            f"[bridge] F-07 graph start slides={doc.total_slides} "
            f"has_slide_doc={slide_doc is not None} mock={_mock()}\n"
        )
        _fake_delay("/api/v1/graph")
        graph = build_graph(doc, ctx, slide_doc=slide_doc, llm=llm)
        sys.stderr.write(
            f"[bridge] F-07 graph done nodes={len(graph.nodes)} "
            f"edges={len(graph.edges)} sections={len(graph.sections)}\n"
        )
        payload = graph.to_dict()
        _stage_cache_put("graph", key, payload)
        return self._json(200, payload)

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
        llm = "mock" if _mock() else body.get("llm")
        sys.stderr.write(
            f"[bridge] F-11 alignment start nodes={len(graph.nodes)} "
            f"slides={graph.total_slides} mock={_mock()}\n"
        )
        _fake_delay("/api/v1/alignment")
        alignment = align_speech(graph, transcript, ctx, llm=llm)
        s = alignment.summary
        sys.stderr.write(
            f"[bridge] F-11 alignment done coverage={s.coverage} "
            f"verdicts={s.verdict_counts}\n"
        )
        return self._json(200, alignment.to_dict())

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
        return self._json(200, flow.to_dict())


    def _handle_chatter(self, raw: bytes):
        """삐약 청중석 · ConceptGraph + AlignmentDoc + FlowDiff → ChatterDoc."""
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
        chatter = build_chatter(body["graph"], body["alignment"], body["flow"])
        speakers = sorted({t.speaker for t in chatter.turns})
        sys.stderr.write(
            f"[bridge] chatter done turns={len(chatter.turns)} "
            f"speakers={len(speakers)} refs={len(chatter.referenced_node_ids)}\n"
        )
        return self._json(200, chatter.to_dict())

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
        llm = "mock" if _mock() else body.get("llm")
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
        return self._json(200, result.to_dict())

    def _handle_pace(self, raw: bytes):
        """F-17 · Transcript(+ConceptDoc/Context) → PaceDoc. LLM 없음."""
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
        pace = analyze_pace(transcript, ctx, concept_doc)
        sys.stderr.write(
            f"[bridge] F-17 pace done slides={len(pace.slides)} "
            f"actual={pace.actual_sec}s target={pace.target_sec}s\n"
        )
        return self._json(200, pace.to_dict())

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
        provider = body.get("provider")  # None → extract_habits 가 lora 기본
        spans = body.get("spans")
        habits = extract_habits(transcript, provider=provider, spans=spans)
        sys.stderr.write(
            f"[bridge] F-18 habits done REP={habits.repeat_cnt} FIL={habits.filler_cnt} "
            f"PAUSE={habits.pause_cnt} provider={habits.provider}\n"
        )
        return self._json(200, habits.to_dict())

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
        llm = "mock" if _mock() else body.get("llm")
        # 점수는 채점표(F-14)가 진실이다. rubric 을 같이 보내면 그 점수를 싣고,
        # 안 보내면 0 으로 둔다 — 여기서 두 번째 점수를 만들지 않는다.
        report = compose_report(pace, habits, ctx, rubric=body.get("rubric"), llm=llm)
        sys.stderr.write(
            f"[bridge] F-19 report done score={report.score} model={report.model}\n"
        )
        return self._json(200, report.to_dict())

    def _handle_transcribe(self, raw: bytes):
        body = json.loads(raw or b"{}")

        # 실데이터 스왑 지점의 더미 — 시나리오가 심긴 Transcript fixture 를 그대로 준다.
        # 실 녹음이 들어오면 이 분기를 안 타고 아래 provider 경로로 흐른다 (코드 수정 0줄).
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

        marks = [SlideMark.from_dict(m) for m in body.get("marks", [])]
        provider = "mock" if _mock() else body.get("provider", "skt-ax")
        _fake_delay("/api/v1/transcribe")

        audio_b64 = body.get("audio_base64")
        audio_path = body.get("audio_path")
        if audio_b64:
            import base64

            audio_bytes = base64.b64decode(audio_b64)
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
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(audio_bytes)
                audio_path = tmp.name
        if not audio_path:
            audio_path = str(ROOT / "fixtures" / ".keep")
            Path(audio_path).write_text("", encoding="utf-8")

        try:
            t = transcribe(audio_path, marks, provider=provider)
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
                sys.stderr.write(
                    f"[bridge] F-04 구간 추정 estimated={got.estimated} "
                    f"confidence={got.confidence}\n"
                )
            return self._json(200, out)
        except Exception as e:  # noqa: BLE001
            from chuckchuck.contracts import STTError

            msg = str(e) or e.__class__.__name__
            sys.stderr.write(f"[bridge] F-05 transcribe failed: {msg}\n")
            code = 502 if isinstance(e, STTError) else 500
            return self._json(
                code,
                {
                    "error": "stt_failed",
                    "message": msg if isinstance(e, STTError) else f"음성 인식에 실패했어요: {msg}",
                },
            )
        finally:
            if audio_b64 and audio_path:
                Path(audio_path).unlink(missing_ok=True)


    def _client_key(self) -> str:
        """요청 제한을 셀 단위. 데모는 인증이 없으니 IP 가 최선이다."""
        try:
            return str(self.client_address[0])
        except Exception:  # noqa: BLE001
            return "unknown"

    def _handle_session_artifacts(self, raw: bytes):
        """
        세션 아티팩트 등록 · {session_id, graph?, alignment?, flow?, transcript?, context?}.

        한 번 올려 두면 이후 질문 생성·판정은 session_id 만 보내면 된다.
        판정마다 그래프·발화를 통째로 재업로드하던 것을 없애는 자리다.
        """
        body = json.loads(raw or b"{}")
        session_id = str(body.get("session_id") or "").strip()
        if not session_id:
            return self._json(400, {"error": "bad_request", "message": "session_id 가 필요합니다."})

        # 본문에 있는 키만 넘긴다 — body.get() 으로 전부 채우면 "안 보낸 키" 와
        # "null 로 지우겠다는 키" 가 구분되지 않는다 (put_artifacts 의 계약).
        stored = STORE.put_artifacts(session_id, {k: body[k] for k in ARTIFACT_KEYS if k in body})
        sys.stderr.write(f"[bridge] session artifacts sid={session_id} stored={stored}\n")
        return self._json(200, {"session_id": session_id, "stored": stored})

    def _resolve(self, body: dict, *keys: str) -> dict:
        """
        본문에 없는 아티팩트를 세션 저장소에서 채운다.

        본문이 이긴다 — 방금 만든 결과를 들고 온 요청이 오래된 캐시에 밀리면 안 된다.
        """
        found = {k: body.get(k) for k in keys}
        missing = [k for k in keys if not found[k]]
        if not missing:
            return found
        stored = STORE.artifacts(str(body.get("session_id") or ""))
        for key in missing:
            found[key] = stored.get(key)
        return found

    def _handle_questions(self, raw: bytes):
        """F-08 · {graph, alignment?, flow?, transcript?, context, track} → QuestionDoc."""
        from chuckchuck import build_questions, triage_questions
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
        llm = "mock" if _mock() else body.get("llm")

        # triage 는 트랙과 무관하다 (f08_questions 모듈 주석). 같은 입력이면 1차 심사를
        # 재사용해 트랙만 바꾼 재요청이 LLM 1콜로 끝나게 한다 — 매번 다시 돌리면
        # temperature 탓에 1분 트랙 질문이 5분 트랙의 부분집합이라는 보장도 깨진다.
        cache_key = fingerprint(found["graph"], found["alignment"], found["flow"], str(llm))
        try:
            triage = STORE.get_triage(cache_key)
            if triage is None:
                triage = triage_questions(
                    graph, alignment, flow, ctx, transcript=transcript, llm=llm
                )
                STORE.set_triage(cache_key, triage)
            else:
                sys.stderr.write("[bridge] F-08 triage cache hit\n")
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
                context=ctx,
                llm=llm,
            )
        except QuestionError as e:
            return self._json(502, {"error": "questions_failed", "message": str(e)})
        sys.stderr.write(
            f"[bridge] F-08 questions track={doc.track} n={len(doc.questions)} model={doc.model}\n"
        )
        return self._json(200, with_hint_ladders(doc.to_dict(), doc.questions))

    def _handle_qa_judge(self, raw: bytes):
        """F-09 · {question_id, answer, history?, question, give_up?} → QaJudgement.

        데모 브리지는 세션 저장소가 없다. 프론트가 보낸 question 본문으로 판정한다.
        """
        from chuckchuck import judge_answer
        from chuckchuck.contracts import (
            AlignmentDoc,
            ConceptGraph,
            JudgeError,
            Question,
            Transcript,
        )

        body = json.loads(raw or b"{}")
        qraw = body.get("question")
        if not qraw:
            return self._json(
                400,
                {
                    "error": "bad_request",
                    "message": "question 이 필요합니다. (데모 브리지는 세션 캐시가 없어요)",
                },
            )
        question = Question.from_dict(qraw)
        if not question.question.strip():
            return self._json(400, {"error": "bad_request", "message": "질문 문장이 비어 있어요."})
        # 자료 근거 없이 판정하면 '자료와 어긋난다'(wrong)를 대조할 원본이 없고
        # 함정 질문의 핵심 규칙도 짐작이 된다. 본문에 없으면 세션에서 끌어온다.
        found = self._resolve(body, "graph", "alignment", "transcript", "context")
        # session_id 를 들고 왔는데 근거가 통째로 비었다면 세션이 날아간 것이다
        # (브리지 재시작). 조용히 근거 없이 판정하지 말고 다시 등록하게 알린다.
        if body.get("session_id") and not any(found[k] for k in ("graph", "alignment", "transcript")):
            return self._json(409, {
                "error": "session_missing",
                "message": "세션 아티팩트가 없어요. 다시 등록하고 시도해 주세요.",
            })
        graph = ConceptGraph.from_dict(found["graph"]) if found["graph"] else None
        alignment = AlignmentDoc.from_dict(found["alignment"]) if found["alignment"] else None
        transcript = Transcript.from_dict(found["transcript"]) if found["transcript"] else None
        ctx = Context.from_dict(found["context"] or body.get("context") or {})
        llm = "mock" if _mock() else body.get("llm")
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
                llm=llm,
            )
        except JudgeError as e:
            return self._json(502, {"error": "judge_failed", "message": str(e)})
        sys.stderr.write(
            f"[bridge] F-09 judge q={question.id} verdict={judgement.verdict} "
            f"passed={judgement.passed} stage={judgement.coach_stage!r} "
            f"근거={'graph' if graph else '-'}/{'align' if alignment else '-'}"
            f"/{'stt' if transcript else '-'}\n"
        )
        return self._json(200, judgement.to_dict())

    def _json(self, code: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self):
        # 데모는 수정이 잦다. 캐시된 옛 app.js 가 새 흐름을 가리는 사고 방지
        self.send_header("Cache-Control", "no-store")
        # CORS 는 허용 목록에 있는 origin 에만 연다. 브리지가 UI 를 같이 서빙하므로
        # 기본 경로는 같은 출처라 헤더가 아예 필요 없다 — '*' 는 브리지를 외부에
        # 노출했을 때 아무 페이지나 과금 API 를 부를 수 있게 하는 문이었다.
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if origin and origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    host = settings.demo_host
    port = settings.demo_port
    print(f"척척발표 demo bridge → http://{host}:{port}/", flush=True)
    print(f"  SDK:  http://{host}:{port}/sdk/index.js", flush=True)
    print(f"  MOCK_EXTERNAL_APIS={_mock()}", flush=True)
    print(f"  요청 제한: IP당 {PAID_RATE_LIMIT}회/분 (0=끔) · CORS 허용={sorted(ALLOWED_ORIGINS) or '없음(같은 출처만)'}", flush=True)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"  ⚠ {host} 로 열려 있습니다. 브리지에는 인증이 없어 같은 망의 누구든 "
            "과금 API(파싱·STT·LLM)를 부를 수 있어요. 시연이 끝나면 DEMO_HOST 를 되돌리세요.",
            flush=True,
        )
    print(settings.masked(), flush=True)
    server = ReusableThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nshutting down", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
