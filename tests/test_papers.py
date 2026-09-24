"""
F-24 문헌 — 자료 인용 추출(_evidence.citation_lines) · OpenAlex 어댑터 · build_papers/search_papers ·
F-08 인용 검사(목록 밖 논문을 인용한 문장은 버린다). 네트워크·API 키 없이 돈다.
"""

import json

import pytest

from chuckchuck._evidence import citation_lines, find_citations
from chuckchuck.contracts import (
    ConceptGraph,
    ConceptNode,
    PaperDoc,
    PaperError,
    PaperRef,
    QaTriage,
    Slide,
    SlideBlock,
    SlideDoc,
    TriageMark,
)
from chuckchuck.f08_questions import (
    CITE_SYSTEM_PROMPT,
    PAPER_SYSTEM_ADDENDUM,
    QUESTION_SYSTEM_PROMPT,
    _build_question_prompt,
    build_questions,
)
from chuckchuck.f24_papers import build_papers, search_papers
from chuckchuck.providers.llm_base import LLMProvider
from chuckchuck.providers.scholar_base import ScholarProvider
from chuckchuck.providers.scholar_impl import OpenAlexScholar, _abstract_from_inverted, coverage, get_scholar


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def slide(no: int, title: str, *lines: str) -> Slide:
    return Slide(slide_no=no, title=title, blocks=[SlideBlock(category="paragraph", text="\n".join(lines))])


REF_SLIDE = slide(
    12, "REFERENCES",
    "REFERENCES", "참고 연구",
    "Stothart, Mitchum & Yehnert (2015)",
    "The attentional cost of receiving a cell phone notification. Journal of Experimental Psychology: HPP. DOI: 10.1037/xhp0000100",
    "Ward, Duke, Gneezy & Bos (2017)",
    "Brain Drain: The Mere Presence of One’s Own Smartphone Reduces Available Cognitive Capacity. DOI: 10.10 86/691462",
    # Upstage 가 순서를 흔든 항목 — 제목 → DOI → 저자
    "Why is it so hard to do my work? The challenge of attention residue when switching between work tasks. DOI:",
    "10.1016/j.obhdp.2009.04.002",
    "Leroy (2009)",
    "Peng et al. (CHI 2021)",
    "No task left behind? Examining the nature of fragmented work. CHI Extended Abstracts.",
)


def make_slidedoc() -> SlideDoc:
    return SlideDoc(file_name="deck.pdf", total_slides=12, slides=[
        slide(3, "배경", "알림은 주의를 빼앗는다 — Stothart et al. (2015)"),
        slide(5, "선행 연구", "김철수 등(2021)은 국내 대학생 표본으로 같은 효과를 봤다"),
        REF_SLIDE,
    ])


def make_graph() -> ConceptGraph:
    return ConceptGraph(file_name="deck.pdf", total_slides=12, nodes=[
        ConceptNode(id="c1", label="알림의 주의 비용", slide_nos=[3], summary="알림 하나가 과제 수행을 흔든다", weight=1.0),
        ConceptNode(id="c2", label="Attention residue", slide_nos=[5], weight=0.8),
        ConceptNode(id="c3", label="표본", slide_nos=[5], weight=0.3, importance="support"),
    ])


class FakeScholar(ScholarProvider):
    name = "fake"

    def __init__(self, hits: dict[str, list[PaperRef]] | None = None, fail: bool = False):
        self.hits = hits or {}
        self.fail = fail
        self.queries: list[str] = []

    def search(self, query, *, limit=5):
        self.queries.append(query)
        if self.fail:
            raise PaperError("boom")
        return [PaperRef.from_dict(r.to_dict()) for r in self.hits.get(query, [])][:limit]


class ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, replies: dict[str, dict]):
        self.replies = replies
        self.systems: list[str] = []
        self.users: list[str] = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.systems.append(system)
        self.users.append(user)
        for tag, reply in self.replies.items():
            if tag in user:
                return json.dumps(reply, ensure_ascii=False)
        return "{}"


def scholar_ref(title, authors, year, doi="", abstract="", cited=0) -> PaperRef:
    return PaperRef(id="", kind="scholar", title=title, authors=authors, year=year, doi=doi,
                    abstract=abstract, cited_by=cited)


# ---------------------------------------------------------------------------
# citation_lines — 결정론 인용 추출
# ---------------------------------------------------------------------------

def test_본문_인용과_참고문헌_장을_합쳐서_뽑는다():
    refs = citation_lines(make_slidedoc())
    by_key = {r.cite_key: r for r in refs}
    assert [r.id for r in refs] == [f"d{i:02d}" for i in range(1, len(refs) + 1)]
    st = by_key["Stothart et al. (2015)"]
    assert st.slide_no == 3                      # 첫 등장 장 (본문) — 교수는 "3장에서 인용한" 으로 묻는다
    assert st.title.startswith("The attentional cost")
    assert st.doi == "10.1037/xhp0000100"
    assert st.venue.startswith("Journal of Experimental Psychology")
    assert len(st.authors) == 3                  # 참고문헌 장의 세 저자로 보강


def test_한글_인용도_잡는다():
    refs = {r.cite_key: r for r in citation_lines(make_slidedoc())}
    assert "김철수 et al. (2021)" in refs
    assert refs["김철수 et al. (2021)"].slide_no == 5


