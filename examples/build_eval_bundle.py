"""
동의한 세션을 `examples/qa_eval.py` 가 읽는 번들로 바꾼다.

    python examples/build_eval_bundle.py                # var/data → exports/eval_bundles/
    python examples/build_eval_bundle.py --since 2026-09-01 --data-dir /var/lib/chuckchuck
    python examples/qa_eval.py --bundle-dir exports/eval_bundles --no-coach --limit 2

왜 — 측정 하네스는 지금까지 고정 fixture 한 개(`fixtures/live_qa_run.json`)로만 돌았다.
프롬프트를 고칠 때마다 "좋아진 것 같다" 가 아니라 실제 발표 N건의 평균±편차로 보려면
코퍼스가 필요하다. 번들 모양은 `live_qa_run.json` 과 같아서 하네스를 안 고친다.

- **동의 세션만** 쓴다 (`SessionArchive.iter_consented`). 동의 없는 세션은 파싱본·받아쓰기가
  캐시로 남아 있어도 건드리지 않는다.
- 출력 폴더를 **매번 비우고** 다시 만든다 — 사용자가 지운 세션이 export 에 남으면
  「지웠어요」 가 거짓이 된다.
- 판정 이의(`judgement_dispute`)는 `disputes` 로 같이 싣는다. 하네스가 그 (질문, 답) 쌍을
  다시 판정해 "이의 턴 판정 뒤집힘률" 을 볼 수 있다.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from demo.session_archive import SessionArchive  # noqa: E402

DEFAULT_OUT = ROOT / "exports" / "eval_bundles"

#: 번들이 되려면 이 둘은 있어야 한다. 질문 생성이 그래프 위에서 돈다.
REQUIRED = ("slide_doc", "concept_graph")
#: 있으면 같이 싣는 것.
OPTIONAL = ("transcript", "concept_doc", "alignment_doc", "flow_diff", "question_doc",
            "pace_doc", "habit_doc", "rubric_score", "report_doc")


def _since_epoch(text: str | None) -> float:
    if not text:
        return 0.0
    return time.mktime(time.strptime(text, "%Y-%m-%d"))


def bundle_for(archive: SessionArchive, rec) -> dict | None:
    """세션 하나 → 번들 dict. 필수 산출물이 없으면 None."""
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=ROOT / "var" / "data")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--since", default=None, help="YYYY-MM-DD 이후 업로드만")
    args = ap.parse_args()

    archive = SessionArchive(args.data_dir)
    written = build_bundles(archive, args.out, since=_since_epoch(args.since))
    total = sum(1 for _ in archive.iter_consented())
    print(f"동의 세션 {total}건 중 번들 {len(written)}건 → {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}")
    for p in written:
        b = json.loads(p.read_text(encoding="utf-8"))
        arts = b["session"]["artifacts"]
        print(f"  {p.stem}  {b['session']['title'][:30]:<30} 산출물 {len(arts):>2} · QA {len(b['qa_turns'])}턴 · 이의 {len(b['disputes'])}")
    if not written:
        print("  (없음) — 자료를 올릴 때 「학습에 써도 좋아요」 를 켠 발표가 분석까지 끝나야 쌓여요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
