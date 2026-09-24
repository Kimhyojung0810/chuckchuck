# 캠 트랙 (devforCAM) — 발표 셀프뷰 · Q&A 오버레이를 메인 플로에서 떼어 키운다 (2026-09-24)

> 사용자 요청(9/24): "발표할 때 발표 화면이 뜨면서 내가 오른쪽 하단에 나와서 실감나게 · QA 할 때는 overlay 로 내 모습이 잘 나오게.
> 정상 작동하는 플로에서 따로 빼서, devforCAM 버전으로 진척도를 확인. 설계 → 우선순위 → 멀티에이전트로 작업 → UI/UX 최적화는 토스·당근 데이터 기반."
> 상위 설계: [qa-cam-overlay.plan.md](qa-cam-overlay.plan.md) (9/22, canvas 합성·디렉터·송출). 이 문서는 그 위에 **트랙 정의·우선순위·디자인 규칙·진척도**를 얹는다.

## 0. 한 문장

**캠 트랙의 집은 `booth.html` 이다.** 메인 앱(`index.html`·`app.js`)은 실 API 로 정상 운용 중인 플로라 한 줄도 안 건드린다(헌장 §0).
두 요청은 이미 `booth.html` 의 **발표 모드**(자료 메인 + 내 모습 우하단 작은 창)와 **통화 모드**(내 모습 메인 + 삐약이 질문 오버레이)로 구현돼 있다.
남은 일은 (1) 토스·당근 규칙으로 UI/UX 를 조이고 (2) 오버레이 상태를 한 덩어리로 빼서 (3) canvas 합성·디렉터·송출로 가는 길을 여는 것이다.

## 1. 트랙 정의 — 무엇이 분리돼 있나

| | 메인 플로 (건드리지 않음) | 캠 트랙 (여기서 키움) |
|---|---|---|
| 입구 | `index.html` → `#/new` → `#/qa` → `#/report` | `booth.html` (찍기 → 분석 → **발표 모드** → **통화 모드** → 결과) |
| 코드 | `js/app.js` · `js/qa_live.js` | `js/booth.js` · `js/booth_logic.js`(순수) · `css/booth.css` · `booth.html` (+ 새 파일은 `booth_*.js`) |
| 카메라 | 없음 (마이크만) | `openSelfView()` 앞카메라 1280×720 거울 · `data-main` 으로 메인/작은 창 교체 |
| 검증 | `labs/app_flow` (실 API 실흐름) | `labs/qa_call` (헤드리스 크롬 + 가짜 카메라, 단계별 사진) · `tests/js/booth.smoke.mjs` |
| 진척도 | — | 이 문서 §6 표 + `labs/qa_call/out/<stamp>/` 사진 |

브리지는 같은 것을 쓴다(`/api/v1/*`). 트랙을 나누는 것은 **화면과 파일**이지 서버가 아니다.

## 2. 지금 상태 (2026-09-23 16:00 실험실 사진 기준)

| 화면 | 되어 있는 것 | 사진 |
|---|---|---|
| 발표 모드 | 자료가 프레임을 채우고 내 모습이 **우하단 176px 작은 창**(거울). 시계 · 계기 · 삐약이 실시간 말하기 지적(7종) · 작은 창 누르면 자리 바꿈 · Document PiP | `3_present.png` · `3c_present_swapped.png` |
| 통화 모드 | 내 모습이 프레임을 채우고, 왼쪽 아래 삐약이 타일 + 글라스 말풍선(질문·답·판정·되묻기) · 자막 띠 · 자동 대화(침묵 2.5초 → 카운트다운) · 자료가 우하단 작은 창 | `3_call_ask.png` · `4_call_answer.png` |
| 안 된 것 | 오버레이가 DOM 이라 화상 앱(Zoom/Meet)으로 못 나감 · 상태가 `bubble()/setPhase()` 에 흩어져 있음 · 디자인 언어가 글라스(③)·극장(②) 혼재 · 실제 마이크·TTS 는 이 서버에서 못 봄 | — |

## 3. 디자인 규칙 — 토스·당근 데이터에서 가져온 것만

원칙은 하나다. **토스는 "지우는 규율", 당근은 "따뜻한 형태와 역할 토큰".** 색·토큰 값은 우리 것(`app.css :root`, [design_improvement/02_tokens.md](../design_improvement/02_tokens.md))을 쓰고, 아래는 **배치·타이포·터치·모션·문구 규칙**이다.

