# 부스 퍼널 신호 — `POST /api/v1/tour/event` (v1)

결선 부스(11/3~5)에서 QR → `/hi` → 팀 카드 → 「척척발표 살펴보기」 → 투어 → 「내 자료로 직접 해 보기」 가 **어디서 끊기는지** 세기 위한 신호다.
투어는 녹화 응답만 재생해서 API 를 하나도 안 부르고, 화면 파일은 Cloudflare 캐시라 원본 로그에 안 찍힌다 — 그래서 화면이 단계마다 신호를 하나 보낸다.

서버는 **저장하지 않는다.** 접근 로그와 같은 머리의 한 줄만 남기고(`journalctl -u chuckchuck-bridge`), 집계는 [`scripts/booth_funnel.py`](../../scripts/booth_funnel.py) 가 한다.

| 쪽 | 파일 |
|---|---|
| 서버 검사·제한·로그 | [`demo/tour_events.py`](../../demo/tour_events.py) · 배선 `demo/bridge.py` `_handle_tour_event` |
| 화면이 부르는 함수 | [`demo/YEHS_demo/js/funnel.js`](../../demo/YEHS_demo/js/funnel.js) → `window.ccFunnel(step, { deck })` |
| 집계 | [`scripts/booth_funnel.py`](../../scripts/booth_funnel.py) |
| 회귀 | `tests/test_tour_events.py` · `tests/test_booth_funnel.py` · `node tests/js/funnel.smoke.mjs` |

## 요청

```http
POST /api/v1/tour/event
Content-Type: application/json

{"step": "tour_qa", "deck": "battery-fastcharge", "t": 180}
```

| 칸 | 필수 | 모양 | 뜻 |
|---|---|---|---|
| `step` | ✔ | 아래 표의 이름 하나 | 어느 단계에 왔나 |
| `deck` | | `^_?[a-z0-9][a-z0-9-]{0,39}$` (투어 녹화 id = `data/tour/<id>.json`) | 어느 투어 덱인가 |
| `t` | | 0~86400 숫자 (초, 정수로 내림) | 이 탭에서 첫 신호 뒤 지난 시간 |

- 다른 열쇠가 하나라도 있으면 400. 본문 512바이트 넘으면 413. `Content-Type: application/json` 아니면 415.
- 성공 **204**(본문 없음). 틀린 본문 400 `{"error":"bad_event","reason":"bad_step|bad_deck|bad_t|bad_keys|bad_json|bad_body"}`.
- 상한을 넘으면 429 `{"scope":"tour_ip"|"tour_global","retry_after":n}` + `Retry-After`. 화면(js/funnel.js)은 `Retry-After` 가 60초 이하면
  그 뒤에 한 번 더 보내고, 그래도 안 되거나 망이 끊기면 「보냈다」 표시를 지워 다음에 그 단계를 부를 때 다시 보낸다(10-12).
- 공개 — 팀 쿠키 불필요. 과금 관문(점검 깃발·분당 상한·동시 칸·시간당 천장)을 **안 거친다** (외부 호출 0).

## 단계 (`step`) — 화면 차례

| step | 보내는 곳 | 언제 |
|---|---|---|
| `hi` | `/hi` 랜딩 | 첫 화면이 그려졌을 때 |
| `intro` | `/hi` | 척척발표 소개 카드를 봤을 때 |
| `team` | `/hi` | 팀원 카드 **첫 장**이 보였을 때 |
| `team_end` | `/hi` | 팀 소개 목록의 **마지막 줄**이 화면에 보였을 때 (10-12 카드 넘기기 → 한 줄 목록) |
| `explore` | `/hi` | 「척척발표 살펴보기」 를 눌렀을 때 (페이지가 바뀌기 직전 — keepalive 라 간다) |
| `tour_deck` · `tour_present` · `tour_analysis` · `tour_qa` · `tour_report` | `#/tour/*` | 그 화면에 들어왔을 때 (`deck` 를 같이) |
| `try_real` | `#/tour/report` | 「내 자료로 직접 해 보기」 를 눌렀을 때 |
| `inapp_notice` | 어디든 | 인앱 브라우저라 「Safari/Chrome 으로 열기」 안내를 띄웠을 때 |
| `back_team` | `#/tour/report` | 「팀 소개로 돌아가기」 를 눌렀을 때 |

