"""
판정 근거 줄 (2026-10-01 · qa/judge-grounds) — LLM 은 자료 줄 **번호**만, 줄 글은 코드가 되찾는다 (`chuckchuck/_judge_grounds.py`).

사용자 보고: 「자료에서 제시한 '시간 × 연속성 × 규칙성'…」 이라는 반응이 몇 장 어느 줄에서 왔는지, 왜 그 줄이 답인지가 안 보였다.
"""

from __future__ import annotations

import json

from chuckchuck import judge_answer
from chuckchuck._client_payload import client_grounds, client_judgement
from chuckchuck._deck_claims import build_deck
from chuckchuck._judge_grounds import (
    DROP_COVERED_GUARDS,
    cite_slides,
    finalize_grounds,
    index_lines,
    parse_grounds,
    resolve_grounds,
)
from chuckchuck.contracts import (
    QA_GROUNDS_MAX,
    JudgeGround,
    QaJudgement,
    Question,
    Slide,
    SlideBlock,
    SlideDoc,
    TrapPremise,
)
from chuckchuck.providers.llm_base import LLMProvider


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, payload: dict):
        self.payload = payload
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.prompts.append(user)
        self.systems.append(system)
        return json.dumps(self.payload, ensure_ascii=False)


def slide(no: int, text: str) -> Slide:
    return Slide(slide_no=no, title=f"{no}장", blocks=[SlideBlock(category="paragraph", text=text)])


# 사용자가 보고한 덱의 판정에 쓰이는 장 (원문 그대로 — 식은 칸마다 나뉘어 있다)
SLEEP = SlideDoc(file_name="sleep.pdf", total_slides=8, slides=[
    slide(1, "수면 시간보다 중요한 수면의 질\n잠을 오래 잤다고 반드시 개운한 것은 아닙니다."),
    slide(4, "수면의 질은 단순한 “시간”보다 넓은 개념입니다.\n수면의 질 =\n시간\n×\n연속성\n×\n규칙성\n"
             "얼마나 잤는가\n얼마나 끊기지 않았는가\n언제 자고 일어났는가"),
    slide(6, "주말 몰아자기는 해결책일까\n잠을 보충할 수는 있어도 리듬까지 완전히 회복되지는 않습니다.\n평일\n02:00 취침\n"
             "사회적 시차\n평일과 주말의 수면 시간이 크게 달라질 때 생기는 리듬 차이"),
    slide(7, "수면의 질을 높이는 방법\n| 시간 부족 | 필요한 수면 시간 확보 |\n| --- | --- |\n| 규칙성 저하 | 일정한 기상 시간 유지 |"),
])
Q_SLEEP = Question(
    id="q01-sleep-quality", node_id="sleep-quality", label="수면의 질", slide_nos=[1, 4],
    question="수면 시간도 수면의 질의 요소인데, 수면의 질이 수면 시간보다 중요하다는 건 어떤 뜻인가요?",
    answer_gist="수면 시간도 수면의 질의 요소예요 — 「수면의 질 = 시간 × 연속성 × 규칙성」. 그래서 「수면 시간보다 중요한 수면의 질」은"
                " 수면 시간 하나만 보지 말고 요소 전체를 함께 봐야 한다는 뜻이에요.",
    evidence_slide_no=4, evidence_quote="수면의 질은 단순한 “시간”보다 넓은 개념입니다.",
)
A_SLEEP = ("한 번 수면을 진행했을 때 그 수면의 질이 매우 중요하다는 이유다. 아무리 잠을 많이 자더라도 수면의 질적이 미흡하게 된다면"
           " 사람은 피곤함을 느낄수밖에 없다.")
REACT_SLEEP = ("수면의 질이 수면 시간보다 중요하다는 점을 정확히 짚었어요. 다만, 자료에서 제시한 '시간 × 연속성 × 규칙성'이라는 구체적인"
               " 구성 요소와 그 관계를 함께 설명하면 더 완전한 답이 돼요.")


