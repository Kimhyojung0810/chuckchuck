# 01 — 발표새 캐릭터 시스템

> 기준 레퍼런스: `reference/404b762b-….png` (피니 보드). 베끼지 않고 **문법**만 가져온다:
> 머리 60%+ · 완전히 둥근 실루엣 · 굵은 브랜드 초록 외곽선 · 색 3~4개 · 큰 눈 · 점 부리 · 홍조.
>
> **이식 대상은 `demo/YEHS_demo/js/chatter.js` 의 `props()`(82-131행) · `eye()`(134-143행) ·
> `chickSvg()`(154-189행) 세 함수뿐이다.** §4 의 완성 코드를 그대로 옮긴다.
> 렌더 지점 9곳과 애니메이션 27종은 클래스 API 로 걸려 있어서 **클래스 이름을 지키면 무수정 동작**한다.

---

## 1. 왜 함수 셋만 바꾸면 되나 (기존 구조)

- 병아리는 이미 `chickSvg(speaker)` **한 함수**가 그린다. 이미지 파일 0개, 이모지 0개 — 전부 인라인 SVG.
- 표정은 백엔드 `data-mood` 5종(`neutral/happy/curious/excited/grumpy`)이 좌석 요소에 붙고,
  CSS(`chatter.css:521-585`)가 **미리 그려 둔 레이어**(∪눈·∧눈·하트·물음표)의 opacity 를 토글한다.
- 몸짓은 CSS 클래스(`talking/waving/applauding/nodding/…`)와 keyframes 27종이 담당한다.
- 렌더 지점 9곳 (전부 `chickSvg()` 호출): 객석 오버레이(96-134px) · 리포트 청중 카드(76px) ·
  무대 실루엣(38-54px) · 등장 의식(56-78px) · 종연/커튼콜/배웅(72-104px) · 회상 카드(46px) ·
  `chatter_preview.html`.

**따라서 지켜야 할 클래스 계약 (하나라도 빠지면 해당 연출이 죽는다):**

```
svg.ch-chick (inline style: --ch-sway, --ch-breath-delay)
└ g.ch-figure                       ← 숨쉬기(chBreathe)·anticipation 이 여기 걸린다
  ├ g.ch-legs                       ← 발
  ├ .ch-tailfeather                 ← 꼬리 깃
  ├ .ch-torso                       ← 몸 (새 버전에서는 머리+몸 한 덩어리 블롭)
  ├ .ch-wing ×2
  ├ g.ch-head                       ← data-listening 이 머리(얼굴)를 ±8° 돌린다
  │ ├ .ch-tuft                      ← 머리 장식 (새싹)
  │ ├ .ch-blush ×2
  │ ├ g.ch-eyes                     ← 깜빡임(chBlinkEyes) — scaleY
  │ │ └ g.ch-eye › .ch-eye-ball / .ch-eye-hi ×2 / .ch-eye-line.ch-eye-happy / .ch-eye-line.ch-eye-grumpy
  │ └ .ch-beak
  ├ g.ch-prop (.ch-prop-phones|script|pen|badge) › .ch-pen-stroke / .ch-sparkle
  └ g.ch-emote › .ch-heart / .ch-mark
```

## 2. 새 캐릭터 스펙 — "말랑한 발표새"

viewBox `0 0 100 100` 유지 (transform-origin·좌석 CSS 가 이 좌표계를 가정한다).

