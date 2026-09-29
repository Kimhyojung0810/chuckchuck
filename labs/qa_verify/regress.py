"""
회귀 사례 실행기 — regression/cases.json 의 사례마다 **대상 저장소의 공개 함수**를 불러 기대와 대조한다. 자식 프로세스
(target_probe.py) 안에서 돈다 — `chuckchuck` 은 대상의 것이다. LLM 은 부르지 않는다(F-08 은 정해 둔 응답 ScriptedLLM).

검사 종류(kind) — 규칙 코드는 여기에만 있고, 무엇을 넣고 무엇을 기대하는지는 사례 데이터에 있다.
- units_no_midword_start  원문에서 낱말 한가운데 꺾인 줄을 잣대가 찾고, 대상 `_evidence.slide_units`·`best_quote` 가
                          그 조각으로 시작하는 인용을 내지 않는지
- best_quote_slide        대상 `_evidence.best_quote` 가 기대한 장·글을 고르는지
- contrast_choice         대상 `_evidence.mask_gist` · `f09_judge._narrow_followup` 의 보기 쌍이 (세운 쪽, 부정한 쪽)인지,
                          세는 단위가 보기로 안 나오는지 (덱의 모든 「X 아니라 Y」 줄도 훑는다)
- f08_scripted            대상 `build_questions` 에 정해 둔 LLM 응답(질문·골자)을 넣고 나온 골자·질문을 검사
- judge_scripted          대상 `judge_answer` 에 실측의 LLM 판정을 넣고 코드가 낸 등급·결손·되물음·react 를 검사 (09-30 WP-J3)
- stuck_ladder            「모르겠어요」 첫 단계 보기 · 발판 · 힌트 빈칸 · 칩 답 판정(LLM 없이)을 검사 (09-30 WP-J3)
"""

from __future__ import annotations

import inspect
import json
import re
import shutil
from pathlib import Path

from . import common as C
from . import tags as TG
from . import textkit as T

CASES = C.HERE / "regression" / "cases.json"


# ---------------------------------------------------------------------------
# 자료 읽기 — 원본 → 얼린 사본 → inline
# ---------------------------------------------------------------------------

def _inline_doc(inline: dict) -> dict:
    slides = []
    for s in inline.get("slides") or []:
        text = s.get("text", "")
        slides.append({"slide_no": int(s["slide_no"]), "title": text.split("\n")[0][:40], "raw_text": text,
                       "blocks": [{"category": "paragraph", "text": line} for line in text.split("\n") if line.strip()]})
    return {"file_name": "inline.pptx", "total_slides": len(slides), "slides": slides}


def load_source(case: dict, all_cases: dict[str, dict]) -> tuple[dict | None, str]:
    """(slide_doc, 어디서 왔나). 못 찾으면 (None, 까닭)."""
    src = case.get("source") or {}
    doc, where = None, ""
    if src.get("file"):
        base = C.MAIN_CHECKOUT if src.get("base", "main") == "main" else C.HARNESS_ROOT
        path = base / src["file"]
        frozen = C.FROZEN / f"{case['id']}.json"
        if path.exists():
            doc, where = C.read_json(path), f"file:{src['file']}"
            try:
                frozen.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, frozen)
            except OSError:
                pass
        elif frozen.exists():
            doc, where = C.read_json(frozen), f"frozen:{frozen.name}"
    if doc is None:
        inline = src.get("inline")
        if inline is None and src.get("inline_from"):
            inline = ((all_cases.get(src["inline_from"]) or {}).get("source") or {}).get("inline")
        if inline:
            doc, where = _inline_doc(inline), "inline"
    if doc is None:
        return None, "원본·얼린 사본·inline 이 다 없음"
    want = src.get("slides")
    if want:
        doc = dict(doc, slides=[s for s in doc.get("slides") or [] if int(s.get("slide_no") or 0) in want])
    return doc, where


def _raw(slide: dict) -> str:
    raw = slide.get("raw_text")
    if raw is None:
        raw = "\n".join(str(b.get("text", "")) for b in slide.get("blocks") or [])
    return raw or ""


# ---------------------------------------------------------------------------
# 검사 종류
# ---------------------------------------------------------------------------

