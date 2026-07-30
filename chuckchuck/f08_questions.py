"""
[F-08] 발표가 끝난 뒤 "이거 물어보면 답할 수 있나" 를 연습시키는 모듈입니다.
ConceptGraph(+선택 AlignmentDoc·FlowDiff) → QaTriage → QuestionDoc.

F-11 과 같은 철학입니다 — **어떤 개념을 물을지는 코드가 정하고 LLM 은 문장만 씁니다.**
리포트가 "누락" 이라고 말한 개념과 질문이 어긋나면 사용자가 두 화면을 믿을 수 없기
때문입니다. 후보 선정·순위·근거(source)는 이미 계산된 결정적 신호에서만 나옵니다.

LLM 을 두 번 부릅니다. 개념의 **중요도**는 F-07 weight·F-11 verdict 로 이미 알지만,
"이게 심사위원한테 실제로 찔릴 질문인가 · 함정을 팔 수 있나" 는 코드가 모릅니다.
그 판단만 1차(triage)에 맡기고, 2차는 문장 생성만 맡깁니다.

    from chuckchuck.f08_questions import triage_questions, build_questions
    triage = triage_questions(graph, alignment, flow, context, llm="solar")
    doc = build_questions(graph, triage, track="5", alignment=alignment, llm="solar")

triage 는 트랙과 무관하므로 **세션에 한 번만** 만들고 재사용합니다.
1/5/10분을 바꿔도 순위가 흔들리지 않고, 문장 생성 1콜만 더 듭니다.
"""

from __future__ import annotations

import os

from ._json_text import extract_json_object
from .contracts import (
    QA_SEVERITIES,
    QA_SOURCE_FALLBACK,
    QA_SOURCES,
    QA_TEXT_MAX,
    QA_TRACK_FALLBACK,
    QA_TRACK_LIMITS,
    QA_TRACK_TRAPS,
    QA_TRACKS,
    AlignmentDoc,
    ConceptGraph,
    ConceptNode,
    Context,
    FlowDiff,
    QaTriage,
    Question,
    QuestionDoc,
    QuestionError,
    Transcript,
    TriageMark,
)
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm

MAX_TOKENS = int(os.environ.get("CHUCKCHUCK_QUESTION_MAX_TOKENS", "4096"))

#: 심사에 올릴 후보 수. 가장 긴 트랙 상한의 두 배까지만 본다 —
#: 어차피 못 물어볼 개념까지 LLM 에 보내면 프롬프트만 길어지고 판단이 흐려진다.
CANDIDATE_LIMIT = max(QA_TRACK_LIMITS.values()) * 2

#: slide_nos 가 빈 노드는 순서상 맨 뒤로 (f11_flow 와 같은 관례).
_NO_SLIDE = 10 ** 9

#: QA_SOURCES 순서가 곧 우선순위다 (모순 > 누락 > 흐름 결손 > 자료 비중).
_SOURCE_RANK = {source: rank for rank, source in enumerate(QA_SOURCES)}

#: weak_flow 로 볼 FlowDiff 이슈. good_link 는 잘한 것이라 질문 근거가 아니다.
_WEAK_FLOW_KINDS = ("missing_link", "order_jump")

#: LLM 이 severity 를 안 줬을 때의 결정적 폴백 (source 기반).
_SEVERITY_BY_SOURCE = {"contradiction": 1, "missing": 1, "weak_flow": 2}

#: 자료가 이만큼 힘준 개념은 근거가 core_weight 여도 '보통' 으로 본다.
HEAVY_WEIGHT = float(os.environ.get("CHUCKCHUCK_QA_HEAVY_WEIGHT", "0.5"))

#: 개념 하나당 프롬프트에 실을 발화 발췌 길이. 전체 발화를 다 실으면 개념이 묻힌다.
SPEECH_EXCERPT_MAX = int(os.environ.get("CHUCKCHUCK_QA_SPEECH_EXCERPT_MAX", "300"))

#: 한 개념에 붙여 보여 줄 이웃 개념 수. 그래프가 넓어도 프롬프트가 안 터지게 자른다.
NEIGHBOR_MAX = 5

