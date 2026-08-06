# 발표 평가 로직 전면 개편 — 채점표 v3 기반

> **이 문서를 읽는 에이전트에게:** 실행 순서는 §5 다. 그 전에 §0(채점표 숫자)·§1(집계 공식)·§7(하지 말 것)을 먼저 읽는다.
> 기준 원본은 `docs/발표평가_상황별_채점표_v3.xlsx` 이고, **코드가 읽는 원본은 §0 의 표**다 (런타임 xlsx 파싱 금지 — §7 참조).
> 작성일 2026-08-06 · 대상 브랜치 `fix/qa-evidence-and-demo-hardening`

---

## Context — 왜 고치는가

지금 발표가 끝나면 화면에 0~100 점수가 하나 뜬다. 그 점수가 어디서 왔는지 사용자도, 우리도 설명할 수 없다.

- **f13 `score_presentation`** (`chuckchuck/f13_score.py:118`) 이 화면 링의 점수를 만든다. 근거는 개념 그래프 정렬 지표 4개뿐이다 — `coverage 0.45 / rank 0.20 / edge 0.20 / order 0.15` (`f13_score.py:28-33`). 발표를 잘했는지가 아니라 **자료의 개념 그래프를 얼마나 따라 말했는지**만 잰다. 논리 구조, 청중 적합성, 시간 관리, 시각자료 품질은 점수에 1도 반영되지 않는다.
- **f19 `_rule_score`** (`f19_report.py:70-80`) 라는 **두 번째 0~100 점수**가 따로 있다. 말속도·습관 기반이고 `max(45, min(92, …))` 로 강제 클램프돼 절대 실패할 수도 90점을 넘을 수도 없다. 그리고 **프론트에서 아무도 안 읽는다** — `grade` 는 계산만 하고 버려진다.
- 상황(`Context.situation`)은 전 모듈에서 **프롬프트 텍스트로만** 쓰인다. 어떤 가중치·임계값·분기도 상황을 읽지 않는다 (`f17_pace.py:221` 의 `duration_min` 만 예외).

`docs/발표평가_상황별_채점표_v3.xlsx` 는 이걸 대체할 기준을 이미 갖고 있다: **7개 클러스터 · 39개 세부 항목 · 4개 발표 상황별 가중치**.

**목표 상태:** 최종 점수의 모든 자릿수가 "39개 항목 중 이 항목에서 몇 점을 받았고, 이 상황에서 가중치가 몇이라서, 이만큼 기여했다" 로 역추적된다. 점수가 하나로 통일된다. 못 잰 항목은 0점 처리하지 않고 **정직하게 빠졌다고 표시**한다.

**사용자 확정 사항 (이번 대화에서 결정):**
1. UI 상황 선택지를 채점표 4개 열로 **교체**한다 (`app.js:964` 의 `['사내 보고','학회·수업 발표','대회·IR 피칭','범용']` → 채점표 4개).
2. f13 과 f19 `_rule_score` **둘 다** 새 채점표로 통합한다. f13 은 폴백으로만 남기고 08-09 이후 삭제 대상으로 표시한다.

**전제 (실행 에이전트가 반드시 지킬 것):**
- 마감이 임박했다 (1차 2026-08-07, 최종 개발 2026-08-09). `CLAUDE.md` §4 스프린트 예외가 적용된다 — TDD 선행·커버리지 80% 강제 없음. 판단 기준은 **"부스에서 이 화면이 오늘 돌아가는가"**.
- 저장소에 **음향 특징이 전혀 없다.** `requirements.txt` 에 librosa/soundfile/pydub 없음. 오디오는 STT 로 보내고 즉시 삭제된다 (`demo/bridge.py:785-786`). 모든 "음성" 신호는 **단어 타임스탬프 + 단어 텍스트**에서 파생된 것이다. 이 제약을 우회하려 하지 말고 항목 25·26 을 `unmeasured` 로 정직하게 처리한다.

---

## 0. 채점표 데이터 (xlsx 파싱 금지 — 이 표가 코드의 원본)

`openpyxl` 이 설치돼 있지 않고 파일명이 NFD 정규화라 리터럴 경로 open 이 실패한다. **런타임에 xlsx 를 읽지 않는다.** 아래 숫자를 `chuckchuck/rubric_v3.py` 에 그대로 박는다. xlsx 는 사람용 원본으로 남긴다.

### 0-1. 클러스터 가중치 (%, 상황별 합계 100)

| 클러스터 | key | 학교 프로젝트 | 신제품 설명 | 업무 보고 | 캐주얼 PR |
|---|---|---|---|---|---|
| 내용 충실도 | `content` | 26 | 17 | 19 | 28 |
| 논리 구조 | `logic` | 23 | 15 | 23 | 20 |
| 목적·청중 적합성 | `audience` | 8 | 19 | 15 | 8 |
| 언어적 명료성 | `clarity` | 10 | 12 | 8 | 11 |
| 음성적 전달 | `delivery` | 7 | 12 | 6 | 9 |
| 시각자료 활용 | `visual` | 13 | 17 | 11 | 12 |
| 시간 관리 | `time` | 13 | 8 | 18 | 12 |

상황 key: `school_project` / `product_launch` / `work_report` / `casual_peer`

### 0-2. 39개 항목 — 내부 가중치 · 산출 방식 · 읽는 필드

`det` = 코드가 계산 (LLM 없음), `llm` = LLM 채점, `n/a` = 이번 파이프라인에서 측정 불가.
가중치 **0 = 그 상황에서 평가하지 않음** (`situation_excluded`).

