<!-- 이 파일: ours 스키마(SlideDoc/Transcript/ConceptDoc 등)와 벤더 매핑 문서입니다. -->

# 척척발표 · 스키마 계약서

팀 공유용. **벤더 원본(raw)** 과 **우리가 후처리한 계약(ours)** 을 기능별로 정리한다.

- F-01 / F-06 **Document Parse 후처리 합의안:** [`DOCUMENT_PARSE_POSTPROCESS.md`](./DOCUMENT_PARSE_POSTPROCESS.md)
- 모듈 간 결합은 **ours만** 사용한다. (`chuckchuck/contracts.py`)
- 프론트 ↔ 백엔드 JSON도 ours를 그대로 쓴다.
- raw는 어댑터(`f01_parse`, `stt_impl`) 안에서만 존재하고 밖으로 새지 않는다.

```
파일 업로드 ──► [Upstage raw] ──► SlideDoc          (F-01)
맥락 입력   ──►                   Context           (F-02)
마이크+넘김 ──►                   audio + SlideMark[] (F-03·04)
audio+marks ──► [A.X STT raw] ──► Transcript        (F-05)
SlideDoc+Context(+Transcript?) ─► ConceptDoc        (F-06)
ConceptDoc(+SlideDoc) ─[LLM]──► ConceptGraph      (F-07)
ConceptGraph+Transcript ─[LLM]─► AlignmentDoc     (F-11)
```

---

## 0. 공통 규칙

| 항목 | 규칙 |
|------|------|
| 시각 단위 | **초(float)**. 밀리초 raw는 어댑터에서 `/1000` |
| 슬라이드 번호 | **1부터** |
| 재방문 | 같은 `slide_no` + 다른 `visit` |
| JSON | 모든 ours 타입은 `to_dict()` / `from_dict()` 왕복 |
| 코드 위치 | `chuckchuck/contracts.py` |

---

## 1. F-01 Document Parse

### 1-A. 원본 — Upstage Document Parse

`POST /v1/document-digitization` · `model=document-parse`

```jsonc
{
  "apiVersion": "1.1",
  "model": "document-parse-260128",
  "elements": [
    {
      "id": 1,
      "category": "heading1 | heading2 | paragraph | list | table | figure | chart | image | caption | ...",
      "page": 1,
      "content": {
        "text": "문자열",
        "html": "<p>...</p>",
        "markdown": "..."
      },
      "coordinates": [
        { "x": 0.12, "y": 0.22 },
        { "x": 0.42, "y": 0.22 },
        { "x": 0.42, "y": 0.32 },
        { "x": 0.12, "y": 0.32 }
      ]
    }
  ],
  "content": {
    "text": "문서 전체 텍스트",
    "html": "...",
    "markdown": "..."
  },
  "usage": {
    "pages": 52,
    "standard": [1, 2],
    "enhanced": [3]
  }
}
```

**우리가 버리는 것(현재 ours):** `coordinates`, 전체 `content`, `usage` 상세, `html`(블록 단위 text 우선).

**raw 확보(스키마 실측):**

```bash
python examples/dump_parse_raw.py /path/to/deck.pdf
# → fixtures/raw/*.upstage.json  (벤더 원본)
# → fixtures/raw/*.keys.json     (키·category 인벤토리)
# → fixtures/raw/*.slidedoc.json (현재 ours)
```

`coordinates=true` 로 덤프한다. 후처리 필드는 **keys.json에 실제로 있는 키만** 계약에 올린다.

**매핑:**

| Upstage | → ours |
|---------|--------|
| `elements[].page` | `Slide.slide_no` |
| `elements[].category` | `SlideBlock.category` |
| `elements[].content.text` (fallback: markdown → html) | `SlideBlock.text` |
| heading1/heading2/title 중 첫 텍스트 | `Slide.title` |
| 글자 수 < 20 | `text_sparse=true` |
| sparse + figure/chart/image 존재 | `image_only=true` |
| page별 그룹 개수 | `SlideDoc.total_slides` |

### 1-B. 후처리 — `SlideDoc`

