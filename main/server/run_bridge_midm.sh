#!/usr/bin/env bash
# LoRA(F-18)까지 포함한 데모 브리지 실행기.
#
# callers: 로컬 개발자가 직접 실행 · 문서(.env.example)에서 안내
# affected: server.bridge HTTP (:DEMO_PORT) — /api/v1/habits 가 provider=lora 로 동작
# data: REP·FIL 어댑터 디렉터리 (adapter_config.json + weights) — CHUCKCHUCK_LORA_REP_PATH · CHUCKCHUCK_LORA_FIL_PATHS
#       (비우면 /data/models/_runs/habits-lora/ 에서 찾는다. etc/habits_lora/README.md)
# user: "LoRA 같이 돌아가는걸 봐야하는데... 이거 어떻게 해결해...?"
#
# 기본 `python` 에는 torch 가 없어서 HABIT_PROVIDER=lora 가 heuristic 으로 떨어진다.
# midm conda env(또는 torch+peft 가 있는 .venv) + GPU 로 띄워야 REP·FIL LoRA 가 같이 돈다.
# 뜨자마자 뒤에서 LoRA 를 올린다(CHUCKCHUCK_LORA_PRELOAD=0 으로 끔) — 다 올리기 전 요청은 heuristic(lora-loading).
#
# 사용:
#   ./main/server/run_bridge_midm.sh
#   DEMO_PORT=8801 ./main/server/run_bridge_midm.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

MIDM_PY="${MIDM_PY:-/home/ubuntu/miniforge3/envs/midm/bin/python}"
# 팀 GPU 서버 밖(예: .venv 에 torch+CUDA 가 있는 A100 머신)에서는 midm env 가 없다 — .venv 로 대신한다.
if [[ ! -x "$MIDM_PY" && -x "$ROOT/.venv/bin/python" ]] \
   && "$ROOT/.venv/bin/python" -c 'import torch, peft' 2>/dev/null; then
  echo "midm python 없음($MIDM_PY) — torch+peft 가 있는 $ROOT/.venv/bin/python 을 쓴다." >&2
  MIDM_PY="$ROOT/.venv/bin/python"
fi
if [[ ! -x "$MIDM_PY" ]]; then
  echo "midm python 없음: $MIDM_PY" >&2
  echo "  conda activate midm 후 MIDM_PY=\$(which python) 로 다시 실행하세요." >&2
  exit 1
fi

# .env 는 bash source 하지 않는다 (주석·특수문자 때문에 깨질 수 있음).
# server.bridge → pipeline.config.load_dotenv() 가 키를 읽는다.
# 여기선 LoRA/포트만 셸에서 확실히 고정한다.
export MOCK_EXTERNAL_APIS="${MOCK_EXTERNAL_APIS:-false}"
export HABIT_PROVIDER="${HABIT_PROVIDER:-lora}"
# 어댑터 경로는 비워 두면 _lora_tagger 가 찾는다: /data/models/_runs/habits-lora/{rep_seed42,fil_seed42,fil_seed43,fil_seed44}/final
# (REP 은 팀 GPU 서버의 옛 경로 20_AIHub_data/runs/tagger_seed42/final 도 후보). 설정했으면 그대로 넘긴다.
export CHUCKCHUCK_LORA_KINDS="${CHUCKCHUCK_LORA_KINDS:-REP}"
export HF_HOME="${HF_HOME:-/data/models/_runs/habits-lora/hf_cache}"   # 루트 디스크가 작다
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
PYTHONPATH="$ROOT/main" "$MIDM_PY" - <<'PY' || true
from pipeline._lora_tagger import load_config
c = load_config()
print(f"  base:   {c.base}")
print(f"  REP:    {c.rep.path if c.rep else '없음 → 규칙'}")
print(f"  FIL:    {[str(a.path) for a in c.fil] or '없음 → 규칙'}" + (f"  (min {c.fil_min_votes}표)" if c.fil else ""))
if c.missing:
    print(f"  ⚠ adapter_config.json 없는 경로: {list(c.missing)}")
PY
echo "  soffice: ${SOFFICE_BIN:-(PATH 탐색)}"
export PYTHONPATH="$ROOT/main${PYTHONPATH:+:$PYTHONPATH}"   # 패키지(pipeline · server)는 main/ 아래다
exec "$MIDM_PY" -m server.bridge