| No | 클러스터 | 항목 | 학교 | 신제품 | 업무 | 캐주얼 | 방식 | 읽는 데이터 |
|---|---|---|---|---|---|---|---|---|
| 1 | content | 핵심 개념 커버리지 | 9 | 8 | 8 | 6 | det | `AlignmentSummary.coverage` × 100 |
| 2 | content | 설명 깊이 | 10 | 6 | 6 | 5 | llm | `Transcript.by_slide[].text` + `ConceptGraph.nodes[].summary` |
| 3 | content | 근거·수치·사례 제시 | 9 | 7 | 8 | 5 | llm | `Transcript.full_text` (숫자·단위 밀도를 힌트로 동봉) |
| 4 | content | 자료-발화 일치성 | 8 | 6 | 7 | 4 | det | `AlignmentItem.verdict=="contradiction"` × `doc_weight` |
| 5 | content | 근거 없는 추가 발화 | 7 | 5 | 6 | 3 | det | `AlignmentDoc.extra_concepts[]` 개수 / 노드 수 |
| 6 | content | 선행연구·이론적 근거 인용 | **7** | 0 | 0 | 0 | llm | `Transcript.full_text` |
| 7 | logic | 핵심 주장 제시 시점 | 6 | 8 | 9 | 5 | llm | 도입 구간 발화 (`Section.slide_role=="intro"` 슬라이드의 `by_slide.text`) |
| 8 | logic | 주장-근거-결론 연결 | 9 | 8 | 9 | 6 | llm | `Transcript.full_text` + `ConceptGraph.edges` |
| 9 | logic | 전제 생략·결론 점프·모순 | 8 | 7 | 8 | 5 | llm | 발화 + `FlowDiff.issues[kind=="order_jump"]` 힌트 |
| 10 | logic | 전환의 자연스러움 | 6 | 6 | 6 | 4 | llm | `FlowDiff.issues[missing_link/good_link]` + 슬라이드 경계 발화 |
| 11 | logic | 결론의 핵심 회수 | 6 | 6 | 7 | 4 | llm | 결론 구간 발화 (`slide_role=="conclusion"`) + 상위 weight 노드 label |
| 12 | logic | 두괄식 구조 | 0 | 0 | **8** | 0 | llm | 도입 구간 발화 |
| 13 | audience | 청중 수준 맞춤 설명 | 7 | 9 | 7 | 5 | llm | 발화 + `Context.audience` |
| 14 | audience | 목적에 맞는 강조점 | 6 | 9 | 8 | 5 | llm | 발화 + `Context.situation` |
| 15 | audience | 흥미 유발·스토리텔링 | 0 | **9** | 0 | 0 | llm | 도입 구간 발화 |
| 16 | audience | 실행 가능한 제안 명확성 | 0 | 0 | **9** | 0 | llm | 결론 구간 발화 |
| 17 | clarity | 지시어 남용 여부 | 4 | 4 | 4 | 3 | det | 지시어 사전 빈도 / 총 어절 |
| 18 | clarity | 전문용어 설명 동반 | 6 | 8 | 5 | 4 | llm | 발화 + `ConceptDoc.slides[].keywords` |
| 19 | clarity | 문장 길이·완결성 | 4 | 5 | 4 | 3 | det | `f05_stt.SENTENCE_END` 로 문장 분할 → 평균 어절 수 + 미완결 비율 |
| 20 | clarity | 표현의 의미 없는 반복 | 3 | 4 | 3 | 3 | det | `HabitDoc.repeat_cnt` / 총 어절 |
| 21 | clarity | 핵심 구조 신호어 사용 | 5 | 6 | 5 | 3 | det | 신호어 사전 출현 종류 수 + 빈도 |
| 22 | delivery | 말속도 적절성 | 4 | 6 | 5 | 4 | det | `PaceDoc.avg_chars_per_min` + `slides[].status in {fast,slow}` 비율 |
| 23 | delivery | 필러 빈도·위치 | 4 | 5 | 5 | 4 | det | `HabitDoc.filler_cnt`/분 + `by_slide` × core 슬라이드 몰림 |
| 24 | delivery | 휴지·침묵의 위치 | 3 | 5 | 4 | 3 | det(약함) | `HabitDoc.pause_cnt` (≥5s 단어 간격) + 슬라이드 경계 일치 여부 |
| 25 | delivery | 음량 안정성 | 3 | 5 | 4 | 3 | **n/a** | 음향 특징 없음 → `unmeasured` |
| 26 | delivery | 핵심 구간 강조 | 4 | 7 | 5 | 3 | **n/a** | 톤·음량 변화 필요 → `unmeasured` |
| 27 | visual | 낭독 vs 실제 설명 구분 | 6 | 6 | 5 | 3 | det | `Slide.raw_text` vs 해당 구간 `by_slide.text` 의 n-gram 중복률 |
| 28 | visual | 슬라이드별 설명시간 균형 | 5 | 6 | 6 | 3 | det | `SlidePace.status in {short,long}` × `importance` |
| 29 | visual | 그래프·표 설명 | 6 | 7 | 6 | 3 | llm | `visual_type ∈ {chart,table}` 슬라이드 + 해당 구간 발화 |
| 30 | visual | 슬라이드-발화 강조 일치 | 5 | 6 | 5 | 3 | det | `AlignmentSummary.rank_correlation` → `(τ+1)/2 × 100` |
| 31 | time | 제한시간 준수 | 5 | 6 | 8 | 4 | det | `abs(PaceDoc.actual_sec - target_sec) / target_sec` |
| 32 | time | 구간별 시간 배분 | 5 | 6 | 7 | 4 | det | `PaceDoc.sections[].status` |
| 33 | time | 핵심 슬라이드 체류시간 | 4 | 5 | 6 | 3 | det | `SlidePace[importance=="core"].delta_sec` |
| 34 | visual | 슬라이드 정보 밀도 | 5 | 6 | 5 | 3 | det | `Slide.total_char_count` · `line_count` 분포 |
| 35 | visual | 제목-본문 일치성 | 5 | 6 | 6 | 3 | llm | `Slide.title` + `Slide.raw_text` |
| 36 | visual | 목차·로드맵 슬라이드 | 4 | 5 | 5 | 2 | det | `Section.slide_role=="intro"` 존재 or 목차/차례/agenda 키워드 슬라이드 |
| 37 | visual | 데이터 시각화 적절성 | 6 | 6 | 6 | 3 | llm(약함) | `visual_type` + 차트가 텍스트로 변환된 `SlideBlock.text` |
| 38 | visual | 출처·근거 표기 | 7 | 4 | 5 | 2 | det | 출처/source/참고문헌/`[1]` 패턴 검출 |
| 39 | visual | 오탈자·맞춤법 | 4 | 5 | 5 | 3 | llm | `Slide.raw_text` |

**집계: det 19개 · llm 18개 · n/a 2개 = 39개.**
(det = 1,4,5,17,19,20,21,22,23,24,27,28,30,31,32,33,34,36,38 / llm = 2,3,6,7,8,9,10,11,12,13,14,15,16,18,29,35,37,39 / n/a = 25,26)

