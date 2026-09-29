"""
녹음 ↔ 자료 대조의 F-11 한 벌 (09-30 녹음 대화 감사 REC-03·06·12 · 여러 장 개념의 모순) — LLM 없이 도는 합성 자료·발표.

- 모순의 갈래(수치·방향·맞다아니다)를 AlignmentItem.contra_kind 에 싣고 note 가 그 갈래로 말한다
- 말로 건너뛴 장(「다루지 않을게요」「빼고 … 가겠습니다」)은 가벼운 개념이라도 「정당한 생략」 이 아니다
- 여러 장에 걸친 개념 하나가 앞 장 모순을 받아도 뒤 장 모순이 버려지지 않는다
- LLM 인용의 문장마다 발화 확인 — 녹음에 없는 문장은 「이 슬라이드에서 한 말」 이 되지 않는다

분야: 동네 빨래방 · 청소년 합창단 (감사 덱·held-out 덱과 겹치지 않는다).
"""

from __future__ import annotations

import json

from chuckchuck._align_checks import resolve_evidence
from chuckchuck._spoken import utterances
from chuckchuck.contracts import (
    AlignmentItem,
    ConceptGraph,
    ConceptNode,
    Slide,
    SlideBlock,
    SlideDoc,
    SlideSpeech,
    Transcript,
    Word,
)
from chuckchuck.f11_align import align_speech
from chuckchuck.providers.llm_base import LLMProvider


# ---------------------------------------------------------------------------
# F-11 한 벌 — 모순 갈래 · 건너뛴 장 · 지어낸 인용
# ---------------------------------------------------------------------------

def talk(*segs: tuple[int, str], sec: float = 20.0) -> Transcript:
    by_slide, words, t = [], [], 0.0
    for no, text in segs:
        toks = text.split()
        step = sec / max(1, len(toks))
        words += [Word(tok, round(t + k * step, 2), round(t + (k + 1) * step, 2)) for k, tok in enumerate(toks)]
        by_slide.append(SlideSpeech(no, 1, t, t + sec, text))
        t += sec
    return Transcript(full_text=" ".join(x for _, x in segs), words=words, by_slide=by_slide, provider="clova", duration_sec=t)


def slide_doc(*slides: tuple[str, str]) -> SlideDoc:
    out = []
    for i, (title, body) in enumerate(slides, start=1):
        blocks = [SlideBlock("heading1", title)] + [SlideBlock("paragraph", ln) for ln in body.split("\n") if ln]
        out.append(Slide(slide_no=i, title=title, blocks=blocks))
    return SlideDoc("deck.pptx", len(out), out)


class LLM(LLMProvider):
    name = "scripted"

    def __init__(self, items: list[dict] | None = None):
        self.items = items or []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False) -> str:
        return json.dumps({"items": self.items, "speech_edges": [], "extra_concepts": []}, ensure_ascii=False)


