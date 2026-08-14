# 발표새(병아리) 이미지 내보내기

제품 안의 병아리는 **이미지 파일이 아니라 코드 안의 인라인 SVG** 다.
이 폴더는 그걸 배경 투명 PNG · 단독 SVG 로 구워 둔 것이다. 원본이 바뀌면 다시 구워야 한다.

- `png/` — 1024×1024 RGBA, 배경 투명 (24장)
- `svg/` — 벡터 원본. 색 변수를 안에 심어서 `chatter.css` 없이 단독으로 열린다 (24개)
- `index.html` — 24장 한눈에 보는 대조표 (브라우저로 열면 된다)
- `../chicks.zip` — 위 전부를 묶은 것

## 무엇이 들어 있나

### 객석 발표새 — `chick_{모델}_{이름}_{표정}` (4 모델 × 5 표정 = 20)

몸은 넷이 같다. **넷을 가르는 건 색이 아니라 소품**이고, 소품은 그 모델이
파이프라인에서 실제로 한 일이다 (`docs/design_improvement/01_character.md`).

| 모델 | 이름 | 소품 | 무슨 일을 했나 |
|---|---|---|---|
| `ax` | 엑씨 | 헤드폰 | 발표를 귀로 들었다 (F-05 STT) |
| `solar` | 쏠라 | 겹친 슬라이드 | 자료를 통독했다 (F-01/06/07) |
| `midm` | 믿음 | 형광펜 | 자료와 발화를 대조했다 (F-11) |
| `exaone` | 엑사원 | 별 로제트 | 잘 맞은 대목을 인정했다 (aligned) |

표정 5종: `neutral` · `happy`(∪ 눈 + 하트) · `curious`(물음표) ·
`grumpy`(∧ 눈, 믿음은 형광펜 밑줄까지) · `excited`(눈 커짐).

### 작업대 새 — `workbench_bird_{소품}` (4)

F-11 분석 연출(`f11_reveal.html`)이 iframe 안에서 따로 그리는 단순한 새다.
객석 발표새와 **선이 다르다** — 같은 그림이 아니니 섞어 쓰지 않는다.
소품은 `none` · `phones` · `slides` · `pen`.

## 다시 굽는 법

원본이 바뀌면(아래 세 파일 중 하나라도) 이 폴더는 낡은 것이다.

- `demo/YEHS_demo/js/chatter.js` — `chickSvg(speaker)` · 소품
- `demo/YEHS_demo/css/chatter.css` — `:root` 의 `--chick-*` 색, `[data-mood]` 표정
- `demo/YEHS_demo/f11_reveal.html` — `wbBirdSvg(prop)`

```bash
python3 exports/export_chicks.py    # playwright + 캐시된 chromium 을 쓴다
```

애니메이션(흔들림·호흡·깜빡임)은 전부 끄고 정지 프레임을 굽는다.
표정 중 `excited` 와 `grumpy` 의 형광펜 밑줄은 원래 애니메이션으로만 존재해서,
스크립트의 `STATE_CSS` 가 최종 프레임으로 굳혀 둔 것이다.
