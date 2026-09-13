---
name: continue
description: 자율 개발 세션을 헌장(docs/ROADMAP_AUTONOMOUS.md §2) 순서대로 시작한다. 사용자가 "계속" 이라고 하면 이걸 부른다. 브리핑은 scripts/chk brief 가 만든다.
---

# /continue — 세션 이어받기

1. `scripts/chk brief` 를 돌려 출력을 읽는다. 마일스톤 D-day · 헌장 §0 조건 · 끝나지 않은 할 일 · 두 장부의 마지막 줄 ·
   WORKLOG 맨 위 절과 「이어받을 한 줄」 · git 상태가 한 화면에 있다. 문서를 따로 다시 읽을 필요는 없다 —
   상세가 필요한 항목만 그 파일을 연다.
2. `git status` 에 남의 미커밋 변경이 있으면 건드리지 않는다.
3. 헌장 §1 의 A·B(·B'·G) 에서 **끝난 기준이 가장 가까운 것 하나**를 고른다. 두 개를 동시에 벌리지 않는다.
   Festa(10/6) 전이면 C(뉘앙스 UI)는 설계 노트만.
4. 테스트와 함께 구현한다 (새 파일 800줄/50줄 상한, `app.js`·`app.css` 는 분할하지 않는다).
5. 커밋 전 `scripts/chk gate` — pytest·node 스모크·`?v=`·비밀키를 한 번에 본다. css/js 를 고쳤으면 `scripts/chk bump` 가 `?v=` 를 올린다.
   git 훅이 설치돼 있으면(`scripts/chk install-hooks`) 커밋 때 자동으로 돈다.
6. 커밋·푸시 (CLAUDE.md §3-5, 메시지에 **왜**).
7. WORKLOG 맨 위에 한 절 + 회의록 할 일 상태 갱신 + 「**다음:** …」 한 줄. 다음 세션의 `chk brief` 가 그 줄을 집어 올린다.
8. B4 — `/improve-qa` 한 바퀴 (과금). 사용자가 막았으면 건너뛰고 적는다.

브리지 시연 준비가 목적이면 `scripts/chk doctor` → 브리지 띄우기 → `scripts/chk warmup` 순서다.
