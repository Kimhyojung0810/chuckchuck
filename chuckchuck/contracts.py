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

    def text_for_slide(self, slide_no: int) -> str:
        """특정 슬라이드에서 한 말 전부 (재방문 포함). F-11 대조용."""
        parts = [s.text for s in self.by_slide if s.slide_no == slide_no and s.text.strip()]
        return " ".join(parts)

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
# F-11 : 정합 판정 (발화 축 + 4-class)
# ---------------------------------------------------------------------------
# F-07 이 만든 슬라이드 축(weight) 옆에 발화 축(speech_weight)을 세우고,
# 개념마다 발화가 자료와 정합했는지 4-class 로 판정한다. 조인 키는 node_id.
#
# 발화 그래프를 독립 추출해 비교하지 않는다 — LLM 추출 분산이 두 배가 되어
# diff 가 노이즈를 측정하게 된다. 발화 개념 추출은 문서 그래프 노드에 조건화한다.

#: items[].verdict 허용값. 이 밖의 값은 결정적 폴백으로 대체된다.
ALIGN_VERDICTS = ("aligned", "justified_skip", "missing", "contradiction")


@dataclass
class SpeechBasis:
    """
    speech_weight 를 그렇게 준 근거. F-07 WeightBasis 와 대칭이다.

    words 가 없는 Transcript(mock 등)면 first_mention_sec 은 None 으로 남는다.
    """
    speech_sec: float = 0.0            # 근거 장 발화 시간 합 (초)
    time_share: float = 0.0            # / 전체 발화 시간
    mention_count: int = 0             # 발화 전체에서 label 언급 횟수
    mentioned_slide_count: int = 0     # 근거 장 중 label 이 실제 언급된 장 수
    first_mention_sec: float | None = None  # label 이 처음 등장한 시각

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SpeechBasis":
        first = d.get("first_mention_sec")
        return cls(
            speech_sec=float(d.get("speech_sec", 0.0)),
            time_share=float(d.get("time_share", 0.0)),
            mention_count=int(d.get("mention_count", 0)),
            mentioned_slide_count=int(d.get("mentioned_slide_count", 0)),
            first_mention_sec=None if first is None else float(first),
        )


@dataclass
class AlignmentItem:
    """개념 노드 1개의 판정. node_id 로 ConceptGraph.nodes 와 조인한다."""
    node_id: str
    verdict: str = "missing"           # aligned | justified_skip | missing | contradiction
    speech_weight: float = 0.0         # 0.0~1.0. 그래프 안에서 상대적 (최상위 = 1.0)
    speech_basis: SpeechBasis = field(default_factory=SpeechBasis)
    doc_weight: float = 0.0            # 파생: 해당 노드의 F-07 weight 복사 (산점도 편의)
    evidence: str = ""                 # 판정 근거가 된 발화 인용
    note: str = ""                     # LLM 한 줄 설명

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "verdict": self.verdict,
            "speech_weight": self.speech_weight,
            "speech_basis": self.speech_basis.to_dict(),
            "doc_weight": self.doc_weight,
            "evidence": self.evidence,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AlignmentItem":
        verdict = d.get("verdict", "missing")
        return cls(
            node_id=str(d["node_id"]),
            verdict=verdict if verdict in ALIGN_VERDICTS else "missing",
            speech_weight=float(d.get("speech_weight", 0.0)),
            speech_basis=SpeechBasis.from_dict(d.get("speech_basis") or {}),
            doc_weight=float(d.get("doc_weight", 0.0)),
            evidence=d.get("evidence", ""),
            note=d.get("note", ""),
        )


