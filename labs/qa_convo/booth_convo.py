"""
부스 통화(booth.html) 대화 감사 — 사진 → 분석 → 발표 → 질문 받기 → 여러 턴 대본 → 통화 마치기.

labs/qa_call/run.py 는 단계마다 한 번씩만 누른다. 여기서는 사람처럼 한 질문 안에서 여러 번 오간다:
  Q1: 절반 답 → 판정 → 「다시 답하기」 → 보완 → 판정 → 힌트 1·2 → 좋은 답
  Q2: 모르겠어요 → (보기·되물음이 오나?) → 다시 답할 수 있나? → 다음
  Q3: 오답 → 다시 답하기 → 정답
  나머지는 손대지 않고 통화 마치기 → 결과 표에 안 물은 질문이 어떻게 뜨나
말풍선 전문 · 판정 요청/응답 · 버튼 상태 · 사진을 동작마다 남긴다. 실 LLM 과금.

    LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu .venv/bin/python labs/qa_convo/booth_convo.py [--mobile] [--photos a.jpg b.jpg] [--bank fixture]
결과: labs/qa_convo/out/booth_<stamp>[_mobile]/turns.json · *.png
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
sys.path.insert(0, str(ROOT / "labs/qa_call"))

# 답 은행 — 질문 글과 낱말이 가장 많이 겹치는 항목을 고른다. 사진 자료를 읽고 사람이 쓴 답이다.
BANKS = {
    "fixture": [
        {"keys": "타깃 고객 대학생 취업준비생 기업 확장 초기",
         "good": "초기 타깃은 대학 수업이나 공모전, 면접 발표를 준비하는 대학생이랑 취업준비생이고요, 그다음에 기업 보고나 영업, 사내교육 같은 전문 커뮤니케이션 쪽으로 넓히려고 해요.",
         "partial": "대학생이 먼저예요.",
         "addon": "대학생·취업준비생 다음에는 기업의 보고, 영업, 사내교육 쪽으로 확장할 계획이에요.",
         "wrong": "처음부터 기업 고객만 노리고 있어요, 개인은 안 받아요."},
        {"keys": "수익 모델 BM 구독 B2C B2B SaaS 과금 유료",
         "good": "개인 사용자에게는 구독형 서비스로 B2C 를 하고, 대학이나 기업에는 조직 단위 SaaS 로 B2B 도입을 하는 걸 주요 수익모델로 검토하고 있어요.",
         "partial": "구독료를 받아요.",
         "addon": "개인은 구독형 B2C, 대학·기업은 조직 단위 SaaS 도입 B2B 예요.",
         "wrong": "광고 수익으로 운영하려고 해요."},
        {"keys": "차별 정합성 발화 자료 누락 설명 부족 논리 흐름 기술 코칭",
         "good": "발표자료랑 실제로 말한 발화를 같이 분석해서 핵심 개념이 빠졌는지, 설명이 부족한지, 논리 흐름이 맞는지를 진단하고, 약한 개념을 골라 Q&A 로 다시 설명하게 하는 게 차별점이에요.",
         "partial": "자료랑 말을 같이 봐요.",
         "addon": "누락·설명 부족·논리 흐름을 진단하고, 취약 개념 기반 Q&A 로 설명 능력을 키워요.",
         "wrong": "목소리 톤이랑 제스처만 분석해서 점수를 매기는 서비스예요."},
        {"keys": "고민 멘토 자문 시장성 검증 집중 결선 피칭 시연 배치 비중",
         "good": "B2C 대학생 개인 사용자랑 B2B 기관 고객 중 어디에 먼저 집중해야 시장성을 가장 빨리 검증할 수 있을지, 그리고 결선에서 기술 설명과 사용자 문제·효과 비중을 어떻게 나눌지, 시연을 언제 넣을지가 고민이에요.",
         "partial": "B2C 냐 B2B 냐가 고민이에요.",
         "addon": "그리고 무료 체험에서 유료로 넘어가는 구조랑 과금 단위도 자문받고 싶어요.",
         "wrong": "고민은 딱히 없고 투자 금액만 정하면 돼요."},
        {"keys": "단계 PoC MVP 프로토타입 매출",
         "good": "지금은 프로토타입, MVP 를 보유한 단계예요. 아이디어 검증은 지났고 실제 유저 매출은 아직이에요.",
         "partial": "개발 중이에요.",
         "addon": "PoC 는 지났고 MVP 보유 단계, 매출은 아직이에요.",
         "wrong": "이미 유저가 많고 매출도 나고 있어요."},
    ],
}
GENERIC = {"good": "자료에 적힌 대로, 핵심 주장과 그걸 뒷받침하는 근거를 같이 말하면 그게 답이에요.",
           "partial": "음 자료에 있었던 것 같아요.", "addon": "자료에 적힌 근거를 하나 더 들면 이거예요.",
           "wrong": "그건 자료랑 상관없이 제 생각이에요."}


def pick(bank: list[dict], text: str) -> dict:
    best, score = GENERIC, 0
    for row in bank:
        s = sum(1 for k in row["keys"].split() if k in text)
        if s > score:
            best, score = row, s
    return best


def run(args) -> Path:
    from playwright.sync_api import sync_playwright
    from fakecam import build as build_cam

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + ("_mobile" if args.mobile else "")
    out = OUT / f"booth_{stamp}_{args.bank}"
    out.mkdir(parents=True, exist_ok=True)
    cam = build_cam(out / "fakecam.mjpeg")
    rec: dict = {"mobile": args.mobile, "photos": args.photos, "actions": [], "console": [], "questions": []}
    net: list[dict] = []
    t_req: dict = {}
    n = [0]
    bank = BANKS.get(args.bank, [])

    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                    f"--use-file-for-fake-video-capture={cam}", "--autoplay-policy=no-user-gesture-required"])
        ctx = b.new_context(viewport={"width": 390, "height": 844} if args.mobile else {"width": 1280, "height": 860},
                            device_scale_factor=2 if args.mobile else 1, has_touch=args.mobile,
                            permissions=["camera", "microphone"])
        page = ctx.new_page()
        page.on("console", lambda m: rec["console"].append(f"{m.type}: {m.text}"[:300]) if m.type == "error" else None)
        page.on("pageerror", lambda e: rec["console"].append(f"pageerror: {e}"[:300]))
        page.on("request", lambda r: t_req.__setitem__(r, time.time()) if "/api/" in r.url else None)

        def on_resp(r):
            if "/api/" not in r.url:
                return
            row = {"path": r.url.split("/api/")[-1][:60], "status": r.status, "sec": round(time.time() - t_req.get(r.request, time.time()), 2)}
            if "/qa/" in r.url:
                try:
                    row["req"] = {k: v for k, v in json.loads(r.request.post_data or "{}").items() if k not in ("artifacts", "question")}
                    row["res"] = r.json()
                except Exception as e:  # noqa: BLE001
                    row["err"] = str(e)[:200]
            net.append(row)
        page.on("response", on_resp)

        def shot(name: str) -> str:
            n[0] += 1
            f = f"{n[0]:02d}_{name}.png"
            page.screenshot(path=str(out / f))
            return f

        def bubbles() -> list[dict]:
            return page.evaluate("Array.from(document.querySelectorAll('#call-bubbles .call-bubble')).map(b => ({cls: b.className.replace('call-bubble glass ', ''), v: b.dataset.v || '', text: b.innerText.trim()}))")

        def ui() -> dict:
            return page.evaluate("""() => { const st = (id) => { const e = document.getElementById(id); return e ? (e.hidden ? 'hidden' : (e.disabled ? 'disabled' : 'on')) + '|' + e.textContent.trim().slice(0, 20) : null; };
                return { count: (document.getElementById('qa-count')||{}).textContent, mood: document.getElementById('call-partner-seat').dataset.mood,
                  status: document.getElementById('call-partner-status').textContent, note: document.getElementById('qa-mic-note').textContent,
                  placeholder: document.getElementById('qa-answer').placeholder, input: document.getElementById('qa-answer').disabled ? 'disabled' : 'on',
                  btn: Object.fromEntries(['btn-answer','btn-hint','btn-giveup','btn-again','btn-next','btn-leave','btn-mic'].map(i => [i, st(i)])),
                  hscroll: document.documentElement.scrollWidth > innerWidth }; }""")

        def act(qn: int, kind: str, text: str = "") -> dict:
            nb, nn = len(bubbles()), len(net)
            t0 = time.time()
            if kind == "answer":
                page.fill("#qa-answer", text)
                page.click("#btn-answer")
            elif kind == "giveup":
                if text:
                    page.fill("#qa-answer", text)
                page.click("#btn-giveup")
            elif kind == "hint":
                page.click("#btn-hint")
            elif kind == "again":
                page.click("#btn-again")
            elif kind == "next":
                page.click("#btn-next")
            if kind in ("answer", "giveup"):
                page.wait_for_function("(n) => document.querySelectorAll('#call-bubbles .call-bubble').length > n + 1", arg=nb, timeout=120000)
            page.wait_for_timeout(1800)
            new = bubbles()[nb:]
            calls = net[nn:]
            j = next((c.get("res") for c in reversed(calls) if "/qa/" in c["path"]), None)
            row = {"q": qn, "action": kind, "input": text, "new_bubbles": new, "ui": ui(),
                   "judge": j, "judge_req": next((c.get("req") for c in reversed(calls) if "/qa/" in c["path"]), None),
                   "calls": [{k: c[k] for k in ("path", "status", "sec")} for c in calls], "sec": round(time.time() - t0, 1)}
            row["shot"] = shot(f"q{qn}_{kind}")
            rec["actions"].append(row)
            v = j or {}
            print(f"  Q{qn} {kind:7s} {text[:30]!r:34s} → {v.get('verdict', '-')}/{v.get('score', '-')} stage={v.get('coach_stage') or v.get('probe_tier') or '-'} "
                  f"bubbles+{len(new)} {row['sec']}s", flush=True)
            (out / "turns.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
            return row

        def can(btn: str) -> bool:
            return page.is_visible(f"#{btn}") and page.is_enabled(f"#{btn}")

        try:
            t0 = time.time()
            page.goto(f"{args.base}/booth.html", wait_until="networkidle")
            if args.track:
                try:
                    page.select_option("#ctx-track", args.track)
                except Exception:
                    try:
                        page.click(f'#ctx-track [value="{args.track}"]')
                    except Exception:
                        pass
            page.set_input_files("#file-shots", args.photos)
            page.wait_for_function(f"document.querySelectorAll('.booth-shot').length==={len(args.photos)}")
            shot("capture")
            page.click("#btn-go")
            page.wait_for_selector("#call:not([hidden]), #progress-error:not([hidden])", timeout=300000)
            rec["analyze_sec"] = round(time.time() - t0, 1)
            if page.is_visible("#progress-error"):
                rec["error"] = page.inner_text("#progress-error-text")
                shot("analyze_error")
                return out
            page.wait_for_timeout(1200)
            shot("present")
            page.click("#btn-ask")
            page.wait_for_selector("#call-bubbles .call-bubble.is-question", timeout=15000)
            page.wait_for_timeout(2500)
            rec["questions"] = page.evaluate("(() => { try { return (window.boothLab && window.boothLab.state) ? window.boothLab.state().questions : null } catch (e) { return null } })()")
            first = bubbles()
            rec["actions"].append({"q": 1, "action": "ask", "new_bubbles": first, "ui": ui(), "shot": shot("q1_ask")})

            def qtext() -> str:
                qs = page.evaluate("Array.from(document.querySelectorAll('#call-bubbles .call-bubble.is-question')).map(b => b.innerText)")
                return qs[-1] if qs else ""

            nq = int((page.inner_text("#qa-count").split("/")[-1]).strip() or 1)
            rec["n_questions"] = nq
            if args.stop_after:
                nq = min(nq, args.stop_after)   # 끝까지 안 가고 통화를 마친다 — 안 물은 질문이 결과 표에 어떻게 뜨나
            def answerable() -> bool:
                return page.is_enabled("#qa-answer") and can("btn-answer")

            # Q1 — 힌트 두 번 → 절반 → (되물으면) 보완 → (또 되물으면) 좋은 답
            a = pick(bank, qtext())
            rec["actions"][-1]["bank_pick"] = a.get("keys")
            for _ in range(2):
                if can("btn-hint"):
                    act(1, "hint")
            act(1, "answer", a["partial"])
            if answerable():
                act(1, "answer", a["addon"])
            if answerable():
                act(1, "answer", a["good"])
            if nq >= 2:
                act(1, "next")
                # Q2 — 모르겠어요 → (다시 답할 수 있으면) 짧은 답 → 모르겠어요 한 번 더
                a = pick(bank, qtext())
                act(2, "giveup")
                if can("btn-again"):
                    act(2, "again")
                if answerable():
                    act(2, "answer", a["partial"])
                if can("btn-giveup"):
                    act(2, "giveup")
            if nq >= 3:
                act(2, "next")
                a = pick(bank, qtext())
                act(3, "answer", a["wrong"])
                if can("btn-again"):
                    act(3, "again")
                if answerable():
                    act(3, "answer", a["good"])
            rec["final_bubbles"] = bubbles()
            page.click("#btn-leave")
            page.wait_for_selector("#qa-done:not([hidden])", timeout=5000)
            page.wait_for_timeout(600)
            rec["tally"] = page.evaluate("Array.from(document.querySelectorAll('#qa-tally li')).map(li => li.textContent)")
            rec["done_text"] = page.inner_text("#qa-done")
            shot("finish")
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"[:500]
            print("  ✕", rec["error"])
            try:
                shot("error")
            except Exception:
                pass
        finally:
            (out / "turns.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
            b.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8799")
    ap.add_argument("--mobile", action="store_true")
    ap.add_argument("--bank", default="fixture")
    ap.add_argument("--track", default="")
    ap.add_argument("--stop-after", type=int, default=0, help="이 질문까지만 하고 통화를 마친다")
    ap.add_argument("--photos", nargs="*", default=[str(ROOT / "labs/qa_call/fixture_slide1.jpg"), str(ROOT / "labs/qa_call/fixture_slide2.jpg")])
    args = ap.parse_args()
    t = time.time()
    out = run(args)
    print(f"끝 {time.time() - t:.0f}s → {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
