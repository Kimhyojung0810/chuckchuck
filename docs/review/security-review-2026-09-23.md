<!-- 이 파일: 2026-09-23 보안 점검 결과(백엔드·프론트 두 갈래)와 조치 상태. 부스(AI Festa 10/6~8) 전에 닫아야 할 구멍의 단일 목록. -->

# 보안 점검 2026-09-23 — 브리지·서버·프론트·운영 노출면

읽기 전용 리뷰어 둘(백엔드 / 프론트·비밀·노출면)이 같은 날 병렬로 본 결과를 한 파일로 모았다.
행 번호는 점검 시점 기준이라 이후 커밋에서 밀렸을 수 있다. 키 값은 어디에도 적지 않았다.
**조치 상태는 맨 아래 §조치 표가 원본이다** — 고치면 그 표를 갱신한다.

**한 줄 결론:** CRITICAL 1건(`/api/v1/transcribe` 가 서버 파일 경로를 받는다) + HIGH 7건. 과거 커밋에 키가 들어간 흔적은 없다.

---

# A. 백엔드 (demo/bridge.py · server/ · providers · 터널)


파일은 하나도 고치지 않았습니다. 키 값은 출력하지 않았고 변수명만 적었습니다. 코드를 읽고 판단한 것이며, 실제 요청으로 확인하지 않은 항목은 "(추정)"으로 표시했습니다. 재현 경로는 공격 절차가 아니라 어떤 조건에서 문제가 생기는지만 짧게 적었습니다.

**결론:** 부스 전에 반드시 막아야 할 구멍이 하나 있습니다. `/api/v1/transcribe`가 요청 본문의 서버 파일 경로를 그대로 받습니다. 과거 커밋에 키가 들어간 흔적은 없습니다.

## CRITICAL

| 파일:행 | 문제 | 재현 조건 | 최소 수정안 |
|---|---|---|---|
| `demo/bridge.py:1068, 1087-1106` → `chuckchuck/providers/stt_impl.py:293-306` | 요청 본문의 `audio_path`를 검증 없이 `transcribe()`에 넘깁니다. `AxSTT`는 그 경로에 파일이 있으면 SKT 게이트웨이로 올립니다. 그래서 인증 없는 요청 하나로 서버 안의 아무 파일이나(키가 든 설정 파일 포함) 제3자 벤더로 나갈 수 있습니다. 또 파일이 없으면 `"오디오 파일이 없습니다: {path}"`가 응답에 실려 파일이 있는지 알아낼 수 있고, 아주 큰 파일을 지정하면 ffmpeg가 최대 900초 돌면서 과금도 나갑니다. | `audio_base64` 없이 `audio_path` 필드만 담아 `/api/v1/transcribe`로 보내면 됩니다. 요청 제한 안에서 통과합니다. | `audio_path` 분기를 지웁니다(서버는 `audio_base64`만 받기). 꼭 필요하면 `DEMO_DEV_ROUTES`일 때만 열고 `fixtures/` 안으로 `resolve()`해서 가둡니다. 오류 문구에서 경로를 뺍니다. |

## HIGH

