#!/usr/bin/env python3
"""
/hi 랜딩 전용 글꼴 서브셋 만들기 (2026-10-13).

왜 — /hi 는 Pretendard 를 jsDelivr 「dynamic subset」 CSS 로 받았는데, 글자 조각 파일 14개 · 362.6KB 로
첫 화면 전송량의 83% 였다. /hi 에 실제로 나오는 글자만 담은 woff2 한 장을 우리 서버에서 준다.

라이선스 — Pretendard 는 SIL OFL 1.1 이고 「Pretendard」 가 예약 글꼴 이름(Reserved Font Name)이다.
서브셋은 OFL 이 말하는 수정본이라 그 이름을 쓸 수 없다 → 글꼴 안 이름과 CSS 이름을 「CC Hi Sans」 로 바꾼다.
저작권 · 라이선스 칸(name ID 0 · 13 · 14)은 그대로 남기고, 원문은 main/web/assets/fonts/OFL.txt 에 둔다.

담는 글자 — intro.html 의 화면 글(주석 · <script> 안 주석 제외) · intro.js 의 문자열 · data/team.json 의 모든 문자열 값
+ 영문 · 숫자 · 기본 기호. 빠진 글자는 CSS font-family 다음 칸(Pretendard · Apple SD Gothic Neo · Noto Sans KR · 시스템)으로 떨어진다.

사용법 (team.json 이나 /hi 문구를 고친 뒤 다시 돌린다):
    ../chuckchuck/.venv/bin/pip install fonttools brotli      # 처음 한 번
    PYTHONPATH=main ../chuckchuck/.venv/bin/python etc/scripts/subset_hi_font.py          # 만들고 ?v= 까지 맞춘다
    PYTHONPATH=main ../chuckchuck/.venv/bin/python etc/scripts/subset_hi_font.py --check  # 빠진 글자만 본다(파일 안 바꿈, 빠지면 종료 코드 1)

원본(가변 woff2 2MB)은 고정 주소에서 받아 ~/.cache/chuckchuck/fonts 에 두고 sha256 으로 확인한다. --src 로 직접 줄 수도 있다.
?v= 는 브리지가 해시로 바꾸는 값(static_assets.content_digest)과 똑같이 적는다 — CSS 안 url() 은 브리지가 바꿔 쓰지 않아서,
같은 값이어야 intro.html 의 preload 와 intro.css 의 @font-face 가 한 주소(1년 immutable 캐시)가 된다.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "main" / "web"
OUT = WEB / "assets" / "fonts" / "cc-hi-sans.woff2"
REFS = [WEB / "intro.html", WEB / "css" / "intro.css"]
FAMILY = "CC Hi Sans"
WGHT_RANGE = (500, 830)   # intro.css --w-body ~ --w-display. 이 밖의 굵기를 쓰면 여기도 넓힌다

SRC_URL = ("https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/"
           "packages/pretendard/dist/web/variable/woff2/PretendardVariable.woff2")
SRC_SHA256 = "9599f12fd42fc0bce1cd50b47a0c022e108d7aa64dd0d1bb0ed44f3282d900b4"
CACHE = Path.home() / ".cache" / "chuckchuck" / "fonts" / "PretendardVariable-1.3.9.woff2"

BASE_CHARS = (
    "".join(chr(c) for c in range(0x20, 0x7F))           # 영문 · 숫자 · ASCII 기호
    + "·「」『』…—–‘’“”→←↑↓×÷%‰°±~★☆✓•○●◦※、。,."  # 이 저장소 문구에 자주 나오는 기호
    + "\u00a0"
)


def _strip_html(src: str) -> str:
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    # <script> 안은 주석이 대부분이다 — JSON-LD 의 문자열 값만 남긴다
    def keep_script(m: re.Match) -> str:
        body = m.group(1)
        return " ".join(re.findall(r'"((?:[^"\\]|\\.)*)"', body)) if "ld+json" in m.group(0)[:80] else ""
    src = re.sub(r"<script\b[^>]*>(.*?)</script>", keep_script, src, flags=re.S)
    src = re.sub(r"<style\b[^>]*>.*?</style>", " ", src, flags=re.S)
    attrs = " ".join(re.findall(r'\b(?:aria-label|alt|title|content|placeholder)="([^"]*)"', src))
    text = re.sub(r"<[^>]+>", " ", src)
    return html.unescape(text + " " + attrs)


def _js_strings(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"(^|[^:\\])//[^\n]*", r"\1", src)
    return " ".join(m.group(2) for m in re.finditer(r"""(['"`])((?:\\.|(?!\1).)*)\1""", src, flags=re.S))


def _json_strings(node) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        return " ".join(_json_strings(v) for v in node.values())
    if isinstance(node, list):
        return " ".join(_json_strings(v) for v in node)
    return ""


def wanted_chars() -> set[str]:
    text = _strip_html((WEB / "intro.html").read_text("utf-8"))
    text += _js_strings((WEB / "js" / "intro.js").read_text("utf-8"))
    text += _json_strings(json.loads((WEB / "data" / "team.json").read_text("utf-8")))
    return {c for c in text + BASE_CHARS if c.isprintable() or c == " "}


def source_font(src: str | None) -> Path:
    if src:
        return Path(src)
    if not CACHE.exists() or hashlib.sha256(CACHE.read_bytes()).hexdigest() != SRC_SHA256:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        print(f"원본 받기: {SRC_URL}")
        data = urllib.request.urlopen(SRC_URL, timeout=60).read()
        if hashlib.sha256(data).hexdigest() != SRC_SHA256:
            sys.exit("원본 글꼴 sha256 이 다르다 — 주소나 판을 확인할 것")
        CACHE.write_bytes(data)
    return CACHE


def missing_in(font_path: Path, chars: set[str]) -> list[str]:
    from fontTools.ttLib import TTFont
    cmap = TTFont(str(font_path)).getBestCmap()
    return sorted(c for c in chars if not c.isspace() and ord(c) not in cmap)


def build(src: Path, chars: set[str]) -> bytes:
    from fontTools import subset
    from fontTools.ttLib import TTFont

    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = subset.Options().layout_features + ["tnum", "kern"]
    opts.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14, 16, 17]
    opts.name_languages = ["*"]
    opts.notdef_outline = True
    font = TTFont(str(src))
    # 굵기 축을 이 페이지가 쓰는 범위(--w-body 500 ~ --w-display 830)로 줄인다 — 그 밖의 굵기 변화 자료가 빠진다
    from fontTools.varLib import instancer
    font = instancer.instantiateVariableFont(font, {"wght": WGHT_RANGE})
    sub = subset.Subsetter(opts)
    sub.populate(text="".join(chars))
    sub.subset(font)
    # OFL 예약 이름 — 수정본은 「Pretendard」 를 쓰지 않는다
    for rec in font["name"].names:
        if rec.nameID in (1, 3, 4, 6, 16):
            old = rec.toUnicode()
            new = re.sub(r"Pretendard\s*Variable|Pretendard", FAMILY, old)
            if rec.nameID == 6:
                new = new.replace(" ", "")
            rec.string = new
    import io
    buf = io.BytesIO()
    font.flavor = "woff2"
    font.save(buf)
    return buf.getvalue()


def digest(data: bytes) -> str:
    # main/server/static_assets.content_digest 와 같은 규칙 (h + sha1 앞 10자리)
    return "h" + hashlib.sha1(data).hexdigest()[:10]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="원본 가변 woff2 (안 주면 고정 주소에서 받는다)")
    ap.add_argument("--check", action="store_true", help="지금 서브셋에 빠진 글자만 보고 끝낸다")
    a = ap.parse_args()
    chars = wanted_chars()
    if a.check:
        miss = missing_in(OUT, chars) if OUT.exists() else ["(서브셋 파일 없음)"]
        print("빠진 글자:", "".join(miss) if miss else "없음")
        return 1 if miss else 0
    src = source_font(a.src)
    absent = missing_in(src, chars)
    if absent:
        print("원본에도 없는 글자(시스템 서체로 그려진다):", "".join(absent))
    data = build(src, chars)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(data)
    v = digest(data)
    for ref in REFS:
        s = ref.read_text("utf-8")
        s2 = re.sub(r"(cc-hi-sans\.woff2\?v=)[A-Za-z0-9]+", rf"\g<1>{v}", s)
        if s2 != s:
            ref.write_text(s2, "utf-8")
    print(f"{OUT.relative_to(ROOT)}  {len(data) / 1024:.1f}KB  글자 {len(chars)}개  ?v={v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
