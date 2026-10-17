#!/usr/bin/env bash
# 카메라 판단(부스 booth_cv · 발표 태도 behavior_cv)이 쓰는 OpenCV.js 를 우리 정적 경로에 받아 둔다.
#
# 왜 — 로컬 사본이 없으면 방문자마다 jsDelivr 에서 ~10MB 를 받는다(10-08 실측). 화면은 js/vendor/opencv.js 를 먼저 찾고
# 없을 때만 CDN 으로 간다. 파일이 커서 git 에는 올리지 않는다 (.gitignore: main/web/js/vendor/opencv.js).
# 캐스케이드 XML 셋(정면 · 옆얼굴 · 눈)은 작아서 git 에 있다 — main/web/js/vendor/cv/ (README.md 에 출처 · 라이선스).
#
#   etc/scripts/get_opencv.sh            # 없으면 받는다
#   etc/scripts/get_opencv.sh --force    # 다시 받는다
#
# 빌드: @techstark/opencv-js 4.10.0-release.1 (OpenCV 4.10.0 공식 emscripten 빌드를 npm 에 올린 것, Apache-2.0).
# 이 빌드에 CascadeClassifier · calcOpticalFlowFarneback · matchTemplate · Laplacian · CamShift 가 든 것을 노드로 확인했다 (10-17).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$ROOT/main/web/js/vendor/opencv.js"
URL="https://cdn.jsdelivr.net/npm/@techstark/opencv-js@4.10.0-release.1/dist/opencv.js"
SHA="19b46167b59efbef9cc3836264b0b657110833e4b1df84282004b8b3141c048d"

if [[ -s "$DEST" && "${1:-}" != "--force" ]]; then
  echo "있음  $DEST ($(stat -c%s "$DEST") B)"
else
  echo "받음  $URL"
  curl -fsSL --retry 3 -o "$DEST.part" "$URL"
  mv "$DEST.part" "$DEST"
fi
echo "$SHA  $DEST" | sha256sum -c --quiet && echo "sha256 맞음"
