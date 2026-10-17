# 행동 추적 실험실 (etc/labs/behavior_cv)

카메라 행동 추적(「발표 태도 · 베타」 — 화면 쪽을 향한 시간 · 긴 시선 이탈 · 아래 본 시간 · 몸 흔들림 · 움직임 · 손짓 · 자리)을
**정답이 프레임마다 있는 합성 영상**으로 재는 곳. 이 서버엔 웹캠이 없어서, 실제 얼굴 스캔으로 대본대로 움직이는 영상을 만들고
헤드리스 크롬의 가짜 카메라(`--use-file-for-fake-video-capture`)로 엔진을 실제 카메라 경로 그대로 돌린다.
계획: `~/meetings/리서치/2026-10-17_행동추적_고도화_계획.md` §2 · §4. 자료 출처: [SOURCES.md](SOURCES.md).

```
render_heads.py   3D 머리 스캔(CC BY) → 자세 아틀라스 PNG (yaw -90..90 · pitch -50..25, 5° 간격 · 눈 3단계 · 안경 유무)
validate_atlas.py 아틀라스를 OpenCV Haar 로 검증 → calib.json(얼굴 폭 맞춤) · lab/atlas_validation.md(각도 × 얼굴 크기 × 톤 × 안경)
scenarios.py      장면 대본(사람 · 고개 · 흔들림 · 손 · 장 넘김) — 영상 하나 = 함수 하나
gen.py            대본 → .y4m 영상 + .gt.json 정답 + .sheet.jpg 낱장 모음
ref_engine.py     파이썬 참조 엔진(고전 OpenCV, 브라우저 엔진과 같은 순서) + 기법 변형(VARIANTS)
browser_adapter.py · web/harness.html · web/labtap.js · web/adapter_default.js   브라우저 엔진 돌리기
score.py          엔진 로그 × 정답 → 지표          run.py   한 번에 돌리기 + report.md
```

## 0. 준비 (한 번)
루트 디스크가 꽉 차 있어 venv 를 새로 만들지 않는다. OpenCV-python · scipy 는 /data 에 따로 깔려 있다(`common.py` 가 경로를 붙인다).
```bash
PY=/home/yehschuck/project/chuckchuck/.venv/bin/python
# 없으면: $PY -m pip install --target /data/models/_runs/behavior-cv/pylib opencv-python-headless==4.10.0.84 scipy
cd etc/labs/behavior_cv
$PY render_heads.py        # 자산 받기 + 아틀라스 3,552장 (~3분, 118MB → /data/.../lab/assets/atlas)
$PY validate_atlas.py      # calib.json + atlas_validation.md
```
크롬은 Playwright 것을 쓰고 `LD_LIBRARY_PATH=$HOME/.local/lib/pwlibs` 는 스크립트가 알아서 붙인다.

## 1. 영상 만들기
```bash
$PY gen.py --list                 # 장면 목록
$PY gen.py                        # 전부 (~4분, 약 6GB → /data/models/_runs/behavior-cv/lab/clips)
$PY gen.py --only s03,d1          # 몇 개만
```
| 묶음 | 장면 |
|---|---|
| 방향 · 이탈 | s01_front_steady(정면 고정) · s02_turns(45/60/75/90° 돌림) · s03_lookaway(4~6초 vs 2초 이탈) · s13_yaw_sweep(yaw ±20/35/50/70 · roll ±8/15 · pitch -15/-25/-35) |
| 아래 보기 | s04_down_reading(1~5초 숙임 묶음 + -15° 끄덕임) |
| 흔들림 | s05_sway_freq(0.5/1.0/1.4Hz) · s06_sway_amp(0.7Hz 진폭 .06/.15/.40 얼굴 폭) · s07_drift(느린 이동 · 0.12Hz — 흔들림 아님) |
| 손짓 | s08_gesture(손짓 묶음 · 가슴 앞 가만한 손 · 손 내림) |
| 자리 · 여럿 | s09_leave(걸어 나감 · 빈 방 · 가장자리) · s10_empty(빈 방) · s11_two_people · s12_poster(벽의 모나리자 포스터) |
| 품질 변형(같은 대본) | d0_clean · d1_dim45 · d2_dim30 · d3_blur · d4_noise · d5_backlit · d6_jpeg · d7_small(얼굴 6%) · d8_hd30(1280x720@30) · d9_glasses |
| 피부 톤(같은 대본) | t1_tone_medium · t2_tone_deep · t3_tone_deep_dim |

