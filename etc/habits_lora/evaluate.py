"""
습관 태거 평가 — 서비스와 같은 경로(_lora_tagger.tag_habits + _lora_runtime 러너)로 돌려 스팬 P/R/F1 을 잰다.

호출 (GPU 잠금 안에서):
  # FIL 3시드 앙상블 (min 방식) — 옛 기록: P 0.9927 / R 0.7253 / F1 0.838 (rp 1.2)
  flock ~/.cache/chuckchuck-gpu.lock python etc/habits_lora/evaluate.py --kind FIL \\
      --data /data/models/_runs/habits-lora/data/FIL/test.jsonl \\
      --adapters /data/models/_runs/habits-lora/fil_seed{42,43,44}/final
  # REP (통합 태거, greedy rp 1.0) — 옛 기록: F1 0.686±0.027 (3시드 평균)
  flock ~/.cache/chuckchuck-gpu.lock python etc/habits_lora/evaluate.py --kind REP \\
      --data /data/models/_runs/habits-lora/data/unified/test.jsonl --adapters /data/models/_runs/habits-lora/rep_seed42/final
  # 정답 없는 전사문(서비스 Transcript JSON) — 지금 환경변수 설정 그대로 돌려 스팬·지연·VRAM 만
  flock ~/.cache/chuckchuck-gpu.lock python etc/habits_lora/evaluate.py --transcript etc/fixtures/focus_transcript.json

채점: 문서마다 (태그, 정규화한 구간 글자) 의 중복 집합을 정답과 맞춘다 — TP = Σ min(예측 수, 정답 수), 전체 합산(micro).
예측은 서비스처럼 전사문 단어 위에 위치를 찾은 것만 센다 (못 찾은 줄은 unlocated 로 따로 센다).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = Path(os.environ.get("HABITS_LORA_RUNS", "/data/models/_runs/habits-lora"))
sys.path.insert(0, str(ROOT / "main"))

from pipeline import _lora_tagger as LT  # noqa: E402
from pipeline.contracts import Transcript, Word  # noqa: E402


def doc_transcript(stt: str) -> Transcript:
    """정답 데이터의 STT 전문 → 단어마다 가짜 0.3초 타임스탬프 (위치 찾기·청크 나누기를 서비스와 같이 태운다)."""
    words = [Word(text=t, start_sec=i * 0.3, end_sec=i * 0.3 + 0.25) for i, t in enumerate(stt.split())]
    return Transcript(full_text=stt, words=words)


def _key(text: str) -> str:
    return "".join(LT._tok(t) for t in text.split())


def score(pred: list[Counter], gold: list[Counter]) -> dict:
    tp = sum(sum((p & g).values()) for p, g in zip(pred, gold))
    np_, ng = sum(sum(p.values()) for p in pred), sum(sum(g.values()) for g in gold)
    prec = tp / np_ if np_ else 0.0
    rec = tp / ng if ng else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    mae = sum(abs(sum(p.values()) - sum(g.values())) for p, g in zip(pred, gold)) / max(1, len(gold))
    return {"precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
            "pred": np_, "gold": ng, "tp": tp, "count_mae": round(mae, 3)}


def config_for(kind: str, adapters: list[Path], ns) -> LT.TaggerConfig:
    base = LT.load_config()
    if kind == "REP":
        a = adapters[0]
        task = LT._read_task(a, LT.TaskSpec(LT.SYSTEM_PROMPT, LT.USER_TEMPLATE, ns.rp or 1.0))
        if ns.rp:
            task = LT.TaskSpec(task.system_prompt, task.user_template, ns.rp, task.max_new_tokens)
        return LT.TaggerConfig(base.base, LT.AdapterSpec("rep", a, "REP", frozenset({"REP"}), task),
                               chunk_chars=ns.chunk_chars, max_batch=ns.max_batch)
    sys_p, user_t = (LT.SYSTEM_PROMPT, LT.USER_TEMPLATE) if ns.unified_prompt else LT.TASK_PROMPTS["FIL"]
    fil = []
    for i, a in enumerate(adapters):
        t = LT._read_task(a, LT.TaskSpec(sys_p, user_t, ns.rp or 1.2))
        if ns.rp:
            t = LT.TaskSpec(t.system_prompt, t.user_template, ns.rp, t.max_new_tokens)
        fil.append(LT.AdapterSpec(f"fil{i}", a, "FIL", frozenset({"FIL"}), t))
    votes = ns.min_votes or len(fil)
    return LT.TaggerConfig(base.base, None, tuple(fil), min(votes, len(fil)), ns.chunk_chars, ns.max_batch)


def _vram() -> dict:
    try:
        import torch

        return {"vram_alloc_gb": round(torch.cuda.memory_allocated() / 2**30, 2),
                "vram_peak_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2)}
    except Exception:  # noqa: BLE001
        return {}


def run_labeled(ns) -> dict:
    from pipeline import _lora_runtime as RT

    adapters = [Path(a) for a in ns.adapters]
    cfg = config_for(ns.kind, adapters, ns)
    rows = [json.loads(x) for x in ns.data.read_text(encoding="utf-8").splitlines() if x.strip()]
    if ns.limit:
        rows = rows[:ns.limit]
    t0 = time.time()
    runner = RT.get_runner(cfg, wait=True)
    load = time.time() - t0
    pred, gold, lat, unloc = [], [], [], Counter()
    for r in rows:
        t1 = time.time()
        res = LT.tag_habits(doc_transcript(r["stt"]), config=cfg, runner=runner)
        lat.append(time.time() - t1)
        unloc.update(res.stats.get("unlocated", {}))
        pred.append(Counter(_key(s.text) for s in res.spans if s.kind == ns.kind))
        gold.append(Counter(_key(t) for tag, t in LT.parse_tag_lines(r["target"]) if tag == ns.kind))
    out = {"kind": ns.kind, "docs": len(rows), "adapters": [str(a) for a in adapters],
           "min_votes": cfg.fil_min_votes if cfg.fil else None,
           "rp": [a.task.repetition_penalty for a in cfg.adapters], **score(pred, gold),
           "unlocated": dict(unloc), "load_sec": round(load, 1),
           "latency_sec": {"mean": round(sum(lat) / max(1, len(lat)), 2), "max": round(max(lat or [0]), 2)},
           **_vram()}
    return out


def run_transcript(ns) -> dict:
    from pipeline import _lora_runtime as RT

    cfg = LT.load_config()
    if not cfg.adapters:
        raise SystemExit("어댑터가 없어요 — CHUCKCHUCK_LORA_REP_PATH / CHUCKCHUCK_LORA_FIL_PATHS 를 확인하세요")
    t = Transcript.from_dict(json.loads(ns.transcript.read_text(encoding="utf-8")))
    t0 = time.time()
    runner = RT.get_runner(cfg, wait=True)
    load = time.time() - t0
    lat = []
    for _ in range(ns.repeat):
        t1 = time.time()
        res = LT.tag_habits(t, config=cfg, runner=runner)
        lat.append(round(time.time() - t1, 2))
    return {"transcript": str(ns.transcript), "words": len(LT._words(t)), "adapters": [a.name for a in cfg.adapters],
            "covered": res.covered, "stats": res.stats, "load_sec": round(load, 1), "latency_sec": lat,
            "counts": dict(Counter(s.kind for s in res.spans)),
            "spans": [(s.kind, s.text, s.start_sec, s.slide_no) for s in res.spans][:40], **_vram()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", choices=("REP", "FIL"))
    ap.add_argument("--data", type=Path, help="aihub.py 가 만든 test.jsonl")
    ap.add_argument("--adapters", nargs="+", default=[])
    ap.add_argument("--min-votes", type=int, default=0, help="기본 = 어댑터 수 (min 방식)")
    ap.add_argument("--rp", type=float, default=0.0, help="repetition_penalty 덮어쓰기 (기본: chuckchuck_task.json · REP 1.0 · FIL 1.2)")
    ap.add_argument("--unified-prompt", action="store_true", help="FIL 어댑터를 통합(REP/FIL/WR) 프롬프트로 학습했을 때")
    ap.add_argument("--chunk-chars", type=int, default=LT.DEFAULT_CHUNK_CHARS)
    ap.add_argument("--max-batch", type=int, default=LT.DEFAULT_MAX_BATCH)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--transcript", type=Path, help="정답 없는 서비스 Transcript JSON")
    ap.add_argument("--repeat", type=int, default=2, help="--transcript 지연을 몇 번 잴까 (첫 번째는 예열 포함)")
    ap.add_argument("--out", type=Path)
    ns = ap.parse_args(argv)
    os.environ.setdefault("HF_HOME", str(RUNS / "hf_cache"))   # 루트 디스크가 96% — 캐시는 /data 로
    if ns.transcript:
        res = run_transcript(ns)
    else:
        if not (ns.kind and ns.data and ns.adapters):
            ap.error("--kind · --data · --adapters 가 필요해요 (또는 --transcript)")
        res = run_labeled(ns)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    print(text)
    if ns.out:
        ns.out.parent.mkdir(parents=True, exist_ok=True)
        ns.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
