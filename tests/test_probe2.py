"""
탐침 질문의 **무엇을·어떻게 묻고 무엇을 모범답으로 주는가** — 09-30 WP-P2 회귀 테스트.

standard 실측(8c48180·3d12c92·e2e703b)의 #/qa 대화에서 나온 여섯 가지 + 조정자 추가 두 가지를 **처음 보는 분야의 덱**으로 본다
(새벽 수영반·동네 공방·자전거 수리 교실·온라인 서점). 튜닝·held-out·벤치 덱의 문장·분야는 넣지 않는다 — 규칙이 그 덱 낱말로
맞춘 것이면 여기서 떨어져야 한다.

1. 단정 탐침은 **따져 물을 주장**에만 — 자기 자료에서 본 것(과거 관찰)·늘어놓은 것 안에서 센 것·비용이 붙는 기제·정의는 아니다
2. 단정 탐침의 모범답은 자료가 단 조건을 대거나(있으면), 조건이 없다고 솔직히 말하고 무엇을 더할지 말한다
3. 질문·이유·힌트·골자에 우리 분석 말(「경계·탐침·긴장」)이 새면 정해진 문장으로
4. 한 문장에 두 물음이면 질문의 근거에 묶인 물음 하나만
5. 화면 네 칸은 인용 밖이 해요체
6. 긴장 질문은 언제나 한 꼴
(a) 코드가 답할 수 없다고 본 질문은 다음 후보 뒤로 · (b) 폴백 모범답에 과장 줄·다른 질문이 따지는 줄을 싣지 않는다
"""

import json

import pytest

import chuckchuck.f08_questions as f08
from chuckchuck import _claim_rules as R
from chuckchuck import _probes as P
from chuckchuck import build_questions
from chuckchuck._probe_stance import restates_line
from chuckchuck.contracts import (
    Claim,
    ClaimDoc,
    ClaimQuote,
    ConceptEdge,
    ConceptGraph,
    ConceptNode,
    Probe,
    QaTriage,
    Slide,
    SlideBlock,
    SlideDoc,
    TriageMark,
)
from chuckchuck.f26_claims import build_claims
from chuckchuck.providers.llm_base import LLMProvider


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, questions: list[dict] | None = None):
        self.questions = questions or []
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.prompts.append(user)
        self.systems.append(system)
        if "[TASK] qa-triage" in user:
            return json.dumps({"marks": []})
        return json.dumps({"questions": self.questions}, ensure_ascii=False)


def slide(no: int, text: str) -> Slide:
    return Slide(slide_no=no, title=f"{no}장", blocks=[SlideBlock(category="paragraph", text=text)])


def node(id, label, nos, depth=2, parent="root", weight=0.5, summary=""):
    return ConceptNode(id=id, label=label, slide_nos=nos, summary=summary, weight=weight, depth=depth,
                       parent_id=None if depth == 1 else parent)


def q(no: int, text: str) -> ClaimQuote:
    return ClaimQuote(slide_no=no, quote=text)


# ---------------------------------------------------------------------------
# 덱 — 새벽 수영반 운영 개선 (비교 줄 · 식 · 문제 목록 · 해결 줄 · 과장 · 관찰 · 셈 · 기제 · 유보)
# ---------------------------------------------------------------------------