def test_줄_순서가_흔들린_항목도_제_DOI_를_찾는다():
    refs = {r.cite_key: r for r in citation_lines(make_slidedoc())}
    assert refs["Ward et al. (2017)"].doi == "10.1086/691462"          # 공백 낀 DOI 복원
    assert refs["Leroy (2009)"].doi == "10.1016/j.obhdp.2009.04.002"   # 저자 줄 앞의 제목·DOI
    assert refs["Leroy (2009)"].title.startswith("Why is it so hard to do my work?")
    assert refs["Peng et al. (2021)"].title.startswith("No task left behind? Examining")
    assert refs["Peng et al. (2021)"].venue == "CHI Extended Abstracts"


def test_같은_자료면_같은_결과():
    a = [r.to_dict() for r in citation_lines(make_slidedoc())]
    b = [r.to_dict() for r in citation_lines(make_slidedoc())]
    assert a == b


def test_인용_없는_자료는_빈_목록():
    assert citation_lines(SlideDoc(file_name="x", total_slides=1, slides=[slide(1, "제목", "본문")])) == []
    assert citation_lines(None) == []


def test_find_citations():
    assert find_citations("3장에서 Stothart et al. (2015)를 인용했는데") == [("stothart", 2015)]
    assert find_citations("김철수(2021)의 결과와") == [("김철수", 2021)]
    assert find_citations("2021년 조사에서") == []


# ---------------------------------------------------------------------------
# OpenAlex 어댑터
# ---------------------------------------------------------------------------

def test_역색인_초록을_원문_순서로_복원한다():
    idx = {"cost": [2], "The": [0], "attentional": [1], "of": [3]}
    assert _abstract_from_inverted(idx) == "The attentional cost of"


def test_openalex_응답을_PaperRef_로_바꾸고_품질순으로_정렬한다(monkeypatch):
    payload = {"results": [
        {"id": "https://openalex.org/W1", "display_name": "Low cited but relevant notification attention", "publication_year": 2023,
         "cited_by_count": 2, "relevance_score": 90.0,
         "authorships": [{"author": {"display_name": "Ada Lovelace"}}],
         "primary_location": {"source": {"display_name": "CHI"}},
         "abstract_inverted_index": {"A": [0], "b": [1]}, "is_retracted": False, "doi": "https://doi.org/10.1/a"},
        {"id": "https://openalex.org/W2", "display_name": "Classic highly cited notification attention", "publication_year": 2015,
         "cited_by_count": 900, "relevance_score": 80.0,
         "authorships": [{"author": {"display_name": "Cary Stothart"}}, {"author": {"display_name": "Ainsley Mitchum"}}],
         "primary_location": {"source": {"display_name": "JEP:HPP"}},
         "abstract_inverted_index": {"C": [0]}, "is_retracted": False, "doi": "https://doi.org/10.1037/xhp0000100"},
        {"id": "https://openalex.org/W3", "display_name": "Retracted", "publication_year": 2020,
         "cited_by_count": 5000, "relevance_score": 99.0, "authorships": [], "is_retracted": True},
    ]}

    class Res:
        status_code = 200
        text = ""

        def json(self):
            return payload

    calls = {}

    def fake_get(url, params=None, timeout=None, headers=None):
        calls["url"], calls["params"] = url, params
        return Res()

    monkeypatch.setattr("chuckchuck.providers.scholar_impl.requests.get", fake_get)
    refs = OpenAlexScholar(mailto="team@example.com").search("notification attention", limit=2)
    assert calls["url"].endswith("/works")
    assert calls["params"]["mailto"] == "team@example.com"
    assert "is_retracted:false" in calls["params"]["filter"]
    assert [r.title for r in refs] == ["Classic highly cited notification attention", "Low cited but relevant notification attention"]  # 겹침이 같으면 피인용이 순위를 올린다
    top = refs[0]
    assert top.kind == "scholar" and top.doi == "10.1037/xhp0000100" and top.url == "https://doi.org/10.1037/xhp0000100"
    assert top.authors == ["Stothart", "Mitchum"] and top.cite_key == "Stothart et al. (2015)"
    assert top.venue == "JEP:HPP" and top.abstract == "C" and top.query == "notification attention"


def test_openalex_오류는_PaperError(monkeypatch):
    class Res:
        status_code = 503
        text = "down"

    monkeypatch.setattr("chuckchuck.providers.scholar_impl.requests.get", lambda *a, **k: Res())
    with pytest.raises(PaperError):
        OpenAlexScholar().search("x")


def test_get_scholar_기본은_none(monkeypatch):
    monkeypatch.delenv("SCHOLAR_PROVIDER", raising=False)
    assert get_scholar().name == "none"
    assert get_scholar("openalex").name == "openalex"
    assert get_scholar("unknown-vendor").name == "none"


# ---------------------------------------------------------------------------
# build_papers
# ---------------------------------------------------------------------------

def test_검색_꺼지면_자료_인용만_남고_note_에_사정을_적는다():
    doc = build_papers(make_graph(), make_slidedoc(), scholar="none")
    assert doc.provider == "none" and "검색 꺼짐" in doc.note
    assert [r.kind for r in doc.refs] and all(r.kind == "deck" for r in doc.refs)
    # 그 장을 근거로 가진 개념이 문헌에 붙는다
    st = next(r for r in doc.refs if r.cite_key.startswith("Stothart"))
    assert st.node_ids == ["c1"]


