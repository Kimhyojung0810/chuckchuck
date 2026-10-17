"""테스트 공통 — 다수결 추출·뼈대 판단은 한 번으로 (가짜 LLM 호출 수를 세는 테스트가 많다). 다수결 자체는 test_typed_graph 가 따로 본다."""
import pytest


@pytest.fixture(autouse=True)
def _single_vote(monkeypatch):
    monkeypatch.setenv("CHUCKCHUCK_CONCEPT_VOTES", "1")
    monkeypatch.setenv("CHUCKCHUCK_GRAPH_SKELETON_VOTES", "1")
    monkeypatch.setenv("CHUCKCHUCK_GRAPH_SAME", "0")          # 같은 개념 묶기는 임베딩 API 를 부른다 — 테스트는 따로 켠다


@pytest.fixture(autouse=True)
def _number_traps_on(monkeypatch):
    """함정 장치 테스트는 수치 함정 fixture 위에 서 있다 — 10-05 부터 기본값은 끔(f08 TRAP_NUMBERS). 끈 동작은 test_questions 가 따로 본다."""
    from pipeline import f08_questions
    monkeypatch.setattr(f08_questions, "TRAP_NUMBERS", True)


@pytest.fixture(autouse=True)
def _no_service_switches(monkeypatch):
    """서비스 .env 의 켜기 스위치를 테스트에 물려받지 않는다 (10-17 버그 사냥) — 저장소 .env 에 QA_ENSEMBLE=1 · QA_JUDGE_LLM 이 들어간 뒤
    질문 테스트가 **실 API 로 네 모델 묶음을 만들며** 10초씩 서서(test_bridge_degraded 3건 실패) 과금까지 났다. 켜서 보는 테스트는 스스로 setenv 한다."""
    for name in ("QA_ENSEMBLE", "QA_JUDGE_LLM", "QA_ENS_MODELS", "QA_ENS_PICKER"):
        monkeypatch.delenv(name, raising=False)
