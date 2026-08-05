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

from ._json_text import extract_json_object
from .contracts import (
    QA_COACH_STAGES,
    QA_EXPLAIN_MAX,
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
    Transcript,
    qa_passed,
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
SPEECH_EXCERPT_MAX = int(os.environ.get("CHUCKCHUCK_JUDGE_SPEECH_EXCERPT_MAX", "300"))

#: 개념 하나에 붙여 보여 줄 이웃 개념 수.
NEIGHBOR_MAX = 5

#: react 가 비어 돌아왔을 때 채워 넣는 결정적 문구.
#: 프론트가 이걸로 말풍선을 그리므로 비워 둘 수 없다.
_REACT_BY_VERDICT = {
    "good": "네, 그 설명이면 충분합니다.",
    # '절반' 은 요지를 맞힌 사람에게 과소평가로 읽힌다. 되묻기의 목적은 채점이 아니라
    # 한 걸음 더 끌어내는 것이라, 인정할 것은 인정하고 남은 하나를 가리킨다.
    "partial": "요지는 잡으셨습니다. 한 가지만 더 짚어 주세요.",
    "wrong": "그 부분은 자료와 맞지 않습니다.",
    "unknown": "지금 답변만으로는 판단하기 어렵습니다.",
}

#: summary_sentence 가 비어 돌아왔을 때. 리포트 총평 줄에 그대로 남는다.
_SUMMARY_BY_VERDICT = {
    "good": "{label} — 자기 말로 방어했어요.",
    "partial": "{label} — 방향은 맞지만 근거가 얕아요.",
    "wrong": "{label} — 자료와 어긋나게 설명했어요. 다시 보세요.",
    "unknown": "{label} — 판정을 보류했어요. 다시 답해 보세요.",
}

#: 답변이 비었을 때의 반응. LLM 을 부르지 않고 여기서 끝낸다.
EMPTY_ANSWER_REACT = "아직 답변이 없습니다. 짧아도 좋으니 자기 말로 말해 보세요."

#: followup 이 비어 돌아왔을 때 쓰는 결정적 문장. 실전 코칭은 턴 상한이 없어서
#: 되묻기가 멈추면 사용자가 갇힌다 — LLM 이 빠뜨려도 질문은 반드시 나와야 한다.
#: 빠진 포인트가 있으면 그것을 겨냥하고, 없으면 개념 이름으로 좁힌다.
_FOLLOWUP_BY_POINT = "{point} 에 대해서는 어떻게 보시나요?"
_FOLLOWUP_GENERIC = "{label} 를 뒷받침할 근거를 하나만 더 들어 주시겠어요?"

SYSTEM_PROMPT = """당신은 발표 심사위원이다.
방금 던진 질문에 발표자가 답했다. 그 답이 개념을 **실제로 방어했는지** 판정한다.

되묻기로 여러 번에 나눠 답했다면 **그 답변들을 합쳐서** 본다.
앞 턴에서 이미 말한 것을 다시 빠졌다고 하지 마라 — 마지막 한 마디만 채점하면
좁혀 물은 쪽이 손해를 본다.

verdict 는 다음 넷 중 하나다:
- "good" (설득 완료): 개념을 자기 말로 정확히 설명했다. 근거도 댔다.
- "partial" (부분 인정): 방향은 맞지만 핵심 근거가 빠졌거나 얕다.
- "wrong" (미방어): 자료와 어긋나게 설명했거나 질문을 빗나갔다.
- "unknown" (판정 보류): 답이 너무 짧거나 모호해 판단할 수 없다.

규칙:
1. **내용만 본다.** 말투·문장력·길이로 깎지 마라. 짧아도 맞으면 good 이다.
2. 이 질문이 '함정' 이라면, 발표자가 그 잘못된 전제를 **바로잡았을 때** good 이다.
   함정에 그대로 동의했으면 wrong 이다.
3. react 는 심사위원이 그 자리에서 할 한 마디다. 존댓말, 한 문장.
4. summary_sentence 는 이 개념에 대한 총평 한 문장이다. 리포트에 남는다.
5. missing_points 에는 **통과를 막는 결정적 결손 하나만** 적는다.
   "있으면 더 좋을" 수준은 적지 마라. 부족한 데가 없으면 빈 배열이다.
   여러 개를 늘어놓으면 발표자는 뭘 고쳐야 할지 도리어 모른다.
6. score 는 0~100. **70점 이상이면 통과로 처리된다.**
   - good: 80 이상
   - partial 중 **요지는 맞고 근거만 얕다**: 70~79 — 통과 구간이다
   - partial 중 방향만 겨우 맞다: 40~59
   - wrong: 39 이하
   표현이나 용어가 자료와 달라도 **요지가 같으면 70~79 를 줘라.**
   완벽한 문장을 받아내는 것이 목적이 아니다.
7. followup 은 **이 답으로는 부족할 때 이어서 던질 질문 한 문장**이다.
   - 원래 질문을 **다시 말하지 마라.** 빠진 지점 하나를 콕 집어 물어라.
   - 발표자를 몰아세우지 말고, 답할 수 있게 좁혀 주는 질문이어야 한다.
   - 답이 충분하면 빈 문자열로 둬라.
8. 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마 — **아래 값은 자리 표시자다. 그대로 베끼지 말고 이번 답변을 보고 새로 써라.**
{
  "verdict": "good | partial | wrong | unknown 중 하나",
  "score": 0,
  "react": "<심사위원이 그 자리에서 할 한 마디>",
  "summary_sentence": "<이 개념에 대한 총평 한 문장>",
  "missing_points": ["<답변에서 빠진 포인트>"],
  "followup": "<빠진 지점을 겨냥한 후속 질문 한 문장. 충분하면 빈 문자열>"
}
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
    return lines if len(lines) > 2 else []


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
) -> str:
    """
    질문 → 자료 근거 → 지난 대화 → 이번 답변 순.

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

    parts += _answer_block(answer, prior_answers)
    return "\n".join(parts)


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


def _normalize(data: dict, question: Question, model: str) -> QaJudgement:
    """
    - verdict 가 enum 밖이면 QA_VERDICT_FALLBACK ('unknown')
    - score 없으면 verdict 기본값, 있으면 clamp
    - node_id 는 **질문에서 승계** — LLM 이 다른 값을 줘도 무시한다
      (조인 키가 흔들리면 리포트가 엉뚱한 개념에 총평을 붙인다)
    - react·summary_sentence 는 비면 결정적 문구로 채운다
    """
    # 표기 정규화 — "Good"·" partial " 을 그대로 enum 대조하면 unknown 으로
    # 떨어지는데 score 는 살아 있어 '판정 보류' 배지를 달고 통과하는 모순이 된다.
    verdict = str(data.get("verdict", "") or "").strip().lower()
    if verdict not in QA_VERDICTS:
        verdict = QA_VERDICT_FALLBACK

    raw_score = data.get("score")
    score = QA_VERDICT_SCORES[verdict] if raw_score is None else _clamp_score(raw_score, verdict)

    react = str(data.get("react", "") or "").strip() or _REACT_BY_VERDICT[verdict]
    summary = str(data.get("summary_sentence", "") or "").strip()
    if not summary:
        summary = _SUMMARY_BY_VERDICT[verdict].format(
            label=question.label or question.node_id or "이 개념"
        )

    points = [
        str(p).strip()
        for p in (data.get("missing_points") or [])
        if str(p).strip()
    ]

    judgement = QaJudgement(
        question_id=question.id,
        node_id=question.node_id,
        verdict=verdict,
        score=score,
        react=react,
        summary_sentence=summary,
        missing_points=points,
        model=model,
        followup=_followup(data, question, points, verdict, score),
    )
    # 힌트는 판정을 보고 만든다 — 사용자가 실제로 빠뜨린 것에 반응해야 하기 때문이다.
    # 판정에 함께 실어 보내면 프론트가 추가 왕복 없이 즉시 보여 줄 수 있다.
    judgement.hints = build_hint_ladder(question, judgement)
    return judgement


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
    verdict: str,
    score: int,
) -> str:
    """
    되물을 후속 질문. 정답 계열이면 비운다.

    통과한 답에 되묻는 질문을 남겨 두면 프론트가 그것을 이어 붙여
    "설득 완료" 라고 해 놓고 또 묻는 화면이 된다.
    """
    if qa_passed(verdict, score):
        return ""

    written = _clip(str(data.get("followup", "") or ""))
    if written:
        return written
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


