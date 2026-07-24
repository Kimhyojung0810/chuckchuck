"""
Upstage Document Parse / Solar 연결이 되는지 확인하는 예제 스크립트입니다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# bridge 와 동일하게 .env 로드
from chuckchuck.config import load_dotenv

load_dotenv()

from chuckchuck.f01_parse import describe_config, parse_document  # noqa: E402
from chuckchuck.providers.llm_impl import SolarLLM  # noqa: E402


def main():
    print("=== Document Parse config ===")
    print(describe_config())
    print()

    key = os.environ.get("UPSTAGE_API_KEY", "").strip()
    if not key:
        print(
            "UPSTAGE_API_KEY 가 비어 있습니다.\n"
            "1) https://console.upstage.ai 로그인\n"
            "2) API Keys → Create New Key\n"
            "3) SSA/.env 의 UPSTAGE_API_KEY= 에 붙여넣기\n"
            "AI Initiative 참가팀이면 Solar Pro + Document Parse 무료(~2026-03-31)."
        )
        return 1

    print("=== Solar ping ===")
    try:
        text = SolarLLM().complete(
            system="한 줄로만 답한다.",
            user="ping 에 pong 이라고만 답해.",
            max_tokens=16,
        )
        print("solar:", text.strip())
    except Exception as e:
        print("solar 실패:", e)
        return 1

    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        print(f"\n=== Document Parse: {path.name} ===")
        doc = parse_document(path)
        print(f"slides={doc.total_slides}")
        for s in doc.slides[:5]:
            print(f"  [{s.slide_no}] {s.title or '(제목없음)'} sparse={s.text_sparse}")
            print(f"      {s.raw_text[:80]!r}")
    else:
        print("\nPDF/PPTX 경로를 인자로 주면 Document Parse 실호출을 합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