**신호 품질에 대한 정직한 한계 (리포트에 note 로 노출할 것):**
- 37 데이터 시각화 적절성 — **이미지 바이트가 파이프라인에 오지 않는다.** 차트는 Upstage `chart_recognition` 이 뱉은 텍스트/마크다운으로만 존재한다 (`f01_parse.py:87`). LLM 이 "차트 유형이 데이터 성격에 맞는가"를 제대로 볼 수 없다. `evidence` 에 근거 부족을 명시하거나 `unmeasured` 로 내려도 된다.
- 34 슬라이드 정보 밀도 — `Slide.alignment` 는 `UPSTAGE_DOCPARSE_COORDINATES` 가 기본 `false` 라서 보통 `None` 이다 (`f01_parse.py:35-39`). 레이아웃이 아니라 글자 수·줄 수로만 판단한다.
- 발표자 노트가 파싱되지 않는다. 헤더·푸터는 `NOISE_CATEGORIES` 로 버려진다 (`f01_parse.py:61`).
- 24 휴지 위치 — `PAUSE_SEC = 5.0` (`f18_habits.py:24`) 은 "의미 단위 전환의 자연스러운 정적"을 재기엔 너무 거칠다. 5초 이상 침묵만 잡힌다.
- 1·5·30 은 `_match.py` 의 토큰 매칭 정확도에 얹혀 있다 (한글은 부분 문자열 포함, 2자 미만 label 은 매칭 안 됨 — `_match.py:14,26`).

---

## 1. 집계 공식 (채점표 `점수산정` 시트와 동일)

```
상황 S 고정.

1) 항목 i 의 상태 결정
   w_i(S) == 0                       → status = "situation_excluded"
   측정 실패 / 입력 문서 없음 / n/a  → status = "unmeasured"
   그 외                             → status = "scored", score_i ∈ [0, 100]

2) 클러스터 c 평균 (같은 클러스터 안에서 내부 가중치로 가중평균 — 중복 완화)
   scored_c = { i ∈ c : status == "scored" }
   scored_c 가 비면 → 클러스터 status = "omitted"
   avg_c = Σ(score_i × w_i) / Σ(w_i)          for i ∈ scored_c

3) 클러스터 가중치 재분배 (omitted 클러스터의 몫을 남은 클러스터에 비례 배분)
   present = { c : status != "omitted" }

   ★ present 가 비면 (측정된 항목이 하나도 없음) — 0으로 나누지 말 것:
       score = 0, basis = "partial", 클러스터 7개 전부 status="omitted",
       eff_c = 0.0, note = "이번엔 매길 수 있는 항목이 없었어요"
       → 여기서 즉시 반환한다. 예외를 던지지 않는다.
     이 분기는 실제로 도달한다 (§6 의 빈 바디 curl 이 정확히 이 경로다).
     f13 의 같은 분기(`f13_score.py:143-145`)는 도달 불가능한 죽은 코드였지만,
     여기서는 모든 입력이 optional 이라 살아 있다.

   eff_c = W_c(S) / Σ(W_k(S) for k ∈ present)

4) 최종
   final = round( Σ(avg_c × eff_c) )          → int, 0~100
   contribution_c = avg_c × eff_c
```

**`basis` 의 뜻 — 항상 `"partial"` 이 되지 않게 정의한다.**
항목 25·26 은 **영구적으로** 측정 불가라, 순진하게 `unmeasured 가 있으면 partial` 로 두면 `basis` 는 절대 `"full"` 이 될 수 없고 `app.js:2555` 의 안내 문구가 매 리포트마다 뜬다. 항상 켜진 정직 신호는 소음이 돼서 아무도 안 읽는다. 그래서:

```
n/a 항목(25·26)은 basis 계산에서 제외한다.
basis = "full"  : source != "n/a" 인 항목을 전부 측정했다 ("잴 수 있는 건 다 쟀어요")
basis = "partial": 잴 수 있었어야 할 항목을 못 쟀다 (입력 문서 누락, LLM 실패, mock STT 등)
```
`unmeasured` 리스트에는 25·26 도 그대로 들어간다 — 화면에는 "이번엔 측정할 수 없었어요" 로 보여야 하니까. `basis` 만 이 둘을 무시한다.

**불변식 (테스트로 고정할 것):**
- `Σ eff_c == 1.0` (부동소수 오차 허용 1e-9)
- `final == round(Σ contribution_c)`
- 아무것도 빠지지 않으면 `eff_c == W_c(S)/100` → 채점표 시트와 자릿수까지 동일
- `unmeasured` 는 **0점이 아니다.** 가중치에서 빠질 뿐이다 (f13 이 이미 쓰던 원칙 — `f13_score.py:7-18`)
- `situation_excluded` 와 `unmeasured` 는 **절대 같은 필드에 담지 않는다.** UI 문구가 다르다 — "이 상황에서는 평가하지 않아요" vs "이번엔 측정할 수 없었어요". 합치면 지금 없애려는 그 블랙박스가 다시 생긴다.

---

## 2. 파일별 작업

### 2-1. `chuckchuck/rubric_v3.py` — 신규 (채점표 동결)

§0 의 표를 그대로 상수로 박는다. 로직 없음, 데이터만.

```python
RUBRIC_VERSION = "v3"

SITUATIONS: dict[str, str] = {
    "school_project": "학교 프로젝트 (교수 대상)",
    "product_launch": "신제품 설명 (대중 대상)",
    "work_report":    "업무 보고 (상사 대상)",
    "casual_peer":    "동료 간 캐주얼 PR",
}

CLUSTERS: dict[str, str] = {  # key → 한글 이름. 순서 = 리포트 표시 순서
    "content": "내용 충실도", "logic": "논리 구조", "audience": "목적·청중 적합성",
    "clarity": "언어적 명료성", "delivery": "음성적 전달",
    "visual": "시각자료 활용", "time": "시간 관리",
}

CLUSTER_WEIGHTS: dict[str, dict[str, int]] = { ... }   # §0-1 그대로

@dataclass(frozen=True)
class RubricItem:
    no: int
    cluster: str
    name: str
    description: str        # 채점표 '평가 설명' 열 — LLM 프롬프트에 그대로 넣는다
    source: str             # "det" | "llm" | "n/a"
    weights: dict[str, int] # 상황 key → 내부 가중치

ITEMS: tuple[RubricItem, ...] = ( ... )   # 39개, §0-2 그대로

def items_for(situation: str) -> list[RubricItem]: ...        # weights[situation] > 0 만
def cluster_weight(cluster: str, situation: str) -> int: ...
def resolve_situation(raw: str | None) -> str: ...            # 자유 텍스트 → key, 기본 "school_project"
```

`description` 열은 채점표 `평가기준표` 시트의 '평가 설명' 을 그대로 옮긴다 (예: 항목 2 = "용어를 읽는 데 그치지 않고 의미·원리·관계까지 설명했는가"). 이 문장이 LLM 채점의 기준 원본이다.

