# Report 2.0 — 기존 기능 · 코드 · 데이터 조사 (Phase 1)

> 2026-10-15 조사. 경로는 저장소 루트 기준, JS 는 `main/web/js/`. **확인한 사실만** 적는다 — 모르는 건 「확인 못 함」.
> 기준 커밋: `71cfd84` (design/overhaul-1012).

## 0. 가장 중요한 발견

1. **스크린샷의 리포트(B+ · 「언급만 함」 · 4:56 인용 · 「이렇게 말해보세요」)는 샘플 데이터다** (`#/report/sample-investor`, `data.js` 의 전역 `DATA`).
   - `mid`(언급만 함)는 서버 판정에 없다 — `STATUS_FROM_VERDICT = {aligned:'ok', missing:'no', contradiction:'ct', justified_skip:'om'}` (`app.js:7325`, 주석 7324).
   - 서버 `AlignmentItem` 에 `suggestion` · `confidence` · `checks` 가 없다 (`main/pipeline/contracts.py:733-786`). 그래서 실측 리포트에선 `node.fix`(`app.js:7381`)가 늘 비고 `realTrophy()` 가 null 이다(`5781-5782`). **「이렇게 말해보세요」 · 트로피는 샘플에서만 찬다.**
   - 실측 시각은 `fmtMarkSec` 의 "MM:SS"(`app.js:3542-3545`), 샘플은 문자열 `'4:56'`.
2. **리포트는 서버에 저장되지 않는다.** 브라우저가 분석 API 응답을 `nf.pipelineOut` 에 모아 그린다. 서버 보관(`var/data/sessions/<날짜>/<sid>/`)은 `manifest.json · preview.pdf · slide_doc.json · transcript.json` 뿐(실제 폴더 확인).
3. **리포트 화면은 발화 단위 시각(`transcript.words` · `by_slide`)을 쓰지 않는다** — 개념별 첫 언급 시각(`alignment.items[].speech_basis.first_mention_sec`)과 장별 시간(`pace.slides[]`)만. 단어 시각은 데이터에는 있다(실측 `transcribe.json` words 182개, `start_sec/end_sec`).

## 1. 리포트 화면 (`renderReport`, `app.js:5246-5411`)

### 1-1. 들어오는 순서
1. `ensureVoicePipelineOut()` (91-140)
2. `reportId = routeParts()[1]` — `#/rehearsal/report` 도 `['report']` (328-331)
3. 샘플 id 는 `sampleOpen()`(= `ccTeam`, `rehearsal.js:1067`) 아니면 `#/report` 로 (5255-5265)
4. `rSampleMode = reportId==='sample-investor'` (5266) → `ensureShowcasePreviewPdf()` (5270)
5. `last` → `restoreLastReport()`, 없으면 빈 카드 (5274-5289)
6. id 도 실측도 없으면 빈 카드 (5292-5310)
7. `DATA.reportProfiles[id]`(vla/pitch/trend) → `renderProfileReport` (5311-5314)
8. `prefetchChatter()` → `reportSessionMeta()` · `reportVerdict()`; 실측이면 `saveLastReport()` (5341)

### 1-2. 머리 (`section.verdict`, 5356-5390)
| 부분 | 함수 | 읽는 필드 |
|---|---|---|
| 메타 줄 | `reportSessionMeta()` 4992-5037 | `graph.file_name/total_slides`, `nf.slideDocMeta`, `nf.fileName`, `transcript.duration_sec`, `nf.sec/min/occ`, `nf.uploadedTake.name` |
| 점수 · 등급 | `scoreGrade(v.score)` 5131-5140 | 서버 `score.score` → A+≥90 · A≥80 · B+≥70 · B≥60 · C+≥50 · C≥40 · D |
| 「먼저 짚을 것」 | `reportFaultRows` 6201-6241 · `reportFaultsHtml` 6265-6290 | `score.faults[].{kind,text,slide_no}`, `alignment.items[].{verdict,deck_quote,deck_slide_no,evidence,note,node_id}`, `alignment.skipped_slides[]`, `speech_overlap`, `speech_match` |
| 기준별 점수 | `dimsHtml` 6062-6093 | 가장 약한 기준 = 「여기부터 보세요」 (`timeManagementReason` 5146 · `clusterReason` 5991 · `DIM_HINT` 5978) |
| 근거 접기 | `verdictBasisHtml` 6138 | `v.basis`, 제외 · 못 잰 항목 수 |

