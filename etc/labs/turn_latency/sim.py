#!/usr/bin/env python3
"""
말 끝 판단 모의 (2026-10-17 tune) — 진짜 A.X 사건 시각표(stt_trace.py)에 화상판 자동 보내기 규칙(booth_call.js bcAutoSend ·
js/qa_turn.js silenceFor)을 그대로 돌려 **너무 일찍 보냄(사람 말 자름)** 과 **말 끝 → 보내기** 를 잰다.

- 시각표 하나 = 한 사람이 쉬지 않고 이어 말한 긴 말(발표 녹음). 문장 사이(문장 확정 뒤 다음 말소리 시작 전)마다
  「여기서 보내 버리나」 를 본다 — 보내면 자름 1건(이어 말하던 사람을 끊었다), 그 뒤 다음 말소리부터 다시 듣는다.
- 맨 끝(마지막 문장 확정) 뒤에는 말이 없다 — 거기서 보내기까지 걸린 시간이 말 끝 → 보내기.
- 질문 답은 발표보다 생각하며 쉬는 일이 많다(음성UX 조사 1-1 Rowe) — 문장 사이 쉼을 --gap-scale 배로 늘려 민감도를 본다.
- 어미 판단은 js/qa_turn.js 를 node 로 그대로 돌린다(사본을 쓰지 않는다).

    .venv/bin/python etc/labs/turn_latency/sim.py --traces /data/models/_runs/wt-qa-tune/stt_trace --json out.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TICK = 0.3   # booth_call.js BC_AUTO_TICK_MS

PRESETS = {
    "base": {"eot": "fixed", "silenceMs": 2200, "sendMs": 3000},                  # 지금 기본 (5단계)
    "fixed_1.2+1.2": {"eot": "fixed", "silenceMs": 1200, "sendMs": 1200},
    "fixed_0.9+1.2": {"eot": "fixed", "silenceMs": 900, "sendMs": 1200},
    "ending+3.0": {"eot": "ending", "silenceMs": 2200, "sendMs": 3000, "finalMs": 900, "softMs": 1800, "contMs": 3200},
    "fast": {"eot": "ending", "silenceMs": 2200, "sendMs": 1200, "finalMs": 900, "softMs": 1800, "contMs": 3200},   # ?qa_turn=fast
    "fast_0.6": {"eot": "ending", "silenceMs": 2200, "sendMs": 600, "finalMs": 900, "softMs": 1800, "contMs": 3200},
    "fast_1.8": {"eot": "ending", "silenceMs": 2200, "sendMs": 1800, "finalMs": 900, "softMs": 1800, "contMs": 3200},
    "ending_1.5+1.2": {"eot": "ending", "silenceMs": 2200, "sendMs": 1200, "finalMs": 1500, "softMs": 2200, "contMs": 3500},
    "rec_1.8+1.4": {"eot": "ending", "silenceMs": 2200, "sendMs": 1400, "finalMs": 1800, "softMs": 2400, "contMs": 3500},   # 권고안
    "fixed_1.8+1.4": {"eot": "fixed", "silenceMs": 1800, "sendMs": 1400},
}

NODE_KIND = r"""
const fs = require('fs'); const vm = require('vm');
const box = { console, location: { search: '' }, URLSearchParams }; box.window = box;
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), box);
const texts = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(texts.map((t) => box.QaTurn.endKind(t))));
"""


def end_kinds(texts: list[str]) -> list[str]:
    out = subprocess.run(["node", "-e", NODE_KIND, str(ROOT / "main/web/js/qa_turn.js")], input=json.dumps(texts),
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def silence_for(kind: str, cfg: dict) -> float:
    if cfg["eot"] != "ending":
        return cfg["silenceMs"] / 1000
    return {"final": cfg["finalMs"], "soft": cfg["softMs"], "cont": cfg["contMs"]}.get(kind, cfg["silenceMs"]) / 1000


def simulate(events: list[dict], kinds: dict[int, str], cfg: dict, gap_scale: float = 1.0) -> dict:
    """사건 열 → 보낸 때 목록. kinds: text 사건 번호 → 어미 종류. gap_scale: 문장 사이 쉼(text → 다음 speech on)을 늘린다."""
    # 쉼 늘리기 — text 뒤 다음 speech on 까지를 gap_scale 배, 그 뒤 사건은 모두 그만큼 밀린다
    ev, shift, last_text_t = [], 0.0, None
    for i, e in enumerate(events):
        t = e["t"]
        if e.get("type") == "speech" and e.get("on") and last_text_t is not None:
            gap = t - last_text_t
            shift += gap * (gap_scale - 1.0)
            last_text_t = None
        if e.get("type") == "text":
            last_text_t = t
        ev.append({**e, "t": round(t + shift, 3), "i": i})
    ev = [e for e in ev if e.get("type") in ("speech", "text")]
    if not ev:
        return {"sends": [], "boundaries": 0}
    end_t = ev[-1]["t"] + 12.0
    speaking, last_at, final_kind, have_text = False, None, "none", False
    send_at, sends = None, []
    k, t = 0, ev[0]["t"]
    texts_done = 0
    while t <= end_t:
        while k < len(ev) and ev[k]["t"] <= t:
            e = ev[k]
            if e["type"] == "speech":
                speaking = bool(e.get("on"))
                last_at = e["t"]
            else:
                speaking, last_at, have_text = False, e["t"], True
                final_kind = kinds.get(e["i"], "unknown")
                texts_done += 1
            k += 1
        settled = (not speaking) and last_at is not None and have_text
        quiet = settled and t - last_at >= silence_for(final_kind, cfg)
        if not quiet:
            send_at = None
        elif send_at is None:
            send_at = t + cfg["sendMs"] / 1000
        if send_at is not None and t >= send_at:
            more = k < len(ev)   # 뒤에 사건이 남았다 = 그 사람은 이어 말했다 → 자름
            sends.append({"t": round(t, 2), "after_text": round(t - last_at, 2), "cut": more, "kind": final_kind,
                          "texts": texts_done})
            send_at, have_text = None, False   # 보낸 뒤 칸이 비었다 — 다음 말부터 새로 듣는다
            if not more:
                break
        t = round(t + TICK, 3)
    n_text = sum(1 for e in ev if e["type"] == "text")
    return {"sends": sends, "boundaries": max(0, n_text - 1), "end_send": next((s for s in sends if not s["cut"]), None)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", required=True)
    ap.add_argument("--gap-scales", default="1,1.5,2")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    traces = [json.loads(p.read_text()) | {"name": p.stem} for p in sorted(Path(args.traces).glob("*.json")) if p.stem != "smoke"]
    # 어미 종류 (node · js/qa_turn.js)
    all_texts, idx = [], []
    for ti, tr in enumerate(traces):
        for i, e in enumerate(tr["events"]):
            if e.get("type") == "text":
                all_texts.append(e.get("text") or "")
                idx.append((ti, i))
    kinds_flat = end_kinds(all_texts)
    kinds = [dict() for _ in traces]
    for (ti, i), kd in zip(idx, kinds_flat):
        kinds[ti][i] = kd
    from collections import Counter
    report = {"n_traces": len(traces), "n_sentences": len(all_texts), "kind_mix": dict(Counter(kinds_flat)), "presets": {}}
    # 실제 쉼 분포 — 문장 확정 → 다음 말소리 시작 (= 자동 보내기가 버텨야 하는 쉼)
    gaps = []
    for tr in traces:
        last = None
        for e in tr["events"]:
            if e.get("type") == "text":
                last = e["t"]
            elif e.get("type") == "speech" and e.get("on") and last is not None:
                gaps.append(round(e["t"] - last, 2))
                last = None
    gaps.sort()
    q = lambda xs, p: xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None  # noqa: E731
    report["gap_after_text"] = {"n": len(gaps), "p50": q(gaps, .5), "p90": q(gaps, .9), "p95": q(gaps, .95), "max": gaps[-1] if gaps else None}
    # A.X 늦음 α — 에너지 말소리 끝 → eos(speech off)
    lags = []
    for tr in traces:
        segs = tr.get("segments") or []
        for e in tr["events"]:
            if e.get("type") == "speech" and e.get("on") is False:
                ends = [b for a, b in segs if b <= e["t"] + 0.05]
                if ends:
                    lags.append(round(e["t"] - ends[-1], 2))
    lags.sort()
    report["eos_lag"] = {"n": len(lags), "p50": q(lags, .5), "p90": q(lags, .9)}
    for name, cfg in PRESETS.items():
        row = {}
        for gs in [float(x) for x in args.gap_scales.split(",")]:
            cuts, bounds, end_lat = 0, 0, []
            for tr, kd in zip(traces, kinds):
                r = simulate(tr["events"], kd, cfg, gs)
                cuts += sum(1 for s in r["sends"] if s["cut"])
                bounds += r["boundaries"]
                if r["end_send"]:
                    end_lat.append(r["end_send"]["after_text"])
            end_lat.sort()
            row[f"x{gs:g}"] = {"cut_per_boundary": round(cuts / bounds, 3) if bounds else None, "cuts": cuts, "boundaries": bounds}
        # 「여기서 답이 끝났다면」 — 문장마다 확정 → 보내기 (침묵 + 초읽기 + 300ms 틱의 평균 반) · 3문장 답 하나를 자를 확률
        ifend = sorted(silence_for(k, cfg) + cfg["sendMs"] / 1000 + TICK / 2 for k in kinds_flat)
        row["text_to_send_if_end_p50"] = round(q(ifend, .5), 2)
        row["text_to_send_if_end_final"] = round(silence_for("final", cfg) + cfg["sendMs"] / 1000 + TICK / 2, 2)
        p1 = row["x1.5"]["cut_per_boundary"] if "x1.5" in row else None
        row["cut_3sentence_answer_x1.5"] = round(1 - (1 - p1) ** 2, 3) if p1 is not None else None
        report["presets"][name] = row
    # 맨 끝 문장의 어미별 — 말 끝 → 보내기는 어미에 달렸다 (fast 기준)
    txt = json.dumps(report, ensure_ascii=False, indent=1)
    print(txt)
    if args.json:
        Path(args.json).write_text(txt, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
