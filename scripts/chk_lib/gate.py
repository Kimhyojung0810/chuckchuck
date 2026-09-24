"""
커밋 전 문지기. CLAUDE.md §3-5 의 네 가지를 한 번에 검사하고 하나라도 걸리면 exit 1.

왜 — 2026-09-13 에 테스트 실패가 `| tail` 파이프에 가려진 채 두 번 커밋됐다 (WORKLOG). 사람이 넷을 순서대로
기억하는 대신 이 한 명령이 기억한다. git pre-commit 훅(staged)·Claude PreToolUse 훅(worktree)·
regression-guard 에이전트가 전부 이 파일을 부른다.

    scripts/chk gate                       # HEAD 대비 바뀐 전부 (worktree)
    scripts/chk gate --scope staged        # 인덱스에 올라간 것만 (pre-commit 훅이 쓴다)
    scripts/chk gate --allow chuckchuck/f08_questions.py chuckchuck/f09_judge.py   # 범위 검사 (루프용)
    scripts/chk gate --json                # 에이전트가 읽는 구조
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import PurePosixPath

from . import common as C
from .common import Check

# 비밀키 패턴. 진짜 키는 앞머리가 정해져 있다: Upstage up_ · A.X awf_ · Friendli flp_ · OpenAI sk- · AWS AKIA.
# 마지막 줄은 `X_API_KEY="긴값"` 꼴. 값이 20자 넘는 영숫자일 때만 — 경로(/)·모델명(.)은 안 걸린다.
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bup_[A-Za-z0-9]{16,}"),
    re.compile(r"\bawf_[A-Za-z0-9]{16,}"),
    re.compile(r"\bflp_[A-Za-z0-9]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"Bearer [A-Za-z0-9._-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*[\"']?[A-Za-z0-9_-]{20,}"),
]
ENV_FILE = re.compile(r"(^|/)\.env(\.|$)(?!example$)")
# 범위 검사가 보는 폴더 (regression-guard 규칙). examples/docs/scripts/.claude 는 사람이 루프 중에도 고친다.
SCOPED_DIRS = ("chuckchuck/", "tests/", "fixtures/", "demo/", ".env")
SUMMARY_RE = re.compile(r"(?:(\d+) passed)?.*?(?:(\d+) failed)?.*?(?:(\d+) errors?)?")


def parse_pytest_summary(text: str) -> tuple[int, int, int, str]:
    """마지막 요약 줄에서 (passed, failed, errors, 줄) 을 뽑는다. 요약이 없으면 (0,0,1,…) — 죽은 것으로 본다."""
    for line in reversed(text.strip().splitlines()):
        if " passed" in line or " failed" in line or " error" in line:
            passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", line)) else 0
            failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", line)) else 0
            errors = int(m.group(1)) if (m := re.search(r"(\d+) errors?", line)) else 0
            return passed, failed, errors, line.strip()
    return 0, 0, 1, text.strip().splitlines()[-1] if text.strip() else "(출력 없음)"


def check_pytest() -> Check:
    r = C.sh([C.venv_python(), "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider"], timeout=900)
    passed, failed, errors, line = parse_pytest_summary(r.stdout + r.stderr)
    if r.returncode != 0 or failed or errors:
        tail = (r.stdout + r.stderr).strip().splitlines()[-15:]
        return Check("pytest", "fail", line, tail)
    if passed < C.PYTEST_MIN:
        return Check("pytest", "fail", f"{line} — 기준선 {C.PYTEST_MIN} 아래. 테스트가 사라졌나? (CHK_PYTEST_MIN)")
    return Check("pytest", "ok", line)


def is_front_js(path: str) -> bool:
    return path.startswith("demo/YEHS_demo/js/") and path.endswith(".js") or path.startswith("tests/js/")


# 프론트 스모크 전부. 파일 하나만 박아 두면 새 스모크(booth)는 아무도 안 돌린다.
NODE_SMOKES = sorted(str(p.relative_to(C.ROOT)) for p in (C.ROOT / "tests/js").glob("*.smoke.mjs"))


def check_node_smoke(files: list[str]) -> Check:
    if not any(is_front_js(f) for f in files):
        return Check("node smoke", "skip", "프론트 JS 변경 없음")
    if not shutil.which("node"):
        return Check("node smoke", "fail", "node 가 없어요 — 프론트 JS 를 고쳤으면 스모크를 돌려야 한다 (CLAUDE.md §2)")
    lines: list[str] = []
    for smoke in NODE_SMOKES:
        r = C.sh(["node", smoke], timeout=120)
        last = (r.stdout.strip().splitlines() or ["(출력 없음)"])[-1]
        lines.append(f"{PurePosixPath(smoke).name}: {last}")
        if r.returncode != 0 or re.search(r"\b[1-9]\d* failed", last):
            return Check("node smoke", "fail", lines[-1], (r.stdout + r.stderr).strip().splitlines()[-15:])
    return Check("node smoke", "ok", " · ".join(lines))


# `?v=` 를 무는 곳(host) 과 그 host 가 무는 자산. index.html 이 전부가 아니다 —
# booth.html 은 booth.css·booth.js 를, js/booth.js 는 import 로 booth_logic.js 를 문다.
# 값은 host 기준 상대 경로를 검사하는 정규식 (host 가 js/ 안에 있으면 자산도 js/ 기준).
ASSET_HOSTS: dict[str, str] = {
    "index.html": r"^(css/.+\.css|js/.+\.js)$",
    "booth.html": r"^(css/.+\.css|js/.+\.js)$",
    "js/booth.js": r"^js/booth_(logic|overlay_state)\.js$",
    # 오버레이 상태 모듈도 booth_logic 을 ?v= 로 문다 — 둘의 값이 다르면 모듈이 두 벌 올라온다 (2026-09-24)
    "js/booth_overlay_state.js": r"^js/booth_logic\.js$",
}


def host_ref(host: str, rel: str) -> str:
    """host 파일 안에서 자산을 부르는 이름. js/booth.js 는 `./booth_logic.js` 처럼 같은 폴더 기준이다."""
    host_dir = str(PurePosixPath(host).parent)
    if host_dir in ("", ".") or not rel.startswith(host_dir + "/"):
        return rel
    return rel[len(host_dir) + 1:]


def asset_token(html: str, asset: str) -> str | None:
    """host 가 `asset?v=TOKEN` 으로 무는 값. `href=`·`src=` 와 ES import 의 `from './asset?v='` 둘 다 본다. 안 물면 None."""
    m = re.search(r'(?:(?:href|src)="|from\s+[\'"]\./)' + re.escape(asset) + r'\?v=([^"\'&]+)', html)
    return m.group(1) if m else None


def reveal_token(app_js: str) -> str | None:
    m = re.search(r"f11_reveal\.html\?embed=1&v=([^\"'&]+)", app_js)
    return m.group(1) if m else None


def stale_assets(files: list[str], index_old: str, index_new: str, app_old: str, app_new: str,
                 hosts: dict[str, tuple[str, str]] | None = None) -> list[str]:
    """
    바뀌었는데 ?v= 가 그대로인 자산 목록. 순수 함수 — 테스트가 여기를 잡는다.

    `hosts` 는 index.html 밖에서 ?v= 를 무는 곳들 {host: (old, new)} (ASSET_HOSTS 의 나머지).
    """
    pages: dict[str, tuple[str, str]] = {"index.html": (index_old, index_new), **(hosts or {})}
    stale: list[str] = []
    for f in files:
        if not f.startswith("demo/YEHS_demo/"):
            continue
        rel = f[len("demo/YEHS_demo/"):]
        if rel == "f11_reveal.html":
            if reveal_token(app_old) is not None and reveal_token(app_old) == reveal_token(app_new):
                stale.append("f11_reveal.html → js/app.js 의 `f11_reveal.html?embed=1&v=` (CLAUDE.md §2: index.html 이 아니다)")
            continue
        if not ((rel.startswith("css/") and rel.endswith(".css")) or (rel.startswith("js/") and rel.endswith(".js"))):
            continue
        for host, (h_old, h_new) in pages.items():
            if host in ASSET_HOSTS and not re.search(ASSET_HOSTS[host], rel):
                continue
            ref = host_ref(host, rel)
            old, new = asset_token(h_old, ref), asset_token(h_new, ref)
            if old is not None and old == new:
                stale.append(f"{rel} → {host} `?v={old}` 그대로")
    return stale


def check_cache_version(files: list[str], scope: str) -> Check:
    touched = [f for f in files if f.startswith("demo/YEHS_demo/") and re.search(r"\.(css|js)$|f11_reveal\.html$", f)]
    if not touched:
        return Check("?v= 캐시", "skip", "css/js/리빌 변경 없음")
    hosts = {
        host: (C.file_at_head(str(C.DEMO / host)), C.file_at(str(C.DEMO / host), scope))
        for host in ASSET_HOSTS if host != "index.html"
    }
    stale = stale_assets(
        files, C.file_at_head(str(C.INDEX_HTML)), C.file_at(str(C.INDEX_HTML), scope),
        C.file_at_head(str(C.APP_JS)), C.file_at(str(C.APP_JS), scope), hosts,
    )
    if stale:
        return Check("?v= 캐시", "fail", f"{len(stale)}개 안 올림 — `scripts/chk bump` 로 올린다", stale)
    return Check("?v= 캐시", "ok", f"{len(touched)}개 자산 모두 올림")


def find_secrets(diff: str) -> list[str]:
    """diff 의 추가 줄(+)만 본다. 지운 줄에 키가 있었다면 그건 이미 이력에 있는 것 — 여기서 잡을 일이 아니다."""
    hits: list[str] = []
    for line in diff.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for pat in SECRET_PATTERNS:
            if pat.search(line):
                shown = line[:60] + ("…" if len(line) > 60 else "")
                hits.append(re.sub(r"[A-Za-z0-9_-]{12,}", lambda m: m.group(0)[:4] + "…", shown))
                break
    return hits


def check_secrets(files: list[str], scope: str) -> Check:
    env_files = [f for f in files if ENV_FILE.search(f)]
    hits = find_secrets(C.diff_text(scope))
    if env_files:
        return Check("비밀키", "fail", f".env 가 커밋 대상에 있어요: {', '.join(env_files)}", hits)
    if hits:
        return Check("비밀키", "fail", f"{len(hits)}줄이 키 패턴에 걸림 (§4 보안은 예외 없음)", hits)
    return Check("비밀키", "ok", "걸린 줄 없음")


def check_scope(files: list[str], allow: list[str]) -> Check:
    if not allow:
        return Check("범위", "skip", "--allow 없음")
    allowed = {str(PurePosixPath(a)) for a in allow}
    out = [f for f in files if f.startswith(SCOPED_DIRS) and f not in allowed]
    if out:
        return Check("범위", "fail", f"허용 목록 밖 {len(out)}개 (tests/ 를 고쳐 통과시키는 건 문지기를 죽이는 일)", out)
    return Check("범위", "ok", f"{len(files)}개 전부 허용 범위 안")


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="scripts/chk gate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scope", choices=["worktree", "staged"], default="worktree")
    ap.add_argument("--allow", nargs="*", default=[], help="바뀌어도 되는 파일 목록 (루프의 범위 검사)")
    ap.add_argument("--no-pytest", action="store_true", help="pytest 생략 (문서만 고쳤을 때 등. 훅은 쓰지 않는다)")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)

    files = C.changed_files(ns.scope)
    checks = [
        check_pytest() if not ns.no_pytest else Check("pytest", "skip", "--no-pytest"),
        check_node_smoke(files),
        check_cache_version(files, ns.scope),
        check_secrets(files, ns.scope),
        check_scope(files, ns.allow),
    ]
    failed = [c for c in checks if c.failed]
    if ns.json:
        print(json.dumps({"ok": not failed, "scope": ns.scope, "files": files,
                          "checks": [c.__dict__ for c in checks]}, ensure_ascii=False, indent=2))
    else:
        print(C.bold(f"chk gate · scope={ns.scope} · 바뀐 파일 {len(files)}개"))
        print(C.render(checks))
        print(C.bad(f"막음 — {len(failed)}개 실패. 고친 뒤 다시.") if failed else C.ok("통과 — 커밋해도 된다."))
    return 1 if failed else 0
