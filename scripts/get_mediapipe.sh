#!/usr/bin/env bash
# 평가 실험실(#/lab/eval)이 쓰는 MediaPipe Tasks Vision 런타임·모델을 우리 정적 경로에 받아 둔다.
#
# 왜 — 공개 사이트에서 vendor/opencv.js 가 404 라 방문자마다 jsDelivr 로 ~10MB 를 받는다 (10-08 실측).
# 같은 일을 되풀이하지 않게 받는 스크립트를 두고, 화면은 로컬 사본을 먼저 찾고 없을 때만 CDN 으로 간다.
# 파일이 커서(합 ~29MB) git 에는 올리지 않는다 (.gitignore: demo/YEHS_demo/js/vendor/mediapipe/).
#
#   scripts/get_mediapipe.sh            # demo/YEHS_demo/js/vendor/mediapipe/ 에 받는다 (이미 있으면 건너뛴다)
#   scripts/get_mediapipe.sh --force    # 다시 받는다
#
# 크기 (2026-10-08): vision_bundle.mjs 155KB · vision_wasm_module_internal.js 323KB · .wasm 11.8MB
#                   face_landmarker 3.8MB · pose_landmarker_lite 5.8MB · hand_landmarker 7.8MB
set -euo pipefail

VER="1.0.1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/demo/YEHS_demo/js/vendor/mediapipe"
FORCE="${1:-}"
mkdir -p "$DEST/wasm"

NPM="https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@$VER"
MODELS="https://storage.googleapis.com/mediapipe-models"

declare -A SRC=(
  ["vision_bundle.mjs"]="$NPM/vision_bundle.mjs"
  ["wasm/vision_wasm_module_internal.js"]="$NPM/wasm/vision_wasm_module_internal.js"
  ["wasm/vision_wasm_module_internal.wasm"]="$NPM/wasm/vision_wasm_module_internal.wasm"
  ["face_landmarker.task"]="$MODELS/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
  ["pose_landmarker_lite.task"]="$MODELS/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
  ["hand_landmarker.task"]="$MODELS/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
SUMS="$ROOT/scripts/mediapipe.sha256"

for rel in "${!SRC[@]}"; do
  out="$DEST/$rel"
  if [[ -s "$out" && "$FORCE" != "--force" ]]; then
    echo "있음  $rel ($(stat -c%s "$out") B)"
    continue
  fi
  echo "받음  $rel"
  curl -fsSL --retry 3 -o "$out.part" "${SRC[$rel]}"
  mv "$out.part" "$out"
done

# 대조 — scripts/mediapipe.sha256 은 처음 받은 사람이 만든다 (없으면 지금 내용으로 만든다)
cd "$DEST"
if [[ -f "$SUMS" ]]; then
  sha256sum -c "$SUMS" --quiet && echo "sha256 맞음"
else
  sha256sum vision_bundle.mjs wasm/vision_wasm_module_internal.js wasm/vision_wasm_module_internal.wasm \
    face_landmarker.task pose_landmarker_lite.task hand_landmarker.task > "$SUMS"
  echo "sha256 기록 → $SUMS"
fi
du -sh "$DEST"
