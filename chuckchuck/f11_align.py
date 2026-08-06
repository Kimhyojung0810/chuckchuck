"""
[F-11] 발화가 개념 그래프를 얼마나 잘 다뤘는지 판정하는 모듈입니다.
ConceptGraph + Transcript → AlignmentDoc.

발화 그래프를 독립 추출해 문서 그래프와 비교하지 않습니다 — LLM 추출 분산이
두 배가 되어 diff 가 노이즈를 측정하게 됩니다. 대신 문서 그래프를 기준축으로:
- speech_weight(발화 축)는 코드가 결정적으로 계산하고,
- LLM 은 4-class 판정·근거 인용·발화 간선·발화 전용 개념만 맡습니다.
  이때 노드 목록을 후보 앵커로 줘서 node_id 로 조인해 돌려받습니다 (조건화 추출).

    from chuckchuck.f11_align import align_speech
    alignment = align_speech(graph, transcript, context, llm="solar")
"""

from __future__ import annotations

import os

from ._json_text import extract_json_object
from ._match import (
    contains_tokens,
    count_occurrences,
    first_match_index,
    label_tokens,
    norm_tokens,
)
from .contracts import (
    ALIGN_VERDICTS,
    AlignError,
    AlignmentDoc,
    AlignmentItem,
    AlignmentSummary,
    ConceptGraph,
    Context,
    ExtraConcept,
    SpeechBasis,
    SpeechEdge,
    Transcript,
)
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm

MAX_TOKENS = int(os.environ.get("CHUCKCHUCK_ALIGN_MAX_TOKENS", "8192"))

# speech_weight 배합. 합 1.0. F-07 weight 와 같은 철학 — 최댓값 정규화(상대 서열).
_S_TIME = 0.45          # 근거 장 발화 시간 / 전체 발화 시간
_S_MENTION = 0.35       # 발화 내 언급 횟수 / 그래프 내 최댓값
_S_SLIDE_COVER = 0.20   # label 이 언급된 근거 장 수 / 근거 장 수

# 무언급 '정당생략' 가드. 자료 weight 가 이 값 이상인 개념은 발화에 한 번도
# 안 나왔으면 justified_skip 을 missing 으로 강등한다 — justified_skip 은
# coverage 분모에서 빠지는 판정이라, LLM 이 후하게 주면 헤드라인 점수가 부푼다.
SKIP_GUARD_WEIGHT = float(os.environ.get("CHUCKCHUCK_SKIP_GUARD_WEIGHT", "0.35"))

# 정합으로 인정할 최소 언급 횟수.
#
# 1 이면 슬라이드 제목 낱말을 스치듯 한 번 말한 것도 "설명했다"가 된다. 실제로
# 리포트가 전부 초록으로 떠서 못한 발표도 잘한 것처럼 보였다 (2026-08-07 지시).
# 2 는 "한 번은 우연, 두 번은 설명" 이라는 기준이다.
#
# 시연 직전에도 조일 수 있게 환경변수로 뺐다 — 심사위원이 후한 판정을 눈치채면
# 리포트 전체의 신뢰가 같이 무너진다.
MENTION_MIN = max(1, int(os.environ.get("CHUCKCHUCK_ALIGN_MENTION_MIN", "2")))

SYSTEM_PROMPT = """당신은 발표 리허설 평가자다.
'개념 목록'(발표 자료에서 뽑은 개념들)과 '슬라이드별 발화'를 대조해,
개념마다 발화가 자료와 정합했는지 판정한다.

verdict 는 다음 넷 중 하나다:
- "aligned" (정합): 발화가 이 개념을 실제로 설명했고 자료와 부합한다.
- "justified_skip" (정당생략): 설명하지 않았지만 생략이 합리적이다.
  보조 개념이거나, 다른 개념을 설명하며 자연스럽게 포함된 경우다.
- "missing" (누락): 설명했어야 하는데 발화에 없다.
- "contradiction" (모순): 발화 내용이 자료와 어긋난다.

규칙:
1. items 에는 개념 목록의 모든 id 가 정확히 한 번씩 나와야 한다. id 를 지어내지 마라.
2. evidence 는 발화에서 그대로 인용한다. 지어내지 마라.
   aligned 와 contradiction 은 evidence 가 필수다. 근거 없는 모순 판정은 버려진다.
3. speech_edges 는 발표자가 **말로** 두 개념을 연결한 경우만 적는다
   ("그래서", "왜냐하면", "이걸 바탕으로" 같은 연결 발화). cue 에 그 발화를 인용하라.
   from/to 는 개념 목록의 id 다. 두 개념을 각자 말한 것만으로는 연결이 아니다.
4. extra_concepts 는 발화에는 있는데 개념 목록에 없는 **실질적 개념**만 적는다.
   인사말·자기소개·군더더기는 개념이 아니다.
5. 판정은 내용 기준이다. 말투·발음 같은 스타일 평가를 하지 마라.
6. 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마:
{
  "items": [
    { "node_id": "contrast", "verdict": "aligned",
      "evidence": "발화 인용", "note": "한 줄 설명" }
  ],
  "speech_edges": [
    { "from": "contrast", "to": "joint", "cue": "그래서 이 손실로 정렬합니다" }
  ],
  "extra_concepts": [
    { "label": "개념 이름", "quote": "발화 인용", "slide_no": 3 }
  ]
}
"""

