"""
질문 코치 벤치 입력을 한 번 만들어 얼린다 — 자료 본문(SlideDoc) · 개념 그래프(F-06→F-07) · 주장(F-26).

왜 얼리나 — 개념 그래프 파이프라인은 다른 세션이 고치는 중이다. 코치의 전후 비교가 그래프 변화에 흔들리지 않게
같은 그래프 한 벌로만 잰다. 그래프 코드는 import 해서 부르기만 하고 고치지 않는다. 실 과금(Solar) — 한 번만 돈다.
이미 얼린 그래프·주장이 있으면 다시 만들지 않는다 (다시 얼리려면 out/fixtures 의 그 파일을 지운다).

    .venv/bin/python labs/qcoach_bench/prepare.py [--slidedoc PATH]

결과: labs/qcoach_bench/out/fixtures/{slidedoc,graph,claims,context}.json (덱 본문이라 .gitignore — docs/review 규칙과 같다)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import FIX, first_existing, load_env

#: 이 덱의 파싱본은 10-01 그래프 점검이 이미 만들어 두었다 (PPTX 를 다시 파싱하면 과금이 또 난다). .gitignore 대상이다
DEFAULT_SLIDEDOC = first_existing("docs/review/2026-10-01_수익률격차_그래프점검/slidedoc_수익률격차.json")
CTX = {"situation": "school_project", "duration_min": 10}


def _write(name: str, data: dict, *, indent: int | None = 1) -> None:
    (FIX / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=indent))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slidedoc", default=str(DEFAULT_SLIDEDOC))
    ap.add_argument("--llm", default="solar")
    args = ap.parse_args()
    load_env()
    from chuckchuck import build_claims, build_graph, extract_concepts
    from chuckchuck.contracts import SlideDoc

    FIX.mkdir(parents=True, exist_ok=True)
    sd = SlideDoc.from_dict(json.loads(Path(args.slidedoc).read_text()))
    _write("slidedoc", sd.to_dict(), indent=None)
    graph_path = FIX / "graph.json"
    if graph_path.exists():
        graph = json.loads(graph_path.read_text())
    else:
        concepts = extract_concepts(sd, CTX, llm=args.llm)
        graph = build_graph(concepts, CTX, slide_doc=sd, llm=args.llm).to_dict()
        _write("graph", graph)
    if not (FIX / "claims.json").exists():
        _write("claims", build_claims(graph, sd, llm=args.llm).to_dict())
    _write("context", CTX, indent=None)
    print(f"fixtures → {FIX} · nodes={len(graph['nodes'])}")


if __name__ == "__main__":
    main()
