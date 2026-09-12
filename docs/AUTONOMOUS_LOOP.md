# Q&A 자율 개선 루프 — 벤치마크가 채택을 결정한다

> 회의(2026-09-12 §4·§5)에서 "Q&A 를 감으로 고치지 않는다. 고정 benchmark → 반복 평가 → 정량 개선" 으로 정했다.
> 이 문서는 그 루프를 **에이전트가 사람 개입 없이 돌리는 환경**의 설명서다.
> 실행은 `/improve-qa` (스킬) 또는 Workflow `improve-qa`. 규칙을 모르면 돌리지 않는다 — 실 LLM 을 부르고 과금된다.

## 1. 한 바퀴가 하는 일

```
기준선 재기 ──▶ 가설 세우기 ──▶ [가설마다] 고치기 ─▶ 문지기 ─▶ 벤치마크 ─▶ 비교
   base-…        rubric 7항목      f08/f09 한 곳     pytest·키    qa_bench.sh    IMPROVED → 커밋, 새 기준
                 장부 참조                            범위        (실 LLM)      그 외    → git checkout
                                                                                          ──▶ 작업 일지
```

| 단계 | 누가 | 파일 | 과금 |
|---|---|---|---|
| 기준선·벤치마크 | `qa-bench-runner` | `scripts/qa_bench.sh` → `examples/qa_eval.py` | **있음** (아래 표) |
| 가설 | 워크플로 안의 가설 에이전트 | 기준선 JSON · 프롬프트 · `docs/QA_BENCH_LEDGER.md` · rubric | 없음 (읽기만) |
| 고치기 | `qa-prompt-tuner` | `chuckchuck/f08_questions.py` · `f09_judge.py` **만** | 없음 |
| 문지기 | `regression-guard` | pytest · 비밀키 · 손댄 범위 | 없음 |
| 비교·판정 | `examples/qa_eval_compare.py` (결정론적, LLM 없음) | `exports/qa_eval/reports/*.md` · `docs/QA_BENCH_LEDGER.md` | 없음 |
| 사람 기준 채점 | `qa-question-judge` (선택) | 결과 JSON 을 rubric 7항목으로 읽는다 | 없음 |

에이전트 정의는 `.claude/agents/*.md`, 오케스트레이션은 `.claude/workflows/improve-qa.js`, 진입점은 `.claude/skills/improve-qa/SKILL.md`.

## 2. 실행

```bash
# 전제: 두 프롬프트 파일이 깨끗하고(.git status 비어 있음), .env 가 있고, mock 이 아니다
git status --short chuckchuck/f08_questions.py chuckchuck/f09_judge.py
```

Claude Code 세션에서:

```
/improve-qa                      # 기본 3변형 · 판정 없음 · 푸시 없음
/improve-qa maxVariants=2 judge=true focus="Groundedness — 자료 밖 전제를 없앤다"
```

또는 워크플로를 직접: `Workflow({name:"improve-qa", args:{stamp:"20260912-1130", maxVariants:3, judge:false, limit:2, push:false}})`.
`stamp` 는 호출자가 만든다 — 워크플로 스크립트 안에서는 시각을 만들 수 없다 (재개 호환).

손으로 한 바퀴 돌리는 순서는 스킬 문서에 있다. 핵심은 **비교 스크립트의 마지막 줄 `VERDICT:` 가 채택을 정한다**는 것이다. 사람이 "좋아진 것 같다" 로 채택하지 않는다.

### 과금 규모 (변형 하나당 LLM 호출)

| 옵션 | 질문 생성 | rubric 심사 | 판정 | 코칭 | 합계 |
|---|---|---|---|---|---|
| 기본 (`rubric=true, judge=false`) | 1 | 1 | 0 | 0 | **2** |
| `rubric=false` | 1 | 0 | 0 | 0 | 1 |
| `judge=true, limit=2` | 1 | 1 | 2 × 4벌 = 8 | 0 | **10** |
| `--coach` 까지 | 1 | 1 | 8 | 2 × 2단 = 4 | 14 |

기준선 1회 + 변형 N회. 기본 설정 3변형이면 호출 8회, 판정까지 켜면 40회. **`maxVariants` 상한은 5** (스크립트가 자른다).
번들 폴더(`--bundle-dir`)로 돌리면 번들 수만큼 곱한다.

## 3. 판정 규칙 (`examples/qa_eval_compare.py`)

- 1차 지표 23개: 특이도·인용률·폴백·말투 3종·판정 4벌·코칭 5종·**rubric 8종**(종합·6항목·환각 수). 각각 좋아지는 방향과 잡음 폭이 코드에 박혀 있다.
- **REGRESSED**: 1차 지표 **하나라도** 잡음 밖으로 나빠짐 → 되돌린다. 다른 지표가 아무리 좋아져도.
- **IMPROVED**: 나빠진 것 없이 하나 이상 좋아짐 → 채택, 새 기준선.
- **NOISE**: 그 밖에 전부 → 채택하지 않는다. 같은 조건으로 한 번 더 재기 전에는 신호가 아니다.
- 지연·프롬프트 크기는 표에만 찍고 판정에 넣지 않는다.

