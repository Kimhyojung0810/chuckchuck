# 논문을 근거로 묻는다 — F-24 문헌 + F-08 연동 + 자유 논문 검색 (2026-09-22 구현)

> 사용자 요청(9/22): ① QA 프롬프트에서 **논문을 긁어와** 그에 기반해 질문을 설계할 것 ② 사용자가 **자유롭게 묻는 주제**에도
> 수준 높은 논문·상위 자료를 바로 가져올 것 ③ 완성하면 **검증 루프**를 돌려 답이 제대로, 어긋나지 않게 나오는지 확인할 것.
> [audience-evidence-and-deck-consulting.plan.md](audience-evidence-and-deck-consulting.plan.md) §2-1 의 L1·L2 를 앞당긴 것이다.
> 상태: **서버 쪽 구현 완료 · 검증 루프 통과(§5)** — 09-23 에 통로 5개·병합·인용 재작성(qa-cite)까지. 화면은 Festa(10/1 잠금) 뒤.
> 09-22 밤 세션이 통로 5개 실측 도중 끊겼다(코드는 적용됐고 실측·검증·문서가 안 남았다). 09-23 에 이어서 마무리 — §5-2·§7.

## 0. 한 문장

**어떤 논문이 있는지는 코드와 검색 API 가 정하고, LLM 은 그 논문을 인용한 질문 문장만 쓴다.** 목록 밖 논문을 인용한 문장은
코드가 버린다. 그래서 "교수가 논문 근거로 묻는다" 를 **지어냄 0** 으로 만들 수 있다.

## 1. 무엇을 만들었나

| 조각 | 파일 | 역할 |
|---|---|---|
| 계약 | `contracts.py` `PaperRef`·`PaperDoc`·`PaperError` · `Question.paper_ids` · `QuestionDoc.papers` | SCHEMA §8-G·§8-E |
| 자료 인용 추출 (L1) | `_evidence.citation_lines()` · `find_citations()` | 「저자 (연도)」·「김철수 등(2021)」·REFERENCES 장·DOI 를 **정규식**으로. LLM 0 |
| 학술 검색 provider (L2) | `providers/scholar_base.py` · `scholar_impl.py` (`OpenAlexScholar`·`SemanticScholarScholar`·`ArxivScholar`·`CrossrefScholar`·`EuropePmcScholar`·`MultiScholar`·`NoScholar`·`get_scholar`) | 전부 무료·키 없음. `search()` 품질순(`rank_refs` 한 함수), `resolve()` DOI 우선 되찾기. 쉼표로 여러 개면 동시에 부르고 합친다 |
| F-24 모듈 | `f24_papers.py` `build_papers()` · `search_papers()` | 세션용 문헌 묶음 / 자유 질문 검색. 검색어 번역 LLM 1콜 |
| F-08 연동 | `f08_questions.py` `PAPER_SYSTEM_ADDENDUM` · 서가 블록(질문 대상 개념의 문헌만) · 개념별 「문헌 (d01) …」 줄 · `_ungrounded_citation` · `CITE_SYSTEM_PROMPT`(`[TASK] qa-cite`) | 인용은 목록 안에서만. 문헌이 붙었는데 인용이 없는 질문만 골라 **한 번** 고쳐 쓰게 한다 (§3) |
| 경로 | `demo/bridge.py` · `server/app.py` · `server/jobs.py` · `server/store.py PAPER_DOC` | `/api/v1/papers` · `/api/v1/papers/search` · questions 에 자동 연결(세션 캐시) |
| 벤치 | `examples/qa_eval.py --papers [--scholar openalex]` | 지표 `citation_grounded`(1.0 아니면 실패) · `paper_cited_questions` |
| 테스트 | `tests/test_papers.py`(37) · `tests/test_scholar_providers.py`(16) · `tests/test_papers_routes.py`(3) | 네트워크 없이. 회귀 전체 1,240 초록 (09-23) |
| 설정 | `.env.example` `SCHOLAR_PROVIDER=all` · `SCHOLAR_MAILTO` · `S2_API_KEY` · `SCHOLAR_TIMEOUT_SEC` | 코드 기본은 `none` — .env 로 켠다. `all` = openalex,arxiv,europepmc (+semanticscholar 는 키가 있을 때) |