def test_영문_개념은_그대로_한글_개념은_LLM_번역으로_검색한다():
    hit_en = scholar_ref("Attention residue paper", ["Leroy"], 2009, doi="10.1016/j.obhdp.2009.04.002", abstract="residue")
    hit_ko = scholar_ref("Notification cost paper", ["Stothart", "Mitchum"], 2015, doi="10.1037/xhp0000100", abstract="cost", cited=500)
    fake = FakeScholar({"Attention residue": [hit_en], "smartphone notification attention cost": [hit_ko]})
    llm = ScriptedLLM({"paper-queries": {"queries": [{"node_id": "c1", "query": "smartphone notification attention cost"}]}})
    doc = build_papers(make_graph(), None, scholar=fake, llm=llm, node_max=2, per_node=2)
    assert doc.provider == "fake" and doc.note == ""
    assert sorted(fake.queries) == ["Attention residue", "smartphone notification attention cost"]
    assert "(c1) 알림의 주의 비용" in llm.users[0] and "(c2)" not in llm.users[0]   # 영문은 번역 안 시킨다
    by_node = {tuple(r.node_ids): r for r in doc.refs}
    assert by_node[("c1",)].title == "Notification cost paper" and by_node[("c1",)].id == "s01"
    assert by_node[("c2",)].title == "Attention residue paper" and by_node[("c2",)].id == "s02"


def test_자료_인용을_되찾아_DOI_초록을_채우되_kind_는_deck_그대로():
    hit = scholar_ref("The attentional cost of receiving a cell phone notification", ["Stothart", "Mitchum", "Yehnert"], 2015,
                      doi="10.1037/xhp0000100", abstract="Cell phone notifications alone disrupt performance", cited=400)
    fake = FakeScholar({"The attentional cost of receiving a cell phone notification": [hit]})
    doc = build_papers(make_graph(), make_slidedoc(), scholar=fake, llm=ScriptedLLM({}), node_max=0)
    st = doc.ref("d01")
    assert st.kind == "deck" and st.abstract.startswith("Cell phone notifications") and st.cited_by == 400


def test_검색_결과가_자료_인용과_같은_논문이면_합친다():
    dup = scholar_ref("The attentional cost of receiving a cell phone notification", ["Stothart"], 2015, doi="10.1037/xhp0000100")
    fake = FakeScholar({"Attention residue": [dup]})
    doc = build_papers(make_graph(), make_slidedoc(), scholar=fake, llm=ScriptedLLM({}), node_max=2)
    assert not doc.scholar_refs
    assert "c2" in doc.ref("d01").node_ids and "c1" in doc.ref("d01").node_ids


def test_검색_실패는_예외_대신_note_와_deck_폴백():
    doc = build_papers(make_graph(), make_slidedoc(), scholar=FakeScholar(fail=True), llm=ScriptedLLM({}))
    assert doc.deck_refs and not doc.scholar_refs
    assert "검색 실패" in doc.note


def test_왕복():
    hit = scholar_ref("T", ["A"], 2020, abstract="x")
    doc = build_papers(make_graph(), make_slidedoc(), scholar=FakeScholar({"Attention residue": [hit]}), llm=ScriptedLLM({}), node_max=2)
    again = PaperDoc.from_dict(json.loads(json.dumps(doc.to_dict(), ensure_ascii=False)))
    assert again.to_dict() == doc.to_dict()


# ---------------------------------------------------------------------------
# search_papers — 자유 질문
# ---------------------------------------------------------------------------

def test_자유_질문_한글이면_번역해서_검색한다():
    hit = scholar_ref("IR survey", ["Manning"], 2008, cited=9000)
    fake = FakeScholar({"information retrieval dense retrieval survey": [hit]})
    llm = ScriptedLLM({"paper-queries": {"queries": [{"node_id": "q", "query": "information retrieval dense retrieval survey"}]}})
    doc = search_papers("IR에서 dense retrieval 관련 최신 논문 있어?", scholar=fake, llm=llm, limit=3)
    assert [r.id for r in doc.refs] == ["s01"] and doc.refs[0].query == "information retrieval dense retrieval survey"


def test_자유_질문_영문은_LLM_없이_바로():
    hit = scholar_ref("BM25 revisited", ["Robertson"], 2009)
    fake = FakeScholar({"BM25 ranking function": [hit]})
    doc = search_papers("BM25 ranking function", scholar=fake, llm=ScriptedLLM({}))
    assert doc.refs[0].title == "BM25 revisited"


def test_자유_질문_검색_꺼짐():
    doc = search_papers("아무거나", scholar="none")
    assert doc.refs == [] and "검색 꺼짐" in doc.note


# ---------------------------------------------------------------------------
# F-08 연동 — 인용은 목록 안에서만
# ---------------------------------------------------------------------------

def papers_doc() -> PaperDoc:
    return PaperDoc(file_name="deck.pdf", provider="fake", refs=[
        PaperRef(id="d01", kind="deck", title="The attentional cost of receiving a cell phone notification",
                 authors=["Stothart", "Mitchum", "Yehnert"], year=2015, slide_no=3, node_ids=["c1"],
                 abstract="Notifications alone disrupt performance"),
        PaperRef(id="s01", kind="scholar", title="Attention residue", authors=["Leroy"], year=2009,
                 node_ids=["c2"], query="attention residue"),
    ])


def triage() -> QaTriage:
    return QaTriage(file_name="deck.pdf", total_slides=12, marks=[
        TriageMark(node_id="c1", severity=1, rank=1, source="core_weight", doc_weight=1.0),
        TriageMark(node_id="c2", severity=2, rank=2, source="core_weight", doc_weight=0.8),
    ])


def test_papers_없으면_프롬프트와_시스템_프롬프트가_예전과_같다():
    g = make_graph()
    by_id = {n.id: n for n in g.nodes}
    from chuckchuck.contracts import Context
    a = _build_question_prompt(g, triage().marks, by_id, None, None, Context())
    b = _build_question_prompt(g, triage().marks, by_id, None, None, Context(), papers=None)
    c = _build_question_prompt(g, triage().marks, by_id, None, None, Context(), papers=PaperDoc(file_name="x"))
    assert a == b == c and "문헌" not in a
    llm = ScriptedLLM({"qa-questions": {"questions": []}})
    build_questions(g, triage(), track="5", llm=llm)
    assert llm.systems[0] == QUESTION_SYSTEM_PROMPT


