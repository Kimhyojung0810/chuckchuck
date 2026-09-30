#!/usr/bin/env python3
"""
배포(브리지 재시작) 뒤 Cloudflare 서울(ICN) 캐시를 미리 채운다 — 첫 방문자가 VM 까지 가지 않게.

왜 — 공개 경로는 VM → Funnel 도쿄 → DERP 홍콩을 거쳐 새 연결 ~1초, 대역폭 초당 100~330KB 다 (docs/DEPLOYMENT.md §10-5).
정적 파일은 내용 해시 주소라 한 번 Cloudflare 에 들어가면 1년 거기서 나간다. 배포 직후엔 새 해시라 비어 있으니
이 VM 에서(ICN 을 탄다) 한 번씩 받아 둔다. HTML 캐시 규칙을 켰다면 HTML 을 두 번 받아 옛 판을 새 판으로 갈아 끼운다
(stale-while-revalidate 는 첫 요청에 옛 판을 주고 뒤에서 새로 받는다).

    python3 scripts/warm_edge.py                                  # https://chuckchuck-present.com
    python3 scripts/warm_edge.py --base https://chuckchuck-present.com --check   # 두 번째 받을 때 HIT 인지까지

표준 라이브러리만 쓴다 (gzip 만 달라고 한다 — Cloudflare 는 원본 응답을 저장해 두고 방문자에 맞춰 다시 압축한다). 파일 목록은 HTML 의 src·href(템플릿 #lazyAssets 포함)와 ES 모듈의 import 를 따라간다.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

ATTR = re.compile(r'\b(?:src|href)="([^"#]+\?v=[^"]+)"')
IMPORT = re.compile(r"""^\s*(?:import|export)\b[^;'"]*?(['"])([^'"]+\?v=[^'"]+)\1""", re.M)
UA = "chuckchuck-warm-edge/1"


def get(url: str, timeout: float = 60) -> tuple[int, dict, bytes, float]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, {k.lower(): v for k, v in r.headers.items()}, body, time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, b"", time.perf_counter() - t0


def text_of(headers: dict, body: bytes) -> str:
    enc = headers.get("content-encoding", "")
    if enc == "gzip":
        import gzip
        body = gzip.decompress(body)
    return body.decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://chuckchuck-present.com")
    ap.add_argument("--check", action="store_true", help="한 번 더 받아 cf-cache-status 가 HIT 인지 본다")
    a = ap.parse_args()
    base = a.base.rstrip("/") + "/"
    host = urlparse(base).netloc

    # HTML 두 번 — 캐시 규칙이 있으면 첫 번째가 옛 판을 받고 새로 고침을 건다
    pages = [base, urljoin(base, "index.html")]
    html = ""
    for p in pages:
        for _ in range(2):
            st, h, body, dt = get(p)
        html += text_of(h, body)
        print(f"HTML {p} → {st} {dt:.2f}s cf={h.get('cf-cache-status', '-')} ray={h.get('cf-ray', '-')[-3:]}")

    todo = {urljoin(base, u) for u in ATTR.findall(html)}
    todo = {u for u in todo if urlparse(u).netloc == host}
    done: dict[str, tuple] = {}
    while todo:
        batch, todo = sorted(todo), set()
        with ThreadPoolExecutor(max_workers=6) as ex:
            for u, (st, h, body, dt) in zip(batch, ex.map(get, batch)):
                done[u] = (st, h.get("cf-cache-status", "-"), dt, len(body))
                if u.endswith((".js",)) or ".js?" in u:
                    for m in IMPORT.finditer(text_of(h, body)):
                        nxt = urljoin(u, m.group(2))
                        if urlparse(nxt).netloc == host and nxt not in done:
                            todo.add(nxt)

    bad = [u for u, v in done.items() if v[0] != 200]
    first = {}
    for v in done.values():
        first[v[1]] = first.get(v[1], 0) + 1
    print(f"파일 {len(done)}개 받음 · cf={first} · 가장 느린 {max((v[2] for v in done.values()), default=0):.2f}s")
    for u in bad:
        print(f"  ✗ {done[u][0]} {u}")

    if a.check:
        again = {}
        slow = []
        for u in done:
            st, h, _, dt = get(u)
            s = h.get("cf-cache-status", "-")
            again[s] = again.get(s, 0) + 1
            if s != "HIT":
                slow.append((s, u))
        print(f"다시 받기 cf={again}")
        for s, u in slow[:8]:
            print(f"  {s} {u.split('/', 3)[-1]}")
        if again.get("HIT", 0) == 0:
            print("  → HIT 이 하나도 없다: 도메인이 Cloudflare 캐시를 거치지 않거나(Worker·규칙) 브리지가 옛 판이다")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
