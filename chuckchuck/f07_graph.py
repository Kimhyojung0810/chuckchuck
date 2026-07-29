"""
[F-07] 장 단위 개념을 발표 전체 기준 '가중치 그래프' 로 묶는 모듈입니다.
ConceptDoc(+선택 SlideDoc) → ConceptGraph.

트리가 아니라 그래프인 이유: 개념은 부모가 하나라는 보장이 없습니다.
parent 간선만 따라가면 트리 뷰가 나오고, relates 간선이 나머지 연결을 담습니다.

발화 축(speech_weight)과 정합 판정(누락·모순)은 여기 없습니다.
F-07 은 Transcript 를 받지 않습니다. 그건 node.id 로 조인하는 뒤 단계 몫입니다.

    from chuckchuck.f07_graph import build_graph
    graph = build_graph(concept_doc, context, slide_doc=slide_doc, llm="solar")
"""

from __future__ import annotations

import os
import re

from ._json_text import extract_json_object
from ._match import contains_tokens, label_tokens, norm_tokens
from .contracts import (
    EDGE_KIND_FALLBACK,
    EDGE_KINDS,
    SLIDE_ROLE_FALLBACK,
    SLIDE_ROLES,
    ConceptDoc,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    Context,
    GraphError,
    Section,
    SlideDoc,
    WeightBasis,
)
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm

MAX_TOKENS = int(os.environ.get("CHUCKCHUCK_GRAPH_MAX_TOKENS", "8192"))
MAX_CONCEPTS_PER_SLIDE = int(os.environ.get("CHUCKCHUCK_GRAPH_MAX_CONCEPTS", "6"))
#: 계약상 얕은 그래프를 요구한다. 이보다 깊으면 상위로 끌어올린다.
MAX_GRAPH_DEPTH = int(os.environ.get("CHUCKCHUCK_GRAPH_MAX_DEPTH", "3"))
#: 프롬프트가 요구하는 최상위 개념 상한. 실측에서 13/28 이 루트로 떠서 후처리로 잡는다.
MAX_ROOTS = int(os.environ.get("CHUCKCHUCK_GRAPH_MAX_ROOTS", "4"))

# weight 배합. 합이 1.0 이고, 여기서 깊이 감점을 뺀다.
# mention·title 은 개념 단위 신호 — slide_nos 가 같은 개념들의 동률을 가른다.
_W_IMPORTANCE = 0.18
_W_SLIDE_SHARE = 0.30
_W_CHAR_SHARE = 0.25
_W_VISUAL = 0.10
_W_MENTION = 0.12
_W_TITLE = 0.05
_DEPTH_PENALTY = 0.05
_IMPORTANCE_SCORE = {"core": 1.0, "support": 0.35}

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

