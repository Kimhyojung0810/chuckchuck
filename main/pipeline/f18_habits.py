"""
[F-18] 음성 습관 신호(반복·간투어·긴 휴지)를 뽑는 모듈입니다.
Transcript → HabitDoc.

provider:
  - lora (기본): Mi:dm LoRA — REP 어댑터(rp 1.0) + FIL 어댑터 3시드 앙상블(rp 1.2, 있으면).
    어댑터가 없는 태그와 긴 휴지(PAUSE) 는 규칙으로. 무엇이 찾았는지는 HabitDoc.detectors 에 남는다.
    올리는 중이면 heuristic(lora-loading), 못 돌면 heuristic(lora-fallback).
  - heuristic: 규칙/사전만 (테스트·GPU 없을 때)
  - fixture: spans 가 이미 있으면 그대로 집계
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from dataclasses import replace
from collections import defaultdict

from .contracts import HabitDoc, HabitError, HabitSpan, SlideHabits, Transcript

FILLERS = {
    "어", "음", "그", "저", "에", "아", "뭐", "이제", "약간", "좀",
    "그게", "그냥", "사실은", "일단", "뭐랄까", "그니까", "그러니까",
    "어쨌든", "아무튼", "막",
}
PAUSE_SEC = 5.0
#: HabitDoc.detectors — 태그마다 무엇이 찾았나. lora · lora-ensemble×3 · rule · fixture
RULE_DETECTORS = {"REP": "rule", "FIL": "rule", "PAUSE": "rule"}
_NORM = re.compile(r"[^\w가-힣]+", re.UNICODE)


def _norm_tok(t: str) -> str:
    return _NORM.sub("", (t or "").strip().lower())


def _slide_at(transcript: Transcript, t: float) -> int | None:
    for sp in transcript.by_slide:
        if sp.start_sec <= t < sp.end_sec or (
            sp.words and sp.words[0].start_sec <= t <= sp.words[-1].end_sec
        ):
            return sp.slide_no
    best = None
    best_d = 1e9
    for sp in transcript.by_slide:
        mid = (sp.start_sec + sp.end_sec) / 2
        d = abs(mid - t)
        if d < best_d:
            best_d = d
            best = sp.slide_no
    return best


def _heuristic_spans(transcript: Transcript, *, kinds: set[str] | None = None) -> list[HabitSpan]:
    want = kinds or {"REP", "FIL", "PAUSE"}
    words = list(transcript.words)
    if not words and transcript.by_slide:
        for sp in transcript.by_slide:
            words.extend(sp.words)
    spans: list[HabitSpan] = []

    if "FIL" in want:
        for w in words:
            tok = _norm_tok(w.text)
            if tok in FILLERS:
                spans.append(HabitSpan(
                    kind="FIL",
                    text=w.text,
                    start_sec=w.start_sec,
                    end_sec=w.end_sec,
                    slide_no=_slide_at(transcript, w.start_sec),
                ))

    if "REP" in want:
        for i in range(1, len(words)):
            a, b = words[i - 1], words[i]
            na, nb = _norm_tok(a.text), _norm_tok(b.text)
            if na and na == nb and len(na) >= 1:
                spans.append(HabitSpan(
                    kind="REP",
                    text=f"{a.text} {b.text}",
                    start_sec=a.start_sec,
                    end_sec=b.end_sec,
                    slide_no=_slide_at(transcript, a.start_sec),
                ))
            elif na and nb and nb.startswith(na) and len(na) >= 2:
                # 접두 반복("지도 지도력은") — 인접 쌍(a, b)에서 바로 잡는다. 예전 코드는 words[i-2]·words[i-1] 을
                # 비교하면서 스팬은 words[i] 까지 잡아 한 단어 밀렸고, 전사 끝의 반복은 아예 놓쳤다 (2026-09-13 감사).
                spans.append(HabitSpan(
                    kind="REP",
                    text=f"{a.text} {b.text}",
                    start_sec=a.start_sec,
                    end_sec=b.end_sec,
                    slide_no=_slide_at(transcript, a.start_sec),
                ))

    if "PAUSE" in want:
        for i in range(1, len(words)):
            gap = words[i].start_sec - words[i - 1].end_sec
            if gap < PAUSE_SEC:
                continue
            s0 = _slide_at(transcript, words[i - 1].end_sec)
            s1 = _slide_at(transcript, words[i].start_sec)
            if s0 is not None and s0 == s1:
                spans.append(HabitSpan(
                    kind="PAUSE",
                    text=f"{gap:.1f}s",
                    start_sec=words[i - 1].end_sec,
                    end_sec=words[i].start_sec,
                    slide_no=s0,
                ))
    return spans


def _internal(name: str):
    """sys.modules 를 먼저 보는 import — 테스트가 끼운 스텁이 패키지 속성보다 이긴다 (from . import 는 반대)."""
    return importlib.import_module(f"{__package__}.{name}")


class _LoraOutcome:
    """LoRA 한 번 돌린 결과 — 스팬, 맡은 태그(태그→탐지기 이름), 못 돌았을 때 그 까닭."""

    def __init__(self, spans=None, covered=None, why: str = ""):
        self.spans: list[HabitSpan] = list(spans or [])
        self.covered: dict[str, str] = dict(covered or {})
        self.why = why

    @property
    def ok(self) -> bool:
        return not self.why


def _lora_spans(transcript: Transcript) -> _LoraOutcome:
    """LoRA 추론. 못 돌면 why 에 까닭(fallback · loading) → 호출측이 규칙으로 대신한다."""
    try:
        _lora_tagger = _internal("_lora_tagger")
    except Exception as e:  # noqa: BLE001 — torch 없는 python 등
        sys.stderr.write(f"[f18] LoRA 모듈을 못 불러 규칙으로 대신해요: {type(e).__name__}: {e}\n")
        return _LoraOutcome(why="fallback")
    if _lora_tagger is None or not _lora_tagger.adapter_available():
        return _LoraOutcome(why="fallback")
    not_ready = getattr(_lora_tagger, "LoraNotReady", None)
    try:
        tag = getattr(_lora_tagger, "tag_habits", None)
        if tag is None:  # 옛 인터페이스(스팬만) — 나온 태그를 맡은 것으로 본다
            spans = _lora_tagger.tag_spans(transcript)
            return _LoraOutcome(spans, {s.kind: "lora" for s in spans})
        res = tag(transcript)
        return _LoraOutcome(res.spans, res.covered)
    except Exception as e:  # noqa: BLE001
        if not_ready is not None and isinstance(e, not_ready):
            return _LoraOutcome(why="loading")
        sys.stderr.write(f"[f18] LoRA 실패 → 규칙으로 대신해요: {type(e).__name__}: {e}\n")
        return _LoraOutcome(why="fallback")


def _merge_lora_and_heuristic(transcript: Transcript, lora: list[HabitSpan],
                              covered: dict[str, str] | None = None) -> tuple[list[HabitSpan], dict[str, str]]:
    """
    LoRA 가 맡은 태그는 LoRA 결과만 믿는다 (0개여도 — 「찾아 봤는데 없다」).
    맡지 않은 태그와 긴 휴지(PAUSE, 타임스탬프 계산) 는 규칙으로 채운다.
    covered 가 없으면(옛 인터페이스) LoRA 가 낸 태그를 맡은 것으로 본다.
    """
    cov = dict(covered) if covered is not None else {s.kind: "lora" for s in lora}
    need = {"PAUSE"} | ({"REP", "FIL"} - set(cov))
    extra = _heuristic_spans(transcript, kinds=need)
    detectors = {k: cov.get(k, "rule") for k in ("REP", "FIL")}
    detectors["PAUSE"] = "rule"
    return [s for s in lora if s.kind in cov] + extra, detectors


def preload_lora() -> bool:
    """브리지가 뜰 때 뒤에서 LoRA 를 미리 올린다 (HABIT_PROVIDER=lora 일 때만). 올리기 시작했으면 True."""
    if (os.environ.get("HABIT_PROVIDER") or "lora").lower() != "lora":
        return False
    if os.environ.get("CHUCKCHUCK_LORA_PRELOAD", "1") == "0":
        return False
    try:
        _lora_tagger = _internal("_lora_tagger")
        _lora_runtime = _internal("_lora_runtime")
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[f18] LoRA 미리 올리기 생략: {type(e).__name__}: {e}\n")
        return False
    cfg = _lora_tagger.load_config()
    if cfg.missing:
        sys.stderr.write(f"[f18] 설정한 어댑터 경로에 adapter_config.json 이 없어요: {list(cfg.missing)}\n")
    if not cfg.adapters:
        sys.stderr.write("[f18] LoRA 어댑터가 없어 습관 분석은 규칙으로 돌아요 (heuristic(lora-fallback))\n")
        return False
    return _lora_runtime.preload(cfg)


def _aggregate(spans: list[HabitSpan], transcript: Transcript) -> HabitDoc:
    by: dict[int, dict] = defaultdict(lambda: {"REP": 0, "FIL": 0, "PAUSE": 0})
    spans = [replace(s) for s in spans]  # 호출자가 넘긴 객체를 제자리에서 바꾸지 않는다
    for s in spans:
        no = s.slide_no
        if no is None:
            no = _slide_at(transcript, s.start_sec) or 0
            s.slide_no = no if no else None
        if no:
            by[no][s.kind] += 1

    slide_nos = sorted({sp.slide_no for sp in transcript.by_slide} | set(by))
    by_slide: list[SlideHabits] = []
    for no in slide_nos:
        c = by.get(no, {"REP": 0, "FIL": 0, "PAUSE": 0})
        note_parts = []
        if c["REP"] >= 2:
            note_parts.append(f"같은 장을 더듬으며 반복 {c['REP']}회")
        if c["FIL"] >= 3:
            note_parts.append(f"간투어 {c['FIL']}회")
        if c["PAUSE"] >= 1:
            note_parts.append(f"긴 휴지 {c['PAUSE']}회")
        by_slide.append(SlideHabits(
            slide_no=no,
            repeat_cnt=c["REP"],
            filler_cnt=c["FIL"],
            pause_cnt=c["PAUSE"],
            note=" · ".join(note_parts),
        ))

    rep = sum(1 for s in spans if s.kind == "REP")
    fil = sum(1 for s in spans if s.kind == "FIL")
    pau = sum(1 for s in spans if s.kind == "PAUSE")

    tips: list[str] = []
    noisy = [s for s in by_slide if s.repeat_cnt + s.filler_cnt >= 3]
    for s in noisy[:3]:
        tips.append(f"{s.slide_no}번: {s.note or '습관 신호 다수'}")
    if pau:
        tips.append(f"5초 이상 긴 쉼이 {pau}번 있어요. 전환 멘트를 미리 정해 보세요.")
    if not tips:
        tips.append("눈에 띄는 반복·간투어·긴 휴지는 적어요.")

    return HabitDoc(
        spans=spans,
        by_slide=by_slide,
        repeat_cnt=rep,
        filler_cnt=fil,
        pause_cnt=pau,
        tips=tips,
    )


def extract_habits(
    transcript: Transcript | dict,
    *,
    provider: str | None = None,
    spans: list[HabitSpan] | list[dict] | None = None,
) -> HabitDoc:
    """습관 스팬을 뽑고 슬라이드별로 집계한다. 기본 provider=lora."""
    if isinstance(transcript, dict):
        transcript = Transcript.from_dict(transcript)
    if not transcript.words and not transcript.by_slide:
        raise HabitError("Transcript 가 비어 있습니다. F-05 결과를 먼저 확인하세요.")

    prov = (provider or os.environ.get("HABIT_PROVIDER") or "lora").lower()

    if spans is not None:
        parsed = [
            HabitSpan.from_dict(s) if isinstance(s, dict) else s
            for s in spans
        ]
        doc = _aggregate(parsed, transcript)
        doc.provider = "fixture"
        doc.detectors = {"REP": "fixture", "FIL": "fixture", "PAUSE": "fixture"}
        return doc

    if prov == "lora":
        out = _lora_spans(transcript)
        if out.ok:
            merged, detectors = _merge_lora_and_heuristic(transcript, out.spans, out.covered)
            doc = _aggregate(merged, transcript)
            doc.provider = "lora"
            doc.detectors = detectors
            return doc
        # 어댑터/GPU/의존성 없으면(fallback) · 미리 올리는 중이면(loading) 규칙으로
        doc = _aggregate(_heuristic_spans(transcript), transcript)
        doc.provider = f"heuristic(lora-{out.why})"
        doc.detectors = dict(RULE_DETECTORS)
        return doc

    if prov == "heuristic":
        doc = _aggregate(_heuristic_spans(transcript), transcript)
        doc.provider = "heuristic"
        doc.detectors = dict(RULE_DETECTORS)
        return doc

    raise HabitError(f"unknown habit provider: {prov}")
