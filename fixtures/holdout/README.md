# Holdout Test Set — 끝까지 숨겨 두는 검증 세트

회의(2026-09-12 §4) 결정: 개발 중 계속 보는 **Eval Set**(`fixtures/live_qa_run.json`, `exports/eval_bundles/`)과,
마지막 검증에만 쓰는 **Holdout** 을 분리한다. 안 그러면 benchmark 숫자만 좋아지는 overfitting 을 못 잡는다.

## 규칙

- 여기 있는 번들은 **자율 루프·프롬프트 튜너·가설 에이전트가 읽지 않는다** (`.claude/agents/qa-prompt-tuner.md`).
- 파인튜닝 학습 데이터에 넣지 않는다.
- 쓰는 때: 결선 전 Final Validation (§5 6단계) 한 번, 그리고 Festa 전 Freeze 직전 한 번.
- 형식은 `examples/build_eval_bundle.py` 가 만드는 번들과 같다. 학습 동의한 세션만 넣는다 ([PRIVACY.md](../../docs/PRIVACY.md)).

## 채우기 (할 일 #2 — 선호·종원)

```bash
python examples/build_eval_bundle.py --out fixtures/holdout   # 동의 세션 중 5~10건을 골라 옮긴다
scripts/qa_bench.sh --tag holdout-<날짜> --bundle-dir fixtures/holdout --judge --limit 3
```

아직 비어 있다. 채우기 전까지 holdout 검증은 없는 것으로 친다 — 있는 척하지 않는다.