| 항목 | 값 | 이유 |
|---|---|---|
| 실루엣 | 머리+몸이 **한 덩어리 달걀 블롭** (y 9~86). 위가 넓고 아래가 살짝 좁다 | 레퍼런스 문법 — 목 없는 몽실함. 눈사람으로 갈라 그리면 외곽선이 교차한다 |
| 머리 비율 | 얼굴 영역(y 9~58)이 몸 전체의 **~64%** | "머리가 몸의 60% 이상" |
| 외곽선 | **`var(--chick-line)` = #356B59, 두께 3** (소품 2, 세부 1.6) | 검정 대신 브랜드 초록 — 부드러움의 핵심 |
| 몸 색 | `var(--chick-${speaker})` → 전부 `--chick-body` #FFD96A 로 수렴 (02_tokens §3) | 4마리 같은 몸 = 같은 종족 |
| 배 | 밝은 크림 타원 `--chick-belly` #FFF3CF, 외곽선 없음 | 레퍼런스의 밝은 배 |
| 눈 | 크게 — rx5.2 ry5.8, 하이라이트 2점(흰 r2 + r1) | 현재(4.3)보다 큼직하게. 생기의 90%는 눈 |
| 부리 | **점처럼 작게** — 가로 8.6 세로 6 의 둥근 콩, #F0A93C + 외곽선 | 현재 삼각형 → 레퍼런스의 점 부리 |
| 홍조 | rx4.6 ry2.7, `--chick-blush` #F7B6A8, 눈 바로 아래 바깥쪽 | |
| 날개 | 아주 작은 옆 플랩 2개, 몸 밖으로 살짝 | 어두운 객석 실루엣에서도 보여야 한다 |
| 발 | 아주 작은 주황 콩 2개, 블롭 밑단 아래로 6px | "팔다리는 극단적으로 짧게" |
| 머리 장식 | **민트 새싹** (줄기 + 잎 2장, `--chick-mint`) | "머리 위에 작은 새싹" — 성장 서비스 은유 |
| 색 수 | 몸1 + 외곽선1 + 주황1 + 민트1 (+홍조) = **4색 문법** | 레퍼런스 팔레트 5색 중 4색 사용 |

## 3. 표정 · 소품 · 점수 매핑

**표정 5종 — 기존 `data-mood` enum 을 그대로 쓴다** (백엔드 `contracts.py:931` 불변):

| mood | 눈 | 추가 연출 (기존 CSS 그대로) | 뜻 |
|---|---|---|---|
| `neutral` | 동그란 눈 + 하이라이트 | idle 흔들림·숨쉬기·깜빡임 | 기본 |
| `happy` | ∪ 곡선 | 하트 + 통통(chHop) | 기쁨·축하 |
| `curious` | 동공 1.08배 | 물음표 + 갸웃(chTilt) | 갸웃 |
| `excited` | 눈 확대(chEyeWide) | 부르르(chShiver) | 놀람·신남 |
| `grumpy` | ∧ 곡선 | 고개 돌림 + 밑줄 긋기 | 뾰로통 (화남 아님) |

**우는 표정은 만들지 않는다.** 낮은 점수의 표정은 `neutral`(응원 문맥) 이다.

**점수 → 표정 티어** (리포트 헤드 옆 캐릭터, 04_screens §2):

| 점수 | mood | 문맥 |
|---|---|---|
| ≥ 90 | `excited` | 축하 |
| ≥ 75 | `happy` | 기쁨 |
| < 75 | `neutral` | **응원** — "다음엔 더 잘 들려줘요" 톤. grumpy 금지 |

**소품 4종 — 역할 의미는 유지, 그림체만 새 문법으로** (민트 + 초록 외곽선):

| 자리 | 소품 | 역할 (명패 아래 한 줄, `SEAT_ROLE`) | 유의 |
|---|---|---|---|
| 엑씨 (SKT A.X) | **민트 헤드폰** | 발표를 귀로 들었어요 (F-05 STT) | 밴드가 새싹을 피해 지나간다 |
| 쏠라 (Upstage) | **슬라이드 몇 장** (겹친 흰 카드) | 발표자료를 통독했어요 (F-01/06/07) | 기존 두루마리 → 레퍼런스의 문서 |
| 믿:음 (KT) | **형광펜** | 자료와 발화를 대조했어요 (F-11) | `.ch-pen-stroke` 클래스 필수 — `chPenDraw` 애니메이션이 이 클래스에 걸려 있다 |
| 엑사원 (LG) | **별 로제트 배지** (가슴) | 설명한 개념을 인정했어요 | `.ch-sparkle` 클래스 유지 |

## 4. 이식 코드 — `chatter.js` 의 세 함수를 이걸로 교체

> 이 블록이 **캐릭터의 단일 원본**이다. `components/preview.html` 은 이 코드의 사본으로
> 만들어졌다 — 둘이 어긋나면 이 문서가 맞다.