S = {
    1: "새벽 수영반 운영 개선\n수강생 수보다 중요한 출석 유지율",
    2: "우리가 보는 숫자\n출석 유지율 = 등록 인원 × 출석률 × 재등록률",
    3: "새벽반이 겪는 세 가지 문제\n추운 탈의실\n짧은 강습 시간\n주차 공간 부족",
    4: "개선안\n탈의실에 난방기를 설치해 추운 탈의실 문제를 해소합니다\n강습을 10분 늘려 짧은 강습 시간을 보완합니다",
    5: "기대 효과\n새벽반만 등록하면 누구나 한 달 안에 자유형을 완벽하게 익힐 수 있습니다.",
    6: "지난 학기 돌아보기\n지난 학기 수강생 30명 가운데 중도에 그만둔 사람은 아무도 없었습니다.\n"
       "분석한 네 가지 불만 가운데 강사와 관련된 항목은 하나도 없다\n강습을 받을 때마다 수건 대여료는 반드시 발생합니다.",
    7: "맺음\n다만 체력에 따라 익히는 속도는 다를 수 있습니다.",
}
DECK = SlideDoc(file_name="swim.pdf", total_slides=7, slides=[slide(n, t) for n, t in S.items()])
SLIDES = {n: t for n, t in S.items()}
GRAPH = ConceptGraph(file_name="swim.pdf", total_slides=7, nodes=[
    node("root", "새벽 수영반", [1, 5], depth=1, weight=1.0, summary="새벽 수영반을 오래 다니게 하는 운영 개선"),
    node("keep", "출석 유지율", [1, 2], weight=0.9),
    node("heads", "수강생 수", [1], weight=0.6),
    node("cold", "추운 탈의실", [3, 4], depth=3, parent="keep", weight=0.4),
    node("short", "짧은 강습 시간", [3, 4], depth=3, parent="keep", weight=0.4),
    node("park", "주차 공간 부족", [3], depth=3, parent="keep", weight=0.4),
    node("crawl", "자유형 습득", [5], weight=0.7),
    node("dropout", "중도 포기", [6], depth=3, parent="keep", weight=0.3),
    node("gripe", "불만 항목", [6], depth=3, parent="keep", weight=0.3),
    node("towel", "수건 대여료", [6], depth=3, parent="keep", weight=0.3),
    node("heater", "난방기 설치", [4], depth=3, parent="keep", weight=0.3),
    node("extend", "강습 연장", [4], depth=3, parent="keep", weight=0.3),
], edges=[ConceptEdge(from_id="root", to_id=n, kind="parent") for n in ("keep", "heads", "crawl")])
LABELS = {n.id: n.label for n in GRAPH.nodes}

OVERCLAIM = "새벽반만 등록하면 누구나 한 달 안에 자유형을 완벽하게 익힐 수 있습니다."
FINDING = "지난 학기 수강생 30명 가운데 중도에 그만둔 사람은 아무도 없었습니다."
COUNT = "분석한 네 가지 불만 가운데 강사와 관련된 항목은 하나도 없다"
MECHANISM = "강습을 받을 때마다 수건 대여료는 반드시 발생합니다."

CLAIMS = ClaimDoc(file_name="swim.pdf", claims=[
    Claim(id="c1", kind="compare", subject_id="keep", object_ids=["heads"], evidence=[q(1, "수강생 수보다 중요한 출석 유지율")]),
    Claim(id="c2", kind="compose", subject_id="keep", object_ids=["heads"], evidence=[q(2, "출석 유지율 = 등록 인원 × 출석률 × 재등록률")]),
    Claim(id="c3", kind="absolute", subject_id="crawl", evidence=[q(5, OVERCLAIM)]),
    Claim(id="c4", kind="absolute", subject_id="dropout", evidence=[q(6, FINDING)]),
    Claim(id="c5", kind="absolute", subject_id="gripe", evidence=[q(6, COUNT)]),
    Claim(id="c6", kind="absolute", subject_id="towel", evidence=[q(6, MECHANISM)]),
    Claim(id="c7", kind="compose", subject_id="keep", object_ids=["cold", "short", "park"], evidence=[q(3, "새벽반이 겪는 세 가지 문제")]),
    Claim(id="c8", kind="solve", subject_id="heater", object_ids=["cold"],
          evidence=[q(4, "탈의실에 난방기를 설치해 추운 탈의실 문제를 해소합니다")]),
    Claim(id="c9", kind="solve", subject_id="extend", object_ids=["short"], evidence=[q(4, "강습을 10분 늘려 짧은 강습 시간을 보완합니다")]),
])


# ===========================================================================
# 1. 단정이 따져 물을 주장인가 (`_claim_rules.absolute_kind`)
# ===========================================================================

@pytest.mark.parametrize("line", [
    OVERCLAIM,
    "화분을 창가에 두면 잎은 반드시 더 크게 자랍니다.",
    "필터를 달면 교실의 미세먼지는 완전히 사라집니다.",
    "주 3회 달리기를 하면 체중은 항상 줄어듭니다.",
    "고객은 언제나 가장 싼 상품을 고릅니다.",
    "교칙이 시행되면 지각은 절대 생기지 않습니다.",
    "무조건 아침에 공부하는 학생이 성적이 오릅니다.",
    "작은 동아리는 결코 큰 동아리를 이길 수 없습니다.",
    "예약제를 도입하면 대기 시간은 반드시 0분이 됩니다.",
    "알림은 절대 하루 2번을 넘지 않습니다.",                        # 제품의 약속도 따질 주장이다
    "옛 민담은 항상 해피엔딩으로 끝났다.",                            # 자기 자료 없이 과거로 쓴 일반화
    "이 교재만으로도 시험 문제를 100% 맞힐 수 있습니다.",
    "이 앱으로만 결제하면 수수료는 전혀 붙지 않습니다.",               # 「X만 하면」 이 기제 예외보다 앞선다
    "회원이 되면 추가 요금은 절대 발생하지 않습니다.",                 # 비용이 **안** 붙는다는 건 기제가 아니라 약속
])
def test_따져_물을_단정(line):
    assert R.absolute_kind(line) == "claim" and R.contestable_absolute(line)


