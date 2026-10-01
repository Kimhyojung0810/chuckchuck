# 척척발표 — 실행·배포 환경

이 문서는 척척발표를 어디서, 어떻게 띄우는지 정리한다. **클라우드 상시 배포는 없다** —
대회 지급 GPU 서버에서 로컬 프로세스로 띄우고 SSH 터널로 접근하는 것이 전부다. 실행
절차의 단일 원본은 [`README.md`](../README.md)이며, 이 문서는 그 위에 "왜 이 구조인지"와
서버 두 종류·포트·GPU·쇼케이스 모드처럼 여러 파일에 흩어진 배포 관련 사실을 모은다.

## 1. 실행 경로 3단계

같은 코드베이스를 세 가지 신뢰 수준으로 띄울 수 있다. 무엇을 검증하려는지에 따라 고른다.

| 경로 | 명령 | 실제로 붙는 것 |
|---|---|---|
| ① Mock | `MOCK_EXTERNAL_APIS=true python -m demo.bridge` | 없음. `fixtures/sample_slidedoc.json` 등 고정 데이터로 화면 흐름만 확인 |
| ② 실 API (기본 venv) | `python -m demo.bridge` (`.env`에 키) | Upstage/A.X STT/LLM 4종 전부 실연동. **F-18 LoRA는 기본 venv에 torch가 없어 heuristic으로 떨어진다** |
| ③ 실 API + LoRA | `./demo/run_bridge_midm.sh` (conda `midm` env) | ②에 더해 F-18 REP LoRA까지 GPU에서 실행 |

`CLAUDE.md`가 이 프로젝트 자체 규칙으로 못 박은 것: **데모는 항상 ③으로 띄운다.**
mock은 `_handle_parse`가 업로드 파일을 버리고 고정 fixture를 파일명만 바꿔치기해
돌려주는 착시를 만든 적이 있어(2026-08-07), "내 자료로 제대로 도는가"는 mock으로
검증할 수 없다.

## 2. 서버 두 종류 — 실제 데모는 `demo/bridge.py`

이 저장소엔 서버 구현이 **두 개** 있고, 데모에 쓰이는 건 FastAPI 쪽이 아니다.

| | `server/`(FastAPI) | `demo/bridge.py`(실사용) |
|---|---|---|
| 실행 | `python -m server` (`server/__main__.py`) | `python -m demo.bridge` / `run_bridge_midm.sh` |
| 뼈대 | FastAPI + uvicorn, `/docs` 자동 문서 | 표준 라이브러리 `ThreadingHTTPServer` (새 의존성 없음) |
| 작업 처리 | `server/jobs.py` 인메모리 큐 + 워커 스레드 2개, `202 + job_id` 폴링 | 요청 안에서 동기 처리 |
| 지원 범위 | 파싱·STT·개념·그래프·정합·질문까지 | 채점·음성 리포트·전략·가상 청중까지 **더 넓다** |
| 세션·잡 상태 | 인메모리 — **프로세스 재시작 시 소실, 재시도·복구 없음** | `SessionStore`도 프로세스 메모리 — 재시작하면 사라지고 클라이언트가 재등록 |
| 프론트 서빙 | 없음(API 전용) | `demo/YEHS_demo/` 정적 파일 + `/sdk/*` + `/api/v1/*` 전부 이 프로세스가 서빙 |
| 쓰는 곳 | `tests/test_flat_routes.py` (API 계약 테스트) | 실제 데모·시연 |

`server/jobs.py`가 "모듈 순서를 아는 유일한 지점"이라는 원칙(`docs/DEV_POLICY.md` §4-1)은
지키지만, 지금 판단은 데모 브리지 쪽이 기능이 더 넓어 시연은 항상 브리지로 한다.
FastAPI 서버는 `/api/v1/*` 계약이 스펙대로 동작하는지 pytest로 검증하는 용도에 가깝다.

## 3. 포트·호스트

