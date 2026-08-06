# 03 — 컴포넌트 스펙

> 원칙: **콘텐츠 영역은 차분하게, 피드백 순간만 귀엽게.** 캐릭터·장식은 여기 명시된
> 컴포넌트에만 넣는다. 표·리스트·판정 칩·숫자는 손대지 않는다.

---

## 1. 카드 — "행정 서류" → "부드러운 노트"

토큰 교체(02_tokens §2)로 radius 는 자동으로 20px 이 된다. 추가로 보더와 그림자를 바꾼다:

```css
/* app.css:137-141 .card 수정 */
.card {
  background: var(--paper);                 /* #FFFFFF — 크림 배경 위 순백 */
  border-radius: var(--r-card);             /* 20px (토큰이 해결) */
  border: 1.5px solid var(--border);        /* #D8EEE3 — 신설 */
  padding: 24px;
  box-shadow: var(--shadow-panel);          /* 0 8px 24px rgba(28,82,61,.08) */
}
```

- 안쪽 작은 카드(`.stat-card`, `.aud-seat`, `details.fold` 등)는 `--r-inner`(16px)를 따른다.
  `.aud-seat` 처럼 `var(--r-print, 4px)` 를 쓰는 곳은 `var(--r-inner)` 로 바꾼다.
- `.resume-card`(검정 면)·`.next-card`(민트 면)는 색 유지, radius 만 자동 추종.
- **날카로운 예외 유지:** 판정 칩(`.chip`)·상태 점(`.dot`)·진행 막대는 지금 그대로 —
  상태 표시는 장식이 아니다.

## 2. 말풍선

앱 층의 `.bubble`(app.css:147-160, 각진 4px)은 그대로 둔다 — Q&A 대화는 콘텐츠 영역(70%)이다.

캐릭터 층의 `.ch-bubble`(chatter.css:286-325)은 이미 완성형이다: 네 모서리가 다른 유기 radius
`20px 22px 20px 24px`, 화자별 크림 배경, 부리 쪽 꼬리, spring 등장. **건드리지 않는다.**
바뀌는 것은 배경 변수 `--bub-*` 값뿐 (02_tokens §3 — 청중 카드 틴트와 공유).

## 3. 역할 pill (신규, 청중 카드용)

```css
.aud-role-pill {
  display: inline-flex; align-items: center;
  padding: 3px 10px; border-radius: var(--r-pill);
  background: rgba(255, 255, 255, .75);      /* 틴트 카드 위 반투명 흰 알약 */
  border: 1px solid var(--border);
  font-size: 11px; font-weight: 750; color: var(--text-2);
}
```
문구는 짧은 명사형: `자료 담당` `듣기 담당` `대조 담당` `인정 담당`.
(긴 역할 설명 "발표를 귀로 들었어요"는 카드 하단 한 줄 평 자리로 이동 — §4)

## 4. 청중 좌석 카드 — 리포트 「청중 반응」 진입 카드 개편

**현재** (`chatter.js:622-636` `entryCardHtml()` + `chatter.css:900-919`): 회색 `--fill` 사각형 4개에
병아리 + 이름 + 모델 + 역할 텍스트가 세로로 쌓임. **레퍼런스 `528b3b8c` 처럼 바꾼다:**

```
┌─────────────────────┐   카드마다 배경 틴트가 다르다 (--bub-*)
│      (발표새 76px)    │   캐릭터 상단, 소품으로 역할이 보인다
│  ｢자료가 좋았어요!｣   │   말풍선 한 줄 — 흰 반투명 알약
│                     │
│  믿:음   [대조 담당]  │   이름(830) + 역할 pill
│  KT 믿:음            │   모델 배지 (11.5px, text-3) — 후원사 표기 유지
└─────────────────────┘
```

```html
<!-- entryCardHtml() 교체 스케치 -->
<li class="aud-seat" data-speaker="midm">
  <span class="aud-chick">${chickSvg('midm')}</span>
  <span class="aud-line">자료랑 발표를 나란히 봤어요!</span>
  <span class="aud-id"><b class="aud-name">믿:음</b><span class="aud-role-pill">대조 담당</span></span>
  <span class="aud-model">KT 믿:음</span>
</li>
```

```css
.aud-seat {
  border-radius: var(--r-inner);
  border: 1.5px solid rgba(255, 255, 255, .9);
  padding: 16px 12px 14px;
  background: var(--seat-tint, var(--fill));
}
.aud-seat[data-speaker="midm"]   { --seat-tint: var(--bub-midm);   }  /* 민트 */
.aud-seat[data-speaker="solar"]  { --seat-tint: var(--bub-solar);  }  /* 노랑 */
.aud-seat[data-speaker="exaone"] { --seat-tint: var(--bub-exaone); }  /* 핑크 */
.aud-seat[data-speaker="ax"]     { --seat-tint: var(--bub-ax);     }  /* 블루 */
.aud-line {
  margin-top: 4px; font-size: 12.5px; font-weight: 650; color: var(--bub-ink);
  background: rgba(255,255,255,.8); border-radius: 12px 14px 12px 4px; padding: 5px 10px;
}
```

`aud-line` 문구 (고정 카피 — LLM 아님, 실제 수다는 객석 오버레이에서):

| 자리 | 한 줄 |
|---|---|
| 믿:음 | 자료랑 발표를 나란히 봤어요! |
| 쏠라 | 슬라이드를 처음부터 끝까지 읽었어요! |
| 엑사원 | 잘 설명한 개념에 도장을 찍었어요! |
| 엑씨 | 한마디도 놓치지 않고 들었어요! |

