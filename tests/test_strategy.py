"""
[F-20] 발표 구성 제안이 계약을 지키는지 검사하는 테스트입니다.

이 모듈의 위험은 "LLM 이 그럴듯하게 지어낸다" 하나로 모입니다. 그래서 테스트도
정상 경로보다 방어 경로에 무게를 둡니다 — 없는 발화를 인용했는가, 없는 유형을
만들어냈는가, 응답이 잘렸을 때 살릴 것과 버릴 것을 가르는가.

전부 스크립트된 가짜 프로바이더로 돌아갑니다 — 네트워크·API 키가 필요 없습니다.
"""

import json

import pytest

from chuckchuck.contracts import StrategyError
from chuckchuck.f20_strategy import (
    MAX_CONCEPT_CHARS,
    MAX_QUOTE_CHARS,
    STRATEGY_TYPES,
    _build_user_prompt,
    suggest_strategy,
)
from chuckchuck.providers.llm_base import LLMProvider
from chuckchuck.providers.llm_impl import MockLLM

# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

REAL_QUOTE = "잠을 못 자면 다음 날 하루가 통째로 사라집니다"


class ScriptedLLM(LLMProvider):
    """지정한 문자열을 그대로 돌려주는 가짜 프로바이더. 받은 프롬프트를 기록한다."""

    name = "scripted"

    def __init__(self, payload: str):
        self.payload = payload
        self.seen_user = ""
        self.seen_system = ""

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096,
                 json_mode=False) -> str:
        self.seen_system = system
        self.seen_user = user
        return self.payload


@pytest.fixture
def analysis() -> dict:
    """수면의 질 발표를 축소한 픽스처. 도입에 시간을 과하게 쓴 발표다."""
    return {
        "title": "수면의 질을 결정하는 것",
        "occasion": "사내 공유회",
        "duration": "8:15",
        "concepts": [
            {"label": "수면 부채", "slide": "S02", "verdict": "aligned"},
            {"label": "렘수면 주기", "slide": "S03", "verdict": "partial"},
            {"label": "카페인 반감기", "slide": "S05", "verdict": "missing"},
        ],
        "time_alloc": [
            {"slide": "S01", "label": "인사", "recommended": "0:40", "actual": "2:24"},
            {"slide": "S05", "label": "실천법", "recommended": "2:00", "actual": "0:35"},
        ],
        "slides": [
            {"no": 1, "title": "인사", "spent": "2:24"},
            {"no": 2, "title": "수면 부채란"},
            {"no": 3, "title": "렘수면 주기"},
            {"no": 5, "title": "실천법", "spent": "0:35"},
        ],
        "quotes": [
            {"at": "00:12", "text": REAL_QUOTE},
            {"at": "04:33", "text": "그래서 카페인은 오후 2시가 마지노선입니다"},
        ],
    }


def payload_of(**chosen_over) -> str:
    chosen = {
        "type": "베이조스식 결론 선행형",
        "why": "도입 S01 에 2:24 를 써서 권장 0:40 의 세 배를 넘겼어요.",
        "outline": [
            {"role": "결론 선언", "from": "0:00", "to": "0:40", "slides": [], "new": True,
             "what": "결론을 먼저 못박아요.", "add": "5번의 실천법을 여기로 끌어와 주세요."},
            {"role": "근거", "from": "0:40", "to": "5:00", "slides": [2, 3],
             "what": "수면 부채를 축으로 세워요.", "add": ""},
        ],
        "keep": {"quote": REAL_QUOTE, "at": "00:12"},
    }
    chosen.update(chosen_over)
    return json.dumps({
        "chosen": chosen,
        "alternatives": [{"type": "잡스식 축 고정형", "one_line": "주장 하나로 묶어요."}],
    }, ensure_ascii=False)


def run(analysis: dict, payload: str) -> dict:
    return suggest_strategy(analysis, llm=ScriptedLLM(payload))


# ---------------------------------------------------------------------------
# ⓐ 정상 경로
# ---------------------------------------------------------------------------

def test_normal_response(analysis):
    out = run(analysis, payload_of())
    assert out["chosen"]["type"] == "베이조스식 결론 선행형"
    assert out["chosen"]["keep"]["quote"] == REAL_QUOTE
    assert len(out["alternatives"]) == 1
    outline = out["chosen"]["outline"]
    assert [b["role"] for b in outline] == ["결론 선언", "근거"]
    assert outline[0]["new"] is True and outline[0]["slides"] == []
    assert outline[1]["slides"] == [2, 3]
    assert outline[0]["add"] and outline[1]["add"] == ""


