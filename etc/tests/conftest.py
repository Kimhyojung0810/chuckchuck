"""테스트 공통 — 다수결 추출·뼈대 판단은 한 번으로 (가짜 LLM 호출 수를 세는 테스트가 많다). 다수결 자체는 test_typed_graph 가 따로 본다."""
import pytest


@pytest.fixture(autouse=True)
def _single_vote(monkeypatch):
    monkeypatch.setenv("CHUCKCHUCK_CONCEPT_VOTES", "1")
    monkeypatch.setenv("CHUCKCHUCK_GRAPH_SKELETON_VOTES", "1")
    monkeypatch.setenv("CHUCKCHUCK_GRAPH_SAME", "0")          # 같은 개념 묶기는 임베딩 API 를 부른다 — 테스트는 따로 켠다
    # 네 모델 Q&A 는 실 API 를 부른다 — .env 에 QA_ENSEMBLE=1 이 있어도(10-17 통합 브리지용) 테스트는 끈다. 켜 보는 테스트는 스스로 켠다
    monkeypatch.setenv("QA_ENSEMBLE", "0")


@pytest.fixture(autouse=True)
def _number_traps_on(monkeypatch):
    """함정 장치 테스트는 수치 함정 fixture 위에 서 있다 — 10-05 부터 기본값은 끔(f08 TRAP_NUMBERS). 끈 동작은 test_questions 가 따로 본다."""
    from pipeline import f08_questions
    monkeypatch.setattr(f08_questions, "TRAP_NUMBERS", True)