### 1-3. 탭 (`R_TAB_VIEWS`, 5563 · `switchReportTab` 5575)
| 탭 | 함수 | 실측 데이터 | 샘플 데이터 |
|---|---|---|---|
| 요약 | `rSummary` 6665-6859 | 트로피 `realTrophy` 5770(실측은 늘 빔) · 「슬라이드로 보는 발표」 `deckHtml` 7197-7276 · 개념 판정 접기 `judgeTree` · Q&A 기록 `qaHistoryPanelHtml` 6569 | `DATA.session.qa.trophy`, `DATA.priorities` |
| 말하기 | `rDelivery` 8213 → `rPace` 8059-8201 · `rAudience` 6905 | `pace.sections/slides/target_sec/actual_sec/avg_chars_per_min/recommended_cpm`, `habits.{filler,repeat,pause}_cnt · spans`, `report.one_liner/actions` | `DATA.pace/paceStats/timeAlloc` |
| 개념 전달 | `rJudge` 7454-7511 · `jDetail` 7513-7552 | `realJudgeTree` 노드 | `DATA.tree` |
| 흐름 | `rLogic` 7831-7880 | `flow.issues[].{kind,slide_nos,cue,note}`, `order_tau`, `ghost_node_ids` | `DATA.logicBreaks` |
| 채점 근거 | `rRubric` 5845-5934 | `score.items[]` 를 `cluster` 로 묶음, 항목 `no,name,source,score,evidence/note` + 이의 단추 | `DATA.score` |
| 연습 도구 | `rTools` 8239 (`TOOL_SECTIONS` 8233-8237) | 개념도 `liveMapNodes` 8390 · 펀치라인 `livePunchlines` 8407 · 용어 카드 `liveTerms` 8427 — 전부 클라이언트 파생 | `DATA.mapNodes/punchlines/terms` |
| 발표 구성 | `rStrategy` 8340 → `ReportStrategy.render`(`report-strategy.js`) | POST `/api/v1/strategy`(`bridge.py:2923`, `pipeline/f20_strategy.py`) — `chosen.outline[]`, `alternatives`, `recommendation` | 같은 API(`sample` 키는 자동 아님) |

- **「전환 문장」 도구는 없다** — `data.js:163` 샘플 문구에만 나온다.
- 펀치라인 · 용어 카드는 Q&A 질문(`qa.live.questions[].answer_gist`)이나 `graph.nodes[].summary` 에서 뽑는다 — 새 생성이 아니다.

### 1-4. 슬라이드 · 개념 판정 모형
- 라벨 `STATUS = {ok:'설명함', mid:'언급만 함', no:'안 나옴', ct:'자료와 모순', om:'정당한 생략', na:'판정 안 함'}` (`data.js:898`), 색 `--ok/--mid/--no/--ct/--om` (`css/app.css:52-56`, 불변).
- 실측 트리 `realJudgeTree()` 7348-7385: 개념마다 `{id,label,depth,parent,w,slide:'Sxx',status,naWhy,mentions,conf,checks,ev,evTime,why,fix,real:true}`
  - `ev`=`item.evidence`(말한 구절), `evTime`=`fmtMarkSec(speech_basis.first_mention_sec)`, `why`=`item.note`, `fix`=`item.suggestion`(서버에 없음), `mentions`=`speech_basis.mention_count`
  - `na` = 녹음이 자료와 무관하거나 `decided_by==='fallback'` (`conceptUnjudgedWhy` 7318)
  - 장 = `judgeSlideOf` 7333 (모순이면 `deck_slide_no`, 아니면 `min(node.slide_nos)`)
