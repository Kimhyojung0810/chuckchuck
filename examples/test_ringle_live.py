"""
RINGLE PDF·녹음으로 실API 파이프라인을 돌려 보는 테스트 스크립트입니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chuckchuck.config import load_dotenv

load_dotenv()

from chuckchuck import Context, extract_concepts, parse_document, transcribe
from chuckchuck.contracts import SlideMark
from chuckchuck.f01_parse import sparse_slide_numbers
from chuckchuck.providers.stt_impl import AxSTT

PDF = Path("/Users/gimhyojeong/Downloads/(최종)RINGLE 마케팅 공모전 PPT_SAIGHT.pdf")
AUDIO = Path("/Users/gimhyojeong/Downloads/새로운 녹음 20.m4a")
OUT = ROOT / "fixtures" / "live_ringle_test.json"


def main():
    print("=" * 60)
    print("1) F-01 Document Parse")
    print("=" * 60)
    print(f"  file={PDF.name} size={PDF.stat().st_size/1e6:.1f}MB")
    doc = parse_document(PDF)
    sparse = sparse_slide_numbers(doc)
    print(f"  ✅ slides={doc.total_slides}")
    print(f"  sparse/image-heavy: {sparse[:15]}{'...' if len(sparse)>15 else ''}")
    for s in doc.slides[:5]:
        print(f"  [{s.slide_no}] {s.title[:50] or '(제목없음)'} | {len(s.raw_text)} chars")

    print("\n" + "=" * 60)
    print("2) F-05 A.X STT")
    print("=" * 60)
    print(f"  file={AUDIO.name} size={AUDIO.stat().st_size/1e3:.1f}KB")
    full, words = AxSTT().transcribe(AUDIO)
    dur = max((w.end_sec for w in words), default=0.0)
    print(f"  ✅ text={full!r}")
    print(f"  words={len(words)} duration≈{dur:.2f}s")
    if words:
        print(f"  first={words[0].text!r} {words[0].start_sec}-{words[0].end_sec}")
        print(f"  last ={words[-1].text!r} {words[-1].start_sec}-{words[-1].end_sec}")

    # 녹음이 짧으면 앞 몇 장에만 균등 배분한 marks 로 분할 데모
    n = min(3, doc.total_slides) if dur > 0 else 1
    step = max(dur / n, 0.5)
    marks = [
        SlideMark(slide_no=i + 1, start_sec=i * step, end_sec=(i + 1) * step, visit=1)
        for i in range(n)
    ]
    # 마지막 구간을 실제 끝까지
    if marks:
        marks[-1].end_sec = max(dur, marks[-1].end_sec)

    t = transcribe(AUDIO, marks, provider="skt-ax")
    print("\n  슬라이드별 발화:")
    for s in t.by_slide:
        preview = s.text[:80] + ("…" if len(s.text) > 80 else "")
        print(f"    slide {s.slide_no}: {preview!r}")

    print("\n" + "=" * 60)
    print("3) F-06 개념 추출 (Solar) — 앞 5장")
    print("=" * 60)
    slim = doc
    slim.slides = doc.slides[:5]
    slim.total_slides = len(slim.slides)
    concepts = extract_concepts(
        slim,
        Context(situation="대회·IR 피칭", audience="심사위원", duration_min=5),
        llm="solar",
        transcript=t,
    )
    for s in concepts.slides:
        print(f"  [{s.slide_no}] topic={s.topic!r}")
        print(f"       keywords={s.keywords[:5]}")
        print(f"       concepts={s.concepts[:3]}")

    payload = {
        "slide_doc": doc.to_dict(),
        "transcript": t.to_dict(),
        "concepts_preview": concepts.to_dict(),
    }
    # 전체 SlideDoc 은 클 수 있어 slides raw 만 요약 저장
    payload["slide_doc"]["slides"] = [
        {
            "slide_no": s.slide_no,
            "title": s.title,
            "text_sparse": s.text_sparse,
            "raw_text": s.raw_text[:500],
        }
        for s in doc.slides
    ]
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