def _coach_stage(question: Question, turns: list[QaTurn]) -> str:
    """
    이번 막힘에 몇 번째로 응할지. **프론트가 보내지 않는다** — 저장된 옛 세션에는
    그 필드가 없고, 질문이 바뀔 때 초기화하는 것도 빠뜨리기 쉽다. 이 질문에 대한
    앞선 포기 횟수만 세면 상태 없이 같은 답이 나온다.

    history 전체를 본다 (HISTORY_TURNS 로 자르기 전) — 앞 단계를 잊으면
    같은 되물음을 반복하게 된다.
    """
    # 문면 완전일치가 아니라 strip 비교다 — 질문을 trim 해 보내는 클라이언트에서
    # prior 가 영영 0 이 되어 explain 단계로 못 올라가는 것을 막는다.
    asked = question.question.strip()
    prior = sum(
        1 for t in turns
        if t.question.strip() == asked and looks_stuck(t.answer)
    )
    return "explain" if prior >= 1 else "narrow"


COACH_SYSTEM_PROMPT = """당신은 발표 코치다. 발표자가 방금 "모르겠다" 고 했다.

절대 나무라지 마라. 한 문장으로 안심시키고 바로 도움으로 넘어간다.

[단계=narrow] 답을 알려 주지 마라. 대신 **원래 질문보다 훨씬 쉬운 되물음** 하나를
쓴다. 자료의 근거 슬라이드에서 출발해 예/아니오나 한 단어로 답할 수 있을 만큼
좁혀라. 발표자가 스스로 첫 발을 떼게 하는 것이 목적이다.

[단계=explain] 이제 알려 준다. '기대하는 답의 골자' 와 근거 슬라이드, 그리고
발표 때 실제로 한 말을 엮어 "이렇게 답했으면 됐다" 를 설명한다. 자료에 없는
사실을 지어내지 마라. 다음 질문으로 넘어갈 것이므로 되물음은 쓰지 않는다.

출력 스키마 (단계에 해당하는 키만 채운다):
{
  "react": "안심시키는 한 마디",
  "followup": "narrow 단계에서 쓸 더 쉬운 되물음 한 문장",
  "explanation": "explain 단계에서 쓸 해설 두세 문장"
}"""


