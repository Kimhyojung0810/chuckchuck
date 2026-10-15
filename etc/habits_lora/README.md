# 말버릇 태거 LoRA (F-18) — 연결·재현 안내

KT **Mi:dm 2.0 Base Instruct** 에 얹은 LoRA 두 갈래로 발표 전사문의 말버릇을 찾는다.

| 태그 | 어댑터 | 디코딩 | 옛 기록 (AI Hub held-out 62건) |
|---|---|---|---|
| REP 반복 | 통합 태거 `tagger_seed42` (REP/FIL/WR 프롬프트) | greedy, repetition_penalty **1.0** | F1 0.686 ± 0.027 (3시드) |
| FIL 간투어 | 전용 태거 `fil_seed{42,43,44}` 3개 | greedy, repetition_penalty **1.2**, **min 방식**(세 시드 모두 찾은 것만) | P 0.9927 · R 0.7253 · F1 0.838 |
| PAUSE 긴 쉼 | — | STT 타임스탬프 5초 이상 (규칙) | — |

서비스 코드: `main/pipeline/_lora_tagger.py`(설정·파싱·위치 찾기·투표) · `main/pipeline/_lora_runtime.py`(GPU).
베이스 한 벌(22GB)에 어댑터 4개를 PEFT 다중 어댑터로 얹고, **한 generate 호출 안에서 행마다 다른 어댑터와
다른 repetition_penalty** 를 쓴다. 긴 전사문은 1,600자 안팎으로 잘라(학습 전사문 길이) 같이 배치한다.
결과의 `HabitDoc.detectors` 에 태그마다 무엇이 찾았는지 남는다 (`lora` · `lora-ensemble×3` · `rule`).

## 1. 팀이 건네줄 것 — 둘 중 하나

### (가) 학습된 어댑터 (가장 빠름, 재학습 없음)

팀 GPU 서버의 `/home/ubuntu/workspace/20_AIHub_data/runs/` 에서 **`adapter_config.json` 이 들어 있는 폴더**를 통째로:

| 원본 (팀 서버) | 이 머신에 둘 곳 |
|---|---|
| `runs/tagger_seed42/final/` | `/data/models/_runs/habits-lora/rep_seed42/final/` |
| `runs/fil_seed42/…` (adapter_config.json 있는 폴더) | `/data/models/_runs/habits-lora/fil_seed42/final/` |
| `runs/fil_seed43/…` | `/data/models/_runs/habits-lora/fil_seed43/final/` |
| `runs/fil_seed44/…` | `/data/models/_runs/habits-lora/fil_seed44/final/` |

**같이 받아야 하는 것 — FIL 학습 프롬프트.** FIL 어댑터는 `src/build_task_dataset.py` 가 만든
`data/tagging_FIL/` 로 학습했는데, 그 프롬프트(시스템·사용자 문장)가 이 저장소에 없다. 둘 중 하나로 맞춘다.

- 통합 프롬프트(REP/FIL/WR 세 줄 설명)를 그대로 썼으면 → `CHUCKCHUCK_LORA_FIL_PROMPT=unified`
- FIL 전용 문장을 썼으면 → 각 `fil_seed*/final/` 에 `chuckchuck_task.json` 을 둔다:
  ```json
  {"system_prompt": "…build_task_dataset.py 의 시스템 문장…",
   "user_template": "…{stt_text}…",
   "repetition_penalty": 1.2, "max_new_tokens": 512}
  ```
- 확인용: `data/tagging_FIL/test.jsonl`(또는 그 원본)과 `ensemble_eval_rp1.2.json` 을 같이 받으면
  아래 §3 평가로 P/R/F1 이 옛 기록과 맞는지 바로 본다.

### (나) AI Hub 원본 라벨 (재학습)

AI Hub 「공적말하기 실습 및 평가 데이터」 **언어적 라벨 Training(TL) 640건** — zip 이든 풀어 둔 JSON 이든.
`/data/models/_runs/habits-lora/aihub/` 에 넣는다. 원래와 같은 분할을 쓰려면 팀의 분할 목록
(`{"train":[id…],"val":[…],"test":[…]}`, id = 라벨 파일 이름 줄기)도 받아 `split.json` 으로 둔다
(없으면 원고 SHA1 묶음으로 seed 42 · 80/10/10 — 원래 513/65/62 와 다를 수 있다).
학습률·에폭은 옛 문서에 없어 기본값(2e-4 · 3에폭 · 실효 배치 8)을 쓴다 — `README_FINETUNING.md` 값을 받으면 인자로 맞춘다.

## 2. 재학습 (한 줄씩, GPU 잠금 안에서)

같은 A100 을 다른 학습이 쓸 수 있다. 시작 전에 `nvidia-smi` 로 남은 메모리(학습 1개 ≈ 30~40GB)를 보고, 잠금을 건다.

```bash
cd <저장소>
export PATH=/home/yehschuck/project/chuckchuck/.venv/bin:$PATH
R=/data/models/_runs/habits-lora
L=~/.cache/chuckchuck-gpu.lock

python etc/habits_lora/aihub.py --src $R/aihub --out $R/data [--split-file $R/aihub/split.json]
for s in 42 43 44; do flock $L python etc/habits_lora/train.py --task FIL --seed $s; done   # → $R/fil_seed{s}/final
flock $L python etc/habits_lora/train.py --task unified --seed 42                          # → $R/rep_seed42/final
```