def judged(**kw) -> dict:
    base = dict(verdict="partial", score=65, react=REACT_SLEEP, summary_sentence="요지는 맞췄어요.",
                missing_points=["시간 × 연속성 × 규칙성의 관계"], followup="자료의 식에서 시간은 어떤 자리에 있나요?")
    base.update(kw)
    return base


def sleep_index():
    deck = build_deck((s.slide_no, s.raw_text) for s in SLEEP.slides)
    from chuckchuck._evidence import clean_slide_text
    return deck, index_lines(deck, {s.slide_no: clean_slide_text(s.raw_text) for s in SLEEP.slides})


# ---------------------------------------------------------------------------
# 계약
# ---------------------------------------------------------------------------

def test_판정_근거는_to_dict_from_dict_를_오간다():
    j = QaJudgement(question_id="q", verdict="partial", score=65, react="r", summary_sentence="s",
                    grounds=[JudgeGround(4, "수면의 질 = 시간 × 연속성 × 규칙성", "missing", "관계를 말해요.", "S4-2")])
    back = QaJudgement.from_dict(json.loads(json.dumps(j.to_dict(), ensure_ascii=False)))
    assert back.grounds == j.grounds
    assert j.to_dict()["grounds"][0] == {"slide_no": 4, "quote": "수면의 질 = 시간 × 연속성 × 규칙성", "role": "missing",
                                         "note": "관계를 말해요.", "ref": "S4-2"}


def test_옛_판정_dict_는_근거_없이_읽힌다():
    old = {"question_id": "q", "verdict": "good", "score": 85, "react": "r", "summary_sentence": "s"}
    assert QaJudgement.from_dict(old).grounds == []


def test_근거_dict_의_이상한_값은_계약이_다듬는다():
    d = {"question_id": "q", "grounds": [{"slide_no": "x", "quote": "줄", "role": "?"}, {"slide_no": 2, "quote": " "},
                                         "S4-2", *[{"slide_no": 1, "quote": f"줄{i}"} for i in range(5)]]}
    got = QaJudgement.from_dict(d).grounds
    assert got[0] == JudgeGround(0, "줄", "missing", "", "")
    assert len(got) == QA_GROUNDS_MAX


# ---------------------------------------------------------------------------
# 줄 번호
# ---------------------------------------------------------------------------

def test_줄_번호는_장마다_본문_차례로_매긴다():
    _, idx = sleep_index()
    assert idx.get("S4-2").text == "수면의 질 = 시간 × 연속성 × 규칙성"     # 칸마다 나뉜 식이 한 줄로
    assert idx.get("S4-1").text.startswith("수면의 질은 단순한")
    # 표만 있는 장도 번호가 매겨진다 — 표 행이 글줄보다 먼저 쌓여도 번호는 본문 차례다
    assert idx.get("S7-1").text == "수면의 질을 높이는 방법"
    assert any("일정한 기상 시간 유지" in r.text for r in idx.in_slide(7))
    assert idx.of_line(4, "수면의 질 = 시간 × 연속성 × 규칙성").ref == "S4-2"


def test_같은_자료면_같은_번호다():
    _, a = sleep_index()
    _, b = sleep_index()
    assert [(r.ref, r.text) for n in a.slides() for r in a.in_slide(n)] == \
           [(r.ref, r.text) for n in b.slides() for r in b.in_slide(n)]


# ---------------------------------------------------------------------------
# 번호 읽기 · 되찾기
# ---------------------------------------------------------------------------

def test_근거_번호는_여러_꼴로_읽는다():
    got = parse_grounds([{"ref": "S4-2", "role": "missing", "note": "n"}, "[S1-1]", {"ref": "4 - 3", "role": "빠진 것"},
                         {"ref": "S6", "role": "covered"}, {"ref": "수면의 질 = 시간"}, 42, {"id": "s7-1", "role": "hit"}])
    assert [(g.ref, g.role) for g in got] == [("S4-2", "missing"), ("S1-1", ""), ("S4-3", "missing"), ("S6", "covered"),
                                              ("S7-1", "covered")]
    assert parse_grounds(None) == [] and parse_grounds("S4-2")[0].ref == "S4-2"


