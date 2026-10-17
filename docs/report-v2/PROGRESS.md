# Report 2.0 — 진행 기록

> 새 세션은 `README.md` → 이 파일 순서로 읽으면 이어갈 수 있다. 체크박스는 실제로 한 것만 친다.
> 작업 명세: `/home/yehschuck/project/chuckchuck/chuckchuck_report_v2_claude_code_prompt.md` (사용자 제공, 저장소 밖 · git 미추적)

## 지금 단계 — Phase 1(조사) + Phase 2(그래프 설계 · UX 프로토타입) · 2026-10-15 시작

**목표:** 기존 리포트 코드 · 데이터를 실제로 조사해 기록하고, Evidence Graph 최소 스키마와 `/report-v2` 클릭 가능한 프로토타입을 실제 데이터로 만든 뒤 사용자 승인을 받는다. 승인 전 기존 리포트 교체 · 대규모 구현 금지.

### Phase 1 — 조사
- [x] 리포트 화면 코드 조사 (renderReport · 탭 · 데이터 필드)
- [x] 평가위원(삐약이 청중석) · Q&A · 개념 그래프 조사
- [x] 분석 파이프라인 데이터 흐름 · 저장 위치 · 리플레이 가능성 조사
- [x] 실제 리포트 데이터 표본 확보 (실 API 결과, 샘플과 구분)
- [x] `AUDIT.md` · `DATA_MAPPING.md` 초안

### Phase 2 — 설계 · 프로토타입
- [x] Evidence Graph 최소 스키마 (`EVIDENCE_GRAPH.md`)
- [x] 그래프 빌더 · 검증기 (순수 JS, 기존 데이터 → 그래프) + 스모크
- [x] 실제 데이터로 `Insight → Evidence → Replay → Coaching` 경로 1~2개 검증
- [x] 5개 화면 IA · 와이어프레임 · 레이아웃 대안 (`PRODUCT_SPEC.md` · `UX_PROTOTYPES.md`)
- [x] `/report-v2` 클릭 가능한 프로토타입 (구버전 그대로)
- [x] `DECISIONS.md` OPEN 항목 정리 → 사용자 승인 요청

## 2026-10-16 — iOS + 토스 리포트 (D-011)
- 사용자: 「iOS + 토스 · 리포트 하나로 만들지 마라 · 화면 전환 여러 개 · 기능은 죽이지 말고 강약 · 와우 포인트 · 디테일」
- `js/report_v2.js` 화면 층을 다시 씀(그래프 · 데이터 · inputFromApp · mount API 그대로): 스택 9화면(home · issue · coach · replay · audience · chick · practice · qa · scores), push/pop(iOS 곡선) · 왼쪽 가장자리 밀기(1:1 · 속도) · 아래 시트(끌어 닫기) · 큰 제목 접힘 · 주소에 스택(page) / sessionStorage(app)
- `css/report_v2.css` 새로(.rv2 범위 그대로). 스튜디오 안에선 zoom 때문에 vh 가 모자라 `html.sx-studio #app.rv2-host` 를 창에 고정
- 검증: 헤드리스 1440 · 390 아홉 화면 · 뒤로 · 새로고침 · rehearsal_flow --report-v2(앱 · /VRShow) 통과

## 2026-10-16 — 승인 · Phase 3 구현 (/VRShow 반영)
- 사용자: 「네 가지 다 승인, 구현 시작해. 원래 그 /VRShow 에 반영」 → D-004 · 005 · 006 · 009 DECIDED
- [x] P3-1 앱 진입점 — /VRShow 정면 창은 자동, 그 밖엔 팀 플래그 `localStorage cheokcheok:report-v2=1`, 「이전 리포트」 로 옛 화면
- [x] P3-2 같은 탭 실데이터 (nf.pipelineOut · qa.live · 청중석 · 덱 그림 · 녹음)
- [x] P3-3 저장 확장 (단어 · 장 구간 · Q&A 흐름 · 덱 녹음 키)
- [x] P3-4 Q&A 기록 개념 · 장 빈 값 버그
- [~] P3-5 사용자 녹음 재생 — 코드 있음, 실제 마이크 확인 안 함
- [ ] P3-6 옛 극장에도 근거 검사 · [ ] P3-8 재연습 이력 · [ ] P3-9 F-19 자유 글(D-006 으로 안 함)
- 검증: QA.md 2026-10-16 (앱 · /VRShow 연결)
- 배포: main 합치기는 사용자 `!` (자동 모드가 운영 배포를 막음)

## 2026-10-16 — 디자인 다시 잡음
- 사용자 「디자인 개병신 같은데」 → Apple 자료 수집(`etc/design-ref/apple/README.md`) → 「그 방향으로 다시 디자인해」 → `css/report_v2.css` · `js/report_v2.js` 마크업 재작성(D-010). 그래프 · 데이터 로직은 그대로

