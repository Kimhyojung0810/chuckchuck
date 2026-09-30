#!/usr/bin/env bash
# 브리지가 공개 서비스에서 JS·CSS 의 주석·공백을 걷을 때 쓰는 esbuild 바이너리를 받는다 (demo/static_assets.py).
# 이 VM 에는 npm 이 없어서 npm 레지스트리의 정적 바이너리 하나만 받고 무결성(sha512)을 확인한다.
# 없어도 브리지는 돈다 — 줄이지 않은 파일을 그대로 보낸다.
#
#   scripts/get_esbuild.sh          # → tools/bin/esbuild
set -euo pipefail
VERSION=0.23.1
INTEGRITY="sha512-EV6+ovTsEXCPAp58g2dD68LxoP/wK5pRvgy0J/HxPGB009omFPv3Yet0HiaqvrIrgPTBuC6wCH1LTOY91EO5hQ=="
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/tools/bin/esbuild"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

curl -fsSL --max-time 60 -o "$TMP/pkg.tgz" "https://registry.npmjs.org/@esbuild/linux-x64/-/linux-x64-$VERSION.tgz"
GOT="sha512-$(openssl dgst -sha512 -binary "$TMP/pkg.tgz" | base64 -w0)"
if [ "$GOT" != "$INTEGRITY" ]; then
  echo "무결성이 맞지 않아요 — 받은 파일을 쓰지 않아요" >&2; exit 1
fi
tar -xzf "$TMP/pkg.tgz" -C "$TMP" package/bin/esbuild
mkdir -p "$(dirname "$DEST")"
install -m 0755 "$TMP/package/bin/esbuild" "$DEST"
"$DEST" --version
echo "→ $DEST"
