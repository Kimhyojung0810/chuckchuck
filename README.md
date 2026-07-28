<!-- 이 파일: 프로젝트 소개·설치·실행 방법이 적힌 메인 안내서입니다. -->

# 척척발표 · 마이크로 모듈

팀원 데모([YEHS_demo](https://whilethis00.github.io/YEHS_demo/)) 화면에 맞춰, 담당 기능을 **독립 모듈**로 분리한 패키지다. 나중에 프론트만 API/SDK에 연결하면 된다.

| ID | 모듈 | I/O | 기술 |
|----|------|-----|------|
| F-01 | `chuckchuck/f01_parse.py` | 파일 → `SlideDoc` | Upstage Document Parse |
| F-03·04 | `sdk/rehearsal-recorder.js` | 마이크+슬라이드 → audio + `SlideMark[]` | 브라우저 (통합 SDK) |
| F-03 | `sdk/recorder.js` | 마이크 → audio blob | MediaRecorder (분리) |
| F-04 | `sdk/slide_marks.js` | 슬라이드 전환 → `SlideMark[]` | 브라우저 상대시각 (분리) |
| F-05 | `chuckchuck/f05_stt.py` | audio + marks → `Transcript` | **SKT A.X STT** + 순수 분할 |
| F-06 | `chuckchuck/f06_concepts.py` | `SlideDoc`+`Context` → `ConceptDoc` | Solar / A.X / 믿음 / 엑사원 |
| F-07 | `chuckchuck/f07_graph.py` | `ConceptDoc`(+`SlideDoc`) → `ConceptGraph` | Solar / A.X / 믿음 / 엑사원 |
| F-11 | `chuckchuck/f11_align.py` | `ConceptGraph`+`Transcript` → `AlignmentDoc` | Solar / A.X / 믿음 / 엑사원 |

공통 계약은 `chuckchuck/contracts.py` 하나다. 설정은 `chuckchuck/config.py` (`settings.masked()`).

**모델 개발 정책 (1-Pager):** [`docs/DEV_POLICY.md`](docs/DEV_POLICY.md) — 모듈 독립 · API/SDK 규격.  
**API / SDK 템플릿:** [`docs/API_SDK_TEMPLATE.md`](docs/API_SDK_TEMPLATE.md) · [`docs/templates/`](docs/templates/) — 새 모듈 복사해서 시작.  
**Document Parse 후처리:** [`docs/DOCUMENT_PARSE_POSTPROCESS.md`](docs/DOCUMENT_PARSE_POSTPROCESS.md) — SlideDoc / ConceptDoc 합의안.  
**스키마 공유 문서:** [`docs/SCHEMA.md`](docs/SCHEMA.md) — 벤더 원본 vs 후처리 계약.

## 보안

채팅·이슈·문서에 API 키를 붙이지 말 것. 공유는 `.env.example`(변수명만).  
키가 노출됐다면 **Upstage / A.X / Friendli(믿음·엑사원) 전부 재발급**하세요. Friendli dedicated는 과금됩니다.

## LLM 선택

국내 LLM 써도 된다. 기본은 환경변수 `REASONING_BACKEND=solar`(Upstage Solar). A.X-K1·믿음·엑사원도 `get_llm("ax"|"midm"|"exaone")` 로 갈아끼울 수 있다. F-06은 JSON 구조 추출이라 Solar/A.X 모두 충분하다.

## STT (확정)

[A.X STT API 가이드](https://portal.adot.ai/docs/stt-api-guide) 기준 batch 흐름:

1. `GET /v1/stt/upload-token?fileSize=N`
2. `PUT /v1/stt/upload/{token}` (octet-stream)
3. `POST /v1/stt/transcript` (`speech_model=A.X_STT_note_batch`)

인증은 **`X-API-Key`** (LLM의 Bearer 와 다름). 단어 시각은 `words[].start_time` / `end_time`.

실측(2026-07): 단어별 timestamp **있음** → F-17 진행 가능. 재확인:

```bash
python -m chuckchuck.probe_ax_stt 샘플녹음.wav
python -c "from chuckchuck.providers import health_check; print(health_check())"
python -c "from chuckchuck.config import settings; print(settings.masked())"
```

전문용어 인식률을 위해 `keywords=`(발표자료 키워드) 를 넘길 수 있다.

## 빠른 시작

```bash
cd /Users/gimhyojeong/SSA
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 키 채우기. 없으면 MOCK 로 개발

# API 없이 파이프라인 검증
python examples/run_pipeline_mock.py
python -m pytest tests/ -q

# 데모 UI + 모듈 브리지
export MOCK_EXTERNAL_APIS=true
python -m demo.bridge
# http://127.0.0.1:8787/  → 새 발표 연습 → 리허설 녹음
```

실 API:

```bash
export MOCK_EXTERNAL_APIS=false
export UPSTAGE_API_KEY=...
export AX_STT_API_KEY=...   # awf_ 키, X-API-Key 로 사용
export REASONING_BACKEND=solar
python -m demo.bridge
```

## 모듈 사용 예

```python
from chuckchuck import parse_document, extract_concepts, transcribe, Context

doc = parse_document("발표.pdf")                 # F-01
concepts = extract_concepts(                     # F-06
    doc,
    Context(situation="학회·수업 발표", audience="교수님"),
    llm="solar",  # or "ax" / "mock"
)

# F-03/F-04 는 브라우저 SDK가 marks JSON 을 만들고
t = transcribe("녹음.webm", marks, provider="skt-ax", keywords=["IMU2CLIP", "CLIP"])
for s in t.by_slide:
    print(s.slide_no, s.text[:40])
```

브라우저:

```js
import { PresentationRecorder, SlideMarkTracker } from '/sdk/index.js';
const rec = new PresentationRecorder();
const marks = new SlideMarkTracker({ getElapsedSec: () => rec.elapsedSec });
await rec.start();
marks.start(1);
marks.goTo(2);
const list = marks.finish();
const { blob } = await rec.stop();
```

## 디렉터리

```
chuckchuck/
  contracts.py          # 유일한 결합점
  f01_parse.py
  f05_stt.py
  f06_concepts.py
  providers/            # STT·LLM 어댑터
  sdk/                  # F-03/F-04 JS
demo/
  bridge.py             # YEHS_demo 서빙 + /api/v1/*
  YEHS_demo/            # 팀원 데모 (SDK 연결됨)
fixtures/ sample_slidedoc.json
tests/ examples/
```

## 주의

- F-06은 **위계를 만들지 않는다**. 그건 F-07(`build_graph`)이 `ConceptDoc`을 받아서 한다.
- F-07은 **트리가 아니라 그래프**를 낸다. 개념은 부모가 하나라는 보장이 없어서다.
  `parent` 간선만 따라가면 트리 뷰, `relates` 간선이 나머지 연결.
- F-07은 **판정하지 않는다**. 발화 축(`speech_weight`)과 정합 판정(누락·모순)은
  `Transcript`가 있어야 나오므로 F-11(`align_speech`)이 `node_id`로 붙인다.
- F-11은 **발화 그래프를 따로 뽑지 않는다**. LLM 추출 분산이 두 배가 되어 diff 가
  노이즈를 재기 때문이다. 문서 그래프 노드에 조건화해 판정만 받고,
  `speech_weight` 는 marks·토큰 매칭으로 코드가 결정적으로 계산한다.
- STT 제공자가 단어 시각을 안 주면 `WordTimestampUnsupported` 로 즉시 실패한다 (F-17 말속도 대비).
- API 키는 `.env`에만 두고 커밋하지 말 것.
