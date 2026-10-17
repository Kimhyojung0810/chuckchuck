"""
F-11 LoRA 판정기(ALIGN_JUDGE=lora|lora+solar) — 항목 그림·출력 해석·align_speech 배선을 가짜 판정기로 검사한다.

GPU·어댑터·API 키가 필요 없다. 실제 모델 성능은 etc/finetune/align/eval_*.py 가 잰다.
"""

import json

import pytest

from pipeline import _align_lora as lora
from pipeline._spoken import utterances
from pipeline.contracts import AlignError, AlignmentItem, ConceptEdge, ConceptGraph, ConceptNode, SlideSpeech, Transcript
from pipeline.f11_align import align_speech
from pipeline.providers.llm_base import LLMProvider


def _graph() -> ConceptGraph:
    nodes = [
        ConceptNode(id="c1", label="환기 시간", slide_nos=[1], summary="창문을 여는 시간", weight=1.0),
        ConceptNode(id="c2", label="평균 농도", slide_nos=[2], summary="평균 농도가 40% 낮아짐", weight=0.8),
        ConceptNode(id="c3", label="발표자 소속", slide_nos=[3], summary="2학년 3반", weight=0.2),
    ]
    return ConceptGraph(file_name="t.pdf", total_slides=3, nodes=nodes,
                        edges=[ConceptEdge(from_id="c1", to_id="c2", kind="parent")])


def _transcript() -> Transcript:
    texts = {1: "오늘은 환기 시간 이야기를 할게요. 창문을 오래 열수록 좋아요.",
             2: "수업 중에 5분을 더 열었더니 평균 농도가 40퍼센트 낮아졌어요.",
             3: "감사합니다."}
    by = [SlideSpeech(slide_no=no, visit=1, start_sec=10.0 * (no - 1), end_sec=10.0 * no, text=t) for no, t in texts.items()]
    return Transcript(full_text=" ".join(texts.values()), by_slide=by, provider="mock", duration_sec=30.0)


class FakeJudge(lora.AlignJudge):
    """node_id → (verdict, sid, confidence). 받은 항목도 기록한다."""

    name = "fake-lora"

    def __init__(self, plan: dict, fail: bool = False):
        self.plan, self.fail, self.seen = plan, fail, []

    def judge_items(self, items):
        if self.fail:
            raise FileNotFoundError("어댑터 없음")
        self.seen = items
        out = []
        for it in items:
            verdict, sid, conf = self.plan.get(it["node_id"], ("missing", None, 0.99))
            got = lora.parse_output(lora.ASSISTANT_PREFIX + lora.render_target(verdict, sid, "가짜 이유")[len(lora.ASSISTANT_PREFIX):], it)
            out.append(lora.Judgment(node_id=it["node_id"], verdict=got["verdict"], sid=got["sid"], evidence=got["evidence"],
                                     note=got["note"], confidence=conf, ok=got["ok"]))
        return out


