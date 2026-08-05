# TDD 증거 · 질문 코칭이 조용히 데모 질문으로 되돌아가던 문제

- 날짜: 2026-08-02
- 브랜치: `feat/qalogic`
- 출처 계획: 없음 (`*.plan.md` 미사용). 아래 사용자 여정은 이번 조사 중에 도출했다.

## 증상

"내 발표로 질문 코칭"을 시작하면 실제 생성된 질문 대신 IMU2CLIP 데모 질문이 나온다.
`qa.live.questions` 가 비어 있었고, 서버 로그에는 `/api/v1/questions` 호출 자체가 없었다.

## 사용자 여정

1. 발표자로서, 내 자료와 녹음으로 만든 **실제** 예상 질문을 받고 싶다 — 데모 질문은 연습이 되지 않는다.
2. 발표자로서, 녹음 없이 **자료만** 올려도 예상 질문을 받고 싶다 — 아직 리허설 전일 수 있다.
3. 발표자로서, 실제 질문을 만들지 **못했다면 그 사실을 알고 싶다** — 데모 질문이 내 질문처럼 보이면 안 된다.

## 근본 원인 (2개, 서로 독립)

### 원인 A — `nf.pipelineOut` 이 저장되지 않았다 (클라이언트)

`demo/YEHS_demo/js/app.js` 의 파이프라인 완료 핸들러가 `nf.pipelineOut = out` 으로
`graph`·`alignment` 를 메모리에만 넣고 `saveSession('new-flow', nf)` 를 호출하지 않았다.
`new-flow` 의 마지막 저장은 그보다 훨씬 앞(파이프라인 시작 전)이었다.

결과: 새로고침·탭 복원·페이지 이탈 후 복귀 중 무엇이든 한 번이면 `pipelineOut` 이 사라진다.
그러면 `wireQaStart` 의 가드(`!out.graph || !out.alignment`)가 걸려 **조용히 return** 하고,
화면은 데모 질문을 렌더한다. 서버는 호출조차 되지 않는다 — 로그에 흔적이 없던 이유다.

> 처음 세운 "sessionStorage 용량 초과" 가설은 **반증**했다. 실제 `pipelineOut` 직렬화 크기는
> 98,449자로 약 5MB 한도에 한참 못 미친다. 저장이 실패한 게 아니라 저장을 **시도하지 않았다**.

### 원인 B — 플랫 `/api/v1/questions` 가 `alignment` 를 강제했다 (서버)

`server/app.py` 의 `flat_questions` 가 `graph` 와 `alignment` 를 **둘 다** 요구해 400 을 냈다.
그러나 같은 기능의 세션 라우트는 개념 그래프만 요구하고, `triage_questions` 의 계약도 명시한다 —
"alignment·flow·transcript 없이 그래프만으로도 동작한다".

결과: 녹음 없이 자료만 올린 사용자(여정 2)는 항상 400 을 받고 데모 질문으로 떨어졌다.

## 과제별 보고

| # | 실행 요약 | 검증 명령 | 결과 |
|---|-----------|-----------|------|
| 1 | 서버가 실제 데이터로 질문을 만드는지 먼저 확인 (차단 질문) | 실서버 8002 에 fixture 의 실제 graph+alignment POST | **질문 7개 / 13.4초 / HTTP 200** — 서버 정상, 원인은 클라이언트 |
| 2 | 용량 초과 가설 검증 | `pipelineOut` JSON 크기 측정 | 98,449자 < 5MB — **가설 반증** |
| 3 | 플랫 라우트 회귀 테스트 추가 | `pytest tests/test_flat_routes.py` | RED 1건 / GREEN 4건 |
| 4 | 원인 B 수정 | 같은 위 명령 재실행 | **5 passed** |
| 5 | 전체 회귀 확인 | `python -m pytest -q` | **232 passed, 4 skipped** (수정 전 227 passed) |

