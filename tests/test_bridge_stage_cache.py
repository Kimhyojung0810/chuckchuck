"""
단계 캐시 키의 코드 판 (09-30 감사 B-02 · G-A4/A5/A34).

두 가지를 못 박는다.
1. **닫힘** — 단계 진입 모듈이 import 하는(함수 안의 지연 import 포함) chuckchuck 모듈은 전부 그 단계 키에 들어간다.
   브리지의 계산(ast)과 따로, 이 파일은 ① 소스를 정규식으로 훑고 ② 가짜 LLM 으로 실제로 돌려 **실행된 파일**을 모아
   둘 다 키의 부분집합인지 본다. 손으로 적은 목록(예전 F-26 키 = f26 하나)이면 여기서 걸린다.
2. **돌고 있는 코드** — 키는 브리지가 뜰 때 읽은 소스로 센다. 요청 때 디스크를 읽으면, 도는 중에 다른 세션이 파일을
   고쳤을 때 새 소스의 키 자리를 옛 코드의 결과가 채운다 (이 VM 에서 8799 가 도는 동안 실제로 일어나는 일).
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import pytest

import chuckchuck
import demo.bridge as bridge
from chuckchuck.contracts import ConceptDoc, ConceptGraph, Context, SlideDoc

PKG = Path(chuckchuck.__file__).resolve().parent
ROOT = PKG.parent
LIVE = ROOT / "fixtures" / "live_qa_run.json"


def module_of(path: Path) -> str:
    parts = path.resolve().relative_to(ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def file_of(module: str) -> Path:
    base = ROOT.joinpath(*module.split("."))
    return base / "__init__.py" if (base / "__init__.py").is_file() else base.with_suffix(".py")


# 브리지의 ast 걷기와 **다른 방법**으로 센다 — 줄 단위 정규식. 들여쓴 줄(함수 안 import)도 잡는다.
FROM_RE = re.compile(r"^\s*from\s+(\.*)([\w.]*)\s+import\s+\(?([^#\n]*)", re.M)
IMPORT_RE = re.compile(r"^\s*import\s+(chuckchuck[\w.]*)", re.M)


def regex_imports(module: str) -> set[str]:
    src = file_of(module).read_text(encoding="utf-8")
    src = re.sub(r'(?s)""".*?"""', "", src)          # 독스트링 속 예시 import 는 코드가 아니다
    is_pkg = file_of(module).name == "__init__.py"
    pkg = module if is_pkg else module.rpartition(".")[0]
    out: set[str] = set()
    for dots, mod, names in FROM_RE.findall(src):
        if dots:
            base = pkg.split(".")[: len(pkg.split(".")) - (len(dots) - 1)]
            target = ".".join([*base, mod] if mod else base)
        else:
            target = mod
        if not target.startswith("chuckchuck"):
            continue
        for name in re.findall(r"[A-Za-z_]\w*", names.split(" as ")[0] if not mod else names):
            if file_of(f"{target}.{name}").is_file():
                out.add(f"{target}.{name}")
        if file_of(target).is_file() and not (not mod and dots):
            out.add(target)
    out.update(m for m in IMPORT_RE.findall(src) if file_of(m).is_file())
    return out


def regex_closure(entries) -> set[str]:
    seen: set[str] = set()
    stack = list(entries)
    while stack:
        m = stack.pop()
        if m in seen:
            continue
        seen.add(m)
        stack.extend(regex_imports(m) - seen)
    return seen


@pytest.mark.parametrize("stage", sorted(bridge.STAGE_ENTRY_MODULES))
def test_단계_키는_진입_모듈이_import_하는_모듈을_전부_담는다(stage):
    walked = regex_closure(bridge.STAGE_ENTRY_MODULES[stage])
    missing = walked - bridge.STAGE_MODULES[stage]
    assert not missing, f"{stage} 키에 빠진 모듈: {sorted(missing)}"
    # 예전에 빠졌던 것들이 실제로 들어 있는지 (감사 G-A4/A5)
    if stage == "claims":
        assert {"chuckchuck._claim_rules", "chuckchuck._claim_quote", "chuckchuck._evidence",
                "chuckchuck._match"} <= bridge.STAGE_MODULES["claims"]
    if stage == "graph":
        assert {"chuckchuck._graph_items", "chuckchuck._claim_rules", "chuckchuck._match"} <= bridge.STAGE_MODULES["graph"]
    if stage == "triage":
        assert {"chuckchuck._grounding", "chuckchuck._probes", "chuckchuck._probe_stance", "chuckchuck._traps",
                "chuckchuck._reason", "chuckchuck._evidence", "chuckchuck._speech"} <= bridge.STAGE_MODULES["triage"]


def test_함수_안의_지연_import_도_닫힘에_든다():
    # f09 는 _deck_claims 를 위에서도 부르지만, _probe_stance 는 함수 안에서 `from ._deck_claims import clauses` 를 한다
    src = file_of("chuckchuck._probe_stance").read_text(encoding="utf-8")
    assert re.search(r"^\s+from \._deck_claims import clauses", src, re.M), "전제: 지연 import 가 있어야 이 검사가 의미 있다"
    assert "chuckchuck._deck_claims" in bridge.STAGE_MODULES["triage"]


@pytest.fixture(scope="module")
def live() -> dict:
    if not LIVE.is_file():
        pytest.skip(f"fixture 없음: {LIVE}")
    return json.loads(LIVE.read_text(encoding="utf-8"))["session"]["artifacts"]


def executed_modules(fn) -> set[str]:
    """fn 을 돌리며 **실제로 불린** chuckchuck 파일들 (sys.setprofile)."""
    seen: set[str] = set()
    root = str(PKG)

    def prof(frame, event, arg):
        if event == "call" and frame.f_code.co_filename.startswith(root):
            seen.add(frame.f_code.co_filename)

    sys.setprofile(prof)
    try:
        fn()
    finally:
        sys.setprofile(None)
    return {module_of(Path(f)) for f in seen}


def test_가짜_LLM_으로_돌려서_실행된_모듈이_전부_키에_있다(live):
    ctx = Context.from_dict({"situation": "school_project", "duration_min": 5})
    runs = {
        "concepts": lambda: chuckchuck.extract_concepts(SlideDoc.from_dict(live["slide_doc"]), ctx, llm="mock"),
        "graph": lambda: chuckchuck.build_graph(ConceptDoc.from_dict(live["concept_doc"]), ctx,
                                                slide_doc=SlideDoc.from_dict(live["slide_doc"]), llm="mock"),
        "claims": lambda: chuckchuck.build_claims(live["concept_graph"], live["slide_doc"], llm="mock"),
        "papers": lambda: chuckchuck.build_papers(live["concept_graph"], live["slide_doc"], scholar="none"),
        "triage": lambda: chuckchuck.triage_questions(live["concept_graph"], live["alignment_doc"], live["flow_diff"],
                                                      ctx, llm="mock"),
        "questions": lambda: chuckchuck.build_questions(live["concept_graph"], live["qa_triage"], track="10",
                                                        slidedoc=live["slide_doc"], context=ctx, llm="mock"),
        "judge": lambda: chuckchuck.judge_answer(live["question_doc"]["questions"][0], "핵심은 정렬이에요",
                                                 graph=live["concept_graph"], slidedoc=live["slide_doc"], llm="mock"),
    }
    for stage, run in runs.items():
        ran = executed_modules(run)
        assert ran, stage
        assert ran <= bridge.STAGE_MODULES[stage], f"{stage}: 실행됐는데 키에 없는 모듈 {sorted(ran - bridge.STAGE_MODULES[stage])}"
    # 예전 F-26 키(f26 하나)였다면 여기서 걸렸다 — 대조 규칙이 실제로 돈다
    assert len(executed_modules(runs["claims"])) > 1


def test_브리지가_부르는_진입_함수는_단계_진입_모듈에_있다():
    entry = {
        "concepts": bridge.extract_concepts, "graph": bridge.build_graph, "claims": chuckchuck.build_claims,
        "papers": chuckchuck.build_papers, "memory": chuckchuck.build_memory, "triage": chuckchuck.triage_questions,
        "questions": chuckchuck.build_questions, "judge": chuckchuck.judge_answer,
    }
    for stage, fn in entry.items():
        assert fn.__module__ in bridge.STAGE_ENTRY_MODULES[stage], (stage, fn.__module__)


# ─── 키는 돌고 있는 코드의 판 ──────────────────────────────────────────────────

def test_코드_판은_요청_때_디스크를_읽지_않는다(monkeypatch):
    before = {s: bridge._stage_version(s) for s in bridge.STAGE_ENTRY_MODULES}
    bridge._DRIFT_STATE["checked_at"] = time.monotonic()          # 사람용 경고 훑기는 이번엔 쉰다

    def no_disk(self, *a, **k):
        raise AssertionError(f"요청 중에 소스를 읽었다: {self}")

    monkeypatch.setattr(Path, "read_bytes", no_disk)
    monkeypatch.setattr(Path, "read_text", no_disk)
    assert {s: bridge._stage_version(s) for s in bridge.STAGE_ENTRY_MODULES} == before


def test_도는_중에_소스가_바뀌면_알리되_키는_옛_코드_판_그대로(monkeypatch, capsys):
    stage_before = bridge._stage_version("graph")
    monkeypatch.setattr(bridge, "SOURCE_HASHES", {**bridge.SOURCE_HASHES, "chuckchuck._match": "000000000000"})
    monkeypatch.setitem(bridge._DRIFT_STATE, "checked_at", 0.0)
    monkeypatch.setitem(bridge._DRIFT_STATE, "warned", set())

    assert bridge._stage_version("graph") == stage_before
    err = capsys.readouterr().err
    assert "chuckchuck._match 소스가 브리지를 띄운 뒤 바뀌었어요" in err


def test_시작_때_읽은_소스로_판을_세고_나중의_수정은_새로_읽을_때만_보인다(tmp_path):
    pkg = tmp_path / "toy"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "entry.py").write_text("from . import helper\n\ndef run():\n    from .lazy import x\n    return x\n",
                                  encoding="utf-8")
    (pkg / "helper.py").write_text("A = 1\n", encoding="utf-8")
    (pkg / "lazy.py").write_text("x = 1\n", encoding="utf-8")
    (pkg / "other.py").write_text("B = 2\n", encoding="utf-8")

    snap = bridge._snapshot_sources(pkg)
    closure = bridge._import_closure(("toy.entry",), snap)
    assert closure == {"toy.entry", "toy.helper", "toy.lazy"}        # 함수 안의 지연 import 도, 안 쓰는 other 는 빼고
    hashes = {k: h for k, (h, _, _) in snap.items()}
    v0 = bridge._version_of(closure, hashes)

    (pkg / "lazy.py").write_text("x = 2  # 도는 중에 누가 고쳤다\n", encoding="utf-8")
    assert bridge._version_of(closure, hashes) == v0                 # 시작 때 판은 그대로
    fresh = {k: h for k, (h, _, _) in bridge._snapshot_sources(pkg).items()}
    assert bridge._version_of(closure, fresh) != v0                  # 다시 띄우면 새 판
    (pkg / "other.py").write_text("B = 3\n", encoding="utf-8")
    fresh2 = {k: h for k, (h, _, _) in bridge._snapshot_sources(pkg).items()}
    assert bridge._version_of(closure, fresh2) == bridge._version_of(closure, fresh)   # 닫힘 밖은 판을 안 바꾼다


# ─── 단계 캐시가 도우미 모듈 수정을 알아본다 ────────────────────────────────────

class _Graph:
    nodes, edges, sections = [], [], []

    def to_dict(self):
        return {"file_name": "a.pdf", "total_slides": 1, "nodes": [], "edges": []}


def test_그래프_캐시는_match_를_고친_다음_판에서_안_맞는다(tmp_path, monkeypatch):
    """예전 F-07 키(f07·_graph_items·_claim_rules)는 _match 를 몰랐다 — 고쳐도 옛 그래프가 나왔다."""
    import io
    from email.message import Message

    calls: list[int] = []
    monkeypatch.setattr(bridge, "build_graph", lambda *a, **k: calls.append(1) or _Graph())
    monkeypatch.setattr(bridge, "STAGE_CACHE_ON", True)
    monkeypatch.setattr(bridge, "STAGE_CACHE_DIR", tmp_path / "stage")
    monkeypatch.setattr(bridge.Handler, "_archive", staticmethod(lambda *a: None))

    class H(bridge.Handler):
        def __init__(self):  # noqa: D107
            self.headers, self.sent, self.wfile = Message(), [], io.BytesIO()

        def _json(self, code, payload):
            self.sent.append(code)

    concept_doc = ConceptDoc(file_name="a.pdf", total_slides=1).to_dict()
    raw = json.dumps({"concept_doc": concept_doc}).encode()
    H()._handle_graph(raw)
    H()._handle_graph(raw)
    assert len(calls) == 1                                           # 같은 판 → 캐시

    bumped = {**bridge.SOURCE_HASHES, "chuckchuck._match": "fffffffffff0"}   # 다음에 띄울 때 _match 가 바뀌었다
    monkeypatch.setitem(bridge.STAGE_VERSIONS, "graph", bridge._version_of(bridge.STAGE_MODULES["graph"], bumped))
    H()._handle_graph(raw)
    assert len(calls) == 2


def test_LLM_백엔드를_바꿔_띄우면_키가_달라진다(monkeypatch):
    monkeypatch.setenv("REASONING_BACKEND", "solar")
    monkeypatch.setenv("REASONING_FALLBACK", "ax")
    solar = bridge._llm_identity(None)
    monkeypatch.setenv("REASONING_BACKEND", "midm")
    assert bridge._llm_identity(None) != solar and bridge._llm_identity("exaone") == "exaone"


def test_단계_캐시_쓰기는_반쪽_파일을_남기지_않는다(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "STAGE_CACHE_ON", True)
    monkeypatch.setattr(bridge, "STAGE_CACHE_DIR", tmp_path / "stage")
    bridge._stage_cache_put("graph", "k1", {"nodes": [1]})
    assert bridge._stage_cache_get("graph", "k1") == {"nodes": [1]}
    assert [p.name for p in (tmp_path / "stage").iterdir()] == ["graph-k1.json"]


def test_ConceptGraph_계약이_키에_든다():
    # 출력 모양(to_dict)을 정하는 contracts 도 코드 판이다 — 새 필드가 생기면 옛 캐시는 그 필드가 없다
    assert ConceptGraph.__module__ == "chuckchuck.contracts"
    assert all("chuckchuck.contracts" in mods for mods in bridge.STAGE_MODULES.values())
