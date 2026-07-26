<!-- 이 파일: Document Parse raw → SlideDoc → ConceptDoc 후처리 합의안입니다. -->

# 척척발표 · Document Parse 후처리

> Upstage Document Parse **raw → SlideDoc**, 이어서 **ConceptDoc** 까지의 후처리 합의안.  
> 초안을 raw 실측·모듈 경계에 맞춰 확정한 문서.  
> 구현·리뷰의 단일 기준. 상세 벤더 매핑은 [`SCHEMA.md`](./SCHEMA.md), 정책은 [`DEV_POLICY.md`](./DEV_POLICY.md).

**상태:** 합의안 (2026-07-22)  
**raw 근거:** `fixtures/raw/*.keys.json` (RINGLE 덤프 — element keys: `id`, `page`, `category`, `content`, `coordinates`)

---

## 0. 한 줄 목적

| 산출물 | 목적 | LLM |
|--------|------|-----|
| **SlideDoc (F-01)** | raw → **분석 가능한 구조** (노이즈 제거 + 밀도/구성 신호). 이후 F-06·F-07이 조인·분기할 수 있게 | ❌ |
| **ConceptDoc (F-06)** | SlideDoc → **장 단위 의미** (topic / concepts / 수치). F-07 트리의 입력 | ✅ |

하지 않는 것:

- F-01에 발화 시간 추정 넣기 → **F-05 Transcript / marks**가 진실
- F-06에 서론·본론·구획 잡기 → **F-07** 책임
- raw에 없는 필드를 계약에 필수로 넣기

---

## 1. 초안 → 최종 결정 요약

| 초안 | 최종 | 왜 |
|------|------|-----|
| F-01 지표 / F-06 LLM 층 분리 | **채택** | 정책·cascade와 동일 |
| `blocks` 삭제, categories+raw_text만 | **blocks 유지 + 지표 추가** | categories는 라벨 집합, raw_text는 통짜. **구조 단위는 blocks뿐** — 재처리·유형 분기·트리 전 단계에 필요 |
| `estimated_speaking_time` | **제외** | 글자수÷초는 가짜 신호. 시간은 STT |
| `visual_type` diagram/photo/decorative | **Upstage category만** | raw에 해당 enum 없음 |
| `title_font_size` | **제외** | 전용 키 없음. html `font-size`는 불안정 → 계약 필수 금지 |
| `alignment` | **1차 optional 채택** | coords로 근사. 2단 레이아웃·글/도식 쏠림 등 **구조 신호**. 애매하면 `null` |
| `visual_char_count` | **제외** | “시각 안 글자” 정의 없음 |
| `text_sparse` / `image_only` | **유지 (아래 2-6)** | 새 숫자 필드의 **미리 계산해 둔 bool**. 별도 정보가 아님 |
| `section` / `slide_role` | **F-07로** | 문서 전체 논리 구조 |
| `key_figures` | **F-06에 채택** | 수치 개념 → 트리·질문·진단에 직접 쓰임 |

---

## 2. SlideDoc (F-01) 최종 스키마

### 2-1. JSON

```jsonc
{
  "file_name": "전략금속_선택적회수_이온교환수지.pptx",
  "total_slides": 15,
  "slides": [
    {
      "slide_no": 8,
      "title": "전략 금속군별 선택적 회수 (1) — 리튬 및 이차전지 양극재 금속",
      "blocks": [
        { "category": "heading1", "text": "전략 금속군별 선택적 회수 (1) — …" },
        { "category": "paragraph", "text": "리튬(Li) 회수: …" },
        { "category": "figure", "text": "…" }
      ],
      "categories": ["heading1", "paragraph", "figure"],
      "total_char_count": 210,
      "line_count": 6,
      "has_visual": true,
      "visual_type": ["figure"],
      "alignment": "left",
      "text_sparse": false,
      "image_only": false,
      "raw_text": "리튬(Li) 회수: 이온 반경이 극도로 작아 … 순도 99% 이상 배터리급 소재 확보"
    }
  ]
}
```

