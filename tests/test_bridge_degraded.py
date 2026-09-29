"""
질문 재료의 폴백·캐시·동시성·요청 제한 (09-30 감사 WP-B) — 소켓 없이 핸들러를 직접 부른다.

- B-03: 규칙 주장·검색 실패 문헌·못 읽은 기억은 **폴백이라고 응답에 싣고**(degraded) 짧게만 든다 — 성공처럼 6시간 담지 않는다.
- B-11: 보관한 문헌은 같은 그래프로 만든 것만 다시 쓴다.
- G-A9·B-14/B-15: 문헌이 제한 시간 안에 안 오면 자료 인용만으로 간다 · 실패한 검색 통로는 잠시 쉰다.
- B-04·M-14: 트랙 둘을 동시에 미리 만들어도 주장·문헌·1차 심사는 한 번씩. 같은 덱을 새 세션으로 다시 올려도
  파싱·개념·그래프 캐시가 맞는다.
- B-05: 캐시 상한은 종류마다.   H-15: 요청 제한은 세션마다 + IP 천장, 429 에 기계용 표시.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import time
from email.message import Message

import pytest

import chuckchuck
import demo.bridge as bridge
from chuckchuck.contracts import ClaimDoc, PaperDoc, PaperRef, QaTriage, QuestionDoc
from demo.session_archive import SessionArchive
from demo.session_store import CACHE_KIND_CAPS, MAX_TRIAGE, SessionStore


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, sec: float) -> None:
        self.now += sec


class FakeHandler(bridge.Handler):
    def __init__(self, path: str = "/", *, headers: dict | None = None, body: bytes = b"") -> None:  # noqa: D107
        self.path = path
        self.headers = Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v
        if body and "Content-Length" not in (headers or {}):
            self.headers["Content-Length"] = str(len(body))
        self.rfile = io.BytesIO(body)
        self.client_address = ("127.0.0.1", 1)
        self.sent: list[tuple[int, dict]] = []
        self.wfile = io.BytesIO()
        self.request_version = "HTTP/1.1"
        self.command = "POST"

    def _json(self, code: int, payload: dict):
        self.sent.append((code, payload))


def post(path: str, payload: dict | bytes, ctype: str = "application/json") -> tuple[int, dict]:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
    h = FakeHandler(path, headers={"Content-Type": ctype}, body=raw)
    h.do_POST()
    return h.sent[-1]


GRAPH = {"file_name": "sleep.pdf", "total_slides": 2,
         "nodes": [{"id": "c1", "label": "수면 연속성", "slide_nos": [1], "weight": 1.0}]}
GRAPH2 = {**GRAPH, "nodes": [{"id": "v2-c1", "label": "수면 연속성", "slide_nos": [1], "weight": 1.0}]}
SLIDE_DOC = {"file_name": "sleep.pdf", "total_slides": 2, "slides": [
    {"slide_no": 1, "title": "연속성", "blocks": [{"category": "paragraph", "text": "카페인·음주가 수면 연속성을 끊는다"}]},
]}
DECK_REF = PaperRef(id="d01", kind="deck", title="Sleep continuity", slide_no=1)
SCHOLAR_REF = PaperRef(id="s01", kind="scholar", title="Caffeine and sleep", authors=["A"], year=2020)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """실 모드 · 임시 보관소(단계 캐시도 그 아래) · 가짜 시계의 메모리 저장소 · 요청 제한 끔 · 쉬는 통로 없음."""
    archive = SessionArchive(tmp_path / "data")
    clock = FakeClock()
    monkeypatch.setattr(bridge, "ARCHIVE", archive)
    monkeypatch.setattr(bridge, "STORE", SessionStore(clock=clock))
    monkeypatch.setattr(bridge, "STAGE_CACHE_ON", True)
    monkeypatch.setattr(bridge, "STAGE_CACHE_DIR", None)
    monkeypatch.setattr(bridge, "DEV_ROUTES", False)
    monkeypatch.setattr(bridge, "REQUIRE_ACCESS", False)
    monkeypatch.setattr(bridge, "_mock", lambda: False)
    monkeypatch.setattr(bridge.LIMITER, "allow", lambda key: True)
    monkeypatch.setattr(bridge, "_PAPERS_DOWN", {})
    monkeypatch.setenv("SCHOLAR_PROVIDER", "openalex")               # .env 와 무관하게 — 검색 통로가 켜진 실 모드
    return archive, clock


def open_session(archive: SessionArchive, *, slide_doc: dict | None = SLIDE_DOC, consent: bool = True) -> str:
    sid = archive.new_id()
    archive.open(sid, consent=consent, file_name="sleep.pdf", ext=".pdf", upload=b"%PDF-1.4 x",
                 sha256=hashlib.sha256(sid.encode()).hexdigest(), title="sleep", learner_id="brw_degr01")
    if slide_doc is not None:
        archive.put_artifact(sid, "slide_doc", {**slide_doc, "session_id": sid})
    bridge.STORE.put_artifacts(sid, {"graph": GRAPH, "context": {"situation": "school_project"}})
    return sid


@pytest.fixture
def f08(monkeypatch):
    """가짜 F-08 — 부른 횟수와 받은 재료를 센다."""
    seen: dict = {"triage": 0, "build": [], "papers": [], "claims": []}

    def triage(*a, **k):
        seen["triage"] += 1
        return QaTriage(file_name="sleep.pdf")

    def build(graph, tri, *, track, papers=None, claims=None, **_):
        seen["build"].append(track)
        seen["papers"].append(papers)
        seen["claims"].append(claims)
        return QuestionDoc(file_name="sleep.pdf", track=track, model="fake")

    monkeypatch.setattr(chuckchuck, "triage_questions", triage)
    monkeypatch.setattr(chuckchuck, "build_questions", build)
    return seen


def ask(sid: str, track: str = "10", **extra) -> tuple[int, dict]:
    return post("/api/v1/questions", {"session_id": sid, "graph": GRAPH, "alignment": None, "flow": None,
                                      "transcript": None, "context": {"situation": "school_project"},
                                      "track": track, **extra})


# ─── B-03 · 주장 ────────────────────────────────────────────────────────────────

def test_규칙_주장은_디스크에_안_남기고_짧게만_든다(env, monkeypatch):
    archive, clock = env
    calls: list[int] = []
    monkeypatch.setattr(chuckchuck, "build_claims",
                        lambda graph, slidedoc, *, llm=None, **_: calls.append(1) or ClaimDoc(file_name="s", model="rule"))
    h = FakeHandler()

    h._claims_for({}, GRAPH, SLIDE_DOC, None)
    h._claims_for({}, GRAPH, SLIDE_DOC, None)
    assert len(calls) == 1                                          # 미리 만들기 → 시작 한 쌍은 나눠 쓴다
    clock.advance(bridge.FALLBACK_TTL_SEC + 1)
    h._claims_for({}, GRAPH, SLIDE_DOC, None)
    assert len(calls) == 2                                          # 그 뒤엔 LLM 을 다시 불러 본다
    assert not list(archive.stage_dir.glob("claims-*.json"))


def test_LLM_주장은_디스크에_남고_오래_든다(env, monkeypatch):
    archive, clock = env
    calls: list[int] = []
    monkeypatch.setattr(chuckchuck, "build_claims",
                        lambda graph, slidedoc, *, llm=None, **_: calls.append(1) or ClaimDoc(file_name="s", model="solar"))
    h = FakeHandler()
    h._claims_for({}, GRAPH, SLIDE_DOC, None)
    clock.advance(bridge.FALLBACK_TTL_SEC + 1)
    h._claims_for({}, GRAPH, SLIDE_DOC, None)
    assert len(calls) == 1 and len(list(archive.stage_dir.glob("claims-*.json"))) == 1


def test_주장_캐시는_세션_표시가_붙은_본문도_같은_자료로_본다(env, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(chuckchuck, "build_claims",
                        lambda graph, slidedoc, *, llm=None, **_: calls.append(1) or ClaimDoc(file_name="s", model="solar"))
    monkeypatch.setattr(bridge, "STORE", SessionStore())
    FakeHandler()._claims_for({}, GRAPH, {**SLIDE_DOC, "session_id": "20260930T000000Z_aaaaaaaa"}, None)
    monkeypatch.setattr(bridge, "STORE", SessionStore())             # 메모리는 비고 디스크만 남았다
    FakeHandler()._claims_for({}, GRAPH, {**SLIDE_DOC, "session_id": "20260930T000001Z_bbbbbbbb",
                                          "preview_pdf": "/api/v1/preview-pdf?session_id=…"}, None)
    assert len(calls) == 1


# ─── B-03 · B-11 · B-14 · 문헌 ──────────────────────────────────────────────────

def test_검색이_실패한_문헌은_보관하지_않고_통로를_잠시_쉰다(env, monkeypatch):
    archive, _ = env
    sid = open_session(archive)
    calls: list = []

    def fake_papers(graph, slidedoc, *, scholar=None, llm=None, **_):
        calls.append(scholar)
        if scholar == "none":
            return PaperDoc(file_name="s", refs=[DECK_REF], provider="none", note="검색 꺼짐")
        return PaperDoc(file_name="s", refs=[DECK_REF], provider="openalex", note="openalex 검색 실패: 429 Too Many Requests")

    monkeypatch.setattr(chuckchuck, "build_papers", fake_papers)
    first = FakeHandler()._papers_for({"session_id": sid}, GRAPH, SLIDE_DOC, None)
    assert bridge._papers_degraded(first) == "papers_unavailable"
    assert archive.read_artifact(sid, "paper_doc") is None          # 보관본은 다음 요청이 그대로 다시 쓴다 — 남기지 않는다

    monkeypatch.setattr(bridge, "STORE", SessionStore())             # 메모리 캐시가 비어도
    second = FakeHandler()._papers_for({"session_id": sid}, GRAPH, SLIDE_DOC, None)
    assert calls == [None, "none"]                                  # 통로는 쉬고 자료 인용만 (LLM·네트워크 0)
    assert second.note == bridge.PAPERS_RESTING_NOTE and bridge._papers_degraded(second) == "papers_unavailable"


def test_일부만_실패한_문헌은_부분_폴백이고_통로는_쉬지_않는다(env, monkeypatch):
    archive, _ = env
    sid = open_session(archive)
    monkeypatch.setattr(chuckchuck, "build_papers", lambda *a, **k: PaperDoc(
        file_name="s", refs=[DECK_REF, SCHOLAR_REF], provider="arxiv", note="arxiv 검색 실패: 429"))
    got = FakeHandler()._papers_for({"session_id": sid}, GRAPH, SLIDE_DOC, None)
    assert bridge._papers_degraded(got) == "papers_partial"
    assert bridge._papers_down_left(bridge._papers_spec(None)) == 0 and archive.read_artifact(sid, "paper_doc") is None


def test_보관된_문헌은_같은_그래프로_만든_것만_다시_쓴다(env, monkeypatch):
    archive, _ = env
    sid = open_session(archive)
    calls: list = []
    monkeypatch.setattr(chuckchuck, "build_papers", lambda graph, *a, **k: calls.append(graph) or PaperDoc(
        file_name="s", refs=[DECK_REF, SCHOLAR_REF], provider="openalex", note=""))

    FakeHandler()._papers_for({"session_id": sid}, GRAPH, SLIDE_DOC, None)
    assert archive.read_artifact(sid, "paper_doc")[bridge.PAPERS_GRAPH_FP_KEY]
    monkeypatch.setattr(bridge, "STORE", SessionStore())
    FakeHandler()._papers_for({"session_id": sid}, GRAPH, SLIDE_DOC, None)
    assert len(calls) == 1                                          # 같은 그래프 — 보관본

    monkeypatch.setattr(bridge, "STORE", SessionStore())
    got = FakeHandler()._papers_for({"session_id": sid}, GRAPH2, SLIDE_DOC, None)
    assert len(calls) == 2 and got.refs[1].title == "Caffeine and sleep"   # 그래프가 바뀌었다 — 새로


def test_그래프_지문이_없는_옛_보관본은_다시_만든다(env, monkeypatch):
    archive, _ = env
    sid = open_session(archive)
    archive.put_artifact(sid, "paper_doc", PaperDoc(file_name="s", refs=[DECK_REF], provider="openalex").to_dict())
    calls: list = []
    monkeypatch.setattr(chuckchuck, "build_papers", lambda *a, **k: calls.append(1) or PaperDoc(
        file_name="s", refs=[DECK_REF], provider="openalex"))
    FakeHandler()._papers_for({"session_id": sid}, GRAPH, SLIDE_DOC, None)
    assert calls == [1]


# ─── B-03 · 질문 응답의 degraded ─────────────────────────────────────────────────

def test_폴백_재료로_만든_질문은_그렇다고_싣고_짧게만_든다(env, f08, monkeypatch):
    archive, clock = env
    sid = open_session(archive)
    monkeypatch.setattr(bridge.Handler, "_papers_for", lambda self, *a: PaperDoc(
        file_name="s", refs=[DECK_REF], provider="openalex", note="openalex 검색 실패: ReadTimeout"))
    monkeypatch.setattr(bridge.Handler, "_claims_for", lambda self, *a: ClaimDoc(file_name="s", model="rule"))

    code, first = ask(sid)
    assert code == 200 and first["degraded"] == ["claims_rule_only", "papers_unavailable"]
    assert len(first["degraded_notes"]) == 2 and all(first["degraded_notes"])
    assert ask(sid)[1] == first and f08["build"] == ["10"]           # 시작 버튼은 미리 만든 것을 그대로
    clock.advance(bridge.FALLBACK_TTL_SEC + 1)
    ask(sid)
    assert f08["build"] == ["10", "10"]                              # 그 뒤엔 재료부터 다시 시도한다


def test_폴백이_없으면_degraded_는_비고_오래_든다(env, f08, monkeypatch):
    archive, clock = env
    sid = open_session(archive)
    monkeypatch.setattr(bridge.Handler, "_papers_for", lambda self, *a: PaperDoc(
        file_name="s", refs=[DECK_REF, SCHOLAR_REF], provider="openalex"))
    monkeypatch.setattr(bridge.Handler, "_claims_for", lambda self, *a: ClaimDoc(file_name="s", model="solar"))

    code, body = ask(sid)
    assert code == 200 and body["degraded"] == [] and body["degraded_notes"] == []
    clock.advance(bridge.FALLBACK_TTL_SEC + 1)
    ask(sid)
    assert f08["build"] == ["10"]


def test_자료_본문이_없으면_표시하되_짧게_들지는_않는다(env, f08, monkeypatch):
    archive, clock = env
    sid = open_session(archive, slide_doc=None)
    monkeypatch.setattr(bridge.Handler, "_papers_for", lambda self, *a: PaperDoc(file_name="s", provider="openalex"))
    claims_calls: list = []
    monkeypatch.setattr(bridge.Handler, "_claims_for", lambda self, *a: claims_calls.append(1))

    code, body = ask(sid)
    assert code == 200 and body["degraded"] == ["slide_doc_missing"] and claims_calls == []
    clock.advance(bridge.FALLBACK_TTL_SEC + 1)
    ask(sid)
    assert f08["build"] == ["10"]                                    # 다시 해도 본문은 안 생긴다 — LLM 을 또 안 부른다


def test_기억을_못_읽으면_질문은_나오고_degraded_에_남는다(env, f08, monkeypatch):
    archive, clock = env
    sid = open_session(archive)
    monkeypatch.setattr(bridge.Handler, "_papers_for", lambda self, *a: PaperDoc(file_name="s", provider="openalex"))
    monkeypatch.setattr(bridge.Handler, "_claims_for", lambda self, *a: ClaimDoc(file_name="s", model="solar"))
    reads: list = []

    def broken(_sid):
        reads.append(1)
        raise OSError("manifest 읽기 실패")

    monkeypatch.setattr(archive, "rehearsals_for", broken)
    code, body = ask(sid)
    assert code == 200 and body["degraded"] == ["memory_failed"]
    FakeHandler()._memory_for({"session_id": sid})
    assert reads == [1]                                              # 방금 실패 — 짧게는 다시 안 읽는다
    clock.advance(bridge.FALLBACK_TTL_SEC + 1)
    FakeHandler()._memory_for({"session_id": sid})
    assert reads == [1, 1]


def test_끈_재료는_폴백이_아니다(env, f08):
    archive, _ = env
    sid = open_session(archive)
    code, body = ask(sid, papers=False, claims=False, memory=False)
    assert code == 200 and body["degraded"] == []


# ─── G-A9 · 문헌 제한 시간 ──────────────────────────────────────────────────────

def test_문헌이_늦으면_기다리지_않고_자료_인용만으로_간다(env, f08, monkeypatch):
    archive, _ = env
    sid = open_session(archive)
    monkeypatch.setattr(bridge, "PAPERS_DEADLINE_SEC", 0.2)
    finished = threading.Event()

    def slow(self, body, graph_raw, slidedoc, llm):
        time.sleep(1.0)                                              # 막힌 학술 검색 (실측 ~60초)
        finished.set()
        return PaperDoc(file_name="s", refs=[DECK_REF, SCHOLAR_REF], provider="openalex")

    monkeypatch.setattr(bridge.Handler, "_papers_for", slow)
    t0 = time.monotonic()
    code, body = ask(sid, claims=False)
    took = time.monotonic() - t0

    assert code == 200 and took < 0.8, took
    assert body["degraded"] == ["papers_timeout"]
    fallback = f08["papers"][0]
    assert fallback is not None and fallback.note == bridge.PAPERS_TIMEOUT_NOTE and fallback.provider == "none"
    assert finished.wait(3)                                          # 검색은 뒤에서 끝까지 한다
    deadline = time.monotonic() + 2
    while bridge._FLIGHTS.busy() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not bridge._FLIGHTS.busy()


def test_주장이_더_오래_걸리면_문헌은_그만큼_더_기다린다(env, f08, monkeypatch):
    archive, _ = env
    sid = open_session(archive)
    monkeypatch.setattr(bridge, "PAPERS_DEADLINE_SEC", 0.1)

    def papers(self, *a):
        time.sleep(0.3)
        return PaperDoc(file_name="s", refs=[DECK_REF, SCHOLAR_REF], provider="openalex")

    def claims(self, *a):
        time.sleep(0.6)                                              # 주장 LLM 이 문헌보다 느리다 — 같이 돌렸으니 문헌은 이미 왔다
        return ClaimDoc(file_name="s", model="solar")

    monkeypatch.setattr(bridge.Handler, "_papers_for", papers)
    monkeypatch.setattr(bridge.Handler, "_claims_for", claims)
    t0 = time.monotonic()
    code, body = ask(sid)
    assert code == 200 and body["degraded"] == [] and f08["papers"][0].provider == "openalex"
    assert time.monotonic() - t0 < 0.85                             # 문헌 0.3 + 주장 0.6 을 차례로 했으면 0.9 넘는다


# ─── B-04 · M-14 · 트랙끼리 재료 나누기 ─────────────────────────────────────────

def test_두_트랙을_동시에_미리_만들어도_주장_문헌_1차_심사는_한_번씩(env, monkeypatch):
    archive, _ = env
    sid = open_session(archive)
    n = {"claims": 0, "papers": 0, "triage": 0, "build": 0}
    started = threading.Event()

    def claims(graph, slidedoc, *, llm=None, **_):
        n["claims"] += 1
        started.set()
        time.sleep(0.4)
        return ClaimDoc(file_name="s", model="solar")

    def papers(graph, slidedoc, *, scholar=None, llm=None, **_):
        n["papers"] += 1
        time.sleep(0.4)
        return PaperDoc(file_name="s", refs=[DECK_REF, SCHOLAR_REF], provider="openalex")

    def triage(*a, **k):
        n["triage"] += 1
        time.sleep(0.3)
        return QaTriage(file_name="s")

    def build(graph, tri, *, track, **_):
        n["build"] += 1
        return QuestionDoc(file_name="s", track=track, model="fake")

    monkeypatch.setattr(chuckchuck, "build_claims", claims)
    monkeypatch.setattr(chuckchuck, "build_papers", papers)
    monkeypatch.setattr(chuckchuck, "triage_questions", triage)
    monkeypatch.setattr(chuckchuck, "build_questions", build)
    monkeypatch.setattr(bridge, "PAPERS_DEADLINE_SEC", 5.0)

    results: list = []
    ten = threading.Thread(target=lambda: results.append(ask(sid, "10", prefetch=True)))
    ten.start()
    assert started.wait(3)                                           # 10분 트랙이 주장을 만드는 중에
    five = threading.Thread(target=lambda: results.append(ask(sid, "5", prefetch=True)))
    five.start()
    ten.join(5)
    five.join(5)

    assert [r[0] for r in results] == [200, 200]
    assert (n["claims"], n["papers"], n["triage"], n["build"]) == (1, 1, 1, 2)


def test_트랙을_차례로_바꿔도_마지막_질문_만들기만_다시_한다(env, monkeypatch):
    archive, _ = env
    sid = open_session(archive)
    n = {"claims": 0, "papers": 0, "triage": 0, "build": 0}
    monkeypatch.setattr(chuckchuck, "build_claims",
                        lambda *a, **k: n.__setitem__("claims", n["claims"] + 1) or ClaimDoc(file_name="s", model="solar"))
    monkeypatch.setattr(chuckchuck, "build_papers", lambda *a, **k: n.__setitem__("papers", n["papers"] + 1) or PaperDoc(
        file_name="s", refs=[DECK_REF, SCHOLAR_REF], provider="openalex"))
    monkeypatch.setattr(chuckchuck, "triage_questions",
                        lambda *a, **k: n.__setitem__("triage", n["triage"] + 1) or QaTriage(file_name="s"))
    monkeypatch.setattr(chuckchuck, "build_questions", lambda graph, tri, *, track, **_: n.__setitem__(
        "build", n["build"] + 1) or QuestionDoc(file_name="s", track=track, model="fake"))

    for track in ("10", "5", "1"):
        assert ask(sid, track)[0] == 200
    assert n == {"claims": 1, "papers": 1, "triage": 1, "build": 3}


# ─── M-14 · 같은 덱 다시 올리기 ──────────────────────────────────────────────────

class _Result:
    model = "fake"
    nodes, edges, sections = [], [], []

    def to_dict(self):
        return {"file_name": "sleep.pdf", "total_slides": 2, "slides": [], "nodes": [], "edges": []}


def test_같은_덱을_새_세션으로_다시_올려도_개념_그래프_캐시가_맞는다(env, monkeypatch):
    calls = {"concepts": 0, "graph": 0}
    monkeypatch.setattr(bridge, "extract_concepts", lambda *a, **k: calls.__setitem__("concepts", calls["concepts"] + 1) or _Result())
    monkeypatch.setattr(bridge, "build_graph", lambda *a, **k: calls.__setitem__("graph", calls["graph"] + 1) or _Result())
    concept_doc = {"file_name": "sleep.pdf", "total_slides": 2, "slides": []}
    for sid in ("20260930T010101Z_aaaaaaaa", "20260930T020202Z_bbbbbbbb"):
        # /parse 응답 그대로 — 세션마다 다른 표시가 붙어 있다
        slide_doc = {**SLIDE_DOC, "session_id": sid, "consent_learning": False,
                     "preview_pdf": f"/api/v1/preview-pdf?session_id={sid}"}
        assert post("/api/v1/concepts", {"session_id": sid, "slide_doc": slide_doc, "context": {"situation": "x"},
                                         "transcript": None})[0] == 200
        assert post("/api/v1/graph", {"session_id": sid, "concept_doc": concept_doc, "slide_doc": slide_doc,
                                      "context": {"situation": "x"}})[0] == 200
    assert calls == {"concepts": 1, "graph": 1}


def _multipart(filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = "XBOUNDARYX"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def test_같은_파일을_다시_올리면_파서를_다시_안_부른다(env, monkeypatch):
    from chuckchuck.contracts import SlideDoc

    parsed: list[str] = []
    monkeypatch.setattr(bridge, "parse_document", lambda path: parsed.append(path) or SlideDoc.from_dict(SLIDE_DOC))
    pdf = b"%PDF-1.4\n% sleep deck\n"

    body, ctype = _multipart("sleep.pdf", pdf)
    first = post("/api/v1/parse", body, ctype)
    body, ctype = _multipart("다시 올린 sleep.pdf", pdf)
    second = post("/api/v1/parse", body, ctype)
    body, ctype = _multipart("sleep.pdf", pdf + b"% one byte differs\n")          # 한 바이트라도 다르면 다른 키
    post("/api/v1/parse", body, ctype)

    assert first[0] == second[0] == 200 and len(parsed) == 2
    assert first[1]["session_id"] != second[1]["session_id"]
    assert second[1]["file_name"] == "다시 올린 sleep.pdf" and second[1]["slides"] == first[1]["slides"]


# ─── B-05 · 종류별 상한 ─────────────────────────────────────────────────────────

def test_캐시_상한은_종류마다_따로_센다():
    clock = FakeClock()
    store = SessionStore(clock=clock)
    store.set_triage("pace:s1", {"slides": []})
    store.set_triage("memory:s1", {})
    for i in range(200):
        clock.advance(1)
        store.set_triage(f"questions:{i}", {"i": i})
    for i in range(50):
        clock.advance(1)
        store.set_triage(f"fp{i}", {"marks": []})

    assert store.get_triage("pace:s1") == {"slides": []} and store.get_triage("memory:s1") == {}
    kinds = [k.partition(":")[0] if ":" in k else "triage" for k in store._triage]
    assert kinds.count("questions") == CACHE_KIND_CAPS["questions"] and kinds.count("triage") == MAX_TRIAGE
    assert store.get_triage("questions:199") == {"i": 199} and store.get_triage("questions:0") is None


def test_짧게_담은_항목은_자주_써도_늘어나지_않는다():
    clock = FakeClock()
    store = SessionStore(clock=clock)
    store.set_triage("questions:x", {"q": 1}, ttl=100)
    for _ in range(3):
        clock.advance(30)
        assert store.get_triage("questions:x") == {"q": 1}
    clock.advance(30)
    assert store.get_triage("questions:x") is None


def test_질문_색인은_최근_트랙부터_찾고_세션을_지우면_같이_지운다():
    store = SessionStore()
    store.remember_questions("s1", "10", {"questions": [{"id": "q1", "question": "10분 판"}]})
    store.remember_questions("s1", "5", {"questions": [{"id": "q1", "question": "5분 판"}]})
    store.remember_questions("s1", "10", {"questions": [{"id": "q1", "question": "10분 새 판"}]})
    assert [q["question"] for q in store.find_questions("s1", "q1")] == ["10분 새 판", "5분 판"]
    store.forget("s1")
    assert store.find_questions("s1", "q1") == []


def test_질문_색인은_세션_등록과_따로_센다():
    store = SessionStore(max_sessions=1, max_question_index=2)
    for sid in ("a", "b", "c"):
        store.remember_questions(sid, "10", {"questions": [{"id": "q1", "question": sid}]})
    assert store.find_questions("a", "q1") == [] and store.find_questions("c", "q1")[0]["question"] == "c"
    assert store.artifacts("c") == {}                                # 세션 자리는 안 먹는다


# ─── H-15 · 요청 제한은 세션마다 ────────────────────────────────────────────────

def test_요청_제한은_세션마다_세고_IP_에는_넉넉한_천장만(env, monkeypatch):
    archive, _ = env
    monkeypatch.setattr(bridge, "LIMITER", bridge.PaidLimiter(limit=2, ip_limit=5))
    s1, s2, s3 = (open_session(archive) for _ in range(3))

    assert [post("/api/v1/memory", {"session_id": s1})[0] for _ in range(2)] == [200, 200]
    code, body = post("/api/v1/memory", {"session_id": s1})
    assert code == 429 and body["scope"] == "session"                # s1 만 막혔다
    assert [post("/api/v1/memory", {"session_id": s2})[0] for _ in range(2)] == [200, 200]
    code, body = post("/api/v1/memory", {"session_id": s3})
    assert code == 429 and body["scope"] == "ip"                     # 같은 IP 전체 천장(5)

    assert body["error"] == "rate_limited" and body["rate_limited"] is True
    assert isinstance(body["retry_after"], int) and body["retry_after"] > 0 and "초 뒤에" in body["message"]


def test_세션이_없거나_flat_이면_IP_칸으로_센다(env, monkeypatch):
    monkeypatch.setattr(bridge, "LIMITER", bridge.PaidLimiter(limit=2, ip_limit=100))
    monkeypatch.setattr(bridge.Handler, "_handle_papers_search", lambda self, raw: self._json(200, {"refs": []}))
    codes = [post("/api/v1/papers/search", {"query": "sleep"})[0],
             post("/api/v1/papers/search", {"query": "sleep", "session_id": "flat"})[0],
             post("/api/v1/papers/search", {"query": "sleep", "session_id": "evil-id"})[0]]
    assert codes == [200, 200, 429]


def test_판정_경로는_본문이_없어도_경로의_세션으로_센다(env, monkeypatch):
    archive, _ = env
    sid = open_session(archive)
    h = FakeHandler(f"/api/v1/sessions/{sid}/qa/judge")
    assert h._rate_bucket(f"/api/v1/sessions/{sid}/qa/judge", b"not json") == "session:" + sid
    assert h._rate_bucket("/api/v1/parse", json.dumps({"session_id": sid}).encode()) == "client:127.0.0.1"


def test_큰_녹음_본문은_다_풀지_않고_세션_칸을_찾는다(env, monkeypatch):
    archive, _ = env
    sid = open_session(archive)
    raw = json.dumps({"audio_base64": "A" * (bridge.JSON_BODY_MAX + 10), "session_id": sid}).encode()
    monkeypatch.setattr(bridge.json, "loads", lambda *a, **k: pytest.fail("큰 본문을 통째로 풀었다"))
    assert FakeHandler()._rate_bucket("/api/v1/transcribe", raw) == "session:" + sid
