<!-- 이 파일: 프로젝트 소개·설치·실행 방법이 적힌 메인 안내서입니다. -->

# 척척발표 · 마이크로 모듈

팀원 데모([YEHS_demo](https://whilethis00.github.io/YEHS_demo/)) 화면에 맞춰, 담당 기능을 **독립 모듈**로 분리한 패키지다. 나중에 프론트만 API/SDK에 연결하면 된다.

| ID | 모듈 | I/O | 기술 | API |
|----|------|-----|------|-----|
| F-01 | `chuckchuck/f01_parse.py` | 파일 → `SlideDoc` | Upstage Document Parse | `POST /api/v1/parse` |
| F-03·04 | `sdk/rehearsal-recorder.js` | 마이크+슬라이드 → audio + `SlideMark[]` | 브라우저 (통합 SDK) | — (브라우저) |
| F-03 | `sdk/recorder.js` | 마이크 → audio blob | MediaRecorder (분리) | — (브라우저) |
| F-04 | `sdk/slide_marks.js` | 슬라이드 전환 → `SlideMark[]` | 브라우저 상대시각 (분리) | — (브라우저) |
| F-05 | `chuckchuck/f05_stt.py` | audio + marks → `Transcript` | **SKT A.X STT** + 순수 분할 | `POST /api/v1/transcribe` |
| F-06 | `chuckchuck/f06_concepts.py` | `SlideDoc`+`Context` → `ConceptDoc` | Solar / A.X / 믿음 / 엑사원 | `POST /api/v1/concepts` |
| F-07 | `chuckchuck/f07_graph.py` | `ConceptDoc`(+`SlideDoc`) → `ConceptGraph` | Solar / A.X / 믿음 / 엑사원 | `POST /api/v1/graph` |
| F-08 | `chuckchuck/f08_questions.py` | `ConceptGraph`(+`AlignmentDoc`·`FlowDiff`) → `QaTriage` → `QuestionDoc` | Solar / A.X / 믿음 / 엑사원 | `POST /api/v1/questions` |
| F-09 | `chuckchuck/f09_judge.py` | `Question`+답변(+`QaTurn[]`) → `QaJudgement` | Solar / A.X / 믿음 / 엑사원 | `POST /api/v1/qa/judge` |
| F-11 | `chuckchuck/f11_align.py` | `ConceptGraph`+`Transcript` → `AlignmentDoc` | Solar / A.X / 믿음 / 엑사원 | `POST /api/v1/alignment` |
| F-11 파생 | `chuckchuck/f11_flow.py` | `ConceptGraph`+`AlignmentDoc` → `FlowDiff` | 순수 함수 (LLM 없음) | `POST /api/v1/flow` |
| F-12 | `chuckchuck/f12_chatter.py` | `ConceptGraph`+`AlignmentDoc`+`FlowDiff` → `ChatterDoc` | 국내 LLM 4개 (병아리 페르소나) | `POST /api/v1/chatter` |
| F-13 | `chuckchuck/f13_score.py` | `AlignmentDoc`+`FlowDiff` → `PresentationScore` | 순수 함수 (LLM 없음) | `POST /api/v1/score` |
| F-17 | `chuckchuck/f17_pace.py` | `Transcript`(+`Context`·`ConceptDoc`) → `PaceDoc` | 규칙 (LLM 없음) | `POST /api/v1/pace` |
| F-18 | `chuckchuck/f18_habits.py` | `Transcript` → `HabitDoc` | 믿음 LoRA(REP) + heuristic(FIL·PAUSE) | `POST /api/v1/habits` |
| F-19 | `chuckchuck/f19_report.py` | `PaceDoc`+`HabitDoc`(+`Context`) → `ReportDoc` | Solar / A.X / 믿음 / 엑사원 | `POST /api/v1/report` |

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
cd /path/to/00_chuckchuck
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 키 채우기. 없으면 MOCK 로 개발

# API 없이 파이프라인 검증
python examples/run_pipeline_mock.py
python -m pytest tests/ -q
```

## 데모 실행 · 테스트 가이드

브리지는 `demo/YEHS_demo` UI와 `/api/v1/*` 를 같이 띄운다.  
**`.env` 는 깃에 올리지 않는다.** 공유는 `.env.example`(변수명만).

### 1) Mock (키 없이 UI 확인)

```bash
export MOCK_EXTERNAL_APIS=true
python -m demo.bridge
# http://127.0.0.1:8787/
```

샘플 자료로 화면 흐름만 볼 때 쓴다. 실 STT·LLM·LoRA 는 돌지 않는다.

### 2) 실 API (기본 Python · Solar 등)

`.env` 에 키를 채운 뒤:

```bash
# .env 권장 값
# MOCK_EXTERNAL_APIS=false
# UPSTAGE_API_KEY=...
# AX_STT_API_KEY=...          # awf_ 키, STT 는 X-API-Key
# REASONING_BACKEND=solar     # solar | ax | midm | exaone
# HABIT_PROVIDER=heuristic    # 이 환경에 torch/GPU 없으면 heuristic
# DEMO_PORT=8787

python -m demo.bridge
# http://127.0.0.1:8787/
```

이 경로에서는 F-01 파싱 · F-05 STT · F-06~11 LLM · F-08/09 질문 코칭까지 실연동된다.  
다만 **F-18 LoRA(반복어 태거)는 기본 venv에 torch가 없으면 heuristic으로 떨어진다.**

### 3) 파인튜닝 LoRA 포함 (midm conda + GPU) ← 습관 분석 실사용

F-18 REP LoRA 를 쓰려면 **midm 환경 + CUDA** 로 브리지를 띄운다.

```bash
# 1) .env
# MOCK_EXTERNAL_APIS=false
# 실 API 키들 + (선택) REASONING_BACKEND=midm 등
# HABIT_PROVIDER=lora
# CHUCKCHUCK_LORA_PATH=/path/to/lora/adapter   # adapter_config.json 있는 폴더
# CHUCKCHUCK_LORA_KINDS=REP

# 2) 실행 (권장 스크립트 — 포트 기본 8799)
chmod +x demo/run_bridge_midm.sh
DEMO_PORT=8799 ./demo/run_bridge_midm.sh
# http://127.0.0.1:8799/
```

스크립트가 하는 일:
- `MIDM_PY`(기본: conda `midm` 의 python) 으로 `demo.bridge` 실행
- `HABIT_PROVIDER=lora`, `MOCK_EXTERNAL_APIS=false` 고정
- `CHUCKCHUCK_LORA_PATH` 미지정 시 팀 서버 기본 adapter 경로를 씀  
  → 로컬에 어댑터가 없으면 `.env` / 셸에서 경로를 명시할 것

직접 실행하려면:

```bash
conda activate midm
export MOCK_EXTERNAL_APIS=false
export HABIT_PROVIDER=lora
export CHUCKCHUCK_LORA_PATH=/path/to/lora/adapter
export DEMO_PORT=8799
python -m demo.bridge
```

CUDA 확인:

```bash
python -c 'import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")'
```

### 손으로 눌러보는 체크리스트

1. **자료 업로드** — 본인 PDF/PPTX (샘플이 아닌 파일). PPTX는 미리보기 PDF 변환이 필요할 수 있다.
2. **발표 연습** — 「발표 시작하기」가 제목 바로 아래에 보이는지, 녹음·슬라이드 넘기기.
3. **분석** — 스텝 4 체크리스트가 STT→개념→정합까지 진행되는지. 실패 시 샘플 그래프로 위장하면 안 된다.
4. **질문 코칭** — 시작 → 답/넘기기 → 끝나면 **상세 리포트 보기**로 `#/report` 연결.
5. **리포트** — 제목이 IMU2CLIP 샘플이 아니라 **올린 파일명**인지. 건너뛴 리포트와 동일 분석(`pipelineOut`).
6. **객석** — 「객석 들어가기」→「객석 나가기」/「리포트에서 자세히 보기」가 리포트로 복귀하는지.
7. **음성 습관(LoRA)** — midm 브리지에서 리포트「음성 습관」탭. `/api/v1/habits` 응답 `provider` 가 `lora` 인지 확인.

### 단위 테스트

```bash
python -m pytest tests/ -q
# 질문 코칭만: python -m pytest tests/test_questions.py tests/test_judge.py -q
```

### 포트가 이미 쓰일 때

```bash
DEMO_PORT=8801 ./demo/run_bridge_midm.sh
# 또는
DEMO_PORT=8801 python -m demo.bridge
```

## 개발 환경 (Claude Code · ECC)

이 저장소는 Claude Code 플러그인 **ECC**를 쓴다. 설정은 `.claude/settings.json`에 커밋돼 있어서, 클론 후 Claude Code로 이 폴더를 열면 마켓플레이스 등록과 플러그인 활성화가 자동으로 잡힌다. 플러그인 본체는 저장소에 없으므로 각자 머신에 한 번 받아야 한다.

```bash
git clone git@github.com:Kimhyojung0810/chuckchuck.git
cd chuckchuck
claude          # 첫 실행 시 ecc 플러그인 설치 여부를 묻는다

/plugin         # 설치 상태 확인 (ecc@ecc → enabled)
```

`.claude/settings.local.json`은 개인 권한 설정이라 git이 무시한다. 팀 전체에 적용할 설정만 `.claude/settings.json`에 넣을 것.

### 팀 공통 규칙

코딩 스타일·테스트·보안 등 ECC 공통 rule 10개를 `.claude/rules/common/`에 커밋해뒀다. 플러그인 시스템은 rule 배포를 지원하지 않아서 저장소에 직접 넣는 방식이다(ECC 문서의 "옵션 B: 프로젝트 레벨 룰"). 클론하면 별도 설치 없이 팀 전원에게 같은 규칙이 적용된다.

| 파일 | 내용 |
|------|------|
| `coding-style.md` | 불변성 우선, KISS/DRY/YAGNI, 함수 50줄·파일 800줄 상한 |
| `testing.md` | TDD(RED→GREEN→REFACTOR), 커버리지 80% |
| `security.md` | 커밋 전 시크릿 점검, 입력 검증 — 이 프로젝트의 `.env` 정책과 직결 |
| `code-review.md` | 리뷰 체크리스트, 심각도 등급 |
| `git-workflow.md` · `development-workflow.md` | 커밋 형식, 기능 개발 순서 |
| `agents.md` · `hooks.md` · `patterns.md` · `performance.md` | 에이전트 위임, 훅, 공통 패턴 |

ECC 원본을 갱신하려면 `~/.claude/plugins/cache/ecc/ecc/<버전>/rules/common/`에서 다시 복사한다.

### 훅이 명령을 막을 때

ECC는 도구 실행 전에 개입하는 훅을 건다. 예를 들어 GateGuard는 첫 `Bash` 실행이나 파일 편집 전에 "무엇을 검증하는 명령인지" 먼저 밝히라고 요구하며 반려한다. 정상 동작이지만 급할 때는 끌 수 있다.

```bash
ECC_GATEGUARD=off claude
# 또는 특정 훅만
ECC_DISABLED_HOOKS=pre:bash:gateguard-fact-force claude
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