### 2-2. 필드 정의

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `file_name` | string | ✅ | 원본 파일명 |
| `total_slides` | int | ✅ | 슬라이드 수 |
| `slides[].slide_no` | int | ✅ | **조인 키** (1부터) |
| `slides[].title` | string | ✅ | heading 원문. 없으면 `""` |
| `slides[].blocks[]` | `{category, text}` | ✅ | 파싱 구조 단위. **삭제하지 않음** |
| `slides[].categories` | string[] | ✅ | 해당 장에 등장한 category 고유 목록 |
| `slides[].total_char_count` | int | ✅ | 본문 글자 수 (**header/footer 제외**) |
| `slides[].line_count` | int | ✅ | 줄(불릿) 수 — 본문 기준 |
| `slides[].has_visual` | bool | ✅ | figure/chart/image/table 중 하나라도 있으면 true |
| `slides[].visual_type` | string[] | ✅ | Upstage category 중 시각 관련만. 없으면 `[]` |
| `slides[].alignment` | `"left"` \| `"right"` \| `"center"` \| null | ○ | 본문 blocks bbox 중심 x 근사. 애매/coords 없으면 `null` |
| `slides[].text_sparse` | bool | ✅ | **편의 플래그** — `total_char_count`로 계산 (2-6) |
| `slides[].image_only` | bool | ✅ | **편의 플래그** — sparse + visual (2-6) |
| `slides[].raw_text` | string | ✅ | 정제 본문 (header/footer 제외, blocks 연결) |

### 2-3. `visual_type` 허용 값 (1차)

Upstage raw category에 존재하는 것만:

`figure` | `chart` | `table` | `image`

(캡션은 `categories`에는 들어갈 수 있으나 `visual_type`에는 넣지 않음.)

### 2-4. `alignment` 근사 규칙 (1차)

- 입력: 본문 blocks에 대응하는 raw `coordinates` (정규화 0~1)
- 각 block bbox 중심 `cx = (x_min + x_max) / 2` 의 평균(또는 글자 수 가중)
- 구간 예: `cx < 0.40` → `left`, `cx > 0.60` → `right`, 그 사이 → `center`
- coords 없음 / block 0개 → `null`
- **슬라이드 하나당 요약값**이지, 블록별 배치는 아님

### 2-5. 노이즈 제거 규칙

발표 자료에는 매 장 반복되는 **머리글·바닥글**이 많다.  
후처리에서는 이걸 **본문이 아니라고 보고 뺀다.**

**빼는 것 (노이즈)**  
- Upstage category가 `header` 또는 `footer` 인 덩어리  
- 예: “링글 공모전”, “SAIGHT”, 페이지 장식 문구

**남기는 것 (본문)**  
- `heading1`, `paragraph`, `list`, `table`, `figure`, `chart`, …  
- 이걸로 `blocks` / `raw_text` / 글자 수 / 줄 수를 만든다

**한 줄 규칙**  
> 머리글·바닥글은 SlideDoc 본문에 넣지 않는다.  
> 제목·본문·불릿·표·그림만 남긴다.

(디버깅용으로 raw 파일에는 그대로 남아 있다. ours SlideDoc에만 안 넣으면 된다.)

### 2-6. `text_sparse` / `image_only` 가 뭔 말인가

이 둘은 **새로운 정보가 아니다.**  
이미 있는 숫자·플래그를 bool로 미리 접어 둔 **편의 필드**다.

| 플래그 | 계산식 (현행) | 뜻 |
|--------|---------------|-----|
| `text_sparse` | `total_char_count < 20` | 이 장은 글이 거의 없다 |
| `image_only` | `text_sparse && has_visual` | 글은 거의 없고 시각자료가 있다 |

왜 같이 두나?

- **지금** F-06 코드/프롬프트가 `text_sparse` / `image_only`를 그대로 읽고 있음 → 하위 안 깨려고 SlideDoc에 계속 실어 줌
- **앞으로** F-06은 `total_char_count`, `has_visual`을 직접 봐도 됨. 그때 bool은 deprecated 가능