LAUNDRY = slide_doc(
    ("동네 빨래방 운영 개선", "건조기 대기를 줄이는 운영 제안"),
    ("이용 현황", "평일 저녁 평균 대기는 14분입니다"),
    ("대기 시간 계산", "대기 시간 = 도착 간격 × 건조 시간 ÷ 건조기 수"),
    ("알림 서비스 효과", "알림 문자를 보낸 매장은 안 보낸 매장보다 재방문율 증가 폭이 컸습니다"),
    ("예외 매장", "24시간 무인 매장은 대기가 거의 없습니다"),
    ("제안", "건조기 두 대를 더 두면 대기가 절반으로 줄어듭니다"),
)
LAUNDRY_G = ConceptGraph("deck.pptx", 6, nodes=[
    ConceptNode(id="laundry", label="빨래방 운영", slide_nos=[1, 6], weight=1.0, importance="core"),
    ConceptNode(id="wait", label="평일 대기", slide_nos=[2, 3], summary="평일 저녁 평균 14분", weight=0.8, importance="core"),
    ConceptNode(id="formula", label="대기 시간 계산", slide_nos=[3], weight=0.6, importance="core"),
    ConceptNode(id="notice", label="알림 문자", slide_nos=[4], summary="재방문율 증가 폭이 컸다", weight=0.7, importance="core"),
    ConceptNode(id="revisit", label="재방문율", slide_nos=[4], weight=0.4, importance="core"),
    ConceptNode(id="unmanned", label="무인 매장", slide_nos=[5], weight=0.2, importance="support"),
    ConceptNode(id="dryer", label="건조기 증설", slide_nos=[6], weight=0.5, importance="core"),
])
LAUNDRY_TALK = talk(
    (1, "오늘은 동네 빨래방 운영 개선을 제안할게요."),
    (2, "평일 저녁 평균 대기는 이십사 분이에요."),
    (3, "이 식은 오늘 다루지 않을게요."),
    (4, "그리고 매장끼리도 견줘 봤는데요, 알림 문자를 보낸 매장이 안 보낸 매장보다 재방문율이 덜 늘었어요."),
    (5, "예외 매장은 오늘은 빼고 바로 제안으로 가겠습니다."),
    (6, "그래서 건조기 두 대를 더 두면 대기가 절반으로 줄어들어요."),
)


def _aligned_all() -> list[dict]:
    return [{"node_id": n.id, "verdict": "aligned", "evidence": seg.text.rstrip(".")}
            for n in LAUNDRY_G.nodes for seg in LAUNDRY_TALK.by_slide if seg.slide_no == n.slide_nos[0]]


def test_align_carries_contradiction_kinds():
    doc = align_speech(LAUNDRY_G, LAUNDRY_TALK, llm=LLM(_aligned_all()), slide_doc=LAUNDRY)
    wait, notice = doc.item("wait"), doc.item("notice")
    assert (wait.verdict, wait.contra_kind, wait.deck_slide_no) == ("contradiction", "number", 2)
    assert "24분" in wait.note and "14분" in wait.note
    assert (notice.verdict, notice.contra_kind, notice.deck_slide_no) == ("contradiction", "direction", 4)
    assert "방향" in notice.note
    # 발화 쪽 인용은 어긋난 절부터 — 앞의 딴 절(「그리고 매장끼리도 견줘 봤는데요,」)은 뗀다 (질문이 그 절을 따옴표로 들었다)
    assert notice.evidence == "알림 문자를 보낸 매장이 안 보낸 매장보다 재방문율이 덜 늘었어요."
    assert all(i.contra_kind == "" for i in doc.items if i.verdict != "contradiction")
    # 같은 문장을 설명함 근거로 쓴 다른 개념은 그 문장이 자료와 반대라는 말을 숨기지 않는다 (LLM 인용은 끝 부호를 곧잘 뺀다)
    revisit = doc.item("revisit")
    assert revisit.verdict == "aligned" and "4장과 방향이 반대" in revisit.note


def test_skipped_slides_with_new_cues_are_not_justified_skips():
    items = _aligned_all() + [{"node_id": "unmanned", "verdict": "justified_skip", "note": "보조 개념"}]
    items = [i for i in items if not (i["node_id"] == "unmanned" and i["verdict"] == "aligned")]
    doc = align_speech(LAUNDRY_G, LAUNDRY_TALK, llm=LLM(items), slide_doc=LAUNDRY)
    assert sorted(s.slide_no for s in doc.skipped_slides) == [3, 5]
    assert doc.item("formula").verdict == "missing" and doc.item("formula").evidence == ""   # 설명한 문장이 없다면서 인용을 남기지 않는다
    unmanned = doc.item("unmanned")                     # 가벼운 개념이라도 말로 건너뛴 장이면 정당한 생략이 아니다
    assert unmanned.verdict == "missing" and unmanned.decided_by == "code" and "5장" in unmanned.note


