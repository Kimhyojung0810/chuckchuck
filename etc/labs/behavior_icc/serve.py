"""코딩판(coder.html)을 내 컴퓨터에서만 여는 작은 정적 서버 — 표준 라이브러리만 쓴다(맥 기본 python3 로 된다).

    python3 etc/labs/behavior_icc/serve.py            # → http://127.0.0.1:8840/coder.html 를 크롬으로 연다
    python3 etc/labs/behavior_icc/serve.py --port 8848 --no-open

127.0.0.1 에만 붙는다(같은 와이파이의 다른 사람도 못 들어온다). 이 폴더의 web/ 만 내준다 — 영상 · 엔진 결과는 내주지 않는다.
영상은 브라우저가 내 디스크에서 바로 읽는다(서버로 안 올라간다).
"""
from __future__ import annotations

import argparse
import functools
import http.server
import socket
import socketserver
import webbrowser
from pathlib import Path

WEB = Path(__file__).resolve().parent / "web"


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass


def free(port: int) -> int:
    for p in range(port, port + 10):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise SystemExit(f"{port}~{port + 9} 포트가 다 쓰이고 있어요 — --port 로 바꿔 줘요")


def main() -> None:
    ap = argparse.ArgumentParser(description="행동 코딩판 열기 (127.0.0.1 전용)")
    ap.add_argument("--port", type=int, default=8840)
    ap.add_argument("--no-open", action="store_true", help="브라우저를 열지 않는다")
    a = ap.parse_args()
    port = free(a.port)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), functools.partial(Handler, directory=str(WEB))) as httpd:
        url = f"http://127.0.0.1:{port}/coder.html"
        print(f"코딩판: {url}  (끝낼 때 Ctrl+C)", flush=True)
        if not a.no_open:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n닫았어요")


if __name__ == "__main__":
    main()
