"""
세션 시작 브리핑 — ROADMAP_AUTONOMOUS §2 가 "매 세션 읽어라" 고 한 것을 한 화면에.

    scripts/chk brief
    scripts/chk brief --ledger-rows 8 --worklog-lines 40

순서는 헌장 그대로: 오늘·마일스톤 D-day → 헌장 §0 조건 → 회의록 할 일(끝나지 않은 것) → 장부 마지막 줄들 →
WORKLOG 맨 위 절과 「다음:」 → git 상태. 읽기만 한다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re

from . import common as C

MEETING = C.ROOT / "docs/회의록/README.md"
WORKLOG = C.ROOT / "docs/WORKLOG.md"
LEDGERS = {"QA": C.ROOT / "docs/QA_BENCH_LEDGER.md", "그래프": C.ROOT / "docs/GRAPH_BENCH_LEDGER.md"}
FESTA_FREEZE = dt.date(2026, 10, 1)
FESTA_END = dt.date(2026, 10, 8)
DATE_RE = re.compile(r"(2026-\d{2}-\d{2})")


def table_rows(md: str, header_prefix: str) -> list[list[str]]:
    """`| 시각 | …` 처럼 시작하는 표를 찾아 본문 줄들을 셀 목록으로."""
    rows, inside = [], False
    for line in md.splitlines():
        if line.startswith(header_prefix):
            inside = True
            continue
        if inside and line.startswith("|---"):
            continue
        if inside and line.startswith("|"):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif inside and rows:
            break
    return rows


def milestones(md: str, today: dt.date) -> list[str]:
    out = []
    for cells in table_rows(md, "| 날짜 | 일정"):
        m = DATE_RE.search(cells[0])
        if not m or len(cells) < 2:
            continue
        d = dt.date.fromisoformat(m.group(1))
        left = (d - today).days
        tag = f"D-{left}" if left > 0 else ("오늘" if left == 0 else f"D+{-left}")
        out.append(f"{tag:>6}  {m.group(1)}  {re.sub(r'\*\*', '', cells[1])[:50]}")
    return out


def open_todos(md: str) -> list[str]:
    out = []
    for cells in table_rows(md, "| # | 상태 | 할 일"):
        if len(cells) < 5 or "✅" in cells[1]:
            continue
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cells[2])
        text = re.sub(r"\*\*", "", text)
        owner = re.sub(r"\*\*", "", cells[3])[:10]
        due = DATE_RE.search(cells[4]).group(1) if DATE_RE.search(cells[4]) else cells[4][:10]
        out.append(f"#{cells[0]:<3}{cells[1]} {text[:64]:<64} {owner:<10} {due}")
    return out


def ledger_tail(md: str, n: int) -> tuple[list[str], int]:
    rows = table_rows(md, "| 시각 | 전 | 후")
    improved = sum(1 for r in rows if len(r) > 3 and r[3] == "IMPROVED")
    lines = [f"{r[0]}  {r[3]:<9} {r[6][:60] if len(r) > 6 else ''}" for r in rows[-n:]]
    return lines, improved


def worklog_top(md: str, max_lines: int) -> tuple[list[str], str | None]:
    lines, started, nxt = [], False, None
    for line in md.splitlines():
        if line.startswith("## "):
            if started:
                break
            started = True
        if started:
            lines.append(line)
            if nxt is None and re.search(r"\*\*다음:?\*\*|^다음:", line):
                nxt = re.sub(r"\*\*", "", line).strip()
    return lines[:max_lines], nxt


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="scripts/chk brief", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger-rows", type=int, default=5)
    ap.add_argument("--worklog-lines", type=int, default=25)
    ns = ap.parse_args(argv)
    today = dt.date.today()
    meeting = MEETING.read_text(encoding="utf-8") if MEETING.exists() else ""
    worklog = WORKLOG.read_text(encoding="utf-8") if WORKLOG.exists() else ""

    print(C.bold(f"chk brief · {today.isoformat()} ({'월화수목금토일'[today.weekday()]})"))
    print(C.bold("\n마일스톤"))
    print("\n".join("  " + l for l in milestones(meeting, today)) or "  (회의록 §3 표를 못 읽음)")
    print(C.bold("\n헌장 §0"))
    if today < FESTA_FREEZE:
        print(f"  Festa 전 — 프론트에 새 화면을 얹지 않는다 (C 는 설계만). 잠금 {FESTA_FREEZE} 까지 {(FESTA_FREEZE - today).days}일")
    elif today <= FESTA_END:
        print("  Festa 기간 — 화면 고정. 부스 운영·Human Eval 수집만")
    else:
        print("  Festa 뒤 — C(뉘앙스 UI)·리포트 탭 착수 가능. 결선 그래프는 장부의 IMPROVED 줄")
    print("  동의한 세션만 학습·측정에 쓴다 · 세션은 사람이 연다 (클라우드 cron 없음)")
    print(C.bold("\n할 일 (끝나지 않은 것)"))
    print("\n".join("  " + l for l in open_todos(meeting)) or "  (없음)")
    for name, path in LEDGERS.items():
        if path.exists():
            lines, improved = ledger_tail(path.read_text(encoding="utf-8"), ns.ledger_rows)
            print(C.bold(f"\n{name} 장부 — 마지막 {len(lines)}줄 · IMPROVED 누계 {improved}"))
            print("\n".join("  " + l for l in lines))
    top, nxt = worklog_top(worklog, ns.worklog_lines)
    print(C.bold("\nWORKLOG 맨 위"))
    print("\n".join("  " + l for l in top))
    if nxt:
        print(C.bold("\n이어받을 한 줄"))
        print("  " + nxt)
    print(C.bold("\ngit"))
    print(f"  {C.git('branch', '--show-current').strip()} @ {C.git('rev-parse', '--short', 'HEAD').strip()}")
    status = C.git("status", "--short").splitlines()
    print(f"  미커밋 {len(status)}개" + (" — 남의 변경은 건드리지 않는다" if status else ""))
    for l in status[:12]:
        print("    " + l)
    if len(status) > 12:
        print(f"    … {len(status) - 12}개 더")
    print("\n".join("  " + l for l in C.git("log", "--oneline", "-5").splitlines()))
    return 0