한 줄:  
`total_char_count` / `has_visual` = **원천 데이터**  
`text_sparse` / `image_only` = **그걸 보고 만든 단축 스위치** (중복이지만 마이그레이션용)

### 2-7. 의도적으로 넣지 않는 필드

| 필드 | 이유 |
|------|------|
| `estimated_speaking_time` | F-05가 진실 |
| `title_font_size` | raw 전용 필드 없음 |
| `visual_char_count` | 정의 모호 |
| `title_length` | `len(title)`로 충분 — 계약 비대 방지 |

---

## 3. ConceptDoc (F-06) 최종 스키마

### 3-1. JSON

```jsonc
{
  "file_name": "전략금속_선택적회수_이온교환수지.pptx",
  "total_slides": 15,
  "model": "solar",
  "slides": [
    {
      "slide_no": 8,
      "title": "전략 금속군별 선택적 회수 (1) — 리튬 및 이차전지 양극재 금속",
      "topic": "이온 반경이 작은 리튬은 LIS 탈삽입으로, 유사한 니켈·코발트는 리간드 안정도 차이로 순차 분리한다",
      "keywords": ["리튬 이온 체(LIS)", "순차 분리", "안정도 상수(logK)"],
      "concepts": [
        "리튬 이온 체(LIS): 리튬 이온만 격자에 끼웠다 빼는 탈삽입으로 선택 회수하는 산화물 수지",
        "순차 분리: pH를 단계적으로 바꿔 니켈을 먼저, 코발트를 나중에 회수하는 전략"
      ],
      "key_figures": [
        { "item": "나트륨 분리율", "value": 95, "unit": "%", "source": "본문" },
        { "item": "코발트 순도", "value": 99, "unit": "%", "source": "본문" }
      ],
      "importance": "core",
      "raw_text": "리튬(Li) 회수: 이온 반경이 극도로 작아 … 순도 99% 이상 배터리급 소재 확보"
    }
  ]
}
```

### 3-2. 필드 정의

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `file_name` | string | ✅ | 파일명 |
| `total_slides` | int | ✅ | 장 수 |
| `model` | string | ✅ | LLM 이름 (`solar` / `ax` / …) |
| `slides[].slide_no` | int | ✅ | **조인 키** |
| `slides[].title` | string | ✅ | **SlideDoc title 승계**. heading 없을 때만 유추 |
| `slides[].topic` | string | ✅ | 한 줄 요약 |
| `slides[].keywords` | string[] | ✅ | 중요도순 |
| `slides[].concepts` | string[] | ✅ | `"이름: 설명"` 형식. **트리(부모-자식) 만들지 않음** |
| `slides[].key_figures` | object[] | ✅ | 유효 수치. 없으면 `[]` |
| `slides[].importance` | `"core"` \| `"support"` | ✅ | Context 가중 |
| `slides[].raw_text` | string | ✅ | 근거 대조용 (SlideDoc에서 복사) |

### 3-3. `key_figures[]` 항목

| 필드 | 타입 | 설명 |
|------|------|------|
| `item` | string | 수치 이름 |
| `value` | number \| string | `"약 95"`·범위 대비. number 강제 금지 |
| `unit` | string | `%`, `억` 등. 없으면 `""` |
| `source` | string | 권장: `"본문"` \| `"표"` \| `"차트"` |

### 3-4. F-07로 미루는 필드 — F-07이 뭐길래?

**F-07 = 개념 트리** (만드는 중).  
장마다 뽑은 개념(`ConceptDoc`)을 받아서, 발표 **전체** 기준으로 묶고 위계를 만드는 단계다.

| | F-06 (지금) | F-07 (다음) |
|--|-------------|-------------|
| 보는 범위 | **한 장** | **여러 장·발표 전체** |
| 하는 일 | 이 장 주제가 뭐고, 핵심 개념·수치가 뭔가 | 장들을 서론/본론으로 묶고, 개념 부모-자식 트리 |
| 예 | “이 장은 리튬 회수 공정” | “3~8장은 본론 — 금속군별 회수” |