### 3-1. 토스에서 (프로덕트 원칙 · UX Writing · 오류 문구 시스템)

| 규칙 | 출처 | 캠 트랙 적용 |
|---|---|---|
| **One Thing Per Page** — 한 화면 한 메시지 | 토스 프로덕트 원칙 | 발표 모드의 주인공은 **자료**, 통화 모드의 주인공은 **내 얼굴**. 나머지는 한 겹만 얹는다. 동시에 뜨는 말풍선은 최대 2개(질문 + 내 답). |
| **Easy to Answer** — 3초 안에 이해 | 〃 | 질문 말풍선은 2줄(≈ 60자) 안. 넘치면 어절 타이핑으로 흘린다. 판정은 pill 한 단어 + 한 줄 요약. |
| **Tap & Scroll** — 가로 스와이프 금지 | 〃 | 슬라이드 넘김은 버튼(이전/다음)과 음성 명령만. 드래그 이동 없음. |
| **No More Loading** | 〃 | 질문은 사전 생성. 판정 대기(1.6초)는 삐약이 "생각하는 중" 상태로 보인다. 스피너 금지. |
| **Sleek** — 무의식적 상호작용 | 〃 | 작은 창 교체는 200ms 이하 전환, 카운트다운은 숫자만. |
| 해요체 · 능동형 · 긍정형 · `{명사}+{명사}` 풀어쓰기 | CLAUDE.md §3-1 (TDS ux-writing) | 모든 오버레이·버튼·상태 문구. |
| **Navigating error** — 무슨 일 / 왜 / 이제 뭘 | 토스 오류 문구 시스템 | 카메라·마이크·판정 실패 문구 전부 3요소. "카메라를 못 열었어요. 다른 앱이 쓰고 있어요. 그 앱을 닫고 「카메라 켜기」를 눌러요." |
| 다이얼로그 왼쪽은 `닫기` · CTA 만 보고 다음 행동이 예측돼야 | TDS components | 「통화 마치기」「질문 받기」처럼 동사로 끝낸다. "확인" 금지. |

### 3-2. 당근에서 (SEED 파운데이션)

| 규칙 | 출처 | 캠 트랙 적용 |
|---|---|---|
| **색 역할 3종 `fg / bg / stroke`** — 같은 단계는 같은 대비 | SEED color | 오버레이 CSS 변수를 역할로 이름 짓는다: `--ov-bg`(글라스 어두운 면) `--ov-fg`(흰 글자) `--ov-stroke`(얇은 반사 테두리) `--ov-accent`(브랜드). 영상 위 글자는 **항상 `--ov-bg` 위에** 둔다(맨 픽셀 위 텍스트 금지). |
| **타이포 스케일 t1~t14** (11~48px, 400/500/700) | SEED typography | 오버레이 텍스트는 3단만: 질문 **t7 20px/700**, 자막·내 답 **t5 16px/500**, 상태·라벨 **t3 13px/500**. 폰은 한 단씩 내린다. rem 기반. |
| **터치 타깃 `targetSize` 명시** | SEED accessibility | 영상 위 버튼은 최소 **44×44** (폰 48). 작은 창(교체 버튼)도 44 이상. |
| **눌리면 살짝 눌렸다 돌아온다** (compress feedback) | SEED motion | 조작줄 버튼 `:active { transform: scale(.96) }` 120ms. `prefers-reduced-motion` 이면 끔. |
| **둥근 형태 + 정제된 모서리** | SEED shape | 말풍선 radius 는 우리 토큰 `--r-inner 16px`, 캡슐 버튼 `--r-pill`. 4px 각진 것 금지. |
| **접근성은 기본값** — 포커스 상태·키보드 | SEED a11y | 영상 위 모든 버튼에 `:focus-visible` 2.5px 브랜드 외곽선(이미 `.call-stage` 에 있음 → 버튼까지). 오버레이 문장은 `aria-live` 에 같은 문장. |
| 다크 면 위 층 대비 조정 | SEED dark mode | 영상(어두울 수 있음) 위 글라스는 `--ov-bg` 알파를 .46 → **.56** 로 올려 밝은 얼굴·어두운 방 둘 다에서 4.5:1 을 지킨다. |

### 3-3. 우리 규칙과의 우선순위

