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
# F-07 : 개념 그래프 (발표 전체 기준 우선순위 + 연결선 + 구획)
# ---------------------------------------------------------------------------
# F-06 은 한 장 안을 보고, F-07 은 장들이 발표 전체에서 어디에 앉는지를 본다.
#
# 트리가 아니라 그래프인 이유: 개념은 부모가 하나라는 보장이 없다.
# 'CAFP 분석'은 '링글 AI 서비스'와 '데이터 자산' 양쪽에 걸린다.
# parent 간선만 따라가면 트리 뷰가 나오고, relates 간선이 나머지 연결을 담는다.
#
# 발화 축(speech_weight)과 정합 판정(누락·모순)은 넣지 않는다.
# F-07 은 Transcript 를 받지 않는다. 그건 node.id 로 조인하는 뒤 단계 책임이다.

#: sections[].slide_role 허용값. 이 밖의 값은 SLIDE_ROLE_FALLBACK 으로 떨어진다.
SLIDE_ROLES = ("cover", "intro", "body", "conclusion", "closing")
SLIDE_ROLE_FALLBACK = "body"

#: edges[].kind 허용값. parent 는 위계, relates 는 그 밖의 논리 연결.
EDGE_KINDS = ("parent", "relates")
EDGE_KIND_FALLBACK = "relates"

#: nodes[].weight_basis.position 허용값. 발표 안에서 개념이 등장하는 위치.
NODE_POSITIONS = ("early", "middle", "late")


@dataclass
class WeightBasis:
    """
    weight 를 그렇게 준 근거. 산점도에서 '왜 이 값인지' 를 설명하려면 필요하다.

    slide_doc 없이 build 하면 char_share·has_visual 은 0/False 로 남는다.
    """
    slide_count: int = 0        # 이 개념이 걸친 장 수
    char_share: float = 0.0     # 그 장들의 본문 글자 수 / 전체 글자 수
    has_visual: bool = False    # 근거 장에 도식·표·차트가 있나
    position: str = "middle"    # early | middle | late
    mention_count: int = 0      # 문서 전체 개념·키워드에서 이 개념이 언급된 횟수
    title_hit: bool = False     # 근거 장 제목에 이 개념이 등장하나

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WeightBasis":
        pos = d.get("position", "middle")
        return cls(
            slide_count=int(d.get("slide_count", 0)),
            char_share=float(d.get("char_share", 0.0)),
            has_visual=bool(d.get("has_visual", False)),
            position=pos if pos in NODE_POSITIONS else "middle",
            mention_count=int(d.get("mention_count", 0)),
            title_hit=bool(d.get("title_hit", False)),
        )


@dataclass
class ConceptEdge:
    """개념 사이의 연결 하나. from 은 파이썬 예약어라 필드명은 from_id 다."""
    from_id: str
    to_id: str
    kind: str = "parent"        # parent | relates

    def to_dict(self) -> dict:
        return {"from": self.from_id, "to": self.to_id, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: dict) -> "ConceptEdge":
        kind = d.get("kind", "parent")
        return cls(
            from_id=str(d["from"]),
            to_id=str(d["to"]),
            kind=kind if kind in EDGE_KINDS else EDGE_KIND_FALLBACK,
        )


