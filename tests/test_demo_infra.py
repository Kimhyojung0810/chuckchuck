"""
데모 브리지의 상태 관리(세션 저장소 · 요청 제한)를 검사합니다.

시각은 전부 가짜 clock 을 주입해서 잰다 — 실제로 기다리는 테스트는 느리고,
느린 테스트는 결국 안 돌리게 된다.
"""

from __future__ import annotations

from demo.rate_limit import RateLimiter
from demo.session_store import SessionStore, fingerprint


def _question(**over):
    """힌트 사다리 검사용 질문 하나. F-08 이 실제로 채우는 필드만 채운다."""
    from chuckchuck.contracts import Question

    base = dict(
        id="q1",
        node_id="n1",
        label="대조학습",
        question="대조학습으로 정렬했다는 근거가 무엇인가요?",
        why="자료가 근거 장을 갖고 있다",
        hint="핵심을 한 문장으로 먼저 말해 보세요",
        slide_nos=[3, 4],
        answer_gist="영상·텍스트와 같은 공간에 IMU 를 맞춘다",
    )
    base.update(over)
    return Question(**base)


class FakeClock:
    """수동으로 감는 시계."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, sec: float) -> None:
        self.now += sec


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------

def test_fingerprint_ignores_key_order():
    """프론트가 키 순서를 보장하지 않는다 — 같은 내용이면 같은 지문이어야 한다."""
    a = fingerprint({"nodes": [1, 2], "file_name": "a.pdf"})
    b = fingerprint({"file_name": "a.pdf", "nodes": [1, 2]})
    assert a == b


def test_fingerprint_changes_with_content():
    assert fingerprint({"nodes": [1]}) != fingerprint({"nodes": [2]})


def test_fingerprint_separates_parts():
    """이어 붙이기로 같은 지문이 나오면 안 된다 (graph+alignment 조합 키로 쓴다)."""
    assert fingerprint("ab", "c") != fingerprint("a", "bc")


# ---------------------------------------------------------------------------
# SessionStore — 아티팩트
# ---------------------------------------------------------------------------

def test_put_and_get_artifacts():
    store = SessionStore()
    stored = store.put_artifacts("s1", {"graph": {"nodes": []}, "alignment": {"items": []}})

    assert set(stored) == {"graph", "alignment"}
    assert store.artifacts("s1")["graph"] == {"nodes": []}


def test_none_does_not_erase_registered_artifact():
    """나중 요청의 빈 값이 이미 등록된 근거를 지우면 판정이 근거를 잃는다."""
    store = SessionStore()
    store.put_artifacts("s1", {"graph": {"nodes": [1]}})
    store.put_artifacts("s1", {"graph": None, "transcript": {"words": []}})

    assert store.artifacts("s1")["graph"] == {"nodes": [1]}
    assert "transcript" in store.artifacts("s1")


def test_unknown_keys_are_not_stored():
    """큰 객체(SlideDoc·오디오)를 밀어 넣어도 메모리가 새지 않는다."""
    store = SessionStore()
    store.put_artifacts("s1", {"graph": {}, "slide_doc": {"huge": "x" * 1000}})

    assert "slide_doc" not in store.artifacts("s1")


def test_missing_session_returns_empty():
    assert SessionStore().artifacts("nope") == {}
    assert SessionStore().artifacts("") == {}


def test_artifacts_returns_a_copy():
    """호출자가 받은 dict 를 건드려도 저장소가 오염되면 안 된다."""
    store = SessionStore()
    store.put_artifacts("s1", {"graph": {}})
    store.artifacts("s1")["graph"] = "오염"

    assert store.artifacts("s1")["graph"] == {}


def test_session_expires_after_ttl():
    clock = FakeClock()
    store = SessionStore(ttl_sec=100, clock=clock)
    store.put_artifacts("s1", {"graph": {}})

    clock.advance(101)
    assert store.artifacts("s1") == {}


def test_recent_use_keeps_session_alive():
    """쓰이는 세션은 살려 둔다 — 코칭이 길어졌다고 근거가 사라지면 안 된다."""
    clock = FakeClock()
    store = SessionStore(ttl_sec=100, clock=clock)
    store.put_artifacts("s1", {"graph": {}})

    for _ in range(5):
        clock.advance(60)
        assert store.artifacts("s1") != {}


def test_overflow_evicts_least_recently_used():
    clock = FakeClock()
    store = SessionStore(max_sessions=2, clock=clock)
    store.put_artifacts("old", {"graph": {}})
    clock.advance(1)
    store.put_artifacts("mid", {"graph": {}})
    clock.advance(1)
    store.artifacts("old")            # old 를 다시 써서 살린다
    clock.advance(1)
    store.put_artifacts("new", {"graph": {}})

    assert store.artifacts("mid") == {}
    assert store.artifacts("old") != {}
    assert store.artifacts("new") != {}


# ---------------------------------------------------------------------------
# SessionStore — triage 캐시
# ---------------------------------------------------------------------------

def test_triage_cache_roundtrip():
    store = SessionStore()
    store.set_triage("fp1", {"marks": []})

    assert store.get_triage("fp1") == {"marks": []}
    assert store.get_triage("fp2") is None
    assert store.get_triage("") is None


def test_triage_cache_expires():
    clock = FakeClock()
    store = SessionStore(ttl_sec=100, clock=clock)
    store.set_triage("fp1", {"marks": []})

    clock.advance(101)
    assert store.get_triage("fp1") is None


def test_triage_cache_evicts_oldest():
    clock = FakeClock()
    store = SessionStore(max_triage=2, clock=clock)
    for key in ("a", "b", "c"):
        store.set_triage(key, {"k": key})
        clock.advance(1)

    assert store.get_triage("a") is None
    assert store.get_triage("c") == {"k": "c"}


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------

def test_allows_up_to_limit_then_blocks():
    clock = FakeClock()
    limiter = RateLimiter(limit=3, window_sec=60, clock=clock)

    assert [limiter.allow("ip") for _ in range(4)] == [True, True, True, False]


def test_window_slides():
    clock = FakeClock()
    limiter = RateLimiter(limit=1, window_sec=60, clock=clock)
    assert limiter.allow("ip") is True
    assert limiter.allow("ip") is False

    clock.advance(61)
    assert limiter.allow("ip") is True


def test_keys_are_counted_separately():
    limiter = RateLimiter(limit=1, window_sec=60)
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True
    assert limiter.allow("a") is False


def test_zero_limit_disables_throttling():
    """오프라인 시연·테스트에서 제한을 꺼도 동작해야 한다."""
    limiter = RateLimiter(limit=0, window_sec=60)
    assert all(limiter.allow("ip") for _ in range(50))
    assert limiter.retry_after("ip") == 0


def test_retry_after_counts_down():
    clock = FakeClock()
    limiter = RateLimiter(limit=1, window_sec=60, clock=clock)
    limiter.allow("ip")

    clock.advance(20)
    assert 1 <= limiter.retry_after("ip") <= 41


# ---------------------------------------------------------------------------
# 힌트 사다리 (F-08 → /api/v1/questions 응답)
# ---------------------------------------------------------------------------


def test_questions_payload_carries_multi_step_hints():
    """
    판정 전에도 힌트가 2단계 이상 실려야 한다.

    하나만 실리면 화면(qa_live.js)이 1단계를 보여 준 뒤 버튼을 지운다 —
    3단계로 설계한 사다리가 첫 칸에서 끝나 버린다.
    """
    from demo.bridge import with_hint_ladders

    q = _question()
    out = with_hint_ladders({"questions": [{"id": q.id}]}, [q])

    assert len(out["questions"][0]["hints"]) >= 2


def test_hint_ladder_starts_with_the_questions_own_hint():
    """1단계는 F-08 이 질문과 함께 만든 힌트다 — 사다리가 딴 데서 시작하면 안 된다."""
    from demo.bridge import with_hint_ladders

    q = _question(hint="근거로 삼은 장부터 짚어 보세요")
    out = with_hint_ladders({"questions": [{"id": q.id}]}, [q])

    assert out["questions"][0]["hints"][0] == "근거로 삼은 장부터 짚어 보세요"


def test_with_hint_ladders_does_not_mutate_the_input_payload():
    """doc.to_dict() 를 제자리에서 고치면 호출자가 쥔 문서까지 같이 바뀐다."""
    from demo.bridge import with_hint_ladders

    payload = {"questions": [{"id": "q1"}]}
    with_hint_ladders(payload, [_question()])

    assert "hints" not in payload["questions"][0]


def test_questions_without_a_matching_object_are_left_alone():
    """짝이 없으면 힌트만 빠진다 — 목록이 어긋났다고 응답 전체를 죽이지 않는다."""
    from demo.bridge import with_hint_ladders

    out = with_hint_ladders({"questions": [{"id": "q1"}, {"id": "q9"}]}, [_question()])

    assert out["questions"][0]["hints"]
    assert "hints" not in out["questions"][1]