1. **판정 색 5종·숫자는 불변** (UI_REDESIGN §14, CLAUDE.md §3-3).
2. 부스 통화 화면의 **글라스(③)는 조작줄·도구줄에만** (9/22 회의안 1-1 추천안 A). 프레임 안 말풍선은 9/25 회의 결정 전까지 현재 글라스를 유지하되, 위 `--ov-*` 역할 변수로만 그린다 — 결정이 나면 변수 값만 바꾼다.
3. 얼굴을 가리지 않는다 — 말풍선은 왼쪽 60%(폰 70%), 작은 창은 우하단, 자막은 하단 띠 (9/22 회의안 1-2 추천안 A).

## 4. 우선순위

| 순위 | 일 | 왜 이 순서인가 | 파일 | 완료 기준 | 담당 |
|---|---|---|---|---|---|
| **P0-1** | 토스·당근 규칙으로 발표 모드·통화 모드 **UI/UX 조이기** — 역할 변수 `--ov-*`, 타이포 3단, 터치 44/48, 눌림 모션, 포커스, 알파 .56, 말풍선 2줄 상한 | 지금 화면을 바로 좋게 만들고, 뒤의 canvas 합성이 같은 규칙을 물려받는다 | `booth.css` · `booth.html` · `booth.js`(클래스만) | 실험실 사진 8장에서 규칙 위반 0 · 콘솔 오류 0 · 스모크 통과 | opus |
| **P0-2** | **문구 전수 점검** — 해요체·능동·3요소 오류 문구·CTA 동사화 | 문구는 되돌리기 쉽고 효과가 바로 보인다 | `booth_logic.js`(cameraErrorText 등) · `booth.js` 문자열 · `booth.html` | 문구 목록 표 + 스모크 케이스(오류 문구 3요소) | haiku → opus 가 반영 |
| **P0-3** | **오버레이 상태 한 덩어리** — `booth_overlay_state.js`(순수) `{mode, main, phase, question, speaker, mood, caption, verdict, handRaised}` → 렌더 함수 하나. `bubble()/setPhase()/setMain()` 이 상태를 갱신하고 렌더가 DOM 을 만진다 | canvas 합성(P1)의 전제. 겉모습 변화 없이 구조만 | `booth_overlay_state.js`(새) · `booth.js` | 스모크에 상태 전이 케이스 ≥ 8 · 실험실 사진이 P0-1 결과와 같음 | opus |
| P1 | canvas compositor (`booth_stage.js`) — qa-cam-overlay §6 #2 | 9/25 회의(디자인 언어) 뒤 | 새 파일 | 가짜 카메라 사진에 질문이 **픽셀 안에** · rAF < 8ms | sonnet |
| P2 | 디렉터(개념 매칭·손 들기·타이밍) + 화자 배정 — §6 #3·#4 | 질문 타이밍의 실감. 마이크 실측 필요 | `booth_director.js`(새) | 받아쓰기 시퀀스 → 기대 시점에 질문 | sonnet |
| P3 | `?cast=1` + BroadcastChannel + OBS — §6 #5·#6 | 결선(11월) 시그니처 후보. Festa 범위는 팀 결정(§8-1) | `booth.js` · 문서 | 부스 컴퓨터에서만 확인 가능 | sonnet |

**이번 세션은 P0-1 ~ P0-3.** P1 이후는 9/25 정기회의 결정(9/22 회의안 §1) 뒤에 연다.

## 5. 멀티에이전트 셋팅

```
1단계 (병렬, 읽기 전용)
  A1 ui-audit  (sonnet) booth.html/css/js 를 §3 규칙으로 감사 → docs/plan/cam-track-audit.md §A (file:line · 규칙 · 고칠 값)
  A2 copy-audit (haiku) 문구 전수 → 같은 파일 §B (지금 문구 · 바꿀 문구 · 규칙)
2단계 (직렬, 파일 소유자 1명)
  B  implement (opus)  감사 결과로 P0-1 → P0-2 → P0-3 구현. booth.* 만. 스모크 갱신. booth.html ?v= 올림
3단계 (병렬)
  C1 lab-verify (sonnet) labs/qa_call run.py all --base :8799 (실 API) → 사진 8장 눈으로 검사 · report.json 콘솔 오류 · §3 체크리스트
  C2 code-review (code-reviewer) diff 검토 — 회귀·접근성·불변 규칙(판정색·숫자)
4단계 (직렬)
  B' fix (opus, 최대 2바퀴) → 사람(이 세션) scripts/chk gate → 커밋 → 이 문서 §6 갱신
```

