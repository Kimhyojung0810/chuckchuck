"""
판정 항목 만들기 — 덱·녹음(또는 대본 변형)마다 Transcript 를 만들고 제품 함수(_align_lora.build_items)로 개념별 항목을 뽑는다.
결함을 일부러 심은 곳은 「구성 라벨」(cons)을 같이 단다 — 무엇을 바꿨는지 알기 때문에 아는 라벨이다.

  ko_synth : 합성 덱 × {clean 충실한 대본, flawed 결함 5+건너뛰기 1, drop 문장 25% 무작위로 뺌}
  ko_real  : 시험셋 녹음(qa_bench · 부스 대본) — 심은 결함(truth)을 cons 로

산출: DATA/items_ko_synth.jsonl · DATA/items_ko_real.jsonl
"""

from __future__ import annotations

import argparse
import random
import re

from common import DATA, jdump, jload, write_jsonl

from pipeline._align_lora import build_items
from pipeline._deck_claims import content_stems
from pipeline._spoken import count_hits
from pipeline.contracts import ConceptGraph, SlideDoc, Transcript

SKIP_CUES = [
    "이 장은 시간 관계상 그냥 넘어갈게요.", "이 부분은 오늘은 건너뛸게요.", "여기는 자세한 건 생략하고 다음으로 갈게요.",
    "이건 좀 복잡해서 오늘은 생략하고 바로 넘어가겠습니다.", "이 내용은 나중에 질문 주시면 설명드릴게요.",
]
FILLERS = ["음", "어", "그", "약간", "이제"]


# ---------------------------------------------------------------------------
# Transcript 만들기
# ---------------------------------------------------------------------------

def transcript_from(slides: list[tuple[int, list[str]]], *, punct: bool, rng: random.Random, filler: float = 0.0) -> Transcript:
    """장별 문장 → Transcript. punct=False 면 A.X STT 처럼 마침표 없이 잇는다. 어절 시각은 0.4초씩."""
    segs, words, t = [], [], 0.0
    for no, sents in slides:
        parts = []
        for s in sents:
            s = " ".join(s.split())
            if not s:
                continue
            if filler and rng.random() < filler:
                s = f"{rng.choice(FILLERS)} {s}"
            s = s.rstrip()
            if punct and not re.search(r"[.?!]$", s):
                s += "."
            if not punct:
                s = s.rstrip(".")
            parts.append(s)
        text = " ".join(parts)
        start = t
        ws = []
        for w in text.split():
            ws.append({"text": w, "start_sec": round(t, 2), "end_sec": round(t + 0.38, 2)})
            t += 0.4
        segs.append({"slide_no": no, "visit": 1, "start_sec": round(start, 2), "end_sec": round(t + 0.5, 2),
                     "text": text, "words": ws})
        t += 0.5
        words += ws
    return Transcript.from_dict({"full_text": " ".join(s["text"] for s in segs), "words": words, "by_slide": segs,
                                 "provider": "synthetic", "duration_sec": round(t, 2)})


def apply_flaws(script: dict, flaws: list[dict], n_slides: int, rng: random.Random) -> tuple[list, list[dict]]:
    """결함 적용 + 코드가 고른 건너뛰기 한 장. 돌려주는 것: (장별 문장, 적용한 결함 목록)."""
    sents = {s["slide_no"]: list(s["sentences"]) for s in script["slides"]}
    applied, touched_slides = [], set()
    repl: dict[str, str | None] = {}
    for f in flaws:
        sids = [x for x in f["sids"] if x not in repl]
        if not sids or f["type"] not in ("contradiction_number", "contradiction_flip", "omission", "name_only"):
            continue
        for k, sid in enumerate(sids):
            repl[sid] = (f["new_text"] or None) if k == 0 else None
        applied.append(f)
        touched_slides.add(f["slide_no"])
    out = []
    for no in range(1, n_slides + 1):
        row = []
        for j, s in enumerate(sents.get(no, []), 1):
            sid = f"s{no:02d}-{j:02d}"
            if sid in repl:
                if repl[sid]:
                    row.append(repl[sid])
            else:
                row.append(s)
        out.append([no, row])
    middle = [no for no in range(2, n_slides) if no not in touched_slides and sents.get(no)]
    if middle:
        no = rng.choice(middle)
        cue = rng.choice(SKIP_CUES)
        out[no - 1][1] = [cue]
        applied.append({"type": "skip", "slide_no": no, "deck_line": "", "sids": [], "new_text": cue})
    return [tuple(x) for x in out], applied