| 파일:행 | 문제 | 재현 조건 | 최소 수정안 |
|---|---|---|---|
| `bridge.py:710, 750, 779, 822, 919, 1016, 1324, 1473, 1493, 1542` → `providers/llm_impl.py:681-700` | 실 API 모드에서도 LLM 백엔드(`llm`)를 클라이언트가 고릅니다. `.env`에 `EXAONE_ENDPOINT_ID`가 설정돼 있어 Friendli dedicated(시간 과금)까지 불립니다. STT `provider`(1064)와 습관 `provider`(991)도 같습니다. | 본문에 `"llm"` 값을 넣으면 됩니다. | 실 API 모드에서는 본문의 `llm`/`provider`를 무시하고 환경변수만 씁니다. 벤치용이 필요하면 `DEMO_DEV_ROUTES`에서만 허용 목록으로 엽니다. |
| `bridge.py:1419-1429`, `demo/session_archive.py:394-426`, `contracts.py:1723-1736` | `/api/v1/memory` 응답의 `RehearsalSummary.session_id`에 **다른 사용자의 세션 id**가 실립니다. 같은 파일(sha256)이면 이어 주는데, 요청하는 쪽 세션은 동의하지 않아도 됩니다. session_id가 유일한 열쇠라서, 이 id로 남의 받아쓰기를 열람하고(`cached-transcript`, 동의 세션은 365일 보관), 세션을 삭제하고, 학습용 라벨(`feedback`·`qa_turns`)을 오염시킬 수 있습니다. 부스처럼 모두 같은 샘플 덱을 쓰는 곳에서 특히 위험합니다. | 누군가 동의하고 올린 자료와 같은 파일을 올리고 memory를 조회하면 됩니다. | 응답에서 `session_id`를 빼거나 해시합니다. 요청하는 쪽도 동의 세션일 때만 이어 주고, sha256만으로는 잇지 않습니다(learner_id 일치를 필수로). |
| `demo/run_tunnel.sh:27, 49-51`, `bridge.py:1663-1668`, `docs/DEPLOYMENT.md §10-2` | Access 없이 열리는 길이 있습니다. ① 스크립트 주석은 "Access 가 없으면 경고하고 멈춘다"고 하지만 검사 코드가 없고 echo만 합니다. ② 대시보드 토큰 방식은 Public Hostname만 추가하고 Access 앱을 빼먹어도(도메인 오타 포함) 열립니다. trycloudflare를 손으로 실행해도 막을 장치가 없습니다. ③ `DEMO_HOST=0.0.0.0`은 경고만 출력하고 그대로 뜹니다. ④ 브리지 자체는 Access가 붙이는 `Cf-Access-Jwt-Assertion` 헤더를 확인하지 않아서, 앞단 설정 하나가 틀리면 바로 무방비가 됩니다. | Access 정책이 빠진 호스트명으로 터널을 엽니다. | 브리지에 `DEMO_REQUIRE_ACCESS=1` 모드를 둡니다. 이 모드에서는 루프백으로 온 요청 중 `Cf-Access-Jwt-Assertion`이 없는 것을 403으로 거절합니다(가능하면 JWT의 aud·서명까지 검증). 비루프백 `DEMO_HOST`는 실 API 모드에서 시작을 거부합니다. `run_tunnel.sh`는 시작 전에 해당 호스트가 Access 로그인으로 리다이렉트되는지 `curl -sI`로 확인합니다. |
| `bridge.py:704-736, 1501-1586`, `chuckchuck/f01_parse.py:485` | 요청 제한은 요청 **횟수**만 셉니다. concepts·judge 같은 경로는 최대 약 42MB의 임의 텍스트를 그대로 LLM 프롬프트에 싣습니다. 또 PDF는 Upstage 파싱(전체 페이지 과금)이 끝난 **뒤에야** `MAX_SLIDES`를 검사합니다. 분당 30회 안에서도 청구액이 크게 늘 수 있습니다. | 큰 본문이나 페이지 수가 아주 많은 PDF를 보내면 됩니다. | JSON 경로별로 본문 상한을 둡니다(예: 2MB). answer·history 길이를 제한합니다. 업로드 전에 로컬에서 페이지 수를 확인합니다(PDF는 pypdf 등). |

## MEDIUM

