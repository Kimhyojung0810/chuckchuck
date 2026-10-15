"""
[F-18 내부] Mi:dm 베이스 한 벌 + LoRA 어댑터 여럿을 GPU 에 올리고 배치로 생성한다.

호출: _lora_tagger.tag_habits() → get_runner(cfg).generate_batch(requests)
     etc/habits_lora/evaluate.py 도 같은 러너를 쓴다 (평가 = 서비스 경로).

베이스(22GB)는 한 벌만 올리고 어댑터(REP 1 + FIL 3)는 PEFT 다중 어댑터로 얹는다. 생성 방식은 셋
(CHUCKCHUCK_LORA_MODE), 2026-10-16 이 VM(A100, CPU 가 느려 커널 띄우는 비용이 지배)에서 잰 토큰당 시간:

  swap (기본)  어댑터마다 베이스 가중치에 더해(merge) 두고 그 어댑터의 행을 한 배치로 생성 → 백업에서 원래 값으로
               되돌린다.  합친 모델 속도 52~67ms/토큰. merge·되돌리기 각 0.05초 안팎.
               bf16 에서 unmerge(빼기)로 되돌리면 값이 어긋난다 — 한 번에 원소 1.5~14% (실측). 그래서 빼지 않고
               백업을 덮어쓴다 (CHUCKCHUCK_LORA_BACKUP): cpu(기본, 고정 메모리 19.5GB · 되돌리기 0.84초) |
               gpu(VRAM 19.5GB 더 · 수십 ms) | auto(GPU 여유가 백업+8GB 넘으면 gpu).
  unmerged     set_adapter 로 하나씩 (LoRA 를 매 층 따로 계산) — 117~136ms/토큰. 백업이 필요 없다.
  mixed        한 배치에 행마다 다른 어댑터(adapter_names) — 522ms/토큰. 이 머신에선 가장 느리다.

· 행마다 repetition_penalty 가 다를 수 있다(REP 1.0 · FIL 1.2) — RowRepetitionPenalty. 왼쪽 패딩 토큰은
  페널티 대상에서 뺀다 (한 줄씩 돌린 학습 평가와 같은 계산). mixed==어댑터별==한 줄씩 출력이 같음을 실측했다.
· 생성은 잠금 하나로 줄 세운다. 브리지는 요청마다 스레드라 동시에 들어오면 GPU 가 두 배로 먹는다.
· 미리 올리기(preload) 를 켜면 올리는 동안 들어온 요청은 LoraNotReady → f18 이 규칙으로 대신한다.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import contextmanager

from ._lora_tagger import GenRequest, LoraNotReady, TaggerConfig

_lock = threading.Lock()
_runner = None            # MidmLoraRunner
_runner_key: tuple | None = None
_loading = threading.Event()
_load_error: BaseException | None = None
_failed_key: tuple | None = None
_failed_at = 0.0


class RowRepetitionPenalty:
    """행마다 다른 repetition_penalty. pad_lens[r] 앞쪽(왼쪽 패딩)은 세지 않는다."""

    def __init__(self, penalties: list[float], pad_lens: list[int]):
        self.penalties = list(penalties)
        self.pad_lens = list(pad_lens)

    def __call__(self, input_ids, scores):
        import torch

        for r, p in enumerate(self.penalties):
            if p == 1.0:
                continue
            ids = input_ids[r, self.pad_lens[r]:]
            sc = torch.gather(scores[r], 0, ids)
            sc = torch.where(sc < 0, sc * p, sc / p)
            scores[r].scatter_(0, ids, sc)
        return scores


MODES = ("swap", "unmerged", "mixed")
BACKUP_MARGIN_GB = 8.0


class MidmLoraRunner:
    """베이스 한 벌 + 이름 붙은 어댑터들. generate_batch 는 요청 순서대로 출력 문자열을 돌려준다."""

    def __init__(self, cfg: TaggerConfig, mode: str | None = None):
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if not torch.cuda.is_available() and os.environ.get("CHUCKCHUCK_LORA_ALLOW_CPU") != "1":
            raise RuntimeError("CUDA 없음 — 11.5B 를 CPU 로 돌리지 않는다 (CHUCKCHUCK_LORA_ALLOW_CPU=1 로 강제)")
        t0 = time.time()
        self.cfg = cfg
        mode = (mode or os.environ.get("CHUCKCHUCK_LORA_MODE") or "swap").strip().lower()
        self.mode = mode if mode in MODES else "swap"
        on_gpu = torch.cuda.is_available()
        tok = AutoTokenizer.from_pretrained(cfg.base)
        if tok.pad_token_id is None:
            tok.pad_token = tok.eos_token
        tok.padding_side = "left"
        self.tokenizer = tok
        kw = {"device_map": {"": 0}} if on_gpu else {}
        dtype = torch.bfloat16 if on_gpu else torch.float32
        try:
            base = AutoModelForCausalLM.from_pretrained(cfg.base, dtype=dtype, **kw)
        except TypeError:
            base = AutoModelForCausalLM.from_pretrained(cfg.base, torch_dtype=dtype, **kw)
        ads = cfg.adapters
        model = PeftModel.from_pretrained(base, str(ads[0].path), adapter_name=ads[0].name)
        for ad in ads[1:]:
            model.load_adapter(str(ad.path), adapter_name=ad.name)
        model.eval()
        self.model = model
        self.mixed_ok = True
        self.backup_on = None
        if self.mode == "swap":
            self._make_backup(torch)
        self.load_sec = round(time.time() - t0, 1)
        self.gen_lock = threading.Lock()

    # ── swap: 합치기 · 되돌리기 ──
    def _lora_layers(self):
        return [m for m in self.model.modules() if hasattr(m, "lora_A") and hasattr(m, "base_layer")
                and hasattr(m, "get_delta_weight")]

    def _make_backup(self, torch) -> None:
        layers = self._lora_layers()
        need = sum(m.base_layer.weight.numel() * m.base_layer.weight.element_size() for m in layers)
        # 기본 cpu — GPU 를 예전 REP 서비스만큼(22.4GB)만 문다. 같은 GPU 에서 학습이 돌 수 있어서.
        # gpu 로 두면 19.5GB 를 더 물고 요청당 ~3초 빨라진다 (되돌리기 0.84초 → 수십 ms, 어댑터 4개).
        want = (os.environ.get("CHUCKCHUCK_LORA_BACKUP") or "cpu").lower()
        free = torch.cuda.mem_get_info()[0] if torch.cuda.is_available() else 0
        on_gpu = want == "gpu" or (want == "auto" and free > need + BACKUP_MARGIN_GB * 2**30)
        self._layers = layers
        if on_gpu:
            self._backup = [m.base_layer.weight.detach().clone() for m in layers]
        else:
            self._backup = [m.base_layer.weight.detach().to("cpu").pin_memory() for m in layers]
        self.backup_on = "gpu" if on_gpu else "cpu"
        self.backup_gb = round(need / 2**30, 1)

    def _merge(self, name: str) -> None:
        import torch

        with torch.no_grad():
            for m in self._layers:
                if name in m.lora_A:
                    w = m.base_layer.weight
                    w.add_(m.get_delta_weight(name).to(w.dtype))

    def _restore(self) -> None:
        import torch

        with torch.no_grad():
            for m, b in zip(self._layers, self._backup):
                m.base_layer.weight.copy_(b, non_blocking=True)
        if torch.cuda.is_available():
            torch.cuda.synchronize()

    @contextmanager
    def _active(self, name: str):
        """이 어댑터로 생성할 수 있게 해 두고, 끝나면 베이스를 원래대로."""
        if self.mode != "swap":
            self.model.set_adapter(name)
            yield
            return
        self._merge(name)
        try:
            with self.model.disable_adapter():   # 합친 가중치만 쓴다 — LoRA 를 한 번 더 더하지 않게
                yield
        finally:
            self._restore()

    def _prompt(self, req: GenRequest) -> str:
        msgs = [{"role": "system", "content": req.system_prompt}, {"role": "user", "content": req.user_text}]
        return self.tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)

    def _run(self, reqs: list[GenRequest], mixed: bool) -> list[str]:
        import torch
        from transformers import LogitsProcessorList

        tok = self.tokenizer
        enc = tok([self._prompt(r) for r in reqs], return_tensors="pt", padding=True, add_special_tokens=False)
        enc = {k: v.to(self.model.device) for k, v in enc.items()}
        pad_lens = (enc["attention_mask"] == 0).sum(dim=1).tolist()
        proc = RowRepetitionPenalty([r.repetition_penalty for r in reqs], pad_lens)
        kw = dict(
            max_new_tokens=max(r.max_new_tokens for r in reqs),
            do_sample=False,
            logits_processor=LogitsProcessorList([proc]),
            pad_token_id=tok.pad_token_id,
        )
        if mixed:
            kw["adapter_names"] = [r.adapter for r in reqs]
        with torch.no_grad():
            out = self.model.generate(**enc, **kw)
        n_in = enc["input_ids"].shape[1]
        return [tok.decode(row[n_in:], skip_special_tokens=True) for row in out]

    def generate_batch(self, reqs: list[GenRequest]) -> list[str]:
        """요청들을 생성해 요청 순서대로. mixed 는 길이 순 max_batch 묶음, 나머지는 어댑터별 max_batch 묶음."""
        out: list[str | None] = [None] * len(reqs)
        step = max(1, self.cfg.max_batch)
        with self.gen_lock:
            if self.mode == "mixed" and self.mixed_ok:
                order = sorted(range(len(reqs)), key=lambda i: len(reqs[i].user_text))
                try:
                    for s in range(0, len(order), step):
                        idx = order[s:s + step]
                        for i, text in zip(idx, self._run([reqs[i] for i in idx], mixed=True)):
                            out[i] = text
                    return [o or "" for o in out]
                except (TypeError, ValueError) as e:
                    # 이 PEFT 판이 섞인 어댑터 배치를 못 받으면 어댑터별로 (한 번 보고 끈다)
                    sys.stderr.write(f"[lora] mixed adapter batch 불가 → 어댑터별: {e}\n")
                    self.mixed_ok = False
                    self.mode = "unmerged"
            for name in dict.fromkeys(r.adapter for r in reqs):
                idx = sorted((i for i, r in enumerate(reqs) if r.adapter == name), key=lambda i: len(reqs[i].user_text))
                with self._active(name):
                    for s in range(0, len(idx), step):
                        part = idx[s:s + step]
                        for i, text in zip(part, self._run([reqs[i] for i in part], mixed=False)):
                            out[i] = text
        return [o or "" for o in out]


def _build(cfg: TaggerConfig) -> None:
    """_lock 을 쥔 채로 부른다."""
    global _runner, _runner_key, _load_error, _failed_key, _failed_at
    try:
        r = MidmLoraRunner(cfg)
        _runner, _runner_key = r, cfg.key()
        _load_error, _failed_key = None, None
        sys.stderr.write(f"[lora] 올림 {r.load_sec}s · base={cfg.base} · 어댑터={[a.name for a in cfg.adapters]}\n")
    except BaseException as e:  # noqa: BLE001 — 실패를 저장해 두고 한동안은 규칙으로 대신한다
        _load_error, _failed_key, _failed_at = e, cfg.key(), time.time()
        sys.stderr.write(f"[lora] 올리기 실패: {type(e).__name__}: {e}\n")
    finally:
        _loading.clear()


def _recently_failed(cfg: TaggerConfig) -> bool:
    """같은 설정으로 RETRY 초 안에 실패했으면 다시 올리지 않는다 (요청마다 22GB 를 다시 읽지 않게)."""
    try:
        retry = float(os.environ.get("CHUCKCHUCK_LORA_RETRY_SEC", "") or 600)
    except ValueError:
        retry = 600.0
    return _failed_key == cfg.key() and (time.time() - _failed_at) < retry


def _ready(cfg: TaggerConfig) -> bool:
    return _runner is not None and _runner_key == cfg.key()


def get_runner(cfg: TaggerConfig, *, wait: bool | None = None) -> MidmLoraRunner:
    """설정이 같으면 올려 둔 러너를 재사용. 올리는 중이면 LoraNotReady (wait=True 면 기다린다)."""
    if _ready(cfg):
        return _runner
    if _recently_failed(cfg):
        raise RuntimeError(f"LoRA 올리기가 실패했다: {_load_error}")
    if wait is None:
        wait = os.environ.get("CHUCKCHUCK_LORA_WAIT", "") == "1"
    if _loading.is_set() and not wait:
        raise LoraNotReady("LoRA 를 올리는 중")
    with _lock:
        if not _ready(cfg) and not _recently_failed(cfg):
            _loading.set()
            _build(cfg)
    if not _ready(cfg):
        raise RuntimeError(f"LoRA 를 못 올렸다: {_load_error}")
    return _runner


def preload(cfg: TaggerConfig) -> bool:
    """뒤에서 미리 올린다. 이미 올렸거나 올리는 중이면 False."""
    if _ready(cfg) or _loading.is_set():
        return False
    _loading.set()

    def _go():
        with _lock:
            if _ready(cfg):
                _loading.clear()
                return
            _build(cfg)

    threading.Thread(target=_go, name="lora-preload", daemon=True).start()
    return True


def state() -> dict:
    """진단용 — 올렸는지, 올리는 중인지, 실패했는지, GPU 를 얼마나 무는지."""
    out = {"ready": _runner is not None, "loading": _loading.is_set(),
           "error": f"{type(_load_error).__name__}: {_load_error}" if _load_error else None}
    if _runner is not None:
        out["load_sec"] = _runner.load_sec
        out["mode"] = _runner.mode
        out["backup"] = _runner.backup_on
        out["adapters"] = [a.name for a in _runner.cfg.adapters]
        try:
            import torch

            out["vram_gb"] = round(torch.cuda.memory_allocated() / 2**30, 2)
        except Exception:  # noqa: BLE001
            pass
    return out
