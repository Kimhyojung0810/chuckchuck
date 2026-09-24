# 캠 트랙 UI/UX 감사 — §3 토스·당근 규칙 대조 (A1 ui-audit)

> 대상: `demo/YEHS_demo/booth.html` · `css/booth.css` · `js/booth.js` (발표 모드 · 통화 모드).
> 기준: [`cam-track.plan.md`](cam-track.plan.md) §3 (규칙 표) · §4 P0-1 (완료 기준: 실험실 사진 8장에서 규칙 위반 0).
> 근거 사진: `labs/qa_call/out/20260923T160056/{3_present,3c_present_swapped,3d_present_meter,3_call_ask,4_call_answer}.png` · `labs/qa_call/out/20260923T011424_mobile/{3b_present_tell,3c_present_swapped}.png` (390×844, DPR 2).
> 읽기 전용 감사다. 이 문서 하나만 쓰고 다른 파일은 고치지 않았다.

## 요약

지금 화면은 **레이아웃 규율**(무대 둘·작은 창·조작줄 분리)은 §3-3(얼굴/자료를 안 가린다)를 대체로 지키지만, **토큰·타이포·터치·모션 규칙은 대부분 아직 적용 전**이다. 가장 눈에 띄는 셋: (1) `--ov-bg/--ov-fg/--ov-stroke/--ov-accent` 역할 변수가 코드 어디에도 없고 `--glass-dark` 알파가 계획서가 올리기로 한 `.56`이 아니라 여전히 `.46`이다. (2) 영상 위 버튼 높이가 32px(발표·통화 공통 도구줄)·30px(폰)·42px(폰 조작줄)로 44/48 기준에 못 미치는 곳이 다섯 군데다. (3) 질문·판정 말풍선에 2줄 상한·타이핑 오버플로가 없고, 실제로 스크린샷 3장(`3b_present_tell` 모바일·`3c_present_swapped`·`4_call_answer`)에서 말풍선이 **동시에 3개** 떠 있는 게 확인된다 — "One Thing Per Page / 최대 2개" 위반이 사진으로 남아 있다. 판정 문구도 "pill + 한 줄"이 아니라 요약·빠진 것 목록·되묻기가 한 풍선에 다 들어가 화면을 채운다. 반대로 포커스 표시(`.call-stage`)·판정 색 불변·타이포 t3(13px) 몇 곳은 이미 규칙과 일치한다.

## 표 A — 위반·개선 항목