#: severity=1(치명) 을 줄 후보 비율. 실측에서 Solar 가 후보 16개 중 11개에 치명을
#: 몰아줘 순위가 뭉개졌다 — 배분 목표를 개수로 못박아 변별을 강제한다.
#: 코드가 강제로 깎지는 않는다. LLM 판정을 덮어쓰면 그 판단을 맡긴 의미가 없다.
SEVERE_SHARE = float(os.environ.get("CHUCKCHUCK_QA_SEVERE_SHARE", "0.34"))

#: trap=true 를 줄 후보 비율. 같은 실측에서 16개 중 11개가 함정이었다.
TRAP_SHARE = float(os.environ.get("CHUCKCHUCK_QA_TRAP_SHARE", "0.25"))


def _quota(total: int, share: float) -> int:
    """후보 수에 비례한 배분 목표. 최소 1개는 준다 (후보가 하나뿐일 수 있다)."""
    return max(1, round(total * share))

#: why 를 LLM 이 안 줬을 때 채워 넣는 결정적 문장. 근거(source)가 곧 이유다.
_WHY_BY_SOURCE = {
    "contradiction": "발표 내용이 자료와 어긋난 지점이라 확인이 필요해요",
    "missing": "자료에는 있는데 발표에서 설명하지 않은 개념이에요",
    "weak_flow": "다른 개념과의 연결이 발표에서 드러나지 않았어요",
    "core_weight": "자료가 가장 큰 비중을 둔 핵심 개념이에요",
}

TRIAGE_SYSTEM_PROMPT = """당신은 발표 심사위원의 질문을 예측하는 코치다.
'개념 목록'(발표 자료에서 뽑은 개념들)을 보고, 개념마다 **질문 가치**를 심사한다.

너의 판단은 **순위를 매기는 데 그대로 쓰인다.** 1분짜리 짧은 코스에서는 네가
severity=1 을 준 개념 하나만 물어보게 된다. 그러니 severity 는 **줄 세우기**지
칭찬이 아니다. 전부 1을 주면 순위가 사라져 아무 개념이나 뽑히게 된다.

개념마다 다음 셋만 판단하라:

- severity: 이 개념을 못 답했을 때의 타격.
  1 (치명)   못 답하면 발표의 핵심 주장이 무너진다. 이 발표가 왜 성립하는지가
             이 개념에 걸려 있다.
  2 (보통)   못 답하면 설명이 얕아 보이지만 주장 자체는 선다. 근거·사례·수치류.
  3 (가벼움) 못 답해도 넘어간다. 배경 설명·용어 소개·부수적 개념.

- trap: 자료와 어긋난 주장으로 찔러 볼 수 있는가 (true/false).
  **자료에 뒤집을 대상이 실제로 있을 때만** true 다 — 수치, 인과("A 때문에 B"),
  비교("X 가 Y 보다"), 조건("~할 때만") 중 하나가 개념 안에 들어 있어야 한다.
  정의·용어 소개·나열처럼 반대로 말해 볼 거리가 없으면 false 다.
  애매하면 false 로 둬라. 함정을 남발하면 연습이 말장난이 된다.

- angle: 어느 각도로 물을지 한 줄. 질문 문장이 아니라 **각도**만 적어라.
  (예: "왜 다른 방식 대신 이걸 골랐는지", "이 수치의 출처와 측정 조건")

규칙:
1. marks 에는 개념 목록의 id 만 쓴다. id 를 지어내지 마라 — 버려진다.
2. 개념 목록의 모든 id 를 한 번씩 판단하라.
3. **아래 '배분' 에 적힌 개수를 지켜라.** 개념 목록 순서와 무관하게, 전체를 다 본 뒤
   가장 치명적인 것부터 골라 1 을 배정하라.
4. '근거' 가 모순·누락인 개념은 이미 문제가 확인된 것이다. severity 를 후하게 주지 마라.
5. 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마:
{
  "marks": [
    { "node_id": "joint", "severity": 1, "trap": true,
      "angle": "왜 다른 정렬 방식 대신 이걸 골랐는지" }
  ]
}
"""

