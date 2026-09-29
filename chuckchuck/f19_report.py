"""
[F-19] F-17·F-18 수치를 받아 종합 진단 리포트를 쓰는 모듈입니다.
PaceDoc + HabitDoc(+Context) → ReportDoc. 숫자는 다시 짐작하지 않습니다.
"""

from __future__ import annotations

import json
import os
import re

from ._json_text import extract_json_object
from .contracts import RUBRIC_CAP_KINDS, Context, HabitDoc, PaceDoc, ReportDoc, ReportError, RubricFault, RubricScore
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
    "점수·등급은 쓰지 마세요 — 코드가 수치로 계산합니다. "
    "[먼저 짚을 것] 줄이 있으면 그것이 이 발표에서 가장 먼저 고칠 문제예요 — one_liner 와 weaknesses 첫 줄에 그 사실을 "
    "쓰고, '잘 전달했다·자료와 일치한다·모순이 없다·정확하게 설명했다' 같은 말은 쓰지 마세요. "
    "녹음이 자료와 다른 발표라는 줄이 있으면 발표 내용·슬라이드를 칭찬하거나 평가하지 말고 목소리·속도·말버릇만 말하세요."
)

#: LLM 응답 토큰 상한. 1200 이면 한국어 JSON 이 pace_summary 쯤에서 잘려 통째로 규칙 폴백이 됐다
#: (09-30 수면 녹음 실측 — 837자에서 끊겨 닫는 괄호가 없었다). 잘린 JSON 도 아래에서 되살린다.
MAX_TOKENS = 2000


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
    if rubric.faults:
        # 점수와 따로 읽어야 하는 사실 — 코드가 자료 원문과 견줘 확인한 모순, 말로 건너뛴 핵심 장, 다른 발표 녹음 (09-30 C-06·C-07)
        lines.append("[먼저 짚을 것]")
        lines += [f"- {f.text}" for f in rubric.faults]
        if rubric.cap is not None:
            lines.append(f"- 그래서 총점은 {rubric.cap}점을 넘지 않아요")
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
    # 규칙 폴백도 해요체다 (CLAUDE.md §3-1). 09-30 WP-A 가 토큰을 늘려 폴백이 드물어졌지만, LLM 이 죽은 날 화면에 합쇼체
    # (「…가깝습니다」「…맞추세요」)가 LLM 문장과 섞여 나갔다. 행동은 LLM 과 같은 「~해 보세요」 권유로 맞춘다 (_SYSTEM actions).
    strengths = []
    weaknesses = []
    if pace.avg_chars_per_min and 280 <= pace.avg_chars_per_min <= 360:
        strengths.append(f"평균 말 속도 {pace.avg_chars_per_min:.0f}자/분이 권장 구간에 가까워요.")
    for s in pace.slides:
        if s.importance == "core" and s.status == "ok":
            strengths.append(f"{s.slide_no}번 핵심 슬라이드 시간 배분이 안정적이에요.")
            break
    for tip in pace.tips[:2]:
        weaknesses.append(tip)
    for tip in habits.tips[:2]:
        if tip not in weaknesses:
            weaknesses.append(tip)
    if not strengths:
        strengths.append("슬라이드 전환과 발화 기록이 남아 코칭 근거를 만들 수 있어요.")
    if not weaknesses:
        weaknesses.append("특별히 큰 배분·습관 문제는 보이지 않아요.")

    actions = []
    for s in pace.slides:
        if s.importance != "core" and s.status == "long":
            actions.append(f"{s.slide_no}번(보조) 설명을 한 문장으로 줄여 목표 시간에 맞춰 보세요.")
            break
    for s in pace.slides:
        if s.importance == "core" and s.status == "short":
            actions.append(f"{s.slide_no}번(핵심)에 예시 한 줄을 더해 권장 {s.recommended_sec:.0f}초에 가깝게 말해 보세요.")
            break
    for h in habits.by_slide:
        if h.repeat_cnt >= 2:
            actions.append(f"{h.slide_no}번에서 반복한 구절은 한 번만 말하고 다음으로 넘어가 보세요.")
            break
    while len(actions) < 3:
        actions.append("리허설 때 타이머를 켜고 핵심 장 앞에서 3초 쉬며 속도를 조절해 보세요.")

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
        data = json.loads(text, strict=False)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise
        data = json.loads(m.group(0), strict=False)
    if not isinstance(data, dict):
        # 리스트·숫자·문자열이 오면 예전엔 try 밖에서 AttributeError 로 500 이 났다 (2026-09-13 감사)
        raise ValueError(f"리포트 JSON 최상위가 객체가 아닙니다: {type(data).__name__}")
    return data


