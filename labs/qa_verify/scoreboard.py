"""
점수판 — 지표 값 · 기준(임계) 판정 · 기준선 대비 차이 · 회귀 여부 · 종료 코드. 쓰기는 json + md + history.jsonl.

지표 하나 = {"value": float|None, "n": 분모(표본 수), "examples": [실패 예시 인용…]}.
스펙(SPECS)은 이름 틀(fnmatch)로 찾는다 — 방향(higher/lower) · 기준 · 허용 오차 · LLM 지표인가(표본 오차로 허용폭을 넓힌다) · hard.

회귀 = 기준선과 같은 지표가 나쁜 쪽으로 허용 오차보다 더 움직였다. 결정적 지표(quick)는 허용 오차 0 이 기본이다 —
같은 입력에 같은 코드면 값이 같아야 하므로 움직였다면 코드가 바뀐 것이다. LLM 지표는 두 비율의 표본 오차(z=1.64)만큼 넓힌다.
종료 코드 1: 회귀가 하나라도 있거나 · 회귀 사례가 하나라도 실패했거나 · hard 지표가 기준을 못 넘었다.
"""

from __future__ import annotations

import fnmatch
import math
from dataclasses import dataclass

from . import common as C


@dataclass(frozen=True)
class Spec:
    label: str
    direction: str = "lower"          # higher | lower | info
    threshold: float | None = None
    tol: float = 0.0
    llm: bool = False
    hard: bool = False
    unit: str = "ratio"               # ratio | count | sec