def test_climax_comes_from_the_table_not_the_llm(analysis):
    """'핵심을 앞에 두나 뒤에 두나' 는 서버가 유형 표에서 채운다. LLM 값은 무시된다."""
    out = run(analysis, payload_of(climax="아무거나"))
    assert out["chosen"]["climax"] == "early"

    late = run(analysis, payload_of(type="머스크식 전제 축적형"))
    assert late["chosen"]["climax"] == "late"


def test_every_type_declares_a_known_climax():
    for name, meta in STRATEGY_TYPES.items():
        assert meta["climax"] in ("early", "late", "throughline"), name
        assert meta["principle"] and meta["reads"], name


def test_code_fence_is_stripped(analysis):
    out = run(analysis, f"```json\n{payload_of()}\n```")
    assert out["chosen"]["type"] == "베이조스식 결론 선행형"


# ---------------------------------------------------------------------------
# ⓑ 잘린 JSON 복구 — 이 코드베이스의 알려진 실패 모드
# ---------------------------------------------------------------------------

def test_truncated_response_keeps_chosen_and_drops_partial_tail(analysis):
    """max_tokens 에서 끊긴 응답. 완성된 chosen 은 살리고 미완성 alternatives 는 버린다."""
    truncated = (
        '{"chosen": {"type": "잡스식 축 고정형", "why": "중심 주장이 2번 하나로 모여요.",'
        ' "outline": [{"role": "축 세우기", "from": "0:00", "to": "3:00",'
        ' "slides": [2], "what": "수면 부채를 먼저 세워요.", "add": ""}]},'
        ' "alternatives": [{"type": "베이조'
    )
    out = run(analysis, truncated)
    assert out["chosen"]["type"] == "잡스식 축 고정형"
    assert out["chosen"]["outline"][0]["slides"] == [2]
    assert out["alternatives"] == []


def test_unparseable_response_raises(analysis):
    with pytest.raises(StrategyError):
        run(analysis, "구성을 제안드릴게요. 결론을 먼저 말하는 게 좋겠어요.")


def test_json_array_is_rejected(analysis):
    """dict 가 아니면 받지 않는다."""
    with pytest.raises(StrategyError):
        run(analysis, '[{"type": "잡스식 축 고정형"}]')


# ---------------------------------------------------------------------------
# ⓒ 환각 방어 — 프롬프트 지시가 아니라 코드로 막는다
# ---------------------------------------------------------------------------

def test_fabricated_quote_is_dropped(analysis):
    """실제 발화에 없는 인용은 keep 을 통째로 버린다. 나머지 제안은 살린다."""
    out = run(analysis, payload_of(
        keep={"quote": "저는 이 자리에서 여러분께 약속드립니다", "at": "03:00"}))
    assert "keep" not in out["chosen"]
    assert out["chosen"]["type"] == "베이조스식 결론 선행형"


def test_real_quote_survives_whitespace_difference(analysis):
    """LLM 이 띄어쓰기를 바꿔 옮겨도 같은 발화면 살린다."""
    out = run(analysis, payload_of(
        keep={"quote": "잠을 못자면 다음 날 하루가  통째로 사라집니다", "at": "00:12"}))
    assert out["chosen"]["keep"]["at"] == "00:12"


def test_unknown_type_raises(analysis):
    with pytest.raises(StrategyError, match="알 수 없는 유형"):
        run(analysis, payload_of(type="오프라 윈프리식 공감형"))


@pytest.mark.parametrize("copied", [
    # 실 LLM(A.X)에서 실제로 관측된 응답 — 프롬프트의 메타데이터까지 옮겨 적었다
    "잡스식 축 고정형 (핵심 위치: throughline)",
    '"잡스식 축 고정형"',
    "잡스식 축 고정형 — 주장 하나를 세우고",
    "잡스식  축  고정형",
])
def test_type_copied_with_extra_text_is_normalized(analysis, copied):
    """모델이 이름에 설명을 덧붙여도 정본으로 되돌린다. 지어낸 이름과는 다르다."""
    out = run(analysis, payload_of(type=copied))
    assert out["chosen"]["type"] == "잡스식 축 고정형"
    assert out["chosen"]["climax"] == "throughline"


def test_normalization_applies_to_alternatives(analysis):
    payload = json.dumps({
        "chosen": json.loads(payload_of())["chosen"],
        "alternatives": [{"type": "잡스식 축 고정형 (핵심 위치: throughline)", "one_line": "하나"}],
    }, ensure_ascii=False)
    assert [a["type"] for a in run(analysis, payload)["alternatives"]] == ["잡스식 축 고정형"]


