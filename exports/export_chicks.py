#!/usr/bin/env python3
"""병아리(발표새) SVG → 배경 투명 PNG + 단독 실행 가능한 SVG 내보내기.

원본은 두 군데다 (둘 다 코드 안의 인라인 SVG, 이미지 파일이 아니다):
  1) demo/YEHS_demo/js/chatter.js  : Chatter.chickSvg(speaker)  — 4 모델 × mood
  2) demo/YEHS_demo/f11_reveal.html: wbBirdSvg(prop)            — 작업대 새 4종

애니메이션은 전부 끄고 mood 정지 프레임을 굽는다. mood 상태 규칙은
STATE_CSS 한 곳에만 적고 PNG·SVG 양쪽에 같은 문자열을 주입한다.
"""

import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]   # exports/ 의 부모 = 저장소 루트
DEMO = ROOT / "demo" / "YEHS_demo"
OUT = ROOT / "exports" / "chicks"
PNG_SIZE = 1024
VIEWBOX = "-6 -6 112 112"  # 볏·날개 외곽선이 가장자리에서 깎이지 않게 여유를 준다

SPEAKERS = ["midm", "solar", "exaone", "ax"]
MOODS = ["neutral", "happy", "curious", "grumpy", "excited"]
PROPS = ["none", "phones", "slides", "pen"]

KO = {"midm": "믿음", "solar": "쏠라", "exaone": "엑사원", "ax": "엑씨"}

# css/chatter.css :root 와 같은 값 (단독 SVG 는 그 파일을 못 읽으니 안에 심는다)
VARS = """svg{--chick-body:#FFD96A;--chick-midm:#FFD96A;--chick-solar:#FFD96A;
--chick-exaone:#FFD96A;--chick-ax:#FFD96A;--chick-line:#356B59;--chick-belly:#FFF3CF;
--chick-mint:#9ADBC0;--chick-beak:#F0A93C;--chick-blush:#F7B6A8;}
*{animation:none!important;transition:none!important;}
.ch-blush{opacity:.5!important}
.ch-eye-line{fill:none;stroke:#2F3B33;stroke-width:2.6;stroke-linecap:round;opacity:0!important}
.ch-heart{opacity:0!important}.ch-mark{opacity:0!important}.ch-pen-stroke{opacity:0!important}
"""
# ↑ 전부 !important 다. 페이지에서는 chatter.css 의 `.ch-chick .ch-heart`(특이도 0,2,0)가
#   여기 규칙(0,1,0)을 이겨서 하트·물음표가 안 나온다. 아래 mood 규칙도 같은 이유로
#   !important 를 달고, 나중에 선언되므로 이 기본값을 덮는다.

# mood 별 정지 상태. chatter.css 의 [data-mood] 규칙과 같은 결과를 내되,
# 애니메이션으로만 표현되던 것(놀람 눈·형광펜 밑줄)은 여기서 최종 프레임으로 굳힌다.
_WIDE = "transform-box:fill-box;transform-origin:center;"
STATE_CSS = {
    "neutral": "",
    "happy": ".ch-eye-happy{opacity:1!important}.ch-eye-ball,.ch-eye-hi{opacity:0!important}"
             ".ch-heart{opacity:1!important}",
    "curious": ".ch-mark{opacity:1!important}"
               ".ch-eye-ball{transform:scale(1.08)!important;" + _WIDE + "}",
    "grumpy": ".ch-eye-grumpy{opacity:1!important}.ch-eye-ball,.ch-eye-hi{opacity:0!important}"
              ".ch-pen-stroke{opacity:.55!important;clip-path:none!important}",
    "excited": ".ch-eye-ball{transform:scale(1.2)!important;" + _WIDE + "}",
}

HARNESS = """<!doctype html><meta charset="utf-8">
<style>
  html,body{background:transparent!important;margin:0;padding:0}
  .ch-chick{width:%dpx!important;height:auto!important;max-width:none!important;
            transform:none!important;overflow:visible!important;display:block!important}
</style>
<div id="stage"></div>
""" % PNG_SIZE


def extract_wb_bird_svg(html: str) -> str:
    """f11_reveal.html 에서 wbBirdSvg 함수 본문만 떼어 온다.

    페이지 전체를 로드하면 리빌 초기화가 통째로 돈다 — 함수만 가져와 평가한다.
    """
    start = html.index("function wbBirdSvg(prop)")
    end = html.index("\n}", start) + 2
    return html[start:end]


def prepare(page, markup: str, state_css: str) -> None:
    """SVG 하나를 무대에 세우고 viewBox·xmlns·상태 CSS 를 입힌다."""
    page.evaluate(
        """([markup, css, viewBox, size]) => {
            const stage = document.getElementById('stage');
            stage.innerHTML = markup;
            const svg = stage.querySelector('svg');
            svg.classList.add('ch-chick');
            svg.setAttribute('viewBox', viewBox);
            svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
            svg.setAttribute('width', size);
            svg.setAttribute('height', size);
            svg.removeAttribute('style');
            const style = document.createElementNS('http://www.w3.org/2000/svg', 'style');
            style.textContent = css;
            svg.insertBefore(style, svg.firstChild);
        }""",
        [markup, VARS + state_css, VIEWBOX, PNG_SIZE],
    )


def shoot(page, png_dir: Path, svg_dir: Path, name: str) -> None:
    page.locator("#stage svg").screenshot(path=str(png_dir / f"{name}.png"), omit_background=True)
    markup = page.evaluate("() => document.querySelector('#stage svg').outerHTML")
    (svg_dir / f"{name}.svg").write_text(markup, encoding="utf-8")


def main() -> None:
    png_dir, svg_dir = OUT / "png", OUT / "svg"
    for d in (png_dir, svg_dir):
        d.mkdir(parents=True, exist_ok=True)

    wb_src = extract_wb_bird_svg((DEMO / "f11_reveal.html").read_text(encoding="utf-8"))
    made = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": PNG_SIZE + 200, "height": PNG_SIZE + 200})
        page.set_content(HARNESS)
        page.add_style_tag(path=str(DEMO / "css/chatter.css"))
        page.add_script_tag(path=str(DEMO / "js/chatter.js"))

        # 1) 객석 발표새 — 모델 4 × mood 5
        for speaker in SPEAKERS:
            markup = page.evaluate("s => Chatter.chickSvg(s)", speaker)
            for mood in MOODS:
                name = f"chick_{speaker}_{KO[speaker]}_{mood}"
                prepare(page, markup, STATE_CSS[mood])
                shoot(page, png_dir, svg_dir, name)
                made.append(name)

        # 2) 작업대 새 (F-11 분석 연출) — 소품 4종
        page.evaluate(f"() => {{ {wb_src}; window.wbBirdSvg = wbBirdSvg; }}")
        for prop in PROPS:
            markup = page.evaluate("p => window.wbBirdSvg(p)", prop)
            name = f"workbench_bird_{prop}"
            prepare(page, markup, "")
            shoot(page, png_dir, svg_dir, name)
            made.append(name)

        browser.close()

    # base_dir 을 줘야 압축을 풀 때 chicks/ 폴더 하나로 떨어진다.
    # root_dir 만 주면 png/·svg/·README 가 받은 폴더에 그대로 쏟아진다.
    shutil.make_archive(str(OUT.parent / "chicks"), "zip",
                        root_dir=str(OUT.parent), base_dir=OUT.name)
    print(f"{len(made)} 종 내보냄 → {OUT}")
    for n in made:
        print("  ", n)


if __name__ == "__main__":
    main()