| 파일:행 | 문제 | 최소 수정안 |
|---|---|---|
| `bridge.py:1165-1182`, `demo/rate_limit.py:33` | 루프백에서 온 요청이면 `CF-Connecting-IP`를 무조건 믿습니다. SSH 터널 사용자나 같은 호스트의 프로세스는 헤더 값을 바꿔 가며 요청 제한을 피할 수 있습니다. `_hits` dict도 줄어들지 않아 메모리가 계속 늘어납니다. | Access 모드일 때만 이 헤더를 믿습니다. 전체 요청에 대한 상한(글로벌 버킷)을 하나 더 두고, 오래된 키를 주기적으로 지웁니다. |
| `bridge.py:385-393, 437, 1651-1653`, `demo/session_store.py:82-113` | 소켓 timeout이 없고 스레드 수도 무제한입니다. 요청 본문(최대 42MB)을 통째로 메모리에 올립니다. `session/artifacts`의 session_id를 검증하지 않고 크기 상한도 없어서, 세션 32개 한도를 채우면 남의 세션이 밀려납니다. | Handler에 `timeout = 30`을 두고 동시 처리 수를 세마포어로 제한합니다. `_handle_session_artifacts`에 `ARCHIVE.safe_id`를 적용하고 크기 상한을 둡니다. |
| `bridge.py:669-670`, `docs/PRIVACY.md:11`, `bridge.py:349-383`, `bridge.py:1643-1648` | 개인정보 약속과 실제 동작이 어긋납니다. 동의하지 않은 PDF의 **원본 바이트가 `preview.pdf`로 저장됩니다**(디스크에서 확인). PRIVACY.md는 "원본은 처음부터 안 남긴다"고 합니다. `stage_cache`는 동의 여부와 상관없이 발화에서 파생된 개념 결과를 72시간 남깁니다. 정리 스레드가 24시간마다 돌기 때문에 "하루 안에 지워요"가 실제로는 최대 약 48시간입니다. | 동의하지 않은 원본 저장을 끄거나, 문서에 "미리보기용 PDF 24시간 보관"을 명시합니다. stage_cache TTL을 24시간 이하로 줄입니다. 정리 주기를 1시간으로 줄입니다. |
| `bridge.py:502-505, 1152-1158, 1275`, `providers/llm_impl.py:544, 557`, `stt_impl.py:257, 276, 323` | 500/502 응답에 `str(e)`가 그대로 나갑니다. 벤더 응답 본문(최대 300자), 서버 파일 경로, raw 저장 경로가 포함될 수 있습니다. 키가 새는 경로는 확인되지 않았습니다(헤더는 메시지에 넣지 않음). | 응답에는 일반 문구만 보내고 상세 내용은 stderr 로그에만 남깁니다. |
| `bridge.py:258-308` | 신뢰할 수 없는 PPTX를 soffice로 변환하면서 격리를 하지 않습니다. 링크된 외부 리소스를 불러오는 SSRF 가능성(추정)이 있고, 사용자 프로필을 공유해서 동시에 변환하면 실패합니다. 인자는 리스트로 넘기고 파일명이 임시 이름이라 **명령 주입은 없습니다.** | 변환마다 `-env:UserInstallation=file:///tmp/…`로 프로필을 분리합니다. 가능하면 네트워크를 끈 샌드박스에서 실행합니다(`systemd-run -p PrivateNetwork=yes` 등). |
| 세션 id 전반 (`session_archive.py:119-121`) | session_id(타임스탬프 + 32비트 난수)가 유일한 권한 수단입니다. `preview_pdf` URL 쿼리와 로그에 노출되고, id만 알면 열람·삭제·오염이 됩니다. 무작위로 추측하는 것은 현실적으로 어렵습니다. | 업로드 때 128비트 비밀 토큰을 따로 발급하고, 열람·삭제·기록할 때 이 토큰을 요구합니다. |
| `bridge.py:1205, 707` 외, `bridge.py:1597-1613` | Content-Type과 상관없이 JSON을 파싱하고 Host 헤더도 확인하지 않습니다. 그래서 브리지를 띄운 기기의 브라우저가 연 다른 웹사이트가 text/plain·multipart 요청(CSRF)이나 DNS rebinding으로 과금 API를 부를 수 있습니다(추정: 최신 Chrome의 로컬 네트워크 접근 제한이 일부 막아 줌). | JSON 경로는 `Content-Type: application/json`을 필수로 합니다(이러면 교차 출처 요청에 preflight가 붙습니다). Host 헤더 허용 목록(`127.0.0.1:포트`, 터널 호스트명)을 둡니다. |
| `server/app.py:92-97, 175-193, 70/145, 459` | FastAPI 서버 쪽(데모에는 안 씀): CORS `*`, 전체 세션 목록과 모든 산출물을 GET으로 조회할 수 있고, 요청 제한이 없습니다. `var/uploads`의 원본과 녹음을 **지우지 않으며 동의 여부도 보지 않습니다.** transcribe의 `ext`도 검증하지 않습니다(테스트 결과 경로 탈출은 실패하고 500만 남). | 외부에 절대 노출하지 않는다고 문서에 명시하거나, CORS를 좁히고 목록 라우트를 닫고 업로드 정리 로직을 추가합니다. |

## LOW

