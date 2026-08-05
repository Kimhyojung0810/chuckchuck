# 질문 코칭이 실제 경로에서 데모 질문만 보여주는 문제

## 배경

`/api/v1/questions` 서버 라우트는 정상이다 (실 LLM 로 질문 7개 생성, 13.4초 확인).
`pipelineOut` 영속화와 안내 배너도 고쳤고 브라우저로 확인했다.
그런데 **실제 사용 경로에서는 여전히 데모 질문만 나온다.**

## 근본 원인

질문 생성(`buildQuestions`)이 **CTA 버튼(`[data-qa-start]`) 클릭 핸들러 안에만** 붙어 있다.
`#/qa` 로 가는 다른 경로들은 이 핸들러를 거치지 않아 서버를 아예 부르지 않고,
`qa.live` 가 빈 채로 `renderQa()` 가 데모 질문(`js/data.js`)을 렌더한다.
안내 배너조차 뜨지 않아 사용자에게는 "그냥 데모값" 으로만 보인다.

우회 경로 3곳 (모두 `app.js`):

| 위치 | 경로 | 비고 |
|---|---|---|
| `app.js:1078` | 파이프라인 완료 후 f11 리빌 종료 → `location.hash = '#/qa'` | **주 경로.** 리허설을 마친 사용자가 실제로 타는 길 |
| `app.js:1895` | "이 개념으로 질문 연습" 링크 | `data-qa-start` 없음 |
| `app.js:2147` | "복습 코칭 시작하기" 링크 | `data-qa-start` 없음 |

`app.js:1747` 의 `wireQaStart(app, { pickMode: true })` 는 의도적으로 게이트를 태우는 경로라
버그는 아니지만, 게이트 통과 후 질문 생성으로 이어지는지 확인이 필요하다.

## 설계 방향

진입점마다 질문 생성을 복사하지 말고 **단일 보장 지점**을 만든다.
`renderQa()` 가 실행될 때 "실제 질문이 필요한데 없으면 만든다" 를 한 번만 책임지게 하고,
CTA 핸들러는 그 함수를 부르는 여러 호출자 중 하나가 된다.
이렇게 해야 앞으로 `#/qa` 링크가 늘어나도 같은 버그가 재발하지 않는다.

## Step 1. 질문 생성을 단일 진입점으로 통합

`ensureLiveQuestions()` 를 만들어 `renderQa()` 초입에서 호출한다.
`nf.pipelineOut.graph` 가 있고 `qa.live` 가 비어 있으면 `buildQuestions` 를 호출하고,
그동안 로딩 상태를 보여준다. 실패하면 기존 `qa.liveNotice` 로 이유를 남긴다.
`wireQaStart` 의 중복 생성 로직은 이 함수를 부르도록 정리한다 (동시 중복 호출 방지 포함).

- Acceptance: `#/qa` 로 들어오는 모든 경로에서 `POST /api/v1/questions` 가 정확히 1회 발생한다.
- Acceptance: 질문 생성 중에는 로딩 표시가 보이고, 실패 시 데모 질문 + 안내 배너가 함께 보인다.
- Out of scope: 판정(judge) 계약 변경, 세션 라우트 도입.

## Step 2. 우회 경로 3곳 배선 및 중복 제거

`app.js:1078` 자동 이동, `app.js:1895`·`app.js:2147` 링크가 Step 1 의 보장 지점을 타도록 한다.
`data-qa-start` 를 붙일지, 링크는 그대로 두고 `renderQa()` 보장에만 의존할지 한 가지로 통일한다.
`wireQaStart` 가 여러 렌더에서 중복 바인딩되지 않는지도 함께 정리한다.

- Acceptance: 세 경로 각각에서 실제 질문이 나온다 (데모 질문 아님).
- Acceptance: 핸들러 중복 바인딩으로 인한 이중 요청이 없다.
- Out of scope: QA 화면 시각 디자인 변경.

## Step 3. 실제 사용 경로 전 구간 재현 테스트

지금까지의 확인은 `sessionStorage` 에 `pipelineOut` 을 심어 둔 상태에서 시작했다.
그래서 파이프라인이 그것을 *쓰는* 순간과 자동 이동 경로를 못 잡았다.
업로드 → (녹음 파일) → 파이프라인 → 자동 이동 → 질문 생성까지 실제로 태우는
Playwright 테스트를 만든다. 녹음은 `fixtures/` 의 샘플 오디오를 파일 업로드 경로로 대체한다.

- Acceptance: 시드 없이 빈 `sessionStorage` 에서 시작해 실제 질문이 화면에 뜬다.
- Acceptance: 테스트가 수정 전 코드에서는 실패한다 (판별력 확인).
- Out of scope: JS 단위 테스트 하네스(Vitest) 도입.

## Step 4. 회귀 방지 문서화

`docs/testing/qa-questions-fallback.tdd.md` 에 이번 우회 경로 원인과 단일 진입점 설계를 추가한다.
"새 `#/qa` 링크를 추가할 때 확인할 것" 체크리스트를 남긴다.

- Acceptance: 우회 경로 3곳과 단일 진입점 규칙이 문서에 남는다.
- Out of scope: 전체 아키텍처 문서 재작성.
