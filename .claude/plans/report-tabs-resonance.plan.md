# Plan: 논리 흐름·음성 습관 탭 — 3초 안에 진단+처방이 읽히게

**Source PRD**: .claude/prds/report-tabs-resonance.prd.md
**Selected Milestone**: 1~3 (논리 흐름 탭 재편 · 음성 습관 탭 재편 · 숫자 해석 라벨) — 같은 메커니즘 하나로 세 마일스톤을 덮는다
**Complexity**: Medium

## Summary
두 탭 상단에 「가장 큰 문제 한 줄 + 처방 한 줄」 탭 진단 블록을 얹고, 그 진단을 받치는 카드를
바로 아래로 올린 뒤 나머지는 `details.fold` 로 접는다. 남는 숫자에는 전부 판정 말을 붙인다.
파이프라인·스키마는 불변 — 프론트가 이미 받는 `flow`·`pace`·`habits` 데이터의 표현만 바꾼다.

## Patterns to Mirror
| Category | Source | Pattern |
|---|---|---|
| 진단 블록 구조 | `demo/YEHS_demo/js/app.js:2821` (`reportVerdict`) | "판단은 헤드, 단서는 아래 작은 줄" — 점수 임계값 → 해요체 한 줄, 근거는 subnotes 로 |
| 헤드라인 선택 규칙 | `demo/YEHS_demo/js/app.js:153-178` (`voiceEasyBlocks`) | 데이터 조건 분기로 해요체 headline + actions[] 를 이미 만든다 — 음성 탭은 이걸 승격하면 된다 |
| 접기 | `demo/YEHS_demo/js/app.js:3600` (rSummary) | `<details class="fold"><summary>… 더 보기</summary>` — 1순위만 펼치고 나머지를 접는 기존 관례 |
| 정직성 (지어내지 않기) | `demo/YEHS_demo/js/app.js:3540, 4178` | 분석 없으면 empty-card, 샘플이면 ⚠️ 샘플 배지 — 헤드라인도 근거 없으면 생략 |
| 렌더 함수 이름 | `demo/YEHS_demo/js/app.js:4044, 4117` | 탭 렌더는 `r접두사`(`rLogic`/`rPace`), 순수 도우미는 camelCase 별도 함수 |
| CSS 토큰·타이포 | `demo/YEHS_demo/css/app.css:135, 738` | `.section-title`/`.voice-lead` 급 크기, `:root` 토큰 밖의 색·radius 금지 |
| Tests | 해당 없음 | 프론트 JS 테스트가 없다 — 검증은 pytest 회귀(파이프라인 불변 확인) + 수동 체크리스트 |

## Files to Change
| File | Action | Why |
|---|---|---|
| `demo/YEHS_demo/js/app.js` | UPDATE | 진단 도우미 2개 추가 + `rLogic`/`rPace` 재배열 + 해석 라벨 |
| `demo/YEHS_demo/css/app.css` | UPDATE | `.tab-verdict` 진단 블록·해석 라벨 스타일 (기존 토큰만 사용) |
| `demo/YEHS_demo/index.html` | UPDATE | 캐시 버전 `?v=qa73` → `?v=qa74` (app.js·app.css) — CLAUDE.md §2 함정 |

## Tasks

### Task 1: 진단 선택 규칙 — 순수 함수 2개
- **Action**: `flowVerdict(flow)` 와 `voiceVerdict(easy)` 를 추가한다. 각각 `{ headline, action, evidence } | null` 을 돌려준다.
  - **논리 흐름 우선순위**: `missing_link`(연결 멘트 없음) > `order_jump`(근거 점프) > (나쁜 것 없으면) 잘된 연결 칭찬 + tau 기반 처방. 처방 한 줄은 1순위 이슈의 `note`/`cue` 에서 만든다 (예: 「N번→M번 사이에 잇는 말이 없었어요. "그래서 다음으로" 같은 연결 멘트를 하나 넣어 보세요」).
  - **음성 습관 우선순위**: 핵심 장 시간 부족(shortCore) > 초과(longOnes) > 속도(권장 범위 이탈) > 간투어. `voiceEasyBlocks` 가 이미 만드는 `headline`/`actions[0]` 을 재사용하고, 우선순위에 맞게 정렬만 정리한다.
  - **근거가 없으면 `null`** — 헤드라인을 지어내지 않고 기존 화면 그대로 둔다 (PRD out-of-scope 규율).
- **Mirror**: `voiceEasyBlocks` 의 조건 분기, `reportVerdict` 의 임계값 문구
- **Validate**: 브라우저 콘솔에서 실데이터/빈 데이터/이슈 없음 3케이스 수동 호출

### Task 2: 탭 진단 블록 마크업 + CSS
- **Action**: `#rbody` 맨 위에 들어가는 `tabVerdictHtml(v)` 를 추가한다 — 진단 `<h2>` 한 줄(16~18px, `--w-bold`) + 처방 한 줄(`.voice-lead` 급) + 근거 미리보기(발화 인용이 있으면 `bubble` 재사용). 새 스타일은 `.tab-verdict` 하나로 묶고 `:root` 토큰만 쓴다.
- **Mirror**: `verdict-judgement`(app.js:2921) 의 "큰 글씨는 한 줄" 규율, MVP_SPEC §3 절제(장식·이모지 없음)
- **Validate**: 아이패드 가로(1180px)에서 진단+처방+1차 근거가 스크롤 없이 보이는지 실측

