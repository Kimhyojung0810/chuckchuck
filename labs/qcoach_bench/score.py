"""
질문 코치 벤치 채점 — LLM 없이 규칙으로만 잰다 (같은 LLM 이 자기 질문을 좋다고 하는 채점을 피한다).
규칙은 baseline 을 돌리기 전에 고정했다 (2026-10-02). 개선 결과에 맞춰 고치지 않는다 — README §규칙.

    .venv/bin/python labs/qcoach_bench/score.py baseline              # 한 태그 점수 + 기록표(records.md)
    .venv/bin/python labs/qcoach_bench/score.py baseline after        # 전후 비교표

Priority   덱 원문으로 고른 핵심 개념 K1~K5(key_concepts.json)를 먼저 묻는가 — 첫 세션(A) 질문 목록
           p_q1 첫 질문이 K · p_top3 상위 3개 중 K 몫 · p_tier1 상위 3개에 K1/K2 · p_cov 질문 7개가 덮는 K 수/5
Grounding  질문이 자료·그래프에 근거하는가 — 모든 세션의 모든 질문
           g_node 대상 노드가 그래프에 있음 · g_num 질문·모범답의 수가 전부 덱에 있음 · g_anchor 근거 장 본문의 내용어 2개 이상 ·
           g_target 질문이 대상 개념 이름을 부름 · g_vocab 덱에 없는 내용어 40% 이하 · g_quote 근거 인용이 그 장 원문 그대로
Adaptivity 사용자 상태에 따라 다음 질문이 맞게 바뀌는가 — 시나리오별 검사의 통과 비율, A~E 평균
"""
from __future__ import annotations

import json
import re
import statistics as st
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
FIX = OUT / "fixtures"

FOREIGN_MAX = 0.4
TWIN_MAX = 0.3
STAGE_ORDER = {"narrow": 0, "scaffold": 1, "explain": 2}
JOSA = ("으로써", "으로서", "에서는", "에서도", "이라는", "이라고", "라는", "라고", "으로", "에서", "에게", "에는", "까지", "부터",
        "처럼", "보다", "이나", "이란", "은", "는", "이", "가", "을", "를", "의", "에", "도", "로", "와", "과", "만", "나", "란")
#: 질문의 뼈대 말 — 어느 덱의 질문에나 나오는 묻는 말이라 근거 대조에서 뺀다
FUNC = {"왜", "어떻게", "무엇", "무엇인가요", "어떤", "설명", "설명해", "설명해주세요", "설명해 주세요", "생각", "생각하나요", "이유",
        "의미", "근거", "말씀", "발표", "발표에서", "자료", "자료에서", "슬라이드", "그렇다면", "그러면", "그런데", "이것", "그것",
        "어느", "어디", "얼마나", "가요", "나요", "인가요", "있나요", "한다고", "했는데", "했어요", "말했는데", "보면", "때문",
        "결과", "차이", "관계", "연결", "구체적", "구체적으로", "실제로", "정말", "다른", "같은", "모두", "가장", "있다", "없다",
        "한다", "된다", "합니다", "나요?", "인데", "하는", "되는", "있는", "없는", "다고", "라면", "이라면", "경우", "부분"}


def nfc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def squash(s: str) -> str:
    return re.sub(r"\s+", "", nfc(s)).lower()


def load_keys() -> dict:
    return json.loads((HERE / "key_concepts.json").read_text())


def keys_of(label: str, keys: dict) -> set[str]:
    lab = squash(label)
    return {c["id"] for c in keys["concepts"] if any(a.lower() in lab for a in c["aliases"])}


def key_of(label: str, keys: dict) -> str:
    ks = keys_of(label, keys)
    return min(ks) if ks else ""


def tokens(text: str) -> list[str]:
    out = []
    for t in re.findall(r"[가-힣A-Za-z][가-힣A-Za-z0-9%]*", nfc(text)):
        for j in JOSA:
            if len(t) > len(j) + 1 and t.endswith(j):
                t = t[: -len(j)]
                break
        # 「…」라고 처럼 따옴표 뒤에 떨어진 조사·어미는 낱말이 아니다 (2026-10-02 채점기 버그 — baseline 채점 전에 고침)
        if len(t) >= 2 and t not in FUNC and t not in JOSA and t not in ("이라고", "라고"):
            out.append(t)
    return out


