# 2026-09-28 QA 지엽성 원인분석 — 자료

본문은 [`../2026-09-28_QA_지엽성_원인분석.md`](../2026-09-28_QA_지엽성_원인분석.md). 스크립트는 **저장소 루트에서** `.venv/bin/python docs/review/2026-09-28_QA_지엽성_자료/<이름>.py` 로 돈다 (실 LLM 과금 표시한 것 주의).

## 스크립트
| 파일 | 하는 일 | 문서 절 | 과금 |
|---|---|---|---|
| `dumpgraph.py` | 그래프 JSON 을 weight·깊이·자식 수로 덤프 | §1 | 없음 |
| `rerun_f07.py` | F-07 을 다시 돌리며 루트 클램프 직전을 가로챈다 | §1-5 | Solar |
| `verify_fix.py` | 수면 PPTX 파싱 → F-07 → F-08 끝까지 (인자 = 태그) | §5·§6 | Upstage+Solar |
| `thesis_eval.py` | 주제가 루트인가·요소가 주제 밑인가 (수면·form 덱 ×N) | §6 | Solar |
| `variance_eval.py` | F-06 을 얼리고 F-07 만 N번 — 노드 수 흔들림 | §7-3 | Solar |
| `wording_eval.py` | 3인칭·순서 질문 세기 | §7-2 | Solar |
| `paper_diag.py` | 문헌 경로 — 인용 수·재사용·대체 문구 (인자: 작업 폴더·횟수·태그) | §9 | Solar+검색 |
| `render_graph_png.py` | 그래프 JSON → PNG (좌→우 나무, 위계 실선·relates 점선) | 부록 | 없음 |
| `render_network_png.py` | 그래프 JSON → PNG (네트워크 배치, 위계와 같은 쌍의 relates 는 뺀다) | 부록 | 없음 |
| `make_transcript.py` | 클로바 전사 + 대본 docx → 슬라이드별 Transcript | §10 | 없음 |
| `audio_path_eval.py` | 녹음 경로 끝까지 (정합·흐름·pace·문헌·질문 1/5/10분) | §10·§11 | Solar+검색 |

## 입력 (얼린 것)
| 파일 | 무엇 |
|---|---|
| `concepts_0926_수면.json` | 수면 덱 F-06 결과 (9/26 stage_cache 사본) |
| `concepts_form2장.json` | 척척발표 소개 2장 F-06 결과 |
| `concepts_알림12장.json` | 벤치 fixture(알림 12장) F-06 결과 |
| `slidedoc_수면.json` · `slidedoc_수면_세션.json` | 수면 덱 파싱본 — **로컬에만** (덱 본문). `verify_fix.py` 가 첫 실행 때 만든다 |

## 결과
| 파일 | 무엇 |
|---|---|
| `graph_0926_수면_slidedoc있음.json` | 수정 전 — 9/26 화면에 쓰인 그래프 (주제가 잎 밑) |
| `graph_rerun1·2.json` | §1-5 F-07 재실행 (slide_doc 없음) |
| `graph_fixed_a·b·c.json` | §5·§6 수정 후 그래프 |
| `graph_after_screen_0928.json` | 수정 후 — 9/28 화면 실행 수면 그래프 (stage_cache 사본) |
| `graph_before_0926.png` · `graph_after_c.png` · `graph_after_screen_0928.png` | 수정 전·후 원본 그래프 그림 (트리 뷰) |
| `network_before_0926.png` · `network_after_screen_0928.png` | 같은 그래프의 네트워크 뷰 |
| `graph_after_links_0929.json` · `graph_after_links_0929.png` · `network_after_links_0929.png` | §12 가지 간 연결 보강 뒤 그래프 (트리·네트워크 뷰) |
| `audio_path_before_5c345e5.json` · `audio_path_after_a149349.json` · `audio_path_after_pace.json` | §10·§11 녹음 경로 전후 |

`transcript_*.json`·`slidedoc_*.json` 은 **올리지 않는다** — 발표자 음성 전문·덱 본문이다 (.gitignore 2026-08-08·09-10 규칙). 전사는 `make_transcript.py`(ppt/수면발표 의 .txt·.docx), 파싱본은 `verify_fix.py` 로 다시 만든다.
