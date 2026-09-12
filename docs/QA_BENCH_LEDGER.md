# Q&A 벤치마크 장부

각 줄은 `qa_eval_compare.py --ledger` 가 붙인다. 채택(IMPROVED)만 코드에 남고, 나머지는 되돌린다.

| 시각 | 전 | 후 | 판정 | 핵심 델타 | HEAD | 메모 |
|---|---|---|---|---|---|---|
| 2026-09-12 17:22 | 20260912-171643_base-20260912-1643 | 20260912-172218_v1-20260912-1643 | REGRESSED | specificity_mean 3.33→4; grounding_mean 0.50→0.59; fallback 3→0; impolite_questions 0→3; rubric.overall_mean 4.14→3.66; rubric.groundedness_mean 4→5; rubric.relevance_mean 4.67→3.67; rubric.depth_mean 3.67→2.67; rubric.answerability_mean 4.67→3.67 | 504d8d8 | H1-node-id-list 질문 대상 node_id 목록을 프롬프트에 한 줄로 명시해 폴백(3/3)을 없앤다 |
| 2026-09-12 17:24 | 20260912-171643_base-20260912-1643 | 20260912-172439_v2-20260912-1643 | REGRESSED | specificity_mean 3.33→4.67; fallback 3→0; impolite_questions 0→3; rubric.relevance_mean 4.67→5; rubric.depth_mean 3.67→4; rubric.answerability_mean 4.67→5 | 504d8d8 | H2-coverage-gap aligned 개념의 심화 질문을 「자료 본문에는 있는데 발표에서 안 한 말」에 겨냥한다 (coverage 3.0 ↑) |
| 2026-09-12 17:27 | 20260912-171643_base-20260912-1643 | 20260912-172712_v3-20260912-1643 | REGRESSED | specificity_mean 3.33→5; fallback 3→0; rubric.depth_mean 3.67→4; rubric.non_duplication_mean 5→4.67 | 504d8d8 | H3-concrete-item-depth 질문 문장에 자료 본문의 구체 항목 하나를 넣고 그것의 이유·한계·비교를 묻게 한다 (depth 3.67 · 특이도 ↑) |
