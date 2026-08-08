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

    @classmethod
    def from_dict(cls, d: dict) -> "Word":
        """알 수 없는 키(slide_no 등)는 무시 — 프런트·캐시 JSON 이 섞여도 깨지지 않게.
        callers: Transcript.from_dict ← bridge /api/v1/concepts|pace|habits|alignment
        schema: {text, start_sec, end_sec}; extra keys dropped
        user: "목업으로 작동하는거 없이 다 제대로 작동하는지 체크"
        """
        return cls(
            text=str(d.get("text", "")),
            start_sec=float(d.get("start_sec", 0.0) or 0.0),
            end_sec=float(d.get("end_sec", 0.0) or 0.0),
        )


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
            words=[Word.from_dict(w) for w in d.get("words", [])],
            by_slide=[
                SlideSpeech(
                    slide_no=s["slide_no"],
                    visit=s.get("visit", 1),
                    start_sec=float(s["start_sec"]),
                    end_sec=float(s["end_sec"]),
                    text=s.get("text", ""),
                    words=[Word.from_dict(w) for w in s.get("words", [])],
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
#: 이름은 모델명을 그대로 짧게 부른 것이다. 별명을 따로 지으면 좌석 명패
#: (= 모델 배지)와 어긋나 "국내 LLM 4개가 듣고 있다"는 사실이 흐려진다.
CHATTER_NAMES = {
    "midm": "믿:음",
    "solar": "쏠라",
    "exaone": "엑사원",
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
    #: 오늘 못 온 병아리 (모델이 죽었거나 쓸 만한 대사를 한 줄도 못 준 경우).
    #:
    #: 프론트가 이걸 추측하면 안 된다. "refs 가 비었으면 결석" 같은 규칙은 틀린다 —
    #: 엑씨의 애드립·발표 시간 사실은 node_ids 가 원래 비어 있어서, 멀쩡히 일한
    #: 병아리가 결석 처리된다. 결석은 build_chatter 만 알 수 있으므로 여기 싣는다.
    absent: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "total_slides": self.total_slides,
            "turns": [t.to_dict() for t in self.turns],
            "speaker_models": dict(self.speaker_models),
            "speaker_names": dict(self.speaker_names),
            "absent": list(self.absent),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChatterDoc":
        return cls(
            file_name=d["file_name"],
            total_slides=int(d.get("total_slides", 0)),
            turns=[ChatterTurn.from_dict(t) for t in d.get("turns", [])],
            speaker_models=dict(d.get("speaker_models", {})),
            speaker_names=dict(d.get("speaker_names", {})),
            absent=list(d.get("absent", [])),
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
# F-17 : 말 속도 · 시간 배분 (규칙, LLM 없음)
# ---------------------------------------------------------------------------

#: 슬라이드 시간 배분 판정
PACE_STATUSES = ("ok", "short", "long", "fast", "slow")


@dataclass
class SlidePace:
    """한 슬라이드의 실제/권장 시간·속도."""
    slide_no: int
    title: str = ""
    importance: str = "support"   # core | support
    importance_weight: float = 0.35
    actual_sec: float = 0.0
    recommended_sec: float = 0.0
    delta_sec: float = 0.0          # actual - recommended
    chars_per_min: float = 0.0
    syllable_per_sec: float = 0.0
    status: str = "ok"              # ok | short | long | fast | slow
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SlidePace":
        st = d.get("status", "ok")
        return cls(
            slide_no=int(d["slide_no"]),
            title=d.get("title", ""),
            importance=d.get("importance", "support"),
            importance_weight=float(d.get("importance_weight", 0.35)),
            actual_sec=float(d.get("actual_sec", 0.0)),
            recommended_sec=float(d.get("recommended_sec", 0.0)),
            delta_sec=float(d.get("delta_sec", 0.0)),
            chars_per_min=float(d.get("chars_per_min", 0.0)),
            syllable_per_sec=float(d.get("syllable_per_sec", 0.0)),
            status=st if st in PACE_STATUSES else "ok",
            note=d.get("note", ""),
        )


@dataclass
class SectionAlloc:
    """구획(섹션) 단위 권장/실제 시간."""
    name: str
    slide_nos: list[int] = field(default_factory=list)
    recommended_sec: float = 0.0
    actual_sec: float = 0.0
    status: str = "ok"              # ok | short | long
    label: str = ""                 # UI용 "+17% 초과" 등

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SectionAlloc":
        return cls(
            name=d.get("name", ""),
            slide_nos=[int(n) for n in d.get("slide_nos", [])],
            recommended_sec=float(d.get("recommended_sec", 0.0)),
            actual_sec=float(d.get("actual_sec", 0.0)),
            status=d.get("status", "ok"),
            label=d.get("label", ""),
        )


@dataclass
class PaceDoc:
    """F-17 산출물. 말 속도·시간 배분 표 + 규칙 팁."""
    target_sec: float = 0.0
    actual_sec: float = 0.0
    avg_chars_per_min: float = 0.0
    avg_syllable_per_sec: float = 0.0
    max_chars_per_min: float = 0.0
    max_slide_no: int | None = None
    recommended_cpm: str = "300~350"
    slides: list[SlidePace] = field(default_factory=list)
    sections: list[SectionAlloc] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "target_sec": self.target_sec,
            "actual_sec": self.actual_sec,
            "avg_chars_per_min": self.avg_chars_per_min,
            "avg_syllable_per_sec": self.avg_syllable_per_sec,
            "max_chars_per_min": self.max_chars_per_min,
            "max_slide_no": self.max_slide_no,
            "recommended_cpm": self.recommended_cpm,
            "slides": [s.to_dict() for s in self.slides],
            "sections": [s.to_dict() for s in self.sections],
            "tips": list(self.tips),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PaceDoc":
        return cls(
            target_sec=float(d.get("target_sec", 0.0)),
            actual_sec=float(d.get("actual_sec", 0.0)),
            avg_chars_per_min=float(d.get("avg_chars_per_min", 0.0)),
            avg_syllable_per_sec=float(d.get("avg_syllable_per_sec", 0.0)),
            max_chars_per_min=float(d.get("max_chars_per_min", 0.0)),
            max_slide_no=d.get("max_slide_no"),
            recommended_cpm=d.get("recommended_cpm", "300~350"),
            slides=[SlidePace.from_dict(s) for s in d.get("slides", [])],
            sections=[SectionAlloc.from_dict(s) for s in d.get("sections", [])],
            tips=list(d.get("tips", [])),
        )


# ---------------------------------------------------------------------------
# F-18 : 음성 습관 신호 (REP/FIL/PAUSE)
# ---------------------------------------------------------------------------

HABIT_KINDS = ("REP", "FIL", "PAUSE")


@dataclass
class HabitSpan:
    """습관 스팬 하나. 타임코드로 슬라이드에 붙인다."""
    kind: str                       # REP | FIL | PAUSE
    text: str = ""
    start_sec: float = 0.0
    end_sec: float = 0.0
    slide_no: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "HabitSpan":
        kind = d.get("kind", "FIL")
        return cls(
            kind=kind if kind in HABIT_KINDS else "FIL",
            text=d.get("text", ""),
            start_sec=float(d.get("start_sec", 0.0)),
            end_sec=float(d.get("end_sec", 0.0)),
            slide_no=d.get("slide_no"),
        )


@dataclass
class SlideHabits:
    """슬라이드별 습관 카운트."""
    slide_no: int
    repeat_cnt: int = 0
    filler_cnt: int = 0
    pause_cnt: int = 0
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SlideHabits":
        return cls(
            slide_no=int(d["slide_no"]),
            repeat_cnt=int(d.get("repeat_cnt", 0)),
            filler_cnt=int(d.get("filler_cnt", 0)),
            pause_cnt=int(d.get("pause_cnt", 0)),
            note=d.get("note", ""),
        )


@dataclass
class HabitDoc:
    """F-18 산출물. 습관 스팬 + 슬라이드별 집계."""
    spans: list[HabitSpan] = field(default_factory=list)
    by_slide: list[SlideHabits] = field(default_factory=list)
    repeat_cnt: int = 0
    filler_cnt: int = 0
    pause_cnt: int = 0
    provider: str = ""              # heuristic | fixture | lora
    tips: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "spans": [s.to_dict() for s in self.spans],
            "by_slide": [s.to_dict() for s in self.by_slide],
            "repeat_cnt": self.repeat_cnt,
            "filler_cnt": self.filler_cnt,
            "pause_cnt": self.pause_cnt,
            "provider": self.provider,
            "tips": list(self.tips),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HabitDoc":
        return cls(
            spans=[HabitSpan.from_dict(s) for s in d.get("spans", [])],
            by_slide=[SlideHabits.from_dict(s) for s in d.get("by_slide", [])],
            repeat_cnt=int(d.get("repeat_cnt", 0)),
            filler_cnt=int(d.get("filler_cnt", 0)),
            pause_cnt=int(d.get("pause_cnt", 0)),
            provider=d.get("provider", ""),
            tips=list(d.get("tips", [])),
        )


# ---------------------------------------------------------------------------
# F-19 : 종합 진단 리포트 (LLM — F-17·F-18 수치만 해석)
# ---------------------------------------------------------------------------

@dataclass
class ReportDoc:
    """F-19 산출물. 요약 탭·코칭 문장의 재료."""
    one_liner: str = ""
    score: int = 0                  # 0~100 (UI 링)
    grade: str = ""                 # A+~F (선택)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    pace_summary: str = ""
    habit_summary: str = ""
    model: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ReportDoc":
        return cls(
            one_liner=d.get("one_liner", ""),
            score=int(d.get("score", 0)),
            grade=d.get("grade", ""),
            strengths=list(d.get("strengths", [])),
            weaknesses=list(d.get("weaknesses", [])),
            actions=list(d.get("actions", [])),
            pace_summary=d.get("pace_summary", ""),
            habit_summary=d.get("habit_summary", ""),
            model=d.get("model", ""),
        )


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


#: 한 질문을 붙들 최대 라운드. 넘어가면 통과 수준(qa_passed)에서 닫아 준다 —
#: 소크라테스식 압박이 목적이지 고문이 목적이 아니다. 지치면 이탈한다.
QA_MAX_ROUNDS = 3


def qa_mastered(verdict: str, score: int, round_no: int) -> bool:
    """
    이 답변으로 질문을 닫을지. **되묻기를 멈추는 유일한 출구다.**

    `qa_passed` 와 일부러 나눠 둔다. 둘을 하나로 두면 요지만 맞힌 72점 답이
    곧바로 질문을 닫아 **되묻기가 아예 안 돈다** — 실제로 그랬다. 절반 맞힌
    사람에게 한 걸음 더 묻는 것이 이 서비스의 핵심 로직인데, 가장 흔한 답변
    구간(70~79)이 통째로 그 루프를 건너뛰고 있었다.

      passed    리포트가 "이 개념을 방어했는가" 를 셀 때 쓴다. 기준을 안 건드린다.
      mastered  대화가 "이제 넘어가도 되는가" 를 정할 때 쓴다. 더 엄격하다.

    verdict 가 good 이면 라운드와 무관하게 닫는다 — "자기 말로 정확히 설명했다"
    가 곧 정복이다. 그 아래는 QA_MAX_ROUNDS 라운드까지 계속 되묻고, 거기서도
    못 올라오면 통과 수준에서 닫아 준다.

    round_no 는 이 질문에 낸 답변의 순번(1부터)이다. **서버가 누적 답변 수로 센다** —
    프론트가 보내면 옛 세션에서 비고, 질문마다 초기화하는 것도 빠뜨리기 쉽다
    (f09_judge `_coach_stage` 와 같은 이유).
    """
    if verdict == "good":
        return True
    return round_no >= QA_MAX_ROUNDS and qa_passed(verdict, score)


#: 되묻기 압박 단계. 라운드가 오를수록 질문이 좁아진다 — 같은 넓이로 세 번
#: 물으면 압박이 아니라 반복이다. **무엇을 물을지는 코드가 정하고 LLM 은
#: 문장만 쓴다** (F-08·F-09 공통 원칙).
#:   ""         되물을 일이 없다 (정복했거나 막힘 코칭 경로다)
#:   probe      1라운드 — 빠진 지점 하나를 열린 질문으로 짚는다
#:   focus      2라운드 — 예/아니오·둘 중 하나로 답할 만큼 좁힌다
#:   converge   3라운드+ — 답을 거의 품은 확인 질문으로 마지막 한 걸음만 남긴다
QA_PROBE_TIERS = ("", "probe", "focus", "converge")


def qa_probe_tier(round_no: int) -> str:
    """라운드 번호 → 압박 단계. 상한을 넘으면 계속 converge 다."""
    if round_no <= 1:
        return "probe"
    if round_no == 2:
        return "focus"
    return "converge"


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

    `gave_up` 은 **의사**지 텍스트가 아니다. 「모르겠어요」 버튼을 누른 사실을
    답변 글에서 역추정하면(`looks_stuck`) 사용자가 뭔가 써 놓고 눌렀을 때 놓친다 —
    그러면 F-09 막힘 코칭이 explain 단계로 못 올라가 같은 질문에 갇힌다.
    """
    question: str = ""
    answer: str = ""
    verdict: str = QA_VERDICT_FALLBACK
    question_id: str = ""
    gave_up: bool = False

    def to_dict(self) -> dict:
        return {
            "질문": self.question,
            "답변": self.answer,
            "판정": self.verdict,
            "question_id": self.question_id,
            "포기": self.gave_up,
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
            gave_up=bool(d.get("포기", d.get("gave_up", False))),
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
    #: 이 질문에 낸 답변의 순번 (1부터). 서버가 누적 답변 수로 센다.
    #: 화면이 「1차 방어 → 2차 압박 → 3차 확인」 을 표시하는 근거이자,
    #: mastered·probe_tier 를 계산하는 입력이다.
    round_no: int = 1
    #: 되묻기 압박 단계 (QA_PROBE_TIERS). 정복했으면 빈 문자열이다.
    probe_tier: str = ""

    @property
    def passed(self) -> bool:
        """정답 계열인가. **리포트가 방어 여부를 셀 때 쓰는 값이다.**"""
        return qa_passed(self.verdict, self.score)

    @property
    def mastered(self) -> bool:
        """
        이 질문을 닫아도 되는가. **되묻기를 멈추는 유일한 출구다.**

        passed 보다 엄격하다 — 절반만 맞힌 답에 한 걸음 더 묻기 위해서다.
        자세한 이유는 `qa_mastered` 를 보라.
        """
        return qa_mastered(self.verdict, self.score, self.round_no)

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
            "round_no": self.round_no,
            "probe_tier": self.probe_tier,
            # 파생 — 프론트가 임계를 다시 계산하지 않게 서버가 계산해 내려보낸다.
            # 둘을 다 보낸다: passed 는 리포트가 세는 값, mastered 는 대화가 닫는 값.
            "passed": self.passed,
            "mastered": self.mastered,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QaJudgement":
        verdict = str(d.get("verdict", QA_VERDICT_FALLBACK) or "")
        coach_stage = str(d.get("coach_stage", "") or "")
        probe_tier = str(d.get("probe_tier", "") or "")
        try:
            score = int(d.get("score", 0) or 0)
        except (TypeError, ValueError):
            score = 0
        try:
            round_no = int(d.get("round_no", 1) or 1)
        except (TypeError, ValueError):
            round_no = 1
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
            round_no=max(1, round_no),
            probe_tier=probe_tier if probe_tier in QA_PROBE_TIERS else "",
            # `passed`·`mastered` 는 일부러 읽지 않는다 — 요청 바디가 임계를 뒤집을 수 없어야 한다.
            # round_no 는 읽는다: 파생값이 아니라 서버가 센 사실이고, 판정을 저장했다가
            # 다시 읽을 때(옛 세션 복원) 이 값이 없으면 mastered 가 1라운드로 되돌아간다.
        )


# ---------------------------------------------------------------------------
# F-14 채점표 채점 (rubric v3)
# ---------------------------------------------------------------------------

#: 항목 하나의 상태.
#: - scored: 실제로 매겼다
#: - situation_excluded: 이 발표 상황에서는 평가하지 않는 항목이다 (채점표 가중치 0)
#: - unmeasured: 평가해야 할 항목인데 이번 실행에서 못 쟀다 (자료 없음·LLM 실패·음향 없음)
#:
#: 뒤의 둘을 한 필드로 합치지 않는다. 화면 문구가 다르다 —
#: "이 상황에서는 평가하지 않아요" 와 "이번엔 측정할 수 없었어요" 는 다른 말이다.
RUBRIC_ITEM_STATUSES = ("scored", "situation_excluded", "unmeasured")
RUBRIC_ITEM_STATUS_FALLBACK = "unmeasured"

#: 클러스터 상태. omitted 면 그 클러스터 가중치를 남은 클러스터에 재분배한다.
RUBRIC_CLUSTER_STATUSES = ("scored", "omitted")

#: 채점의 완결성.
#: - full: 잴 수 있는 항목은 다 쟀다 (영구 측정 불가 항목은 계산에서 제외한다)
#: - partial: 잴 수 있었어야 할 항목을 못 쟀다
#:
#: 음량 안정성(25)·핵심 구간 강조(26)는 음향 특징이 없어 언제나 못 잰다. 이 둘까지
#: partial 로 치면 basis 가 영영 full 이 못 되고, 늘 켜진 경고는 아무도 안 읽는다.
RUBRIC_BASES = ("full", "partial")


@dataclass
class RubricItemScore:
    """채점표 항목 하나의 결과. 점수 한 자리를 끝까지 역추적하게 해 주는 단위다."""

    no: int
    cluster: str = ""
    name: str = ""
    status: str = "scored"     # RUBRIC_ITEM_STATUSES
    score: int = 0             # 0~100. status == "scored" 일 때만 뜻이 있다
    weight: int = 0            # 이 상황의 내부 가중치 (재분배 전 원본)
    source: str = ""           # det | llm | na
    evidence: str = ""         # 발화 인용 또는 수치 근거 한 줄. 비면 점수를 안 쓴다
    note: str = ""             # 왜 이 점수인지 / 왜 못 쟀는지

    def to_dict(self) -> dict:
        return {
            "no": self.no,
            "cluster": self.cluster,
            "name": self.name,
            "status": self.status,
            "score": self.score,
            "weight": self.weight,
            "source": self.source,
            "evidence": self.evidence,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RubricItemScore":
        status = str(d.get("status", "scored") or "")
        try:
            score = int(d.get("score", 0) or 0)
        except (TypeError, ValueError):
            score = 0
        try:
            weight = int(d.get("weight", 0) or 0)
        except (TypeError, ValueError):
            weight = 0
        return cls(
            no=int(d.get("no", 0) or 0),
            cluster=str(d.get("cluster", "") or ""),
            name=str(d.get("name", "") or ""),
            status=status if status in RUBRIC_ITEM_STATUSES else RUBRIC_ITEM_STATUS_FALLBACK,
            score=max(0, min(100, score)),
            weight=max(0, weight),
            source=str(d.get("source", "") or ""),
            evidence=str(d.get("evidence", "") or ""),
            note=str(d.get("note", "") or ""),
        )


@dataclass
class RubricClusterScore:
    """클러스터 하나의 가중평균. 리포트 막대 한 줄이 이것이다."""

    key: str
    name: str = ""
    weight: int = 0                  # 채점표의 클러스터 가중치(%)
    effective_weight: float = 0.0    # 재분배 후 실제 적용 비중. 살아 있는 것들의 합이 1.0
    average: float = 0.0             # 0~100
    contribution: float = 0.0        # average * effective_weight
    item_nos: list[int] = field(default_factory=list)   # 평균에 실제로 들어간 항목
    status: str = "scored"           # RUBRIC_CLUSTER_STATUSES

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "weight": self.weight,
            "effective_weight": round(self.effective_weight, 4),
            "average": round(self.average, 2),
            "contribution": round(self.contribution, 2),
            "item_nos": list(self.item_nos),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RubricClusterScore":
        status = str(d.get("status", "scored") or "")
        return cls(
            key=str(d.get("key", "") or ""),
            name=str(d.get("name", "") or ""),
            weight=int(d.get("weight", 0) or 0),
            effective_weight=float(d.get("effective_weight", 0.0) or 0.0),
            average=float(d.get("average", 0.0) or 0.0),
            contribution=float(d.get("contribution", 0.0) or 0.0),
            item_nos=[int(x) for x in d.get("item_nos", [])],
            status=status if status in RUBRIC_CLUSTER_STATUSES else "omitted",
        )


@dataclass
class RubricScore:
    """
    F-14 산출물. 발표 하나의 최종 점수와 그 근거 전부다.

    불변식은 f14_rubric.score_rubric() 이 보장한다:
    살아 있는 클러스터의 effective_weight 합이 1.0 · score == round(Σ contribution) ·
    excluded 와 unmeasured 는 서로 섞이지 않음 · 근거(evidence) 없는 점수는 채택하지 않음.
    """

    score: int = 0
    situation: str = ""            # 채점 기준이 된 상황 key
    situation_label: str = ""      # 화면에 그대로 나가는 한글 라벨
    rubric_version: str = "v3"     # "v3-fallback" 이면 채점표가 아니라 예전 방식으로 매긴 것
    clusters: list[RubricClusterScore] = field(default_factory=list)
    items: list[RubricItemScore] = field(default_factory=list)
    excluded: list[int] = field(default_factory=list)     # 이 상황에서 평가하지 않는 항목 번호
    unmeasured: list[int] = field(default_factory=list)   # 이번에 못 잰 항목 번호
    basis: str = "full"            # RUBRIC_BASES
    model: str = ""
    note: str = ""                 # 사용자에게 보일 한 줄 (상황 추정·폴백·전부 못 잼 등)

    def item(self, no: int) -> "RubricItemScore | None":
        for it in self.items:
            if it.no == no:
                return it
        return None

    def cluster(self, key: str) -> "RubricClusterScore | None":
        for c in self.clusters:
            if c.key == key:
                return c
        return None

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "situation": self.situation,
            "situation_label": self.situation_label,
            "rubric_version": self.rubric_version,
            "clusters": [c.to_dict() for c in self.clusters],
            "items": [i.to_dict() for i in self.items],
            "excluded": list(self.excluded),
            "unmeasured": list(self.unmeasured),
            "basis": self.basis,
            "model": self.model,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RubricScore":
        basis = str(d.get("basis", "full") or "")
        try:
            score = int(d.get("score", 0) or 0)
        except (TypeError, ValueError):
            score = 0
        return cls(
            score=max(0, min(100, score)),
            situation=str(d.get("situation", "") or ""),
            situation_label=str(d.get("situation_label", "") or ""),
            rubric_version=str(d.get("rubric_version", "v3") or "v3"),
            clusters=ensure_dict_list(d.get("clusters", []), RubricClusterScore.from_dict),
            items=ensure_dict_list(d.get("items", []), RubricItemScore.from_dict),
            excluded=[int(x) for x in d.get("excluded", [])],
            unmeasured=[int(x) for x in d.get("unmeasured", [])],
            basis=basis if basis in RUBRIC_BASES else "partial",
            model=str(d.get("model", "") or ""),
            note=str(d.get("note", "") or ""),
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


class PaceError(ChuckchuckError):
    """F-17 말 속도·시간 배분 실패."""


class HabitError(ChuckchuckError):
    """F-18 음성 습관 추출 실패."""


class ReportError(ChuckchuckError):
    """F-19 종합 리포트 생성 실패."""


class ChatterError(ChuckchuckError):
    """삐약 청중석 수다 생성 실패."""


class QuestionError(ChuckchuckError):
    """F-08 예상 질문 생성 실패."""


class JudgeError(ChuckchuckError):
    """F-09 답변 판정 실패."""


class StrategyError(ChuckchuckError):
    """F-20 발표 전략 제안 실패."""


class RubricError(ChuckchuckError):
    """F-14 채점표 채점 실패."""


def ensure_dict_list(items: list[Any] | list[dict], factory):
    """dict 리스트면 dataclass로 변환. 프론트 JSON 직결용."""
    if not items:
        return []
    if isinstance(items[0], dict):
        return [factory(x) for x in items]
    return list(items)
