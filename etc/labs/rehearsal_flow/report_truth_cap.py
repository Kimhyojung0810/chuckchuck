"""리포트 문장 검증(바퀴 5) — 실 흐름이 남긴 저장소(run.py --storage-out)로 리포트 2.0 을 390 폭에서 다시 열어,
리포트가 **화면에 실제로 쓴 글**을 뽑고 발표 태도 화면 · 다시 보기 시간축을 찍는다. 과금 없음(리포트는 저장본만 읽는다).

  python report_truth_cap.py <base> <storage.json> <out_dir> [--tag s03] [--width 390]

남기는 것: <tag>.dom.json — 홈 발표 태도 줄 · 「예전 화면」 단추 · 발표 태도 화면(먼저 살펴볼 한 가지 · 장면 칩 · 갈래 넷 · 장면 카드 ·
Q&A 질문별 줄 · 전체 글) · 다시 보기 태도 막대(aria-label · 자리) · 시간축 「1장」 글자와 재생 머리의 겹침.
사진: <tag>_home.png · <tag>_attitude_full.png · <tag>_replay_tl.png
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("base"); ap.add_argument("storage"); ap.add_argument("out")
ap.add_argument("--tag", default="r")
ap.add_argument("--width", type=int, default=390)
args = ap.parse_args()
OUT = Path(args.out); OUT.mkdir(parents=True, exist_ok=True)
S = ".rv2 .nv-screen:last-child"

DOM_ATT = """(S) => { const el = document.querySelector(S); if (!el) return null;
  const t = (x) => (x ? x.innerText.replace(/\\s+/g, ' ').trim() : '');
  const all = (sel) => [...el.querySelectorAll(sel)].map(t);
  return { state: (el.querySelector('.bh-rv2') || {dataset: {}}).dataset.state || '',
    hero_label: t(el.querySelector('.bh-hero .bh-label')), hero: t(el.querySelector('.bh-hero .bh-head')),
    hero_chip: t(el.querySelector('.bh-hero .bh-chips')), hero_tip: t(el.querySelector('.bh-hero .bh-tip')), hero_sec: (el.querySelector('.bh-hero') || {dataset: {}}).dataset.sec || null,
    areas: all('.bh-areas2 .bh-arow'), scenes: [...el.querySelectorAll('.bh-scene')].map((s) => ({ obs: t(s.querySelector('.bh-obs')), chip: t(s.querySelector('.bh-chips')), sec: s.dataset.sec || null })),
    qa_head: t([...el.querySelectorAll('.nv-sec')].find((h) => /Q&A/.test(h.textContent))), qa_rows: all('.bh-qrows .bh-arow'),
    qa_note: t(el.querySelector('.bh-qrows ~ .nv-note, h3 + .nv-note')), prev: t(el.querySelector('.bh-prev')),
    text: t(el.querySelector('.nv-scroll')) }; }"""

DOM_REPLAY = """(S) => { const el = document.querySelector(S); if (!el) return null;
  const r = (x) => { if (!x) return null; const b = x.getBoundingClientRect(); return [Math.round(b.left * 10) / 10, Math.round(b.top * 10) / 10, Math.round(b.width * 10) / 10, Math.round(b.height * 10) / 10]; };
  const head = el.querySelector('.nv-head'); const em = el.querySelector('.nv-band em');
  const hb = head && head.getBoundingClientRect(); const eb = em && em.getBoundingClientRect();
  const overlap = hb && eb ? Math.max(0, Math.min(hb.right, eb.right) - Math.max(hb.left, eb.left)) * Math.max(0, Math.min(hb.bottom, eb.bottom) - Math.max(hb.top, eb.top)) : 0;
  return { bars: [...el.querySelectorAll('.rp-m.is-bar')].map((b) => ({ label: b.getAttribute('aria-label'), left: b.style.left, width: b.style.width })),
    dots: el.querySelectorAll('.rp-m.is-dot').length, lanes: [...el.querySelectorAll('.rp-keys span')].map((s) => s.textContent),
    band_labels: [...el.querySelectorAll('.nv-band em')].map((e) => e.textContent),
    first_band_em: r(em), head: r(head), head_overlap_px2: Math.round(overlap),
    em_area: eb ? Math.round(eb.width * eb.height) : 0 }; }"""


def main() -> None:
    res: dict = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(storage_state=args.storage, locale="ko-KR", viewport={"width": args.width, "height": 844},
                            device_scale_factor=2, is_mobile=True, has_touch=True)
        ctx.add_init_script("try { localStorage.setItem('cheokcheok:report-v2', '1'); } catch (_) {}")
        page = ctx.new_page()
        errs: list[str] = []
        page.on("pageerror", lambda e: errs.append(str(e)[:200]))
        page.goto(f"{args.base}/#/report/last", wait_until="load")
        page.wait_for_selector("#app.rv2 .nv-screen", timeout=30000)
        page.wait_for_timeout(1500)
        res["home"] = page.evaluate("""(S) => { const el = document.querySelector(S);
          const t = (x) => (x ? x.innerText.replace(/\\s+/g, ' ').trim() : '');
          return { beh_row: t(el.querySelector('.hm-beh')), oldbtn: t(el.querySelector('.nv-oldbtn')), title: t(el.querySelector('.nv-large')),
            bar: t(el.querySelector('.nv-bar')) }; }""", S)
        page.screenshot(path=str(OUT / f"{args.tag}_home.png"))
        page.evaluate("rv2Handle.open('attitude')")
        page.wait_for_timeout(900)
        res["attitude"] = page.evaluate(DOM_ATT, S)
        # 화면 전체를 한 장으로 — 스크롤 칸을 늘려 찍고 되돌린다
        page.evaluate("""() => { const s = document.querySelector('.rv2 .nv-screen:last-child .nv-scroll'); const app = document.querySelector('#app.rv2');
          window.__h = [app.style.height, app.style.overflow]; app.style.height = (s.scrollHeight + 160) + 'px'; app.style.overflow = 'visible'; }""")
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUT / f"{args.tag}_attitude_full.png"), full_page=True)
        page.evaluate("() => { const app = document.querySelector('#app.rv2'); [app.style.height, app.style.overflow] = window.__h; }")
        page.evaluate("rv2Handle.open('replay')")
        page.wait_for_timeout(900)
        res["replay"] = page.evaluate(DOM_REPLAY, S)
        tl = page.query_selector(f"{S} .rp-tl")
        if tl:
            tl.scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            tl.screenshot(path=str(OUT / f"{args.tag}_replay_tl.png"))
        res["errors"] = errs
        b.close()
    (OUT / f"{args.tag}.dom.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "attitude"}, ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
