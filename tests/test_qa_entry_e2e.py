"""
질문 코칭 진입 경로 E2E 회귀 테스트입니다.

브라우저에서만 재현되는 회귀를 잡습니다. pytest 의 나머지 테스트는 서버 경계에서
멈추기 때문에, 프론트가 서버를 "몇 번" 부르는지는 아무도 감시하지 않았습니다.

    RUN_LIVE_TESTS=1 SERVER_BASE=http://127.0.0.1:8000 \
        python -m pytest tests/test_qa_entry_e2e.py -v -s

기본값은 skip 입니다. 실행 중인 서버와 Playwright 브라우저가 필요합니다.
"""

from __future__ import annotations

import json
import os

import pytest

# live 마커만으로는 건너뛰지 않는다 — 실행 중인 서버와 브라우저가 필요하므로
# tests/test_live_pipeline.py 와 같은 규칙으로 기본 경로에서 제외한다.
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_TESTS") != "1",
        reason="RUN_LIVE_TESTS=1 일 때만 실행 (실행 중인 서버 + Playwright 필요)",
    ),
]

BASE = os.environ.get("SERVER_BASE", "http://127.0.0.1:8000")

#: JS 에서는 truthy 라 클라이언트 가드를 통과하지만, 서버에서는 falsy 라 400 이 난다.
#: 생성 실패 경로를 LLM 과금 없이 결정적으로 만든다.
FAILING_GRAPH: dict = {}


def _seed(pipeline_out: dict) -> dict:
    """resetNf() 가 만드는 모양. step 이 정수가 아니면 앱이 통째로 초기화한다."""
    return {
        "step": 4, "gate": None, "occ": "학회", "ctx": "교수님", "min": 10,
        "mic": "idle", "sec": 0, "slide": 1, "visits": {"1": 1}, "log": [],
        "done": 4, "completed": True, "fileName": "x.pptx", "sparseSlides": [],
        "parseError": None, "useSample": False, "marks": [], "pipelineError": None,
        "pipelinePhase": "done", "pipelineDetail": "준비 완료",
        "pipelineStartedAt": 1754051234567, "_pipelineTickStarted": False,
        "pipelineOut": pipeline_out,
    }


def _init_script(pipeline_out: dict) -> str:
    # 문서 로드 **전에** 심어야 실제 사용자의 메모리 상태와 같아진다.
    # goto(BASE) 후 goto(BASE+"#/qa") 는 해시만 다른 같은 문서라 재로드되지 않는다.
    return "sessionStorage.setItem('cheokcheok:new-flow', %s);" % json.dumps(
        json.dumps(_seed(pipeline_out))
    )


@pytest.fixture(scope="module")
def real_graph() -> dict:
    """실제 발표 1회분에서 뽑은 개념 그래프. 합성 그래프로는 질문이 안 나온다."""
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "live_qa_run.json"
    if not fixture.is_file():
        pytest.skip(f"fixture 없음: {fixture}")
    return json.loads(fixture.read_text())["session"]["artifacts"]["concept_graph"]


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip(
        "playwright.sync_api", reason="playwright 미설치"
    ).sync_playwright
    import urllib.error
    import urllib.request

    try:
        urllib.request.urlopen(f"{BASE}/api/health", timeout=3).read()
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"서버가 없습니다 ({BASE}): {exc}")

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _open_qa(browser, pipeline_out: dict, observe_ms: int):
    """#/qa 로 직행해 관찰 시간 동안의 questions 요청과 마지막 안내를 돌려준다."""
    posts: list[str] = []
    page = browser.new_page()
    try:
        page.add_init_script(_init_script(pipeline_out))
        page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
        page.goto(f"{BASE}/#/qa", wait_until="load")
        page.wait_for_timeout(900)
        gate = page.query_selector("#qaGateStart")   # 시간 트랙 게이트
        if gate:
            gate.click()
        page.wait_for_timeout(observe_ms)
        notice = page.evaluate(
            "()=>{try{return (JSON.parse(sessionStorage.getItem('cheokcheok:qa-flow')||'{}')).liveNotice||'';}"
            "catch(e){return '';}}"
        )
        return [u for u in posts if "/api/v1/questions" in u], notice
    finally:
        page.close()


def test_failed_generation_does_not_retry_forever(browser):
    """생성이 실패해도 재시도 루프에 빠지지 않는다.

    회귀 이력: ensureLiveQuestions() 의 finally 가 renderQa() 를 부르고,
    renderQa() 가 다시 ensureLiveQuestions() 를 불러 무한 루프가 됐다.
    12초에 3409 요청이 나갔고 화면은 '질문 준비 중' 에서 멈췄다.
    실 그래프였다면 그만큼 실 LLM 과금이 발생한다.
    """
    calls, _ = _open_qa(browser, {"graph": FAILING_GRAPH, "alignment": None, "flow": None}, 8000)

    assert len(calls) <= 1, f"실패 후 재시도 루프: 8초 동안 {len(calls)}회 요청. 1회 이하여야 한다."


#: 오늘 데모 질문을 눌러본 사용자의 남은 상태. 실제 사용자는 거의 항상 이 상태다.
STALE_QA = {
    "aud": "교수님", "started": True, "ended": False, "mode": "10", "bi": 0,
    "sub": "answer", "hint": 0,
    "turns": [{"who": "ai", "kind": "question", "text": "데모 질문입니다"}],
    "concepts": {"joint": "current", "temp": "wait", "aria": "wait"},
    "lost": [], "combo": 0, "comboMax": 0, "awarded": False, "award": None,
}


def test_generates_even_when_previous_demo_conversation_exists(browser, real_graph):
    """이전 데모 대화가 남아 있어도 내 발표 질문을 만든다.

    회귀 이력: renderQa() 가 `!qa.turns.length` 일 때만 생성하도록 막아 둬서,
    데모 질문을 한 번이라도 눌러본 사용자는 영원히 데모만 봤다. sessionStorage 에
    남는 상태라 새로고침으로도 풀리지 않았다.
    """
    page = browser.new_page()
    posts: list[str] = []
    try:
        page.add_init_script(
            _init_script({"graph": real_graph, "alignment": None, "flow": None})
            + "sessionStorage.setItem('cheokcheok:qa-flow', %s);"
            % json.dumps(json.dumps(STALE_QA, ensure_ascii=False))
        )
        page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
        page.goto(f"{BASE}/#/qa", wait_until="load")
        for _ in range(60):
            n = page.evaluate(
                "()=>{try{const q=JSON.parse(sessionStorage.getItem('cheokcheok:qa-flow')||'{}');"
                "return (q.live&&q.live.questions||[]).length;}catch(e){return 0;}}"
            )
            if n:
                break
            page.wait_for_timeout(1000)
        calls = [u for u in posts if "/api/v1/questions" in u]
        assert calls, "이전 대화가 있으면 생성을 건너뛴다 — 데모 질문만 보인다"
        assert n, "질문이 채워지지 않았다"
    finally:
        page.close()


def test_failed_generation_shows_reason(browser):
    """실패하면 조용히 넘어가지 말고 이유를 남긴다."""
    _, notice = _open_qa(browser, {"graph": FAILING_GRAPH, "alignment": None, "flow": None}, 4000)

    assert notice, "실패 이유가 화면 상태에 남지 않았다"
