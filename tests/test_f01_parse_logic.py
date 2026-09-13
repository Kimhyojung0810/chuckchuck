"""
F-01 후처리(Upstage raw → SlideDoc)의 순수 로직을 네트워크 없이 고정합니다.

파싱 결과는 F-06·F-07·채점이 전부 `slide_no` 로 조인해 쓰는 뿌리라서, 노이즈 제거·제목 승계·지표
(글자 수/줄 수/시각/정렬) 규칙이 조용히 바뀌면 화면 전체가 틀어집니다. `fixtures/raw/ringle_raw_vs_ours_
example.json` 의 한 장을 골든으로 잡고, 나머지는 DOCUMENT_PARSE_POSTPROCESS.md §2 의 규칙을 불변식으로
검사합니다. 스펙과 코드가 어긋나는 곳은 스펙대로 쓰고 `xfail(strict=True)` 로 결함을 기록합니다.
HTTP 는 `requests.post/get` 만 가짜로 바꿔 sync·async·배치 병합 경로를 탑니다.
"""

import json
import random
import re
from pathlib import Path

import pytest

import chuckchuck.f01_parse as f01
from chuckchuck.contracts import ParseError, SlideDoc

FIX = Path(__file__).resolve().parent.parent / "fixtures"


def el(category: str, text: str = "", *, page=1, x0=None, x1=None, **content) -> dict:
    """Upstage element 하나. x0/x1 을 주면 정규화 bbox 를 붙인다."""
    d: dict = {"page": page, "category": category, "content": {"text": text, **content}}
    if x0 is not None and x1 is not None:
        d["coordinates"] = [{"x": x0, "y": 0.1}, {"x": x1, "y": 0.1},
                            {"x": x1, "y": 0.2}, {"x": x0, "y": 0.2}]
    return d