def found(tok: str, text_sq: str) -> bool:
    stem = tok if len(tok) <= 3 else tok[: max(3, len(tok) - 2)]
    return stem.lower() in text_sq


def numbers(text: str) -> set[str]:
    out = set()
    # 「자료 11장」 의 장 번호는 내용 수치가 아니다 (2026-10-02 채점기 버그 — baseline 채점 전에 고침)
    text = re.sub(r"\d+\s*장", " ", nfc(text))
    for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        n = n.replace(",", "").rstrip(".")
        out.add(n.rstrip("0").rstrip(".") if "." in n else n)
    return out


class Deck:
    def __init__(self):
        sd = json.loads((FIX / "slidedoc.json").read_text())
        g = json.loads((FIX / "graph.json").read_text())
        self.slides = {s["slide_no"]: s.get("raw_text") or "" for s in sd["slides"]}
        self.sq = {n: squash(t) for n, t in self.slides.items()}
        self.all_sq = "".join(self.sq.values())
        self.nums = set().union(*(numbers(t) for t in self.slides.values()))
        self.nodes = {n["id"]: n for n in g["nodes"]}


def grounding(q: dict, deck: Deck) -> dict:
    text = q.get("question") or ""
    cited = set(q.get("slide_nos") or []) | ({q["evidence_slide_no"]} if q.get("evidence_slide_no") else set())
    cited_sq = "".join(deck.sq.get(n, "") for n in cited)
    toks = list(dict.fromkeys(tokens(text)))
    anchored = [t for t in toks if found(t, cited_sq)]
    foreign = [t for t in toks if not found(t, deck.all_sq)]
    label_toks = tokens(q.get("label") or "") or [squash(q.get("label") or "")]
    quote = q.get("evidence_quote") or ""
    r = {
        "g_node": q.get("node_id") in deck.nodes,
        "g_num": numbers(text + " " + (q.get("answer_gist") or "")) <= deck.nums,
        "g_anchor": len(anchored) >= 2,
        "g_target": any(found(t, squash(text)) for t in label_toks),
        "g_vocab": (len(foreign) / len(toks) if toks else 1.0) <= FOREIGN_MAX,
        "g_quote": (squash(quote) in deck.sq.get(q.get("evidence_slide_no") or 0, "")) if quote else True,
    }
    r["grounded"] = all(r.values())
    r["_foreign"] = foreign
    r["_bad_nums"] = sorted(numbers(text + " " + (q.get("answer_gist") or "")) - deck.nums)
    return r


def followup_grounded(text: str, q1: dict, deck: Deck) -> bool:
    if not text:
        return True
    cited_sq = "".join(deck.sq.get(n, "") for n in (q1.get("slide_nos") or []))
    toks = tokens(text)
    return numbers(text) <= deck.nums and any(found(t, cited_sq or deck.all_sq) for t in toks)


def gist_twin(a: dict, b: dict) -> bool:
    ta, tb = set(tokens(a.get("answer_gist") or "")), set(tokens(b.get("answer_gist") or ""))
    return bool(ta | tb) and len(ta & tb) / len(ta | tb) >= TWIN_MAX


def priority(qs: list[dict], keys: dict) -> dict:
    ks = [keys_of(q["label"], keys) for q in qs]
    top3 = ks[:3]
    return {"p_q1": float(bool(ks and ks[0])), "p_top3": sum(bool(k) for k in top3) / 3,
            "p_tier1": float(any(k & {"K1", "K2"} for k in top3)),
            "p_cov": len(set().union(*ks)) / len(keys["concepts"]) if ks else 0.0}