| 변수 | 기본값 | 비고 |
|---|---|---|
| `DEMO_PORT` | 8787(②) / 8799(③, LoRA 포함) | 겹치면 `DEMO_PORT=8801 ./demo/run_bridge_midm.sh`처럼 바꾼다 |
| `DEMO_HOST` | `127.0.0.1` | **실 API 모드에서 루프백이 아니면 브리지가 시작을 거부한다** (2026-09-23 부터, 전에는 경고만). IP만 알면 아무나 눌러 팀 계정으로 과금된다 |
| `DEMO_REQUIRE_ACCESS` | `0` | `1` 이면 `Cf-Access-Jwt-Assertion` 헤더 없는 요청을 전부 403 (정적 파일 포함). 터널로 열 때만 켠다 (§10-2) |
| `TUNNEL_HOSTNAME` · `DEMO_ALLOWED_HOSTS` | 비어 있음 | Host 헤더 허용 목록에 더한다 (기본 `127.0.0.1`·`localhost`·`::1`). 터널 호스트명은 반드시 넣는다 |
| `DEMO_JSON_MAX_MB` | `2` | JSON 본문 상한(MB). 산출물 묶음 경로는 3배, 녹음·업로드는 30MB 원본 기준 |
| `SERVER_PORT`/`SERVER_HOST` | 8000 / `127.0.0.1` | FastAPI(`server/`) 전용, 데모와 별개 |
| 로컬 믿:음 서빙 포트 | 8010 | `serve_midm.py --port 8010`, `MIDM_BASE_URL=http://127.0.0.1:8010/v1`로 연결 |

원격에서 화면을 봐야 하면 `DEMO_HOST`를 열지 않고 **SSH 터널**을 쓴다
(`ssh -L 8799:127.0.0.1:8799 <host>`). 심사위원처럼 SSH 가 없는 사람에게 열려면
§10 의 Cloudflare Tunnel + Access 를 쓴다 — 역시 `DEMO_HOST` 는 그대로다.

## 4. 하드웨어

대회 지급 GPU 서버(A100‑SXM4‑80GB × 2)를 로컬처럼 쓴다. 상시 운영 클러스터가 아니다.

| 프로세스 | GPU 점유 |
|---|---|
| 데모 브리지 + F-18 REP LoRA (`run_bridge_midm.sh`) | ~23.6GB (GPU0 기준) |
| 로컬 믿:음 베이스 서빙(`serve_midm.py`, `REASONING_BACKEND=midm`용) | ~21.5GB |
| AI Hub 파인튜닝 실험(`20_AIHub_data/`) | 유휴 GPU1을 우선 사용 — "GPU0 데모 브리지 충돌 시 시연 리허설 중이면 GPU1만 사용"(`PLAN_2ND_FINETUNING.md`) |

첫 요청은 22GB 베이스 모델 로드로 2~3분 걸린다 — **시연 전 예열이 필수**다(README §STT/§빠른
시작, `CLAUDE.md` §2). 예열 뒤 습관 분석은 ~1.2초.

## 5. 캐시·속도·과금 방어

- **레이트 리밋** (`demo/bridge.py`): 과금이 붙는 경로(`/api/v1/parse`·`concepts`·
  `transcribe`·`graph`·`alignment`·`chatter`·`habits` 등)에 IP당 분당
  `DEMO_RATE_LIMIT_PER_MIN`(기본 30) 상한. 0 이하로 두면 꺼진다(오프라인 시연·자동화용).
  사람이 분당 30턴을 못 넘으므로 정상 사용엔 안 걸린다.
- **세션 보관소** (`demo/session_archive.py`, 2026-09-10): 업로드 한 건이 세션 하나다. 파싱 때
  브리지가 `session_id` 를 발급하고 이후 모든 호출이 그것을 실어 보낸다. 디스크는
  `DEMO_DATA_DIR`(기본 `var/data`) 아래 `sessions/YYYY/MM/DD/<타임스탬프>_<난수>/` 로 남아
  `ls` 만으로 시간순이다. **학습 동의를 켠 세션만** 원본·분석 산출물·QA 턴·피드백을 남기고
  `DEMO_RETENTION_DAYS`(365) 뒤 지운다. 동의 없는 세션은 파싱본·받아쓰기 캐시만
  `DEMO_CACHE_TTL_HOURS`(24) 두고 지운다. 정리는 시작 때 한 번 + 하루 한 번 데몬 스레드
  (`journalctl` 에 `만료 세션 정리: N건` 이 찍힌다). 자세한 규칙은 [PRIVACY.md](PRIVACY.md).
  예전의 `fixtures/raw/{파일명}.*` 는 더 쓰지 않는다 — 파일명으로 남의 자료가 붙고 실제
  발표 자료가 git 에 커밋됐다.
