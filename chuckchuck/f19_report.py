"""
[F-19] F-17·F-18 수치를 받아 종합 진단 리포트를 쓰는 모듈입니다.
PaceDoc + HabitDoc(+Context·RubricScore·AlignmentDoc) → ReportDoc. 숫자는 다시 짐작하지 않습니다.

LLM 은 문장만 쓴다. 두 가지는 코드가 맡는다 (09-30 녹음 대화 감사 REC-10·REC-15):
1. 녹음이 이 자료의 발표가 아니면 LLM 을 부르지 않는다 — 녹음으로 잰 것(말 속도·시간·말버릇)을 이 발표의 것처럼 말하면 거짓이다.
2. LLM 문장이 F-17 이 잰 말 속도와 반대 방향을 말하거나(116자/분을 「너무 빨라서」) 잰 적 없는 수를 대면 그 문장을 빼고 코드 문장으로
   채운다. 프롬프트에는 내부 이름(자분·SPS·REP·core)을 싣지 않고, 그래도 새어 나온 이름은 사람 말로 바꾼다.
"""

from __future__ import annotations

import json
import re

from ._json_text import extract_json_object
from .contracts import (
    RUBRIC_CAP_KINDS,
    AlignmentDoc,
    Context,
    HabitDoc,
    PaceDoc,
    ReportDoc,
    ReportError,
    RubricFault,
    RubricScore,
)
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm

# callers: compose_report() ← bridge /api/v1/report, examples/run_voice_report.py
# user: "사용자가 이해하기 쉽게 설명해야지... 화면 UI에서도 레포트에서 잘 시각적으로도"
_SYSTEM = (
    "당신은 친절한 발표 코치입니다. 아래에 주어진 수치·사실만 근거로 "
    "중학생도 이해할 수 있는 쉬운 한국어로 종합 진단을 JSON으로 쓰세요. "
    "숫자·시간을 새로 만들어내지 마세요. "
    "슬라이드 번호를 나열만 하지 말고, '짧게 말한 핵심 장', '길게 말한 장'처럼 "
    "상황을 먼저 설명하세요. 말 속도는 'N자/분'으로 쓰고, 권장보다 느린지 빠른지는 [FACTS] 에 적힌 그대로만 말하세요. "
    "JSON 키: one_liner(한 줄 총평, 친근한 해요체), "
    "strengths(쉬운 문장 배열), weaknesses(쉬운 문장 배열), "
    "actions(바로 연습할 행동 3개, '~해보세요' 체), "
    "pace_summary(문장 하나), habit_summary(문장 하나). "
    "점수·등급은 쓰지 마세요 — 코드가 수치로 계산합니다. "
    "[먼저 짚을 것] 줄이 있으면 그것이 이 발표에서 가장 먼저 고칠 문제예요 — one_liner 와 weaknesses 첫 줄에 그 사실을 "
    "쓰고, '잘 전달했다·자료와 일치한다·모순이 없다·정확하게 설명했다' 같은 말은 쓰지 마세요."
)

#: LLM 응답 토큰 상한. 1200 이면 한국어 JSON 이 pace_summary 쯤에서 잘려 통째로 규칙 폴백이 됐다
#: (09-30 수면 녹음 실측 — 837자에서 끊겨 닫는 괄호가 없었다). 잘린 JSON 도 아래에서 되살린다.
MAX_TOKENS = 2000

#: 권장 말 속도(자/분) — PaceDoc.recommended_cpm("300~350")을 못 읽을 때만 쓴다. F-17 _REC_CPM 과 같은 값이다.
_REC_CPM_FALLBACK = (300.0, 350.0)
#: 프롬프트에 싣는 사람 말 — 내부 값(core·support·short)을 그대로 실으면 LLM 이 「핵심(core)이」 처럼 되받아 쓴다 (09-30 REC-15)
_IMPORTANCE_WORD = {"core": "핵심", "support": "보조"}
_STATUS_WORD = {"ok": "알맞음", "short": "짧음", "long": "김", "fast": "내 평균보다 빠름", "slow": "내 평균보다 느림"}
_WAY_WORD = {"slow": "권장보다 느려요", "fast": "권장보다 빨라요", "ok": "권장 구간 안이에요"}

# ---------------------------------------------------------------------------
# 녹음이 이 자료의 발표가 아닐 때 — LLM 없이 정해진 말만 (09-30 REC-10)
# ---------------------------------------------------------------------------

