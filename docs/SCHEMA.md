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

**안 함:** 부모-자식 트리 → **F-07 책임**

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

입력: `ConceptGraph` + `Transcript` (+ 선택 `Context`)
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

## 8. 한눈에 보기

| 기능 | 원본(raw) | 후처리(ours) | 변환 위치 |
|------|-----------|--------------|-----------|
| F-01 | Upstage `elements[]` | `SlideDoc` | `f01_parse.py` |
| F-02 | 프론트 폼 | `Context` | 프론트 → JSON |
| F-03 | MediaRecorder | audio blob | `sdk/rehearsal-recorder.js` |
| F-04 | 클릭 시각 | `SlideMark[]` | 同上 |
| F-05 | A.X `utterances[].words[]` | `Transcript` | `stt_impl.py` + `f05_stt.py` |
| F-06 | LLM JSON 문자열 | `ConceptDoc` | `f06_concepts.py` |
| F-07 | LLM JSON 문자열 | `ConceptGraph` | `f07_graph.py` |
| F-11 | LLM JSON 문자열 | `AlignmentDoc` | `f11_align.py` |
| F-11 파생 | `ConceptGraph`+`AlignmentDoc` (LLM 없음) | `FlowDiff` | `f11_flow.py` |

---

## 9. 다음 모듈이 받을 것

| 다음 | 필요한 ours |
|------|-------------|
| F-07 그래프 | `ConceptDoc` (+ 선택 `SlideDoc`) |
| F-08~10 질문 코칭 | `ConceptGraph` (개념 경로·근거 슬라이드·우선순위) + `Transcript.by_slide` |
| F-11 정합 판정 | `ConceptGraph` + `Transcript` → `AlignmentDoc` (§7) |
| 흐름 비교 (F-11 파생) | `ConceptGraph` + `AlignmentDoc` → `FlowDiff` (§7-E) |
| 산점도·diff 뷰 (프론트) | `AlignmentDoc.items[]` (`doc_weight` × `speech_weight`) + `summary` |
| 논리 흐름 탭 (프론트) | `FlowDiff.issues[]` + `order_tau` |
| F-17 말 속도 | `Transcript.words` (+ marks) |

---

## 10. 구현 파일

| 파일 | 역할 |
|------|------|
| `chuckchuck/contracts.py` | ours 타입 정의 (유일 결합점) |
| `chuckchuck/f01_parse.py` | Upstage → SlideDoc |
| `chuckchuck/providers/stt_impl.py` | A.X → Word[] |
| `chuckchuck/f05_stt.py` | Word[] + SlideMark[] → Transcript |
| `chuckchuck/f06_concepts.py` | SlideDoc+Context → ConceptDoc |
| `chuckchuck/f07_graph.py` | ConceptDoc(+SlideDoc) → ConceptGraph |
| `chuckchuck/f11_align.py` | ConceptGraph+Transcript → AlignmentDoc |
| `chuckchuck/f11_flow.py` | ConceptGraph+AlignmentDoc → FlowDiff (LLM 없음) |
| `chuckchuck/sdk/rehearsal-recorder.js` | audio + SlideMark[] |

질문·이슈 올릴 때 **ours JSON 예시**만 붙여 주세요. raw는 어댑터 담당자만 보면 됩니다.
