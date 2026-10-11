"""
녹화본 → 투어 파일 — labs/tour_capture/out/recordings/<덱>.json 을 docs/booth-mobile/tour.schema.json 모양으로 옮긴다 (과금 · 브리지 없음).

    /home/yehschuck/project/chuckchuck/.venv/bin/python labs/tour_capture/build.py            # 녹화본 전부 → data/tour/<덱>.json + index.json
    /home/yehschuck/project/chuckchuck/.venv/bin/python labs/tour_capture/build.py --check    # 쓰지 않고 지금 파일과 같은지만 (다시 만들 수 있는가)

옮기는 규칙 (전부 이 파일의 순수 함수 — tests/test_tour_capture.py 가 본다)
- **값은 녹화 응답에서만 온다.** 글을 새로 짓지 않는다. 화면 한 줄 상한에 맞춰 줄일 때는 문장 · 절 경계에서 자르고(뜻은 그대로) 「…」 를 붙인다.
  예외 하나 — 리포트 · 분석 요약 문구는 용어를 맞추고(장 번호 「N장」 · 「군더더기 말」), LLM 문장은 사람이 녹화본을 읽고 해요체 한 문장으로
  다듬은 CURATED 만 쓴다(원문 앞부분이 같을 때만). 숫자 · 판정 단계는 바꾸지 않는다 (10-12 점검).
- 숫자는 3단계 말로: 채점 평균 85 이상 good · 70 이상 fair · 그 아래 practice. 말 속도 300~350자/분 good. 군더더기 분당 2번 이하 good.
- 판정 비교가 성립하는 질문만 싣는다: 「잘 답한 답」 이 good, 「엉성한 답」 이 good 이 아닌 것. 빠진 질문은 source.note 에 적는다.
- 판정기의 알려진 오류를 화면에 옮기지 않는다(지우기만 한다, 바꿔 쓰지 않는다):
  · 엉성한 답에서 「짚은 것(covered)」 근거 줄인데 그 줄의 숫자가 답 글에 하나도 없는 것 — 답이 말하지 않은 것을 짚었다고 보인다.
  · 엉성한 답 반응 중 답에 없는 숫자를 들어 칭찬하는 문장 — 다음 문장이나 되묻기(followup)로 갈음한다.
- 개인정보 · 키 · 내부 경로는 거른다(scrub) — 세션 id · 파일 경로 · 메일 · 전화 · 키 모양 글. 맨 끝에 한 번 더 훑어 남아 있으면 실패한다.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REC_DIR = HERE / "out" / "recordings"
TOUR_DIR = ROOT / "demo" / "YEHS_demo" / "data" / "tour"
ASSETS = ROOT / "demo" / "YEHS_demo"

#: 투어 덱 차례(index.json) — 첫째가 기본 덱. 부스 덱 C · A · B.
ORDER = ["delivery-rating", "battery-fastcharge", "microplastic-daphnia"]
LABELS = {"delivery-rating": "C-1", "battery-fastcharge": "A-1", "microplastic-daphnia": "B-1"}
ASKER_BY_SITUATION = {   # app.js QA_AUD_BY_OCC 와 같은 값
    "학교 프로젝트 (교수 대상)": "교수님", "신제품 설명 (대중 대상)": "청중", "업무 보고 (상사 대상)": "상사", "동료 간 캐주얼 PR": "동료",
}
VERDICT_LEVEL = {"good": "good", "partial": "fair", "wrong": "practice", "unknown": "practice"}
PACE_GOOD = (300, 350)
FAST_CPM, SLOW_CPM = 350 * 1.15, 300 * 0.85      # js/vision_cue.js VISION.fastCpm · slowCpm
CHIP_WINDOW_SEC, CHIP_GAP_SEC, CHIP_REPEAT_SEC, CHIP_MAX = 8.0, 14.0, 30.0, 6
SNAP_SEC = 6.0   # 장 넘김을 문장 끝으로 옮길 수 있는 거리
NODE_MAX = 12
#: 사람이 자료와 맞춰 보고 뺀 질문 — {투어 id: {질문 id 앞부분: 이유}}. 판정이 good 이라도 정답 자체가 틀리면 방문객에게 틀린 답을 정답으로 보인다.
EXCLUDE = {
    "battery-fastcharge": {
        "q03-2c-chungjeoneun": "골자 오답(질문은 25 °C · 76% 인데 45 °C · 64% 줄을 답으로 잡음)",
    },
}

# ─── 글 다루기 ──────────────────────────────────────────────────────────────

_SCRUB = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[메일]"),
    (re.compile(r"https?://\S+"), "[링크]"),
    (re.compile(r"(?<!\d)0\d{1,2}-\d{3,4}-\d{4}(?!\d)"), "[전화]"),
    (re.compile(r"(?:/home|/tmp|/var|/Users|[A-Za-z]:\\)[^\s'\"]*"), "[경로]"),
    (re.compile(r"\b(?:sk|up|pk|rk|key)[-_][A-Za-z0-9_-]{16,}\b"), "[키]"),
    (re.compile(r"\b[A-Fa-f0-9]{32,}\b"), "[키]"),
]
#: 끝에 한 번 더 훑는 금지 모양 — 하나라도 남으면 build 가 실패한다 (scrub 이 놓친 것을 공개 파일로 내보내지 않는다)
FORBIDDEN = re.compile(r"session_id|/home/|/tmp/|\.env\b|[\w.+-]+@[\w-]+\.\w+|\b(?:sk|up)[-_][A-Za-z0-9]{16,}|\b[A-Fa-f0-9]{32,}\b")


def scrub(text: str) -> str:
    out = str(text or "")
    for pat, rep in _SCRUB:
        out = pat.sub(rep, out)
    return re.sub(r"\s+", " ", out).strip()


def clip(text: str, limit: int) -> str:
    """limit 자 안으로 — 문장 끝 → 절 경계(, · — /) → 낱말 경계 순으로 자르고, 자른 곳엔 「…」. 뜻을 바꾸지 않게 앞부분만 남긴다."""
    t = scrub(text)
    if len(t) <= limit:
        return t
    head = t[: limit - 1]
    for pat in (r"[.!?。](?=\s)", r"(?:,|·|—| / |;)\s", r"\s"):
        cuts = [m.end() for m in re.finditer(pat, head)]
        cuts = [c for c in cuts if c >= limit * 0.45]
        if cuts:
            cut = head[: cuts[-1]].rstrip(" ,·—/;")
            return cut if re.search(r"[.!?。]$", cut) else cut + "…"
    return head.rstrip() + "…"


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?。])\s+", scrub(text)) if s.strip()]


def numbers(text: str) -> set[str]:
    """비교용 숫자 토큰 — 쉼표를 뺀 숫자 덩어리 (「3,200」 = 「3200」)."""
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", str(text or ""))}


def three_level(score: float, good: float = 85, fair: float = 70) -> str:
    return "good" if score >= good else "fair" if score >= fair else "practice"


# ─── 덱 ────────────────────────────────────────────────────────────────────

_KICKER = re.compile(r"^(?:\S\s){3,}\S$")   # 「가 설 과 검 증」 처럼 한 글자씩 띄운 머리말


def letter_spaced(line: str) -> bool:
    """글자마다 띄운 장식 줄인가 — 표지 머리줄 「배 터 리 공 학 과 … · 2 0 2 6 . 1 0 . 6 .」.
    「·」 가 섞여 _KICKER 정규식을 빠져나가서 A-1 · B-1 투어 제목이 머리줄이 됐다(10-12 통합 캡처). app.js letterSpacedLine 과 같은 잣대."""
    words = (line or "").split()
    singles = sum(1 for w in words if len(w) == 1 and re.match(r"[가-힣0-9]", w))
    return bool(_KICKER.match(line or "")) or (singles >= 5 and singles >= 0.7 * len(words))


def slide_headline(slide: dict) -> str:
    """장 제목 — 파서 제목이 8자 이상이면 그것, 아니면 본문 첫 문단(머리말 · 표 · 그림 빼고, 8자 이상 한 줄)."""
    title = scrub(slide.get("title") or "")
    if len(title) >= 8 and not letter_spaced(title):
        return title
    for b in slide.get("blocks") or []:
        text = scrub(b.get("text") or "")
        if b.get("category") not in ("paragraph", "heading1", "heading2") or "\n" in (b.get("text") or "") or "|" in text:
            continue
        if len(text) >= 8 and not letter_spaced(text):
            return text
    return title or f"{slide.get('slide_no')}장"


def deck_section(deck_id: str, slide_doc: dict) -> dict:
    slides = slide_doc.get("slides") or []
    first = slides[0] if slides else {}
    title = slide_headline(first)
    subtitle = None
    seen = False
    for b in first.get("blocks") or []:
        text = scrub(b.get("text") or "")
        if seen and b.get("category") == "paragraph" and 4 <= len(text) <= 40 and "\n" not in (b.get("text") or ""):
            subtitle = text
            break
        seen = seen or text == title
    return {
        "id": deck_id, "title": clip(title, 40), "subtitle": subtitle, "cover": f"assets/deck-covers/{deck_id}.webp",
        "slides": [{"no": i + 1, "image": f"assets/deck-slides/{deck_id}/{i + 1}.webp", "title": clip(slide_headline(s), 40)}
                   for i, s in enumerate(slides)],
    }


# ─── 발표 재생 ──────────────────────────────────────────────────────────────

def slide_spans(transcript: dict, duration: float) -> list[dict]:
    """장별 넘김 시각 — 받아쓰기 구간(by_slide) 그대로. 같은 장을 다시 간 구간(visit>1)은 앞 구간에 이어 붙이지 않고 시간 차례대로 둔다."""
    spans = []
    for s in sorted(transcript.get("by_slide") or [], key=lambda x: x.get("start_sec") or 0):
        start, end = round(float(s["start_sec"]), 2), round(min(float(s["end_sec"]), duration), 2)
        if spans and start < spans[-1]["end_sec"]:
            start = spans[-1]["end_sec"]
        if end > start:
            spans.append({"slide_no": int(s["slide_no"]), "start_sec": start, "end_sec": end})
    return spans


def snap_spans(spans: list[dict], words: list[dict]) -> list[dict]:
    """
    추정한 장 넘김이 문장 한가운데면(받아쓰기 재분할은 낱말 단위다) 그 문장이 끝나는 곳으로 옮긴다 — SNAP_SEC 안에서만.
    자막 한 줄이 두 장에 갈라져 「…리뷰를 / 아예 안 쓴다는 건데」 가 다음 장 그림 위에 뜨지 않게. 새 값은 만들지 않는다(낱말 끝 시각).
    """
    out = [dict(s) for s in spans]
    for i in range(len(out) - 1):
        b = out[i]["end_sec"]
        prev = [w for w in words if w["end_sec"] <= b + 0.05]
        if not prev or re.search(r"[.!?。]$", prev[-1]["text"]):
            continue
        ends = [w for w in words if b < w["end_sec"] <= b + SNAP_SEC and re.search(r"[.!?。]$", w["text"])]
        if ends and ends[0]["end_sec"] < out[i + 1]["end_sec"]:
            nb = round(ends[0]["end_sec"], 2)
            out[i]["end_sec"], out[i + 1]["start_sec"] = nb, nb
    return out


def _slide_at(spans: list[dict], t: float) -> int:
    for s in spans:
        if s["start_sec"] <= t < s["end_sec"]:
            return s["slide_no"]
    return spans[-1]["slide_no"] if spans else 1


def transcript_chunks(words: list[dict], spans: list[dict], limit: int = 60) -> list[dict]:
    """자막 조각 — 문장 끝 · 0.8초 넘는 쉼 · 장 넘김 · limit 자에서 끊는다. 시각은 낱말 시각 그대로."""
    chunks: list[dict] = []
    cur: list[dict] = []

    def flush():
        if cur:
            text = clip(" ".join(w["text"] for w in cur), 80)
            if text:
                chunks.append({"slide_no": _slide_at(spans, cur[0]["start_sec"]), "start_sec": round(cur[0]["start_sec"], 2),
                               "end_sec": round(cur[-1]["end_sec"], 2), "text": text})
            cur.clear()

    for w in words:
        if not (w.get("text") or "").strip():
            continue
        if cur:
            gap = w["start_sec"] - cur[-1]["end_sec"]
            joined = len(" ".join(x["text"] for x in cur)) + 1 + len(w["text"])
            if gap > 0.8 or joined > limit or _slide_at(spans, w["start_sec"]) != _slide_at(spans, cur[0]["start_sec"]):
                flush()
        cur.append(w)
        if re.search(r"[.!?。]$", w["text"]):
            flush()
    flush()
    return chunks


def _rate_at(words: list[dict], t: float) -> float | None:
    """t 까지 8초 창의 말 속도(자/분) — vision_cue.js speakingRate 처럼 낱말 사이 쉼은 2초까지만 말한 시간으로 센다."""
    win = [w for w in words if t - CHIP_WINDOW_SEC <= w["start_sec"] <= t]
    if len(win) < 3:
        return None
    chars = sum(len(re.findall(r"[가-힣A-Za-z0-9]", w["text"])) for w in win)
    speak = sum(min(b["start_sec"] - a["start_sec"], 2.0) for a, b in zip(win, win[1:]))
    if chars < 12 or speak < 2.2:
        return None
    return chars / (speak / 60)


def filler_word(text) -> str:
    return re.sub(r"[.,!?…]+", "", scrub(text or "")).strip()


def _free(kept: list[dict], at: float) -> bool:
    return all(abs(at - c["at_sec"]) >= CHIP_GAP_SEC for c in kept)


def coaching_chips(words: list[dict], spans: list[dict], habits: dict, pace: dict, duration: float) -> list[dict]:
    """
    코칭 칩 — 녹화에서 잰 신호만: 첫 말(listen) · 말버릇 구간(filler) · 권장보다 긴 장(time) · 8초 창 말 속도(fast/slow, vision_cue 문턱).
    음량(quiet/loud)은 녹음 크기를 재지 않아서 만들지 않는다. 칩끼리 CHIP_GAP_SEC 는 띄운다 — 사건(말버릇 · 시간)이 먼저 자리를 잡고,
    말 속도는 그 상태가 이어지는 동안 빈자리에 한 번. 같은 속도 칩은 CHIP_REPEAT_SEC 안에 다시 내지 않는다.
    """
    events: list[dict] = []
    for sp in habits.get("spans") or []:
        if sp.get("kind") == "FIL" and filler_word(sp.get("text")):
            events.append({"at_sec": round(float(sp["start_sec"]), 1), "kind": "filler",
                           "text": clip(f"「{filler_word(sp['text'])}」가 들렸어요", 16)})
    for ps in pace.get("slides") or []:
        span = next((s for s in spans if s["slide_no"] == ps.get("slide_no")), None)
        if span and ps.get("status") == "long" and ps.get("recommended_sec"):
            at = span["start_sec"] + float(ps["recommended_sec"])
            if at < span["end_sec"]:
                events.append({"at_sec": round(at, 1), "kind": "time", "text": "이 장이 길어요"})
    kept: list[dict] = []
    if words:
        kept.append({"at_sec": round(min(words[0]["start_sec"] + 3, duration), 1), "kind": "listen", "text": "잘 듣고 있어요"})
    for ev in sorted(events, key=lambda c: c["at_sec"]):
        if ev["at_sec"] <= duration and _free(kept, ev["at_sec"]):
            kept.append(ev)
    run, pending, last_at = "", "", {}
    t = (words[0]["start_sec"] if words else 0) + CHIP_WINDOW_SEC
    while t < duration:
        cpm = _rate_at(words, t)
        kind = "fast" if cpm and cpm > FAST_CPM else "slow" if cpm and cpm < SLOW_CPM else ""
        if kind != run:
            run, pending = kind, kind
        if pending and _free(kept, t) and t - last_at.get(pending, -1e9) >= CHIP_REPEAT_SEC:
            kept.append({"at_sec": round(t, 1), "kind": pending, "text": "조금 빨라요" if pending == "fast" else "조금 느려요"})
            last_at[pending], pending = t, ""
        t += 2.0
    if len(kept) > CHIP_MAX:   # 넘치면 말 속도 칩부터 덜어 낸다 (사건이 더 구체적이다)
        pace_chips = [c for c in kept if c["kind"] in ("fast", "slow")]
        drop = {id(c) for c in pace_chips[len(pace_chips) - (len(kept) - CHIP_MAX):]} if len(pace_chips) >= len(kept) - CHIP_MAX else set()
        kept = [c for c in kept if id(c) not in drop][:CHIP_MAX]
    kept.sort(key=lambda c: c["at_sec"])
    return [{"at_sec": c["at_sec"], "slide_no": _slide_at(spans, c["at_sec"]), "kind": c["kind"], "text": c["text"]} for c in kept]


def present_section(transcript: dict, habits: dict, pace: dict) -> dict:
    # 0.1초 단위로 **올린다** — 내리면 마지막 낱말 끝이 재생 길이 밖으로 나간다
    duration = math.ceil(float(transcript.get("duration_sec") or 0) * 10) / 10
    words = [w for w in transcript.get("words") or [] if w.get("end_sec", 0) <= duration]
    spans = snap_spans(slide_spans(transcript, duration), words)
    return {"duration_sec": duration, "slides": spans, "transcript": transcript_chunks(words, spans),
            "coaching_chips": coaching_chips(words, spans, habits, pace, duration)}


# ─── 분석 ───────────────────────────────────────────────────────────────────

def pace_level(cpm: float) -> str:
    lo, hi = PACE_GOOD
    if lo <= cpm <= hi:
        return "good"
    return "fair" if SLOW_CPM <= cpm <= FAST_CPM else "practice"


def slide_level(ps: dict) -> str:
    if ps.get("status") in (None, "", "ok"):
        return "good"
    rec = float(ps.get("recommended_sec") or 0)
    off = abs(float(ps.get("delta_sec") or 0)) / rec if rec else 0
    return "practice" if off > 0.4 else "fair"


SLIDE_NOTE = {"short": "권장 시간보다 짧았어요", "long": "권장 시간보다 길었어요"}
KIND_MAP = {"thesis": "claim", "claim": "reason", "evidence": "evidence", "concept": "concept"}


def claim_graph(graph: dict, alignment: dict) -> dict:
    verdict = {it["node_id"]: it.get("verdict") for it in alignment.get("items") or []}
    nodes = graph.get("nodes") or []
    root = graph.get("thesis") or (nodes[0]["id"] if nodes else "")
    ranked = sorted(nodes, key=lambda n: (n["id"] != root, -(n.get("weight") or 0)))[:NODE_MAX]
    keep = {n["id"] for n in ranked}
    out_nodes = [{"id": re.sub(r"[^a-z0-9_-]", "-", n["id"].lower())[:60], "src": n["id"], "label": clip(n.get("label") or n["id"], 30),
                  "kind": KIND_MAP.get(n.get("kind") or "", "concept"),
                  "status": verdict.get(n["id"]) if verdict.get(n["id"]) in ("aligned", "justified_skip", "missing", "contradiction") else "missing",
                  "slide_no": (n.get("slide_nos") or [None])[0]} for n in ranked]
    ids = {n["src"]: n["id"] for n in out_nodes}
    edges = [{"from": ids[e["from"]], "to": ids[e["to"]]} for e in graph.get("edges") or []
             if e.get("from") in keep and e.get("to") in keep and e["from"] != e["to"]]
    # 요약 숫자는 **보여 주는 노드**로 센다 — 원본 전체(22개 중 14개)로 세면 바로 아래 범례(12개: 잘 설명함 8 · 아직 4)와
    # 한 카드 안에서 숫자가 달랐다(10-12 점검, CLAUDE.md §3-4 숫자는 신성하다). 잘랐으면 「중요한」 을 붙여 일부임을 밝힌다.
    counts = Counter(n["status"] for n in out_nodes)
    shown = len(out_nodes)
    said = counts["aligned"] + counts["justified_skip"]
    which = "중요한 개념" if len(nodes) > shown else "자료의 핵심 개념"
    summary = f"{which} {shown}개 가운데 {said}개를 발표에서 말했어요."
    if counts["contradiction"]:
        summary += f" 자료와 어긋나게 말한 곳이 {counts['contradiction']}곳 있어요."
    root_status = next((n["status"] for n in out_nodes if n["src"] == root), "")
    if root_status == "missing":
        summary = clip(summary + " 핵심 주장은 말하지 않은 것으로 봤어요.", 90)
    return {"summary": clip(summary, 90), "root": ids.get(root, out_nodes[0]["id"] if out_nodes else ""),
            "nodes": [{k: v for k, v in n.items() if k != "src"} for n in out_nodes], "edges": edges}


def analysis_section(rec: dict, duration: float) -> dict:
    pace, habits, rubric, report = rec["pace"], rec["habits"], rec["rubric"], rec["report"]
    cpm = round(float(pace.get("avg_chars_per_min") or 0), 1)
    lo, hi = PACE_GOOD
    pace_note = "권장 빠르기예요" if lo <= cpm <= hi else f"권장({lo}~{hi}자/분)보다 {'느려요' if cpm < lo else '빨라요'}"
    fil = [filler_word(s.get("text")) for s in habits.get("spans") or [] if s.get("kind") == "FIL" and filler_word(s.get("text"))]
    count = int(habits.get("filler_cnt") or len(fil))
    per_min = round(count / (duration / 60), 1) if duration else 0.0
    return {
        "summary": clip(plain_terms(curated(rec.get("tour_deck_id") or "", "one_liner", report.get("one_liner") or "")), 90) or "발표를 분석했어요.",
        "level": three_level(float(rubric.get("score") or 0)),
        "slide_times": [{"slide_no": int(p["slide_no"]), "sec": round(float(p.get("actual_sec") or 0), 1), "level": slide_level(p),
                         "note": SLIDE_NOTE.get(p.get("status") or "")} for p in pace.get("slides") or []],
        "pace": {"cpm": cpm, "level": pace_level(cpm), "note": pace_note},
        "fillers": {"count": count, "per_min": per_min,
                    "top": [{"word": clip(w, 8), "count": c} for w, c in Counter(fil).most_common(5)],
                    "level": "good" if per_min <= 2 else "fair" if per_min <= 5 else "practice"},
        "claim_graph": claim_graph(rec["graph"], rec["alignment"]),
    }


# ─── 질문 · 판정 ────────────────────────────────────────────────────────────

_PRAISE = re.compile(r"정확|맞아요|맞게|맞습니다|잘 (?:설명|짚|말)|짚었")
_LEAD = re.compile(r"^(?:그런데|하지만|다만|그러나)\s*,?\s*")


def feedback_text(judge: dict, answer: str) -> str:  # noqa: C901
    """판정 반응의 첫 문장(90자). 좋지 않은 판정에서 답에 없는 숫자를 들어 칭찬한 문장은 건너뛴다 — 없으면 되묻기(followup)."""
    said = numbers(answer)
    picked = ""
    for s in sentences(tidy(judge.get("react") or "")):
        if judge.get("verdict") != "good" and _PRAISE.search(s) and numbers(s) - said:
            continue
        picked = _LEAD.sub("", s)
        break
    if not picked:
        picked = tidy(judge.get("followup") or judge.get("summary_sentence") or "")
    return clip(picked, 90) or "판정을 받았어요."


def tidy(text: str) -> str:
    """판정 문구의 알려진 군더더기 — 「자료 자료 2장」 처럼 장 번호를 끼우며 겹친 낱말(_judge_grounds.cite_slides)."""
    return re.sub(r"\b(자료)\s+\1\b", r"\1", scrub(text))


def note_text(note: str) -> str:
    """근거 설명 60자 — 길면 「…하므로, <결론>」 의 결론 절만 (왜 근거인지가 거기 있다). 그래도 길면 앞에서 자른다."""
    t = re.sub(r"^이 줄은\s*", "", tidy(note))
    if len(t) > 60:
        tail = re.split(r"(?:므로|으며|하여|어서|아서),\s+", t)[-1].strip()
        if 8 <= len(tail) <= 60 and tail != t:
            return tail
    return clip(t, 60)


def grounds_view(judge: dict, answer: str) -> list[dict]:
    said = numbers(answer)
    out = []
    for g in judge.get("grounds") or []:
        if not re.fullmatch(r"S\d+-\d+", str(g.get("ref") or "")):
            continue
        nums = numbers(g.get("quote"))
        if judge.get("verdict") != "good" and nums:
            if g.get("role") == "covered" and not (nums & said):
                continue   # 답이 말하지 않은 숫자 줄을 「짚은 것」 으로 보이지 않는다
            if g.get("role") == "missing" and nums <= said:
                continue   # 답이 그대로 말한 줄을 「빠진 것」 으로 보이지 않는다
        out.append({"slide_no": int(g["slide_no"]), "ref": g["ref"], "quote": clip(g.get("quote") or "", 80),
                    "role": g.get("role") if g.get("role") in ("covered", "missing", "conflict") else "missing",
                    "note": note_text(g.get("note") or "")})
    return out[:3]


def answer_view(judge: dict, text: str) -> dict:
    verdict = judge.get("verdict") if judge.get("verdict") in VERDICT_LEVEL else "unknown"
    return {"text": clip(text, 200), "verdict": verdict, "level": VERDICT_LEVEL[verdict],
            "feedback": feedback_text(judge, text), "grounds": grounds_view(judge, text)}


def qa_section(rec: dict, have: set[int]) -> tuple[dict, list[str]]:
    questions, dropped = [], []
    skip = EXCLUDE.get(rec.get("tour_deck_id") or "", {})
    for row in rec["judged"]:
        q, good, rough = row["question"], row.get("good"), row.get("rough")
        qid = re.sub(r"[^a-z0-9_-]", "-", str(q.get("id") or f"q{len(questions) + 1}").lower())[:40]
        short = qid.split("-")[0]
        reason = next((why for pre, why in skip.items() if qid.startswith(pre)), "")
        if reason:
            dropped.append(f"{short} {reason}")
            continue
        if not good or not rough:
            dropped.append(f"{short} 판정 없음")
            continue
        if good.get("verdict") != "good" or rough.get("verdict") == "good":
            dropped.append(f"{short} 잘 답한 답 {good.get('verdict')} · 엉성한 답 {rough.get('verdict')}")
            continue
        sn = q.get("evidence_slide_no") or (q.get("slide_nos") or [1])[0]
        questions.append({"id": qid, "slide_no": int(sn) if int(sn) in have else min(have), "question": clip(q.get("question") or "", 120),
                          "answers": {"good": answer_view(good, row["good_text"]), "rough": answer_view(rough, row["rough_text"])}})
    asker = ASKER_BY_SITUATION.get(rec.get("situation") or "", "질문자")
    return {"asker": asker, "questions": questions[:5]}, dropped


# ─── 리포트 문구 다듬기 ──────────────────────────────────────────────────────
# 10-12 점검(perf-security-copy-r1-4 · layout-touch-a11y-r1-4): 리포트 평가 문구가 해요체 · 한다체 · 합쇼체 · 음슴체로 섞이고,
# 60자에서 「…」 로 잘리고, 항목 이름이 「언어적 명료성」 같은 명사+명사 한자어였다(CLAUDE.md §3-1). 분석 화면은 「핵심 주장은
# 말하지 않은 것으로 봤어요」 인데 리포트는 「핵심 주장이 명확히 제시」 라고 해서 한 화면 건너 서로 어긋났다.
# 규칙은 둘이다. (1) 정해진 모양의 문구(채점기 det 문장)는 용어만 바꾼다 — 숫자 · 뜻은 그대로. (2) LLM 문장은 사람이 녹화본을 읽고
# 해요체 한 문장으로 다듬은 것만 쓴다(EXCLUDE 와 같은 사람 검수). 원문 앞부분이 같을 때만 바꾸므로, 다시 녹화해 원문이 바뀌면 원문이 남는다.

#: 묶음 key → 풀어 쓴 항목 이름 (14자 이하)
LABEL_PLAIN = {
    "content": "자료와 맞게 말했나", "logic": "흐름이 이어지나", "audience": "듣는 사람에게 맞나", "clarity": "말이 또렷한가",
    "delivery": "목소리와 빠르기", "visual": "자료 화면", "time": "시간 나누기",
}


def _signed_sec(m: re.Match) -> str:
    return f"({m.group(1)}장은 {m.group(3)}초 {'더' if m.group(2) == '+' else '덜'} 썼어요)"


#: 용어 맞추기 — 장 번호는 「N장」, 개수는 「N개 장」, 간투어는 「군더더기 말」 (perf-security-copy-r1-7). 차례가 중요하다(좁은 것 먼저)
TERM_RULES: list[tuple[re.Pattern, object]] = [
    (re.compile(r"간투어"), "군더더기 말"),
    (re.compile(r"구조 신호어를 (\d+)종류"), r"흐름을 알리는 말을 \1종류"),
    (re.compile(r"\((\d+)번이 ([+-])(\d+)초\)"), _signed_sec),
    (re.compile(r"핵심 슬라이드\s*\((\d+)번, (\d+)번\)"), r"핵심 장(\1장 · \2장)"),
    (re.compile(r"핵심 슬라이드 (\d+)장이"), r"핵심 장 \1개가"),
    (re.compile(r"핵심 슬라이드 (\d+)번"), r"핵심 장인 \1장"),
    (re.compile(r"근거 자료 (\d+)장 중 (\d+)장에"), r"근거 자료 \1개 장 중 \2개 장에"),
    (re.compile(r"근거 자료 (\d+)장 모두"), r"근거 자료 \1개 장 모두"),
    (re.compile(r"출처가 없는 슬라이드 (\d+)장"), r"출처가 없는 장 \1개"),
    (re.compile(r"\(([\d, ]+)번\)"), r"(\1장)"),
    (re.compile(r"(핵심|보조) 장([+-])(\d+)%"), r"\1 장 \3%"),
    (re.compile(r"(\d+)개 슬라이드"), r"\1개 장"),
    (re.compile(r"슬라이드"), "장"),
    (re.compile(r"해보세요"), "해 보세요"),
]


def plain_terms(text: str) -> str:
    for pat, rep in TERM_RULES:
        text = pat.sub(rep, text)
    return text


#: 사람이 녹화본을 읽고 다듬은 문구 — {(투어 id, 칸): (원문 앞부분, 다듬은 문장)}. 원문 앞부분이 다르면(다시 녹화) 적용하지 않는다.
#: 칸: "one_liner"(분석 요약 · 리포트 제목), "headline"(리포트 제목만, 40자), "item:<묶음 key>", "step:<차례>".
CURATED: dict[tuple[str, str], tuple[str, str]] = {
    # 분석 화면이 「핵심 주장은 말하지 않은 것으로 봤어요」 — 도입에서 밝힌 것은 주제(「…를 발표하겠습니다」)라 그만큼만 적는다
    ("delivery-rating", "item:logic"): ("도입부에서 발표 목적과 핵심 주장이", "도입에서 발표 주제와 목적을 분명히 밝혔어요"),
    ("delivery-rating", "item:audience"): ("정보 전달과 설득 목적을 명확히 구분해", "행동 지표 노출 같은 구체적인 해결 방안을 강조했어요"),
    ("battery-fastcharge", "item:logic"): ("도입부에서 발표 목적과 핵심 주장을", "도입에서 발표 주제와 목적을 분명히 밝혔어요"),
    ("battery-fastcharge", "item:audience"): ("배터리 수명 감소라는 핵심 메시지를", "배터리 수명이 줄어든다는 핵심 메시지를 분명히 강조했어요"),
    ("battery-fastcharge", "one_liner"): ("간투어가 한 번 있었지만", "군더더기 말이 한 번 있었지만 자료와 잘 맞았어요. 핵심 장에 시간을 더 넣어 보세요."),
    ("microplastic-daphnia", "item:logic"): ("생존율과 산자수 감소의 관계를", "생존율과 새끼 수가 함께 줄어든 관계를 모순 없이 설명했어요"),
    ("microplastic-daphnia", "item:audience"): ("청중(교수 대상)의 전문성에 비해", "교수 청중의 전문성에 비해 설명이 너무 단순했어요"),
    ("microplastic-daphnia", "headline"): ("청중 맞춤 설명이 부족하고", "청중에 맞춘 설명과 출처 표기를 더해 봐요"),
    ("microplastic-daphnia", "step:0"): ("청중이 교수라는 걸 기억하고", "실험 농도가 실제 하천보다 백 배 넘게 높다는 점을 숫자로 말해 보세요."),
    ("microplastic-daphnia", "step:1"): ("실험 농도와 실제 하천 농도를 비교하는", "실험 농도와 실제 하천 농도를 견주고, 출처가 없는 장 4개에 근거를 적어 보세요."),
}


def curated(deck: str, slot: str, text: str) -> str:
    prefix, fixed = CURATED.get((deck, slot), ("", ""))
    return fixed if prefix and text.startswith(prefix) else text


def report_note(deck: str, key: str, raw: str) -> str:
    """리포트 한 줄(60자) — 다듬은 문장이 있으면 그것, 아니면 용어만 맞춘다. 길면 괄호 속 예시부터 뺀다(가운데서 「…」 로 잘리지 않게)."""
    t = plain_terms(curated(deck, f"item:{key}", scrub(raw)))
    if len(t) > 60:
        t = re.sub(r"\s*\([^)]*\)\s*$", "", t)
    return clip(t, 60)


# ─── 리포트 ─────────────────────────────────────────────────────────────────

def report_section(rec: dict, have: set[int]) -> dict:
    rubric, report = rec["rubric"], rec["report"]
    deck = rec.get("tour_deck_id") or ""
    by_no = {it["no"]: it for it in rubric.get("items") or []}
    items = []
    for c in rubric.get("clusters") or []:
        if c.get("status") != "scored":
            continue
        level = three_level(float(c.get("average") or 0))
        scored = [by_no[n] for n in c.get("item_nos") or [] if n in by_no and by_no[n].get("status") == "scored"]
        pick = (max if level == "good" else min)(scored, key=lambda it: it.get("score") or 0) if scored else {}
        note = pick.get("evidence") if pick.get("source") == "det" else (pick.get("note") or pick.get("evidence") or "")
        key = str(c.get("key") or "item")
        items.append({"id": re.sub(r"[^a-z0-9_-]", "-", key)[:30], "label": LABEL_PLAIN.get(key) or clip(c.get("name") or "", 14),
                      "level": level, "note": report_note(deck, key, note or "")})
    steps = []
    for i, a in enumerate((report.get("actions") or [])[:3]):
        m = re.search(r"(\d+)\s*번", a)
        n = int(m.group(1)) if m and int(m.group(1)) in have else None
        steps.append({"text": clip(plain_terms(curated(deck, f"step:{i}", a)), 60), "slide_no": n})
    one = report.get("one_liner") or "발표를 분석했어요"
    head = curated(deck, "headline", one)
    head = plain_terms(curated(deck, "one_liner", one) if head == one else head)
    return {"headline": clip(head, 40), "items": items[:8],
            "next_steps": steps or [{"text": "다시 한 번 발표해 봐요", "slide_no": None}]}


# ─── 조립 ───────────────────────────────────────────────────────────────────

def build_tour(rec: dict) -> dict:
    deck_id = rec["tour_deck_id"]
    deck = deck_section(deck_id, rec["slide_doc"])
    have = {s["no"] for s in deck["slides"]}
    present = present_section(rec["transcript"], rec["habits"], rec["pace"])
    qa, dropped = qa_section(rec, have)
    note = (f"부스 덱 {LABELS.get(deck_id, deck_id)} 녹음을 실 API 브리지(labs/tour_capture)로 한 번 태운 응답. "
            f"받아쓰기 {rec['transcript'].get('provider') or '?'} · 판정 {rec['questions_doc'].get('model') or '?'} · 5분 코칭 질문.")
    if dropped:
        note += " 뺀 질문: " + "; ".join(dropped)
    tour = {
        "schema": "chuckchuck.tour", "version": 1, "id": deck_id,
        "source": {"kind": "recorded", "recorded_at": rec.get("recorded_at"), "note": clip(note, 200)},
        "deck": deck, "present": present, "analysis": analysis_section(rec, present["duration_sec"]),
        "qa": qa, "report": report_section(rec, have),
    }
    leaks = forbidden_hits(tour)
    if leaks:
        raise ValueError(f"{deck_id}: 공개 파일에 내보내면 안 되는 글이 남았어요 — {leaks[:3]}")
    return tour


def forbidden_hits(value, path: str = "$") -> list[str]:
    if isinstance(value, dict):
        return [h for k, v in value.items() for h in forbidden_hits(v, f"{path}.{k}")]
    if isinstance(value, list):
        return [h for i, v in enumerate(value) for h in forbidden_hits(v, f"{path}[{i}]")]
    if isinstance(value, str) and FORBIDDEN.search(value):
        return [f"{path}: {value[:60]}"]
    return []


def build_index(tours: list[dict]) -> dict:
    rank = {d: i for i, d in enumerate(ORDER)}
    tours = sorted(tours, key=lambda t: rank.get(t["id"], len(ORDER)))
    return {"schema": "chuckchuck.tour-index", "version": 1, "default": tours[0]["id"] if tours else None,
            "tours": [{"id": t["id"], "label": LABELS.get(t["id"], t["id"]), "title": t["deck"]["title"], "subtitle": t["deck"].get("subtitle"),
                       "cover": t["deck"]["cover"], "slides": len(t["deck"]["slides"]), "duration_sec": t["present"]["duration_sec"],
                       "questions": len(t["qa"]["questions"]), "recorded_at": t["source"]["recorded_at"]} for t in tours]}


def dump(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="녹화본 → data/tour/<덱>.json + index.json")
    ap.add_argument("--check", action="store_true", help="쓰지 않고 지금 파일과 같은지만 본다")
    ap.add_argument("--rec-dir", type=Path, default=REC_DIR,
                    help="녹화본 폴더 (기본 labs/tour_capture/out/recordings) — 다른 worktree 에서 녹화했으면 그 폴더를 읽기만 한다")
    args = ap.parse_args(argv)
    rec_dir = args.rec_dir
    recs = sorted(rec_dir.glob("*.json"))
    if not recs:
        print(f"녹화본이 없어요 — 먼저 capture.py 를 돌려요 ({rec_dir})", file=sys.stderr)
        return 1
    tours = [build_tour(json.loads(p.read_text(encoding="utf-8"))) for p in recs]
    files = {TOUR_DIR / f"{t['id']}.json": dump(t) for t in tours}
    files[TOUR_DIR / "index.json"] = dump(build_index(tours))
    stale = [p for p, text in files.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
    if args.check:
        for p in stale:
            print(f"다름: {p.relative_to(ROOT)}")
        return 1 if stale else 0
    for p, text in files.items():
        p.write_text(text, encoding="utf-8")
        print(f"썼어요 {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