```js
  /**
   * 소품 = 그 모델이 파이프라인에서 실제로 한 일 (UI_REDESIGN §9 실루엣 테스트).
   * 전부 민트(--chick-mint) + 초록 외곽선(--chick-line) — 같은 세계관의 물건.
   */
  function props(speaker) {
    if (speaker === 'ax') {
      /* 헤드폰 — 발표를 귀로 들은 유일한 청중 (F-05 STT) */
      return `
  <g class="ch-prop ch-prop-phones">
    <path d="M21 34a29 29 0 0 1 58 0" fill="none" stroke="var(--chick-line)"
          stroke-width="3.4" stroke-linecap="round"/>
    <rect x="14" y="30" width="10.5" height="15.5" rx="5"
          fill="var(--chick-mint)" stroke="var(--chick-line)" stroke-width="2"/>
    <rect x="75.5" y="30" width="10.5" height="15.5" rx="5"
          fill="var(--chick-mint)" stroke="var(--chick-line)" stroke-width="2"/>
  </g>`;
    }
    if (speaker === 'solar') {
      /* 슬라이드 몇 장 — 자료를 통독한 청중 (F-01/06/07). 겹친 두 장이어야 '자료 묶음'으로 읽힌다 */
      return `
  <g class="ch-prop ch-prop-script" transform="rotate(-8 76 68)">
    <rect x="71.5" y="56.5" width="17" height="12.5" rx="2.5"
          fill="#F2FBF6" stroke="var(--chick-line)" stroke-width="2"/>
    <rect x="68.5" y="59.5" width="17" height="12.5" rx="2.5"
          fill="#FFFFFF" stroke="var(--chick-line)" stroke-width="2"/>
    <rect x="71" y="62" width="5.5" height="3.2" rx="1" fill="var(--chick-mint)"/>
    <path d="M71 67.5h12M71 69.8h8.5" stroke="#BFD9CB" stroke-width="1.4" stroke-linecap="round"/>
  </g>`;
    }
    if (speaker === 'midm') {
      /* 형광펜 — 자료와 발화를 대조하며 표시 (F-11). ch-pen-stroke 는 chPenDraw 가 긋는 밑줄 */
      return `
  <g class="ch-prop ch-prop-pen">
    <path class="ch-pen-stroke" d="M72 90h22" stroke="#FFE14D" stroke-width="6"
          stroke-linecap="round" opacity="0"/>
    <g transform="rotate(28 79 68)">
      <rect x="75" y="56" width="8.5" height="18" rx="3.5"
            fill="#FFE14D" stroke="var(--chick-line)" stroke-width="2"/>
      <rect x="75" y="56" width="8.5" height="6" rx="3"
            fill="var(--chick-beak)" stroke="var(--chick-line)" stroke-width="2"/>
      <path d="M75.8 74h7l-3.5 5z" fill="#F7E9B8" stroke="var(--chick-line)" stroke-width="1.6"
            stroke-linejoin="round"/>
    </g>
  </g>`;
    }
    /* 엑사원 — 가슴의 별 로제트. 전문가의 인정 담당 (aligned) */
    return `
  <g class="ch-prop ch-prop-badge">
    <path d="M46.4 78.2l-2.6 5.2 3.6-.9 1.7 3.1 2.2-5.6z" fill="var(--chick-mint)"
          stroke="var(--chick-line)" stroke-width="1.4" stroke-linejoin="round"/>
    <path d="M53.6 78.2l2.6 5.2-3.6-.9-1.7 3.1-2.2-5.6z" fill="var(--chick-mint)"
          stroke="var(--chick-line)" stroke-width="1.4" stroke-linejoin="round"/>
    <circle cx="50" cy="71" r="8" fill="var(--chick-mint)"
            stroke="var(--chick-line)" stroke-width="2"/>
    <circle cx="50" cy="71" r="5" fill="#FFFFFF"/>
    <path d="M50 67.4l1.2 2.4 2.7.4-2 1.9.5 2.7-2.4-1.3-2.4 1.3.5-2.7-2-1.9 2.7-.4z"
          fill="var(--chick-body, #FFD96A)" stroke="var(--chick-line)" stroke-width=".8"/>
    <g class="ch-sparkle" fill="#FFF2C4">
      <path d="M63 58l1 2.6 2.6 1-2.6 1-1 2.6-1-2.6-2.6-1 2.6-1z"/>
    </g>
  </g>`;
  }

  /** 눈 한 짝. 크고 또렷하게 + 하이라이트 2점. 표정 곡선은 mood 가 켠다 */
  function eye(cx) {
    return `
    <g class="ch-eye">
      <ellipse class="ch-eye-ball" cx="${cx}" cy="42" rx="5.2" ry="5.8" fill="#2F3B33"/>
      <circle class="ch-eye-hi" cx="${cx + 1.8}" cy="39.6" r="2" fill="#fff"/>
      <circle class="ch-eye-hi" cx="${cx - 2}" cy="44.2" r="1" fill="#fff" opacity=".75"/>
      <path class="ch-eye-line ch-eye-happy" d="M${cx - 5.5} 40q5.5 7.5 11 0"/>
      <path class="ch-eye-line ch-eye-grumpy" d="M${cx - 5.5} 45.5q5.5 -7.5 11 0"/>
    </g>`;
  }

  /**
   * 발표새 한 마리 — "말랑한 발표새".
   *
   * 머리+몸이 한 덩어리 달걀 블롭이다 (얼굴 영역이 전체의 ~64%). 갈라 그리면
   * 외곽선이 교차해서 지저분해진다. 외곽선은 검정이 아니라 브랜드 초록
   * (--chick-line) — 이게 부드러움의 핵심이다.
   *
   * 클래스 구조는 옛 병아리와 동일하게 유지한다. mood CSS·keyframes 27종·
   * 렌더 지점 9곳이 전부 이 클래스에 걸려 있다 (01_character.md §1).
   */
  function chickSvg(speaker) {
    const body = `var(--chick-${speaker}, #FFD96A)`;
    return `
<svg class="ch-chick" viewBox="0 0 100 100" role="img"
     aria-label="${esc(FALLBACK_NAMES[speaker] || speaker)} 병아리"
     style="--ch-sway:${SWAY[speaker] || '2.4s'};--ch-breath-delay:${BREATH[speaker] || '0s'}">
  <g class="ch-figure">
    <g class="ch-legs" fill="var(--chick-beak)" stroke="var(--chick-line)"
       stroke-width="1.8" stroke-linejoin="round">
      <path d="M41 85.5c-2.8 3.2-1.6 6.5 1.6 6.5 2.6 0 4.4-1.8 4.2-5.4z"/>
      <path d="M59 85.5c2.8 3.2 1.6 6.5-1.6 6.5-2.6 0-4.4-1.8-4.2-5.4z"/>
    </g>
    <path class="ch-tailfeather" d="M20 62c-5.5-1-9 1.5-9.5 5.5 4 1.2 7.5.3 10-1.8z"
          fill="${body}" stroke="var(--chick-line)" stroke-width="2.4" stroke-linejoin="round"/>
    <path class="ch-torso" d="M50 9C30 9 16 24 16 45c0 13 5 22 9 28 5 7 14 13 25 13s20-6 25-13c4-6 9-15 9-28C84 24 70 9 50 9z"
          fill="${body}" stroke="var(--chick-line)" stroke-width="3" stroke-linejoin="round"/>
    <ellipse class="ch-belly" cx="50" cy="72" rx="13" ry="9.5" fill="var(--chick-belly)"/>
    <path class="ch-wing" d="M17 50c-5 .8-8 4.4-7.4 9 4.4 1 8.6-.7 11-4z"
          fill="${body}" stroke="var(--chick-line)" stroke-width="2.4" stroke-linejoin="round"/>
    <path class="ch-wing" d="M83 50c5 .8 8 4.4 7.4 9-4.4 1-8.6-.7-11-4z"
          fill="${body}" stroke="var(--chick-line)" stroke-width="2.4" stroke-linejoin="round"/>
    <g class="ch-head">
      <g class="ch-tuft">
        <path d="M50 9V4.5" fill="none" stroke="var(--chick-line)" stroke-width="2"
              stroke-linecap="round"/>
        <path d="M50 5C49 1.8 46.2.6 43.8 1.6c.5 2.7 3 4 6.2 3.4z" fill="var(--chick-mint)"
              stroke="var(--chick-line)" stroke-width="1.6" stroke-linejoin="round"/>
        <path d="M50 5c1-3.2 3.8-4.4 6.2-3.4-.5 2.7-3 4-6.2 3.4z" fill="var(--chick-mint)"
              stroke="var(--chick-line)" stroke-width="1.6" stroke-linejoin="round"/>
      </g>
      <ellipse class="ch-blush" cx="29.5" cy="50" rx="4.6" ry="2.7" fill="var(--chick-blush)"/>
      <ellipse class="ch-blush" cx="70.5" cy="50" rx="4.6" ry="2.7" fill="var(--chick-blush)"/>
      <g class="ch-eyes">${eye(38.5)}${eye(61.5)}</g>
      <path class="ch-beak" d="M50 47c2.7 0 4.3 1.3 4.3 2.8 0 1.8-1.9 3.2-4.3 3.2s-4.3-1.4-4.3-3.2c0-1.5 1.6-2.8 4.3-2.8z"
            fill="var(--chick-beak)" stroke="var(--chick-line)" stroke-width="1.6"/>
    </g>
${props(speaker)}
    <g class="ch-emote">
      <path class="ch-heart" d="M78 13c2-3 6-1 6 2 0 3-4 5-6 7-2-2-6-4-6-7 0-3 4-5 6-2z"
            fill="#FF8FA3"/>
      <text class="ch-mark" x="75" y="17" font-size="19" font-weight="800"
            fill="#4C8A74">?</text>
    </g>
  </g>
</svg>`;
  }
