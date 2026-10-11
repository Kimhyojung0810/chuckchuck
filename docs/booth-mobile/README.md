# 부스 모바일 — /hi 팀 소개 · #/tour 체험 투어 (2026-10-11 ~)

결선 부스(11/3~5)에서 방문객이 QR 을 찍으면 **폰에서** 이렇게 흐른다.

```
QR → /hi  (intro.html — 척척발표 소개 · 네 단계 · 팀원 카드 한 명씩)
       └ 「척척발표 살펴보기」 ▶ /index.html#/tour
            #/tour ▶ /deck ▶ /present ▶ /analysis ▶ /qa(/2, /3) ▶ /report ▶ /done
              └ 「내 자료로 직접 해 보기」 ▶ #/rehearsal (실제 흐름 · 인앱 브라우저면 먼저 「Safari/Chrome 으로 열기」 시트)
              └ 「팀 소개로 돌아가기」 · 닫기(✕) ▶ /hi
```

왜 투어인가: 10/7 QR 실측 64명 → 덱 선택 14 → 리허설 8 → 분석 3 → 답변 2. 폰 방문객 97% 가 실제 흐름에서 빠졌다.
투어는 **녹화된 응답만 재생**한다 — 분석 API 호출 0, 카메라·마이크 권한 없음, 인앱 브라우저(카카오톡·네이버·인스타)에서도 끝까지 돈다.
투어 동안 나가는 요청은 퍼널 신호 `POST /api/v1/tour/event` · 앱 첫 `GET /api/v1/team` · 연결 감시 `GET /api/health` 뿐이다(`labs/mobile_tour` 가 센다).

## 무엇이 어디 있나

| 조각 | 파일 | 만든 브랜치 |
|---|---|---|
| `/hi` 랜딩 | `demo/YEHS_demo/intro.html` · `css/intro.css` · `js/intro.js` — app.js 를 안 싣는 정적 페이지 | web/intro-1011 |
| `/hi` 주소 | `demo/bridge.py` `standalone_page_for` (`/hi` · `/hi/<id>` → intro.html 200, 302 없음) | web/intro-1011 |
| 팀 카드 데이터 | `demo/YEHS_demo/data/team.json` · 사진 `demo/YEHS_demo/assets/team/<id>.webp` | (계약) |
| 투어 화면 | `js/tour_logic.js`(순수 판단) · `js/tour.js`(셸 · 시작 · 자료 · 끝) · `js/tour_play.js`(발표 · 분석 · 질문 · 리포트) · `css/tour.css` — `index.html` `#lazyAssets` 의 `tour` 번들 | web/tour-1011 |
| 투어 주소 | `js/app.js` `routes.tour` · `LAZY_ROUTE_BUNDLES.tour` · `route()` 의 `tourOnRoute` · 옛 `#/hi` → `/hi` 넘김 | web/tour-1011 · 통합 |
| 투어 녹화 데이터 | `demo/YEHS_demo/data/tour/index.json`(목록 · 기본 덱) · `<id>.json` 3개(C-1 배달앱 별점 · A-1 급속충전 · B-1 미세플라스틱) · `_example.json`(형식 예시) | lab/tour-fixtures-1011 |
| 녹화 도구 | `labs/tour_capture/` (`capture.py` 실 API 녹화 · `build.py` 계약 모양으로 옮기기) | lab/tour-fixtures-1011 |
| 퍼널 신호 | 서버 `demo/tour_events.py` · 배선 `demo/bridge.py` `_handle_tour_event` · 화면 `js/funnel.js` `ccFunnel()` · 집계 `scripts/booth_funnel.py` | ops/booth-qr-1011 |
| QR | `scripts/booth_qr.py` → `~/meetings/2026-10-11_결선_QR/` (A4 PDF · SVG · PNG) | ops/booth-qr-1011 |
| 공개 허용 목록 | `demo/static_assets.py` `_PUBLIC_PATH` · Cloudflare 짧은 캐시 `EDGE_SHORT_PATH` | 기준선 · ops |
| 캡처(폰 한 바퀴) | `labs/mobile_tour/run.py` — [README](../../labs/mobile_tour/README.md) | 통합 |
| 배포 | [`DEPLOY.md`](DEPLOY.md) | ops/booth-qr-1011 |

이음매 회귀는 `tests/test_booth_mobile_stitch.py`(랜딩 → 투어 → 끝 링크 · 퍼널 단계 이름 · 공개 파일)와
`node tests/js/tour.smoke.mjs`(투어 화면 이름 → 퍼널 계약 이름 `funnelStep`)가 잡는다.

## 계약 (단일 원본)