def test_모르는_번호는_버리고_장만_맞으면_설명과_겹치는_줄로_잇는다():
    _, idx = sleep_index()
    raw = parse_grounds([{"ref": "S9-1", "role": "missing", "note": "없는 장"},
                         {"ref": "S4-9", "role": "missing", "note": "시간·연속성·규칙성이 곱으로 묶인 관계"},
                         {"ref": "S4", "role": "missing", "note": "전혀 다른 이야기"}])
    got = resolve_grounds(raw, idx)
    assert [(g.ref, g.quote) for g in got] == [("S4-2", "수면의 질 = 시간 × 연속성 × 규칙성")]


def test_LLM_이_자료_글을_옮겨_적은_ref_는_근거가_아니다():
    """번호가 아닌 글(인용 베낌)은 읽지 않는다 — 인용은 코드가 번호로 찾는다(09-29 논문 대조의 교훈)."""
    assert parse_grounds([{"ref": "수면의 질 = 시간 × 연속성 × 규칙성", "role": "missing"}]) == []


# ---------------------------------------------------------------------------
# 판정 끝까지 — 사용자가 보고한 그 질문·답
# ---------------------------------------------------------------------------

def test_판정_프롬프트는_번호_매긴_줄과_grounds_스키마를_싣는다():
    llm = ScriptedLLM(judged())
    judge_answer(Q_SLEEP, A_SLEEP, slidedoc=SLEEP, llm=llm)
    assert "[S4-2] 수면의 질 = 시간 × 연속성 × 규칙성" in llm.prompts[0]
    assert '"grounds"' in llm.systems[0] and "번호만 적어라" in llm.systems[0]
    # 프롬프트 규칙·스키마에 덱 낱말이 없다 — 어느 발표에나 같은 규칙
    for word in ("수면", "연속성", "규칙성"):
        assert word not in llm.systems[0]


def test_보고된_답에_근거_줄이_장_번호와_글_그대로_붙는다():
    llm = ScriptedLLM(judged(grounds=[
        {"ref": "S1-1", "role": "covered", "note": "제목 줄이 질이 시간보다 앞선다고 말해요."},
        {"ref": "S4-2", "role": "missing", "note": "이 식은 시간을 질의 세 요소 가운데 하나로 둬요 — 그 관계를 말해야 해요."}]))
    v = judge_answer(Q_SLEEP, A_SLEEP, slidedoc=SLEEP, llm=llm)
    assert [(g.slide_no, g.quote, g.role) for g in v.grounds] == [
        (1, "수면 시간보다 중요한 수면의 질", "covered"),
        (4, "수면의 질 = 시간 × 연속성 × 규칙성", "missing")]
    assert v.grounds[1].note.startswith("이 식은")
    # 맨 「자료에서 제시한」 에 근거 줄의 장 번호가 붙는다
    assert "자료 4장에서 제시한" in v.react


def test_LLM_이_근거를_안_주면_결손으로_코드가_줄을_고른다():
    v = judge_answer(Q_SLEEP, A_SLEEP, slidedoc=SLEEP, llm=ScriptedLLM(judged()))
    miss = [g for g in v.grounds if g.role == "missing"]
    assert miss and miss[0].slide_no == 4 and "×" in miss[0].quote
    assert "자료 4장에서" in v.react


def test_good_이면_빠진_줄은_싣지_않는다():
    llm = ScriptedLLM(judged(verdict="good", score=88, react="네, 그 설명이면 충분해요.", missing_points=[], followup="",
                             grounds=[{"ref": "S4-2", "role": "missing", "note": "관계"},
                                      {"ref": "S4-2", "role": "covered", "note": "이 식의 세 요소를 곱의 관계로 짚었어요."}]))
    v = judge_answer(Q_SLEEP, "수면의 질은 시간 × 연속성 × 규칙성이라서 시간은 세 요소 중 하나일 뿐이에요. 그래서 오래 자도 끊기거나 "
                              "불규칙하면 질이 낮아요.", slidedoc=SLEEP, llm=llm)
    assert v.verdict == "good"
    assert [g.role for g in v.grounds] == ["covered"]


