"""
로컬 데모용 얇은 서버입니다.
YEHS_demo 화면과 chuckchuck 모듈을 HTTP API(/api/v1/*)와 SDK(/sdk/*)로 연결합니다.
"""

from __future__ import annotations

import json
import sys
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
    build_graph,
    extract_concepts,
    parse_document,
    transcribe,
)
from chuckchuck.contracts import ConceptDoc, SlideDoc, SlideMark  # noqa: E402

MAX_UPLOAD_BYTES = 30 * 1024 * 1024  # UI 안내와 동일 (원본 파일 기준)
# JSON 본문은 오디오를 base64 로 실어 4/3 로 부푼다. 원본 30MB 를 그대로 받으려면
# 본문 한도도 그만큼 키워야 한다 — 안 그러면 정상 크기 녹음이 413 으로 막힌다.
MAX_BODY_BYTES = MAX_UPLOAD_BYTES * 4 // 3 + 2 * 1024 * 1024

ALLOWED_AUDIO_EXTS = frozenset(
    {".webm", ".m4a", ".mp4", ".mp3", ".wav", ".ogg", ".oga", ".flac", ".aac"}
)
DEFAULT_AUDIO_EXT = ".webm"


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


def _mock() -> bool:
    return settings.mock_external


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
                return self._json(
                    413,
                    {
                        "error": "too_large",
                        "message": "자료·녹음 모두 원본 기준 최대 30MB까지 올릴 수 있어요.",
                    },
                )
            raw = self.rfile.read(length) if length else b""

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
                    {
                        "error": "no_cache_for_file",
                        "message": f"{hint} 의 파싱 결과가 없습니다. 자료를 다시 올려주세요.",
                    },
                )
        else:
            chosen = cands[0]
        doc = json.loads(chosen.read_text(encoding="utf-8"))
        sys.stderr.write(f"[bridge] SlideDoc 캐시 사용 {chosen.name}\n")
        return self._json(200, doc)

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
            payload = doc.to_dict()
            # mock 에서도 캐시를 남겨야 새로고침 후 반복 테스트가 실API 와 똑같이 돈다
            _save_slidedoc_cache(payload, filename)
            return self._json(200, payload)

        sys.stderr.write(f"[bridge] F-01 parse start file={filename!r} bytes={len(file_bytes)}\n")
        with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix or ".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            doc = parse_document(tmp_path)
            sys.stderr.write(f"[bridge] F-01 parse done slides={doc.total_slides}\n")
            payload = doc.to_dict()
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
        sys.stderr.write(
            f"[bridge] F-06 concepts start slides={doc.total_slides} "
            f"has_transcript={transcript is not None} mock={_mock()}\n"
        )
        result = extract_concepts(doc, ctx, transcript=transcript, llm=llm)
        sys.stderr.write(f"[bridge] F-06 concepts done model={result.model}\n")
        return self._json(200, result.to_dict())

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
        sys.stderr.write(
            f"[bridge] F-07 graph start slides={doc.total_slides} "
            f"has_slide_doc={slide_doc is not None} mock={_mock()}\n"
        )
        graph = build_graph(doc, ctx, slide_doc=slide_doc, llm=llm)
        sys.stderr.write(
            f"[bridge] F-07 graph done nodes={len(graph.nodes)} "
            f"edges={len(graph.edges)} sections={len(graph.sections)}\n"
        )
        return self._json(200, graph.to_dict())

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

    def _handle_transcribe(self, raw: bytes):
        body = json.loads(raw or b"{}")

        # 실데이터 스왑 지점의 더미 — 시나리오가 심긴 Transcript fixture 를 그대로 준다.
        # 실 녹음이 들어오면 이 분기를 안 타고 아래 provider 경로로 흐른다 (코드 수정 0줄).
        if body.get("fixture"):
            fixture = ROOT / "fixtures" / "sample_transcript.json"
            if not fixture.exists():
                return self._json(
                    404,
                    {"error": "no_fixture", "message": "sample_transcript.json 이 없습니다."},
                )
            sys.stderr.write("[bridge] F-05 transcribe → fixture transcript\n")
            return self._json(200, json.loads(fixture.read_text(encoding="utf-8")))

        marks = [SlideMark.from_dict(m) for m in body.get("marks", [])]
        provider = "mock" if _mock() else body.get("provider", "skt-ax")

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
            return self._json(200, t.to_dict())
        finally:
            if audio_b64 and audio_path:
                Path(audio_path).unlink(missing_ok=True)

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
        self.send_header("Access-Control-Allow-Origin", "*")
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
