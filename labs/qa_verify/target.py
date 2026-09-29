"""
검증 대상 저장소(--repo) 다루기 — 파이썬 경로 · git 정보 · 자식 프로세스(target_probe) 부르기 · 덱 폴더 잇기.

대상은 읽기만 한다. 예외 하나: standard/full 에서 브리지가 ppt/<덱> 을 찾도록, 대상에 없는 덱 폴더를 **하드 링크**로 만든다
(파일은 전부 .gitignore 의 ppt/**/*.pptx·*.m4a·*.txt 에 걸려 git 에 안 잡힌다). 끝나면 만든 것만 지운다.
심볼릭 링크를 쓰지 않는 까닭: 브리지의 /api/v1/dev/deck-file 이 resolve() 뒤 경로가 ppt/ 안인지 확인해서 막는다.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import common as C

#: 덱 이름 줄임말 — --decks 에 쓰기 편하게. 벤치 캐시 이름(quick)과 ppt 폴더 이름(standard/full)이 다르다.
PPT_ALIAS = {
    "sleep": "수면발표", "수면": "수면발표", "yield": "수익률격차", "yield_gap": "수익률격차", "수익률": "수익률격차",
    "focus": "focus_notification", "glucose": "_held_health_glucose", "health_glucose": "_held_health_glucose",
    "banchan": "_held_ir_banchan", "ir_banchan": "_held_ir_banchan", "jeonse": "_held_policy_jeonse",
    "policy_jeonse": "_held_policy_jeonse", "lib": "_held_lib_reopen", "lib_reopen": "_held_lib_reopen",
    "novel": "_held_hum_novel", "hum_novel": "_held_hum_novel",
}
BENCH_ALIAS = {
    "수면발표": "sleep", "수면": "sleep", "수익률격차": "yield_gap", "yield": "yield_gap", "focus_notification": "focus",
    "_held_health_glucose": "health_glucose", "glucose": "health_glucose", "_held_ir_banchan": "ir_banchan",
    "_held_policy_jeonse": "policy_jeonse", "_held_lib_reopen": "lib_reopen", "_held_hum_novel": "hum_novel",
}
#: 튜닝에 쓴 덱 — held-out 과 따로 센다
TUNED = frozenset({"수면발표", "수익률격차", "focus_notification"})


def ppt_name(name: str) -> str:
    n = unicodedata.normalize("NFC", name.strip())
    return PPT_ALIAS.get(n, n)


def bench_name(name: str) -> str:
    n = unicodedata.normalize("NFC", name.strip())
    return BENCH_ALIAS.get(n, n)


@dataclass
class Target:
    repo: Path
    python: str = ""
    label: str = ""
    sha: str = ""
    branch: str = ""
    dirty: bool = False
    created: list[Path] = field(default_factory=list)

    @classmethod
    def open(cls, repo: str | Path) -> "Target":
        root = Path(repo).expanduser().resolve()
        if not (root / "chuckchuck" / "__init__.py").exists():
            raise SystemExit(f"--repo 가 척척발표 저장소가 아니에요 (chuckchuck/ 없음): {root}")
        py = root / ".venv" / "bin" / "python"
        t = cls(repo=root, python=str(py) if py.exists() else (C.HARNESS_ROOT / ".venv" / "bin" / "python").as_posix())
        t.sha = C.run(["git", "-C", str(root), "rev-parse", "HEAD"]).stdout.strip()
        t.branch = C.run(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
        status = C.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"]).stdout
        t.dirty = bool(status.strip())
        name = t.branch
        if not name or name == "HEAD":          # 떼어 낸 HEAD — 같은 커밋을 가리키는 브랜치 이름(main 먼저)
            heads = C.run(["git", "-C", str(root), "for-each-ref", "--points-at", "HEAD", "--format=%(refname:short)",
                           "refs/heads"]).stdout.split()
            name = "main" if "main" in heads else (heads[0] if heads else root.name)
        t.label = f"{name.replace('/', '-')}@{t.sha[:7]}"
        return t

    def meta(self) -> dict:
        return {"repo": str(self.repo), "sha": self.sha, "branch": self.branch, "label": self.label, "dirty": self.dirty}

    # ── 자식 프로세스 ────────────────────────────────────────────────────
    def probe(self, cmd: str, payload: dict, timeout: int = 900, log: Path | None = None) -> dict:
        """대상 python 으로 target_probe.py 를 돌린다. 출력 JSON 을 돌려준다 (실패면 {"ok": False, "error": …})."""
        with tempfile.TemporaryDirectory(prefix="qa_verify_") as tmp:
            inp, out = Path(tmp) / "in.json", Path(tmp) / "out.json"
            C.write_json(inp, payload)
            env = {"QA_VERIFY_REPO": str(self.repo), "PYTHONDONTWRITEBYTECODE": "1"}
            r = C.run([self.python, str(C.HERE / "target_probe.py"), cmd, str(inp), str(out)],
                      cwd=self.repo, env=env, timeout=timeout)
            if log is not None:
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text((r.stdout or "") + "\n--- stderr ---\n" + (r.stderr or ""), encoding="utf-8")
            got = C.read_json(out)
            if got is None:
                return {"ok": False, "error": f"자식 프로세스가 결과를 못 남김 (rc={r.returncode})", "tail": C.tail(r.stderr or r.stdout)}
            return got

    # ── 덱 폴더 ──────────────────────────────────────────────────────────
    def link_decks(self, decks: list[str], source: Path | None = None) -> list[str]:
        """대상 ppt/ 에 없는 덱 폴더를 주 체크아웃에서 하드 링크(안 되면 복사)로 만든다. 못 찾은 덱 이름을 돌려준다."""
        src_root = source or (C.MAIN_CHECKOUT / "ppt")
        missing = []
        for deck in decks:
            dst = self.repo / "ppt" / deck
            if dst.exists():
                continue
            src = src_root / deck
            if not src.is_dir():
                missing.append(deck)
                continue
            dst.mkdir(parents=True)
            self.created.append(dst)
            for f in src.iterdir():
                if not f.is_file():
                    continue
                try:
                    os.link(f, dst / f.name)
                except OSError:
                    shutil.copy2(f, dst / f.name)
        return missing

    def unlink_decks(self) -> None:
        for d in reversed(self.created):
            shutil.rmtree(d, ignore_errors=True)
        self.created = []