## 2. 흐름

```
업로드 → SlideDoc ─┬─ citation_lines() ──────────────► deck 문헌 d01… (장 번호·node_ids 조인)
ConceptGraph ─────┤                                          │ resolve(DOI|제목) → DOI·초록 채움
                  └─ 상위 5개념 → [LLM] 영어 검색어 → OpenAlex search ×2편 ─► scholar 문헌 s01…
                                                                 (같은 논문은 합침)      │
                                                                                        ▼
F-08 build_questions(papers=PaperDoc)  ── 프롬프트: 「교수가 읽고 온 문헌」 서가 + 개념별 「문헌 (d01) ← 이 문헌을 근거로 물어라」
      └ 어댑터: 질문·why·hint·골자 속 「저자 (연도)」 ∉ 목록 → 그 문장 버리고 템플릿 · paper_ids 검증/추론 · QuestionDoc.papers
자유 질문 "IR 최신 논문?" → search_papers() ── [LLM] 영어 검색어 → OpenAlex → 품질순 PaperDoc (kind=scholar)
```

## 3. 결정과 이유

| 결정 | 이유 |
|---|---|
| OpenAlex 하나 (Semantic Scholar 는 provider 한 장 더 쓰면 됨) | 키 없음·무료·초록 제공·철회 필터. 외부 의존을 하나만 늘린다 |
| **초록은 원문을 300자로 자른 것.** LLM 요약 금지 | 논문 내용을 LLM 이 다시 쓰면 거기서 지어낸다 (기존 계획 §2-1 L2 위험) |
| 품질 = 검색어 낱말 겹침 0.5 + 관련도 0.2 + 피인용 0.2 + 최근성 0.1 | 09-22 실측: 관련도+피인용만 쓰면 "attention residue task switching" 1위가 AlphaFold(피인용 1.5만). 겹침을 넣자 Leroy(2018) 가 1위 |
| deck 되찾기는 DOI 우선, 제목은 `title.search` 필터 | `search=` 어간 검색은 Leroy(2009) 를 못 찾았고, `?` 가 든 제목엔 400 을 냈다 |
| 검색어 번역 응답은 id → label → 순서로 받는다 | Solar 가 예시의 `c1` 을 그대로 베껴 id 가 하나도 안 맞았다(1회차 검증). 검색어는 열쇠라 느슨해도 안전하다 |
| 인용 0 이면 전체 재요청이 아니라 **그 질문만 qa-cite 로 한 번** 고쳐 쓴다 (09-23) | 서가·문헌 줄·규칙을 다 실어도 첫 응답은 인용 0, 15k자 프롬프트를 나무라며 다시 물어도 0 (paper_ids 를 questions 바깥에 적었다). 긴 프롬프트에서 규칙은 묻힌다. 질문 하나 + 문헌 줄만 실은 3k자 과제로 바꾸자 2/3 → 3/3 (§5-2). 고쳐 쓴 문장도 어댑터가 다시 검사한다 |
| qa-cite 결과에서 «제목»·끝에 덧붙인 인용은 떼고, 200자 넘거나 해요체 물음으로 안 끝나면 원문을 지킨다 | 09-23 실측: 1회차는 질문 끝에 "Stothart et al. (2015) «제목»" 을 덧붙였고, 2회차는 초록을 옮겨 적은 세 문장(300자↑)을 내 QA_TEXT_MAX 에서 잘리며 끝맺음이 사라졌다(반말 2/3). 인용 하나 얻자고 화면 말투를 깨지 않는다 |
| 통로 5개, `all` 은 openalex+arxiv+europepmc | 분야가 다르다 — OpenAlex(전 분야·피인용), arXiv(최신 CS 프리프린트), Europe PMC(심리·의학). Crossref 는 검색 초록이 없어 되찾기용, Semantic Scholar 는 키 없이 3번째 요청부터 429 라 키가 있을 때만 |
| 순위는 통로가 몇 개든 `rank_refs` 하나 · 제목에 검색어 낱말 2개 이상, 아무도 보증하지 않은 논문(피인용 0·한 통로)은 하나만 빼고 전부 | 09-23 실측: 초록 겹침만 보면 단백질 결합 부위 논문(초록에 attention·residue·task)이 "attention residue task switching" 3위, 냉장 창고 IoT 알림 시스템이 "smartphone notification … concentration loss" 에 올랐다. 두 통로가 같이 찾으면 관련도 +0.15 |
| 같은 논문의 여러 판은 하나로 | Europe PMC 는 MED·PMC·PPR 판을 따로 내고(같은 DOI 3번), arXiv 판은 DOI 가 없다 — DOI 키와 제목 키 둘 다로 잇는다 |
| papers 가 없으면 프롬프트·시스템 프롬프트가 **글자까지 예전과 같다** (테스트로 고정) | Festa 데모 경로를 바꾸지 않는다. `SCHOLAR_PROVIDER=none` 이어도 deck 문헌은 실린다 |
| 문헌은 실패해도 질문 생성을 막지 않는다 (`note` 에 사유) | 있으면 좋은 재료지 필수가 아니다. 외부 API 가 죽어도 부스가 선다 |
| 화면은 안 만들었다 | 10/1 기능 잠금. 응답에 `paper_ids`·`papers`·`cite_key` 가 있어 카드 하나면 된다 |