#: 응답이 복구 불가능한 JSON 일 때 한 번 더 물어볼 때 덧붙이는 말.
JSON_RETRY_NUDGE = """
[재요청] 직전 응답이 완전한 JSON 객체가 아니어서 버렸다.
코드펜스·주석·말머리·말끝 문장 없이, 출력 스키마 그대로의 JSON 객체 하나만 다시 출력하라.
"""

#: items 가 통째로 비어 돌아왔을 때 한 번 더 물어볼 때 덧붙이는 말.
EMPTY_RETRY_NUDGE = """
[재요청] 직전 응답의 items 가 비어 있었다. 판정이 하나도 없으면 쓸 수 없다.
개념 목록의 모든 id 에 대해 verdict 를 하나씩 판정해 items 를 채워라.
"""


# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------

def _build_user_prompt(graph: ConceptGraph, transcript: Transcript, ctx: Context) -> str:
    """
    노드 목록을 후보 앵커로 먼저, 슬라이드별 발화를 나중에 둔다.

    F-07 실측 교훈의 재적용: 판정 대상(개념)을 앞에 둬야 모델이
    발화를 개념에 매핑하지, 발화를 새 개념으로 다시 뽑지 않는다.
    """
    parts = [
        "[TASK] speech-alignment",
        ctx.to_prompt_block(),
        "",
        f"파일명: {graph.file_name}",
        f"총 슬라이드: {graph.total_slides}",
        "",
        "## 개념 목록 — 판정 대상. items 에 이 id 가 전부 나와야 한다",
        "(id) 개념이름 [근거 슬라이드] — 한 줄 설명. w= 는 자료가 배분한 중요도다.",
        "",
    ]
    for n in graph.by_weight:
        nos = ",".join(str(x) for x in n.slide_nos)
        line = f"- ({n.id}) {n.label} [S{nos}] w={n.weight}"
        if n.summary:
            line += f" — {n.summary}"
        parts.append(line)

    parts += ["", "## 슬라이드별 발화", ""]
    slide_nos = sorted({s.slide_no for s in transcript.by_slide})
    for no in slide_nos:
        text = transcript.text_for_slide(no).strip()
        parts.append(f"### 슬라이드 {no}")
        parts.append(text if text else "(발화 없음)")
    if not slide_nos:
        parts.append(transcript.full_text.strip() or "(발화 없음)")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 발화 축 — 결정적 신호 (LLM 아님)
# ---------------------------------------------------------------------------

def _total_speech_sec(transcript: Transcript) -> float:
    total = sum(s.end_sec - s.start_sec for s in transcript.by_slide)
    return total if total > 0 else max(0.0, transcript.duration_sec)