| 경계 | 원본(기계 검사) | 사람용 설명 | 데이터 파일 | 쓰는 쪽 |
|---|---|---|---|---|
| 투어 녹화 데이터 | [`tour.schema.json`](tour.schema.json) | [`tour-schema.md`](tour-schema.md) | `data/tour/<id>.json` | `#/tour/*` 화면 |
| 투어 목록 | [`tour-index.schema.json`](tour-index.schema.json) | [`tour-schema.md`](tour-schema.md) §목록 | `data/tour/index.json` | `#/tour/deck` 덱 고르기 · 기본 덱 |
| 팀 카드 | [`team.schema.json`](team.schema.json) | [`team-schema.md`](team-schema.md) | `data/team.json` | `/hi` 화면 |
| 퍼널 신호 | `demo/tour_events.py` `STEPS` | [`funnel-events.md`](funnel-events.md) | (저장 안 함 — 서버 로그 한 줄) | `/hi` · `#/tour/*` → `ccFunnel()` |

- **스키마가 원본이다.** 문서·예시·화면 코드가 스키마와 어긋나면 스키마를 기준으로 고친다.
- 검사: `python -m pytest tests/test_booth_mobile_contract.py tests/test_booth_mobile_stitch.py -q`.
  `data/tour/` 에 파일을 넣으면 따로 등록하지 않아도 계약 테스트가 집어 검사한다(`index.json` 은 목록 스키마로 따로).
- 투어 화면 이름(`deck`·`present`·`analysis`·`qa`·`report`)과 퍼널 이름(`tour_deck`…)은 다르다. 화면은 `TourLogic.funnelStep()` 으로 바꿔 보낸다 —
  예전 이름 그대로 보내면 서버가 400(`bad_step`) 으로 거절해 안 세어졌다(10-12 통합에서 잡음).

## team.json 고치는 법

1. `demo/YEHS_demo/data/team.json` 의 `members[]` 를 고친다. **카드 수 = 배열 길이**, 순서 = 보여 줄 순서. 코드 수정 없음.
2. 칸 규칙은 [`team-schema.md`](team-schema.md): `headline` ≤40자 해요체, `did` 2~3개(확인할 수 있는 사실만), `quote` 는 본인이 준 말만(없으면 `null` → 화면에서 숨김), `links` 는 https 만.
3. 본인 확인이 끝나면 `draft` 를 `false` 로. 결선 전에 **전원 `false`**(화면엔 안 보이지만 운영 확인용).
4. 사진:
   - 위치: `demo/YEHS_demo/assets/team/<id>.webp` — 파일 이름은 그 사람의 `id` 와 같게. `png` · `jpg` 도 열려 있지만 webp 를 쓴다.
   - 규격: **정사각 400×400px 안팎, 60KB 이하**. 화면에선 64px 원(DPR 3 이면 192px)으로 잘라 보이므로 얼굴을 가운데에.
   - `photo` 칸에 `"assets/team/<id>.webp"` 를 적는다(앞에 `/` 없이). 이 폴더는 공개 허용 목록에 이미 있다.
   - 사진이 없거나 못 받으면 이름 첫 글자 + 병아리로 대신한다(깨진 그림 없음).
5. 검사: `python -m pytest tests/test_booth_mobile_contract.py -q` (스키마 · 사진 파일이 있는지 · 공개인지).
6. 폰에서 보기: `labs/mobile_tour/run.py <포트> --widths 375` 의 `team_*` 사진.
   팀원 한 명에게 자기 카드 주소를 줄 때는 `https://chuckchuck-present.com/hi/<id>`.

## 투어 데이터 다시 녹화하는 법

녹화(`capture.py`)는 실 API 를 부른다(2026-10-11 실측 덱당 LLM 25회 · Upstage 1 · A.X 1). 옮기기(`build.py`)는 과금 0.

```bash
PY=.venv/bin/python
# 1) 녹화 — 도구가 브리지를 직접 띄우고 끈다. 포트는 8983~8985 만(8799 공개 · 8800 팀 개발은 거부)
$PY labs/tour_capture/capture.py --decks 배달앱별점인플레이션A 급속충전배터리열화A 미세플라스틱물벼룩번식A --port 8983 --budget 80
# 2) 녹화본 → data/tour/<id>.json + index.json
$PY labs/tour_capture/build.py
#    다른 worktree 에서 녹화했으면 그 녹화본을 읽기만:  --rec-dir <그 worktree>/labs/tour_capture/out/recordings
# 3) 검사 — 계약 · 변환 규칙 · 이음매 · 재현성
$PY -m pytest tests/test_tour_capture.py tests/test_booth_mobile_contract.py tests/test_booth_mobile_stitch.py -q
$PY labs/tour_capture/build.py --check
# 4) 폰에서 보기
$PY labs/mobile_tour/run.py <포트>
```

