# 네 모델 Q&A — 4·5단계에 넘기는 데이터 계약 (2026-10-17)

1~3단계 구현: `main/pipeline/_ens_slots.py`(슬롯·거르기·음성 신호, LLM 없음) · `main/pipeline/f08_ensemble.py`(네 모델 호출·묶음·고르기) ·
`main/server/bridge.py`(`/api/v1/qa/pool` · `/api/v1/qa/next` · 질문 요청이 묶음으로 세션 질문을 고름). 켜기 `QA_ENSEMBLE=1`(기본 0).
실험·기준표: `docs/qa-ensemble/PLAN.md` · `etc/bench/qa_ensemble_*.py` · 결과 `/data/models/_runs/qa-ensemble/`.

## 1. 후보 판 (4단계 리포트) — 세션 보관본 `qa_ensemble_board`

`ARCHIVE.read_artifact(session_id, "qa_ensemble_board")` (동의 세션만 저장됨). `Pool.to_dict()` + `picked`:

```jsonc
{
  "slots": [{                       // 그래프 → 질문 대상 지도 (코드가 정함)
    "id": "T1", "node_id": "…", "label": "주장 문장", "kind": "thesis|claim|concept",
    "pattern": "P1", "pattern_desc": "핵심 주장 — …", "angle": "claim|evidence|limit|application|trap",
    "slides": [3], "lines": ["S3.2"], "score": 1.1,
    "partner_id": "", "partner_label": "",          // P5(연결)의 두 번째 노드
    "trap": null                                      // P9: TrapPremise.to_dict() (코드가 만든 틀린 전제)
  }],
  "candidates": [{                  // 거르기 통과 후보 (모델 × 슬롯)
    "uid": "ax:T1:3", "model": "solar|ax|midm|exaone|solar4", "slot": "T1",
    "node_id": "…", "label": "…", "pattern": "P1", "angle": "claim",
    "question": "…?", "answer": "모범답 1~2문장(해요체)", "why": "모델이 댄 이유 한 줄",
    "lines": ["S3.2"], "slide_no": 3, "quote": "근거 자료 줄 원문", "terms": ["자료 고유 낱말"],
    "answer_inference": false,      // true = 모범답에 자료 줄을 잇는 추론이 듦 (절 대조를 다 넘지 못함)
    "peer": 0.84,                   // 0~1, 자기 표 뺀 서로 평가 (PEER_WEIGHTS: core .4 · grounded .2 · specific .25 · clear .15)
    "peer_scores": [{"reviewer": "exaone", "core": 4, "grounded": 5, "specific": 4, "clear": 5, "answer_ok": true, "self": false}],
    "twins": ["midm"]               // 같은 슬롯에서 거의 같은 질문을 쓴 모델 (겹쳐서 하나만 남김)
  }],
  "dropped": [{"uid": "…", "model": "…", "slot": "T3", "reasons": ["micro", "vague_deixis"], "question": "…", "answer": "…"}],
  "calls": [{"role": "generate|peer|pick|voice|gist", "model": "…", "sec": 4.6, "ok": true, "retries": 0,
             "prompt_tokens": 2168, "completion_tokens": 561, "n_in": 0, "n_out": 5}],
  "timings": {"generate_sec": 12.3, "peer_sec": 7.0, "total_sec": 19.4},
  "models": ["solar", "ax", "midm", "exaone"],
  "picked": ["ax:T1:3", "midm:T2:7"]   // 세션에 낸 순서
}
```

- 버림 까닭 이름(`reasons`): `micro`(미시 확인) · `generic`(자료 고유 낱말 0) · `vague_deixis`(가리킬 게 없는 지시어) · `off_slot`(슬롯 대상을 안 물음) ·
  `multi_ask` · `impolite` · `too_long` · `not_korean` · `line_id_leak` · `false_premise` · `number_not_in_deck` · `off_deck_terms` ·
  `bad_line_ref` · `answer_len` · `answer_fragment` · `answer_messy` · `answer_number_not_in_deck` · `answer_off_deck` · `answer_mismatch` ·
  `trap_premise_missing` · `duplicate` · `repeats_asked`(음성) · `skipped`(모델이 「자료가 답을 안 담음」).
