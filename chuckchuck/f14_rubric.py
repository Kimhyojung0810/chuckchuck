"""
[F-14] 발표 평가 채점표 v3 채점입니다.

`docs/발표평가_상황별_채점표_v3.xlsx` 의 39개 항목·7개 클러스터·4개 상황 가중치로
발표 하나를 0~100 점으로 묶습니다. F-13 과 달리 최종 점수의 모든 자릿수가
"어느 항목에서 몇 점을 받았고, 이 상황에서 가중치가 몇이라서, 이만큼 보탰다" 로
역추적됩니다.

설계에서 정한 것 넷:

1. **못 잰 항목은 0점이 아니다.** 가중치에서 빼고 남은 항목에 다시 나눠 준다.
   자료가 없어서 못 잰 것과 못해서 0점인 것은 완전히 다른 말이다.
2. **'이 상황에서 평가 안 함'과 '이번에 못 잼'은 다른 필드다.** 화면 문구가 다르다 —
   합치면 지금 걷어내는 그 블랙박스가 그대로 다시 생긴다.
3. **근거 없는 점수는 채택하지 않는다.** LLM 이 evidence 를 못 대면 그 항목은
   '못 쟀다'로 내린다. 근거 없는 숫자는 안 매긴 것만 못하다.
4. **입력은 전부 없어도 된다.** 부스에서 파이프라인 일부가 실패해도 점수가 나온다.
   없는 자료에 기대는 항목만 빠지고 나머지는 정상 채점된다.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

from . import rubric_v3
from ._json_text import extract_json_object
from ._rubric_det import Evidence, score_item
from .contracts import (
    AlignmentDoc,
    ConceptGraph,
    Context,
    FlowDiff,
    HabitDoc,
    PaceDoc,
    RubricClusterScore,
    RubricItemScore,
    RubricScore,
    SlideDoc,
    Transcript,
)
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm

# callers: score_rubric() ← bridge /api/v1/rubric, tests/test_rubric.py

#: LLM 채점 묶음. 클러스터 단위로 한 번씩 부르고 병렬로 돌린다.
#: `clarity` 는 LLM 항목이 18번 하나뿐이라 content 묶음에 얹는다 — 콜 하나를 아낀다.
LLM_BATCHES: dict[str, tuple[int, ...]] = {
    "content": (2, 3, 6, 18),
    "logic": (7, 8, 9, 10, 11, 12),
    "audience": (13, 14, 15, 16),
    "visual": (29, 35, 37, 39),
}

#: 항목이 기대는 자료. 하나라도 없으면 LLM 을 부르기 전에 '못 쟀다'로 내린다.
LLM_NEEDS: dict[int, tuple[str, ...]] = {
    2: ("transcript",), 3: ("transcript",), 6: ("transcript",),
    7: ("transcript",), 8: ("transcript",), 9: ("transcript",),
    10: ("transcript",), 11: ("transcript",), 12: ("transcript",),
    13: ("transcript",), 14: ("transcript",), 15: ("transcript",),
    16: ("transcript",), 18: ("transcript",),
    29: ("slides", "transcript"), 35: ("slides",), 37: ("slides",), 39: ("slides",),
}

#: 병렬 LLM 콜 수. 묶음이 4개라 그 이상은 의미가 없다.
MAX_WORKERS = 4
MAX_TOKENS = 2000
TEMPERATURE = 0.2

#: 프롬프트에 넣는 발화 전문 길이. 이보다 길면 앞뒤를 남기고 가운데를 줄인다.
PROMPT_SPEECH_CHARS = 3500
#: 프롬프트에 넣는 슬라이드 수와 슬라이드당 본문 길이.
PROMPT_SLIDE_MAX = 30
PROMPT_SLIDE_CHARS = 180
#: 프롬프트에 넣는 개념 노드 수 (비중 상위부터).
PROMPT_NODE_MAX = 12

_NA_NOTE = "음향 특징을 뽑지 않아서 이번엔 못 쟀어요"
_MOCK_STT_NOTE = "모의 음성이라 말속도와 정적을 잴 수 없어요"
_NO_DATA_NOTE = "필요한 자료가 없어서 이번엔 못 쟀어요"
_NO_DOC_NOTE = {
    "slides": "발표자료를 못 읽어서 이번엔 못 쟀어요",
    "transcript": "발화 기록이 없어서 이번엔 못 쟀어요",
}
_LLM_FAILED_NOTE = "채점을 마치지 못해서 이번엔 못 쟀어요"

SYSTEM_PROMPT = (
    "당신은 발표 평가자입니다. 아래 [자료] 에 실제로 있는 내용만 근거로 "
    "[채점 항목] 을 각각 0~100 점으로 매기세요.\n"
    "\n"
    "점수의 뜻 (이 구간을 지키세요):\n"
    "- 90~100 충분히 했다 · 70~89 했지만 아쉽다 · 40~69 부분적으로만 했다\n"
    "- 1~39 거의 못했다 · 0 아예 하지 않았다\n"
    "\n"
    "규칙:\n"
    "- **판단할 근거가 자료에 없으면 그 번호를 결과에서 아예 빼세요.**\n"
    "  0점은 '자료를 보니 안 했다'는 판정입니다. '모르겠다'를 0점으로 적지 마세요.\n"
    "- evidence 에는 [발화 전문] 이나 [슬라이드] 에서 **그대로 복사한 문장**을 넣으세요.\n"
    "  요약하거나, 항목 설명을 되풀이하거나, 비워 두면 그 항목은 버려집니다.\n"
    "- 항목마다 **서로 다른** 근거를 고르세요. 같은 문장을 모든 항목에 붙이지 마세요.\n"
    "- 자료에 없는 내용을 지어내지 마세요.\n"
    "- note 는 왜 그 점수인지 한 문장으로 씁니다. 해요체를 씁니다.\n"
    "- 요청한 번호만 채점하세요. 다른 번호를 만들지 마세요.\n"
    'JSON 만 출력: {"items":[{"no":정수,"score":0~100,"evidence":"자료에서 복사한 문장","note":"한 문장"}]}'
)

JSON_RETRY_NUDGE = (
    "\n\n앞 응답이 JSON 으로 읽히지 않았습니다. 설명이나 코드펜스 없이 "
    'JSON 객체 하나만 출력하세요: {"items":[{"no":1,"score":80,"evidence":"…","note":"…"}]}'
)


# ---------------------------------------------------------------------------
# 집계 — 채점표 '점수산정' 시트와 같은 공식. 산수는 여기에만 있다.
# ---------------------------------------------------------------------------

def _aggregate(situation: str, items: list[RubricItemScore]) -> RubricScore:
    """
    항목 39개 → 클러스터 7개 → 최종 점수.

    순수 함수다. I/O 도 LLM 도 없다 — 테스트가 항목 점수를 손으로 넣어 공식만 검증한다.

    같은 클러스터 안에서는 내부 가중치로 가중평균한다 (채점표가 말하는 '중복 완화').
    빠진 클러스터의 가중치는 남은 클러스터에 비례 재분배한다.
    """
    label = rubric_v3.situation_label(situation)

    scored_by_cluster: dict[str, list[RubricItemScore]] = {k: [] for k in rubric_v3.CLUSTERS}
    for it in items:
        if it.cluster in scored_by_cluster and it.status == "scored" and it.weight > 0:
            scored_by_cluster[it.cluster].append(it)

    clusters: list[RubricClusterScore] = []
    for key, name in rubric_v3.CLUSTERS.items():
        weight = rubric_v3.cluster_weight(key, situation)
        members = scored_by_cluster[key]
        if weight <= 0 or not members:
            clusters.append(
                RubricClusterScore(key=key, name=name, weight=weight, status="omitted")
            )
            continue
        wsum = sum(m.weight for m in members)
        clusters.append(RubricClusterScore(
            key=key,
            name=name,
            weight=weight,
            average=sum(m.score * m.weight for m in members) / wsum,
            item_nos=sorted(m.no for m in members),
            status="scored",
        ))

    excluded = sorted(i.no for i in items if i.status == "situation_excluded")
    unmeasured = sorted(i.no for i in items if i.status == "unmeasured")
    # 영구 측정 불가 항목(음량·강조)은 basis 계산에서 뺀다. 이 둘까지 세면
    # basis 가 영영 full 이 못 되고, 늘 켜진 경고는 아무도 안 읽는다.
    missed = [i for i in items if i.status == "unmeasured" and i.source != "na"]
    basis = "partial" if missed else "full"

    present = [c for c in clusters if c.status == "scored"]
    if not present:
        # 잴 수 있는 항목이 하나도 없다. 0 으로 나누지 말고 여기서 끝낸다.
        # 입력이 전부 optional 이라 실제로 도달하는 경로다 (빈 바디 요청).
        return RubricScore(
            score=0,
            situation=situation,
            situation_label=label,
            clusters=clusters,
            items=items,
            excluded=excluded,
            unmeasured=unmeasured,
            basis="partial",
            note="이번엔 매길 수 있는 항목이 없었어요",
        )

    total_weight = sum(c.weight for c in present)
    for c in present:
        c.effective_weight = c.weight / total_weight
        c.contribution = c.average * c.effective_weight

    score = int(round(max(0.0, min(100.0, sum(c.contribution for c in present)))))
    return RubricScore(
        score=score,
        situation=situation,
        situation_label=label,
        clusters=clusters,
        items=items,
        excluded=excluded,
        unmeasured=unmeasured,
        basis=basis,
    )


# ---------------------------------------------------------------------------
# 항목 준비 — 결정 채점까지
# ---------------------------------------------------------------------------

def _blank(
    item: rubric_v3.RubricItem, situation: str, status: str, note: str = ""
) -> RubricItemScore:
    return RubricItemScore(
        no=item.no,
        cluster=item.cluster,
        name=item.name,
        status=status,
        score=0,
        weight=item.weight_for(situation),
        source=item.source,
        note=note,
    )


def _has(ev: Evidence, doc: str) -> bool:
    return getattr(ev, doc, None) is not None


def _score_deterministic(situation: str, ev: Evidence) -> tuple[list[RubricItemScore], list[int]]:
    """
    코드로 매길 수 있는 것을 다 매기고, LLM 이 맡을 항목 번호를 함께 돌려준다.

    Returns:
        (항목 결과 39개, LLM 이 채점해야 할 항목 번호)
    """
    results: list[RubricItemScore] = []
    pending: list[int] = []

    for item in rubric_v3.ITEMS:
        weight = item.weight_for(situation)
        if weight == 0:
            results.append(_blank(item, situation, "situation_excluded"))
            continue

        if item.source == "na":
            results.append(_blank(item, situation, "unmeasured", _NA_NOTE))
            continue

        if item.source == "det":
            got = score_item(item.no, ev)
            if got is None:
                mock = ev.is_mock_stt and item.cluster == "delivery"
                results.append(
                    _blank(item, situation, "unmeasured", _MOCK_STT_NOTE if mock else _NO_DATA_NOTE)
                )
                continue
            value, evidence = got
            results.append(RubricItemScore(
                no=item.no, cluster=item.cluster, name=item.name, status="scored",
                score=value, weight=weight, source="det", evidence=evidence,
            ))
            continue

        # llm — 기대는 자료가 없으면 부르기 전에 내린다
        missing = [d for d in LLM_NEEDS.get(item.no, ()) if not _has(ev, d)]
        if missing:
            results.append(_blank(item, situation, "unmeasured", _NO_DOC_NOTE[missing[0]]))
            continue
        results.append(_blank(item, situation, "unmeasured", _LLM_FAILED_NOTE))
        pending.append(item.no)

    return results, pending


# ---------------------------------------------------------------------------
# LLM 채점
# ---------------------------------------------------------------------------

def _clip(text: str, limit: int) -> str:
    """길면 가운데를 줄인다. 도입과 결론이 살아 있어야 논리 항목을 볼 수 있다."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    head = limit * 2 // 3
    return f"{flat[:head]}\n…(가운데 줄임)…\n{flat[-(limit - head):]}"