def adaptivity(rep: dict, keys: dict) -> dict:
    s1 = rep["A"]["session1"]["questions"]
    q1 = s1[0]
    B, C, D, E = rep["B"], rep["C"], rep["D"], rep["E"]
    s2 = lambda sc: sc["session2"]["questions"]  # noqa: E731
    q1_toks = set(tokens(q1["label"] + " " + q1["question"] + " " + (q1.get("answer_gist") or "")))
    nb = B["next"] or {}
    fc = (C["next"] or {}).get("followup") or ""
    fd = D["judgement"].get("followup") or ""
    st1, st2 = D["judgement"].get("coach_stage") or "", D["judgement2"].get("coach_stage") or ""
    cleared = set(E["cleared"])
    cleared_k = set().union(*(keys_of(q["label"], keys) for q in s1 if q["node_id"] in cleared))
    e_top3 = s2(E)[:3]
    checks = {
        "A": {"a1_q1_key": bool(keys_of(q1["label"], keys)), "a2_q1_not_trap": not q1.get("trap"),
              "a3_q1_single_ask": (q1["question"].count("?") <= 1)},
        "B": {"b1_passed": bool(B["judgement"]["passed"]), "b2_closed": bool(B["judgement"]["mastered"]),
              "b3_next_new": bool(nb.get("node_id")) and nb["node_id"] != q1["node_id"] and not gist_twin(nb, q1),
              "b4_s2_moves_on": s2(B)[0]["node_id"] != q1["node_id"]},
        "C": {"c1_not_passed": not C["judgement"]["passed"],
              "c2_followup": bool(fc) and squash(fc) != squash(q1["question"]),
              "c3_same_concept": bool(set(tokens(fc)) & q1_toks),
              "c4_s2_retries": s2(C)[0]["node_id"] == q1["node_id"]},
        "D": {"d1_coached": st1 in ("narrow", "scaffold") and not D["judgement"].get("score"),
              "d2_narrower": bool(D["judgement"].get("choices")) or (bool(fd) and len(fd) < len(q1["question"])),
              "d3_escalates": STAGE_ORDER.get(st2, -1) > STAGE_ORDER.get(st1, -1),
              "d4_s2_retries": s2(D)[0]["node_id"] == q1["node_id"]},
        "E": {"e1_q1_not_cleared": s2(E)[0]["node_id"] not in cleared,
              "e2_top3_no_cleared": not any(q["node_id"] in cleared for q in e_top3),
              "e3_top3_other_key": any(keys_of(q["label"], keys) - cleared_k for q in e_top3)},
    }
    return checks


def all_questions(rep: dict) -> list[dict]:
    qs = list(rep["A"]["session1"]["questions"])
    for sc in "BCDE":
        qs += rep[sc]["session2"]["questions"]
    return qs


def score_rep(rep: dict, keys: dict, deck: Deck) -> dict:
    pr = priority(rep["A"]["session1"]["questions"], keys)
    gs = [grounding(q, deck) for q in all_questions(rep)]
    q1 = rep["A"]["session1"]["questions"][0]
    fus = [(rep["C"]["next"] or {}).get("followup") or "", rep["D"]["judgement"].get("followup") or ""]
    ad = adaptivity(rep, keys)
    g = {k: st.mean(float(x[k]) for x in gs) for k in ("g_node", "g_num", "g_anchor", "g_target", "g_vocab", "g_quote", "grounded")}
    g["g_followup"] = st.mean(float(followup_grounded(f, q1, deck)) for f in fus)
    # 진단 (공식 점수 아님): 함정은 일부러 틀린 전제를 얹는 설계라 g_num 이 떨어진다 — 함정을 뺀 근거율과 함정 수를 따로 본다
    plain = [x for x, q in zip(gs, all_questions(rep)) if not q.get("trap")]
    g["diag_grounded_no_trap"] = st.mean(float(x["grounded"]) for x in plain) if plain else 0.0
    g["diag_traps_per_session"] = sum(bool(q.get("trap")) for q in all_questions(rep)) / 5
    per = {sc: st.mean(float(v) for v in c.values()) for sc, c in ad.items()}
    return {"priority": {**pr, "score": st.mean(pr.values())},
            "grounding": {**g, "score": g["grounded"]},
            "adaptivity": {**per, "score": st.mean(per.values()), "checks": ad},
            "_ground_rows": gs}


