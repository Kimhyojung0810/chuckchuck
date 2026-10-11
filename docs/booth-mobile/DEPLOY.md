# 부스 모바일 배포 · 당일 운영 (결선 11/3~5)

`/hi` 랜딩 · `#/tour/*` 투어 · 퍼널 신호를 공개 서비스(chuckchuck-present.com = systemd `chuckchuck-bridge` · 8799 · main)에 올리는 순서.
**명령은 전부 사람이 Claude Code 프롬프트에서 `!` 로 직접 친다** — main 합치기·재시작은 자동 모드가 막는다(10/1 실측).
Claude 세션은 브랜치·검증까지만 하고 여기서 멈춘다.

```
QR(https://chuckchuck-present.com/hi) ─▶ Cloudflare ─▶ Funnel(ts.net) ─▶ 127.0.0.1:8799 브리지(main)
                                            │  정적: 해시 주소 1년 · 투어 JSON·덱 그림 60초(CDN-Cache-Control)
                                            └─ HTML·/hi·신호(POST /api/v1/tour/event)는 원본까지 → journalctl 한 줄 → scripts/booth_funnel.py
```

## 0. 전에 한 번 — Cloudflare 대시보드 (사람 몫)

| 할 것 | 어디서 | 왜 |
|---|---|---|
| **Browser Cache TTL → Respect Existing Headers** | Caching → Configuration | 지금 4시간(`max-age=14400`)으로 덮어쓴다(10/11 실측: `/js/app.js`·`/css/app.css`·덱 그림). 해시 없는 파일을 폰이 4시간 들고 있어서, 배포한 투어 JSON·팀 카드를 팀원 폰이 못 본다. 해시 주소(`?v=h…`)는 원본의 1년 immutable 이 그대로 간다 |
| **Cache Rule `booth-data`** — `URI Path starts with "/data/tour/"` **or** `URI Path equals "/data/team.json"` → Eligible for cache · Edge TTL = **Use cache-control header if present** | Caching → Cache Rules | JSON 은 Cloudflare 기본 저장 확장자가 아니다. 브리지가 이 파일들에 `CDN-Cache-Control: max-age=60, stale-while-revalidate=86400` 을 붙이므로 규칙만 켜면 60초씩 서울에서 내준다. 덱 그림(webp)은 규칙 없이도 이 머리글을 따른다 |
| **HTML 캐시 규칙에 `/hi` 를 넣지 않는다** | (§10-5 의 HTML 규칙을 켰다면) | `/hi` 진입은 원본 접근 로그 `GET /hi` 로 센다. 넣으면 그 줄이 줄고 화면 신호 `step=hi` 만 남는다(둘 다 세므로 숫자는 맞지만 신호가 막힌 브라우저는 빠진다) |
| **Rate limiting `api-burst` 에서 신호 빼기** — 조건을 `starts with "/api/"` **and** `URI Path does not equal "/api/v1/tour/event"` 로 | Security → WAF → Rate limiting rules | 그 규칙은 IP 당 10초 100번이다. 행사장 와이파이 하나 뒤 폰 50대가 투어를 돌면 신호만 10초에 ~90개라 걸릴 수 있다. 신호는 브리지가 IP 분당 600 · 전체 분당 6000 으로 따로 막는다 |
| QR 에 꼬리표를 붙이지 않는다 | — | `?src=booth` 같은 쿼리는 캐시 열쇠를 가른다. 진입은 `/hi` 전용으로 센다 |

비밀 머리글·원본 잠금(§10-6)은 그대로 — 켜져 있으면 신호 IP 도 `via=edge` 로 정확해진다.

## 1. 합치기 전 확인 (통합 worktree)

```bash
! cd /home/yehschuck/project/wt-booth-mobile && git status --short && git log --oneline -5
! cd /home/yehschuck/project/wt-booth-mobile && PATH=/home/yehschuck/project/chuckchuck/.venv/bin:$PATH python3 scripts/chk gate --scope worktree
! cd /home/yehschuck/project/wt-booth-mobile && node tests/js/funnel.smoke.mjs
```

실험 브리지(8800 또는 배정 포트)에 띄워 폰 50대 벤치 — 과금 경로가 0 이 아니면 실패로 끝난다:

```bash
! cd /home/yehschuck/project/wt-booth-mobile && DEMO_PORT=8989 DEMO_WARM_DECK_GROUPS= nohup ./demo/run_bridge_midm.sh > /tmp/b8989.log 2>&1 & echo $!
! cd /home/yehschuck/project/wt-booth-mobile && python3 labs/booth_load/run.py --base http://127.0.0.1:8989 --phones 50 --log /tmp/b8989.log
! cd /home/yehschuck/project/wt-booth-mobile && python3 scripts/booth_funnel.py /tmp/b8989.log      # 벤치 신호가 표로 나오는지
! ss -ltnp | grep ':8989 '            # users:(("python",pid=<PID>…)) — 위에서 찍힌 PID 와 같아야 한다 (run_bridge_midm.sh 가 exec 한다)
! kill <PID>                           # PID 로만 끈다. pkill -f · killall 금지 (10/7 공개 서비스가 7초 끊겼다)
```

## 2. 통합 브랜치에 main 을 합친다

main 이 그새 움직였으면 ff 가 안 된다 → 통합 브랜치에 main 을 먼저 합친다 (10/1·10/5 와 같은 방식).

```bash
! git -C /home/yehschuck/project/chuckchuck fetch -q 2>/dev/null; git -C /home/yehschuck/project/chuckchuck log --oneline -1 main
! cd /home/yehschuck/project/wt-booth-mobile && git merge --no-ff main -m "merge: main 을 web/booth-mobile-1011 로 — 결선 부스 배포 전"
! cd /home/yehschuck/project/wt-booth-mobile && PATH=/home/yehschuck/project/chuckchuck/.venv/bin:$PATH python3 scripts/chk gate --scope worktree
```

## 3. main ff → 재시작

```bash
! git -C /home/yehschuck/project/chuckchuck rev-parse --short main > /tmp/main_before_booth && cat /tmp/main_before_booth   # 되돌릴 자리
! git -C /home/yehschuck/project/chuckchuck merge --ff-only web/booth-mobile-1011
! cd /home/yehschuck/project/chuckchuck && scripts/get_esbuild.sh            # 처음 한 번 (있으면 건너뜀)
! sudo systemctl restart chuckchuck-bridge && sleep 3 && sudo journalctl -u chuckchuck-bridge -n 25 --no-pager
```
부팅 로그에서 `방패:` · `원본 잠금:` 두 줄과 `MOCK_EXTERNAL_APIS=False` 를 본다. 재시작 동안 3초쯤 공개 사이트가 끊긴다 — 부스 시간 밖에 한다.

## 4. Cloudflare 퍼지 → 예열

대시보드 **Caching → Configuration → Purge Cache → Custom Purge** 에 아래를 넣는다(해시 주소는 새 해시라 퍼지할 필요 없다):

```
https://chuckchuck-present.com/
https://chuckchuck-present.com/index.html
https://chuckchuck-present.com/data/team.json
https://chuckchuck-present.com/data/tour/<투어id>.json
```
투어 파일(`demo/YEHS_demo/data/tour/*.json`)마다 한 줄, 팀 사진을 바꿨으면 `assets/team/<id>.webp` 도 한 줄씩. 목록 만들기:
`! cd /home/yehschuck/project/chuckchuck && ls demo/YEHS_demo/data/tour/*.json demo/YEHS_demo/assets/team/* 2>/dev/null | sed 's#demo/YEHS_demo#https://chuckchuck-present.com#'`
화면 구조를 크게 바꾼 배포면 **Purge Everything** 한 번이 낫다(§10-5).

```bash
! cd /home/yehschuck/project/chuckchuck && python3 scripts/warm_edge.py --check
```

## 5. 공개 도메인 확인 체크리스트

VM 에서 머리글 (2~3초 걸린다):

```bash
! for p in /hi /data/team.json /data/tour/<투어id>.json /assets/deck-covers/battery-fastcharge.webp; do echo "== $p"; curl -s -o /dev/null -D - -A 'Mozilla/5.0 (iPhone)' "https://chuckchuck-present.com$p" | grep -iE '^(HTTP|cache-control|cdn-cache-control|cf-cache-status|location)'; done
! curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/json' -d '{"step":"hi"}' https://chuckchuck-present.com/api/v1/tour/event   # 204
! sudo journalctl -u chuckchuck-bridge --since "-2 min" -o cat | grep "tour step=hi"     # 줄 머리가 내 공인 IP 여야 한다 (127.0.0.1 이면 IP 판별이 틀린 것)
```