### RED 증거

```
tests/test_flat_routes.py::test_questions_returns_questions_for_real_graph PASSED
tests/test_flat_routes.py::test_questions_works_without_alignment FAILED
tests/test_flat_routes.py::test_questions_rejects_missing_graph PASSED
tests/test_flat_routes.py::test_flow_requires_graph_and_alignment PASSED
tests/test_flat_routes.py::test_judge_falls_back_to_body_question_without_session PASSED
==================== 1 failed, 4 passed in 0.43s ====================
```

### GREEN 증거

```
tests/test_flat_routes.py::test_questions_works_without_alignment PASSED
========================= 5 passed in 0.40s =========================
```

## 테스트 명세

| # | 무엇을 보장하는가 | 테스트 | 종류 | 결과 |
|---|-------------------|--------|------|------|
| 1 | 실제 그래프로 질문이 비지 않게 생성되고, 프론트가 쓰는 키(id·node_id·label·question·severity)가 모두 있다 | `test_questions_returns_questions_for_real_graph` | 통합 | PASS |
| 2 | `alignment` 없이 그래프만으로도 질문이 생성된다 (여정 2 · **서버 쪽만**) | `test_questions_works_without_alignment` | 통합 | PASS (RED→GREEN) |
| 6 | 프론트가 실제로 보내는 `alignment: null` 도 '없음' 으로 다뤄진다 | `test_questions_accepts_explicit_null_alignment` | 통합 | PASS |
| 3 | `graph` 가 없으면 평평한 `{error,message}` 봉투로 400 을 낸다 | `test_questions_rejects_missing_graph` | 통합 | PASS |
| 4 | `/api/v1/flow` 는 graph·alignment 를 둘 다 요구한다 | `test_flow_requires_graph_and_alignment` | 통합 | PASS |
| 5 | 서버 세션이 없어도 요청 바디 폴백으로 판정이 돌아온다 (404 아님) | `test_judge_falls_back_to_body_question_without_session` | 통합 | PASS |

테스트는 `fixtures/live_qa_run.json` 의 **실제 발표 1회분** 산출물을 쓰고, LLM 은 `llm:"mock"` 으로
못박아 과금·네트워크 없이 계약만 검증한다.

## 브라우저 확인 (Playwright · 실서버 8000 · 실 LLM)

pytest 는 서버 경계에서 멈춘다. 원인 A(클라이언트 영속성)는 실제 브라우저로만 확인할 수 있어
Playwright 로 4가지를 직접 돌렸다.

| 검사 | 내용 | 결과 |
|------|------|------|
| A | 분석 결과가 없을 때 조용히 넘어가지 않고 안내가 뜨는가 | PASS — "내 발표 분석 결과가 없어 데모 질문으로 진행해요…" 배너 표시 |
| B | **새로고침 후** `pipelineOut` 이 복원되고 서버를 부르는가 | PASS — `{graph: True, alignment: True}` 복원, `POST /api/v1/questions` 1건, **질문 7개**, `sessionId='flat'` |
| C | 녹음 없이(=alignment 없이) 자료만으로 질문이 나오는가 (여정 2) | PASS — **질문 7개** |
| D | 답변 판정이 세션 없이도 도는가 | PASS — `POST /api/v1/sessions/flat/qa/judge` → `verdict=good score=85` (`undefined` 사라짐) |

화면에는 실제 질문("알림 확인 여부와 관계없이 인지 자원을 소모한다는 주장의 근거는…")이 렌더되고
IMU2CLIP 데모 문자열은 나타나지 않는다. 콘솔 오류 없음.

