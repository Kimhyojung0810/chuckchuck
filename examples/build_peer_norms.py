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

from chuckchuck.f22_peer_norm import MIN_N, bucket_key, build_norms, save_norms, session_metrics  # noqa: E402
from demo.session_archive import SessionArchive  # noqa: E402

DEFAULT_OUT = ROOT / "data" / "norms" / "percentile_table.json"


def collect(archive: SessionArchive) -> list[tuple[str, dict]]:
    samples = []
    for rec in archive.iter_consented():
        art = {k: archive.read_artifact(rec.session_id, k)
               for k in ("transcript", "pace_doc", "habit_doc", "alignment_doc", "flow_diff")}
        metrics = session_metrics(transcript=art["transcript"], pace=art["pace_doc"], habits=art["habit_doc"],
                                  alignment=art["alignment_doc"], flow=art["flow_diff"])
        if metrics:
            samples.append((bucket_key(rec.context), metrics))
    return samples


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=ROOT / "var" / "data")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--min-n", type=int, default=MIN_N)
    args = ap.parse_args()

    samples = collect(SessionArchive(args.data_dir))
    buckets = Counter(b for b, _ in samples)
    norms = build_norms(samples, min_n=args.min_n)
    save_norms(args.out, norms, sessions=len(samples), buckets=dict(buckets), min_n=args.min_n)

    print(f"세션 {len(samples)}건 · 버킷 {len(buckets)}개 · 기준 {len(norms)}줄 → {args.out}")
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
