"""
[F-09] 예상 질문에 대한 답변을 판정하는 모듈입니다.
Question + 답변(+선택 history·ConceptGraph·AlignmentDoc) → QaJudgement.

F-08 과 짝입니다. F-08 이 "무엇을 물을지" 를 결정적으로 정했다면,
여기서는 "그 답이 개념을 실제로 방어했는가" 를 4-class 로 판정합니다.

    from chuckchuck.f09_judge import judge_answer
    judgement = judge_answer(question, "제 답변은...", history=turns, llm="solar")

판정 자체는 LLM 이 하지만 **계약은 코드가 지킵니다** — verdict 는 enum 안,
score 는 0~100, node_id 는 질문에서 승계, react·summary_sentence 는 항상 채워집니다.
프론트가 이 넷으로 말풍선을 그리기 때문에 비어 있으면 화면이 빕니다.
"""

from __future__ import annotations

import os
import re

from ._evidence import anchor_slides, clean_slide_text, mask_gist, neighbor_lines
from ._match import norm_tokens
from ._speech import to_haeyo
from ._json_text import extract_json_object
from .contracts import (
    ConceptMemory,
    MemoryDoc,
    QA_COACH_STAGES,
    QA_EXPLAIN_MAX,
    QA_MAX_ROUNDS,
    QA_TEXT_MAX,
    QA_VERDICT_FALLBACK,
    QA_VERDICT_SCORES,
    QA_VERDICTS,
    AlignmentDoc,
    ConceptGraph,
    Context,
    JudgeError,
    QaJudgement,
    QaTurn,
    Question,
    SlideDoc,
    Transcript,
    qa_mastered,
    qa_probe_tier,
)
from .f08_questions import build_hint_ladder
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm

MAX_TOKENS = int(os.environ.get("CHUCKCHUCK_JUDGE_MAX_TOKENS", "2048"))

#: history 를 몇 턴까지 프롬프트에 실을지. 앞 턴은 판정에 거의 기여하지 않는데
#: 토큰만 먹는다 — 최근 대화만 맥락으로 준다.
HISTORY_TURNS = int(os.environ.get("CHUCKCHUCK_JUDGE_HISTORY_TURNS", "6"))

#: 같은 질문에 대해 앞서 낸 답변을 몇 개까지 판정 대상에 실을지.
#: 되묻기는 턴 상한이 없어 무한정 쌓일 수 있는데, 프롬프트가 길어지면 정작
#: 마지막 답변이 묻힌다. 최근 것부터 이만큼만 싣는다.
PRIOR_ANSWERS_MAX = int(os.environ.get("CHUCKCHUCK_JUDGE_PRIOR_ANSWERS", "5"))

#: 프롬프트에 실을 발화 발췌 길이. 이 개념의 근거 장 발화만 붙인다.
SPEECH_EXCERPT_MAX = int(os.environ.get("CHUCKCHUCK_JUDGE_SPEECH_EXCERPT_MAX", "500"))

#: 판정에 실을 **자료 근거 장 본문** 총 글자 수. 0 이면 끈다.
#: 2026-09-10 까지 판정은 자료 본문을 아예 못 봤다 — summary 한 줄과 발화 300자로
#: "자료와 어긋나는가" 를 판정했으니 함정에 동의한 답이 60점을 받았다.
SLIDE_BODY_MAX = int(os.environ.get("CHUCKCHUCK_JUDGE_SLIDE_BODY_MAX", "1200"))

#: 개념 하나에 붙여 보여 줄 이웃 개념 수.
NEIGHBOR_MAX = 5

#: CLAUDE.md §3-1 이 금지한 높임. 프롬프트가 해요체를 시켜도 실 LLM 이 「좋아요」 판정에
#: "정확히 짚으셨습니다" 를 냈다 (2026-09-13 Solar A/B, 2문장). 코칭 경로의 _COACH_PRAISE_RE 와
#: 같은 규율 — 문장은 LLM, 말투 계약은 코드. 걸리면 그 등급의 결정적 문구로 바꾼다.
#: examples/qa_eval.py 의 HONORIFIC_RE 와 같은 낱말이라 하네스가 세는 것과 코드가 막는 것이 일치한다.
_HONORIFIC_RE = re.compile(r"셨|시겠|십니|십시오|시나요|시는지|계시|여쭈|께\s")

#: react 가 비어 돌아왔을 때 채워 넣는 결정적 문구.
#: 프론트가 이걸로 말풍선을 그리므로 비워 둘 수 없다.
_REACT_BY_VERDICT = {
    "good": "네, 그 설명이면 충분해요.",
    # '절반' 은 요지를 맞힌 사람에게 과소평가로 읽힌다. 되묻기의 목적은 채점이 아니라
    # 한 걸음 더 끌어내는 것이라, 인정할 것은 인정하고 남은 하나를 가리킨다.
    "partial": "요지는 잡았어요. 한 가지만 더 짚어 주세요.",
    "wrong": "그 부분은 자료와 맞지 않아요.",
    "unknown": "지금 답변만으로는 판단하기 어려워요.",
}

#: summary_sentence 가 비어 돌아왔을 때. 리포트 총평 줄에 그대로 남는다.
_SUMMARY_BY_VERDICT = {
    "good": "{label} — 자기 말로 방어했어요.",
    "partial": "{label} — 방향은 맞지만 근거가 얕아요.",
    "wrong": "{label} — 자료와 어긋나게 설명했어요. 다시 보세요.",
    "unknown": "{label} — 판정을 보류했어요. 다시 답해 보세요.",
}

#: 답변이 비었을 때의 반응. LLM 을 부르지 않고 여기서 끝낸다.
EMPTY_ANSWER_REACT = "아직 답변이 없어요. 짧아도 좋으니 자기 말로 말해 보세요."

#: followup 이 비어 돌아왔을 때 쓰는 결정적 문장. 실전 코칭은 턴 상한이 없어서
#: 되묻기가 멈추면 사용자가 갇힌다 — LLM 이 빠뜨려도 질문은 반드시 나와야 한다.
#: 빠진 포인트가 있으면 그것을 겨냥하고, 없으면 개념 이름으로 좁힌다.
#: 조사를 붙이지 않는 모양으로 둔다 — "인지 자원 를" 처럼 띄어 붙은 조사가 화면에
#: 그대로 나갔다. '~시겠어요' 는 CLAUDE.md §3-1 이 금지한 높임이다.
_FOLLOWUP_BY_POINT = "{point} — 이 부분은 어떻게 봐요?"
_FOLLOWUP_GENERIC = "{label} — 이걸 뒷받침할 근거를 하나만 더 들어 주세요."
#: 답변이 질문·자료와 아무 낱말도 안 겹칠 때. LLM 의 react 는 자료 본문을 답변으로
#: 착각한 문장("…까지는 정확합니다")이라 쓰지 않는다.
_OFF_TOPIC_REACT = "질문과 다른 이야기예요. {label}에 대해 자료에 있는 대로 말해 보세요."
#: 함정 질문의 잘못된 전제를 그대로 받아들였을 때.
_TRAP_AGREED_REACT = "질문의 전제부터 확인해 보세요 — 자료는 그렇게 말하지 않아요."
#: 두 가드가 내리는 점수 상한. 규칙 8 의 wrong 구간(39 이하) 안이다.
OFF_TOPIC_SCORE_MAX = 35
#: 이보다 근거 낱말이 적으면 무관 판정을 하지 않는다 — 실사용은 골자+자료 본문으로
#: 언제나 수백 개다. 질문 한 줄만 있는 호출(테스트·근거 없는 flat 판정)은 건드리지 않는다.
ON_TOPIC_MIN_EVIDENCE_TOKENS = 30
#: 질문·골자·개념(=이 질문이 묻는 것)과 대조할 때의 최소 낱말 수. 상투어를 뺀 뒤 센다.
ON_TOPIC_MIN_FOCUS_TOKENS = 12
#: 이보다 짧은 답("빠진 개념을 찾아 주는 거예요")은 이 대조를 걸지 않는다 — 짧은 바꿔 말하기는 LLM 판정에 맡긴다.
#: 이 가드가 잡는 것은 **길게 잘 말했는데 다른 개념 이야기**인 답이다 (09-26 실측 답은 내용 낱말 12개).
ON_TOPIC_FOCUS_MIN_ANSWER_TOKENS = 8
#: 「이 질문」 을 벗어난 답은 wrong 이 아니라 **통과 못 하는 partial** 이다 — 낱말 대조만으로 "자료와 달라요" 라고 못 박지 않는다.
#: 바꿔 말한 정답이 걸렸을 때의 피해를 되묻기 한 바퀴로 줄인다. 통과선(70) 아래.
FOCUS_MISS_SCORE_MAX = 65
_FOCUS_MISS_REACT = "{label}에 대한 답으로는 조금 멀어요. 질문이 묻는 것에 맞춰 다시 말해 보세요."
#: 이 발표 어디에나 있는 상투어 — 이것만 겹치는 답은 「이 질문」 에 답한 것이 아니다.
#: 2026-09-26 실험대 실측: 개념 그래프 질문에 타깃 시장 이야기가 partial 75 로 통과했다 — 자료 본문과 「발표」 한 낱말이 겹쳐서.
_GENERIC_TOKENS = (
    "발표", "자료", "질문", "설명", "개념", "근거", "이유", "핵심", "내용", "부분", "경우", "방법", "방식", "정도",
    "이것", "그것", "저희", "우리", "이후", "계획", "생각", "때문", "그래서", "하지만", "그리고", "위해", "통해", "대해",
    "관해", "무엇", "어떤", "어느", "어떻게", "있어요", "없어요", "같아요", "거예요", "이에요", "예요", "해요", "됩니다",
    "있습니다", "없습니다", "합니다", "입니다", "했어요", "했습니다", "서비스", "프로젝트", "사용자", "기능",
)
TRAP_AGREED_SCORE_MAX = 35

