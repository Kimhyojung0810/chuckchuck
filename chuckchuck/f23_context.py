"""
[F-23] 자료를 올리면 발표 상황을 추정한다 — "이 자료는 업무 보고 같아요, 맞나요?"

사용자 제안(2026-09-12): PPT 가 올라왔을 때 맞춤으로 제안. 지금은 `#/new` 폼에서 사용자가 상황을
직접 고르고, 안 고르면 범용 발표로 흘러가 페르소나·채점표 가중치가 전부 기본값이 된다.

1단(여기): **결정론 규칙**. 장 제목(×3)·본문에서 상황별 신호 낱말을 세고, 신호가 충분히 몰리면
그 상황을 제안한다. 호출 0, 즉시. 틀려도 사용자가 고친다 — 그래서 자동 확정하지 않고 confidence 와
근거(몇 장의 어떤 낱말)를 같이 준다. 신호가 약하면 situation="" (미정) 으로 돌려주고 화면은 아무것도 안 채운다.
2단(LLM, 미정일 때만)은 아직 없다 — 동의 세션에서 추정 vs 사용자 최종값 일치율을 본 뒤 결정한다.
설계: docs/plan/deck-tailored-suggestions.plan.md
"""
from __future__ import annotations

import re

from .contracts import ContextSuggestion, SlideDoc

#: 상황별 신호 낱말. 장 제목에 있으면 3점, 본문에 있으면 1점. 한 장에서 같은 낱말은 한 번만 센다.
SIGNALS: dict[str, tuple[str, ...]] = {
    "school_project": ("참고문헌", "선행 연구", "연구", "실험", "가설", "논문", "방법론", "데이터셋", "분석 결과",
                       "교수", "과제", "고찰", "결론 및", "reference", "related work"),
    "product_launch": ("가격", "요금", "출시", "런칭", "고객", "구매", "경쟁", "시장", "제품", "서비스 소개",
                       "기능 소개", "체험", "사전 예약", "beta", "pricing"),
    "work_report": ("현황", "실적", "진행률", "이슈", "요청 사항", "요청", "계획", "일정", "분기", "kpi", "보고",
                    "리스크", "예산", "의사결정", "결정 필요", "액션 아이템", "다음 단계"),
    "casual_peer": ("회고", "공유", "데모", "삽질", "팁", "시행착오", "해봤", "우리 팀", "같이", "코드", "레포",
                    "retro", "lessons learned"),
}
#: 사람이 읽는 라벨 (rubric_v3.SITUATIONS 와 같은 뜻).
LABELS: dict[str, str] = {
    "school_project": "학교 프로젝트 (교수 대상)",
    "product_launch": "신제품 설명 (대중 대상)",
    "work_report": "업무 보고 (상사 대상)",
    "casual_peer": "동료 간 캐주얼 PR",
}
#: 제안하려면 1위 상황이 이만큼은 모여야 하고, 전체 신호 중 이 비율은 차지해야 한다.
MIN_HITS = 2
MIN_SHARE = 0.4
TITLE_WEIGHT = 3


def _hits(text: str, words: tuple[str, ...]) -> list[str]:
    low = (text or "").lower()
    return [w for w in words if w.lower() in low]


def score_slidedoc(doc: SlideDoc) -> tuple[dict[str, int], list[dict]]:
    """상황별 점수와, 근거가 된 (장 번호, 낱말, 어디서) 목록."""
    scores = {k: 0 for k in SIGNALS}
    evidence: list[dict] = []
    for slide in doc.slides:
        title = slide.title or ""
        body = slide.raw_text or ""
        for situation, words in SIGNALS.items():
            seen: set[str] = set()
            for w in _hits(title, words):
                scores[situation] += TITLE_WEIGHT
                seen.add(w)
                evidence.append({"slide_no": slide.slide_no, "word": w, "where": "title", "situation": situation})
            for w in _hits(body, words):
                if w in seen:
                    continue
                scores[situation] += 1
                evidence.append({"slide_no": slide.slide_no, "word": w, "where": "body", "situation": situation})
    return scores, evidence


def _why(evidence: list[dict], situation: str, limit: int = 3) -> str:
    """사람이 읽는 근거. 제목 신호를 먼저, 장마다 하나씩 — 한 장의 낱말 셋보다 세 장의 낱말 하나씩이 더 설득력 있다."""
    picked = sorted((e for e in evidence if e["situation"] == situation),
                    key=lambda e: (e["where"] != "title", e["slide_no"]))
    seen: set[int] = set()
    out = []
    for e in picked:
        if e["slide_no"] in seen:
            continue
        seen.add(e["slide_no"])
        out.append(f"{e['slide_no']}장 '{e['word']}'")
        if len(out) == limit:
            break
    return " · ".join(out)


def suggest_context(doc: SlideDoc | dict) -> ContextSuggestion:
    """SlideDoc → ContextSuggestion. 신호가 약하면 situation 이 빈 문자열이다 — 화면은 그때 아무것도 안 채운다."""
    if isinstance(doc, dict):
        doc = SlideDoc.from_dict(doc)
    scores, evidence = score_slidedoc(doc)
    total = sum(scores.values())
    top, top_score = max(scores.items(), key=lambda kv: kv[1])
    share = top_score / total if total else 0.0
    if top_score < MIN_HITS or share < MIN_SHARE:
        return ContextSuggestion(situation="", audience="", confidence=round(share, 2) if total else 0.0,
                                 why="자료만으로는 상황을 정하기 어려워요", scores=scores)
    return ContextSuggestion(
        situation=top, audience=LABELS[top].split("(")[-1].rstrip(")").replace(" 대상", "").strip(),
        confidence=round(share, 2), why=_why(evidence, top), scores=scores,
    )


