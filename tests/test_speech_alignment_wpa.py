"""
녹음 경로 정직성 (WP-A, 09-30 held-out 감사 C-06·C-07 · 레드팀 G-A22) — LLM 없이 도는 합성 발표로 검사한다.

- 말로 틀린 숫자(반올림 허용 포함)·뒤집은 방향 → contradiction + 양쪽 인용 (F-11 코드 대조)
- 「시간 관계상 그냥 넘어갈게요」 → 그 문장은 근거가 아니고, 그 장은 건너뛴 장 (F-11·F-17 이 같은 말)
- 두 장 발화를 이은 인용은 없다
- 개념 이름 + 자료 줄 낱말을 같이 말한 문장이 있으면 missing 을 뒤집는다
- 다른 발표 녹음 → LLM 을 안 부르고 판정하지 않는다 (speech_match·basis) · 채점·리포트가 말 내용을 안 매긴다
- LLM 판정이 통째로 비면 폴백 표시 (basis·decided_by) · 채점이 개념 전달을 안 매긴다
- 치명 결함 상한 · 시간 배분은 실제 길이에 맞춘 비율로

자료·발표는 분야 다섯(건강·사업·정책·기술·도서관)에서 새로 지었다 — 규칙에 특정 발표 낱말이 없음을 보이려고.
"""

from __future__ import annotations

import json

import pytest

from chuckchuck._rubric_det import Evidence, faults, score_item
from chuckchuck._spoken import skip_cue, spoken_numbers, split_sentences, utterances
from chuckchuck.contracts import (
    AlignmentDoc,
    ConceptDoc,
    ConceptGraph,
    ConceptNode,
    Context,
    PaceDoc,
    RubricScore,
    Slide,
    SlideBlock,
    SlideConcepts,
    SlideDoc,
    SlidePace,
    SlideSpeech,
    Transcript,
    Word,
)
from chuckchuck.f11_align import align_speech
from chuckchuck.f14_rubric import CAP_FIRST, CAP_STEP, score_rubric
from chuckchuck.f17_pace import analyze_pace
from chuckchuck.f19_report import compose_report
from chuckchuck.providers.llm_base import LLMProvider

# ---------------------------------------------------------------------------
# 재료
# ---------------------------------------------------------------------------


def deck(*slides: tuple[str, str]) -> SlideDoc:
    """(제목, 본문 — 줄은 \\n) → SlideDoc."""
    out = []
    for i, (title, body) in enumerate(slides, start=1):
        blocks = [SlideBlock("heading1", title)] + [SlideBlock("paragraph", ln) for ln in body.split("\n") if ln]
        out.append(Slide(slide_no=i, title=title, blocks=blocks))
    return SlideDoc("deck.pptx", len(out), out)


def graph(*nodes: tuple[str, str, list[int], str, float], total: int) -> ConceptGraph:
    """(id, 라벨, 장, 요약, weight) → ConceptGraph (전부 core)."""
    return ConceptGraph("deck.pptx", total, nodes=[
        ConceptNode(id=i, label=lb, slide_nos=nos, summary=sm, weight=w, importance="core") for i, lb, nos, sm, w in nodes
    ])


def talk(*segs: tuple[int, str], sec: float = 20.0) -> Transcript:
    """(장, 발화) → 장마다 sec 초, 낱말마다 시각이 있는 Transcript (by_slide 의 낱말은 빼 둔다 — 프런트 slim 과 같게)."""
    by_slide, words, t = [], [], 0.0
    for no, text in segs:
        toks = text.split()
        step = sec / max(1, len(toks))
        words += [Word(tok, round(t + k * step, 2), round(t + (k + 1) * step, 2)) for k, tok in enumerate(toks)]
        by_slide.append(SlideSpeech(no, 1, t, t + sec, text))
        t += sec
    return Transcript(full_text=" ".join(x for _, x in segs), words=words, by_slide=by_slide,
                      provider="clova", duration_sec=t)


class LLM(LLMProvider):
    """정해 둔 판정을 돌려준다. 부른 횟수를 센다 — 다른 발표면 0 이어야 한다."""

    name = "scripted"

    def __init__(self, items: list[dict] | None = None):
        self.items = items or []
        self.calls = 0

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False) -> str:
        self.calls += 1
        return json.dumps({"items": self.items, "speech_edges": [], "extra_concepts": []}, ensure_ascii=False)


def aligned(*ids_quotes: tuple[str, str]) -> list[dict]:
    return [{"node_id": i, "verdict": "aligned", "evidence": q} for i, q in ids_quotes]


