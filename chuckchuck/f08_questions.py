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
import re
import sys
from itertools import groupby

from . import _grounding as grounding
from ._evidence import (
    anchor_slides,
    best_quote,
    clean_slide_text,
    find_citations,
    mask_gist,
    neighbor_lines,
    ranked_quotes,
    section_line,
)
from ._json_text import extract_json_object
from ._match import norm_tokens
from ._probes import as_claims, derive_probes, mentions, probe_question, probe_why
from ._probes import josa as _probe_josa
from ._speech import to_haeyo, ungrounded_numbers
from .contracts import (
    PROBE_KINDS,
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
    ClaimDoc,
    ClaimQuote,
    ConceptGraph,
    ConceptNode,
    Context,
    FlowDiff,
    FlowIssue,
    ConceptMemory,
    MemoryDoc,
    PaceDoc,
    PAPER_ABSTRACT_MAX,
    PaperDoc,
    PaperRef,
    Probe,
    QaJudgement,
    QaTriage,
    Question,
    QuestionBasis,
    QuestionDoc,
    QuestionError,
    Slide,
    SlideDoc,
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
#: 탐침(PROBE_KINDS)도 확인된 사실이다 — 자료 안의 긴장(tension)은 모순처럼 치명, 나머지 빈틈은 보통이다.
_SEVERITY_BY_SOURCE = {
    "contradiction": 1, "missing": 1, "under_spoken": 1, "weak_flow": 2, "extra": 2,
    "justified_skip": 3,
    "tension": 1, "unsolved": 2, "unsupported_cause": 2, "absolute_boundary": 2, "sibling_priority": 2,
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

#: 자료가 이만큼도 안 실은 개념은 '누락' 이어도 치명이 아니다.
#: 우리가 재는 것은 «자료가 약속한 것을 말로 지켰는가» 다. 자료가 스치듯 둔 개념을
#: 안 말한 것은 약속을 어긴 게 아니라 자료가 원래 안 중요하게 본 것이다 —
#: 그걸 치명으로 두면 질문 코치가 사소한 것부터 캐묻는다 (2026-08-10 지시).
MINOR_WEIGHT = float(os.environ.get("CHUCKCHUCK_QA_MINOR_WEIGHT", "0.2"))

#: 개념 하나당 프롬프트에 실을 발화 발췌 길이. 전체 발화를 다 실으면 개념이 묻힌다.
SPEECH_EXCERPT_MAX = int(os.environ.get("CHUCKCHUCK_QA_SPEECH_EXCERPT_MAX", "500"))

#: 개념 하나당 프롬프트에 실을 **자료 본문** 길이. 근거 장(`node.slide_nos`)만 잘라
#: 넣는다 — 자료 전체를 실으면 F-06 이 겪은 「입력이 길면 LLM JSON 이 잘린다」로 간다.
#:
#: 이게 있어야 모범답에 "자료에 있는 말로만 써라" 를 **가리킬 수 있다.** 예전엔
#: F-08 이 ConceptGraph 요약(토큰 아홉 개)만 쥐고 있어서 그 규칙이 부탁일 뿐이었고,
#: 자료엔 "약 90–110분" 만 있는데 모범답이 "뇌파 측정을 통해" 라고 썼다.
#:
#: **0 이면 본문을 아예 안 싣는다** — 시연 중에 프롬프트를 예전으로 되돌리는
#: 스위치다. 커밋을 찾지 않고 `CHUCKCHUCK_QA_SLIDE_BODY_MAX=0` 하나로 끈다.
#: 2026-09-10: 400 → 1200. 근거 장을 anchor 3장으로 좁히고 캡션 잡음을 걷어냈으니
#: 같은 글자 수가 전부 본문이다. 400 이던 때는 그중 70% 가 이미지 캡션이었다.
SLIDE_BODY_MAX = int(os.environ.get("CHUCKCHUCK_QA_SLIDE_BODY_MAX", "1200"))

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
    **{kind: probe_why(Probe(kind=kind)) for kind in PROBE_KINDS},
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
  **발표자가 자료와 발표만 보고 답할 수 있어야 한다.** 우리가 준 배경(경로·연결·
  치명도·각도)은 네가 각도를 잡는 재료지 발표자가 아는 것이 아니다.
- why: 왜 이걸 묻는지 한 줄. 발표자에게 보여 줄 설명이다.
- hint: 막혔을 때 줄 힌트 한 줄. 답을 그대로 말하지 말고 방향만 준다.
- answer_gist: 이 질문에 기대하는 **답의 골자** 한두 줄. 발표자가 끝내 못 답했을 때
  "이렇게 답했어야 한다" 로 보여 줄 내용이다. **자료에 있는 내용만** 쓰고 지어내지 마라.
  질문이 아니라 답을 써라 — 물음표로 끝나면 안 된다.
  **개념에 「자료 본문」 줄이 붙어 있으면 거기 있는 말로만 쓴다.** 그 줄에 없는
  사실·용어·수치를 보태지 마라. 자료엔 "주 3회" 만 있는데 "임상 시험으로
  입증되었으며" 라고 쓰는 것이 정확히 금지되는 것이다 — 발표자가 방어할 수 없는
  답이 된다. 본문 줄이 없는 개념은 요약과 발표에서 한 말까지만 쓴다.
  **숫자는 자료에서 그 숫자가 붙은 대상 그대로 쓴다.** 표의 「그룹 A | 71%」 를 다른 그룹의 값으로 옮기지 마라.
  **자료가 말하지 않은 서열·비교(「X 가 더 중요」·「가장 큰 요인」)를 만들지 마라.** 자료가 「A = B × C」 처럼
  나란히 두기만 했으면 골자도 나란히 둔다.
  **trap=true 질문의 골자는 전제에 동의하지 않는다.** 질문이 얹은 어긋난 주장을 뒤집는 **자료의 사실**을 쓴다
  (「자료는 X 가 아니라 Y 라고 해요」 꼴).
  **근거는 자료 본문이나 발표에서 한 말에서만 든다.** "경로에 …로 표시되어 있다"
  처럼 우리가 준 배경을 근거로 인용하지 마라 — 발표자는 그걸 본 적이 없어서
  그 답은 애초에 쓸 수 없는 답이 된다.
- answer_gist_parts: 질문이 **둘 이상**을 묻는다면 (「A와 B를 각각」·「무엇이고 왜인지」)
  골자를 그 요소대로 쪼개 배열로 적는다. 채점이 요소별로 이뤄져서, 하나만 답하고
  넘어가는 것을 막는다. **하나만 묻는 질문이면 빈 배열이다** — 억지로 쪼개면
  answer 하나로는 이길 수 없는 질문이 된다. 최대 3개, 각 요소는 answer_gist 안의 내용이다.

trap=true 인 개념은 **자료와 어긋난 주장을 얹어** 찔러 보는 질문으로 쓴다
("~라고 했는데, 사실 반대 아닌가요?" 꼴). trap=false 면 그냥 묻는다.
- trap_premise: trap=true 질문이면 질문 문장 안에 얹은 **어긋난 주장 한 절을 질문에 쓴 글자 그대로** 옮긴다.
  자료 줄을 그대로 옮긴 말은 어긋난 주장이 아니다 — 자료의 수치·비교·인과·조건 **하나를 바꿔서** 얹어라.
  trap=false 면 "" 이다. 코드가 이 절이 질문에 있는지, 자료와 정말 어긋나는지 대조한다 — 아니면 함정 표시를 뗀다.

규칙:
1. questions 에는 '질문 대상' 의 node_id 만 쓴다. 지어내면 버려진다.
2. 대상마다 정확히 하나씩. 한 개념에 두 질문을 쓰지 마라.
3. 발표 태도·말투·발음을 묻지 마라. 내용만 묻는다.
3-1. **개념의 배치·위계·분류·정렬 자체를 묻지 마라.** "왜 이렇게 정렬했나요",
   "왜 A 를 B 의 하위로 두었나요", "다른 분류 방식 대신 이 방식을 택한 이유는"
   같은 질문은 **발표자가 하지도 않은 선택을 방어하라는 요구**다. 그 배치는
   우리가 자료를 읽고 추론한 것이지 발표자가 만든 것이 아니다.
   관계를 묻고 싶으면 배치가 아니라 **내용**으로 물어라.
   (X) 왜 다른 정렬 방식 대신 이 방식을 선택했나요?
   (O) 만족도가 맛과 분위기를 모두 포함한다면, 둘 중 어느 쪽이 재방문에 더 크게
       좌우되나요?
3-2. **발표자에게 직접 묻는다.** "발표자는 어떻게 설명했나요" 처럼 발표자를 3인칭으로 부르지 마라.
   주어를 빼거나 "발표에서" 로 쓴다.  (X) 발표자는 이 공식을 어떻게 설명했나요?  (O) 이 공식을 어떻게 설명했나요?
3-3. **"왜 A 를 B 보다 먼저 말했나" 같은 순서 질문은 「흐름(order_jump):」 줄이 붙은 개념에만** 쓴다. 그 줄이 없으면
   순서가 문제라는 근거가 없다 — 순서 대신 그 개념의 내용·근거·한계를 물어라.
3-4. 「시간배분:」 줄이 붙은 개념은 그 장을 제 몫보다 짧게 넘긴 것이다. 정의를 되묻지 말고, 그 장에서
   설명하지 못했을 **개념 사이의 관계·조건·우선순위**를 물어라.
   (예) "대기 시간이 한 번만 길어도 재방문이 줄어드나요, 아니면 여러 번 쌓여야 줄어드나요?"
3-5. 「주제:」 줄이 붙은 개념은 발표 전체의 주장이다. 자료의 두 문구를 이어 붙여 "…를 바탕으로 설명해 주세요" 로
   **주장을 되읊게 하지 마라.** 주장이 성립하는 조건·경계·반례, 또는 자료 안에서 **서로 부딪히는 표현**
   (예: "X보다 중요하다" 면서 X 를 요소로 넣음)을 한 가지 골라 물어라.
   (X) 만족도가 가격보다 중요한 이유를 세 가지 요소(가격, 맛, 분위기)를 바탕으로 설명해 주세요.
   (O) 가격도 만족도의 요소인데, 만족도가 가격보다 중요하다는 건 어떤 뜻인가요?
3-6. **「어떻게 측정·계산·통제했나요」 는 근거 장 자료 본문에 수치·방법·출처가 있을 때만** 묻는다. 자료에 없는
   측정·실험을 전제하면 발표자가 답할 수 없다 — 코드가 그런 질문을 버리고 정해진 문장으로 바꾼다.
3-7. 검색 문헌(교수가 읽고 온 논문)을 **질문의 대상**으로 삼지 마라. 「X (연도)는 어떻게 설명했나요」·
   「X 를 왜 인용했나요」·「X 를 어떻게 반영했나요」 는 발표자가 본 적 없는 논문을 묻는 것이다.
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
      "answer_gist": "기대하는 답의 골자 한두 줄",
      "answer_gist_parts": ["둘 이상을 묻는 질문일 때만 요소별로. 아니면 []"],
      "trap_premise": "trap=true 일 때만 질문에 얹은 어긋난 주장 한 절. 아니면 빈 문자열" }
  ]
}
"""

#: 탐침(주장 그래프)이 붙은 개념이 있을 때만 시스템 프롬프트 뒤에 붙는 규칙. **없으면 프롬프트는 예전과 글자까지 같다.**
PROBE_SYSTEM_ADDENDUM = """

## 탐침 — 이 요청에만 붙는 규칙
질문 대상 개념에 「탐침(종류): …」 줄이 붙어 있으면, 그 개념이 뽑힌 이유가 바로 그 탐침이다.
- 질문은 **탐침이 짚은 긴장·빈틈 하나만** 물어라. 다른 각도로 새지 마라.
- 「근거 원문」 은 자료에 그대로 있는 문장이다. 질문은 그 문장들이 가리키는 것을 묻되, 문장을 되읊게 하지 마라.
- 화살표(←) 줄이 이름을 댄 개념은 **전부** 질문 문장에 넣어라. 빠지면 버려지고 정해진 문장으로 바뀐다.
- answer_gist 는 근거 원문과 자료 본문에 있는 말로만 쓴다.
"""

#: 문헌(PaperDoc)이 있을 때만 시스템 프롬프트 뒤에 붙는 규칙. **없으면 프롬프트는 예전과 글자까지 같다.**
#: 교수 페르소나의 「경험」 = 문헌이다 (docs/plan/audience-evidence-and-deck-consulting.plan.md §2-1).
PAPER_SYSTEM_ADDENDUM = """

## 문헌 근거 — 이 요청에만 붙는 규칙
사용자 프롬프트에 '교수가 읽고 온 문헌' 목록이 있다. 너는 **그 문헌을 읽고 온 심사위원**이다.
- 질문 대상 개념에 「문헌」 줄이 붙어 있으면, 그 문헌을 근거로 찌르는 질문을 **우선** 써라.
  문헌 줄이 없는 개념은 예전처럼 자료로 묻는다.
