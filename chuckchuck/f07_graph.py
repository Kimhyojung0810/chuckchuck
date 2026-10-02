"""
[F-07] 장 단위 개념을 발표 전체 기준 '가중치 그래프' 로 묶는 모듈입니다.
ConceptDoc(+선택 SlideDoc) → ConceptGraph.

트리가 아니라 그래프인 이유: 개념은 부모가 하나라는 보장이 없습니다.
parent 간선만 따라가면 트리 뷰가 나오고, relates 간선이 나머지 연결을 담습니다.

발화 축(speech_weight)과 정합 판정(누락·모순)은 여기 없습니다.
F-07 은 Transcript 를 받지 않습니다. 그건 node.id 로 조인하는 뒤 단계 몫입니다.

LLM 응답 뒤에 **결정적 후처리**가 붙습니다 (2026-09-29, `_graph_items`): 이름이 같은 노드 합치기,
thesis 칸에 적힌 이름 풀기, 자료의 식·목록 항목 중 노드가 없는 것 더하기. 프롬프트는 건드리지 않았습니다 —
예시 id 를 바꾼 안은 A/B 에서 위계 일치율을 0.61 → 0.43 으로 떨어뜨렸고
(docs/review/2026-09-29_QA_근거검증/graph_ab.md), 예시 낱말만 중립으로 바꾼 안도 잣대를 고치고 표본을 늘린 2차 A/B 의
사전 판정 규칙을 못 넘었습니다 (graph_ab2.md, SYSTEM_PROMPT 아래 주석).

    from chuckchuck.f07_graph import build_graph
    graph = build_graph(concept_doc, context, slide_doc=slide_doc, llm="solar")
"""

from __future__ import annotations

import os
import re
import sys

from . import _claim_rules as R
from . import _deck_lines as DL
from . import _graph_items as GI
from . import _typed_graph as TG
from ._claim_rules import mention_score as R_mention
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
#: 2026-10-01: 3 → 4. 「주장 → 요인 묶음 → 요인 → 세부」(수익률격차: 다섯 가지 행동 요인 → 과잉 매매 → 회전율)가 3단에 막혀
#: 세부가 요인과 형제로 올라왔다 (6회 중 6회 깊이 3, 세부 자리 틀림 2~12개).
MAX_GRAPH_DEPTH = int(os.environ.get("CHUCKCHUCK_GRAPH_MAX_DEPTH", "4"))
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

#: 질문 꼴 — 주장 노드 이름이 이렇게 끝나면 답이 아니라 물음이다 (「…는 왜 … 못하는가」 · 「…일까?」).
_QUESTION_RE = re.compile(r"[?？]|(?:는가|은가|일까|ㄹ까|을까|할까|나요|까요)\s*$|^왜\s|\s왜\s")
#: 주장 이름으로 쓸 길이. 넘으면 첫 마디(쉼표·대시·마침표)에서 자른다.
CLAIM_LABEL_MAX = 40
#: thesis_claim 으로 받는 최대 길이 — 모델이 40자 규칙을 넘겨 쓰기 일쑤라(10-01 소개 덱 70자대) 버리지 않고 받는다.
CLAIM_ACCEPT_MAX = 80


def _shorten_claim(text: str) -> str:
    """
    긴 주장을 「주어 + 마지막 마디」 로 줄인다. 모델이 쓴 낱말만 쓴다 — 새로 짓지 않는다.
    (10-01 소개 덱: 「AI 발표 코칭 서비스는 …을 진단하고, 취약 개념 기반 Q&A로 … 능력을 향상시킨다」 100자 →
     「AI 발표 코칭 서비스는 취약 개념 기반 Q&A로 … 능력을 향상시킨다」)
    """
    if len(text) <= CLAIM_ACCEPT_MAX:
        return text
    m = re.match(r"^(.{2,30}?(?:은|는|이|가))\s", text)
    tail = re.split(r",\s", text)[-1].strip()
    if m and tail and tail != text:
        short = f"{m.group(1)} {tail}"
        if len(short) <= CLAIM_ACCEPT_MAX:
            return short
    return text


def _answer_part(text: str) -> str:
    """「질문: 답」 꼴이면 답만 (F-06 이 표지를 「…는 왜 …못하는가: 실력 문제가 아닌 행동 문제」 로 뽑는다)."""
    text = re.sub(r"\s+", " ", text or "").strip().strip('"「」')
    if ":" in text:
        left, right = text.split(":", 1)
        if _QUESTION_RE.search(left.strip()) and right.strip():
            return right.strip()
    return text

