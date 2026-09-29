"""
Q&A 파이프라인 검증 하네스 (`labs/qa_verify`) — 아무 worktree 에나 걸어 되풀이해 돌리고 회귀를 잡는다.

    .venv/bin/python labs/qa_verify/verify.py --repo <worktree> --tier quick|standard|full

모듈 배치 (잣대와 대상 코드를 섞지 않는다):
- 순수 잣대: textkit · personas · redteam · tags · scoreboard — 대상 저장소 코드를 import 하지 않는다.
- 대상 코드로 도는 자식: target_probe(진입) · regress · replay · guard_audit — 대상의 chuckchuck 을 먼저 올린다.
- 바깥 조립: verify · quick · llm_tier · bridge · ui · conversation · target.
자세한 것은 README.md.
"""
