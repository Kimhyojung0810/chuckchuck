"""
F-08 질문 생성 — 2026-09-29 근거검증 기준선(docs/review/2026-09-29_QA_근거검증/baseline.md §5)에서 나온 문제의 회귀 테스트.

예시 문장·자료 줄은 두 실측 덱(수면 · 수익률격차)에서 그대로 옮겼다. **코드의 규칙에는 이 낱말들이 없다** —
규칙은 숫자·비교 표지·표의 행·슬라이드 줄·그래프 라벨로만 말한다 (마지막 절이 그걸 지킨다).

1. 함정 표시는 질문에 자료와 어긋나는 전제가 실제로 있을 때만 남는다
2. 골자의 숫자는 자료에서 그 숫자가 붙은 대상에, 비교는 자료의 비교 줄에, 표 값은 그 행에 — 아니면 자료 줄로 다시 쓴다
3. 자료로 답할 수 없는 질문(방법·측정, 검색 논문이 대상)은 정해진 문장으로 바꾼다
4. 관련 없는 논문은 서가에 못 올라오고, 논문 절을 뗀 질문의 골자에 논문 이야기가 남지 않는다
5. 힌트 인용은 질문과 낱말이 겹치는 줄이다
6. 폴백 문장·해라체 힌트·인사말 발화 인용
"""

import inspect
import json

from chuckchuck import _grounding as grounding
from chuckchuck import build_questions
from chuckchuck._evidence import best_quote
from chuckchuck.contracts import (
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    PaperDoc,
    PaperRef,
    QaTriage,
    Slide,
    SlideBlock,
    SlideDoc,
    Transcript,
    TriageMark,
)
from chuckchuck.f08_questions import (
    CITE_SYSTEM_PROMPT,
    PAPER_SYSTEM_ADDENDUM,
    PROBE_SYSTEM_ADDENDUM,
    QUESTION_SYSTEM_PROMPT,
    TRIAGE_SYSTEM_PROMPT,
    _fallback_text,
    _pick_marks,
    _polite_statement,
    _speech_quote,
)
from chuckchuck.f24_papers import _above_floor
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


# ---------------------------------------------------------------------------
# 두 실측 덱의 뼈대 (자료 줄은 원문 그대로, 필요한 장만)
# ---------------------------------------------------------------------------

INVEST = SlideDoc(file_name="gap.pdf", total_slides=11, slides=[
    slide(2, "격차는 실재한다\n· 개인 평균은 지수 대비 연 4.8%p\n낮음\n· 상위 25% 그룹도 지수를 2.6%p\n하회"),
    slide(3, "현황 진단\n먼저 격차가 실제로 존재하는지 확인한다\n| 시장지수 | 9 |\n| --- | --- |\n| 기관 | 8 |\n"
             "| 개인 상위25% | 6 |\n기관과의 차이는 작다\n지수 8.7% vs 기관 7.9% — 0.8%p\n상위 25%도 못 넘었다\n6.1%로 지수를 2.6%p 하회"),
    slide(5, "원인 구조\n격차를 만든 다섯 가지 행동 요인\n| 거래 비용 | -0.2 |\n| --- | --- |\n| 집중 투자 | -0.6 |\n"
             "| 손실 회피 | -0.8 |\n| 타이밍 실패 | -1.2 |\n| 과잉 매매 | -1.6 |\n핵심 요지\n상위 2개가 전체의 58%\n"
             "과잉 매매와 타이밍 실패에 집중\n요인 간 상호작용 존재"),
    slide(11, "성공 요인\n반대로, 상위 성과 그룹은 무엇이 달랐는가\n상위 25% vs 하위 25% 행동 지표\n"
              "| Category | 상위 25% | 하위 25% |\n| --- | --- | --- |\n| 회전율(회) | 1 | 12 |\n| 매도규칙(%) | 71 | 18 |\n"
              "핵심 요지\n회전율 8.4배 차이\n연 1.4회 vs 11.8회\n매도규칙 71% vs 18%\n사전 기준의 유무가 가장 큰 격차"),
])


def _node(id, label, nos, depth=2, parent="root", summary="", weight=0.5):
    return ConceptNode(id=id, label=label, slide_nos=nos, summary=summary, weight=weight, depth=depth,
                       parent_id=None if depth == 1 else parent)


INVEST_GRAPH = ConceptGraph(file_name="gap.pdf", total_slides=11, nodes=[
    _node("root", "수익률 격차", [2, 3], depth=1, summary="개인 투자자는 시장 수익률을 이기지 못한다", weight=1.0),
    _node("behavior", "행동 요인", [5], summary="격차를 만든 다섯 가지 행동 요인"),
    _node("institution", "기관", [3], summary="기관 투자자의 수익률"),
    _node("individual", "개인 투자자", [2, 3], summary="개인 투자자 집단의 평균 수익률"),
    _node("top25", "상위 25%", [2, 3, 11], summary="개인 투자자 중 상위 25% 그룹의 수익률"),
    _node("overtrading", "과잉 매매", [5], depth=3, parent="behavior"),
    _node("timing", "타이밍 실패", [5], depth=3, parent="behavior"),
    _node("sellrule", "매도 규칙", [11], depth=3, parent="behavior"),
    _node("turnover", "회전율", [11], depth=3, parent="behavior"),
], edges=[ConceptEdge(from_id="root", to_id=n, kind="parent") for n in ("behavior", "institution", "individual", "top25")])

