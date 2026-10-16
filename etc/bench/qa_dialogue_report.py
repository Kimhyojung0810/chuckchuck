#!/usr/bin/env python3
"""
5단계 실험 판(qa_dialogue_bench.py) 집계 → 기준표 (실측 · 통과/미달 · 잡음 폭).

    python etc/bench/qa_dialogue_report.py --tags t1-solar4 --base j0-pro3 [--llm-judge exaone] [--md out.md]

- 판정: 모범답 → good · 자기 말 → 통과 · 외운 답 판별(1~3단계 정의 그대로) · 엉뚱 → wrong · 함정 동의 → wrong · 모름 → 코칭
- 꼬리질문: 앞 답 구절 인용 · 인용에서 나온 질문 · 다른 답 → 다른 꼬리질문 · 세션 중복 · 반응 3-gram 겹침 · 미시 확인 · 말투 검사 ·
  틀린 전제 짚음 · 빈 곳 겨냥(LLM 심판, 말하기에 안 쓴 모델) · 출처(llm/respeak/template/judge)
- 지연: judge_answer 전체 · 말하기 콜 · 다시 말하기 · 기준선(엔진 끔)과 짝지은 증가분
잡음 폭: 같은 조건 반복(--tags 에 rep 여럿)의 최대−최소.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "main"), str(ROOT / "etc"), str(ROOT)]

from pipeline.config import load_dotenv  # noqa: E402

load_dotenv()
from pipeline import _ai_calllog  # noqa: E402
from pipeline import f09_dialogue as DLG  # noqa: E402
from pipeline._json_text import extract_json_object  # noqa: E402

OUT = Path("/data/models/_runs/qa-dialogue")
DEIXIS_RE = re.compile(r"그\s*말|그렇다면|그게|그건|그 점|그 차이|그 조건|그 수치|그 근거|그 논리|그 생각|그 부분|그 연결|그 문장|그 편차|그 이유|그 의견|그 애매")

LJ_SYSTEM = """당신은 발표 Q&A 코칭 품질 심사관이다. 발표자의 답과, 그 답에 대한 심사위원의 반응 · 꼬리질문을 본다. 작성자는 가려져 있다.
- gap (true/false): 꼬리질문이 **이 답의 빈 곳**(이유를 건너뜀 · 흐린 말 · 자료와 어긋난 말 · 반대 의견의 근거 · 자료 문장만 옮김)을 겨냥한다.
  답과 상관없이 아무 답에나 할 수 있는 질문이면 false.
