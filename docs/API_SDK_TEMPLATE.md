<!-- 이 파일: 새 모듈의 API·SDK를 만들 때 따르는 템플릿 안내입니다. -->

# 척척발표 · API / SDK 템플릿

> **새 모듈은 이 템플릿을 복사해서 시작한다.**  
> 입출력 모양이 모듈마다 다르면 cascade가 깨진다.  
> 정책: [`DEV_POLICY.md`](./DEV_POLICY.md) · 스키마: [`SCHEMA.md`](./SCHEMA.md) · 타입: `chuckchuck/contracts.py`

복사본 스켈레톤: [`docs/templates/`](./templates/)

---

## 0. 레이어별 역할 (한눈에)

```
화면 / JS SDK
    │  ours JSON  (또는 multipart 파일)
    ▼
서버  HTTP  /api/v1/{action

    │  from_dict → 모듈 함수 → to_dict
    ▼
기능 모듈  chuckchuck/fXX_*.py
    │  (필요 시) provider 인터페이스
    ▼
외부 AI 어댑터  chuckchuck/providers/*_impl.py   ← raw는 여기만
```

| 레이어 | 파일 위치 | 밖으로 내보내는 것 |
|--------|-----------|-------------------|
| 계약 | `contracts.py` | `OursType.to_dict()` / `from_dict()` |
| 모듈 | `fXX_name.py` | **공개 함수 1개** (+ 순수 헬퍼) |
| Provider | `providers/*_base.py` + `*_impl.py` | ABC + `get_*()` 팩토리 |
| HTTP | 서버/브리지 | `POST /api/v1/{action}` → ours JSON |
| JS SDK | `chuckchuck/sdk/*.js` | 클래스 + `index.js`
export |

---

## 1. 계약 (contracts) 템플릿

**규칙**

- `@dataclass` + **`to_dict()` / `from_dict()`** 필수 (왕복 가능해야 함)
- 시각 = `float` 초, 슬라이드 = 1부터
- 에러는 `ChuckchuckError` 하위 (`ParseError`, `STTError`, …)
- 스키마를 **먼저** `SCHEMA.md`에 적고, 그다음 `contracts.py`에 올린다

```python
# chuckchuck/contracts.py 에 추가

@dataclass
class MyOut:
    """F-XX 산출물."""
    # ... fields ...

    def to_dict(self) -> dict:
        return { ... }

    @classmethod
    def from_dict(cls, d: dict) -> "MyOut":
        return cls( ... )
```

전체 스켈레톤: [`templates/contract_snippet.py`](./templates/contract_snippet.py)

---

## 2. Python 모듈 (SDK) 템플릿

**파일명:** `chuckchuck/fXX_name.py`  
**공개 API:** 동사 함수 하나 (`parse_document`, `transcribe`, `extract_concepts` 스타일)

```python
"""
F-XX · 한 줄 책임

    InType  →  OutType

사용:
    from chuckchuck.fXX_name import do_thing
    out = do_thing(inp)
"""

from __future__ import annotations

from .contracts import InType, OutType, MyError


def do_thing(
    inp: InType | dict,
    *,
    provider: str | None = None,   # 외부 AI 있을 때만
) -> OutType:
    """입력(ours) → 출력(ours). raw/벤더 이름은 밖으로 새기지 않는다."""
    if isinstance(inp, dict):
        inp = InType.from_dict(inp)
    # ... 로직 (provider 호출은 어댑터에 위임) ...
    return OutType( ... )
```

**필수**

| 규칙 | 내용 |
|------|------|
| I/O | 인자·반환은 **ours만**. dict면 함수 입구에서 `from_dict` |
| 결합 | **다른 `fXX_*` 모듈 import 금지**. 서버가 순서 잡음 |
| raw | 벤더 응답은 provider/어댑터에서 ours로 변환 후만 사용 |
| mock | `provider="mock"` 또는 `MOCK_EXTERNAL_APIS`로 파이프라인 검증 가능 |
| export | 안정되면 `chuckchuck/__init__.py`의 `__all__`에 추가 |

스켈레톤: [`templates/fXX_module.py`](./templates/fXX_module.py)

---

## 3. Provider (외부 AI) 템플릿

STT·LLM처럼 갈아끼울 수 있는 것만 ABC로 둔다.

```python
# providers/my_base.py
class MyProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    def run(self, ...) -> OursPartial:
        ...

# providers/my_impl.py
def get_my(name: str | None = None) -> MyProvider:
    ...
```

- `name` 필드로 식별 (`"skt-ax"`, `"solar"`, `"mock"` …)
- mock 구현 **필수**
- raw → ours 변환은 **impl 안**에서 끝

스켈레톤: [`templates/provider_stub.py`](./templates/provider_stub.py)