def _slides_block(ev: Evidence) -> str:
    if not ev.slides or not ev.slides.slides:
        return ""
    lines = ["[슬라이드]"]
    for s in ev.slides.slides[:PROMPT_SLIDE_MAX]:
        visual = ",".join(s.visual_type) or "-"
        body = " ".join(s.raw_text.split())[:PROMPT_SLIDE_CHARS]
        lines.append(f"- {s.slide_no}번 | 제목: {s.title or '-'} | 시각요소: {visual} | 본문: {body}")
    if len(ev.slides.slides) > PROMPT_SLIDE_MAX:
        lines.append(f"- …외 {len(ev.slides.slides) - PROMPT_SLIDE_MAX}장")
    return "\n".join(lines)


def _concepts_block(ev: Evidence) -> str:
    if not ev.graph or not ev.graph.nodes:
        return ""
    top = sorted(ev.graph.nodes, key=lambda n: n.weight, reverse=True)[:PROMPT_NODE_MAX]
    lines = ["[자료의 핵심 개념 — 비중 높은 순]"]
    lines += [f"- {n.label} (비중 {n.weight:.2f}, 슬라이드 {n.slide_nos or '-'})" for n in top]
    if ev.graph.sections:
        roles = " / ".join(f"{s.name}({s.slide_role}): {s.slide_nos}" for s in ev.graph.sections)
        lines.append(f"[구간] {roles}")
    return "\n".join(lines)


