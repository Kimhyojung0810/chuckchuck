# Apple UI 참고 자료 (2026-10-16 수집)

> 목적: Report 2.0 시제품 디자인을 Apple 수준으로 다시 잡기 위한 근거. 사용자: 「디자인 개병신 같은데. 애플 UI 자료 어디서 좀 구해봐와」.
> **원문 · 캡처는 저작물이라 공개 저장소에 올리지 않는다** (`.gitignore` — 로컬에만). 이 파일은 요약 · 실측 값만.

## 1. 구한 것
| 자료 | 위치 (로컬) | 무엇 |
|---|---|---|
| Apple HIG 11쪽 | `etc/design-ref/apple/hig/*.md` (+ 원본 JSON) | Typography · Layout · Color · Charts · Charting data · Materials(Liquid Glass) · Dark Mode · Motion · Accessibility · Writing · What's new. `hig2md.py` 가 `developer.apple.com/tutorials/data/design/human-interface-guidelines/<쪽>.json` 을 마크다운으로 |
| apple.com/kr 실측 토큰 | `etc/design-ref/output/apple.com/DESIGN.md` (dembrandt, 4쪽 합침: /kr · /kr/iphone · /kr/watch · /kr/newsroom) | 글자 크기 · 굵기 · 행간 · 색 · 둥글기 · 버튼 · 움직임 |
| apple.com/kr 캡처 12장 | `etc/design-ref/apple/shots/*.jpg` (1440×900, 쪽마다 3화면) | 홈 · iPhone · Watch · Newsroom |

**못 구한 것 (그리고 이유)**
- Figma · Sketch UI 키트 (iOS 27 · macOS 27, 2026-06 공개): Apple 계정 · 라이선스 동의 · Sketch 는 맥 전용 — 이 서버에서 받을 수 없다. 받을 곳: developer.apple.com/design/resources · Figma Community 「Apple Design」.
- **SF Pro · SF Pro KR 폰트**: Apple 라이선스상 Apple 플랫폼 앱 목업 용도 — **웹에 실어 배포하면 안 된다.** 웹에선 `-apple-system, BlinkMacSystemFont` 로 Apple 기기에서만 시스템 SF 가 뜨게 하고, 나머지는 Pretendard(SF 와 비슷한 비율)로 받는다.

## 2. HIG 에서 리포트에 바로 쓰는 규칙 (원문 근거)
- **위계는 굵기 · 크기 · 색으로.** 가는 굵기(Ultralight · Thin · Light) 피하고 Regular · Medium · Semibold · Bold 만. 서체 수는 최소로. (Typography — Conveying hierarchy)
- **중요한 것을 위 · 앞에.** 정렬로 훑기 쉽게, 들여쓰기로 종속 표시. 관련된 것은 **여백 · 컨테이너 · 구분선**으로 묶는다. (Layout — Visual hierarchy)
- **점진적 공개.** 처음엔 적게 보이고 나머지는 펼치기 · 메뉴 · 다음 화면으로. (Layout)
- **컨트롤과 콘텐츠를 구분.** Liquid Glass 는 **컨트롤 층에만**, 콘텐츠 층에 쓰지 말 것 · 아껴 쓸 것. (Materials)
- **차트: 데이터가 주인공**, 축 · 설명은 보조. 차트마다 **한 줄 요약**을 먼저(예: 날씨 앱 강수 제목). 색에만 의미를 싣지 말 것, 인접 색 사이 구분선. 앞쪽 가장자리를 주변 요소와 맞춘다. (Charts — Best practices · Descriptive content · Color)
- 기본 글자 크기: iOS 17pt(최소 11) · macOS 13pt(최소 10). (Typography 표)