SLEEP = SlideDoc(file_name="sleep.pdf", total_slides=5, slides=[
    slide(1, "수면 시간보다 중요한 수면의 질\n“어젯밤 몇 시간 잤나요?”\n5시간 미만\n5–7시간\n7시간 이상\n오늘의 질문\n"
             "“침대에 누운 시간”과 “회복한 시간”은 왜 다를까?"),
    slide(4, "충분히 자도 피곤한 진짜 이유\n수면의 질은 단순한 “시간”보다 넓은 개념입니다.\n수면의 질 =\n시간\n×\n연속성\n×\n규칙성\n"
             "핵심 침대에 누워 있던 시간과 실제로 회복한 시간은 다를 수 있습니다."),
    slide(5, "자다가 깨는 대표적인 원인\n수면의 연속성을 끊는 요인은 생각보다 일상적입니다.\n| 카페인 | 오후·<br>저녁 섭취 |\n"
             "| --- | --- |\n| 음주 | 수면 후반 각성 |\n| 스트레스 | 잠들기 전 각성 |\n| 환경 | 빛·<br>소음·<br>높은 온도 |"),
])

SLEEP_GRAPH = ConceptGraph(file_name="sleep.pdf", total_slides=5, nodes=[
    _node("root", "수면의 질", [1, 4], depth=1, summary="수면 시간보다 회복 효과가 더 중요함", weight=1.0),
    _node("time", "수면 시간", [1, 4], summary="침대에 누운 시간과 실제 회복 시간의 차이"),
    _node("recovery", "회복 시간", [1, 4], summary="피곤함"),
    _node("continuity", "수면 연속성", [4, 5], summary="수면 주기가 자주 끊기면 회복감 감소"),
    _node("regularity", "규칙성", [4], summary="일정한 기상 시간 유지"),
    _node("caffeine", "카페인", [5], depth=3, parent="continuity"),
    _node("alcohol", "음주", [5], depth=3, parent="continuity"),
], edges=[ConceptEdge(from_id="root", to_id=n, kind="parent") for n in ("time", "recovery", "continuity", "regularity")])


def triage(graph: ConceptGraph, *marks: tuple[str, bool]) -> QaTriage:
    return QaTriage(file_name=graph.file_name, total_slides=graph.total_slides, model="scripted", marks=[
        TriageMark(node_id=nid, rank=i, severity=1, trap=trap, source="core_weight", doc_weight=1.0)
        for i, (nid, trap) in enumerate(marks, 1)
    ])


def ask(graph, deck, marks, questions, **kw):
    """함정은 코드가 트랙 허용치만큼 고른다 (qa/trap). 함정이 아닌 동작을 보는 테스트(표시가 전부 False)는 허용치를 0 으로
    둬서 함정 선택이 끼어들지 않게 한다 — 실제로는 triage 표시와 상관없이 전제를 만들 수 있는 개념이 함정이 된다."""
    import chuckchuck.f08_questions as f08
    saved = f08.QA_TRACK_TRAPS
    if not any(trap for _, trap in marks):
        f08.QA_TRACK_TRAPS = {k: 0 for k in saved}
    try:
        llm = ScriptedLLM({"questions": questions})
        doc = build_questions(graph, triage(graph, *marks), track="10", slidedoc=deck, llm=llm, **kw)
    finally:
        f08.QA_TRACK_TRAPS = saved
    return {q.node_id: q for q in doc.questions}, llm


def idx_of(graph, deck):
    return grounding.build_index({s.slide_no: s for s in deck.slides}, graph.nodes)


# ---------------------------------------------------------------------------
# 1. 함정 — 전제가 질문에 있고 자료와 어긋날 때만
# ---------------------------------------------------------------------------

def test_루트_질문은_함정이_아니다():
    """기준선 §5-1: 루트 개념이 매번 trap=True 인데 질문엔 거짓 전제가 없었다 → 골자대로 한 답이 wrong 35.
    qa/trap: 주제(루트) 자리는 함정 자리가 아니다 — triage 가 함정이라 해도 코드가 전제를 만들지 않는다."""
    q, _ = ask(INVEST_GRAPH, INVEST, [("root", True)], [{
        "node_id": "root", "question": "수익률 격차가 실력보다 행동에서 비롯되었다는 주장을 뒷받침하는 실증적 근거는 무엇인가요?",
        "answer_gist": "개인 평균은 지수 대비 연 4.8%p 낮고, 상위 25% 그룹도 지수를 2.6%p 하회해요."}])
    got = q["root"]
    assert got.trap is False and got.trap_premise is None and "trap_generated" not in got.basis.checks
    assert "전제" not in got.answer_gist


