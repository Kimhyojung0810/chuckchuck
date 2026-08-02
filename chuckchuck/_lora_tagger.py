"""
[F-18 내부] Midm LoRA 태거 추론기입니다.
AI Hub 공적말하기 태깅 어댑터로 REP/FIL/WR 스팬을 뽑고 HabitSpan 으로 변환합니다.

호출: f18_habits.extract_habits(provider="lora") → tag_spans()
API: POST /api/v1/habits (기본 provider=lora)
스키마: HabitSpan {kind,text,start_sec,end_sec,slide_no}
사용자 지시: "LoRA를 기본으로 쓰게 하고 싶어"

기본 어댑터: 20_AIHub_data/runs/tagger_seed42/final
서빙은 greedy(repetition_penalty=1.0) — README_FINETUNING §5.3 권장(REP).
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from .contracts import HabitSpan, Transcript

MODEL_ID = "K-intelligence/Midm-2.0-Base-Instruct"
DEFAULT_ADAPTER = Path(
    "/home/ubuntu/workspace/20_AIHub_data/runs/tagger_seed42/final"
)
MAX_NEW_TOKENS = 512

SYSTEM_PROMPT = (
    "너는 한국어 공적 말하기 전사문에서 발화 오류 구간을 찾아내는 전문 주석기다.\n"
    "다음 세 가지만 찾는다.\n"
    "REP: 같은 말을 더듬거나 되풀이한 구간 (예: '지도 지도력은')\n"
    "FIL: 의미 없는 간투어 (예: '어', '음')\n"
    "WR: 잘못 발음했거나 잘못 쓴 낱말 (예: '지속성')\n"
    "출력은 '태그<TAB>원문구간' 형식의 줄 목록이며 REP, FIL, WR 순서로 적는다.\n"
    "해당하는 구간이 없으면 NONE 한 줄만 출력한다."
)
USER_TEMPLATE = "다음 발표 전사문에서 REP/FIL/WR 구간을 모두 찾아라.\n\n{stt_text}"
_WS = re.compile(r"\s+")

_lock = threading.Lock()
_model = None
_tokenizer = None
_loaded_adapter: str | None = None


def default_adapter_path() -> Path:
    env = os.environ.get("CHUCKCHUCK_LORA_PATH", "").strip()
    return Path(env) if env else DEFAULT_ADAPTER


def adapter_available(path: Path | None = None) -> bool:
    p = path or default_adapter_path()
    return p.exists() and (p / "adapter_config.json").exists()


def _normalize(text: str) -> str:
    return _WS.sub(" ", (text or "").strip())


def parse_tag_lines(raw: str) -> list[tuple[str, str]]:
    """모델 출력 → [(TAG, text), ...]."""
    out: list[tuple[str, str]] = []
    for line in (raw or "").strip().splitlines():
        line = line.strip()
        if not line or line == "NONE":
            continue
        tag, sep, body = line.partition("\t")
        if not sep:
            tag, sep, body = line.partition(" ")
        tag = tag.strip().upper()
        body = _normalize(body)
        if tag in ("REP", "FIL", "WR") and body:
            out.append((tag, body))
    return out


def _words(transcript: Transcript) -> list:
    words = list(transcript.words)
    if not words:
        for sp in transcript.by_slide:
            words.extend(sp.words)
    return words


def _locate_span(span_text: str, words: list) -> tuple[float, float] | None:
    """스팬 텍스트를 단어열에서 찾아 (start_sec, end_sec)."""
    if not words or not span_text:
        return None
    target = _normalize(span_text).split()
    if not target:
        return None
    norms = [_normalize(w.text) for w in words]
    n, m = len(norms), len(target)
    for i in range(n):
        if norms[i] != target[0]:
            continue
        if m <= n - i and norms[i:i + m] == target:
            return words[i].start_sec, words[i + m - 1].end_sec
        joined = norms[i]
        j = i
        want = _normalize(span_text)
        while j + 1 < n and len(joined) < len(want):
            j += 1
            joined = _normalize(joined + " " + norms[j])
            if joined == want or want in joined:
                return words[i].start_sec, words[j].end_sec
    for i, nrm in enumerate(norms):
        if nrm and (nrm == target[0] or target[0] in nrm or nrm in target[0]):
            return words[i].start_sec, words[i].end_sec
    return None


def _slide_at(transcript: Transcript, t: float) -> int | None:
    for sp in transcript.by_slide:
        if sp.start_sec <= t < sp.end_sec:
            return sp.slide_no
        if sp.words and sp.words[0].start_sec <= t <= sp.words[-1].end_sec:
            return sp.slide_no
    return None


def _ensure_model(adapter: Path):
    global _model, _tokenizer, _loaded_adapter
    key = str(adapter.resolve())
    if _model is not None and _loaded_adapter == key:
        return _model, _tokenizer

    with _lock:
        if _model is not None and _loaded_adapter == key:
            return _model, _tokenizer

        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        device = 0 if torch.cuda.is_available() else "cpu"
        tok_src = str(adapter) if (adapter / "tokenizer_config.json").exists() else MODEL_ID
        tokenizer = AutoTokenizer.from_pretrained(tok_src)
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        dtype = torch.bfloat16 if device != "cpu" else torch.float32
        try:
            model = AutoModelForCausalLM.from_pretrained(
                MODEL_ID, dtype=dtype, device_map={"": device} if device != "cpu" else None,
            )
        except TypeError:
            model = AutoModelForCausalLM.from_pretrained(
                MODEL_ID, torch_dtype=dtype, device_map={"": device} if device != "cpu" else None,
            )
        if device == "cpu":
            model = model.to("cpu")
        model = PeftModel.from_pretrained(model, str(adapter))
        model = model.merge_and_unload()
        model.eval()

        _model = model
        _tokenizer = tokenizer
        _loaded_adapter = key
        return _model, _tokenizer


def _generate(stt_text: str, adapter: Path) -> str:
    import torch

    model, tokenizer = _ensure_model(adapter)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_TEMPLATE.format(stt_text=stt_text)},
    ]
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = tokenizer(prompt, return_tensors="pt", add_special_tokens=False)
    inputs = {k: v.to(model.device) for k, v in inputs.items()}
    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            repetition_penalty=1.0,
            pad_token_id=tokenizer.pad_token_id,
        )
    return tokenizer.decode(
        output[0][inputs["input_ids"].shape[1]:],
        skip_special_tokens=True,
    )


def tag_spans(transcript: Transcript, adapter: str | Path | None = None) -> list[HabitSpan]:
    """
    Transcript → HabitSpan 목록 (기본 REP만).
    FIL 퇴행 때문에 CHUCKCHUCK_LORA_KINDS 기본값은 REP.
    PAUSE 는 f18 heuristic 쪽에서 합친다.
    """
    path = Path(adapter) if adapter else default_adapter_path()
    if not adapter_available(path):
        raise FileNotFoundError(f"LoRA adapter not found: {path}")

    stt = transcript.full_text or " ".join(w.text for w in _words(transcript))
    if not stt.strip():
        return []

    raw = _generate(stt, path)
    kinds_env = os.environ.get("CHUCKCHUCK_LORA_KINDS", "REP").upper()
    allow = {k.strip() for k in kinds_env.split(",") if k.strip()} or {"REP"}

    words = _words(transcript)
    spans: list[HabitSpan] = []
    for tag, text in parse_tag_lines(raw):
        if tag not in allow or tag not in ("REP", "FIL"):
            continue
        loc = _locate_span(text, words)
        if loc:
            start, end = loc
        else:
            start = end = 0.0
        spans.append(HabitSpan(
            kind=tag,
            text=text,
            start_sec=start,
            end_sec=end,
            slide_no=_slide_at(transcript, start) if loc else None,
        ))
    return spans
