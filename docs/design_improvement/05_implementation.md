# 05 — 구현 순서 · 제약 · 검증

> 구현 에이전트용 실행 시퀀스. 각 단계 끝의 검증을 통과해야 다음으로 간다.
> 브랜치는 `fix/qa-evidence-and-demo-hardening` 그대로 (새 브랜치 금지 — CLAUDE.md §1).

## 0. 시작 전

```bash
cd /home/ubuntu/workspace/00_chuckchuck
python -m pytest tests/ -q                # 기준선 기록 (2026-08-06 기준 544 passed · 7 skipped)
grep -o '?v=[a-zA-Z0-9]*' demo/YEHS_demo/index.html | sort -u    # 현재 캐시 버전 기록
```

- `components/preview.html` 을 브라우저로 열어 **최종 모습을 먼저 눈에 넣는다.**
- 이 문서들의 행 번호가 어긋나 있으면 함수·클래스 이름으로 grep (04_screens 머리말).

## 1. 단계 순서

| # | 작업 | 문서 | 검증 |
|---|---|---|---|
| 1 | 토큰 값 교체 — `app.css :root` + **`design-system.css:26` 의 `--r-print` 재선언 제거**(잊으면 카드가 도로 4px) + `chatter.css :root` 캐릭터 팔레트 | 02 §1-3, §5 | 데모 기동 → 홈이 크림 배경 + 20px 카드로 보이는지. 판정 칩 5색 그대로인지 |
| 2 | `.card` 보더·그림자 + 리터럴 정리(`.clickable:hover` 등) | 02 §5, 03 §1 | 홈·리포트 카드 육안 |
| 3 | `chatter.js` 세 함수 교체 (`props`/`eye`/`chickSvg`) + chatter.css 후속 3건(eye-line 색·ch-eyes 원점·ch-mark) | 01 §4-5 | `node --check js/chatter.js` → `chatter_preview.html` 열어 4마리·표정 확인 |
| 4 | 청중 진입 카드 개편 (`entryCardHtml` + `.aud-*` CSS + 역할 pill) | 03 §3-4, 04 §3 | 리포트 청중 탭 → 틴트 4장 + 객석 열림 |
| 5 | 리포트 헤드 (점수 옆 발표새 + 문구 톤 + 막대 끝 점) | 03 §5, 04 §2 | 점수 티어별 표정 (샘플 86점 → happy) |
| 6 | 빈·로딩 상태 3곳 | 03 §6, 04 §5 | 새 세션에서 로딩·빈 카드 확인 |
| 7 | playbill 도장 색 | 04 §6 | 포스터 벽 티켓 |
| 8 | **`index.html` `?v=` 전부 +1** | README §6 | `grep -c` 로 남은 옛 버전 0 확인 |
| 9 | 문서 동기화: `MVP_SPEC.md` 토큰 사본 · `CLAUDE.md` §3-3 hex 두 줄 · `docs/UI_REDESIGN.md` §9-10 에 "시각 스펙은 docs/design_improvement/01_character.md 로 대체" 한 줄 | 02 §5 | — |

각 단계 후 공통:

```bash
python -m pytest tests/ -q       # 파이썬 무접촉이므로 기준선과 동일해야 한다. 달라지면 즉시 중단
node --check demo/YEHS_demo/js/chatter.js && node --check demo/YEHS_demo/js/app.js \
  && node --check demo/YEHS_demo/js/playbill.js
```

마지막에:

```bash
MOCK_EXTERNAL_APIS=true DEMO_PORT=8840 python -m demo.bridge    # 포트 충돌 시 8841…
curl -s localhost:8840/api/health                               # {"ok":true,"mock":true}
# 브라우저: http://127.0.0.1:8840/ → 04_screens §7 체크리스트
```

## 2. 제약 (요약 — 어기면 되돌린다)

- **판정 5색 불변.** `--ok/--mid/--no/--ct/--om` 과 `-bg` 를 만지는 diff 는 그 자체로 버그다.
- **클래스 계약 보존** (01 §1 트리). `chickSvg` 교체 후 `grep -c "ch-eye-happy\|ch-pen-stroke\|ch-figure" js/chatter.js` 로 잔존 확인.
- **숫자·표·개수는 문구 톤만 바꾸고 값은 그대로.**
- **새 keyframe 을 추가하면 reduced-motion 두 레지스트리에 등록** (`chatter.css:934-969`, `theater.css:583-607`).
- **`app.js`·`app.css` 분할 리팩터 금지** (마감 전). 수정은 지점 단위로.
- **랜딩 3종 CSS 는 범위 밖.**
- 백엔드·파이썬은 **한 줄도 만지지 않는다.** pytest 결과가 변하면 잘못 만진 것이다.

## 3. 롤백

토큰·캐릭터·카드가 전부 별개 커밋이 되도록 단계마다 커밋한다 (`feat:`/`fix:` 컨벤션).
부스에서 문제가 보이면 해당 단계 커밋만 `git revert` — 전체를 되돌릴 필요가 없게.

커밋 예:
```
feat: 디자인 토큰 v2 — 크림 배경·20px 카드·새 브랜드 초록 (docs/design_improvement/02)
feat: 발표새 캐릭터 교체 — 단일 몸 + 소품 4종, 클래스 API 유지 (docs/design_improvement/01)
feat: 청중 좌석 카드 — 틴트 4장 + 역할 pill (docs/design_improvement/03§4)
```

## 4. 알려진 함정 (이 저장소 특유)

| 함정 | 회피 |
|---|---|
| `?v=` 안 올리면 "고쳤는데 안 바뀜" | 8단계. 데모 날 20분 날리는 1순위 함정 (CLAUDE.md §2) |
| `design-system.css` 의 `--r-print` 재선언 | 1단계에서 같이 제거 — app.css 만 고치면 카드가 도로 4px |
| `.ch-eyes` 깜빡임 원점 | 01 §5-2 — transform-box 없으면 눈이 얼굴 밖으로 튄다 |
| playbill 이 `window.Chatter` 이전에 돌 수 있음 | 04 §5 — 로드 순서 확인 (`index.html` 에서 playbill.js 가 chatter.js 뒤인지) |
| 이 문서들의 행 번호 드리프트 | 이름으로 grep. 행 번호는 참고용 |
| 캐릭터가 데이터 가림 | "연출이 데이터를 가리면 연출을 버린다" (CLAUDE.md §3-4) |