@pytest.mark.parametrize("line,kind", [
    (FINDING, "finding"),
    ("관찰 기간 동안 불량품은 하나도 나오지 않았다.", "finding"),
    ("세 차례 실험에서 잎 면적은 예외 없이 늘었다.", "finding"),
    ("파일럿 기간에 민원은 전혀 접수되지 않았습니다.", "finding"),
    ("조사 결과 모든 매장에서 매출이 늘어난 것으로 나타났다.", "finding"),
    ("우리 매장은 개업 이후 항상 흑자였다.", "finding"),
    (COUNT, "count"),
    ("분석한 여섯 요인 중 날씨와 관련된 항목은 하나도 없다.", "count"),
    (MECHANISM, "mechanism"),
    ("택배로 보낼 때마다 포장비와 운송비는 반드시 듭니다.", "mechanism"),
    ("대출을 받으면 이자는 반드시 붙습니다.", "mechanism"),
    ("적자란 항상 지출이 수입보다 많은 상태를 말한다.", "definition"),
])
def test_관찰_셈_기제_정의는_따질_단정이_아니다(line, kind):
    assert R.absolute_kind(line) == kind and not R.contestable_absolute(line)


def test_부정된_단정은_단정이_아니고_표지가_둘이면_하나라도_주장이면_주장():
    assert R.absolute_kind("잠을 오래 잤다고 반드시 개운한 것은 아닙니다.") == ""
    assert R.absolute_kind("지난 3년 동안 매출은 항상 늘었고, 앞으로도 반드시 늘어납니다.") == "claim"


def test_단정_탐침은_따질_주장에만_걸린다():
    probes = P.derive_probes(GRAPH, CLAIMS)
    ab = [p for p in probes if p.kind == "absolute_boundary"]
    assert [p.node_ids[0] for p in ab] == ["crawl"]
    assert ab[0].evidence[0].quote == OVERCLAIM


def test_규칙_주장만으로도_같다_LLM_없이():
    claims = build_claims(GRAPH, DECK, llm="none")
    absolute = {e.quote for c in claims.claims if c.kind == "absolute" for e in c.evidence}
    assert {OVERCLAIM, FINDING, COUNT, MECHANISM} <= absolute          # 주장 그래프는 자료의 말을 그대로 적는다
    ab = [p for p in P.derive_probes(GRAPH, claims, SLIDES) if p.kind == "absolute_boundary"]
    assert [p.evidence[0].quote for p in ab] == [OVERCLAIM]            # 탐침은 따질 주장에만


def test_단정_각도는_우리_말_없이_묻는다():
    ab = next(p for p in P.derive_probes(GRAPH, CLAIMS) if p.kind == "absolute_boundary")
    assert "경계" not in ab.angle and "들어맞지 않는 경우나 조건" in ab.angle


# ===========================================================================
# 2. 단정 탐침의 모범답 — 조건을 대거나, 없다고 말하고 무엇을 더할지
# ===========================================================================

AB = Probe(kind="absolute_boundary", node_ids=["crawl"], claim_ids=["c3"], evidence=[q(5, OVERCLAIM)])


def _bare(text: str) -> str:
    """「」 인용 밖의 글."""
    return "".join(part for i, part in enumerate(text.replace("」", "「").split("「")) if i % 2 == 0)


def test_자료가_단_조건이_있으면_그_조건과_장을_댄다():
    gist = P.probe_code_gist(AB, LABELS, SLIDES)
    assert gist.startswith("「새벽반만 등록하면 누구나") and "」라고 단정할 수는 없어요 — " in gist   # 첫 절 인용 밖에 열쇠 말
    assert "자료 7장에 적었듯 체력에 따라 익히는 속도는 다를 수 있어요." in gist
    assert "누구나" not in _bare(gist) and "습니다" not in _bare(gist)            # 단정 줄은 인용으로만 — 인용 밖은 조건과 해요체
    assert restates_line(gist, AB, "") == ""                                     # 이 모범답을 그대로 말하면 판정 가드가 막지 않는다
    assert len(gist) <= 200


