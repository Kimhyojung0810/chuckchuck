"""
QA **일반화 벤치** (`labs/qa_bench`) — 수면 덱 하나가 아니라 여러 덱에서 Q&A 파이프라인이 무엇을 내는지 잰다.

    자료(SlideDoc 또는 .pptx→f01 파싱) → F-06 개념 → F-07 그래프 → F-26 주장 → 탐침 → F-08 1차 심사 → 질문(5·10분)
      → 힌트 사다리 → F-09 판정(표본)          + 녹음 경로(F-11 대조·흐름 → 1차 심사 → 질문) · 안정성(1차 심사를 새로 3번)

실 LLM 을 부른다 (.env, 과금). mock 은 쓰지 않는다 (CLAUDE.md §2). 호출은 `--budget` 에서 끊고 `out/calls.jsonl` 에 전부 남긴다.

    .venv/bin/python labs/qa_bench/run.py all                        # 전 단계 (캐시가 있으면 건너뛴다)
    .venv/bin/python labs/qa_bench/run.py all --decks ir_banchan,sleep --track 5
    .venv/bin/python labs/qa_bench/run.py base      # 자료→질문까지만      · judge · stability · recording · report
    .venv/bin/python labs/qa_bench/run.py report    # LLM 없이 캐시에서 지표만 다시 (코드 바꾼 뒤 결정적 단계는 다시 돈다)
    .venv/bin/python labs/qa_bench/run.py all --fresh questions      # 이 단계부터 캐시 무시

캐시: `out/<deck>/` 에 단계 산출물과 `keys.json`. 단계 키 = 앞 단계 산출물 해시 + 그 단계 모듈 소스 해시. 그래서
f08 을 고치면 1차 심사·질문만, f26 을 고치면 주장부터 다시 돈다. 개념·그래프는 f06·f07 을 안 고치면 그대로 쓴다.
`--repo-root` 는 실제 덱(수면·수익률격차 등)을 찾을 주 체크아웃 (기본 /home/yehschuck/project/chuckchuck).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from chuckchuck.config import load_dotenv  # noqa: E402

load_dotenv()

import metrics as M  # noqa: E402
from chuckchuck.providers.llm_base import LLMProvider  # noqa: E402

OUT = HERE / "out"
CORPUS = HERE / "corpus"
#: 표를 쓸 곳 — 루프마다 따로 남기려면 QA_BENCH_REPORT_DIR 로 바꾼다 (qa/loop2 는 loop2/ 에 쓴다; P5 표를 덮지 않게).
REPORT_DIR = Path(os.environ.get("QA_BENCH_REPORT_DIR") or ROOT / "docs" / "review" / "2026-09-29_QA_근거검증" / "bench")
DEFAULT_REPO = Path(os.environ.get("QA_BENCH_REPO_ROOT", "/home/yehschuck/project/chuckchuck"))

#: 라이브 경로(.pptx → f01)로 태울 합성 덱. deck.pptx 가 있어야 한다.
LIVE_DEFAULT = ("ir_banchan", "policy_jeonse", "hum_novel", "health_glucose", "lib_reopen")
#: 안정성(1차 심사를 새로 3번) — 탐침이 가장 많은 합성 덱 하나 + 원래 사례
STABILITY_DEFAULT = ("health_glucose", "sleep")
#: 녹음 경로 — 합성 녹음(핵심 장을 6초에 넘김) + 실제 녹음
RECORDING_DEFAULT = ("health_glucose", "sleep")

#: 단계 → 그 단계 산출물을 바꾸는 모듈 (소스 해시가 캐시 키에 들어간다)
STAGE_MODULES = {
    "slides": ["chuckchuck/f01_parse.py"],
    "concepts": ["chuckchuck/f06_concepts.py"],
    "graph": ["chuckchuck/f07_graph.py", "chuckchuck/_graph_items.py", "chuckchuck/_claim_rules.py", "chuckchuck/_match.py"],
    "claims": ["chuckchuck/f26_claims.py", "chuckchuck/_claim_quote.py", "chuckchuck/_claim_rules.py", "chuckchuck/_evidence.py", "chuckchuck/_match.py"],
    "triage": ["chuckchuck/f08_questions.py", "chuckchuck/_probes.py", "chuckchuck/_claim_rules.py", "chuckchuck/_match.py"],
    "questions": ["chuckchuck/f08_questions.py", "chuckchuck/_probes.py", "chuckchuck/_claim_rules.py", "chuckchuck/_grounding.py", "chuckchuck/_probe_stance.py",
                  "chuckchuck/_evidence.py", "chuckchuck/_traps.py", "chuckchuck/_speech.py", "chuckchuck/_match.py"],
    "align": ["chuckchuck/f11_align.py", "chuckchuck/f11_flow.py"],
    "judge": ["chuckchuck/f09_judge.py", "chuckchuck/f08_questions.py", "chuckchuck/_traps.py", "chuckchuck/_deck_claims.py", "chuckchuck/_probe_stance.py"],
}
STAGE_ORDER = ["slides", "concepts", "graph", "claims", "triage", "questions", "judge", "stability", "recording"]


# ---------------------------------------------------------------------------
# LLM 호출 세기 · 예산
# ---------------------------------------------------------------------------

class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    def total_logged(self) -> int:
        p = OUT / "calls.jsonl"
        return sum(1 for _ in p.open(encoding="utf-8")) if p.exists() else 0


BUDGET = Budget(150)


class Counted(LLMProvider):
    """모든 호출을 세고 남기는 겉감. 예산을 넘으면 부르기 전에 끊는다."""

    def __init__(self, inner: LLMProvider, deck: str, stage: str):
        self.inner, self.deck, self.stage = inner, deck, stage
        self.name = getattr(inner, "name", "unknown")

    def complete(self, *, system: str, user: str, temperature: float = 0.2, max_tokens: int = 4096,
                 json_mode: bool = False) -> str:
        if BUDGET.used >= BUDGET.limit:
            raise BudgetExceeded(f"LLM 예산 {BUDGET.limit} 을 다 썼어요 ({self.deck}/{self.stage})")
        BUDGET.used += 1
        t0 = time.time()
        err = ""
        try:
            return self.inner.complete(system=system, user=user, temperature=temperature, max_tokens=max_tokens,
                                       json_mode=json_mode)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:120]}"
            raise
        finally:
            OUT.mkdir(parents=True, exist_ok=True)
            with (OUT / "calls.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "deck": self.deck, "stage": self.stage,
                                    "model": self.name, "sec": round(time.time() - t0, 1), "chars_in": len(system) + len(user),
                                    "err": err}, ensure_ascii=False) + "\n")


def engine(deck: str, stage: str) -> Counted:
    from chuckchuck.providers.llm_impl import get_llm

    return Counted(get_llm(None), deck, stage)


class Replay(LLMProvider):
    """
    응답을 (system, user) 해시로 얼려 두는 겉감 — 같은 프롬프트면 LLM 을 다시 부르지 않고 얼린 응답을 준다.

    F-26 은 LLM 후보를 코드가 대조·받침 검사로 거른다. 대조 규칙만 고쳤을 때 프롬프트는 그대로라, 주장 단계를
    새로 돌려도 LLM 을 다시 부를 까닭이 없다 (예산 150콜 안에서 규칙을 여러 번 고쳐 잰다). 프롬프트가 바뀌면
    해시가 달라져 새로 부른다.
    """

    def __init__(self, deck: str, stage: str, path: Path):
        self.deck, self.stage, self.path = deck, stage, path
        self.name = ""
        self.inner: Counted | None = None

    def _engine(self) -> Counted:
        if self.inner is None:
            self.inner = engine(self.deck, self.stage)
        return self.inner

    def complete(self, *, system: str, user: str, temperature: float = 0.2, max_tokens: int = 4096,
                 json_mode: bool = False) -> str:
        store = read_json(self.path) or {}
        key = h(system, user)
        got = store.get(key)
        if got is not None:
            self.name = got.get("model", "replay")
            return got["text"]
        eng = self._engine()
        text = eng.complete(system=system, user=user, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
        self.name = eng.name
        store[key] = {"model": eng.name, "text": text}
        write_json(self.path, store)
        return text


# ---------------------------------------------------------------------------
# 파일·해시
# ---------------------------------------------------------------------------

def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def h(*parts) -> str:
    m = hashlib.sha256()
    for x in parts:
        m.update((x if isinstance(x, (bytes, bytearray)) else json.dumps(x, ensure_ascii=False, sort_keys=True).encode()))
        m.update(b"\0")
    return m.hexdigest()[:16]


def src_hash(stage: str) -> str:
    return h(*[(ROOT / p).read_bytes() for p in STAGE_MODULES.get(stage, [])])


def note(msg: str) -> None:
    print(msg, flush=True)


def log_stage(deck: str, stage: str, t0: float, calls0: int, **extra) -> None:
    """실제로 돈 단계(캐시 아님)의 벽시계 시간과 그 단계의 LLM 호출 수 → out/timing.jsonl (실시간 경로 지연표의 원본)."""
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "timing.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "deck": deck, "stage": stage,
                            "sec": round(time.time() - t0, 2), "calls": BUDGET.used - calls0, **extra},
                           ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 덱 목록
# ---------------------------------------------------------------------------

def load_decks(repo_root: Path, live: set[str]) -> dict[str, dict]:
    decks: dict[str, dict] = {}
    for d in sorted(p for p in CORPUS.iterdir() if p.is_dir() and (p / "slidedoc.json").exists()):
        truth = read_json(d / "truth.json") or {}
        pptx = d / "deck.pptx"
        decks[d.name] = {
            "name": d.name, "group": truth.get("group") or "heldout", "synthetic": True, "truth": truth,
            "context": truth.get("context") or {"situation": "school_project", "duration_min": 5},
            "slidedoc_path": d / "slidedoc.json", "pptx": pptx if (pptx.exists() and d.name in live) else None,
            "transcript_path": d / "transcript.json" if (d / "transcript.json").exists() else None,
        }
    manifest = read_json(CORPUS / "real_decks.json") or {}
    for r in manifest.get("decks") or []:
        def resolve(spec: str | None) -> Path | None:
            if not spec:
                return None
            base, _, rel = spec.partition(":")
            return (repo_root if base == "repo" else ROOT) / rel
        decks[r["name"]] = {
            "name": r["name"], "group": r["group"], "synthetic": False, "truth": r.get("truth"),
            "context": r.get("context") or {}, "slidedoc_path": resolve(r["slidedoc"]), "pptx": None,
            "transcript_path": resolve(r.get("transcript")), "note": r.get("note", ""),
        }
    return decks


# ---------------------------------------------------------------------------
# 단계 캐시
# ---------------------------------------------------------------------------

class DeckRun:
    def __init__(self, spec: dict, fresh_from: str | None):
        self.spec = spec
        self.name = spec["name"]
        self.dir = OUT / self.name
        self.keys = read_json(self.dir / "keys.json") or {}
        self.fresh_idx = STAGE_ORDER.index(fresh_from) if fresh_from in STAGE_ORDER else 99

    def cached(self, stage: str, fname: str, key: str):
        if STAGE_ORDER.index(stage.split(":")[0]) >= self.fresh_idx:
            return None
        if self.keys.get(stage) == key and (self.dir / fname).exists():
            return read_json(self.dir / fname)
        return None

    def save(self, stage: str, fname: str, key: str, data) -> None:
        write_json(self.dir / fname, data)
        self.keys[stage] = key
        write_json(self.dir / "keys.json", self.keys)

    def out_hash(self, fname: str) -> str:
        return h(read_json(self.dir / fname))


def stage_slides(run: DeckRun) -> dict:
    spec = run.spec
    if spec["pptx"] is not None:
        key = h("live", spec["pptx"].read_bytes(), src_hash("slides"))
        got = run.cached("slides", "slide_doc.json", key)
        if got is not None:
            return got
        from chuckchuck.f01_parse import parse_document

        t0, c0 = time.time(), BUDGET.used
        sd = parse_document(spec["pptx"]).to_dict()
        log_stage(run.name, "slides", t0, c0, upstage=1)
        with (OUT / "parse_calls.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "deck": run.name, "sec": round(time.time() - t0, 1)}) + "\n")
        note(f"  [{run.name}] f01 파싱(Upstage) {time.time() - t0:.1f}s · {len(sd.get('slides') or [])}장 (라이브)")
        run.save("slides", "slide_doc.json", key, sd)
        return sd
    src = spec["slidedoc_path"]
    if src is None or not src.exists():
        got = read_json(run.dir / "slide_doc.json")   # 보관소가 지워졌으면 얼려 둔 것을 쓴다
        if got is None:
            raise FileNotFoundError(f"{run.name}: slidedoc 이 없어요 ({src})")
        return got
    from chuckchuck.contracts import SlideDoc

    sd = SlideDoc.from_dict(read_json(src)).to_dict()
    key = h("json", sd)
    if run.keys.get("slides") != key:
        run.save("slides", "slide_doc.json", key, sd)
    return sd


def stage_concepts(run: DeckRun, sd: dict) -> dict:
    key = h(run.out_hash("slide_doc.json"), run.spec["context"], src_hash("concepts"))
    got = run.cached("concepts", "concept_doc.json", key)
    if got is not None:
        return got
    from chuckchuck import extract_concepts
    from chuckchuck.contracts import Context, SlideDoc

    t0, c0 = time.time(), BUDGET.used
    cd = extract_concepts(SlideDoc.from_dict(sd), Context.from_dict(run.spec["context"]), llm=engine(run.name, "concepts"))
    log_stage(run.name, "concepts", t0, c0)
    note(f"  [{run.name}] F-06 개념 {time.time() - t0:.1f}s")
    run.save("concepts", "concept_doc.json", key, cd.to_dict())
    return cd.to_dict()


def stage_graph(run: DeckRun, sd: dict, cd: dict) -> dict:
    key = h(run.out_hash("concept_doc.json"), run.out_hash("slide_doc.json"), run.spec["context"], src_hash("graph"))
    got = run.cached("graph", "graph.json", key)
    if got is not None:
        return got
    from chuckchuck import build_graph
    from chuckchuck.contracts import ConceptDoc, Context, SlideDoc

    t0, c0 = time.time(), BUDGET.used
    g = build_graph(ConceptDoc.from_dict(cd), Context.from_dict(run.spec["context"]), slide_doc=SlideDoc.from_dict(sd),
                    llm=engine(run.name, "graph"))
    log_stage(run.name, "graph", t0, c0)
    note(f"  [{run.name}] F-07 그래프 {time.time() - t0:.1f}s · 노드 {len(g.nodes)}")
    run.save("graph", "graph.json", key, g.to_dict())
    return g.to_dict()


def stage_claims(run: DeckRun, sd: dict, graph: dict) -> dict:
    key = h(run.out_hash("graph.json"), run.out_hash("slide_doc.json"), src_hash("claims"))
    got = run.cached("claims", "claims.json", key)
    if got is not None:
        return got
    from chuckchuck.f26_claims import build_claims

    t0, c0 = time.time(), BUDGET.used
    c = build_claims(graph, sd, llm=Replay(run.name, "claims", run.dir / "claims_llm.json"))
    log_stage(run.name, "claims", t0, c0)
    note(f"  [{run.name}] F-26 주장 {time.time() - t0:.1f}s · {len(c.claims)}개 (버림 {c.dropped}) model={c.model}")
    run.save("claims", "claims.json", key, c.to_dict())
    return c.to_dict()


def stage_triage(run: DeckRun, graph: dict, claims: dict, tag: str = "triage", fname: str = "triage.json",
                 *, alignment=None, flow=None, transcript=None, force: bool = False) -> dict:
    extra = [alignment, flow, transcript] if alignment is not None else []
    key = h(run.out_hash("graph.json"), run.out_hash("claims.json"), run.spec["context"], src_hash("triage"), *extra, tag)
    if not force and STAGE_ORDER.index("triage") < run.fresh_idx and run.keys.get(tag) == key and (run.dir / fname).exists():
        return read_json(run.dir / fname)
    from chuckchuck import triage_questions

    t0, c0 = time.time(), BUDGET.used
    t = triage_questions(graph, alignment, flow, run.spec["context"], transcript=transcript, claims=claims,
                         llm=engine(run.name, tag))
    log_stage(run.name, tag, t0, c0)
    note(f"  [{run.name}] F-08 1차 심사({tag}) {time.time() - t0:.1f}s · 후보 {len(t.marks)} · 탐침 {len(t.probes)}")
    run.save(tag, fname, key, t.to_dict())
    return t.to_dict()


def stage_questions(run: DeckRun, sd: dict, graph: dict, claims: dict, triage: dict, track: str,
                    tag: str = "questions", fname: str | None = None, *, alignment=None, flow=None,
                    transcript=None, triage_fname: str = "triage.json") -> dict:
    fname = fname or f"questions_t{track}.json"
    key = h(run.out_hash(triage_fname), run.out_hash("slide_doc.json"), run.out_hash("claims.json"), track,
            src_hash("questions"), alignment, flow, transcript)
    stage_key = f"{tag}:t{track}"
    if STAGE_ORDER.index("questions") < run.fresh_idx and run.keys.get(stage_key) == key and (run.dir / fname).exists():
        return read_json(run.dir / fname)
    from chuckchuck import build_questions

    t0, c0 = time.time(), BUDGET.used
    # 질문 LLM 응답도 얼린다(Replay) — 코드 쪽 후처리(골자·함정 규칙)만 고쳤으면 프롬프트가 같아 다시 부르지 않는다 (qa/loop2).
    doc = build_questions(graph, triage, track=track, alignment=alignment, flow=flow, transcript=transcript,
                          slidedoc=sd, context=run.spec["context"], claims=claims,
                          llm=Replay(run.name, f"{tag}{track}", run.dir / f"{tag}_llm_t{track}.json"))
    log_stage(run.name, f"{tag}{track}", t0, c0)
    t1 = time.time()
    ladders_of(doc.to_dict())
    log_stage(run.name, f"ladders{track}", t1, BUDGET.used)
    note(f"  [{run.name}] F-08 질문 t{track}({tag}) {time.time() - t0:.1f}s · {len(doc.questions)}개")
    run.save(stage_key, fname, key, doc.to_dict())
    return doc.to_dict()


def ladders_of(qdoc: dict) -> dict[str, list[str]]:
    from chuckchuck.f08_questions import build_hint_ladder

    return {q["id"]: build_hint_ladder(q) for q in qdoc.get("questions") or []}


# ---------------------------------------------------------------------------
# 판정 — 표본 2문항 × 답 5종 (예산 때문에 두 문항에 나눠 넣는다)
# ---------------------------------------------------------------------------

#: 문항 A(탐침 질문이 있으면 그것): 골자 그대로 · 그럴듯한 오답 · 모르겠어요 / 문항 B: 바꿔 말한 좋은 답 · 무관한 답 · 그럴듯한 오답
JUDGE_PLAN = {"A": ("gist", "wrong", "dunno"), "B": ("paraphrase", "offtopic", "wrong")}
#: qa/loop2 (09-29): 탐침 질문이면 A 에 「따져 묻는 자료 줄을 되풀이한 답」(restate, LLM 없이 만든다)을 넣는다 — P5 에서 판정이
#: 탐침 질문을 거꾸로 채점했다(단정에 동의한 답 good 85). 예산 때문에 탐침 A 는 모르겠어요 대신 restate·offtopic, B 는 바꿔 말한 답만.
JUDGE_PLAN_PROBE = {"A": ("gist", "restate", "offtopic", "wrong"), "B": ("paraphrase",)}


def restate_answer(q: dict) -> str:
    """탐침 근거 줄을 그대로 받아들인 답 — 「자료에 그렇게 나와 있어요」. 통과하면 판정이 탐침을 거꾸로 채점한 것이다."""
    ev = ((q.get("basis") or {}).get("probe") or {}).get("evidence") or []
    quote = (ev[0].get("quote") or "").strip().rstrip(".") if ev else ""
    return f"{quote}. 자료에 그렇게 나와 있어요." if quote else ""
OFFTOPIC = ("저희 팀은 지난 분기에 물류 창고 세 곳의 재고 회전율을 비교했고, "
            "동절기 배송 지연이 반품률을 끌어올린다는 결론을 얻었어요.")

ANSWER_SYSTEM = """너는 발표 Q&A 연습용 답안을 쓰는 조교다. 질문마다 두 가지 답을 만든다.
- paraphrase: 기대 답(골자)과 **뜻은 같지만 낱말·순서를 바꿔** 발표자가 말하듯 쓴 좋은 답. 골자에 없는 사실을 보태지 마라.
- wrong: 자료와 **어긋나는** 그럴듯한 오답. 질문 주제에 맞는 말투로, 골자의 핵심 관계를 뒤집거나 틀린 원인을 댄다. 무관한 이야기는 안 된다.
둘 다 해요체 1~2문장, 80자 안팎. 반드시 완전한 JSON 객체만 출력하라.
{"items": [{"key": "<받은 key 그대로>", "paraphrase": "...", "wrong": "..."}]}"""


def pick_sample(qdoc: dict) -> list[tuple[str, dict]]:
    qs = qdoc.get("questions") or []
    if not qs:
        return []
    a = next((q for q in qs if (q.get("basis") or {}).get("probe")), qs[0])
    b = next((q for q in qs if q is not a), None)
    return [("A", a)] + ([("B", b)] if b else [])


def gen_answers(samples: dict[str, list[tuple[str, dict]]], force: bool) -> dict[str, dict]:
    """답안(바꿔 말한 좋은 답·그럴듯한 오답)을 **한 번의 호출로** 모든 덱의 표본에 대해 만든다. 캐시: out/answers.json."""
    cache = {} if force else (read_json(OUT / "answers.json") or {})
    todo = []
    for deck, pairs in samples.items():
        for slot, q in pairs:
            key = f"{deck}|{q['id']}|{h(q['question'], q.get('answer_gist', ''))}"
            if key not in cache:
                todo.append((key, q))
    if todo:
        from chuckchuck._json_text import extract_json_object

        user = "\n\n".join(f"key: {k}\n질문: {q['question']}\n골자: {q.get('answer_gist', '')}" for k, q in todo)
        raw = engine("*", "answers").complete(system=ANSWER_SYSTEM, user=user, temperature=0.4, max_tokens=4000, json_mode=True)
        data = extract_json_object(raw)
        for it in data.get("items") or []:
            if isinstance(it, dict) and it.get("key"):
                cache[str(it["key"])] = {"paraphrase": str(it.get("paraphrase", "")), "wrong": str(it.get("wrong", ""))}
        write_json(OUT / "answers.json", cache)
        note(f"  답안 생성 {len(todo)}문항 → {sum(1 for k, _ in todo if k in cache)} 받음")
    return cache


def stage_judge(run: DeckRun, sd: dict, graph: dict, qdoc: dict, answers: dict[str, dict]) -> list[dict]:
    from chuckchuck import judge_answer

    fname = "judge.json"
    key = h(run.out_hash("questions_t5.json"), src_hash("judge"), answers)
    if STAGE_ORDER.index("judge") < run.fresh_idx and run.keys.get("judge") == key and (run.dir / fname).exists():
        return read_json(run.dir / fname)
    records = []
    sample = pick_sample(qdoc)
    plan = JUDGE_PLAN_PROBE if sample and (sample[0][1].get("basis") or {}).get("probe") else JUDGE_PLAN
    for slot, q in sample:
        ans = answers.get(f"{run.name}|{q['id']}|{h(q['question'], q.get('answer_gist', ''))}") or {}
        for kind in plan[slot]:
            text = {"gist": q.get("answer_gist", ""), "offtopic": OFFTOPIC, "dunno": "모르겠어요",
                    "restate": restate_answer(q),
                    "paraphrase": ans.get("paraphrase", ""), "wrong": ans.get("wrong", "")}[kind]
            if not text:
                continue
            t0, c0 = time.time(), BUDGET.used
            try:
                j = judge_answer(q, text, graph=graph, context=run.spec["context"], slidedoc=sd,
                                 give_up=(kind == "dunno"), llm=engine(run.name, f"judge:{kind}")).to_dict()
            except BudgetExceeded:
                # 예산에서 끊겨도 이미 받은 판정은 남긴다 (키는 안 적어 다음 실행이 다시 돈다) — P5 에서 4건을 잃었다
                write_json(run.dir / "judge_partial.json", records)
                raise
            log_stage(run.name, f"judge:{kind}", t0, c0)
            row = M.judge_row(kind, j)
            row.update(q=q["id"], question=q["question"], probe=((q.get("basis") or {}).get("probe") or {}).get("kind", ""),
                       answer=text, sec=round(time.time() - t0, 1))
            records.append(row)
            note(f"  [{run.name}] 판정 {q['id'][:18]} {kind:10s} → {row['verdict']} {row['score']} ({row['outcome']}, 기대 {row['expect']}) {'✓' if row['ok'] else '✗'}")
    run.save("judge", fname, key, records)
    return records


# ---------------------------------------------------------------------------
# 녹음 경로 · 안정성
# ---------------------------------------------------------------------------

def stage_recording(run: DeckRun, sd: dict, graph: dict, claims: dict) -> dict | None:
    tp = run.spec.get("transcript_path")
    if not tp or not Path(tp).exists():
        return None
    transcript = read_json(Path(tp))
    key = h(run.out_hash("graph.json"), transcript, src_hash("align"))
    alignment = read_json(run.dir / "alignment.json") if run.keys.get("align") == key and STAGE_ORDER.index("recording") < run.fresh_idx else None
    if alignment is None:
        from chuckchuck.f11_align import align_speech

        t0 = time.time()
        alignment = align_speech(graph, transcript, run.spec["context"], llm=engine(run.name, "align")).to_dict()
        note(f"  [{run.name}] F-11 대조 {time.time() - t0:.1f}s")
        run.save("align", "alignment.json", key, alignment)
    from chuckchuck.f11_flow import build_flow_diff

    flow = build_flow_diff(graph, alignment).to_dict()
    write_json(run.dir / "flow.json", flow)
    tri = stage_triage(run, graph, claims, tag="triage_rec", fname="triage_rec.json",
                       alignment=alignment, flow=flow, transcript=transcript)
    return stage_questions(run, sd, graph, claims, tri, "5", tag="rec", fname="questions_rec_t5.json",
                           alignment=alignment, flow=flow, transcript=transcript, triage_fname="triage_rec.json")


def stage_stability(run: DeckRun, sd: dict, graph: dict, claims: dict, base_q5: dict, n: int = 3) -> list[dict]:
    """1차 심사를 새로 돌려 질문 5분 트랙을 n 번 — 첫 번째는 기본 실행(questions_t5)을 그대로 쓴다."""
    runs = [base_q5]
    for i in range(2, n + 1):
        fq = f"stability/q5_run{i}.json"
        key = h(run.out_hash("graph.json"), run.out_hash("claims.json"), src_hash("triage"), src_hash("questions"), i)
        if run.keys.get(f"stab{i}") == key and (run.dir / fq).exists() and STAGE_ORDER.index("stability") < run.fresh_idx:
            runs.append(read_json(run.dir / fq))
            continue
        from chuckchuck import build_questions, triage_questions

        t = triage_questions(graph, None, None, run.spec["context"], claims=claims, llm=engine(run.name, f"stab_triage{i}"))
        write_json(run.dir / f"stability/triage_run{i}.json", t.to_dict())
        doc = build_questions(graph, t, track="5", slidedoc=sd, context=run.spec["context"], claims=claims,
                              llm=engine(run.name, f"stab_q{i}")).to_dict()
        run.save(f"stab{i}", fq, key, doc)
        runs.append(doc)
        note(f"  [{run.name}] 안정성 {i}번째 · 질문 {len(doc['questions'])}")
    return runs


# ---------------------------------------------------------------------------
# 지표 모으기
# ---------------------------------------------------------------------------

def parse_fidelity(run: DeckRun, sd: dict) -> dict | None:
    """라이브 덱: 파싱 결과 줄이 저작한 SlideDoc 줄을 얼마나 그대로 담는가 (식 조각·표·설문 보기)."""
    if run.spec["pptx"] is None:
        return None
    authored = M.slide_raw(read_json(run.spec["slidedoc_path"]))
    parsed = M.slide_raw(sd)
    lines = [(no, ln) for no, t in authored.items() for ln in t.split("\n") if ln.strip()]
    missing = [(no, ln) for no, ln in lines if not M.verbatim(ln, parsed.get(no, ""))]
    return {"slides_authored": len(authored), "slides_parsed": len(parsed), "lines": len(lines),
            "lines_kept": len(lines) - len(missing), "missing": [f"S{no} «{ln}»" for no, ln in missing[:12]]}


def deck_text(sd: dict) -> str:
    from chuckchuck.contracts import SlideDoc
    from chuckchuck.f09_judge import _deck_text

    return _deck_text(SlideDoc.from_dict(sd))


def scaffold_choices(qd: dict, sd: dict, graph: dict) -> list[dict]:
    """발판 단계(LLM 없음)의 빈칸 선택지 둘 — 모든 질문에 대해 지금 코드로 다시 만든다."""
    from chuckchuck.contracts import ConceptGraph, Question
    from chuckchuck.f09_judge import _scaffold_judgement

    deck = deck_text(sd)
    g = ConceptGraph.from_dict(graph)
    out = []
    for q in qd.get("questions") or []:
        j = _scaffold_judgement(Question.from_dict(q), g, deck)
        out.append(dict(M.choice_quality(list(j.choices) if j else [], deck, q.get("evidence_quote", "")),
                        q=q["id"], followup=j.followup if j else ""))
    return out


def collect(run: DeckRun, tracks: list[str]) -> dict:
    d = run.dir
    sd, graph, claims = read_json(d / "slide_doc.json"), read_json(d / "graph.json"), read_json(d / "claims.json")
    triage = read_json(d / "triage.json")
    if not (sd and graph and claims and triage):
        return {"name": run.name, "incomplete": True}
    truth = run.spec.get("truth")
    from chuckchuck.contracts import ClaimDoc, ConceptGraph
    from chuckchuck._probes import derive_probes

    # 탐침은 결정적이다 — 캐시된 triage 가 아니라 **지금 코드**로 다시 찾는다 (규칙을 고친 뒤 LLM 없이 다시 잰다)
    probes = [p.to_dict() for p in derive_probes(ConceptGraph.from_dict(graph), ClaimDoc.from_dict(claims))]
    out = {"name": run.name, "group": run.spec["group"], "synthetic": run.spec["synthetic"],
           "live": run.spec["pptx"] is not None, "slides": len(sd.get("slides") or []),
           "nodes": len(graph.get("nodes") or []), "note": run.spec.get("note", ""),
           "parse": parse_fidelity(run, sd),
           "claims": M.claim_metrics(claims, sd, truth), "probes": M.probe_metrics(probes, graph, truth),
           "probes_cached_triage": len(triage.get("probes") or []), "questions": {}, "hints": {}}
    for t in tracks:
        qd = read_json(d / f"questions_t{t}.json")
        if qd:
            out["questions"][t] = M.question_metrics(qd, graph, sd, truth)
            out["hints"][t] = M.hint_metrics(qd, sd, truth, ladders_of(qd))
            out["hints"][t]["scaffold"] = scaffold_choices(qd, sd, graph)
    j = read_json(d / "judge.json")
    if j:
        out["judge"] = M.judge_metrics(j)
        out["judge_rows"] = j
        deck = deck_text(sd)
        q5 = {q["id"]: q for q in (read_json(d / "questions_t5.json") or {}).get("questions") or []}
        out["dunno_choices"] = [dict(M.choice_quality(r.get("choices") or [], deck, q5.get(r["q"], {}).get("evidence_quote", "")),
                                     q=r["q"], followup=r.get("followup", ""))
                                for r in j if r["kind"] == "dunno"]
    tr = (read_json(OUT / "traps_run.json") or {}).get(run.name)
    if tr:
        out["traps"] = tr
    rec = read_json(d / "questions_rec_t5.json")
    if rec:
        rm = M.question_metrics(rec, graph, sd, truth)
        under = (truth or {}).get("under_spoken_slides") or []
        rm["under_spoken_asked"] = [r["label"] for r in rm["rows"]
                                   if r["source"] in ("under_spoken", "missing") and set(r["slide_nos"]) & set(under or r["slide_nos"])]
        out["recording"] = rm
    stab = [read_json(d / "questions_t5.json")] + [read_json(p) for p in sorted((d / "stability").glob("q5_run*.json"))]
    stab = [s for s in stab if s]
    if len(stab) >= 2:
        out["stability"] = M.stability_metrics(stab, graph)
    return out


# ---------------------------------------------------------------------------
# 명령
# ---------------------------------------------------------------------------

def run_base(runs: list[DeckRun], tracks: list[str]) -> None:
    for run in runs:
        note(f"\n== {run.name} ({run.spec['group']}{', 라이브' if run.spec['pptx'] else ''})")
        try:
            sd = stage_slides(run)
            cd = stage_concepts(run, sd)
            graph = stage_graph(run, sd, cd)
            claims = stage_claims(run, sd, graph)
            triage = stage_triage(run, graph, claims)
            for t in tracks:
                stage_questions(run, sd, graph, claims, triage, t)
        except BudgetExceeded as e:
            note(f"  예산: {e}")
            raise
        except Exception as e:  # noqa: BLE001 — 한 덱이 죽어도 나머지는 돈다
            note(f"  ✗ {run.name}: {type(e).__name__}: {e}")


def run_judge(runs: list[DeckRun], force: bool) -> None:
    samples = {}
    for run in runs:
        q5 = read_json(run.dir / "questions_t5.json")
        if q5:
            samples[run.name] = pick_sample(q5)
    answers = gen_answers(samples, force)
    for run in runs:
        q5 = read_json(run.dir / "questions_t5.json")
        if not q5:
            continue
        try:
            stage_judge(run, read_json(run.dir / "slide_doc.json"), read_json(run.dir / "graph.json"), q5, answers)
        except BudgetExceeded:
            raise
        except Exception as e:  # noqa: BLE001
            note(f"  ✗ 판정 {run.name}: {type(e).__name__}: {e}")


def cmd(ns: argparse.Namespace) -> int:
    BUDGET.limit = ns.budget
    decks = load_decks(Path(ns.repo_root), set(ns.live.split(",")) if ns.live else set())
    names = list(decks) if ns.decks in ("all", "") else [x.strip() for x in ns.decks.split(",")]
    unknown = [n for n in names if n not in decks]
    if unknown:
        raise SystemExit(f"모르는 덱: {unknown} · 있는 덱: {list(decks)}")
    runs = [DeckRun(decks[n], ns.fresh) for n in names]
    tracks = [t.strip() for t in ns.track.split(",")]
    note(f"덱 {len(runs)}개 · 트랙 {tracks} · 예산 {BUDGET.limit} (지금까지 남긴 호출 {BUDGET.total_logged()})")
    try:
        if ns.cmd in ("all", "base"):
            run_base(runs, tracks)
        if ns.cmd in ("all", "recording"):
            for run in runs:
                if run.name in ns.recording.split(","):
                    d = run.dir
                    stage_recording(run, read_json(d / "slide_doc.json"), read_json(d / "graph.json"), read_json(d / "claims.json"))
        if ns.cmd in ("all", "stability"):
            for run in runs:
                if run.name in ns.stability.split(","):
                    d = run.dir
                    stage_stability(run, read_json(d / "slide_doc.json"), read_json(d / "graph.json"),
                                    read_json(d / "claims.json"), read_json(d / "questions_t5.json"))
        if ns.cmd in ("all", "judge"):
            run_judge(runs, ns.fresh == "judge")
    except BudgetExceeded as e:
        note(f"\n예산에서 멈췄어요: {e}")
    results = [collect(r, tracks) for r in runs]
    write_json(OUT / "results.json", results)
    import report as R

    R.write(results, REPORT_DIR, calls=BUDGET.total_logged())
    note(f"\n이번 실행 LLM 호출 {BUDGET.used} · 누적 {BUDGET.total_logged()} · 결과 {(OUT / 'results.json').relative_to(ROOT)}"
         f" · 표 {(REPORT_DIR / 'metrics.md').relative_to(ROOT)}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="labs/qa_bench/run.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("all", "base", "judge", "stability", "recording", "report"))
    ap.add_argument("--decks", default="all", help="쉼표로. 기본 all")
    ap.add_argument("--track", default="5,10")
    ap.add_argument("--repo-root", default=str(DEFAULT_REPO))
    ap.add_argument("--budget", type=int, default=150, help="이번 실행의 LLM 호출 상한")
    ap.add_argument("--fresh", default=None, choices=STAGE_ORDER, help="이 단계부터 캐시 무시")
    ap.add_argument("--live", default=",".join(LIVE_DEFAULT), help="pptx→f01 로 태울 합성 덱 (빈 문자열이면 전부 JSON)")
    ap.add_argument("--stability", default=",".join(STABILITY_DEFAULT))
    ap.add_argument("--recording", default=",".join(RECORDING_DEFAULT))
    return cmd(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
