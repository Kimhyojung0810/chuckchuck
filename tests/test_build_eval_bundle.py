"""
동의 세션 → 측정 번들 변환을 고정합니다.

- 동의 없는 세션·필수 산출물이 없는 세션은 번들이 되지 않는다
- 출력 폴더는 매번 비운다 (지운 세션이 export 에 남지 않는다)
- 번들은 qa_eval.load_artifacts 가 그대로 읽는 모양이다
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from demo.session_archive import SessionArchive

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "examples" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
    archive.append(sid, "qa_turns", {"question_id": "q1", "answer": "x"})
    archive.append(sid, "feedback", {"kind": "judgement_dispute", "target_id": "q:q1:r1", "value": "wrong_verdict"})
    archive.append(sid, "feedback", {"kind": "question_vote", "target_id": "q1", "value": "up"})
    return sid


def test_동의_세션만_번들이_되고_폴더를_비운다(archive, tmp_path):
    mod = _load("build_eval_bundle")
    out = tmp_path / "bundles"
    out.mkdir()
    (out / "stale.json").write_text("{}")
    ok = _session(archive, consent=True)
    _session(archive, consent=False)
    _session(archive, consent=True, with_graph=False)

    written = mod.build_bundles(archive, out)
    assert [p.stem for p in written] == [ok]
    assert not (out / "stale.json").exists()

    bundle = json.loads(written[0].read_text(encoding="utf-8"))
    assert bundle["session"]["id"] == ok
    assert set(bundle["session"]["artifacts"]) == {"slide_doc", "concept_graph", "alignment_doc"}
    assert bundle["qa_turns"][0]["question_id"] == "q1"
    assert [d["kind"] for d in bundle["disputes"]] == ["judgement_dispute"]


def test_qa_eval_이_번들을_그대로_읽는다(archive, tmp_path):
    mod = _load("build_eval_bundle")
    sid = _session(archive, consent=True)
    written = mod.build_bundles(archive, tmp_path / "b")
    qa_eval = _load("qa_eval")
    art = qa_eval.load_artifacts(written[0])
    assert art["concept_graph"]["file_name"] == "a.pdf"
    assert art["slide_doc"]["total_slides"] == 1