def check_units_no_midword_start(doc: dict, args: dict) -> tuple[str, str, dict]:
    from chuckchuck._evidence import best_quote, slide_units

    wraps, bad = [], []
    for s in doc.get("slides") or []:
        raw = _raw(s)
        heads = TG.wrap_points(raw)
        if not heads:
            continue
        units = slide_units(raw)
        for head in heads:
            wraps.append(head[:20])
            frag = T.squash(head)[:6]
            starts = [u for u in units if T.squash(u).startswith(frag)]
            words = " ".join(T.tokens(head)[:4])
            _, quote = best_quote("", "", [(int(s["slide_no"]), raw)], f"{words}에 대해 설명해 주세요")
            if starts:
                bad.append(f"인용 후보가 조각으로 시작: «{starts[0][:40]}»")
            if quote and T.squash(quote).startswith(frag):
                bad.append(f"힌트 인용이 조각으로 시작: «{quote[:40]}»")
    if len(wraps) < int(args.get("min_wraps", 1)):
        return "skip", f"폭 꺾임을 못 찾음 (자료가 바뀌었나) — {len(wraps)}곳", {"wraps": wraps}
    if bad:
        return "fail", "; ".join(bad[:3]), {"wraps": wraps, "bad": bad}
    return "pass", f"꺾인 곳 {len(wraps)}곳 — 조각으로 시작하는 인용 없음", {"wraps": wraps}


def check_best_quote_slide(doc: dict, args: dict) -> tuple[str, str, dict]:
    from chuckchuck._evidence import best_quote

    texts = [(int(s["slide_no"]), _raw(s)) for s in doc.get("slides") or []]
    no, quote = best_quote(args.get("label", ""), args.get("summary", ""), texts, args.get("question", ""))
    obs = {"slide_no": no, "quote": quote}
    if no != args.get("expect_slide"):
        return "fail", f"{no}장 «{quote[:60]}» — 기대 {args.get('expect_slide')}장", obs
    miss = [x for x in args.get("quote_contains") or [] if x not in quote]
    bad = [x for x in args.get("quote_forbid") or [] if x in quote]
    if miss or bad:
        return "fail", f"«{quote[:60]}» — 빠짐 {miss} · 금지 {bad}", obs
    return "pass", f"{no}장 «{quote[:60]}»", obs


def _question(label: str, question: str, gist: str, quote: str, slide_no: int):
    from chuckchuck.contracts import Question

    return Question(id="qv-case", node_id="qv-node", label=label, question=question or f"{label}는 무엇인가요?",
                    answer_gist=gist, evidence_slide_no=slide_no, evidence_quote=quote)


def _narrow(q, deck_text: str) -> list[str]:
    from chuckchuck.f09_judge import _narrow_followup

    _, choices = _narrow_followup({}, q, None, deck_text)
    return [str(c) for c in choices]


