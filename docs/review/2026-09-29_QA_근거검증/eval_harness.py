"""
QA 근거·힌트·판정 평가 하네스 (2026-09-29). 실 LLM 을 부른다 — 과금. mock 은 쓰지 않는다 (CLAUDE.md §2).

한 발표자료(SlideDoc, 선택 Transcript)에 대해 F-08 질문을 만들고, 질문마다
  1. 근거 추적 — 개념 노드 · 트랙 배합 자리(QA_TRACK_MIX) · 근거(source) · anchor 장 · 그 장 원문 · 골자 낱말이 자료에 있는가
  2. 힌트 — build_hint_ladder(판정 전) · 발판(_scaffold_judgement) · 판정 뒤 사다리 · 코칭(narrow) 되물음과 인용
  3. 판정 — (a) 골자 그대로 (b) 무관한 답 (c) 그럴듯한 오답 (d) 골자와 다른 말로 한 정답 (e) 「모르겠어요」 (+함정이면 (t) 전제 동의)
를 JSON 과 마크다운 표로 남긴다.

**다른 워크트리에 그대로 다시 돌릴 수 있게** 저장소 경로를 인자로 받는다 (그 저장소의 chuckchuck 코드로 돈다).
단계마다 결과를 out 폴더에 얼려 두고 다시 쓰므로, 같은 명령을 두 번 돌리면 LLM 을 다시 부르지 않는다.
새 기능 뒤 비교할 때는 그래프는 기준선 것을 쓰고(--reuse-graph) 질문부터 새로 만든다(--fresh questions).

    # 기준선 (이 워크트리)
    .venv/bin/python docs/review/2026-09-29_QA_근거검증/eval_harness.py --repo . --deck 수면 \
        --slidedoc /home/yehschuck/project/chuckchuck/docs/review/2026-09-28_QA_지엽성_자료/slidedoc_수면_세션.json \
        --transcript /home/yehschuck/project/chuckchuck/docs/review/2026-09-28_QA_지엽성_자료/transcript_수면_clova.json

    # 새 기능이 들어간 다른 워크트리에서, 같은 그래프로 질문부터 다시
    /path/to/wt/.venv/bin/python docs/review/2026-09-29_QA_근거검증/eval_harness.py --repo /path/to/wt --deck 수면 \
        --slidedoc … --transcript … --out /tmp/qa_eval_after \
        --reuse-graph docs/review/2026-09-29_QA_근거검증/out/수면 --fresh questions

    # 표만 다시 (LLM 0회)
    … eval_harness.py --repo . --deck 수면 --slidedoc … --stage report

단계 순서: graph < papers < align < triage < questions < probes < judge < report.
--fresh STAGE 는 그 단계와 뒤 단계를 새로 만든다. --stage STAGE 는 그 단계까지만 돈다.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGES = ("graph", "papers", "align", "triage", "questions", "probes", "judge", "report")

PROBE_UNRELATED = (
    "저희 팀은 지난 분기에 물류 창고 세 곳의 재고 회전율을 비교했고, "
    "동절기 배송 지연이 반품률을 끌어올린다는 결론을 얻었어요."
)
PROBE_AGREE = "네, 맞아요. 질문한 대로예요. 그 전제가 정확해요."
PROBE_GIVEUP = "모르겠어요"
#: 탐침 이름 → 기대 결과. pass=통과(good 또는 70↑) · fail=통과 못 함(wrong 또는 partial<70) · wrong · coach
PROBE_EXPECT = {"a": "pass", "b": "wrong", "c": "fail", "d": "pass", "e": "coach", "t": "wrong"}
PROBE_NAME = {"a": "골자그대로", "b": "무관한답", "c": "그럴듯한오답", "d": "다른말정답", "e": "모르겠어요", "t": "함정동의"}

PROBE_AUTHOR_SYSTEM = """너는 발표 Q&A 채점기를 시험하는 평가 도우미다. 질문마다 시험용 답 두 개를 쓴다.

- wrong: **그럴듯하지만 틀린 답**. 같은 발표의 낱말을 쓰되, 자료 본문과 어긋나는 주장을 한다
  (인과를 뒤집기, 수치·순서를 바꾸기, 자료가 부정한 것을 긍정하기). 무관한 이야기는 안 된다 — 같은 주제여야 한다.
  함정 질문(trap=true)이면 전제에 동의하는 답이 아니라, 전제는 건드리지 않고 다른 쪽으로 틀리게 답한다.