| 확인 | 기대 |
|---|---|
| `/hi` | 302 → `/index.html#/hi` (랜딩 페이지가 따로 서면 200) · `cf-cache-status: DYNAMIC` · `no-store`/`no-cache` |
| `/data/tour/*.json` · `/data/team.json` | 200 · `cdn-cache-control: max-age=60…` · 두 번째부터 `cf-cache-status: HIT` (규칙 `booth-data` 를 켰을 때) |
| 덱 그림 webp | 두 번째부터 `HIT` · `cache-control` 이 `no-cache` (Browser Cache TTL 을 Respect 로 바꿨을 때) |
| 신호 | 204 · journalctl 에 방문자 IP 로 한 줄 · `/api/v1/ops/shield` 의 `recent_5min.tour_ok` 가 는다 |
| 과금 | 투어를 끝까지 돌린 뒤 `sudo journalctl -u chuckchuck-bridge --since "-10 min" -o cat \| grep -cE '"POST /api/v1/(parse\|transcribe\|questions\|qa/judge\|concepts\|graph)'` 가 **0** |

**폰으로 (인쇄한 QR 을 찍어서)** — 각 폰에서 `/hi` → 팀 카드 끝까지 → 「척척발표 살펴보기」 → 투어 5화면 → 리포트의 두 버튼:

- [ ] 아이폰 카메라 → Safari
- [ ] 안드로이드 카메라(삼성) → Chrome / 삼성 인터넷
- [ ] **카카오톡** QR 스캐너 → 카톡 인앱 (iOS · Android 둘 다) — 투어는 끝까지 돌고, 「내 자료로 직접 해 보기」 에서만 「Safari/Chrome 으로 열기」 안내
- [ ] 네이버 앱 · 인스타그램 인앱 (링크로) — 위와 같다
- [ ] 세로 360px 폰(갤럭시 A 계열)에서 주 버튼이 엄지 자리에 있고 가로 스크롤이 없다
- [ ] 끝나고 `booth_funnel.py --since "<시작 시각>"` 에 내 IP 가 단계마다 1 로 찍힌다

## 6. 부스 당일 — 퍼널 보기

```bash
# 오늘 30분 단위 표 (기본은 VM 안·사설 IP 를 뺀다. 팀 폰은 --exclude <IP> 로 뺀다)
! sudo journalctl -u chuckchuck-bridge --since "2026-11-03 09:00" -o cat | python3 /home/yehschuck/project/chuckchuck/scripts/booth_funnel.py --bucket 30
# 부스 시간만 · 곁가지(소개·팀 끝·인앱 안내·팀으로)까지
! sudo journalctl -u chuckchuck-bridge --since today -o cat | python3 /home/yehschuck/project/chuckchuck/scripts/booth_funnel.py --since 13:00 --until 18:00 --all
# 10/7 처럼 경로별 요청 수·IP 수 (실제 흐름으로 넘어간 뒤 어디까지 갔나)
! sudo journalctl -u chuckchuck-bridge --since today -o cat | python3 /home/yehschuck/project/chuckchuck/scripts/booth_funnel.py --paths --top 40
# 들어오는 신호를 그대로 보기
! sudo journalctl -u chuckchuck-bridge -f -o cat | grep --line-buffered "tour step="
# 최근 5분 사건 수 (tour_ok · tour_429 · flood_429 …)
! curl -s http://127.0.0.1:8799/api/v1/ops/shield | python3 -c 'import json,sys; print(json.load(sys.stdin).get("recent_5min"))'
```

읽는 법: 숫자는 **단계마다 서로 다른 방문자 IP 수**다. IP ≠ 사람 — 폰 IPv6 는 바뀌고(한 사람이 둘로), 행사장 와이파이는 여럿이 한 IP(여럿이 하나로).
비교 기준은 10/7 실측 64 → 덱 선택 14 → 리허설 8 → 분석 3 → 답변 2. 투어 끝(`리포트`)과 `직접 해 보기`·`자료 올림` 사이가 실제 흐름으로 넘어가는 비율이다.