- **[검색: …] 문헌은 발표자가 본 적도 인용한 적도 없다.** 교수가 따로 찾아 읽고 온 것이다.
  그 문헌에 "인용했는데"·"인용하셨는데"·"N장에서 인용한" 을 붙이지 마라 — 없는 전제를 세운 질문이 된다.
  검색 문헌은 **문헌을 주어로 세워 자료·발표와 견주는** 꼴로만 쓴다.
  (검색 문헌 예: "Kim et al. (2020)는 대기 시간이 짧아도 좌석이 부족하면 만족도가 떨어진다고 봤는데,
  발표가 말한 재방문 감소도 좌석이 부족한 경우를 포함하나요?")
- "N장에서 인용한 …" 은 **[자료 N장이 인용] 문헌에만** 쓴다 — 자료가 실제로 인용한 것이라서.
  (자료 인용 문헌 전용 예: "5장에서 인용한 Kim et al. (2020)는 좌석이 부족한 조건을
  쟀어요. 이 조사는 어느 조건인가요?")
- 높임을 쓰지 마라 — "하셨는데"·"판단하신" 이 아니라 "했는데"·"판단한".
- **인용은 목록에 있는 문헌만, 적힌 인용 표시(저자 (연도)) 그대로.** 목록 밖의 논문·저자·
  연도를 쓰면 그 질문은 통째로 버려지고 템플릿 문장으로 바뀐다.
- 그 논문에 대해 말할 수 있는 것은 「초록」 줄에 적힌 것뿐이다. 초록에 없는 결과·수치·
  조건을 논문의 것으로 말하지 마라. **"X 는 …라고 봤는데" 의 「…」 는 초록의 결과·결론 문장에서 가져온다.**
  초록이 발표의 주장을 직접 말하지 않으면 논문이 **무엇을 쟀는지·비교했는지**(목적·방법)로 끌어온다
  ("X 는 …를 …와 견줘 쟀는데"). **발표의 주장을 논문의 주장처럼 쓰지 마라** — 코드가 초록과 대조해 없으면 버린다.
- answer_gist 는 여전히 **자료 본문과 발표에서 한 말**로만 쓴다. 논문 내용을 답의 골자로
  쓰지 마라 — 발표자가 그 논문을 읽었다고 가정할 수 없다. 단, 「자료 N장이 인용」한
  문헌은 발표자가 직접 낸 것이라, 그 논문이 무엇을 다뤘는지 정도는 답에 기대해도 된다.
- 출력의 질문마다 `paper_ids` 를 더한다: 이 질문이 인용한 문헌 id 배열. 인용 안 했으면 [].
  { "node_id": "joint", "question": "…", "why": "…", "hint": "…",
    "answer_gist": "…", "answer_gist_parts": [], "paper_ids": ["d01"] }
"""

#: 지난 리허설 기억(MemoryDoc)이 질문 대상 개념에 붙었을 때만 시스템 프롬프트 뒤에 붙는 규칙. **없으면 예전과 글자까지 같다.**
MEMORY_SYSTEM_ADDENDUM = """

## 지난 리허설 — 이 요청에만 붙는 규칙
개념에 「지난 리허설: …」 줄이 있으면 같은 발표자가 이 개념을 전에 답해 본 것이다.
- 「빠졌던 점」이 있으면 그 지점을 **콕 집어** 묻는다 — 지난번과 같은 넓이로 다시 묻지 마라.
- 지난번에 통과한 개념이면 한 단계 깊게(조건·한계·반례) 묻는다. 같은 질문을 되풀이하지 마라.
- 질문 문장에 "지난번" 같은 말을 넣지 마라 — 발표자에게는 새 심사위원이다. 기억은 질문의 과녁을 정하는 데만 쓴다.
- 지난 답변 원문은 주어지지 않는다. 지난번에 무엇을 말했는지 짐작해서 쓰지 마라.
"""

#: 문헌 줄이 붙은 개념인데 질문이 문헌을 인용하지 않았을 때, **그 질문만** 골라 문헌을 얹어 다시 쓰게 하는 작은 호출.
#: 2026-09-22 실측(solar): 서가·문헌 줄·규칙을 다 실어도 첫 응답은 인용 0 이었고, 전체 프롬프트(15k자)를 나무라며
#: 다시 물어도 0 이었다 (paper_ids 를 questions 바깥에 적었다). 긴 프롬프트에서 규칙은 묻힌다 — 그래서 문헌과
#: 질문 하나만 보여 주는 짧은 과제로 바꾼다. 호출은 **한 번만**, 결과는 어댑터가 다시 검사한다 (목록 밖 인용은 버린다).
CITE_SYSTEM_PROMPT = """당신은 논문을 읽고 온 심사위원이다. 이미 쓴 질문을 받아, 붙어 있는 문헌을 근거로 찌르는 질문으로 고쳐 쓴다.

규칙
- question 문장 **안에** 문헌의 인용 표시를 **적힌 그대로** 넣어라 (예: "Kim et al. (2020)"). 표시를 바꾸거나 다른 논문을 끌어오지 마라.
  인용은 문장의 주어나 전제로 들어간다. **문장 끝에 덧붙이지 말고, «제목» 은 넣지 마라.**
  나쁨: "…메커니즘은 무엇인가요? Kim et al. (2020) «Seating and satisfaction …»"
  좋음(검색 문헌): "Kim et al. (2020)는 대기 시간이 짧아도 좌석이 부족하면 만족도가 떨어진다고 봤는데, 발표가 말한 재방문 감소도 좌석이 부족한 경우를 포함하나요?"
- **[검색: …] 문헌은 발표자가 본 적도 인용한 적도 없다.** 교수가 따로 찾아 읽고 온 것이다. 그 문헌에
  "인용했는데"·"인용하셨는데"·"N장에서 인용한" 을 쓰지 마라 — 없는 전제를 세운 질문이 되어 통째로 버려진다.
  검색 문헌은 위 「좋음」 처럼 **문헌을 주어로 세워** "X (연도)는 …라고 봤는데, 발표(자료)는 …인가요?" 꼴로만 쓴다.
- "N장에서 인용한 …" 은 **[자료 N장이 인용] 문헌에만** 쓴다.
  좋음(자료 인용 문헌 전용): "5장에서 인용한 Kim et al. (2020)는 대기 시간이 짧아도 좌석이 부족하면 만족도가 떨어진다고 봤는데, 발표가 말한 재방문 감소도 좌석이 부족한 경우를 포함하나요?"
- 문헌에 대해 말할 수 있는 것은 「초록」 줄에 적힌 것뿐이다. 초록에 없는 결과·수치·조건을 논문의 것으로 말하지 마라.
  "…라고 봤는데" 의 「…」 는 초록의 결과·결론 문장에서 가져온다. 초록이 그런 결론을 말하지 않으면 논문이 무엇을 쟀는지로
  끌어온다("X 는 …를 …와 견줘 쟀는데"). **발표의 주장을 논문의 주장처럼 쓰지 마라** — 코드가 초록과 대조해 없으면 버린다.
- 질문의 대상 개념과 묻는 요지는 유지한다. 발표자의 주장과 문헌이 어긋나거나, 문헌이 잰 조건을 발표가 밝히지 않은
  지점을 찌른다.
- 높임을 쓰지 마라 — "하셨는데"·"판단하신"·"말씀" 이 아니라 "했는데"·"판단한"·"말".
- **question 은 두 문장 이내, 200자 이내.** 논문 요지는 한 절("…라고 봤는데")로만 끌어오고 초록을 옮겨 적지 마라.
  길면 통째로 버려진다. 문헌이 여럿이어도 하나만 골라 인용한다.
- 해요체. why 는 이 문헌으로 묻는 이유 한 줄, hint 는 발표자가 답을 떠올릴 실마리 한 줄. answer_gist 는 고치지 않는다.
- paper_ids 에는 실제로 인용한 문헌 id 만 적는다.
- 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마:
{ "questions": [ { "node_id": "<그대로>", "question": "…", "why": "…", "hint": "…", "paper_ids": ["d01"] } ] }
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
    pace: PaceDoc | None = None,
    probes: list[Probe] | None = None,
) -> dict[str, str]:
    """
    노드마다 '왜 물을 만한가' 를 하나씩 정한다.

    여러 근거가 겹치면 우선순위가 높은 것이 이긴다 (모순 > 긴장 > 누락 > 흐름 결손 > 탐침 빈틈 > 자료 비중).
    alignment·flow 가 없으면 전부 core_weight 다 — 녹음 없이 자료만 올린 경로다.
    probes(주장 그래프 탐침)를 주면 그 대상 노드가 탐침 종류를 근거로 얻는다 — 자료만 올린 경로도
    "크다" 말고 **자료 안의 긴장·빈틈** 이라는 근거를 갖게 된다 (2026-09-29, P3). 안 주면 예전과 같다.
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

    # 시간을 크게 덜 쓴 장의 개념도 '덜 말함' 이다 (_rushed_slides). 이미 누락·모순이면 그대로 둔다.
    rushed = _rushed_slides(pace, graph)
    if rushed:
        for node in graph.nodes:
            if any(no in rushed for no in node.slide_nos):
                claim(node.id, "under_spoken")

    # 탐침은 claim 으로 얹는다 — QA_SOURCES 순서가 그대로 이긴다. 모순은 긴장보다, 누락은 해결 빠짐보다 앞이다.
    # 정당생략은 가장 뒤라 탐침이 덮는다: 생략이 합리적이어도 자료 **안에서** 부딪히는 말은 여전히 찔릴 자리다.
    for probe in probes or []:
        if probe.node_ids:
            claim(probe.node_ids[0], probe.kind)

    return found


#: 시간을 크게 덜 쓴 장. (실제 시간 몫) ÷ (권장 시간 몫) 이 이보다 작으면 그 장의 개념을 '덜 말함' 으로 본다.
#: 몫으로 보는 것은 총시간이 목표를 넘겨도(9/29 전사: 목표 5분 · 실제 8분 15초) 배분만 재기 위해서다.
#: 2026-09-29 수면 대본: 핵심 4장을 50초로 일부러 줄였다 → 0.60. 다른 본론 장은 0.79 이상.
RUSHED_RATIO = float(os.environ.get("CHUCKCHUCK_QA_RUSHED_RATIO", "0.7"))

#: 시간 배분을 볼 구획. 도입·맺음말·결론이 짧은 것은 정상이다.
_RUSHED_ROLES = ("body",)


def _rushed_slides(pace: PaceDoc | None, graph: ConceptGraph) -> dict[int, tuple[float, float]]:
    """
    본론의 가장 중요한 장 중 시간을 크게 덜 쓴 장 → (실제 초, 몫 기준 권장 초).

    개념 단위 정합(F-11)은 이걸 못 본다 — 4장에서 짧게 넘긴 요소도 7·8장에서 이름이 다시 나오면
    '말함' 이 된다. 발표자가 약속을 어긴 것은 개념이 아니라 **장의 시간 배분**이다.
    """
    if pace is None or not pace.slides:
        return {}
    total_act = sum(max(s.actual_sec, 0.0) for s in pace.slides)
    total_rec = sum(max(s.recommended_sec, 0.0) for s in pace.slides)
    if total_act <= 0 or total_rec <= 0:
        return {}
    top = max(s.importance_weight for s in pace.slides)
    body = {no for sec in graph.sections if sec.slide_role in _RUSHED_ROLES for no in sec.slide_nos}
    out: dict[int, tuple[float, float]] = {}
    for sp in pace.slides:
        if sp.importance_weight < top or sp.recommended_sec <= 0:
            continue
        if graph.sections and sp.slide_no not in body:
            continue
        fair = total_act * sp.recommended_sec / total_rec
        if sp.actual_sec / fair < RUSHED_RATIO:
            out[sp.slide_no] = (round(sp.actual_sec), round(fair))
    return out


def _rushed_ids(pace: PaceDoc | None, graph: ConceptGraph) -> set[str]:
    """시간을 크게 덜 쓴 장에 앉은 개념 id. 같은 근거·같은 깊이 안에서 먼저 세운다."""
    rushed = _rushed_slides(pace, graph)
    return {n.id for n in graph.nodes if any(no in rushed for no in n.slide_nos)} if rushed else set()


def _rushed_line(node: ConceptNode, rushed: dict[int, tuple[float, float]]) -> str:
    """이 개념의 장 중 시간을 덜 쓴 장이 있으면 프롬프트에 붙일 한 줄."""
    hits = [no for no in node.slide_nos if no in rushed]
    if not hits:
        return ""
    no = hits[0]
    act, fair = rushed[no]
    return (f"시간배분: {no}장을 제 몫 약 {int(fair)}초 중 {int(act)}초만 말했다 — "
            f"이 장에서 이 개념이 다른 개념과 어떻게 이어지는지(관계·조건·우선순위)를 설명하지 못했을 수 있다")


def _as_pace(pace: PaceDoc | dict | None) -> PaceDoc | None:
    return PaceDoc.from_dict(pace) if isinstance(pace, dict) else pace


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


def _hierarchy_of(graph: ConceptGraph | None, nodes: list[ConceptNode]) -> dict[str, tuple[int, int]]:
    """
    노드마다 위계 정렬 키 (depth, -서브트리가 덮는 장 수). 작을수록 앞이다.

    **위계가 weight 위다.** weight 는 글자·그림 비중이라 설명이 긴 장의 세부 개념이
    발표 주제보다 무겁게 나온다 — 그걸 그대로 줄 세우면 질문이 "글자 많은 장 순" 이
    된다 (2026-09-28 수면발표: 「수면의 질」이 7개 질문에 한 번도 안 나왔다.
    docs/review/2026-09-28_QA_지엽성_원인분석.md). 큰 개념을 먼저 묻고 아래로 내려간다.

    같은 깊이 안에서는 서브트리가 발표를 더 넓게 덮는 개념이 먼저다.
    그래프 밖 노드(extra:)는 루트와 같은 깊이로 본다 — 근거(source)가 따로 줄 세운다.
    """
    by_id = {n.id: n for n in graph.nodes} if graph is not None else {}
    span: dict[str, set[int]] = {nid: set(n.slide_nos) for nid, n in by_id.items()}
    for node in by_id.values():
        seen = {node.id}
        up = node.parent_id
        while up is not None and up in by_id and up not in seen:
            seen.add(up)
            span[up] |= set(node.slide_nos)
            up = by_id[up].parent_id
    return {
        n.id: (n.depth if n.id in by_id else 1, -len(span.get(n.id, n.slide_nos)))
        for n in nodes
    }


def _ordered_candidates(
    graph: ConceptGraph,
    alignment: AlignmentDoc | None,
    flow: FlowDiff | None,
    pace: PaceDoc | None = None,
    probes: list[Probe] | None = None,
) -> list[tuple[ConceptNode, str]]:
    """
    질문 후보를 결정적 우선순위로 정렬해 CANDIDATE_LIMIT 까지 자른다.

    근거 우선순위 → 구획 역할 → 위계(깊이 → 서브트리 장 범위) → 자료 weight 내림차순
    → 요약 유무 → 앞 슬라이드 → id 순.

    위계가 weight 위라서 CANDIDATE_LIMIT 창도 위에서부터 찬다 — 루트·상위 개념이
    triage 에 보이기도 전에 잘리는 일이 없다 (_hierarchy_of).

    구획 역할이 weight 위에 있는 것은 의도된 것이다. 표지·맺음말에만 나오는 개념은
    자료가 크게 다뤘어도 심사위원이 물을 대상이 아니라서, 크기보다 **어느 구획에
    앉았는가**가 먼저다. 본론·결론은 같은 순위라 그 안에서는 weight 가 그대로 정한다.

    요약(summary)이 빈 개념은 뒤로 민다 — 질문 문장을 쓸 재료가 없어 LLM 이
    사전식 정의 질문밖에 못 쓴다. 버리지는 않는다, 그것뿐인 그래프도 있다.

    마지막 두 단계는 동률을 깨려고 있다 — 같은 그래프면 언제나 같은 순서가 나온다.
    """
    source_of = _source_by_node(graph, alignment, flow, pace, probes)
    # 발화에만 나온 개념도 같은 축에서 같은 규칙으로 줄 세운다.
    extras = _extra_nodes(alignment)
    for extra in extras:
        source_of[extra.id] = "extra"

    everyone = [*graph.nodes, *extras]
    hierarchy_of = _hierarchy_of(graph, everyone)
    rushed = _rushed_ids(pace, graph)

    def sort_key(node: ConceptNode) -> tuple:
        return (
            _SOURCE_RANK[source_of[node.id]],
            _role_rank_of(graph, node),
            hierarchy_of[node.id][0],
            node.id not in rushed,
            hierarchy_of[node.id][1],
            -node.weight,
            0 if (node.summary or "").strip() else 1,
            min(node.slide_nos) if node.slide_nos else _NO_SLIDE,
            node.id,
        )

    ranked = sorted(everyone, key=sort_key)[:CANDIDATE_LIMIT]
    return [(node, source_of[node.id]) for node in ranked]


def _fallback_severity(source: str, weight: float) -> int:
    """
    LLM 이 severity 를 안 줬을 때. 이미 문제가 확인된 근거일수록 치명으로 본다.

    다만 '안 말했다' 의 무게는 **자료가 그 개념에 실은 비중** 에 비례한다.
    자료가 스치듯 둔 개념을 안 말한 것은 약속을 어긴 게 아니다 — 예전엔 weight 와
    무관하게 missing 이면 전부 치명(1)이라, 질문 코치가 사소한 개념부터 캐물었다.

    contradiction 은 비중과 무관하게 치명으로 둔다. 안 말한 것과 **틀리게 말한 것**
    은 다르다 — 사소한 개념이라도 자료와 어긋나게 말했으면 그건 바로잡아야 한다.
    """
    if source in ("missing", "under_spoken") and weight < MINOR_WEIGHT:
        return 2
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


def _call(engine: LLMProvider, system: str, user: str, temperature: float = 0.3) -> dict:
    """LLM 한 번 부르고 JSON 객체로. 파싱 실패는 QuestionError 로 감싼다."""
    raw = engine.complete(system=system, user=user, temperature=temperature, max_tokens=MAX_TOKENS, json_mode=True)
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


def _raw_questions(data: dict) -> list[dict]:
    return [q for q in (data.get("questions") or []) if isinstance(q, dict)]


def _covers_any_target(raw_questions: list[dict], marks: list[TriageMark]) -> bool:
    targets = {m.node_id for m in marks}
    return any(str(q.get("node_id", "") or "") in targets for q in raw_questions)


def _questions_with_retry(
    engine: LLMProvider, prompt: str, marks: list[TriageMark], system: str = QUESTION_SYSTEM_PROMPT,
) -> list[dict]:
    """질문 JSON 을 받되, **대상 id 가 하나도 없으면 파싱 실패와 같은 실패로 보고 한 번 더 묻는다.**

    2026-09-12 실측: A.X 가 0.9초 만에 파싱은 되지만 대상 node_id 가 하나도 없는 JSON 을 돌려준 일이
    측정 5회 중 2회. 그때 `_normalize_questions` 는 조용히 전부 템플릿으로 메웠고 사용자는 "라벨 —
    설명해 주세요." 만 받았다. 두 번째도 비면 그대로 템플릿으로 간다 — 구멍은 내지 않는다.
    """
    raw = _raw_questions(_call_with_retry(engine, system, prompt))
    if marks and not _covers_any_target(raw, marks):
        try:
            raw = _raw_questions(_call(engine, system + JSON_RETRY_NUDGE, prompt))
        except QuestionError:
            raw = []
    return raw


def _question_cites(q: dict, papers: PaperDoc | None) -> bool:
    """이 질문(raw)이 목록의 문헌을 인용했는가 — 문장 속 「저자 (연도)」 또는 실재하는 paper_ids."""
    if papers is None:
        return True
    ids = {r.id for r in papers.refs}
    if any(str(x) in ids for x in (q.get("paper_ids") or [])):
        return True
    return bool(_cited_ids(" ".join(str(q.get(k, "") or "") for k in ("question", "why", "hint")), papers))


def _cite_targets(
    raw: list[dict], marks: list[TriageMark], by_id: dict[str, ConceptNode], by_no: dict[int, Slide],
    papers: PaperDoc | None,
    paper_plan: dict[str, list[PaperRef]] | None = None,
) -> list[tuple[dict, ConceptNode, list[PaperRef]]]:
    """문헌 줄이 붙은 개념인데 인용이 없는 질문들. 개념당 첫 질문만 (어댑터도 개념당 하나만 쓴다).
    paper_plan 을 주면 계획에 든 개념만 고쳐 쓴다 — 상한 밖 개념에 인용을 강제하지 않는다."""
    if papers is None:
        return []
    marked = {m.node_id for m in marks}
    out, seen = [], set()
    for q in raw:
        nid = str(q.get("node_id", "") or "")
        if nid not in marked or nid in seen or nid not in by_id:
            continue
        seen.add(nid)
        node = by_id[nid]
        refs = (paper_plan.get(nid, []) if paper_plan is not None
                else _papers_for_node(papers, node, _anchor_nos(node, by_no)))
        if refs and str(q.get("question", "") or "").strip() and not _question_cites(q, papers):
            out.append((q, node, refs))
    return out


def _cite_prompt(targets: list[tuple[dict, ConceptNode, list[PaperRef]]]) -> str:
    parts = ["[TASK] qa-cite", "", "아래 질문마다 붙은 문헌을 근거로 question·why·hint 를 고쳐 써라. node_id 는 그대로.", ""]
    for q, node, refs in targets:
        parts.append(f"### ({node.id}) {node.label}")
        parts.append(f"question: {str(q.get('question', '') or '')}")
        if q.get("why"):
            parts.append(f"why: {str(q.get('why') or '')}")
        if q.get("hint"):
            parts.append(f"hint: {str(q.get('hint') or '')}")
        for ref in refs:
            parts.append("문헌 " + _paper_line(ref))
        parts.append("")
    return "\n".join(parts)


#: 고쳐 쓴 문장에서 지울 것 — 프롬프트의 «제목» 표기를 그대로 베낀 조각. 09-23 실측(solar): 질문 끝에 "Stothart et al. (2015)
#: «The attentional cost …»" 를 덧붙였다. 제목은 카드가 그리지 문장에 들어갈 것이 아니다.
_TITLE_SPAN_RE = re.compile(r"\s*«[^»]*»")
#: 문장 끝에 덧붙인 인용 표시 — 「…인가요? Stothart et al. (2015)」 꼴. 끝맺음 뒤에 오는 인용은 뗀다 (앞에 인용이 또 있으면 그것이 남는다).
_TRAILING_CITE_RE = re.compile(r"([?？.!]|요|까)\s*(?:[A-Z][A-Za-z\-']+(?:\s+(?:et\s+al\.|&\s+[A-Z][A-Za-z\-']+|and\s+[A-Z][A-Za-z\-']+))?\s*\(\d{4}[a-z]?\)\s*[,·;]?\s*)+$")


def _clean_rewritten(text: str) -> str:
    text = _TITLE_SPAN_RE.sub("", str(text or ""))
    text = _TRAILING_CITE_RE.sub(r"\1", text)
    return _WS_RE.sub(" ", text).strip() if "_WS_RE" in globals() else " ".join(text.split())


def _apply_cite_rewrite(raw: list[dict], targets: list[tuple[dict, ConceptNode, list[PaperRef]]], data: dict,
                        papers: PaperDoc) -> list[dict]:
    """고쳐 쓴 질문을 원래 자리에 얹는다. **문헌을 실제로 인용한 것만** 받고, 나머지는 원문 그대로."""
    rewritten = {str(x.get("node_id", "") or ""): x for x in _raw_questions(data)}
    allowed = {ref.id for _, _, refs in targets for ref in refs}
    for q, node, _ in targets:
        new = rewritten.get(node.id)
        if not new or not str(new.get("question", "") or "").strip():
            continue
        candidate = {**q, **{k: _plain_speech(_clean_rewritten(new[k])) for k in ("question", "why", "hint") if new.get(k)},
                     "paper_ids": [str(x) for x in (new.get("paper_ids") or []) if str(x) in allowed]}
        # 09-23 실측(solar): 초록을 옮겨 적은 세 문장짜리 질문이 와서 QA_TEXT_MAX 에서 잘려 끝맺음이 사라졌다(반말로 찍힘).
        # 길거나 해요체 물음으로 끝나지 않으면 원문을 지킨다 — 인용 하나 얻자고 화면 말투를 깨지 않는다.
        q_text = _polite_question(str(candidate.get("question", "") or ""))
        if len(q_text) > QA_TEXT_MAX or not _POLITE_END_RE.search(q_text):
            continue
        candidate["question"] = q_text
        # paper_ids 만 적고 문장에 인용이 없거나, 목록 밖 논문을 끌어왔으면 원문을 지킨다 (어댑터가 버릴 문장이다).
        # 검색 문헌에 「인용했는데」 를 씌운 거짓 전제도 원문을 지킨다 — 09-24 실측, 판정이 전제부터 틀렸다고 했다.
        text = " ".join(str(candidate.get(k, "") or "") for k in ("question", "why", "hint"))
        if (_cited_ids(text, papers) and not _ungrounded_citation(text, papers)
                and not _claims_presenter_cited(text, papers)):
            q.clear()
            q.update(candidate)
    return raw


def _questions_with_papers(
    engine: LLMProvider, prompt: str, marks: list[TriageMark], system: str,
    by_id: dict[str, ConceptNode], by_no: dict[int, Slide], papers: PaperDoc | None,
    paper_plan: dict[str, list[PaperRef]] | None = None,
) -> list[dict]:
    """질문을 받은 뒤, 문헌이 붙었는데 인용이 없는 질문만 골라 qa-cite 로 **한 번** 고쳐 쓴다. 실패하면 첫 응답 그대로."""
    raw = _questions_with_retry(engine, prompt, marks, system)
    targets = _cite_targets(raw, marks, by_id, by_no, papers, paper_plan)
    if targets:
        try:
            raw = _apply_cite_rewrite(raw, targets, _call(engine, CITE_SYSTEM_PROMPT, _cite_prompt(targets)), papers)
        except QuestionError:
            pass
    return _verify_paper_claims(engine, raw, marks, papers)


# ---------------------------------------------------------------------------
# 인용 주장 검사 — 「X (연도)는 …라고 봤는데」 의 「…」 가 정말 초록에 있는가
#
# 2026-09-29 실측(solar): "Paulsrud et al. (2026)는 수면의 질이 시간보다 중요하다고 보았는데, …" 가 나왔다.
# 그 논문은 아이들의 주관·객관 수면 측정이 얼마나 맞는지 본 메타분석이고, 질이 시간보다 중요하다는 말은 초록 어디에도
# 없다 — 발표의 주장을 논문 입에 넣은 것이다. 프롬프트 규칙(「초록에 없는 것을 말하지 마라」)만으로는 안 지켜졌다
# (09-12 교훈과 같다). 그래서 코드가 받는다: 주장을 붙인 인용 질문마다 LLM 에 **초록에서 그대로 베낀 근거 문장**을
# 내게 하고, 그 문장이 초록에 글자 그대로 있는지를 코드가 확인한다. 근거가 없으면 초록이 실제로 말하는 것으로 고친
# 문장(역시 근거 문장 필수)을 받고, 그것도 안 되면 인용을 빼고 템플릿으로 보낸다. 호출은 트랙당 한 번(인용 질문 ≤2).
# ---------------------------------------------------------------------------

#: 문헌을 주어로 세워 무언가를 **봤다·밝혔다** 고 말하는 꼴. 이런 동사가 없는 인용(「X 의 개념이 여기 어떻게 적용되나요?」·
#: 「3장에서 인용한 X 는 무엇을 쟀나요?」)은 논문에 주장을 붙이지 않으니 검사하지 않는다.
_PAPER_CLAIM_RE = re.compile(
    r"(봤|보았|밝혔|밝혀냈|보고했|주장했|제시했|제안했|발견했|확인했|보여\s?줬|보여\s?주었|보였|나타냈|결론\S*|지적했|강조했|"
    r"설명했|말했|규정했|정의했|입증했|증명했|시사했|드러냈|[다라]고\s?했|[다라]고\s?하였|[다라]는\s?(?:결과|결론))"
)
#: 인용 표시 바로 뒤의 주어·화제 조사 — 「Driller et al. (2026)는 …」. 논문을 주어로 세웠다는 뜻이다.
_PAPER_SUBJECT_RE = re.compile(r"\s?(?:는|은|이|가|에서는|의\s?연구는|연구는)\s")
#: 근거 문장으로 받는 최소 길이. 몇 낱말짜리 조각(「sleep quality」)은 어느 초록에나 있어 근거가 못 된다.
PAPER_EVIDENCE_MIN = 25

PAPER_CHECK_SYSTEM_PROMPT = """당신은 논문 인용을 검사하는 편집자다. 질문이 논문에 대해 한 말이 그 논문의 초록에 실제로 적혀 있는지 본다.

규칙
- supported 는 초록의 문장이 질문이 논문에 붙인 주장을 **직접** 말할 때만 true 다. 비슷한 주제를 다루기만 하면 false 다.
  발표의 주장을 논문의 주장처럼 쓴 것이면 false 다.
- 초록은 문장마다 [번호] 가 붙어 있다. evidence_no 는 그 주장을 **직접** 말하는 초록 문장의 번호다. 없으면 0.
- supported 가 false 면 rewrite 에 고친 질문을 쓴다. 초록이 **실제로 말하는 것**(연구 목적·방법·결과 중 하나)을 한 절로
  논문에 붙이고, 발표의 개념과 견주는 물음은 유지한다. 예: "X (연도)는 …를 …와 견줘 쟀는데, 발표의 '…'는 …인가요?"
  논문 내용은 **앞 절(「…는데,」)에만** 두고, 물음은 발표에 대해 묻는다 — 「X 는 …라고 했나요?」 처럼 논문 내용 자체를 묻지 마라.
  인용 표시(저자 (연도))는 적힌 그대로 문장 안에 넣는다. 해요체, 두 문장 이내, 200자 이내, 높임 금지.
  rewrite_evidence_no 는 고친 문장이 논문에 붙인 내용을 말하는 초록 문장의 번호다. 초록으로 고칠 수 없으면 rewrite 는 "", 번호는 0.
- 번호는 반드시 초록에 붙은 [번호] 중 하나다. 질문 문장이나 고친 문장을 근거 자리에 베끼지 마라.
- 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.
{ "checks": [ { "node_id": "<### 줄의 괄호 안 그대로>", "supported": false, "evidence_no": 0, "rewrite": "…", "rewrite_evidence_no": 3 } ] }"""


def _flat(text: str) -> str:
    """근거 대조용 — 대소문자·공백·따옴표 모양·끝 마침표 차이는 무시한다."""
    text = str(text or "").lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return " ".join(text.split()).strip(" .\"'")


def _evidence_in_abstract(evidence: str, ref: PaperRef) -> bool:
    ev = _flat(evidence)
    return len(ev) >= PAPER_EVIDENCE_MIN and ev in _flat(ref.abstract)


#: 초록 문장 경계 — 마침표·물음표 뒤 공백 다음이 대문자·숫자일 때. "et al. (2015)"·"e.g. sleep" 에서는 안 자른다.
_ABSTRACT_SENT_RE = re.compile(r"(?<=[.?!])\s+(?=[A-Z0-9(])(?<!\bal\.\s)(?<!\be\.g\.\s)(?<!\bi\.e\.\s)")


def _abstract_sentences(ref: PaperRef) -> list[str]:
    return [x.strip() for x in _ABSTRACT_SENT_RE.split(ref.abstract or "") if len(x.strip()) >= PAPER_EVIDENCE_MIN]


def _evidence_of(c: dict, key: str, ref: PaperRef) -> str:
    """검사 응답이 가리킨 초록 문장. 번호(`<key>_no`)가 먼저다 — 09-29 실측(solar): 「초록 문장을 그대로 복사」 하라 했더니
    세 번 중 세 번 고친 질문 문장을 근거 자리에 베꼈다. 번호는 초록에 실제로 있는 문장만 가리킬 수 있다.
    글자 그대로 옮긴 인용(`<key>`)도 초록에 있으면 받는다. 둘 다 아니면 "" — 근거 없음."""
    sents = _abstract_sentences(ref)
    try:
        no = int(c.get(f"{key}_no") or 0)
    except (TypeError, ValueError):
        no = 0
    if 1 <= no <= len(sents):
        return sents[no - 1]
    text = str(c.get(key, "") or "")
    return text if _evidence_in_abstract(text, ref) else ""


def _claimed_ref(q: dict, papers: PaperDoc | None, key: str = "question") -> PaperRef | None:
    """이 질문(의 key 칸)이 주장을 붙인 문헌. 인용이 없거나 주장 동사가 없으면 None — 검사할 것이 없다."""
    if papers is None:
        return None
    text = str(q.get(key, "") or "")
    by_id = {r.id: r for r in papers.refs}
    for pid in _cited_ids(text, papers):
        ref = by_id.get(pid)
        at = text.find(ref.cite_key) if ref is not None and ref.cite_key else -1
        if at < 0:
            continue
        # 논문을 주어로 세운 절만 본다 — 이음새(는데·지만)나 문장 끝까지. 「…를 발표에서 어떻게 설명했나요?」 의
        # 「설명했」 은 발표자에게 묻는 말이지 논문의 주장이 아니다 (09-29 실측에서 이것까지 잡았다).
        tail = text[at + len(ref.cite_key):]
        stop = _CLAIM_JOINT_RE.search(tail)
        end = re.search(r"[?？!]|[가-힣]\.(?:\s|$)", tail)
        cut = min(x.start() for x in (stop, end) if x) if (stop or end) else len(tail)
        if stop is None or stop.start() != cut:
            continue          # 이음새 없이 끝나는 문장은 논문에 주장을 붙이지 않고 묻기만 한다
        # 논문이 주어(는·은·이·가)인 절이 이음새로 끝나면 동사와 상관없이 주장이다 — 09-29 실측: 「…로 구분했는데」 가
        # 동사 목록을 비껴갔다. 동사 목록은 주어 조사가 없는 꼴(「X 에 따르면 …라고 했는데」)을 잡는 보조다.
        if _PAPER_SUBJECT_RE.match(tail) or _PAPER_CLAIM_RE.search(tail[:cut]):
            return ref
    return None


def _paper_check_prompt(targets: list[tuple[dict, PaperRef]]) -> str:
    parts = ["[TASK] qa-paper-check", "", "질문마다 논문에 붙인 주장이 초록에 있는지 검사하라. node_id 는 그대로.", ""]
    for q, ref in targets:
        parts.append(f"### ({q.get('node_id', '')})")
        parts.append(f"question: {q.get('question', '')}")
        parts.append(f"문헌 ({ref.id}) {ref.cite_key} «{ref.title}»")
        parts.append("초록:")
        parts += [f"[{i}] {x}" for i, x in enumerate(_abstract_sentences(ref), 1)]
        parts.append("")
    return "\n".join(parts)


#: 논문 절을 떼고 남은 본론이 앞 절을 가리키면(「그 주장을 뒷받침하나요?」) 뗄 수 없다 — 가리킬 것이 사라진다.
_CLAIM_ANAPHORA_RE = re.compile(r"(그|이|해당)\s?(주장|결과|결론|연구|논문|정의|관점|견해|발견|지적)|(?:^|\s)(그|해당)\s|그것|이것|그와|이와|그렇다면|반면")
#: 「X 는 …라고 봤는데, 본론」 의 이음새. 첫 이음새에서 자른다.
_CLAIM_JOINT_RE = re.compile(r"(?:는데|지만|으나|는데도)\s*,?\s*")
#: 떼고 남은 본론의 최소 길이 — 이보다 짧으면 질문이 아니라 꼬리다.
CLAIM_REST_MIN = 12


def _drop_paper_clause(text: str, ref: PaperRef) -> str:
    """「X (연도)는 …라고 봤는데, 본론?」 에서 논문 절을 떼고 본론만. 뗄 수 없으면 "".

    템플릿으로 떨어지는 것보다 LLM 이 쓴 본론(발표를 겨냥한 물음)을 살리는 쪽이 낫다 — 09-29 실측에서 템플릿은
    개념 요약을 그대로 이어 붙인 「왜 수면의 질이 시간 × 연속성 × … 으로 정의되는지 — 설명해 주세요」 였다."""
    text = str(text or "")
    at = text.find(ref.cite_key) if ref.cite_key else -1
    if at < 0:
        return ""
    m = _CLAIM_JOINT_RE.search(text, at + len(ref.cite_key))
    if not m:
        return ""
    rest = text[m.end():].strip(" ,")
    if (len(rest) < CLAIM_REST_MIN or _CLAIM_ANAPHORA_RE.search(rest) or ref.cite_key in rest
            or not _POLITE_END_RE.search(rest)):
        return ""
    return rest


def _strip_paper_claim(q: dict, ref: PaperRef) -> None:
    """근거 없는 인용 주장. 질문은 논문 절만 떼어 본론을 살리고, 못 떼면 비워 템플릿으로 보낸다 (_normalize_questions 의 `or`).
    이유·힌트가 그 문헌을 말했으면 비운다 — 확인 못 한 주장을 거기서 되풀이하지 않게."""
    q["question"] = _drop_paper_clause(str(q.get("question", "") or ""), ref)
    for key in ("why", "hint"):
        if ref.cite_key and ref.cite_key in str(q.get(key, "") or ""):
            q[key] = ""
    q["paper_ids"] = []
    # 논문 절을 뗐다는 표시 — 골자·요소에 남은 논문 이야기를 `_normalize_questions` 가 걷어 낸다. 09-29 기준선 §5-5:
    # 질문의 논문 절만 떼고 골자의 「문헌의 '노동 시장 협상 모델'」 은 남아 채점 기준이 됐다.
    q["_paper_stripped"] = ref.id


def _rewrite_miss(rewrite: str, ref: PaperRef, c: dict, papers: PaperDoc | None) -> str:
    """고친 문장을 못 받는 이유 한 마디. 받을 수 있으면 "". 로그에 남겨 어느 규율에서 떨어지는지 본다."""
    if not rewrite:
        return "고친 문장 없음"
    if ref.cite_key not in rewrite:
        return "인용 표시 없음"
    if len(rewrite) > QA_TEXT_MAX or not _POLITE_END_RE.search(rewrite):
        return "길이·말끝"
    if _cites_scaffold(rewrite) or _claims_presenter_cited(rewrite, papers) or _ungrounded_citation(rewrite, papers):
        return "자리표시·거짓 인용"
    if not _evidence_of(c, "rewrite_evidence", ref):
        return f"근거 번호 없음({c.get('rewrite_evidence_no')})"
    # 「X 는 …는데, 발표는 …?」 꼴이어야 한다 — 09-29 실측: 「X 는 …라고 했나요?」 로 논문 내용 자체를 발표자에게 물었다
    if _claimed_ref({"question": rewrite}, papers) is not ref:
        return "전제 절 꼴 아님"
    return ""


def _checks_by_node(data: dict, checkable: list[tuple[dict, PaperRef]]) -> dict[str, dict]:
    """검사 응답을 질문(node_id)에 잇는다. node_id 가 틀리면 순서로 받는다 — 09-29 실측(solar): node_id 자리에
    문헌 id(s05)를 적었다. f24 번역 응답(09-22)과 같은 버릇이다. 개수가 다르면 순서를 믿지 않는다."""
    rows = [c for c in (data.get("checks") or []) if isinstance(c, dict)]
    ids = [str(q.get("node_id", "") or "") for q, _ in checkable]
    out = {str(c.get("node_id", "") or ""): c for c in rows if str(c.get("node_id", "") or "") in ids}
    if len(rows) == len(ids):
        for nid, c in zip(ids, rows):
            out.setdefault(nid, c)
    return out


def _verify_paper_claims(
    engine: LLMProvider, raw: list[dict], marks: list[TriageMark], papers: PaperDoc | None,
) -> list[dict]:
    """주장을 붙인 인용 질문을 초록과 대조한다 (위 절 주석). 대상이 없으면 LLM 을 부르지 않는다.

    **확인 못 한 주장은 버린다** — 검사 호출이 실패해도, 초록이 비어 있어도 같다. 근거를 못 댄 인용 하나 잃는 것이
    발표자에게 없는 논문 주장을 믿게 하는 것보다 싸다. 개념당 첫 질문만 본다 (어댑터도 첫 질문만 쓴다)."""
    marked, seen = {m.node_id for m in marks}, set()
    targets: list[tuple[dict, PaperRef]] = []
    firsts: list[dict] = []
    for q in raw:
        nid = str(q.get("node_id", "") or "")
        if nid not in marked or nid in seen:
            continue
        seen.add(nid)
        firsts.append(q)
        ref = _claimed_ref(q, papers)
        if ref is not None:
            targets.append((q, ref))
    if not targets:
        _drop_side_claims(firsts, papers, verified=set())
        return raw
    checks = _run_paper_check(engine, [(q, ref) for q, ref in targets if ref.abstract])
    pending: list[tuple[dict, PaperRef, str]] = []
    for q, ref in targets:
        nid = str(q.get("node_id", "") or "")
        c = checks.get(nid) or {}
        evidence = _evidence_of(c, "evidence", ref)
        if c.get("supported") is True and evidence:
            sys.stderr.write(f"[f08] 인용 주장 검사 {nid} {ref.cite_key}: 초록에 근거 있음 — 그대로 · 근거: {evidence[:100]}\n")
            continue
        # 첫 응답 질문과 같은 손질 — 문장 단위로 줄이고 말끝을 고친다 (09-29 실측: 고친 문장 3개 중 2개가 길이·말끝에서 떨어졌다)
        rewrite = _fit_question(_polite_question(_plain_speech(_clean_rewritten(str(c.get("rewrite", "") or "")))), trap=False)
        miss = _rewrite_miss(rewrite, ref, c, papers)
        if not miss:
            pending.append((q, ref, rewrite))
            continue
        why = "초록 없음" if not ref.abstract else ("검사 응답 없음" if not c else f"초록에 없음, 고친 문장 못 씀({miss})")
        _strip_logged(q, ref, why)
    # 고친 문장도 한 번 더 검사한다 — 09-29 실측: 번호만 맞으면 통과하던 때, 「REM 중 부정적 정서가 해소된다」 로 고치고
    # 근거로는 NREM 방추파 문장 번호를 댔다. 번호는 초록 밖을 못 가리킬 뿐, 맞는 문장을 가리킨다는 보장은 없다.
    rechecks = _run_paper_check(engine, [({"node_id": q.get("node_id", ""), "question": rw}, ref) for q, ref, rw in pending])
    for q, ref, rewrite in pending:
        nid = str(q.get("node_id", "") or "")
        c = rechecks.get(nid) or {}
        evidence = _evidence_of(c, "evidence", ref)
        if c.get("supported") is True and evidence:
            q["question"] = rewrite
            q["paper_ids"] = [ref.id]
            sys.stderr.write(f"[f08] 인용 주장 검사 {nid} {ref.cite_key}: 초록에 없음 — 초록 근거로 고쳐 씀 · 근거: {evidence[:100]}\n")
        else:
            _strip_logged(q, ref, "초록에 없음, 고친 문장도 재검사에서 근거 없음")
    verified = {(str(q.get("node_id", "") or ""), ref.id) for q, ref in targets if q.get("paper_ids") == [ref.id]}
    _drop_side_claims(firsts, papers, verified)
    return raw


def _run_paper_check(engine: LLMProvider, pairs: list[tuple[dict, PaperRef]]) -> dict[str, dict]:
    """검사 1콜. 대상이 없거나 응답이 깨지면 빈 dict — 호출자는 「확인 못 함」 으로 다룬다.
    검사는 판정이라 흔들리면 안 된다 — 09-29 실측: 같은 Nishida 주장을 0.3 에서 한 번은 근거 없음, 한 번은 [8] 로 봤다."""
    if not pairs:
        return {}
    try:
        return _checks_by_node(_call(engine, PAPER_CHECK_SYSTEM_PROMPT, _paper_check_prompt(pairs), temperature=0.0), pairs)
    except QuestionError:
        return {}


def _strip_logged(q: dict, ref: PaperRef, why: str) -> None:
    before = str(q.get("question", "") or "")
    _strip_paper_claim(q, ref)
    sys.stderr.write(f"[f08] 인용 주장 검사 {q.get('node_id', '')} {ref.cite_key}: {why} — "
                     f"{'논문 절만 뗌' if q['question'] else '템플릿으로'} · 질문: {before[:80]}\n")


def _drop_side_claims(firsts: list[dict], papers: PaperDoc | None, verified: set[tuple[str, str]]) -> None:
    """이유·힌트·골자 칸이 논문에 주장을 붙였으면 비운다 (템플릿이 메운다). 질문 문장이 같은 문헌으로 검사를 통과했을 때만 둔다.

    09-29 실측(solar): 질문은 인용 없이 묻고 이유 칸에 「Sowers et al. (2008)는 …로 정의했다」 를 적었다. 이유는 질문 말풍선
    아래 그대로 나가고 paper_ids 도 거기서 추론된다 — 검사 없이 두면 질문 문장에서 막은 거짓 주장이 한 줄 아래로 새어 나간다.
    LLM 을 따로 부르지 않는다: 이유·힌트는 없어도 질문이 서고, 템플릿이 있다."""
    for q in firsts:
        nid = str(q.get("node_id", "") or "")
        for key in ("why", "hint", "answer_gist"):   # 골자는 「이렇게 답하면 좋았어요」 로 화면에 나간다
            ref = _claimed_ref(q, papers, key)
            if ref is not None and (nid, ref.id) not in verified:
                q[key] = ""


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


def _speech_excerpt(
    node: ConceptNode, transcript: Transcript | None, slide_nos: list[int] | None = None
) -> str:
    """이 개념의 근거 장에서 실제로 한 말. Transcript.by_slide 를 slide_no 로 조인한다.
    `slide_nos` 를 주면 그 장만 (anchor 장) — 안 주면 node.slide_nos 전부다."""
    if transcript is None:
        return ""
    nos = node.slide_nos if slide_nos is None else slide_nos
    said = " ".join(
        text
        for text in (transcript.text_for_slide(no).strip() for no in nos)
        if text
    )
    if len(said) <= SPEECH_EXCERPT_MAX:
        return said
    return said[: SPEECH_EXCERPT_MAX - 1].rstrip() + "…"


def _slides_by_no(slidedoc: SlideDoc | None) -> dict[int, Slide]:
    """
    `slide_no → Slide` 색인. **build_questions 에서 한 번만 만든다** —
    개념마다 slides 를 훑으면 개념 수 × 장 수가 된다.
    """
    if slidedoc is None:
        return {}
    return {s.slide_no: s for s in slidedoc.slides}


def _anchor_nos(node: ConceptNode, by_no: dict[int, Slide]) -> list[int]:
    """
    이 개념의 **anchor 장** — F-07 의 slide_nos 안에서 본문이 실제로 이 개념을 말하는
    장만 최대 ANCHOR_MAX 개. 자료가 없으면(by_no 비면) 좁힐 근거가 없어 slide_nos 그대로다.
    """
    # 근거 장이 없는 개념(정합이 만든 extra 개념 등)은 자료 본문도 없다 — 덱 전체에서
    # 찾아 붙이면 "이 개념의 근거 장" 이 아니라 아무 장이 된다.
    if not by_no or not node.slide_nos:
        return list(node.slide_nos)
    texts = {
        no: clean_slide_text(s.raw_text or "")
        for no, s in by_no.items()
        if no in node.slide_nos
    }
    return anchor_slides(node.label, node.summary, node.slide_nos, texts)


def _slide_body(
    node: ConceptNode, by_no: dict[int, Slide], slide_nos: list[int] | None = None
) -> str:
    """
    이 개념의 **근거 장 자료 본문**. `_speech_excerpt` 와 같은 규칙으로 자른다
    (근거 장만 · 한 줄로 이어 붙여 · 상한에서 절단).

    발화가 "말로 뭐라고 했나" 라면 이건 "자료에 뭐라고 써 있나" 다. 둘을 나란히
    줘야 모범답이 자료 밖으로 나가는 것을 프롬프트가 가리킬 수 있다.
    """
    if not by_no or SLIDE_BODY_MAX <= 0:
        return ""
    nos = node.slide_nos if slide_nos is None else slide_nos
    # 정제해서 싣는다 — 이미지 캡션·HTML 을 걷어내고 줄바꿈을 접는다 (_evidence).
    # 안 걷어내면 예산의 70% 가 "A well-lit, modern wooden desk…" 로 찬다.
    body = " ".join(
        text
        for text in (
            clean_slide_text(by_no[no].raw_text or "") for no in nos if no in by_no
        )
        if text
    )
    if len(body) <= SLIDE_BODY_MAX:
        return body
    return body[: SLIDE_BODY_MAX - 1].rstrip() + "…"


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
    rushed: dict[int, tuple[float, float]] | None = None,
    probe_of: dict[str, Probe] | None = None,
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
        rushed_line = _rushed_line(node, rushed or {})
        if rushed_line:
            parts.append(f"    {rushed_line}")
        # 탐침 각도는 근거가 그 탐침인 개념에만 — 흐름 줄과 같은 이유다. 주장이 없으면 이 줄은 안 생긴다.
        probe = (probe_of or {}).get(node.id)
        if probe is not None and source == probe.kind:
            parts.append(f"    {_probe_line(probe)}")

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


def _probe_line(probe: Probe) -> str:
    """프롬프트에 붙일 「탐침(kind): 각도」 한 줄."""
    return f"탐침({probe.kind}): {probe.angle}"


def _probe_evidence_line(probe: Probe) -> str:
    """「근거 원문: S1 «…» · S4 «…»」 — 탐침을 받치는 자료 원문 인용 (F-26 이 원문과 대조한 것만 온다)."""
    return "근거 원문: " + " · ".join(f"S{e.slide_no} «{e.quote}»" for e in probe.evidence)


def _probes_by_node(probes: list[Probe]) -> dict[str, Probe]:
    """노드 id → 그 노드의 가장 우선인 탐침. probes 는 derive_probes 가 종류 우선순위로 정렬해 뒀다."""
    out: dict[str, Probe] = {}
    for p in probes:
        if p.node_ids and p.node_ids[0] not in out:
            out[p.node_ids[0]] = p
    return out


def _normalize_marks(
    raw_marks: list[dict],
    pairs: list[tuple[ConceptNode, str]],
    graph: ConceptGraph | None = None,
    rushed: set[str] | None = None,
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
    return _rerank(marks, pairs, graph, rushed)


def _spread_adjacent(
    ordered: list[TriageMark],
    graph: ConceptGraph | None,
    tier_of: dict[str, tuple] | None = None,
) -> list[TriageMark]:
    """
    같은 층에서 이미 뽑은 개념과 **한 덩어리인** 개념은 그 층 뒤로 민다.

    이웃끼리 나란히 물으면 "왜 이걸 골랐나" 와 "이걸 어떻게 쓰나" 처럼 사용자가
    한 번에 답할 수 있는 질문이 두 개 나온다 — 같은 맥락을 다르게 물어 놓고
    다른 답을 요구하는 꼴이다. edges 가 그 인접을 이미 알고 있으니 LLM 이 필요 없다.

    한 덩어리로 보는 것은 둘이다 — relates 로 이어진 개념, **같은 부모 밑 형제**.
    부모·자식은 한 덩어리로 보지 않는다. 큰 개념을 묻고 그 아래로 내려가는 것은
    되풀이가 아니라 심화다. 예전엔 parent 도 인접으로 쳐서, 잎이 먼저 뽑히면
    **부모가 밀려났다** — 위계가 순위에 거꾸로 쓰였다
    (docs/review/2026-09-28_QA_지엽성_원인분석.md §1-4).

    **강등은 같은 층(tier_of — 근거·구획·깊이) 안에서만 일어난다.** 근거가 다른 두
    개념은 서로 다른 이유로 뽑힌 것이라 중복이 아니고, 깊이를 넘어 밀면 형제 하나
    때문에 잎이 상위 개념 앞으로 올라온다. tier_of 가 없으면 근거로만 층을 나눈다.

    **제외가 아니라 강등이다.** 트랙 상한에 여유가 있으면 여전히 물어본다.
    모순·누락 근거는 아예 면제된다 (_ADJACENCY_EXEMPT).
    """
    if graph is None or len(ordered) < 2:
        return ordered

    parent_of = {n.id: n.parent_id for n in graph.nodes}
    related: dict[str, set[str]] = {}
    for e in graph.relates_edges:
        related.setdefault(e.from_id, set()).add(e.to_id)
        related.setdefault(e.to_id, set()).add(e.from_id)

    def tier(m: TriageMark) -> tuple:
        if tier_of is not None and m.node_id in tier_of:
            return tier_of[m.node_id]
        return (_SOURCE_RANK[m.source],)

    result: list[TriageMark] = []
    # ordered 는 이미 층 순서로 정렬돼 있어 groupby 가 그대로 층 묶음이 된다.
    for _, group in groupby(ordered, key=tier):
        kept: list[TriageMark] = []
        demoted: list[TriageMark] = []
        chosen: set[str] = set()
        chosen_parents: set[str] = set()
        for mark in group:
            parent = parent_of.get(mark.node_id)
            clash = bool(related.get(mark.node_id, set()) & chosen) or (
                parent is not None and parent in chosen_parents
            )
            if mark.source not in _ADJACENCY_EXEMPT and clash:
                demoted.append(mark)
                continue
            kept.append(mark)
            chosen.add(mark.node_id)
            if parent is not None:
                chosen_parents.add(parent)
        result.extend(kept + demoted)
    return result


def _rerank(
    marks: list[TriageMark],
    pairs: list[tuple[ConceptNode, str]],
    graph: ConceptGraph | None = None,
    rushed: set[str] | None = None,
) -> list[TriageMark]:
    """
    LLM 이 매긴 severity 를 반영해 최종 순위(rank)를 다시 매긴다.

    **이 재정렬이 triage 를 따로 부르는 이유다.** rank 가 곧 트랙 상한에 들어갈
    순서이므로, 여기서 severity 를 안 쓰면 1차 호출은 화면 표시용 장식이 되고
    1분 트랙이 '가벼움' 개념을 물어보게 된다.

    다만 source 는 severity 보다 위다. 모순·누락은 이미 **확인된 사실**이고
    severity 는 LLM 의 짐작이라, 리포트가 "누락" 이라 말한 개념을 짐작이 밀어내면
    두 화면이 어긋난다. 그래서 근거 안에서만 severity 가 순위를 정한다.

    같은 근거 안에서는 위계(깊이)가 severity 위다 — 큰 개념부터 묻고 내려간다.
    severity 는 같은 깊이 안의 서열을 정한다 (_hierarchy_of).

    나머지 키(서브트리 장 범위 → 자료 weight → 앞 슬라이드 → id)는 동률을 깨기 위한 것이다 —
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
    # 위계는 severity 위다 — 큰 개념부터 묻고 내려간다. severity 는 같은 깊이 안의
    # 서열을 정하고, 서브트리 범위는 severity 가 같을 때만 가른다.
    hierarchy_of = _hierarchy_of(graph, [node for node, _ in pairs])
    ordered = sorted(
        marks,
        key=lambda m: (
            _SOURCE_RANK[m.source],
            role_of.get(m.node_id, _ROLE_RANK_FALLBACK),
            hierarchy_of[m.node_id][0],
            # 시간을 크게 덜 쓴 장의 개념이 같은 근거·깊이 안에서 먼저다 — LLM 짐작(severity)보다
            # 발표 시간표라는 관측이 위다 (2026-09-29 수면 전사: 2·3장 '덜 말함' 이 4장 요소를 밀어냈다).
            m.node_id not in (rushed or set()),
            m.severity,
            hierarchy_of[m.node_id][1],
            -m.doc_weight,
            no_summary_of.get(m.node_id, 0),
            slide_of[m.node_id],
            m.node_id,
        ),
    )
    # 순위가 정해진 뒤에 인접을 편다. 정렬 키에 섞으면 "누가 먼저 뽑혔나" 를
    # 알 수 없어 인접 판단이 불가능하다 — 이것은 순서에 의존하는 연산이다.
    tier_of = {
        m.node_id: (
            _SOURCE_RANK[m.source],
            role_of.get(m.node_id, _ROLE_RANK_FALLBACK),
            hierarchy_of[m.node_id][0],
        )
        for m in marks
    }
    ordered = _spread_adjacent(ordered, graph, tier_of)
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
    memory: MemoryDoc | dict | None = None,
    pace: PaceDoc | dict | None = None,
    claims: ClaimDoc | dict | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> QaTriage:
    """
    ConceptGraph(+선택 AlignmentDoc·FlowDiff·Context·Transcript·MemoryDoc) → QaTriage.

    memory(F-25) 를 주면 **지난 리허설에서 못 넘긴 개념이 앞으로 온다** — 순위 안에서의 상대 순서는 그대로다
    (결정적). 트랙 상한 때문에 뒤로 밀려 안 물어보던 개념도, 지난번에 막혔으면 이번엔 물어본다. 안 주면 예전과 같다.

    후보와 순위(rank)·근거(source)는 코드가 결정적으로 정하고,
    LLM 은 severity·trap·angle 만 채운다. 빠뜨린 후보는 결정적 폴백으로 메운다.

    개념은 홀로 주지 않는다 — parent 경로(트리 뷰)와 relates 이웃(그래프 뷰)을 함께 준다.
    심사위원 질문은 "이게 저것과 무슨 관계인가" 로 들어오기 때문이다.
    transcript 를 주면 근거 장의 실제 발화까지 붙어 함정 판단이 정확해진다
    (Transcript.by_slide 를 slide_no 로 조인).

    alignment·flow·transcript 없이 그래프만으로도 동작한다 — 녹음 없이 자료만 올린
    경로에서 근거는 전부 core_weight 가 되고 자료 weight 순으로 후보가 나온다.
    트랙과 무관하므로 세션에 한 번만 만들어 재사용하면 된다.

    claims(F-26 ClaimDoc) 를 주면 주장 그래프에서 탐침(derive_probes)을 찾아, 대상 노드의 근거가 탐침 종류가
    되고 `QaTriage.probes` 에 실린다. 자료만 올린 경로도 weak 자리를 "자료 안의 긴장·빈틈" 으로 채울 수 있다.
    안 주면(또는 주장이 비면) 프롬프트·순위가 예전과 글자까지 같다.
    """
    graph = _as_graph(graph)
    if isinstance(alignment, dict):
        alignment = AlignmentDoc.from_dict(alignment)
    if isinstance(flow, dict):
        flow = FlowDiff.from_dict(flow)
    if isinstance(transcript, dict):
        transcript = Transcript.from_dict(transcript)
    ctx = _as_context(context)

    pace = _as_pace(pace)
    probes = derive_probes(graph, claims)
    pairs = _ordered_candidates(graph, alignment, flow, pace, probes)
    engine = _engine(llm, llm_kwargs)

    data = _call_with_retry(
        engine,
        TRIAGE_SYSTEM_PROMPT,
        _build_triage_prompt(graph, pairs, alignment, transcript, ctx, flow, _rushed_slides(pace, graph),
                             _probes_by_node(probes)),
    )
    raw_marks = [m for m in (data.get("marks") or []) if isinstance(m, dict)]
    marks = _normalize_marks(raw_marks, pairs, graph, _rushed_ids(pace, graph))
    if memory is not None:
        marks = _stalled_first(marks, graph, MemoryDoc.from_dict(memory) if isinstance(memory, dict) else memory)

    return QaTriage(
        file_name=graph.file_name,
        total_slides=graph.total_slides,
        marks=marks,
        model=engine.name,
        probes=probes,
    )


def _stalled_first(marks: list[TriageMark], graph: ConceptGraph, memory: MemoryDoc) -> list[TriageMark]:
    """지난 리허설에서 한 번도 good 을 못 받은 개념을 앞으로. 그 안팎의 상대 순서는 유지하고 rank 를 다시 매긴다."""
    stalled = {nid for nid, cm in memory.by_node(graph).items() if cm.stalled}
    if not stalled:
        return marks
    ordered = [m for m in marks if m.node_id in stalled] + [m for m in marks if m.node_id not in stalled]
    for rank, mark in enumerate(ordered, start=1):
        mark.rank = rank
    return ordered


# ---------------------------------------------------------------------------
# 2차 · 질문 문장
# ---------------------------------------------------------------------------

#: 골자가 이만큼 겹치면 「사실상 같은 질문」으로 본다 (토큰 Jaccard).
#:
#: 왜 필요한가 — 2026-08-08 실측(qa_judge_probe). 5분 트랙 질문 3개의 골자가
#: 사실상 같아서, 한 번 제대로 답하면 **셋이 전부 good 85 로 닫혔다.** 사용자가
#: "정답 판정이 너무 광범위하다" 고 느낀 실체가 이것이다 — 판정이 무른 게 아니라
#: 질문이 같아서 아무 답이나 맞는 것처럼 보인다.
#:
#: 왜 0.20 인가 — **여기 쓰는 토크나이저로 직접 쟀다.** 측정 도구(qa_judge_probe)가
#: 낸 0.40 은 그쪽 토크나이저의 값이라 그대로 옮기면 안 된다. 실제로 옮겼다가
#: 쌍둥이 셋 중 둘을 놓쳤다:
#:
#:   실제 쌍둥이 (5분 트랙에서 셋이 다 닫히던 골자)   0.24 · 0.26 · 0.43
#:   서로 다른 골자 6쌍                              0.00 ~ 0.04
#:
#: 진짜 쌍둥이와 무관한 골자 사이가 5배 넘게 벌어져 있어 0.20 이 안전하다.
#: 오탐이 나도 손해가 작다 — `_drop_twin_questions` 가 개수를 안 줄이므로
#: 다음 후보 질문(역시 멀쩡한 질문)으로 바뀔 뿐이다. 반대로 놓치면 버그가 남는다.
QA_TWIN_GIST_MAX = 0.20

#: 쌍둥이를 빼도 **개수가 안 줄도록** 미리 더 골라 두는 여유분.
#:
#: 짧은 트랙에만 준다. 5분은 후보 13개 중 가장 중심적인(= 서로 답이 겹치는)
#: 상위 3개만 뽑아서 중복이 생긴다. 10분은 뒤쪽 후보까지 내려가 골자가 흩어지므로
#: 여유분이 0이고, 그래서 **기본 시연 경로는 프롬프트 길이도 과금도 안 바뀐다.**
#: 여유분이 0이면 쌍둥이를 찾아도 되채워 넣게 되어 결과가 종전과 완전히 같다.
QA_TWIN_SLACK = 2
QA_TWIN_SLACK_MAX_LIMIT = 3

#: 조사·서술어는 어느 개념인지 못 가린다. 겹침을 재기 전에 턴다.
_GIST_STOP = {
    "그리고", "그래서", "하지만", "때문", "통해", "대한", "위해", "이것", "그것",
    "있다", "없다", "한다", "된다", "하는", "되는", "이다", "라는", "면서",
    "수도", "정도", "경우", "가지", "부분", "이런", "그런", "저런", "매우",
}
#: 토큰 끝에 붙은 조사 한 겹만 턴다. 형태소 분석기를 붙일 자리가 아니다 —
#: 같은 개념이 "회복은/회복이/회복을" 로 갈리는 것만 막으면 충분하다.
_GIST_JOSA = ("으로써", "으로서", "에서는", "에게서", "이라는", "라는", "으로", "에서",
              "에게", "에는", "과는", "와는", "은", "는", "이", "가", "을", "를",
              "의", "에", "도", "로", "와", "과", "만")


def _twin_slack(limit: int) -> int:
    """쌍둥이를 바꿔 넣을 여유분. 질문이 1개인 트랙엔 바꿔 넣을 자리가 없다."""
    return QA_TWIN_SLACK if 1 < limit <= QA_TWIN_SLACK_MAX_LIMIT else 0


def _gist_tokens(text: str) -> set[str]:
    """골자 문장을 겹침 비교용 토큰 집합으로. LLM 을 부르지 않는다."""
    out: set[str] = set()
    for raw in re.findall(r"[가-힣A-Za-z0-9]+", str(text or "")):
        tok = raw.lower()
        for josa in _GIST_JOSA:
            if len(tok) > len(josa) + 1 and tok.endswith(josa):
                tok = tok[: -len(josa)]
                break
        if len(tok) >= 2 and tok not in _GIST_STOP:
            out.add(tok)
    return out


def _gist_overlap(a: str, b: str) -> float:
    """두 골자의 토큰 Jaccard. 한쪽이라도 비면 0 — 없는 근거로 안 버린다."""
    ta, tb = _gist_tokens(a), _gist_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _drop_twin_questions(
    questions: list[Question], limit: int
) -> tuple[list[Question], list[str]]:
    """
    골자가 사실상 같은 질문을 뒤로 밀고, 상한만큼 돌려준다.

    **개수는 절대 줄이지 않는다.** 쌍둥이를 빼서 상한에 못 미치면 밀어 둔 것을
    도로 채운다. 여유분 없이 뺐다가는 10분 트랙 질문이 7개에서 6개가 되는데,
    중복을 없애자고 기본 시연 경로의 내용을 깎는 것은 남는 장사가 아니다.
    (여유분이 0인 트랙에서는 이 되채우기 때문에 결과가 종전과 완전히 같아진다.)

    앞선 것을 남긴다 — marks 는 rank 순이라 앞이 더 중요한 개념이다.
    """
    kept: list[Question] = []
    spare: list[Question] = []
    for q in questions:
        twin = any(
            _gist_overlap(q.answer_gist, k.answer_gist) > QA_TWIN_GIST_MAX for k in kept
        )
        (spare if twin else kept).append(q)

    while len(kept) < limit and spare:
        kept.append(spare.pop(0))

    keep_ids = {q.id for q in kept[:limit]}
    dropped = [q.node_id for q in questions if q.id not in keep_ids]
    return kept[:limit], dropped


#: 트랙별 질문 배합 — 자리마다 순위가 가장 높은 맞는 개념을 넣는다. 맞는 개념이 없으면 남은 것 중 순위대로.
#:   theme 주제(루트) · part 주제 바로 밑 요소 · weak 확인된 약점(모순·누락·덜 말함·흐름 결손, 지난 리허설에서 막힌 개념)
#: 나오는 순서도 이 순서다 — 큰 주장을 먼저 묻고, 요소로 내려가고, 약점을 찌른다.
#: 2026-09-28: 순위만으로 채우면 녹음 경로는 누락 잎이, 자료만 경로는 한 가지 가지가 트랙을 통째로 먹었다
#: (docs/review/2026-09-28_QA_지엽성_원인분석.md §8).
QA_TRACK_MIX: dict[str, tuple[str, ...]] = {
    "1": ("theme",),
    "5": ("theme", "part", "weak"),
    "10": ("theme", "part", "weak", "part", "weak", "part", "weak"),
}

#: weak 자리에 들어갈 근거. extra(발화에만 나온 개념)는 약점이 아니라 즉흥이라 뺀다.
#: 탐침(PROBE_KINDS)도 약점이다 — 자료 **안에서** 코드가 찾은 긴장·빈틈이라, 녹음이 없어도 근거가 있다.
#: 2026-09-29: 자료만 경로는 근거가 전부 core_weight 라 weak 자리가 맞는 개념을 못 찾고 순위 1등(= weight 순)으로
#: 채워졌다. 탐침이 있으면 그 자리를 탐침이 먼저 받는다 (주장이 없으면 탐침 근거가 아예 없어 예전과 같다).
_WEAK_SOURCES = ("contradiction", "missing", "under_spoken", "weak_flow", *PROBE_KINDS)


def _slot_fits(slot: str, mark: TriageMark, depth_of: dict[str, int], stalled: set[str]) -> bool:
    if slot == "theme":
        return depth_of.get(mark.node_id) == 1
    if slot == "part":
        return depth_of.get(mark.node_id) == 2
    return mark.source in _WEAK_SOURCES or mark.node_id in stalled


def _slot_prefers(slot: str, mark: TriageMark, depth_of: dict[str, int], stalled: set[str]) -> bool:
    """자리에 맞는 개념 가운데 **먼저** 볼 것. theme 자리는 루트의 긴장 탐침이 있으면 그것 —
    발표 전체의 주장이 자료 안에서 부딪히는 자리가 주제 질문으로 가장 날카롭다 (규칙 3-5)."""
    return slot == "theme" and mark.source == "tension" and _slot_fits(slot, mark, depth_of, stalled)


def _theme_pick(rest: list[TriageMark], depth_of: dict[str, int], stalled: set[str]) -> TriageMark | None:
    """theme 자리 — 긴장 탐침 루트가 먼저, 없으면 루트 가운데 치명도(1차 심사)가 가장 높은 것, 그중 **자료 비중(doc_weight)이
    가장 큰 것**, 같으면 순위. 일반화 벤치 §7: 루트가 넷인 덱에서 순위 1등의 가벼운 루트(가짜 단정 탐침)가 주제 자리를 먹었다 —
    같은 치명도면 실제 주제는 가장 무거운 루트다. 치명도는 그대로 앞에 둔다 (1분 트랙은 「가장 치명적인 개념 하나」)."""
    tension = next((m for m in rest if _slot_prefers("theme", m, depth_of, stalled)), None)
    if tension is not None:
        return tension
    roots = [m for m in rest if _slot_fits("theme", m, depth_of, stalled)]
    # 확인된 근거(모순·누락·덜 말함)는 리포트가 이미 말한 것이라 앞에 둔다 (_ADJACENCY_EXEMPT 와 같은 이유). 탐침 근거는 여기서
    # 앞세우지 않는다 — 벤치의 가벼운 루트는 가짜 단정 탐침으로 순위가 올라와 있었다.
    return min(roots, key=lambda m: (m.source not in _ADJACENCY_EXEMPT, m.severity, -m.doc_weight, rest.index(m))) if roots else None


def _mixed_order(
    ordered: list[TriageMark],
    track: str,
    depth_of: dict[str, int] | None,
    stalled: set[str],
    slots_out: dict[str, str] | None = None,
) -> list[TriageMark]:
    """배합대로 앞자리를 채우고, 나머지는 원래 순위대로 뒤에 붙인다. depth 를 모르면 순위 그대로.

    slots_out 을 주면 **자리에 맞아서** 뽑힌 개념의 자리 이름(theme·part·weak)을 적는다 (P1 — 질문 근거).
    맞는 개념이 없어 순위 1등으로 채운 자리는 적지 않는다 — 그건 배합이 고른 게 아니라 순위가 고른 것이다."""
    plan = QA_TRACK_MIX.get(track) or ()
    if depth_of is None or not plan:
        return ordered
    rest = list(ordered)
    head: list[TriageMark] = []
    for slot in plan:
        if not rest:
            break
        if slot == "theme":
            pick = _theme_pick(rest, depth_of, stalled)
        else:
            pick = next((m for m in rest if _slot_prefers(slot, m, depth_of, stalled)), None) \
                or next((m for m in rest if _slot_fits(slot, m, depth_of, stalled)), None)
        if pick is not None and slots_out is not None:
            slots_out[pick.node_id] = slot
        # 맞는 개념이 없으면 순위 1등 — 단 weak 자리는 잎(깊이 3 이상)보다 가지·다른 축(깊이 ≤2)을 먼저 본다. 09-29 기준선:
        # 자료만 경로의 weak 자리는 늘 순위로 찼고, 잎 개념에 검색 문헌이 붙어 발표자가 인용하지 않은 논문 질문이 됐다.
        # 가지 개념은 자료 여러 장에 걸쳐 있어 자료로 답할 거리가 더 많다. 자리 이름은 여전히 적지 않는다 (배합이 고른 것이 아니다).
        if pick is None and slot == "weak":
            pick = next((m for m in rest if 1 <= depth_of.get(m.node_id, 99) <= 2), None)
        pick = pick or rest[0]
        rest.remove(pick)
        head.append(pick)
    return head + rest


def _pick_marks(
    marks: list[TriageMark],
    track: str,
    depth_of: dict[str, int] | None = None,
    stalled: set[str] | None = None,
    slots_out: dict[str, str] | None = None,
) -> tuple[list[TriageMark], list[str]]:
    """
    트랙 상한만큼 배합(QA_TRACK_MIX)대로 고르고, 함정 개수를 트랙 허용치로 깎는다.

    depth_of(노드 id → 깊이)를 안 주면 예전처럼 rank 순이다.
    1분 트랙은 방어 연습할 시간이 없어 함정이 0개다 (QA_TRACK_TRAPS).
    상한에서 밀린 개념은 deferred 로 돌려준다 — "더 길게 하면 이것도 물어요" 안내용이다.
    """
    ordered = _mixed_order(
        sorted(marks, key=lambda m: (m.rank, m.node_id)), track, depth_of, stalled or set(), slots_out
    )
    limit = QA_TRACK_LIMITS[track]
    take = limit + _twin_slack(limit)
    picked, deferred = ordered[:take], [m.node_id for m in ordered[take:]]

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
    by_no: dict[int, Slide] | None = None,
    papers: PaperDoc | None = None,
    memory_of: dict[str, ConceptMemory] | None = None,
    paper_plan: dict[str, list[PaperRef]] | None = None,
    rushed: dict[int, tuple[float, float]] | None = None,
    probe_of: dict[str, Probe] | None = None,
) -> str:
    def refs_of(node: ConceptNode, anchors: list[int]) -> list[PaperRef]:
        if paper_plan is not None:
            return paper_plan.get(node.id, [])
        return _papers_for_node(papers, node, anchors)

    parts = [
        "[TASK] qa-questions",
        ctx.to_prompt_block(),
        "",
        f"파일명: {graph.file_name}",
        f"총 슬라이드: {graph.total_slides}",
        "",
        "## 질문 대상 — questions 에 이 id 가 전부 나와야 한다",
        "(id) 개념이름 [근거 슬라이드] · 치명도 · 함정여부 · 각도",
        "",
        "**경로·연결 줄은 우리가 자료를 읽고 추론한 배경이다. 발표자가 고른 것도,",
        "자료에 그려져 있는 것도 아니다 — 발표자는 이 배치를 본 적이 없다.**",
        "개념끼리 **내용상** 어떤 관계인지 파고드는 데만 쓰고, 배치 자체는 묻지 마라.",
        "연결된 개념과의 관계를 파고드는 질문이 정의를 묻는 질문보다 낫다.",
        "",
        "흐름이 붙은 개념은 다르다 — 그건 발표자가 **실제로 말한 순서**를 전사에서",
        "관측한 것이라 물어도 된다. order_jump 는 \"왜 이 순서로 설명했는지\",",
        "missing_link 는 \"두 개념이 어떤 관계인지\".",
        "",
    ]
    if papers is not None:
        shelf: list[PaperRef] = []
        for mark in marks:
            node = by_id[mark.node_id]
            for ref in refs_of(node, _anchor_nos(node, by_no or {})):
                if ref not in shelf:
                    shelf.append(ref)
        parts += _paper_shelf_lines(papers, shelf)
    judged = {i.node_id: i for i in alignment.items} if alignment else {}
    # 각도(triage 메모)에 자료·발화·문헌 어디에도 없는 숫자가 있으면 싣지 않는다. 일반화 벤치 §9: 각도의 「당기순이익 93.923조원」
    # (자료는 93,923 십억원)이 질문 재료가 됐다 — LLM 이 각도의 숫자를 사실로 옮긴다.
    number_sources = _number_sources(by_no, transcript, papers)
    for mark in marks:
        node = by_id[mark.node_id]
        # 자료가 있으면 근거 장을 anchor 로 좁힌다. 12장짜리 개념이 세 개면 셋이
        # 똑같은 덱 첫 장을 받았다 — 그 상태에서는 사전 정의 질문밖에 안 나온다.
        anchors = _anchor_nos(node, by_no or {})
        nos = ",".join(str(n) for n in anchors)
        line = (
            f"- ({node.id}) {node.label} [S{nos}] · 치명도={mark.severity}"
            f" · 함정={'예' if mark.trap else '아니오'}"
        )
        if mark.angle and not (number_sources and ungrounded_numbers(mark.angle, number_sources)):
            line += f" · 각도={mark.angle}"
        if node.summary:
            line += f" — {node.summary}"
        parts.append(line)

        relation = _relation_line(node, graph)
        if relation:
            parts.append(f"    {relation}")
        if node.parent_id is None and node.depth == 1:
            parts.append("    주제: 발표 전체의 주장이다 — 되읊게 하지 말고 조건·경계·부딪히는 표현을 물어라 (규칙 3-5)")
        section = section_line(node, graph)
        if section:
            parts.append(f"    {section}")
        # 이웃의 요약·간선 종류·근거 장. 이름만 있으면 관계를 캐묻지 못한다.
        for ln in neighbor_lines(node, graph):
            parts.append(f"    이웃 {ln}")

        issue = (flow_of or {}).get(node.id)
        if issue is not None and mark.source == "weak_flow":
            parts.append(f"    {_flow_line(issue)}")
        rushed_line = _rushed_line(node, rushed or {})
        if rushed_line:
            parts.append(f"    {rushed_line}")

        # 탐침 (P4) — 이 개념이 탐침 때문에 뽑혔으면 **그 각도를 그대로 묻게** 묶는다. 근거 원문은 F-26 이 원문과
        # 대조해 확인한 인용이라 질문이 자료 밖으로 나갈 수 없다. 탐침 개념 이름이 문장에 빠지면 _normalize_questions 가
        # 템플릿으로 바꾸므로 여기서 이름을 못 박아 둔다.
        probe = (probe_of or {}).get(node.id)
        if probe is not None:
            names = "·".join(f"「{by_id[i].label if i in by_id else i}」" for i in probe.node_ids)
            parts.append(f"    {_probe_line(probe)}")
            if probe.evidence:
                parts.append(f"    {_probe_evidence_line(probe)}")
            parts.append(f"    ← 이 개념의 질문은 위 탐침이 짚은 것 하나만 그대로 물어라. {names} 를 문장에 넣고, 자료를 되읊게 하지 마라")

        # 이 개념에 붙은 문헌 — 자료가 그 장에서 인용했거나 이 개념으로 검색된 것.
        for ref in refs_of(node, anchors):
            parts.append(f"    문헌 ({ref.id}) {ref.cite_key} ← 질문 문장에 \"{ref.cite_key}\" 를 그대로 넣어 이 문헌을 근거로 물어라")

        # 지난 리허설 기억 (F-25) — 판정·횟수·빠진 점만. 지난 답변 원문은 싣지 않는다.
        cm = (memory_of or {}).get(node.id)
        if cm is not None:
            tail = " ← 빠졌던 점을 겨냥해 물어라" if cm.missing_points else (" ← 지난번에 못 넘긴 개념이다, 이번엔 더 좁게 물어라" if cm.stalled else "")
            parts.append(f"    {cm.prompt_line}{tail}")

        # 자료가 먼저, 발화가 나중. 우리가 재는 것은 «자료가 약속한 것을 말로
        # 지켰는가» 라서 프롬프트도 자료를 기준으로 읽히게 둔다.
        body = _slide_body(node, by_no or {}, anchors)
        if body:
            parts.append(f"    자료 본문(S{nos}): {body}")

        said = _speech_excerpt(node, transcript, anchors if by_no else None)
        item = judged.get(node.id)
        if said or (item is not None and item.evidence.strip()):
            verdict = f"({item.verdict}) " if item is not None else ""
            parts.append(f"    발표에서 한 말{verdict}: {said or item.evidence}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 문헌 (F-24 PaperDoc) — 프롬프트 재료와 인용 검사. papers 가 None 이면 전부 잠잔다.
# ---------------------------------------------------------------------------

#: 프롬프트에 실을 초록 길이. 계약의 300자보다 짧게 — 서가가 길어지면 규칙이 묻힌다 (09-22 실측 15k자·인용 0).
#: 프롬프트에 싣는 초록 길이. 예전엔 200 이라 구조화 초록의 목적 줄만 실렸고, 결과를 못 본 LLM 이 발표의 주장을
#: 논문 입에 넣었다 (2026-09-29 Paulsrud et al. (2026)). 서가에는 계획된 문헌(트랙당 ≤2)만 실리므로 전문을 실어도 짧다.
PAPER_PROMPT_ABSTRACT_MAX = PAPER_ABSTRACT_MAX


def _paper_line(ref: PaperRef) -> str:
    where = f"자료 {ref.slide_no}장이 인용" if ref.kind == "deck" and ref.slide_no else (
        f"검색: {ref.query}" if ref.query else "검색")
    line = f"({ref.id}) {ref.cite_key}"
    if ref.title:
        line += f" «{ref.title}»"
    if ref.venue:
        line += f" · {ref.venue}"
    line += f" · [{where}]"
    if ref.abstract:
        line += f"\n    초록: {ref.abstract[:PAPER_PROMPT_ABSTRACT_MAX]}"
    return line


def _paper_shelf_lines(papers: PaperDoc | None, refs: list[PaperRef] | None = None) -> list[str]:
    """서가. refs 를 주면 그것만 싣는다 — 질문 대상 개념에 붙은 문헌만 실어 프롬프트를 짧게 둔다."""
    if papers is None or not papers.refs:
        return []
    shelf = refs if refs is not None else papers.refs
    if not shelf:
        return []
    lines = [
        "## 교수가 읽고 온 문헌 — 인용은 **이 목록 안에서만**, 인용 표시는 적힌 그대로",
        "초록은 원문 그대로다. 논문에 대해 말할 수 있는 것은 이 초록에 적힌 것뿐이다.",
        "",
    ]
    lines += [_paper_line(r) for r in shelf]
    lines.append("")
    return lines


#: 개념 하나에 붙일 문헌 줄 수. 참고문헌 장을 근거로 가진 개념은 그 장의 문헌 전부가 걸리므로 자른다.
PAPER_LINES_PER_NODE = 4


def _papers_for_node(papers: PaperDoc | None, node: ConceptNode, anchors: list[int]) -> list[PaperRef]:
    """이 개념에 붙은 문헌 — 검색으로 이 개념에 붙은 것이 먼저, 그다음 근거 장이 인용한 것."""
    if papers is None:
        return []
    direct = [r for r in papers.refs if node.id in r.node_ids]
    by_slide = [r for r in papers.refs if r not in direct
                and r.kind == "deck" and r.slide_no and r.slide_no in anchors]
    return (direct + by_slide)[:PAPER_LINES_PER_NODE]



#: 트랙별 **논문 인용 질문 상한**. 예전엔 문헌 줄이 붙은 개념마다 인용을 강제해 5분 트랙 3개 중 2개,
#: 10분 7개 중 5개가 「X et al. (연도)는 …했는데」 틀이었고 같은 논문이 여러 질문에 되풀이됐다
#: (2026-09-29 실측, docs/review/2026-09-28_QA_지엽성_원인분석.md §9). 1분은 발표 자체만 묻는다.
QA_TRACK_CITES = {"1": 0, "5": 1, "10": 2}


def _plan_papers(
    marks: list[TriageMark],
    by_id: dict[str, ConceptNode],
    by_no: dict[int, Slide] | None,
    papers: PaperDoc | None,
    track: str,
) -> dict[str, list[PaperRef]]:
    """
    어느 질문에 어느 문헌 하나를 붙일지 정한다. 상한(QA_TRACK_CITES)까지만, **한 문헌은 한 번만**.

    자료가 직접 인용한 문헌(deck)을 먼저 배정한다 — 발표자가 스스로 낸 근거라 묻기에 정당하다.
    그다음 검색 문헌. 각 단계 안에서는 질문 순서(배합 순서)대로. 계획에 없는 개념은 문헌 줄 없이 자료로만 묻는다.
    """
    budget = QA_TRACK_CITES.get(track, 0)
    if papers is None or budget <= 0:
        return {}
    plan: dict[str, list[PaperRef]] = {}
    used: set[str] = set()
    for want_deck in (True, False):
        for mark in marks:
            if budget <= 0:
                return plan
            node = by_id.get(mark.node_id)
            if node is None or mark.node_id in plan:
                continue
            # 제목도 초록도 없는 자료 인용은 붙이지 않는다 — 물을 거리가 없고, 대개 「Skills (2019)」 처럼 본문 낱말을 인용으로
            # 잘못 읽은 것이다 (09-29 held-out 링글 덱: 「Skills (2019)는 … 근거는 무엇인가요?」·「Land (2016)는 …」).
            ref = next(
                (r for r in _papers_for_node(papers, node, _anchor_nos(node, by_no or {}))
                 if (r.kind == "deck") == want_deck and r.id not in used and r.cite_key not in used
                 and (r.title or r.abstract)),
                None,
            )
            if ref is not None:
                plan[mark.node_id] = [ref]
                used |= {ref.id, ref.cite_key}
                budget -= 1
    return plan

def _ref_cited(ref: PaperRef, surname: str, year: int) -> bool:
    return ref.year == year and surname in {a.lower() for a in ref.authors}


def _ungrounded_citation(text: str, papers: PaperDoc | None) -> bool:
    """문장이 목록에 없는 논문을 인용했는가. papers 가 없으면 검사하지 않는다 (예전과 같은 동작)."""
    if papers is None:
        return False
    for surname, year in find_citations(text):
        if not any(_ref_cited(r, surname, year) for r in papers.refs):
            return True
    return False


def _cited_ids(text: str, papers: PaperDoc | None) -> list[str]:
    if papers is None:
        return []
    ids: list[str] = []
    for surname, year in find_citations(text):
        for r in papers.refs:
            if _ref_cited(r, surname, year) and r.id not in ids:
                ids.append(r.id)
    return ids


def _paper_ids_of(raw: dict, texts: list[str], papers: PaperDoc | None) -> list[str]:
    """LLM 이 적은 paper_ids 중 실재하는 것 + 문장에서 실제로 인용한 것. 순서는 문서 순."""
    if papers is None:
        return []
    claimed = {str(x) for x in (raw.get("paper_ids") or []) if str(x)}
    cited = set()
    for t in texts:
        cited.update(_cited_ids(t, papers))
    return [r.id for r in papers.refs if r.id in claimed or r.id in cited]


#: 숫자로 끝나는 라벨은 읽는 소리로 받침을 본다 (영·일·삼·육·칠·팔). 09-29: 폴백 문장에 「개념1가」 가 나왔다.
#: `_probes.josa` 는 한글이 아니면 받침 없음으로 본다 — 그 모듈은 F-26 쪽 담당이라 여기서 숫자만 받는다.
_DIGIT_BATCHIM = {"0": True, "1": True, "2": False, "3": True, "4": False, "5": False, "6": True, "7": True, "8": True, "9": False}


def josa(word: str, with_batchim: str, without: str) -> str:
    last = (word or "").rstrip()[-1:]
    if last in _DIGIT_BATCHIM:
        return word + (with_batchim if _DIGIT_BATCHIM[last] else without)
    return _probe_josa(word, with_batchim, without)


def _fallback_question(node: ConceptNode, mark: TriageMark, flow_issue: FlowIssue | None, nos_all: list[int]) -> str:
    """
    LLM 문장이 없을 때의 질문 — 근거(source)마다 **해요체로 끝나는 자연스러운 한 문장**.

    예전엔 「{개념}: {angle} — 설명해 주세요.」 였다. angle 은 triage 프롬프트용 한다체 메모라 그대로 붙이면
    「…근거는 무엇인가? — 설명해 주세요」 처럼 해라체·메모가 화면에 나갔다 (09-29 기준선 §5-8, 두 덱 3회).
    angle 은 쓰지 않는다 — 근거와 장 번호만으로 문장을 만든다. '~시겠어요' 도 쓰지 않는다 (CLAUDE.md §3-1).
    """
    label = node.label
    shown = nos_all[:HINT_SLIDE_MAX]
    where = f"자료 {', '.join(str(n) for n in shown)}장" if shown else "자료"
    if mark.source == "contradiction":
        return f"{josa(label, '은', '는')} 발표에서 한 설명이 자료와 조금 달랐어요. {where} 기준으로 다시 설명해 주세요."
    if mark.source == "missing":
        return f"{where}에 있는 {josa(label, '을', '를')} 발표에서는 다루지 않았어요. 이 발표에서 {josa(label, '은', '는')} 어떤 역할을 하나요?"
    if mark.source == "under_spoken":
        return f"{josa(label, '은', '는')} 발표에서 짧게 지나갔어요. {where}의 핵심을 한 문장으로 말하면 무엇인가요?"
    if mark.source == "weak_flow" and flow_issue is not None and flow_issue.kind == "order_jump":
        return f"{josa(label, '을', '를')} 자료와 다른 순서로 설명했는데, 그렇게 한 이유가 있나요?"
    if mark.source == "weak_flow":
        return f"{josa(label, '이', '가')} 앞뒤 내용과 어떻게 이어지는지 설명해 주세요."
    if mark.source == "extra":
        return f"{josa(label, '은', '는')} 자료에 없는데 발표에서 꺼냈어요. 이 내용을 넣은 이유는 무엇인가요?"
    if mark.source == "justified_skip":
        return f"{josa(label, '은', '는')} 발표에서 생략했는데, 누가 물으면 한 문장으로 어떻게 답할 건가요?"
    return f"{josa(label, '이', '가')} 이 발표에서 왜 중요한지 {josa(where, '을', '를')} 근거로 설명해 주세요."


def _fallback_text(
    node: ConceptNode,
    mark: TriageMark,
    flow_issue: FlowIssue | None = None,
    slide_nos: list[int] | None = None,
) -> tuple[str, str, str]:
    """LLM 이 이 개념을 빠뜨렸을 때 쓰는 결정적 문장 3종 (question, why, hint).
    `slide_nos` 는 anchor 장 — 안 주면 node.slide_nos 다."""
    nos_all = node.slide_nos if slide_nos is None else slide_nos
    question = _fallback_question(node, mark, flow_issue, nos_all)

    if mark.source == "weak_flow" and flow_issue is not None:
        # 이슈 종류를 알면 why 도 그 종류로 말한다 — 순서 역행에 "연결이 안
        # 드러났다" 를 붙이면 사용자가 질문 의도를 오해한다.
        why = _WHY_BY_FLOW_KIND[flow_issue.kind]
    else:
        why = _WHY_BY_SOURCE.get(mark.source, _WHY_BY_SOURCE[QA_SOURCE_FALLBACK])

    if nos_all:
        # 사다리 2단(_hint_scope)과 같은 절단 — 12장을 다 나열하면 좁혀 주기는커녕
        # 아무 정보도 없다. 문구는 2단과 다르게 둔다: 같으면 build_hint_ladder 의
        # 중복 제거가 2단을 지워 사다리가 한 칸 짧아진다.
        shown = nos_all[:HINT_SLIDE_MAX]
        nos = ", ".join(str(n) for n in shown)
        extra = f" 외 {len(nos_all) - len(shown)}장" if len(nos_all) > len(shown) else ""
        hint = f"{nos}장{extra}에 이 개념을 둔 이유부터 떠올려 보세요"
    else:
        hint = "자료에서 이 개념을 왜 다뤘는지부터 짚어 보세요"
    return question, why, hint


def _fallback_gist(
    node: ConceptNode, *, trap: bool = False, slide_nos: list[int] | None = None
) -> str:
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
    nos_all = node.slide_nos if slide_nos is None else slide_nos
    if nos_all:
        # _fallback_text 의 힌트와 같은 절단. 이 문장은 화면에 모범답으로 그대로
        # 나간다 — "(1, 2, 3, …, 12장 근거)" 는 근거가 아니라 소음이다.
        shown = nos_all[:HINT_SLIDE_MAX]
        nos = ", ".join(str(n) for n in shown)
        extra = f" 외 {len(nos_all) - len(shown)}장" if len(nos_all) > len(shown) else ""
        return f"{summary} ({nos}장{extra} 근거)"
    return summary


#: 프롬프트 발판을 **인용한** 자리를 잡는 표지.
#:
#: `_build_question_prompt` 이 개념마다 "경로=A > B · 연결=C, D" 를 넣는데, 그건
#: 우리가 자료를 읽고 추론한 것이지 자료에 그려진 것도 발표자가 고른 것도 아니다.
#: LLM 이 그걸 자료인 줄 알고 근거로 옮기면 **발표자가 본 적 없는 것을 근거로 든
#: 답**이 된다 (2026-08-08: "경로(위계)에서 '수면의 질 > 회복'으로 표시되어
#: 있습니다"). 프롬프트로 금지했지만 부탁일 뿐이라, 새어 나온 것은 여기서 버린다.
#:
#: **낱말이 아니라 인용 꼴로 잡는다.** '정렬'·'경로'·'연결' 은 자료가 실제로 쓰는
#: 말일 수 있다 (IMU2CLIP 의 '정렬', 네트워크 발표의 '경로'). 우리 발판을 가리킬
#: 때만 나오는 모양새여야 오검출이 없다.
_SCAFFOLD_CITED = (
    "경로(위계)",
    "경로=",
    "연결=",
    "경로에서",
    "경로에 표시",
    "위계에서",
    "위계로 표시",
    "그래프에서 표시",
)


#: 프롬프트 예시의 자리표시(「발표의 '<이 발표의 개념>'은」)를 그대로 베낀 흔적. 09-29 실측(solar): 예시의 구체 개념
#: ('비가시적 집중 손실')을 수면 발표 질문에 베꼈고, 자리표시로 바꾸자 자리표시를 베꼈다. 베낀 문장은 없는 것으로 친다.
_PLACEHOLDER_RE = re.compile(r"<[^<>\n]{1,24}>")


def _cites_scaffold(text: str) -> bool:
    """이 문장이 우리 프롬프트 발판을 근거로 인용했거나, 예시의 자리표시를 베꼈는가."""
    t = (text or "").replace(" ", "")
    return any(mark.replace(" ", "") in t for mark in _SCAFFOLD_CITED) or bool(_PLACEHOLDER_RE.search(text or ""))


#: 한 질문이 **둘 이상**을 묻는다는 표지. 여기 걸릴 때만 코드가 골자를 쪼갠다.
#: 오검출하면 하나만 묻는 질문에도 없는 요소를 요구해서 이길 수 없는 질문이 된다 —
#: 그래서 «묻는 것이 둘» 이 문면에 드러나는 모양만 잡는다.
_MULTI_ASK_RE = re.compile(
    r"각각|둘\s*다|두\s*가지|세\s*가지|무엇이고|무엇이며|무엇인지와|"
    r"[와과]\s*그\s*이유|이유(까지|도)\s*(함께|같이)|"
    r"(함께|같이|모두)\s*(말해|설명|말씀|짚어)"
)

#: 골자를 요소로 가르는 구분자. **맨 쉼표는 넣지 않는다** — 한 요소 안의 수식절까지
#: 잘라 내서, 하나를 물은 질문이 두 요소짜리로 둔갑한다.
#:
#: 연결어미 뒤의 쉼표(`~이며,` · `~이고,`)는 넣는다. 실측(2026-08-10, solar-pro3)에서
#: 「무엇이며, 그 근거는」 질문의 골자가 "…가장 큰 요인이며, 이는 …때문입니다" 로
#: 와서 위 구분자로는 하나도 안 갈렸다 — 질문은 둘을 묻는다고 잡히는데 요소는
#: 안 생겨서 **백스톱이 통째로 죽어 있었다.** 어미를 남기고 쉼표만 소비한다.
_GIST_SPLIT_RE = re.compile(
    r"\s*[·;]\s*|\s*,?\s*그리고\s+|\s+또한\s+|\s+및\s+|(?<=이며),\s*|(?<=이고),\s*"
)

#: 쪼갠 조각의 최소 길이. 이보다 짧으면 요소가 아니라 잘린 꼬리다.
GIST_PART_MIN = 4


def _asks_multiple(question_text: str) -> bool:
    """질문 문면이 둘 이상을 묻고 있는가 (코드 백스톱의 발동 조건)."""
    return bool(_MULTI_ASK_RE.search(question_text or ""))


def _split_gist_parts(gist: str) -> list[str]:
    """
    골자를 요소로 쪼갠다. **LLM 이 빠뜨렸을 때만 쓰는 결정적 백스톱이다.**

    쪼개지지 않으면 빈 배열이다 — 억지로 반 토막 내면 뜻이 없는 조각이 채점
    기준이 된다. `Question.answer_gist_parts` 의 「비었거나 2개 이상」 불변식은
    `contracts._gist_parts_of` 가 마지막으로 지킨다.
    """
    parts = [
        p.strip(" .·,")
        for p in _GIST_SPLIT_RE.split((gist or "").strip())
        if len(p.strip(" .·,")) >= GIST_PART_MIN
    ]
    return parts if len(parts) >= 2 else []


#: 이미 해요체·경어로 끝나는 문장. 이건 건드리지 않는다.
_POLITE_END_RE = re.compile(r"(요|죠|세요|나요|가요|래요|습니까)\s*[?.!]?\s*$")
#: LLM 이 자주 내는 반말 의문 어미 → 해요체. 순서대로 첫 매치만 적용한다.
#: 규칙 5(해요체)를 프롬프트로 부탁만 해서는 안 지켜진다 — 2026-09-12 실측에서 두 변형 모두 3/3 반말.
_IMPOLITE_END_RULES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"는가(\s*[?.!]?)\s*$"), r"나요\1"),            # 되는가 → 되나요
    (re.compile(r"([가-힣])가(\s*[?.!]?)\s*$"), r"\1가요\2"),     # 무엇인가·타당한가·어떻게 다른가 → …가요 (ㄴ받침 검사는 아래)
    (re.compile(r"(?<!니)까(\s*[?.!]?)\s*$"), r"까요\1"),        # 일까 → 일까요 (습니까는 그대로)
    (re.compile(r"(?:느)?냐(\s*[?.!]?)\s*$"), r"나요\1"),          # 있느냐 → 있나요
    (re.compile(r"(설명|서술|말|답)하라\s*[?.!]?\s*$"), r"\1해 주세요."),
)


