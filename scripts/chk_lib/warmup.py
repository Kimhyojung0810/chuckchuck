"""
브리지를 예열하고 F-18 이 진짜 LoRA 로 도는지 확인한다 (CLAUDE.md §2 의 curl 을 도구로).

    scripts/chk warmup                    # 127.0.0.1:$DEMO_PORT(.env) 또는 8799
    scripts/chk warmup --port 8801 --expect heuristic

두 번 부른다: 첫 호출은 22GB 베이스 모델 로드(2~3분), 둘째가 실제 지연(예열 뒤 ~1.2초). provider 가 기대와
다르면 exit 1 — heuristic(lora-fallback) 이면 python 을 잘못 쓴 것이다 (`chk doctor`).
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request

from . import common as C

SAMPLE = {"transcript": {"by_slide": [{"slide_no": 1, "start_sec": 0, "end_sec": 3, "words": [
    {"text": "지도", "start_sec": 0, "end_sec": 0.4}, {"text": "지도력은", "start_sec": 0.4, "end_sec": 1}]}]}}


def _post(url: str, body: dict, timeout: int) -> tuple[int, dict, float]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}"), time.monotonic() - t0
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except json.JSONDecodeError:
            payload = {}
        return e.code, payload, time.monotonic() - t0


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="scripts/chk warmup", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    env = C.read_dotenv()
    ap.add_argument("--host", default=env.get("DEMO_HOST") or "127.0.0.1")
    ap.add_argument("--port", type=int, default=int(env.get("DEMO_PORT") or 8799))
    ap.add_argument("--expect", default="lora", help="기대하는 provider (기본 lora)")
    ap.add_argument("--timeout", type=int, default=400, help="첫 호출 대기 초 (모델 로드 포함)")
    ap.add_argument("--once", action="store_true", help="한 번만 부른다")
    ns = ap.parse_args(argv)
    base = f"http://{ns.host}:{ns.port}"

    try:
        with urllib.request.urlopen(base + "/", timeout=5) as r:
            print(C.ok(f"브리지 응답 {r.status} @ {base}"))
    except (urllib.error.URLError, OSError) as e:
        print(C.bad(f"{base} 에 브리지가 없어요 ({e}). `DEMO_PORT={ns.port} ./demo/run_bridge_midm.sh` 로 띄운다 (이 머신 조건은 `chk doctor`)"))
        return 1

    rounds = 1 if ns.once else 2
    provider = None
    for i in range(rounds):
        try:
            status, body, dt = _post(base + "/api/v1/habits", SAMPLE, ns.timeout if i == 0 else 60)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            print(C.bad(f"{i + 1}차 호출 실패: {e}"))
            return 1
        if status != 200:
            print(C.bad(f"{i + 1}차 HTTP {status}: {body.get('message') or body.get('error') or body}"))
            return 1
        provider = body.get("provider")
        label = "예열(모델 로드 포함)" if i == 0 and rounds == 2 else "실제 지연"
        print(C.ok(f"{i + 1}차 {label} {dt:.2f}초 · provider={provider} · REP={body.get('repeat_cnt')} FIL={body.get('filler_cnt')} PAUSE={body.get('pause_cnt')}"))

    if provider != ns.expect:
        print(C.bad(f"provider 가 {provider!r} — 기대 {ns.expect!r}. heuristic/lora-fallback 이면 torch 없는 python 이거나 LoRA 경로가 틀렸다 (`chk doctor`)"))
        return 1
    print(C.ok(f"provider={ns.expect} 확인. 시연 준비됨."))
    return 0