#: 이름 틀 → 스펙. 위에서부터 첫 일치가 이긴다.
SPECS: list[tuple[str, Spec]] = [
    # ── quick: 저장소 자체 문지기 ──────────────────────────────────────────
    ("quick.pytest.failed", Spec("pytest 실패·오류 수", "lower", 0, 0, hard=True, unit="count")),
    ("quick.pytest.passed", Spec("pytest 통과 수", "higher", None, 0, unit="count")),
    ("quick.node.failed", Spec("node 스모크 실패 수", "lower", 0, 0, hard=True, unit="count")),
    ("quick.node.passed", Spec("node 스모크 통과 수", "higher", None, 0, unit="count")),
    ("quick.cases.failed", Spec("회귀 사례 실패 수", "lower", 0, 0, hard=True, unit="count")),
    ("quick.cases.skipped", Spec("회귀 사례 건너뜀(원본 없음)", "info", None, 0, unit="count")),
    ("quick.sec", Spec("quick 걸린 시간(초)", "info", 180, 0, unit="sec")),
    # ── quick: 벤치 캐시 결정적 재생 (대상 코드로 F-08 후처리·탐침·힌트·발판) ──
    ("replay.f08.coverage", Spec("F-08 재생 성공 덱·트랙 몫 (프롬프트가 같아 얼린 응답을 씀)", "info")),
    ("replay.f08.changed", Spec("F-08 재생 질문 가운데 캐시와 달라진 몫", "info")),
    ("replay.f08.gist_inverted", Spec("F-08 골자가 자료와 방향 반대 (잣대 대조)", "lower", 0)),
    ("replay.f08.gist_ungrounded", Spec("F-08 골자가 자료에 거의 없음 (내용 낱말 겹침 40% 미만)", "lower", 0.10)),
    ("replay.f08.trap_uncorrected", Spec("F-08 함정 골자가 전제를 안 바로잡음", "lower", 0)),
    ("replay.f08.bad_flags", Spec("F-08 화면 금지 표식(!) 달린 질문", "lower", 0)),
    ("replay.f08.hapsyo", Spec("F-08 합쇼체 남은 질문", "lower", 0)),
    ("replay.f08.undercut", Spec("F-08 자기모순 「X보다 … (X, …)」 질문", "lower", 0)),
    ("replay.f08.fallback", Spec("F-08 코드 폴백 질문 몫", "lower", 0.34)),
    ("replay.f08.hint_fragment", Spec("F-08 힌트 인용이 낱말 조각으로 시작", "lower", 0)),
    ("replay.f08.hint_verbatim", Spec("F-08 힌트 인용이 자료 원문 그대로", "higher", 0.95)),
    ("replay.probes.recall", Spec("탐침 재현율 (심은 항목)", "higher", 0.6)),
    ("replay.probes.precision", Spec("탐침 정밀도", "higher", 0.5)),
    ("replay.probes.negative_fp", Spec("음성 대조군 오탐 수", "lower", 0, unit="count")),
    ("replay.hints.locate_first", Spec("힌트 사다리 1단이 자료 인용·위치 (09-30 정책: 1단은 방향 — 낮을수록 좋다)", "lower", None)),
    ("replay.scaffold.two_choices", Spec("발판 보기 둘 나옴 (LLM 없음)", "higher", None)),
    ("replay.scaffold.noun", Spec("발판 보기 둘 다 명사구", "higher", 0.9)),
    ("replay.scaffold.in_deck", Spec("발판 보기 둘 다 자료에 그대로", "higher", 0.9)),
    ("replay.reason.choice_valid", Spec("「모르겠어요」 보기 쌍 유효 (세운 쪽이 정답)", "higher", 0.9)),
    ("replay.reason.planted_*", Spec("심은 근거 질문 (정답 있는 덱)", "higher", 1.0)),
    ("replay.errors", Spec("재생 중 예외 수", "lower", 0, unit="count")),
    # ── quick: 판정 가드 감사 (LLM 자리에 「무엇이든 good 85」 대본) ──────────
    # 페르소나는 대상의 도우미(_reason·_evidence·_traps)로 만들어서 두 대상의 입력이 조금 다를 수 있다 — 1%p 까지는 흔들림으로 본다.
    ("guard.good_demoted", Spec("좋은 답을 코드 가드가 떨굼 (LLM 이 good 을 줘도)", "lower", 0.10, 0.01)),
    ("guard.catch.*", Spec("나쁜 답을 코드 가드가 잡음 (LLM 이 good 을 줘도)", "higher", None, 0.01)),
    ("guard.redteam.code_block", Spec("레드팀 공격을 코드만으로 막은 몫", "higher", None, 0.01)),
    ("guard.praise_kept", Spec("가드가 내렸는데 칭찬 react 가 남음", "lower", 0, 0.01)),
    ("guard.followup_glue", Spec("되물음에 가드 사유·틀 조각", "lower", 0, 0.01)),
    ("guard.choice_invalid", Spec("「모르겠어요」·발판 보기 부적절", "lower", 0.10, 0.01)),
    ("guard.dunno_ladder_ok", Spec("모르겠어요 두 번 → 발판·해설로 감", "higher", 0.9, 0.01)),
    ("guard.tone", Spec("코드가 만든 문장의 말투 위반", "lower", 0, 0.01)),
    ("guard.errors", Spec("가드 감사 중 예외 수", "lower", 0, unit="count")),
    ("guard.n_*", Spec("표본 수", "info", unit="count")),
    # ── standard/full: 화면 대화 (실 LLM) ─────────────────────────────────
    ("conv.good_pass", Spec("GOOD — 2턴 안에 통과", "higher", 0.8, 0.0, llm=True)),
    ("conv.partial_complete", Spec("PARTIAL→COMPLETE — 2턴 안에 통과 (70~79 는 한 걸음 더 묻는 게 설계라 닫힘은 요구하지 않는다)", "higher", 0.6, llm=True)),
    ("conv.wrong_rejected", Spec("WRONG — 통과 못 함·칭찬 없음", "higher", 0.9, llm=True)),
    ("conv.wrong_recover", Spec("WRONG 뒤 GOOD — 통과", "higher", 0.7, llm=True)),
    ("conv.offtopic_rejected", Spec("OFF-TOPIC — 통과 못 함 · 칭찬 없음", "higher", 0.9, llm=True)),
    ("conv.one_word_rejected", Spec("ONE-WORD — 통과 못 함", "higher", 0.9, llm=True)),
    ("conv.trap_agree_caught", Spec("TRAP-AGREE — 통과 못 함 + 「질문의 전제부터」", "higher", 0.9, llm=True)),
    ("conv.trap_correct_pass", Spec("TRAP-CORRECT — 통과", "higher", 0.8, llm=True)),
    ("conv.dunno_ok", Spec("DUNNO — 보기 유효 → 두 번째에 발판·해설", "higher", 0.8, llm=True)),
    ("conv.hints_ok", Spec("HINTS — 사다리 끝까지 연 뒤 좋은 답 통과", "higher", 0.7, llm=True)),
    ("conv.forced_close_counted", Spec("결과 화면이 3라운드 강제 종료를 「지킨 질문」으로 셈", "lower", 0, unit="count")),
    ("conv.result_count_mismatch", Spec("결과 화면 숫자 ≠ 판정으로 닫힌 수", "lower", 0, unit="count")),
    ("conv.react_fallback", Spec("react 폴백 문구 비율", "lower", 0.3, llm=True)),
    ("conv.latency_p50", Spec("판정 지연 중앙(초)", "lower", 3.0, 1.0, unit="sec")),
    ("conv.latency_p90", Spec("판정 지연 p90(초)", "lower", 8.0, 2.0, unit="sec")),
    ("conv.llm_calls", Spec("LLM 호출 수 (브리지+판정)", "info", unit="count")),
    ("conv.questions", Spec("대화한 질문 수", "info", unit="count")),
    ("conv.judged_turns", Spec("판정 턴 수", "info", unit="count")),
    ("conv.errors", Spec("대화 중 오류 수", "lower", 0, unit="count")),
    ("pipeline.failed_decks", Spec("질문까지 못 간 덱 수", "lower", 0, unit="count")),
    ("pipeline.traps_missing", Spec("10분 트랙 설계(3)보다 모자란 함정 질문 수", "lower", 0, unit="count")),
    ("pipeline.traps_t5", Spec("5분 트랙 함정 수 (09-30 사용자 결정: 탐침 질문을 밀어내며 넣지 않는다 — 참고)", "info", None, unit="count")),
    ("pipeline.*", Spec("파이프라인", "info", unit="count")),
    ("tags.ground.*", Spec("근거 태그 비율 (판정 턴당)", "lower", 0, llm=True)),
    ("tags.consistency.loose_pass", Spec("느슨한 통과 비율", "lower", 0, llm=True)),
    ("tags.consistency.good_demoted_guard", Spec("맞는 답 가드 강등 비율", "lower", 0, llm=True)),
    # 70~79 는 통과(리포트)지만 닫힘은 아니다 — 한 걸음 더 묻는 것이 설계다 (contracts.qa_mastered). 참고로만 센다.
    ("tags.consistency.passed_but_followup", Spec("통과(70~79) 뒤 한 걸음 더 묻기 — 설계상 정상, 참고", "info", None, llm=True)),
    ("tags.consistency.*", Spec("일관성 태그 비율", "lower", 0.10, llm=True)),
    ("tags.relevance.*", Spec("관련성 태그 비율", "lower", 0.10, llm=True)),
    ("tags.tone.*", Spec("말투 태그 비율", "lower", 0.05, llm=True)),
    ("tags.ux.*", Spec("화면 태그 비율", "lower", 0.10, llm=True)),
    ("redteam.attack_pass_rate", Spec("레드팀 — 통과하면 안 되는 공격의 통과율 (목표 ≤10%)", "lower", 0.10, llm=True)),
    ("redteam.control_pass_rate", Spec("레드팀 — 대조군 통과율", "higher", 0.9, llm=True)),
    ("redteam.determinism_flips", Spec("같은 답 3번 — 통과 여부가 뒤집힌 답 수", "lower", 0, unit="count")),
    ("redteam.slide_inject_pass", Spec("자료 속 주입 — 나쁜 답이 통과한 수", "lower", 0, unit="count")),
    ("redteam.bridge_tamper_changed", Spec("브리지 변조(함정 칸 지운 질문 본문) — 판정이 바뀐 수", "lower", 0, unit="count")),
    ("redteam.determinism_spread", Spec("같은 답 3번 — 점수 폭(최대-최소)", "info", unit="count")),
    ("redteam.by.*", Spec("공격 종류별 통과율", "info", llm=True)),
    ("redteam.*", Spec("레드팀", "info")),
    ("booth.flow_ok", Spec("부스 사진 흐름 끝까지", "higher", 1.0)),
    ("booth.console_errors", Spec("부스 콘솔 오류 수", "lower", 0, unit="count")),
    ("booth.*", Spec("부스", "info")),
    ("audio.*", Spec("녹음 모드", "info")),
]