def check_contrast_choice(doc: dict, args: dict) -> tuple[str, str, dict]:
    from chuckchuck._evidence import mask_gist

    deck_text = " ".join(_raw(s).replace("\n", " ") for s in doc.get("slides") or [])
    quote, affirmed, negated = args["quote"], args["affirmed"], args["negated"]
    forbid = set(args.get("forbid_choices") or [])
    problems: list[str] = []
    _, answer, distractor = mask_gist(args.get("gist", quote), args.get("label", ""), list(args.get("pool") or []),
                                      quote=quote, deck_text=deck_text)
    if affirmed not in (answer or ""):
        problems.append(f"빈칸 정답 「{answer}」 ≠ 세운 쪽 「{affirmed}」")
    if negated not in (distractor or ""):
        problems.append(f"빈칸 오답 「{distractor}」 ≠ 부정한 쪽 「{negated}」")
    choices = _narrow(_question(args.get("label", ""), "", args.get("gist", quote), quote, 0), deck_text)
    if not any(affirmed in c for c in choices) or not any(negated in c for c in choices):
        problems.append(f"보기 {choices} 에 (세운 쪽 「{affirmed}」, 부정한 쪽 「{negated}」) 가 없음")
    if forbid & set(choices):
        problems.append(f"금지 보기 {sorted(forbid & set(choices))}")
    scanned = []
    if args.get("scan_deck"):
        for line in [x for _, x in T.deck_lines(doc)]:
            sides = T.contrast_sides(line)
            if not sides or not (T.noun_phrase_ok(sides[0]) and T.noun_phrase_ok(sides[1])):
                continue
            neg, pos = sides
            got = _narrow(_question("", "", line, line, 0), deck_text)
            scanned.append({"line": line[:60], "choices": got})
            if not got:
                continue
            if any(len(re.findall(r"[가-힣A-Za-z0-9%]+", c)) == 1 and c in T.BOUND_NOUNS for c in got):
                problems.append(f"「{line[:30]}…」 보기에 세는 단위 {got}")
            if len(got) == 2 and not any(T.overlap(c, pos) for c in got):
                problems.append(f"「{line[:30]}…」 보기 {got} 에 세운 쪽 「{pos}」 가 없음")
    obs = {"answer": answer, "distractor": distractor, "choices": choices, "scanned": scanned}
    if problems:
        return "fail", "; ".join(problems[:3]), obs
    return "pass", f"빈칸 ({answer}, {distractor}) · 보기 {choices}" + (f" · 대비 줄 {len(scanned)}개 훑음" if scanned else ""), obs


def make_scripted(payload: dict):
    from chuckchuck.providers.llm_base import LLMProvider

    class Scripted(LLMProvider):
        name = "scripted"

        def __init__(self):
            self.calls = 0

        def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
            self.calls += 1
            return json.dumps(payload, ensure_ascii=False)

    return Scripted()


def _call_build(graph, triage, doc, llm):
    from chuckchuck import build_questions

    kw = {"track": "1", "slidedoc": doc, "llm": llm}
    if "claims" in inspect.signature(build_questions).parameters:
        kw["claims"] = None
    return build_questions(graph, triage, **kw)


def self_contradicting(question: str) -> str:
    """「X보다 … (X, …)」 — 견준 대상 X 를 괄호 속 요소로 다시 넣은 질문이면 X."""
    for m in re.finditer(r"([가-힣A-Za-z]{1,10})보다", question or ""):
        x = m.group(1)
        for p in re.finditer(r"\(([^)]*)\)", question):
            items = [t.strip() for t in re.split(r"[,·、]", p.group(1))]
            if x in items:
                return x
    return ""


def check_f08_scripted(doc: dict, args: dict) -> tuple[str, str, dict]:
    from chuckchuck.contracts import ConceptEdge, ConceptGraph, ConceptNode, QaTriage, TriageMark

    nodes = [ConceptNode(id=n["id"], label=n["label"], slide_nos=list(n.get("slide_nos") or []), summary=n.get("summary", ""),
                         weight=float(n.get("weight", 0.5)), depth=int(n.get("depth", 2)), parent_id=n.get("parent_id"))
             for n in args["nodes"]]
    graph = ConceptGraph(file_name=doc.get("file_name", "case.pptx"), total_slides=len(doc.get("slides") or []), nodes=nodes,
                         edges=[ConceptEdge(from_id=n.parent_id, to_id=n.id, kind="parent") for n in nodes if n.parent_id])
    triage = QaTriage(file_name=graph.file_name, marks=[
        TriageMark(node_id=args["node_id"], rank=1, source="core_weight", severity=1, doc_weight=1.0)])
    item = {"node_id": args["node_id"], "question": args["question"], "answer_gist": args["gist"]}
    if args.get("why"):
        item["why"] = args["why"]
    qdoc = _call_build(graph, triage, doc, make_scripted({"questions": [item]}))
    q = next((x for x in qdoc.questions if x.node_id == args["node_id"]), None)
    if q is None:
        return "fail", "F-08 이 질문을 버렸다", {"questions": [x.question for x in qdoc.questions]}
    gist, question = q.answer_gist or "", q.question or ""
    exp = args.get("expect") or {}
    problems = []
    for x in exp.get("gist_forbid") or []:
        if x in gist:
            problems.append(f"골자에 「{x}」 가 남음")
    for pat in exp.get("gist_forbid_regex") or []:
        if re.search(pat, gist):
            problems.append(f"골자가 /{pat}/ 에 걸림")
    want = exp.get("gist_require_any") or []
    if want and not any(x in gist for x in want):
        problems.append(f"골자에 {want} 가운데 하나도 없음")
    if exp.get("question_not_self_contradicting") and self_contradicting(question):
        problems.append(f"질문이 여전히 「{self_contradicting(question)}보다 … ({self_contradicting(question)}, …)」")
    checks = list(q.basis.checks) if getattr(q, "basis", None) else []
    obs = {"question": question, "gist": gist, "checks": checks}
    if problems:
        return "fail", "; ".join(problems) + f" — 골자 «{gist[:80]}»", obs
    return "pass", f"골자 «{gist[:70]}»" + (f" · 질문 «{question[:50]}»" if exp.get("question_not_self_contradicting") else ""), obs