이름을 바꾸거나 더하면 **세 곳을 같이** 고친다: `demo/tour_events.py` `STEPS` → `js/funnel.js` `STEPS` → `scripts/booth_funnel.py` `FUNNEL`/`SIDE`.
`node tests/js/funnel.smoke.mjs` 와 `pytest tests/test_tour_events.py` 가 어긋나면 잡는다.

## 화면에서 부르기

```html
<script src="js/funnel.js?v=fn1"></script>   <!-- intro.html · index.html 둘 다. 브리지가 ?v= 를 내용 해시로 바꿔 1년 캐시 -->
```

```js
window.ccFunnel && window.ccFunnel('hi');
window.ccFunnel && window.ccFunnel('tour_deck', { deck: tour.id });
```

- 같은 탭에서 같은 단계(+덱)는 **한 번만** 보낸다(sessionStorage, 막히면 페이지 안에서 한 번). 다시 그려도 줄이 안 분다.
- 쿠키·식별자·화면 내용은 안 보낸다. 사람 구분은 서버 로그의 방문자 IP 뿐이다(10/7 집계와 같다).
- `fetch(…, {keepalive:true})` — 버튼을 누르고 바로 페이지가 바뀌어도 대개 간다. 실패해도 화면엔 아무 일 없다.

## 서버 로그 한 줄

```
211.234.10.1 - - [03/Nov/2026 14:04:00] tour step=tour_qa deck=battery-fastcharge t=180
```

- 머리(`<방문자 IP> - - [날짜]`)는 접근 로그와 같다. IP 는 방패의 `resolve_client` 로 정한다 — `CF-Connecting-IP` 를 바꿔 보내도 칸이 안 갈린다(10/5 구멍).
- 성공한 신호는 접근 로그 줄(`"POST /api/v1/tour/event" 204`)을 따로 안 남긴다 — 같은 정보가 두 줄이 되지 않게.
- 값은 모두 허용 목록·정규식을 통과한 것만 쓴다 → 줄바꿈·따옴표로 가짜 로그 줄을 만들 수 없다.
- `/hi` 진입은 신호 없이도 접근 로그 `GET /hi …`(302 또는 랜딩 200) 로 센다. 둘 중 하나만 와도 1명.

## 상한

| 칸 | 기본 | 환경변수 |
|---|---|---|
| IP(칸)당 분당 | 600 | `DEMO_TOUR_EVENT_RPM` |
| 서버 전체 분당 — (IP 칸, 단계) 첫 신호 | 3000 | `DEMO_TOUR_EVENT_FIRST_RPM` |
| 서버 전체 분당 — 같은 쌍의 반복 | 3000 | `DEMO_TOUR_EVENT_GLOBAL_RPM` |

- 전체 칸을 둘로 나눈 까닭(10-12 점검): 한 칸(6000)이었을 때 IP 11개가 같은 단계를 560번씩 되풀이하면 3초 만에 전체 상한이 차서
  1분 내내 **진짜 방문객의 신호가 모두 429** 였다. 이제 반복이 반복 칸을 채워도 새 방문객의 첫 신호는 첫 신호 칸으로 들어온다.
  첫 신호 칸이 차면 반복 칸으로 넘어간다. 로그 줄 상한은 두 칸의 합(분당 6000)이다.
- 남은 길: `DEMO_EDGE_SECRET` 이 꺼져 있으면 도메인 경로(via=cf)로 CF-Connecting-IP 를 바꿔 가며 첫 신호만 쏟을 수 있다 —
  **결선 전에 `DEMO_EDGE_SECRET` 을 켠다** (DEPLOY.md).

- 투어 한 바퀴가 신호 11~13개 — 행사장 와이파이(NAT) 하나 뒤의 폰 50대가 같은 1분에 돌아도(550개) IP 칸에 안 걸린다.
  어차피 집계는 IP 단위라, 같은 IP 뒤 방문자는 표에서 1로 센다(IP ≠ 사람).
- 사람으로 셀 수 없는 칸(Cloudflare 서버·설비 IP)과 팀·VM 안 요청은 IP 칸을 건너뛰고 전체 칸만 센다.
- 감옥(Jail)에는 안 넣는다 — 같은 IP 뒤 방문자가 다 같이 막힌다. 홍수는 방패 첫 줄(분당 1200)이 이미 센다.
- 상한을 본문 검사보다 먼저 센다 — 틀린 본문을 쏟아부어 400 접근 로그로 디스크를 채우는 길도 같은 상한에 걸린다.

## 바뀜

- v1 (2026-10-11) — 처음.