- 장 색 = 그 장 개념 중 가장 나쁜 판정 (`JUDGE_RANK` 5619 · `slideJudgeNodes` 5622)
- 비전 리허설 삐약이 신호 `nf.visionCues[].{slide_no,cue,sec}` (7150)

### 1-5. 점수
- 서버 계산: `pipeline/f14_rubric.py:_aggregate` 120-193 — 39항목 → 7묶음(`rubric_v3.py:36`), 묶음 평균 = 항목 가중 평균, 점수 = Σ평균·가중/Σ가중, 결함 상한 `_apply_faults` 230-250(69 · 10씩 · 하한 39). 실패 시 F-13 대체(`rubric_version` 끝 `-fallback`).
- 클라이언트: `realSummary` 5936-5974 — `status==='scored'` 묶음만 기준 점수로.

### 1-6. 저장
| 무엇 | 어디 | 키 · 함수 |
|---|---|---|
| 진행 중 발표 `nf` | sessionStorage | `cheokcheok:new-flow` (`saveSession/loadSession` 19-64) — slideDoc · transcript 단어 · concepts 는 빼고 `pipelineOut.{graph,alignment,flow,score,pace,habits,report}` 유지 |
| 마지막 리포트 | localStorage | `cheokcheok:last-report` (`saveLastReport` 5061-5095 · `restoreLastReport` 5098-5113) — 단어 · by_slide · 그림 없음 |
| Q&A 기록 | localStorage | `cheokcheok:qa-history` (`qa-history.js:18`) |
| 발표 구성 캐시 | sessionStorage | `cheokcheok:strategy3` (`report-strategy.js:21`) |

### 1-7. 분석 호출 순서 (`runPreparePipeline`, `chuckchuck_bridge.js:412-682`)
`/transcribe`(426) → `/concepts`(375) → `/graph`(394) → `/alignment`(511) → `/flow`(535) → `/pace`(568) → `/habits`(590) → `/rubric`(613) → `/report`(642). 결과는 `nf.pipelineOut` 로 (`app.js:4849-4861`), 탭은 `reportOut()`(4946)로만 읽는다. 청중석은 별도 POST `/api/v1/chatter`(`chatter.js:615`), 재료 `pipelineBundle()`(6988) = graph · alignment · flow.

### 1-8. 테스트
- JS: `report_faults` · `report_hint` · `report_tidy` · `score_model` 스모크 (app.js 함수를 이름으로 잘라 시험). `renderReport` · `deckHtml` · `rSummary` · 저장/복원 · 도구 · 구성 탭은 **시험 없음**.
- Python: test_rubric · test_score · test_alignment · test_flow_diff · test_pace_habits_logic · test_voice_report · test_report_concepts_logic · test_report_recording_trust · test_report_sentence_check · test_strategy 등 (백엔드만).

## 2. 분석 데이터 흐름 (원천 → 정규화 → 평가 → 근거 → 화면)

브라우저가 흐름 전체를 몬다. 서버는 호출마다 계산하고(동의 시 보관) 돌려줄 뿐이다. 모든 POST 는 `bridge.py _route_post` 2280-2336, 본문에 `session_id`.

| 경로 | 처리 (bridge.py) | 파이프라인 | 주고받는 것 |
|---|---|---|---|
| /transcribe | `_handle_transcribe` 3281 | f05 `transcribe`(f05_stt.py:125) + `split_by_slide`(84), 장 시각 재추정 f04 `infer_slide_marks`(`_resegment_transcript` 580) | marks[] · 오디오 → Transcript + `marks_source/confidence/match/estimated/reason` |
| /concepts | 2868 | f06 `extract_concepts` (f06_concepts.py:760) | slide_doc → ConceptDoc |
| /graph | 2953 | f07 `build_graph` (f07_graph.py:1318) | → ConceptGraph |
| /alignment | 3007 | f11 `align_speech` (f11_align.py:834) | graph · transcript → AlignmentDoc (개념 전달 판정) |
| /flow | 3059 | `build_flow_diff` (f11_flow.py:182, LLM 없음) | → FlowDiff |
| /pace | 3203 | f17 `analyze_pace` | → PaceDoc |
| /habits | 3232 | f18 `extract_habits` | → HabitDoc |
| /rubric | 3154 | f14 `score_rubric` (실패 시 f13 대체) | → RubricScore |
| /report | 3255 | f19 `compose_report` | → ReportDoc (총평 · 강점 · 약점 · 할 일) |
| /chatter | 3082 | f12 `build_chatter` (f12_chatter.py:687) | graph · alignment · flow → ChatterDoc (청중석) |
| /strategy | 2923 | f20 `suggest_strategy` | `{analysis}` → 발표 구성 (session_id 없음, 보관 없음) |
| /questions | 3650 | f08 `triage_questions` · `build_questions` | → QuestionDoc |
| /sessions/{id}/qa/judge | 4132 | f09 `judge_answer` (f09_judge.py:3339) | → QaJudgement (+ `grounds`) |
| /sessions/{id}/qa/reframe | 4271 | `reframe_question` (f09_reframe.py:93) | — |