def _clip_explain(text: str) -> str:
    stripped = (text or "").strip()
    if len(stripped) <= QA_EXPLAIN_MAX:
        return stripped
    return stripped[: QA_EXPLAIN_MAX - 1].rstrip() + "…"


_COACH_REACT_FALLBACK = "괜찮아요. 여기서 같이 짚어 볼게요."


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
) -> QaJudgement:
    """
    막힌 발표자에게 응한다. 1차는 쉬운 되물음(narrow), 2차는 해설(explain).

    판정이 아니므로 verdict 는 항상 'unknown' · score 0 이고 passed 는 거짓이다.
    단계는 history 로 서버가 정한다 (_coach_stage).
    """
    if isinstance(question, dict):
        question = Question.from_dict(question)
    if isinstance(graph, dict):
        graph = ConceptGraph.from_dict(graph)
    if isinstance(alignment, dict):
        alignment = AlignmentDoc.from_dict(alignment)
    if isinstance(transcript, dict):
        transcript = Transcript.from_dict(transcript)

    turns = [t if isinstance(t, QaTurn) else QaTurn.from_dict(t) for t in (history or [])]
    ctx = Context() if context is None else (
        Context.from_dict(context) if isinstance(context, dict) else context
    )
    stage = _coach_stage(question, turns)

    engine = llm if isinstance(llm, LLMProvider) else get_llm(llm, **(llm_kwargs or {}))
    user = "\n".join([
        f"[단계] {stage}",
        _build_user_prompt(question, "(모르겠다고 했다)", turns, graph, alignment, transcript, ctx),
        "",
        f"기대하는 답의 골자: {question.answer_gist or '(없음)'}",
    ])

    try:
        data = _call(engine, user, extra_system="\n\n" + COACH_SYSTEM_PROMPT)
    except JudgeError:
        data = _call(engine, user, extra_system="\n\n" + COACH_SYSTEM_PROMPT + JSON_RETRY_NUDGE)

    react = _clip(str(data.get("react", "") or "")) or _COACH_REACT_FALLBACK
    # 폴백은 F-08 이 이미 만들어 둔 것을 쓴다 — 코칭이 빈손으로 끝나면 안 된다
    if stage == "explain":
        followup = ""
        explanation = _clip_explain(str(data.get("explanation", "") or "")) or _clip_explain(
            question.answer_gist or f"{question.label or '이 개념'} 은 자료의 근거 장을 다시 보면 좋아요."
        )
    else:
        followup = _clip(str(data.get("followup", "") or "")) or _clip(
            question.hint or f"{question.label or '이 개념'} 이 왜 필요했는지부터 떠올려 볼까요?"
        )
        explanation = ""

    return QaJudgement(
        question_id=question.id,
        node_id=question.node_id,
        verdict=QA_VERDICT_FALLBACK,   # 판정이 아니다 — 점수를 매기지 않는다
        score=0,
        react=react,
        summary_sentence=_clip(f"{question.label or '이 개념'} — 막힌 지점을 같이 짚었어요."),
        model=engine.name,
        followup=followup,
        hints=build_hint_ladder(question, None),
        coach_stage=stage if stage in QA_COACH_STAGES else "narrow",
        explanation=explanation,
    )


