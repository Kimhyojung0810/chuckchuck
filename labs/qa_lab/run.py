"""
QA 실험대 (`labs/qa_lab`) — 브라우저 없이 **질문 생성(F-08)·판정(F-09)만** 골라 되돌려 보는 자리.

`labs/qa_call` 은 통화 화면까지 통째로 찍지만(40초, 파싱·개념·그래프까지 매번 과금) 답은 한 문장으로 고정이다.
여기서는 자료 한 벌을 **묶음(bundle)** 으로 한 번 얼려 두고, 그 위에서 질문만 다시 만들거나 판정만 여러 답으로 돌린다.
실 LLM 을 부른다 — .env 필요, 과금. mock 은 쓰지 않는다 (CLAUDE.md §2).

    .venv/bin/python labs/qa_lab/run.py snapshot  --name form --session 20260926T045837Z_023af58a   # 보관소 slide_doc → 개념·그래프
    .venv/bin/python labs/qa_lab/run.py snapshot  --name form --photos labs/qa_call/fixture_slide1.jpg labs/qa_call/fixture_slide2.jpg --bridge http://127.0.0.1:8799
    .venv/bin/python labs/qa_lab/run.py questions --bundle form [--track 5] [--no-papers] [--fresh-triage] [--bridge URL]
    .venv/bin/python labs/qa_lab/run.py judge     --bundle form --probe                 # 질문마다 골자·무관·(함정동의)·포기 4벌
    .venv/bin/python labs/qa_lab/run.py judge     --bundle form --q 1 --answer "…" --answer "…(2차)"
    .venv/bin/python labs/qa_lab/run.py judge     --bundle form --answers my_answers.json
    .venv/bin/python labs/qa_lab/run.py check     --bundle form                         # 데모값이 아니라 실제값인가
    .venv/bin/python labs/qa_lab/run.py show      --bundle form · list

`--bridge URL` 을 주면 떠 있는 브리지의 HTTP 경로(부스 화면과 같은 body)로 보내고, 없으면 chuckchuck 모듈을 직접 부른다.
묶음은 `labs/qa_lab/out/bundles/<name>/` (git 무시). 판정 기록은 그 안 `judgements/`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from chuckchuck.config import load_dotenv  # noqa: E402

load_dotenv()

from checks import (  # noqa: E402
    judgement_flags,
    slide_texts,
    probe_outcome,
    probe_plan,
    question_flags,
    real_value_checks,
)

OUT = HERE / "out" / "bundles"
SESSIONS_ROOT = Path(__import__("os").environ.get("DEMO_DATA_DIR", "").strip() or (ROOT / "var" / "data")) / "sessions"


# ---------------------------------------------------------------------------
# 묶음 읽고 쓰기
# ---------------------------------------------------------------------------

def bundle_dir(name: str) -> Path:
    return OUT / name


def read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(p: Path, data: dict | list) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load_bundle(name: str) -> dict:
    d = bundle_dir(name)
    if not (d / "meta.json").exists():
        raise SystemExit(f"묶음이 없어요: {d.relative_to(ROOT)} — 먼저 snapshot 을 만들어요.")
    b = {k: read_json(d / f"{k}.json") for k in ("meta", "slide_doc", "concept_doc", "graph", "papers", "triage", "question_doc")}
    b["judgements"] = []
    for p in sorted((d / "judgements").glob("*.json")):
        rows = read_json(p)
        if isinstance(rows, list):
            b["judgements"].extend(r.get("judgement") or {} for r in rows)
    return b


def stamp() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S")


def note(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# 브리지 호출 (부스 화면과 같은 body)
# ---------------------------------------------------------------------------

def post(base: str, path: str, body: dict, timeout: float = 180.0) -> dict:
    import requests

    r = requests.post(base.rstrip("/") + path, json=body, timeout=timeout)
    try:
        data = r.json()
    except ValueError:
        data = {"error": f"HTTP {r.status_code}", "message": r.text[:200]}
    if r.status_code >= 400 or (isinstance(data, dict) and data.get("error")):
        raise SystemExit(f"{path} 실패 HTTP {r.status_code}: {data.get('message') or data.get('error')}")
    return data


def parse_photos(base: str, photos: list[Path]) -> dict:
    """부스 `uploadShots` 와 같은 multipart — 사진 여러 장 = 한 자료."""
    import requests

    files = []
    for i, p in enumerate(photos):
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        files.append(("document", (f"shot_{i + 1}{p.suffix.lower()}", p.read_bytes(), mime)))
    r = requests.post(base.rstrip("/") + "/api/v1/parse", files=files, timeout=180)
    data = r.json()
    if r.status_code >= 400 or data.get("error"):
        raise SystemExit(f"parse 실패 HTTP {r.status_code}: {data.get('message') or data.get('error')}")
    return data


def find_session_slidedoc(sid: str) -> tuple[Path | None, dict | None]:
    hits = list(SESSIONS_ROOT.glob(f"*/*/*/{sid}/slide_doc.json"))
    if not hits:
        return None, None
    return hits[0], read_json(hits[0].parent / "manifest.json")


# ---------------------------------------------------------------------------
# snapshot — 자료 한 벌을 얼린다 (slide_doc → concept_doc → graph)
# ---------------------------------------------------------------------------

def cmd_snapshot(ns: argparse.Namespace) -> int:
    d = bundle_dir(ns.name)
    if (d / "meta.json").exists() and not ns.force:
        raise SystemExit(f"이미 있어요: {d.relative_to(ROOT)} — 덮어쓰려면 --force")
    context = {"situation": ns.situation, "duration_min": int(ns.duration)}
    meta: dict = {"name": ns.name, "created": stamp(), "context": context, "models": {}, "session_id": "", "source": ""}

    if ns.session:
        p, manifest = find_session_slidedoc(ns.session)
        if p is None:
            raise SystemExit(f"보관소에 {ns.session} 의 slide_doc 이 없어요 ({SESSIONS_ROOT.relative_to(ROOT)}). 24시간이 지나면 지워져요.")
        slide_doc = read_json(p) or {}
        meta["session_id"] = ns.session
        meta["source"] = f"session:{ns.session}"
        if manifest and manifest.get("context"):
            context = manifest["context"]
            meta["context"] = context
        note(f"보관소 slide_doc: {p.relative_to(ROOT)} ({len(slide_doc.get('slides') or [])}장)")
    elif ns.slidedoc:
        slide_doc = read_json(Path(ns.slidedoc)) or {}
        meta["source"] = "fixture" if "fixtures" in str(ns.slidedoc) else f"file:{ns.slidedoc}"
        note(f"slide_doc 파일: {ns.slidedoc}")
    elif ns.photos:
        if not ns.bridge:
            raise SystemExit("--photos 는 --bridge 가 필요해요 (부스와 같은 /api/v1/parse 경로를 탄다).")
        t0 = time.time()
        slide_doc = parse_photos(ns.bridge, [Path(x) for x in ns.photos])
        meta["session_id"] = str(slide_doc.get("session_id") or "")
        meta["source"] = f"photos:{len(ns.photos)}"
        note(f"parse {time.time() - t0:.1f}s · session {meta['session_id'] or '-'} · {len(slide_doc.get('slides') or [])}장")
    else:
        raise SystemExit("--session · --slidedoc · --photos 중 하나가 필요해요.")

    if not slide_doc.get("slides"):
        raise SystemExit("slide_doc 에 장이 없어요.")

    sid = meta["session_id"] or None
    t0 = time.time()
    if ns.bridge:
        concept_doc = post(ns.bridge, "/api/v1/concepts", {"slide_doc": slide_doc, "context": context, "session_id": sid})
        note(f"concepts(브리지) {time.time() - t0:.1f}s · model={concept_doc.get('model')}")
        t0 = time.time()
        graph = post(ns.bridge, "/api/v1/graph", {"concept_doc": concept_doc, "slide_doc": slide_doc, "context": context, "session_id": sid})
        note(f"graph(브리지) {time.time() - t0:.1f}s · nodes={len(graph.get('nodes') or [])}")
    else:
        from chuckchuck import build_graph, extract_concepts
        from chuckchuck.contracts import Context, SlideDoc

        sd = SlideDoc.from_dict(slide_doc)
        ctx = Context.from_dict(context)
        cd = extract_concepts(sd, ctx)
        concept_doc = cd.to_dict()
        note(f"concepts {time.time() - t0:.1f}s · model={cd.model}")
        t0 = time.time()
        g = build_graph(cd, ctx, slide_doc=sd)
        graph = g.to_dict()
        note(f"graph {time.time() - t0:.1f}s · nodes={len(g.nodes)}")

    meta["models"]["concepts"] = str(concept_doc.get("model") or "")
    if graph.get("model"):
        meta["models"]["graph"] = str(graph.get("model"))
    write_json(d / "slide_doc.json", slide_doc)
    write_json(d / "concept_doc.json", concept_doc)
    write_json(d / "graph.json", graph)
    write_json(d / "meta.json", meta)
    note(f"묶음 저장: {d.relative_to(ROOT)}  → 다음: questions --bundle {ns.name}")
    return 0


# ---------------------------------------------------------------------------
# questions — F-24 문헌(캐시) + F-08 1차(캐시) + 질문
# ---------------------------------------------------------------------------

def cmd_questions(ns: argparse.Namespace) -> int:
    b = load_bundle(ns.bundle)
    d = bundle_dir(ns.bundle)
    meta, graph, slide_doc = b["meta"], b["graph"], b["slide_doc"]
    context = meta.get("context") or {}
    track = str(ns.track)
    sid = meta.get("session_id") or None

    t0 = time.time()
    if ns.bridge:
        body = {"session_id": sid, "graph": graph, "alignment": None, "flow": None, "transcript": None,
                "context": context, "track": track}
        if ns.no_papers:
            body["papers"] = False
        doc = post(ns.bridge, "/api/v1/questions", body)
        papers = {"file_name": doc.get("file_name", ""), "refs": doc.get("papers") or [], "provider": "(브리지)", "note": ""}
        if not sid:
            note("주의: session_id 가 없어 브리지가 자료 본문 없이 질문을 만들었어요 (본문=-).")
        note(f"questions(브리지) {time.time() - t0:.1f}s · model={doc.get('model')} · 인용 문헌 {len(doc.get('papers') or [])}")
    else:
        from chuckchuck import build_papers, build_questions, triage_questions
        from chuckchuck.contracts import ConceptGraph, Context, PaperDoc, QaTriage, SlideDoc

        g = ConceptGraph.from_dict(graph)
        sd = SlideDoc.from_dict(slide_doc)
        ctx = Context.from_dict(context)

        papers = None
        if not ns.no_papers:
            if b.get("papers") and not ns.fresh_papers:
                papers = b["papers"]
                note(f"papers 캐시: provider={papers.get('provider')} · {len(papers.get('refs') or [])}편")
            else:
                try:
                    pd = build_papers(g, sd)
                    papers = pd.to_dict()
                    write_json(d / "papers.json", papers)
                    note(f"papers {time.time() - t0:.1f}s · provider={pd.provider} · {len(pd.refs)}편" + (f" · {pd.note}" if pd.note else ""))
                except Exception as e:  # noqa: BLE001 — 브리지와 같은 규율: 문헌 없이도 질문은 나온다
                    note(f"papers 실패, 문헌 없이: {type(e).__name__}: {e}")
        t0 = time.time()
        if b.get("triage") and not ns.fresh_triage:
            triage = QaTriage.from_dict(b["triage"])
            note("triage 캐시 (다시 돌리려면 --fresh-triage)")
        else:
            triage = triage_questions(g, None, None, ctx)
            write_json(d / "triage.json", triage.to_dict())
            note(f"triage {time.time() - t0:.1f}s · 후보 {len(triage.marks)}")
        t0 = time.time()
        qd = build_questions(g, triage, track=track, slidedoc=sd, context=ctx,
                             papers=PaperDoc.from_dict(papers) if papers else None)
        doc = qd.to_dict()
        note(f"questions {time.time() - t0:.1f}s · model={qd.model} · track={qd.track}")

    write_json(d / "question_doc.json", doc)
    meta.setdefault("models", {})["questions"] = str(doc.get("model") or "")
    write_json(d / "meta.json", meta)
    print_questions(doc, papers, slide_doc)
    return 0


def print_questions(doc: dict, papers: dict | None, slide_doc: dict | None = None) -> None:
    qs = doc.get("questions") or []
    texts = slide_texts(slide_doc)
    print(f"\n질문 {len(qs)}개 · track={doc.get('track')} · model={doc.get('model')}")
    for i, q in enumerate(qs, 1):
        flags = question_flags(q, papers, texts)
        slides = "·".join(str(n) for n in (q.get("slide_nos") or [])) or "-"
        print(f"\n[{i}] {q.get('label')}  (장 {slides} · {q.get('source')} · sev{q.get('severity')})  {' '.join(flags)}")
        print(f"    Q  {q.get('question')}")
        print(f"    골자 {q.get('answer_gist')}")
        if q.get("answer_gist_parts"):
            print(f"    요소 {' | '.join(q['answer_gist_parts'])}")
        if q.get("evidence_quote"):
            print(f"    인용 {q.get('evidence_slide_no')}장 «{q['evidence_quote'][:80]}»")
    bad = [i for i, q in enumerate(qs, 1) if any("!" in f for f in question_flags(q, papers, texts))]
    print(f"\n{'⚠ 화면에 그대로 나가면 안 되는 질문: ' + ', '.join(map(str, bad)) if bad else '✓ 말투·잘림·거짓 전제 표식 없음'}")


# ---------------------------------------------------------------------------
# judge — 답을 넣고 판정을 본다
# ---------------------------------------------------------------------------

def judge_one(ns: argparse.Namespace, b: dict, q: dict, answer: str, *, prior: list[str], history: list[dict],
              give_up: bool) -> dict:
    meta = b["meta"]
    if ns.bridge:
        sid = meta.get("session_id") or "flat"
        body = {"session_id": sid, "question_id": q.get("id"), "answer": answer, "history": history,
                "question": q, "give_up": give_up, "prior_answers": prior, "hints_shown": [],
                "graph": b["graph"], "context": meta.get("context") or {}}
        return post(ns.bridge, f"/api/v1/sessions/{sid}/qa/judge", body)
    from chuckchuck import judge_answer

    j = judge_answer(q, answer, graph=b["graph"], context=meta.get("context") or {}, slidedoc=b["slide_doc"],
                     prior_answers=prior, history=history, give_up=give_up)
    return j.to_dict()


def cmd_judge(ns: argparse.Namespace) -> int:
    b = load_bundle(ns.bundle)
    doc = b.get("question_doc")
    if not doc:
        raise SystemExit("question_doc 이 없어요 — 먼저 questions 를 돌려요.")
    qs = doc.get("questions") or []

    # 실행 계획: [(질문 번호, 이름, [답…], give_up, 기대)]
    plan: list[tuple[int, str, list[str], bool, str]] = []
    if ns.probe:
        for i, q in enumerate(qs, 1):
            if ns.q and i not in ns.q:
                continue
            for name, ans, expect in probe_plan(q):
                plan.append((i, name, [ans], name == "포기", expect))
    elif ns.answers:
        spec = read_json(Path(ns.answers))
        if not isinstance(spec, list):
            raise SystemExit("--answers 파일은 [{\"q\": 1, \"answers\": [\"…\"], \"give_up\": false, \"expect\": \"pass\"}] 꼴이에요.")
        for row in spec:
            plan.append((int(row["q"]), str(row.get("name") or f"답{len(plan) + 1}"), [str(a) for a in row.get("answers") or []],
                         bool(row.get("give_up")), str(row.get("expect") or "")))
    elif ns.q and (ns.answer or ns.give_up):
        for i in ns.q:
            plan.append((i, "손답", list(ns.answer or []), bool(ns.give_up), ""))
    else:
        raise SystemExit("--probe · --answers FILE · --q N --answer TEXT 중 하나가 필요해요.")

    records: list[dict] = []
    mismatches = 0
    for qno, name, answers, give_up, expect in plan:
        if not 1 <= qno <= len(qs):
            raise SystemExit(f"질문 번호 {qno} 는 없어요 (1~{len(qs)})")
        q = qs[qno - 1]
        prior: list[str] = []
        history: list[dict] = []
        rounds = answers or [""]
        for r, ans in enumerate(rounds, 1):
            t0 = time.time()
            j = judge_one(ns, b, q, ans, prior=prior, history=history, give_up=give_up and r == len(rounds))
            sec = time.time() - t0
            outcome = probe_outcome(j)
            ok = "" if not expect else ("✓" if outcome == expect else "✗")
            if expect and outcome != expect:
                mismatches += 1
            flags = judgement_flags(j)
            print(f"\n[{qno}] {q.get('label')} · {name} · {r}차 → {j.get('verdict')} {j.get('score')} ({outcome}{(' 기대 ' + expect + ' ' + ok) if expect else ''})"
                  f"  {sec:.1f}s  {' '.join(flags)}")
            print(f"    답  {ans[:90] or '(빈 답)'}")
            print(f"    react {j.get('react')}")
            if j.get("summary_sentence"):
                print(f"    총평 {j.get('summary_sentence')}")
            if j.get("missing_points"):
                print(f"    빠진 {' | '.join(j['missing_points'])}")
            if j.get("followup"):
                print(f"    되묻기 {j.get('followup')}")
            if j.get("explanation"):
                print(f"    해설 {j.get('explanation')[:160]}")
            records.append({"q": qno, "question": q.get("question"), "label": q.get("label"), "trap": bool(q.get("trap")),
                            "name": name, "round": r, "answer": ans, "give_up": give_up, "expect": expect,
                            "outcome": outcome, "sec": round(sec, 1), "flags": flags, "judgement": j})
            if ans:
                prior.append(ans)
            history.append({"질문": q.get("question"), "답변": ans, "판정": j.get("verdict") or "unknown",
                            "question_id": q.get("id"), "포기": give_up})

    out = bundle_dir(ns.bundle) / "judgements" / f"{stamp()}_{'probe' if ns.probe else 'answers'}.json"
    write_json(out, records)
    expected = sum(1 for r in records if r["expect"])
    print(f"\n판정 {len(records)}건 저장: {out.relative_to(ROOT)}"
          + (f" · 기대와 다른 것 {mismatches}/{expected}" if expected else ""))
    return 1 if mismatches else 0


# ---------------------------------------------------------------------------
# check · show · list
# ---------------------------------------------------------------------------

def cmd_check(ns: argparse.Namespace) -> int:
    b = load_bundle(ns.bundle)
    rows = real_value_checks(b)
    worst = "PASS"
    for grade, item, desc in rows:
        print(f"{grade:4s} {item:10s} {desc}")
        if grade == "FAIL" or (grade == "WARN" and worst == "PASS"):
            worst = grade
    print("\n" + {"PASS": "✓ 실제값이에요 — 샘플·mock 흔적 없음", "WARN": "△ 실제값이지만 확인할 것이 있어요",
                  "FAIL": "✗ 데모값 또는 빈 값이 섞여 있어요"}[worst])
    return 1 if worst == "FAIL" else 0


def cmd_show(ns: argparse.Namespace) -> int:
    b = load_bundle(ns.bundle)
    meta = b["meta"]
    print(json.dumps({k: meta.get(k) for k in ("name", "created", "source", "session_id", "context", "models")}, ensure_ascii=False, indent=1))
    print(f"slide_doc {len((b['slide_doc'] or {}).get('slides') or [])}장 · graph nodes {len((b['graph'] or {}).get('nodes') or [])}"
          f" · papers {len((b.get('papers') or {}).get('refs') or [])}편 · triage {'있음' if b.get('triage') else '없음'}"
          f" · 판정 기록 {len(b['judgements'])}건")
    if b.get("question_doc"):
        print_questions(b["question_doc"], b.get("papers"), b.get("slide_doc"))
    return 0


def cmd_list(ns: argparse.Namespace) -> int:
    if not OUT.exists():
        print("묶음이 없어요.")
        return 0
    for d in sorted(OUT.iterdir()):
        m = read_json(d / "meta.json") or {}
        n = len(list((d / "judgements").glob("*.json"))) if (d / "judgements").exists() else 0
        print(f"{d.name:20s} {m.get('created', '')}  {m.get('source', '')}  질문 {'있음' if (d / 'question_doc.json').exists() else '없음'}  판정파일 {n}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="labs/qa_lab/run.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot", help="자료 한 벌을 얼린다 (slide_doc → 개념 → 그래프)")
    s.add_argument("--name", required=True)
    s.add_argument("--session", help="보관소 세션 id (var/data/sessions 의 slide_doc)")
    s.add_argument("--slidedoc", help="SlideDoc JSON 파일")
    s.add_argument("--photos", nargs="*", help="사진 → 브리지 /api/v1/parse (--bridge 필요)")
    s.add_argument("--situation", default="school_project")
    s.add_argument("--duration", default="5")
    s.add_argument("--bridge", default=None)
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_snapshot)

    s = sub.add_parser("questions", help="F-24 문헌 + F-08 질문")
    s.add_argument("--bundle", required=True)
    s.add_argument("--track", default="5", choices=("1", "5", "10"))
    s.add_argument("--no-papers", action="store_true")
    s.add_argument("--fresh-papers", action="store_true")
    s.add_argument("--fresh-triage", action="store_true")
    s.add_argument("--bridge", default=None)
    s.set_defaults(fn=cmd_questions)

    s = sub.add_parser("judge", help="F-09 판정")
    s.add_argument("--bundle", required=True)
    s.add_argument("--probe", action="store_true", help="질문마다 골자·무관·(함정동의)·포기 답을 넣고 기대와 대조")
    s.add_argument("--answers", help="답 대본 JSON")
    s.add_argument("--q", type=int, action="append", help="질문 번호 (여러 번)")
    s.add_argument("--answer", action="append", help="답 (여러 번 주면 차수별)")
    s.add_argument("--give-up", action="store_true")
    s.add_argument("--bridge", default=None)
    s.set_defaults(fn=cmd_judge)

    s = sub.add_parser("check", help="데모값이 아니라 실제값인가")
    s.add_argument("--bundle", required=True)
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("show", help="묶음 요약과 질문 표식")
    s.add_argument("--bundle", required=True)
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("list", help="묶음 목록")
    s.set_defaults(fn=cmd_list)

    ns = ap.parse_args(argv)
    return ns.fn(ns)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