- **없는 것:** 코칭 문장 고쳐 쓰기(rewrite) 엔드포인트 없음. `/api/v1/score`(F-13)는 있으나 웹이 안 부름.

### 2-1. 근거 앵커로 쓸 수 있는 것 (해상도)
| 앵커 | 있음? | 근거 |
|---|---|---|
| 장 번호 `slide_no` | ✅ 모든 산출물 | contracts 전반 |
| 개념 `node_id` | ✅ graph · alignment · flow · chatter(`refs`) · questions | contracts.py:470-599, 1169 |
| 단어 시각 `words[].start_sec/end_sec` | ✅ 단어 단위 (A.X STT, 없으면 발화 단위로 대체) | providers/stt_impl.py:346-364 |
| 장 구간 `by_slide[].start_sec/end_sec` · `marks[]` | ✅ (라이브는 넘긴 시각, 올린 녹음은 내용으로 추정 · `marks_estimated`) | f05_stt.py:84-122, bridge.py:596-613 |
| **발화(utterance) id** | ❌ 없음 — 업체 발화 경계는 버리고 평평한 words 만 | stt_impl.py:345-376 |
| 자료 줄 id | ❌ SlideDoc 에 없음 — 판정 근거 `S{장}-{k}` 는 프롬프트 때만 지어 `JudgeGround.ref` 로만 나온다 | _judge_grounds.py:105-125 |
| 개념 첫 언급 시각 | ✅ `speech_basis.first_mention_sec` · `flow.steps[].first_mention_sec` | contracts.py:705-716 |
| 말한 구절 · 자료 구절 | ✅ `alignment.items[].evidence` · `deck_quote` (문자열) | contracts.py:733-786 |
| 장 그림 | ✅ `preview.pdf` (`/api/v1/preview-pdf?session_id=`) · 부스 덱은 `assets/deck-slides/<id>/*.webp` | bridge.py:2604-2616 |

→ **발화 노드는 우리가 만든다**: `words` 를 문장 경계 · 쉼으로 묶어 `U-{n}` (시작 · 끝 시각 · 원문). 인용은 `evidence` 문자열을 이 발화들에서 **원문 그대로 찾을 때만** 잇는다(못 찾으면 `inferred`).

### 2-2. 저장 · 다시 열기
- 서버 보관(`put_artifact`): slide_doc · concept_doc · concept_graph · alignment_doc · flow_diff · chatter_doc · rubric_score · pace_doc · habit_doc · report_doc · transcript · question_doc · claim_doc 등 + 스트림 `qa_turns` · `feedback`. **동의(consent_learning) 없으면 slide_doc · transcript 만** (contracts.py:3207, session_archive.py:238). 보존 비동의 24시간 · 동의 365일.
- **분석 산출물을 돌려주는 GET 은 없다.** 다시 열기는 브라우저 저장(`#/report/last`) 또는 `#/replay`(저장 받아쓰기로 파이프라인 재실행)뿐.

