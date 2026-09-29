"""
근거 질문 지표 (qa/reason, 2026-09-30) — 근거·이유를 묻는 질문의 골자가 **이유 줄**을 싣는지, 배경만 싣는지,
「모르겠어요」 보기 쌍이 자료가 세운 쪽을 정답으로 두는지. LLM 을 부르지 않는다.

    .venv/bin/python labs/qa_bench/reason_metrics.py --out labs/qa_bench/out --json after.json
    .venv/bin/python labs/qa_bench/reason_metrics.py --out labs/qa_bench/out/_before_reason --code-root <aadf68f 코드> --json before.json

`--code-root` 로 **옛 코드**를 올려 같은 질문에 옛 보기 규칙을 태울 수 있다 (전후 비교). 판별은 코드의 `_reason` 을 쓰지 않고
여기서 **따로** 한다 (같은 코드로 검사하면 같은 버그를 못 본다) — 규칙은 말투·절 제목만 보는 단순한 것이다.

지표
- 근거 질문: 질문에 근거·이유·왜·원인·결론지은 이 있고 「왜 중요」 가 아닌 것 (함정·탐침 질문 제외 — 제 골자 규칙이 따로 있다).
- 이유 줄 인용: 골자가 근거 장의 **이유 줄**(정답이 있는 덱은 정답 줄, 없으면 이유 말투 줄·원인/이유 절의 줄) 하나 이상을 담는다.
- 배경만: 골자가 근거 장의 줄을 담긴 하는데 이유 줄은 하나도 없다.
- 심은 근거 질문: 정답(truth.reason)이 있는 덱에 정답 질문 + 「배경과 이유를 섞은 골자」 를 LLM 없이(ScriptedLLM) F-08 에 넣어
  나온 골자가 가장 곧은 줄을 담는가 · 배경 줄 수치를 뺐는가, 그리고 그 질문의 「모르겠어요」 보기가 정답 대비 쌍인가.
- 보기 쌍 유효: 모든 질문에서 LLM 보기 없이(`_narrow_followup({})`) 나온 두 보기가 (1) 둘 다 자료에 있고 (2) 정답 쪽이
  자료의 부정 절(「… 아니라」 앞) 안에 있지 않고 (3) 보여 준 인용이 「X 아니라 Y」 면 정답이 Y 쪽이다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

_ASK_RE = re.compile(r"근거|이유|(?<![가-힣])왜(?![가-힣])|어째서|때문|원인|결론지")
_IMPORTANCE_RE = re.compile(r"왜\s*중요|중요한\s*이유|중요성")
_REASON_MARK_RE = re.compile(r"아니라|아닌\s|상관|비례|때문|원인|이유|→|수록|갈랐|좌우|영향|결과로")
_REASON_HEAD_RE = re.compile(r"원인|이유|요인|근거")
_BULLET_RE = re.compile(r"^\s*[·•▪■◦\-–—*]\s*")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_WORD_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{3,}|\d+(?:\.\d+)?")
_JOSA_RE = re.compile(r"(?:에서는|에서|으로|에게|은|는|이|가|을|를|의|에|와|과|도|로)$")


def _words(text: str) -> set[str]:
    out = set()
    for w in _WORD_RE.findall(text or ""):
        s = _JOSA_RE.sub("", w)
        out.add(s if len(s) >= 2 else w)
    return out


def _hit(a: str, bag: set[str]) -> bool:
    return any(a == b or (len(a) >= 2 and len(b) >= 2 and (a.startswith(b) or b.startswith(a))) for b in bag)


def _cites(gist: str, line: str) -> bool:
    """골자가 자료 줄을 담았나 — 줄 낱말의 40% 이상·둘 이상이 골자에 있다 (앞부분이 같은 낱말은 같은 낱말로)."""
    lw, gw = _words(line), _words(gist)
    got = sum(1 for w in lw if _hit(w, gw))
    return bool(lw) and got >= 2 and got * 5 >= len(lw) * 2


def _slide_lines(raw: str) -> list[tuple[str, str]]:
    """(줄, 절 제목) — 글머리표 앞의 짧은 줄을 절 제목으로 본다. 꺾인 낱말은 앞 줄에 잇는다."""
    lines = [ln.strip() for ln in (raw or "").split("\n") if ln.strip()]
    out: list[list[str]] = []
    head = ""
    for i, ln in enumerate(lines):
        if re.fullmatch(r"[·•\-–—*]+|\d{1,2}", ln):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if not _BULLET_RE.match(ln) and len(ln) <= 24 and _BULLET_RE.match(nxt):
            head = ln
            out.append([ln, head])
            continue
        body = _BULLET_RE.sub("", ln)
        if out and ((" " not in body and len(body) <= 6 and not re.search(r"[.다요]$", out[-1][0]))
                    or re.search(r",\s*$", out[-1][0])):
            out[-1][0] += " " + body
            continue
        out.append([body, head])
    return [(a, b) for a, b in out]


def _reason_lines(raw: str) -> tuple[list[str], list[str]]:
    """(이유 줄, 배경 줄). 배경은 **이유 줄이 있는 장**의 나머지 줄만 — 이유가 하나도 없는 장의 줄은 어느 쪽도 아니다."""
    rs, bg = [], []
    for ln, head in _slide_lines(raw):
        (rs if (_REASON_MARK_RE.search(ln) or _REASON_HEAD_RE.search(head)) else bg).append(ln)
    return rs, (bg if rs else [])


def _asks_phenomenon(q: dict, raw: dict[int, str], truth_reason: dict | None) -> bool:
    """질문이 배경 줄(현상 자체)을 되뇌고 이유 줄과는 안 겹친다 — 현상의 근거를 묻는 것이라 배경이 답이다."""
    qw = _words(q.get("question", ""))
    nos = [n for n in q.get("slide_nos") or [] if n in raw]
    if truth_reason and truth_reason.get("slide") in nos:
        rs, bg = truth_reason["reason_lines"], truth_reason["background_lines"]
    else:
        rs, bg = [], []
        for n in nos:
            r, b = _reason_lines(raw[n])
            rs, bg = rs + r, bg + b
    top_bg = max((sum(1 for w in _words(ln) if _hit(w, qw)) for ln in bg), default=0)
    top_rs = max((sum(1 for w in _words(ln) if _hit(w, qw)) for ln in rs), default=0)
    return top_bg >= 3 and top_rs < 2


def is_reason_question(q: dict) -> bool:
    b = q.get("basis") or {}
    return (bool(_ASK_RE.search(q.get("question", ""))) and not _IMPORTANCE_RE.search(q.get("question", ""))
            and not q.get("trap") and not b.get("probe"))


def gist_row(q: dict, raw: dict[int, str], truth_reason: dict | None) -> dict:
    nos = [n for n in q.get("slide_nos") or [] if n in raw]
    if truth_reason and truth_reason.get("slide") in nos:
        reason = truth_reason["reason_lines"]
        background = truth_reason["background_lines"]
    else:
        reason, background = [], []
        for n in nos:
            r, b = _reason_lines(raw[n])
            reason += r
            background += b
    gist = q.get("answer_gist", "")
    cites_r = [ln for ln in reason if _cites(gist, ln)]
    cites_b = [ln for ln in background if _cites(gist, ln)]
    return {"q": q["id"], "question": q["question"], "gist": gist, "reason_cited": bool(cites_r),
            "background_only": bool(cites_b) and not cites_r, "has_reason_lines": bool(reason),
            "checks": [c for c in (q.get("basis") or {}).get("checks") or [] if c.startswith(("gist_", "reason", "contrast"))]}


def _negated_side(line: str, term: str) -> bool:
    for m in re.finditer(r"아니라|아닌\s", line):
        clause = re.split(r"[:.·,—]", line[: m.start()])[-1]
        if term and term in clause:
            return True
    return False


def choice_row(q: dict, graph, deck_text: str, lines: list[str]) -> dict:
    from chuckchuck.contracts import Question
    from chuckchuck.f09_judge import _distractor_pool, _narrow_followup
    from chuckchuck._evidence import mask_gist

    qq = Question.from_dict(q)
    followup, choices = _narrow_followup({}, qq, graph, deck_text)
    b = q.get("basis") or {}
    # 탐침 질문의 입장 보기 쌍 (09-30 WP-J3) — 맞는 쪽은 탐침 종류가 정한다(잣대 쪽 정의 `metrics.STANCE_TRUTH`). 쌍의 종류가 질문의 탐침과 같은
    # 뜻(빈틈 둘은 같다)이면 유효다.
    from metrics import STANCE_TRUTH, stance_pair

    kind = stance_pair(list(choices))
    if kind:
        probe_kind = ((b.get("probe") or {}).get("kind") or "")
        right = STANCE_TRUTH.get(probe_kind, (None, None))[0]
        answer = next((c for c in choices if right is not None and right.search(c)), "")
        ok = bool(answer) and STANCE_TRUTH.get(kind) == STANCE_TRUTH.get(probe_kind)
        return {"q": q["id"], "choices": choices, "answer": answer, "valid": ok, "followup": followup, "stance": kind}
    if len(b.get("contrast") or []) == 2 and hasattr(qq.basis, "contrast"):
        answer = b["contrast"][0]
    else:
        answer = mask_gist(qq.answer_gist, qq.label, _distractor_pool(qq, graph), quote=qq.evidence_quote,
                           deck_text=deck_text)[1] if len(choices) == 2 else ""
    shown = re.search(r"«(.+?)»", followup or "")
    shown = shown.group(1) if shown else ""
    ok = len(choices) == 2 and all(c.replace(" ", "") in deck_text.replace(" ", "") for c in choices) and bool(answer)
    if ok:
        ok = not any(_negated_side(ln, answer) and all(c in ln for c in choices) for ln in lines)
    if ok and re.search(r"아니라", shown) and answer in shown:
        ok = shown.find(answer) > shown.find("아니라")
    return {"q": q["id"], "choices": choices, "answer": answer, "valid": ok if len(choices) == 2 else None,
            "followup": followup}


def planted_row(name: str, sd: dict, graph: dict, claims: dict | None, truth_reason: dict) -> dict:
    """정답 근거 질문 + 배경·이유를 섞은 골자를 ScriptedLLM 으로 F-08 에 넣는다 (LLM 없음)."""
    from chuckchuck import build_questions
    from chuckchuck.contracts import ConceptGraph, QaTriage, SlideDoc, TriageMark
    from chuckchuck.f09_judge import _deck_text, _narrow_followup
    from chuckchuck.providers.llm_base import LLMProvider

    g = ConceptGraph.from_dict(graph)
    conc = truth_reason["conclusion"]
    target = max((n for n in g.nodes if truth_reason["slide"] in (n.slide_nos or [])),
                 key=lambda n: (len(_words(n.label) & _words(conc)), -n.depth, n.weight), default=g.nodes[0])
    mixed = f"{truth_reason['background_lines'][0]}이고, {truth_reason['reason_lines'][0]}이에요."

    class Scripted(LLMProvider):
        name = "scripted"

        def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
            return json.dumps({"questions": [{"node_id": target.id, "question": truth_reason["question"],
                                              "answer_gist": mixed}]}, ensure_ascii=False)

    triage = QaTriage(file_name=sd.get("file_name", ""), marks=[
        TriageMark(node_id=target.id, rank=1, source="core_weight", severity=1, doc_weight=1.0)])
    kw = {"claims": claims} if claims is not None else {}
    try:
        doc = build_questions(g, triage, track="1", slidedoc=sd, llm=Scripted(), **kw)
    except TypeError:
        doc = build_questions(g, triage, track="1", slidedoc=sd, llm=Scripted())
    q = doc.questions[0]
    sdoc = SlideDoc.from_dict(sd)
    followup, choices = _narrow_followup({}, q, g, _deck_text(sdoc))
    bg_nums = {n for ln in truth_reason["background_lines"] for n in _NUM_RE.findall(ln) if len(n) >= 2 or "." in n}
    want = truth_reason["contrast"]
    b = q.to_dict().get("basis") or {}
    answer = (b.get("contrast") or [""])[0] if b.get("contrast") else ""
    return {"deck": name, "node": target.label, "gist_in": mixed, "gist_out": q.answer_gist,
            "strongest_cited": _cites(q.answer_gist, truth_reason["strongest"]),
            "background_numbers_dropped": not any(n in q.answer_gist for n in bg_nums),
            "choices": choices, "choice_answer": answer,
            "choice_pair_ok": bool(choices) and any(want["affirmed"] in c for c in choices)
            and any(want["negated"] in c for c in choices) and (not answer or want["affirmed"] in answer),
            "followup": followup}


def load_truths() -> dict[str, dict]:
    out = {}
    corpus = HERE / "corpus"
    for d in corpus.iterdir():
        t = d / "truth.json"
        if t.exists():
            out[d.name] = json.loads(t.read_text(encoding="utf-8"))
    for r in json.loads((corpus / "real_decks.json").read_text(encoding="utf-8")).get("decks") or []:
        out[r["name"]] = dict(r.get("truth") or {}, group=r["group"])
    return out


def _pct(a: int, b: int) -> str:
    return f"{round(100 * a / b)}% ({a}/{b})" if b else "-"


def _agg(d: dict, groups: set[str]) -> dict:
    r = dict(decks=0, all=0, n=0, cite=0, bg=0, ph=0, ch=0, chv=0, pl=0, pl_s=0, pl_b=0, pl_c=0)
    for e in d.values():
        if e["group"] not in groups:
            continue
        r["decks"] += 1
        for v in e["tracks"].values():
            rows = [x for x in v["reason"] if x["has_reason_lines"]]      # 근거 장에 이유 줄이 없으면 잴 것이 없다
            r["all"] += len(v["reason"])
            r["n"] += len(rows)
            r["cite"] += sum(x["reason_cited"] for x in rows)
            r["bg"] += sum(x["background_only"] for x in rows)
            r["ph"] += len(v.get("phenomenon") or [])
            cs = [c for c in v["choices"] if c["valid"] is not None]
            r["ch"] += len(cs)
            r["chv"] += sum(1 for c in cs if c["valid"])
        p = e.get("planted")
        if p:
            r["pl"] += 1
            r["pl_s"] += p["strongest_cited"]
            r["pl_b"] += p["background_numbers_dropped"]
            r["pl_c"] += p["choice_pair_ok"]
    return r


def compare_md(before: dict, after: dict) -> str:
    """전후 표 — held-out(안 본 덱 + 새 덱)과 tuned(튜닝에 쓴 덱·오늘 부스 덱)를 따로."""
    groups = (("held-out (안 본 덱)", {"heldout", "new"}), ("tuned (튜닝·부스 덱)", {"tuned"}))
    rows = [("근거 질문 수 (두 트랙)", lambda r: str(r["all"])),
            ("└ 근거 장에 이유 줄이 있는 것 (아래 두 비율의 분모)", lambda r: str(r["n"])),
            ("└ 현상 자체의 근거를 묻는 질문 (배경이 답 — 제외)", lambda r: str(r["ph"])),
            ("근거 질문 골자가 이유 줄을 인용", lambda r: _pct(r["cite"], r["n"])),
            ("근거 질문 골자가 배경만", lambda r: _pct(r["bg"], r["n"])),
            ("「모르겠어요」 보기 쌍 유효 (정답 쪽이 자료가 세운 쪽)", lambda r: _pct(r["chv"], r["ch"])),
            ("심은 근거 질문: 가장 곧은 이유 줄 인용", lambda r: _pct(r["pl_s"], r["pl"])),
            ("심은 근거 질문: 배경 수치 뺌", lambda r: _pct(r["pl_b"], r["pl"])),
            ("심은 근거 질문: 보기 = 정답 대비 쌍", lambda r: _pct(r["pl_c"], r["pl"]))]
    out = ["| 지표 | " + " | ".join(f"{g} 전 | {g} 후" for g, _ in groups) + " |",
           "|---|" + "---|" * (2 * len(groups))]
    aggs = [(_agg(before, gs), _agg(after, gs)) for _, gs in groups]
    out.append("| 덱 | " + " | ".join(f"{b['decks']} | {a['decks']}" for b, a in aggs) + " |")
    for name, f in rows:
        out.append(f"| {name} | " + " | ".join(f"{f(b)} | {f(a)}" for b, a in aggs) + " |")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    if argv[:1] == ["compare"]:
        before, after, md = argv[1:4]
        text = compare_md(json.loads(Path(before).read_text(encoding="utf-8")),
                          json.loads(Path(after).read_text(encoding="utf-8")))
        Path(md).write_text("# 근거 질문 지표 — 전후 (자동 생성, `labs/qa_bench/reason_metrics.py compare`)\n\n" + text,
                            encoding="utf-8")
        print(text)
        return 0
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--code-root", default=str(ROOT))
    ap.add_argument("--json", required=True)
    ns = ap.parse_args(argv)
    sys.path.insert(0, ns.code_root)
    from chuckchuck.contracts import ConceptGraph, SlideDoc
    from chuckchuck.f09_judge import _deck_text

    truths = load_truths()
    result = {}
    for d in sorted(Path(ns.out).iterdir()):
        if not d.is_dir() or d.name.startswith("_") or not (d / "questions_t5.json").exists():
            continue
        sd = json.loads((d / "slide_doc.json").read_text(encoding="utf-8"))
        graph = json.loads((d / "graph.json").read_text(encoding="utf-8"))
        claims = json.loads((d / "claims.json").read_text(encoding="utf-8")) if (d / "claims.json").exists() else None
        sdoc = SlideDoc.from_dict(sd)
        raw = {s.slide_no: s.raw_text for s in sdoc.slides}
        deck_text = _deck_text(sdoc)
        g = ConceptGraph.from_dict(graph)
        lines = [ln for t in raw.values() for ln in t.split("\n") if ln.strip()]
        truth = truths.get(d.name) or {}
        tr = truth.get("reason")
        entry = {"group": truth.get("group", "heldout"), "tracks": {}}
        for t in ("5", "10"):
            p = d / f"questions_t{t}.json"
            if not p.exists():
                continue
            qs = json.loads(p.read_text(encoding="utf-8")).get("questions") or []
            entry["tracks"][t] = {
                "reason": [gist_row(q, raw, tr) for q in qs if is_reason_question(q) and not _asks_phenomenon(q, raw, tr)],
                "phenomenon": [q["id"] for q in qs if is_reason_question(q) and _asks_phenomenon(q, raw, tr)],
                "choices": [choice_row(q, g, deck_text, lines) for q in qs if not q.get("trap")],
            }
        if tr:
            entry["planted"] = planted_row(d.name, sd, graph, claims, tr)
        result[d.name] = entry
    Path(ns.json).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {ns.json} ({len(result)}덱)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