## 7. 문제가 생기면

| 증상 | 할 것 |
|---|---|
| 배포 뒤 화면이 깨졌다 | `! git -C /home/yehschuck/project/chuckchuck reset --hard $(cat /tmp/main_before_booth) && sudo systemctl restart chuckchuck-bridge` (main 을 배포 전 자리로 — 그 사이 main 에 다른 커밋이 없을 때만) → Cloudflare Purge Everything |
| 팀원 폰에 옛 투어·팀 카드가 보인다 | 0절 Browser Cache TTL 확인 → 그 주소 Custom Purge → 폰에서 새 탭 |
| 신호 줄이 너무 많다(봇) | `/api/v1/ops/shield` 에서 IP 확인 → `var/blocklist.txt` 에 한 줄(2초 안에 반영). 전체 상한은 drop-in `DEMO_TOUR_EVENT_GLOBAL_RPM` |
| 표에 /hi 만 있고 다음 단계가 0 | 화면이 `ccFunnel()` 을 안 부르거나 `js/funnel.js` 를 안 실었다 — 폰 브라우저 콘솔 또는 `grep -n ccFunnel demo/YEHS_demo/js/*.js` |
| 공격·폭주 | DEPLOYMENT.md §10-6 「비상 시 순서」 그대로 (Under Attack → `var/lockdown` → 차단 목록). 투어는 과금이 없어 점검 깃발을 켜도 계속 돈다 |

## 8. 실측 (2026-10-11, 실험 브리지 8989 · 실 API 모드 · 키 없음 · 과금 0)

`labs/booth_load/run.py --phones 50` — 폰 50대가 같은 순간에 `/hi` → `index.html` → 해시 자산 39개 → 팀·투어 JSON → 덱 그림 5장 → 신호 11개
(폰 1대당 59요청, 전부 원본까지 = Cloudflare 없는 최악).

| | HTML p95 | 전체 p50 / p95 / p99 | 벽시계 | 오류 | 과금 경로 |
|---|---|---|---|---|---|
| 고치기 전 (HTML 을 요청마다 바꿔 씀) | 3829ms | 80 / 589 / 3686ms | 9.9초 | 0% | 0 |
| 고친 뒤 (`perf(static)` 2초 나눠 쓰기 + single-flight) | 198ms | 57 / 101 / 154ms | 3.5초 | 0% | 0 |
| 같은 IP 50대(행사장 와이파이) · 원본까지 오는 것만(`--edge`) | 202ms | 18 / 156 / 192ms | 0.5초 | 0% (신호 550개 모두 204) | 0 |

- 신호 `POST /api/v1/tour/event` 는 p95 ~50ms, 550개 모두 204.
- 모든 정적 자산을 원본에서 받는 `--same-ip`(Cloudflare 없음) 는 방패 홍수 제한(IP 분당 1200)에 걸린다 — 실제로는 해시 자산을 Cloudflare 가 받아 원본엔 폰 1대당 ~14요청이라 50대여도 700.
- 공개 도메인 실측(10/11): HTML `cf-cache-status: DYNAMIC`(HTML 캐시 규칙 없음 — 그래서 위 HTML 개선이 그대로 효과), 해시 자산 `HIT`, 해시 없는 정적 파일은 Browser Cache TTL 4시간으로 덮인다(0절).
- 헤드리스 Chromium(iPhone 13 · 카카오톡 UA)에서 `ccFunnel()` 이 같은 단계를 두 번 안 보내고, 페이지가 바뀌어도 이어지는 것을 브리지 로그로 확인.

## QR

`~/meetings/2026-10-11_결선_QR/` — `chuckchuck_hi_qr_A4.pdf`(인쇄용) · `.svg` · `_1024.png`. 오류 정정 Q · 여백 4칸 · 로고 없음.
PNG · 인쇄면 · PDF(150/72dpi) 모두 zxing-cpp 로 다시 읽어 `https://chuckchuck-present.com/hi` 확인. 다시 만들기: `scripts/booth_qr.py`.