# --- 건강: 물 마시기 -----------------------------------------------------------------

WATER = deck(
    ("물 마시기의 효과", "하루 물 섭취가 두통을 줄입니다"),
    ("연구로 본 효과", "물을 2리터 이상 마신 그룹은 두통 빈도가 평균 35% 줄었습니다"),
    ("탈수 지수 계산", "탈수 지수 = 체중 감소량 ÷ 체중 × 100"),
    ("생활 팁", "카페인 음료는 밤사이 소변량을 크게 늘립니다"),
)
WATER_G = graph(
    ("water", "물 섭취", [1, 2], "하루 물 섭취가 두통을 줄인다", 1.0),
    ("study", "두통 빈도 연구", [2], "물을 2리터 이상 마신 그룹은 두통 빈도가 평균 35% 감소", 0.8),
    ("index", "탈수 지수", [3], "탈수 지수 = 체중 감소량 ÷ 체중 × 100", 0.6),
    ("caffeine", "카페인 음료", [4], "카페인 음료는 밤사이 소변량을 늘린다", 0.4),
    total=4,
)
WATER_TALK = talk(
    (1, "오늘은 물 섭취가 두통을 줄인다는 이야기를 할게요."),
    (2, "물을 2리터 이상 마신 그룹은 두통 빈도가 평균 55퍼센트나 줄었다고 해요."),
    (3, "음 이건 탈수 지수 계산식인데요, 시간 관계상 그냥 넘어갈게요."),
    (4, "그리고 카페인 음료는 밤사이 소변량을 크게 줄여 줘요."),
)


def test_misspoken_number_is_contradiction_with_both_quotes():
    llm = LLM(aligned(("water", "오늘은 물 섭취가 두통을 줄인다는 이야기를 할게요."),
                      ("study", "물을 2리터 이상 마신 그룹은 두통 빈도가 평균 55퍼센트나 줄었다고 해요.")))
    doc = align_speech(WATER_G, WATER_TALK, llm=llm, slide_doc=WATER)
    it = doc.item("study")
    assert it.verdict == "contradiction" and it.decided_by == "code"
    assert "55퍼센트" in it.evidence                    # 발화 쪽 — 한 말 그대로
    assert "35%" in it.deck_quote and it.deck_slide_no == 2   # 자료 쪽
    assert "55%" in it.note and "35%" in it.note
    assert doc.summary.verdict_counts["contradiction"] >= 1


def test_direction_flip_is_contradiction():
    doc = align_speech(WATER_G, WATER_TALK, llm=LLM(aligned(("caffeine", "그리고 카페인 음료는 밤사이 소변량을 크게 줄여 줘요."))),
                       slide_doc=WATER)
    it = doc.item("caffeine")
    assert it.verdict == "contradiction" and "늘립니다" in it.deck_quote and "방향" in it.note


def test_skip_cue_is_never_evidence_and_marks_the_slide_skipped():
    llm = LLM(aligned(("index", "음 이건 탈수 지수 계산식인데요, 시간 관계상 그냥 넘어갈게요.")))
    doc = align_speech(WATER_G, WATER_TALK, llm=llm, slide_doc=WATER)
    it = doc.item("index")
    assert it.verdict == "missing" and it.decided_by == "code" and it.evidence == ""
    assert "3장" in it.note and "넘어갈게요" in it.note
    assert [(s.slide_no, s.node_ids) for s in doc.skipped_slides] == [(3, ["index"])]
    assert all("넘어갈게요" not in i.evidence for i in doc.items)
    # 건너뛴 말의 언급은 언급 횟수에 안 들어간다
    assert it.speech_basis.mention_count == 0


def test_deck_text_quoted_as_speech_is_not_evidence():
    """발화가 아니라 자료 글(식)을 옮긴 인용은 발표자가 한 말이 아니다."""
    llm = LLM(aligned(("index", "탈수 지수 = 체중 감소량 ÷ 체중 × 100")))
    doc = align_speech(WATER_G, WATER_TALK, llm=llm, slide_doc=WATER)
    assert doc.item("index").verdict == "missing" and doc.item("index").evidence == ""


# --- 사업: 반찬 정기구독 IR -----------------------------------------------------------