- `chuckchuck/config.py:159-174` `masked()`: 키마다 앞 6자와 뒤 4자를 stdout·journald에 찍습니다. 부스에서 화면에 뜰 수 있습니다. "설정됨(길이 N)"으로 바꾸기를 권합니다.
- `bridge.py:1213`: 검증하지 않은 session_id를 로그에 그대로 찍습니다(개행을 넣으면 가짜 로그 줄을 만들 수 있음).
- 실 API 모드에서도 클라이언트가 `llm:"mock"`이나 `provider:"mock"`을 보내면 mock 결과가 실제 산출물로 보관됩니다(무결성 문제).
- 정적 서빙에서 디렉터리 목록이 켜져 있습니다. `MVP_SPEC.md`·UX 로그·`data/voice_report_live.json`(실제 발화 미리보기 포함)이 공개됩니다.
- `var/data` 파일 권한이 0664입니다(홈 디렉터리가 0750이라 영향은 제한적).

## 문제없음으로 확인한 것

- 정적 파일 경로 탈출: `SimpleHTTPRequestHandler`와 `_serve_sdk`의 resolve 검사로 막혀 있습니다.
- `ARCHIVE.safe_id`(정규식 + 날짜 검증): preview·cached·DELETE 경로에서 디렉터리 탈출이 불가능합니다.
- fixture 이름은 `Path().name`으로 처리하고, `_safe_audio_ext`는 허용 목록 방식입니다.
- 업로드 형식은 확장자가 아니라 내용(magic byte)으로 판별합니다.
- CORS 기본값은 닫혀 있고, OPTIONS 응답에도 허용 헤더가 없습니다.
- 요청 제한과 라우팅이 같은 `parsed.path`를 써서 경로 표기를 바꿔 우회할 수 없습니다.
- `cached-takes`는 DEV_ROUTES일 때만 열립니다.
- 동의 여부에 따른 저장 분기(`put_artifact`·`append`)는 보관소에서 제대로 걸러집니다.
- scholar의 URL은 호스트가 고정돼 있어 SSRF가 아닙니다.

## 과거 커밋의 키

- 전체 ref 429커밋을 키 모양 패턴(up_ / awf_ / sk- / flp_ / hf_ / AKIA / ghp_ / JWT)으로 검색했습니다: **발견 없음**.
- 현재 `.env`의 키 6개(`UPSTAGE_API_KEY`, `AX_API_KEY`, `AX_STT_API_KEY`, `MIDM_API_KEY`, `EXAONE_API_KEY`, `NC_VARCO_API_KEY`) 값으로 `git log -S`와 작업 트리 grep을 돌렸습니다: **모두 없음**.
- git이 추적한 적 있는 env 파일은 `.env.example`뿐입니다. `.env`는 0600 권한입니다.
- 한계: 이미 교체해서 지금 `.env`에 없는 예전 키는 값으로 대조할 수 없어 패턴 검색만 했습니다.

## 부스 전날까지 반드시 고칠 것 3가지

1. **`bridge.py`의 `audio_path` 분기를 제거합니다**(CRITICAL). 서버 파일이 외부 벤더로 올라가는 길을 막습니다.
2. **실 API 모드에서 클라이언트가 보낸 `llm`/`provider`를 무시하고, JSON 본문 상한(예: 2MB)과 PDF 페이지 수 사전 검사를 넣습니다.** Friendli dedicated 호출과 대형 입력으로 인한 과금 폭주를 막습니다.
3. **브리지에서 Access를 직접 확인합니다**(`Cf-Access-Jwt-Assertion` 필수 모드, 비루프백 `DEMO_HOST`면 시작 거부, Host 헤더 허용 목록). `run_tunnel.sh`에는 Access 리다이렉트 확인을 실제로 넣습니다.

그다음 우선순위는 `/api/v1/memory` 응답에서 남의 `session_id`를 빼는 것입니다(HIGH, 한 줄로 고칠 수 있음). 시간이 되면 3번과 함께 고치기를 권합니다.

---

# B. 프론트 · 브라우저 저장소 · 비밀 · 운영 노출면

읽기만 했고 파일은 고치지 않았다. XSS 항목은 코드를 읽고 판단한 것이며 실제 페이로드로 실행해 보지는 않았다.
점검 중에도 `app.js` 가 다른 세션에서 수정되고 있어 행 번호가 약 46행 밀렸다(8278 → 8324).