UNRELATED_ONE_LINER = ("녹음이 이 발표 자료와 다른 발표라서 말한 내용·말 속도·시간·말버릇은 분석하지 않았어요. "
                       "이 자료로 발표한 녹음을 올리면 같이 볼게요.")
UNRELATED_ACTION = "이 발표 자료로 한 녹음을 다시 올려 보세요 — 그래야 말한 내용과 말 속도·시간까지 볼 수 있어요."
UNMEASURED_PACE = "녹음이 이 자료의 발표가 아니라서 말 속도와 시간 배분은 재지 않았어요."
UNMEASURED_HABITS = "녹음이 이 자료의 발표가 아니라서 말버릇은 보지 않았어요."


def _unrelated(rubric: RubricScore | None, alignment: AlignmentDoc | None) -> bool:
    """
    녹음이 이 자료의 발표가 아닌가 — 채점표 결함(unrelated_speech) 또는 F-11 정합(speech_match·basis) 그대로. 따로 표시를 만들지 않는다.

    채점표가 폴백(F-13)으로 매겨져 결함 칸이 비어도 정합을 같이 보면 놓치지 않는다.
    """
    if rubric is not None and any(f.kind == "unrelated_speech" for f in rubric.faults):
        return True
    return alignment is not None and (alignment.speech_match == "unrelated" or alignment.basis == "skipped")


def _unrelated_report(rubric: RubricScore | None, alignment: AlignmentDoc | None, score: int) -> ReportDoc:
    """
    다른 발표 녹음의 리포트. 녹음으로 잰 것은 어느 칸에도 싣지 않는다 — 0 이 아니라 「재지 않았어요」 다.

    09-30 녹음 대화 감사(REC-10): 다른 발표 녹음 3벌 모두 리포트가 「93자/분 … 너무 느렸어요」 · 「말 속도를 … 빠르게 연습해 보세요」 ·
    강점 「말 속도가 일정해서…」 를 실었다 — 목소리·습관은 된다고 LLM 에 남겨 둔 길이었다. 할 수 있는 말이 「다시 올려 달라」 뿐이라
    LLM 을 부르지 않는다.
    """
    head = next((f.text for f in (rubric.faults if rubric else []) if f.kind == "unrelated_speech" and f.text), "")
    if not head:
        overlap = alignment.speech_overlap if alignment is not None else None
        pct = "" if overlap is None else f" (발화 낱말 중 자료에도 있는 비중 {overlap:.0%})"
        head = f"녹음이 이 발표 자료와 다른 발표예요{pct} — 녹음으로 재는 항목은 채점하지 않았어요"
    return ReportDoc(
        one_liner=UNRELATED_ONE_LINER,
        score=score,
        grade="",
        strengths=[],
        weaknesses=[head],
        actions=[UNRELATED_ACTION],
        pace_summary=UNMEASURED_PACE,
        habit_summary=UNMEASURED_HABITS,
        model="code",
    )


# ---------------------------------------------------------------------------
# 사실 블록 — 숫자는 원본 그대로, 이름은 사람 말로
# ---------------------------------------------------------------------------

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
        # 점수와 따로 읽어야 하는 사실 — 코드가 자료 원문과 견줘 확인한 모순, 말로 건너뛴 핵심 장 (09-30 C-06·C-07)
        lines.append("[먼저 짚을 것]")
        lines += [f"- {f.text}" for f in rubric.faults]
        if rubric.cap is not None:
            lines.append(f"- 그래서 총점은 {rubric.cap}점을 넘지 않아요")
    return lines


def _pace_measured(pace: PaceDoc) -> bool:
    """F-17 이 말 속도·시간을 실제로 쟀나. 빈 PaceDoc(0)은 「안 쟀다」 다 — 0자/분으로 읽으면 안 된다."""
    return pace.avg_chars_per_min > 0 and bool(pace.slides)


def _rec_range(pace: PaceDoc) -> tuple[float, float]:
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", pace.recommended_cpm or "")]
    return (nums[0], nums[1]) if len(nums) >= 2 and nums[0] <= nums[1] else _REC_CPM_FALLBACK


def _speed_way(pace: PaceDoc) -> str | None:
    """F-17 이 잰 평균 말 속도의 방향 — 권장 구간보다 느림 slow · 빠름 fast · 안 ok. 못 쟀으면 None."""
    avg = pace.avg_chars_per_min
    if avg <= 0:
        return None
    low, high = _rec_range(pace)
    return "slow" if avg < low else "fast" if avg > high else "ok"


