"""
투어 녹화본 → data/tour 변환(etc/labs/tour_capture/build.py) 의 순수 함수와 실제 투어 파일 (2026-10-11, lab/tour-fixtures).

- 변환 규칙: 줄이기(clip) · 거르기(scrub) · 3단계 말 · 장 넘김을 문장 끝으로 · 코칭 칩 · 판정기 알려진 오류 지우기 · 비교가 안 되는 질문 빼기.
- 합성 녹화본 하나를 통째로 옮겨 계약 검사기(test_booth_mobile_contract)를 통과하는지.
- 커밋된 투어 파일: 녹화 투어마다 질문 1개 이상 · 근거 장 번호가 덱 안 · 공개 파일에 내부 글이 없음 · (녹화본이 있으면) 다시 만들면 같은 파일.
브리지 · API 를 부르지 않는다.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path

import pytest

from tests.test_booth_mobile_contract import TOUR_FILES, TOUR_SCHEMA, check, tour_semantics

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("tour_capture_build", ROOT / "etc" / "labs" / "tour_capture" / "build.py")
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


def test_답이_말한_숫자로_칭찬하면_그대로_싣고_다음_문장의_고칠_점까지_싣는다():
    """10-12 2차 r2-3 — 한 문장만 실어서 칭찬만 남고 빠진 것이 안 보였다. 두 문장까지, 이음말은 다듬는다."""
    judge = {"verdict": "partial", "react": "방전 1C 고정은 정확해요. 그런데 나머지가 빠졌어요. 셋째 문장이에요.", "followup": "x"}
    assert B.feedback_text(judge, "방전은 1C로 고정했어요") == "방전 1C 고정은 정확해요. 나머지가 빠졌어요."


def test_피드백은_되묻는_문장을_빼고_자르지_않는다():
    long = "검정 결과를 " + "아주 " * 40 + "정확히 말했어요."
    judge = {"verdict": "good", "react": f"{long} 다른 근거도 말해 줄래요?"}
    assert B.feedback_text(judge, "답") == long


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


def test_그래프_요약_숫자는_보여_준_노드와_같다():
    """perf-security-copy-r1-3 — 요약은 원본 그래프 전체(22개 중 14개)로, 범례는 자른 12개(잘 설명함 8 · 아직 4)로 세서 한 카드 안 숫자가 달랐다."""
    rec = _recording()
    rec["graph"]["nodes"] += [{"id": f"n{i}", "label": f"개념 {i}", "kind": "concept", "slide_nos": [1], "weight": i / 100} for i in range(20)]
    rec["alignment"]["items"] += [{"node_id": f"n{i}", "verdict": "aligned" if i % 2 else "missing"} for i in range(20)]
    rec["alignment"]["summary"]["verdict_counts"] = {"aligned": 11, "missing": 11}
    g = B.claim_graph(rec["graph"], rec["alignment"])
    shown, said = graph_summary_numbers(g["summary"])
    assert shown == len(g["nodes"]) == B.NODE_MAX
    assert said == sum(n["status"] in ("aligned", "justified_skip") for n in g["nodes"])


def graph_summary_numbers(summary: str) -> tuple[int, int]:
    m = re.search(r"(\d+)개 가운데 (\d+)개", summary)
    assert m, summary
    return int(m.group(1)), int(m.group(2))


@pytest.mark.parametrize("path", RECORDED, ids=lambda p: p.name)
def test_녹화_투어의_그래프_요약_숫자는_범례와_같다(path):
    g = json.loads(path.read_text(encoding="utf-8"))["analysis"]["claim_graph"]
    shown, said = graph_summary_numbers(g["summary"])
    assert shown == len(g["nodes"]), g["summary"]
    assert said == sum(n["status"] in ("aligned", "justified_skip") for n in g["nodes"]), g["summary"]
    bad = sum(n["status"] == "contradiction" for n in g["nodes"])
    assert (f"어긋나게 말한 곳이 {bad}곳" in g["summary"]) == bool(bad), g["summary"]


#: 해요체 한 문장 — 「…요」 로 끝나고 뒤에 마침표 · 괄호 보충만 온다 (한다체 「…다.」 · 합쇼체 「…습니다.」 · 음슴체 「…함」 이 아니다)
HAEYO = re.compile(r"요[.!]?(\s*\([^()]*\))?$")
JARGON_LABELS = {"목적·청중 적합성", "언어적 명료성", "음성적 전달", "시각자료 활용", "내용 충실도", "논리 구조", "시간 관리"}


def report_voice_problems(t: dict) -> list[str]:
    errs = []
    r = t["report"]
    lines = [("headline", r["headline"])] + [(f"item:{i['id']}", i["note"]) for i in r["items"] if i["note"]] + \
            [(f"step:{k}", s["text"]) for k, s in enumerate(r["next_steps"])] + [("analysis.summary", t["analysis"]["summary"])]
    for where, text in lines:
        if "…" in text:
            errs.append(f"{where}: 「…」 로 잘렸다 — {text}")
        if not HAEYO.search(text):
            errs.append(f"{where}: 해요체가 아니다 — {text}")
        if "간투어" in text or "슬라이드" in text:
            errs.append(f"{where}: 용어(군더더기 말 · 장)가 다르다 — {text}")
    errs += [f"label: 명사+명사 한자어 {i['label']}" for i in r["items"] if i["label"] in JARGON_LABELS]
    g = t["analysis"]["claim_graph"]
    root = next((n for n in g["nodes"] if n["id"] == g["root"]), None)
    if root and root["status"] == "missing":
        errs += [f"item:{i['id']}: 분석은 핵심 주장을 안 말했다는데 리포트는 제시했다고 한다 — {i['note']}"
                 for i in r["items"] if "핵심 주장" in i["note"]]
    return errs


@pytest.mark.parametrize("path", RECORDED, ids=lambda p: p.name)
def test_녹화_투어_리포트는_해요체_한_문장이고_분석과_어긋나지_않는다(path):
    """perf-security-copy-r1-4 · layout-touch-a11y-r1-4 — 해요체 · 한다체 · 합쇼체 · 음슴체가 섞이고 「…」 로 잘렸다."""
    assert report_voice_problems(json.loads(path.read_text(encoding="utf-8"))) == []


def test_다듬은_문구는_원문_앞부분이_같을_때만_쓴다():
    deck, slot = "delivery-rating", "item:logic"
    prefix, fixed = B.CURATED[(deck, slot)]
    assert B.curated(deck, slot, prefix + " 뒤는 무엇이든") == fixed
    assert B.curated(deck, slot, "다시 녹화해서 바뀐 원문") == "다시 녹화해서 바뀐 원문"


def test_정해진_모양_문구는_숫자를_그대로_두고_용어만_바꾼다():
    assert B.plain_terms("핵심 슬라이드 3장이 권장 시간과 평균 67% 어긋나요 (2번이 +47초)") == \
        "핵심 장 3개가 권장 시간과 평균 67% 어긋나요 (2장은 47초 더 썼어요)"
    assert B.plain_terms("근거 자료 4장 중 4장에 출처가 없어요 (1, 2, 3, 4번)") == "모든 장(1~4장)에 출처가 없어요"
    assert B.plain_terms("근거 자료 4장 중 3장에 출처가 없어요 (1, 2, 4번)") == "근거 자료 4개 장 중 3개 장에 출처가 없어요 (1, 2, 4장)"
    assert B.plain_terms("분당 간투어 0.4번") == "분당 군더더기 말 0.4번"
    assert B.report_note("x", "content", "자료에 없는 이야기를 18개 덧붙였어요 (급속 충전이 배터리 수명을 얼마나 깎는지, 중간 결과, 상용 셀을 직접 500 사이클 돌려받습니다)") == \
        "자료에 없는 이야기를 18개 덧붙였어요"


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
        pytest.skip("녹화본(etc/labs/tour_capture/out/recordings) 이 이 머신에 없다 — capture.py 를 돌린 머신에서만 본다")
    assert B.main(["--check"]) == 0


# ─── 10-12 2차 점검 — 잘림 · 판정 피드백 · 리포트 모순 · 공개 메모 ─────────────

def _strings(value, path="$"):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _strings(v, f"{path}[{i}]")
    elif isinstance(value, str):
        yield path, value


ANSWER_TEXT = re.compile(r"\.answers\.(good|rough)\.text$")


@pytest.mark.parametrize("path", RECORDED, ids=lambda p: p.name)
def test_녹화_투어_글은_사람_답_말고는_잘리지_않는다(path):
    """layout-touch-a11y-r2-4 · perf-security-copy-r2-7 — 핵심 주장 이름 · 판정 문장 · 근거 인용이 「…」 로 잘린 채 실렸다.
    줄이는 건 화면(CSS 줄 수 제한 · 펼치기)이 한다. 사람 답의 「…」 는 머뭇거림이라 뺀다."""
    t = json.loads(path.read_text(encoding="utf-8"))
    cut = [f"{p}: {v[-40:]}" for p, v in _strings(t) if v.rstrip().endswith(("…", "...")) and not ANSWER_TEXT.search(p)]
    assert cut == []


@pytest.mark.parametrize("path", RECORDED, ids=lambda p: p.name)
def test_녹화_투어_판정_피드백은_답을_되풀이하지_않고_되묻지_않는다(path):
    """perf-security-copy-r2-3 — 피드백이 답 첫 줄을 옮기다 잘리거나, 되묻는 질문이 피드백 자리에 들어갔다."""
    t = json.loads(path.read_text(encoding="utf-8"))
    errs = []
    for q in t["qa"]["questions"]:
        for kind, a in q["answers"].items():
            fb = a["feedback"].strip()
            if fb.endswith(("?", "…")):
                errs.append(f"{q['id']}:{kind}: {fb}")
            if fb[:30] and fb[:30] in a["text"]:
                errs.append(f"{q['id']}:{kind}: 답을 되풀이 — {fb}")
            if a["verdict"] != "good" and not re.search(r"빠|말해|말하지|다시|아쉬|확인|견줘|못|않", fb):
                errs.append(f"{q['id']}:{kind}: 좋지 않은 답인데 빠진 것 · 고칠 점이 없다 — {fb}")
    assert errs == []


#: 리포트 제목 · 연습 문장이 항목 판정과 부딪히는 말 — {말: 그 말이 참이려면 「좋아요」 여야 할 항목}
CLAIMS = {"자료와 잘 맞": "content", "잘 맞았": "content", "빠르기가 좋": "delivery"}


@pytest.mark.parametrize("path", RECORDED, ids=lambda p: p.name)
def test_녹화_투어_리포트는_한_화면_안에서_부딪히지_않는다(path):
    """perf-security-copy-r2-2 — 제목 「자료와 잘 맞았어요」 아래 「자료에 없는 이야기 18개 · 보통」, 「목소리와 빠르기 · 좋아요」 인데 분석은
    말 속도 「느려요 · 더 연습」, 연습 3 은 「권장보다 빠르게」."""
    t = json.loads(path.read_text(encoding="utf-8"))
    r, a = t["report"], t["analysis"]
    level = {i["id"]: i["level"] for i in r["items"]}
    rank = {"good": 0, "fair": 1, "practice": 2}
    texts = [r["headline"]] + [s["text"] for s in r["next_steps"]] + [a["summary"]]
    errs = [f"{phrase} ↔ {item}={level.get(item)} : {txt}" for txt in texts for phrase, item in CLAIMS.items()
            if phrase in txt and level.get(item, "good") != "good"]
    if "delivery" in level:
        if rank[level["delivery"]] < rank[a["pace"]["level"]]:
            errs.append(f"목소리와 빠르기 {level['delivery']} 가 분석 말 속도 {a['pace']['level']} 보다 좋다")
    errs += [f"권장을 넘으라는 말: {s}" for s in texts if "권장보다 빠르게" in s or "권장보다 느리게" in s]
    errs += [f"번역투: {i['note']}" for i in r["items"] if re.search(r"(\d+)개 장 중 \1개 장", i["note"])]
    assert errs == []


@pytest.mark.parametrize("path", RECORDED, ids=lambda p: p.name)
def test_공개_투어_메모에는_검수_내용이_없다(path):
    """perf-security-copy-r2-9 — source.note 에 「뺀 질문 · 판정 모델이 틀린 이유 · 모델 이름」 이 공개 주소로 나갔다."""
    note = json.loads(path.read_text(encoding="utf-8"))["source"]["note"]
    assert not re.search(r"뺀 질문|오답|solar|skt|판정 |받아쓰기 |etc/labs/", note), note
