# 척척발표 Report 2.0 — Evidence Graph 기반 인터랙티브 코칭 리포트

> 이어서 일할 땐 이 파일 → [`PROGRESS.md`](PROGRESS.md) 순서로 읽는다.

## 목표
기존 리포트(`#/report` · `#/rehearsal/report`)의 분석 자산을 그대로 쓰면서, **진단 → 근거 → 고치기 → 다시 연습** 이 이어지는 새 리포트를 만든다.
분석 결과 · 슬라이드 · 발언 · 평가위원 · 코칭을 내부 **Evidence Graph** 로 잇고, 화면에는 그래프 대신 근거 사슬 · 하이라이트만 보인다.

## 범위
- 5개 화면: 01 결과 공개 · 02 삐약이 청중석 · 03 발표 리플레이 · 04 코칭 스튜디오 · 05 다시 연습
- 기존 리포트는 그대로 둔다. 새 버전은 별도 주소(결정: [`DECISIONS.md`](DECISIONS.md))
- 데이터가 없는 기능은 `unavailable` · `not_supported` 로 보인다 — 지어내지 않는다

## 현재 상태
2026-10-17 리포트 개편(홈 · Q&A 돌아보기 · 발표 태도 갈고리 · 옛 리포트 빈 요소 정리) — feat/report-ia-1017. 자세한 건 [`PROGRESS.md`](PROGRESS.md) · 결정은 [`DECISIONS.md`](DECISIONS.md) D-014~D-020.

## 문서
| 문서 | 내용 |
|---|---|
| [`AUDIT.md`](AUDIT.md) | 기존 기능 · 코드 · 데이터 전수조사, 재사용 여부, 누락 · 위험 |
| [`DATA_MAPPING.md`](DATA_MAPPING.md) | 기존 데이터 필드 ↔ 그래프 · 뷰모델 ↔ 화면 |
| [`EVIDENCE_GRAPH.md`](EVIDENCE_GRAPH.md) | 노드 · 엣지 스키마, 출처, 검증 규칙, 예제 |
| [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md) | 5개 화면 정의 · 여정 · 성공 기준 |
| [`UX_PROTOTYPES.md`](UX_PROTOTYPES.md) | 레이아웃 대안 비교 · 와이어프레임 · 전환 흐름 |
| [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) | 작은 작업 단위 · 의존성 · 완료 조건 |
| [`DECISIONS.md`](DECISIONS.md) | 결정 기록 (OPEN = 승인 필요) |
| [`PROGRESS.md`](PROGRESS.md) | 진행 체크리스트 · 막힌 점 · 검증 결과 |
| [`QA.md`](QA.md) | 테스트 계획 · 실제 검증 로그 |

## 실행 · 확인
```bash
# 개발 브리지(DEV_ROUTES — 팀 모드)에서
http://localhost:8810/report-v2                # 실측 묶음(data/report_v2_rec.json)으로 다섯 화면
http://localhost:8810/report-v2?src=last       # 이 브라우저의 마지막 리포트로 (단어 시각 · Q&A 꼬리질문 없음 → 리플레이 · 전환점 약함)
node etc/tests/js/report_graph.smoke.mjs        # 그래프 정합 · 실측 불변식
# 실측 묶음 다시 만들기 (실험실 응답 → 한 파일)
.venv/bin/python etc/labs/report_v2/make_fixture.py --rec etc/labs/rehearsal_flow/out/rec_v2 --state etc/labs/rehearsal_flow/out/rec_v2/state.json
```
미리보기 링크(데이터 · 장 그림 · 녹음을 한 파일로 묶은 사본, 비공개): https://claude.ai/artifact/U4uV9mwcJGjRZtUUQ5KghJ — 묶는 스크립트는 저장소 밖 세션 임시 폴더였다(재현: report_v2.js 의 그림 주소를 data: 로 바꾸고 `__RV2_DATA` · `__RV2_EMBED` 를 넣는다).

브라우저 콘솔 `__RV2.validate()` 로 그래프 지표 · 문제 목록을 볼 수 있다.