#: 되묻기 단계별 지시. **질문의 넓이는 코드가 정하고 LLM 은 그 넓이의 문장만 쓴다.**
#: 단계가 안 좁혀지면 사용자는 같은 벽을 세 번 만나고, 세 번째에 창을 닫는다.
_PROBE_TIER_BRIEF = {
    "probe": (
        "1라운드다. 빠진 지점 하나를 **열린 질문**으로 짚어라. "
        "발표자가 자기 말로 한 문단을 더 붙일 여지를 남겨 둔다."
    ),
    "focus": (
        "2라운드다. 같은 넓이로 또 물으면 안 된다. followup 은 **예/아니오나 둘 중 "
        "하나, 혹은 한 단어**로 답할 수 있어야 한다. **선택지를 질문 안에 넣어라.**\n"
        "  쓸 수 있는 모양: \"A인가요, B인가요?\" · \"자료에 있었나요, 없었나요?\" · "
        "\"한 단어로 말하면 무엇인가요?\"\n"
        "  쓰면 안 되는 모양: \"왜 …인가요?\" · \"…는 무엇인가요?\" · \"설명해 주시겠어요?\"\n"
        "  — 이건 1라운드의 넓이다. 좁혀 준다고 해 놓고 같은 벽을 다시 세우는 셈이다.\n"
        "  발표자가 첫 발을 떼는 것이 목적이지 완결된 답을 받는 것이 목적이 아니다."
    ),
    "converge": (
        "3라운드 이상이다. 여기서도 막히면 발표자는 지친다. followup 은 **답을 거의 "
        "품은 확인 질문**이어야 한다 — 고개만 끄덕이면 되게 마지막 한 걸음만 남겨라.\n"
        "  쓸 수 있는 모양: \"…때문이라고 보면 될까요?\" · \"…라고 이해하면 맞을까요?\"\n"
        "  쓰면 안 되는 모양: 열린 질문 전부. 정답 문장을 그대로 읽어 주지도 마라."
    ),
}

#: 단계별 결정적 폴백 질문. LLM 이 followup 을 빠뜨려도 되묻기는 반드시 나와야 한다 —
#: 실전 코칭은 턴 상한이 없어서, 질문이 멈추면 사용자가 그 자리에 갇힌다.
_FOLLOWUP_BY_TIER = {
    "focus": "{point} — 이건 자료에 있었나요, 없었나요?",
    "converge": "{point} 때문이라고 보면 될까요?",
}

#: 열린 질문의 표지. focus·converge 인데 이게 보이면 **단계를 안 지킨 문장**이다.
#: 실측(2026-08-08, solar-pro3): 단계 지시를 user 꼬리에 붙여도, system 으로 올려도
#: 2라운드에 "…어떤 점에서 더 유리한가요?" 처럼 1라운드와 같은 넓이로 되물었다.
#: 프롬프트로 부탁만 해서는 사다리가 안 좁혀진다.
_OPEN_QUESTION_RE = re.compile(r"왜\s|무엇|어떤\s|어떻게\s|설명해|말씀해\s*주|이유는")


def _is_narrow(text: str) -> bool:
    """
    좁힌 질문인가 — 예/아니오·둘 중 하나·한 단어로 답할 수 있는 모양인가.

    "한 단어로 말하면 무엇인가요?" 는 «무엇» 을 품지만 좁은 질문이다.
    이 한 가지만 예외로 두고, 나머지는 열린 표지가 없으면 좁은 것으로 본다.
    """
    if "한 단어" in text:
        return True
    return not _OPEN_QUESTION_RE.search(text)

SYSTEM_PROMPT = """당신은 발표 심사위원이다.
방금 던진 질문에 발표자가 답했다. 그 답이 개념을 **실제로 방어했는지** 판정한다.

되묻기로 여러 번에 나눠 답했다면 **그 답변들을 합쳐서** 본다.
앞 턴에서 이미 말한 것을 다시 빠졌다고 하지 마라 — 마지막 한 마디만 채점하면
좁혀 물은 쪽이 손해를 본다.

**아래는 누적 답변이 있을 때(2턴 이상)만 적용한다.**
여러 턴에 나눠서 골자의 요소를 **전부** 말했으면 good 이다. 한 턴에 다 담지
못했다고 깎지 마라 — 되묻기의 목적은 발표자가 스스로 나머지를 꺼내게 하는
것이고, 꺼냈으면 성공한 것이다. 끝내 good 을 못 받으면 아무리 답해도 못 이기는
대화가 되고, 그러면 다음부터 시도하지 않는다.

**첫 턴에는 이 규칙이 없다.** 아직 나눠 말한 것이 없으므로 평소대로 엄격히
매겨라 — 첫 답에 무르면 되묻기가 시작조차 안 된다. 누적이든 아니든 골자의
요소가 하나라도 안 나왔으면 partial 이다.

verdict 는 다음 넷 중 하나다:
- "good" (설득 완료): 개념을 자기 말로 정확히 설명했다. 근거도 댔다.
- "partial" (부분 인정): 방향은 맞지만 핵심 근거가 빠졌거나 얕다.
- "wrong" (미방어): 자료와 어긋나게 설명했거나 질문을 빗나갔다.
- "unknown" (판정 보류): 무슨 말인지 알 수 없어 내용으로 판정할 수 없다.
  **짧다는 이유로 고르지 마라** — 질문이 요구한 것을 담았는지로만 정한다.

규칙:
1. **내용만 본다.** 말투·문장력·길이로 깎지 마라. 짧아도 맞으면 good 이다.
1-1. **답변에 있는 것만 답변이다.** 아래 '자료 근거 장 본문'·'기대하는 답의 골자' 는
   대조 원본이지 발표자가 말한 것이 아니다. 답변 본문에 없는 내용을 답변이 말한
   것으로 치지 마라. 답변이 질문·자료와 무관한 이야기면 wrong 이다.
2. **선택형 질문(둘 중 하나·예/아니오)은 맞는 쪽을 고른 것 자체가 완전한 답이다.**
   "얕은 수면인가요, 깊은 수면인가요?" 에 "얕은 수면이요" 라고만 답해도,
   그 선택이 맞으면 근거가 없어도 good 이다.
3. '기대하는 답의 골자' 가 주어지면 **그것이 채점 기준이다.** 표현·용어가 달라도
   뜻이 같으면 정답으로 본다. 골자의 문장을 react·followup 에 그대로 옮겨
   정답을 흘리지 마라.
4. 이 질문이 '함정' 이라면, 발표자가 그 잘못된 전제를 **바로잡았을 때** good 이다.
   함정에 그대로 동의했으면 wrong 이다. 함정 질문에는 출력에 premise_corrected 를
   **반드시** 적는다 — 전제가 틀렸다고 지적·정정했으면 true, 받아들였거나 언급이
   없으면 false. 이 값은 코드가 등급에 그대로 반영한다.
5. react 는 심사위원이 그 자리에서 할 한 마디다. 존댓말, 한 문장.
   **답변 안에서 맞힌 것을 먼저 이름 붙이고 나서** 남은 것을 가리켜라 — "…까지는 정확합니다.
   그럼 …은요?" 처럼. 틀린 데부터 말하면 발표자는 다음 답을 시도하지 않는다.
   앞 턴보다 나아졌으면 그 진전을 짚어라. 빈말 칭찬은 하지 마라.
6. summary_sentence 는 이 개념에 대한 총평 한 문장이다. 리포트에 남는다.
7. missing_points 에는 **통과를 막는 결정적 결손 하나만** 적는다.
   "있으면 더 좋을" 수준은 적지 마라. 부족한 데가 없으면 빈 배열이다.
   여러 개를 늘어놓으면 발표자는 뭘 고쳐야 할지 도리어 모른다.
8. score 는 0~100. **70점 이상이면 통과로 처리된다.**
   - good: 80 이상
   - partial 중 **요지는 맞고 근거만 얕다**: 70~79 — 통과 구간이다
   - partial 중 방향만 겨우 맞다: 40~59
   - wrong: 39 이하
   표현이나 용어가 자료와 달라도 **요지가 같으면 70~79 를 줘라.**
   완벽한 문장을 받아내는 것이 목적이 아니다.
9. followup 은 **이어서 던질 질문 한 문장**이다. verdict 가 good 이 아니면
   **반드시 쓴다.** 요지를 맞힌 답에도 쓴다 — 절반 맞힌 사람을 거기서 놓아 주면
   스스로 깨우칠 기회를 뺏는 것이다. good 일 때만 빈 문자열이다.
   - 원래 질문을 **다시 말하지 마라.** 빠진 지점 하나를 콕 집어 물어라.
   - 발표자를 몰아세우지 말고, 답할 수 있게 좁혀 주는 질문이어야 한다.
   - **[되묻기 단계] 가 주어지면 그 단계의 넓이로 물어라.** 같은 넓이로 세 번
     물으면 압박이 아니라 반복이다. 단계마다 한 칸씩 좁혀 답에 다가가게 한다.
10. 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마 — **아래 값은 자리 표시자다. 그대로 베끼지 말고 이번 답변을 보고 새로 써라.**
{
  "verdict": "good | partial | wrong | unknown 중 하나",
  "score": 0,
  "react": "<심사위원이 그 자리에서 할 한 마디>",
  "summary_sentence": "<이 개념에 대한 총평 한 문장>",
  "missing_points": ["<답변에서 빠진 포인트>"],
  "followup": "<빠진 지점을 겨냥한 후속 질문 한 문장. 충분하면 빈 문자열>",
  "covered_parts": [true, false],
  "premise_corrected": true
}

premise_corrected 는 함정 질문일 때만 쓴다 (아니면 빼거나 null).

covered_parts 는 '골자의 요소' 가 주어졌을 때만 쓴다 (없으면 빈 배열).
요소와 **같은 순서·같은 개수**로 참/거짓만 적는다. 개수가 어긋나면 통째로 버려진다.
"""

#: 응답이 복구 불가능한 JSON 일 때 한 번 더 물어볼 때 덧붙이는 말.
JSON_RETRY_NUDGE = """
[재요청] 직전 응답이 완전한 JSON 객체가 아니어서 버렸다.
코드펜스·주석·말머리·말끝 문장 없이, 출력 스키마 그대로의 JSON 객체 하나만 다시 출력하라.
"""


# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------

def _concept_block(question: Question, graph: ConceptGraph | None) -> list[str]:
    """
    자료가 말하는 이 개념 + 그래프에서의 위치.

    edges 가 진실이다. 경로는 parent 간선만 따라간 트리 뷰, 연결은 relates 까지 포함한
    그래프 뷰다. 답변이 "옆 개념과의 관계" 를 짚었는지 보려면 이게 있어야 한다.
    """
    node = graph.node(question.node_id) if graph is not None else None
    if node is None:
        return []

    lines = ["", "## 자료가 말하는 이 개념"]
    if node.summary:
        lines.append(f"{node.label}: {node.summary}")
    path = [n.label for n in graph.path_of(node.id)]
    if len(path) > 1:
        lines.append("경로(위계): " + " > ".join(path))
    # 무거운 이웃부터. id 로 동률을 깨 같은 그래프면 같은 줄이 나온다 (f08 과 같은 규칙)
    ranked = sorted(graph.neighbors_of(node.id), key=lambda n: (-n.weight, n.id))
    if ranked:
        shown = ", ".join(n.label for n in ranked[:NEIGHBOR_MAX])
        if len(ranked) > NEIGHBOR_MAX:
            shown += f" 외 {len(ranked) - NEIGHBOR_MAX}개"
        lines.append("연결된 개념: " + shown)
        # 이웃의 요약·간선 종류. 이름만으로는 "옆 개념과의 관계를 짚었는가" 를 못 본다.
        for ln in neighbor_lines(node, graph):
            lines.append(f"  - {ln}")
    return lines if len(lines) > 2 else []