def _empty_answer(question: Question) -> QaJudgement:
    """
    빈 답변은 LLM 을 부르지 않는다. 판정할 내용이 없는데 비용을 태울 이유가 없다.

    그래도 followup·hints 는 채워 나간다 — 첫 마디를 못 뗀 사람이야말로
    되묻기와 힌트가 필요한 사람이기 때문이다. 폴백이 유일한 공급원이다.
    """
    return _normalize(
        {"verdict": QA_VERDICT_FALLBACK, "react": EMPTY_ANSWER_REACT},
        question,
        model="",
    )


# ---------------------------------------------------------------------------
# LLM 호출
# ---------------------------------------------------------------------------

def _call(engine: LLMProvider, user: str, *, extra_system: str = "") -> dict:
    raw = engine.complete(
        system=SYSTEM_PROMPT + extra_system,
        user=user,
        temperature=0.2,
        max_tokens=MAX_TOKENS,
        json_mode=True
    )
    try:
        return extract_json_object(raw)
    except ValueError as e:
        raise JudgeError(f"LLM 응답에서 판정 JSON 을 찾지 못했습니다: {e}") from e


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
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> QaJudgement:
    """
    Question + 답변 (+선택 ConceptGraph·AlignmentDoc·Transcript·history·Context)
    → QaJudgement.

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

    if not (answer or "").strip():
        return _empty_answer(question)

    # 포기는 판정하지 않는다. 버튼(give_up)이든 타이핑(looks_stuck)이든 같은 곳으로 간다.
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
        )

    if isinstance(graph, dict):
        graph = ConceptGraph.from_dict(graph)
    if isinstance(alignment, dict):
        alignment = AlignmentDoc.from_dict(alignment)
    if isinstance(transcript, dict):
        transcript = Transcript.from_dict(transcript)

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
        question, answer, turns, graph, alignment, transcript, ctx, prior_answers
    )

    try:
        data = _call(engine, user)
    except JudgeError:
        # 파싱 실패는 대부분 그 실행의 출력 문제다. 한 번은 다시 묻고, 또 깨지면 실패로 둔다
        data = _call(engine, user, extra_system=JSON_RETRY_NUDGE)

    return _normalize(data, question, engine.name)