def test_함정_전제는_코드가_자료_줄에서_만들고_자료와_어긋난다():
    """solar 는 trap_premise 를 한 번도 안 적었다(fix08 뒤 함정 0개). LLM 이 사실(58%)을 전제로 적어 와도 쓰지 않고,
    코드가 근거 장의 자료 줄 하나를 뒤집어 만든 전제를 얹는다 — 그 전제는 자료 어느 줄과도 같지 않다."""
    text = "과잉 매매와 타이밍 실패가 전체의 58%를 차지한다는데, 그 근거는 무엇인가요?"
    q, _ = ask(INVEST_GRAPH, INVEST, [("behavior", True)], [{
        "node_id": "behavior", "question": text, "trap_premise": "과잉 매매와 타이밍 실패가 전체의 58%를 차지한다"}])
    got = q["behavior"]
    tp = got.trap_premise
    assert got.trap is True and tp is not None and "trap_generated" in got.basis.checks
    assert "trap_template" in got.basis.checks            # LLM 문장은 코드 전제를 안 실었다
    assert tp.premise in got.question
    idx = idx_of(INVEST_GRAPH, INVEST)
    assert all(grounding.squash(r.text) != grounding.squash(tp.premise) for r in idx.all_rows())
    assert got.answer_gist.startswith("질문의 전제와 달리, 자료 5장") and tp.fact in got.answer_gist
    assert got.answer_gist_parts == []


def test_LLM_이_코드_전제를_실은_문장은_그대로_쓴다():
    q0, _ = ask(INVEST_GRAPH, INVEST, [("behavior", True)], [])
    tp = q0["behavior"].trap_premise
    worded = f"{tp.premise}라고 하셨는데, 그게 무슨 뜻인가요?"
    q, _ = ask(INVEST_GRAPH, INVEST, [("behavior", True)], [{"node_id": "behavior", "question": worded}])
    got = q["behavior"]
    assert got.trap is True and "trap_llm_worded" in got.basis.checks and tp.premise in got.question


def test_전제에_자료의_정답_단서가_섞인_문장은_버린다():
    q0, _ = ask(INVEST_GRAPH, INVEST, [("behavior", True)], [])
    tp = q0["behavior"].trap_premise
    leak = f"{tp.premise}라고 했는데, 사실은 {tp.fact} 아닌가요?"
    q, _ = ask(INVEST_GRAPH, INVEST, [("behavior", True)], [{"node_id": "behavior", "question": leak}])
    assert "trap_template" in q["behavior"].basis.checks and "trap_premise_missing" in q["behavior"].basis.checks


def test_폴백_자리에도_함정은_전제를_얹은_문장이다():
    """LLM 이 빠뜨려도 함정 문장은 코드가 전제로 만든다 — 전제 없는 함정 질문이 나가지 않는다."""
    q, _ = ask(INVEST_GRAPH, INVEST, [("behavior", True)], [])
    got = q["behavior"]
    assert got.trap is True and got.trap_premise.premise in got.question
    assert got.question.startswith("자료") and got.question.endswith(("요.", "요?"))


def test_힌트와_이유는_답을_흘리지_않는다():
    q, _ = ask(INVEST_GRAPH, INVEST, [("behavior", True)], [])
    got = q["behavior"]
    tp = got.trap_premise
    assert "5장" in got.hint and tp.fact not in got.hint and tp.fact not in got.why
    for cue in tp.right:
        head = cue.partition("|")[0]
        assert head not in got.hint and head not in got.why


def test_전제_판정_규칙():
    idx = idx_of(INVEST_GRAPH, INVEST)
    assert grounding.premise_drop_reason("과잉 매매와 타이밍 실패가 전체의 58%를 차지한다", idx) == "premise_numbers_true"
    assert grounding.premise_drop_reason("과잉 매매가 전체의 80%를 차지한다", idx) == ""          # 자료에 없는 숫자
    assert grounding.premise_drop_reason("기관이 71%로 개인보다 규칙을 잘 지킨다", idx) == ""        # 다른 대상의 숫자
    assert grounding.premise_drop_reason("상위 2개가 전체의 58%", idx) == "premise_is_deck_line"
    sleep = idx_of(SLEEP_GRAPH, SLEEP)
    assert grounding.premise_drop_reason("수면 시간이 수면의 질보다 더 중요하다", sleep) == "premise_comparison_true"


def test_질문_프롬프트가_함정_전제와_함정_골자_규칙을_말한다():
    assert '"trap_premise"' in QUESTION_SYSTEM_PROMPT
    assert "trap=true 질문의 골자는 전제에 동의하지 않는다" in QUESTION_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# 2. 골자 근거 — 숫자의 주어 · 비교 · 표의 행
# ---------------------------------------------------------------------------

def test_다른_대상의_숫자를_붙인_골자는_자료_줄로_다시_쓴다_기관_71():
    """기준선 deck/10 #5: 71%·18% 는 「상위 25% vs 하위 25%」 표의 값인데 골자가 기관·개인 평균에 붙였다 → good 85."""
    q, _ = ask(INVEST_GRAPH, INVEST, [("institution", False)], [{
        "node_id": "institution", "question": "기관 투자자의 수익률이 개인 투자자보다 높은 이유를 뒷받침하는 핵심 요인은 무엇인가요?",
        "answer_gist": "기관은 사전 매도 규칙 준수율이 71%로 개인 평균(18%)보다 훨씬 높아 불필요한 거래를 줄여 수익률을 개선했어요.",
        "answer_gist_parts": ["기관의 매도 규칙 준수율 71%", "개인 평균 18%"]}])
    got = q["institution"]
    assert "gist_rebuilt" in got.basis.checks
    assert "71" not in got.answer_gist and got.answer_gist.startswith("자료는 이렇게 말해요 — ")
    assert got.answer_gist_parts == []


