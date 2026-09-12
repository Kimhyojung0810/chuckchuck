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
- 로직은 `demo/learning_jobs.py` 에 있고 브리지가 하루 한 번 같은 것을 `var/data/derived/` 에 만든다.
- 판정 이의(`judgement_dispute`)는 `disputes` 로 같이 싣는다. 하네스가 그 (질문, 답) 쌍을
  다시 판정해 "이의 턴 판정 뒤집힘률" 을 볼 수 있다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from demo.learning_jobs import OPTIONAL, REQUIRED, bundle_for, build_bundles  # noqa: E402, F401
from demo.session_archive import SessionArchive  # noqa: E402

DEFAULT_OUT = ROOT / "exports" / "eval_bundles"


def _since_epoch(text: str | None) -> float:
    if not text:
        return 0.0
    return time.mktime(time.strptime(text, "%Y-%m-%d"))


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