`resolve_situation` 은 UI 가 key 를 직접 보내는 게 정상 경로지만, 예전 자유 텍스트(`'사내 보고'` 등)와 라벨 문자열도 받아 준다. 매칭 실패 시 `school_project` 로 떨어지고 **그 사실을 `RubricScore.note` 에 남긴다** (조용히 기본값 쓰지 않는다).

**검증 스텝:** 모듈 로드 시 각 상황의 클러스터 가중치 합이 100 인지 assert. 39개 항목의 cluster 값이 전부 `CLUSTERS` 안에 있는지 assert.

### 2-2. `chuckchuck/contracts.py` — 타입 추가

기존 dataclass 관례(`to_dict` / `from_dict`, 열거형 클램프)를 그대로 따른다. `QaJudgement` (`contracts.py:1634-1711`) 가 가장 가까운 본보기다.

```python
RUBRIC_ITEM_STATUSES = ("scored", "situation_excluded", "unmeasured")
RUBRIC_BASIS = ("full", "partial")

@dataclass
class RubricItemScore:
    no: int
    cluster: str = ""
    name: str = ""
    status: str = "scored"        # 범위 밖이면 "unmeasured" 로 클램프
    score: int = 0                # 0~100, status=="scored" 일 때만 의미 있음
    weight: int = 0               # 그 상황의 내부 가중치 (원본, 재분배 전)
    source: str = ""              # "det" | "llm"
    evidence: str = ""            # 발화 인용 또는 수치 근거 한 줄 — 비면 안 됨
    note: str = ""                # 왜 이 점수인지 / 왜 못 쟀는지

@dataclass
class RubricClusterScore:
    key: str
    name: str = ""
    weight: int = 0               # 상황별 클러스터 가중치 (%)
    effective_weight: float = 0.0 # 재분배 후 (합 1.0)
    average: float = 0.0          # 0~100
    contribution: float = 0.0
    item_nos: list[int] = field(default_factory=list)
    status: str = "scored"        # scored | omitted

@dataclass
class RubricScore:
    score: int = 0
    situation: str = ""           # key
    situation_label: str = ""     # 한글 라벨 — UI 가 그대로 출력
    rubric_version: str = "v3"
    clusters: list[RubricClusterScore] = field(default_factory=list)
    items: list[RubricItemScore] = field(default_factory=list)
    excluded: list[int] = field(default_factory=list)    # situation_excluded 항목 no
    unmeasured: list[int] = field(default_factory=list)  # unmeasured 항목 no
    basis: str = "full"           # unmeasured 가 하나라도 있으면 "partial"
    model: str = ""
    note: str = ""

class RubricError(ChuckchuckError): ...
```

`to_dict()` 는 중첩 dataclass를 재귀적으로 dict 화한다 (`AlignmentDoc.to_dict` 패턴). `from_dict` 는 `status`/`basis` 를 열거형에 클램프하고 `score` 를 0~100 으로 클램프한다.

### 2-3. `chuckchuck/f14_rubric.py` — 신규 (본체)

```python
def score_rubric(
    *,
    situation: str | None = None,
    context: Context | dict | None = None,
    slides: SlideDoc | dict | None = None,
    concepts: ConceptDoc | dict | None = None,
    graph: ConceptGraph | dict | None = None,
    transcript: Transcript | dict | None = None,
    alignment: AlignmentDoc | dict | None = None,
    flow: FlowDiff | dict | None = None,
    pace: PaceDoc | dict | None = None,
    habits: HabitDoc | dict | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> RubricScore
```

**모든 입력이 optional 이다.** 없는 문서에 의존하는 항목은 `unmeasured` 가 되고 가중치에서 빠진다. 부스에서 파이프라인 일부가 실패해도 점수가 나온다.

구조:

1. `situation = resolve_situation(situation or context.situation)`
2. `items = rubric_v3.items_for(situation)`; 가중치 0 항목은 즉시 `situation_excluded`
3. **결정 채점 (`_score_deterministic`)** — 항목별로 작은 순수 함수 하나씩. `_DET_SCORERS: dict[int, Callable]` 로 번호 → 함수 매핑. 각 함수는 `(bundle) -> tuple[int, str] | None` 을 반환하고, `None` 이면 `unmeasured`.
   - 파일이 800줄을 넘으면 `chuckchuck/rubric_det/` 패키지로 클러스터별 분할한다 (`CLAUDE.md` §4 는 **기존** 데모 프론트 파일에만 상한을 면제한다 — 새 파일은 상한을 지킨다).
4. **LLM 채점 (`_score_llm`)** — 클러스터 단위로 배치, 병렬. `ThreadPoolExecutor(max_workers=4)` — `f06_concepts.py:29,252` 와 `f12_chatter.py:581-601` 패턴 그대로.
   - LLM 항목이 있는 클러스터: `content`(2,3,6) · `logic`(7~12) · `audience`(13~16) · `clarity`(18) · `visual`(29,35,37,39) → **최대 5콜, 병렬**. `clarity` 는 항목이 1개뿐이라 `content` 배치에 합쳐도 된다.
   - 프롬프트에 채점표의 `description` 열을 그대로 넣는다. 이게 채점 기준의 원본이다.
   - 응답 스키마: `{"items": [{"no": int, "score": 0~100, "evidence": str, "note": str}]}`
   - **정규화 (f09 `_normalize` 패턴 필수):** 요청하지 않은 `no` 는 버린다. `score` 는 0~100 클램프. `evidence` 가 비면 `unmeasured` 로 강등한다 — **근거 없는 점수는 넣지 않는다.** 이게 이번 개편의 핵심이다.
   - **재시도:** JSON 실패 시 `JSON_RETRY_NUDGE` 로 1회 (`f09_judge.py:656-660` 패턴). 2회 실패한 클러스터는 그 항목 전부 `unmeasured` — 파이프라인 전체를 죽이지 않는다 (`f12_chatter._ask:495-506` 의 부분 실패 허용 방식).
   - JSON 파싱은 `chuckchuck/_json_text.py` 의 `extract_json_object` 를 쓴다 (f06·f20 처럼 사설 복제본을 만들지 않는다).
