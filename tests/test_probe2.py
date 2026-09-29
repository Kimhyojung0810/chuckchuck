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


def test_자료가_단_조건이_있으면_그_조건과_장을_댄다():
    gist = P.probe_code_gist(AB, LABELS, SLIDES)
    assert gist.startswith("「완벽하게」라고 단정할 수는 없어요")                 # 첫 절에 열쇠 말(빈칸 칸이 가린다)
    assert "자료 7장에 적었듯 체력에 따라 익히는 속도는 다를 수 있어요." in gist
    assert "누구나 한 달 안에" not in gist                                       # 단정 줄을 되읊지 않는다
    assert restates_line(gist, AB, "") == ""                                     # 이 모범답을 그대로 말하면 판정 가드가 막지 않는다
    assert "습니다" not in gist.replace("「", "").split("」")[-1]


def test_조건이_없으면_없다고_말하고_무엇을_더할지_말한다():
    slides = {n: t for n, t in SLIDES.items() if n != 7}
    gist = P.probe_code_gist(AB, LABELS, slides)
    assert gist.startswith("「완벽하게」라고 단정할 수는 없어요 — 자료 5장에는 이 말이 들어맞는 조건이 아직 없어요.")
    assert "누구에게, 언제, 어떤 조건에서" in gist and gist.endswith("보완할게요.")
    assert restates_line(gist, AB, "") == ""


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
