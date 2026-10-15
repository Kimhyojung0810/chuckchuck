"""
Mi:dm 2.0 Base Instruct 에 습관 태거 LoRA 를 학습한다 (REP 통합 태거 · FIL 전용 태거).

호출 (GPU 잠금 안에서 — 같은 A100 을 다른 학습이 쓸 수 있다):
  flock ~/.cache/chuckchuck-gpu.lock python etc/habits_lora/train.py --task FIL --seed 42
  flock ~/.cache/chuckchuck-gpu.lock python etc/habits_lora/train.py --task unified --seed 42   # 서비스 REP 태거
산출: <runs>/{fil,rep}_seed<seed>/final/ (adapter_config.json · adapter_model.safetensors · chuckchuck_task.json)
      <runs>/{fil,rep}_seed<seed>/train_log.json

하이퍼파라미터 — 옛 docs/DATA_PIPELINE.md §3 에 적힌 것: LoRA r=16 α=32 dropout=0.05, 대상 q/k/v/o/gate/up/down,
시드 42/43/44. 학습률·에폭·배치는 그 문서에 없다 (원본 20_AIHub_data/README_FINETUNING.md 에 있다) — 아래 기본값은
흔한 값(2e-4 · 3에폭 · 실효 배치 8) 이고, 원본 값을 받으면 인자로 맞춘다.
chuckchuck_task.json 에 학습 프롬프트와 서빙 디코딩(REP rp 1.0 · FIL rp 1.2)을 같이 적어, 서비스가 그대로 읽는다.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = Path(os.environ.get("HABITS_LORA_RUNS", "/data/models/_runs/habits-lora"))
sys.path.insert(0, str(ROOT / "main"))

from pipeline._lora_tagger import LOCAL_BASE, MODEL_ID, SYSTEM_PROMPT, TASK_PROMPTS, USER_TEMPLATE  # noqa: E402

TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
SERVE_RP = {"unified": 1.0, "REP": 1.0, "FIL": 1.2}
OUT_PREFIX = {"unified": "rep", "REP": "reponly", "FIL": "fil"}


def prompts_for(task: str) -> tuple[str, str]:
    return (SYSTEM_PROMPT, USER_TEMPLATE) if task == "unified" else TASK_PROMPTS[task]


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def encode(tok, system: str, user_t: str, row: dict, max_len: int):
    """프롬프트는 -100 으로 가리고 정답 줄 목록 + eos 만 학습한다."""
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user_t.replace("{stt_text}", row["stt"])}]
    prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    t_ids = tok(row["target"], add_special_tokens=False)["input_ids"] + [tok.eos_token_id]
    if len(p_ids) + len(t_ids) > max_len:
        return None
    return p_ids + t_ids, [-100] * len(p_ids) + t_ids


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", choices=("unified", "REP", "FIL"), required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--data", type=Path, help="기본 <runs>/data/<task>")
    ap.add_argument("--out", type=Path, help="기본 <runs>/{rep|fil}_seed<seed>")
    ap.add_argument("--base", default=str(LOCAL_BASE) if (LOCAL_BASE / "config.json").is_file() else MODEL_ID)
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--max-len", type=int, default=4096)
    ap.add_argument("--warmup", type=float, default=0.03)
    ap.add_argument("--max-steps", type=int, default=0, help="0=끝까지. 연기 시험용")
    ns = ap.parse_args(argv)
    os.environ.setdefault("HF_HOME", str(RUNS / "hf_cache"))   # 루트 디스크가 96% — 캐시는 /data 로

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    data = ns.data or RUNS / "data" / ns.task
    out = ns.out or RUNS / f"{OUT_PREFIX[ns.task]}_seed{ns.seed}"
    random.seed(ns.seed)
    torch.manual_seed(ns.seed)
    system, user_t = prompts_for(ns.task)

    tok = AutoTokenizer.from_pretrained(ns.base)
    train = [e for e in (encode(tok, system, user_t, r, ns.max_len) for r in read_jsonl(data / "train.jsonl")) if e]
    val_rows = read_jsonl(data / "val.jsonl") if (data / "val.jsonl").is_file() else []
    val = [e for e in (encode(tok, system, user_t, r, ns.max_len) for r in val_rows) if e]
    print(f"train {len(train)} · val {len(val)} · base {ns.base}", flush=True)

    model = AutoModelForCausalLM.from_pretrained(ns.base, dtype=torch.bfloat16, device_map={"": 0})
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, target_modules=TARGETS,
                                             task_type="CAUSAL_LM"))
    model.print_trainable_parameters()
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=ns.lr, weight_decay=0.0)
    total = ns.max_steps or math.ceil(len(train) * ns.epochs / ns.grad_accum)
    warm = max(1, int(total * ns.warmup))
    sched = torch.optim.lr_scheduler.LambdaLR(   # 선형 예열 → 선형 감소
        opt, lambda s: (s + 1) / warm if s < warm else max(0.0, (total - s) / max(1, total - warm)))

    def loss_of(ex):
        ids, labels = ex
        x = torch.tensor([ids], device=model.device)
        y = torch.tensor([labels], device=model.device)
        return model(input_ids=x, labels=y).loss

    log, step, t0 = [], 0, time.time()
    model.train()
    order: list[int] = []
    micro = 0
    while step < total:
        if not order:
            order = list(range(len(train)))
            random.shuffle(order)
        loss = loss_of(train[order.pop()]) / ns.grad_accum
        loss.backward()
        micro += 1
        if micro % ns.grad_accum:
            continue
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        opt.step()
        sched.step()
        opt.zero_grad(set_to_none=True)
        step += 1
        if step % 10 == 0 or step == total:
            rec = {"step": step, "loss": round(loss.item() * ns.grad_accum, 4), "lr": sched.get_last_lr()[0],
                   "min": round((time.time() - t0) / 60, 1)}
            print(json.dumps(rec), flush=True)
            log.append(rec)

    model.eval()
    if val:
        with torch.no_grad():
            vl = sum(loss_of(e).item() for e in val) / len(val)
        log.append({"val_loss": round(vl, 4)})
        print(f"val_loss {vl:.4f}", flush=True)

    final = out / "final"
    model.save_pretrained(str(final))
    task = {"task": ns.task, "system_prompt": system, "user_template": user_t,
            "repetition_penalty": SERVE_RP[ns.task], "max_new_tokens": 512,
            "base": ns.base, "seed": ns.seed, "lora": {"r": 16, "alpha": 32, "dropout": 0.05, "targets": TARGETS}}
    (final / "chuckchuck_task.json").write_text(json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "train_log.json").write_text(json.dumps({"args": {k: str(v) for k, v in vars(ns).items()}, "log": log},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved {final}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