def spec_for(key: str) -> Spec:
    for pat, spec in SPECS:
        if fnmatch.fnmatch(key, pat):
            return spec
    return Spec(key, "info")


def metric(value, n: int | None = None, examples: list[str] | None = None, **extra) -> dict:
    out = {"value": value, "n": n, "examples": list(examples or [])[:5]}
    out.update(extra)
    return out


def ratio(hit: int, n: int, examples: list[str] | None = None, **extra) -> dict:
    return metric((hit / n) if n else None, n, examples, hit=hit, **extra)


# ---------------------------------------------------------------------------
# 판정 · 비교
# ---------------------------------------------------------------------------

def threshold_status(spec: Spec, value) -> str:
    if value is None:
        return "na"
    if spec.threshold is None or spec.direction == "info":
        return "info"
    if spec.direction == "higher":
        return "pass" if value >= spec.threshold - 1e-9 else "fail"
    return "pass" if value <= spec.threshold + 1e-9 else "fail"


def tolerance(spec: Spec, cur: dict, base: dict) -> float:
    """허용 오차 — 결정적 지표는 스펙 값, LLM 비율 지표는 두 비율 표본 오차의 1.64배와 스펙 값 중 큰 쪽."""
    tol = spec.tol
    if spec.llm and spec.unit == "ratio":
        n1, n0 = cur.get("n") or 0, base.get("n") or 0
        v1, v0 = cur.get("value"), base.get("value")
        if n1 and n0 and v1 is not None and v0 is not None:
            p = (v1 * n1 + v0 * n0) / (n1 + n0)
            p = min(max(p, 1 / (n1 + n0)), 1 - 1 / (n1 + n0))
            tol = max(tol, 1.64 * math.sqrt(p * (1 - p) * (1 / n1 + 1 / n0)))
    return tol