**요약:** 부스 화면의 질문·힌트·정답 요지·판정 문장은 `esc()` 로 막혀 있다. 남은 구멍은 "판정 값(verdict)·점수·장 번호를 서버 응답 그대로 속성이나 HTML 에 넣는 곳" 네 군데이고, 이것이 `?api=` 백엔드 바꿔치기와 만나면 실제로 스크립트가 실행되는 경로가 된다.

## HIGH

| 파일:행 | 문제 | 재현 경로 | 최소 수정안 |
|---|---|---|---|
| `demo/YEHS_demo/js/chuckchuck_bridge.js:675-680` (`apiBase`) | `?api=` 쿼리 값을 검증 없이 `sessionStorage cheokcheok:qaApiBase` 에 저장하고, 그 탭이 닫힐 때까지 모든 `/api/v1/*` 호출이 그 주소로 간다. `booth.html` 은 `config.js` 도 안 불러서 `?api=` 가 있으면 무조건 그 주소다. | 부스 PC 주소창에 `booth.html?api=https://남의서버` 한 번 → 주소를 되돌려도 같은 탭에서 계속 적용 → 방문객이 찍은 슬라이드·답변 녹음·질문·판정 요청이 전부 남의 서버로 간다. | `?api=` 는 허용 목록(같은 오리진 + `config.js` 값)에 있을 때만 받는다. 아니면 `location.hostname` 이 localhost 일 때만. 적용 중이면 화면에 띠로 표시. |
| `demo/YEHS_demo/js/booth.js:636` | 판정 풍선의 `data-v="${b.verdict}"` 에 이스케이프가 없다. `b.verdict` 는 서버 `j.verdict` 원문이고 `bubble()` 이 `innerHTML` 로 넣는다. | 서버(또는 `?api=` 로 바꾼 가짜 서버)가 `verdict` 에 태그를 돌려주면 부스 오리진에서 스크립트가 실행된다. | `judgementBubbles` 에서 verdict 를 허용 목록(`good/partial/wrong/unknown`)으로 좁힌다. 또는 `esc()`. |
| booth 전체 (`booth.js` `restart`·`finish`) | 방문객이 바뀔 때 **서버 세션을 지우지 않는다.** `restart()` 는 브라우저 상태만 비우고 `DELETE /api/v1/sessions/{id}` 를 부르지 않는다. 동의 없는 세션도 `var/data/sessions/.../slide_doc.json`(슬라이드 글자 전문)이 24시간 남는다 — 화면 안내 「지금 질문·판정에만 써요」와 어긋난다. | 부스 체험 1회 → 「다른 자료로 다시 하기」 → 오늘 폴더에 slide_doc.json 이 그대로 있다(확인함). | `finish()`/`restart()` 에서 `state.sessionId` 가 있으면 `deleteSession` 호출(실패해도 흐름은 막지 않음). |

## MEDIUM

| 파일:행 | 문제 | 최소 수정안 |
|---|---|---|
| `qa_live.js:1525` | 결과 화면 칩에 `chipWord[r.verdict] \|\| r.verdict` 를 이스케이프 없이 `innerHTML` 로. | `escapeHtml(chipWord[r.verdict] \|\| '보류')` |
| `app.js:8324` | `streamRow` 의 `${it.quoteSlide}장` — 서버 `v.evidence_slide_no` 를 숫자로 안 바꾼다. | `Number(v.evidence_slide_no) \|\| 0` |
| `app.js:8339` | `<b class="msg-score num">${it.score}</b>` — 서버 `v.score` 원문. | `Math.round(Number(v.score) \|\| 0)` |
| booth 전체 / booth.html | 다음 방문객에게 앞사람 흔적이 보인다. ① `finish()` 뒤 결과 화면이 「다시 하기」 전까지 남는다(유휴 자동 초기화 없음). ② 브랜드 링크(`booth.html:23` → index.html)로 앱 홈에 가면 그 PC 의 `cheokcheok:qa-history`(질문과 **방문객 답변 원문**, 최대 30건)·`last-report`·`playbill` 이 보인다. ③ `chuckchuck.learner` 가 PC 당 1개라 모든 방문객이 같은 익명 학습자가 되고, F-25 「지난 리허설 기억」이 앞사람 기록을 이어 붙일 수 있다(추정). | 부스 모드에서는 브랜드 링크 제거 또는 이동 시 `cheokcheok:*`·`chuckchuck.learner` 삭제. `restart()` 끝에 `sessionStorage.clear()`. 결과 화면 90초 유휴 자동 초기화. |
| `app.js:343` `route()` / `qa_live.js:925` `stopLiveMic` | 화면을 옮길 때(hashchange) 질문 코칭 마이크와 리허설 녹음을 끄지 않는다. | `route()` 맨 앞에서 `stopLiveMic()`, `#/new` 밖으로 나갈 때 `stopLiveRehearsal()`. |
| `booth.js` `finish`/`restart` → `stopMic({silent:true})` | 서버 받아쓰기(녹음) 경로에서는 「통화 마치기」를 눌러도 녹음을 끝까지 받아 `/transcribe` 로 **올린다**. | `stopMic` 에 `discard` 옵션; finish/restart 는 `session.stop()` 만 하고 업로드 안 함. |
| booth.html 동의 안내 | 실시간 받아쓰기는 Chrome Web Speech 라 **음성이 구글 서버로 간다.** 자동 대화 기본 켜짐이라 발표 모드에서 바로 듣기 시작하는데 안내가 없다. 운영 계획의 "동의 2단 체크"도 없다. | 안내 한 줄 추가. 동의 체크 전에는 마이크를 켜지 않는다. |

