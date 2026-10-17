"""
발표를 들으며 3번+ 질문을 준비한다 (2026-10-17, docs/qa-ensemble/LIVE_REPORT.md) — `POST /api/v1/qa/live` 의 서버 몫.

    브라우저 (발표 중)         장을 넘길 때마다 {session_id, talk_id, slide_no, text, closed} — 그 장에서 확정된 문장 전체(A.X 실시간 받아쓰기)
                               발표를 마치면 {final: true} · 분석이 끝나면 {alignment} (흐림 · 어긋남 신호용)
    여기                        판(talk) 단위로 장별 발화를 쌓고(_ens_live.LiveTalk), 다 들은 장의 새 신호가 생기면
                               그 장 몫 음성 후보를 뒤에서 만든다(f08_ensemble.live_round — 모델 1~2개, F-08-live)
    /qa/next (3번+)            쌓아 둔 후보(candidates)를 고르기 판에 올린다 — 발표가 끝나면 고르기만

규율:
- **열쇠는 세션 + talk_id** — 같은 덱 세션(부스 덱)을 여러 사람이 써도 남의 발화가 섞이지 않는다. talk_id 가 없으면 아무것도 쌓지 않는다.
- 한 발표의 라운드 상한(MAX_ROUNDS) · 한 라운드의 신호 상한(SIGS_PER_ROUND) · 서버 전체 동시 라운드 상한(세마포어). 넘치면 그 장은
  다음 장을 넘길 때 · 발표를 마칠 때 다시 본다. 429 는 f08_ensemble._complete 가 물러났다 다시 부른다.
- 1·2번은 여기 후보를 쓰지 않는다(자료 묶음). 여기 후보는 3번부터.
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time

TALK_RE = re.compile(r"^[A-Za-z0-9_-]{4,48}$")
KEY_TALK = "live_talk:"
KEY_CANDS = "live_cands:"

#: 한 발표(talk)에서 장 단위 후보를 만드는 라운드 상한 — 20장 발표여도 호출이 장 수 × 모델 수로 불지 않게
MAX_ROUNDS = int(os.environ.get("QA_LIVE_MAX_ROUNDS", "8"))
#: 한 라운드에 싣는 신호 상한 (넘는 신호는 다음 라운드)
SIGS_PER_ROUND = int(os.environ.get("QA_LIVE_SIGS", "4"))
#: 발표 중엔 새 신호가 이만큼 모이면 라운드를 돌린다(장마다 하나씩이면 라운드 상한에 일찍 닿아 뒷장이 빠진다 — r1 invest_long 9장에서 멈춤).
#: 발표를 마치면(final) 남은 것을 다 돌린다
MIN_SIGS = int(os.environ.get("QA_LIVE_MIN_SIGS", "2"))
#: 서버 전체에서 동시에 도는 발표 중 라운드 상한 (부스에서 여러 사람이 동시에 발표해도 429 폭주를 막는다)
GLOBAL_ROUNDS = int(os.environ.get("QA_LIVE_GLOBAL", "4"))
#: 쌓는 후보 상한 (판 하나)
CANDS_MAX = 24


def enabled() -> bool:
    """QA_LIVE=1(기본) 이고 앙상블이 켜져 있을 때만 — 앙상블이 꺼져 있으면 3번+ 를 고르지 않는다."""
    from pipeline import f08_ensemble as FE  # noqa: PLC0415
    return FE.enabled() and (os.environ.get("QA_LIVE") or "1").strip().lower() not in ("0", "false", "off", "no")


def talk_of(body: dict) -> str:
    t = str((body or {}).get("talk_id") or "").strip()
    return t if TALK_RE.match(t) else ""


def talk_key(sid: str, talk: str) -> str:
    return f"{sid}:{talk}"


class Listener:
    """
    store: get_triage/set_triage 가 있는 저장소(브리지 STORE). materials(sid) → (graph_raw, slidedoc) 또는 None.
    runner(key, fn) → 뒤에서 돌리기(브리지 _FLIGHTS.run — 같은 열쇠는 한 번만 돈다). llms 는 테스트용 가짜 엔진.
    """

    def __init__(self, store, materials, runner=None, *, llms: dict | None = None, models: list[str] | None = None):
        self.store = store
        self.materials = materials
        self.runner = runner or _thread_runner
        self.llms = llms
        self.models = models
        self._lock = threading.Lock()
        self._sem = threading.BoundedSemaphore(max(1, GLOBAL_ROUNDS))
        self._decks: dict = {}

    # ── 쌓기 ──────────────────────────────────────────────────────────────────────────────────
    def put(self, sid: str, talk: str, *, slide_no: int = 0, text: str | None = None, closed: bool = False,
            final: bool = False, alignment: dict | None = None, transcript: dict | None = None) -> dict:
        from pipeline._ens_live import LiveTalk  # noqa: PLC0415

        k = talk_key(sid, talk)
        with self._lock:
            raw = self.store.get_triage(KEY_TALK + k) or {}
            t = LiveTalk.from_dict(raw)
            t.put(slide_no, text, closed=closed, final=final)
            d = {**t.to_dict(), "alignment": alignment if alignment is not None else raw.get("alignment"),
                 "transcript": transcript if transcript is not None else raw.get("transcript"),
                 "started": raw.get("started") or time.time()}
            self.store.set_triage(KEY_TALK + k, d)
        kicked = False
        if closed or final or alignment is not None:
            self.runner("live_round:" + k, lambda: self._work(sid, talk))
            kicked = True
        return {"slides": len(t.slides), "closed": len(t.closed), "final": t.final, "kicked": kicked}

    def talk(self, sid: str, talk: str) -> dict:
        return self.store.get_triage(KEY_TALK + talk_key(sid, talk)) or {} if talk else {}

    def speech_of(self, sid: str, talk: str) -> dict[int, str]:
        from pipeline._ens_live import LiveTalk  # noqa: PLC0415
        return LiveTalk.from_dict(self.talk(sid, talk)).speech_of() if talk else {}

    def alignment(self, sid: str, talk: str):
        return self.talk(sid, talk).get("alignment") if talk else None

    def transcript(self, sid: str, talk: str):
        """분석이 끝난 뒤 브라우저가 붙인 일괄 받아쓰기 (일찍 시작한 Q&A 의 3번+ 재료). 없으면 None."""
        return self.talk(sid, talk).get("transcript") if talk else None

    def state(self, sid: str, talk: str) -> dict:
        return self.store.get_triage(KEY_CANDS + talk_key(sid, talk)) or {"candidates": [], "rounds": [], "dropped": []} \
            if talk else {"candidates": [], "rounds": [], "dropped": []}

    def candidates(self, sid: str, talk: str) -> list[dict]:
        return list(self.state(sid, talk).get("candidates") or [])

    # ── 뒤에서: 다 들은 장의 새 신호 → 음성 후보 ────────────────────────────────────────────────────────
    def _deck(self, sid: str):
        from pipeline import f08_ensemble as FE  # noqa: PLC0415

        mats = self.materials(sid)
        if not mats or not mats[0] or not mats[1]:
            return None
        graph_raw, slidedoc = mats
        from server.session_store import fingerprint  # noqa: PLC0415
        fp = fingerprint(sorted((n.get("id"), n.get("label")) for n in graph_raw.get("nodes", []) if isinstance(n, dict)),
                         len((slidedoc or {}).get("slides") or []))
        hit = self._decks.get(sid)
        if hit and hit[0] == fp:
            return hit[1]
        deck = FE.Deck.build(graph_raw, slidedoc)
        self._decks[sid] = (fp, deck)
        if len(self._decks) > 32:
            self._decks.pop(next(iter(self._decks)))
        return deck

    def _work(self, sid: str, talk: str) -> int:
        """새 신호가 없을 때까지(라운드 상한 안에서) 돈다. 돌린 라운드 수."""
        from pipeline import f08_ensemble as FE  # noqa: PLC0415
        from pipeline._ens_live import LiveTalk, new_signals, sig_key  # noqa: PLC0415
        from pipeline.contracts import AlignmentDoc  # noqa: PLC0415

        k = talk_key(sid, talk)
        deck = self._deck(sid)
        if deck is None:
            return 0
        done = 0
        while True:
            with self._lock:
                raw = self.store.get_triage(KEY_TALK + k) or {}
                st = self.store.get_triage(KEY_CANDS + k) or {"candidates": [], "rounds": [], "dropped": []}
                if len(st["rounds"]) >= MAX_ROUNDS:
                    return done
                t = LiveTalk.from_dict(raw)
                al = raw.get("alignment")
                al = AlignmentDoc.from_dict(al) if isinstance(al, dict) else None
                sigs = new_signals(t, deck.graph, deck.slides, deck.lines, al)[:SIGS_PER_ROUND]
                if not sigs or (len(sigs) < MIN_SIGS and not t.final):
                    return done
                # 고른 신호는 바로 「썼다」 로 — 같은 신호로 두 라운드가 동시에 돌지 않게 (실패하면 아래에서 되돌린다)
                t.done_sigs = [*t.done_sigs, *(sig_key(s) for s in sigs)]
                self.store.set_triage(KEY_TALK + k, {**raw, **t.to_dict()})
                speech_of = t.speech_of()
            if not self._sem.acquire(timeout=20):
                self._undo(k, sigs)
                return done
            t0 = time.time()
            try:
                vr = FE.live_round(deck, sigs, speech_of, models=self.models, llms=self.llms)
            except Exception as e:  # noqa: BLE001 — 발표 중 준비가 실패해도 발표 · 질문은 그대로 간다
                sys.stderr.write(f"[qa-listen] 라운드 실패: {type(e).__name__}: {str(e)[:120]}\n")
                vr = None
            finally:
                self._sem.release()
            ok_calls = [c for c in (vr.calls if vr else []) if getattr(c, "ok", False)]
            with self._lock:
                st = self.store.get_triage(KEY_CANDS + k) or {"candidates": [], "rounds": [], "dropped": []}
                cands = [*st["candidates"], *((vr.candidates if vr else []))][-CANDS_MAX:]
                rnd = {"at": round(time.time(), 2), "sec": round(time.time() - t0, 2),
                       "slides": sorted({int(s.get("slide_no") or 0) for s in sigs}),
                       "signals": [{"id": s["id"], "kind": s["kind"], "node_id": s["node_id"], "slide_no": s.get("slide_no")}
                                   for s in sigs],
                       "n_cand": len(vr.candidates) if vr else 0, "n_drop": len(vr.dropped) if vr else 0,
                       "calls": [c.to_dict() for c in (vr.calls if vr else [])]}
                self.store.set_triage(KEY_CANDS + k, {"candidates": cands, "rounds": [*st["rounds"], rnd],
                                                      "dropped": [*st["dropped"], *((vr.dropped if vr else []))][-40:]})
            sys.stderr.write(f"[qa-listen] 라운드 talk={talk[:8]} 장={rnd['slides']} 신호={[s['kind'] for s in sigs]} "
                             f"후보={rnd['n_cand']} 버림={rnd['n_drop']} 호출={len(rnd['calls'])}(성공 {len(ok_calls)}) {rnd['sec']}s\n")
            if not ok_calls:
                self._undo(k, sigs)        # 모델이 다 실패했으면 그 신호는 다음 기회(다음 장 · 발표 끝)에 다시
                return done + 1
            done += 1

    def _undo(self, k: str, sigs: list[dict]) -> None:
        from pipeline._ens_live import sig_key  # noqa: PLC0415
        drop = {sig_key(s) for s in sigs}
        with self._lock:
            raw = self.store.get_triage(KEY_TALK + k) or {}
            raw["done_sigs"] = [x for x in raw.get("done_sigs") or [] if x not in drop]
            self.store.set_triage(KEY_TALK + k, raw)


def _thread_runner(key: str, fn):
    th = threading.Thread(target=fn, name=key[:40], daemon=True)
    th.start()
    return th


__all__ = ["Listener", "talk_of", "talk_key", "enabled", "KEY_TALK", "KEY_CANDS"]