SUB = deck(
    ("월 반복 매출", "월 반복 매출 = 구독자 수 × 객단가 × 유지율"),
    ("첫 달 이탈", "첫 달 유지율은 62%입니다\n배송비는 건당 3,200원으로 41% 줄었습니다"),
    ("시장 규모", "1인 가구는 전체 가구의 34.5%를 차지합니다"),
)
SUB_G = graph(
    ("mrr", "월 반복 매출", [1], "구독자 수 × 객단가 × 유지율", 1.0),
    ("retention", "첫 달 유지율", [2], "첫 달 유지율 62%", 0.7),
    ("delivery", "배송비", [2], "배송비 건당 3,200원, 41% 감소", 0.5),
    ("market", "1인 가구", [3], "1인 가구 비중 34.5%", 0.4),
    total=3,
)


@pytest.mark.parametrize("said, contra", [
    ("첫 달 유지율은 82%예요.", True),                 # 62 → 82
    ("첫 달 유지율은 육십이 퍼센트예요.", False),       # 한자어 수로 맞게
    ("첫 달 유지율은 팔십이 프로예요.", True),          # 한자어 수로 틀리게
])
def test_spoken_number_forms(said, contra):
    t = talk((1, "월 반복 매출은 구독자 수 곱하기 객단가 곱하기 유지율이에요."), (2, said))
    doc = align_speech(SUB_G, t, llm=LLM(aligned(("retention", said))), slide_doc=SUB)
    assert (doc.item("retention").verdict == "contradiction") is contra


@pytest.mark.parametrize("said", [
    "배송비는 건당 약 3천 원 정도로 40% 정도 줄었어요.",   # 어림 표지 + 15% 안
    "1인 가구는 전체 가구의 35%를 차지해요.",             # 34.5 → 35 반올림
    "1인 가구는 전체 가구의 34.5%를 차지해요.",
])
def test_rounding_and_approximation_are_not_contradictions(said):
    t = talk((1, "월 반복 매출 이야기부터 할게요."), (2, "첫 달 유지율은 62%예요."), (3, said))
    doc = align_speech(SUB_G, t, llm=LLM(), slide_doc=SUB)
    assert doc.summary.verdict_counts["contradiction"] == 0, [(i.node_id, i.note) for i in doc.items]


def test_no_contradiction_pass_without_deck_text():
    """자료 원문이 없으면 숫자를 견주지 않는다 — 개념 요약은 원문이 아니다."""
    t = talk((1, "월 반복 매출 이야기부터 할게요."), (2, "첫 달 유지율은 82%예요."))
    doc = align_speech(SUB_G, t, llm=LLM(aligned(("retention", "첫 달 유지율은 82%예요."))))
    assert doc.item("retention").verdict == "aligned"


# --- 정책: 전세 보증 ------------------------------------------------------------------

LEASE = deck(
    ("보증 가입", "보증 가입률은 18%에 그칩니다"),
    ("피해 회복", "피해 회복까지 평균 14개월이 걸립니다"),
    ("제안", "시세 정보를 공개하면 계약 전 확인이 쉬워집니다"),
)
LEASE_G = graph(
    ("rate", "보증 가입률", [1], "보증 가입률 18%", 0.9),
    ("recover", "피해 회복", [2], "피해 회복까지 평균 14개월", 0.8),
    ("price", "시세 정보", [3], "시세 정보 공개", 0.7),
    total=3,
)


def test_sino_numeral_months_contradiction_and_transition_is_not_skip():
    t = talk(
        (1, "보증 가입률은 18퍼센트밖에 안 돼요. 다음으로 넘어갈게요."),
        (2, "피해 회복까지 평균 이십사 개월이 걸려요."),
        (3, "그래서 시세 정보를 공개하면 계약 전에 확인이 쉬워져요."),
    )
    doc = align_speech(LEASE_G, t, llm=LLM(aligned(("rate", "보증 가입률은 18퍼센트밖에 안 돼요."))), slide_doc=LEASE)
    assert doc.item("rate").verdict == "aligned"               # 18퍼센트 = 18%
    assert doc.item("recover").verdict == "contradiction"      # 이십사 개월 ≠ 14개월
    assert doc.skipped_slides == []                            # 「다음으로 넘어갈게요」 는 전환이다


def test_spoken_sentence_rescues_llm_missing():
    """이름 + 그 자료 줄의 다른 낱말을 같이 말한 문장이 있으면 missing 이 아니다 (추정 장 경계가 밀려 LLM 이 놓친 경우)."""
    t = talk(
        (1, "보증 가입률 얘기는 뒤에서 할게요."),
        (2, "먼저 보증 가입률은 18%에 그친다는 점, 그리고 피해 회복까지 평균 14개월이 걸린다는 점이에요."),
        (3, "시세 정보를 공개하면 계약 전 확인이 쉬워져요."),
    )
    items = [{"node_id": "rate", "verdict": "missing"}, {"node_id": "recover", "verdict": "missing"}]
    doc = align_speech(LEASE_G, t, llm=LLM(items), slide_doc=LEASE)
    for nid in ("rate", "recover"):
        it = doc.item(nid)
        assert it.verdict == "aligned" and it.decided_by == "code" and "18%" in it.evidence


