"""
런타임 코드에 **특정 덱의 낱말**이 프롬프트·규칙·정규식으로 박혀 있는지 훑는다 (과적합 위험). LLM 없음.

주석·docstring 은 빼고, 실행되는 문자열 리터럴(프롬프트·정규식·상수)만 본다 — 주석의 「09-29 수면 실측」 은 기록이지
규칙이 아니다. 프롬프트의 예시(「수면의 질 = 시간 × …」)는 규칙은 아니어도 모델이 그 덱 말투를 끌어오게 만들 수 있어 같이 센다.

    .venv/bin/python labs/qa_bench/overfit_scan.py                 # 표
    .venv/bin/python labs/qa_bench/overfit_scan.py --json out.json
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

#: 알려진 덱(튜닝에 쓴 덱)의 낱말. 수면·수익률격차·알림(focus)·IMU2CLIP·멘토링 폼·SK하이닉스·링글.
DECK_WORDS = {
    "수면": ["수면", "연속성", "규칙성", "카페인", "음주", "REM", "깊은 수면", "몰아자기", "사회적 시차", "기상", "취침", "피곤"],
    "수익률격차": ["수익률", "기관", "회전율", "개인 투자자", "개인투자자", "손실 회피", "복리", "지수", "매매", "종목"],
    "알림": ["알림", "집중", "attention residue", "맥락 복구", "스마트폰"],
    "IMU2CLIP": ["IMU", "CLIP", "IMU2CLIP", "Ego4D"],
    "멘토링폼": ["멘토링", "신청 폼", "신청폼"],
    "SK하이닉스": ["하이닉스", "HBM", "DRAM", "NAND"],
    "링글": ["링글", "RINGLE", "Ringle"],
}

TARGETS = ["chuckchuck", "demo/bridge.py", "server"]


def _docstring_lines(src: str) -> set[int]:
    """module·class·def 의 docstring 이 차지하는 줄 번호."""
    out: set[int] = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                out.update(range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1))
    return out


def _context_of(src_lines: list[str], lineno: int) -> str:
    """이 줄이 어느 이름(대입 대상·함수)에 속하는가 — 위로 올라가며 첫 `NAME =` 또는 `def`."""
    for i in range(lineno - 1, max(-1, lineno - 80), -1):
        m = re.match(r"^\s*(?:def\s+(\w+)|([A-Z_][A-Z0-9_]*)\s*[:=]|(\w+)\s*=)", src_lines[i])
        if m:
            return m.group(1) or m.group(2) or m.group(3)
    return ""


def scan() -> list[dict]:
    files: list[Path] = []
    for t in TARGETS:
        p = ROOT / t
        files.extend([p] if p.is_file() else sorted(p.rglob("*.py")))
    words = [(deck, w) for deck, ws in DECK_WORDS.items() for w in ws]
    hits: list[dict] = []
    for f in files:
        if "/tests/" in str(f) or f.name.startswith("test_"):
            continue
        src = f.read_text(encoding="utf-8", errors="replace")
        doc_lines = _docstring_lines(src)
        src_lines = src.splitlines()
        try:
            toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        except (tokenize.TokenError, IndentationError):
            continue
        for tok in toks:
            if tok.type != tokenize.STRING:
                continue
            if tok.start[0] in doc_lines:
                continue
            text = tok.string
            for deck, w in words:
                # 영문 약어는 낱말 경계, 한글은 포함
                pat = re.escape(w) if re.search(r"[가-힣]", w) else rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])"
                for m in re.finditer(pat, text):
                    line = tok.start[0] + text[: m.start()].count("\n")
                    snippet = src_lines[line - 1].strip() if line - 1 < len(src_lines) else ""
                    hits.append({"file": str(f.relative_to(ROOT)), "line": line, "deck": deck, "word": w,
                                 "in": _context_of(src_lines, tok.start[0]), "snippet": snippet[:160]})
    # 같은 줄·같은 덱은 하나로 (한 줄에 수면·연속성·규칙성이 다 있으면 한 건)
    seen: dict[tuple, dict] = {}
    for h in hits:
        key = (h["file"], h["line"], h["deck"])
        if key in seen:
            if h["word"] not in seen[key]["word"].split("·"):
                seen[key]["word"] += "·" + h["word"]
        else:
            seen[key] = dict(h)
    return sorted(seen.values(), key=lambda h: (h["file"], h["line"]))


def kind_of(h: dict) -> str:
    """프롬프트 예시인가, 규칙(정규식·상수 목록)인가 — 이름으로 가른다."""
    name = h["in"] or ""
    snip = h["snippet"]
    if "PROMPT" in name or "ADDENDUM" in name or "NUDGE" in name or name.endswith("_SYSTEM"):
        return "프롬프트 예시"
    if name.endswith("_RE") or "re.compile" in snip:
        return "정규식"
    if name.isupper():
        return "상수·규칙"
    return "코드 문자열"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ns = ap.parse_args(argv)
    hits = scan()
    for h in hits:
        h["kind"] = kind_of(h)
    if ns.json:
        Path(ns.json).write_text(json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")
    for h in hits:
        print(f"{h['file']}:{h['line']}\t{h['deck']}\t{h['word']}\t{h['kind']}\t{h['in']}\t{h['snippet'][:90]}")
    print(f"\n{len(hits)}건", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