#: 명사구 + 주제 조사로 끝난 물음 — 「…재무 건전성에 미치는 영향은?」. 서술어가 통째로 빠진 꼴이라 「무엇인가요?」 를 붙인다.
#: 일반화 벤치 §9: SK하이닉스 덱 5분 트랙에서 반말 끝으로 화면에 나갔다.
_INDIRECT_END_RE = re.compile(r"((?:는|은|인|할|될|을|일|던|한|된)지)\s*[?？.]?\s*$")
_TOPIC_END_RE = re.compile(r"([가-힣])(은|는)\s*[?？]?\s*$")


def _polite_question(text: str) -> str:
    """반말 의문 어미를 해요체로 바꾼다. 문장 끝만 본다 — 본문의 낱말은 건드리지 않는다.
    문장부호는 있는 그대로 둔다 (LLM 이 쓴 문장을 어미 말고는 바꾸지 않는다). 이미 해요체면 그대로."""
    t = text or ""
    if not t.strip() or _POLITE_END_RE.search(t):
        return t
    if _INDIRECT_END_RE.search(t):                          # 「…어떻게 연결되는지」 — 간접 물음으로 끝났다 (09-29 held-out IR 덱)
        return _INDIRECT_END_RE.sub(r"\1 설명해 주세요.", t)
    m = _TOPIC_END_RE.search(t)
    if m and not re.search(r"(?:하|되|있|없|이|같|않)(?:는|은)\s*[?？]?\s*$", t):   # 「…하는?」 같은 관형형 끝은 명사구가 아니다
        return t[:m.end(2)] + " 무엇인가요?"
    for pat, rep in _IMPOLITE_END_RULES:
        m = pat.search(t)
        if not m:
            continue
        # "X가" 규칙은 X 가 ㄴ받침 음절(인·한·던·은·른·큰…)일 때만 의문 어미다. "평가?" 같은 명사 끝은 건드리지 않는다.
        if rep.startswith("\\1가요") and (ord(m.group(1)) - 0xAC00) % 28 != 4:
            continue
        return pat.sub(rep, t)
    return t