- 그래프 경로: `_ens_slots.path_to_root(graph, node_id)` → 노드 → 루트 라벨 목록 (「그래프의 어디를 물었나」).
- **4단계 구현(10-17, `main/server/qa_board.py`)**: 판은 위 칸 + `schema: "qa-board/1"` · `graph.nodes`(id·label·kind·parent_id·weight·slide_nos 만) ·
  `paths`(슬롯 → 루트 라벨) · `track`/`tracks`(트랙별 고른 순서) · `rounds`(3번+ `/qa/next` 마다: n · uid · by · question · signal_kind ·
  pick_reason · substituted · signals · candidates · dropped · calls · voice_sec · pick_sec · path). 보관본과 같은 판을 **세션 메모리**
  (바탕 `STORE ens_board_base:<지문>` → 질문을 받아 간 판마다 `ens_board:<sid>:<run>`)에도 늘 담아, 동의 없는 세션도 `POST /api/v1/qa/board {session_id, qa_run_id}` → `{board}`(없으면 404)로 자기 리포트에서 본다
  (LLM 없음 · 과금 경로 아님). 보관은 그대로 동의 세션만. 앞 답 약점(weak_answer) 신호의 인용(답 원문)은 판에 남기지 않는다.
  화면: `main/web/js/report_qaboard.js` (리포트 2.0 board · slot:<id> · round:<n>), 샘플 판 `js/report_qaboard_sample.js`(`etc/labs/report_v2/make_qa_board.py`).
- 판에 보여 줄 것(제안): 슬롯별로 모델 후보를 가로로, 뽑힌 것 강조 · 서로 평가 점수(누가 누구를 몇 점) · 버린 까닭 칩 · 작성 모델 표시.
  **화면 문구는 해요체**, 판정 색은 쓰지 말 것(판정이 아니다).

## 2. 세션 질문 (지금 화면 그대로) — `/api/v1/questions` 응답

앙상블이 켜져 있으면 `questions[]` 가 묶음에서 고른 `Question` 이다(계약은 그대로 — 판정·힌트 사다리가 그대로 읽는다).
- `Question.basis.checks` 에 `ensemble` · `by:<모델>` · `pattern:P1` · (모범답이 절마다 자료로 받쳐지면) `gist_polished` · (음성) `signal:<종류>`.
- 응답 `ensemble`: `{"active": true, "models": [...], "n_candidates": 13, "timings": {...}, "next": "/api/v1/qa/next"}`
  — Q&A 화면에는 작은 표시만(「네 모델이 발표를 다시 듣는 중」). 묶음이 늦거나 2개를 못 고르면 이 칸이 없고 지금 방식 질문이다.

## 3. 다음 질문 (3번 이후) — `POST /api/v1/qa/next`

```jsonc
// 요청
{"session_id": "…", "asked": [{"question_id": "e01-…", "answer": "답 원문", "verdict": "good|partial|wrong|unknown",
                               "missing": ["빠진 점"]}],
 "prefetch": false, "wait_sec": 0.5}
// prefetch=true → 202 {"started": true}  (1번 질문을 낼 때 · 답마다 불러 음성 후보를 뒤에서 만들기 시작)
// 응답
{"question": {/* client_questions 사본 + hint_ladder */}, "substituted": false, "pick_reason": "한 줄 이유(해요체)",
 "signal": "skipped_reason|vague|misexplained|weak_answer|", "by": "ax"}
```
- 음성 후보를 `wait_sec`(기본 `QA_ENS_NEXT_WAIT_SEC=0.5`) 안에 못 받으면 묶음의 남은 1등을 바로 낸다(`substituted: true`). 몇 번 대신 냈는지는 이 칸으로 센다.
- 서버가 이 질문을 세션 색인에 `ens:<id>` 트랙으로 올리므로 `/qa/judge` 가 그대로 채점한다.

## 4. 꼬리질문 엔진(5단계)이 쓸 입력

- 질문: `Question`(위) — `answer_gist`(깨끗한 모범답) · `basis.checks`(`pattern:P*` · `signal:*`) · `node_id`.
- 노드 이웃: `ConceptGraph` 의 `parent_id` · 자식 · `path_to_root` — 「더 깊이(왜) / 옆으로(이어진 주장) / 바로잡기」 이동(`voice_signals` 의 `move`·`neighbors`).
- 음성 신호: `_ens_slots.voice_signals(graph, slides, speech_of, alignment, answers, lines)` → `[{id, kind, node_id, label, slide_no,
  deck_line, deck_text, speech_quote, note, (weak_answer: move, neighbors)}]`. 숫자 차이는 신호가 아니다(§0-1).
- 답 기록: `asked[]` 의 `answer` · `verdict` · `missing` (F-09 `missing_points`).
- 측정 자리(5단계가 채움): 꼬리질문 고정 문장 비율(10-16: 11/11) · 앞 답 인용률(R8) · 같은 꼬리 반복(R9) — `qa_ensemble_report.py` 에 칸을 더하면 기준표에 붙는다.
- **5단계 최우선 위험(실사용 데이터 10/17)**: 이탈은 첫 wrong 직후 82%, 같은 질문 연속 wrong 최대 25번 — `f09_judge._coach_stage` 가 연속 오답을 안 센다.

## 5. 설정