def test_contra_kind_round_trips_and_old_payloads_load():
    it = AlignmentItem(node_id="n", verdict="contradiction", contra_kind="polarity", deck_quote="x", evidence="y")
    assert AlignmentItem.from_dict(it.to_dict()).contra_kind == "polarity"
    assert AlignmentItem.from_dict({"node_id": "n", "verdict": "aligned"}).contra_kind == ""
    assert AlignmentItem.from_dict({"node_id": "n", "contra_kind": "모름"}).contra_kind == ""


def test_two_contradictions_on_one_multislide_concept_are_both_kept():
    """여러 장에 걸친 개념 하나가 앞 장 모순을 받아도 뒤 장 모순은 그 장의 다른 개념에 붙는다 (예전엔 통째로 버려졌다)."""
    g = ConceptGraph("deck.pptx", 6, nodes=[
        ConceptNode(id="ops", label="빨래방 운영", slide_nos=[1, 2, 4, 6], weight=1.0, importance="core"),
        ConceptNode(id="notice", label="알림 문자", slide_nos=[4], weight=0.5, importance="core"),
        ConceptNode(id="formula", label="대기 시간 계산", slide_nos=[3], weight=0.5, importance="core"),
        ConceptNode(id="unmanned", label="무인 매장", slide_nos=[5], weight=0.2, importance="support"),
    ])
    doc = align_speech(g, LAUNDRY_TALK, llm=LLM([]), slide_doc=LAUNDRY)
    assert sorted(i.deck_slide_no for i in doc.items if i.verdict == "contradiction") == [2, 4]


# ---------------------------------------------------------------------------
# 지어낸 인용 (REC-06)
# ---------------------------------------------------------------------------

CHOIR_TALK = talk(
    (1, "청소년 합창단 연습 방법을 소개할게요."),
    (2, "그래서 굳이 파트 연습을 길게 할 필요는 없다는 거죠. 저희는 호흡 훈련을 먼저 했어요."),
)
CHOIR_NODE = ConceptNode(id="breath", label="호흡 훈련", slide_nos=[2], summary="파트 연습보다 먼저 하는 호흡 연습")


def test_fabricated_sentence_is_dropped_and_unsupported_rest_downgrades():
    utts = utterances(CHOIR_TALK)
    node = ConceptNode(id="solo", label="독창 오디션", slide_nos=[2], summary="독창자를 뽑는 오디션")
    quote = "굳이 파트 연습을 길게 할 필요는 없다는 거죠. 독창 오디션은 합창보다 두 배 빨리 실력이 늘었습니다."
    assert resolve_evidence(quote, node, utts) == ""       # 남은 문장이 독창 오디션을 받치지 않는다


def test_fabricated_sentence_is_dropped_but_supported_rest_is_kept():
    utts = utterances(CHOIR_TALK)
    quote = "저희는 호흡 훈련을 먼저 했어요. 호흡 훈련 덕분에 음정 정확도가 40% 올랐습니다."
    assert resolve_evidence(quote, CHOIR_NODE, utts) == "저희는 호흡 훈련을 먼저 했어요."


def test_verbatim_and_paraphrased_quotes_keep_their_old_behaviour():
    utts = utterances(CHOIR_TALK)
    assert resolve_evidence("저희는 호흡 훈련을 먼저 했어요.", CHOIR_NODE, utts) == "저희는 호흡 훈련을 먼저 했어요."
    # 통째로 바꿔 말한 인용 — 발화 원문 문장으로 바뀐다(지어낸 글을 그대로 두지 않는다)
    got = resolve_evidence("저희 합창단은 호흡 훈련을 먼저 했다고 말했어요.", CHOIR_NODE, utts)
    assert got == "저희는 호흡 훈련을 먼저 했어요."
    # 발화와 애매하게만 겹치는 인용은 버린다 — 예전엔 LLM 글을 그대로 「발표에서 한 말」 로 보였다
    assert resolve_evidence("호흡 훈련은 무대 공포를 줄이고 고음을 안정시키는 핵심 비결입니다.", CHOIR_NODE, utts) == ""
