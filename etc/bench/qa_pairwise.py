"""
Q&A 질문 묶음 **둘을 나란히** 놓고 심사관이 어느 쪽이 나은지 고른다 — rubric(1~5 절대 점수)이 천장(4.8~5.0)에 붙어
모델 차이를 못 가를 때 쓴다 (2026-10-16 모델 나눠 맡기기 벤치).

    python etc/bench/qa_pairwise.py --run /data/models/_runs/qa-route/bench/<실행> --base solar/solar \\
        --bundle-dir /data/models/_runs/qa-route/bundles

- 같은 번들 · 같은 회차(r1·r2)의 묶음끼리만 비교한다 (기준 조합 vs 도전 조합).
- 자리 편향을 없애려고 **A·B 자리를 바꿔 두 번** 묻는다. 두 번 다 같은 쪽을 고르면 승, 갈리면 무승부.
- 심사관은 solar 고정 (model_bench 와 같다). 실 LLM 을 부른다.
- 결과: <실행>/pairwise.json · 표는 stdout.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path[:0] = [str(ROOT / "main"), str(ROOT / "etc"), str(ROOT), str(Path(__file__).resolve().parent)]

from pipeline.config import load_dotenv  # noqa: E402

load_dotenv()

from pipeline._json_text import extract_json_object  # noqa: E402
from pipeline.contracts import SlideDoc, Transcript  # noqa: E402
from pipeline.providers.llm_impl import get_llm  # noqa: E402

from qa_eval import Corpus, RUBRIC_SLIDE_MAX, RUBRIC_SPEECH_MAX, load_artifacts  # noqa: E402

SYSTEM = """당신은 발표 Q&A 코치 심사관이다. 같은 발표에 대해 만든 예상 질문 묶음 A 와 B 를 비교한다.
기준(중요한 순서): ① 자료·발화에 근거했는가(자료에 없는 사실을 전제하지 않는다) ② 이 발표의 핵심 주장·약점을 찌르는가
③ 이유·비교·한계를 묻는 깊이 ④ 자료 고유의 용어·수치를 짚는 구체성 ⑤ 발표자가 실제로 답할 수 있고 말이 자연스러운가(해요체).
trap=true 질문은 일부러 틀린 전제를 넣은 함정이다 — 전제가 틀린 것을 벌하지 않는다.
길이나 개수가 아니라 질이다. 비슷하면 tie.
코드펜스 없이 JSON 하나만, winner 를 **먼저** 쓴다: {"winner": "A" | "B" | "tie", "reason": "한 문장(100자 이내), 장 번호(S3 처럼)를 댄다"}"""


def _deck_block(corpus: Corpus) -> str:
    lines = ["## 자료 (장별 본문)"]
    lines += [f"S{no}: {t[:RUBRIC_SLIDE_MAX]}" for no, t in corpus.slide_text.items() if t.strip()]
    lines += ["", "## 발화 (장별 받아쓰기)"]
    lines += [f"S{no}: {t[:RUBRIC_SPEECH_MAX]}" for no, t in corpus.speech_text.items() if t.strip()]
    return "\n".join(lines)


def _qs_block(name: str, qs: list[dict]) -> str:
    return "\n".join([f"## 묶음 {name}"] + [f"- trap={'true' if q['trap'] else 'false'}: {q['question']}" for q in qs])


def ask(llm, deck: str, a: list[dict], b: list[dict]) -> str:
    user = "[TASK] qa-pairwise\n\n" + deck + "\n\n" + _qs_block("A", a) + "\n\n" + _qs_block("B", b)
    raw = llm.complete(system=SYSTEM, user=user, temperature=0.0, max_tokens=1200, json_mode=True)
    try:
        w = str(extract_json_object(raw).get("winner", "tie")).strip().upper()
    except ValueError:
        # 이유가 길어 잘려도 winner 는 앞에 있다 (10-16 실측: 이유를 끝없이 늘어놓아 JSON 이 잘렸다)
        m = re.search(r'"winner"\s*:\s*"(A|B|tie)"', raw or "", re.I)
        if not m:
            return "error"
        w = m.group(1).upper()
    return w if w in ("A", "B") else "tie"


def _results(run: Path, cfg: str) -> dict[tuple[str, str], dict]:
    slug = cfg.replace("/", "-")
    out = {}
    for p in run.glob(f"*_{slug}-r*_*.json"):
        if p.name.endswith((".raw.json", ".corpus.json")):
            continue
        rest = p.name.split(f"_{slug}-", 1)[1][:-5]          # r1_booth_A1_battery
        rep, bundle = rest.split("_", 1)
        out[(rep, bundle)] = json.loads(p.read_text(encoding="utf-8"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--bundle-dir", type=Path, required=True)
    ap.add_argument("--base", default="solar/solar")
    ap.add_argument("--challengers", default="ax/ax,exaone/exaone,solar/ax,solar/exaone")
    ap.add_argument("--judge", default="solar")
    args = ap.parse_args()

    llm = get_llm(args.judge)
    base = _results(args.run, args.base)
    rng = random.Random(16)
    table, detail = [], []
    for cfg in [c.strip() for c in args.challengers.split(",") if c.strip()]:
        ch = _results(args.run, cfg)
        win = lose = tie = err = 0
        for key in sorted(set(base) & set(ch)):
            art = load_artifacts(args.bundle_dir / f"{key[1]}.json")
            corpus = Corpus(SlideDoc.from_dict(art["slide_doc"]),
                            Transcript.from_dict(art["transcript"]) if art.get("transcript") else None)
            deck = _deck_block(corpus)
            b_qs, c_qs = base[key]["questions"], ch[key]["questions"]
            first_challenger_a = rng.random() < 0.5
            votes = []
            for challenger_is_a in (first_challenger_a, not first_challenger_a):
                a, b = (c_qs, b_qs) if challenger_is_a else (b_qs, c_qs)
                w = ask(llm, deck, a, b)
                votes.append("err" if w == "error" else "tie" if w == "tie" else
                             ("ch" if (w == "A") == challenger_is_a else "base"))
            if "err" in votes:
                err += 1
                outcome = "error"
            elif votes[0] == votes[1] and votes[0] != "tie":
                outcome = votes[0]
                win += outcome == "ch"
                lose += outcome == "base"
            else:
                tie += 1
                outcome = "tie"
            detail.append({"challenger": cfg, "rep": key[0], "bundle": key[1], "votes": votes, "outcome": outcome})
            print(f"  {cfg:<14} {key[0]} {key[1]:<24} {votes} → {outcome}", flush=True)
        table.append({"challenger": cfg, "vs": args.base, "n": win + lose + tie + err, "win": win, "lose": lose, "tie": tie, "error": err})
    (args.run / "pairwise.json").write_text(json.dumps({"table": table, "detail": detail}, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    print(f"\n| 도전 조합 | 기준 | n | 승 | 패 | 무 | 오류 |\n|---|---|---|---|---|---|---|")
    for r in table:
        print(f"| {r['challenger']} | {r['vs']} | {r['n']} | {r['win']} | {r['lose']} | {r['tie']} | {r['error']} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
