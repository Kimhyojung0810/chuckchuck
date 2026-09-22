# 리허설을 기억하는 Q&A — F-25 (2026-09-23 구현)

> 사용자 요청(9/23): "사람들이 QA 를 하면서 답변하는 과정 또한 전부 메모리할 수 있나? 다음 QA 할 때 더 효과적으로 할 수 있는
> 개선 — 서비스 구체화." [audience-evidence-and-deck-consulting.plan.md](audience-evidence-and-deck-consulting.plan.md) §2-1 의
> **L3 「기억하는 교수」** 를 앞당긴 것이다. 상태: **서버 쪽 구현 완료 · 브리지에 연결 · 회귀 1,251 초록.** 화면은 Festa(10/1 잠금) 뒤.

## 0. 한 문장

**답변 과정은 이미 남고 있었다(동의 세션의 `qa_turns.jsonl`). 없던 것은 그것을 다음 리허설로 되가져오는 길이다.**
같은 사람이 같은 발표를 다시 연습하면, 지난 리허설에서 못 넘긴 개념이 먼저 나오고, 질문은 지난번에 빠졌던 점을 겨냥하고,
판정은 "지난번엔 빠졌던 조건을 이번엔 짚었어요" 를 알아보고, 포기하면 코칭이 지난번에 안 통한 되물음을 건너뛴다.

## 1. 무엇을 만들었나

| 조각 | 파일 | 역할 |
|---|---|---|
| 계약 | `contracts.py` `ConceptMemory`·`RehearsalSummary`·`MemoryDoc`(`by_node`·`concept`·`stalled`) · `memory_key`·`memory_similarity` · `SessionRecord.learner_id` · 보관 종류 `memory_doc`(+빠져 있던 `paper_doc`) | SCHEMA §8-H |
| F-25 모듈 | `f25_memory.py` `build_memory(rehearsals)` · `link_memory` | qa_turns 기록 → MemoryDoc. **LLM 0** — 전부 센 것 |
| 보관소 | `demo/session_archive.py` `open(learner_id=)` · `related_sessions()` · `rehearsals_for()` | 같은 사람(learner_id) 또는 같은 파일(sha256)의 **동의한** 지난 세션만 잇는다 |
| F-08 1차 | `triage_questions(memory=)` `_stalled_first` | 한 번도 good 을 못 받은 개념을 앞으로 (상대 순서 유지, rank 재부여) |
| F-08 2차 | `build_questions(memory=)` · 개념 줄 「지난 리허설: 2번 물음 · 마지막 판정 반쯤 · 빠졌던 점: …」 · `MEMORY_SYSTEM_ADDENDUM` | 빈틈을 겨냥해 묻는다. 질문에 "지난번" 이라는 말은 금지 |
| F-09 | `judge_answer(memory=)` `_memory_block` · `coach_stuck(memory=)` | 판정 프롬프트에 사실만 싣고 진전을 알아보게 한다. 지난번에도 포기한 개념이면 narrow → scaffold |
| 경로 | `demo/bridge.py` `_memory_for` · `POST /api/v1/memory` · questions·judge 에 자동 연결 · parse 쿼리 `?learner=` | 세션에 한 번 만들고 캐시. `memory_doc` 아티팩트로 보관 |
| FastAPI | `server/app.py` flat `/questions` · `/sessions/{id}/qa/judge` 가 본문 `memory` dict 를 받는다 | 그 서버는 세션 간 보관소가 없어 브리지가 만든 것을 실어 보내는 계약 |
| 프론트 | `js/chuckchuck_bridge.js` `learnerId()`(localStorage 난수) · `fetchMemory()` | 업로드 때 `?learner=` 한 번. 화면은 아직 없다 |
| 테스트 | `tests/test_memory.py`(12) | 기록→기억, 잇기, 순서, 프롬프트 불변, 판정 블록, 코칭 단계, 보관소 규칙 |

## 2. 흐름

```
지난 리허설(동의 세션) qa_turns.jsonl ──┐
  {question{label,node_id}, answer, hints_shown, give_up, judgement{verdict,score,missing_points}}
                                        ▼
related_sessions(sid)  learner_id 같음 | sha256 같음 · 동의 · 자기 제외 · 최신 5개
                                        ▼
build_memory() ─► MemoryDoc{ sessions:[요약], concepts:[ConceptMemory{asked, attempts, give_ups, verdicts, last/best,
                                                          missing_points(최신 3), hints_max, stalled}] }
                                        ▼ by_node(graph)  이름 → 글자 2-gram Dice ≥ 0.6
triage_questions(memory)  못 넘긴 개념 먼저 ─► build_questions(memory)  「지난 리허설: …」 줄 + 규칙
judge_answer(memory)      「## 지난 리허설에서 이 개념」 블록 ─► coach_stuck(memory)  지난번에도 포기 → scaffold 부터
```