def test_papers_가_있으면_서가와_개념별_문헌_줄이_실린다():
    g = make_graph()
    llm = ScriptedLLM({"qa-questions": {"questions": []}})
    build_questions(g, triage(), track="5", papers=papers_doc(), llm=llm)
    user, system = llm.users[0], llm.systems[0]
    assert "## 교수가 읽고 온 문헌" in user
    assert "(d01) Stothart et al. (2015) «The attentional cost" in user and "[자료 3장이 인용]" in user
    assert "초록: Notifications alone disrupt performance" in user
    assert "    문헌 (d01) Stothart et al. (2015)" in user and "    문헌 (s01) Leroy (2009)" in user
    assert system == QUESTION_SYSTEM_PROMPT + PAPER_SYSTEM_ADDENDUM


def test_목록_안_인용은_통과하고_paper_ids_를_추론한다():
    llm = ScriptedLLM({"qa-questions": {"questions": [
        {"node_id": "c1", "question": "3장에서 Stothart et al. (2015)를 인용했는데, 어느 조건을 쟀나요?",
         "why": "문헌 근거", "hint": "조건", "answer_gist": "알림을 확인하지 않은 조건", "paper_ids": ["d01", "zzz"]},
        {"node_id": "c2", "question": "Leroy (2009)의 attention residue 가 여기 어떻게 적용되나요?",
         "why": "w", "hint": "h", "answer_gist": "작업 전환 뒤 남는 주의", "paper_ids": []},
    ]}})
    doc = build_questions(make_graph(), triage(), track="5", papers=papers_doc(), llm=llm)
    q1, q2 = doc.questions
    assert "Stothart" in q1.question and q1.paper_ids == ["d01"]        # 지어낸 id(zzz) 는 버린다
    assert q2.paper_ids == ["s01"]                                       # 문장의 인용에서 추론
    assert [p.id for p in doc.papers] == ["d01", "s01"]
    again = doc.__class__.from_dict(doc.to_dict())
    assert again.questions[0].paper_ids == ["d01"] and again.papers[0].cite_key == "Stothart et al. (2015)"


def test_목록_밖_논문을_인용한_문장은_버리고_템플릿으로_메운다():
    llm = ScriptedLLM({"qa-questions": {"questions": [
        {"node_id": "c1", "question": "Smith et al. (2019)는 반대 결과를 냈는데 어떻게 보나요?",
         "why": "Smith (2019) 근거", "hint": "Smith 논문을 떠올려 보세요", "answer_gist": "Smith et al. (2019)와 달리 …"},
    ]}})
    doc = build_questions(make_graph(), triage(), track="5", papers=papers_doc(), llm=llm)
    q1 = doc.questions[0]
    assert "Smith" not in q1.question and "Smith" not in q1.why and "Smith" not in q1.answer_gist
    assert q1.question and q1.why and q1.hint and q1.answer_gist      # 구멍은 안 낸다
    assert q1.paper_ids == [] and doc.papers == []


def test_papers_없이는_인용_검사를_하지_않는다():
    llm = ScriptedLLM({"qa-questions": {"questions": [
        {"node_id": "c1", "question": "Smith et al. (2019)를 어떻게 보나요?", "why": "w", "hint": "h", "answer_gist": "g"},
    ]}})
    doc = build_questions(make_graph(), triage(), track="5", llm=llm)
    assert "Smith" in doc.questions[0].question and doc.questions[0].paper_ids == []


# ---------------------------------------------------------------------------
# 되찾기(resolve) · 검색어 정제 · 낱말 겹침 순위
# ---------------------------------------------------------------------------

def test_clean_query_는_와일드카드와_따옴표를_지운다():
    from chuckchuck.providers.scholar_impl import clean_query
    assert clean_query('Why is it so hard? "attention" residue: work*') == "Why is it so hard attention residue work"


def test_coverage_는_어간으로_센다():
    assert coverage("attention residue task switching", "Tasks Interrupted: resumption", "attentional residue") == 0.75
    assert coverage("", "x", "y") == 1.0


def test_낱말_겹침이_낮은_고피인용_논문은_뒤로_간다(monkeypatch):
    payload = {"results": [
        {"id": "W1", "display_name": "AlphaFold structure prediction", "publication_year": 2024, "cited_by_count": 15000,
         "relevance_score": 330.0, "authorships": [{"author": {"display_name": "J Jumper"}}],
         "abstract_inverted_index": {"protein": [0]}, "is_retracted": False},
        {"id": "W2", "display_name": "Attention residue when switching tasks", "publication_year": 2018, "cited_by_count": 84,
         "relevance_score": 250.0, "authorships": [{"author": {"display_name": "Sophie Leroy"}}],
         "abstract_inverted_index": {"attention": [0], "residue": [1]}, "is_retracted": False},
    ]}

    class Res:
        status_code = 200
        text = ""

        def json(self):
            return payload

    monkeypatch.setattr("chuckchuck.providers.scholar_impl.requests.get", lambda *a, **k: Res())
    refs = OpenAlexScholar().search("attention residue task switching", limit=1)
    assert refs[0].title.startswith("Attention residue")