SYSTEM_PROMPT = """당신은 발표 구조 분석가다.
'개념 목록'을 받아, 발표 전체 기준의 개념 그래프와 구획을 만든다.

가장 중요한 것 — 노드는 슬라이드가 아니라 '개념'이다:
- 노드는 반드시 '개념 목록'의 항목에서 만든다.
- 슬라이드 제목("자사 분석", "경쟁사 분석", "기대 효과", "향후 계획" 같은 것)을 노드 label 로 쓰지 마라.
  그건 목차지 개념이 아니다. 그 장을 그래프에 담으려면 **그 장의 개념 목록 항목들**을 노드로 만든다
  (「향후 계획」 노드 하나가 아니라, 그 장에 나열된 항목 하나하나).
- 노드 개수가 슬라이드 개수와 같으면 슬라이드를 그대로 옮긴 것이므로 잘못 만든 것이다.
- 같은 개념이 여러 [S번호]에 나오면 하나의 노드로 합치고 slide_nos 에 그 번호를 모두 적어라.
- '개념명: 설명' 꼴이 아니라 **낱말만 있는 줄**(키워드)은, 그 낱말을 이미 다루는 개념 노드가 있으면
  거기 합치고 slide_nos 만 보탠다. 그런 노드가 없을 때만 따로 노드로 둔다.
  이때 summary 에 **다른 노드의 설명을 베껴 쓰지 마라** — 그 낱말이 나온 장의 개념 설명 중 그 낱말이
  들어간 것을 옮긴다. 두 노드의 summary 가 같으면 잘못 만든 것이다.

위계(parent) 규칙 — 노드마다 parent 칸에 적는다:
1. 노드마다 parent 에 **상위 개념의 id** 를 적는다. 최상위 개념만 parent 가 null 이다.
   하위 개념 하나에 상위 개념은 하나만.
2. **parent 가 null 인 노드는 많아야 4개다.** 5개 이상이면 위계를 안 만든 것이므로 잘못 만든 것이다.
   개념 하나하나마다 "이건 어느 개념을 설명하거나 이루는가" 를 묻고, 그 답을 parent 에 적어라.
3. 위계 깊이는 4단계를 넘기지 마라. 한 장에만 나오는 세부는 그 장을 대표하는 요소 밑으로 내려라
   (예: 어느 원인의 상세 장에만 나오는 지표는 그 원인 밑). 목록에 없는 묶음 이름을 새로 짓지 마라.
4. nodes 는 **위에서 아래 순서**로 적는다 — 주제 먼저, 그 자식들, 그 손자들. parent 에는 이미 적은 노드의 id 만 쓴다.

위계는 이 순서로 만든다 — 위에서 아래로:
A. 먼저 **발표의 핵심 주장 하나**를 노드로 세운다. thesis 에 그 id 를, thesis_claim 에 그 주장 한 문장을 적는다.
   주장 노드는 parent 가 null 이다.
   주장은 "이 발표는 결국 무엇을 말하려는가" 에 대한 **답 한 문장**이다. 분량이 가장 많은 개념이 아니다 —
   표지 부제·요약 장 제목·결론 장·공식 한 줄처럼 **글이 짧은 곳에 있는 경우가 많다.**
   - thesis_claim 과 주장 노드의 label 은 **짧은 평서문**(40자 이내)이다. 질문형 제목을 그대로 쓰지 않는다. 주제어 하나로 쓰지 않는다.
     (X) "도시는 왜 더워지는가"  (X) "도시 열섬"  (O) "도시 숲은 열섬을 식힌다"
   - 주장 노드에 한해 개념 목록의 설명 부분·「발표 흐름」의 장 제목·결론 장 문장에서 낱말을 가져와 label 을 쓸 수 있다.
     **자료에 적힌 주장 문장(부제·요약 장 제목·결론 문장)을 가능한 그대로 옮긴다. 바꿔 말하지 마라** — 낱말을 섞어
     새 문장을 지으면 뜻이 뒤집힌다 ("예측 능력은 격차의 원인이 아니다" → "예측을 잘해도 못 이긴다" 는 다른 주장이다).
     자료에 없는 주장을 지어내지 마라. summary 에는 그 주장이 적힌 자료 문장을 그대로 옮긴다.
B. 주제를 이루는 **요소**를 주제 밑에 단다. 주제가 "A = B × C × D" 같은 공식·정의면
   B·C·D 는 주제의 자식이다. 요소가 여러 장에 흩어져 나와도(설명 장·실천 장) 같은 부모다.
   **주제 바로 밑 자식은 3~6개다.** 7개 이상이면 요소와 세부를 섞은 것이다 — 목록에 있는
   개념 중 더 큰 것을 요소로 세우고, 나머지는 그 요소 밑(C)으로 내려라.
   이름이 겹치는 개념("집중" 과 "집중 루틴", "시각적 X" 와 "비시각적 X")은 한 요소 밑에 형제로 둔다.
C. 요소를 설명하는 세부(단계·종류·원인·수치·사례)는 그 요소 밑에 단다.
D. 뒤쪽 장의 **실천·해결책·저하·부족·원인** 개념은 새 최상위가 아니다. 그것이 개선하거나
   무너뜨리는 개념 밑에 단다. ("집중력 저하" 는 "집중력" 밑, "알림 끄기" 는 그것이 지키는 "집중력" 밑)
E. 주제와 관계없이 독립적으로 서는 큰 축이 정말 있을 때만 최상위를 더 둔다 (주제 포함 4개까지).
   배경 설명 장의 개념도 주제를 떠받치면 주제 밑이다. 자식이 하나도 없는 개념은 최상위가 아니다.

연결선(edges) 규칙 — 위계가 아닌 연결만:
5. edges 에는 kind="relates" 만 적는다. 근거·수단·대조·인과처럼 위계가 아닌 논리 연결이다.
   위계는 edges 가 아니라 parent 칸에 적는다.
   **같은 가지의 위아래(부모-자식·조상-자손, 주제 포함)를 edges 에 다시 적지 마라** — 위계로 이미 이었다. 버려진다.
   edges 는 **서로 다른 가지**의 개념을 잇는 자리다. 없으면 비워도 된다.

그 밖:
6. 자료에 없는 개념을 지어내지 마라. 주어진 개념 안에서만 묶어라.
7. id 는 영소문자·숫자·하이픈만 쓴다. 짧고 의미 있게. 유일해야 한다.
8. label 은 개념 이름만 짧게 (핵심 주장 노드는 A 를 따른다 — 짧은 평서문). summary 는 새 문장을 짓지 않는다 — 그 노드의 근거가 된 개념 목록 항목의
   '개념명: 설명' 에서 설명 부분을 그대로 옮겨 적는다(여러 항목을 합친 노드면 그중 하나). 목록에 없는
   일반어(정신적·구조적·체계·에너지·요소·신호 같은 말)로 풀어 쓰지 마라. 자료의 낱말만 쓴다.
9. sections 는 발표를 앞에서 뒤로 훑어 구획으로 나눈 것이다. 모든 장이 어딘가에 들어가야 한다.
   slide_role 은 cover, intro, body, conclusion, closing 중 하나만 쓴다.
10. 개념이 잘 설명됐는지 못 됐는지 판정하지 마라. 그건 다음 단계 일이다.
11. 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마:
{
  "thesis": "contrast",
  "thesis_claim": "자료 낱말로 쓴 핵심 주장 한 문장",
  "nodes": [
    { "id": "contrast", "label": "핵심 주장 한 문장", "slide_nos": [1, 4],
      "summary": "그 주장이 적힌 자료 문장", "importance": "core", "parent": null },
    { "id": "joint", "label": "요소 개념", "slide_nos": [5, 6],
      "summary": "한 줄 설명", "importance": "core", "parent": "contrast" },
    { "id": "encoder", "label": "세부 개념", "slide_nos": [6],
      "summary": "한 줄 설명", "importance": "support", "parent": "joint" },
    { "id": "baseline", "label": "다른 요소 개념", "slide_nos": [7],
      "summary": "한 줄 설명", "importance": "core", "parent": "contrast" }
  ],
  "edges": [
    { "from": "encoder", "to": "baseline", "kind": "relates" }
  ],
  "sections": [
    { "name": "본론 — 제안 방법", "slide_role": "body", "slide_nos": [6, 7, 8] }
  ]
}
"""

# 규칙 B·D 예시 낱말(「집중·집중 루틴·집중력 저하·알림 끄기」)은 focus 덱에서, 스키마 예시 id(contrast·joint·encoder·baseline)는
# IMU2CLIP 에서 왔다 — 처음 보는 PPT 에서 도는 프롬프트에 남은 덱 글이다. 그래도 **그대로 둔다** (09-30 실측, WP-C2 graph_ab2.md):
# - 앞선 A/B 두 번(표본 2개, 옛 「부모 일치율」)은 루트 이름 한 번 바뀜(「공강」↔「틈새」)에 덱 하나가 0 이 되는 잣대라 헛 하락이
#   섞였다. 노드를 짝지은 뒤 부모가 짝인지 세는 apa(labs/qa_bench/hier_stab.py)로 바꾸고, 판정 규칙을 돌리기 전에 커밋(23f512f)했다.
# - 10덱 × 표본 base 6·W 4 에서, 예시 낱말만 중립(「보온·보온 용품·보온성 저하·외풍 막기」)으로 바꾼 W 는 문 셋을 못 넘었다:
#   apa 0.643 → 0.570 (문턱 0.05), 자전거 덱 0.67 → 0.33 (한 덱 무너짐 0.25), 세부(깊이 3) 비율 0.48 → 0.41. 루트 바로 밑 자식이
#   6.4 → 8.3 개로 늘어 트리가 납작해졌다 (규칙 B 「3~6개」 지킨 표본 57% → 48%). 심은 주장·탐침은 그대로였다.
# - 예시 id 중립화·입력 울타리 갈래는 W 위에 하나씩 더한 것이라, W 가 떨어지면 돌리지 않기로 미리 정했다.
# - 남긴 대가는 작다: base 62표본에서 예시 낱말이 다른 덱 노드 이름으로 새지 않았다 (걸린 것은 자료에 있는 「알림 원칙」 같은 말).
#   예시 id 를 따라 쓴 노드는 `_assign_ids` 가 이름에서 만든 id 로, 예시 이름 자리표지는 `_drop_placeholders` 가 뺀다.
# 자료 속 지시문은 프롬프트 글을 안 바꾸고 막는다: 지시문을 옮긴 개념 항목은 목록에서 빼고(`_build_user_prompt`), F-06 이
# 이미 울타리 안에서 개념을 뽑는다.

#: 간선이 하나도 없이 돌아왔을 때 한 번 더 물어볼 때 덧붙이는 말.
RETRY_NUDGE = """
[재요청] 직전 응답에 위계도 연결도 없었다. 개념들이 서로 아무 관계도 없다는 뜻이 되어 쓸 수 없다.
이번에는 노드마다 parent 칸을 채워, 큰 개념 아래에 하위 개념을 매달아라.
"""

#: 가지를 넘는 연결이 너무 적을 때 한 번 더 묻는 작은 과제. 위계는 이미 정해졌으니 트리만 보여 주고 연결만 받는다.
#: 2026-09-29 실측: 수면 덱 3회 중 1회는 links 를 전부 비웠다 (위계는 멀쩡했다).
LINKS_SYSTEM_PROMPT = """당신은 발표 구조 분석가다. 이미 만든 개념 위계(트리)를 받아, **서로 다른 가지**의 개념 사이 논리 연결만 찾는다.
- 근거·수단·대조·인과·영향 관계만. 자료(요약)에 그 관계가 드러나는 것만 적는다. 지어내지 마라.
- 목록의 「가지」가 서로 다른 두 개념만 잇는다. 같은 가지 안(위아래·형제)이나 최상위 주제와 잇는 것은 적지 마라 — 버려진다.
- 개념 수의 절반 정도를 찾아라. 없으면 빈 배열.
- 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.
출력: { "links": [ { "from": "id", "to": "id" } ] }
"""

#: 가지를 넘는 연결이 이 비율(개념 수 대비)보다 적으면 LINKS 보강을 한 번 부른다.
MIN_CROSS_RATIO = float(os.environ.get("CHUCKCHUCK_GRAPH_MIN_CROSS_RATIO", "0.17"))