## LOW

| 파일:행 | 문제 | 최소 수정안 |
|---|---|---|
| `chuckchuck_bridge.js:822` 부근 `judgeQaAnswer` | 경로 `/api/v1/sessions/${sid}/qa/judge` 에 `encodeURIComponent` 가 없다(267·278 은 있음). | `encodeURIComponent(sid)` |
| `booth.html`, `index.html` | CSP 없음. `index.html:90` 은 jsdelivr 의 pdf.js 를 SRI 없이 부른다(공급망, 부스 와이파이 끊기면 PDF 안 뜸). | `integrity=` 또는 vendor 복사. 최소 CSP 메타. |
| `booth.js:1277` pagehide | 스트림·셀프뷰·센서는 끄지만 `state.mic` 은 안 멈춘다. | pagehide 에 `state.mic.session.stop()` |
| `booth.js` `window.boothLab` | 실험실용 문이 `state`(방문객 답변 `history`)를 전역에 드러낸다. | `?lab=1` 일 때만 붙인다. |
| 브리지 로그 | 키는 없다. 대신 **업로드 파일명**과 `learner=` ID 가 남는다. | 부스 기간에는 파일명을 해시나 길이만. |
| 브리지 CORS | 허용 목록 방식이라 괜찮다. multipart POST 는 preflight 없이 도착하므로 부스 PC 의 다른 사이트가 `/api/v1/parse` 로 과금 요청을 보낼 수는 있다(응답은 못 읽음, 추정). | 키오스크 모드. Origin 없는 쓰기 요청 거부 검토(백엔드 §A). |

## 확인 결과 (요청 항목별)