파일 경계: 1단계·3단계는 쓰지 않는다. 2·4단계만 쓰고, `app.js`·`index.html`·`chatter.*` 는 금지. 실 API 는 3단계 1회 + 4단계 바퀴마다 1회.

## 6. 진척도

| 항목 | 상태 | 증거 |
|---|---|---|
| 발표 모드 — 자료 메인 + 내 모습 우하단 | ✅ 구현 (9/23) | `labs/qa_call/out/20260923T160056/3_present.png` |
| 통화 모드 — 내 모습 메인 + 질문 오버레이 | ✅ 구현 (9/18) | `…/3_call_ask.png` `4_call_answer.png` |
| 가짜 카메라 파이프라인 | ✅ 검증 (9/24) | 1280×720 30fps 트랙, 프레임 차 감지, 콘솔 오류 0 |
| P0-1 UI/UX 규칙 적용 | ✅ 구현·검증 (9/24) | `labs/qa_call/out/20260924T180123/`(데스크톱 8단계) · `20260924T180219_mobile/`(폰) 콘솔 오류 0 · 얼굴 가운데 안 가림(데스크톱·폰) · 코드 리뷰 APPROVE · gate 초록 · `booth.css` `--ov-*` 역할 변수·알파 .56·타이포 20/16/13(폰 18/15/12)·버튼 44(폰 48)·눌림 .96·포커스 2.5px·질문 2줄+어절 흘려 쓰기·옛 풍선 옅게(.is-older)·작은 창 16:9 · 숨은 「다시 답하기」「다음 질문」 노출 버그 수정 · 고침 1바퀴(9/24 실 API 사진): 말풍선 열 상한 42%(폰 36%, 데스크톱 통화는 무대 절반 아래로), 판정 요약·빠진 것·힌트·정답 요지 2줄 + 눌러 펼치기, 옛 풍선은 한 줄로 접기(.8) · 고침 2바퀴: 폰 통화는 삐약이를 한 줄 아바타(44px)로 줄이고 자료 작은 창을 오른쪽 위로 — 열 꼭대기가 무대 49.5% 아래라 얼굴 가운데(≈40%)가 비는 걸 가짜 응답 실험에서 쟀다, 판정이 열보다 크면 pill·요약부터 보인다 · 펼칠 수 있는 풍선은 키보드로도(tabindex·role=button·aria-expanded, Enter/Space) |
| P0-2 문구 점검 | ✅ 구현·검증 (9/24) | 「주세요/누르세요」 0 · 카메라 오류 3요소(`cameraErrorText`) · 통화 중 내 모습 오류 `selfViewErrorText` 분리 · 스모크 「3요소」 케이스 |
| P0-3 오버레이 상태 분리 | ✅ 구현·검증 (9/24) | `js/booth_overlay_state.js`(순수 전이 + `renderOverlay`) · setMode/setMain/setPhase 는 껍질 · 스모크 상태 전이 9 케이스 · 겉모습 변화 없음(상태 값 P0-1 과 동일) |
| P1 canvas 합성 | ⬜ 9/25 회의 뒤 | |
| P2 디렉터·화자 배정 | ⬜ | |
| P3 송출(OBS) | ⬜ 팀 결정 | |
| 실제 마이크·TTS·부스 웹캠 문턱 | ⬜ 부스 리허설 | booth-screen-qa §6-2 |

## 7. 출처

- 토스 프로덕트 원칙 (Simplicity · One Thing Per Page · Easy to Answer · Tap & Scroll · No More Loading · Sleek): https://brunch.co.kr/@figmaster/8
- 토스 오류 문구 시스템 (Navigating error · 무슨 일/왜/이제 뭘 · 해요체): https://toss.tech/article/introducing-toss-error-message-system
- 토스 UX Writing: https://toss.im/tossfeed/article/uxwriter-interview · CLAUDE.md §3-1
- 당근 SEED 디자인 토큰 (scale/semantic 2층 · fg/bg/stroke): https://seed-design.io/docs/foundation/design-token
- 당근 SEED 타이포 (t1~t14 · 400/500/700 · rem): https://seed-design.io/docs/foundation/typography
- 당근 SEED 진화 (역할 색 · targetSize · 눌림 피드백 · 접근성 기본): https://seed-design.io/updates/how-seed-evolved
