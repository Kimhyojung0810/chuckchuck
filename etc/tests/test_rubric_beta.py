"""
채점표 베타 항목 — 카메라 분석 「발표 태도」 (rubric_v3.BETA_ITEMS · f14_rubric.presence_items · contracts.BehaviorSummary).

지키는 것:

1. **총점은 한 점도 안 바뀐다.** 같은 입력에 카메라 요약을 얹어도 score · clusters · items · cap 이 그대로다
   (받아쓰기 점수 회귀). 베타 가중치는 사람 채점과의 일치(ICC)를 확인하기 전까지 0 이다.
2. 카메라 분석이 없었던 발표 · 게이트에 걸린 지표는 0점이 아니라 「못 쟀다」 와 까닭이다.
3. 브라우저가 보낸 값은 거른 것만 옮겨 적는다 — 모르는 키 · 범위 밖 · 긴 글 · 큰 목록은 걸러진다.
4. 브리지가 요약을 세션 보관소 behavior_doc 에 판(발표 · Q&A)별로 남긴다.
"""

from __future__ import annotations

import hashlib
import io
import json
from email.message import Message

import pytest

import server.bridge as bridge
from pipeline import rubric_v3
from pipeline.contracts import BEHAVIOR_MAX_BYTES, BehaviorSummary, RubricScore, Transcript, Word
from pipeline.f14_rubric import presence_items, score_rubric
from pipeline.providers.llm_base import LLMProvider
from server.session_archive import SessionArchive
from server.session_store import SessionStore


class _FixedLLM(LLMProvider):
    """묶음마다 같은 점수를 내는 가짜 LLM — 결과가 늘 같아야 두 번 매긴 점수를 견줄 수 있다."""

    name = "fixed"

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        nos = [
            int(line[3:line.index(")")])
            for line in user.splitlines()
            if line.startswith("- (") and ")" in line and line[3:line.index(")")].isdigit()
        ]
        return json.dumps({"items": [{"no": n, "score": 70 + n % 7, "evidence": f"{n}번 근거 인용 문장"} for n in nos]},
                          ensure_ascii=False)


def _transcript() -> Transcript:
    return Transcript(
        full_text="오늘은 세 가지를 말씀드릴게요. 첫째 문제입니다. 따라서 이렇게 정리했어요.",
        words=[Word(text=w, start_sec=i, end_sec=i + 1) for i, w in enumerate("오늘은 세 가지를 말씀드릴게요".split())],
        provider="ax",
        duration_sec=120.0,
    )


#: behavior_cv_logic.js summaryOf() 가 내는 모양 (숫자만)
BEHAVIOR_OK = {
    "v": 1, "phase": "present", "status": "ok", "why": "",
    "dur": 182.4, "frames": 905, "fps": 4.96, "ms_p50": 17, "ms_p90": 56,
    "quality": {"presence": 0.97, "dark": 0, "bright": 151.2, "blur": 320.5, "face": 0.18, "eyes": 0.74, "track": 0.95, "body": 0.9},
    "metrics": {
        "gaze": {"ok": True, "value": 0.81, "level": 2, "conf": "보통", "sides": {"left": 0.05, "right": 0.08, "down": 0.04, "away": 0.02}},
        "lookaway": {"ok": True, "value": 0.66, "level": 1, "conf": "보통", "n": 2, "total": 8.4, "longest": 4.6},
        "down": {"ok": True, "value": 0.04, "level": 0, "conf": "낮음"},
        "sway": {"ok": True, "value": 0.2, "level": 1, "conf": "보통", "amp": 0.21, "windows": 35},
        "movement": {"ok": True, "value": 0.31, "level": 1, "conf": "보통"},
        "gesture": {"ok": True, "value": 0.33, "level": 1, "conf": "보통", "speak": 0.42, "silent": 0.12},
        "framing": {"ok": True, "value": 0.18, "level": 1, "conf": "보통", "off": 0.04},
    },
    "areas": [{"key": "gaze", "ok": True, "level": 0, "word": "짚을 곳이 없어요"}, {"key": "body", "ok": True, "level": 1, "word": "흔들림 가끔 있어요"},
              {"key": "hands", "ok": True, "level": 1, "word": "보통이에요"}, {"key": "frame", "ok": True, "level": 0, "word": "알맞아요"}],
    "first": {"kind": "lookaway", "area": "gaze", "text": "3장에서 4.6초 동안 화면 쪽이 아니라 왼쪽을 향했어요", "slide": 3, "q": None, "sec": 41.2},
    "segs": [{"seg": "s1", "dur": 30.2, "present": 1, "gaze": 0.9, "down": 0, "gesture": 0.3, "move": 0.2, "lookaway": 0}],
    "events": [{"k": "lookaway", "seg": "s3", "t": 41.2, "d": 4.6}],
}