- **XSS:** `booth.js` 의 질문·칩·why·힌트·빠진 것·되묻기·정답 요지·오류·발표 지적은 모두 `esc()`. `qa_live.js` 는 `pushTurn` 전에 `escapeHtml` 하는 규약이 지켜짐. `chatter.js` `esc()`, `playbill.js` 캔버스+`esc()`. `app.js` 의 LLM 출력 자리(개념도 SVG 라벨·펀치라인·판정 패널·파이프라인 로그·headline)는 이스케이프 확인. 남은 구멍은 위 4곳.
- **브라우저 저장소:** localStorage — `cheokcheok:qa-history`·`last-report`·`playbill`·`game`·`stage-visits`·`house-visits`·`booth-delivery`·`booth-sound`·`chuckchuck.learner`. sessionStorage — `cheokcheok:qaApiBase`·`chuckchuck-session`·`new-flow`/`qa-flow`(답변 포함). 방문객을 바꿀 때 한꺼번에 지우는 장치는 없다.
- **미디어:** booth 의 `stopStream`·`closeSelfView`·`stopSensors` 는 `track.stop()`·`AudioContext.close()` 를 제대로 한다. `startAnswerRecording`·`rehearsal-recorder.js:141-142` 도 트랙을 끈다. 셀프뷰 영상은 서버로 안 간다. 동의 플래그는 앱의 `parseDocument` 에서만 붙고 booth `uploadShots` 에는 없다(항상 동의 없음 — 방향은 안전). `/transcribe` 에는 동의 필드가 없고 booth 의 `transcribeAnswer` 는 `session_id` 도 안 보낸다.
- **비밀:** `.env` 는 `.gitignore:4`, 권한 600. `.env.example` 의 키 변수는 모두 비어 있음. 전체 429 커밋에서 키 패턴 검색 **발견 없음**. 작업 트리·`labs/qa_call/out`·`exports`·`var`·`.claude/settings*.json`·스크린샷 2장에도 없음. **걸린 것 하나:** `/tmp/claude-7778/-home-yehschuck-project/6aa30bd5-…/scratchpad/.env.bak-20260913`(9/13 .env 백업, 키 4개, 권한 600) — 지울 것. `exports/qa_eval/*.json` 6개는 `.gitignore:65` 에 있는데도 이미 추적 중.
- **운영 노출면:** 브리지는 `127.0.0.1` 에만. 모든 주소에 열린 것은 22·10022(SSH), **9100 node_exporter, 9400 dcgm-exporter**(호스트·GPU 지표 무인증, 우리 것 아님). `~/.cloudflared/` 비어 있고 서비스 inactive — **폰 트랙은 준비되지 않은 상태.** 불일치: ① `.env.example`·`bridge.js API_FALLBACK` 은 8787, 문서·실제는 8799. ② `run_tunnel.sh` 주석은 "Access 없으면 멈춘다" 인데 실제로는 확인 안 함. ③ `booth-operations.plan.md §5` 폰 트랙은 "Tunnel + Access" 전제인데 Access 는 이메일 로그인이라 지나가는 방문객 폰과 안 맞는다 — 운영 방식 결정 필요.

## 부스 전날까지 반드시 고칠 것 3가지 (프론트)

1. `?api=` 바꿔치기 막기 + verdict 허용 목록(`booth.js:636`, `qa_live.js:1525`, `app.js:8324/8339`).
2. 방문객이 바뀔 때 완전히 지우기: 서버 세션 DELETE, `sessionStorage.clear()`, 녹음 중 음성 버리기, 결과 화면 유휴 초기화, 브랜드 링크 정리.
3. 마이크·동의 정직하게: `route()` 에서 `stopLiveMic()`/`stopLiveRehearsal()`, 동의 안내에 "구글 받아쓰기" 명시, 동의 전 자동 마이크 금지. 운영: `.env.bak-20260913` 삭제, 8801 브리지 정리, `run_tunnel.sh` 주석·동작 일치.

---

# 조치 상태

| # | 항목 | 심각도 | 상태 | 커밋 |
|---|---|---|---|---|
| 1 | transcribe `audio_path` 제거 | CRITICAL | 진행 중 | |
| 2 | 실 API 모드에서 본문 `llm`/`provider` 무시 | HIGH | 진행 중 | |
| 3 | `/api/v1/memory` 남의 session_id 제거 | HIGH | 진행 중 | |
| 4 | 본문 상한 · PDF 페이지 수 사전 검사 | HIGH | 진행 중 | |
| 5 | DEMO_HOST 비루프백 시작 거부 · Access 헤더 검사 · run_tunnel 실제 확인 | HIGH | 진행 중 | |
| 6 | `?api=` 허용 목록 | HIGH | 대기(프론트) | |
| 7 | verdict 허용 목록 · score/장 번호 Number() | HIGH/MEDIUM | 대기(프론트) | |
| 8 | 방문객 교체 시 서버 세션 DELETE · 저장소 정리 · 유휴 초기화 | HIGH/MEDIUM | 대기(프론트) | |
| 9 | route() 에서 마이크·녹음 정지 | MEDIUM | 대기(프론트) | |
| 10 | 동의 안내(구글 받아쓰기) · 동의 전 마이크 금지 | MEDIUM | 대기(팀 결정) | |
| 11 | 오류 응답 일반 문구 · Content-Type 필수 · Host 허용 목록 · soffice 프로필 분리 · 디렉터리 목록 끄기 · masked() | MEDIUM/LOW | 진행 중(시간 되면) | |
| 12 | `/tmp/.../.env.bak-20260913` 삭제 · 8801 브리지 정리 · `exports/qa_eval` 추적 해제 | 운영 | 대기(사람) | |
