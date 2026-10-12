"""etc/scripts/booth_qr.py — 결선 부스 QR PNG 쓰기(표준 라이브러리) · 주소 고정 (2026-10-11)."""

from __future__ import annotations

import struct
import zlib

import pytest

from scripts import booth_qr


def _read_gray_png(data: bytes) -> tuple[int, int, list[bytes]]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            w, h, depth, color = struct.unpack(">IIBB", body[:10])
            assert (depth, color) == (8, 0)
        elif tag == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    rows = [raw[i * (w + 1) + 1:(i + 1) * (w + 1)] for i in range(h)]
    return w, h, rows


def test_주소는_꼬리표_없는_hi_하나다():
    # ?src= 같은 꼬리표는 Cloudflare 캐시 열쇠를 가른다 — 진입은 서버 로그 GET /hi 로 센다
    assert booth_qr.URL == "https://chuckchuck-present.com/hi"
    assert "?" not in booth_qr.URL and booth_qr.BORDER >= 4


def test_PNG_는_정확히_1024px_이고_여백_4칸_이상_칸은_정수_픽셀(tmp_path):
    n = 33
    matrix = [[1 if (x, y) in ((0, 0), (n - 1, n - 1)) else 0 for x in range(n)] for y in range(n)]
    info = booth_qr.write_png(matrix, tmp_path / "q.png")
    w, h, rows = _read_gray_png((tmp_path / "q.png").read_bytes())
    assert (w, h) == (1024, 1024)
    scale = info["scale_px"]
    assert scale == 1024 // (n + 8) and info["quiet_zone_modules"] >= 4
    off = (1024 - scale * n) // 2
    # 여백은 전부 흰색, 첫 칸(검정)은 scale×scale 로 꽉 찬다
    assert set(rows[off - 1]) == {255} and set(rows[0]) == {255}
    assert rows[off][off:off + scale] == b"\x00" * scale and rows[off][off + scale] == 255


def test_segno_가_있으면_오류_정정_Q_이상으로_만든다():
    segno = pytest.importorskip("segno")
    qr = booth_qr.make_qr()
    assert qr.error in ("Q", "H") and qr.version <= 5
    assert isinstance(segno.__version__, str)
