# 02 — 토큰 변경표 (색·radius)

> **원칙:** 기존 토큰 **이름**에 새 **값**을 넣는다. 병렬 토큰 체계를 만들지 않는다.
> 단일 원본은 `demo/YEHS_demo/css/app.css` 의 `:root` (6-53행) — 이 문서는 변경 지시서고,
> 적용한 순간부터 코드가 원본이다 (CLAUDE.md §3-3).
>
> 검은 외곽선 대신 **브랜드 초록 외곽선** — 이게 이번 팔레트의 핵심 한 줄이다.

## 1. 브랜드·면 (app.css `:root`)

| 토큰 | 현재 | **새 값** | 쓰임 · 이유 |
|---|---|---|---|
| `--navy` | `#0a3d2a` | **`#155C46`** | 메인 초록. 다크 판정 헤드(`design-system.css:41` 그라디언트 중단)·명패 |
| `--navy-deep` | `#052a1c` | **`#0C3D2E`** | 그라디언트 하단 (새 navy 에서 유도) |
| `--brand` | `#03b26c` | **`#08B879`** | 버튼 초록 (주 액션) |
| `--brand-strong` | `#029359` | **`#069E67`** | 주 액션 hover·active (새 brand 에서 유도) |
| `--brand-weak` | `#f0faf6` | **`#E7F7EF`** | 연한 민트 — 틴트 버튼·선택 칩·next-card |
| `--canvas` | `#F5F5F5` | **`#FFFDF7`** | 페이지 배경. **흰색/회색 대신 색이 아주 약하게 들어간 크림** |
| `--paper` | `#FAF9F6` | **`#FFFFFF`** | 카드 면. 배경이 크림이 됐으니 카드가 순백이어야 떠 보인다 (관계 역전) |
| `--fill` | `#F0F3F0` | **`#EFF6F1`** | 카드 안 회색 면 → 초록기 살짝 |
| `--border` | `#E2E7E3` | **`#D8EEE3`** | 카드 1.5px 보더 색 (03_components §카드 참조) |
| `--text` | `#16211C` | **`#26372F`** | 본문 글자 — 순검정 대신 진초록 섞인 잉크 |
| `--text-2` | `#46584F` | 유지 | 이미 초록 계열 |
| `--text-3` | `#8AA295` | 유지 | |
| `--cyan` | `#3fd599` | 유지 | 어두운 면 위 강조 (verdict 막대·파형) |
| `--mint` | `#aeefd5` | 유지 | delta pill |
| `--yellow` | `#F0B429` | 유지 | 주의·초과 |
| `--shadow` | `0 1px 2px rgba(10,61,42,.08)` | `0 2px 8px rgba(28,82,61,.06)` | 새 navy 기준으로 부드럽게 |
| `--shadow-panel` | (기존 2겹) | **`0 8px 24px rgba(28,82,61,.08)`** | 카드 그림자 (사용자 지정값) |

**주의:** `--blue/--blue-strong/--blue-weak` 는 `--brand*` 별칭이라 자동으로 따라온다. 건드리지 않는다.

## 2. radius — 토큰 4종 문법 유지, 값만 교체

| 토큰 | 현재 | **새 값** | 쓰임 |
|---|---|---|---|
| `--r-print` | `4px` | **`20px`** | 카드·패널. "제본된 리포트(각짐)" → "부드러운 노트" |
| `--r-inner` | `var(--r-print)` 별칭 | **`16px` (별칭 해제, 실값)** | 카드 안의 작은 카드 — 바깥 20px 보다 살짝 작아야 자연스럽다 |
| `--r-ctl` | `10px` | **`12px`** | 버튼·입력 |
| `--r-pill` | `999px` | 유지 | 칩·탭 |
| `--r-dot` | `50%` | 유지 | 아바타·점 |
| `--r-card`, `--r-btn` | 별칭 | 유지 (자동 추종) | |

**⚠ `design-system.css:26` 에 `--r-print: 4px` 재선언이 있다.** app.css 만 고치면
캐스케이드에서 도로 4px 로 덮인다 — **두 곳 다** 고치거나 design-system.css 쪽 재선언을 지운다.

## 3. 캐릭터 팔레트 (chatter.css `:root`, 15-42행)

