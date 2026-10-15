"""
팀 덱(자료 파싱본 + 받아쓰기)을 `qa_eval.py` 가 읽는 번들로 만든다 — 모델 비교의 **고정 입력**.

    python etc/bench/build_deck_bundle.py --out /data/models/_runs/qa-route/bundles \\
        --deck A1=var/data/sessions/2026/10/05/20261005T140201Z_7631969f
    python etc/bench/build_deck_bundle.py --booth --out DIR       # 부스 덱 셋(A-1·B-1·C-1)을 세션 보관소에서 찾아 만든다

왜 — 모델끼리 질문(F-08)을 비교하려면 그 앞 단계(F-06 개념 · F-07 그래프 · F-26 주장 · F-11 대조 · 흐름)는
**모두 같은 입력**이어야 한다. 그래서 앞 단계는 한 번만, 늘 같은 백엔드(기본 solar — 서비스 기본값)로 만들어 번들에 얼린다.
번들은 자료 본문이 들어 있으므로 **git 에 넣지 않는다** (출력은 /data 아래 등 저장소 밖).

번들 모양은 `etc/fixtures/live_qa_run.json` 과 같다 (session.artifacts) + `claims`(F-26, 서비스 브리지가 F-08 에 넘기는 것).
실 LLM 을 부른다 (.env, 과금). 이미 있는 번들은 건너뛴다 (`--force` 로 다시).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path[:0] = [str(ROOT / "main"), str(ROOT / "etc"), str(ROOT)]

from pipeline.config import load_dotenv  # noqa: E402

load_dotenv()

#: 부스 덱 셋 — 세션 보관소 제목 → 번들 이름. 녹음이 있는 첫 버전(A-1·B-1·C-1)이다.
BOOTH_TITLES = {
    "A_급속충전_배터리열화": "booth_A1_battery",
    "B_미세플라스틱_물벼룩번식": "booth_B1_microplastic",
    "C_배달앱_별점인플레이션": "booth_C1_delivery",
}
DEFAULT_SESSIONS = Path("/home/yehschuck/project/chuckchuck/var/data/sessions")


def find_booth_sessions(base: Path) -> dict[str, Path]:
    """세션 보관소에서 부스 덱(자료+받아쓰기가 다 있는 가장 최근 세션)을 찾는다."""
    found: dict[str, tuple[float, Path]] = {}
    for man in base.rglob("manifest.json"):
        try:
            m = json.loads(man.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = BOOTH_TITLES.get(unicodedata.normalize("NFC", m.get("title") or ""))  # macOS 에서 온 이름은 NFD
        arts = m.get("artifacts") or {}
        if not name or "slide_doc" not in arts or "transcript" not in arts:
            continue
        ts = float(m.get("updated_at") or 0)
        if name not in found or ts > found[name][0]:
            found[name] = (ts, man.parent)
    return {k: v[1] for k, v in found.items()}


def build_bundle(session_dir: Path, llm_name: str) -> dict:
    from pipeline import build_graph, extract_concepts
    from pipeline.contracts import Context, SlideDoc, Transcript
    from pipeline.f11_align import align_speech
    from pipeline.f11_flow import build_flow_diff
    from pipeline.f26_claims import build_claims
    from pipeline.providers.llm_impl import get_llm

    if (session_dir / "manifest.json").exists():          # 세션 보관소 폴더
        man = json.loads((session_dir / "manifest.json").read_text(encoding="utf-8"))
        sd_raw = json.loads((session_dir / "slide_doc.json").read_text(encoding="utf-8"))
    else:                                                  # etc/labs/qa_bench/corpus/<덱> (slidedoc.json · truth.json)
        truth = json.loads((session_dir / "truth.json").read_text(encoding="utf-8")) if (session_dir / "truth.json").exists() else {}
        man = {"title": session_dir.name, "context": truth.get("context") or {"situation": "school_project", "duration_min": 5}}
        sd_raw = json.loads((session_dir / "slidedoc.json").read_text(encoding="utf-8"))
    tr_path = session_dir / "transcript.json"
    tr_raw = json.loads(tr_path.read_text(encoding="utf-8")) if tr_path.exists() else None
    ctx = Context.from_dict(man.get("context") or {})
    slidedoc = SlideDoc.from_dict(sd_raw)
    transcript = Transcript.from_dict(tr_raw) if tr_raw else None
    llm = get_llm(llm_name)
    times = {}

    t0 = time.time()
    concepts = extract_concepts(slidedoc, ctx, transcript=transcript, llm=llm)
    times["concepts"] = round(time.time() - t0, 1)
    t0 = time.time()
    graph = build_graph(concepts, ctx, slide_doc=slidedoc, llm=llm)
    times["graph"] = round(time.time() - t0, 1)
    t0 = time.time()
    claims = build_claims(graph.to_dict(), sd_raw, llm=llm)
    times["claims"] = round(time.time() - t0, 1)
    alignment = flow = None
    if transcript is not None:
        t0 = time.time()
        alignment = align_speech(graph, transcript, ctx, llm=llm, slide_doc=sd_raw,
                                 speech_match=(tr_raw or {}).get("marks_match"))
        flow = build_flow_diff(graph, alignment)
        times["align"] = round(time.time() - t0, 1)
    arts = {
        "slide_doc": sd_raw,
        "concept_graph": graph.to_dict(),
        "claims": claims.to_dict(),
        "transcript": tr_raw,
        "alignment_doc": alignment.to_dict() if alignment else None,
        "flow_diff": flow.to_dict() if flow else None,
        "context": ctx.to_dict(),
    }
    return {"session": {"title": man.get("title"), "artifacts": arts},
            "built": {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "llm": llm.name, "sec": times,
                      "source_session": session_dir.name, "nodes": len(graph.nodes), "claims": len(claims.claims)}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True, help="번들 폴더 (저장소 밖 — 자료 본문이 든다)")
    ap.add_argument("--deck", action="append", default=[], help="이름=세션폴더 (여러 번)")
    ap.add_argument("--booth", action="store_true", help="부스 덱 셋(A-1·B-1·C-1)을 세션 보관소에서 찾는다")
    ap.add_argument("--sessions", type=Path, default=DEFAULT_SESSIONS)
    ap.add_argument("--llm", default="solar", help="앞 단계 백엔드 (기본 solar — 서비스 기본값, 모든 비교에 같은 입력)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    targets: dict[str, Path] = {}
    if args.booth:
        targets.update(find_booth_sessions(args.sessions))
    for spec in args.deck:
        name, _, path = spec.partition("=")
        targets[name] = Path(path)
    if not targets:
        raise SystemExit("만들 덱이 없어요 — --booth 또는 --deck 이름=세션폴더")
    args.out.mkdir(parents=True, exist_ok=True)
    for name, sdir in sorted(targets.items()):
        out = args.out / f"{name}.json"
        if out.exists() and not args.force:
            print(f"  {name}: 있음 (건너뜀) {out}")
            continue
        t0 = time.time()
        bundle = build_bundle(sdir, args.llm)
        out.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        b = bundle["built"]
        print(f"  {name}: {time.time() - t0:.0f}s 노드 {b['nodes']} 주장 {b['claims']} {b['sec']} → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
