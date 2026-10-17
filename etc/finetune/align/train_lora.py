"""
Mi:dm 2.0 Base Instruct(11.5B) 에 F-11 판정 LoRA 를 붙여 학습한다 — bf16, 손실은 정답 JSON 토큰에만.

  flock /home/yehschuck/.cache/chuckchuck-gpu.lock python train_lora.py --run r1 --epochs 1

입력: DATA/sets/train.jsonl · dev.jsonl (assemble.py 가 만든다; 줄마다 item·verdict·sid·note)
산출: RUN/runs/<run>/{final,ckpt-*}/ (어댑터) · log.jsonl · dev_eval.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from collections import Counter

from common import DATA, RUN, read_jsonl

from pipeline._align_lora import ASSISTANT_PREFIX, BASE_MODEL, EOT, render_prompt, render_target
from pipeline.contracts import ALIGN_VERDICTS


def encode(tok, row: dict, max_len: int):
    p = tok(render_prompt(row["item"]), add_special_tokens=False)["input_ids"]
    t = tok(render_target(row["verdict"], row.get("sid"), row.get("note", "")) + EOT, add_special_tokens=False)["input_ids"]
    if len(p) + len(t) > max_len:
        return None
    return p + t, [-100] * len(p) + t


def verdict_ids(tok) -> list[int]:
    pre = tok(ASSISTANT_PREFIX, add_special_tokens=False)["input_ids"]
    out = []
    for v in ALIGN_VERDICTS:
        ids = tok(ASSISTANT_PREFIX + v, add_special_tokens=False)["input_ids"]
        assert ids[: len(pre)] == pre, "접두 토큰이 판정 낱말과 붙는다 — 확률을 첫 토큰에서 읽을 수 없다"
        out.append(ids[len(pre)])
    assert len(set(out)) == len(out)
    return out


def macro_f1(gold: list[str], pred: list[str]) -> dict:
    res = {}
    for v in ALIGN_VERDICTS:
        tp = sum(1 for g, p in zip(gold, pred) if g == v and p == v)
        fp = sum(1 for g, p in zip(gold, pred) if g != v and p == v)
        fn = sum(1 for g, p in zip(gold, pred) if g == v and p != v)
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        res[v] = {"p": round(pr, 3), "r": round(rc, 3), "f1": round(2 * pr * rc / (pr + rc), 3) if pr + rc else 0.0,
                  "n": tp + fn}
    present = [v for v in ALIGN_VERDICTS if res[v]["n"]]
    res["macro_f1"] = round(sum(res[v]["f1"] for v in present) / max(1, len(present)), 4)
    res["acc"] = round(sum(1 for g, p in zip(gold, pred) if g == p) / max(1, len(gold)), 4)
    return res


def score_verdicts(model, tok, rows: list[dict], vids: list[int], bs: int = 4) -> list[dict]:
    """정답 생성 없이 첫 판정 토큰 확률만 — 빠른 dev 지표."""
    import torch

    pre = tok(ASSISTANT_PREFIX, add_special_tokens=False)["input_ids"]
    out = []
    model.eval()
    for i in range(0, len(rows), bs):
        seqs = [tok(render_prompt(r["item"]), add_special_tokens=False)["input_ids"] + pre for r in rows[i:i + bs]]
        n = max(len(s) for s in seqs)
        ids = torch.full((len(seqs), n), tok.pad_token_id, dtype=torch.long)
        att = torch.zeros((len(seqs), n), dtype=torch.long)
        for b, s in enumerate(seqs):
            ids[b, n - len(s):] = torch.tensor(s)
            att[b, n - len(s):] = 1
        with torch.no_grad():
            logits = model(input_ids=ids.cuda(), attention_mask=att.cuda()).logits[:, -1, :].float()
        p = torch.softmax(logits[:, vids], dim=-1).cpu()
        for b in range(len(seqs)):
            probs = {v: float(p[b, k]) for k, v in enumerate(ALIGN_VERDICTS)}
            out.append({"pred": max(probs, key=probs.get), "probs": probs})
    model.train()
    return out


def balance(rows: list[dict], caps: dict, rng: random.Random) -> list[dict]:
    """클래스별 상한·하한(복제) — aligned 가 판을 먹지 않게, contradiction·justified_skip 은 적으면 한 번까지 복제."""
    by = {v: [r for r in rows if r["verdict"] == v] for v in ALIGN_VERDICTS}
    out = []
    for v, rs in by.items():
        rng.shuffle(rs)
        cap = caps.get(v)
        if cap and len(rs) > cap:
            rs = rs[:cap]
        floor = caps.get(f"{v}_min")
        if floor and len(rs) < floor:
            rs = rs + rs[: min(len(rs), floor - len(rs))]
        out += rs
    rng.shuffle(out)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--base", default=BASE_MODEL)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--r", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--accum", type=int, default=16)
    ap.add_argument("--max_len", type=int, default=3072)
    ap.add_argument("--cap_aligned", type=int, default=0)
    ap.add_argument("--contra_min", type=int, default=0)
    ap.add_argument("--save_every", type=int, default=150)
    ap.add_argument("--seed", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sets_dir", default=str(DATA / "sets"))
    ap.add_argument("--dev_limit", type=int, default=0)
    ap.add_argument("--aug", type=int, default=0, help="train_aug.jsonl 에서 섞을 최대 줄 수(0 이면 안 섞음)")
    args = ap.parse_args()

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    out_dir = RUN / "runs" / args.run
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "args.json").write_text(json.dumps(vars(args), indent=1))
    rng = random.Random(args.seed)
    torch.manual_seed(args.seed)

    tok = AutoTokenizer.from_pretrained(args.base)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    vids = verdict_ids(tok)

    from pathlib import Path
    train = read_jsonl(Path(args.sets_dir) / "train.jsonl")
    dev = read_jsonl(Path(args.sets_dir) / "dev.jsonl")
    if args.dev_limit:
        dev = dev[: args.dev_limit]
    if args.aug:
        aug = read_jsonl(Path(args.sets_dir) / "train_aug.jsonl")
        rng.shuffle(aug)
        train = train + aug[: args.aug]
    caps = {}
    if args.cap_aligned:
        caps["aligned"] = args.cap_aligned
    if args.contra_min:
        caps["contradiction_min"] = args.contra_min
    train = balance(train, caps, rng)
    if args.limit:
        train = train[: args.limit]
    enc = [(r, encode(tok, r, args.max_len)) for r in train]
    dropped = sum(1 for _, e in enc if e is None)
    data = [e for _, e in enc if e is not None]
    lens = sorted(len(x[0]) for x in data)
    print(f"[train] n={len(data)} dropped_long={dropped} dist={Counter(r['verdict'] for r, e in enc if e)} "
          f"len p50={lens[len(lens)//2]} p95={lens[int(len(lens)*.95)]} max={lens[-1]}", flush=True)

    model = AutoModelForCausalLM.from_pretrained(args.base, dtype=torch.bfloat16, device_map={"": 0},
                                                 attn_implementation="sdpa")
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    cfg = LoraConfig(r=args.r, lora_alpha=args.alpha, lora_dropout=args.dropout, bias="none", task_type="CAUSAL_LM",
                     target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, cfg)
    model.print_trainable_parameters()

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.0, betas=(0.9, 0.999))
    steps_total = math.ceil(len(data) * args.epochs / args.accum)
    warm = max(1, int(0.05 * steps_total))

    def lr_at(step: int) -> float:
        if step < warm:
            return args.lr * (step + 1) / warm
        prog = (step - warm) / max(1, steps_total - warm)
        return args.lr * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * prog)))

    order = []
    while len(order) < steps_total * args.accum:
        idx = list(range(len(data)))
        rng.shuffle(idx)
        order += idx
    order = order[: steps_total * args.accum]

    log = (out_dir / "log.jsonl").open("a")
    model.train()
    t0 = time.time()
    run_loss, run_tok = 0.0, 0
    for step in range(steps_total):
        for g in opt.param_groups:
            g["lr"] = lr_at(step)
        for k in range(args.accum):
            ids, lab = data[order[step * args.accum + k]]
            x = torch.tensor([ids], device="cuda")
            y = torch.tensor([lab], device="cuda")
            out = model(input_ids=x, labels=y)
            (out.loss / args.accum).backward()
            ntok = sum(1 for t in lab if t != -100)
            run_loss += float(out.loss.detach()) * ntok
            run_tok += ntok
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        opt.step()
        opt.zero_grad(set_to_none=True)
        if (step + 1) % 5 == 0 or step == steps_total - 1:
            el = time.time() - t0
            rec = {"step": step + 1, "of": steps_total, "loss": round(run_loss / max(1, run_tok), 4),
                   "lr": lr_at(step), "elapsed_s": round(el), "eta_s": round(el / (step + 1) * (steps_total - step - 1)),
                   "mem_gb": round(torch.cuda.max_memory_allocated() / 2**30, 1)}
            print("[train]", json.dumps(rec), flush=True)
            log.write(json.dumps(rec) + "\n")
            log.flush()
            run_loss, run_tok = 0.0, 0
        if args.save_every and (step + 1) % args.save_every == 0 and step + 1 < steps_total:
            model.save_pretrained(str(out_dir / f"ckpt-{step + 1}"))
    model.save_pretrained(str(out_dir / "final"))
    train_s = time.time() - t0

    dev_rows = dev
    res = score_verdicts(model, tok, dev_rows, vids)
    rep = {"overall": macro_f1([r["verdict"] for r in dev_rows], [x["pred"] for x in res])}
    for lang in ("ko", "en"):
        sub = [(r, x) for r, x in zip(dev_rows, res) if r["lang"] == lang]
        if sub:
            rep[lang] = macro_f1([r["verdict"] for r, _ in sub], [x["pred"] for _, x in sub])
    rep["train_s"] = round(train_s)
    rep["peak_mem_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 1)
    (out_dir / "dev_eval.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    print("[dev]", json.dumps(rep, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    main()
