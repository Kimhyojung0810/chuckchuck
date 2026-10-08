"""
질문 코치 벤치 채점 — LLM 없이 규칙으로만 잰다 (같은 LLM 이 자기 질문을 좋다고 하는 채점을 피한다).
규칙은 baseline 을 돌리기 전에 고정했다 (2026-10-02). 개선 결과에 맞춰 고치지 않는다 — README §규칙.

    .venv/bin/python labs/qcoach_bench/score.py baseline              # 한 태그 점수 + 기록표(records.md)
    .venv/bin/python labs/qcoach_bench/score.py baseline after        # 전후 비교표

지표는 넷만 쓴다 (2026-10-02 사용자 지시 — Priority 는 질문 선택의 변화를 못 보여 줘서 아래 둘로 바꿨다):
TopK       Top-K Coverage — 덱 원문으로 고른 핵심 개념 K1~K5(key_concepts.json) 중 첫 세션(A) 질문이 다룬 몫.
           질문 하나는 핵심 개념 **하나**로만 센다(대상 노드 이름에 걸리는 K 중 번호가 앞선 것) — 핵심 주장 하나가 K1·K3 둘로 세지지 않게.
Redundancy 같은 질문 목록에서 앞 질문과 겹치는 질문의 몫 (낮을수록 좋다) — 대상 노드가 같다 · 같은 K 다 ·
           대상 이름 내용어가 절반 이상 겹친다(Jaccard ≥ 0.5) 중 하나면 겹친 것.
Grounding  질문이 자료·그래프에 근거하는가 — 모든 세션의 모든 질문
           g_node 대상 노드가 그래프에 있음 · g_num 질문·모범답의 수가 전부 덱에 있음 · g_anchor 근거 장 본문의 내용어 2개 이상 ·
           g_target 질문이 대상 개념 이름을 부름 · g_vocab 덱에 없는 내용어 40% 이하 · g_quote 근거 인용이 그 장 원문 그대로
Adaptivity 사용자 상태에 따라 다음 질문이 맞게 바뀌는가 — 시나리오별 검사의 통과 비율, A~E 평균
"""
from __future__ import annotations

import json
import statistics as st
import sys

from common import FIX, FOLLOW_UPS, OUT, key_of, keys_of, load_keys, load_tag, misquoted_evidence
from textrules import found, numbers, squash, tokens

AXES = ("topk", "redundancy", "grounding", "adaptivity")
GROUND_CHECKS = ("g_node", "g_num", "g_anchor", "g_target", "g_vocab", "g_quote")
#: 덱에 없는 내용어가 이 몫을 넘으면 g_vocab 실패
FOREIGN_MAX = 0.4
#: 모범답 내용어가 이만큼 겹치면 쌍둥이 질문 (B 의 다음 질문 검사)
TWIN_MAX = 0.3
#: 대상 이름 내용어가 이만큼 겹치면 중복 질문 (Redundancy)
REDUNDANT_JACCARD = 0.5
#: 「모르겠어요」 코칭 단계의 높이 — 두 번째가 첫 번째보다 높아야 한다 (D)
STAGE_ORDER = {"narrow": 0, "scaffold": 1, "explain": 2}


class Deck:
    """얼린 덱 본문과 그래프 — 장별 글(공백 뺀 것) · 덱 전체 수치 · 노드 id."""

    def __init__(self):
        sd = json.loads((FIX / "slidedoc.json").read_text())
        g = json.loads((FIX / "graph.json").read_text())
        self.slides = {s["slide_no"]: s.get("raw_text") or "" for s in sd["slides"]}
        self.sq = {n: squash(t) for n, t in self.slides.items()}
        self.all_sq = "".join(self.sq.values())
        self.nums = set().union(*(numbers(t) for t in self.slides.values()))
        self.nodes = {n["id"] for n in g["nodes"]}

    def text_of(self, slide_nos) -> str:
        return "".join(self.sq.get(n, "") for n in slide_nos)


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------

def grounding(q: dict, deck: Deck) -> dict:
    """질문 하나의 근거 검사 여섯 개 + grounded(전부 통과). `_` 로 시작하는 칸은 기록표용 진단이다."""
    text = q.get("question") or ""
    cited = set(q.get("slide_nos") or []) | ({q["evidence_slide_no"]} if q.get("evidence_slide_no") else set())
    toks = list(dict.fromkeys(tokens(text)))
    anchored = [t for t in toks if found(t, deck.text_of(cited))]
    foreign = [t for t in toks if not found(t, deck.all_sq)]
    label_toks = tokens(q.get("label") or "") or [squash(q.get("label") or "")]
    quote = q.get("evidence_quote") or ""
    bad_nums = numbers(text + " " + (q.get("answer_gist") or "")) - deck.nums
    r = {
        "g_node": q.get("node_id") in deck.nodes,
        "g_num": not bad_nums,
        "g_anchor": len(anchored) >= 2,
        "g_target": any(found(t, squash(text)) for t in label_toks),
        "g_vocab": (len(foreign) / len(toks) if toks else 1.0) <= FOREIGN_MAX,
        "g_quote": (squash(quote) in deck.sq.get(q.get("evidence_slide_no") or 0, "")) if quote else True,
    }
    r["grounded"] = all(r.values())
    r["_foreign"] = foreign
    r["_bad_nums"] = sorted(bad_nums)
    return r


