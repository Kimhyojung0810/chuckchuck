"""
함정 질문 (qa/trap, 2026-09-29) — 코드가 자료 줄 하나를 뒤집어 틀린 전제를 만들고(F-08), 판정은 답이 그 전제를
받아들였는지·바로잡았는지로 함정 가드를 건다(F-09).

왜: 09-29 기준선에서 LLM 이 붙인 함정 21/21 에 질문 속 전제가 없어 골자대로 한 정답이 wrong 35 였고, fix08 이
「LLM 이 전제를 적어 올 때만」 으로 조이자 solar 가 한 번도 안 적어 함정이 0개가 됐다.

덱은 **처음 보는 여러 분야**(카페 운영·식물 재배·도서관·물류)로 짰다 — 규칙이 특정 발표 낱말을 모르는지 마지막 절이 검사한다.
"""

import inspect
import json

from chuckchuck import _grounding as grounding
from chuckchuck import _traps as traps
from chuckchuck import build_questions, judge_answer
from chuckchuck.contracts import (
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    QaTriage,
    Question,
    Slide,
    SlideBlock,
    SlideDoc,
    TrapPremise,
    TriageMark,
)
from chuckchuck.f08_questions import QUESTION_SYSTEM_PROMPT, build_hint_ladder
from chuckchuck.f09_judge import _TRAP_AGREED_REACT
from chuckchuck.providers.llm_base import LLMProvider


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, payload: dict):
        self.payload = payload
        self.prompts: list[str] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.prompts.append(user)
        return json.dumps(self.payload, ensure_ascii=False)


def slide(no: int, text: str) -> Slide:
    return Slide(slide_no=no, title=f"{no}장", blocks=[SlideBlock(category="paragraph", text=text)])


def node(id, label, nos, depth=2, parent="root", summary="", weight=0.5):
    return ConceptNode(id=id, label=label, slide_nos=nos, summary=summary, weight=weight, depth=depth,
                       parent_id=None if depth == 1 else parent)


# ---------------------------------------------------------------------------
# 처음 보는 분야 네 개
# ---------------------------------------------------------------------------

CAFE = SlideDoc(file_name="cafe.pdf", total_slides=6, slides=[
    slide(1, "가격보다 중요한 대기 시간\n동네 카페 운영 개선안"),
    slide(2, "무인 주문기 효과\n무인 주문기 도입 후 평균 대기 시간이 12분에서 7분으로 42% 줄었습니다."),
    slide(3, "메뉴별 판매량\n| 메뉴 | 주간 판매량 |\n| --- | --- |\n| 아메리카노 | 420 |\n| 카페라테 | 310 |\n| 과일 스무디 | 95 |"),
    slide(4, "단골 만들기\n적립 쿠폰이 재방문을 늘립니다."),
    slide(5, "진짜 병목\n매장 문제는 좌석 수가 아니라 회전율이다"),
    slide(6, "주의할 점\n혼잡 시간에도 주문 누락은 없습니다."),
])
CAFE_GRAPH = ConceptGraph(file_name="cafe.pdf", total_slides=6, nodes=[
    node("root", "대기 시간", [1, 2], depth=1, weight=1.0),
    node("kiosk", "무인 주문기", [2]),
    node("menu", "메뉴별 판매량", [3]),
    node("coupon", "적립 쿠폰", [4]),
    node("turn", "회전율", [5]),
    node("miss", "주문 누락", [6]),
], edges=[ConceptEdge(from_id="root", to_id=n, kind="parent") for n in ("kiosk", "menu", "coupon", "turn", "miss")])

PLANT = SlideDoc(file_name="plant.pdf", total_slides=3, slides=[
    slide(1, "재배 결과\n물 주기를 줄인 화분이 매일 준 화분보다 뿌리가 20% 길었습니다.\n마사토는 상토보다 물 빠짐이 빠릅니다."),
    slide(2, "해석\n과습은 뿌리 호흡을 막습니다."),
    slide(3, "토양별 수분 유지\n| 토양 | 유지 시간(시간) |\n| --- | --- |\n| 마사토 | 18 |\n| 상토 | 46 |\n| 펄라이트 | 11 |"),
])
PLANT_GRAPH = ConceptGraph(file_name="plant.pdf", total_slides=3, nodes=[
    node("root", "뿌리 생장", [1, 2, 3], depth=1, weight=1.0),
    node("water", "물 주기", [1]),
    node("wet", "과습", [2]),
    node("soil", "토양 수분", [3]),
], edges=[ConceptEdge(from_id="root", to_id=n, kind="parent") for n in ("water", "wet", "soil")])


