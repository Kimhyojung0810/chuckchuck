"""
국내 AI API 호출 로그(main/pipeline/_ai_calllog.py) — 설계 §8.

가짜 HTTP 응답(requests.Session.send 바꿔치기)으로:
- 레코드 필드가 다 있고 시각이 +09:00 이다 · 헤더(Authorization · 키)는 파일 어디에도 없다
- 재시도하면 attempt 2 · multipart · 파일 본문은 지문(sha256)으로만 남는다
- 스레드풀 안에서 부른 호출도 기능 코드가 맞다(F-06 · F-14 · F-12 · F-07) — 요청 범위가 일꾼으로 따라간다
- team 모드에서 팀이 아닌 요청은 0건 · 해외 AI 호스트로 가면 경고
- 내보내기(etc/scripts/ai_calllog_export.py): 기능 수만큼 파일 · 파일명 = 기능 표 · 마스킹해도 구조 그대로
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from pipeline import _ai_calllog as AC
from pipeline.providers.llm_base import LLMProvider

ROOT = Path(__file__).resolve().parents[2]
FAKE_KEY = "up" + "_" + "FAKEKEY0123456789abcdefABCDEF"   # 문지기 키 검사에 안 걸리게 이어 붙인다 (가짜 값)
UPSTAGE = "https://api.upstage.ai/v1"
CFG = SimpleNamespace(
    docparse_url="https://api.upstage.ai/v1/document-digitization",
    docparse_async_url="https://api.upstage.ai/v1/document-digitization/async",
    solar_base_url=UPSTAGE, ax_base_url="https://awf-gw.adot.ai/v1", ax_stt_base_url="https://awf-gw.adot.ai",
    midm_base_url="https://midm.kt.com/v1", exaone_base_url="https://api.friendli.ai/dedicated/v1",
)


class FakeNet:
    """requests.Session.send 자리. plan 의 앞에서부터 (status, body) 또는 예외를 하나씩 쓴다. 다 쓰면 마지막 것을 되풀이."""

    def __init__(self, *plan):
        self.plan = list(plan) or [(200, {"id": "x", "model": "solar-pro3", "choices": [], "usage": {"total_tokens": 3}})]
        self.sent = []
        self.lock = threading.Lock()

    def __call__(self, session, request, **kw):
        with self.lock:
            self.sent.append(request)
            step = self.plan.pop(0) if len(self.plan) > 1 else self.plan[0]
        if isinstance(step, Exception):
            raise step
        status, body = step
        r = requests.Response()
        r.status_code = status
        r._content = body if isinstance(body, bytes) else json.dumps(body).encode()
        r.url = request.url
        r.request = request
        return r


@pytest.fixture
def net(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_CALLLOG_DIR", str(tmp_path / "log"))
    monkeypatch.setenv("AI_CALLLOG", "all")
    fake = FakeNet()
    monkeypatch.setattr(requests.Session, "send", fake)
    AC.install(CFG)
    AC._SCOPE.set(None)
    AC.FOREIGN_SEEN.clear()
    yield fake
    AC.uninstall()


def records(tmp_path) -> list[dict]:
    out = []
    for p in sorted((tmp_path / "log").rglob("*.jsonl")):
        out += [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    return out


def raw_text(tmp_path) -> str:
    return "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "log").rglob("*.jsonl"))


class PostingLLM(LLMProvider):
    """complete() 가 실제로 requests 로 Upstage 를 부르는 가짜 엔진 — 호출 스택은 진짜 기능 모듈을 지난다."""

    name = "posting-fake"
    model = "solar-pro3"

    def __init__(self, reply: str = "{}"):
        self.reply = reply

    def complete(self, *, system: str, user: str, **kw) -> str:
        requests.post(f"{UPSTAGE}/chat/completions", headers={"Authorization": f"Bearer {FAKE_KEY}"},
                      json={"model": "solar-pro3", "messages": [{"role": "user", "content": user[:40]}]}, timeout=5)
        return self.reply(user) if callable(self.reply) else self.reply


# ─── 레코드 ───────────────────────────────────────────────────────────────────────────

def test_레코드_필드가_다_있고_KST_이고_헤더는_안_남는다(net, tmp_path):
    AC.begin_request(team=True, route="/api/v1/questions")
    requests.post(f"{UPSTAGE}/chat/completions", headers={"Authorization": f"Bearer {FAKE_KEY}", "X-API-Key": FAKE_KEY},
                  json={"model": "solar-pro3", "messages": [{"role": "user", "content": "안녕"}], "temperature": 0.3})
    [r] = records(tmp_path)
    for k in ("record_id", "run_id", "feature", "feature_code", "provider", "request", "response", "attempt", "ok", "masked"):
        assert k in r
    assert r["request"]["time_kst"].endswith("+09:00") and r["response"]["time_kst"].endswith("+09:00")
    assert r["request"]["endpoint"] == f"{UPSTAGE}/chat/completions" and r["request"]["method"] == "POST"
    assert r["request"]["model"] == "solar-pro3" and r["request"]["body"]["temperature"] == 0.3
    assert r["response"]["status"] == 200 and r["response"]["body"]["usage"]["total_tokens"] == 3
    assert r["provider"] == "Upstage" and r["ok"] is True and r["attempt"] == 1
    assert r["request_scope"]["route"] == "/api/v1/questions"
    text = raw_text(tmp_path)
    assert "Authorization" not in text and FAKE_KEY not in text and "X-API-Key" not in text
    assert r["feature_code"] == AC.UNCLASSIFIED            # 기능 모듈 밖(테스트)에서 부른 호출


def test_저장_폴더는_0700_파일은_0600(net, tmp_path):
    requests.get(f"{UPSTAGE}/models")
    [p] = list((tmp_path / "log").rglob("*.jsonl"))
    assert (tmp_path / "log").stat().st_mode & 0o777 == 0o700
    assert p.stat().st_mode & 0o777 == 0o600


def test_국내_AI_목록_밖_호스트는_적지_않는다(net, tmp_path):
    requests.get("https://api.openalex.org/works?search=x")
    assert records(tmp_path) == []


def test_LLM_재시도는_attempt_2_로_남는다(net, tmp_path, monkeypatch):
    from pipeline.providers.llm_impl import OpenAICompatLLM

    net.plan = [(500, {"error": "busy"}), (200, {"id": "ok", "model": "solar-pro3", "choices": [], "usage": {}})]
    monkeypatch.setattr(OpenAICompatLLM, "RETRY_BACKOFF_SEC", 0)
    llm = OpenAICompatLLM(api_key=FAKE_KEY, base_url=UPSTAGE, model="solar-pro3", name="solar")
    res = llm._post_with_retry(f"{UPSTAGE}/chat/completions", {"Authorization": f"Bearer {FAKE_KEY}"}, {"model": "solar-pro3"})
    assert res.status_code == 200
    a, b = records(tmp_path)
    assert (a["attempt"], a["ok"], b["attempt"], b["ok"]) == (1, False, 2, True)
    assert a["run_id"] == b["run_id"]


def test_연결_실패는_error_로_남고_다시_던진다(net, tmp_path):
    net.plan = [requests.ConnectionError("boom")]
    with pytest.raises(requests.ConnectionError):
        requests.post(f"{UPSTAGE}/chat/completions", json={"model": "solar-pro3"})
    [r] = records(tmp_path)
    assert r["response"]["error"] == "ConnectionError" and r["ok"] is False and "status" not in r["response"]


def test_성공한_뒤_같은_요청_비동기_폴링은_재시도가_아니다(net, tmp_path):
    for _ in range(3):
        requests.get(f"{UPSTAGE}/document-digitization/requests/abc")
    assert [r["attempt"] for r in records(tmp_path)] == [1, 1, 1]


def test_multipart_와_파일_본문은_지문으로만(net, tmp_path):
    doc = tmp_path / "deck.pdf"
    doc.write_bytes(b"%PDF-1.4 secret slide text")
    with doc.open("rb") as f:
        requests.post(CFG.docparse_url, headers={"Authorization": f"Bearer {FAKE_KEY}"},
                      files={"document": ("deck.pdf", f)}, data={"model": "document-parse", "ocr": "auto"})
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF....WAVEfmt " + b"\x01\x02" * 500)
    with wav.open("rb") as f:
        requests.put("https://awf-gw.adot.ai/v1/stt/upload/tok", data=f,
                     headers={"X-API-Key": FAKE_KEY, "Content-Type": "application/octet-stream"})
    requests.post("https://awf-gw.adot.ai/v1/stt/transcript", headers={"X-API-Key": FAKE_KEY},
                  json={"speech_model": "A.X_STT_note_batch", "audio_file_key": "k"})
    d, put, tr = records(tmp_path)
    body = d["request"]["body"]
    assert body["form"]["model"] == "document-parse" and d["request"]["model"] == "document-parse"
    assert body["document"] == {"filename": "deck.pdf", "bytes": doc.stat().st_size,
                                "sha256": hashlib.sha256(doc.read_bytes()).hexdigest()}
    assert put["request"]["body"]["audio"]["sha256"] == hashlib.sha256(wav.read_bytes()).hexdigest()
    assert tr["request"]["model"] == "A.X_STT_note_batch" and tr["provider"] == "SKT"
    text = raw_text(tmp_path)
    assert "secret slide text" not in text and "RIFF" not in text


def test_긴_실수_배열_임베딩은_줄여서_남긴다(net, tmp_path):
    net.plan = [(200, {"data": [{"index": 0, "embedding": [0.5] * 4096}], "model": "embedding-passage", "usage": {}})]
    requests.post(f"{UPSTAGE}/embeddings", json={"model": "embedding-passage", "input": ["a"]})
    [r] = records(tmp_path)
    emb = r["response"]["body"]["data"][0]["embedding"]
    assert emb["_floats"] == 4096 and len(emb["head"]) == 8 and len(emb["sha256"]) == 64


# ─── 모드 ─────────────────────────────────────────────────────────────────────────────

def test_team_모드는_팀_요청만_적는다(net, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_CALLLOG", "team")
    requests.post(f"{UPSTAGE}/chat/completions", json={"model": "solar-pro3"})        # 범위 없음 (CLI)
    AC.begin_request(team=False, route="/api/v1/graph")
    requests.post(f"{UPSTAGE}/chat/completions", json={"model": "solar-pro3"})        # 공개 방문자
    assert records(tmp_path) == []
    AC.begin_request(team=True, route="/api/v1/graph")
    requests.post(f"{UPSTAGE}/chat/completions", json={"model": "solar-pro3"})
    assert len(records(tmp_path)) == 1


def test_off_모드는_아무것도_안_적는다(net, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_CALLLOG", "off")
    AC.begin_request(team=True)
    requests.post(f"{UPSTAGE}/chat/completions", json={"model": "solar-pro3"})
    assert records(tmp_path) == []


def test_해외_AI_호스트는_경고한다(net, tmp_path, capsys):
    requests.post("https://api.openai.com/v1/chat/completions", json={"model": "gpt"})
    requests.post("https://speech.googleapis.com/v1/speech:recognize", json={})
    requests.get("https://api.openalex.org/works")                                    # 학술 검색은 AI 가 아니다
    assert AC.FOREIGN_SEEN == ["api.openai.com", "speech.googleapis.com"]
    assert "해외 AI 호스트" in capsys.readouterr().err
    assert records(tmp_path) == []


def test_서버_코드에_해외_AI_호스트가_없다():
    """규정 「100% 국내 AI」 — 서버(main/pipeline · main/server)가 해외 AI API 를 부르는 코드를 새로 붙이면 여기서 걸린다."""
    hits = []
    for p in list((ROOT / "main" / "pipeline").rglob("*.py")) + list((ROOT / "main" / "server").rglob("*.py")):
        if p.name == "_ai_calllog.py":
            continue
        for host in ("api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com", "speech.googleapis.com",
                     "api.cohere", "api.mistral.ai"):
            if host in p.read_text(encoding="utf-8"):
                hits.append(f"{p.relative_to(ROOT)}: {host}")
    assert hits == []


# ─── 기능 찾기 · 스레드풀 ────────────────────────────────────────────────────────────────

def test_기능_표의_모듈_이름_규칙():
    assert AC._FEATURE_MOD.match("f08_questions") and AC._FEATURE_MOD.match("f09_reframe")
    assert not AC._FEATURE_MOD.match("_typed_graph")
    feats = json.loads(AC.FEATURES_FILE.read_text(encoding="utf-8"))["features"]
    assert {"F-01", "F-05", "F-05-live", "F-06", "F-07", "F-08", "F-09", "F-11", "F-12", "F-14", "F-19", "F-20", "F-24", "F-26"} <= set(feats)
    assert "F-18" not in feats                                           # 로컬 서빙 — 제출 대상 아님
    assert len(set(feats.values())) == len(feats)                        # 파일명이 겹치면 zip 안에서 덮인다


def _team_scope():
    return AC.begin_request(team=True, route="/api/v1/test")


def test_스레드풀_F06_배치와_다수결도_요청_범위를_물려받는다(net, tmp_path, monkeypatch):
    from tests.test_concept_parallel import SlowLLM, make_doc
    from pipeline.contracts import Context
    from pipeline.f06_concepts import extract_concepts

    monkeypatch.setenv("AI_CALLLOG", "team")                            # 범위가 안 따라가면 0건이 된다
    monkeypatch.setenv("CHUCKCHUCK_CONCEPT_VOTES", "2")
    slow = SlowLLM(delay=0.01)
    llm = PostingLLM(reply=lambda user: slow.complete(system="", user=user))
    s = _team_scope()
    extract_concepts(make_doc(24), Context(), llm=llm, batch_size=8)
    rs = records(tmp_path)
    assert len(rs) == 6 and {r["feature_code"] for r in rs} == {"F-06"}  # 배치 3 × 다수결 2
    assert {r["run_id"] for r in rs} == {s.runs["F-06"]["id"]}            # 한 실행으로 묶인다
    assert rs[0]["feature"] == "핵심개념_추출"


def test_스레드풀_F14_채점_묶음(net, tmp_path, monkeypatch):
    from pipeline import f14_rubric
    from pipeline._rubric_det import Evidence

    monkeypatch.setenv("AI_CALLLOG", "team")
    _team_scope()
    nos = [n for b in f14_rubric.LLM_BATCHES.values() for n in b]
    f14_rubric._score_llm(PostingLLM(), Evidence(), nos)
    rs = records(tmp_path)
    assert len(rs) >= len(f14_rubric.LLM_BATCHES) and {r["feature_code"] for r in rs} == {"F-14"}


def test_스레드풀_F07_뼈대_다수결은_유틸_표로_F07(net, tmp_path, monkeypatch):
    from pipeline import _typed_graph as TG

    monkeypatch.setenv("AI_CALLLOG", "team")
    monkeypatch.setattr(TG, "skeleton_votes", lambda engine: 3)
    monkeypatch.setattr(TG, "build_prompt", lambda doc, ctx: "뼈대 질문")      # 재료(ConceptDoc) 없이 — 호출 길은 진짜 그대로
    _team_scope()
    TG.call_structure(PostingLLM('{"core": 1}'), None, None, 100)
    rs = records(tmp_path)
    assert len(rs) == 3 and {r["feature_code"] for r in rs} == {"F-07"}  # 일꾼 스택엔 fNN 이 없다 → 유틸 표


def test_스레드풀_F12_객석_병아리(net, tmp_path, monkeypatch):
    from tests.test_chatter import make_alignment, make_graph
    from pipeline.f11_flow import build_flow_diff
    from pipeline.f12_chatter import CHATTER_SPEAKERS, build_chatter

    monkeypatch.setenv("AI_CALLLOG", "team")
    graph = make_graph()
    alignment = make_alignment(graph)
    _team_scope()
    reply = json.dumps({"turns": [{"text": "어... 그거 좋네요.", "mood": "curious", "ref_node_ids": []}]}, ensure_ascii=False)
    build_chatter(graph, alignment, build_flow_diff(graph, alignment), llm_factory=lambda sp: PostingLLM(reply), rounds=1)
    rs = records(tmp_path)
    assert len(rs) == len(CHATTER_SPEAKERS) and {r["feature_code"] for r in rs} == {"F-12"}


def test_실시간_받아쓰기_세션은_한_건(net, tmp_path):
    _team_scope()
    dg = AC.audio_digest()
    dg.add(b"\x00\x01" * 16000)
    AC.record_live_session(endpoint="wss://awf-gw.adot.ai/v1/stt/realtime", model="A.X_STT_note_streaming",
                           create={"message_type": "create", "speech_model": "A.X_STT_note_streaming"},
                           audio=dg.summary(), transcripts=[{"message_type": "transcript", "text": "안녕하세요"}],
                           t0=AC.now_kst(), t1=AC.now_kst(), closed={"message_type": "stopped", "code": 0}, ok=True)
    [r] = records(tmp_path)
    assert r["feature_code"] == "F-05-live" and r["feature"] == "답변_실시간_받아쓰기" and r["provider"] == "SKT"
    assert r["request"]["body"]["audio"]["duration_sec"] == 1.0 and r["response"]["status"] == 101
    assert r["transport"] == "websocket"


def test_보관_기간이_지난_날짜_폴더는_지운다(tmp_path):
    base = tmp_path / "log"
    for name in ("2020-01-01", "2999-01-01", "pinned"):
        (base / name).mkdir(parents=True)
    assert AC.prune(base) == ["2020-01-01"]
    assert sorted(p.name for p in base.iterdir()) == ["2999-01-01", "pinned"]


# ─── 내보내기 ──────────────────────────────────────────────────────────────────────────

def _export_mod():
    spec = importlib.util.spec_from_file_location("ai_calllog_export", ROOT / "etc" / "scripts" / "ai_calllog_export.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed(net, tmp_path, monkeypatch):
    """기능 둘(F-08 · F-09) × 실행 둘. F-09 의 나중 실행은 실패로 끝난다 — 앞 실행이 골라져야 한다."""
    from pipeline import f08_questions, f09_judge

    def call(mod, content, status=200):
        net.plan = [(status, {"id": "r", "model": "solar-pro3", "choices": [{"message": {"content": content}}],
                              "usage": {"total_tokens": 9}})]
        # 기능 모듈 안에서 부른 것처럼 — 그 모듈의 전역으로 함수를 만들어 스택에 fNN 프레임을 둔다
        fn = type(lambda: 0)(compile("def _t(rq, u, body):\n    return rq.post(u, json=body)\n", mod.__file__, "exec")
                             .co_consts[0], vars(mod))
        fn(requests, f"{UPSTAGE}/chat/completions", {"model": "solar-pro3", "messages": [{"role": "user", "content": content}]})

    _team_scope()
    call(f08_questions, "질문 하나 — 연락처 010-1234-5678 · a.b@example.com")
    call(f09_judge, "판정 첫 실행")
    _team_scope()
    call(f08_questions, "질문 둘")
    call(f09_judge, "판정 둘", status=500)


def test_내보내기는_기능마다_성공한_실행_하나를_기능명_파일로(net, tmp_path, monkeypatch):
    _seed(net, tmp_path, monkeypatch)
    ex = _export_mod()
    out = tmp_path / "out.zip"
    report = ex.export(root=tmp_path / "log", since="2000-01-01", out=out, keys=[FAKE_KEY])
    with zipfile.ZipFile(out) as z:
        names = sorted(z.namelist())
        docs = {n: json.loads(z.read(n)) for n in names}
    assert names == ["답변_판정_꼬리질문.json", "예상질문_생성.json"]
    q = docs["예상질문_생성.json"]
    assert q["feature"] == "예상질문_생성" and q["record_count"] == 1 and q["models"] == ["solar-pro3"]
    assert q["records"][0]["request"]["body"]["messages"][0]["content"] == "질문 둘"        # 가장 최근 성공 실행
    j = docs["답변_판정_꼬리질문.json"]
    assert j["records"][0]["request"]["body"]["messages"][0]["content"] == "판정 첫 실행"  # 실패로 끝난 나중 실행은 건너뜀
    assert "F-01" in report["missing"] and report["outside_hosts"] == []


def test_내보내기_마스킹은_구조를_지킨다(net, tmp_path, monkeypatch):
    _seed(net, tmp_path, monkeypatch)
    ex = _export_mod()
    rec = [r for r in records(tmp_path) if "010-1234" in json.dumps(r, ensure_ascii=False)][0]
    masked, paths = ex.mask(rec, keys=[FAKE_KEY])
    assert json.dumps(ex.shape(masked)) == json.dumps(ex.shape(rec))                         # 키 · 자료형 · 길이 그대로
    content = masked["request"]["body"]["messages"][0]["content"]
    assert "010-1234-5678" not in content and "a.b@example.com" not in content and "***" in content
    assert "request.body.messages[0].content" in paths
    s, _ = ex.mask({"x": f"Bearer {FAKE_KEY} 그리고 {FAKE_KEY} 와 900101-1234567"}, keys=[FAKE_KEY])
    assert FAKE_KEY not in s["x"] and "900101-1234567" not in s["x"] and "Bearer" not in s["x"]


def test_내보내기_run_지정과_고정(net, tmp_path, monkeypatch):
    _seed(net, tmp_path, monkeypatch)
    ex = _export_mod()
    first = [r for r in records(tmp_path) if r["feature_code"] == "F-08"][0]["run_id"]
    ex.pin(tmp_path / "log", [first])
    assert list((tmp_path / "log" / "pinned").glob("*.jsonl"))
    out = tmp_path / "o.zip"
    ex.export(root=tmp_path / "log", since="2000-01-01", out=out, runs={"F-08": first}, keys=[])
    with zipfile.ZipFile(out) as z:
        q = json.loads(z.read("예상질문_생성.json"))
    assert q["run_id"] == first and q["record_count"] == 1                                     # 고정본과 날짜 폴더가 겹쳐도 한 번만
