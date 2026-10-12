"""
검증용 브리지를 대상 저장소 코드로 띄우고 끈다 — 실 API · heuristic 습관 · 개발 경로 열림 · 루프백만.

    DEMO_HOST=127.0.0.1 DEMO_PORT=<포트> DEMO_DEV_ROUTES=1 HABIT_PROVIDER=heuristic MOCK_EXTERNAL_APIS=false

팀 브리지(8799)는 건드리지 않는다: 8799 를 거부하고, 포트가 이미 물려 있으면 띄우지 않는다. 끌 때는 **우리가 띄운 프로세스만**
(Popen 핸들) 끈다 — pkill 을 쓰지 않는다. 세션 보관소는 하네스 out/bridge_data (대상과 섞지 않는다; 단계 캐시 키에
모듈 소스 해시가 들어 있어 여러 대상이 같이 써도 안전하다).
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import common as C
from .target import Target

READY_TIMEOUT = 90


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


class Bridge:
    def __init__(self, target: Target, port: int, run_dir: Path, budget: int, *, no_papers: bool = False):
        if port == 8799:
            raise SystemExit("8799 는 팀 브리지 자리예요")
        self.target, self.port, self.run_dir, self.budget = target, port, run_dir, budget
        self.base = f"http://127.0.0.1:{port}"
        self.calls = run_dir / "llm_calls.jsonl"
        self.log = run_dir / "bridge.log"
        self.no_papers = no_papers
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        if port_busy(self.port):
            raise SystemExit(f"포트 {self.port} 가 이미 물려 있어요 — --port 로 다른 포트를 고르세요 (남의 브리지를 끄지 않는다)")
        env = dict(os.environ)
        env.update({
            "DEMO_HOST": "127.0.0.1", "DEMO_PORT": str(self.port), "DEMO_DEV_ROUTES": "1", "HABIT_PROVIDER": "heuristic",
            "MOCK_EXTERNAL_APIS": "false", "DEMO_RATE_LIMIT_PER_MIN": "0",
            "DEMO_DATA_DIR": str(C.OUT / "bridge_data"),
            "QA_VERIFY_REPO": str(self.target.repo), "QA_VERIFY_CALLS": str(self.calls), "QA_VERIFY_BUDGET": str(self.budget),
            "PATH": f"{Path.home() / '.local' / 'bin'}:{env.get('PATH', '')}", "PYTHONDONTWRITEBYTECODE": "1",
        })
        if self.no_papers:
            env["SCHOLAR_PROVIDER"] = "none"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        fh = self.log.open("w", encoding="utf-8")
        self.proc = subprocess.Popen([self.target.python, str(C.HERE / "bridge_wrap.py")], cwd=str(self.target.repo),
                                     env=env, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        t0 = time.time()
        while time.time() - t0 < READY_TIMEOUT:
            if self.proc.poll() is not None:
                raise SystemExit(f"브리지가 바로 죽었어요 (rc={self.proc.returncode}) — {self.log}\n" + "\n".join(C.tail(self.log.read_text(encoding='utf-8'))))
            try:
                with urllib.request.urlopen(f"{self.base}/index.html", timeout=3) as r:
                    if r.status == 200:
                        C.note(f"   브리지 준비 {time.time() - t0:.0f}s · pid {self.proc.pid} · {self.base}")
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(1)
        self.stop()
        raise SystemExit(f"브리지가 {READY_TIMEOUT}초 안에 안 떴어요 — {self.log}")

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)          # 우리가 띄운 프로세스 무리만
            self.proc.wait(timeout=15)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        C.note(f"   브리지 끔 (pid {self.proc.pid})")

    def used(self) -> int:
        return len(C.read_jsonl(self.calls))

    def remaining(self) -> int:
        return max(0, self.budget - self.used())

    # ── HTTP (브리지 변조 검사) ────────────────────────────────────────────
    def post(self, path: str, body: dict, timeout: int = 120) -> tuple[int, dict]:
        req = urllib.request.Request(self.base + path, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}
        except (urllib.error.URLError, OSError) as e:
            return 0, {"error": str(e)}

    def get_json(self, path: str, timeout: int = 30) -> dict | None:
        try:
            with urllib.request.urlopen(self.base + path, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except (urllib.error.URLError, OSError, ValueError):
            return None