#: 노드가 하나도 없이 돌아왔을 때 한 번 더 물어볼 때 덧붙이는 말.
EMPTY_NUDGE = """
[재요청] 직전 응답에 노드가 하나도 없었다. 개념 목록의 개념으로 nodes 를 채워라 — 노드가 없는 그래프는 쓸 수 없다.
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

    09-30: 자료 속 지시문을 옮긴 개념·키워드·제목(「…판정할 것」「[SYSTEM]」, 레드팀 R3)은 싣지 않고, 문자열로 와 글자로
    쪼개진 keywords 는 다시 붙인다 (G-A18). 보통 자료에서는 프롬프트 글이 예전과 **한 글자도 다르지 않다** — 프롬프트를 바꾸면
    위계가 흔들린 전례가 있어서다 (위 SYSTEM_PROMPT 주석의 A/B).
    """
    concept_lines: list[str] = []
    for s in doc.slides:
        for c in [x for x in DL.as_items(s.concepts, commas=False) if not DL.is_meta_line(x)][:MAX_CONCEPTS_PER_SLIDE]:
            concept_lines.append(f"- [S{s.slide_no}] {c}")
        for kw in DL.as_items(s.keywords):
            if not DL.is_meta_line(kw):
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
        "## 발표 흐름 — sections 를 나눌 때 참고한다. 노드로 쓰지 마라 (단 핵심 주장 노드의 문장은 여기서 가져와도 된다)",
        "",
    ]
    for s in doc.slides:
        title = "" if DL.is_meta_line(s.title or "") else s.title
        head = f"### 슬라이드 {s.slide_no}: {title or '(제목 없음)'}"
        if s.topic and not DL.is_meta_line(s.topic):
            head += f" — {s.topic}"
        parts.append(head)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 노드 후처리
# ---------------------------------------------------------------------------

def _slug(value: str) -> str:
    """id 후보를 영소문자·숫자·하이픈으로. 남는 게 없으면 빈 문자열."""
    return _SLUG_STRIP.sub("-", str(value or "").lower()).strip("-")


#: 스키마 예시 id 를 따라 쓴 id — 「encoder-7」「joint2」 는 뜻이 없고 실행마다 다른 노드를 가리킨다.
_NUMBERED_ID_RE = re.compile(r"^(?:n|node|id|c|concept)?-?\d+$")


def _example_ids() -> set[str]:
    """지금 프롬프트 스키마 예시의 id 들 (프롬프트를 바꿔도 따라간다)."""
    return set(re.findall(r'"id":\s*"([a-z0-9-]+)"', SYSTEM_PROMPT))


def _example_labels() -> set[str]:
    """지금 프롬프트 스키마 예시의 label 들 — 모델이 「주제 개념」 을 노드 이름으로 그대로 옮기기도 한다 (09-29 수익률격차 1회)."""
    # 예전 예시 이름도 자리표지로 본다 — 10-01 주장 노드 개편으로 예시가 「핵심 주장 한 문장」 이 됐지만,
    # 「주제 개념」 을 옮긴 출력(09-29 실측)도 계속 걸러야 한다.
    return set(re.findall(r'"label":\s*"([^"]+)"', SYSTEM_PROMPT)) | {"주제 개념"}


def _positional_id(slug: str, examples: set[str]) -> bool:
    """뜻 없는 id 인가 — 비었거나, 순번(「n3」「12」)이거나, 스키마 예시 id(+번호)를 따라 썼다."""
    if not slug or _NUMBERED_ID_RE.match(slug):
        return True
    base = re.sub(r"-?\d+$", "", slug)
    return base in examples


def _assign_ids(raw_nodes: list[dict]) -> tuple[list[str], dict[str, str]]:
    """
    최종 id 목록과 '모델이 쓴 원래 id → 최종 id' 대응표를 만든다.

    edges 는 원래 id 로 적혀 있으므로, 대응표가 있어야 양끝을 다시 찾는다.

    09-30 레드팀 G-A21: 모델 id 가 뜻이 없으면(비었거나 순번 「n3」, 스키마 예시 id 「encoder-7」 를 따라 쓴 것) 이름에서 만든
    로마자 id(`_graph_items.slug_id`, 「독서 경험」 → dokseo-gyeongheom)로 바꾼다 — 같은 이름은 그래프를 다시 만들어도 같은 id 다.
    예전엔 한글 id 가 slug 에서 빈 문자열이 되어 「n1」「n2」 순번이 됐고, 예시 id 를 따라 쓴 「encoder-12」 는 실행마다 다른
    개념을 가리켜서 캐시가 바뀐 뒤 옛 질문의 node_id 가 엉뚱한 노드에 붙었다. 뜻 있는 영문 id(「reading-experience」)는 둔다.
    """
    final_ids: list[str] = []
    alias: dict[str, str] = {}
    used: set[str] = set()
    examples = _example_ids()

    for raw in raw_nodes:
        original = str(raw.get("id", "") or "")
        candidate = _slug(original)
        if _positional_id(candidate, examples):
            unique = GI.slug_id(str(raw.get("label", "") or original), used)
        else:
            unique, suffix = candidate, 2
            while unique in used:
                unique = f"{candidate}-{suffix}"
                suffix += 1
        used.add(unique)
        final_ids.append(unique)
        if original and original not in alias:
            alias[original] = unique

    return final_ids, alias


def _scoped_parents(raw_nodes: list[dict], final_ids: list[str]) -> list[dict]:
    """
    노드마다 적힌 parent 를 **최종 id** 간선으로. 같은 id 가 두 노드에 쓰였으면(겹친 id) 그 노드보다 **앞에 적힌 가장 가까운**
    노드를 가리킨다고 본다 — 프롬프트가 위에서 아래로, parent 에는 이미 적은 노드만 쓰라고 한다. 예전엔 대응표가 첫 노드만
    알아서, 둘째 노드의 자식들이 첫 노드 밑에 붙었다 (09-30 레드팀 G-A28). parent 칸에 id 대신 이름을 적었으면 이름으로 찾는다.
    """
    first: dict[str, str] = {}
    by_label: dict[str, str] = {}
    for raw, fid in zip(raw_nodes, final_ids):
        first.setdefault(str(raw.get("id", "") or ""), fid)
        by_label.setdefault(GI.label_keys(str(raw.get("label", "") or ""))[1], fid)
    latest: dict[str, str] = {}
    edges: list[dict] = []
    for raw, fid in zip(raw_nodes, final_ids):
        p = raw.get("parent")
        if p not in (None, "", "null"):
            key = str(p)
            target = latest.get(key) or first.get(key) or by_label.get(GI.label_keys(key)[1])
            if target and target != fid:
                edges.append({"from": target, "to": fid, "kind": "parent"})
        rid = str(raw.get("id", "") or "")
        if rid:
            latest[rid] = fid
    return edges


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


def _clamp_depth(parent_of: dict[str, str], node_ids: list[str], max_depth: int) -> list[ConceptEdge]:
    """
    너무 깊은 노드를 max_depth 에 맞게 상위로 끌어올린다 (제자리 수정). 끊은 원래 부모 → 노드 연결은 relates 로 돌려준다.

    원래 체인에서 depth == max_depth - 1 인 조상을 찾아 그 아래로 다시 매단다. 예전엔 원래 부모와의 관계를 그냥 버려서,
    강등된 루트의 손자·식 항의 부모 관계가 흔적 없이 사라졌다 (09-30 레드팀 G-A29) — 이제 가지를 넘는 연결로 남긴다.
    """
    cut: list[ConceptEdge] = []
    if max_depth < 1:
        return cut
    depths = {nid: _depth_of(nid, parent_of) for nid in node_ids}
    for nid in sorted(node_ids, key=lambda x: depths[x]):
        if depths[nid] <= max_depth:
            continue
        former = parent_of.get(nid)
        cursor = nid
        while cursor in parent_of and depths[cursor] > max_depth - 1:
            cursor = parent_of[cursor]
        if cursor == nid:
            parent_of.pop(nid, None)
        else:
            parent_of[nid] = cursor
        if former is not None and former != parent_of.get(nid):
            cut.append(ConceptEdge(from_id=former, to_id=nid, kind="relates"))
        depths = {n: _depth_of(n, parent_of) for n in node_ids}
    return cut


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
    only: set[str] | None = None,
) -> None:
    """
    weight 를 채운다. 그래프 안에서 **상대적** 이라 최상위 개념이 1.0 이 된다.

    우선순위 비교가 목적이므로 절대값보다 서열이 중요하다.
    """
    char_by, visual_by, total_char = _slide_signals(slide_doc)
    entries, titles = _concept_signals(doc)
    mentions = [_mention_count(n.label, entries) for n in nodes]
    # only 가 있으면 그 노드만 새로 매기고, 정규화(최고 언급·최고 점수)는 나머지 노드 기준이다 —
    # 후처리로 더한 항목 노드가 LLM 노드의 weight 서열을 흔들지 않게 (F-08 정렬이 weight 를 본다).
    base = [m for n, m in zip(nodes, mentions) if only is None or n.id not in only]
    top_mention = max(base, default=0)

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
    top = max((r for n, r in zip(nodes, raws) if only is None or n.id not in only), default=0.0)
    for node, raw in zip(nodes, raws):
        if only is None or node.id in only:
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


