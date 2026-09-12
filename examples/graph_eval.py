"""
개념 그래프(F-06→F-07)와 정합(F-11)의 품질을 재는 자 — 질문(F-08)의 앞단.

그래프가 나쁘면 질문도 나쁘다: 노드가 5개면 발표의 4분의 3 이 평가 대상에서 빠지고(MODEL_BENCH_F07),
근거 인용이 발화에 없는 문장이면 정합 판정이 거짓말이다. `qa_eval.py` 가 질문을 재듯 이 도구는 그래프를 잰다.
**지표는 전부 결정론적**이다 — 저장된 그래프·정합을 읽을 때는 LLM 호출이 0 이다.

    python examples/graph_eval.py                        # fixtures/live_qa_run.json 의 저장된 그래프·정합 (호출 0)
    python examples/graph_eval.py --rebuild --tag v1     # F-06→F-07→F-11 을 다시 돌려 잰다 (호출 ≈ 3~5, 2~3분)
    python examples/graph_eval.py --rebuild --stage align --tag a1   # 저장 그래프 고정, F-11 만 (F-11 가설은 이걸로)
    python examples/graph_eval.py --bundle-dir exports/eval_bundles --tag v1
    python examples/graph_eval.py --compare base --tag v1   # 전후 비교 → VERDICT

재는 것 (↑ 좋아지는 방향):
    slide_coverage ↑        본문이 있는 장 중 노드가 하나라도 걸린 장의 비율. 낮으면 발표 일부가 아예 평가 밖.
    anchored_ratio ↑        근거 장(slide_nos)이 있는 노드 비율. 없으면 힌트·인용·판정이 붙을 자리가 없다.
    label_grounded ↑        개념 이름의 낱말이 자료 본문에 실제로 있는 노드 비율. 낮으면 모델이 개념을 지어냈다.
    summary_grounding ↑     노드 요약의 낱말 중 근거 장 본문에 있는 비율(평균).
    nodes_per_slide ↑       본문 장 하나당 노드 수. 5노드/12장 같은 성긴 그래프를 잡는다.
    orphan_ratio ↓          간선이 하나도 없는 노드 비율. 위계가 없는 그래프.
    dangling_edges ↓        끝점 노드가 없는 간선 수 (LLM 이 id 를 지어냄).
    dup_label_pairs ↓       이름이 거의 같은 노드 쌍 수 (같은 개념을 둘로 쪼갬).
    align.evidence_found ↑  정합 판정의 근거 인용이 발화에 실제로 있는 비율. 낮으면 인용을 지어냈다.
    align.false_missing ↓   「누락」 판정인데 발화에 개념 이름이 나오는 수.
    align.false_aligned ↓   「정합」 판정인데 발화에 이름도 인용도 없는 수.
    align.coverage ↑        F-11 요약의 weight 가중 커버리지.

결과는 exports/graph_eval/<시각>_<tag>.json. 비교 판정 규칙은 qa_eval_compare 와 같다 (하나라도 나빠지면 REGRESSED).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chuckchuck.config import load_dotenv  # noqa: E402

load_dotenv()

from chuckchuck._evidence import clean_slide_text  # noqa: E402
from chuckchuck._match import norm_tokens  # noqa: E402
from chuckchuck.contracts import AlignmentDoc, ConceptGraph, Context, SlideDoc, Transcript  # noqa: E402

RUN_FIXTURE = ROOT / "fixtures" / "live_qa_run.json"
OUT_DIR = ROOT / "exports" / "graph_eval"
REPORT_DIR = OUT_DIR / "reports"

#: 본문이 있다고 치는 최소 글자 수 (정제 뒤). 표지·구분 장은 뺀다.
CONTENT_MIN_CHARS = 20
#: 이름이 "거의 같다" 로 보는 토큰 포함 비율 — 짧은 쪽 이름의 낱말이 긴 쪽에 이만큼 들어 있으면 같은 개념이다
#: ("집중 손실" 과 "집중 손실 문제"). 자카드는 이런 덧말 쌍을 놓친다.
DUP_CONTAINMENT = 0.8
#: 근거 인용이 발화에 "있다" 로 보는 토큰 포함 비율.
EVIDENCE_FOUND_MIN = 0.8

#: (summary 경로, 방향, 잡음 폭) — qa_eval_compare.PRIMARY 와 같은 규약.
PRIMARY: tuple[tuple[str, str, float], ...] = (
    ("slide_coverage", "up", 0.05),
    ("anchored_ratio", "up", 0.05),
    ("label_grounded", "up", 0.05),
    ("summary_grounding", "up", 0.05),
    ("nodes_per_slide", "up", 0.3),
    ("orphan_ratio", "down", 0.02),
    ("dangling_edges", "down", 0),
    ("dup_label_pairs", "down", 0),
    ("align.evidence_found", "up", 0.05),
    ("align.false_missing", "down", 0),
    ("align.false_aligned", "down", 0),
    ("align.coverage", "up", 0.05),
)


def tokens(text: str) -> set[str]:
    return {t for t in norm_tokens(text or "") if len(t) >= 2}


# ---------------------------------------------------------------------------
# 그래프 지표
# ---------------------------------------------------------------------------

def _depths(graph: ConceptGraph) -> dict[str, int]:
    parent = {e.to_id: e.from_id for e in graph.edges if e.kind == "parent"}
    depths: dict[str, int] = {}
    for n in graph.nodes:
        d, cur, seen = 0, n.id, set()
        while cur in parent and cur not in seen:
            seen.add(cur)
            cur = parent[cur]
            d += 1
        depths[n.id] = d
    return depths


def _dup_pairs(labels: list[str]) -> int:
    toks = [tokens(l) for l in labels]
    count = 0
    for i in range(len(toks)):
        for j in range(i + 1, len(toks)):
            a, b = toks[i], toks[j]
            if a and b and len(a & b) / min(len(a), len(b)) >= DUP_CONTAINMENT:
                count += 1
    return count


def graph_metrics(graph: ConceptGraph, slidedoc: SlideDoc) -> dict:
    slide_text = {s.slide_no: clean_slide_text(s.raw_text or "") for s in slidedoc.slides}
    content = {no for no, t in slide_text.items() if len(t.strip()) >= CONTENT_MIN_CHARS}
    deck_tokens = tokens(" ".join(slide_text.values()))
    ids = {n.id for n in graph.nodes}
    touched = {no for n in graph.nodes for no in n.slide_nos}
    linked = {e.from_id for e in graph.edges} | {e.to_id for e in graph.edges}

    def grounded(n) -> bool:
        lt = tokens(n.label)
        return bool(lt & deck_tokens) if lt else False

    def summary_ground(n) -> float | None:
        st = tokens(n.summary)
        if not st:
            return None
        ev = tokens(" ".join(slide_text.get(no, "") for no in n.slide_nos)) or deck_tokens
        return len(st & ev) / len(st)

    sg = [v for v in (summary_ground(n) for n in graph.nodes) if v is not None]
    nn = len(graph.nodes)
    depths = _depths(graph)
    return {
        "nodes": nn, "edges": len(graph.edges), "sections": len(graph.sections),
        "content_slides": len(content),
        "core_ratio": round(sum(1 for n in graph.nodes if n.importance == "core") / nn, 2) if nn else None,
        "slide_coverage": round(len(content & touched) / len(content), 2) if content else None,
        "anchored_ratio": round(sum(1 for n in graph.nodes if n.slide_nos) / nn, 2) if nn else None,
        "label_grounded": round(sum(1 for n in graph.nodes if grounded(n)) / nn, 2) if nn else None,
        "summary_grounding": round(sum(sg) / len(sg), 2) if sg else None,
        "nodes_per_slide": round(nn / len(content), 2) if content else None,
        "orphan_ratio": round(sum(1 for n in graph.nodes if n.id not in linked) / nn, 2) if nn else None,
        "dangling_edges": sum(1 for e in graph.edges if e.from_id not in ids or e.to_id not in ids),
        "dup_label_pairs": _dup_pairs([n.label for n in graph.nodes]),
        "depth_max": max(depths.values(), default=0),
        "depth2plus_ratio": round(sum(1 for d in depths.values() if d >= 2) / nn, 2) if nn else None,
        "top_weight_count": sum(1 for n in graph.nodes if n.weight >= 1.0),
    }


# ---------------------------------------------------------------------------
# 정합 지표
# ---------------------------------------------------------------------------

def alignment_metrics(alignment: AlignmentDoc, graph: ConceptGraph, transcript: Transcript) -> dict:
    speech_all = " ".join([transcript.full_text] + [s.text for s in transcript.by_slide])
    speech_tokens = tokens(speech_all)
    by_id = {n.id: n for n in graph.nodes}
    counts: dict[str, int] = {}
    found = with_evidence = false_missing = false_aligned = 0
    for it in alignment.items:
        counts[it.verdict] = counts.get(it.verdict, 0) + 1
        node = by_id.get(it.node_id)
        label_hit = bool(tokens(node.label) & speech_tokens) if node else False
        ev = tokens(it.evidence)
        ev_found = bool(ev) and len(ev & speech_tokens) / len(ev) >= EVIDENCE_FOUND_MIN
        if ev:
            with_evidence += 1
            found += int(ev_found)
        if it.verdict == "missing" and label_hit:
            false_missing += 1
        if it.verdict == "aligned" and not label_hit and not ev_found:
            false_aligned += 1
    n = len(alignment.items)
    return {
        "items": n, "verdicts": counts,
        "aligned_ratio": round(counts.get("aligned", 0) / n, 2) if n else None,
        "evidence_found": round(found / with_evidence, 2) if with_evidence else None,
        "false_missing": false_missing, "false_aligned": false_aligned,
        "coverage": round(float(alignment.summary.coverage), 2),
        "extra_concepts": len(alignment.extra_concepts),
    }


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def load_artifacts(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw["session"]["artifacts"] if "session" in raw else raw


def _load_compare_module():
    spec = importlib.util.spec_from_file_location("qa_eval_compare", ROOT / "examples" / "qa_eval_compare.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def compare_graph(before: dict, after: dict) -> dict:
    """qa_eval_compare 의 판정 규칙을 그래프 지표 표로 적용한다."""
    cmp = _load_compare_module()
    rows = []
    for key, direction, tol in PRIMARY:
        b, a = cmp.as_number(cmp.get_path(before, key)), cmp.as_number(cmp.get_path(after, key))
        rows.append({"key": key, "before": b, "after": a, "dir": direction,
                     "state": cmp.judge_metric(b, a, direction, tol)})
    states = {r["state"] for r in rows}
    verdict = "REGRESSED" if "worse" in states else ("IMPROVED" if "better" in states else "NOISE")
    info = [{"key": k, "before": cmp.as_number(before.get(k)), "after": cmp.as_number(after.get(k))}
            for k in ("nodes", "edges", "sections", "depth_max") if k in before or k in after]
    return {"verdict": verdict, "rows": rows, "secondary": info}


def rebuild(art: dict, llm_name: str | None, stage: str = "all") -> tuple[dict, list[dict]]:
    """다시 돌린다. stage=all: F-06→F-07→F-11 · graph: F-06→F-07 만(정합은 저장본) · align: 저장 그래프 위에 F-11 만.

    F-11 가설을 잴 때 그래프까지 다시 만들면 노드가 달라져 정합 지표가 그 잡음을 탄다 (2026-09-12 G1 실측).
    가설이 건드리는 단계만 다시 돌리는 것이 자다."""
    from chuckchuck import align_speech, build_graph, extract_concepts
    from chuckchuck.providers.llm_impl import get_llm
    qa_eval_spec = importlib.util.spec_from_file_location("qa_eval", ROOT / "examples" / "qa_eval.py")
    qa_eval = importlib.util.module_from_spec(qa_eval_spec)
    qa_eval_spec.loader.exec_module(qa_eval)
    llm = qa_eval.RecordingLLM(get_llm(llm_name))

    slidedoc = SlideDoc.from_dict(art["slide_doc"])
    transcript = Transcript.from_dict(art["transcript"]) if art.get("transcript") else None
    ctx = Context.from_dict(art.get("context") or {})
    t0 = time.time()
    out = dict(art)
    if stage in ("all", "graph"):
        concept_doc = extract_concepts(slidedoc, ctx, transcript=transcript, llm=llm)
        graph = build_graph(concept_doc, ctx, slide_doc=slidedoc, llm=llm)
        print(f"F-06→F-07 다시 만듦: 노드 {len(graph.nodes)} · 간선 {len(graph.edges)} ({time.time() - t0:.0f}s, {llm.name})")
        out["concept_doc"], out["concept_graph"] = concept_doc.to_dict(), graph.to_dict()
    else:
        graph = ConceptGraph.from_dict(art["concept_graph"])
        print(f"저장 그래프 고정: 노드 {len(graph.nodes)} · 간선 {len(graph.edges)}")
    if transcript is not None and stage in ("all", "align"):
        alignment = align_speech(graph, transcript, ctx, llm=llm)
        out["alignment_doc"] = alignment.to_dict()
        print(f"F-11 다시 판정: 항목 {len(alignment.items)} ({llm.name})")
    calls = [{k: v for k, v in c.items() if k not in ("system", "user", "response")} for c in llm.calls]
    return out, calls


def measure(art: dict) -> dict:
    graph = ConceptGraph.from_dict(art["concept_graph"])
    slidedoc = SlideDoc.from_dict(art["slide_doc"])
    summary = graph_metrics(graph, slidedoc)
    if art.get("alignment_doc") and art.get("transcript"):
        summary["align"] = alignment_metrics(AlignmentDoc.from_dict(art["alignment_doc"]), graph,
                                             Transcript.from_dict(art["transcript"]))
    return summary


def print_summary(s: dict) -> None:
    print(f"노드 {s['nodes']} · 간선 {s['edges']} · 섹션 {s['sections']} · 본문 장 {s['content_slides']} · 깊이 {s['depth_max']}")
    print(f"장 커버리지 {s['slide_coverage']} · 근거 장 있음 {s['anchored_ratio']} · 이름 근거 {s['label_grounded']} · "
          f"요약 근거 {s['summary_grounding']} · 장당 노드 {s['nodes_per_slide']}")
    print(f"고립 {s['orphan_ratio']} · 끊긴 간선 {s['dangling_edges']} · 중복 이름 쌍 {s['dup_label_pairs']}")
    a = s.get("align")
    if a:
        print(f"정합 {a['items']}항목 {a['verdicts']} · 인용∈발화 {a['evidence_found']} · 거짓 누락 {a['false_missing']} · "
              f"거짓 정합 {a['false_aligned']} · 커버리지 {a['coverage']}")


def run_one(bundle: Path, args) -> dict:
    art = load_artifacts(bundle)
    calls: list[dict] = []
    if args.rebuild:
        art, calls = rebuild(art, args.llm, args.stage)
    summary = measure(art)
    print(f"\n자료: {art['concept_graph'].get('file_name', bundle.stem)}")
    print_summary(summary)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"{stamp}{'_' + args.tag if args.tag else ''}.json"
    payload = {"bundle": str(bundle), "rebuilt": bool(args.rebuild), "summary": summary, "calls": calls}
    if args.rebuild:
        payload["artifacts"] = {k: art[k] for k in ("concept_graph", "alignment_doc") if k in art}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"요약 저장: {out.relative_to(ROOT)}")
    return summary


def latest_for_tag(tag: str) -> Path:
    hits = sorted(OUT_DIR.glob(f"*_{tag}.corpus.json")) or sorted(OUT_DIR.glob(f"*_{tag}.json"))
    if not hits:
        sys.exit(f"tag '{tag}' 결과가 없어요: {OUT_DIR}/*_{tag}.json")
    return hits[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", type=Path, default=RUN_FIXTURE)
    ap.add_argument("--bundle-dir", type=Path, default=None)
    ap.add_argument("--rebuild", action="store_true", help="실 LLM 으로 다시 돌린다 (--stage 로 범위)")
    ap.add_argument("--stage", choices=("all", "graph", "align"), default="all",
                    help="all: F-06→07→11 · graph: F-06→07 만 · align: 저장 그래프 위에 F-11 만 (F-11 가설용)")
    ap.add_argument("--llm", default=None, help="REASONING_BACKEND 대신 쓸 백엔드")
    ap.add_argument("--tag", default="")
    ap.add_argument("--compare", default=None, help="이 tag 의 최신 결과와 비교해 VERDICT 를 찍는다")
    ap.add_argument("--compare-only", action="store_true", help="새로 재지 않고 --compare 와 --tag 의 최신 결과만 비교한다")
    ap.add_argument("--ledger", action="store_true", help="docs/GRAPH_BENCH_LEDGER.md 에 한 줄 붙인다")
    ap.add_argument("--note", default="", help="장부 메모 (가설 이름 등)")
    args = ap.parse_args()

    bundles = sorted(args.bundle_dir.glob("*.json")) if args.bundle_dir else [args.bundle]
    if not bundles:
        sys.exit(f"번들이 없어요: {args.bundle_dir}")
    if args.compare_only and not (args.compare and args.tag):
        sys.exit("--compare-only 에는 --compare 와 --tag 둘 다 필요해요")
    summaries = [] if args.compare_only else [run_one(b, args) for b in bundles]
    if len(summaries) > 1:
        qa_spec = importlib.util.spec_from_file_location("qa_eval", ROOT / "examples" / "qa_eval.py")
        qa_eval = importlib.util.module_from_spec(qa_spec)
        qa_spec.loader.exec_module(qa_eval)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = OUT_DIR / f"{stamp}{'_' + args.tag if args.tag else ''}.corpus.json"
        out.write_text(json.dumps({"n": len(summaries), "summary": qa_eval.aggregate_summaries(summaries)},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"코퍼스 요약 저장: {out.relative_to(ROOT)}")

    if args.compare:
        if not args.tag:
            sys.exit("--compare 에는 --tag 가 필요해요")
        before_p, after_p = latest_for_tag(args.compare), latest_for_tag(args.tag)
        before = json.loads(before_p.read_text(encoding="utf-8"))["summary"]
        after = json.loads(after_p.read_text(encoding="utf-8"))["summary"]
        result = compare_graph(before, after)
        cmp = _load_compare_module()
        md = cmp.render_markdown(result, before_p.stem, after_p.stem)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        rp = REPORT_DIR / f"{before_p.stem}__vs__{after_p.stem}.md"
        rp.write_text(md, encoding="utf-8")
        print("\n" + md + f"리포트: {rp.relative_to(ROOT)}")
        if args.ledger:
            cmp.LEDGER = ROOT / "docs" / "GRAPH_BENCH_LEDGER.md"
            cmp.append_ledger(result, before_p.stem, after_p.stem, args.note)
            print(f"장부: {cmp.LEDGER.relative_to(ROOT)}")
        print(f"VERDICT: {result['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