def _graph_of(args: dict, doc: dict):
    """args.nodes(있으면)로 그래프 — f08_scripted 와 같은 꼴. 없으면 None."""
    from chuckchuck.contracts import ConceptEdge, ConceptGraph, ConceptNode

    if not args.get("nodes"):
        return None
    nodes = [ConceptNode(id=n["id"], label=n["label"], slide_nos=list(n.get("slide_nos") or []), summary=n.get("summary", ""),
                         weight=float(n.get("weight", 0.5)), depth=int(n.get("depth", 2)), parent_id=n.get("parent_id"))
             for n in args["nodes"]]
    return ConceptGraph(file_name=doc.get("file_name", "case.pptx"), total_slides=len(doc.get("slides") or []), nodes=nodes,
                        edges=[ConceptEdge(from_id=n.parent_id, to_id=n.id, kind="parent") for n in nodes if n.parent_id])


def _forbid_llm():
    from chuckchuck.providers.llm_base import LLMProvider

    class Forbid(LLMProvider):
        name = "forbid"

        def complete(self, **kw):
            raise RuntimeError("이 경로는 LLM 을 부르면 안 된다")

    return Forbid()


def check_judge_scripted(doc: dict, args: dict) -> tuple[str, str, dict]:
    """
    대상 `judge_answer` 에 **정해 둔 LLM 판정**(args.llm — 실측에서 LLM 이 한 말)을 넣고 코드가 낸 판정을 본다 (LLM 없음).
    args.llm_variants 가 있으면 그 판정들 모두로 돌려 (등급, 점수)가 하나로 모이는지(`same_across`) 본다 — 실행마다 흔들리던 답.
    expect: verdict_in · score_min · score_max · passed · guard_in · same_across ·
            missing_forbid_regex · followup_forbid_regex · react_forbid_regex · hints_forbid_regex
    """
    from chuckchuck import judge_answer
    from chuckchuck.f09_judge import clear_judge_cache

    graph = _graph_of(args, doc)
    payloads = [args["llm"], *(args.get("llm_variants") or [])]
    got = []
    for payload in payloads:
        clear_judge_cache()
        j = judge_answer(args["question"], args["answer"], slidedoc=doc, graph=graph, prior_answers=list(args.get("prior") or []),
                         history=list(args.get("history") or []), llm=make_scripted(payload)).to_dict()
        got.append(j)
    j = got[0]
    exp = args.get("expect") or {}
    problems = []
    if exp.get("verdict_in") and j.get("verdict") not in exp["verdict_in"]:
        problems.append(f"등급 {j.get('verdict')} ∉ {exp['verdict_in']}")
    if exp.get("score_min") is not None and int(j.get("score") or 0) < exp["score_min"]:
        problems.append(f"점수 {j.get('score')} < {exp['score_min']}")
    if exp.get("score_max") is not None and int(j.get("score") or 0) > exp["score_max"]:
        problems.append(f"점수 {j.get('score')} > {exp['score_max']}")
    if exp.get("passed") is not None and bool(j.get("passed")) != exp["passed"]:
        problems.append(f"통과 {j.get('passed')} ≠ {exp['passed']}")
    if exp.get("guard_in") is not None and (j.get("guard") or "") not in exp["guard_in"]:
        problems.append(f"가드 {j.get('guard')!r} ∉ {exp['guard_in']}")
    if exp.get("same_across") and len({(x.get("verdict"), x.get("score")) for x in got}) > 1:
        problems.append(f"LLM 판정마다 다름 {[(x.get('verdict'), x.get('score')) for x in got]}")
    for field, key in (("missing_points", "missing_forbid_regex"), ("followup", "followup_forbid_regex"),
                       ("react", "react_forbid_regex"), ("hints", "hints_forbid_regex")):
        for pat in exp.get(key) or []:
            for x in got:
                vals = x.get(field) if isinstance(x.get(field), list) else [x.get(field) or ""]
                bad = [v for v in vals if re.search(pat, str(v))]
                if bad:
                    problems.append(f"{field} 가 /{pat}/ 에 걸림: «{str(bad[0])[:60]}»")
                    break
    obs = {"judgements": [{k: x.get(k) for k in ("verdict", "score", "guard", "react", "followup", "missing_points")} for x in got]}
    if problems:
        return "fail", "; ".join(problems[:4]), obs
    return "pass", f"{j.get('verdict')}/{j.get('score')} · 되물음 «{str(j.get('followup'))[:40]}»", obs


