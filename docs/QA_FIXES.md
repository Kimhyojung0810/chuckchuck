<!-- 이 파일: Q&A 코칭(F-08·F-09) 및 서비스 전반에서 확인된 문제와 수정 결과를 적어 둔 작업 기록입니다. -->

# Q&A 코칭 점검 — 고칠 것

`chuckchuck/f08_questions.py` · `chuckchuck/f09_judge.py` · `demo/bridge.py` ·
`demo/YEHS_demo/js/{app.js,qa_live.js,chuckchuck_bridge.js}` 를 읽고 정리했다.
모듈 계약·판정 후처리는 문서대로 동작한다. 아래는 **배선과 운영에서 새던 곳**이다.

실측 근거는 `fixtures/live_qa_run.json` (focus_notification_demo_designed.pptx 12장 +
실제 녹음, track=5) 을 썼다.

**상태 요약 — 11건 중 10건 수정 완료, 1건(S-5) 부분 완료.**

| 항목 | 내용 | 상태 |
|------|------|------|
| #1 | 판정이 자료 근거 없이 돌던 것 | ✅ |
| #2 | 요청마다 triage 재실행 | ✅ |
| #3 | 「모르겠어요」가 explain 까지 못 가던 것 | ✅ |
| #4 | 코칭 호출이 판정 스키마를 이고 가던 것 | ✅ |
| #5 | 설득 카운터 기준이 화면마다 다르던 것 | ✅ |
| S-1 | 리포트 점수를 LLM 이 덮어쓰던 것 (+크래시) | ✅ |
| S-2 | 판정 호출에 타임아웃이 없던 것 | ✅ |
| S-3 | 서버 무상태 — 아티팩트 재업로드 | ✅ |
| S-4 | 인증·요청제한 없음 + CORS `*` | ✅ |
| S-5 | app.js 4,487줄 (상한 800) | ⚠️ 부분 |
| S-6 | 데모 폴백이 리포트에 섞이는지 | ✅ 확인 결과 안 섞임 |

---

## 1. [HIGH] 판정이 자료 근거 없이 돈다 — ✅ 수정됨

> **수정**: `judgeQaAnswer()` 가 `session_id` 로 자료 근거를 실어 보낸다. 세션이 비었으면
> (브리지 재시작) 서버가 409 `session_missing` 을 주고 클라이언트가 재등록 후 재시도한다.
> 브리지 로그에 `근거=graph/align/stt` 로 적재 여부가 찍힌다.

**증상** — F-09 가 질문 문장·답변·history 만 보고 판정했다. 자료(그래프)·정합 판정·발화를
못 봐서 "자료와 어긋난다"(`wrong`) 를 대조할 원본이 프롬프트에 없고,
함정 질문의 핵심 규칙(*잘못된 전제를 바로잡았을 때 good*)도 짐작이었다.

**원인** — 프론트가 안 보냈다. `chuckchuck_bridge.js` 의 `judgeQaAnswer()` 가
`question_id · answer · history · question · give_up` 만 실었다.
서버(`bridge.py`)와 모듈(`f09_judge.py`)은 이미 받을 준비가 돼 있었고
단위 테스트도 넘겨서 검증하고 있었다 — **모듈은 정상, 배선만 누락이었다.**

---

## 2. [MEDIUM] 브리지가 요청마다 triage 를 다시 돌린다 — ✅ 수정됨

> **수정**: `demo/session_store.py` 의 지문(fingerprint) 캐시. 키는
> `sha1(graph + alignment + flow + llm)` 이라 트랙만 바꾼 재요청은 `build_questions()` 1콜로 끝난다.
> 적중하면 로그에 `[bridge] F-08 triage cache hit`.

**증상** — 질문 1세트에 LLM 이 2번 불렸고, 트랙을 바꾸면 순위가 흔들려
1분 트랙 질문이 5분 트랙의 부분집합이라는 보장이 깨졌다 (`temperature=0.3`).
`f08_questions.py` 는 *"triage 는 트랙과 무관하므로 세션에 한 번만"* 을 전제로 쓰여 있었다.

**검증** — 같은 자료로 track 5 → 10 요청 시 캐시 적중 1회, 5분 질문 3개가
10분 질문 7개의 **부분집합임을 확인**했다.

---