#: 힌트·이유·골자 끝의 해라체·한다체 → 해요체. 09-29 기준선 §5-10: rec/10 힌트 7개 중 6개가 「생각해 보라」·「참고하라」,
#: 골자 끝이 「…근거로 한다」·「…미친다」 였다. `to_haeyo` 는 합쇼체만 풀고 `_polite_question` 은 물음 끝만 본다.
_PLAIN_IMPERATIVE_RE = re.compile(r"(보|하)라(?=[.!]?\s*$)")
_PLAIN_COPULA_RE = re.compile(r"([가-힣])이다(?=[.!]?\s*$)")
_PLAIN_EXIST_RE = re.compile(r"(있|없)다(?=[.!]?\s*$)")
_PLAIN_NDA_RE = re.compile(r"([가-힣])다(?=[.!]?\s*$)")
_PLAIN_HADA_RE = re.compile(r"하다(?=[.!]?\s*$)")
_NOMINAL_END_RE = re.compile(r"([가-힣]?)(있음|없음|함|됨|임)(?=[.!]?\s*$)")
#: `to_haeyo` 가 「보입니다」(보이+ㅂ니다)를 서술격 「입니다」 로 읽어 「보예요」 를 낸다 (09-29 수익률·링글 골자 「차이만 보예요」).
#: 「정보예요」 처럼 명사 끝은 맞는 꼴이라 앞이 글자가 아닐 때만 고친다.
_BOYEYO_RE = re.compile(r"(?<![가-힣])보예요")
_PLAIN_NEUNDA_RE = re.compile(r"([가-힣])는다(?=[.!]?\s*$)")
#: 문장 경계 — 마침표·느낌표 뒤 공백.
_STATEMENT_SPLIT_RE = re.compile(r"(?<=[.!])\s+")


