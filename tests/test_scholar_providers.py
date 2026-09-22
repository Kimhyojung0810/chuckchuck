"""
F-24 학술 검색 통로 5개 + MultiScholar — 네트워크 없이 (requests.get 을 가짜로).

09-23 실측에서 나온 결함을 고정한다: OpenAlex 결과에 source 가 비던 것, Semantic Scholar 429, Europe PMC 의 같은 논문
세 번 중복, 제목에 검색어가 하나도 없는 논문(단백질 결합 부위)이 초록 겹침만으로 서가에 오르던 것, arXiv AND 인코딩.
"""

import json

import pytest

from chuckchuck.contracts import PaperError, PaperRef
from chuckchuck.providers import scholar_impl as si
from chuckchuck.providers.scholar_base import ScholarProvider
from chuckchuck.providers.scholar_impl import (
    ArxivScholar,
    CrossrefScholar,
    EuropePmcScholar,
    MultiScholar,
    OpenAlexScholar,
    SemanticScholarScholar,
    get_scholar,
    paper_key,
    rank_refs,
)


class Res:
    def __init__(self, status=200, payload=None, text="", content=b"", headers=None):
        self.status_code, self._payload, self.text, self.content = status, payload, text, content
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def fake_get(monkeypatch, responses):
    """responses: 순서대로 돌려줄 Res 목록. 호출 기록은 calls 에."""
    calls = []
    queue = list(responses)

    def _get(url, params=None, timeout=None, headers=None):
        calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr("chuckchuck.providers.scholar_impl.requests.get", _get)
    return calls


def ref(title, authors=("A",), year=2020, doi="", abstract="", cited=0, query="", source=""):
    return PaperRef(id="", kind="scholar", title=title, authors=list(authors), year=year, doi=doi,
                    abstract=abstract, cited_by=cited, query=query, source=source)


# ---------------------------------------------------------------------------
# 통로별 파싱
# ---------------------------------------------------------------------------

def test_openalex_결과에_source_가_남는다(monkeypatch):
    fake_get(monkeypatch, [Res(payload={"results": [
        {"display_name": "Notification attention cost", "publication_year": 2020, "cited_by_count": 3, "relevance_score": 1.0,
         "authorships": [{"author": {"display_name": "Ada Lovelace"}}], "abstract_inverted_index": {"x": [0]}, "is_retracted": False},
    ]})])
    refs = OpenAlexScholar().search("notification attention", limit=1)
    assert refs and refs[0].source == "openalex"


def test_semanticscholar_는_TLDR_을_초록으로_쓰고_DOI_url_을_만든다(monkeypatch):
    calls = fake_get(monkeypatch, [Res(payload={"data": [
        {"title": "Smartphone notification attention cost", "year": 2022, "venue": "CHI", "citationCount": 37,
         "authors": [{"name": "Jane Upshaw"}, {"name": "Kim Bo"}], "externalIds": {"DOI": "10.1/abc"},
         "abstract": "long abstract " * 40, "tldr": {"text": "Notifications cost attention."}, "openAccessPdf": {"url": "http://pdf"}},
    ]})])
    refs = SemanticScholarScholar(api_key="k").search("smartphone notification attention cost", limit=1)
    assert calls[0]["url"].endswith("/paper/search") and calls[0]["headers"]["x-api-key"] == "k"
    r = refs[0]
    assert r.abstract == "Notifications cost attention." and r.doi == "10.1/abc" and r.url == "https://doi.org/10.1/abc"
    assert r.authors == ["Upshaw", "Bo"] and r.cite_key == "Upshaw et al. (2022)" and r.source == "semanticscholar"


