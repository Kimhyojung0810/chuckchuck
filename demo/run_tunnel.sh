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
#      Access 를 안 걸면 이 스크립트가 경고하고 멈춥니다.
#
# ── 매번 ────────────────────────────────────────────────────────
#   TUNNEL_HOSTNAME=demo.<내도메인> ./demo/run_tunnel.sh
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

echo "터널을 엽니다 → https://${HOSTNAME_}  (브리지 127.0.0.1:${PORT})"
echo "Access 정책이 걸려 있는지 확인하세요. 로그인 화면 없이 열리면 즉시 끄세요."
exec cloudflared tunnel --url "http://127.0.0.1:${PORT}" run "$NAME"
