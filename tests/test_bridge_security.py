"""
브리지 보안 점검(2026-09-23) 회귀 — 소켓 없이 핸들러를 직접 부른다.

- transcribe 는 서버 파일 경로(audio_path)를 받지 않는다 (CRITICAL)
- 실 API 모드에서 본문의 llm/provider 는 무시된다 (mock 포함). DEMO_DEV_ROUTES 에서만 허용 목록
- /api/v1/memory 응답에 남의 session_id 가 없고, 같은 파일만으로는 남의 기록을 잇지 않는다
- 과금 상한: 경로별 본문 상한(413) · JSON 필수(415) · PDF 장수 사전 검사 · 판정 입력 길이
- 노출: 실 모드 비루프백 DEMO_HOST 는 시작 거부 · Access 필수 모드 · Host 허용 목록 · 디렉터리 목록 끔
- 오류 응답에 서버 경로·벤더 본문이 실리지 않는다 · 키는 길이만 찍는다
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from dataclasses import replace
from email.message import Message
from pathlib import Path

import pytest

import demo.bridge as bridge
from chuckchuck.contracts import ParseError, STTError
from demo.session_archive import SessionArchive
from demo.session_store import SessionStore


class FakeHandler(bridge.Handler):
    """소켓 없이 응답만 잡는다. body 를 주면 do_POST 가 읽을 rfile 과 Content-Length 를 채운다."""

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
        self.errors: list[int] = []
        self.status: int | None = None
        self.wfile = io.BytesIO()
        self.request_version = "HTTP/1.1"
        self.command = "GET"

    def _json(self, code: int, payload: dict):
        self.sent.append((code, payload))

    def send_error(self, code, message=None, explain=None):
        self.errors.append(code)

    def send_response(self, code, message=None):
        self.status = code

    def send_header(self, k, v):
        pass

    def end_headers(self):
        pass

    @property
    def last(self) -> tuple[int, dict]:
        return self.sent[-1]


JSON = {"Content-Type": "application/json"}


def _post(path: str, payload: dict | bytes, headers: dict | None = None) -> FakeHandler:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    h = FakeHandler(path, headers={**JSON, **(headers or {})}, body=raw)
    h.do_POST()
    return h


@pytest.fixture
def real(tmp_path, monkeypatch) -> SessionArchive:
    """실 API 모드 · 개발 경로 닫힘 · 빈 보관소."""
    a = SessionArchive(tmp_path / "data")
    monkeypatch.setattr(bridge, "ARCHIVE", a)
    monkeypatch.setattr(bridge, "STORE", SessionStore())
    monkeypatch.setattr(bridge, "DEV_ROUTES", False)
    monkeypatch.setattr(bridge, "REQUIRE_ACCESS", False)
    monkeypatch.setattr(bridge, "_mock", lambda: False)
    monkeypatch.setattr(bridge.LIMITER, "allow", lambda key: True)
    return a


# ─── 1. transcribe: 서버 경로를 받지 않는다 ───────────────────────────────────

def test_transcribe_에_audio_path_를_보내면_400_이고_STT_를_부르지_않는다(real, monkeypatch):
    called = []
    monkeypatch.setattr(bridge, "transcribe", lambda *a, **k: called.append(a))
    h = _post("/api/v1/transcribe", {"audio_path": "/home/someone/.env", "marks": []})
    code, body = h.last
    assert code == 400 and body["error"] == "audio_path_unsupported"
    assert ".env" not in json.dumps(body, ensure_ascii=False)
    assert called == []


def test_transcribe_는_base64_와_audio_path_를_같이_보내도_거절한다(real, monkeypatch):
    monkeypatch.setattr(bridge, "transcribe", lambda *a, **k: pytest.fail("STT 가 불렸다"))
    h = _post("/api/v1/transcribe", {"audio_base64": base64.b64encode(b"x" * 10).decode(),
                                      "audio_path": "/etc/passwd"})
    assert h.last[0] == 400


def test_transcribe_는_실_모드에서_본문_provider_를_무시한다(real, monkeypatch):
    seen = {}

    def fake(path, marks, provider=None):
        seen["provider"] = provider
        seen["path"] = path
        raise STTError("A.X STT upload 실패 500: 벤더 본문 /srv/secret")

    monkeypatch.setattr(bridge, "transcribe", fake)
    h = _post("/api/v1/transcribe", {"audio_base64": base64.b64encode(b"abc").decode(), "provider": "mock"})
    assert seen["provider"] is None                       # → STT_PROVIDER 환경변수
    assert not Path(seen["path"]).exists()                # 임시 파일은 지웠다
    code, body = h.last
    assert code == 502 and "/srv/secret" not in body["message"] and "벤더" not in body["message"]


def test_AxSTT_의_파일_없음_오류에_경로가_없다(monkeypatch):
    from chuckchuck.providers.stt_impl import AxSTT

    stt = AxSTT.__new__(AxSTT)
    with pytest.raises(STTError) as ei:
        stt.transcribe("/nonexistent/secret/dir/file.wav")
    assert "secret" not in str(ei.value)


# ─── 2. 모델 선택: 실 모드에서는 환경변수만 ────────────────────────────────────

@pytest.mark.parametrize("value", ["exaone", "mock", "solar+exaone", "evil", None, 3])
def test_실_모드에서_본문_llm_은_무시된다(real, value):
    assert bridge._pick_llm({"llm": value}) is None


def test_mock_모드에서는_llm_이_mock_으로_고정된다(real, monkeypatch):
    monkeypatch.setattr(bridge, "_mock", lambda: True)
    assert bridge._pick_llm({"llm": "exaone"}) == "mock"
    assert bridge._pick_stt_provider({"provider": "skt-ax"}) == "mock"


def test_DEV_ROUTES_에서만_허용_목록의_llm_을_받는다(real, monkeypatch):
    monkeypatch.setattr(bridge, "DEV_ROUTES", True)
    assert bridge._pick_llm({"llm": "exaone"}) == "exaone"
    assert bridge._pick_llm({"llm": "solar+ax"}) == "solar+ax"
    assert bridge._pick_llm({"llm": "mock"}) is None       # mock 은 실 모드 산출물을 오염시킨다
    assert bridge._pick_llm({"llm": "solar+mock"}) is None
    assert bridge._pick_stt_provider({"provider": "mock"}) is None
    assert bridge._pick_habit_provider({"provider": "heuristic"}) == "heuristic"


def test_concepts_경로가_본문_llm_을_모듈에_넘기지_않는다(real, monkeypatch):
    seen = {}

    class Result:
        model = "x"

        def to_dict(self):
            return {"concepts": []}

    def fake(doc, ctx, transcript=None, llm=None):
        seen["llm"] = llm
        return Result()

    monkeypatch.setattr(bridge, "extract_concepts", fake)
    monkeypatch.setattr(bridge, "STAGE_CACHE_ON", False)
    slide_doc = {"file_name": "a.pdf", "total_slides": 1, "slides": [{"slide_no": 1, "blocks": []}]}
    h = _post("/api/v1/concepts", {"slide_doc": slide_doc, "llm": "exaone"})
    assert h.last[0] == 200 and seen["llm"] is None


def test_habits_경로가_실_모드에서_본문_provider_를_무시한다(real, monkeypatch):
    seen = {}

    class Doc:
        repeat_cnt = filler_cnt = pause_cnt = 0
        provider = "heuristic"

        def to_dict(self):
            return {}

    def fake(transcript, provider=None, spans=None):
        seen["provider"] = provider
        return Doc()

    monkeypatch.setattr(bridge, "extract_habits", fake)
    _post("/api/v1/habits", {"transcript": {"by_slide": []}, "provider": "fixture"})
    assert seen["provider"] is None


# ─── 3. memory: 남의 session_id 가 응답에 없다 ────────────────────────────────

def _open(a: SessionArchive, *, consent: bool, learner: str, upload: bytes = b"%PDF-1.4 booth sample") -> str:
    sid = a.new_id()
    a.open(sid, consent=consent, file_name="샘플.pdf", ext=".pdf", upload=upload,
           sha256=hashlib.sha256(upload).hexdigest(), title="샘플", learner_id=learner)
    return sid


def _turn(qid: str, label: str) -> dict:
    return {"at": 1.0, "question_id": qid, "give_up": False, "hints_shown": [],
            "question": {"id": qid, "node_id": "n1", "label": label, "question": f"{label}?"},
            "answer": "…", "prior_answers": [],
            "judgement": {"verdict": "partial", "score": 40, "missing_points": ["근거"], "coach_stage": ""}}


def test_memory_응답에_지난_세션의_진짜_session_id_가_없다(real):
    mine = _open(real, consent=True, learner="brw_mine1")
    real.append(mine, "qa_turns", _turn("q01-a", "알림 비용"))
    now = _open(real, consent=True, learner="brw_mine1")
    h = _post("/api/v1/memory", {"session_id": now})
    code, body = h.last
    assert code == 200 and len(body["sessions"]) == 1
    text = json.dumps(body, ensure_ascii=False)
    assert mine not in text and body["sessions"][0]["session_id"].startswith("past-")


def test_memory_는_같은_파일이어도_남의_기록을_잇지_않는다(real):
    other = _open(real, consent=True, learner="brw_other")
    real.append(other, "qa_turns", _turn("q01-a", "알림 비용"))
    me = _open(real, consent=True, learner="brw_mine1")        # 부스: 같은 샘플 자료
    h = _post("/api/v1/memory", {"session_id": me})
    code, body = h.last
    assert code == 200 and body["sessions"] == [] and other not in json.dumps(body)


def test_memory_는_요청_세션이_동의하지_않았으면_잇지_않는다(real):
    past = _open(real, consent=True, learner="brw_mine1")
    real.append(past, "qa_turns", _turn("q01-a", "알림 비용"))
    me = _open(real, consent=False, learner="brw_mine1")
    rows, key = real.related_sessions(me)
    assert rows == [] and key == ""


# ─── 4. 과금 상한 ────────────────────────────────────────────────────────────

def test_JSON_경로에_큰_본문을_보내면_413(real):
    h = FakeHandler("/api/v1/memory", headers={**JSON, "Content-Length": str(bridge.JSON_BODY_MAX + 1)})
    h.do_POST()
    assert h.last[0] == 413


def test_묶음_경로도_상한이_있고_녹음_경로는_30MB_기준이다():
    assert bridge._body_limit("/api/v1/rubric") == bridge.JSON_BODY_MAX_BUNDLE < bridge.MAX_BODY_BYTES
    assert bridge._body_limit("/api/v1/sessions/x/qa/judge") == bridge.JSON_BODY_MAX_BUNDLE
    assert bridge._body_limit("/api/v1/transcribe") == bridge.MAX_BODY_BYTES
    assert bridge._body_limit("/api/v1/papers/search") == bridge.JSON_BODY_MAX


def test_JSON_경로는_Content_Type_이_json_이어야_한다(real):
    h = FakeHandler("/api/v1/memory", headers={"Content-Type": "text/plain"}, body=b'{"session_id":"x"}')
    h.do_POST()
    assert h.last == (415, h.last[1]) and h.last[1]["error"] == "json_required"


def _pdf(pages: int) -> bytes:
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_장수가_많은_PDF_는_Upstage_에_보내기_전에_413(real, monkeypatch):
    monkeypatch.setattr(bridge, "parse_document", lambda *a, **k: pytest.fail("파싱(과금)이 불렸다"))
    monkeypatch.setattr(bridge, "_max_slides", lambda: 3)
    data = _pdf(5)
    boundary = "XyZ"
    raw = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"big.pdf\"\r\n"
           f"Content-Type: application/pdf\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    h = FakeHandler("/api/v1/parse", headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, body=raw)
    h.do_POST()
    code, body = h.last
    assert code == 413 and body["error"] == "too_many_pages" and "5장" in body["message"]


def test_장수_세기는_pypdf_와_pptx_와_근사치를_쓴다(monkeypatch):
    assert bridge._count_pages(_pdf(4), ".pdf") == 4
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ppt/presentation.xml", "<p/>")
        for i in range(1, 8):
            z.writestr(f"ppt/slides/slide{i}.xml", "<s/>")
        z.writestr("ppt/slides/_rels/slide1.xml.rels", "<r/>")
    assert bridge._count_pages(buf.getvalue(), ".pptx") == 7
    assert bridge._count_pages(b"not a pdf", ".png") is None


def test_판정_답변이_너무_길면_413_이고_LLM_을_부르지_않는다(real, monkeypatch):
    monkeypatch.setattr("chuckchuck.judge_answer", lambda *a, **k: pytest.fail("판정 LLM 이 불렸다"))
    h = _post("/api/v1/qa/judge", {"question": {"id": "q1", "question": "왜요?"},
                                   "answer": "가" * (bridge.ANSWER_MAX_CHARS + 1)})
    assert h.last[0] == 413


def test_판정_기록은_거절하지_않고_오래된_것부터_자른다():
    history = [{"질문": f"q{i}", "답변": "a" * 50, "판정": "partial"} for i in range(100)]
    body, err = bridge._clip_judge_inputs({"answer": "ok", "history": history,
                                           "prior_answers": ["x"] * 30, "hints_shown": ["h"] * 30})
    assert err == ""
    assert len(body["history"]) == bridge.HISTORY_MAX_ITEMS and body["history"][-1]["질문"] == "q99"
    assert len(body["prior_answers"]) == bridge.PRIOR_ANSWERS_MAX
    assert len(body["hints_shown"]) == bridge.PRIOR_ANSWERS_MAX
    assert len(history) == 100                                    # 원본은 건드리지 않는다


def test_session_artifacts_는_발급한_모양의_id_만_받는다(real):
    h = _post("/api/v1/session/artifacts", {"session_id": "evil\nfake-log-line", "graph": {}})
    assert h.last[0] == 400


# ─── 5. 노출 ─────────────────────────────────────────────────────────────────

def test_실_모드에서_비루프백_DEMO_HOST_는_시작을_거부한다(monkeypatch):
    assert bridge.bind_refusal("0.0.0.0", mock=False)
    assert bridge.bind_refusal("192.168.0.10", mock=False)
    assert bridge.bind_refusal("127.0.0.1", mock=False) == ""
    assert bridge.bind_refusal("0.0.0.0", mock=True) == ""
    monkeypatch.setattr(bridge, "settings", replace(bridge.settings, demo_host="0.0.0.0"))
    monkeypatch.setattr(bridge, "_mock", lambda: False)
    monkeypatch.setattr(bridge, "ReusableThreadingHTTPServer", lambda *a, **k: pytest.fail("소켓을 열었다"))
    with pytest.raises(SystemExit):
        bridge.main()


def test_Access_필수_모드는_헤더_없는_요청을_정적_파일까지_403(real, monkeypatch):
    monkeypatch.setattr(bridge, "REQUIRE_ACCESS", True)
    h = FakeHandler("/index.html")
    h.do_GET()
    assert h.last[0] == 403 and h.last[1]["error"] == "access_required"
    h = FakeHandler("/api/v1/memory", headers=JSON, body=b"{}")
    h.do_POST()
    assert h.last[0] == 403
    h = FakeHandler("/api/health", headers={"Cf-Access-Jwt-Assertion": "eyJ.x.y"})
    h.do_GET()
    assert h.last[0] == 200


def test_Host_허용_목록_밖이면_403(real, monkeypatch):
    monkeypatch.setattr(bridge, "settings", replace(bridge.settings, demo_host="127.0.0.1"))
    h = FakeHandler("/api/health", headers={"Host": "evil.example:8799"})
    h.do_GET()
    assert h.last[0] == 403 and h.last[1]["error"] == "forbidden_host"
    for ok in ("127.0.0.1:8799", "localhost:8799", "[::1]:8799"):
        h = FakeHandler("/api/health", headers={"Host": ok})
        h.do_GET()
        assert h.last[0] == 200, ok


def test_정적_서빙의_디렉터리_목록은_404():
    h = FakeHandler("/")
    assert h.list_directory(str(bridge.DEMO_DIR)) is None and h.errors == [404]


# ─── 6. 오류 문구 · 키 표시 ───────────────────────────────────────────────────

def test_500_문구는_사용자가_고칠_수_있는_파서_오류만_싣고_경로는_뗀다():
    assert bridge._public_message(ParseError("120장입니다. 현재 100장까지 지원합니다. (raw 저장: /srv/x)")) \
        == "120장입니다. 현재 100장까지 지원합니다."
    assert bridge._public_message(ParseError("Document Parse 오류 500: {vendor body}")) == bridge.GENERIC_ERROR_MESSAGE
    assert bridge._public_message(RuntimeError("/home/x/secret")) == bridge.GENERIC_ERROR_MESSAGE


def test_키는_앞뒤_글자_없이_길이만_찍는다():
    from chuckchuck.config import Settings

    # 가짜 키를 문자 그대로 적으면 scripts/chk gate 의 비밀키 검사(up_ + 16자)에 걸린다 — 이어 붙여 만든다
    fake_key = "up_" + "ABCDEFGHIJKLMNOP1234"
    s = replace(Settings.load(), upstage_api_key=fake_key)
    out = s.masked()
    assert "up_ABC" not in out and "1234" not in out and "설정됨(길이 23)" in out
