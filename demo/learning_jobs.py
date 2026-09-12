"""
동의 세션 → 학습 자산 (평가 묶음 · 또래 기준표). 브리지가 하루 한 번, 사람이 CLI 로 아무 때나.

왜 여기(`demo/`)에 있나 — `examples/*.py` 는 스크립트라 브리지가 import 하지 못한다. 로직은
여기 한 곳에 두고, `examples/build_eval_bundle.py` · `build_peer_norms.py` 는 CLI 껍데기로 남긴다.

규칙 (PRIVACY.md 「학습에 쓰는 것과 안 쓰는 것」):
- **동의 세션만** (`SessionArchive.iter_consented`). 동의 없는 세션은 캐시가 남아 있어도 읽지 않는다.
- 번들 출력 폴더는 **매번 비우고** 다시 만든다 — 사용자가 지운 세션이 export 에 남으면 「지웠어요」가 거짓이 된다.
- 동의 세션이 **0건이면 아무것도 쓰지 않는다** — 손으로 만든 평가 묶음이나 이전 표를 빈 것으로 덮지 않는다.
"""
from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

from chuckchuck.f22_peer_norm import MIN_N, bucket_key, build_norms, save_norms, session_metrics
from demo.session_archive import SessionArchive

#: 번들이 되려면 이 둘은 있어야 한다. 질문 생성이 그래프 위에서 돈다.
REQUIRED = ("slide_doc", "concept_graph")
#: 있으면 같이 싣는 것.
OPTIONAL = ("transcript", "concept_doc", "alignment_doc", "flow_diff", "question_doc",
            "pace_doc", "habit_doc", "rubric_score", "report_doc")
#: 또래 기준표에 넣는 산출물.
NORM_ARTIFACTS = ("transcript", "pace_doc", "habit_doc", "alignment_doc", "flow_diff")


# -- 평가 묶음 ----------------------------------------------------------------

def bundle_for(archive: SessionArchive, rec) -> dict | None:
    """세션 하나 → 번들 dict (`fixtures/live_qa_run.json` 과 같은 모양). 필수 산출물이 없으면 None."""
    arts = {k: archive.read_artifact(rec.session_id, k) for k in REQUIRED + OPTIONAL}
    if any(arts[k] is None for k in REQUIRED):
        return None
    disputes = [e for e in archive.read_stream(rec.session_id, "feedback") if e.get("kind") == "judgement_dispute"]
    return {
        "session_id": rec.session_id,
        "consent": True,
        "code_version": rec.code_version,
        "session": {
            "id": rec.session_id,
            "title": rec.title or rec.file_name,
            "context": rec.context,
            "created_at": rec.uploaded_at,
            "artifacts": {k: v for k, v in arts.items() if v is not None},
        },
        "qa_turns": archive.read_stream(rec.session_id, "qa_turns"),
        "disputes": disputes,
    }


def build_bundles(archive: SessionArchive, out_dir: Path, *, since: float = 0.0) -> list[Path]:
    """동의 세션 전부를 번들로. 출력 폴더는 비우고 새로 만든다."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for rec in archive.iter_consented():
        if rec.uploaded_at < since:
            continue
        bundle = bundle_for(archive, rec)
        if bundle is None:
            continue
        path = out_dir / f"{rec.session_id}.json"
        path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        written.append(path)
    return written


# -- 또래 기준표 --------------------------------------------------------------

def collect_norm_samples(archive: SessionArchive) -> list[tuple[str, dict]]:
    samples = []
    for rec in archive.iter_consented():
        art = {k: archive.read_artifact(rec.session_id, k) for k in NORM_ARTIFACTS}
        metrics = session_metrics(transcript=art["transcript"], pace=art["pace_doc"], habits=art["habit_doc"],
                                  alignment=art["alignment_doc"], flow=art["flow_diff"])
        if metrics:
            samples.append((bucket_key(rec.context), metrics))
    return samples


def build_norm_table(archive: SessionArchive, out: Path, *, min_n: int = MIN_N) -> dict:
    """표를 만들어 저장하고 요약을 돌려준다. 표본이 0이면 저장하지 않는다."""
    samples = collect_norm_samples(archive)
    buckets = Counter(b for b, _ in samples)
    norms = build_norms(samples, min_n=min_n)
    if samples:
        save_norms(out, norms, sessions=len(samples), buckets=dict(buckets), min_n=min_n)
    return {"sessions": len(samples), "buckets": dict(buckets), "norms": norms, "written": bool(samples)}


# -- 브리지가 부르는 한 방 -------------------------------------------------------

def refresh_learning_assets(archive: SessionArchive, *, bundles_dir: Path, norms_path: Path,
                            min_n: int = MIN_N) -> dict:
    """하루 한 번: 동의 세션 → 평가 묶음 + 또래 표. 예외는 밖으로 — 호출자가 로그로 삼킨다.

    동의 세션이 0건이면 **아무것도 쓰지 않는다.** 빈 결과로 기존 자산을 덮는 것이 최악이다."""
    consented = sum(1 for _ in archive.iter_consented())
    if consented == 0:
        return {"consented": 0, "bundles": 0, "norm_sessions": 0, "norm_rows": 0, "written": False}
    bundles = build_bundles(archive, bundles_dir)
    table = build_norm_table(archive, norms_path, min_n=min_n)
    return {"consented": consented, "bundles": len(bundles), "norm_sessions": table["sessions"],
            "norm_rows": len(table["norms"]), "written": True}
