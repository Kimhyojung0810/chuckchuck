"""
학습 세트 보강 — 정답이 「구성으로」 정해지는 어려운 반례를 코드로 만든다(학습 세트에서만, 시험 세트에는 넣지 않는다).

  num_flip  : aligned 항목의 근거 문장에서 **자료에도 있는 수치**(단위 붙은 수)를 다른 값으로 바꾼다 → contradiction(같은 sid)
  dir_flip  : 근거 문장의 방향 낱말(늘었·줄었, 높·낮, 증가·감소, 상승·하락 / increase·decrease …)을 뒤집는다 → contradiction
              (자료 글에 원래 방향 낱말이 있을 때만 — 자료가 말하지 않는 방향을 뒤집으면 모순인지 알 수 없다)
  drop_claim: 주장·핵심 주장 개념의 aligned 항목에서 개념 낱말을 담은 문장을 이 장·앞뒤 장에서 전부 지운다 → missing
              (지운 뒤에도 개념 이름 낱말이 남아 있으면 만들지 않는다)

산출: DATA/sets/train_aug.jsonl (assemble 뒤에 돌린다) — train_lora 는 --aug 로 섞는다.
"""

from __future__ import annotations

import copy
import random
import re
from collections import Counter

from common import DATA, read_jsonl, write_jsonl

from pipeline._align_lora import _toks

NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)(\s?)(%p|%|퍼센트|배|명|원|만 원|억 원|점|분|시간|일|개|건|곳|회|kWh|ppm|mg|kg|km|도|°C|percent|times|participants|users|ms|s\b)")
DIRS_KO = [("늘었", "줄었"), ("늘어", "줄어"), ("높았", "낮았"), ("높아", "낮아"), ("높습", "낮습"), ("높은", "낮은"),
           ("증가", "감소"), ("상승", "하락"), ("많았", "적었"), ("많아", "적어"), ("빨랐", "느렸"), ("빨라", "느려"),
           ("개선", "악화"), ("올랐", "떨어졌")]
DIRS_EN = [("increase", "decrease"), ("increased", "decreased"), ("higher", "lower"), ("more", "less"),
           ("improved", "worsened"), ("faster", "slower"), ("better", "worse")]


def _swap_dir(text: str, pairs) -> tuple[str, str] | None:
    for a, b in pairs:
        for x, y in ((a, b), (b, a)):
            if re.search(rf"(?<![A-Za-z가-힣]){re.escape(x)}" if x.isascii() else re.escape(x), text):
                return re.sub(rf"\b{re.escape(x)}\b" if x.isascii() else re.escape(x), y, text, count=1), x
    return None


def _new_num(v: str, rng: random.Random) -> str:
    x = float(v.replace(",", ""))
    if x == 0:
        return "5"
    f = rng.choice([0.5, 0.6, 1.5, 2.0, 0.7, 1.3])
    y = x * f
    if abs(y - x) < 1:
        y = x + rng.choice([2, 3, 5])
    return f"{y:.1f}".rstrip("0").rstrip(".") if "." in v else f"{round(y):,}" if "," in v else str(round(y))


def _replace_sentence(item: dict, sid: str, text: str) -> dict:
    it = copy.deepcopy(item)
    for part in ("own", "prev", "next"):
        for r in it.get(part, []):
            if r.get("sid") == sid:
                r["text"] = text
    return it


def slide_text(item: dict) -> str:
    return " ".join([item.get("summary", ""), *item.get("evidence", []), *(s["text"] for s in item.get("slides", []))])


def num_flip(row: dict, rng: random.Random) -> dict | None:
    it, sid = row["item"], row["sid"]
    sent = next((r["text"] for p in ("own", "prev", "next") for r in it.get(p, []) if r.get("sid") == sid), "")
    deck = slide_text(it)
    for m in NUM_RE.finditer(sent):
        val = m.group(1)
        if val in deck:
            new = _new_num(val, rng)
            if new == val:
                continue
            text = sent[: m.start(1)] + new + sent[m.end(1):]
            return {**row, "uid": row["uid"] + ":num", "item": _replace_sentence(it, sid, text), "verdict": "contradiction",
                    "note": f"발표에서는 {new}{m.group(3)}라고 했는데 자료는 {val}{m.group(3)}예요" if row["lang"] == "ko"
                    else f"발표의 {new} 은 자료의 {val} 과 달라요", "basis": "aug_num"}
    return None


def dir_flip(row: dict, rng: random.Random) -> dict | None:
    it, sid = row["item"], row["sid"]
    sent = next((r["text"] for p in ("own", "prev", "next") for r in it.get(p, []) if r.get("sid") == sid), "")
    pairs = DIRS_KO if row["lang"] == "ko" else DIRS_EN
    got = _swap_dir(sent, pairs)
    if not got:
        return None
    text, orig = got
    if orig not in slide_text(it):
        return None
    return {**row, "uid": row["uid"] + ":dir", "item": _replace_sentence(it, sid, text), "verdict": "contradiction",
            "note": "발표에서 말한 방향이 자료와 반대예요", "basis": "aug_dir"}


def drop_claim(row: dict, rng: random.Random) -> dict | None:
    it = row["item"]
    if it.get("kind") not in ("claim", "thesis"):
        return None
    name = {t for t in _toks(it["label"]) if len(t) >= 2}
    if len(name) < 2:
        return None
    new = copy.deepcopy(it)
    removed = 0
    for part in ("own", "prev", "next"):
        keep = []
        for r in new.get(part, []):
            if r.get("sid") and len(_toks(r["text"]) & name) >= max(1, len(name) // 2):
                removed += 1
                continue
            keep.append(r)
        new[part] = keep
    if not removed or not new["own"]:
        return None
    left = " ".join(r["text"] for p in ("own", "prev", "next") for r in new[p])
    if len(_toks(left) & name) >= max(1, len(name) // 2):
        return None
    return {**row, "uid": row["uid"] + ":drop", "item": new, "verdict": "missing", "sid": None,
            "note": "이 주장을 말한 문장이 없어요", "basis": "aug_drop"}


def main() -> None:
    rng = random.Random(16)
    train = read_jsonl(DATA / "sets" / "train.jsonl")
    out = []
    for r in train:
        if r["verdict"] != "aligned" or not r.get("sid"):
            continue
        for fn, p in ((num_flip, 0.6), (dir_flip, 0.6), (drop_claim, 0.35)):
            if rng.random() > p:
                continue
            got = fn(r, rng)
            if got:
                out.append(got)
                break
    write_jsonl(DATA / "sets" / "train_aug.jsonl", out)
    print(len(out), Counter(r["basis"] for r in out), Counter((r["lang"], r["verdict"]) for r in out))


if __name__ == "__main__":
    main()
