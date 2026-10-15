# 모델 장부 — 제품 안의 AI 모델 전부, 지금 상태와 마지막 측정

**계속 파악해 두는 문서다** (2026-10-16 사용자: 「질문은 Solar 혼자 하지 말고 나눠 맡기기 — 계속 파악해 두고」).
모델을 바꾸거나 다시 쟀으면 이 표를 고치고, 맨 아래 「실행 기록」에 줄이 붙는다.

- 다시 재기 (한 줄): `etc/scripts/model_bench.sh` — 점검(모델마다 작은 JSON 호출) + Q&A 모델 벤치 → 아래 실행 기록에 줄 추가.
  점검만: `etc/scripts/model_bench.sh --health` (몇 초).
- 상태: **live** = 오늘 점검에서 답함 · **broken** = 엔드포인트가 막힘(원인 적음) · **absent** = 코드는 있으나 이 서버/서비스에서 안 씀.
- 대회 규칙: 모든 AI 는 국내 모델(Upstage Solar · SKT A.X · KT Mi:dm · LG EXAONE). 브라우저 MediaPipe 는 화면 연출·실험실용이다 (아래 표 참고).

## 1. 모델 표

| 모델 | id / 버전 | 어디에 쓰나 | 상태 (점검일) | 마지막 측정 (날짜 · 커밋) | 다시 재는 명령 |
|---|---|---|---|---|---|
| Upstage **Solar** | `solar-pro3` (응답 id `solar-pro3-260323`) | 주 추론 `REASONING_BACKEND=solar`: F-06 개념 · F-07 그래프 · F-26 주장 · F-11 대조 · **F-08 1차 심사(triage)·논문 주장 대조** · **F-08 문장의 예비(EXAONE 마감·실패 때)** · **F-09 판정(온도 0)**·코칭 · F-24 문헌 · F-19 리포트 · F-20 전략 · 삐약이(순서) | live 0.37s (10-16) | Q&A 아래 §2 (10-16) · 그래프 재현성 docs/review/2026-10-02 (251ba8f) · GRAPH_BENCH_LEDGER | `etc/scripts/model_bench.sh` · `etc/scripts/graph_bench.sh` |
| SKT **A.X-K2** | `A.X-K2` (K1 은 10-10 종료) | 예비 `REASONING_FALLBACK=ax`(Solar 가 넘어지면 한 번 — Q&A 문장 라우팅의 예비 체인에도 들어 있다) · 삐약이(들은 말) | live 0.23s (10-16) | §2 (10-16) | `etc/scripts/model_bench.sh` |
| LG **EXAONE** | Friendli dedicated (`EXAONE_ENDPOINT_ID`), **사고 끔**(`chat_template_kwargs.enable_thinking=false`, 7b8ecfc) | **Q&A 질문 문장(phrase) 주 모델** `QA_PHRASE_MODEL=exaone`(기본, §3) · 삐약이(칭찬) | live 0.14s (10-16, 사고 끔) | §2 (10-16) | `etc/scripts/model_bench.sh` |
| KT **Mi:dm** (API) | `midm-pro-fp8-kaic` @ midm.kt.com | 삐약이(빠뜨린 말) | **broken — 401 `4203` 인증 안 됨** (10-16). 팀이 새 키를 받아야 한다 | 09-16 미측정(401) | `etc/scripts/model_bench.sh --health` |
| KT **Mi:dm 2.0 + LoRA** (로컬) | 베이스 `K-intelligence/Midm-2.0-Base-Instruct` + 어댑터 `CHUCKCHUCK_LORA_PATH` (태그 REP) | F-18 말버릇(되풀이) 태거 `HABIT_PROVIDER=lora` | 개발 브리지(run_bridge_midm.sh)에서 live · **공개 서비스(8799 systemd)는 `HABIT_PROVIDER=heuristic` — 서비스에선 absent** | REP F1 0.01→0.69 (AI Hub 공적말하기 640건, DATA_PIPELINE §3 — /hi 랜딩 b44e8b2) | `curl …/api/v1/habits` 예열(CLAUDE.md §2) · 재학습은 `wt-habits-lora` |
| F-11 정합 LoRA (새) | 작업 중 (`wt-align-lora`) | F-11 발화↔자료 대조 | absent (10-16, 브랜치에 커밋 없음) | — | (그 작업 트리에서 정함) |
| Upstage **Document Parse** | `document-parse` (`UPSTAGE_DOCPARSE_MODEL`) | F-01 자료 파싱 (PPTX·PDF → SlideDoc) | live (10-16 서비스 사용 중, 이 점검은 과금이라 안 부름) | — | 업로드 한 번 (`#/test/qa` DEV_ROUTES) |
| Upstage **embedding** | `embedding-passage` (`UPSTAGE_EMBED_MODEL`) | F-07 같은 개념 묶기 후보 (`_typed_graph.call_same`) | live 추정 (점검 대상 아님) | — | `etc/scripts/graph_bench.sh` |
| SKT **A.X STT** (배치) | `A.X_STT_note_batch` | F-05 받아쓰기 `STT_PROVIDER=skt-ax` | live (서비스 사용 중) | — | `cd main && python -m pipeline.probe_ax_stt` |
| SKT **A.X STT** (실시간) | `A.X_STT_note_streaming` | 실시간 받아쓰기 — `wt-ax-rt` 작업 중 (+ 국내 AI 호출 로그 5b58abd) | 작업 중 | — | (그 작업 트리) |
| MediaPipe Tasks Vision (Google, 브라우저) | 1.0.1 · face/pose/hand landmarker | 평가 실험실 `#/lab/eval` · 부스 스캔 연출 | 브라우저 쪽 · LLM 아님 | — | `etc/scripts/get_mediapipe.sh` |

