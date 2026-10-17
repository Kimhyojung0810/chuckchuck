"""
리포트 2.0 「질문은 이렇게 골랐어요」 샘플 판 — 공개 샘플 리포트(#/rehearsal/report/demo)와 부스 시연이 바로 여는 실측 묶음.

재료는 둘 중 하나:
  --run    1~3단계 실험 산출(/data/models/_runs/qa-ensemble/runs/*/<덱>.json) + --flow(답 유형) + --bundle(그 덱의 그래프)
  --board  개발 브리지의 /api/v1/qa/board 응답 그대로(실험실 리허설 한 판)
  --state  rehearsal_flow 한 판의 state.json — 그 판 리포트 저장본에 든 판(lastReport.qaBoard). 샘플 Q&A(make_fixture --swap-qa)와 같은 판으로 맞출 때

    .venv/bin/python etc/labs/report_v2/make_qa_board.py \
        --run /data/models/_runs/qa-ensemble/runs/dev3p4/C1-r1-p4.json --flow good-good \
        --bundle /data/models/_runs/qa-route/bundles/booth_C1_delivery.json

결과: main/web/js/report_qaboard_sample.js (window.__RV2_QA_BOARD) — 손으로 고치지 않는다.
덱은 부스 시연용으로 팀이 지어낸 연구(배달앱 별점) — 사람 이름 · 연락처 같은 개인정보가 없다. 그래도 아래 PII 검사를 통과해야 쓴다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "main"))

from server import qa_board as QB  # noqa: E402

OUT = ROOT / "main/web/js/report_qaboard_sample.js"
PII = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|01[016789]-?\d{3,4}-?\d{4}|\d{6}-?[1-4]\d{6}")


def from_run(run: dict, flow: str, graph: dict) -> dict:
    ens = run["ensemble"]
    picked = [c["uid"] for c in ens.get("five") or ens.get("opening") or []]
    b = QB.board(ens["pool"], picked, graph, track="sample")
    f = (run.get("flows") or {}).get(flow) or {}
    for n, vk, qk, pk, ck in ((3, "voice1", "q3", "pick3_sec", "pick_calls"), (4, "voice2", "q4", "pick4_sec", None)):
        if not f.get(qk):
            continue
        vr = SimpleNamespace(**f[vk]) if f.get(vk) else None
        b = QB.with_round(b, QB.round_record(n, f[qk], vr, f.get(ck) or [], f.get(pk) or 0.0, paths_from=b["graph"]["nodes"]))
    return b


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="")
    ap.add_argument("--flow", default="good-good")
    ap.add_argument("--bundle", default="")
    ap.add_argument("--board", default="")
    ap.add_argument("--state", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    if a.state:
        st = json.loads(Path(a.state).read_text(encoding="utf-8"))
        b = (st.get("lastReport") or {}).get("qaBoard")
        if not b:
            sys.exit("이 state.json 의 리포트 저장본에 판(qaBoard)이 없어요")
        src = a.note or "부스 시연 덱(배달앱 별점)으로 10/17 실 API 리허설 한 판에서 네 모델이 고른 묶음이에요. 위 Q&A 기록과 같은 판이에요."
    elif a.board:
        raw = json.loads(Path(a.board).read_text(encoding="utf-8"))
        b = raw.get("board") or raw
        src = a.note or "개발 브리지에서 실제 리허설 한 판(부스 시연 덱 · 실 API)을 돌린 묶음이에요."
    else:
        run = json.loads(Path(a.run).read_text(encoding="utf-8"))
        graph = json.loads(Path(a.bundle).read_text(encoding="utf-8"))["session"]["artifacts"]["concept_graph"]
        b = from_run(run, a.flow, graph)
        src = a.note or ("부스 시연 덱(배달앱 별점)으로 10/17 실험에서 실제로 돌린 네 모델 묶음이에요. "
                         "위 Q&A 기록과는 다른 판이라, 질문 순서는 판이 고른 순서로 보여 줘요.")
    b = {**b, "source": {"kind": "sample", "note": src, "from": Path(a.state).parent.name if a.state else Path(a.board or a.run).name,
                         "flow": "" if (a.board or a.state) else a.flow}}
    text = json.dumps(b, ensure_ascii=False, separators=(",", ":"))
    if PII.search(text):
        sys.exit("개인정보로 보이는 문자열이 있어 쓰지 않았어요: " + PII.search(text).group(0)[:4] + "…")
    Path(a.out).write_text("/* 리포트 2.0 「질문은 이렇게 골랐어요」 샘플 판 — etc/labs/report_v2/make_qa_board.py 가 만든다. 손으로 고치지 않는다 */\n"
                           f"window.__RV2_QA_BOARD = {text};\n", encoding="utf-8")
    print(f"{a.out} · 후보 {len(b['candidates'])} · 버림 {len(b['dropped'])} · 자리 {len(b['slots'])} · 3번+ {len(b['rounds'])} · "
          f"모델 {b['models']} · {len(text) // 1024}KB")


if __name__ == "__main__":
    main()