```jsonc
{
  "file_name": "(최종)RINGLE 마케팅 공모전 PPT_SAIGHT.pdf",
  "total_slides": 10,
  "slides": [
    {
      "slide_no": 1,
      "title": "자사 분석",
      "blocks": [
        { "category": "heading1", "text": "자사 분석" },
        { "category": "paragraph", "text": "일하는 사람을 위한 영어..." }
      ],
      "text_sparse": false,
      "image_only": false,
      "raw_text": "자사 분석\n일하는 사람을 위한 영어..."
    }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `file_name` | string | 원본 파일명 |
| `total_slides` | int | 텍스트 element가 있는 페이지 수 |
| `slides[].slide_no` | int | 1..N |
| `slides[].title` | string | 없으면 `""` |
| `slides[].blocks[]` | `{category, text}` | 레이아웃 블록 |
| `slides[].text_sparse` | bool | F-06/프론트 경고용 |
| `slides[].image_only` | bool | 도식 위주 |
| `slides[].raw_text` | string | blocks 이어붙인 통짜 (직렬화 시 포함) |

코드: `f01_parse.parse_document()` → `SlideDoc`

---

## 2. F-02 발표 맥락

### 원본
프론트 폼 / 프리셋 칩. 벤더 API 없음.

### 후처리 — `Context`

```jsonc
{
  "situation": "대회·IR 피칭",
  "audience": "심사위원",
  "duration_min": 5
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `situation` | string | 발표 상황 (빈 값 허용 → 범용) |
| `audience` | string | 청중 |
| `duration_min` | int \| null | 예정 분 |

---

## 3. F-03 · F-04 녹음 + 슬라이드 전환

### 원본
브라우저 `MediaRecorder` blob + 클릭 이벤트. 벤더 API 없음.

### 후처리

**오디오:** `Blob` / 파일 (`audio/webm` 또는 `audio/mp4`)  
**마크:** `SlideMark[]`

```jsonc
[
  { "slide_no": 1, "start_sec": 0.0,  "end_sec": 12.4, "visit": 1 },
  { "slide_no": 2, "start_sec": 12.4, "end_sec": 28.1, "visit": 1 },
  { "slide_no": 1, "start_sec": 28.1, "end_sec": 35.0, "visit": 2 }
]
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `slide_no` | int | 보고 있던 장 |
| `start_sec` | float | 녹음 시작=0 기준 |
| `end_sec` | float | 다음 전환 또는 종료 |
| `visit` | int | 그 장의 n번째 방문 (1부터) |

화면 로그 문자열(참고용, 계약 아님):  
`02:04 → 4번 슬라이드` / `02:57 ↩ 2번 슬라이드 (2번째 방문)`

코드: `sdk/rehearsal-recorder.js` → `{ audioBlob, marks }`

---

## 4. F-05 STT + 슬라이드별 발화

### 4-A. 원본 — SKT A.X STT (batch)

흐름: `upload-token` → `upload` → `POST /v1/stt/transcript`  
인증: **`X-API-Key`** (LLM Bearer와 다름)  
모델: `A.X_STT_note_batch`

```jsonc
{
  "message_id": "probe-0d0ab8ddb6",
  "audio_duration": 2205,          // ms
  "transcript_duration": 2.20594,  // sec
  "utterance_count": 1,
  "utterances": [
    {
      "text": "안녕하세요 발표 테스트입니다",
      "start": 0.0,
      "end": 0.0,
      "start_time": 0.0,
      "end_time": 2.18,
      "words": [
        {
          "text": "안녕하세요",
          "start": 0.0,
          "end": 0.0,
          "start_time": 0.121111,   // ← 실제 사용
          "end_time": 0.847778,     // ← 실제 사용
          "speaker": 1
        }
      ]
    }
  ]
}
```

**매핑:**

| A.X | → ours |
|-----|--------|
| `utterances[].words[].text` | `Word.text` |
| `utterances[].words[].start_time` | `Word.start_sec` |
| `utterances[].words[].end_time` | `Word.end_sec` |
| (words 없으면) utterance text + start/end_time | Word 1개로 근사 |
| `SlideMark[]` + words | `Transcript.by_slide` |

`start`/`end` 필드는 0으로 오는 경우가 있어 **`start_time`/`end_time`만 신뢰**.

### 4-B. 후처리 — `Transcript`

```jsonc
{
  "full_text": "안녕하세요 제 이름은 김효정입니다 ...",
  "provider": "skt-ax",
  "duration_sec": 43.58,
  "words": [
    { "text": "안녕하세요", "start_sec": 1.571, "end_sec": 2.333 }
  ],
  "by_slide": [
    {
      "slide_no": 1,
      "visit": 1,
      "start_sec": 0.0,
      "end_sec": 10.9,
      "text": "안녕하세요 제 이름은 ...",
      "words": [ /* 이 구간에 속한 Word[] */ ]
    }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `full_text` | string | 전체 인식 문장 |
| `words[]` | Word | 단어별 시각 — **F-17 필수** |
| `by_slide[]` | SlideSpeech | 마크 기준 분할 |
| `provider` | string | `skt-ax` \| `mock` … |
| `duration_sec` | float | 마지막 단어 end |

**분할 규칙:** 문장 시작 시점의 슬라이드에 문장 전체를 귀속. 중간 넘김으로 문장을 자르지 않음.

코드: `f05_stt.transcribe()` → `Transcript`

---

## 5. F-06 개념 추출

### 5-A. 원본 — LLM (Solar / A.X …)

프롬프트로 JSON만 요청. 벤더 chat completions 응답의 `message.content` 문자열.

기대 raw(모델 출력):

```jsonc
{
  "slides": [
    {
      "slide_no": 1,
      "title": "...",
      "topic": "한 줄 주제",
      "keywords": ["키워드1", "키워드2"],
      "concepts": ["개념명: 한 줄 설명"],
      "importance": "core | support"
    }
  ]
}
```

### 5-B. 후처리 — `ConceptDoc`

입력: `SlideDoc` + `Context` (+ 선택 `Transcript` → sparse 보완)  
출력:

```jsonc
{
  "file_name": "...",
  "total_slides": 5,
  "model": "solar",
  "slides": [
    {
      "slide_no": 1,
      "title": "...",
      "topic": "경쟁사와 차별화된 링글의 직군 중심 마케팅 전략",
      "keywords": ["난이도 중심", "직군 중심"],
      "concepts": [
        "직군 중심 타겟팅: 직장인 집단 내 초·중·고급 실력 혼재"
      ],
      "raw_text": "(SlideDoc에서 복사한 원문)",
      "importance": "core"
    }
  ]
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `model` | string | 사용한 LLM 이름 |
| `slides[].topic` | string | 슬라이드 한 줄 요약 |
| `slides[].keywords` | string[] | 키워드 |
| `slides[].concepts` | string[] | `"이름: 설명"` 형식 |
| `slides[].importance` | `"core"`\|`"support"` | 맥락 가중 |
| `slides[].raw_text` | string | 근거 대조용 원문 보존 |
| `slides[].missing` | `true` \| (키 없음) | (09-30 G-A8) 모델이 이 장의 개념을 **두 번 물어도** 안 돌려줬다 — `concepts` 가 빈 것은 「개념 없는 장」 이 아니라 「못 받은 장」 이다. 거짓이면 키가 없다(옛 캐시·저장본 모양 그대로). 화면: 그 장에 「개념을 못 받았어요 — 다시 분석하면 채워요」. 빠진 장이 `MISSING_MAX`(2)장을 넘고 전체의 25%(`MISSING_SHARE_MAX`)도 넘으면 결과 대신 502 `concepts_incomplete` 다 (§10-E) |

**안 함:** 부모-자식 트리 → **F-07 책임**

`POST /api/v1/concepts` 는 빠진 장이 있으면 ConceptDoc 에 `degraded: ["concepts_missing"]` · `degraded_notes` · `missing_slides`(장 번호)를
더해 돌려주고 단계 캐시에 담지 않는다 — 다음 분석이 그 장을 다시 받는다. 온전하면 응답 모양이 예전과 같다(세 키 없음).

코드: `f06_concepts.extract_concepts()` → `ConceptDoc`

---

## 6. F-07 개념 그래프

**책임 한 줄:** 장 단위 개념(`ConceptDoc`)을 발표 **전체** 기준으로 묶어
**우선순위(weight) + 연결선(edges) + 구획(sections)** 을 만든다.

F-06과의 경계: F-06은 "이 장 안에 뭐가 있나", F-07은 "장들이 전체에서 어디에 앉나".
`section` / `slide_role`은 앞뒤 장을 함께 봐야 정해지므로 F-07 책임이다
([`DOCUMENT_PARSE_POSTPROCESS.md` §3-4](./DOCUMENT_PARSE_POSTPROCESS.md)).

**왜 트리가 아니라 그래프인가.** 개념은 부모가 하나라는 보장이 없다.
"CAFP 분석"은 *링글 AI 서비스*와 *데이터 자산* 양쪽에 걸린다. 트리는 이걸 못 적는다.
그래서 `edges`를 진실로 두고, `parent` 간선만 따라간 결과를 트리 뷰로 쓴다.

**F-07이 안 하는 것 — 발화 축.** F-07은 `Transcript`를 받지 않는다.
발화 시간·반복·강조에서 나오는 `speech_weight`와 정합 4-class(정합·정당생략·누락·모순)는
발화가 있어야 나오므로 뒤 단계(F-11) 책임이다. 조인은 `node.id`로 한다.

```
F-07  ConceptDoc(+SlideDoc)      → ConceptGraph    (슬라이드 축 weight + 연결선)
F-11  ConceptGraph + Transcript  → AlignmentDoc    (발화 축 + 4-class, §7)
                                     ↑ node_id 로 조인
```

### 6-A. 원본 — LLM (Solar / A.X …)

`ConceptDoc` 전체를 한 번에 보여주고 JSON만 요청한다. 배치로 쪼개지 않는다 —
위계는 전역 시야가 있어야 정해지고, 배치로 나누면 배치 경계에서 연결선을 잃는다.

기대 raw(모델 출력):

```jsonc
{
  "nodes": [
    { "id": "contrast", "label": "Contrastive Learning",
      "slide_nos": [4], "summary": "한 줄 설명", "importance": "core" }
  ],
  "edges": [
    { "from": "contrast", "to": "joint",   "kind": "parent"  },
    { "from": "joint",    "to": "encoder", "kind": "relates" }
  ],
  "sections": [
    { "name": "서론 — 배경 개념", "slide_role": "intro", "slide_nos": [1, 2, 3] }
  ]
}
```

모델이 준 `depth`·`parent_id`는 신뢰하지 않는다. **`edges`에서 다시 계산**한다.

프롬프트 주의(실측 근거): 슬라이드 단위로 나열해 보여 주면 모델이
"슬라이드 1개 = 노드 1개"로 옮겨 적고 연결선을 만들지 않는다.
그래서 **개념 풀을 앞에, 슬라이드 흐름은 sections 참고용으로 뒤에** 둔다.

### 6-B. 후처리 — `ConceptGraph`

입력: `ConceptDoc` (+ 선택 `Context`, + 선택 `SlideDoc` → weight 정밀화)
출력:

```jsonc
{
  "file_name": "250729 IMU2CLIP_Pulbic.pdf",
  "total_slides": 23,
  "model": "solar",
  "nodes": [
    {
      "id": "contrast",
      "label": "Contrastive Learning",
      "slide_nos": [4],
      "summary": "같은 데이터는 가깝게, 다른 데이터는 멀게 학습",
      "importance": "core",
      "weight": 1.0,
      "weight_basis": { "slide_count": 1, "char_share": 0.081,
                        "has_visual": true, "position": "early",
                        "mention_count": 4, "title_hit": true },
      "parent_id": null,
      "depth": 1
    },
    {
      "id": "joint",
      "label": "공동 임베딩 정렬",
      "slide_nos": [7, 8],
      "summary": "세 모달리티를 하나의 임베딩 공간에 정렬",
      "importance": "core",
      "weight": 0.79,
      "weight_basis": { "slide_count": 2, "char_share": 0.142,
                        "has_visual": false, "position": "middle",
                        "mention_count": 2, "title_hit": false },
      "parent_id": "contrast",
      "depth": 2
    }
  ],
  "edges": [
    { "from": "contrast", "to": "joint",   "kind": "parent"  },
    { "from": "joint",    "to": "encoder", "kind": "relates" }
  ],
  "sections": [
    { "name": "서론 — 배경 개념", "slide_role": "intro", "slide_nos": [1, 2, 3, 4, 5] },
    { "name": "본론 — 제안 방법", "slide_role": "body",  "slide_nos": [6, 7, 8, 9, 10, 11, 12] }
  ]
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `file_name` | string | ✅ | `ConceptDoc`에서 승계 |
| `total_slides` | int | ✅ | 同上 |
| `model` | string | ✅ | 사용한 LLM 이름 |
| `nodes[].id` | string | ✅ | **안정 키**. 영소문자·숫자·`-`. 그래프 안에서 유일 |
| `nodes[].label` | string | ✅ | 개념 이름 (화면 표시용) |
| `nodes[].slide_nos` | int[] | ✅ | **조인 키**. 개념 하나가 여러 장에 걸칠 수 있어 배열 |
| `nodes[].summary` | string | ✅ | 한 줄 설명. 없으면 `""` |
| `nodes[].importance` | `"core"`\|`"support"` | ✅ | 근거 슬라이드의 `ConceptDoc.importance`에서 승계 |
| `nodes[].weight` | float | ✅ | 0.0~1.0. **그래프 안에서 상대적** — 최상위 개념이 1.0 |
| `nodes[].weight_basis` | object | ✅ | weight 근거. 아래 6-C |
| `nodes[].parent_id` | string \| null | ✅ | **파생** — 첫 `parent` 간선. 루트면 `null` |
| `nodes[].depth` | int | ✅ | **파생** — 루트=1. `parent` 체인 길이 |
| `edges[].from` | string | ✅ | 상위(또는 출발) 개념 `id` |
| `edges[].to` | string | ✅ | 하위(또는 도착) 개념 `id` |
| `edges[].kind` | `"parent"`\|`"relates"` | ✅ | `parent`=위계, `relates`=그 밖의 논리 연결 |
| `sections[].name` | string | ✅ | 구획 이름 (예: `"본론 — 제안 방법"`) |
| `sections[].slide_role` | enum | ✅ | `cover`\|`intro`\|`body`\|`conclusion`\|`closing` |
| `sections[].slide_nos` | int[] | ✅ | 이 구획에 속한 장 번호 |
| `thesis` | string | — | (09-30 G-A17) 모델이 고른 **발표 주제 노드의 `id`** (문장이 아니다). 루트(`parent_id` null)일 때만 남고, 모르면 키가 없다. F-08 주제 자리(theme)·F-26 탐침이 「가장 무거운 루트」 를 짐작하지 않게 쓴다. 화면: 있으면 그 노드를 주제로 강조, 없으면 예전처럼 weight 1.0 루트 |
| `degraded` | string[] | — | (09-30 G-A30) 만들다 떨어진 단계 이름. 지금 값은 `links` 하나(연결 보강 LLM 실패 → 처음 그린 연결로 그래프를 만듦). 비면 키가 없다. 이런 그래프는 단계 캐시에 담지 않는다 — 다시 분석하면 채울 수 있다. 화면: `/graph` 응답의 `degraded_notes` 를 한 줄로 (§10-E) |

`thesis`·`degraded` 는 **값이 있을 때만** 직렬화한다 — 옛 그래프 캐시·저장본과 모양이 같다. `POST /api/v1/graph` 는 `degraded` 가
있으면 `degraded_notes` 를 더해 돌려준다. 노드를 하나도 못 만들면 그래프 대신 502 `graph_empty` 다 (§10-E).

**보증(어댑터가 지키는 불변식):**

1. `id`는 유일하다.
2. 간선 양끝은 존재하는 `id`다. 없는 id를 가리키는 간선은 버린다.
3. 자기 자신을 가리키는 간선은 버린다. 같은 `(from, to)`는 한 번만 남는다.
4. 노드당 `parent` 간선은 **최대 1개**. 둘째 부모는 `relates`로 내려 정보를 보존한다.
5. `parent` 순환이 없다. 순환이 생기면 그 고리를 끊는다.
6. `depth`는 `parent` 체인 길이와 항상 일치하고, **3을 넘지 않는다**(넘으면 상위로 끌어올림).
7. `parent_id`와 `edges`는 어긋날 수 없다 — `edges`에서 되짚어 만든다.
8. `slide_nos`는 `1..total_slides` 안의 값만 남는다.
9. `sections[].slide_role`은 enum 밖이면 `body`, `edges[].kind`는 enum 밖이면 `relates`로 떨어진다.
10. 노드가 2개 이상인데 간선이 0개면 **한 번 재요청**한다(실측: Solar가 이런 응답을 준 실행이 있었다).
    재요청도 비면 1차 결과를 쓴다 — 실패로 만들지 않는다.
11. 루트(부모 없는 노드)는 **4개를 넘지 않는다**(실측: 28개 중 13개가 루트로 떠서 여전히 평평했다).
    넘으면 weight 상위만 루트로 남기고, 나머지는 ① relates 이웃 → ② 슬라이드 겹침 →
    ③ 최고 weight 순으로 고른 루트 밑에 `parent`로 붙인다. 이때 위계로 승격된 쌍과
    같은 방향의 relates 는 지워 3번(중복 없음)을 지킨다. 붙인 뒤 depth·weight 는 재계산한다.

### 6-C. `weight` 와 `weight_basis`

`weight` = 슬라이드가 그 개념에 **배분한 양**. 발화 우선순위와 나란히 놓고 비교하는 축이다.

배합 (합 1.0, 여기서 깊이 감점 `0.05 × (depth-1)`):

| 성분 | 비중 | 출처 |
|------|------|------|
| `importance` (core=1.0, support=0.35) | 0.18 | `ConceptDoc` |
| 걸친 장 수 / `total_slides` | 0.30 | `slide_nos` |
| 그 장들의 글자 비중 | 0.25 | `SlideDoc.total_char_count` |
| 시각자료 유무 | 0.10 | `SlideDoc.has_visual` |
| 언급 빈도 / 그래프 내 최댓값 | 0.12 | `ConceptDoc` 개념·키워드 목록 |
| 장 제목 등장 유무 | 0.05 | `ConceptDoc.slides[].title` |

계산 후 **최댓값으로 나눠 정규화**한다. 절대값보다 서열이 목적이라서다.

언급 빈도·제목 등장은 **개념 단위** 신호다. `slide_nos`가 같은 개념들은
장 수·글자 비중·도식이 전부 같아져 동률이 났는데(실측: 0.779가 4개),
같은 장 안에서도 개념마다 다른 이 두 신호가 서열을 가른다.

| `weight_basis` | 타입 | 설명 |
|------|------|------|
| `slide_count` | int | 걸친 장 수 |
| `char_share` | float | 근거 장들의 본문 글자 수 / 전체 글자 수 |
| `has_visual` | bool | 근거 장에 도식·표·차트가 있나 |
| `position` | `early`\|`middle`\|`late` | 처음 등장하는 위치 |
| `mention_count` | int | 문서 전체 개념·키워드 목록에서 언급된 횟수 |
| `title_hit` | bool | 근거 장 제목에 이 개념이 등장하나 |

`slide_doc`을 안 주면 `char_share=0.0`, `has_visual=false`로 남고 weight가 거칠어진다.
`ConceptDoc`에는 밀도 신호가 없어서 `SlideDoc`이 필요하다 — 형제 모듈 호출이 아니라
서버가 이미 갖고 있는 F-01 산출물을 같이 넘기는 것이다.

**안 함:** 개념별 이해 판정·confidence·근거 발화·발화 시간 → **F-11 책임**.
F-07은 골격과 슬라이드 축만 만들고, 나머지는 뒤 단계가 `id`로 붙인다.

코드: `f07_graph.build_graph()` → `ConceptGraph`

---

## 7. F-11 정합 판정

**책임 한 줄:** 발화(`Transcript`)가 개념 그래프(`ConceptGraph`)의 각 개념을
얼마나 잘 다뤘는지 **발화 축(speech_weight) + 4-class 판정 + 발화 간선**으로 만든다.

**왜 발화 그래프를 따로 안 뽑나.** 같은 입력으로도 LLM 그래프 추출은 실행마다
구조가 흔들린다 (F-07 실측: 노드 10/34/21). 발화 그래프를 독립 추출해 문서
그래프와 비교하면 추출 분산이 두 배가 되어 **diff 가 발표 실력이 아니라 노이즈를
측정**하게 된다. 그래서 문서 그래프를 기준축으로 두고, 발화 개념 추출을 노드
목록에 **조건화**한다 — LLM 에 노드 목록을 후보 앵커로 주고 `node_id` 로 조인해
돌려받는다. 노드 정렬(같은 개념, 다른 이름) 문제가 구조적으로 사라진다.

**역할 분담이 핵심이다:**
- `speech_weight` 와 그 근거(`speech_basis`)는 **코드가 결정적으로 계산**한다
  (marks 기반 발화 시간 + 토큰 매칭 언급 횟수). LLM 이 아니라서 실행마다 같다.
- LLM 은 코드가 못 하는 것만 맡는다: 4-class 판정, 근거 인용, 발화 간선
  (말로 연결했나), 발화 전용 개념.

### 7-A. 원본 — LLM (Solar / A.X …)

노드 목록을 앞에, 슬라이드별 발화를 뒤에 두고 JSON 만 요청한다
(F-07 교훈 재적용 — 판정 대상을 앞에 둬야 발화를 개념에 매핑한다).

기대 raw(모델 출력):

```jsonc
{
  "items": [
    { "node_id": "contrast", "verdict": "aligned",
      "evidence": "그래서 대조 학습으로 두 모달리티를 정렬합니다",
      "note": "슬라이드 4의 핵심을 그대로 설명" }
  ],
  "speech_edges": [
    { "from": "contrast", "to": "joint", "cue": "이걸 바탕으로 공동 임베딩을 만들면" }
  ],
  "extra_concepts": [
    { "label": "온도 파라미터", "quote": "온도를 낮추면 hard negative 에 민감해지는데", "slide_no": 4 }
  ]
}
```

`verdict` 는 넷 중 하나:

| verdict | 뜻 |
|---|---|
| `aligned` | 정합 — 발화가 개념을 설명했고 자료와 부합 |
| `justified_skip` | 정당생략 — 안 다뤘지만 생략이 합리적 (보조 개념 등) |
| `missing` | 누락 — 다뤘어야 하는데 발화에 없음 |
| `contradiction` | 모순 — 발화가 자료와 어긋남 (evidence 필수) |

### 7-B. 후처리 — `AlignmentDoc`

입력: `ConceptGraph` + `Transcript` (+ 선택 `Context`, + 선택 `SlideDoc`·F-04 `marks_match` — 09-30 부터. 브리지는 둘 다
요청 본문이 아니라 세션 보관소에서 `session_id` 로 찾는다)
출력:

```jsonc
{
  "file_name": "250729 IMU2CLIP_Pulbic.pdf",
  "total_slides": 23,
  "model": "solar",
  "items": [
    {
      "node_id": "contrast",
      "verdict": "aligned",
      "speech_weight": 1.0,
      "speech_basis": { "speech_sec": 42.5, "time_share": 0.18,
                        "mention_count": 4, "mentioned_slide_count": 1,
                        "first_mention_sec": 61.2 },
      "doc_weight": 1.0,
      "evidence": "그래서 대조 학습으로 두 모달리티를 정렬합니다",
      "note": "슬라이드 4의 핵심을 그대로 설명"
    }
  ],
  "speech_edges": [
    { "from": "contrast", "to": "joint",
      "cue": "이걸 바탕으로 공동 임베딩을 만들면", "in_graph": true }
  ],
  "extra_concepts": [
    { "label": "온도 파라미터", "quote": "온도를 낮추면 ...", "slide_no": 4 }
  ],
  "summary": {
    "coverage": 0.84,
    "rank_correlation": 0.71,
    "edge_coverage": 0.4,
    "verdict_counts": { "aligned": 21, "justified_skip": 3, "missing": 3, "contradiction": 1 },
    "speech_total_sec": 312.4
  }
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `items[].node_id` | string | ✅ | **조인 키** — `ConceptGraph.nodes[].id` |
| `items[].verdict` | enum | ✅ | 위 4-class |
| `items[].speech_weight` | float | ✅ | 0.0~1.0. **그래프 안에서 상대적** — 최상위 = 1.0. 코드 계산 |
| `items[].speech_basis` | object | ✅ | speech_weight 근거. 아래 7-C |
| `items[].doc_weight` | float | ✅ | **파생** — 해당 노드의 F-07 `weight` 복사 (산점도 편의) |
| `items[].evidence` | string | ✅ | 판정 근거 발화 인용. 없으면 `""` |
| `items[].note` | string | ✅ | LLM 한 줄 설명. 없으면 `""` |
| `speech_edges[].from` / `to` | string | ✅ | 발표자가 **말로** 연결한 개념 쌍 |
| `speech_edges[].cue` | string | ✅ | 연결을 보여 준 발화 인용 |
| `speech_edges[].in_graph` | bool | ✅ | **파생** — 문서 간선에도 있는 연결인가 (방향 무시) |
| `extra_concepts[].label` | string | ✅ | 발화에만 나온 개념 |
| `extra_concepts[].quote` | string | ✅ | 발화 인용 |
| `extra_concepts[].slide_no` | int \| null | ✅ | 언급 시점의 장. 범위 밖이면 null |
| `summary` | object | ✅ | 아래 7-D. 전부 코드 계산 |
| `items[].decided_by` | enum | ✅ | `llm` LLM 판정 그대로 · `code` 코드가 까닭을 대고 바꿈(모순·건너뛴 장·말한 문장) · `fallback` **LLM 판정이 없어** 언급 횟수로 짐작 (09-30) |
| `items[].deck_quote` | string | ✅ | 코드가 잡은 모순의 **자료 쪽** 인용 (발화 쪽은 `evidence`). 비면 코드가 확인한 모순이 아니다 |
| `items[].deck_slide_no` | int \| null | ✅ | `deck_quote` 의 장 |
| `speech_match` | enum | ✅ | `matched` · `unrelated`(녹음이 이 자료의 발표가 아님 — 판정하지 않음). F-04 와 같은 겹침 문턱 |
| `speech_overlap` | float \| null | ✅ | 발화 낱말 중 자료에도 있는 비중(IDF 가중). `speech_match` 를 가른 수 |
| `basis` | enum | ✅ | `llm` 정상 · `fallback` LLM 이 두 번 다 판정을 비워 전 노드가 짐작 · `skipped` 다른 발표라 판정 안 함 |
| `skipped_slides[]` | object | ✅ | 말로 건너뛴 장 `{slide_no, cue(발화 원문), node_ids(그 장 개념 중 끝내 missing)}` |

**읽는 순서 (09-30 held-out C-06·C-07 · 레드팀 G-A22):** 판정을 쓰기 전에 `basis`·`speech_match` 를 본다.
`basis != "llm"` 이거나 `speech_match == "unrelated"` 면 item 의 missing 은 「안 말했다」 는 확인이 아니다
(`AlignmentDoc.speech_usable` 이 둘을 묶는다). `decided_by == "fallback"` 인 item 하나하나도 같다.
질문(F-08)은 `speech_usable` 이 거짓이면 발화·정합 근거 없이 자료만으로 묻는다.

**화면이 할 일 (09-30, 새 칸은 전부 `to_dict` 에 언제나 있다 — 옛 저장본을 읽으면 `matched`·`llm`·`[]`·`""`·null):**
- `speech_match == "unrelated"` → 산점도·누락 목록 대신 「녹음이 이 자료의 발표가 아니에요」 한 줄. 누락 개수를 세지 않는다.
- `basis == "fallback"` 이거나 item 의 `decided_by == "fallback"` → 「누락」 을 확정으로 쓰지 않는다(「AI 판정 없이 언급 횟수로 짐작」).
- `contradiction` 인 item 에 `deck_quote` 가 있으면 자료 쪽 인용(`deck_slide_no` 장)과 발화 인용(`evidence`)을 나란히 보인다.
- `skipped_slides[]` → 「N장을 말로 건너뛰었어요: «cue»」 + 그 장에서 끝내 missing 인 개념(`node_ids`) 칩. 비면 안 그린다.
- `speech_overlap` 은 못 쟀으면 null — 숫자를 화면에 낼 일은 없다(판정 근거 로그용).

**LLM 뒤 코드 대조 (`_align_checks`, 순서가 뜻이다):**
1. 인용은 **한 장 구간 안의 이어진 문장**만 — 두 구간을 이어 붙이지 않는다. 건너뛰기(「시간 관계상 그냥 넘어갈게요」)·
   미루기(「나중에 설명할게요」) 말과 **자료 글을 옮긴** 인용은 근거가 아니다.
2. `missing`·`justified_skip` 인데 개념 이름 + 그 개념 자료 줄의 다른 낱말·수(값+단위)를 같이 말한 문장이 있으면 `aligned`.
3. 말로 건너뛴 장의 개념은 다른 문장이 이름을 불러 설명하지 않았으면 `missing` (가벼운 개념의 정당생략은 존중).
4. 발화의 숫자·방향이 자료 원문과 어긋나면 `contradiction` (`_deck_claims.conflicts` — 받아쓰기의 「49퍼센트」「이십구 프로」 는
   먼저 「49%」「29%」 로). 반올림·어림(약·정도, 15%) 은 같은 수다. 자료 원문(`slide_doc`)이 없으면 이 대조는 건너뛴다.

**보증(어댑터가 지키는 불변식):**

1. 그래프의 **모든 노드에 item 이 정확히 1개**다. LLM 이 빠뜨린 노드는 결정적
   폴백(발화에 언급 있으면 `aligned`, 없으면 `missing`)으로 채운다.
   같은 `node_id` 가 여러 번 오면 첫 번째만 남는다.
2. 없는 `node_id` 를 가리키는 판정은 버린다.
3. `verdict` 가 enum 밖이면 결정적 폴백으로 대체한다.
4. **`missing` 은 결정적 신호와 모순될 수 없다** — label 이 발화에 실제
   등장하면(mention_count ≥ 1) `aligned` 로 정정한다.
5. **evidence 없는 `contradiction` 은 내보내지 않는다** — 결정적 폴백으로 강등.
   "틀렸다"고 말하는 판정이라 근거 없이는 오탐 비용이 크다.
6. `speech_edges` 는 양끝이 존재하는 id 만, 자기 간선 금지, 방향 무시 중복 제거.
   `in_graph` 는 문서 간선과 대조해 파생한다.
7. `extra_concepts` 는 기존 노드 label 과 토큰 일치하면 버린다(이미 있는 개념).
   빈 label 은 버리고, `slide_no` 는 범위 검증한다.
8. `speech_weight` 는 0~1, 그래프 내 최댓값으로 정규화한다.
9. JSON 파싱 실패는 1회 재요청, 두 번째도 깨지면 `AlignError`.
10. `items` 가 통째로 비면 1회 재요청, 그래도 비면 전 노드 결정적 폴백으로 간다.
11. `Transcript` 가 비어 있으면(`by_slide` 없음 + `full_text` 없음) `AlignError`.

### 7-C. `speech_weight` 와 `speech_basis`

`speech_weight` = 발화가 그 개념에 **배분한 양**. F-07 `weight`(슬라이드 축)와
나란히 놓고 비교하는 축이다. **전부 결정적 계산** — LLM 실행마다 흔들리지 않는다.

배합 (합 1.0, 계산 후 최댓값으로 나눠 정규화):

| 성분 | 비중 | 출처 |
|------|------|------|
| 근거 장 발화 시간 / 전체 발화 시간 | 0.45 | `Transcript.by_slide` (marks 기반) |
| 발화 내 언급 횟수 / 그래프 내 최댓값 | 0.35 | label 토큰 매칭 (F-07 과 동일 규칙) |
| label 이 언급된 근거 장 수 / 근거 장 수 | 0.20 | `by_slide` 텍스트 |

| `speech_basis` | 타입 | 설명 |
|------|------|------|
| `speech_sec` | float | 근거 장 발화 시간 합 (재방문 포함) |
| `time_share` | float | / 전체 발화 시간 |
| `mention_count` | int | 발화 전체에서 label 언급 횟수 |
| `mentioned_slide_count` | int | 근거 장 중 label 이 실제 언급된 장 수 |
| `first_mention_sec` | float \| null | 첫 언급 시각. `words` 없으면 null |

### 7-D. `summary` — 발표 점수의 재료

| 필드 | 계산 | 읽는 법 |
|------|------|---------|
| `coverage` | Σ doc_weight(aligned) / Σ doc_weight(정당생략 제외 전체) | 중요 개념을 빼먹을수록 크게 깎인다 |
| `rank_correlation` | doc_weight vs speech_weight 의 Spearman. 동률 전부·표본 <2 면 null | 슬라이드가 힘준 순서대로 말했나 (산점도 요약) |
| `edge_coverage` | 문서 간선 중 발화 간선과 겹치는 비율 (방향 무시). 간선 0 이면 null | 개념을 각각 말했어도 연결을 안 지었으면 낮다 |
| `verdict_counts` | 4-class 별 개수 | diff 뷰 헤더 |
| `speech_total_sec` | 전체 발화 시간 | |

**안 함:** 발표 점수 산식(coverage·rank·edge 를 어떻게 합칠지)은 프론트/기획
결정 사항이라 여기서 정하지 않는다. F-11 은 재료만 만든다.

코드: `f11_align.align_speech()` → `AlignmentDoc`

### 7-E. FlowDiff — 자료 흐름 vs 발표 흐름 (F-11 파생)

**책임 한 줄:** 자료 흐름(슬라이드 순)과 발표 흐름(첫 언급 순)을 같은 `node_id`
축에서 비교해 **흐름 차원 판정 3종**을 만든다. `ConceptGraph + AlignmentDoc →
FlowDiff`, **LLM 호출 없는 순수 함수**다 — 같은 입력이면 언제나 같은 출력.

```jsonc
{
  "file_name": "IMU2CLIP_sample.pdf",
  "steps": [
    { "node_id": "s1", "doc_order": 1, "speech_order": 2, "first_mention_sec": 8.4 },
    { "node_id": "s5", "doc_order": 5, "speech_order": null, "first_mention_sec": null }
  ],
  "issues": [
    { "kind": "order_jump", "node_ids": ["s1", "s3"], "cue": "",
      "slide_nos": [1, 3], "note": "'Contrastive Learning' 을(를) 상위 개념 … 먼저 말했어요" },
    { "kind": "good_link", "node_ids": ["s1", "s2"], "cue": "그래서 이어서 설명하면",
      "slide_nos": [1, 2], "note": "… 말로 잘 이었어요" }
  ],
  "order_tau": 0.333,
  "spoken_node_count": 4,
  "ghost_node_ids": ["s5"],
  "extra_labels": ["Temperature Parameter"]
}
```

| `issues[].kind` | 정의 (전부 결정적 — LLM 아님) |
|------|------|
| `missing_link` | 문서 간선의 두 개념을 각각 말했는데(`mention_count ≥ 1`) `speech_edges` 에 그 쌍이 없다 (방향 무시) |
| `order_jump` | parent 간선에서 자식을 부모보다 먼저 말했다. 문서 순서(`doc_order`)도 부모가 앞일 때만 |
| `good_link` | `speech_edges` 중 `in_graph=true` — 발화 인용(`cue`)이 있어야 칭찬한다 |

**보증 (불변식):** ① steps 는 그래프의 모든 노드 정확히 1개씩 ② `speech_order` 는
`first_mention_sec` 있는 노드에만, 그 안에서 1..k 연속 ③ issues 의 node_id 는 전부
실존, `good_link` 는 `cue` 필수 ④ 순수 함수 — 재실행해도 결과가 같다.

| 요약 필드 | 계산 | 읽는 법 |
|------|------|---------|
| `order_tau` | `doc_order` vs `speech_order` Kendall tau (언급된 노드만, <2 면 null) | `rank_correlation` 이 **힘 배분**이라면 이건 **순서** 일치도 |
| `ghost_node_ids` | 첫 언급을 못 잡은 노드 | 발표 흐름 그림에서 유령 노드로 그린다 |
| `extra_labels` | `extra_concepts` 의 label | 발표 흐름에만 있는 개념 (점선 노드) |

**안 함:** 발화 그래프 독립 추출(§7 결정 그대로), LLM 재호출, 최종 점수 합산.

코드: `f11_flow.build_flow_diff()` → `FlowDiff` · API: `POST /api/v1/flow`

---

## 7-F. ChatterDoc — 삐약 청중석 (F-12)

**책임 한 줄:** 국내 LLM 4개가 병아리 청중을 연기하며 발표에 대해 소곤거리는
대사를 만든다. `ConceptGraph + AlignmentDoc + FlowDiff → ChatterDoc`.

**성격은 분장이 아니라 실제 역할이다.** 각 병아리의 담당 데이터는 그 모델이
파이프라인에서 실제로 한 일에서 나온다. 심사위원에게 "국내 LLM 4개를 다 썼다"를
설명 없이 보이게 하는 장치이기도 하다.

| speaker | 배지 | 파이프라인에서 실제로 한 일 | 담당 데이터 |
|---|---|---|---|
| `solar` (쏠라) | Upstage Solar | 자료를 읽었다 (F-01 파싱, F-06/07 추출) | FlowDiff `order_jump`·`missing_link`·`order_tau` |
| `ax` (엑씨) | SKT A.X | 발표를 들었다 (F-05 STT) | `extra_concepts`, `ghost_node_ids`, 발화 시간 |
| `midm` (믿음이) | KT 믿:음 | 이름이 곧 신뢰 → 어긋남 검증 | `missing`·`contradiction`, doc−speech 격차 > 0.4 |
| `exaone` (엑사) | LG EXAONE | 'EXpert AI for everyONE' → 전문가의 인정 | `aligned` 상위, `good_link` |

**LLM 은 말투만 입힌다.** 어떤 노드를 언급할지는 `pick_talking_points()` 가
결정적으로 정하고, 그 사실 목록(fact)만 프롬프트에 넣는다. 목록 밖 `node_id` 를
가리키는 대사는 어댑터가 버린다 — 그래서 수다가 리포트와 어긋날 수 없다.

```jsonc
{
  "file_name": "발표자료.pdf",
  "total_slides": 23,
  "turns": [
    {
      "speaker": "midm",
      "text": "어... 아 맞다. '대조 학습' 얘기 안 했잖아. 흥, 나 계속 기다렸는데.",
      "mood": "grumpy",                       // grumpy|happy|curious|excited|neutral
      "refs": [ { "node_id": "contrast", "source": "alignment" } ]
    }
  ],
  "speaker_models": { "midm": "KT 믿:음", "solar": "Upstage Solar",
                      "exaone": "LG EXAONE", "ax": "SKT A.X" },
  "speaker_names":  { "midm": "믿:음", "solar": "쏠라",
                      "exaone": "엑사원", "ax": "엑씨" },
  "absent": ["exaone"]                      // 오늘 못 온 병아리 (모델 다운)
}
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `turns[].speaker` | enum | ✅ | `midm`\|`solar`\|`exaone`\|`ax`. REGISTRY 키와 동일 |
| `turns[].text` | string | ✅ | 대사. 200자 이하, 이모지 없음 |
| `turns[].mood` | enum | ✅ | 프론트 표정·모션 키. enum 밖이면 `neutral` |
| `turns[].refs[]` | `{node_id, source}` | ✅ | 근거. 비면 스몰토크. `source`=`alignment`\|`flow`\|`graph` |
| `speaker_models` | object | ✅ | 좌석 명패에 찍는 모델 배지. 화면에서 절대 숨기지 않는다 |
| `speaker_names` | object | ✅ | 병아리 이름. 모델명을 짧게 부른 것이라 명패와 어긋나지 않는다 |
| `absent` | string[] | ✅ | 오늘 못 온 speaker. 빈 배열이면 전원 출석 |

**보증(어댑터가 지키는 불변식):**

1. 네 speaker 전원이 **최소 1턴**. 모델이 죽었으면 결정적 대타 대사로 채운다
   (예: 엑사원 → "엑사원은 오늘 객석에 못 왔어요."). 청중석이 안 열리는 것보다 낫다.
   대타를 받은 speaker 가 곧 `absent` 다.

   > **`absent` 를 프론트가 추측하면 안 된다.** "refs 가 빈 대사 한 줄뿐이면 결석"
   > 같은 규칙은 틀린다 — `_ax_points` 의 애드립·발표 시간 사실과 `_solar_points` 의
   > `order_tau` 는 `node_ids` 가 원래 비어 있고, 그런 턴은 `is_smalltalk` 이라
   > `_trim` 이 제일 먼저 깎는다. 멀쩡히 일한 병아리가 '정확히 refs 없는 한 턴'만
   > 남기는 건 흔한 경로다. 결석은 `build_chatter` 만 알 수 있어서 이 필드로 싣는다.
   > UI 는 결석한 자리를 재우지 않고 **빈 좌석 + 명패**로 그린다 (UI_REDESIGN §12).
2. `refs[].node_id` 는 그 speaker 에게 **배정된 talking point 안**에만 있을 수 있다.
   밖을 가리키면 그 ref 만 떼고, 전부 떨어지면 스몰토크로 강등한다.
3. `mood` 가 enum 밖이면 `neutral`.
4. 빈 대사·200자 초과·이모지·**발표자 인신 평가 금칙어**(목소리·발음·외모 등)는 버린다.
   지적은 발표 내용에만 한다.
5. 스몰토크 비율은 20% 이하, 전체 턴은 16개 이하. 단 **각 speaker 의 마지막 한 턴은
   절대 지우지 않는다** (1번과 충돌 방지).
6. JSON 파싱 실패는 1회 재요청, 두 번째도 깨지면 그 speaker 는 대타로 간다.
7. `ConceptGraph` 에 노드가 없거나 `AlignmentDoc` 에 판정이 없으면 `ChatterError`.
8. **녹음을 판정 근거로 못 쓰면(`AlignmentDoc.speech_usable` 거짓 — 다른 발표 녹음 · 판정이 전부 짐작) LLM 을 부르지 않는다**
   (09-30 WP-S2). 넷이 정해진 말(「이 자료의 발표가 아니라 못 봤다」 류, 자료 주제 이름 하나)로 서고 `absent` 는 비어 있다 —
   부르면 없는 결함·칭찬·다른 발표의 예시 개념을 지어냈다. 쓸 수 있는 녹음에서도 `decided_by == "fallback"`(짐작) 판정은
   누락 투정·칭찬의 재료가 아니고, 코드가 확인한 모순(`deck_quote`)은 자료 쪽 줄까지 사실에 싣는다. 출력 형식 예시(「대사」)를
   베낀 대사는 버린다.

**호출 방식:** 한 라운드 안에서 네 모델을 **병렬** 호출한다(기본 2라운드).
순차로 부르면 대기가 모델 수만큼 곱해져 시연이 불가능하다. 같은 히스토리를 보고
각자 반응하는 편이 객석 웅성거림에도 더 가깝다.

`REASONING_BACKEND=mock` 이면 청중도 전부 mock 을 쓴다 — 파이프라인 나머지는 가짜인데
청중만 실제 엔드포인트로 나가는 사고를 막는다.

코드: `f12_chatter.build_chatter()` → `ChatterDoc` · API: `POST /api/v1/chatter`

---

## 8. F-08 · F-09 질문 코칭

**책임 한 줄:** 발표가 끝난 뒤 "이거 물어보면 답할 수 있나" 를 연습시킨다.
`ConceptGraph`(+선택 `AlignmentDoc`·`FlowDiff`·`Transcript`) → `QaTriage` → `QuestionDoc`,
그리고 `Question` + 답변 → `QaJudgement`.

| 입력 | 필수 | 무엇에 쓰나 |
|------|------|------|
| `ConceptGraph` | ✅ | 후보·순위·`weight`, 그리고 **`edges` 로 개념의 위치** (아래 8-B) |
| `AlignmentDoc` | 선택 | `verdict` → `source`(모순·누락), `evidence` → 발화 인용 |
| `FlowDiff` | 선택 | `issues` → `source`(`weak_flow`) |
| `Transcript.by_slide` | 선택 | 근거 장에서 **실제로 한 말** (`slide_no` 로 조인) |
| `ClaimDoc` (F-26, 09-29) | 선택 | 탐침(`tension`·`unsolved` …) → `source`·`basis.probe` (§8-I). 자료 본문(`SlideDoc`)이 있어야 만든다 |

선택 입력이 없어도 동작한다 — 녹음 없이 자료만 올린 경로에서도 질문이 나온다.

§7 과 같은 철학이다 — **어떤 개념을 물을지는 코드가 정하고 LLM 은 문장만 쓴다.**
리포트가 "누락" 이라고 말한 개념과 질문이 어긋나면 두 화면을 같이 믿을 수 없다.

LLM 을 두 번 부른다. 개념의 **중요도**는 §6 `weight`·§7 `verdict` 로 이미 결정적으로
알지만, "이게 심사위원한테 실제로 찔릴 질문인가 · 함정을 팔 수 있나" 는 코드가 모른다.
그 판단만 1차(triage)에 맡기고 2차는 문장 생성만 맡긴다.
**triage 는 트랙과 무관하므로 세션에 캐시한다** — 1/5/10분을 바꿔도 순위가 안 흔들린다.

### 8-A. 시간 트랙

프론트 `QA_MODES` 키와 같은 문자열이다 (`app.js`).

| `track` | 질문 상한 `QA_TRACK_LIMITS` | 함정 상한 `QA_TRACK_TRAPS` | 뜻 |
|------|------|------|------|
| `"1"` | 1 | 0 | 가장 치명적인 개념 하나. 방어 연습할 시간이 없어 함정을 안 넣는다 |
| `"5"` | 3 | 1 | 핵심 + 놓친 개념 |
| `"10"` | 7 | 3 | 아쉬운 개념 전부 + 모순 대조 |

> 프론트가 CTA 에 약속하는 개수(`QA_MODES[k].count`)는 이 표와 **같은 값이어야 한다.**

### 8-B. 후보 선정 — 전부 코드 (LLM 아님)

`source` 가 곧 우선순위다. 여러 근거가 겹치면 위쪽이 이긴다.

| `source` | 어디서 오나 |
|------|------|
| `contradiction` | `AlignmentDoc.items[].verdict == "contradiction"` — `deck_quote` 가 있는 것(코드가 자료 원문과 견줘 확인)은 **맨 앞**에 서고 「발표에서 한 말 vs 자료 N장, 어느 쪽이 맞나」 로 묻는다 (09-30 WP-S2) |
| `tension` | 주장 그래프(F-26) 탐침 — 자료 안의 긴장 (`QaTriage.probes`) |
| `skipped_slide` | `AlignmentDoc.skipped_slides` — 말로 건너뛴 **핵심** 장마다 대표 개념 하나(그 장에서 missing 으로 남은 핵심 개념 중 자료 비중이 가장 큰 것). 나머지는 `missing` (09-30 WP-S2) |
| `missing` | 같은 곳 `verdict == "missing"` — **`decided_by == "fallback"`(LLM 판정이 없어 언급 횟수로 짐작) 은 누락이 아니다** |
| `under_spoken` | `doc_weight − speech_weight > QA_UNDER_SPOKEN_GAP` (정당생략 제외) |
| `weak_flow` | `FlowDiff.issues` 중 `missing_link`·`order_jump` 에 등장하는 `node_ids` |
| `extra` | `AlignmentDoc.extra_concepts` — 발화에만 나온 개념 (`extra:` 합성 노드) |
| `core_weight` | 나머지를 `ConceptNode.weight` 내림차순 |
| `justified_skip` | `verdict == "justified_skip"` — **강등**. 리포트가 생략을 승인한 개념은 weight 가 커도 서열 맨 뒤다 (모순·누락은 못 덮고, weak_flow 는 덮는다) |

**`AlignmentDoc`·`FlowDiff` 없이 그래프만으로도 동작한다** — 녹음 없이 자료만 올린
경로에서는 전부 `core_weight` 가 되고, 빈 질문 세트가 나오지 않는다.

**녹음을 받았는데 못 쓰면 자료만으로 묻는다 (09-30 WP-S2 `speech_unused_reason`).** 정합이 있으면 그 판정을 따른다 —
`speech_match == "unrelated"`(또는 `basis == "skipped"`) → `unrelated_speech`, `basis == "fallback"` → `align_fallback`
(`AlignmentDoc.speech_usable` 과 같은 뜻). 정합이 겹침을 못 쟀거나 받아쓰기만 왔으면 자료 원문과의 낱말 겹침으로 가른다.
까닭은 `QuestionDoc.speech_unused` 한 칸으로 나간다(§8-E).

`weak_flow` 개념에는 해당 `FlowIssue` 의 상세(`kind`·`note`)가 **프롬프트 재료로**
붙는다 — `order_jump` 는 "왜 이 순서로 설명했나요?", `missing_link` 는 "두 개념은
어떤 관계인가요?" 각도가 된다. 순위는 안 바뀐다 (source 가 정한다).
`build_questions` 에 `flow` 를 넘겨야 질문 단계까지 상세가 전달된다.

#### 최종 순위(`rank`) — 근거가 1순위, 그다음이 1차 LLM 의 치명도

`rank` 가 곧 트랙 상한에 들어갈 순서다. 정렬 키는 이 순서로 본다:

| 순위 키 | 누가 정하나 | 왜 이 자리인가 |
|------|------|------|
| 1. `source` | 코드 (`AlignmentDoc`·`FlowDiff`) | 모순·누락은 **확인된 사실**이다 |
| 2. `severity` | **1차 LLM** | 같은 근거 안에서 무엇이 더 치명적인지는 코드가 모른다 |
| 3. `weight` 내림차순 | 코드 (F-07) | 동률 |
| 4. 앞 슬라이드 → `node.id` | 코드 | 동률 |

**2번이 이 단계를 따로 두는 이유다.** 여기서 `severity` 를 안 쓰면 1차 호출은 화면
표시용 장식이 되고, 1분 트랙이 '가벼움' 개념을 물어보게 된다.

반대로 `severity` 를 1순위로 올리면 안 된다. `severity` 는 LLM 의 짐작이고
`source` 는 확인된 사실이라, 짐작이 사실을 밀어내면 리포트가 "누락" 이라 말한 개념을
안 묻게 되어 두 화면이 어긋난다. 그래서 **근거 안에서만** 치명도가 순위를 정한다.

#### 개념을 홀로 주지 않는다 — `edges` 가 진실

심사위원 질문은 "이게 저것과 무슨 관계인가" 로 들어온다. 개념 하나만 던지면 LLM 은
사전식 정의 질문만 쓰므로, 프롬프트에 **그래프에서의 위치**를 함께 싣는다.

| 프롬프트 항목 | 어디서 | 뜻 |
|------|------|------|
| `경로=` | `graph.path_of(node_id)` | **트리 뷰** — `parent` 간선만 따라간 위계 (노드당 parent 최대 1개) |
| `연결=` | `graph.neighbors_of(node_id)` | **그래프 뷰** — `relates` 까지 포함한 모든 논리 연결 (최대 5개) |
| `발표에서 한 말` | `Transcript.text_for_slide(no)` | 근거 장의 실제 발화 (없으면 줄 자체가 빠진다) |

**트리는 그래프의 부분집합이다.** 둘째 부모가 생기면 F-07 이 버리지 않고 `relates`
로 내려 두므로, `연결=` 에는 남고 `경로=` 에는 안 나타난다 — 정보가 사라지지 않는다.

발화는 그 장을 실제로 말했을 때만 붙인다. 누락(`missing`) 개념처럼 발표자가 그 장까지
못 간 경우, 없는 발화를 '한 말' 로 실으면 판정이 헛돈다.

### 8-C. 원본 — LLM (Solar / A.X …)

1차 `[TASK] qa-triage` — **severity·trap·angle 만** 쓴다:

```json
{ "marks": [ { "node_id": "s5", "severity": 1, "trap": true,
               "angle": "왜 다른 정렬 방식 대신 이걸 골랐는지" } ] }
```

2차 `[TASK] qa-questions` — **question·why·hint 만** 쓴다:

```json
{ "questions": [ { "node_id": "s5", "question": "질문 한 문장",
                   "why": "왜 묻는지", "hint": "방향만 주는 힌트" } ] }
```

판정 `[TASK] qa-judge`:

```json
{ "verdict": "partial", "score": 55, "react": "심사위원 한 마디",
  "summary_sentence": "총평 한 문장", "missing_points": ["빠진 포인트"] }
```

### 8-D. 후처리 — `QaTriage` (F-08 1차)

```jsonc
{
  "file_name": "IMU2CLIP_sample.pdf",
  "total_slides": 12,
  "model": "solar",
  "marks": [
    { "node_id": "s5", "severity": 1, "trap": true, "angle": "왜 이 방식을 골랐는지",
      "source": "missing", "rank": 1, "doc_weight": 0.92 }
  ]
}
```

`node_id`·`source`·`doc_weight` 는 **코드가 채운다** (LLM 값을 쓰지 않는다).
`severity`·`trap`·`angle` 은 LLM 이 쓰고, `rank` 는 둘을 합쳐 코드가 계산한다
(위 8-B 정렬 키). `marks` 는 `rank` 오름차순이고, 후보는 가장 긴 트랙 상한의
두 배까지만 올린다.

LLM 이 어떤 후보를 빠뜨리면 `severity` 는 `source` 기반 결정적 폴백으로 채운다
(모순·누락 → 1, 흐름 결손 → 2, 자료 비중 → weight ≥ 0.5 면 2 아니면 3).

`probes[]` (2026-09-29, F-26) — 주장 그래프에서 코드가 찾은 탐침(`Probe`, §8-I). `marks` 중 `source` 가 `PROBE_KINDS`
(`tension`·`unsolved`·`unsupported_cause`·`absolute_boundary`·`sibling_priority`)인 것은 같은 `node_ids[0]` 의 탐침이 여기 있다
(`QaTriage.probe_for`). QaTriage 는 브리지 안의 캐시라 응답으로 나가지 않는다 — 화면은 `questions[].basis.probe` 로 본다.

### 8-E. 후처리 — `QuestionDoc` (F-08 2차)

```jsonc
{
  "file_name": "IMU2CLIP_sample.pdf",
  "total_slides": 12,
  "track": "5",
  "model": "solar",
  "questions": [
    { "id": "q01-s5", "node_id": "s5", "label": "공동 임베딩 정렬",
      "question": "공동 임베딩 정렬을 왜 이 방식으로 하셨나요?",
      "why": "자료에는 있는데 발표에서 설명하지 않은 개념이에요",
      "hint": "5장에서 이 개념을 어떻게 설명했는지 떠올려 보세요",
      "severity": 1, "trap": true, "source": "missing",
      "slide_nos": [5], "doc_weight": 0.92,
      "answer_gist": "두 모달리티를 같은 공간에 놓고 대조 손실로 정렬한다",
      "answer_gist_parts": [],
      "evidence_slide_no": 5,
      "evidence_quote": "IMU 와 영상 임베딩을 같은 공간에 놓고 대조 손실로 정렬한다",
      "speech_quote": "여기서는 두 신호를 같은 공간에 두고 맞췄습니다",
      "paper_ids": ["d01"] }
  ],
  "deferred_node_ids": ["s7", "s2"],
  "papers": [ { "id": "d01", "kind": "deck", "cite_key": "Stothart et al. (2015)", "title": "…", "…": "§8-G PaperRef" } ],
  "speech_unused": "",
  "speech_note": ""
}
```

`speech_unused`·`speech_note` (09-30 WP-S2) — **녹음을 받았는데 질문 재료로 쓰지 않은 까닭**. 문서 단위 신호는 이것 하나다.
`speech_unused` 는 `""`(녹음을 썼거나 원래 없었다) · `"unrelated_speech"`(녹음이 이 자료의 발표가 아님) · `"align_fallback"`(정합
판정이 짐작뿐) — `RubricFault.kind` 와 같은 말이다. 값이 있으면 모든 질문이 자료만으로 만든 것이고, `speech_note` 는 화면이 첫 질문
앞에 한 번 띄울 해요체 한 줄이다. 질문마다 `basis.checks` 에도 `speech_mismatch_deck_only` / `align_fallback_deck_only` 가 남는다(로그용).

코드가 확인한 모순 질문(`basis.checks` 에 `contradiction_reconcile`)은 **자료 쪽 값을 질문·이유·힌트 1단·「이 질문의 근거」 에 싣지 않는다** —
LLM 문장이 흘리면 정해진 문장으로 바꾼다. `answer_gist` 는 두 인용(자료 쪽이 맞고 발표에서 한 말을 바로잡는다), `evidence_quote` 는
자료 쪽 줄, `speech_quote` 는 어긋난 발화 문장이다. 힌트 사다리는 방향 → 범위 → 어긋난 값만 가린 자료 줄이다.

`paper_ids`·`papers` 는 F-08 이 `PaperDoc`(§8-G) 을 받았을 때만 채운다 (2026-09-22). `paper_ids` 는
이 질문이 인용한 문헌이고, `papers` 는 질문들이 인용한 문헌만 모은 `PaperDoc.refs` 의 부분집합이라
화면이 질문 카드 옆에 「이 논문을 보고 묻는 질문이에요」 를 그릴 때 PaperDoc 을 따로 안 들고 있어도 된다.
**보증 ⑧: 질문·why·hint·answer_gist 속 「저자 (연도)」 인용은 전부 PaperDoc 에 실재한다** — 목록 밖
논문을 인용한 문장은 어댑터가 버리고 결정적 템플릿으로 메운다 (`qa_eval --papers` 의 `citation_grounded` = 1.0).

`slide_nos` 는 **anchor 장**이다 (2026-09-10) — F-07 의 근거 장 안에서 본문이 실제로 이
개념을 말하는 장 최대 3개. 힌트·모범답·화면의 장 그림·판정 본문이 전부 이 목록을 따른다.
`evidence_slide_no`·`evidence_quote`·`speech_quote` 는 F-08 이 slidedoc 을 받았을 때만
채운다 — 「모르겠어요」 사다리가 "자료 5장은 이렇게 말해요: «…»" 로 LLM 없이 즉시 쓴다.
없으면 빈 값이고 사다리는 예전(방향·범위·접근) 그대로다.

**질문의 근거·함정 전제 (2026-09-29 P1·qa/trap, 09-30 qa/reason)** — 질문마다 두 칸이 더 실린다. 옛 세션은 둘 다 null 이다.

```jsonc
"basis": {                                   // QuestionBasis — 이 질문이 왜·무엇을 근거로 나왔나. 옛 세션은 null
  "source": "tension", "slot": "theme", "rank": 1,
  "probe": { "kind": "tension", "node_ids": ["revisit", "price"], "claim_ids": ["c01", "c02"],
             "angle": "…", "evidence": [ { "slide_no": 1, "quote": "…" } ] },   // 탐침에서 나왔으면 (§8-I), 아니면 null
  "evidence": [ { "slide_no": 4, "quote": "자료 원문 그대로" } ],
  "checks": ["mentions_probe_nodes", "gist_probe_code"],
  "reason": [], "background": [], "contrast": [], "contrast_quote": null        // 09-30 qa/reason — 근거 질문일 때만 찬다
},
"trap_premise": {                            // TrapPremise — 함정 질문일 때만. 아니면 null
  "kind": "number", "premise": "질문에 얹은 틀린 말", "fact": "자료가 실제로 말하는 것",
  "slide_no": 3, "wrong": ["40%"], "right": ["25%"]
}
```

| 필드 | 타입 | 뜻 · 화면 |
|------|------|------|
| `basis.source` | string | `Question.source` 와 같은 값 (탐침에서 나왔으면 `PROBE_KINDS` 이름) |
| `basis.slot` | `"theme"`\|`"part"`\|`"weak"`\|`""` | 트랙 배합 자리 — 주제 · 요소 · 약점. `""` 은 배합 밖 |
| `basis.rank` | int | 1차 심사 순위 (`TriageMark.rank`) |
| `basis.probe` | `Probe` \| null | 탐침에서 나온 질문이면 그 탐침 (§8-I) |
| `basis.evidence[]` | `{slide_no, quote}` | 자료 원문 인용 — 힌트 인용과 같은 출처 |
| `basis.checks[]` | string[] | 질문 문장에 대한 코드 검사 이름 (`trap_generated`·`probe_template`·`fallback_template`·`gist_rebuilt` …). **열린 목록** — 로그·하네스용, 화면은 읽지 않는다 |
| `basis.reason[]` | `{slide_no, quote}` | (09-30) 근거·이유를 묻는 질문이면 결론을 받치는 **이유 줄**. F-09 가 채점 기준으로 싣는다 |
| `basis.background[]` | `{slide_no, quote}` | (09-30) 현상이 있다는 **배경 줄** — 이유가 아니다(배경 수치를 이유처럼 답하면 `reason` 가드) |
| `basis.contrast` | string[] (0 또는 2) | (09-30) 「모르겠어요」 보기 쌍 `[자료가 세운 쪽, 부정한 쪽]`. 쌍이 아니면 빈 목록 |
| `basis.contrast_quote` | `{slide_no, quote}` \| null | (09-30) 그 대비가 적힌 자료 줄 |
| `trap_premise.kind` | enum | `TRAP_KINDS` — `number` 수치 · `order` 비교 순서 · `extreme` 표의 가장 큰 쪽 · `direction` 방향 · `negation` 부정·대조 |
| `trap_premise.premise` | string | 질문에 얹은 **틀린 말** — 코드(`_traps`)가 자료 줄 하나에서 한 곳만 뒤집어 만든다 (LLM 이 지어내지 않는다) |
| `trap_premise.fact` | string | 자료가 실제로 말하는 것 (자료 줄 그대로 또는 표 행에서 읽은 값) |
| `trap_premise.slide_no` | int | `fact` 의 장 |
| `trap_premise.wrong[]` · `right[]` | string[] | 전제에만 있는 단서 · 자료에만 있는 단서. F-09 가 답이 어느 쪽을 말했는지로 「전제에 동의했나」 를 정한다 |

**화면 규칙 — 답하기 전에 답을 흘리지 않는다:** 「이 질문의 근거」 칸은 한 줄 설명과 **장 번호까지만** 보인다 — `basis.evidence`·
`reason`·`contrast_quote` 의 인용문은 질문을 띄울 때 싣지 않는다(09-30 held-out C-03: 함정은 근거 인용이 곧 바로잡은 사실이라
15개 중 13개가 정답을 질문 밑에 펼쳤다). 서버도 먼저 가린다 — 함정 질문(`trap_premise` 있음)과 인용이 곧 기대 답인 질문은
`basis.evidence[].quote` 가 `""`(장 번호만)이고 `reason`·`background`·`contrast` 가 비며 `checks` 에 `basis_quote_hidden` 이 붙는다.
`trap_premise.fact` 와 함정 질문의 `answer_gist` 는 통과(`passed`)하거나 닫힌 뒤에만 펼친다(09-30 §7). 함정 질문의 `why` 는
함정임을 알려 주므로 화면이 장만 가리키는 중립 문장으로 바꾼다(09-30 B-01·H-07).
`trap=true` 인데 `trap_premise` 가 null 이면 옛 세션이다 — 판정은 예전 규칙으로 간다.

**응답의 폴백 표시 (09-30 WP-B):** `POST /api/v1/questions` 응답(QuestionDoc + 힌트 사다리)에는 `degraded`(코드 목록)·`degraded_notes`
(같은 순서의 사람 말)가 **언제나** 있다 — 폴백이 없으면 둘 다 `[]`. 코드는 `slide_doc_missing` · `claims_rule_only`·`claims_failed`·
`claims_timeout` · `papers_timeout`·`papers_unavailable`·`papers_partial`·`papers_failed` · `memory_failed` (§10-E). `slide_doc_missing` 을 뺀
나머지로 만든 질문 묶음은 `DEMO_FALLBACK_TTL_SEC`(120초)만 들고 있다가 재료부터 다시 만든다. 화면: `degraded_notes` 를 첫 질문 앞에
한 번 짧게.

**보증 (불변식):** ① 질문 `id` 유일 · `node_id` 중복 없음 ② 질문 수 ≤
`QA_TRACK_LIMITS[track]` ③ `trap=true` 수 ≤ `QA_TRACK_TRAPS[track]` (1분 트랙은 0)
④ `severity` 는 `QA_SEVERITIES` 안 ⑤ `question`·`why`·`hint` 는 `QA_TEXT_MAX`(200자)
이내이며 **절대 비지 않는다** (LLM 이 빠뜨리면 결정적 템플릿으로 메운다)
⑥ **`id` 가 `rank`·`node_id` 에서 결정적으로 나오므로, 같은 triage·같은 track 이면
결과가 완전히 같다** (uuid 금지) ⑦ `deferred_node_ids` 는 상한에 밀린 후보.

### 8-G. `PaperDoc` — 교수가 읽고 온 문헌 (F-24, 2026-09-22)

**책임 한 줄:** 자료가 인용한 참고문헌과 개념별로 검색한 실재 논문을 모아, F-08 이 **논문을 근거로 묻는**
질문을 만들 수 있게 한다. `SlideDoc`(+`ConceptGraph`) → `PaperDoc` · 자유 질문 문자열 → `PaperDoc`.

| 입력 | 필수 | 무엇에 쓰나 |
|------|------|------|
| `ConceptGraph` | ✅ | 상위 weight 개념 `PAPER_NODE_MAX`(5)개 → 검색어 · deck 문헌에 `node_ids` 조인(`slide_nos`) |
| `SlideDoc` | 선택 | 「저자 (연도)」·REFERENCES 장을 **정규식**으로 뽑아 deck 문헌 (LLM 0) |
| 학술 검색 provider | 선택 | `SCHOLAR_PROVIDER` 가 `none` 이 아닐 때만 외부 호출. 통로 5개(openalex · semanticscholar · arxiv · crossref · europepmc)를 쉼표로 여러 개, `all` 은 openalex,arxiv,europepmc(+semanticscholar 는 `S2_API_KEY` 가 있을 때). `none` 이면 deck 만 |

```jsonc
{
  "file_name": "IMU2CLIP_sample.pdf",
  "provider": "openalex+arxiv+europepmc",   // 검색을 맡은 통로 — 하나면 그 이름, 여럿이면 "a+b", 껐으면 none
  "note": "",                      // 검색을 못 했으면 왜인지 ("검색 꺼짐…" · "openalex 검색 실패: …")
  "refs": [
    { "id": "d01", "kind": "deck",                      // d = 자료가 인용 · s = 검색 결과
      "cite_key": "Stothart et al. (2015)",             // 파생 — 프롬프트·화면·검사가 같은 문자열을 쓴다
      "title": "The attentional cost of receiving a cell phone notification",
      "authors": ["Stothart", "Mitchum", "Yehnert"], "et_al": true, "year": 2015,
      "venue": "Journal of Experimental Psychology: HPP",
      "doi": "10.1037/xhp0000100", "url": "https://doi.org/10.1037/xhp0000100",
      "abstract": "…원문을 PAPER_ABSTRACT_MAX(300자)로 자른 것…",   // 요약 아님
      "cited_by": 412, "slide_no": 5, "node_ids": ["notification"], "query": "", "source": "openalex" },
    { "id": "s01", "kind": "scholar", "cite_key": "Leroy (2009)", "slide_no": 0,
      "node_ids": ["attention-residue"], "query": "attention residue task switching",
      "source": "openalex+europepmc",   // 어느 통로가 찾았나. 두 통로가 같이 찾으면 "a+b" (합의는 순위를 올린다)
      "…": "…" }
  ]
}
```

**원칙:** 제목·저자·연도·DOI·초록은 전부 **원문(자료 또는 검색 API)** 에서 온다. LLM 이 채우는 필드는 없다.
LLM 은 한 번만 쓴다 — 한글 개념 이름을 영어 검색어로 바꾸는 일(`[TASK] paper-queries`). 검색어는
사실이 아니라 열쇠라 지어내도 해가 없다. 영문 개념은 LLM 없이 그대로 검색한다.

**품질 순위**(`providers/scholar_impl.rank_refs` — 통로가 몇 개든 이 한 함수): 검색어 낱말이 제목·초록에
실제로 있는 비율 0.5 · 관련도(통로가 안 주면 응답 순서) 0.2 · 피인용(log) 0.2 · 최근성 0.1. 낱말 겹침 0.5 미만은
**채워 넣지 않는다** (관련도·피인용만 믿으면 "attention residue task switching" 에 AlphaFold 가 1위로 온다 — 09-22 실측).
**제목에 검색어 낱말이 하나도 없으면 버린다** (초록에만 attention·residue·task 가 다 있는 단백질 결합 부위 논문이
3위에 올랐다 — 09-23 실측). 같은 논문의 여러 판(Europe PMC 의 MED·PMC·PPR, DOI 있는 판과 arXiv 판)은 하나로 합친다.

**보증:** ① `id` 는 문서 안에서 결정적(d01…, s01… 첫 등장 순) ② 같은 논문(DOI 또는 제목)은 하나로 합치고
`node_ids` 를 더한다 ③ 검색이 꺼졌거나 실패해도 예외 없이 deck 만 돌려주고 `note` 에 사정을 적는다
④ deck 문헌은 검색으로 되찾아(DOI 우선) DOI·초록을 채우되 `kind` 는 deck 그대로다.

**F-08 이 인용하게 하는 법(2026-09-23):** 문헌 줄이 붙은 개념인데 질문이 인용을 안 했으면, 그 질문과 문헌만 실은
짧은 과제 `[TASK] qa-cite` 로 **한 번** 고쳐 쓰게 한다 (전체 프롬프트 재요청은 15k자 속에서 규칙이 묻혀 두 번 다 인용 0 이었다).
고쳐 쓴 문장도 어댑터가 다시 검사한다 — 목록 밖 인용이면 원문을 지킨다.

**경로:** `POST /api/v1/papers` `{graph|session_id, slide_doc?}` → PaperDoc (세션에 한 번 만들어 `paper_doc`
아티팩트로 보관, 그래프가 바뀌면 지운다) · `POST /api/v1/papers/search` `{query, limit?}` → PaperDoc
(자유 질문의 논문 검색, 전부 `kind=scholar`). `/api/v1/questions` 는 `papers=false` 로 끌 수 있다.

**`status[]` — 검색 한 건 한 건의 사정 (09-30 G-A9·G-A32).** `note` 한 줄로는 「어느 개념이 왜 문헌 없이 갔나」 를 못 가른다.
항목은 dict 이고 `kind` 로 나뉜다. `to_dict` 에 언제나 있고, 비면 검색을 안 했거나(scholar=none) 옛 문서다.

| `kind` | 칸 |
|------|------|
| `concept` | `{node_id, label, query, query_source, state, kept, dropped, reason}` — 개념 하나의 검색. `query_source`: `label`(영문 이름 그대로)·`llm`(번역)·`ascii`·`none`. `kept`/`dropped` 는 그 개념의 관련성 바닥(`_keeps`)을 넘은/떨어진 검색 결과 수. `/papers/search` 는 `node_id: ""` 한 줄 |
| `resolve` | `{cite_key, state}` — 자료 인용 되찾기. 못 찾으면 `state: "not_found"` |
| `provider` | `{provider, calls, ok, empty, failed, rate_limited, timeout, throttled, not_searched, error}` — 통로마다 센 수와 첫 오류 한 줄 |

`state`: `ok`·`empty`(성공) · `failed`·`rate_limited`·`timeout`·`http`·`network`·`parse`·`error`(실패) · `throttled`(우리 요청 한도로 참음) ·
`not_searched`(시간 예산으로 시작 못 함) · `no_query`(검색어 없음). 화면: 문헌 카드가 비었을 때 `rate_limited`·`timeout` 이면 「검색이 잠시
막혔어요」, `no_query`·`empty` 면 「맞는 논문을 못 찾았어요」 로 가른다.

**폴백 표시 (09-30 B-03·B-11·B-14):** `POST /api/v1/papers` 응답에는 `degraded`·`degraded_notes` 가 언제나 있다 — `papers_unavailable`
(검색 실패·통로 쉬는 중 → 자료 인용 문헌만)·`papers_partial`(일부 통로만 실패) 중 하나 또는 `[]` (§10-E). `papers_timeout` 은 질문 생성이
문헌을 6초(`DEMO_PAPERS_DEADLINE_SEC`)까지만 기다릴 때 `/questions` 에만 나온다. `/papers/search` 응답에는 `degraded` 가 없다. 검색이 실패한 PaperDoc(429·시간
초과로 자료 인용만 남은 것)은 보관하지 않고 120초만 들며, 실패한 통로는 `DEMO_PAPERS_NEGATIVE_TTL_SEC`(180초) 동안 부르지 않는다.
보관한 `paper_doc` 은 그래프 지문(`graph_fp` 키)이 같을 때만 다시 쓴다.

### 8-H. `MemoryDoc` — 리허설을 기억하는 Q&A (F-25, 2026-09-23)

**책임 한 줄:** 같은 사람·같은 발표의 지난 리허설(동의 세션의 `qa_turns.jsonl`)에서 개념별 답변 과정을 **세어** 다음 Q&A 에 잇는다.
못 넘긴 개념이 먼저 나오고(F-08 1차), 질문이 빠졌던 점을 겨냥하고(F-08 2차), 판정이 진전을 알아보고(F-09), 코칭이 안 통한 되물음을 건너뛴다.

| 입력 | 필수 | 무엇에 쓰나 |
|------|------|------|
| 지난 세션 `qa_turns` | ✅ | `{question{label,node_id}, hints_shown, give_up, judgement{verdict,score,missing_points}}` → 개념별 집계. **LLM 0** |
| 잇는 열쇠 | ✅ | `learner_id`(브라우저 난수, 업로드 쿼리 `?learner=`)만. 요청 세션도 동의해야 한다. **같은 파일(`sha256`)·파일 이름만으로는 안 잇는다** — 부스에서 남의 기록이 붙는다. `sessions[].session_id` 는 불투명한 `past-…` 표시다 |
| 이번 `ConceptGraph` | 선택 | `MemoryDoc.by_node(graph)` — 이름을 글자 2-gram Dice ≥ 0.6 으로 잇는다 (노드 id 는 세션마다 다르다). 09-30 부터 반대말·한 낱말 치환은 잇지 않고(「인력 부족」≠「인력 부족 해소」, `memory_similarity`), 표기만 다른 이름은 0.95, 발표 지문(`deck_keys`)이 이번 그래프와 맞는 기억만 잇는다. 브리지는 그래프·자료를 넘겨 이번 발표로 거른 기억(`scoped`)을 만든다 |

```jsonc
{
  "learner_key": "learner:3f9a2c7e",     // "learner:<id 앞 8자>" | "" (못 이음). 같은 파일만으로는 잇지 않는다
  "file_name": "발표.pdf", "note": "",
  "scoped": true,                          // 09-30 — 이번 발표(그래프)로 거른 기억인가
  "sessions": [                            // 최신이 먼저, 최대 MEMORY_SESSIONS_MAX(5)
    { "session_id": "past-3f9a2c7e1b04", "at": 1758550000.0, "title": "발표",
      "questions": 3, "good": 1, "partial": 1, "wrong": 0, "give_ups": 1, "score_mean": 58.3 }
  ],
  "concepts": [                            // stalled(한 번도 통과선을 못 넘음)가 먼저
    { "key": "알림의주의비용", "label": "알림의 주의 비용", "node_ids": ["notification"],
      "asked": 2, "attempts": 3, "give_ups": 0, "verdicts": { "wrong": 1, "partial": 2 },
      "last_verdict": "partial", "best_verdict": "partial", "last_score": 65, "last_at": 1758550201.0,
      "missing_points": ["통제 집단", "측정 조건"],   // 최근 판정이 짚은 것, 최신 우선, 최대 3
      "hints_max": 1,
      "passes": 0, "closes": {}, "deck_keys": ["알림의주의비용", "주의잔여", "측정조건"],   // 09-30
      "stalled": true }
  ]
}
```

| 필드 (09-30 WP-P) | 타입 | 뜻 · 화면 |
|------|------|------|
| `scoped` | bool | f25 가 이번 그래프를 받아 **다른 발표의 리허설을 빼고** 만든 기억이다(요약 `sessions` 까지). 참이면 이름만으로 찾아도(`concept`) 안전하고 `by_node` 는 지문 대조를 건너뛴다. 거짓(이번 발표를 모르고 만든 기억)이면 지문이 있는 기억은 그래프와 견줘서만 잇는다 |
| `concepts[].passes` | int | 통과선(`qa_passed`)을 넘은 턴 수 — 70~79 partial 도 센다. 옛 기억은 0 |
| `concepts[].closes` | `{close_reason: 횟수}` | 닫힌 까닭별 횟수 — `good`·`rounds`·`guard` (§8-F `close_reason`). 화면: 「설득해 닫음」 은 `good` 만 센다 |
| `concepts[].deck_keys` | string[] | 발표 지문 — 같은 발표로 묶인 지난 리허설에서 물은 개념 이름 열쇠 전부(정렬, 최대 40). 이름 하나(「비용」)가 같다고 다른 발표의 기억을 잇지 않게 한다. 비면(옛 기억) 예전처럼 이름으로만 잇는다 |
| `concepts[].stalled` | bool (파생) | **뜻이 바뀌었다** — 「물어봤는데 한 번도 통과선을 못 넘었다」(`attempts > 0 && passes == 0 && best_verdict != "good"`). 예전엔 good 이 없으면 전부 stalled 라 partial 70~79 로 통과한 개념이 다음 리허설 맨 앞에 다시 섰다(09-30 G-A23). 가드에 막힌 채 3라운드에서 닫힌 턴은 통과가 아니라 여기 남는다 |

**프롬프트에 싣는 것:** `ConceptMemory.prompt_line` 한 줄 — 「지난 리허설: 2번 물음 · 마지막 판정 반쯤 · 빠졌던 점: 통제 집단 / 측정 조건」.
**싣지 않는 것:** 답변 원문(지난 답을 이번 답으로 착각한다), 오디오, 동의 없는 세션. memory 가 없으면 F-08·F-09 프롬프트는 예전과 글자까지 같다.

**경로:** `POST /api/v1/memory {session_id}` → MemoryDoc (없으면 `note` 에 사유). `/api/v1/questions`·`/api/v1/qa/judge` 는 세션에 기억이 있으면
자동으로 싣고, 본문 `"memory": false` 로 끈다. 만든 기억은 이 세션의 `memory_doc` 아티팩트(동의 세션만)로 남는다.

`POST /api/v1/memory` 는 기억을 **못 읽었으면** 「지난 리허설 없음」(200 + `note`)이 아니라 503 `memory_failed`(`retry_after` 120)다 —
실패는 120초만 들고 다시 읽어 본다. `/questions`·`/qa/judge` 는 같은 실패를 막지 않고 응답 `degraded` 에 `memory_failed` 로 싣는다 (§10-E).

### 8-I. `ClaimDoc` · `Probe` — 주장 그래프와 탐침 (F-26, 2026-09-29)

**책임 한 줄:** 개념 사이의 **주장**(「A = B × C」 · 「A 가 B 보다 중요」 · 「A 가 B 를 일으킨다」 …)을 자료 원문 인용과 함께 뽑아,
F-08 이 자료 안의 긴장·빈칸을 **코드로** 찾게 한다. `ConceptGraph` + `SlideDoc`(필수 — 인용을 원문과 대조한다) → `ClaimDoc`.
LLM 1콜 + 규칙 주장(식·비교·인과·목록). LLM 이 죽으면 규칙 주장만 낸다(`model: "rule"`). 탐침(`Probe`)은 F-08 이
ClaimDoc(+ 자료 원문)에서 결정적으로 만든다(`_probes.derive_probes`, LLM 0).

```jsonc
{
  "file_name": "cafe.pdf", "model": "solar", "dropped": 2,
  "claims": [
    { "id": "c01", "kind": "compose", "subject_id": "revisit", "object_ids": ["taste", "price", "mood"],
      "text": "재방문은 맛·가격·분위기로 이뤄진다",
      "evidence": [ { "slide_no": 2, "quote": "재방문 = 맛 × 가격 × 분위기" } ], "has_support": false }
  ],
  "degraded": [], "degraded_notes": []          // /api/v1/claims 응답에만 (09-30) — 규칙 주장만이면 ["claims_rule_only"]
}
```

| 필드 | 타입 | 뜻 |
|------|------|------|
| `model` | string | 주장을 뽑은 LLM · `rule`(LLM 없이 규칙 주장만) |
| `dropped` | int | 원문 대조 실패·그래프 밖 id 로 버린 주장 수 (로그·측정용) |
| `claims[].id` | string | `c01` … 문서 안 안정 키 |
| `claims[].kind` | enum | `CLAIM_KINDS` — `compose`(subject 는 objects 로 이뤄진다) · `compare`(subject 가 objects 보다 더 …) · `cause`(일으키거나 끊는다) · `solve`(해결한다) · `absolute`(단정 — objects 는 비어도 된다) · `contrast`(맞세운다). 밖이면 `contrast` |
| `claims[].subject_id` · `object_ids[]` | string | `ConceptGraph.nodes[].id`. 그래프 밖 id 는 어댑터가 버린다 |
| `claims[].text` | string | 주장 한 줄 — 자료 표현에 가까운 **내부 재료**(해요체 아님). 화면 문구로 쓰지 않는다 |
| `claims[].evidence[]` | `{slide_no, quote}` (`ClaimQuote`) | 자료 원문 **그대로** — 코드가 원문과 대조해 통과한 것만. 하나도 없으면 그 주장은 버린다 |
| `claims[].has_support` | bool | 그 장에 수치·출처·연구 언급이 있나 (코드가 채운다) — `unsupported_cause` 탐침이 본다 |

| `Probe` 필드 | 타입 | 뜻 |
|------|------|------|
| `kind` | enum | `PROBE_KINDS` — `tension`(compare A>B 와 compose A⊃B 가 함께) · `unsolved`(compose 의 요소에 solve 가 없음) · `unsupported_cause`(수치·출처 없는 cause) · `absolute_boundary`(「반드시·완전히·항상」 단정 — 반례·경계) · `sibling_priority`(같은 compose 의 형제 — 하나만 지킨다면). `QA_SOURCES` 에도 같은 이름으로 있다 |
| `node_ids[]` | string[] | `[0]` 이 질문의 대상 개념 |
| `claim_ids[]` | string[] | 근거 주장 id (자료 구조 탐침이면 빌 수 있다) |
| `angle` | string | 코드가 조립한 질문 각도 한 줄 — 질문 프롬프트에 그대로 실린다 |
| `evidence[]` | `{slide_no, quote}` | 자료 원문 인용 |

**빈 주장 문서도 문서다 (09-30 WP-Q2):** 주장이 0개인 ClaimDoc 은 실패가 아니라 결과다 — F-08 은 그래도 자료 구조 탐침(「X보다 중요한 Y」
줄 + 「Y = … × X」 식 줄의 긴장)을 찾는다. 「주장을 안 돌렸다」 는 ClaimDoc 이 null 일 때뿐이다.

**경로:** `POST /api/v1/claims` `{graph | session_id, slide_doc?}` → ClaimDoc + `degraded`·`degraded_notes`(언제나, 09-30). 자료 본문이
없으면 409 `slide_doc_missing`, 못 만들면 502 `claims_failed`. 세션에 한 번 만들어 `claim_doc` 아티팩트로 남기지만 **되읽지 않는다**(그래프를
다시 만들면 id 가 안 맞는다). 규칙 주장만 나온 문서는 단계 캐시에 안 담고 120초만 든다. `/api/v1/questions` 는 `claims=false` 로 끈다.
화면이 직접 그리는 문서가 아니다 — 질문의 `basis.probe`·`basis.evidence` 로 보인다(§8-E).

### 8-F. 후처리 — `QaJudgement` (F-09)

```jsonc
{
  "question_id": "q01-s5",
  "node_id": "s5",
  "verdict": "partial",
  "score": 55,
  "react": "그 부분은 맞습니다. 다만 왜 그 값을 골랐는지가 빠졌네요.",
  "summary_sentence": "공동 임베딩 정렬 — 방향은 맞지만 근거가 얕아요.",
  "missing_points": ["온도 파라미터를 고른 이유"],
  "model": "solar",
  "followup": "그 값을 키우면 무엇이 달라지나요?",
  "round_no": 1,
  "probe_tier": "probe",
  "choices": [],
  "evidence_quote": "",
  "evidence_slide_no": 0,
  "guard_reason": "",
  "guard": "",
  "passed": false,
  "mastered": false,
  "close_reason": ""
}
```

`guard_reason` 은 코드 가드가 등급을 내린 까닭(「자료 4장과 어긋난 곳: …」「질문이 묻는 것: …」)이다. **`missing_points` 와 따로 온다** —
2026-09-30 대화 감사 §6 에서 가드 사유가 결손 맨 앞에 끼어 되물음 틀이 깨졌다. `close_reason` 은 파생값이다(아래 「두 개의 출구」).

`guard` 는 등급·점수를 정한 코드 가드의 **이름**이다(`contracts.QA_JUDGE_GUARDS`, 2026-09-30 레드팀) — `""` 이면 LLM 판정 그대로.
`injection`(답 속 채점 지시 · 55) · `list`(낱말 나열·서술어 없음 · 65) · `echo`(질문 되읊기 · 55) · `repeat`(앞 답 되풀이 · 65, 라운드도
안 오른다) · `number_unsupported`(자료에 없는 수를 자료가 다른 값을 붙인 대상에 · 65) · `ungrounded`(통과 점수인데 골자 요소·질문의
고유 낱말과 안 닿음 · 65) · `trap_misfixed`(수치 함정을 틀린 값으로 고침 · wrong 35) · `trap_open`(함정인데 전제를 짚었는지 모름 · 65) ·
`language`(한국어가 아닌 답 — 채점하지 않고 `unknown`) 와 예전 가드들(`trap` · `deck` · `self_opposed` · `restated` · `reason` ·
`off_topic` · `focus_miss` · `short` · `choice`). 화면은 문장(`guard_reason`)을, 하네스·리포트는 이름을 읽는다.

**판정 응답에만 붙는 네 칸 (09-30 R4·B-07·B-12, `POST /api/v1/sessions/{id}/qa/judge` · `/api/v1/qa/judge`)** — QaJudgement 계약 밖이라
`from_dict` 는 읽지 않는다. 네 칸은 판정 응답에 **언제나** 있다.

| 필드 | 타입 | 뜻 · 화면 |
|------|------|------|
| `grounded_on_server` | bool | 채점 기준이 **서버가 만든 질문**이었나 (이 세션 질문 색인 · 동의 세션의 `question_doc` 보관본 · 문장이 달라 서버 최신 판으로 채점한 것 모두 참). 거짓이면 본문 질문으로 채점했고 그 턴은 `qa_turns` 에 남기지 않는다(F-25 기억·학습 묶음으로 안 흘러간다). 화면: 사용자가 할 일이 없어 띄우지 않는다(로그만) |
| `grounded_on_deck` | bool | 자료 본문(`slide_doc`)과 대조해서 판정했나. 화면: 거짓이면 「자료 본문 없이 판정했어요」 한 줄 |
| `degraded` | string[] | 폴백 코드 — `slide_doc_missing` · `question_unverified`(서버 질문을 못 찾아 본문 질문으로) · `question_mismatch`(화면 질문이 서버 것과 달라 서버 판으로) · `memory_failed`. 없으면 `[]` |
| `degraded_notes` | string[] | 같은 순서의 사람 말 (§10-E). 화면: `question_unverified`·`question_mismatch` 의 말은 띄우지 않고 나머지만 |

세션 id 는 본문 `session_id` 가 먼저, 없으면 경로의 `{id}`. 발급 모양 또는 `"flat"`(발급 id 가 없는 경로의 자리표시자)만 받는다 —
그 밖이면 400. `question_id` 로 서버 질문을 찾으므로 **`question_id` 와 `question`(문장 비교·폴백용)을 같이 보낸다.**

#### 막힘 코칭 — `coach_stage` (「모르겠어요」)

| 단계 | 몇 번째 포기 | 무엇을 주나 | LLM |
|---|---|---|---|
| `narrow` | 1 | 자료 인용(«…», `evidence_slide_no`) + **둘 중 하나** 되물음. `choices` 2개 | 호출. 선택형이 아니면 코드 문장으로 폴백 |
| `scaffold` | 2 | 골자에서 낱말 하나를 가린 **빈칸** + `choices`(정답·이웃 개념에서 뽑은 오답) | **없음** |
| `explain` | 3+ | 해설 + 출처(자료 N장 인용 · 발표 때 한 말) → 화면이 「자기 말로 다시」로 보낸다 | 호출 |
| `clarify` | (되물음) | 같은 질문을 쉬운 말로 | 호출 |

단계는 서버가 history 의 같은 `question_id` 포기 횟수로 센다. 골자가 없어 빈칸을 못 만들면
`scaffold` 를 건너뛰고 `explain` 이다. `choices` 가 비면 자유 답이다.

| `verdict` | 뜻 | 기본 `score` |
|------|------|------|
| `good` | 설득 완료 — 자기 말로 정확히 설명했다 | 85 |
| `partial` | 부분 인정 — 방향은 맞지만 근거가 얕다 | 55 |
| `wrong` | 미방어 — 자료와 어긋났거나 질문을 빗나갔다 | 20 |
| `unknown` | 판정 보류 — 판단할 수 없다 | 0 |

> `skipped` 는 프론트가 넘긴 질문에 로컬로 붙이는 값이라 서버 판정에는 없다.

#### 두 개의 출구 — `passed` 와 `mastered`

**같은 값이 아니다. 합치면 되묻기가 안 돈다.**

| 파생 필드 | 누가 쓰나 | 기준 |
|------|------|------|
| `passed` | **리포트**가 "이 개념을 방어했는가" 를 셀 때 | `good` 이거나 `score >= 70` (점수는 등급 구간 안으로 잘라 본다 — partial ≤ 79 · wrong ≤ 39 · unknown 0) |
| `mastered` | **대화**가 "다음 개념으로 넘어가도 되는가" 를 정할 때 | `good` 이거나, `round_no >= 3` 이면서 (`passed` 이거나 **코드 가드만** 통과를 막았음) |
| `close_reason` | 결과 화면이 진짜 설득과 라운드 출구를 나눠 셀 때 | `""`(안 닫힘) · `good` · `rounds`(3라운드 통과 수준) · `guard`(가드에 막힌 채 3라운드) |

코드 가드(자료 어긋남·자기모순·초점)는 글자로 대조해서 틀릴 수 있다. LLM 판정은 통과였는데 가드만 막고 있으면 3라운드에서
닫는다(2026-09-30 §2: 자료대로 답한 사람이 네 턴 내리 55 를 받고 「답 보기」 로만 빠져나갔다). 그 표시(`guard_blocked`)는
`to_dict`·`from_dict` 에 싣지 않는다 — 요청 바디가 출구를 열 수 없어야 한다.

판정 규칙 8 이 "요지는 맞고 근거만 얕다" 를 70~79 로 매기게 하는데 그 구간이 곧
`passed` 라, 하나로 쓰던 시절엔 **가장 흔한 답변이 되묻기를 통째로 건너뛰었다.**
절반 맞힌 사람에게 한 걸음 더 묻는 것이 이 제품의 핵심 로직인데 그 로직이 실행되지
않았다. 그래서 리포트 기준(`passed`)은 그대로 두고 대화 기준(`mastered`)만 올렸다.

`QA_MAX_ROUNDS`(3) 는 지치지 않게 하는 밸브다 — 세 번 물었는데도 못 올라오면
통과 수준에서 닫아 준다. 압박이 목적이지 고문이 목적이 아니다.

#### 되묻기 단계 — `probe_tier`

라운드가 오를수록 질문의 **넓이**가 좁아진다. 같은 넓이로 세 번 물으면 압박이
아니라 반복이다. §8-B 와 같은 철학 — 넓이는 코드가 정하고 LLM 은 문장만 쓴다.

| `probe_tier` | 라운드 | 질문의 모양 |
|------|------|------|
| `probe` | 1 | 빠진 지점 하나를 **열린 질문**으로 짚는다 |
| `focus` | 2 | **예/아니오·둘 중 하나·한 단어**로 답할 만큼 좁힌다 |
| `converge` | 3+ | 답을 거의 품은 **확인 질문** — 고개만 끄덕이면 되는 형태 |
| `""` | — | 되물을 일이 없다 (정복했거나 막힘 코칭 경로다) |

**보증 (불변식):** ① `verdict` 는 4-class 안 (밖이면 `unknown`) ② `score` 는 0~100,
없으면 verdict 기본값 ③ **`node_id`·`question_id` 는 질문에서 승계** — LLM 이 다른 값을
줘도 무시한다 (조인 키가 흔들리면 리포트가 엉뚱한 개념에 총평을 붙인다)
④ `react`·`summary_sentence` 는 항상 채워진다 (프론트가 이 둘로 말풍선을 그린다)
⑤ 빈 답변은 **LLM 을 부르지 않고** 즉시 `unknown`
⑥ `followup` 은 **`mastered` 가 아닐 때 절대 비지 않는다** — 실전 코칭은 턴 상한이
없어서 질문이 멈추면 사용자가 그 자리에 갇힌다. LLM 이 빠뜨리면 단계별 템플릿이 메운다
⑦ `round_no`·`probe_tier`·`mastered` 는 **서버가 정한다** — `from_dict` 가 `passed`·
`mastered` 를 일부러 안 읽어서 요청 바디로 임계를 뒤집을 수 없다.

`history` 는 프론트가 한글 키(`질문`·`답변`·`판정`)로 보낸다. 이미 굳은 계약이라
`QaTurn.from_dict` 가 한글·영문 양쪽을 받는다.

**안 함:** 질문 순위 재정렬(코드가 정한 `rank` 를 LLM 이 못 바꾼다), 말투·발음 평가,
최종 점수 합산.

코드: `f08_questions.triage_questions()` / `.build_questions()` · `f09_judge.judge_answer()`
API: `POST /api/v1/sessions/{id}/questions` (202+job) · `POST /api/v1/sessions/{id}/qa/judge` (동기 200)

> `/qa/judge` 는 **잡이 아니라 동기 라우트**다 — 프론트가 응답 바디를 바로 읽는다.
> 세션이 사라졌을 때를 대비해 요청 바디의 `question`(=`Question.to_dict()`)을 폴백으로
> 받는다. 서버 저장소가 인메모리라 재시작하면 세션이 날아가는데, 질문 세트는 브라우저에
> 남아 있기 때문이다. 세션 아티팩트가 정본이고, 없을 때만 바디를 쓴다.
>
> **09-30 부터 채점 기준(질문)도 서버가 정한다** (감사 R4·B-07·B-12 — 본문의 `trap`·`trap_premise`·`basis` 를 지우거나 `answer_gist` 를
> 고쳐 보내면 함정에 동의한 답이 wrong 0 → good 80 이 됐다). 서버 질문(이 세션 색인 → 동의 세션 보관본)을 `question_id` 로 찾아 **그걸로**
> 판정하고, 본문 `question` 은 같은 id 가 트랙마다 있을 때 문장이 같은 판을 고르는 데만 쓴다. 서버에 없을 때만 본문으로 판정하되
> 길이·깊이를 자르고 `grounded_on_server: false` · `degraded: ["question_unverified"]` 로 알리며 그 턴은 기록하지 않는다.

---

## 9. 한눈에 보기

| 기능 | 원본(raw) | 후처리(ours) | 변환 위치 |
|------|-----------|--------------|-----------|
| F-01 | Upstage `elements[]` | `SlideDoc` | `f01_parse.py` |
| F-02 | 프론트 폼 | `Context` | 프론트 → JSON |
| F-03 | MediaRecorder | audio blob | `sdk/rehearsal-recorder.js` |
| F-04 | 클릭 시각 | `SlideMark[]` | 同上 |
| F-05 | A.X `utterances[].words[]` | `Transcript` | `stt_impl.py` + `f05_stt.py` |
| F-06 | LLM JSON 문자열 | `ConceptDoc` | `f06_concepts.py` |
| F-07 | LLM JSON 문자열 | `ConceptGraph` | `f07_graph.py` |
| F-08 | LLM JSON 문자열 ×2 | `QaTriage` → `QuestionDoc` | `f08_questions.py` |
| F-09 | LLM JSON 문자열 | `QaJudgement` | `f09_judge.py` |
| F-11 | LLM JSON 문자열 | `AlignmentDoc` | `f11_align.py` |
| F-11 파생 | `ConceptGraph`+`AlignmentDoc` (LLM 없음) | `FlowDiff` | `f11_flow.py` |

---

## 10. 다음 모듈이 받을 것

| 다음 | 필요한 ours |
|------|-------------|
| F-07 그래프 | `ConceptDoc` (+ 선택 `SlideDoc`) |
| F-08 예상 질문 | `ConceptGraph` (+ 선택 `AlignmentDoc`·`FlowDiff`·`Transcript.by_slide`) → `QaTriage` → `QuestionDoc` (§8) |
| F-09 답변 판정 | `Question` + 답변 (+ 선택 `ConceptGraph`·`AlignmentDoc`·`Transcript.by_slide`·history) → `QaJudgement` (§8) |
| F-10 질문 코칭 (예정) | `QuestionDoc` + `QaJudgement[]` |
| F-11 정합 판정 | `ConceptGraph` + `Transcript` (+ 선택 `SlideDoc` — 숫자·방향 대조, F-04 `marks_match` — 다른 발표) → `AlignmentDoc` (§7) |
| 흐름 비교 (F-11 파생) | `ConceptGraph` + `AlignmentDoc` → `FlowDiff` (§7-E) |
| 산점도·diff 뷰 (프론트) | `AlignmentDoc.items[]` (`doc_weight` × `speech_weight`) + `summary` |
| 논리 흐름 탭 (프론트) | `FlowDiff.issues[]` + `order_tau` |
| F-12 삐약 청중석 | `ConceptGraph` + `AlignmentDoc` + `FlowDiff` → `ChatterDoc` |
| F-13 발표 점수 (폴백) | `AlignmentDoc` (+ `FlowDiff`) → `PresentationScore` |
| **F-14 채점표 채점** | 파이프라인 산출물 전부(선택) → `RubricScore` |
| F-17 말 속도·시간 배분 | `Transcript` + `Context` (+ `ConceptDoc`) → `PaceDoc` — 말로 건너뛴 장은 `slides[].skip_cue`(발화 원문)·`status` short (F-11 과 같은 규칙, `_spoken`) |
| F-18 음성 습관 | `Transcript` → `HabitDoc` (REP/FIL/PAUSE) |
| F-19 음성 종합 리포트 | `PaceDoc` + `HabitDoc` (+ `RubricScore`) → `ReportDoc` — `RubricScore.faults` 가 있으면 한 줄 총평·약점 첫 줄이 그것부터 말한다 |
| F-26 주장 그래프 | `ConceptGraph` + `SlideDoc` → `ClaimDoc` → F-08 탐침(`Probe`) (§8-I) |

---

## 10-A. F-14 채점표 채점 — `RubricScore`

기준 원본은 `docs/발표평가_상황별_채점표_v3.xlsx`, **코드가 읽는 원본은
`chuckchuck/rubric_v3.py`** 다 (런타임에 xlsx 를 읽지 않는다 — openpyxl 이 없고
파일명이 NFD 라 리터럴 경로 open 이 실패한다). 실행 계획은
[`RUBRIC_SCORING_PLAN.md`](RUBRIC_SCORING_PLAN.md).

### 구조

- **상황 4종** `school_project` · `product_launch` · `work_report` · `casual_peer`
- **클러스터 7종** `content` 내용 충실도 · `logic` 논리 구조 · `audience` 목적·청중 적합성 ·
  `clarity` 언어적 명료성 · `delivery` 음성적 전달 · `visual` 시각자료 활용 · `time` 시간 관리
- **세부 항목 39종** — 결정 채점 19 · LLM 채점 18 · 측정 불가 2 (25 음량 안정성, 26 핵심 구간 강조)

### 집계 (채점표 `점수산정` 시트와 같은 식)

```
클러스터 평균  avg_c = Σ(항목점수 × 내부가중치) / Σ(내부가중치)     # scored 항목만
유효 가중치    eff_c = W_c(상황) / Σ(살아있는 클러스터의 W)          # 빠진 몫을 재분배
최종          score = round(Σ(avg_c × eff_c))
```

**불변식** — 살아 있는 클러스터의 `effective_weight` 합은 1.0 · `score == min(cap, round(Σ contribution))`
(`cap` 이 null 이면 상한 없음) · 빠진 게 없으면 `effective_weight == weight/100` 으로 채점표 시트와 자릿수까지 같다.

**치명 결함 상한 `cap` · `faults` (09-30 held-out C-06·C-07)** — `faults[]` 는 `{kind, text, slide_no}`.
`contradiction`(정합이 **자료 원문과 견줘 확인한** 모순, `deck_quote` 가 있는 것만) · `skipped_slide`(말로 건너뛰어 핵심 개념이
빠진 장) 는 총점에 상한을 건다 — 하나면 69(채점표 구간 「40~69 부분적으로만 했다」 꼭대기), 하나 늘 때마다 10씩(59·49), 39 아래로는 안 내린다.
`unrelated_speech`(다른 발표 녹음)는 말을 이 자료와 견주는 항목(1~16·18·27~30·32·33)을 `unmeasured` 로 두고 총점은 39 까지 —
남은 자료·목소리 항목만으로는 점수가 오히려 올라(09-30 재현 38 → 81 「A」) 「이 자료의 발표」 로 매길 수 없다.
`align_fallback`(정합이 짐작뿐)은 1·4·5·30 을 `unmeasured` 로 둘 뿐 상한은 없다. `note` 가 한 줄로 같이 말한다.
28·32·33(배분)은 권장 시간을 **실제 발표 길이에 맞춰** 견준다 — 총 길이의 어긋남은 31번만 매긴다(「시간 관리 5/100」 삼중 청구).

### 항목 상태 — 셋을 절대 섞지 않는다

| `status` | 뜻 | 화면 문구 |
|---|---|---|
| `scored` | 실제로 매겼다 | 점수와 근거를 보여 준다 |
| `situation_excluded` | 이 상황에서는 평가하지 않는 항목 (채점표 가중치 0) | "이 상황에서는 평가하지 않아요" |
| `unmeasured` | 평가해야 하는데 이번에 못 쟀다 | "이번엔 측정할 수 없었어요" |

`unmeasured` 는 **0점이 아니다.** 가중치에서 빠지고 남은 항목에 다시 나뉜다.
뒤의 둘을 한 필드에 담으면 이번 개편이 걷어낸 그 블랙박스가 그대로 다시 생긴다.

`basis` 는 `full` | `partial` 이고, **영구 측정 불가 항목(25·26)은 계산에서 뺀다** —
이 둘까지 세면 `full` 이 영영 안 나오고 늘 켜진 경고는 아무도 안 읽는다.

### 응답 예시

```jsonc
{
  "score": 67,
  "situation": "school_project",
  "situation_label": "학교 프로젝트 (교수 대상)",
  "rubric_version": "v3",              // "v3-fallback" 이면 F-13 으로 매긴 것
  "clusters": [
    { "key": "content", "name": "내용 충실도", "weight": 26,
      "effective_weight": 0.26, "average": 70.4, "contribution": 18.3,
      "item_nos": [2, 3, 6], "status": "scored" }
  ],
  "items": [
    { "no": 1, "cluster": "content", "name": "핵심 개념 커버리지", "status": "scored",
      "score": 75, "weight": 9, "source": "det",
      "evidence": "핵심 개념 12개 중 9개를 실제로 설명했어요 (비중 반영 커버리지 75%)",
      "note": "" }
  ],
  "excluded": [12, 15, 16],
  "unmeasured": [25, 26],
  "basis": "full",
  "model": "solar",
  "note": "",
  "cap": null,                         // 09-30 — 치명 결함 상한 (없으면 null). 있으면 score ≤ cap
  "faults": []                         // 09-30 — [{kind, text, slide_no}] · kind: contradiction | skipped_slide | unrelated_speech | align_fallback
}
```

`cap`·`faults` 는 `to_dict` 에 언제나 있다(옛 저장본을 읽으면 null·`[]`, 모르는 `kind` 는 버린다). **화면이 할 일:** `faults` 가 있으면
점수보다 먼저 `text` 를 보이고(F-19 총평도 그것부터 말한다), `cap` 이 있으면 「상한 N점 — 까닭」 을 점수 옆에 붙인다.
`unrelated_speech` 면 등급 대신 「이 자료의 발표 녹음이 아니에요」 를 앞세운다.

**보증 (불변식):** ① 입력은 **전부 optional** — 없는 자료에 기대는 항목만 빠지고
나머지는 정상 채점된다 ② 아무것도 못 재면 0점 + `note`, 예외를 던지지 않는다
③ **`evidence` 가 빈 LLM 점수는 채택하지 않는다** — 근거 없는 숫자는 안 매긴 것만 못하다
④ 요청하지 않은 항목 번호는 버리고 점수는 0~100 으로 자른다
⑤ LLM 묶음 하나가 죽어도 그 항목만 `unmeasured` 가 되고 나머지는 살아남는다
⑥ 모의 STT 에서는 22·23·24 를 강제로 `unmeasured` 로 둔다 (균등 간격이라 침묵이
구조적으로 0 이고 말속도가 상수라, 그대로 채점하면 음성 전달이 가짜 만점이 된다).

### LLM 계약

`[TASK] rubric-score` — 묶음(클러스터)별로 한 번씩, 최대 4콜을 병렬로 부른다.

```json
{ "items": [ { "no": 2, "score": 78, "evidence": "발화에서 그대로 가져온 문장", "note": "한 문장 설명" } ] }
```

---

## 10-B. 세션 기록 · 피드백 — `SessionRecord` · `FeedbackEvent` (데모 브리지 보관소)

업로드 한 건 = 세션 하나. `POST /api/v1/parse` 응답에 `session_id` 가 실리고 이후 모든 호출이
그것을 보낸다. 디스크: `DEMO_DATA_DIR/sessions/YYYY/MM/DD/{session_id}/` (`demo/session_archive.py`).
id 는 `YYYYMMDDTHHMMSSZ_{8 hex}` — 앞은 사람·배치용 시간순 정렬, 뒤가 추측 불가능성.

```jsonc
// manifest.json — SessionRecord
{
  "session_id": "20260910T143512Z_3f9a2c7e",
  "uploaded_at": 1789000000.0, "updated_at": 1789000900.0,
  "consent_learning": true, "consent_at": 1789000000.0,   // 업로드 때 한 번, 이후 못 올린다
  "title": "발표", "file_name": "발표.pdf", "upload_ext": ".pdf",  // ext 는 매직바이트로 판별
  "upload_sha256": "…", "upload_bytes": 1234567,
  "context": { "situation": "학회", "audience": "심사위원", "duration_min": 10 },
  "artifacts": { "slide_doc": "slide_doc.json", "concept_graph": "artifacts/concept_graph.json" },
  "models": { "concept_graph": "solar-pro2", "habit_doc": "lora" },
  "code_version": "e20c05f",
  "qa_turn_count": 4, "feedback_count": 2
}
```

| 종류 | 파일 | 동의 없이도? |
|---|---|---|
| `slide_doc` · `transcript` | `slide_doc.json` · `transcript.json` | ✅ 캐시 (24h) |
| `concept_doc` `concept_graph` `alignment_doc` `flow_diff` `chatter_doc` `pace_doc` `habit_doc` `rubric_score` `report_doc` `question_doc` | `artifacts/<kind>.json` | ❌ 동의 세션만 |
| 원본 | `original.pdf` / `original.pptx` | ❌ 동의 세션만 |
| QA 턴 | `qa_turns.jsonl` `{at, question_id, question, answer, prior_answers, hints_shown, give_up, judgement, question_source}` — 09-30 부터 **서버가 만든 질문으로 채점한 턴만** 남고 `question_source` 는 `server`·`archive`·`mismatch` 중 하나 | ❌ |
| 피드백 | `feedback.jsonl` (아래) | ❌ |

`POST /api/v1/sessions/{id}/feedback` · `{ "events": [FeedbackEvent…] }` → `{session_id, accepted}`.
`DELETE /api/v1/sessions/{id}` → 204 (있든 없든).

```jsonc
// FeedbackEvent — 이것만이 라벨이다. 침묵·모델 출력·점수는 라벨이 아니다.
{
  "kind": "question_vote | judgement_dispute | rubric_dispute | habit_dispute",
  "target_id": "q3 | q:q3:r2 | 12 | span:41.2",
  "value": "up|down | wrong_verdict | too_high|too_low | not_habit",
  "at": 1789000500.0,
  "comment": "≤200자",
  "payload": { /* 판정 대상 스냅샷 — 질문 본문·판정·구간 텍스트. 프롬프트가 바뀌어도 라벨이 산다 */ }
}
```

---

## 10-C. F-23 상황 추정 — `ContextSuggestion`

자료를 올린 직후, 발화 없이 **자료만 보고** 발표 상황을 제안한다 (`POST /api/v1/suggest-context {slide_doc}`). 결정론 규칙, LLM 호출 0.

```json
{"situation": "work_report", "audience": "상사", "confidence": 0.86,
 "why": "1장 '실적' · 2장 '이슈' · 3장 '요청 사항'",
 "scores": {"school_project": 0, "product_launch": 1, "work_report": 12, "casual_peer": 0}}
```

- `situation`: `rubric_v3.SITUATIONS` 의 키. **빈 문자열이면 미정** — 화면은 아무것도 채우지 않는다.
- `confidence`: 1위 상황 점수 / 전체 신호 점수. 1위가 2점 미만이거나 비율 0.4 미만이면 미정.
- 화면 규칙: `#/new` 폼을 **미리 채우기만** 한다. 사용자가 고른 값이 언제나 이긴다. 자동 확정·바텀시트 없음.
- 측정: 동의 세션의 manifest context(사용자 최종값) vs 이 추정값의 일치율 (로드맵 A5).

## 10-D. F-23 내용 제안 — `deck_gaps` (결정론 1단)

`POST /api/v1/deck-gaps {slide_doc, situation?}` → 상황별 「청중이 기대하는 것」 항목마다 `present | weak | missing` 과 근거 장.
상황이 비면 F-23 추정값을 쓰고, 그래도 없으면 빈 목록 + 안내 문장.

```json
{"situation": "work_report", "situation_label": "업무 보고 (상사 대상)",
 "items": [{"key": "status", "label": "목표 대비 현황(수치)", "status": "present", "slide_nos": [2], "why": "2장 '현황' · 2장 '진행률'"},
           {"key": "risk", "label": "리스크", "status": "missing", "slide_nos": [], "why": "자료에 이 항목의 낱말이 없어요"}],
 "summary": {"present": 3, "weak": 1, "missing": 1}}
```

- 낱말 신호라 `present` 는 과대평가될 수 있다. 화면(Festa 뒤)은 **missing 을 먼저**, present 는 근거 장을 같이 낸다.
- 계약 타입은 아직 dict — LLM 2단을 붙이며 `DeckGapDoc` 으로 올린다 (로드맵 B6).

## 10-E. 09-29~09-30 QA 보강 — 프론트가 기대도 되는 필드

09-29 주장 그래프·함정 전제와 09-30 감사·레드팀 수정(`91d4c3d..f6d3854`)이 계약·응답에 더한 칸의 색인이다. **전부 더한 칸**이라
모르는 클라이언트는 무시해도 되고, 옛 세션·저장본은 기본값(null · `[]` · `""` · 키 없음)으로 읽힌다. 응답에만 붙는 칸(`degraded`·
`grounded_on_*`·429/502/503 본문)은 **데모 브리지(`demo/bridge.py`) 기준**이다 — `server/app.py` 는 아직 싣지 않는다.

| 필드 | 어디 (계약 / 라우트) | 날짜 | 화면이 할 일 | 자세히 |
|------|------|------|------|------|
| `Question.basis` (`source`·`slot`·`rank`·`probe`·`evidence`·`checks`) | `QuestionDoc.questions[]` · `/questions` | 09-29 | 접힌 「이 질문의 근거」 — 한 줄 + 장 번호까지만. null 이면 안 그린다 | §8-E |
| `basis.reason`·`background`·`contrast`·`contrast_quote` | `QuestionBasis` | 09-30 | `contrast` 쌍은 「모르겠어요」 보기. 인용문은 답하기 전에 안 보인다 | §8-E |
| `Question.trap_premise` | `QuestionDoc.questions[]` | 09-29 | 통과·닫힘 전에는 `fact`·골자를 펼치지 않는다. 함정 `why` 는 중립 문장으로 | §8-E |
| `QaJudgement.guard`·`guard_reason` | `/qa/judge` | 09-30 | `guard_reason` 은 되물음·결손과 따로 한 줄. `guard` 이름은 하네스·리포트용 | §8-F |
| `QaJudgement.close_reason` (파생) | `/qa/judge` | 09-30 | 결과 화면은 `good` 만 「자기 말로 지켰어요」, `rounds`·`guard` 는 「다시 볼 곳」 | §8-F |
| `guard_blocked` | 계약 속성 — **직렬화하지 않는다** | 09-30 | 없음 (요청 바디로 출구를 못 열게) | §8-F |
| `grounded_on_server`·`grounded_on_deck` | `/qa/judge` 응답 | 09-30 | `grounded_on_deck: false` 면 「자료 본문 없이 판정했어요」 | §8-F |
| `degraded`·`degraded_notes` | `/questions`·`/qa/judge`·`/claims`·`/papers` 응답(언제나) · `/concepts`·`/graph`(반쪽일 때만) | 09-30 | `degraded_notes` 를 한 줄로. `question_unverified`·`question_mismatch` 는 띄우지 않는다 | 아래 |
| `missing_slides` | `/concepts` 응답(반쪽일 때) · 502 `concepts_incomplete` 본문 | 09-30 | 「N장 개념을 못 받았어요 — 다시 분석」 | §5-B |
| `SlideConcepts.missing` | `ConceptDoc.slides[]` (참일 때만 키) | 09-30 | 그 장에 「개념을 못 받았어요」 | §5-B |
| `ConceptGraph.thesis` | `/graph` (있을 때만 키) — 주제 **노드 id** | 09-30 | 주제 노드 강조 | §6-B |
| `ConceptGraph.degraded` | `/graph` (있을 때만 키) — `links` | 09-30 | 「연결 보강을 못 했어요」 한 줄 | §6-B |
| `AlignmentDoc.speech_match`·`speech_overlap`·`basis`·`skipped_slides` | `/alignment` | 09-30 | `unrelated` 면 「다른 발표 녹음」, `fallback` 이면 누락을 확정으로 안 쓴다, 건너뛴 장 카드 | §7-B |
| `AlignmentItem.decided_by`·`deck_quote`·`deck_slide_no` | `/alignment` `items[]` | 09-30 | 모순 카드에 자료·발화 인용을 나란히 | §7-B |
| `SlidePace.skip_cue` | `/pace` `slides[]` (언제나, 비면 `""`) | 09-30 | 비지 않으면 「말로 건너뛴 장: «cue»」 — 머문 시간이 있어도 `status` 는 `short` | §10 F-17 |
| `RubricScore.cap`·`faults` | `/rubric` (언제나, null·`[]`) | 09-30 | `faults[].text` 를 점수보다 먼저, `cap` 은 「상한 N점」 | §10-A |
| `PaperDoc.status` | `/papers`·`/papers/search` (언제나) | 09-30 | 문헌이 비었을 때 「검색이 막힘」 과 「맞는 논문 없음」 을 가른다 | §8-G |
| `MemoryDoc.scoped` | `/memory` | 09-30 | (로그) 거짓이면 이번 발표를 모르고 만든 기억 | §8-H |
| `ConceptMemory.passes`·`closes`·`deck_keys` (+ `stalled` 뜻) | `/memory` `concepts[]` | 09-30 | 「지난번에 못 넘긴 개념」 은 `stalled` 만. 설득 횟수는 `closes.good` | §8-H |
| `ClaimDoc`·`Claim`·`ClaimQuote` | `/claims` (+ `degraded` 09-30) | 09-29 | 직접 안 그린다 (`text` 는 해요체가 아니다) | §8-I |
| `Probe` · `QaTriage.probes` | `basis.probe` · 브리지 내부 | 09-29 | `basis.probe.kind` 로 근거 한 줄을 고른다 | §8-I |
| `qa_turns[].question_source` | 세션 보관소 `qa_turns.jsonl` | 09-30 | 없음 (F-25 기억·학습 묶음이 읽는다) | §10-B |
| `GET /api/v1/team` → `{ "team": bool }` | 새 라우트 | 09-30 | 참이면 샘플 발표·샘플 리포트·개발 화면을 연다 | 아래 |
| 요청 `purpose: "qa_answer"` | `POST /api/v1/transcribe` 요청 칸 | 09-30 | 답변 받아쓰기에 싣는다 | 아래 |

### `degraded` 코드 — 폴백은 폴백이라고 말한다

`degraded` 는 코드 목록, `degraded_notes` 는 **같은 순서**의 해요체 한 문장(`DEGRADED_NOTES`)이라 그대로 띄워도 된다. 모르는 코드는
코드 문자열이 그대로 문장 자리에 온다.

| 코드 | 어느 응답 | 뜻 | 다시 하면 |
|------|------|------|------|
| `slide_doc_missing` | `/questions`·`/qa/judge` | 자료 본문을 못 찾아 자료와 대조하지 않았다 (근거 인용·주장·함정 전제가 빠진다) | 자료를 다시 올려야 한다 |
| `question_unverified` | `/qa/judge` | 서버가 만든 질문을 못 찾아 화면의 질문으로 판정 — 기록에 안 남는다 | — |
| `question_mismatch` | `/qa/judge` | 화면 질문이 서버 것과 달라 서버 질문으로 판정 | — |
| `claims_rule_only` | `/questions`·`/claims` | 주장 LLM 이 죽어 규칙 주장만 | 120초 뒤 다시 만든다 |
| `claims_failed` · `claims_timeout` | `/questions` | 주장 없이 (실패 · `DEMO_CLAIMS_WAIT_SEC` 90초 넘김) | 120초 뒤 |
| `papers_timeout` | `/questions` | 문헌 검색이 6초를 넘겨 자료 인용 문헌만 — 검색은 뒤에서 마저 해 캐시를 채운다 | 다음 요청 |
| `papers_unavailable` · `papers_partial` | `/questions`·`/papers` | 검색 실패·통로 쉬는 중(180초) → 자료 인용만 · 일부 통로만 실패 | 120~180초 뒤 |
| `papers_failed` | `/questions` | 문헌 없이 | 120초 뒤 |
| `memory_failed` | `/questions`·`/qa/judge` | 지난 리허설 기억 없이 | 120초 뒤 |
| `concepts_missing` | `/concepts` | 개념을 못 받은 장(`missing_slides`)은 개념 없이 | 다시 분석 (캐시에 안 담았다) |
| `links` | `/graph` | 연결 보강을 못 해 처음 그린 연결로 | 다시 분석 (캐시에 안 담았다) |

### HTTP 오류 본문 (09-30 추가분)

오류 본문은 언제나 `{error, message}` 다 — `message` 는 그대로 띄워도 되는 해요체 한 문장이고, 벤더 응답 본문·서버 경로는 싣지 않는다.
`retry_after` 는 초(int).

| 상태 | `error` | 어느 경로 | 더 실리는 칸 |
|------|------|------|------|
| 429 | `rate_limited` | 과금 경로 전부(`PAID_PATHS`: `/parse`·`/concepts`·`/transcribe`·`/graph`·`/alignment`·`/chatter`·`/habits`·`/report`·`/questions`·`/rubric`·`/qa/judge`·`/strategy`·`/papers`·`/papers/search`·`/claims`·`/memory`) + `/sessions/{id}/qa/judge` | `rate_limited: true` · `scope` · `retry_after` |
| 503 | `upstream_timeout` | POST 전부 — 외부 LLM·검색이 제시간에 안 답했다 | `retry_after: 10` |
| 503 | `upstream_unavailable` | POST 전부 — 외부에 연결하지 못했다 | `retry_after: 10` |
| 502 | `upstream_failed` | POST 전부 — 외부가 오류로 답했다 | — |
| 502 | `concepts_incomplete` | `/concepts` — 빠진 장이 너무 많아 분석을 멈췄다 | `missing_slides: int[]` · `retry_after: 10` |
| 502 | `graph_empty` | `/graph` — 노드를 하나도 못 만들었다 | `retry_after: 10` |
| 502 | `graph_failed` | `/graph` — 알아볼 수 없는 모양으로 답했다 | `retry_after: 10` |
| 400 | `bad_request` | `/graph` — 개념 문서에 장이 없다 · `/qa/judge` — `session_id` 모양·질문 형식·질문 없음 | — |
| 503 | `memory_failed` | `/memory` — 기억을 못 읽었다 (「없음」 과 다르다) | `retry_after: 120` |
| 400 | `fixture_disabled` | `/transcribe` — 공개 방문자가 샘플 받아쓰기(`fixture`)를 요청 (mock·팀만) | — |

```jsonc
// 429 — 예전 칸(error·message·retry_after)은 그대로, rate_limited·scope 를 더했다 (09-30 H-15)
{ "error": "rate_limited", "rate_limited": true, "scope": "session", "retry_after": 12,
  "message": "요청이 너무 잦아요. 12초 뒤에 다시 시도해 주세요." }
```

`scope`: `session` = 이 세션의 분당 상한(`DEMO_RATE_LIMIT_PER_MIN`, 기본 30) · `ip` = IP 전체 천장(`DEMO_RATE_LIMIT_IP_PER_MIN`, 기본 180)
이거나 세션 id 없는 요청(업로드·`"flat"`)을 IP 칸으로 센 것(상한 30). 세션 id 는 본문 `session_id` → `/sessions/{id}/` 경로 순으로 찾는다.
`/concepts`·`/graph` 는 외부 지연·끊김이면 위 503 과 같은 본문이다. 예전부터 있던 코드(`session_missing` 409 · `judge_failed`·
`questions_failed`·`claims_failed`·`papers_failed` 502 · `too_large` 413 · `/claims` 의 `slide_doc_missing` 409)는 그대로다.

지금 프론트(`chuckchuck_bridge.js judgeRetryPlan`)의 판정 재시도: 429 는 `retry_after`(없으면 5초, 1~60초)만큼 기다려 두 번까지 — 판정
실패로 세지 않는다. 503 `upstream_*` 은 한 번(1~10초). 502 는 다시 보내지 않고 `message` 를 띄운다.

### 새 라우트 · 요청 칸

- `GET /api/v1/team` → `{ "team": bool }` — 이 브라우저가 `/auth`(팀 코드, `cc_team` 쿠키)를 거쳤거나 브리지를 `DEMO_DEV_ROUTES=1` 로
  띄웠나. 참이면 샘플 발표·샘플 리포트·개발용 화면(`#/replay`·`#/test/qa` …)을 연다. `/auth` 는 HTML 폼이라 JSON 계약이 아니다
  (`DEMO_TEAM_CODE` 가 비면 404).
- `POST /api/v1/transcribe` 요청 `purpose: "qa_answer"` — 질문 코칭의 답변 한 마디. 세션의 발표 받아쓰기(`transcript` 아티팩트)로
  **보관하지 않는다**(보관하면 새로고침 복구·기억이 답변 한 줄을 발표로 읽었다). 그래서 `session_id` 를 실어도 되고, 실으면 요청 제한을
  세션 칸으로 센다.
- `/api/v1/qa/judge` 본문 `session_id` 는 발급 모양 또는 `"flat"` — 경로 `{id}` 보다 본문이 먼저다 (§8-F).

## 11. 구현 파일

| 파일 | 역할 |
|------|------|
| `chuckchuck/contracts.py` | ours 타입 정의 (유일 결합점) |
| `demo/session_archive.py` | 세션 보관소 — id 발급·동의·만료·삭제 (§10-B) |
| `chuckchuck/f01_parse.py` | Upstage → SlideDoc |
| `chuckchuck/providers/stt_impl.py` | A.X → Word[] |
| `chuckchuck/f05_stt.py` | Word[] + SlideMark[] → Transcript |
| `chuckchuck/f06_concepts.py` | SlideDoc+Context → ConceptDoc |
| `chuckchuck/f07_graph.py` | ConceptDoc(+SlideDoc) → ConceptGraph |
| `chuckchuck/f08_questions.py` | ConceptGraph(+AlignmentDoc·FlowDiff) → QaTriage → QuestionDoc |
| `chuckchuck/f09_judge.py` | Question+답변 → QaJudgement |
| `chuckchuck/f11_align.py` | ConceptGraph+Transcript → AlignmentDoc |
| `chuckchuck/f11_flow.py` | ConceptGraph+AlignmentDoc → FlowDiff (LLM 없음) |
| `chuckchuck/f26_claims.py` · `chuckchuck/_probes.py` | ConceptGraph+SlideDoc → ClaimDoc · ClaimDoc(+자료 원문) → Probe[] (§8-I) |
| `chuckchuck/sdk/rehearsal-recorder.js` | audio + SlideMark[] |

질문·이슈 올릴 때 **ours JSON 예시**만 붙여 주세요. raw는 어댑터 담당자만 보면 됩니다.