## 4. 운영

- **켜기:** `.env` 에 `SCHOLAR_PROVIDER=all` (09-23 에 넣어 둠 — **브리지를 다시 띄워야 읽는다**). 하나만 쓰려면 `openalex`. `SCHOLAR_MAILTO=팀메일` 을 넣으면 polite pool, `S2_API_KEY` 가 있으면 all 에 Semantic Scholar 가 낀다.
- **비용:** 질문 생성당 LLM +1콜(검색어 번역, 한글 개념일 때만) +1콜(qa-cite, 인용 없는 질문이 있을 때만 · ~3k자 · 3초) + 검색 API ≤10 요청 × 통로 수(세션에 한 번, 캐시). 실측 문헌 만들기 4.6초(openalex) · 8.3초(all).
- **끄기:** 요청 본문 `"papers": false`, 또는 `SCHOLAR_PROVIDER=none`(deck 만).
- **통로 실측(09-23, 검색어 3개 × 3편):** openalex 1.6~2.0초 · semanticscholar 0.9~1.3초(키 없이 3번째부터 429) · arxiv 0.3~0.6초 · crossref 1.4~1.9초(초록 없음) · europepmc 2~10초. 한 통로가 죽어도 나머지로 간다.
- **자유 검색:** `POST /api/v1/papers/search {"query": "IR에서 dense retrieval 최신 논문", "limit": 8}`.
- **벤치:** `SCHOLAR_PROVIDER=openalex python examples/qa_eval.py --papers --tag papers` → `exports/qa_eval/`. `citation_grounded` 가 1.0 이 아니면 어댑터 버그다.

## 5. 검증 루프 (live_qa_run 픽스처 · solar-pro3 · 5분 트랙)

숫자는 `exports/qa_eval/20260923-*.json` 에 있다. `citation_grounded` 는 전 회차 1.0 — 어댑터가 목록 밖 인용을 버린다는 보증은 지켜졌다.

### 5-1. 09-22 (끊긴 세션까지) — 논문은 왔지만 질문이 인용하지 않았다

| 태그 | 논문 인용 질문 | 인용 실재율 | 특이도 | 근거 인용률 | 골자→통과 | qa-questions 프롬프트 | 잡음 |
|---|---|---|---|---|---|---|---|
| baseline (문헌 없음) | – | – | 4.0 | 0.40 | 3/3 | 8,213자 | 2% |
| papers (openalex, 1회차) | **0/3** | 1.0 | 3.33 | 0.39 | 2/3 | 9,762자 | 10% |
| papers2 (검색어 id 수정 뒤) | **0/3** | 1.0 | 2.67 | 0.62 | 3/3 | 15,323자 | 32% |