def check_stuck_ladder(doc: dict, args: dict) -> tuple[str, str, dict]:
    """
    「모르겠어요」 사다리·힌트 사다리 (09-30 WP-J3) — 대상 `_narrow_followup`(LLM 보기 args.llm_choices 를 줘도) · `_scaffold_judgement` ·
    `build_hint_ladder` · 칩 답 판정(LLM 없이, args.chips — [{answer, verdict_in}]).
    expect: choices_equal · choices_forbid · narrow_forbid_regex · scaffold_forbid_regex · scaffold_require_regex ·
            blank_not_in_question(발판·힌트 빈칸의 가린 말이 질문에 없다 — 잣대가 원문으로 되찾는다) · hint_forbid_regex ·
            coach_react_forbid_regex(args.llm_coach — 실측의 코칭 LLM 응답을 대본으로 넣은 「모르겠어요」 1단 react 에 걸리면 안 되는 말)
    """
    from chuckchuck.contracts import Question
    from chuckchuck.f08_questions import build_hint_ladder
    from chuckchuck.f09_judge import _deck_text, _narrow_followup, _scaffold_judgement, clear_judge_cache
    from chuckchuck.contracts import SlideDoc
    from chuckchuck import judge_answer

    from . import replay as RP

    q = Question.from_dict(args["question"])
    qd = args["question"]
    graph = _graph_of(args, doc)
    deck_text = _deck_text(SlideDoc.from_dict(doc))
    exp = args.get("expect") or {}
    problems = []
    fu, choices = _narrow_followup({"followup": args.get("llm_followup", ""), "choices": list(args.get("llm_choices") or [])},
                                   q, graph, deck_text)
    if exp.get("choices_equal") is not None and list(choices) != list(exp["choices_equal"]):
        problems.append(f"보기 {choices} ≠ {exp['choices_equal']}")
    bad = [c for c in choices if c in (exp.get("choices_forbid") or [])]
    if bad:
        problems.append(f"금지 보기 {bad}")
    for pat in exp.get("narrow_forbid_regex") or []:
        if re.search(pat, fu):
            problems.append(f"첫 단계가 /{pat}/ 에 걸림: «{fu[:70]}»")
    sj = _scaffold_judgement(q, graph, deck_text)
    scaffold = sj.followup if sj else ""
    for pat in exp.get("scaffold_forbid_regex") or []:
        if re.search(pat, scaffold):
            problems.append(f"발판이 /{pat}/ 에 걸림: «{scaffold[:70]}»")
    for pat in exp.get("scaffold_require_regex") or []:
        if not re.search(pat, scaffold):
            problems.append(f"발판에 /{pat}/ 가 없음: «{scaffold[:70]}»")
    rung = next((h for h in build_hint_ladder(q) if h.startswith("빈칸을 채워 보세요")), "")
    for pat in exp.get("hint_forbid_regex") or []:
        if re.search(pat, rung):
            problems.append(f"힌트 빈칸이 /{pat}/ 에 걸림: «{rung[:70]}»")
    if exp.get("blank_not_in_question"):
        probe_quotes = [e.quote for e in (q.basis.probe.evidence if q.basis and q.basis.probe else [])]
        sources = [q.answer_gist, q.evidence_quote, *probe_quotes, deck_text]
        for label, text, ch in (("발판", scaffold, list(sj.choices) if sj else []), ("힌트", rung, [])):
            if "___" not in text or T.stance_pair(ch) or re.search(r"'[^']+' 인가요, '[^']+' 인가요", text) and not ch:
                continue
            word = RP._fill(text, [] if T.stance_pair(ch) else ch, sources)
            if word and RP._shown(word, qd):
                problems.append(f"{label} 빈칸이 질문에 보인 말 「{word}」")
    chips = []
    for c in args.get("chips") or []:
        clear_judge_cache()
        j = judge_answer(qd, c["answer"], slidedoc=doc, graph=graph, llm=_forbid_llm()).to_dict()
        chips.append({"answer": c["answer"], "verdict": j.get("verdict"), "score": j.get("score"), "followup": j.get("followup")})
        if c.get("verdict_in") and j.get("verdict") not in c["verdict_in"]:
            problems.append(f"칩 「{c['answer']}」 → {j.get('verdict')} ∉ {c['verdict_in']}")
        for pat in c.get("followup_forbid_regex") or []:
            if re.search(pat, j.get("followup") or ""):
                problems.append(f"칩 「{c['answer']}」 되물음이 /{pat}/ 에 걸림")
    coach = {}
    if args.get("llm_coach"):
        from chuckchuck import coach_stuck

        clear_judge_cache()
        cj = coach_stuck(qd, slidedoc=doc, graph=graph, llm=make_scripted(args["llm_coach"])).to_dict()
        coach = {k: cj.get(k) for k in ("coach_stage", "react", "followup", "choices")}
        for pat in exp.get("coach_react_forbid_regex") or []:
            if re.search(pat, cj.get("react") or ""):
                problems.append(f"「모르겠어요」 react 가 /{pat}/ 에 걸림: «{str(cj.get('react'))[:70]}»")
    obs = {"narrow": fu, "choices": choices, "scaffold": scaffold, "hint_blank": rung, "chips": chips, "coach": coach}
    if problems:
        return "fail", "; ".join(problems[:4]), obs
    return "pass", f"보기 {choices} · 발판 «{scaffold[:50]}»", obs