def _flow_block(ev: Evidence) -> str:
    flow = ev.flow
    if not isinstance(flow, FlowDiff) or not flow.issues:
        return ""
    lines = ["[코드가 잡은 흐름 문제 — 참고용]"]
    for issue in flow.issues[:8]:
        lines.append(f"- {issue.kind}: {issue.note or issue.cue or ''} (슬라이드 {issue.slide_nos})")
    if flow.order_tau is not None:
        lines.append(f"- 자료 순서와 발화 순서의 상관: {flow.order_tau:+.2f}")
    return "\n".join(lines)


def _speech_block(ev: Evidence) -> str:
    if not ev.transcript:
        return ""
    lines = ["[발화 전문]", _clip(ev.full_text, PROMPT_SPEECH_CHARS)]
    by_slide = ev.transcript.by_slide
    if by_slide:
        first, last = by_slide[0], by_slide[-1]
        lines.append(f"[도입 구간 발화 — {first.slide_no}번] {_clip(first.text, 400)}")
        lines.append(f"[결론 구간 발화 — {last.slide_no}번] {_clip(last.text, 400)}")
    return "\n".join(lines)


def _build_prompt(ev: Evidence, nos: list[int]) -> str:
    ctx = [
        "[TASK] rubric-score",
        "[자료]",
        f"발표 상황: {rubric_v3.situation_label(ev.situation)}",
        # 청중을 안 알려 주면 모델이 13·14 번을 근거 없이 0점 처리한다.
        # 모른다는 사실 자체를 알려 줘야 '상황으로 미루어 판단' 한다.
        f"청중: {ev.audience or '따로 안 알려 줬어요 — 발표 상황으로 미루어 판단하세요'}",
        f"목표 시간: {f'{ev.duration_min}분' if ev.duration_min else '따로 안 알려 줬어요'}",
    ]
    for block in (_concepts_block(ev), _slides_block(ev), _flow_block(ev), _speech_block(ev)):
        if block:
            ctx.append(block)

    ctx.append("[채점 항목]")
    for no in nos:
        item = rubric_v3.ITEM_BY_NO[no]
        ctx.append(f"- ({no}) {item.name}: {item.description}")
    ctx.append("[END] JSON 만 출력하세요.")
    return "\n".join(ctx)