def idx_of(graph, deck):
    return grounding.build_index({s.slide_no: s for s in deck.slides}, graph.nodes)


def cands(graph, deck, node_id):
    n = graph.node(node_id)
    return traps.candidates(n.label, n.slide_nos, idx_of(graph, deck))


def kinds(cs):
    return [c.premise.kind for c in cs]


# ---------------------------------------------------------------------------
# 1. 전제 만들기 — 종류마다
# ---------------------------------------------------------------------------

def test_수치_전제는_자료에_없는_값으로_한_곳만_바꾼다():
    """09-29 P5: 바꾼 값은 ×2 가 아니라 ±20~50% 안의 믿을 만한 값이다 (qa/loop2)."""
    tp = next(c.premise for c in cands(CAFE_GRAPH, CAFE, "kiosk") if c.premise.kind == "number")
    assert tp.fact == "무인 주문기 도입 후 평균 대기 시간이 12분에서 7분으로 42% 줄었습니다"
    wrong = int(tp.wrong[0].rstrip("%"))
    assert tp.premise == f"무인 주문기 도입 후 평균 대기 시간이 12분에서 7분으로 {wrong}% 줄었습니다"
    assert wrong != 42 and 42 * 0.5 <= wrong <= 42 * 1.5
    assert tp.right == ["42%"] and tp.slide_no == 2


def test_표의_수치와_표의_끝을_뒤집는다():
    cs = cands(CAFE_GRAPH, CAFE, "menu")
    ext = next(c.premise for c in cs if c.premise.kind == "extreme")
    assert ext.premise == "표에서 「주간 판매량」 값이 가장 큰 메뉴는 과일 스무디"     # 첫 열 이름(「메뉴」)을 행 이름으로
    assert "아메리카노(420)" in ext.fact
    num = next(c.premise for c in cs if c.premise.kind == "number")
    assert num.premise.startswith("표에서 ") and "값이" in num.premise
    ext2 = next(c.premise for c in cands(PLANT_GRAPH, PLANT, "soil") if c.premise.kind == "extreme")
    assert ext2.premise.endswith("펄라이트") and "상토(46)" in ext2.fact


def test_비교_순서를_뒤집는다_제목_꼴과_문장_꼴():
    # 09-30 대화 감사 §12: 문장 없는 덱 첫 장(표지)은 함정 재료가 아니다 — CAFE 1장은 제목·부제뿐이라 표지다.
    assert traps.candidates("대기 시간", [1], idx_of(CAFE_GRAPH, CAFE)) == []
    # 제목 꼴 비교는 본문 장의 머리에 있으면 그대로 뒤집는다
    deck = SlideDoc(file_name="cafe2.pdf", total_slides=2, slides=[
        slide(1, "동네 카페 운영 개선안\n2026 가을"),
        slide(2, "가격보다 중요한 대기 시간\n무인 주문기 도입 후 대기 시간이 줄었습니다."),
    ])
    graph = ConceptGraph(file_name="cafe2.pdf", total_slides=2, nodes=[
        node("root", "카페 운영", [1, 2], depth=1, weight=1.0), node("wait", "대기 시간", [2])])
    title = traps.candidates("대기 시간", [2], idx_of(graph, deck))
    tp = next(c.premise for c in title if c.premise.kind == "order")
    assert tp.premise == "대기 시간보다 중요한 가격" and tp.fact == "가격보다 중요한 대기 시간"
    sent = next(c.premise for c in cands(PLANT_GRAPH, PLANT, "water") if c.premise.kind == "order")
    assert sent.premise == "상토는 마사토보다 물 빠짐이 빠릅니다" and sent.fact == "마사토는 상토보다 물 빠짐이 빠릅니다"
    assert traps.hits(sent.premise, sent.wrong, "order") and not traps.hits(sent.premise, sent.right, "order")


