"""qa_eval_compare 의 순수 함수 — 판정 규칙이 뒤집히면 자율 루프가 나쁜 프롬프트를 채택한다."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("qa_eval_compare", ROOT / "examples" / "qa_eval_compare.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _summary(**over):
    base = {
        "specificity_mean": 4.0, "grounding_mean": 0.61, "fallback": 0,
        "honorifics_questions": 0, "impolite_questions": 3, "honorifics_judge": 1,
        "judge": {"gist_passed": "3/3", "unrelated_wrong": "3/3", "trap_agree_wrong": "1/1",
                  "trap_fixed_passed": "0/1"},
        "prompts": {"qa-questions": {"n": 1, "user_chars_mean": 8213.0, "noise_ratio_mean": 0.02, "sec_mean": 24.5}},
        "coach": {"step1_cites_slide": "3/3", "step1_choice_form": "3/3", "step1_quote_in_deck": "3/3",
                  "explain_cites_slide": "3/3", "honorifics": 0},
    }
    for k, v in over.items():
        if "." in k:
            a, b = k.split(".")
            base[a][b] = v
        else:
            base[k] = v
    return base


def test_ratio_strings_become_fractions():
    assert mod.as_number("3/3") == 1.0
    assert mod.as_number("1/4") == 0.25
    assert mod.as_number("-") is None
    assert mod.as_number("0/0") is None
    assert mod.as_number(4) == 4.0


def test_identical_summaries_are_noise():
    r = mod.compare(_summary(), _summary())
    assert r["verdict"] == "NOISE"
    assert all(row["state"] in ("same", "na") for row in r["rows"])


def test_small_float_drift_inside_tolerance_is_noise():
    r = mod.compare(_summary(), _summary(specificity_mean=4.4, grounding_mean=0.64))
    assert r["verdict"] == "NOISE"


def test_clear_gain_without_loss_is_improved():
    r = mod.compare(_summary(), _summary(**{"judge.trap_fixed_passed": "1/1", "impolite_questions": 0}))
    assert r["verdict"] == "IMPROVED"
    better = {row["key"] for row in r["rows"] if row["state"] == "better"}
    assert better == {"judge.trap_fixed_passed", "impolite_questions"}


def test_any_regression_beats_gains():
    # 특이도는 크게 올랐지만 폴백이 하나 생겼다 → 채택하면 안 된다
    r = mod.compare(_summary(), _summary(specificity_mean=6.0, fallback=1))
    assert r["verdict"] == "REGRESSED"


def test_down_metrics_use_direction():
    r = mod.compare(_summary(honorifics_judge=1), _summary(honorifics_judge=0))
    assert r["verdict"] == "IMPROVED"
    r = mod.compare(_summary(honorifics_judge=0), _summary(honorifics_judge=2))
    assert r["verdict"] == "REGRESSED"


def test_missing_section_is_not_a_regression():
    after = _summary()
    del after["coach"]
    r = mod.compare(_summary(), after)
    assert r["verdict"] == "NOISE"
    assert {row["state"] for row in r["rows"] if row["key"].startswith("coach.")} == {"na"}


def test_markdown_ends_with_verdict_and_lists_secondary():
    r = mod.compare(_summary(), _summary(**{"judge.trap_fixed_passed": "1/1"}))
    md = mod.render_markdown(r, "a", "b")
    assert "**판정: IMPROVED**" in md
    assert "qa-questions.sec_mean" in md
    assert "▲ 좋아짐" in md


def test_headline_names_only_changed_metrics():
    r = mod.compare(_summary(), _summary(fallback=2))
    assert mod.headline(r) == "fallback 0→2"
    assert mod.headline(mod.compare(_summary(), _summary())) == "잡음 폭 안"


def test_ledger_creates_header_then_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "LEDGER", tmp_path / "LEDGER.md")
    monkeypatch.setattr(mod, "git_head", lambda: "abc1234")
    r = mod.compare(_summary(), _summary(fallback=1))
    mod.append_ledger(r, "base", "v1", "가설 A")
    mod.append_ledger(r, "base", "v2", "가설 B")
    text = (tmp_path / "LEDGER.md").read_text(encoding="utf-8")
    assert text.count("| 시각 |") == 1
    assert text.count("REGRESSED") == 2
    assert "abc1234" in text and "가설 B" in text
