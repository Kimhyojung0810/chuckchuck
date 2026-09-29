"""
QA 일반화 벤치의 **순수 지표** — 단계 산출물(dict)과 정답(truth)을 받아 숫자와 사례를 돌려준다. LLM·파일을 안 만진다.

원문 대조는 f26 의 `verify_quote` 를 쓰지 않고 **따로** 한다 (같은 코드로 검사하면 같은 버그를 못 본다):
공백·따옴표·표 칸·글머리표·마크업을 지우고 소문자로 만든 뒤 부분 문자열인지만 본다. 퍼지 일치는 없다.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "qa_lab"))

from checks import judgement_flags, probe_outcome, question_flags  # noqa: E402

PROBE_KINDS = ("tension", "unsolved", "unsupported_cause", "absolute_boundary", "sibling_priority")
PLANTABLE = ("tension", "unsolved", "unsupported_cause", "absolute_boundary")
#: 음성 대조군 → 나오면 안 되는 탐침 종류
FORBIDDEN = {"supported_cause": "unsupported_cause", "hedged": "absolute_boundary", "unsolved": "unsolved",
             "tension": "tension",
             # 09-30 WP-P2 — 단정 표지는 있지만 따질 주장이 아닌 줄: 자기 자료에서 본 과거 관찰 · 늘어놓은 것 안에서 센 것 ·
             # 비용이 붙는 기제 · 정의
             "observation": "absolute_boundary", "count": "absolute_boundary", "mechanism": "absolute_boundary",
             "definition": "absolute_boundary"}

_TAG_RE = re.compile(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)")
_DROP_RE = re.compile(r"[\s\"'“”‘’「」『』`|•▪■◦*# ]+")
_DASH_RE = re.compile(r"[–—−]")
_ELLIPSIS_RE = re.compile(r"(…|\.\.\.)\s*$")
_PAGE_RE = re.compile(r"^[\d\s/|.·-]+$")
#: 단정 표지 — 이게 없는 인용을 absolute 로 적었으면 LLM 이 종류를 지어낸 것이다
ABSOLUTE_RE = re.compile(r"반드시|완전히|완전한|항상|언제나|절대|결코|모든|전혀|하나도|예외\s*없|100\s*%|무조건|늘\s")
#: 함정 질문의 골자가 전제를 바로잡는가 — 「전제」「사실은」「…가 아니라」「자료는 …라고」 같은 말
PREMISE_RE = re.compile(r"전제|사실은|사실과|아니라|아니에요|아닙니다|않아요|않습니다|자료(?:는|에서는)\s*\S+(?:라고|고)\s|오해|잘못")
#: 부정된 단정 — 「반드시 …는 아니다」「완전히 …지는 않는다」「없앨 수는 없지만」 은 오히려 유보다
NEGATED_RE = re.compile(r"(?:반드시|완전히|완전한|항상|모든)[^.,]{0,20}?(?:아니|않|어렵|없지|수는\s*없|수\s*없)")


def norm(text: str) -> str:
    text = _TAG_RE.sub(" ", text or "")
    text = _DASH_RE.sub("-", text)
    return _DROP_RE.sub("", text).lower()


def verbatim(quote: str, raw: str) -> bool:
    """인용이 원문에 글자 그대로 있는가 (정규화 뒤 부분 문자열). 끝의 「…」(잘림 표시)는 떼고 본다."""
    q = norm(_ELLIPSIS_RE.sub("", quote or ""))
    return len(q) >= 2 and q in norm(raw)


#: 식 조각·표 칸처럼 짧은 줄은 이어 붙여도 한 「줄」 로 친다
SHORT_LINE = 12


def single_line(quote: str, raw: str) -> bool:
    """인용이 원문 **한 줄**(또는 짧은 줄 조각이 이어진 식·표 한 덩이) 안에 있는가.
    False 면 여러 글 상자를 이어 붙인 인용이다 — 정규화가 줄바꿈을 지워서 대조를 통과했을 뿐이다."""
    q = norm(_ELLIPSIS_RE.sub("", quote or ""))
    lines = [norm(x) for x in (raw or "").split("\n") if x.strip()]
    if any(q in ln for ln in lines):
        return True
    for i in range(len(lines)):
        acc, longs = "", 0
        for ln in lines[i:i + 12]:
            longs += len(ln) > SHORT_LINE
            if longs > 1:
                break
            acc += ln
            if q in acc:
                return True
    return False


def slide_raw(slide_doc: dict) -> dict[int, str]:
    out = {}
    for s in slide_doc.get("slides") or []:
        raw = s.get("raw_text")
        if raw is None:
            raw = "\n".join(str(b.get("text", "")) for b in s.get("blocks") or [] if str(b.get("text", "")).strip())
        out[int(s["slide_no"])] = raw
    return out


def deck_texts(slide_doc: dict) -> list[str]:
    return [t for t in slide_raw(slide_doc).values() if t]


def _has_any(text: str, terms: list[str]) -> bool:
    n = norm(text)
    return any(len(norm(t)) >= 2 and norm(t) in n for t in terms or [])


def _labels(graph: dict) -> dict[str, dict]:
    return {n["id"]: n for n in graph.get("nodes") or []}


# ---------------------------------------------------------------------------
# 주장
# ---------------------------------------------------------------------------

def claim_metrics(claims: dict, slide_doc: dict, truth: dict | None) -> dict:
    raw = slide_raw(slide_doc)
    rows = claims.get("claims") or []
    quotes = [(c["kind"], e["slide_no"], e["quote"]) for c in rows for e in c.get("evidence") or []]
    bad = [(k, no, q) for k, no, q in quotes if not verbatim(q, raw.get(no, ""))]
    multi = [(k, no, q) for k, no, q in quotes if verbatim(q, raw.get(no, "")) and not single_line(q, raw.get(no, ""))]
    absolute_bad = [e["quote"] for c in rows if c["kind"] == "absolute" for e in c.get("evidence") or []
                    if not ABSOLUTE_RE.search(e["quote"]) or NEGATED_RE.search(e["quote"])]
    out = {
        "n": len(rows), "dropped": int(claims.get("dropped") or 0), "model": claims.get("model", ""),
        "by_kind": dict(Counter(c["kind"] for c in rows)),
        "quotes": len(quotes), "quotes_verbatim": len(quotes) - len(bad),
        "not_verbatim": [{"kind": k, "slide": no, "quote": q} for k, no, q in bad],
        "support_true": sum(1 for c in rows if c.get("has_support")),
        "quotes_multiline": len(multi),
        "multiline": [{"kind": k, "slide": no, "quote": q[:90]} for k, no, q in multi],
        "absolute": sum(1 for c in rows if c["kind"] == "absolute"),
        "absolute_no_marker": absolute_bad,
    }
    if truth and truth.get("claims"):
        hit, miss = [], []
        for t in truth["claims"]:
            ok = any(c["kind"] == t["kind"] and any(
                (not t.get("slide") or e["slide_no"] == t["slide"]) and _has_any(e["quote"], t["quote_any"])
                for e in c.get("evidence") or []) for c in rows)
            (hit if ok else miss).append(f"{t['kind']}@{t.get('slide')}:{t['quote_any'][0]}")
        out.update(planted=len(truth["claims"]), planted_hit=len(hit), planted_miss=miss)
    return out


# ---------------------------------------------------------------------------
# 탐침
# ---------------------------------------------------------------------------

def probe_matches(p: dict, item: dict, graph_by: dict[str, dict]) -> bool:
    """탐침 p 가 심은 항목 item 을 짚었는가. 대상 개념 라벨 또는 (unsolved 가 아니면) 근거 인용으로 본다."""
    target = graph_by.get((p.get("node_ids") or [""])[0], {}).get("label", "")
    if _has_any(target, item.get("labels_any") or []):
        return True
    if item["kind"] == "unsolved":
        return False   # 같은 compose 인용을 형제 요소 탐침도 들고 있어 인용으로는 못 가른다
    return any(_has_any(e.get("quote", ""), item.get("quote_any") or []) for e in p.get("evidence") or [])


def label_natural(label: str, quotes: list[str]) -> bool:
    """
    개념 이름이 **자료의 낱말**인가 — 이름의 토큰이 전부 근거 인용 안에 나온다(조사 허용).
    F-08 은 LLM 질문이 탐침 개념 이름을 다 불러야 받는다. 이름이 자료에 없는 말(「전세사기 완전 소멸」)이면
    LLM 이 그 말을 안 쓰고, 코드가 템플릿으로 떨어진다 — 템플릿 폴백률의 앞쪽 원인을 따로 잰다.
    """
    from chuckchuck._claim_rules import mention_score

    text = " ".join(quotes)
    return bool(label) and mention_score(label, text) >= 1.0


def probe_metrics(probes: list[dict], graph: dict, truth: dict | None) -> dict:
    by = _labels(graph)
    natural = [all(label_natural(by.get(i, {}).get("label", ""), [e.get("quote", "") for e in p.get("evidence") or []])
                   for i in p["node_ids"]) for p in probes]
    out: dict = {"n": len(probes), "by_kind": dict(Counter(p["kind"] for p in probes)), "natural": sum(natural),
                 "list": [{"kind": p["kind"], "target": by.get(p["node_ids"][0], {}).get("label", p["node_ids"][0]),
                           "nodes": [by.get(i, {}).get("label", i) for i in p["node_ids"]],
                           "evidence": [f"S{e['slide_no']} «{e['quote'][:60]}»" for e in p.get("evidence") or []]}
                          for p in probes]}
    if not truth:
        return out
    planted = [t for t in truth.get("planted") or [] if t["expect"] == "probe"]
    negatives = [t for t in truth.get("planted") or [] if t["expect"] == "no_probe"]
    recall = {}
    for t in planted:
        recall[t["id"]] = any(p["kind"] == t["kind"] and probe_matches(p, t, by) for p in probes)
    tp_idx = set()
    for i, p in enumerate(probes):
        if any(p["kind"] == t["kind"] and probe_matches(p, t, by) for t in planted):
            tp_idx.add(i)
    plantable = [i for i, p in enumerate(probes) if p["kind"] in PLANTABLE]
    fps = []
    for t in negatives:
        forbidden = FORBIDDEN.get(t["kind"], "")
        for p in probes:
            if p["kind"] == forbidden and any(_has_any(e.get("quote", ""), t.get("quote_any") or []) for e in p.get("evidence") or []) \
                    and not any(p["kind"] == x["kind"] and probe_matches(p, x, by) for x in planted):
                fps.append(f"{t['id']}({t['kind']})→{p['kind']}:{by.get(p['node_ids'][0], {}).get('label', '')}")
    out.update(
        planted=len(planted), planted_hit=sum(recall.values()), recall_by_id=recall,
        recall_by_kind={k: [sum(1 for t in planted if t["kind"] == k and recall[t["id"]]),
                            sum(1 for t in planted if t["kind"] == k)] for k in PLANTABLE},
        plantable_probes=len(plantable), plantable_tp=len(tp_idx & set(plantable)),
        unplanted=[out["list"][i] for i in plantable if i not in tp_idx],
        negative_fp=fps,
        control_tension=bool(truth.get("control_tension")),
        false_tension=sum(1 for p in probes if p["kind"] == "tension") if truth.get("control_tension") else 0,
    )
    return out


# ---------------------------------------------------------------------------
# 질문
# ---------------------------------------------------------------------------

def _lcs_len(a: str, b: str) -> int:
    """가장 긴 공통 부분 문자열 길이 (짧은 문장끼리라 O(nm) 로 충분)."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ch in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ch == cb:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


