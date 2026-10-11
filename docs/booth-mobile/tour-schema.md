# 투어 녹화 데이터 — `data/tour/<id>.json` (v1)

원본은 [`tour.schema.json`](tour.schema.json). 이 문서는 칸마다 **화면이 무엇에 쓰는지**를 적는다. 예시는 [`demo/YEHS_demo/data/tour/_example.json`](../../demo/YEHS_demo/data/tour/_example.json).

## 화면 ↔ 칸

| 화면 | 읽는 칸 | 하는 일 |
|---|---|---|
| `#/tour/deck` | `deck` | 표지·장 그림 넘겨 보기. 「이 자료로 발표 보기」 |
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
`claim_graph{summary, root, nodes[{id, label≤120(자르지 않는다 · 화면이 접는다), kind, status, slide_no|null}], edges[{from, to}]}`.
노드 `kind`: `claim`(루트=주장 문장) · `reason` · `evidence` · `concept`. `status`: `aligned` · `justified_skip` · `missing` · `contradiction` (판정 색과 짝). 노드 12개까지.

**`qa`** — `asker`(질문하는 역할 이름표, 교수님 등), `questions[{id, slide_no, question≤120, answers{good, rough}}]` (1~5개).
답 하나: `text`, `verdict`(`good|partial|wrong|unknown`), `level`, `feedback≤240`(두 문장까지 · 자르지 않는다), `grounds[≤3]`.
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

## 목록 — `data/tour/index.json`

원본은 [`tour-index.schema.json`](tour-index.schema.json). `#/tour/deck` 이 덱 고르기 카드와 기본 덱을 투어 파일을 다 받지 않고 그린다.

```json
{ "schema": "chuckchuck.tour-index", "version": 1, "default": "delivery-rating",
  "tours": [{ "id": "delivery-rating", "label": "C-1", "title": "별점은 왜 4.7에 몰리는가", "subtitle": "…",
              "cover": "assets/deck-covers/delivery-rating.webp", "slides": 3, "duration_sec": 139.8, "questions": 2, "recorded_at": "2026-10-11" }] }
```

- `tours` 차례가 보여 줄 차례다. `default` 는 처음 열 투어(주 덱 = 부스 C-1 배달앱 별점). 형식 예시(`_example`)는 싣지 않는다.
- 제목 · 부제 · 표지 · 장 수 · 길이 · 질문 수 · 녹화 날짜는 각 투어 파일과 같아야 한다(테스트가 본다). 손으로 고치지 말고 `build.py` 로 같이 만든다.

## 녹화본 만들기

[`labs/tour_capture/`](../../labs/tour_capture/README.md) — 부스 덱 녹음을 실 API 브리지(8983)로 한 번 태워(`capture.py`) 응답을 남기고,
`build.py` 가 이 모양으로 옮긴다(과금 없음). 옮기는 규칙:

- 값은 녹화 응답에서만 온다. 글자 수 상한에 맞춰 줄일 때는 문장 · 절 경계에서 자르고 「…」 (뜻은 바꾸지 않는다).
- 3단계 말: 채점 평균 85↑ `good` · 70↑ `fair` · 그 아래 `practice`. 말 속도 300~350자/분 `good`, 255~402 `fair`(vision_cue 문턱). 군더더기 분당 2번↓ `good` · 5번↓ `fair`.
- 장 넘김은 받아쓰기 재분할 구간 그대로, 문장 한가운데면 6초 안의 문장 끝으로 옮긴다. 코칭 칩은 잰 신호(첫 말 · 말버릇 구간 · 권장보다 긴 장 · 8초 창 말 속도)만 — 음량 칩은 만들지 않는다.
- 답 판정: 「잘 답한 답」 = 부스 「정답 보기」 글(질문 골자, 함정은 서버 reveal), 「엉성한 답」 = 「대충 답해 보기」 글(`qa_live.js liveWeakAnswer` 원본). 질문마다 판정 두 번.
  `good` 이 good 이 아니거나 `rough` 가 good 인 질문, 사람이 자료와 대조해 정답이 틀린 걸 찾은 질문(`build.py EXCLUDE`)은 빼고 `source.note` 에 적는다.
- 판정기의 알려진 오류는 **지우기만** 한다: 엉성한 답에서 답에 없는 숫자 줄을 「짚은 것」 으로 한 근거 · 답이 말한 숫자 줄을 「빠진 것」 으로 한 근거 · 답에 없는 숫자를 들어 칭찬한 반응 문장(→ 다음 문장이나 되묻기).
- 세션 id · 경로 · 메일 · 키 모양 글은 거르고, 남으면 만들기가 실패한다.

## 바뀜

- v1 (2026-10-11) — 처음.
- v1 + 목록(2026-10-11, lab/tour-fixtures-1011) — `index.json`(tour-index.schema.json) 추가. 투어 파일 모양은 그대로.
