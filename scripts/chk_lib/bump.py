"""
바뀐 css/js 의 `?v=` 캐시 버전을 올린다. CLAUDE.md §2 「데모 날 20분 날리는 함정」의 자동화.

    scripts/chk bump                 # HEAD 대비 바뀐 css/js/리빌을 찾아 올린다
    scripts/chk bump css/app.css     # 지정한 자산만
    scripts/chk bump --dry-run

규칙
- `자산?v=TOKEN` 으로 무는 곳(gate.ASSET_HOSTS: index.html · booth.html · js/booth.js 의 import)만 다룬다.
  어느 곳도 안 무는 파일(landing*.js 등)은 알려 주고 넘어간다.
- f11_reveal.html 이 바뀌면 index.html 이 아니라 js/app.js 의 `f11_reveal.html?embed=1&v=` 를 올린다.
  그러면 app.js 가 바뀌므로 app.js 의 ?v= 도 같이 올린다.
- 이미 HEAD 와 다른 토큰이면 「이미 올림」 — 두 번 안 올린다 (--force 로 강제).
- 토큰은 끝 숫자가 있으면 +1, 없으면 '2' 를 붙인다: ql3→ql4 · qkh→qkh2 · showcase6→showcase7.
"""

from __future__ import annotations

import argparse
import re

from . import common as C
from .gate import ASSET_HOSTS, asset_token, host_ref, reveal_token

DEMO = "demo/YEHS_demo/"


def next_token(tok: str) -> str:
    m = re.match(r"^(.*?)(\d+)$", tok)
    return f"{m.group(1)}{int(m.group(2)) + 1}" if m else tok + "2"


def bump_asset(html: str, asset: str, new: str) -> str:
    """자산의 모든 참조(favicon 처럼 여러 번 물릴 수 있다)를 새 토큰으로. ES import 의 `from './x?v='` 도 같이."""
    html = re.sub(r'((?:href|src)="' + re.escape(asset) + r'\?v=)[^"&]+"', lambda m: m.group(1) + new + '"', html)
    return re.sub(r"(from\s+(['\"])\./" + re.escape(asset) + r"\?v=)[^'\"&]+(\2)", lambda m: m.group(1) + new + m.group(3), html)


def bump_reveal(app_js: str, new: str) -> str:
    return re.sub(r"(f11_reveal\.html\?embed=1&v=)[^\"'&]+", lambda m: m.group(1) + new, app_js)


def _targets(explicit: list[str]) -> list[str]:
    if explicit:
        return [a if a.startswith(DEMO) else DEMO + a for a in explicit]
    return [f for f in C.changed_files("worktree") if f.startswith(DEMO)]


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="scripts/chk bump", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("assets", nargs="*", help="css/app.css 처럼 demo/YEHS_demo 기준 경로. 비우면 git 이 찾는다")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="이미 올렸어도 한 번 더")
    ns = ap.parse_args(argv)

    app_path = C.ROOT / C.APP_JS
    app_js, app_head = app_path.read_text(encoding="utf-8"), C.file_at_head(str(C.APP_JS))
    # host 마다 (지금 내용, HEAD 내용). js/booth.js 를 먼저 — 거기서 올리면 booth.js 가 바뀌어 booth.html 도 올려야 한다.
    hosts = {h: [C.file_at(str(C.DEMO / h), "worktree"), C.file_at_head(str(C.DEMO / h))]
             for h in ("js/booth.js", "booth.html", "index.html")}
    rels = [t[len(DEMO):] for t in _targets(ns.assets)]
    done: list[str] = []

    # 1) 리빌 iframe — app.js 안에 따로 박혀 있다.
    if "f11_reveal.html" in rels:
        old, head = reveal_token(app_js), reveal_token(app_head)
        if old is None:
            print(C.warn("app.js 에 f11_reveal.html?embed=1&v= 가 없어요 — 리빌 참조 위치가 바뀌었나?"))
        elif old != head and not ns.force:
            print(C.dim(f"– 리빌 v={old} 이미 올림 (HEAD {head})"))
        else:
            new = next_token(old)
            app_js = bump_reveal(app_js, new)
            done.append(f"js/app.js: f11_reveal v={old} → {new}")
            if "js/app.js" not in rels:
                rels.append("js/app.js")

    # 2) host 마다 css/js. 어느 host 도 안 무는 자산은 알려 주고 넘어간다.
    touched_hosts: set[str] = set()
    for host, texts in hosts.items():
        for rel in list(rels):
            if not re.search(r"^(css/.+\.css|js/.+\.js)$", rel) or not re.search(ASSET_HOSTS[host], rel):
                continue
            ref = host_ref(host, rel)
            old, head = asset_token(texts[0], ref), asset_token(texts[1], ref)
            if old is None:
                continue
            if head is None and not ns.force:
                # HEAD 가 이 참조를 모른다 = 새 파일·새 참조. 처음 값이 곧 새 값이다
                print(C.dim(f"– {rel}: {host} v={old} 새 참조 — 올릴 것 없음"))
                continue
            if old != head and not ns.force:
                print(C.dim(f"– {rel}: {host} v={old} 이미 올림 (HEAD {head})"))
                continue
            new = next_token(old)
            texts[0] = bump_asset(texts[0], ref, new)
            touched_hosts.add(host)
            done.append(f"{host}: {rel} v={old} → {new}")
            # host 가 자산이기도 하면(js/booth.js) 그 host 를 무는 페이지도 올려야 한다
            if host in ASSET_HOSTS and re.search(r"^(css/.+\.css|js/.+\.js)$", host) and host not in rels:
                rels.append(host)
    for rel in rels:
        if re.search(r"^(css/.+\.css|js/.+\.js)$", rel) and not any(asset_token(t[0], host_ref(h, rel)) for h, t in hosts.items()):
            print(C.dim(f"– {rel}: 어느 페이지도 ?v= 로 물지 않음 — 건너뜀"))

    if not done:
        print(C.ok("올릴 것 없음"))
        return 0
    for d in done:
        print(C.ok(d))
    if ns.dry_run:
        print(C.dim("(--dry-run — 파일은 안 건드림)"))
        return 0
    for host in touched_hosts:
        (C.ROOT / C.DEMO / host).write_text(hosts[host][0], encoding="utf-8")
    if "js/app.js" in [d.split(":")[0] for d in done] or "f11_reveal.html" in rels:
        app_path.write_text(app_js, encoding="utf-8")
    return 0