- **F-06·F-07 내용 해시 캐시**: `var/data/stage_cache/` (`DEMO_STAGE_CACHE_TTL_HOURS`, 72).
  파일명이 아니라 내용 해시라 남의 자료가 붙을 길이 없다.
- **인메모리 세션(`SessionStore`)은 그대로 핫패스**다. 질문·판정 근거는 메모리에서 먼저 찾고,
  보관소는 write-behind 다 — 저장 실패가 요청을 죽이지 않는다.
- **저장된 세션 목록**(`/api/v1/cached-takes`, `#/replay`)은 `DEMO_DEV_ROUTES=1` 일 때만 열린다.
  목록은 곧 남의 발표 기록이라 운영 기본은 404 다.
- **발표자료 폴더로 질문 코칭**(`/api/v1/dev/decks`, `#/test/qa`, 주소창 `/test/QA` 도 여기로 온다)도 같은 스위치 뒤다.
  서버의 `ppt/<덱>/` 폴더(PPTX·PDF + 녹음 파일)를 목록으로 보여 주고, 클릭 한 번에 파싱 → 선분석 → (녹음 업로드 경로) → `#/qa` 까지
  업로드 화면과 **같은 함수**로 태운다. 목록은 곧 이 서버의 로컬 파일이고 클릭이 곧 실 API 과금이라 운영 기본은 404 다.
  확인은 `labs/test_qa/run.py` (헤드리스 크롬, 실 과금).

## 6. 정적 프론트 캐시 버전 함정 (`?v=`)

`demo/YEHS_demo/index.html`은 CSS/JS를 `?v=…`로 캐시 버스팅한다. **`css/*.css`나
`js/*.js`를 고치고 `index.html`의 해당 `?v=`를 안 올리면 브라우저가 옛 파일을 그대로
서빙한다** — "고쳤는데 안 바뀐다"의 원인 1순위다. `f11_reveal.html`(분석 연출)은
`index.html`이 아니라 `js/app.js`의 `showF11Reveal()` 안에 별도로 버전이 박혀 있어
**따로** 올려야 한다(2026-08-07에 실제로 이걸 놓쳐 리빌 레이아웃이 안 바뀐 채 하드
리로드까지 했던 사고가 있었다). 확인 명령은 `CLAUDE.md` §2에 있다.

## 7. 쇼케이스 모드 — 2026-09-23 부터 꺼져 있다 (실분석이 기본)

**`demo/YEHS_demo/js/app.js` — `const SHOWCASE_DEMO = false;`** (사용자 지시 "서비스 전체를 실제로 운용하도록").
올린 자료·리허설 녹음이 파싱→개념→그래프→STT→정합→질문→판정→리포트 전부 실 API 를 탄다.
`labs/app_flow/run.py` 가 이 흐름을 실 브리지로 한 번 태우고 단계별 사진·요청 로그를 남기며,
데모 전용 문구(`DEMO_MARKERS`)가 실제 세션 화면에 뜨면 잡아낸다 (2026-09-23 16:05 실측: 0건).

켜져 있던 동안의 뜻: 업로드·녹음은 실제지만 **분석·질문 코칭·리포트는 고정 더미(`#/report/sample-investor`)** 였다.
부스 시연용으로 다시 켤 일이 있으면 이 상수 하나만 `true` 로 바꾸고 `?v=` 를 올린다. 꺼진 상태에서 샘플 데모는
「샘플 데모로 계속하기」(`nf.useSample`)와 `#/report/sample-investor` 로 **사용자가 고를 때만** 열린다.
실제 세션은 질문 생성이 실패하거나 분석이 덜 끝났으면 데모 질문으로 떨어지지 않고 실패 화면(`renderQaUnavailable`)을 보여준다.
시연 모드에서 만든 옛 세션(sessionStorage 의 `showcaseDemo`)은 켜자마자 버린다.

## 8. 배포 전 체크리스트 (README 발췌 + 배포 관점 보강)

1. **예열**: `curl -sS -X POST http://127.0.0.1:8799/api/v1/habits ...` — 응답
   `"provider":"lora"` 확인 (`heuristic`이면 python을 잘못 띄운 것).
2. **캐시 버전**: `grep -o 'v=q[a-z0-9]*' demo/YEHS_demo/index.html`과
   `grep -n 'f11_reveal.html?embed' demo/YEHS_demo/js/app.js`가 최신 커밋과 맞는지.
