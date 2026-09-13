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
| `DEMO_HOST` | `127.0.0.1` | **실 API 모드에서 `0.0.0.0` 금지.** IP만 알면 아무나 눌러 팀 계정으로 과금된다 |
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

## 6. 정적 프론트 캐시 버전 함정 (`?v=`)

`demo/YEHS_demo/index.html`은 CSS/JS를 `?v=…`로 캐시 버스팅한다. **`css/*.css`나
`js/*.js`를 고치고 `index.html`의 해당 `?v=`를 안 올리면 브라우저가 옛 파일을 그대로
서빙한다** — "고쳤는데 안 바뀐다"의 원인 1순위다. `f11_reveal.html`(분석 연출)은
`index.html`이 아니라 `js/app.js`의 `showF11Reveal()` 안에 별도로 버전이 박혀 있어
**따로** 올려야 한다(2026-08-07에 실제로 이걸 놓쳐 리빌 레이아웃이 안 바뀐 채 하드
리로드까지 했던 사고가 있었다). 확인 명령은 `CLAUDE.md` §2에 있다.

## 7. 쇼케이스 모드 — 지금 배포된 화면은 실분석이 아니다

**`demo/YEHS_demo/js/app.js:849` — `const SHOWCASE_DEMO = true;`가 지금 켜져 있다.**
업로드·리허설 녹음(마이크·슬라이드 넘김)은 실제로 동작하지만, **분석·질문 코칭·
리포트 결과는 고정 쇼케이스 더미(`#/report/sample-investor`)로 바뀐다** — 실 파이프라인
결과가 아니다. `기술개발_구현내용_초안.md` §3.5의 표현을 그대로 쓰면: "실분석 경로와
정직한 빈 상태 처리 코드가 함께 존재하지만, 현재 배포 화면을 실사용 제품으로 전환하려면
쇼케이스 강제를 해제하고 전체 실데이터 흐름을 다시 검증해야 한다."

즉 지금 상태로 시연하면 **연출은 실제 상호작용이고 숫자는 샘플**이다. 실제 파이프라인
결과를 보려면(§8 체크리스트 3~5번) `SHOWCASE_DEMO = false`로 바꾸고 §1의 경로 ③으로
띄운 뒤 실 데이터 흐름을 다시 확인해야 한다.

## 8. 배포 전 체크리스트 (README 발췌 + 배포 관점 보강)

1. **예열**: `curl -sS -X POST http://127.0.0.1:8799/api/v1/habits ...` — 응답
   `"provider":"lora"` 확인 (`heuristic`이면 python을 잘못 띄운 것).
2. **캐시 버전**: `grep -o 'v=q[a-z0-9]*' demo/YEHS_demo/index.html`과
   `grep -n 'f11_reveal.html?embed' demo/YEHS_demo/js/app.js`가 최신 커밋과 맞는지.
3. **쇼케이스 여부**: 실제 분석 결과를 보여줘야 하면 §7의 `SHOWCASE_DEMO` 값을 확인.
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