def test_name_alone_does_not_rescue_missing():
    t = talk((1, "보증 가입률"), (2, "피해 회복"), (3, "시세 정보"))
    doc = align_speech(LEASE_G, t, llm=LLM([{"node_id": "rate", "verdict": "missing"}]), slide_doc=LEASE)
    assert doc.item("rate").verdict == "missing"


def test_evidence_never_stitches_two_segments():
    t = talk(
        (1, "보증 가입률은 18%에 그칩니다 라고 자료에 있어요."),
        (2, "피해 회복까지는 평균 14개월이 걸려요."),
        (3, "시세 정보를 공개해요."),
    )
    stitched = "18%에 그칩니다 라고 자료에 있어요. 피해 회복까지는 평균 14개월이"
    doc = align_speech(LEASE_G, t, llm=LLM(aligned(("rate", stitched), ("recover", stitched))), slide_doc=LEASE)
    segs = [s.text for s in t.by_slide]
    for nid in ("rate", "recover"):
        ev = doc.item(nid).evidence
        assert ev and any(ev in s for s in segs), ev


# --- 기술: 배터리 --------------------------------------------------------------------

BATT = deck(
    ("충전 수명", "리튬인산철 배터리는 충전 횟수가 3000회입니다"),
    ("에너지 밀도", "리튬인산철은 삼원계보다 에너지 밀도가 20% 낮습니다"),
)
BATT_G = graph(
    ("cycle", "충전 횟수", [1], "리튬인산철 충전 횟수 3000회", 1.0),
    ("density", "에너지 밀도", [2], "삼원계 대비 에너지 밀도 20% 낮음", 0.8),
    total=2,
)


def test_same_number_opposite_direction_is_contradiction():
    t = talk((1, "리튬인산철 배터리는 충전 횟수가 3000회예요."),
             (2, "리튬인산철은 삼원계보다 에너지 밀도가 20% 높아요."))
    doc = align_speech(BATT_G, t, llm=LLM(aligned(("density", "리튬인산철은 삼원계보다 에너지 밀도가 20% 높아요."))),
                       slide_doc=BATT)
    assert doc.item("density").verdict == "contradiction"
    assert doc.item("cycle").verdict != "contradiction"


# --- 도서관 · 다른 발표 녹음 ---------------------------------------------------------

LIB = deck(
    ("방문자 감소", "연간 방문자는 3년 사이 15% 줄었습니다"),
    ("독서 경험", "대출 권수보다 더 중요한 것은 독서 경험입니다"),
    ("시범 운영", "야간 개방 8주 동안 방문자가 77% 늘었습니다"),
    ("공간 개선", "좌석과 조명을 바꾸면 머무는 시간이 늘어납니다"),
)
LIB_G = graph(
    ("visitors", "연간 방문자", [1, 3], "연간 방문자 15% 감소", 1.0),
    ("reading", "독서 경험", [2], "대출 권수보다 중요한 독서 경험", 0.9),
    ("night", "야간 개방", [3], "야간 개방 8주 방문자 77% 증가", 0.7),
    ("space", "공간 개선", [4], "좌석과 조명 개선", 0.5),
    total=4,
)
SLEEP_WORDS = (
    "잠은 하나의 상태가 아니라 여러 단계로 나뉩니다. 얕은 수면에서 깊은 수면으로 들어갑니다. "
    "렘수면은 기억 정리와 관련이 있어요. 주말에 몰아서 자면 사회적 시차가 생겨요. "
    "카페인과 음주는 수면의 연속성을 끊습니다. 기상 시간을 일정하게 지키는 게 쉬워요. "
    "침실의 빛과 소음을 줄여 보세요. 좋은 잠은 끊기지 않고 규칙적인 잠이에요. "
    "수면 주기는 약 90분이에요. 깊은 수면은 초반에 많아요. 렘수면은 아침에 길어져요. "
    "평일과 주말의 기상 시간 차이를 줄여요."
)


