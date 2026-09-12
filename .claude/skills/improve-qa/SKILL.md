---
name: improve-qa
description: Q&A 질문·판정 프롬프트를 벤치마크 기준으로 자율 개선하는 루프를 띄우거나, 손으로 한 바퀴 돌린다. 실 LLM 호출·과금이 있으므로 변형 수와 판정 여부를 먼저 정한다.
---

# /improve-qa — Q&A 프롬프트 자율 개선 루프

회의(2026-09-12 §4·§5)에서 정한 **고정 benchmark → 반복 평가 → 정량 개선** 을 실행하는 스킬.
전체 그림과 규칙은 [docs/AUTONOMOUS_LOOP.md](../../../docs/AUTONOMOUS_LOOP.md).

## 시작하기 전에 확인

1. `git status --short chuckchuck/f08_questions.py chuckchuck/f09_judge.py` 가 **비어 있어야** 한다. 손대다 만 프롬프트 위에 기준선을 잡지 않는다.
2. `.env` 가 있고 `MOCK_EXTERNAL_APIS` 가 켜져 있지 않다.
3. 과금 규모를 사용자 인자에서 읽는다. 기본은 `judge=false, limit=2, maxVariants=3` (호출 약 4회).
   `judge=true` 는 변형당 호출이 ~9배다 — 사용자가 명시했을 때만.

## 실행 (Workflow 도구)

사용자가 이 스킬을 불렀으면 Workflow 를 돌릴 권한이 있는 것이다. 이름 있는 워크플로 `improve-qa` 를 args 와 함께 부른다.
`stamp` 는 지금 시각을 `YYYYMMDD-HHMM` 으로 만들어 넣는다 (스크립트 안에서는 시각을 만들 수 없다).

```
Workflow({ name: "improve-qa", args: { stamp: "20260912-1130", maxVariants: 3, judge: false, limit: 2, focus: "", push: false } })
```

- `focus`: 이번 루프가 노릴 rubric 항목 (예: "Groundedness — 자료 밖 전제를 없앤다"). 비우면 기준선에서 가장 약한 것.
- `push`: 채택 커밋을 바로 `origin` 에 밀지. 기본 false — **사람이 장부를 보고 민다.**

끝나면 반환값의 `variants` 표와 `docs/QA_BENCH_LEDGER.md` 를 사용자에게 요약한다: 채택 몇 개, 되돌린 몇 개, 왜.

## 손으로 한 바퀴 (Workflow 없이)

```bash
scripts/qa_bench.sh --tag base-$(date +%Y%m%d-%H%M)              # 1. 기준선
# 2. chuckchuck/f08_questions.py 또는 f09_judge.py 에 가설 하나 적용 (.claude/agents/qa-prompt-tuner.md 규칙)
.venv/bin/python -m pytest tests/ -q                                # 3. 회귀
scripts/qa_bench.sh --tag v1-… --compare base-… --note "가설 이름"  # 4. 비교 → VERDICT
# 5. IMPROVED 면 두 파일만 커밋, 아니면 git checkout -- chuckchuck/f08_questions.py chuckchuck/f09_judge.py
```

## 멈추는 조건

- 기준선을 못 잡음 (ERROR) → 원인 보고, 가설 단계로 넘어가지 않는다.
- 같은 가설이 두 번 NOISE → 잡음 폭 안이다. `judge=true` 나 `--bundle-dir` 로 표본을 키우기 전에는 다시 시도하지 않는다.
- 문지기(regression-guard) 실패 → 되돌리고 다음 가설. 테스트를 고쳐 통과시키지 않는다.
- 사용자가 준 `maxVariants` 를 다 썼다 → 끝. 더 돌릴지는 사용자가 정한다.
