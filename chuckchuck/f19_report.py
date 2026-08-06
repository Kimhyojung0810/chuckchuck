"""
[F-19] F-17·F-18 수치를 받아 종합 진단 리포트를 쓰는 모듈입니다.
PaceDoc + HabitDoc(+Context) → ReportDoc. 숫자는 다시 짐작하지 않습니다.
"""

from __future__ import annotations

import json
import os
import re

from .contracts import Context, HabitDoc, PaceDoc, ReportDoc, ReportError, RubricScore
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
    "JSON 키: one_liner(한 줄 총평, 친근한 해요체), "
    "strengths(쉬운 문장 배열), weaknesses(쉬운 문장 배열), "
    "actions(바로 연습할 행동 3개, '~해보세요' 체), "
    "pace_summary, habit_summary. "
    "점수·등급은 쓰지 마세요 — 코드가 수치로 계산합니다."
)


def _rubric_block(rubric: RubricScore) -> list[str]:
    """
    채점표 결과를 사실 블록으로. 코칭 문장이 **채점표 항목 이름으로** 나오게 한다.

    점수 자체는 넣되 다시 쓰지 말라고 시스템 프롬프트가 막는다. 여기 넣는 이유는
    LLM 이 "무엇이 약했는지"를 우리 기준의 언어로 말하게 하기 위해서다.
    """
    lines = [f"채점 기준: {rubric.situation_label} (총점 {rubric.score}점)"]
    live = [c for c in rubric.clusters if c.status == "scored"]
    if live:
        lines.append("영역별: " + " / ".join(f"{c.name} {c.average:.0f}점" for c in live))
    weak = sorted(
        (i for i in rubric.items if i.status == "scored"), key=lambda i: i.score
    )[:3]
    for i in weak:
        lines.append(f"- 약한 항목: {i.name} {i.score}점 — {i.evidence}")
    if rubric.unmeasured:
        lines.append(f"측정 못 한 항목 번호: {rubric.unmeasured} (없는 걸 있는 척하지 마세요)")
    return lines


def _facts_block(
    pace: PaceDoc, habits: HabitDoc, context: Context | None,
    rubric: RubricScore | None = None,
) -> str:
    lines = ["[TASK] voice-comprehensive-report", "[FACTS]"]
    if rubric:
        lines += _rubric_block(rubric)
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


def _fallback_report(pace: PaceDoc, habits: HabitDoc, model: str, score: int = 0) -> ReportDoc:
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
        grade="",
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
    rubric: RubricScore | dict | None = None,
    llm: str | LLMProvider | None = None,
) -> ReportDoc:
    """
    F-17·F-18 결과를 종합 서술로 묶는다.

    **점수는 여기서 만들지 않는다.** 채점표(F-14)가 매긴 점수를 받아 그대로 싣는다.
    예전에는 이 모듈이 45~92 로 클램프된 두 번째 점수를 따로 계산했는데, 화면에
    보이는 F-13 점수와 서로 달랐고 프론트는 그걸 아예 읽지도 않았다.
    `rubric` 이 없으면 0 을 싣는다 — 짐작하지 않는다.
    """
    if isinstance(pace, dict):
        pace = PaceDoc.from_dict(pace)
    if isinstance(habits, dict):
        habits = HabitDoc.from_dict(habits)
    if isinstance(context, dict):
        context = Context.from_dict(context)
    if isinstance(rubric, dict):
        rubric = RubricScore.from_dict(rubric)
    score = rubric.score if rubric else 0

    if llm is None:
        llm = os.environ.get("REASONING_BACKEND", "solar")
    engine = llm if isinstance(llm, LLMProvider) else get_llm(str(llm))

    if getattr(engine, "name", "") == "mock":
        return _fallback_report(pace, habits, model="mock", score=score)

    user = _facts_block(pace, habits, context, rubric)
    try:
        raw = engine.complete(system=_SYSTEM, user=user, temperature=0.2, max_tokens=1200)
        data = _parse_json(raw)
    except Exception as e:  # noqa: BLE001
        doc = _fallback_report(
            pace, habits, model=f"{getattr(engine, 'name', 'llm')}-fallback", score=score
        )
        if not doc.one_liner:
            raise ReportError(str(e)) from e
        return doc

    # 점수는 채점표가 진실이다 — 모듈 원칙("숫자는 다시 짐작하지 않습니다")대로
    # LLM 이 준 score/grade 는 무시한다. LLM 값을 받으면 같은 수치 입력인데
    # 실행마다 점수가 흔들리고, "85점" 같은 문자열이 오면 int() 가 터진다.
    return ReportDoc(
        one_liner=str(data.get("one_liner") or ""),
        score=score,
        grade="",
        strengths=[str(x) for x in data.get("strengths") or []][:5],
        weaknesses=[str(x) for x in data.get("weaknesses") or []][:5],
        actions=[str(x) for x in data.get("actions") or []][:5],
        pace_summary=str(data.get("pace_summary") or " ".join(pace.tips[:2])),
        habit_summary=str(data.get("habit_summary") or " ".join(habits.tips[:2])),
        model=getattr(engine, "name", str(llm)),
    )