모두 640x360@15fps(d8 만 1280x720@30), 24~60초, 장(슬라이드) 넘김 3~5번. `.sheet.jpg` 로 눈으로 먼저 확인하면 좋다.

### 정답 형식 (`<clip>.gt.json`)
```jsonc
{ "version": 1, "name": "s03_lookaway", "fps": 15, "w": 640, "h": 360, "n_frames": 780, "duration": 52,
  "conventions": { ... },                       // 아래 규약을 글로
  "slides":   [{"i": 0, "t0": 0, "t1": 12}, ...],
  "segments": { "lookaway": [{"t0","t1","dir"}],   // 사람 있음 & 정면 아님 > 3초
                "down": [...], "absent": [...], "gesture": [...],
                "sway": [{"t0","t1","freq","amp_fw"}],  // 들고 나는 0.6초를 뺀 「흔들리는 중」
                "drift": [...] },                    // 대역 밖 느린 흔들림 — 흔들림 아님
  "per_slide": [{"i","presence_ratio","front_ratio","down_sec","lookaway_n","lookaway_sec","gesture_ratio","sway_sec"}],
  "frames": [{"i","t","slide","present","label","ignore","n_people","yaw","pitch","roll",
              "face":[x,y,w,h], "hands_visible","gesture","hand_speed","head_speed","sway","bright"}] }
```
- **yaw +: 코가 영상 오른쪽**(보는 사람 기준, 좌우를 뒤집지 않은 원본 프레임). label `right` = yaw ≥ 35°, `left` = yaw ≤ -35°.
  발표자 기준(엔진 `behavior_cv_logic.rawDir` 규약)은 좌우가 반대 → 채점 `--yaw-convention subject`.
- `front` = |yaw| < 20° & pitch > -12°, `down` = pitch ≤ -25°. **사이 각도와 화면 가장자리는 `ignore=1`**(방향 채점 제외 — 경계에서 엔진을 탓하지 않는다).
- `face` 는 정면 Haar 상자 크기에 맞춘 근사(화면 비율). `gesture` = 손짓 모드 & 손이 화면 안.
- 영상 **오른쪽 위 20칸 바코드** = [1,0] + 프레임 번호 16비트 + 짝수 패리티 + 1. 칸 폭 = max(4, W/160) px → 320px 로 줄여도 2px.

## 2. 돌리기
```bash
$PY run.py ref --run baseline_1017 --primary v2      # 참조 엔진 13변형 × 모든 영상 (14프로세스, ~15분)
$PY run.py ref --variants full,booth_v0 --clips s03,d1 --run quick
$PY run.py browser --web /data/models/_wt/wt-behavior-cv/main/web --run engine_<commit> [--include-hd] [--cpu-throttle 4]
$PY run.py score --run baseline_1017               # 예측은 그대로, 다시 채점 · 보고서만
```
결과: `/data/models/_runs/behavior-cv/lab/runs/<run>/` — `preds/<변형>/<영상>.json` · `scores.json` · `report.md`.
사람이 쓴 해석은 같은 폴더 `notes.md` 에 두면 다시 채점해도 보고서 끝에 붙는다. 기준 결과: `runs/baseline_1017/report.md`(참조 엔진) · `runs/engine_5e3dd16/report.md`(브라우저 엔진 첫 측정).
브라우저 실험은 127.0.0.1:8835~8839 중 빈 포트를 쓴다(8799 · 8800 은 안 건드림). 영상 길이만큼 실시간으로 돈다(전체 ≈ 25분).