@dataclass
class SpeechEdge:
    """발표자가 말로 연결한 개념 쌍. cue 가 그 연결을 보여 준 발화 인용이다."""
    from_id: str
    to_id: str
    cue: str = ""
    in_graph: bool = False             # 파생: 문서 그래프에도 있는 연결인가 (방향 무시)

    def to_dict(self) -> dict:
        return {
            "from": self.from_id,
            "to": self.to_id,
            "cue": self.cue,
            "in_graph": self.in_graph,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SpeechEdge":
        return cls(
            from_id=str(d["from"]),
            to_id=str(d["to"]),
            cue=d.get("cue", ""),
            in_graph=bool(d.get("in_graph", False)),
        )


@dataclass
class ExtraConcept:
    """발화에는 있는데 문서 그래프에 없는 개념. 보충 설명이거나 삼천포다."""
    label: str
    quote: str = ""
    slide_no: int | None = None        # 언급 시점에 보고 있던 장

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ExtraConcept":
        slide_no = d.get("slide_no")
        return cls(
            label=d.get("label", ""),
            quote=d.get("quote", ""),
            slide_no=None if slide_no is None else int(slide_no),
        )


@dataclass
class AlignmentSummary:
    """발표 전체 요약 지표. 전부 코드가 계산한다 (LLM 아님)."""
    coverage: float = 0.0                    # weight 가중 커버리지 (0~1)
    rank_correlation: float | None = None    # doc_weight vs speech_weight Spearman
    edge_coverage: float | None = None       # 문서 간선 중 발화로도 연결된 비율
    verdict_counts: dict = field(default_factory=dict)
    speech_total_sec: float = 0.0

    def to_dict(self) -> dict:
        return {
            "coverage": self.coverage,
            "rank_correlation": self.rank_correlation,
            "edge_coverage": self.edge_coverage,
            "verdict_counts": dict(self.verdict_counts),
            "speech_total_sec": self.speech_total_sec,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AlignmentSummary":
        rank = d.get("rank_correlation")
        edge = d.get("edge_coverage")
        return cls(
            coverage=float(d.get("coverage", 0.0)),
            rank_correlation=None if rank is None else float(rank),
            edge_coverage=None if edge is None else float(edge),
            verdict_counts=dict(d.get("verdict_counts") or {}),
            speech_total_sec=float(d.get("speech_total_sec", 0.0)),
        )


@dataclass
class AlignmentDoc:
    """
    F-11 의 산출물. 산점도(doc_weight × speech_weight)와 diff 뷰가 여기서 나온다.

    불변식은 f11_align.align_speech() 가 보장한다:
    그래프의 모든 노드에 item 정확히 1개 · verdict 는 enum 안 ·
    speech_edges 양끝이 존재하는 id · extra_concepts 는 그래프에 없는 개념만.
    """
    file_name: str
    total_slides: int
    items: list[AlignmentItem] = field(default_factory=list)
    speech_edges: list[SpeechEdge] = field(default_factory=list)
    extra_concepts: list[ExtraConcept] = field(default_factory=list)
    summary: AlignmentSummary = field(default_factory=AlignmentSummary)
    model: str = ""

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "total_slides": self.total_slides,
            "model": self.model,
            "items": [i.to_dict() for i in self.items],
            "speech_edges": [e.to_dict() for e in self.speech_edges],
            "extra_concepts": [c.to_dict() for c in self.extra_concepts],
            "summary": self.summary.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AlignmentDoc":
        return cls(
            file_name=d["file_name"],
            total_slides=int(d["total_slides"]),
            items=[AlignmentItem.from_dict(i) for i in d.get("items", [])],
            speech_edges=[SpeechEdge.from_dict(e) for e in d.get("speech_edges", [])],
            extra_concepts=[ExtraConcept.from_dict(c) for c in d.get("extra_concepts", [])],
            summary=AlignmentSummary.from_dict(d.get("summary") or {}),
            model=d.get("model", ""),
        )

    # --- 조회 (diff 뷰·산점도가 쓴다) -------------------------------------

    def item(self, node_id: str) -> AlignmentItem | None:
        """node_id 로 판정 하나."""
        for i in self.items:
            if i.node_id == node_id:
                return i
        return None

    def by_verdict(self, verdict: str) -> list[AlignmentItem]:
        """특정 판정의 개념들. diff 뷰의 한 칸이 된다."""
        return [i for i in self.items if i.verdict == verdict]

    @property
    def scatter_points(self) -> list[tuple[str, float, float]]:
        """(node_id, doc_weight, speech_weight). 산점도에 바로 꽂는다."""
        return [(i.node_id, i.doc_weight, i.speech_weight) for i in self.items]


# ---------------------------------------------------------------------------
# F-11 파생 : 흐름 비교 (FlowDiff)
# ---------------------------------------------------------------------------
# 자료 흐름(슬라이드 순)과 발표 흐름(첫 언급 순)을 같은 node_id 축에서 비교한다.
# 전부 이미 계산된 결정적 신호(first_mention_sec·mention_count·speech_edges)의
# 파생이므로 LLM 을 다시 부르지 않는다. 발화 그래프 독립 추출은 하지 않는다.

#: issues[].kind 허용값. missing_link 잇는 멘트 없음 · order_jump 근거 점프 ·
#: good_link 잘된 연결(칭찬).
FLOW_ISSUE_KINDS = ("missing_link", "order_jump", "good_link")


@dataclass
class FlowStep:
    """개념 노드 1개의 흐름 좌표. doc_order 는 자료 축, speech_order 는 발화 축."""
    node_id: str
    doc_order: int                          # 1..n — 근거 슬라이드 순
    speech_order: int | None = None         # 1..k — 첫 언급 시각 순. 못 잡으면 None
    first_mention_sec: float | None = None  # SpeechBasis 에서 복사 (화면 편의)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FlowStep":
        speech = d.get("speech_order")
        first = d.get("first_mention_sec")
        return cls(
            node_id=str(d["node_id"]),
            doc_order=int(d["doc_order"]),
            speech_order=None if speech is None else int(speech),
            first_mention_sec=None if first is None else float(first),
        )


@dataclass
class FlowIssue:
    """흐름 차원 판정 하나. good_link 는 칭찬이라 cue(발화 인용)가 반드시 있다."""
    kind: str                               # missing_link | order_jump | good_link
    node_ids: list[str] = field(default_factory=list)
    cue: str = ""                           # 근거 발화 인용 (good_link 필수)
    slide_nos: list[int] = field(default_factory=list)
    note: str = ""                          # 화면에 그대로 내보낼 한 줄 설명

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "node_ids": list(self.node_ids),
            "cue": self.cue,
            "slide_nos": list(self.slide_nos),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FlowIssue":
        return cls(
            kind=d.get("kind", ""),
            node_ids=[str(x) for x in d.get("node_ids", [])],
            cue=d.get("cue", ""),
            slide_nos=[int(n) for n in d.get("slide_nos", [])],
            note=d.get("note", ""),
        )


@dataclass
class FlowDiff:
    """
    F-11 파생 산출물. 자료 흐름 vs 발표 흐름의 차이와 플로우 피드백.

    불변식은 f11_flow.build_flow_diff() 가 보장한다:
    steps 는 그래프의 모든 노드 정확히 1개씩 · speech_order 는 1..k 연속 ·
    issues 의 node_id 는 전부 실존 · good_link 는 cue 필수 · 순수 함수(결정적).
    """
    file_name: str
    steps: list[FlowStep] = field(default_factory=list)
    issues: list[FlowIssue] = field(default_factory=list)
    order_tau: float | None = None          # 문서 순서 vs 발화 순서 Kendall tau
    spoken_node_count: int = 0              # 발화에서 언급된 노드 수
    ghost_node_ids: list[str] = field(default_factory=list)  # 첫 언급을 못 잡은 노드
    extra_labels: list[str] = field(default_factory=list)    # 발화 전용 개념 label

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "steps": [s.to_dict() for s in self.steps],
            "issues": [i.to_dict() for i in self.issues],
            "order_tau": self.order_tau,
            "spoken_node_count": self.spoken_node_count,
            "ghost_node_ids": list(self.ghost_node_ids),
            "extra_labels": list(self.extra_labels),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FlowDiff":
        tau = d.get("order_tau")
        return cls(
            file_name=d["file_name"],
            steps=[FlowStep.from_dict(s) for s in d.get("steps", [])],
            issues=[FlowIssue.from_dict(i) for i in d.get("issues", [])],
            order_tau=None if tau is None else float(tau),
            spoken_node_count=int(d.get("spoken_node_count", 0)),
            ghost_node_ids=[str(x) for x in d.get("ghost_node_ids", [])],
            extra_labels=[str(x) for x in d.get("extra_labels", [])],
        )

    def issues_of(self, kind: str) -> list[FlowIssue]:
        """특정 종류의 판정들. 리포트 '논리 흐름' 탭의 한 묶음이 된다."""
        return [i for i in self.issues if i.kind == kind]


# ---------------------------------------------------------------------------
# F-08 · F-09 : 질문 코칭 (예상 질문 + 답변 판정)
# ---------------------------------------------------------------------------
# 발표가 끝난 뒤 "이거 물어보면 답할 수 있나" 를 연습시키는 단계다.
# 입력은 ConceptGraph(+ 선택 AlignmentDoc·FlowDiff) — 이미 계산된 결정적 신호만 쓴다.
# 리포트가 "누락" 이라고 말한 개념과 질문이 어긋나면 안 되므로,
# **어떤 개념을 물을지는 코드가 정하고 LLM 은 문장만 쓴다** (F-11 과 같은 철학).
#
#   F-08  ConceptGraph(+AlignmentDoc·FlowDiff) → QaTriage    (질문 가치 심사, 세션 1회)
#   F-08  QaTriage + track                     → QuestionDoc (트랙별 질문 세트)
#   F-09  Question + 답변(+history)            → QaJudgement (4-class 판정)
#
# LLM 을 두 번 부르는 이유: 개념의 **중요도**는 F-07 weight·F-11 verdict 로 이미
# 결정적으로 알지만, "이게 심사위원한테 실제로 찔릴 질문인가 · 함정을 팔 수 있나"
# 는 코드가 모른다. 그 판단만 1차(triage)에 맡기고, 2차는 문장 생성만 맡는다.
# triage 는 트랙과 무관하므로 세션에 캐시한다 — 1/5/10분을 바꿔도 순위가 안 흔들린다.

#: 질문 세트 트랙. 프론트 QA_MODES 키와 같은 문자열이다 (app.js).
QA_TRACKS = ("1", "5", "10")
QA_TRACK_FALLBACK = "10"

#: 트랙 → 질문 개수 상한. 1분=핵심만, 5분=핵심+놓친 것, 10분=정복.
QA_TRACK_LIMITS = {"1": 1, "5": 3, "10": 7}

#: 트랙 → 함정 질문(자료와 어긋난 주장으로 찔러보기) 허용 개수.
#: 1분 트랙은 방어 연습할 시간이 없어 함정을 넣지 않는다.
QA_TRACK_TRAPS = {"1": 0, "5": 1, "10": 3}

#: severity — 1 치명 · 2 보통 · 3 가벼움. 프론트 SEVERITY_WORD 와 같은 값이다.
QA_SEVERITIES = (1, 2, 3)
QA_SEVERITY_FALLBACK = 2

#: 이 질문이 뽑힌 **결정적 근거**. 리포트가 "왜 이걸 묻나" 를 설명할 때 쓴다.
#: 우선순위도 이 순서다 (모순 > 누락 > 흐름 결손 > 자료 비중).
#: 질문 후보가 된 결정적 근거. **순서가 곧 우선순위다** (_SOURCE_RANK 가 이 순서를 쓴다).
#: 확인된 결손이 앞이고 "그냥 중요하다" 는 맨 뒤다 —
#: 모순(자료와 어긋남) > 누락(아예 안 다룸) > 얕음(중요한데 설명 부족)
#: > 흐름 결손(연결을 안 지음) > 즉흥 개념(발화에만 있음) > 자료 비중 > 정당생략.
#: extra 가 core_weight 보다 앞인 것은 의도된 것이다 — 발표자가 **실제로 입 밖에 낸**
#: 개념이라 되물을 근거가 확실하고, core_weight 는 크다는 이유뿐이기 때문이다.
#: justified_skip 이 core_weight 보다도 뒤인 것도 의도된 것이다 — 리포트가
#: "생략이 합리적" 이라 말한 개념을 자료 weight 가 크다는 이유로 앞세우면
#: 두 화면이 어긋난다. 버리지는 않는다 — 트랙 상한에 여유가 있으면 여전히 물어본다.
QA_SOURCES = (
    "contradiction", "missing", "under_spoken", "weak_flow", "extra",
    "core_weight", "justified_skip",
)
QA_SOURCE_FALLBACK = "core_weight"

#: doc_weight − speech_weight 가 이만큼 벌어지면 '중요도 대비 설명 부족'(under_spoken).
#: SCHEMA §7-F 가 같은 격차를 쓰고 있어 값을 맞춘다 — 리포트와 질문이 같은 선을 봐야
#: 사용자가 두 화면을 믿을 수 있다.
QA_UNDER_SPOKEN_GAP = 0.4

#: extra_concepts 에서 질문 후보로 올릴 최대 개수. 즉흥 발화가 많은 발표에서
#: 자료 기반 질문이 통째로 밀려나면 안 된다.
QA_EXTRA_MAX = 3

#: 답변 판정 4-class. 프론트 LIVE_VERDICT 키와 동일하다.
#: (`skipped` 는 질문을 넘겼을 때 프론트가 로컬로 붙이는 값이라 여기 없다.)
QA_VERDICTS = ("good", "partial", "wrong", "unknown")
QA_VERDICT_FALLBACK = "unknown"

#: verdict 만 오고 score 가 없을 때 채워 넣는 기본 점수 (0~100).
QA_VERDICT_SCORES = {"good": 85, "partial": 55, "wrong": 20, "unknown": 0}

#: 이 점수 이상이면 '정답 계열' 로 보고 되묻기를 멈춘다.
#: 실전 코칭은 턴 상한이 없으므로 **이 임계 하나가 대화의 유일한 출구다.**
#: 너무 높으면 대화가 실제로 안 끝나고, 너무 낮으면 얕은 답이 통과한다.
#: partial 기본값 55 와 good 기본값 85 사이 — "방향도 맞고 근거도 어느 정도 댔다" 구간.
QA_PASS_SCORE = 70


def qa_passed(verdict: str, score: int) -> bool:
    """
    이 답변을 정답 계열로 인정할지. **판정 규칙은 여기 한 곳에만 둔다.**

    프론트가 임계를 따로 계산하면 서버와 어긋나는 순간 화면이 모순된다 —
    '설득 완료' 칩을 띄워 놓고 되묻는 식으로. 그래서 QaJudgement.to_dict() 가
    이 결과를 `passed` 로 실어 보내고, 프론트는 그 불리언만 읽는다.

    verdict 가 good 이면 점수와 무관하게 통과다. 등급과 점수가 어긋날 때는
    등급을 믿는다 — 사용자에게 보이는 것이 등급이기 때문이다.
    """
    return verdict == "good" or score >= QA_PASS_SCORE


#: 대사 길이 상한. 화면 말풍선이 감당하는 길이다.
QA_TEXT_MAX = 200

#: 막힘 코칭 단계. verdict 를 4-class 로 유지하기 위해 **별도 축**으로 둔다 —
#: 5번째 verdict 를 만들면 qa_passed·점수표·프론트 배지 맵이 전부 흔들린다.
#:   ""        평시 판정
#:   narrow    1차 포기 — 답을 주지 않고 더 쉬운 되물음으로 한 발 끌어준다
#:   explain   2차 포기 — 해설하고 이 질문을 닫는다
QA_COACH_STAGES = ("", "narrow", "explain")

#: 해설 길이 상한. QA_TEXT_MAX 보다 길다 — 해설은 말풍선 한 마디가 아니라
#: "이렇게 답했어야 한다" 를 근거까지 붙여 설명하는 문단이기 때문이다.
QA_EXPLAIN_MAX = 500


@dataclass
class TriageMark:
    """
    개념 하나의 질문 가치 심사 결과 (F-08 1차).

    node_id·source·rank 는 **코드가 결정적으로** 채우고,
    severity·trap·angle 만 LLM 이 손댄다. 후보 밖 node_id 는 어댑터가 버린다.
    """
    node_id: str
    severity: int = QA_SEVERITY_FALLBACK   # 1 치명 | 2 보통 | 3 가벼움
    trap: bool = False                     # 함정 질문을 팔 수 있는 개념인가
    angle: str = ""                        # 질문 각도 한 줄 (2차 프롬프트 입력)
    source: str = QA_SOURCE_FALLBACK       # 파생: 뽑힌 결정적 근거
    rank: int = 0                          # 파생: 결정적 후보 순위 (1부터)
    doc_weight: float = 0.0                # 파생: F-07 weight 복사

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TriageMark":
        try:
            severity = int(d.get("severity", QA_SEVERITY_FALLBACK))
        except (TypeError, ValueError):
            severity = QA_SEVERITY_FALLBACK
        source = d.get("source", QA_SOURCE_FALLBACK)
        return cls(
            node_id=str(d["node_id"]),
            severity=severity if severity in QA_SEVERITIES else QA_SEVERITY_FALLBACK,
            trap=bool(d.get("trap", False)),
            angle=str(d.get("angle", "") or ""),
            source=source if source in QA_SOURCES else QA_SOURCE_FALLBACK,
            rank=int(d.get("rank", 0)),
            doc_weight=float(d.get("doc_weight", 0.0)),
        )


@dataclass
class QaTriage:
    """
    F-08 1차 산출물. 트랙과 무관해서 **세션에 한 번만** 만들고 재사용한다.

    marks 는 결정적 우선순위(rank) 오름차순이다.
    """
    file_name: str
    total_slides: int = 0
    marks: list[TriageMark] = field(default_factory=list)
    model: str = ""

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "total_slides": self.total_slides,
            "model": self.model,
            "marks": [m.to_dict() for m in self.marks],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QaTriage":
        return cls(
            file_name=d["file_name"],
            total_slides=int(d.get("total_slides", 0)),
            marks=[TriageMark.from_dict(m) for m in d.get("marks", [])],
            model=d.get("model", ""),
        )

    def mark(self, node_id: str) -> TriageMark | None:
        for m in self.marks:
            if m.node_id == node_id:
                return m
        return None


@dataclass
class Question:
    """
    예상 질문 하나. 필드 이름은 프론트가 이미 소비하는 키와 같다 (app.js 실전 QA).

    node_id 로 ConceptGraph·AlignmentDoc 과 조인해서 "이 질문이 리포트의 어느
    개념인지" 를 되짚는다.
    """
    id: str                                # 질문 안정 키 (프론트 results 조인)
    node_id: str                           # 조인 키 — ConceptGraph.nodes[].id
    label: str                             # 개념 이름 (화면 칩)
    question: str                          # 질문 문장
    why: str = ""                          # 왜 이걸 묻나 (근거 한 줄)
    hint: str = ""                         # 막혔을 때 보여 줄 힌트
    severity: int = QA_SEVERITY_FALLBACK   # 1 치명 | 2 보통 | 3 가벼움
    trap: bool = False                     # 자료와 어긋난 주장으로 찔러보는 질문인가
    source: str = QA_SOURCE_FALLBACK       # 파생: 뽑힌 결정적 근거
    slide_nos: list[int] = field(default_factory=list)  # 근거 장
    doc_weight: float = 0.0                # 파생: F-07 weight 복사
    #: 이 질문에 기대하는 답의 골자. 되묻기가 끝날 때 "그래서 뭐라고 답했어야 하나" 를
    #: 보여 주는 재료다. 대화가 끝났는데 답을 모른 채면 코칭이 실패한 것이므로 비워 두지 않는다.
    answer_gist: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "node_id": self.node_id,
            "label": self.label,
            "question": self.question,
            "why": self.why,
            "hint": self.hint,
            "severity": self.severity,
            "trap": self.trap,
            "source": self.source,
            "slide_nos": list(self.slide_nos),
            "doc_weight": self.doc_weight,
            "answer_gist": self.answer_gist,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Question":
        try:
            severity = int(d.get("severity", QA_SEVERITY_FALLBACK))
        except (TypeError, ValueError):
            severity = QA_SEVERITY_FALLBACK
        source = d.get("source", QA_SOURCE_FALLBACK)
        return cls(
            id=str(d["id"]),
            node_id=str(d.get("node_id", "") or ""),
            label=str(d.get("label", "") or ""),
            question=str(d.get("question", "") or ""),
            why=str(d.get("why", "") or ""),
            hint=str(d.get("hint", "") or ""),
            severity=severity if severity in QA_SEVERITIES else QA_SEVERITY_FALLBACK,
            trap=bool(d.get("trap", False)),
            source=source if source in QA_SOURCES else QA_SOURCE_FALLBACK,
            slide_nos=[int(n) for n in d.get("slide_nos", [])],
            doc_weight=float(d.get("doc_weight", 0.0)),
            answer_gist=str(d.get("answer_gist", "") or ""),
        )


@dataclass
class QuestionDoc:
    """
    F-08 의 산출물. 프론트 실전 QA 루프가 이 questions[] 를 그대로 재생한다.

    불변식은 f08_questions.build_questions() 가 보장한다:
    질문 id 유일 · 개념(node_id) 중복 없음 · 트랙 상한 준수 ·
    severity 는 enum 안 · 1분 트랙에는 함정 없음 · 같은 triage 면 결과가 같다.
    """
    file_name: str
    total_slides: int = 0
    track: str = QA_TRACK_FALLBACK
    questions: list[Question] = field(default_factory=list)
    #: 후보였지만 이번 트랙 상한에서 밀린 개념. "더 길게 하면 이것도 물어요" 안내용.
    deferred_node_ids: list[str] = field(default_factory=list)
    model: str = ""

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "total_slides": self.total_slides,
            "track": self.track,
            "questions": [q.to_dict() for q in self.questions],
            "deferred_node_ids": list(self.deferred_node_ids),
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QuestionDoc":
        track = str(d.get("track", QA_TRACK_FALLBACK))
        return cls(
            file_name=d["file_name"],
            total_slides=int(d.get("total_slides", 0)),
            track=track if track in QA_TRACKS else QA_TRACK_FALLBACK,
            questions=[Question.from_dict(q) for q in d.get("questions", [])],
            deferred_node_ids=[str(x) for x in d.get("deferred_node_ids", [])],
            model=d.get("model", ""),
        )

    def question(self, question_id: str) -> Question | None:
        """id 로 질문 하나. 판정(F-09)이 question_id 로 되찾을 때 쓴다."""
        for q in self.questions:
            if q.id == question_id:
                return q
        return None

    @property
    def node_ids(self) -> list[str]:
        return [q.node_id for q in self.questions]


@dataclass
class QaTurn:
    """
    주고받은 질문·답변 한 턴 (F-09 history).

    프론트는 한글 키(`질문`·`답변`·`판정`)로 보낸다 — 이미 굳은 계약이라
    from_dict 가 한글·영문 양쪽을 받아 준다.

    `question_id` 는 턴을 질문에 잇는 조인 키다. 문면(`question`)으로는 이을 수
    없다 — 프론트가 2턴째부터 원래 질문이 아니라 **직전 후속 질문**을 그 턴의
    question 으로 적기 때문이다(app.js submitLiveAnswer). 문면으로 세면 되물은
    턴이 다른 질문으로 읽혀 막힘 코칭이 explain 단계로 못 올라간다.
    옛 클라이언트는 이 키 없이 보내므로, 빈 문자열이면 문면 비교로 폴백한다.
    """
    question: str = ""
    answer: str = ""
    verdict: str = QA_VERDICT_FALLBACK
    question_id: str = ""

    def to_dict(self) -> dict:
        return {
            "질문": self.question,
            "답변": self.answer,
            "판정": self.verdict,
            "question_id": self.question_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QaTurn":
        verdict = str(d.get("판정", d.get("verdict", QA_VERDICT_FALLBACK)) or "")
        return cls(
            question=str(d.get("질문", d.get("question", "")) or ""),
            answer=str(d.get("답변", d.get("answer", "")) or ""),
            # 프론트는 넘긴 질문에 'skipped' 를 붙인다 — enum 밖이라 보류로 떨어진다
            verdict=verdict if verdict in QA_VERDICTS else QA_VERDICT_FALLBACK,
            question_id=str(d.get("question_id", "") or ""),
        )


@dataclass
class QaJudgement:
    """
    F-09 의 산출물. 답변 하나의 판정이다.

    최상위 키(`verdict`·`react`·`summary_sentence`·`score`)는 프론트가 이미
    소비하는 이름이라 바꾸지 않는다.

    불변식은 f09_judge.judge_answer() 가 보장한다:
    verdict 는 enum 안 · score 0~100 · react·summary_sentence 는 항상 채워짐 ·
    node_id 는 질문에서 승계(LLM 값 무시).
    """
    question_id: str
    node_id: str = ""
    verdict: str = QA_VERDICT_FALLBACK     # good | partial | wrong | unknown
    score: int = 0                         # 0~100. 없으면 verdict 기본값
    react: str = ""                        # 즉답 반응 한 마디 (말풍선)
    summary_sentence: str = ""             # 이 개념에 대한 총평 한 문장
    missing_points: list[str] = field(default_factory=list)  # 답변에서 빠진 포인트
    model: str = ""
    #: 정답 계열에 못 미칠 때 되물을 후속 질문. 원래 질문을 반복하지 않고
    #: 빠진 지점을 겨냥한다. 통과한 답에는 빈 문자열이다.
    followup: str = ""
    #: 힌트 사다리 (방향 → 범위 → 근접). f08_questions.build_hint_ladder 가 만든다.
    #: 판정에 함께 실어 보내 프론트가 추가 왕복 없이 즉시 보여 줄 수 있게 한다.
    hints: list[str] = field(default_factory=list)
    #: 막힘 코칭 단계 (QA_COACH_STAGES). "" 면 평시 판정이다.
    #: **단계는 서버가 history 로 계산한다** — 프론트가 들고 있으면 저장된 옛 세션에서
    #: 값이 비고, 질문마다 초기화하는 것도 빠뜨리기 쉽다.
    coach_stage: str = ""
    #: coach_stage == "explain" 일 때 채우는 해설. 다른 단계에서는 빈 문자열이다.
    explanation: str = ""

    @property
    def passed(self) -> bool:
        """정답 계열인가. 되묻기를 멈출지 정하는 유일한 출구다."""
        return qa_passed(self.verdict, self.score)

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "node_id": self.node_id,
            "verdict": self.verdict,
            "score": self.score,
            "react": self.react,
            "summary_sentence": self.summary_sentence,
            "missing_points": list(self.missing_points),
            "model": self.model,
            "followup": self.followup,
            "hints": list(self.hints),
            "coach_stage": self.coach_stage,
            "explanation": self.explanation,
            # 파생 — 프론트가 임계를 다시 계산하지 않게 서버가 계산해 내려보낸다
            "passed": self.passed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QaJudgement":
        verdict = str(d.get("verdict", QA_VERDICT_FALLBACK) or "")
        coach_stage = str(d.get("coach_stage", "") or "")
        try:
            score = int(d.get("score", 0) or 0)
        except (TypeError, ValueError):
            score = 0
        return cls(
            question_id=str(d.get("question_id", "") or ""),
            node_id=str(d.get("node_id", "") or ""),
            verdict=verdict if verdict in QA_VERDICTS else QA_VERDICT_FALLBACK,
            score=max(0, min(100, score)),
            react=str(d.get("react", "") or ""),
            summary_sentence=str(d.get("summary_sentence", "") or ""),
            missing_points=[str(x) for x in d.get("missing_points", [])],
            model=d.get("model", ""),
            followup=str(d.get("followup", "") or ""),
            hints=[str(x) for x in d.get("hints", [])],
            coach_stage=coach_stage if coach_stage in QA_COACH_STAGES else "",
            explanation=str(d.get("explanation", "") or ""),
            # `passed` 는 일부러 읽지 않는다 — 요청 바디가 임계를 뒤집을 수 없어야 한다
        )


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


class AlignError(ChuckchuckError):
    """F-11 정합 판정 실패."""


class QuestionError(ChuckchuckError):
    """F-08 예상 질문 생성 실패."""


class JudgeError(ChuckchuckError):
    """F-09 답변 판정 실패."""


def ensure_dict_list(items: list[Any] | list[dict], factory):
    """dict 리스트면 dataclass로 변환. 프론트 JSON 직결용."""
    if not items:
        return []
    if isinstance(items[0], dict):
        return [factory(x) for x in items]
    return list(items)
