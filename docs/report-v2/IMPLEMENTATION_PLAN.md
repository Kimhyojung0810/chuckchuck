# Report 2.0 — 구현 계획 (Phase 3 · 4, 승인 후)

> 2026-10-16 사용자 승인(D-004 · 005 · 006 · 009) — 「구현 시작해. 원래 그 /VRShow 에 반영」. ✅ = 완료 조건 확인, ◐ = 일부.

| # | 작업 | 파일 | 의존 | 완료 조건 |
|---|---|---|---|---|
| ✅ P3-1 | 앱 안 진입점 (/VRShow 정면 창은 플래그 없이) — 기존 리포트 위에 「새 리포트로 보기」(feature flag `cheokcheok:report-v2`) | `js/app.js` renderReport 머리 | 승인 | 플래그 꺼짐이면 기존 화면 픽셀 동일, 켜면 `/report-v2?src=live` |
| ✅ P3-2 | 같은 탭의 실데이터 입력 — `nf.pipelineOut` + 메모리 transcript(단어) + `qa.live` + chatter 를 묶음으로 | `js/report_v2.js loadData` | P3-1 | 실제 리허설 1회 끝에서 v2 가 같은 점수 · 판정을 보임(회귀 시험) |
| ✅ P3-3 | 저장 확장 (D-005) — last-report 에 단어 시각 · qa trail(claim · 꼬리질문) 보관 | `app.js saveLastReport` · `recordQaHistory` | 승인 | `#/report/last` 로 다시 열어도 리플레이 · 전환점 유지, 저장 크기 상한 시험 |
| ✅ P3-4 | qa-history 개념 · 장 빈 값 버그 (AUDIT §4) | `app.js:9669-9671` | — | 실측 Q&A 기록에 concept · slide 가 찬다(스모크) |
| ◐ P3-5 | 사용자 녹음 재생 (같은 탭) — `ccLastTake._blob` 을 object URL 로 | `report_v2.js` | P3-2 | 녹음한 탭에서 「여기 듣기」가 그 구간 재생, 새로고침 뒤엔 「글로만」 |
| P3-6 | 청중석 근거 검사 결과를 기존 극장에도 (근거 없는 대사 표시) | `chatter.js` · `report_graph.js` | 승인(D-004) | 쏠라 같은 근거 없는 대사에 표시 |
| P3-7 | 화면별 마감 — 01 → 02 → 03 → 04 → 05 순, 각 화면 빈 · 오류 · 로딩 상태 | `report_v2.*` | P3-2 | QA.md 화면별 시험 통과 |
| P3-8 | 재연습 이력 — 연습 끝에 진단 id 를 넘겨 PracticeAttempt 로 | `rehearsal.js` · `qa_live.js` | P3-3 | 같은 개념 재질문 결과가 05 에 「전 · 후」로 (사전 · 사후 증거가 있을 때만) |
| P3-9 | F-19 강점 · 약점 · 할 일 자유 글을 인사이트에 잇기 (D-006) | `report_graph.js` | 승인 | 장 번호 · 개념 이름이 맞을 때만 inferred 로 |
| P4-1 | 회귀 — 기존 리포트 점수 · 판정 값 보존 | `etc/tests/js/report_graph.smoke.mjs` + 새 비교 시험 | P3-2 | 같은 입력에서 v1 · v2 점수 · 판정 수 같음 |
| P4-2 | 덱 3개 × 실측으로 그래프 정합 | `etc/labs/report_v2/` | P3-2 | 덱마다 끊긴 엣지 0 · 원문에 없는 인용 0 · 근거 길 비율 기록 |
| P4-3 | 브라우저 시각 확인 데스크톱 · 태블릿 · 폰 | 실험실 스크립트 | P3-7 | QA.md 에 사진 · 결과 |

## 실제로 한 것 (2026-10-16)
- `js/report_v2.js` → `ReportV2.mount(root, data, {mode, slideImage, onLegacy})` 부품 + `inputFromApp()`(순수). 단독 페이지는 `bootPage`, 앱은 `mode:'app'`(주소를 안 건드리고 상태는 sessionStorage `cheokcheok:rv2-state`)
- `css/report_v2.css` 전부 `.rv2` 범위로 — 앱 토큰(--bg · --ink · --accent …)과 이름이 겹쳐도 앱을 덮지 않는다(스모크가 지킴)
- `js/app.js`: `reportV2On()`(sessionStorage `cheokcheok:report-v1` 이면 옛 화면 → /VRShow 정면 창 → localStorage `cheokcheok:report-v2`) · `renderReportV2()`(파일은 처음 쓸 때만 받음, 실패하면 옛 리포트) · 청중석이 늦게 오면 `update({chatter})` · 리포트를 떠나면 재생 정지
- 녹음: 부스 덱이면 서버 파일(`nf.deckAudio`, 저장본에도), 아니면 이 탭 메모리 녹음(object URL — 새로고침하면 없음, 실제 마이크로는 아직 안 봄 → P3-5 ◐)
- 저장(D-005): new-flow · last-report 에 단어(최대 4000 · 소수 둘째 자리) · 장 구간 · 추정 표시, last-report 에 Q&A 흐름(질문 · claim trail) · 덱 녹음 키. 넘치면 단어 · Q&A 를 빼고 다시 저장
- Q&A 기록 버그(P3-4): `concept` ← `node_id`, `slide` ← `slide_no · evidence_slide_no · slide_nos[0]`, `trail` 보관
