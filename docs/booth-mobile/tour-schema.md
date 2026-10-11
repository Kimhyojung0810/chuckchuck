# 투어 녹화 데이터 — `data/tour/<id>.json` (v1)

원본은 [`tour.schema.json`](tour.schema.json). 이 문서는 칸마다 **화면이 무엇에 쓰는지**를 적는다. 예시는 [`demo/YEHS_demo/data/tour/_example.json`](../../demo/YEHS_demo/data/tour/_example.json).

## 화면 ↔ 칸

| 화면 | 읽는 칸 | 하는 일 |
|---|---|---|
| `#/tour/deck` | `deck` | 표지·장 그림 넘겨 보기. 「이 자료로 발표해 볼게요」 |
| `#/tour/present` | `deck.slides` · `present` | `present.slides` 시각에 장을 넘기고, `transcript` 를 자막처럼, `coaching_chips` 를 `at_sec` 에 띄운다. 건너뛰기 가능 |
| `#/tour/analysis` | `analysis` | 한 줄 요약 → 장별 시간 → 말 속도 · 군더더기 → 핵심 주장 그래프 요약 |
| `#/tour/qa` | `qa` | 질문마다 「잘 답한 답」·「엉성한 답」 중 하나를 눌러 판정과 근거 줄을 비교 |
| `#/tour/report` | `report` | 3단계 평가 항목 + 다음 연습 제안 → 「내 자료로 직접 해 보기」 · 「팀 소개로 돌아가기」 |

## 칸

**맨 위** — `schema:"chuckchuck.tour"`, `version:1`, `id`(= 파일 이름; `_` 로 시작하면 예시), `source{kind, recorded_at, note}`.
`kind` 는 `example`(형식 예시) 또는 `recorded`(실제 리허설 녹화). 이름이 `_` 로 시작하는 파일만 `example` 일 수 있다(테스트가 본다).

**`deck`** — `id`(= `assets/deck-slides/<id>/` 폴더), `title`(≤40자), `subtitle`(선택), `cover`, `slides[{no, image, title}]`.
그림 경로는 `index.html` 기준 상대, `?v=` 없이: `assets/deck-covers/<x>.webp`, `assets/deck-slides/<덱>/<n>.webp`. 부스 덱 그림은 이미 있다
(`battery-fastcharge` 4장 · `delivery-rating` 3장 · `microplastic-daphnia` · `focus-notification` · `investor-gap` · `sleep`). `no` 는 1부터 차례.

**`present`** — `duration_sec`, `slides[{slide_no, start_sec, end_sec}]`(장별 넘김 시각, 겹치지 않고 차례),
`transcript[{slide_no, start_sec, end_sec, text≤80자}]`(발화 전사 조각),
`coaching_chips[{at_sec, slide_no, kind, text≤16자}]`. `kind`: `listen`(잘 듣고 있어요) · `fast` · `slow` · `quiet` · `loud`
(비전 리허설 삐약이 반응, `js/vision_cue.js`) + `filler`(군더더기) · `time`(이 장이 길어요). 감정 추정 칩은 만들지 않는다.

**`analysis`** — `summary`(≤90자), `level`, `slide_times[{slide_no, sec, level, note?}]`,
`pace{cpm, level, note}`(자/분, 권장 300~350), `fillers{count, per_min, top[{word, count}], level}`,
`claim_graph{summary, root, nodes[{id, label≤30, kind, status, slide_no|null}], edges[{from, to}]}`.
노드 `kind`: `claim`(루트=주장 문장) · `reason` · `evidence` · `concept`. `status`: `aligned` · `justified_skip` · `missing` · `contradiction` (판정 색과 짝). 노드 12개까지.

**`qa`** — `asker`(질문하는 역할 이름표, 교수님 등), `questions[{id, slide_no, question≤120, answers{good, rough}}]` (1~5개).
답 하나: `text`, `verdict`(`good|partial|wrong|unknown`), `level`, `feedback≤90`, `grounds[≤3]`.
근거 줄: `{slide_no, ref:"S<장>-<줄>", quote(자료 줄 그대로), role:"covered|missing|conflict", note(왜 근거인지)}` — 서버 판정 응답의
`grounds`(`chuckchuck/_judge_grounds.py`)와 같은 이름이라 녹화 응답을 그대로 옮겨 담을 수 있다. 화면 글자는 `js/qa_live.js` 의
`LIVE_GROUND_ROLE`(짚은 것 · 빠진 것 · 다시 볼 곳)을 쓴다.
규칙: `good` 답의 판정은 `good`, `rough` 답은 `good` 이 아니다 — 아니면 비교가 성립하지 않는다.

**`report`** — `headline≤40`, `items[{id, label≤14, level, note≤60}]`, `next_steps[{text≤60, slide_no|null}]`(1~3개).

## 3단계 말

| 값 | 화면 글자 |
|---|---|
| `good` | 좋아요 |
| `fair` | 보통 |
| `practice` | 더 연습 |

숫자(`cpm`, `per_min`, `sec`)는 보조로만 쓴다. 판정 점수(score)는 계약에 넣지 않았다 — 화면이 점수를 그리지 않게.

## 녹화본 만들기

실 API 로 한 번 돌린 응답(예: `labs/rehearsal_flow/run.py --record <폴더>`)에서 받아쓰기 · 판정 · grounds 를 이 모양으로 옮긴다.
글자 수 상한은 폰 한 줄에 맞춘 것이라, 긴 응답은 옮길 때 줄인다(뜻은 바꾸지 않는다). 옮긴 뒤 `pytest tests/test_booth_mobile_contract.py`.

## 바뀜

- v1 (2026-10-11) — 처음.