#: 질문이 자료 한 줄을 이만큼 이상 그대로 옮기면 「되읊기」 후보로 본다 (정규화 뒤 글자 수).
RECITE_MIN = 16


def recites(question: str, raw: dict[int, str]) -> str:
    """질문 문장이 자료의 한 줄을 RECITE_MIN 자 이상 그대로 싣는가 — 실었으면 그 줄."""
    qn = norm(question)
    best, line = 0, ""
    for text in raw.values():
        for ln in text.split("\n"):
            n = _lcs_len(qn, norm(ln))
            if n > best:
                best, line = n, ln
    return line if best >= RECITE_MIN else ""


def _undercut(text: str) -> str:
    from chuckchuck.f08_questions import _self_undercut
    return _self_undercut(text)


def _drop_expected_numbers(flags: list[str], q: dict, n_slides: int) -> list[str]:
    """「자료밖숫자!」 중 **일부러 넣은 것**은 뺀다 — 함정 전제의 바꾼 값(설계상 자료에 없다)과 「N장」(장 번호)."""
    premise = str((q.get("trap_premise") or {}).get("premise", "") or "")
    out = []
    for f in flags:
        if not f.startswith("자료밖숫자!"):
            out.append(f)
            continue
        left = []
        for tok in f.removeprefix("자료밖숫자!").split("·"):
            digits = re.sub(r"[^\d.,]", "", tok)
            if tok.endswith("장") and digits.isdigit() and int(digits) <= n_slides:
                continue
            if q.get("trap") and digits and digits in premise:
                continue
            left.append(tok)
        if left:
            out.append("자료밖숫자!" + "·".join(left))
    return out