def test_resolve_는_DOI_가_있으면_DOI_로_조회한다(monkeypatch):
    calls = []

    class Res:
        status_code = 200
        text = ""

        def json(self):
            return {"id": "W9", "display_name": "The attentional cost of receiving a cell phone notification",
                    "publication_year": 2015, "cited_by_count": 400, "doi": "https://doi.org/10.1037/xhp0000100",
                    "authorships": [{"author": {"display_name": "Cary Stothart"}}],
                    "abstract_inverted_index": {"Notifications": [0]}, "is_retracted": False}

    def fake_get(url, params=None, timeout=None, headers=None):
        calls.append(url)
        return Res()

    monkeypatch.setattr("chuckchuck.providers.scholar_impl.requests.get", fake_get)
    hit = OpenAlexScholar().resolve("whatever", "10.1037/xhp0000100")
    assert calls == ["https://api.openalex.org/works/https://doi.org/10.1037/xhp0000100"]
    assert hit[0].abstract == "Notifications" and hit[0].cited_by == 400


def test_resolve_는_DOI_없으면_제목_필터로_찾고_404_는_빈_목록(monkeypatch):
    seen = {}

    class Res:
        def __init__(self, code, body):
            self.status_code, self._body, self.text = code, body, ""

        def json(self):
            return self._body

    def fake_get(url, params=None, timeout=None, headers=None):
        seen["url"], seen["params"] = url, params
        if url.endswith("/works"):
            return Res(200, {"results": []})
        return Res(404, {})

    monkeypatch.setattr("chuckchuck.providers.scholar_impl.requests.get", fake_get)
    assert OpenAlexScholar().resolve("Why is it so hard to do my work?", "") == []
    assert "title.search:Why is it so hard to do my work" in seen["params"]["filter"]
    assert OpenAlexScholar().resolve("x", "10.0/missing") == []


def test_build_papers_는_DOI_있는_자료_인용을_resolve_로_되찾는다():
    class ResolvingScholar(FakeScholar):
        def __init__(self):
            super().__init__()
            self.resolved: list[tuple[str, str]] = []

        def resolve(self, title, doi=""):
            self.resolved.append((title, doi))
            if doi == "10.1037/xhp0000100":
                return [scholar_ref(title, ["Stothart"], 2015, doi=doi, abstract="Notifications disrupt", cited=400)]
            return []

    sch = ResolvingScholar()
    doc = build_papers(make_graph(), make_slidedoc(), scholar=sch, llm=ScriptedLLM({}), node_max=0)
    assert ("The attentional cost of receiving a cell phone notification", "10.1037/xhp0000100") in sch.resolved
    assert doc.ref("d01").abstract == "Notifications disrupt" and doc.ref("d01").kind == "deck"


def test_번역_응답의_id_가_틀려도_label_과_순서로_받는다():
    from chuckchuck.f24_papers import _translate_queries
    llm = ScriptedLLM({"paper-queries": {"queries": [
        {"node_id": "c1", "label": "알림의 주의 비용", "query": "notification attention cost"},   # 예시 id 를 베낀 경우
        {"node_id": "c2", "query": "attention residue"},                                       # label 도 없음 → 순서
        {"node_id": "zzz", "query": "한국어 검색어"},                                             # 한글은 버린다
    ]}})
    out = _translate_queries([("notification", "알림의 주의 비용 — 요약"), ("residue", "주의 잔류"), ("x", "기타")], llm, None)
    assert out == {"notification": "notification attention cost", "residue": "attention residue"}


def test_문헌이_있는데_인용_0_이면_그_질문만_qa_cite_로_한_번_고쳐_쓴다():
    class CountingLLM(LLMProvider):
        name = "counting"

        def __init__(self):
            self.systems, self.users = [], []

        def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
            self.systems.append(system)
            self.users.append(user)
            if "[TASK] qa-cite" in user:
                return json.dumps({"questions": [
                    {"node_id": "c1", "question": "3장에서 인용한 Stothart et al. (2015)는 무엇을 쟀나요?", "why": "문헌 근거",
                     "hint": "조건", "paper_ids": ["d01"]},
                    {"node_id": "c2", "question": "Smith (2020)는 어떻게 보나요?", "paper_ids": ["s01"]},   # 목록 밖 인용 → 안 받는다
                ]}, ensure_ascii=False)
            return json.dumps({"questions": [
                {"node_id": "c1", "question": "알림 비용은 왜 생기나요?", "why": "w", "hint": "h", "answer_gist": "원래 골자"},
                {"node_id": "c2", "question": "잔여 주의란 무엇인가요?", "why": "w2", "hint": "h2", "answer_gist": "g2"}]}, ensure_ascii=False)

    llm = CountingLLM()
    doc = build_questions(make_graph(), triage(), track="5", papers=papers_doc(), llm=llm)
    assert len(llm.systems) == 2 and llm.systems[1] == CITE_SYSTEM_PROMPT
    cite_user = llm.users[1]
    # 인용 없는 질문 둘 다, 각자의 문헌과 함께 실린다 — 전체 프롬프트가 아니라 이것만
    assert "### (c1) 알림의 주의 비용" in cite_user and "question: 알림 비용은 왜 생기나요?" in cite_user
    assert "문헌 (d01) Stothart et al. (2015)" in cite_user and "문헌 (s01) Leroy (2009)" in cite_user
    assert "## 교수가 읽고 온 문헌" not in cite_user
    q1, q2 = doc.questions
    assert "Stothart et al. (2015)" in q1.question and q1.paper_ids == ["d01"] and q1.why == "문헌 근거"
    assert q1.answer_gist == "원래 골자"                         # 골자는 고치지 않는다
    assert "Smith" not in q2.question and q2.question == "잔여 주의란 무엇인가요?" and q2.paper_ids == []   # 원문 유지
    # 인용이 이미 있으면 qa-cite 를 부르지 않는다
    llm2 = ScriptedLLM({"qa-questions": {"questions": [
        {"node_id": "c1", "question": "Stothart et al. (2015)는 무엇을 쟀나요?", "why": "w", "hint": "h", "answer_gist": "g"},
        {"node_id": "c2", "question": "Leroy (2009)를 어떻게 적용하나요?", "why": "w", "hint": "h", "answer_gist": "g"}]}})
    build_questions(make_graph(), triage(), track="5", papers=papers_doc(), llm=llm2)
    assert len(llm2.systems) == 1


