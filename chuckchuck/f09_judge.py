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

from ._json_text import extract_json_object
from .contracts import (
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
)
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm

MAX_TOKENS = int(os.environ.get("CHUCKCHUCK_JUDGE_MAX_TOKENS", "2048"))

#: history 를 몇 턴까지 프롬프트에 실을지. 앞 턴은 판정에 거의 기여하지 않는데
#: 토큰만 먹는다 — 최근 대화만 맥락으로 준다.
HISTORY_TURNS = int(os.environ.get("CHUCKCHUCK_JUDGE_HISTORY_TURNS", "6"))

#: 프롬프트에 실을 발화 발췌 길이. 이 개념의 근거 장 발화만 붙인다.
SPEECH_EXCERPT_MAX = int(os.environ.get("CHUCKCHUCK_JUDGE_SPEECH_EXCERPT_MAX", "300"))

#: 개념 하나에 붙여 보여 줄 이웃 개념 수.
NEIGHBOR_MAX = 5

#: react 가 비어 돌아왔을 때 채워 넣는 결정적 문구.
#: 프론트가 이걸로 말풍선을 그리므로 비워 둘 수 없다.
_REACT_BY_VERDICT = {
    "good": "네, 그 설명이면 충분합니다.",
    "partial": "절반은 이해했습니다. 나머지가 아직 비어 있어요.",
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

SYSTEM_PROMPT = """당신은 발표 심사위원이다.
방금 던진 질문에 발표자가 답했다. 그 답이 개념을 **실제로 방어했는지** 판정한다.

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
5. missing_points 는 답변에서 빠진 포인트만 적는다. 없으면 빈 배열.
6. score 는 0~100. good 80 이상, partial 40~79, wrong 39 이하가 기준이다.
7. 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마:
{
  "verdict": "partial",
  "score": 55,
  "react": "그 부분은 맞습니다. 다만 왜 그 값을 골랐는지가 빠졌네요.",
  "summary_sentence": "공동 임베딩 정렬 — 개념은 알지만 설계 근거가 얕아요.",
  "missing_points": ["온도 파라미터를 고른 이유"]
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

    parts += ["", "## 이번 답변 — 이것을 판정하라", answer.strip()]
    return "\n".join(parts)


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
    verdict = str(data.get("verdict", "") or "")
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

    return QaJudgement(
        question_id=question.id,
        node_id=question.node_id,
        verdict=verdict,
        score=score,
        react=react,
        summary_sentence=summary,
        missing_points=points,
        model=model,
    )


def _empty_answer(question: Question) -> QaJudgement:
    """빈 답변은 LLM 을 부르지 않는다. 판정할 내용이 없는데 비용을 태울 이유가 없다."""
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
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> QaJudgement:
    """
    Question + 답변 (+선택 ConceptGraph·AlignmentDoc·Transcript·history·Context)
    → QaJudgement.

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
    user = _build_user_prompt(question, answer, turns, graph, alignment, transcript, ctx)

    try:
        data = _call(engine, user)
    except JudgeError:
        # 파싱 실패는 대부분 그 실행의 출력 문제다. 한 번은 다시 묻고, 또 깨지면 실패로 둔다
        data = _call(engine, user, extra_system=JSON_RETRY_NUDGE)

    return _normalize(data, question, engine.name)