def test_unrelated_talk_is_not_judged_and_llm_is_not_called():
    sents = split_sentences(SLEEP_WORDS)
    t = talk(*[(i % 4 + 1, s) for i, s in enumerate(sents)], sec=6.0)
    llm = LLM(aligned(("visitors", sents[0])))
    doc = align_speech(LIB_G, t, llm=llm, slide_doc=LIB)
    assert llm.calls == 0
    assert doc.speech_match == "unrelated" and doc.basis == "skipped" and not doc.speech_usable
    assert all(i.verdict == "missing" and i.decided_by == "fallback" and not i.evidence for i in doc.items)
    assert "판정하지 않았어요" in doc.items[0].note
    back = AlignmentDoc.from_dict(doc.to_dict())
    assert back.speech_match == "unrelated" and back.basis == "skipped"


def test_upstream_unrelated_hint_is_followed_even_for_short_talks():
    t = talk((1, "렘수면은 기억 정리와 관련이 있어요."))
    llm = LLM()
    doc = align_speech(LIB_G, t, llm=llm, slide_doc=LIB, speech_match="unrelated")
    assert llm.calls == 0 and doc.basis == "skipped"


def test_matched_talk_is_judged():
    t = talk((1, "연간 방문자는 3년 사이 15% 줄었어요."), (2, "대출 권수보다 독서 경험이 더 중요해요."),
             (3, "야간 개방 8주 동안 방문자가 77% 늘었어요."), (4, "좌석과 조명을 바꾸면 머무는 시간이 늘어요."))
    llm = LLM(aligned(("reading", "대출 권수보다 독서 경험이 더 중요해요.")))
    doc = align_speech(LIB_G, t, llm=llm, slide_doc=LIB)
    assert llm.calls == 1 and doc.speech_match == "matched" and doc.basis == "llm" and doc.speech_usable
    assert doc.summary.verdict_counts["contradiction"] == 0


# --- 폴백 표시 (G-A22) ---------------------------------------------------------------

def test_empty_llm_verdicts_are_marked_fallback():
    t = talk((1, "연간 방문자가 줄었어요."), (2, "독서 경험이 중요해요."), (3, "야간 개방을 했어요."), (4, "공간을 바꿔요."))
    llm = LLM([])
    doc = align_speech(LIB_G, t, llm=llm, slide_doc=LIB)
    assert llm.calls == 2                                     # 한 번 다시 묻는다
    assert doc.basis == "fallback" and not doc.speech_usable
    assert {i.decided_by for i in doc.items} == {"fallback"}
    ev = Evidence(alignment=doc)
    assert score_item(1, ev) is not None                      # 채점기 자체는 값을 내지만
    got = score_rubric(situation="school_project", alignment=doc, llm="mock")
    for no in (1, 4, 5, 30):                                  # 채점표는 짐작한 정합을 매기지 않는다
        assert got.item(no).status == "unmeasured" and "대조하지 못해서" in got.item(no).note
    assert [f.kind for f in got.faults] == ["align_fallback"]


def test_llm_omitted_node_is_fallback_but_judged_node_is_llm():
    t = talk((1, "연간 방문자는 3년 사이 15% 줄었어요."), (2, "독서 경험이 더 중요해요."))
    doc = align_speech(LIB_G, t, llm=LLM(aligned(("visitors", "연간 방문자는 3년 사이 15% 줄었어요."))), slide_doc=LIB)
    assert doc.item("visitors").decided_by == "llm"
    assert doc.item("space").decided_by == "fallback" and doc.basis == "llm"


# --- 시간 배분 (F-17) 이 같은 말을 한다 ----------------------------------------------

def _concepts(doc: SlideDoc, importance: dict[int, str]) -> ConceptDoc:
    return ConceptDoc(doc.file_name, doc.total_slides, slides=[
        SlideConcepts(slide_no=s.slide_no, title=s.title, topic=s.title, raw_text=s.raw_text,
                      importance=importance.get(s.slide_no, "core")) for s in doc.slides])


def test_pace_marks_the_skipped_slide_short_with_the_cue():
    pace = analyze_pace(WATER_TALK, Context(duration_min=2), _concepts(WATER, {4: "support"}))
    s3 = next(s for s in pace.slides if s.slide_no == 3)
    assert s3.status == "short" and "넘어갈게요" in s3.skip_cue and "건너뛴" in s3.note
    assert pace.tips[0].startswith("3번(핵심)은")
    assert all(not s.skip_cue for s in pace.slides if s.slide_no != 3)


