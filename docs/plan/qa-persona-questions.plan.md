# 청중 페르소나 질문 — "이 상황에서 누가, 무엇을 묻는가" (로드맵 B3)

> 작성 2026-09-12. 상태: 설계. 구현은 `/improve-qa` 가설로 넣어 벤치마크가 채택을 정한다.

## 지금

`Context.situation`(`school_project` · `product_launch` · `work_report` · `casual_peer`)과 `audience` 는
`ctx.to_prompt_block()` 으로 질문 프롬프트 맨 위에 **한 줄 텍스트**로만 실린다
(`f08_questions.py _build_question_prompt`). "학교 프로젝트 (교수 대상)" 이라는 말만 있고,
교수가 **어떤 질문을 하는 사람인지**는 모델의 상식에 맡긴다. 그래서 상황이 달라도 질문 각도가 같다.

## 가설

상황별 「묻는 사람」 블록을 프롬프트에 넣으면 rubric relevance·depth 가 오른다 (특이도·인용률은 그대로).

| situation | 묻는 사람 | 그 사람이 실제로 묻는 것 | 묻지 않는 것 |
|---|---|---|---|
| school_project | 교수·심사위원 | 근거의 출처, 방법의 타당성, 한계와 대안, 선행 연구와의 차이, "그 수치는 어떻게 쟀나" | 감상, 발표 태도 |
| product_launch | 고객·기자 | 왜 지금 나에게 필요한가, 경쟁 제품과 뭐가 다른가, 가격·조건, 안 되는 경우 | 내부 구현 |
| work_report | 상사·의사결정자 | 결과가 목표 대비 어디까지 왔나, 다음 행동과 필요한 자원, 리스크와 대비, "그래서 결정할 건 뭔가" | 배경 설명 반복 |
| casual_peer | 동료 개발자·팀원 | 어떻게 구현했나, 재현하려면, 시행착오, 다음에 같이 할 수 있는 것 | 격식 있는 검증 |

## 구현 (f08 만, 계약 변경 없음)

```python
PERSONA_BY_SITUATION = {
    "school_project": "묻는 사람은 교수·심사위원이다. 근거의 출처, 방법의 타당성, 한계와 대안, 선행 연구와의 차이를 묻는다. ...",
    ...
}
# _build_question_prompt: ctx.to_prompt_block() 다음 줄에 PERSONA_BY_SITUATION.get(ctx.situation, "") 을 넣는다.
```

- 상황이 비었으면(`""`) 블록도 비운다 — 범용 발표에 억지 페르소나를 씌우지 않는다.
- `audience` 자유 입력이 있으면 페르소나 문장 뒤에 "청중은 실제로 {audience} 다" 를 붙인다.
- 4개 상황을 한 프롬프트에 다 싣지 않는다 — 해당 상황 한 블록만.

## 측정

- `fixtures/live_qa_run.json` 의 context.situation 을 확인하고, 없으면 4개 상황으로 같은 번들을 4번 잰다
  (`qa_eval.py` 에 `--situation` 덮어쓰기 옵션 추가 — 자를 고치는 것이므로 루프 밖에서 먼저 커밋).
- 기대: `rubric.relevance_mean` ↑ · `rubric.depth_mean` ↑ · 특이도·인용률 ＝ · 환각 0.
- 상황 4개 중 하나라도 REGRESSED 면 채택하지 않는다 — 한 상황을 살리려고 다른 상황을 망치지 않는다.

## 순서

1. `qa_eval.py --situation` (측정 도구) → 커밋
2. `/improve-qa focus="청중 페르소나 블록 (docs/plan/qa-persona-questions.plan.md)"` 로 가설 1개만
3. 채택되면 4개 상황 × 벤치를 장부에 남긴다