def test_qa_cite_결과의_제목_조각과_끝에_덧붙인_인용은_떼고_길거나_반말이면_원문을_지킨다():
    from chuckchuck.contracts import QA_TEXT_MAX
    from chuckchuck.f08_questions import _clean_rewritten

    assert _clean_rewritten("메커니즘은 무엇인가요? Stothart et al. (2015) «The attentional cost …»") == "메커니즘은 무엇인가요?"
    assert _clean_rewritten("어떤 영향을 주나요? Leroy (2009)") == "어떤 영향을 주나요?"
    assert _clean_rewritten("Stothart et al. (2015)는 무엇을 쟀나요?") == "Stothart et al. (2015)는 무엇을 쟀나요?"

    class Cite(LLMProvider):
        name = "cite"

        def __init__(self, question):
            self.q = question

        def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
            if "[TASK] qa-cite" in user:
                return json.dumps({"questions": [{"node_id": "c1", "question": self.q, "paper_ids": ["d01"]}]}, ensure_ascii=False)
            return json.dumps({"questions": [
                {"node_id": "c1", "question": "알림 비용은 왜 생기나요?", "why": "w", "hint": "h", "answer_gist": "g"}]}, ensure_ascii=False)

    # 끝에 «제목» 만 덧붙인 것 → 제목을 떼면 인용이 없다 → 원문 유지
    doc = build_questions(make_graph(), triage(), track="5", papers=papers_doc(), llm=Cite("알림 비용은 왜 생기나요? Stothart et al. (2015) «제목»"))
    assert doc.questions[0].question == "알림 비용은 왜 생기나요?" and doc.questions[0].paper_ids == []
    # 초록을 옮겨 적어 상한을 넘긴 것 → 원문 유지
    long_q = "Stothart et al. (2015)는 " + "주의 자원을 공유해야 하기 때문에 성능이 저하된다고 밝혔으며, " * 12 + "어떻게 보나요?"
    assert len(long_q) > QA_TEXT_MAX
    doc = build_questions(make_graph(), triage(), track="5", papers=papers_doc(), llm=Cite(long_q))
    assert doc.questions[0].question == "알림 비용은 왜 생기나요?"
    # 반말 의문은 해요체로 고쳐서 받는다
    doc = build_questions(make_graph(), triage(), track="5", papers=papers_doc(), llm=Cite("Stothart et al. (2015)는 무엇을 쟀는가?"))
    assert doc.questions[0].question.endswith("요?") and doc.questions[0].paper_ids == ["d01"]


def test_qa_cite_가_깨진_JSON_이면_첫_응답을_그대로_쓴다():
    class BrokenCite(LLMProvider):
        name = "broken"

        def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
            if "[TASK] qa-cite" in user:
                return "not json at all"
            return json.dumps({"questions": [
                {"node_id": "c1", "question": "알림 비용은 왜 생기나요?", "why": "w", "hint": "h", "answer_gist": "g"}]}, ensure_ascii=False)

    doc = build_questions(make_graph(), triage(), track="5", papers=papers_doc(), llm=BrokenCite())
    assert doc.questions[0].question == "알림 비용은 왜 생기나요?" and doc.questions[0].paper_ids == []


# ---------------------------------------------------------------------------
# 거짓 전제 — 검색 문헌(scholar)에 「발표자가 인용했다」 를 씌우지 않는다 (2026-09-24 실측)
# ---------------------------------------------------------------------------

class _CiteRewrite(LLMProvider):
    """첫 응답은 인용 없는 질문 둘, qa-cite 응답은 주어진 것."""
    name = "cite-rewrite"

    def __init__(self, rewrites: list[dict]):
        self.rewrites = rewrites

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        if "[TASK] qa-cite" in user:
            return json.dumps({"questions": self.rewrites}, ensure_ascii=False)
        return json.dumps({"questions": [
            {"node_id": "c1", "question": "알림 비용은 왜 생기나요?", "why": "w", "hint": "h", "answer_gist": "g"},
            {"node_id": "c2", "question": "잔여 주의란 무엇인가요?", "why": "w2", "hint": "h2", "answer_gist": "g2"},
        ]}, ensure_ascii=False)


def test_qa_cite_검색_문헌만_인용하며_인용하셨는데_라고_쓴_재작성은_버리고_원문을_지킨다():
    llm = _CiteRewrite([{"node_id": "c2", "question": "Leroy (2009)를 인용하셨는데, 잔여 주의는 어떻게 생기나요?",
                         "why": "문헌 근거", "hint": "전환", "paper_ids": ["s01"]}])
    doc = build_questions(make_graph(), triage(), track="5", papers=papers_doc(), llm=llm)
    q2 = doc.questions[1]
    assert q2.question == "잔여 주의란 무엇인가요?" and q2.paper_ids == [] and q2.why == "w2"


