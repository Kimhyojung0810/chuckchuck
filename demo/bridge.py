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

MAX_UPLOAD_BYTES = 30 * 1024 * 1024  # UI 안내와 동일


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
            if length > MAX_UPLOAD_BYTES + 1024 * 1024:
                return self._json(413, {"error": "too_large", "message": "최대 30MB까지 올릴 수 있어요."})
            raw = self.rfile.read(length) if length else b""

            if parsed.path == "/api/v1/parse":
                return self._handle_parse(raw)
            if parsed.path == "/api/v1/concepts":
                return self._handle_concepts(raw)
            if parsed.path == "/api/v1/transcribe":
                return self._handle_transcribe(raw)
            if parsed.path == "/api/v1/graph":
                return self._handle_graph(raw)
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
        chosen = cands[0]
        if hint:
            stem = Path(hint).stem
            for p in cands:
                if stem and (stem in p.name or hint in p.name):
                    chosen = p
                    break
        doc = json.loads(chosen.read_text(encoding="utf-8"))
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
            return self._json(200, doc.to_dict())

        sys.stderr.write(f"[bridge] F-01 parse start file={filename!r} bytes={len(file_bytes)}\n")
        with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix or ".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            doc = parse_document(tmp_path)
            sys.stderr.write(f"[bridge] F-01 parse done slides={doc.total_slides}\n")
            return self._json(200, doc.to_dict())
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

    def _handle_transcribe(self, raw: bytes):
        body = json.loads(raw or b"{}")
        marks = [SlideMark.from_dict(m) for m in body.get("marks", [])]
        provider = "mock" if _mock() else body.get("provider", "skt-ax")

        audio_b64 = body.get("audio_base64")
        audio_path = body.get("audio_path")
        if audio_b64:
            import base64

            ext = body.get("ext", ".webm")
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(base64.b64decode(audio_b64))
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
