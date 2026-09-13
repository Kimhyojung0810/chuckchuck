"""
scripts/chk 의 순수 함수 검사 — 문지기(gate)·캐시 버전(bump)·장부 파서(ledger)·브리핑 표 파서(brief).

git·네트워크·pytest 실행은 부르지 않는다. 문지기 자체가 회귀하면 다른 회귀를 못 잡으므로 여기가 먼저다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from chk_lib import bump, gate, ledger, brief  # noqa: E402

INDEX = '''<link rel="icon" href="favicon.ico?v=qk13">
<link rel="stylesheet" href="css/app.css?v=ql2">
<script src="js/qa_live.js?v=ql3"></script>
<script src="js/app.js?v=ql3"></script>
<img src="favicon.ico?v=qk13">'''
APP_JS = '''x + '<iframe src="f11_reveal.html?embed=1&v=showcase6" title="발표 분석 과정" ' '''


# ---- gate ------------------------------------------------------------------

def test_pytest_summary_parse():
    assert gate.parse_pytest_summary("...\n830 passed, 7 skipped, 2 warnings in 5.18s\n")[:3] == (830, 0, 0)
    assert gate.parse_pytest_summary("2 failed, 828 passed in 5s")[:3] == (828, 2, 0)
    assert gate.parse_pytest_summary("1 error in 0.1s")[:3] == (0, 0, 1)
    # 요약이 아예 없으면(수집 단계에서 죽음) 오류로 본다 — tail 파이프에 가려진 실패가 두 번 커밋된 이유
    assert gate.parse_pytest_summary("Traceback ...")[2] == 1


def test_secret_patterns_catch_real_key_shapes_only():
    # 가짜 키를 실행 시점에 조립한다 — 이 파일 자체가 gate 의 비밀키 검사에 걸리면 안 되니까 (실제로 걸렸다, 09-13)
    up, awf, jwt = "up_" + "a" * 30, "awf_" + "B" * 22, "eyJ" + "c" * 40
    diff = "\n".join([
        "+UPSTAGE_API_KEY=" + up,
        "+headers = {'X-API-Key': '" + awf + "'}",
        "+Authorization: Bearer " + jwt,
        "+CHUCKCHUCK_LORA_PATH=/home/ubuntu/workspace/20_AIHub_data/runs/tagger_seed42/final",
        "+AX_STT_BATCH_MODEL=A.X_STT_note_batch",
        "+MIDM_API_KEY=local",
        "-OLD_KEY=" + up,                 # 지운 줄은 이미 이력에 있는 것 — 여기서 안 잡는다
        "+++ b/.env.example",
    ])
    hits = gate.find_secrets(diff)
    assert len(hits) == 3
    assert all(up not in h and awf not in h for h in hits), "출력에 키 원문이 그대로 나오면 안 된다"


def test_stale_assets_requires_bump_only_for_touched_referenced_files():
    files = ["demo/YEHS_demo/css/app.css", "demo/YEHS_demo/js/app.js", "demo/YEHS_demo/js/landing.js", "chuckchuck/x.py"]
    # 아무것도 안 올림 → app.css·app.js 둘 다 걸린다. landing.js 는 index.html 이 안 물어서 제외
    stale = gate.stale_assets(files, INDEX, INDEX, APP_JS, APP_JS)
    assert [s.split(" ")[0] for s in stale] == ["css/app.css", "js/app.js"]
    # 둘 다 올림 → 통과
    new = bump.bump_asset(bump.bump_asset(INDEX, "css/app.css", "ql3"), "js/app.js", "ql4")
    assert gate.stale_assets(files, INDEX, new, APP_JS, APP_JS) == []


def test_stale_reveal_checks_app_js_not_index():
    files = ["demo/YEHS_demo/f11_reveal.html"]
    assert len(gate.stale_assets(files, INDEX, INDEX, APP_JS, APP_JS)) == 1
    assert gate.stale_assets(files, INDEX, INDEX, APP_JS, bump.bump_reveal(APP_JS, "showcase7")) == []


def test_env_file_pattern():
    assert gate.ENV_FILE.search(".env")
    assert gate.ENV_FILE.search(".env.bak")
    assert gate.ENV_FILE.search("demo/.env.local")
    assert not gate.ENV_FILE.search(".env.example")
    assert not gate.ENV_FILE.search("docs/environment.md")


# ---- bump ------------------------------------------------------------------

def test_next_token():
    assert bump.next_token("ql3") == "ql4"
    assert bump.next_token("qkh") == "qkh2"
    assert bump.next_token("showcase6") == "showcase7"
    assert bump.next_token("qk13") == "qk14"


def test_bump_asset_replaces_every_reference():
    out = bump.bump_asset(INDEX, "favicon.ico", "qk14")
    assert out.count("favicon.ico?v=qk14") == 2 and "qk13" not in out
    assert "css/app.css?v=ql2" in out  # 다른 자산은 그대로


# ---- ledger ----------------------------------------------------------------

LEDGER = """# 장부