def test_qa_cite_자료_인용_문헌을_N장에서_인용한_으로_쓴_재작성은_받는다():
    llm = _CiteRewrite([{"node_id": "c1", "question": "3장에서 인용한 Stothart et al. (2015)는 무엇을 쟀나요?",
                         "why": "문헌 근거", "hint": "조건", "paper_ids": ["d01"]}])
    doc = build_questions(make_graph(), triage(), track="5", papers=papers_doc(), llm=llm)
    q1 = doc.questions[0]
    assert q1.question == "3장에서 인용한 Stothart et al. (2015)는 무엇을 쟀나요?" and q1.paper_ids == ["d01"]


def test_qa_cite_검색_문헌을_주어로_세워_봤는데_꼴로_쓴_재작성은_받는다():
    rewritten = "Leroy (2009)는 작업을 바꾼 뒤에도 주의가 남는다고 봤는데, 발표의 '잔여 주의'도 같은 뜻인가요?"
    llm = _CiteRewrite([{"node_id": "c2", "question": rewritten, "why": "문헌 근거", "hint": "전환", "paper_ids": ["s01"]}])
    doc = build_questions(make_graph(), triage(), track="5", papers=papers_doc(), llm=llm)
    q2 = doc.questions[1]
    assert q2.question == rewritten and q2.paper_ids == ["s01"]


def test_첫_응답의_거짓_전제는_전제_절만_떼고_높임도_푼다():
    llm = ScriptedLLM({"qa-questions": {"questions": [
        {"node_id": "c2", "question": "Leroy (2009)를 인용하셨는데, 잔여 주의가 핵심이라고 판단하신 근거는 무엇인가요?",
         "why": "w", "hint": "h", "answer_gist": "g"},
    ]}})
    doc = build_questions(make_graph(), triage(), track="5", papers=papers_doc(), llm=llm)
    q2 = next(q for q in doc.questions if q.node_id == "c2")
    assert q2.question == "잔여 주의가 핵심이라고 판단한 근거는 무엇인가요?"


def test_첫_응답의_관형절_인용은_떼면_문헌_주어_꼴이_된다():
    llm = ScriptedLLM({"qa-questions": {"questions": [
        {"node_id": "c2", "question": "5장에서 인용한 Leroy (2009)는 주의가 남는다고 봤는데, 발표는 어떻게 보나요?",
         "why": "w", "hint": "h", "answer_gist": "g"},
    ]}})
    doc = build_questions(make_graph(), triage(), track="5", papers=papers_doc(), llm=llm)
    q2 = next(q for q in doc.questions if q.node_id == "c2")
    assert q2.question == "Leroy (2009)는 주의가 남는다고 봤는데, 발표는 어떻게 보나요?" and q2.paper_ids == ["s01"]


def test_첫_응답의_인용_주장을_뗄_수_없으면_템플릿으로_간다():
    llm = ScriptedLLM({"qa-questions": {"questions": [
        {"node_id": "c2", "question": "Leroy (2009)를 인용한 이유는 무엇인가요?", "why": "w", "hint": "h", "answer_gist": "g"},
    ]}})
    doc = build_questions(make_graph(), triage(), track="5", papers=papers_doc(), llm=llm)
    q2 = next(q for q in doc.questions if q.node_id == "c2")
    assert q2.question and "Leroy" not in q2.question and "인용한 이유" not in q2.question


def test_claims_presenter_cited_는_deck_문헌이면_거짓이다():
    from chuckchuck.f08_questions import _claims_presenter_cited
    pd = papers_doc()
    assert _claims_presenter_cited("Leroy (2009)를 인용했는데 왜 그런가요?", pd)
    assert not _claims_presenter_cited("3장에서 인용한 Stothart et al. (2015)는 무엇을 쟀나요?", pd)
    assert not _claims_presenter_cited("Leroy (2009)는 그렇게 봤는데 발표는 어떤가요?", pd)
    assert not _claims_presenter_cited("3장에서 인용한 통계의 출처는 무엇인가요?", pd)   # 목록 문헌이 없으면 자료 속 인용 얘기
    assert not _claims_presenter_cited("Leroy (2009)를 인용했는데 왜 그런가요?", None)


# ---------------------------------------------------------------------------
# 관련성 검사 — 검색어와 낱말 하나 안 나누는 검색 결과는 버리고 note 에 남긴다 (2026-09-24 GDM 실측)
# ---------------------------------------------------------------------------

def test_검색어와_낱말이_겹치는_결과는_남는다():
    hit = scholar_ref("Attention residues after task switching", ["Leroy"], 2009, abstract="work tasks")
    doc = build_papers(make_graph(), None, scholar=FakeScholar({"Attention residue": [hit]}), llm=ScriptedLLM({}), node_max=2)
    assert [r.title for r in doc.scholar_refs] == ["Attention residues after task switching"]
    assert "관련성 없음" not in doc.note


def test_검색어와_낱말이_하나도_안_겹치는_결과는_버리고_note_에_적는다():
    good = scholar_ref("Attention residue at work", ["Leroy"], 2009)
    gdm = scholar_ref("Gestational diabetes mellitus prevention in pregnant women", ["Kim"], 2021,
                      abstract="A randomized trial of lifestyle intervention for GDM", cited=300)
    doc = build_papers(make_graph(), None, scholar=FakeScholar({"Attention residue": [gdm, good]}),
                       llm=ScriptedLLM({}), node_max=2)
    assert [r.title for r in doc.scholar_refs] == ["Attention residue at work"]
    assert "관련성 없음 1건 버림" in doc.note


