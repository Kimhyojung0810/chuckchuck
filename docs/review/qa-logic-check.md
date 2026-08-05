# QA 로직 검증 체크 문서 (F-08 · F-09)

> **이 문서의 용도**: 다른 LLM(리뷰어)에게 이 저장소의 QA 코칭 로직이
> 설계 의도대로 구현·접목되었는지 검증을 요청할 때 그대로 전달하는 문서다.
> 1부는 "무엇이 어떻게 되어야 하는가"(설계 계약), 2부는 "그것이 실제로
> 그런가"를 확인하는 체크리스트, 3부는 실행으로 증명하는 명령이다.
>
> **리뷰어에게**: 각 체크 항목을 코드에서 직접 확인하고
> `[x] 확인됨 / [ ] 불일치(사유)` 로 표시해 달라. 항목마다 근거 파일·위치를
> 적어 두었다. 문서와 코드가 어긋나면 **코드가 아니라 이 문서를 의심**하고
> 어긋난 지점을 보고해 달라.

---

## 0부. 시작 전 전제 확인 — **건너뛰지 말 것**

이 문서는 **`feat/qalogic` 브랜치**를 대상으로 한다. `main` 에는 F-08·F-09 구현도
`server/` 디렉터리도 없다. 아래를 먼저 실행해 올바른 트리 위에 있는지 확인하라.

```bash
git fetch origin && git checkout feat/qalogic
git rev-parse --short HEAD          # 이 문서와 함께 전달받은 기준 커밋과 일치해야 한다

# 이 셋 중 하나라도 어긋나면 잘못된 체크아웃이다 — 검증을 중단하고 보고하라
grep -c "_spread_adjacent" chuckchuck/f08_questions.py     # ≥ 1
grep -c "_answer_block" chuckchuck/f09_judge.py            # ≥ 1
ls server/app.py tests/test_flat_routes.py                 # 둘 다 존재
```

**규칙**: 문서에 적힌 심볼이 grep 0건으로 나오면 "구현되지 않았다"고 결론짓지 말고
**먼저 체크아웃을 의심하라.** 실제로 이전 리뷰가 `main` 을 검증하는 바람에 판정
18건이 무효가 됐다. 파일 하나가 통째로 없으면 그것은 코드 결함이 아니라 환경 문제다.

**좌표 표기**: 결함을 보고할 때는 라인 번호만 쓰지 말고 **함수·심볼 이름**을 함께
적어 달라. 라인은 커밋마다 밀리지만 심볼은 밀리지 않는다.

---

## 1부. 설계 — QA 로직의 흐름과 원칙

### 1.1 전체 파이프라인에서의 위치

```
F-01 parse (PDF/PPTX → SlideDoc)
  └─ F-05 stt (녹음 → Transcript)          ← 선택 (자료만 올린 경로도 있다)
       └─ F-06 concepts (SlideDoc → ConceptDoc)
            └─ F-07 graph (→ ConceptGraph: nodes/edges/sections/weight)
                 └─ F-11 align (그래프 × 발화 → AlignmentDoc)   ← 녹음 있을 때만
                      └─ F-11 flow (→ FlowDiff: order_jump/missing_link)
                           └─ [F-08] triage_questions → build_questions  ← 이번 구현
                                └─ [F-09] judge_answer / coach_stuck     ← 이번 구현
```

- **F-08** (`chuckchuck/f08_questions.py`): "심사위원이 뭘 물을까"를 만든다.
- **F-09** (`chuckchuck/f09_judge.py`): "그 답이 개념을 방어했나"를 판정한다.
- 계약 타입은 전부 `chuckchuck/contracts.py` (TriageMark, QaTriage, Question,
  QuestionDoc, QaTurn, QaJudgement + QA_* 상수들).

### 1.2 핵심 설계 원칙 — 리뷰의 기준축

1. **"무엇을 물을지는 코드가 정하고, LLM은 문장만 쓴다."**
   후보 선정·순위(rank)·근거(source)는 결정적 신호(F-07 weight, F-11 verdict,
   FlowDiff)에서만 나온다. LLM에는 severity·trap·angle 판단(1차)과
   문장 생성(2차)만 맡긴다. 이유: 리포트(F-11)가 "누락"이라 말한 개념과
   질문이 어긋나면 사용자가 두 화면을 믿을 수 없다.
2. **결정성(determinism)**: 같은 입력이면 항상 같은 후보·순서·질문 id가
   나와야 한다. 모든 정렬에 동률 파쇄 키(id 순 등)가 있다.