```

## 5. 함께 고칠 CSS (chatter.css) — 좌표 이동 후속

새 얼굴이 **아래로 내려왔다** (눈 y 30→42, 부리 y 41→50). CSS 세 곳을 확인·수정한다:

1. **`.ch-eye-line` stroke 색** — 표정 곡선의 stroke 는 CSS 에 있다. 현재 `#2b2f3a` 계열이면
   눈동자 색과 같은 **`#2F3B33`** 으로 (두께는 기존 유지).
2. **`.ch-eyes` 깜빡임 원점** — `chBlinkEyes` 가 `scaleY` 를 쓴다. `.ch-eyes` 에
   `transform-box: fill-box; transform-origin: center` 가 **없으면 추가** — 없으면 viewBox 원점
   기준으로 찌그러져 눈이 얼굴 밖으로 튄다 (눈 위치가 내려왔으므로 기존엔 우연히 덜 보였을 수 있다).
3. **`.ch-mark`(물음표) 위치** — 새 머리에 맞춰 x75 y17 로 옮겼다. CSS 가 위치를
   덧입히면(예: translate) 겹침이 없는지 확인.

`--chick-*` 토큰 값 변경은 `02_tokens.md` §3 을 따른다 (4색 몸 → `--chick-body` 별칭 수렴,
`--chick-line`·`--chick-belly`·`--chick-mint` 신설).

