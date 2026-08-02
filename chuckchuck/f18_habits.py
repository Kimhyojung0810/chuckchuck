"""
[F-18] 음성 습관 신호(반복·간투어·긴 휴지)를 뽑는 모듈입니다.
Transcript → HabitDoc.

provider:
  - lora (기본): Midm LoRA 태거로 REP(기본) 추출 + heuristic 으로 FIL/PAUSE 보강
  - heuristic: 규칙/사전만 (테스트·GPU 없을 때)
  - fixture: spans 가 이미 있으면 그대로 집계
"""

from __future__ import annotations

import os
import re
from collections import defaultdict

from .contracts import HabitDoc, HabitError, HabitSpan, SlideHabits, Transcript

FILLERS = {
    "어", "음", "그", "저", "에", "아", "뭐", "이제", "약간", "좀",
    "그게", "그냥", "사실은", "일단", "뭐랄까", "그니까", "그러니까",
    "어쨌든", "아무튼", "막",
}
PAUSE_SEC = 5.0
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
            elif i >= 2:
                prev2 = _norm_tok(words[i - 2].text)
                if na and prev2 and na.startswith(prev2) and len(prev2) >= 2 and na != prev2:
                    spans.append(HabitSpan(
                        kind="REP",
                        text=f"{words[i - 2].text} {b.text}",
                        start_sec=words[i - 2].start_sec,
                        end_sec=b.end_sec,
                        slide_no=_slide_at(transcript, words[i - 2].start_sec),
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


def _lora_spans(transcript: Transcript) -> list[HabitSpan] | None:
    """LoRA 추론. 실패 시 None → 호출측에서 heuristic 폴백."""
    try:
        from . import _lora_tagger
    except Exception:
        return None
    if not _lora_tagger.adapter_available():
        return None
    try:
        return _lora_tagger.tag_spans(transcript)
    except Exception:
        return None


def _merge_lora_and_heuristic(transcript: Transcript, lora: list[HabitSpan]) -> list[HabitSpan]:
    """
    LoRA 기본 기여: REP (CHUCKCHUCK_LORA_KINDS 로 FIL 포함 가능).
    타임스탬프 휴지·간투어는 heuristic 보강.
    """
    lora_kinds = {s.kind for s in lora}
    # FIL 을 LoRA 가 안 줬으면 heuristic FIL 사용 (기본 설정)
    need = {"PAUSE"}
    if "FIL" not in lora_kinds:
        need.add("FIL")
    # LoRA 가 REP 를 전혀 못 뽑으면 heuristic REP 로라도 보강
    if "REP" not in lora_kinds:
        need.add("REP")
    extra = _heuristic_spans(transcript, kinds=need)
    return list(lora) + extra


def _aggregate(spans: list[HabitSpan], transcript: Transcript) -> HabitDoc:
    by: dict[int, dict] = defaultdict(lambda: {"REP": 0, "FIL": 0, "PAUSE": 0})
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
        return doc

    if prov == "lora":
        lora = _lora_spans(transcript)
        if lora is not None:
            doc = _aggregate(_merge_lora_and_heuristic(transcript, lora), transcript)
            doc.provider = "lora"
            return doc
        # 어댑터/GPU/의존성 없으면 heuristic 폴백
        doc = _aggregate(_heuristic_spans(transcript), transcript)
        doc.provider = "heuristic(lora-fallback)"
        return doc

    if prov == "heuristic":
        doc = _aggregate(_heuristic_spans(transcript), transcript)
        doc.provider = "heuristic"
        return doc

    raise HabitError(f"unknown habit provider: {prov}")