# ---------------------------------------------------------------------------
# 결함 → 개념
# ---------------------------------------------------------------------------

def _score(node, stems: list[str]) -> float:
    lab = list(dict.fromkeys(content_stems(node.label)))
    rest = list(dict.fromkeys(content_stems(" ".join([node.summary or "", *(node.evidence or [])]))))
    if not lab:
        return 0.0
    return 2 * count_hits(lab, stems) / len(lab) + (count_hits(rest, stems) / len(rest) if rest else 0.0)


def nodes_for_line(graph: ConceptGraph, slide_no: int, text: str, *, min_score: float = 1.0, near: float = 0.7) -> list:
    """그 장 개념 중 자료 줄과 이름이 절반 넘게 겹치는 것(이름 2배 가중). 가장 잘 맞는 것과 near 배 이내만(1.0 이면 1등만)."""
    stems = list(dict.fromkeys(content_stems(text)))
    if not stems:
        return []
    cands = [(n, _score(n, stems)) for n in graph.nodes if slide_no in n.slide_nos]
    cands = [(n, s) for n, s in cands if s >= min_score]
    if not cands:
        return []
    best = max(s for _, s in cands)
    return [n for n, s in cands if s >= near * best]


def cons_synth(graph: ConceptGraph, applied: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in applied:
        if f["type"] == "skip":
            for n in graph.nodes:
                if n.slide_nos and set(n.slide_nos) <= {f["slide_no"]}:
                    out.setdefault(n.id, {"label": "missing", "flaw": "skip"})
            continue
        label = "contradiction" if f["type"].startswith("contradiction") else "missing"
        for n in nodes_for_line(graph, f["slide_no"], f["deck_line"]):
            prev = out.get(n.id)
            if prev and prev["label"] != label:
                out[n.id] = {"label": "conflict", "flaw": "multi"}
            else:
                out[n.id] = {"label": label, "flaw": f["type"]}
    return {k: v for k, v in out.items() if v["label"] != "conflict"}


# ---------------------------------------------------------------------------
# 합성 덱
# ---------------------------------------------------------------------------

def synth_rows(deck_dir, seed: int) -> list[dict]:
    did = deck_dir.name
    deck, script, flaws = jload(deck_dir / "deck.json"), jload(deck_dir / "script.json"), jload(deck_dir / "flaws.json")
    graph = ConceptGraph.from_dict(jload(deck_dir / "graph.json"))
    sd = SlideDoc.from_dict(jload(deck_dir / "slide_doc.json"))
    rng = random.Random(f"{seed}:{did}")
    n = len(deck["slides"])
    punct = rng.random() < 0.7
    filler = 0.15 if "긴장" in deck["spec"].get("style", "") else 0.0
    clean = [(s["slide_no"], s["sentences"]) for s in script["slides"]]
    rows = []

    def emit(variant: str, slides, cons: dict, only: set | None):
        tr = transcript_from(slides, punct=punct, rng=random.Random(f"{did}:{variant}"), filler=filler)
        jdump(deck_dir / f"transcript_{variant}.json", tr.to_dict())
        for it in build_items(graph, tr, sd):
            if only is not None and it["node_id"] not in only:
                continue
            rows.append({"uid": f"{did}:{variant}:{it['node_id']}", "source": "ko_synth", "group": did,
                         "rec": f"{did}:{variant}", "variant": variant, "lang": "ko", "item": it,
                         "cons": cons.get(it["node_id"])})

    emit("clean", clean, {}, None)
    flawed, applied = apply_flaws(script, flaws, n, rng)
    cons = cons_synth(graph, applied)
    hit_slides = {f["slide_no"] for f in applied}
    only = {nd.id for nd in graph.nodes if set(nd.slide_nos) & hit_slides} | set(cons)
    emit("flawed", flawed, cons, only)
    # drop: 가운데 장들에서 문장 25% 를 무작위로 뺀다 — 라벨은 큰 LLM 둘이 맞춰야만 쓴다(구성 라벨 없음)
    drop, dropped_slides = [], set()
    for no, ss in clean:
        if 1 < no < n and ss:
            keep = [s for s in ss if rng.random() > 0.25]
            if len(keep) < len(ss):
                dropped_slides.add(no)
            drop.append((no, keep or ss[:1]))
        else:
            drop.append((no, ss))
    only = {nd.id for nd in graph.nodes if set(nd.slide_nos) & dropped_slides}
    emit("drop", drop, {}, only)
    return rows


# ---------------------------------------------------------------------------
# 시험셋 녹음
# ---------------------------------------------------------------------------

def real_rows() -> list[dict]:
    base = DATA / "ko_real"
    rows = []
    for rec in jload(base / "recs.json"):
        deck = rec["deck"]
        graph = ConceptGraph.from_dict(jload(base / deck / "graph.json"))
        sd = SlideDoc.from_dict(jload(base / deck / "slide_doc.json"))
        tr = Transcript.from_dict(jload(__import__("pathlib").Path(rec["transcript"])))
        cons: dict[str, dict] = {}
        for p in rec.get("planted", []):
            kind = p.get("kind", "")
            if kind in ("contradiction_number", "contradiction_direction", "contradiction"):
                text = p.get("deck_quote") or " ".join(p.get("keys", [])) or p.get("deck_value", "")
                # 시험 정답은 엄격하게 — 어긋난 문장의 주인 개념 하나만(제품 node_for 와 같은 뜻). 문장 속 다른 개념은 큰 LLM 둘이 정한다
                for nd in nodes_for_line(graph, p["slide"], text, min_score=0.6, near=1.0)[:1]:
                    cons[nd.id] = {"label": "contradiction", "flaw": p.get("id", kind)}
            elif kind == "skipped_slide":
                for nd in graph.nodes:
                    if nd.slide_nos and set(nd.slide_nos) <= {p["slide"]}:
                        cons.setdefault(nd.id, {"label": "missing", "flaw": p.get("id", kind)})
            elif kind == "missing":
                for nd in nodes_for_line(graph, p["slide"], " ".join(p.get("keys", [])), min_score=0.6):
                    cons.setdefault(nd.id, {"label": "missing", "flaw": p.get("note", kind)})
        for it in build_items(graph, tr, sd):
            rows.append({"uid": f"{rec['rec_id']}:{it['node_id']}", "source": "ko_real", "group": deck,
                         "rec": rec["rec_id"], "variant": rec["kind"], "lang": "ko", "item": it,
                         "cons": cons.get(it["node_id"])})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", choices=["synth", "real"], required=True)
    ap.add_argument("--seed", type=int, default=16)
    args = ap.parse_args()
    if args.what == "real":
        rows = real_rows()
        write_jsonl(DATA / "items_ko_real.jsonl", rows)
    else:
        rows = []
        for d in sorted((DATA / "ko_synth").iterdir()):
            if (d / "graph.json").exists():
                rows += synth_rows(d, args.seed)
        write_jsonl(DATA / "items_ko_synth.jsonl", rows)
    from collections import Counter
    print(len(rows), Counter(r["variant"] for r in rows),
          Counter((r["cons"] or {}).get("label", "-") for r in rows))


if __name__ == "__main__":
    main()
