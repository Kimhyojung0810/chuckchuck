#!/usr/bin/env bash
# sudo 없는 A100 머신(yehschuck, .venv 에 torch+CUDA)에서 실 API 브리지를 띄운다.
#
# callers: 사람이 직접 실행 (CLAUDE.md §2 의 run_bridge_midm.sh 를 이 머신에 맞게 감싼 것)
# affected: demo.bridge HTTP (:DEMO_PORT, 기본 8799) — 백그라운드, 로그는 $LOG
# data: ~/.local/bin/{soffice,ffmpeg} · CHUCKCHUCK_LORA_PATH(있으면)
#
# ── 한 번만 하는 설치 (루트 불필요, 2026-09-23 실측) ─────────────────────────────
#   # ffmpeg — 리허설 녹음 webm 을 A.X STT 로 보낼 때 10MB 미만 WAF 우회(PCM WAV 로 키우기)에 필요
#   mkdir -p ~/.local/opt/ffmpeg && cd ~/.local/opt/ffmpeg
#   curl -fsSL https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz | tar xJ
#   ln -sf "$PWD"/ffmpeg-*-static/ffmpeg ~/.local/bin/ffmpeg
#
#   # LibreOffice — PPTX 원본 슬라이드 미리보기(/api/v1/preview-pdf). FUSE 없이 AppImage 를 푼다.
#   mkdir -p ~/.local/opt/libreoffice && cd ~/.local/opt/libreoffice
#   curl -fsSLo lo.AppImage https://appimages.libreitalia.org/LibreOffice-previous.standard-x86_64.AppImage
#   chmod +x lo.AppImage && ./lo.AppImage --appimage-extract >/dev/null && rm lo.AppImage
#   ln -sf "$PWD"/squashfs-root/opt/libreoffice*/program/soffice ~/.local/bin/soffice
#   #  ⚠ squashfs-root/AppRun 은 쓰지 않는다 — 내부에서 cd 해서 상대경로 입력을 못 연다.
#
#   # 한글 폰트 — 없으면 PDF 가 두부(□)로 나온다
#   mkdir -p ~/.local/share/fonts/noto-cjk && cd ~/.local/share/fonts/noto-cjk
#   for w in Regular Bold; do curl -fsSLO https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/KR/NotoSansKR-$w.otf; done
#   fc-cache -f ~/.local/share/fonts
#
# ── LoRA(F-18) ────────────────────────────────────────────────────────────────────
#   어댑터(adapter_config.json) 가 이 머신에 없다(2026-09-23 `find /` 결과 0건). 팀 GPU 서버의
#   /home/ubuntu/workspace/20_AIHub_data/runs/tagger_seed42/final 을 복사해 오고
#   CHUCKCHUCK_LORA_PATH 로 넘기기 전까지 /api/v1/habits 는 provider=heuristic(lora-fallback) 이다.
#
# 사용:
#   ./scripts/run_bridge_local.sh                     # 8799, 백그라운드
#   DEMO_PORT=8801 ./scripts/run_bridge_local.sh
#   CHUCKCHUCK_LORA_PATH=~/lora/tagger_seed42/final ./scripts/run_bridge_local.sh
# 끄기: 출력된 PID 로 `kill <PID>` — `pkill -f "python -m demo.bridge"` 는 금지(자기 셸까지 죽는다).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PATH="$HOME/.local/bin:$PATH"
export MIDM_PY="${MIDM_PY:-$ROOT/.venv/bin/python}"
export SOFFICE_BIN="${SOFFICE_BIN:-$HOME/.local/bin/soffice}"
export DEMO_PORT="${DEMO_PORT:-8799}"
LOG="${LOG:-$ROOT/var/log/bridge_${DEMO_PORT}.log}"
mkdir -p "$(dirname "$LOG")"

[[ -x "$SOFFICE_BIN" ]] || echo "경고: soffice 없음($SOFFICE_BIN) — PPTX 미리보기가 자리표시자로 떨어진다. 머리말의 설치 절차" >&2
command -v ffmpeg >/dev/null || echo "경고: ffmpeg 없음 — 10MB 미만 녹음 받아쓰기가 WAF 에 막힐 수 있다" >&2
if [[ -n "${CHUCKCHUCK_LORA_PATH:-}" && ! -f "$CHUCKCHUCK_LORA_PATH/adapter_config.json" ]]; then
  echo "경고: $CHUCKCHUCK_LORA_PATH 에 adapter_config.json 없음 — F-18 은 heuristic 으로 떨어진다" >&2
fi

nohup ./demo/run_bridge_midm.sh > "$LOG" 2>&1 &
PID=$!
echo "bridge PID $PID · 로그 $LOG · http://127.0.0.1:$DEMO_PORT/"
echo "예열: CLAUDE.md §2 의 /api/v1/habits curl (응답 provider 확인)"
