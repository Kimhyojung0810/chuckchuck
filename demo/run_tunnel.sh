#!/usr/bin/env bash
# 척척발표 데모를 외부에서 볼 수 있게 Cloudflare Tunnel 로 내보냅니다.
#
# callers: 로컬 개발자가 직접 실행 (원격 시연·심사위원 접속용)
#
# ── 왜 이렇게 하나 ──────────────────────────────────────────────
# demo/bridge.py 는 인증이 없습니다. IP당 30회/분 제한만 있고, 모든
# 엔드포인트가 과금 API(A.X STT·LLM)를 부릅니다. 그래서 CLAUDE.md §2 가
# DEMO_HOST=0.0.0.0 을 금지합니다 — 주소만 알면 아무나 팀 크레딧을 태웁니다.
#
# 터널은 브리지를 127.0.0.1 에 그대로 두고 Cloudflare 가 대신 받게 합니다.
# 여기에 **Cloudflare Access 를 반드시 함께** 걸어서, 허용한 이메일만
# 들어오게 합니다. Access 없이 터널만 뚫으면 0.0.0.0 으로 여는 것과 같습니다.
#
# ── 더 쉬운 길: 대시보드 토큰 방식 ─────────────────────────────
# Zero Trust → Networks → Tunnels → Create 에서 주는 `sudo cloudflared service install <토큰>`
# 한 줄이면 이 스크립트 없이 systemd 서비스로 붙는다. 절차는 docs/DEPLOYMENT.md §10.
# 아래는 CLI 로 직접 만들 때의 길이다.
#
# ── 처음 한 번만 (사람이 직접) ──────────────────────────────────
#   1) cloudflared tunnel login          # 브라우저 로그인. Cloudflare 에 등록된 도메인이 필요합니다.
#   2) cloudflared tunnel create chuckchuck
#   3) cloudflared tunnel route dns chuckchuck demo.<내도메인>
#   4) Zero Trust 대시보드 → Access → Applications → Add an application
#      · Self-hosted, 도메인 demo.<내도메인>
#      · Policy: Allow / Emails / 시연에 들어올 사람 주소만
#      Access 를 안 걸면 이 스크립트가 멈춥니다 (아래 ① 검사).
#
# ── 매번 ────────────────────────────────────────────────────────
#   # 브리지는 Access 필수 모드로, 터널 호스트명을 알려 주고 띄운다 (Host 허용 목록에 들어간다)
#   DEMO_REQUIRE_ACCESS=1 TUNNEL_HOSTNAME=demo.<내도메인> DEMO_PORT=8799 ./demo/run_bridge_midm.sh
#   TUNNEL_HOSTNAME=demo.<내도메인> ./demo/run_tunnel.sh
#
# 시작 전에 두 가지를 실제로 확인하고, 하나라도 아니면 멈춥니다.
#   ① https://$TUNNEL_HOSTNAME 이 Access 로그인(302 → *.cloudflareaccess.com)으로 보내는가.
#      Access 는 Cloudflare 가장자리에서 걸리므로 터널이 아직 안 떠도 확인된다.
#   ② 브리지가 Access 헤더 없는 요청을 403 으로 막는가 (DEMO_REQUIRE_ACCESS=1 · TUNNEL_HOSTNAME 설정).
#      앞단 설정이 하나 빠져도 브리지가 무방비로 열리지 않게 하는 두 번째 자물쇠다.
# ACCESS_CHECK_SKIP 같은 우회 스위치는 두지 않는다 — 우회가 있으면 부스 전날 누군가 켠다.
set -euo pipefail

PORT="${DEMO_PORT:-8799}"
NAME="${TUNNEL_NAME:-chuckchuck}"
HOSTNAME_="${TUNNEL_HOSTNAME:-}"

if [[ -z "$HOSTNAME_" ]]; then
  echo "TUNNEL_HOSTNAME 을 지정하면 시작할 수 있어요. 예: TUNNEL_HOSTNAME=demo.example.com $0" >&2
  echo "임시 주소(trycloudflare.com)는 인증이 없어서 쓰지 않습니다 — 과금 위험이 그대로예요." >&2
  exit 1
fi

if ! curl -sS -o /dev/null --max-time 3 "http://127.0.0.1:${PORT}/"; then
  echo "브리지가 127.0.0.1:${PORT} 에 없어요. 먼저 띄우면 연결할 수 있어요:" >&2
  echo "  DEMO_PORT=${PORT} ./demo/run_bridge_midm.sh" >&2
  exit 1
fi

# ① Access 로그인으로 보내는가 — 302 이고 Location 이 cloudflareaccess.com 이어야 한다.
headers="$(curl -sI --max-time 10 "https://${HOSTNAME_}/" || true)"
status="$(printf '%s\n' "$headers" | awk 'NR==1 {print $2}')"
location="$(printf '%s\n' "$headers" | tr -d '\r' | awk 'tolower($1)=="location:" {print $2; exit}')"
if [[ "$status" != "302" || "$location" != *".cloudflareaccess.com"* ]]; then
  echo "https://${HOSTNAME_} 가 Access 로그인으로 가지 않아요 (응답 ${status:-없음}). 터널을 열지 않습니다." >&2
  echo "  Zero Trust → Access → Applications 에 이 호스트명(오타 포함 확인)으로 앱과 Allow 정책을 걸면 열 수 있어요." >&2
  exit 1
fi

# ② 브리지가 Access 헤더 없는 요청을 막는가. 터널이 붙이는 Host 로 물어본다.
# forbidden_host(Host 허용 목록 밖)가 아니라 access_required 여야 한다 — 전자면 터널 손님이 전부 403 을 본다.
bridge_body="$(curl -s --max-time 5 -H "Host: ${HOSTNAME_}" "http://127.0.0.1:${PORT}/api/health" || true)"
if [[ "$bridge_body" != *'"access_required"'* ]]; then
  echo "브리지가 Access 헤더 없는 요청을 access_required 로 막지 않아요 (${bridge_body:-응답 없음}). 터널을 열지 않습니다." >&2
  echo "  DEMO_REQUIRE_ACCESS=1 TUNNEL_HOSTNAME=${HOSTNAME_} 로 브리지를 다시 띄우면 열 수 있어요." >&2
  exit 1
fi

echo "터널을 엽니다 → https://${HOSTNAME_}  (브리지 127.0.0.1:${PORT}, Access 로그인 확인함)"
exec cloudflared tunnel --url "http://127.0.0.1:${PORT}" run "$NAME"
