"""
화면으로 내보내는 **질문 사본**의 규칙 — 브리지(`demo/bridge.py`)와 FastAPI 서버(`server/app.py`)가 같은 칸을 뺀다. LLM 을 부르지 않는다.

함정 질문의 틀린 전제·자료의 사실(`trap_premise`)과 그 전제를 바로잡은 기대 답(`answer_gist`·`answer_gist_parts`)은 **채점 기준**이다.
채점은 서버가 제 사본으로 하므로 브라우저에 있을 까닭이 없다 — 있으면 개발자 도구 한 번이 정답이고, 화면의 「답 펼치기」 한 곳만
잘못 그려도 바로잡기 전에 사실이 뜬다 (09-30 WP-J2). 브리지는 그때 사본 규칙을 넣었는데 같은 계약의 FastAPI 서버는 그대로
내보냈다 — 규칙이 한쪽에만 있으면 두 서버가 갈라진다. 그래서 규칙을 여기 한곳에 두고 두 서버가 이것만 부른다.

- `client_questions` — 질문 묶음(QuestionDoc dict)의 화면 사본. 함정 질문은 세 칸을 비우고 `gist_withheld=true` 를 단다.
- `reveal_due` · `reveal_fields` — 뺀 기대 답을 **언제** 판정 응답에 실어 줄지(바로잡았거나·닫혔거나·해설 단계)와 무엇을 실을지.
  「답 보고 다시 말해보기」 는 판정이 아니라 reveal 요청으로 받는다(LLM 없이 `reveal_fields` 만).
- `client_grounds` · `client_judgement` — 판정 근거 줄(grounds, 2026-10-01)의 화면 사본. 함정 질문은 기대 답을 싣기 전까지 사실 줄·빠진 줄을 뺀다.

계약(`contracts.Question`)은 그대로다 — 여기서는 dict 사본만 만들고 질문 객체는 속성으로만 읽는다. F-모듈을 import 하지 않는다.
"""

from __future__ import annotations

#: 함정 질문에서 **화면으로 보내지 않는** 칸.
TRAP_WITHHELD = ("trap_premise", "answer_gist", "answer_gist_parts")


def withheld(question: dict) -> bool:
    """이 질문(dict)의 기대 답을 화면 사본에서 빼는가 — 함정 질문(trap)이거나 코드가 만든 전제를 들고 있다."""
    return bool(question.get("trap")) or bool(question.get("trap_premise"))


def client_question(question: dict) -> dict:
    """질문 하나의 화면 사본. 함정이 아니면 그대로(같은 객체), 함정이면 세 칸을 비운 새 dict 에 `gist_withheld=true`."""
    if not isinstance(question, dict) or not withheld(question):
        return question
    return {**question, "trap_premise": None, "answer_gist": "", "answer_gist_parts": [], "gist_withheld": True}


def client_questions(payload):
    """
    질문 묶음(QuestionDoc dict)의 **화면용 사본** — 함정 질문의 사실이 든 칸(TRAP_WITHHELD)을 비우고 gist_withheld=true 를 단다.
    원본은 그대로 둔다(서버 색인·보관은 원본이 채점 기준이다). 함정 질문이 없거나 모양이 다르면 받은 것을 그대로 돌려준다.
    """
    qs = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(qs, list) or not any(isinstance(q, dict) and withheld(q) for q in qs):
        return payload
    return {**payload, "questions": [client_question(q) for q in qs]}


def reveal_due(question, judgement) -> bool:
    """판정 응답에 뺀 기대 답을 실을 때인가 — 함정 질문이고, 바로잡았거나(통과)·닫혔거나·해설(explain) 단계일 때만."""
    is_trap = bool(getattr(question, "trap", False)) or getattr(question, "trap_premise", None) is not None
    return is_trap and bool(getattr(judgement, "passed", False) or getattr(judgement, "mastered", False)
                            or getattr(judgement, "coach_stage", "") == "explain")


def reveal_fields(question) -> dict:
    """함정 질문을 펼칠 때 판정 응답에 싣는 기대 답·사실 줄 — 화면 사본에서 뺀 것 (`client_questions`)."""
    tp = getattr(question, "trap_premise", None)
    return {"answer_gist": getattr(question, "answer_gist", "") or "",
            "reveal_quote": (getattr(tp, "fact", "") if tp is not None else "") or getattr(question, "evidence_quote", "") or "",
            "reveal_slide_no": (getattr(tp, "slide_no", 0) if tp is not None else 0)
            or getattr(question, "evidence_slide_no", 0) or 0}


def client_grounds(question, grounds: list) -> list:
    """
    판정 근거 줄(`QaJudgement.grounds` dict 목록)의 화면 사본 (2026-10-01). 판정(`f09_judge`)이 이미 정답 누설을 거르지만, 함정 질문은
    화면 사본의 규칙을 한 번 더 건다 — **기대 답을 싣기 전(`reveal_due` 가 아닐 때)** 에는 자료의 사실 줄(trap_premise.fact)을 담은 줄과
    「빠진 줄(missing)」 을 싣지 않는다. 함정의 빠진 것은 곧 바로잡은 사실이라서다. 그 밖의 질문은 그대로 돌려준다.
    """
    if not isinstance(grounds, list):
        return []
    is_trap = bool(getattr(question, "trap", False)) or getattr(question, "trap_premise", None) is not None
    if not is_trap:
        return grounds
    tp = getattr(question, "trap_premise", None)
    fact = ((getattr(tp, "fact", "") if tp is not None else "") or "").strip()
    return [g for g in grounds if isinstance(g, dict) and g.get("role") != "missing"
            and not (fact and (fact in str(g.get("quote", "")) or str(g.get("quote", "")).strip() in fact))]


def client_judgement(question, judgement) -> dict:
    """판정 응답의 화면 사본 — `judgement.to_dict()` 에 기대 답을 실을 때면 싣고(`reveal_due`), 아니면 근거 줄을 거른다(`client_grounds`)."""
    body = judgement.to_dict()
    if reveal_due(question, judgement):
        return {**body, **reveal_fields(question)}
    return {**body, "grounds": client_grounds(question, body.get("grounds") or [])}