- 응답은 요청 해시로 캐시해서 다시 돌리면 바뀐 단계만 부른다. 녹화본(`out/`)은 덱 본문 · 발표 전사가 들어 있어 git 에 안 올린다.
- 판정기가 틀린 질문은 `build.py` `EXCLUDE` 로 빼고 이유를 `source.note` 에 남긴다(바꿔 쓰지 않는다). 자세한 건 [`labs/tour_capture/README.md`](../../labs/tour_capture/README.md).
- 표지 머리줄(「배 터 리 공 학 과 … · 2 0 2 6 .」)은 덱 제목이 되지 않게 `letter_spaced()` 가 거른다(app.js `letterSpacedLine` 과 같은 잣대).

## 캡처 도구 — `labs/mobile_tour`

```bash
DEMO_PORT=<내 포트> DEMO_DEV_ROUTES=0 ./demo/run_bridge_midm.sh &     # 팀 쿠키 없는 공개 모드로
.venv/bin/python labs/mobile_tour/run.py <포트>                    # 360 · 375 · 393 · 412
.venv/bin/python labs/mobile_tour/run.py <포트> --ua kakao         # 카카오톡 인앱 UA (naver · instagram 도)
```

`/hi` 첫 화면 → 팀 카드 각 장 → 살펴보기 → 투어 각 단계(터치 밀기 포함) → 끝 → 실제 흐름 / 인앱 시트 → 팀 소개로 돌아가기를 따라가며
`out/<시각>/<ua>_<폭>/NN_<화면>.png` 와 `report.json`(콘솔 오류 · 실패 요청 · 가로 넘침 · 44px 미만 누를 곳 · 주 버튼 위치 · 퍼널 신호)을 남긴다.
문제가 있으면 종료 코드 1. **사진은 사람이 직접 연다** — 표는 어디를 볼지 알려 줄 뿐이다. 자세한 건 [README](../../labs/mobile_tour/README.md).
`/hi` 만 따로(team.json 실패 · JS 꺼짐 · 데스크톱 폭): `labs/intro_flow/run.py`. 투어만 따로(새로 고침 · 뒤로 가기 복원): `labs/tour_flow/run.py`.

## 바꾸는 순서 (contract-first)

1. 필요한 칸·값을 말한다(어느 화면이 무엇을 그리려고).
2. **스키마부터** 고친다 → 사람용 문서 → `_example.json` → 테스트 초록.
3. 그다음 화면 코드를 고친다. 깨지는 변경이면 `version` 을 올리고, 화면은 모르는 버전을 「체험을 불러오지 못했어요」 로 처리한다.
4. 퍼널 단계 이름을 바꾸거나 더하면 세 곳(`tour_events.py` · `funnel.js` · `booth_funnel.py`)과 `tour_logic.js` `FUNNEL_STEP` 을 같이.

## 공통 규칙

- 평가는 숫자 대신 **3단계 말**: `good`=「좋아요」 · `fair`=「보통」 · `practice`=「더 연습」. 화면 글자는 이 셋으로 고정.
- 판정 낱말은 새로 짓지 않는다 — 그래프 상태는 정합 판정 enum(`aligned|justified_skip|missing|contradiction`), 답 판정은 F-09 enum(`good|partial|wrong|unknown`), 근거 역할은 `covered|missing|conflict`. 판정 색 5종과 짝이다.
- **정직 표시**: `source.kind=example` 이면 화면에 예시라고 적는다. 녹화본도 「미리 녹화한 체험이에요」 를 남긴다(CLAUDE.md §3-4).
- 폰 규칙: 기준 폭 360/375/393/412 세로, 누를 곳 44px 이상, 가로 스크롤 0, 주 버튼은 아래 고정, 스와이프는 `touch-action` + pointer capture.
- 새 공개 파일을 쓰면 `_PUBLIC_PATH` 부터 연다(안 열면 공개 사이트에서 404). `tests/test_booth_mobile_stitch.py` 가 랜딩 · 투어 번들 파일을 훑는다.

## 운영 (QR · 퍼널 · 배포)

- QR 은 `https://chuckchuck-present.com/hi` 하나 — 꼬리표(`?src=`)를 붙이지 않는다(Cloudflare 캐시 열쇠가 갈린다). `/hi` 진입은 서버 로그로도 센다.
- 배포(통합 브랜치 → main → 재시작 → Cloudflare)·당일 퍼널 보기·캐시 확인: [`DEPLOY.md`](DEPLOY.md). 명령은 전부 사람이 `!` 로 친다.
