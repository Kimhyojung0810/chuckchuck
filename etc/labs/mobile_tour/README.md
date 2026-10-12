# etc/labs/mobile_tour — 부스 모바일 한 바퀴 캡처 (2026-10-12)

QR 을 찍은 폰이 따라가는 길 전체(`/hi` → 팀 카드 → 「척척발표 살펴보기」 → `#/tour/*` → 끝 → 실제 흐름 · 팀 소개로 돌아가기)를
폰 세로 네 폭 × 헤드리스 크롬 모바일 에뮬레이션(터치 · DPR · UA · is_mobile)으로 태워 화면마다 찍는다.
이 서버(VMware VM)엔 폰이 없어서 만들었다. 다음 점검 단계가 그대로 다시 쓴다.

## 실행

```bash
# 1) 브리지 — 팀 쿠키 없는 공개 모드(DEMO_DEV_ROUTES=0). 배정받은 포트만, 끝나면 그 PID 로 끈다(pkill 금지)
DEMO_PORT=8992 DEMO_DEV_ROUTES=0 ./main/server/run_bridge_midm.sh > /tmp/b.log 2>&1 &  echo $! > /tmp/b.pid
# 2) 캡처
.venv/bin/python etc/labs/mobile_tour/run.py 8992                       # 360 · 375 · 393 · 412, 폭마다 안드로이드 크롬 · iOS 사파리 UA
.venv/bin/python etc/labs/mobile_tour/run.py 8992 --ua kakao            # 카카오톡 인앱 (naver · instagram 도)
.venv/bin/python etc/labs/mobile_tour/run.py 8992 --widths 375 --deck battery-fastcharge --full
# 3) 끄기
kill "$(cat /tmp/b.pid)"
```

| 옵션 | 뜻 |
|---|---|
| `port` (필수) | 브리지 포트. 주소는 `http://127.0.0.1:<port>` (`--host` 로 바꿈) |
| `--widths` | 쉼표로 폭 고르기. 높이 · DPR 은 `DEVICES` 표(갤럭시 S24 · 아이폰 SE · 아이폰 15 · 픽셀 8 프로) |
| `--ua` | `kakao` · `naver` · `instagram` — 인앱 UA. 끝 화면 「내 자료로 직접 해 보기」 가 바깥 브라우저 안내 시트를 띄우는지 본다 |
| `--deck` | 자료 화면에서 고를 투어 id. 없으면 `index.json` 의 `default` |
| `--full` | 모든 화면의 본문 전체 높이 사진도. 없어도 긴 화면(시작 · 자료 · 분석 · 질문 판정 · 리포트)은 `_full.png` 를 찍는다 |
| `--no-stress` | 버팀 검사를 건너뛴다. 기본은 폭마다 한 번 더 연다(`stress_<폭>/`): team.json 을 바꿔치기해 띄어쓰기 없는 긴 영문 덩어리를 넣은 팀 카드 폭 · 둘째 카드의 「n / N」 이 아래 고정 버튼에 가리는지 · 장 그림과 표지를 막았을 때 깨진 그림 대신 「N장 · 제목」 카드가 있는지 (10-12 점검) |

크롬 헤드리스가 `libasound.so.2` 없이 못 뜨는 이 VM 에서는 `/tmp/pwlibs/usr/lib/x86_64-linux-gnu`(있으면)를 `LD_LIBRARY_PATH` 에 붙여 띄운다(`PW_LIBS` 로 바꿈).

## 따라가는 길

1. `/hi` 첫 화면 → 팀 소개 목록(한 사람 한 줄, 10-12) 사진 → 맨 아래
2. 「척척발표 살펴보기」(`#explore-btn`) → `#/tour` 시작 → 자료(→ `--deck`) → 발표 재생
3. 발표: 멈춘 뒤 CDP `Input.dispatchTouchEvent` 로 왼쪽 · 오른쪽 밀기 — 장 번호가 1→2→1 인지(10-08 pan-y → pointercancel 사고)
4. 분석 → 질문마다 「잘 답한 답」 · 「엉성한 답」 사진(질문 수는 데이터대로) → 리포트 → 끝
5. 「내 자료로 직접 해 보기」: 보통 UA 는 `#/rehearsal` 로 가고 투어 층이 걷혔는지, 인앱 UA 는 안내 시트가 떴는지
6. 「팀 소개로 돌아가기」 → `/hi` 랜딩, 옛 링크 `/index.html#/hi` → `/hi` 넘김

## 결과 — `out/<시각>/` (git 무시)

- `<ua>_<폭>/NN_<화면>.png` (+ `_full.png`) — **사람이 Read 로 직접 연다.** 표가 깨끗해도 줄바꿈 · 겹침 · 잘림은 사진에서만 보인다.
- `report.json` — 폭마다
  - `steps[화면]`: 주소 · 가로 넘침(`hscroll` · 안쪽 가로 스크롤 칸 밖으로 나간 요소) · 44px 미만 누를 곳(지금 화면 안) · 주 버튼이 화면 안에 다 보이는가 · 제목 · 장 번호
  - `console`(error · warning · pageerror) · `failed`(4xx/5xx · 네트워크 실패) · `api`(나간 /api/ 요청) · `funnel`(신호 본문 · 상태) · `checks`(카드 수 · 질문 수 · 밀기 · 이동 주소)
  - `problems`: 위에서 뽑은 문제 목록. 하나라도 있으면 **종료 코드 1**
- 불러도 되는 API 는 `OK_API`(퍼널 신호 · 앱 첫 팀 확인 · 연결 감시 health)뿐이다. 그 밖의 `/api/` 는 투어가 과금 경로를 부른 것이라 문제로 센다.
- 퍼널 신호는 요청 때 적는다. 누르자마자 페이지가 바뀌는 신호(`explore` · `back_team`)는 응답이 이 페이지에 안 와서 `status: null` 일 수 있다 —
  서버에 닿았는지는 브리지 로그 `tour step=…` 줄로 본다. keepalive 요청의 `ERR_ABORTED` 는 크롬이 그렇게 알릴 뿐이라 실패로 안 센다.

## 2026-10-12 첫 실행에서 잡은 것

- 투어가 화면 이름(`deck` …)을 그대로 보내 퍼널 서버가 400 으로 거절 → `funnelStep()` 으로 계약 이름(`tour_deck` …)
- 투어 「팀 소개로 돌아가기」 가 앱 해시 `#/hi`(앱에 없는 화면 → 홈) → `/hi` 랜딩
- A-1 · B-1 덱 제목이 표지 머리줄(「배 터 리 공 학 과 …」) → `build.py` `letter_spaced()`
- 팀 카드 점이 32×44 → 44×44, 점 줄을 버튼 위 한 줄로
- 360 폭 끝 화면 「팀 소개로 돌아가기」 가 두 줄로 접힘 → 둘째 줄 버튼은 15px 한 줄