| # | 화면 | 규칙(§3) | 지금(file:line + 현재 값) | 바꿀 값 | 우선순위 |
|---|---|---|---|---|---|
| 1 | 공통 | 색 역할 3종 `fg/bg/stroke`(당근 SEED color) | `--ov-bg/--ov-fg/--ov-stroke/--ov-accent`가 코드 어디에도 없다. 오버레이는 전부 `demo/YEHS_demo/css/booth.css:147-153`의 `--glass-dark/--glass-light/--glass-brand/--glass-edge`로 직접 그린다 (예: `booth.css:172,176,188,227,240,304-305,308,329,340,346,348,356,366` 전부 `var(--glass-dark)`/`var(--glass-light)`/`var(--glass-brand)` 직접 참조). | `.call { --ov-bg: var(--glass-dark); --ov-fg: #fff; --ov-stroke: var(--glass-edge); --ov-accent: var(--glass-brand); }` 로 역할 이름을 얹고, 위 참조 지점을 `var(--ov-bg)` 등으로 바꾼다. 값은 그대로 두고 이름만 역할로 — 9/25 결정 뒤 값만 바꾸면 되게(§3-3-2). | 높 |
| 2 | 통화 | 다크 면 위 층 대비 — 알파 `.46 → .56` (당근 SEED dark mode) | `booth.css:149` `--glass-dark: rgba(16, 20, 32, .46);` — 계획서(§3-2 표)가 명시한 `.56`으로 아직 안 올라갔다. | `--glass-dark: rgba(16, 20, 32, .56);`로 값 하나만 변경. `@supports not (backdrop-filter…)`(`booth.css:206,209`)의 `.9` 폴백은 그대로 둔다. | 높 |
| 3 | 발표+통화 공통 | 터치 타깃 44×44(폰 48) | `booth.css:176` `.call-topbar .btn { height: 32px; … }` — 계기/자동대화/카메라/PiP 버튼 4~5개가 전부 32px. | `height: 44px;`로. 패딩 `0 14px`쯤으로 같이 늘려 원형 비율 유지. | 높 |
| 4 | 발표+통화 공통(폰) | 터치 타깃 폰 48 | `booth.css:181` (`@media max-width:640px`) `.call-topbar .btn { height: 30px; … }` — 데스크톱보다도 더 작아진다. 폰 스크린샷(`3b_present_tell` 모바일)에서 실측: 표시 이미지 780px폭이 DPR2 스케일이라 실제 CSS 높이는 규칙 미달. | `height: 48px;`로. 가로 공간이 부족하면 아이콘만 남기거나 2줄 배치(이미 2줄로 wrap 중이므로 높이만 올리면 됨). | 높 |
| 5 | 통화(폰) | 터치 타깃 폰 48 | `booth.css:387` (`@media max-width:640px`) `.call-controls .btn { flex: 1 1 auto; height: 42px; padding: 0 12px; }` — 데스크톱 44px(`booth.css:356`)보다도 **더 줄어든다**. 답하기·힌트·모르겠어요·질문 받기 등 QA 핵심 버튼. | `height: 48px;`로. | 높 |
| 6 | 발표(계기) | 터치 타깃 44×44 | `booth.css:196` `.call-meter-row .btn { height: 30px; padding: 0 10px; font-size: 12px; … }` — 기준 맞추기/기본값으로 버튼. 운영자 전용이지만 영상 위 버튼 규칙은 예외를 두지 않는다. | `height: 44px;`로. | 중 |
| 7 | 통화(폰) | 터치 타깃 폰 48 | `booth.css:348,350` `.call-dock-row > .booth-mic { height: 44px; … }` / `.call-dock-row > .call-leave { height: 44px; … }` — 데스크톱 기준은 맞지만 `@media max-width:640px`(`booth.css:368-389`)에 이 두 선택자의 height 오버라이드가 없어 폰에서도 44px 그대로다. | `@media (max-width:640px)` 블록 안에 `.call-dock-row > .booth-mic, .call-dock-row > .call-leave { height: 48px; }` 추가. | 중 |
| 8 | 공통 | 눌림 피드백 `scale(.96)` 120ms + `prefers-reduced-motion` 끔 | `demo/YEHS_demo/css/app.css:198` `.btn:active { transform: scale(.97); }` — 값이 `.97`이고(`.96` 아님), `prefers-reduced-motion: reduce` 가드가 전혀 없다(app.css 안의 reduced-motion 블록 13곳 중 이 규칙은 없음, grep 확인). `booth.css:360` `.call-controls .btn:active { transform: scale(.97); }`도 같은 값으로 중복. | `app.css:198`을 `transform: scale(.96)`로, `transition`(`app.css:195`)에 `120ms` 명시. 바로 아래에 `@media (prefers-reduced-motion: reduce) { .btn:active { transform: none; } }` 추가. `booth.css:360`은 지우고 전역 규칙에 맡긴다(중복 제거). | 높 |
| 9 | 공통 | 접근성 기본값 — 영상 위 모든 버튼에 `:focus-visible` 2.5px 브랜드 (이미 `.call-stage`에 있음 → 버튼까지) | `booth.css:220` `.call-stage:focus-visible { outline: 2.5px solid var(--brand); outline-offset: -2.5px; }` 만 2.5px. 도구줄·조작줄 버튼(`.call-topbar .btn`·`.call-controls .btn`·`.booth-mic`·`.call-leave`)은 전역 `app.css:200` `.btn:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }`를 그대로 물려받아 2px다. | `.call .btn:focus-visible, .call-stage:focus-visible { outline: 2.5px solid var(--brand); }`로 통화 프레임 안 버튼만 2.5px로 올린다(전역 `.btn`은 건드리지 않는다 — 앱 화면 회귀 방지). | 중 |
| 10 | 통화 | 타이포 3단 — 질문 t7 20px/700 | `booth.css:310` `.call-bubble .call-q { font-size: 17px; font-weight: 700; … }` — 실제 질문 말풍선은 17px다. `booth.css:77` `.booth-question { font-size: 20px; font-weight: 700; … }`은 20/700로 정의돼 있지만 통화 중 질문에는 안 쓰이고 `qa-done`(통화 종료 카드 제목)에만 쓰인다. | `.call-bubble .call-q { font-size: 20px; font-weight: 700; }`로 올린다(`--t-h1: 24px`와 헷갈리지 않게 리터럴 20px 유지, rem 전환은 §3-2 rem 원칙에 맞춰 `1.25rem`으로). | 중 |
| 11 | 통화 | 타이포 3단 — 자막·내 답 t5 16px/500 | 세 곳이 제각각이다: `booth.css:287` `.call-bubble { … font-size: 15px; …}`(판정/답 풍선 본문), `booth.css:328` `.call-caption textarea { … font-size: 17px; …}`(Q&A 자막 입력), `booth.css:340` `.call-live { … font-size: 17px; …}`(발표 실시간 자막). | 세 곳 모두 `font-size: 16px; font-weight: 500;`로 통일(rem 기준이면 `1rem`). | 중 |
| 12 | 통화(발표) | Easy to Answer — 질문 2줄(≈60자) 상한, 넘치면 어절 타이핑 | `js/booth.js:544-556`(`bubble()`)이 `el.innerHTML = html`로 **즉시 전체 삽입**한다. `js/booth.js:559-566`(`renderQuestion()`)도 같은 방식 — 줄 수 제한·타이핑 로직이 전혀 없다. CSS에도 `-webkit-line-clamp` 등 2줄 상한이 없다(booth.css 전체에 `line-clamp` 0건). | `.call-bubble .call-q`에 `display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;` 추가하고, 60자 넘는 질문은 `renderQuestion()`에서 어절 단위 `setTimeout` 타이핑으로 채워 넣는다(booth_logic.js 쪽 순수 함수로 분리 가능). | 높 |
| 13 | 통화 | 판정은 pill 한 단어 + 한 줄 요약 | `js/booth.js:629-638`(`renderJudgement()`) — `<span class="booth-pill">…</span><p>${b.text}</p>${missing}${tail}`로 pill + 요약 + 빠진 것 목록(`<ul>`) + 되묻기/설명을 **한 풍선에 전부** 채운다. `4_call_answer.png` 스크린샷에서 이 한 풍선이 화면 절반 가까이 차지하는 게 실측된다. 주석(`booth.js:632`)은 "풍선 개수를 안 늘리려고" 한 것이라 의도는 있으나 내용 길이 규칙과 충돌한다. | pill + 한 줄 요약만 기본으로 보여주고, `missing`/`tail`은 "더 보기" 토글이나 별도의 얇은 줄(`call-explain`)로 접어 둔다. 최소한 `b.text`를 요약 1문장으로 줄이는 룰(문장 분리 후 첫 문장만)이라도 넣는다. | 높 |
| 14 | 발표+통화 | One Thing Per Page — 동시에 뜨는 말풍선 최대 2개 | 실측 위반 3건: (a) `labs/qa_call/out/20260923T011424_mobile/3b_present_tell.png` — 발표 지적 풍선 3개("발표해 봐요…" · "「어」「음」이 자주 들려요" · "몸이 많이 움직여요") 동시 표시. (b) `.../20260923T160056/3c_present_swapped.png` — 데스크톱에서도 동일 3개 동시 표시. (c) `.../20260923T160056/4_call_answer.png` — 질문 풍선 + 내 답(초록) + 판정 풍선 3개 동시 표시. `booth.css:269-284`(`.call-log`/`.call-bubbles`)에 표시 개수를 2개로 제한하는 로직이 없다 — `overflow-y:auto`와 위쪽 페이드(mask-image, `booth.css:282-283`)만 있어 화면 높이가 허용하는 만큼 다 보인다. `js/booth.js:544-556`(`bubble()`)도 개수 제한 없이 계속 append한다(80개 넘으면만 pop, `booth.js:553`). | `bubble()` 호출 뒤 "가장 오래된 것부터 옅게/숨김" 처리: 최신 2개(질문/지적 + 내 답 또는 직전 지적)만 `opacity:1`, 그 이전은 `.call-bubbles`에 남기되 `opacity:.35` 이하로 낮추거나 `max-height`로 접는다. 최소 수정은 `.call-bubble:not(.is-latest):nth-last-child(n+3) { opacity: .3; }` 같은 CSS 한 줄. | 높 |
| 15 | 발표(작은 창) | 얼굴/자료를 가리지 않는다 (9/22 회의안 1-2) — PiP 프레이밍 | `booth.css:217` `.call[data-main="self"] .call-slides, .call[data-main="slides"] .call-self { … width: var(--pip-w, 176px); aspect-ratio: 16 / 10; … }` — 작은 창 비율이 16:10인데 `js/booth.js:513` `getUserMedia({ video: { … width:{ideal:1280}, height:{ideal:720} } })`은 16:9다. `object-fit:cover`(`booth.css:222`)가 위아래를 잘라내 얼굴 상단/턱이 잘릴 여지가 있다. | `--pip-w`와 짝인 aspect-ratio를 `16/9`로 맞추거나, 카메라 요청 해상도를 `1280×800`(16:10)으로 바꾼다. 자료(슬라이드) 쪽은 `object-fit:contain`(`booth.css:225`)이라 이 문제가 없다 — self 타일만 해당. | 낮 |
| 16 | 통화 | 접근성 — `aria-live`에 오버레이와 같은 문장 | `booth.html`에서 `aria-live="polite"`가 있는 곳은 `#shots`(51행)·`#call-bubbles`(144행)·`#qa-mic-note`(151행) 뿐. 발표 중 실시간 자막 `#present-caption`(153행, `.call-live`)과 상대 상태 `#call-partner-status`(141행), 계기 안내 `#meter-note`(130행)에는 `aria-live`가 없다. | `#present-caption`은 업데이트가 잦아 `aria-live="off"`로 명시(의도적 제외 표시)하고, `#call-partner-status`·`#meter-note`에는 `aria-live="polite"`를 추가한다. | 낮 |
| 17 | 통화 | 둥근 형태·정제된 모서리 — `--r-inner`/`--r-pill` 밖의 값 금지 | `booth.css:287` `.call-bubble { … border-radius: 18px; …}`, `booth.css:292-296`(꼬리) `border-radius: 0 0 0 2px`, `booth.css:300-301` `border-bottom-left-radius: 18px` — 토큰(`--r-inner:16px`/`--r-pill:999px`, `app.css:66-70`)에 없는 리터럴 18px·2px·6px(`booth.css:300-301`)가 여러 곳. | 18px→`var(--r-inner)`(16px)로 통일하거나, 말풍선 전용 반경이 필요하면 `--r-bubble:18px` 토큰을 새로 선언해 리터럴을 없앤다(값 자체를 바꾸자는 게 아니라 이름을 붙이자는 것). | 낮 |

