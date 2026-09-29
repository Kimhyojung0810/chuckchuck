"""
[F-11] 발화가 개념 그래프를 얼마나 잘 다뤘는지 판정하는 모듈입니다.
ConceptGraph + Transcript → AlignmentDoc.

발화 그래프를 독립 추출해 문서 그래프와 비교하지 않습니다 — LLM 추출 분산이
두 배가 되어 diff 가 노이즈를 측정하게 됩니다. 대신 문서 그래프를 기준축으로:
- speech_weight(발화 축)는 코드가 결정적으로 계산하고,
- LLM 은 4-class 판정·근거 인용·발화 간선·발화 전용 개념만 맡습니다.
  이때 노드 목록을 후보 앵커로 줘서 node_id 로 조인해 돌려받습니다 (조건화 추출).

    from chuckchuck.f11_align import align_speech
    alignment = align_speech(graph, transcript, context, llm="solar", slide_doc=slide_doc)

09-30 held-out 감사(C-06·C-07·G-A22) 뒤로 LLM 판정 다음에 코드 대조 네 겹을 더 한다 (`_align_checks`):
① 인용은 한 장 구간 안의 이어진 문장만 · 건너뛰기·미루기 말은 근거가 아니다
② 개념 이름과 그 자료 줄의 다른 낱말을 같이 담은 문장이 있으면 말한 것이다(missing → aligned)
③ 「넘어갈게요」 로 건너뛴 장의 개념은 다른 문장으로 설명되지 않았으면 missing
④ 발화의 숫자·방향이 자료 원문과 어긋나면 contradiction (자료 쪽 인용을 deck_quote 에)
녹음이 이 자료의 발표가 아니면(speech_match == "unrelated") LLM 을 부르지 않고 판정하지 않는다.
"""

from __future__ import annotations

import os