QUESTION_SYSTEM_PROMPT = """당신은 발표 심사위원이다.
'질문 대상' 개념마다 실제로 던질 **질문 문장**을 쓴다.

무엇을 물을지는 이미 정해져 있다. 너는 대상을 바꾸지 않는다.
개념마다 다음 셋만 쓴다:

- question: 심사위원이 실제로 말할 질문 한 문장. 존댓말. 200자 이내.
  주어진 '각도' 를 살려라. 자료에 없는 사실을 지어내지 마라.
- why: 왜 이걸 묻는지 한 줄. 발표자에게 보여 줄 설명이다.
- hint: 막혔을 때 줄 힌트 한 줄. 답을 그대로 말하지 말고 방향만 준다.

trap=true 인 개념은 **자료와 어긋난 주장을 얹어** 찔러 보는 질문으로 쓴다
("~라고 하셨는데, 사실 반대 아닌가요?" 꼴). trap=false 면 그냥 묻는다.

규칙:
1. questions 에는 '질문 대상' 의 node_id 만 쓴다. 지어내면 버려진다.
2. 대상마다 정확히 하나씩. 한 개념에 두 질문을 쓰지 마라.
3. 발표 태도·말투·발음을 묻지 마라. 내용만 묻는다.
4. 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마:
{
  "questions": [
    { "node_id": "joint", "question": "질문 한 문장",
      "why": "왜 묻는지 한 줄", "hint": "방향만 주는 힌트" }
  ]
}
"""

#: 응답이 복구 불가능한 JSON 일 때 한 번 더 물어볼 때 덧붙이는 말 (f11_align 과 같은 전략).
JSON_RETRY_NUDGE = """
[재요청] 직전 응답이 완전한 JSON 객체가 아니어서 버렸다.
코드펜스·주석·말머리·말끝 문장 없이, 출력 스키마 그대로의 JSON 객체 하나만 다시 출력하라.
"""


# ---------------------------------------------------------------------------
# 후보 선정 — 전부 코드. LLM 이 관여하지 않는다.
# ---------------------------------------------------------------------------

def _source_by_node(
    graph: ConceptGraph,
    alignment: AlignmentDoc | None,
    flow: FlowDiff | None,
) -> dict[str, str]:
    """
    노드마다 '왜 물을 만한가' 를 하나씩 정한다.

    여러 근거가 겹치면 우선순위가 높은 것이 이긴다 (모순 > 누락 > 흐름 결손 > 자료 비중).
    alignment·flow 가 없으면 전부 core_weight 다 — 녹음 없이 자료만 올린 경로다.
    """
    found: dict[str, str] = {n.id: QA_SOURCE_FALLBACK for n in graph.nodes}

    def claim(node_id: str, source: str) -> None:
        if node_id not in found:
            return
        if _SOURCE_RANK[source] < _SOURCE_RANK[found[node_id]]:
            found[node_id] = source

    if flow is not None:
        for issue in flow.issues:
            if issue.kind not in _WEAK_FLOW_KINDS:
                continue
            for node_id in issue.node_ids:
                claim(node_id, "weak_flow")

    if alignment is not None:
        for item in alignment.items:
            if item.verdict in ("contradiction", "missing"):
                claim(item.node_id, item.verdict)

    return found


def _ordered_candidates(
    graph: ConceptGraph,
    alignment: AlignmentDoc | None,
    flow: FlowDiff | None,
) -> list[tuple[ConceptNode, str]]:
    """
    질문 후보를 결정적 우선순위로 정렬해 CANDIDATE_LIMIT 까지 자른다.

    근거 우선순위 → 자료 weight 내림차순 → 앞 슬라이드 → id 순.
    뒤 두 단계는 동률을 깨려고 있다 — 같은 그래프면 언제나 같은 순서가 나온다.
    """
    source_of = _source_by_node(graph, alignment, flow)

    def sort_key(node: ConceptNode) -> tuple:
        return (
            _SOURCE_RANK[source_of[node.id]],
            -node.weight,
            min(node.slide_nos) if node.slide_nos else _NO_SLIDE,
            node.id,
        )

    ranked = sorted(graph.nodes, key=sort_key)[:CANDIDATE_LIMIT]
    return [(node, source_of[node.id]) for node in ranked]