3. **LLM 응답은 계약 안으로 강제 정규화**: enum 밖 값은 폴백, 빠진 필드는
   결정적 템플릿으로 메꾼다. 프론트 화면이 비는 일이 없어야 한다.
4. **비용 규율**: 파싱 실패 시 재시도는 1회뿐. 빈 답변·힌트 사다리는
   LLM을 아예 부르지 않는다.
5. **triage는 세션당 1회, 재사용**: 트랙(1/5/10분)을 바꿔도 순위가
   흔들리지 않고 문장 생성 1콜만 추가된다.

### 1.3 F-08 흐름 (질문 생성)

**1단계 — 후보 선정 (코드만, LLM 없음)** `_ordered_candidates`
- 노드마다 근거(source) 하나를 정한다. 우선순위:
  `contradiction > missing > under_spoken > weak_flow > extra > core_weight > justified_skip`
  (`QA_SOURCES` 순서가 곧 서열, `contracts.py`)
  - `under_spoken`: `doc_weight - speech_weight > QA_UNDER_SPOKEN_GAP(0.4)` 인 개념
  - `justified_skip`: 리포트가 생략을 승인한 개념 → 서열 맨 뒤로 **강등**
    (단, 이미 모순·누락이 붙은 노드는 못 덮는다)
  - `extra`: 발화에만 나온 개념. 그래프를 새로 만들지 않고 `extra:` 네임스페이스의
    합성 노드로 기존 축에 얹는다 (weight 0.0, 최대 `QA_EXTRA_MAX=3`)
- 정렬 키: 근거 서열 → 구획 역할(`_ROLE_RANK`: 표지·맺음말 개념은 뒤로) →
  weight 내림차순 → 요약 유무 → 앞 슬라이드 → id. 상한 `CANDIDATE_LIMIT = 최대 트랙 상한 × 2 = 14`.

**2단계 — triage (LLM 1차 호출)** `triage_questions`
- LLM은 후보마다 severity(1치명/2보통/3가벼움)·trap(함정 가능 여부)·angle(질문 각도)만 판단.
- 프롬프트에 배분 쿼터를 명시한다: severity=1 은 후보의 ~34%(`SEVERE_SHARE`),
  trap 은 ~25%(`TRAP_SHARE`) — Solar 실측에서 치명·함정 몰아주기로 순위가
  뭉개진 것에 대한 대응. **코드가 강제로 깎지는 않는다** (판단 위임 원칙).
- `_normalize_marks`: 후보 밖 id 버림, enum 밖 severity는 source 기반 폴백,
  node_id·source·rank·doc_weight 는 코드가 채움.
- `_rerank`: 최종 순위 = 근거 서열 → 구획 역할 → **severity** → weight → … .
  source 가 severity 위인 이유: 모순·누락은 확인된 사실, severity는 LLM의 짐작.
- `_spread_adjacent`: 그래프에서 인접한 개념끼리 나란히 뽑히면 뒤로 강등
  (같은 source 안에서만, 모순·누락·under_spoken 은 면제).

**3단계 — 질문 문장 (LLM 2차 호출)** `build_questions`
- 트랙 상한(`QA_TRACK_LIMITS`: 1분=1, 5분=3, 10분=7)만큼 rank 순으로 자르고,
  함정 허용치(`QA_TRACK_TRAPS`: 1분=0, 5분=1, 10분=3)로 trap을 깎는다.
  밀린 개념은 `deferred_node_ids` 로 반환.
- LLM은 대상마다 question·why·hint·answer_gist 4문장만 쓴다.
- `_normalize_questions`: 빠진 대상은 결정적 템플릿으로 메꿈, 질문 id 는
  `q{rank:02d}-{node_id}` 로 결정적, 모든 문장 `QA_TEXT_MAX=200` 클립.

**힌트 사다리 (LLM 없음)** `build_hint_ladder`
- 방향(질문의 hint) → 범위(근거 슬라이드, 최대 3개만 나열) → 근접(판정의
  missing_points 또는 answer_gist 앞 절반 조각). 판정 전에는 2단계까지만.

### 1.4 F-09 흐름 (답변 판정)

