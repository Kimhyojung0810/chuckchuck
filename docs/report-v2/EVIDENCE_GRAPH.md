# Report 2.0 — Evidence Graph

> 구현: [`main/web/js/report_graph.js`](../../main/web/js/report_graph.js) (순수 함수, 스키마 `reg/1`) · 시험: [`etc/tests/js/report_graph.smoke.mjs`](../../etc/tests/js/report_graph.smoke.mjs)
> 이 문서는 코드와 같아야 한다 — 다르면 코드가 맞고 문서를 고친다.

## 1. 무엇이고 무엇이 아닌가
- 분석 결과 · 슬라이드 · 발언 · 청중 대사 · Q&A · 코칭을 **타입 있는 노드 · 엣지**로 잇는 브라우저 안 인메모리 구조다.
- **화면에 그리지 않는다.** 화면은 `buildViewModel()` 이 내는 뷰모델(인사이트 · 근거 사슬 · 구간)만 읽는다.
- **새 판정을 만들지 않는다.** 판정 · 점수 · 문장은 원래 산출물에서 온다. 그래프는 잇고 · 고르고 · 검사만 한다.
- 별도 그래프 DB 없음 (D-003). 리포트 하나 = 노드 ~160 · 엣지 ~280 (실측).

## 2. 데이터 흐름
```
원천                         정규화(그래프 빌더)            평가 · 근거 연결                 뷰모델            화면
transcript.words/marks  ──▶ Utterance(U*) · TimeSpan(T*)
slide_doc / deck.slides ──▶ Slide(S*)
concept_graph           ──▶ Concept(C:*)
alignment_doc.items     ──▶ Assessment(A:align:*) ──SUPPORTED_BY──▶ Evidence(V:said/V:deck) ──POINTS_TO──▶ U*/S*
rubric_score            ──▶ Criterion(K:*) · Assessment(A:rubric:*)
pace_doc · flow_diff · habit_doc ─────────────────────────▶ Evidence(V:pace/flow/habit)
chatter_doc             ──▶ Evaluator(E:*) · Remark(R*) (+ 근거 검사)
question_doc · qa.live  ──▶ Question · Answer · FollowUp
                              └──▶ Insight(I:*) ─ ADDRESSES ◀ CoachingAction(CA:*) ◀ REHEARSES ─ PracticeTarget(PR:*)
                                                                                    └──▶ buildViewModel ──▶ 5개 화면
```

## 3. 노드 (실제로 만드는 것만)
모든 노드: `id · type · reportId · schema('reg/1') · source{type, id} · status · anchor{slide_no?, start_sec?, end_sec?, utt_ids?, quote?}`

| 타입 | id | 원천 (source.type) | 주요 필드 |
|---|---|---|---|
| Presentation | `P` | session | title, duration_sec, total_slides |
| Slide | `S{n}` | slide_doc | slide_no, title |
| TimeSpan | `T{n}.{visit}` | transcript.marks | anchor 시작 · 끝, `estimated`(올린 녹음이면 추정 → status inferred) |
| Utterance | `U{k}` | transcript.words | text, anchor — **서버에 발화 id 가 없어 빌더가 만든다**: 문장 끝(`니다 · 어요 · 요.` 등) · 0.6초 넘는 쉼 · 12초 상한으로 단어를 묶음 |
| Concept | `C:{node_id}` | concept_graph | label, kind(thesis · claim · concept), weight, slide_nos |
| Criterion | `K:{cluster}` | rubric_score.clusters | name, weight, average, scored |
| Assessment | `A:align:{node}` · `A:rubric:{no}` | alignment_doc.items · rubric_score.items | verdict · ui_status(ok/no/ct/om/na) · decided_by · score · method |
| Evaluator | `E:engine` · `E:{midm,solar,exaone,ax}` | pipeline · chatter_doc | 엔진 = 분석 파이프라인, 넷 = **청중**(role audience, lane = 코드가 정한 역할, absent) |
| Remark | `R{i}` | chatter_doc.turns | speaker, text, mood, named(대사 속 '…' 이름), ghost(그래프 · 받아쓰기에 없는 이름) |
| Evidence | `V:said:*` · `V:deck:*` · `V:pace:*` · `V:flow:*` · `V:habit:*` | 각 산출물 필드 | kind(said · deck · time), text, anchor |
| Question | `Q:{id}` | question_doc | text, label, gist(기대 답) |
| Answer | `A:qa:{qid}:{k}` | qa.results.trail | claim(답 원문 구절), text(마지막 답만), verdict |
| FollowUp | `F:{qid}:{k}` | qa.results.trail | text |
| Insight | `I:{kind}:{key}` | 아래 §5 | title, polarity(issue · strength · unknown), criterion, impact · evidence · actionability(등급), conflict |
| CoachingAction | `CA:{insight}:{k}` | question_doc.answer_gist · alignment deck_quote · pace_doc | kind(explain · time), text, basis(어디서 온 문장인가) |
| PracticeTarget | `PR:{kind}:{target}` | route | kind(qa · slide), route, available |