# ---------------------------------------------------------------------------
# 가드와 맞추기
# ---------------------------------------------------------------------------

def test_자료와_어긋난_답은_가드가_찾은_줄이_맨_앞이고_짚은_줄은_뺀다():
    """다른 덱(수익률 격차 5장 표) — 가드가 수치 어긋남으로 등급을 내리면 그 자료 줄이 conflict 로 맨 앞에 선다."""
    from test_qa_fix09 import BEHAVIOR_C, GAP, GAP_GRAPH, Q_BEHAVIOR

    llm = ScriptedLLM(judged(verdict="partial", score=75, react="요지는 잡았어요. 타이밍 실패가 크다는 점은 정확해요.",
                             missing_points=[], grounds=[{"ref": "S5-7", "role": "covered", "note": "타이밍 실패를 짚었어요."}]))
    v = judge_answer(Q_BEHAVIOR, BEHAVIOR_C, graph=GAP_GRAPH, slidedoc=GAP, llm=llm)
    assert v.guard == "deck" and not v.passed
    assert v.grounds[0].role == "conflict" and v.grounds[0].slide_no == 5
    assert v.grounds[0].quote == "타이밍 실패 | -1.2" and v.grounds[0].ref == "S5-7"
    assert "covered" not in [g.role for g in v.grounds]
    assert v.grounds[0].note.startswith("다시 볼 곳:")


def test_답의_내용을_인정하지_않는_가드는_짚은_줄을_뺀다():
    deck, idx = sleep_index()
    cands = [JudgeGround(1, "수면 시간보다 중요한 수면의 질", "covered", "", "S1-1"),
             JudgeGround(4, "수면의 질 = 시간 × 연속성 × 규칙성", "missing", "관계를 봐요.", "S4-2")]
    for guard in ("off_topic", "echo", "injection"):
        assert guard in DROP_COVERED_GUARDS
        got = finalize_grounds(cands, index=idx, deck=deck, said="수면의 질이 중요해요", verdict="partial", passed=False,
                               guard=guard)
        assert [g.role for g in got] == ["missing"]


def test_답과_한_낱말도_안_겹치는_줄은_짚었다고_하지_않는다():
    deck, idx = sleep_index()
    cands = [JudgeGround(6, "사회적 시차", "covered", "", "S6-5")]
    assert finalize_grounds(cands, index=idx, deck=deck, said="수면의 질이 중요해요", verdict="partial", passed=False,
                            fallback=False) == []


def test_근거는_많아야_셋이고_한_줄은_한_번만_싣는다():
    deck, idx = sleep_index()
    refs = [idx.get(r) for r in ("S4-2", "S1-1", "S1-2", "S4-1", "S4-3")]
    cands = [JudgeGround(r.slide_no, r.text, "missing", "", r.ref) for r in refs]
    cands.append(JudgeGround(4, idx.get("S4-2").text, "covered", "", "S4-2"))
    got = finalize_grounds(cands, index=idx, deck=deck, said="잠", verdict="partial", passed=False)
    assert len(got) <= QA_GROUNDS_MAX
    assert len({(g.slide_no, g.quote) for g in got}) == len(got)
    assert [g for g in got if g.ref == "S4-2"][0].role == "missing"     # 빠진 쪽이 짚은 쪽을 이긴다


def test_골자를_통째로_옮긴_설명은_지우고_줄은_남긴다():
    llm = ScriptedLLM(judged(grounds=[{"ref": "S4-2", "role": "missing", "note": Q_SLEEP.answer_gist}]))
    v = judge_answer(Q_SLEEP, A_SLEEP, slidedoc=SLEEP, llm=llm)
    g = [x for x in v.grounds if x.ref == "S4-2"][0]
    assert g.quote == "수면의 질 = 시간 × 연속성 × 규칙성" and g.note == ""


