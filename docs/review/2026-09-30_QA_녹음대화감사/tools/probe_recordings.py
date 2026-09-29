"""
녹음 한 벌을 **통째로** 제품의 코드 대조(F-11)에 태워 심은 결함을 몇 개 잡는지 센다 — LLM 0콜, 결정적.

probe_rules.py 는 심은 문장 하나씩을 규칙 함수에 넣는다. 여기서는 화면과 같은 길을 탄다:
클로바 .txt → `demo/clova_transcript.transcript_dict` → `f04_infer_marks.infer_slide_marks`(글로 장 경계 추정) →
`f05_stt.split_by_slide` → `f11_align.align_speech`(자료 원문 = 실제 Upstage 파싱본). 장 경계는 두 가지로 본다 —
ui(추정 경계, 녹음만 올린 사용자와 같다)·truth(정답 경계, transcript*.json).

LLM 자리는 **아무것도 못 보는 판정**이다 — 모든 개념을 aligned 로, 근거는 그 개념 장 구간의 첫 문장으로 돌려준다(최악의 경우).
그래서 여기서 잡힌 모순·건너뜀은 전부 코드가 잡은 것이다. 그래프는 LLM 이 없으니 뿌리 하나 + 장마다 개념 하나로 짓는다.

    .venv/bin/python "docs/review/2026-09-30_QA_녹음대화감사/tools/probe_recordings.py"                      # 이 저장소 코드로
    .venv/bin/python "docs/review/2026-09-30_QA_녹음대화감사/tools/probe_recordings.py" --repo <다른 worktree>   # 그 코드로(전·후 비교)
    ... --corpus <폴더> --decks a b     # 다른 덱 묶음(held-out)  ·  --older  예전 녹음(혈당·수면) 회귀 확인
"""
from __future__ import annotations

import argparse
import glob
import importlib
import json
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve()
DEFAULT_REPO = HERE.parents[4]


def _load(repo: Path):
    sys.path.insert(0, str(repo))
    mods = {name: importlib.import_module(name) for name in (
        "chuckchuck.contracts", "chuckchuck.f11_align", "chuckchuck.f04_infer_marks", "chuckchuck.f05_stt",
        "chuckchuck.providers.llm_base", "demo.clova_transcript")}
    return mods


class _Blind:
    """아무것도 못 보는 판정 — 모든 개념 aligned, 근거는 그 장 구간의 첫 문장. 부른 횟수를 센다."""

    def __init__(self, base, items: list[dict]):
        class Impl(base):
            name = "blind"

            def complete(self_inner, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):  # noqa: N805
                self.calls += 1
                return json.dumps({"items": items, "speech_edges": [], "extra_concepts": []}, ensure_ascii=False)
        self.calls = 0
        self.engine = Impl()


def _first_line(text: str) -> str:
    for ln in (text or "").split("\n"):
        ln = ln.strip().strip("#").strip()
        if ln and not ln.replace(" ", "").replace("/", "").replace("-", "").isdigit():
            return ln
    return ""


def synthetic_graph(C, doc):
    """뿌리(모든 장) + 장마다 개념 하나 — 라벨은 장 제목(없으면 첫 글줄), 요약은 둘째 글줄."""
    nodes = [C.ConceptNode(id="root", label=_first_line(doc.slides[0].raw_text) or "발표", slide_nos=[s.slide_no for s in doc.slides],
                           weight=1.0, depth=1, importance="core")]
    for s in doc.slides:
        lines = [x.strip().strip("#").strip() for x in (s.raw_text or "").split("\n") if x.strip()]
        lines = [x for x in lines if not x.replace(" ", "").replace("/", "").replace("-", "").isdigit()]
        label = (s.title or "").strip() or (lines[0] if lines else f"{s.slide_no}장")
        summary = next((x for x in lines if x != label and not x.startswith("|")), "")
        nodes.append(C.ConceptNode(id=f"s{s.slide_no}", label=label[:30], slide_nos=[s.slide_no], summary=summary[:80],
                                   weight=0.6, depth=2, parent_id="root", importance="core"))
    return C.ConceptGraph(file_name=doc.file_name, total_slides=len(doc.slides), nodes=nodes)


def blind_items(graph, transcript) -> list[dict]:
    first = {}
    for seg in transcript.by_slide:
        text = (seg.text or "").strip()
        if text and seg.slide_no not in first:
            first[seg.slide_no] = text.split(". ")[0].rstrip(".") + "."
    out = []
    for n in graph.nodes:
        ev = next((first[no] for no in n.slide_nos if no in first), "")
        out.append({"node_id": n.id, "verdict": "aligned", "evidence": ev})
    return out


def ui_transcript(M, doc, txt: Path):
    C, f04, f05 = M["chuckchuck.contracts"], M["chuckchuck.f04_infer_marks"], M["chuckchuck.f05_stt"]
    t = C.Transcript.from_dict(M["demo.clova_transcript"].transcript_dict(txt))
    got = f04.infer_slide_marks(doc, t.words, t.duration_sec)
    if got.estimated:
        t.by_slide = f05.split_by_slide(t.words, got.marks)
    return t, got.match