def _speech_bases(graph: ConceptGraph, transcript: Transcript) -> dict[str, SpeechBasis]:
    """노드별 SpeechBasis. 전부 marks·토큰 매칭에서 나오는 결정적 값이다."""
    total_sec = _total_speech_sec(transcript)

    sec_by_slide: dict[int, float] = {}
    for s in transcript.by_slide:
        sec_by_slide[s.slide_no] = sec_by_slide.get(s.slide_no, 0.0) + max(
            0.0, s.end_sec - s.start_sec
        )
    tokens_by_slide = {
        no: norm_tokens(transcript.text_for_slide(no)) for no in sec_by_slide
    }
    full_tokens = norm_tokens(transcript.full_text)
    if not full_tokens:
        full_tokens = [t for toks in tokens_by_slide.values() for t in toks]

    # 단어별 시각이 있으면 첫 언급 시각을 잡는다 (mock 은 words 가 없을 수 있다)
    timed: list[tuple[str, float]] = [
        (tok, w.start_sec) for w in transcript.words for tok in norm_tokens(w.text)
    ]
    timed_tokens = [t for t, _ in timed]

    bases: dict[str, SpeechBasis] = {}
    for node in graph.nodes:
        speech_sec = sum(sec_by_slide.get(no, 0.0) for no in node.slide_nos)
        tokens = label_tokens(node.label)
        mentioned_slides = sum(
            1
            for no in node.slide_nos
            if contains_tokens(tokens_by_slide.get(no, []), tokens)
        )
        first: float | None = None
        if timed:
            idx = first_match_index(timed_tokens, tokens)
            if idx is not None:
                first = round(timed[idx][1], 3)
        bases[node.id] = SpeechBasis(
            speech_sec=round(speech_sec, 2),
            time_share=round(speech_sec / total_sec, 4) if total_sec else 0.0,
            mention_count=count_occurrences(node.label, full_tokens),
            mentioned_slide_count=mentioned_slides,
            first_mention_sec=first,
        )
    return bases


def _apply_speech_weights(items: list[AlignmentItem], graph: ConceptGraph) -> None:
    """speech_weight 를 채운다. F-07 weight 처럼 최댓값 정규화 — 서열이 목적이다."""
    slide_count = {n.id: len(n.slide_nos) for n in graph.nodes}
    top_mention = max((i.speech_basis.mention_count for i in items), default=0)

    raws: list[float] = []
    for item in items:
        b = item.speech_basis
        covered = slide_count.get(item.node_id, 0)
        raws.append(
            _S_TIME * min(1.0, b.time_share)
            + _S_MENTION * (b.mention_count / top_mention if top_mention else 0.0)
            + _S_SLIDE_COVER * (b.mentioned_slide_count / covered if covered else 0.0)
        )
    top = max(raws, default=0.0)
    for item, raw in zip(items, raws):
        item.speech_weight = round(raw / top, 3) if top > 0 else 0.0


# ---------------------------------------------------------------------------
# 판정 후처리 — LLM 판정을 결정적 신호와 대조해 다듬는다
# ---------------------------------------------------------------------------

def _fallback_verdict(basis: SpeechBasis) -> str:
    """LLM 판정이 없거나 못 믿을 때: 충분히 언급했으면 정합, 아니면 누락."""
    return "aligned" if basis.mention_count >= MENTION_MIN else "missing"


def _normalize_items(
    raw_items: list[dict],
    graph: ConceptGraph,
    bases: dict[str, SpeechBasis],
) -> list[AlignmentItem]:
    """
    raw 판정을 그래프의 모든 노드에 정확히 1개씩으로 정리한다.

    - 없는 node_id 를 가리키는 판정은 버린다. 같은 node_id 가 여러 번 오면 첫 번째만
    - verdict 가 enum 밖이면 결정적 폴백으로 대체
    - missing 인데 label 이 발화에 MENTION_MIN 회 이상 등장하면 aligned 로 정정
      (토큰 매칭이 프롬프트 널뛰기보다 믿을 만하다. 단 1회는 스친 것이지
       설명한 것이 아니라서, 그 한 번으로 LLM 의 '누락' 판정을 뒤집지 않는다)
    - evidence 없는 contradiction 은 결정적 폴백으로 강등
      (사용자에게 "틀렸다"고 말하는 판정이라 근거 없이는 내보내지 않는다)
    - evidence 없는 aligned 도 같은 이유로 강등
      ("잘했다"도 근거가 있어야 한다. 이걸 안 걸러서 모델이 전부 aligned 로
       도장 찍은 리포트가 나갔다 — 17/17 초록, coverage 1.0)
    - justified_skip 인데 언급 0회 + doc weight ≥ SKIP_GUARD_WEIGHT 면
      missing 으로 강등 (자료가 힘준 개념은 무언급이 '정당한 생략'일 수 없다)
    """
    node_ids = {n.id for n in graph.nodes}
    judged: dict[str, dict] = {}
    for raw in raw_items:
        nid = str(raw.get("node_id", "") or "")
        if nid in node_ids and nid not in judged:
            judged[nid] = raw

    items: list[AlignmentItem] = []
    for node in graph.nodes:
        basis = bases[node.id]
        raw = judged.get(node.id)
        evidence = str((raw or {}).get("evidence", "") or "").strip()
        note = str((raw or {}).get("note", "") or "").strip()

        verdict = str((raw or {}).get("verdict", "") or "")
        if verdict not in ALIGN_VERDICTS:
            verdict = _fallback_verdict(basis)
        if verdict == "missing" and basis.mention_count >= MENTION_MIN:
            verdict = "aligned"
        if verdict == "contradiction" and not evidence:
            verdict = _fallback_verdict(basis)
        # 근거 없는 aligned 도 버린다. 프롬프트는 aligned 에 evidence 를 필수로
        # 요구하는데(SYSTEM_PROMPT) 코드는 contradiction 만 검사하고 있었다.
        # 그래서 모델이 근거 없이 전부 '잘했다'로 도장 찍으면 그대로 통과했다 —
        # 실측으로 17개 개념이 전부 aligned, coverage 1.0 이 나왔다.
        # "틀렸다"를 근거 없이 말하지 않는다면 "잘했다"도 마찬가지여야 한다.
        if verdict == "aligned" and not evidence:
            verdict = _fallback_verdict(basis)
        if (
            verdict == "justified_skip"
            and basis.mention_count == 0
            and node.weight >= SKIP_GUARD_WEIGHT
        ):
            verdict = "missing"

        items.append(AlignmentItem(
            node_id=node.id,
            verdict=verdict,
            speech_basis=basis,
            doc_weight=node.weight,
            evidence=evidence,
            note=note,
        ))
    return items