| 시각 | 전 | 후 | 판정 | 핵심 델타 | HEAD | 메모 |
|---|---|---|---|---|---|---|
| 2026-09-12 17:22 | a | b | REGRESSED | specificity_mean 3.33→4; rubric.overall_mean 4.14→3.66 | 504d8d8 | H1 첫 가설 |
| 2026-09-12 22:26 | c | d | IMPROVED | specificity_mean 3.67→4.67; grounding_mean 0.47→0.66 | 8e4e908 | persona school_project |
| 2026-09-12 23:02 | e | f | IMPROVED | grounding_mean 0.66→0.70 | f13dd52 | H9 |
"""


def test_ledger_series_baseline_then_improved_with_carry_forward():
    rows = ledger.parse_rows(LEDGER)
    assert [r["verdict"] for r in rows] == ["REGRESSED", "IMPROVED", "IMPROVED"]
    # 기준선은 지표가 처음 나온 줄의 「전」. 세 번째 줄은 특이도를 안 적었으니 앞 값(4.67)을 잇는다
    assert ledger.series(rows, "specificity_mean") == [("Baseline", 3.33), ("persona", 4.67), ("H9", 4.67)]
    assert ledger.series(rows, "grounding_mean") == [("Baseline", 0.47), ("persona", 0.66), ("H9", 0.70)]
    assert ledger.series(rows, "never_seen") == []


def test_ledger_svg_has_one_panel_per_metric():
    rows = ledger.parse_rows(LEDGER)
    svg = ledger.render_svg("t", rows, ["specificity_mean", "grounding_mean", "never_seen"])
    assert svg.count("<polyline") == 2 and "never_seen" not in svg


# ---- brief -----------------------------------------------------------------

MEETING = """## 2. 할 일
| # | 상태 | 할 일 | 담당 | 마감 | 근거 회의 |
|---|---|---|---|---|---|
| 1 | 🟡 | 소개자료 [초안](x.md) | **담당 미정** | **2026-09-16 (수) 18:00** | a |
| 2 | ✅ | 끝난 일 | 갑 | 2026-09-01 | b |

## 3. 달력
| 날짜 | 일정 | 비고 |
|---|---|---|
| **2026-09-16 (수) 18:00** | 부스 소개자료 제출 | 급함 |
| 2026-10-06 (화) ~ 10-08 (목) | **AI Festa 2026** | 3일 |
"""


def test_brief_parsers():
    import datetime as dt
    todos = brief.open_todos(MEETING)
    assert len(todos) == 1 and "담당 미정" in todos[0] and "**" not in todos[0] and "2026-09-16" in todos[0]
    ms = brief.milestones(MEETING, dt.date(2026, 9, 13))
    assert ms[0].startswith("   D-3") and "AI Festa 2026" in ms[1]