#: 발표의 **진행 칸**이지 개념이 아닌 이름 — 인사·질의응답·목차·발표자. 이름 전체가 이 꼴일 때만 (「인사 평가」 는 개념이다).
_STRUCTURAL_LABEL_RE = re.compile(
    r"^(?:감사(?:합니다|드립니다)?(?:\s*인사)?|(?:마무리|끝맺음|맺음)?\s*인사(?:말)?|질의\s*응답|질문과\s*답변|Q\s*&\s*A|QnA|"
    r"목차|차례|발표\s*순서|발표자(?:\s*소개)?|마무리|맺음말|끝|thank\s*you|thanks|agenda|contents|q\s*and\s*a)$", re.I)


#: 스키마 예시 이름 뒤의 번호 — 「세부 개념 3」「요소 개념 A」「주제 개념(2)」. 반복 루프가 예시 이름에 번호를 매겨 늘어놓는 꼴이다.
_INDEX_TAIL_RE = re.compile(r"\s*\(?\s*(?:\d+|[A-Za-z])\s*\)?$")


def _drop_placeholders(raw_nodes: list[dict], data: dict) -> tuple[list[dict], dict]:
    """
    개념이 아닌 노드를 뺀다 — 스키마 예시 이름(「주제 개념」「요소 개념」 …)을 그대로 옮긴 자리표지와, 발표 진행 칸(「감사 인사」
    「질의응답」「목차」)이다. 그 노드의 자식은 그 노드의 부모 밑으로, thesis 였으면 thesis 를 비운다 (루트 클램프가 서브트리로
    주제를 다시 고른다). 09-29 A/B: main 프롬프트가 수익률격차 덱에서 thesis 노드 이름을 「주제 개념」 으로 적었다. 09-30 WP-Q:
    도서관 덱 그래프에 루트 「감사 인사」 가 있었다 — 진행 칸이 질문 대상·루트 후보가 되면 안 된다.

    09-30 WP-C2 루프 점검: 예시 이름에 번호를 매긴 루프(「세부 개념 1」 … 「세부 개념 98」)는 이름이 다 달라 겹친 이름 합치기가
    못 접고, 노드 상한(80)까지 자리표지로 채웠다. 번호 붙은 예시 이름도 자리표지로 본다 (「1단계」 같은 진짜 번호 이름은 그대로).
    """
    examples = _example_labels()

    def dud(r: dict) -> bool:
        label = str(r.get("label", "") or "").strip()
        return (label in examples or _INDEX_TAIL_RE.sub("", label).strip() in examples
                or bool(_STRUCTURAL_LABEL_RE.match(label)))
    gone = {str(r.get("id", "") or ""): r.get("parent") for r in raw_nodes if dud(r)}
    if not gone:
        return raw_nodes, data
    sys.stderr.write(f"[f07] 개념이 아닌 노드(예시 이름·진행 칸) {len(gone)}개를 뺐다\n")

    def up(v):
        seen = set()
        while v not in (None, "", "null") and str(v) in gone and str(v) not in seen:
            seen.add(str(v))
            v = gone[str(v)]
        return v
    kept = [{**r, "parent": up(r.get("parent"))} for r in raw_nodes if not dud(r)]
    thesis = data.get("thesis")
    return kept, {**data, "thesis": None if str(thesis or "") in gone else thesis}


def _assemble(
    data: dict,
    doc: ConceptDoc,
    slide_doc: SlideDoc | None,
) -> tuple[list[ConceptNode], list[ConceptEdge], list[Section], str | None]:
    """
    raw JSON → 불변식을 만족하는 (nodes, edges, sections, thesis).

    thesis 는 모델이 고른 발표 주제 노드 id 다 (없거나 목록 밖이면 None).
    주제는 루트여야 하므로 모델이 부모를 붙였으면 떼고, 그 연결은 relates 로 남긴다.
    """
    raw_nodes = [n for n in (data.get("nodes") or []) if isinstance(n, dict)]
    raw_edges = [e for e in (data.get("edges") or []) if isinstance(e, dict)]
    raw_sections = [s for s in (data.get("sections") or []) if isinstance(s, dict)]
    # 자리표지·진행 칸을 **먼저** 뺀다 — 합치기가 노드 상한(80)에서 자르므로, 예시 이름에 번호를 매긴 루프가 상한을 먹으면
    # 루프 뒤의 진짜 노드가 잘렸다 (09-30 WP-C2 루프 점검).
    raw_nodes, data = _drop_placeholders(raw_nodes, data)
    # 이름이 같은 노드는 한 개념이다 — 먼저 합치고 나서 id 를 매긴다. 09-29 한 실행은 같은 이름이 98번
    # 되풀이된 113노드를 냈다 (반복 루프). 합친 노드를 가리키던 parent·edges·thesis 는 남은 노드로 옮긴다.
    raw_nodes, merged = GI.dedupe_raw_nodes(raw_nodes)
    if merged:
        def moved(v):
            return merged.get(str(v), v) if v not in (None, "", "null") else v
        for raw in raw_nodes:
            raw["parent"] = moved(raw.get("parent"))
            if isinstance(raw.get("links"), list):
                raw["links"] = [moved(x) for x in raw["links"]]
        raw_edges = [{**e, "from": moved(e.get("from")), "to": moved(e.get("to"))} for e in raw_edges]
        data = {**data, "thesis": moved(data.get("thesis"))}
    # 노드의 links 칸도 relates 로 받는다. 프롬프트는 더 요구하지 않는다 — 요구했더니 위계가 흔들렸다
    # (2026-09-29: form 덱 4회 중 2회 루트 12·2개). 가지를 넘는 연결은 _fill_links 가 따로 채운다.
    raw_edges += [
        {"from": raw.get("id"), "to": other, "kind": "relates"}
        for raw in raw_nodes
        for other in (raw.get("links") or [] if isinstance(raw.get("links"), list) else [])
        if raw.get("id") and other not in (None, "", "null")
    ]

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

    _natural_labels(nodes, slide_doc)
    node_ids = {n.id for n in nodes}
    # 위계는 노드의 parent 칸으로 받는다 (edges 로 받던 때는 Solar 가 절반 넘는 노드의 부모를
    # 빠뜨려 루트가 13~17개였다). 앞에 두어, edges 의 parent 와 겹치면 노드 칸이 이긴다.
    # 노드 칸은 겹친 id 를 자리로 가려 **최종 id** 로 풀고(`_scoped_parents`), edges·links 는 대응표로 푼다.
    def final(v):
        return alias.get(str(v)) if v not in (None, "", "null") else None
    edges_final = _scoped_parents(raw_nodes, final_ids) + [
        {"from": final(e.get("from")), "to": final(e.get("to")), "kind": e.get("kind", "parent")}
        for e in raw_edges if final(e.get("from")) and final(e.get("to"))]
    parent_of, relates = _normalize_edges(edges_final, {}, node_ids)
    raw_thesis = str(data.get("thesis", "") or "")
    thesis = alias.get(raw_thesis, raw_thesis) if raw_thesis else None
    if thesis not in node_ids:
        thesis = _thesis_by_label(raw_thesis, nodes, parent_of)
    if thesis is not None and thesis in parent_of:
        former = parent_of.pop(thesis)
        if not any({e.from_id, e.to_id} == {former, thesis} for e in relates):
            relates.append(ConceptEdge(from_id=former, to_id=thesis, kind="relates"))
    _break_parent_cycles(parent_of)
    _expand_title_nodes(nodes, parent_of, doc, thesis)
    relates += _clamp_depth(parent_of, [n.id for n in nodes], MAX_GRAPH_DEPTH)

    for node in nodes:
        node.parent_id = parent_of.get(node.id)
        node.depth = _depth_of(node.id, parent_of)

    # 주장 노드는 답 한 문장이어야 한다. thesis 가 없으면 루트가 하나일 때 그 루트.
    # ① 모델이 thesis_claim 을 따로 적었고 자료 낱말로 된 평서문이면 그걸 이름으로 ② 아니면 질문 꼴 이름을 요약의 답으로.
    roots = [n for n in nodes if n.parent_id is None]
    claim_node = next((n for n in nodes if n.id == thesis), None) or (roots[0] if len(roots) == 1 else None)
    if claim_node is not None:
        if not _apply_thesis_claim(claim_node, str(data.get("thesis_claim", "") or ""), doc):
            _claim_label(claim_node)

    _apply_weights(nodes, doc, slide_doc)

    # edges 를 parent_of 에서 되짚어 만들어, parent_id/depth 와 어긋날 수 없게 한다
    edges = [
        ConceptEdge(from_id=parent, to_id=child, kind="parent")
        for child, parent in parent_of.items()
    ]
    edges += _without_parent_pairs(
        [e for e in relates if e.from_id in node_ids and e.to_id in node_ids], parent_of
    )

    return nodes, edges, _to_sections(raw_sections, doc.total_slides), thesis