- paraphrase: **맞는 답을 골자와 다른 낱말로**. 골자의 뜻은 그대로 두고, 골자에 나온 명사·서술어를 가능한 한
  다른 말로 바꿔 말한다. 자료 본문에 있는 사실만 쓴다. 1~2문장, 해요체, 발표자가 말로 하듯이.
  함정 질문이면 잘못된 전제를 바로잡는 답이어야 한다.

반드시 JSON 객체 하나만: {"probes": [{"id": "질문 id", "wrong": "…", "paraphrase": "…"}]}
"""


# ---------------------------------------------------------------------------
# 준비
# ---------------------------------------------------------------------------

def setup_repo(repo: Path):
    repo = repo.resolve()
    os.chdir(repo)
    sys.path.insert(0, str(repo))
    import chuckchuck  # noqa: F401
    from chuckchuck.config import load_dotenv

    load_dotenv(repo / ".env")
    if str(os.environ.get("MOCK_EXTERNAL_APIS", "")).lower() in ("1", "true", "yes"):
        raise SystemExit("MOCK_EXTERNAL_APIS=true 예요 — 이 하네스는 실 API 로만 돌아요 (CLAUDE.md §2).")
    return repo


CALLS: list[dict] = []


def count_llm_calls() -> None:
    """모든 실제 제공자 complete() 를 감싸 호출 수를 센다 (Fallback 래퍼는 빼서 두 번 세지 않는다)."""
    from chuckchuck.providers.llm_base import LLMProvider

    seen = set()

    def walk(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from walk(sub)

    for cls in walk(LLMProvider):
        if cls in seen or "Fallback" in cls.__name__ or "Mock" in cls.__name__ or "complete" not in cls.__dict__:
            continue
        seen.add(cls)
        orig = cls.__dict__["complete"]

        def wrapped(self, *a, __orig=orig, __name=cls.__name__, **kw):
            t0 = time.time()
            try:
                return __orig(self, *a, **kw)
            finally:
                CALLS.append({"provider": __name, "stage": CURRENT_STAGE[0], "sec": round(time.time() - t0, 1)})

        cls.complete = wrapped


CURRENT_STAGE = ["-"]


def rj(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def wj(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def call_kw(fn, *args, **kw):
    """새 기능으로 인자가 바뀌어도 돌게 — 함수가 받는 키워드만 넘긴다."""
    params = inspect.signature(fn).parameters
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return fn(*args, **kw)
    return fn(*args, **{k: v for k, v in kw.items() if k in params})


def note(msg: str) -> None:
    print(msg, flush=True)


class Run:
    def __init__(self, ns):
        self.ns = ns
        self.out = Path(ns.out).resolve() / ns.deck
        self.fresh_from = STAGES.index(ns.fresh) if ns.fresh else len(STAGES)
        self.stop_at = STAGES.index(ns.stage)

    def cached(self, stage: str, path: Path):
        if STAGES.index(stage) >= self.fresh_from:
            return None
        return rj(path)

    def want(self, stage: str) -> bool:
        return STAGES.index(stage) <= self.stop_at


# ---------------------------------------------------------------------------
# 단계
# ---------------------------------------------------------------------------

def stage_graph(run: Run, slide_doc: dict, ctx: dict) -> tuple[dict, dict]:
    CURRENT_STAGE[0] = "graph"
    from chuckchuck import build_graph, extract_concepts
    from chuckchuck.contracts import Context, SlideDoc

    if run.ns.reuse_graph:
        src = Path(run.ns.reuse_graph)
        cd, g = rj(src / "concept_doc.json"), rj(src / "graph.json")
        if not (cd and g):
            raise SystemExit(f"--reuse-graph {src} 에 concept_doc.json·graph.json 이 없어요.")
        wj(run.out / "concept_doc.json", cd)
        wj(run.out / "graph.json", g)
        note(f"graph: {src} 것을 그대로 씀 · nodes={len(g.get('nodes') or [])}")
        return cd, g
    cd, g = run.cached("graph", run.out / "concept_doc.json"), run.cached("graph", run.out / "graph.json")
    if cd and g:
        note(f"graph 캐시 · nodes={len(g.get('nodes') or [])}")
        return cd, g
    sd, c = SlideDoc.from_dict(slide_doc), Context.from_dict(ctx)
    t0 = time.time()
    cdoc = extract_concepts(sd, c)
    gdoc = call_kw(build_graph, cdoc, c, slide_doc=sd)
    cd, g = cdoc.to_dict(), gdoc.to_dict()
    wj(run.out / "concept_doc.json", cd)
    wj(run.out / "graph.json", g)
    note(f"graph {time.time() - t0:.0f}s · nodes={len(g.get('nodes') or [])} · model={cd.get('model')}")
    return cd, g


def stage_papers(run: Run, graph: dict, slide_doc: dict) -> dict | None:
    CURRENT_STAGE[0] = "papers"
    if run.ns.no_papers:
        return None
    p = run.out / "papers.json"
    cached = run.cached("papers", p)
    if cached is not None:
        return cached or None
    from chuckchuck import build_papers

    try:
        pd = build_papers(graph, slide_doc).to_dict()
    except Exception as e:  # noqa: BLE001 — 브리지와 같은 규율: 문헌 없이도 질문은 나온다
        note(f"papers 실패, 문헌 없이: {type(e).__name__}: {e}")
        pd = {}
    wj(p, pd)
    note(f"papers · {len((pd or {}).get('refs') or [])}편")
    return pd or None


def stage_align(run: Run, graph: dict, concept_doc: dict, transcript: dict, ctx: dict) -> tuple[dict, dict, dict]:
    CURRENT_STAGE[0] = "align"
    p = run.out / "rec_inputs.json"
    cached = run.cached("align", p)
    if cached:
        return cached["alignment"], cached["flow"], cached["pace"]
    from chuckchuck import align_speech, analyze_pace, build_flow_diff

    al = align_speech(graph, transcript, ctx).to_dict()
    fl = build_flow_diff(graph, al).to_dict()
    pc = analyze_pace(transcript, ctx, concept_doc).to_dict()
    wj(p, {"alignment": al, "flow": fl, "pace": pc})
    note(f"align · items={len(al.get('items') or [])} · flow issues={len(fl.get('issues') or [])}")
    return al, fl, pc


def stage_triage(run: Run, path: str, graph, ctx, rec, transcript, tag: str = "") -> dict:
    CURRENT_STAGE[0] = "triage"
    p = run.out / f"triage_{path}{tag}.json"
    cached = run.cached("triage", p) if not tag else None
    if cached:
        return cached
    from chuckchuck import triage_questions

    al, fl, pc = rec if rec else (None, None, None)
    t = call_kw(triage_questions, graph, al, fl, ctx, transcript=transcript if rec else None, pace=pc).to_dict()
    wj(p, t)
    note(f"triage[{path}{tag}] · 후보 {len(t.get('marks') or [])}")
    return t


def stage_questions(run: Run, path: str, track: str, graph, triage, slide_doc, ctx, papers, rec, transcript,
                    tag: str = "") -> dict:
    CURRENT_STAGE[0] = "questions"
    p = run.out / f"questions_{path}_t{track}{tag}.json"
    cached = run.cached("questions", p) if not tag else None
    if cached:
        return cached
    from chuckchuck import build_questions

    al, fl, pc = rec if rec else (None, None, None)
    qd = call_kw(build_questions, graph, triage, track=track, alignment=al, flow=fl,
                 transcript=transcript if rec else None, slidedoc=slide_doc, context=ctx, papers=papers, pace=pc)
    doc = qd.to_dict()
    wj(p, doc)
    note(f"questions[{path} t{track}{tag}] · {len(doc.get('questions') or [])}개 · model={doc.get('model')}")
    return doc


def _qhash(q: dict) -> str:
    return hashlib.sha1(json.dumps([q.get("id"), q.get("question"), q.get("answer_gist")], ensure_ascii=False).encode()).hexdigest()[:10]


def _overlap(a: str, b: str) -> float:
    """a 의 내용 낱말 중 b 에도 있는 몫 (0~1). 다른 말 정답이 골자를 베꼈는지 본다."""
    from chuckchuck._match import norm_tokens

    ta = [t for t in norm_tokens(a or "") if len(t) >= 2]
    tb = set(t for t in norm_tokens(b or "") if len(t) >= 2)
    return sum(1 for t in ta if t in tb) / len(ta) if ta else 1.0


PARAPHRASE_MAX_OVERLAP = 0.5


def _author(todo: list[dict], slide_texts: dict[int, str], retry_note: str = "") -> dict[str, dict]:
    from chuckchuck._json_text import extract_json_object
    from chuckchuck.providers.llm_impl import get_llm

    lines = []
    for q in todo:
        body = " / ".join(slide_texts.get(n, "")[:500] for n in q.get("slide_nos") or [])
        lines += [f"- id: {q['id']}", f"  trap: {str(bool(q.get('trap'))).lower()}", f"  질문: {q.get('question')}",
                  f"  골자: {q.get('answer_gist')}", f"  자료 본문: {body}"]
    raw = get_llm().complete(system=PROBE_AUTHOR_SYSTEM + retry_note, user="\n".join(lines), temperature=0.5,
                             max_tokens=3000, json_mode=True)
    data = extract_json_object(raw)
    return {str(r.get("id")): r for r in data.get("probes") or [] if isinstance(r, dict)}


def stage_probes(run: Run, key: str, qdoc: dict, slide_texts: dict[int, str]) -> dict:
    """
    (c) 그럴듯한 오답 · (d) 다른 말 정답을 질문 묶음마다 LLM 한 번으로 쓴다. 질문 문장이 같으면 다시 쓰지 않는다.
    다른 말 정답이 골자 낱말을 절반 넘게 베꼈으면 그 질문만 한 번 더 쓰게 한다 (09-29 첫 실행: 셋 다 골자를 그대로 베꼈다).
    """
    CURRENT_STAGE[0] = "probes"
    p = run.out / f"probes_{key}.json"
    have = run.cached("probes", p) or {}
    qs = qdoc.get("questions") or []
    # 사람이 쓴 탐침이 먼저다 — 자료 원문만 보고 쓴 오답·다른 말 정답 (probes_manual.json · 개념 id 로 잇는다)
    manual = (rj(Path(run.ns.probe_file)) or {}).get(run.ns.deck, {}) if run.ns.probe_file else {}
    for q in qs:
        m = manual.get(f"{key}:{q['node_id']}") or manual.get(q["node_id"])
        if m:
            have[_qhash(q)] = {"id": q["id"], "wrong": m.get("wrong", ""), "paraphrase": m.get("paraphrase", ""),
                               "paraphrase_overlap": round(_overlap(m.get("paraphrase", ""), q.get("answer_gist", "")), 2),
                               "author": "manual", "for_question": m.get("for_question", "")}
    todo = [q for q in qs if _qhash(q) not in have
            or (have[_qhash(q)].get("author") != "manual" and _overlap(have[_qhash(q)].get("paraphrase", ""), q.get("answer_gist", "")) > PARAPHRASE_MAX_OVERLAP)]
    if not todo:
        wj(p, have)
        return have
    by_id = _author(todo, slide_texts)
    copied = [q for q in todo if _overlap((by_id.get(q["id"]) or {}).get("paraphrase", ""), q.get("answer_gist", "")) > PARAPHRASE_MAX_OVERLAP]
    if copied:
        note_ = ("\n\n[재요청] paraphrase 가 골자를 거의 그대로 베꼈다. 골자에 나온 낱말을 **최대한 쓰지 말고** 같은 뜻을 "
                 "발표자가 즉석에서 말하듯 다른 표현으로 다시 써라. 예: '곱으로 정의' → '셋을 곱한 값', '유발해' → '일으켜서'.")
        by_id.update({k: v for k, v in _author(copied, slide_texts, note_).items()})
    for q in todo:
        r = by_id.get(q["id"]) or {}
        para = str(r.get("paraphrase") or "")
        have[_qhash(q)] = {"id": q["id"], "wrong": str(r.get("wrong") or ""), "paraphrase": para,
                           "paraphrase_overlap": round(_overlap(para, q.get("answer_gist", "")), 2)}
    wj(p, have)
    note(f"probes[{key}] · {len(todo)}개 새로 씀 · 베낌 재요청 {len(copied)}")
    return have


def probe_outcome(j: dict) -> str:
    if j.get("coach_stage"):
        return "coach"
    v = str(j.get("verdict") or "")
    s = int(j.get("score") or 0)
    if v == "good" or s >= 70:
        return "pass"
    if v == "wrong":
        return "wrong"
    return "partial"


def matches(expect: str, outcome: str) -> bool:
    if expect == "fail":
        return outcome in ("wrong", "partial")
    return expect == outcome


def stage_judge(run: Run, key: str, qdoc: dict, letters: str, probes: dict, graph, slide_doc, ctx, rec, transcript,
                only_nodes: set[str] | None = None) -> list[dict]:
    CURRENT_STAGE[0] = "judge"
    p = run.out / f"judgements_{key}.json"
    prev = {(r["qhash"], r["probe"]): r for r in (run.cached("judge", p) or []) if r["probe"] not in run.ns.redo}
    from chuckchuck import judge_answer

    al = rec[0] if rec else None
    rows: list[dict] = []
    for i, q in enumerate(qdoc.get("questions") or [], 1):
        h = _qhash(q)
        use = letters if (only_nodes is None or q["node_id"] not in only_nodes) else ""
        pr = probes.get(h) or {}
        answers = {"a": q.get("answer_gist") or "", "b": PROBE_UNRELATED, "c": pr.get("wrong") or "",
                   "d": pr.get("paraphrase") or "", "e": PROBE_GIVEUP, "t": PROBE_AGREE}
        for L in use + ("t" if q.get("trap") and use else ""):
            ans = answers[L]
            if not ans:
                continue
            if (h, L) in prev and prev[(h, L)]["answer"] == ans:
                rows.append(prev[(h, L)])
                continue
            t0 = time.time()
            j = call_kw(judge_answer, q, ans, graph=graph, alignment=al, transcript=transcript if rec else None,
                        context=ctx, slidedoc=slide_doc, give_up=(L == "e")).to_dict()
            out = probe_outcome(j)
            rows.append({"q": i, "qid": q["id"], "qhash": h, "probe": L, "name": PROBE_NAME[L], "answer": ans,
                         "expect": PROBE_EXPECT[L], "outcome": out, "ok": matches(PROBE_EXPECT[L], out),
                         "sec": round(time.time() - t0, 1), "judgement": j})
            note(f"  [{key} Q{i}] {PROBE_NAME[L]} → {j.get('verdict')} {j.get('score')} ({out}) {'✓' if rows[-1]['ok'] else '✗'}")
    wj(p, rows)
    return rows


# ---------------------------------------------------------------------------
# 추적 — LLM 없이
# ---------------------------------------------------------------------------

def trace_questions(qdoc: dict, triage: dict, graph: dict, slide_doc: dict, transcript: dict | None, papers) -> list[dict]:
    from chuckchuck import build_hint_ladder
    from chuckchuck._evidence import clean_slide_text
    from chuckchuck._match import norm_tokens
    from chuckchuck.contracts import ConceptGraph, Question, Transcript
    import chuckchuck.f08_questions as f08
    import chuckchuck.f09_judge as f09

    g = ConceptGraph.from_dict(graph)
    tr = Transcript.from_dict(transcript) if transcript else None
    texts = {s["slide_no"]: clean_slide_text(s.get("raw_text") or "") for s in slide_doc.get("slides") or []}
    deck_all = " ".join(texts.values())
    speech_all = tr.full_text if tr is not None else ""
    marks = {m["node_id"]: m for m in triage.get("marks") or []}
    track = str(qdoc.get("track"))

    # 배합 자리: build_questions 와 같은 _mixed_order 로 다시 낸다.
    plan = f08.QA_TRACK_MIX.get(track) or ()
    depth_of = {n.id: n.depth for n in g.nodes}
    from chuckchuck.contracts import TriageMark

    tm = [TriageMark.from_dict(m) for m in triage.get("marks") or [] if m.get("node_id") in depth_of or str(m.get("node_id", "")).startswith("extra:")]
    ordered = f08._mixed_order(sorted(tm, key=lambda m: (m.rank, m.node_id)), track, depth_of, set())
    slot_of: dict[str, str] = {}
    for idx, m in enumerate(ordered):
        if idx < len(plan):
            fits = f08._slot_fits(plan[idx], m, depth_of, set())
            slot_of[m.node_id] = plan[idx] + ("" if fits else "(맞는 개념 없음→순위)")
        else:
            slot_of[m.node_id] = f"여분#{idx - len(plan) + 1}"

    def toks(s: str) -> list[str]:
        return [t for t in norm_tokens(s or "") if len(t) >= 2]

    def found(t: str, hay: set[str]) -> bool:
        return t in hay or any(h.startswith(t) or t.startswith(h) for h in hay if len(h) >= 2 and len(t) >= 2 and (h[:2] == t[:2]))

    deck_set = set(toks(deck_all))
    speech_set = set(toks(speech_all))
    out = []
    for i, qd in enumerate(qdoc.get("questions") or [], 1):
        q = Question.from_dict(qd)
        node = g.node(q.node_id)
        m = marks.get(q.node_id, {})
        anchor_txt = {n: texts.get(n, "") for n in q.slide_nos}
        anchor_set = set(toks(" ".join(anchor_txt.values())))
        gist_t = toks(q.answer_gist)
        gist_out_anchor = [t for t in gist_t if not found(t, anchor_set)]
        gist_out_deck = [t for t in gist_t if not found(t, deck_set) and not found(t, speech_set)]
        q_t = toks(q.question)
        quote_t = set(toks(q.evidence_quote))
        q_quote_overlap = sorted({t for t in q_t if found(t, quote_t)})
        numbers = []
        try:
            from chuckchuck._speech import ungrounded_numbers

            srcs = [deck_all, speech_all] + [str(r.get("abstract") or "") + " " + str(r.get("title") or "") for r in ((papers or {}).get("refs") or [])]
            numbers = ungrounded_numbers(q.answer_gist + " " + q.question, srcs)
        except Exception:  # noqa: BLE001
            pass
        undercut = f08._self_undercut(q.question) if hasattr(f08, "_self_undercut") else ""
        scaffold = f09._scaffold_judgement(q, g) if hasattr(f09, "_scaffold_judgement") else None
        flags = []
        if gist_out_deck:
            flags.append(f"골자낱말_자료·발화밖:{','.join(gist_out_deck[:6])}")
        if q.evidence_quote and q.evidence_slide_no not in q.slide_nos:
            flags.append("인용장≠근거장")
        if q.evidence_quote and not q_quote_overlap:
            flags.append("인용-질문 겹침0")
        if not q.evidence_quote:
            flags.append("인용없음")
        if numbers:
            flags.append(f"자료밖숫자:{','.join(numbers)}")
        if undercut:
            flags.append(f"자기모순({undercut})")
        if q.paper_ids:
            flags.append(f"문헌인용:{','.join(q.paper_ids)}")
        if q.trap:
            flags.append("함정")
        out.append({
            "i": i, "id": q.id, "node_id": q.node_id, "label": q.label, "question": q.question, "why": q.why,
            "hint": q.hint, "answer_gist": q.answer_gist, "answer_gist_parts": q.answer_gist_parts, "trap": q.trap,
            "source": q.source, "rank": m.get("rank"), "angle": m.get("angle"), "severity": q.severity,
            "slot": slot_of.get(q.node_id, "?"), "depth": node.depth if node else None,
            "path": [n.label for n in g.path_of(q.node_id)] if node else [],
            "node_summary": node.summary if node else "", "node_slide_nos": node.slide_nos if node else [],
            "anchors": q.slide_nos, "anchor_text": {str(k): v for k, v in anchor_txt.items()},
            "evidence_slide_no": q.evidence_slide_no, "evidence_quote": q.evidence_quote, "speech_quote": q.speech_quote,
            "quote_question_overlap": q_quote_overlap, "gist_tokens_outside_anchor": gist_out_anchor,
            "gist_tokens_outside_deck_speech": gist_out_deck, "ungrounded_numbers": numbers, "self_undercut": undercut,
            "ladder_before_answer": build_hint_ladder(q),
            "scaffold": ({"followup": scaffold.followup, "choices": scaffold.choices} if scaffold else None),
            "paper_ids": q.paper_ids, "flags": flags,
            "extra_fields": {k: v for k, v in qd.items() if k not in {
                "id", "node_id", "label", "question", "why", "hint", "severity", "trap", "source", "slide_nos",
                "doc_weight", "answer_gist", "answer_gist_parts", "evidence_slide_no", "evidence_quote",
                "speech_quote", "paper_ids", "hints"} and v not in (None, "", [], {})},
        })
    return out


# ---------------------------------------------------------------------------
# 표
# ---------------------------------------------------------------------------

def _cell(s: str, n: int = 160) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).replace("|", "\\|")
    return s if len(s) <= n else s[: n - 1] + "…"


def table(key: str, traced: list[dict], judg: list[dict]) -> str:
    by_q: dict[int, dict[str, dict]] = {}
    for r in judg:
        by_q.setdefault(r["q"], {})[r["probe"]] = r
    lines = [f"### {key}", "",
             "| # | 질문 | 개념 · 자리 · 근거 | 근거 장 원문(발췌) | 골자 | 자동 표식 | 힌트 인용 · 사다리 | 판정 a·b·c·d·e(·t) |",
             "|---|---|---|---|---|---|---|---|"]
    for t in traced:
        where = f"**{t['label']}** (깊이 {t['depth']}) · {t['slot']} · {t['source']} · 순위 {t['rank']}" + (" · 함정" if t["trap"] else "")
        src = " ".join(f"[{k}장] {_cell(v, 140)}" for k, v in t["anchor_text"].items())
        hint = (f"{t['evidence_slide_no']}장 «{_cell(t['evidence_quote'], 90)}» (질문과 겹침: {','.join(t['quote_question_overlap']) or '없음'})"
                if t["evidence_quote"] else "(인용 없음)")
        hint += f" · 사다리 {len(t['ladder_before_answer'])}칸"
        js = []
        for L in "abcdet":
            r = by_q.get(t["i"], {}).get(L)
            if r:
                j = r["judgement"]
                mark = "✓" if r["ok"] else "✗"
                js.append(f"{L}:{j.get('verdict')}{'' if r['outcome'] == 'coach' else ' ' + str(j.get('score'))}{mark}")
        lines.append(f"| {t['i']} | {_cell(t['question'], 200)} | {where} | {src} | {_cell(t['answer_gist'], 160)} | "
                     f"{_cell(' · '.join(t['flags']), 120) or '-'} | {hint} | {' '.join(js) or '-'} |")
    return "\n".join(lines) + "\n"


def write_lab_bundle(repo: Path, deck: str, key: str, meta: dict, slide_doc, concept_doc, graph, papers, triage, qdoc,
                     judg: list[dict]) -> None:
    """labs/qa_lab 묶음 꼴로도 남긴다 — `run.py check|show --bundle eval_<덱>_<키>` 로 실험대 표식을 LLM 없이 본다."""
    d = repo / "labs" / "qa_lab" / "out" / "bundles" / f"eval_{deck}_{key}"
    wj(d / "meta.json", {"name": d.name, "created": meta["started"], "context": meta["context"],
                         "models": {"concepts": concept_doc.get("model", ""), "graph": graph.get("model", ""),
                                    "questions": qdoc.get("model", "")},
                         "session_id": "", "source": f"file:{meta['slidedoc']}"})
    for name, data in (("slide_doc", slide_doc), ("concept_doc", concept_doc), ("graph", graph),
                       ("papers", papers or {}), ("triage", triage), ("question_doc", qdoc)):
        wj(d / f"{name}.json", data)
    if judg:
        wj(d / "judgements" / "eval_probe.json", [{"judgement": r["judgement"]} for r in judg])


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="chuckchuck 코드가 있는 저장소(워크트리) 루트")
    ap.add_argument("--deck", required=True, help="이름 (out 하위 폴더)")
    ap.add_argument("--slidedoc", required=True)
    ap.add_argument("--transcript", default=None, help="있으면 녹음 경로(rec)도 돈다")
    ap.add_argument("--situation", default="학교 프로젝트 (교수 대상)")
    ap.add_argument("--duration", type=int, default=10)
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--paths", default="deck,rec", help="deck(자료만) · rec(녹음 포함)")
    ap.add_argument("--tracks", default="5,10")
    ap.add_argument("--probes", default="deck/5:abcde,deck/10:a,rec/5:a",
                    help="경로/트랙별 탐침 글자. a 골자 · b 무관 · c 그럴듯한오답 · d 다른말정답 · e 모르겠어요 (함정이면 t 자동). "
                         "둘째 트랙부터는 앞 트랙에서 이미 판정한 개념을 건너뛴다")
    ap.add_argument("--probe-file", default=str(HERE / "probes_manual.json"),
                    help="사람이 쓴 (c)(d) 탐침 {덱: {\"경로_t트랙:개념id\" 또는 \"개념id\": {wrong, paraphrase}}}. 없는 개념만 LLM 이 쓴다")
    ap.add_argument("--redo", default="", help="이 탐침 글자의 판정 캐시만 버리고 다시 (예: d)")
    ap.add_argument("--reuse-graph", default=None, help="concept_doc.json·graph.json 을 가져올 폴더 (비교용)")
    ap.add_argument("--no-papers", action="store_true")
    ap.add_argument("--fresh", choices=STAGES, default=None)
    ap.add_argument("--stage", choices=STAGES, default="report", help="이 단계까지만")
    ap.add_argument("--variance", type=int, default=0, help="자료만·5분 트랙 triage+질문을 N번 더 (분산 확인용, 표는 안 만든다)")
    ns = ap.parse_args(argv)

    slidedoc_path, transcript_path = Path(ns.slidedoc).resolve(), Path(ns.transcript).resolve() if ns.transcript else None
    out_abs = Path(ns.out).resolve()
    ns.out = str(out_abs)
    if ns.reuse_graph:
        ns.reuse_graph = str(Path(ns.reuse_graph).resolve())
    if ns.probe_file:
        ns.probe_file = str(Path(ns.probe_file).resolve())
    repo = setup_repo(Path(ns.repo))
    count_llm_calls()
    run = Run(ns)
    run.out.mkdir(parents=True, exist_ok=True)

    slide_doc = rj(slidedoc_path)
    transcript = rj(transcript_path) if transcript_path else None
    ctx = {"situation": ns.situation, "duration_min": ns.duration}
    head = __import__("subprocess").run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    meta = {"repo": str(repo), "head": head, "deck": ns.deck, "slidedoc": str(slidedoc_path),
            "transcript": str(transcript_path or ""), "context": ctx, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}

    concept_doc, graph = stage_graph(run, slide_doc, ctx)
    papers = stage_papers(run, graph, slide_doc) if run.want("papers") else None
    paths = [p for p in ns.paths.split(",") if p and (p != "rec" or transcript)]
    rec = stage_align(run, graph, concept_doc, transcript, ctx) if ("rec" in paths and run.want("align")) else None
    texts = {s["slide_no"]: s.get("raw_text") or "" for s in slide_doc.get("slides") or []}
    from chuckchuck._evidence import clean_slide_text

    clean = {k: clean_slide_text(v) for k, v in texts.items()}
    probe_spec = dict(x.split(":") for x in ns.probes.split(",") if ":" in x)

    report = [f"# QA 근거검증 자동 표 — {ns.deck}", "",
              f"저장소 `{repo}` @ `{head}` · 자료 `{slidedoc_path.name}` · 전사 `{transcript_path.name if transcript_path else '-'}`", ""]
    summary = {"meta": meta, "runs": {}}
    for path in paths:
        if not run.want("triage"):
            break
        prec = rec if path == "rec" else None
        triage = stage_triage(run, path, graph, ctx, prec, transcript)
        judged_nodes: set[str] = set()
        for track in ns.tracks.split(","):
            if not run.want("questions"):
                break
            key = f"{path}_t{track}"
            qdoc = stage_questions(run, path, track, graph, triage, slide_doc, ctx, papers, prec, transcript)
            traced = trace_questions(qdoc, triage, graph, slide_doc, transcript if path == "rec" else None, papers)
            judg: list[dict] = []
            letters = probe_spec.get(f"{path}/{track}", "")
            if letters and run.want("probes"):
                probes = stage_probes(run, key, qdoc, clean) if set(letters) & {"c", "d"} else {}
                if run.want("judge"):
                    skip = judged_nodes if track != ns.tracks.split(",")[0] else None
                    judg = stage_judge(run, key, qdoc, letters, probes, graph, slide_doc, ctx, prec, transcript, skip)
                    judged_nodes |= {r_["node_id"] for r_ in traced if any(j["qid"] == r_["id"] for j in judg)}
            # 판정 뒤 사다리(4단)·코칭 되물음을 추적에 붙인다
            for t in traced:
                for r in judg:
                    if r["qid"] != t["id"]:
                        continue
                    j = r["judgement"]
                    t.setdefault("after", {})[r["probe"]] = {
                        "verdict": j.get("verdict"), "score": j.get("score"), "passed": j.get("passed"),
                        "react": j.get("react"), "missing_points": j.get("missing_points"), "followup": j.get("followup"),
                        "coach_stage": j.get("coach_stage"), "choices": j.get("choices"), "hints": j.get("hints"),
                        "explanation": j.get("explanation"), "model": j.get("model")}
            wj(run.out / f"trace_{key}.json", traced)
            if path == "deck":
                write_lab_bundle(repo, ns.deck, key, meta, slide_doc, concept_doc, graph, papers, triage, qdoc, judg)
            report.append(table(key, traced, judg))
            summary["runs"][key] = {
                "questions": len(traced), "flags": {t["i"]: t["flags"] for t in traced},
                "probe_ok": sum(1 for r in judg if r["ok"]), "probe_total": len(judg),
                "probe_miss": [f"Q{r['q']}{r['probe']}:{r['outcome']}" for r in judg if not r["ok"]]}

    for n in range(ns.variance):
        tri = stage_triage(run, "deck", graph, ctx, None, None, tag=f"_var{n + 1}")
        qd = stage_questions(run, "deck", "5", graph, tri, slide_doc, ctx, papers, None, None, tag=f"_var{n + 1}")
        summary.setdefault("variance", []).append([(q["label"], q["source"], q["question"]) for q in qd.get("questions") or []])

    meta["llm_calls_this_run"] = len(CALLS)
    meta["llm_calls_by_stage"] = {s: sum(1 for c in CALLS if c["stage"] == s) for s in {c["stage"] for c in CALLS}}
    wj(run.out / "summary.json", summary)
    log = rj(run.out / "calls_log.json") or []
    log.append({"at": meta["started"], "head": head, "calls": meta["llm_calls_by_stage"], "total": len(CALLS)})
    wj(run.out / "calls_log.json", log)
    (run.out / "tables.md").write_text("\n".join(report), encoding="utf-8")
    note(f"\nLLM 호출 {len(CALLS)}회 {meta['llm_calls_by_stage']} · 표: {run.out / 'tables.md'}")
    for k, v in summary["runs"].items():
        note(f"  {k}: 질문 {v['questions']} · 탐침 기대대로 {v['probe_ok']}/{v['probe_total']} {' '.join(v['probe_miss'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