`judge_answer(question, answer, ...)` 분기:
1. **빈 답변** → LLM 없이 `unknown` 즉시 반환 (`_empty_answer`). followup·hints 는 채움.
2. **포기** — `give_up=True`(버튼) 또는 `looks_stuck(answer)`(15자 이하 + 포기
   표현 + 시도 흔적 없음) → `coach_stuck` 으로. 점수를 매기지 않는다.
   - 1차 포기: `narrow` (더 쉬운 되물음), 2차 이상: `explain` (골자 해설 후 종료).
   - 단계는 서버가 history에서 계산 (`_coach_stage`) — 프론트가 상태를 보내지 않는다.
3. **정상 판정** → LLM 1콜. 프롬프트 순서: 질문 → 자료 근거(그래프 경로·이웃,
   정합 판정 evidence, 발화 발췌) → 최근 대화(`HISTORY_TURNS=6`) → 이번 답변.
   - **누적 판정**: `prior_answers` 가 있으면 "전체를 합쳐서 판정하라" 블록으로
     싣는다 (최근 `PRIOR_ANSWERS_MAX=5`개) — 되묻기로 나눠 답한 사람이
     마지막 증분만으로 평가되는 것을 막는다.

`_normalize` 가 지키는 계약:
- verdict 는 `QA_VERDICTS`(good/partial/wrong/unknown) 안, 밖이면 `unknown`
- score 는 0~100 clamp, 없으면 `QA_VERDICT_SCORES` 기본값
- **node_id 는 질문에서 승계** (LLM 값 무시 — 조인 키 보호)
- react·summary_sentence 는 비면 결정적 문구로 채움
- 통과(`qa_passed`: good 이거나 score ≥ 70)면 **followup 은 반드시 빈 문자열**
- 판정에 hints(힌트 사다리)를 실어 보낸다 — 프론트 추가 왕복 없음

### 1.5 서버·프론트 배선

**서버** (`server/app.py`) — 두 계열이 공존한다:
- 세션 라우트(비동기 잡): `POST /api/v1/sessions/{id}/questions` (202 + job_id,
  `track`/`mode` 둘 다 수용) → `GET /api/v1/jobs/{job_id}` 폴링.
- 판정만 동기: `POST /api/v1/sessions/{id}/qa/judge` — 프론트가 응답 바디를 바로 읽는다.
  `_resolve_question` 은 세션의 QuestionDoc 이 정본, 없으면 요청 바디의 question
  폴백 (인메모리 스토어라 서버 재시작 시 세션이 날아가는 경로 방어).
- 플랫 라우트(세션 없이 동기): `POST /api/v1/questions` — graph 만 필수,
  alignment/flow/transcript 는 선택. 내부에서 triage → build 를 연달아 실행.
- `settings.mock_external` 이면 llm 은 강제로 "mock".

**프론트** (`demo/YEHS_demo/js/`):
- `chuckchuck_bridge.js` 가 플랫 `/api/v1/questions` 와 세션 라우트 둘 다 사용.
- `app.js` 의 `ensureLiveQuestions()` 가 **단일 보장 지점**이다 — `renderQa()`
  초입에서 호출되어 "실제 질문이 필요한데 없으면 만든다"를 한 번만 책임진다.
  CTA·자동 이동·링크 등 어느 경로로 `#/qa` 에 들어와도 생성은 여기서만 일어난다.
  실패 시 `qa.liveNotice` 배너 + 데모 질문 폴백.
  (배경: `docs/plan/qa-live-questions.plan.md` — 진입 경로 3곳이 데모 질문만
  보여주던 버그의 단일 진입점 설계)

---

## 2부. 검증 체크리스트

리뷰어는 각 항목을 코드에서 확인하고 표시해 달라.

### A. 결정성과 순위 계약 (F-08)

- [ ] A1. 후보 선정·정렬에 LLM 이 관여하지 않는다. 정렬 키 마지막에 id 동률
      파쇄가 있어 같은 그래프면 같은 순서다. — `f08_questions.py:_ordered_candidates`
- [ ] A2. source 우선순위가 `QA_SOURCES` 순서와 일치하고, `_rerank` 에서
      source 가 severity 보다 위다. — `f08_questions.py:_rerank`
- [ ] A3. `justified_skip` 은 강등만 하고, 이미 모순·누락이 붙은 노드를 덮지
      않는다. weak_flow 는 덮는다. — `f08_questions.py:_source_by_node`
- [ ] A4. `extra:` 합성 노드가 weight 0.0 으로 만들어지고, `build_questions` 의
      `by_id` 사전에도 포함된다 (안 그러면 발화 개념 질문이 조용히 사라진다).
      — `f08_questions.py:_extra_nodes`, `build_questions`