**안 만드는 것:** 연습 결과(PracticeAttempt) — 지금 재연습 결과를 인사이트에 잇는 저장이 없다(AUDIT §4). PracticeTarget(갈 곳)까지만 만들고 시도 기록은 Phase 3 후보.

## 4. 엣지
모든 엣지: `id('{type}:{from}>{to}') · type · from · to · source · status`

| 타입 | from → to | 비고 |
|---|---|---|
| CONTAINS | P → S · S → C | 개념은 `slide_nos` 로만 장에 붙는다 (줄 id 없음) |
| SPANS | T → S | |
| OCCURS_IN | U → T | 장 구간이 추정이면 inferred |
| SCORES | A:rubric → K | |
| PRODUCED_BY | A · R → E | |
| ASSESSES | A:align → C | |
| SUPPORTED_BY | A · I → V (· A:rubric) | |
| POINTS_TO | V → U · S | 인용을 **원문에서 찾았을 때만** U 로(supported). 시각만 있으면 겹치는 U 로 inferred |
| REFERENCES | R · Q → C · S | 청중 `refs` 는 supported, 대사 속 이름으로만 이으면 inferred |
| RESPONDS_TO | A:qa → Q · F | |
| GROUNDED_IN | F → A:qa | 꼬리질문이 앞 답의 claim 에서 나옴 (claim 이 없으면 missing) |
| TARGETS | I → C · S · K | |
| ADDRESSES | CA → I | |
| REHEARSES | PR → CA | |

## 5. 인사이트 (원래 산출물에서만)
| 종류 | 언제 | 근거 |
|---|---|---|
| `I:concept:*` | alignment `missing` · `contradiction` (대체값 아님) | V:said(말한 구절) · V:deck(자료 구절). 판정이 missing 인데 note 가 「설명했…」 면 **conflicting** + `conflict` 문구 |
| `I:unjudged:*` | alignment `decided_by: fallback` 또는 녹음 무관 | 없음 → status missing, polarity unknown (「판정하지 못했어요」) |
| `I:good:*` | 무게 큰 aligned 중 말한 구절이 원문에 있는 것 2개 | V:said |
| `I:pace:*` | pace 장 상태가 ok/fit 아님. 같은 쪽 둘 이상이면 하나(`short` · `long`)로 묶음 | V:pace(장 구간 시각) |
| `I:flow:*` | flow issues (`good_link` 는 strength) | V:flow(cue 인용) |
| `I:fault:*` | rubric `faults` | — (텍스트만) |
| `I:habit` | habits spans 있을 때 (4개 이상이면 issue) | V:habit(구간 시각) |
| `I:cluster:*` | 채점 묶음 평균 < 70 (시간은 I:pace 가 있으면 생략) | 그 묶음의 70점 미만 항목 글(위치 없음) |

