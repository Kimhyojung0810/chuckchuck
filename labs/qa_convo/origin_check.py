"""
「이 질문의 근거」 누설 검사 — LLM 을 부르지 않는다 (판정 없이 lab skip 으로 넘긴다).

얼린 세션(prepare 결과)을 되살려 #/qa 의 질문마다 접힌 「이 질문의 근거」를 펴고 본문을 찍는다.
함정 질문 아래에 자료의 사실 줄(=정답)이 인용되는지 본다 (2026-09-30 held-out 감사).

    LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu .venv/bin/python labs/qa_convo/origin_check.py labs/qa_convo/out/<prep 폴더>
"""
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
prep = Path(sys.argv[1])
storage = json.loads((prep / "storage.json").read_text())
with sync_playwright() as p:
    b = p.chromium.launch(); ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_init_script(f"""(() => {{ if (sessionStorage.getItem('__s')) return; const s = {json.dumps(storage, ensure_ascii=False)};
      for (const k in s) sessionStorage.setItem(k, s[k]); sessionStorage.setItem('__s','1'); }})();""")
    pg = ctx.new_page(); pg.goto("http://127.0.0.1:8799/index.html#/qa", wait_until="networkidle"); pg.wait_for_selector("#liveAnswer", timeout=60000)
    n = pg.evaluate("qa.live.questions.length")
    for i in range(n):
        q = pg.evaluate("qa.live.questions[qa.live.qi]")
        pg.evaluate("() => document.querySelectorAll('details.msg-origin').forEach(d => d.open = true)")
        org = pg.evaluate("() => { const d = Array.from(document.querySelectorAll('details.msg-origin')).pop(); return d ? d.innerText : null; }")
        print(f"Q{i+1} trap={q.get('trap')} | {q['question'][:70]}\n   ORIGIN: {(org or '').replace(chr(10),' / ')[:300]}")
        if i == 0: pg.screenshot(path=str(prep / "origin_q1.png"))
        if q.get('trap') and not Path(prep / "origin_trap.png").exists():
            el = pg.locator("details.msg-origin").last; el.scroll_into_view_if_needed(); pg.screenshot(path=str(prep / "origin_trap.png"))
        pg.evaluate("""() => { const L = qa.live; const q = L.questions[L.qi]; closeLiveQuestion({id: q.id, label: q.label, question: q.question, answer: '(lab skip)', verdict: 'skipped', score: 0, passed: false, mastered: false, summary: ''}); advanceLiveStream(); }""")
        pg.wait_for_timeout(300)
    b.close()
