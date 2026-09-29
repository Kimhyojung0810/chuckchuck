"""
#/qa 대화를 **질문마다 정한 동작 순서**로 누른다 — labs/qa_convo/run.py 의 Driver 를 그대로 쓰고, 페르소나(P1~P8) 대신
감사용 동작 목록(모순 질문의 side_deck · side_speech · typo_claim · dunno 등)을 준다. 제품 코드는 건드리지 않는다.

    LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu .venv/bin/python \
      "docs/review/2026-09-30_QA_녹음대화감사/tools/play_script.py" --base http://127.0.0.1:8833 \
      --prep labs/qa_convo/out/<prep> --script labs/qa_convo/answers/<file>.json --tag side_deck

script JSON: {"_default": "skip", "1": {"persona": "side_deck", "steps": [["answer", "…"], ["answer", "…"]]}, ...}
    동작: answer <글> · stuck(「모르겠어요」 버튼) · choice <번호|-1=자료와 가장 겹치는 보기> · hint · reveal
    목록에 없는 질문은 판정 없이 넘긴다(과금 없음). 목록을 다 돌고도 안 닫히면 「답 보기」(판정 없음)로 닫는다.
끝나면 결과 화면과 상세 리포트(#/report)의 글·사진을 남긴다.
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
    ap.add_argument("--prep", required=True)
    ap.add_argument("--script", required=True)
    ap.add_argument("--tag", default="script")
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    prep = Path(args.prep)
    meta = json.loads((prep / "prepared.json").read_text(encoding="utf-8"))
    storage = json.loads((prep / "storage.json").read_text(encoding="utf-8"))
    script = json.loads(Path(args.script).read_text(encoding="utf-8"))
    qs = meta["questions"]
    out = prep / f"play_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{args.tag}"
    out.mkdir(parents=True, exist_ok=True)
    record = {"prep": prep.name, "deck": meta["deck"], "mode": meta["mode"], "track": meta["track"], "tag": args.tag,
              "script": str(args.script), "questions": qs, "turns": [], "console": []}

    def save() -> None:
        (out / "turns.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    with sync_playwright() as p:
        b, ctx = R.launch(p)
        ctx.add_init_script(f"""(() => {{ try {{ if (sessionStorage.getItem('__qa_convo_seeded')) return;
            const s = {json.dumps(storage, ensure_ascii=False)}; for (const k in s) sessionStorage.setItem(k, s[k]);
            sessionStorage.setItem('__qa_convo_seeded', '1'); }} catch (e) {{}} }})();""")
        page = ctx.new_page()
        page.on("pageerror", lambda e: record["console"].append(f"pageerror: {e}"[:300]))
        page.on("console", lambda m: record["console"].append(f"{m.type}: {m.text}"[:300]) if m.type == "error" else None)
        d = R.Driver(page, out, args.base)
        try:
            page.goto(f"{args.base}/index.html#/qa", wait_until="networkidle")
            page.wait_for_selector("#liveAnswer", timeout=60000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out / "00_entry.png"), full_page=True)
            record["entry_turns"] = page.evaluate("qa.turns.map(t => ({who: t.who, kind: t.kind, text: String(t.text || '').replace(/<[^>]+>/g, '')}))")
            record["entry_stream"] = page.inner_text("#stream")[:4000]
            for i, q in enumerate(qs):
                qn = i + 1
                plan = script.get(str(qn))
                if not plan:
                    page.evaluate("""() => { const L = qa.live; const q = L.questions[L.qi];
                        closeLiveQuestion({id: q.id, label: q.label, question: q.question, answer: '(lab skip)', verdict: 'skipped',
                          score: 0, passed: false, mastered: false, summary: ''}); advanceLiveStream(); }""")
                    page.wait_for_timeout(500)
                    continue
                pid = plan.get("persona", "script")
                start_qi = d.state()["qi"]
                turns = []

                def closed() -> bool:
                    s = d.state()
                    return s["qi"] != start_qi or s["awaitEnd"]

                print(f"  Q{qn} {pid} — {q.get('question')[:70]}", flush=True)
                for step in plan["steps"]:
                    if closed():
                        break
                    kind = step[0]
                    if kind == "choice":
                        idx = step[1] if len(step) > 1 else -1
                        if idx < 0:
                            idx = R.pick_chip(page, q)
                        t = d.act(qn, pid, "choice", "", idx)
                    elif kind in ("answer", "retell"):
                        t = d.act(qn, pid, kind, step[1])
                    else:
                        if kind == "hint" and "liveHint" not in " ".join(d.state()["buttons"]):
                            continue
                        t = d.act(qn, pid, kind)
                    turns.append(t)
                    v = t["judge"] or {}
                    print(f"      {kind:6s} {t['input'][:40]!r:44s} → {v.get('verdict', '-')}/{v.get('score', '-')} "
                          f"stage={v.get('coach_stage') or v.get('probe_tier') or '-'} {'CLOSED' if closed() else ''}", flush=True)
                guard = 0
                while not closed() and guard < 3:
                    guard += 1
                    btns = " ".join(d.state()["buttons"])
                    if "liveReveal" in btns:
                        turns.append(d.act(qn, pid, "reveal"))
                    elif d.state()["retell"] and "liveSkipRetell" in btns:
                        turns.append(d.act(qn, pid, "skip_retell"))
                    else:
                        page.evaluate("""() => { const L = qa.live; const q = L.questions[L.qi];
                            closeLiveQuestion({id: q.id, label: q.label, question: q.question, answer: '(lab close)', verdict: 'skipped',
                              score: 0, passed: false, mastered: false, summary: ''}); advanceLiveStream(); }""")
                        page.wait_for_timeout(500)
                        break
                record["turns"].extend(turns)
                (out / f"q{qn}_{pid}.md").write_text(R.md_transcript(q, qn, pid, turns), encoding="utf-8")
                save()
            page.wait_for_timeout(800)
            page.screenshot(path=str(out / "99_end.png"))
            if page.is_visible("#liveSeeResult"):
                page.click("#liveSeeResult")
                page.wait_for_timeout(1800)
                record["result_text"] = page.inner_text("#app")[:4000]
                page.screenshot(path=str(out / "99_result.png"), full_page=True)
                if not args.no_report:
                    try:
                        page.click('a[href="#/report"]')
                        page.wait_for_timeout(5000)
                        page.evaluate("() => document.querySelectorAll('details').forEach(d => d.open = true)")
                        page.wait_for_timeout(600)
                        record["report_qa_log"] = page.evaluate("() => { const f = document.querySelector('.qa-log-fold'); return f ? f.innerText : null; }")
                        record["report_text"] = page.inner_text("#app")[:16000]
                        page.screenshot(path=str(out / "99_report.png"), full_page=True)
                    except Exception as e:  # noqa: BLE001
                        record["report_error"] = str(e)[:200]
        except Exception as e:  # noqa: BLE001
            record["error"] = f"{type(e).__name__}: {e}"[:500]
            print("  ✕", record["error"])
            try:
                page.screenshot(path=str(out / "error.png"))
            except Exception:
                pass
        finally:
            save()
            b.close()
    n_calls = sum(len(t["calls"]) for t in record["turns"])
    print(f"  판정 호출 {n_calls}회 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