## 표 B — 규칙을 이미 지키는 것

| # | 근거 file:line | 지키는 규칙 |
|---|---|---|
| 1 | `booth.css:336` `.call-mic-note { … font-size: 13px; … }` | 타이포 3단 중 상태·라벨 t3(13px/500)에 이미 일치 |
| 2 | `booth.css:311` `.call-bubble .call-why { font-size: 13px; color: var(--text-2); }` | 동일 t3(13px) 일치 |
| 3 | `booth.css:220` `.call-stage:focus-visible { outline: 2.5px solid var(--brand); outline-offset: -2.5px; }` | 접근성 기본값(포커스 표시)이 무대 전환 버튼에는 이미 있음 — §A9의 확장 대상 |
| 4 | `booth.css:166` `.call[hidden] { display: none; }` (주석: "display:flex 가 [hidden] 을 이겨서…") | "연출이 데이터를 가리면 연출을 버린다"의 실사례 — 숨김 규칙을 명시적으로 다시 잡아둔 이력 |
| 5 | `booth.html:144` `<div class="call-bubbles" id="call-bubbles" aria-live="polite">` | 접근성 — 오버레이 대화 로그에 aria-live 적용 |
| 6 | `booth.css:92-95` `.booth-pill[data-v="good|partial|wrong|unknown"]` → `var(--ok/--mid/--no/--fill)` 참조 | 판정 색 5종 불변 규칙(CLAUDE.md §3-3, plan §3-3-1)을 그대로 따름 — 리터럴 색 없음 |
| 7 | `booth.css:240` `.call-partner { … border-radius: var(--r-inner, 16px); … }` | 토큰(`--r-inner`) 사용 사례 — §A17에서 지적한 리터럴 18px과 대비되는 모범 사례 |
| 8 | `booth.js:463-473`(`setMain`/`tapStage`) | "작은 창을 누르면 자리가 바뀐다 · 메인을 누르는 건 아무 일도 아니다"(Tap & Scroll의 "예측 가능한 탭"과 일치, 드래그 이동 없음) |