| 토큰 | 현재 | **새 값** | 이유 |
|---|---|---|---|
| `--chick-body` | (없음 — 신설) | **`#FFD96A`** | 캐릭터 노랑 — 몸 색 단일 원본 |
| `--chick-midm` | `#f6c945` | **`var(--chick-body)`** | 4색 → 단일. 기존 `var(--chick-${speaker})` 참조가 그대로 동작하도록 별칭으로 유지 |
| `--chick-solar` | `#ffd76e` | **`var(--chick-body)`** | 〃 |
| `--chick-exaone` | `#f7b96b` | **`var(--chick-body)`** | 〃 |
| `--chick-ax` | `#ffe3a3` | **`var(--chick-body)`** | 〃 |
| `--chick-line` | (없음 — 신설) | **`#356B59`** | **캐릭터 외곽선.** 검정 대신 브랜드 초록 — 훨씬 부드럽다 |
| `--chick-belly` | (없음 — 신설) | **`#FFF3CF`** | 배의 밝은 크림 패치 |
| `--chick-mint` | (없음 — 신설) | **`#9ADBC0`** | 소품(헤드폰·배지 로제트·새싹) 민트 |
| `--chick-beak` | `#f08a3c` | **`#F0A93C`** | 부리·발 — 레퍼런스의 따뜻한 주황 |
| `--chick-blush` | `#ff9d9d` | **`#F7B6A8`** | 볼 홍조 (사용자 지정값) |
| `--bub-midm/-solar/-exaone/-ax` | 크림 4종 | 아래 표로 교체 | 말풍선 → **청중 카드 틴트**로 승격 (레퍼런스 `528b` 카드 4색) |
| `--bub-ink` | `#4a3b2c` | 유지 | 말풍선 잉크 — 대비 검증 완료된 값 |

**카드 틴트 4색 (레퍼런스 `528b3b8c` 의 파스텔 4장):**

| 토큰 | 새 값 | 카드 |
|---|---|---|
| `--bub-midm` | `#E9F6EF` (민트) | 믿:음 — 대조 담당 |
| `--bub-solar` | `#FFF6E0` (노랑) | 쏠라 — 자료 담당 |
| `--bub-exaone` | `#FDEEEA` (핑크) | 엑사원 — 인정 담당 |
| `--bub-ax` | `#EAF2FB` (블루) | 엑씨 — 듣기 담당 |

## 4. 불변 — 절대 건드리지 않는다

```css
--ok:#0A8F68;  --ok-bg:#E9F7EF;    /* aligned */
--mid:#B45309; --mid-bg:#FDF6E3;   /* 언급만 */
--no:#DC2626;  --no-bg:#FDF0EF;    /* missing */
--ct:#9333EA;  --ct-bg:#F6EDFD;    /* contradiction */
--om:#8A6A15;  --om-bg:#F7F1DE;    /* justified_skip */
```
weight 4단(`--w-body:500/--w-med:650/--w-bold:750/--w-display:830`)·`--ease`·서체(Pretendard)도 유지.

## 5. 파급 범위와 후속 정리 (같은 커밋에서)

값 교체만으로 대부분 화면이 따라오지만, **리터럴로 박힌 곳**은 따로 고쳐야 한다:

| 위치 | 현재 | 처리 |
|---|---|---|
| `app.css:142-143` `.clickable:hover` | `rgba(2,32,71,.07)` — 옛 파란 잔재 | `rgba(28,82,61,.08)` 로 |
| `design-system.css:41` verdict 그라디언트 시작색 | `#1B4A3E` 리터럴 | `#1F6B52` (새 navy 계열 밝은 단) |
| `design-system.css` 다크면 뮤트 텍스트 | `#9FC9B6 #7FB3A2 #52796C` 등 리터럴 | 유지 가능 (새 navy 와도 조화) — 눈으로 확인 후 결정 |
| `app.css .btn-primary:disabled` | `#DFE3E8` | `#E3EDE6` (초록기) |
| `app.css .btn-tint:hover` | `#C4E2D2` | 유지 (새 `--brand-weak` 와 자연 연결) |
| `theater.css` 커튼색 `--th-curtain:#1F5A49` | 리터럴 토큰 | `#1E6B52` 로 새 navy 에 맞춤 (선택) |
| `MVP_SPEC.md` §디자인 토큰 사본 | 옛 값 | **코드 적용 후** 새 값으로 갱신 |
| `CLAUDE.md` §3-3 두 줄 | `--brand:#03B26C`, `--navy:#0A3D2A` | 새 hex 로 갱신 |

**랜딩 3종 CSS(`landing*.css`)는 이번 범위 밖이다** — 리터럴 hex 가 수십 개라 값 교체가 안 먹는다.
후속 작업으로 남기고, 부스 데모가 랜딩을 안 거치는 경로면 그대로 둬도 된다.