## 3. [MEDIUM] 「모르겠어요」를 텍스트와 같이 누르면 해설 단계로 못 간다 — ✅ 수정됨

> **수정**: `QaTurn` 에 `gave_up` 필드 추가(한글 키 `포기`). `_coach_stage` 가
> `t.gave_up or looks_stuck(t.answer)` 로 센다. 프론트는 `L.turns` 와 history 에 플래그를 싣는다.

**증상** — 입력창에 뭔가 써 놓고 「모르겠어요」를 누르면 두 번 세 번 눌러도 계속
`narrow`(쉬운 되물음)만 나와 같은 질문에 갇혔다.

**원인** — 단계를 history 의 답변 **텍스트**로 역추정했다. 사용자가 친 글이 답변으로 가면
`looks_stuck()` 이 거짓이 되고(`GIVE_UP_MAX_CHARS = 15`), history 에 give_up 플래그가 없어
서버가 의도를 복원할 수 없었다. 채택안은 문서에 적었던 (A) — 의도를 텍스트로 역추정하는
구조 자체가 원인이었기 때문이다.

---

## 4. [LOW] 코칭 호출이 판정 시스템 프롬프트를 이고 간다 — ✅ 수정됨

> **수정**: `_call_coach()` 를 분리해 system 을 `COACH_SYSTEM_PROMPT` 하나로 뒀다.
> 공용 `_complete_json()` 아래에서 판정·코칭이 각자의 스키마만 이고 간다.

**증상** — 코칭 응답이 판정 스키마(`verdict`/`score`)로 돌아오면 `react`·`followup`·`explanation`
이 비고 조용히 F-08 폴백 문장으로 대체됐다. 화면은 멀쩡해 보여서 알아채기 어려웠다.

**회귀 테스트** — 코칭 호출의 system 에 `verdict`·`summary_sentence` 가 없고
`단계=narrow`·`explanation` 이 있는지 검사한다 (`tests/test_stuck_coaching.py`).

---

## 5. [LOW] '설득' 카운터가 화면마다 다른 기준을 쓴다 — ✅ 수정됨

> **수정**: `liveWonCount(results)` 하나로 모으고 서버가 내려 주는 `passed` 만 센다.
> 판정 결과를 닫을 때 `passed` 를 기록한다.

같은 `N / 총` 이 세 기준으로 계산돼 진행 중 3/3 이 결과 화면에서 1/3 로 떨어질 수 있었다.

| 위치 | 전 | 후 |
|------|-----|-----|
| 코칭 진행 중 헤더 | `good \|\| partial` | `r.passed` |
| 코칭 결과 화면 | `good` 만 | `r.passed` |
| 서버 `qa_passed()` | `good \|\| score >= 70` | (진실의 단일 출처) |

---

# 서비스 전체 관점 (S-1 ~ S-6)

## S-1. [HIGH] F-19 리포트 점수·등급을 LLM 이 덮어쓴다 (+크래시 경로) — ✅ 수정됨

> **수정**: `compose_report` 가 score/grade 를 항상 `_rule_score`·`_grade_from_score` 로
> 계산하고 LLM 값을 무시한다. `_SYSTEM` 프롬프트에서 score/grade 요구도 뺐다.
> 회귀 테스트 2건 (`tests/test_voice_report.py`).

- 모듈 도입부는 *"숫자는 다시 짐작하지 않습니다"* 인데 LLM 점수가 규칙 점수를 밀어냈다.
- grade 는 enum 검증이 없어 "S급" 도 화면에 갈 수 있었다.
- **크래시** — `"score": "85점"` 이 오면 `int()` 가 try/except **밖**에서 터져,
  폴백 리포트를 두고도 502 가 났다.

## S-2. [MEDIUM] 판정 API 호출에 타임아웃이 없다 — ✅ 수정됨

> **수정**: `fetchWithTimeout()` 공용 헬퍼를 만들어 `qaApi` 에도 적용(판정 30초,
> 질문 생성 60초). 타임아웃은 오류로 끝나므로 `finally` 의 busy 해제가 반드시 돈다.

`qaApi()` 에 AbortController 가 없어, 판정 요청이 매달리면 「판정 중…」 상태로
textarea·버튼이 전부 잠긴 채 새로고침 말고는 출구가 없었다.

## S-3. [MEDIUM] 서버가 무상태 — 아티팩트 재업로드·LLM 재과금의 뿌리 — ✅ 수정됨