로컬 파인튜닝 후보(제품 밖): `/data/models` 의 A.X Light · kanana · Midm · EXAONE 32B · Solar Open 100B (10-12).

## 2. Q&A 질문(F-08) — 모델 나눠 맡기기 벤치

**2026-10-16 · 측정 코드 1503ab2(1실행) / 1088dbd(2실행, node_id 라벨 되돌리기 포함) · `etc/bench/model_bench.py qa`**

- 입력: 고정 번들 5개 — 부스 덱 A-1(배터리) · B-1(미세플라스틱) · C-1(배달앱 별점) + 혈당(held-out 합성) + 수면(live_qa_run 픽스처).
  앞 단계(F-06·F-07·F-26·F-11)는 Solar 로 한 번 만들어 얼렸다 (`build_deck_bundle.py`, 번들은 `/data/models/_runs/qa-route/bundles`, git 밖).
- 트랙 10 (질문 7개). 조합 = **1차 심사(triage)/질문 문장(phrase)**. **판정(F-09)·rubric 심사관은 Solar 로 고정** — 자기 질문을 자기가 채점하지 않게.
- n = 번들×회. solar/solar · solar/exaone · exaone/exaone 은 두 실행을 합쳐 20 (질문 140), 나머지는 10 (질문 70).
- 지연은 호출 하나하나의 시간(429 로 기다린 시간 제외). F-08 = 1차 심사 + 문장(+재시도) 호출 합.

| 조합 triage/phrase | n | 특이도 | 인용률 | rubric(1~5) | 깊이 | 환각 | 템플릿 질문 | 함정 동의→wrong · 정정→통과 | 골자→통과 | JSON 첫응답 실패 | 되풀이 고리(4096토큰) | 문장 p50/p95 (초) | F-08 p50/p95 (초) | 토큰/F-08 | 나란히 비교 vs solar/solar (승·패·무) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **solar/solar** (예전 기본) | 20 | 1.27 | 0.69 | 4.88 | 4.53 | 0 | 5/140 | 12/12 · 12/12 | 61/69 | 0/40 | 0 | 7.3 / 9.5 | 11.6 / 14.2 | 10.7k | — |
| ax/ax | 10 | 1.13 | 0.67 | 4.86 | 4.48 | 0 | 3/70 | 6/6 · 6/6 | 32/35 | 0/20 | 0 | 13.0 / 19.6 | 19.9 / 29.8 | 10.7k | 2 · 1 · 7 |
| exaone/exaone | 20 | **1.71** | 0.63 | 4.91 | **4.70** | 0 | 7/140 | 12/12 · 12/12 | 64/66 | 0/43 | 0 | 10.2 / 20.0 | 18.7 / 28.1 | 11.5k | 8 · 4 · 8 |
| solar/ax | 10 | 1.49 | 0.66 | 4.88 | 4.46 | 0 | 4/70 | 6/6 · 6/6 | 29/32 | 0/20 | 0 | 13.3 / 17.2 | 16.9 / 23.6 | 10.6k | 2 · 1 · 7 |
| **solar/exaone** (새 기본) | 20 | **1.54** | **0.69** | **4.92** | 4.57 | 0 | 9/140 | 12/12 · 12/12 | 61/69 | 1/43 | **5/43** | 11.2 / 45.3 | 16.5 / 51.8 | 12.5k | **8 · 2 · 10** |

읽는 법:
- **특이도**(질문 속 이 자료 고유 낱말 수)는 EXAONE 문장이 가장 높다 (1.27 → 1.54 · 1.71). 표준오차 ±0.15 안팎이라 두 실행 모두 같은 방향이었다.
- **인용률**(모범답 낱말이 자료·발화에 있는 비율)은 solar/exaone 이 Solar 와 같고(0.69), EXAONE 이 1차 심사까지 하면 0.63 으로 내려간다 → 1차 심사는 Solar.
- **rubric** 은 전부 4.86~4.92 — 천장이라 못 가른다. 그래서 **나란히 비교**(`qa_pairwise.py`: 같은 번들·회차 묶음 둘을 자리 바꿔 두 번, 둘 다 같은 쪽이면 승)를 더했다.
  심사관이 Solar 인데도 solar/exaone 이 8승 2패 10무. 표본이 작아(n=20) 부호 검정 p≈0.11 — **방향은 분명, 크기는 작다.**
