"""
F-11 정합 판정 LoRA 학습용 공통 — 경로 · 키 읽기 · 한국 LLM 호출(캐시 · 사용량 기록) · 병렬 실행.

키는 주 체크아웃의 .env 에서 읽기만 한다(값을 찍지 않는다). 산출물은 전부 /data/models/_runs/align-lora 아래다
(루트 디스크가 96% 찼다). LLM 응답은 sqlite 캐시에 남겨 같은 호출은 다시 과금하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

WT = Path(__file__).resolve().parents[3]
MAIN = WT / "main"
REPO_MAIN = Path("/home/yehschuck/project/chuckchuck")           # .env · 덱(로컬 전용)이 있는 주 체크아웃 — 읽기만
RUN = Path(os.environ.get("ALIGN_RUN_ROOT", "/data/models/_runs/align-lora"))
DATA = RUN / "data"
CACHE = RUN / "cache"
CORPUS = WT / "etc/labs/qa_bench/corpus"
DECKS = REPO_MAIN / "main/decks"
PILOT = REPO_MAIN / "Fine-Tune/alignment-pilot"
M3AV = REPO_MAIN / "Fine-Tune/data/M3AV_v1.0/dataset_v1.0_noaudio"

for p in (str(MAIN), str(WT / "etc")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("HF_HOME", str(RUN / "hf"))
os.environ.setdefault("TMPDIR", str(RUN / "tmp"))


def load_env() -> None:
    """주 체크아웃 .env — 이미 있는 키는 덮지 않는다. 값은 어디에도 찍지 않는다."""
    path = REPO_MAIN / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    os.environ["MOCK_EXTERNAL_APIS"] = "false"


def jdump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def jload(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# LLM — 제공자 설정은 pipeline.providers 에서 빌리고, 호출은 여기서 해 사용량(usage)을 남긴다
# ---------------------------------------------------------------------------

_db_lock = threading.Lock()
_engines: dict = {}
#: 제공자별 초당 호출 상한 — Upstage 는 분당 한도를 넘으면 429 를 낸다(10/16 실측, 8 병렬에서). 같은 키를 쓰는 다른 일도 있다.
RPS = {"solar": float(os.environ.get("ALIGN_SOLAR_RPS", "2.0")), "ax": float(os.environ.get("ALIGN_AX_RPS", "1.5"))}
_rate_lock = threading.Lock()
_next_slot: dict[str, float] = {}


def _throttle(name: str) -> None:
    gap = 1.0 / RPS.get(name, 2.0)
    with _rate_lock:
        now = time.time()
        slot = max(now, _next_slot.get(name, 0.0))
        _next_slot[name] = slot + gap
    if slot > now:
        time.sleep(slot - now)


def _db() -> sqlite3.Connection:
    CACHE.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(CACHE / "llm.sqlite"), timeout=60, check_same_thread=False)
    con.execute("create table if not exists c (k text primary key, engine text, out text, pin int, pout int, ts real)")
    return con


_con = None


def _conn():
    global _con
    if _con is None:
        _con = _db()
    return _con


def _engine(name: str):
    if name not in _engines:
        load_env()
        from pipeline.providers.llm_impl import get_llm
        _engines[name] = get_llm(name)
    return _engines[name]


def llm(name: str, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 1200,
        json_mode: bool = True, tag: str = "", retries: int = 6) -> str:
    """캐시를 거쳐 한 번 부른다. tag 는 같은 입력을 일부러 다시 부를 때(두 번째 판정) 캐시 열쇠를 가른다."""
    import requests

    key = hashlib.sha1(json.dumps([name, system, user, temperature, max_tokens, json_mode, tag],
                                  ensure_ascii=False).encode()).hexdigest()
    with _db_lock:
        row = _conn().execute("select out from c where k=?", (key,)).fetchone()
    if row:
        return row[0]
    eng = _engine(name)
    payload = {
        "model": eng.model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {eng.api_key}", "Content-Type": "application/json", **eng.extra_headers}
    last = ""
    for attempt in range(retries):
        _throttle(name)
        try:
            res = requests.post(f"{eng.base_url}/chat/completions", headers=headers, json=payload, timeout=240)
        except (requests.Timeout, requests.ConnectionError) as e:
            last = f"{type(e).__name__}"
            time.sleep(5 * (attempt + 1))
            continue
        if res.status_code == 200:
            body = res.json()
            msg = (body.get("choices") or [{}])[0].get("message") or {}
            out = msg.get("content") or ""
            if not out:
                last = "empty"
                time.sleep(2)
                continue
            use = body.get("usage") or {}
            with _db_lock:
                _conn().execute("insert or replace into c values (?,?,?,?,?,?)",
                                (key, name, out, int(use.get("prompt_tokens") or 0),
                                 int(use.get("completion_tokens") or 0), time.time()))
                _conn().commit()
            return out
        last = f"HTTP {res.status_code}: {res.text[:160]}"
        if res.status_code in (429, 500, 502, 503, 504):
            print(f"[llm:{name}] HTTP {res.status_code} — {15 * (attempt + 1)}s 쉬고 다시", flush=True)
            time.sleep(15 * (attempt + 1))
            continue
        break
    raise RuntimeError(f"[{name}] LLM 실패: {last}")


def usage_report() -> dict:
    with _db_lock:
        rows = _conn().execute("select engine, count(*), sum(pin), sum(pout) from c group by engine").fetchall()
    return {e: {"calls": n, "prompt_tokens": a or 0, "completion_tokens": b or 0} for e, n, a, b in rows}


def parse_json(raw: str) -> dict:
    from pipeline._json_text import extract_json_object
    d = extract_json_object(raw)
    if not isinstance(d, dict):
        raise ValueError("JSON 객체가 아니다")
    return d


def pmap(fn, items, workers: int = 4, desc: str = "", every: int = 25):
    """순서 보존 병렬 map. 실패는 예외 객체로 돌려준다(한 항목 때문에 전체를 버리지 않는다)."""
    out = [None] * len(items)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, it): i for i, it in enumerate(items)}
        for n, f in enumerate(as_completed(futs), 1):
            i = futs[f]
            try:
                out[i] = f.result()
            except Exception as e:  # noqa: BLE001
                out[i] = e
            if desc and (n % every == 0 or n == len(items)):
                print(f"[{desc}] {n}/{len(items)} {time.time() - t0:.0f}s", flush=True)
    return out
