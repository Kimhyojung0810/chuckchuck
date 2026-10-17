#!/usr/bin/env bash
# 모델 장부(etc/bench/results/ledgers/MODEL_LEDGER.md)를 다시 재는 한 줄 — 정기적으로 돌린다.
# 실 LLM 을 부른다 — .env 가 필요하고 과금된다. mock 으로는 재지 않는다 (CLAUDE.md §2).
#
#   etc/scripts/model_bench.sh                 # 점검(모델마다 작은 호출 1번) + Q&A 모델 벤치(기본 조합 × 번들 × 2회) → 장부에 줄 추가
#   etc/scripts/model_bench.sh --health        # 점검만 (몇 초, 거의 공짜)
#   etc/scripts/model_bench.sh --reps 1 --configs solar/solar,solar/exaone
#
# 번들(자료 본문이 든 고정 입력)은 저장소 밖에 둔다. 없으면 부스 덱 셋으로 먼저 만든다 (Solar 로 F-06·F-07·F-26·F-11, ~2분).
# Upstage 키는 서비스(8799)와 같다 — 동시 실행은 2 를 넘기지 않는다 (10-16 첫 실행에서 5개 동시 → 429).
set -euo pipefail
cd "$(dirname "$0")/../.."

PY=.venv/bin/python; [[ -x $PY ]] || PY=python
BUNDLES="${MODEL_BENCH_BUNDLES:-/data/models/_runs/qa-route/bundles}"
[[ "${MOCK_EXTERNAL_APIS:-false}" != "true" ]] || { echo "MOCK 으로는 재지 않아요 (CLAUDE.md §2)" >&2; exit 2; }

if [[ "${1:-}" == "--health" ]]; then
  exec "$PY" etc/bench/model_bench.py health --ledger
fi

"$PY" etc/bench/model_bench.py health --ledger || echo "(점검에 실패한 모델이 있어요 — 위 줄을 보세요. 벤치는 계속해요)" >&2
if ! ls "$BUNDLES"/*.json >/dev/null 2>&1; then
  "$PY" etc/bench/build_deck_bundle.py --booth --out "$BUNDLES"
fi
exec "$PY" etc/bench/model_bench.py qa --bundle-dir "$BUNDLES" --ledger "$@"