def test_pace_attributes_cue_to_the_neighbour_slide_it_names():
    """장 경계가 한 장 밀려 3장 이야기의 「넘어갈게요」 가 4장 구간에 붙어도, 말에 나온 낱말로 3장을 건너뛴 것으로 본다."""
    t = talk((1, "물 섭취가 두통을 줄여요."), (2, "물을 2리터 마신 그룹은 두통 빈도가 35% 줄었어요."),
             (3, "그러니까 물이 중요해요."),
             (4, "이건 탈수 지수 계산식인데 시간 관계상 넘어갈게요. 카페인 음료는 소변량을 늘려요."))
    pace = analyze_pace(t, Context(duration_min=2), _concepts(WATER, {}))
    assert [s.slide_no for s in pace.slides if s.skip_cue] == [3]


# --- 채점표 · 리포트 -----------------------------------------------------------------

def _rich_alignment() -> AlignmentDoc:
    llm = LLM(aligned(("water", "오늘은 물 섭취가 두통을 줄인다는 이야기를 할게요."),
                      ("study", "물을 2리터 이상 마신 그룹은 두통 빈도가 평균 55퍼센트나 줄었다고 해요.")))
    return align_speech(WATER_G, WATER_TALK, llm=llm, slide_doc=WATER)


def test_faults_count_code_confirmed_contradictions_and_skipped_core_slides():
    doc = _rich_alignment()
    got = faults(Evidence(alignment=doc, graph=WATER_G))
    kinds = sorted(f.kind for f in got)
    assert kinds.count("contradiction") == 2 and kinds.count("skipped_slide") == 1
    assert any("55%" in f.text and "35%" in f.text for f in got)
    assert any(f.kind == "skipped_slide" and f.slide_no == 3 for f in got)


def test_llm_only_contradiction_is_not_a_capping_fault():
    t = talk((1, "물 섭취는 두통과 상관없어요."), (2, "연구가 있어요."))
    llm = LLM([{"node_id": "water", "verdict": "contradiction", "evidence": "물 섭취는 두통과 상관없어요."}])
    doc = align_speech(WATER_G, t, llm=llm)                     # 자료 원문 없음 → 코드 확인 불가
    assert doc.item("water").verdict == "contradiction" and not doc.item("water").deck_quote
    assert not [f for f in faults(Evidence(alignment=doc)) if f.kind == "contradiction"]


def test_rubric_caps_score_and_says_why():
    doc = _rich_alignment()
    got = score_rubric(situation="school_project", graph=WATER_G, alignment=doc, llm="mock")
    n = sum(1 for f in got.faults if f.kind in ("contradiction", "skipped_slide"))
    assert n == 3
    assert got.cap == CAP_FIRST - CAP_STEP * (n - 1) and got.score <= got.cap
    assert "총점은" in got.note and "건너뛴 핵심 장" in got.note
    assert RubricScore.from_dict(json.loads(json.dumps(got.to_dict()))).to_dict() == got.to_dict()