5. **집계 (`_aggregate`)** — §1 공식 그대로. 여기에만 산수가 있다.

   ```python
   def _aggregate(situation: str, items: list[RubricItemScore]) -> RubricScore:
       """순수 함수. I/O·LLM 없음. 39개 항목의 status/score/weight 만 보고 최종 점수를 만든다."""
   ```
   **이 시그니처가 중요하다.** §4 의 집계 테스트(3·4·5·7·8·9·10·14-b·14-c번)는 `score_rubric` 이 아니라 **`_aggregate` 를 직접 호출한다.** 특히 3번 "모든 항목이 만점이면 100점" 은 `score_rubric` 으로는 **달성 불가능하다** — 25·26 이 영구 `unmeasured` 이고 MockLLM 은 65~85 만 돌려주기 때문이다. 이걸 `score_rubric` 으로 돌리려다 실패를 보고 공식을 "고치면" 안 된다.

6. `basis`, `excluded`, `unmeasured`, `note` 채우고 `RubricScore` 반환.

**모듈 상수 (전부 파일 상단, 매직넘버 금지):** 지시어 사전, 신호어 사전, 낭독 판정 n-gram 크기와 임계값, 정보 밀도 임계 글자 수, 출처 표기 정규식, 시간 준수 허용 오차. 각 상수 옆에 왜 그 값인지 한 줄.

### 2-4. `chuckchuck/providers/llm_impl.py` — MockLLM 분기 **필수**

`MockLLM` 은 유저 프롬프트의 `[TASK] …` 마커로 분기하고, **모르는 마커는 슬라이드 개념 JSON 으로 떨어진다** (`llm_impl.py:65-106`). 분기를 안 만들면 `MOCK_EXTERNAL_APIS=true` 기본 데모 경로 전체가 파싱은 되지만 말이 안 되는 값을 돌려준다.

- 프롬프트에 `[TASK] rubric-score` 마커를 넣는다 (`f09_judge.py:205` 방식).
- `llm_impl.py:65-78` 에 분기를 추가해 요청된 `no` 목록에 대해 그럴듯한 `{"items":[…]}` 를 돌려준다. 점수는 65~85 범위에서 `no` 기반 결정적 값으로 (랜덤 금지 — 데모가 재현돼야 한다). `evidence` 는 반드시 채운다.

### 2-5. `chuckchuck/f19_report.py` — 두 번째 점수 제거

- `_rule_score` (`:70-80`) 와 `_grade_from_score` (`:83-100`) 삭제.
- `compose_report` 에 `rubric: RubricScore | None = None` 파라미터 추가. 있으면 `ReportDoc.score = rubric.score`, 없으면 `score = 0` (추측하지 않는다).
- **`grade` 는 언제나 `""` 로 둔다.** 프론트에 소비자가 하나도 없다 (`grep -rn "grade" demo/YEHS_demo/js/` → 0건). 등급 사다리를 새로 만들 이유가 없다. `ReportDoc.grade` 필드 자체는 계약 호환을 위해 남긴다.
- `_facts_block` 에 클러스터별 평균과 하위 3개 항목을 넣어 LLM 이 **채점표 항목 이름으로** 코칭 문장을 쓰게 한다. `_SYSTEM` (`:18-32`) 의 "점수·등급은 쓰지 마세요" 규칙은 유지.
- **먼저 확인할 것:** `tests/test_voice_report.py:39` 가 `40 <= report.score <= 95` 를 고정하고 있다. rubric 없이 호출하면 0이 되므로 이 테스트를 새 계약에 맞게 고친다 (rubric 을 넘긴 경우와 안 넘긴 경우를 나눠서).

### 2-6. `chuckchuck/f13_score.py` — 폴백으로 강등

- 코드는 **그대로 둔다.** `tests/test_score.py` 의 17개 고정 동작이 마감까지 그린으로 유지된다.
- 모듈 docstring 상단에 추가: `# DEPRECATED (2026-08-09 이후 삭제) — F-14 채점표 채점의 폴백. 새 코드는 f14_rubric.score_rubric 을 쓴다.`
- 호출 경로는 §2-7 참조.

### 2-7. `demo/bridge.py` — 새 엔드포인트

- `_handle_rubric` 추가, `do_POST` 디스패치 테이블(`:290-341`)에 `/api/v1/rubric` 등록. 기존 핸들러(`_handle_score:639`)와 같은 모양 — 400 `bad_request` 봉투, `_mock()` 이면 `llm="mock"`.
- **`PAID_PATHS` (`:59`) 에 `/api/v1/rubric` 을 추가한다.** LLM 을 5콜 태우므로 레이트 리밋 대상이다.
- 바디: `{situation?, context?, slides?, concepts?, graph?, transcript?, alignment?, flow?, pace?, habits?}` — 전부 optional. 프론트 `pipelineOut` 에 이미 다 있다.
- **구현 시 확인:** 이 8개 문서를 한 POST 에 넣으면 바디가 커진다 (단어 타임스탬프가 붙은 `Transcript` 가 특히 크다). `demo/bridge.py` 의 요청 바디 크기 제한을 먼저 확인하고, 모자라면 올린다. 413 이 나면 부스에서 점수가 통째로 안 뜬다.
- **폴백 (`_rubric_from_legacy`):** `score_rubric` 이 예외를 던지면, `alignment` 가 있을 때 `score_presentation` 결과를 **`RubricScore` 모양으로 변환해서** 200 으로 돌려준다. 부스에서 점수가 아예 안 뜨는 것보다 낫다. 변환 규칙 — 프론트의 새 `realSummary()` 가 그대로 렌더할 수 있어야 한다:

  | `RubricScore` 필드 | `PresentationScore` 에서 |
  |---|---|
  | `score` | `ps.score` 그대로 |
  | `clusters[]` | `ps.components[]` 4개 → 유사 클러스터 4개 |
  | `clusters[].key` / `.name` | `c.key` / `c.label` (`핵심 개념 설명` 등 f13 라벨 그대로) |
  | `clusters[].average` | `c.raw * 100` (0~1 → 0~100 **스케일 변환 필수**) |
  | `clusters[].effective_weight` | `c.weight` (f13 가 이미 합 1.0 로 정규화해 둠) |
  | `clusters[].weight` | `round(c.weight * 100)` |
  | `clusters[].contribution` | `c.contribution` |
  | `clusters[].status` | `"scored"` |
  | `items[]` | `[]` (항목별 근거 없음) |
  | `excluded[]` | `[]` |
  | `unmeasured[]` | `list(range(1, 40))` — 39개 항목을 하나도 못 쟀다는 뜻 |
  | `basis` | `"partial"` |
  | `situation` / `situation_label` | `resolve_situation(...)` 결과 그대로 |
  | `rubric_version` | `"v3-fallback"` |
  | `note` | `"채점표로 매기지 못해서 예전 방식으로 매겼어요"` |

  프론트는 `rubric_version` 이 `"v3-fallback"` 이면 리포트 머리글에 `채점표 v3 · {상황}` 대신 `예전 방식 · {상황}` 을 띄운다. 폴백인지 숨기지 않는다.
