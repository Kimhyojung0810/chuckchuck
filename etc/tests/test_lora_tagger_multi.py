"""
F-18 Mi:dm LoRA 다중 어댑터(REP + FIL 3시드) — GPU 없이 가짜 러너로 설정·파싱·위치 찾기·투표·폴백을 밟는다.
실제 모델은 절대 올리지 않는다 (MidmLoraRunner 는 가짜 클래스로 바꿔 끼운다).
"""

from __future__ import annotations

import json
import threading

import pytest

from pipeline import _lora_runtime as RT
from pipeline import _lora_tagger as LT
from pipeline import f18_habits
from pipeline.contracts import HabitDoc, SlideSpeech, Transcript, Word
from pipeline.f18_habits import extract_habits


def _adapter(path, task: dict | None = None):
    path.mkdir(parents=True)
    (path / "adapter_config.json").write_text("{}", encoding="utf-8")
    if task:
        (path / LT.TASK_FILE).write_text(json.dumps(task), encoding="utf-8")
    return path


@pytest.fixture
def hermetic(tmp_path, monkeypatch):
    """기본 탐색 위치를 빈 임시 폴더로 — 이 머신에 진짜 어댑터가 생겨도 테스트가 흔들리지 않게."""
    monkeypatch.setattr(LT, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(LT, "LEGACY_REP", tmp_path / "legacy")
    monkeypatch.setattr(LT, "LOCAL_BASE", tmp_path / "base")
    for k in ("CHUCKCHUCK_LORA_PATH", "CHUCKCHUCK_LORA_REP_PATH", "CHUCKCHUCK_LORA_FIL_PATHS",
              "CHUCKCHUCK_LORA_KINDS", "CHUCKCHUCK_LORA_FIL_MIN_VOTES", "CHUCKCHUCK_LORA_FIL_RP",
              "CHUCKCHUCK_LORA_FIL_PROMPT", "CHUCKCHUCK_LORA_BASE", "CHUCKCHUCK_LORA_CHUNK_CHARS",
              "CHUCKCHUCK_LORA_MAX_BATCH", "HABIT_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


@pytest.fixture
def three_fil(hermetic):
    rep = _adapter(hermetic / "runs" / "rep_seed42" / "final")
    fils = [_adapter(hermetic / "runs" / f"fil_seed{s}" / "final") for s in (42, 43, 44)]
    return rep, fils


# ─── 설정 ──────────────────────────────────────────────────────────────────────

def test_config_nothing_installed(hermetic):
    cfg = LT.load_config({})
    assert cfg.rep is None and cfg.fil == () and not cfg.adapters
    assert cfg.base == LT.MODEL_ID  # 로컬 베이스가 없으면 HF id
    assert not LT.adapter_available()


def test_config_autodiscovers_runs_root(three_fil, hermetic):
    (hermetic / "base").mkdir()
    (hermetic / "base" / "config.json").write_text("{}")
    cfg = LT.load_config({})
    assert cfg.base == str(hermetic / "base")
    assert cfg.rep.take == {"REP"} and cfg.rep.task.repetition_penalty == 1.0
    assert cfg.rep.task.system_prompt == LT.SYSTEM_PROMPT        # 서비스 REP 는 통합 태거
    assert [a.name for a in cfg.fil] == ["fil0", "fil1", "fil2"]
    assert all(a.task.repetition_penalty == 1.2 for a in cfg.fil)
    assert all(a.task.system_prompt == LT.TASK_PROMPTS["FIL"][0] for a in cfg.fil)
    assert cfg.fil_min_votes == 3                                  # min 방식
    assert LT.covered_kinds(cfg) == {"REP": "lora", "FIL": "lora-ensemble×3"}


def test_config_env_paths_votes_and_legacy_kinds(hermetic):
    rep = _adapter(hermetic / "a" / "rep")
    f1 = _adapter(hermetic / "a" / "f1")
    env = {"CHUCKCHUCK_LORA_PATH": str(rep), "CHUCKCHUCK_LORA_KINDS": "REP,FIL"}
    cfg = LT.load_config(env)
    assert cfg.rep.path == rep and cfg.rep.take == {"REP", "FIL"} and cfg.fil == ()   # 옛 설정 그대로
    env.update({"CHUCKCHUCK_LORA_FIL_PATHS": f"{f1}, {hermetic / 'nope'}",
                "CHUCKCHUCK_LORA_FIL_MIN_VOTES": "9", "CHUCKCHUCK_LORA_FIL_RP": "1.3"})
    cfg = LT.load_config(env)
    assert cfg.rep.take == {"REP"}                      # FIL 은 전용 어댑터가 맡는다
    assert [a.path for a in cfg.fil] == [f1] and cfg.fil_min_votes == 1
    assert cfg.fil[0].task.repetition_penalty == 1.3
    assert str(hermetic / "nope") in cfg.missing
    assert LT.load_config({**env, "CHUCKCHUCK_LORA_FIL_PATHS": "off"}).fil == ()
    uni = LT.load_config({**env, "CHUCKCHUCK_LORA_FIL_PROMPT": "unified"})
    assert uni.fil[0].task.system_prompt == LT.SYSTEM_PROMPT


def test_config_placeholder_path_falls_back_to_runs_root(three_fil):
    rep, fils = three_fil
    cfg = LT.load_config({"CHUCKCHUCK_LORA_PATH": "/path/to/lora/adapter",       # .env.example 자리표시 그대로
                          "CHUCKCHUCK_LORA_FIL_PATHS": "/nope/a,/nope/b"})
    assert cfg.rep.path == rep and [a.path for a in cfg.fil] == fils
    assert set(cfg.missing) == {"/path/to/lora/adapter", "/nope/a", "/nope/b"}


def test_config_task_file_overrides_defaults(hermetic):
    f = _adapter(hermetic / "f", {"system_prompt": "S", "user_template": "U {stt_text}",
                                  "repetition_penalty": 1.15, "max_new_tokens": 128})
    cfg = LT.load_config({"CHUCKCHUCK_LORA_FIL_PATHS": str(f)})
    t = cfg.fil[0].task
    assert (t.system_prompt, t.user_template, t.repetition_penalty, t.max_new_tokens) == ("S", "U {stt_text}", 1.15, 128)
    assert cfg.rep is None and cfg.adapters == cfg.fil


# ─── 파싱 · 위치 · 투표 ───────────────────────────────────────────────────────

def test_parse_tag_lines():
    raw = "REP\t지도 지도력은\nFIL 어\nNONE\nWR\t지속성\nXX\tfoo\nFIL\t\n"
    assert LT.parse_tag_lines(raw) == [("REP", "지도 지도력은"), ("FIL", "어"), ("WR", "지속성")]


def test_locate_ordered_maps_kth_line_to_kth_occurrence():
    toks = [LT._tok(t) for t in "어, 오늘은 어 발표를 음 어 시작합니다 지도 지도력은".split()]
    locs = LT.locate_ordered(["어", "어", "음", "어", "지도 지도력은", "없는말"], toks)
    assert locs == [(0, 1), (2, 3), (4, 5), (5, 6), (7, 9), None]


def test_locate_ordered_tolerates_spacing_and_reorder():
    toks = [LT._tok(t) for t in "음 그러니까 어 그 그 사람".split()]
    # 띄어쓰기가 달라도(「그그」) 붙여서 찾고, 순서가 어긋나면 남은 앞쪽에서 찾는다
    assert LT.locate_ordered(["그그", "음"], toks) == [(3, 5), (0, 1)]


def test_vote_positions_is_min_count():
    seeds = [[(0, 1), (2, 3), (5, 6)], [(0, 1), (2, 3)], [(0, 1), (2, 3), (5, 6), (8, 9)]]
    assert LT.vote_positions(seeds, 3) == [(0, 1), (2, 3)]
    assert LT.vote_positions(seeds, 2) == [(0, 1), (2, 3), (5, 6)]


def test_chunk_words_breaks_on_word_boundaries():
    words = [Word(text="가나다", start_sec=i, end_sec=i + 1) for i in range(10)]   # 단어당 4글자
    assert LT.chunk_words(words, 9) == [(0, 2), (2, 4), (4, 6), (6, 8), (8, 10)]
    assert LT.chunk_words(words, 10_000) == [(0, 10)]
    assert LT.chunk_words([], 100) == []


# ─── 태깅 (가짜 러너) ─────────────────────────────────────────────────────────

def _talk() -> Transcript:
    s1 = "안녕하세요 어 오늘은 지도 지도력은 이야기를 어 하겠습니다".split()
    s2 = "음 첫째로 어 리더는 음 듣는 사람입니다".split()
    w1 = [Word(text=t, start_sec=i * 0.5, end_sec=i * 0.5 + 0.4) for i, t in enumerate(s1)]
    w2 = [Word(text=t, start_sec=10 + i * 0.5, end_sec=10 + i * 0.5 + 0.4) for i, t in enumerate(s2)]
    return Transcript(full_text="", by_slide=[SlideSpeech(1, 1, 0, 9, " ".join(s1), w1), SlideSpeech(2, 1, 9, 20, " ".join(s2), w2)])


class FakeRunner:
    def __init__(self, by_adapter: dict[str, str]):
        self.by_adapter = by_adapter
        self.calls: list[list] = []

    def generate_batch(self, reqs):
        self.calls.append(list(reqs))
        return [self.by_adapter.get(r.adapter, "NONE") for r in reqs]


def test_tag_habits_rep_plus_fil_ensemble(three_fil):
    cfg = LT.load_config({})
    runner = FakeRunner({
        "rep": "REP\t지도 지도력은\nFIL\t어",          # 통합 태거의 FIL 은 버린다(take=REP)
        "fil0": "FIL\t어\nFIL\t어\nFIL\t음\nFIL\t어\nFIL\t음",
        "fil1": "FIL\t어\nFIL\t어\nFIL\t음\nFIL\t어",
        "fil2": "FIL\t어\nFIL\t어\nFIL\t음\nFIL\t어\nFIL\t음\nFIL\t지어낸말",
    })
    res = LT.tag_habits(_talk(), config=cfg, runner=runner)
    reqs = runner.calls[0]
    assert [r.adapter for r in reqs] == ["rep", "fil0", "fil1", "fil2"]          # 한 배치, 행마다 어댑터
    assert [r.repetition_penalty for r in reqs] == [1.0, 1.2, 1.2, 1.2]
    assert "지도 지도력은" in reqs[0].user_text and reqs[1].user_text.startswith("다음 발표 전사문에서 FIL")
    got = [(s.kind, s.text, s.start_sec, s.slide_no) for s in res.spans]
    assert got == [
        ("FIL", "어", 0.5, 1),
        ("REP", "지도 지도력은", 1.5, 1),
        ("FIL", "어", 3.0, 1),
        ("FIL", "음", 10.0, 2),
        ("FIL", "어", 11.0, 2),
    ]  # 두 번째 「음」 은 세 시드 중 둘만 → min 방식에서 빠진다
    assert res.covered == {"REP": "lora", "FIL": "lora-ensemble×3"}
    assert res.stats["unlocated"] == {"FIL": 1} and res.stats["fil_per_seed"] == [5, 4, 5]


def test_tag_habits_chunks_long_transcripts(three_fil, monkeypatch):
    monkeypatch.setenv("CHUCKCHUCK_LORA_CHUNK_CHARS", "200")
    words = [Word(text=("어" if i % 10 == 0 else "말씀입니다"), start_sec=i, end_sec=i + 0.5) for i in range(200)]
    t = Transcript(full_text="", words=words, by_slide=[SlideSpeech(1, 1, 0, 300, "", words)])

    class EchoFil:
        """청크마다 그 청크 안의 「어」 개수만큼 FIL 줄을 낸다."""
        def generate_batch(self, reqs):
            return [("\n".join(["FIL\t어"] * r.user_text.split().count("어")) if r.adapter.startswith("fil") else "NONE")
                    for r in reqs]

    res = LT.tag_habits(t, runner=EchoFil())
    assert res.stats["chunks"] > 1 and res.stats["rows"] == res.stats["chunks"] * 4
    assert sum(1 for s in res.spans if s.kind == "FIL") == 20
    assert [s.start_sec for s in res.spans][:3] == [0, 10, 20]


def test_tag_habits_rejects_short_runner_output(three_fil):
    class Short:
        def generate_batch(self, reqs):
            return ["NONE"]
    with pytest.raises(RuntimeError):
        LT.tag_habits(_talk(), runner=Short())


# ─── F-18 통합 ────────────────────────────────────────────────────────────────

def test_extract_habits_uses_fil_lora_and_reports_detectors(three_fil, monkeypatch):
    runner = FakeRunner({"rep": "NONE", "fil0": "FIL\t음", "fil1": "FIL\t음", "fil2": "FIL\t음"})
    real = LT.tag_habits
    monkeypatch.setattr(LT, "tag_habits", lambda tr: real(tr, runner=runner))
    d = extract_habits(_talk(), provider="lora")
    assert d.provider == "lora"
    assert d.detectors == {"REP": "lora", "FIL": "lora-ensemble×3", "PAUSE": "rule"}
    # LoRA 가 맡은 태그는 LoRA 만 — REP 는 「찾아 봤는데 없다」, 규칙이 셌을 간투어 5개는 안 섞인다
    assert (d.repeat_cnt, d.filler_cnt) == (0, 1)
    assert HabitDoc.from_dict(d.to_dict()).detectors == d.detectors


def test_extract_habits_rep_only_keeps_rule_filler(hermetic, monkeypatch):
    _adapter(hermetic / "runs" / "rep_seed42" / "final")
    runner = FakeRunner({"rep": "REP\t지도 지도력은"})
    real = LT.tag_habits
    monkeypatch.setattr(LT, "tag_habits", lambda tr: real(tr, runner=runner))
    d = extract_habits(_talk(), provider="lora")
    assert d.detectors == {"REP": "lora", "FIL": "rule", "PAUSE": "rule"}
    assert d.repeat_cnt == 1 and d.filler_cnt == 5   # 규칙(FILLERS 사전): 어×3 · 음×2


def test_extract_habits_loading_and_failure_fall_back(three_fil, monkeypatch):
    def not_ready(tr):
        raise LT.LoraNotReady("loading")
    monkeypatch.setattr(LT, "tag_habits", not_ready)
    d = extract_habits(_talk(), provider="lora")
    assert d.provider == "heuristic(lora-loading)" and d.detectors["FIL"] == "rule"
    monkeypatch.setattr(LT, "tag_habits", lambda tr: 1 / 0)
    assert extract_habits(_talk(), provider="lora").provider == "heuristic(lora-fallback)"


def test_extract_habits_without_adapters_falls_back(hermetic):
    d = extract_habits(_talk(), provider="lora")
    assert d.provider == "heuristic(lora-fallback)"
    assert d.detectors == {"REP": "rule", "FIL": "rule", "PAUSE": "rule"}


def test_preload_lora_respects_provider_and_missing_adapters(hermetic, monkeypatch):
    monkeypatch.setenv("HABIT_PROVIDER", "heuristic")
    assert f18_habits.preload_lora() is False
    monkeypatch.setenv("HABIT_PROVIDER", "lora")
    assert f18_habits.preload_lora() is False        # 어댑터 없음


# ─── 런타임 (모델 없이) ───────────────────────────────────────────────────────

@pytest.fixture
def fresh_runtime(monkeypatch):
    for name, val in (("_runner", None), ("_runner_key", None), ("_load_error", None),
                      ("_failed_key", None), ("_failed_at", 0.0)):
        monkeypatch.setattr(RT, name, val)
    monkeypatch.setattr(RT, "_loading", threading.Event())
    return RT


def test_preload_then_get_runner(three_fil, fresh_runtime, monkeypatch):
    gate = threading.Event()

    class SlowRunner:
        def __init__(self, cfg):
            gate.wait(5)
            self.cfg, self.load_sec = cfg, 0.0

    monkeypatch.setattr(RT, "MidmLoraRunner", SlowRunner)
    cfg = LT.load_config({})
    assert RT.preload(cfg) is True and RT.preload(cfg) is False
    with pytest.raises(LT.LoraNotReady):
        RT.get_runner(cfg, wait=False)
    gate.set()
    r = RT.get_runner(cfg, wait=True)
    assert isinstance(r, SlowRunner) and RT.get_runner(cfg) is r
    assert RT.state()["ready"] is True


def test_failed_load_is_not_retried_every_request(three_fil, fresh_runtime, monkeypatch):
    built = []

    class Boom:
        def __init__(self, cfg):
            built.append(1)
            raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(RT, "MidmLoraRunner", Boom)
    cfg = LT.load_config({})
    for _ in range(3):
        with pytest.raises(RuntimeError):
            RT.get_runner(cfg)
    assert len(built) == 1 and "out of memory" in RT.state()["error"]
    monkeypatch.setenv("CHUCKCHUCK_LORA_RETRY_SEC", "0")
    with pytest.raises(RuntimeError):
        RT.get_runner(cfg)
    assert len(built) == 2


def test_generate_batch_orders_groups_and_falls_back_to_per_adapter():
    r = object.__new__(RT.MidmLoraRunner)
    r.cfg = type("C", (), {"max_batch": 2})()
    r.gen_lock = threading.Lock()
    r.mixed_ok = True
    seen = []

    def run(group, mixed):
        seen.append((mixed, [g.adapter for g in group]))
        if mixed:
            raise TypeError("adapter_names unsupported")
        return [f"{g.adapter}:{g.user_text}" for g in group]

    r._run = run
    reqs = [LT.GenRequest(a, "s", u, 1.0, 8) for a, u in (("rep", "aaaa"), ("fil0", "b"), ("fil1", "cc"))]
    out = r.generate_batch(reqs)
    assert out == ["rep:aaaa", "fil0:b", "fil1:cc"]           # 요청 순서로 돌려준다
    assert seen[0] == (True, ["fil0", "fil1"])                 # 짧은 프롬프트부터 2개씩
    assert r.mixed_ok is False and all(not m for m, _ in seen[1:])


def test_row_repetition_penalty_matches_hf_and_skips_padding():
    torch = pytest.importorskip("torch")
    tr = pytest.importorskip("transformers")
    scores = torch.tensor([[2.0, -1.0, 0.5, 3.0], [2.0, -1.0, 0.5, 3.0]])
    ids = torch.tensor([[3, 0, 1], [3, 0, 1]])
    proc = RT.RowRepetitionPenalty([1.2, 1.0], [1, 0])        # 0행: 맨 앞 토큰(3)은 패딩
    out = proc(ids, scores.clone())
    ref = tr.RepetitionPenaltyLogitsProcessor(1.2)(torch.tensor([[0, 1]]), scores[:1].clone())
    assert torch.allclose(out[0], ref[0])                      # 패딩 뺀 한 줄 생성과 같다
    assert out[0, 3] == 3.0                                    # 패딩 토큰은 벌하지 않는다
    assert torch.equal(out[1], scores[1])                      # rp 1.0 행은 그대로