> **함정 기록.** 처음 B·C 를 돌렸을 때 C 가 실패했다. 코드가 아니라 **20시간째 떠 있던 낡은 서버**(PID 2743897/2743905,
> `python3 -m server`)가 8000·8001 을 잡고 있었고, 새로 띄운 프로세스는 `address already in use` 로 죽어 있었다.
> `ss` 가 이 환경에서 아무것도 출력하지 않아 "서버가 죽었다" 고 잘못 판단한 게 시작점이었다.
> **포트 확인은 `ss` 말고 `curl /api/health` 로 할 것.** 낡은 프로세스를 정리하고 재기동하니 C 도 통과했다.

## 원인 C — 질문 생성이 CTA 클릭 핸들러에만 있었다 (2차 수정)

원인 A·B 를 고친 뒤에도 사용자는 여전히 데모 질문만 봤다. 이유는 따로 있었다.

`buildQuestions` 호출이 **`[data-qa-start]` 버튼 클릭 핸들러 안에만** 있었다.
그런데 실제 사용자의 주 경로는 버튼이 아니다 — 리허설을 마치면 `showF11Reveal` 이
끝나면서 `app.js` 가 **스스로** `location.hash = '#/qa'` 로 이동한다. 이 경로는 핸들러를
안 거치므로 서버를 아예 부르지 않고, 안내 배너조차 뜨지 않는다. `#/qa` 로 가는
맨 링크 2곳("이 개념으로 질문 연습", "복습 코칭 시작하기")도 같은 문제였다.

**수정**: 진입점마다 생성 로직을 붙이는 대신 `ensureLiveQuestions()` 라는 단일 보장 지점을
만들고 `renderQa()` 초입(시간 트랙 게이트 통과 직후)에서 호출한다. `wireQaStart` 는 생성
책임을 내려놓고 상태만 세운다. 이렇게 하면 앞으로 `#/qa` 링크가 늘어도 같은 버그가 안 난다.
동시 호출은 모듈 변수 `qaBuilding` 으로 막고(저장소에 넣지 않는다 — 생성 중 새로고침하면
`true` 가 영구히 남아 재생성을 막기 때문), 생성 중에는 대기 화면을 보여준다.

| 검사 | 결과 |
|------|------|
| 첫 로드부터 `#/qa` 직행 (자동 이동과 동일, CTA 안 거침) | PASS — 대기 화면 → `POST /api/v1/questions` 1회 → **질문 7개**, IMU2CLIP 미노출 |
| CTA 버튼 경로 (기존) | PASS — 질문 7개, 요청 1회 (중복 없음) |
| 분석 결과 없음 | PASS — 안내 배너 |

> **테스트 함정 기록.** 처음 직접 진입 테스트가 실패했는데 코드가 아니라 테스트가 틀렸다.
> Playwright 에서 `goto(BASE)` 뒤 `goto(BASE + "#/qa")` 는 **해시만 다른 같은 문서라 재로드되지 않는다.**
> 그래서 메모리의 `nf` 는 첫(빈) 페이지 것 그대로였다. `add_init_script` 로 문서 로드 **전에**
> `sessionStorage` 를 심어야 실제 사용자의 메모리 상태와 같아진다.

## 원인 D — 단일 진입점 수정이 만든 무한 재시도 루프 (3차 수정)

원인 C 를 고치면서 **내가 새 버그를 넣었다.** 증상은 "페이지 로딩이 안 됨" 이었다.

`ensureLiveQuestions()` 의 `.finally` 가 `renderQa()` 를 부르고, `renderQa()` 가 다시
`ensureLiveQuestions()` 를 부른다. 생성이 **성공하면** `qaLiveActive()` 가 true 라 멈추지만,
**실패하거나 질문이 0개면** 아무 것도 기억하지 않으므로 조건이 그대로 남아 다시 생성한다.

- 실측: **8초 동안 `POST /api/v1/questions` 2278회**, 화면은 "질문 준비 중" 에서 영구 정지.
- 실제 그래프였다면 그 횟수만큼 **실 LLM 과금**이 발생한다. 심각도 높음.