def test_조건이_없으면_없다고_말하고_무엇을_더할지_말한다():
    slides = {n: t for n, t in SLIDES.items() if n != 7}
    gist = P.probe_code_gist(AB, LABELS, slides)
    assert "」라고 단정할 수는 없어요 — 자료 5장에는 이 말이 들어맞는 조건이 아직 없어요." in gist
    assert "누구에게, 언제, 어떤 조건에서" in gist and gist.endswith("보완할게요.")
    assert "누구나" not in _bare(gist) and restates_line(gist, AB, "") == "" and len(gist) <= 200


def test_멀리_떨어진_다른_이야기의_유보는_이_단정의_조건이_아니다():
    slides = {**{n: t for n, t in SLIDES.items() if n != 7},
              12: "행사 안내\n날씨에 따라 행사 일정은 달라질 수 있습니다"}
    gist = P.probe_code_gist(AB, LABELS, slides)
    assert "날씨" not in gist and "조건이 아직 없어요" in gist


def test_조건이_가까운_장이나_같은_낱말이면_받는다():
    near = {5: S[5], 6: "주의\n개인에 따라 효과가 다를 수 있으니 무리하지 마세요"}
    assert "개인에 따라 효과가 다를 수 있어요" in P.probe_code_gist(AB, LABELS, near)
    far_same_word = {5: S[5], 11: "부록\n자유형 속도는 사람마다 다를 수 있습니다"}
    assert "사람마다 다를 수 있어요" in P.probe_code_gist(AB, LABELS, far_same_word)


# ===========================================================================
# 3. 우리 분석 말 · 4. 두 물음 · 6. 긴장 꼴 — 코드
# ===========================================================================

def test_우리_분석_말은_자료가_쓰지_않을_때만_걸린다():
    assert P.jargon_terms("이 주장의 경계는 무엇인가요?", "새벽 수영반 운영 개선") == ["경계"]
    assert P.jargon_terms("두 표현 사이의 긴장은 어떻게 풀리나요?", "") == ["긴장"]
    assert P.jargon_terms("이 probe 의 답은?", "") == ["probe"]
    assert P.jargon_terms("국경의 경계는 어떻게 정했나요?", "국경의 경계를 다시 긋는다") == []
    assert P.jargon_terms("근육 긴장을 푸는 방법은 무엇인가요?", "근육 긴장 완화 체조") == []
    assert P.jargon_terms("「모든」이라고 단정할 수는 없어요", "") == []


@pytest.mark.parametrize("text,head,tail", [
    ("주차 공간 부족을 개선하는 방법은 무엇이며, 추운 탈의실과는 어떤 차이가 있나요?",
     "주차 공간 부족을 개선하는 방법은 무엇인가요?", "추운 탈의실과는 어떤 차이가 있나요?"),
    ("주차 공간 부족이 출석 유지율과 어떻게 연결되며, 주차를 개선할 방법은 무엇인가요?",
     "주차 공간 부족이 출석 유지율과 어떻게 연결되나요?", "주차를 개선할 방법은 무엇인가요?"),
    ("재등록률을 올린다고 볼 근거는 무엇이며, 강사와의 관계는 어떻게 되는지 설명해 주세요.",
     "재등록률을 올린다고 볼 근거는 무엇인가요?", "강사와의 관계는 어떻게 되는지 설명해 주세요."),
    ("강습 시간이 왜 중요하고, 어떻게 늘리나요?", "강습 시간이 왜 중요하나요?", "어떻게 늘리나요?"),
    ("등록 인원이 무엇인지, 그리고 왜 늘었는지 설명해 주세요.", "등록 인원이 무엇인가요?", "왜 늘었는지 설명해 주세요."),
])
def test_한_문장에_두_물음을_가른다(text, head, tail):
    assert P.split_asks(text) == [head, tail]


@pytest.mark.parametrize("text", [
    "어떻게 보면 수강생 수도 출석 유지율의 요소이며, 그렇다면 둘 중 어느 쪽이 더 중요한가요?",
    "무엇보다 중요한 요소이며, 그 까닭은 자료 2장에 있나요?",
    "무엇을 배우느냐에 따라 속도가 달라지며, 이 차이는 왜 생기나요?",
    "누구나 쓸 수 있으며, 대여료는 얼마인가요?",
    "언제나 붐비는 시간대이며, 대기 시간은 어떻게 줄이나요?",
    "출석 유지율이 왜 중요한지 자료 2장을 근거로 설명해 주세요.",
    "「새벽반만 등록하면 누구나 …」라고 했는데, 이 말이 들어맞지 않는 경우도 있나요?",
    "수강생 수도 출석 유지율의 요소인데, 출석 유지율이 수강생 수보다 중요하다는 건 어떤 뜻인가요?",
    "추운 탈의실에는 해결책을 제시했는데, 주차 공간 부족은 어떻게 개선하나요?",
    "등록 인원과 출석률 중 하나만 챙길 수 있다면, 출석 유지율에는 어느 쪽이 더 중요한가요?",
    "학생이 스스로 계획하며, 교사는 어떤 역할을 하나요?",
])
def test_물음_낱말처럼_생긴_관용과_전제_절은_두_물음이_아니다(text):
    assert P.split_asks(text) == [text]


