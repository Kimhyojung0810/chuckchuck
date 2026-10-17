#!/usr/bin/env python3
"""
제공자 요청 변수(파라미터) 비교 — 호출 로그에 남은 **실제 요청**을 변수만 바꿔 다시 보낸다 (10-17 국내 모델 조사의 시험 거리).

    python etc/bench/calllog_run.py etc/bench/param_replay.py --model exaone --feature F-08 --n 8 --reps 2 \\
        --variant base --variant 'pp15:{"presence_penalty":1.5}' --out /data/models/_runs/qa-ensemble/param/exaone.json

- EXAONE 되풀이 고리: 모델 카드 권장 presence_penalty=1.5 (우리는 0.5 까지만 쟀다)
- A.X K2: chat_template_kwargs.enable_thinking 을 명시(1.8배 느림의 원인 추정)
- Mi:dm: response_format json_schema (json_object 는 400 7005)
재는 것: 지연 · 출력 토큰 · finish_reason(length = 고리/잘림) · JSON 파싱 성공 · 질문 수.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "main"), str(ROOT / "etc"), str(ROOT)]

from pipeline.config import load_dotenv  # noqa: E402

load_dotenv()
from pipeline import _ai_calllog  # noqa: E402
from pipeline._json_text import extract_json_object  # noqa: E402
from pipeline.providers.llm_impl import REGISTRY  # noqa: E402

MODEL_KEYS = {"exaone": ("friendli",), "ax": ("A.X",), "midm": ("midm",), "solar": ("solar",)}


def requests_from_log(log_dir: str, model: str, feature: str, n: int) -> list[dict]:
    out = []
    for f in sorted(glob.glob(f"{log_dir}/*/{feature}.jsonl")):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            req = r.get("request") or {}
            ep = req.get("endpoint", "") + " " + str(req.get("model") or "")
            body = req.get("body") or {}
            if not isinstance(body, dict) or "messages" not in body:
                continue
            if not any(k.lower() in ep.lower() for k in MODEL_KEYS[model]):
                continue
            out.append(body)
    # 서로 다른 요청만, 뒤에서부터 (최근)
    seen, uniq = set(), []
    for b in reversed(out):
        k = json.dumps(b["messages"][-1], ensure_ascii=False)[-3000:]
        if k not in seen:
            seen.add(k)
            uniq.append(b)
    return uniq[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--feature", default="F-08")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--variant", action="append", default=[])
    ap.add_argument("--log-dir", default=os.environ.get("AI_CALLLOG_DIR", ""))
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    bodies = requests_from_log(a.log_dir, a.model, a.feature, a.n)
    variants = []
    for v in a.variant or ["base"]:
        name, _, js = v.partition(":")
        variants.append((name, json.loads(js) if js else {}))
    rows = []
    for i, body in enumerate(bodies):
        msgs = body["messages"]
        system = next((m["content"] for m in msgs if m["role"] == "system"), "")
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        for name, extra in variants:
            for rep in range(a.reps):
                llm = REGISTRY[a.model]()
                if extra.get("chat_template_kwargs") and getattr(llm, "extra_body", None) is not None:
                    llm.extra_body["chat_template_kwargs"] = {**llm.extra_body.get("chat_template_kwargs", {}),
                                                              **extra["chat_template_kwargs"]}
                llm.extra_body.update({k: v for k, v in extra.items() if k not in ("chat_template_kwargs", "json_schema")})
                if extra.get("json_schema"):
                    llm.extra_body["response_format"] = {"type": "json_schema", "json_schema": {
                        "name": "out", "schema": {"type": "object", "properties": {"items": {"type": "array"},
                                                                                     "questions": {"type": "array"}}}}}
                t0 = time.monotonic()
                try:
                    with _ai_calllog.feature_scope("F-08-bench"):
                        out = llm.complete(system=system, user=user, temperature=body.get("temperature", 0.3),
                                           max_tokens=int(body.get("max_tokens") or 4096), json_mode=True)
                    ok_json = True
                    try:
                        d = extract_json_object(out)
                        n_items = len(d.get("items") or d.get("questions") or [])
                    except ValueError:
                        ok_json, n_items = False, 0
                    u = llm.last_usage or {}
                    rows.append({"req": i, "variant": name, "rep": rep, "sec": round(time.monotonic() - t0, 2),
                                 "finish": llm.last_finish, "out_tokens": u.get("completion_tokens"), "json": ok_json,
                                 "items": n_items, "error": ""})
                except Exception as e:  # noqa: BLE001
                    rows.append({"req": i, "variant": name, "rep": rep, "sec": round(time.monotonic() - t0, 2),
                                 "error": f"{type(e).__name__}: {str(e)[:160]}"})
                print(rows[-1], flush=True)
    summ = {}
    for name, _ in variants:
        rs = [r for r in rows if r["variant"] == name]
        ok = [r for r in rs if not r["error"]]
        secs = sorted(r["sec"] for r in ok)
        summ[name] = {"n": len(rs), "errors": len(rs) - len(ok), "json_ok": sum(1 for r in ok if r["json"]),
                      "length_finish": sum(1 for r in ok if r.get("finish") == "length"),
                      "p50": secs[len(secs) // 2] if secs else None, "p95": secs[int(0.95 * (len(secs) - 1))] if secs else None,
                      "out_tokens_mean": round(st.mean([r["out_tokens"] for r in ok if r.get("out_tokens")]), 1)
                      if any(r.get("out_tokens") for r in ok) else None,
                      "items_mean": round(st.mean([r["items"] for r in ok]), 2) if ok else None}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"model": a.model, "feature": a.feature, "n_requests": len(bodies), "summary": summ,
                                 "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