### 5-1. 순위 — 숫자를 지어내지 않는다
`rank = [impact, evidence, actionability]` 를 등급(high 3 · mid 2 · low 1 · none 0)으로 사전순 정렬.
- impact: 개념 = thesis 또는 무게 ≥ 0.85 → high, ≥ 0.6 → mid / 시간 = core 장 포함 → high / 채점 묶음 = 가중 ≥ 15 → high
- evidence: 원문 인용 · 시각 앵커 → high, 장만 → mid, 위치 없는 글 → low, 없음 → none(→ status missing)
- actionability: 제안 문장 + 연습 갈 곳 → high, 하나만 → mid

## 6. 상태
`supported`(원천에서 확인) · `inferred`(겹치는 시각 · 이름으로만 이음) · `missing`(근거 · 판정 없음) · `conflicting`(근거끼리 어긋남) · `unsupported`(근거 없는 주장 — 청중 대사).
청중 대사 검사(`addAudience`):
1. 대사 속 '…' 이름이 그래프 라벨에도 받아쓰기에도 없음 → **unsupported** (실측: 쏠라 「Model Architecture」)
2. 「안 나왔다/언급이 없다/빠졌다」 + 그 개념이 정합 `aligned` → **conflicting** (실측: 엑씨 「평점 인플레이션」 — 낱말은 0회, 뜻은 설명함)
3. refs 나 이름이 확인됨 → supported, 아무 근거도 못 찾음 → inferred
4. 결석 삐약이의 대체 대사 → missing (근거로 쓰지 않음)

## 7. 검증 (`validate`)
끊긴 엣지 · 중복 엣지 · 출처 없는 노드/엣지 · 장 범위 밖 · 시각 범위 밖(길이 +0.5초) · 원문에 없는 말한 구절 · 근거 없는 인사이트 · 근거 없는 청중 대사를 `issues` 로 낸다.
지표: `evidencePathRate`(인사이트 중 Insight → Evidence → U/S/T 길이 있는 비율) · `anchoredRate`(원문 · 시각 앵커까지 있는 비율).

**실측 (rec_v2, 2026-10-15):** 노드 161 · 엣지 280 · 인사이트 8 · evidencePathRate 0.75 · anchoredRate 0.75. issues = `unsupported_remark R1`(쏠라) · `insight_without_evidence I:unjudged:4-7eun…`(thesis 대체값). 끊긴 엣지 0 · 범위 밖 0 · 원문에 없는 인용 0.

## 8. 실제 경로 예 (rec_v2)
```
I:concept:gaseol-a 「가설 A」 를 말로 전하지 못했어요   status conflicting · rank [mid, high, high]
  └ SUPPORTED_BY V:said:gaseol-a  46.1–51.0s  "매장 품질이 실제로 좋아졌다. 이건 기각됐습니다"
       └ POINTS_TO U8 (44.7–48.4s, 2장) · U9 (49.0–51.0s, 2장 "이건 기각됐습니다")
  └ ADDRESSES ◀ CA:concept:gaseol-a:1 "같은 기간 재주문율은 +0.6%p로 사실상 변화가 없었으며 … 기각"  (근거: 질문 생성 기대 답 · 2장)
       └ REHEARSES ◀ PR:qa:q01-gaseol-a  #/rehearsal/qa 「이 개념 질문 다시 받기」
```
→ 판정은 「빠뜨림」인데 근거 글(note)은 「설명했으나 기각되어 생략 가능」 — 화면은 이걸 숨기지 않고 「판정을 그대로 믿기 어려워요」로 보인다.

## 9. 화면 간 맥락 계약 (cross-screen)
주소 해시 하나로 고정: `#/{screen}?i={insightId}&s={slideNo}&t={startSec}-{endSec}`
- screen ∈ `reveal · audience · replay · coach · practice`
- 화면을 바꿔도 `i · s · t` 를 그대로 넘긴다. 뒤로 가기 = 브라우저 기록, 새로고침 = 같은 해시로 다시 그림(그래프는 같은 입력에서 같은 id 가 나온다 — id 가 원천 키에서 오므로 결정적).
- 없는 id 가 오면 첫 이슈로 떨어지고 「찾는 항목이 이 리포트에 없어요」를 한 줄 보인다.