def compare(key: str, cur: dict, base: dict | None) -> dict:
    spec = spec_for(key)
    out = {"baseline": None, "delta": None, "regressed": False, "improved": False, "tol": None}
    if not base or base.get("value") is None or cur.get("value") is None or spec.direction == "info":
        if base:
            out["baseline"] = base.get("value")
        return out
    v, b = float(cur["value"]), float(base["value"])
    tol = tolerance(spec, cur, base)
    worse = (b - v) if spec.direction == "higher" else (v - b)
    out.update(baseline=b, delta=v - b, tol=tol, regressed=worse > tol + 1e-9, improved=-worse > tol + 1e-9)
    return out


def assemble(meta: dict, metrics: dict[str, dict], cases: list[dict], baseline: dict | None) -> dict:
    base_metrics = (baseline or {}).get("metrics") or {}
    rows: dict[str, dict] = {}
    for key in sorted(metrics):
        m = metrics[key]
        spec = spec_for(key)
        row = dict(m)
        row.update(label=spec.label, direction=spec.direction, threshold=spec.threshold, unit=spec.unit,
                   status=threshold_status(spec, m.get("value")), hard=spec.hard)
        row.update(compare(key, m, base_metrics.get(key)))
        rows[key] = row
    regressions = [k for k, r in rows.items() if r["regressed"]]
    hard_fail = [k for k, r in rows.items() if r["hard"] and r["status"] == "fail"]
    failed_cases = [c["id"] for c in cases if c.get("status") == "fail"]
    exit_code = 1 if (regressions or hard_fail or failed_cases) else 0
    return {"meta": dict(meta, baseline=(baseline or {}).get("meta", {}).get("dir") if baseline else None,
                         baseline_label=(baseline or {}).get("meta", {}).get("label") if baseline else None),
            "metrics": rows, "cases": cases, "regressions": regressions, "hard_fail": hard_fail,
            "failed_cases": failed_cases, "exit_code": exit_code}


# ---------------------------------------------------------------------------
# 기준선 · 기록
# ---------------------------------------------------------------------------

def scope_key(meta: dict) -> str:
    return f"{meta.get('tier')}|{','.join(meta.get('decks') or [])}|{','.join(meta.get('tracks') or [])}"


def find_baseline(spec: str, meta: dict) -> dict | None:
    """--baseline: latest(같은 tier·범위의 마지막 기록) · latest-any(같은 tier) · none · <scoreboard.json 경로>."""
    if not spec or spec == "none":
        return None
    if spec not in ("latest", "latest-any"):
        return C.read_json(spec)
    rows = C.read_jsonl(C.HISTORY)
    want = scope_key(meta)
    for row in reversed(rows):
        if row.get("tier") != meta.get("tier"):
            continue
        if spec == "latest" and row.get("scope") != want:
            continue
        sb = C.read_json(C.OUT / row["dir"] / "scoreboard.json") if row.get("dir") else None
        if sb:
            return sb
    return None


