<!-- 이 파일: AI 루키 대회 데모 스프린트 동안 이 저장소에서 지킬 작업 규칙입니다. -->

# 척척발표 — 작업 규칙 (AI 루키 데모 스프린트)

## 0. 지금 상황

- **1차 마감: 2026-08-07(금)** — 데모 흐름이 처음부터 끝까지 끊기지 않고 돌아가야 한다.
- **최종 개발 마감: 2026-08-09(일)** — 이후로는 화면을 고치지 않고 시연 연습만 한다.
- **목적은 데모다. 완벽한 아키텍처보다 동작하는 화면이 우선이다.**
  판단이 갈리면 "부스에서 이 화면이 오늘 돌아가는가"를 기준으로 고른다.

## 1. 작업 위치

모든 작업은 **`/home/ubuntu/workspace/00_chuckchuck`** 안에서 한다.
이 폴더 밖의 파일은 읽기만 하고 고치지 않는다 (토스 문서 `11_heonseok/toss` 포함).
`pytest` 는 `pyproject.toml` 의 `pythonpath=["."]` 에 기대므로 **반드시 저장소 루트에서** 돌린다.

**브랜치 가정:** 스프린트 동안 `fix/qa-evidence-and-demo-hardening` 위에 쌓고, 마감 직전에만 `main` 으로 합친다.
새 브랜치는 만들지 않는다. 다르게 가야 하면 그때 말해 줄 것.

## 2. 실행

```bash
# 키 없이 화면만 확인 (기본 경로)
MOCK_EXTERNAL_APIS=true python -m demo.bridge      # http://127.0.0.1:8787/

# 실 API (.env 채운 뒤)
python -m demo.bridge

# F-18 LoRA 습관 분석 (conda midm + CUDA 필요, 없으면 heuristic 폴백)
DEMO_PORT=8799 ./demo/run_bridge_midm.sh

python -m pytest tests/ -q                          # 회귀 스모크
```

포트가 물려 있으면 `DEMO_PORT=8801` 처럼 바꾼다. 자세한 절차는 [`README.md`](README.md).

### ⚠️ 캐시 버전 — 데모 날 20분 날리는 함정

`demo/YEHS_demo/index.html` 은 CSS/JS 를 `?v=qa4` · `?v=qa7` 로 물고 있다.
**`css/*.css` 나 `js/*.js` 를 고쳤으면 `index.html` 의 해당 `?v=` 를 같이 올린다.**
안 올리면 브라우저가 옛 파일을 그대로 서빙해서 "고쳤는데 안 바뀐다"가 된다.

## 3. UI 는 무조건 토스처럼

색만 우리 딥그린을 쓰고, **말투·간격·타이포·모션·화면 구조는 토스(TDS) 규율을 따른다.**

### 3-1. 항상 적용 (문서 안 읽어도 되는 것)

- **해요체.** 상황 불문 모든 문구에 적용한다.
- **능동형·긍정형.** "됐어요"→"했어요", "없어요"→"있어요". 에러 문구도 "~하면 할 수 있어요" 로.
- **과도한 경어 금지.** `~시`, `~시겠어요?`, `계시다`, `여쭈다`, `께` 를 쓰지 않는다. (`께`→`에게`)
- **`{명사}+{명사}` 한자어는 풀어쓴다.** "발표 분석 완료" → "발표를 분석했어요".
- **다이얼로그 왼쪽 버튼은 `닫기`.** `취소` 는 쓰지 않는다 — 하던 작업이 취소된다고 오해한다.
- **CTA 문구만 보고 다음 행동이 예측돼야 한다.** "확인" 같은 빈 버튼 금지.
- **다크패턴 금지** — 진입 즉시 바텀시트, 뒤로가기를 막는 시트, 나갈 선택지가 없는 화면, 예상 못 한 광고.

### 3-2. 토스 문서 읽는 법 (`/home/ubuntu/workspace/11_heonseok/toss`)

| 파일 | 크기 | 읽는 법 |
|---|---|---|
| `ux-writing.md` | 3KB | 통째로 읽어도 된다 |
| `components.md` | 2KB | 통째로 읽어도 된다 |
| `consumer-ux-guide.md` | 23KB | 필요한 절만 — 「다크패턴 방지 정책」·「그래픽」 |
| `TDS.md` | **481KB / 17,805줄** | **절대 통째로 읽지 말 것.** `grep -n 'colors.grey' TDS.md` 처럼 필요한 값만 뽑는다 |

### 3-3. 색·토큰은 우리 것

**단일 원본은 `demo/YEHS_demo/css/app.css` 의 `:root` 다.** 토스의 `blue500` 을 가져오지 않는다.