def test_설명의_내부_번호와_합쇼체는_다듬는다():
    llm = ScriptedLLM(judged(grounds=[{"ref": "S4-2", "role": "missing", "note": "S4-2의 식은 시간이 세 요소 중 하나임을 보여 줍니다."}]))
    v = judge_answer(Q_SLEEP, A_SLEEP, slidedoc=SLEEP, llm=llm)
    note = [x for x in v.grounds if x.ref == "S4-2"][0].note
    assert "S4-2" not in note and "자료 4장" in note and note.endswith("보여 줘요.")


# ---------------------------------------------------------------------------
# 정답이 새면 안 되는 질문 — 안 풀린 함정
# ---------------------------------------------------------------------------

TRAP_DECK = SlideDoc(file_name="t.pdf", total_slides=2, slides=[
    slide(1, "도입 방법\n팀은 매주 회고를 연다."),
    slide(2, "결과\n회고를 연 뒤 배포 실패가 줄었다."),
])
Q_TRAP = Question(
    id="q02-retro", node_id="retro", label="회고", slide_nos=[2], trap=True,
    question="회고를 연 뒤 배포 실패가 늘었다고 했는데, 그 이유는 무엇인가요?",
    answer_gist="질문의 전제와 달리, 자료 2장은 「회고를 연 뒤 배포 실패가 줄었다」라고 해요.",
    evidence_slide_no=2, evidence_quote="회고를 연 뒤 배포 실패가 줄었다.",
    trap_premise=TrapPremise(kind="direction", premise="회고를 연 뒤 배포 실패가 늘었다", fact="회고를 연 뒤 배포 실패가 줄었다",
                             slide_no=2, wrong=["늘었|"], right=["줄었|"]),
)


def test_안_풀린_함정은_사실_줄을_근거로_싣지_않는다():
    llm = ScriptedLLM(judged(verdict="wrong", score=30, react="질문의 전제부터 확인해 보세요.", missing_points=[],
                             grounds=[{"ref": "S2-2", "role": "conflict", "note": "자료는 줄었다고 해요."}]))
    v = judge_answer(Q_TRAP, "네, 회고 때문에 사람들이 바빠져서 실패가 늘었어요", slidedoc=TRAP_DECK, llm=llm)
    assert not v.passed
    assert all("줄었" not in g.quote for g in v.grounds)


def test_화면_사본은_기대_답_전의_함정에서_빠진_줄과_사실_줄을_뺀다():
    grounds = [{"slide_no": 2, "quote": "회고를 연 뒤 배포 실패가 줄었다.", "role": "conflict"},
               {"slide_no": 1, "quote": "팀은 매주 회고를 연다.", "role": "missing"},
               {"slide_no": 1, "quote": "도입 방법", "role": "covered"}]
    assert client_grounds(Q_TRAP, grounds) == [grounds[2]]
    assert client_grounds(Q_SLEEP, grounds) == grounds              # 함정이 아니면 그대로
    j = QaJudgement(question_id=Q_TRAP.id, verdict="wrong", score=30, react="r", summary_sentence="s",
                    grounds=[JudgeGround.from_dict(g) for g in grounds])
    body = client_judgement(Q_TRAP, j)
    assert [g["quote"] for g in body["grounds"]] == ["도입 방법"] and "reveal_quote" not in body
    passed = QaJudgement(question_id=Q_TRAP.id, verdict="good", score=85, react="r", summary_sentence="s",
                         grounds=[JudgeGround.from_dict(grounds[0])])
    body = client_judgement(Q_TRAP, passed)
    assert body["grounds"][0]["quote"].startswith("회고를 연 뒤") and body["reveal_quote"]


# ---------------------------------------------------------------------------
# 반응 문장의 장 번호
# ---------------------------------------------------------------------------