- [ ] A5. 트랙 상한·함정 허용치가 `QA_TRACK_LIMITS`/`QA_TRACK_TRAPS` 대로
      적용되고, `_pick_marks` 가 원본 TriageMark 를 **변형하지 않는다**
      (triage 는 트랙 간 재사용되는 캐시다). — `f08_questions.py:_pick_marks`
- [ ] A6. `_spread_adjacent` 의 강등이 같은 source 그룹 안에서만 일어나고
      `_ADJACENCY_EXEMPT` 근거는 면제된다. 별 모양 그래프에서 루트가 맨 뒤로
      밀리는 회귀가 없는지. — `f08_questions.py:_spread_adjacent`
- [ ] A7. LLM 이 후보를 빠뜨리거나 잘못된 id 를 지어내도: 후보 밖 id 는
      버려지고, 빠진 후보는 폴백(severity·문장)으로 메워져 **질문 세트에
      구멍이 없다**. — `_normalize_marks`, `_normalize_questions`

### B. 판정 계약 (F-09)

- [ ] B1. verdict enum 밖 → unknown, score clamp 0~100, node_id 질문 승계,
      react/summary 항상 비어 있지 않음. — `f09_judge.py:_normalize`
- [ ] B2. `qa_passed` (good 또는 score ≥ 70) 이면 followup 이 빈 문자열이다.
      통과 못 하면 followup 이 항상 존재한다 (LLM 누락 시 결정적 폴백).
      — `f09_judge.py:_followup`
- [ ] B3. 빈 답변은 LLM 을 부르지 않는다. — `_empty_answer` + `judge_answer` 초입
- [ ] B4. `looks_stuck` 오탐 방어: 15자 초과이거나 시도 흔적("~는데", "~아닐까" 등)
      이 있으면 포기로 안 본다. — `f09_judge.py:looks_stuck`
- [ ] B5. 막힘 코칭 단계가 history 에서 상태 없이 계산되고(같은 질문의 앞선
      포기 횟수), 1차=narrow(정답 노출 금지), 2차=explain(되물음 없음)이다.
      explain 의 해설 폴백은 answer_gist. — `_coach_stage`, `coach_stuck`
- [ ] B6. 누적 판정: prior_answers 가 프롬프트에 "합쳐서 판정하라" 블록으로
      실리고 최근 5개로 잘린다. — `f09_judge.py:_answer_block`
- [ ] B7. 힌트 사다리는 LLM 을 부르지 않고, 어떤 단계도 answer_gist 전체를
      노출하지 않는다 (앞 절반 + …). — `f08_questions.py:build_hint_ladder`, `_gist_fragment`

### C. LLM 호출 규율

- [ ] C1. F-08 두 호출·F-09 판정·코칭 모두 JSON 파싱 실패 시 재시도는
      정확히 1회다 (무한 재시도 없음). — `_call_with_retry`, f09 `_call` try/except
- [ ] C2. 프롬프트에 배분 쿼터(severity=1 최대 N개, trap 최대 M개)가 실제
      후보 수에 비례해 들어간다. — `_build_triage_prompt`, `_quota`
- [ ] C3. temperature·max_tokens 가 용도별로 고정돼 있다 (triage/questions 0.3,
      judge 0.2) 이고 json_mode=True 다.

### D. 서버 배선

- [ ] D1. `POST /api/v1/sessions/{id}/questions` 가 track/mode 둘 다 받고
      enum 밖이면 폴백("10")이다. ConceptGraph 없으면 에러로 안내한다.
      — `server/app.py` `start_questions`
- [ ] D2. `POST /api/v1/sessions/{id}/qa/judge` 가 동기이고, 세션이 죽어도
      바디의 question 폴백으로 판정이 성립한다. — `server/app.py` `_resolve_question`, `judge_qa_answer`
- [ ] D3. 플랫 `POST /api/v1/questions` 가 graph 만으로 동작한다 (alignment
      없는 자료-만 경로). — `server/app.py` `flat_questions`
- [ ] D4. `settings.mock_external` 일 때 모든 QA 라우트가 llm="mock" 을 강제한다.
- [ ] D5. LLM 호출이 이벤트 루프를 막지 않는다 (`run_in_threadpool`).

### E. 프론트 배선

- [ ] E1. `#/qa` 로 들어오는 **모든** 경로에서 질문 생성이 `ensureLiveQuestions()`
      한 곳으로 수렴하고, 중복 호출(이중 요청) 가드가 있다. — `app.js` `ensureLiveQuestions`, `renderQa`
