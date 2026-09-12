# Q&A 벤치마크 장부

각 줄은 `qa_eval_compare.py --ledger` 가 붙인다. 채택(IMPROVED)만 코드에 남고, 나머지는 되돌린다.

| 시각 | 전 | 후 | 판정 | 핵심 델타 | HEAD | 메모 |
|---|---|---|---|---|---|---|
| 2026-09-12 17:56 | 20260912-174825_gbase-20260912-1801 | 20260912-175645_g1-20260912-1801 | REGRESSED | label_grounded 0.86→1; align.evidence_found 0.17→0; align.false_aligned 2→5; align.coverage 0.88→1 | 5b2be5c | G1-evidence-from-speech-only F-11: evidence 는 「슬라이드별 발화」 절에서만 복사 — 개념 목록의 한 줄 설명을 옮기면 버려진다 |
| 2026-09-12 18:00 | 20260912-174825_gbase-20260912-1801 | 20260912-180026_g2-20260912-1801 | IMPROVED | label_grounded 0.86→1; align.evidence_found 0.17→1; align.false_aligned 2→0; align.coverage 0.88→1 | 5b2be5c | G2-summary-copy-concept-line F-07: summary 는 새로 짓지 말고 개념 목록 항목의 설명 문장을 그대로 옮긴다 |
| 2026-09-12 18:04 | 20260912-180026_g2-20260912-1801 | 20260912-180402_g3-20260912-1801 | REGRESSED | orphan_ratio 0→0.12 | 4e48ece | G3-merge-only-same-name F-07: 합치는 것은 이름이 같은 항목뿐 — 고유 이름(영문 용어·연구자·N단계)은 각자 노드, label 은 목록 이름 그대로 |
| 2026-09-12 23:12 | 20260912-230525_gbase-20260912-2304 | 20260912-231219_g1-20260912-2304 | REGRESSED | slide_coverage 1→0.83; summary_grounding 0.66→0.35; orphan_ratio 0.14→0; align.evidence_found 0.86→1 | 0fb708c | G5 F-07: 노드 수 기준을 '피할 숫자'에서 '후보 대비 근거 있는 목표'로 바꾸고, 따로 둔 노드마다 parent 간선을 묶는다 |
| 2026-09-12 23:14 | 20260912-230525_gbase-20260912-2304 | 20260912-231446_g2-20260912-2304 | REGRESSED | summary_grounding 0.66→0.45; orphan_ratio 0.14→0 | fbc1fef | G4 F-06: 슬라이드 본문에서 이미지 캡션을 걷어낸 뒤 클리핑한다 — S4 4단계·S9 3가지 해법이 지금은 잘려서 안 보인다 |
| 2026-09-12 23:17 | 20260912-230525_gbase-20260912-2304 | 20260912-231717_g3-20260912-2304 | REGRESSED | summary_grounding 0.66→0.37; nodes_per_slide 0.58→0.92; orphan_ratio 0.14→0; dup_label_pairs 0→1 | fbc1fef | G6 F-06: 장당 개념 2~5개, 번호·단계·표 행·항목 목록은 항목 하나가 개념 하나 — 개념명은 자료 낱말 그대로 |
| 2026-09-12 23:31 | 20260912-232918_gbase3-20260912 | 20260912-233136_g4-20260912 | REGRESSED | nodes_per_slide 1.30→0.86; dup_label_pairs 2.67→0.67 | f16dbb0 | G4 F-06 입력 정제(clean_slide_text) 뒤 클립 · 3회 평균 |