### 빠르게 돌리기 (바퀴 3)
```bash
node replay_logic.mjs engine_<run> rp_x                       # logic 만 바꿨을 때 — 저장된 engine_rows 를 지금 logic 으로 (preds 아래 모든 갈래)
LOGIC_CFG='{"gestThr":0.045}' node replay_logic.mjs engine_<run> rp_y   # 문턱만 바꿔 보기
node node_engine.mjs --run n_x --jobs 14 [--phase-ms 67] [--proc-fps 3] [--in-fps 15] [--fx '{"bgSkinOn":0.3}'] [--debug 1]
                                                              # 특징까지 노드에서(opencv.js 그대로) — 25편 ≈ 30초. 그다음 run.py score --run n_x
$PY decimate.py d8_hd30 2 d8_hd15                             # 같은 영상을 15fps 로 솎기(정답 · 바코드는 원래 번호) — 15 vs 30fps 입력 비교
```
- **위상 잡음**: 5fps 처리는 15fps 영상의 3장마다 한 장이라, 어느 장부터 뽑느냐(0 · 67 · 133ms)에 손짓 영상별 재현율이 ±0.15 까지 흔들린다(합성 손은 0.3~0.7초마다 멈칫한다).
  노드로 기법을 고를 땐 세 위상 평균을 보고(`--label p0 --phase-ms 0` …), 싣기 전엔 브라우저로 다시 잰다. 노드 값은 브라우저와 몇 %p 다르다(줄이기 · 시계) — 기법 비교용.
- `--proc-fps 3` 은 느린 기기(엔진이 3fps 로 내려감)를 흉내 낸다. 흔들림은 대역 위끝 0.45×fps 가 1.5Hz 아래면 「잴 수 없었어요」(qreport.gates.sway = sway_fps).
- HD 영상(d8_*)은 기본 목록에서 빠진다 — `--clips d8_hd30,d8_hd15`(브라우저는 `--include-hd`).

### 참조 엔진 변형 (ref_engine.py `VARIANTS`)
| 이름 | 무엇 |
|---|---|
| booth_v0 | 지금 main 부스 방식 — 정면 Haar 가 잡히면 정면, 아니면 없음 |
| prof_raw | + 옆얼굴 캐스케이드(원본 · 뒤집음), 평활 · 추적 · 숙임 단서 없음 |
| full | + 얼굴 가운데 y 하강(숙임) · CamShift 메움 · 옆 방향 유지 · 3장 다수결 · 연속성(멀리 있는 얼굴로 안 갈아탐) |
| **v2** (권장) | full + 정면 alt2 + 꼼짝 않는 헛얼굴 거르기 + 배경 피부 빼기 · 손 크기 덩어리 (v2_clahe · v2_nobgskin 은 하나씩 바꾼 것) |
| full_notrack / full_nosmooth / full_alt2 / full_clahe / full_eyes / full_w480 / full_gest_v0 | 기법 하나씩 빼거나 바꾼 것 |

## 3. 엔진 계약 (브라우저 어댑터가 기대하는 것)
`web/adapter_default.js` 가 지금 엔진(6dd2891 · 5e3dd16 모양)에 맞춰 있다. 엔진 API 가 바뀌면 **이 파일만** 고치거나 새 어댑터를 `--adapter` 로 준다.
- 하네스는 `/behavior_lab_harness.html` 로 엔진 `main/web` 루트에 끼워 내준다 → 엔진의 상대 경로(`js/…`, `js/vendor/opencv.js`)가 앱과 같다.
- `LabAdapter.scripts` → `prepare()`(도구 받기, 끝나야 카메라를 연다) → `start(ctx)` → `markSlide(i, t)` → `stop(ctx)`.
- 지금 엔진 호출: `BehaviorCV.load()` · `BehaviorCV.start('present', {video:()=>v, seg:()=>'s<장>', active:()=>true})` · `BehaviorCV.finish('present')`
  · `BehaviorCvLogic.states(rows)` · `.swayWindows(seq)` · `.measure(seq)` · `.CFG.gestOn/gestOff`.
- **프레임 맞춤**: `web/labtap.js` 가 `Worker` 를 감싸 엔진이 워커로 보내는 `{type:'frame', w, h, data:RGBA, id, t}` 에서 바코드를 풀고,
  워커 답 `{type:'row', id, row}` 와 id 로 잇는다 → 줄마다 엔진이 **실제로 본** 영상 프레임 번호. 워커를 안 쓰는 엔진은
  `LabTap.frameOfPerf(performance.now())`(requestVideoFrameCallback 시계)로 맞춘다.