def test_숫자의_주어_검사():
    idx = idx_of(INVEST_GRAPH, INVEST)
    bad = "개인 투자자의 높은 매매 회전율(연간 11.8회)이 거래 비용 증가를 유발해요."   # 11.8 은 하위 25% 값
    assert grounding.misplaced_numbers(bad, idx) == ["11.8"]
    ok = "과잉 매매는 연간 수익률에 -1.6%p, 타이밍 실패는 -1.2%p의 영향을 미치며, 두 요인이 전체 격차의 58%를 차지해요."
    assert grounding.gist_problems(ok, idx) == []
    ok2 = "상위 25% 개인 투자자는 연 6.1% 수익률로 시장 지수(8.7%)를 2.6%p 하회해요."
    assert grounding.misplaced_numbers(ok2, idx) == []
    # 표가 값으로만 말하는 서열(「가장 큰」)은 표의 극값이 받친다
    assert grounding.unbacked_comparisons("과잉 매매가 연간 수익률에 가장 큰 영향을 미쳤어요.", idx) == []


def test_자료에_없는_서열을_지어낸_골자는_다시_쓴다():
    """기준선 수면 #1: 자료는 곱(시간 × 연속성 × 규칙성)인데 골자가 「연속성과 규칙성이 더 큰 영향」 서열을 지어냈다."""
    gist = "수면의 질은 시간, 연속성, 규칙성의 곱으로 정의되며, 특히 연속성과 규칙성이 회복 효과에 더 큰 영향을 미친다고 설명했어요."
    q, _ = ask(SLEEP_GRAPH, SLEEP, [("root", False)], [{
        "node_id": "root", "question": "시간도 수면의 질의 요소인데, 수면의 질이 시간보다 중요하다는 건 어떤 뜻인가요?",
        "answer_gist": gist}])
    got = q["root"]
    assert "gist_rebuilt" in got.basis.checks and "더 큰 영향" not in got.answer_gist
    idx = idx_of(SLEEP_GRAPH, SLEEP)
    assert grounding.unbacked_comparisons("수면의 질이 수면 시간보다 중요해요.", idx) == []


def test_표의_한_행_값을_다른_행에_붙인_골자는_다시_쓴다():
    """기준선 수면 rec/10 #3: 「수면 후반 각성」 은 음주 행의 값인데 카페인에 붙였다."""
    idx = idx_of(SLEEP_GRAPH, SLEEP)
    swapped = "음주는 수면 후반부에 각성을 유발하고, 카페인은 오후나 저녁에 섭취 시 수면 후반부에 각성을 유발해요."
    lumped = "카페인, 음주, 스트레스, 환경 요인 등이 수면 후반 각성을 유발해 수면 주기를 끊어요."
    right = "음주는 수면 후반에 각성을 일으키고, 스트레스는 잠들기 전 각성을 일으켜요."
    assert grounding.misattributed_cells(swapped, idx) and grounding.misattributed_cells(lumped, idx)
    assert grounding.misattributed_cells(right, idx) == []


def test_맞는_골자는_그대로_둔다():
    gist = "과잉 매매는 연간 수익률에 -1.6%p, 타이밍 실패는 -1.2%p의 영향을 미치며, 두 요인이 전체 격차의 58%를 차지해요."
    q, _ = ask(INVEST_GRAPH, INVEST, [("behavior", False)], [{
        "node_id": "behavior", "question": "다섯 가지 행동 요인 중 과잉 매매와 타이밍 실패의 상대적 크기는 어떻게 측정되었나요?",
        "answer_gist": gist}])
    got = q["behavior"]
    assert got.answer_gist == gist and "gist_rebuilt" not in got.basis.checks
    assert "method_unsupported" not in got.basis.checks      # 5장 표에 수치가 있다


# ---------------------------------------------------------------------------
# 3. 자료로 답할 수 없는 질문
# ---------------------------------------------------------------------------

def test_근거_장에_수치_방법_출처가_없는_측정_질문은_바꾼다():
    """기준선 수면 deck #2·deck/10 #2·#6·#7: 「어떻게 측정/계산/정량화했나요」 — 자료엔 그런 게 없다."""
    q, _ = ask(SLEEP_GRAPH, SLEEP, [("continuity", False), ("recovery", False)], [
        {"node_id": "continuity", "question": "수면 주기가 자주 끊기면 회복감이 감소한다는 주장을 뒷받침하는 구체적인 측정 기준은 무엇인가요?"},
        {"node_id": "recovery", "question": "침대에 누운 시간과 실제 회복 시간의 차이를 어떻게 계산했나요?"},
    ])
    for nid in ("continuity", "recovery"):
        got = q[nid]
        assert "method_unsupported" in got.basis.checks and "측정" not in got.question and "계산" not in got.question


