"""
임베딩으로 「직접 계산하는 attention」 시험 — Solar 는 API 라 내부 attention 을 못 꺼내니, 파서·F-06 이 뽑은 항목을
Upstage 임베딩(embedding-passage)으로 벡터화해 항목 × 항목 유사도(행마다 softmax = attention 꼴)를 직접 만든다.

    .venv/bin/python labs/embed_attention/try_embed.py [CONCEPTS.json] [--top 5] [--temp 0.05]
    .venv/bin/python labs/embed_attention/try_embed.py --direction [--pair-min 0.6] [--votes 3]   # 후보 쌍 방향을 Solar 에게

    .venv/bin/python labs/embed_attention/try_embed.py --hierarchy [--votes 3]                    # 개념 목록 전체로 위계를 Solar 에게

    .venv/bin/python labs/embed_attention/try_embed.py --hybrid [GRAPH.json] [--votes 3]          # 자료 위계 고정 + 나머지만 Solar

--hybrid: 현재 그래프(층 그래프)에서 **자료가 명시한 개념 위계**(같은 장 목록 · 「X — …」 상세 장 · 제목 개념)는 고정하고, 핵심 주장 바로 밑에
떠 있는 개념만 Solar 에게 사전지식으로 부모를 고르게 한다(자기 자손은 못 고른다). 같은 개념 묶기는 임베딩 유사도 0.7 이상인 쌍만
「같은 대상을 가리키는가」 로 따로 묻는다. 둘 다 n 번 물어 다수결.

--hierarchy: Solar 에게 개념 목록 전체(이름 · 자료 설명 · 나온 장)를 주고 사전지식으로 위계를 짜게 한다 — 개념마다 상위 개념 id 하나(없으면 null)와
같은 개념 묶음. 이름은 목록의 id 로만 가리킨다(새 개념·새 이름 금지). n 번 물어 개념마다 상위 개념을 다수결, 실행 간 일치도도 낸다.

--direction: 임베딩은 「관련 있다」 만 안다(방향·포함을 모른다). 그래서 임베딩으로 **후보 쌍**만 고르고(서로 상위 k 안 · 유사도 문턱),
Solar 에게 쌍마다 관계를 묻는다 — same(같은 개념) · A>B(A 가 상위: B 는 A 의 부분·종류·지표·요소) · B>A · related(관련만) · none.
Solar 의 사전지식을 써도 된다고 명시한다 (노드 이름은 자료 것 그대로 — 새 이름은 받지 않는다). n 번 물어 다수결.

입력: F-06 결과(ConceptDoc JSON, 종류 있는 추출). 기본은 수익률격차.
출력: 개념마다 attention 상위 항목 · 상위 개념 후보(더 넓게 묶이는 개념 중 가장 가까운 것) · 중심성 순위.
임베딩은 out/cache.json 에 저장해 다시 돌릴 때 과금하지 않는다 (out/ 은 .gitignore).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import json
import math
import os
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT = ROOT / "docs/review/2026-10-02_개념그래프_재현성/graphs/concepts_수익률격차.json"
CACHE = HERE / "out" / "cache.json"
MODEL = os.environ.get("UPSTAGE_EMBED_MODEL", "embedding-passage")


def items_of(doc: dict) -> list[dict]:
    """노드가 될 항목 — 개념(이름: 설명) · 주장. 근거는 붙는 쪽이라 따로 둔다."""
    out = []
    for s in doc["slides"]:
        if s.get("title_kind") == "structural":
            continue
        for c in s.get("concepts", []):
            name, _, desc = c.partition(":")
            out.append({"kind": "concept", "slide": s["slide_no"], "label": name.strip(),
                        "text": f"{name.strip()}: {desc.strip()}" if desc.strip() else name.strip()})
        for c in s.get("claims", []):
            out.append({"kind": "claim", "slide": s["slide_no"], "label": c, "text": c})
    # 같은 이름의 개념은 하나로 (장 번호를 모은다)
    merged: dict[tuple, dict] = {}
    for it in out:
        k = (it["kind"], it["label"].replace(" ", ""))
        if k in merged:
            merged[k]["slides"].append(it["slide"])
        else:
            merged[k] = {**it, "slides": [it["slide"]]}
    return list(merged.values())


def embed(texts: list[str]) -> list[list[float]]:
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    key = lambda t: hashlib.sha1(f"{MODEL}|{t}".encode()).hexdigest()
    todo = [t for t in dict.fromkeys(texts) if key(t) not in cache]
    base = os.environ.get("UPSTAGE_SOLAR_BASE_URL", "https://api.upstage.ai/v1")
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        r = requests.post(f"{base}/embeddings", timeout=60,
                          headers={"Authorization": f"Bearer {os.environ['UPSTAGE_API_KEY']}"},
                          json={"model": MODEL, "input": chunk})
        r.raise_for_status()
        for t, d in zip(chunk, sorted(r.json()["data"], key=lambda d: d["index"])):
            cache[key(t)] = d["embedding"]
    if todo:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
    return [cache[key(t)] for t in texts]


def cos(a, b) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("concepts", nargs="?", default=str(DEFAULT))
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--temp", type=float, default=0.05, help="softmax 온도 — 작을수록 가장 가까운 것에 몰린다")
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    its = items_of(json.loads(Path(args.concepts).read_text()))
    vecs = embed([it["text"] for it in its])
    n = len(its)
    sim = [[cos(vecs[i], vecs[j]) if i != j else 0.0 for j in range(n)] for i in range(n)]
    # 행마다 softmax — 「i 가 어디에 주의를 두는가」
    att = []
    for i in range(n):
        ex = [math.exp(sim[i][j] / args.temp) if j != i else 0.0 for j in range(n)]
        z = sum(ex) or 1.0
        att.append([e / z for e in ex])
    # 중심성 = 다른 항목들이 나에게 준 attention 합 (열 합) — 많이 끌어당기는 항목이 상위 개념 후보
    central = [sum(att[i][j] for i in range(n)) for j in range(n)]
    concepts = [i for i in range(n) if its[i]["kind"] == "concept"]

    print(f"항목 {n}개 (개념 {len(concepts)} · 주장 {n - len(concepts)}) · 모델 {MODEL} · 온도 {args.temp}\n")
    print("== 중심성 상위 (다른 항목이 가장 많이 주의를 두는 것)")
    for j in sorted(range(n), key=lambda j: -central[j])[:12]:
        print(f"  {central[j]:5.2f}  [{its[j]['kind'][:2]}] S{its[j]['slides']} {its[j]['label'][:50]}")

    print("\n== 개념마다 attention 상위 · 상위 개념 후보 (나보다 중심성이 큰 개념 중 가장 가까운 것)")
    for i in sorted(concepts, key=lambda i: -central[i]):
        top = sorted(range(n), key=lambda j: -att[i][j])[:args.top]
        parents = [j for j in concepts if central[j] > central[i]]
        parent = max(parents, key=lambda j: sim[i][j]) if parents else None
        ptxt = f"{its[parent]['label']} ({sim[i][parent]:.2f})" if parent is not None else "— (최상위)"
        print(f"\n  {its[i]['label']} S{its[i]['slides']}  중심성 {central[i]:.2f}  → 상위 후보: {ptxt}")
        for j in top:
            print(f"      {att[i][j]:.2f}  sim {sim[i][j]:.2f}  [{its[j]['kind'][:2]}] {its[j]['label'][:46]}")


DIRECTION_SYSTEM = """당신은 발표 내용을 구조화하는 분석가다. 같은 발표에서 뽑은 개념 쌍마다 두 개념의 관계를 고른다.
일반 지식(사전지식)을 써서 판단해도 된다. 개념 이름은 바꾸지 마라.
관계:
- same: 같은 개념을 다르게 부른 것 (예: 「연 매출」 과 「연간 매출액」)
- A>B: A 가 상위 개념 — B 는 A 의 부분·종류·하위 요소·측정 지표·사례다 (예: 「운동 효과」 > 「근력 증가」)
- B>A: B 가 상위 개념
- related: 관련은 있지만 위아래가 아니다 (원인·결과·대조·나란한 개념, 예: 「상위 그룹」 과 「하위 그룹」)
- none: 이 발표 안에서 관계가 없다
반드시 JSON 객체만 출력: {"pairs": [{"id": 0, "rel": "A>B", "why": "짧은 이유"}]}"""


def candidate_pairs(its, vecs, concepts, pair_min: float, k: int = 5) -> list[tuple[int, int, float]]:
    """개념 쌍 후보 — 서로의 상위 k 안에 들고 유사도가 pair_min 이상."""
    sim = {(i, j): cos(vecs[i], vecs[j]) for i in concepts for j in concepts if i < j}
    s = lambda a, b: sim[(min(a, b), max(a, b))]
    topk = {i: set(sorted((j for j in concepts if j != i), key=lambda j: -s(i, j))[:k]) for i in concepts}
    out = [(i, j, sc) for (i, j), sc in sim.items() if sc >= pair_min and (j in topk[i] or i in topk[j])]
    return sorted(out, key=lambda x: -x[2])


def ask_direction(its, pairs, deck_topic: str, votes: int) -> dict[int, tuple[str, str]]:
    from collections import Counter
    from concurrent.futures import ThreadPoolExecutor
    from chuckchuck._json_text import extract_json_object
    from chuckchuck.providers.llm_impl import get_llm
    engine = get_llm("solar")
    lines = [f"발표 주제: {deck_topic}", "", "## 개념 쌍 — (id) A ‖ B. 괄호 안은 자료에 적힌 설명"]
    for n, (i, j, _) in enumerate(pairs):
        da = its[i]["text"].partition(":")[2].strip()
        db = its[j]["text"].partition(":")[2].strip()
        lines.append(f"- ({n}) A={its[i]['label']}{f' ({da})' if da else ''} ‖ B={its[j]['label']}{f' ({db})' if db else ''}")
    user = "\n".join(lines)

    def once(_):
        try:
            data = extract_json_object(engine.complete(system=DIRECTION_SYSTEM, user=user, temperature=0.0,
                                                       max_tokens=4096, json_mode=True))
            return {int(p["id"]): (str(p.get("rel", "")), str(p.get("why", ""))) for p in data.get("pairs", [])
                    if isinstance(p, dict) and str(p.get("id", "")).isdigit()}
        except Exception as e:  # noqa: BLE001 — 시험용: 한 번 깨져도 나머지로 다수결
            print("  (한 번 실패:", type(e).__name__, ")")
            return {}
    with ThreadPoolExecutor(votes) as ex:
        runs = list(ex.map(once, range(votes)))
    out = {}
    for n in range(len(pairs)):
        got = [r[n] for r in runs if n in r and r[n][0] in ("same", "A>B", "B>A", "related", "none")]
        if got:
            rel, cnt = Counter(g[0] for g in got).most_common(1)[0]
            out[n] = (rel if cnt * 2 > votes else "split", next(g[1] for g in got if g[0] == rel), cnt)
    return out


def direction_main(args) -> None:
    doc = json.loads(Path(args.concepts).read_text())
    its = items_of(doc)
    vecs = embed([it["text"] for it in its])
    concepts = [i for i in range(len(its)) if its[i]["kind"] == "concept"]
    pairs = candidate_pairs(its, vecs, concepts, args.pair_min)[:args.max_pairs]
    topic = next((s.get("claims", [""])[0] for s in doc["slides"] if s.get("claims")), doc.get("file_name", ""))
    print(f"개념 {len(concepts)}개 · 후보 쌍 {len(pairs)}개 (유사도 ≥ {args.pair_min}, 서로 상위 5) · Solar {args.votes}회 다수결\n")
    rels = ask_direction(its, pairs, topic, args.votes)
    parent: dict[int, tuple[int, float]] = {}
    same: list[tuple[int, int]] = []
    print("== 쌍별 판정 (유사도 · 관계 · 표 수 · 이유)")
    for n, (i, j, sc) in enumerate(pairs):
        rel, why, cnt = rels.get(n, ("?", "", 0))
        print(f"  {sc:.2f}  {its[i]['label'][:16]:<16} {rel:>7} ({cnt}/{args.votes})  {its[j]['label'][:16]:<16}  {why[:50]}")
        if rel == "same":
            same.append((i, j))
        elif rel in ("A>B", "B>A"):
            up, down = (i, j) if rel == "A>B" else (j, i)
            if down not in parent or sc > parent[down][1]:
                parent[down] = (up, sc)
    # 고리 끊기 — 위로 올라가다 자기로 돌아오면 그 간선을 버린다
    for c in list(parent):
        seen, cur = {c}, parent[c][0]
        while cur in parent:
            if cur in seen:
                parent.pop(c, None)
                break
            seen.add(cur)
            cur = parent[cur][0]
    kids: dict[int, list[int]] = {}
    for c, (p, _) in parent.items():
        kids.setdefault(p, []).append(c)
    print(f"\n== 같은 개념 {len(same)}쌍: " + " · ".join(f"{its[a]['label']}={its[b]['label']}" for a, b in same))
    print("\n== Solar 가 정한 위계 (자식이 있는 개념만)")

    def walk(i, d):
        print("  " + "  " * d + f"- {its[i]['label']} S{its[i]['slides']}")
        for c in sorted(kids.get(i, []), key=lambda c: its[c]["label"]):
            walk(c, d + 1)
    for r in sorted((i for i in kids if i not in parent), key=lambda i: -len(kids[i])):
        walk(r, 0)


HIER_SYSTEM = """당신은 발표 내용을 구조화하는 분석가다. 한 발표에서 뽑은 개념 목록을 보고 개념들의 위계(상위-하위)를 정리한다.
**일반 지식(사전지식)을 써서 판단하라** — 자료가 명시하지 않았어도 상식·분야 지식상 A 가 B 를 포함하거나(종류·부분·구성 요소),
B 가 A 를 재는 지표이거나, B 가 A 의 구체적 사례면 A 가 B 의 상위다.
규칙:
1. 개념마다 parent 에 상위 개념의 id 를 하나 적는다. 이 목록 안에 상위 개념이 없으면 null.
2. 목록에 없는 개념을 새로 만들거나 이름을 바꾸지 마라. id 로만 가리킨다.
3. 같은 개념을 다르게 부른 것(「연 매출」 「연간 매출액」)은 same 에 id 묶음으로 적는다. 묶은 개념은 parent 를 같게 둔다.
4. 원인·결과·대조·나란한 개념은 위계가 아니다 — 억지로 위아래로 잇지 마라.
5. 최상위(parent null)는 발표의 큰 갈래만 — 너무 많으면 잘못 짠 것이다.
반드시 JSON 객체만 출력: {"nodes": [{"id": "c3", "parent": "c1"}], "same": [["c5", "c9"]]}"""


def hierarchy_main(args) -> None:
    from collections import Counter
    from concurrent.futures import ThreadPoolExecutor
    from chuckchuck._json_text import extract_json_object
    from chuckchuck.providers.llm_impl import get_llm
    doc = json.loads(Path(args.concepts).read_text())
    its = [it for it in items_of(doc) if it["kind"] == "concept"]
    ids = [f"c{k}" for k in range(len(its))]
    topic = next((s.get("claims", [""])[0] for s in doc["slides"] if s.get("claims")), doc.get("file_name", ""))
    lines = [f"발표의 핵심 주장: {topic}", "", "## 개념 목록 — (id) 이름 [나온 장] — 자료에 적힌 설명"]
    for cid, it in zip(ids, its):
        desc = it["text"].partition(":")[2].strip()
        lines.append(f"- ({cid}) {it['label']} [S{','.join(map(str, sorted(set(it['slides']))))}]{f' — {desc}' if desc else ''}")
    user = "\n".join(lines)
    engine = get_llm("solar")

    def once(_):
        try:
            data = extract_json_object(engine.complete(system=HIER_SYSTEM, user=user, temperature=0.0,
                                                       max_tokens=6000, json_mode=True))
        except Exception as e:  # noqa: BLE001
            print("  (한 번 실패:", type(e).__name__, str(e)[:80], ")")
            return None
        par = {str(n.get("id")): (str(n.get("parent")) if n.get("parent") not in (None, "", "null") else None)
               for n in data.get("nodes", []) if isinstance(n, dict)}
        par = {k: (v if v in ids and v != k else None) for k, v in par.items() if k in ids}
        same = [[x for x in g if x in ids] for g in data.get("same", []) if isinstance(g, list)]
        return par, [g for g in same if len(g) >= 2]
    with ThreadPoolExecutor(args.votes) as ex:
        runs = [r for r in ex.map(once, range(args.votes)) if r]
    print(f"개념 {len(its)}개 · Solar {args.votes}회 중 응답 {len(runs)}회\n")
    if not runs:
        return
    # 개념마다 상위 개념 다수결 (과반 못 넘으면 null), 실행 간 일치도
    final, agree = {}, []
    for cid in ids:
        votes = Counter(r[0].get(cid) for r in runs)
        top, cnt = votes.most_common(1)[0]
        final[cid] = top if cnt * 2 > len(runs) else None
        agree.append(cnt / len(runs))
    for c in list(final):                       # 고리 끊기
        seen, cur = {c}, final[c]
        while cur is not None:
            if cur in seen:
                final[c] = None
                break
            seen.add(cur)
            cur = final.get(cur)
    same_votes = Counter(frozenset(g) for r in runs for g in r[1])
    same = [g for g, n in same_votes.items() if n * 2 > len(runs)]
    name = {cid: it["label"] for cid, it in zip(ids, its)}
    kids: dict[str | None, list[str]] = {}
    for c, p in final.items():
        kids.setdefault(p, []).append(c)
    roots = kids.get(None, [])
    print(f"상위 개념 다수결 일치도 평균 {sum(agree) / len(agree):.2f} (1.0 = 매번 같은 부모) · 최상위 {len(roots)}개 · "
          f"자식 있는 개념 {sum(1 for k in kids if k)}개")
    print("같은 개념: " + (" · ".join(" = ".join(name[x] for x in sorted(g)) for g in same) or "없음") + "\n")

    def walk(c, d):
        print("  " + "  " * d + f"- {name[c]}")
        for k in sorted(kids.get(c, []), key=lambda k: name[k]):
            walk(k, d + 1)
    for r in sorted(roots, key=lambda r: (-len(kids.get(r, [])), name[r])):
        walk(r, 0)


DEFAULT_GRAPH = ROOT / "docs/review/2026-10-02_개념그래프_재현성/graphs/graph_수익률격차.json"

HYBRID_SYSTEM = """당신은 발표 내용을 구조화하는 분석가다. 개념 위계의 일부는 자료가 이미 정했다(「고정된 위계」). 「부모를 정할 개념」 각각에 대해
상위 개념을 목록에서 하나 고르거나, 발표의 큰 갈래라 상위가 없으면 null 을 적는다.
**일반 지식(사전지식)을 써서 판단하라** — A 가 B 를 포함하거나(종류·부분·구성 요소), B 가 A 를 재는 지표이거나, B 가 A 의 구체적 사례면 A 가 상위다.
원인·결과·대조·나란한 개념은 위계가 아니다 — 확신이 없으면 null.
목록에 없는 개념을 만들거나 이름을 바꾸지 마라. id 로만 가리킨다.
반드시 JSON 객체만 출력: {"nodes": [{"id": "c3", "parent": "c1", "why": "짧은 이유"}]}"""

VERIFY_SYSTEM = """개념 쌍마다 「B 가 A 의 하위 개념인가」 를 예/아니오로 판단한다. 쌍마다 따로 판단하라.
예(yes): B 가 A 의 부분·종류·구성 요소이거나, A 를 재는 측정 지표이거나, A 의 구체적 사례다.
아니오(no): 원인·결과·관련·대조·나란한 개념이거나, B 가 오히려 A 보다 넓은 개념이거나, 둘이 같은 개념이다.
일반 지식을 써도 된다. 반드시 JSON 객체만 출력: {"pairs": [{"id": 0, "yes": true}]}"""

SAME_SYSTEM = """두 개념 이름이 이 발표에서 **같은 대상**을 가리키는지 판단한다 (표기·단위·수식어만 다른 같은 지표·같은 개념이면 same).
부분·종류·대조·나란한 다른 개념이면 different. 일반 지식을 써도 된다.
반드시 JSON 객체만 출력: {"pairs": [{"id": 0, "same": true}]}"""


MODEL_NAME = "solar"     # --model 로 바꾼다 (solar · ax · exaone · midm)


def _vote_json(system: str, user: str, votes: int):
    from concurrent.futures import ThreadPoolExecutor
    from chuckchuck._json_text import extract_json_object
    from chuckchuck.providers.llm_impl import get_llm
    engine = get_llm(MODEL_NAME)

    def once(_):
        try:
            return extract_json_object(engine.complete(system=system, user=user, temperature=0.0, max_tokens=6000, json_mode=True))
        except Exception as e:  # noqa: BLE001
            print("  (한 번 실패:", type(e).__name__, str(e)[:80], ")")
            return None
    with ThreadPoolExecutor(votes) as ex:
        return [r for r in ex.map(once, range(votes)) if isinstance(r, dict)]


def hybrid_main(args) -> None:
    from collections import Counter
    g = json.loads(Path(args.graph).read_text())
    nodes = {n["id"]: n for n in g["nodes"]}
    thesis = next(n["id"] for n in g["nodes"] if n.get("kind") == "thesis")
    concepts = [n for n in g["nodes"] if n.get("kind") == "concept"]
    cid = {n["id"]: f"c{k}" for k, n in enumerate(concepts)}
    back = {v: k for k, v in cid.items()}
    fixed = {n["id"]: n["parent_id"] for n in concepts if nodes.get(n["parent_id"], {}).get("kind") == "concept"}
    floating = [n for n in concepts if n["id"] not in fixed]

    # 1) 같은 개념 — 임베딩 0.7 이상 쌍만 Solar 에게
    vecs = embed([n["label"] + (f": {n['summary']}" if n.get("summary") else "") for n in concepts])
    pairs = [(i, j, cos(vecs[i], vecs[j])) for i in range(len(concepts)) for j in range(i + 1, len(concepts))]
    pairs = sorted([p for p in pairs if p[2] >= args.same_min], key=lambda p: -p[2])[:40]
    same: list[tuple[str, str]] = []
    if pairs:
        user = "\n".join(f"- ({k}) {concepts[i]['label']} ‖ {concepts[j]['label']}" for k, (i, j, _) in enumerate(pairs))
        runs = _vote_json(SAME_SYSTEM, user, args.votes)
        for k, (i, j, sc) in enumerate(pairs):
            yes = sum(1 for r in runs for p in r.get("pairs", []) if isinstance(p, dict) and p.get("id") == k and p.get("same") is True)
            if yes * 2 > len(runs):
                same.append((concepts[i]["label"], concepts[j]["label"]))
    # 2) 떠 있는 개념의 부모 — 고정 위계를 보여 주고 Solar 사전지식으로
    def fixed_kids(pid):
        return [c for c, p in fixed.items() if p == pid]

    def desc_of(pid, out=None):
        out = out if out is not None else set()
        for c in fixed_kids(pid):
            out.add(c)
            desc_of(c, out)
        return out
    lines = [f"발표의 핵심 주장: {nodes[thesis]['label']}", "", "## 고정된 위계 (자료가 정함)"]
    for n in concepts:
        if n["id"] in fixed:
            lines.append(f"- ({cid[n['id']]}) {n['label']}  ⟵ 상위 ({cid[fixed[n['id']]]}) {nodes[fixed[n['id']]]['label']}")
    lines += ["", "## 개념 목록 — (id) 이름 [나온 장] — 자료 설명"]
    for n in concepts:
        lines.append(f"- ({cid[n['id']]}) {n['label']} [S{','.join(map(str, n['slide_nos']))}]" + (f" — {n['summary']}" if n.get("summary") else ""))
    lines += ["", "## 부모를 정할 개념 (이것만 nodes 에 적는다)"] + [f"- ({cid[n['id']]}) {n['label']}" for n in floating]
    runs = _vote_json(HYBRID_SYSTEM, "\n".join(lines), args.votes)
    print(f"개념 {len(concepts)}개 · 자료가 정한 위계 {len(fixed)}개 · Solar 가 정할 개념 {len(floating)}개 · 응답 {len(runs)}/{args.votes}\n")
    chosen: dict[str, tuple[str | None, str, float]] = {}
    for n in floating:
        votes = Counter()
        why = {}
        for r in runs:
            for x in r.get("nodes", []):
                if isinstance(x, dict) and x.get("id") == cid[n["id"]]:
                    p = x.get("parent")
                    p = back.get(str(p)) if p not in (None, "", "null") else None
                    if p == n["id"] or (p is not None and p in desc_of(n["id"])):
                        p = None                       # 자기·자손은 부모가 될 수 없다
                    votes[p] += 1
                    why.setdefault(p, str(x.get("why", "")))
        top, cnt = votes.most_common(1)[0] if votes else (None, 0)
        if cnt * 2 <= max(1, len(runs)):
            top = None
        chosen[n["id"]] = (top, why.get(top, ""), cnt / max(1, len(runs)))
    # 3) 검증 — ① 이유가 스스로 위계를 부정하면(「무관」「관련 없」「동일」) 코드가 버린다 ② 남은 연결을 하나씩 예/아니오로 다시 묻는다
    proposed = {k: v for k, v in chosen.items() if v[0]}
    by_why = {k for k, v in proposed.items() if re.search(r"무관|관련\s*(?:이\s*)?없|관계\s*(?:가\s*)?없|동일|같은\s*개념", v[1])}
    to_check = [(k, v[0]) for k, v in proposed.items() if k not in by_why]
    rejected: set[str] = set()
    if to_check and args.verify:
        user = "\n".join(f"- ({n}) A={nodes[p]['label']} ‖ B={nodes[c]['label']}" for n, (c, p) in enumerate(to_check))
        runs_v = _vote_json(VERIFY_SYSTEM, f"발표의 핵심 주장: {nodes[thesis]['label']}\n\n" + user, args.votes)
        for n, (c, p) in enumerate(to_check):
            yes = sum(1 for r in runs_v for x in r.get("pairs", []) if isinstance(x, dict) and x.get("id") == n and x.get("yes") is True)
            if yes * 2 <= len(runs_v):
                rejected.add(c)
    kept = {k: v for k, v in proposed.items() if k not in by_why and k not in rejected}
    print(f"검증: 제안 {len(proposed)} · 이유가 부정해서 버림 {len(by_why)} · 예/아니오 검증에서 버림 {len(rejected)} · 남김 {len(kept)}")
    for k in sorted(by_why | rejected, key=lambda k: nodes[k]["label"]):
        print(f"   ✗ {nodes[proposed[k][0]]['label']} > {nodes[k]['label']}  ({'이유' if k in by_why else '검증'}: {proposed[k][1][:40]})")
    chosen = {k: (v if k in kept else (None, "", v[2])) for k, v in chosen.items()}
    parent = {**fixed, **{k: v[0] for k, v in chosen.items() if v[0]}}
    for c in list(parent):                             # 고리 끊기
        seen, cur = {c}, parent[c]
        while cur in parent:
            if cur in seen:
                parent.pop(c, None)
                break
            seen.add(cur)
            cur = parent[cur]
    agree = [v[2] for v in chosen.values()]
    print(f"Solar 부모 다수결 일치도 {sum(agree) / max(1, len(agree)):.2f} · Solar 가 부모를 단 개념 {sum(1 for v in chosen.values() if v[0])}/{len(floating)}")
    print("같은 개념(임베딩 ≥ %.2f · Solar 과반): " % args.same_min + (" · ".join(f"{a} = {b}" for a, b in same) or "없음") + "\n")
    kids: dict[str | None, list[str]] = {}
    for n in concepts:
        kids.setdefault(parent.get(n["id"]), []).append(n["id"])

    def walk(i, d):
        tag = "" if i in fixed else ("  ← Solar: " + chosen[i][1][:40] if chosen.get(i, (None,))[0] else "")
        print("  " + "  " * d + f"- {nodes[i]['label']}{tag}")
        for k in sorted(kids.get(i, []), key=lambda k: nodes[k]["label"]):
            walk(k, d + 1)
    print(f"== {nodes[thesis]['label'][:40]} (핵심 주장)")
    for r in sorted(kids.get(None, []), key=lambda r: (-len(kids.get(r, [])), nodes[r]["label"])):
        walk(r, 0)


if __name__ == "__main__":
    if "--hybrid" in sys.argv:
        ap = argparse.ArgumentParser()
        ap.add_argument("graph", nargs="?", default=str(DEFAULT_GRAPH))
        ap.add_argument("--hybrid", action="store_true")
        ap.add_argument("--votes", type=int, default=3)
        ap.add_argument("--same-min", type=float, default=0.7)
        ap.add_argument("--no-verify", dest="verify", action="store_false")
        ap.add_argument("--model", default="solar")
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        a = ap.parse_args()
        MODEL_NAME = a.model
        print(f"[모델 {MODEL_NAME}]")
        hybrid_main(a)
        sys.exit(0)
    if "--hierarchy" in sys.argv:
        ap = argparse.ArgumentParser()
        ap.add_argument("concepts", nargs="?", default=str(DEFAULT))
        ap.add_argument("--hierarchy", action="store_true")
        ap.add_argument("--votes", type=int, default=3)
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        hierarchy_main(ap.parse_args())
        sys.exit(0)
    if "--direction" in sys.argv:
        ap = argparse.ArgumentParser()
        ap.add_argument("concepts", nargs="?", default=str(DEFAULT))
        ap.add_argument("--direction", action="store_true")
        ap.add_argument("--pair-min", type=float, default=0.6)
        ap.add_argument("--max-pairs", type=int, default=60)
        ap.add_argument("--votes", type=int, default=3)
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        direction_main(ap.parse_args())
        sys.exit(0)
    main()
