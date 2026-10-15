"""
한국어 실 시험셋(held-out) — 학습에 절대 넣지 않는 덱들.

  qa_bench 녹음 덱 11개 (etc/labs/qa_bench/corpus — r1 결함 심은 녹음 · r2 깨끗한 녹음, r3 다른 발표는 F-11 이 판정하지 않아 뺌)
  + health_glucose (혈당 발표 녹음 전사)
  + 팀 부스 덱 6개 (main/decks 급속충전·미세플라스틱·배달앱 × 두 버전 — 대본 PDF 를 장별 발화로)

덱마다 SlideDoc → F-06/F-07(Solar, 제품 기본 다수결 3) → ConceptGraph 를 만들어 캐시하고,
녹음마다 Transcript 와 「심은 결함」(truth) 을 같이 둔다. 라벨은 label_set.py 가 붙인다.

산출: DATA/ko_real/<deck>/{slide_doc,graph,concept_doc}.json · DATA/ko_real/recs.json
"""

from __future__ import annotations

import argparse
import glob
import re
import unicodedata
from pathlib import Path

from common import CORPUS, DATA, DECKS, jdump, jload, load_env

OUT = DATA / "ko_real"

CORPUS_DECKS = [
    "audit_bunt", "audit_co2", "audit_kiosk", "heldout_badminton", "heldout_coding", "heldout_subway",
    "heldout2_clinic", "heldout2_dorm", "heldout2_recycle", "rec_laundry", "rec_trail", "health_glucose",
]

#: 부스 덱 — 폴더(NFC) · 덱 키 · 대본 PDF 머리말 · 상황.
BOOTH = {
    "급속충전배터리열화A": ("booth_battery", "A-1"),
    "급속충전배터리열화B": ("booth_battery", "A-2"),
    "미세플라스틱물벼룩번식A": ("booth_plastic", "B-1"),
    "미세플라스틱물벼룩번식B": ("booth_plastic", "B-2"),
    "배달앱별점인플레이션A": ("booth_rating", "C-1"),
    "배달앱별점인플레이션B": ("booth_rating", "C-2"),
}
BOOTH_CTX = {
    "booth_battery": {"situation": "lab_seminar", "audience": "연구실 구성원", "duration_min": 5},
    "booth_plastic": {"situation": "lab_seminar", "audience": "지도교수와 같은 랩 구성원", "duration_min": 5},
    "booth_rating": {"situation": "conference", "audience": "학회 청중", "duration_min": 5},
}

#: 부스 대본 2쪽(「척척발표가 찾아낸 것」)에 적힌 결함 중 F-11 클래스로 옮길 수 있는 것만 — 사람이 읽고 옮겼다.
#: kind: missing(내용 누락) · contradiction(숫자 불일치). keys 는 그 개념을 가려낼 자료 낱말.
BOOTH_TRUTH = {
    "A-1": [
        {"slide": 2, "kind": "missing", "keys": ["온도", "45", "25", "항온조"], "note": "온도 2수준을 말하지 않음"},
        {"slide": 3, "kind": "contradiction", "keys": ["64", "용량유지율", "45"], "speech": "60% 정도", "note": "64% → 60% 정도"},
        {"slide": 4, "kind": "missing", "keys": ["4개", "셀", "표준편차", "3.2"], "note": "표본(군당 4셀) 한계를 건너뜀"},
    ],
    "A-2": [
        {"slide": 3, "kind": "contradiction", "keys": ["93", "0.5C"], "speech": "90% 정도", "note": "93% → 90% 정도"},
        {"slide": 4, "kind": "missing", "keys": ["한계", "4셀", "방전심도", "원인"], "note": "한계를 한 문장으로 지나감"},
    ],
    "B-1": [
        {"slide": 2, "kind": "missing", "keys": ["수온", "광주기", "Chlorella", "배지", "고정"], "note": "통제 조건을 말하지 않음"},
        {"slide": 3, "kind": "contradiction", "keys": ["NOEC"], "speech": "0.1 밀리그램", "note": "NOEC 1 → 0.1"},
        {"slide": 4, "kind": "missing", "keys": ["기아", "섭식", "소화관", "먹이 섭취"], "note": "기아 효과 한계를 건너뜀"},
    ],
    "B-2": [
        {"slide": 3, "kind": "missing", "keys": ["생존율", "90%"], "note": "생존율 90% 이상을 말하지 않음"},
    ],
    "C-1": [
        {"slide": 2, "kind": "contradiction", "keys": ["0.34", "이벤트"], "speech": "0.5점", "note": "+0.34 → 0.5점"},
        {"slide": 2, "kind": "missing", "keys": ["재주문율", "0.6"], "note": "가설 기각 근거를 말하지 않음"},
        {"slide": 3, "kind": "missing", "keys": ["한 플랫폼", "91%", "정확도", "인과", "연관"], "note": "한계를 통째로 뺌"},
    ],
    "C-2": [],
}


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def deck_dir(name: str) -> Path:
    for p in DECKS.iterdir():
        if nfc(p.name) == name:
            return p
    raise FileNotFoundError(name)