`train.py` 는 산출 폴더에 `chuckchuck_task.json`(학습 프롬프트 + 서빙 rp)을 같이 쓴다 — 서비스가 그대로 읽는다.
HF 캐시는 `$R/hf_cache` (루트 디스크가 96% 라서).

## 3. 평가 (서비스와 같은 경로)

```bash
flock $L python etc/habits_lora/evaluate.py --kind FIL --data $R/data/FIL/test.jsonl \
    --adapters $R/fil_seed42/final $R/fil_seed43/final $R/fil_seed44/final --out $R/eval/fil_ens.json
flock $L python etc/habits_lora/evaluate.py --kind REP --data $R/data/unified/test.jsonl \
    --adapters $R/rep_seed42/final --out $R/eval/rep42.json
flock $L python etc/habits_lora/evaluate.py --transcript etc/fixtures/focus_transcript.json   # 지연·VRAM
```

`--max-batch 1` 이면 한 줄씩(학습 때 평가와 같은 계산), 기본 8 은 배치 — bf16 이라 글자가 드물게 달라질 수 있다.

## 4. 서비스에 켜기

어댑터를 §1 위치에 두면 경로 설정 없이 찾는다. systemd drop-in 에서는 `HABIT_PROVIDER` 만 바꾼다:

```ini
# /etc/systemd/system/chuckchuck-bridge.service.d/habits-lora.conf
[Service]
Environment=HABIT_PROVIDER=lora
Environment=HF_HOME=/data/models/_runs/habits-lora/hf_cache
# Environment=CHUCKCHUCK_LORA_BACKUP=gpu      # VRAM 이 넉넉하면 (요청당 ~3초 빠름)
# FIL 프롬프트가 통합 프롬프트였으면:
# Environment=CHUCKCHUCK_LORA_FIL_PROMPT=unified
```

(기존 unit 의 `Environment=HABIT_PROVIDER=heuristic` 줄은 drop-in 이 덮는다.) 브리지는 뜨자마자 뒤에서 LoRA 를 올리고
(`[lora] 올림 …s` 로그), 그 전 요청은 `provider=heuristic(lora-loading)` 로 규칙이 맡는다.
확인: `etc/scripts/chk doctor` (REP·FIL 어댑터 줄) · `etc/scripts/chk warmup` (provider=lora) ·
응답의 `detectors` 가 `{"REP":"lora","FIL":"lora-ensemble×3","PAUSE":"rule"}`.

**GPU·속도 (2026-10-16 이 VM 실측, 학습 안 된 가짜 어댑터 4개로 배선만 확인)** — 생성 방식 `CHUCKCHUCK_LORA_MODE`:

| 방식 | 토큰당 | 비고 |
|---|---|---|
| `swap` (기본) | 52~67ms | 어댑터마다 베이스에 합쳐(merge) 생성 → 백업으로 되돌림. 디스크 원본과 비트 단위로 같게 돌아옴 확인 |
| `unmerged` | 117~136ms | set_adapter 로 하나씩 |
| `mixed` | 522ms | 한 배치에 어댑터 섞기 — 출력은 다른 방식과 같았지만 이 VM(CPU 가 느려 커널 띄우기가 지배)에선 가장 느림 |

- bf16 에서 unmerge(빼기)로 되돌리면 원소 1.5~14% 가 어긋난다(실측) — 그래서 빼지 않고 백업을 덮어쓴다.
  `CHUCKCHUCK_LORA_BACKUP=cpu`(기본: VRAM 22.4GB 그대로, 고정 RAM 19.5GB, 되돌리기 0.84초) | `gpu`(VRAM 42GB, 요청당 ~3초 빠름).
- 올리기 30~55초(페이지 캐시 따라). 가짜 어댑터 96토큰 상한으로 focus 전사문(194단어) 한 번 = swap 20~24초, 8816 브리지 왕복 23.6초.
  학습된 태거는 출력이 훨씬 짧다(정답 줄 목록 평균 REP 152자 · FIL 76자) — 추정 REP ~4초 + FIL 3시드 ~6초 + 되돌리기 ~3초.
  예전 REP 하나(합친 모델)는 ~4초였으니 **FIL 앙상블을 켜면 분석이 ~10초 늘어난다.** 줄이려면 `CHUCKCHUCK_LORA_BACKUP=gpu`,
  또는 FIL 시드를 하나만(`CHUCKCHUCK_LORA_FIL_PATHS=…/fil_seed42/final` — 단일 시드 수치는 RESULTS_2ND 로 확인할 것).
**STT 주의** — 서비스 STT(A.X) 전사문 4건(10/5 세션 3 · 리허설 픽스처 1)에 「어」「음」이 한 번도 없다.
STT 가 간투어를 지우면 FIL 태거도 셀 것이 없다 — 일부러 「어」「음」을 섞은 녹음으로 한 번 확인할 것.
