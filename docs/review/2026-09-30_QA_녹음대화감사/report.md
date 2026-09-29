# 2026-09-30 녹음 모드 #/qa 대화 감사 — WP-S2(8c48180)를 처음 보는 덱 3종으로

> 무엇을 봤나 — 「녹음까지 태워서 질문 코칭」 에서 실제로 오가는 말: 질문 · 힌트 · 판정 · 되물음 · 해설 카드 · 닫는 말 · 결과 화면 · 상세 리포트.
> 덱은 저장소 어디에도 없던 주제 셋(교실 이산화탄소 환기 · 어르신 키오스크 교육 · 사회인 야구 번트 손익)으로 새로 만들었고,
> 모든 문제는 **덱 낱말이 아니라 모듈·함수·규칙**으로 적었다. 제품 코드는 고치지 않았다. 기계용 목록은 `issues.json`.

> 조정자 주(09-30): REC-07 의 「소유자 규칙」 은 감사 지시문의 요약이 지나쳤다. 사용자 결정은 「탐침 질문을 밀어내면서까지 5분 트랙에 함정을 넣지 않는다」 이고
> 5분 트랙의 함정 1개 예산(`QA_TRACK_TRAPS["5"] = 1`)은 원래 설계다. 다만 co2 5분처럼 **건너뛴 장 질문이 밀리고 함정이 들어간 것**은 그 결정의 취지에 어긋나므로
> 수정 방향은 「5분 함정 0」 이 아니라 「근거가 확인된 약점 질문(모순·건너뛴 장·탐침)을 밀어내는 함정 금지」 로 읽는다.

## 0. 한눈에

**R1(틀린 녹음)에 심은 9개(모순 6 · 건너뛴 장 3) 가운데 제품이 잡은 것은 2개다.** 수치 모순 1/3, 방향(비교) 모순 0/3, 건너뛴 장 2/3.
바른 녹음(R2) 3벌 중 1벌에 없는 모순이 「먼저 짚을 것」 과 등급 상한으로 붙었다. 다른 발표 녹음(R3)은 3벌 모두 알아봤다.

| 심은 것 | 교실(co2) | 키오스크(kiosk) | 번트(bunt) |
|---|---|---|---|
| N 수치 모순 | ✓ 5장 60%↔40% · 질문 1번 · 먼저 짚을 것 | ✗ 「31%에서 88%까지」(자료 78%) — REC-02 | ✗ 「72퍼센트 정도」(자료 62%) — REC-02 |
| D 방향 모순 | ✗ 주어 맞바꿈 — 오히려 **그 말을 전제로 한 질문** — REC-01 | ✗ 반의어 — 코드가 「설명함」 으로 올림 | ✗ 수 없이 방향만 — 「짧게 지나감」 질문 둘 |
| S 건너뛴 장 | ✓ 4장(「생략하고」) — 질문이 「왜 생략했나」 — REC-05 | ✓ 3장(「패스하겠습니다」) — 질문이 답을 싣고 나감 | ✗ 7장(「빼고」) 못 읽음 · 「정당한 생략」 — REC-12 |
| U 자료에 없는 주장 | 오탐 없음 ✓ | 오탐 없음 ✓ (「72분」(사람)도 무사) | 오탐 없음 ✓ |
| R2 바른 녹음 | 오탐 없음 ✓ | 오탐 없음 ✓ | ✗ 「이 할도 안 되는」 거짓 모순 — REC-03 |
| R3 다른 발표 | ✓ 자료만 · 알림 · D 상한 | ✓ | ✓ (말하기·시간 측정은 계속 리포트에 — REC-10) |

가장 급한 것(높음 7): REC-01 방향 모순 불감 · REC-02 수치 모순 두 꼴 불감 · REC-03 「N도 안 되는」 거짓 모순 · REC-04 모순 질문에서 틀린 값 고집 통과·맞는 답 55점 ·
REC-05 건너뛴 장 질문 꼴 검사 없음 · REC-06 발표자가 하지 않은 말을 「이 슬라이드에서 한 말」 로 보임 · REC-07 5분 트랙 함정.

## 1. 방법

**환경** — `git worktree add --detach /home/yehschuck/project/wt-audit-rec 8c48180` → 브랜치 `qa/audit-rec`. 브리지:
`DEMO_HOST=127.0.0.1 DEMO_PORT=8833 DEMO_DEV_ROUTES=1 HABIT_PROVIDER=heuristic MOCK_EXTERNAL_APIS=false DEMO_RATE_LIMIT_PER_MIN=0 DEMO_DATA_DIR=<scratch>`
(실 API, 추론 solar, PID 로만 내림). LLM 호출 수는 제품 코드를 건드리지 않고 `PYTHONPATH` 의 `sitecustomize` 로 나가는 HTTP 요청을 한 줄씩 세었다(헤더·키·본문 안 남김).

**녹음 경로** — `ppt/audit_<덱>_r<N>/` 에 PPTX 와 클로바 꼴 `.txt` 를 **실파일로** 넣었다. 「녹음까지」 는 표식 박힌 무음 WAV(`demo/bridge.py _handle_dev_deck_file`)로
업로드 녹음과 같은 길을 타고, `/api/v1/transcribe` 가 전사로 Transcript 를 만든다(`demo/clova_transcript.py`). **장 구분 표시가 없어 F-04 가 글로 장 경계를 추정한다** — 녹음만 올린 사용자와 같은 조건.