SYSTEM_PROMPT = """당신은 발표 구조 분석가다.
'개념 목록'을 받아, 발표 전체 기준의 개념 그래프와 구획을 만든다.

가장 중요한 것 — 노드는 슬라이드가 아니라 '개념'이다:
- 노드는 반드시 '개념 목록'의 항목에서 만든다.
- 슬라이드 제목("자사 분석", "경쟁사 분석" 같은 것)을 노드 label 로 쓰지 마라.
  그건 목차지 개념이 아니다.
- 노드 개수가 슬라이드 개수와 같으면 슬라이드를 그대로 옮긴 것이므로 잘못 만든 것이다.
- 같은 개념이 여러 [S번호]에 나오면 하나의 노드로 합치고 slide_nos 에 그 번호를 모두 적어라.

연결선(edges) 규칙:
1. edges 는 반드시 채운다. 간선이 하나도 없으면 잘못 만든 것이다.
2. kind="parent" 는 위계다. from 이 상위 개념, to 가 하위 개념이다.
   하위 개념 하나에 상위 개념은 하나만 붙인다.
3. kind="relates" 는 위계가 아닌 논리 연결이다. 근거·수단·대조 관계를 여기 적는다.
   한 개념이 여러 개념에 걸칠 때 이걸 쓴다.
4. 위계 깊이는 3단계를 넘기지 마라. 발표를 관통하는 큰 개념 2~4개를 최상위로 둔다.
   부모 없는 개념이 5개 이상이면 위계를 안 만든 것이므로 잘못 만든 것이다.

그 밖:
5. 자료에 없는 개념을 지어내지 마라. 주어진 개념 안에서만 묶어라.
6. id 는 영소문자·숫자·하이픈만 쓴다. 짧고 의미 있게. 유일해야 한다.
7. label 은 개념 이름만 짧게. summary 에 한 줄 설명을 넣는다.
8. sections 는 발표를 앞에서 뒤로 훑어 구획으로 나눈 것이다. 모든 장이 어딘가에 들어가야 한다.
   slide_role 은 cover, intro, body, conclusion, closing 중 하나만 쓴다.
9. 개념이 잘 설명됐는지 못 됐는지 판정하지 마라. 그건 다음 단계 일이다.
10. 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마:
{
  "nodes": [
    { "id": "contrast", "label": "개념 이름", "slide_nos": [4, 5],
      "summary": "한 줄 설명", "importance": "core" }
  ],
  "edges": [
    { "from": "contrast", "to": "joint", "kind": "parent" },
    { "from": "joint", "to": "encoder", "kind": "relates" }
  ],
  "sections": [
    { "name": "본론 — 제안 방법", "slide_role": "body", "slide_nos": [6, 7, 8] }
  ]
}
"""

#: 간선이 하나도 없이 돌아왔을 때 한 번 더 물어볼 때 덧붙이는 말.
RETRY_NUDGE = """
[재요청] 직전 응답의 edges 가 비어 있었다. 개념들이 서로 아무 관계도 없다는 뜻이 되어 쓸 수 없다.
이번에는 kind="parent" 간선을 반드시 포함해, 큰 개념 아래에 하위 개념을 매달아라.
"""

#: 응답이 복구 불가능한 JSON 일 때 한 번 더 물어볼 때 덧붙이는 말 (실측: Solar 가 가끔 낸다).
JSON_RETRY_NUDGE = """
[재요청] 직전 응답이 완전한 JSON 객체가 아니어서 버렸다.
코드펜스·주석·말머리·말끝 문장 없이, 출력 스키마 그대로의 JSON 객체 하나만 다시 출력하라.
"""


# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------

def _build_user_prompt(doc: ConceptDoc, ctx: Context) -> str:
    """
    ConceptDoc 전체를 한 번에 보여 준다. 위계는 전역 시야가 있어야 정해진다.

    개념 풀을 먼저, 슬라이드 흐름을 나중에 둔다. 슬라이드 단위로 먼저 보여 주면
    모델이 '슬라이드 1개 = 노드 1개' 로 옮겨 적고 연결선을 만들지 않는다.
    """
    concept_lines: list[str] = []
    for s in doc.slides:
        for c in s.concepts[:MAX_CONCEPTS_PER_SLIDE]:
            concept_lines.append(f"- [S{s.slide_no}] {c}")
        for kw in s.keywords:
            concept_lines.append(f"- [S{s.slide_no}] {kw}")

    parts = [
        "[TASK] concept-graph",
        ctx.to_prompt_block(),
        "",
        f"파일명: {doc.file_name}",
        f"총 슬라이드: {doc.total_slides}",
        f"개념 후보: {len(concept_lines)}개",
        "",
        "## 개념 목록 — 노드는 여기서만 만든다",
        "[S번호] 는 그 개념이 나온 슬라이드다. 같은 개념이 여러 번 나오면 하나로 합쳐라.",
        "",
    ]
    parts += concept_lines
    parts += [
        "",
        "## 발표 흐름 — sections 를 나눌 때만 참고한다 (노드로 쓰지 마라)",
        "",
    ]
    for s in doc.slides:
        head = f"### 슬라이드 {s.slide_no}: {s.title or '(제목 없음)'}"
        if s.topic:
            head += f" — {s.topic}"
        parts.append(head)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 노드 후처리