def test_방향_서술어_짝을_뒤집는다():
    tp = next(c.premise for c in cands(CAFE_GRAPH, CAFE, "coupon") if c.premise.kind == "direction")
    assert tp.premise == "적립 쿠폰이 재방문을 줄입니다"
    tp2 = next(c.premise for c in cands(PLANT_GRAPH, PLANT, "wet") if c.premise.kind == "direction")
    assert tp2.premise == "과습은 뿌리 호흡을 부추깁니다"


def test_부정과_대조를_뒤집는다():
    tp = next(c.premise for c in cands(CAFE_GRAPH, CAFE, "turn") if c.premise.kind == "negation")
    assert tp.premise == "매장 문제는 회전율이 아니라 좌석 수다"
    tp2 = next(c.premise for c in cands(CAFE_GRAPH, CAFE, "miss") if c.premise.kind == "negation")
    assert tp2.premise == "혼잡 시간에도 주문 누락은 있습니다"


def test_뒤집을_사실이_없으면_함정도_없다():
    deck = SlideDoc(file_name="x.pdf", total_slides=1, slides=[slide(1, "우리 동아리를 소개할게요\n함께해요")])
    graph = ConceptGraph(file_name="x.pdf", total_slides=1, nodes=[node("root", "동아리", [1], depth=1), node("a", "소개", [1])])
    assert cands(graph, deck, "a") == []
    assert traps.candidates("소개", [1], None) == []


def test_물음_줄_연도_시각_순위_구간은_뒤집지_않는다():
    deck = SlideDoc(file_name="y.pdf", total_slides=1, slides=[slide(
        1, "조사 개요 2025.09\n전날 18시에 주문을 마감합니다\n상위 10% 가게도 같았습니다\n몇 명이 올까?")])
    graph = ConceptGraph(file_name="y.pdf", total_slides=1, nodes=[node("root", "조사", [1], depth=1), node("a", "주문 마감", [1])])
    assert [c for c in cands(graph, deck, "a") if c.premise.kind == "number"] == []


def test_전제는_자료_줄과_같지_않고_바꾼_값은_자료에_없다():
    for graph, deck in ((CAFE_GRAPH, CAFE), (PLANT_GRAPH, PLANT)):
        idx = idx_of(graph, deck)
        rows = {grounding.squash(r.text) for r in idx.all_rows()}
        for n in graph.nodes:
            for c in traps.candidates(n.label, n.slide_nos, idx):
                assert grounding.squash(c.premise.premise) not in rows
                assert traps.verify(c.premise, idx)


# ---------------------------------------------------------------------------
# 2. F-08 — 코드가 함정을 고르고 문장을 확인한다
# ---------------------------------------------------------------------------

def _triage(graph, *ids, trap=False):
    return QaTriage(file_name=graph.file_name, total_slides=graph.total_slides, model="scripted", marks=[
        TriageMark(node_id=nid, rank=i, severity=1, trap=trap, source="core_weight", doc_weight=1.0)
        for i, nid in enumerate(ids, 1)])


def test_트랙_허용치만큼_함정이_생기고_루트는_빠진다():
    ids = ("root", "kiosk", "menu", "coupon", "turn", "miss")
    doc10 = build_questions(CAFE_GRAPH, _triage(CAFE_GRAPH, *ids), track="10", slidedoc=CAFE,
                            llm=ScriptedLLM({"questions": []}))
    traps10 = [q for q in doc10.questions if q.trap]
    assert len(traps10) == 3 and all(q.node_id != "root" for q in traps10)
    for q in traps10:
        tp = q.trap_premise
        assert tp is not None and "trap_generated" in q.basis.checks
        assert traps.question_carries(q.question, tp)
        assert q.answer_gist.startswith("질문의 전제와 달리") and q.answer_gist_parts == []
        assert q.question.endswith(("요.", "요?"))
    doc5 = build_questions(CAFE_GRAPH, _triage(CAFE_GRAPH, *ids), track="5", slidedoc=CAFE,
                           llm=ScriptedLLM({"questions": []}))
    assert sum(q.trap for q in doc5.questions) == 1
    doc1 = build_questions(CAFE_GRAPH, _triage(CAFE_GRAPH, *ids), track="1", slidedoc=CAFE,
                           llm=ScriptedLLM({"questions": []}))
    assert sum(q.trap for q in doc1.questions) == 0


