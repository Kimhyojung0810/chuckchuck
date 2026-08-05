#!/usr/bin/env bash
# LoRA(F-18)까지 포함한 데모 브리지 실행기.
#
# callers: 로컬 개발자가 직접 실행 · 문서(.env.example)에서 안내
# affected: demo.bridge HTTP (:DEMO_PORT) — /api/v1/habits 가 provider=lora 로 동작
# data: CHUCKCHUCK_LORA_PATH adapter 디렉터리 (adapter_config.json + weights)
# user: "LoRA 같이 돌아가는걸 봐야하는데... 이거 어떻게 해결해...?"
#
# 기본 `python` 에는 torch 가 없어서 HABIT_PROVIDER=lora 가 heuristic 으로 떨어진다.
# midm conda env + GPU 로 띄워야 REP LoRA 가 같이 돈다.
#
# 사용:
#   ./demo/run_bridge_midm.sh
#   DEMO_PORT=8801 ./demo/run_bridge_midm.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MIDM_PY="${MIDM_PY:-/home/ubuntu/miniforge3/envs/midm/bin/python}"
if [[ ! -x "$MIDM_PY" ]]; then
  echo "midm python 없음: $MIDM_PY" >&2
  echo "  conda activate midm 후 MIDM_PY=\$(which python) 로 다시 실행하세요." >&2
  exit 1
fi

# .env 는 bash source 하지 않는다 (주석·특수문자 때문에 깨질 수 있음).
# demo.bridge → chuckchuck.config.load_dotenv() 가 키를 읽는다.
# 여기선 LoRA/포트만 셸에서 확실히 고정한다.
export MOCK_EXTERNAL_APIS="${MOCK_EXTERNAL_APIS:-false}"
export HABIT_PROVIDER="${HABIT_PROVIDER:-lora}"
export CHUCKCHUCK_LORA_PATH="${CHUCKCHUCK_LORA_PATH:-/home/ubuntu/workspace/20_AIHub_data/runs/tagger_seed42/final}"
export CHUCKCHUCK_LORA_KINDS="${CHUCKCHUCK_LORA_KINDS:-REP}"
export DEMO_HOST="${DEMO_HOST:-127.0.0.1}"
export DEMO_PORT="${DEMO_PORT:-8799}"

if ! "$MIDM_PY" -c 'import torch; assert torch.cuda.is_available()' 2>/dev/null; then
  echo "경고: midm env 에서 CUDA 를 못 봅니다. LoRA 가 CPU/실패할 수 있어요." >&2
fi

echo "척척발표 bridge (midm+LoRA)"
echo "  python: $MIDM_PY"
echo "  url:    http://${DEMO_HOST}:${DEMO_PORT}/"
echo "  mock:   $MOCK_EXTERNAL_APIS"
echo "  habits: $HABIT_PROVIDER  kinds=$CHUCKCHUCK_LORA_KINDS"
echo "  lora:   $CHUCKCHUCK_LORA_PATH"
exec "$MIDM_PY" -m demo.bridge