def test_unrelated_talk_rubric_skips_speech_items_and_report_does_not_praise_content():
    sents = split_sentences(SLEEP_WORDS)
    t = talk(*[(i % 4 + 1, s) for i, s in enumerate(sents)], sec=6.0)
    doc = align_speech(LIB_G, t, llm=LLM(), slide_doc=LIB)
    got = score_rubric(situation="school_project", slides=LIB, alignment=doc, transcript=t, llm="mock")
    for no in (1, 2, 4, 8, 27, 30):
        assert got.item(no).status == "unmeasured" and "발표가 아니라서" in got.item(no).note
    # 녹음 자체로 재는 항목(말하기 습관·속도·간투어·정적·총 길이)도 이 발표의 값이 아니다 — 0점이 아니라 못 쟀다 (09-30 REC-10:
    # 다른 발표 녹음인데 「여기부터 보세요: 시간 관리 0/100」·「말 속도를 … 빠르게 연습」 이었다)
    for no in (17, 19, 20, 21, 22, 23, 24, 31):
        assert got.item(no).status == "unmeasured" and "발표가 아니라서" in got.item(no).note, no
    assert {i.no for i in got.items if i.status == "scored"} <= {34, 35, 36, 37, 38, 39}   # 남는 건 자료만 보는 항목
    # 녹음으로 재는 것을 빼면 자료 항목만 남아 점수가 오른다 — 「이 자료의 발표」 로는 가장 낮은 상한 (09-30: 38 → 81 「A」 였다)
    from chuckchuck.f14_rubric import CAP_FLOOR
    assert got.cap == CAP_FLOOR and got.score <= CAP_FLOOR and [f.kind for f in got.faults] == ["unrelated_speech"]
    assert "다른 발표" in got.note and "말하기 습관만 봤" not in got.note

    class Praise(LLMProvider):
        name = "praise"

        def __init__(self):
            self.calls = 0

        def complete(self, **_):
            self.calls += 1
            return json.dumps({"one_liner": "모든 슬라이드를 꼼꼼히 설명했어요",
                               "strengths": ["파일럿 결과를 구체적으로 제시했어요", "말 속도가 일정해요"],
                               "weaknesses": [], "actions": ["말 속도를 300~350자/분으로 빠르게 연습해 보세요"]},
                              ensure_ascii=False)

    llm = Praise()
    rep = compose_report(PaceDoc(), __import__("chuckchuck").contracts.HabitDoc(), rubric=got, llm=llm)
    assert llm.calls == 0                               # 할 말이 「다시 올려 달라」 뿐이라 LLM 을 부르지 않는다
    assert "다른 발표" in rep.one_liner and "꼼꼼히" not in rep.one_liner
    assert rep.strengths == []                          # 「말 속도가 일정해요」 도 이 발표의 값이 아니다
    assert "다른 발표" in rep.weaknesses[0] and len(rep.weaknesses) == 1
    assert rep.actions and all("자/분" not in a and "빠르게" not in a for a in rep.actions) and "녹음을 다시 올려" in rep.actions[0]
    assert "재지 않았어요" in rep.pace_summary and "자/분" not in rep.pace_summary
    assert "보지 않았어요" in rep.habit_summary
    # 채점표가 폴백이라 결함 칸이 비어도 정합을 같이 보내면 알아본다
    assert compose_report(PaceDoc(), __import__("chuckchuck").contracts.HabitDoc(), rubric=RubricScore(score=12),
                          alignment=doc, llm=llm).strengths == [] and llm.calls == 0


def test_report_leads_with_faults_and_drops_consistency_praise():
    doc = _rich_alignment()
    got = score_rubric(situation="school_project", graph=WATER_G, alignment=doc, llm="mock")

    class Rosy(LLMProvider):
        name = "rosy"

        def complete(self, **_):
            return json.dumps({"one_liner": "핵심은 잘 전달했어요", "strengths": ["발표 내용이 자료와 일치해요", "목소리가 또렷해요"],
                               "weaknesses": ["속도가 조금 빨라요"], "actions": ["천천히 말해 보세요"]}, ensure_ascii=False)

    from chuckchuck.contracts import HabitDoc
    rep = compose_report(PaceDoc(), HabitDoc(), rubric=got, llm=Rosy())
    assert rep.one_liner.startswith("자료와 다르게 말한 곳이") and "3장" in rep.one_liner
    assert rep.strengths == ["목소리가 또렷해요"]
    assert "55%" in rep.weaknesses[0] and rep.weaknesses[-1] == "속도가 조금 빨라요"


# --- 시간 관리 — 비율로 (「시간 관리 5/100」) -------------------------------------------

def _half_length_pace() -> PaceDoc:
    """목표 10분에 5분만 — 네 장 모두 권장의 딱 절반씩 (나눈 모양은 완벽)."""
    slides = [SlidePace(slide_no=i, importance="core", actual_sec=75.0, recommended_sec=150.0, delta_sec=-75.0,
                        status="short") for i in range(1, 5)]
    from chuckchuck.contracts import SectionAlloc
    sections = [SectionAlloc("핵심(core)", [1, 2, 3, 4], recommended_sec=600.0, actual_sec=300.0, status="short")]
    return PaceDoc(target_sec=600.0, actual_sec=300.0, slides=slides, sections=sections)


def test_short_talk_is_charged_once_by_total_time_not_by_allocation():
    ev = Evidence(pace=_half_length_pace())
    assert score_item(31, ev)[0] == 0                  # 총 길이는 31번이 매긴다
    assert score_item(28, ev)[0] == 100                # 나눈 모양은 완벽하다
    assert score_item(32, ev)[0] == 100
    assert score_item(33, ev)[0] == 100


def test_skipped_core_slide_counts_as_zero_dwell():
    p = _half_length_pace()
    p.slides[2].skip_cue = "시간 관계상 그냥 넘어갈게요"
    ev = Evidence(pace=p)
    s28, why28 = score_item(28, ev)
    s33, why33 = score_item(33, ev)
    assert s28 < 100 and "3번은 말로 건너뛰었어요" in why28
    assert s33 < 100 and "3번은 말로 건너뛰었어요" in why33