## 3. apple.com/kr 실측 (dembrandt, 2026-10-16)
| 역할 | 값 |
|---|---|
| 글꼴 | SF Pro KR (Display/Text) — 웹에선 우리가 못 씀 → 시스템 스택 + Pretendard |
| 큰 제목 | 80 · 56 · 48 · 40px / **600** / 행간 1.1~1.19 |
| 중간 제목 | 32 · 28 · 24px / 600 (일부 700) / 행간 1.22~1.29 |
| 본문 | 21 · 19 · 17px / 400 / 행간 1.29~1.47 |
| 작은 글 | 14 · 12px / 400 · 600 |
| 글자색 | `#1D1D1F` (순검정 아님) |
| 바탕 | `#FFFFFF` · 섹션 바탕 `#F5F5F7` · `#FAFAFC` |
| 강조(유일한 색) | `#0071E3` 버튼 · 링크 `#0066CC` · 어두운 면 링크 `#2997FF` · 「New」 `#B64400` |
| 둥글기 | 카드 **28px**(가장 많음) · 18~20px · 12px · 버튼 **980px(알약)** |
| 버튼 | 17px / 400 / 안쪽 11px 21px / 알약 — 주 버튼 파랑 면 + 옆에 「구입하기 ›」 글자 링크 |
| 그림자 | 거의 없음 (카드도 그림자 없이 바탕색 차이로 구분) |
| 움직임 | `cubic-bezier(0.4, 0, 0.6, 1)` · 0.24~0.4초 · 들어올 때 0.7~0.9초 한 번 |

캡처에서 보이는 것: 제목 한 줄이 크고 굵다(「라인업 살펴보기.」 처럼 마침표까지), 그 아래는 **넓은 여백**, 카드는 테두리 · 그림자 없이 `#F5F5F7` 위 흰 면(또는 그 반대), 한 줄에 행동 둘(주 버튼 + 글자 링크 ›), 칩 · 배지는 거의 없음(「New」 주황 글자 하나).

## 4. Report 2.0 시제품이 별로인 이유 (위와 비교한 진단)
| 지금 | Apple 은 |
|---|---|
| 화면마다 바탕이 다름(아이보리 · 차콜 · 차콜 · 아이보리) — 한 제품처럼 안 보임 | 한 바탕 체계(흰 · `#F5F5F7`), 어두운 면은 사진 · 영상 무대에만 |
| 칩 · 배지 남발 (근거 위치 · 영향 · 판정이 흔들려요 …) — 시선이 흩어짐 | 칩 거의 없음. 상태는 글 한 줄 · 색 점 하나 |
| 테두리 + 둥근 상자가 겹겹 (카드 안 카드) | 테두리 없는 면 하나, 묶음은 여백으로 |
| 13~14px 회색 설명 글이 많고 대비가 낮음 | 본문 17~21px, 설명도 짙은 회색 |
| 제목 48px 800 굵기 + 단락 사이가 좁음 | 600 굵기, 제목 아래 넉넉한 여백, 문단 짧게 |
| 버튼 모양이 화면마다 다름 · 한 줄에 버튼 여럿 | 주 버튼 하나(알약) + 글자 링크 › 하나 |
| 상단에 출처 문구 · 내비 · 선택 알약이 한 줄에 몰림 | 위 줄은 이름 + 메뉴만, 나머지는 화면 안으로 |

## 5. 다시 잡을 방향 (제안 — 사용자 승인 후 적용)
- 바탕 `#F5F5F7` / 면 `#FFFFFF` / 글 `#1D1D1F` · 보조 `#6E6E73` / **강조는 우리 초록 하나**(파랑 대신, 브랜드), 판정 5색은 불변 — 판정에만.
- 글: 화면 제목 40~48px/600, 단락 제목 24~28px/600, 본문 17~19px/400, 보조 14px. 시스템 스택 `-apple-system, BlinkMacSystemFont, 'Pretendard Variable', …`.
- 카드 28px 둥글기 · 테두리 · 그림자 없음, 묶음은 여백(섹션 간 80~120px).
- 칩 없애고 상태는 문장 앞 색 점 + 한 줄. 버튼은 주 버튼 알약 하나 + 「근거 보기 ›」 글자 링크.
- 청중석 · 리플레이도 같은 밝은 바탕. 극장 느낌은 삐약이 무대 한 부분(어두운 카드)에만.
