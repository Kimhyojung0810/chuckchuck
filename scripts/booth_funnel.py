#!/usr/bin/env python3
"""
부스 퍼널 집계 — 브리지 접근 로그(journalctl 출력 또는 파일) → 시간대별 /hi → 팀 카드 → 살펴보기 → 투어 → 직접 해 보기 표.

10/7 QR 집계와 같은 방식이다 — 접근 로그의 **방문자 IP** 를 센다(IP ≠ 사람: 폰 IPv6 는 바뀌고, 행사장 와이파이는 여럿이 한 IP).
다른 점은 투어 단계를 API 로 어림하지 않고 화면이 보낸 신호 줄(`tour step=…`, demo/tour_events.py)로 센다는 것.
/hi 진입은 `GET /hi …` 접근 로그 줄(302 또는 랜딩 페이지 200 — Cloudflare 가 저장하지 않는 동안 원본까지 온다)과
화면 신호 `step=hi` 둘 중 하나면 1 이다(같은 IP 는 한 번). HTML 캐시 규칙에 /hi 를 넣으면 접근 로그 줄이 줄고 신호가 대신 센다.

    sudo journalctl -u chuckchuck-bridge --since "2026-11-03 09:00" -o cat | python3 scripts/booth_funnel.py
    sudo journalctl -u chuckchuck-bridge --since today | python3 scripts/booth_funnel.py --bucket 30
    python3 scripts/booth_funnel.py var/log/bridge_8989.log --include-local     # 실험 브리지(VM 안 요청 포함)
    sudo journalctl -u chuckchuck-bridge --since today | python3 scripts/booth_funnel.py --paths   # 10/7 처럼 경로별 수
    … | python3 scripts/booth_funnel.py --json

표준 라이브러리만 쓴다. 저장소 밖(맥북 등)에서도 이 파일 하나로 돈다.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable, NamedTuple

#: 퍼널 열 — 화면 차례. upload 는 「직접 해 보기」 뒤 실제 흐름에서 자료를 올린 것(POST /api/v1/parse 200).
FUNNEL = ("hi", "team", "explore", "tour_deck", "tour_present", "tour_analysis", "tour_qa", "tour_report",
          "try_real", "upload")
#: 퍼널 밖 곁가지 신호 (--all 로 같이 본다) — demo/tour_events.py STEPS 와 맞춘다
SIDE = ("intro", "team_end", "inapp_notice", "back_team")
LABELS = {
    "hi": "/hi", "intro": "소개", "team": "팀 카드", "team_end": "팀 끝", "explore": "살펴보기",
    "tour_deck": "덱", "tour_present": "발표", "tour_analysis": "분석", "tour_qa": "Q&A", "tour_report": "리포트",
    "try_real": "직접 해 보기", "upload": "자료 올림", "inapp_notice": "인앱 안내", "back_team": "팀으로",
}
_MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}

#: `<IP> - - [11/Oct/2026 14:02:03] <나머지>` — http.server 접근 로그 머리. **줄 맨 앞**(또는 journalctl 의
#: 「Nov 03 14:01:00 vm python3[123]: 」 · 「2026-11-03T14:01:00+0900 vm python3[123]: 」 앞머리 바로 뒤)에서만 읽는다 —
#: 줄 가운데서 찾으면, 깨진 요청 줄을 그대로 옮겨 적는 오류 로그(`code 400, message Bad request syntax ('… 1.2.3.4 - - [..] tour step=…')`)
#: 로 누구나 가짜 신호 줄을 끼워 넣을 수 있다.
_LINE = re.compile(r"^(?:(?:[A-Z][a-z]{2} [ \d]\d \d\d:\d\d:\d\d|\d{4}-\d\d-\d\dT[\d:.+-]+) \S+ [^\s\[]+\[\d+\]: )?"
                   r"(?P<ip>[0-9A-Fa-f:.]{2,45}) - - \[(?P<d>\d{2})/(?P<mon>[A-Z][a-z]{2})/(?P<y>\d{4}) "
                   r"(?P<hms>\d{2}:\d{2}:\d{2})\] (?P<rest>.*)$")
_ACCESS = re.compile(r'^"(?P<method>[A-Z]{3,7}) (?P<target>\S+) HTTP/\d(?:\.\d)?" (?P<code>\d{3})')
_TOUR = re.compile(r"^tour step=(?P<step>[a-z_]{1,20}) deck=(?P<deck>\S{1,41}) t=(?P<t>\S{1,6})\s*$")
#: 우리 설비 — VM 안 실험·벤치·운영 curl. 기본으로 뺀다 (demo/shield.py INFRA_RANGES 와 같은 대역)
_INFRA = [ipaddress.ip_network(c) for c in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16",
    "::1/128", "fc00::/7", "fe80::/10")]


class Hit(NamedTuple):
    at: datetime
    ip: str
    kind: str            # FUNNEL·SIDE 단계 이름, 또는 "path" (그 밖의 접근 로그 줄)
    path: str = ""       # 접근 로그 줄이면 「메서드 경로 상태」 (--paths 열쇠), 신호 줄이면 빈 값
    deck: str = ""


def _infra(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr.version == n.version and addr in n for n in _INFRA)


def _path_of(target: str) -> str:
    p = target.split("?", 1)[0].split("#", 1)[0]
    return (p.rstrip("/") or "/").lower()


def parse_line(line: str) -> Hit | None:
    """로그 한 줄 → Hit. 접근 로그·신호 줄이 아니면 None."""
    m = _LINE.match(line.rstrip("\n"))
    if not m or m["mon"] not in _MONTHS:
        return None
    try:
        h, mi, s = (int(x) for x in m["hms"].split(":"))
        at = datetime(int(m["y"]), _MONTHS[m["mon"]], int(m["d"]), h, mi, s)
    except ValueError:
        return None
    ip, rest = m["ip"], m["rest"]
    t = _TOUR.match(rest)
    if t:
        step = t["step"]
        if step not in FUNNEL and step not in SIDE:
            return None
        return Hit(at, ip, step, deck="" if t["deck"] == "-" else t["deck"])
    a = _ACCESS.match(rest)
    if not a:
        return None
    path, code = _path_of(a["target"]), int(a["code"])
    key = f"{a['method']} {path} {code}"
    # /hi 는 지금 302(→ /index.html#/hi), 랜딩 페이지가 따로 서면 200(intro.html) — 어느 쪽이든 진입이다. /hi/<팀원 id> 도.
    if a["method"] in ("GET", "HEAD") and (path == "/hi" or path.startswith("/hi/")) and code in (200, 302, 304):
        return Hit(at, ip, "hi", path=key)
    if a["method"] == "POST" and path == "/api/v1/parse" and code == 200:
        return Hit(at, ip, "upload", path=key)
    return Hit(at, ip, "path", path=key)


def _when(raw: str | None, ref: datetime | None) -> datetime | None:
    """--since/--until — 「HH:MM」(첫 줄의 날짜) 또는 「YYYY-MM-DD HH:MM」."""
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    hm = datetime.strptime(raw, "%H:%M")
    base = ref or datetime.now()
    return base.replace(hour=hm.hour, minute=hm.minute, second=0, microsecond=0)


def read_hits(lines: Iterable[str], *, include_local: bool = False, exclude: Iterable[str] = (),
              since: str | None = None, until: str | None = None) -> list[Hit]:
    skip = set(exclude)
    hits = [h for h in (parse_line(ln) for ln in lines) if h is not None]
    hits = [h for h in hits if h.ip not in skip and (include_local or not _infra(h.ip))]
    ref = hits[0].at if hits else None
    lo, hi = _when(since, ref), _when(until, ref)
    return [h for h in hits if (lo is None or h.at >= lo) and (hi is None or h.at < hi)]


def _bucket(at: datetime, minutes: int) -> datetime:
    """하루 안에서 minutes 칸으로 내림 (minutes 는 1440 의 약수)."""
    m = (at.hour * 60 + at.minute) // minutes * minutes
    return at.replace(hour=m // 60, minute=m % 60, second=0, microsecond=0)


def funnel(hits: list[Hit], *, bucket_min: int = 60, steps: tuple[str, ...] = FUNNEL) -> dict:
    """시간대별 · 합계 — 단계마다 서로 다른 IP 수. 「자료 올림」 은 퍼널에 들어온 IP 만 센다(다른 공개 방문자 업로드 제외)."""
    visitors = {h.ip for h in hits if (h.kind in FUNNEL and h.kind != "upload") or h.kind in SIDE}
    rows: dict[datetime, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    total: dict[str, set] = defaultdict(set)
    decks: dict[str, set] = defaultdict(set)
    for h in hits:
        if h.kind not in steps or (h.kind == "upload" and h.ip not in visitors):
            continue
        rows[_bucket(h.at, bucket_min)][h.kind].add(h.ip)
        total[h.kind].add(h.ip)
        if h.deck and h.kind.startswith("tour_"):
            decks[h.deck].add(h.ip)
    base = len(total["hi"]) or max((len(v) for v in total.values()), default=0)
    return {
        "steps": list(steps),
        "rows": [{"at": at.strftime("%m/%d %H:%M"), **{s: len(rows[at][s]) for s in steps}} for at in sorted(rows)],
        "total": {s: len(total[s]) for s in steps},
        "rate": {s: (round(100 * len(total[s]) / base) if base else 0) for s in steps},
        "decks": {d: len(ips) for d, ips in sorted(decks.items(), key=lambda kv: -len(kv[1]))},
        "visitors": len(visitors),
    }


def paths(hits: list[Hit], top: int = 30) -> list[dict]:
    """10/7 방식 — 「메서드 경로 상태」 별 요청 수 · 서로 다른 IP 수."""
    req: dict[str, int] = defaultdict(int)
    ips: dict[str, set] = defaultdict(set)
    for h in hits:
        key = h.path or f"tour {h.kind}"   # 접근 로그 줄은 「메서드 경로 상태」, 신호 줄은 「tour 단계」
        req[key] += 1
        ips[key].add(h.ip)
    order = sorted(req, key=lambda k: (-len(ips[k]), -req[k], k))[:top]
    return [{"key": k, "requests": req[k], "ips": len(ips[k])} for k in order]


# ─── 출력 ─────────────────────────────────────────────────────────────────────


def _w(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s: str, width: int, right: bool = True) -> str:
    gap = " " * max(0, width - _w(s))
    return gap + s if right else s + gap


def render(f: dict) -> str:
    steps = f["steps"]
    head = ["시간"] + [LABELS.get(s, s) for s in steps]
    body = [[r["at"]] + [str(r[s]) for s in steps] for r in f["rows"]]
    body.append(["합계"] + [str(f["total"][s]) for s in steps])
    body.append(["/hi 대비"] + [f"{f['rate'][s]}%" for s in steps])
    widths = [max(_w(row[i]) for row in [head, *body]) for i in range(len(head))]
    line = lambda row: "  ".join(_pad(c, widths[i], right=i > 0) for i, c in enumerate(row))  # noqa: E731
    out = [line(head), "  ".join("─" * w for w in widths)]
    out += [line(r) for r in body[:-2]]
    out += ["  ".join("─" * w for w in widths), line(body[-2]), line(body[-1])]
    if f["decks"]:
        out.append("")
        out.append("투어 덱별 IP: " + " · ".join(f"{d} {n}" for d, n in f["decks"].items()))
    out.append(f"(단계마다 서로 다른 방문자 IP 수 · 퍼널에 들어온 IP {f['visitors']}개 · IP ≠ 사람)")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="부스 퍼널 집계 (journalctl 출력 · 브리지 로그 파일)")
    ap.add_argument("files", nargs="*", help="로그 파일 (없으면 표준 입력)")
    ap.add_argument("--bucket", type=int, default=60, help="시간대 칸(분): 10·15·30·60·120 … 1440 의 약수 (기본 60)")
    ap.add_argument("--since", help="이때부터 — HH:MM 또는 'YYYY-MM-DD HH:MM'")
    ap.add_argument("--until", help="이때 전까지 — 같은 모양")
    ap.add_argument("--all", action="store_true", help="곁가지 신호(소개·팀 끝·인앱 안내·팀으로)도 열로")
    ap.add_argument("--paths", action="store_true", help="10/7 방식 — 경로별 요청 수·IP 수")
    ap.add_argument("--top", type=int, default=30, help="--paths 줄 수")
    ap.add_argument("--include-local", action="store_true", help="VM 안·사설·Tailscale IP 도 센다 (실험 브리지)")
    ap.add_argument("--exclude", action="append", default=[], help="빼는 IP (팀 폰 등, 여러 번)")
    ap.add_argument("--json", action="store_true", help="JSON 으로")
    a = ap.parse_args(argv)
    if a.bucket <= 0 or 1440 % a.bucket:
        ap.error("--bucket 은 하루(1440분)를 나누어떨어지게 — 10·15·30·60·120·180·240 …")

    def lines():
        if not a.files:
            yield from sys.stdin
        for name in a.files:
            with open(name, encoding="utf-8", errors="replace") as fh:
                yield from fh

    hits = read_hits(lines(), include_local=a.include_local, exclude=a.exclude, since=a.since, until=a.until)
    if a.paths:
        rows = paths(hits, a.top)
        if a.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for r in rows:
                print(f"{r['ips']:>5} IP  {r['requests']:>6} 회  {r['key']}")
        return 0
    f = funnel(hits, bucket_min=a.bucket, steps=FUNNEL + SIDE if a.all else FUNNEL)
    print(json.dumps(f, ensure_ascii=False, indent=1) if a.json else render(f))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