def test_429_는_한_번_쉬고_다시_묻고_두_번째도_429_면_PaperError(monkeypatch):
    slept = []
    monkeypatch.setattr("chuckchuck.providers.scholar_impl.time.sleep", lambda s: slept.append(s))
    ok = {"data": [{"title": "Attention residue task switching", "year": 2018, "authors": [{"name": "S Leroy"}]}]}
    calls = fake_get(monkeypatch, [Res(429, text="slow down", headers={"Retry-After": "2"}), Res(payload=ok)])
    refs = SemanticScholarScholar().search("attention residue task switching", limit=1)
    assert len(calls) == 2 and slept == [2.0] and refs[0].title.startswith("Attention residue")

    fake_get(monkeypatch, [Res(429, text="slow down"), Res(429, text="slow down")])
    with pytest.raises(PaperError):
        SemanticScholarScholar().search("attention residue task switching", limit=1)


ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2101.00001v1</id>
    <title>Unsupervised Dense Information Retrieval with Contrastive Learning</title>
    <summary>We study dense retrieval for information retrieval.</summary>
    <published>2021-12-16T00:00:00Z</published>
    <author><name>Gautier Izacard</name></author><author><name>Edouard Grave</name></author>
    <arxiv:doi>10.48550/arXiv.2112.09118</arxiv:doi>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2101.00002v1</id>
    <title>Beyond Self-attention: External Attention</title>
    <summary>attention attention dense retrieval information</summary>
    <published>2021-05-05T00:00:00Z</published>
    <author><name>Meng Guo</name></author>
  </entry>