def test_함정_전제가_질문_프롬프트에_실리고_LLM_문장이_실으면_쓴다():
    ids = ("root", "kiosk")
    first = build_questions(CAFE_GRAPH, _triage(CAFE_GRAPH, *ids), track="5", slidedoc=CAFE,
                            llm=ScriptedLLM({"questions": []}))
    tp = next(q.trap_premise for q in first.questions if q.trap)
    llm = ScriptedLLM({"questions": [{"node_id": "kiosk", "question": f"{tp.premise}라고 했는데, 비결이 뭔가요?"}]})
    doc = build_questions(CAFE_GRAPH, _triage(CAFE_GRAPH, *ids), track="5", slidedoc=CAFE, llm=llm)
    q = next(q for q in doc.questions if q.node_id == "kiosk")
    assert f"함정 전제: 「{tp.premise}」" in llm.prompts[0]
    assert "trap_llm_worded" in q.basis.checks and q.question.startswith(tp.premise)


def test_전제를_의심하게_하거나_지어낸_숫자를_단_LLM_문장은_템플릿으로():
    """qa/trap 벤치: solar 가 「…84%라고 했는데, 실제 값은 어떻게 되나요?」 처럼 함정을 드러내거나, 전제 옆에 자료에 없는
    수치를 붙였다."""
    ids = ("root", "kiosk")
    first = build_questions(CAFE_GRAPH, _triage(CAFE_GRAPH, *ids), track="5", slidedoc=CAFE,
                            llm=ScriptedLLM({"questions": []}))
    tp = next(q.trap_premise for q in first.questions if q.trap)
    for text in (f"{tp.premise}라고 했는데, 실제 값은 어떻게 되나요?",
                 f"{tp.premise}라고 했는데, 이 말이 맞다면 비결은 뭔가요?",
                 f"{tp.premise}라고 했는데, 매출이 37% 오른 것과 어떻게 이어지나요?"):
        doc = build_questions(CAFE_GRAPH, _triage(CAFE_GRAPH, *ids), track="5", slidedoc=CAFE,
                              llm=ScriptedLLM({"questions": [{"node_id": "kiosk", "question": text}]}))
        q = next(q for q in doc.questions if q.node_id == "kiosk")
        assert "trap_template" in q.basis.checks and q.question == traps.trap_question(tp), text


def test_함정_힌트_사다리는_자료_줄을_첫_칸에_두지_않는다():
    doc = build_questions(CAFE_GRAPH, _triage(CAFE_GRAPH, "root", "kiosk"), track="5", slidedoc=CAFE,
                          llm=ScriptedLLM({"questions": []}))
    q = next(q for q in doc.questions if q.trap)
    ladder = build_hint_ladder(q)
    assert q.trap_premise.fact not in ladder[0] and "2장" in ladder[0]
    assert any(q.trap_premise.fact in step for step in ladder[1:])


def test_계약_왕복():
    tp = TrapPremise(kind="number", premise="p", fact="f", slide_no=2, wrong=["84%"], right=["42%"])
    q = Question(id="q", node_id="n", label="l", question="?", trap=True, trap_premise=tp)
    back = Question.from_dict(json.loads(json.dumps(q.to_dict(), ensure_ascii=False)))
    assert back.trap_premise == tp
    assert Question.from_dict({"id": "q"}).trap_premise is None


# ---------------------------------------------------------------------------
# 3. F-09 — 전제를 알고 판정한다
# ---------------------------------------------------------------------------

def _trap_question():
    doc = build_questions(CAFE_GRAPH, _triage(CAFE_GRAPH, "root", "kiosk"), track="5", slidedoc=CAFE,
                          llm=ScriptedLLM({"questions": []}))
    return next(q for q in doc.questions if q.trap)


def _judge(q, answer, **payload):
    base = dict(verdict="good", score=85, react="좋아요.", summary_sentence="총평이에요.", missing_points=[], followup="")
    base.update(payload)
    return judge_answer(q, answer, graph=CAFE_GRAPH, slidedoc=CAFE, llm=ScriptedLLM(base))


