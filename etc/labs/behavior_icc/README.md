# 행동 지표 사람 검증 키트 (etc/labs/behavior_icc)

카메라 행동 지표(화면 쪽 비율 · 아래 본 시간 · 손 움직임 비율 · 몸 흔들림 시간 · 긴 이탈 횟수)가 **사람 눈과 얼마나 맞는지**를
결선(11/3) 전에 팀 다섯 명이 직접 재는 도구예요. 결과로 지표마다 **총점 후보 / 베타 / 숨김**을 정해요.
설계 근거: `~/meetings/리서치/2026-10-17_행동추적_근거조사.md` §6 · 계획서 `…_고도화_계획.md` §4.

```
촬영 (사람마다 6편, 20~25분)  →  코딩 (사람마다 12편 + 훈련 2편, 약 2시간)  →  엔진 실행 (서버, 약 1시간 자동)  →  분석 · 판정 (1분)
docs/behavior-icc/촬영대본.md      web/coder.html + serve.py                    engine_run.py                       analyze.py → report.md
```

## 누가 무엇을

| 역할 | 누가 | 할 일 | 시간 |
|---|---|---|---|
| 진행 담당 | 1명(QA 담당) | 번호 정하기 · 배정표 · 파일 모으기 · manifest · 엔진 실행 · 분석 · 결과 공유 · **삭제** | 약 2시간(대부분 기다림) |
| 발표자 | 5명 모두 | 촬영 대본대로 6편 찍기 | 20~25분 |
| 감독 | 짝 1명 | 스톱워치 보며 신호 주기(발표자와 번갈아) | 20~25분 |
| 코더 | 5명 모두 | 훈련 2편 → 맞추기 모임 → 배정된 12편 코딩(**본인 영상은 빼요**) | 약 2시간 |

권장 일정: 10/20~22 촬영 · 10/23 훈련 코딩 + 맞추기 모임(30분) · 10/24~29 본 코딩 · 10/30 엔진 실행 · 분석 · 10/31 판정 반영 · 11/10 까지 삭제.

---

## 1. 촬영 (발표자 · 감독)

`docs/behavior-icc/촬영대본.md` 를 인쇄해서 그대로 따라 해요. 동의서 서명 → 자리 잡기 → 여섯 상황(① 평소처럼 ② 원고 자주 보기 ③ 몸 흔들기 ④ 손짓 많이
⑤ 화면 밖 자주 보기 ⑥ 자유, 각 60~90초) → 파일 이름 `p번호_c상황번호.mov`. 훈련 영상 `train1`, `train2` 도 두 사람이 한 편씩 찍어요.

## 2. 모으기 (진행 담당)

```bash
# 서버에서 (127.0.0.1 만 쓰는 도구들이에요 — 8799 공개 서비스와 상관없어요)
cd ~/project/chuckchuck          # 이 키트가 main 에 들어간 뒤. 그 전엔 /data/models/_wt/wt-behavior-lab
PY=/home/yehschuck/project/chuckchuck/.venv/bin/python
python3 etc/labs/behavior_icc/assign.py          # → /data/models/_runs/behavior-icc/배정표.csv + 사람별 12편 목록
mkdir -p /data/models/_runs/behavior-icc/clips   # 영상 32편(30 + 훈련 2)을 여기에 — scp 나 USB
# manifest.csv 를 같은 폴더에 (촬영대본 §5 표: clip,split,glasses,light,device,note)
```
코더에게는 **배정된 영상만** USB 나 팀 서버에서 받아 가게 해요(메신저 금지). 배정표 규칙: 사람 p 의 ①~③ 은 p+1 · p+2, ④~⑥ 은 p+3 · p+4 가 코딩해요(번호는 돌려 셈).

## 3. 코딩 (코더 모두, 약 2시간)

설치할 것이 없어요. 저장소를 받은 노트북에서(맥 기본 `python3` 로 돼요):
```bash
python3 etc/labs/behavior_icc/serve.py          # → 크롬에 http://127.0.0.1:8840/coder.html 이 열려요 (끝낼 때 Ctrl+C)
```
저장소가 없으면 `web/coder.html` 파일 하나만 받아 크롬으로 열어도 돼요(더블클릭).

1. **내 번호**(p1~p5)를 적고 **영상 열기** → 내 디스크의 영상을 골라요. 영상은 어디로도 올라가지 않아요.
2. 한 초가 재생돼요. 그 1초를 보고 표시해요.

| 키 | 하는 일 |
|---|---|
| `1` `2` `3` `4` | 시선: 화면 쪽 · 다른 곳 · 아래 · 자리 없음 (그 1초 동안 **가장 오래** 향한 쪽) |
| `H` | 손 움직임 있음 ↔ 없음 |
| `S` | 몸 좌우 흔들림 있음 ↔ 없음 |
| `Space` | 저장하고 다음 초(바로 재생) |
| `←` `→` | 이전 · 다음 초 · `R` 다시 보기 · `C` 앞뒤 3초 보기 · `U` 빈칸으로 |

   새 초로 넘어가면 **앞 초의 표시를 이어받아요** — 대부분은 `Space` 만 누르면 돼요. 한글 입력 상태여도 키가 먹어요.
