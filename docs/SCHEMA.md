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
ConceptDoc  ──► [LLM raw]     ──► ConceptTree       (F-07)
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

## 6. F-07 개념 트리

**책임 한 줄:** 장 단위 개념(`ConceptDoc`)을 발표 **전체** 기준으로 묶어 위계(트리)와 구획(section)을 만든다.

F-06과의 경계: F-06은 "이 장 안에 뭐가 있나", F-07은 "장들이 전체에서 어디에 앉나".
`section` / `slide_role`은 앞뒤 장을 함께 봐야 정해지므로 F-07 책임이다
([`DOCUMENT_PARSE_POSTPROCESS.md` §3-4](./DOCUMENT_PARSE_POSTPROCESS.md)).

### 6-A. 원본 — LLM (Solar / A.X …)

`ConceptDoc` 전체를 한 번에 보여주고 JSON만 요청한다. 배치로 쪼개지 않는다 —
위계는 전역 시야가 있어야 정해지고, 배치로 나누면 배치 경계에서 부모를 잃는다.

기대 raw(모델 출력):

```jsonc
{
  "nodes": [
    {
      "id": "contrast",
      "label": "Contrastive Learning",
      "parent_id": null,
      "slide_nos": [4],
      "summary": "한 줄 설명",
      "importance": "core"
    }
  ],
  "sections": [
    { "name": "서론 — 배경 개념", "slide_role": "intro", "slide_nos": [1, 2, 3] }
  ]
}
```

모델이 준 `depth`는 신뢰하지 않는다. `parent_id` 체인에서 **다시 계산**한다.

### 6-B. 후처리 — `ConceptTree`

입력: `ConceptDoc` (+ 선택 `Context` → 중요도 가중)
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
      "depth": 1,
      "parent_id": null,
      "slide_nos": [4],
      "summary": "같은 데이터는 가깝게, 다른 데이터는 멀게 학습",
      "importance": "core",
      "weight": 0.91
    },
    {
      "id": "joint",
      "label": "공동 임베딩 정렬",
      "depth": 2,
      "parent_id": "contrast",
      "slide_nos": [7, 8],
      "summary": "세 모달리티를 하나의 임베딩 공간에 정렬",
      "importance": "core",
      "weight": 0.79
    }
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
| `nodes[].id` | string | ✅ | **안정 키**. 영소문자·숫자·`-`. 트리 안에서 유일 |
| `nodes[].label` | string | ✅ | 개념 이름 (화면 표시용) |
| `nodes[].depth` | int | ✅ | 루트=1. `parent_id` 체인에서 계산 |
| `nodes[].parent_id` | string \| null | ✅ | 루트면 `null`. 없는 id를 가리키면 루트로 강등 |
| `nodes[].slide_nos` | int[] | ✅ | **조인 키**. 개념 하나가 여러 장에 걸칠 수 있어 배열 |
| `nodes[].summary` | string | ✅ | 한 줄 설명. 없으면 `""` |
| `nodes[].importance` | `"core"`\|`"support"` | ✅ | 근거 슬라이드의 `ConceptDoc.importance`에서 승계 |
| `nodes[].weight` | float | ✅ | 0.0~1.0 중요도. 화면 정렬·질문 우선순위용 |
| `sections[].name` | string | ✅ | 구획 이름 (예: `"본론 — 제안 방법"`) |
| `sections[].slide_role` | enum | ✅ | `cover`\|`intro`\|`body`\|`conclusion`\|`closing` |
| `sections[].slide_nos` | int[] | ✅ | 이 구획에 속한 장 번호 |

**보증(어댑터가 지키는 불변식):**

1. `id`는 유일하다.
2. `parent_id`는 존재하는 `id`이거나 `null`이다.
3. 순환이 없다. 순환이 생기면 그 고리의 노드를 루트로 끊는다.
4. `depth`는 `parent_id` 체인 길이와 항상 일치한다.
5. `slide_nos`는 `1..total_slides` 안의 값만 남는다.
6. `sections[].slide_role`은 위 enum 밖이면 `body`로 떨어진다.

**안 함:** 개념별 이해 판정·confidence·근거 발화 → **F-11 책임**.
F-07은 골격만 만들고, 상태는 뒤 단계가 `id`로 붙인다.

코드: `f07_tree.build_tree()` → `ConceptTree`

---

## 7. 한눈에 보기

| 기능 | 원본(raw) | 후처리(ours) | 변환 위치 |
|------|-----------|--------------|-----------|
| F-01 | Upstage `elements[]` | `SlideDoc` | `f01_parse.py` |
| F-02 | 프론트 폼 | `Context` | 프론트 → JSON |
| F-03 | MediaRecorder | audio blob | `sdk/rehearsal-recorder.js` |
| F-04 | 클릭 시각 | `SlideMark[]` | 同上 |
| F-05 | A.X `utterances[].words[]` | `Transcript` | `stt_impl.py` + `f05_stt.py` |
| F-06 | LLM JSON 문자열 | `ConceptDoc` | `f06_concepts.py` |
| F-07 | LLM JSON 문자열 | `ConceptTree` | `f07_tree.py` |

---

## 8. 다음 모듈이 받을 것

| 다음 | 필요한 ours |
|------|-------------|
| F-07 트리 | `ConceptDoc` |
| F-08~10 질문 코칭 | `ConceptTree` (개념 경로·근거 슬라이드) + `Transcript.by_slide` |
| F-11 설명 판정 | `ConceptTree` + `Transcript.by_slide` |
| F-17 말 속도 | `Transcript.words` (+ marks) |

---

## 9. 구현 파일

| 파일 | 역할 |
|------|------|
| `chuckchuck/contracts.py` | ours 타입 정의 (유일 결합점) |
| `chuckchuck/f01_parse.py` | Upstage → SlideDoc |
| `chuckchuck/providers/stt_impl.py` | A.X → Word[] |
| `chuckchuck/f05_stt.py` | Word[] + SlideMark[] → Transcript |
| `chuckchuck/f06_concepts.py` | SlideDoc+Context → ConceptDoc |
| `chuckchuck/f07_tree.py` | ConceptDoc → ConceptTree |
| `chuckchuck/sdk/rehearsal-recorder.js` | audio + SlideMark[] |

질문·이슈 올릴 때 **ours JSON 예시**만 붙여 주세요. raw는 어댑터 담당자만 보면 됩니다.
