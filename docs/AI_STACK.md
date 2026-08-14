# 척척발표 — 활용 AI 모델·API·라이브러리

이 문서는 척척발표가 실제로 호출하는 외부 AI 모델·API와, 핵심 파이프라인(F-01~F-20)이
의존하는 라이브러리를 한곳에 정리한다. 단일 원본은 `.env.example`·`chuckchuck/config.py`·
`chuckchuck/providers/`·`requirements.txt` 이며, 코드와 이 문서가 어긋나면 코드가 맞다.

## 1. AI 모델 · API

### 1-1. 문서 읽기 — Upstage Document Parse (F-01)

| 항목 | 값 |
|---|---|
| 모델 | `document-parse` (`UPSTAGE_DOCPARSE_MODEL`) |
| 엔드포인트 | `POST /v1/document-digitization` (동기), `/v1/document-digitization/async` (비동기, 10p↑) |
| 용도 | 업로드한 발표 자료(PDF/PPT 등)를 슬라이드 단위 텍스트+레이아웃으로 파싱 → `SlideDoc` |
| 코드 | `chuckchuck/f01_parse.py` |
| 비고 | AI Initiative 대상이면 Solar+DP 무료(~2026-03-31). 키: console.upstage.ai |

### 1-2. 추론 LLM (F-06/F-07/F-08/F-09/F-11/F-14/F-19/F-20) — 4개 중 택1

`REASONING_BACKEND` 환경변수로 스위칭한다 (`solar | ax | midm | exaone | mock`). 개념 정리,
개념 그래프, 예상 질문, 답변 판정, 발표-자료 정합, 채점표 채점, 리포트, 전략 제안이 전부
같은 스위치를 공유한다.

| 백엔드 | 모델 | 제공사 | 접속 방식 |
|---|---|---|---|
| `solar` (기본) | Solar Pro 3 (`solar-pro3`) | Upstage | OpenAI 호환, `UPSTAGE_SOLAR_BASE_URL` |
| `ax` | A.X-K1 | SKT (adot.ai) | OpenAI 호환, `AX_BASE_URL`, Bearer 인증 |
| `midm` | Mi:dm 2.0 (`K-intelligence/Midm-2.0-Base-Instruct`) | KT | Friendli dedicated 엔드포인트 또는 로컬 서빙 |
| `exaone` | EXAONE | LG AI연구원 | Friendli dedicated 엔드포인트 |

코드: `chuckchuck/providers/llm_impl.py` (`SolarLLM`/`AxLLM`/`MidmLLM`/`ExaoneLLM`,
공통 부모 `OpenAICompatLLM`), 팩토리 `get_llm()`.

**F-12 청중 수다는 예외적으로 4개를 동시에 쓴다** — 국내 LLM 4개(믿:음/쏠라/엑사원/에이닷)가
각자 성격을 가진 캐릭터로 등장해 서로 다른 관점의 코멘트를 낸다 (`chuckchuck/f12_chatter.py`).

> 2026-08-11: KT 믿:음 Friendli dedicated 엔드포인트가 종료(HTTP 410)됐다. 로컬 GPU에
> 22GB 가중치를 올려 `serve_midm.py`로 대체 서빙 중 (`MIDM_BASE_URL=http://127.0.0.1:8010/v1`).

### 1-3. 받아쓰기 — SKT A.X STT (F-05)

| 항목 | 값 |
|---|---|
| 모델 | `A.X_STT_note_batch` / `A.X_STT_note_streaming` |
| 엔드포인트 | `https://awf-gw.adot.ai` (`/v1/stt/upload-token`, `/v1/stt/upload/{token}`, `/v1/stt/transcript`) |
| 인증 | `X-API-Key` (LLM 은 Bearer, STT 는 헤더가 다름 — 같은 `awf_` 키) |
| 용도 | 발표 녹음 오디오 → 슬라이드별 타임스탬프 자막(`Transcript`) |
| 코드 | `chuckchuck/providers/stt_impl.py` (`AxSTT`) |

### 1-4. 음성 습관 태거 — LoRA on Mi:dm (F-18)

| 항목 | 값 |
|---|---|
| 베이스 모델 | `K-intelligence/Midm-2.0-Base-Instruct` |
| 어댑터 | 자체 학습 LoRA (`CHUCKCHUCK_LORA_PATH`, PEFT) |
| 담당 태그 | `REP`(반복) — `FIL`(간투사)·`PAUSE`는 규칙 기반(heuristic) 보강 |
| 실행 조건 | `HABIT_PROVIDER=lora`, torch+GPU 필요. 기본 `python` 엔 torch가 없어 `heuristic`으로 자동 폴백 |
| 코드 | `chuckchuck/_lora_tagger.py`, 실행 스크립트 `demo/run_bridge_midm.sh` |

## 2. 라이브러리

### 2-1. 백엔드 (Python)

| 라이브러리 | 버전 하한 | 용도 |
|---|---|---|
| `requests` | 2.31.0 | Upstage/A.X/Friendli REST 호출 (코어 `chuckchuck/` 유일 의존성) |
| `fastapi` | 0.110.0 | `server/` HTTP API |
| `uvicorn[standard]` | 0.27.0 | ASGI 서버 |
| `python-multipart` | 0.0.9 | 업로드 라우트(`UploadFile`) |
| `pytest` / `pytest-cov` | 8.0 / 5.0 | 테스트·커버리지 |
| `httpx` | 0.27.0 | `fastapi.testclient` |
| `transformers`, `peft`, `torch` | — (`demo/run_bridge_midm.sh` 전용 conda env) | F-18 LoRA 태거 로드·추론 |

### 2-2. 프론트엔드 (`demo/YEHS_demo`, CDN/로컬 vendor, npm 빌드 없음)

| 라이브러리 | 출처 | 용도 |
|---|---|---|
| Pretendard Variable | jsDelivr CDN | 전 화면 유일 서체 |
| `pdf.js` 3.11.174 | jsDelivr CDN | 업로드 PDF 미리보기 렌더링 |
| `3d-force-graph` 1.80.0 (three.js 내장) | 로컬 `js/vendor/` | 개념 그래프 3D 시각화(`#/graph`) |
| GSAP | 로컬 `js/vendor/` | 리빌·타임라인 모션 |
| Motion (구 Motion One) | 로컬 `js/vendor/` | 분석 타임라인·피드 스프링 등장 모션 |

부스 네트워크를 믿지 않는다는 이유로 three.js/GSAP/Motion 은 CDN이 아니라 로컬 vendor 파일로
번들되어 있다 (`index.html` 주석 참고). Pretendard·pdf.js만 CDN에서 받는다.

## 3. 모듈 ↔ 모델 매핑 요약

| 기능 | 모델/API |
|---|---|
| F-01 자료 읽기 | Upstage Document Parse |
| F-05 받아쓰기 | SKT A.X STT |
| F-06/07/08/09/11/14/19/20 | Solar\|A.X\|Mi:dm\|EXAONE 중 1개 (`REASONING_BACKEND`) |
| F-12 청중 수다 | Solar+A.X+Mi:dm+EXAONE 4개 동시 |
| F-18 음성 습관 | Mi:dm 기반 LoRA 태거(REP) + heuristic(FIL/PAUSE) |

더 자세한 F-01~F-20 계약과 모듈 경계는 [`docs/DEV_POLICY.md`](DEV_POLICY.md) 참고.