그래서 초안에 있던 아래 둘은 **F-06에 넣지 않는다.**

| 필드 | 뜻 | 왜 F-07인가 |
|------|-----|-------------|
| `section` | “본론 — 회수 공정” 같은 **구획 이름** | 한 장만 보면 구획을 안정적으로 못 정함. 앞뒤 장을 봐야 함 |
| `slide_role` | 표지 / 서론 / 본론 / 결론 / 마무리 | 발표 **구성상 역할** = 전체 목차 문제. 장 단독 LLM이면 장마다 흔들림 |

한 줄:  
> F-06은 “이 장 안에 뭐가 있나”, F-07은 “장들이 전체에서 어디에 앉나”.

---

## 4. 모듈 간 데이터 흐름

```
Upstage raw (elements)
    │  F-01: 노이즈 제거 + blocks/지표 (LLM ❌)
    ▼
 SlideDoc
    │  F-06: 의미 추출 (+ 선택 Transcript로 sparse 보완)
    ▼
 ConceptDoc
    │  F-07 (예정): section / slide_role / 부모-자식 트리
    ▼
 ConceptGraph …
```

조인: 항상 `slide_no`.  
시간·속도: `Transcript` (+ `SlideMark[]`), SlideDoc에 넣지 않음.

---

## 5. raw 실측 메모 (계약에 넣지 말 것)

RINGLE `dump_parse_raw` 기준:

- element keys: `id`, `page`, `category`, `content`, `coordinates`
- `content`: `html`, `markdown`, `text`
- `coordinates`: `{x, y}`만 — **font / align 전용 키 없음**
- categories 예: `paragraph`, `header`, `heading1`, `figure`, `footer`, `list`, `table`, `chart`, `caption`

raw 재확보·비교 예시:

```bash
python examples/dump_parse_raw.py /path/to/deck.pdf
python examples/compare_ringle_parse.py          # API 재호출
python examples/compare_ringle_parse.py --from-raw  # 저장된 raw만
```

**RINGLE raw vs ours 예시:** [`examples/ringle_parse_compare.md`](./examples/ringle_parse_compare.md)  
(JSON: `fixtures/raw/ringle_raw_vs_ours_example.json`)

요지 (slide 10):

| | raw | ours (채택 스펙) |
|--|-----|------------------|
| 구성 | header/footer 포함 elements 38개 | header/footer **제거**, blocks 26 |
| 제목 | (흩어진 heading) | `title` = heading1 승계 |
| 지표 | 없음 | `categories`, `visual_type`[`figure`,`chart`,`table`], `alignment`, char/line… |
| 좌표 | element별 bbox | SlideDoc에는 안 넣고, alignment 근사에만 사용 |

---

## 6. 구현 체크리스트

- [x] `contracts.py` — Slide에 지표·`alignment` (Concept `key_figures`는 후속)
- [x] `f01_parse.py` — header/footer 제외, categories/char/line/visual_*/alignment
- [ ] `f06_concepts.py` — 프롬프트에 `key_figures`; section/slide_role 넣지 않음
- [ ] `SCHEMA.md` — 본 스펙과 동기화
- [x] fixtures / mock 왕복 (`to_dict` / `from_dict`) — 기존 테스트 통과
- [ ] F-06이 `total_char_count`/`has_visual`을 직접 읽게 된 뒤 `text_sparse`/`image_only` deprecate 검토

---

## 7. 팀 공유용 초짧 요약

```text
F-01: blocks 유지 + 정제 raw_text + 밀도/구성 지표 + alignment(optional).
      시간 추정·font·세분 visual_type 제외.
      text_sparse/image_only = total_char_count/has_visual 의 단축 bool (중복·호환용).
F-06: topic/keywords/concepts/importance + key_figures.
      section/slide_role → F-07.
목적: 트리·진단 전에 조인 가능한 깔끔한 구조와 의미만 남긴다.
```