def _plain_end_to_haeyo(sent: str) -> str:
    """한 문장의 끝 어미만. 이미 해요체면 그대로. 모르는 꼴은 두고 넘어간다 — 틀리게 바꾸는 것보다 남기는 쪽이 낫다."""
    if _POLITE_END_RE.search(sent):
        return sent
    t = _PLAIN_IMPERATIVE_RE.sub(r"\1세요", sent)          # 생각해 보라 → 생각해 보세요 · 참고하라 → 참고하세요
    if t != sent:
        return t
    m = _NOMINAL_END_RE.search(sent)                          # 개조식 끝(…하게 함 · 발생함 · 있음 · 중심임) — 09-29 held-out(링글) 골자
    if m and not (m.group(2) == "함" and m.group(1) == "포"):   # 「…포함」 은 명사다
        tail = {"함": "해요", "됨": "돼요", "있음": "있어요", "없음": "없어요"}.get(m.group(2))
        if tail is None:                                      # 명사 + 임 → 이에요/예요
            prev = m.group(1)
            tail = "이에요" if _has_batchim(prev) else "예요"
            return sent[:m.start()] + prev + tail + sent[m.end():]
        return sent[:m.start()] + m.group(1) + tail + sent[m.end():]
    t = _PLAIN_EXIST_RE.sub(r"\1어요", sent)               # 있다 → 있어요
    if t != sent:
        return t
    m = _PLAIN_COPULA_RE.search(sent)                         # 것이다 → 것이에요 · 차이다 → 차이예요
    if m:
        return sent[:m.start()] + m.group(1) + ("이에요" if _has_batchim(m.group(1)) else "예요") + sent[m.end():]
    m = _PLAIN_HADA_RE.search(sent)                           # 필요하다 → 필요해요 · 가능하다 → 가능해요
    if m:
        return sent[:m.start()] + "해요" + sent[m.end():]
    m = _PLAIN_NEUNDA_RE.search(sent)                         # 않는다 → 않아요 · 먹는다 → 먹어요 (받침 어간 + 는다)
    if m:
        vowel = ((ord(m.group(1)) - 0xAC00) % 588) // 28
        return sent[:m.start()] + m.group(1) + ("아요" if vowel in (0, 8) else "어요") + sent[m.end():]
    m = _PLAIN_NDA_RE.search(sent)
    if m and m.group(1) == "인":                               # 쌓인다·보인다 → 쌓여요·보여요 (이+어). 「입니다」 로 돌리면 서술격으로 읽힌다
        return sent[:m.start()] + "여요" + sent[m.end():]
    if m and (ord(m.group(1)) - 0xAC00) % 28 == 4:            # ㄴ받침 + 다 (한다·미친다·된다) → ㅂ니다 → 해요체
        ch = chr(ord(m.group(1)) - 4 + 17)
        return to_haeyo(sent[:m.start()] + ch + "니다" + sent[m.end():])
    return sent


