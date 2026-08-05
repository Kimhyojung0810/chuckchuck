"""
[F-19] F-17·F-18 수치를 받아 종합 진단 리포트를 쓰는 모듈입니다.
PaceDoc + HabitDoc(+Context) → ReportDoc. 숫자는 다시 짐작하지 않습니다.
"""

from __future__ import annotations

import json
import os
import re

from .contracts import Context, HabitDoc, PaceDoc, ReportDoc, ReportError
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm

# callers: compose_report() ← bridge /api/v1/report, examples/run_voice_report.py
# user: "사용자가 이해하기 쉽게 설명해야지... 화면 UI에서도 레포트에서 잘 시각적으로도"
_SYSTEM = (
    "당신은 친절한 발표 코치입니다. 아래에 주어진 수치·사실만 근거로 "
    "중학생도 이해할 수 있는 쉬운 한국어로 종합 진단을 JSON으로 쓰세요. "
    "숫자·시간을 새로 만들어내지 마세요. "
    "슬라이드 번호를 나열만 하지 말고, '짧게 말한 핵심 장', '길게 말한 장'처럼 "
    "상황을 먼저 설명하세요. 전문 용어(SPS, REP, FIL) 대신 "
    "'말 속도', '같은 말 반복', '간투어(어, 그, 음)'를 쓰세요. "
    "JSON 키: one_liner(한 줄 총평, 친근한 해요체), score(0-100 정수), "
    "grade(A+|A0|B+|B0|C+|C0|D+|D0|F), "
    "strengths(쉬운 문장 배열), weaknesses(쉬운 문장 배열), "
    "actions(바로 연습할 행동 3개, '~해보세요' 체), "
    "pace_summary, habit_summary."
)


def _facts_block(pace: PaceDoc, habits: HabitDoc, context: Context | None) -> str:
    lines = ["[TASK] voice-comprehensive-report", "[FACTS]"]
    if context:
        lines.append(
            f"상황={context.situation or '-'} / 청중={context.audience or '-'} / "
            f"목표분={context.duration_min or '-'}"
        )
    lines.append(
        f"목표초={pace.target_sec} 실제초={pace.actual_sec} "
        f"평균자분={pace.avg_chars_per_min} 평균SPS={pace.avg_syllable_per_sec} "
        f"최대자분={pace.max_chars_per_min}(슬라이드 {pace.max_slide_no})"
    )
    lines.append("슬라이드별:")
    for s in pace.slides:
        lines.append(
            f"- {s.slide_no}번({s.importance}) title={s.title[:40]} "
            f"권장={s.recommended_sec}s 실제={s.actual_sec}s "
            f"cpm={s.chars_per_min} sps={s.syllable_per_sec} status={s.status} note={s.note}"
        )
    if pace.tips:
        lines.append("배분팁: " + " | ".join(pace.tips))
    lines.append(
        f"습관합계: REP={habits.repeat_cnt} FIL={habits.filler_cnt} "
        f"PAUSE={habits.pause_cnt} provider={habits.provider}"
    )
    for h in habits.by_slide:
        if h.repeat_cnt or h.filler_cnt or h.pause_cnt:
            lines.append(
                f"- {h.slide_no}번 REP={h.repeat_cnt} FIL={h.filler_cnt} "
                f"PAUSE={h.pause_cnt} {h.note}"
            )
    if habits.tips:
        lines.append("습관팁: " + " | ".join(habits.tips))
    lines.append("[END FACTS] JSON만 출력하세요.")
    return "\n".join(lines)


def _rule_score(pace: PaceDoc, habits: HabitDoc) -> int:
    score = 78
    if pace.target_sec > 0:
        drift = abs(pace.actual_sec - pace.target_sec) / pace.target_sec
        score -= int(min(20, drift * 40))
    short_core = sum(1 for s in pace.slides if s.importance == "core" and s.status == "short")
    score -= short_core * 6
    long_sup = sum(1 for s in pace.slides if s.importance != "core" and s.status == "long")
    score -= long_sup * 3
    score -= min(15, habits.repeat_cnt * 2 + habits.filler_cnt + habits.pause_cnt * 3)
    return int(max(45, min(92, score)))


def _grade_from_score(score: int) -> str:
    if score >= 93:
        return "A+"
    if score >= 88:
        return "A0"
    if score >= 83:
        return "B+"
    if score >= 78:
        return "B0"
    if score >= 73:
        return "C+"
    if score >= 68:
        return "C0"
    if score >= 60:
        return "D+"
    if score >= 50:
        return "D0"
    return "F"