# ---------------------------------------------------------------------------

def _slug(value: str) -> str:
    """id 후보를 영소문자·숫자·하이픈으로. 남는 게 없으면 빈 문자열."""
    return _SLUG_STRIP.sub("-", str(value or "").lower()).strip("-")


def _assign_ids(raw_nodes: list[dict]) -> tuple[list[str], dict[str, str]]:
    """
    최종 id 목록과 '모델이 쓴 원래 id → 최종 id' 대응표를 만든다.

    edges 는 원래 id 로 적혀 있으므로, 대응표가 있어야 양끝을 다시 찾는다.
    """
    final_ids: list[str] = []
    alias: dict[str, str] = {}
    used: set[str] = set()

    for i, raw in enumerate(raw_nodes, start=1):
        original = str(raw.get("id", "") or "")
        candidate = _slug(original) or f"n{i}"
        unique = candidate
        suffix = 2
        while unique in used:
            unique = f"{candidate}-{suffix}"
            suffix += 1
        used.add(unique)
        final_ids.append(unique)
        if original and original not in alias:
            alias[original] = unique

    return final_ids, alias


def _valid_slide_nos(values, total_slides: int) -> list[int]:
    """1..total_slides 밖의 번호는 버리고, 중복 제거 후 정렬."""
    out: set[int] = set()
    for v in values or []:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= total_slides:
            out.add(n)
    return sorted(out)


def _inherit_importance(slide_nos: list[int], by_slide: dict[int, str], fallback: str) -> str:
    """근거 슬라이드 중 하나라도 core 면 core, 전부 support 면 support."""
    marks = [by_slide[n] for n in slide_nos if n in by_slide]
    if not marks:
        return fallback if fallback in _IMPORTANCE_SCORE else "core"
    return "core" if "core" in marks else "support"


def _position(slide_nos: list[int], total_slides: int) -> str:
    """개념이 처음 등장하는 위치. 초반 맥락인지 후반 클라이맥스인지."""
    if not slide_nos or total_slides <= 0:
        return "middle"
    ratio = (min(slide_nos) - 1) / total_slides
    if ratio < 1 / 3:
        return "early"
    if ratio >= 2 / 3:
        return "late"
    return "middle"


# ---------------------------------------------------------------------------
# 간선 후처리 — edges 가 진실이고 parent_id/depth 는 여기서 파생된다
# ---------------------------------------------------------------------------

def _normalize_edges(
    raw_edges: list[dict],
    alias: dict[str, str],
    node_ids: set[str],
) -> tuple[dict[str, str], list[ConceptEdge]]:
    """
    raw 간선을 (child → parent 대응표, relates 간선 목록) 으로 정리한다.

    - 양끝이 존재하는 노드가 아니면 버린다
    - 자기 자신을 가리키는 간선은 버린다
    - 같은 (from, to) 가 여러 번 오면 첫 번째만 남긴다
    - 한 노드에 parent 간선이 여러 개 붙으면 첫 번째만 parent, 나머지는 relates 로 내린다
    """
    def resolve(value) -> str | None:
        if value is None:
            return None
        key = str(value)
        final = alias.get(key, key)
        return final if final in node_ids else None

    parent_of: dict[str, str] = {}
    relates: list[ConceptEdge] = []
    seen_pairs: set[tuple[str, str]] = set()

    for raw in raw_edges:
        src = resolve(raw.get("from"))
        dst = resolve(raw.get("to"))
        if src is None or dst is None or src == dst:
            continue
        if (src, dst) in seen_pairs:
            continue
        seen_pairs.add((src, dst))

        kind = raw.get("kind", "parent")
        kind = kind if kind in EDGE_KINDS else EDGE_KIND_FALLBACK
        if kind == "parent" and dst not in parent_of:
            parent_of[dst] = src
        else:
            # 이미 부모가 있는 하위 개념의 추가 부모 → 정보를 버리지 않고 relates 로
            relates.append(ConceptEdge(from_id=src, to_id=dst, kind="relates"))

    return parent_of, relates