### 2-3. 녹음 다시 듣기 (리플레이)
- 사용자 녹음은 **어디에도 남지 않는다** — 브라우저 메모리(`ccLastTake._blob`)에만 있고 저장 안 함, 서버는 받아쓰기 뒤 임시 파일 삭제 (bridge.py:3369-3371, 3439-3440). 재생 코드 없음.
- **예외: 부스 시연 덱**은 서버에 녹음이 있고 공개로 준다 (`/api/v1/dev/decks/file?deck=&kind=audio`). 「녹음으로 대신하기」로 분석한 발표는 받아쓰기 시각이 그 파일 시각과 같다 → **실제 음성 구간 재생이 된다.**
- 그 밖의 발표: 같은 탭 안에서는 메모리의 녹음으로 재생할 수 있으나(새로고침하면 사라짐), 지금 코드에 없음 → Phase 3 후보.

### 2-4. 실제 데이터 표본 (프로토타입 재료)
| 경로 | 무엇 | 실/샘플 |
|---|---|---|
| `etc/labs/rehearsal_flow/out/rec_weave/` | 부스 덱 C 「별점은 왜 4.7에 몰리는가」(3장) 녹음 139.7초를 실 API 로 분석한 응답 11종: transcribe(단어 182) · concepts · graph(노드 15) · alignment(15) · flow · pace · habits · rubric(39항목) · voice_report · questions · questions_10 | **실측** (10-13 `--record`) — 청중석 `chatter` 와 Q&A 판정은 없음 |
| `main/web/data/tour/{battery-fastcharge,delivery-rating,microplastic-daphnia}.json` | 부스 덱 녹화 투어 (발표 구간 · 분석 · qa · report) | 실측 (10-11, `source.kind:"recorded"`), `_example.json` 은 합성 |
| `etc/fixtures/live/transcript_live.json` · `voice_report_live.json` | 347초 · 12장 실제 받아쓰기 · 말하기 리포트 | 실측 (장 시각은 추정) |
| `data.js DATA` | sample-investor 리포트 전부 | **샘플** — 화면에 DEMO 로 보여야 함 |
| `etc/fixtures/sample_*.json` · `focus_*` | IMU2CLIP mock · 심어 둔 시나리오 | 샘플 |

## 3. 삐약이 청중석 (F-12 chatter)

**코드상 정체: 「평가위원」이 아니라 「청중」이다** — 점수를 내지 않는다고 명시 (`web/js/chatter.js:8`, `pipeline/f12_chatter.py:368-371`). 명세의 「4명의 AI 평가위원」은 이 청중 넷이다. 역할을 바꾸지 않는다(명세 §1-6).

| id | 이름 | 모델 (`providers/llm_impl.py`) | 코드가 정한 역할 (`f12_chatter.py:365-393`) | 사실 고르기 (결정적) |
|---|---|---|---|---|
| midm | 믿:음 | KT 믿:음 `midm-pro-fp8-kaic` (629-643) | 자료와 말이 어긋난 곳 · 형광펜 · 「흥」 | `_midm_points` 98-143: missing · contradiction · 자료 비중 대비 말 비중 차이 |
| solar | 쏠라 | Upstage `solar-pro3` (605-614) | 발표 구조 · 순서 (자료를 읽음) · 대본 · 「오홍」 | `_solar_points` 146-174: flow `order_jump` · `missing_link`, 순서 일치율 |
| exaone | 엑사원 | LG EXAONE (Friendli dedicated, 646-655) | 칭찬 · 배지 · 「히히」 | `_exaone_points` 177-209: aligned · `good_link` |
| ax | 엑씨 | SKT `A.X-K2` (617-626) | 들은 것 (STT 담당) · 애드리브 · 안 나온 개념 · 말한 시간 · 헤드폰 · 「헐」 | `_ax_points` 212-247: `extra_concepts` · `ghost_node_ids` · 총 발화 시간 |

