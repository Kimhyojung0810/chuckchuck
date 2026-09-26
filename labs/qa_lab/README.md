# QA 실험대 (`labs/qa_lab`)

부스 Q&A 의 **질문 생성(F-08)·판정(F-09)만** 골라 되돌려 보는 자리다. 브라우저도 카메라도 없다.

`labs/qa_call` 은 통화 화면까지 통째로 찍지만 한 바퀴 40초에 파싱·개념·그래프까지 매번 과금하고 답은 한 문장 고정이다.
여기서는 자료 한 벌을 **묶음(bundle)** 으로 한 번 얼려 두고, 그 위에서 질문만 다시 만들거나(호출 2~4) 판정만 여러 답으로 돌린다(답마다 호출 1).
실 LLM 을 부른다 — `.env` 필요, 과금. mock 은 쓰지 않는다 (CLAUDE.md §2).

## 흐름

```bash
# 1. 얼리기 — 부스에서 방금 쓴 세션(보관소 slide_doc)에서. 개념·그래프 호출 2번.
.venv/bin/python labs/qa_lab/run.py snapshot --name form --session 20260926T045837Z_023af58a
#    또는 사진으로, 부스와 같은 /api/v1/parse 경로를 타서
.venv/bin/python labs/qa_lab/run.py snapshot --name form --photos labs/qa_call/fixture_slide1.jpg labs/qa_call/fixture_slide2.jpg --bridge http://127.0.0.1:8799

# 2. 질문 — 문헌(F-24)·1차 심사(triage)는 묶음에 캐시된다. 프롬프트를 고친 뒤엔 이것만 다시.
.venv/bin/python labs/qa_lab/run.py questions --bundle form            # --track 1|5|10 · --no-papers · --fresh-triage · --fresh-papers

# 3. 판정 — 질문마다 「골자 그대로 → pass · 무관한 답 → wrong · (함정이면) 전제 동의 → wrong · 모르겠어요 → coach」
.venv/bin/python labs/qa_lab/run.py judge --bundle form --probe
.venv/bin/python labs/qa_lab/run.py judge --bundle form --q 1 --answer "1차 답" --answer "2차 답"   # 되묻기 라운드
.venv/bin/python labs/qa_lab/run.py judge --bundle form --answers answers.json

# 4. 실제값인가 — 샘플 자료·mock 모델·자료에 없는 인용문·전부 폴백을 잡는다
.venv/bin/python labs/qa_lab/run.py check --bundle form
.venv/bin/python labs/qa_lab/run.py show --bundle form · list
```

`--bridge http://127.0.0.1:8799` 를 주면 떠 있는 브리지의 HTTP 경로(부스 화면과 **같은 body**)로 보낸다 — 브리지 코드까지 포함해서 보고 싶을 때.
없으면 `chuckchuck` 모듈을 직접 부른다 — 프롬프트·가드를 고치고 브리지 재시작 없이 바로 볼 때. 둘의 결과가 다르면 브리지가 옛 코드다.

`answers.json` 은 `[{"q": 1, "name": "이름", "answers": ["1차", "2차"], "give_up": false, "expect": "pass|wrong|coach|partial"}]`.

## 표식

질문마다 · 판정마다 한 줄 표식이 붙는다. `!` 가 붙은 것은 **화면에 그대로 나가면 안 되는 것**이다.

| 표식 | 뜻 | 어디서 막아야 하나 |
|---|---|---|
| `잘림!` | 200자(`QA_TEXT_MAX`)에서 잘려 `…` 로 끝난다 — 물음이 사라졌다 (09-24 모바일 실측) | f08 `_normalize_questions` |
| `반말끝!` | 해요체 물음으로 끝나지 않는다 | f08 `_polite_question` |
| `높임N!` | 하셨·하신·말씀·께 … (CLAUDE.md §3-1) | f08 `_plain_speech` · f09 `_HONORIFIC_RE` |
| `인용주장!` | 검색 문헌(scholar)을 「인용했는데」 라고 발표자에게 씌웠다 — 거짓 전제 | f08 `_drop_cite_claim` |
| `합쇼체N` | ~습니다·~입니다·~ㅂ니다 (해요체 규칙) — 코드가 푸는데 남은 것 | `_speech.to_haeyo` (표에 없는 어간) |
| `노드id노출` | 라벨 대신 `concept-graph` 같은 id 가 문장에 나왔다 (09-26 실측) | f08 `_unslug` |
| `자료밖숫자!` | 골자·질문의 숫자가 자료·발화·문헌 어디에도 없다 (09-26 실측 70~80%·15%) | f08 `_number_sources` + `_speech.ungrounded_numbers` |
| `폴백` · `함정` · `인용N` · `인용문없음` | 정보 | — |
| `가드:무관` · `가드:함정동의` · `가드:질문벗어남` | f09 코드 가드가 등급을 뒤집었다 (무관→wrong · 함정 동의→wrong · 이 질문만 벗어남→통과 못 하는 partial) | 정상 동작 |
| `react폴백` | LLM react 가 비었거나 높임이라 코드 문구로 대체됐다 | 정보 |
| `코칭:단계` · `되묻기잘림!` | 포기 코칭 단계 · followup 이 잘렸다 | — |

`judge --probe` 는 기대와 다른 판정 수를 종료 코드로 돌려준다(0 이면 전부 기대대로). `check` 는 FAIL 이 있으면 1.

## 묶음 안

`labs/qa_lab/out/bundles/<name>/` (git 무시): `meta.json`(출처·세션·모델) · `slide_doc.json` · `concept_doc.json` · `graph.json` · `papers.json` · `triage.json` · `question_doc.json` · `judgements/<시각>_probe|answers.json`.

부스 세션은 동의가 없어 보관소에 `slide_doc` 만 24시간 남는다 — 그래서 여기 묶음으로 얼려 둔다. `--bridge` 로 질문을 만들 때 그 세션이 이미 지워졌으면 브리지는 자료 본문 없이 만든다(`본문=-`, 브리지 로그).

## 못 보는 것

말풍선·펼치기·자막·카메라·마이크·TTS — 화면은 `labs/qa_call`, 마이크·소리는 부스 컴퓨터 리허설 몫이다.
알림·기억(F-25)은 동의 세션에만 있어 여기서는 끈 채로 돈다(부스 플로우와 같다).
