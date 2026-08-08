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
from itertools import groupby

from ._json_text import extract_json_object
from .contracts import (
    QA_EXTRA_MAX,
    QA_SEVERITIES,
    QA_UNDER_SPOKEN_GAP,
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
    FlowIssue,
    QaJudgement,
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

#: 한 노드에 흐름 이슈가 겹칠 때 프롬프트에 실을 우선순위. 순서 역행이
#: 연결 누락보다 앞이다 — "왜 이 순서로 설명했나" 가 더 구체적인 각도를 준다.
_FLOW_KIND_RANK = {"order_jump": 0, "missing_link": 1}

#: FlowIssue.note 가 비었을 때 kind 로 만드는 결정적 폴백 (구버전 산출물 방어).
_FLOW_NOTE_FALLBACK = {
    "order_jump": "자료 순서와 다른 순서로 말했어요",
    "missing_link": "연결된 개념과 잇는 멘트가 없었어요",
}

#: weak_flow 의 why 폴백을 이슈 종류로 가른다. 순서 역행에 "연결이 안 드러났다"
#: 를 붙이면 사용자가 질문 의도를 오해한다. flow 가 없어 종류를 모를 때는
#: _WHY_BY_SOURCE 의 일반 문구가 그대로 쓰인다.
_WHY_BY_FLOW_KIND = {
    "order_jump": "자료 순서와 다르게 설명한 지점이라 그 의도를 확인하는 질문이에요",
    "missing_link": "다른 개념과의 연결이 발표에서 드러나지 않았어요",
}

#: LLM 이 severity 를 안 줬을 때의 결정적 폴백 (source 기반).
#: justified_skip 은 3 이다 — 리포트가 생략을 승인한 개념이라 못 답해도 넘어간다.
_SEVERITY_BY_SOURCE = {
    "contradiction": 1, "missing": 1, "under_spoken": 1, "weak_flow": 2, "extra": 2,
    "justified_skip": 3,
}

#: sections[].slide_role → 질문 가치 순위. 표지·맺음말에만 나오는 개념은 자료가
#: 아무리 크게 다뤘어도 심사 질문 대상이 아니다 ("감사합니다" 장의 개념을 물을 수 없다).
#: 본론과 결론이 같은 순위인 것은 의도된 것이다 — 그 안의 서열은 weight 와
#: triage severity 가 정한다. 여기서 가르는 것은 '물어볼 만한 구획인가' 하나뿐이다.
_ROLE_RANK = {"body": 0, "conclusion": 0, "intro": 1, "closing": 2, "cover": 3}

#: sections 가 없거나 이 개념의 장이 어느 구획에도 안 들어갈 때. **본론으로 본다** —
#: 구획 정보가 없다는 이유로 질문 후보에서 밀어내면 F-07 이 sections 를 못 만든
#: 발표에서 질문이 통째로 이상해진다.
_ROLE_RANK_FALLBACK = 0

#: 인접 강등에서 면제되는 근거. 모순·누락은 리포트가 이미 "문제" 라고 말한 개념이라,
#: 옆 개념과 붙어 있다는 이유로 질문에서 밀어내면 두 화면이 어긋난다
#: (_rerank 가 source 를 severity 위에 두는 것과 같은 이유다).
_ADJACENCY_EXEMPT = ("contradiction", "missing", "under_spoken")

#: 합성 노드 id 접두사. extra_concepts 는 그래프에 없는 개념이라 조인 키가 없다.
#: **새 그래프를 만들지 않고** 이 네임스페이스로 기존 node_id 축에 얹는다 —
#: `extra:` 로 시작하면 그래프 노드가 아니라는 뜻이고, 리포트는 이걸로 구분한다.
EXTRA_ID_PREFIX = "extra:"

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
    "under_spoken": "자료에서 비중이 큰데 발표에서는 짧게 지나간 개념이에요",
    "weak_flow": "다른 개념과의 연결이 발표에서 드러나지 않았어요",
    "extra": "자료에는 없는데 발표에서 직접 꺼낸 개념이에요",
    "core_weight": "자료가 가장 큰 비중을 둔 핵심 개념이에요",
    "justified_skip": "발표에서 생략해도 괜찮았던 개념이지만, 질문이 나올 수 있어요",
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
5. '발표에서 실제로 한 말' 이 (aligned) 인 개념은 이미 잘 설명한 개념이다.
   정의를 확인하는 각도 대신 **심화·응용·한계**를 파고드는 각도를 잡아라.
6. '근거' 가 justified_skip 인 개념은 생략이 합리적이라고 이미 판정된 것이다.
   severity 는 3 이 기본이다 — 못 답해도 넘어갈 개념이다.
7. 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

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
개념마다 다음 넷만 쓴다:

- question: 심사위원이 실제로 말할 질문 한 문장. 존댓말. 200자 이내.
  주어진 '각도' 를 살려라. 자료에 없는 사실을 지어내지 마라.
- why: 왜 이걸 묻는지 한 줄. 발표자에게 보여 줄 설명이다.
- hint: 막혔을 때 줄 힌트 한 줄. 답을 그대로 말하지 말고 방향만 준다.
- answer_gist: 이 질문에 기대하는 **답의 골자** 한두 줄. 발표자가 끝내 못 답했을 때
  "이렇게 답했어야 한다" 로 보여 줄 내용이다. **자료에 있는 내용만** 쓰고 지어내지 마라.
  질문이 아니라 답을 써라 — 물음표로 끝나면 안 된다.

trap=true 인 개념은 **자료와 어긋난 주장을 얹어** 찔러 보는 질문으로 쓴다
("~라고 했는데, 사실 반대 아닌가요?" 꼴). trap=false 면 그냥 묻는다.

규칙:
1. questions 에는 '질문 대상' 의 node_id 만 쓴다. 지어내면 버려진다.
2. 대상마다 정확히 하나씩. 한 개념에 두 질문을 쓰지 마라.
3. 발표 태도·말투·발음을 묻지 마라. 내용만 묻는다.
4. '발표에서 한 말' 이 (aligned) 인 개념은 이미 설명에 성공한 개념이다.
   같은 설명을 되풀이하게 하지 말고 **심화·응용·한계**를 묻는 질문을 써라.
5. 말투는 해요체다. '~시', '~시겠어요', '하셨는데' 같은 높임을 쓰지 마라.
   이 질문은 리포트의 용어 카드에도 그대로 실린다 — 제품 문구와 말투가 같아야 한다.
   (X) 설명해 주시겠어요?  →  (O) 설명해 주세요. / 왜 필요했나요?
6. 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마:
{
  "questions": [
    { "node_id": "joint", "question": "질문 한 문장",
      "why": "왜 묻는지 한 줄", "hint": "방향만 주는 힌트",
      "answer_gist": "기대하는 답의 골자 한두 줄" }
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
            elif item.verdict == "justified_skip":
                # 리포트가 "생략이 합리적" 이라 한 개념은 서열 맨 뒤로 보낸다 —
                # 자료 weight 가 크다는 이유로 잘 설명한 개념보다 먼저 캐물으면
                # 두 화면이 어긋난다. 승격이 아니라 강등이라 claim 을 못 쓰고
                # 직접 대입한다. 이미 모순·누락이 붙은 노드는 건드리지 않는다 —
                # 확인된 문제를 정당생략이 덮을 수 없다. weak_flow 는 덮는다:
                # 생략이 합리적이면 그 개념의 연결 결손도 캐물을 일이 아니다.
                if found.get(item.node_id) in ("weak_flow", QA_SOURCE_FALLBACK):
                    found[item.node_id] = "justified_skip"
            elif item.doc_weight - item.speech_weight > QA_UNDER_SPOKEN_GAP:
                # 자료는 크게 다뤘는데 발화가 짧았던 개념. 두 축이 이미 같은 node_id 로
                # 조인돼 있어 뺄셈 한 번이면 나온다 — LLM 이 필요 없다.
                # justified_skip 은 위 분기에서 이미 갈라졌다.
                claim(item.node_id, "under_spoken")

    return found


def _extra_nodes(alignment: AlignmentDoc | None) -> list[ConceptNode]:
    """
    발화에만 나온 개념(extra_concepts)을 질문 후보용 **합성 노드**로 만든다.

    그래프에 없는 개념이라 조인 키가 없다. **새 그래프를 만들지 않고** `extra:`
    네임스페이스로 기존 node_id 축에 얹는다 — F-11 이 발화 그래프를 따로 뽑지 않고
    노드 목록에 조건화한 것과 같은 이유다. 여기서 축을 하나 더 만들면 리포트가
    두 축을 조인해야 하고, 그 순간 추출 분산이 실력을 덮는다.

    weight 는 0.0 이다. 자료가 배분한 양이 실제로 없는 개념이라 그렇게 두는 것이
    정직하다 — 이 후보의 순위는 근거(source='extra')가 정하지 weight 가 정하지 않는다.

    label 로 중복을 제거하고 QA_EXTRA_MAX 까지만 올린다. 입력 순서를 보존하므로
    같은 AlignmentDoc 이면 언제나 같은 후보가 나온다.
    """
    if alignment is None:
        return []
    nodes: list[ConceptNode] = []
    seen: set[str] = set()
    for extra in alignment.extra_concepts:
        label = (extra.label or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        nodes.append(ConceptNode(
            id=f"{EXTRA_ID_PREFIX}{label}",
            label=label,
            slide_nos=[extra.slide_no] if extra.slide_no else [],
            summary=(extra.quote or "").strip(),
            weight=0.0,
        ))
        if len(nodes) >= QA_EXTRA_MAX:
            break
    return nodes


def _flow_issue_by_node(flow: FlowDiff | None) -> dict[str, FlowIssue]:
    """
    weak_flow 근거가 된 이슈를 노드마다 하나씩. **프롬프트 재료로만** 쓴다 —
    순위는 여전히 source 가 정하므로 이 맵이 순서를 바꾸지 않는다.

    같은 노드에 이슈가 겹치면 order_jump 가 이긴다 (_FLOW_KIND_RANK).
    good_link 는 잘한 것이라 여기 들어오지 않는다.
    """
    if flow is None:
        return {}
    found: dict[str, FlowIssue] = {}
    for issue in flow.issues:
        if issue.kind not in _WEAK_FLOW_KINDS:
            continue
        for node_id in issue.node_ids:
            held = found.get(node_id)
            if held is None or _FLOW_KIND_RANK[issue.kind] < _FLOW_KIND_RANK[held.kind]:
                found[node_id] = issue
    return found


def _flow_line(issue: FlowIssue) -> str:
    """
    프롬프트에 붙일 '흐름:' 한 줄. F-11 이 만든 note 가 곧 사람이 읽을 설명이라
    ("'B' 을(를) 상위 개념 'A' 보다 먼저 말했어요") 그대로 싣는다 — 여기서
    문장을 다시 만들면 리포트 화면과 다른 말이 된다.
    """
    note = (issue.note or "").strip() or _FLOW_NOTE_FALLBACK[issue.kind]
    return f"흐름({issue.kind}): {note}"


def _role_rank_of(graph: ConceptGraph, node: ConceptNode) -> int:
    """
    이 개념이 앉은 구획(sections[].slide_role)의 질문 가치 순위.

    여러 구획에 걸치면 **가장 앞선 것**을 쓴다 — 표지와 본론에 동시에 나오는 개념은
    본론 개념으로 본다. 한 장이라도 본론에서 다뤘으면 물어볼 거리가 있다는 뜻이다.

    slide_nos 가 조인 키다 (SCHEMA §6-B). sections 를 안 만든 그래프에서는
    전부 폴백(본론)이 되어 기존 순서와 같아진다.
    """
    if not node.slide_nos or not graph.sections:
        return _ROLE_RANK_FALLBACK
    covered = set(node.slide_nos)
    ranks = [
        _ROLE_RANK.get(section.slide_role, _ROLE_RANK_FALLBACK)
        for section in graph.sections
        if covered & set(section.slide_nos)
    ]
    return min(ranks) if ranks else _ROLE_RANK_FALLBACK


def _ordered_candidates(
    graph: ConceptGraph,
    alignment: AlignmentDoc | None,
    flow: FlowDiff | None,
) -> list[tuple[ConceptNode, str]]:
    """
    질문 후보를 결정적 우선순위로 정렬해 CANDIDATE_LIMIT 까지 자른다.

    근거 우선순위 → 구획 역할 → 자료 weight 내림차순 → 요약 유무
    → 앞 슬라이드 → id 순.

    구획 역할이 weight 위에 있는 것은 의도된 것이다. 표지·맺음말에만 나오는 개념은
    자료가 크게 다뤘어도 심사위원이 물을 대상이 아니라서, 크기보다 **어느 구획에
    앉았는가**가 먼저다. 본론·결론은 같은 순위라 그 안에서는 weight 가 그대로 정한다.

    요약(summary)이 빈 개념은 뒤로 민다 — 질문 문장을 쓸 재료가 없어 LLM 이
    사전식 정의 질문밖에 못 쓴다. 버리지는 않는다, 그것뿐인 그래프도 있다.

    마지막 두 단계는 동률을 깨려고 있다 — 같은 그래프면 언제나 같은 순서가 나온다.
    """
    source_of = _source_by_node(graph, alignment, flow)
    # 발화에만 나온 개념도 같은 축에서 같은 규칙으로 줄 세운다.
    extras = _extra_nodes(alignment)
    for extra in extras:
        source_of[extra.id] = "extra"

    def sort_key(node: ConceptNode) -> tuple:
        return (
            _SOURCE_RANK[source_of[node.id]],
            _role_rank_of(graph, node),
            -node.weight,
            0 if (node.summary or "").strip() else 1,
            min(node.slide_nos) if node.slide_nos else _NO_SLIDE,
            node.id,
        )

    ranked = sorted([*graph.nodes, *extras], key=sort_key)[:CANDIDATE_LIMIT]
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
    raw = engine.complete(system=system, user=user, temperature=0.3, max_tokens=MAX_TOKENS, json_mode=True)
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
    flow: FlowDiff | None = None,
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
        "흐름은 발표에서 확인된 순서·연결 문제다 — order_jump 는 \"왜 이 순서로",
        "설명했는지\", missing_link 는 \"두 개념의 관계\" 를 묻는 각도가 된다.",
        "",
    ]
    flow_of = _flow_issue_by_node(flow)
    for line, (node, source) in zip(_node_lines(pairs), pairs):
        parts.append(line)
        relation = _relation_line(node, graph)
        if relation:
            parts.append(f"    {relation}")
        # 흐름 상세는 근거가 weak_flow 인 개념에만 붙인다 — 다른 근거로 뽑힌
        # 개념에 이슈까지 얹으면 LLM 이 근거를 섞어 각도를 잡는다.
        issue = flow_of.get(node.id)
        if issue is not None and source == "weak_flow":
            parts.append(f"    {_flow_line(issue)}")

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
    graph: ConceptGraph | None = None,
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
    return _rerank(marks, pairs, graph)


def _spread_adjacent(
    ordered: list[TriageMark],
    graph: ConceptGraph | None,
) -> list[TriageMark]:
    """
    앞에서 이미 뽑은 개념과 **그래프에서 바로 붙어 있는** 개념은 뒤로 민다.

    이웃끼리 나란히 물으면 "왜 이걸 골랐나" 와 "이걸 어떻게 쓰나" 처럼 사용자가
    한 번에 답할 수 있는 질문이 두 개 나온다 — 같은 맥락을 다르게 물어 놓고
    다른 답을 요구하는 꼴이다. edges 가 그 인접을 이미 알고 있으니 LLM 이 필요 없다.

    인접은 `neighbors_of` 로 본다 — parent·relates 를 방향 무시하고 모두 센다.
    위계로 붙었든 논리로 붙었든 사용자에게는 똑같이 '한 덩어리' 이기 때문이다.

    **강등은 같은 근거(source) 안에서만 일어난다.** 근거가 다른 두 개념은 서로 다른
    이유로 뽑힌 것이라 중복이 아니다. 이 울타리가 없으면 별 모양 그래프에서
    루트가 무너진다 — 루트는 모든 자식과 인접하므로, 자식 하나가 '누락' 으로 먼저
    뽑히는 순간 **자료에서 가장 무거운 개념이 맨 뒤로 밀린다.**
    근거 우선순위를 넘지 않는다는 이 모듈의 규칙(_rerank 주석)과도 같은 결이다.

    **제외가 아니라 강등이다.** 트랙 상한에 여유가 있으면 여전히 물어본다.
    모순·누락 근거는 아예 면제된다 (_ADJACENCY_EXEMPT).
    """
    if graph is None or len(ordered) < 2:
        return ordered

    result: list[TriageMark] = []
    # ordered 는 이미 근거 우선순위로 정렬돼 있어 groupby 가 그대로 근거 묶음이 된다.
    for _, group in groupby(ordered, key=lambda m: _SOURCE_RANK[m.source]):
        kept: list[TriageMark] = []
        demoted: list[TriageMark] = []
        chosen: set[str] = set()
        for mark in group:
            neighbors = {n.id for n in graph.neighbors_of(mark.node_id)}
            if mark.source not in _ADJACENCY_EXEMPT and (neighbors & chosen):
                demoted.append(mark)
                continue
            kept.append(mark)
            chosen.add(mark.node_id)
        result.extend(kept + demoted)
    return result


def _rerank(
    marks: list[TriageMark],
    pairs: list[tuple[ConceptNode, str]],
    graph: ConceptGraph | None = None,
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
    # 구획 역할은 severity 위다 — 표지·맺음말 개념은 LLM 이 '치명' 을 줘도
    # 물어볼 대상이 아니다. source 를 severity 위에 두는 것과 같은 이유로,
    # 구조에서 나온 사실이 LLM 의 짐작을 이긴다.
    role_of = (
        {node.id: _role_rank_of(graph, node) for node, _ in pairs}
        if graph is not None
        else {}
    )
    # 요약이 빈 개념은 질문 문장을 쓸 재료가 없다. severity·weight 아래에 둬서
    # 동률일 때만 갈리게 한다 — 재료가 없다고 중요한 개념을 밀어내면 안 된다.
    no_summary_of = {
        node.id: (0 if (node.summary or "").strip() else 1) for node, _ in pairs
    }
    ordered = sorted(
        marks,
        key=lambda m: (
            _SOURCE_RANK[m.source],
            role_of.get(m.node_id, _ROLE_RANK_FALLBACK),
            m.severity,
            -m.doc_weight,
            no_summary_of.get(m.node_id, 0),
            slide_of[m.node_id],
            m.node_id,
        ),
    )
    # 순위가 정해진 뒤에 인접을 편다. 정렬 키에 섞으면 "누가 먼저 뽑혔나" 를
    # 알 수 없어 인접 판단이 불가능하다 — 이것은 순서에 의존하는 연산이다.
    ordered = _spread_adjacent(ordered, graph)
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
        _build_triage_prompt(graph, pairs, alignment, transcript, ctx, flow),
    )
    raw_marks = [m for m in (data.get("marks") or []) if isinstance(m, dict)]

    return QaTriage(
        file_name=graph.file_name,
        total_slides=graph.total_slides,
        marks=_normalize_marks(raw_marks, pairs, graph),
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
    flow_of: dict[str, FlowIssue] | None = None,
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
        "흐름이 붙은 개념은 그 문제를 그대로 묻는다 — order_jump 는 \"왜 이",
        "순서로 설명했는지\", missing_link 는 \"두 개념이 어떤 관계인지\".",
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

        issue = (flow_of or {}).get(node.id)
        if issue is not None and mark.source == "weak_flow":
            parts.append(f"    {_flow_line(issue)}")

        said = _speech_excerpt(node, transcript)
        item = judged.get(node.id)
        if said or (item is not None and item.evidence.strip()):
            verdict = f"({item.verdict}) " if item is not None else ""
            parts.append(f"    발표에서 한 말{verdict}: {said or item.evidence}")
    return "\n".join(parts)


def _fallback_text(
    node: ConceptNode,
    mark: TriageMark,
    flow_issue: FlowIssue | None = None,
) -> tuple[str, str, str]:
    """LLM 이 이 개념을 빠뜨렸을 때 쓰는 결정적 문장 3종 (question, why, hint)."""
    # '~시겠어요' 는 쓰지 않는다 (CLAUDE.md §3-1). 이 문장은 용어 카드의
    # 「이런 질문이 와요」로도 그대로 나가므로 제품 말투를 따른다.
    if mark.angle:
        question = f"{node.label}: {mark.angle} — 설명해 주세요."
    else:
        question = f"{node.label}: 이 개념의 핵심과 자료에 넣은 근거를 설명해 주세요."

    if mark.source == "weak_flow" and flow_issue is not None:
        # 이슈 종류를 알면 why 도 그 종류로 말한다 — 순서 역행에 "연결이 안
        # 드러났다" 를 붙이면 사용자가 질문 의도를 오해한다.
        why = _WHY_BY_FLOW_KIND[flow_issue.kind]
    else:
        why = _WHY_BY_SOURCE.get(mark.source, _WHY_BY_SOURCE[QA_SOURCE_FALLBACK])

    if node.slide_nos:
        # 사다리 2단(_hint_scope)과 같은 절단 — 12장을 다 나열하면 좁혀 주기는커녕
        # 아무 정보도 없다. 문구는 2단과 다르게 둔다: 같으면 build_hint_ladder 의
        # 중복 제거가 2단을 지워 사다리가 한 칸 짧아진다.
        shown = node.slide_nos[:HINT_SLIDE_MAX]
        nos = ", ".join(str(n) for n in shown)
        extra = f" 외 {len(node.slide_nos) - len(shown)}장" if len(node.slide_nos) > len(shown) else ""
        hint = f"{nos}장{extra}에 이 개념을 둔 이유부터 떠올려 보세요"
    else:
        hint = "자료에서 이 개념을 왜 다뤘는지부터 짚어 보세요"
    return question, why, hint


def _fallback_gist(node: ConceptNode, *, trap: bool = False) -> str:
    """
    LLM 이 골자를 빠뜨렸을 때 자료로 조립하는 결정적 문장.

    비워 두면 되묻기가 끝날 때 "그래서 답이 뭔데" 가 빈칸으로 남는다.
    개념 요약이 곧 자료가 말하는 답이므로 그것을 근거 장과 함께 돌려준다.

    trap 질문은 거짓 전제를 **바로잡는 것**이 정답이다 — 요약만 돌려주면
    "이렇게 말하면 완성" 칸에 전제 반박이 없는 답이 실려 질문과 어긋난다.
    """
    summary = (node.summary or "").strip()
    if not summary:
        summary = f"{node.label} 의 핵심"
    if trap:
        summary = f"질문의 전제가 자료와 달라요 — 자료가 말하는 것: {summary}"
    if node.slide_nos:
        nos = ", ".join(str(n) for n in node.slide_nos)
        return f"{summary} ({nos}장 근거)"
    return summary


def _normalize_questions(
    raw_questions: list[dict],
    marks: list[TriageMark],
    by_id: dict[str, ConceptNode],
    flow_of: dict[str, FlowIssue] | None = None,
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
        fb_question, fb_why, fb_hint = _fallback_text(
            node, mark, (flow_of or {}).get(mark.node_id)
        )

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
            answer_gist=(
                _clip(str(raw.get("answer_gist", "") or ""))
                or _fallback_gist(node, trap=mark.trap)
            ),
        ))
    return questions


def build_questions(
    graph: ConceptGraph | dict,
    triage: QaTriage | dict,
    *,
    track: str = QA_TRACK_FALLBACK,
    alignment: AlignmentDoc | dict | None = None,
    flow: FlowDiff | dict | None = None,
    transcript: Transcript | dict | None = None,
    context: Context | dict | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> QuestionDoc:
    """
    ConceptGraph + QaTriage (+선택 track·AlignmentDoc·FlowDiff·Transcript·Context)
    → QuestionDoc.

    무엇을 물을지는 triage 가 이미 정했다. 여기서는 트랙 상한만큼 자르고
    LLM 에 문장만 받아 온다. 같은 triage·같은 track 이면 질문 id 까지 같다.

    개념마다 parent 경로·relates 이웃·근거 장 발화를 함께 줘서, 정의를 묻는 질문 대신
    관계를 파고드는 질문이 나오게 한다. flow 를 주면 weak_flow 근거 개념에 이슈
    상세(순서 역행·연결 누락)가 붙어 "왜 이 순서로 설명했나요?" 류 질문이 가능해진다
    — 순위는 안 바뀐다, 프롬프트 재료일 뿐이다.
    """
    graph = _as_graph(graph)
    if isinstance(triage, dict):
        triage = QaTriage.from_dict(triage)
    if isinstance(alignment, dict):
        alignment = AlignmentDoc.from_dict(alignment)
    if isinstance(flow, dict):
        flow = FlowDiff.from_dict(flow)
    if isinstance(transcript, dict):
        transcript = Transcript.from_dict(transcript)
    ctx = _as_context(context)

    if track not in QA_TRACKS:
        track = QA_TRACK_FALLBACK

    # 합성 노드(extra:)도 사전에 넣는다. triage 가 후보로 올렸는데 여기서 빠지면
    # `known` 필터가 조용히 떨어뜨려, 발화 개념 질문이 이유 없이 사라진다.
    by_id = {n.id: n for n in (*graph.nodes, *_extra_nodes(alignment))}
    known = [m for m in triage.marks if m.node_id in by_id]
    if not known:
        raise QuestionError(
            "QaTriage 에 이 그래프의 개념이 없습니다. "
            "triage 가 같은 ConceptGraph 에서 나온 것인지 확인하세요."
        )

    marks, deferred = _pick_marks(known, track)
    engine = _engine(llm, llm_kwargs)
    flow_of = _flow_issue_by_node(flow)

    data = _call_with_retry(
        engine,
        QUESTION_SYSTEM_PROMPT,
        _build_question_prompt(graph, marks, by_id, alignment, transcript, ctx, flow_of),
    )
    raw_questions = [q for q in (data.get("questions") or []) if isinstance(q, dict)]

    return QuestionDoc(
        file_name=graph.file_name,
        total_slides=graph.total_slides,
        track=track,
        questions=_normalize_questions(raw_questions, marks, by_id, flow_of),
        deferred_node_ids=deferred,
        model=engine.name,
    )


# ---------------------------------------------------------------------------
# 힌트 사다리 — LLM 을 부르지 않는다
#
# 실전 코칭에서 사용자가 '힌트 보기' 를 누르면 기다림 없이 나와야 한다. 그래서
# 여기서는 이미 계산된 신호만 쓴다 — 질문이 들고 온 힌트, 근거 슬라이드,
# 판정이 짚은 빠진 포인트. 이 모듈의 원칙("무엇을 말할지는 코드가 정하고
# LLM 은 문장만 쓴다")이 힌트에도 그대로 적용된 것이다.
# ---------------------------------------------------------------------------

#: 3단계에 나열할 빠진 포인트 최대 개수. 다 늘어놓으면 사실상 정답 공개다.
HINT_POINT_MAX = 3

#: 2단계에 이름 붙일 근거 슬라이드 최대 개수. 넘으면 개수만 알리고 앞쪽으로 안내한다.
HINT_SLIDE_MAX = 3

#: 골자 조각을 만들 최소 길이. 이보다 짧으면 잘라 봐야 통째로 노출된다.
GIST_FRAGMENT_MIN = 4


def _hint_direction(question: Question) -> str:
    """1단계 · 방향. F-08 이 질문과 함께 만든 힌트가 있으면 그것을 쓴다."""
    hint = (question.hint or "").strip()
    if hint:
        return _clip(hint)
    label = question.label or "이 개념"
    return _clip(f"{label}: 핵심을 한 문장으로 말하는 것부터 시작해 보세요")


def _hint_scope(question: Question) -> str:
    """
    2단계 · 범위. 어디를 보면 되는지까지 좁혀 준다.

    근거 장을 전부 나열하지 않는다 — 실측에서 개념 하나가 12장에 걸쳐
    "1,2,3,…,12장에서" 가 나왔다. 다 나열하면 좁혀 주기는커녕 아무 정보도 없다.

    **기억을 요구하지 않는다.** 예전 문구는 "27, 28장에서 이 개념을 어떻게
    설명했는지 떠올려 보세요" 였는데, 몇 장에 뭐가 있는지는 발표자도 모른다 —
    아는 사람에게만 힌트인 문장이었다. 화면이 이 번호를 읽어 그 장을 조그맣게
    같이 띄우므로 (qa_live.js `hintSlideNos`), 문구도 **보고 짚는 말**로 둔다.
    """
    nos = question.slide_nos
    if not nos:
        return "자료에서 이 개념을 왜 다뤘는지부터 짚어 보세요"
    shown = ", ".join(str(n) for n in nos[:HINT_SLIDE_MAX])
    if len(nos) > HINT_SLIDE_MAX:
        return _clip(f"{shown}장을 비롯해 {len(nos)}장에 걸쳐 나옵니다 — 앞쪽부터 짚어 보세요")
    return _clip(f"{shown}장을 같이 볼게요 — 여기서 이 개념을 어떻게 설명했는지 짚어 보세요")


def _gist_fragment(gist: str) -> str:
    """
    골자의 앞부분만. **통째로 보여 주면 힌트가 아니라 정답 공개다.**

    너무 짧은 골자는 조각을 내도 원문이 그대로 드러나므로 아예 쓰지 않는다.
    """
    text = (gist or "").strip()
    if len(text) < GIST_FRAGMENT_MIN:
        return ""
    return text[: max(1, len(text) // 2)].rstrip() + "…"


def _hint_gist(question: Question) -> str:
    """
    3단계 · 접근. 기대 답의 앞 조각으로 방향을 잡아 준다.

    **판정 없이 만들 수 있는 마지막 단계다.** 아직 답을 안 한 사람에게 "뭘
    빠뜨렸다" 는 못 해도 "이쪽입니다" 까지는 짚어 줄 수 있다. 이게 없으면
    답하기 전 힌트가 방향·범위 둘뿐이라 사다리가 금방 끝난다.

    골자가 짧으면 조각을 내도 원문이 드러나므로 빈 문자열이 된다.
    """
    fragment = _gist_fragment(question.answer_gist)
    return _clip(f"이 방향입니다 — {fragment}") if fragment else ""


def _hint_close(question: Question, judgement: QaJudgement) -> str:
    """
    4단계 · 근접. **사용자가 실제로 빠뜨린 것**에 반응한다.

    판정이 짚은 포인트가 있으면 그것을, 없으면 골자 조각을 준다.
    둘 다 없으면 빈 문자열 — 억지로 채우면 앞 단계를 되풀이할 뿐이다.
    """
    points = [p.strip() for p in judgement.missing_points if str(p).strip()]
    if points:
        shown = ", ".join(points[:HINT_POINT_MAX])
        if len(points) > HINT_POINT_MAX:
            shown += f" 외 {len(points) - HINT_POINT_MAX}개"
        return _clip(f"아직 안 나온 것: {shown}")

    fragment = _gist_fragment(question.answer_gist)
    return _clip(f"이 방향입니다 — {fragment}") if fragment else ""


def build_hint_ladder(
    question: Question | dict,
    judgement: QaJudgement | dict | None = None,
) -> list[str]:
    """
    Question (+선택 QaJudgement) → 힌트 사다리. **LLM 을 부르지 않는다.**

    단계가 갈수록 구체적이다 — 방향 → 범위 → 접근 → 근접.
    어느 단계에서도 답을 그대로 말해 주지 않는다.

    판정이 없으면 3단계까지다. 4단계는 아직 답하지도 않은 사람에게
    "뭘 빠뜨렸다" 고 말할 수 없어 성립하지 않는다.

    재료가 없는 단계는 빈 문자열로 나오고, 여기서 걷어낸다. 중복도 마찬가지다 —
    빠뜨린 포인트가 없으면 4단계가 3단계와 같은 골자 조각으로 떨어지는데,
    같은 말을 두 번 하면 사다리가 아니다.
    """
    if isinstance(question, dict):
        question = Question.from_dict(question)
    if isinstance(judgement, dict):
        judgement = QaJudgement.from_dict(judgement)

    steps = [_hint_direction(question), _hint_scope(question), _hint_gist(question)]
    if judgement is not None:
        steps.append(_hint_close(question, judgement))

    ladder: list[str] = []
    for step in steps:
        if step and step not in ladder:
            ladder.append(step)
    return ladder


def with_hint_ladders(payload: dict, questions: list) -> dict:
    """
    QuestionDoc 직렬화 결과에 질문별 힌트 사다리를 얹은 **새 dict** 를 준다.

    Question 이 들고 있는 힌트는 `hint` 문자열 하나뿐이라, 이걸 안 실으면 화면은
    첫 판정을 받기 전까지 1단계밖에 못 보여 준다 — 3단계로 만든 사다리가
    첫 칸에서 끝난다. `build_hint_ladder` 는 LLM 을 부르지 않으니 공짜다.

    판정이 없는 시점이라 사다리는 3단계(방향·범위·접근)까지다. 4단계(근접)는
    답을 받아 본 뒤에야 F-09 가 판정과 함께 채운다.

    원래 demo/bridge.py 에 있었는데, 브리지만 붙이니 FastAPI 라우트로 직결하면
    사다리가 1칸으로 무너지고 「답 보고 넘어가기」가 조기에 열렸다 — 질문을
    주는 모든 백엔드가 같은 응답을 내도록 여기(단일 출처)로 옮겼다.
    """
    by_id = {q.id: q for q in questions}
    items = []
    for item in payload.get("questions") or []:
        q = by_id.get(item.get("id"))
        items.append({**item, "hints": build_hint_ladder(q)} if q else item)
    return {**payload, "questions": items}
