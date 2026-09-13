"""
이 머신에서 브리지가 뜰 조건을 표로 점검한다. 키 **값은 절대 안 보여 준다** — 있음/없음만.

왜 — CLAUDE.md 와 run_bridge_midm.sh 는 팀 GPU 서버(/home/ubuntu/…)를 가정한다. 다른 머신(예: .venv 에 torch 가
있는 A100 머신)에서는 midm python 경로·LoRA 경로가 없어서 F-18 이 조용히 heuristic 으로 떨어진다. 사람이
매번 기억하는 대신 이 표가 기억한다. 부스 컴퓨터 체크리스트(회의록 할 일 #14)도 이걸로 한다.

    scripts/chk doctor            # 경고는 통과, 실패만 exit 1
    scripts/chk doctor --strict   # 경고도 실패로
"""

from __future__ import annotations

import argparse
import platform
import shutil
import socket
from pathlib import Path

from . import common as C
from .common import Check

MIDM_PY_DEFAULT = "/home/ubuntu/miniforge3/envs/midm/bin/python"
LORA_DEFAULT = "/home/ubuntu/workspace/20_AIHub_data/runs/tagger_seed42/final"


def _env_check(env: dict[str, str]) -> list[Check]:
    out: list[Check] = []
    if not env:
        return [Check(".env", "fail", "없음 — `cp .env.example .env` 뒤 키를 채운다")]
    out.append(Check(".env", "ok", f"키 {len(env)}개 (값은 표시 안 함)"))
    mock = env.get("MOCK_EXTERNAL_APIS", "").lower() in ("1", "true", "yes")
    out.append(Check("mock", "fail" if mock else "ok",
                     "MOCK_EXTERNAL_APIS=true — CLAUDE.md §2: mock 으로 띄우지 않는다" if mock else "실 API 모드"))
    backend = env.get("REASONING_BACKEND", "solar")
    key_for = {"solar": "UPSTAGE_API_KEY", "ax": "AX_API_KEY", "midm": "MIDM_API_KEY", "exaone": "EXAONE_API_KEY"}
    k = key_for.get(backend)
    has = bool(env.get(k, "")) if k else False
    out.append(Check("LLM 백엔드", "ok" if has else "fail",
                     f"REASONING_BACKEND={backend} · {k} {'있음' if has else '없음'}"))
    out.append(Check("Solar 키", "ok" if env.get("UPSTAGE_API_KEY") else "warn",
                     "UPSTAGE_API_KEY 있음" if env.get("UPSTAGE_API_KEY")
                     else "UPSTAGE_API_KEY 없음 — F-01 파싱 불가, 그래프 벤치 판별 불가 (FAILURE_QUESTIONS P1)"))
    stt = env.get("AX_STT_API_KEY") or env.get("AX_API_KEY")
    out.append(Check("A.X STT 키", "ok" if stt else "fail", "있음" if stt else "AX_STT_API_KEY / AX_API_KEY 둘 다 없음 — F-05 받아쓰기 불가"))
    host = env.get("DEMO_HOST", "127.0.0.1")
    out.append(Check("DEMO_HOST", "fail" if host == "0.0.0.0" and not mock else "ok",
                     f"{host}" + (" — 실 API 모드에서 외부 개방 금지 (CLAUDE.md §2). SSH 터널을 쓴다" if host == "0.0.0.0" else "")))
    return out


def _lora_check(env: dict[str, str]) -> list[Check]:
    out: list[Check] = []
    provider = env.get("HABIT_PROVIDER", "lora")
    path = Path(env.get("CHUCKCHUCK_LORA_PATH") or LORA_DEFAULT)
    if provider != "lora":
        out.append(Check("F-18 LoRA", "warn", f"HABIT_PROVIDER={provider} — 습관 분석이 heuristic 으로 돈다"))
        return out
    if (path / "adapter_config.json").is_file():
        out.append(Check("F-18 LoRA", "ok", f"어댑터 {path}"))
    else:
        out.append(Check("F-18 LoRA", "fail", f"어댑터 없음: {path} — CHUCKCHUCK_LORA_PATH 를 이 머신의 경로로. 없으면 provider 가 heuristic 으로 떨어진다"))
    r = C.sh([C.venv_python(), "-c",
              "import torch;print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-')"],
             timeout=120)
    if r.returncode == 0:
        ver, cuda, name = r.stdout.split(maxsplit=2)
        out.append(Check("torch/CUDA", "ok" if cuda == "True" else "warn",
                         f"{C.venv_python()} · torch {ver} · cuda={cuda} · {name.strip()}"))
        venv_torch = cuda == "True"
    else:
        out.append(Check("torch/CUDA", "warn", f"{C.venv_python()} 에 torch 없음 — 기본 python 으로 띄우면 F-18 은 heuristic"))
        venv_torch = False
    midm = Path(C.sh(["bash", "-c", "echo ${MIDM_PY:-" + MIDM_PY_DEFAULT + "}"]).stdout.strip() or MIDM_PY_DEFAULT)
    if midm.exists():
        out.append(Check("midm python", "ok", str(midm)))
    elif venv_torch:
        out.append(Check("midm python", "warn", f"{midm} 없음. 이 머신은 .venv 에 CUDA torch 가 있으니 "
                         f"`MIDM_PY={C.venv_python()} DEMO_PORT=8799 ./demo/run_bridge_midm.sh` 로 띄운다"))
    else:
        out.append(Check("midm python", "fail", f"{midm} 없음, .venv 에도 torch 없음 — LoRA 브리지를 띄울 python 이 없다"))
    return out