def _fallback_severity(source: str, weight: float) -> int:
    """LLM 이 severity 를 안 줬을 때. 이미 문제가 확인된 근거일수록 치명으로 본다."""
    if source in _SEVERITY_BY_SOURCE:
        return _SEVERITY_BY_SOURCE[source]
    return 2 if weight >= HEAVY_WEIGHT else 3


# ---------------------------------------------------------------------------
# 공용 헬퍼
# ---------------------------------------------------------------------------

def _clip(text: str) -> str:
    """QA_TEXT_MAX 로 자른다. 화면 말풍선이 감당하는 길이다."""
    stripped = (text or "").strip()
    if len(stripped) <= QA_TEXT_MAX:
        return stripped
    return stripped[: QA_TEXT_MAX - 1].rstrip() + "…"


def _as_graph(graph: ConceptGraph | dict) -> ConceptGraph:
    if isinstance(graph, dict):
        graph = ConceptGraph.from_dict(graph)
    if not graph.nodes:
        raise QuestionError("ConceptGraph 에 노드가 없습니다. F-07 결과를 먼저 확인하세요.")
    return graph


def _as_context(context: Context | dict | None) -> Context:
    if context is None:
        return Context()
    if isinstance(context, dict):
        return Context.from_dict(context)
    return context


def _engine(llm: str | LLMProvider | None, llm_kwargs: dict | None) -> LLMProvider:
    return llm if isinstance(llm, LLMProvider) else get_llm(llm, **(llm_kwargs or {}))


def _call(engine: LLMProvider, system: str, user: str) -> dict:
    """LLM 한 번 부르고 JSON 객체로. 파싱 실패는 QuestionError 로 감싼다."""
    raw = engine.complete(system=system, user=user, temperature=0.3, max_tokens=MAX_TOKENS)
    try:
        return extract_json_object(raw)
    except ValueError as e:
        raise QuestionError(f"LLM 응답에서 질문 JSON 을 찾지 못했습니다: {e}") from e


def _call_with_retry(engine: LLMProvider, system: str, user: str) -> dict:
    """
    파싱 실패는 대부분 그 실행의 출력 문제다. 한 번은 다시 묻고, 또 깨지면 실패로 둔다.

    f11_align 과 같은 전략이다 — 무한 재시도로 비용을 태우지 않는다.
    """
    try:
        return _call(engine, system, user)
    except QuestionError:
        return _call(engine, system + JSON_RETRY_NUDGE, user)


def _node_lines(pairs: list[tuple[ConceptNode, str]]) -> list[str]:
    """'- (id) 이름 [S1,2] w=0.8 · 근거=missing — 요약' 줄. MockLLM 도 이 꼴을 읽는다."""
    lines = []
    for node, source in pairs:
        nos = ",".join(str(n) for n in node.slide_nos)
        line = f"- ({node.id}) {node.label} [S{nos}] w={node.weight} · 근거={source}"
        if node.summary:
            line += f" — {node.summary}"
        lines.append(line)
    return lines


def _relation_line(node: ConceptNode, graph: ConceptGraph) -> str:
    """
    이 개념이 그래프에서 어디에 있는지 한 줄.

    edges 가 진실이다. 경로는 parent 간선만 따라간 **트리 뷰**(노드당 parent 최대 1개),
    연결은 relates 까지 포함한 **그래프 뷰**다 — 트리는 그래프의 부분집합이다.
    심사위원 질문은 "이게 저것과 무슨 관계인가" 로 들어오는 일이 많아서,
    개념을 홀로 주면 LLM 이 사전식 정의 질문만 쓴다.
    """
    parts = []
    path = [n.label for n in graph.path_of(node.id)]
    if len(path) > 1:
        parts.append("경로=" + " > ".join(path))

    # 무거운 이웃부터 자른다 — 상한에 걸릴 때 사소한 개념이 살아남으면 안 된다.
    # id 로 동률을 깨서 같은 그래프면 언제나 같은 줄이 나온다.
    ranked = sorted(graph.neighbors_of(node.id), key=lambda n: (-n.weight, n.id))
    if ranked:
        shown = ", ".join(n.label for n in ranked[:NEIGHBOR_MAX])
        if len(ranked) > NEIGHBOR_MAX:
            shown += f" 외 {len(ranked) - NEIGHBOR_MAX}개"
        parts.append("연결=" + shown)
    return " · ".join(parts)