### Task 3: 논리 흐름 탭 재배열 (마일스톤 1)
- **Action**: `rLogic()` — 진단 블록을 맨 위에, 1순위 이슈 카드를 그 아래에 펼치고, 나머지 카드는 `<details class="fold"><summary>나머지 N곳 더 보기</summary>` 로 접는다. 실데이터 경로(`rLogicRealCards`)와 샘플 경로(`DATA.logicBreaks`) 모두 같은 구조.
- **Mirror**: rSummary 의 「이것부터 고치면 돼요」+fold 패턴 (app.js:3597-3602)
- **Validate**: 브리지 실데이터 리포트 + 샘플 리포트 양쪽에서 탭 확인

### Task 4: 음성 습관 탭 재배열 (마일스톤 2)
- **Action**: `rPace()` — 진단 블록을 맨 위에, 진단을 받치는 카드 1개(시간 문제면 시간 차트, 간투어 문제면 간투어 구름)를 그 아래로. 나머지(구간별 속도·시간 배분 등)는 fold. 기존 `voice-tip`·중복 리드 문구는 진단 블록으로 통합해 한 번만 말한다 (PRD open question 3 해소).
- **Mirror**: Task 3 과 동일 구조 — 두 탭이 같은 문법으로 읽히게
- **Validate**: 실데이터 3분기(신형 slides 경로·구형 segments 경로·샘플) 모두 확인

### Task 5: 숫자 해석 라벨 (마일스톤 3)
- **Action**: 남는 모든 판정 숫자 옆에 판정 말을 붙인다.
  - 일치도 % (tau): ≥85 「자료 순서를 잘 따랐어요」 / 60~84 「순서가 몇 번 엇갈렸어요」 / <60 「자료 순서와 많이 달랐어요」
  - 평균 자/분: 권장 범위 대비 「권장 범위예요」/「권장보다 조금 빨라요/느려요」
  - 스탯 카드(목표/실제 시간): 차이를 말로 (「목표보다 1분 짧았어요」)
  - 숫자 자체는 유지·판정 색 5종 불변 (UI_REDESIGN §14 — 숫자는 신성하다)
- **Mirror**: 기존 `note` 문구 톤 (app.js:4165-4176), 해요체·능동형 규율 (CLAUDE.md §3-1)
- **Validate**: 두 탭 전수 육안 점검 — 라벨 없는 숫자 0개

### Task 6: 캐시 버전 + 회귀 + 커밋
- **Action**: `index.html` 의 app.js·app.css `?v=qa73`→`qa74`. `python -m pytest tests/ -q` 초록(기준 561 passed · 7 skipped) 확인 후 커밋·푸시 (§3-5 — 묻지 않는다).
- **Validate**: 아래 Validation 블록 전체

## Validation
```bash
cd /home/ubuntu/workspace/00_chuckchuck
python -m pytest tests/ -q                          # 561 passed · 7 skipped 유지 (파이프라인 불변 증명)
grep -c 'v=qa74' demo/YEHS_demo/index.html          # app.js·app.css 캐시 버전 갱신 확인
# 수동: DEMO_PORT=8799 ./demo/run_bridge_midm.sh 로 실데이터 리포트 열어
#  - 논리 흐름·음성 습관 탭 첫 화면(아이패드 가로)에 진단+처방+근거가 스크롤 없이 보이는지
#  - 샘플 경로(#/report/imu2clip 폴백)도 같은 구조 + 샘플 배지 유지되는지
#  - 이슈 0건 데이터에서 헤드라인이 거짓말하지 않는지
```

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| 199KB `app.js` 수정 중 다른 탭 파손 | 중 | `rLogic`/`rPace`/신규 함수 밖은 건드리지 않는다. 분할 리팩터 금지(§4) 준수 |
| 캐시 버전 미갱신으로 "고쳤는데 안 바뀜" | 중 | Task 6 에 명시 + grep 검증 |
| 데이터 빈약 시 헤드라인이 어색·거짓 | 중 | verdict 함수가 `null` 을 돌려주면 블록 자체를 생략 — 기존 화면 폴백 |
| fold 안에 넣은 정보를 심사위원이 못 찾음 | 하 | summary 문구에 개수 명시(「나머지 N곳 더 보기」), 기존 rSummary 관례와 동일 |

## Acceptance
- [ ] Task 1~6 완료
- [ ] Validation 전체 통과 (pytest 초록 + 수동 체크 3항목)
- [ ] 기존 패턴 미러링 — 새 문법 발명 없음 (fold·verdict·note 재사용)
- [ ] 부스 리허설 3초 테스트(PRD 마일스톤 4)는 이 계획 밖 — 배포 후 별도 진행