_SITUATION_RE = re.compile(r"^[a-z_]+$")


def is_situation_key(text: str) -> bool:
    return bool(_SITUATION_RE.match(text or "")) and text in SIGNALS


# ---------------------------------------------------------------------------
# [F-23 · 내용 제안] 이 청중이 기대하는데 자료에 없는 것 — 결정론 1단 (docs/plan/deck-tailored-suggestions.plan.md §2)
# ---------------------------------------------------------------------------

#: 상황별 「청중이 기대하는 것」. (키, 화면 라벨, 신호 낱말). 제목에 있으면 강한 신호, 본문 두 곳 이상이면 있음, 한 곳이면 약함.
EXPECTATIONS: dict[str, tuple[tuple[str, str, tuple[str, ...]], ...]] = {
    "school_project": (
        ("problem", "문제 정의", ("문제", "배경", "동기", "목적", "필요성")),
        ("method", "방법", ("방법", "방법론", "설계", "절차", "실험")),
        ("evidence", "근거·출처", ("근거", "출처", "참고문헌", "논문", "데이터", "연구")),
        ("result", "결과 수치", ("결과", "수치", "정확도", "%", "표", "그래프")),
        ("limit", "한계", ("한계", "제한", "향후", "개선점", "limitation")),
        ("prior", "선행 연구 대비 차이", ("선행", "기존", "대비", "차이", "비교")),
    ),
    "product_launch": (
        ("who", "누구의 어떤 문제", ("고객", "사용자", "문제", "불편", "페인")),
        ("diff", "차별점·비교", ("차별", "비교", "경쟁", "대비", "유일")),
        ("price", "가격·조건", ("가격", "요금", "무료", "조건", "플랜")),
        ("cta", "다음 행동", ("신청", "구매", "체험", "예약", "문의", "다운로드")),
        ("caveat", "안 되는 경우", ("제한", "지원하지", "안 되", "주의", "예외")),
    ),
    "work_report": (
        ("status", "목표 대비 현황(수치)", ("현황", "진행률", "목표", "달성", "%", "실적")),
        ("issue", "이슈와 원인", ("이슈", "문제", "원인", "지연", "장애")),
        ("next", "다음 행동과 기한", ("계획", "다음", "일정", "기한", "액션")),
        ("ask", "필요한 자원·결정 요청", ("요청", "결정", "승인", "필요", "예산", "인력")),
        ("risk", "리스크", ("리스크", "위험", "대비", "우려")),
    ),
    "casual_peer": (
        ("what", "무엇을 만들었나", ("만들", "구현", "개발", "결과물", "데모")),
        ("how", "어떻게(구조)", ("구조", "아키텍처", "흐름", "설계", "코드")),
        ("lesson", "시행착오", ("시행착오", "삽질", "실패", "배운", "교훈")),
        ("repro", "재현 방법", ("재현", "설치", "실행", "레포", "링크", "명령")),
        ("together", "같이 할 것", ("같이", "함께", "다음에", "제안", "협업")),
    ),
}
#: '있음' 으로 보는 본문 신호 수 (제목 신호는 하나면 있음).
PRESENT_MIN_BODY_HITS = 2


def deck_gaps(doc: SlideDoc | dict, situation: str) -> dict:
    """SlideDoc + 상황 → 기대 항목별 있음/약함/없음과 장 번호. 결정론, 호출 0.

    LLM 2단(항목이 실제로 그 장에서 다뤄졌는지)은 표본이 생기면 붙인다. 지금은 낱말 신호라 "있음" 이 과대평가될 수 있으므로
    화면(Festa 뒤)은 '없음' 을 먼저 보여 주고 '있음' 은 근거 장을 같이 낸다."""
    if isinstance(doc, dict):
        doc = SlideDoc.from_dict(doc)
    expects = EXPECTATIONS.get(situation or "", ())
    items = []
    for key, label, words in expects:
        title_hits: list[tuple[int, str]] = []
        body_hits: list[tuple[int, str]] = []
        for slide in doc.slides:
            for w in _hits(slide.title or "", words):
                title_hits.append((slide.slide_no, w))
            for w in _hits(slide.raw_text or "", words):
                body_hits.append((slide.slide_no, w))
        hits = title_hits + body_hits
        if title_hits or len({n for n, _ in body_hits}) >= PRESENT_MIN_BODY_HITS:
            status = "present"
        elif body_hits:
            status = "weak"
        else:
            status = "missing"
        nos = sorted({n for n, _ in hits})
        why = " · ".join(f"{n}장 '{w}'" for n, w in hits[:3]) if hits else "자료에 이 항목의 낱말이 없어요"
        items.append({"key": key, "label": label, "status": status, "slide_nos": nos, "why": why})
    counts = {s: sum(1 for i in items if i["status"] == s) for s in ("present", "weak", "missing")}
    return {"situation": situation or "", "situation_label": LABELS.get(situation or "", ""),
            "items": items, "summary": counts}
