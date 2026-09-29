"""
이미 녹음까지 태운 세션(prepare 로 얼린 storage.json)을 되살려 **질문 코칭 시작 화면에서 다른 시간(트랙)** 을 고른다.

같은 녹음·같은 분석 결과로 5분 트랙 질문을 보려고 파이프라인(객석·채점·리포트 LLM 약 17콜)을 다시 태우지 않는다 — 사용자가
분석이 끝난 뒤 시작 화면에서 5분을 고르는 것과 같은 길이다. 질문 코칭 상태(cheokcheok:qa-flow)만 비우고 #/qa 를 연다.

    LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu .venv/bin/python \
      "docs/review/2026-09-30_QA_녹음대화감사/tools/reprepare_track.py" --base http://127.0.0.1:8833 \
      --from labs/qa_convo/out/<t10 prep> --track 5
결과: labs/qa_convo/out/<stamp>_<덱>_audio_t<트랙>/prepared.json · storage.json (run.py prepare 와 같은 꼴)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "labs" / "qa_convo"))
import run as R  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--track", default="5", choices=("1", "5", "10"))
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    src = Path(args.src)
    meta = json.loads((src / "prepared.json").read_text(encoding="utf-8"))
    storage = json.loads((src / "storage.json").read_text(encoding="utf-8"))
    storage.pop("cheokcheok:qa-flow", None)
    out = R.OUT / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{meta['deck']}_{meta['mode']}_t{args.track}"
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b, ctx = R.launch(p)
        ctx.add_init_script(f"""(() => {{ try {{ if (sessionStorage.getItem('__qa_convo_seeded')) return;
            const s = {json.dumps(storage, ensure_ascii=False)}; for (const k in s) sessionStorage.setItem(k, s[k]);
            sessionStorage.setItem('__qa_convo_seeded', '1'); }} catch (e) {{}} }})();""")
        page = ctx.new_page()
        t0 = time.time()
        page.goto(f"{args.base}/index.html#/qa", wait_until="networkidle")
        page.wait_for_selector("#qaGateStart", timeout=60000)
        page.click(f'.qa-mode[data-mode="{args.track}"]')
        page.wait_for_timeout(400)
        page.screenshot(path=str(out / "gate.png"))
        page.click("#qaGateStart")
        while time.time() - t0 < 600:
            page.wait_for_timeout(2000)
            if page.evaluate("typeof qaLiveActive === 'function' && qaLiveActive()") and page.is_visible("#liveAnswer"):
                break
        page.wait_for_timeout(1500)
        page.screenshot(path=str(out / "qa_first.png"), full_page=True)
        qs = page.evaluate("qa.live.questions")
        st = page.evaluate("Object.fromEntries(Object.keys(sessionStorage).map(k => [k, sessionStorage.getItem(k)]))")
        st.pop("__qa_convo_seeded", None)
        (out / "storage.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        (out / "prepared.json").write_text(json.dumps({
            "deck": meta["deck"], "mode": meta["mode"], "track": args.track, "qa_mode": page.evaluate("qa.mode"),
            "session_id": page.evaluate("qa.live.sessionId"), "questions": qs, "from": src.name,
            "sec": round(time.time() - t0, 1)}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  질문 {len(qs)}개 (트랙 {args.track}) {time.time() - t0:.0f}s → {out}")
        for i, q in enumerate(qs, 1):
            print(f"    Q{i}{' [함정]' if q.get('trap') else ''} {q.get('label')}: {q.get('question')[:110]}")
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
