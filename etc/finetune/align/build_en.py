"""
영어 M3AV 실 강의 항목 — 파일럿 silver(A.X 가 같은 항목을 두 번 판정해 같았던 것)를 제품 항목 그림으로 다시 만든다.

파일럿 silver 줄에는 근거 문장(sid)이 남아 있지 않아(label_rest.py 가 저장하지 않았다) Solar 로 한 번 더 판정해
① 근거 sid · 한국어 note 를 얻고 ② A.X 라벨과 **다른 모델끼리** 맞는지 본다. 같을 때만 쓴다(label_set.py 가 한다).

파일럿 폴더는 읽기만 한다 — label_rest.py 가 아직 쓰고 있다. 실행할 때의 줄까지만 쓴다.
발표(talk) 단위로 train/dev/test 를 가른다(같은 발표가 두 쪽에 들어가지 않게).

산출: DATA/items_en.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import random
from collections import Counter, defaultdict

from common import M3AV, PILOT, jload, read_jsonl, write_jsonl, DATA

from pipeline._align_lora import build_items
from pipeline.contracts import ConceptGraph, Slide, SlideBlock, SlideDoc, Transcript


def build_slides(talk: str, segs: list[dict]) -> SlideDoc:
    """파일럿 build_items.build_slides 와 같다 — M3AV 화면 구간 하나 = 장 하나, OCR 첫 줄 = 제목."""
    slides = []
    for i, seg in enumerate(segs, 1):
        raw = (seg.get("ocr_text") or "").strip()
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        slides.append(Slide(slide_no=i, title=lines[0][:180] if lines else "",
                            blocks=[SlideBlock("paragraph", raw)] if raw else [],
                            categories=["paragraph"] if raw else [], total_char_count=len(raw),
                            line_count=len(lines), has_visual=False, text_sparse=len(raw) < 20, image_only=False))
    return SlideDoc(file_name=talk, total_slides=len(slides), slides=slides)


def transcript_of(segs: list[dict]) -> Transcript:
    by = []
    for i, seg in enumerate(segs, 1):
        text = " ".join((seg.get("speech_text") or "").split())
        by.append({"slide_no": i, "visit": 1, "start_sec": float(seg.get("start") or 0),
                   "end_sec": float(seg.get("end") or 0), "text": text, "words": []})
    return Transcript.from_dict({"full_text": " ".join(b["text"] for b in by), "by_slide": by, "words": [],
                                 "provider": "m3av", "duration_sec": max([b["end_sec"] for b in by] or [0])})


def split_of(talk: str) -> str:
    h = int(hashlib.sha1(talk.encode()).hexdigest(), 16) % 20
    return "test" if h < 2 else "dev" if h < 3 else "train"


def silver_rows() -> list[dict]:
    rows = read_jsonl(PILOT / "silver.jsonl")
    for f in sorted((PILOT / "talks").glob("*/silver.jsonl")):
        try:
            rows += read_jsonl(f)
        except Exception:  # noqa: BLE001 — 쓰는 중인 마지막 줄
            pass
    seen, out = set(), []
    for r in rows:
        if r["item_id"] not in seen and r.get("label") in ("aligned", "missing", "justified_skip", "contradiction"):
            seen.add(r["item_id"])
            out.append(r)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aligned", type=int, default=1300)
    ap.add_argument("--per_talk_aligned", type=int, default=8)
    ap.add_argument("--seed", type=int, default=16)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    silver = silver_rows()
    by_talk: dict[str, list[dict]] = defaultdict(list)
    for r in silver:
        by_talk[r["talk_id"]].append(r)
    # aligned 는 발표마다 최대 per_talk 개 — 큰 강의 몇 개가 판을 먹지 않게
    keep = []
    aligned_pool = []
    for talk, rs in by_talk.items():
        al = [r for r in rs if r["label"] == "aligned"]
        rng.shuffle(al)
        aligned_pool += al[: args.per_talk_aligned]
        keep += [r for r in rs if r["label"] != "aligned"]
    rng.shuffle(aligned_pool)
    keep += aligned_pool[: args.aligned]
    want: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in keep:
        node_id = r["item_id"][len(r["talk_id"]) + 1:]
        want[r["talk_id"]][node_id] = r

    out = []
    for talk, nodes in sorted(want.items()):
        gpath = PILOT / "talks" / talk / "graph.json"
        seg_path = M3AV / talk / "ocr/seg_speech_ocr.json"
        if not gpath.exists() or not seg_path.exists():
            continue
        segs = jload(seg_path)
        graph = ConceptGraph.from_dict(jload(gpath))
        sd = build_slides(talk, segs)
        tr = transcript_of(segs)
        for it in build_items(graph, tr, sd):
            r = nodes.get(it["node_id"])
            if r is None or not it["slide_nos"]:
                continue
            out.append({"uid": f"en:{talk}:{it['node_id']}", "source": "en_m3av", "group": talk, "split": split_of(talk),
                        "variant": "real", "lang": "en", "item": it, "cons": None,
                        "ax": {"label": r["label"], "partial": r.get("partial"), "asr": r.get("asr_suspect"),
                               "reason": r.get("reason", "")}})
    write_jsonl(DATA / "items_en.jsonl", out)
    print(len(silver), "silver ->", len(out), Counter(r["ax"]["label"] for r in out), Counter(r["split"] for r in out))


if __name__ == "__main__":
    main()
