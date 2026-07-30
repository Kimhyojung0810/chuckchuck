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
# 삐약 청중석 : 청중 반응 수다 (ChatterDoc)
# ---------------------------------------------------------------------------
# 국내 LLM 4개가 병아리 청중을 연기하며 발표에 대해 떠든다. 성격은 임의 배정이
# 아니라 각 모델이 파이프라인에서 실제로 한 일에서 나온다 (solar=자료를 읽음,
# ax=발표를 들음, midm=믿음/검증, exaone=전문가 칭찬).
#
# 대사 내용은 이미 계산된 AlignmentDoc·FlowDiff 의 사실만 쓴다. 어떤 노드를
# 언급할지는 코드가 결정적으로 고르고, LLM 은 말투만 입힌다 — F-11 과 같은 철학.

#: speaker id. providers/llm_impl.py REGISTRY 키와 동일해서 별도 매핑이 없다.
CHATTER_SPEAKERS = ("midm", "solar", "exaone", "ax")

#: 프론트가 아바타 표정·모션을 고르는 키. enum 밖은 neutral 로 떨어진다.
CHATTER_MOODS = ("grumpy", "happy", "curious", "excited", "neutral")

#: refs[].source — 이 대사의 근거가 어느 산출물에서 왔나.
CHATTER_REF_SOURCES = ("alignment", "flow", "graph")

#: 화면에 상시 노출하는 모델 배지. "국내 LLM 총출동"을 설명 없이 보이게 하는 장치라
#: 어느 단계에서도 숨기지 않는다.
CHATTER_BADGES = {
    "midm": "KT 믿:음",
    "solar": "Upstage Solar",
    "exaone": "LG EXAONE",
    "ax": "SKT A.X",
}

#: 병아리 이름 (화면 표시용).
CHATTER_NAMES = {
    "midm": "믿음이",
    "solar": "쏠라",
    "exaone": "엑사",
    "ax": "엑씨",
}


@dataclass
class ChatterRef:
    """대사 하나의 근거. node_id 로 리포트의 개념 판정과 조인한다."""
    node_id: str
    source: str = "alignment"   # alignment | flow | graph

    def to_dict(self) -> dict:
        return {"node_id": self.node_id, "source": self.source}

    @classmethod
    def from_dict(cls, d: dict) -> "ChatterRef":
        return cls(
            node_id=str(d["node_id"]),
            source=str(d.get("source", "alignment")),
        )


@dataclass
class ChatterTurn:
    """수다 한 턴. refs 가 비면 근거 없는 스몰토크다 (개수 제한 대상)."""
    speaker: str                        # CHATTER_SPEAKERS 중 하나
    text: str
    mood: str = "neutral"               # CHATTER_MOODS 중 하나
    refs: list[ChatterRef] = field(default_factory=list)

    @property
    def is_smalltalk(self) -> bool:
        return not self.refs

    def to_dict(self) -> dict:
        return {
            "speaker": self.speaker,
            "text": self.text,
            "mood": self.mood,
            "refs": [r.to_dict() for r in self.refs],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChatterTurn":
        return cls(
            speaker=str(d["speaker"]),
            text=str(d.get("text", "")),
            mood=str(d.get("mood", "neutral")),
            refs=[ChatterRef.from_dict(r) for r in d.get("refs", [])],
        )


@dataclass
class ChatterDoc:
    """
    청중 반응 수다. 프론트 채팅방이 이걸 그대로 재생한다.

    불변식은 f12_chatter.build_chatter() 가 보장한다:
    speaker 전원 최소 1턴 · refs 는 그 speaker 에게 배정된 근거만 ·
    mood 는 enum 안 · 스몰토크 비율 상한 · 전체 턴 수 상한.
    """
    file_name: str
    total_slides: int = 0
    turns: list[ChatterTurn] = field(default_factory=list)
    #: speaker → 배지 문자열. 프론트가 CHATTER_BADGES 를 몰라도 되게 같이 실어 보낸다.
    speaker_models: dict[str, str] = field(default_factory=dict)
    #: speaker → 병아리 이름.
    speaker_names: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "total_slides": self.total_slides,
            "turns": [t.to_dict() for t in self.turns],
            "speaker_models": dict(self.speaker_models),
            "speaker_names": dict(self.speaker_names),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChatterDoc":
        return cls(
            file_name=d["file_name"],
            total_slides=int(d.get("total_slides", 0)),
            turns=[ChatterTurn.from_dict(t) for t in d.get("turns", [])],
            speaker_models=dict(d.get("speaker_models", {})),
            speaker_names=dict(d.get("speaker_names", {})),
        )

    def turns_of(self, speaker: str) -> list[ChatterTurn]:
        """특정 병아리의 대사들."""
        return [t for t in self.turns if t.speaker == speaker]

    @property
    def referenced_node_ids(self) -> list[str]:
        """수다가 실제로 언급한 노드들. 리포트와 따로 놀지 않는지 확인용."""
        seen: list[str] = []
        for turn in self.turns:
            for ref in turn.refs:
                if ref.node_id not in seen:
                    seen.append(ref.node_id)
        return seen


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


class ChatterError(ChuckchuckError):
    """삐약 청중석 수다 생성 실패."""


def ensure_dict_list(items: list[Any] | list[dict], factory):
    """dict 리스트면 dataclass로 변환. 프론트 JSON 직결용."""
    if not items:
        return []
    if isinstance(items[0], dict):
        return [factory(x) for x in items]
    return list(items)