class OneShotSolar(LLMProvider):
    name = "solar-fake"

    def __init__(self, items):
        self.items, self.calls, self.users = items, 0, []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.calls += 1
        self.users.append(user)
        return json.dumps({"items": self.items, "speech_edges": [], "extra_concepts": []}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 항목 · 프롬프트 · 출력 해석
# ---------------------------------------------------------------------------

def test_build_items_numbers_sentences_per_slide_and_neighbors():
    items = lora.build_items(_graph(), _transcript())
    it = {x["node_id"]: x for x in items}["c2"]
    assert [r["sid"] for r in it["own"]] == ["s02-01"]
    assert [r["sid"] for r in it["prev"]] == ["s01-01", "s01-02"]
    assert [r["sid"] for r in it["next"]] == ["s03-01"]
    assert lora.item_sentences(it)["s02-01"].startswith("수업 중에")


def test_prompt_is_hand_built_midm_chat_without_default_preamble():
    it = lora.build_items(_graph(), _transcript())[0]
    p = lora.render_prompt(it)
    assert p.startswith("<|begin_of_text|><|start_header_id|>system")
    assert p.endswith("<|start_header_id|>assistant<|end_header_id|>\n\n")
    assert "Mi:dm(믿:음)은" not in p          # 기본 틀의 긴 안내문을 싣지 않는다
    assert "s02-01 수업 중에" in p


def test_parse_output_maps_sid_to_verbatim_sentence():
    it = {x["node_id"]: x for x in lora.build_items(_graph(), _transcript())}["c2"]
    got = lora.parse_output('{"verdict": "aligned", "sid": "s02-01", "note": "말했어요"}', it)
    assert got["ok"] and got["verdict"] == "aligned"
    assert got["evidence"] == it["own"][0]["text"]
    assert lora.evidence_valid(it, got["sid"], got["evidence"])


def test_parse_output_broken_json_recovers_verdict_but_flags_not_ok():
    got = lora.parse_output('{"verdict": "missing", "sid": null, "note": "끊김', None)
    assert got["verdict"] == "missing" and got["ok"] is False


def test_parse_output_unknown_sid_is_not_valid_evidence():
    it = lora.build_items(_graph(), _transcript())[0]
    got = lora.parse_output('{"verdict": "aligned", "sid": "s09-09", "note": ""}', it)
    assert not lora.evidence_valid(it, got["sid"], got["evidence"])


def test_long_speech_is_trimmed_to_budget_keeping_order():
    node = ConceptNode(id="x", label="핵심 결과", slide_nos=[1], summary="핵심 결과")
    long = " ".join(f"문장 {i}번은 다른 이야기예요." for i in range(400)) + " 핵심 결과는 이거예요."
    tr = Transcript(full_text=long, by_slide=[SlideSpeech(slide_no=1, visit=1, start_sec=0, end_sec=100, text=long)])
    it = lora.build_item(node, lora.speech_index(utterances(tr)), {})
    assert sum(len(r["text"]) for r in it["own"]) <= lora.OWN_CHARS + 50
    assert any("핵심 결과는" in r["text"] for r in it["own"])           # 개념 낱말이 든 문장은 남는다
    ks = [int(r["sid"].split("-")[1]) for r in it["own"] if r["sid"]]
    assert ks == sorted(ks)                                              # 말한 순서 그대로


def test_target_has_no_generated_quote():
    t = json.loads(lora.render_target("aligned", "s02-01", "이유"))
    assert set(t) == {"verdict", "sid", "note"}
    assert json.loads(lora.render_target("missing", "s02-01", ""))["sid"] is None


# ---------------------------------------------------------------------------
# align_speech 배선
# ---------------------------------------------------------------------------

def test_lora_judge_marks_provenance_and_does_not_fake_edge_coverage():
    fake = FakeJudge({"c1": ("aligned", "s01-01", 0.97), "c2": ("contradiction", "s02-01", 0.95),
                      "c3": ("justified_skip", None, 0.99)})
    solar = OneShotSolar([])
    doc = align_speech(_graph(), _transcript(), judge="lora", lora_judge=fake, llm=solar)
    assert solar.calls == 0
    assert doc.model == "fake-lora"
    by = {i.node_id: i for i in doc.items}
    assert by["c1"].decided_by == "lora" and by["c1"].verdict == "aligned"
    assert by["c1"].evidence == "오늘은 환기 시간 이야기를 할게요."
    assert by["c3"].verdict == "justified_skip"
    assert doc.summary.edge_coverage is None            # 발화 간선을 안 봤다 — 0% 라고 하지 않는다
    assert AlignmentItem.from_dict(by["c1"].to_dict()).decided_by == "lora"


def test_lora_plus_solar_escalates_only_unsure_nodes():
    fake = FakeJudge({"c1": ("aligned", "s01-01", 0.97), "c2": ("missing", None, 0.41),
                      "c3": ("justified_skip", None, 0.99)})
    solar = OneShotSolar([{"node_id": "c2", "verdict": "aligned", "evidence": "평균 농도가 40퍼센트 낮아졌어요"}])
    doc = align_speech(_graph(), _transcript(), judge="lora+solar", lora_judge=fake, llm=solar)
    assert solar.calls == 1
    assert "(c2)" in solar.users[0] and "(c1)" not in solar.users[0]    # 올린 개념만 묻는다
    by = {i.node_id: i for i in doc.items}
    assert by["c2"].decided_by == "llm" and by["c2"].verdict == "aligned"
    assert by["c1"].decided_by == "lora"
    assert doc.model == "fake-lora+solar-fake"


def test_lora_plus_solar_escalates_when_quote_does_not_point_into_speech():
    fake = FakeJudge({"c1": ("aligned", "s07-07", 0.99)})
    solar = OneShotSolar([{"node_id": "c1", "verdict": "aligned", "evidence": "오늘은 환기 시간 이야기를 할게요."}])
    doc = align_speech(_graph(), _transcript(), judge="lora+solar", lora_judge=fake, llm=solar)
    assert {i.node_id: i for i in doc.items}["c1"].decided_by == "llm"


def test_lora_without_solar_keeps_unsure_verdict_and_never_calls_api():
    fake = FakeJudge({"c2": ("missing", None, 0.3)})
    solar = OneShotSolar([])
    doc = align_speech(_graph(), _transcript(), judge="lora", lora_judge=fake, llm=solar)
    assert solar.calls == 0
    # 코드 대조가 「말한 문장」 을 찾아 aligned 로 되살릴 수는 있다 — 그때는 decided_by code
    assert {i.node_id: i for i in doc.items}["c2"].decided_by in ("lora", "code")


def test_lora_failure_falls_back_to_solar_judgment():
    fake = FakeJudge({}, fail=True)
    solar = OneShotSolar([{"node_id": "c1", "verdict": "aligned", "evidence": "오늘은 환기 시간 이야기를 할게요."}])
    doc = align_speech(_graph(), _transcript(), judge="lora", lora_judge=fake, llm=solar)
    assert solar.calls >= 1
    assert doc.model == "solar-fake"
    assert {i.node_id: i for i in doc.items}["c1"].decided_by == "llm"


def test_unknown_judge_is_an_error():
    with pytest.raises(AlignError):
        align_speech(_graph(), _transcript(), judge="gpt", llm=OneShotSolar([]))


def test_default_judge_is_solar(monkeypatch):
    monkeypatch.delenv("ALIGN_JUDGE", raising=False)
    solar = OneShotSolar([{"node_id": "c1", "verdict": "aligned", "evidence": "오늘은 환기 시간 이야기를 할게요."}])
    fake = FakeJudge({})
    doc = align_speech(_graph(), _transcript(), llm=solar, lora_judge=fake)
    assert solar.calls >= 1 and fake.seen == []
    assert doc.model == "solar-fake"


def test_judge_identity_separates_bridge_cache_by_judge(monkeypatch):
    from pipeline.f11_align import judge_identity

    monkeypatch.delenv("ALIGN_JUDGE", raising=False)
    monkeypatch.setenv("CHUCKCHUCK_ALIGN_LORA_PATH", "/x/r1/final")
    assert judge_identity() == "solar"
    assert judge_identity("lora") != judge_identity("solar")
    assert "/x/r1/final" in judge_identity("lora+solar")