def _tools_check() -> list[Check]:
    out: list[Check] = []
    if shutil.which("nvidia-smi"):
        r = C.sh(["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader"], timeout=30)
        out.append(Check("GPU", "ok" if r.returncode == 0 else "warn", r.stdout.strip().replace("\n", " · ") or r.stderr.strip()[:80]))
    else:
        out.append(Check("GPU", "warn", "nvidia-smi 없음 — LoRA 는 CPU 로 떨어지거나 실패한다"))
    out.append(Check("ffmpeg", "ok" if shutil.which("ffmpeg") else "warn",
                     "있음" if shutil.which("ffmpeg") else "없음 — 10MB 미만 녹음의 WAF 우회가 꺼진다 (DEPLOYMENT §STT, `sudo apt-get install ffmpeg`)"))
    out.append(Check("node", "ok" if shutil.which("node") else "warn",
                     C.sh(["node", "--version"]).stdout.strip() if shutil.which("node") else "없음 — 프론트 JS 스모크(tests/js) 못 돈다"))
    out.append(Check("soffice", "ok" if shutil.which("soffice") or shutil.which("libreoffice") else "warn",
                     "있음" if shutil.which("soffice") or shutil.which("libreoffice") else "없음 — PPTX 미리보기 PDF 변환이 안 될 수 있다"))
    out.append(Check("gh", "ok" if shutil.which("gh") else "skip", "있음" if shutil.which("gh") else "없음 (PR 만들 때만 필요)"))
    return out


def _port_check(env: dict[str, str]) -> list[Check]:
    out: list[Check] = []
    for port in sorted({int(env.get("DEMO_PORT") or 8787), 8799}):
        with socket.socket() as s:
            s.settimeout(0.3)
            busy = s.connect_ex(("127.0.0.1", port)) == 0
        out.append(Check(f"포트 {port}", "ok", "무언가 듣고 있음 (브리지가 떠 있으면 `chk warmup`)" if busy else "비어 있음"))
    return out


def _storage_check(env: dict[str, str]) -> list[Check]:
    data = Path(env.get("DEMO_DATA_DIR") or (C.ROOT / "var/data"))
    free_gb = shutil.disk_usage(C.ROOT).free / 1e9
    return [
        Check("세션 보관소", "ok" if data.exists() else "warn",
              f"{data}" + ("" if data.exists() else " 없음 — 첫 업로드 때 생긴다. 동의 세션 0건")),
        Check("디스크", "ok" if free_gb > 10 else "warn", f"여유 {free_gb:.0f} GB" + ("" if free_gb > 10 else " — 22GB 베이스 모델 캐시가 들어갈 자리를 본다")),
        Check("holdout", "ok" if (C.ROOT / "fixtures/holdout").is_dir() else "warn", "fixtures/holdout 있음 (튜너는 읽지 않는다)" if (C.ROOT / "fixtures/holdout").is_dir() else "없음"),
    ]


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="scripts/chk doctor", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="경고도 실패로")
    ns = ap.parse_args(argv)
    env = C.read_dotenv()
    checks = [Check("머신", "ok", f"{platform.node()} · {platform.system()} · python {platform.python_version()} · {C.ROOT}"),
              Check("git", "ok", f"{C.git('branch', '--show-current').strip()} @ {C.git('rev-parse', '--short', 'HEAD').strip()}")]
    checks += _env_check(env) + _lora_check(env) + _tools_check() + _port_check(env) + _storage_check(env)
    print(C.bold("chk doctor — 이 머신에서 브리지가 뜰 조건"))
    print(C.render(checks))
    fails = [c for c in checks if c.failed or (ns.strict and c.status == "warn")]
    warns = [c for c in checks if c.status == "warn"]
    print(C.bad(f"실패 {len(fails)} · 경고 {len(warns)}") if fails else C.ok(f"실패 0 · 경고 {len(warns)}"))
    return 1 if fails else 0
