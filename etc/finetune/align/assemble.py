"""
라벨 붙은 항목을 학습·시험 세트로 묶는다 — 정답을 정하는 규칙이 여기 한 곳에 있다.

정답 규칙
  구성 라벨(cons — 일부러 심은 모순·누락·건너뛰기)이 있으면: Solar·A.X 중 **하나 이상이 같은 라벨**일 때만 그 라벨.
      둘 다 다르면 버린다(심은 결함이 그 개념에 안 걸렸을 수 있다 — 예: 모순 문장 속 다른 개념).
  구성 라벨이 없으면: Solar == A.X 일 때만(unsure 제외). 갈리면 버린다.
      단 한쪽은 missing·한쪽은 justified_skip 이면(둘 다 「안 말했다」 는 같다) 제품 규칙(skip_rule)으로 가른다.
  aligned·contradiction 은 근거 문장 번호(sid)가 이 항목 발화 안에 있어야 한다(라벨러가 맞춘 쪽의 sid, Solar 먼저).
  영어(M3AV): 파일럿 A.X(B v1 프롬프트, 두 번 같음) 라벨은 참고만 — 새 프롬프트의 Solar·A.X 가 맞을 때만.

나누기 — 덱·발표 단위(같은 덱이 두 쪽에 들어가지 않는다)
  ko_synth : 덱 해시로 train 80% · dev 8% · test 12%
  en_m3av  : 발표 해시(build_en.split_of)
  ko_real  : 전부 test(학습에 절대 안 쓴다)

산출: DATA/sets/{train,dev,test_ko_synth,test_ko_real,test_en}.jsonl · DATA/sets/card.json
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict

from common import DATA, jdump, read_jsonl, write_jsonl

from pipeline._align_lora import item_sentences

LABELS = ("aligned", "justified_skip", "missing", "contradiction")


def synth_split(group: str) -> str:
    h = int(hashlib.sha1(("ko:" + group).encode()).hexdigest(), 16) % 100
    return "test" if h < 12 else "dev" if h < 20 else "train"


#: 제품 F-11 의 생략 가드와 같은 값 — 자료가 힘준 개념(weight ≥ 0.35)은 말하지 않았으면 「정당한 생략」 이 아니다.
SKIP_GUARD_WEIGHT = 0.35


def skip_rule(item: dict) -> str:
    """말하지 않은 개념의 missing/justified_skip — ① 그 장에서 「넘어갈게요·나중에」 로 넘겼으면 missing(제품 _apply_skips)
    ② 주장·핵심 주장이거나 자료 중요도가 가드 이상이면 missing(제품 SKIP_GUARD_WEIGHT) ③ 나머지는 justified_skip."""
    from pipeline._spoken import defer_cue, skip_cue

    if any(skip_cue(r["text"]) or defer_cue(r["text"]) for r in item.get("own", []) if r.get("sid")):
        return "missing"
    if item.get("kind") in ("claim", "thesis") or float(item.get("weight") or 0) >= SKIP_GUARD_WEIGHT:
        return "missing"
    return "justified_skip"


def decide(row: dict) -> tuple[str | None, str | None, str, str]:
    """(verdict, sid, note, basis) — verdict None 이면 버린다. basis 는 정답이 어디서 왔는지."""
    labs = row.get("labels", {})
    s, a = labs.get("solar", {}), labs.get("ax", {})
    sl, al = s.get("label"), a.get("label")
    cons = (row.get("cons") or {}).get("label")
    if cons:
        agree = [x for x in (s, a) if x.get("label") == cons]
        if not agree:
            return None, None, "", "cons_rejected"
        verdict, src, basis = cons, agree[0], "cons+llm"
    elif sl and al and {sl, al} == {"justified_skip", "missing"}:
        # 두 라벨러의 생략 문턱이 다르다(10/16 실측: A.X 는 justified_skip 을 거의 안 쓰고, Solar 는 「넘어갈게요」 장도 생략으로 본다).
        # 둘 다 「말하지 않았다」 에는 동의한다 — 어느 쪽인지는 제품 규칙으로 가른다(skip_rule).
        verdict, basis = skip_rule(row["item"]), "skip_rule"
        src = s if sl == verdict else a
    else:
        if not sl or sl != al or sl not in LABELS:
            return None, None, "", "llm_disagree" if sl and al else "llm_missing"
        verdict, src, basis = sl, s, "solar=ax"
    sid = None
    if verdict in ("aligned", "contradiction"):
        sents = item_sentences(row["item"])
        for cand in ((src, s, a) if cons else (s, a)):
            if cand.get("label") == verdict and cand.get("sid") in sents:
                sid = cand["sid"]
                break
        if sid is None:
            return None, None, "", "no_valid_sid"
    note = (src.get("note") or s.get("note") or "").strip()
    return verdict, sid, note, basis


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--suffix", default=".labels.jsonl", help="라벨 파일 꼬리(중간 결과 스냅숏은 .snap.jsonl)")
    ap.add_argument("--out_dir", default=str(DATA / "sets"))
    args = ap.parse_args()
    from pathlib import Path
    out_dir = Path(args.out_dir)
    sets: dict[str, list[dict]] = defaultdict(list)
    stats: dict[str, Counter] = defaultdict(Counter)
    for name in ("items_ko_synth_sel", "items_en_sel", "items_ko_real"):
        rows = read_jsonl(DATA / f"{name}{args.suffix}")
        for r in rows:
            verdict, sid, note, basis = decide(r)
            src = r["source"]
            stats[src][basis] += 1
            if verdict is None:
                continue
            if src == "ko_real":
                split = "test_ko_real"
            elif src == "ko_synth":
                split = {"train": "train", "dev": "dev", "test": "test_ko_synth"}[synth_split(r["group"])]
            else:
                split = {"train": "train", "dev": "dev", "test": "test_en"}[r["split"]]
            sets[split].append({"uid": r["uid"], "source": src, "group": r["group"], "lang": r["lang"],
                                "variant": r.get("variant"), "rec": r.get("rec"), "item": r["item"],
                                "verdict": verdict, "sid": sid, "note": note, "basis": basis,
                                "cons": r.get("cons"),
                                "labels": {k: {"label": v.get("label"), "sid": v.get("sid")}
                                           for k, v in r.get("labels", {}).items()}})
    card = {"decisions": {k: dict(v) for k, v in stats.items()}, "sets": {}}
    for split, rows in sets.items():
        write_jsonl(out_dir / f"{split}.jsonl", rows)
        card["sets"][split] = {
            "n": len(rows),
            "by_verdict": dict(Counter(r["verdict"] for r in rows)),
            "by_source": dict(Counter(r["source"] for r in rows)),
            "by_lang_verdict": {lang: dict(Counter(r["verdict"] for r in rows if r["lang"] == lang))
                                for lang in ("ko", "en")},
            "groups": len({r["group"] for r in rows}),
        }
    # 새는 곳 검사 — 같은 덱·발표가 두 세트에 있으면 멈춘다
    owner: dict[str, str] = {}
    for split, rows in sets.items():
        for r in rows:
            prev = owner.setdefault(r["group"], split)
            if prev != split and {prev, split} != {"test_ko_synth", "test_ko_synth"}:
                raise SystemExit(f"덱/발표가 두 세트에 있다: {r['group']} {prev} {split}")
    jdump(out_dir / "card.json", card)
    import json
    print(json.dumps(card, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