## 위험 — 바꾸면 깨질 수 있는 것

`labs/qa_call/run.py`가 실제로 의존하는 선택자·속성·전역(스모크가 이걸로 통과/실패를 가른다). **아래는 이름을 그대로 유지해야 한다(MUST-KEEP)** — 클래스명·id·data attribute 값 중 하나라도 바뀌면 실 API 실험실 검증(`labs/qa_call/run.py all`)이 깨진다.

| 항목 | run.py 사용처 | 비고 |
|---|---|---|
| `#file-shots`, `.booth-shot` | 39행, 90행 | 담기 단계 |
| `#btn-go`, `#step-progress`(`[hidden]`), `#call`(`[hidden]`), `#progress-error(-text)` | 97-106행 | 분석 진입 게이트 |
| `#stages li[data-stage]`, `.st-time` | 107행 | 진행 표시 |
| `window.boothLab.feed(...)` (전역 JS API) | 117-131행 | 헤드리스에서 마이크 대신 말/움직임을 주입하는 유일한 통로 |
| `#call[data-mode="present"]`, `#call[data-main]` | 114행, 138행, 142행, 165행 | **`setMode()`/`setMain()`이 쓰는 값 자체(`present`/`qa`, `slides`/`self`)를 바꾸면 안 됨** |
| `.call-bubble.is-tell` (개수 ≥2, ≥3 로 대기) | 121행, 133행 | `is-tell` 클래스명 고정 |
| `#call-partner-seat[data-tell="awkward"]`, `[data-mood]`, `#call-partner-status` | 122행, 125-127행 | 지적 표정 트리거 값 `"awkward"` 고정 |
| `#call-self`, `#call-slides` (클릭 대상) | 137행, 141행 | `tapStage()`가 매핑하는 id |
| `#btn-meter`, `#call-meter`(`[hidden]`), `#meter-read`(텍스트에 `"기준"` 포함 검사) | 144-150행 | "기준"이라는 한글 문구 자체가 검사 대상 — 카피를 바꾸면 `AssertionError` |
| `#btn-ask`, `.call-bubble.is-question` | 159-161행 | |
| `#call-self[data-camera]`, `#btn-mic[data-state]`, `#qa-count` | 164-166행 | |
| `#qa-answer`(값 채우기), `#btn-answer` | 171-172행 | |
| `.call-bubble.is-verdict[data-v]`, `.call-bubble.is-error` | 173행, 176행 | |
| `#call-bubbles` 안의 `.is-verdict/.is-question/.is-answer/.is-me.is-latest/.is-partner.is-latest` 개수가 **정확히 1개씩** + `scrollHeight > clientHeight` | 178-186행 | **표 A #14의 "오래된 풍선 옅게/접기" 수정이 이 카운트 자체(class 존재 여부)를 건드리면 안 된다** — 옅게 하는 건 opacity/CSS만, DOM에서 지우거나 클래스를 빼면 이 assert가 깨진다 |
| `#btn-hint`(disabled 여부), `.call-bubble.is-hint` | 192-197행 | |
| `#btn-next`, `#btn-giveup`, `.call-bubble.is-verdict .call-explain`, `.call-bubble.is-error` | 203-212행 | |
| `#btn-leave`, `#qa-done`(`[hidden]`), `#qa-tally li` | 220-224행 | |
| `document.querySelectorAll('#call-log .call-bubble')` (className, `dataset.v`, `innerText`) | 65-68행, 219행 | `report.json`의 `bubbles` 필드 — 클래스명 규칙(`is-partner`/`is-me`/`is-latest`/`is-tell`/`is-question`/`is-verdict`/`is-hint`/`is-giveup`/`is-error`) 전체가 여기 걸림 |

