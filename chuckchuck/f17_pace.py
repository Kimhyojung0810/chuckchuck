"""
[F-17] 말 속도·시간 배분을 규칙으로 계산하는 모듈입니다.
Transcript(+선택 ConceptDoc/Context) → PaceDoc. LLM을 쓰지 않습니다.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .contracts import (
    ConceptDoc,
    Context,
    PaceDoc,
    PaceError,
    SectionAlloc,
    SlidePace,
    Transcript,
)

# core / support 가중 (F-06 importance 와 동일 스케일)
_IMP_W = {"core": 1.0, "support": 0.35}
_HANGUL = re.compile(r"[가-힣]")
_REC_CPM = (300.0, 350.0)
# 권장 대비 ±25% 안이면 ok, 밖이면 short/long
_TIME_TOL = 0.25
# 평균 대비 +20% 이상이면 fast
_FAST_RATIO = 1.20


def count_syllables(text: str) -> int:
    """한글 음절 + 영문 대략 음절 수."""
    hangul = len(_HANGUL.findall(text or ""))
    latin = re.findall(r"[A-Za-z]+", text or "")
    latin_syl = sum(max(1, (len(w) + 2) // 3) for w in latin)
    return hangul + latin_syl


def count_chars(text: str) -> int:
    """공백 제외 글자 수 (자/분 계산용)."""
    return len(re.sub(r"\s+", "", text or ""))


def _importance_map(concept_doc: ConceptDoc | None, slide_nos: list[int]) -> dict[int, tuple[str, float]]:
    out: dict[int, tuple[str, float]] = {}
    if concept_doc:
        for s in concept_doc.slides:
            imp = s.importance if s.importance in _IMP_W else "support"
            out[s.slide_no] = (imp, _IMP_W[imp])
    for no in slide_nos:
        if no not in out:
            out[no] = ("support", _IMP_W["support"])
    return out


def _title_map(concept_doc: ConceptDoc | None) -> dict[int, str]:
    if not concept_doc:
        return {}
    return {s.slide_no: s.title or s.topic or f"{s.slide_no}번" for s in concept_doc.slides}


def _aggregate_by_slide(transcript: Transcript) -> dict[int, dict]:
    """재방문을 합쳐 슬라이드별 체류 시간·발화 시간·글자·음절을 모은다.

    - sec: 슬라이드 체류(권장 대비 배분용) = by_slide start~end
    - speak_sec: 실제 발화 길이(속도 계산용) = words 구간
    """
    buckets: dict[int, dict] = defaultdict(lambda: {
        "sec": 0.0, "speak_sec": 0.0, "chars": 0, "syl": 0, "text": [], "words": 0,
    })
    for sp in transcript.by_slide:
        if not sp.words and not (sp.text or "").strip():
            continue
        wall = max(0.0, sp.end_sec - sp.start_sec)
        if sp.words:
            speak = max(0.0, sp.words[-1].end_sec - sp.words[0].start_sec)
            text = " ".join(w.text for w in sp.words)
        else:
            speak = wall
            text = sp.text or ""
        b = buckets[sp.slide_no]
        b["sec"] += wall if wall > 0 else speak
        b["speak_sec"] += speak
        b["chars"] += count_chars(text)
        b["syl"] += count_syllables(text)
        b["text"].append(text)
        b["words"] += len(sp.words)
    return dict(buckets)


def _status(actual: float, recommended: float, cpm: float, avg_cpm: float) -> tuple[str, str]:
    if recommended <= 0:
        return "ok", ""
    ratio = actual / recommended
    if ratio < 1.0 - _TIME_TOL:
        return "short", f"권장 대비 {int((1 - ratio) * 100)}% 부족"
    if ratio > 1.0 + _TIME_TOL:
        return "long", f"권장 대비 {int((ratio - 1) * 100)}% 초과"
    if avg_cpm > 0 and cpm >= avg_cpm * _FAST_RATIO:
        return "fast", "이 구간 말이 평균보다 빨라요"
    if avg_cpm > 0 and cpm > 0 and cpm <= avg_cpm * 0.75:
        return "slow", "이 구간 말이 평균보다 느려요"
    return "ok", "적절"


def _section_allocs(slides: list[SlidePace]) -> list[SectionAlloc]:
    groups: list[tuple[str, list[SlidePace]]]
    if len(slides) >= 6:
        n = len(slides)
        groups = [
            ("전반", slides[: n // 3 or 1]),
            ("중반", slides[n // 3: (2 * n) // 3]),
            ("후반", slides[(2 * n) // 3:]),
        ]
    else:
        groups = [
            ("핵심(core)", [s for s in slides if s.importance == "core"]),
            ("보조(support)", [s for s in slides if s.importance != "core"]),
        ]

    out: list[SectionAlloc] = []
    for name, group in groups:
        if not group:
            continue
        rec = sum(s.recommended_sec for s in group)
        act = sum(s.actual_sec for s in group)
        if rec <= 0:
            st, label = "ok", "적절"
        else:
            r = act / rec
            if r < 1.0 - _TIME_TOL:
                st, label = "short", f"-{int((1 - r) * 100)}% 부족"
            elif r > 1.0 + _TIME_TOL:
                st, label = "long", f"+{int((r - 1) * 100)}% 초과"
            else:
                st, label = "ok", "적절"
        out.append(SectionAlloc(
            name=name,
            slide_nos=[s.slide_no for s in group],
            recommended_sec=round(rec, 1),
            actual_sec=round(act, 1),
            status=st,
            label=label,
        ))
    return out


def _tips(pace: PaceDoc) -> list[str]:
    tips: list[str] = []
    if pace.target_sec > 0 and pace.actual_sec > pace.target_sec * 1.05:
        over = pace.actual_sec - pace.target_sec
        long_support = [
            s for s in pace.slides
            if s.importance != "core" and s.status == "long"
        ]
        if long_support:
            nos = ", ".join(f"{s.slide_no}번" for s in long_support[:3])
            tips.append(
                f"목표보다 {over:.0f}초 길어요. 덜 중요한 {nos}을(를) 빠르게 줄여 보세요."
            )
        else:
            tips.append(f"목표보다 {over:.0f}초 길어요. 보조 슬라이드 설명을 한 문장씩 줄여 보세요.")
    elif pace.target_sec > 0 and pace.actual_sec < pace.target_sec * 0.9:
        tips.append("목표 시간보다 짧아요. 핵심 슬라이드에 예시나 한 문장을 더 넣어 보세요.")

    short_core = [s for s in pace.slides if s.importance == "core" and s.status == "short"]
    for s in short_core[:2]:
        tips.append(
            f"{s.slide_no}번은 핵심인데 권장 {s.recommended_sec:.0f}초 중 "
            f"{s.actual_sec:.0f}초만 썼어요. 여기 시간을 늘리세요."
        )
    fast_core = [s for s in pace.slides if s.importance == "core" and s.status == "fast"]
    for s in fast_core[:1]:
        tips.append(
            f"{s.slide_no}번(핵심)에서 말이 빨라요({s.chars_per_min:.0f}자/분). "
            "핵심 문장은 천천히 또박또박."
        )
    if not tips:
        tips.append("시간 배분과 말 속도가 대체로 안정적이에요.")
    return tips


def analyze_pace(
    transcript: Transcript | dict,
    context: Context | dict | None = None,
    concept_doc: ConceptDoc | dict | None = None,
) -> PaceDoc:
    """
    슬라이드별 말 속도·권장/실제 시간을 계산한다.

    - 권장 시간 = 목표초 × (importance_weight / Σweight)
    - 목표 분이 없으면 실제 총시간을 목표로 써서 상대 배분만 본다.
    """
    if isinstance(transcript, dict):
        transcript = Transcript.from_dict(transcript)
    if isinstance(context, dict):
        context = Context.from_dict(context)
    if isinstance(concept_doc, dict):
        concept_doc = ConceptDoc.from_dict(concept_doc)

    if not transcript.by_slide and not transcript.words:
        raise PaceError("Transcript 가 비어 있습니다. F-05 결과를 먼저 확인하세요.")

    buckets = _aggregate_by_slide(transcript)
    if not buckets:
        text = transcript.full_text or " ".join(w.text for w in transcript.words)
        dur = transcript.duration_sec or (
            transcript.words[-1].end_sec - transcript.words[0].start_sec
            if transcript.words else 0.0
        )
        buckets = {1: {
            "sec": dur, "chars": count_chars(text), "syl": count_syllables(text),
            "text": [text], "words": len(transcript.words),
        }}

    slide_nos = sorted(buckets)
    imp = _importance_map(concept_doc, slide_nos)
    titles = _title_map(concept_doc)

    actual_total = sum(buckets[n]["sec"] for n in slide_nos)
    target = float((context.duration_min or 0) * 60) if context else 0.0
    if target <= 0:
        target = actual_total or 1.0

    weight_sum = sum(imp[n][1] for n in slide_nos) or 1.0

    raw_cpm: dict[int, float] = {}
    raw_sps: dict[int, float] = {}
    for n in slide_nos:
        b = buckets[n]
        speak = b.get("speak_sec") or b["sec"] or 0.0
        raw_cpm[n] = (b["chars"] / speak * 60.0) if speak > 0.2 else 0.0
        raw_sps[n] = (b["syl"] / speak) if speak > 0.2 else 0.0

    speaking_sec = sum(
        (buckets[n].get("speak_sec") or buckets[n]["sec"])
        for n in slide_nos
        if (buckets[n].get("speak_sec") or buckets[n]["sec"]) > 0.2
    ) or actual_total or 1.0
    total_chars = sum(buckets[n]["chars"] for n in slide_nos)
    total_syl = sum(buckets[n]["syl"] for n in slide_nos)
    avg_cpm = total_chars / speaking_sec * 60.0 if speaking_sec > 0 else 0.0
    avg_sps = total_syl / speaking_sec if speaking_sec > 0 else 0.0

    slides: list[SlidePace] = []
    for n in slide_nos:
        b = buckets[n]
        importance, w = imp[n]
        rec = target * (w / weight_sum)
        act = b["sec"]
        cpm = raw_cpm[n]
        sps = raw_sps[n]
        st, note = _status(act, rec, cpm, avg_cpm)
        if importance == "core" and rec > 0 and act < rec * (1.0 - _TIME_TOL):
            st = "short"
            note = f"핵심 · 권장 대비 {int((1 - act / rec) * 100)}% 부족"
        slides.append(SlidePace(
            slide_no=n,
            title=titles.get(n) or f"{n}번 슬라이드",
            importance=importance,
            importance_weight=w,
            actual_sec=round(act, 2),
            recommended_sec=round(rec, 2),
            delta_sec=round(act - rec, 2),
            chars_per_min=round(cpm, 1),
            syllable_per_sec=round(sps, 2),
            status=st,
            note=note,
        ))

    max_slide = max(slides, key=lambda s: s.chars_per_min) if slides else None
    doc = PaceDoc(
        target_sec=round(target, 1),
        actual_sec=round(actual_total, 1),
        avg_chars_per_min=round(avg_cpm, 1),
        avg_syllable_per_sec=round(avg_sps, 2),
        max_chars_per_min=round(max_slide.chars_per_min, 1) if max_slide else 0.0,
        max_slide_no=max_slide.slide_no if max_slide else None,
        recommended_cpm=f"{int(_REC_CPM[0])}~{int(_REC_CPM[1])}",
        slides=slides,
        sections=_section_allocs(slides),
    )
    doc.tips = _tips(doc)
    return doc
