"""
scripts/booth_funnel.py — journalctl 출력·브리지 로그 → 부스 퍼널 표 (2026-10-11).

로그 줄 모양은 브리지가 실제로 쓰는 것에서 만든다(http.server 접근 로그 머리 + demo/tour_events.log_fields) —
브리지 쪽 형식이 바뀌면 여기서 깨지도록.
"""

from __future__ import annotations

import io
import json
from datetime import datetime

from demo import tour_events
from scripts import booth_funnel as bf

PHONE_A = "211.234.10.1"
PHONE_B = "223.38.20.2"
PHONE_C = "2001:e60:1234::5"


def access(ip: str, when: str, method: str, path: str, code: int, *, journal: bool = False) -> str:
    """http.server BaseHTTPRequestHandler.log_request 와 같은 줄 (log_date_time_string = 11/Oct/2026 14:02:03)."""
    d = datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
    stamp = f"{d.day:02d}/{d.strftime('%b')}/{d.year} {d:%H:%M:%S}"
    line = f'{ip} - - [{stamp}] "{method} {path} HTTP/1.1" {code} -'
    return (f"{d:%b} {d.day:2d} {d:%H:%M:%S} vm python3[4242]: " + line) if journal else line


def signal(ip: str, when: str, step: str, deck: str | None = None, t: int | None = None, *, journal: bool = True) -> str:
    d = datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
    stamp = f"{d.day:02d}/{d.strftime('%b')}/{d.year} {d:%H:%M:%S}"
    body = tour_events.log_fields({"step": step, "deck": deck, "t": t})
    line = f"{ip} - - [{stamp}] {body}"
    return (f"{d:%b} {d.day:2d} {d:%H:%M:%S} vm python3[4242]: " + line) if journal else line


LOG = [
    "Nov 03 13:59:00 vm python3[4242]: [bridge] 만료 세션 정리: 0건 지움",          # 접근 로그가 아닌 줄은 건너뛴다
    access(PHONE_A, "2026-11-03 14:01:00", "GET", "/hi", 302, journal=True),
    access(PHONE_A, "2026-11-03 14:01:01", "GET", "/index.html", 200, journal=True),
    signal(PHONE_A, "2026-11-03 14:01:02", "hi"),
    signal(PHONE_A, "2026-11-03 14:01:10", "team"),
    signal(PHONE_A, "2026-11-03 14:01:40", "explore"),
    signal(PHONE_A, "2026-11-03 14:01:41", "tour_deck", "battery-fastcharge", 41),
    signal(PHONE_A, "2026-11-03 14:02:30", "tour_present", "battery-fastcharge", 90),
    signal(PHONE_A, "2026-11-03 14:03:30", "tour_analysis", "battery-fastcharge", 150),
    signal(PHONE_A, "2026-11-03 14:04:00", "tour_qa", "battery-fastcharge", 180),
    signal(PHONE_A, "2026-11-03 14:05:00", "tour_report", "battery-fastcharge", 240),
    signal(PHONE_A, "2026-11-03 14:05:10", "try_real", t=250),
    access(PHONE_A, "2026-11-03 14:06:00", "POST", "/api/v1/parse", 200),
    # B: /hi 쿼리·끝 빗금도 같은 진입. 팀 카드까지만
    access(PHONE_B, "2026-11-03 14:20:00", "GET", "/hi/?x=1", 200),          # 랜딩 페이지가 따로 서면 200
    signal(PHONE_B, "2026-11-03 14:20:05", "team", journal=False),
    signal(PHONE_B, "2026-11-03 14:20:06", "team", journal=False),                 # 같은 IP 두 번은 1
    # C(IPv6): 다음 시간대, 투어 덱에서 멈춤 + 인앱 안내
    access(PHONE_C, "2026-11-03 15:10:00", "GET", "/hi", 302),
    signal(PHONE_C, "2026-11-03 15:10:20", "explore"),
    signal(PHONE_C, "2026-11-03 15:10:21", "tour_deck", "delivery-rating", 21),
    signal(PHONE_C, "2026-11-03 15:10:30", "inapp_notice"),
    # 퍼널 밖 공개 방문자의 업로드 — 「자료 올림」 에 안 센다
    access("198.51.100.9", "2026-11-03 15:20:00", "POST", "/api/v1/parse", 200),
    # VM 안 벤치 — 기본으로 뺀다
    access("127.0.0.1", "2026-11-03 15:30:00", "GET", "/hi", 302),
    signal("127.0.0.1", "2026-11-03 15:30:01", "team"),
    # 깨진 줄 · 모르는 단계 · 꾸민 줄
    "garbage line",
    signal(PHONE_B, "2026-11-03 15:40:00", "team").replace("step=team", "step=admin"),
]