def question_metrics(qdoc: dict, graph: dict, slide_doc: dict, truth: dict | None) -> dict:
    qs = qdoc.get("questions") or []
    raw = slide_raw(slide_doc)
    texts = deck_texts(slide_doc)
    by = _labels(graph)
    planted = [t for t in (truth or {}).get("planted") or [] if t["expect"] == "probe"]
    rows = []
    for q in qs:
        b = q.get("basis") or {}
        ev = b.get("evidence") or []
        probe = b.get("probe")
        checks = b.get("checks") or []
        flags = _drop_expected_numbers(question_flags(q, None, texts), q, len(raw))
        node = by.get(q["node_id"], {})
        planted_hit = ""
        if probe:
            planted_hit = next((t["id"] for t in planted if probe["kind"] == t["kind"] and probe_matches(probe, t, by)), "")
        mention_hit = next((t["id"] for t in planted if _has_any(q["question"], t.get("labels_any") or [])), "")
        rows.append({
            "id": q["id"], "label": q["label"], "question": q["question"], "gist": q.get("answer_gist", ""),
            "source": q.get("source"), "slot": b.get("slot", ""), "depth": node.get("depth"),
            "weight": node.get("weight"), "trap": bool(q.get("trap")),
            "basis": bool(b), "basis_evidence": len(ev),
            "basis_verbatim": all(verbatim(e["quote"], raw.get(e["slide_no"], "")) for e in ev) if ev else None,
            "basis_bad": [f"S{e['slide_no']} «{e['quote'][:50]}»" for e in ev if not verbatim(e["quote"], raw.get(e["slide_no"], ""))],
            "probe": probe["kind"] if probe else "", "probe_template": "probe_template" in checks,
            "checks": checks, "undercut": _undercut(q["question"]), "recite": recites(q["question"], raw),
            "flags": flags, "bad_flags": [f for f in flags if "!" in f], "planted_probe": planted_hit,
            "planted_mention": mention_hit, "slide_nos": q.get("slide_nos") or [],
            "evidence_slide_no": q.get("evidence_slide_no"), "evidence_quote": q.get("evidence_quote", ""),
        })
    n = len(rows) or 1
    probe_rows = [r for r in rows if r["probe"]]
    roots = sorted((x for x in by.values() if x.get("depth") == 1), key=lambda x: -float(x.get("weight") or 0))
    theme = [r for r in rows if r["slot"] == "theme"]
    return {
        "n": len(rows),
        "basis_share": sum(r["basis"] for r in rows) / n,
        "basis_evidence_share": sum(1 for r in rows if r["basis_evidence"]) / n,
        "basis_verbatim_share": sum(1 for r in rows if r["basis_verbatim"]) / n,
        "undercut": sum(1 for r in rows if r["undercut"]),
        "recite": sum(1 for r in rows if r["recite"]),
        "probe_bound": len(probe_rows),
        "probe_template": sum(1 for r in probe_rows if r["probe_template"]),
        "bad_flags": dict(Counter(re.sub(r"\d+|·.*$", "", f) for r in rows for f in r["bad_flags"])),
        "hapsyo": sum(1 for r in rows if any(f.startswith("합쇼체") for f in r["flags"])),
        "flag_counts": {k: sum(1 for r in rows if any(f.startswith(k) for f in r["flags"]))
                        for k in ("반말끝", "높임", "잘림", "합쇼체", "자료밖숫자", "3인칭", "노드id노출")},
        "fallback": sum(1 for r in rows if "폴백" in r["flags"] or "fallback_template" in r["checks"]),
        "slots": dict(Counter(r["slot"] or "-" for r in rows)),
        "trap": sum(1 for r in rows if r["trap"]),
        "trap_gist_uncorrected": [r["id"] for r in rows if r["trap"] and not PREMISE_RE.search(r["gist"])],
        "trap_on_probe": sum(1 for r in rows if r["trap"] and r["probe"]),
        "sources": dict(Counter(r["source"] for r in rows)),
        "theme_is_root": bool(theme) and theme[0]["depth"] == 1,
        "theme_is_top_root": bool(theme and roots) and theme[0]["label"] == roots[0]["label"],
        "top_root": roots[0]["label"] if roots else "",
        "planted_probe_q": sorted({r["planted_probe"] for r in rows if r["planted_probe"]}),
        "planted_mention_q": sorted({r["planted_mention"] for r in rows if r["planted_mention"]}),
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# 힌트
# ---------------------------------------------------------------------------

_POLLISH_RE = re.compile(r"(?:\d+\s*(?:시간|시|분)\s*(?:미만|이상|이후)?|[①②③④]|\d+\s*[–~-]\s*\d+\s*시간)")


def noise_quote(quote: str, noise_lines: list[str]) -> str:
    """힌트 인용이 설문 보기·쪽 번호 조각인가 — 그렇다면 까닭."""
    q = (quote or "").strip()
    if not q:
        return ""
    if _PAGE_RE.match(q):
        return "쪽번호"
    hits = [ln for ln in noise_lines or [] if len(norm(ln)) >= 2 and not _PAGE_RE.match(ln) and norm(ln) in norm(q)]
    if len(hits) >= 2:
        return "설문보기:" + "·".join(hits[:3])
    if len(_POLLISH_RE.findall(q)) >= 2 and len(re.findall(r"[가-힣]{2,}", q)) <= 6:
        return "보기조각"
    if re.search(r"(?:^|\s)\d{1,2}\s*/\s*\d{1,2}(?:\s|$)", q):
        return "쪽번호섞임"
    return ""


#: 질문·힌트 낱말 겹침에서 빼는 물음 틀 낱말
_Q_STOP = {"무엇", "무엇인가요", "어떤", "어떻게", "어느", "있나요", "했는데", "라고", "이라고", "대해", "설명해", "주세요",
           "경우", "의미", "근거", "이유", "자료", "발표", "말씀", "생각", "그렇게", "있는", "하는", "것은", "것이", "이런", "그런"}
_JOSA_TAIL = re.compile(r"(?:으로|에서|에게|까지|부터|처럼|보다|이라|이나|라고|은|는|이|가|을|를|의|에|와|과|도|로|만)$")


def content_words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[가-힣A-Za-z0-9%.]{2,}", _TAG_RE.sub(" ", text or "")):
        w = _JOSA_TAIL.sub("", w) if len(w) > 2 else w
        if len(w) >= 2 and w not in _Q_STOP:
            out.add(w)
    return out


def overlap(question: str, quote: str) -> int:
    """질문 내용 낱말 중 힌트 인용에 (앞 두 글자 이상 줄기로) 나오는 것의 수."""
    qn = norm(quote)
    return sum(1 for w in content_words(question) if norm(w[:max(2, len(w) - 1)]) in qn)


#: 되물음 선택지가 명사(구)가 아닌 꼴 — 활용 어미·명사형 어미·조사로 끝난다 (09-29 기준선: '중요함'·'늘릴수록'·'차지해'·'설명할')
_NOT_NOUN_RE = re.compile(r"(?:다|요|함|됨|음|할|했|해서|하는|하게|하고|하며|수록|지만|면서|겠|된|되는|돼|해|은|는|을|를|의|에|로)$")
_NOUN_OK = {"올해", "피해", "이해", "방해", "손해", "재해", "마음", "처음", "다음", "소음", "얼음", "기로", "도로", "경로", "진로",
}


def choice_quality(choices: list[str], deck_text: str, quote: str = "") -> dict:
    """「모르겠어요」·발판 선택지 둘이 **명사(구)** 이고 **자료에 글자 그대로** 있는가 (정규화 부분 문자열)."""
    def noun(c: str) -> bool:
        last = (re.findall(r"[가-힣A-Za-z0-9%]+", c) or [""])[-1]
        # 셋 글자 이상이 「지」로 끝나면 용언 줄기(「떨어지」「보이지」) — 「유지」「의지」 같은 두 글자 명사는 둔다
        stem = len(last) >= 3 and last.endswith("지")
        return bool(last) and (last in _NOUN_OK or not (_NOT_NOUN_RE.search(last) or stem))
    dn = norm(deck_text)
    return {"n": len(choices), "noun": bool(choices) and all(noun(c) for c in choices),
            "in_deck": bool(choices) and all(norm(c) and norm(c) in dn for c in choices),
            "in_quote": bool(choices and quote) and sum(1 for c in choices if norm(c) in norm(quote)) >= 1,
            "choices": list(choices)}


def hint_metrics(qdoc: dict, slide_doc: dict, truth: dict | None, ladders: dict[str, list[str]]) -> dict:
    raw = slide_raw(slide_doc)
    planted = {t["id"]: t for t in (truth or {}).get("planted") or []}
    noise = (truth or {}).get("noise_lines") or []
    rows = []
    for q in qdoc.get("questions") or []:
        b = q.get("basis") or {}
        probe = b.get("probe")
        quote, no = q.get("evidence_quote", ""), q.get("evidence_slide_no") or 0
        ladder = ladders.get(q["id"]) or []
        in_probe = None
        on_planted = None
        if probe:
            in_probe = any(norm(_ELLIPSIS_RE.sub("", quote)) in norm(e["quote"]) or norm(e["quote"]) in norm(quote)
                           for e in probe.get("evidence") or []) if quote else False
        rows.append({
            "id": q["id"], "has_quote": bool(quote), "slide_ok": (no in (q.get("slide_nos") or [])) if quote else None,
            "slide_in_probe": (no in {e["slide_no"] for e in probe.get("evidence") or []}) if (quote and probe) else None,
            "verbatim": verbatim(quote, raw.get(no, "")) if quote else None,
            "in_probe_evidence": in_probe, "noise": noise_quote(quote, noise), "quote": quote, "slide": no,
            "ladder_len": len(ladder), "locate_first": bool(ladder) and ladder[0].startswith("자료"),
            "overlap": overlap(q.get("question", ""), quote) if quote else None,
            "probe": probe["kind"] if probe else "",
        })
    # 탐침이 심은 항목을 짚은 질문이면, 힌트 인용이 그 항목의 근거 줄인가
    for r, q in zip(rows, qdoc.get("questions") or []):
        probe = (q.get("basis") or {}).get("probe")
        if not probe:
            continue
        for t in planted.values():
            if t["expect"] == "probe" and t["kind"] == probe["kind"] and r["quote"]:
                if _has_any(r["quote"], t.get("quote_any") or []) or _has_any(r["quote"], t.get("labels_any") or []):
                    r["planted_line"] = t["id"]
    n = len(rows) or 1
    quoted = [r for r in rows if r["has_quote"]]
    probe_rows = [r for r in rows if r["probe"]]
    return {
        "n": len(rows), "quoted": len(quoted),
        "slide_ok": sum(1 for r in quoted if r["slide_ok"]),
        "verbatim": sum(1 for r in quoted if r["verbatim"]),
        "probe_q": len(probe_rows),
        "probe_in_evidence": sum(1 for r in probe_rows if r["in_probe_evidence"]),
        "noise": [f"{r['id']}: {r['noise']} «{r['quote'][:50]}»" for r in rows if r["noise"]],
        "locate_first": sum(1 for r in rows if r["locate_first"]) / n,
        "overlap_any": sum(1 for r in quoted if (r["overlap"] or 0) >= 1),
        "overlap_zero": [f"{r['id']}: S{r['slide']} «{r['quote'][:50]}»" for r in quoted if not r["overlap"]],
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# 판정
# ---------------------------------------------------------------------------

EXPECT = {"gist": "pass", "paraphrase": "pass", "offtopic": "wrong", "wrong": "not_pass", "dunno": "coach",
          "restate": "not_pass"}


def judge_row(kind: str, j: dict) -> dict:
    outcome = probe_outcome(j)
    exp = EXPECT[kind]
    ok = outcome != "pass" if exp == "not_pass" else outcome == exp
    return {"kind": kind, "verdict": j.get("verdict"), "score": j.get("score"), "outcome": outcome,
            "expect": exp, "ok": ok, "flags": judgement_flags(j), "react": j.get("react", ""),
            "missing": j.get("missing_points") or [], "followup": j.get("followup", ""),
            "choices": j.get("choices") or [], "coach_stage": j.get("coach_stage", ""),
            "explanation": (j.get("explanation") or "")[:200]}


def judge_metrics(records: list[dict]) -> dict:
    by_kind: dict[str, list[int]] = {}
    for r in records:
        s = by_kind.setdefault(r["kind"], [0, 0])
        s[0] += 1 if r["ok"] else 0
        s[1] += 1
    return {"n": len(records), "ok": sum(1 for r in records if r["ok"]), "by_kind": by_kind,
            "contradicts": [r for r in records if not r["ok"] and r["kind"] in ("gist", "paraphrase", "wrong", "offtopic")]}


# ---------------------------------------------------------------------------
# 안정성
# ---------------------------------------------------------------------------

def _jac(a: set, b: set) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def stability_metrics(runs: list[dict], graph: dict) -> dict:
    by = _labels(graph)
    nodes = [{q["node_id"] for q in r.get("questions") or []} for r in runs]
    probed = [{(by.get(q["node_id"], {}).get("label", q["node_id"]), (q.get("basis") or {}).get("probe", {}).get("kind"))
               for q in r.get("questions") or [] if (q.get("basis") or {}).get("probe")} for r in runs]
    tmpl = [sum(1 for q in r.get("questions") or [] if "probe_template" in ((q.get("basis") or {}).get("checks") or []))
            for r in runs]
    pairs = list(combinations(range(len(runs)), 2))
    return {
        "runs": len(runs),
        "node_jaccard": sum(_jac(nodes[i], nodes[j]) for i, j in pairs) / max(1, len(pairs)),
        "probe_jaccard": sum(_jac(probed[i], probed[j]) for i, j in pairs) / max(1, len(pairs)),
        "probe_sets": [sorted(f"{lab}/{k}" for lab, k in s) for s in probed],
        "probe_counts": [len(s) for s in probed],
        "templates": tmpl,
        "questions": [[q["question"] for q in r.get("questions") or []] for r in runs],
    }
