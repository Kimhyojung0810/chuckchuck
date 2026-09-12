#!/usr/bin/env bash
# Q&A 벤치마크를 한 번 재고, 지정하면 직전 승자와 비교해 판정을 찍는다.
# 실 LLM 을 부른다 — .env 가 필요하고 과금된다. mock 으로는 재지 않는다 (CLAUDE.md §2).
#
#   scripts/qa_bench.sh --tag base-20260912                 # 기준선 (비교 없음)
#   scripts/qa_bench.sh --tag v1-20260912 --compare base-20260912 --note "가설 이름"
#   옵션: --rubric (7항목 LLM 심사, 호출 +1) · --judge (F-09 판정까지, 호출 ~9배) · --coach (막힘 코칭까지)
#         --limit N (기본 2)
#         --bundle-dir DIR (동의 세션 묶음) · --track 1|5|10
#
# 마지막 줄이 VERDICT: IMPROVED|REGRESSED|NOISE|BASELINE|INVALID 다. 자동 루프는 이 줄만 읽는다.
# INVALID = 질문이 전부 코드 조립 폴백 (LLM 이 지시를 못 따랐거나 응답이 잘렸다). 이런 측정은
# 프롬프트가 아니라 그날의 LLM 을 잰 것이라 비교에 쓰지 않는다 — 2026-09-12 첫 루프에서 실제로 겪었다.
set -euo pipefail
cd "$(dirname "$0")/.."

TAG="" COMPARE="" NOTE="" BUNDLE_DIR="" TRACK=5 LIMIT=2 JUDGE=0 COACH=0 RUBRIC=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) TAG=$2; shift 2 ;;
    --compare) COMPARE=$2; shift 2 ;;
    --note) NOTE=$2; shift 2 ;;
    --bundle-dir) BUNDLE_DIR=$2; shift 2 ;;
    --track) TRACK=$2; shift 2 ;;
    --limit) LIMIT=$2; shift 2 ;;
    --judge) JUDGE=1; shift ;;
    --coach) COACH=1; shift ;;
    --rubric) RUBRIC=1; shift ;;
    *) echo "모르는 옵션: $1" >&2; exit 2 ;;
  esac
done
[[ -n $TAG ]] || { echo "--tag 가 필요해요" >&2; exit 2; }
[[ "${MOCK_EXTERNAL_APIS:-false}" != "true" ]] || { echo "MOCK 으로는 벤치마크를 재지 않아요 (CLAUDE.md §2)" >&2; exit 2; }
[[ -f .env ]] || echo "경고: .env 가 없어요 — LLM 호출이 실패할 수 있어요" >&2

PY=.venv/bin/python; [[ -x $PY ]] || PY=python
ARGS=(examples/qa_eval.py --tag "$TAG" --track "$TRACK" --limit "$LIMIT")
(( JUDGE )) || ARGS+=(--no-judge)
(( COACH )) || ARGS+=(--no-coach)
(( RUBRIC )) && ARGS+=(--rubric)
[[ -n $BUNDLE_DIR ]] && ARGS+=(--bundle-dir "$BUNDLE_DIR")

echo "▶ $PY ${ARGS[*]}"
"$PY" "${ARGS[@]}"

# 방금 남은 결과(코퍼스 파일 우선)가 전부 폴백이면 비교하지 않는다.
if ! "$PY" - "$TAG" <<'PYCHK'
import json, sys
from pathlib import Path
tag = sys.argv[1]
out = Path("exports/qa_eval")
hits = sorted(out.glob(f"*_{tag}.corpus.json")) or sorted(out.glob(f"*_{tag}.json"))
s = json.loads(hits[-1].read_text(encoding="utf-8")).get("summary", {}) if hits else {}
q, fb = s.get("questions") or 0, s.get("fallback") or 0
if q and fb >= q:
    print(f"⚠ 질문 {q}개가 전부 폴백 — LLM 응답 이상. 이 측정은 비교에 쓰지 않아요.")
    sys.exit(1)
PYCHK
then
  echo "VERDICT: INVALID"
  exit 0
fi

if [[ -n $COMPARE ]]; then
  "$PY" examples/qa_eval_compare.py --tag "$COMPARE" --tag "$TAG" --ledger --note "$NOTE"
else
  echo "VERDICT: BASELINE"
fi