def test_시간대별_퍼널은_단계마다_서로_다른_IP_를_센다():
    f = bf.funnel(bf.read_hits(LOG))
    assert f["total"] == {"hi": 3, "team": 2, "explore": 2, "tour_deck": 2, "tour_present": 1, "tour_analysis": 1,
                          "tour_qa": 1, "tour_report": 1, "try_real": 1, "upload": 1}
    assert [r["at"] for r in f["rows"]] == ["11/03 14:00", "11/03 15:00"]
    first, second = f["rows"]
    assert first["hi"] == 2 and first["team"] == 2 and first["tour_report"] == 1 and first["upload"] == 1
    assert second["hi"] == 1 and second["tour_deck"] == 1 and second["upload"] == 0
    assert f["rate"]["team"] == 67 and f["rate"]["tour_report"] == 33
    assert f["decks"] == {"battery-fastcharge": 1, "delivery-rating": 1}
    assert f["visitors"] == 3


def test_VM_안_요청은_옵션으로만_센다():
    assert bf.funnel(bf.read_hits(LOG))["total"]["hi"] == 3
    assert bf.funnel(bf.read_hits(LOG, include_local=True))["total"]["hi"] == 4
    assert bf.funnel(bf.read_hits(LOG, exclude=[PHONE_A]))["total"]["try_real"] == 0


def test_시간_자르기와_칸_크기():
    f = bf.funnel(bf.read_hits(LOG, since="14:10", until="15:00"))
    assert f["total"]["hi"] == 1 and f["total"]["team"] == 1
    f30 = bf.funnel(bf.read_hits(LOG), bucket_min=30)
    assert [r["at"] for r in f30["rows"]] == ["11/03 14:00", "11/03 15:00"]
    f10 = bf.funnel(bf.read_hits(LOG), bucket_min=10)
    assert [r["at"] for r in f10["rows"]] == ["11/03 14:00", "11/03 14:20", "11/03 15:10"]


def test_곁가지_신호는_all_로_본다():
    f = bf.funnel(bf.read_hits(LOG), steps=bf.FUNNEL + bf.SIDE)
    assert f["total"]["inapp_notice"] == 1 and f["total"]["intro"] == 0


def test_10_7_방식_경로별_수():
    rows = {r["key"]: r for r in bf.paths(bf.read_hits(LOG))}
    assert rows["GET /hi 302"]["ips"] == 2 and rows["GET /hi 200"]["ips"] == 1
    assert rows["GET /index.html 200"]["requests"] == 1
    assert rows["tour team"]["ips"] == 2 and rows["tour team"]["requests"] == 3
    assert rows["POST /api/v1/parse 200"]["ips"] == 2   # 경로 수는 퍼널과 달리 전부 센다


def test_표_출력과_JSON(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(LOG) + "\n"))
    assert bf.main([]) == 0
    out = capsys.readouterr().out
    assert "/hi" in out and "직접 해 보기" in out and "합계" in out and "/hi 대비" in out
    assert "battery-fastcharge 1" in out
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(LOG) + "\n"))
    assert bf.main(["--json", "--all"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total"]["hi"] == 3 and "inapp_notice" in data["steps"]


def test_파일_입력(tmp_path, capsys):
    p = tmp_path / "bridge.log"
    p.write_text("\n".join(LOG), encoding="utf-8")
    assert bf.main([str(p), "--paths", "--top", "3"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 3


def test_빈_입력도_표를_낸다(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert bf.main([]) == 0
    assert "합계" in capsys.readouterr().out


def test_브리지_신호_줄을_그대로_읽는다():
    # tour_events 가 쓰는 몸통 + log_message 머리 — 모든 단계가 집계 쪽에서 읽혀야 한다
    for step in tour_events.STEPS:
        hit = bf.parse_line(signal(PHONE_A, "2026-11-03 14:00:00", step, "sleep", 3))
        assert hit is not None and hit.kind == step and hit.deck == "sleep", step


def test_집계_단계는_서버_허용_목록과_같다():
    assert set(bf.FUNNEL) - {"upload"} | set(bf.SIDE) == set(tour_events.STEPS)
    assert set(bf.LABELS) >= set(bf.FUNNEL) | set(bf.SIDE)


def test_줄_가운데에_끼운_가짜_신호는_세지_않는다():
    # http.server 는 깨진 요청 줄을 오류 로그에 그대로 옮긴다 — 그 안에 접근 로그 모양을 넣어도 줄 맨 앞이 아니면 무시
    forged = ("Nov 03 14:30:00 vm python3[4242]: 203.0.113.9 - - [03/Nov/2026 14:30:00] code 400, message Bad request "
              "syntax ('GET 9.9.9.9 - - [03/Nov/2026 14:30:00] tour step=try_real deck=- t=1')")
    forged2 = ("203.0.113.9 - - [03/Nov/2026 14:30:00] code 400, message Bad request syntax "
               "('x 9.9.9.9 - - [03/Nov/2026 14:30:00] \"GET /hi HTTP/1.1\" 302 -')")
    assert bf.parse_line(forged) is None and bf.parse_line(forged2) is None
    # journalctl -o short-iso 앞머리도 읽는다
    iso = "2026-11-03T14:30:00+0900 vm python3[4242]: 211.234.10.1 - - [03/Nov/2026 14:30:00] tour step=team deck=- t=3"
    assert bf.parse_line(iso).kind == "team"
