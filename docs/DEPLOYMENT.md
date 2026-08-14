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
(`ssh -L 8799:127.0.0.1:8799 <host>`).

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
- **파일명/내용 해시 캐시**: 같은 자료·같은 녹음의 재호출 비용을 줄인다
  (`_save_slidedoc_cache`/`_load_slidedoc_cache`, `fixtures/raw/*.slidedoc.json`).
  "이건 운영용 영속 저장소를 대체하지 않는다" —
  `기술개발_구현내용_초안.md` §3.4가 이미 이 한계를 명시했다.
- **세션·작업 상태는 전부 인메모리**다. 브리지든 FastAPI든 재시작하면 진행 중이던 세션이
  사라진다 — 데모 중 프로세스를 재시작해야 하면 사용자는 처음부터 다시 시작해야 한다.

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

## 9. 개발 환경 (참고)

로컬 개발은 Claude Code 플러그인 **ECC**를 쓰고(`.claude/settings.json`이 저장소에
커밋돼 있어 클론 후 자동 인식), 공통 규칙은 `.claude/rules/common/`에 저장소 안에 직접
커밋돼 있다(플러그인이 rule 배포를 지원하지 않아서). 이건 실행·배포와는 별개 층이라
자세한 내용은 `README.md` §"개발 환경 (Claude Code · ECC)"를 참고한다.
