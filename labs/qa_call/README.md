# 통화형 Q&A 실험실 (`labs/qa_call`)

부스 통화 화면(`demo/YEHS_demo/booth.html`)만 **떼어서** 단계별로 돌려 보는 자리다. 앱(`index.html`)은 건드리지 않는다.
헤드리스 크롬 + 가짜 카메라로 실 API 브리지에 붙어, 단계마다 스크린샷과 보고(JSON)를 남긴다.
이 서버에는 브라우저가 없어서 이 방법이 통화 화면을 "보는" 유일한 길이다 (2026-09-18).

## 준비 (한 번)

```bash
.venv/bin/pip install playwright pillow
.venv/bin/python -m playwright install chromium
# libasound.so.2 가 없다고 하면 (이 서버가 그렇다) — 루트 없이:
mkdir -p /tmp/pwlibs && cd /tmp/pwlibs && apt-get download libasound2t64 && dpkg -x libasound2t64_*.deb . && cd -
export LD_LIBRARY_PATH=/tmp/pwlibs/usr/lib/x86_64-linux-gnu
```

브리지는 **새 코드**로 떠 있어야 한다 (`MIDM_PY=… DEMO_PORT=8801 ./demo/run_bridge_midm.sh`). 실 API·실 과금이다.

## 돌리기

```bash
.venv/bin/python labs/qa_call/run.py all                    # 전 단계, 데스크톱 1280×860
.venv/bin/python labs/qa_call/run.py call-answer --mobile   # 폰 390×844, 답·판정까지만
.venv/bin/python labs/qa_call/run.py freeze                 # 지금 booth 파일을 out/snapshots/<stamp>/ 에 얼린다
```

| 단계 | 무엇을 보나 | 사진 |
|---|---|---|
| capture | 사진 2장이 썸네일로 담기는가 | `1_capture.png` |
| analyze | 파싱→개념→그래프→질문 실측 초, 실패면 실패 문구 | `2_analyze_*.png` |
| call-ask | 내 모습(가짜 카메라) + 병아리 + 질문 말풍선, 마이크 상태 | `3_call_ask.png` |
| call-answer | 답 → 판정 pill·요약·빠진 것·되묻기 말풍선, 병아리 기분 | `4_call_answer.png` |
| call-hint | 힌트 말풍선 | `5_call_hint.png` |
| call-giveup | 다음 질문 → 「모르겠어요」 → 정답 요지 | `6_call_giveup.png` |
| finish | 통화 마치기 → 결과 카드 | `7_finish.png` |

`report.json` 에 단계별 초·판정·기분·말풍선 본문·콘솔 오류가 남는다. `out/` 은 git 이 무시한다.

## 못 보는 것

- **실제 마이크·실시간 받아쓰기** — 헤드리스 크롬은 구글 음성 서버에 못 붙는다. 답은 자막에 타이핑해 넣는다.
- **읽어 주기(TTS)** — 헤드리스에 음성이 없다. 켜도 소리는 안 난다.
- 그래서 마이크·소리는 부스 컴퓨터 리허설(`docs/plan/booth-screen-qa.plan.md` §6-2)에서만 확인된다.

## 사진 고정물

`fixture_slide1.jpg`·`fixture_slide2.jpg` 는 멘토링 신청 폼 스크린샷을 폰 사진처럼(기울임·배경·JPEG 78) 만든 것이다.
다른 자료로 보려면 `--photos a.jpg b.jpg`.