def _as_list(v) -> list[str]:
    """LLM 이 목록 자리에 문자열 하나를 주면 글자 단위로 쪼개지 않고 한 항목으로 받는다."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    return [str(x) for x in v]


# ---------------------------------------------------------------------------
# 정직 — 치명 결함이 있으면 한 줄 총평이 그걸 먼저 말한다 (09-30 held-out C-06·C-07)
# ---------------------------------------------------------------------------

#: 자료와 맞게·빠짐없이 전했다는 칭찬 — 코드가 모순·건너뛴 핵심 장을 확인했으면 이 말은 거짓이다.
_CONSISTENT_RE = re.compile(
    r"일치|모순(?:이|은|도)?\s?없|어긋난\s?(?:곳|점)(?:이|은)?\s?없|정확(?:히|하게)?\s?(?:전달|설명|인용|제시)|자료대로|"
    r"빠짐없이|꼼꼼(?:히|하게)|핵심(?:을|은|이)?\s?(?:잘\s?|모두\s?|다\s?)?전(?:달|했)"
)
#: 발표 **내용**에 대한 칭찬·평가 — 녹음이 다른 발표면 이 자료 기준으로 말할 수 없다 (목소리·속도·습관만 남긴다).
_CONTENT_RE = re.compile(r"슬라이드|자료|개념|내용|설명|근거|제시|결과|논리|구조|흐름|주장|사례|결론|핵심")
#: 한 줄 총평이 결함을 이미 말했는가 — 장 번호나 이런 말이 있으면 그대로 둔다.
_FAULT_WORDS_RE = re.compile(r"어긋|다르게|다른\s?수치|틀리|틀린|건너뛰|건너뛴|넘어가|넘어갔|빠뜨|모순")


def _slides_word(nos: list[int]) -> str:
    return ", ".join(f"{n}장" for n in nos)


def _fault_lead(key: list[RubricFault]) -> str:
    """상한을 건 결함을 한 문장으로 — 숫자·장 번호는 결함 목록 그대로."""
    contra = sorted({f.slide_no for f in key if f.kind == "contradiction" and f.slide_no})
    skips = sorted({f.slide_no for f in key if f.kind == "skipped_slide" and f.slide_no})
    n_contra = sum(1 for f in key if f.kind == "contradiction")
    where = f"({_slides_word(contra)})" if contra else ""
    if n_contra and skips:
        return (f"자료와 다르게 말한 곳이 {n_contra}곳{where} 있고, 핵심 {_slides_word(skips)}을 말로 건너뛰었어요. "
                "이것부터 고쳐 보세요.")
    if n_contra:
        return f"자료와 다르게 말한 곳이 {n_contra}곳{where} 있어요. 이것부터 고쳐 보세요."
    return f"핵심 {_slides_word(skips)}을 말로 건너뛰었어요. 이것부터 채워 보세요."


def _mentions(text: str, key: list[RubricFault]) -> bool:
    nos = {f.slide_no for f in key if f.slide_no}
    return bool(_FAULT_WORDS_RE.search(text or "")) or any(re.search(rf"(?<!\d){n}\s?(?:장|번)", text or "") for n in nos)


def _honest(doc: ReportDoc, rubric: RubricScore | None, pace: PaceDoc, habits: HabitDoc) -> ReportDoc:
    """
    채점표가 짚은 사실(faults)을 리포트 문장이 **먼저, 빠짐없이** 말하게 한다. LLM 이 규칙을 어겨도 여기서 막는다.

    09-30 held-out: 혈당 녹음(6장 29%→49%, 핵심 3장 건너뜀)의 리포트가 「발표 완성도 B · 핵심은 전했고」 였고,
    /temp 재현(반찬 IR 자료 + 집중·알림 녹음)은 「모든 슬라이드를 꼼꼼히 설명했고, 파일럿 결과와 고객 반응을 구체적으로
    제시했어요」 라고 칭찬했다 — 녹음은 다른 발표였다.
    """
    found = list(rubric.faults) if rubric else []
    if not found:
        return doc
    kinds = {f.kind for f in found}
    if "unrelated_speech" in kinds:
        head = next(f.text for f in found if f.kind == "unrelated_speech")
        doc.one_liner = ("녹음이 이 발표 자료와 다른 발표라서 말한 내용은 분석하지 않았어요. "
                         "이 자료로 발표한 녹음을 올리면 개념·흐름까지 같이 볼게요.")
        doc.strengths = [x for x in doc.strengths if not _CONTENT_RE.search(x)] or [
            x for x in _fallback_report(pace, habits, doc.model).strengths if not _CONTENT_RE.search(x)]
        doc.weaknesses = [head] + [x for x in doc.weaknesses if not _CONTENT_RE.search(x) and "다른 발표" not in x]
        doc.actions = ["이 발표 자료로 한 녹음을 다시 올려 보세요 — 그래야 개념·흐름·자료와 맞게 말했는지 볼 수 있어요."] + [
            x for x in doc.actions if not _CONTENT_RE.search(x) and "녹음" not in x]
        return doc
    key = [f for f in found if f.kind in RUBRIC_CAP_KINDS]
    if key:
        if not _mentions(doc.one_liner, key):
            doc.one_liner = f"{_fault_lead(key)} {doc.one_liner}".strip()
        texts = [f.text for f in key]
        doc.weaknesses = texts + [x for x in doc.weaknesses if x not in texts]
        doc.strengths = [x for x in doc.strengths if not _CONSISTENT_RE.search(x)]
    if "align_fallback" in kinds:
        doc.weaknesses.append(next(f.text for f in found if f.kind == "align_fallback"))
    return doc


def _loads(raw: str) -> dict:
    """LLM 응답 → dict. 코드펜스·말머리는 `_parse_json` 이, 끝이 잘린 JSON 은 `_json_text` 가 되살린다."""
    try:
        return _parse_json(raw)
    except json.JSONDecodeError:
        # 읽을 수 없는 JSON(잘림)만 되살린다 — 읽히는데 객체가 아닌 것(리스트·숫자)은 규칙 폴백이 맞다
        data = extract_json_object(raw)
        if not isinstance(data, dict) or not data:
            raise ValueError("리포트 JSON 을 되살리지 못했습니다")
        return data


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

    # llm 미지정이면 get_llm 기본 경로 — REASONING_BACKEND 와 REASONING_FALLBACK(예비) 를 함께 읽는다
    engine = llm if isinstance(llm, LLMProvider) else get_llm(None if llm is None else str(llm))

    if getattr(engine, "name", "") == "mock":
        return _honest(_fallback_report(pace, habits, model="mock", score=score), rubric, pace, habits)

    user = _facts_block(pace, habits, context, rubric)
    try:
        raw = engine.complete(system=_SYSTEM, user=user, temperature=0.2, max_tokens=MAX_TOKENS)
        data = _loads(raw)
    except Exception as e:  # noqa: BLE001
        doc = _fallback_report(
            pace, habits, model=f"{getattr(engine, 'name', 'llm')}-fallback", score=score
        )
        if not doc.one_liner:
            raise ReportError(str(e)) from e
        return _honest(doc, rubric, pace, habits)

    # 점수는 채점표가 진실이다 — 모듈 원칙("숫자는 다시 짐작하지 않습니다")대로
    # LLM 이 준 score/grade 는 무시한다. LLM 값을 받으면 같은 수치 입력인데
    # 실행마다 점수가 흔들리고, "85점" 같은 문자열이 오면 int() 가 터진다.
    has_body = any(_as_list(data.get(k)) for k in ("strengths", "weaknesses", "actions"))
    if not str(data.get("one_liner") or "").strip() and not has_body:
        # 파싱은 됐지만 알맹이가 없다({} 등) — 빈 리포트를 내보내느니 숫자로 조립한 폴백을 준다
        return _honest(_fallback_report(
            pace, habits, model=f"{getattr(engine, 'name', 'llm')}-fallback", score=score
        ), rubric, pace, habits)
    return _honest(ReportDoc(
        one_liner=str(data.get("one_liner") or ""),
        score=score,
        grade="",
        strengths=_as_list(data.get("strengths"))[:5],
        weaknesses=_as_list(data.get("weaknesses"))[:5],
        actions=_as_list(data.get("actions"))[:5],
        pace_summary=str(data.get("pace_summary") or " ".join(pace.tips[:2])),
        habit_summary=str(data.get("habit_summary") or " ".join(habits.tips[:2])),
        model=getattr(engine, "name", str(llm)),
    ), rubric, pace, habits)