---

## 4. HTTP API 템플릿

기존 브리지(`demo/bridge.py`) 기준. 화면·외부 클라이언트가 쓰는 창구.

### 엔드포인트 규칙

| 항목 | 규격 |
|------|------|
| 경로 | `POST /api/v1/{action}` — action은 모듈 동사 (`parse`, `transcribe`, `concepts`, …) |
| 요청 | `Content-Type: application/json` + **ours 필드** (파일만 multipart) |
| 성공 | `200` + **ours `to_dict()` 그대로** |
| 실패 | `4xx/5xx` + `{ "error": "ErrorClass", "message": "..." }` |
| CORS | 데모/로컬은 `Access-Control-Allow-Origin: *` |

### 요청/응답 예시 (기존과 동일 패턴)

**F-01** `POST /api/v1/parse`  
- multipart `document` 파일 → body = `SlideDoc.to_dict()`

**F-05** `POST /api/v1/transcribe`  
```jsonc
// request
{ "audio_base64": "...", "ext": ".webm", "marks": [ /* SlideMark */ ], "provider": "skt-ax" }
// response = Transcript.to_dict()
```

**F-06** `POST /api/v1/concepts`  
```jsonc
// request
{ "slide_doc": { /* SlideDoc */ }, "context": { /* Context */ }, "llm": "solar" }
// response = ConceptDoc.to_dict()
```

**새 모듈**도 똑같이:

```jsonc
// POST /api/v1/{action}
// request:  입력 ours 필드들 (+ optional provider)
// response: 출력 ours to_dict()
```

핸들러 스켈레톤: [`templates/api_handler.py`](./templates/api_handler.py)

---

## 5. JS SDK 템플릿 (브라우저)

브라우저에서만 생기는 입력(녹음·슬라이드 마크)용. 서버 ours와 **필드명이 같아야** 한다.

```js
/**
 * F-XX · 한 줄 책임
 * 출력은 contracts / SCHEMA 의 ours JSON 과 동일 키.
 */
export class MyClient {
  /** @returns {object} ours dict — 서버가 from_dict 할 수 있는 형태 */
  toJSON() { return { ... }; }
}

// index.js
export { MyClient } from './my_client.js';
```

| 규칙 | 내용 |
|------|------|
| 키 이름 | Python `to_dict()`와 **동일** (`slide_no`, `start_sec`, …) |
| 시각 | 초(float), 녹음 시작 = 0 |
| 업로드 | `fetch('/api/v1/...', { method:'POST', body })` — 응답도 ours JSON |
| export | `chuckchuck/sdk/index.js`에 재export |

스켈레톤: [`templates/sdk_module.js`](./templates/sdk_module.js)

---

## 6. 기존 모듈 ↔ 템플릿 매핑 (기준선)

| ID | 모듈 함수 | HTTP | JS SDK | Provider |
|----|-----------|------|--------|----------|
| F-01 | `parse_document` | `POST /api/v1/parse` | — | Upstage (모듈 내 어댑터) |
| F-03·04 | — | (업로드는 transcribe로) | `RehearsalRecorder` | — |
| F-05 | `transcribe` | `POST /api/v1/transcribe` | `uploadRehearsal` | `STTProvider` / `get_provider` |
| F-06 | `extract_concepts` | `POST /api/v1/concepts` | — | `LLMProvider` / `get_llm` |
| F-07 | `build_graph` | `POST /api/v1/graph` | — | `LLMProvider` / `get_llm` |
| F-11 | `align_speech` | `POST /api/v1/alignment` | — | `LLMProvider` / `get_llm` |
| F-11 파생 | `build_flow_diff` | `POST /api/v1/flow` | — | — (LLM 없음) |
| F-17 | `analyze_pace` | `POST /api/v1/pace` | — | — (규칙) |
| F-18 | `extract_habits` | `POST /api/v1/habits` | — | **LoRA(기본)** + heuristic 보강 |
| F-19 | `compose_report` | `POST /api/v1/report` | — | `LLMProvider` / `get_llm` |

새 파트(F-07+)는 **이 표에 한 줄을 추가하는 것**이 완료 조건이다, 구현의 시작이다.

---

## 7. PR 전에 맞출 것

- [ ] `SCHEMA.md`에 raw → ours 표 + JSON 예시
- [ ] `contracts.py`에 타입 + `to_dict`/`from_dict`
- [ ] `fXX_*.py` 공개 함수 1개, 형제 모듈 import 없음
- [ ] HTTP면 `POST /api/v1/{action}`, 응답 = ours
- [ ] JS면 키·단위가 Python과 동일
- [ ] mock으로 `examples/` 또는 테스트 통과
- [ ] `__init__.py` / `sdk/index.js` export (공개할 때만)
