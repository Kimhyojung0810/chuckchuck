"""
Document Parse raw 응답을 fixtures에 덤프해 두는 예제입니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chuckchuck.config import load_dotenv

load_dotenv()

from chuckchuck.f01_parse import (  # noqa: E402
    RAW_DIR,
    describe_config,
    parse_document,
)

DEFAULT_PDF = Path(
    "/Users/gimhyojeong/Downloads/(최종)RINGLE 마케팅 공모전 PPT_SAIGHT.pdf"
)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF
    if not path.is_file():
        print(f"파일 없음: {path}")
        print("사용법: python examples/dump_parse_raw.py /path/to/deck.pdf")
        return 1

    print("=== Document Parse config ===")
    print(describe_config())
    print()
    print(f"dump → {RAW_DIR}")
    print(f"file  → {path} ({path.stat().st_size / 1e6:.1f} MB)")
    print("coordinates=True (스키마 실측)")
    print()

    # 52페이지 등이면 sync 한도/시간 이슈 → force_async
    force_async = path.stat().st_size > 5_000_000  # 대략 큰 덱
    doc = parse_document(
        path,
        force_async=force_async,
        coordinates=True,
        save_raw=True,
        timeout=600,
    )

    keys_files = sorted(RAW_DIR.glob("*.keys.json"), key=lambda p: p.stat().st_mtime)
    if not keys_files:
        print("keys.json 이 없습니다.")
        return 1
    keys_path = keys_files[-1]
    inv = json.loads(keys_path.read_text(encoding="utf-8"))

    print(f"✅ SlideDoc slides={doc.total_slides}")
    print(f"✅ raw inventory: {keys_path.name}")
    print(f"   element_count: {inv.get('element_count')}")
    print(f"   element_keys:  {list(inv.get('element_keys', {}).keys())}")
    print(f"   has_coordinates_any: {inv.get('has_coordinates_any')}")
    print(f"   font_like_keys: {inv.get('font_like_keys')}")
    print(f"   categories: {inv.get('categories')}")
    print(f"   nested_keys: {inv.get('nested_keys')}")
    print()
    print("다음: fixtures/raw/*.keys.json 보고 SCHEMA / 초안 필드를 채택·기각")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