G4 = JudgeGround(4, "수면의 질 = 시간 × 연속성 × 규칙성", "missing", "", "S4-2")
G1 = JudgeGround(1, "수면 시간보다 중요한 수면의 질", "covered", "", "S1-1")


def test_맨_자료에_장_번호를_끼우고_조사를_받침에_맞춘다():
    assert cite_slides("자료에서 제시한 연속성 식을 보세요.", [G4]) == "자료 4장에서 제시한 연속성 식을 보세요."
    assert cite_slides("자료를 다시 보면 규칙성이 있어요.", [G4]) == "자료 4장을 다시 보면 규칙성이 있어요."
    assert cite_slides("자료가 말하는 연속성 관계예요.", [G4]) == "자료 4장이 말하는 연속성 관계예요."
    assert cite_slides("규칙성은 자료와 같아요.", [G4]) == "규칙성은 자료 4장과 같아요."


def test_장_번호가_이미_있거나_자료가_아닌_낱말이면_두고_근거가_없으면_그대로다():
    assert cite_slides("자료 4장의 식을 보세요.", [G1]) == "자료 4장의 식을 보세요."
    assert cite_slides("자료들을 모아 봤어요.", [G4]) == "자료들을 모아 봤어요."
    assert cite_slides("자료에서 제시한 식이에요.", []) == "자료에서 제시한 식이에요."


def test_장은_그_문장과_가장_많이_겹치는_근거_줄로_고른다():
    text = "질이 시간보다 중요하다는 자료의 제목을 짚었어요. 자료에서 제시한 연속성 × 규칙성 식도 말해 보세요."
    assert cite_slides(text, [G1, G4]) == ("질이 시간보다 중요하다는 자료 1장의 제목을 짚었어요. "
                                           "자료 4장에서 제시한 연속성 × 규칙성 식도 말해 보세요.")


# ---------------------------------------------------------------------------
# 실측(2026-10-01 solar)에서 나온 모양
# ---------------------------------------------------------------------------

def test_번호를_잘못_센_근거는_설명이_가리키는_줄로_고친다():
    """실측: 「침대에 누워 있던 시간과 실제 회복 시간이 다를 수 있음」 을 설명하며 번호는 다른 줄을 댔다."""
    deck = build_deck([(1, "잠을 오래 잤다고 반드시 개운한 것은 아닙니다."),
                       (4, "수면의 질 = 시간\n×\n연속성\n핵심 침대에 누워 있던 시간과 실제로 회복한 시간은 다를 수 있습니다.")])
    idx = index_lines(deck)
    raw = parse_grounds([{"ref": "S1-1", "role": "missing", "note": "침대에 누워 있던 시간과 실제 회복 시간이 다를 수 있음을 설명함"},
                         {"ref": "S1-1", "role": "covered", "note": "오래 잔다고 개운하지 않다는 점을 짚었어요."}])
    got = resolve_grounds(raw, idx)
    assert got[0].slide_no == 4 and got[0].quote.startswith("핵심 침대에")
    assert got[1].slide_no == 1                                  # 설명이 번호의 줄과 겹치면 번호를 믿는다


def test_설명의_명사형_끝은_해요체로_푼다():
    from chuckchuck._judge_grounds import note_haeyo
    assert note_haeyo("세 요소의 곱셈 관계를 정의함") == "세 요소의 곱셈 관계를 정의해요."
    assert note_haeyo("이 식을 명시해야 함.") == "이 식을 명시해야 해요."
    assert note_haeyo("시간은 요소임") == "시간은 요소예요." and note_haeyo("이 줄이 핵심임") == "이 줄이 핵심이에요."
    assert note_haeyo("세 요소를 모두 포함") == "세 요소를 모두 포함해요."
    assert note_haeyo("이미 해요체예요.") == "이미 해요체예요."