def _slide_block(
    question: Question, slidedoc: SlideDoc | None, graph: ConceptGraph | None
) -> list[str]:
    """
    질문의 근거 장 **자료 본문** — 판정이 "자료와 어긋난다" 를 대조할 원본이다.

    F-08 이 만든 질문은 slide_nos 가 이미 anchor(최대 3장)다. 옛 세션의 질문은
    12장을 들고 올 수 있어 여기서 다시 좁힌다. 장마다 예산을 나눠 싣는다.
    """
    if slidedoc is None or SLIDE_BODY_MAX <= 0 or not question.slide_nos:
        return []
    texts = {s.slide_no: clean_slide_text(s.raw_text or "") for s in slidedoc.slides}
    node = graph.node(question.node_id) if graph is not None else None
    nos = anchor_slides(
        question.label, node.summary if node else "", list(question.slide_nos), texts
    )
    nos = [n for n in nos if texts.get(n)]
    if not nos:
        return []
    per_slide = max(80, SLIDE_BODY_MAX // len(nos))
    lines = ["", "## 자료 근거 장 본문 (판정의 대조 원본 — 발표자가 말한 것이 아니다)"]
    for no in nos:
        text = texts[no]
        if len(text) > per_slide:
            text = text[: per_slide - 1].rstrip() + "…"
        lines.append(f"[S{no}] {text}")
    return lines


def _speech_block(question: Question, transcript: Transcript | None) -> list[str]:
    """근거 장에서 실제로 한 말. Transcript.by_slide 를 slide_no 로 조인한다."""
    if transcript is None or not question.slide_nos:
        return []
    said = " ".join(
        text
        for text in (transcript.text_for_slide(no).strip() for no in question.slide_nos)
        if text
    )
    if not said:
        return []
    if len(said) > SPEECH_EXCERPT_MAX:
        said = said[: SPEECH_EXCERPT_MAX - 1].rstrip() + "…"
    return ["", "## 발표 때 이 개념의 근거 장에서 한 말", said]


def _build_user_prompt(
    question: Question,
    answer: str,
    history: list[QaTurn],
    graph: ConceptGraph | None,
    alignment: AlignmentDoc | None,
    transcript: Transcript | None,
    ctx: Context,
    prior_answers: list[str] | None = None,
    slidedoc: SlideDoc | None = None,
    memory_cm: ConceptMemory | None = None,
) -> str:
    """
    질문 → 자료 근거 → 지난 대화 → 지난 리허설 기억 → 이번 답변 순.

    판정 대상(질문)을 맨 앞에 두는 것은 F-07·F-11 에서 확인한 배치다 —
    앞에 둬야 모델이 답변을 질문에 비추어 보지, 답변만 따로 요약하지 않는다.
    """
    parts = [
        "[TASK] qa-judge",
        ctx.to_prompt_block(),
        "",
        "## 던진 질문",
        f"개념: {question.label} (id={question.node_id})",
        f"질문: {question.question}",
        f"함정 질문인가: {'예' if question.trap else '아니오'}",
    ]
    if question.why:
        parts.append(f"이 질문을 던진 이유: {question.why}")

    parts += _concept_block(question, graph)
    parts += _slide_block(question, slidedoc, graph)

    item = None
    if alignment is not None:
        item = next((i for i in alignment.items if i.node_id == question.node_id), None)
    if item is not None and item.evidence.strip():
        parts += [
            "",
            "## 발표 때 이 개념에 대해 한 말 (정합 판정 근거)",
            f"({item.verdict}) {item.evidence}",
        ]
    parts += _speech_block(question, transcript)

    recent = history[-HISTORY_TURNS:] if history else []
    if recent:
        parts += ["", "## 지금까지 주고받은 대화"]
        for turn in recent:
            parts.append(f"- Q: {turn.question}")
            parts.append(f"  A: {turn.answer}  → {turn.verdict}")

    parts += _memory_block(memory_cm)
    parts += _answer_block(answer, prior_answers)
    return "\n".join(parts)


def _memory_concept(question: Question, memory: MemoryDoc | dict | None, graph: ConceptGraph | None) -> ConceptMemory | None:
    """이 질문의 개념에 붙은 기억. 그래프가 있으면 node_id 로, 없으면 질문의 label 로 잇는다."""
    if memory is None:
        return None
    if isinstance(memory, dict):
        memory = MemoryDoc.from_dict(memory)
    if graph is not None:
        cm = memory.by_node(graph).get(question.node_id)
        if cm is not None:
            return cm
    return memory.concept(question.label)


def _memory_block(cm: ConceptMemory | None) -> list[str]:
    """F-25 지난 리허설 기억. 없으면 빈 목록 — 프롬프트가 예전과 같다."""
    if cm is None or cm.attempts <= 0:
        return []
    lines = ["", "## 지난 리허설에서 이 개념 (같은 발표자 · 사실만)", cm.prompt_line]
    if cm.missing_points:
        lines.append(
            "지난번에 빠졌던 점이 이번 답에 나왔으면 summary_sentence 에서 그 진전을 알아봐 주고("
            "예: \"지난번엔 빠졌던 조건을 이번엔 짚었어요\"), 또 빠졌으면 missing_points 에 같은 말로 적어라."
        )
    return lines


def _gist_parts_block(question: Question) -> str:
    """
    요소별 채점 체크리스트. 요소가 없는 질문에서는 빈 문자열이라 프롬프트가 안 는다.

    **결정은 코드가 한다** (`_enforce_good`). 여기서 받는 것은 요소마다
    「나왔는가」 하나뿐이고, good 을 줄지 말지는 그 답을 보고 코드가 정한다.
    체크리스트를 안 주고 판정만 맡기면 둘 중 하나만 답해도 good 이 나온다.
    """
    parts = question.answer_gist_parts
    if not parts:
        return ""
    lines = [
        "",
        "",
        "## 골자의 요소 — 이 질문은 둘 이상을 묻는다",
        "누적 답변 전체를 합쳐, 요소마다 나왔는지 본다.",
    ]
    lines += [f"{i}. {part}" for i, part in enumerate(parts, start=1)]
    lines += [
        f"covered_parts 에 이 {len(parts)}개의 참/거짓을 **같은 순서로** 적어라.",
        "표현이 달라도 뜻이 같으면 나온 것이다 (규칙 3).",
        "**하나라도 안 나왔으면 good 이 아니다.**",
    ]
    return "\n".join(lines)


def _answer_block(answer: str, prior_answers: list[str] | None) -> list[str]:
    """
    판정 대상 블록. 되묻기로 나눠 말한 답변을 **합쳐서** 판정하게 한다.

    후속 질문 규칙(SYSTEM_PROMPT 7)은 "빠진 지점 하나를 콕 집어" 물어 발표자를
    증분 답변으로 유도한다. 그런데 마지막 증분만 채점하면 1턴에 A, 2턴에 B 를 말한
    사람이 A+B 를 다 말하고도 B 만으로 평가된다 — 좁혀 물은 쪽이 손해를 본다.

    앞 답변이 없으면 예전과 같은 한 줄짜리 블록이다. 빈 문자열은 버린다.
    """
    prior = [text.strip() for text in (prior_answers or []) if (text or "").strip()]
    if not prior:
        return ["", "## 이번 답변 — 이것을 판정하라", answer.strip()]

    prior = prior[-PRIOR_ANSWERS_MAX:]
    lines = ["", "## 이 질문에 대한 답변 (누적) — 전체를 합쳐서 판정하라"]
    for turn_no, text in enumerate(prior, start=1):
        lines.append(f"{turn_no}턴: {text}")
    lines.append(f"{len(prior) + 1}턴 (이번): {answer.strip()}")
    return lines


# ---------------------------------------------------------------------------
# 후처리 — LLM 판정을 계약 안으로 밀어 넣는다
# ---------------------------------------------------------------------------

def _clamp_score(raw: object, verdict: str) -> int:
    """score 를 못 읽으면 verdict 기본값, 읽히면 0~100 으로 자른다."""
    try:
        score = int(raw)
    except (TypeError, ValueError):
        return QA_VERDICT_SCORES[verdict]
    return max(0, min(100, score))


#: 'good' 으로 인정하는 최저 점수 (SYSTEM_PROMPT 규칙 8 과 같은 값).
GOOD_SCORE_MIN = 80

#: good 을 막을 때 남기는 최고 점수. **통과선(QA_PASS_SCORE=70) 위, good 선 아래**다.
#: 70 밑으로 떨어뜨리면 `qa_mastered` 의 3라운드 출구까지 닫혀서 그 질문에 갇힌다 —
#: 우리가 막으려는 것은 «무른 통과» 지 «출구» 가 아니다.
GIST_MISS_SCORE_MAX = GOOD_SCORE_MIN - 1


def _uncovered_parts(data: dict, question: Question) -> list[str]:
    """
    판정이 보고한 요소별 커버리지에서 **안 나온 요소**만 추린다.

    `covered_parts` 는 요소와 **같은 순서·같은 개수**의 참/거짓 배열이다.
    길이가 어긋나면 어느 요소를 가리키는지 알 수 없으므로 통째로 버린다 —
    짐작해서 맞추면 엉뚱한 요소를 빠졌다고 말하게 된다.
    """
    parts = question.answer_gist_parts
    raw = data.get("covered_parts")
    if not parts or not isinstance(raw, (list, tuple)) or len(raw) != len(parts):
        return []
    return [part for part, covered in zip(parts, raw) if not bool(covered)]


def _enforce_good(
    data: dict,
    question: Question,
    verdict: str,
    score: int,
    points: list[str],
) -> tuple[str, int, list[str]]:
    """
    good 을 **코드가** 막는다. 골자의 요소가 남았으면 통과시키지 않는다.

    SYSTEM_PROMPT 는 이미 "골자의 요소가 하나라도 안 나왔으면 partial 이다" 라고
    적어 두었는데, 실 LLM 이 지키지 않는 것이 이번에 지적받은 무른 통과다.
    프롬프트로 부탁만 해서는 안 지켜지는 것을 코드가 받는 자리는 이 모듈에 이미
    있다 — `_followup` 이 단계에 안 맞는 문장을 버리는 것과 같은 규율이다.

    두 가지를 본다.

    1. **요소 미달** — `answer_gist_parts` 가 있으면 판정에 `covered_parts`
       (요소 순서대로 true/false)를 함께 받아, 하나라도 false 면 good 을 막는다.
       개수가 안 맞거나 아예 없으면 **판단 근거가 없는 것**이라 손대지 않는다 —
       근거 없이 깎으면 맞힌 사람이 이유 없이 진다.
    2. **자기모순** — good 인데 missing_points 를 적어 왔다. 규칙 7 이 거기에는
       "통과를 막는 결정적 결손" 만 적으라고 했으므로 둘이 동시에 참일 수 없다.

    **둘 다 요소 목록이 있는 질문에만 건다.** 2번을 모든 질문에 걸어 봤는데,
    그건 코드로 검증할 수 없는 «모델 습관» 에 걸린 규칙이었다 — 실 LLM 이 멀쩡한
    답에도 「있으면 더 좋을」 결손을 적으면 모든 질문이 3라운드까지 가서 대화
    호흡이 늘어진다. 요소를 못박은 질문 안에서는 규칙 7 위반이 분명하지만,
    밖에서는 그게 위반인지 조언인지 코드가 가릴 수 없다. 무른 통과를 막으려다
    대화를 망치지 않는다.

    막을 때도 점수는 GIST_MISS_SCORE_MAX 로만 내린다. 되묻기를 한 바퀴 더 돌리는
    것이 목적이고, 3라운드에 닿으면 통과 수준에서 닫힌다 (`qa_mastered`).
    """
    if verdict != "good" or not question.answer_gist_parts:
        return verdict, score, points

    uncovered = _uncovered_parts(data, question)
    if not uncovered and not points:
        return verdict, score, points

    # 빠진 요소를 결손 목록 맨 앞에 세운다 — `_followup` 이 물을 지점이 되고,
    # 힌트 사다리 4단(`_hint_close`)이 "아직 안 나온 것" 으로 열어 준다.
    merged = uncovered + [p for p in points if p not in uncovered]
    return "partial", min(score, GIST_MISS_SCORE_MAX), merged


#: 한 칸 더 좁힌 단계. 발표자가 스스로 «이건 모르겠다» 고 밝힌 조각을 그 단계의
#: 넓이로 다시 물으면, 좁혀 주겠다고 해 놓고 같은 벽을 세우는 셈이다.
_TIER_NARROWER = {"probe": "focus", "focus": "converge", "converge": "converge"}


def _content_tokens(text: str) -> list[str]:
    return [t for t in norm_tokens(text or "") if len(t) >= 2]


def _is_generic(token: str) -> bool:
    return any(token.startswith(g) for g in _GENERIC_TOKENS)


def _shares_vocabulary(
    answer: str, evidence: str, min_tokens: int = ON_TOPIC_MIN_EVIDENCE_TOKENS, *, drop_generic: bool = False
) -> bool:
    """
    답변과 근거가 낱말을 하나라도 공유하는가. 조사가 붙은 토큰("알림을"·"알림")은
    앞머리 일치로 같은 낱말로 본다. 둘 중 하나가 비면 판단할 수 없어 True 다.
    drop_generic 이면 상투어(_GENERIC_TOKENS)를 양쪽에서 뺀 뒤 본다 — 「이 질문」 과 겹치는지 볼 때.
    """
    a_tokens = _content_tokens(answer)
    e_tokens = _content_tokens(evidence)
    if drop_generic:
        a_tokens = [t for t in a_tokens if not _is_generic(t)]
        e_tokens = [t for t in e_tokens if not _is_generic(t)]
    # 근거가 얇으면(자료 본문·발화 없이 질문 한 줄뿐) 안 겹치는 것이 신호가 아니다.
    if not a_tokens or len(e_tokens) < min_tokens:
        return True
    e_set = set(e_tokens)
    for a in a_tokens:
        if a in e_set:
            return True
        if any(e.startswith(a) or a.startswith(e) for e in e_set):
            return True
    return False


def _enforce_on_topic(
    answer: str, evidence: str, question: Question, verdict: str, score: int, points: list[str], focus: str = ""
) -> tuple[str, int, list[str], str]:
    """
    **질문·자료와 아무 낱말도 안 겹치는 답은 wrong 이다.** 코드가 막는다.

    2026-09-10 실측: 물류 창고 재고 회전율 이야기(이 발표와 무관)에 partial 65~75 가
    나왔다. react 는 "스마트폰 시야 밖 두기·메일 닫기까지는 정확합니다" — 답변이
    아니라 프롬프트에 실린 **자료 본문을 답변으로 착각**한 것이다. 자료를 더 실을수록
    이 착각은 커지므로, 규칙 1-1 로 부탁하고 여기서 받는다.

    낱말 하나만 겹쳐도 통과시킨다 — 바꿔 말한 답을 오답으로 만들지 않기 위해서다.
    이 가드는 «관련 없는 이야기» 만 잡는다.

    2026-09-26 실측(실험대): 개념 그래프 질문에 **타깃 시장 이야기**(이 발표의 다른 개념)가 partial 75 — 자료 본문 전체와
    「발표」 가 겹쳐 위 검사를 비켜 갔다. 그래서 `focus`(질문·골자·이 개념의 그래프 자리)와도 대조한다 — 상투어를 뺀 뒤
    낱말 하나도 안 겹치면 이 질문에 답한 것이 아니다. 단, 이쪽은 wrong 이 아니라 **통과 못 하는 partial** 로만 내린다 —
    같은 날 "빠진 개념을 찾아 주는 거예요" 같은 짧은 바꿔 말하기가 걸렸다. 낱말 대조는 «다른 이야기» 는 알아도
    «틀린 이야기» 는 모른다. 짧은 답(ON_TOPIC_FOCUS_MIN_ANSWER_TOKENS 미만)은 LLM 에 맡긴다.

    마지막 값은 어느 가드가 걸렸는지다 — "" · "off_topic"(자료와도 무관 → wrong) · "focus_miss"(이 질문만 벗어남 → partial ≤ 65).
    """
    lead = f"질문이 묻는 것: {question.label or question.node_id}"
    if not _shares_vocabulary(answer, evidence):
        return "wrong", min(score, OFF_TOPIC_SCORE_MAX), [lead] + [p for p in points if p != lead], "off_topic"
    if (focus and len(_content_tokens(answer)) >= ON_TOPIC_FOCUS_MIN_ANSWER_TOKENS
            and not _shares_vocabulary(answer, focus, ON_TOPIC_MIN_FOCUS_TOKENS, drop_generic=True)):
        demoted = "partial" if verdict in ("good", "partial") else verdict
        return demoted, min(score, FOCUS_MISS_SCORE_MAX), [lead] + [p for p in points if p != lead], "focus_miss"
    return verdict, score, points, ""


def _enforce_trap(
    data: dict, question: Question, verdict: str, score: int, points: list[str]
) -> tuple[str, int, list[str], bool]:
    """
    함정 질문에 **전제를 받아들인 답은 통과하지 못한다.** 코드가 막는다.

    규칙 4 는 처음부터 "동의했으면 wrong" 이었는데 실 LLM 은 "네, 맞습니다" 에
    partial 60~70 을 줬다 (2026-09-10 실측). 판정에 premise_corrected 를 함께 받아
    false 면 등급을 되돌린다. 값이 없으면 판단 근거가 없는 것이라 손대지 않는다
    (`_enforce_good` 과 같은 규율 — 근거 없이 깎으면 맞힌 사람이 이유 없이 진다).
    """
    if not question.trap:
        return verdict, score, points, False
    corrected = data.get("premise_corrected")
    if corrected is None or bool(corrected):
        return verdict, score, points, False
    lead = "질문의 전제가 자료와 다르다는 점"
    return "wrong", min(score, TRAP_AGREED_SCORE_MAX), [lead] + [p for p in points if p != lead], True


def _normalize(
    data: dict,
    question: Question,
    model: str,
    round_no: int = 1,
    *,
    followup_tier: str = "",
    forced_point: str = "",
    answer: str = "",
    evidence: str = "",
    focus: str = "",
) -> QaJudgement:
    """
    - verdict 가 enum 밖이면 QA_VERDICT_FALLBACK ('unknown')
    - score 없으면 verdict 기본값, 있으면 clamp
    - node_id 는 **질문에서 승계** — LLM 이 다른 값을 줘도 무시한다
      (조인 키가 흔들리면 리포트가 엉뚱한 개념에 총평을 붙인다)
    - react·summary_sentence 는 비면 결정적 문구로 채운다
    - round_no·probe_tier 는 **코드가 정한다** — LLM 이 보낸 값은 읽지 않는다.
      대화의 출구(mastered)가 여기 달려 있어서, 모델이 흔들면 루프가 흔들린다.
    """
    # 표기 정규화 — "Good"·" partial " 을 그대로 enum 대조하면 unknown 으로
    # 떨어지는데 score 는 살아 있어 '판정 보류' 배지를 달고 통과하는 모순이 된다.
    verdict = str(data.get("verdict", "") or "").strip().lower()
    if verdict not in QA_VERDICTS:
        verdict = QA_VERDICT_FALLBACK

    raw_score = data.get("score")
    score = QA_VERDICT_SCORES[verdict] if raw_score is None else _clamp_score(raw_score, verdict)

    points = [
        str(p).strip()
        for p in (data.get("missing_points") or [])
        if str(p).strip()
    ]
    # 스스로 «이건 모르겠다» 고 밝힌 조각은 **반드시** 결손 목록에 오른다.
    # 여기 없으면 힌트 사다리 4단이 그걸 열어 주지 못해서, 모른다고 말한 보람이
    # 없는 대화가 된다. LLM 이 알아서 적었으면 그 자리를 맨 앞으로 올리기만 한다.
    if forced_point:
        points = [forced_point] + [p for p in points if p != forced_point]

    # 무른 통과는 여기서 잘린다. **등급·점수·결손만** 코드가 되돌린다 —
    # 문장은 LLM, 계약은 코드 (모듈 원칙). react·summary 폴백보다 앞에 둬야
    # 등급이 뒤집힌 판정에 "충분합니다" 라는 good 폴백이 붙지 않는다.
    verdict, score, points = _enforce_good(data, question, verdict, score, points)
    # 함정 동의가 먼저다 — "네, 맞아요" 는 질문에 답한 것이라 무관 가드가 볼 일이 아니다 (09-26 실측: 무관 문구가 먼저 붙었다).
    verdict, score, points, trap_agreed = _enforce_trap(data, question, verdict, score, points)
    guard = ""
    if not trap_agreed:
        verdict, score, points, guard = _enforce_on_topic(
            answer, evidence, question, verdict, score, points, focus
        )

    react = str(data.get("react", "") or "").strip() or _REACT_BY_VERDICT[verdict]
    # 가드가 등급을 뒤집었으면 LLM 의 react 는 그 등급과 어긋난 문장이다 — 코드 문구로.
    if trap_agreed:
        react = _TRAP_AGREED_REACT
    elif guard == "off_topic":
        react = _OFF_TOPIC_REACT.format(label=question.label or "이 개념")
    elif guard == "focus_miss":
        react = _FOCUS_MISS_REACT.format(label=question.label or "이 개념")
    elif _HONORIFIC_RE.search(react):
        react = _REACT_BY_VERDICT[verdict]
    summary = str(data.get("summary_sentence", "") or "").strip()
    if _HONORIFIC_RE.search(summary):
        summary = ""
    if not summary:
        summary = _SUMMARY_BY_VERDICT[verdict].format(
            label=question.label or question.node_id or "이 개념"
        )

    round_no = max(1, int(round_no or 1))
    mastered = qa_mastered(verdict, score, round_no)
    judgement = QaJudgement(
        question_id=question.id,
        node_id=question.node_id,
        verdict=verdict,
        score=score,
        react=react,
        summary_sentence=summary,
        missing_points=points,
        model=model,
        round_no=round_no,
        # 정복했으면 되물을 일이 없다. 단계를 남겨 두면 화면이 「3차 확인」 이라고
        # 써 놓고 다음 질문으로 넘어가는 모순이 된다.
        # probe_tier 는 **라운드 그대로** 둔다 — 화면이 「2차 확인」 을 세는 축이다.
        # 좁히는 것은 followup 의 모양뿐이라 그 인자만 따로 받는다.
        probe_tier="" if mastered else qa_probe_tier(round_no),
        followup=_followup(
            data, question, points, mastered,
            followup_tier or qa_probe_tier(round_no),
        ),
    )
    # 힌트는 판정을 보고 만든다 — 사용자가 실제로 빠뜨린 것에 반응해야 하기 때문이다.
    # 판정에 함께 실어 보내면 프론트가 추가 왕복 없이 즉시 보여 줄 수 있다.
    judgement.hints = build_hint_ladder(question, judgement)
    return judgement


_HAEYO_FIELDS = ("react", "summary_sentence", "followup", "explanation")


def _haeyo_data(data: dict) -> dict:
    """LLM 응답의 문장 필드를 해요체로 푼다(_speech.to_haeyo). 2026-09-26 실측: 총평·해설이 매번 「~했습니다」 였다.
    새 dict 를 돌려준다 — 원본은 건드리지 않는다."""
    out = dict(data)
    for k in _HAEYO_FIELDS:
        v = out.get(k)
        if isinstance(v, str) and v:
            out[k] = to_haeyo(v)
    return out


def _clip(text: str) -> str:
    """QA_TEXT_MAX 로 자른다 (f08_questions 와 같은 규칙)."""
    stripped = (text or "").strip()
    if len(stripped) <= QA_TEXT_MAX:
        return stripped
    return stripped[: QA_TEXT_MAX - 1].rstrip() + "…"


def _followup(
    data: dict,
    question: Question,
    points: list[str],
    mastered: bool,
    tier: str,
) -> str:
    """
    되물을 후속 질문. **정복(mastered)했을 때만 비운다.**

    예전에는 `qa_passed` 로 잘랐다. 그런데 판정 규칙 8 이 "요지는 맞고 근거만
    얕다" 를 70~79 로 매기게 하고 그 구간이 곧 통과라, **가장 흔한 답변이
    되묻기를 통째로 건너뛰었다.** 절반 맞힌 사람에게 한 걸음 더 묻는 것이
    이 서비스의 핵심 로직인데 그 로직이 실행되지 않고 있었던 것이다.

    정복한 답에까지 질문을 남기면 반대 방향의 모순이 된다 — "설득 완료" 라고
    해 놓고 또 묻는 화면. 그래서 자르는 기준을 없앤 게 아니라 옮겼다.

    폴백도 단계를 따른다. LLM 이 빠뜨렸다고 1라운드짜리 열린 질문을 3라운드에
    내면, 좁혀 주겠다고 해 놓고 같은 벽을 다시 세우는 셈이다.

    그리고 **LLM 이 쓴 문장도 단계에 안 맞으면 버린다.** 프롬프트로 부탁만
    해서는 안 좁혀지는 것을 실측으로 확인했다 (_OPEN_QUESTION_RE 주석 참고).
    무엇을 물을지는 코드가 정하고 LLM 은 문장만 쓴다 — 문장이 계약을 안 지키면
    코드가 쓴다. 이 모듈이 verdict·score 에 하는 것과 같은 일이다.
    """
    if mastered:
        return ""

    point = points[0] if points else (question.label or "이 개념")
    written = _clip(str(data.get("followup", "") or ""))
    if _HONORIFIC_RE.search(written):
        written = ""
    # probe(1라운드)는 열린 질문이 맞는 모양이라 그대로 쓴다.
    if written and (tier == "probe" or _is_narrow(written)):
        return written

    shaped = _FOLLOWUP_BY_TIER.get(tier)
    if shaped:
        return _clip(shaped.format(point=point))
    if points:
        return _clip(_FOLLOWUP_BY_POINT.format(point=points[0]))
    return _clip(_FOLLOWUP_GENERIC.format(label=question.label or "이 개념"))


# ---------------------------------------------------------------------------
# 막힘 코칭 — "모르겠어요" 에 응한다
#
# 판정과 별도의 경로다. 포기한 사람에게 점수를 매기는 것은 의미가 없고,
# 되묻기만 반복하면 같은 질문에 갇힌다. 대신 한 단계 끌어주고, 그래도 막히면
# 해설하고 넘어간다.
# ---------------------------------------------------------------------------

#: 포기로 볼 답변의 최대 길이. 짧을수록 안전하다 — 놓쳐도 사용자에게는
#: 「모르겠어요」 버튼이라는 명시적 출구가 있지만, 오탐하면 진짜 답변이 묻힌다.
GIVE_UP_MAX_CHARS = 15

#: 포기 표현.
_GIVE_UP_RE = re.compile(
    r"모르겠|모름|잘\s*몰라|생각\s*안\s*나|기억\s*안\s*나|패스|스킵|pass|skip",
    re.I,
)

#: 시도한 흔적. 하나라도 있으면 포기가 아니다 —
#: "잘 모르겠는데 지연 시간 아닐까요?" 는 답변이지 포기가 아니다.
_ATTEMPT_RE = re.compile(r"지만|는데|근데|그런데|다만|아닐까|같아요|같습니다|듯")


def looks_stuck(answer: str | None) -> bool:
    """
    '모르겠다' 류의 포기 의사인지. **규칙은 코드가 정한다** — 이 모듈의 원칙대로
    의도 판별을 LLM 에 맡기지 않는다 (왕복 비용도, 비결정성도 늘기 때문이다).

    짧고 · 시도한 흔적이 없고 · 포기 표현이 있을 때만 참이다.
    빈 답변은 _empty_answer 가 따로 다루므로 여기서 가로채지 않는다.
    """
    text = (answer or "").strip()
    if not text or len(text) > GIVE_UP_MAX_CHARS:
        return False
    if _ATTEMPT_RE.search(text):
        return False
    return bool(_GIVE_UP_RE.search(text))


#: 부분 포기 절을 가르는 구분자. 한국어 답변은 «X는 모르겠고, Y는 …» 처럼
#: 연결어미로 이어 붙는다 — 문장 부호만 보면 한 덩어리로 뭉쳐서 못 가른다.
_CLAUSE_SPLIT_RE = re.compile(
    r"(?<=[고요다지만은])\s*[,·]\s*|\s*[.?!]\s+|\n+|(?<=는데)\s+|(?<=지만)\s+"
)

#: 포기 절을 뺀 나머지가 이만큼은 돼야 «부분» 포기다. 이보다 짧으면 답한 것이
#: 없다는 뜻이라 통째 포기와 같다 — 그쪽은 「모르겠어요」 버튼과 코칭 경로가 받는다.
GIVE_UP_REMAINDER_MIN = 8

#: 과녁이 될 수 없는 지시어. 「이건」 을 결손 목록에 올리면 화면이 «아직 안 나온 것:
#: 이건» 이라고 쓴다 — 무엇을 열어 주는지 아무도 모르는 힌트가 된다.
_VAGUE_TOPICS = frozenset({
    "이건", "그건", "저건", "이거", "그거", "저거", "이것", "그것", "저것",
    "이 부분", "그 부분", "나머지", "뒤", "앞", "거기",
})

#: 포기 표현에서 **주제만** 남기기 위해 걷어 내는 꼬리.
_GIVE_UP_TAIL_RE = re.compile(
    # 긴 조사부터. 짧은 「는」 이 먼저 걸리면 "…에 대해서" 가 주제에 남는다.
    r"(에\s*대해서?는?|에\s*대한|쪽은|부분은|까지는|은|는|이|가|을|를)?\s*"
    r"(잘\s*)?(모르겠|모름|몰라|생각\s*안\s*나|기억\s*안\s*나)[가-힣\s]*$"
)


def partial_giveup_topic(answer: str | None) -> str:
    """
    '**X 는 모르겠고** Y 는 …' 에서 스스로 모른다고 밝힌 **X** 를 뽑는다. 없으면 "".

    `looks_stuck` 은 통째로 포기한 짧은 답만 잡는다. 그런데 실제 답변은 «한쪽은
    모르겠고 한쪽은 이렇다» 로 온다 — 그러면 판정 경로로 가서, 판정은 발표자가
    이미 모른다고 밝힌 것을 **또 비슷하게 되묻는다.** 그게 이번에 지적받은 자리다.

    **규칙은 코드가 정한다** (이 모듈의 원칙). 절로 갈라서, 포기 표현이 있고
    시도한 흔적이 없는 절만 포기로 보고 그 절의 주제를 남긴다. 나머지 절은
    그대로 채점 대상이다 — 모른다고 밝혔다는 이유로 답한 부분까지 버리지 않는다.

    통째 포기(`looks_stuck`)는 여기서 잡지 않는다. 그쪽은 코칭 경로가 이미 받는다.
    """
    text = (answer or "").strip()
    if not text or looks_stuck(text):
        return ""

    clauses = [c.strip(" ,·") for c in _CLAUSE_SPLIT_RE.split(text) if c and c.strip(" ,·")]
    # 절이 하나뿐이면 «나머지» 가 없다 — 부분 포기가 아니라 통째 포기이거나 답변이다.
    if len(clauses) < 2:
        return ""

    given_up = [c for c in clauses if _GIVE_UP_RE.search(c)]
    # 남은 절이 답변 구실을 못 하면 «부분» 이 아니라 통째 포기다. 그걸 여기서
    # 잡으면 채점할 것도 없는 답에 과녁만 세우게 된다.
    remainder = " ".join(c for c in clauses if c not in given_up)
    if not given_up or len(remainder) < GIVE_UP_REMAINDER_MIN:
        return ""

    for clause in given_up:
        topic = _GIVE_UP_TAIL_RE.sub("", clause).strip(" ,·")
        # 주제를 못 건지거나 지시어뿐이면 «무엇을» 모르는지 알 수 없다. 그때는
        # 안 잡는 편이 낫다 — 빈 과녁을 세우면 되묻기가 도리어 막연해진다.
        if topic and topic != clause and topic not in _VAGUE_TOPICS:
            return _clip(topic)
    return ""


def _giveup_block(topic: str) -> str:
    """부분 포기가 있을 때 판정 프롬프트에 붙는 블록."""
    if not topic:
        return ""
    return (
        "\n\n## 발표자가 스스로 모른다고 밝힌 부분\n"
        f"「{topic}」\n"
        "- **이걸 그대로 되묻지 마라.** 이미 모른다고 했다. 같은 걸 또 물으면 대화가 멈춘다.\n"
        "- 나머지 답변은 평소대로 채점하라. 솔직히 밝힌 것 자체로 깎지 마라.\n"
        "- react 는 답한 쪽을 먼저 인정하고, 모른다고 한 쪽은 방향을 짚어 준다.\n"
        f"- missing_points 에는 「{topic}」 를 적어라 — 화면이 그걸로 힌트를 열어 준다."
    )


#: 되물음의 표지 — **질문 자체**를 못 알아들었다는 말. 답의 내용이 아니라
#: 질문에 대해 말하고 있는 모양만 잡는다.
_ASKS_BACK_RE = re.compile(
    r"무슨\s*(뜻|말|의미|말씀)|어떤\s*(뜻|의미)|"
    r"질문(이|을)?\s*(무엇|뭐|무슨|이해|잘|다시)|"
    r"다시\s*(한\s*번\s*)?(말씀|설명|여쭤|물어|얘기|이야기|짚어)|"
    r"(뭘|무엇을|어떤\s*걸)\s*(물어|묻는|여쭤)|"
    r"이해(가|를)?\s*(잘\s*)?(안|못)"
)

#: 되물음으로 볼 답변의 최대 길이. 이보다 길면 «답하면서 덧붙여 물은 것» 이라
#: 채점할 내용이 들어 있다. **놓치는 쪽이 안전하다** — 오탐하면 맞는 답을
#: 채점하지 않고 질문만 다시 쓴다 (_ATTEMPT_RE 가 지키던 경계와 같은 규율).
ASKS_BACK_MAX_CHARS = 40


def asks_back(answer: str | None) -> bool:
    """
    답이 아니라 **질문 자체를 되묻는** 말인가. 규칙은 코드가 정한다.

    "깊은 수면 아닐까요?" 는 자신 없는 **답**이지 되물음이 아니다 — 물음표가
    아니라 «질문에 대해 말하고 있는가» 로 가른다. 되물음이면 채점하지 않고
    같은 질문을 더 쉬운 말로 다시 쓴다 (coach_stuck 의 clarify 단계).
    """
    text = (answer or "").strip()
    if not text or len(text) > ASKS_BACK_MAX_CHARS:
        return False
    return bool(_ASKS_BACK_RE.search(text))


def _coach_stage(question: Question, turns: list[QaTurn]) -> str:
    """
    이번 막힘에 몇 번째로 응할지. **프론트가 보내지 않는다** — 저장된 옛 세션에는
    그 필드가 없고, 질문이 바뀔 때 초기화하는 것도 빠뜨리기 쉽다. 이 질문에 대한
    앞선 포기 횟수만 세면 상태 없이 같은 답이 나온다.

    history 전체를 본다 (HISTORY_TURNS 로 자르기 전) — 앞 단계를 잊으면
    같은 되물음을 반복하게 된다.
    """
    # 조인 키는 question_id 다. 문면으로 세면 안 된다 — 프론트가 2턴째부터
    # 원래 질문이 아니라 직전 후속 질문을 그 턴의 question 으로 적기 때문에
    # (app.js submitLiveAnswer), 한 번 답을 시도한 뒤 막힌 사람은 prior 가
    # 영영 0 이 되어 되물음만 무한히 받는다.
    # id 를 안 보내는 옛 클라이언트만 문면 비교(strip)로 폴백한다.
    asked_id = (question.id or "").strip()
    asked = question.question.strip()

    def _same_question(turn: QaTurn) -> bool:
        turn_id = (turn.question_id or "").strip()
        if asked_id and turn_id:
            return turn_id == asked_id
        return turn.question.strip() == asked

    # 포기는 **의사**다. 답변 글에서 역추정(looks_stuck)만 하면 뭔가 써 놓고
    # 「모르겠어요」를 누른 턴을 놓쳐 explain 단계로 못 올라간다.
    prior = sum(
        1 for t in turns
        if _same_question(t) and (t.gave_up or looks_stuck(t.answer))
    )
    # 0: 위치(자료 인용 + 둘 중 하나) · 1: 발판(빈칸, LLM 없음) · 2+: 해설.
    # 답 공개까지 간접 힌트 두 번 — MVP_SPEC §5.3 "세 번째에 자기 말로".
    if prior >= 2:
        return "explain"
    return "scaffold" if prior == 1 else "narrow"


COACH_SYSTEM_PROMPT = """당신은 발표 코치다. 발표자가 방금 막혔다.

절대 나무라지 마라. 한 문장으로 안심시키고 바로 도움으로 넘어간다.
react 는 **막힌 상황에 맞는 말**이다 — 발표자는 답을 못 했다. "핵심을 잘 짚었다"
같은 빈말 칭찬은 쓰지 마라. 안심과 다음 발걸음만 말한다.

[단계=narrow] 답을 알려 주지 마라. '자료 인용' 이 주어지면 **그 문장에 대해** 둘 중
하나를 고르게 하는 되물음 하나를 쓴다 — "A인가요, B인가요?" 꼴. choices 에 그 두
선택지를 각각 20자 이내로 적는다: 하나는 자료가 말하는 쪽, 하나는 그럴듯한 반대쪽.
인용이 없으면 근거 슬라이드에서 출발해 예/아니오로 답할 수 있을 만큼 좁힌다.
발표자가 스스로 첫 발을 떼게 하는 것이 목적이다.

[단계=explain] 이제 알려 준다. '기대하는 답의 골자' 와 근거 슬라이드, 그리고
발표 때 실제로 한 말을 엮어 "이렇게 답했으면 됐다" 를 설명한다. 자료에 없는
사실을 지어내지 마라. 다음 질문으로 넘어갈 것이므로 되물음은 쓰지 않는다.

[단계=clarify] 발표자는 **포기한 것이 아니라 질문을 못 알아들었다.** 답을 알려
주지 말고, **같은 것을 묻는 같은 질문**을 더 쉬운 말로 다시 써라.
- 묻는 대상을 바꾸지 마라. 쉬운 질문으로 갈아타는 것이 아니라 같은 질문을 푸는 것이다.
- 전문 용어와 겹문장을 걷어내고, 자료의 어느 대목 이야기인지 한 마디로 짚어 준다.
- react 는 "제가 어렵게 물었어요" 쪽이다. 발표자 탓으로 돌리지 마라.

반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마 (단계에 해당하는 키만 채운다):
{
  "react": "안심시키는 한 마디",
  "followup": "narrow 단계에서 쓸 둘 중 하나 되물음 · clarify 단계에서 쓸 다시 쓴 질문 한 문장",
  "choices": ["narrow 단계의 선택지 A", "선택지 B"],
  "explanation": "explain 단계에서 쓸 해설 두세 문장"
}"""


def _clip_explain(text: str) -> str:
    stripped = (text or "").strip()
    if len(stripped) <= QA_EXPLAIN_MAX:
        return stripped
    return stripped[: QA_EXPLAIN_MAX - 1].rstrip() + "…"


_COACH_REACT_FALLBACK = "괜찮아요. 여기서 같이 짚어 볼게요."
#: 포기한 사람에게 나올 수 없는 말. 프롬프트가 금지해도 실 LLM 이 "핵심을 잘 짚으셨어요" 를
#: 냈다 (2026-09-10). 높임 '~셨' 도 여기서 같이 걸린다 (CLAUDE.md §3-1).
_COACH_PRAISE_RE = re.compile(r"잘 짚|정확합니다|정확해요|맞습니다|맞아요|훌륭|잘 하셨|셨어요|셨습니다")


def coach_stuck(
    question: Question | dict,
    *,
    graph: ConceptGraph | dict | None = None,
    alignment: AlignmentDoc | dict | None = None,
    transcript: Transcript | dict | None = None,
    history: list[QaTurn] | list[dict] | None = None,
    context: Context | dict | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
    stage: str = "",
    slidedoc: SlideDoc | dict | None = None,
    memory: MemoryDoc | dict | None = None,
) -> QaJudgement:
    """
    막힌 발표자에게 응한다. 1차는 쉬운 되물음(narrow), 2차는 해설(explain).

    memory(F-25) 가 「이 개념에서 지난번에도 포기했다」 고 하면 1차 되물음(narrow)을 건너뛰고 발판(scaffold)에서
    시작한다 — 지난번에 안 통한 되물음을 같은 넓이로 다시 하지 않는다.

    판정이 아니므로 verdict 는 항상 'unknown' · score 0 이고 passed 는 거짓이다.
    단계는 history 로 서버가 정한다 (_coach_stage).

    `stage` 를 주면 그 단계로 고정한다. 되물음(clarify)이 그 경우다 — 포기가
    아니라 질문을 못 알아들은 것이라, 앞선 포기 횟수로 셀 수 있는 상태가 아니다.
    """
    if isinstance(question, dict):
        question = Question.from_dict(question)
    if isinstance(graph, dict):
        graph = ConceptGraph.from_dict(graph)
    if isinstance(alignment, dict):
        alignment = AlignmentDoc.from_dict(alignment)
    if isinstance(transcript, dict):
        transcript = Transcript.from_dict(transcript)
    if isinstance(slidedoc, dict):
        slidedoc = SlideDoc.from_dict(slidedoc)

    turns = [t if isinstance(t, QaTurn) else QaTurn.from_dict(t) for t in (history or [])]
    ctx = Context() if context is None else (
        Context.from_dict(context) if isinstance(context, dict) else context
    )
    stage = stage if stage in QA_COACH_STAGES and stage else _coach_stage(question, turns)
    memory_cm = _memory_concept(question, memory, graph)
    if stage == "narrow" and memory_cm is not None and memory_cm.stalled and memory_cm.give_ups >= 1:
        stage = "scaffold"
    # 발판 단계는 LLM 을 부르지 않는다 — 골자에서 낱말 하나를 가린 빈칸이 전부다.
    # 재료가 없으면(골자 없음) 이 단을 건너뛰고 해설로 간다.
    if stage == "scaffold":
        scaffold = _scaffold_judgement(question, graph)
        if scaffold is not None:
            return scaffold
        stage = "explain"
    said = "(질문을 못 알아들어 되물었다)" if stage == "clarify" else "(모르겠다고 했다)"

    engine = llm if isinstance(llm, LLMProvider) else get_llm(llm, **(llm_kwargs or {}))
    user = "\n".join([
        f"[단계] {stage}",
        _build_user_prompt(
            question, said, turns, graph, alignment, transcript, ctx, slidedoc=slidedoc
        ),
        *_quote_lines(question),
        "",
        f"기대하는 답의 골자: {question.answer_gist or '(없음)'}",
    ])

    try:
        data = _call_coach(engine, user)
    except JudgeError:
        data = _call_coach(engine, user, extra_system=JSON_RETRY_NUDGE)
    data = _haeyo_data(data)

    react = _clip(str(data.get("react", "") or "")) or _COACH_REACT_FALLBACK
    if _COACH_PRAISE_RE.search(react) or _HONORIFIC_RE.search(react):
        react = _COACH_REACT_FALLBACK
    choices: list[str] = []
    # 폴백은 F-08 이 이미 만들어 둔 것을 쓴다 — 코칭이 빈손으로 끝나면 안 된다
    if stage == "explain":
        followup = ""
        explanation = _clip_explain(str(data.get("explanation", "") or "")) or _clip_explain(
            question.answer_gist or f"{question.label or '이 개념'} 은 자료의 근거 장을 다시 보면 좋아요."
        )
        explanation = _with_citation(explanation, question)
    elif stage == "clarify":
        # 폴백은 **원래 질문 그대로**다. 여기서 힌트로 갈아타면 묻는 대상이 바뀌어,
        # 못 알아들었다고 말한 사람이 다른 질문을 받게 된다.
        followup = _clip(str(data.get("followup", "") or "")) or _clip(question.question)
        explanation = ""
    else:
        followup, choices = _narrow_followup(data, question, graph)
        explanation = ""
        react = _with_quote(react, question)

    label = question.label or "이 개념"
    summary = (
        f"{label} — 질문을 다시 풀어 드렸어요."
        if stage == "clarify"
        else f"{label} — 막힌 지점을 같이 짚었어요."
    )
    return QaJudgement(
        question_id=question.id,
        node_id=question.node_id,
        verdict=QA_VERDICT_FALLBACK,   # 판정이 아니다 — 점수를 매기지 않는다
        score=0,
        react=react,
        summary_sentence=_clip(summary),
        model=engine.name,
        followup=followup,
        hints=build_hint_ladder(question, None),
        coach_stage=stage if stage in QA_COACH_STAGES else "narrow",
        explanation=explanation,
        choices=choices,
        evidence_quote=question.evidence_quote,
        evidence_slide_no=question.evidence_slide_no,
    )


#: 선택형 되물음의 모양. 이게 아니면 LLM 이 넓게 물은 것이라 결정적 문장으로 간다.
_CHOICE_FORM_RE = re.compile(r"(인가요|였나요|있었나요|없었나요|맞나요)[^?]*?(인가요|였나요|있었나요|없었나요|아닌가요)|둘 중")


def _quote_lines(question: Question) -> list[str]:
    """코치 프롬프트에 싣는 자료 인용·발화 인용. 없으면 빈 목록."""
    lines: list[str] = []
    if question.evidence_quote:
        where = f"자료 {question.evidence_slide_no}장" if question.evidence_slide_no else "자료"
        lines += ["", f"자료 인용: {where} — «{question.evidence_quote}»"]
    if question.speech_quote:
        lines.append(f"발표 때 한 말: «{question.speech_quote}»")
    return lines


def _slide_tag(question: Question) -> str:
    return f" (자료 {question.evidence_slide_no}장)" if question.evidence_slide_no else ""


def _distractor_pool(question: Question, graph: ConceptGraph | None) -> list[str]:
    if graph is None:
        return []
    return [n.summary for n in graph.neighbors_of(question.node_id) if n.summary]


def _narrow_followup(data: dict, question: Question, graph: ConceptGraph | None) -> tuple[str, list[str]]:
    """
    위치 단계의 되물음. **둘 중 하나 모양이 아니면 코드 문장으로 간다.**

    LLM 이 choices 2개와 선택형 followup 을 다 줬으면 그것. 하나라도 빠지면 골자를
    가린 빈칸에서 정답·오답을 뽑아 "자료 N장은 «…» 라고 해요. 이 장이 말하는 건
    A 쪽인가요, B 쪽인가요?" 를 만든다. 그것도 안 되면 예전 폴백(F-08 힌트)이다.
    장 번호를 문장에 남긴다 — 화면이 그 번호로 장 그림을 붙인다.
    """
    followup = _clip(str(data.get("followup", "") or ""))
    choices = [_clip(str(c)) for c in (data.get("choices") or []) if str(c).strip()][:2]
    if not question.evidence_quote:
        # 인용이 없는 옛 질문 — 선택형을 강제할 재료가 없다. 예전 그대로 LLM 되물음이고,
        # 선택지는 둘 다 왔을 때만 싣는다.
        fallback = _clip(question.hint or f"{question.label or '이 개념'} 이 왜 필요했는지부터 떠올려 볼까요?")
        return (followup or fallback), (choices if len(choices) == 2 else [])
    if followup and len(choices) == 2 and _CHOICE_FORM_RE.search(followup):
        if question.evidence_slide_no and "장" not in followup:
            followup = _clip(followup + _slide_tag(question))
        return followup, choices
    _, answer, distractor = mask_gist(question.answer_gist, question.label, _distractor_pool(question, graph))
    if answer and distractor and question.evidence_quote:
        where = f"자료 {question.evidence_slide_no}장은" if question.evidence_slide_no else "자료는"
        pair = sorted([answer, distractor])
        text = f"{where} «{question.evidence_quote}» 라고 해요. 이 장이 말하는 건 '{pair[0]}' 쪽인가요, '{pair[1]}' 쪽인가요?"
        return _clip(text), pair
    fallback = _clip(question.hint or f"{question.label or '이 개념'} 이 왜 필요했는지부터 떠올려 볼까요?")
    return fallback, []


def _with_quote(react: str, question: Question) -> str:
    """안심 한 마디 뒤에 자료 인용을 붙인다 — 상한 안에 들어갈 때만."""
    if not question.evidence_quote:
        return react
    where = f"자료 {question.evidence_slide_no}장은" if question.evidence_slide_no else "자료는"
    joined = f"{react} {where} 이렇게 말해요: «{question.evidence_quote}»"
    return joined if len(joined) <= QA_TEXT_MAX else react


def _with_citation(explanation: str, question: Question) -> str:
    """해설 끝에 출처를 **반드시** 단다: 자료 N장 인용, 발표 때 한 말. 상한 안에서."""
    parts: list[str] = []
    if question.evidence_quote and question.evidence_quote not in explanation:
        where = f"자료 {question.evidence_slide_no}장" if question.evidence_slide_no else "자료"
        parts.append(f"{where}: «{question.evidence_quote}»")
    if question.speech_quote and question.speech_quote not in explanation:
        parts.append(f"발표에서는 «{question.speech_quote}» 라고 말했어요.")
    if not parts:
        return explanation
    tail = " — " + " ".join(parts)
    room = QA_EXPLAIN_MAX - len(tail)
    if room < 40:
        return explanation
    body = explanation if len(explanation) <= room else explanation[: room - 1].rstrip() + "…"
    return body + tail


def _scaffold_judgement(question: Question, graph: ConceptGraph | None) -> QaJudgement | None:
    """
    발판 단계 — LLM 없이. 골자에서 낱말 하나를 가린 빈칸과 선택지 둘.
    골자가 없어 빈칸을 못 만들면 None (호출자가 해설로 넘긴다).
    """
    masked, answer, distractor = mask_gist(
        question.answer_gist, question.label, _distractor_pool(question, graph)
    )
    if not masked:
        return None
    choices = sorted([answer, distractor]) if distractor else []
    followup = f"빈칸을 채워 보세요: {masked}"
    if choices:
        followup += f" — '{choices[0]}' 인가요, '{choices[1]}' 인가요?"
    followup += _slide_tag(question)
    return QaJudgement(
        question_id=question.id,
        node_id=question.node_id,
        verdict=QA_VERDICT_FALLBACK,
        score=0,
        react="괜찮아요. 한 칸만 채우면 돼요.",
        summary_sentence=_clip(f"{question.label or '이 개념'} — 빈칸으로 발판을 놓았어요."),
        model="",
        followup=_clip(followup),
        hints=build_hint_ladder(question, None),
        coach_stage="scaffold",
        choices=choices,
        evidence_quote=question.evidence_quote,
        evidence_slide_no=question.evidence_slide_no,
    )


def _empty_answer(question: Question, round_no: int = 1) -> QaJudgement:
    """
    빈 답변은 LLM 을 부르지 않는다. 판정할 내용이 없는데 비용을 태울 이유가 없다.

    그래도 followup·hints 는 채워 나간다 — 첫 마디를 못 뗀 사람이야말로
    되묻기와 힌트가 필요한 사람이기 때문이다. 폴백이 유일한 공급원이다.
    """
    return _normalize(
        {"verdict": QA_VERDICT_FALLBACK, "react": EMPTY_ANSWER_REACT},
        question,
        model="",
        round_no=round_no,
    )


def _round_no(prior_answers: list[str] | None) -> int:
    """
    이번이 이 질문의 몇 번째 답변인지 (1부터).

    프론트가 보내 주는 '앞서 낸 답들' 을 세면 상태 없이 같은 답이 나온다
    (`_coach_stage` 와 같은 규율). 포기 턴의 자리 표시자는 프론트가 이미
    걸러서 보내지만, 빈 문자열은 여기서도 한 번 더 버린다.
    """
    return 1 + sum(1 for text in (prior_answers or []) if (text or "").strip())


# ---------------------------------------------------------------------------
# LLM 호출
# ---------------------------------------------------------------------------

def _complete_json(engine: LLMProvider, system: str, user: str) -> dict:
    raw = engine.complete(
        system=system,
        user=user,
        temperature=0.2,
        max_tokens=MAX_TOKENS,
        json_mode=True
    )
    try:
        return extract_json_object(raw)
    except ValueError as e:
        raise JudgeError(f"LLM 응답에서 판정 JSON 을 찾지 못했습니다: {e}") from e


def _call(engine: LLMProvider, user: str, *, extra_system: str = "") -> dict:
    """판정 호출. system 은 판정 스키마 하나뿐이다."""
    return _complete_json(engine, SYSTEM_PROMPT + extra_system, user)


def _call_coach(engine: LLMProvider, user: str, *, extra_system: str = "") -> dict:
    """
    막힘 코칭 호출. **판정 시스템 프롬프트를 이고 가지 않는다.**

    둘을 붙이면 system 에 출력 스키마가 두 개(verdict/score · react/followup/explanation)
    실려 모델이 어느 쪽으로 답할지 모호해진다. 판정 스키마로 답해 오면 코칭 문장이
    전부 비어 조용히 F-08 폴백으로 대체되고, 화면은 멀쩡해 보여서 알아채기 어렵다.
    """
    return _complete_json(engine, COACH_SYSTEM_PROMPT + extra_system, user)


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------

def judge_answer(
    question: Question | dict,
    answer: str,
    *,
    graph: ConceptGraph | dict | None = None,
    alignment: AlignmentDoc | dict | None = None,
    transcript: Transcript | dict | None = None,
    history: list[QaTurn] | list[dict] | None = None,
    context: Context | dict | None = None,
    give_up: bool = False,
    prior_answers: list[str] | None = None,
    hints_shown: list[str] | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
    slidedoc: SlideDoc | dict | None = None,
    memory: MemoryDoc | dict | None = None,
) -> QaJudgement:
    """
    Question + 답변 (+선택 ConceptGraph·AlignmentDoc·Transcript·history·Context·MemoryDoc)
    → QaJudgement.

    memory(F-25) 를 주면 이 개념의 지난 리허설 기억(판정·빠진 점)이 판정 프롬프트에 실려, 지난번에 빠졌던 점이
    이번엔 나왔는지 알아본다. 포기하면 코칭 시작 단계도 기억이 정한다 (coach_stuck). 안 주면 예전과 같다.

    give_up=True 이거나 답변이 포기로 보이면(looks_stuck) 판정하지 않고
    coach_stuck() 으로 넘긴다 — 모르겠다는 사람에게 점수를 매길 이유가 없다.

    판정은 LLM 이 하지만 계약은 코드가 지킨다: verdict 는 4-class 안,
    score 는 0~100, node_id 는 질문에서 승계, react·summary_sentence 는 항상 채워진다.
    빈 답변은 LLM 없이 'unknown' 으로 즉시 돌려준다.

    graph 를 주면 개념의 parent 경로(트리 뷰)와 relates 이웃(그래프 뷰)이 함께 실려,
    "옆 개념과의 관계를 짚었는가" 까지 볼 수 있다. transcript 를 주면 근거 장의
    실제 발화가 붙어 "발표 때와 지금 답이 다른가" 를 대조할 수 있다.

    history 는 프론트가 보내는 한글 키({질문, 답변, 판정})와 영문 키 둘 다 받는다.
    """
    if isinstance(question, dict):
        question = Question.from_dict(question)
    if not question.question.strip():
        raise JudgeError("판정할 질문이 비어 있습니다. F-08 결과를 먼저 확인하세요.")

    # 이 질문의 몇 번째 답변인가. 되묻기 단계와 대화의 출구(mastered)가 여기 달렸다.
    round_no = _round_no(prior_answers)

    # 「모르겠어요」 버튼은 답이 비어 있어도 코칭으로 간다 — 빈 답 검사가 먼저면
    # 버튼을 누른 사람이 "아직 답변이 없습니다" 를 받는다 (2026-09-10 실측).
    if not give_up and not (answer or "").strip():
        return _empty_answer(question, round_no)

    # 포기는 판정하지 않는다. 버튼(give_up)이든 타이핑(looks_stuck)이든 같은 곳으로 간다.
    # 되물음도 판정하지 않는다 — 「질문이 무슨 뜻인가요?」 를 채점하면 못 알아들었다고
    # 말한 사람이 오답으로 기록되고, 화면은 답을 안 준 채 되묻기만 한 칸 더 간다.
    # **버튼(give_up)이 먼저다.** 누른 사람의 의사가 글에서 읽은 짐작보다 세다.
    if give_up or looks_stuck(answer):
        return coach_stuck(
            question,
            graph=graph,
            alignment=alignment,
            transcript=transcript,
            history=history,
            context=context,
            llm=llm,
            llm_kwargs=llm_kwargs,
            slidedoc=slidedoc,
            memory=memory,
        )
    if asks_back(answer):
        return coach_stuck(
            question,
            graph=graph,
            alignment=alignment,
            transcript=transcript,
            history=history,
            context=context,
            llm=llm,
            llm_kwargs=llm_kwargs,
            stage="clarify",
            slidedoc=slidedoc,
        )

    if isinstance(graph, dict):
        graph = ConceptGraph.from_dict(graph)
    if isinstance(alignment, dict):
        alignment = AlignmentDoc.from_dict(alignment)
    if isinstance(transcript, dict):
        transcript = Transcript.from_dict(transcript)
    if isinstance(slidedoc, dict):
        slidedoc = SlideDoc.from_dict(slidedoc)

    turns = [
        t if isinstance(t, QaTurn) else QaTurn.from_dict(t)
        for t in (history or [])
    ]

    if context is None:
        ctx = Context()
    elif isinstance(context, dict):
        ctx = Context.from_dict(context)
    else:
        ctx = context

    engine = llm if isinstance(llm, LLMProvider) else get_llm(llm, **(llm_kwargs or {}))
    user = _build_user_prompt(
        question, answer, turns, graph, alignment, transcript, ctx, prior_answers,
        slidedoc=slidedoc, memory_cm=_memory_concept(question, memory, graph),
    )
    # 정답 골자는 판정에도 싣는다 (규칙 3 의 채점 기준). 코칭(coach_stuck)만 갖고
    # 있으면 이지선다 질문에 정답 단답이 와도 모델이 자료 발췌에서 확신을 못 얻어
    # unknown 으로 도망간다 — "얕은 수면이야" 가 '너무 짧다' 로 거부된 실측(2026-08-07).
    # _build_user_prompt 안에 넣지 않는 것은 coach_stuck 이 같은 함수를 쓰면서
    # 골자를 따로 붙이기 때문이다 — 두 번 실리면 안 된다.
    gist = (question.answer_gist or "").strip()
    if gist:
        user += f"\n\n## 기대하는 답의 골자 (채점 기준 — 발표자에게는 보이지 않는다)\n{gist}"
    user += _gist_parts_block(question)

    # 부분 포기 — «X 는 모르겠고 Y 는 …». 판정은 그대로 하되, 스스로 모른다고
    # 밝힌 조각을 또 비슷하게 되묻지 않게 과녁과 넓이를 코드가 정한다.
    giveup_topic = partial_giveup_topic(answer)
    user += _giveup_block(giveup_topic)

    # 힌트는 화면에만 뜨고 판정이 모르면, 힌트를 따라온 답에 코치가 맥락 없이
    # 반응한다 — 화면은 대화처럼 보이는데 판정은 일방향이 된다 (2026-08-07 사용자).
    shown = [str(h).strip() for h in (hints_shown or []) if str(h).strip()]
    if shown:
        user += (
            "\n\n## 발표자에게 보여준 힌트\n"
            + "\n".join(f"- {h}" for h in shown)
            + "\n힌트를 따라온 답이면 그 진전을 인정하고, react 는 힌트와 이어지는 말로 하라."
        )

    # 되묻기 단계. 라운드가 오를수록 질문이 좁아져야 스스로 답에 닿는다 —
    # 같은 넓이로 세 번 물으면 압박이 아니라 반복이고, 사용자는 세 번째에 창을 닫는다.
    #
    # **system 에 싣는다.** 처음엔 user 프롬프트 꼬리에 붙였는데 실 LLM(solar-pro3)이
    # 무시했다 — 2라운드 followup 이 "…유리한 점은 무엇인가요?" 로 나와 1라운드보다
    # 오히려 넓어졌다(2026-08-08 실측). 규칙 9 가 system 에서 "빠진 지점 하나를 콕
    # 집어" 라고 말하는데 단계 지시는 user 꼬리에 있으니, 같은 층위로 안 읽힌 것이다.
    # 모른다고 밝힌 조각은 **한 칸 더 좁혀** 묻는다. 같은 넓이로 다시 물으면
    # 발표자가 방금 못 넘은 벽을 그대로 다시 세우는 것이다.
    tier = qa_probe_tier(round_no)
    if giveup_topic:
        tier = _TIER_NARROWER[tier]
    tier_brief = (
        f"\n\n[되묻기 단계 — {tier}] ({round_no}번째 답변 / 최대 {QA_MAX_ROUNDS}라운드)\n"
        + ("발표자가 일부를 «모르겠다» 고 밝혀서 한 칸 더 좁혔다. 라운드 번호가 아니라"
           " 아래 넓이를 따르라.\n" if giveup_topic else "")
        + f"{_PROBE_TIER_BRIEF[tier]}\n"
        + "이 단계 지시는 규칙 9 보다 우선한다. followup 의 넓이는 여기서 정한다."
    )

    try:
        data = _call(engine, user, extra_system=tier_brief)
    except JudgeError:
        # 파싱 실패는 대부분 그 실행의 출력 문제다. 한 번은 다시 묻고, 또 깨지면 실패로 둔다
        data = _call(engine, user, extra_system=tier_brief + JSON_RETRY_NUDGE)

    # 이 질문이 묻는 것 — 질문·골자·개념의 그래프 자리. 무관 가드가 자료 본문 전체가 아니라 이것과도 대조한다.
    focus_lines = [question.question, question.answer_gist, *question.answer_gist_parts, *_concept_block(question, graph)]
    return _normalize(
        _haeyo_data(data), question, engine.name, round_no,
        followup_tier=tier,
        forced_point=giveup_topic,
        answer=answer,
        # 가드가 대조할 근거 — 프롬프트에 실린 것과 같은 자료·발화·골자.
        evidence="\n".join([
            *focus_lines, *_slide_block(question, slidedoc, graph),
            *_speech_block(question, transcript),
        ]),
        focus="\n".join(focus_lines),
    )
