"""
[F-07] 장 단위 개념을 발표 전체 기준 위계(트리)와 구획으로 묶는 모듈입니다.
ConceptDoc → ConceptTree. 이해 판정·confidence·근거 발화는 F-11 몫입니다.

    from chuckchuck.f07_tree import build_tree
    tree = build_tree(concept_doc, context, llm="solar")
"""

from __future__ import annotations

import os
import re

from ._json_text import extract_json_object
from .contracts import (
    SLIDE_ROLE_FALLBACK,
    SLIDE_ROLES,
    ConceptDoc,
    ConceptNode,
    ConceptTree,
    Context,
    Section,
    TreeError,
)
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm

MAX_TOKENS = int(os.environ.get("CHUCKCHUCK_TREE_MAX_TOKENS", "8192"))
MAX_CONCEPTS_PER_SLIDE = int(os.environ.get("CHUCKCHUCK_TREE_MAX_CONCEPTS", "6"))

#: 근거 슬라이드 중요도별 기본 가중치. weight 계산의 출발점.
_BASE_WEIGHT = {"core": 0.6, "support": 0.3}
_COVERAGE_BONUS = 0.2   # 여러 장에 걸친 개념일수록 가산
_DEPTH_PENALTY = 0.05   # 하위 개념일수록 감산

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

SYSTEM_PROMPT = """당신은 발표 구조 분석가다.
슬라이드별로 뽑아 둔 개념 목록을 받아, 발표 '전체' 기준의 개념 위계와 구획을 만든다.

규칙:
1. 자료에 없는 개념을 지어내지 마라. 주어진 개념·주제 안에서만 묶어라.
2. 비슷한 개념이 여러 장에 나오면 하나의 노드로 합치고 slide_nos 에 장 번호를 모두 적어라.
3. parent_id 로 위계를 만든다. 가장 큰 개념은 parent_id 를 null 로 둔다.
4. 위계는 3단계를 넘기지 마라. 애매하면 얕게 두어라.
5. id 는 영소문자·숫자·하이픈만 쓴다. 짧고 의미 있게. 트리 안에서 유일해야 한다.
6. sections 는 발표를 앞에서 뒤로 훑어 구획으로 나눈 것이다.
   slide_role 은 cover, intro, body, conclusion, closing 중 하나만 쓴다.
7. 개념이 잘 됐는지 못 됐는지 판정하지 마라. 그건 다음 단계 일이다.
8. 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마:
{
  "nodes": [
    {
      "id": "contrast",
      "label": "개념 이름",
      "parent_id": null,
      "slide_nos": [4, 5],
      "summary": "한 줄 설명",
      "importance": "core"
    }
  ],
  "sections": [
    { "name": "본론 — 제안 방법", "slide_role": "body", "slide_nos": [6, 7, 8] }
  ]
}
"""


# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------

def _build_user_prompt(doc: ConceptDoc, ctx: Context) -> str:
    """ConceptDoc 전체를 한 번에 보여 준다. 위계는 전역 시야가 있어야 정해진다."""
    parts = [
        "[TASK] concept-tree",
        ctx.to_prompt_block(),
        "",
        f"파일명: {doc.file_name}",
        f"총 슬라이드: {doc.total_slides}",
        "",
        "아래는 슬라이드별로 이미 뽑아 둔 개념이다. 이걸 묶어 트리와 구획을 만들어라.",
    ]
    for s in doc.slides:
        parts.append(f"### 슬라이드 {s.slide_no}: {s.title or '(제목 없음)'}")
        if s.topic:
            parts.append(f"주제: {s.topic}")
        if s.keywords:
            parts.append(f"키워드: {', '.join(s.keywords)}")
        for c in s.concepts[:MAX_CONCEPTS_PER_SLIDE]:
            parts.append(f"- {c}")
        parts.append(f"중요도: {s.importance}")
        parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 후처리 — SCHEMA.md 6-B 의 불변식을 여기서 보장한다
# ---------------------------------------------------------------------------

def _slug(value: str) -> str:
    """id 후보를 영소문자·숫자·하이픈으로. 남는 게 없으면 빈 문자열."""
    return _SLUG_STRIP.sub("-", str(value or "").lower()).strip("-")