- 흐름: 코드가 삐약이마다 사실 최대 3개를 고르고(45) → LLM 은 말투만 입힌다(`TONE_GUIDE` 398-460). 2라운드 · 최대 16턴 · 턴당 200자. 녹음이 못 쓰이면 LLM 없이 고정 대사. 실패한 삐약이는 `absent` + 대체 대사.
- 출력 `ChatterDoc{turns[{speaker, text, mood, refs[{node_id, source}]}], speaker_models, speaker_names, absent}` (contracts.py:1123-1219). **점수 · 칭찬/우려 구분 · 인용 · 장 · 시각 필드가 없다.** 구조화된 앵커는 `refs[].node_id` 하나 — 장 번호 · 인용은 자유 글 안에만 (UI 가 정규식 `QUOTE_RE` 로 첫 인용을 뽑음, chatter.js:292).
- 리포트에서: 말하기 탭의 입장 카드(`rAudience` 6905-6927) → 전체 화면 극장 `openAudience` 7039-7110 → 말풍선의 「슬라이드 N」(node → `judgeSlideOf`) → `goJudge(node_id)`. 리포트 본문에는 청중 글이 없다.

### 3-1. 실측 (2026-10-15, rec_weave 분석 그대로 `/api/v1/chatter` 1회 · `out/rec_v2/chatter.json`)
| 삐약이 | 결과 | 근거 대조 |
|---|---|---|
| 믿:음 · 엑사원 | **결석** (`absent`, 대체 대사 「오늘 객석에 못 왔어요」) | midm 키 401 · exaone 응답 깨짐 (10-13 확인과 같음) |
| 쏠라 | 「1번 장 'Model Architecture'부터 … 'Training Objective'에 대한 언급이 전혀 없네」 refs [] | ❌ **근거 없음** — 'Model Architecture' · 'Training Objective' 는 이 덱(별점) 그래프 · 받아쓰기 · 자료 어디에도 없다. 지어낸 말 |
| 엑씨 | 「'평점 인플레이션'이라는 개념이 발표 내내 한 번도 안 나왔어」 refs [ribyu-deiteo] | ⚠️ **상충** — 받아쓰기에 그 낱말은 0회(엑씨 말이 낱말로는 맞다), 그러나 정합은 `aligned`(뜻으로 설명했다, 근거 「4.7이라는 숫자는 음식이 좋아서 나온 게 아니라…」). 또 refs 는 다른 개념(리뷰 데이터)을 가리킨다 |

→ **청중 대사는 그대로 믿을 수 없다.** Evidence Graph 가 대사마다 「refs · 언급한 개념 이름이 그래프에 있는가 · 정합 판정과 맞는가」를 검사해 `supported / conflicting / unsupported` 로 표시해야 한다. 근거 없는 대사(쏠라)는 화면에 근거처럼 보이면 안 된다.

## 4. Q&A (질문 코칭 · 리허설 Q&A)

- 클라이언트 상태 `newLiveState` (`qa_live.js:91-133`). 턴마다 `{question, questionId, answer, verdict, score, gaveUp, clarify, claim}` (1622-1630), 전체 판정은 `L.lastJudgement`.
- 닫힌 질문 `L.results[]` (2115-2124, 2181-2196): `id, label, question, answer, verdict, score, passed, mastered, closeReason, viaCoach, summary, lookSlides, turns, hintLevel, hintUsed, trail(마지막 4개 {q, claim})` + 정답 보기 `revealed/retold/coached`, 내려놓기 `setAside/switchedTo/answers`. 묶음 `liveBucket` 1863-1871 (self · helped · retold · skipped).
- 판정 `QaJudgement` (contracts.py:2792-2921): `verdict(good|partial|wrong|unknown), score, react, missing_points, followup, claim, hints, coach_stage, explanation, evidence_quote, evidence_slide_no, grounds[{slide_no, quote, role(covered|missing|conflict), note, ref:"S4-2"}]` …
  - `claim` 은 **사용자 답 원문의 구절** (정확한 부분 문자열, 아니면 가장 비슷한 답 문장 그대로 — `_answer_claim` f09_judge.py:1469-1500).