**대화** — `labs/qa_convo/run.py prepare --mode audio --track 10` 으로 실제 화면(#/test/qa → 파싱 → 분석 → 리빌 → 시간 고르기 → #/qa)을 태워 질문까지 얼렸다.
페르소나(side_deck · side_speech · typo_claim · dunno 등)는 run.py 의 `Driver` 를 그대로 쓰는 `tools/play_script.py` 로 질문마다 동작 목록을 줬다(`labs/qa_convo/answers/audit_rec_*.json`).
목록에 없는 질문은 판정 없이 넘긴다. 5분 트랙은 `tools/reprepare_track.py` 로 **같은 녹음·같은 분석 결과**의 시작 화면에서 5분을 골랐다(분석이 끝난 뒤 사용자가 5분을 고르는 길과 같다).
주의: co2 5분 질문은 co2 10분 대화 **뒤에** 만들어 리허설 기억(F-25)에 그 대화가 들어갔을 수 있다. kiosk 5분은 대화 전에 만들었다.

**근본 원인 확인** — 화면 증상은 제품 규칙 함수를 **LLM 없이** 같은 입력(실제 Upstage 파싱본 `labs/qa_bench/corpus/audit_*/slidedoc_parsed_upstage.json`)에 다시 돌려 결정적으로 되풀이했다: `tools/probe_rules.py` → `evidence/offline_probes.txt`.

**예산·시간** — LLM **230콜**: 파이프라인(분석·질문) 약 130 · 판정 45 · 결과·리포트 화면을 열 때 다시 부른 객석 약 55(REC-19). 벽시계 약 55분. Upstage 문서 파싱 3회.

**다루지 못한 것** — 함정은 10분 트랙에서 제품이 둔 것만 눌렀다(5분 함정은 제품이 스스로 넣음 — REC-07). 모순 질문이 co2 하나뿐이라 네 페르소나는 그 질문에 10분·5분 두 번씩 걸었다.
**내용(방향) 모순 질문의 대화는 볼 수 없었다** — 제품이 그런 질문을 만들지 못했다. R2 kiosk, R3 kiosk·bunt 의 결과·리포트 화면은 렌더하지 않고 저장된 분석 결과(`pipeline_summary.json`)로만 봤다.
발표 속도 수치는 합성 전사의 구간 시각이 넉넉해 실제보다 느리게 나온다 — 속도 **크기**는 판단에 쓰지 않고 방향·출처만 봤다.

## 2. 덱과 녹음 설계 (심은 것)

`labs/qa_bench/corpus/audit_{co2,kiosk,bunt}/` — `slidedoc.json` · `deck.pptx`(`build_pptx.py`) · `slidedoc_parsed_upstage.json` · `recording_r{1,2,3}.txt` · `transcript*.json` · `truth.json`(녹음마다 심은 것·기대·장별 정답 구간). 생성기 `tools/build_audit_decks.py`.
겉모양을 일부러 갈랐다 — 쪽 번호(「01 / 08」·「- n -」·없음), 식(곱셈·덧셈·뺄셈), 비교(수치 표·퍼센트포인트 표·확률 표), 결론 장.

| 덱 | 장 | R1 틀림 (N 수치 · D 방향 · S 건너뜀 · U 자료에 없는 주장) | R2 바름 — 말로 읽은 수 | R3 다른 발표 |
|---|---|---|---|---|
| **co2** 교실 이산화탄소 환기 | 8 | N 5장 40%→「60퍼센트나」 · D 6장 「맞통풍이 한쪽 창문보다 2배 빨리」→「한쪽 창문만 열었을 때가 맞통풍보다 두 배 빨리」 · S 4장 식 「…오늘은 **생략하고** 바로 결과로 갈게요」 · U 「기말고사 평균도 5점 정도 높았다고」 | 「사십 퍼센트」「천사백오십 피피엠」「두 배」「십사 분·칠 분」「스물여섯 명에서 스물아홉 명」 | 학생회 축제 부스 결산 |
| **kiosk** 어르신 키오스크 교실 | 8 | N 5장 표 78%→「31퍼센트에서 88퍼센트까지」 · D 6장 「…상승 폭이 작았습니다」→「…더 많이 올랐어요」 · S 3장 덧셈 식 「시간이 없어서 **패스하겠습니다**」 · U 「열 명 중 아홉 명은 한 달 뒤에도」 · 덤 「참여하신 72분」 | 「칠십팔 퍼센트」「**두 배 반**」「**일 분 사 초**」「십이 퍼센트포인트」「사천팔백만 원」 | bunt R2 |
| **bunt** 사회인 야구 번트 손익 | 8 | N 5장 62%→「72퍼센트 **정도**」 · D 6장 「강공은 번트보다 1.3배 높았습니다」→「번트를 했을 때가 강공보다 더 높게」 · S 7장 「예외인 경우는 오늘은 **빼고**…」 · U 「메이저리그에서도 10년 사이에 절반으로」 | 「육십이 퍼센트」「**삼십 퍼센트 정도 더 높았던**(=1.3배)」「영 점 팔육 점」「이 할」 | co2 R2 |

## 3. 질문별 대화 요약 표

「심은 것과 대조」 ✓ 맞게 물음 · ✗ 틀림. 대화 칸 `동작→판정/점수`. 전체 대화록은 `evidence/<실행>/play_*/q*.md`.

| 실행 | Q | 근거 | 함정 | 장 | 질문 (앞부분) | 심은 것과 대조 | 대화 |
|---|---|---|---|---|---|---|---|
| co2_r1_t10 | Q1 | contradiction |  | 2,3,5 | 평균 농도가 60퍼센트나 낮아졌다고 했는데 자료 5장과 수치가 다른가요? | ✓ N1 | side_speech: wrong/0 → **partial/75 통과** → partial/55 닫힘 · side_deck: good/85 · typo_claim: 35 → 65 · dunno: narrow → scaffold → explain |
| co2_r1_t10 | Q2 | weak_flow |  | 1,2 | 교실 공기 상태와 이산화탄소 농도 사이의 인과 관계는… |  | off→good: wrong/0 → good/85 |
| co2_r1_t10 | Q3 | weak_flow | 함정 | 1,5,6 | 한쪽 창문 … 값이 10분이라고 했는데… | (D1 걸린 6장에 함정) | trap_agree: 35 → good/85 |
| co2_r1_t10 | Q4 | skipped_slide |  | 4 | **왜 4장을 생략하고 바로 결과로 넘어갔는지** 설명해 주세요 | ✓ S1 · 꼴 ✗ | 이유만 답: **70 통과** → 내용: 85 |
| co2_r1_t10 | Q5 | weak_flow |  | 6 | **왜 한쪽 창문만 열었을 때가 맞통풍보다 두 배 빨리 떨어졌는지**… | ✗ D1 을 사실로 전제 | 전제대로: wrong/0 → 바로잡음: 85 |
| co2_r1_t10 | Q6·Q7 | missing |  | 4,5,6 | 환기 면적… / …실제 측정값과 **일치하는가요**? | (건너뛴 4장 중복) | Q6 short→long: 0 → 85 |
| co2_r1_t5 | Q1 | contradiction |  | 2,3,5 | …자료 5장의 수치는 어떻게 다른가요? | ✓ N1 | side_speech: 39 → **70 통과** → 55 닫힘 · typo_claim: 39 → 65 · dunno: narrow → scaffold → explain |
| co2_r1_t5 | Q3 | weak_flow | **함정** | 1,5,6 | 한쪽 창문 … 10분… | ✗ 5분 함정 | trap_agree: 35 → 85 |
| co2_r2_t10 | Q1–Q7 | weak_flow·missing |  | — | 모순·건너뜀 질문 없음 · Q3 「가장 중요한 변수로 설정된 이유」 | 오탐 없음 ✓ · REC-20 | 리포트: 「먼저 짚을 것」 없음 ✓ |
| co2_r3_t10 | Q1–Q7 | core_weight |  | — | 전부 자료만 · 첫 질문 앞 알림 | ✓ | Q1 good: 85 · 리포트 머리 D ✓ |
| kiosk_r1_t10 | Q3 | skipped_slide |  | 3 | **메뉴 찾기 평균 48초와 … 총 평균 주문 시간 110초**가 주문 포기 문제와… | ✓ S1 · 꼴 ✗ | 한 줄: **75 통과** → 85 |
| kiosk_r1_t10 | Q5 | missing | 함정 | 3 | 「48초 + 35초 + 27초 = 140초」 | ✗ 건너뛴 장에 함정 | 35 → 정정 65 |
| kiosk_r1_t10 | Q2·Q6 | weak_flow·core | 함정 | 2 / 4,8 | 「20명 중 6명」 · 「연 3,400만 원」(라벨 「교실 운영 방식」) |  | — |
| kiosk_r1_t10 | Q7 | under_spoken |  | 2,3,4 | 키오스크는 발표에서 짧게 지나갔어요… | (N1·D1 질문 없음) | 70 → 85 |
| kiosk_r1_t5 | Q2 | weak_flow | **함정** | 2 | 「20명 중 6명」 | ✗ 5분 함정 | 35 → 85 |
| kiosk_r1_t5 | Q3 | skipped_slide |  | 3 | 메뉴 찾기 평균 48초는 **어떤 인터페이스 조건에서 측정된**… | ✓ S1 · 꼴 ✗ | 0 → 85 |
| kiosk_r2_t10 | Q1–Q7 | under_spoken·weak_flow |  | — | Q4 「선정 기준」, Q7 「측정 방법과 조건」 | 오탐 없음 ✓ · REC-20 | — |
| kiosk_r3_t10 | Q1–Q7 | core_weight |  | — | 전부 자료만 | ✓ | — |
| bunt_r1_t10 | Q1 | under_spoken |  | 4 | 번트 전략의 순손실 수치가 실제 계산과 일치하는지 **확인해 주세요** | (주제 자리) | — |
| bunt_r1_t10 | Q3 | under_spoken | 함정 | 6 | 「…**0.8배 높았습니다**」 | ✗ REC-13 | — |
| bunt_r1_t10 | Q4 | under_spoken | 함정 | 4 | 「**71** − 0.86 = −0.11점」 | ✗ REC-13 | 0 → 85 |
| bunt_r1_t10 | Q5·Q7 | under_spoken |  | 6 | 「…발표에서 짧게 지나갔어요. 자료 6장의 핵심을…」 두 번 | ✗ D1 을 「짧게 지나감」 으로 | Q7 뒤집은 말: wrong/0 ✓ → 85 |
| bunt_r1_t10 | Q6 | core_weight |  | 5 | …프로 리그 대비 **19%p 낮다고 했는데**… | ✗ N1 대신 자료 주장을 발표자 말로 | 72% 고집: wrong/0 ✓ → 80 |
| bunt_r2_t10 | Q1 | contradiction |  | 7 | “그리고 타율이 이 할도 안 되는 타자라면…” … 자료 7장의 **수치와 달라요** | ✗ **거짓 모순** | 「같은 말이에요」: 85 — 리포트 결함은 그대로 |
| bunt_r3_t10 | Q1–Q7 | core_weight |  | — | 전부 자료만 | ✓ | — |

## 4. 문제 목록

높음: 잘못된 사실을 말하거나(질문·판정·리포트) 설계 규칙을 어김 / 중간: 코칭 가치를 크게 깎음 / 낮음: 문구·표시·비용.
재현 — UI 두 번 이상 `재현 n회`, 한 번 `1회`, 제품 함수로 LLM 없이 되풀이 `오프라인 결정적`(`evidence/offline_probes.txt`). 경로는 이 폴더 기준.

### REC-01 · 높음 · 방향(비교) 모순을 하나도 못 잡는다 — 뒤집어 말한 비교가 「설명함」 이 되고 그 말을 전제로 한 질문이 나간다
- 증상 — co2: 「한쪽 창문만 열었을 때가 맞통풍보다 두 배 빨리」(자료 반대)가 aligned, Q5 「왜 한쪽 창문만 열었을 때가 맞통풍보다 두 배 빨리 떨어졌는지 설명해 주세요」(함정 표시 없음, 골자는 반대 사실).
  kiosk: 반의어 문장이 `decided_by=code` aligned. bunt: 6장이 「짧게 지나갔어요」 질문 두 개. 리포트 「먼저 짚을 것」 에 없음, 6장 「설명함」, kiosk 강점 「슬라이드 6번과 7번은 … 이해하기 쉬웠어요」.
- 증거 — `evidence/co2_r1_audio_t10/prepared.json`(Q5) · `evidence/co2_r1_audio_t10/play_20260930_050457_main/q5_premise_follow_then_fix.md`·`_10_answer.png` · `evidence/kiosk_r1_audio_t10/pipeline_summary.json`(screen-mode) · `evidence/bunt_r1_audio_t10/prepared.json`(Q5·Q7) · `evidence/offline_probes.txt` §1·§2
- 재현 — 3/3 덱 · 오프라인 결정적(가장 단순한 「번트가 강공보다 … 더 높았어요」 도 못 잡음)
- 근본 원인 — `chuckchuck/_deck_claims.py:_than_sides` 가 「보다」 앞 두 줄기를 한 덩어리로 잡아 주어·대상을 못 가르고, `_swapped_comparison` 은 둘이 겹치면 건너뛴다(「X보다 … Y」 꼴만 봄 — 「A는 B보다 V」 맞바꿈 불가).
  `direction()` 꼬리(`_DIR_TAIL_RE`)에 졌·진·져·갔·간 이 없어 「떨어졌습니다·내려갔어요」 가 방향 낱말이 아니다. `directions()` 는 명사 「상승 폭」 도 세어 {up, down} → `_polarity_one` 이 건너뛴다.
  같은 규칙을 F-11(`_align_checks.contradictions`)과 F-08 전제 검사가 같이 쓴다.
- 수정안 — 비교를 (주어, 비교 대상, 서술 방향) 세 칸으로 읽어 자료 줄과 견준다. 지다·가다 활용을 꼬리에 넣고, 방향 낱말 뒤가 명사 머리(폭·률·량·세)면 명사로 친다. F-08 은 새 대조로 LLM 질문 전제를 걸러 뒤집은 발화 전제는 모순 질문으로.
- 파일 — `chuckchuck/_deck_claims.py` · `chuckchuck/f08_questions.py` · `tests/test_speech_alignment_wpa.py` 류

### REC-02 · 높음 · 수치 모순을 두 꼴에서 놓친다 — 「A에서 B로」 짝, 「N 정도」 어림
- 증상 — kiosk 「교육 전 31퍼센트에서 교육 후 88퍼센트까지」(자료 78%) · bunt 「72퍼센트 정도」(자료 62%) 모두 aligned. bunt 는 대신 Q6 「…19%p 낮다고 **했는데**」 — 발표자가 하지 않은 자료 주장을 발표자 말로.
- 증거 — `evidence/kiosk_r1_audio_t10/pipeline_summary.json` · `evidence/bunt_r1_audio_t10/pipeline_summary.json`·`prepared.json`(Q6) · `evidence/offline_probes.txt` §1(뒤 값만 말하면·「정도」 빼면 잡힘)
- 재현 — 두 꼴 UI 1회씩(다른 덱) · 오프라인 결정적
- 근본 원인 — `chuckchuck/_deck_claims.py:_unsupported_numbers` 가 같은 절에서 주인의 자료 값(31%)을 말했으면 덧붙인 수(88%)를 면제. `_near_value` 는 어림 표지면 ±15% 상대 오차를 **그 칸의 같은 단위 값 아무것에나** — 72% 가 같은 줄 프로 리그 81% 에 붙음.
- 수정안 — 면제는 `_derived`(합·차)로 설명되는 수에만. 「A에서 B로/까지」 는 표 열(전·후) 순으로 짝지어 견줌. 어림은 주어가 가리키는 값과만, % 는 퍼센트포인트 폭(「72 정도」 → 70~75).
- 파일 — `chuckchuck/_deck_claims.py` · 테스트

### REC-03 · 높음 · 바른 발표에 거짓 모순 — 「N도 안 되는」(= N 미만)을 부정으로 읽는다
- 증상 — bunt R2 첫 질문 「…“그리고 타율이 이 할도 안 되는 타자라면 번트가 나아요”라고 했는데, 자료 7장의 **수치와** 달라요. 어느 쪽이 맞나요?」. 발표자 「같은 말이에요」 에 코치는 good/85 로 인정했지만
  리포트는 「먼저 짚을 것 1가지 — 자료 7장과 맞다·아니다가 반대예요」 · 「등급은 B까지만」 · 「78점에서 낮췄어요(69)」. 질문은 「수치」, 리포트는 「맞다·아니다」.
- 증거 — `evidence/bunt_r2_audio_t10/qa_first.png` · `evidence/bunt_r2_audio_t10/play_20260930_050755_q1_no_contra/q1_no_contradiction_claim.md`·`99_report.png` · `evidence/bunt_r2_audio_t10/pipeline_summary.json` · `evidence/offline_probes.txt` §3
- 재현 — UI 1회 · 오프라인 결정적(「2할도 안 되는」「2할이 안 되는」 도 걸림, 「2할 미만인」 은 무사)
- 근본 원인 — `chuckchuck/_deck_claims.py:negated`(`_NEG_RE`)가 수량 한정 「(수)도/이/가 안 되는」 을 명제 부정으로 읽고 `_polarity_one` 이 자료 「미만」 줄과 반대라 친다.
  `chuckchuck/f08_questions.py:_contra_numeric` 은 모순 종류를 버리고 자료 쪽에만 남은 수로 「수치」 라 부른다(「이 할」 을 `_spoken.spoken_numbers` 가 안 바꿈).
- 수정안 — 수+(도|이|가)?+안 되/못 되/안 넘/못 미치/미만/이하 를 같은 한정으로 정규화해 부정 대조에서 뺀다. 「N할」 을 spoken_numbers 에. 모순 종류를 AlignmentItem 에 실어 질문이 쓴다. 코치가 같은 말을 인정하면 리포트 결함을 풀린 것으로 표시.
- 파일 — `chuckchuck/_deck_claims.py` · `chuckchuck/_spoken.py` · `chuckchuck/f08_questions.py` · `chuckchuck/contracts.py` · 테스트

### REC-04 · 높음 · 모순 질문 판정: 틀린 값 고집이 통과하고, 맞는 답은 55점·「자료 2장과 한 번 더 맞춰 볼 부분」 으로 닫힌다
- 증상 — co2 Q1, side_speech. 1턴 「60퍼센트가 맞아요」 → wrong 인데 반응이 곧바로 답(40%)을 말함. 2턴 「60퍼센트가 맞다고 생각해요. 제가 직접 측정했어요」 → **75(5분 70) · passed · 「제대로 설명했어요」**.
  3턴 완전히 맞는 답 → **55**, 「세 번째 답이라 … **자료 2장**과 한 번 더 맞춰 볼 부분은…」, 결과 「도움 받아 닫음 · 자료와 다시 맞춰 볼 곳이 남았어요」(2장은 무관, 모순은 5장). side_deck 은 첫 답 good/85 로 바르게 닫힘.
- 증거 — `evidence/co2_r1_audio_t10/play_20260930_050457_main/q1_side_speech.md`·`q1_side_speech_01~03_answer.png`·`99_result.png`·`99_report.png` · `evidence/co2_r1_audio_t5/play_20260930_051017_main/q1_side_speech.md` · `evidence/offline_probes.txt` §4
- 재현 — 재현 2회(10분·5분) · 오프라인 결정적(맞는 답 → `number@2장 ↔ «1,000ppm 이상에서는…»`, 틀린 고집 → 어긋남 없음)
- 근본 원인 — ① `chuckchuck/f09_judge.py:judge_answer` 에 모순 질문 가드가 없다(파일에 contradiction 이 안 나온다) — 발표 쪽 값 재주장 검사도, 반응의 자료 값 누설 검사도 없다.
  ② `chuckchuck/_deck_claims.py:numbers`(`_NUM_RE`)가 ppm·kg·km·MB 를 단위로 안 읽어 「ppm」 이 주어 낱말이 되고, `_number_conflicts` 가 「ppm」 이 든 아무 줄(2장)을 주인으로 삼아 맞는 답에 어긋남(상한 55). 답이 부른 「5장」 도 안 본다.
  ③ `f09_judge._GUARD_CLOSE_REACT` 가 그 가짜 `conflict.slide_no` 를 닫는 말에 넣는다.
- 수정안 — F-09 `source == "contradiction"` 가드(발표 쪽 수·방향 재주장 + 자료 쪽 값 없음 → wrong 상한·코드 반응, 자료 값을 말하면 가드로 안 깎음, 반응·되물음에 `_contra_leaks`). `_NUM_RE` 에 로마자 단위. 답이 장을 부르면 그 장 줄을 주인 후보 앞에. 닫는 말 장은 `evidence_slide_no`.
- 파일 — `chuckchuck/f09_judge.py` · `chuckchuck/_deck_claims.py` · 테스트

### REC-05 · 높음 · 건너뛴 장 질문은 꼴 검사가 없어 「왜 건너뛰었나」 나 답을 다 실은 질문이 나간다
- 증상 — co2 Q4 「왜 4장을 생략하고 바로 결과로 넘어갔는지」 — 「시간이 모자랄 것 같아서 생략했어요」 만으로 **70 통과**(내용 없음). kiosk Q3 는 건너뛴 장 답(48+35+27=110초)을 질문이 다 말해 한 줄 답이 **75 통과**.
  kiosk 5분 Q3 「어떤 키오스크 인터페이스 조건에서 측정된 수치인가요?」 — 자료에 없는 조건. 힌트 1단도 답을 줌. 이유 줄은 세 질문 모두 바름.
- 증거 — `evidence/co2_r1_audio_t10/play_20260930_050457_main/q4_literal_then_content.md`·`_08_answer.png` · `evidence/kiosk_r1_audio_t10/play_20260930_050755_main/q3_short_then_good.md`·`_01_answer.png` · `evidence/kiosk_r1_audio_t5/prepared.json`(Q3)
- 재현 — 재현 3회(2덱, 10분·5분)
- 근본 원인 — `chuckchuck/f08_questions.py:_normalize_questions` 는 모순(`_contra_asked`)·탐침(`probe_shaped`)·함정(`question_carries`)은 LLM 문장을 검사해 템플릿으로 바꾸지만 건너뛴 장은 **이유 줄만** 바꾼다.
  명세 문장 「발표에서 N장은 넘어갔는데, 그 장의 …을 설명해 주세요」 는 `_fallback_question` 에만 있다(주석 「태도를 묻지 않는다 — 규칙 3」 을 LLM 문장은 안 거침).
- 수정안 — `_skip_asked(question, skip, node, idx)`: 장 번호나 대표 개념을 부르고, 내용을 묻고(「왜 생략」 금지), 그 장 자료 줄의 수·10글자 조각을 싣지 않을 때만 LLM 문장, 아니면 템플릿. 힌트 1단도 같은 누설 검사.
- 파일 — `chuckchuck/f08_questions.py` · `tests/test_speech_consumers_s2.py`

### REC-06 · 높음 · 발표자가 하지 않은 말을 「이 슬라이드에서 한 말」 로 보여 준다
- 증상 — co2 R1 리포트 6장: 「설명함 · 맞통풍 · 이 슬라이드에서 한 말: 앞문까지 다 열 필요는 없다는 거죠. **맞통풍은 한쪽 환기보다 농도가 2배 빨리 떨어집니다.** 03:07」 — 뒤 문장은 녹음에 없다(발표자는 반대로 말함). 방향 모순(REC-01)을 덮었다.
- 증거 — `evidence/co2_r1_audio_t10/report_slide6.png` · `evidence/co2_r1_audio_t10/pipeline_summary.json`(cross-ventilation·one-side-ventilation) · `evidence/offline_probes.txt` §6. 녹음 모드 6회 근거 106개 중 지어낸 문장 든 것 2개.
- 재현 — UI 1회(개념 2개) · 오프라인 결정적
- 근본 원인 — `chuckchuck/_align_checks.py:resolve_evidence` 가 인용 전체 겹침만 재서, 진짜 문장+지어낸 문장(겹침 0.15~0.35)을 `return "" if best_score < EVIDENCE_FABRICATED_MAX else ev_text` 로 그대로 둔다.
- 수정안 — 문장마다 한 구간 안에 거의 그대로(≥0.8) 있는지 보고 없는 문장은 뺀다. 남은 문장이 개념을 못 받치면 판정을 내린다. 리포트는 검증된 문장만.
- 파일 — `chuckchuck/_align_checks.py` · `chuckchuck/f11_align.py` · 테스트

### REC-07 · 높음 · 5분 트랙에 함정 (소유자 규칙: 5분 함정 없음)
- 증상 — 5분 두 번 모두 3문항 중 1개가 함정(kiosk Q2 「20명 중 6명」, co2 Q3 「10분」). co2 5분은 건너뛴 4장 질문 대신 함정이 들어갔다.
- 증거 — `evidence/kiosk_r1_audio_t5/prepared.json`·`qa_first.png` · `evidence/co2_r1_audio_t5/prepared.json`·`qa_first.png`
- 재현 — 2/2
- 근본 원인 — `chuckchuck/contracts.py:QA_TRACK_TRAPS = {"1": 0, "5": 1, "10": 3}` 를 `f08_questions._assign_traps` 가 그대로 씀.
- 수정안 — `"5": 0`, 비는 자리는 약점 근거가. 테스트·SCHEMA 갱신.
- 파일 — `chuckchuck/contracts.py` · 테스트 · `docs/SCHEMA.md`

### REC-08 · 중간 · 「모르겠어요」 사다리가 모순 질문에서 1단부터 답을 보이고 보기가 엉뚱
- 증상 — 1단: 반응 「40% 감소 쪽인가요, 60% 감소 쪽인가요?」 + 인용 상자 「…평균 농도가 **40%** 낮아졌습니다」, 보기 칩은 **「2배」「40%」**(2배는 6장 수, 60% 없음). 5분은 1단 반응이 「40% 낮아졌다고 보면 돼요」.
  2단 빈칸 옆에도 40% 인용 상자. 3단 해설 → 「이제 내 말로」 순서는 맞음.
- 증거 — `evidence/co2_r1_audio_t10/play_20260930_050604_q1_dunno/q1_dunno.md`·`_01_stuck.png`·`_02_stuck.png` · `evidence/co2_r1_audio_t5/play_20260930_051046_q1_dunno/q1_dunno.md`
- 재현 — 재현 2회
- 근본 원인 — `chuckchuck/f09_judge.py:_narrow_followup` 이 모순 질문을 모름: `mask_gist(… _distractor_pool(question, graph))` 가 개념의 다른 장 수를 오답으로, 되물음이 `evidence_quote`(= 답이 든 줄)를 통째로. `_scaffold_judgement` 도 같은 인용 상자.
- 수정안 — 모순 질문이면 보기 = (자료 값, 발표 값), 1~2단은 발표 인용 + 장만, 자료 줄은 해설에서만, 빈칸 단계 인용 상자 끔, 반응에 `_contra_leaks`.
- 파일 — `chuckchuck/f09_judge.py` · `demo/YEHS_demo/js/app.js`(인용 상자) · 테스트 · node 스모크

### REC-09 · 중간 · 까닭 있는 반박(「자료가 오타, 발표가 맞다」)에 「답으로는 조금 멀어요」, 되풀이하면 점수가 오른다
- 증상 — 1턴(출처를 든 반박) 35/39 + 「이산화탄소 농도에 대한 답으로는 조금 멀어요…」, 2턴 근거 없는 되풀이 **65(+30/+26)** 에 같은 문장. 질문에 정확히 맞는 답을 「멀다」 하고, 출처를 확인할 수 없다는 말도, 자료 5장 표(1,450→870 = 40%)가 60% 와 안 맞는다는 쓸모 있는 말도 없다.
- 증거 — `evidence/co2_r1_audio_t10/play_20260930_050551_q1_typo_claim/q1_typo_claim.md`·`_01~02_answer.png` · `evidence/co2_r1_audio_t5/play_20260930_051034_q1_typo_claim/q1_typo_claim.md`
- 재현 — 재현 2회
- 근본 원인 — `chuckchuck/f09_judge.py:_enforce_on_topic` 초점 대조가 자료·발표류를 `_GENERIC_TOKENS` 로 빼 모순 질문 답을 `focus_miss`(`_FOCUS_MISS_REACT`)로. 반박 길(`_judge_guard.absence_or_dispute`)이 모순 질문엔 없음.
- 수정안 — 모순 질문은 초점에 두 인용 낱말·수를 넣고 generic 제외를 끔. 반박엔 코드 반응(원본은 확인 불가 · 자료 안 교차 확인만), 되풀이로 점수 안 오르게.
- 파일 — `chuckchuck/f09_judge.py` · `chuckchuck/_judge_guard.py` · 테스트

### REC-10 · 중간 · 다른 발표 녹음(R3)인데 시간·말하기 측정이 리포트 첫머리에
- 증상 — 머리(「말 분석은 하지 않았어요」·겹침 5%·「D까지만」)는 바르지만 바로 아래 **「여기부터 보세요: 시간 관리 0/100 — 핵심(core)이 계획보다 63% 모자랐어요」**, 음성적 전달 64·언어적 명료성 79,
  팁 「1번은 핵심인데 권장 600초 중 220초만 썼어요」(다른 발표 전체가 1장 구간), 요약 「93자/분 … 너무 느렸어요」, 할 일 「말 속도를 … 빠르게 연습」, 강점 「말 속도가 일정해서…」(bunt).
  개념 17개 모두 「안 나옴」·「다시 볼 곳 17개」 인데 같은 화면이 「판정하지 않았어요」.
- 증거 — `evidence/co2_r3_audio_t10/play_20260930_051229_q1_report/99_report.png`·`turns.json` · `evidence/{co2,kiosk,bunt}_r3_audio_t10/pipeline_summary.json`
- 재현 — 3/3 R3 · 화면 렌더 1회
- 근본 원인 — 다른 발표면 말 **내용** 항목만 unmeasured. `chuckchuck/f17_pace.py`·`f14_rubric.py`/`_rubric_det.py`(속도·필러·휴지·제한시간·신호어)·`f19_report.py`(pace_summary·actions)는 녹음 시각을 그대로 쓰고, `app.js` 「여기부터 보세요」 는 녹음 신뢰를 안 본다.
- 수정안 — unrelated(basis skipped)면 녹음에서 재는 항목 전부 unmeasured, 시간 배분 생략, 리포트 속도·습관 문장 제거, 「여기부터 보세요」 는 녹음 다시 올리기 한 줄, 개념 칩 「판정 안 함」.
- 파일 — `f17_pace.py` · `f14_rubric.py` · `_rubric_det.py` · `f19_report.py` · `demo/YEHS_demo/js/app.js` · 테스트

### REC-11 · 중간 · 건너뛴 장 하나가 질문 2~3개를 먹고, 그 장에 함정까지
- 증상 — co2 10분 7문항 중 3개가 건너뛴 4장(Q4·Q6·Q7). kiosk 는 건너뛴 3장에 Q3 + **함정** Q5 「…= 140초」(Q3 가 이미 「110초」 를 말해 함정 답을 흘림). bunt 는 6장 같은 틀 두 번(Q5·Q7).
  대표 개념은 비중 순이라 식의 한 칸(「바람 속도」 0.76)이 식 머리(「환기량」 0.59)를 앞섰다.
- 증거 — `evidence/co2_r1_audio_t10/prepared.json` · `evidence/kiosk_r1_audio_t10/prepared.json`(Q3·Q5) · `evidence/bunt_r1_audio_t10/prepared.json`(Q5·Q7)
- 재현 — 2덱 + 같은 장 중복 1덱
- 근본 원인 — `f08_questions._skipped_core`(장마다 대표 하나만, 나머지 missing 그대로) · `_pick_marks`(같은 장·같은 틀 중복 규칙 없음) · `_assign_traps` 의 `avoid_slides` 가 모순 장만(건너뛴 장 없음).
- 수정안 — 건너뛴 장의 나머지 missing 은 대표 질문 골자로 접고, 같은 장 under_spoken·missing 두 번 금지, avoid_slides 에 건너뛴 장, 대표는 식 머리·장 제목 개념 우선.
- 파일 — `chuckchuck/f08_questions.py` · 테스트

### REC-12 · 중간 · 건너뛰는 말 사전이 좁다 — 「빼고」「제외하고」「다루지 않을게요」「안 볼게요」
- 증상 — bunt 7장 「예외인 경우는 오늘은 빼고 바로 결론으로 가겠습니다」 가 건너뛰기로 안 읽혀 skipped_slides 가 비고, LLM 정합은 **justified_skip(정당한 생략)** — 결함·상한 없음. (그 장은 support 0.3 이라 핵심 문턱에도 걸렸을 것.)
- 증거 — `evidence/bunt_r1_audio_t10/pipeline_summary.json` · `evidence/offline_probes.txt` §5
- 재현 — UI 1회 · 오프라인 결정적(4꼴)
- 근본 원인 — `chuckchuck/_spoken.py:_SKIP_INTENT_RE`·`_SKIP_CONNECT_RE`·`_SKIP_VERB_RE` 가 닫힌 동사 목록(건너뛰·생략·스킵·패스·넘어가·넘기).
- 수정안 — 빼·제외·다루지 않·안 보·설명 안 하 를 주제 표지(이 장·이 부분·…경우는·오늘은)와 함께일 때만 추가. 건너뛰기 말 장의 justified_skip 은 missing 으로.
- 파일 — `chuckchuck/_spoken.py` · `chuckchuck/_align_checks.py` · 테스트

### REC-13 · 중간 · 함정 전제가 수를 망가뜨린다 — 「0.71」→「71」, 「1.3배 높았다」→「0.8배 높았다」
- 증상 — bunt 함정 「자료에서 「**71** − 0.86 = −0.11점」라고 했는데…」 — 골자·해설이 쓰는 **사실 줄**까지 「71 − 0.86 = −0.15점」. 「강공은 번트보다 … **0.8배 높았습니다**」 — 말이 안 되는 전제.
- 증거 — `evidence/bunt_r1_audio_t10/prepared.json`(Q3·Q4) · `evidence/bunt_r2_audio_t10/prepared.json`(Q3·Q6) · `evidence/bunt_r3_audio_t10/prepared.json`(Q3) · `evidence/offline_probes.txt` §7
- 재현 — 「71」 2회 · 「0.8배 높았습니다」 3회 · 오프라인 결정적(`_clean("1.5배 늘었습니다")` → 「5배 늘었습니다」)
- 근본 원인 — `chuckchuck/_traps.py:_clean` 의 `_BULLET_RE` 가 줄 머리 소수의 「0.」「1.」 을 글머리 번호로 뗀다(premise·fact 둘 다 `_number_from_line` 에서 이 함수를 거침). 배수 바꾸기(`_wrong_value`)는 방향 낱말을 안 본다.
- 수정안 — 글머리 떼기는 「숫자. 」 뒤 공백·한글일 때만(소수 보존). 「N배 높/많/크」 는 1보다 큰 배수(또는 방향 반전)로만.
- 파일 — `chuckchuck/_traps.py` · 테스트

### REC-14 · 낮음 · 다른 발표 알림이 문헌 알림 뒤에 붙는다
- 증상 — R3 첫 말풍선 「문헌 검색 일부가 실패해서… 녹음이 이 자료와 다른 발표라서…」. 증거 `evidence/co2_r3_audio_t10/play_20260930_051229_q1_report/00_entry.png` · 재현 3/3 R3
- 원인 — `demo/YEHS_demo/js/app.js`(~L8212) 가 speech_note 를 notes 끝에 push. 수정 — 맨 앞(unshift). 파일 — `app.js` · `index.html ?v=`

### REC-15 · 낮음 · 리포트 문장이 잰 값과 반대 방향·내부 이름 노출
- 증상 — kiosk R1 「말 속도가 너무 빠르고」·「너무 빨라서(116자/분)」(권장 300~350 — 느림), bunt R3 「평균 자분 144.9, 평균 SPS 2.26」, co2 R3 「핵심(core)이」. 증거 `evidence/kiosk_r1_audio_t10/pipeline_summary.json` · `evidence/bunt_r3_audio_t10/pipeline_summary.json` · 각 1회
- 원인 — `chuckchuck/f19_report.py` 가 LLM 문장의 속도 방향을 F-17 판정과 안 맞춰 보고 필드 이름이 샘. `_rubric_det.py` 이유 문자열의 importance 라벨. 수정 — 방향 일치 검사·이름 치환. 파일 — `f19_report.py` · `_rubric_det.py`

### REC-16 · 낮음 · 개념 목록이 모순 개념을 「1번 슬라이드」 로 (모순은 5장)
- 증거 `evidence/co2_r1_audio_t10/play_20260930_050457_main/99_report.png` · 1회. 원인 — `app.js` 개념 목록이 `node.slide_nos[0]`. 수정 — contradiction 이면 `deck_slide_no`.

### REC-17 · 낮음 · 모순 질문 LLM 문장이 예/아니요 꼴(「…다른가요?」)로 통과, 인용이 「그리고」 로 시작
- 증거 `evidence/co2_r1_audio_t10/prepared.json`(Q1) · `evidence/bunt_r2_audio_t10/prepared.json`(Q1) · 각 1회. 원인 — `f08_questions._RECONCILE_RE`(「다른」 하나로 통과) · `_FILLER_HEAD_RE`(접속사 없음). 수정 — 답을 요구하는 꼴(어느 쪽·무엇이 맞·어떻게 다른)만, 인용 머리 접속사 떼기.

### REC-18 · 낮음 · 장 경계 추정이 문장 가운데를 자른다
- 증상 — bunt 「…과연 손해일까 | 이득일까가 오늘 주제예요」(R1·R2), R1 「…뺀 | 거예요.」 → 4장 구간이 비어 시간 배분에서 사라짐. kiosk 건너뛴 3장 질문의 speech_quote 가 2장 문장.
- 증거 `evidence/bunt_r1_audio_t10/pipeline_summary.json`(transcript_by_slide) · `evidence/bunt_r2_audio_t10/pipeline_summary.json` · `evidence/kiosk_r1_audio_t10/prepared.json`(Q3) · 정답 구간은 `truth.json` 의 `slide_segments_truth` · 재현 2회
- 원인 — `chuckchuck/f05_stt.py:split_by_slide` 가 안긴 물음 「-ㄹ까」 를 문장 끝으로(경계는 `f04_infer_marks.py`), `f08_questions._speech_quote` 가 건너뛴 장에 옆 장 문장. 수정 — 「-ㄹ까/-는지」 뒤 격조사·연속 물음은 안긴 절, 건너뛴 장 speech_quote 는 건너뛰기 말.

### REC-19 · 낮음 · 결과·리포트 화면을 열 때마다 객석(F-12) LLM 을 다시 부른다
- 증상 — 이 감사 LLM 230콜 중 101콜이 audience-chatter, 그중 약 55콜은 이미 분석한 세션의 결과·리포트 화면을 다시 열 때(브리지 로그 「client disconnected during /api/v1/chatter」 반복). 재현 — 렌더 때마다.
- 원인 — `demo/bridge.py` chatter 경로에 세션 캐시 없음, 화면이 렌더마다 요청(`chatter.js`·`app.js`). 수정 — 세션 id + 입력 해시로 단계 캐시(`_stage_cache_*`) 재사용.

### REC-20 · 낮음 · 자료에 없는 전제·측정 조건을 묻는 질문 (바른 녹음에서도)
- 증상 — co2 R2 Q3 「환기 면적이 '세 가지 요소' 중 **가장 중요한 변수로 설정된** 이유」(자료에 없는 전제), kiosk R2 Q4 「**선정 기준**」, Q7 「**측정 방법과 조건**」, kiosk R3 Q5 「실제 매장 환경과 일치하는지」.
- 증거 — `evidence/co2_r2_audio_t10/prepared.json` · `evidence/kiosk_r2_audio_t10/prepared.json` · `evidence/kiosk_r3_audio_t10/prepared.json` · 4문항 2덱
- 원인 — `f08_questions._normalize_questions` 의 전제·방법 검사(`method_unsupported`·`question_unanswerable`)가 최상급 전제·메타 물음을 못 봄. 수정 — 최상급 전제는 자료에 같은 말이 있을 때만, 방법·조건 물음은 자료에 방법 줄이 있을 때만 LLM 문장.

## 5. 잘 된 것

- **다른 발표 녹음(R3)** — 3/3 겹침 3~5% 로 알아봄. 질문 21개 모두 자료만(`speech_mismatch_deck_only`), 첫 질문 앞 알림, 정합 LLM 0콜, 객석은 LLM 없이 즉시, 리포트 머리 「녹음이 이 자료와 다른 발표라서 말 분석은 하지 않았어요」 + 겹침 + 「D까지만」, 채점 노트 정직. 자료만 질문의 좋은 답은 good/85.
- **확인된 모순(co2 N1) 질문 묶음** — 질문·이유·힌트 1단에 자료 값 없음, 빈칸 힌트 「…평균 농도가 ___ 낮아졌습니다」, 골자는 두 인용, 「꼭 넘어야 해요」 맨 앞(5분에서도). side_deck 첫 답 good/85 「60%에서 40%로 정정한 부분은 정확해요」.
- **「먼저 짚을 것」(co2 R1)** — 모순 두 인용, 건너뛴 장 원문 + 설명 안 한 개념, 「이 2가지 때문에 등급은 C+까지만」·「76점에서 낮췄어요」 — 잡힌 결함과 정확히 일치. 바른 co2·kiosk R2 는 블록 없이 B+.
- **건너뛴 장 이유 줄** — 발표자가 한 건너뛰는 말을 그대로 든다.
- **말로 읽은 수·꼴만 같은 주장에 오탐 없음** — 「사십 퍼센트」「두 배 반」「일 분 사 초」「삼십 퍼센트 더 높았던(=1.3배)」「열 명 중 아홉 명」「참여하신 72분」.
- **판정 LLM 은 답 속 뒤집은 비교·틀린 값을 잡는다** — bunt Q7 wrong/0, Q6 72% wrong/0, co2 Q5 전제 따른 설명 wrong/0 → 바로잡은 답 85. (그래서 REC-01 은 정합·질문·리포트 쪽 문제다.)
- **함정(10분)** — 전제를 받아들인 답은 wrong 35/0 + 「질문의 전제부터 확인해 보세요」, 바로잡은 답은 대부분 85(kiosk 1회 65).
- **딴 얘기·한 단어** — 칭찬 없이 wrong/0, 이어 85.
- 정합 근거 106개 중 104개는 녹음에 실제로 있는 문장, F-08 `speech_quote` 는 모두 원문 그대로.

## 6. 다음 수정 묶음 제안

| 묶음 | 포함 | 방향 | 손댈 곳 | 검증 |
|---|---|---|---|---|
| **A. 정합 대조 규칙**(먼저) | REC-01·02·03·06·12 · 04 의 로마자 단위 | 비교 세 칸, 지다·가다 활용, 전→후 짝, % 어림은 %p, 「N도 안 되는」=미만, 로마자 단위, 인용 문장별 검증, 건너뛰기 동사 확장 | `_deck_claims.py` · `_spoken.py` · `_align_checks.py` · `f11_align.py` | `tools/probe_rules.py` 전 케이스 기대대로(9/9 · 오탐 0) + 기존 테스트 |
| **B. F-09 모순 질문 판정** | REC-04·08·09 | 모순 가드(발표 값 고집 wrong, 반응 누설 금지, 닫는 말 장=evidence 장), 보기=(자료 값, 발표 값), 반박 코드 반응 | `f09_judge.py` · `_judge_guard.py` · `app.js` | `play_script.py` + `answers/audit_rec_co2_r1_*` 재생: side_speech 2턴 <70·3턴 ≥70, dunno 1단에 40% 없음 |
| **C. F-08 질문 꼴·배치** | REC-05·11·13·17·20 | `_skip_asked`, 건너뛴 장 질문 하나로 접기·그 장 함정 금지, `_clean` 소수 보존·배수 방향, 모순 물음 꼴 | `f08_questions.py` · `_traps.py` | 세 덱 R1 질문에서 건너뛴 장 질문이 템플릿 꼴·장마다 하나, 함정에 「71 −」「0.8배 높」 없음 |
| **D. 다른 발표 리포트** | REC-10·14 | unrelated 면 녹음 측정 전부 unmeasured, 「여기부터 보세요」·개념 칩, 알림 순서 | `f17_pace.py` · `f14_rubric.py` · `_rubric_det.py` · `f19_report.py` · `app.js` | R3 3벌 리포트에 속도·시간 문장 0 |
| **E. 트랙 정책** | REC-07 | `QA_TRACK_TRAPS["5"] = 0` | `contracts.py` · 테스트 · SCHEMA | 5분 함정 0 |
| **F. 문구·표시·비용** | REC-15·16·18·19 | 속도 방향·내부 이름, 모순 장 표시, 안긴 물음 경계, chatter 캐시 | `f19_report.py` · `app.js` · `f05_stt.py` · `bridge.py` | — |

**재현 도구** — 덱·녹음 `tools/build_audit_decks.py`(PPTX 는 `labs/qa_bench/corpus/build_pptx.py`) · 화면 `labs/qa_convo/run.py prepare --mode audio` + `tools/play_script.py` + `tools/reprepare_track.py` ·
규칙만 `tools/probe_rules.py`(LLM 0콜) · 증거 `tools/collect_evidence.py`. 덱 폴더는 `ppt/audit_<덱>_r<N>/`(PPTX + 「발표 녹음 전사.txt」, git 에 안 올라감)로 다시 만든다.
