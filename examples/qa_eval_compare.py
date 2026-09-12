"""
`qa_eval.py` 결과 파일 둘을 놓고 **좋아졌는지·나빠졌는지·잡음인지** 를 판정하는 regression report.

회의(2026-09-12 §4)에서 정한 "버전마다 batch test 를 돌려 이전 버전 대비 report 가 바로
나오게 한다" 의 결정론적 부분이다. LLM 을 부르지 않는다 — 이미 남은 JSON 만 읽는다.

    python examples/qa_eval_compare.py --tag baseline --tag v1        # 각 tag 의 최신 파일끼리
    python examples/qa_eval_compare.py exports/qa_eval/A.json exports/qa_eval/B.json
    python examples/qa_eval_compare.py --latest 2                      # 최근 두 파일
    python examples/qa_eval_compare.py --tag baseline --tag v1 --ledger  # LEDGER.md 에 한 줄 추가

마지막 줄은 언제나 `VERDICT: IMPROVED | REGRESSED | NOISE` 다. 자동 루프는 이 줄만 읽는다.

판정 규칙 (한 항목이라도 잡음 밖으로 나빠지면 REGRESSED — 한 발표에서 좋아진 것이 다른
지표를 깎았으면 채택하지 않는다):
    IMPROVED   1차 지표 중 하나 이상이 잡음 폭 밖으로 좋아지고, 나빠진 1차 지표가 없다
    REGRESSED  1차 지표 중 하나라도 잡음 폭 밖으로 나빠졌다
    NOISE      그 밖에 전부 — 같은 조건으로 한 번 더 돌려 보기 전에는 채택하지 않는다
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "exports" / "qa_eval"
REPORT_DIR = OUT_DIR / "reports"
LEDGER = ROOT / "docs" / "QA_BENCH_LEDGER.md"

#: (summary 경로, 좋아지는 방향, 잡음 폭). 잡음 폭 안의 변화는 "같다" 로 본다.
#: LLM 출력은 매번 조금씩 다르므로 소수 지표에 폭을 둔다. 개수·비율 지표는 0 — 하나라도 달라지면 신호다.
PRIMARY: tuple[tuple[str, str, float], ...] = (
    ("specificity_mean", "up", 0.5),
    ("grounding_mean", "up", 0.05),
    ("fallback", "down", 0),
    ("honorifics_questions", "down", 0),
    ("honorifics_judge", "down", 0),
    ("impolite_questions", "down", 0),
    ("judge.gist_passed", "up", 0),
    ("judge.unrelated_wrong", "up", 0),
    ("judge.trap_agree_wrong", "up", 0),
    ("judge.trap_fixed_passed", "up", 0),
    ("coach.step1_cites_slide", "up", 0),
    ("coach.step1_choice_form", "up", 0),
    ("coach.step1_quote_in_deck", "up", 0),
    ("coach.explain_cites_slide", "up", 0),
    ("coach.honorifics", "down", 0),
)

#: 참고 지표 — 판정에는 안 들어가고 표에만 찍는다 (지연·프롬프트 크기).
SECONDARY_TASKS = ("qa-questions", "qa-judge")


def load_summary(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("summary", data)


def get_path(d: dict, dotted: str):
    cur = d
    for key in dotted.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def as_number(v) -> float | None:
    """'3/3' 같은 비율 문자열은 0~1 소수로, '-' 나 None 은 None 으로."""
    if v is None or v == "-":
        return None
    if isinstance(v, str) and "/" in v:
        a, b = v.split("/", 1)
        return round(int(a) / int(b), 4) if int(b) else None
    return float(v)


def judge_metric(before, after, direction: str, tol: float) -> str:
    """한 지표의 판정: 'better' | 'worse' | 'same' | 'na'."""
    if before is None or after is None:
        return "na"
    delta = after - before
    if abs(delta) <= tol:
        return "same"
    improved = delta > 0 if direction == "up" else delta < 0
    return "better" if improved else "worse"


def compare(before: dict, after: dict) -> dict:
    """두 summary 를 비교해 행 목록과 최종 판정을 돌려준다. 순수 함수."""
    rows = []
    for key, direction, tol in PRIMARY:
        b, a = as_number(get_path(before, key)), as_number(get_path(after, key))
        rows.append({"key": key, "before": b, "after": a, "dir": direction,
                     "state": judge_metric(b, a, direction, tol)})
    states = {r["state"] for r in rows}
    if "worse" in states:
        verdict = "REGRESSED"
    elif "better" in states:
        verdict = "IMPROVED"
    else:
        verdict = "NOISE"
    secondary = []
    for task in SECONDARY_TASKS:
        for field in ("sec_mean", "user_chars_mean"):
            b = as_number(get_path(before, f"prompts.{task}.{field}"))
            a = as_number(get_path(after, f"prompts.{task}.{field}"))
            if b is not None or a is not None:
                secondary.append({"key": f"{task}.{field}", "before": b, "after": a})
    return {"verdict": verdict, "rows": rows, "secondary": secondary}


def _fmt(v: float | None) -> str:
    if v is None:
        return "–"
    return f"{v:.2f}" if isinstance(v, float) and not v.is_integer() else f"{int(v)}"


_MARK = {"better": "▲ 좋아짐", "worse": "▼ 나빠짐", "same": "＝", "na": "–"}


def render_markdown(result: dict, before_name: str, after_name: str) -> str:
    lines = [f"# Q&A 벤치마크 비교 — `{before_name}` → `{after_name}`", "",
             f"**판정: {result['verdict']}**", "",
             "| 지표 | 방향 | 전 | 후 | 판정 |", "|---|---|---|---|---|"]
    for r in result["rows"]:
        lines.append(f"| {r['key']} | {'↑' if r['dir'] == 'up' else '↓'} | {_fmt(r['before'])} | "
                     f"{_fmt(r['after'])} | {_MARK[r['state']]} |")
    if result["secondary"]:
        lines += ["", "참고 (판정에 안 들어감)", "", "| 지표 | 전 | 후 |", "|---|---|---|"]
        for r in result["secondary"]:
            lines.append(f"| {r['key']} | {_fmt(r['before'])} | {_fmt(r['after'])} |")
    return "\n".join(lines) + "\n"


def headline(result: dict) -> str:
    """LEDGER 한 줄에 넣을 핵심 델타 요약."""
    parts = [f"{r['key']} {_fmt(r['before'])}→{_fmt(r['after'])}"
             for r in result["rows"] if r["state"] in ("better", "worse")]
    return "; ".join(parts) or "잡음 폭 안"


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "?"


def append_ledger(result: dict, before_name: str, after_name: str, note: str, now: datetime | None = None) -> None:
    """변형 장부. 이전에 채택한 승자와 비교한 기록이 시간순으로 쌓인다."""
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    if not LEDGER.exists():
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text("# Q&A 벤치마크 장부\n\n각 줄은 `qa_eval_compare.py --ledger` 가 붙인다. "
                          "채택(IMPROVED)만 코드에 남고, 나머지는 되돌린다.\n\n"
                          "| 시각 | 전 | 후 | 판정 | 핵심 델타 | HEAD | 메모 |\n|---|---|---|---|---|---|---|\n",
                          encoding="utf-8")
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(f"| {stamp} | {before_name} | {after_name} | {result['verdict']} | {headline(result)} | "
                f"{git_head()} | {note} |\n")


def latest_for_tag(tag: str) -> Path:
    hits = sorted(OUT_DIR.glob(f"*_{tag}.json"))
    if not hits:
        sys.exit(f"tag '{tag}' 결과 파일이 없어요: {OUT_DIR}/*_{tag}.json")
    return hits[-1]


def resolve_pair(args) -> tuple[Path, Path]:
    if args.files:
        if len(args.files) != 2:
            sys.exit("파일은 정확히 둘을 주세요 (전, 후)")
        return Path(args.files[0]), Path(args.files[1])
    if args.tag:
        if len(args.tag) != 2:
            sys.exit("--tag 는 정확히 둘 (전, 후)")
        return latest_for_tag(args.tag[0]), latest_for_tag(args.tag[1])
    hits = sorted(p for p in OUT_DIR.glob("*.json"))
    if len(hits) < 2:
        sys.exit("비교할 결과 파일이 둘 미만이에요")
    return hits[-2], hits[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="결과 JSON 둘 (전, 후)")
    ap.add_argument("--tag", action="append", help="tag 의 최신 결과 (둘 지정)")
    ap.add_argument("--latest", type=int, default=0, help="최근 2개 (값은 무시, 호환용)")
    ap.add_argument("--ledger", action="store_true", help="LEDGER.md 에 한 줄 붙인다")
    ap.add_argument("--note", default="", help="장부 메모 (가설 이름 등)")
    args = ap.parse_args()

    before_p, after_p = resolve_pair(args)
    result = compare(load_summary(before_p), load_summary(after_p))
    bn, an = before_p.stem, after_p.stem
    md = render_markdown(result, bn, an)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"{bn}__vs__{an}.md"
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"리포트: {out.relative_to(ROOT)}")
    if args.ledger:
        append_ledger(result, bn, an, args.note)
        print(f"장부: {LEDGER.relative_to(ROOT)}")
    print(f"VERDICT: {result['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