def test_긴장_서술어는_비교_줄에서_여러_낱말_앞말도():
    t = Probe(kind="tension", node_ids=["keep", "heads"], claim_ids=["c1", "c2"],
              evidence=[q(1, "수강생 수보다 중요한 출석 유지율"), q(2, "출석 유지율 = 등록 인원 × 출석률 × 재등록률")])
    assert P.tension_pred(t) == "중요하다"
    assert P.probe_question(t, LABELS, {n.id: n for n in GRAPH.nodes}, CLAIMS) == \
        "수강생 수도 출석 유지율의 요소인데, 출석 유지율이 수강생 수보다 중요하다는 건 어떤 뜻인가요?"
    wide = Probe(kind="tension", node_ids=["keep", "heads"], evidence=[q(1, "수강생 수보다 넓은 개념인 출석 유지율")])
    assert P.tension_pred(wide) == "넓다"
    less = Probe(kind="tension", node_ids=["keep", "heads"], evidence=[q(1, "수강생 수보다 적은 출석 유지율")])
    assert P.tension_pred(less) == ""                    # 작은 쪽 서술어는 템플릿 방향과 어긋난다 — 폴백


# ===========================================================================
# F-08 을 통째로 — 질문 문장·골자·자리 (LLM 은 정해 둔 응답)
# ===========================================================================

def triage(*marks: tuple[str, str]) -> QaTriage:
    return QaTriage(file_name="swim.pdf", total_slides=7, model="scripted", marks=[
        TriageMark(node_id=nid, rank=i, severity=1, trap=False, source=src, doc_weight=1.0)
        for i, (nid, src) in enumerate(marks, 1)])


def build(questions, marks, *, track="10", claims=CLAIMS):
    saved = f08.QA_TRACK_TRAPS
    f08.QA_TRACK_TRAPS = {k: 0 for k in saved}
    try:
        doc = build_questions(GRAPH, triage(*marks), track=track, slidedoc=DECK, claims=claims,
                              llm=ScriptedLLM(questions))
    finally:
        f08.QA_TRACK_TRAPS = saved
    return doc


def item(nid, question, gist="자료 1장의 줄로 설명해요.", why="이 개념을 확인하는 질문이에요.", hint="자료를 다시 보세요."):
    return {"node_id": nid, "question": question, "answer_gist": gist, "why": why, "hint": hint}


def test_우리_분석_말이_샌_탐침_질문은_정해진_문장이다():
    doc = build([item("crawl", "새벽반만 등록하면 자유형을 완벽하게 익힌다는 주장의 경계는 무엇인가요?")],
                [("crawl", "core_weight")])
    q1 = next(x for x in doc.questions if x.node_id == "crawl")
    assert "question_jargon" in q1.basis.checks and "probe_template" in q1.basis.checks
    assert "경계" not in q1.question and q1.question.endswith("이 말이 들어맞지 않는 경우도 있나요?")


def test_두_물음이면_근거에_묶인_물음만_남긴다():
    doc = build([item("park", "주차 공간 부족을 개선하는 방법은 무엇이며, 추운 탈의실과는 어떤 차이가 있나요?")],
                [("park", "core_weight")])
    q1 = next(x for x in doc.questions if x.node_id == "park")
    assert q1.question == "주차 공간 부족을 개선하는 방법은 무엇인가요?"
    assert "two_asks_split" in q1.basis.checks and q1.answer_gist_parts == []


def test_두_물음_가운데_뒤_물음만_근거에_묶이면_뒤_물음():
    doc = build([item("park", "주차 공간 부족이 출석 유지율과 어떻게 연결되며, 주차를 개선할 방법은 무엇인가요?")],
                [("park", "core_weight")])
    q1 = next(x for x in doc.questions if x.node_id == "park")
    assert q1.question == "주차를 개선할 방법은 무엇인가요?" and "two_asks_split" in q1.basis.checks


def test_두_물음이_다_근거에서_벗어나면_탐침_템플릿():
    doc = build([item("park", "주차 공간 부족이 출석 유지율과 어떻게 연결되며, 강사 교육은 어떻게 하나요?")],
                [("park", "core_weight")])
    q1 = next(x for x in doc.questions if x.node_id == "park")
    assert "two_asks_dropped" in q1.basis.checks and "probe_template" in q1.basis.checks
    assert q1.question == "추운 탈의실에는 해결책을 제시했는데, 주차 공간 부족은 어떻게 개선하나요?"