def _assign_ids(raw_nodes: list[dict]) -> tuple[list[str], dict[str, str]]:
    """
    최종 id 목록과 '모델이 쓴 원래 id → 최종 id' 대응표를 만든다.

    parent_id 는 원래 id 로 적혀 있으므로, 대응표가 있어야 부모를 다시 찾는다.
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
        # 같은 원래 id 가 여러 번 나오면 첫 번째가 부모 참조를 가져간다
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


def _break_cycles(nodes: list[ConceptNode]) -> None:
    """부모 체인을 따라가다 자기 자신을 다시 만나면 그 고리를 끊어 루트로 만든다."""
    by_id = {n.id: n for n in nodes}
    for node in nodes:
        seen = {node.id}
        cursor = node
        while cursor.parent_id:
            if cursor.parent_id in seen:
                cursor.parent_id = None
                break
            seen.add(cursor.parent_id)
            cursor = by_id[cursor.parent_id]


def _assign_depths(nodes: list[ConceptNode]) -> None:
    """모델이 준 depth 는 버리고 parent_id 체인 길이로 다시 센다. 순환 제거 뒤에 부른다."""
    by_id = {n.id: n for n in nodes}
    for node in nodes:
        depth = 1
        cursor = node
        while cursor.parent_id:
            depth += 1
            cursor = by_id[cursor.parent_id]
        node.depth = depth


def _inherit_importance(slide_nos: list[int], by_slide: dict[int, str], fallback: str) -> str:
    """근거 슬라이드 중 하나라도 core 면 core, 전부 support 면 support."""
    marks = [by_slide[n] for n in slide_nos if n in by_slide]
    if not marks:
        return fallback if fallback in ("core", "support") else "core"
    return "core" if "core" in marks else "support"


def _weight(importance: str, slide_nos: list[int], depth: int, total_slides: int) -> float:
    """중요도 + 몇 장에 걸치는지 + 얼마나 깊은지로 0.0~1.0 가중치."""
    base = _BASE_WEIGHT.get(importance, _BASE_WEIGHT["support"])
    coverage = len(slide_nos) / max(1, total_slides)
    raw = base + _COVERAGE_BONUS * coverage - _DEPTH_PENALTY * (depth - 1)
    return round(min(1.0, max(0.0, raw)), 3)


def _to_nodes(raw_nodes: list[dict], doc: ConceptDoc) -> list[ConceptNode]:
    final_ids, alias = _assign_ids(raw_nodes)
    importance_by_slide = {s.slide_no: s.importance for s in doc.slides}

    nodes: list[ConceptNode] = []
    for node_id, raw in zip(final_ids, raw_nodes):
        raw_parent = raw.get("parent_id")
        parent_id = alias.get(str(raw_parent)) if raw_parent else None
        if parent_id == node_id:      # 자기 자신을 부모로 지목한 경우
            parent_id = None
        slide_nos = _valid_slide_nos(raw.get("slide_nos"), doc.total_slides)
        nodes.append(ConceptNode(
            id=node_id,
            label=str(raw.get("label", "") or node_id),
            parent_id=parent_id,
            slide_nos=slide_nos,
            summary=str(raw.get("summary", "") or ""),
            importance=_inherit_importance(
                slide_nos,
                importance_by_slide,
                str(raw.get("importance", "core")),
            ),
        ))

    _break_cycles(nodes)
    _assign_depths(nodes)
    for node in nodes:
        node.weight = _weight(node.importance, node.slide_nos, node.depth, doc.total_slides)
    return nodes


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


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------

def build_tree(
    doc: ConceptDoc | dict,
    context: Context | dict | None = None,
    *,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> ConceptTree:
    """
    ConceptDoc(+선택 Context) → ConceptTree.

    배치로 쪼개지 않는다. 위계는 발표 전체를 한 번에 봐야 정해지고,
    나눠 부르면 배치 경계에서 부모를 잃는다.
    """
    if isinstance(doc, dict):
        doc = ConceptDoc.from_dict(doc)
    if not doc.slides:
        raise TreeError("ConceptDoc 에 슬라이드가 없습니다. F-06 결과를 먼저 확인하세요.")

    if context is None:
        ctx = Context()
    elif isinstance(context, dict):
        ctx = Context.from_dict(context)
    else:
        ctx = context

    engine = llm if isinstance(llm, LLMProvider) else get_llm(llm, **(llm_kwargs or {}))

    raw = engine.complete(
        system=SYSTEM_PROMPT,
        user=_build_user_prompt(doc, ctx),
        temperature=0.2,
        max_tokens=MAX_TOKENS,
    )
    try:
        data = extract_json_object(raw)
    except ValueError as e:
        raise TreeError(f"LLM 응답에서 트리 JSON 을 찾지 못했습니다: {e}") from e

    raw_nodes = [n for n in (data.get("nodes") or []) if isinstance(n, dict)]
    raw_sections = [s for s in (data.get("sections") or []) if isinstance(s, dict)]

    return ConceptTree(
        file_name=doc.file_name,
        total_slides=doc.total_slides,
        nodes=_to_nodes(raw_nodes, doc),
        sections=_to_sections(raw_sections, doc.total_slides),
        model=engine.name,
    )
