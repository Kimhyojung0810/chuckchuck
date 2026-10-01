"""
질문 코치 벤치 입력을 한 번 만들어 얼린다 — 자료 본문(SlideDoc) · 개념 그래프(F-06→F-07) · 주장(F-26).

왜 얼리나 — 개념 그래프 파이프라인은 다른 세션이 고치는 중이다. 코치의 전후 비교가 그래프 변화에 흔들리지 않게
같은 그래프 한 벌로만 잰다. 그래프 코드는 import 해서 부르기만 하고 고치지 않는다. 실 과금(Solar) — 한 번만 돈다.

    .venv/bin/python labs/qcoach_bench/prepare.py [--slidedoc PATH]

결과: labs/qcoach_bench/out/fixtures/{slidedoc,graph,claims}.json (덱 본문이라 .gitignore — docs/review 규칙과 같다)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
FIX = HERE / "out" / "fixtures"
#: 이 덱의 파싱본은 10-01 그래프 점검이 이미 만들어 두었다 (PPTX 를 다시 파싱하면 과금이 또 난다)
_SD = "docs/review/2026-10-01_수익률격차_그래프점검/slidedoc_수익률격차.json"
#: .gitignore 대상이라 worktree 에는 없다 — 본 체크아웃(../chuckchuck)의 것을 읽는다
DEFAULT_SLIDEDOC = next((p for p in (ROOT / _SD, ROOT.parent / "chuckchuck" / _SD) if p.exists()), ROOT / _SD)
CTX = {"situation": "school_project", "duration_min": 10}


def _env() -> None:
    from dotenv import load_dotenv
    # worktree 에는 .env 가 없다 — 본 저장소의 것을 읽는다 (값은 출력하지 않는다)
    for p in (ROOT / ".env", ROOT.parent / "chuckchuck" / ".env"):
        if p.exists():
            load_dotenv(p)
            return


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slidedoc", default=str(DEFAULT_SLIDEDOC))
    ap.add_argument("--llm", default="solar")
    args = ap.parse_args()
    _env()
    from chuckchuck import build_claims, build_graph, extract_concepts
    from chuckchuck.contracts import SlideDoc

    FIX.mkdir(parents=True, exist_ok=True)
    sd = SlideDoc.from_dict(json.loads(Path(args.slidedoc).read_text()))
    (FIX / "slidedoc.json").write_text(json.dumps(sd.to_dict(), ensure_ascii=False))
    gp = FIX / "graph.json"
    if gp.exists():
        graph = json.loads(gp.read_text())
    else:
        cd = extract_concepts(sd, CTX, llm=args.llm)
        graph = build_graph(cd, CTX, slide_doc=sd, llm=args.llm).to_dict()
        gp.write_text(json.dumps(graph, ensure_ascii=False, indent=1))
    cp = FIX / "claims.json"
    if not cp.exists():
        claims = build_claims(graph, sd, llm=args.llm)
        cp.write_text(json.dumps(claims.to_dict(), ensure_ascii=False, indent=1))
    (FIX / "context.json").write_text(json.dumps(CTX, ensure_ascii=False))
    print(f"fixtures → {FIX} · nodes={len(graph['nodes'])}")


if __name__ == "__main__":
    main()