거기에 더해 `let qaBuildFailed` 를 `resetQa()` **뒤에** 선언해 TDZ 참조 오류를 낼 뻔했다
(`resetQa()` 는 모듈 로드 중 실행된다). 그 자체로 페이지 전체가 죽는다. 선언을 앞으로 옮겼다.

**수정**: 모듈 변수 `qaBuildFailed` 로 실패를 기억하고 재시도하지 않는다.
저장소에 넣지 않으므로 새로고침하면 한 번 더 시도한다 — 일시적 실패는 사용자가 되살릴 수 있다.
`resetQa()` 에서 초기화해 새 코칭이면 다시 시도한다.

### RED → GREEN

```
RED : AssertionError: 실패 후 재시도 루프: 8초 동안 2278회 요청. 1회 이하여야 한다.
GREEN: tests/test_qa_entry_e2e.py .. 2 passed in 15.66s
```

| # | 무엇을 보장하는가 | 테스트 | 결과 |
|---|---|---|---|
| 7 | 생성 실패해도 재시도 루프에 빠지지 않는다 (요청 1회 이하) | `test_failed_generation_does_not_retry_forever` | PASS (RED→GREEN) |
| 8 | 생성 실패 시 이유가 상태에 남는다 | `test_failed_generation_shows_reason` | PASS |

`tests/test_qa_entry_e2e.py` 는 브라우저에서만 재현되는 회귀를 잡는 첫 테스트다.
`RUN_LIVE_TESTS=1` 일 때만 돌고(실행 중인 서버 + Playwright 필요), 기본 경로는 그대로 0.65초다.

> **교훈.** "요청이 나갔는가" 만 보고 "몇 번 나갔는가" 를 안 봤다.
> 앞선 검증들은 전부 요청 1회를 전제로 성공만 확인했고, 실패 경로는 아무도 안 봤다.

## 커버리지와 남은 빈칸 (정직하게)

- **원인 A(진짜 근본 원인)에는 자동 테스트가 없다.** 브라우저 `sessionStorage` 영속 로직이고,
  이 저장소에는 JS 테스트 하네스가 전혀 없다(`pyproject.toml` 은 파이썬 전용, `package.json` 없음).
  이번 버그를 잡아낼 회귀 테스트는 클라이언트 영속성 테스트여야 한다. 하네스 도입은 이 버그보다
  큰 결정이라 임의로 하지 않았다 — 도입한다면 Vitest + jsdom 이 최소 비용 선택지다.
- 위 6개 테스트가 덮는 것은 **서버 계약**이다. 원인 B 를 막고, 프론트가 의존하는 응답 모양을 고정한다.
- **여정 2 는 서버 수정만으로는 끝나지 않았다.** 서버에서 `alignment` 를 선택으로 바꾼 뒤에도
  클라이언트 가드(`qaLiveBlockReason`)가 여전히 `alignment` 를 요구해, 녹음 없는 사용자는
  "데모 질문으로 진행해요" 안내만 받고 여전히 질문을 못 받았다. 가드에서도 조건을 뺐다.
  테스트가 서버 경계에서 멈추기 때문에 이 누락을 테스트가 잡지 못했다는 점을 기록해 둔다 —
  원인 A 와 같은 빈칸(클라이언트 무테스트)의 두 번째 발현이다.
- 플랫 경로의 판정은 **근거 없이(ungrounded)** 돈다. 서버 세션이 없어 `graph`·`alignment`·`transcript`
  없이 `judge_answer` 가 호출된다. 실측에서 같은 답변이 `partial/55` 와 `good/85` 로 갈렸다.
  404 는 아니므로 동작은 하지만 품질이 조용히 낮아진다 — 계약 변경이 필요해 이번 범위에서는 남겨 둔다.

## 남은 조치

- 커밋하지 않았다 (사용자 승인 대기). 체크포인트 커밋을 만들 경우 위 RED/GREEN 요약을 커밋 본문에 옮길 것.
