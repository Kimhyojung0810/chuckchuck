#!/usr/bin/env bash
# 같은 번들을 발표 상황 4개로 재고, 상황마다 직전 기준(--compare 접두어)과 비교한다 (로드맵 B3).
# 한 상황이라도 REGRESSED 면 전체 REGRESSED — 한 상황을 살리려고 다른 상황을 망치지 않는다.
#
#   scripts/persona_bench.sh --tag persona-v1-20260912 --compare persona-base                # 기준 tag = persona-base-<상황>-20260912 꼴
#   scripts/persona_bench.sh --tag persona-base-20260912                                    # 기준선만 (비교 없음)
#   옵션: --judge · --limit N (기본 2) · --date YYYYMMDD (기준 tag 의 날짜, 기본 오늘)
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="" COMPARE="" LIMIT=2 JUDGE=0 DATE=$(date +%Y%m%d)
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) TAG=$2; shift 2 ;; --compare) COMPARE=$2; shift 2 ;; --limit) LIMIT=$2; shift 2 ;;
    --judge) JUDGE=1; shift ;; --date) DATE=$2; shift 2 ;;
    *) echo "모르는 옵션: $1" >&2; exit 2 ;;
  esac
done
[[ -n $TAG ]] || { echo "--tag 가 필요해요" >&2; exit 2; }
[[ "${MOCK_EXTERNAL_APIS:-false}" != "true" ]] || { echo "MOCK 으로는 재지 않아요" >&2; exit 2; }
PY=.venv/bin/python; [[ -x $PY ]] || PY=python
# tag 는 "<접두어>-<날짜>" 꼴. 상황을 접두어와 날짜 사이에 끼운다: persona-v1-20260912 → persona-v1-<상황>-20260912
PREFIX=${TAG%-*}; STAMP=${TAG##*-}
overall=IMPROVED; any_better=0
for s in school_project product_launch work_report casual_peer; do
  t="$PREFIX-$s-$STAMP"
  echo "=== $s → $t"
  ARGS=(examples/qa_eval.py --situation "$s" --rubric --no-coach --limit "$LIMIT" --tag "$t")
  (( JUDGE )) || ARGS+=(--no-judge)
  "$PY" "${ARGS[@]}" | grep -E '^질문 특이도|^rubric|^판정 일관성|재시도|⚠' || true
  if [[ -n $COMPARE ]]; then
    v=$("$PY" examples/qa_eval_compare.py --tag "$COMPARE-$s-$DATE" --tag "$t" --ledger --note "persona $s" | tail -1)
    echo "  $v"
    case "$v" in
      *REGRESSED*) overall=REGRESSED ;;
      *IMPROVED*) any_better=1 ;;
    esac
  fi
done
if [[ -n $COMPARE ]]; then
  [[ $overall == REGRESSED ]] || (( any_better )) || overall=NOISE
  echo "VERDICT: $overall"
else
  echo "VERDICT: BASELINE"
fi
