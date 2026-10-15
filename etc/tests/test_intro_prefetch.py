"""/hi 가 미리 받는 투어 자산(intro.html <template id="tour-prefetch">)이 index.html 과 같은 주소인가 (2026-10-13).

브리지는 둘 다 ?v= 를 내용 해시로 바꿔 넣어 저절로 맞지만, 브리지 밖 정적 호스팅에서는 손으로 적은 값이 그대로 나간다 —
index.html 의 ?v= 를 올리고 여기를 안 올리면 미리 받은 파일이 캐시에서 안 쓰인다. 그리고 /hi 글꼴 preload 와 @font-face 주소가 같은가.
"""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "main" / "web"


def _refs(html: str) -> dict[str, str]:
    out = {}
    for path, v in re.findall(r'\b(?:href|src)="/?([^"?#]+\.(?:css|js))\?v=([^"&#]+)"', html):
        out[path] = v
    return out


def test_prefetch_matches_index():
    intro = (WEB / "intro.html").read_text("utf-8")
    tpl = re.search(r'<template id="tour-prefetch">(.*?)</template>', intro, re.S)
    assert tpl, "intro.html 에 tour-prefetch template 이 없다"
    want = _refs(tpl.group(1))
    assert want, "미리 받을 주소가 비었다"
    have = _refs((WEB / "index.html").read_text("utf-8"))
    for path, v in want.items():
        assert path in have, f"{path} 는 index.html 이 받지 않는다"
        assert have[path] == v, f"{path}: intro {v} ≠ index {have[path]} — index.html 의 ?v= 를 따라 올릴 것"


def test_hi_font_preload_matches_font_face():
    intro = (WEB / "intro.html").read_text("utf-8")
    css = (WEB / "css" / "intro.css").read_text("utf-8")
    pre = re.search(r'rel="preload" href="(/assets/fonts/[^"]+)"', intro)
    face = re.search(r'url\("(/assets/fonts/[^"]+)"\)', css)
    assert pre and face and pre.group(1) == face.group(1)
    assert (WEB / pre.group(1).split("?")[0].lstrip("/")).is_file()