def _undirected_pairs(edges) -> set[frozenset]:
    return {
        frozenset((e.from_id, e.to_id)) for e in edges if e.from_id != e.to_id
    }


def _normalize_speech_edges(raw_edges: list[dict], graph: ConceptGraph) -> list[SpeechEdge]:
    """양끝이 존재하는 id 만, 자기 간선 금지, 방향 무시 중복 제거, in_graph 파생."""
    node_ids = {n.id for n in graph.nodes}
    graph_pairs = _undirected_pairs(graph.edges)

    out: list[SpeechEdge] = []
    seen: set[frozenset] = set()
    for raw in raw_edges:
        src, dst = str(raw.get("from", "") or ""), str(raw.get("to", "") or "")
        if src not in node_ids or dst not in node_ids or src == dst:
            continue
        pair = frozenset((src, dst))
        if pair in seen:
            continue
        seen.add(pair)
        out.append(SpeechEdge(
            from_id=src,
            to_id=dst,
            cue=str(raw.get("cue", "") or "").strip(),
            in_graph=pair in graph_pairs,
        ))
    return out


def _normalize_extras(raw_extras: list[dict], graph: ConceptGraph) -> list[ExtraConcept]:
    """그래프에 이미 있는 개념·빈 label 은 버린다. slide_no 는 범위 검증."""
    node_token_lists = [label_tokens(n.label) for n in graph.nodes]

    out: list[ExtraConcept] = []
    seen: list[list[str]] = []
    for raw in raw_extras:
        label = str(raw.get("label", "") or "").strip()
        tokens = label_tokens(label)
        if not tokens:
            continue
        if any(
            contains_tokens(nt, tokens) or contains_tokens(tokens, nt)
            for nt in node_token_lists if nt
        ):
            continue  # 이미 그래프에 있는 개념 — LLM 이 '새 개념'으로 착각한 것
        if any(contains_tokens(s, tokens) or contains_tokens(tokens, s) for s in seen):
            continue
        seen.append(tokens)

        slide_no = raw.get("slide_no")
        try:
            slide_no = int(slide_no)
        except (TypeError, ValueError):
            slide_no = None
        if slide_no is not None and not (1 <= slide_no <= graph.total_slides):
            slide_no = None
        out.append(ExtraConcept(
            label=label,
            quote=str(raw.get("quote", "") or "").strip(),
            slide_no=slide_no,
        ))
    return out


# ---------------------------------------------------------------------------
# 요약 지표 — 전부 코드 계산
# ---------------------------------------------------------------------------

def _ranks(values: list[float]) -> list[float]:
    """평균 순위 (동순위는 평균). Spearman 용."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman 순위 상관. 표본 2개 미만이거나 한쪽이 전부 동률이면 None."""
    if len(xs) < 2:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx * vy) ** 0.5