@dataclass
class ConceptNode:
    """
    그래프의 개념 하나. 중첩하지 않고 평평하게 둔다.

    parent_id / depth 는 parent 간선에서 **파생된 편의 필드**다.
    진실은 ConceptGraph.edges 이고, 화면이 트리로 그릴 때 쓰라고 실어 준다.
    """
    id: str
    label: str
    slide_nos: list[int] = field(default_factory=list)  # 조인 키. 여러 장 가능
    summary: str = ""
    importance: str = "core"       # core | support
    weight: float = 0.0            # 0.0~1.0. 그래프 안에서 상대적 (최상위 = 1.0)
    weight_basis: WeightBasis = field(default_factory=WeightBasis)
    parent_id: str | None = None   # 파생: 첫 parent 간선
    depth: int = 1                 # 파생: 루트=1

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "slide_nos": list(self.slide_nos),
            "summary": self.summary,
            "importance": self.importance,
            "weight": self.weight,
            "weight_basis": self.weight_basis.to_dict(),
            "parent_id": self.parent_id,
            "depth": self.depth,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConceptNode":
        return cls(
            id=str(d["id"]),
            label=d.get("label", ""),
            slide_nos=[int(n) for n in d.get("slide_nos", [])],
            summary=d.get("summary", ""),
            importance=d.get("importance", "core"),
            weight=float(d.get("weight", 0.0)),
            weight_basis=WeightBasis.from_dict(d.get("weight_basis") or {}),
            parent_id=d.get("parent_id"),
            depth=int(d.get("depth", 1)),
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
class ConceptGraph:
    """
    F-07 의 산출물. F-08~10(질문 코칭)·F-11(정합 판정)의 입력이 된다.

    edges 가 진실이고, node.parent_id / node.depth 는 parent 간선에서 파생된 편의 필드다.
    불변식은 f07_graph.build_graph() 가 보장한다:
    id 유일 · 간선 양끝이 존재하는 id · 자기 간선 없음 · parent 순환 없음 ·
    노드당 parent 간선 최대 1개 · depth = 체인 길이.
    """
    file_name: str
    total_slides: int
    nodes: list[ConceptNode] = field(default_factory=list)
    edges: list[ConceptEdge] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    model: str = ""

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "total_slides": self.total_slides,
            "model": self.model,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "sections": [s.to_dict() for s in self.sections],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConceptGraph":
        return cls(
            file_name=d["file_name"],
            total_slides=int(d["total_slides"]),
            nodes=[ConceptNode.from_dict(n) for n in d.get("nodes", [])],
            edges=[ConceptEdge.from_dict(e) for e in d.get("edges", [])],
            sections=[Section.from_dict(s) for s in d.get("sections", [])],
            model=d.get("model", ""),
        )

    # --- 노드 조회 (질문 코칭·판정이 id 로 붙일 때 쓴다) -------------------

    def node(self, node_id: str) -> ConceptNode | None:
        """id 로 노드 하나."""
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def nodes_for_slide(self, slide_no: int) -> list[ConceptNode]:
        """이 장을 근거로 삼는 개념들."""
        return [n for n in self.nodes if slide_no in n.slide_nos]

    def section_of(self, slide_no: int) -> Section | None:
        """이 장이 속한 구획."""
        for s in self.sections:
            if slide_no in s.slide_nos:
                return s
        return None

    @property
    def by_weight(self) -> list[ConceptNode]:
        """중요도 내림차순. 슬라이드 축 우선순위 목록이 그대로 나온다."""
        return sorted(self.nodes, key=lambda n: -n.weight)

    # --- 트리 뷰 (parent 간선만 따라간 결과) ------------------------------

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

    # --- 그래프 뷰 (연결선 전체) -----------------------------------------

    @property
    def parent_edges(self) -> list[ConceptEdge]:
        return [e for e in self.edges if e.kind == "parent"]

    @property
    def relates_edges(self) -> list[ConceptEdge]:
        return [e for e in self.edges if e.kind == "relates"]

    def edges_from(self, node_id: str) -> list[ConceptEdge]:
        return [e for e in self.edges if e.from_id == node_id]

    def edges_to(self, node_id: str) -> list[ConceptEdge]:
        return [e for e in self.edges if e.to_id == node_id]

    def neighbors_of(self, node_id: str) -> list[ConceptNode]:
        """방향 무시하고 이 개념과 연결된 개념들 (중복 제거)."""
        ids: list[str] = []
        for e in self.edges:
            other = e.to_id if e.from_id == node_id else (e.from_id if e.to_id == node_id else None)
            if other and other != node_id and other not in ids:
                ids.append(other)
        return [n for n in (self.node(i) for i in ids) if n is not None]


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


class GraphError(ChuckchuckError):
    """F-07 개념 그래프 생성 실패."""


def ensure_dict_list(items: list[Any] | list[dict], factory):
    """dict 리스트면 dataclass로 변환. 프론트 JSON 직결용."""
    if not items:
        return []
    if isinstance(items[0], dict):
        return [factory(x) for x in items]
    return list(items)