def _polite_statement(text: str) -> str:
    """힌트·이유·골자의 문장 끝마다 해라체·한다체를 해요체로. 결정적이고 멱등이다."""
    t = text or ""
    if not t.strip():
        return t
    return _BOYEYO_RE.sub("보여요", " ".join(_plain_end_to_haeyo(x) for x in _STATEMENT_SPLIT_RE.split(t.strip())))


# ---------------------------------------------------------------------------
# 문장 가운데 높임 — `_polite_question` 은 끝 어미만 본다. 2026-09-24 실측: "인용하셨는데 … 판단하신 근거는" 이
# 규칙 5 가 있는데도 나왔다 (09-12 과 같은 교훈 — 말투는 부탁이 아니라 코드가 지킨다, CLAUDE.md §3-1).
# ---------------------------------------------------------------------------

#: (패턴, 바꿀 말). 순서대로 적용한다. 전부 「높임 선어말 어미가 붙은 꼴」 이라 명사 안에서 나올 일이 거의 없다 —
#: 그래서 짧은 고정 문자열로 둔다. 문맥이 필요한 '이셨'·'께' 는 아래 함수가 따로 본다.
_HONORIFIC_RULES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"하셨"), "했"),          # 인용하셨는데 → 인용했는데 · 선택하셨을 → 선택했을
    (re.compile(r"되셨"), "됐"),
    (re.compile(r"하시는"), "하는"),
    (re.compile(r"하신"), "한"),          # 판단하신 → 판단한 · 생각하신다 → 생각한다
    (re.compile(r"되신"), "된"),
    (re.compile(r"하실"), "할"),
    (re.compile(r"말씀"), "말"),          # 말씀하셨 → (위에서) 말씀했 → 말했
)
#: '이셨' — 앞 음절에 받침이 있으면 '이었', 없으면 '였' (학생이셨 → 학생이었 · 누구이셨 → 누구였).
_ISYEOT_RE = re.compile(r"([가-힣]?)이셨")
#: 높임 조사 '께' → '에게'. '께서' 는 주어 높임이라 문장 뜻이 바뀌므로 두지 않는다(요청 범위 밖).
#: 앞이 한글 음절이고, 뒤가 낱말 끝(또는 는·도·만 다음 낱말 끝)일 때만 — '함께'·'그저께'·'엊그제께' 는 뺀다.
_KKE_RE = re.compile(r"(?<=[가-힣])(?<![함저제])께(?!서)(?=(?:는|도|만)?(?![가-힣]))")


def _has_batchim(ch: str) -> bool:
    return "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 != 0


def _plain_speech(text: str) -> str:
    """문장 **가운데**의 높임(~셨·~신·~실·말씀·께)을 평이한 해요체 서술로 바꾼다. 끝 어미는 `_polite_question` 몫.
    결정적이고 멱등이다 — 이미 평서면 그대로."""
    t = text or ""
    if not t:
        return t
    for pat, rep in _HONORIFIC_RULES:
        t = pat.sub(rep, t)
    t = _ISYEOT_RE.sub(lambda m: m.group(1) + ("이었" if not m.group(1) or _has_batchim(m.group(1)) else "였"), t)
    return _KKE_RE.sub("에게", t)


#: 발표자를 3인칭으로 부르는 꼴 — 「발표자는 어떻게 설명했나요?」. 질문은 발표자 **본인에게** 하는 말이다.
#: 2026-09-28 수면발표 실측(solar). 뒤에 발표 행위 동사가 올 때만 잡는다 — 척척발표처럼 「발표자」 가 자료의
#: 개념인 덱("발표자의 이해도를 진단")에서 내용을 지우면 안 된다.
_THIRD_PERSON_RE = re.compile(
    r"발표자(는|가|께서)\s+(?=[^.?!]{0,30}?(?:설명|언급|제시|말|강조|주장|소개|정의|꼽|들었|든 |했|한 ))"
)


def _second_person(text: str) -> str:
    """「발표자는 …했나요」 → 「…했나요」, 「발표자가 제시한 X」 → 「발표에서 제시한 X」. 결정적이고 멱등이다."""
    return _THIRD_PERSON_RE.sub(lambda m: "" if m.group(1) == "는" else "발표에서 ", text or "")


# ---------------------------------------------------------------------------
# 거짓 전제 — 검색 문헌(kind="scholar")을 「발표자가 인용했다」 고 쓴 문장.
# 2026-09-24 실측: 자료는 논문을 하나도 인용하지 않았는데 "O'Reilly et al. (2026)와 Kulshreshtha (2026)를
# 인용하셨는데 …" 가 나왔고, 판정이 "질문의 전제부터 확인해 보세요" 로 빠졌다. 시스템이 만든 질문을 시스템이 틀렸다고
# 하는 꼴이라, 프롬프트(CITE_SYSTEM_PROMPT·PAPER_SYSTEM_ADDENDUM)와 별개로 코드가 잡는다.
# ---------------------------------------------------------------------------

#: 「발표자가 인용했다」 는 표현. _plain_speech 뒤에 보지만 높임 꼴도 같이 잡는다.
_PRESENTER_CITED_RE = re.compile(r"인용(?:했|하셨|하신|하였|한|하고|되었|됐|된)")
#: 떼어 낼 수 있는 꼴 ① 관형절 — 「(N장에서) 인용한 X (연도)는 …」. 떼면 「X (연도)는 …」 로 검색 문헌에 허용된 꼴이 된다.
#: 바로 뒤에 인용 표시가 올 때만 뗀다 ("…를 인용한 이유는" 을 떼면 문장이 깨진다).
_CITED_ADNOMINAL_RE = re.compile(
    r"(?:(?:\d+\s*장|자료|발표|슬라이드)\s*에서\s+)?인용(?:한|하신|된|했던|하셨던)\s+"
    r"(?=[A-Z][A-Za-z'\-]+[^()]{0,60}\(\d{4}[a-z]?\))"
)
#: 떼어 낼 수 있는 꼴 ② 문장 앞 전제절 — 「X (연도)를 인용했는데, 본론」. 문장 첫머리부터 이 절까지 뗀다.
#: 문장 단위로 잘라서 보므로 첫머리부터 아무 글자나 받는다 ("et al." 의 마침표 때문에 [^.] 로 막으면 못 잡는다).
_CITED_CLAUSE_RE = re.compile(r"^.*?인용(?:했|하셨|하였|되었|됐)(?:는데|지만|으나|으며|고)\s*,?\s*|^.*?인용하고\s*,\s*")
#: 떼고 남은 문장이 이보다 짧으면 질문이 아니라 꼬리다 — 뗀 것으로 치지 않는다.
CITE_CLAIM_REST_MIN = 8
#: 문장 경계 — 물음표·느낌표 뒤, 또는 한글 뒤 마침표. "et al. (2015)" 의 마침표에서 자르지 않는다.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[?!？])\s+|(?<=[가-힣]\.)\s+")


def _claims_presenter_cited(text: str, papers: PaperDoc | None) -> bool:
    """문장이 「발표자가 인용했다」 고 말하는데, 문장이 인용한 문헌 중 자료가 실제로 인용한 것(kind="deck")이 없는가.

    문장에 목록의 문헌이 하나도 없으면 False 다 — "3장에서 인용한 통계는 …" 처럼 자료 속 인용을 말하는 것일 수 있고,
    그건 자료에 있는 사실이라 거짓 전제가 아니다. 이 검사가 막는 것은 **검색 문헌에 발표자의 인용을 덧씌우는 것**뿐이다."""
    if papers is None or not _PRESENTER_CITED_RE.search(text or ""):
        return False
    ids = _cited_ids(text, papers)
    if not ids:
        return False
    kind_of = {r.id: r.kind for r in papers.refs}
    return not any(kind_of.get(i) == "deck" for i in ids)


def _drop_cite_claim(text: str, papers: PaperDoc | None) -> str:
    """첫 응답의 거짓 전제 처리. 전제가 없으면 그대로, 전제 절만 떼어 낼 수 있으면 뗀 문장, 못 떼면 "".

    **가장 덜 파괴적인 쪽을 고른다.** "" 은 호출자에서 기존 ungrounded 처리와 같이 결정적 템플릿으로 떨어진다 —
    그러면 LLM 이 쓴 본론(자료를 근거로 한 좋은 물음)까지 잃는다. 09-24 실측 문장은 「…를 인용하셨는데, 본론?」 꼴이라
    전제 절만 떼면 본론이 그대로 남는다. 관형절(「5장에서 인용한 X (연도)는 …라고 봤는데」)은 떼면 검색 문헌에 허용한
    「X (연도)는 …」 꼴이 된다. 둘 다 아니면(주절 자체가 인용 주장 — "X 를 인용한 이유는?") 뗄 수 없어 템플릿으로 보낸다."""
    if not _claims_presenter_cited(text, papers):
        return text
    out = []
    for sent in _SENTENCE_SPLIT_RE.split(text.strip()):
        if _claims_presenter_cited(sent, papers):
            sent = _CITED_ADNOMINAL_RE.sub("", sent)
            if _claims_presenter_cited(sent, papers):
                sent = _CITED_CLAUSE_RE.sub("", sent, count=1)
            sent = sent.strip(" ,")
        if sent:
            out.append(sent)
    rest = " ".join(out)
    if len(rest) < CITE_CLAIM_REST_MIN or _claims_presenter_cited(rest, papers):
        return ""
    return rest


#: 노드 id 가 슬러그 꼴(concept-graph · sync-analysis)일 때만 라벨로 바꾼다 — "b2b" 같은 낱말 id 는 자연어와 겹쳐 손대지 않는다.
_SLUG_ID_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)+$")


def _unslug(text: str, node: ConceptNode) -> str:
    """문장에 라벨 대신 노드 id 가 그대로 나온 것을 라벨로 바꾼다.

    2026-09-26 실험대 실측(solar, 2회 중 2회): "concept-graph가 발표의 핵심 주장을…" · "sync-analysis가 Q&A 기반 학습에서…".
    프롬프트가 node_id 를 대상 열쇠로 쓰다 보니 문장에도 새어 나온다. 화면 칩은 라벨인데 문장은 영문 슬러그면 다른 개념처럼 읽힌다."""
    nid = (node.id or "").strip()
    if not text or not nid or not node.label or nid == node.label or not _SLUG_ID_RE.match(nid.lower()):
        return text
    return re.sub(re.escape(nid), node.label, text, flags=re.IGNORECASE)


#: 「X보다 …」 — 견주는 대상과 그 뒤 서술어 첫 낱말.
_COMPARE_RE = re.compile(r"([가-힣A-Za-z]{1,12})보다\s+([가-힣]+)")
#: 괄호 안 나열 「(시간, 연속성, 규칙성)」.
_LISTED_RE = re.compile(r"\(([^()]*[,·][^()]*)\)")


def _self_undercut(text: str) -> str:
    """
    「X보다 …」 로 견주면서 같은 문장의 괄호 나열에 X 를 요소로 다시 넣으면 그 X. 아니면 "".

    09-29 수면 발표: "수면의 질이 시간보다 중요한 이유를 … 세 가지 요소(시간, 연속성, 규칙성)를
    바탕으로 설명해 주세요" — 1장(시간보다 중요)과 4장(시간 × 연속성 × 규칙성)을 이어 붙여, 답할 수
    없는 요구가 됐다. 읽는 사람은 "시간이 더 중요하다는 건가" 로 읽었다.
    """
    listed = {
        item.strip() for m in _LISTED_RE.finditer(text or "") for item in re.split(r"[,·]", m.group(1))
    }
    for m in _COMPARE_RE.finditer(text or ""):
        compared = m.group(1)
        if compared in listed:
            return compared
    return ""


def _undercut_question(text: str, node: ConceptNode) -> str:
    """자기모순 문장을 **그 모순을 묻는 문장**으로. 모순이 없으면 그대로.

    부딪힘 자체는 자료에 있다(한 장은 "X보다", 다른 장은 X 를 요소로) — 심사위원이 실제로 찌를 자리라
    버리지 않고 그걸 묻는다. 서술어는 원문의 것을 쓴다 ("중요한" → "중요하다").
    """
    compared = _self_undercut(text)
    if not compared:
        return text
    m = next(m for m in _COMPARE_RE.finditer(text) if m.group(1) == compared)
    pred = m.group(2)
    pred = pred[:-1] + "하다" if pred.endswith("한") and len(pred) > 1 else pred
    subj = node.label + ("이" if node.label and _has_batchim(node.label[-1]) else "가")
    return f"{compared}도 {node.label}의 요소인데, {subj} {compared}보다 {pred}는 건 어떤 뜻인가요?"


def _fit_question(text: str, *, trap: bool = False) -> str:
    """QA_TEXT_MAX 를 넘는 질문을 **문장 단위로** 줄인다. 앞 문장부터 버리고, 남은 것이 해요체 물음으로 끝나야 한다.

    2026-09-24 모바일 실측: LLM 이 225자를 써서 `_clip` 이 199자에서 잘라 "…연구했는데, 이…" 로 나갔다 — 물음이 통째로
    사라진 질문이 화면에 그대로 떴다. qa-cite 재작성 경로(`_apply_cite_rewrite`)는 09-23 교훈으로 길이·끝맺음을 검사했지만
    첫 응답 경로에는 없었다. 못 줄이면 "" — 호출자가 결정적 템플릿으로 보낸다 (잘린 문장보다 템플릿이 낫다).
    함정 질문은 문장을 버리지 않는다(거짓 전제가 앞 문장에 있을 수 있다) — 넘치면 바로 템플릿."""
    t = (text or "").strip()
    if len(t) <= QA_TEXT_MAX:
        return t
    if trap:
        return ""
    sents = [x for x in _SENTENCE_SPLIT_RE.split(t) if x]
    while sents and len(" ".join(sents)) > QA_TEXT_MAX:
        sents.pop(0)
    rest = " ".join(sents).strip()
    if not rest or not _POLITE_END_RE.search(rest):
        return ""
    return rest