def test_관련성_없는_결과는_자료_인용에_개념을_붙이지도_않는다():
    # 자료 인용과 같은 논문이라도 검색어와 무관하면 그 개념을 deck 문헌에 붙이지 않는다.
    dup = scholar_ref("The attentional cost of receiving a cell phone notification", ["Stothart"], 2015, doi="10.1037/xhp0000100")
    doc = build_papers(make_graph(), make_slidedoc(), scholar=FakeScholar({"completely unrelated query": [dup]}),
                       llm=ScriptedLLM({"paper-queries": {"queries": [{"node_id": "c1", "query": "completely unrelated query"}]}}),
                       node_max=1)
    assert "c1" in doc.ref("d01").node_ids          # 자료 장으로 붙은 것만
    assert "관련성 없음 1건 버림" in doc.note


def test_자유_검색도_관련성_없는_결과를_버린다():
    hits = [scholar_ref("BM25 revisited", ["Robertson"], 2009), scholar_ref("Maternal glucose screening", ["Lee"], 2020)]
    doc = search_papers("BM25 ranking function", scholar=FakeScholar({"BM25 ranking function": hits}), llm=ScriptedLLM({}))
    assert [r.title for r in doc.refs] == ["BM25 revisited"] and "관련성 없음 1건 버림" in doc.note


# ---------------------------------------------------------------------------
# 짧은 영문 라벨 검색어 보강 — 09-24 실측: "B2C" 그대로 검색해 당뇨 선별 B2C 모델 논문이 붙었다
# ---------------------------------------------------------------------------

def make_en_graph() -> ConceptGraph:
    return ConceptGraph(file_name="deck.pdf", total_slides=10, nodes=[
        ConceptNode(id="root", label="AI Presentation Coaching", slide_nos=[1], depth=1, weight=1.0),
        ConceptNode(id="b2c", label="B2C", slide_nos=[7], depth=2, weight=0.9),
        ConceptNode(id="align", label="Slide-Speech Alignment Scoring Method", slide_nos=[4], depth=2, weight=0.5),
    ])


def test_짧은_영문_라벨은_주제_토큰을_붙여_검색한다():
    fake = FakeScholar()
    build_papers(make_en_graph(), None, scholar=fake, llm=ScriptedLLM({}), node_max=3)
    assert "B2C AI Presentation Coaching" in fake.queries
    assert "AI Presentation Coaching" in fake.queries                 # 루트는 3토큰 — 자기 자신을 붙이지 않는다
    assert "Slide-Speech Alignment Scoring Method" in fake.queries   # 3토큰 이상은 그대로


def test_보강_검색어에서_개념만_맞고_주제가_안_맞는_결과는_버린다():
    gdm = scholar_ref("Early viability assessment of a Business-to-Consumer (B2C) model for digital diabetes screening",
                      ["Kim"], 2023, abstract="gestational diabetes mellitus screening", cited=12)
    fake = FakeScholar({"B2C AI Presentation Coaching": [gdm]})
    doc = build_papers(make_en_graph(), None, scholar=fake, llm=ScriptedLLM({}), node_max=3)
    assert not [r for r in doc.scholar_refs if "b2c" in r.node_ids]   # 문헌 없이 간다
    assert "관련성 없음 1건 버림" in doc.note


def test_보강_검색어에서_개념과_주제가_둘_다_맞는_결과는_남는다():
    hit = scholar_ref("A B2C subscription model for AI presentation coaching tools", ["Park"], 2024, abstract="")
    fake = FakeScholar({"B2C AI Presentation Coaching": [hit]})
    doc = build_papers(make_en_graph(), None, scholar=fake, llm=ScriptedLLM({}), node_max=3)
    kept = [r for r in doc.scholar_refs if "b2c" in r.node_ids]
    assert [r.title for r in kept] == ["A B2C subscription model for AI presentation coaching tools"]
    assert kept[0].query == "B2C AI Presentation Coaching" and "관련성 없음" not in doc.note


def test_세_토큰_이상_검색어는_예전처럼_낱말_하나만_겹쳐도_남는다():
    hit = scholar_ref("Scoring rubrics for oral exams", ["Lee"], 2019)            # 'scoring' 하나만 겹친다
    fake = FakeScholar({"Slide-Speech Alignment Scoring Method": [hit]})
    doc = build_papers(make_en_graph(), None, scholar=fake, llm=ScriptedLLM({}), node_max=3)
    assert [r.title for r in doc.scholar_refs if "align" in r.node_ids] == ["Scoring rubrics for oral exams"]


def test_주제_토큰은_weight_가_높은_지엽이_아니라_core_개념에서_온다():
    # 09-24 실측: 수익모델 자료에서 B2C·B2B·SaaS(support, weight 1.0)가 주제로 뽑혀 "B2C" 에 "B2B SaaS" 가 붙었다.
    graph = ConceptGraph(file_name="deck.pdf", total_slides=10, nodes=[
        ConceptNode(id="cg", label="Concept Graph", slide_nos=[1], depth=1, weight=0.99, importance="core"),
        ConceptNode(id="coach", label="AI Presentation Coaching", slide_nos=[1], depth=2, weight=0.7, importance="core"),
        ConceptNode(id="b2b", label="B2B", slide_nos=[2], depth=1, weight=1.0, importance="support"),
        ConceptNode(id="b2c", label="B2C", slide_nos=[2], depth=1, weight=1.0, importance="support"),
        ConceptNode(id="saas", label="SaaS", slide_nos=[2], depth=2, weight=1.0, importance="support"),
    ])
    fake = FakeScholar()
    build_papers(graph, None, scholar=fake, llm=ScriptedLLM({}), node_max=5)
    b2c = [q for q in fake.queries if q.startswith("B2C")]
    assert b2c == ["B2C Concept Graph AI Presentation Coaching"]   # core 라벨을 통째로, support(B2B·SaaS)는 안 붙는다
    assert not any("B2B" in q or "SaaS" in q for q in b2c)