- `/api/v1/score` 는 **남겨 둔다** (경로 삭제하면 캐시된 옛 JS 가 500 을 받는다).

### 2-8. 프론트 — `dims` 계약 확장

지금 화면은 `dims = [[label, 0~100, chickKey], …]` 3-튜플에 묶여 있고, 4곳이 이 모양을 읽는다 (`app.js:2358, 2404, 2599, 2843`). 클러스터가 7개로 늘어난다.

| 파일 | 위치 | 할 일 |
|---|---|---|
| `js/chuckchuck_bridge.js` | `:381-399` | `/api/v1/score` → `/api/v1/rubric` 로 교체. 실패는 지금처럼 **비치명적** (`score=null` + `score_error`) 유지. `:471` 의 `pipelineOut` 번들에 `rubric` 추가 |
| `js/app.js` | `realSummary():2548` | `sc.clusters[]` → `dims = [name, round(average), CLUSTER_CHICK[key]]`. `sc.unmeasured`/`sc.excluded` 로 note 두 줄을 **따로** 만든다 (합치지 말 것) |
| `js/app.js` | `SCORE_CHICK:2541` | 7개 클러스터 → 4마리 병아리 맵으로 교체. 예: `content·logic→midm`, `audience·clarity→ax`, `visual→exaone`, `delivery·time→solar` |
| `js/app.js` | `reportVerdict():2272-2298` | `basis` 표시를 `F-13 실측` → `채점표 v3 · {situation_label}` 로. 상황이 화면에 보여야 한다 |
| `js/app.js` | `:964` | 상황 선택지를 채점표 4개로 교체. **value 는 key**(`school_project` 등)를 보내고 라벨만 한글로 — 자유 텍스트 매칭에 의존하지 않는다 |
| `js/app.js` | `applauseTier:2598-2617` | 임계값 90/75/60 은 유지. `dims` 가 7개가 돼도 정렬 로직은 그대로 동작한다 |
| `js/playbill.js` | `STAMP_OWNER:32`, `:86-107` | `SCORE_CHICK` 의 독립 복제본. 같이 7키로 고친다. `sc.components[].raw` (0~1) → `sc.clusters[].average` (0~100) 로 스케일이 바뀌므로 `:93-95` 의 .75/.5/.25 임계값을 75/50/25 로 |
| `js/data.js` | `:15-17` | 샘플 `dims` 를 7개 클러스터 3-튜플로 교체. **지금도 3개 2-튜플이라 실측과 어휘가 다르다** — 같은 커밋에서 안 고치면 샘플/실측이 서로 다른 말을 한다 |
| `js/data.js` | `:35-84` | `DATA.reportProfiles.*.dims` 도 같은 모양으로 |
| `index.html` | `:13-56` | **`?v=` 를 한 단계 올린다 (이번 작업에서는 qa13 → qa14).** `CLAUDE.md` §2 가 경고하는 "데모 날 20분 날리는 함정" — 별도 스텝으로 처리 |

**신규 화면 (여유 있으면):** 리포트 요약 탭에 39개 항목 표를 접이식으로. 항목명 · 점수 · 근거 인용 · 상태 칩. `situation_excluded` 는 회색 "이 상황에서는 평가하지 않아요", `unmeasured` 는 "이번엔 측정할 수 없었어요". 이게 있어야 블랙박스가 진짜로 사라진다. 시간이 없으면 클러스터 7줄까지만 하고 항목 표는 마감 후로.

### 2-9. `chuckchuck/__init__.py`

`score_rubric`, `RubricScore`, `RubricItemScore`, `RubricClusterScore`, `RubricError` 를 재export 하고 `__all__` 에 추가 (`:41-42, 64, 102-103, 122, 129` 패턴).

---

## 3. 모의(mock) 모드에서 무엇을 보여줄 것인가

부스 기본 경로가 `MOCK_EXTERNAL_APIS=true` 다. 여기서 가짜 만점이 뜨면 안 된다.

- `MockSTT` (`stt_impl.py:45-57`) 는 단어를 **균등 간격**으로 뱉는다 → `pause_cnt` 가 구조적으로 0, `chars_per_min` 이 상수.
  → **항목 22·23·24 는 mock STT 일 때 `unmeasured` 로 강제한다.** `Transcript.provider == "mock"` 으로 판별. 안 그러면 `delivery` 클러스터가 통째로 만점처럼 보인다.
- 항목 25·26 은 언제나 `unmeasured`.
- 결과: mock 모드에서 `delivery` 클러스터는 측정 가능한 항목이 0개 → 클러스터 `omitted`, 가중치가 나머지 6개에 재분배. 리포트에 "이번엔 음성 전달을 측정할 수 없었어요" 한 줄이 뜬다. **정직하고, 재현 가능하고, 설명 가능하다.**
- 실 API 경로(A.X STT)에서는 22·23·24 가 살아나고 25·26 만 빠진다.

---

## 4. 테스트 — `tests/test_rubric.py` (신규)

스프린트 예외로 TDD 선행은 강제하지 않지만, **집계 공식은 반드시 고정한다.** 이게 틀리면 리포트 전체가 거짓말이 된다.

**어느 함수를 때리는지 먼저 정한다.** 3·4·5·7·8·9·10번은 `_aggregate(situation, items)` 를 **직접** 호출하고 `items` 를 손으로 만들어 넣는다 (§2-3 5번 참조). `score_rubric` 으로 돌리면 25·26 의 영구 `unmeasured` 와 MockLLM 의 65~85 범위 때문에 만점·정확 비교가 불가능하다. 11·12·13·17번만 `score_rubric` + mock LLM 을 쓴다.