def test_전제에_동의한_답은_함정_가드에_걸린다():
    q = _trap_question()
    assert q.trap_premise.kind == "number"
    for answer in ("네, 맞아요. 주문기 덕분에 대기가 확 줄었어요.",
                   f"무인 주문기를 들인 뒤 대기 시간이 {q.trap_premise.wrong[0]} 줄어든 건 주문이 분산됐기 때문이에요."):
        j = _judge(q, answer, premise_corrected=None)
        assert j.verdict == "wrong" and j.score <= 35 and j.react == _TRAP_AGREED_REACT, answer


def test_전제를_바로잡은_답은_LLM_이_틀려도_통과한다():
    q = _trap_question()
    for answer in (q.answer_gist,
                   "84%가 아니라 42%예요. 12분에서 7분으로 줄었어요.",
                   "자료와 달라요, 그렇게까지 줄지는 않았어요."):
        j = _judge(q, answer, premise_corrected=False)
        assert j.verdict == "good" and j.react != _TRAP_AGREED_REACT, (answer, j.verdict, j.react)


def test_딴_이야기는_함정_문구가_아니라_무관_가드로_간다():
    q = _trap_question()
    j = _judge(q, "저희 팀은 지난 분기에 물류 창고 세 곳의 재고 회전율을 비교했어요.", premise_corrected=False,
               verdict="partial", score=65)
    assert j.verdict == "wrong" and j.react != _TRAP_AGREED_REACT


def test_단서가_없으면_LLM_의_premise_corrected_를_따른다():
    q = _trap_question()
    j = _judge(q, "주문기 도입 뒤로 대기가 줄었어요.", premise_corrected=False, verdict="partial", score=72)
    assert j.verdict == "wrong" and j.react == _TRAP_AGREED_REACT


def test_순서와_방향_전제의_입장():
    order = TrapPremise(kind="order", premise="대기 시간보다 중요한 가격", fact="가격보다 중요한 대기 시간",
                        wrong=["대기 시간|보다", "대기|보다"], right=["가격|보다"])
    assert traps.premise_stance("맞아요, 대기 시간보다 가격이 더 중요해요.", order) == "agree"
    assert traps.premise_stance("가격보다 대기 시간이 더 중요해요.", order) == "correct"
    direction = TrapPremise(kind="direction", premise="적립 쿠폰이 재방문을 줄입니다", fact="적립 쿠폰이 재방문을 늘립니다",
                            wrong=["줄입니다|"], right=["늘립니다|"])
    assert traps.premise_stance("쿠폰이 재방문을 줄입니다. 할인에만 오니까요.", direction) == "agree"
    assert traps.premise_stance("오히려 재방문을 늘려요.", direction) == "correct"
    assert traps.premise_stance("", direction) == ""


# ---------------------------------------------------------------------------
# 4. 규칙에 발표 낱말이 없다 — 벤치 덱(튜닝·held-out)의 낱말이 규칙·프롬프트에 안 들어간다
# ---------------------------------------------------------------------------

BENCH_WORDS = ("수면", "수익률", "카페인", "연속성", "규칙성", "기관", "매매", "투자", "음주", "회복", "반찬", "배송",
               "혈당", "탄수화물", "전세", "보증", "상추", "적색", "청색", "소설", "알림", "집중", "매출", "공강",
               "카페", "주문기", "화분", "쿠폰")


def test_함정_규칙에_발표_낱말이_없다():
    patterns = [v.pattern for v in vars(traps).values() if hasattr(v, "pattern") and isinstance(v.pattern, str)]
    consts = [str(v) for v in vars(traps).values() if isinstance(v, (tuple, set, frozenset, dict))]
    blob = " ".join(patterns + consts)
    assert not [w for w in BENCH_WORDS if w in blob]
    code = "\n".join(line.split("#", 1)[0] for line in inspect.getsource(traps).splitlines())
    code_wo_docs = code.replace('"""', "\x00").split("\x00")[::2]
    assert not [w for w in BENCH_WORDS if any(w in part for part in code_wo_docs)]
    assert not [w for w in BENCH_WORDS if w in QUESTION_SYSTEM_PROMPT]