def _break_parent_cycles(parent_of: dict[str, str]) -> None:
    """부모를 따라가다 자기 자신을 다시 만나면 그 고리를 끊는다 (제자리 수정)."""
    for start in list(parent_of):
        seen = {start}
        cursor = start
        while cursor in parent_of:
            nxt = parent_of[cursor]
            if nxt in seen:
                del parent_of[cursor]
                break
            seen.add(nxt)
            cursor = nxt


def _depth_of(node_id: str, parent_of: dict[str, str]) -> int:
    """부모 체인 길이. 순환이 제거된 뒤에 부른다."""
    depth = 1
    cursor = node_id
    while cursor in parent_of:
        depth += 1
        cursor = parent_of[cursor]
    return depth


def _clamp_depth(parent_of: dict[str, str], node_ids: list[str], max_depth: int) -> None:
    """
    너무 깊은 노드를 max_depth 에 맞게 상위로 끌어올린다 (제자리 수정).

    원래 체인에서 depth == max_depth - 1 인 조상을 찾아 그 아래로 다시 매단다.
    """
    if max_depth < 1:
        return
    depths = {nid: _depth_of(nid, parent_of) for nid in node_ids}
    for nid in sorted(node_ids, key=lambda x: depths[x]):
        if depths[nid] <= max_depth:
            continue
        cursor = nid
        while cursor in parent_of and depths[cursor] > max_depth - 1:
            cursor = parent_of[cursor]
        if cursor == nid:
            parent_of.pop(nid, None)
        else:
            parent_of[nid] = cursor
        depths = {n: _depth_of(n, parent_of) for n in node_ids}


# ---------------------------------------------------------------------------
# weight — 슬라이드가 그 개념에 배분한 양
# ---------------------------------------------------------------------------

def _slide_signals(slide_doc: SlideDoc | None) -> tuple[dict[int, int], dict[int, bool], int]:
    """SlideDoc 에서 글자 수·시각자료 신호를 뽑는다. 없으면 빈 값."""
    if slide_doc is None:
        return {}, {}, 0
    char_by = {s.slide_no: max(0, s.total_char_count) for s in slide_doc.slides}
    visual_by = {s.slide_no: bool(s.has_visual) for s in slide_doc.slides}
    return char_by, visual_by, sum(char_by.values())


def _concept_signals(doc: ConceptDoc) -> tuple[list[list[str]], dict[int, list[str]]]:
    """
    ConceptDoc 에서 개념 단위 신호의 재료를 토큰열로 뽑는다.

    slide_nos 가 같으면 char_share·has_visual 이 같아져 weight 동률이 났다 (실측).
    문서 전체 언급 목록과 장 제목은 개념마다 달라서 동률을 가른다.
    """
    entries = [
        norm_tokens(item)
        for s in doc.slides
        for item in list(s.concepts) + list(s.keywords)
    ]
    titles = {s.slide_no: norm_tokens(s.title) for s in doc.slides}
    return [e for e in entries if e], titles


def _mention_count(label: str, entries: list[list[str]]) -> int:
    """label 이 개념·키워드 목록에 몇 번 등장하나. 짧은 쪽이 긴 쪽에 안기면 인정."""
    tokens = label_tokens(label)
    if not tokens:
        return 0
    return sum(
        1 for e in entries if contains_tokens(e, tokens) or contains_tokens(tokens, e)
    )


def _title_hit(label: str, slide_nos: list[int], titles: dict[int, list[str]]) -> bool:
    """근거 장 제목에 label 이 등장하나. 제목에 오른 개념은 그 장의 주인공이다."""
    tokens = label_tokens(label)
    if not tokens:
        return False
    return any(contains_tokens(titles.get(n, []), tokens) for n in slide_nos)