#: 이름 끝의 추세 낱말 — 「대출 권수 감소」 의 「감소」. 행동·해결 말(절감·개선·강화)은 뜻이 달라져서 넣지 않는다.
_TREND_TAIL_RE = re.compile(r"\s+(?:증가|감소|상승|하락|증대|늘어남|줄어듦)$")
_SPACE_RE = re.compile(r"\s+")


def _natural_labels(nodes: list[ConceptNode], slide_doc: SlideDoc | None) -> None:
    """
    자료에 없는 「변수 + 추세」 이름을 자료의 낱말로 — 「대출 권수 감소」 가 자료에 없고 「대출 권수」 는 있으면 이름을 「대출 권수」 로
    (제자리 수정, id 는 그대로). 09-30 WP-Q: 모델이 표의 추세를 이름에 붙여, 질문이 「대출 권수 감소도 독서 경험의 요소인데…」 가
    됐다 — 자료가 요소로 둔 것은 「대출 권수」 다. 변수가 낱말 둘 이상이고(「방문」 하나로는 뜻이 흐려진다), 같은 이름의 노드가
    없을 때만 바꾼다. 자료에 그 이름이 그대로 있으면(「1인 가구 증가」) 둔다.
    """
    if slide_doc is None:
        return
    deck = _SPACE_RE.sub("", " ".join(s.raw_text or "" for s in slide_doc.slides))
    taken = {GI.label_keys(n.label)[1] for n in nodes}
    for n in nodes:
        m = _TREND_TAIL_RE.search(n.label)
        if not m:
            continue
        base = n.label[: m.start()].strip()
        if len(R.content_tokens(base)) < 2 or _SPACE_RE.sub("", n.label) in deck or _SPACE_RE.sub("", base) not in deck:
            continue
        if GI.label_keys(base)[1] in taken:
            continue
        taken.add(GI.label_keys(base)[1])
        n.label = base


def _thesis_by_label(raw: str, nodes: list[ConceptNode], parent_of: dict[str, str]) -> str | None:
    """
    thesis 칸에 id 대신 **이름**이 적혔을 때 그 노드. 이름이 같거나, 두 쪽 낱말이 절반 이상 서로 덮는 노드 —
    같은 점수면 부모가 없는 노드, 앞에 적힌 노드(위에서 아래로 적는다).

    2026-09-29 A/B: main 프롬프트 응답 20회 중 11회가 thesis 에 「독서 경험」「한글 소설 확산」 같은 이름을 적었다.
    id 가 아니라서 버려졌고, 주제를 모르는 루트 클램프가 주제를 남길지 운에 맡겼다 (주제가 루트인 덱 3.5/9).
    """
    if not raw:
        return None
    scored = []
    for i, n in enumerate(nodes):
        sc = GI.head_match(raw, n.label)          # 머리말이 통해야 — 「혈당 부하」 가 「혈당 스파이크」 가 되지 않게 (09-30)
        if sc >= 0.5:
            scored.append((sc, n.id not in parent_of, -i, n.id))
    return max(scored)[3] if scored else None


# ---------------------------------------------------------------------------
# 루트 클램프 — 실측에서 28개 중 13개가 루트로 떠서 여전히 평평했다
# ---------------------------------------------------------------------------