def test_측정_질문_판정():
    sleep = idx_of(SLEEP_GRAPH, SLEEP)
    assert grounding.asks_method("피곤함을 회복 시간으로 정량화하는 방법은 무엇인가요?")
    assert not grounding.method_supported("피곤함을 회복 시간으로 정량화하는 방법은 무엇인가요?", [1, 4], sleep)   # 1장 수치는 설문 보기
    invest = idx_of(INVEST_GRAPH, INVEST)
    assert grounding.method_supported("과잉 매매와 타이밍 실패의 크기는 어떻게 측정되었나요?", [5], invest)
    assert not grounding.asks_method("두 요인이 서로 어떻게 이어지나요?")


def _scholar(pid, cite_surname, year, title, abstract="", nodes=("regularity",)):
    return PaperRef(id=pid, kind="scholar", title=title, authors=[cite_surname], year=year, et_al=True,
                    abstract=abstract, node_ids=list(nodes))


SLEEP_PAPERS = PaperDoc(file_name="sleep.pdf", provider="fake", refs=[
    _scholar("s07", "Chaput", 2020, "Sleep timing, sleep consistency, and health in adults: a systematic review",
             "The objective of this systematic review was to examine the associations between sleep timing and health."),
])


def test_검색_논문이_대상인_질문은_바꾸고_골자의_논문_이야기도_뗀다():
    """기준선 수면 규칙성 3/3: 「Chaput et al. (2020)의 연구에서 … 어떻게 설명했나요?」 — 발표자가 인용하지 않은 논문이다."""
    q, _ = ask(SLEEP_GRAPH, SLEEP, [("regularity", False)], [{
        "node_id": "regularity",
        "question": "Chaput et al. (2020)의 연구에서 일정한 기상 시간 유지가 수면 질에 미치는 영향에 대해 어떻게 설명했나요?",
        "hint": "문헌 초록에서 언급된 효과를 떠올려 보세요",
        "answer_gist": "Chaput et al. (2020)은 일정한 기상 시간 유지가 건강에 긍정적인 영향을 미친다고 보고했어요.",
        "paper_ids": ["s07"]}], papers=SLEEP_PAPERS)
    got = q["regularity"]
    assert "scholar_question_dropped" in got.basis.checks and "Chaput" not in got.question
    assert "Chaput" not in got.answer_gist and "문헌" not in got.hint and got.paper_ids == []


def test_weak_자리를_순위로_채울_때는_잎보다_가지를_먼저_본다():
    marks = [TriageMark(node_id=n, rank=r, severity=2, source="core_weight")
             for r, n in enumerate(["root", "time", "caffeine", "regularity"], 1)]
    depth = {n.id: n.depth for n in SLEEP_GRAPH.nodes}
    slots: dict[str, str] = {}
    picked, _ = _pick_marks(marks, "5", depth, set(), slots)
    assert [m.node_id for m in picked][:3] == ["root", "time", "regularity"]
    assert "regularity" not in slots        # 배합이 고른 것이 아니다 — 자리 이름은 비워 둔다


# ---------------------------------------------------------------------------
# 4. 관련 없는 논문
# ---------------------------------------------------------------------------

def test_수량_낱말만_겹친_논문은_관련성_바닥에서_떨어진다():
    """기준선 §5-5: 「상위 25%」 개념에 소득 상위 1% 논문이 붙었다 (top·percent·return 만 겹쳤다)."""
    concept = "top 25 percent individual investor return performance"
    off = PaperRef(id="s01", kind="scholar", title="The Top 1 Percent in International and Historical Perspective",
                   abstract="The top 1 percent income share has more than doubled. Returns to capital and investment income matter.")
    on = PaperRef(id="s02", kind="scholar", title="Portfolio Concentration and the Performance of Individual Investors",
                  abstract="This paper tests whether information advantages help explain why some individual investors concentrate.")
    assert not _above_floor(off, concept) and _above_floor(on, concept)
    ko = PaperRef(id="s03", kind="scholar", title="개인 투자자의 매매 빈도와 수익률", abstract="")
    node = INVEST_GRAPH.node("individual")
    assert _above_floor(ko, concept, node)


def test_논문_절을_뗀_질문의_골자에_논문_이야기가_남지_않는다():
    from chuckchuck.f08_questions import _strip_paper_claim
    ref = _scholar("s01", "Alvaredo", 2013, "The Top 1 Percent", nodes=("top25",))
    raw = {"node_id": "top25",
           "question": "Alvaredo et al. (2013)는 구조적 요인을 봤는데, 상위 25% 개인 투자자의 격차는 어떤 행동으로 설명되나요?",
           "answer_gist": "상위 25%도 지수를 2.6%p 하회해요. 문헌에서 제시한 '노동 시장 협상 모델'과는 다른 접근이에요.",
           "answer_gist_parts": ["상위 25%도 지수를 2.6%p 하회", "문헌의 구조적 설명과 발표의 행동적 설명 비교"]}
    _strip_paper_claim(raw, ref)
    assert raw["_paper_stripped"] == "s01" and "Alvaredo" not in raw["question"]
    papers = PaperDoc(file_name="gap.pdf", provider="fake", refs=[ref])
    q, _ = ask(INVEST_GRAPH, INVEST, [("top25", False)], [raw], papers=papers)
    got = q["top25"]
    assert "문헌" not in got.answer_gist and "협상" not in got.answer_gist
    assert "gist_paper_stripped" in got.basis.checks
    assert all("문헌" not in p for p in got.answer_gist_parts)