def _number_sources(
    by_no: dict[int, Slide] | None, transcript: Transcript | None, papers: PaperDoc | None
) -> list[str]:
    """골자·힌트의 숫자를 대조할 원본 — 자료 글 전체·발화 전체·문헌 제목/초록. 자료 글이 없으면 빈 목록(판단하지 않는다).

    2026-09-26 실험대 실측(solar): 멘토링 신청 폼 2장에 숫자가 하나도 없는데 골자가 "정확도 70~80%"·"전환율 15%"·"3회 진단 뒤" 를
    썼다. 포기하면 「정답 요지」 로 화면에 나가는 문장이다 — 발표자가 방어할 수 없는 숫자를 정답이라고 보여 주는 꼴."""
    if not by_no:
        return []
    out = [clean_slide_text(s.raw_text or "") for s in by_no.values()]
    if transcript is not None and transcript.full_text:
        out.append(transcript.full_text)
    if papers is not None:
        out.extend(f"{r.title} {r.abstract}" for r in papers.refs)
    return [x for x in out if x]


# ---------------------------------------------------------------------------
# 근거 검사 (09-29 기준선 §5 — docs/review/2026-09-29_QA_근거검증/baseline.md). 규칙 본체는 `_grounding` 에 있다.
# ---------------------------------------------------------------------------

#: 발표자가 검색 문헌을 「인용·반영·참고」 했다고 전제하는 꼴.
_SCHOLAR_ADOPTED_RE = re.compile(r"(?:인용|반영|참고|활용|참조)(?:했|하였|한|하셨|하신|된|됐|되었|하고|할)")
#: 인용 표시 바로 뒤가 「논문 안에서」 를 뜻하는 꼴 — 답이 논문 속에 있다는 물음이다.
_SCHOLAR_LOCUS_RE = re.compile(r"\s?(?:의\s?(?:연구|논문|결과|분석|리뷰)(?:에서|는|은|에\s?따르면)|에서는?\s|에\s?따르면|의\s?연구\s)")


def _label_keys(label: str, others: list[str]) -> list[str]:
    """라벨을 부른 것으로 칠 낱말 — 다른 탐침 라벨에 없는 낱말(두 글자 이상). 다 겹치면 라벨의 낱말 전부."""
    own = [t for t in norm_tokens(label) if len(t) >= 2]
    shared = {t for o in others for t in norm_tokens(o)}
    keys = [t for t in own if t not in shared]
    return keys or own


def _mentions_loosely(text: str, label: str, others: list[str]) -> bool:
    """문장이 라벨을 부르는가 — 라벨 통째(`mentions`)거나, 라벨의 변별 낱말 하나가 문장 낱말에 든다 (조사 허용).
    일반화 벤치 §요약: held-out 덱의 라벨은 길고 합성어라(「혈당 스파이크 영향」) LLM 이 풀어 쓰면 통째 대조가 떨어졌다 —
    탐침 질문의 69% 가 템플릿으로 갔다 (튜닝 덱은 0%)."""
    if mentions(text, label):
        return True
    words = norm_tokens(text)
    return any(any(k == w or (len(k) >= 2 and w.startswith(k)) for w in words) for k in _label_keys(label, others))


def _probe_mentions(text: str, probe: Probe, labels: dict[str, str]) -> str:
    """탐침 질문이 탐침 개념을 부르는가. "all" = 전부 통째로, "partial" = 대상 개념 + (둘 이상이면) 다른 개념 하나를 느슨하게,
    "" = 못 부름 (템플릿으로). 대상 개념(node_ids[0])은 반드시 불러야 한다 — 다른 것을 물은 질문이 된다."""
    ids = probe.node_ids
    if not ids:
        return "all"
    if all(mentions(text, labels[i]) for i in ids):
        return "all"
    labs = [labels[i] for i in ids]
    target = _mentions_loosely(text, labs[0], labs[1:])
    other = len(ids) < 2 or any(_mentions_loosely(text, labs[k], [x for j, x in enumerate(labs) if j != k])
                                 for k in range(1, len(ids)))
    return "partial" if target and other else ""


def _asks_about_scholar(text: str, papers: PaperDoc | None) -> bool:
    """
    검색 문헌(kind≠deck)이 질문의 **대상**인가 — 「X (연도)는 어떻게 설명했나요」·「X 를 어떻게 반영했나요」.

    허용하는 꼴은 하나다: 논문을 앞 절의 주어로 세우고(「X (연도)는 …라고 봤는데,」) 물음은 발표에 하는 것
    (`_drop_paper_clause` 가 본론을 떼어 낼 수 있는 꼴). 09-29 기준선: 수면 발표 규칙성 자리에 3/3 번
    「Chaput et al. (2020)의 연구에서 … 어떻게 설명했나요?」 가 나왔다 — 발표자가 인용하지도 읽지도 않은 논문이다.
    """
    if papers is None:
        return False
    by_id = {r.id: r for r in papers.refs}
    for pid in _cited_ids(text, papers):
        ref = by_id.get(pid)
        if ref is None or ref.kind == "deck":
            continue
        if _SCHOLAR_ADOPTED_RE.search(text or ""):
            return True
        at = (text or "").find(ref.cite_key) if ref.cite_key else -1
        # 논문이 답의 자리인 꼴 — 「X (연도)의 연구에서 …?」·「X (연도)에서 …?」·「X (연도)에 따르면 …?」. 앞 절(「…는데,」)로
        # 끝나 본론이 발표를 묻는 꼴이면 허용한다. 「X 의 개념이 여기 어떻게 적용되나요」 처럼 논문을 재료로만 쓰는 물음도 허용한다.
        if at >= 0 and _SCHOLAR_LOCUS_RE.match(text[at + len(ref.cite_key):]) and not _drop_paper_clause(text, ref):
            return True
    return False


#: 프롬프트 예시(카페 재방문 — 어느 실측 덱과도 겹치지 않게 고른 가상 도메인)의 낱말. 09-29 재실행(solar): 인용 재작성이
#: 예시 문장 「발표가 말한 재방문 감소도 좌석이 부족한 경우를 포함하나요?」 를 수면 발표 질문에 그대로 베꼈다 (09-29 앞선 실측의
#: 「비가시적 집중 손실」 베낌과 같은 버릇). 자료에 없는 예시 낱말이 둘 이상이면 베낀 문장으로 본다.
_PROMPT_EXAMPLE_WORDS = ("카페", "재방문", "좌석", "대기 시간", "만족도", "매장", "분위기", "동선")


def _copies_prompt_example(text: str, idx) -> bool:
    hits = [w for w in _PROMPT_EXAMPLE_WORDS if grounding.mentions(text, w) and (idx is None or not grounding.mentions(idx.text, w))]
    return len(hits) >= 2


def _touched_paper_texts(raw: dict, papers: PaperDoc | None) -> list[str]:
    """이 질문(raw)이 건드린 검색 문헌의 제목·초록 — 문장에서 인용했거나, paper_ids 에 적었거나, 인용 검사가 떼어 낸 것."""
    if papers is None:
        return []
    ids = {str(x) for x in (raw.get("paper_ids") or [])}
    ids |= {str(raw.get("_paper_stripped"))} if raw.get("_paper_stripped") else set()
    for key in ("question", "why", "hint", "answer_gist"):
        ids.update(_cited_ids(str(raw.get(key, "") or ""), papers))
    return [f"{r.title} {r.abstract}" for r in papers.refs if r.id in ids and r.kind != "deck"]


def _cites_scholar(text: str, papers: PaperDoc | None) -> bool:
    """글이 검색 문헌을 인용 표시로 부르는가 (자료가 인용한 문헌은 뺀다)."""
    if papers is None:
        return False
    kind_of = {r.id: r.kind for r in papers.refs}
    return any(kind_of.get(pid) != "deck" for pid in _cited_ids(text, papers))


#: 골자가 전제를 바로잡는 표지 — 부정·대조 (어느 발표에나 쓰는 말이다).
_CORRECTS_PREMISE_RE = re.compile(r"아니라|아니에요|아닙니다|아니고|달리|다르|반대|사실은|오히려|않|없|틀렸|전제")

#: 증거로 다시 쓰는 골자에 실을 자료 줄 수. 셋이면 화면 한 칸을 넘는다.
EVIDENCE_GIST_LINES = 2


def _evidence_gist(
    node: ConceptNode, question: str, anchors: list[int], by_no: dict[int, Slide] | None, *, trap: bool = False,
) -> str:
    """
    근거 장에서 **이 질문을 받치는 자료 줄** 로 조립한 골자. 자료가 없으면 "".

    LLM 골자가 근거 검사에서 떨어졌을 때 쓴다 (gist_rebuilt). 예전 폴백은 개념 요약 + 「(1, 2, 3장 근거)」 라 답이 아니었고
    (09-29 기준선 §5-8: 「개인 투자자 집단의 평균 수익률 (1, 2, 3장 근거)」 를 말하면 good 85), 판정은 그걸 채점 기준으로 썼다.
    자료 줄 그대로라 지어낸 것이 없다. 함정 질문이면 「전제와 달리」 로 연다 — 정답은 전제를 바로잡는 것이다.
    """
    if not by_no:
        return ""
    texts = [(no, by_no[no].raw_text or "") for no in anchors if no in by_no]
    found = [(no, q) for no, q in ranked_quotes(node.label, node.summary, texts, question, k=EVIDENCE_GIST_LINES) if q]
    if not found:
        return ""
    # 가장 맞는 줄의 장에 설명 표가 있으면 둘째 줄 대신 그 표 — 사실은 표에 있고 글 줄은 제목인 장이 많다.
    # 09-29 재실행: 「수면 주기를 끊는 구체적인 원인은?」 의 다시 쓴 골자가 제목 두 줄이었고 원인 표(카페인 | 오후·저녁 섭취 …)가 빠졌다.
    table = grounding.described_table(found[0][0], by_no[found[0][0]].raw_text or "") if found[0][0] in by_no else ""
    if table:
        found = [found[0], (found[0][0], table)]
    nos = sorted({no for no, _ in found})
    body = " · ".join(q.rstrip(" .") for _, q in found)
    where = ", ".join(str(n) for n in nos)
    lead = "질문의 전제와 달리, 자료는 이렇게 말해요 — " if trap else "자료는 이렇게 말해요 — "
    return _clip(f"{lead}{body} ({where}장)")


def _trap_verdict(question: str, premise: str, idx) -> str:
    """함정 표시를 뗄 이유. "" 이면 함정이다. 전제가 질문에 없거나(없는 전제) 자료가 그 전제를 사실로 말하면 뗀다."""
    if not question:
        return "no_question"
    if not (premise or "").strip():
        return "no_premise"
    if not grounding.premise_in_question(premise, question):
        return "premise_not_in_question"
    return grounding.premise_drop_reason(premise, idx)


#: 발화 인용에서 건너뛸 인사·진행 멘트. 발표 내용이 아니라 어느 발표에나 있는 말이다.
_FILLER_SPEECH_RE = re.compile(
    r"안녕하세요|안녕하십니까|감사합니다|고맙습니다|시작하겠습니다|마치겠습니다|질문\s*받겠습니다|"
    r"발표를?\s*(?:시작|마치)|시작하기\s*전에|오늘\s*(?:주제|발표)는|제\s*발표|저희\s*(?:팀|조)은"
)
#: STT 는 문장부호가 없다 — 해요체·합쇼체 끝에서 자른다.
_SPEECH_SENT_RE = re.compile(r"(?<=[.?!])\s+|(?<=니다)\s+|(?<=[요죠])\s+")


def _speech_quote(anchors: list[int], transcript: Transcript | None, question: str = "",
                  node: ConceptNode | None = None) -> str:
    """
    anchor 장에서 실제로 한 말 가운데 **이 질문과 겹치는** 한 구절. 인사·진행 멘트는 건너뛴다. 없으면 "".

    09-29 기준선 §5-12: 예전엔 근거 장 발화의 앞 120자라 「아 안녕하세요 오늘 주제는…」·「여러분 … 떠올려 보셨으면」 이
    explain 해설 끝에 「발표에서는 «…» 라고 말했어요」 로 붙었다.
    """
    if transcript is None:
        return ""
    lines: list[str] = []
    for no in anchors:
        for sent in _SPEECH_SENT_RE.split(transcript.text_for_slide(no) or ""):
            sent = sent.strip()
            if sent and not _FILLER_SPEECH_RE.search(sent):
                lines.append(sent)
    if not lines:
        return ""
    label, summary = (node.label, node.summary) if node is not None else ("", "")
    return best_quote(label, summary, [(0, "\n".join(lines))], question)[1]


def _normalize_questions(
    raw_questions: list[dict],
    marks: list[TriageMark],
    by_id: dict[str, ConceptNode],
    flow_of: dict[str, FlowIssue] | None = None,
    by_no: dict[int, Slide] | None = None,
    transcript: Transcript | None = None,
    papers: PaperDoc | None = None,
    probe_of: dict[str, Probe] | None = None,
    slot_of: dict[str, str] | None = None,
    claims: ClaimDoc | None = None,
) -> list[Question]:
    """
    raw 질문을 대상마다 정확히 1개씩으로 정리한다.

    - 대상 밖 node_id 는 버린다. 같은 node_id 가 여러 번 오면 첫 번째만
    - 빠진 대상은 결정적 템플릿 문장으로 메운다 (질문 세트에 구멍을 내지 않는다)
    - id 는 rank·node_id 에서 결정적으로 만든다 — 같은 triage 면 같은 결과가 나온다
    - 모든 문장은 QA_TEXT_MAX 로 자른다
    - papers 가 있으면 **목록 밖 논문을 인용한 문장은 버리고** 템플릿으로 메운다 (citation_grounded = 1.0)
    - 모든 질문에 근거 묶음(QuestionBasis)을 채운다 — 근거·배합 자리·순위·탐침·인용·걸린 검사 (P1)
    - 탐침 질문(probe_of)은 탐침의 대상 개념(+둘 이상이면 다른 하나)을 불러야 한다 — 라벨 통째거나 변별 낱말.
      못 부르면 탐침 템플릿이다 (P4). 힌트 인용도 탐침의 근거 원문에서 고른다. 탐침 질문은 함정이 아니다.
    - 근거 검사 (09-29 기준선 §5 · 규칙은 `_grounding`): 함정은 질문에 얹힌 전제(trap_premise)가 자료와 정말 어긋날 때만,
      골자는 숫자의 주어·비교·표의 행이 자료와 맞을 때만 (아니면 근거 장 자료 줄로 다시 쓴다), 방법·측정 질문은 근거 장에
      방법·수치·출처가 있을 때만, 검색 문헌은 질문의 대상이 될 수 없고 골자·힌트에 논문 이야기가 남지 않는다.
    """
    target_ids = {m.node_id for m in marks}
    number_sources = _number_sources(by_no, transcript, papers)
    # 근거 검사 색인 (09-29 기준선 §5). 자료가 없으면 None — 검사들이 판단하지 않고 예전처럼 둔다.
    idx = grounding.build_index(by_no or {}, list(by_id.values()),
                                transcript.full_text if transcript is not None else "")
    written: dict[str, dict] = {}
    for raw in raw_questions:
        node_id = str(raw.get("node_id", "") or "")
        if node_id in target_ids and node_id not in written:
            written[node_id] = raw

    questions: list[Question] = []
    for mark in marks:
        node = by_id[mark.node_id]
        raw = written.get(mark.node_id) or {}
        # 질문의 근거 장은 anchor 다 — 힌트·모범답·화면의 장 그림·판정의 본문이
        # 전부 이 목록을 따라가므로, 프롬프트에 실린 장과 같아야 한다.
        anchors = _anchor_nos(node, by_no or {})
        fb_question, fb_why, fb_hint = _fallback_text(
            node, mark, (flow_of or {}).get(mark.node_id), slide_nos=anchors
        )

        # 발판을 근거로 인용한 문장은 없는 것으로 친다 — 아래 `or` 가 결정적
        # 템플릿으로 떨어뜨린다. 자료로 만든 문장이 발판 인용보다 언제나 낫다.
        # 높임을 먼저 풀고(_plain_speech) 끝 어미를 고친다(_polite_question). 거짓 전제(검색 문헌에 「인용하셨는데」)는
        # 전제 절만 떼고, 못 떼면 "" — 아래 `or` 가 ungrounded 와 같은 템플릿으로 보낸다 (_drop_cite_claim 참고).
        # 합쇼체(to_haeyo)도 여기서 푼다 — 09-26 실측: "고민된다고 했습니다." 가 질문 가운데, "…할 수 있습니다." 가 골자에.
        # 질문은 자르지 않고 문장 단위로 줄인다(_fit_question) — 잘린 물음은 물음이 아니다.
        def _tidy(key: str) -> str:
            return to_haeyo(_second_person(_plain_speech(_unslug(str(raw.get(key, "") or ""), node))))

        def _tidy_statement(key: str) -> str:
            # 힌트·이유·골자는 해라체(「생각해 보라」)·한다체(「…근거로 한다」)도 푼다 — 09-29 기준선 §5-10.
            return _drop_cite_claim(_clip(_polite_statement(_tidy(key))), papers)

        # 근거 묶음에 남길 검사 이름 (P1). "이 질문이 왜 이 문장인가" 를 코드를 다시 안 돌려도 답할 수 있게 한다.
        checks: list[str] = []
        probe = (probe_of or {}).get(mark.node_id)
        trap = mark.trap

        fitted = _fit_question(_polite_question(_tidy("question")), trap=mark.trap)
        written_q = _drop_cite_claim(fitted, papers)
        if fitted and not written_q:
            checks.append("cite_claim_dropped")
        # 검색 문헌을 질문의 대상으로 삼은 문장은 버린다 (`_asks_about_scholar`, 규칙 3-7).
        if written_q and _asks_about_scholar(written_q, papers):
            written_q = ""
            checks.append("scholar_question_dropped")
        # 논문에서 온 흔적 (09-29 기준선 §5-5). 이 질문 칸들이 불렀거나 인용 검사가 떼어 낸 검색 문헌의 제목·초록이 대조 원본이다.
        # 논문 절을 뗐거나 논문 질문을 버렸으면(suspect) 자료·발화에 없는 낱말이 절반 넘는 문장도 흔적으로 본다.
        paper_texts = _touched_paper_texts(raw, papers)
        suspect = bool(raw.get("_paper_stripped")) or "scholar_question_dropped" in checks
        if written_q and raw.get("_paper_stripped") and grounding.paper_residue(written_q, idx, paper_texts, novel=True):
            written_q = ""
            checks.append("paper_residue_dropped")
        # 함정은 **질문에 얹힌 전제가 자료와 정말 어긋날 때만** 함정이다 (09-29 기준선 §5-1). triage 가 함정이라 해도
        # 질문 문장에 전제가 없거나, 전제가 자료에 사실로 있으면 뗀다 — 그대로 두면 판정이 골자대로 한 정답을
        # 「전제를 안 바로잡았다」 며 wrong 35 로 내린다 (두 덱 루트 질문 4/4).
        if trap:
            why_not = _trap_verdict(written_q, str(raw.get("trap_premise", "") or ""), idx)
            if why_not:
                trap = False
                checks.append("trap_dropped")
                sys.stderr.write(f"[f08] 함정 뗌 {mark.node_id}: {why_not}\n")
            else:
                checks.append("trap_premise_verified")
        if written_q and not trap:
            undercut = _undercut_question(written_q, node)
            if undercut != written_q:
                checks.append("undercut_rewritten")
            written_q = undercut
        written_gist = _tidy_statement("answer_gist")
        written_why = _tidy_statement("why")
        written_hint = _tidy_statement("hint")
        # 자료·발화·문헌 어디에도 없는 숫자는 지어낸 것이다 — 아래 `or` 가 결정적 템플릿으로 보낸다 (_number_sources 참고).
        # 함정 질문의 문장은 거짓 전제가 설계라 보지 않는다. 골자·힌트·이유는 함정이어도 자료가 말하는 것이어야 한다.
        if number_sources:
            before = (written_q, written_gist, written_why, written_hint)
            if not trap and ungrounded_numbers(written_q, number_sources):
                written_q = ""
            if ungrounded_numbers(written_gist, number_sources):
                written_gist = ""
            if ungrounded_numbers(written_why, number_sources):
                written_why = ""
            if ungrounded_numbers(written_hint, number_sources):
                written_hint = ""
            if before != (written_q, written_gist, written_why, written_hint):
                checks.append("ungrounded_number_dropped")
        before = (written_q, written_gist, written_why, written_hint)
        if _cites_scaffold(written_q) or _ungrounded_citation(written_q, papers) or _copies_prompt_example(written_q, idx):
            written_q = ""
        if _cites_scaffold(written_gist) or _ungrounded_citation(written_gist, papers) or _copies_prompt_example(written_gist, idx):
            written_gist = ""
        if _cites_scaffold(written_why) or _ungrounded_citation(written_why, papers) or _copies_prompt_example(written_why, idx):
            written_why = ""
        if _cites_scaffold(written_hint) or _ungrounded_citation(written_hint, papers) or _copies_prompt_example(written_hint, idx):
            written_hint = ""
        if before != (written_q, written_gist, written_why, written_hint):
            checks.append("scaffold_or_citation_dropped")
        # 방법·측정 질문은 근거 장에 방법·수치·출처가 있을 때만 (규칙 3-6). 09-29 기준선 §5-4: 「어떻게 측정/계산/정량화했나요」
        # 4건이 자료에 없는 것을 물었고, 골자는 「실험적 관찰을 바탕으로」 처럼 전제에 동의하며 지어냈다.
        if written_q and grounding.asks_method(written_q) and not grounding.method_supported(written_q, anchors, idx):
            written_q = ""
            checks.append("method_unsupported")

        if probe is not None:
            # (a) 탐침 개념 이름이 전부 문장에 있어야 탐침을 물은 것이다. 이름 하나라도 빠지면 탐침과 다른 것을
            # 물은 질문이라, 부탁(프롬프트)만 믿지 않고 코드가 탐침 템플릿으로 바꾼다 (09-12 교훈과 같은 규율).
            labels = {i: (by_id[i].label if i in by_id else i) for i in probe.node_ids}
            # 탐침 질문은 함정이 아니다 — 탐침은 자료 **안에** 진짜로 있는 긴장·빈틈이라 거짓 전제가 아니다 (일반화 벤치 §3:
            # 수면 긴장 질문이 함정으로 나가 골자를 그대로 말한 답이 wrong 35).
            if trap:
                trap = False
                checks.append("trap_dropped")
            hit = _probe_mentions(written_q, probe, labels) if written_q else ""
            if hit:
                checks.append("mentions_probe_nodes" if hit == "all" else "mentions_probe_nodes_partial")
            else:
                if written_q:
                    checks.append("probe_nodes_missing")
                written_q = probe_question(probe, labels, by_id, claims)
                checks.append("probe_template")
                # 템플릿은 함정이 아니다 — 거짓 전제를 안 얹었는데 함정으로 두면 골자가 "전제가 달라요" 로 나간다.
                trap = False
            # why 가 비었거나 탐침 개념을 하나도 안 부르면 탐침에서 만든 이유를 쓴다 — 「이 질문의 근거」 와 같은 말이 된다.
            if not written_why or not any(mentions(written_why, labels[i]) for i in probe.node_ids):
                written_why = probe_why(probe)
                checks.append("why_from_probe")
        elif not written_q:
            checks.append("fallback_template")
        if not written_q and trap:
            trap = False     # 폴백 문장에는 전제가 없다 — 함정 폴백 골자(「전제가 자료와 달라요」)가 참인 질문에 붙지 않게
            checks.append("trap_dropped")
        if not written_q:
            # 폴백 문장에는 LLM 골자·요소가 맞지 않는다 — 버린 질문에 대한 답이다. 09-29 재실행: 논문 질문을 버린 자리의
            # 골자가 그 논문 초록(「SRQ 는 … 약한 상관」)을 그대로 말했다. 근거 장 자료 줄로 다시 쓴다 (아래 `or`).
            written_gist = ""

        question_text = written_q or fb_question
        # 힌트·코칭이 그대로 옮겨 보여 줄 인용 — LLM 없이 즉시 나와야 하므로 여기서 저장한다.
        # 질문 문장이 정해진 뒤에 고른다 — 힌트는 질문이 가리키는 자리를 보여 줘야 한다 (폴백·템플릿 문장이어도 같다).
        # (b) 탐침 질문은 탐침의 근거 원문 가운데서 고른다 — 질문이 짚은 부딪힘을 힌트가 그대로 보여 준다.
        quote_no, quote = _probe_quote(node, probe, question_text, by_no) if probe is not None else (0, "")
        if quote:
            checks.append("probe_evidence_quote")
        else:
            quote_no, quote = _evidence_quote(node, anchors, by_no or {}, question_text)
        speech = _speech_quote(anchors, transcript, question_text, node) if quote else ""

        # 문헌에서 온 말 (09-29 기준선 §5-5). 질문이 문헌을 인용하지 않았으면 이유·힌트도 문헌을 말하지 않는다.
        # 골자는 언제나 자료로만 쓴다(PAPER_SYSTEM_ADDENDUM) — 검색 문헌 인용·「문헌·논문」 이야기는 문장째 뗀다.
        # 논문 절을 뗀 질문이면(_paper_stripped) 자료·발화에 없는 낱말이 절반 넘는 문장도 뗀다 — 논문 절의 흔적이다.
        question_cites = bool(_cited_ids(question_text, papers))
        for key in ("why", "hint"):
            val = written_why if key == "why" else written_hint
            if val and not question_cites and (_cites_scholar(val, papers) or grounding.paper_talk(val, idx)
                                               or grounding.paper_residue(val, idx, paper_texts)):
                checks.append(f"{key}_paper_dropped")
                if key == "why":
                    written_why = ""
                else:
                    written_hint = ""
        if written_gist:
            kept = [x for x in grounding.sentences(written_gist)
                    if not _cites_scholar(x, papers) and not grounding.paper_talk(x, idx)
                    and not grounding.paper_residue(x, idx, paper_texts, novel=suspect)]
            if len(kept) != len(grounding.sentences(written_gist)):
                checks.append("gist_paper_stripped")
                written_gist = " ".join(kept)
        # 골자 근거 검사 — 숫자의 주어·비교·표의 행 (`_grounding.gist_problems`). 떨어지면 근거 장 자료 줄로 다시 쓴다.
        problems = grounding.gist_problems(written_gist, idx)
        if problems:
            sys.stderr.write(f"[f08] 골자 다시 씀 {mark.node_id}: {','.join(problems)} · 골자: {written_gist[:80]}\n")
            written_gist = ""
            checks.append("gist_rebuilt")
        elif not written_gist:
            checks.append("gist_template")
        # 남은 함정의 골자는 전제를 바로잡아야 한다 (규칙: trap 골자는 자료의 사실로 전제를 뒤집는다). 일반화 벤치 §3: 함정 21개 모두
        # 골자에 바로잡는 말이 없었다 — 그 골자를 그대로 말해도 판정은 「전제를 안 바로잡았다」 로 내린다. 바로잡는 말이 없으면
        # 「질문의 전제와 달리, 자료는 …」 로 근거 장 자료 줄을 쓴다.
        if trap and written_gist and not _CORRECTS_PREMISE_RE.search(written_gist):
            written_gist = ""
            checks.append("gist_rebuilt_trap")
        gist = written_gist or _evidence_gist(node, question_text, anchors, by_no, trap=trap) \
            or _fallback_gist(node, trap=trap, slide_nos=anchors)
        # 요소 쪼개기. LLM 이 쓴 것을 먼저 믿고, 안 썼는데 문면이 둘 이상을 묻고
        # 있으면 코드가 골자를 갈라 백스톱을 세운다 (_followup·_OPEN_QUESTION_RE 와
        # 같은 규율 — 프롬프트로 부탁만 해서는 안 지켜지는 것을 코드가 받는다).
        parts = [
            p for p in (
                _drop_cite_claim(_clip(_polite_statement(to_haeyo(_plain_speech(_unslug(str(p) or "", node))))), papers)
                for p in (raw.get("answer_gist_parts") or [])
            )
            if p and not _cites_scaffold(p) and not _ungrounded_citation(p, papers)
            and not (number_sources and ungrounded_numbers(p, number_sources))
            and not _cites_scholar(p, papers) and not grounding.paper_talk(p, idx)
            and not grounding.paper_residue(p, idx, paper_texts, novel=suspect)
            and not grounding.gist_problems(p, idx)
        ]
        # 골자가 템플릿·자료 줄로 떨어졌으면 LLM 의 요소도 같은 출처다 — 지어낸 골자의 조각을 요소로 남기지 않는다.
        if not written_gist:
            parts = []
        if len(parts) < 2 and _asks_multiple(question_text):
            parts = _split_gist_parts(gist)
        paper_ids = _paper_ids_of(
            raw, [question_text, written_why, written_hint, gist], papers,
        ) if written_q and "probe_template" not in checks else []   # 탐침 템플릿은 문헌을 인용하지 않는다

        questions.append(Question(
            id=f"q{mark.rank:02d}-{mark.node_id}",
            node_id=mark.node_id,
            label=node.label,
            question=question_text,
            why=written_why or fb_why,
            hint=written_hint or fb_hint,
            severity=mark.severity,
            trap=trap,
            source=mark.source,
            slide_nos=list(anchors),
            doc_weight=mark.doc_weight,
            answer_gist=gist,
            # 「비었거나 2개 이상」 불변식은 Question 이 지킨다 (contracts._gist_parts_of).
            answer_gist_parts=parts,
            evidence_slide_no=quote_no,
            evidence_quote=quote,
            speech_quote=speech,
            paper_ids=paper_ids,
            basis=_basis_of(mark, (slot_of or {}).get(mark.node_id, ""), probe, quote_no, quote, checks),
        ))
    return questions