def _raw_weight(
    node: ConceptNode,
    total_slides: int,
    char_by: dict[int, int],
    visual_by: dict[int, bool],
    total_char: int,
    mention_count: int,
    mention_share: float,
    title_hit: bool,
) -> float:
    """정규화 전 점수. weight_basis 도 여기서 채운다."""
    slide_count = len(node.slide_nos)
    char_share = (
        sum(char_by.get(n, 0) for n in node.slide_nos) / total_char if total_char else 0.0
    )
    has_visual = any(visual_by.get(n, False) for n in node.slide_nos)

    node.weight_basis = WeightBasis(
        slide_count=slide_count,
        char_share=round(char_share, 4),
        has_visual=has_visual,
        position=_position(node.slide_nos, total_slides),
        mention_count=mention_count,
        title_hit=title_hit,
    )

    slide_share = slide_count / total_slides if total_slides else 0.0
    score = (
        _W_IMPORTANCE * _IMPORTANCE_SCORE.get(node.importance, _IMPORTANCE_SCORE["support"])
        + _W_SLIDE_SHARE * min(1.0, slide_share)
        + _W_CHAR_SHARE * min(1.0, char_share)
        + _W_VISUAL * (1.0 if has_visual else 0.0)
        + _W_MENTION * min(1.0, mention_share)
        + _W_TITLE * (1.0 if title_hit else 0.0)
    )
    return max(0.0, score - _DEPTH_PENALTY * (node.depth - 1))


def _apply_weights(
    nodes: list[ConceptNode],
    doc: ConceptDoc,
    slide_doc: SlideDoc | None,
) -> None:
    """
    weight 를 채운다. 그래프 안에서 **상대적** 이라 최상위 개념이 1.0 이 된다.

    우선순위 비교가 목적이므로 절대값보다 서열이 중요하다.
    """
    char_by, visual_by, total_char = _slide_signals(slide_doc)
    entries, titles = _concept_signals(doc)
    mentions = [_mention_count(n.label, entries) for n in nodes]
    top_mention = max(mentions, default=0)

    raws = [
        _raw_weight(
            n,
            doc.total_slides,
            char_by,
            visual_by,
            total_char,
            mention_count=m,
            mention_share=(m / top_mention) if top_mention else 0.0,
            title_hit=_title_hit(n.label, n.slide_nos, titles),
        )
        for n, m in zip(nodes, mentions)
    ]
    top = max(raws, default=0.0)
    for node, raw in zip(nodes, raws):
        node.weight = round(min(1.0, raw / top), 3) if top > 0 else 0.0


# ---------------------------------------------------------------------------
# 조립
# ---------------------------------------------------------------------------

def _to_sections(raw_sections: list[dict], total_slides: int) -> list[Section]:
    sections: list[Section] = []
    for raw in raw_sections:
        role = str(raw.get("slide_role", "") or "")
        sections.append(Section(
            name=str(raw.get("name", "") or ""),
            slide_role=role if role in SLIDE_ROLES else SLIDE_ROLE_FALLBACK,
            slide_nos=_valid_slide_nos(raw.get("slide_nos"), total_slides),
        ))
    return sections