# ---------------------------------------------------------------------------
# 5. 힌트 인용은 질문과 겹치는 줄
# ---------------------------------------------------------------------------

def test_인용은_개념_이름이_든_제목보다_질문과_겹치는_줄이다():
    """기준선 §4: 「58%」 를 묻는데 제목 줄 «격차를 만든 다섯 가지 행동 요인» 이 이겼다."""
    texts = [(5, INVEST.slides[2].raw_text)]
    no, quote = best_quote("행동 요인", "격차를 만든 다섯 가지 행동 요인", texts,
                           "과잉 매매와 타이밍 실패가 수익률 격차의 58%를 차지한다는 계산 근거는 무엇인가요?")
    assert no == 5 and quote != "격차를 만든 다섯 가지 행동 요인"
    assert "58" in quote or "과잉 매매" in quote
    texts = [(1, SLEEP.slides[0].raw_text), (4, SLEEP.slides[1].raw_text)]
    _, quote = best_quote("수면 시간", "침대에 누운 시간과 실제 회복 시간의 차이", texts,
                          "침대에 누운 시간과 실제 회복 시간의 차이를 어떻게 계산했나요?")
    assert "침대" in quote


def test_폴백_질문도_질문과_겹치는_인용을_받는다():
    q, _ = ask(INVEST_GRAPH, INVEST, [("behavior", False)], [])
    got = q["behavior"]
    assert "fallback_template" in got.basis.checks and got.evidence_quote
    assert "행동 요인" in got.evidence_quote or "요인" in got.evidence_quote


# ---------------------------------------------------------------------------
# 6. 폴백 문장 · 해라체 · 발화 인용
# ---------------------------------------------------------------------------

def test_폴백_질문은_근거마다_해요체_한_문장이고_angle_메모를_붙이지_않는다():
    node = INVEST_GRAPH.node("top25")
    for source in ("contradiction", "missing", "under_spoken", "weak_flow", "extra", "core_weight", "justified_skip", "tension"):
        mark = TriageMark(node_id="top25", source=source, angle="상위 25% 개인 투자자의 수익률이 기관 대비 얼마나 차이가 나는지")
        q, _, _ = _fallback_text(node, mark, None, slide_nos=[2, 3])
        assert q.endswith(("요.", "요?")), q
        assert "—" not in q and ":" not in q
        assert "기관 대비" not in q


def test_힌트_이유_골자의_해라체와_한다체는_해요체로():
    assert _polite_statement("손실 종목을 오래 보유하는 것이 성과에 어떤 영향을 미치는지 생각해 보라") \
        == "손실 종목을 오래 보유하는 것이 성과에 어떤 영향을 미치는지 생각해 보세요"
    assert _polite_statement("막대 그래프의 길이와 퍼센트 포인트 값을 참고하라") == "막대 그래프의 길이와 퍼센트 포인트 값을 참고하세요"
    assert _polite_statement("자료 본문의 설명을 근거로 한다.") == "자료 본문의 설명을 근거로 해요."
    assert _polite_statement("오른 종목은 빠지고 내린 종목만 쌓인다") == "오른 종목은 빠지고 내린 종목만 쌓여요"
    assert _polite_statement("이미 해요체예요.") == "이미 해요체예요."
    q, _ = ask(INVEST_GRAPH, INVEST, [("behavior", False)], [{
        "node_id": "behavior", "question": "다섯 요인 가운데 어느 것이 가장 통제하기 쉬운가요?",
        "hint": "막대 그래프의 길이와 퍼센트 포인트 값을 참고하라", "why": "요인별 크기를 확인한다"}])
    assert q["behavior"].hint.endswith("참고하세요") and q["behavior"].why.endswith("확인해요")


def _transcript(text_by_slide: dict[int, str]) -> Transcript:
    return Transcript.from_dict({"by_slide": [
        {"slide_no": no, "start_sec": 0, "end_sec": 1, "text": text}
        for no, text in text_by_slide.items()]})


def test_발화_인용은_인사말을_건너뛰고_질문과_겹치는_말을_고른다():
    """기준선 §4: 발화 인용이 근거 장 발화의 앞 120자라 「아 안녕하세요 오늘 주제는…」 이 나왔다."""
    tr = _transcript({2: "아 안녕하세요 오늘 주제는 개인 투자자는 왜 시장을 이기지 못하는가입니다 "
                         "개인 평균은 지수보다 연 4.8% 포인트 낮았습니다 상위 25% 그룹도 지수를 못 넘었습니다"})
    said = _speech_quote([2], tr, "상위 25% 그룹도 지수를 못 넘은 이유는 무엇인가요?", INVEST_GRAPH.node("top25"))
    assert "안녕하세요" not in said and "상위 25%" in said
    assert _speech_quote([2], _transcript({2: "안녕하세요 발표를 시작하겠습니다"}), "질문?") == ""


# ---------------------------------------------------------------------------
# 규칙에 발표 낱말이 없다 (09-29 사용자 지시 — 부스에 들어오는 아무 PPT 에나)
# ---------------------------------------------------------------------------