| 이름 | 기본 | 뜻 |
|---|---|---|
| `QA_ENSEMBLE` | 0 | 켜면 질문 요청이 묶음으로 고른다 · `/qa/next` 가 열린다 |
| `QA_ENS_MODELS` | solar4,ax,midm,exaone | 후보·서로 평가·음성 모델 (solar-pro3 은 10-30 종료) |
| `QA_ENS_ASSIGN` | strength | 슬롯을 누구에게 — strength(패턴별 잘하는 두 모델: `f08_ensemble.STRENGTH`) · all(넷 다) · roles(돌려 가며) |
| `QA_ENS_PICKER` | solar4 | 3번+ 최종 선택 모델 (측정 결과는 MODEL_LEDGER §4) |
| `QA_ENS_SLOTS_PER_CALL` | 5 | 한 호출에 싣는 슬롯 수 (덱당 모델별 1~2회) |
| `QA_ENS_POOL_WAIT_SEC` | 45 | 질문 요청이 묶음을 기다리는 상한 |
| `QA_ENS_NEXT_WAIT_SEC` | 0.5 | 다음 질문이 음성 후보를 기다리는 상한 |
| `QA_ENS_EXAONE_PP` | (끔) | EXAONE presence_penalty (권장 1.5) |
| `QA_ENS_MIDM_SCHEMA` | (끔) | Mi:dm response_format json_schema |
| `QA_GIST_POLISH` | 1 | 지금 방식 질문의 지저분한 모범답 정리(1단계) |

## 6. Q&A 한 판 구분 값 `qa_run_id` (2026-10-17, 5단계 · 4단계 보고)

파싱이 같은 파일의 세션을 재사용한다(부스 덱은 미리 파싱한 세션 하나를 모두가 쓴다). 세션 id 만으로 나누면 같은 파일을 올린 사람끼리
3번 이후 기록(앞 답 · 음성 후보 · 이해 상태 · 이미 한 말 · 판의 「뽑힌 것」)이 섞인다 — 개인정보 · 정확도 둘 다 문제다.

- **만드는 곳**: 브라우저 `chuckchuck_bridge.js` `qaRunId(sessionId, {fresh})` — `r` + 무작위 20자(`[A-Za-z0-9_-]{4,48}`).
  질문 요청(`/api/v1/questions`, prefetch 가 아닐 때)이 새 판을 연다. 세션이 바뀌어도 새로 만든다. `window.ChuckchuckBridge.qaRunId` 로도 부를 수 있다.
- **싣는 곳** (본문 필드 이름 `qa_run_id`): `/api/v1/questions` · `/api/v1/sessions/{sid}/qa/judge` · `/api/v1/qa/next`. 4단계 `/api/v1/qa/board` 도 같은 이름으로 받는다.
- **서버 열쇠**: `server.bridge.qa_run_of(body)` (모양이 틀리면 "") · `run_key(sid, run)` = `"<sid>:<run>"` (run 이 없으면 `"<sid>"` — 옛 클라이언트는 예전처럼).
  - 이해 상태 `dlg_nodes:<sid>:<run>` · 이미 한 말 `dlg_said:<sid>:<run>` (꼬리질문 엔진)
  - 음성 후보 `ens_voice:` 지문에 run 과 앞 답 원문을 넣는다 · 마지막 음성 후보 `ens_voice_last:<pool>:<run>`
  - 후보 판 `ens_board:<sid>:<run>` (합침 10-17) — 바탕(후보 · 거르기 · 서로 평가 · 뽑힌 것)은 질문 결과에 실린 `ensemble.board_key` 로 들고 있다가 `_bind_board` 가 질문을 받아 간 판마다 복사한다(캐시로 받은 판도). 3번+ 기록은 그 판 칸에만 붙는다.
  - 판 보관본 `qa_ensemble_board` 는 세션에 하나(마지막 판)이고 `"qa_run_id"` 칸이 있다 — `/qa/board` 는 메모리에 없을 때 **같은 판 값일 때만** 보관본을 준다.
- **남은 것**: 발표 받아쓰기(transcript)는 여전히 세션 단위다 — 같은 파일 세션에 두 사람이 녹음을 올리면 음성 신호의 「발화」 가 섞일 수 있다.
  파싱 세션 재사용(파일 sha)을 판 단위로 나누거나, 받아쓰기를 판 열쇠로 따로 두는 것은 배포 전 결정이 필요하다.

## 7. 꼬리질문 엔진 (5단계) — 판정 응답에 더한 칸

`QaJudgement.to_dict()` 에 `move`(connect·clarify·challenge·explore·recite·hint·deepen·refocus·explain) · `anchor`(답 원문 구절) ·
`dialogue`(읽기 신호 · 출처 llm/respeak/template/judge/guard · judge_sec · sec_after_judge) · `close_reason` 에 `explained`(갇힘 출구)가 더해졌다.
`closed=true` 면 질문을 닫는다(`mastered`) — 셋째 답 · 둘째 「모르겠어요」, `coach_stage="explain"` · `explanation` 에 근거 장 해설.