> **수정**: `demo/session_store.py` (스레드 안전 · TTL 6시간 · LRU 32세션).
> 신규 `POST /api/v1/session/artifacts` 로 한 번 등록하면 이후 질문 생성·판정은
> `session_id` 만 보낸다. 본문이 오면 본문이 이긴다(방금 만든 결과가 캐시에 밀리지 않게).
> #2 의 triage 캐시도 이 저장소가 함께 들고 있다.

보관 키는 `graph · alignment · flow · transcript · context` 로 **고정**이다 —
프론트가 큰 객체(SlideDoc·오디오)를 밀어 넣어도 메모리가 새지 않는다.
`None` 은 저장하지 않는다: 나중 요청의 빈 값이 이미 등록된 근거를 지우면 판정이 근거를 잃는다.

프로세스 메모리라 재시작하면 사라진다 — 그때는 409 `session_missing` 으로 알리고
클라이언트가 재등록 후 재시도한다. (`DEV_POLICY.md` 계층표의 '저장소' 는 여전히 프로덕션 서버 몫.)

## S-4. [MEDIUM] 인증·레이트리밋 없음 + CORS `*` — ✅ 수정됨

> **수정**: `demo/rate_limit.py` — 과금 경로(파싱·STT·개념·그래프·정합·수다·습관·리포트·질문)에
> IP당 분당 상한(`DEMO_RATE_LIMIT_PER_MIN`, 기본 30, 0이면 끔). 초과 시 429 + `retry_after`.
> CORS 는 `DEMO_ALLOWED_ORIGINS` 허용 목록에만 연다(기본은 같은 출처라 헤더 자체가 불필요).
> 바인드 기본값은 이미 `127.0.0.1` 이었고, 외부 주소로 열면 시작 로그가 경고한다.

**검증** — 상한 2/분에서 3번째 요청이 429, 제한 없는 경로(`/api/v1/score`)는 통과,
허용 목록 밖 Origin 에는 `Access-Control-Allow-Origin` 이 안 붙는 것을 확인했다.

## S-5. [LOW] 자체 파일 크기 규칙 위반 — ⚠️ 부분 수정

> **수정**: 실전 질문 코칭 화면을 `demo/YEHS_demo/js/qa_live.js` (361줄) 로 분리했다.
> `app.js` 4,487 → **4,177줄**. 여전히 상한(800)을 크게 넘는다.

문서가 권했던 "qa-live 부분만이라도 분리" 는 끝냈지만 규칙 준수는 아니다.
남은 분리 후보(각각 독립적으로 떼어낼 수 있다):

| 후보 | 대략 범위 | 크기 |
|------|----------|------|
| 리포트 화면 (`renderReport` 계열) | 탭 6종 · 시각화 | ~700줄 |
| 리허설·녹음 화면 | 업로드 → 녹음 → 파이프라인 진행 | ~900줄 |
| 데모 코칭(스크립트 `qaBeats` 경로) | 샘플 시연 전용 | ~500줄 |
| 게임 레이어(XP·연속 방어) | localStorage 상태값 | ~150줄 |

자동화된 프론트 테스트가 없어 한 번에 쪼개면 시연 직전에 위험하다.
**분리할 때마다 클래식 스크립트 로드 시뮬레이션으로 전역 공유·중복 선언을 확인할 것** —
이번 분리도 그렇게 검증했다 (5개 스크립트 동일 전역 로드 + 필수 함수 15종 확인).

## S-6. [LOW·확인 필요] 데모 질문 폴백이 실제 리포트에 섞이는지 — ✅ 확인 결과 안 섞임

리포트 화면은 `nf.pipelineOut`(파이프라인 결과)만 읽는다. Q&A 코칭 결과
(`qa.live.results` · `qa.concepts`)를 참조하는 코드가 리포트 경로에 **없다**.
`renderProfileReport(DATA.reportProfiles[...])` 는 별도 라우트의 정적 샘플 페이지다.
따라서 데모 질문으로 진행한 코칭이 실제 발표 리포트를 오염시키지 않는다. 조치 불필요.

---

## 검증 방법

```bash
python -m pytest tests/ -q                     # 399 passed
MOCK_EXTERNAL_APIS=true python -m demo.bridge  # 손으로 눌러 보는 경로
```

새로 추가된 테스트:

| 파일 | 내용 |
|------|------|
| `tests/test_demo_infra.py` | 세션 저장소(TTL·LRU·None 보호·사본 반환) · triage 캐시 · 요청 제한 |
| `tests/test_stuck_coaching.py` | 긴 텍스트 + 포기 버튼 → explain · 포기 플래그 왕복 · 코칭 프롬프트 격리 |
| `tests/test_voice_report.py` | LLM 점수/등급 덮어쓰기 차단 · 비수치 score 크래시 방지 |

프론트는 자동화 테스트가 없어, mock 브리지에 실제 프론트 코드
(`app.js` · `qa_live.js` · `chuckchuck_bridge.js`)를 물려 확인했다 —
질문 생성(session_id 만) · 판정 근거 적재 · 포기 2회 → explain · 세션 유실 후 재등록 재시도 ·
카운터 단일 기준까지 6항목.

---

## 확인된 수치 — 자료 하나가 질문 몇 개가 되나

`fixtures/live_qa_run.json` (실제 실행, 12장 PPTX + 실제 녹음, track=5):

| 단계 | 결과 |
|------|------|
| F-01 슬라이드 | 12장 |
| F-06 개념 추출 | 12장분 `ConceptDoc` |
| **F-07 개념 그래프** | **노드 13개** · 간선 19 · 섹션 5 |
| F-11 정합 | 13개 판정 (전부 `aligned`) · 흐름 이슈 3 (전부 `good_link`) |
| F-08 후보 심사 | 노드 13개 전부 (상한 `CANDIDATE_LIMIT = 14`) |
| **F-08 질문 생성** | **3개** (track=5) · 보류 10개 |

**트랙이 목표 개수를 정한다** (`contracts.py`):

| 트랙 | 질문 수 = 설득 목표 | 함정 허용 |
|------|--------------------|----------|
| 1분 | 1개 | 0 |
| 5분 | 3개 | 1 |
| **10분 (기본값)** | **7개** | 3 |

- 개념(노드) 수 자체에는 상한이 없다. 자료가 크면 늘어난다 —
  구조 제약만 있다 (루트 ≤ 4 · 깊이 ≤ 3 · F-07 입력은 슬라이드당 개념 6개까지).
- 질문 수는 개념 수와 무관하게 **트랙 상한**에 묶인다. 13개 개념이 나와도 5분이면 3개만 묻고
  나머지 10개는 `deferred_node_ids` 로 "더 길게 하면 이것도 물어요" 안내에 쓴다.
- 화면의 `N / 총` 에서 총은 그 트랙의 질문 수다. 기본 10분이면 **7개 중 7개 설득**이 만점이다.

### 덤 — triage 배분 목표는 실제로 안 지켜진다

같은 실행에서 LLM 이 13개 중 **13개 전부에 `trap=true`** 를 줬다
(프롬프트 배분 목표는 `TRAP_SHARE=0.25` → 최대 3개). severity 는 지켜졌다
(1이 4개, 목표 `round(13 × 0.34) = 4`).

함정이 실제로 1개로 줄어든 것은 `_pick_marks()` 의 트랙 예산(`QA_TRACK_TRAPS`) 덕이다 —
프롬프트 배분은 권고고 **코드 캡이 유일한 실효 장치**다. `f08_questions.py` 주석이
이미 같은 현상을 적어 뒀다. 배분 목표를 프롬프트로 더 조이기보다, 트랙 캡을 신뢰하는 편이 낫다.

---

## 문제 없던 것 (재확인함)

- **XSS** — `summary_sentence` 를 escape 없이 push 하지만 `streamRow` 가 렌더 시점에
  escape 한다 (`qa_live.js` → `app.js:streamRow`). 이중 이스케이프 회피 의도.
- `_normalize()` 계약 강제 — verdict enum · score clamp(0~100) · node_id 질문 승계 ·
  react/summary 폴백.
- 힌트 사다리가 LLM 을 부르지 않고 도는 것.
- `_pick_marks()` 가 `TriageMark` 를 새 객체로 복사해 캐시된 triage 를 안 건드리는 것 —
  이제 triage 가 실제로 캐시되므로 이 성질이 특히 중요해졌다.
- 업로드 상한 30MB(`MAX_UPLOAD_BYTES`) · Content-Length 검사 · 파일/오디오 개별 검사.