추가로 CSS 쪽 구조 의존:

- **`--dock-h` / `ResizeObserver`** — `js/booth.js:476-483`(`watchDock()`)가 `#call-dock`의 높이를 재서 `#call`에 `--dock-h`를 쓴다. `booth.css:217` `.call[data-main=…] … { bottom: calc(var(--dock-h, 132px) + 10px); }`가 이 값을 그대로 쓴다. `#call-dock`의 id나 구조를 바꾸면 작은 창이 조작줄과 겹친다.
- **`data-main` 스왑** — `booth.css:215-218`의 CSS가 `data-main="self"|"slides"` 두 값만 안다. 표 A #1(역할 변수화)·#15(PiP 비율)를 고치면서 이 두 값이나 선택자 구조(`.call[data-main="…"] .call-self`)를 건드리면 위 run.py 어서션(138·142행)이 즉시 깨진다.
- **`[data-mode="qa"]`/`[data-mode="present"]` 이중 표시 규칙** — `booth.css:343` `.call[data-mode="present"] [data-mode="qa"], .call[data-mode="qa"] [data-mode="present"] { display: none !important; }`. 표 A #3·#4(도구줄 버튼 높이)를 고치며 이 선택자 특이성을 깨면 두 모드 버튼이 동시에 보이는 회귀가 난다(9/23 실험실에서 실제로 겪은 버그, `booth.css:174` 주석 참고).
- **판정 색 5종·pill 클래스(`data-v="good|partial|wrong|unknown"`)** — 표 A #13(판정 풍선 요약)을 고치며 `booth-pill`의 `data-v` 값 자체나 `VERDICT_WORD` 매핑(`booth.js:638`)을 건드리면 CLAUDE.md §3-3 불변 규칙 위반이 된다. 요약 길이만 줄이고 이 값들은 그대로 둘 것.
