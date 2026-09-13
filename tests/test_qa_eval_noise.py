"""
examples/qa_eval_noise.py — 반복 측정에서 잡음 폭을 실측해 PRIMARY 와 대조하는 도구의 순수 함수 검사.
파일·LLM 은 부르지 않는다. 폭 계산이 틀리면 루프가 잡음을 신호로 채택하거나 신호를 버린다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("qa_eval_noise", ROOT / "examples" / "qa_eval_noise.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _summ(spec_, ground, fallback, overall=None):
    s = {"specificity_mean": spec_, "grounding_mean": ground, "fallback": fallback}
    if overall is not None:
        s["rubric"] = {"overall_mean": overall}
    return s


def test_stats_and_suggest():
    st = mod.stats([3.33, 3.67, 4.33])
    assert st["n"] == 3 and abs(st["range"] - 1.0) < 1e-9 and st["min"] == 3.33
    assert mod.suggest_tol("specificity_mean", st) >= 1.0          # 범위보다 작게 제안하지 않는다
    assert mod.suggest_tol("fallback", mod.stats([0, 3, 0])) == 3.0  # 정수 지표는 범위 그대로
    assert mod.suggest_tol("grounding_mean", mod.stats([0.5, 0.5])) == 0.0


def test_analyze_flags_narrow_and_wide(monkeypatch):
    # PRIMARY 의 실제 폭은 실측으로 바뀐다 — 판정 논리만 검사하도록 폭을 고정한다
    monkeypatch.setattr(mod, "PRIMARY", (("specificity_mean", "up", 0.5), ("grounding_mean", "up", 0.05),
                                         ("fallback", "down", 0), ("judge.gist_passed", "up", 0),
                                         ("rubric.overall_mean", "up", 0.5)))
    rows = {r["metric"]: r for r in mod.analyze([_summ(3.33, 0.50, 0, 4.0), _summ(4.33, 0.52, 0, 4.1), _summ(3.67, 0.51, 3, 4.0)])}
    assert rows["specificity_mean"]["verdict"] == "좁다"     # 범위 1.0 > 폭 0.5 — 잡음이 신호로 채택된다
    assert rows["fallback"]["verdict"] == "좁다"             # 0→3 이 같은 코드에서 나왔다 (09-12 실제)
    assert rows["rubric.overall_mean"]["verdict"] == "넓다"  # 범위 0.1 인데 폭 0.5
    assert rows["grounding_mean"]["verdict"] == "맞다"
    assert rows["judge.gist_passed"]["verdict"] == "n/a"    # 판정을 안 돌린 측정


def test_render_mentions_counts():
    text = mod.render({"g": mod.analyze([_summ(3, 0.5, 0), _summ(3, 0.5, 0)])})
    assert "반복 2회" in text and "폭이 좁은 지표 0개" in text
    assert mod.group_name("*_rep*-ax-20260913.json") == "rep-ax-20260913"