3. **쇼케이스 여부**: `SHOWCASE_DEMO` 가 `false` 인지 (§7). `true` 면 분석·질문·리포트가 더미다.
4. **`DEMO_HOST`가 `127.0.0.1`인지** — 실 API 키가 걸린 채로 `0.0.0.0`이면 과금 위험.
5. **회귀 스모크**: `python -m pytest tests/ -q`(591 passed·7 skipped 기준),
   프론트 JS를 고쳤으면 `node tests/js/qa_live.smoke.mjs`도.

## 10. 원격 호스팅 — Cloudflare Tunnel + Access (2026-09-10)

GPU 머신이 늘 켜져 있으니 브리지를 여기서 상시로 띄우고, Cloudflare 가 앞에서 받는다.
포트를 열지 않고 `DEMO_HOST=127.0.0.1` 을 지킨 채로 `https://demo.<도메인>` 이 열린다.

```
브라우저 ──https──▶ Cloudflare (Access: 이메일 로그인) ──터널──▶ 127.0.0.1:8799 브리지 (+GPU)
```

**Access 없이 터널만 뚫으면 `0.0.0.0` 으로 여는 것과 같다.** 브리지는 인증이 없고
모든 엔드포인트가 과금 API 를 부른다. `trycloudflare.com` 임시 주소도 같은 이유로
시연 호스팅에는 쓰지 않는다 (`demo/run_tunnel.sh` 가 거부한다).

### 10-1. 브리지를 상시 서비스로

`/etc/systemd/system/chuckchuck-bridge.service` — 재부팅해도 살아난다. 키는 저장소 `.env`
에서 읽고 유닛에는 적지 않는다. LoRA 어댑터가 없는 머신은 `HABIT_PROVIDER=heuristic` 을
**명시**한다 (그냥 두면 조용히 떨어진다).

```bash
sudo systemctl status chuckchuck-bridge          # active · enabled 이어야 한다
sudo journalctl -u chuckchuck-bridge -n 20       # 부팅 로그에 f-06 backend · 키 상태가 찍힌다
sudo systemctl restart chuckchuck-bridge         # 브리지 코드나 .env 를 고쳤으면
```

세션 보관소는 `WorkingDirectory` 아래 `var/data` 가 기본이다 (유닛의 `User` 가 쓸 수 있어야 한다).
저장소 디스크 밖에 두려면 유닛에 `Environment=DEMO_DATA_DIR=/var/lib/chuckchuck` 을 넣고
`sudo install -d -o yehschuck -m 0700 /var/lib/chuckchuck`. 백업 대상에 넣으면 백업도 같이 만료시킬 것 —
안 그러면 「1년 뒤 지워요」 가 거짓이 된다.

### 10-2. 터널 — 대시보드 토큰 방식 (권장, CLI 로그인 불필요)

1. **도메인**이 Cloudflare 에 있어야 한다. 없으면 대시보드 → Domain Registration 에서
   하나 산다 (`.com` 원가 약 $10/년, 사자마자 물린다).
2. Zero Trust 대시보드 → Networks → Tunnels → **Create a tunnel** (Cloudflared) → 이름 `chuckchuck`.
3. 화면이 주는 명령을 **GPU 머신 터미널에서** 그대로 실행한다 (토큰이 들어 있으니 채팅에 붙이지 않는다):
   `sudo cloudflared service install <토큰>` — systemd 서비스로 깔리고 재부팅해도 살아난다.
4. 같은 화면 → Public Hostname → `demo.<도메인>` → Service `HTTP` `127.0.0.1:8799`.
5. Access → Applications → **Add an application** → Self-hosted → 도메인 `demo.<도메인>`
   → Policy `Allow` / Include `Emails` / 시연에 들어올 사람 주소만. 세션 기간은 하루면 충분하다.
6. 확인: 시크릿 창에서 `https://demo.<도메인>` → **로그인 화면이 먼저** 떠야 한다.
   로그인 없이 열리면 Access 가 안 걸린 것 — 즉시 `sudo systemctl stop cloudflared`.
   명령으로는 `curl -sI https://demo.<도메인>` 이 `302` + `location: https://<팀>.cloudflareaccess.com/…` 이어야 한다.
