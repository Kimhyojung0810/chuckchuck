"""
부스 폰 동시 접속 벤치 — QR 을 찍은 폰 N 대가 한꺼번에 /hi → 랜딩 → 투어 파일 → 퍼널 신호를 받는 걸 흉내 낸다 (2026-10-11).

왜 — 결선 부스(11/3~5)는 발표가 끝날 때마다 객석이 한꺼번에 QR 을 찍는다. 10/7 은 10분에 13명이 최고였지만, 결선은 강당에서
수십 명이 같은 1분 안에 들어올 수 있다. 원본(이 VM 의 브리지)이 정적 파일·신호를 그 동시성에서 얼마에 내주는지,
과금 경로를 하나라도 부르는지를 잰다. 과금 0: 이 벤치는 정적 GET 과 POST /api/v1/tour/event 만 보낸다.

    python3 etc/labs/booth_load/run.py --base http://127.0.0.1:8989 --phones 50
    python3 etc/labs/booth_load/run.py --base http://127.0.0.1:8989 --phones 50 --log <브리지 로그>   # 과금 경로 0 확인까지

폰마다 다른 방문자 IP 를 CF-Connecting-IP 로 싣는다(X-Forwarded-For 없이 = shield 의 legacy 길, cloudflared 와 같다) —
신호 상한이 IP 칸마다 따로 도는지 같이 본다. 폰 하나는 연결 하나를 이어 쓴다(keep-alive, 브라우저처럼).
Cloudflare 를 거치지 않으므로 이 값은 **원본만의 값**이다 — 실제 폰은 정적 파일 대부분을 Cloudflare 서울에서 받는다.
결과: etc/labs/booth_load/out/<stamp>.json + 표준 출력 표. 표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import argparse
import gzip
import http.client
import json
import re
import statistics
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
      "Mobile/15E148 KAKAOTALK 10.8.0")
STEPS = ["hi", "intro", "team", "team_end", "explore", "tour_deck", "tour_present", "tour_analysis", "tour_qa",
         "tour_report", "try_real"]
_ASSET = re.compile(r'(?:src|href)="((?:js|css|assets)/[^"]+\?v=[^"]+)"')
#: main/server/bridge.py PAID_PATHS 와 같은 목록 — 벤치 동안 브리지 로그에 이 중 하나라도 찍히면 실패
PAID = ("/api/v1/parse", "/api/v1/concepts", "/api/v1/transcribe", "/api/v1/graph", "/api/v1/alignment",
        "/api/v1/chatter", "/api/v1/habits", "/api/v1/report", "/api/v1/questions", "/api/v1/rubric",
        "/api/v1/qa/judge", "/api/v1/strategy", "/api/v1/papers", "/api/v1/claims", "/api/v1/memory", "/qa/judge")


class Phone:
    def __init__(self, base: str, ip: str, timeout: float) -> None:
        u = urlparse(base)
        self.host, self.port = u.hostname, u.port or 80
        self.ip, self.timeout = ip, timeout
        self.conn: http.client.HTTPConnection | None = None
        self.samples: list[tuple[str, float, int]] = []    # (종류, 초, 상태 — 0 은 연결 오류)

    def _req(self, kind: str, method: str, path: str, body: bytes | None = None, ctype: str | None = None) -> bytes:
        headers = {"Host": f"{self.host}:{self.port}", "User-Agent": UA, "CF-Connecting-IP": self.ip,
                   "Accept-Encoding": "gzip", "Accept-Language": "ko-KR"}
        if ctype:
            headers["Content-Type"] = ctype
        for attempt in (0, 1):  # 서버가 유휴 연결을 닫았으면 한 번만 새로 연다 (브라우저처럼)
            if self.conn is None:
                self.conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
            t0 = time.perf_counter()
            try:
                self.conn.request(method, path, body=body, headers=headers)
                res = self.conn.getresponse()
                data = res.read()
                if res.getheader("Content-Encoding", "") == "gzip":
                    data = gzip.decompress(data)
                self.samples.append((kind, time.perf_counter() - t0, res.status))
                if res.getheader("Connection", "").lower() == "close":
                    self.conn.close()
                    self.conn = None
                return data if res.status == 200 else b""
            except (OSError, http.client.HTTPException):
                self.conn.close()
                self.conn = None
                if attempt:
                    self.samples.append((kind, time.perf_counter() - t0, 0))
        return b""

    def visit(self, deck_files: list[str], start: threading.Event, edge: bool = False) -> None:
        start.wait()
        self._req("hi", "GET", "/hi")                         # 302 → /index.html#/hi (또는 랜딩 200)
        html = self._req("html", "GET", "/index.html").decode("utf-8", "replace")
        if edge:
            imgs: list[str] = []
        else:
            for a in _ASSET.findall(html)[:40]:               # 첫 방문: 해시 주소 자산 (실제로는 Cloudflare 가 받는다)
                self._req("asset", "GET", "/" + a)
            self._req("data", "GET", "/data/team.json")
            tour = self._req("data", "GET", "/data/tour/_example.json")
            imgs = deck_files or re.findall(r'"(assets/deck-(?:slides|covers)/[^"]+\.webp)"', tour.decode("utf-8", "replace"))
        for i, step in enumerate(STEPS):
            ev = {"step": step, "t": i * 15}
            if step.startswith("tour_"):
                ev["deck"] = "_example"
            self._req("event", "POST", "/api/v1/tour/event", json.dumps(ev).encode(), "application/json")
            if step == "tour_deck":
                for img in imgs:
                    self._req("image", "GET", "/" + img)
        if self.conn:
            self.conn.close()


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1)))))
    return xs[k]


def summarize(phones: list[Phone], wall: float) -> dict:
    by: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for ph in phones:
        for kind, sec, status in ph.samples:
            by[kind].append((sec, status))
            by["all"].append((sec, status))
    out = {}
    for kind, rows in by.items():
        lat = [s * 1000 for s, _ in rows]
        bad = [st for _, st in rows if st == 0 or st >= 400]
        codes: dict[str, int] = defaultdict(int)
        for _, st in rows:
            codes[str(st)] += 1
        out[kind] = {"n": len(rows), "p50_ms": round(statistics.median(lat), 1), "p95_ms": round(pct(lat, 95), 1),
                     "p99_ms": round(pct(lat, 99), 1), "max_ms": round(max(lat), 1),
                     "error_rate": round(len(bad) / len(rows), 4), "codes": dict(codes)}
    out["wall_sec"] = round(wall, 2)
    out["rps"] = round(out["all"]["n"] / wall, 1) if wall else 0
    return out


def paid_lines(log: Path, since_bytes: int) -> list[str]:
    """벤치 동안 브리지 로그에 새로 찍힌 줄 중 과금 경로 요청."""
    with open(log, "rb") as fh:
        fh.seek(since_bytes)
        text = fh.read().decode("utf-8", "replace")
    return [ln for ln in text.splitlines() if '"POST ' in ln and any(p in ln for p in PAID)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="부스 폰 동시 접속 벤치 (정적 + 퍼널 신호, 과금 0)")
    ap.add_argument("--base", default="http://127.0.0.1:8989")
    ap.add_argument("--phones", type=int, default=50)
    ap.add_argument("--rounds", type=int, default=1, help="같은 폰 무리를 몇 번 (2 면 재방문 흉내)")
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--log", type=Path, help="브리지 로그 파일 — 과금 경로 요청이 0 인지 본다")
    ap.add_argument("--edge", action="store_true",
                    help="Cloudflare 가 받는 것(해시 자산 · 덱 그림 · 투어 JSON)은 빼고 원본까지 오는 것만 — /hi · HTML · 신호")
    ap.add_argument("--same-ip", action="store_true", help="폰 전부 한 IP (행사장 와이파이 NAT 흉내 — 신호 IP 칸 429 를 본다)")
    ap.add_argument("--deck-images", default="battery-fastcharge", help="투어 덱 그림 폴더 (assets/deck-slides/<이름>) · 빈 값이면 투어 JSON 에서")
    a = ap.parse_args(argv)
    root = HERE.parents[2] / "main/web"
    deck_files = []
    if a.deck_images:
        deck_files = [f"assets/deck-covers/{a.deck_images}.webp"] + sorted(
            f"assets/deck-slides/{a.deck_images}/{p.name}" for p in (root / "assets/deck-slides" / a.deck_images).glob("*.webp"))
    log_at = a.log.stat().st_size if a.log and a.log.exists() else 0
    results = []
    for r in range(a.rounds):
        phones = [Phone(a.base, "203.0.113.200" if a.same_ip else
                        (f"203.0.113.{i % 250 + 1}" if i < 250 else f"198.51.100.{i % 250 + 1}"), a.timeout)
                  for i in range(a.phones)]
        start = threading.Event()
        threads = [threading.Thread(target=ph.visit, args=(deck_files, start, a.edge), daemon=True) for ph in phones]
        for t in threads:
            t.start()
        t0 = time.perf_counter()
        start.set()
        for t in threads:
            t.join()
        results.append(summarize(phones, time.perf_counter() - t0))
    report = {"at": datetime.now().isoformat(timespec="seconds"), "base": a.base, "phones": a.phones,
              "same_ip": a.same_ip, "edge": a.edge, "rounds": results}
    if a.log:
        paid = paid_lines(a.log, log_at)
        report["paid_requests"] = len(paid)
        report["paid_samples"] = paid[:5]
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    path = out / f"{datetime.now():%Y%m%d_%H%M%S}_{a.phones}phones{'_sameip' if a.same_ip else ''}{'_edge' if a.edge else ''}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for i, res in enumerate(results, 1):
        print(f"── {i}회차 · 폰 {a.phones} 대 · {res['wall_sec']}초 · {res['rps']} req/s")
        print(f"{'종류':<7}{'요청':>6}{'p50':>9}{'p95':>9}{'p99':>9}{'최대':>9}{'오류율':>8}  상태")
        for kind in ("all", "hi", "html", "asset", "data", "image", "event"):
            s = res.get(kind)
            if s:
                print(f"{kind:<7}{s['n']:>6}{s['p50_ms']:>8.1f}ms{s['p95_ms']:>7.1f}ms{s['p99_ms']:>7.1f}ms"
                      f"{s['max_ms']:>7.1f}ms{s['error_rate'] * 100:>7.2f}%  {s['codes']}")
    if a.log:
        print(f"과금 경로 요청: {report['paid_requests']}건")
    print(f"결과: {path}")
    return 1 if a.log and report["paid_requests"] else 0


if __name__ == "__main__":
    sys.exit(main())
