"""
[F-01] 발표자료(PDF/PPTX)를 읽어 슬라이드 구조로 바꾸는 모듈입니다.
Upstage Document Parse를 호출해 SlideDoc을 만듭니다.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

from .contracts import ParseError, Slide, SlideBlock, SlideDoc

API_URL = os.environ.get(
    "UPSTAGE_DOCPARSE_URL",
    "https://api.upstage.ai/v1/document-digitization",
)
ASYNC_URL = os.environ.get(
    "UPSTAGE_DOCPARSE_ASYNC_URL",
    "https://api.upstage.ai/v1/document-digitization/async",
)
POLL_URL = "https://api.upstage.ai/v1/document-digitization/requests/{rid}"
MODEL = os.environ.get("UPSTAGE_DOCPARSE_MODEL", "document-parse")
# 발표자료는 도식·차트 많음 → auto (페이지별 standard/enhanced 자동)
MODE = os.environ.get("UPSTAGE_DOCPARSE_MODE", "auto")
OCR = os.environ.get("UPSTAGE_DOCPARSE_OCR", "auto")
OUTPUT_FORMATS = os.environ.get(
    "UPSTAGE_DOCPARSE_OUTPUT_FORMATS",
    '["html", "markdown", "text"]',
)
# 기본 false. raw 스키마 실측 시 true (dump_parse_raw / SAVE_PARSE_RAW)
COORDINATES = os.environ.get("UPSTAGE_DOCPARSE_COORDINATES", "false").strip().lower() in (
    "1",
    "true",
    "yes",
)
SAVE_PARSE_RAW = os.environ.get("SAVE_PARSE_RAW", "").strip().lower() in (
    "1",
    "true",
    "yes",
)
RAW_DIR = Path(
    os.environ.get(
        "UPSTAGE_PARSE_RAW_DIR",
        str(Path(__file__).resolve().parent.parent / "fixtures" / "raw"),
    )
)

ALLOWED_EXT = {".pdf", ".pptx"}
MAX_MB = 30          # 제품 스펙. Upstage 한도는 50MB
# 제품 UI 권장은 30장, Upstage sync 한도는 100p. 데모/실측용으로 env 로 조절 가능.
MAX_SLIDES = int(os.environ.get("CHUCKCHUCK_MAX_SLIDES", "100"))
ASYNC_THRESHOLD_PAGES = int(
    os.environ.get("UPSTAGE_DOCPARSE_USE_ASYNC_THRESHOLD_PAGES", "10")
)

TITLE_CATEGORIES = {"heading1", "heading2", "title"}
NOISE_CATEGORIES = {"header", "footer"}
VISUAL_TYPE_ORDER = ("figure", "chart", "table", "image")
VISUAL_CATEGORIES = set(VISUAL_TYPE_ORDER)
SPARSE_CHAR_THRESHOLD = 20
ALIGN_LEFT_MAX = 0.40
ALIGN_RIGHT_MIN = 0.60


def _api_key() -> str:
    key = os.environ.get("UPSTAGE_API_KEY", "").strip()
    if not key:
        raise ParseError(
            "UPSTAGE_API_KEY 가 없습니다.\n"
            "1) https://console.upstage.ai 로그인\n"
            "2) API Keys → Create New Key\n"
            "3) .env 의 UPSTAGE_API_KEY= 에 붙여넣기"
        )
    return key


def _form_data(*, coordinates: bool | None = None) -> dict:
    use_coords = COORDINATES if coordinates is None else coordinates
    return {
        "model": MODEL,
        "mode": MODE,
        "ocr": OCR,
        "output_formats": OUTPUT_FORMATS,
        "chart_recognition": "true",
        "coordinates": "true" if use_coords else "false",
    }


def _validate(path: Path) -> None:
    if not path.exists():
        raise ParseError(f"파일이 없습니다: {path}")
    if path.suffix.lower() not in ALLOWED_EXT:
        raise ParseError(
            f"{path.suffix} 는 지원하지 않습니다. "
            f"{', '.join(sorted(ALLOWED_EXT))} 만 올려주세요."
        )
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_MB:
        raise ParseError(f"파일이 {size_mb:.1f}MB 입니다. {MAX_MB}MB 이하로 줄여주세요.")


def _call_sync(
    path: Path, key: str, timeout: int, *, coordinates: bool | None = None
) -> dict:
    with path.open("rb") as f:
        res = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {key}"},
            files={"document": (path.name, f)},
            data=_form_data(coordinates=coordinates),
            timeout=timeout,
        )
    if res.status_code != 200:
        raise ParseError(f"Document Parse 오류 {res.status_code}: {res.text[:300]}")
    return res.json()


def _merge_async_batches(status: dict, key: str) -> dict:
    """
    async 완료 응답은 sync 와 달리 batches[].download_url 에 결과가 있다.
    배치를 id 순으로 이어 붙여 elements 를 합친다.
    """
    batches = sorted(status.get("batches") or [], key=lambda b: b.get("id", 0))
    if not batches:
        # 구형 응답 호환
        if status.get("elements"):
            return status
        raise ParseError(f"async 완료인데 batches 가 없습니다: {status}")

    all_elements: list[dict] = []
    content_parts = {"text": [], "html": [], "markdown": []}

    for batch in batches:
        if batch.get("status") != "completed":
            raise ParseError(f"배치 실패: {batch}")
        url = batch.get("download_url")
        if not url:
            raise ParseError(f"download_url 없음: {batch}")
        r = requests.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=60)
        if r.status_code != 200:
            # download_url 은 보통 서명 URL — Authorization 없이 재시도
            r = requests.get(url, timeout=60)
        if r.status_code != 200:
            raise ParseError(f"배치 다운로드 실패 {r.status_code}: {r.text[:200]}")
        body = r.json()
        all_elements.extend(body.get("elements") or [])
        c = body.get("content") or {}
        for k in content_parts:
            if c.get(k):
                content_parts[k].append(c[k])

    return {
        "apiVersion": status.get("apiVersion"),
        "model": status.get("model", MODEL),
        "elements": all_elements,
        "content": {k: "\n".join(v) for k, v in content_parts.items() if v},
        "usage": {"pages": status.get("total_pages")},
    }


def _call_async(
    path: Path,
    key: str,
    timeout: int,
    poll_sec: float = 3.0,
    *,
    coordinates: bool | None = None,
) -> dict:
    with path.open("rb") as f:
        res = requests.post(
            ASYNC_URL,
            headers={"Authorization": f"Bearer {key}"},
            files={"document": (path.name, f)},
            data=_form_data(coordinates=coordinates),
            timeout=timeout,
        )
    if res.status_code != 200:
        raise ParseError(f"Document Parse(async) 오류 {res.status_code}: {res.text[:300]}")

    rid = res.json().get("request_id") or res.json().get("id")
    if not rid:
        raise ParseError(f"async 요청에 request_id가 없습니다: {res.text[:300]}")

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(poll_sec)
        r = requests.get(
            POLL_URL.format(rid=rid),
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
        )
        body = r.json()
        status = body.get("status")
        if status == "completed":
            return _merge_async_batches(body, key)
        if status == "failed":
            raise ParseError(
                f"파싱 실패: {body.get('failure_message') or body}"
            )
    raise ParseError(f"파싱이 {timeout}초 안에 끝나지 않았습니다. (request_id={rid})")


def _element_text(el: dict) -> str:
    content = el.get("content") or {}
    return (
        content.get("text")
        or content.get("markdown")
        or content.get("html")
        or ""
    ).strip()


def _bbox_center_x(coords: list | None) -> float | None:
    if not coords or not isinstance(coords, list):
        return None
    xs = [float(p["x"]) for p in coords if isinstance(p, dict) and "x" in p]
    if not xs:
        return None
    return (min(xs) + max(xs)) / 2.0


def _align_from_centers(centers: list[float], weights: list[float]) -> str | None:
    if not centers:
        return None
    if len(centers) != len(weights):
        weights = [1.0] * len(centers)
    wsum = sum(weights) or 1.0
    cx = sum(c * w for c, w in zip(centers, weights)) / wsum
    if cx < ALIGN_LEFT_MAX:
        return "left"
    if cx > ALIGN_RIGHT_MIN:
        return "right"
    return "center"


def _line_count(text: str) -> int:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return len(lines) if lines else (1 if text.strip() else 0)


def _elements_to_slides(elements: list[dict]) -> list[Slide]:
    """Upstage elements → SlideDoc slides (header/footer 제외 + 지표)."""
    by_page: dict[int, list[dict]] = {}
    for el in elements:
        page = int(el.get("page", 1))
        by_page.setdefault(page, []).append(el)

    slides: list[Slide] = []
    for page in sorted(by_page):
        els = by_page[page]
        blocks: list[SlideBlock] = []
        title = ""
        centers: list[float] = []
        weights: list[float] = []
        cats_order: list[str] = []

        for el in els:
            category = el.get("category", "paragraph")
            if category in NOISE_CATEGORIES:
                continue
            text = _element_text(el)
            if not text:
                if category in VISUAL_CATEGORIES and category not in cats_order:
                    cats_order.append(category)
                continue

            blocks.append(SlideBlock(category=category, text=text))
            if category not in cats_order:
                cats_order.append(category)
            if not title and category in TITLE_CATEGORIES:
                title = text

            cx = _bbox_center_x(el.get("coordinates"))
            if cx is not None:
                centers.append(cx)
                weights.append(float(max(len(text), 1)))

        for el in els:
            category = el.get("category", "")
            if category in NOISE_CATEGORIES:
                continue
            if category in VISUAL_CATEGORIES and category not in cats_order:
                cats_order.append(category)

        total_char = sum(len(b.text) for b in blocks)
        line_count = sum(_line_count(b.text) for b in blocks)
        visual_type = [c for c in VISUAL_TYPE_ORDER if c in cats_order]
        has_visual = bool(visual_type)
        text_sparse = total_char < SPARSE_CHAR_THRESHOLD

        slides.append(Slide(
            slide_no=page,
            title=title,
            blocks=blocks,
            categories=cats_order,
            total_char_count=total_char,
            line_count=line_count,
            has_visual=has_visual,
            visual_type=visual_type,
            alignment=_align_from_centers(centers, weights),
            text_sparse=text_sparse,
            image_only=(text_sparse and has_visual),
        ))
    return slides


def inventory_raw_elements(body: dict, *, sample_n: int = 3) -> dict:
    """
    Upstage raw 에서 element 키·category 분포를 뽑아 후처리 스키마 실측용으로 쓴다.
    ours 가 아님 — fixtures/raw/*.keys.json 전용.
    """
    elements = body.get("elements") or []
    key_counts: dict[str, int] = {}
    categories: dict[str, int] = {}
    nested: dict[str, set[str]] = {}
    samples: list[dict] = []

    for el in elements:
        if not isinstance(el, dict):
            continue
        for k in el:
            key_counts[k] = key_counts.get(k, 0) + 1
        cat = str(el.get("category", ""))
        if cat:
            categories[cat] = categories.get(cat, 0) + 1
        for nest_key in ("content", "coordinates", "base64_encoding"):
            if nest_key in el and isinstance(el[nest_key], dict):
                nested.setdefault(nest_key, set()).update(el[nest_key].keys())
            elif nest_key in el and isinstance(el[nest_key], list) and el[nest_key]:
                first = el[nest_key][0]
                if isinstance(first, dict):
                    nested.setdefault(nest_key, set()).update(first.keys())
        if len(samples) < sample_n:
            # 거대한 base64 는 인벤토리에서 자른다
            clip = dict(el)
            if isinstance(clip.get("base64_encoding"), str) and len(clip["base64_encoding"]) > 80:
                clip["base64_encoding"] = clip["base64_encoding"][:40] + f"…({len(el['base64_encoding'])} chars)"
            samples.append(clip)

    return {
        "apiVersion": body.get("apiVersion"),
        "model": body.get("model"),
        "element_count": len(elements),
        "element_keys": dict(sorted(key_counts.items(), key=lambda x: (-x[1], x[0]))),
        "categories": dict(sorted(categories.items(), key=lambda x: (-x[1], x[0]))),
        "nested_keys": {k: sorted(v) for k, v in sorted(nested.items())},
        "top_level_keys": sorted(body.keys()),
        "sample_elements": samples,
        "has_coordinates_any": any(
            isinstance(el, dict) and el.get("coordinates") for el in elements
        ),
        "font_like_keys": sorted(
            k for k in key_counts
            if "font" in k.lower() or "size" in k.lower() or "align" in k.lower()
        ),
    }


def save_parse_raw(
    body: dict,
    *,
    source_name: str,
    out_dir: str | Path | None = None,
    also_ours: SlideDoc | None = None,
) -> dict[str, Path]:
    """
    벤더 raw + 키 인벤토리를 fixtures/raw 에 저장한다.
    반환: {"raw": Path, "keys": Path, ...}
    """
    directory = Path(out_dir) if out_dir else RAW_DIR
    directory.mkdir(parents=True, exist_ok=True)
    stem = Path(source_name).stem
    # 파일명에 특수문자 정리
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)[:80] or "parse"

    raw_path = directory / f"{safe}.upstage.json"
    keys_path = directory / f"{safe}.keys.json"
    written: dict[str, Path] = {}

    raw_path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    written["raw"] = raw_path

    inv = inventory_raw_elements(body)
    inv["source_file"] = source_name
    inv["coordinates_requested"] = (
        body.get("_chuckchuck_meta", {}) or {}
    ).get("coordinates_requested")
    keys_path.write_text(
        json.dumps(inv, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    written["keys"] = keys_path

    if also_ours is not None:
        ours_path = directory / f"{safe}.slidedoc.json"
        ours_path.write_text(
            json.dumps(also_ours.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written["ours"] = ours_path

    return written


def parse_document(
    file_path: str | Path,
    *,
    timeout: int = 300,
    force_async: bool = False,
    coordinates: bool | None = None,
    save_raw: bool | str | Path | None = None,
) -> SlideDoc:
    """발표자료를 파싱해 SlideDoc으로 돌려준다.

    save_raw:
      True / 환경변수 SAVE_PARSE_RAW → fixtures/raw/ 에 raw+keys 저장
      Path/str → 그 디렉터리에 저장
    coordinates:
      None 이면 UPSTAGE_DOCPARSE_COORDINATES (기본 false)
      raw 실측 시 True 권장
    """
    path = Path(file_path)
    _validate(path)
    key = _api_key()

    use_async = force_async
    body = (
        _call_async(path, key, timeout, coordinates=coordinates)
        if use_async
        else _call_sync(path, key, timeout, coordinates=coordinates)
    )
    # 인벤토리용 메타 (벤더 필드 아님)
    use_coords = COORDINATES if coordinates is None else coordinates
    body = {
        **body,
        "_chuckchuck_meta": {
            "coordinates_requested": use_coords,
            "source_file": path.name,
        },
    }

    elements = body.get("elements", [])
    if not elements:
        # 실패해도 raw 는 남긴다 (스키마 실측)
        do_save = save_raw if save_raw is not None else SAVE_PARSE_RAW
        if do_save:
            out_dir = None
            if isinstance(do_save, (str, Path)) and str(do_save) not in ("1", "true", "True"):
                out_dir = Path(do_save)
            save_parse_raw(body, source_name=path.name, out_dir=out_dir)
        raise ParseError(
            "자료에서 아무 내용도 읽지 못했습니다. "
            "스캔 이미지 PDF라면 ocr=force 로 다시 시도하거나 "
            "텍스트가 살아있는 파일로 올려주세요."
        )

    slides = _elements_to_slides(elements)
    doc = SlideDoc(
        file_name=path.name,
        total_slides=len(slides),
        slides=slides,
    )

    # ours 변환 전/후와 무관하게 raw 먼저 확보
    do_save = save_raw if save_raw is not None else SAVE_PARSE_RAW
    if do_save:
        out_dir = None
        if isinstance(do_save, (str, Path)) and str(do_save) not in ("1", "true", "True"):
            out_dir = Path(do_save)
        save_parse_raw(body, source_name=path.name, out_dir=out_dir, also_ours=doc)

    # Upstage sync 한도(~100p)와 맞춤. CHUCKCHUCK_MAX_SLIDES 로 조절.
    if len(slides) > MAX_SLIDES:
        raise ParseError(
            f"{len(slides)}장입니다. 현재 {MAX_SLIDES}장까지 지원합니다."
            f" (raw 는 이미 저장됨: {RAW_DIR})"
        )

    # 장수가 많으면 다음부터 async 권장 신호 — 이번엔 이미 sync로 받았음
    _ = ASYNC_THRESHOLD_PAGES

    return doc


def sparse_slide_numbers(doc: SlideDoc) -> list[int]:
    """글자가 거의 없어 발화로 보완해야 하는 슬라이드 번호들."""
    return [s.slide_no for s in doc.slides if s.text_sparse]


def describe_config() -> str:
    """현재 Upstage Document Parse 설정 요약."""
    return json.dumps(
        {
            "model": MODEL,
            "mode": MODE,
            "ocr": OCR,
            "output_formats": OUTPUT_FORMATS,
            "coordinates": COORDINATES,
            "save_parse_raw": SAVE_PARSE_RAW,
            "raw_dir": str(RAW_DIR),
            "api_url": API_URL,
            "has_api_key": bool(os.environ.get("UPSTAGE_API_KEY", "").strip()),
        },
        ensure_ascii=False,
        indent=2,
    )