def _speech_excerpt(node: ConceptNode, transcript: Transcript | None) -> str:
    """이 개념의 근거 장에서 실제로 한 말. Transcript.by_slide 를 slide_no 로 조인한다."""
    if transcript is None:
        return ""
    said = " ".join(
        text
        for text in (transcript.text_for_slide(no).strip() for no in node.slide_nos)
        if text
    )
    if len(said) <= SPEECH_EXCERPT_MAX:
        return said
    return said[: SPEECH_EXCERPT_MAX - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# 1차 · triage
# ---------------------------------------------------------------------------

def _build_triage_prompt(
    graph: ConceptGraph,
    pairs: list[tuple[ConceptNode, str]],
    alignment: AlignmentDoc | None,
    transcript: Transcript | None,
    ctx: Context,
) -> str:
    parts = [
        "[TASK] qa-triage",
        ctx.to_prompt_block(),
        "",
        f"파일명: {graph.file_name}",
        f"총 슬라이드: {graph.total_slides}",
        "",
        f"## 배분 — 후보 {len(pairs)}개 중",
        f"- severity=1(치명): **최대 {_quota(len(pairs), SEVERE_SHARE)}개**. "
        f"나머지는 2 나 3 이다. 3(가벼움)도 반드시 쓴다.",
        f"- trap=true(함정): **최대 {_quota(len(pairs), TRAP_SHARE)}개**. "
        f"뒤집을 수치·인과·비교 주장이 실제로 있는 개념만.",
        "",
        "## 개념 목록 — 심사 대상. marks 에 이 id 가 전부 나와야 한다",
        "(id) 개념이름 [근거 슬라이드] w=자료가 배분한 중요도 · 근거=후보가 된 이유",
        "경로는 위계(parent), 연결은 그 밖의 논리 관계(relates)다.",
        "",
    ]
    for line, (node, _) in zip(_node_lines(pairs), pairs):
        parts.append(line)
        relation = _relation_line(node, graph)
        if relation:
            parts.append(f"    {relation}")

    judged = {i.node_id: i for i in alignment.items} if alignment else {}
    spoken = []
    for node, _ in pairs:
        said = _speech_excerpt(node, transcript)
        item = judged.get(node.id)
        if not said and (item is None or not item.evidence.strip()):
            continue
        verdict = f"({item.verdict}) " if item is not None else ""
        spoken.append(f"- ({node.id}) {verdict}{said or item.evidence}")
    if spoken:
        parts += ["", "## 발표에서 실제로 한 말 (근거 장의 발화)", ""] + spoken
    return "\n".join(parts)


def _normalize_marks(
    raw_marks: list[dict],
    pairs: list[tuple[ConceptNode, str]],
) -> list[TriageMark]:
    """
    raw 심사를 후보마다 정확히 1개씩으로 정리한다.

    - 후보 밖 node_id 는 버린다. 같은 node_id 가 여러 번 오면 첫 번째만
    - severity 가 enum 밖이거나 없으면 source 기반 결정적 폴백
    - node_id·source·rank·doc_weight 는 **코드가 채운다** (LLM 값을 쓰지 않는다)
    """
    candidate_ids = {node.id for node, _ in pairs}
    judged: dict[str, dict] = {}
    for raw in raw_marks:
        node_id = str(raw.get("node_id", "") or "")
        if node_id in candidate_ids and node_id not in judged:
            judged[node_id] = raw

    marks: list[TriageMark] = []
    for node, source in pairs:
        raw = judged.get(node.id) or {}
        try:
            severity = int(raw.get("severity", 0))
        except (TypeError, ValueError):
            severity = 0
        if severity not in QA_SEVERITIES:
            severity = _fallback_severity(source, node.weight)

        marks.append(TriageMark(
            node_id=node.id,
            severity=severity,
            trap=bool(raw.get("trap", False)),
            angle=_clip(str(raw.get("angle", "") or "")),
            source=source,
            rank=0,                      # 아래에서 severity 를 반영해 다시 매긴다
            doc_weight=node.weight,
        ))
    return _rerank(marks, pairs)


def _rerank(
    marks: list[TriageMark],
    pairs: list[tuple[ConceptNode, str]],
) -> list[TriageMark]:
    """
    LLM 이 매긴 severity 를 반영해 최종 순위(rank)를 다시 매긴다.

    **이 재정렬이 triage 를 따로 부르는 이유다.** rank 가 곧 트랙 상한에 들어갈
    순서이므로, 여기서 severity 를 안 쓰면 1차 호출은 화면 표시용 장식이 되고
    1분 트랙이 '가벼움' 개념을 물어보게 된다.

    다만 source 는 severity 보다 위다. 모순·누락은 이미 **확인된 사실**이고
    severity 는 LLM 의 짐작이라, 리포트가 "누락" 이라 말한 개념을 짐작이 밀어내면
    두 화면이 어긋난다. 그래서 근거 안에서만 severity 가 순위를 정한다.

    나머지 키(자료 weight → 앞 슬라이드 → id)는 동률을 깨기 위한 것이다 —
    같은 triage 응답이면 언제나 같은 순서가 나온다.
    """
    slide_of = {
        node.id: (min(node.slide_nos) if node.slide_nos else _NO_SLIDE)
        for node, _ in pairs
    }
    ordered = sorted(
        marks,
        key=lambda m: (
            _SOURCE_RANK[m.source],
            m.severity,
            -m.doc_weight,
            slide_of[m.node_id],
            m.node_id,
        ),
    )
    for rank, mark in enumerate(ordered, start=1):
        mark.rank = rank
    return ordered


def triage_questions(
    graph: ConceptGraph | dict,
    alignment: AlignmentDoc | dict | None = None,
    flow: FlowDiff | dict | None = None,
    context: Context | dict | None = None,
    *,
    transcript: Transcript | dict | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> QaTriage:
    """
    ConceptGraph(+선택 AlignmentDoc·FlowDiff·Context·Transcript) → QaTriage.

    후보와 순위(rank)·근거(source)는 코드가 결정적으로 정하고,
    LLM 은 severity·trap·angle 만 채운다. 빠뜨린 후보는 결정적 폴백으로 메운다.

    개념은 홀로 주지 않는다 — parent 경로(트리 뷰)와 relates 이웃(그래프 뷰)을 함께 준다.
    심사위원 질문은 "이게 저것과 무슨 관계인가" 로 들어오기 때문이다.
    transcript 를 주면 근거 장의 실제 발화까지 붙어 함정 판단이 정확해진다
    (Transcript.by_slide 를 slide_no 로 조인).

    alignment·flow·transcript 없이 그래프만으로도 동작한다 — 녹음 없이 자료만 올린
    경로에서 근거는 전부 core_weight 가 되고 자료 weight 순으로 후보가 나온다.
    트랙과 무관하므로 세션에 한 번만 만들어 재사용하면 된다.
    """
    graph = _as_graph(graph)
    if isinstance(alignment, dict):
        alignment = AlignmentDoc.from_dict(alignment)
    if isinstance(flow, dict):
        flow = FlowDiff.from_dict(flow)
    if isinstance(transcript, dict):
        transcript = Transcript.from_dict(transcript)
    ctx = _as_context(context)

    pairs = _ordered_candidates(graph, alignment, flow)
    engine = _engine(llm, llm_kwargs)

    data = _call_with_retry(
        engine,
        TRIAGE_SYSTEM_PROMPT,
        _build_triage_prompt(graph, pairs, alignment, transcript, ctx),
    )
    raw_marks = [m for m in (data.get("marks") or []) if isinstance(m, dict)]

    return QaTriage(
        file_name=graph.file_name,
        total_slides=graph.total_slides,
        marks=_normalize_marks(raw_marks, pairs),
        model=engine.name,
    )


# ---------------------------------------------------------------------------
# 2차 · 질문 문장
# ---------------------------------------------------------------------------

def _pick_marks(marks: list[TriageMark], track: str) -> tuple[list[TriageMark], list[str]]:
    """
    트랙 상한만큼 rank 순으로 고르고, 함정 개수를 트랙 허용치로 깎는다.

    1분 트랙은 방어 연습할 시간이 없어 함정이 0개다 (QA_TRACK_TRAPS).
    상한에서 밀린 개념은 deferred 로 돌려준다 — "더 길게 하면 이것도 물어요" 안내용이다.
    """
    ordered = sorted(marks, key=lambda m: (m.rank, m.node_id))
    limit = QA_TRACK_LIMITS[track]
    picked, deferred = ordered[:limit], [m.node_id for m in ordered[limit:]]

    trap_budget = QA_TRACK_TRAPS[track]
    capped: list[TriageMark] = []
    for mark in picked:
        trap = mark.trap and trap_budget > 0
        if trap:
            trap_budget -= 1
        # 새 객체로 만든다 — 원본 triage 는 캐시돼 트랙마다 재사용되므로 건드리면 안 된다
        capped.append(TriageMark(
            node_id=mark.node_id,
            severity=mark.severity,
            trap=trap,
            angle=mark.angle,
            source=mark.source,
            rank=mark.rank,
            doc_weight=mark.doc_weight,
        ))
    return capped, deferred


def _build_question_prompt(
    graph: ConceptGraph,
    marks: list[TriageMark],
    by_id: dict[str, ConceptNode],
    alignment: AlignmentDoc | None,
    transcript: Transcript | None,
    ctx: Context,
) -> str:
    parts = [
        "[TASK] qa-questions",
        ctx.to_prompt_block(),
        "",
        f"파일명: {graph.file_name}",
        f"총 슬라이드: {graph.total_slides}",
        "",
        "## 질문 대상 — questions 에 이 id 가 전부 나와야 한다",
        "(id) 개념이름 [근거 슬라이드] · 치명도 · 함정여부 · 각도",
        "경로는 위계(parent), 연결은 그 밖의 논리 관계(relates)다.",
        "연결된 개념과의 관계를 파고드는 질문이 정의를 묻는 질문보다 낫다.",
        "",
    ]
    judged = {i.node_id: i for i in alignment.items} if alignment else {}
    for mark in marks:
        node = by_id[mark.node_id]
        nos = ",".join(str(n) for n in node.slide_nos)
        line = (
            f"- ({node.id}) {node.label} [S{nos}] · 치명도={mark.severity}"
            f" · 함정={'예' if mark.trap else '아니오'}"
        )
        if mark.angle:
            line += f" · 각도={mark.angle}"
        if node.summary:
            line += f" — {node.summary}"
        parts.append(line)

        relation = _relation_line(node, graph)
        if relation:
            parts.append(f"    {relation}")

        said = _speech_excerpt(node, transcript)
        item = judged.get(node.id)
        if said or (item is not None and item.evidence.strip()):
            verdict = f"({item.verdict}) " if item is not None else ""
            parts.append(f"    발표에서 한 말{verdict}: {said or item.evidence}")
    return "\n".join(parts)


def _fallback_text(node: ConceptNode, mark: TriageMark) -> tuple[str, str, str]:
    """LLM 이 이 개념을 빠뜨렸을 때 쓰는 결정적 문장 3종 (question, why, hint)."""
    if mark.angle:
        question = f"{node.label}: {mark.angle} — 설명해 주시겠어요?"
    else:
        question = f"{node.label}: 이 개념의 핵심과 자료에 넣은 근거를 설명해 주시겠어요?"

    why = _WHY_BY_SOURCE.get(mark.source, _WHY_BY_SOURCE[QA_SOURCE_FALLBACK])

    if node.slide_nos:
        nos = ", ".join(str(n) for n in node.slide_nos)
        hint = f"{nos}장에서 이 개념을 어떻게 설명했는지 떠올려 보세요"
    else:
        hint = "자료에서 이 개념을 왜 다뤘는지부터 짚어 보세요"
    return question, why, hint


def _normalize_questions(
    raw_questions: list[dict],
    marks: list[TriageMark],
    by_id: dict[str, ConceptNode],
) -> list[Question]:
    """
    raw 질문을 대상마다 정확히 1개씩으로 정리한다.

    - 대상 밖 node_id 는 버린다. 같은 node_id 가 여러 번 오면 첫 번째만
    - 빠진 대상은 결정적 템플릿 문장으로 메운다 (질문 세트에 구멍을 내지 않는다)
    - id 는 rank·node_id 에서 결정적으로 만든다 — 같은 triage 면 같은 결과가 나온다
    - 모든 문장은 QA_TEXT_MAX 로 자른다
    """
    target_ids = {m.node_id for m in marks}
    written: dict[str, dict] = {}
    for raw in raw_questions:
        node_id = str(raw.get("node_id", "") or "")
        if node_id in target_ids and node_id not in written:
            written[node_id] = raw

    questions: list[Question] = []
    for mark in marks:
        node = by_id[mark.node_id]
        raw = written.get(mark.node_id) or {}
        fb_question, fb_why, fb_hint = _fallback_text(node, mark)

        questions.append(Question(
            id=f"q{mark.rank:02d}-{mark.node_id}",
            node_id=mark.node_id,
            label=node.label,
            question=_clip(str(raw.get("question", "") or "")) or fb_question,
            why=_clip(str(raw.get("why", "") or "")) or fb_why,
            hint=_clip(str(raw.get("hint", "") or "")) or fb_hint,
            severity=mark.severity,
            trap=mark.trap,
            source=mark.source,
            slide_nos=list(node.slide_nos),
            doc_weight=mark.doc_weight,
        ))
    return questions


def build_questions(
    graph: ConceptGraph | dict,
    triage: QaTriage | dict,
    *,
    track: str = QA_TRACK_FALLBACK,
    alignment: AlignmentDoc | dict | None = None,
    transcript: Transcript | dict | None = None,
    context: Context | dict | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> QuestionDoc:
    """
    ConceptGraph + QaTriage (+선택 track·AlignmentDoc·Transcript·Context) → QuestionDoc.

    무엇을 물을지는 triage 가 이미 정했다. 여기서는 트랙 상한만큼 자르고
    LLM 에 문장만 받아 온다. 같은 triage·같은 track 이면 질문 id 까지 같다.

    개념마다 parent 경로·relates 이웃·근거 장 발화를 함께 줘서, 정의를 묻는 질문 대신
    관계를 파고드는 질문이 나오게 한다.
    """
    graph = _as_graph(graph)
    if isinstance(triage, dict):
        triage = QaTriage.from_dict(triage)
    if isinstance(alignment, dict):
        alignment = AlignmentDoc.from_dict(alignment)
    if isinstance(transcript, dict):
        transcript = Transcript.from_dict(transcript)
    ctx = _as_context(context)

    if track not in QA_TRACKS:
        track = QA_TRACK_FALLBACK

    by_id = {n.id: n for n in graph.nodes}
    known = [m for m in triage.marks if m.node_id in by_id]
    if not known:
        raise QuestionError(
            "QaTriage 에 이 그래프의 개념이 없습니다. "
            "triage 가 같은 ConceptGraph 에서 나온 것인지 확인하세요."
        )

    marks, deferred = _pick_marks(known, track)
    engine = _engine(llm, llm_kwargs)

    data = _call_with_retry(
        engine,
        QUESTION_SYSTEM_PROMPT,
        _build_question_prompt(graph, marks, by_id, alignment, transcript, ctx),
    )
    raw_questions = [q for q in (data.get("questions") or []) if isinstance(q, dict)]

    return QuestionDoc(
        file_name=graph.file_name,
        total_slides=graph.total_slides,
        track=track,
        questions=_normalize_questions(raw_questions, marks, by_id),
        deferred_node_ids=deferred,
        model=engine.name,
    )