- 브랜드 딥그린 `--brand:#1F7A5F`, 다크 면 `--navy:#12362D`
- 판정 색 5종(`--ok/--mid/--no/--ct/--om`)은 **불변**. 의미가 붙어 있어서 바꾸면 리포트가 거짓말이 된다.
- radius 4종(`--r-print/--r-ctl/--r-pill/--r-dot`) · weight 4단(`--w-body/--w-med/--w-bold/--w-display`) 밖의 값은 쓰지 않는다.
- 서체는 Pretendard 하나.
- 토큰 표가 문서와 어긋나면 **코드가 맞고 문서를 고친다** ([`MVP_SPEC.md`](demo/YEHS_demo/MVP_SPEC.md) §디자인 토큰).

### 3-4. 어느 화면에 어느 규율인가

두 디자인 문서는 충돌이 아니라 **담당 화면이 다르다.**

- **앱 화면**(`#/`, `#/new`, `#/qa`, `#/report`) → [`MVP_SPEC.md`](demo/YEHS_demo/MVP_SPEC.md) §3 절제 규율.
  히어로·마케팅 카피·장식 이모지·glassmorphism·스크롤 하이재킹 금지. 한 화면의 주인공은 하나.
- **객석·극장 화면**(`theater.css`, `chatter.js`, 병아리 연출) → [`docs/UI_REDESIGN.md`](docs/UI_REDESIGN.md).
  단 §14 「토스의 규율」이 위에 있다: 숫자는 신성하고, 판정 색은 안 건드리고, 모든 연출은 스킵 가능하고,
  진행률·오류 원인·샘플 표시는 정직하게 남기고, 소리는 기본 무음이다.
- **연출이 데이터를 가리면 연출을 버린다.** 병아리는 얹는 층이지 가리는 층이 아니다.

## 4. 마감 스프린트 예외 (2026-08-09 까지)

이 절은 **`.claude/rules/common/` 의 규칙보다 우선한다.** 마감 이후에는 원래 규칙으로 돌아간다.

**완화하는 것**

- TDD 선행·커버리지 80% 강제하지 않는다. 데모 경로를 먼저 돌아가게 만든다.
- 새 구현 전 `gh search` 선행 조사, PRD/아키텍처 문서 생성, planner·tdd-guide 자동 위임을 생략한다.
- 코드 리뷰 에이전트는 요청할 때만 돌린다.
- **기존 데모 프론트의 파일·함수 길이 상한(800줄/50줄)을 적용하지 않는다.**
  `js/app.js`(199KB)·`css/app.css`(94KB)는 이미 한참 넘겼다. **마감 전 분할 리팩터 금지** —
  화면이 깨질 위험이 아끼는 것보다 크다. 상한은 새로 만드는 파일에만 지킨다.

**그래도 지키는 것**

- **보안은 예외 없다** (`.claude/rules/common/security.md`). `.env` 에는 실키가 들어 있다.
  키를 코드·문서·채팅·커밋에 넣지 않는다. 공유는 `.env.example`(변수명만).
  노출되면 Upstage / A.X / Friendli 전부 재발급이고 Friendli dedicated 는 과금된다.
- **`python -m pytest tests/ -q` 는 초록으로 유지한다.** 2026-08-06 기준 **498 passed · 7 skipped** 가 기준선이다.
  순수 함수 모듈(`test_flow_diff.py`·`test_score.py`)과 `test_voice_report.py` 가 파이프라인 회귀를 잡아 준다.
  새 기능에 테스트를 안 붙이는 건 괜찮지만, 있는 걸 깨고 넘어가지 않는다.
- **모듈 계약**([`docs/DEV_POLICY.md`](docs/DEV_POLICY.md) §4). 모듈끼리 import 하지 않고, 교환은 `contracts.py` 타입으로만.
  이걸 깨면 아끼는 시간보다 물어뜯기는 시간이 크다.
- **분석이 실패하면 실패로 보여준다.** 샘플 그래프로 위장하지 않는다 — 심사 때 들킨다.

## 5. 더 볼 문서

| 문서 | 내용 |
|---|---|
| [`README.md`](README.md) | 설치·실행·손으로 눌러보는 체크리스트 |
| [`docs/DEV_POLICY.md`](docs/DEV_POLICY.md) | 모듈 독립·API/SDK 계약 (F-01~F-20 맵) |
| [`docs/SCHEMA.md`](docs/SCHEMA.md) · `chuckchuck/contracts.py` | 스키마 단일 출처 |
| [`demo/YEHS_demo/MVP_SPEC.md`](demo/YEHS_demo/MVP_SPEC.md) | 화면 스펙·정보 구조·디자인 토큰 |
| [`docs/UI_REDESIGN.md`](docs/UI_REDESIGN.md) | 척척극장 연출 규율 |
