# 부스 체험 — 지금 보는 화면을 담아 바로 질문 받기 (2026-09-16)

> 사용자 요청(9/15): "Q&A 과정에서 vision 으로 우리 화면을 보여 주면서, 스크린에 QA 내용을 띄워서
> 직접 해볼 수 있게 하는 체험형" — 부스 방문객이 PDF 업로드·녹음 없이 자기 화면으로 질문을 받는다.
> 상태: **구현 완료 · 실 API 실측 완료 (아래 §4)**. 화면은 `booth.html` 별도 페이지 — `app.js` 는 손대지 않았다.

## 0. 한 문장

**캡처 한 장 = 슬라이드 한 장.** 화면 캡처를 Upstage Document Parse 에 이미지로 넣으면 1페이지 SlideDoc 이 되고,
여러 장은 `merge_slidedocs` 로 한 자료가 되어 F-06 → F-07 → F-08 → F-09 가 **그대로** 돈다. 새 vision 모델은 없다.

## 1. 왜 별도 페이지인가

- 앱의 `#/qa` 는 `pipelineQaReady()` 가 graph·alignment·flow 셋을 요구한다. 발화 없는 체험은 alignment·flow 가 없다.
- 헌장 §0 "Festa 전 프론트 새 화면 금지" 는 `app.js` 가 깨질 위험 때문이다. `booth.html` + `js/booth.js` + `css/booth.css` 는
  `app.js`·`index.html` 을 한 줄도 건드리지 않고, API 클라이언트(`chuckchuck_bridge.js`)만 import 해서 요청 본문 계약을 앱과 같게 맞춘다.
- 별도 저장소·상위 폴더는 **아니다.** 브리지·contracts·`.env`·세션 보관소를 그대로 써야 하므로 저장소 안에 둔다.

## 2. 흐름

| 단계 | 어디 | 무엇 |
|---|---|---|
| 담기 | `booth.js startShare/grabFrame` | `getDisplayMedia` 로 창 공유 → 한 프레임을 PNG(긴 변 1600px)로. 최대 8장. 스크린샷 파일 업로드도 같은 길 |
| 파싱 | `bridge._handle_parse` · `_multipart_files` | 파일 파트를 **전부** 모은다(예전엔 첫 파트에서 멈춤). PNG/JPEG 매직바이트로 판별. 여러 장은 이미지끼리만 |
| 합치기 | `f01_parse.merge_slidedocs` | 캡처는 전부 slide_no=1 → 올린 순서대로 다시 번호 |
| 개념·그래프·질문 | 기존 F-06/07/08 | transcript·alignment·flow 없이 호출. 브리지는 graph 만 필수 |
| 판정 | 기존 F-09 | `judgeQaAnswer` 그대로. history 는 한글 키 QaTurn 계약 |
| 작은 창 | `booth.js openPip` | Document Picture-in-Picture (Chrome 116+) 로 질문 카드만 항상 위에 띄운다 — 발표 화면 위에 "띄운다"에 가장 가깝다 |

미리보기 PDF 는 이미지에 없다 (PNG 를 preview.pdf 로 두면 pdf.js 가 죽는다). 동의한 세션은 `original.png` + `original_2.png…` 로 전 장을 남긴다.

## 3. 규율

- 진행 시간은 실측만 보여 준다 (UI_REDESIGN §14). 분석이 실패하면 실패 문구를 그대로 보여 준다 — 샘플로 위장하지 않는다.
- 해요체 · 왼쪽 버튼 「닫기」계열 · CTA 만 보고 다음 행동 예측 (CLAUDE.md §3-1).
- 판정 색 5종은 app.css 토큰을 그대로 쓴다.

## 4. 실측 (2026-09-16 · Solar · 텍스트 많은 스크린샷 2장 · 브리지 8801)

| 단계 | 초 |
|---|---|
| 파싱(이미지 2장, Upstage 2콜) | 5.2 |
| 개념(F-06) | 2.9 |
| 그래프(F-07) | 9.8 |
| 질문(F-08, 트랙 5 → 3문) | 13.3 |
| **질문까지 합계** | **31.2** |
| 판정(F-09) | 2.9 |

질문 3개 모두 캡처 본문을 인용했고(힌트 사다리 5칸 정상), 판정은 자료 밖 답을 wrong 으로 잡았다.
같은 화면을 두 번 올리면 질문이 1장만 가리킨다 — 실제 부스에서는 서로 다른 장면을 담아야 한다.

## 5. 남은 것 (안 한 것)

- 부스 노트북 크롬에서 `getDisplayMedia`·PiP 를 실제로 눌러 보는 것 — 이 머신에는 브라우저가 없어 파일 업로드 경로만 실측했다.
- 캡처 한 장짜리 얕은 그래프 대비: 방문객에게 "장면을 2~4장 담으면 질문이 깊어져요" 안내 문구는 화면에 아직 없다.
- 부스에서 쓰려면 Festa 잠금(10/1) 전에 위 두 가지를 확인해야 한다. 이건 사용자 결정.