def _basis_of(
    mark: TriageMark, slot: str, probe: Probe | None, quote_no: int, quote: str, checks: list[str],
) -> QuestionBasis:
    """
    이 질문의 근거 묶음 (P1). 인용은 탐침 근거 원문 전부 + 힌트 인용(없던 것이면 뒤에) — 화면 「이 질문의 근거」 와
    로그가 같은 목록을 읽는다. 탐침은 트리아지 캐시의 것을 그대로 물지 않고 사본으로 싣는다.
    """
    evidence = [ClaimQuote(slide_no=e.slide_no, quote=e.quote) for e in (probe.evidence if probe else [])]
    if quote and not any(e.slide_no == quote_no and e.quote == quote for e in evidence):
        evidence.append(ClaimQuote(slide_no=quote_no, quote=quote))
    return QuestionBasis(
        source=mark.source,
        slot=slot,
        rank=mark.rank,
        probe=Probe.from_dict(probe.to_dict()) if probe else None,
        evidence=evidence,
        checks=list(checks),
    )


def _probe_quote(
    node: ConceptNode, probe: Probe, question: str, by_no: dict[int, Slide] | None = None,
) -> tuple[int, str]:
    """
    탐침 근거 원문 가운데 이 질문을 가장 잘 받치는 한 줄 (`best_quote`). 인용이 인용 후보로 너무 짧으면
    (QUOTE_MIN 미만) 그 인용이 나온 **장의 원문**에서 고른다 — 그래도 탐침이 가리킨 장이다. 없으면 (0, "").
    """
    texts = [(e.slide_no, e.quote) for e in probe.evidence if e.quote]
    found = best_quote(node.label, node.summary, texts, question) if texts else (0, "")
    if found[1] or not by_no:
        return found
    nos = sorted({e.slide_no for e in probe.evidence if e.slide_no in by_no})
    return best_quote(node.label, node.summary, [(no, by_no[no].raw_text or "") for no in nos], question) if nos else (0, "")


def _evidence_quote(
    node: ConceptNode, anchors: list[int], by_no: dict[int, Slide], question: str = "",
) -> tuple[int, str]:
    """anchor 장 전부에서 이 질문을 가장 잘 받치는 한 줄. (장 번호, 문장). 없으면 (0, "").

    장을 앞에서부터 보고 첫 문장을 쓰면 표지가 늘 이긴다 — 09-29 수면 발표에서 질문은 4장의
    식(시간 × 연속성 × 규칙성)을 묻는데 힌트는 1장 설문 보기를 붙여 보여 줬다 (`best_quote`).
    """
    texts = [(no, by_no[no].raw_text or "") for no in anchors if no in by_no]
    return best_quote(node.label, node.summary, texts, question)


def _with_probes(triage: QaTriage, graph: ConceptGraph, claims: ClaimDoc | None) -> QaTriage:
    """
    탐침이 든 triage. 이미 들고 왔으면 그대로, 없는데 claims 가 오면 찾아서 근거를 올린 **새 triage** 를 준다.

    순위(rank)는 안 바꾼다 — triage 의 순위는 LLM severity 까지 반영된 것이라 여기서 다시 매기면 1차 심사를
    버리는 꼴이다. 근거(source)만 올라가서 weak 자리(_WEAK_SOURCES)가 탐침을 알아본다.
    """
    if triage.probes or claims is None:
        return triage
    probes = derive_probes(graph, claims)
    if not probes:
        return triage
    best = _probes_by_node(probes)
    marks = []
    for m in triage.marks:
        p = best.get(m.node_id)
        source = p.kind if p is not None and _SOURCE_RANK[p.kind] < _SOURCE_RANK[m.source] else m.source
        marks.append(TriageMark(node_id=m.node_id, severity=m.severity, trap=m.trap, angle=m.angle,
                                source=source, rank=m.rank, doc_weight=m.doc_weight))
    return QaTriage(file_name=triage.file_name, total_slides=triage.total_slides, marks=marks,
                    model=triage.model, probes=probes)


#: 로그 한 줄에 실을 인용 길이. 줄이 터미널 한 줄을 넘으면 다른 로그와 섞여 못 읽는다.
LOG_QUOTE_MAX = 60


def _log_bases(questions: list[Question]) -> None:
    """질문마다 근거 한 줄 — 브리지 로그(stderr)에 「[f08] 인용 주장 검사」 와 나란히 남는다."""
    for n, q in enumerate(questions, start=1):
        b = q.basis or QuestionBasis(source=q.source)
        ev = f"S{q.evidence_slide_no} «{q.evidence_quote[:LOG_QUOTE_MAX]}»" if q.evidence_quote else "-"
        sys.stderr.write(
            f"[f08] 질문 {n}: slot={b.slot or '-'} node={q.node_id} source={b.source} "
            f"probe={b.probe.kind if b.probe else '-'} rank={b.rank} 근거={ev}"
            f"{' 검사=' + ','.join(b.checks) if b.checks else ''}\n"
        )


def build_questions(
    graph: ConceptGraph | dict,
    triage: QaTriage | dict,
    *,
    track: str = QA_TRACK_FALLBACK,
    alignment: AlignmentDoc | dict | None = None,
    flow: FlowDiff | dict | None = None,
    transcript: Transcript | dict | None = None,
    slidedoc: SlideDoc | dict | None = None,
    context: Context | dict | None = None,
    papers: PaperDoc | dict | None = None,
    memory: MemoryDoc | dict | None = None,
    pace: PaceDoc | dict | None = None,
    claims: ClaimDoc | dict | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> QuestionDoc:
    """
    ConceptGraph + QaTriage (+선택 track·AlignmentDoc·FlowDiff·Transcript·Context·PaperDoc·MemoryDoc)
    → QuestionDoc.

    memory(F-25 MemoryDoc) 를 주면 질문 대상 개념에 「지난 리허설: …」 한 줄이 붙어, 질문이 지난번의 빈틈을
    겨냥한다. 사실(판정·횟수·빠진 점)만 싣고 답변 원문은 싣지 않는다. 안 주면 프롬프트가 예전과 글자까지 같다.

    papers(F-24 PaperDoc) 를 주면 「교수가 읽고 온 문헌」 이 프롬프트에 실리고, 질문은
    그 문헌을 근거로 찌를 수 있다. **목록 밖 논문을 인용한 문장은 코드가 버린다** — 질문
    속 인용은 전부 PaperDoc 에 실재하고, `Question.paper_ids` 와 `QuestionDoc.papers` 로
    화면이 되짚는다. 안 주면 프롬프트·시스템 프롬프트가 예전과 글자까지 같다.

    무엇을 물을지는 triage 가 이미 정했다. 여기서는 트랙 상한만큼 자르고
    LLM 에 문장만 받아 온다. 같은 triage·같은 track 이면 질문 id 까지 같다.

    개념마다 parent 경로·relates 이웃·근거 장 발화를 함께 줘서, 정의를 묻는 질문 대신
    관계를 파고드는 질문이 나오게 한다. flow 를 주면 weak_flow 근거 개념에 이슈
    상세(순서 역행·연결 누락)가 붙어 "왜 이 순서로 설명했나요?" 류 질문이 가능해진다
    — 순위는 안 바뀐다, 프롬프트 재료일 뿐이다.

    slidedoc 을 주면 개념마다 **근거 장의 자료 본문**이 함께 실려, 모범답
    (`answer_gist`)이 자료 밖 지식으로 살을 붙이는 것을 프롬프트가 가리킬 수 있다.
    **안 주면 예전과 완전히 같은 프롬프트다** — 이 인자는 켜야 도는 것이라,
    호출자가 안 넘기면 이 기능은 통째로 잠잔다.

    triage 에는 자료 본문을 안 준다. 1차 심사는 «물을 만한 개념인가» 만 고르고
    순위는 결정적 신호에서 나오므로, 본문을 실어도 순위는 안 바뀌고 토큰만 는다.

    탐침(P3·P4): triage 가 이미 probes 를 들고 오면(triage_questions(claims=…)) 그것을 쓴다. 옛 triage(탐침 없음)에
    claims 만 따로 오면 여기서 탐침을 찾아 marks 의 근거를 올린 **사본**을 쓴다 — 캐시된 triage 는 안 건드린다.
    탐침 개념의 질문은 탐침 각도·근거 원문에 묶이고(프롬프트), 탐침 개념 이름이 빠지면 템플릿으로 바뀐다(코드).

    모든 질문에 `Question.basis`(근거·배합 자리·순위·탐침·인용·검사)가 채워지고, 질문마다 stderr 에
    「[f08] 질문 n: slot=… node=… source=… probe=… 근거=S4 «…»」 한 줄을 남긴다 — "이 질문은 왜 나왔나" 를
    코드를 다시 돌리지 않고 답하려고 (2026-09-29 사용자 질문).
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
    if isinstance(slidedoc, dict):
        slidedoc = SlideDoc.from_dict(slidedoc)
    if isinstance(papers, dict):
        papers = PaperDoc.from_dict(papers)
    if papers is not None and not papers.refs:
        papers = None   # 빈 문헌은 없는 것과 같다 — 프롬프트를 바꾸지 않는다
    if isinstance(memory, dict):
        memory = MemoryDoc.from_dict(memory)
    memory_of = memory.by_node(graph) if memory is not None else {}
    ctx = _as_context(context)

    if track not in QA_TRACKS:
        track = QA_TRACK_FALLBACK
    claim_doc = as_claims(claims)
    triage = _with_probes(triage, graph, claim_doc)
    probe_of = _probes_by_node(triage.probes)

    # 합성 노드(extra:)도 사전에 넣는다. triage 가 후보로 올렸는데 여기서 빠지면
    # `known` 필터가 조용히 떨어뜨려, 발화 개념 질문이 이유 없이 사라진다.
    by_id = {n.id: n for n in (*graph.nodes, *_extra_nodes(alignment))}
    known = [m for m in triage.marks if m.node_id in by_id]
    if not known:
        raise QuestionError(
            "QaTriage 에 이 그래프의 개념이 없습니다. "
            "triage 가 같은 ConceptGraph 에서 나온 것인지 확인하세요."
        )

    depth_of = {n.id: n.depth for n in graph.nodes}
    stalled = {nid for nid, cm in memory_of.items() if cm.stalled}
    slot_of: dict[str, str] = {}
    marks, deferred = _pick_marks(known, track, depth_of, stalled, slot_of)
    # 탐침은 근거가 그 탐침인 개념에만 묶는다 — 모순·누락처럼 더 앞선 근거로 뽑힌 개념까지 탐침으로 끌면 근거가 섞인다.
    probe_of = {m.node_id: probe_of[m.node_id] for m in marks
                if m.node_id in probe_of and probe_of[m.node_id].kind == m.source}
    engine = _engine(llm, llm_kwargs)
    flow_of = _flow_issue_by_node(flow)

    by_no = _slides_by_no(slidedoc)
    paper_plan = _plan_papers(marks, by_id, by_no, papers, track)
    prompt = _build_question_prompt(
        graph, marks, by_id, alignment, transcript, ctx, flow_of, by_no, papers, memory_of, paper_plan,
        _rushed_slides(_as_pace(pace), graph), probe_of,
    )
    remembered = any(m.node_id in memory_of for m in marks)
    raw_questions = _questions_with_papers(
        engine, prompt, marks,
        QUESTION_SYSTEM_PROMPT
        + (PAPER_SYSTEM_ADDENDUM if paper_plan else "")
        + (MEMORY_SYSTEM_ADDENDUM if remembered else "")
        + (PROBE_SYSTEM_ADDENDUM if probe_of else ""),
        by_id, by_no, papers, paper_plan,
    )

    # 골자가 사실상 같은 질문은 뒤로 민다. 한 번 답하면 셋이 다 닫히는 5분 트랙의
    # 중복이 여기서 걸린다 — 대신 개수는 안 줄고, 밀린 개념은 deferred 로 간다.
    questions, twins = _drop_twin_questions(
        _normalize_questions(raw_questions, marks, by_id, flow_of, by_no, transcript, papers,
                             probe_of, slot_of, claim_doc),
        QA_TRACK_LIMITS[track],
    )
    _log_bases(questions)

    used = {pid for q in questions for pid in q.paper_ids}
    return QuestionDoc(
        file_name=graph.file_name,
        total_slides=graph.total_slides,
        track=track,
        questions=questions,
        deferred_node_ids=twins + deferred,
        model=engine.name,
        papers=[r for r in papers.refs if r.id in used] if papers is not None else [],
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


def _hint_locate(question: Question) -> str:
    """
    0단계 · 위치. **자료의 문장을 그대로** 보여 준다 — "자료 3장은 이렇게 말해요: «…»".

    기억을 요구하는 대신 보고 짚게 한다. 장 번호가 문장에 있어서 화면이 그 장 그림을
    같이 띄운다 (qa_live.js `hintSlideNos`). F-08 이 slidedoc 없이 만든 질문은 인용이
    없어 빈 문자열 — 그때 사다리는 예전 그대로다.
    """
    if not question.evidence_quote:
        return ""
    where = f"자료 {question.evidence_slide_no}장은" if question.evidence_slide_no else "자료는"
    return _clip(f"{where} 이렇게 말해요: «{question.evidence_quote}»")


def _hint_scaffold(question: Question) -> str:
    """
    발판. 골자에서 낱말 하나를 가린 빈칸 — 답을 통째로 주지 않으면서 문장의 뼈대를 준다.
    인용이 있는 질문에서만 (옛 질문의 사다리 길이를 바꾸지 않는다).
    """
    if not question.evidence_quote:
        return ""
    masked, _, _ = mask_gist(question.answer_gist, question.label, [])
    return _clip(f"빈칸을 채워 보세요: {masked}") if masked else ""


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
        return _clip(f"{shown}장을 비롯해 {len(nos)}장에 걸쳐 나와요 — 앞쪽부터 짚어 보세요")
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
    return _clip(f"이 방향이에요 — {fragment}") if fragment else ""


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
    return _clip(f"이 방향이에요 — {fragment}") if fragment else ""


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

    steps = [
        _hint_locate(question),
        _hint_direction(question),
        _hint_scope(question),
        _hint_scaffold(question),
        _hint_gist(question),
    ]
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
