# Report 2.0 — 데이터 매핑 (기존 필드 ↔ 그래프 ↔ 뷰모델 ↔ 화면)

> 기존 필드 이름은 `main/pipeline/contracts.py` · 브라우저 저장본 그대로. 「화면」 열의 01~05 는 [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md) 화면 번호.

## 1. 입력 — 리포트 v2 가 받는 한 묶음
리포트 v2 는 기존 리포트와 **같은 입력**을 쓴다. 새 API 없음.

| 묶음 키 | 실제 원천 | 브라우저에서 꺼내는 곳 | 비고 |
|---|---|---|---|
| `transcript` | `/api/v1/transcribe` 응답 | `nf.pipelineOut.transcript` — **단어(words)는 저장본에서 빠진다** (`app.js:28-59`, `saveLastReport` 5061) | 같은 탭이면 `ChuckchuckBridge` 세션(`cheokcheok:chuckchuck-session`)의 transcript, 아니면 words 없음 → 인용은 `inferred`, 리플레이는 장 단위로 떨어진다 |
| `graph` · `alignment` · `flow` · `pace` · `habits` · `score` · `report` | 각 API | `nf.pipelineOut.*` · `cheokcheok:last-report` | 그대로 |
| `chatter` | `/api/v1/chatter` | 리포트가 극장을 열 때 부름 (`prefetchChatter` 6936) — 저장 안 함 | v2 는 같은 호출을 쓴다(입력 해시 캐시, bridge.py:3082) |
| `questions` · `qa` | `/api/v1/questions` · `qa.live`(sessionStorage `cheokcheok:qa-flow`) | `qa.live.questions · results` | `#/report/last` 로 다시 열면 `qa-history` 만 남아 claim · 꼬리질문이 없다 (AUDIT §4) |
| `deck` | slide_doc 제목 · 장 그림 | `nf.slideTitles` · `preview.pdf` / 부스 덱 `assets/deck-slides/<id>/` | 녹음 재생은 부스 덱만 (`/api/v1/dev/decks/file?kind=audio`) |

프로토타입 재료: `main/web/data/report_v2_rec.json` (`etc/labs/report_v2/make_fixture.py` 가 실험실 실측 응답을 묶음, 출처는 파일 안 `provenance`).

## 2. 필드 → 그래프 → 뷰모델 → 화면
| 기존 필드 | 그래프 | 뷰모델 (`buildViewModel`) | 화면 |
|---|---|---|---|
| `transcript.words[].{text,start_sec,end_sec}` | Utterance `U*` (빌더가 묶음) | `utterances[]{id,text,start,end,slide_no}` | 03 발언 줄 |
| `transcript.marks[]` · `by_slide[]` | TimeSpan `T{n}.{v}` (`marks_estimated` → inferred) | `slides[].spans[]{start,end,estimated}` | 03 시간축 장 띠 |
| `graph.nodes[].{id,label,kind,weight,slide_nos}` | Concept `C:*` | `issues[].concepts` · `evaluators[].remarks[].concepts` | 02 · 04 |
| `alignment.items[].verdict / decided_by` | Assessment `A:align:*` (ui_status ok/no/ct/om/na) | 인사이트 `I:concept · I:unjudged · I:good` | 01 · 03 · 04 |
| `alignment.items[].evidence` | Evidence `V:said:*` → POINTS_TO `U*` (원문 대조) | `proofs[]{kind:'said',text,anchor{start_sec,end_sec,utt_ids}}` | 03 하이라이트 · 01 「근거 보기」 |
| `alignment.items[].deck_quote / deck_slide_no` | Evidence `V:deck:*` → `S*` | `proofs[]{kind:'deck'}` · 코칭 대체 문장 | 04 「자료는 이렇게 말해요」 |
| `alignment.items[].note` | Assessment.note · Insight.why | `why` · `conflict` | 03 「왜 문제인가」 |
| `score.score` | — | `score.value` (등급은 기존 `scoreGrade` 규칙) | 01 보조 점수 |
| `score.clusters[]` | Criterion `K:*` | `score.criteria[]` · `I:cluster:*` | 01 더 보기 |
| `score.items[].{no,name,score,evidence,note,source}` | Assessment `A:rubric:*` | `proofs[]{kind:'rubric'}` | 03 채점 근거 · 01 더 보기 |
| `score.faults[]` | Insight `I:fault:*` | `issues[]` | 01 |
| `pace.slides[].{actual_sec,recommended_sec,delta_sec,status,importance}` | Evidence `V:pace:*` · Insight `I:pace:*` | `proofs[]{kind:'time'}` · `actions[]{kind:'time'}` | 01 · 03 · 04 |
| `pace.target_sec · actual_sec` | Insight.why | `why` | 01 |
| `flow.issues[].{kind,cue,node_ids,slide_nos,note}` | Evidence `V:flow:*` · Insight `I:flow:*` | `issues` / `strengths` | 03 · 04 |
| `habits.spans[].{kind,text,start_sec,end_sec}` | Evidence `V:habit:*` · Insight `I:habit` | `proofs[]{kind:'time'}` | 03 마커 |
| `report.one_liner` | — | `headline` | 01 첫 문장 |
| `report.strengths · weaknesses · actions` | (아직 안 이음 — 자유 글이라 인사이트에 정확히 못 붙는다) | — | 01 「분석 요약」 보조 (D-006 OPEN) |
| `chatter.turns[].{speaker,text,mood,refs}` · `absent` | Evaluator `E:*` · Remark `R*` (+ 근거 검사) | `evaluators[]{name,lane,absent,remarks[]{text,status,why,concepts}}` | 02 |
| `questions[].{id,node_id,question,answer_gist,evidence_slide_no}` | Question `Q:*` · CoachingAction(기대 답) | `qa[]` · `actions[]{kind:'explain',basis}` | 04 제안 · 05 |
| `qa.results[].{verdict,setAside,trail[{q,claim}],answer}` | Answer · FollowUp (GROUNDED_IN) | `qa[].steps[]{claim,followup,answer,verdict}` · `qa[].result` | 05 전환점 |
| (없음) 재연습 결과 | — | — | 05 「재연습 이력」 = not_supported 표시 |

## 3. 쓰지 않는 · 없는 필드 (지어내지 않음)
| 필드 | 상태 |
|---|---|
| `alignment.items[].suggestion · confidence · checks` | 서버에 없다 — 기존 화면은 읽지만 늘 빔 (AUDIT §0). v2 는 읽지 않는다 |
| 「언급만 함」(mid) | 서버 판정에 없음 — v2 에 안 쓴다 |
| 청중 점수 · 칭찬/우려 구분 | ChatterDoc 에 없음 — v2 는 대사 + 역할(lane) + 근거 상태만 |
| 사용자 녹음 파일 | 저장 안 됨 — 리플레이 음성은 부스 덱 녹음일 때만 |
| 전환 문장 도구 | 코드에 없음 (샘플 문구뿐) |