- [ ] E2. 생성 중 로딩 표시, 실패 시 데모 질문 + `qa.liveNotice` 배너가 뜬다.
- [ ] E3. judge 응답의 followup/hints/coach_stage/explanation 을 프론트가
      실제로 소비한다 (죽은 필드가 없는지). — `app.js`, `chuckchuck_bridge.js`
- [ ] E4. 판정 히스토리를 서버에 보낼 때 한글 키({질문,답변,판정})든 영문 키든
      `QaTurn.from_dict` 가 둘 다 받는다. — `contracts.py` `QaTurn`

### F. 테스트 커버리지

- [ ] F1. 위 A~E 의 각 계약에 대응하는 테스트가 존재한다. **개수는 문서를 믿지 말고
      직접 세어라** (parametrize 때문에 `grep -c "def test"` 는 실제보다 적게 나온다):
      ```bash
      python -m pytest tests/test_questions.py tests/test_judge.py tests/test_hints.py \
        tests/test_stuck_coaching.py tests/test_flat_routes.py --collect-only -q | tail -1
      ```
- [ ] F2. 테스트가 구현 세부가 아니라 **계약(불변식)** 을 검증한다
      — 예: "통과면 followup 이 빈다", "같은 입력이면 같은 사다리".
- [ ] F3. 커버리지 빈틈 후보를 리뷰어가 직접 제안해 달라. 아래는 이미 지목된 것들이니
      **여전히 비어 있는지 확인하고, 그 밖의 빈틈을 추가로 찾아 달라**:
      - Context 전파: QA 경로 전체에서 `context` 인자가 실제로 프롬프트까지 닿는지
      - `QA_EXPLAIN_MAX`: 다른 텍스트 필드는 상한 검증이 있는데 `explanation` 만 누락
      - triage 재사용(트랙 전환) 경로, `_spread_adjacent` 별 모양 그래프,
        세션 만료 후 judge 바디 폴백
      - 브리지/서버 QA 라우트: 400 안내 문구, track 폴백, 잡 폴링 종료 조건

---

## 3부. 실행 검증

```bash
# 1) QA 로직 단위·통합 테스트 (mock LLM, 네트워크 불필요 — 전부 통과해야 함)
python -m pytest tests/test_questions.py tests/test_judge.py \
  tests/test_hints.py tests/test_stuck_coaching.py tests/test_flat_routes.py -q
# 기대: 실패 0. 개수는 커밋마다 늘어나므로 고정값과 대조하지 말 것 —
# 전체 스위트(python -m pytest tests/ -q)도 실패 0 이어야 한다.

# 2) 서버 기동 + 플랫 경로 스모크 (mock 모드)
MOCK_EXTERNAL_APIS=1 python -m server &
curl -s localhost:8000/api/health          # {"ok": true, "mock": true}

# 3) E2E (Playwright — 브라우저 실제 경로)
python -m pytest tests/test_qa_entry_e2e.py -q
```

## 4부. 리뷰어에게 특별히 봐 달라는 열린 질문

1. **순위 정책의 타당성**: source > 구획 역할 > severity 라는 서열이
   "리포트와 질문 화면의 일관성"이라는 목표에 비추어 과한 제약은 아닌가?
   LLM 이 치명이라 본 본론 개념이 under_spoken 하나에 밀리는 경우가 실제
   UX 에서 이상하게 보일 수 있는지.
2. **쿼터의 강제 수준**: severity/trap 쿼터를 프롬프트로만 요청하고 코드가
   깎지 않는데, 모델이 계속 무시하면 1분 트랙 선정이 흔들린다. 코드 강제
   (초과분 강등)로 바꿔야 할지, 지금처럼 위임을 유지할지.
3. **`looks_stuck` 휴리스틱**: 한국어 표현 기반 정규식이라 영어 발표 연습
   등에서 빠질 수 있다. 지금 범위에서 충분한가?
4. **인메모리 세션**: judge 의 바디 폴백으로 살렸지만, 폴백 경로에서는
   graph/alignment 근거 없이 판정한다 — 판정 품질 차이가 사용자에게
   보이지 않는 것이 문제인지.
5. **triage 캐시 부재(플랫 경로)**: 플랫 `/api/v1/questions` 는 요청마다
   triage+build 2콜을 실행한다. 같은 그래프로 트랙만 바꿔 다시 부르면
   triage 가 재실행되는데(세션 라우트와 달리 캐시 없음), 이 비용을 받아들일지.
