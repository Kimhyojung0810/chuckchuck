"""
동의 세션 코퍼스에서 또래 기준표(`data/norms/percentile_table.json`)를 만든다 — F-22.

    python examples/build_peer_norms.py
    python examples/build_peer_norms.py --data-dir /var/lib/chuckchuck --min-n 20

라벨이 필요 없는 순수 통계라 코퍼스만 있으면 바로 만든다. 다만 **버킷(상황×길이) 하나에
n 이 20 미만이면 그 버킷은 표에 안 들어간다** — 그때 화면은 「아직 비교할 만큼 모이지
않았어요」 를 낸다. 데모 코퍼스는 한동안 이 밑일 것이다. 표를 먼저 만들어 두고, n 이 차면
리포트 카피(「또래 상위 N%」)를 붙인다.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chuckchuck.f22_peer_norm import MIN_N  # noqa: E402
from demo.learning_jobs import build_norm_table  # noqa: E402
from demo.session_archive import SessionArchive  # noqa: E402

DEFAULT_OUT = ROOT / "data" / "norms" / "percentile_table.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=ROOT / "var" / "data")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--min-n", type=int, default=MIN_N)
    args = ap.parse_args()

    table = build_norm_table(SessionArchive(args.data_dir), args.out, min_n=args.min_n)
    norms, buckets = table["norms"], Counter(table["buckets"])

    print(f"세션 {table['sessions']}건 · 버킷 {len(buckets)}개 · 기준 {len(norms)}줄 → "
          f"{args.out if table['written'] else '(동의 세션 0건 — 쓰지 않았어요)'}")
    for bucket, n in buckets.most_common():
        mark = "✓" if n >= args.min_n else f"✗ (n<{args.min_n})"
        print(f"  {bucket:<20} n={n:<4} {mark}")
    for n in norms:
        print(f"  {n.bucket:<20} {n.metric:<16} p10 {n.p10:>7} · p50 {n.p50:>7} · p90 {n.p90:>7}")
    if not norms:
        print("  아직 비교할 만큼 모이지 않았어요 — 표는 비어 있고 화면도 그렇게 말해요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