def test_missing_chosen_raises(analysis):
    with pytest.raises(StrategyError, match="chosen"):
        run(analysis, json.dumps({"alternatives": []}))


def test_empty_analysis_raises():
    for bad in ({}, None, "발표 내용"):
        with pytest.raises(StrategyError):
            suggest_strategy(bad, llm=ScriptedLLM(payload_of()))


def test_alternatives_exclude_the_chosen_type_and_cap_at_two(analysis):
    payload = json.dumps({
        "chosen": json.loads(payload_of())["chosen"],
        "alternatives": [
            {"type": "베이조스식 결론 선행형", "one_line": "자기 자신"},
            {"type": "잡스식 축 고정형", "one_line": "하나"},
            {"type": "머스크식 전제 축적형", "one_line": "둘"},
            {"type": "저커버그식 사용자 서사형", "one_line": "셋 — 잘려야 한다"},
            {"type": "없는 유형", "one_line": "지어냄"},
        ],
    }, ensure_ascii=False)
    alts = [a["type"] for a in run(analysis, payload)["alternatives"]]
    assert alts == ["잡스식 축 고정형", "머스크식 전제 축적형"]


def test_invented_slide_numbers_are_dropped(analysis):
    """없는 장 번호가 섞이면 발표자가 그걸 찾다 신뢰를 잃는다. 여기서 지운다."""
    out = run(analysis, payload_of(outline=[
        {"role": "근거", "from": "0:00", "to": "3:00", "slides": [2, 99, 3, "x", 2],
         "what": "수면 부채를 세워요.", "add": ""},
    ]))
    assert out["chosen"]["outline"][0]["slides"] == [2, 3]   # 99·"x" 제거, 중복 제거


def test_block_losing_every_slide_becomes_new(analysis):
    """번호를 다 잃은 구간은 지우지 않고 '신설' 로 돌린다 — 취지는 남긴다."""
    out = run(analysis, payload_of(outline=[
        {"role": "도입", "from": "0:00", "to": "1:00", "slides": [77, 88],
         "what": "결론을 먼저 못박아요.", "add": ""},
    ]))
    block = out["chosen"]["outline"][0]
    assert block["slides"] == [] and block["new"] is True
    assert block["what"]


def test_blocks_without_role_or_what_are_dropped(analysis):
    out = run(analysis, payload_of(outline=[
        {"role": "", "what": "역할이 없어요", "slides": [2]},
        {"role": "설명만 있음", "what": "", "slides": [2]},
        "구간이 아니라 문자열",
        {"role": "정상", "what": "이건 살아요", "slides": [2]},
    ]))
    assert [b["role"] for b in out["chosen"]["outline"]] == ["정상"]


def test_parenthetical_numbers_are_stripped(analysis):
    """괄호 숫자는 오른쪽 슬라이드 배지와 중복되고 시각인지 장 번호인지도 흐리다."""
    out = run(analysis, payload_of(outline=[
        {"role": "동기(3:12)", "from": "0:00", "to": "3:00", "slides": [2, 3],
         "what": "동기(3:12)와 구조(3:56)를 축으로 세우고 데이터셋(14, 16)을 붙여요.",
         "add": "loss(8, 12)만 간단히 언급해 주세요."},
    ]))
    b = out["chosen"]["outline"][0]
    assert b["role"] == "동기"
    assert b["what"] == "동기와 구조를 축으로 세우고 데이터셋을 붙여요."
    assert b["add"] == "loss만 간단히 언급해 주세요."


def test_non_numeric_parentheses_survive(analysis):
    """숫자만 든 괄호만 지운다. 뜻이 있는 괄호는 남겨야 문장이 안 망가진다."""
    out = run(analysis, payload_of(outline=[
        {"role": "방법론", "slides": [2],
         "what": "IMU Encoder(1D conv)를 30%(권장 대비) 줄여요.", "add": ""},
    ]))
    assert out["chosen"]["outline"][0]["what"] == "IMU Encoder(1D conv)를 30%(권장 대비) 줄여요."


def test_outline_is_capped(analysis):
    from chuckchuck.f20_strategy import MAX_BLOCKS
    many = [{"role": f"구간{i}", "what": f"내용{i}", "slides": [2]} for i in range(20)]
    assert len(run(analysis, payload_of(outline=many))["chosen"]["outline"]) == MAX_BLOCKS


def test_missing_outline_raises(analysis):
    with pytest.raises(StrategyError, match="outline"):
        run(analysis, payload_of(outline=[]))