def _attach_target(
    demoted: ConceptNode,
    kept: list[ConceptNode],
    relates: list[ConceptEdge],
    thesis: str | None = None,
) -> ConceptNode:
    """
    강등된 루트를 어느 남은 루트 밑에 붙일지 고른다.

    relates 이웃 > 슬라이드 겹침 > 발표 주제(thesis) > 최고 weight 순. 아무 관련 없는
    개념을 아무 데나 붙이는 것보다, 모델이 이미 적어 둔 연결을 근거로 쓴다.
    근거가 없으면 발표 주제 밑이 가장 덜 틀린다 — 발표의 모든 개념은 주제를 떠받친다.
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
        candidates = [k for k in kept if k.id == thesis] or kept
    return sorted(candidates, key=lambda k: (-k.weight, k.id))[0]


def _without_parent_pairs(relates: list[ConceptEdge], parent_of: dict[str, str]) -> list[ConceptEdge]:
    """
    같은 가지의 위아래(부모-자식·조상-자손, 방향 무관)를 이은 relates 를 뺀다.

    2026-09-29: 노드의 parent 칸으로 위계를 받게 바꾼 뒤, 수면 덱에서 relates 15개가 전부 부모-자식을
    되풀이했다 (가지를 넘는 연결 0). 남겨 두면 개수만 부풀고, 인접 강등(F-08)·연결 누락(F-11)이
    이미 아는 부모-자식 관계를 '다른 연결' 로 잘못 센다.
    """
    def ancestors(node_id: str) -> set[str]:
        out, cur = set(), parent_of.get(node_id)
        while cur is not None and cur not in out:
            out.add(cur)
            cur = parent_of.get(cur)
        return out

    # 부모-자식뿐 아니라 조상-자손(같은 가지 위아래)도 뺀다 — 09-29 실측: 연결 보강 뒤 19개 중 다수가
    # 주제(루트)에서 손자로 가는 선이었다. 주제는 모든 개념의 조상이라 그 선은 새 정보가 아니다.
    return [e for e in relates
            if e.from_id not in ancestors(e.to_id) and e.to_id not in ancestors(e.from_id)]


def _dedupe_relates(edges: list[ConceptEdge]) -> list[ConceptEdge]:
    """같은 두 노드를 잇는 relates 는 하나만 (방향 무관). parent 간선은 그대로."""
    seen: set[frozenset] = set()
    out: list[ConceptEdge] = []
    for e in edges:
        if e.kind == "relates":
            key = frozenset((e.from_id, e.to_id))
            if key in seen or e.from_id == e.to_id:
                continue
            seen.add(key)
        out.append(e)
    return out


def _expand_title_nodes(nodes: list[ConceptNode], parent_of: dict[str, str], doc: ConceptDoc, thesis: str | None) -> None:
    """
    장 제목을 그대로 이름으로 단 노드(「실행 체크리스트」「오해와 사실」)가 자식 없이 끝났으면, 그 장의 개념 목록 항목을 자식으로 단다 (제자리).

    프롬프트로 막아도 6회 중 6회 2~3개씩 나왔다 (2026-10-01 수익률격차). 지우면 그 장이 그래프에서 통째로 빠지고,
    그대로 두면 「실행 체크리스트란?」 같은 목차 질문이 된다. 그 장 항목(「종목 수 하한: 8종목 이상」 …)은 자료에 적힌 개념이라
    지어내는 것이 없고, 1-2 대조에서 「발표에만 나온 개념」 으로 떨어지던 것들이다. 이름이 이미 그래프에 있는 항목은 건너뛴다.
    """
    norm = lambda t: re.sub(r"[\s·:\-—]+", "", (t or "").lower())
    with_children = set(parent_of.values())
    used = {n.id for n in nodes}
    have = [set(w for w in label_tokens(n.label) if len(w) >= 2) for n in nodes]
    added: list[ConceptNode] = []
    for node in list(nodes):
        if node.id == thesis or node.id in with_children:
            continue
        for slide in (s for s in doc.slides if s.title and norm(s.title) == norm(node.label)):
            for item in slide.concepts[:MAX_CONCEPTS_PER_SLIDE]:
                name, _, desc = str(item).partition(":")
                name, desc = name.strip(), desc.strip()
                toks = set(w for w in label_tokens(name) if len(w) >= 2)
                if not name or norm(name) == norm(node.label) or not toks:
                    continue
                if any(len(toks & t) >= max(1, 0.6 * len(toks)) for t in have):
                    continue
                cid, k = _slug(name) or "item", 2
                base = cid
                while cid in used:
                    cid, k = f"{base}-{k}", k + 1
                used.add(cid)
                have.append(toks)
                added.append(ConceptNode(id=cid, label=name, slide_nos=[slide.slide_no], summary=desc,
                                         importance=slide.importance if slide.importance in _IMPORTANCE_SCORE else "support"))
                parent_of[cid] = node.id
    nodes.extend(added)


def _claim_label(node: ConceptNode) -> None:
    """
    핵심 주장 노드의 이름이 질문 꼴이면, 그 답이 적힌 요약으로 이름을 바꾼다 (제자리).

    2026-10-01 수익률격차: F-06 이 표지를 「개인 투자자는 왜 시장을 이기지 못하는가: 실력 문제가 아닌 행동 문제」 로
    뽑아 노드 이름이 질문, 주장은 요약에만 남았다 — 질문 코칭이 주장을 방어하게 하는 대신 제목을 되물었다.
    요약도 질문이거나 비었으면 손대지 않는다 (지어낼 재료가 없다). 원래 질문은 요약 앞에 남긴다.
    """
    label, summary = (node.label or "").strip(), (node.summary or "").strip()
    answer = _answer_part(label)
    if answer != label and not _QUESTION_RE.search(answer):      # 이름 자체가 「질문: 답」 — 답만 남긴다
        node.summary = " — ".join(x for x in (label, summary) if x)
        node.label = answer
        return
    claim = _answer_part(summary)                              # 요약도 「질문: 답」 이면 답만 본다
    if not _QUESTION_RE.search(label) or not claim or _QUESTION_RE.search(claim):
        return
    if len(claim) > CLAIM_LABEL_MAX:
        cut = re.split(r"\s[—–-]\s|[.,;·]\s", claim)[0].strip()
        claim = cut if 4 <= len(cut) <= CLAIM_LABEL_MAX else claim[:CLAIM_LABEL_MAX].rstrip()
    node.summary = f"{label} — {summary}"
    node.label = claim


#: thesis_claim 낱말 중 자료(개념 목록·장 제목·주제)에 있어야 하는 비율. 아래면 지어낸 주장으로 보고 버린다.
CLAIM_GROUNDED_MIN = 0.6


def _apply_thesis_claim(node: ConceptNode, claim: str, doc: ConceptDoc) -> bool:
    """
    출력의 thesis_claim 을 주장 노드 이름으로 쓴다. 받으면 True.

    노드 이름 규칙만으로는 3회 중 1~2회가 주제어(「수면의 질」 · 「AI 발표 코칭 서비스」)로 남았다 (2026-10-01) —
    parent 칸처럼 칸을 따로 받는다. 질문 꼴·너무 긺·자료 낱말이 모자람(지어낸 주장)이면 받지 않는다.
    """
    claim = _shorten_claim(_answer_part(claim))
    if not claim or len(claim) > CLAIM_ACCEPT_MAX or _QUESTION_RE.search(claim):
        return False
    words = [w for w in label_tokens(claim) if len(w) >= 2]      # 떨어진 조사·숫자 한 글자는 세지 않는다
    if not words:
        return False
    deck_text = " ".join(
        " ".join([s.title or "", s.topic or "", *s.concepts, *s.keywords]) for s in doc.slides
    )
    deck_words = norm_tokens(deck_text)
    # 조사가 붙은 꼴(「행동에서」 · 「행동의」)도 같은 낱말로 본다 — 앞 두 글자 이상이 같으면 자료 낱말이다
    def stem_hit(w: str) -> bool:
        return any(len(d) >= 2 and (w.startswith(d[:2]) and (len(w) <= 2 or w[:2] == d[:2])) for d in deck_words)
    grounded = sum(1 for w in words if stem_hit(w))
    if grounded / len(words) < CLAIM_GROUNDED_MIN:
        return False
    if node.label.strip() != claim:
        node.summary = " — ".join(x for x in (node.label.strip(), (node.summary or "").strip()) if x)
        node.label = claim
    return True


def _subtree_reach(
    nodes: list[ConceptNode],
    parent_of: dict[str, str],
) -> tuple[dict[str, int], dict[str, int]]:
    """노드마다 (서브트리가 덮는 장 수, 서브트리 개념 수). 자기 자신을 포함한다."""
    slides = {n.id: set(n.slide_nos) for n in nodes}
    size = {n.id: 1 for n in nodes}
    for node in nodes:
        seen = {node.id}
        up = parent_of.get(node.id)
        while up is not None and up not in seen:     # 순환은 이미 끊겼지만 방어
            seen.add(up)
            if up in slides:
                slides[up] |= set(node.slide_nos)
                size[up] += 1
            up = parent_of.get(up)
    return {k: len(v) for k, v in slides.items()}, size


def _clamp_roots(
    nodes: list[ConceptNode],
    edges: list[ConceptEdge],
    doc: ConceptDoc,
    slide_doc: SlideDoc | None,
    thesis: str | None = None,
) -> list[ConceptEdge]:
    """
    루트가 MAX_ROOTS 를 넘으면 **서브트리가 큰** 루트만 남기고 나머지를 그 밑에 붙인다.

    모델이 고른 발표 주제(thesis)는 무조건 남는다. 나머지는 모델이 그린 위계로 고른다 —
    weight 가 아니라 서브트리가 덮는 장 수 →
    서브트리 개념 수 → weight 순. weight 는 글자·그림 비중이라, 예전엔 짧은 표지·공식
    장에 앉은 발표 주제가 설명이 긴 장의 세부 개념에 밀려 **자기 자식 밑으로** 강등됐다
    (2026-09-28 수면발표: 「수면의 질」이 자식 8개를 거느리고도 「수면 주기」 밑으로 갔다.
    docs/review/2026-09-28_QA_지엽성_원인분석.md §1-5).

    nodes 의 parent_id/depth/weight 를 제자리 갱신하고, 새 edges 를 돌려준다.
    상한 이하면 아무것도 바꾸지 않는다.
    """
    if MAX_ROOTS < 1:
        return edges
    roots = [n for n in nodes if n.parent_id is None]
    if len(roots) <= MAX_ROOTS:
        return edges

    relates = [e for e in edges if e.kind == "relates"]
    parent_of = {e.to_id: e.from_id for e in edges if e.kind == "parent"}
    span, size = _subtree_reach(nodes, parent_of)
    # 자식이 없는 루트는 축이 아니다 — 모델이 부모를 빠뜨린 개념이라 먼저 붙인다.
    ranked = sorted(
        roots,
        key=lambda n: (n.id != thesis, size[n.id] == 1, -span[n.id], -size[n.id], -n.weight, n.id),
    )
    kept, demoted = ranked[:MAX_ROOTS], ranked[MAX_ROOTS:]

    for node in demoted:
        parent_of[node.id] = _attach_target(node, kept, relates, thesis).id

    node_ids = [n.id for n in nodes]
    relates = relates + _clamp_depth(parent_of, node_ids, MAX_GRAPH_DEPTH)
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
    return new_edges + _dedupe_relates(_without_parent_pairs(relates, parent_of))


def _branch_of(node: ConceptNode, by: dict[str, ConceptNode]) -> str:
    """루트 바로 밑 조상(가지). 루트 자신은 '주제'."""
    cur, seen = node, set()
    while cur.parent_id in by and by[cur.parent_id].parent_id is not None and cur.id not in seen:
        seen.add(cur.id)
        cur = by[cur.parent_id]
    return "주제" if node.parent_id is None else cur.label


def _links_prompt(nodes: list[ConceptNode]) -> str:
    by = {n.id: n for n in nodes}
    lines = ["[TASK] concept-links", "",
             "## 개념 위계 — (id) 이름 [장] · 가지 · 부모 · 요약",
             "가지가 **다른** 두 개념만 이어라. 가지가 '주제' 인 개념(최상위)은 잇지 마라.", ""]
    for n in nodes:
        up = by[n.parent_id].label if n.parent_id in by else "없음"
        lines.append(f"- ({n.id}) {n.label} [S{','.join(map(str, n.slide_nos))}] · 가지={_branch_of(n, by)} · 부모={up} · {n.summary}")
    return "\n".join(lines)


def _fill_links(engine: LLMProvider, nodes: list[ConceptNode], edges: list[ConceptEdge],
                degraded: list[str] | None = None) -> list[ConceptEdge]:
    """
    가지를 넘는 연결이 MIN_CROSS_RATIO 보다 적으면 트리만 보여 주고 연결을 한 번 더 묻는다.
    실패하거나 JSON 이 깨지면 그래프는 그대로 낸다 — 연결은 보조 정보라 그래프를 실패시킬 이유가 없다.
    다만 **조용히 삼키지 않는다** (09-30 레드팀 G-A30): stderr 에 까닭을 남기고 `degraded` 에 「links」 를 적는다 —
    계약에 칸이 있으면 그래프에 실린다 (`build_graph`).
    """
    if not nodes or MIN_CROSS_RATIO <= 0:
        return edges
    parent_of = {n.id: n.parent_id for n in nodes if n.parent_id}
    # 클램프로 위계가 바뀌었을 수 있다 — 지금 트리 기준으로 같은 가지 선을 한 번 더 걸러 센다
    edges = [e for e in edges if e.kind != "relates"] + _without_parent_pairs(
        [e for e in edges if e.kind == "relates"], parent_of)
    relates = [e for e in edges if e.kind == "relates"]
    if len(relates) >= MIN_CROSS_RATIO * len(nodes):
        return edges
    try:
        raw = engine.complete(system=LINKS_SYSTEM_PROMPT, user=_links_prompt(nodes),
                              temperature=0.2, max_tokens=MAX_TOKENS // 2, json_mode=True)
        data = extract_json_object(raw)
    except Exception as e:  # noqa: BLE001 — 보조 호출이 깨져도 그래프는 낸다, 깨졌다고 적고
        sys.stderr.write(f"[f07] 연결 보강 실패 — 가지를 넘는 연결 없이 그래프를 낸다: {type(e).__name__}: {str(e)[:160]}\n")
        if degraded is not None:
            degraded.append("links")
        return edges
    ids = {n.id for n in nodes}
    seen = {frozenset((e.from_id, e.to_id)) for e in relates}
    added: list[ConceptEdge] = []
    for link in data.get("links") or []:
        if not isinstance(link, dict):
            continue
        a, b = str(link.get("from", "") or ""), str(link.get("to", "") or "")
        pair = frozenset((a, b))
        if a == b or a not in ids or b not in ids or pair in seen:
            continue
        seen.add(pair)
        added.append(ConceptEdge(from_id=a, to_id=b, kind="relates"))
    return edges + _without_parent_pairs(added, parent_of)


# ---------------------------------------------------------------------------
# 식·목록 항목 메우기 — LLM 이 빠뜨린 요소 개념을 자료 구조로 더한다
# ---------------------------------------------------------------------------

def _root_of(nodes: list[ConceptNode], thesis: str | None) -> ConceptNode | None:
    """근거가 없을 때 매달 곳 — 발표 주제, 없으면 서브트리가 가장 큰 루트."""
    by = {n.id: n for n in nodes}
    if thesis in by and by[thesis].parent_id is None:
        return by[thesis]
    parent_of = {n.id: n.parent_id for n in nodes if n.parent_id}
    _, size = _subtree_reach(nodes, parent_of)
    roots = [n for n in nodes if n.parent_id is None]
    return min(roots, key=lambda n: (-size[n.id], -n.weight, n.id)) if roots else None


def _head_node(head: str, slide_no: int, nodes: list[ConceptNode]) -> ConceptNode | None:
    """
    식 좌변·목록 제목이 가리키는 노드 — 두 쪽 낱말이 절반 이상 서로 덮고 **머리말이 통해야** 한다. 같은 점수면 그 장·얕은 노드.
    09-30 held-out 감사 M-05: 건강 덱 한 실행에서 좌변 「혈당 부하」 가 낱말 「혈당」 하나로 「혈당 스파이크」 에 붙어 좌변 노드가
    안 생겼고, 비교(1장)·식(3장)이 서로 다른 노드로 풀려 긴장 T1 을 놓쳤다 (`_graph_items.head_match`).
    """
    scored = [(GI.head_match(head, n.label), n) for n in nodes]
    scored = [(sc, n) for sc, n in scored if sc >= 0.5]
    if not scored:
        return None
    return max(scored, key=lambda x: (x[0], slide_no in x[1].slide_nos, -x[1].depth, x[1].weight))[1]


def _head_in(label: str, text: str) -> bool:
    """이름의 머리말이 글에 나오는가 — 한 글자 머리(「…의 질」)는 글자 그대로 찾는다 (토큰 대조는 두 글자부터)."""
    head = R.head_token(label)
    return bool(head) and (head in text if len(head) < R.TOKEN_MIN else R.mentioned(head, text, min_score=1.0))


def _context_node(group: GI.ItemGroup, nodes: list[ConceptNode]) -> ConceptNode | None:
    """
    제목이 노드를 못 가리킬 때 — 그 장 노드 중 이름이 제목·소개 문장에 가장 많이 나온 것 (낱말 절반 이상,
    같으면 긴 이름·얕은 쪽). 09-29 건강 덱: 「스파이크가 만드는 세 가지 문제」 → 「혈당 스파이크」.
    09-29 수면 덱: 「자다가 깨는 대표적인 원인」 은 어느 노드도 아니지만 소개 줄 「수면의 연속성을 끊는 요인은…」 이
    「수면 연속성」 을 부른다. 그 밑이 발표 주제 밑보다 덜 틀린다.
    """
    # 이름의 머리말이 제목·소개 글에 나와야 한다 — 수식어 낱말 하나(「혈당」)로 「혈당 지수」 를 목록의 부모로 고르지 않게
    scored = [(R_mention(n.label, group.context), n) for n in nodes if group.slide_no in n.slide_nos
              and _head_in(n.label, group.context)]
    scored = [(sc, n) for sc, n in scored if sc >= 0.5]
    if not scored:
        return None
    return max(scored, key=lambda x: (x[0], len(label_tokens(x[1].label)), -x[1].depth, x[1].weight))[1]


def _item_slides(item: str, slide_no: int, lines_by: dict[int, list[str]]) -> list[int]:
    """항목 이름이 줄에 통째로 나온 장들 (근거 장은 늘 포함) — weight 의 걸친 장 수가 여기서 온다."""
    toks = label_tokens(item)
    found = {no for no, lines in lines_by.items() if toks and any(contains_tokens(norm_tokens(x), toks) for x in lines)}
    return sorted(found | {slide_no})


def _add_items(
    nodes: list[ConceptNode],
    edges: list[ConceptEdge],
    doc: ConceptDoc,
    slide_doc: SlideDoc | None,
    thesis: str | None,
) -> list[ConceptEdge]:
    """
    자료의 식(「A = B × C × D」)·목록(「세 가지 문제」 + 항목 줄)에서 **노드가 없는 항목**을 노드로 더한다.

    부모: 식이면 좌변 노드(없으면 좌변도 노드로 더해 주제 밑에), 목록이면 이미 노드인 항목들의 공통 부모 →
    제목이 가리키는 노드 → 발표 주제 순. id 는 이름의 로마자 slug, weight 는 같은 배합(정규화는 LLM 노드 기준).
    묶음 하나를 통째로 못 넣으면(상한 MAX_ADDED) 그 묶음은 건너뛴다 — 식의 항 일부만 있으면 compose 가 반쪽이 된다.
    nodes 는 제자리에 늘리고 새 edges 를 돌려준다. slide_doc 이 없으면 아무것도 안 한다.
    """
    if slide_doc is None or GI.MAX_ADDED <= 0 or not nodes:
        return edges
    lines_by = {s.slide_no: GI.deck_lines(s.raw_text) for s in slide_doc.slides}
    groups = GI.item_groups([(s.slide_no, s.raw_text) for s in slide_doc.slides])
    by_slide_imp = {s.slide_no: s.importance for s in doc.slides}
    used = {n.id for n in nodes}
    parent_of = {n.id: n.parent_id for n in nodes if n.parent_id}
    added: list[ConceptNode] = []

    def make(label: str, group: GI.ItemGroup, parent: str | None) -> ConceptNode:
        slides = _item_slides(label, group.slide_no, lines_by)
        node = ConceptNode(id=GI.slug_id(label, used), label=label, slide_nos=slides, summary=group.line,
                           importance=_inherit_importance(slides, by_slide_imp, "support"))
        used.add(node.id)
        if parent:
            parent_of[node.id] = parent
        return node

    for g in groups:
        labels = [n.label for n in nodes + added]
        missing = [it for it in g.items if GI.present_index(it, labels) is None]
        pool = nodes + added
        # 식의 좌변은 항이 다 있어도 없으면 더한다 — 비교(「X보다 중요한 Y」)와 식(「Y = … × X」)이 같은 노드 Y 로 만나야
        # F-26 이 긴장을 적는다. 09-30 held-out 감사: 건강 덱 한 실행은 항(혈당 지수·탄수화물 양)만 있고 좌변 「혈당 부하」 가 없었다
        head_missing = g.kind == "formula" and _head_node(g.head, g.slide_no, pool) is None \
            and GI.present_index(g.head, labels) is None
        if not missing and not head_missing:
            continue
        parent = None
        if g.kind == "list":
            have = [pool[i] for it in g.items if (i := GI.present_index(it, labels)) is not None]
            ups = {n.parent_id for n in have}
            if len(ups) == 1 and None not in ups:
                parent = next(iter(ups))
        if parent is None:
            got = _head_node(g.head, g.slide_no, pool) or (_context_node(g, pool) if g.kind == "list" else None)
            if got is None and g.kind == "formula" and (k := GI.present_index(g.head, labels)) is not None:
                got = pool[k]                     # 좌변이 이미 노드면 그 밑에 — 같은 좌변을 또 더하지 않는다
            parent = got.id if got is not None else None
        new_head = None
        if parent is None and g.kind == "formula":
            root = _root_of(nodes, thesis)
            new_head = (g.head, root.id if root else None)
        if len(added) + len(missing) + (new_head is not None) > GI.MAX_ADDED:
            continue
        if new_head is not None:
            head = make(new_head[0], g, new_head[1])
            added.append(head)
            parent = head.id
        if parent is None:
            root = _root_of(nodes, thesis)
            parent = root.id if root else None
        for it in missing:
            added.append(make(it, g, parent))

    if not added:
        return edges
    nodes.extend(added)
    ids = [n.id for n in nodes]
    cut = _clamp_depth(parent_of, ids, MAX_GRAPH_DEPTH)
    for node in nodes:
        node.parent_id = parent_of.get(node.id)
        node.depth = _depth_of(node.id, parent_of)
    _apply_weights(nodes, doc, slide_doc, only={n.id for n in added})
    # 더한 항목이 깊이 상한에 걸려 식 좌변 밑에 못 붙으면 할아버지 밑으로 가고, 좌변과의 관계는 relates 로 남는다
    kept = [e for e in edges if e.kind != "parent" or e.to_id not in parent_of or parent_of[e.to_id] == e.from_id]
    return _dedupe_relates(kept + [ConceptEdge(from_id=parent_of[n.id], to_id=n.id, kind="parent") for n in added
                                   if n.id in parent_of] + _without_parent_pairs(cut, parent_of))


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
) -> tuple[list[ConceptNode], list[ConceptEdge], list[Section], str | None]:
    raw = engine.complete(
        system=SYSTEM_PROMPT + extra_system,
        user=_build_user_prompt(doc, ctx),
        temperature=0.2,
        max_tokens=MAX_TOKENS,
        json_mode=True
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

    if TG.is_typed(doc):
        return _build_typed(engine, doc, ctx, slide_doc)

    try:
        nodes, edges, sections, thesis = _call(engine, doc, ctx, slide_doc)
    except GraphError:
        # 파싱 실패는 대부분 그 실행의 출력 문제다. 한 번은 다시 묻고, 또 깨지면 실패로 둔다
        nodes, edges, sections, thesis = _call(
            engine, doc, ctx, slide_doc, extra_system=JSON_RETRY_NUDGE
        )
    if not nodes:
        # 노드 0개는 그래프가 아니다 — 한 번 더 묻고, 또 비면 실패로 올린다 (09-30 레드팀 G-A7: 예전엔 빈 그래프를 성공으로
        # 돌려줘서 화면이 「개념 없음」 을 분석 결과처럼 보였다. 브리지는 예외를 오류 응답으로 낸다 — CLAUDE.md 「실패는 실패로」)
        try:
            nodes, edges, sections, thesis = _call(engine, doc, ctx, slide_doc, extra_system=EMPTY_NUDGE)
        except GraphError:
            nodes = []
        if not nodes:
            raise GraphError("F-07 이 개념 노드를 하나도 만들지 못했습니다 — 개념 그래프를 만들 수 없습니다.")
    if _is_degenerate(nodes, edges):
        try:
            retry = _call(engine, doc, ctx, slide_doc, extra_system=RETRY_NUDGE)
        except GraphError:
            retry = None                      # 재시도가 깨지면 1차 결과를 쓴다
        if retry and not _is_degenerate(retry[0], retry[1]):
            nodes, edges, sections, thesis = retry

    degraded: list[str] = []
    edges = _clamp_roots(nodes, edges, doc, slide_doc, thesis)
    edges = _fill_links(engine, nodes, edges, degraded)
    # 식·목록 항목 메우기는 연결 보강 **뒤**다 — 앞에 두면 노드 수가 늘어 보강 호출 여부(가지 간 연결 비율)가 바뀐다.
    # 더한 항목은 위계(부모 간선)로만 잇는다. 가지를 넘는 연결은 F-26 주장(compose)이 맡는다.
    edges = _add_items(nodes, edges, doc, slide_doc, thesis)

    graph = ConceptGraph(
        file_name=doc.file_name,
        total_slides=doc.total_slides,
        nodes=nodes,
        edges=edges,
        sections=sections,
        model=engine.name,
    )
    # 계약(contracts.ConceptGraph)에 칸이 생기면 싣는다 — 칸이 없는 지금도 그대로 돈다 (09-30 G-A17·G-A30).
    # thesis: 모델이 고른 발표 주제 노드 (F-08 theme 자리가 「가장 무거운 루트」 를 짐작하지 않게). 루트일 때만.
    _set_contract_field(graph, "thesis", thesis if thesis in {n.id for n in nodes if n.parent_id is None} else None)
    _set_contract_field(graph, "degraded", degraded)
    return graph


def _build_typed(engine: LLMProvider, doc: ConceptDoc, ctx: Context, slide_doc: SlideDoc | None) -> ConceptGraph:
    """
    종류가 있는 F-06 (2026-10-01~) 의 길 — 노드는 자료에서 코드가, 뼈대 판단만 LLM 이 (`_typed_graph`).
    루트는 늘 핵심 주장 하나라 루트 클램프가 필요 없고, 가지 간 연결은 자료가 밝힌 것만 받아 개수 보강(`_fill_links`)을 부르지 않는다.
    뼈대 판단이 끝내 깨지면 모든 장을 핵심 주장 밑에 두고 degraded 에 「skeleton」 을 적는다.
    """
    degraded: list[str] = []
    data = TG.call_structure(engine, doc, ctx, MAX_TOKENS)
    if data is None:
        degraded.append("skeleton")
    # 이름이 다른 같은 개념(임베딩 후보 → LLM 확인) — 실패해도 빈 목록, 그래프는 그대로
    same = TG.call_same(engine, doc)
    data = {**(data or {}), "same_keys": same}
    nodes, edges, sections, thesis = TG.assemble(doc, data, slide_doc)
    cov = TG.coverage(doc, nodes, same)
    if cov["lost"]:
        sys.stderr.write(f"[f07] 그래프에 없는 F-06 항목 {cov['lost']}/{cov['total']}: {cov['missing']}\n")
    graph = ConceptGraph(file_name=doc.file_name, total_slides=doc.total_slides, nodes=nodes, edges=edges,
                         sections=sections, model=engine.name)
    _set_contract_field(graph, "thesis", thesis)
    _set_contract_field(graph, "degraded", degraded)
    return graph


def _set_contract_field(obj, name: str, value) -> None:
    """계약 dataclass 에 그 칸이 있을 때만 채운다 — 계약은 WP-J 몫이라, 칸이 생기기 전·후 모두 이 코드가 돈다."""
    if name in getattr(type(obj), "__dataclass_fields__", {}):
        setattr(obj, name, value)