def ringle_page10() -> tuple[list[dict], dict]:
    """골든 fixture 는 text/bbox 로 납작하게 저장돼 있어 raw 모양으로 되돌린다."""
    r = json.loads((FIX / "raw" / "ringle_raw_vs_ours_example.json").read_text("utf-8"))
    els = [{**el(e["category"], e["text"], page=e["page"], x0=e["bbox"]["x0"], x1=e["bbox"]["x1"]),
            "id": e["id"]} for e in r["raw_page_elements"]]
    return els, r["ours_slide"]


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code, self._payload, self.text = status_code, payload, text or json.dumps(payload)

    def json(self):
        return self._payload


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """raw 저장·키·네트워크를 전부 tmp/가짜로 돌린다. 실 fixtures/raw 를 건드리지 않는다."""
    monkeypatch.setattr(f01, "SAVE_PARSE_RAW", False)
    monkeypatch.setattr(f01, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setenv("UPSTAGE_API_KEY", "test-key")
    monkeypatch.setattr(f01.time, "sleep", lambda *_: None)
    monkeypatch.setattr(f01.requests, "post", lambda *a, **k: pytest.fail("post 호출 금지"))
    monkeypatch.setattr(f01.requests, "get", lambda *a, **k: pytest.fail("get 호출 금지"))
    return tmp_path


def _file(tmp_path, name="deck.pdf") -> Path:
    (p := tmp_path / name).write_bytes(b"x")
    return p


def test_validate_extension_existence_size(tmp_path, monkeypatch):
    for ext in (".txt", ".docx", ".ppt", ".key"):
        with pytest.raises(ParseError, match=rf"{re.escape(ext)} 는 지원하지 않습니다.*\.pdf, \.pptx"):
            f01._validate(_file(tmp_path, f"deck{ext}"))
    for ext in (".pdf", ".PDF", ".pptx", ".Pptx"):
        f01._validate(_file(tmp_path, f"deck{ext}"))
    with pytest.raises(ParseError, match="파일이 없습니다"):
        f01._validate(tmp_path / "없음.pdf")
    monkeypatch.setattr(f01, "MAX_MB", 0)
    with pytest.raises(ParseError, match="0MB 이하로"):
        f01._validate(_file(tmp_path))


def test_api_key_form_data_describe_config(monkeypatch):
    monkeypatch.setenv("UPSTAGE_API_KEY", "   ")
    with pytest.raises(ParseError, match="console.upstage.ai"):
        f01._api_key()
    monkeypatch.setenv("UPSTAGE_API_KEY", " k1 ")
    assert f01._api_key() == "k1"
    monkeypatch.setattr(f01, "COORDINATES", False)
    assert f01._form_data()["coordinates"] == "false"
    assert f01._form_data(coordinates=True)["coordinates"] == "true"
    assert set(f01._form_data()) == {"model", "mode", "ocr", "output_formats",
                                      "chart_recognition", "coordinates"}
    cfg = json.loads(f01.describe_config())
    assert cfg["has_api_key"] is True and "k1" not in f01.describe_config()
    doc = SlideDoc.from_dict(json.loads((FIX / "sample_slidedoc.json").read_text("utf-8")))
    assert f01.sparse_slide_numbers(doc) == [5]


def test_element_text_bbox_center_line_count():
    assert f01._element_text({"content": {"text": " 본문 ", "markdown": "md"}}) == "본문"
    assert f01._element_text({"content": {"text": "", "markdown": "md", "html": "<p>h</p>"}}) == "md"
    assert f01._element_text({"content": {"html": "<p>h</p>"}}) == "<p>h</p>"
    assert f01._element_text({"content": None}) == "" and f01._element_text({}) == ""
    assert f01._bbox_center_x(None) is None and f01._bbox_center_x([]) is None
    assert f01._bbox_center_x({"x": 1}) is None and f01._bbox_center_x([{"y": 1}, "junk"]) is None
    assert f01._bbox_center_x([{"x": 0.2}, {"x": 0.6}, {"x": 0.4}]) == pytest.approx(0.4)
    assert f01._line_count("") == 0 and f01._line_count("   ") == 0
    assert f01._line_count("한 줄") == 1 and f01._line_count("a\n\n b \n\n") == 2


# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_element_text_whitespace_text_falls_back_to_markdown():
    assert f01._element_text({"content": {"text": "  \n", "markdown": "본문"}}) == "본문"


def test_align_from_centers_boundaries_weighting_fallbacks():
    for cx, expected in [(0.39, "left"), (0.40, "center"), (0.60, "center"), (0.61, "right")]:
        assert f01._align_from_centers([cx], [1.0]) == expected
    assert f01._align_from_centers([], []) is None
    assert f01._align_from_centers([0.1, 0.9], [100.0, 1.0]) == "left"      # 글자 수 가중
    assert f01._align_from_centers([0.1, 0.9], [100.0]) == "center"         # 길이 불일치 → 균등


# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_align_from_centers_all_zero_weights_fall_back_to_equal():
    assert f01._align_from_centers([0.9], [0.0]) == "right"


def test_golden_ringle_page10_matches_pinned_spec_example():
    els, ours = ringle_page10()
    slides = f01._elements_to_slides(els)
    assert len(slides) == 1 and slides[0].to_dict() == ours
    assert not ({"header", "footer"} & set(slides[0].categories)) and slides[0].visual_type == ["figure", "chart", "table"]


def test_header_footer_dropped_and_title_is_first_heading():
    s = f01._elements_to_slides([
        el("header", "링글 공모전"), el("paragraph", "본문입니다"), el("footer", "10")])[0]
    assert [b.category for b in s.blocks] == ["paragraph"] and s.categories == ["paragraph"]
    assert s.total_char_count == len("본문입니다") and s.line_count == 1 and s.raw_text == "본문입니다"
    t = f01._elements_to_slides([
        el("paragraph", "p"), el("heading2", "둘째"), el("heading1", "첫째"), el("title", "t")])[0]
    assert t.title == "둘째"
    assert f01._elements_to_slides([el("paragraph", "제목 없음")])[0].title == ""
    assert f01._elements_to_slides([el("header", "머리글"), el("heading1", "")])[0].title == ""
    no_cat = f01._elements_to_slides([{"page": 1, "content": {"text": "카테고리 없음"}}])[0]
    assert no_cat.blocks[0].category == "paragraph" and no_cat.categories == ["paragraph"]


def test_visual_rules_caption_empty_figure_fixed_order():
    s = f01._elements_to_slides([el("caption", "그림 1"), el("paragraph", "본문")])[0]
    assert "caption" in s.categories and s.visual_type == [] and s.has_visual is False
    s = f01._elements_to_slides([el("figure", ""), el("paragraph", "짧다")])[0]
    assert [b.category for b in s.blocks] == ["paragraph"]
    assert s.categories == ["figure", "paragraph"] and s.visual_type == ["figure"]
    assert s.has_visual and s.text_sparse and s.image_only
    s = f01._elements_to_slides([el(c, "x") for c in ("chart", "image", "table", "figure")])[0]
    assert s.visual_type == list(f01.VISUAL_TYPE_ORDER)
    assert s.categories == ["chart", "image", "table", "figure"]


def test_slide_no_is_page_sorted_gaps_kept_noise_only_page_is_empty():
    s = f01._elements_to_slides([el("paragraph", "c", page=3), el("paragraph", "a", page=1),
                                 el("paragraph", "b", page="2")])
    assert [x.slide_no for x in s] == [1, 2, 3] and [x.raw_text for x in s] == ["a", "b", "c"]
    # 벤더가 element 를 하나도 안 준 페이지는 건너뛴다. 조인 키는 물리 페이지 번호를 유지한다.
    gap = f01._elements_to_slides([el("paragraph", "a"), el("paragraph", "c", page=3)])
    assert [x.slide_no for x in gap] == [1, 3] and f01._elements_to_slides([]) == []
    e = f01._elements_to_slides([el("paragraph", "본문", page=1), el("footer", "2", page=2)])[1]
    assert e.slide_no == 2 and e.blocks == [] and e.title == "" and e.raw_text == ""
    assert e.total_char_count == 0 and e.line_count == 0 and e.alignment is None
    assert e.has_visual is False and e.image_only is False and e.text_sparse is True


def test_text_sparse_threshold_and_alignment_weighting():
    for n, sparse in [(19, True), (20, False)]:
        s = f01._elements_to_slides([el("paragraph", "가" * n)])[0]
        assert s.total_char_count == n and s.text_sparse is sparse
    left_heavy = f01._elements_to_slides([
        el("paragraph", "왼쪽에 긴 본문이 있습니다", x0=0.0, x1=0.2),
        el("paragraph", "우", x0=0.9, x1=1.0),
        el("figure", "", x0=0.9, x1=1.0)])[0]        # 글 없는 시각 요소는 정렬에 안 들어간다
    assert left_heavy.alignment == "left"
    assert f01._elements_to_slides([el("paragraph", "좌표 없음")])[0].alignment is None
    assert f01._elements_to_slides([el("paragraph", "x", x0=0.7, x1=0.9)])[0].alignment == "right"


def _random_elements(rng: random.Random) -> list[dict]:
    cats = ["paragraph", "list", "heading1", "header", "footer", "figure", "chart", "table", "caption"]
    out = []
    for page in range(1, rng.randint(1, 6) + 1):
        for _ in range(rng.randint(0, 6)):
            text = "" if rng.random() < 0.3 else "글" * rng.randint(1, 30)
            x0 = rng.random() * 0.5 if rng.random() < 0.7 else None
            out.append(el(rng.choice(cats), text, page=page, x0=x0, x1=None if x0 is None else x0 + 0.3))
    rng.shuffle(out)
    return out


def test_invariants_on_random_inputs():
    """스펙 §2-2·2-6 의 불변식. 무작위 입력 200벌."""
    for seed in range(200):
        els = _random_elements(random.Random(seed))
        body_pages = {e["page"] for e in els if e["category"] not in f01.NOISE_CATEGORIES}
        slides = f01._elements_to_slides(els)
        nos = [s.slide_no for s in slides]
        assert nos == sorted(set(nos)) and set(nos) == {e["page"] for e in els}
        for s in slides:
            assert s.total_char_count == sum(len(b.text) for b in s.blocks)
            assert s.line_count == sum(f01._line_count(b.text) for b in s.blocks)
            assert s.text_sparse is (s.total_char_count < f01.SPARSE_CHAR_THRESHOLD)
            assert s.has_visual is bool(s.visual_type)
            assert s.image_only is (s.text_sparse and s.has_visual)
            assert s.visual_type == [c for c in f01.VISUAL_TYPE_ORDER if c in s.categories]
            assert not (set(s.categories) & f01.NOISE_CATEGORIES)
            assert len(s.categories) == len(set(s.categories))
            assert s.alignment in ("left", "right", "center", None)
            assert all(b.text for b in s.blocks)
            if s.slide_no not in body_pages:
                assert s.blocks == [] and s.categories == []
            if s.title:
                assert s.title in [b.text for b in s.blocks if b.category in f01.TITLE_CATEGORIES]


@pytest.mark.xfail(strict=True, reason="BUG: content.text 를 그대로 blocks 에 실어 figure 의 <figcaption> HTML·![image](...) 자리표시자와 table 의 <br> 이 raw_text 에 남는다. 스펙(§2-2 raw_text='정제 본문')과 어긋나고 F-06 프롬프트로 그대로 간다")
def test_raw_text_has_no_html_tags_or_image_placeholders():
    els, _ = ringle_page10()
    raw = f01._elements_to_slides(els)[0].raw_text
    assert not re.search(r"<[a-zA-Z/][^>]*>", raw) and "![image](" not in raw


@pytest.mark.xfail(strict=True, reason="BUG: Upstage 가 figure 마다 붙이는 영문 설명(수백 자)이 total_char_count 에 들어가 그림뿐인 장도 text_sparse=False/image_only=False 가 된다 (§2-6 '글은 거의 없고 시각자료가 있다')")
def test_figure_only_slide_is_image_only():
    els, _ = ringle_page10()
    s = f01._elements_to_slides([next(e for e in els if e["category"] == "figure")])[0]
    assert s.has_visual and s.text_sparse and s.image_only


def _batch_getter(bodies: dict, deny_with_auth=False):
    calls: list[bool] = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(bool(headers))
        if deny_with_auth and headers:
            return FakeResponse(403, {}, "signed url")
        return FakeResponse(200, bodies[url]) if url in bodies else FakeResponse(404, {}, "nope")
    return fake_get, calls


def test_merge_async_batches_concatenates_by_id_and_retries_without_auth(offline, monkeypatch):
    bodies = {"u1": {"elements": [el("paragraph", "1장", page=1)], "content": {"text": "A", "html": "<p>A</p>"}},
              "u2": {"elements": [el("paragraph", "2장", page=2)], "content": {"text": "B"}}}
    fake_get, calls = _batch_getter(bodies, deny_with_auth=True)
    monkeypatch.setattr(f01.requests, "get", fake_get)
    status = {"apiVersion": "v", "total_pages": 2, "batches": [
        {"id": 2, "status": "completed", "download_url": "u2"},
        {"id": 1, "status": "completed", "download_url": "u1"}]}
    out = f01._merge_async_batches(status, "k")
    assert [e["page"] for e in out["elements"]] == [1, 2]
    assert out["content"] == {"text": "A\nB", "html": "<p>A</p>"}
    assert out["usage"] == {"pages": 2} and out["model"] == f01.MODEL and out["apiVersion"] == "v"
    assert calls == [True, False, True, False]        # 인증 실패 → 서명 URL 재시도


def test_merge_async_batches_error_and_legacy_paths(offline, monkeypatch):
    monkeypatch.setattr(f01.requests, "get", _batch_getter({})[0])
    status = json.loads((FIX / "ringle_parse_status.json").read_text("utf-8"))
    with pytest.raises(ParseError, match="배치 실패"):   # fixture 의 batch 5 가 started
        f01._merge_async_batches({**status, "batches": [b for b in status["batches"] if b["id"] == 5]}, "k")
    with pytest.raises(ParseError, match="download_url 없음"):
        f01._merge_async_batches({"batches": [{"id": 1, "status": "completed"}]}, "k")
    with pytest.raises(ParseError, match="배치 다운로드 실패 404"):
        f01._merge_async_batches({"batches": [{"id": 1, "status": "completed", "download_url": "x"}]}, "k")
    legacy = {"elements": [el("paragraph", "a")]}
    assert f01._merge_async_batches(legacy, "k") is legacy
    with pytest.raises(ParseError, match="batches 가 없습니다"):
        f01._merge_async_batches({"status": "completed"}, "k")


def _async_env(monkeypatch, polls: list[dict], job: dict | None = None):
    job = job or json.loads((FIX / "ringle_parse_job.json").read_text("utf-8"))
    monkeypatch.setattr(f01.requests, "post", lambda *a, **k: FakeResponse(200, job))
    it = iter(polls)
    monkeypatch.setattr(f01.requests, "get", lambda *a, **k: FakeResponse(200, next(it)))


def test_call_async_poll_outcomes_and_request_errors(offline, monkeypatch, tmp_path):
    p = _file(tmp_path, "a.pptx")
    done = {"status": "completed", "elements": [el("paragraph", "끝")]}
    _async_env(monkeypatch, [{"status": "started"}, {"status": "started"}, done])
    assert f01._call_async(p, "k", timeout=30, poll_sec=0) is done
    _async_env(monkeypatch, [{"status": "failed", "failure_message": "손상된 파일"}])
    with pytest.raises(ParseError, match="파싱 실패: 손상된 파일"):
        f01._call_async(p, "k", timeout=30, poll_sec=0)
    _async_env(monkeypatch, [{"status": "started"}] * 50, job={"id": "rid-9"})
    with pytest.raises(ParseError, match=r"0초 안에 끝나지 않았습니다.*rid-9"):
        f01._call_async(p, "k", timeout=0, poll_sec=0)
    _async_env(monkeypatch, [], job={"foo": 1})
    with pytest.raises(ParseError, match="request_id가 없습니다"):
        f01._call_async(p, "k", 5)
    monkeypatch.setattr(f01.requests, "post", lambda *a, **k: FakeResponse(500, {}, "boom"))
    with pytest.raises(ParseError, match=r"\(async\) 오류 500"):
        f01._call_async(p, "k", 5)


def test_parse_document_validation_order_and_call_sync_errors(offline, monkeypatch, tmp_path):
    monkeypatch.delenv("UPSTAGE_API_KEY")
    with pytest.raises(ParseError, match="파일이 없습니다"):
        f01.parse_document(tmp_path / "x.pdf")
    with pytest.raises(ParseError, match="지원하지 않습니다"):
        f01.parse_document(_file(tmp_path, "x.hwp"))
    p = _file(tmp_path)
    with pytest.raises(ParseError, match="UPSTAGE_API_KEY"):
        f01.parse_document(p)
    monkeypatch.setattr(f01.requests, "post", lambda *a, **k: FakeResponse(400, {"e": 1}, "bad request"))
    with pytest.raises(ParseError, match="오류 400: bad request"):
        f01._call_sync(p, "k", 5)
    monkeypatch.setattr(f01.requests, "post", lambda *a, **k: FakeResponse(200, {"elements": [1]}))
    assert f01._call_sync(p, "k", 5, coordinates=True) == {"elements": [1]}


def test_parse_document_sync_vs_async_branch(offline, monkeypatch, tmp_path):
    p = _file(tmp_path, "deck.pptx")
    body = {"elements": [el("heading1", "제목", page=1), el("paragraph", "본문", page=2)]}
    used = []
    monkeypatch.setattr(f01, "_call_sync", lambda *a, **k: used.append("sync") or body)
    monkeypatch.setattr(f01, "_call_async", lambda *a, **k: used.append("async") or body)
    doc = f01.parse_document(p)
    assert used == ["sync"] and isinstance(doc, SlideDoc)
    assert doc.file_name == "deck.pptx" and doc.total_slides == 2
    assert [s.slide_no for s in doc.slides] == [1, 2] and doc.slides[0].title == "제목"
    f01.parse_document(p, force_async=True)
    assert used == ["sync", "async"]
    assert not (offline / "raw").exists()          # save_raw 없으면 아무것도 안 쓴다


def test_parse_document_empty_elements_raises_but_keeps_raw(offline, monkeypatch, tmp_path):
    p = _file(tmp_path, "scan.pdf")
    monkeypatch.setattr(f01, "_call_sync", lambda *a, **k: {"elements": [], "usage": {"pages": 3}})
    out = tmp_path / "keep"
    with pytest.raises(ParseError, match="아무 내용도 읽지 못했습니다"):
        f01.parse_document(p, save_raw=out, coordinates=True)
    raw = json.loads((out / "scan.upstage.json").read_text("utf-8"))
    keys = json.loads((out / "scan.keys.json").read_text("utf-8"))
    assert raw["_chuckchuck_meta"] == {"coordinates_requested": True, "source_file": "scan.pdf"}
    assert keys["element_count"] == 0 and keys["coordinates_requested"] is True
    assert not (out / "scan.slidedoc.json").exists()


def test_parse_document_max_slides_cap(offline, monkeypatch, tmp_path):
    p = _file(tmp_path, "long.pdf")
    monkeypatch.setattr(f01, "MAX_SLIDES", 2)
    monkeypatch.setattr(f01, "_call_sync",
                        lambda *a, **k: {"elements": [el("paragraph", "x", page=i) for i in (1, 2, 3)]})
    with pytest.raises(ParseError, match="3장입니다. 현재 2장까지"):
        f01.parse_document(p)
    monkeypatch.setattr(f01, "MAX_SLIDES", 3)
    assert f01.parse_document(p).total_slides == 3


# (2026-09-13 고침 — 예전엔 xfail 이었다)
def test_max_slides_message_does_not_claim_raw_saved_when_it_was_not(offline, monkeypatch, tmp_path):
    p = _file(tmp_path, "long.pdf")
    monkeypatch.setattr(f01, "MAX_SLIDES", 1)
    monkeypatch.setattr(f01, "_call_sync",
                        lambda *a, **k: {"elements": [el("paragraph", "x", page=i) for i in (1, 2)]})
    with pytest.raises(ParseError) as ei:
        f01.parse_document(p, save_raw=False)
    assert "이미 저장됨" not in str(ei.value)


def test_parse_document_save_raw_writes_raw_keys_and_ours(offline, monkeypatch, tmp_path):
    p = _file(tmp_path, "발표 자료(최종).pdf")
    els, ours = ringle_page10()
    monkeypatch.setattr(f01, "_call_sync", lambda *a, **k: {"elements": els, "model": "document-parse"})
    doc = f01.parse_document(p, save_raw=True)                      # True → RAW_DIR
    d = offline / "raw"
    assert sorted(x.name for x in d.iterdir()) == [
        "발표_자료_최종_.keys.json", "발표_자료_최종_.slidedoc.json", "발표_자료_최종_.upstage.json"]
    assert json.loads((d / "발표_자료_최종_.slidedoc.json").read_text("utf-8")) == doc.to_dict()
    keys = json.loads((d / "발표_자료_최종_.keys.json").read_text("utf-8"))
    assert keys["categories"]["paragraph"] > 0 and keys["source_file"] == p.name
    assert doc.slides[0].to_dict() == ours
    f01.parse_document(p, save_raw=str(tmp_path / "other"))        # str → 그 디렉터리
    assert (tmp_path / "other" / "발표_자료_최종_.slidedoc.json").exists()


def test_inventory_raw_elements_counts_keys_and_clips_base64():
    body = {"apiVersion": "1", "model": "m", "elements": [
        {"category": "figure", "content": {"html": "h"}, "coordinates": [{"x": 0, "y": 0}],
         "base64_encoding": "A" * 100, "font_size": 3},
        {"category": "figure", "content": {"text": "t"}}, {"category": "paragraph"}, "junk"]}
    inv = f01.inventory_raw_elements(body, sample_n=2)
    assert inv["element_count"] == 4 and len(inv["sample_elements"]) == 2
    assert list(inv["categories"]) == ["figure", "paragraph"]
    assert list(inv["element_keys"])[:2] == ["category", "content"]
    assert inv["nested_keys"] == {"content": ["html", "text"], "coordinates": ["x", "y"]}
    assert inv["sample_elements"][0]["base64_encoding"] == "A" * 40 + "…(100 chars)"
    assert body["elements"][0]["base64_encoding"] == "A" * 100      # 원본은 안 건드린다
    assert inv["has_coordinates_any"] is True and inv["font_like_keys"] == ["font_size"]
    assert inv["top_level_keys"] == ["apiVersion", "elements", "model"]
    assert f01.inventory_raw_elements({})["has_coordinates_any"] is False
