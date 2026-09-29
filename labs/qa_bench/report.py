"""
벤치 결과(results.json 모양) → `metrics.md`(표·사례, 자동 생성) + `metrics.json`. 사람이 쓰는 해석은 report.md 에.
held-out(안 본 덱)이 머리 숫자다 — 튜닝에 쓴 덱(tuned)은 따로 센다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

GROUPS = (("heldout", "held-out (안 본 덱)"), ("tuned", "tuned-on (튜닝에 쓴 덱: 수면·수익률격차)"))


def pct(a: float, b: float) -> str:
    return "-" if not b else f"{100 * a / b:.0f}% ({a:g}/{b:g})"


def _sum(rows, f):
    return sum(f(r) for r in rows)


def agg(rows: list[dict], track: str) -> dict[str, str]:
    rows = [r for r in rows if not r.get("incomplete")]
    qrows = [r["questions"][track] for r in rows if track in r.get("questions", {})]
    hrows = [r["hints"][track] for r in rows if track in r.get("hints", {})]
    truthy = [r for r in rows if "planted" in r["probes"]]
    nq = _sum(qrows, lambda q: q["n"])
    probe_q = _sum(qrows, lambda q: q["probe_bound"])
    quoted = _sum(hrows, lambda h: h["quoted"])
    hp = _sum(hrows, lambda h: h["probe_q"])
    judge = [r["judge"] for r in rows if r.get("judge")]
    by_kind: dict[str, list[int]] = {}
    for j in judge:
        for k, (ok, n) in j["by_kind"].items():
            s = by_kind.setdefault(k, [0, 0])
            s[0] += ok
            s[1] += n
    recall_kind: dict[str, list[int]] = {}
    for r in truthy:
        for k, (a, b) in r["probes"]["recall_by_kind"].items():
            s = recall_kind.setdefault(k, [0, 0])
            s[0] += a
            s[1] += b
    ctrl = [r for r in truthy if r["probes"].get("control_tension")]
    claim_truth = [r for r in rows if "planted" in r["claims"]]
    return {
        "덱": str(len(rows)),
        "장·노드": f"{_sum(rows, lambda r: r['slides'])}장 · {_sum(rows, lambda r: r['nodes'])}개",
        "주장 수 (버린 후보)": f"{_sum(rows, lambda r: r['claims']['n'])} ({_sum(rows, lambda r: r['claims']['dropped'])})",
        "주장 인용 원문 그대로": pct(_sum(rows, lambda r: r['claims']['quotes_verbatim']), _sum(rows, lambda r: r['claims']['quotes'])),
        "주장 인용 중 여러 글 상자를 이어 붙인 것": pct(_sum(rows, lambda r: r['claims'].get('quotes_multiline', 0)), _sum(rows, lambda r: r['claims']['quotes'])),
        "absolute 주장 중 단정 표지 없음·부정됨": pct(_sum(rows, lambda r: len(r['claims'].get('absolute_no_marker', []))), _sum(rows, lambda r: r['claims'].get('absolute', 0))),
        "심은 주장 재현율": pct(_sum(claim_truth, lambda r: r['claims']['planted_hit']), _sum(claim_truth, lambda r: r['claims']['planted'])),
        "심은 탐침 재현율": pct(_sum(truthy, lambda r: r['probes']['planted_hit']), _sum(truthy, lambda r: r['probes']['planted'])),
        **{f"  └ {k}": pct(v[0], v[1]) for k, v in recall_kind.items() if v[1]},
        "탐침 정밀도 (심은 것과 맞은 비율)": pct(_sum(truthy, lambda r: r['probes']['plantable_tp']), _sum(truthy, lambda r: r['probes']['plantable_probes'])),
        "음성 대조군 오탐 (유보→단정·수치 인과→근거없음·다룬 요소→unsolved)": str(_sum(truthy, lambda r: len(r['probes']['negative_fp']))),
        "대조군 덱의 거짓 긴장": f"{_sum(ctrl, lambda r: r['probes']['false_tension'])} (대조군 {len(ctrl)}덱)",
        "sibling_priority 탐침 / 전체 탐침": f"{_sum(rows, lambda r: r['probes']['by_kind'].get('sibling_priority', 0))} / {_sum(rows, lambda r: r['probes']['n'])}",
        "탐침 개념 이름이 전부 근거 인용 속 낱말": pct(_sum(rows, lambda r: r['probes'].get('natural', 0)), _sum(rows, lambda r: r['probes']['n'])),
        f"질문 수 (t{track})": str(nq),
        "근거(basis) 있음": pct(_sum(qrows, lambda q: q['basis_share'] * q['n']), nq),
        "근거 인용이 전부 원문 그대로": pct(_sum(qrows, lambda q: q['basis_verbatim_share'] * q['n']), nq),
        "자기모순 문장(_self_undercut)": str(_sum(qrows, lambda q: q['undercut'])),
        "자료 줄 되읊기(16자+)": pct(_sum(qrows, lambda q: q['recite']), nq),
        "탐침에 묶인 질문": pct(probe_q, nq),
        "탐침 질문 중 템플릿으로 떨어짐": pct(_sum(qrows, lambda q: q['probe_template']), probe_q),
        "함정 질문 (그중 탐침 질문)": f"{_sum(qrows, lambda q: q.get('trap', 0))} ({_sum(qrows, lambda q: q.get('trap_on_probe', 0))})",
        "함정인데 골자가 전제를 안 바로잡음": pct(_sum(qrows, lambda q: len(q.get('trap_gist_uncorrected', []))), _sum(qrows, lambda q: q.get('trap', 0))),
        "화면 금지 표식(!)": str(_sum(qrows, lambda q: sum(q['bad_flags'].values()))),
        "합쇼체 남음": str(_sum(qrows, lambda q: q['hapsyo'])),
        "주제 자리가 루트(depth 1)": pct(_sum(qrows, lambda q: 1 if q['theme_is_root'] else 0), len(qrows)),
        "주제 자리가 가장 무거운 루트": pct(_sum(qrows, lambda q: 1 if q['theme_is_top_root'] else 0), len(qrows)),
        "심은 항목을 탐침으로 물은 수": str(_sum(qrows, lambda q: len(q['planted_probe_q']))),
        "힌트 인용 있음": pct(quoted, nq),
        "힌트 인용 장이 질문 장 안": pct(_sum(hrows, lambda h: h['slide_ok']), quoted),
        "힌트 인용 원문 그대로": pct(_sum(hrows, lambda h: h['verbatim']), quoted),
        "탐침 질문의 힌트가 탐침 근거 줄": pct(_sum(hrows, lambda h: h['probe_in_evidence']), hp),
        "힌트가 설문 보기·쪽 번호 조각": str(_sum(hrows, lambda h: len(h['noise']))),
        "판정 기대대로": pct(_sum(judge, lambda j: j['ok']), _sum(judge, lambda j: j['n'])),
        **{f"  └ {k}": pct(v[0], v[1]) for k, v in sorted(by_kind.items())},
    }


def agg_table(results: list[dict], track: str) -> list[str]:
    cols = [(g, [r for r in results if r.get("group") == g]) for g, _ in GROUPS]
    cols.append(("전체", [r for r in results if not r.get("incomplete")]))
    tables = [agg(rows, track) for _, rows in cols]
    keys = list(dict.fromkeys(k for t in tables for k in t))
    head = "| 지표 | " + " | ".join(dict(GROUPS).get(g, g) for g, _ in cols) + " |"
    lines = [head, "|" + "---|" * (len(cols) + 1)]
    for k in keys:
        lines.append(f"| {k} | " + " | ".join(t.get(k, "-") for t in tables) + " |")
    return lines


def deck_table(results: list[dict]) -> list[str]:
    lines = ["| 덱 | 묶음 | 경로 | 장 | 노드 | 주장(버림) | 인용 그대로 | 탐침 재현 | 탐침 정밀 | 오탐 | 탐침 종류 | t5 탐침질문(템플릿) | t10 탐침질문(템플릿) | t10 !표식 | 힌트 잡음 | 판정 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        if r.get("incomplete"):
            lines.append(f"| {r['name']} | - | 미완 | | | | | | | | | | | | | |")
            continue
        c, p = r["claims"], r["probes"]
        q5, q10 = r["questions"].get("5"), r["questions"].get("10")
        h10 = r["hints"].get("10") or r["hints"].get("5") or {"noise": []}
        kinds = " ".join(f"{k[:4]}{v}" for k, v in sorted(p["by_kind"].items()))
        j = r.get("judge")
        lines.append(
            f"| {r['name']} | {r['group']} | {'pptx→f01' if r['live'] else 'SlideDoc'} | {r['slides']} | {r['nodes']} | {c['n']}({c['dropped']}) "
            f"| {c['quotes_verbatim']}/{c['quotes']} | {str(p.get('planted_hit', '-')) + '/' + str(p.get('planted', '-')) if 'planted' in p else '-'} "
            f"| {str(p['plantable_tp']) + '/' + str(p['plantable_probes']) if 'planted' in p else '-'} | {len(p.get('negative_fp', [])) + p.get('false_tension', 0) if 'planted' in p else '-'} "
            f"| {kinds or '-'} | {(str(q5['probe_bound']) + '(' + str(q5['probe_template']) + ')') if q5 else '-'} "
            f"| {(str(q10['probe_bound']) + '(' + str(q10['probe_template']) + ')') if q10 else '-'} | {sum(q10['bad_flags'].values()) if q10 else '-'} "
            f"| {len(h10['noise'])} | {str(j['ok']) + '/' + str(j['n']) if j else '-'} |")
    return lines


def deck_detail(r: dict) -> list[str]:
    if r.get("incomplete"):
        return [f"### {r['name']} — 미완", ""]
    out = [f"### {r['name']} ({r['group']}{', pptx→f01 라이브' if r['live'] else ''})", ""]
    if r.get("note"):
        out.append(f"_{r['note']}_\n")
    if r.get("parse"):
        pf = r["parse"]
        out.append(f"- 파싱 충실도: 저작 줄 {pf['lines_kept']}/{pf['lines']} 이 파싱 결과 같은 장에 그대로 · 장 {pf['slides_parsed']}/{pf['slides_authored']}"
                   + (f" · 빠진 줄: {', '.join(pf['missing'][:6])}" if pf["missing"] else ""))
    c, p = r["claims"], r["probes"]
    out.append(f"- 주장 {c['n']}개 {c['by_kind']} · 버린 후보 {c['dropped']} · model={c['model']} · 원문 아님 {len(c['not_verbatim'])}"
               + (f" · 심은 주장 {c['planted_hit']}/{c['planted']}" + (f" (놓침: {'; '.join(c['planted_miss'])})" if c['planted_miss'] else "") if 'planted' in c else ""))
    if c.get("quotes_multiline"):
        out.append(f"  - 여러 줄 이어 붙인 인용 {c['quotes_multiline']}개: " + "; ".join(f"{m['kind']} S{m['slide']} «{m['quote'][:60]}»" for m in c["multiline"][:3]))
    if c.get("absolute_no_marker"):
        out.append("  - 단정 표지 없는 absolute: " + "; ".join(f"«{q[:50]}»" for q in c["absolute_no_marker"][:4]))
    for bad in c["not_verbatim"][:4]:
        out.append(f"  - 원문 아닌 인용: {bad['kind']} S{bad['slide']} «{bad['quote'][:70]}»")
    out.append(f"- 탐침 {p['n']}개 (캐시된 1차 심사 {r['probes_cached_triage']}개):")
    for pr in p["list"]:
        out.append(f"  - `{pr['kind']}` → **{pr['target']}** ({' · '.join(pr['nodes'])}) {' '.join(pr['evidence'][:2])}")
    if "planted" in p:
        miss = [k for k, v in p["recall_by_id"].items() if not v]
        out.append(f"- 심은 탐침 {p['planted_hit']}/{p['planted']}" + (f" · 놓친 것 {miss}" if miss else ""))
        if p["unplanted"]:
            out.append("- 심지 않은 탐침(검토 필요): " + "; ".join(f"{u['kind']}→{u['target']}" for u in p["unplanted"]))
        if p["negative_fp"]:
            out.append("- **오탐**: " + "; ".join(p["negative_fp"]))
        if p.get("false_tension"):
            out.append(f"- **대조군인데 긴장 {p['false_tension']}개**")
    for t in ("5", "10"):
        q = r["questions"].get(t)
        if not q:
            continue
        out.append(f"\n**질문 t{t}** — 자리 {q['slots']} · 근거 {q['sources']} · 주제 자리 루트={q['theme_is_root']} (가장 무거운 루트 「{q['top_root']}」={q['theme_is_top_root']})\n")
        hrows = {h['id']: h for h in r["hints"][t]["rows"]}
        for row in q["rows"]:
            hr = hrows.get(row["id"], {})
            marks = []
            if row["probe"]:
                marks.append(f"탐침:{row['probe']}" + ("·템플릿" if row["probe_template"] else ""))
            if row["planted_probe"]:
                marks.append(f"심은:{row['planted_probe']}")
            if row["undercut"]:
                marks.append("자기모순!")
            if row["recite"]:
                marks.append("되읊기")
            if row["basis_verbatim"] is False:
                marks.append("근거인용≠원문!")
            if hr.get("noise"):
                marks.append(f"힌트잡음:{hr['noise']}")
            if hr.get("in_probe_evidence") is False:
                marks.append("힌트≠탐침근거")
            if hr.get("slide_ok") is False:
                marks.append("힌트장≠질문장")
            marks += row["bad_flags"]
            out.append(f"- [{row['slot'] or '-'}/{row['source']}] **{row['label']}** — {row['question']}  `{' '.join(marks)}`")
            if hr.get("quote"):
                out.append(f"  - 힌트 S{hr['slide']} «{hr['quote'][:90]}»")
    if r.get("recording"):
        rm = r["recording"]
        out.append(f"\n**녹음 경로 t5** — 근거 {rm['sources']} · 덜 말한 핵심 장 개념을 물음: {rm['under_spoken_asked'] or '없음'}\n")
        for row in rm["rows"]:
            out.append(f"- [{row['slot'] or '-'}/{row['source']}] **{row['label']}** — {row['question']}  `{'탐침:' + row['probe'] if row['probe'] else ''}`")
    if r.get("stability"):
        s = r["stability"]
        out.append(f"\n**안정성** ({s['runs']}회) — 대상 개념 자카드 {s['node_jaccard']:.2f} · 탐침 질문 자카드 {s['probe_jaccard']:.2f} · "
                   f"탐침 질문 수 {s['probe_counts']} · 템플릿 {s['templates']}")
        for i, ps in enumerate(s["probe_sets"], 1):
            out.append(f"  - {i}회: {ps}")
    if r.get("judge_rows"):
        out.append("\n**판정 표본**\n")
        for j in r["judge_rows"]:
            out.append(f"- {'✓' if j['ok'] else '✗'} `{j['kind']}` {j['verdict']} {j['score']} ({j['outcome']}, 기대 {j['expect']}) "
                       f"{' '.join(j['flags'])} — Q「{j['question'][:60]}」 A「{j['answer'][:60]}」 → {j['react'][:60]}")
    out.append("")
    return out


#: 노드 id 「sk-hynix-2026q2-…」 가 커밋 문지기의 비밀키 패턴(`sk-` + 16자)에 걸린다 — 표에서만 「sk_」 로 바꾼다.
_SK_ID_RE = re.compile(r"\bsk-(?=[A-Za-z0-9_-]{16,})")


def _safe(text: str) -> str:
    return _SK_ID_RE.sub("sk_", text)


def write(results: list[dict], out_dir: Path, calls: int = 0) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    slim = [{k: v for k, v in r.items()} for r in results]
    (out_dir / "metrics.json").write_text(_safe(json.dumps(slim, ensure_ascii=False, indent=1)), encoding="utf-8")
    lines = ["# QA 일반화 벤치 — 자동 생성 표", "",
             "`labs/qa_bench/run.py` 가 쓴다. 손으로 고치지 않는다 — 해석은 [report.md](report.md).",
             f"누적 LLM 호출 {calls}회 (`labs/qa_bench/out/calls.jsonl`).", ""]
    for t in ("5", "10"):
        if any(t in r.get("questions", {}) for r in results):
            lines += [f"## 묶음별 합계 — 질문 트랙 {t}", ""] + agg_table(results, t) + [""]
    lines += ["## 덱별", ""] + deck_table(results) + ["", "## 덱별 상세", ""]
    for r in results:
        lines += deck_detail(r)
    (out_dir / "metrics.md").write_text(_safe("\n".join(lines)), encoding="utf-8")