실제 사례: 9/10 의 「막힘 코칭 개선」(`coach-baseline` → `coach-final`)을 이 규칙으로 다시 보면 **REGRESSED** 다.
코칭 지표 3개는 0→1 로 좋아졌지만 인용률 0.74→0.61, 반말 질문 0→3, 함정 바로잡음 1→0 이 같이 나빠졌다.
그때는 사람이 코칭 화면만 보고 좋아졌다고 판단했다. 이 루프였다면 채택하지 않았다.

## 4. 지켜야 하는 것

**루프가 고쳐도 되는 파일은 둘뿐이다.** `chuckchuck/f08_questions.py` · `chuckchuck/f09_judge.py`.

| 절대 안 됨 | 왜 |
|---|---|
| `fixtures/` 수정 | 이게 자다. 자를 고치면 전후 비교가 무의미 |
| `fixtures/holdout/` 읽기 | 최종 검증용. 튜너가 보면 holdout 이 아니다 ([README](../fixtures/holdout/README.md)) |
| `tests/` 수정 | 테스트를 고쳐 통과시키는 순간 문지기가 죽는다 |
| `contracts.py` | 모듈 계약 (DEV_POLICY §4) |
| `demo/YEHS_demo/` | Festa 전 프론트 freeze |
| `.env` · 백엔드 · 모델 교체 | 환경 변경이지 가설이 아니다. 모델 비교는 `qa_eval.py --llm` 으로 따로 |
| `MOCK_EXTERNAL_APIS=true` | 벤치 스크립트가 거부한다 (CLAUDE.md §2) |
| "자료에 없는 내용을 지어내지 마라" 삭제 | PROMPT_DESIGN §1 원칙 1 |
| 자동 `push` | 기본 꺼짐. 채택 커밋은 로컬에 남고, **사람이 장부를 보고 민다** |

## 5. 기록이 남는 곳

| 무엇 | 어디 | git |
|---|---|---|
| 결과 원본 | `exports/qa_eval/<시각>_<tag>.json` | 무시됨 (로컬) |
| 비교 리포트 | `exports/qa_eval/reports/<전>__vs__<후>.md` | 무시됨 (로컬) |
| **장부** (모든 시도, 채택·기각) | [`docs/QA_BENCH_LEDGER.md`](QA_BENCH_LEDGER.md) | **커밋** — 결선 그래프의 원자료 |
| 루프 요약 | `docs/WORKLOG.md` 맨 위 절 | 커밋 |
| 채택된 프롬프트 | `feat(qa-prompt): …` 커밋 (두 파일만) | 커밋 |

결선 발표의 `Baseline → Prompt → Context → Fine-tuning → Festa` 그래프는 장부의 IMPROVED 줄을 이어 그린다.
그래서 **장부는 지우거나 고쳐 쓰지 않는다.** 틀린 줄은 다음 줄에 정정을 붙인다.

## 6. 한계와 다음 일

- **표본이 작다.** 기본은 번들 1개(`live_qa_run.json`)·질문 2개. 한 발표에서 좋아진 게 다른 발표에서 나빠졌는지 못 본다.
  → 할 일 #2 (Eval Set 설계): 동의 세션으로 `exports/eval_bundles/` 를 5~10건 채우고 `--bundle-dir` 로 돌린다.
  번들이 5건 이상이면 잡음 폭을 표준편차 기준으로 다시 정한다.
- **rubric 심사관은 LLM 이다** (`qa_eval.py --rubric`, 번들당 1회). 사람 채점과 얼마나 맞는지는 아직 재지 않았다 —
  로드맵 B2: 사람 20건과 일치율을 먼저 잰 뒤에야 rubric 점수를 믿는다. 그 전까지 rubric 은 "참고", 특이도·인용률·판정이 "판정".
  `qa-question-judge` 에이전트는 그 사람 채점 쪽 기준을 잡는 데 쓴다.
- **번들 N개 평균 비교**는 된다: `--bundle-dir` 가 `<시각>_<tag>.corpus.json` 을 남기고 비교 스크립트가 그걸 먼저 집는다.
- 잡음 폭(특이도 ±0.5, 인용률 ±0.05, rubric ±0.5)은 9/10 결과 다섯 개와 9/12 첫 루프를 보고 정한 값이다. 표본이 늘면 다시 잰다.
- **기저 LLM 자체가 흔들린다.** 9/12 같은 프롬프트로 20분 간격 두 번: 폴백 0/3 → 3/3, 말투 해요체 → 반말. 그래서
  전부 폴백인 측정은 `INVALID` 로 버리고(기준선은 재측정), 말투는 코드가 바로잡는다(`f08 _polite_question`).
  프롬프트로 부탁만 해서 안 지켜지는 것은 코드가 받는다 — 이게 이 루프가 준 첫 교훈이다.
- Festa 뒤에는 Human Eval(회의 §7) 결과를 별도 축으로 둔다. 벤치마크는 "시스템이 좋아졌나", 사람 평가는 "유용한가".