- micro (true/false): 꼬리질문이 숫자 하나 · 용어 정의 · 장 번호 같은 미시 확인을 묻는다.
- premise (true/false/null): 답에 자료와 어긋난 사실이 있으면, 반응이나 꼬리질문이 그 어긋남을 짚었나. 어긋남이 없으면 null.
- natural (1~5): 교수가 실제로 할 법한 자연스러운 한 마디인가.
먼저 짧게 근거를 생각하고, JSON 하나: {"reason": "…", "gap": true, "micro": false, "premise": null, "natural": 4}"""


def load(tag: str) -> list[dict]:
    """「태그」 또는 「태그@반복」(그 반복만 — 잡음 폭을 반복마다 잰다)."""
    if "@" in tag:
        base, rep = tag.split("@", 1)
        rows = [r for r in load(base) if str(r.get("rep", 0)) == rep]
        for r in rows:
            r["_tag"] = tag
        return rows
    rows = []
    for f in sorted((OUT / "runs" / tag).glob("*.jsonl")):
        rows += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows:
        r["_tag"] = tag
    return rows


def r3(x):
    return None if x is None else round(x, 3)


def _b(x) -> bool:
    """LLM 심판이 「"false"」 처럼 문자열로 준 참/거짓도 읽는다."""
    if isinstance(x, str):
        return x.strip().lower() in ("true", "1", "yes", "예")
    return bool(x)


def rate(xs):
    xs = [_b(x) for x in xs]
    return (sum(xs) / len(xs)) if xs else None


def judge_metrics(rows: list[dict]) -> dict:
    by_q = defaultdict(dict)
    for r in rows:
        by_q[(r["deck"], r["qid"], r.get("rep", 0))][r["kind"]] = r
    m: dict = {}
    m["gist_good"] = rate(r["verdict"] == "good" for r in rows if r["kind"] == "gist")
    m["own_pass"] = rate(bool(r.get("passed")) for r in rows if r["kind"] == "own")
    m["own_good"] = rate(r["verdict"] == "good" for r in rows if r["kind"] == "own")
    diff, diff_strict = [], []
    for q in by_q.values():
        g = q.get("gist")
        for k in ("memo", "recital"):
            x = q.get(k)
            if not g or not x or x.get("verdict") in (None, "error"):
                continue
            diff.append(x["verdict"] != g["verdict"] or (x.get("score") or 0) <= (g.get("score") or 0) - 15)
            diff_strict.append(not x.get("passed") and bool(g.get("passed")))
    m["memo_diff"] = rate(diff)
    m["memo_n"] = len(diff)
    m["memo_notpass_vs_gist_pass"] = rate(diff_strict)
    m["unrelated_wrong"] = rate(r["verdict"] == "wrong" for r in rows if r["kind"] == "unrelated")
    m["trap_agree_wrong"] = rate(r["verdict"] == "wrong" for r in rows if r["kind"] == "trap_agree")
    m["premise_notpass"] = rate(not r.get("passed") for r in rows if r["kind"] == "premise")
    m["unknown_coach"] = rate(bool(r.get("coach_stage")) for r in rows if r["kind"] == "unknown")
    m["partial_notgood"] = rate(r["verdict"] != "good" for r in rows if r["kind"] == "partial")
    m["vague_notpass"] = rate(not r.get("passed") for r in rows if r["kind"] == "vague")
    m["errors"] = sum(1 for r in rows if r.get("verdict") == "error")
    return m


def _ti(r: dict) -> DLG.TalkInput:
    return DLG.TalkInput(question=r["question"], label="", answer=r["answer"], gist=r.get("gist") or "")


def dialogue_rows(rows: list[dict]) -> list[dict]:
    """꼬리질문이 나간 판정 (닫히지 않음 · 코칭 경로 아님 · 오류 아님)."""
    return [r for r in rows if r.get("followup") and not r.get("coach_stage") and r.get("verdict") != "error"]


def dialogue_metrics(rows: list[dict], lj: dict | None = None) -> dict:
    d = dialogue_rows(rows)
    m: dict = {"n_followup": len(d)}
    if not d:
        return m
    quoted = [bool(DLG.quoted_anchor(r.get("react") or "", r["answer"])) for r in d]
    linked = []
    for r, q in zip(d, quoted):
        anc = DLG.quoted_anchor(r.get("react") or "", r["answer"]) or (r.get("anchor") or "")
        words = [w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", anc)]
        f = r.get("followup") or ""
        linked.append(q and (any(w[:2] in f for w in words) or bool(DEIXIS_RE.search(f))))
    m["quote"] = rate(quoted)
    m["quote_linked"] = rate(linked)
    # 다른 답 → 다른 꼬리질문 (같은 질문 · 같은 반복 안에서 답 유형 짝)
    groups = defaultdict(list)
    for r in d:
        groups[(r["_tag"], r["deck"], r["qid"], r.get("rep", 0))].append(r["followup"])
    pairs = [DLG.similar(a, b) < DLG.REPEAT_SIM for fs in groups.values() for i, a in enumerate(fs) for b in fs[i + 1:]]
    m["diff_followup"] = rate(pairs)
    m["diff_pairs"] = len(pairs)
    # 세션(덱 × 반복) 안 완전 중복 · 반응 3-gram 겹침
    sess = defaultdict(list)
    for r in rows:
        if r.get("react") and r.get("verdict") != "error":
            sess[(r["_tag"], r["deck"], r.get("rep", 0))].append(r)
    dup, overlaps = 0, []
    for rs in sess.values():
        texts = [x["react"] for x in rs] + [x["followup"] for x in rs if x.get("followup")]
        dup += len(texts) - len(set(texts))
        grams = [set(_w3(x["react"])) for x in rs]
        for i, g in enumerate(grams):
            if not g:
                continue
            other = set().union(*(h for j, h in enumerate(grams) if j != i)) if len(grams) > 1 else set()
            overlaps.append(len(g & other) / len(g))
    m["session_dup"] = dup
    m["react_3gram_overlap"] = st.mean(overlaps) if overlaps else None
    # 실제 한 판 크기(질문 5개 × 두 턴 ≈ 반응 10개)로 덱 안에서 무작위로 묶어 본 겹침 — 덱 전체(≈50턴)는 실제 판보다 훨씬 길다
    import random  # noqa: PLC0415
    rng, sims = random.Random(17), []
    for rs in sess.values():
        grams_all = [set(_w3(x["react"])) for x in rs]
        for _ in range(40):
            pick = rng.sample(grams_all, min(10, len(grams_all)))
            for i, g in enumerate(pick):
                if g:
                    other = set().union(*(h for j, h in enumerate(pick) if j != i))
                    sims.append(len(g & other) / len(g))
    m["react_3gram_overlap_s10"] = st.mean(sims) if sims else None
    # 미시 · 말투 검사 (최종 문장)
    m["micro_regex"] = rate(bool(DLG._MICRO_RE.search(r["followup"])) for r in d)
    style = [not [p for p in DLG.check_turn(r["react"], r["followup"], _ti(r))
                  if p in ("not_haeyo", "honorific", "sentence_long", "too_many_sentences", "praise", "ask_form", "placeholder")]
             for r in d]
    m["style_pass"] = rate(style)
    m["premise_challenge"] = rate((r.get("move") == "challenge") for r in rows if r["kind"] == "premise" and not r.get("coach_stage")
                                  and r.get("verdict") != "error")
    src = Counter(((r.get("dialogue") or {}).get("source") or "none") for r in rows if r.get("verdict") != "error"
                  and not r.get("coach_stage"))
    m["source"] = dict(src)
    tot = sum(src.values()) or 1
    m["fixed_fallback"] = (src.get("judge", 0) + src.get("none", 0)) / tot
    m["template_rate"] = src.get("template", 0) / tot
    m["moves"] = dict(Counter(r.get("move") or "" for r in d))
    if lj:
        js = [lj.get(_key(r)) for r in d]
        js = [j for j in js if j]
        m["lj_n"] = len(js)
        m["lj_gap"] = rate(j.get("gap") for j in js)
        m["lj_micro"] = rate(j.get("micro") for j in js)
        prem = [j.get("premise") for j, r in zip([lj.get(_key(r)) for r in d], d) if j and r["kind"] == "premise"]
        prem = [p for p in prem if p is not None and str(p).lower() not in ("null", "none", "")]
        m["lj_premise"] = rate(prem)
        m["lj_natural"] = st.mean([float(j.get("natural") or 0) for j in js]) if js else None
    return m


_COACH_TAIL_RE = re.compile(r"\s*자료(?:\s*\d+장)?[은는]\s*이렇게 말해요:\s*«.*?»\s*$")


def _w3(t: str) -> list[str]:
    # 화면이 보이는 글만 — 「모르겠어요」 1단의 자료 인용 꼬리는 화면이 떼고 카드로 그린다(qa_live coachReactText)
    t = _COACH_TAIL_RE.sub("", t or "")
    w = re.findall(r"[가-힣A-Za-z0-9]+", re.sub(r"「[^」]*」", " ", t))
    return [" ".join(w[i:i + 3]) for i in range(len(w) - 2)]


def _key(r: dict) -> str:
    return hashlib.sha1(f"{r['answer']}|{r.get('react')}|{r.get('followup')}".encode()).hexdigest()[:16]


def latency(rows: list[dict], base: list[dict] | None) -> dict:
    ok = [r for r in rows if r.get("verdict") != "error" and not r.get("coach_stage")]
    secs = sorted(r["sec"] for r in ok if r.get("sec") is not None)
    talk = sorted(((r.get("dialogue") or {}).get("talk_sec") or 0) for r in ok if (r.get("dialogue") or {}).get("talk_sec"))
    resp = [r for r in ok if (r.get("dialogue") or {}).get("respeak_sec") is not None]
    m = {"n": len(secs), "p50": _p(secs, .5), "p90": _p(secs, .9), "p95": _p(secs, .95),
         "talk_p50": _p(talk, .5), "talk_p95": _p(talk, .95), "respeak_rate": len(resp) / len(ok) if ok else None}
    if base:
        bmap = {(b["deck"], b["qid"], b["kind"]): b["sec"] for b in base if b.get("sec") is not None and not b.get("coach_stage")}
        deltas = sorted(r["sec"] - bmap[(r["deck"], r["qid"], r["kind"])] for r in ok if (r["deck"], r["qid"], r["kind"]) in bmap)
        bs = sorted(bmap.values())
        m.update(base_p50=_p(bs, .5), base_p95=_p(bs, .95), delta_p50=_p(deltas, .5), delta_p90=_p(deltas, .9))
    return m


def _p(xs, q):
    if not xs:
        return None
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 2)


def llm_judge(rows: list[dict], model: str, cache_path: Path) -> dict:
    from pipeline.providers.llm_impl import get_llm
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    todo = [r for r in dialogue_rows(rows) if _key(r) not in cache]
    llm = get_llm(model)

    def one(r):
        user = (f"질문: {r['question']}\n모범답(참고): {r.get('gist') or ''}\n발표자의 답: {r['answer']}\n"
                f"반응: {r.get('react')}\n꼬리질문: {r.get('followup')}")
        with _ai_calllog.feature_scope("F-09-bench"):
            for _ in range(3):
                try:
                    return _key(r), extract_json_object(llm.complete(system=LJ_SYSTEM, user=user, temperature=0.0,
                                                                     max_tokens=500, json_mode=True))
                except Exception:  # noqa: BLE001
                    continue
        return _key(r), None

    with ThreadPoolExecutor(6) as ex:
        for k, v in ex.map(_ai_calllog.carry(one, "F-09-bench"), todo):
            if v:
                cache[k] = v
    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return cache


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", required=True, help="쉼표로 — 같은 조건의 반복이면 잡음 폭을 낸다")
    ap.add_argument("--base", default="")
    ap.add_argument("--llm-judge", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    tags = [t for t in args.tags.split(",") if t]
    base = load(args.base) if args.base else None
    out = {}
    lj = None
    if args.llm_judge:
        allrows = [r for t in tags for r in load(t)]
        lj = llm_judge(allrows, args.llm_judge, OUT / "labels" / f"lj_{args.llm_judge}.json")
    for t in tags:
        rows = load(t)
        out[t] = {"judge": judge_metrics(rows), "dialogue": dialogue_metrics(rows, lj), "latency": latency(rows, base),
                  "n": len(rows)}
    if base:
        out["_base:" + args.base] = {"judge": judge_metrics(base), "dialogue": dialogue_metrics(base), "latency": latency(base, None)}
    txt = json.dumps(out, ensure_ascii=False, indent=1, default=r3)
    print(txt)
    if args.json:
        Path(args.json).write_text(txt, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