def test_긴장_질문은_탐침_꼴을_통과한_LLM_문장이어도_한_꼴이다():
    doc = build([item("keep", "수강생 수보다 중요한 출석 유지율이라는 표현과 출석 유지율 = 등록 인원 × 출석률 × 재등록률이라는 "
                              "공식이 함께 성립하는 의미는 무엇인가요?")],
                [("keep", "core_weight")])
    q1 = next(x for x in doc.questions if x.node_id == "keep")
    assert q1.question == "수강생 수도 출석 유지율의 요소인데, 출석 유지율이 수강생 수보다 중요하다는 건 어떤 뜻인가요?"
    assert "tension_clean_form" in q1.basis.checks


def test_폴백_모범답은_과장_줄과_따지는_줄을_싣지_않는다():
    # 근거 장의 비교 줄(긴장 탐침이 따짐)·과장 줄은 빼고 남는 자료 줄로만 짓는다 — 제목만 남으면 답이 아니다(""）.
    by_no = {s.slide_no: s for s in DECK.slides}
    root = next(n for n in GRAPH.nodes if n.id == "root")
    challenged = P.challenged_lines(P.derive_probes(GRAPH, CLAIMS, SLIDES))
    assert "수강생 수보다 중요한 출석 유지율" in challenged and OVERCLAIM in challenged
    ok = lambda line: P.usable_answer_line(line, challenged)                      # noqa: E731
    assert f08._evidence_gist(root, "새벽 수영반을 어떻게 설명했나요?", [1], by_no, usable=ok) == ""
    effect = node("effect", "기대 효과", [5, 6])
    gist = f08._evidence_gist(effect, "기대 효과를 어떻게 설명했나요?", [5, 6], by_no, usable=ok)
    assert "완벽하게" not in gist and gist.startswith("자료는 이렇게 말해요 — ")
    # 따지는 줄이 없으면(탐침을 안 쓴 경로) 예전처럼 자료 줄 그대로다
    assert "수강생 수보다 중요한" in f08._evidence_gist(root, "새벽 수영반을 어떻게 설명했나요?", [1], by_no)


def test_답할_수_없는_질문의_폴백은_묻는_것과_골자가_맞는다():
    doc = build([item("root", "새벽 수영반의 신경학적 메커니즘은 무엇인가요?")], [("root", "core_weight")], track="1")
    q1 = doc.questions[0]
    assert {"question_unanswerable", "fallback_template", "unanswerable_fallback"} <= set(q1.basis.checks)
    assert q1.question == "새벽 수영반을 자료 1장에서 어떻게 설명했나요?"
    assert "수강생 수보다 중요한" not in q1.answer_gist and "완벽하게" not in q1.answer_gist
    assert q1.why == "자료 1장에서 다룬 내용이라, 자료가 말한 대로 설명할 수 있는지 확인하는 질문이에요"


def test_답할_수_없는_폴백은_여유_후보가_있으면_뒤로_밀린다():
    # 5분 트랙은 상한 3 + 여유 2 — 답할 수 없는 질문 자리는 다음 후보가 받는다
    qs = [item("root", "새벽 수영반의 신경학적 메커니즘은 무엇인가요?"),
          item("keep", "출석 유지율은 어떻게 계산하나요?", gist="등록 인원과 출석률, 재등록률을 곱해요."),
          item("cold", "추운 탈의실은 어떻게 해결했나요?", gist="탈의실에 난방기를 설치해 해소해요."),
          item("short", "짧은 강습 시간은 어떻게 보완했나요?", gist="강습을 10분 늘려 보완해요."),
          item("heads", "수강생 수는 출석 유지율에서 어떤 역할인가요?", gist="등록 인원으로 출석 유지율의 한 요소예요.")]
    doc = build(qs, [("root", "core_weight"), ("keep", "core_weight"), ("cold", "core_weight"), ("short", "core_weight"),
                     ("heads", "core_weight")], track="5", claims=None)
    ids = [x.node_id for x in doc.questions]
    assert "root" not in ids and len(ids) == 3 and "root" in doc.deferred_node_ids
    filled = [x for x in doc.questions if "filled_for_unanswerable" in x.basis.checks]
    assert len(filled) == 1