def _pace_facts(pace: PaceDoc) -> list[str]:
    if not _pace_measured(pace):
        return ["말 속도·시간 배분: 이번엔 재지 않았어요 — 말 속도·시간·배분 이야기는 쓰지 마세요"]
    low, high = _rec_range(pace)
    lines = [
        f"목표 시간 {pace.target_sec}초 · 실제 {pace.actual_sec}초",
        f"평균 말 속도 {pace.avg_chars_per_min}자/분 — 권장 {low:.0f}~{high:.0f}자/분이라 {_WAY_WORD[_speed_way(pace) or 'ok']}",
        f"가장 빠른 장 {pace.max_slide_no}번 {pace.max_chars_per_min}자/분",
        "슬라이드별:",
    ]
    for s in pace.slides:
        lines.append(
            f"- {s.slide_no}번({_IMPORTANCE_WORD.get(s.importance, '보조')}) 제목: {s.title[:40]} · "
            f"권장 {s.recommended_sec}초 · 실제 {s.actual_sec}초 · {s.chars_per_min}자/분 · "
            f"{_STATUS_WORD.get(s.status, '알맞음')}{f' · {s.note}' if s.note else ''}"
        )
    if pace.tips:
        lines.append("시간 배분 팁: " + " | ".join(pace.tips))
    return lines


