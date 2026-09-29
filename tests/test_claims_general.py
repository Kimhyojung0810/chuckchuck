"""
F-26 주장 · 탐침이 **아무 발표에나** 같은 잣대로 서는지 — 여러 분야의 작은 합성 장으로 본다 (2026-09-29 일반화 벤치 후속).

규칙마다 벤치 덱과 **다른 분야**의 예를 둔다 (카페 운영·물류·온라인 강의·사내 개발팀·지역 도서관·마케팅).
벤치에서 본 한 덱 때문에 규칙을 고쳤다면, 여기 다른 분야에서도 같은 규칙이 맞아야 일반 규칙이다.

- 인용은 원문 **한 줄**이어야 한다 — 여러 글 상자를 이은 인용은 줄로 나눠 받치는 줄 하나만 남긴다
- 인용이 주장을 **받쳐야** 한다 — absolute 는 부정되지 않은 단정 표지, compare 는 비교 표지 + 두 이름,
  compose 는 식이나 목록, cause 는 인과 말투 + 두 이름. 물음 줄·가설 줄은 주장이 아니다
- has_support 는 인용 줄과 그 옆 줄만 본다
- unsolved 는 문제 목록에서만, 해결 장이 있을 때만 / unsupported_cause 의 목적어는 인용에 나온 것만
- sibling_priority 는 자료가 「함께 필요하다」 고 한 요소에 묻지 않고, 덱에 하나만
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from chuckchuck import _claim_rules as R
from chuckchuck._probes import derive_probes, probe_question
from chuckchuck.contracts import Claim, ClaimDoc, ClaimQuote, ConceptGraph, ConceptNode, Slide, SlideBlock, SlideDoc
from chuckchuck.f26_claims import (
    SYSTEM_PROMPT,
    build_claims,
    line_support,
    locate_quote,
    resolve_label,
    rule_cause,
    rule_compare,
    rule_list_compose,
    rule_solve_rows,
    validate_claims,
    verify_quote,
)
from chuckchuck.providers.llm_base import LLMProvider


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, claims: list[dict]):
        self.claims = claims

    def complete(self, **_):
        return json.dumps({"claims": self.claims}, ensure_ascii=False)


def deck(*slides: tuple[int, str]) -> SlideDoc:
    return SlideDoc(file_name="x.pptx", total_slides=len(slides),
                    slides=[Slide(slide_no=no, title=text.split("\n")[0],
                                  blocks=[SlideBlock(category="paragraph", text=t) for t in text.split("\n")])
                            for no, text in slides])


def graph(*nodes: tuple) -> ConceptGraph:
    """(id, label, slides, parent, weight)"""
    out = []
    for nid, label, slides, *rest in nodes:
        parent = rest[0] if rest else None
        weight = rest[1] if len(rest) > 1 else 0.5
        out.append(ConceptNode(id=nid, label=label, slide_nos=list(slides), parent_id=parent, weight=weight,
                               depth=1 if parent is None else 2))
    return ConceptGraph(file_name="x.pptx", total_slides=9, nodes=out)


def kinds(doc) -> set[tuple]:
    return {(c.kind, c.subject_id, tuple(c.object_ids)) for c in doc.claims}


# ---------------------------------------------------------------------------
# 말투 규칙 (_claim_rules)
# ---------------------------------------------------------------------------

def test_단정_표지는_부정되면_유보이고_부정과_짝인_표지는_단정이다():
    assert R.absolute_marker("이 방식이면 대기 시간은 반드시 0분이 됩니다.") == "반드시"
    assert R.absolute_marker("새 포장재는 파손을 완전히 막을 수 있습니다.") == "완전히"
    assert R.absolute_marker("우리 강의는 항상 20분 안에 끝납니다.") == "항상"
    # 부정과 짝을 이루는 표지 — 「절대 … 않는다」「하나도 없었다」 는 단정이다
    assert R.absolute_marker("상담원은 절대 두 번 이상 전화하지 않습니다.") == "절대"
    assert R.absolute_marker("지연 사고는 한 건도, 하나도 없었다.") == "하나도"
    # 부정된 단정은 유보다
    assert R.absolute_marker("배송이 빠르다고 반드시 만족하는 것은 아닙니다.") == ""
    assert R.absolute_marker("재고 손실을 완전히 없앨 수는 없지만 줄일 수 있습니다.") == ""
    assert R.absolute_marker("한 가지 채널만으로 완전한 홍보가 어렵습니다.") == ""
    # 표지 없는 줄
    assert R.absolute_marker("대부분의 고객은 첫 주에 재방문 여부를 정하는 경향이 있습니다.") == ""
    assert R.absolute_marker("재고가 늘어납니다.") == ""          # 「늘」 은 낱말 안의 글자다


def test_물음_줄과_가설_줄은_주장이_아니다():
    for line in ("고객은 왜 다시 오는가", "몇 명이 강의를 끝까지 듣는가", "배송비는 줄일 수 있을까?",
                 "가설: 조명이 밝을수록 체류 시간이 길어진다.", "연구 질문: 알림 빈도가 이탈에 영향을 주는가"):
        assert R.is_question(line), line
    for line in ("재방문율이 매출을 좌우합니다.", "1인 가구 증가"):
        assert not R.is_question(line), line


def test_목록_제목은_개수나_문제_명사로_열고_해결_문장은_제목이_아니다():
    assert R.is_list_heading("창고 운영의 세 가지 문제")
    assert R.is_list_heading("수강생이 이탈하는 이유")
    assert R.is_list_heading("문제는 네 가지입니다.")
    assert not R.is_list_heading("해결책은 앞 장의 세 가지 문제와 직접 연결됩니다.")
    assert not R.is_list_heading("품질 점수 = 속도 × 정확도")
    assert R.is_problem_head("수강생이 이탈하는 이유") and not R.is_problem_head("좋은 강의의 네 가지 조건")


def test_같은_개념의_두_이름은_수식어만_다르다():
    assert R.same_concept("충분한 재고", "재고 부족")
    assert R.same_concept("응답 속도 저하", "응답 속도")
    assert not R.same_concept("재고 부족", "인력 부족")
    assert not R.same_concept("배송비", "배송 속도")


def test_이름_대조는_조사를_받고_변별_낱말만_본다():
    assert R.mentioned("배송비", "건당 배송비를 낮춥니다")
    assert R.mentioned("사전 점검", "점검 체계를 먼저 세웁니다")                # 변별 낱말 절반
    assert not R.mentioned("피해 보상 지연", "피해 규모는 지역마다 다릅니다")   # 셋 중 하나뿐
    # 맞은편 이름과 겹치는 낱말은 빼고 본다 — 「강의」 는 양쪽에 다 있다
    assert not R.mentioned("강의 길이", "강의 만족도보다 중요한 수료율", exclude="강의 만족도")


# ---------------------------------------------------------------------------
# 인용 대조 — 줄 단위
# ---------------------------------------------------------------------------

CAFE = deck(
    (1, "동네 카페 운영 보고\n가격보다 중요한 단골 관계\n2026 창업 동아리"),
    (2, "매출 구조\n매출 = 방문객 × 객단가 × 재방문율\n얼마나 오는가\n다시 오는가"),
    (3, "매장이 겪는 세 가지 문제\n① 긴 대기 시간\n② 원두 재고 부족\n③ 저녁 시간 공실\n세 문제가 모두 이익을 깎습니다."),
    (4, "개선안\n모바일 선주문 — 주문을 미리 받아 대기 시간을 줄입니다.\n원두 정기 발주 — 매주 같은 양을 받아 재고 부족을 막습니다."),
    (5, "기대 효과\n선주문을 도입하면 대기 시간은 반드시 0분이 됩니다.\n효과는 매장마다 다를 수 있어 한 곳에서 먼저 시험합니다."),
    (6, "손님이 줄어든 이유\n근처 대형 카페가 문을 열어서 평일 손님이 줄었습니다.\n점심 손님 수는 지난달보다 18% 적었습니다."),
)
CAFE_G = graph(
    ("cafe", "카페 운영", [1, 2, 3], None, 1.0),
    ("regular", "단골 관계", [1, 2], "cafe", 0.9),
    ("price", "가격", [1], "cafe", 0.4),
    ("revenue", "매출", [2], "cafe", 0.8),
    ("visitors", "방문객", [2], "revenue", 0.5),
    ("ticket", "객단가", [2], "revenue", 0.5),
    ("revisit", "재방문율", [2], "revenue", 0.6),
    ("wait", "대기 시간", [3, 4, 5], "cafe", 0.7),
    ("stock", "원두 재고 부족", [3, 4], "cafe", 0.6),
    ("empty", "저녁 공실", [3], "cafe", 0.5),
    ("preorder", "모바일 선주문", [4, 5], "wait", 0.5),
    ("supply", "원두 정기 발주", [4], "stock", 0.4),
    ("rival", "대형 카페", [6], "cafe", 0.3),
    ("lunch", "평일 손님", [6], "cafe", 0.3),
)


def test_한_줄_안의_인용은_그대로_여러_줄을_이으면_줄로_나눈다():
    raw3 = CAFE.slides[2].raw_text
    assert verify_quote("① 긴 대기 시간", raw3) == "① 긴 대기 시간"
    glued = "매장이 겪는 세 가지 문제 ① 긴 대기 시간 ② 원두 재고 부족"
    assert verify_quote(glued, raw3) == ""                         # 한 줄이 아니다
    hits = locate_quote(glued, raw3)
    assert [h.quote for h in hits] == ["매장이 겪는 세 가지 문제", "① 긴 대기 시간", "② 원두 재고 부족"]
    assert all(h.glued for h in hits)


def test_이어_붙인_인용은_주장을_받치는_한_줄만_남는다():
    doc = build_claims(CAFE_G, CAFE, llm=ScriptedLLM([
        {"slide_no": 5, "kind": "absolute", "subject_id": "preorder",
         "quote": "기대 효과 선주문을 도입하면 대기 시간은 반드시 0분이 됩니다. 효과는 매장마다 다를 수 있어 한 곳에서 먼저 시험합니다."},
    ]))
    absolute = [c for c in doc.claims if c.kind == "absolute"]
    assert len(absolute) == 1
    assert [q.quote for q in absolute[0].evidence] == ["선주문을 도입하면 대기 시간은 반드시 0분이 됩니다."]


# ---------------------------------------------------------------------------
# 받침 검사
# ---------------------------------------------------------------------------

def test_단정_표지_없는_줄_물음_줄_유보_줄은_absolute_가_아니다():
    doc = build_claims(CAFE_G, CAFE, llm=ScriptedLLM([
        {"slide_no": 2, "kind": "absolute", "subject_id": "revisit", "quote": "다시 오는가"},
        {"slide_no": 1, "kind": "absolute", "subject_id": "cafe", "quote": "2026 창업 동아리"},
        {"slide_no": 5, "kind": "absolute", "subject_id": "wait", "quote": "효과는 매장마다 다를 수 있어 한 곳에서 먼저 시험합니다."},
        {"slide_no": 5, "kind": "absolute", "subject_id": "preorder", "quote": "선주문을 도입하면 대기 시간은 반드시 0분이 됩니다."},
    ]))
    absolute = [c for c in doc.claims if c.kind == "absolute"]
    assert [q.quote for c in absolute for q in c.evidence] == ["선주문을 도입하면 대기 시간은 반드시 0분이 됩니다."]


def test_compare_는_비교_표지와_두_이름이_그_줄에_있어야_한다():
    doc = build_claims(CAFE_G, CAFE, llm=ScriptedLLM([
        # 인용에 두 개념이 하나도 안 나온다 — 버린다
        {"slide_no": 1, "kind": "compare", "subject_id": "revenue", "object_ids": ["wait"], "quote": "가격보다 중요한 단골 관계"},
        # 비교 표지가 없다 — 버린다
        {"slide_no": 2, "kind": "compare", "subject_id": "revisit", "object_ids": ["visitors"], "quote": "다시 오는가"},
    ]))
    assert ("compare", "revenue", ("wait",)) not in kinds(doc)
    assert ("compare", "regular", ("price",)) in kinds(doc)           # 규칙 추출 — 「가격보다 중요한 단골 관계」


def test_compose_는_식이나_목록이어야_하고_제목_한_줄로는_안_된다():
    lonely = deck((1, "도서관 이용을 늘리는 네 가지 조건\n우리 동네 도서관 이야기"),
                  (2, "대출 권수 = 회원 수 × 방문 빈도 × 1회 대출"))
    g = graph(("lib", "도서관 이용", [1], None, 1.0), ("members", "회원 수", [2], "lib"),
              ("freq", "방문 빈도", [2], "lib"), ("loans", "대출 권수", [2], "lib"), ("hours", "개관 시간", [1], "lib"))
    doc = build_claims(g, lonely, llm=ScriptedLLM([
        {"slide_no": 1, "kind": "compose", "subject_id": "lib", "object_ids": ["members", "hours"],
         "quote": "도서관 이용을 늘리는 네 가지 조건"},
    ]))
    assert not any(c.kind == "compose" and c.subject_id == "lib" for c in doc.claims)   # 항목이 없는 제목
    assert ("compose", "loans", ("members", "freq")) in kinds(doc)                        # 식은 규칙이 잡는다


def test_목록_제목_밑_항목은_문제_목록_compose_가_된다():
    got = rule_list_compose(CAFE_G, CAFE)
    assert [(c.subject_id, c.object_ids, c.evidence[0].quote) for c in got] == [
        ("cafe", ["wait", "stock", "empty"], "매장이 겪는 세 가지 문제")]   # 「저녁 시간 공실」 ∋ 「저녁」「공실」
    # 소개 문장 하나를 건너뛰고 표 첫 칸을 읽는다
    course = deck((1, "수강생이 이탈하는 이유\n흔한 이유는 이렇습니다.\n| 이유 | 설명 |\n| 긴 강의 길이 | 한 편이 40분 |\n| 과제 부담 | 매주 보고서 |"))
    g = graph(("drop", "수강생 이탈", [1], None), ("len", "강의 길이", [1], "drop"), ("hw", "과제 부담", [1], "drop"))
    got = rule_list_compose(g, course)
    assert [(c.subject_id, c.object_ids) for c in got] == [("drop", ["len", "hw"])]


def test_인과는_인과_말투와_두_이름이_있어야_하고_말투가_인과면_kind_를_고친다():
    doc = build_claims(CAFE_G, CAFE, llm=ScriptedLLM([
        # compare 로 적었지만 비교 표지가 없고 인과 말투다 — cause 로 (줄에 나온 순서: 대형 카페 → 평일 손님)
        {"slide_no": 6, "kind": "compare", "subject_id": "lunch", "object_ids": ["rival"],
         "quote": "근처 대형 카페가 문을 열어서 평일 손님이 줄었습니다."},
    ]))
    assert ("cause", "rival", ("lunch",)) in kinds(doc)
    assert not any(c.kind == "compare" and c.subject_id == "lunch" for c in doc.claims)


def test_규칙_인과는_연결_어미와_조사로_원인과_결과를_가른다():
    logistics = deck((1, "배송 지연\n포장 인력이 부족해서 출고 지연이 늘어납니다."),
                     (2, "창고 이전\n야간 하역이 새벽 배송 비율을 높였습니다."))
    g = graph(("root", "물류 운영", [1, 2], None), ("staff", "포장 인력", [1], "root"), ("delay", "출고 지연", [1], "root"),
              ("night", "야간 하역", [2], "root"), ("dawn", "새벽 배송 비율", [2], "root"))
    got = {(c.subject_id, tuple(c.object_ids)) for c in rule_cause(g, logistics)}
    assert got == {("staff", ("delay",)), ("night", ("dawn",))}


# ---------------------------------------------------------------------------
# has_support — 인용 줄과 옆 줄만
# ---------------------------------------------------------------------------

def test_근거는_인용_줄과_옆_줄만_보고_옆_문장의_숫자는_남의_근거다():
    raw = "\n".join([
        "사용자 문제",
        "알림이 잦을수록 앱 삭제가 늘어납니다.",
        "하루 평균 40분을 앱에서 보냅니다.",           # 옆 줄이지만 독립된 문장 — 이 인과의 근거가 아니다
    ])
    assert not line_support(raw, "알림이 잦을수록 앱 삭제가 늘어납니다.")
    cited = "결과\n알림을 묶어 보내면 삭제율이 줄었습니다.\n(Kim 외, 2024)"
    assert line_support(cited, "알림을 묶어 보내면 삭제율이 줄었습니다.")
    callout = "결과\n묶음 발송 뒤 삭제율이 줄었습니다.\n삭제율 12% 감소"
    assert line_support(callout, "묶음 발송 뒤 삭제율이 줄었습니다.")
    survey = "설문\n가격보다 중요한 친절\n1만 원 미만\n1만–2만 원\n2만 원 이상"
    assert not line_support(survey, "가격보다 중요한 친절")          # 설문 보기는 근거가 아니다


def test_다른_장의_수치_줄이_두_개념을_다_부르면_인과의_근거다():
    exp = deck((1, "탐구 내용\n물 주기를 늘리면 새싹 키가 커진다고 봅니다."),
               (2, "결과\n물 주기를 늘린 조건의 새싹 키가 32% 컸습니다."))
    g = graph(("root", "새싹 재배", [1, 2], None), ("water", "물 주기", [1, 2], "root"), ("height", "새싹 키", [1, 2], "root"))
    claims, _ = validate_claims([{"slide_no": 1, "kind": "cause", "subject_id": "water", "object_ids": ["height"],
                                  "quote": "물 주기를 늘리면 새싹 키가 커진다고 봅니다."}], g, exp)
    assert claims and claims[0].has_support is True


# ---------------------------------------------------------------------------
# 개념 이름 풀기
# ---------------------------------------------------------------------------

def test_구절의_변별_낱말이_절반_이상_든_이름을_고른다():
    nodes = CAFE_G.nodes
    assert resolve_label("단골 손님 관계", nodes).id == "regular"
    assert resolve_label("원두 재고", nodes).id == "stock"
    assert resolve_label("임대료", nodes) is None


def test_비교_규칙은_서술어_목록이_아니라_꼴로_받는다():
    dev = deck((1, "개발 원칙\n속도보다 필요한 정확성"),
               (2, "리뷰\n정확성은 속도보다 앞선다고 봅니다."),
               (3, "지표\n작년 대비 배포 횟수가 두 배입니다."))
    g = graph(("acc", "정확성", [1, 2], None), ("speed", "속도", [1, 2], None), ("deploy", "배포 횟수", [3], None),
              ("last", "작년", [3], None))
    got = {(c.subject_id, tuple(c.object_ids), c.evidence[0].slide_no) for c in rule_compare(g, dev)}
    assert ("acc", ("speed",), 1) in got and ("acc", ("speed",), 2) in got
    assert ("deploy", ("last",), 3) in got


# ---------------------------------------------------------------------------
# 탐침 — unsolved · unsupported_cause · sibling_priority
# ---------------------------------------------------------------------------

def q(no: int, text: str) -> ClaimQuote:
    return ClaimQuote(slide_no=no, quote=text)


def test_문제_목록에서_해결이_빠진_문제만_unsolved():
    probes = derive_probes(CAFE_G, build_claims(CAFE_G, CAFE, llm=ScriptedLLM([
        {"slide_no": 4, "kind": "solve", "subject_id": "preorder", "object_ids": ["wait"],
         "quote": "모바일 선주문 — 주문을 미리 받아 대기 시간을 줄입니다."},
        {"slide_no": 4, "kind": "solve", "subject_id": "supply", "object_ids": ["stock"],
         "quote": "원두 정기 발주 — 매주 같은 양을 받아 재고 부족을 막습니다."},
        {"slide_no": 3, "kind": "compose", "subject_id": "cafe", "object_ids": ["wait", "stock", "empty"],
         "quote": "매장이 겪는 세 가지 문제"},
    ])))
    unsolved = [p for p in probes if p.kind == "unsolved"]
    assert [p.node_ids[0] for p in unsolved] == ["empty"]


def test_식은_문제_목록이_아니고_해결_장이_없으면_unsolved_가_없다():
    g = graph(("q", "서비스 품질", [1], None), ("fast", "응답 속도", [1, 2], "q"), ("kind", "친절", [1], "q"),
              ("acc", "정확도", [1], "q"), ("bot", "자동 응답", [2], "fast"))
    formula = ClaimDoc(file_name="x", claims=[
        Claim(id="c01", kind="compose", subject_id="q", object_ids=["fast", "kind", "acc"],
              evidence=[q(1, "서비스 품질 = 응답 속도 × 친절 × 정확도")]),
        Claim(id="c02", kind="solve", subject_id="bot", object_ids=["fast"], evidence=[q(2, "자동 응답으로 응답 속도를 줄입니다.")]),
    ])
    assert not [p for p in derive_probes(g, formula) if p.kind == "unsolved"]
    problems = ClaimDoc(file_name="x", claims=[
        Claim(id="c01", kind="compose", subject_id="q", object_ids=["fast", "kind", "acc"],
              evidence=[q(1, "고객이 떠나는 세 가지 이유")]),
    ])
    assert not [p for p in derive_probes(g, problems) if p.kind == "unsolved"]      # 해결 장이 없다


def test_해결_장_개념이_문제와_낱말을_나누면_풀린_것으로_본다():
    # 「일정 자동 공유」 가 해결 장에 있고 「일정 불일치」 와 「일정」 을 나눈다 — solve 주장이 없어도 짝이다
    g = graph(("m", "모임 성사", [1], None), ("sched", "일정 불일치", [1], "m"), ("shy", "첫 만남 부담", [1], "m"),
              ("noshow", "당일 불참", [1], "m"), ("share", "일정 자동 공유", [2], "m"), ("badge", "소개 카드", [2], "m"))
    doc = ClaimDoc(file_name="x", claims=[
        Claim(id="c01", kind="compose", subject_id="m", object_ids=["sched", "shy", "noshow"],
              evidence=[q(1, "모임이 깨지는 세 가지 이유")]),
        Claim(id="c02", kind="solve", subject_id="badge", object_ids=["shy"], evidence=[q(2, "소개 카드로 첫 만남 부담을 줄입니다.")]),
    ])
    assert [p.node_ids[0] for p in derive_probes(g, doc) if p.kind == "unsolved"] == ["noshow"]


def test_문제_해결_표_행이_짝을_지으면_빈_문제가_없다():
    plan = deck((1, "민원이 쌓이는 세 가지 문제\n안내 부족\n처리 지연\n담당자 부재"),
                (2, "개선 방법\n| 안내 부족 | 안내문 다시 쓰기 |\n| 처리 지연 | 처리 기한 설정 |\n| 담당자 부재 | 당번제 도입 |"))
    g = graph(("root", "민원 처리", [1, 2], None, 1.0), ("info", "안내 부족", [1, 2], "root"),
              ("late", "처리 지연", [1, 2], "root"), ("absent", "담당자 부재", [1, 2], "root"))
    solves = rule_solve_rows(g, plan)
    assert sorted(c.object_ids[0] for c in solves) == ["absent", "info", "late"]
    doc = build_claims(g, plan, llm="none")
    assert not [p for p in derive_probes(g, doc) if p.kind == "unsolved"]


def test_인과_탐침의_목적어는_인용에_나온_것만_없으면_주어만():
    g = graph(("root", "지역 상권", [1], None), ("single", "1인 가구 증가", [1], "root"),
              ("worker", "직장인", [1], "root"), ("meal", "간편식 수요", [1], "root"))
    doc = ClaimDoc(file_name="x", claims=[
        Claim(id="c01", kind="cause", subject_id="single", object_ids=["worker"], has_support=False,
              evidence=[q(1, "1인 가구 증가가 간편식 매출을 늘립니다.")]),
        Claim(id="c02", kind="cause", subject_id="worker", object_ids=["single", "meal"], has_support=False,
              evidence=[q(1, "야근하는 직장인이 간편식 수요를 키웁니다.")]),
        Claim(id="c03", kind="cause", subject_id="meal", object_ids=["worker"], has_support=False,
              evidence=[q(1, "퇴근이 늦어지면 저녁을 거릅니다.")]),        # 주어도 인용에 없다 — 버린다
    ])
    probes = {p.claim_ids[0]: p for p in derive_probes(g, doc) if p.kind == "unsupported_cause"}
    assert probes["c01"].node_ids == ["single"]                    # 「직장인」 은 인용에 없다 — 지어내지 않는다
    assert probes["c02"].node_ids == ["worker", "meal"]
    assert "c03" not in probes
    labels = {n.id: n.label for n in g.nodes}
    text = probe_question(probes["c01"], labels, {n.id: n for n in g.nodes}, doc)
    assert text == "「1인 가구 증가가 간편식 매출을 늘립니다.」라고 했는데, 그렇게 볼 수 있는 근거는 무엇인가요?"


def test_함께_필요하다고_한_요소에는_하나만_고르라고_묻지_않는다():
    g = graph(("mk", "홍보 효과", [1, 2], None), ("sns", "SNS 게시", [1, 2], "mk", 0.6), ("flyer", "전단 배포", [1, 2], "mk", 0.5))
    both = ClaimDoc(file_name="x", claims=[
        Claim(id="c01", kind="compose", subject_id="mk", object_ids=["sns", "flyer"],
              evidence=[q(1, "홍보 효과 = SNS 게시 + 전단 배포"), q(2, "온라인 홍보뿐 아니라 오프라인 전단도 있어야 합니다.")]),
    ])
    assert not [p for p in derive_probes(g, both) if p.kind == "sibling_priority"]
    alone = ClaimDoc(file_name="x", claims=[
        Claim(id="c01", kind="compose", subject_id="mk", object_ids=["sns", "flyer"], evidence=[q(1, "홍보 효과 = SNS 게시 + 전단 배포")]),
    ])
    assert [p.node_ids for p in derive_probes(g, alone) if p.kind == "sibling_priority"] == [["sns", "flyer"]]


def test_F26_이_함께_필요하다는_줄을_compose_인용에_붙인다():
    course = deck((1, "좋은 강의의 두 요소\n강의 = 설명 + 실습"),
                  (2, "설명과 실습\n둘 중 하나만으로는 실력이 늘지 않습니다."))
    g = graph(("c", "강의", [1], None), ("talk", "설명", [1, 2], "c"), ("lab", "실습", [1, 2], "c"))
    doc = build_claims(g, course, llm="none")
    comp = next(c for c in doc.claims if c.kind == "compose")
    assert "둘 중 하나만으로는 실력이 늘지 않습니다." in [e.quote for e in comp.evidence]
    assert not [p for p in derive_probes(g, doc) if p.kind == "sibling_priority"]


def test_형제_우선순위_탐침은_다른_탐침이_있으면_덱에_하나만():
    g = graph(("a", "매출", [1], None), ("x1", "방문객", [1], "a", 0.6), ("x2", "객단가", [1], "a", 0.5),
              ("b", "비용", [2], None), ("y1", "임대료", [2], "b", 0.6), ("y2", "인건비", [2], "b", 0.5))
    doc = ClaimDoc(file_name="x", claims=[
        Claim(id="c01", kind="compose", subject_id="a", object_ids=["x1", "x2"], evidence=[q(1, "매출 = 방문객 × 객단가")]),
        Claim(id="c02", kind="compose", subject_id="b", object_ids=["y1", "y2"], evidence=[q(2, "비용 = 임대료 + 인건비")]),
        Claim(id="c03", kind="absolute", subject_id="b", evidence=[q(2, "임대료는 반드시 오른다.")]),
    ])
    kinds_ = [p.kind for p in derive_probes(g, doc)]
    assert kinds_.count("sibling_priority") == 1 and "absolute_boundary" in kinds_
    only = ClaimDoc(file_name="x", claims=doc.claims[:2])
    assert [p.kind for p in derive_probes(g, only)].count("sibling_priority") == 2   # 다른 탐침이 없으면 둔다


def test_부정된_단정_주장은_탐침이_되지_않는다():
    g = graph(("a", "재고 관리", [1], None))
    doc = ClaimDoc(file_name="x", claims=[Claim(id="c01", kind="absolute", subject_id="a",
                                               evidence=[q(1, "재고 손실을 완전히 없앨 수는 없습니다.")])])
    assert derive_probes(g, doc) == []


def test_겹친_이름의_두_노드는_긴장에서_같은_개념이다():
    g = graph(("q", "서비스 품질", [1, 2], None, 1.0), ("t1", "충분한 인력", [2], "q"), ("t2", "인력 부족", [1], "q"),
              ("k", "친절", [2], "q"))
    doc = ClaimDoc(file_name="x", claims=[
        Claim(id="c01", kind="compare", subject_id="q", object_ids=["t2"], evidence=[q(1, "인력보다 중요한 서비스 품질")]),
        Claim(id="c02", kind="compose", subject_id="q", object_ids=["t1", "k"], evidence=[q(2, "서비스 품질 = 충분한 인력 × 친절")]),
    ])
    tension = [p for p in derive_probes(g, doc) if p.kind == "tension"]
    assert tension and tension[0].node_ids == ["q", "t1"]


# ---------------------------------------------------------------------------
# 과적합 방지 — 프롬프트 예시에 실제 덱 낱말이 없다
# ---------------------------------------------------------------------------

def test_주장_프롬프트_예시에_튜닝_덱_낱말이_없다():
    scan = Path(__file__).resolve().parent.parent / "labs" / "qa_bench" / "overfit_scan.py"
    text = scan.read_text(encoding="utf-8")
    block = text[text.index("DECK_WORDS = {"): text.index("}", text.index("DECK_WORDS = {")) + 1]
    words = re.findall(r'"([^"]+)"', block.split(":", 1)[1])
    hits = [w for w in words if len(w) >= 2 and w in SYSTEM_PROMPT]
    assert hits == []
