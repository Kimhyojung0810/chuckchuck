# QA 판정 — 정답 단답이 unknown 으로 거부되는 문제

## Problem
질문 코칭에서 이지선다형 질문("N1, N2 단계는 얕은 수면인가요, 깊은 수면인가요?")에
정답 단답("얕은 수면이야")을 해도 판정 LLM 이 "답변이 너무 짧아 판단할 수 없습니다"
(unknown)를 내려 정답자가 되묻기에 갇힌다. 데모 부스에서 심사위원·관람객이 정답을
말하고도 통과하지 못하면 제품이 채점을 못 하는 것으로 보인다.

## Evidence
- 2026-08-07 사용자 실측: 위 질문에 "얕은 수면이야" 입력 → unknown 판정으로 거부됨.
- 원인 확인됨: 판정 프롬프트에 정답 기준(answer_gist)이 실리지 않고, unknown 정의가
  "답이 너무 짧거나"로 길이를 판정 사유로 명시해 "짧아도 맞으면 good" 규칙과 충돌한다.

## Users
- **Primary**: 데모에서 질문 코칭을 실제로 답하는 발표 연습자(심사위원·관람객 포함).
  선택형 질문에는 자연히 단답으로 답한다.
- **Not for**: 서술형 장답의 채점 품질 개선(이번 범위 아님).

## Hypothesis
We believe **판정 요청에 정답 열쇠(answer_gist)를 싣고 "선택형은 선택이 맞으면 good,
길이는 감점·보류 사유가 아님"을 판정 기준으로 명시하는 것** will **정답 단답의
unknown 거부를 없앤다** for **질문 코칭 사용자**.
We'll know we're right when **정답 단답 케이스가 회귀 테스트와 실측 양쪽에서
good/partial(통과)로 판정된다**.

## Success Metrics
| Metric | Target | How measured |
|---|---|---|
| 정답 단답 판정 | good/partial (70점 이상 통과) | pytest 회귀 케이스 |
| 실측 재현 | 문제 케이스가 실제 브리지에서 통과 | 데모 시나리오 수동 재현 |
| 기존 판정 회귀 | 없음 | `python -m pytest tests/ -q` 초록 유지 (556 passed 기준) |

## Scope
**MVP** — 판정 LLM 요청 1회는 유지하되, 프롬프트에 정답 골자(answer_gist)를 싣고
길이·선택형 판정 규칙의 내부 충돌을 제거한다. 한 문제당 요청 흐름:
답변 → 코드 분기(빈답/포기) → LLM 판정 1회(정답 골자 포함) → 70점 이상 통과 / 미달 되묻기.

**Out of scope**
- unknown 시 2차 확인 호출 — 왕복이 늘어 체감 지연 +2~5초, 데모에 불리해 보류.
- 선택형 질문의 코드 문자열 매칭 — 표현 변형("얕은 거요")을 놓치는 취약점, 보류.
- unknown 안내 문구·출구 UX 개선 — 판정 자체가 고쳐지면 빈도가 줄므로 후순위.

## Delivery Milestones
| # | Milestone | Outcome | Status | Plan |
|---|---|---|---|---|
| 1 | 판정에 정답 열쇠 제공 | 정답 단답이 통과 판정을 받는다 | complete | 2026-08-07 구현·실측 완료 |

## Open Questions
- [ ] answer_gist 가 비어 있는 질문(F-08 이 골자를 못 만든 경우)에서도 같은 규칙이
      안전한가 — 열쇠 없이 규칙만 강화하면 오답 단답이 관대하게 통과할 수 있다.

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 정답 골자를 실으면 모델이 관대해져 오답도 통과 | 중 | 중 | 오답 단답 케이스를 회귀 테스트에 함께 추가 |
| 프롬프트 변경이 기존 서술형 판정을 흔듦 | 저 | 중 | 기준선 pytest 초록 유지 확인 |

---
*Status: DRAFT — requirements only. Implementation planning pending via /plan.*
