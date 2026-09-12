"""demo/learning_jobs — 브리지가 하루 한 번 부르는 학습 자산 갱신.

핵심 불변식: 동의 세션이 0건이면 **아무것도 쓰지 않는다.** 데이터 디렉터리를 잘못 잡은 채
돌아도 손으로 만든 평가 묶음이나 이전 또래 표를 빈 것으로 덮지 않는다."""
from __future__ import annotations

import json

import pytest

from demo.learning_jobs import build_bundles, refresh_learning_assets
from demo.session_archive import SessionArchive


@pytest.fixture
def archive(tmp_path):
    return SessionArchive(tmp_path / "data")


def _session(archive, *, consent, with_graph=True):
    sid = archive.new_id()
    archive.open(sid, consent=consent, file_name="a.pdf", ext=".pdf", upload=b"%PDF", title="a")
    archive.put_artifact(sid, "slide_doc", {"file_name": "a.pdf", "total_slides": 1, "slides": []})
    if with_graph:
        archive.put_artifact(sid, "concept_graph", {"file_name": "a.pdf", "nodes": [], "edges": [], "sections": []})
    archive.put_artifact(sid, "alignment_doc", {"items": [], "summary": {"coverage": 0.5}})
    return sid


def test_zero_consented_sessions_write_nothing(archive, tmp_path):
    _session(archive, consent=False)
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    (bundles / "handmade.json").write_text("{}")
    norms = tmp_path / "norms.json"
    norms.write_text('{"norms": [{"keep": "me"}]}')

    out = refresh_learning_assets(archive, bundles_dir=bundles, norms_path=norms)

    assert out == {"consented": 0, "bundles": 0, "norm_sessions": 0, "norm_rows": 0, "written": False}
    assert (bundles / "handmade.json").exists()
    assert json.loads(norms.read_text())["norms"] == [{"keep": "me"}]


def test_consented_session_becomes_bundle_and_table(archive, tmp_path):
    ok = _session(archive, consent=True)
    _session(archive, consent=False)
    bundles, norms = tmp_path / "bundles", tmp_path / "norms.json"

    out = refresh_learning_assets(archive, bundles_dir=bundles, norms_path=norms)

    assert out["consented"] == 1 and out["bundles"] == 1 and out["written"] is True
    assert [p.stem for p in bundles.glob("*.json")] == [ok]
    table = json.loads(norms.read_text(encoding="utf-8"))
    assert table["sessions"] == 1 and table["norms"] == []      # n < min_n → 줄은 없지만 표는 남는다
    assert out["norm_rows"] == 0


def test_bundle_dir_is_rebuilt_each_time(archive, tmp_path):
    _session(archive, consent=True)
    out = tmp_path / "b"
    out.mkdir()
    (out / "stale.json").write_text("{}")
    written = build_bundles(archive, out)
    assert len(written) == 1 and not (out / "stale.json").exists()