def followup_grounded(text: str, q1: dict, deck: Deck) -> bool:
    """되물음의 수가 덱에 있고, 첫 질문 근거 장(없으면 덱 전체)의 낱말을 하나 이상 부른다. 되물음이 없으면 통과."""
    if not text:
        return True
    cited_sq = deck.text_of(q1.get("slide_nos") or [])
    return numbers(text) <= deck.nums and any(found(t, cited_sq or deck.all_sq) for t in tokens(text))


def grounding_scores(rep: dict, deck: Deck) -> dict:
    qs = all_questions(rep)
    rows = [grounding(q, deck) for q in qs]
    g = {k: st.mean(float(x[k]) for x in rows) for k in (*GROUND_CHECKS, "grounded")}
    q1 = first_session(rep)[0]
    followups = [(rep["C"]["next"] or {}).get("followup") or "", rep["D"]["judgement"].get("followup") or ""]
    g["g_followup"] = st.mean(float(followup_grounded(f, q1, deck)) for f in followups)
    # 진단 (공식 점수 아님): 함정은 일부러 틀린 전제를 얹는 설계라 g_num 이 떨어진다 — 함정을 뺀 근거율과 함정 수를 따로 본다
    plain = [x for x, q in zip(rows, qs) if not q.get("trap")]
    g["diag_grounded_no_trap"] = st.mean(float(x["grounded"]) for x in plain) if plain else 0.0
    g["diag_traps_per_session"] = sum(bool(q.get("trap")) for q in qs) / (1 + len(FOLLOW_UPS))
    g["score"] = g["grounded"]
    return g


# ---------------------------------------------------------------------------
# Top-K Coverage · Redundancy
# ---------------------------------------------------------------------------

def topk_redundancy(qs: list[dict], keys: dict) -> tuple[dict, dict]:
    """첫 세션 질문 목록 → (Top-K Coverage, Redundancy)."""
    ks = [key_of(q["label"], keys) for q in qs]
    covered = {k for k in ks if k}
    toks = [set(tokens(q["label"])) for q in qs]

    def overlaps(i: int, j: int) -> bool:
        same_node = qs[i].get("node_id") and qs[i].get("node_id") == qs[j].get("node_id")
        same_key = ks[i] and ks[i] == ks[j]
        close = bool(toks[i] and toks[j]) and _jaccard(toks[i], toks[j]) >= REDUNDANT_JACCARD
        return bool(same_node or same_key or close)

    dup = sum(any(overlaps(i, j) for j in range(i)) for i in range(len(qs)))
    return ({"covered": len(covered), "score": len(covered) / len(keys["concepts"])},
            {"redundant": dup, "score": dup / len(qs) if qs else 0.0})


# ---------------------------------------------------------------------------
# Adaptivity — 시나리오마다 검사 몇 개
# ---------------------------------------------------------------------------

def _next_session(sc: dict) -> list[dict]:
    return sc["session2"]["questions"]


def _checks_a(q1: dict, keys: dict) -> dict:
    """A 아무것도 학습 안 함 — 첫 질문이 핵심 개념이고, 함정이 아니고, 하나만 묻는다."""
    return {"a1_q1_key": bool(keys_of(q1["label"], keys)), "a2_q1_not_trap": not q1.get("trap"),
            "a3_q1_single_ask": q1["question"].count("?") <= 1}


def _checks_b(B: dict, q1: dict) -> dict:
    """B 정답 — 통과해 닫히고, 다음 질문은 다른 개념(쌍둥이 아님), 다음 리허설은 다른 개념부터."""
    nxt = B["next"] or {}
    twin = _jaccard(set(tokens(nxt.get("answer_gist") or "")), set(tokens(q1.get("answer_gist") or ""))) >= TWIN_MAX
    return {"b1_passed": bool(B["judgement"]["passed"]), "b2_closed": bool(B["judgement"]["mastered"]),
            "b3_next_new": bool(nxt.get("node_id")) and nxt["node_id"] != q1["node_id"] and not twin,
            "b4_s2_moves_on": _next_session(B)[0]["node_id"] != q1["node_id"]}


def _checks_c(C: dict, q1: dict) -> dict:
    """C 오답 — 통과 못 하고, 원래 질문과 다른 되물음이 같은 개념에 머물고, 다음 리허설에 다시 먼저 묻는다."""
    followup = (C["next"] or {}).get("followup") or ""
    q1_toks = set(tokens(q1["label"] + " " + q1["question"] + " " + (q1.get("answer_gist") or "")))
    return {"c1_not_passed": not C["judgement"]["passed"],
            "c2_followup": bool(followup) and squash(followup) != squash(q1["question"]),
            "c3_same_concept": bool(set(tokens(followup)) & q1_toks),
            "c4_s2_retries": _next_session(C)[0]["node_id"] == q1["node_id"]}


