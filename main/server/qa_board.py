"""
네 모델 Q&A 후보 판 (4단계 리포트 「질문은 이렇게 골랐어요」, 2026-10-17) — 브리지가 세션 메모리 · 보관본에 담는 한 묶음.

docs/qa-ensemble/CONTRACT.md §1 의 보관본(`Pool.to_dict()` + `picked`)에 화면이 그리는 데 필요한 칸만 더한다:
- `graph`  — 개념 그래프 노드(id · 라벨 · 종류 · 부모 · 무게 · 장) — 리포트의 미니맵. 그래프 전체(근거 문장 등)는 싣지 않는다
- `paths`  — 슬롯 → 루트까지 라벨 경로 (`_ens_slots.path_to_root` 와 같은 규칙, 그래프 dict 에서 바로)
- `rounds` — 3번 이후 질문마다: 음성 신호 · 네 모델 후보 · 버림 · 최종 선택(누가 · 왜 · 대신 냄)
- `tracks` — 트랙(5분 · 10분 …)마다 1·2번+ 고른 순서 (미리 만들기가 트랙 둘을 만든다)

순수 함수만 — 브리지(STORE · ARCHIVE)가 부르고, 저장 정책(동의 세션만 보관)은 보관소가 그대로 지킨다.
"""
from __future__ import annotations

SCHEMA = "qa-board/1"
#: 판에 싣는 호출 칸 — 프롬프트 · 응답 원문은 싣지 않는다(호출 로그가 따로 남긴다)
CALL_KEYS = ("role", "model", "sec", "ok", "retries", "prompt_tokens", "completion_tokens", "n_in", "n_out")
NODE_KEYS = ("id", "label", "kind", "parent_id", "weight", "slide_nos")
MAX_ROUNDS = 12


def graph_slim(graph_raw) -> dict:
    nodes = []
    for n in (graph_raw or {}).get("nodes", []) if isinstance(graph_raw, dict) else []:
        if isinstance(n, dict) and n.get("id"):
            nodes.append({k: n.get(k) for k in NODE_KEYS if n.get(k) not in (None, "", [])})
    return {"nodes": nodes}


def path_labels(nodes: list[dict], node_id: str) -> list[str]:
    """노드 → 루트 라벨 (자기 포함). 고리가 있어도 멈춘다."""
    by_id = {n["id"]: n for n in nodes}
    out, seen, cur = [], set(), by_id.get(node_id)
    while cur is not None and cur["id"] not in seen:
        seen.add(cur["id"])
        out.append(cur.get("label", ""))
        cur = by_id.get(cur.get("parent_id")) if cur.get("parent_id") else None
    return out


def _calls(rows) -> list[dict]:
    out = []
    for c in rows or []:
        d = c.to_dict() if hasattr(c, "to_dict") else c
        if isinstance(d, dict):
            out.append({k: d.get(k) for k in CALL_KEYS if k in d})
    return out


def board(pool_dict: dict, picked: list[str], graph_raw, *, track: str = "", prev: dict | None = None) -> dict:
    """세션 질문을 고른 순간의 판. prev(같은 세션의 앞 판)가 같은 묶음이면 3번+ 기록(rounds)과 다른 트랙 순서를 잇는다."""
    g = graph_slim(graph_raw)
    slots = list(pool_dict.get("slots") or [])
    same_pool = bool(prev) and [c.get("uid") for c in prev.get("candidates") or []] == \
        [c.get("uid") for c in pool_dict.get("candidates") or []]
    tracks = dict((prev or {}).get("tracks") or {}) if same_pool else {}
    if track:
        tracks[track] = list(picked)
    return {
        "schema": SCHEMA,
        "slots": slots,
        "candidates": list(pool_dict.get("candidates") or []),
        "dropped": list(pool_dict.get("dropped") or []),
        "calls": _calls(pool_dict.get("calls")),
        "timings": dict(pool_dict.get("timings") or {}),
        "models": list(pool_dict.get("models") or []),
        "picked": list(picked),
        "track": track,
        "tracks": tracks,
        "paths": {s["id"]: path_labels(g["nodes"], s.get("node_id", "")) for s in slots if s.get("id")},
        "graph": g,
        "rounds": list((prev or {}).get("rounds") or []) if same_pool else [],
    }