def load_tag(tag: str) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((OUT / tag).glob("rep*.json"))]


def summary(tag: str) -> dict:
    keys, deck = load_keys(), Deck()
    reps = [score_rep(r, keys, deck) for r in load_tag(tag)]
    agg = {}
    for axis in ("priority", "grounding", "adaptivity"):
        names = [k for k in reps[0][axis] if k != "checks"]
        agg[axis] = {k: st.mean(r[axis][k] for r in reps) for k in names}
    checks = {}
    for r in reps:
        for sc, c in r["adaptivity"]["checks"].items():
            for k, v in c.items():
                checks.setdefault(f"{sc}.{k}", []).append(int(v))
    agg["checks"] = {k: f"{sum(v)}/{len(v)}" for k, v in checks.items()}
    agg["n"] = len(reps)
    return agg


def records_md(tag: str) -> str:
    """질문마다 대상 노드 · 선택 이유 · 사용자 상태 · 생성된 질문 (작업 5)."""
    keys, deck = load_keys(), Deck()
    lines = [f"# {tag} — 질문 기록", ""]
    for i, rep in enumerate(load_tag(tag)):
        lines.append(f"## rep{i}")
        sets = [("A", rep["A"]["state"], rep["A"]["session1"]["questions"])]
        sets += [(sc, rep[sc]["state"] + " → 다음 리허설", rep[sc]["session2"]["questions"]) for sc in "BCDE"]
        for sc, state, qs in sets:
            lines.append(f"### {sc} · {state}")
            lines.append("| # | 대상 노드 | K | 선택 이유 (source·rank·why) | 질문 | 근거 |")
            lines.append("|---|---|---|---|---|---|")
            for n, q in enumerate(qs, 1):
                b = q.get("basis") or {}
                why = f"{q.get('source')}·r{b.get('rank', '')} — {q.get('why', '')}"
                gr = grounding(q, deck)
                bad = [k for k in ("g_num", "g_anchor", "g_target", "g_vocab", "g_quote") if not gr[k]]
                lines.append(f"| {n} | {q['label']} | {','.join(sorted(keys_of(q['label'], keys)))} | {why} | "
                             f"{q['question']} | {'ok' if not bad else ' '.join(bad)} |")
            if sc in "BCD":
                j = rep[sc]["judgement"]
                lines.append(f"\n- 답: {rep[sc].get('answer', '(모르겠어요)')}")
                lines.append(f"- 판정: {j['verdict']} {j['score']} · passed={j['passed']} · mastered={j['mastered']} · "
                             f"stage={j.get('coach_stage') or '-'}")
                nxt = rep[sc]["next"] or {}
                lines.append(f"- 코치의 다음 말: {nxt.get('question') or nxt.get('followup') or '-'}"
                             + (f" · 보기 {nxt.get('choices')}" if nxt.get("choices") else ""))
                if sc == "D":
                    j2 = rep["D"]["judgement2"]
                    lines.append(f"- 두 번째 모르겠어요: stage={j2.get('coach_stage')} · {j2.get('followup') or j2.get('explanation', '')[:120]}")
            lines.append("")
    return "\n".join(lines)


def _fmt(v) -> str:
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def main() -> None:
    tags = sys.argv[1:]
    sums = {t: summary(t) for t in tags}
    for t in tags:
        (OUT / t / "records.md").write_text(records_md(t))
        (OUT / t / "summary.json").write_text(json.dumps(sums[t], ensure_ascii=False, indent=1))
    rows = []
    for axis in ("priority", "grounding", "adaptivity"):
        for k in sums[tags[0]][axis]:
            rows.append((f"{axis}.{k}", [sums[t][axis].get(k) for t in tags]))
    rows += [(f"check.{k}", [sums[t]["checks"].get(k) for t in tags]) for k in sums[tags[0]]["checks"]]
    print("| 항목 | " + " | ".join(f"{t} (n={sums[t]['n']})" for t in tags) + " |")
    print("|---|" + "---|" * len(tags))
    for name, vals in rows:
        print(f"| {name} | " + " | ".join(_fmt(v) for v in vals) + " |")


if __name__ == "__main__":
    main()