- `stop()` 이 돌려줄 것: `{ rows:[{frame, orient, present, sway:{active, amp_fw, freq?}, gesture, motion, ms}], summary:{ slides:[{i, presence_ratio, front_ratio, down_sec, gesture_ratio, lookaway_n}], lookaways:[{t0,t1}] } }`
  - `orient` ∈ front/left/right/down/away/none (한국어 정면/왼쪽/오른쪽/아래/없음도 받음). `away` = 정면 아님 · 방향 모름(방향 채점에선 틀림, 이탈에선 정면 아님).
- 엔진에 바라는 것(있으면 어댑터가 덜 흉내 낸다): 줄마다 `frame`(또는 캡처 순간 `performance.now()`), `swayWindows` 에 `freq`, `gestureFlags` 공개.

## 4. 보고서 읽기 (`report.md`)
1. **변형 비교** — 방향 정확도(5갈래, ignore 뺌) · macro-F1 · 정면/정면 아님 · 정면율 오차 · 긴 이탈 F1(IoU ≥ 0.5) · 아래 본 시간 오차 ·
   흔들림 검출률/주파수 오차/진폭 오차/느린 이동 오탐 · 손짓 비율 오차/정밀도/재현율/가만한 손 오탐 · 움직임 순위상관 · 자리 정확도 · **얼굴 자리**(엔진이 고른 얼굴 상자의 가운데가 정답 발표자 얼굴 안인가 — 책장 · 포스터 헛얼굴에 붙으면 방향이 「정면」으로 맞아도 여기서 드러난다) · 장별 MAE · ms.
2. 영상별 표 · 3. 혼동 행렬 · 4. **각도 곡선**(yaw/pitch/roll 구간별 엔진 답 비율) · 5. 흔들림 구간 · 6. 품질 변형 · 피부 톤 · 7. 변형 × 영상.
- `±0.5s` 정확도는 0.5초 늦게 바뀌는 것(평활 지연)을 봐준 값 — 정확도와 차이가 크면 지연 문제.
- 흔들림은 창(8~10초) 때문에 늦게 켜지므로 구간 [t0+1, t1+3] 의 절반 넘게 켜지면 「검출」로 친다.
- ms: 참조 엔진은 여러 프로세스가 동시에 돌아 실제보다 크다. 브라우저 ms 는 워커 안 한 장 처리 시간(엔진 `row.ms`).

## 5. 한계 (합성 자료)
- 얼굴은 **한 사람의 3D 스캔**(성인 남성 · 민머리 · 수염 자국)뿐, 눈은 텍스처에 그린 것이라 눈 캐스케이드 결과는 실제보다 낙관/비관 어느 쪽일 수도 있다.
  피부 톤은 색 배수로 바꾼 것이지 다른 사람이 아니다. 머리카락 · 표정 · 입 움직임 · 안경 반사 · 마스크 없음.
- 손은 2D 도형(팔 + 손바닥 + 손가락)이라 실제 손 모양 · 그림자 · 모션 블러와 다르다. 몸은 흉상 + 그린 몸통.
- 조명은 앞쪽 고정 + 화면 전체 변형(어둡게 · 역광 · 잡음 · 흐림 · 압축). 실제 카메라의 자동 노출 · 화이트 밸런스 흔들림 · 롤링 셔터 없음.
- 배경은 그린 방(책장 · 창 · 화분) — **s03 의 책장은 정면 Haar 헛얼굴을 꾸준히 만든다**(실제 책장에서도 흔한 일이라 그대로 둠).
- 노트북 화면을 보는지 카메라를 보는지는 구분하지 않는다(근거조사: 고전 CV 로 분리 불가) — 정답도 「얼굴 방향」만.
- 그래서 이 숫자는 **기법 비교 · 회귀 · 문턱의 출발점**이다. 사람 채점과의 일치(ICC)는 실제 녹화로 따로 재야 한다(계획 §4).