def test_여유_후보가_없으면_폴백_문장_그대로_남는다():
    doc = build([item("root", "새벽 수영반의 신경학적 메커니즘은 무엇인가요?")], [("root", "core_weight")], track="1")
    assert [x.node_id for x in doc.questions] == ["root"]
    assert "unanswerable_fallback" in doc.questions[0].basis.checks
    assert not any("filled_for_unanswerable" in x.basis.checks for x in doc.questions)


def test_화면_네_칸은_인용_밖이_해요체다():
    doc = build([item("dropout", "중도 포기가 있었나요?", gist="지난 학기에 그만둔 사람은 아무도 없었습니다.",
                      why="중도 포기를 확인하는 질문입니다.", hint="6장을 보십시오.")],
                [("dropout", "core_weight")])
    q1 = next(x for x in doc.questions if x.node_id == "dropout")
    for text in (q1.question, q1.answer_gist, q1.why, q1.hint):
        outside = "".join(part for i, part in enumerate(text.replace("」", "「").split("「")) if i % 2 == 0)
        assert "습니다" not in outside and "입니다" not in outside, text


def test_자료_줄_골자도_해요체로_끝내고_근거_인용은_원문_그대로():
    doc = build([item("dropout", "지난 학기 중도 포기는 어땠나요?", gist="")], [("dropout", "core_weight")])
    q1 = next(x for x in doc.questions if x.node_id == "dropout")
    assert q1.answer_gist.startswith("자료는 이렇게 말해요 — ") and "없었어요" in q1.answer_gist
    assert "습니다" not in q1.answer_gist


# ===========================================================================
# 하네스 잣대 — 회귀 사례의 「두 물음」 검사는 대상 코드가 아니라 하네스 것이다 (같은 버그를 못 보지 않게)
# ===========================================================================

@pytest.mark.parametrize("question,two", [
    ("주차 공간 부족을 개선하는 방법은 무엇이며, 추운 탈의실과는 어떤 차이가 있나요?", True),
    ("재등록률을 올린다고 볼 근거는 무엇이며, 강사와의 관계는 어떻게 되는지 설명해 주세요.", True),
    ("주차 공간 부족을 개선하는 방법은 무엇인가요?", False),
    ("어떻게 보면 수강생 수도 출석 유지율의 요소이며, 그렇다면 둘 중 어느 쪽이 더 중요한가요?", False),
    ("「새벽반만 등록하면 누구나 …」라고 했는데, 이 말이 들어맞지 않는 경우도 있나요?", False),
])
def test_하네스_두_물음_잣대(question, two):
    from labs.qa_verify import regress as RG
    assert RG.two_asks(question) is two


# ===========================================================================
# 녹음 감사 REC-17 — 모순 질문은 답을 요구하는 꼴로, 인용은 이음 말 없이
# ===========================================================================

def _contra():
    from chuckchuck.contracts import AlignmentItem
    return AlignmentItem(node_id="keep", verdict="contradiction", evidence="그리고 출석 유지율이 구십 퍼센트로 올랐어요.",
                         deck_quote="출석 유지율이 72%로 올랐습니다", deck_slide_no=2, decided_by="code")


@pytest.mark.parametrize("question,ok", [
    ("발표에서 말한 출석 유지율이 자료 2장과 다른가요?", False),                          # 예/아니요로 닫힌다
    ("발표에서 말한 출석 유지율이 자료 2장의 수치와 다른데, 어느 쪽이 맞나요?", True),
    ("발표에서 한 말은 자료 2장과 어떻게 다른가요?", True),
    ("자료 2장과 어떤 차이가 있나요?", True),
    ("자료 2장과 다르게 말한 까닭은 무엇인가요?", False),                              # 바로잡기가 아니라 변명
])
def test_모순_질문은_답을_요구하는_꼴만_LLM_문장으로_둔다(question, ok):
    assert f08._contra_asked(question, _contra()) is ok


def test_모순_인용은_이음_말로_시작하지_않는다():
    said = f08._said_clause(_contra().evidence, numeric=True)
    assert said.startswith("출석 유지율이 구십 퍼센트로") and not said.startswith("그리고")
    assert "“그리고" not in f08._contra_question(_contra(), GRAPH.nodes[1])


# ===========================================================================
# 녹음 감사 REC-20 — 자료가 안 매긴 최상급을 전제로 까닭을 묻거나, 방법 줄 없이 방법·조건을 묻는 질문
# ===========================================================================

RAIN = {
    1: "빗물 저금통 설치 제안\n지붕 면적보다 중요한 것은 저장 용량입니다",
    2: "모으는 양 계산\n모으는 빗물 =\n지붕 면적\n×\n강수량\n×\n집수 효율",
    3: "시범 설치 결과\n저금통을 단 집 12곳의 수돗물 사용량이 평균 18% 줄었습니다.",
    4: "남은 과제\n여름철 모기가 가장 큰 불만입니다.",
}


