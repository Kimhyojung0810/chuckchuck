"""
Report 2.0 프로토타입 재료 — 실험실이 남긴 **실제 응답**을 리포트 v2 가 읽는 한 파일로 묶는다 (docs/report-v2/DATA_MAPPING.md).

    .venv/bin/python etc/labs/report_v2/make_fixture.py \
        --rec etc/labs/rehearsal_flow/out/rec_v2 --state etc/labs/rehearsal_flow/out/<stamp>_v2state/state.json

출처를 지어내지 않는다 — 각 묶음에 어디서 왔는지(`provenance`)를 그대로 적는다.
결과: main/web/data/report_v2_rec.json (data/*.json 은 팀 전용 정적 경로 — static_assets._TEAM_PATH)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "main/web/data/report_v2_rec.json"
SAMPLE_JS = ROOT / "main/web/js/report_sample.js"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rec", required=True, help="rehearsal_flow --record 폴더 (실 API 응답)")
    ap.add_argument("--state", required=True, help="rehearsal_flow 가 리포트 단계에서 남긴 state.json")
    ap.add_argument("--deck", default="배달앱별점인플레이션A")
    ap.add_argument("--slides-dir", default="delivery-rating", help="main/web/assets/deck-slides/<이름>")
    args = ap.parse_args()
    rec = Path(args.rec)
    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    load = lambda name: json.loads((rec / name).read_text(encoding="utf-8")) if (rec / name).exists() else None  # noqa: E731

    po = (state.get("newFlow") or {}).get("pipelineOut") or {}
    concepts = load("concepts.json") or {}
    live = state.get("liveQa") or {}
    out = {
        "schema": "report-v2-fixture/1",
        "provenance": {
            "presentation": "부스 시연 덱 녹음(사람이 실제로 발표한 m4a)을 「녹음으로 대신하기」로 넣어 실 API 로 분석 — rehearsal_flow --record (2026-10-13)",
            "analysis": "transcribe · concepts · graph · alignment · flow · pace · habits · rubric · report 응답 그대로",
            "audience": "/api/v1/chatter 실 호출 1회 (2026-10-15) — 결석(absent) 포함 그대로",
            "qa": "질문은 실 API, 답은 실험실 대본(사람 답 아님), 판정은 실 API (rehearsal_flow --weave, 2026-10-15)",
        },
        "deck": {
            "key": args.deck,
            "title": (concepts.get("slides") or [{}])[0].get("title", ""),
            "file_name": (po.get("graph") or {}).get("file_name", ""),
            "audio_url": f"/api/v1/dev/decks/file?deck={args.deck}&kind=audio",
            "slide_images": [f"assets/deck-slides/{args.slides_dir}/{s['slide_no']}.webp" for s in concepts.get("slides") or []],
            "slides": [{"slide_no": s["slide_no"], "title": s.get("title", ""), "raw_text": s.get("raw_text", "")} for s in concepts.get("slides") or []],
        },
        "context": {k: (state.get("newFlow") or {}).get(k) for k in ("occ", "min", "sec", "fileName")},
        # 받아쓰기는 단어 시각까지 — 브라우저 저장본(new-flow)은 단어를 빼서 기록 원본을 쓴다
        "transcript": load("transcribe.json"),
        "graph": po.get("graph") or load("graph.json"),
        "alignment": po.get("alignment") or load("alignment.json"),
        "flow": po.get("flow") or load("flow.json"),
        "score": po.get("score") or load("rubric.json"),
        "pace": po.get("pace") or load("pace.json"),
        "habits": po.get("habits") or load("habits.json"),
        "report": po.get("report") or load("voice_report.json"),
        "chatter": load("chatter.json"),
        "questions": load("questions.json"),
        "qa": {"questions": live.get("questions") or [], "results": live.get("results") or []},
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")
    # 공개 샘플 — /VRShow 에서 발표를 안 해도 리포트 정거장(05~09)을 둘러보게 (10-16 사용자 「미리 돌린 샘플 자료로 왔다 갔다」).
    # data/*.json 은 팀 전용이라 공개 js/ 로 낸다. 화면이 「샘플 리포트」 로 표시한다(sample: true)
    sample = {**out, "sample": True, "provenance": {"sample": "샘플 리포트예요 — 미리 돌려 둔 부스 시연 발표의 실제 분석이에요(내 발표가 아니에요).", **out["provenance"]}}
    SAMPLE_JS.write_text("/* 리포트 2.0 공개 샘플 — etc/labs/report_v2/make_fixture.py 가 만든다. 손으로 고치지 않는다 */\nwindow.__RV2_SAMPLE = "
                         + json.dumps(sample, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"→ {SAMPLE_JS.relative_to(ROOT)} ({SAMPLE_JS.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