1. `test_채점표_가중치_합이_100이다` — 4개 상황 전부
2. `test_39개_항목이_전부_정의됐다` — 번호 1~39 빠짐없이, cluster 값이 전부 유효
3. `test_모든_항목이_만점이면_100점이다` — 4개 상황 전부
4. `test_클러스터_가중치_합계가_1로_정규화된다` — `Σ eff_c ≈ 1.0`, 빠진 클러스터가 있을 때도
5. `test_기여도의_합이_최종점수와_같다` — `final == round(Σ contribution)`
6. `test_상황별로_다른_점수가_나온다` — 같은 항목 점수, 다른 상황 → 최종 점수가 달라야 한다 (상황이 실제로 반영되는지)
7. `test_상황_제외_항목은_점수에_영향이_없다` — 항목 6(선행연구)을 0점/100점으로 바꿔도 `product_launch` 최종 점수 불변
8. `test_측정불가는_0점이_아니다` — 항목 25·26 을 빼도 `delivery` 평균이 떨어지지 않는다
9. `test_제외와_측정불가는_다른_필드다` — `excluded` 와 `unmeasured` 가 섞이지 않는다
10. `test_음성_클러스터가_통째로_빠져도_점수가_나온다` — mock STT 시나리오, 나머지 6개 클러스터로 재분배
11. `test_근거_없는_LLM_점수는_버려진다` — `evidence` 빈 응답 → 해당 항목 `unmeasured`
12. `test_범위_밖_점수는_클램프된다` — LLM 이 150/-20 을 줘도 0~100
13. `test_모르는_항목번호는_버려진다` — LLM 이 no=99 를 줘도 무시
14. `test_입력이_아무것도_없어도_터지지_않는다` — `score_rubric()` 을 인자 없이 → 점수 0, 클러스터 7개 전부 `omitted`, `note` 채워짐, **ZeroDivisionError 없음** (§1 의 `present==∅` 분기)
14-b. `test_잴_수_있는_건_다_쟀으면_basis_가_full_이다` — 25·26 만 `unmeasured` 인 `items` → `basis == "full"` (`_aggregate` 직접 호출)
14-c. `test_폴백_변환이_프론트_계약을_지킨다` — `_rubric_from_legacy(PresentationScore)` → `clusters[].average` 가 0~100 스케일, `Σ effective_weight ≈ 1.0`, `rubric_version == "v3-fallback"`
15. `test_알_수_없는_상황은_기본값으로_떨어지고_기록된다` — `resolve_situation("몰라요")` → `school_project` + `note` 채워짐
16. `test_직렬화가_계약을_지킨다` — `to_dict()` 키 집합 고정, 중첩 dict 화 확인
17. `test_LLM_실패한_클러스터만_빠진다` — 한 클러스터가 2회 실패해도 나머지는 정상 채점

전부 `llm="mock"` 으로 돈다. `python -m pytest tests/test_rubric.py -q` 는 **저장소 루트에서** 실행한다 (`pyproject.toml` 의 `pythonpath=["."]`).

기존 테스트: `tests/test_score.py` 는 그대로 그린이어야 한다 (f13 미변경). `tests/test_voice_report.py` 는 §2-5 대로 수정.

---

## 5. 실행 순서

각 단계 끝에서 `python -m pytest tests/ -q` 를 돌려 회귀가 없는지 본다.

1. `chuckchuck/rubric_v3.py` — 표 동결 + 자체 검증 assert
2. `chuckchuck/contracts.py` — `RubricScore` 3종 + `RubricError`
3. `chuckchuck/f14_rubric.py` — 집계 함수 `_aggregate` **먼저**, det 채점기, 그 다음 LLM 채점기
4. `tests/test_rubric.py` — 최소 1~10번 + 14·14-b (집계 불변식). **여기까지가 정확성의 핵심이다**
5. `llm_impl.py` MockLLM `[TASK] rubric-score` 분기
6. `chuckchuck/__init__.py` 재export
7. `demo/bridge.py` `_handle_rubric` + 라우트 + `PAID_PATHS` + 폴백(`_rubric_from_legacy`)
8. `f19_report.py` `_rule_score` 제거 + `rubric` 파라미터, `test_voice_report.py` 수정
9. `f13_score.py` DEPRECATED 주석
10. 프론트: `chuckchuck_bridge.js` → `app.js` → `playbill.js` → `data.js`
11. **`index.html` 의 `?v=` 전부 한 단계 올리기 (qa13 → qa14)**
12. `docs/SCHEMA.md` 에 §F-14 절 추가 — `RubricScore` 필드 표 + 집계 공식 + 39개 항목 표. `QaJudgement` 절(`SCHEMA.md:987-1010`) 형식을 따른다
13. `CLAUDE.md` / `README.md` 의 모듈 표에 F-14 추가, F-13 을 폴백으로 표기

---

## 6. 검증 (부스 리허설과 동일한 순서)

```bash
cd /home/ubuntu/workspace/00_chuckchuck

# 1) 단위 — 집계 공식
python -m pytest tests/test_rubric.py -v

# 2) 회귀 전체
python -m pytest tests/ -q

# 3) 엔드포인트 — 키 없이
MOCK_EXTERNAL_APIS=true python -m demo.bridge     # http://127.0.0.1:8787/

# 3-a) 퇴화 경로 — 입력이 전혀 없을 때 터지지 않는지 (§1 의 present==∅ 분기)
curl -s -X POST localhost:8787/api/v1/rubric \
  -H 'Content-Type: application/json' \
  -d '{"situation":"school_project"}' | python -m json.tool
#   기대: 200, score=0, 클러스터 7개 전부 status="omitted",
#        excluded 에 6·12·15·16(학교 프로젝트 미평가 항목), unmeasured 에 나머지 전부,
#        note 채워짐, 500 아님

# 3-b) 정상 경로 — 실제 문서를 넣고 (fixtures/ 의 JSON 을 그대로 재활용)
curl -s -X POST localhost:8787/api/v1/rubric \
  -H 'Content-Type: application/json' \
  -d @/tmp/rubric_body.json | python -m json.tool
#   /tmp/rubric_body.json = {"situation":"school_project", "alignment":…, "pace":…, "habits":…, "slides":…}
#   기대: 200, score 0 초과, unmeasured 에 25·26 포함, delivery 클러스터 omitted(mock STT),
#        basis="partial" — 22·23·24 는 n/a 가 아닌데 mock STT 라서 못 쟀으므로.
#        실 A.X STT 경로에서만 basis="full" 이 나올 수 있다.

# 4) 화면 — 브라우저에서 http://127.0.0.1:8787/
#    Ctrl+Shift+R 로 강력 새로고침 (?v= 올렸는지 확인)
#    #/new → 샘플로 파이프라인 실행 → #/report
```