#: 근거로 인정하는 최소 길이. 이보다 짧으면 인용이 아니라 얼버무림이다.
MIN_EVIDENCE_CHARS = 8


def _normalize_llm(data: dict, asked: list[int]) -> dict[int, tuple[int, str, str]]:
    """
    LLM 응답을 계약으로 눌러 담는다.

    버리는 것 넷 — 전부 실 API 응답에서 실제로 나온 것들이다:

    1. 요청하지 않은 번호
    2. `score` 키가 아예 없는 항목. 예전에는 0 으로 채웠는데, 그러면 모델이
       판단을 안 한 항목이 "0점 = 아예 안 했다" 로 둔갑한다.
    3. 근거가 비었거나 너무 짧은 항목. 근거 없는 숫자는 안 매긴 것만 못하다.
    4. **근거가 우리가 준 항목 설명을 그대로 되뱉은 항목.** solar 가
       "핵심 주장 제시 시점: 발표 목적과 핵심 주장이…" 처럼 프롬프트를 복사해
       근거 자리에 넣고 0점을 준 적이 있다. 그건 채점이 아니라 메아리다.
    """
    allowed = set(asked)
    # 되뱉음 판별용. 채점표 문구는 발표에 나올 수 없는 말이라, 근거 안에 이게 들어 있으면
    # 모델이 프롬프트를 복사한 것이다. 물어본 항목만이 아니라 39개 전부를 본다 —
    # 옆 항목 설명을 가져다 붙이는 경우도 있다.
    _RUBRIC_WORDING = {i.description for i in rubric_v3.ITEMS} | {i.name for i in rubric_v3.ITEMS}

    out: dict[int, tuple[int, str, str]] = {}
    for row in data.get("items") or []:
        if not isinstance(row, dict):
            continue
        try:
            no = int(row.get("no"))
        except (TypeError, ValueError):
            continue
        if no not in allowed or "score" not in row:
            continue
        try:
            score = int(float(row.get("score")))
        except (TypeError, ValueError):
            continue

        evidence = " ".join(str(row.get("evidence") or "").split())
        if len(evidence) < MIN_EVIDENCE_CHARS:
            continue
        if any(wording in evidence for wording in _RUBRIC_WORDING):
            continue

        note = " ".join(str(row.get("note") or "").split())
        out[no] = (max(0, min(100, score)), evidence, note)
    return out