def _unwrap(text: str) -> str:
    """PDF 는 한글을 글자 단위로 줄바꿈한다 — 「대조\\n군입니다」「꺾\\n이고」「않습니\\n다.」 는 붙이고 「크기도\\n형상도」 는 띄운다."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    out = ""
    for ln in lines:
        if not out:
            out = ln
            continue
        tail = out.split(" ")[-1]
        glue = (re.match(r"[다요까][.,!?\s]|[다요까]$", ln) is not None
                or (len(tail) <= 2 and re.match(r"[가-힣]", ln) and re.search(r"[가-힣]$", out)))
        out += ("" if glue else " ") + ln
    return " ".join(out.split())


def script_transcript(pdf: Path) -> dict:
    """부스 대본 PDF 1쪽 → 장별 발화 Transcript (어절 길이로 시간을 나눈다 — 받아쓰기 오류 없는 낭독본)."""
    from pypdf import PdfReader

    text = "\n".join(p.extract_text() for p in PdfReader(str(pdf)).pages)
    text = text.split("이 대본에는 일부러")[0]
    parts = re.split(r"\n\s*슬라이드\s*(\d+)\s*\n", "\n" + text)
    segs, words, t = [], [], 0.0
    for i in range(1, len(parts) - 1, 2):
        no = int(parts[i])
        body = _unwrap(parts[i + 1])
        ws = body.split()
        start = t
        seg_words = []
        for w in ws:
            seg_words.append({"text": w, "start_sec": round(t, 2), "end_sec": round(t + 0.38, 2)})
            t += 0.4
        segs.append({"slide_no": no, "visit": 1, "start_sec": round(start, 2), "end_sec": round(t, 2),
                     "text": body, "words": seg_words})
        words += seg_words
    return {"full_text": " ".join(s["text"] for s in segs), "words": words, "by_slide": segs,
            "provider": "script", "duration_sec": round(t, 2)}


def graph_for(deck: str, slide_doc: dict, ctx: dict) -> dict:
    d = OUT / deck
    g = jload(d / "graph.json")
    if g:
        return g
    from pipeline.contracts import Context, SlideDoc
    from pipeline.f06_concepts import extract_concepts
    from pipeline.f07_graph import build_graph

    doc = SlideDoc.from_dict(slide_doc)
    c = Context.from_dict(ctx)
    concepts = extract_concepts(doc, c, llm="solar")
    graph = build_graph(concepts, c, slide_doc=doc, llm="solar")
    jdump(d / "concept_doc.json", concepts.to_dict())
    jdump(d / "graph.json", graph.to_dict())
    print(f"[ko_real] {deck} nodes={len(graph.nodes)}", flush=True)
    return graph.to_dict()


def corpus_recs(deck: str) -> list[dict]:
    t = jload(CORPUS / deck / "truth.json")
    recs = []
    ctx = t.get("context") or {"situation": "school_project", "duration_min": 10}
    if t.get("recordings"):
        for rid, r in t["recordings"].items():
            if r.get("kind") == "unrelated":
                continue
            recs.append({"rec_id": f"{deck}_{rid}", "deck": deck, "kind": r.get("kind"), "ctx": ctx,
                         "transcript": str(CORPUS / deck / r["transcript_file"]), "planted": r.get("planted", [])})
    elif (CORPUS / deck / "transcript.json").exists():
        recs.append({"rec_id": f"{deck}_r1", "deck": deck, "kind": "recorded", "ctx": ctx,
                     "transcript": str(CORPUS / deck / "transcript.json"), "planted": []})
    return recs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    load_env()
    recs = []
    for deck in CORPUS_DECKS:
        if args.only and args.only != deck:
            continue
        sd = jload(CORPUS / deck / "slidedoc.json")
        rs = corpus_recs(deck)
        jdump(OUT / deck / "slide_doc.json", sd)
        graph_for(deck, sd, rs[0]["ctx"] if rs else {})
        recs += rs
    for folder, (deck, ver) in BOOTH.items():
        if args.only and args.only != deck:
            continue
        d = deck_dir(folder)
        sd = jload(OUT / deck / "slide_doc.json")
        if not sd:
            from pipeline.f01_parse import parse_document
            pptx = next(p for p in d.iterdir() if p.suffix == ".pptx")
            sd = parse_document(pptx).to_dict()
            jdump(OUT / deck / "slide_doc.json", sd)
        graph_for(deck, sd, BOOTH_CTX[deck])
        pdf = Path(glob.glob(str(d / "*" / "*.pdf"))[0])
        tr = script_transcript(pdf)
        tpath = OUT / deck / f"transcript_{ver}.json"
        jdump(tpath, tr)
        recs.append({"rec_id": f"{deck}_{ver}", "deck": deck, "kind": "booth", "ctx": BOOTH_CTX[deck],
                     "transcript": str(tpath), "planted": BOOTH_TRUTH[ver]})
    if not args.only:
        jdump(OUT / "recs.json", recs)
    print(f"[ko_real] recordings={len(recs)}")


if __name__ == "__main__":
    main()