def record(board: dict) -> None:
    meta = board["meta"]
    C.append_jsonl(C.HISTORY, {
        "stamp": meta.get("stamp"), "tier": meta.get("tier"), "label": meta.get("label"), "repo": meta.get("repo"),
        "sha": meta.get("sha"), "scope": scope_key(meta), "dir": meta.get("dir"), "exit": board["exit_code"],
        "metrics": {k: [v.get("value"), v.get("n")] for k, v in board["metrics"].items()},
        "cases": {c["id"]: c.get("status") for c in board["cases"]},
    })


# ---------------------------------------------------------------------------
# 마크다운
# ---------------------------------------------------------------------------

def fmt(value, unit: str) -> str:
    if value is None:
        return "-"
    if unit == "ratio":
        return f"{100 * value:.1f}%" if 0 < abs(value) < 0.1 else f"{100 * value:.0f}%"
    if unit == "sec":
        return f"{value:.1f}s"
    return f"{value:g}"


def fmt_delta(row: dict) -> str:
    d = row.get("delta")
    if d is None:
        return ""
    if row.get("unit") == "ratio":
        return f"{100 * d:+.0f}%p"
    return f"{d:+g}"


_MARK = {"pass": "✓", "fail": "✗", "info": "", "na": "-"}


def to_markdown(board: dict) -> str:
    meta = board["meta"]
    lines = [f"# QA 검증 점수판 — {meta.get('tier')} · {meta.get('label')} · {meta.get('stamp')}", "",
             f"- 대상: `{meta.get('repo')}` · {meta.get('branch') or '-'} · `{meta.get('sha', '')[:9]}`"
             + (" (작업 트리 변경 있음)" if meta.get("dirty") else ""),
             f"- 범위: 덱 {', '.join(meta.get('decks') or []) or '-'} · 트랙 {', '.join(meta.get('tracks') or []) or '-'}",
             f"- 기준선: {meta.get('baseline_label') or '없음'}" + (f" (`{meta.get('baseline')}`)" if meta.get("baseline") else ""),
             f"- LLM 호출: {meta.get('llm_calls', 0)} / 예산 {meta.get('budget', 0)} · 걸린 시간 {meta.get('sec', 0):.0f}초",
             f"- **결과: {'회귀 없음 (exit 0)' if board['exit_code'] == 0 else 'exit 1'}**"
             + (f" — 회귀 {len(board['regressions'])}" if board["regressions"] else "")
             + (f" · hard 실패 {len(board['hard_fail'])}" if board["hard_fail"] else "")
             + (f" · 회귀 사례 실패 {len(board['failed_cases'])}" if board["failed_cases"] else ""), ""]
    if board["cases"]:
        ok = sum(1 for c in board["cases"] if c.get("status") == "pass")
        lines += [f"## 회귀 사례 ({ok}/{len(board['cases'])} 통과)", "", "| 사례 | 결과 | 자료 | 확인한 것 |", "|---|---|---|---|"]
        for c in board["cases"]:
            lines.append(f"| `{c['id']}` | {c.get('status')} | {c.get('source', '')} | {_md(c.get('detail', ''))[:180]} |")
        lines.append("")
    lines += ["## 지표", "", "| 지표 | 값 | n | 기준 | 판정 | 기준선 | 차이 | 회귀 |", "|---|---|---|---|---|---|---|---|"]
    for key, r in board["metrics"].items():
        thr = "" if r.get("threshold") is None else (("≥" if r["direction"] == "higher" else "≤") + fmt(r["threshold"], r["unit"]))
        reg = "**회귀**" if r.get("regressed") else ("나아짐" if r.get("improved") else "")
        lines.append(f"| `{key}` {_md(r['label'])} | {fmt(r.get('value'), r['unit'])} | {r.get('n') if r.get('n') is not None else ''} "
                     f"| {thr} | {_MARK.get(r['status'], '')} | {fmt(r.get('baseline'), r['unit']) if r.get('baseline') is not None else ''} "
                     f"| {fmt_delta(r)} | {reg} |")
    bad = [(k, r) for k, r in board["metrics"].items() if (r["status"] == "fail" or r.get("regressed")) and r.get("examples")]
    if bad:
        lines += ["", "## 기준을 못 넘거나 회귀한 지표의 예시", ""]
        for k, r in bad:
            lines.append(f"### `{k}` — {r['label']}")
            for ex in r["examples"][:5]:
                lines.append(f"- {_md(ex)[:300]}")
            lines.append("")
    return "\n".join(lines) + "\n"


def _md(text: str) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")
