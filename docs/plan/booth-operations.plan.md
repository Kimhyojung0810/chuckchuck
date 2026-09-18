# 부스 운영 설계 — 카메라·음성 Q&A 를 부스에서 어떻게 돌릴 것인가 (2026-09-18)

> 사용자 요청(9/18): "앞으로 어떤 설계 방식으로 디벨롭하고 실제 부스 운영을 어떻게 해나갈지,
> 평가가 좋았던 부스 운영 방식들을 리서치한 다음 어떻게 제공하는 게 좋을지 판단."
> 상태: **조사 + 제안. 결정은 팀 몫** (부스 리허설 10/5, 회의록 할 일 #14 전에). 코드가 필요한 항목은 §8 에 우선순위로.
> 표기: **[근거]** 출처가 있는 사실 · **[판단]** 그 근거를 우리 상황에 대입한 제안. 못 찾은 것은 §10 에 그대로 적었다.
> 체험 화면 자체는 [booth-screen-qa.plan.md](booth-screen-qa.plan.md).

## 0. 결론 다섯 줄

1. **흐름은 2단.** 통로 쪽에 90초 무음 리플레이(어트랙터), 안쪽에 3~4분 체험(`booth.html`). 다음 체험 시작 시각을 통로에 써 둔다.
2. **기본 트랙은 부스 노트북 + 웹캠(또는 USB 문서 카메라) + 유선 헤드셋.** 방문객 폰으로 직접 참여하는 트랙은 https 터널이 있을 때만 — 실 API 브리지는 `DEMO_HOST=127.0.0.1` 이 규칙이다(CLAUDE.md §2).
3. **스테이션 2대 · 역할 3(맞이·진행·마무리) · 90분 교대.** 리셋 포함 5분/명 → 스테이션당 하루 60~70명이 상한. 3일 완주 300~400명이 현실적이다.
4. **소음 대책은 이미 코드에 있는 규율을 지키는 것이다.** 마이크는 채워만 주고 보내지 않는다(받아쓴 글 확인 → 답하기). 첫날 오전 현장에서 인식률을 재고, 안 되면 타이핑을 기본으로 바꾼다.
5. **아직 없는 것 셋** — 결과 카드(QR), 측정 이벤트 5개, 동의 2단 체크. 이 셋이 있어야 "잘 됐는지" 를 숫자로 안다 (§8).

## 1. 전제 — AI Festa 2026 이 어떤 자리인가

**[근거]**
- 주최 과학기술정보통신부, 주관 한국소프트웨어산업협회(KOSA)·조직위. 2026 규모 **216개사 501부스**, 9개 테마존. COEX 3층 C홀 등. Google DeepMind·AWS·Anthropic 등 참여. 사전등록 무료, 마감 10/2 18:00 (ZDNet Korea 2026-09-17).
- 관람 10/6~7 10:00~17:00, 10/8 10:00~16:00. 코엑스 소개문은 관객을 "AI 분야 비즈니스 종사자"로 규정한다 (코엑스 전시 안내).
- 2025년은 A홀이었다. 2026 은 C홀 — 지난해 동선 후기는 그대로 못 쓴다.
- 부스 기본 모듈 3m×3m (2025 모집 공고). 비교치: 같은 코엑스에서 열린 AI EXPO KOREA 2026 은 562부스 3일 48,678명, 하루 약 1.6만 명.
- "2025 관람객 6만 명" 은 원문에서 확인하지 못했다. 인용하려면 사무국(info@aifesta.kr) 확인.

**[판단]**
- 방문객은 "일반 대중" 이라기보다 **업계 종사자 + 학생·취준생 혼합**이다. "내 발표 자료로 면접·발표 리허설" 프레임이 둘 다에 먹힌다.
- 501부스면 소음은 대형 전시 급으로 잡는다 (§4).
- 3m×3m 에 스테이션 2대 + 통로 쪽 모니터 1대가 물리적 상한이다.

## 2. 체험 설계 — 무엇을 몇 분 동안 보여 주나

**[근거]**
- **90초 엣지 데모 + 안쪽 긴 데모의 2단 구조.** 통로에서 걷다가 볼 수 있는 90초, 두 번째 질문을 하는 사람에게 안쪽 10분. 정해진 시각에 돌리고 "다음 데모 2:15" 를 게시하면 돌아올 이유가 된다 (Pure Exhibits).
- 데모 하나에 'aha' 하나. 완료율 70% 이상을 목표로 (Guideflow).
- 게임 전시 실측(PAX Aus): 5분 데모 · 스테이션 2대 · 1인당 7~10분 처리(착용·설명 2~3분 포함) · 최대 대기 20분. **한 키로 처음으로 되돌리는 리셋**이 흐름을 살렸다 (Game Developer).
- 음성 데모 전문가(CES): "경로 하나를 정해 여러 번 시험하고, 데모 때 정확히 그 경로만 간다." "백업은 노트북에 내려받은 영상." "실패하면 왜 실패했는지 솔직히." "**실제 전시장 환경에서 시험하라**" (Bouzid).
- 스태프가 내레이션하며 **핵심 순간에 방문객에게 조작을 넘기는 라이브 데모**가 영상 루프·무인 키오스크보다 꾸준히 성과가 좋았다 — 기술이 안정적일 때 (Pure Exhibits).
- YC Demo Day 사례: 프로토타입이 멈추고 백업 영상까지 재생 실패 → "불안정" 으로 기억됨. 백업도 리허설한다.
- 한국 스타트업 전시 후기: "바이어들은 실제 만져보고 작동해 보길 원한다. 앉아 있는 팀은 패스당한다" (brunch).

**[판단] 우리 루프**
- 안쪽 체험 = `booth.html`: 찍기 20초 → 분석 19~30초 → 질문 3개 × (답 30초 + 판정 2초) → 결과. **3~4분**. 이것이 'aha' 하나: *내 자료를 읽고, 내 답을 자료와 대조한다.*
- 통로 = **90초 무음 리플레이**: 샘플 자료 → 질문 → 답 → 판정 카드가 넘어가는 영상 루프(8~15초 어트랙터 + 45~90초 설명, Motion Bloc). 지금 코드에 없다 — 리허설 때 화면 녹화로 만든다 (§8).
- **"내 자료 vs 준비된 샘플" 은 2트랙.** 기본은 준비된 샘플 3종(학생 발표·스타트업 IR·업무 보고)을 고르게 하고, 본인 자료를 폰에 들고 온 사람만 카메라 트랙. 샘플은 미리 분석해 30초 대기를 없앨 수 있되 화면에 「샘플 자료」 표시를 남긴다 — 실패를 샘플로 위장하지 않는다는 원칙과 충돌하지 않게.
- PAX 의 "한 키 리셋" = `booth.html` 의 「다른 자료로 다시 하기」. 리셋이 20초를 넘으면 처리량이 눈에 띄게 준다. 스태프용 단축키(예: `Esc` 두 번)는 없다 — 필요하면 §8.
- **백업 3단**: ① 미리 분석해 둔 샘플 결과 ② 노트북에 내려받은 데모 영상 ③ 폰 핫스팟. 셋 다 부스에서 직접 켜 본다.
- Bouzid 의 규칙대로 **리허설 때 정한 경로(샘플 A → 질문 3개 → 답 대본)만 시연**한다. 즉흥은 방문객 몫이다.

## 3. 대기줄·인력

**[근거]**
- 배치: "둘은 밖, 하나는 데모, 하나는 유동. 90분마다 교대" — 통로 쪽은 지친다. "열 명이 기다리는 줄이 열한 번째를 어떤 그래픽보다 잘 끈다" (Pure Exhibits).
- 역할 5종(맞이·리드 캡처·데모 진행·모으기·캡틴). 처리 예시: 인사 8초 + 자격 확인 25초 + 인계 15초 ≈ 50초 (eventstaff.com · premierstaff.com).
- 인디 부스: 주요 시간엔 최소 2명, 하루 8~9시간 말하니 목 관리 (Game Developer pro-tips).
- 대기 심리(Maister 1985): **할 일이 있는 대기가 짧고, 설명 없는 대기가 길다.** PAX: 사과 대신 "기다려 줘서 고마워요" 가 체감을 리셋한다.
- 처리량 참고치: 중형 전시 하루 80~200명 방문·10~25 리드, 스태프 1인당 하루 25~35 리드가 "strong" (levelbooths · chococraft, 2차 인용).

**[판단]**
- **스테이션 2대**가 상한: 진행 2 + 맞이/마무리 1 + 예비 1 = 4명. 3~5명 교대면 딱 맞다. 팀이 3명인 시간대는 스테이션 1대로 줄인다.
- 1스테이션 = 리셋 포함 **5분/명 → 시간당 10~12명, 하루 6시간 60~70명.** 3일 합계 300~400명 완주가 현실적 상한. 이 숫자를 넘는 목표는 세우지 않는다.
- **대기 중 볼 것** = 진행 중인 세션의 질문·판정 카드를 (동의하에) 통로 쪽 모니터에 미러링. 어트랙터이자 교육이다. `booth.html` 의 「작은 창으로 띄우기」(Document PiP)를 외부 모니터로 끌어다 놓으면 지금 코드로도 된다 — 리허설에서 확인.
- 예상 대기를 숫자로("약 8분") 화이트보드에. 가상 큐(문자 호출)는 개인정보 절차가 붙어 우리 규모에선 **종이 번호표 + 화이트보드**가 더 싸고 실패가 없다.

## 4. 소음 홀에서 말로 답하기

**[근거]**
- SNR 15dB→5dB 면 인식 오류율(WER)이 2배, 10dB 미만에서 급락. 조용한 방 6% 가 현장 30%+ 로 (Deepgram · Forasoft).
- 상시 소음 환경은 **푸시투톡 + 헤드셋(붐 마이크) + 유선**, 짧은 발화·타이핑 혼용 (Weesper).
- Bouzid: 소음 환경에서 웨이크워드 기기는 음소거, 팬·대형 스크린 앞 배치 금지, 실패 시 "너무 시끄럽다" 고 솔직히.
- 공개 실패: LG CES 2018 키노트의 CLOi 로봇 무응답 (TechCrunch).
- VUI: 인식 실패 시 "이해하지 못했어요" 대신 가벼운 재질문 (Google Design).
- **라이브 자막이 만족을 높인다는 정량 근거는 없다.** 오히려 중간 텍스트가 "읽고 고치기" 로 끌어 발화를 흐트러뜨린다는 반론 (thegenacademy).

**[판단]**
- 이미 코드가 지키는 규율이 정답과 같다: **받아쓴 글을 확인한 뒤 「답하기」**(채워만 주고 보내지 않는다). 실시간 자막은 크롬에서만 켜지고, 죽으면 녹음+STT 로 간다.
- 하드웨어: **유선 헤드셋(붐 마이크)** 1인 1개가 아니라 스테이션당 1개 + 알코올 티슈. 블루투스는 페어링·지연으로 리허설 시간을 먹는다.
- **첫날 설치 오전에 현장 소음에서 10문장 인식률을 잰다** (Bouzid 의 "같은 환경" 원칙). 5/10 아래면 그날은 타이핑을 기본 버튼으로 바꾸고 마이크는 보조로 둔다 — 지금은 마이크가 `btn-tint`, 답하기가 `btn-primary` 라 순서만 바꾸면 된다.
- 인식 실패 문구는 이미 "말소리를 못 알아들었어요. 다시 말하거나 타이핑으로 답해 주세요." — 소음을 탓하는 문장("소음이 커서") 한 줄을 부스 버전에 붙일지는 리허설에서 정한다.
- 무대 스피커 옆 배정이면 사무국에 위치 조정을 요청한다. 도면은 사무국에서 받아야 한다.

## 5. 방문객 폰·카메라 참여와 개인정보

**[근거]**
- 현장 수집은 개인정보 수집·이용 동의(목적·항목·보유기간·거부권) 필수, 목적 달성 시 즉시 삭제, 암호 없는 엑셀 공유가 위반 사례 (캐치시큐). 응모 동의와 마케팅 동의는 목적이 달라 **분리**.
- 개인정보위 「생성형 AI 개발·활용 개인정보 처리 안내서」(2025-08): 프롬프트·결과가 다시 학습에 쓰이면 '처리' 에 해당. **학습 이용 목적은 동의 전 고지사항에 명확히.** 정당한 이익 조항은 공개된 정보 대상이라 업로드 자료엔 곧바로 못 쓴다 (korea.kr · 법무법인 세종 뉴스레터).
- 폰 QR 참여 사례는 있으나 참여율 수치는 없다.

**[판단]**
- **폰 트랙은 기본이 아니다.** 실 API 브리지는 `127.0.0.1` 만 듣는 것이 규칙이고(과금·키 보호), 폰에서 카메라·마이크를 열려면 https 가 필요하다. Cloudflare Tunnel + Access(DEPLOYMENT 검토안)가 있을 때만 "QR 로 내 폰에서" 를 연다. 없으면 **방문객이 폰 화면을 부스 웹캠에 보여 주고, 부스 노트북에서 찍는다** — `booth.html` 의 「카메라로 찍기」가 이 경우다.
- 동의는 **2단 체크** — (필수) "담은 장면과 답은 지금 질문·판정에만 쓰고 세션이 끝나면 지워요" / (선택, 기본 꺼짐) "익명으로 모델 개선에 쓰는 데 동의해요". 지금 화면엔 필수 쪽 한 줄 안내만 있고 체크박스는 없다 (§8). 브리지의 `consent_learning` 쿼리는 이미 있다 (`_handle_parse`).
- 부스 벽에 A4 한 장: 수집 항목·목적·보유기간·문의처. "회사 자료는 공개해도 되는 것만" 은 화면에 넣었다.
- 서버 보관은 동의 세션만 (`session_archive` 의 consent 경로 그대로). 동의 없는 세션의 원본은 남기지 않는다 — 현재 코드가 그렇게 돈다는 것을 리허설에서 `var/data` 로 확인한다.

## 6. 가져가는 것 · 후속 · 측정

**[근거]**
- 리드 폼은 **가치를 준 뒤에**, 3~5개 필드. 48시간 안에 연락한 리드가 일주일 뒤보다 3배 전환 (Guideflow · mobilelightbox).
- 체험형 포토부스: QR 로 결과물 회수, 결과물과 교환으로 이메일 옵트인이 자연스럽게 들어온다. 리포트는 세션 수·고유 참가자·공유 수·옵트인 수 (Snapbar).
- 설문 응답률: 현장 QR 30~50%, 키오스크 50~70%, 사후 이메일 10~15% (qrsage · portma).
- 측정: 데모 완료율이 1차 지표, 목표 70%+. "데모당 사람 수, 데모당 스캔 수, 통로→안쪽 전환" (Guideflow · Pure Exhibits).

**[판단]**
- 세션 끝에 **결과 카드 1장**(질문 3개 + 판정 + 한 줄) 을 QR 로 폰에 내려받게 한다. 카드는 이메일 없이 열리고, 이메일은 **선택**으로만 — 다크패턴 금지. "친구 태그" 유도 문구는 넣지 않는다 (토스 규율).
- NPS 는 카드 페이지에 1문항(0~10). 현장 QR 30~50% 를 기대치로.
- **대시보드 6칸**: 시작 세션 / 완주 세션(완료율) / 카메라(본인 자료) 트랙 비율 / 마이크 재시도·타이핑 전환 횟수(§4 건강 지표) / 카드 다운로드 수 / 옵트인 수. 브리지 로그에 세션 ID 단위 이벤트 5개만 남기면 된다 — 지금은 없다 (§8).

## 7. 지금 코드가 지원하는 것 / 없는 것

| 운영 요소 | 상태 | 어디 |
|---|---|---|
| 카메라로 찍기 · 화면 공유 · 사진 올리기 | ✓ 09-18 | `booth.js openCamera/startShare/onFiles` |
| 말해서 답하기(확인 뒤 보내기) · 읽어 주기(기본 무음) | ✓ 09-18 | `booth.js toggleMic/speak` |
| 진행 시간 실측 표시 · 실패를 실패로 | ✓ | `booth.js stageStart/stageDone` |
| 「작은 창으로 띄우기」(대기 중 볼 것의 재료) | ✓ (브라우저 미확인) | `booth.js openPip` |
| 세션 리셋(「다른 자료로 다시 하기」) | ✓ | `booth.js restart` |
| 준비된 샘플 3종 트랙 | ✗ | 샘플 자료 + 미리 분석한 결과 + 「샘플」표시 |
| 90초 통로 리플레이 | ✗ | 리허설 때 화면 녹화 → 무음 mp4 루프 |
| 결과 카드(QR) · NPS 1문항 · 이메일 선택 | ✗ | 새 화면(작음) — Festa 잠금 10/1 전 |
| 측정 이벤트 5개(시작·완주·트랙·마이크 전환·카드) | ✗ | 브리지 로그 한 줄씩 |
| 동의 2단 체크박스 | ✗ (한 줄 안내만) | `booth.html` 담기 화면 + `consent_learning` |
| 폰에서 직접(QR) | △ | https 터널이 있을 때만 |

## 8. 다음 작업 제안 (우선순위 · 10/1 잠금 전)

| 순위 | 무엇 | 왜 | 크기 |
|---|---|---|---|
| 1 | **부스 컴퓨터 리허설** — §9 체크리스트 전부 | 카메라·마이크·TTS·PiP 는 이 서버에 브라우저가 없어 한 번도 눌러 보지 못했다 | 반나절 (사람) |
| 2 | **동의 2단 체크박스** + `consent_learning` 연결 | 개인정보위 안내서 기준. 없으면 학습 데이터를 못 모은다 (로드맵 A1) | 반나절 |
| 3 | **측정 이벤트 5개** (브리지 로그) + 하루 끝 집계 스크립트 | 없으면 "부스가 잘 됐나" 를 느낌으로 말하게 된다 | 반나절 |
| 4 | **결과 카드(QR)** — 질문·판정·한 줄, NPS 1문항, 이메일 선택 | 가져가는 것이 없으면 후속이 없다 | 1일 |
| 5 | **샘플 3종 미리 분석 + 「샘플」표시** | 30초 대기를 없애고 실패 백업 1단이 된다 | 반나절 |
| 6 | 90초 리플레이 영상 | 통로 어트랙터 | 리허설 중 1시간 |

1~3 은 없으면 부스가 "돌아는 가지만 남는 게 없는" 상태가 된다. 4~6 은 있으면 좋다.

## 9. 리허설 체크리스트 (부스 컴퓨터 · 10/5 전)

1. `MIDM_PY=… DEMO_PORT=8799 ./demo/run_bridge_midm.sh` → `chk doctor` 전부 ✓ (ffmpeg 포함) → `chk warmup`.
2. 크롬 `http://127.0.0.1:8799/booth.html` — 「카메라로 찍기」 권한 → 미리보기 → 웹캠으로 폰 화면 찍기 → 썸네일 2장 → 「2장으로 질문 만들기」 → 질문 3개가 사진 본문을 인용하는지.
3. 「말해서 답하기」 10초 → 입력창에 글자 → 「답하기」 → 판정. 5회 중 5회 (회의록 세분화 1-b 와 같은 기준).
4. 와이파이를 끊고 마이크를 다시 눌러 녹음+STT 로 넘어가는지 (실시간 받아쓰기는 구글 서버를 쓴다).
5. 「소리 켜기」 → 질문을 읽는지 → 마이크를 켜면 멈추는지 → 소리 끄기.
6. 「작은 창으로 띄우기」를 외부 모니터로 끌어 통로에서 보이는지.
7. 「다른 자료로 다시 하기」 → 20초 안에 다음 사람이 시작할 수 있는지.
8. 화면 공유 트랙(자료가 열린 창) 도 한 번.
9. 실패 3종 시연: 브리지 죽음 → 오류 문구 · 질문 0개 → "다시 찍으면" 문구 · STT 실패 → 타이핑 안내.
10. 현장 첫날 오전: 홀 소음에서 10문장 인식률 → 5/10 아래면 타이핑 기본.

## 10. 못 찾은 것 (정직하게)

- AI Festa 2025 공식 관람객 수 · C홀 도면 · 부스 배정 원칙 — 사무국 문의.
- 국내 전시에서 음성 인식 데모를 운영한 1차 후기.
- "라이브 자막이 체험 만족을 높인다" 는 정량 근거.
- 시간당 방문객/스테이션 업계 표준 — PAX 실측(7~10분/명)이 유일한 1차 자료.

## 출처

- ZDNet Korea, AI Festa 2026 개요 (2026-09-17) — https://zdnet.co.kr/view/?no=20260917100942
- 코엑스 전시 안내 (인공지능 페스타 2026) — https://www.coex.co.kr/exhibitions/%EC%9D%B8%EA%B3%B5%EC%A7%80%EB%8A%A5-%ED%8E%98%EC%8A%A4%ED%83%80-2026/
- 2025 부스 모집 공고 (벤처스퀘어) — https://www.venturesquare.net/announcement/1000427
- AI EXPO KOREA 2026 결과 — https://expo.koraia.org/
- Pure Exhibits, booth activations / demo stations — https://www.purexhibits.com/trade-show-booth-activations/ · https://www.purexhibits.com/trade-show-demo-stations/
- Guideflow, interactive demos at trade shows — https://www.guideflow.com/blog/interactive-demos-trade-shows-events
- Motion Bloc, trade show loop length — https://www.motionbloc.com/trade-show-loop-length
- Game Developer, PAX Aus post-mortem — https://www.gamedeveloper.com/business/preparing-for-surviving-gaming-expos-as-an-indie---a-pax-aus-post-mortem
- Game Developer, pro tips for indie boothing — https://www.gamedeveloper.com/marketing/pro-tips-for-indie-boothing
- Ahmed Bouzid, voice demos at CES — https://www.linkedin.com/pulse/you-giving-voice-demos-ces-ahmed-bouzid
- Storylane, product demos at conferences — https://www.storylane.io/blog/product-demos-conferences
- SaaS Factor, YC Demo Day failures — https://www.saasfactor.co/blogs/behind-the-curtain-when-yc-demo-day-pitches-go-wrong-and-what-every-founder-can-learn
- Snov.io, Web Summit guide — https://blog.snov.io/web-summit-conference-guide/
- brunch, 해외 전시 부스 후기 — https://brunch.co.kr/@@zIH/1307
- eventstaff.com / premierstaff.com, booth staffing roles — https://eventstaff.com/blog/the-anatomy-of-a-high-performing-trade-show-booth-staffing-team · https://premierstaff.com/blog/how-to-find-reliable-trade-show-staffing/
- Maister, The Psychology of Waiting Lines (1985) — https://www.columbia.edu/~ww2040/4615S13/Psychology_of_Waiting_Lines.pdf
- Deepgram / Forasoft, noise-robust ASR — https://deepgram.com/learn/noise-robust-speech-recognition-methods-best-practices · https://www.forasoft.com/blog/article/speech-recognition-accuracy-noisy-environments
- Weesper, dictation in noisy environments — https://weesperneonflow.ai/en/blog/2025-10-21-voice-dictation-noisy-environments-background-noise-solutions/
- TechCrunch, LG CLOi at CES 2018 — https://techcrunch.com/?p=1583947
- Google Design, VUI — https://design.google/library/speaking-the-same-language-vui
- The Gen Academy, why accurate voice AI still feels off — https://thegenacademy.substack.com/p/why-accurate-voice-ai-still-feels
- 캐치시큐, 현장 수집 동의 — https://www.catchsecu.com/archives/13321 · https://www.catchsecu.com/archives/24469
- 보안뉴스, 명함 수집과 동의 — https://m.boannews.com/html/detail.html?idx=40021&kind=0
- 개인정보위 생성형 AI 안내서 (korea.kr) — https://www.korea.kr/news/policyNewsView.do?newsId=148946215 · 해설 https://www.shinkim.com/kor/media/newsletter/2517
- mobilelightbox, trade show ROI framework — https://mobilelightbox.us/measuring-trade-show-display-effectiveness-the-2026-roi-engagement-framework/
- Snapbar, experiential photo booth — https://snapbar.com/blog/what-is-an-experiential-photo-booth
- qrsage / portma, survey response benchmarks — https://qrsage.com/blogs/customer-feedback-survey-qr-codes · https://portma.com/resources/articles/response-rate-benchmarks-from-post-event-surveys/
- levelbooths / chococraft (2차 인용, 참고치) — https://levelbooths.com/insights/trade-show-booth-design-2026-your-complete-guide-as-an-exhibitor · https://chococraft.com/blogs/corporate-gifts/how-many-leads-should-you-expect-from-a-trade-show
- american-image, engagement metrics — https://american-image.com/trade-show-engagement-metrics-ultimate-guide/