- 환각 0 · 함정 판정 12/12 · 반말 0 은 모든 조합이 같다 — 코드 가드(근거·함정 전제·말투)가 모델과 무관하게 지킨다.
- **A.X-K2 는 질이 Solar 와 같고 1.8배 느리다** → Q&A 에는 안 쓴다 (예비 체인에만).
- **EXAONE 의 대가**: 문장 호출 p50 +4초, 그리고 가끔(solar/exaone 5/43) 같은 구절을 되풀이하다 4096 토큰(~40~50초)까지 간다.
  repetition_penalty 1.05·1.1 은 답이 비정상으로 짧아지고(8~205토큰, 정상 ~850), presence_penalty 0.5 는 고리 3/5 를 냈다 (10-16 같은 프롬프트 5회씩) → 파라미터 대신 **마감 20초 → Solar 가 받는다**.
- 나란히 비교 원문·표: `/data/models/_runs/qa-route/bench/<실행>/pairwise.json` · `table.md` · `aggregate.json`.

## 3. 지금 라우팅 (일마다 맡은 모델)

`main/pipeline/providers/llm_route.py` — F-08 이 llm 을 명시받지 않은 기본 경로(서비스 브리지)에서만 탄다.

| 일 | 환경변수 | 기본 | 마감 | 넘어지면 |
|---|---|---|---|---|
| 1차 심사 (어느 개념·세기·함정·각도) | `QA_TRIAGE_MODEL` | 서비스 기본 체인 (solar → ax) | — | (FallbackLLM: ax) |
| **질문 문장·모범답·힌트·문헌 인용 고쳐 쓰기** | `QA_PHRASE_MODEL` | **exaone** | `QA_PHRASE_DEADLINE_SEC=20` | 마감 초과·오류·빈 답·JSON 아님 → solar(→ax) 한 번. 답한 모델은 `QuestionDoc.model` 에 남는다 |
| 논문 주장 대조 (temperature 0) | `QA_CHECK_MODEL` | 서비스 기본 체인 | — | — |
| F-09 판정·코칭 | (라우팅 없음) | `REASONING_BACKEND` (solar, 온도 0 그대로) | — | ax |

- 끄기: `QA_PHRASE_MODEL=default`(또는 빈 값) → 예전처럼 전부 Solar.
- EXAONE 은 **사고(thinking) 끔**이 기본이다 (`EXAONE_THINKING=1` 로 켬). 켜면 영어 사고 과정 때문에 느리고 JSON 이 깨진다 (09-16 「55초 · 첫 응답 3/3 JSON 실패」의 원인).
- 사용자 흐름의 지연: 질문은 분석이 끝나는 순간 미리 만든다(`app.js prefetchLiveQuestions` — 리빌을 보는 동안). 그래서 리허설 흐름에선 +4초가 안 보인다.
  부스 사진 경로(`booth.js`)는 바로 기다리므로 보통 +4초, 고리면 마감 20초 + Solar ~8초. 프론트 제한(60초) 안이다.
- Friendli dedicated 엔드포인트를 내리면 EXAONE 이 바로 오류 → Solar 가 받는다 (지연 거의 없음). 응답 없이 매달리면 매번 20초를 잃는다 — 그땐 `QA_PHRASE_MODEL=default`.
- 캐시: 브리지 질문 키에 라우팅 지문이 들어간다 (`bridge._qa_llm_identity`) — 모델을 바꿔 다시 띄우면 새로 만든다.

## 실행 기록

| 시각 | 무엇 | 결과 | HEAD |
|---|---|---|---|
<!-- model_bench rows: 이 줄 아래에 model_bench.py --ledger 가 붙인다 -->
| 2026-10-16 00:40 | health | solar live 0.37s · ax live 0.23s · midm broken 0.04s (401) · exaone live 0.14s (사고 끔; 사고 켬이면 2.8s·297토큰·영어 답) | 7b8ecfc |
| 2026-10-16 00:43 | qa 5조합 × 번들 5 × 2회 (1실행) | solar/solar 특이도 1.2 · ax/ax 1.13 · exaone/exaone 1.8 · solar/ax 1.49 · solar/exaone 1.81 · 환각 0 전부 · 429 로 동시 5→2 로 다시 | 1503ab2 |
| 2026-10-16 01:09 | qa 3조합 × 번들 5 × 2회 (2실행, 라벨 id 가드) | solar/solar 1.34 · solar/exaone 1.26 · exaone/exaone 1.63 (특이도) — 합친 값은 §2 | 1088dbd |
| 2026-10-16 01:40 | 나란히 비교 vs solar/solar (두 실행 합) | solar/exaone 8승 2패 10무 · exaone/exaone 8·4·8 · ax/ax 2·1·7 · solar/ax 2·1·7 → **QA_PHRASE_MODEL=exaone 기본** | 1088dbd |
