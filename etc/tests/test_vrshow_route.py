"""
/VRShow — 가상 발표 스튜디오(studio.html)의 공개 주소 (2026-10-15 사용자 「도메인에 합치자 — /VRShow」, 공개로 결정).

    python -m pytest etc/tests/test_vrshow_route.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import server.bridge as bridge
from server.static_assets import static_access

WEB = Path(__file__).resolve().parents[2] / "main" / "web"


@pytest.mark.parametrize("path", ["/VRShow", "/vrshow", "/VRShow/", "/VRSHOW"])
def test_VRShow_는_스튜디오_페이지를_준다(path):
    assert bridge.standalone_page_for(path) == "/studio.html"


@pytest.mark.parametrize("path", ["/VRShowx", "/VRShow/extra", "/vr"])
def test_비슷한_주소는_스튜디오가_아니다(path):
    assert bridge.standalone_page_for(path) is None


def test_스튜디오_파일과_참조_자산은_공개다():
    assert static_access("/studio.html") == "public"
    html = (WEB / "studio.html").read_text(encoding="utf-8")
    refs = [r for r in re.findall(r'\b(?:href|src)="([^"#?]+)', html) if not re.match(r"^(?:[a-z]+:|//)", r)]
    assert refs
    for ref in refs:
        assert static_access("/" + ref.lstrip("/")) == "public", ref


def test_팀_주소_studio_는_그대로_팀_전용이다():
    assert bridge.team_page_for("/studio") == "/studio.html"
    assert bridge.standalone_page_for("/studio") is None


def test_report_v2_는_팀_전용_시제품이다():
    """Report 2.0 시제품(docs/report-v2/) — 승인 전 팀 전용. 실측 묶음(data/*.json)도 팀 전용."""
    assert bridge.team_page_for("/report-v2") == "/report_v2.html"
    assert static_access("/report_v2.html") == "team"
    assert static_access("/data/report_v2_rec.json") == "team"
    assert static_access("/js/report_graph.js") == "public"
