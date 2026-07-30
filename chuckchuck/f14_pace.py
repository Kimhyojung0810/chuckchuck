"""
[F-14] 말 속도와 시간 배분을 재는 모듈입니다.

Transcript(+선택 ConceptGraph) → PaceDoc. LLM 을 부르지 않는 순수 함수입니다.

한국어 발표는 '자/분'(분당 글자 수)으로 잽니다. 단어 수로 재면 조사·어미 때문에
같은 속도라도 문체에 따라 값이 흔들립니다.

시간 배분의 '권장' 은 임의로 정하지 않습니다. **자료가 힘준 만큼 시간을 썼는가**로
봅니다 — F-07 이 이미 매긴 노드 weight 를 구획별로 합쳐 권장 비율로 씁니다.
그래야 일반론이 아니라 "이 발표에서" 무엇이 과했고 부족했는지가 나옵니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import ConceptGraph, Transcript

#: 발표 권장 속도(자/분). 낭독이 아니라 청중 앞 발표 기준.
RECOMMENDED_CPM_MIN = 300
RECOMMENDED_CPM_MAX = 350

#: 본인 평균 대비 이만큼 벗어나면 빠름/느림으로 표시한다.
FAST_RATIO = 1.15
SLOW_RATIO = 0.85

#: 이보다 짧은 구간은 속도를 못 믿는다 (한두 마디로 자/분이 튄다).
MIN_RELIABLE_SEC = 5.0

#: 권장 대비 이만큼(%p) 벗어나면 과함/부족으로 본다.
ALLOC_TOLERANCE_PCT = 10.0


def _chars(text: str) -> int:
    """공백을 뺀 글자 수. 띄어쓰기 습관이 속도에 섞이면 안 된다."""
    return len("".join((text or "").split()))


@dataclass
class PaceSegment:
    """슬라이드 한 구간의 말 속도."""
    slide_no: int
    label: str = ""
    start_sec: float = 0.0
    end_sec: float = 0.0
    chars: int = 0
    cpm: float = 0.0
    is_fast: bool = False
    is_slow: bool = False
    reliable: bool = True      # 너무 짧으면 False — 화면에서 흐리게 표시하라는 뜻

    @property
    def duration(self) -> float:
        return max(0.0, self.end_sec - self.start_sec)

    def to_dict(self) -> dict:
        return {
            "slide_no": self.slide_no,
            "label": self.label,
            "start_sec": round(self.start_sec, 2),
            "end_sec": round(self.end_sec, 2),
            "chars": self.chars,
            "cpm": round(self.cpm),
            "is_fast": self.is_fast,
            "is_slow": self.is_slow,
            "reliable": self.reliable,
        }


@dataclass
class SectionAllocation:
    """구획별 시간 배분. 권장은 자료가 배분한 weight 다."""
    name: str
    slide_nos: list[int] = field(default_factory=list)
    recommended_pct: float = 0.0
    actual_pct: float = 0.0
    actual_sec: float = 0.0

    @property
    def gap_pct(self) -> float:
        return self.actual_pct - self.recommended_pct

    def verdict(self) -> str:
        if self.gap_pct > ALLOC_TOLERANCE_PCT:
            return "over"
        if self.gap_pct < -ALLOC_TOLERANCE_PCT:
            return "under"
        return "ok"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "slide_nos": list(self.slide_nos),
            "recommended_pct": round(self.recommended_pct, 1),
            "actual_pct": round(self.actual_pct, 1),
            "actual_sec": round(self.actual_sec, 1),
            "gap_pct": round(self.gap_pct, 1),
            "verdict": self.verdict(),
        }


@dataclass
class PaceDoc:
    file_name: str = ""
    total_sec: float = 0.0
    total_chars: int = 0
    avg_cpm: float = 0.0
    segments: list[PaceSegment] = field(default_factory=list)
    allocations: list[SectionAllocation] = field(default_factory=list)
    recommended_min: int = RECOMMENDED_CPM_MIN
    recommended_max: int = RECOMMENDED_CPM_MAX

    @property
    def fastest(self) -> PaceSegment | None:
        usable = [s for s in self.segments if s.reliable]
        return max(usable, key=lambda s: s.cpm) if usable else None

    @property
    def slowest(self) -> PaceSegment | None:
        usable = [s for s in self.segments if s.reliable]
        return min(usable, key=lambda s: s.cpm) if usable else None

    def to_dict(self) -> dict:
        fast, slow = self.fastest, self.slowest
        return {
            "file_name": self.file_name,
            "total_sec": round(self.total_sec, 1),
            "total_chars": self.total_chars,
            "avg_cpm": round(self.avg_cpm),
            "recommended_min": self.recommended_min,
            "recommended_max": self.recommended_max,
            "segments": [s.to_dict() for s in self.segments],
            "allocations": [a.to_dict() for a in self.allocations],
            "fastest": fast.to_dict() if fast else None,
            "slowest": slow.to_dict() if slow else None,
        }


def _labels_from_graph(graph: ConceptGraph | None) -> dict[int, str]:
    """슬라이드 번호 → 그 장에서 가장 무거운 개념 이름. 구간 이름표로 쓴다."""
    if graph is None:
        return {}
    best: dict[int, tuple[float, str]] = {}
    for n in graph.nodes:
        weight = getattr(n, "weight", 0.0) or 0.0
        for no in n.slide_nos:
            if no not in best or weight > best[no][0]:
                best[no] = (weight, n.label)
    return {no: label for no, (_, label) in best.items()}


def _allocations(
    graph: ConceptGraph | None,
    sec_by_slide: dict[int, float],
    total_sec: float,
) -> list[SectionAllocation]:
    """
    구획별 권장 대비 실제.

    권장은 그 구획에 속한 노드 weight 의 합 비율이다 — 자료가 힘을 실은 만큼
    시간을 썼는지 보는 것이라, 임의의 '이상적 배분' 을 들이대지 않는다.
    """
    if graph is None or not graph.sections or total_sec <= 0:
        return []

    weight_by_slide: dict[int, float] = {}
    for n in graph.nodes:
        nos = list(n.slide_nos)
        if not nos:
            continue
        share = (getattr(n, "weight", 0.0) or 0.0) / len(nos)
        for no in nos:
            weight_by_slide[no] = weight_by_slide.get(no, 0.0) + share

    total_weight = sum(weight_by_slide.values())
    out: list[SectionAllocation] = []
    for sec in graph.sections:
        nos = list(sec.slide_nos)
        w = sum(weight_by_slide.get(n, 0.0) for n in nos)
        t = sum(sec_by_slide.get(n, 0.0) for n in nos)
        out.append(SectionAllocation(
            name=sec.name,
            slide_nos=nos,
            recommended_pct=(w / total_weight * 100.0) if total_weight > 0 else 0.0,
            actual_pct=t / total_sec * 100.0,
            actual_sec=t,
        ))
    return out


def analyze_pace(
    transcript: Transcript,
    graph: ConceptGraph | None = None,
) -> PaceDoc:
    """
    Transcript(+선택 ConceptGraph) → PaceDoc.

    graph 를 주면 구간에 개념 이름표가 붙고 시간 배분이 계산된다.
    """
    doc = PaceDoc(file_name=getattr(graph, "file_name", "") or "")
    labels = _labels_from_graph(graph)

    segments: list[PaceSegment] = []
    sec_by_slide: dict[int, float] = {}
    total_chars = 0
    total_sec = 0.0

    for sp in transcript.by_slide:
        dur = max(0.0, float(sp.end_sec) - float(sp.start_sec))
        chars = _chars(sp.text)
        total_chars += chars
        total_sec += dur
        sec_by_slide[sp.slide_no] = sec_by_slide.get(sp.slide_no, 0.0) + dur
        # 0초 구간은 속도를 정의할 수 없다 — 나눗셈을 태우지 않는다
        cpm = (chars / dur * 60.0) if dur > 0 else 0.0
        segments.append(PaceSegment(
            slide_no=sp.slide_no,
            label=labels.get(sp.slide_no, f"{sp.slide_no}번 슬라이드"),
            start_sec=float(sp.start_sec),
            end_sec=float(sp.end_sec),
            chars=chars,
            cpm=cpm,
            reliable=dur >= MIN_RELIABLE_SEC and chars > 0,
        ))

    # by_slide 가 비어 있으면(marks 없음) 전체 전사만으로 평균을 낸다
    if not segments:
        total_chars = _chars(transcript.full_text)
        total_sec = float(transcript.duration_sec or 0.0)

    doc.total_chars = total_chars
    doc.total_sec = total_sec
    doc.avg_cpm = (total_chars / total_sec * 60.0) if total_sec > 0 else 0.0

    # 빠름/느림은 본인 평균 기준이다. 절대 기준으로 재면 원래 빠른 사람은 전 구간이
    # 빨갛게 뜨고, 그건 피드백이 아니라 잡음이다.
    for s in segments:
        if not s.reliable or doc.avg_cpm <= 0:
            continue
        s.is_fast = s.cpm > doc.avg_cpm * FAST_RATIO
        s.is_slow = s.cpm < doc.avg_cpm * SLOW_RATIO

    doc.segments = segments
    doc.allocations = _allocations(graph, sec_by_slide, total_sec)
    return doc
