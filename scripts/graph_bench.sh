#!/usr/bin/env bash
# 개념 그래프(F-06→F-07)·정합(F-11)을 실 LLM 으로 다시 만들어 재고, 지정하면 직전 승자와 비교한다.
# 호출 ≈ 3~5회 · 2~3분. mock 으로는 재지 않는다 (CLAUDE.md §2).
#
#   scripts/graph_bench.sh --tag gbase-20260912                       # 기준선
#   scripts/graph_bench.sh --tag g1-20260912 --compare gbase-20260912 --note "가설 이름"
#   옵션: --bundle-dir DIR · --no-rebuild (저장된 그래프만 잰다, 호출 0)
#
# 마지막 줄이 VERDICT: IMPROVED|REGRESSED|NOISE|BASELINE|INVALID 다. INVALID = 노드 0 (F-06/07 실패).
set -euo pipefail
cd "$(dirname "$0")/.."

TAG="" COMPARE="" NOTE="" BUNDLE_DIR="" REBUILD=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) TAG=$2; shift 2 ;;
    --compare) COMPARE=$2; shift 2 ;;
    --note) NOTE=$2; shift 2 ;;
    --bundle-dir) BUNDLE_DIR=$2; shift 2 ;;
    --no-rebuild) REBUILD=0; shift ;;
    *) echo "모르는 옵션: $1" >&2; exit 2 ;;
  esac
done
[[ -n $TAG ]] || { echo "--tag 가 필요해요" >&2; exit 2; }
[[ "${MOCK_EXTERNAL_APIS:-false}" != "true" ]] || { echo "MOCK 으로는 벤치마크를 재지 않아요 (CLAUDE.md §2)" >&2; exit 2; }

PY=.venv/bin/python; [[ -x $PY ]] || PY=python
ARGS=(examples/graph_eval.py --tag "$TAG")
(( REBUILD )) && ARGS+=(--rebuild)
[[ -n $BUNDLE_DIR ]] && ARGS+=(--bundle-dir "$BUNDLE_DIR")
[[ -n $COMPARE ]] && ARGS+=(--compare "$COMPARE" --ledger --note "$NOTE")

echo "▶ $PY ${ARGS[*]}"
"$PY" "${ARGS[@]}"

if ! "$PY" - "$TAG" <<'PYCHK'
import json, sys
from pathlib import Path
tag = sys.argv[1]; out = Path("exports/graph_eval")
hits = sorted(out.glob(f"*_{tag}.corpus.json")) or sorted(out.glob(f"*_{tag}.json"))
s = json.loads(hits[-1].read_text(encoding="utf-8")).get("summary", {}) if hits else {}
if not s.get("nodes"):
    print("⚠ 노드가 0 — F-06/F-07 이 실패했다. 이 측정은 비교에 쓰지 않아요."); sys.exit(1)
PYCHK
then echo "VERDICT: INVALID"; exit 0; fi
[[ -n $COMPARE ]] || echo "VERDICT: BASELINE"
