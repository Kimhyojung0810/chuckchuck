"""
벤치 캐시 결정적 재생 — labs/qa_bench/out 의 얼린 산출물(슬라이드·그래프·주장·1차 심사·질문 LLM 응답)을 입력으로
**대상 코드**의 결정적 단계만 다시 돌려 잰다. LLM 을 부르지 않는다 (자식 프로세스, `llm_guard.install("forbid")`).

- F-08 후처리 재생: 대상 `build_questions` 에 얼린 LLM 응답만 주는 제공자(ReplayOnly — 프롬프트 해시가 같을 때만 응답,
  다르면 그 덱·트랙은 「프롬프트 바뀜」 으로 뺀다) → 골자·함정·힌트 인용을 잣대로 잰다.
- 벤치 `collect` (하네스의 labs/qa_bench/run.py — 잣대 고정): 탐침(derive_probes)·힌트 사다리·발판 보기를 대상 코드로.
- 근거 지표(reason_metrics): 「모르겠어요」 보기 쌍 유효 · 심은 근거 질문.

두 대상(main · 통합)을 **같은 입력**으로 재므로 값의 차이는 코드의 차이다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from . import common as C
from . import regress as RG
from . import scoreboard as S
from . import tags as TG
from . import textkit as T

_PREMISE_RE = re.compile(r"전제|사실은|사실과|아니라|아니에요|아닙니다|않아요|않습니다|자료(?:는|에서는)\s*\S+(?:라고|고)\s|오해|잘못|달리")


def _bench():
    """하네스 쪽 벤치 모듈 (잣대) — 대상 chuckchuck 이 이미 sys.modules 에 있어야 한다."""
    bench = str(C.HARNESS_ROOT / "labs" / "qa_bench")
    sys.path.insert(0, bench)
    # 순서가 중요하다 — metrics 가 labs/qa_lab 을 sys.path 맨 앞에 넣어서, 그 뒤에 「import run」 을 하면 qa_lab/run.py 가 온다
    import run as B  # noqa: E402  (벤치 run.py — 안에서 metrics 를 올린다)
    import metrics as M  # noqa: E402
    import reason_metrics as RM  # noqa: E402
    from checks import is_fallback, question_flags  # noqa: E402

    if not hasattr(B, "load_decks"):
        raise ImportError(f"벤치 run.py 가 아닌 것을 올렸어요: {B.__file__}")

    return B, M, RM, is_fallback, question_flags


class ReplayMiss(RuntimeError):
    pass


def make_replay_only(store: dict, hasher):
    from chuckchuck.providers.llm_base import LLMProvider

    class ReplayOnly(LLMProvider):
        name = "replay"

        def __init__(self):
            self.misses = 0
            self.hits = 0

        def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
            got = store.get(hasher(system, user))
            if got is None:
                self.misses += 1
                raise ReplayMiss("얼린 응답에 없는 프롬프트")
            self.hits += 1
            return got["text"]

    return ReplayOnly()


def make_refresher(store: dict, hasher, path: Path):
    """
    얼린 응답이 있으면 그것, 없으면 **실제 제공자**를 불러 같은 해시로 더해 두는 겉감 (refresh 전용 — quick 은 쓰지 않는다).
    실제 제공자는 대상의 `get_llm(None)` 이다 — 호출 세기·예산은 `llm_guard.install("count", …)` 가 그 클래스에 씌운다.
    """
    from chuckchuck.providers.llm_base import LLMProvider
    from chuckchuck.providers.llm_impl import get_llm

    class Refresher(LLMProvider):
        name = "refresh"

        def __init__(self):
            self.hits = 0
            self.calls = 0
            self.inner = None

        def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
            key = hasher(system, user)
            got = store.get(key)
            if got is not None:
                self.hits += 1
                return got["text"]
            if self.inner is None:
                self.inner = get_llm(None)
            text = self.inner.complete(system=system, user=user, temperature=temperature, max_tokens=max_tokens,
                                       json_mode=json_mode)
            self.calls += 1
            store[key] = {"model": getattr(self.inner, "name", "llm"), "text": text}
            C.write_json(path, store)                 # 한 콜마다 — 예산에서 끊겨도 받은 응답은 남는다
            return text

    return Refresher()


def _replay_f08(B, run, sd, graph, claims, triage, track, ctx, llm=None):
    from chuckchuck import build_questions

    store = C.read_json(run.dir / f"questions_llm_t{track}.json") or {}
    if not store and llm is None:
        return None, "얼린 질문 응답 없음"
    llm = llm or make_replay_only(store, B.h)
    kw = dict(track=track, alignment=None, flow=None, transcript=None, slidedoc=sd, context=ctx, claims=claims, llm=llm)
    try:
        doc = build_questions(graph, triage, **kw)
    except TypeError:
        kw.pop("claims")
        doc = build_questions(graph, triage, **kw)
    except ReplayMiss:
        return None, "프롬프트 바뀜"
    if getattr(llm, "misses", 0):
        return None, "프롬프트 바뀜"
    return doc.to_dict(), ""


def question_rows(qs: list[dict], sd: dict, cached: dict[str, dict], question_flags, is_fallback, M) -> list[dict]:
    raw = TG_raw(sd)
    lines = [x for _, x in T.deck_lines(sd)]
    texts = [t for t in raw.values() if t]
    deck = "\n".join(lines)
    rows = []
    for q in qs:
        gist = q.get("answer_gist", "")
        wrapped = gist.startswith("자료는 이렇게 말해요")
        flags = M._drop_expected_numbers(question_flags(q, None, texts), q, len(raw))
        quote, no = q.get("evidence_quote", ""), int(q.get("evidence_slide_no") or 0)
        inv = TG.inverted_against(gist, lines) if not q.get("trap") else None
        old = cached.get(q.get("id", "")) or {}
        rows.append({
            "id": q.get("id"), "question": q.get("question", ""), "gist": gist, "trap": bool(q.get("trap")),
            "inverted": inv, "ungrounded": (not wrapped and len(T.tokens(gist)) >= 4 and T.coverage(gist, deck) < TG.GIST_GROUNDED_MIN),
            "trap_uncorrected": bool(q.get("trap")) and not _PREMISE_RE.search(gist),
            "bad_flags": [f for f in flags if "!" in f], "hapsyo": any(f.startswith("합쇼체") for f in flags),
            "undercut": RG.self_contradicting(q.get("question", "")), "fallback": bool(is_fallback(q)),
            "hint_fragment": bool(quote) and TG.fragment_start(quote, raw),
            "hint_verbatim": (M.verbatim(quote, raw.get(no, "")) if quote else None), "quote": quote,
            "changed": bool(old) and (old.get("question") != q.get("question") or old.get("answer_gist") != gist),
        })
    return rows


def TG_raw(sd: dict) -> dict[int, str]:
    return T.slide_texts(sd)


def _ex(rows: list[dict], key: str, fmt) -> list[str]:
    return [fmt(r) for r in rows if r.get(key)][:5]


def f08_metrics(rows: list[dict], done: int, total: int, misses: list[str]) -> dict[str, dict]:
    n = len(rows)
    traps = [r for r in rows if r["trap"]]
    quoted = [r for r in rows if r["hint_verbatim"] is not None]
    out = {
        "replay.f08.coverage": S.ratio(done, total, [f"프롬프트 바뀜: {m}" for m in misses]),
        "replay.f08.changed": S.ratio(sum(r["changed"] for r in rows), n),
        "replay.f08.gist_inverted": S.ratio(sum(bool(r["inverted"]) for r in rows), n,
                                            _ex(rows, "inverted", lambda r: f"{r['id']}: «{r['gist'][:80]}» ↔ 자료 «{r['inverted'][0][:60]}»")),
        "replay.f08.gist_ungrounded": S.ratio(sum(r["ungrounded"] for r in rows), n,
                                              _ex(rows, "ungrounded", lambda r: f"{r['id']}: «{r['gist'][:100]}»")),
        "replay.f08.trap_uncorrected": S.ratio(sum(r["trap_uncorrected"] for r in traps), len(traps),
                                               _ex(traps, "trap_uncorrected", lambda r: f"{r['id']}: «{r['gist'][:100]}»")),
        "replay.f08.bad_flags": S.ratio(sum(bool(r["bad_flags"]) for r in rows), n,
                                        _ex(rows, "bad_flags", lambda r: f"{r['id']}: {r['bad_flags']} «{r['question'][:80]}»")),
        "replay.f08.hapsyo": S.ratio(sum(r["hapsyo"] for r in rows), n, _ex(rows, "hapsyo", lambda r: f"{r['id']}: «{r['gist'][:80]}»")),
        "replay.f08.undercut": S.ratio(sum(bool(r["undercut"]) for r in rows), n,
                                       _ex(rows, "undercut", lambda r: f"{r['id']}: «{r['question'][:100]}»")),
        "replay.f08.fallback": S.ratio(sum(r["fallback"] for r in rows), n, _ex(rows, "fallback", lambda r: f"{r['id']}: «{r['question'][:80]}»")),
        "replay.f08.hint_fragment": S.ratio(sum(r["hint_fragment"] for r in rows), n,
                                            _ex(rows, "hint_fragment", lambda r: f"{r['id']}: «{r['quote'][:80]}»")),
        "replay.f08.hint_verbatim": S.ratio(sum(bool(r["hint_verbatim"]) for r in quoted), len(quoted),
                                            [f"{r['id']}: «{r['quote'][:80]}»" for r in quoted if not r["hint_verbatim"]][:5]),
    }
    return out


def bench_metrics(results: list[dict]) -> dict[str, dict]:
    """벤치 collect 결과 → 대상 코드가 다시 계산한 것(탐침·힌트 사다리·발판)만."""
    truthy = [r for r in results if not r.get("incomplete") and "planted" in (r.get("probes") or {})]
    hit = sum(r["probes"]["planted_hit"] for r in truthy)
    planted = sum(r["probes"]["planted"] for r in truthy)
    tp = sum(r["probes"]["plantable_tp"] for r in truthy)
    plantable = sum(r["probes"]["plantable_probes"] for r in truthy)
    fps = [f"{r['name']}: {x}" for r in truthy for x in r["probes"].get("negative_fp") or []]
    hrows = [h for r in results if not r.get("incomplete") for h in (r.get("hints") or {}).values()]
    n_q = sum(h["n"] for h in hrows)
    locate = sum(h["locate_first"] * h["n"] for h in hrows)
    scaf = [c for h in hrows for c in h.get("scaffold") or []]
    two = [c for c in scaf if c["n"] == 2]
    return {
        "replay.probes.recall": S.ratio(hit, planted, [f"{r['name']}: 놓침 {[k for k, v in r['probes']['recall_by_id'].items() if not v]}"
                                                       for r in truthy if r["probes"]["planted_hit"] < r["probes"]["planted"]]),
        "replay.probes.precision": S.ratio(tp, plantable),
        "replay.probes.negative_fp": S.metric(len(fps), len(truthy), fps),
        "replay.hints.locate_first": S.ratio(round(locate), n_q),
        "replay.scaffold.two_choices": S.ratio(len(two), len(scaf)),
        "replay.scaffold.noun": S.ratio(sum(c["noun"] for c in two), len(two), [f"{c['q']}: {c['choices']}" for c in two if not c["noun"]]),
        "replay.scaffold.in_deck": S.ratio(sum(c["in_deck"] for c in two), len(two),
                                           [f"{c['q']}: {c['choices']}" for c in two if not c["in_deck"]]),
    }


def reason_metrics(RM, cache: Path, names: list[str], tracks: tuple[str, ...]) -> tuple[dict[str, dict], list[str]]:
    from chuckchuck.contracts import ConceptGraph, SlideDoc
    from chuckchuck.f09_judge import _deck_text

    truths = RM.load_truths()
    valid = total = 0
    bad, errors, planted = [], [], []
    for name in names:
        d = cache / name
        try:
            sd = C.read_json(d / "slide_doc.json")
            graph = C.read_json(d / "graph.json")
            sdoc = SlideDoc.from_dict(sd)
            raw = {s.slide_no: s.raw_text for s in sdoc.slides}
            deck_text = _deck_text(sdoc)
            g = ConceptGraph.from_dict(graph)
            lines = [ln for t in raw.values() for ln in (t or "").split("\n") if ln.strip()]
            for t in tracks:
                qs = (C.read_json(d / f"questions_t{t}.json") or {}).get("questions") or []
                for q in qs:
                    if q.get("trap"):
                        continue
                    row = RM.choice_row(q, g, deck_text, lines)
                    if row["valid"] is None:
                        continue
                    total += 1
                    valid += 1 if row["valid"] else 0
                    if not row["valid"]:
                        bad.append(f"{name}/{q['id']}: {row['choices']} (정답 「{row['answer']}」)")
            tr = (truths.get(name) or {}).get("reason")
            if tr:
                claims = C.read_json(d / "claims.json")
                planted.append(RM.planted_row(name, sd, graph, claims, tr))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {type(e).__name__}: {str(e)[:120]}")
    out = {"replay.reason.choice_valid": S.ratio(valid, total, bad)}
    if planted:
        for key, field in (("strongest", "strongest_cited"), ("bg_dropped", "background_numbers_dropped"), ("pair_ok", "choice_pair_ok")):
            out[f"replay.reason.planted_{key}"] = S.ratio(sum(bool(p[field]) for p in planted), len(planted),
                                                          [f"{p['deck']}: «{p['gist_out'][:90]}» 보기 {p['choices']}" for p in planted if not p[field]])
    return out, errors


def run(cache: Path, decks: list[str] | None, tracks: tuple[str, ...]) -> dict:
    B, M, RM, is_fallback, question_flags = _bench()
    B.OUT = cache                              # 벤치 모듈이 캐시를 이 자리에서 읽게 (전역 이름을 호출 때 찾는다)
    specs = B.load_decks(C.MAIN_CHECKOUT, set())
    names = [d.name for d in sorted(cache.iterdir()) if d.is_dir() and not d.name.startswith("_")
             and (d / "questions_t5.json").exists() and (d / "slide_doc.json").exists()]
    if decks:
        names = [n for n in names if n in decks]
    errors: list[str] = []
    rows_all: list[dict] = []
    done = total = 0
    misses: list[str] = []
    results = []
    for name in names:
        spec = specs.get(name) or {"name": name, "group": "heldout", "synthetic": False, "truth": None,
                                   "context": {"situation": "school_project", "duration_min": 5}, "pptx": None,
                                   "slidedoc_path": None, "transcript_path": None}
        spec = dict(spec, pptx=None)
        run_ = B.DeckRun(spec, None)
        d = cache / name
        sd, graph, claims, triage = (C.read_json(d / f) for f in ("slide_doc.json", "graph.json", "claims.json", "triage.json"))
        try:
            results.append(B.collect(run_, list(tracks)))
        except Exception as e:  # noqa: BLE001
            errors.append(f"collect {name}: {type(e).__name__}: {str(e)[:120]}")
        if not (sd and graph and triage):
            continue
        for t in tracks:
            cached_doc = C.read_json(d / f"questions_t{t}.json")
            if not cached_doc:
                continue
            total += 1
            try:
                doc, why = _replay_f08(B, run_, sd, graph, claims, triage, t, spec.get("context") or {})
            except Exception as e:  # noqa: BLE001
                errors.append(f"f08 {name} t{t}: {type(e).__name__}: {str(e)[:120]}")
                continue
            if doc is None:
                misses.append(f"{name} t{t} ({why})")
                continue
            done += 1
            cached = {q["id"]: q for q in cached_doc.get("questions") or []}
            for r in question_rows(doc.get("questions") or [], sd, cached, question_flags, is_fallback, M):
                rows_all.append(dict(r, id=f"{name}/t{t}/{r['id']}"))
    metrics = f08_metrics(rows_all, done, total, misses)
    metrics.update(bench_metrics(results))
    rm, rerr = reason_metrics(RM, cache, names, tracks)
    metrics.update(rm)
    errors += rerr
    metrics["replay.errors"] = S.metric(len(errors), None, errors)
    return {"metrics": metrics, "decks": names, "f08_rows": rows_all[:400]}


def refresh(cache: Path, decks: list[str] | None, tracks: tuple[str, ...]) -> dict:
    """
    얼린 F-08 질문 응답을 **지금 프롬프트로** 다시 굽는다 (실 LLM — 부모가 `llm_guard.install("count", …, budget)` 로 센다).

    quick 의 결정적 재생은 프롬프트 해시가 같을 때만 얼린 응답을 쓴다 — F-08 프롬프트가 바뀌면 `replay.f08.coverage` 가 떨어진다
    (09-30 WP-Q 뒤 46% → 0%). 재생과 **똑같은 호출**(같은 캐시 입력 · 같은 트랙 · 같은 상황)로 build_questions 를 돌려, 없는 해시만
    실제 제공자에게 묻고 같은 파일(`questions_llm_t{트랙}.json`)에 더한다 — 옛 응답은 지우지 않는다(옛 코드를 재는 대상도 있다).
    덱 캐시의 그래프·주장·1차 심사는 그대로 쓴다 — 새로 굽는 것은 질문 LLM 응답뿐이라 덱·트랙마다 1콜(재시도면 2콜)이다.
    """
    B, *_ = _bench()
    B.OUT = cache
    specs = B.load_decks(C.MAIN_CHECKOUT, set())
    names = [d.name for d in sorted(cache.iterdir()) if d.is_dir() and not d.name.startswith("_")
             and (d / "questions_t5.json").exists() and (d / "slide_doc.json").exists()]
    if decks:
        names = [n for n in names if n in decks]
    rows, errors = [], []
    for name in names:
        spec = specs.get(name) or {"name": name, "group": "heldout", "synthetic": False, "truth": None,
                                   "context": {"situation": "school_project", "duration_min": 5}, "pptx": None,
                                   "slidedoc_path": None, "transcript_path": None}
        run_ = B.DeckRun(dict(spec, pptx=None), None)
        d = cache / name
        sd, graph, claims, triage = (C.read_json(d / f) for f in ("slide_doc.json", "graph.json", "claims.json", "triage.json"))
        if not (sd and graph and triage):
            continue
        for t in tracks:
            if not (d / f"questions_t{t}.json").exists():
                continue
            path = d / f"questions_llm_t{t}.json"
            llm = make_refresher(C.read_json(path) or {}, B.h, path)
            try:
                doc, why = _replay_f08(B, run_, sd, graph, claims, triage, t, spec.get("context") or {}, llm=llm)
            except Exception as e:  # noqa: BLE001 — 한 덱이 죽어도(예산 포함) 나머지는 본다
                errors.append(f"{name} t{t}: {type(e).__name__}: {str(e)[:160]}")
                if type(e).__name__ == "BudgetExceeded":
                    break
                continue
            rows.append({"deck": name, "track": t, "hits": llm.hits, "calls": llm.calls,
                         "questions": len((doc or {}).get("questions") or []), "why": why})
        if errors and errors[-1].split(": ")[1:2] == ["BudgetExceeded"]:
            break
    return {"rows": rows, "errors": errors, "calls": sum(r["calls"] for r in rows)}