def _summarize(
    items: list[AlignmentItem],
    speech_edges: list[SpeechEdge],
    graph: ConceptGraph,
    transcript: Transcript,
) -> AlignmentSummary:
    counts = {v: 0 for v in ALIGN_VERDICTS}
    for i in items:
        counts[i.verdict] += 1

    # coverage: 정당생략을 뺀 전체 weight 중 정합이 차지하는 비중.
    # 중요 개념(누락·모순)을 빼먹을수록 크게 깎인다.
    scored = [i for i in items if i.verdict != "justified_skip"]
    denom = sum(i.doc_weight for i in scored)
    aligned = sum(i.doc_weight for i in scored if i.verdict == "aligned")
    coverage = round(aligned / denom, 3) if denom > 0 else 1.0

    rank = _spearman(
        [i.doc_weight for i in items], [i.speech_weight for i in items]
    )

    graph_pairs = _undirected_pairs(graph.edges)
    edge_cov: float | None = None
    if graph_pairs:
        spoken = _undirected_pairs(speech_edges)
        edge_cov = round(len(graph_pairs & spoken) / len(graph_pairs), 3)

    return AlignmentSummary(
        coverage=coverage,
        rank_correlation=None if rank is None else round(rank, 3),
        edge_coverage=edge_cov,
        verdict_counts=counts,
        speech_total_sec=round(_total_speech_sec(transcript), 2),
    )


# ---------------------------------------------------------------------------
# LLM 호출
# ---------------------------------------------------------------------------

def _call(
    engine: LLMProvider,
    graph: ConceptGraph,
    transcript: Transcript,
    ctx: Context,
    *,
    extra_system: str = "",
) -> dict:
    raw = engine.complete(
        system=SYSTEM_PROMPT + extra_system,
        user=_build_user_prompt(graph, transcript, ctx),
        temperature=0.2,
        max_tokens=MAX_TOKENS,
        json_mode=True
    )
    try:
        return extract_json_object(raw)
    except ValueError as e:
        raise AlignError(f"LLM 응답에서 판정 JSON 을 찾지 못했습니다: {e}") from e


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------

def align_speech(
    graph: ConceptGraph | dict,
    transcript: Transcript | dict,
    context: Context | dict | None = None,
    *,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> AlignmentDoc:
    """
    ConceptGraph + Transcript (+선택 Context) → AlignmentDoc.

    speech_weight 는 marks·토큰 매칭에서 결정적으로 계산하고,
    LLM 은 4-class 판정·근거 인용·발화 간선·발화 전용 개념만 맡는다.
    LLM 이 빠뜨린 노드는 결정적 폴백(언급 있으면 정합, 없으면 누락)으로 채운다.
    """
    if isinstance(graph, dict):
        graph = ConceptGraph.from_dict(graph)
    if isinstance(transcript, dict):
        transcript = Transcript.from_dict(transcript)
    if not graph.nodes:
        raise AlignError("ConceptGraph 에 노드가 없습니다. F-07 결과를 먼저 확인하세요.")
    if not transcript.by_slide and not transcript.full_text.strip():
        raise AlignError("Transcript 가 비어 있습니다. F-05 결과를 먼저 확인하세요.")

    if context is None:
        ctx = Context()
    elif isinstance(context, dict):
        ctx = Context.from_dict(context)
    else:
        ctx = context

    engine = llm if isinstance(llm, LLMProvider) else get_llm(llm, **(llm_kwargs or {}))

    try:
        data = _call(engine, graph, transcript, ctx)
    except AlignError:
        # 파싱 실패는 대부분 그 실행의 출력 문제다. 한 번은 다시 묻고, 또 깨지면 실패로 둔다
        data = _call(engine, graph, transcript, ctx, extra_system=JSON_RETRY_NUDGE)

    raw_items = [i for i in (data.get("items") or []) if isinstance(i, dict)]
    if not raw_items:
        # 판정이 통째로 비면 한 번 재요청. 그래도 비면 전 노드 결정적 폴백으로 간다
        try:
            retry = _call(engine, graph, transcript, ctx, extra_system=EMPTY_RETRY_NUDGE)
            retry_items = [i for i in (retry.get("items") or []) if isinstance(i, dict)]
            if retry_items:
                data = retry
                raw_items = retry_items
        except AlignError:
            pass

    bases = _speech_bases(graph, transcript)
    items = _normalize_items(raw_items, graph, bases)
    _apply_speech_weights(items, graph)
    speech_edges = _normalize_speech_edges(
        [e for e in (data.get("speech_edges") or []) if isinstance(e, dict)], graph
    )
    extras = _normalize_extras(
        [c for c in (data.get("extra_concepts") or []) if isinstance(c, dict)], graph
    )

    return AlignmentDoc(
        file_name=graph.file_name,
        total_slides=graph.total_slides,
        items=items,
        speech_edges=speech_edges,
        extra_concepts=extras,
        summary=_summarize(items, speech_edges, graph, transcript),
        model=engine.name,
    )
