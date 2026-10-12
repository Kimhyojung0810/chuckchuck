# labs/tour_capture — 모바일 체험 투어 녹화 (2026-10-11)

결선 부스 QR → `/hi` → `#/tour/*` 가 재생하는 **녹화된 실제 응답**을 만든다. 투어는 이 파일만 읽고 API 를 부르지 않는다.
계약: [`docs/booth-mobile/tour-schema.md`](../../docs/booth-mobile/tour-schema.md) · [`tour.schema.json`](../../demo/schema/booth-mobile/tour.schema.json) · [`tour-index.schema.json`](../../demo/schema/booth-mobile/tour-index.schema.json).

```
capture.py  ─ 실 API 브리지(8983)로 덱마다 한 흐름 ─▶ out/recordings/<덱>.json   (과금 · 로컬에만, git 무시)
build.py    ─ 녹화본 → 계약 모양 (과금 0)         ─▶ demo/YEHS_demo/data/tour/<덱>.json + index.json   (커밋)
answers.mjs ─ 「정답 보기」 · 「대충 답해 보기」 글을 qa_live.js 원본 함수로
```

## 실행

```bash
PY=/home/yehschuck/project/chuckchuck/.venv/bin/python      # torch · Pillow 가 있는 venv (작업 폴더엔 .venv 가 없다)

# 1) 녹화 — 브리지를 직접 띄우고 끈다. 포트는 8983~8985 만 (8799 공개 · 8800 팀 개발은 거부, 물린 포트도 거부)
$PY labs/tour_capture/capture.py --decks 배달앱별점인플레이션A 급속충전배터리열화A 미세플라스틱물벼룩번식A --port 8983 --budget 80
# 2) 투어 파일
$PY labs/tour_capture/build.py
#    다른 worktree 에서 녹화했으면 그 녹화본을 읽기만 한다:  $PY labs/tour_capture/build.py --rec-dir <그 worktree>/labs/tour_capture/out/recordings
# 3) 검사
$PY -m pytest tests/test_tour_capture.py tests/test_booth_mobile_contract.py -q
$PY labs/tour_capture/build.py --check      # 녹화본으로 다시 만들면 커밋된 파일과 같은가 (0 = 같다)
```

- 덱 원본(PPTX · 녹음)은 git 에 없다. 작업 폴더 `ppt/` 에 없으면 **주 작업 폴더의 `ppt/`** 를 읽기만 한다(`git rev-parse --git-common-dir`).
- `.env` 는 worktree 에 `ln -s ../chuckchuck/.env .env` (다른 wt-* 와 같은 방식, git 무시).
- 브리지는 `labs/qa_verify/bridge_wrap.py` 로 띄운다 — LLM 논리 호출을 `out/runs/<시각>/llm_calls.jsonl` 에 세고 `--budget` 을 넘으면 부르기 전에 끊는다.
  `MOCK_EXTERNAL_APIS=false` · `DEMO_WARM_DECK_GROUPS=""`(시작 때 덱 미리 파싱 끔) · 세션 보관소는 `out/bridge_data`. 끌 때는 띄운 Popen 하나만(pkill 없음).
- `HABIT_PROVIDER` 는 기본 `heuristic` — 이 VM 엔 REP LoRA 어댑터가 없다(.env 의 경로가 자리표시). 말버릇은 휴리스틱 결과다.

## 한 흐름 (화면 코드가 보내는 그대로 — `chuckchuck_bridge.js`)

파싱(PPTX 업로드) → 상황 추정(F-23, 호출 0) → 녹음 받아쓰기(`marks_source:"even"` → 서버가 발화로 장 구간을 되짚음) → 개념 → 그래프 → 정합 → 흐름
→ 속도 · 말버릇 · 채점 · 리포트 → 세션 아티팩트 등록 → 질문(5분 코칭, 리허설 화상판과 같은 트랙) → 질문마다 「잘 답한 답」 · 「엉성한 답」 판정(되묻기 전 첫 판정).
함정 · 골자를 숨긴 질문의 정답 글은 화면처럼 서버 reveal 로 받는다.

## 비용 (2026-10-11 실측, 부스 A 덱 3개)

| | 배달앱 C-1 | 급속충전 A-1 | 미세플라스틱 B-1 | 합 |
|---|---|---|---|---|
| 브리지 HTTP | 19 | 19 | 20 | 58 |
| Upstage 파싱 · A.X 받아쓰기 | 1 · 1 | 1 · 1 | 1 · 1 | 3 · 3 |
| LLM 논리 호출 (solar) | 25 | 25 | 25 | **75** |
| 걸린 시간 | 63초 | 80초 | 75초 | |

**다시 돌리면 0** — 응답 캐시(`out/cache/<sha256>.json`)가 요청 본문(세션 id 를 빼고, 녹음 · 자료는 바이트 sha256)의 내용 해시로 받는다.
코드가 바뀌어 어느 단계 응답이 달라지면 그 단계부터만 다시 부른다. 캐시를 끄려면 `--fresh`(브리지 단계 캐시는 남는다).
브리지 없이 캐시로만 녹화본을 다시 쓰려면 `--offline`.

## 옮기는 규칙 · 손으로 뺀 것

규칙은 `build.py` 머리말과 [`tour-schema.md`](../../docs/booth-mobile/tour-schema.md) §녹화본 만들기. 2026-10-11 녹화에서 뺀 질문(각 투어의 `source.note` 에도 적힌다):

- 배달앱 q12 — 「엉성한 답」(숫자를 흐린 답)이 good 으로 판정됐다. 반응이 답에 없는 「11% · 34%」 를 맞았다고 했다(판정기 거짓 양성).
- 급속충전 q01 — 「잘 답한 답」(서버 골자 = 자료 줄 나열)이 partial.
- 급속충전 q03 — **골자가 틀렸다**: 질문은 「4분의 1을 깎았다」(25 °C · 76%)인데 골자는 45 °C · 64% 줄. 판정도 good 이라 그대로 두면 틀린 답을 정답으로 보인다(`EXCLUDE`).

장 그림은 이미 있는 `assets/deck-slides/<덱>/<n>.webp`(960×540, 장당 17~30KB)를 그대로 가리킨다 — 폰 2배 화면(375×2=750)에 충분하고 가벼워서 828px 사본을 따로 만들지 않았다.