DECK_WORDS = ("수면", "수익률", "카페인", "연속성", "규칙성", "기관", "매매", "투자", "음주", "회복")


def test_프롬프트_예시에_두_실측_덱의_문장이_없다():
    for prompt in (QUESTION_SYSTEM_PROMPT, PROBE_SYSTEM_ADDENDUM, TRIAGE_SYSTEM_PROMPT, CITE_SYSTEM_PROMPT, PAPER_SYSTEM_ADDENDUM):
        assert not [w for w in DECK_WORDS if w in prompt], [w for w in DECK_WORDS if w in prompt]


def test_근거_검사_규칙에_발표_낱말이_없다():
    patterns = [v.pattern for v in vars(grounding).values() if hasattr(v, "pattern") and isinstance(v.pattern, str)]
    words = [w for w in grounding.__dict__.values() if isinstance(w, (tuple, set, frozenset))]
    blob = " ".join(patterns) + " ".join(str(w) for w in words)
    assert not [w for w in DECK_WORDS if w in blob]
    # 코드 본문(주석·문서 문자열 제외)에도 없다
    code = "\n".join(line.split("#", 1)[0] for line in inspect.getsource(grounding).splitlines())
    code_wo_docs = code.replace('"""', "\x00").split("\x00")[::2]
    assert not [w for w in DECK_WORDS if any(w in part for part in code_wo_docs)]


# ---------------------------------------------------------------------------
# 일반화 벤치 (2026-09-29, docs/review/2026-09-29_QA_근거검증/bench/report.md) 에서 넘어온 것
# ---------------------------------------------------------------------------

def test_탐침_개념은_변별_낱말로도_부른_것으로_친다():
    """벤치 §요약: held-out 라벨은 길고 합성어라 통째 대조가 떨어져 탐침 질문 69% 가 템플릿으로 갔다."""
    from chuckchuck.contracts import Probe
    from chuckchuck.f08_questions import _probe_mentions
    probe = Probe(kind="tension", node_ids=["a", "b"])
    labels = {"a": "혈당 스파이크 영향", "b": "식사 순서"}
    assert _probe_mentions("혈당 스파이크 영향과 식사 순서는 어떤 관계인가요?", probe, labels) == "all"
    assert _probe_mentions("혈당 스파이크가 생기면 식사 순서를 바꾸는 게 도움이 되나요?", probe, labels) == "partial"
    assert _probe_mentions("식사 순서만 바꾸면 되나요?", probe, labels) == ""          # 대상 개념이 없다
    shared = {"a": "수면의 질", "b": "수면 시간"}                                          # 겹치는 낱말(수면)은 변별이 아니다
    assert _probe_mentions("수면이 길면 되나요?", Probe(kind="tension", node_ids=["a", "b"]), shared) == ""


def test_탐침_질문은_함정이_아니다():
    from chuckchuck.contracts import Claim, ClaimDoc, ClaimQuote
    claims = ClaimDoc(file_name="sleep.pdf", claims=[
        Claim(id="c1", kind="compare", subject_id="root", object_ids=["time"], text="수면 시간보다 중요한 수면의 질",
              evidence=[ClaimQuote(slide_no=1, quote="수면 시간보다 중요한 수면의 질")]),
        Claim(id="c2", kind="compose", subject_id="root", object_ids=["time", "continuity", "regularity"], text="수면의 질 = 시간 × 연속성 × 규칙성",
              evidence=[ClaimQuote(slide_no=4, quote="수면의 질 =")]),
    ])
    q, _ = ask(SLEEP_GRAPH, SLEEP, [("root", True)], [{
        "node_id": "root", "question": "수면 시간도 수면의 질의 요소인데, 수면의 질이 수면 시간보다 중요하다는 건 어떤 뜻인가요?",
        "trap_premise": "수면의 질이 수면 시간보다 중요하다"}], claims=claims)
    got = q["root"]
    assert got.basis.probe is not None and got.trap is False


def test_함정의_골자는_LLM_골자와_상관없이_자료_줄로_전제를_바로잡는다():
    q, _ = ask(INVEST_GRAPH, INVEST, [("behavior", True)], [{
        "node_id": "behavior", "question": "다섯 요인 가운데 어느 것이 가장 통제하기 쉬운가요?",
        "answer_gist": "과잉 매매와 타이밍 실패에 집중해야 해요."}])
    got = q["behavior"]
    assert got.trap is True
    assert got.answer_gist.startswith("질문의 전제와 달리, 자료 ")


def test_주제_자리는_같은_치명도면_가장_무거운_루트다():
    marks = [TriageMark(node_id="light", rank=1, severity=1, source="absolute_boundary", doc_weight=0.3),
             TriageMark(node_id="heavy", rank=2, severity=1, source="core_weight", doc_weight=0.9),
             TriageMark(node_id="leaf", rank=3, severity=2, source="core_weight", doc_weight=0.5)]
    picked, _ = _pick_marks(marks, "1", {"light": 1, "heavy": 1, "leaf": 2}, set())
    assert picked[0].node_id == "heavy"


