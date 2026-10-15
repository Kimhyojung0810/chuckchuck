"""
AI Hub 「공적말하기 실습 및 평가 데이터」 언어적 라벨(JSON) → 습관 태거 학습용 JSONL.

호출: python etc/habits_lora/aihub.py --src <라벨 폴더나 zip들> --out /data/models/_runs/habits-lora/data
산출: <out>/{unified,REP,FIL}/{train,val,test}.jsonl · <out>/split.json · <out>/build_report.json

만드는 방식 (옛 docs/DATA_PIPELINE.md §2 를 그대로 따른다):
  · 입력 = script.script_stt_txt (발화 STT 전문), 정답 = taglist 의 (tag_type, tag_keyword) 를 줄 목록으로
    — 인라인 태그 전문(script_tag_txt) 을 베끼게 하지 않는다. PS(휴지, tag_type 3) 는 본문에 앵커가 없어 뺀다.
  · tag_type: 1=FIL 2=REP 3=PS 4=WR
  · 원고(presentation.presen_script) SHA1 로 묶어 나눈다 — 같은 원고를 여러 사람이 읽어서, 무작위로 나누면 누수.
    seed 42 로 원고 묶음을 섞어 80/10/10. 원래 분할(train 513 / val 65 / test 62)과 똑같이 하려면
    팀의 split 목록을 --split-file 로 넘긴다 ({"train":[id…],"val":[…],"test":[…]}, id 는 파일 이름 줄기).
  · unified = REP·FIL·WR 를 그 순서로 (서비스 REP 태거가 이것으로 학습됐다), REP·FIL = 태그 하나씩.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import zipfile
from collections import Counter
from pathlib import Path

TAG_TYPES = {1: "FIL", 2: "REP", 3: "PS", 4: "WR"}
TASK_TAGS = {"unified": ("REP", "FIL", "WR"), "REP": ("REP",), "FIL": ("FIL",)}


def _find(d, key: str):
    """중첩 dict/list 에서 key 를 처음 만나는 값 (라벨 JSON 의 감싸는 층이 판마다 달라도 되게)."""
    if isinstance(d, dict):
        if key in d:
            return d[key]
        for v in d.values():
            hit = _find(v, key)
            if hit is not None:
                return hit
    elif isinstance(d, list):
        for v in d:
            hit = _find(v, key)
            if hit is not None:
                return hit
    return None


def _norm(t: str) -> str:
    return " ".join(str(t or "").split())


def parse_label(doc: dict, doc_id: str) -> dict | None:
    """라벨 JSON 하나 → {id, script_sha1, stt, tags:[(TAG, keyword)…]}. 필요한 칸이 없으면 None."""
    stt = _find(doc, "script_stt_txt")
    script = _find(doc, "presen_script")
    taglist = _find(doc, "taglist")
    if not stt or taglist is None:
        return None
    tags: list[tuple[str, str]] = []
    for t in taglist if isinstance(taglist, list) else []:
        try:
            kind = TAG_TYPES.get(int(t.get("tag_type")))
        except (TypeError, ValueError, AttributeError):
            continue
        kw = _norm(t.get("tag_keyword", ""))
        if kind and kind != "PS" and kw:
            tags.append((kind, kw))
    return {
        "id": doc_id,
        "script_sha1": hashlib.sha1(_norm(script or stt).encode("utf-8")).hexdigest(),
        "stt": _norm(stt),
        "tags": tags,
    }


def iter_label_files(src: Path):
    """폴더 안의 *.json 과 *.zip 속 *.json 을 (id, dict) 로."""
    paths = [src] if src.is_file() else sorted(src.rglob("*"))
    for p in paths:
        if p.suffix.lower() == ".json":
            try:
                yield p.stem, json.loads(p.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
        elif p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                for name in sorted(z.namelist()):
                    if name.lower().endswith(".json"):
                        try:
                            yield Path(name).stem, json.loads(z.read(name).decode("utf-8-sig"))
                        except (ValueError, UnicodeDecodeError):
                            continue


def target_text(tags: list[tuple[str, str]], order: tuple[str, ...]) -> str:
    lines = [f"{k}\t{kw}" for want in order for k, kw in tags if k == want]
    return "\n".join(lines) if lines else "NONE"


def split_groups(records: list[dict], seed: int = 42, ratios=(0.8, 0.1, 0.1)) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for r in records:
        groups.setdefault(r["script_sha1"], []).append(r["id"])
    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    n = len(keys)
    a, b = int(n * ratios[0]), int(n * (ratios[0] + ratios[1]))
    parts = {"train": keys[:a], "val": keys[a:b], "test": keys[b:]}
    return {k: sorted(i for g in v for i in groups[g]) for k, v in parts.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, type=Path, help="라벨 JSON 폴더 · zip · 둘 다 들어 있는 폴더")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--split-file", type=Path, help="팀의 원래 분할 {train:[id],val:[id],test:[id]}")
    ap.add_argument("--seed", type=int, default=42)
    ns = ap.parse_args(argv)

    records, skipped = [], 0
    for doc_id, doc in iter_label_files(ns.src):
        r = parse_label(doc, doc_id)
        if r is None:
            skipped += 1
        else:
            records.append(r)
    if not records:
        print(f"라벨을 하나도 못 읽었어요 ({ns.src}). script_stt_txt·taglist 가 있는 JSON 인지 보세요.", file=sys.stderr)
        return 1

    split = (json.loads(ns.split_file.read_text(encoding="utf-8")) if ns.split_file
             else split_groups(records, ns.seed))
    by_id = {r["id"]: r for r in records}
    ns.out.mkdir(parents=True, exist_ok=True)
    report = {"records": len(records), "skipped": skipped, "split": {}, "tags": {}}
    for task, order in TASK_TAGS.items():
        d = ns.out / task
        d.mkdir(exist_ok=True)
        for part, ids in split.items():
            rows = [by_id[i] for i in ids if i in by_id]
            with (d / f"{part}.jsonl").open("w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps({"id": r["id"], "script_sha1": r["script_sha1"], "task": task,
                                        "stt": r["stt"], "target": target_text(r["tags"], order)},
                                       ensure_ascii=False) + "\n")
            report["split"][part] = len(rows)
    report["tags"] = dict(Counter(k for r in records for k, _ in r["tags"]))
    (ns.out / "split.json").write_text(json.dumps(split, ensure_ascii=False, indent=1), encoding="utf-8")
    (ns.out / "build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