**화면에서 눈으로 확인할 것:**
- [ ] 점수 링에 숫자가 뜨고 `채점표 v3 · <상황 라벨>` 이 같이 보인다
- [ ] 클러스터 막대가 7개, 라벨이 채점표의 한글 클러스터명과 일치한다
- [ ] "이 상황에서는 평가하지 않아요" 와 "이번엔 측정할 수 없었어요" 가 **서로 다른 문구로** 뜬다
- [ ] 상황 선택지 4개가 채점표 그대로다
- [ ] 상황을 바꿔 다시 돌리면 **점수가 실제로 달라진다** (가중치가 진짜 붙었는지)
- [ ] 샘플 모드와 실측 모드의 클러스터 이름이 같다 (`data.js` 를 고쳤는지)
- [ ] 커튼콜 박수 연출이 7개 dims 로도 안 깨진다
- [ ] 리포트 어디에도 45~92 로 클램프된 옛 점수가 안 보인다

**문구 검수 (`CLAUDE.md` §3-1):** 새로 쓰는 모든 문구는 해요체 · 능동형 · 긍정형. `~시`, `계시다`, `여쭈다` 금지. `{명사}+{명사}` 한자어는 풀어쓴다 ("항목 채점 완료" ✗ → "항목을 다 매겼어요" ✓).

---

## 7. 하지 말 것

- **런타임에 xlsx 를 읽지 말 것.** openpyxl 없음, 파일명 NFD. 표는 코드에 동결한다.
- **못 잰 항목을 0점으로 넣지 말 것.** 가중치에서 빼고 이유를 남긴다.
- **`evidence` 없는 LLM 점수를 채택하지 말 것.** 근거 없는 숫자는 옛 블랙박스와 같다.
- **`situation_excluded` 와 `unmeasured` 를 한 필드에 담지 말 것.**
- **MockLLM 분기를 빼먹지 말 것.** 기본 데모 경로가 조용히 망가진다.
- **`?v=` 를 안 올리지 말 것.**
- **마감 전에 `js/app.js`(199KB)·`css/app.css`(94KB) 를 분할 리팩터하지 말 것** (`CLAUDE.md` §4).
- **`--ok/--mid/--no/--ct/--om` 5색과 `ALIGN_VERDICTS` 4-class 열거형을 건드리지 말 것.** 이번 개편의 범위 밖이고, 의미가 붙어 있어 바꾸면 리포트가 거짓말이 된다.
- **새 브랜치를 만들지 말 것.** `fix/qa-evidence-and-demo-hardening` 위에 쌓는다 (`CLAUDE.md` §1).

---

## 8. 마감 후로 미루는 것 (08-09 이후)

- `f13_score.py` + `tests/test_score.py` 삭제, `/api/v1/score` 라우트 제거
- 실제 음향 특징 도입 (librosa 등) → 항목 25·26 되살리기
- 슬라이드 이미지를 비전 모델에 넘겨 항목 37 을 제대로 채점하기
- 39개 항목 접이식 표 UI (§2-8 신규 화면)
- Upstage `coordinates=true` 를 켜서 항목 34 에 레이아웃 정보 넣기

---

## 9. 실제 구현 메모 (2026-08-06 작업 결과)

계획과 달라진 것과, 계획에 없던 발견입니다. 다음에 이 코드를 만지는 사람을 위해 남깁니다.

**계획과 달라진 것**

- **결정 채점기를 `chuckchuck/_rubric_det.py` 로 분리했다.** 한 파일에 두면 800줄을 넘긴다.
  `_match.py`·`_json_text.py` 와 같은 `_` 접두 비공개 도우미 층이다.
- **채점 호출을 F-17·18 뒤로 옮겼다** (`chuckchuck_bridge.js`). 말속도·습관이 있어야
  22·23·24·28·31·32·33 이 채워진다. 정합 판정 직후에 부르면 시간 관리 클러스터가 통째로 빠진다.
- **폴백 변환을 `demo/bridge.py` 가 아니라 `f14_rubric.from_legacy_score()` 에 뒀다.**
  브리지 안에 있으면 테스트할 수 없다.
- **`?v=` 는 qa13 → qa14 였다** (계획을 쓸 때는 qa9 였다 — 그 사이 다른 작업이 올렸다).
  숫자를 외우지 말고 `grep -o '?v=[a-zA-Z0-9]*' index.html` 로 현재 값을 먼저 확인할 것.

**계획에 없던 발견 — 다시 밟지 말 것**

- **`Slide.raw_text` 와 `total_char_count` 는 부풀어 있다.** Upstage 가 `figure` 블록에
  이미지를 보고 쓴 영문 설명을 넣고, `table` 블록 안에도 `<figure><figcaption>` 이 끼어 있다.
  실제 자료에서 한 장이 39,742자였고 그중 사람이 읽는 글자는 2,683자였다.
  F-01 의 `total_char_count` 는 모든 블록 길이의 합이라(`f01_parse.py:289`) 같이 부풀어 있다.
  → **밀도(34)·낭독(27)·출처(38)·목차(36)는 `_rubric_det.readable_text()` 를 쓴다.**
  슬라이드 텍스트를 새로 읽는 항목을 추가한다면 이것도 같이 써야 한다.
- **모의 LLM 점수 폭이 좁으면 상황 가중치가 안 보인다.** 65~85 로 두면 클러스터 평균이
  전부 70 언저리로 뭉개져서, 발표 상황을 바꿔도 최종 점수가 안 움직인다 — 가중치가
  분명히 붙어 있는데도 안 붙은 것처럼 보인다. 42~93 으로 벌려 두었다
  (`llm_impl.py::MockLLM._mock_rubric`). **부스에서 상황을 바꿔 보여 줄 거면 이 폭을 줄이지 말 것.**
- 실측 자료에서 상황별 최종 점수 차이는 크지 않을 수 있다. 클러스터 평균이 고르면
  재분배가 서로 상쇄된다. 이때는 총점이 아니라 **클러스터 가중치 열이 바뀌는 것**을 보여 주면 된다
  (리포트가 `weight` 를 그대로 내려 준다).

**현재 상태**

- `python -m pytest tests/ -q` → **541 passed · 7 skipped** (작업 전 기준선 499 + 신규 42)
- `tests/test_rubric.py` 42개가 집계 불변식·상황 가중치·근거 없는 점수 거절·퇴화 경로를 고정한다
- 브라우저 실제 렌더 확인은 **아직 못 했다** (이 환경에 Chrome 이 없다). CSS 는 읽고 고쳤지만
  (`.verdict-dims` 는 `flex-wrap` 이라 7개도 접힌다 / `.dim-row` 라벨 열 76px → 104px),
  **부스 태블릿에서 `#/report` 와 `#/report/vla` 를 눈으로 한 번 봐야 한다.**