3. 저장은 자동(이 브라우저 안)이에요. 창을 닫았다가 같은 파일을 다시 열면 빈칸부터 이어 해요.
4. 한 편을 끝내면 **이 영상 CSV 받기** → `icc_p3_p1_c4.csv` 같은 파일을 진행 담당에게 줘요(또는 마지막에 **내 것 전부 받기** 한 번).
   다른 브라우저 · 컴퓨터로 옮겨 이어 하려면 **CSV 불러오기**.

**기준**(코딩판 「기준 다시 보기」와 같아요)
- 화면 쪽: 얼굴이 노트북 화면 · 카메라 쪽. 고개를 조금(대략 30° 안) 돌린 것, 눈만 내리깐 것도 화면 쪽.
- 다른 곳: 옆 · 위 · 뒤로 고개를 돌림. 아래: 고개를 숙여 책상 · 원고 · 키보드를 봄. 자리 없음: 얼굴이 화면 밖이거나 반 넘게 안 보임.
- 손 움직임 있음: 그 1초에 손이 눈에 띄게 움직임(손짓 · 만지작 모두). 손이 안 보이거나 가만하면 없음.
- 몸 흔들림 있음: 상체 · 머리가 좌우로 왔다 갔다를 되풀이하는 중. 자세를 한 번 고쳐 앉는 건 없음.
- 엔진 결과는 코딩판에 없어요(눈가림). 다 끝나기 전에 엔진 결과나 다른 사람 CSV 를 보지 않아요.

**순서**: 모두 `train1` · `train2` 를 먼저 코딩 → 진행 담당이 `analyze.py --train` 으로 갈린 초 목록을 뽑아 → **30분 모여서** 갈린 초를 같이 보고 기준을 맞춤 → 본 코딩 12편.

**시간 어림**: 1초 코딩에 3~5초 → 75초 영상 한 편에 5~6분. 12편 ≈ 70분 + 훈련 2편 ≈ 15분 + 맞추기 모임 30분 ≈ **2시간**. 30분씩 끊어서 해요(지치면 정확도가 떨어져요).

## 4. 엔진 실행 (진행 담당, 서버)

```bash
export PATH=$HOME/.local/bin:$PATH            # ffmpeg
$PY etc/labs/behavior_icc/engine_run.py --run real_1030 --jobs 2
#   → /data/models/_runs/behavior-icc/engine/real_1030/ labels/*.csv · engine_metrics.csv · preds/*.json · meta.json
#   실패한 편만 다시: --skip-done   몇 편만: --only p1_c1,p2_c3   다른 엔진: --web /data/models/_wt/wt-behavior-cv/main/web
```
- 영상마다 ffmpeg 로 640폭 · 15fps y4m 으로 바꾸고 오른쪽 위 80×6px 에 프레임 번호 바코드를 새겨, 헤드리스 크롬 가짜 카메라로 **실제 앱과 같은 엔진**(`main/web/js/behavior_cv*.js`)을 돌려요.
  정답 실험실(`etc/labs/behavior_cv`)의 `browser_adapter.py` · `harness.html` · `labtap.js` 를 그대로 써요. 엔진 API 가 바뀌면 어댑터(`web/adapter_default.js`)만 고쳐요.
- 영상 길이만큼 실시간으로 돌아요(32편 × 75초 ÷ 2 ≈ 25분). 포트 127.0.0.1:8841~8844. 바꾼 y4m 은 끝나면 지워요.
- 1초 라벨 규칙: 그 초에 엔진이 본 줄(약 5장)의 다수결 시선 · 손 · 흔들림이 절반 이상이면 있음. 엔진이 리포트에 실제로 내는 값은 `native_*` 칸에 같이 남겨요.

## 5. 분석 · 판정 (진행 담당)

```bash
$PY etc/labs/behavior_icc/analyze.py --engine real_1030 --out train --train      # 훈련 영상: 코더끼리 어디서 갈렸나 → report/train/train_check.md
$PY etc/labs/behavior_icc/analyze.py --engine real_1030 --out real_1030          # 본 분석 → report/real_1030/report.md
```
CSV 는 `/data/models/_runs/behavior-icc/ratings/` 에 모두 넣어요(같은 초가 여러 번이면 나중에 코딩한 것을 써요).

보고서 `report.md` 에서 볼 것:
- **§0 판정 표** — 지표마다 「엔진 ↔ 사람 두 명 평균」 **ICC(2,1) 절대 일치**와 95% CI. **하한**이 ≥ .75 → **총점 후보**, .50~.75 → **베타**(가중치 0, 「베타」 표시), < .50 → **숨김**.
- 사람끼리 ICC 하한이 .50 아래인 지표는 「엔진 탓 전에 정의부터」 — 기준을 고치고 그 지표만 다시 코딩해요.
- §2 Bland–Altman(엔진이 일정하게 많이 · 적게 재는지), §3 1초 κ · 혼동 행렬, §4 구간 F1(±1초 · IoU≥.5), §5 상황별 차이, §6 영상별 값, §7 빠진 CSV · 본인 코딩 경고.
- 판정을 엔진에 반영하면(문턱을 이 자료로 고치면) 그 뒤 수치는 「같은 자료로 맞춘 값」이라고 적어요. 이름은 「검증」이 아니라 **예비 신뢰도 점검**이에요.