def _fallback_report(pace: PaceDoc, habits: HabitDoc, model: str) -> ReportDoc:
    score = _rule_score(pace, habits)
    strengths = []
    weaknesses = []
    if pace.avg_chars_per_min and 280 <= pace.avg_chars_per_min <= 360:
        strengths.append(f"평균 말 속도 {pace.avg_chars_per_min:.0f}자/분이 권장 구간에 가깝습니다.")
    for s in pace.slides:
        if s.importance == "core" and s.status == "ok":
            strengths.append(f"{s.slide_no}번 핵심 슬라이드 시간 배분이 안정적입니다.")
            break
    for tip in pace.tips[:2]:
        weaknesses.append(tip)
    for tip in habits.tips[:2]:
        if tip not in weaknesses:
            weaknesses.append(tip)
    if not strengths:
        strengths.append("슬라이드 전환과 발화 기록이 남아 코칭 근거를 만들 수 있습니다.")
    if not weaknesses:
        weaknesses.append("특별히 큰 배분·습관 문제는 보이지 않습니다.")

    actions = []
    for s in pace.slides:
        if s.importance != "core" and s.status == "long":
            actions.append(f"{s.slide_no}번(보조) 설명을 한 문장으로 줄여 목표 시간을 맞추세요.")
            break
    for s in pace.slides:
        if s.importance == "core" and s.status == "short":
            actions.append(f"{s.slide_no}번(핵심)에 예시 한 줄을 추가해 권장 {s.recommended_sec:.0f}초에 가깝게.")
            break
    for h in habits.by_slide:
        if h.repeat_cnt >= 2:
            actions.append(f"{h.slide_no}번에서 반복한 구절을 한 번만 말하고 다음으로 넘기세요.")
            break
    while len(actions) < 3:
        actions.append("리허설 때 타이머를 켜고 핵심 장 앞에서 3초 쉬어 속도를 조절하세요.")

    return ReportDoc(
        one_liner=pace.tips[0] if pace.tips else "시간 배분과 음성 습관을 함께 점검했어요.",
        score=score,
        grade=_grade_from_score(score),
        strengths=strengths[:3],
        weaknesses=weaknesses[:3],
        actions=actions[:3],
        pace_summary=" ".join(pace.tips[:2]),
        habit_summary=" ".join(habits.tips[:2]),
        model=model,
    )


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def compose_report(
    pace: PaceDoc | dict,
    habits: HabitDoc | dict,
    context: Context | dict | None = None,
    *,
    llm: str | LLMProvider | None = None,
) -> ReportDoc:
    """F-17·F-18 결과를 종합 서술로 묶는다."""
    if isinstance(pace, dict):
        pace = PaceDoc.from_dict(pace)
    if isinstance(habits, dict):
        habits = HabitDoc.from_dict(habits)
    if isinstance(context, dict):
        context = Context.from_dict(context)

    if llm is None:
        llm = os.environ.get("REASONING_BACKEND", "solar")
    engine = llm if isinstance(llm, LLMProvider) else get_llm(str(llm))

    if getattr(engine, "name", "") == "mock":
        return _fallback_report(pace, habits, model="mock")

    user = _facts_block(pace, habits, context)
    try:
        raw = engine.complete(system=_SYSTEM, user=user, temperature=0.2, max_tokens=1200)
        data = _parse_json(raw)
    except Exception as e:  # noqa: BLE001
        doc = _fallback_report(pace, habits, model=f"{getattr(engine, 'name', 'llm')}-fallback")
        if not doc.one_liner:
            raise ReportError(str(e)) from e
        return doc

    score = int(data.get("score") or _rule_score(pace, habits))
    score = max(0, min(100, score))
    return ReportDoc(
        one_liner=str(data.get("one_liner") or ""),
        score=score,
        grade=str(data.get("grade") or _grade_from_score(score)),
        strengths=[str(x) for x in data.get("strengths") or []][:5],
        weaknesses=[str(x) for x in data.get("weaknesses") or []][:5],
        actions=[str(x) for x in data.get("actions") or []][:5],
        pace_summary=str(data.get("pace_summary") or " ".join(pace.tips[:2])),
        habit_summary=str(data.get("habit_summary") or " ".join(habits.tips[:2])),
        model=getattr(engine, "name", str(llm)),
    )