def _kind(it) -> str:
    k = getattr(it, "contra_kind", "") or ""
    if k:
        return k
    note = it.note or ""
    if "라고 했는데" in note:
        return "number"
    if "맞다·아니다" in note:
        return "polarity"
    return "direction"


def run_one(M, graph, doc, transcript, hint=None):
    C, f11 = M["chuckchuck.contracts"], M["chuckchuck.f11_align"]
    blind = _Blind(M["chuckchuck.providers.llm_base"].LLMProvider, blind_items(graph, transcript))
    al = f11.align_speech(graph, transcript, llm=blind.engine, slide_doc=doc, speech_match=hint)
    contra = [(it.deck_slide_no, _kind(it), it.evidence, it.deck_quote, it.note)
              for it in al.items if it.verdict == "contradiction" and (it.deck_quote or "").strip()]
    skipped = [s.slide_no for s in al.skipped_slides]
    return {"match": al.speech_match, "contra": contra, "skipped": skipped, "calls": blind.calls,
            "evidence": {it.node_id: it.evidence for it in al.items if it.evidence}}


def score(truth_rec: dict, got: dict) -> dict:
    """심은 N·D·S 를 잡았나 · 기대에 없는 모순·건너뜀(오탐) · 다른 발표를 알아봤나."""
    exp = truth_rec.get("expect") or {}
    rows, hit = [], 0
    planted = [p for p in truth_rec.get("planted") or [] if p["kind"] in
               ("contradiction_number", "contradiction_direction", "skipped_slide")]
    for p in planted:
        if p["kind"] == "skipped_slide":
            ok = p["slide"] in got["skipped"]
        else:
            want = "number" if p["kind"] == "contradiction_number" else "direction"
            ok = any(no == p["slide"] and k == want for no, k, *_ in got["contra"])
        hit += ok
        rows.append((p["id"], p["kind"], p["slide"], ok))
    fp_contra = [c for c in got["contra"] if c[0] not in (exp.get("contradiction_slides") or [])]
    fp_skip = [s for s in got["skipped"] if s not in (exp.get("skipped_slides") or [])]
    unrelated_ok = (got["match"] == "unrelated") if exp.get("speech_unused") else (got["match"] != "unrelated")
    return {"rows": rows, "hit": hit, "n": len(planted), "fp_contra": fp_contra, "fp_skip": fp_skip, "match_ok": unrelated_ok}


def show(label: str, got: dict, sc: dict | None) -> None:
    head = f"### {label} — 정합 {got['match']} · 모순 {[(c[0], c[1]) for c in got['contra']]} · 건너뜀 {got['skipped']}"
    print(head)
    for no, k, ev, dq, note in got["contra"]:
        print(f"    - {no}장 {k}: «{ev[:70]}» ↔ «{dq[:60]}» · {note[:60]}")
    if sc is None:
        return
    for pid, kind, slide, ok in sc["rows"]:
        print(f"    {'✓' if ok else '✗'} {pid} {kind} {slide}장")
    if sc["fp_contra"] or sc["fp_skip"]:
        print(f"    ! 오탐 모순 {[(c[0], c[1], c[2][:40]) for c in sc['fp_contra']]} · 오탐 건너뜀 {sc['fp_skip']}")
    if not sc["match_ok"]:
        print("    ! 다른 발표 판정이 기대와 다르다")


def _file(folder: Path, pattern: str) -> Path | None:
    hits = [Path(p) for p in glob.glob(str(folder / "*")) if unicodedata.normalize("NFC", Path(p).name).endswith(pattern)]
    return hits[0] if hits else None


def run_corpus(M, corpus: Path, decks: list[str]) -> dict:
    C = M["chuckchuck.contracts"]
    total = {"hit": 0, "n": 0, "fp": 0, "r3_ok": 0, "r3_n": 0, "calls": 0}
    for name in decks:
        d = corpus / name
        truth = json.loads((d / "truth.json").read_text(encoding="utf-8"))
        parsed = d / "slidedoc_parsed_upstage.json"
        doc = C.SlideDoc.from_dict(json.loads((parsed if parsed.exists() else d / "slidedoc.json").read_text(encoding="utf-8")))
        graph = synthetic_graph(C, doc)
        print(f"\n## {name} ({'Upstage 파싱본' if parsed.exists() else 'slidedoc.json'})")
        for rid, rec in truth["recordings"].items():
            for mode in ("ui", "truth"):
                if mode == "ui":
                    t, hint = ui_transcript(M, doc, d / rec["clova_file"])
                else:
                    t, hint = C.Transcript.from_dict(json.loads((d / rec["transcript_file"]).read_text(encoding="utf-8"))), None
                got = run_one(M, graph, doc, t, hint)
                sc = score(rec, got)
                show(f"{rid} ({rec['kind']}) · 장 경계 {mode}", got, sc)
                total["calls"] += got["calls"]
                if mode != "ui":
                    continue            # 합계는 화면과 같은 길(ui)로만 센다 — truth 는 참고
                total["hit"] += sc["hit"]
                total["n"] += sc["n"]
                if rec["kind"] in ("clean", "flawed"):
                    total["fp"] += len(sc["fp_contra"]) + len(sc["fp_skip"])
                if rec["kind"] == "unrelated":
                    total["r3_n"] += 1
                    total["r3_ok"] += sc["match_ok"]
    return total