def test_자료_밖_숫자가_든_각도는_프롬프트에_싣지_않는다():
    """벤치 §9: 각도의 「93.923조원」(자료는 93,923 십억원)이 질문 재료가 됐다."""
    tri = QaTriage(file_name="gap.pdf", total_slides=11, model="scripted", marks=[
        TriageMark(node_id="behavior", rank=1, severity=1, source="core_weight", doc_weight=1.0, angle="93.923조원 손실의 원인"),
        TriageMark(node_id="top25", rank=2, severity=2, source="core_weight", doc_weight=0.5, angle="58% 를 차지하는 근거"),
    ])
    llm = ScriptedLLM({"questions": []})
    build_questions(INVEST_GRAPH, tri, track="5", slidedoc=INVEST, llm=llm)
    assert "93.923" not in llm.prompts[0] and "각도=58% 를 차지하는 근거" in llm.prompts[0]


def test_차트_설명_영문은_인용_후보가_아니다():
    from chuckchuck._evidence import clean_slide_text
    raw = ("실적 추이\n![image](/i)\n- Chart Type: bar chart\n- A red line connects the top of the \"법인세차감순이익\" bar.\n"
           "영업이익은 전년보다 늘었다\n- We propose a new model")
    text = clean_slide_text(raw)
    assert "red line" not in text and "Chart Type" not in text and "We propose a new model" in text


def test_명사구로_끝난_물음은_무엇인가요로_맺는다():
    from chuckchuck.f08_questions import _polite_question
    assert _polite_question("재무 건전성에 미치는 영향은") == "재무 건전성에 미치는 영향은 무엇인가요?"
    assert _polite_question("그 차이의 근거는?") == "그 차이의 근거는 무엇인가요?"
    assert _polite_question("왜 그런가요?") == "왜 그런가요?"


def test_문헌_검색어_프롬프트에_실측_덱_예시가_없다():
    from chuckchuck.f24_papers import QUERY_SYSTEM_PROMPT
    assert not [w for w in ("알림", "notification", "집중", *DECK_WORDS) if w in QUERY_SYSTEM_PROMPT]
    assert "Stothart" not in QUESTION_SYSTEM_PROMPT + PAPER_SYSTEM_ADDENDUM + CITE_SYSTEM_PROMPT


def test_프롬프트_예시를_베낀_문장은_버린다():
    """09-29 재실행: 인용 재작성이 예시 「발표가 말한 재방문 감소도 좌석이 부족한 경우를 포함하나요?」 를 수면 질문에 베꼈다."""
    q, _ = ask(SLEEP_GRAPH, SLEEP, [("regularity", False)], [{
        "node_id": "regularity", "question": "일정한 기상 시간을 말했는데, 발표가 말한 재방문 감소도 좌석이 부족한 경우를 포함하나요?"}])
    assert "fallback_template" in q["regularity"].basis.checks and "재방문" not in q["regularity"].question


def test_개조식_끝과_보예요도_해요체로():
    """09-29 held-out(링글) 골자 「…인식하게 함」·「…중급자 중심임」, 수익률 골자 「0.8%p 차이만 보예요」."""
    assert _polite_statement("자신의 실력을 명확히 인식하게 함") == "자신의 실력을 명확히 인식하게 해요"
    assert _polite_statement("학습 니즈는 중급자 중심임") == "학습 니즈는 중급자 중심이에요"
    assert _polite_statement("0.8%p 차이만 보예요.") == "0.8%p 차이만 보여요."
    assert _polite_statement("세 요소를 모두 포함") == "세 요소를 모두 포함"
    assert _polite_statement("정보예요") == "정보예요"


def test_서지_정보_없는_자료_인용은_질문에_붙이지_않는다():
    """09-29 held-out(링글): 본문 낱말을 인용으로 읽은 「Skills (2019)」 가 「Skills (2019)는 … 근거는 무엇인가요?」 가 됐다."""
    from chuckchuck.f08_questions import _plan_papers
    bare = PaperRef(id="d01", kind="deck", authors=["Skills"], year=2019, slide_no=3, node_ids=["institution"])
    titled = PaperRef(id="d02", kind="deck", authors=["Barber"], year=2000, slide_no=3, title="Trading is hazardous",
                      node_ids=["institution"])
    papers = PaperDoc(file_name="gap.pdf", provider="none", refs=[bare])
    marks = [TriageMark(node_id="institution", rank=1)]
    by_id = {n.id: n for n in INVEST_GRAPH.nodes}
    by_no = {s.slide_no: s for s in INVEST.slides}
    assert _plan_papers(marks, by_id, by_no, papers, "5") == {}
    papers.refs.append(titled)
    assert _plan_papers(marks, by_id, by_no, papers, "5") == {"institution": [titled]}


def test_간접_물음으로_끝난_질문은_설명해_주세요로_맺는다():
    """09-29 held-out(IR 덱): 「…실제 운영 모델과 어떻게 연결되는지」 가 끝맺음 없이 나갔다."""
    from chuckchuck.f08_questions import _polite_question
    assert _polite_question("실제 운영 모델과 어떻게 연결되는지") == "실제 운영 모델과 어떻게 연결되는지 설명해 주세요."
    assert _polite_question("어떤 차이가 있는지?") == "어떤 차이가 있는지 설명해 주세요."