7. **브리지 유닛에 두 줄을 넣는다** (2026-09-23 보안 점검). 안 넣으면 터널 손님이 전부 403 을 본다.
   ```
   Environment=DEMO_REQUIRE_ACCESS=1           # Cf-Access-Jwt-Assertion 헤더 없는 요청은 정적 파일까지 403
   Environment=TUNNEL_HOSTNAME=demo.<도메인>   # Host 허용 목록 (DNS rebinding 방지). 없으면 127.0.0.1·localhost 만 받는다
   ```
   `DEMO_REQUIRE_ACCESS=1` 이면 **로컬에서 `http://127.0.0.1:8799` 로 여는 것도 403** 이다 — 로컬 개발은 이 줄 없이 따로 띄운다.
   확인: `curl -s -H 'Host: demo.<도메인>' http://127.0.0.1:8799/api/health` 가 `access_required` 여야 한다.

CLI 로 직접 만들고 싶으면 `demo/run_tunnel.sh` 머리말의 절차(`cloudflared tunnel login` →
`create` → `route dns`)를 따른다. 결과는 같다.

### 10-3. 터널 뒤에서 달라지는 것

- **요청 제한의 IP**: 터널을 거친 요청은 전부 127.0.0.1 에서 온다. 브리지 `_client_key` 가
  루프백 요청에 한해 `CF-Connecting-IP` 를 읽어 사람마다 따로 센다. 이게 없으면 심사위원
  전원이 30회/분 한 통을 나눠 써서 세 명째부터 429 가 난다.
- **CORS 불필요**: 화면과 API 가 같은 오리진(브리지)이라 `DEMO_ALLOWED_ORIGINS` 도
  `js/config.js` 의 `CHUCKCHUCK_API_BASE` 도 그대로 비워 둔다.
- **첫 요청 지연**: LoRA 가 있는 머신은 예열(CLAUDE.md §2)을 시연 전에 해 둔다.
- **과금**: Access 를 통과한 사람은 누구나 실 API 를 부른다. 허용 이메일을 최소로 두고
  시연이 끝나면 Access 정책을 끄거나 `sudo systemctl stop cloudflared`.

### 10-4. chuckchuck-present.com 현황 (2026-09-30 새벽)

