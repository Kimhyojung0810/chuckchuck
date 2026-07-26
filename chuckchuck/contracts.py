"""
모듈끼리 주고받는 데이터 모양(계약)을 정한 파일입니다.
SlideDoc, Transcript, ConceptDoc 같은 공통 타입이 여기 있습니다.
프론트·서버·모듈이 모두 이 모양의 JSON으로만 대화합니다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# F-01 : 발표자료 파싱 결과
# ---------------------------------------------------------------------------

@dataclass
class SlideBlock:
    """슬라이드 안의 텍스트 덩어리 하나 (Document Parse element 1개)."""
    category: str
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Slide:
    slide_no: int
    title: str = ""
    blocks: list[SlideBlock] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    total_char_count: int = 0
    line_count: int = 0
    has_visual: bool = False
    visual_type: list[str] = field(default_factory=list)
    alignment: str | None = None  # left | right | center | None
    text_sparse: bool = False
    image_only: bool = False

    @property
    def raw_text(self) -> str:
        return "\n".join(b.text for b in self.blocks if b.text.strip())

    def to_dict(self) -> dict:
        return {
            "slide_no": self.slide_no,
            "title": self.title,
            "blocks": [b.to_dict() for b in self.blocks],
            "categories": list(self.categories),
            "total_char_count": self.total_char_count,
            "line_count": self.line_count,
            "has_visual": self.has_visual,
            "visual_type": list(self.visual_type),
            "alignment": self.alignment,
            "text_sparse": self.text_sparse,
            "image_only": self.image_only,
            "raw_text": self.raw_text,
        }


@dataclass
class SlideDoc:
    """F-01의 산출물. 발표자료 전체."""
    file_name: str
    total_slides: int
    slides: list[Slide] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "total_slides": self.total_slides,
            "slides": [s.to_dict() for s in self.slides],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SlideDoc":
        slides = []
        for s in d.get("slides", []):
            blocks = [SlideBlock(**b) for b in s.get("blocks", [])]
            # 구 fixture: 지표 없으면 blocks 에서 최소 유도
            char_count = int(s.get("total_char_count", sum(len(b.text) for b in blocks)))
            has_visual = bool(
                s["has_visual"] if "has_visual" in s
                else any(b.category in ("figure", "chart", "image", "table") for b in blocks)
            )
            cats = list(s.get("categories") or [])
            if not cats:
                seen: list[str] = []
                for b in blocks:
                    if b.category not in seen:
                        seen.append(b.category)
                cats = seen
            visual_type = list(s.get("visual_type") or [])
            if "visual_type" not in s:
                visual_type = [
                    c for c in ("figure", "chart", "table", "image") if c in cats
                ]
            text_sparse = bool(s.get("text_sparse", char_count < 20))
            slides.append(Slide(
                slide_no=s["slide_no"],
                title=s.get("title", ""),
                blocks=blocks,
                categories=cats,
                total_char_count=char_count,
                line_count=int(s.get("line_count", 0)),
                has_visual=has_visual,
                visual_type=visual_type,
                alignment=s.get("alignment"),
                text_sparse=text_sparse,
                image_only=bool(s.get("image_only", text_sparse and has_visual)),
            ))
        return cls(
            file_name=d["file_name"],
            total_slides=d["total_slides"],
            slides=slides,
        )


# ---------------------------------------------------------------------------
# F-02 : 발표 맥락
# ---------------------------------------------------------------------------

@dataclass
class Context:
    """F-02 산출물. F-06의 중요도 판단에 가중치로 들어간다."""
    situation: str = ""
    audience: str = ""
    duration_min: int | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.situation or self.audience)

    def to_prompt_block(self) -> str:
        if self.is_empty:
            return "발표 상황: (입력 없음 — 범용 발표로 간주)"
        lines = []
        if self.situation:
            lines.append(f"발표 상황: {self.situation}")
        if self.audience:
            lines.append(f"청중: {self.audience}")
        if self.duration_min:
            lines.append(f"발표 시간: 약 {self.duration_min}분")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Context":
        return cls(
            situation=d.get("situation", ""),
            audience=d.get("audience", ""),
            duration_min=d.get("duration_min"),
        )


# ---------------------------------------------------------------------------
# F-04 : 슬라이드 전환 기록  (브라우저 SDK가 생성)
# ---------------------------------------------------------------------------

@dataclass
class SlideMark:
    """'몇 초에 몇 번 슬라이드를 보고 있었다' 한 구간."""
    slide_no: int
    start_sec: float
    end_sec: float
    visit: int = 1

    @property
    def duration(self) -> float:
        return max(0.0, self.end_sec - self.start_sec)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SlideMark":
        return cls(
            slide_no=d["slide_no"],
            start_sec=float(d["start_sec"]),
            end_sec=float(d["end_sec"]),
            visit=d.get("visit", 1),
        )


# ---------------------------------------------------------------------------
# F-05 : STT 결과
# ---------------------------------------------------------------------------

@dataclass
class Word:
    text: str
    start_sec: float
    end_sec: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SlideSpeech:
    slide_no: int
    visit: int
    start_sec: float
    end_sec: float
    text: str
    words: list[Word] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "slide_no": self.slide_no,
            "visit": self.visit,
            "start_sec": self.start_sec,
            "end_sec": self.end_sec,
            "text": self.text,
            "words": [w.to_dict() for w in self.words],
        }


@dataclass
class Transcript:
    """F-05의 산출물."""
    full_text: str
    words: list[Word] = field(default_factory=list)
    by_slide: list[SlideSpeech] = field(default_factory=list)
    provider: str = ""
    duration_sec: float = 0.0

    def to_dict(self) -> dict:
        return {
            "full_text": self.full_text,
            "words": [w.to_dict() for w in self.words],
            "by_slide": [s.to_dict() for s in self.by_slide],
            "provider": self.provider,
            "duration_sec": self.duration_sec,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        return cls(
            full_text=d.get("full_text", ""),
            words=[Word(**w) for w in d.get("words", [])],
            by_slide=[
                SlideSpeech(
                    slide_no=s["slide_no"],
                    visit=s.get("visit", 1),
                    start_sec=float(s["start_sec"]),
                    end_sec=float(s["end_sec"]),
                    text=s.get("text", ""),
                    words=[Word(**w) for w in s.get("words", [])],
                )
                for s in d.get("by_slide", [])
            ],
            provider=d.get("provider", ""),
            duration_sec=float(d.get("duration_sec", 0.0)),
        )


# ---------------------------------------------------------------------------
# F-06 : 개념 추출 결과 (1차 전처리)
# ---------------------------------------------------------------------------
# 주의: 여기서는 개념 간 부모-자식 관계를 만들지 않는다.
#      위계는 F-07(트리 생성)의 책임이다.

@dataclass
class SlideConcepts:
    slide_no: int
    title: str
    topic: str
    keywords: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    raw_text: str = ""
    importance: str = "core"  # core | support — 맥락 가중치 반영

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConceptDoc:
    """F-06의 산출물. F-07 트리 생성의 입력이 된다."""
    file_name: str
    total_slides: int
    slides: list[SlideConcepts] = field(default_factory=list)
    model: str = ""

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "total_slides": self.total_slides,
            "model": self.model,
            "slides": [s.to_dict() for s in self.slides],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConceptDoc":
        slides = []
        for s in d.get("slides", []):
            slides.append(SlideConcepts(
                slide_no=s["slide_no"],
                title=s.get("title", ""),
                topic=s.get("topic", ""),
                keywords=list(s.get("keywords", [])),
                concepts=list(s.get("concepts", [])),
                raw_text=s.get("raw_text", ""),
                importance=s.get("importance", "core"),
            ))
        return cls(
            file_name=d["file_name"],
            total_slides=d["total_slides"],
            model=d.get("model", ""),
            slides=slides,
        )


# ---------------------------------------------------------------------------
# F-07 : 개념 트리 (발표 전체 기준 위계 + 구획)
# ---------------------------------------------------------------------------
# F-06 은 한 장 안을 보고, F-07 은 장들이 발표 전체에서 어디에 앉는지를 본다.
# 이해 판정·confidence·근거 발화는 넣지 않는다. 그건 F-11 이 id 로 붙인다.

#: sections[].slide_role 허용값. 이 밖의 값은 SLIDE_ROLE_FALLBACK 으로 떨어진다.
SLIDE_ROLES = ("cover", "intro", "body", "conclusion", "closing")
SLIDE_ROLE_FALLBACK = "body"


@dataclass
class ConceptNode:
    """트리의 개념 하나. 중첩하지 않고 parent_id 로 평평하게 잇는다."""
    id: str
    label: str
    depth: int = 1                 # 루트=1. parent_id 체인에서 다시 계산한다
    parent_id: str | None = None
    slide_nos: list[int] = field(default_factory=list)  # 조인 키. 여러 장 가능
    summary: str = ""
    importance: str = "core"       # core | support
    weight: float = 0.0            # 0.0~1.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "depth": self.depth,
            "parent_id": self.parent_id,
            "slide_nos": list(self.slide_nos),
            "summary": self.summary,
            "importance": self.importance,
            "weight": self.weight,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConceptNode":
        return cls(
            id=str(d["id"]),
            label=d.get("label", ""),
            depth=int(d.get("depth", 1)),
            parent_id=d.get("parent_id"),
            slide_nos=[int(n) for n in d.get("slide_nos", [])],
            summary=d.get("summary", ""),
            importance=d.get("importance", "core"),
            weight=float(d.get("weight", 0.0)),
        )


@dataclass
class Section:
    """발표 구획 하나. slide_role 은 이 구획이 전체에서 하는 역할."""
    name: str
    slide_role: str = SLIDE_ROLE_FALLBACK
    slide_nos: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "slide_role": self.slide_role,
            "slide_nos": list(self.slide_nos),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Section":
        role = d.get("slide_role", SLIDE_ROLE_FALLBACK)
        return cls(
            name=d.get("name", ""),
            slide_role=role if role in SLIDE_ROLES else SLIDE_ROLE_FALLBACK,
            slide_nos=[int(n) for n in d.get("slide_nos", [])],
        )


@dataclass
class ConceptTree:
    """
    F-07 의 산출물. F-08~10(질문 코칭)·F-11(설명 판정)의 입력이 된다.

    불변식은 f07_tree.build_tree() 가 보장한다:
    id 유일 · parent_id 는 존재하는 id 나 None · 순환 없음 · depth = 체인 길이.
    """
    file_name: str
    total_slides: int
    nodes: list[ConceptNode] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    model: str = ""

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "total_slides": self.total_slides,
            "model": self.model,
            "nodes": [n.to_dict() for n in self.nodes],
            "sections": [s.to_dict() for s in self.sections],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConceptTree":
        return cls(
            file_name=d["file_name"],
            total_slides=int(d["total_slides"]),
            nodes=[ConceptNode.from_dict(n) for n in d.get("nodes", [])],
            sections=[Section.from_dict(s) for s in d.get("sections", [])],
            model=d.get("model", ""),
        )

    # --- 조회 헬퍼 (질문 코칭·판정이 id 로 붙일 때 쓴다) -------------------

    def node(self, node_id: str) -> ConceptNode | None:
        """id 로 노드 하나."""
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def children_of(self, node_id: str | None) -> list[ConceptNode]:
        """직속 자식들. None 을 주면 루트 목록."""
        return [n for n in self.nodes if n.parent_id == node_id]

    @property
    def roots(self) -> list[ConceptNode]:
        return self.children_of(None)

    def path_of(self, node_id: str) -> list[ConceptNode]:
        """
        루트에서 해당 노드까지의 경로.

        Q&A 화면의 '개념 경로' 표시용. 없는 id 면 빈 리스트.
        """
        by_id = {n.id: n for n in self.nodes}
        cur = by_id.get(node_id)
        chain: list[ConceptNode] = []
        seen: set[str] = set()
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            chain.append(cur)
            cur = by_id.get(cur.parent_id) if cur.parent_id else None
        return list(reversed(chain))

    def nodes_for_slide(self, slide_no: int) -> list[ConceptNode]:
        """이 장을 근거로 삼는 개념들."""
        return [n for n in self.nodes if slide_no in n.slide_nos]

    def section_of(self, slide_no: int) -> Section | None:
        """이 장이 속한 구획."""
        for s in self.sections:
            if slide_no in s.slide_nos:
                return s
        return None


# ---------------------------------------------------------------------------
# 예외
# ---------------------------------------------------------------------------

class ChuckchuckError(Exception):
    """모듈 공통 예외. 프론트는 이것만 잡으면 된다."""


class ParseError(ChuckchuckError):
    """F-01 파싱 실패."""


class STTError(ChuckchuckError):
    """F-05 음성 인식 실패."""


class WordTimestampUnsupported(STTError):
    """STT 제공자가 단어별 시각을 주지 않을 때."""


class ConceptError(ChuckchuckError):
    """F-06 개념 추출 실패."""


class TreeError(ChuckchuckError):
    """F-07 개념 트리 생성 실패."""


def ensure_dict_list(items: list[Any] | list[dict], factory):
    """dict 리스트면 dataclass로 변환. 프론트 JSON 직결용."""
    if not items:
        return []
    if isinstance(items[0], dict):
        return [factory(x) for x in items]
    return list(items)