def _ask_batch(
    engine: LLMProvider, ev: Evidence, nos: list[int]
) -> dict[int, tuple[int, str, str]]:
    """묶음 하나를 채점한다. 두 번 실패하면 빈 dict — 그 항목만 '못 쟀다'가 된다."""
    user = _build_prompt(ev, nos)
    for nudge in ("", JSON_RETRY_NUDGE):
        try:
            raw = engine.complete(
                system=SYSTEM_PROMPT + nudge,
                user=user,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                json_mode=True,
            )
            return _normalize_llm(extract_json_object(raw), nos)
        except Exception:  # noqa: BLE001 — 묶음 하나가 죽어도 나머지 채점은 계속한다
            continue
    return {}


def _score_llm(
    engine: LLMProvider, ev: Evidence, pending: list[int]
) -> dict[int, tuple[int, str, str]]:
    """묶음별로 병렬 채점. 한 묶음이 실패해도 다른 묶음은 살아남는다."""
    want = set(pending)
    batches = [[no for no in nos if no in want] for nos in LLM_BATCHES.values()]
    batches = [b for b in batches if b]
    if not batches:
        return {}

    merged: dict[int, tuple[int, str, str]] = {}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(batches))) as pool:
        for got in pool.map(lambda nos: _ask_batch(engine, ev, nos), batches):
            merged.update(got)
    return merged


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------

def _coerce(value, cls):
    return cls.from_dict(value) if isinstance(value, dict) else value