## 6. 크기 사다리 검증 기준

렌더 지점별로 이 캐릭터가 살아남아야 하는 크기 (04_screens 체크리스트와 연동):

| 크기 | 지점 | 보여야 하는 것 |
|---|---|---|
| 96-134px | 객석 오버레이 | 전부 — 소품·홍조·새싹·하이라이트 |
| 76px | 리포트 청중 카드 | 소품으로 넷 구분 가능 |
| 56-78px | 등장 의식·커튼콜 | 실루엣 + 소품 윤곽 |
| 38-54px | 무대 실루엣 (`brightness(.34)`) | **실루엣만으로** 새싹·헤드폰·펜이 구분 |
| 46px | 회상 카드 | 얼굴이 읽힘 |

38px 실루엣에서 넷이 구분 안 되면 소품 크기를 키우지 말고 **소품의 바깥 돌출량**을 키운다
(실루엣 테스트는 윤곽 밖으로 나온 모양으로 판가름난다).

## 7. 금지

- 우는 표정 · 눈물 · 처진 눈썹 (눈썹 자체를 그리지 않는다 — 인상이 생긴다)
- 이모지로 캐릭터 대체 (백엔드 톤 규칙 `f12_chatter.py:289` 도 이모지 금지)
- 마리별 다른 체형·다른 몸 색 · 5번째 캐릭터 신설 · 피니/코리 이름 사용
- 소품 3개 이상 (객석 소품은 둘까지 — UI_REDESIGN 하지 말아야 할 것)