def _assemble(
    data: dict,
    doc: ConceptDoc,
    slide_doc: SlideDoc | None,
) -> tuple[list[ConceptNode], list[ConceptEdge], list[Section]]:
    """raw JSON → 불변식을 만족하는 (nodes, edges, sections)."""
    raw_nodes = [n for n in (data.get("nodes") or []) if isinstance(n, dict)]
    raw_edges = [e for e in (data.get("edges") or []) if isinstance(e, dict)]
    raw_sections = [s for s in (data.get("sections") or []) if isinstance(s, dict)]

    final_ids, alias = _assign_ids(raw_nodes)
    importance_by_slide = {s.slide_no: s.importance for s in doc.slides}

    nodes: list[ConceptNode] = []
    for node_id, raw in zip(final_ids, raw_nodes):
        slide_nos = _valid_slide_nos(raw.get("slide_nos"), doc.total_slides)
        nodes.append(ConceptNode(
            id=node_id,
            label=str(raw.get("label", "") or node_id),
            slide_nos=slide_nos,
            summary=str(raw.get("summary", "") or ""),
            importance=_inherit_importance(
                slide_nos, importance_by_slide, str(raw.get("importance", "core"))
            ),
        ))

    node_ids = {n.id for n in nodes}
    parent_of, relates = _normalize_edges(raw_edges, alias, node_ids)
    _break_parent_cycles(parent_of)
    _clamp_depth(parent_of, [n.id for n in nodes], MAX_GRAPH_DEPTH)

    for node in nodes:
        node.parent_id = parent_of.get(node.id)
        node.depth = _depth_of(node.id, parent_of)

    _apply_weights(nodes, doc, slide_doc)

    # edges 를 parent_of 에서 되짚어 만들어, parent_id/depth 와 어긋날 수 없게 한다
    edges = [
        ConceptEdge(from_id=parent, to_id=child, kind="parent")
        for child, parent in parent_of.items()
    ]
    edges += [e for e in relates if e.from_id in node_ids and e.to_id in node_ids]

    return nodes, edges, _to_sections(raw_sections, doc.total_slides)


# ---------------------------------------------------------------------------
# 루트 클램프 — 실측에서 28개 중 13개가 루트로 떠서 여전히 평평했다
# ---------------------------------------------------------------------------

def _attach_target(
    demoted: ConceptNode,
    kept: list[ConceptNode],
    relates: list[ConceptEdge],
) -> ConceptNode:
    """
    강등된 루트를 어느 남은 루트 밑에 붙일지 고른다.

    relates 이웃 > 슬라이드 겹침 > 최고 weight 순. 아무 관련 없는 개념을
    아무 데나 붙이는 것보다, 모델이 이미 적어 둔 연결을 근거로 쓴다.
    """
    linked = {e.from_id for e in relates if e.to_id == demoted.id}
    linked |= {e.to_id for e in relates if e.from_id == demoted.id}
    candidates = [k for k in kept if k.id in linked]

    if not candidates:
        overlaps = [(len(set(demoted.slide_nos) & set(k.slide_nos)), k) for k in kept]
        best = max((count for count, _ in overlaps), default=0)
        if best > 0:
            candidates = [k for count, k in overlaps if count == best]

    if not candidates:
        candidates = kept
    return sorted(candidates, key=lambda k: (-k.weight, k.id))[0]


def _clamp_roots(
    nodes: list[ConceptNode],
    edges: list[ConceptEdge],
    doc: ConceptDoc,
    slide_doc: SlideDoc | None,
) -> list[ConceptEdge]:
    """
    루트가 MAX_ROOTS 를 넘으면 weight 상위만 루트로 남기고 나머지를 그 밑에 붙인다.

    nodes 의 parent_id/depth/weight 를 제자리 갱신하고, 새 edges 를 돌려준다.
    상한 이하면 아무것도 바꾸지 않는다.
    """
    if MAX_ROOTS < 1:
        return edges
    roots = [n for n in nodes if n.parent_id is None]
    if len(roots) <= MAX_ROOTS:
        return edges

    ranked = sorted(roots, key=lambda n: (-n.weight, -len(n.slide_nos), n.id))
    kept, demoted = ranked[:MAX_ROOTS], ranked[MAX_ROOTS:]
    relates = [e for e in edges if e.kind == "relates"]
    parent_of = {e.to_id: e.from_id for e in edges if e.kind == "parent"}

    for node in demoted:
        parent_of[node.id] = _attach_target(node, kept, relates).id

    node_ids = [n.id for n in nodes]
    _clamp_depth(parent_of, node_ids, MAX_GRAPH_DEPTH)
    for node in nodes:
        node.parent_id = parent_of.get(node.id)
        node.depth = _depth_of(node.id, parent_of)
    _apply_weights(nodes, doc, slide_doc)          # 깊이 감점이 바뀌었으니 재계산

    new_edges = [
        ConceptEdge(from_id=parent, to_id=child, kind="parent")
        for child, parent in parent_of.items()
    ]
    # 강등된 루트를 relates 이웃 밑에 붙이면 같은 방향 relates 와 (from,to) 가
    # 겹칠 수 있다 (실측에서 발견). 위계로 승격된 쌍의 relates 는 지운다.
    parent_pairs = {(parent, child) for child, parent in parent_of.items()}
    return new_edges + [e for e in relates if (e.from_id, e.to_id) not in parent_pairs]