def _checks_d(D: dict, q1: dict) -> dict:
    """D 모르겠어요 — 점수 없이 코칭하고, 더 좁게(보기 또는 더 짧게) 묻고, 두 번째엔 한 단계 위, 다음 리허설에 다시 먼저."""
    j1, j2 = D["judgement"], D["judgement2"]
    followup = j1.get("followup") or ""
    st1, st2 = j1.get("coach_stage") or "", j2.get("coach_stage") or ""
    return {"d1_coached": st1 in ("narrow", "scaffold") and not j1.get("score"),
            "d2_narrower": bool(j1.get("choices")) or (bool(followup) and len(followup) < len(q1["question"])),
            "d3_escalates": STAGE_ORDER.get(st2, -1) > STAGE_ORDER.get(st1, -1),
            "d4_s2_retries": _next_session(D)[0]["node_id"] == q1["node_id"]}


def _checks_e(E: dict, s1: list[dict], keys: dict) -> dict:
    """E 이미 이해 — 이해한 개념을 첫 질문·상위 3개에 두지 않고, 상위 3개에 아직 안 닫은 다른 핵심 개념이 있다."""
    cleared = set(E["cleared"])
    cleared_k = set().union(*(keys_of(q["label"], keys) for q in s1 if q["node_id"] in cleared))
    s2 = _next_session(E)
    return {"e1_q1_not_cleared": s2[0]["node_id"] not in cleared,
            "e2_top3_no_cleared": not any(q["node_id"] in cleared for q in s2[:3]),
            "e3_top3_other_key": any(keys_of(q["label"], keys) - cleared_k for q in s2[:3])}


def adaptivity(rep: dict, keys: dict) -> dict:
    s1 = first_session(rep)
    q1 = s1[0]
    return {"A": _checks_a(q1, keys), "B": _checks_b(rep["B"], q1), "C": _checks_c(rep["C"], q1),
            "D": _checks_d(rep["D"], q1), "E": _checks_e(rep["E"], s1, keys)}


# ---------------------------------------------------------------------------
# 회차 · 태그
# ---------------------------------------------------------------------------

def first_session(rep: dict) -> list[dict]:
    return rep["A"]["session1"]["questions"]


def all_questions(rep: dict) -> list[dict]:
    return [*first_session(rep), *(q for sc in FOLLOW_UPS for q in _next_session(rep[sc]))]


def score_rep(rep: dict, keys: dict, deck: Deck) -> dict:
    checks = adaptivity(rep, keys)
    per = {sc: st.mean(float(v) for v in c.values()) for sc, c in checks.items()}
    topk, redundancy = topk_redundancy(first_session(rep), keys)
    return {"topk": topk, "redundancy": redundancy, "grounding": grounding_scores(rep, deck),
            "adaptivity": {**per, "score": st.mean(per.values()), "checks": checks}}


def summary(tag: str, keys: dict, deck: Deck) -> dict:
    """태그의 회차 평균 + 검사별 통과 횟수."""
    reps = [score_rep(r, keys, deck) for r in load_tag(tag)]
    agg = {axis: {k: st.mean(r[axis][k] for r in reps) for k in reps[0][axis] if k != "checks"} for axis in AXES}
    passed: dict[str, list[int]] = {}
    for r in reps:
        for sc, c in r["adaptivity"]["checks"].items():
            for k, v in c.items():
                passed.setdefault(f"{sc}.{k}", []).append(int(v))
    agg["checks"] = {k: f"{sum(v)}/{len(v)}" for k, v in passed.items()}
    agg["n"] = len(reps)
    return agg


def _fmt(v) -> str:
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def compare_table(sums: dict[str, dict]) -> str:
    tags = list(sums)
    first = sums[tags[0]]
    rows = [(f"{axis}.{k}", [sums[t][axis].get(k) for t in tags]) for axis in AXES for k in first[axis]]
    rows += [(f"check.{k}", [sums[t]["checks"].get(k) for t in tags]) for k in first["checks"]]
    lines = ["| 항목 | " + " | ".join(f"{t} (n={sums[t]['n']})" for t in tags) + " |", "|---|" + "---|" * len(tags)]
    lines += [f"| {name} | " + " | ".join(_fmt(v) for v in vals) + " |" for name, vals in rows]
    return "\n".join(lines)


def main() -> None:
    from records import records_md

    keys, deck = load_keys(), Deck()
    # 핵심 개념의 원문 근거가 얼린 덱에 그대로 있는가 — 덱을 다시 얼렸거나 key_concepts.json 을 고쳤을 때 어긋남을 알린다 (점수는 안 바꾼다)
    for miss in misquoted_evidence(keys, deck.slides):
        print(f"[qcoach] 덱에 없는 핵심 개념 근거: {miss}", file=sys.stderr)
    sums = {t: summary(t, keys, deck) for t in sys.argv[1:]}
    for t, s in sums.items():
        (OUT / t / "records.md").write_text(records_md(t, keys, deck))
        (OUT / t / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1))
    print(compare_table(sums))


if __name__ == "__main__":
    main()