def run_older(M, int3: Path) -> dict:
    """예전 녹음 — 혈당(전사 .txt · 합성 transcript.json) · 수면(.txt). 그래프·판정은 벤치 캐시의 실제 것(LLM 응답을 얼린 것).
    개념마다 (판정, 근거) 를 돌려준다 — 전·후 코드의 차이를 `--dump` 로 견줄 수 있게."""
    C, f11 = M["chuckchuck.contracts"], M["chuckchuck.f11_align"]
    base = M["chuckchuck.providers.llm_base"].LLMProvider
    cache = Path("/home/yehschuck/project/wt-qa-judge2/labs/qa_bench/out")
    corpus = DEFAULT_REPO / "labs" / "qa_bench" / "corpus"
    runs = [
        ("health_glucose · corpus transcript.json (장 경계 정답)", "health_glucose", corpus / "health_glucose" / "transcript.json", None),
        ("health_glucose · ppt/_held_health_glucose 전사 .txt (ui)", "health_glucose", None, int3 / "ppt" / "_held_health_glucose"),
        ("sleep · ppt/수면발표 전사 .txt (ui)", "sleep", None, int3 / "ppt" / "수면발표"),
    ]
    dump: dict = {}
    for label, cname, tjson, folder in runs:
        doc = C.SlideDoc.from_dict(json.loads((cache / cname / "slide_doc.json").read_text(encoding="utf-8")))
        graph = C.ConceptGraph.from_dict(json.loads((cache / cname / "graph.json").read_text(encoding="utf-8")))
        frozen = json.loads((cache / cname / "alignment.json").read_text(encoding="utf-8"))
        items = [{"node_id": it["node_id"], "verdict": it["verdict"], "evidence": it.get("evidence", "")} for it in frozen["items"]]

        class Frozen(base):
            name = "frozen"

            def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
                return json.dumps({"items": items, "speech_edges": [], "extra_concepts": []}, ensure_ascii=False)

        if tjson is not None:
            t, hint = C.Transcript.from_dict(json.loads(tjson.read_text(encoding="utf-8"))), None
        else:
            txt = _file(folder, ".txt")
            if txt is None:
                print(f"\n### {label} — 전사 없음 (건너뜀)")
                continue
            t, hint = ui_transcript(M, doc, txt)
        al = f11.align_speech(graph, t, llm=Frozen(), slide_doc=doc, speech_match=hint)
        contra = [(it.deck_slide_no, _kind(it), it.evidence, it.deck_quote, it.note)
                  for it in al.items if it.verdict == "contradiction" and (it.deck_quote or "").strip()]
        got = {"match": al.speech_match, "contra": contra, "skipped": [s.slide_no for s in al.skipped_slides]}
        show(label, got, None)
        counts = al.summary.verdict_counts
        print(f"    판정 {counts} · 근거 있는 aligned {sum(1 for it in al.items if it.verdict == 'aligned' and it.evidence)}")
        dump[label] = {it.node_id: [it.verdict, it.evidence] for it in al.items}
    return dump


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(DEFAULT_REPO), help="chuckchuck 을 불러올 저장소 (전·후 비교)")
    ap.add_argument("--corpus", default=str(DEFAULT_REPO / "labs" / "qa_bench" / "corpus"))
    ap.add_argument("--decks", nargs="*", default=["audit_co2", "audit_kiosk", "audit_bunt"])
    ap.add_argument("--older", action="store_true", help="예전 녹음(혈당·수면)도 돌린다")
    ap.add_argument("--int3", default="/home/yehschuck/project/wt-qa-int3", help="ppt/ 예전 녹음을 읽을 체크아웃")
    ap.add_argument("--dump", default="", help="예전 녹음의 개념별 (판정, 근거) 를 이 JSON 에 쓴다")
    args = ap.parse_args()
    M = _load(Path(args.repo))
    print(f"# 녹음 통째 대조 — 코드 {args.repo}")
    total = run_corpus(M, Path(args.corpus), args.decks) if args.decks else None
    if args.older:
        print("\n## 예전 녹음 (회귀 확인)")
        dump = run_older(M, Path(args.int3))
        if args.dump:
            Path(args.dump).write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
    if total is not None:
        print(f"\n## 합계 (장 경계 ui) — 심은 결함 {total['hit']}/{total['n']} · 바른·틀린 녹음의 오탐 {total['fp']} · "
              f"다른 발표 알아봄 {total['r3_ok']}/{total['r3_n']} · 판정 대역 호출 {total['calls']}(LLM 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