def test_자료라는_말_없이_근거_줄을_따옴표로_옮긴_문장에_장을_단다():
    text = "그런데 '수면의 질 = 시간 × 연속성 × 규칙성'이라는 관계를 말하지 않았어요."
    assert cite_slides(text, [G1, G4]) == "그런데 '수면의 질 = 시간 × 연속성 × 규칙성'(자료 4장)이라는 관계를 말하지 않았어요."
    assert cite_slides("'전혀 다른 인용 문장'을 보세요.", [G4]) == "'전혀 다른 인용 문장'을 보세요."


def test_짚은_줄만_댄_판정에도_결손이_있으면_빠진_줄을_코드가_더한다():
    deck, idx = sleep_index()
    cands = [JudgeGround(1, "수면 시간보다 중요한 수면의 질", "covered", "", "S1-1")]
    got = finalize_grounds(cands, index=idx, deck=deck, said="수면의 질이 수면 시간보다 중요해요", verdict="partial",
                           passed=True, points=["시간 × 연속성 × 규칙성의 관계"], anchors=[1, 4])
    assert [g.role for g in got] == ["covered", "missing"]
    assert got[1].slide_no == 4 and "연속성" in got[1].quote


def test_좋은_답의_짚은_줄은_둘까지고_낱말_하나만_겹친_줄은_짚은_것이_아니다():
    """실측: good 85 에 짚은 줄 카드 셋 — 그중 하나는 답과 「시간」 한 낱말만 겹쳤다."""
    deck = build_deck([(4, "수면의 질은 단순한 “시간”보다 넓은 개념입니다.\n수면의 질 = 시간\n×\n연속성\n×\n규칙성\n"
                           "핵심 침대에 누워 있던 시간과 실제로 회복한 시간은 다를 수 있습니다.")])
    idx = index_lines(deck)
    said = "수면의 질은 시간 × 연속성 × 규칙성이라서 시간은 세 요소 가운데 하나일 뿐이에요. 오래 자도 자주 깨면 질이 낮아요."
    cands = [JudgeGround(4, r.text, "covered", "", r.ref) for r in idx.in_slide(4)]
    got = finalize_grounds(cands, index=idx, deck=deck, said=said, verdict="good", passed=True)
    assert [g.role for g in got] == ["covered", "covered"]
    assert all("침대" not in g.quote for g in got)


def test_어느_근거_줄과도_안_겹치는_문장의_자료에는_장을_달지_않는다():
    """코드 문장 「자료의 한쪽 말만 다시 했어요」 — 그 자료는 빠진 줄의 장이 아니다(되풀이한 쪽의 장이다)."""
    text = "자료의 한쪽 말만 다시 했어요. 질문은 두 말이 어떻게 함께 성립하는지 묻고 있어요."
    assert cite_slides(text, [G4]) == text


def test_장_번호는_LLM_이_쓴_문장에만_달고_개념_이름_겹침은_세지_않는다():
    code = "수면의 질 — 질문이 따지는 자료 줄을 다시 말하는 데 그쳤어요."
    assert cite_slides(code, [G4], only=[]) == code                         # 코드 문장
    assert cite_slides(code, [G4], ignore="수면의 질") == code               # 개념 이름만 겹친다
    llm = "수면의 질은 자료에서 제시한 연속성까지 봐야 해요."
    assert cite_slides(llm, [G4], only=[llm], ignore="수면의 질") == "수면의 질은 자료 4장에서 제시한 연속성까지 봐야 해요."


def test_인용은_문장_부호_앞_띄어쓰기만_붙이고_글자는_자료_그대로다():
    deck = build_deck([(8, "알림 확인은 짧지만 , 작업 맥락 복구는 보이지 않는 비용이다 .")])
    idx = index_lines(deck)
    got = finalize_grounds([JudgeGround(8, idx.get("S8-1").text, "covered", "", "S8-1")], index=idx, deck=deck,
                           said="알림 확인은 짧지만 작업 맥락 복구에 비용이 들어요", verdict="partial", passed=True)
    assert got[0].quote == "알림 확인은 짧지만, 작업 맥락 복구는 보이지 않는 비용이다."