def test_베타_항목은_세개이고_가중치가_모두_0이다():
    assert [i.no for i in rubric_v3.BETA_ITEMS] == [40, 41, 42]
    for item in rubric_v3.BETA_ITEMS:
        assert all(w == 0 for w in item.weights.values())
        assert item.cluster not in rubric_v3.CLUSTERS and item.source == "camera"
    # 채점표 39개 · 클러스터 가중치 합 100 · 소리 항목(25·26) na 는 그대로 — 카메라로 채우지 않는다
    assert len(rubric_v3.ITEMS) == 39
    assert rubric_v3.ITEM_BY_NO[25].source == "na" and rubric_v3.ITEM_BY_NO[26].source == "na"
    for s in rubric_v3.SITUATIONS:
        assert sum(rubric_v3.CLUSTER_WEIGHTS[c][s] for c in rubric_v3.CLUSTERS) == 100


@pytest.mark.parametrize("situation", tuple(rubric_v3.SITUATIONS))
def test_카메라_요약을_얹어도_총점이_그대로다(situation):
    """받아쓰기 점수 회귀 — 카메라 요약이 있든 없든, 좋든 나쁘든 점수 · 클러스터 · 항목이 같다."""
    base = score_rubric(situation=situation, transcript=_transcript(), llm=_FixedLLM())
    bad = json.loads(json.dumps(BEHAVIOR_OK))
    bad["metrics"]["gaze"]["value"] = 0.0
    bad["metrics"]["sway"]["value"] = 1.0
    for behavior in (BEHAVIOR_OK, bad, {"phase": "present", "status": "none", "why": "카메라를 꺼 둬서"}, None):
        got = score_rubric(situation=situation, transcript=_transcript(), llm=_FixedLLM(), behavior=behavior)
        assert got.score == base.score
        assert got.cap == base.cap
        assert [c.to_dict() for c in got.clusters] == [c.to_dict() for c in base.clusters]
        assert [i.to_dict() for i in got.items] == [i.to_dict() for i in base.items]
        assert [i.no for i in got.beta] == [40, 41, 42]


def test_숫자를_옮겨_적는다_점수는_설계값_매기기():
    items = {i.no: i for i in presence_items(BEHAVIOR_OK)}
    assert items[40].status == "scored" and items[40].score == 81 and items[40].weight == 0
    assert "화면 쪽을 향한 시간 81%" in items[40].evidence and "2번" in items[40].evidence
    assert items[41].score == 80 and "베타" in items[41].note          # 흔들림 없던 창 80%
    assert items[42].score == 42 and "많을수록 좋다는 뜻은 검증 전" in items[42].evidence


def test_게이트에_걸린_지표는_못_잰_것과_브라우저의_까닭():
    b = json.loads(json.dumps(BEHAVIOR_OK))
    b["metrics"]["gaze"] = {"ok": False, "why": "얼굴이 화면에서 너무 작았어요"}
    b["metrics"]["gesture"]["speak"] = None
    items = {i.no: i for i in presence_items(b)}
    assert items[40].status == "unmeasured" and items[40].score == 0 and "작았어요" in items[40].note
    assert items[42].status == "unmeasured" and "말소리와 맞춰 보지 못해서" in items[42].note


def test_카메라_분석이_없으면_세_항목_모두_못_잰_것과_까닭():
    why = "카메라를 꺼 두고 발표해서 카메라 분석은 없어요"
    for behavior in (None, {}, "문자열", {"phase": "present", "status": "none", "why": why}, {**BEHAVIOR_OK, "phase": "qa"}):
        items = presence_items(behavior)
        assert [i.status for i in items] == ["unmeasured"] * 3
        assert all(i.weight == 0 and i.score == 0 for i in items)
    assert presence_items({"phase": "present", "status": "none", "why": why})[0].note == why


def test_이상한_값은_걸러진다():
    weird = json.loads(json.dumps(BEHAVIOR_OK))
    weird["metrics"]["gaze"]["value"] = 7.5                      # 범위 밖(비율은 0~1 이 아니어도 0~1000 으로 자른다)
    weird["metrics"]["gaze"]["conf"] = "<script>"
    weird["metrics"]["sway"]["value"] = "높음"                    # 숫자가 아님
    weird["metrics"]["evil"] = {"ok": True, "value": 1}          # 모르는 지표
    weird["why"] = "x" * 900
    weird["segs"] = [{"seg": "s1"}, {"seg": "../../etc"}] * 200
    weird["events"] = [{"k": "lookaway", "seg": "s1", "t": 1, "d": 3}, {"k": "emotion", "seg": "s1"}] * 100
    weird["first"]["text"] = "y" * 900
    b = BehaviorSummary.from_dict(weird)
    d = b.to_dict()
    assert "evil" not in d["metrics"] and "evil" not in d
    assert d["metrics"]["gaze"]["conf"] == "낮음"
    assert d["metrics"]["sway"]["value"] is None
    assert len(d["why"]) <= 120 and len(d["first"]["text"]) <= 160
    assert len(d["segs"]) <= 60 and all(s["seg"] == "s1" for s in d["segs"])
    assert len(d["events"]) <= 40 and all(e["k"] == "lookaway" for e in d["events"])
    assert len(json.dumps(d, ensure_ascii=False).encode()) <= BEHAVIOR_MAX_BYTES
    items = {i.no: i for i in presence_items(weird)}
    assert items[41].status == "unmeasured"
    assert BehaviorSummary.from_dict([1, 2]) is None


