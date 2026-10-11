"""
투어 녹화본 → data/tour 변환(labs/tour_capture/build.py) 의 순수 함수와 실제 투어 파일 (2026-10-11, lab/tour-fixtures).

- 변환 규칙: 줄이기(clip) · 거르기(scrub) · 3단계 말 · 장 넘김을 문장 끝으로 · 코칭 칩 · 판정기 알려진 오류 지우기 · 비교가 안 되는 질문 빼기.
- 합성 녹화본 하나를 통째로 옮겨 계약 검사기(test_booth_mobile_contract)를 통과하는지.
- 커밋된 투어 파일: 녹화 투어마다 질문 1개 이상 · 근거 장 번호가 덱 안 · 공개 파일에 내부 글이 없음 · (녹화본이 있으면) 다시 만들면 같은 파일.
브리지 · API 를 부르지 않는다.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from tests.test_booth_mobile_contract import TOUR_FILES, TOUR_SCHEMA, check, tour_semantics

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("tour_capture_build", ROOT / "labs" / "tour_capture" / "build.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

RECORDED = [p for p in TOUR_FILES if not p.stem.startswith("_")]


# ─── 글 다루기 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,limit", [
    ("짧은 글이에요.", 40),
    ("첫 문장이에요. 둘째 문장은 아주 길어서 한 줄에 다 안 들어가요 그래서 잘라야 해요.", 30),
    ("쉼표가 있는 긴 문장, 그 뒤로 이어지는 이야기가 아주 길게 붙어 있어요", 25),
    ("띄어쓰기없는아주긴글자덩어리가계속이어져서경계가하나도없어요정말로", 20),
])
def test_clip_은_상한_안에서_경계로_자른다(text, limit):
    out = B.clip(text, limit)
    assert len(out) <= limit
    assert text.startswith(out.rstrip("…")) or out == text


def test_clip_은_짧은_글을_그대로_둔다():
    assert B.clip("그대로예요", 10) == "그대로예요"


@pytest.mark.parametrize("raw,gone", [
    ("문의 team@example.com 으로", "@"),
    ("파일 /home/yehschuck/project/x.pptx 를", "/home/"),
    ("키 " + "sk" + "-" + "x" * 24 + " 노출", "sk" + "-xxxx"),   # 키 모양은 실행 때 이어 붙인다 — 저장소 키 검사(chk gate)에 걸리지 않게
    ("주소 https://chuckchuck-present.com/x 에서", "https://"),
    ("해시 0123456789abcdef0123456789abcdef 값", "0123456789abcdef0123"),
])
def test_scrub_은_메일_경로_키_링크를_지운다(raw, gone):
    assert gone not in B.scrub(raw)


def test_forbidden_hits_는_남은_내부_글을_찾는다():
    assert B.forbidden_hits({"a": ["괜찮아요", {"b": "session_id=abc"}]}) == ["$.a[1].b: session_id=abc"]
    assert B.forbidden_hits({"a": "평범한 글이에요 3,200곳"}) == []


def test_numbers_는_쉼표를_무시한다():
    assert B.numbers("매장 3,200곳 · 리뷰 124380건 · 0.34점") == {"3200", "124380", "0.34"}


@pytest.mark.parametrize("score,level", [(92, "good"), (85, "good"), (84.9, "fair"), (70, "fair"), (69, "practice")])
def test_three_level(score, level):
    assert B.three_level(score) == level


@pytest.mark.parametrize("cpm,level", [(320, "good"), (300, "good"), (280, "fair"), (390, "fair"), (240, "practice"), (420, "practice")])
def test_pace_level_은_vision_cue_문턱을_쓴다(cpm, level):
    assert B.pace_level(cpm) == level


# ─── 발표 재생 ──────────────────────────────────────────────────────────────

def _w(text, s, e):
    return {"text": text, "start_sec": s, "end_sec": e}


WORDS = [_w("안녕하세요.", 0.5, 1.5), _w("첫", 2.0, 2.3), _w("장이에요.", 2.3, 3.0), _w("둘째", 9.0, 9.4), _w("장은", 9.4, 9.9),
         _w("문장이", 10.1, 10.5), _w("넘어가요.", 10.6, 11.4), _w("마무리예요.", 15.0, 16.0)]


def test_장_넘김이_문장_가운데면_문장_끝으로_옮긴다():
    spans = [{"slide_no": 1, "start_sec": 0.0, "end_sec": 10.0}, {"slide_no": 2, "start_sec": 10.0, "end_sec": 16.0}]
    out = B.snap_spans(spans, WORDS)
    assert out[0]["end_sec"] == out[1]["start_sec"] == 11.4
    assert spans[0]["end_sec"] == 10.0   # 원본은 그대로 (새 목록을 돌려준다)


def test_장_넘김이_이미_문장_끝이면_그대로다():
    spans = [{"slide_no": 1, "start_sec": 0.0, "end_sec": 3.0}, {"slide_no": 2, "start_sec": 3.0, "end_sec": 16.0}]
    assert B.snap_spans(spans, WORDS) == spans


def test_자막_조각은_문장_끝과_장에서_끊기고_상한을_지킨다():
    spans = [{"slide_no": 1, "start_sec": 0.0, "end_sec": 8.0}, {"slide_no": 2, "start_sec": 8.0, "end_sec": 16.0}]
    chunks = B.transcript_chunks(WORDS, spans)
    assert [c["text"] for c in chunks] == ["안녕하세요.", "첫 장이에요.", "둘째 장은 문장이 넘어가요.", "마무리예요."]
    assert [c["slide_no"] for c in chunks] == [1, 1, 2, 2]
    assert all(len(c["text"]) <= 80 and c["start_sec"] <= c["end_sec"] for c in chunks)


def test_코칭_칩은_잰_신호에서만_나오고_뜸하다():
    words = [_w(f"가나다라마바{i}.", i * 0.5, i * 0.5 + 0.45) for i in range(200)]   # 아주 빠른 말
    spans = [{"slide_no": 1, "start_sec": 0.0, "end_sec": 100.0}]
    habits = {"spans": [{"kind": "FIL", "text": "음,", "start_sec": 35.0, "end_sec": 35.4}]}
    pace = {"slides": [{"slide_no": 1, "status": "long", "recommended_sec": 60.0}]}
    chips = B.coaching_chips(words, spans, habits, pace, 100.0)
    kinds = [c["kind"] for c in chips]
    assert kinds[0] == "listen" and "fast" in kinds and "filler" in kinds and "time" in kinds
    assert "slow" not in kinds and "quiet" not in kinds and "loud" not in kinds   # 재지 않은 신호는 만들지 않는다
    assert all(len(c["text"]) <= 16 for c in chips)
    ats = [c["at_sec"] for c in chips]
    assert ats == sorted(ats) and all(b - a >= B.CHIP_GAP_SEC for a, b in zip(ats, ats[1:]))
    assert any(c["text"] == "「음」가 들렸어요" for c in chips)   # 문장부호를 뗀 말버릇


# ─── 판정 ───────────────────────────────────────────────────────────────────

def test_엉성한_답의_근거없는_칭찬은_건너뛰고_되묻기로_갈음한다():
    judge = {"verdict": "partial", "react": "리뷰 124,380건을 사용했다는 점은 정확히 말했어요.",
             "followup": "총 건수를 다시 말해 줄래요?"}
    assert B.feedback_text(judge, "음… 어느 정도의 리뷰를 썼어요") == "총 건수를 다시 말해 줄래요?"


def test_답이_말한_숫자로_칭찬하면_그대로_싣는다():
    judge = {"verdict": "partial", "react": "방전 1C 고정은 정확해요. 그런데 나머지가 빠졌어요.", "followup": "x"}
    assert B.feedback_text(judge, "방전은 1C로 고정했어요") == "방전 1C 고정은 정확해요."


def test_반응의_이음말과_겹친_자료를_다듬는다():
    judge = {"verdict": "wrong", "react": "그런데 자료 자료 3장의 수치를 빠뜨렸어요."}
    assert B.feedback_text(judge, "모르겠어요") == "자료 3장의 수치를 빠뜨렸어요."


def _ground(role, quote, ref="S2-3", slide_no=2):
    return {"slide_no": slide_no, "ref": ref, "quote": quote, "role": role, "note": "이 줄은 근거가 돼요."}


def test_엉성한_답에서_말하지_않은_숫자_줄을_짚은_것으로_보이지_않는다():
    judge = {"verdict": "partial", "grounds": [_ground("covered", "리뷰 124,380건"), _ground("missing", "재주문율 +0.6%p", "S2-4"),
                                               _ground("missing", "방전 1C", "S2-5")]}
    out = B.grounds_view(judge, "음… 방전은 1C 였어요")
    assert [g["ref"] for g in out] == ["S2-4"]   # covered(말 안 한 숫자) · missing(이미 말한 숫자) 를 뺀다
    assert out[0]["note"] == "근거가 돼요."


def test_좋은_답의_근거는_그대로_싣는다():
    judge = {"verdict": "good", "grounds": [_ground("covered", "리뷰 124,380건")]}
    assert len(B.grounds_view(judge, "리뷰를 썼어요")) == 1


def test_근거는_세_줄까지이고_모양이_틀린_번호는_버린다():
    judge = {"verdict": "good", "grounds": [_ground("covered", f"줄 {i}", f"S2-{i}") for i in range(1, 6)] + [_ground("covered", "x", "S2")]}
    out = B.grounds_view(judge, "")
    assert len(out) == 3 and all(g["ref"].startswith("S2-") for g in out)


def _row(qid, good_v, rough_v):
    q = {"id": qid, "question": "근거는 무엇인가요?", "slide_nos": [2], "evidence_slide_no": 2}
    j = lambda v: {"verdict": v, "react": "판정했어요.", "grounds": []}   # noqa: E731
    return {"question": q, "good_text": "좋은 답이에요", "rough_text": "음… 잘 모르겠어요", "good": j(good_v), "rough": j(rough_v)}


def test_비교가_안_되는_질문과_사람이_뺀_질문은_싣지_않는다(monkeypatch):
    monkeypatch.setitem(B.EXCLUDE, "t-deck", {"q09": "골자 오답"})
    rec = {"tour_deck_id": "t-deck", "situation": "업무 보고 (상사 대상)",
           "judged": [_row("q01-a", "good", "partial"), _row("q02-b", "good", "good"), _row("q03-c", "partial", "wrong"),
                      _row("q09-x", "good", "wrong")]}
    qa, dropped = B.qa_section(rec, {1, 2, 3})
    assert [q["id"] for q in qa["questions"]] == ["q01-a"]
    assert qa["asker"] == "상사"
    assert len(dropped) == 3 and any("골자 오답" in d for d in dropped)
    assert qa["questions"][0]["answers"]["rough"]["level"] == "fair"


# ─── 통째로 옮기기 (합성 녹화본) ─────────────────────────────────────────────

def _recording() -> dict:
    blocks = lambda *t: [{"category": "paragraph", "text": x} for x in t]   # noqa: E731
    slides = [
        {"slide_no": 1, "title": "홍길동", "blocks": blocks("가 설 과 검 증", "별점은 왜 4.7에 몰리는가", "배달앱 리뷰 12만 건으로 본 원인")},
        {"slide_no": 2, "title": "", "blocks": blocks("세 가설 가운데 하나만 지지됐다")},
        {"slide_no": 3, "title": "4.7은 수집 방식의 결과다", "blocks": []},
    ]
    words = [_w(f"말{i}이에요{'.' if i % 4 == 3 else ''}", i * 1.0, i * 1.0 + 0.8) for i in range(30)]
    graph = {"thesis": "root", "nodes": [{"id": "root", "label": "4.7은 수집 방식의 결과다", "kind": "thesis", "slide_nos": [3], "weight": 1},
                                         {"id": "c1", "label": "리뷰 이벤트", "kind": "concept", "slide_nos": [2], "weight": 0.5}],
             "edges": [{"from": "root", "to": "c1", "kind": "parent"}]}
    judged = [{"question": {"id": "q01-x", "question": "근거는요?", "slide_nos": [2], "evidence_slide_no": 2},
               "good_text": "재주문율이 0.6%p 였어요", "rough_text": "음… 잘 기억이 안 나요",
               "good": {"verdict": "good", "react": "근거를 정확히 말했어요.", "grounds": [_ground("covered", "재주문율 +0.6%p")]},
               "rough": {"verdict": "unknown", "react": "근거가 빠졌어요.", "grounds": [_ground("missing", "재주문율 +0.6%p")]}}]
    return {
        "tour_deck_id": "delivery-rating", "situation": "학교 프로젝트 (교수 대상)", "recorded_at": "2026-10-11",
        "slide_doc": {"slides": slides},
        "transcript": {"duration_sec": 29.9, "provider": "skt-ax", "words": words,
                       "by_slide": [{"slide_no": 1, "start_sec": 0, "end_sec": 9.5}, {"slide_no": 2, "start_sec": 9.5, "end_sec": 20},
                                    {"slide_no": 3, "start_sec": 20, "end_sec": 29.9}]},
        "habits": {"spans": [], "filler_cnt": 0}, "graph": graph,
        "alignment": {"items": [{"node_id": "root", "verdict": "aligned"}, {"node_id": "c1", "verdict": "missing"}],
                      "summary": {"verdict_counts": {"aligned": 1, "missing": 1}}},
        "pace": {"avg_chars_per_min": 320, "slides": [{"slide_no": n, "actual_sec": 10, "status": "ok"} for n in (1, 2, 3)]},
        "rubric": {"score": 81, "clusters": [{"key": "logic", "name": "논리 구조", "average": 90, "status": "scored", "item_nos": [7]},
                                             {"key": "x", "name": "안 잰 것", "average": 0, "status": "unmeasured", "item_nos": []}],
                   "items": [{"no": 7, "status": "scored", "score": 90, "source": "det", "evidence": "주장이 먼저 나왔어요"}]},
        "report": {"one_liner": "주장이 또렷해요.", "actions": ["핵심 슬라이드 2번에 예시를 더해 보세요.", "9번 장을 줄여요"]},
        "questions_doc": {"model": "solar"}, "judged": judged,
    }


def test_합성_녹화본은_계약을_지키는_투어가_된다():
    tour = B.build_tour(_recording())
    assert check(tour, TOUR_SCHEMA, TOUR_SCHEMA) == []
    assert tour_semantics(tour, "delivery-rating") == []
    assert tour["deck"]["title"] == "별점은 왜 4.7에 몰리는가"           # 파서 제목(이름)이 짧으면 본문 첫 문단
    assert tour["deck"]["slides"][1]["title"] == "세 가설 가운데 하나만 지지됐다"
    assert tour["deck"]["subtitle"] == "배달앱 리뷰 12만 건으로 본 원인"
    assert tour["analysis"]["level"] == "fair" and tour["analysis"]["pace"]["level"] == "good"
    assert [i["id"] for i in tour["report"]["items"]] == ["logic"]   # 안 잰 묶음은 싣지 않는다
    assert [s["slide_no"] for s in tour["report"]["next_steps"]] == [2, None]   # 덱에 없는 9번은 장 번호를 달지 않는다
    assert tour["analysis"]["claim_graph"]["root"] == "root"
    assert tour["source"]["kind"] == "recorded"


def test_내부_글이_남으면_만들지_않는다():
    rec = _recording()
    rec["judged"][0]["good"]["react"] = "session_id 를 봤어요."
    with pytest.raises(ValueError, match="내보내면 안 되는"):
        B.build_tour(rec)


def test_그래프_노드는_12개까지_루트를_먼저_남긴다():
    rec = _recording()
    rec["graph"]["nodes"] += [{"id": f"n{i}", "label": f"개념 {i}", "kind": "concept", "slide_nos": [1], "weight": i / 100} for i in range(20)]
    g = B.claim_graph(rec["graph"], rec["alignment"])
    assert len(g["nodes"]) == B.NODE_MAX and g["nodes"][0]["id"] == "root"
    assert all(e["from"] in {n["id"] for n in g["nodes"]} and e["to"] in {n["id"] for n in g["nodes"]} for e in g["edges"])


def test_목록은_정한_차례와_기본_덱을_쓴다():
    a = B.build_tour(_recording())
    b = copy.deepcopy(a)
    b["id"] = b["deck"]["id"] = "battery-fastcharge"
    idx = B.build_index([b, a])
    assert [t["id"] for t in idx["tours"]] == ["delivery-rating", "battery-fastcharge"]
    assert idx["default"] == "delivery-rating" and idx["tours"][0]["label"] == "C-1"


# ─── 커밋된 투어 파일 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("path", RECORDED, ids=lambda p: p.name)
def test_녹화_투어는_질문이_있고_근거_장이_덱_안이다(path):
    t = json.loads(path.read_text(encoding="utf-8"))
    nos = {s["no"] for s in t["deck"]["slides"]}
    assert t["source"]["kind"] == "recorded" and t["source"]["recorded_at"]
    assert t["qa"]["questions"]
    for q in t["qa"]["questions"]:
        for ans in q["answers"].values():
            for g in ans["grounds"]:
                assert g["slide_no"] in nos and g["ref"].startswith(f"S{g['slide_no']}-")
    assert B.forbidden_hits(t) == []


def test_녹화본이_있으면_다시_만들어도_같은_파일이다():
    if not any(B.REC_DIR.glob("*.json")):
        pytest.skip("녹화본(labs/tour_capture/out/recordings) 이 이 머신에 없다 — capture.py 를 돌린 머신에서만 본다")
    assert B.main(["--check"]) == 0