- **저장**
  1. sessionStorage `cheokcheok:qa-flow` — 탭을 닫으면 사라짐
  2. localStorage `cheokcheok:qa-history` (최대 30세션, `recordQaHistory` app.js:9657-9708) — 한 질문(beat)에 `label, q, a, verdict, bucket, note, turns, answers, hint…, setAside…` 만. **`claim` · `trail` · `grounds` · `followup` · `score` 는 안 남는다.**
     - ⚠️ 버그 의심: `concept = src.concept||src.node`, `slide = src.slide||src.slide_no` (9669-9671) — 실제 질문엔 `node_id` · `slide_nos` 만 있어서 **실측 Q&A 기록의 개념 · 장이 빈 문자열**이 된다.
  3. 서버 `qa_turns` 스트림 (bridge.py:4256-4266, 판정 전체 포함) — **동의한 세션 · 서버가 만든 질문만**
- 리포트 표시: 요약 탭 `qaHistoryPanelHtml` (6569-6655) — 질문 · 내 답 · 묶음. 근거 · claim · 꼬리질문 흐름은 안 보인다.
- **사전 · 사후 증거**: `before`(첫 시도에 힌트 없이 스스로 설명) → `after`(끝내 스스로 설명), 지표 `first_try_to_self` (9694-9708). 다시 말하기는 **판정하지 않는다**(retold 만). 턴별 점수 변화는 말풍선에만, 저장 안 함. 세션 넘어서는 `ConceptMemory`(F-25) · Playbill 회상 카드.

→ **Socratic Reflection(첫 질문 → 답 → AI 가 주목한 말 → 꼬리질문 → 다음 답)은 같은 탭 안 `qa.live`(sessionStorage) 에서만 온전히 재구성된다.** `#/report/last` 로 다시 열면 claim · 꼬리질문이 없다 → 저장 확장이 필요(Phase 3 후보, DECISIONS OPEN).

## 5. 개념 그래프 · 판정 근거

- F-06 `ConceptDoc` → F-07 `build_graph` (typed 경로 `_typed_graph.py`) → `ConceptGraph{nodes[{id, label, slide_nos, summary, importance, weight, weight_basis, parent_id, depth, kind(thesis|claim|concept), evidence}], edges[{from, to, kind(parent|relates)}], sections, thesis}` (contracts.py:470-599). 노드 id 는 라벨 로마자 슬러그.
- 자료와의 연결은 **`slide_nos` 뿐** — 노드에 줄 id 없음. 줄 id `S{장}-{k}` 는 판정 근거 색인에만 (`_judge_grounds.py:106`).
- 3D 그래프 `#/graph` (`graph3d.js`) 는 따로 있고, `mountReportGraph` 는 내보내지만 리포트에서 부르는 곳이 없다.
- 개념 전달 판정은 `AlignmentItem` (§1-4). `realJudgeTree` 가 읽는 `confidence · checks · suggestion` 은 **서버에 없는 필드** → 늘 0 · {} · ''.

### 5-1. 실측 데이터의 품질 문제 (rec_weave · 별점 덱, Evidence Graph 가 다뤄야 할 것)
| 개념 | 판정 | 문제 |
|---|---|---|
| 4.7은 품질이 아니라 리뷰 수집 방식의 결과다 (thesis) | missing · `decided_by: fallback` · 근거 없음 | 대체값 → 화면 규칙상 `na`(판정 안 함). 주장 루트가 판정 안 됨 |
| 가설 A | missing · `decided_by: code` | 그런데 `note` 는 「가설 A는 설명했으나 기각되어 생략 가능」, `evidence` 는 실제 말한 구절 → **판정과 근거 글이 서로 어긋남**(`conflicting`) |
| 평점 인플레이션 · 리뷰 데이터 | aligned (LLM) | `mention_count 0` · `first_mention_sec null` — 낱말은 안 나왔고 뜻으로 설명. **정합이 시각을 주지 않는다** → 리플레이 위치는 `evidence` 구절을 받아쓰기에서 찾아야만 나온다 |
| (전체) | — | 15개 중 13개가 `first_mention_sec` null. flow `ghost_node_ids` 13개 · `spoken_node_count 3` |
| (좋은 소식) | — | **비지 않은 `evidence` 14개가 모두 받아쓰기 원문에 그대로 있다**(공백 무시 대조) → 단어 시각으로 정확한 구간(시작 · 끝 초)을 잡을 수 있다 |