**결정:** Access 로그인 없이 공개한다. 방문자는 자기 자료로만 쓰고, 이미 있는 데이터(세션 목록·ppt/ 덱·
샘플 발표/리포트/받아쓰기)와 베타 화면(#/vision·#/temp·#/test/qa·#/replay)은 `/auth` 에 팀 코드
(`.env` 의 `DEMO_TEAM_CODE`)를 넣은 브라우저에만 연다 — 커밋 261156b, `tests/test_bridge_team_auth.py`.

| 조각 | 상태 |
|---|---|
| 도메인 | Cloudflare 에서 구매, 네임서버 Cloudflare |
| 브리지 서비스 `chuckchuck-bridge` | active · 8799 · `chuckchuck-bridge.service.d/public.conf` = `TUNNEL_HOSTNAME=chuckchuck-present.com` (DEV_ROUTES·REQUIRE_ACCESS 없음) |
| 개발 브리지 | 손으로 8800 · `DEMO_DEV_ROUTES=1` (로그 `var/log/bridge_8800.log`) |
| 터널 `chuckchuck` | 만들어 둠(`~/.cloudflared/config.yml`, `/etc/cloudflared/config.yml`), DNS CNAME 연결됨. **서비스는 disabled** |
| **Tailscale Funnel** (08:16 켬) | **공개 중** — `https://chuckchuck-present.tail79d9bc.ts.net` → 127.0.0.1:8799. 공개 DNS 는 켜고 7분 뒤(08:23)에 올라왔다. VM 은 UDP 가 막혀 DERP(홍콩) 경유, 응답 ~0.9초 |
| 브리지 Host 허용 | `public.conf` 에 `DEMO_ALLOWED_HOSTS=chuckchuck-present.tail79d9bc.ts.net` 추가 |
| `chuckchuck-present.com` | **동작** — Redirect Rule `to-funnel`(All incoming requests · Dynamic `concat("https://chuckchuck-present.tail79d9bc.ts.net", http.request.uri.path)` · 302 · 쿼리 유지). 규칙이 빠지면 멈춘 터널로 가서 530/1033 |

**막힌 곳 — 이 VM 은 바깥으로 TCP 80·443 만 나간다.** 터널은 `region1/2.v2.argotunnel.com:7844`
(TCP·UDP)가 필수이고 443 으로 대신할 수 없다 (Cloudflare 문서 「Tunnel with firewall」). 서비스를
켜면 precheck 가 `QUIC connection failed` · `HTTP/2 connection is blocked` 로 끝나 시작 시간 초과가 난다.
사설 IP(10.26.0.2) NAT 뒤라 들어오는 연결도 없다.

여는 길 (고르는 건 사람 몫):

1. **네트워크 관리자에게 7844 아웃바운드를 연다** — 가장 깔끔하다. 열리면 `sudo systemctl enable --now cloudflared`
   하나로 끝난다. 확인: `timeout 5 bash -c '</dev/tcp/region1.v2.argotunnel.com/7844' && echo open`
2. **Tailscale Funnel (무료, 443 만 씀)** — tailscale 1.102.4 는 설치돼 있다. `sudo tailscale up --hostname=chuckchuck-present`
   → 로그인 → 관리 콘솔에서 HTTPS·Funnel 켜기 → `sudo tailscale funnel --bg 8799`.
   브리지 Host 허용 목록에 ts.net 이름을 더한다 (`public.conf` 에 `Environment=DEMO_ALLOWED_HOSTS=chuckchuck-present.<tailnet>.ts.net`).
   `chuckchuck-present.com` 은 Cloudflare Redirect Rule 로 그 주소에 넘긴다 — 주소창은 ts.net 이 된다
   (무료 요금제는 Origin Rules 의 Host 헤더 덮어쓰기가 Enterprise 전용이라 프록시로 감출 수 없다).
3. ngrok 유료(커스텀 도메인) — 443 으로 나가고 주소창이 우리 도메인으로 남는다. 월 과금.

### 10-5. 공개 사이트 속도 (2026-10-01)

**왜 느린가 — 길이 멀고, 예전엔 매번 전부 새로 받았다.** 이 VM 은 삼성SDS 망 뒤라 바깥으로 UDP 는 53(DNS)만,
TCP 는 80·443 만 나간다(STUN·7844·22 막힘 — 망 바깥 방화벽이라 VMware 설정으로는 안 풀린다). Tailscale 이 직접
연결을 못 맺어 모든 요청이 **Cloudflare(인천) → Funnel 입구(도쿄) → DERP 중계(홍콩, TCP) → VM** 을 탄다.
Tailscale 은 한국에 DERP 가 없다. 실측:

| 구간 | 값 |
|---|---|
| 브리지 직접 | 1ms |
| 새 연결 하나 (TLS 가 도쿄·홍콩을 거쳐 VM 까지 여러 번 오간다) | ~1초 |
| 이어 쓰는 연결의 요청 하나 | 0.17~0.26초 |
| 내려받기 | ~330KB/s |

예전엔 모든 응답이 `no-store` 라 첫 화면 파일 36개(1.5MB)를 방문마다 이 길로 받았고 Cloudflare 도 저장하지 못했다
(도메인 기준 첫 방문 7.0초 · 재방문 3.8초, labs/load_perf).

**고친 것** (`demo/static_assets.py`, `js/lazy.js`)
- 브리지가 HTML·ES 모듈의 `?v=` 를 **내용 해시**로 바꿔 내고, 해시가 맞는 요청만 1년 `immutable` 로 캐시한다.
  나머지 정적 파일은 `no-cache`+ETag(304), API 는 그대로 `no-store`. 글자 파일은 gzip.
  → 파일을 고쳐도 해시가 바뀌므로 옛 판이 남지 않는다 (손으로 올리는 `?v=` 는 브리지 밖 호스팅용으로 남긴다).
- 베타 화면(통화·비전·부스)·랜딩은 들어갈 때, 모션·pdf.js 는 첫 화면 뒤 한가할 때 받는다.
- HTML 에 `CDN-Cache-Control: max-age=60, stale-while-revalidate=86400` — 아래 캐시 규칙을 켜야 쓰인다.

**배포 순서** (main 작업 폴더에서)
```bash
scripts/get_esbuild.sh                         # 처음 한 번 — tools/bin/esbuild (없으면 줄이지 않고 보낸다)
sudo systemctl restart chuckchuck-bridge
python3 scripts/warm_edge.py --check           # Cloudflare 서울 캐시를 채우고, 두 번째에 HIT 인지 본다
```
공개 서비스는 `TUNNEL_HOSTNAME` 이 있어서 JS·CSS 주석·공백 걷기가 켜진다 (`DEMO_MINIFY=0` 이면 끈다).
`warm_edge.py --check` 가 「HIT 이 하나도 없다」 면 도메인이 Cloudflare 캐시를 거치지 않는 구성(Worker 등)이다.

**Cloudflare 에서 할 것 (대시보드, 사람 몫)** — 도메인이 Cloudflare 를 거쳐 오고 있을 때만 해당한다.
1. 정적 파일(js·css·png·ico)은 **따로 할 것 없다.** Cloudflare 는 이 확장자를 기본으로 저장하고 원본의 `immutable` 을 따른다.
   배포 뒤 `curl -sI 'https://chuckchuck-present.com/js/app.js?v=<해시>' | grep cf-cache-status` 가 두 번째부터 `HIT` 면 된다
   (해시는 `curl -s https://chuckchuck-present.com/ | grep -o 'app.js?v=[^"]*'`).
2. (선택) **HTML 도 인천에서 내주기** — Caching → Cache Rules → 새 규칙:
   조건 `URI Path equals "/"` 또는 `URI Path equals "/index.html"` → **Eligible for cache**,
   Edge TTL = **Use cache-control header if present**(브리지의 `CDN-Cache-Control` 을 따른다).
   → 첫 방문에서 VM 왕복이 빠진다. 대신 배포 뒤 첫 요청은 옛 HTML 을 받는다(뒤에서 새로 받는다) —
   배포 순서의 `warm_edge.py` 가 HTML 을 두 번 받아 그 한 번을 대신 치른다. 캐시에서 옛 파일이 밀려난 드문 경우
   옛 HTML 에 새 JS 가 붙을 수 있으니, 화면 구조를 크게 바꾼 배포는 대시보드에서 Purge Everything 을 한 번 누른다.
   `/auth`·`/api/*` 는 조건에 넣지 않는다 (그쪽은 `no-store` 라 넣어도 저장되지 않지만 규칙을 좁게 둔다).

**남은 한계** — API 요청(업로드·받아쓰기·질문 코칭)은 여전히 요청마다 0.2초 안팎을 이 길로 탄다. 없애려면
공인 IP 가 있는 국내 서버(NCP·AWS 서울·가비아 g클라우드·Oracle 무료 등)로 브리지를 옮겨야 한다.
Tailscale 정책 파일에서 홍콩 DERP 를 빼 도쿄로 붙이는 건 왕복 ~40ms 차이라 들일 품에 비해 작다.

**재는 법**: `.venv/bin/python labs/load_perf/run.py --base https://chuckchuck-present.com --runs 3`
(로컬 비교는 `--base http://127.0.0.1:8800 --latency 200`). 이 VM 에서 자기 공개 도메인으로 가는 값은 흔들리니
여러 번 재서 중앙값을 본다.

## 9. 개발 환경 (참고)

로컬 개발은 Claude Code 플러그인 **ECC**를 쓰고(`.claude/settings.json`이 저장소에
커밋돼 있어 클론 후 자동 인식), 공통 규칙은 `.claude/rules/common/`에 저장소 안에 직접
커밋돼 있다(플러그인이 rule 배포를 지원하지 않아서). 이건 실행·배포와는 별개 층이라
자세한 내용은 `README.md` §"개발 환경 (Claude Code · ECC)"를 참고한다.


## STT — ffmpeg 은 필수다 (2026-09-13)

A.X STT 게이트웨이 앞의 WAF 가 **10 MiB 미만** 업로드를 검사하다 막을 수 있다 (`chuckchuck/providers/stt_impl.py` 머리 주석의 8/7 실측).
우회는 업로드 직전에 PCM WAV 로 다시 뽑아 본문을 상한 위로 올리는 것이고, **ffmpeg 이 없으면 우회가 조용히 꺼진다.**
발표 리허설 녹음(수 분, 수 MB)보다 **질문 코칭의 답변 녹음(10초 안팎, 수백 KB)** 이 정확히 이 구간이다.

```bash
sudo apt-get install -y ffmpeg
which ffmpeg && ffmpeg -version | head -1      # 브리지 시작 로그에 "⚠ ffmpeg 이 없어요" 가 안 떠야 한다
```

부스 데모 머신에서 시연 전 확인 목록에 넣는다. 벤더(SKT)에 업로드 엔드포인트의 본문 검사 제외를 요청해 두었고,
풀리면 `CHUCKCHUCK_STT_WAF_WORKAROUND=0` 으로 이 층을 끈다.