서가 15개(초록 300자)를 다 실으니 프롬프트가 15k자·잡음 32% 가 됐고, 모델은 `paper_ids` 를 questions 바깥에 한 줄로 적었다.
전체 프롬프트를 나무라는 재요청(`PAPER_RETRY_NUDGE`)도 0. → 서가는 질문 대상 개념의 문헌만·초록 200자, 인용은 qa-cite 로.

### 5-2. 09-23 (qa-cite · 통로 병합 뒤)

| 태그 | 논문 인용 질문 | 인용 실재율 | 특이도 | 근거 인용률 | 반말 | 골자→통과 | 함정정정→통과 | qa-questions | qa-cite |
|---|---|---|---|---|---|---|---|---|---|
| papers3 (openalex) | **2/3** | 1.0 | 7.67 | 0.63 | 1/3 | 3/3 | 0/1 | 10,579자 · 14% | 2,956자 · 3.3s |
| papers4-all (openalex+arxiv+europepmc) | **3/3** | 1.0 | 11.67 | 0.39 | 2/3 | 3/3 | 1/1 | 11,514자 · 19% | 3,811자 · 3.5s |
| papers5-all (가드 뒤) | **3/3** | 1.0 | 7.67 | 0.50 | **0/3** | 2/3 | 1/1 | 10,090자 · 12% | 2,535자 · 2.9s |

papers3 의 반말 1 은 qa-cite 가 질문 끝에 «제목» 을 덧붙인 것, papers4 의 반말 2 는 초록을 옮겨 적은 세 문장이 200자에서 잘린 것 —
둘 다 코드 가드(§3)를 넣고 papers5 로 재검증 → 반말 0·높임 0, 세 질문이 모두 "…라고 봤는데, 발표의 …는 …인가요?" 꼴로 문헌을 전제로 묻는다. 특이도가 오른 것은 인용 표시가 자료 고유 낱말로 세어진 몫이 있다 — 표본 1건이라 방향만 본다.

## 6. 남은 것

- 화면: 질문 카드 옆 「이 논문을 보고 묻는 질문이에요」 칩(`cite_key`·`url`) · 자유 검색 입력 하나. Festa 뒤.
- ~~Semantic Scholar provider~~ 09-23 에 넣음. 키(`S2_API_KEY`, 무료 신청)를 받아야 `all` 에 낀다.
- 브리지(8799·8801)는 옛 코드로 떠 있다 — 다시 띄우고(`DEMO_PORT=8799 ./demo/run_bridge_midm.sh`) 예열해야 `SCHOLAR_PROVIDER=all` 과 qa-cite 가 산다.
- 첫 응답에서 높임(`인용하셨는데`)이 1건 나왔다(papers4 q01) — F-08 의 기존 높임 가드 범위 확인.
- 자료가 한글 참고문헌만 있는 경우의 되찾기(OpenAlex 한글 제목 검색 품질) — 팀 자료로 실측 필요.
- 표본 1건. 번들이 늘면(0-2) `qa_eval_compare` 로 baseline 대비 특이도·인용률 비교.

## 7. 09-22 세션이 끊긴 자리 (기록)

09-22 23:42 KST 에 시작한 세션은 통로 5개 클래스·`MultiScholar`·`PaperRef.source` 편집까지 적용한 뒤 00:13 에
5개 통로 × 검색어 3개 실측 스크립트를 띄운 채 끊겼다. 남은 것은 (1) 그 실측 (2) 실측이 드러낼 결함 수정 (3) 테스트·문서·커밋이었다.
09-23 에 실측을 다시 돌려 찾은 결함: OpenAlex 결과에 `source` 가 비어 있던 것 · S2 429 · Europe PMC 같은 논문 3번 ·
arXiv `+AND+` 가 `%2B` 로 인코딩돼 AND 가 안 먹던 것 · 병합 때 DOI 를 채워도 url 이 arXiv 링크로 남던 것 · 제목에 검색어가
없는 논문이 초록 겹침만으로 오르던 것. 전부 `tests/test_scholar_providers.py` 로 고정했다.