def test_저장본의_베타_가중치는_0으로_읽는다():
    got = score_rubric(situation="school_project", transcript=_transcript(), llm=_FixedLLM(), behavior=BEHAVIOR_OK)
    d = got.to_dict()
    d["beta"][0]["weight"] = 30   # 누가 손으로 고쳐도
    back = RubricScore.from_dict(json.loads(json.dumps(d)))
    assert all(i.weight == 0 for i in back.beta)
    assert back.score == got.score


# ─── 브리지: /api/v1/rubric 의 behavior · /api/v1/behavior → 보관소 behavior_doc ─────────────────────────

class FakeHandler(bridge.Handler):
    def __init__(self, path: str, body: bytes) -> None:  # noqa: D107
        self.path = path
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"
        self.headers["Content-Length"] = str(len(body))
        self.rfile = io.BytesIO(body)
        self.client_address = ("127.0.0.1", 1)
        self.sent: list[tuple[int, dict]] = []
        self.wfile = io.BytesIO()
        self.request_version = "HTTP/1.1"
        self.command = "POST"

    def _json(self, code: int, payload: dict):
        self.sent.append((code, payload))


def post(path: str, payload: dict) -> tuple[int, dict]:
    h = FakeHandler(path, json.dumps(payload, ensure_ascii=False).encode())
    h.do_POST()
    return h.sent[-1]


@pytest.fixture
def archive(tmp_path, monkeypatch):
    arc = SessionArchive(tmp_path / "data")
    monkeypatch.setattr(bridge, "ARCHIVE", arc)
    monkeypatch.setattr(bridge, "STORE", SessionStore())
    monkeypatch.setattr(bridge, "DEV_ROUTES", False)
    monkeypatch.setattr(bridge, "REQUIRE_ACCESS", False)
    monkeypatch.setattr(bridge, "_mock", lambda: False)
    monkeypatch.setattr(bridge.LIMITER, "allow", lambda key: True)
    return arc


def _session(arc: SessionArchive) -> str:
    sid = arc.new_id()
    arc.open(sid, consent=True, file_name="d.pdf", ext=".pdf", upload=b"%PDF-1.4 x",
             sha256=hashlib.sha256(sid.encode()).hexdigest(), title="d", learner_id="brw_beh001")
    return sid


def test_채점_본문의_behavior_가_베타와_보관소로(archive, monkeypatch):
    monkeypatch.setattr(bridge, "_pick_llm", lambda body: _FixedLLM())
    sid = _session(archive)
    code, payload = post("/api/v1/rubric", {"session_id": sid, "situation": "school_project",
                                            "transcript": _transcript().to_dict(), "behavior": BEHAVIOR_OK})
    assert code == 200
    assert [b["no"] for b in payload["beta"]] == [40, 41, 42] and all(b["weight"] == 0 for b in payload["beta"])
    doc = archive.read_artifact(sid, "behavior_doc")
    assert doc["present"]["metrics"]["gaze"]["value"] == 0.81 and "qa" not in doc


def test_QA_판은_따로_남고_발표_판을_지우지_않는다(archive):
    sid = _session(archive)
    archive.put_artifact(sid, "behavior_doc", {"present": BehaviorSummary.from_dict(BEHAVIOR_OK).to_dict()})
    qa = {**json.loads(json.dumps(BEHAVIOR_OK)), "phase": "qa", "segs": [{"seg": "q1", "dur": 40}]}
    code, payload = post("/api/v1/behavior", {"session_id": sid, "behavior": qa})
    assert code == 200 and payload["behavior"]["phase"] == "qa"
    doc = archive.read_artifact(sid, "behavior_doc")
    assert set(doc) == {"present", "qa"} and doc["qa"]["segs"][0]["seg"] == "q1"
    assert post("/api/v1/behavior", {"session_id": sid})[0] == 400


def test_너무_큰_behavior_는_통째로_버리고_채점은_돈다(archive, monkeypatch):
    monkeypatch.setattr(bridge, "_pick_llm", lambda body: _FixedLLM())
    huge = {**BEHAVIOR_OK, "pad": "z" * (bridge.BEHAVIOR_BODY_MAX + 10)}
    code, payload = post("/api/v1/rubric", {"situation": "school_project", "transcript": _transcript().to_dict(), "behavior": huge})
    assert code == 200
    assert [b["status"] for b in payload["beta"]] == ["unmeasured"] * 3
