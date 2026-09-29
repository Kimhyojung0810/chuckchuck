"""
회귀 사례 실행기 — regression/cases.json 의 사례마다 **대상 저장소의 공개 함수**를 불러 기대와 대조한다. 자식 프로세스
(target_probe.py) 안에서 돈다 — `chuckchuck` 은 대상의 것이다. LLM 은 부르지 않는다(F-08 은 정해 둔 응답 ScriptedLLM).

검사 종류(kind) — 규칙 코드는 여기에만 있고, 무엇을 넣고 무엇을 기대하는지는 사례 데이터에 있다.
- units_no_midword_start  원문에서 낱말 한가운데 꺾인 줄을 잣대가 찾고, 대상 `_evidence.slide_units`·`best_quote` 가
                          그 조각으로 시작하는 인용을 내지 않는지
- best_quote_slide        대상 `_evidence.best_quote` 가 기대한 장·글을 고르는지
- contrast_choice         대상 `_evidence.mask_gist` · `f09_judge._narrow_followup` 의 보기 쌍이 (세운 쪽, 부정한 쪽)인지,
                          세는 단위가 보기로 안 나오는지 (덱의 모든 「X 아니라 Y」 줄도 훑는다)
- f08_scripted            대상 `build_questions` 에 정해 둔 LLM 응답(질문·골자)을 넣고 나온 골자·질문을 검사. `claims: "rules"` 면
                          대상 F-26 규칙 주장(`build_claims(llm="none")`)을 같이 넣어 탐침이 묶이게 하고, `marks`·`track`·`questions` 로
                          여러 개념·트랙을 준다(여유 후보·밀어내기).
- probe_absolute          대상 F-26 규칙 주장 → `derive_probes` 에서 단정 탐침이 **따질 줄에만** 나오는지(`absolute_on`·`absolute_off`),
                          그 탐침의 코드 골자(`probe_code_gist`)가 조건을 대는지·단정 줄을 되읊지 않는지 (09-30 WP-P2)
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


def _call_build(graph, triage, doc, llm, *, track: str = "1", claims=None):
    from chuckchuck import build_questions

    kw = {"track": track, "slidedoc": doc, "llm": llm}
    if "claims" in inspect.signature(build_questions).parameters:
        kw["claims"] = claims
    return build_questions(graph, triage, **kw)


def _graph_of(doc: dict, args: dict):
    from chuckchuck.contracts import ConceptEdge, ConceptGraph, ConceptNode

    nodes = [ConceptNode(id=n["id"], label=n["label"], slide_nos=list(n.get("slide_nos") or []), summary=n.get("summary", ""),
                         weight=float(n.get("weight", 0.5)), depth=int(n.get("depth", 2)), parent_id=n.get("parent_id"))
             for n in args["nodes"]]
    return ConceptGraph(file_name=doc.get("file_name", "case.pptx"), total_slides=len(doc.get("slides") or []), nodes=nodes,
                        edges=[ConceptEdge(from_id=n.parent_id, to_id=n.id, kind="parent") for n in nodes if n.parent_id])


def _rule_claims(graph, doc: dict, extra: list[dict] | None = None):
    """
    대상 F-26 의 **규칙 주장** (LLM 없이) — 탐침을 묶을 재료. extra 는 LLM 이 냈을 주장을 사례 데이터로 더한 것
    ({kind, subject_id, object_ids, slide_no, quote} — quote 는 그 장 원문 한 줄 그대로).
    """
    from chuckchuck.contracts import Claim, ClaimDoc, ClaimQuote
    from chuckchuck.f26_claims import build_claims

    doc_ = build_claims(graph, doc, llm="none")
    more = [Claim(id=f"x{i}", kind=c["kind"], subject_id=c["subject_id"], object_ids=list(c.get("object_ids") or []),
                  evidence=[ClaimQuote(int(c["slide_no"]), c["quote"])]) for i, c in enumerate(extra or [], 1)]
    return ClaimDoc(file_name=doc_.file_name, claims=[*doc_.claims, *more], model=doc_.model, dropped=doc_.dropped)


def _slides_text(doc: dict) -> dict[int, str]:
    return {int(s["slide_no"]): _raw(s) for s in doc.get("slides") or []}


def check_probe_absolute(doc: dict, args: dict) -> tuple[str, str, dict]:
    from chuckchuck._probes import derive_probes, probe_code_gist

    graph = _graph_of(doc, args)
    slides = _slides_text(doc)
    probes = derive_probes(graph, _rule_claims(graph, doc, args.get("extra_claims")), slides)
    ab = [p for p in probes if p.kind == "absolute_boundary"]
    said = [e.quote for p in ab for e in p.evidence]
    problems = []
    for x in args.get("absolute_on") or []:
        if not any(x in q for q in said):
            problems.append(f"「{x}」 에 단정 탐침이 없음")
    for x in args.get("absolute_off") or []:
        if any(x in q for q in said):
            problems.append(f"「{x}」 에 단정 탐침이 나옴 (따질 주장이 아니다)")
    gist = ""
    want_gist = any(args.get(k) for k in ("gist_require", "gist_require_any", "gist_forbid", "gist_bare_forbid"))
    if want_gist:
        target = next((p for p in ab if any(x in e.quote for x in args.get("absolute_on") or [] for e in p.evidence)), None)
        if target is None:
            problems.append("골자를 볼 단정 탐침이 없음")
        else:
            gist = probe_code_gist(target, {n.id: n.label for n in graph.nodes}, slides)
            for x in args.get("gist_require") or []:
                if x not in gist:
                    problems.append(f"골자에 「{x}」 가 없음")
            any_of = args.get("gist_require_any") or []
            if any_of and not any(x in gist for x in any_of):
                problems.append(f"골자에 {any_of} 가운데 하나도 없음")
            for x in args.get("gist_forbid") or []:
                if x in gist:
                    problems.append(f"골자에 「{x}」 가 남음")
            bare = re.sub(r"「[^」]*」", " ", gist)
            for x in args.get("gist_bare_forbid") or []:
                if x in bare:
                    problems.append(f"골자 인용 밖에 「{x}」 가 남음 (단정 줄을 되읊었다)")
    obs = {"absolute": said, "gist": gist}
    if problems:
        return "fail", "; ".join(problems[:4]) + (f" — 골자 «{gist[:70]}»" if gist else ""), obs
    return "pass", f"단정 탐침 {len(ab)}개 «{(said or [''])[0][:40]}»" + (f" · 골자 «{gist[:60]}»" if gist else ""), obs


#: 잣대 쪽 「한 문장에 두 물음」 — 대상 코드(`_probes.split_asks`)를 쓰지 않는다(같은 버그를 못 본다). 물음 낱말이 든 앞 절이
#: 이음 어미 + 쉼표로 끝나고 뒤 절도 물음이면 두 물음이다. 관용(「어떻게 보면」「무엇보다」「누구나」)은 물음 낱말이 아니다.
_ASK_W_RE = re.compile(r"(?<![가-힣])(?:무엇|무슨|어떤|어떻게|왜|얼마|누가|누구|어디|언제|몇)")
_ASK_IDIOM_W_RE = re.compile(r"어떻게\s*보면|어떻게든|무엇보다|무엇이든|누구나|누구든|언제나|언제든|어디서든|얼마든지|어떤\s*경우(?:에도|든)")
_ASK_JOIN_W_RE = re.compile(r"(?:이며|며|이고|고|인지|는지|은지|한지)\s*,\s*")
_ASK_END_W_RE = re.compile(r"(?:나요|가요|까요|습니까)\s*[?？]?\s*$|[?？]\s*$")


def two_asks(question: str) -> bool:
    q = question or ""
    for m in _ASK_JOIN_W_RE.finditer(q):
        head, tail = q[: m.start()], q[m.end():]
        if _ASK_W_RE.search(_ASK_IDIOM_W_RE.sub(" ", head)) and (
                _ASK_W_RE.search(_ASK_IDIOM_W_RE.sub(" ", tail)) or _ASK_END_W_RE.search(tail)):
            return True
    return False


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
    from chuckchuck.contracts import QaTriage, TriageMark

    graph = _graph_of(doc, args)
    marks = args.get("marks") or [[args["node_id"], "core_weight"]]
    triage = QaTriage(file_name=graph.file_name, marks=[
        TriageMark(node_id=nid, rank=i, source=src, severity=1, doc_weight=1.0) for i, (nid, src) in enumerate(marks, 1)])
    items = []
    for raw in args.get("questions") or [{"node_id": args["node_id"], "question": args["question"], "gist": args.get("gist", ""),
                                          "why": args.get("why", "")}]:
        item = {"node_id": raw["node_id"], "question": raw["question"], "answer_gist": raw.get("gist", "")}
        if raw.get("why"):
            item["why"] = raw["why"]
        items.append(item)
    claims = _rule_claims(graph, doc, args.get("extra_claims")) if args.get("claims") == "rules" else None
    qdoc = _call_build(graph, triage, doc, make_scripted({"questions": items}), track=str(args.get("track", "1")), claims=claims)
    exp = args.get("expect") or {}
    got_ids = [x.node_id for x in qdoc.questions]
    if exp.get("node_absent"):
        # 코드가 답할 수 없다고 본 질문을 다음 후보 뒤로 밀었는가 (09-30 WP-P2)
        if exp["node_absent"] in got_ids:
            return "fail", f"「{exp['node_absent']}」 질문이 여전히 트랙에 있음 — {got_ids}", {"questions": got_ids}
        if len(got_ids) < int(exp.get("count", 0) or 0):
            return "fail", f"질문 수가 줄었음 {len(got_ids)}", {"questions": got_ids}
        return "pass", f"밀려남 — 트랙 {got_ids}", {"questions": got_ids}
    q = next((x for x in qdoc.questions if x.node_id == args["node_id"]), None)
    if q is None:
        return "fail", "F-08 이 질문을 버렸다", {"questions": [x.question for x in qdoc.questions]}
    gist, question = q.answer_gist or "", q.question or ""
    problems = []
    for x in exp.get("question_forbid") or []:
        if x in question:
            problems.append(f"질문에 「{x}」 가 남음")
    if exp.get("question_equals") and question != exp["question_equals"]:
        problems.append(f"질문 «{question[:60]}» ≠ «{exp['question_equals'][:60]}»")
    if exp.get("question_single_ask") and two_asks(question):
        problems.append(f"질문이 여전히 두 물음 «{question[:60]}»")
    checks_now = set(q.basis.checks) if getattr(q, "basis", None) else set()
    for c in exp.get("checks_require") or []:
        if c not in checks_now:
            problems.append(f"검사 「{c}」 가 없음")
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
    asked = any(exp.get(k) for k in ("question_not_self_contradicting", "question_equals", "question_forbid", "question_single_ask"))
    return "pass", f"골자 «{gist[:70]}»" + (f" · 질문 «{question[:50]}»" if asked else ""), obs


KINDS = {
    "units_no_midword_start": check_units_no_midword_start,
    "best_quote_slide": check_best_quote_slide,
    "contrast_choice": check_contrast_choice,
    "f08_scripted": check_f08_scripted,
    "probe_absolute": check_probe_absolute,
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