이모지·`!` 남용 금지 (한 문장에 하나까지). 카드 안 텍스트는 판정이 아니라 **역할 소개**다 —
판정은 객석을 열어야 나온다 (기존 동선 유지).

## 5. 점수 배지 (리포트 헤드)

숫자는 신성하다 — 크기·값 그대로. 형태만 "둥근 배지" 감성을 더한다:

- 점수 숫자(`--t-display` 56px) 옆에 **발표새 소형(52px) 1마리** — mood 는 점수 티어
  (01_character §3). 넷 중 누구를 쓰나 → **엑씨** (발표를 귀로 들은 관객이라 점수 옆에서
  "들었다"고 말할 자격이 있다 — 회상 카드와 같은 논리).
- 막대(`.verdict-dims .bar`) 끝 장식: 채운 끝점에 반지름 3px 흰 점 하나 (별·잎 모양은 7개 막대에서
  소음 — 점 하나가 상한).
- "이번엔 측정할 수 없었던 항목 N개" → 말풍선 톤 문안 (04_screens §2). 개수는 그대로 노출.

## 6. 빈 · 로딩 · 완료 상태 — 캐릭터를 넣는 곳 (이 세 군데**만**)

레퍼런스 `7734c502` 의 문법: 캐릭터 1마리 + 해요체 한 줄 + 행동 버튼.

| 상태 | 위치 (현재) | 새 구성 |
|---|---|---|
| **빈 — 분석 없음** | `app.js:2927-2939` "아직 내 발표 분석이 없어요" 카드 | 발표새 1마리(neutral, 72px) + "아직 발표 자료가 없어요. 첫 번째 발표를 만들어 볼까요?" + 기존 `새 발표 만들기` 버튼 유지 |
| **로딩 — 파이프라인** | `app.js:1908-1917` `pipelineLoadingHtml()` | 진행 바·단계 라벨·경과 초 **전부 유지** (정직 원칙) + 위에 엑씨(헤드폰) 1마리, 문구 "발표를 듣고 있어요…" — 캐릭터는 장식 층, 진행률이 주인공 |
| **빈 — 포스터 벽 첫 방문** | `playbill.js:280-287` "오늘 개관!" | 발표새 1마리(curious) + 기존 문구 유지 |

**오류 상태에는 캐릭터를 넣지 않는다.** 오류는 원인·해결이 주인공이다 (`aud-block.is-failed`
등 기존 그대로). 레퍼런스의 "종이를 거꾸로 든 새"는 후속 아이디어로만 남긴다.

## 7. 컴포넌트 캐릭터화 — 이번 범위 / 후속

| 아이디어 (레퍼런스) | 이번 범위 | 이유 |
|---|---|---|
| 청중 좌석 카드 (§4) | **O** | 캐릭터가 주인공인 유일한 카드 |
| 점수 옆 발표새 (§5) | **O** | 피드백 순간 |
| 빈/로딩 상태 (§6) | **O** | 레퍼런스 문법 그대로 |
| 눈 달린 폴더 (자료함) | 후속 | 업로드 화면은 콘텐츠 영역(70%) — 지금 넣으면 온도 초과 |
| 인증서형 리포트 | 후속 | 리포트 구조 개편이 필요 — 마감 후 |
| 별 배지 로제트 (완료) | 후속 | 커튼콜 연출이 이미 완료 감정을 담당 |

## 8. 모델 회사 로고 — 조건부 슬롯 (기본은 텍스트 배지 유지)

후원사 로고(KT·Upstage·LG·SKT)를 넣을지 검토한 결론:

- **캐릭터 몸·소품에는 넣지 않는다.** 원본 로고는 상표라 귀여운 그림체로 변형하면 브랜드
  가이드 위반이고, 원본 그대로 넣으면 세계관(민트·크림 4색 문법)이 깨진다 — 4사 로고가
  빨강·남색 계열이라 팔레트와 충돌한다.
- **기본은 지금의 텍스트 배지 유지** — 명패(`ch-plate`)와 청중 카드의 `KT 믿:음` /
  `Upstage Solar` / `LG EXAONE` / `SKT A.X` 표기가 이미 후원사 정체성을 전달한다.
- **로고 슬롯 — 정말 필요한 순간에, 작게, 딱 한 곳.** 허가와 원본 에셋을 받으면
  **청중 반응 진입 카드의 `.aud-model` 줄** (후원사 정체성이 실제로 일하는 유일한 순간)
  왼쪽에 **높이 12px, 단색(`grayscale`) 로고**를 넣는다. 조건: ① 이 한 곳뿐 — 명패·헤더·
  커튼콜 등 다른 자리에 늘리지 않는다 ② 원본 비율 유지, 단색 처리 (컬러 원본 금지 — 팔레트
  보호) ③ 캐릭터 몸·소품 금지 ④ 에셋은 `docs/design_improvement/assets/logos/` 에 원본
  그대로 보관. **허가 전에는 구현하지 않는다.**

```html
<!-- 허가 확보 후의 슬롯 예 -->
<span class="aud-model"><img class="aud-logo" src="…" alt="" height="12"> KT 믿:음</span>
```
```css
.aud-logo { height: 12px; width: auto; vertical-align: -1px; opacity: .65; filter: grayscale(1); }
```

## 9. 애니메이션 — 새로 만들지 않는다

기존 27종 keyframes(흔들림·숨쉬기·깜빡임·통통·갸웃…)가 새 캐릭터에 그대로 걸린다.
새 keyframe 이 필요해 보이면 먼저 기존 것을 재사용할 수 없는지 본다. 정말 추가한다면
`chatter.css:934-969` / `theater.css:583-607` 의 reduced-motion 목록에 **반드시 같이 등록**한다.