def rain_idx(extra: dict[int, str] | None = None):
    from chuckchuck import _grounding as G
    slides = {**RAIN, **(extra or {})}
    deck = {n: slide(n, t) for n, t in slides.items()}
    nodes = [node(f"r{i}", lab, [1, 2, 3, 4]) for i, lab in enumerate(["빗물 저금통", "지붕 면적", "강수량", "저장 용량", "수돗물 사용량"])]
    return G, G.build_index(deck, nodes)


def test_자료가_안_매긴_최상급을_전제로_까닭을_물으면_전제_문제다():
    G, idx = rain_idx()
    assert G.question_premise_problems("모으는 빗물 식에서 강수량이 세 요소 중 가장 중요한 변수로 설정된 이유는 무엇인가요?", idx) \
        == ["superlative"]
    assert G.question_premise_problems("여름철 모기가 가장 큰 불만인 이유는 무엇인가요?", idx) == []     # 자료가 한 말
    assert G.question_premise_problems("세 요소 중 무엇이 가장 중요한가요?", idx) == []                   # 순위를 묻는 것


def test_방법_조건을_이름으로_묻는_질문은_방법_줄이_있어야_한다():
    G, idx = rain_idx()
    for q in ("시범 설치 집의 선정 기준은 무엇인가요?", "수돗물 사용량의 측정 방법과 조건은 무엇인가요?"):
        assert G.asks_method(q) and not G.method_supported(q, [3], idx), q          # 수치 줄(18%)만으로는 답이 안 된다
    _, idx2 = rain_idx({5: "측정 방법\n수도 계량기로 매주 기록했습니다\n아파트 12곳을 대상으로 모집했습니다"})
    assert G.method_supported("수돗물 사용량의 측정 방법과 조건은 무엇인가요?", [3], idx2)
    assert G.method_supported("시범 설치 집의 선정 기준은 무엇인가요?", [3], idx2)


def test_실제와_같은지_묻는_질문은_자료가_실제와_같다고_적었을_때만():
    G, idx = rain_idx()
    q = "시범 결과가 실제 가정 환경과 일치하는지 설명해 주세요."
    assert G.asks_method(q) and not G.method_supported(q, [3], idx)
    _, idx2 = rain_idx({5: "설치 조건\n실제 가정과 같은 크기의 지붕에 달았습니다"})
    assert G.method_supported(q, [3], idx2)


def test_계산_물음은_근거_장의_식이_답이다():
    G, idx = rain_idx()
    assert G.method_supported("모으는 빗물은 어떻게 계산하나요?", [2], idx)
    assert not G.method_supported("수돗물 사용량은 어떻게 측정했나요?", [2], idx)


def test_F08_은_최상급_전제_질문과_방법_줄_없는_조건_질문을_폴백으로_바꾼다():
    deck = SlideDoc(file_name="rain.pdf", total_slides=4, slides=[slide(n, t) for n, t in RAIN.items()])
    graph = ConceptGraph(file_name="rain.pdf", total_slides=4, nodes=[
        node("root", "빗물 저금통", [1, 3], depth=1, weight=1.0), node("rain", "강수량", [2]), node("saving", "수돗물 사용량", [3])])
    qs = [item("rain", "모으는 빗물 식에서 강수량이 세 요소 중 가장 중요한 변수로 설정된 이유는 무엇인가요?"),
          item("saving", "수돗물 사용량의 측정 방법과 조건은 무엇인가요?")]
    saved = f08.QA_TRACK_TRAPS
    f08.QA_TRACK_TRAPS = {k: 0 for k in saved}
    try:
        doc = build_questions(graph, QaTriage(file_name="rain.pdf", total_slides=4, model="scripted", marks=[
            TriageMark(node_id=n, rank=i, severity=1, source="core_weight", doc_weight=1.0) for i, n in enumerate(("rain", "saving"), 1)]),
            track="10", slidedoc=deck, llm=ScriptedLLM(qs))
    finally:
        f08.QA_TRACK_TRAPS = saved
    by = {x.node_id: x for x in doc.questions}
    assert {"question_premise_conflict", "premise_superlative", "fallback_template"} <= set(by["rain"].basis.checks)
    assert {"method_unsupported", "fallback_template"} <= set(by["saving"].basis.checks)
    assert "가장 중요한" not in by["rain"].question and "측정 방법" not in by["saving"].question
