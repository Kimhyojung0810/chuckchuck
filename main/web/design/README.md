# 디자인 개편 문서 — 먼저 읽기

> 브랜치 `design/overhaul-1012` · 작업 폴더 `~/project/wt-design` · 미리보기 `http://localhost:8810` (VS Code 포트 전달)
> 공개 도메인(chuckchuck-present.com)은 main 이다 — 이 브랜치를 합치기 전까지 바뀌지 않는다.

## 문서

| 파일 | 무엇 | 언제 읽나 |
|---|---|---|
| [BRIEF.md](BRIEF.md) | 서비스 정의 · 사용 흐름 · **바꾸면 안 되는 것** · 디자인 방향(가상 발표 스튜디오) | 처음 한 번, 방향이 헷갈릴 때 |
| [SPACE.md](SPACE.md) | 3D 공간 설계 — 방 하나 · 네 정거장 · 90° 회전 · 단계별 조명 · 3D/2D 경계 · 구현 방식 | 공간 · 전환 · 조명을 만질 때 |
| [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) | 색 · 글 · 공간 · 움직임 · 부품 토큰과 규칙, 옛→새 토큰 표 | 2D 패널 안을 그릴 때 |
| [PLAN.md](PLAN.md) | 단계별 작업 계획 · 체크리스트 · **작업 기록** | 매 작업 시작과 끝 |

## 작업 규칙

1. **시작할 때** PLAN.md 의 「지금 단계」 와 맨 아래 기록을 읽는다.
2. **끝날 때** PLAN.md 체크리스트를 고치고 기록에 한 줄을 남긴다 — 날짜 · 한 일 · 확인한 방법 · 남은 것.
3. 방향이 바뀌면 코드보다 문서를 먼저 고친다 (BRIEF → SPACE/DESIGN_SYSTEM → PLAN).
4. **발표 · 질의응답의 카메라 사용은 절대 바꾸지 않는다** (BRIEF §3). 카메라를 여는 코드(`vision_rehearsal.js` · `booth_qa.js` · `booth_call.js` · `booth_cv*.js` · `call_flow.js`)는 건드리지 않고, 새 공간은 그 화면을 **감싸기만** 한다.
5. CLAUDE.md §3 토스 규율(해요체 · 「닫기」 · 다크패턴 금지 · 히어로 금지)은 그대로다. 유리는 스튜디오 떠 있는 창에만 — liquid-glass 예외 (CLAUDE.md §3-4, 10-12 사용자).
6. 화면은 헤드리스로 확인한다 — 데스크톱(1440×900) · 폰(390×844) · 움직임 줄이기 켬. Playwright 는 `LD_LIBRARY_PATH=$HOME/.local/lib/pwlibs`.
7. 커밋 전 `etc/scripts/chk gate` (css/js 를 고쳤으면 `etc/scripts/chk bump`).
8. 스튜디오(React) 원본은 `main/web/studio-app/src/` — 고친 뒤 `cd main/web/studio-app && npm install && npm run build` 로 `js/studio-app.js` 를 다시 만들어 함께 커밋한다 (`node_modules` 는 올리지 않는다). Node 는 `~/.local/bin`.
9. **시연 데이터(덱 PPT · 녹음 · 파싱본)는 git 밖이다.** 이 작업 공간에서 리허설 덱 셋(급속충전 · 미세플라스틱 · 배달앱 별점)을 고르려면
   원본 저장소에서 복사한다 — 덱 폴더 `~/project/chuckchuck/main/decks/*` → `main/decks/`, 파싱본(10-05 고정본)
   `~/project/chuckchuck/var/data/sessions/2026/10/05/20261005T1402{01,12,23}Z_*` → `var/data/sessions/2026/10/05/`.
   파싱본이 있어야 Upstage 파싱(과금) 없이 바로 뜬다. 확인: `curl -s localhost:8810/api/v1/dev/decks` 의 `cached_session_id`.