## 6. 정리 (진행 담당, 11/10 까지)

```bash
rm -rf /data/models/_runs/behavior-icc/clips /data/models/_runs/behavior-icc/engine/*/_y4m
# preds/*.json 은 얼굴 상자 좌표 같은 숫자만 있지만 함께 지워도 돼요 — 보고서 · CSV(숫자)만 남겨요
```
코더 노트북의 영상 복사본도 지우고 팀 채널에 「지웠어요」를 남겨요. 브라우저 저장분은 코딩판을 연 채 개발자 도구 → Application → Local Storage 에서 `bicc1:` 로 시작하는 칸을 지우면 돼요.

---

## 스스로 점검 (이 키트가 맞게 도는지)

진짜 영상 없이 **합성 영상**(정답 실험실 26편)과 정답에서 만든 **가짜 코더**(잡음 · 경계 늦음 · 치우침이 다른 sim1 · sim2 · sim3)로 전체 흐름을 돌려요.
```bash
PATH=$HOME/.local/bin:$PATH $PY etc/labs/behavior_icc/selftest.py            # 엔진까지 (≈ 10분, --jobs 3)
$PY etc/labs/behavior_icc/selftest.py --reuse-engine                         # 엔진 결과는 그대로
$PY etc/labs/behavior_icc/selftest.py --coder-only                           # 코딩판만(헤드리스 크롬으로 키 · 이어 하기 · CSV)
$PY etc/labs/behavior_icc/test_stats.py                                      # ICC 공식을 Shrout & Fleiss(1979) · pingouin 0.7 과 맞춰 보기
```
점검하는 것: ① 코딩판 키 · 이어받기 · 새로 고침 뒤 이어 하기 · CSV 받기가 분석기에서 그대로 읽힘 ② 가짜 코더끼리 ICC 가 높게 나옴
③ **음성 대조** — 엔진 라벨을 영상끼리 뒤섞으면 어떤 지표도 「총점 후보」가 안 나옴 ④ 훈련 점검 · 보고서 파일.
결과: `/data/models/_runs/behavior-icc/report/selftest/report.md`(합성이라 **수치로 판정하지 않아요**).

## 파일

| 파일 | 하는 일 |
|---|---|
| `web/coder.html` · `serve.py` | 1초 코딩판(눈가림) · 127.0.0.1 전용 정적 서버(표준 라이브러리만) |
| `assign.py` | 배정표(본인 영상 빼고 영상마다 두 명, 사람마다 12편) |
| `engine_run.py` | 영상 → y4m + 바코드 → 헤드리스 크롬 엔진 → 1초 라벨 · 영상별 지표 |
| `common_icc.py` | 경로 · 라벨 규약 · **지표 정의(사람과 엔진이 같은 함수)** · CSV |
| `stats_icc.py` | ICC(2,1)·ICC(1,1) + 95% CI(McGraw & Wong 1996) · Bland–Altman · Cohen κ · 구간 F1 · 판정 |
| `analyze.py` | 보고서 `report.md` · `clip_metrics.csv` · `seconds.csv` · `summary.json` · 훈련 점검 |
| `selftest.py` · `test_stats.py` | 스스로 점검 · 통계 맞춰 보기 |

**CSV 모양** — 코딩판: `rater,clip,sec,gaze,hand,sway,file,dur,coded_at` · 엔진 라벨: `clip,sec,gaze,hand,sway,n_rows`.
`gaze` ∈ `screen`(화면 쪽) · `away`(다른 곳) · `down`(아래) · `absent`(자리 없음), `hand` · `sway` ∈ 0/1. 초 `s` = 영상의 [s, s+1).

**지표 정의**(`common_icc.clip_metrics`) — 분모는 자리 있는 초(화면 쪽 · 다른 곳 · 아래).
화면 쪽 비율 = 화면 쪽 초 ÷ 자리 있는 초 · 아래 본 시간 = 아래 초 · 손 움직임 비율 = 손 있음 초 ÷ 자리 있는 초 · 몸 흔들림 시간 = 흔들림 있음 초 ·
긴 이탈 횟수 = 다른 곳 · 아래가 **4초 이상** 이어진 구간 수(엔진의 「3초 넘게」를 1초 단위로). 세 출처가 모두 라벨을 가진 초만 써요.

**경로** — 결과는 모두 `/data/models/_runs/behavior-icc/`(루트 디스크가 작아요): `clips/` · `ratings/` · `engine/<run>/` · `report/<out>/` · `pylib/`(pingouin, 점검용) · `selftest/`.