def rebase(base: dict, prev: dict) -> dict:
    """
    같은 Q&A 판(qa_run_id)에 질문을 다시 받았을 때 — 새 바탕(base)에 그 판의 앞 기록을 잇는다. 묶음이 같을 때만 트랙 순서와
    3번+ 기록(rounds)을 가져온다. 바탕은 여러 판이 나눠 쓰므로 고치지 않고 새 dict 를 돌려준다.
    """
    same_pool = [c.get("uid") for c in prev.get("candidates") or []] == [c.get("uid") for c in base.get("candidates") or []]
    if not same_pool:
        return base
    tracks = {**(prev.get("tracks") or {}), **(base.get("tracks") or {})}
    return {**base, "tracks": tracks, "rounds": list(prev.get("rounds") or [])}

def _slim_cand(c: dict) -> dict:
    keep = ("uid", "model", "signal", "signal_kind", "signal_note", "signal_quote", "node_id", "label", "pattern",
            "question", "answer", "why", "lines", "slide_no", "quote", "slot", "peer")
    return {k: c[k] for k in keep if k in c}


def round_record(n: int, nxt: dict, vr, pick_calls, sec: float, *, paths_from: list[dict] | None = None) -> dict:
    """3번 이후 한 질문 — 음성 신호 · 네 모델 후보(통과 · 버림) · 최종 선택. vr 은 f08_ensemble.VoiceRound 또는 None."""
    signals = list(getattr(vr, "signals", None) or [])
    rec = {
        "n": int(n),
        "uid": nxt.get("uid", ""),
        "by": nxt.get("model", ""),
        "question": nxt.get("question", ""),
        "node_id": nxt.get("node_id", ""),
        "label": nxt.get("label", ""),
        "pattern": nxt.get("pattern", ""),
        "slot": nxt.get("slot", ""),
        "signal": nxt.get("signal", ""),
        "signal_kind": nxt.get("signal_kind", ""),
        "signal_note": nxt.get("signal_note", ""),
        # 앞 답 약점(weak_answer)의 인용은 그 사람의 답 원문이다 — 판에 남기지 않는다(같은 파일을 올린 사람끼리 세션을 나눠 쓴다)
        "signal_quote": "" if nxt.get("signal_kind") == "weak_answer" else nxt.get("signal_quote", ""),
        "answer": nxt.get("answer", ""),
        "quote": nxt.get("quote", ""),
        "slide_no": nxt.get("slide_no", 0),
        "substituted": bool(nxt.get("substituted")),
        "pick_failed": bool(nxt.get("pick_failed")),
        "pick_reason": str(nxt.get("pick_reason") or "")[:200],
        "signals": [{k: s.get(k) for k in ("id", "kind", "node_id", "label", "slide_no", "deck_line", "deck_text",
                                            "speech_quote", "note", "move") if s.get(k) not in (None, "")
                     and not (k == "speech_quote" and s.get("kind") == "weak_answer")}
                    for s in signals],
        "candidates": [_slim_cand(c) for c in getattr(vr, "candidates", None) or []],
        "dropped": [{k: d.get(k) for k in ("uid", "model", "signal", "reasons", "question") if k in d}
                    for d in getattr(vr, "dropped", None) or []],
        "calls": _calls(list(getattr(vr, "calls", None) or []) + list(pick_calls or [])),
        "voice_sec": float(getattr(vr, "sec", 0.0) or 0.0),
        "pick_sec": round(float(sec), 2),
    }
    if paths_from is not None and rec["node_id"]:
        rec["path"] = path_labels(paths_from, rec["node_id"])
    return rec


def with_round(b: dict, rec: dict) -> dict:
    """같은 번호면 갈아 끼운다(다시 부른 /qa/next). 번호 순."""
    rounds = [r for r in b.get("rounds") or [] if r.get("n") != rec.get("n")] + [rec]
    rounds.sort(key=lambda r: r.get("n", 0))
    return {**b, "rounds": rounds[-MAX_ROUNDS:]}
