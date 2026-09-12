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