def test_legacy_moves_key_never_reaches_the_screen(analysis):
    out = run(analysis, payload_of(moves=[{"slide": "S01"}]))
    assert "moves" not in out["chosen"]


def test_non_list_fields_become_empty_lists(analysis):
    payload = json.dumps({
        "chosen": {"type": "잡스식 축 고정형", "why": "…",
                   "outline": [{"role": "근거", "what": "살아요", "slides": "2번"}]},
        "alternatives": "잡스식도 괜찮아요",
    }, ensure_ascii=False)
    out = run(analysis, payload)
    assert out["chosen"]["outline"][0]["slides"] == []
    assert out["alternatives"] == []


# ---------------------------------------------------------------------------
# ⓓ 입력 절단 — 길면 응답이 잘리므로 보내기 전에 자른다
# ---------------------------------------------------------------------------

def test_long_input_is_clipped_before_sending(analysis):
    big = {
        **analysis,
        "concepts": [{"label": "개념" + str(i), "slide": "S01", "verdict": "aligned"}
                     for i in range(600)],
        "quotes": [{"at": "00:01", "text": "말" * (MAX_QUOTE_CHARS + 500)}],
    }
    llm = ScriptedLLM(payload_of(keep={}))
    suggest_strategy(big, llm=llm)

    concepts_block = llm.seen_user.split("개념별 판정")[1].split("구간별 시간")[0]
    quotes_block = llm.seen_user.split("실제 발화")[1]
    assert len(concepts_block) <= MAX_CONCEPT_CHARS + 40
    assert "…" in concepts_block
    assert len(quotes_block) <= MAX_QUOTE_CHARS + 200
    assert "…" in quotes_block


def test_prompt_offers_every_type_and_the_real_numbers(analysis):
    llm = ScriptedLLM(payload_of())
    suggest_strategy(analysis, llm=llm)
    assert "[TASK] presentation-strategy" in llm.seen_user   # MockLLM 분기 표식
    for name in STRATEGY_TYPES:
        assert name in llm.seen_user
    assert "2:24" in llm.seen_user          # 실제 사용 시간이 근거로 들어간다
    assert REAL_QUOTE in llm.seen_user      # keep 을 고를 원본이 들어간다
    assert "1번 인사" in llm.seen_user      # outline 이 짚을 슬라이드 목록
    assert "5번 실천법" in llm.seen_user


def test_missing_sections_do_not_break_the_prompt():
    """분석이 부분적으로만 있어도 프롬프트가 만들어진다."""
    prompt = _build_user_prompt({"title": "제목만 있는 발표"})
    assert "(없음)" in prompt
    assert "제목만 있는 발표" in prompt


# ---------------------------------------------------------------------------
# MockLLM 왕복 — MOCK_EXTERNAL_APIS=true 인 데모 서버가 실제로 타는 경로
# ---------------------------------------------------------------------------

def test_mock_llm_round_trip(analysis):
    out = suggest_strategy(analysis, llm=MockLLM())
    assert out["chosen"]["type"] in STRATEGY_TYPES
    assert out["chosen"]["climax"] in ("early", "late", "throughline")
    # 도입 S01 이 권장 0:40 에 2:24 를 썼으므로 결론 선행형이 나와야 한다
    assert out["chosen"]["type"] == "베이조스식 결론 선행형"
    known = {s["no"] for s in analysis["slides"]}
    used = [n for b in out["chosen"]["outline"] for n in b["slides"]]
    assert used and set(used) <= known          # 목도 실재하는 번호만 쓴다
    # 가짜 응답도 실제 발화를 인용해야 _validate 의 인용 검사를 통과한다
    assert out["chosen"]["keep"]["quote"] == REAL_QUOTE
    assert len(out["alternatives"]) == 2


def test_mock_llm_survives_a_bare_analysis():
    """시간·발화가 없어도 mock 이 유효한 제안을 낸다 — 데모가 500 을 내면 안 된다."""
    out = suggest_strategy({"title": "제목뿐인 발표"}, llm=MockLLM())
    assert out["chosen"]["type"] == "잡스식 축 고정형"
    assert "keep" not in out["chosen"]
    assert len(out["chosen"]["outline"]) >= 1


# ---------------------------------------------------------------------------
# 인물 이름을 빌리되 그 사람의 말을 지어내지 않는다 — 승인된 제약
# ---------------------------------------------------------------------------

def test_system_prompt_forbids_fabricating_real_people(analysis):
    llm = ScriptedLLM(payload_of())
    suggest_strategy(analysis, llm=llm)
    assert "지어내지 않는다" in llm.seen_system
    assert "당신의 발표를" in llm.seen_system