# --- 유틸 -----------------------------------------------------------------------------

@pytest.mark.parametrize("text, want", [
    ("평균 49퍼센트나 낮았어요", "평균 49%나 낮았어요"),
    ("이십구 프로 낮았어요", "29% 낮았어요"),
    ("3 퍼센트 포인트 올랐고", "3%p 올랐고"),
    ("프로그램을 49개", "프로그램을 49개"),
    ("이십 분석을 했다", "이십 분석을 했다"),
    ("일이 많아서 이 년 동안", "일이 많아서 이 년 동안"),
    ("삼십만 원을 냈다", "30만원을 냈다"),
    ("사십 분의 시간", "40분의 시간"),
])
def test_spoken_numbers(text, want):
    assert spoken_numbers(text) == want


@pytest.mark.parametrize("sentence, want", [
    ("음 이건 계산식인데요, 시간 관계상 그냥 넘어갈게요.", True),
    ("이 부분은 설명 안 하고 넘어갈게요", True),
    ("자세한 건 생략할게요", True),
    ("이 과정은 건너뛰고 결론만 볼게요", True),
    ("다음으로 넘어갈게요.", False),
    ("그럼 다음 장으로 넘어가겠습니다.", False),
    ("넘어가기 전에 하나만 더 말씀드리면", False),
    ("시간 관계상 짧게 말씀드리면", False),
    ("여기까지 하고 넘어갈게요", False),
    ("생략된 전제가 있어요", False),
    ("이 부분은 생략합니다", True),
    ("자세한 설명은 생략하고 결론만 볼게요", True),
    # 발표 **내용** 속 건너뛰기 동사 — 발표자가 지금 건너뛰는 말이 아니다
    ("아침을 건너뛰면 점심에 폭식하게 돼요", False),
    ("아침을 건너뛰고 점심을 먹으면 혈당이 튀어요", False),
    ("광고를 스킵하면 수익이 줄어요", False),
    ("패스해서 골을 넣으면 이겨요", False),
    ("이 문제를 그냥 넘어가면 큰일 나요", False),
    ("생략하면 안 되는 단계예요", False),
    ("여기서 Temperature Parameter 라는 값도 잠깐 언급하고 넘어갈게요", False),
])
def test_skip_cue(sentence, want):
    assert skip_cue(sentence) is want


def test_utterances_stay_inside_segments_and_take_times_from_words():
    t = talk((1, "첫 문장이에요. 둘째 문장이에요."), (2, "셋째 문장이에요."))
    us = utterances(t)
    assert [(u.slide_no, u.seg, u.text) for u in us] == [
        (1, 0, "첫 문장이에요."), (1, 0, "둘째 문장이에요."), (2, 1, "셋째 문장이에요.")]
    assert us[0].start_sec == 0.0 and us[2].start_sec == 20.0


# --- 흐름(FlowDiff) 도 같은 말을 한다 -------------------------------------------------

def test_flow_is_empty_for_unrelated_talk():
    from chuckchuck.contracts import ConceptEdge
    from chuckchuck.f11_flow import build_flow_diff
    g = ConceptGraph("deck.pptx", 4, nodes=LIB_G.nodes,
                     edges=[ConceptEdge("visitors", "night", "parent"), ConceptEdge("reading", "space", "relates")])
    sents = split_sentences(SLEEP_WORDS)
    t = talk(*[(i % 4 + 1, s) for i, s in enumerate(sents)], sec=6.0)
    doc = align_speech(g, t, llm=LLM(), slide_doc=LIB)
    flow = build_flow_diff(g, doc)
    assert flow.issues == [] and flow.order_tau is None and flow.spoken_node_count == 0
    assert sorted(flow.ghost_node_ids) == sorted(n.id for n in g.nodes)


def test_flow_does_not_blame_missing_links_on_llm_failure():
    from chuckchuck.contracts import ConceptEdge
    from chuckchuck.f11_flow import build_flow_diff
    g = ConceptGraph("deck.pptx", 4, nodes=LIB_G.nodes, edges=[ConceptEdge("visitors", "reading", "relates")])
    t = talk((1, "연간 방문자가 줄었어요."), (2, "독서 경험이 중요해요."), (3, "야간 개방을 했어요."), (4, "공간을 바꿔요."))
    doc = align_speech(g, t, llm=LLM([]), slide_doc=LIB)
    assert doc.basis == "fallback"
    assert not [i for i in build_flow_diff(g, doc).issues if i.kind == "missing_link"]