KINDS = {
    "units_no_midword_start": check_units_no_midword_start,
    "best_quote_slide": check_best_quote_slide,
    "contrast_choice": check_contrast_choice,
    "f08_scripted": check_f08_scripted,
    "judge_scripted": check_judge_scripted,
    "stuck_ladder": check_stuck_ladder,
}


def load_cases(path: Path = CASES) -> list[dict]:
    return (C.read_json(path) or {}).get("cases") or []


def run_cases(path: Path = CASES, only: set[str] | None = None) -> list[dict]:
    cases = load_cases(path)
    by_id = {c["id"]: c for c in cases}
    out = []
    for case in cases:
        if only and case["id"] not in only:
            continue
        row = {"id": case["id"], "title": case.get("title", ""), "kind": case.get("kind", ""), "origin": case.get("origin", "")}
        fn = KINDS.get(case.get("kind", ""))
        if fn is None:
            out.append(dict(row, status="error", detail=f"모르는 검사 종류 {case.get('kind')}"))
            continue
        doc, where = load_source(case, by_id)
        row["source"] = where
        if doc is None:
            out.append(dict(row, status="skip", detail=where))
            continue
        try:
            status, detail, obs = fn(doc, case.get("args") or {})
        except ImportError as e:
            status, detail, obs = "fail", f"대상에 공개 함수가 없음: {e}", {}
        except Exception as e:  # noqa: BLE001 — 사례 하나가 죽어도 나머지는 돈다
            status, detail, obs = "error", f"{type(e).__name__}: {str(e)[:200]}", {}
        out.append(dict(row, status="fail" if status == "error" else status, detail=detail, observed=obs,
                        error=status == "error"))
    return out