</feed>"""


def test_arxiv_는_Atom_을_읽고_AND_검색어를_공백으로_만든다(monkeypatch):
    calls = fake_get(monkeypatch, [Res(content=ATOM)])
    refs = ArxivScholar().search("dense retrieval information retrieval", limit=3)
    # "+AND+" 를 글자로 넣으면 requests 가 %2B 로 바꿔 AND 가 안 먹는다 — 공백이어야 한다
    assert calls[0]["params"]["search_query"] == "all:dense AND all:retrieval AND all:information AND all:retrieval"
    assert [r.title[:12] for r in refs] == ["Unsupervised"]        # 제목에 검색어 낱말이 없는 둘째는 문턱에서 떨어진다
    r = refs[0]
    assert r.year == 2021 and r.venue == "arXiv" and r.doi == "10.48550/arXiv.2112.09118" and r.source == "arxiv"
    assert r.authors == ["Izacard", "Grave"] and r.abstract.startswith("We study dense")


def test_arxiv_이_XML_이_아니면_PaperError(monkeypatch):
    fake_get(monkeypatch, [Res(content=b"<html>oops")])
    with pytest.raises(PaperError):
        ArxivScholar().search("dense retrieval")


def test_crossref_는_message_items_를_읽고_태그를_벗기고_mailto_를_보낸다(monkeypatch):
    monkeypatch.setenv("SCHOLAR_MAILTO", "team@example.com")
    calls = fake_get(monkeypatch, [Res(payload={"message": {"items": [
        {"DOI": "10.1016/j.obhdp.2009.04.002", "title": ["Why is it so hard to do my work? Attention residue"],
         "author": [{"family": "Leroy", "given": "Sophie"}], "issued": {"date-parts": [[2009, 7]]},
         "container-title": ["OBHDP"], "abstract": "<jats:p>Attention residue when switching tasks</jats:p>",
         "is-referenced-by-count": 500, "URL": "http://x"},
    ]}})])
    refs = CrossrefScholar().search("attention residue task switching", limit=1)
    assert calls[0]["params"]["mailto"] == "team@example.com" and calls[0]["params"]["query.bibliographic"]
    r = refs[0]
    assert r.cite_key == "Leroy (2009)" and r.venue == "OBHDP" and r.cited_by == 500 and r.source == "crossref"
    assert r.abstract == "Attention residue when switching tasks" and r.url == "https://doi.org/10.1016/j.obhdp.2009.04.002"


def test_crossref_resolve_는_DOI_로_바로_조회한다(monkeypatch):
    calls = fake_get(monkeypatch, [Res(payload={"message": {"DOI": "10.1/x", "title": ["T"], "author": [], "issued": {"date-parts": [[2015]]}}})])
    refs = CrossrefScholar().resolve("T", "10.1/x")
    assert calls[0]["url"].endswith("/works/10.1/x") and refs[0].year == 2015


def test_europepmc_는_같은_논문의_MED_PMC_PPR_판을_하나로_합친다(monkeypatch):
    item = {"title": "Attention hijacked: notifications disrupt attention.", "pubYear": "2025", "doi": "10.1/hij",
            "authorString": "Fournier L, Kim B.", "journalTitle": "J", "abstractText": "smartphone notification attention cost",
            "citedByCount": 4}
    fake_get(monkeypatch, [Res(payload={"resultList": {"result": [
        {**item, "source": "MED", "id": "1"}, {**item, "source": "PMC", "id": "2"}, {**item, "source": "PPR", "id": "3"},
    ]}})])
    refs = EuropePmcScholar().search("smartphone notification attention cost", limit=3)
    assert len(refs) == 1
    r = refs[0]
    assert r.title == "Attention hijacked: notifications disrupt attention" and r.authors == ["Fournier", "Kim"]
    assert r.cite_key == "Fournier et al. (2025)" and r.source == "europepmc" and r.cited_by == 4


# ---------------------------------------------------------------------------
# 순위 규칙 — 모든 통로가 rank_refs 하나를 쓴다
# ---------------------------------------------------------------------------

def test_제목에_검색어_낱말이_하나도_없는_논문은_초록이_겹쳐도_버린다():
    q = "attention residue task switching"
    protein = ref("Handshake: Partner-Specific Protein-Protein Binding Site Prediction", year=2026,
                  abstract="residue attention task interface", query=q)
    leroy = ref("Tasks Interrupted: attention residue on resumption", ("Leroy",), 2018, abstract="attention residue", cited=84, query=q)
    out = rank_refs([(1.0, protein), (0.5, leroy)], limit=3)
    assert [r.title[:5] for r in out] == ["Tasks"]
    # 검색어 낱말이 하나뿐이면 문턱을 걸지 않는다
    one = ref("Handshake", abstract="notification", query="notification")
    assert rank_refs([(1.0, one)], limit=1) == [one]


def test_제목_문턱은_보증_여부로_달라진다():
    q = "attention residue task switching"          # 낱말 4개
    # 아무도 보증하지 않은 논문(피인용 0 · 한 통로)은 제목에 3개는 있어야 한다
    cross_attn = ref("Binding Site Prediction at Residue Level with Cross-Attention", year=2026,
                     abstract="residue attention task", query=q, source="europepmc")
    assert rank_refs([(1.0, cross_attn)], limit=3) == []                       # attention·residue 둘로는 못 오른다
    cross_attn.cited_by = 12
    assert rank_refs([(1.0, cross_attn)], limit=3) == [cross_attn]            # 피인용이 있으면 2개면 된다
    cross_attn.cited_by, cross_attn.source = 0, "openalex+europepmc"
    assert rank_refs([(1.0, cross_attn)], limit=3) == [cross_attn]            # 두 통로가 같이 찾아도 2개면 된다
    preprint = ref("Attention residue after task switching: a preprint", abstract="attention residue", query=q, source="arxiv")
    assert rank_refs([(1.0, preprint)], limit=3) == [preprint]                # 제목이 검색어를 다 말하면 프리프린트도 오른다
    # 피인용이 있어도 제목에 낱말 하나뿐이면 버린다 — 냉장 창고 IoT 알림 시스템 (09-23 실측)
    iot = ref("An IoT-Based Real-Time Intelligent Monitoring and Notification System of Cold Storage", cited=40,
              abstract="notification loss concentration post check", query="smartphone notification post-check concentration loss",
              source="openalex")
    assert rank_refs([(1.0, iot)], limit=3) == []
    # 검색어 낱말이 2개면 둘 다
    assert rank_refs([(1.0, ref("Dense passage retrieval", abstract="x", query="dense retrieval", source="arxiv"))], limit=1)
    assert rank_refs([(1.0, ref("Dense something", abstract="retrieval", query="dense retrieval", source="arxiv"))], limit=1) == []


# ---------------------------------------------------------------------------
# MultiScholar — 합치기 · 한 통로 실패 · 전부 실패
# ---------------------------------------------------------------------------

class Fake(ScholarProvider):
    def __init__(self, name, hits, fail=False):
        self.name, self.hits, self.fail = name, hits, fail

    def search(self, query, *, limit=5):
        if self.fail:
            raise PaperError(f"{self.name} down")
        return [PaperRef.from_dict(r.to_dict()) for r in self.hits][:limit]

    def resolve(self, title, doi=""):
        return self.search(title, limit=1)


def test_multi_는_같은_논문을_합치고_source_를_a_b_로_남기고_DOI_를_채우면_url_도_바꾼다(capsys):
    q = "smartphone notification attention cost"
    a = Fake("openalex", [ref("Smartphone notification attention cost", ("Upshaw",), 2022, doi="10.1/u", abstract="smartphone notification", cited=31, query=q, source="openalex"),
                          ref("Notification cost of smartphones", ("Mourra",), 2020, doi="10.1/m", abstract="smartphone notification attention", cited=45, query=q, source="openalex")])
    b = Fake("arxiv", [ref("Smartphone notification attention cost", ("Upshaw", "Kim"), 2022, abstract="smartphone notification cost attention", cited=0, query=q, source="arxiv")])
    b.hits[0].url = "http://arxiv.org/abs/1"
    m = MultiScholar([a, b])
    assert m.name == "openalex+arxiv"
    out = m.search(q, limit=5)
    assert [r.source for r in out] == ["openalex+arxiv", "openalex"]      # 두 통로가 같이 찾은 논문이 앞으로
    top = out[0]
    assert top.cited_by == 31 and top.doi == "10.1/u" and top.url == "https://doi.org/10.1/u" and top.authors == ["Upshaw", "Kim"]

    # DOI 가 없던 쪽이 먼저 오고 나중 통로가 DOI 를 주면 url 도 DOI 로
    c = Fake("arxiv", [ref("Only arxiv first", abstract="only arxiv first", query="only arxiv first", source="arxiv")])
    c.hits[0].url = "http://arxiv.org/abs/2"
    d = Fake("openalex", [ref("Only arxiv first", doi="10.1/z", abstract="only arxiv first", query="only arxiv first", source="openalex")])
    got = MultiScholar([c, d]).search("only arxiv first", limit=1)[0]
    assert got.doi == "10.1/z" and got.url == "https://doi.org/10.1/z"


def test_multi_는_한_통로가_죽어도_나머지로_가고_전부_죽으면_PaperError(capsys):
    q = "dense retrieval"
    ok = Fake("openalex", [ref("Dense retrieval", abstract="dense retrieval", query=q, source="openalex")])
    dead = Fake("semanticscholar", [], fail=True)
    out = MultiScholar([ok, dead]).search(q, limit=3)
    assert [r.title for r in out] == ["Dense retrieval"]
    assert "semanticscholar down" in capsys.readouterr().err
    with pytest.raises(PaperError):
        MultiScholar([Fake("a", [], fail=True), Fake("b", [], fail=True)]).search(q)


def test_multi_resolve_는_통로들의_첫_결과를_합쳐_하나만_낸다():
    a = Fake("openalex", [ref("The attentional cost of receiving a cell phone notification", ("Stothart",), 2015, doi="10.1037/xhp0000100", source="openalex")])
    b = Fake("europepmc", [ref("The attentional cost of receiving a cell phone notification", ("Stothart", "Mitchum", "Yehnert"), 2015,
                               doi="10.1037/xhp0000100", abstract="Notifications alone disrupt", cited=900, source="europepmc")])
    got = MultiScholar([a, b]).resolve("The attentional cost", "10.1037/xhp0000100")
    assert len(got) == 1 and got[0].abstract == "Notifications alone disrupt" and got[0].cited_by == 900
    assert got[0].authors == ["Stothart", "Mitchum", "Yehnert"] and got[0].source == "openalex+europepmc"


# ---------------------------------------------------------------------------
# get_scholar — 쉼표 · all · S2 는 키가 있을 때만
# ---------------------------------------------------------------------------

def test_get_scholar_쉼표와_all(monkeypatch):
    monkeypatch.delenv("S2_API_KEY", raising=False)
    assert isinstance(get_scholar("openalex,arxiv"), MultiScholar) and get_scholar("openalex,arxiv").name == "openalex+arxiv"
    assert get_scholar("all").name == "openalex+arxiv+europepmc"            # 키 없이는 semanticscholar 를 안 끼운다
    monkeypatch.setenv("S2_API_KEY", "k")
    assert get_scholar("all").name == "openalex+arxiv+europepmc+semanticscholar"
    assert get_scholar("s2").name == "semanticscholar" and get_scholar("pubmed").name == "europepmc"
    assert get_scholar("openalex,openalex,nope").name == "openalex"        # 중복·모르는 이름은 한 번만·건너뛴다
    monkeypatch.setenv("SCHOLAR_PROVIDER", "arxiv,crossref")
    assert get_scholar().name == "arxiv+crossref"