def _is_degenerate(nodes: list[ConceptNode], edges: list[ConceptEdge]) -> bool:
    """
    노드가 둘 이상인데 간선이 하나도 없으면 그래프가 아니다.

    실제 Solar 가 이런 응답을 주는 실행이 있었다 (전부 루트, 연결선 0개).
    """
    return len(nodes) >= 2 and not edges


def _call(
    engine: LLMProvider,
    doc: ConceptDoc,
    ctx: Context,
    slide_doc: SlideDoc | None,
    *,
    extra_system: str = "",
) -> tuple[list[ConceptNode], list[ConceptEdge], list[Section]]:
    raw = engine.complete(
        system=SYSTEM_PROMPT + extra_system,
        user=_build_user_prompt(doc, ctx),
        temperature=0.2,
        max_tokens=MAX_TOKENS,
    )
    try:
        data = extract_json_object(raw)
    except ValueError as e:
        raise GraphError(f"LLM 응답에서 그래프 JSON 을 찾지 못했습니다: {e}") from e
    return _assemble(data, doc, slide_doc)


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------

def build_graph(
    doc: ConceptDoc | dict,
    context: Context | dict | None = None,
    *,
    slide_doc: SlideDoc | dict | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> ConceptGraph:
    """
    ConceptDoc(+선택 Context, 선택 SlideDoc) → ConceptGraph.

    slide_doc 을 주면 weight 가 글자 수·시각자료까지 반영해 촘촘해진다.
    없으면 중요도와 걸친 장 수만으로 거칠게 계산한다.

    배치로 쪼개지 않는다. 위계는 발표 전체를 한 번에 봐야 정해지고,
    나눠 부르면 배치 경계에서 연결선을 잃는다.
    """
    if isinstance(doc, dict):
        doc = ConceptDoc.from_dict(doc)
    if not doc.slides:
        raise GraphError("ConceptDoc 에 슬라이드가 없습니다. F-06 결과를 먼저 확인하세요.")
    if isinstance(slide_doc, dict):
        slide_doc = SlideDoc.from_dict(slide_doc)

    if context is None:
        ctx = Context()
    elif isinstance(context, dict):
        ctx = Context.from_dict(context)
    else:
        ctx = context

    engine = llm if isinstance(llm, LLMProvider) else get_llm(llm, **(llm_kwargs or {}))

    try:
        nodes, edges, sections = _call(engine, doc, ctx, slide_doc)
    except GraphError:
        # 파싱 실패는 대부분 그 실행의 출력 문제다. 한 번은 다시 묻고, 또 깨지면 실패로 둔다
        nodes, edges, sections = _call(engine, doc, ctx, slide_doc, extra_system=JSON_RETRY_NUDGE)
    if _is_degenerate(nodes, edges):
        try:
            retry = _call(engine, doc, ctx, slide_doc, extra_system=RETRY_NUDGE)
        except GraphError:
            retry = None                      # 재시도가 깨지면 1차 결과를 쓴다
        if retry and not _is_degenerate(retry[0], retry[1]):
            nodes, edges, sections = retry

    edges = _clamp_roots(nodes, edges, doc, slide_doc)

    return ConceptGraph(
        file_name=doc.file_name,
        total_slides=doc.total_slides,
        nodes=nodes,
        edges=edges,
        sections=sections,
        model=engine.name,
    )