from . import _align_checks as chk
from ._deck_claims import Deck, deck_from_slidedoc
from ._json_text import extract_json_object
from ._match import (
    contains_tokens,
    count_occurrences,
    first_match_index,
    label_tokens,
    norm_tokens,
)
from ._speech_overlap import measure, slide_token_sets, time_windows
from ._speech_overlap import tokens as overlap_tokens
from ._spoken import Utterance, skip_targets, utterances
from ._traps import josa
from .contracts import (
    ALIGN_VERDICTS,
    AlignError,
    AlignmentDoc,
    AlignmentItem,
    AlignmentSummary,
    ConceptGraph,
    ConceptNode,
    Context,
    ExtraConcept,
    SkippedSlide,
    SlideDoc,
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
# 2 → 5. 단어가 두 번 나왔다고 개념을 설명한 것은 아니다. 이 값이 낮으면
# LLM 이 '누락' 이라 판정해도 코드가 '설명함' 으로 뒤집어서, 리포트가 실제보다
# 후해진다 (2026-08-10: 개념 18개 중 누락 0개가 나온 원인).
MENTION_MIN = max(1, int(os.environ.get("CHUCKCHUCK_ALIGN_MENTION_MIN", "5")))

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
7. 「넘어갈게요·건너뛸게요·생략할게요·시간 관계상」처럼 **설명하지 않고 넘긴 말**과 「나중에 설명할게요」처럼 미룬 말은
   어떤 개념의 근거도 아니다. 그렇게 넘긴 개념은 다른 곳에서 설명하지 않았으면 missing 이다.
8. evidence 는 한 슬라이드 발화 안에서 **이어진 문장 그대로**다. 서로 다른 곳의 말을 이어 붙이지 마라.
9. 슬라이드별 발화의 장 경계는 녹음에서 추정한 것이라 한두 문장 밀려 있을 수 있다.
   개념의 근거 장 발화에 없으면 바로 앞뒤 장 발화에서도 찾아라.
10. 발화의 숫자·단위나 방향(늘었다/줄었다, 높다/낮다)이 개념 설명과 다르면 contradiction 이다.

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


def _speech_bases(
    graph: ConceptGraph, transcript: Transcript, utts: list[Utterance] | None = None,
) -> dict[str, SpeechBasis]:
    """
    노드별 SpeechBasis. 전부 marks·토큰 매칭에서 나오는 결정적 값이다.

    건너뛰기·미루기 말(「이건 혈당 부하 계산식인데요, 시간 관계상 그냥 넘어갈게요」)의 언급은 세지 않는다 (09-30 C-06) —
    설명하지 않겠다는 말이 언급 횟수·첫 언급 시각을 채우면 그 개념이 「말한 개념」 으로 흐름·비중에 잡힌다.
    """
    total_sec = _total_speech_sec(transcript)

    sec_by_slide: dict[int, float] = {}
    for s in transcript.by_slide:
        sec_by_slide[s.slide_no] = sec_by_slide.get(s.slide_no, 0.0) + max(
            0.0, s.end_sec - s.start_sec
        )
    cues = [u for u in (utts or []) if not chk.usable(u)]
    if cues and transcript.by_slide:
        kept = [u for u in utts if chk.usable(u)]
        tokens_by_slide = {
            no: [t for u in kept if u.slide_no == no for t in norm_tokens(u.text)] for no in sec_by_slide
        }
        full_tokens = [t for u in kept for t in norm_tokens(u.text)]
    else:
        tokens_by_slide = {
            no: norm_tokens(transcript.text_for_slide(no)) for no in sec_by_slide
        }
        full_tokens = norm_tokens(transcript.full_text)
    if not full_tokens:
        full_tokens = [t for toks in tokens_by_slide.values() for t in toks]

    # 단어별 시각이 있으면 첫 언급 시각을 잡는다 (mock 은 words 가 없을 수 있다)
    spans = [(u.start_sec, u.end_sec) for u in cues if u.start_sec is not None and u.end_sec is not None]
    timed: list[tuple[str, float]] = [
        (tok, w.start_sec) for w in transcript.words
        if not any(a <= w.start_sec < b for a, b in spans)
        for tok in norm_tokens(w.text)
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
    utts: list[Utterance] | None = None,
    deck_texts: list[str] | None = None,
) -> list[AlignmentItem]:
    """
    raw 판정을 그래프의 모든 노드에 정확히 1개씩으로 정리한다. 누가 판정했는지(decided_by)를 같이 남긴다.

    - 없는 node_id 를 가리키는 판정은 버린다. 같은 node_id 가 여러 번 오면 첫 번째만
    - verdict 가 enum 밖이면(LLM 이 빠뜨린 노드 포함) 결정적 폴백으로 대체 — decided_by "fallback"
    - missing 인데 label 이 발화에 MENTION_MIN 회 이상 등장하면 aligned 로 정정
      (토큰 매칭이 프롬프트 널뛰기보다 믿을 만하다. 단 1회는 스친 것이지
       설명한 것이 아니라서, 그 한 번으로 LLM 의 '누락' 판정을 뒤집지 않는다)
    - evidence 없는 contradiction 은 missing 으로 강등
      (사용자에게 "틀렸다"고 말하는 판정이라 근거 없이는 내보내지 않는다)
    - evidence 없는 aligned 도 같은 이유로 강등 — 결정적 폴백 ("fallback")
      ("잘했다"도 근거가 있어야 한다. 이걸 안 걸러서 모델이 전부 aligned 로
       도장 찍은 리포트가 나갔다 — 17/17 초록, coverage 1.0)
    - justified_skip 인데 언급 0회 + doc weight ≥ SKIP_GUARD_WEIGHT 면
      missing 으로 강등 (자료가 힘준 개념은 무언급이 '정당한 생략'일 수 없다)
    - 인용은 한 장 구간 안의 이어진 발화 문장으로 맞추고, 건너뛰기·미루기 말은 근거에서 뺀다 (`_align_checks.resolve_evidence`)
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
        if evidence and utts:
            evidence = chk.resolve_evidence(evidence, node, utts, deck_texts)
        note = str((raw or {}).get("note", "") or "").strip()

        verdict = str((raw or {}).get("verdict", "") or "")
        decided = "llm"
        if verdict not in ALIGN_VERDICTS:
            verdict, decided = _fallback_verdict(basis), "fallback"
        if verdict == "missing" and basis.mention_count >= MENTION_MIN:
            verdict, decided = "aligned", "code"
        # 근거 없는 모순은 그대로 둘 수 없다(계약). 다만 폴백으로 보내면 언급
        # 횟수만 보고 'aligned' 로 떨어져서, **모델이 문제를 봤는데 화면에는
        # 「잘했어요」가 뜬다.** 문제를 본 판정을 칭찬으로 바꾸지 않는다 —
        # 근거를 못 댔을 뿐 제대로 설명된 것은 아니므로 missing 으로 내린다.
        if verdict == "contradiction" and not evidence:
            verdict, decided = "missing", "code"
        # 근거 없는 aligned 도 버린다. 프롬프트는 aligned 에 evidence 를 필수로
        # 요구하는데(SYSTEM_PROMPT) 코드는 contradiction 만 검사하고 있었다.
        # 그래서 모델이 근거 없이 전부 '잘했다'로 도장 찍으면 그대로 통과했다 —
        # 실측으로 17개 개념이 전부 aligned, coverage 1.0 이 나왔다.
        # "틀렸다"를 근거 없이 말하지 않는다면 "잘했다"도 마찬가지여야 한다.
        if verdict == "aligned" and not evidence:
            verdict = _fallback_verdict(basis)
            if decided == "llm":
                decided = "fallback"
        if (
            verdict == "justified_skip"
            and basis.mention_count == 0
            and node.weight >= SKIP_GUARD_WEIGHT
        ):
            verdict, decided = "missing", "code"

        items.append(AlignmentItem(
            node_id=node.id,
            verdict=verdict,
            speech_basis=basis,
            doc_weight=node.weight,
            evidence=evidence,
            note=note,
            decided_by=decided,
        ))
    return items


# ---------------------------------------------------------------------------
# 코드 대조 — 말한 문장 · 건너뛴 장 · 자료와 어긋난 숫자·방향 (09-30 held-out C-06)
# ---------------------------------------------------------------------------

def _names(node: ConceptNode, text: str) -> bool:
    """글이 이 개념 이름을 부르는가 (조사 붙어도, 이름 토큰이 흩어져 있어도)."""
    return bool(chk.label_hit(norm_tokens(text), label_tokens(node.label)))


def _apply_spoken(items: list[AlignmentItem], graph: ConceptGraph, utts: list[Utterance], deck: Deck) -> None:
    """
    missing 인데 개념 이름과 그 자료 줄의 다른 낱말을 같이 말한 문장이 있으면 aligned (근거는 그 문장).
    aligned 인데 근거가 이 개념 이름을 안 부르면, 이름을 부른 문장이 있을 때 근거만 바꾼다(판정은 LLM 그대로).

    09-30 실측(혈당): 「첫째는 식후 졸림이고, 둘째는 금방 또 배가 고픈 잦은 허기, 셋째는 밤에 폭식하게 되는 거예요」 를 말했는데
    식후 졸림·잦은 허기가 missing 이었다 — 녹음에서 추정한 장 경계가 한 장 밀려 LLM 이 4장 개념을 4장 구간(빈 말)에서만 찾았다.
    """
    by_id = {n.id: n for n in graph.nodes}
    for it in items:
        node = by_id[it.node_id]
        if it.verdict in ("missing", "justified_skip"):
            # justified_skip 도 — 「설명은 안 했지만 생략이 합리적」 인데 설명한 문장이 있으면 그 판정이 틀렸다
            # (09-30 혈당: 「식이섬유를 먼저 먹으면 배도 오래 불러서 잦은 허기도 막을 수 있고요」 를 말했는데 정당생략이었다)
            found = chk.spoken_sentence(node, utts, chk.node_lines(node, deck))
            if found is not None:
                it.verdict, it.evidence, it.decided_by = "aligned", found.utterance.text, "code"
                it.note = f"이 개념을 말한 문장이 있어요 — 자료 줄의 낱말 {found.support}개를 같이 말했어요"
        elif it.verdict == "aligned" and not _names(node, it.evidence):
            found = chk.spoken_sentence(node, utts, chk.node_lines(node, deck))
            if found is not None:
                it.evidence = found.utterance.text
        elif it.verdict == "aligned":
            it.evidence = _trim_to_named(it.evidence, node, utts)


def _trim_to_named(evidence: str, node: ConceptNode, utts: list[Utterance]) -> str:
    """여러 문장 인용이면 이 개념 이름을 부른 문장부터 — 앞에 붙은 딴 말(「아 그리고 장표 색이 좀…」)을 뗀다. 순서·원문은 그대로."""
    inside = [u for u in utts if chk.usable(u) and u.text in evidence]
    if len(inside) < 2:
        return evidence
    first = next((i for i, u in enumerate(inside) if _names(node, u.text)), None)
    if first is None or first == 0:        # 이름을 부른 문장이 없거나 이미 첫 문장이다 — 그대로
        return evidence
    kept = " ".join(u.text for u in inside[first:])
    return kept if kept in evidence else evidence


def _apply_skips(
    items: list[AlignmentItem], graph: ConceptGraph, skipped: dict[int, Utterance],
) -> list[SkippedSlide]:
    """
    말로 건너뛴 장의 개념 — 다른 문장이 그 개념을 이름으로 불러 설명하지 않았으면 missing (「시간 관계상 그냥 넘어갈게요」).
    발표자가 스스로 건너뛴다고 말한 장이라 가벼운 개념이라도 「정당한 생략」(justified_skip)으로 두지 않는다 — 09-30 녹음 감사 REC-12:
    「예외인 경우는 오늘은 빼고」 로 건너뛴 장이 LLM 의 justified_skip 으로 남아 결함도 상한도 없었다. 모순은 건드리지 않는다.
    """
    by_id = {n.id: n for n in graph.nodes}
    for it in items:
        node = by_id[it.node_id]
        hit = [no for no in node.slide_nos if no in skipped]
        if not hit or it.verdict == "contradiction":
            continue
        if it.verdict == "aligned" and it.evidence and _names(node, it.evidence):
            continue
        cue = skipped[hit[0]]
        # 설명한 문장이 없다고 하면서 LLM 인용을 남기면 「이 슬라이드에서 한 말」 과 판정이 서로 다른 말을 한다 — 근거를 비운다
        it.verdict, it.decided_by, it.evidence = "missing", "code", ""
        it.note = f"{hit[0]}장은 「{cue.text}」라고 하고 넘어갔어요 — 이 개념을 설명한 문장이 없어요"
    return [
        SkippedSlide(
            slide_no=no,
            cue=cue.text,
            node_ids=[it.node_id for it in items if no in by_id[it.node_id].slide_nos and it.verdict == "missing"],
        )
        for no, cue in sorted(skipped.items())
    ]


def _strip_title(line: str, title: str) -> str:
    """자료 줄 머리에 붙은 장 제목(글 상자 이음으로 붙는다 — 「연구로 본 효과 채소를 먼저 …」)을 뗀다."""
    t = " ".join((title or "").split())
    return line[len(t) + 1:] if t and line.startswith(t + " ") and len(line) > len(t) + 8 else line


def _apply_contradictions(
    items: list[AlignmentItem], graph: ConceptGraph, utts: list[Utterance], deck: Deck,
    titles: dict[int, str] | None = None,
) -> None:
    """
    발화가 자료 원문과 숫자·방향이 어긋나면 contradiction — 발화 쪽은 evidence, 자료 쪽은 deck_quote.
    어긋난 문장을 근거로 쓴 **다른** aligned 개념은 이름을 부른 다른 문장이 있으면 근거를 바꾼다.

    09-30 실측(혈당): 자료 6장 「평균 29% 낮았습니다」 를 「평균 49퍼센트나 낮았다고 해요」 로 말했는데 contradiction 0,
    그 문장이 식사 순서·채소 먼저·Shukla 연구의 정합 근거였다.
    """
    found = chk.contradictions(graph, utts, deck)
    if not found:
        return
    by_id = {n.id: n for n in graph.nodes}
    item_of = {it.node_id: it for it in items}
    bad = {c.utterance.text for c in found}
    for c in found:
        it = item_of[c.node_id]
        it.verdict, it.decided_by = "contradiction", "code"
        it.evidence, it.deck_slide_no = c.quote or c.utterance.text, c.slide_no
        it.deck_quote = _strip_title(c.deck_line, (titles or {}).get(c.slide_no, ""))
        # 모순의 갈래 — 질문·리포트가 「수치가 달라요」「방향이 반대예요」「맞다·아니다가 반대예요」 를 이것으로 고른다 (09-30 REC-03)
        it.contra_kind = c.family
        if c.said and c.deck_said:
            it.note = f"발표에서는 {josa(c.said, '이라고', '라고')} 했는데 자료 {c.slide_no}장은 {josa(c.deck_said, '이에요', '예요')}"
        elif c.kind == "negation":
            it.note = f"자료 {c.slide_no}장과 맞다·아니다가 반대예요"
        elif c.kind == "order" or c.relation == "swapped":
            it.note = f"자료 {c.slide_no}장과 무엇이 더 큰지가 반대예요 — 견준 두 쪽이 뒤바뀌었어요"
        elif c.family == "number":
            # 값 한 쌍을 못 뽑은 수치 어긋남 — 방향 문구를 붙이면 수치를 잘못 말한 발표에 「방향이 반대」 라고 거짓말을 한다
            it.note = f"자료 {c.slide_no}장과 수치가 달라요"
        else:
            it.note = f"자료 {c.slide_no}장과 높고 낮은 방향이 반대예요"
    for it in items:
        hit = next((c for c in found if it.verdict == "aligned" and _quotes_same(c.utterance.text, it.evidence)), None)
        if hit is None:
            continue
        node = by_id[it.node_id]
        other = chk.spoken_sentence(node, utts, chk.node_lines(node, deck), exclude=bad)
        if other is not None:
            it.evidence = other.utterance.text
        elif hit.said and hit.deck_said:
            # 이 개념은 말했지만 그 문장의 수치가 자료와 다르다 — 설명함은 두되 숨기지 않는다
            it.note = (f"{it.note} · 이 문장의 {josa(hit.said, '은', '는')} 자료 {hit.slide_no}장({hit.deck_said})과 달라요").lstrip(" ·")
        else:
            # 방향·맞다아니다가 자료와 반대인 문장 — 수치가 아니어도 숨기지 않는다 (09-30 녹음 모드 화면: 「맞통풍보다 두 배 빨리」 를
            # 거꾸로 말한 문장이 「농도 감소 속도」 의 설명함 근거로 그대로 남았다)
            it.note = f"{it.note} · 이 문장은 자료 {hit.slide_no}장과 {_CONTRA_WHAT.get(hit.family, '내용이 반대예요')}".lstrip(" ·")


#: 설명함 근거가 어긋난 문장일 때 덧붙이는 말 — 갈래마다. 값 한 쌍을 못 뽑은 수치 어긋남은 「반대」 가 아니라 「달라요」 다.
_CONTRA_WHAT = {"direction": "방향이 반대예요", "polarity": "맞다·아니다가 반대예요", "number": "수치가 달라요"}


def _quotes_same(sentence: str, evidence: str) -> bool:
    """근거 인용이 이 발화 문장(의 일부)인가 — 띄어쓰기·끝 부호와 머리 군말(「그리고」)은 달라도 된다 (LLM 인용은 부호를 자주 뺀다)."""
    a, b = "".join((sentence or "").split()).rstrip(".?!"), "".join((evidence or "").split()).rstrip(".?!")
    return bool(a and b) and (a in b or (len(b) >= 10 and b in a))


# ---------------------------------------------------------------------------
# 녹음이 이 자료의 발표인가 (09-30 held-out C-07)
# ---------------------------------------------------------------------------

#: 자료 원문 없이(개념 이름·요약만으로) 다른 발표라고 단정할 문턱 — 원문보다 낱말이 적어 맞는 발표도 겹침이 낮게 나오므로
#: 원문 문턱(0.2·0.6)보다 낮을 때만 내린다. 09-30 실측(녹음 5종 × 덱 12종, 개념 이름·요약만):
#:   맞는 발표 7쌍   overlap 0.13~0.37 · cover 0.26~0.74 — 둘 다 문턱 아래인 쌍 없음 (최저 0.128·0.741 / 0.228·0.264)
#:   다른 발표 53쌍  overlap 0.00~0.08 · cover 0.00~0.31 — 전부 문턱 아래
GRAPH_ONLY_MAX_OVERLAP = 0.10
GRAPH_ONLY_MAX_COVER = 0.40
#: 이만큼(창 — 6초 또는 문장)은 말해야 스스로 「다른 발표」 라고 단정한다. 몇 문장으로는 주제를 가를 수 없다.
#: 호출부가 F-04 판정(speech_match="unrelated")을 넘기면 길이와 상관없이 따른다.
MATCH_MIN_WINDOWS = 8


def _deck_slide_texts(slide_doc: SlideDoc) -> list[str]:
    return [f"{s.title or ''} {s.raw_text or ''}" for s in slide_doc.slides]


def _speech_match(
    graph: ConceptGraph, transcript: Transcript, utts: list[Utterance],
    slide_doc: SlideDoc | None, hint: str | None,
) -> tuple[str, float | None]:
    """
    (speech_match, speech_overlap). F-04 와 같은 자(`_speech_overlap.measure`) — 자료 원문이 있으면 같은 문턱으로,
    없으면 개념 이름·요약으로 더 낮은 문턱에서만. 호출부가 F-04 판정을 넘기면(hint == "unrelated") 그걸 따른다.
    """
    use_deck = slide_doc is not None and any((s.raw_text or s.title or "").strip() for s in slide_doc.slides)
    if use_deck:
        texts = _deck_slide_texts(slide_doc)
    else:
        by_slide = chk.slide_texts(graph, None)
        texts = [by_slide[no] for no in sorted(by_slide)]
    per_slide = slide_token_sets(texts)
    if transcript.words:
        seq = [{"text": w.text, "start_sec": w.start_sec} for w in transcript.words]
        total = float(transcript.duration_sec or transcript.words[-1].end_sec or 0.0)
        windows = time_windows(seq, total, len(per_slide))
    else:
        windows = [overlap_tokens(u.text) for u in utts]
    ov = measure(per_slide, windows)
    if not ov.spoken_windows or not any(per_slide):
        return ("unrelated" if hint == "unrelated" else "matched"), None
    if ov.spoken_windows < MATCH_MIN_WINDOWS:
        return ("unrelated" if hint == "unrelated" else "matched"), ov.overlap
    if use_deck:
        unrelated = ov.unrelated
    else:
        unrelated = ov.overlap < GRAPH_ONLY_MAX_OVERLAP and ov.cover < GRAPH_ONLY_MAX_COVER
    return ("unrelated" if unrelated or hint == "unrelated" else "matched"), ov.overlap


def _unjudged(graph: ConceptGraph, bases: dict[str, SpeechBasis], overlap: float | None) -> list[AlignmentItem]:
    """다른 발표 녹음 — 판정하지 않는다. item 은 계약상 전부 있어야 해서 missing·fallback 으로 채우고 까닭을 note 에 적는다."""
    pct = "" if overlap is None else f" (발화 낱말이 자료와 겹치는 비중 {overlap:.0%})"
    note = f"녹음이 이 자료의 발표가 아니라서 판정하지 않았어요{pct}"
    return [
        AlignmentItem(node_id=n.id, verdict="missing", speech_basis=bases[n.id], doc_weight=n.weight,
                      note=note, decided_by="fallback")
        for n in graph.nodes
    ]


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
    slide_doc: SlideDoc | dict | None = None,
    speech_match: str | None = None,
) -> AlignmentDoc:
    """
    ConceptGraph + Transcript (+선택 Context·SlideDoc) → AlignmentDoc.

    speech_weight 는 marks·토큰 매칭에서 결정적으로 계산하고,
    LLM 은 4-class 판정·근거 인용·발화 간선·발화 전용 개념만 맡는다.
    LLM 이 빠뜨린 노드는 결정적 폴백(언급 있으면 정합, 없으면 누락)으로 채운다 — decided_by "fallback".

    slide_doc(자료 원문)을 주면 발화의 숫자·방향을 원문과 견줘 contradiction 을 코드가 잡고(deck_quote),
    「아예 다른 발표」 판정도 F-04 와 같은 문턱으로 한다. 없으면 숫자 대조를 건너뛴다(개념 요약은 원문이 아니다).
    speech_match 는 호출부가 아는 F-04 판정(transcript 의 marks_match) — "unrelated" 면 따른다.
    """
    if isinstance(graph, dict):
        graph = ConceptGraph.from_dict(graph)
    if isinstance(transcript, dict):
        transcript = Transcript.from_dict(transcript)
    if isinstance(slide_doc, dict):
        slide_doc = SlideDoc.from_dict(slide_doc)
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
    utts = utterances(transcript)
    bases = _speech_bases(graph, transcript, utts)

    # 녹음이 이 자료의 발표가 아니면 판정하지 않는다 — LLM 을 부르면 남의 발표 말을 이 자료 개념의 근거로 댄다 (09-30 C-07)
    match, overlap = _speech_match(graph, transcript, utts, slide_doc, speech_match)
    if match == "unrelated":
        items = _unjudged(graph, bases, overlap)
        _apply_speech_weights(items, graph)
        return AlignmentDoc(
            file_name=graph.file_name,
            total_slides=graph.total_slides,
            items=items,
            summary=_summarize(items, [], graph, transcript),
            model="code",
            speech_match="unrelated",
            speech_overlap=overlap,
            basis="skipped",
        )

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

    deck = deck_from_slidedoc(slide_doc) if slide_doc is not None else Deck()
    deck_texts = _deck_slide_texts(slide_doc) if slide_doc is not None else None
    items = _normalize_items(raw_items, graph, bases, utts, deck_texts)
    # 코드 대조 셋 — 순서가 뜻이다: 말한 문장으로 되살리고 → 건너뛴 장을 내리고 → 자료와 어긋난 말은 무엇보다 앞선다
    _apply_spoken(items, graph, utts, deck)
    skipped = _apply_skips(items, graph, skip_targets(utts, chk.slide_texts(graph, slide_doc)))
    _apply_contradictions(items, graph, utts, deck,
                          {s.slide_no: s.title for s in slide_doc.slides} if slide_doc is not None else None)
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
        speech_match="matched",
        speech_overlap=overlap,
        # LLM 이 두 번 다 판정을 비웠으면 전 노드가 언급 횟수 짐작이다 — 누락이라 부를 근거가 없다 (레드팀 G-A22)
        basis="llm" if raw_items else "fallback",
        skipped_slides=skipped,
    )