def _habit_facts(habits: HabitDoc) -> list[str]:
    lines = [f"말버릇 합계: 간투어 {habits.filler_cnt}번 · 같은 말 반복 {habits.repeat_cnt}번 · "
             f"5초 넘게 멈춘 곳 {habits.pause_cnt}번"]
    for h in habits.by_slide:
        if h.repeat_cnt or h.filler_cnt or h.pause_cnt:
            lines.append(
                f"- {h.slide_no}번: 간투어 {h.filler_cnt}번 · 같은 말 반복 {h.repeat_cnt}번 · "
                f"멈춤 {h.pause_cnt}번{f' · {h.note}' if h.note else ''}"
            )
    if habits.tips:
        lines.append("말버릇 팁: " + " | ".join(habits.tips))
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
    lines += _pace_facts(pace)
    lines += _habit_facts(habits)
    lines.append("[END FACTS] JSON만 출력하세요.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 규칙 폴백
# ---------------------------------------------------------------------------

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


def _as_text(v) -> str:
    """
    LLM 이 문장 자리에 준 값 → 글. 객체({"average_cpm": 144.9, "status": "…"})면 글 칸만 모은다 — 예전엔 str() 로
    파이썬 표기(「{'average_sps': 2.26, …}」)가 리포트에 그대로 실렸다 (09-30 녹음 감사 co2 R2). 수·참거짓은 문장이 아니다.
    """
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        return " ".join(t for t in (_as_text(x) for x in v.values()) if t)
    if isinstance(v, list):
        return " ".join(t for t in (_as_text(x) for x in v) if t)
    return ""


def _as_list(v) -> list[str]:
    """LLM 이 목록 자리에 문자열 하나를 주면 글자 단위로 쪼개지 않고 한 항목으로 받는다. 객체 항목은 글 칸만."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, dict):
        text = _as_text(v)
        return [text] if text else []
    out = []
    for x in v:
        text = _as_text(x) if isinstance(x, (dict, list)) else str(x)
        if text.strip():
            out.append(text)
    return out


# ---------------------------------------------------------------------------
# 잰 값과 맞추기 — 말 속도 방향·수, 내부 이름 (09-30 녹음 대화 감사 REC-15)
# ---------------------------------------------------------------------------
#
# kiosk R1 실측: 평균 116자/분(권장 300~350 — 느림)인데 리포트가 「말 속도가 너무 빨라서(116자/분)」 · 「1분에 100자 정도로 천천히
# 말해 보세요」 였다. bunt R3 「평균 자분 144.9, 평균 SPS 2.26」, co2 R3 「핵심(core)이」. 문장은 LLM 몫이어도 방향과 수는 F-17 이 쟀다.

#: 말 속도를 주어로 한 절인가 — 방향은 말 속도에 대해서만 따진다(「핵심 장을 빠르게 넘어갔어요」 는 시간 배분이다).
_SPEED_RE = re.compile(r"속도|템포|자\s?/\s?분|분당\s?\d|1분에\s?\d+(?:\.\d+)?\s?자|말이\s?(?:너무\s?|조금\s?|좀\s?|매우\s?|꽤\s?)?(?:빠|빨|느)")
#: 내 평균·다른 장과 견준 말, 장 하나를 짚은 말 — 권장 구간과 견줄 전체 속도가 아니다 (「7번은 평균보다 빠르게」 는 참일 수 있다)
_RELATIVE_RE = re.compile(r"(?:평균|평소|다른\s?\S{1,6})보다|\d+\s?(?:번|장)|슬라이드\s?\d+")
_NOT_FAST_RE = re.compile(r"빠르지\s?(?:는\s?)?않|빠르진\s?않|빠른\s?편은\s?아니")
_NOT_SLOW_RE = re.compile(r"느리지\s?(?:는\s?)?않|느리진\s?않|느린\s?편은\s?아니")
_SAID = r"(?:말했|말하는|말해서|말하고|말한|읽었|읽어서)"
_FAST_RE = re.compile(rf"빨라|빨랐|빠르(?:고|며|다|네|니|죠|지만|던|더라)|빠른|빠릅|빠르게\s?{_SAID}|급하|서둘")
_SLOW_RE = re.compile(rf"느려|느렸|느리(?:고|며|다|네|니|죠|지만|던|더라)|느린|느립|(?:느리게|천천히)\s?{_SAID}|늘어지|늘어졌|처져|처졌")
#: 알맞다는 말 — 권장 구간 밖을 「적절한 속도」 라고 하면 그것도 어긋난 말이다
_OK_RE = re.compile(r"적절|알맞|적당|딱\s?좋|권장\s?(?:구간|범위)\s?(?:안|이내)")
#: 권하는 말 — 「빠르게·빨리·속도를 올려 … 보세요」 는 지금 느리다는 뜻, 「천천히·속도를 늦춰 … 보세요」 는 지금 빠르다는 뜻이다
_ADVICE_RE = re.compile(r"(?:보|하|주)세요|봐요|해\s?봐")
_UP_RE = re.compile(r"빠르게|빨리|(?:속도|템포)를\s?(?:조금\s?|좀\s?|더\s?)*(?:올|높)")
_DOWN_RE = re.compile(r"천천히|느리게|(?:속도|템포)를\s?(?:조금\s?|좀\s?|더\s?)*(?:늦|낮|줄)")
#: 문장이 대는 자/분 수
_CPM_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)\s?자\s?/\s?분|분당\s?(\d+(?:\.\d+)?)\s?자|1분에\s?(\d+(?:\.\d+)?)\s?자")

#: 새어 나온 내부 이름 → 사람 말. 바로 뒤 조사도 받침에 맞춰 고친다(「FIL은」 → 「간투어는」). 괄호 풀이는 떼어 낸다 —
#: LLM 이 단 풀이가 틀린 적이 있다(「FIL(긴 휴지)」).
_NAME_SUBS = tuple(
    (re.compile(rf"{pat}(?:\s?\([^)]*\))?(으로|로|은|는|이|가|을|를|과|와)?"), word)
    for pat, word in (
        (r"(?<![A-Za-z])REP(?![A-Za-z])", "같은 말 반복"),
        (r"(?<![A-Za-z])FIL(?![A-Za-z])", "간투어"),
        (r"(?<![A-Za-z])PAUSE(?![A-Za-z])", "긴 멈춤"),
    )
) + (
    (re.compile(r"\((?:core)\)"), "(핵심)"),
    (re.compile(r"\((?:support)\)"), "(보조)"),
)
#: 사람 말로 옮길 수 없는 내부 이름 — 이게 든 문장은 뺀다(「평균 자분 144.9, 평균 SPS 2.26」). 바꿔 쓴 뒤의 글에서 본다.
_RAW_NAME_RE = re.compile(r"(?<![A-Za-z])(?:SPS|sps|cpm|core|support)(?![A-Za-z])|자분\s?[=:]?\s?\d")
#: 필드 덤프(「status=short」 · 「REP=0」) — 바꿔 쓰기 전의 글에서 본다
_FIELD_DUMP_RE = re.compile(r"[A-Za-z_]+\s?=")
_LEAD_RE = re.compile(r"^(?:특히|또한|그리고|다만|하지만|그래서|게다가)\s*,?\s*")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _josa(word: str, particle: str) -> str:
    """받침에 맞는 조사 — 「반복은」「간투어는」 · 「멈춤으로」「간투어로」 (ㄹ 받침은 「로」)."""
    last = word[-1]
    jong = (ord(last) - 0xAC00) % 28 if "가" <= last <= "힣" else 0
    if particle in ("으로", "로"):
        return "로" if jong in (0, 8) else "으로"
    pairs = {"은": ("은", "는"), "는": ("은", "는"), "이": ("이", "가"), "가": ("이", "가"),
             "을": ("을", "를"), "를": ("을", "를"), "과": ("과", "와"), "와": ("과", "와")}
    with_jong, without = pairs[particle]
    return with_jong if jong else without


def _humanize(text: str) -> str:
    for pat, word in _NAME_SUBS:
        text = pat.sub(lambda m, w=word: w + (_josa(w, m.group(1)) if m.lastindex else ""), text)
    return text


def _speed_claim(clause: str, advice: bool) -> str | None:
    """절이 전체 말 속도에 대해 하는 말 — "fast" · "slow" · "ok"(알맞다) · "not_fast" · "not_slow" · None(말 속도 말이 아님)."""
    if not _SPEED_RE.search(clause) or (_RELATIVE_RE.search(clause) and "권장" not in clause):
        return None
    if _NOT_FAST_RE.search(clause):
        return "not_fast"
    if _NOT_SLOW_RE.search(clause):
        return "not_slow"
    if advice or _ADVICE_RE.search(clause):
        if _DOWN_RE.search(clause):
            return "fast"          # 늦추라 → 지금 빠르다는 말
        if _UP_RE.search(clause):
            return "slow"          # 올리라 → 지금 느리다는 말
    if _FAST_RE.search(clause):
        return "fast"
    if _SLOW_RE.search(clause):
        return "slow"
    if _OK_RE.search(clause):
        return "ok"
    return None


def _contradicts(claim: str | None, way: str | None) -> bool:
    if claim is None or way is None:
        return False
    if claim in ("fast", "slow", "ok"):
        return claim != way
    return (claim, way) in (("not_fast", "fast"), ("not_slow", "slow"))


def _known_cpm(pace: PaceDoc) -> list[float]:
    """문장이 대도 되는 자/분 수 — 평균·최대·장별 속도, 권장 구간 두 끝, 권장과의 차이."""
    low, high = _rec_range(pace)
    avg = pace.avg_chars_per_min
    vals = [avg, pace.max_chars_per_min, low, high, abs(avg - low), abs(avg - high)]
    return [v for v in vals + [s.chars_per_min for s in pace.slides] if v > 0]


def _off_pace(sentence: str, pace: PaceDoc, way: str | None, advice: bool) -> bool:
    """문장이 F-17 이 잰 말 속도와 어긋나는가 — 반대 방향을 말하거나, 잰 적 없는 자/분 수를 댄다. 못 쟀으면(way None) 따지지 않는다."""
    if way is None:
        return False
    known = _known_cpm(pace)
    for clause in re.split(r",\s*", sentence):
        if _contradicts(_speed_claim(clause, advice), way):
            return True
        for m in _CPM_NUM_RE.finditer(clause):
            x = float(next(g for g in m.groups() if g))
            if not any(abs(x - k) <= 1.0 for k in known):
                return True
    return False


def _clean(text: str, pace: PaceDoc, way: str | None, advice: bool) -> tuple[str, bool, bool]:
    """
    문장마다 내부 이름을 사람 말로 바꾸고, 옮길 수 없는 이름이 든 문장·잰 값과 어긋난 속도 문장은 뺀다.
    → (남은 글, 속도 문장을 뺐나, 무엇이든 뺐나). 고칠 것이 없으면 원문 그대로 돌려준다.
    """
    kept: list[str] = []
    off_pace = dropped = False
    for sent in _SENT_SPLIT_RE.split(text.strip()):
        if not sent.strip():
            continue
        human = _humanize(sent)
        if _FIELD_DUMP_RE.search(sent) or _RAW_NAME_RE.search(human):
            dropped = True
            continue
        if _off_pace(human, pace, way, advice):
            off_pace = dropped = True
            continue
        kept.append(human)
    if dropped and kept:
        kept[0] = _LEAD_RE.sub("", kept[0])
    out = " ".join(kept)
    return (text if not dropped and _humanize(text) == text else out), off_pace, dropped


def _pace_line(pace: PaceDoc) -> str:
    """잰 값만으로 쓴 말 속도 한 문장. 못 쟀으면 빈 문자열."""
    way = _speed_way(pace)
    if way is None:
        return ""
    low, high = _rec_range(pace)
    avg = pace.avg_chars_per_min
    if way == "ok":
        return f"평균 말 속도는 {avg:.0f}자/분으로 권장 구간({low:.0f}~{high:.0f}자/분) 안이었어요."
    gap = low - avg if way == "slow" else avg - high
    return (f"평균 말 속도는 {avg:.0f}자/분으로 권장 구간({low:.0f}~{high:.0f}자/분)보다 {gap:.0f}자/분 "
            f"{'느렸어요' if way == 'slow' else '빨랐어요'}.")


def _speed_action(pace: PaceDoc) -> str:
    """잰 방향대로 권하는 한 줄 — 권장 구간 안이면 빈 문자열."""
    way = _speed_way(pace)
    low, high = _rec_range(pace)
    if way == "slow":
        return f"말 속도를 권장 구간({low:.0f}~{high:.0f}자/분)에 가깝게 조금 빠르게 연습해 보세요."
    if way == "fast":
        return f"문장 끝에서 한 박자 쉬며 말 속도를 권장 구간({low:.0f}~{high:.0f}자/분)에 가깝게 늦춰 보세요."
    return ""


def _habit_line(habits: HabitDoc) -> str:
    return (f"간투어는 {habits.filler_cnt}번, 같은 말 반복은 {habits.repeat_cnt}번, "
            f"5초 넘게 멈춘 곳은 {habits.pause_cnt}곳이었어요.")


def _clean_list(items: list[str], pace: PaceDoc, way: str | None, advice: bool) -> tuple[list[str], bool]:
    """→ (남은 항목, 속도 문장을 뺐나)."""
    out: list[str] = []
    off_pace = False
    for item in items:
        text, off, _ = _clean(item, pace, way, advice)
        off_pace = off_pace or off
        if text:
            out.append(text)
    return out, off_pace


def _checked(doc: ReportDoc, pace: PaceDoc, habits: HabitDoc) -> ReportDoc:
    """
    LLM 문장을 F-17·F-18 이 잰 값과 맞춘다 — 어긋난 문장은 빼고, 뺀 자리는 잰 값으로 쓴 코드 문장으로 채운다.

    요약 두 칸(pace_summary·habit_summary)은 한 문장이라도 어긋나면 통째로 코드 문장이다 — 그 칸이 바로 그 수치의 요약이다.
    """
    way = _speed_way(pace)
    one, _, _ = _clean(doc.one_liner, pace, way, advice=False)
    if doc.one_liner.strip() and not one:          # 한 줄 총평이 통째로 어긋났다 — 잰 값으로 쓴 팁으로 바꾼다
        one = pace.tips[0] if pace.tips else (_pace_line(pace) or "시간 배분과 음성 습관을 함께 점검했어요.")
    doc.one_liner = one
    doc.strengths, _ = _clean_list(doc.strengths, pace, way, advice=False)
    doc.weaknesses, lost = _clean_list(doc.weaknesses, pace, way, advice=False)
    if lost and way in ("slow", "fast") and not any(_SPEED_RE.search(w) for w in doc.weaknesses):
        doc.weaknesses.append(_pace_line(pace))
    doc.actions, lost = _clean_list(doc.actions, pace, way, advice=True)
    if lost and _speed_action(pace) and not any(_SPEED_RE.search(a) for a in doc.actions):
        doc.actions.append(_speed_action(pace))
    summary, _, bad = _clean(doc.pace_summary, pace, way, advice=False)
    doc.pace_summary = (_pace_line(pace) or " ".join(pace.tips[:2])) if bad or not summary else summary
    habit, _, bad = _clean(doc.habit_summary, pace, way, advice=False)
    doc.habit_summary = _habit_line(habits) if bad else habit
    return doc


# ---------------------------------------------------------------------------
# 정직 — 치명 결함이 있으면 한 줄 총평이 그걸 먼저 말한다 (09-30 held-out C-06·C-07)
# ---------------------------------------------------------------------------

#: 자료와 맞게·빠짐없이 전했다는 칭찬 — 코드가 모순·건너뛴 핵심 장을 확인했으면 이 말은 거짓이다.
_CONSISTENT_RE = re.compile(
    r"일치|모순(?:이|은|도)?\s?없|어긋난\s?(?:곳|점)(?:이|은)?\s?없|정확(?:히|하게)?\s?(?:전달|설명|인용|제시)|자료대로|"
    r"빠짐없이|꼼꼼(?:히|하게)|핵심(?:을|은|이)?\s?(?:잘\s?|모두\s?|다\s?)?전(?:달|했)"
)
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


def _honest(doc: ReportDoc, rubric: RubricScore | None) -> ReportDoc:
    """
    채점표가 짚은 사실(faults)을 리포트 문장이 **먼저, 빠짐없이** 말하게 한다. LLM 이 규칙을 어겨도 여기서 막는다.

    09-30 held-out: 혈당 녹음(6장 29%→49%, 핵심 3장 건너뜀)의 리포트가 「발표 완성도 B · 핵심은 전했고」 였다.
    다른 발표 녹음(unrelated_speech)은 여기 오지 않는다 — compose_report 가 LLM 없이 `_unrelated_report` 로 끝낸다.
    """
    found = list(rubric.faults) if rubric else []
    if not found:
        return doc
    kinds = {f.kind for f in found}
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
    alignment: AlignmentDoc | dict | None = None,
    llm: str | LLMProvider | None = None,
) -> ReportDoc:
    """
    F-17·F-18 결과를 종합 서술로 묶는다.

    **점수는 여기서 만들지 않는다.** 채점표(F-14)가 매긴 점수를 받아 그대로 싣는다.
    예전에는 이 모듈이 45~92 로 클램프된 두 번째 점수를 따로 계산했는데, 화면에
    보이는 F-13 점수와 서로 달랐고 프론트는 그걸 아예 읽지도 않았다.
    `rubric` 이 없으면 0 을 싣는다 — 짐작하지 않는다.

    `alignment`(F-11)는 녹음이 이 자료의 발표인지만 본다 — 채점표가 폴백이라 결함 칸이 비어도 다른 발표 녹음을 놓치지 않게.
    """
    if isinstance(pace, dict):
        pace = PaceDoc.from_dict(pace)
    if isinstance(habits, dict):
        habits = HabitDoc.from_dict(habits)
    if isinstance(context, dict):
        context = Context.from_dict(context)
    if isinstance(rubric, dict):
        rubric = RubricScore.from_dict(rubric)
    if isinstance(alignment, dict):
        alignment = AlignmentDoc.from_dict(alignment)
    score = rubric.score if rubric else 0

    if _unrelated(rubric, alignment):
        return _unrelated_report(rubric, alignment, score)

    # llm 미지정이면 get_llm 기본 경로 — REASONING_BACKEND 와 REASONING_FALLBACK(예비) 를 함께 읽는다
    engine = llm if isinstance(llm, LLMProvider) else get_llm(None if llm is None else str(llm))

    if getattr(engine, "name", "") == "mock":
        return _honest(_checked(_fallback_report(pace, habits, model="mock", score=score), pace, habits), rubric)

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
        return _honest(_checked(doc, pace, habits), rubric)

    # 점수는 채점표가 진실이다 — 모듈 원칙("숫자는 다시 짐작하지 않습니다")대로
    # LLM 이 준 score/grade 는 무시한다. LLM 값을 받으면 같은 수치 입력인데
    # 실행마다 점수가 흔들리고, "85점" 같은 문자열이 오면 int() 가 터진다.
    has_body = any(_as_list(data.get(k)) for k in ("strengths", "weaknesses", "actions"))
    if not _as_text(data.get("one_liner")) and not has_body:
        # 파싱은 됐지만 알맹이가 없다({} 등) — 빈 리포트를 내보내느니 숫자로 조립한 폴백을 준다
        return _honest(_checked(_fallback_report(
            pace, habits, model=f"{getattr(engine, 'name', 'llm')}-fallback", score=score
        ), pace, habits), rubric)
    return _honest(_checked(ReportDoc(
        one_liner=_as_text(data.get("one_liner")),
        score=score,
        grade="",
        strengths=_as_list(data.get("strengths"))[:5],
        weaknesses=_as_list(data.get("weaknesses"))[:5],
        actions=_as_list(data.get("actions"))[:5],
        pace_summary=_as_text(data.get("pace_summary")) or " ".join(pace.tips[:2]),
        habit_summary=_as_text(data.get("habit_summary")) or " ".join(habits.tips[:2]),
        model=getattr(engine, "name", str(llm)),
    ), pace, habits), rubric)