## 3. 결정과 이유

| 결정 | 이유 |
|---|---|
| **기억은 전부 기록에서 센다. LLM 0** | "지난번에 이랬죠" 를 지어내면 사람을 억울하게 한다. 판정·횟수·빠진 점은 이미 코드가 낸 사실이다 |
| **답변 원문은 프롬프트에 싣지 않는다** | 지난 답을 이번 답으로 착각한다(F-09 는 누적 답변을 보는 구조라 특히). 빠진 점(판정이 낸 문장)만으로 과녁은 충분하다 |
| 같은 사람 = 브라우저 난수 id **또는 같은 파일(sha256)**. 파일 이름만으로는 안 잇는다 | 같은 이름의 남의 자료가 붙는다. 이름·계정을 받지 않는다 — 부스에서는 익명이 규칙 |
| 동의한 세션만 (보관소가 거른다) | PRIVACY.md 의 약속. 동의 없는 세션은 하루 캐시라 어차피 없다 |
| 개념은 이름으로 잇고, 낱말이 아니라 **글자 2-gram** 으로 비교 | 노드 id 는 세션마다 다르다. 낱말 Jaccard 는 조사 하나("알림의"/"알림")에 갈라져 0.5 — 글자 단위는 0.73 |
| 순서는 1차(triage)에서만 바꾼다 | 질문 id 가 rank 에서 나온다 — 한 곳에서만 바꿔야 결정적이다. 2차는 받은 순서를 지킨다 |
| 지난번에도 포기한 개념은 되물음(narrow)을 건너뛴다 | 같은 넓이의 되물음이 지난번에 안 통했다. 발판(빈칸)은 LLM 없이 골자에서 만든다 |
| memory 가 없으면 프롬프트·시스템 프롬프트가 **글자까지 예전과 같다** (테스트로 고정) | Festa 데모 경로를 바꾸지 않는다 |
| 최신 5개 리허설까지만 | 오래된 실수로 사람을 못 박지 않는다 (`MEMORY_SESSIONS_MAX`) |
| 화면은 안 만들었다 | 10/1 잠금. `/api/v1/memory` 응답(sessions 요약·concepts)으로 「지난번보다」 카드 하나면 된다 |

## 4. 운영

- **켜는 조건:** 업로드 때 **학습 동의**를 켠 지난 세션이 있어야 이어진다. 같은 브라우저(localStorage id)거나 같은 파일이면 된다.
- **끄기:** 요청 본문 `"memory": false`. mock 모드에서는 만들지 않는다.
- **비용:** LLM 0, 디스크 읽기만(세션에 한 번, 캐시). 질문 프롬프트는 개념당 한 줄 는다.
- **확인:** `POST /api/v1/memory {"session_id": "…"}` → `learner_key` 가 비어 있으면 못 이은 것(note 에 사유). 브리지 로그 `[bridge] F-25 memory key=… stalled=N`.
- **지우기:** 리포트에서 세션을 지우면(기존 기능) 기억에서도 빠진다 — 기억은 매번 보관소에서 다시 센다.

## 5. 검증

- `tests/test_memory.py` 12건 + 회귀 전체 1,251 초록 (09-23).
- 브리지 E2E: 보관소에 동의 세션 2개(같은 learner_id)를 만들고 첫 세션에 턴 2개(partial·포기) → 둘째 세션 `/api/v1/memory` 가
  `learner:…` 열쇠로 잇고 두 개념을 `stalled` 로 냈다 (실측 뒤 세션 삭제).
- 실 LLM 벤치는 아직 없다 — `examples/qa_eval.py` 에 `--memory <memory_doc.json>` 을 붙여 「빠진 점 겨냥률」 을 재는 것이 다음 일.

## 6. 남은 것

- 화면: 질문 코칭 첫 화면에 「지난번보다」 카드 (sessions[0] vs [1] · stalled 개념 칩), 판정 말풍선의 진전 문장은 이미 summary_sentence 로 온다. Festa 뒤.
- 부스 화면(booth.html)은 `parseDocument` 를 안 쓰면 learner id 가 안 실린다 — 같은 파일(sha256)로만 잇는다. 확인 필요.
- FastAPI 서버(`server/`)는 세션 간 보관소가 없다 — 본문 `memory` 를 받는 계약만. 배포 때 브리지와 같은 보관소를 붙이면 `_memory_for` 를 옮긴다.
- 벤치 지표(위 §5) · 리포트(F-19)에 리허설 추이 넣기.