## 2026-10-17 — 「질문은 이렇게 골랐어요」 (Q&A 개편 4단계, 네 모델 후보 판)
- 사용자: 「각 AI 모델별로 어떻게 해당 슬라이드에서 질문을 빼내고, 마지막에 어떤 질문을 줄지 정교화된 걸 보여 주는 것」 — 결선 심사 와우 포인트
- 화면 셋(스택 push): `board`(고른 과정 — 깔때기 후보→거르기 통과→서로 평가→질문 · 그래프 미니맵(층=핵심 주장·주장·개념, 물은 노드 번호, 루트까지 줄) ·
  받은 질문 · 모델마다 맡은 일 · 거르기에서 뺀 까닭 · 자리 목록) → `slot:<id>`(묻는 방식 · 경로 · 모델별 후보 옆 넘기기 · 서로 평가 표 · 고른 까닭 · 기대한 답)
  · `round:<n>`(3번+: AI 가 들은 신호 · 음성 후보 · Solar Pro4 가 고른 이유). 판정 5색 안 씀(스모크가 지킴)
- 진입점: 연습 탭 「Q&A 돌아보기」 위 · 홈 「더 살펴보기」 · 질문 하나 화면 아래 「이 질문은 이렇게 골랐어요」. 판이 없으면 한 줄(한 모델이 골랐어요 · 불러오는 중 · 처음 연 탭에서 볼 수 있어요)
- 데이터: `/api/v1/qa/board`(세션 메모리 — 동의 무관, 보관은 동의 세션만) → 리포트가 얹고 이 브라우저 마지막 리포트 저장본에도 둔다(`qaBoard`)
- 샘플: `#/rehearsal/report/demo` 는 `js/report_qaboard_sample.js` — 10/17 실험 dev3p4 C1 r1 good-good(부스 덱 배달앱 별점, 네 모델 모두 후보, 3·4번 라운드)
- 검증: 실험실 rehearsal_flow --report-v2 실 API 2판(8821, QA_ENSEMBLE=1) — 앱 리포트 · /VRShow 정면 창 · #/report/last 에서 판 · 자리 · 3번 화면, 360·393·412·1440 캡처
- 남은 것: 같은 파일 = 같은 세션(파싱 sha 재사용)이라 3번+ 기록이 같은 파일을 올린 사람끼리 섞일 수 있다(답 원문은 안 남기고, 화면은 내 Q&A 와 글자로 맞는 것만 그린다) ·
  미니맵은 그래프 품질을 그대로 보인다(개념 아래 주장 같은 꼬인 부모는 줄이 엉킨다)

## (지난) 승인 대기 상태 (2026-10-15)
승인받을 것: `DECISIONS.md` 의 OPEN — D-004(청중 = 청중, 점수 안 만듦) · D-005(저장 늘리기) · D-006(F-19 자유 글) · D-009(안 A 구조).
승인 뒤 `IMPLEMENTATION_PLAN.md` P3-1 부터. **승인 전 기존 리포트 교체 · 대규모 구현 금지.**

## 다음 세션이 할 일
1. 사용자 답 확인 → DECISIONS 의 OPEN 을 DECIDED/REVISED 로
2. P3-1(앱 안 진입점, 플래그) → P3-2(같은 탭 실데이터) 순

## 막힌 점
- 청중 넷 중 믿:음(키 401) · 엑사원(응답 깨짐) 결석 — 운영 키 문제, 리포트 v2 는 결석을 그대로 보인다
- `#/report/last` 저장본엔 단어 시각 · Q&A claim · 꼬리질문이 없다 → 다시 연 리포트에선 리플레이 · 성찰이 약해진다 (D-005 OPEN)

## 검증 결과
- 2026-10-15 `node etc/tests/js/report_graph.smoke.mjs` — 23개 통과 (실측 불변식 6개 포함)
- 실측 그래프(rec_v2): 노드 161 · 엣지 280 · 인사이트 8 · 근거 길 비율 0.75 · 끊긴 엣지 0 · 원문에 없는 인용 0
- 실제 경로 2개 확인: `I:concept:gaseol-a → V:said → U8/U9(46–51초)` · `I:pace:short → V:pace:1~3 → S1~S3 · U*` (EVIDENCE_GRAPH §8)

## 이번에 만든 것 (파일)
- `docs/report-v2/` README · PROGRESS · DECISIONS · AUDIT · DATA_MAPPING · EVIDENCE_GRAPH
- `main/web/js/report_graph.js` — Evidence Graph 빌더 · 검증기 · 뷰모델 (화면 없음)
- `etc/tests/js/report_graph.smoke.mjs`
- `etc/labs/report_v2/make_fixture.py` → `main/web/data/report_v2_rec.json` (실측 묶음, 팀 전용 정적 경로)
- `main/web/report_v2.html` · `js/report_v2.js` · `css/report_v2.css` — `/report-v2` 시제품 (팀 전용, bridge `_TEAM_PAGES`)
- `docs/report-v2/` PRODUCT_SPEC · UX_PROTOTYPES · IMPLEMENTATION_PLAN · QA
- `etc/labs/rehearsal_flow/run.py` — 리포트 단계에서 브라우저 상태를 `state.json` 으로 남김(`dump_state`)
- 실측 추가 호출: `/api/v1/chatter` 1회(청중), rehearsal_flow `--weave` 실 판정 1회(Q&A)