def from_legacy_score(legacy, situation: str | None = None) -> RubricScore:
    """
    F-13 `PresentationScore` 를 RubricScore 모양으로 옮긴다 — 채점 실패 시 폴백.

    부스에서 점수가 아예 안 뜨는 것보다 예전 방식으로라도 뜨는 게 낫다.
    다만 폴백인 걸 숨기지 않는다: `rubric_version` 이 `"v3-fallback"` 이고
    39개 항목이 전부 `unmeasured` 다.

    f13 의 `components[].raw` 는 0~1 이고 새 계약의 `average` 는 0~100 이다.
    **스케일 변환을 빠뜨리면 막대가 전부 1% 로 그려진다.**
    """
    resolved, note = rubric_v3.resolve_situation(situation)
    clusters = [
        RubricClusterScore(
            key=c.key,
            name=c.label,
            weight=int(round(c.weight * 100)),
            effective_weight=c.weight,      # f13 이 이미 합 1.0 으로 정규화해 둔다
            average=c.raw * 100.0,          # 0~1 → 0~100
            contribution=c.contribution,
            status="scored",
        )
        for c in legacy.components
    ]
    return RubricScore(
        score=legacy.score,
        situation=resolved,
        situation_label=rubric_v3.situation_label(resolved),
        rubric_version=f"{rubric_v3.RUBRIC_VERSION}-fallback",
        clusters=clusters,
        items=[],
        excluded=[],
        unmeasured=[i.no for i in rubric_v3.ITEMS],
        basis="partial",
        note=" · ".join(n for n in (note, "채점표로 매기지 못해서 예전 방식으로 매겼어요") if n),
    )


def score_rubric(
    *,
    situation: str | None = None,
    context: Context | dict | None = None,
    slides: SlideDoc | dict | None = None,
    concepts: object = None,          # ConceptDoc. 지금은 안 쓰지만 계약을 열어 둔다
    graph: ConceptGraph | dict | None = None,
    transcript: Transcript | dict | None = None,
    alignment: AlignmentDoc | dict | None = None,
    flow: FlowDiff | dict | None = None,
    pace: PaceDoc | dict | None = None,
    habits: HabitDoc | dict | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> RubricScore:
    """
    채점표 v3 로 발표 하나를 0~100 점으로 매긴다.

    **입력은 전부 없어도 된다.** 없는 자료에 기대는 항목만 '못 쟀다'가 되고,
    그 가중치는 남은 항목에 다시 나뉜다. 아무것도 못 재면 0점과 안내 문구를 낸다
    (예외를 던지지 않는다 — 부스에서 화면이 비는 것보다 낫다).
    """
    context = _coerce(context, Context)
    raw_situation = situation or (context.situation if context else None)
    resolved, situation_note = rubric_v3.resolve_situation(raw_situation)

    ev = Evidence(
        situation=resolved,
        audience=(context.audience if context else "") or "",
        duration_min=(context.duration_min if context else None),
        slides=_coerce(slides, SlideDoc),
        graph=_coerce(graph, ConceptGraph),
        transcript=_coerce(transcript, Transcript),
        alignment=_coerce(alignment, AlignmentDoc),
        flow=_coerce(flow, FlowDiff),
        pace=_coerce(pace, PaceDoc),
        habits=_coerce(habits, HabitDoc),
    )

    items, pending = _score_deterministic(resolved, ev)

    model = ""
    if pending:
        if llm is None:
            llm = os.environ.get("REASONING_BACKEND", "solar")
        engine = llm if isinstance(llm, LLMProvider) else get_llm(str(llm), **(llm_kwargs or {}))
        model = getattr(engine, "name", str(llm))
        graded = _score_llm(engine, ev, pending)
        by_no = {i.no: i for i in items}
        for no, (score, evidence, note) in graded.items():
            row = by_no.get(no)
            if row is None:
                continue
            row.status = "scored"
            row.score = score
            row.evidence = evidence
            row.note = note

    result = _aggregate(resolved, items)
    result.model = model
    result.note = " · ".join(n for n in (situation_note, result.note) if n)
    return result
