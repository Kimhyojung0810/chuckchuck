"""
RINGLE 자료의 raw 파싱 결과와 후처리 SlideDoc을 비교하는 예제입니다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chuckchuck.config import load_dotenv

load_dotenv()

from chuckchuck.f01_parse import (  # noqa: E402
    RAW_DIR,
    _elements_to_slides,
    parse_document,
)

DEFAULT_PDF = Path(
    "/Users/gimhyojeong/Downloads/(최종)RINGLE 마케팅 공모전 PPT_SAIGHT.pdf"
)
RAW_GLOB = "*RINGLE*.upstage.json"
OUT_COMPARE = RAW_DIR / "ringle_raw_vs_ours_example.json"
OUT_MD = ROOT / "docs" / "examples" / "ringle_parse_compare.md"


def _clip_el(el: dict, text_limit: int | None = None) -> dict:
    """text_limit 이 None 이면 전문 유지."""
    text = ((el.get("content") or {}).get("text") or "")
    if text_limit is not None and len(text) > text_limit:
        text = text[:text_limit] + f"…(+{len(text) - text_limit}자)"
    out = {
        "id": el.get("id"),
        "page": el.get("page"),
        "category": el.get("category"),
        "text": text,
    }
    coords = el.get("coordinates")
    if coords:
        xs = [p["x"] for p in coords if isinstance(p, dict) and "x" in p]
        ys = [p["y"] for p in coords if isinstance(p, dict) and "y" in p]
        if xs and ys:
            out["bbox"] = {
                "x0": round(min(xs), 4),
                "y0": round(min(ys), 4),
                "x1": round(max(xs), 4),
                "y1": round(max(ys), 4),
            }
    return out


def _clip_ours_slide(slide: dict, text_limit: int | None = None) -> dict:
    """text_limit 이 None 이면 전문 유지 (기본)."""
    out = dict(slide)
    if text_limit is None:
        return out
    blocks = []
    for b in slide.get("blocks", []):
        t = b.get("text", "")
        if len(t) > text_limit:
            t = t[:text_limit] + f"…(+{len(t) - text_limit}자)"
        blocks.append({"category": b["category"], "text": t})
    out["blocks"] = blocks
    rt = out.get("raw_text", "")
    if len(rt) > text_limit * 2:
        out["raw_text"] = rt[: text_limit * 2] + f"…(+{len(rt) - text_limit * 2}자)"
    return out


def _pick_slide_no(elements: list[dict]) -> int:
    """header/footer + heading + visual 이 있는 장을 고른다. (가능하면 중간 장)"""
    by_page: dict[int, list[dict]] = {}
    for el in elements:
        by_page.setdefault(int(el.get("page", 1)), []).append(el)
    scored: list[tuple[int, int]] = []
    for page, els in by_page.items():
        cats = [e.get("category") for e in els]
        score = 0
        if "header" in cats or "footer" in cats:
            score += 3
        if "heading1" in cats:
            score += 2
        if "chart" in cats:
            score += 3
        if any(c in cats for c in ("figure", "table")):
            score += 1
        scored.append((score, page))
    scored.sort(reverse=True)
    return scored[0][1] if scored else 1


def build_compare(raw_body: dict, file_name: str) -> dict:
    elements = raw_body.get("elements") or []
    slides = _elements_to_slides(elements)
    doc = {
        "file_name": file_name,
        "total_slides": len(slides),
        "slides": [s.to_dict() for s in slides],
    }
    slide_no = _pick_slide_no(elements)
    raw_page = [_clip_el(e) for e in elements if int(e.get("page", 1)) == slide_no]
    ours_full = next(s for s in doc["slides"] if s["slide_no"] == slide_no)
    ours = _clip_ours_slide(ours_full)
    dropped = [e for e in raw_page if e.get("category") in ("header", "footer")]

    return {
        "note": "Document Parse raw 한 장 vs 채택 스펙 SlideDoc 한 장 (전문)",
        "file_name": file_name,
        "slide_no": slide_no,
        "raw_element_count_on_page": len(raw_page),
        "raw_page_elements": raw_page,
        "dropped_as_noise": dropped,
        "ours_slide": ours,
        "diff_summary": {
            "raw_categories": sorted({e.get("category") for e in raw_page}),
            "ours_categories": ours.get("categories"),
            "removed": sorted({e.get("category") for e in dropped}),
            "ours_metrics": {
                "total_char_count": ours_full["total_char_count"],
                "line_count": ours_full["line_count"],
                "has_visual": ours_full["has_visual"],
                "visual_type": ours_full["visual_type"],
                "alignment": ours_full["alignment"],
                "text_sparse": ours_full["text_sparse"],
                "image_only": ours_full["image_only"],
                "blocks_count": len(ours_full["blocks"]),
            },
        },
        "full_slidedoc_slide_count": doc["total_slides"],
    }


def to_markdown(cmp: dict) -> str:
    sn = cmp["slide_no"]
    lines = [
        f"# RINGLE Document Parse 비교 예시 (slide {sn}, 전문)",
        "",
        f"- 파일: `{cmp['file_name']}`",
        f"- raw elements on page: **{cmp['raw_element_count_on_page']}**",
        f"- 노이즈로 제거: `{cmp['diff_summary']['removed']}`",
        f"- 텍스트: **전문** (자르지 않음)",
        "",
        "## raw (Upstage elements, 해당 장)",
        "",
        "```json",
        json.dumps(cmp["raw_page_elements"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## ours (채택 스펙 SlideDoc 한 장)",
        "",
        "```json",
        json.dumps(cmp["ours_slide"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 한눈에",
        "",
        f"- raw categories → `{cmp['diff_summary']['raw_categories']}`",
        f"- ours categories → `{cmp['diff_summary']['ours_categories']}`",
        f"- metrics → `{json.dumps(cmp['diff_summary']['ours_metrics'], ensure_ascii=False)}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-raw", action="store_true", help="API 없이 기존 raw 사용")
    ap.add_argument("pdf", nargs="?", type=Path, default=DEFAULT_PDF)
    args = ap.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if args.from_raw:
        candidates = sorted(RAW_DIR.glob(RAW_GLOB), key=lambda p: p.stat().st_mtime)
        if not candidates:
            print(f"raw 없음: {RAW_DIR}/{RAW_GLOB}")
            return 1
        raw_path = candidates[-1]
        print(f"from raw: {raw_path}")
        raw_body = json.loads(raw_path.read_text(encoding="utf-8"))
        file_name = (raw_body.get("_chuckchuck_meta") or {}).get("source_file") or raw_path.name
    else:
        if not args.pdf.is_file():
            print(f"PDF 없음: {args.pdf}")
            return 1
        print(f"parse: {args.pdf}")
        doc = parse_document(
            args.pdf,
            force_async=args.pdf.stat().st_size > 5_000_000,
            coordinates=True,
            save_raw=True,
            timeout=600,
        )
        file_name = doc.file_name
        # 방금 저장한 raw
        candidates = sorted(RAW_DIR.glob(RAW_GLOB), key=lambda p: p.stat().st_mtime)
        raw_body = json.loads(candidates[-1].read_text(encoding="utf-8"))
        print(f"slides={doc.total_slides}")

    cmp = build_compare(raw_body, file_name)
    OUT_COMPARE.write_text(json.dumps(cmp, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(to_markdown(cmp), encoding="utf-8")

    # 전체 ours도 갱신
    slides = _elements_to_slides(raw_body.get("elements") or [])
    ours_path = RAW_DIR / "ringle_slidedoc_postprocess.json"
    ours_path.write_text(
        json.dumps(
            {
                "file_name": file_name,
                "total_slides": len(slides),
                "slides": [s.to_dict() for s in slides],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"✅ compare json: {OUT_COMPARE}")
    print(f"✅ compare md:   {OUT_MD}")
    print(f"✅ full ours:    {ours_path}")
    print(f"   slide_no={cmp['slide_no']}")
    print(f"   dropped={cmp['diff_summary']['removed']}")
    print(f"   metrics={cmp['diff_summary']['ours_metrics']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
