"""
F-07 프롬프트 A/B 2차 (WP-C2, 2026-09-30) — 프롬프트에 남은 **덱에서 온 예시 낱말**을 빼도 위계가 흔들리지 않는가.

앞선 두 A/B 는 표본이 덱마다 2개였고, 잣대(옛 부모 일치율)가 루트 이름 한 번 바뀜에 덱 하나를 0 으로 만들었다
(`hier_stab` 머리말). 그래서 (1) 잣대를 고치고(`hier_stab.apa`), (2) 표본을 덱마다 4~6개로 늘리고, (3) 판정 규칙을 **돌리기
전에** 이 파일과 graph_ab2.md 에 적어 두고 기계적으로 가른다(`decide`).

갈래 (모두 같은 F-06 개념 캐시 out/<덱>/concept_doc.json — F-07 만 다르다):
    base  지금 프롬프트 그대로 (main 과 바이트까지 같다 — `MAIN_SHA` 로 확인)
    W     규칙 B·D 의 예시 낱말만 중립 낱말로 (focus 덱의 「집중·집중 루틴·집중력 저하·알림 끄기」 → 보온·외풍).
          예시의 구조·id·글자 수·조사는 그대로
    I     W + 스키마 예시 id(IMU2CLIP 에서 온 contrast·joint·encoder·baseline → warmth·draft·seal·heater)
    F     W + 입력 울타리(<concepts>·<flow>, `_deck_lines.fence`) + 울타리 규칙 한 줄(`FENCE_RULE`, F-06·F-26 과 같은 말)

표본:
    - base s0·s1 은 09-29 graph_ab 응답 저장소(out/_graph_ab/<덱>/llm_graph.json)를 **되쓴다** — 프롬프트·개념 입력이 바이트까지 같아
      열쇠 (tag, system, user) 가 맞는다. 나머지 표본은 새로 부른다 (Solar 고정 — 예비 A.X 로 조용히 섞이지 않게).
    - 연결 보강(concept-links) 호출은 **모든 갈래에서 빈 응답**으로 둔다. 연결은 relates 선만 더하고, 위계(parent)·F-26 주장·탐침은
      edges 를 읽지 않는다 (f26_claims·_probes 에 edges 가 없다) — 잰 지표가 하나도 안 바뀌어 예산을 본 호출에 쓴다.
    - 아래 단계: 표본마다 F-26 규칙 주장(0콜) → 탐침(`derive_probes`, 제품 경로처럼 자료 원문과 함께).

    .venv/bin/python labs/qa_bench/graph_ab2.py validate                       # LLM 0콜 — 잣대 검증 (저장된 표본)
    .venv/bin/python labs/qa_bench/graph_ab2.py run --arms base,W --budget 90  # 저장된 표본은 되쓴다
    .venv/bin/python labs/qa_bench/graph_ab2.py report                         # LLM 0콜 — 표와 판정
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import run as B  # noqa: E402 — load_dotenv·덱 목록·해시·파일 도구
import metrics as M  # noqa: E402
import hier_stab as H  # noqa: E402
from chuckchuck import _deck_lines as DL  # noqa: E402
from chuckchuck import _graph_items as GI  # noqa: E402
from chuckchuck.contracts import ClaimDoc, ConceptDoc, ConceptGraph, Context, SlideDoc  # noqa: E402
from chuckchuck.providers.llm_base import LLMProvider  # noqa: E402

AB2 = B.OUT / "_graph_ab2"
LEGACY = B.OUT / "_graph_ab"
#: 위계 A/B 덱 — held-out 합성 6 + 새 합성 2(도서관·자전거) + 실제 2(focus·SK하이닉스). 튜닝 덱은 확인용으로 따로.
DECKS = ("ir_banchan", "sci_led", "policy_jeonse", "hum_novel", "prod_tumsae", "health_glucose",
         "lib_reopen", "transit_bike", "focus", "sk_hynix")
TUNED = ("sleep", "yield_gap")
CONTROLS = ("sci_led", "prod_tumsae")
ARMS = ("base", "W", "I", "F")
#: main(=int3·ecf9a16) SYSTEM_PROMPT 의 sha256 앞 16자 — base 가 바이트까지 main 인지 확인한다 (09-30).
MAIN_SHA = "06b3d47ddc4b72c2"

# ---------------------------------------------------------------------------
# 판정 규칙 — 돌리기 **전에** 적었다 (graph_ab2.md 「판정 규칙」 과 같은 값)
# ---------------------------------------------------------------------------

#: 안정성 문턱의 상한 — 흔들림(SE_Δ)이 이보다 크면 이 값을 쓴다. 표본이 모자라 잡음이 커도 큰 하락이 통과하지 않게 (09-30 되돌림 기준).
MARGIN_CAP = 0.05
#: 덱 하나의 무너짐 — 그 덱 apa 가 base 보다 이만큼 넘게 떨어지면 (09-29 C 갈래 IR 0.88 → 0.08 같은 것)
COLLAPSE = 0.25
#: 아래 단계 문턱의 하한 (덱 합 단위) — 표본 넷 중 하나가 심은 항목 하나를 놓친 차이(0.25)는 잡음으로 본다
DOWN_FLOOR = 0.5
#: 덱에서 온 글이 적은 순 — 통과한 갈래 중 앞쪽을 고른다. W·F 는 덱 글이 같고, F 는 자료 울타리를 더한다
PREFERENCE = ("I", "F", "W", "base")
#: 표류 — base 의 09-29 표본과 오늘 표본 사이 쌍 apa 가 오늘 표본끼리보다 이만큼 넘게 낮으면 오늘 표본만으로 가른다
DRIFT = 0.1

# ---------------------------------------------------------------------------
# 갈래 — 지금 f07 을 모듈로 따로 올려 SYSTEM_PROMPT·_build_user_prompt 만 바꾼다
# ---------------------------------------------------------------------------

W_WORDS = (
    ('("집중" 과 "집중 루틴",', '("보온" 과 "보온 용품",'),
    ('("집중력 저하" 는 "집중력" 밑, "알림 끄기" 는 그것이 지키는 "집중력" 밑)',
     '("보온성 저하" 는 "보온성" 밑, "외풍 막기" 는 그것이 지키는 "보온성" 밑)'),
)
I_IDS = (("contrast", "warmth"), ("joint", "draft"), ("encoder", "seal"), ("baseline", "heater"))
_RULE11 = "11. 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.\n"
_CONCEPT_INTRO = "[S번호] 는 그 개념이 나온 슬라이드다. 같은 개념이 여러 번 나오면 하나로 합쳐라.\n\n"
_FLOW_HEAD = "\n\n## 발표 흐름 — sections 를 나눌 때만 참고한다 (노드로 쓰지 마라)\n\n"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def w_prompt(p: str) -> str:
    for old, new in W_WORDS:
        if old not in p:
            raise SystemExit(f"W: 바꿀 예시 낱말이 프롬프트에 없어요 — {old}")
        p = p.replace(old, new)
    return p


def i_prompt(p: str) -> str:
    p = w_prompt(p)
    for old, new in I_IDS:
        if f'"{old}"' not in p:
            raise SystemExit(f"I: 예시 id 가 프롬프트에 없어요 — {old}")
        p = p.replace(f'"{old}"', f'"{new}"')
    return p


def f_prompt(p: str) -> str:
    p = w_prompt(p)
    if _RULE11 not in p:
        raise SystemExit("F: 규칙 11 줄을 못 찾았어요")
    return p.replace(_RULE11, _RULE11 + f"12. {DL.FENCE_RULE}\n")


def fence_user(text: str) -> str:
    """지금 f07 사용자 프롬프트의 개념 목록·발표 흐름 칸만 울타리로 — 나머지 글은 한 글자도 안 바꾼다."""
    head, rest = text.split(_CONCEPT_INTRO, 1)
    concepts, flow = rest.split(_FLOW_HEAD, 1)
    return head + _CONCEPT_INTRO + DL.fence(concepts, "concepts") + _FLOW_HEAD + DL.fence(flow, "flow")


PROMPTS = {"base": lambda p: p, "W": w_prompt, "I": i_prompt, "F": f_prompt}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_BOX = threading.local()


def main_prompt(current: str) -> str:
    """
    지금 f07 SYSTEM_PROMPT 에서 main 프롬프트를 바이트까지 되살린다 — 어느 갈래를 채택해 f07 을 바꾼 뒤에도 이 A/B 를 다시 돌릴 수
    있게 (저장된 응답 열쇠가 system 글이라서 base 가 한 글자만 달라도 새로 부른다).
    """
    rev_w = current
    for old, new in W_WORDS:
        rev_w = rev_w.replace(new, old)
    rev_i = rev_w
    for old, new in I_IDS:
        rev_i = rev_i.replace(f'"{new}"', f'"{old}"')
    for cand in (current, rev_w, rev_i):
        cand = cand.replace(f"12. {DL.FENCE_RULE}\n", "")
        if sha(cand) == MAIN_SHA:
            return cand
    raise SystemExit(f"main 프롬프트를 되살리지 못했어요 (지금 {sha(current)}, main {MAIN_SHA})")


def arm_module(arm: str):
    """갈래마다 f07 을 따로 올린다 — 모듈 전역(SYSTEM_PROMPT)을 바꿔도 다른 갈래와 섞이지 않는다. 예시 id·이름 거르기도 따라간다."""
    mod = _load(f"chuckchuck._ab2_{arm}_f07", ROOT / "chuckchuck" / "f07_graph.py")
    mod.SYSTEM_PROMPT = PROMPTS[arm](main_prompt(mod.SYSTEM_PROMPT))
    if arm == "F":
        orig = mod._build_user_prompt
        mod._build_user_prompt = lambda doc, ctx: fence_user(orig(doc, ctx))
    examples_id, examples_label = mod._example_ids(), mod._example_labels()
    orig_asm, orig_add = mod._assemble, mod._add_items

    def copied_id(value) -> bool:
        s = mod._slug(str(value or ""))
        return bool(s) and re.sub(r"-?\d+$", "", s) in examples_id

    def asm(data, *a, **k):
        # 원응답 그대로 센다 — 예시 id·이름 따라 쓰기, 반복 루프(같은 이름 되풀이)는 후처리 전에만 보인다
        raw = [n for n in (data.get("nodes") or []) if isinstance(n, dict)]
        labels = Counter(GI.label_keys(str(n.get("label") or ""))[1] for n in raw)
        _BOX.raw = {"nodes": len(raw), "max_repeat": max(labels.values(), default=0),
                    "ids_example": sum(1 for n in raw if copied_id(n.get("id"))),
                    "labels_example": sum(1 for n in raw if str(n.get("label") or "").strip() in examples_label),
                    "thesis_raw": str(data.get("thesis") or "")}
        out = orig_asm(data, *a, **k)
        _BOX.thesis = out[3]
        return out

    def add(nodes, *a, **k):
        before = {n.id for n in nodes}
        out = orig_add(nodes, *a, **k)
        _BOX.added = [n.id for n in nodes if n.id not in before]
        return out

    mod._assemble, mod._add_items = asm, add
    return mod


# ---------------------------------------------------------------------------
# 응답 저장소 — (tag, system, user) 로 얼린다. 옛 graph_ab 저장소도 읽는다 (base s0·s1)
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_BUDGET_LOCK = threading.Lock()


class Solar(LLMProvider):
    """Solar 만 부른다 (예비로 넘기지 않는다) — 예산은 부르기 전에 잠가서 센다. 호출은 out/calls.jsonl 에 남긴다."""

    name = "solar"

    def __init__(self, deck: str, stage: str):
        self.deck, self.stage = deck, stage

    def complete(self, *, system: str, user: str, temperature: float = 0.2, max_tokens: int = 4096,
                 json_mode: bool = False) -> str:
        from chuckchuck.providers.llm_impl import get_llm

        with _BUDGET_LOCK:
            if B.BUDGET.used >= B.BUDGET.limit:
                raise B.BudgetExceeded(f"LLM 예산 {B.BUDGET.limit} 을 다 썼어요 ({self.deck}/{self.stage})")
            B.BUDGET.used += 1
        t0, err = time.time(), ""
        try:
            return get_llm("solar").complete(system=system, user=user, temperature=temperature, max_tokens=max_tokens,
                                             json_mode=json_mode)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:120]}"
            raise
        finally:
            with _LOCK, (B.OUT / "calls.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "deck": self.deck, "stage": self.stage,
                                    "model": "solar", "sec": round(time.time() - t0, 1),
                                    "chars_in": len(system) + len(user), "err": err}, ensure_ascii=False) + "\n")


class Store(LLMProvider):
    def __init__(self, deck: str, arm: str, tag: str, live: bool):
        self.deck, self.arm, self.tag, self.live = deck, arm, tag, live
        self.path = AB2 / deck / "llm_graph.json"
        self.name = "solar"
        self.hits = self.calls = self.links_stubbed = 0
        self.legacy_hits = 0

    def complete(self, *, system: str, user: str, temperature: float = 0.2, max_tokens: int = 4096,
                 json_mode: bool = False) -> str:
        if user.startswith("[TASK] concept-links"):
            self.links_stubbed += 1          # 연결 보강은 위계·주장·탐침에 안 들어간다 (머리말) — 모든 갈래 같게 빈 응답
            return '{"links": []}'
        key = B.h(self.tag, system, user)
        with _LOCK:
            own = B.read_json(self.path) or {}
            legacy = B.read_json(LEGACY / self.deck / "llm_graph.json") or {}
        if key in own:
            self.hits += 1
            return own[key]["text"]
        if key in legacy:
            self.hits += 1
            self.legacy_hits += 1
            return legacy[key]["text"]
        if not self.live:
            raise RuntimeError(f"{self.deck}/{self.arm}/{self.tag}: 저장된 응답이 없어요")
        text = Solar(self.deck, f"ab2:{self.arm}").complete(system=system, user=user, temperature=temperature,
                                                            max_tokens=max_tokens, json_mode=json_mode)
        self.calls += 1
        with _LOCK:
            own = B.read_json(self.path) or {}
            own[key] = {"model": "solar", "text": text, "arm": self.arm, "tag": self.tag,
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
            B.write_json(self.path, own)
        return text


# ---------------------------------------------------------------------------
# 표본 하나
# ---------------------------------------------------------------------------

def _inputs(deck: str, specs: dict):
    d = B.OUT / deck
    cd, sd = B.read_json(d / "concept_doc.json"), B.read_json(d / "slide_doc.json")
    if cd is None or sd is None:
        raise FileNotFoundError(f"{deck}: 개념·자료 캐시가 없어요")
    return cd, sd, Context.from_dict(specs[deck]["context"])


def sample_path(deck: str, arm: str, k: int) -> Path:
    return AB2 / deck / f"{arm}_s{k}.json"


def build_sample(deck: str, arm: str, k: int, mods: dict, specs: dict, live: bool) -> dict:
    fp = sample_path(deck, arm, k)
    got = B.read_json(fp)
    if got is not None:
        return got
    cd, sd, ctx = _inputs(deck, specs)
    mod = mods[arm]
    _BOX.raw, _BOX.thesis, _BOX.added = {}, None, []
    eng = Store(deck, arm, f"s{k}", live)
    g = mod.build_graph(ConceptDoc.from_dict(cd), ctx, slide_doc=SlideDoc.from_dict(sd), llm=eng).to_dict()
    rec = {"deck": deck, "arm": arm, "k": k, "graph": g, "thesis": _BOX.thesis, "added": list(_BOX.added),
           "raw": dict(_BOX.raw), "calls": eng.calls, "hits": eng.hits, "legacy": eng.legacy_hits,
           "links_stubbed": eng.links_stubbed, "prompt_sha": sha(mod.SYSTEM_PROMPT),
           "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    rec["down"] = downstream(g, sd, specs[deck].get("truth"))
    B.write_json(fp, rec)
    B.note(f"[{deck}] {arm} s{k} 노드 {len(g['nodes'])} (원응답 {rec['raw'].get('nodes')}, 되풀이 최대 "
           f"{rec['raw'].get('max_repeat')}, 더함 {len(rec['added'])}) 호출 {eng.calls} 되씀 {eng.hits}")
    return rec


def downstream(g: dict, sd: dict, truth: dict | None) -> dict:
    """규칙 경로(0콜) 주장·탐침 — 탐침은 제품 경로처럼 자료 원문과 함께(`slides`), 벤치 옛 경로(원문 없이)도 같이 센다."""
    from chuckchuck._probes import derive_probes
    from chuckchuck.f26_claims import build_claims

    claims = build_claims(g, sd, llm="none").to_dict()
    graph = ConceptGraph.from_dict(g)
    slides = {s["slide_no"]: s.get("raw_text") or "" for s in sd["slides"]}
    out: dict = {"claims": len(claims["claims"])}
    cm = M.claim_metrics(claims, sd, truth)
    out.update(planted_claims=cm.get("planted_hit"), planted_claims_n=cm.get("planted"))
    for tag, probes in (("", derive_probes(graph, ClaimDoc.from_dict(claims), slides)),
                        ("_noslides", derive_probes(graph, ClaimDoc.from_dict(claims)))):
        pm = M.probe_metrics([p.to_dict() for p in probes], g, truth)
        out.update({f"probes{tag}": pm["n"], f"probe_hit{tag}": pm.get("planted_hit"), f"probe_n{tag}": pm.get("planted"),
                    f"plantable{tag}": pm.get("plantable_probes"), f"plantable_tp{tag}": pm.get("plantable_tp"),
                    f"neg_fp{tag}": len(pm.get("negative_fp") or []), f"false_tension{tag}": pm.get("false_tension") or 0,
                    f"recall{tag}": pm.get("recall_by_id")})
    planted = [t for t in (truth or {}).get("planted") or [] if t["expect"] == "probe" and t.get("labels_any")]
    out["probe_fp"] = (out["plantable"] - out["plantable_tp"]) if out.get("plantable") is not None else None
    out["planted_nodes"] = sum(1 for t in planted if any(M._has_any(n["label"], t["labels_any"]) for n in g["nodes"]))
    out["planted_nodes_n"] = len(planted)
    keys = [GI.label_keys(n["label"])[1] for n in g["nodes"]]
    out["dup_exact"] = len(keys) - len(set(keys))
    out["roots"] = sum(1 for n in g["nodes"] if not n.get("parent_id"))
    out["nodes"] = len(g["nodes"])
    # 모양 — 납작한 트리(전부 루트 밑)는 apa 가 거저 높다 (09-30 검증: 제품 대조군 우연 수준 0.93). 세부(깊이 3) 비율로 본다
    out["depth3"] = sum(1 for n in g["nodes"] if n.get("depth") == 3) / max(1, len(g["nodes"]))
    return out


# ---------------------------------------------------------------------------
# 표·판정
# ---------------------------------------------------------------------------

def load_samples(decks, arms, specs: dict) -> dict[str, dict[str, list[dict]]]:
    """저장된 표본 — 아래 단계(규칙 주장·탐침)는 결정적이라 **지금 코드로 다시** 잰다 (저장 뒤 지표를 더해도 표가 맞다)."""
    out: dict = {}
    for deck in decks:
        sd = B.read_json(B.OUT / deck / "slide_doc.json")
        for arm in arms:
            recs = [B.read_json(p) for p in sorted((AB2 / deck).glob(f"{arm}_s[0-9].json"),
                                                   key=lambda p: int(p.stem.split("_s")[1]))]
            for r in recs:
                r["down"] = downstream(r["graph"], sd, specs[deck].get("truth"))
            if recs:
                out.setdefault(deck, {})[arm] = recs
    return out


def _deck_rows(samples: dict, arm: str, decks) -> dict[str, tuple[list, int]]:
    return {d: (H.within([r["graph"] for r in samples[d][arm]]), len(samples[d][arm]))
            for d in decks if arm in samples.get(d, {}) and len(samples[d][arm]) >= 2}


def _down_sum(samples: dict, arm: str, decks, field: str) -> tuple[float, float, int]:
    """덱마다 표본 평균 → 덱 합. 표준오차는 덱마다 (표본 분산 / 표본 수) 를 더해 √."""
    tot, var, n_decks = 0.0, 0.0, 0
    for d in decks:
        vals = [r["down"].get(field) for r in samples.get(d, {}).get(arm, [])]
        vals = [v for v in vals if v is not None]
        if not vals:
            continue
        n_decks += 1
        tot += sum(vals) / len(vals)
        s = H.sd(vals)
        var += (s * s / len(vals)) if s is not None else 0.0
    return tot, var ** 0.5, n_decks


def _sample_mean_se(samples: dict, arm: str, decks, field: str) -> tuple[float | None, float | None]:
    """표본마다 값이 하나인 지표(모양) — 덱마다 표본 평균 → 덱 평균, 표준오차는 √(Σ 분산/표본 수) / 덱 수."""
    means, var = [], 0.0
    for d in decks:
        vals = [r["down"].get(field) for r in samples.get(d, {}).get(arm, []) if r["down"].get(field) is not None]
        if not vals:
            continue
        means.append(sum(vals) / len(vals))
        s = H.sd(vals)
        var += (s * s / len(vals)) if s is not None else 0.0
    return (sum(means) / len(means), var ** 0.5 / len(means)) if means else (None, None)


#: (지표, 이름, 좋은 쪽) — +1 은 많을수록, -1 은 적을수록 좋다. probe_fp = 심을 수 있는 종류의 탐침 중 심은 것이 아닌 것 (정밀도의 분모−분자)
DOWN_GATES = (("planted_nodes", "심은 탐침 대상 노드", +1), ("planted_claims", "심은 주장", +1),
              ("probe_hit", "심은 탐침 재현", +1), ("probe_fp", "헛탐침(정밀도)", -1))


def decide(samples: dict, decks=DECKS) -> dict:
    """
    판정 규칙(돌리기 전에 적음)을 기계적으로 — 갈래마다 문 1~4 를 보고, 통과한 갈래 중 덱 글이 가장 적은 것을 고른다.

    1 위계: Δapa = 갈래 − base (덱 평균) ≥ −m,  m = min(SE_Δ, MARGIN_CAP), SE_Δ = √(SE_갈래² + SE_base²) (덱마다 잭나이프)
    2 노드 집합: Δcover 도 같은 규칙
    3 무너짐: 어느 덱도 apa 가 base 보다 COLLAPSE 넘게 떨어지지 않는다
    4 아래 단계: 심은 탐침 대상 노드·심은 주장·심은 탐침 재현 (덱 합) 이 각각 ≥ base − max(SE_Δ, DOWN_FLOOR), 헛탐침은
      ≤ base + max(SE_Δ, DOWN_FLOOR), 대조군(과학·제품) 거짓 긴장은 갈래의 모든 표본에서 0
    5 모양: 세부(깊이 3) 비율의 덱 평균이 ≥ base − min(SE_Δ, MARGIN_CAP) — 트리를 납작하게 펴서 apa 를 거저 얻지 않았다
    """
    res: dict = {"arms": {}}
    base_rows = _deck_rows(samples, "base", decks)
    for arm in ARMS[1:]:
        rows = _deck_rows(samples, arm, decks)
        common = [d for d in decks if d in rows and d in base_rows]
        if not common:
            continue
        gates, info = {}, {}
        for field in ("apa", "cover"):
            ma, sa = H.arm_mean_se({d: rows[d] for d in common}, field)
            mb, sb = H.arm_mean_se({d: base_rows[d] for d in common}, field)
            se = ((sa or 0) ** 2 + (sb or 0) ** 2) ** 0.5
            m = min(se, MARGIN_CAP)
            info[field] = {"arm": ma, "base": mb, "delta": ma - mb, "se_arm": sa, "se_base": sb, "se_delta": se, "margin": m}
            gates[field] = ma - mb >= -m
        drops = {d: H.pair_mean(rows[d][0], "apa") - H.pair_mean(base_rows[d][0], "apa") for d in common}
        info["collapse"] = {d: round(v, 3) for d, v in drops.items() if v < -COLLAPSE}
        gates["collapse"] = not info["collapse"]
        ma, sa = _sample_mean_se(samples, arm, common, "depth3")
        mb, sb = _sample_mean_se(samples, "base", common, "depth3")
        se = ((sa or 0) ** 2 + (sb or 0) ** 2) ** 0.5
        info["depth3"] = {"arm": ma, "base": mb, "delta": ma - mb, "se_delta": se, "margin": min(se, MARGIN_CAP)}
        gates["shape"] = ma - mb >= -min(se, MARGIN_CAP)
        down = {}
        ok_down = True
        for field, _name, sign in DOWN_GATES:
            ta, ea, _ = _down_sum(samples, arm, common, field)
            tb, eb, _ = _down_sum(samples, "base", common, field)
            se = (ea ** 2 + eb ** 2) ** 0.5
            m = max(se, DOWN_FLOOR)
            down[field] = {"arm": ta, "base": tb, "delta": ta - tb, "margin": m, "ok": sign * (ta - tb) >= -m}
            ok_down &= down[field]["ok"]
        ft = sum(r["down"].get("false_tension") or 0 for d in common if d in CONTROLS for r in samples[d][arm])
        down["false_tension_controls"] = ft
        gates["downstream"] = ok_down and ft == 0
        info["down"] = down
        res["arms"][arm] = {"decks": common, "gates": gates, "pass": all(gates.values()), **info}
    passed = [a for a in PREFERENCE if a != "base" and res["arms"].get(a, {}).get("pass")]
    res["adopt"] = passed[0] if passed else "base"
    return res


def _fmt(x, nd=3):
    return "—" if x is None else f"{x:.{nd}f}"


def _graph_pairs(recs: list[dict]):
    """표본 쌍 (i, j, (그래프 i, 그래프 j)) — 우연 수준처럼 쌍마다 따로 재는 것에."""
    gs = [r["graph"] for r in recs]
    return [(i, j, (gs[i], gs[j])) for i in range(len(gs)) for j in range(i + 1, len(gs))]


def tables(samples: dict, decks=DECKS) -> str:
    """graph_ab2.md 에 붙일 표 — 덱마다 쌍 평균 ± SD, 갈래 평균 ± SE, 갈래 사이 일치, 아래 단계."""
    arms = [a for a in ARMS if any(a in samples.get(d, {}) for d in decks)]
    lines = []
    for field, title in (("apa", "정렬 부모 일치 apa (주 지표)"), ("cover", "짝 덮음 cover"), ("tes", "편집 유사도 tes"),
                         ("pa_old", "옛 부모 일치율 pa_old (견주기용)")):
        lines += [f"\n### {title} — 덱마다 표본 쌍 평균 ± SD (쌍 수)\n", "| 덱 | " + " | ".join(arms) + " |",
                  "|---|" + "---|" * len(arms)]
        for d in decks:
            cells = []
            for a in arms:
                recs = samples.get(d, {}).get(a) or []
                pairs = H.within([r["graph"] for r in recs])
                vals = [p[2][field] for p in pairs if p[2][field] is not None]
                cells.append(f"{_fmt(H.mean(vals), 2)} ± {_fmt(H.sd(vals), 2)} ({len(vals)})" if vals else "—")
            lines.append(f"| {d} | " + " | ".join(cells) + " |")
        row = []
        for a in arms:
            m, se = H.arm_mean_se(_deck_rows(samples, a, decks), field)
            row.append(f"**{_fmt(m)}** ± {_fmt(se)} (SE)")
        lines.append("| **덱 평균** | " + " | ".join(row) + " |")
    # 갈래 사이 — base 표본과 그 갈래 표본의 모든 쌍 (같은 분포면 base 안 일치와 같아야 한다)
    lines += ["\n### base 와의 일치 (apa, 갈래 사이 모든 쌍) — base 안 일치와 견준다\n",
              "| 덱 | base 안 | " + " | ".join(f"base↔{a}" for a in arms if a != "base") + " |",
              "|---|---|" + "---|" * (len(arms) - 1)]
    for d in decks:
        b = samples.get(d, {}).get("base") or []
        cells = [_fmt(H.mean(p[2]["apa"] for p in H.within([r["graph"] for r in b])), 2)]
        for a in arms:
            if a == "base":
                continue
            xs = samples.get(d, {}).get(a) or []
            cells.append(_fmt(H.mean(p[2]["apa"] for p in H.cross([r["graph"] for r in b], [r["graph"] for r in xs])), 2)
                         if xs else "—")
        lines.append(f"| {d} | " + " | ".join(cells) + " |")
    # 모양·아래 단계 — 덱 합 (덱마다 표본 평균)
    lines += ["\n### 그래프 모양·아래 단계 (규칙 경로, 덱마다 표본 평균의 덱 합 ± SE)\n",
              "| 지표 | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    row = []
    for a in arms:
        m, se = _sample_mean_se(samples, a, decks, "depth3")
        nulls = [null_apa(p1, p2, random.Random(930)) for d in decks
                 for _, _, (p1, p2) in _graph_pairs(samples.get(d, {}).get(a) or [])]
        row.append(f"세부 {_fmt(m, 2)} ± {_fmt(se, 2)} · 우연 apa {_fmt(H.mean(nulls), 2)}")
    lines.append("| 모양 (깊이 3 비율 덱 평균 ± SE · 부모 섞은 우연 수준 apa) | " + " | ".join(row) + " |")
    for field, name in (("nodes", "노드"), ("roots", "루트"), ("dup_exact", "이름이 똑같은 노드"),
                        ("planted_nodes", "심은 탐침 대상 노드 (/ 분모)"), ("planted_claims", "심은 주장 (/ 분모)"),
                        ("probe_hit", "심은 탐침 재현 (/ 분모)"), ("plantable_tp", "탐침 정밀도 분자"),
                        ("plantable", "탐침 정밀도 분모"), ("probe_fp", "헛탐침 (분모 − 분자)"),
                        ("probe_hit_noslides", "심은 탐침 재현 · 원문 없이"),
                        ("neg_fp", "음성 대조 오탐"), ("false_tension", "대조군 거짓 긴장")):
        cells = []
        for a in arms:
            t, e, _ = _down_sum(samples, a, decks, field)
            den = {"planted_nodes": "planted_nodes_n", "planted_claims": "planted_claims_n", "probe_hit": "probe_n",
                   "probe_hit_noslides": "probe_n_noslides"}.get(field)
            dn = f" / {_down_sum(samples, a, decks, den)[0]:.0f}" if den else ""
            cells.append(f"{t:.2f} ± {e:.2f}{dn}")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    # 원응답 — 예시 따라 쓰기·반복 루프
    lines += ["\n### 원응답 (후처리 전) — 예시 따라 쓰기·반복 루프\n",
              "| 지표 | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    for field, name in (("nodes", "원응답 노드 (표본 합)"), ("ids_example", "예시 id 따라 쓴 노드"),
                        ("labels_example", "예시 이름(주제 개념…) 따라 쓴 노드"), ("max_repeat", "한 이름 되풀이 최대")):
        cells = []
        for a in arms:
            vals = [r["raw"].get(field) or 0 for d in decks for r in samples.get(d, {}).get(a) or []]
            cells.append(str(max(vals, default=0) if field == "max_repeat" else sum(vals)))
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 잣대 검증 — 저장된 표본만 (LLM 0콜)
# ---------------------------------------------------------------------------

def null_apa(ga: dict, gb: dict, rng: random.Random, reps: int = 20) -> float | None:
    """우연 수준 — b 의 부모 배정을 루트 아닌 노드끼리 섞어(부모마다 자식 수는 그대로) 잰 apa 평균. 잣대가 거저 높지 않은지 본다."""
    nodes = [dict(n) for n in gb["nodes"]]
    kids = [i for i, n in enumerate(nodes) if n.get("parent_id")]
    if len(kids) < 2:
        return None
    vals = []
    for _ in range(reps):
        parents = [nodes[i]["parent_id"] for i in kids]
        rng.shuffle(parents)
        shuffled = [dict(n) for n in nodes]
        for i, p in zip(kids, parents):
            shuffled[i]["parent_id"] = p if p != shuffled[i]["id"] else nodes[i]["parent_id"]
        v = H.compare(ga, {"nodes": shuffled})["apa"]
        if v is not None:
            vals.append(v)
    return H.mean(vals)


def cmd_validate(ns, specs) -> int:
    """옛 잣대와 새 잣대를 같은 쌍에서 — 09-29 base·C 표본(지금 코드로 다시 조립), 09-30 WP-C 표본(저장된 그래프 그대로)."""
    import graph_ab as GA

    mods = {"base": arm_module("base")}
    mods["C"] = _load("chuckchuck._ab2_C_f07", ROOT / "chuckchuck" / "f07_graph.py")
    mods["C"].SYSTEM_PROMPT = GA.c_prompt(mods["C"].SYSTEM_PROMPT)
    rng = random.Random(930)
    out: dict = {"legacy": {}, "wpc": {}}
    print("## 09-29 graph_ab 표본 (지금 후처리로 다시 조립, 연결 보강 빈 응답)")
    for deck in DECKS:
        if not (LEGACY / deck / "llm_graph.json").exists():
            continue
        cd, sd, ctx = _inputs(deck, specs)
        for arm in ("base", "C"):
            gs = []
            for k in (0, 1):
                try:
                    gs.append(mods[arm].build_graph(ConceptDoc.from_dict(cd), ctx, slide_doc=SlideDoc.from_dict(sd),
                                                    llm=Store(deck, arm, f"s{k}", live=False)).to_dict())
                except Exception as e:  # noqa: BLE001
                    print(f"  {deck} {arm} s{k} 없음: {e}")
            if len(gs) == 2:
                r = H.compare(*gs)
                r["null_apa"] = null_apa(*gs, rng)
                out["legacy"].setdefault(deck, {})[arm] = r
                print(f"  {deck:15s} {arm:4s} pa_old {_fmt(r['pa_old'])} apa {_fmt(r['apa'])} (우연 {_fmt(r['null_apa'])}) "
                      f"cover {_fmt(r['cover'])} tes {_fmt(r['tes'])} 짝 {r['same']}/{r['near']}/{r['renamed']} 옮김 {r['moved']}")
    print("## 09-30 WP-C prompt_ab 표본 (저장된 그래프 그대로 — 그때 후처리)")
    root = B.OUT / "_wpc" / "graphs" / "prompt_ab"
    for p in sorted(root.glob("*__base0.json")):
        deck = p.name.split("__")[0]
        for arm in ("base", "new"):
            a, b = B.read_json(root / f"{deck}__{arm}0.json"), B.read_json(root / f"{deck}__{arm}1.json")
            if a and b:
                r = H.compare(a, b)
                out["wpc"].setdefault(deck, {})[arm] = r
                print(f"  {deck:15s} {arm:4s} pa_old {_fmt(r['pa_old'])} apa {_fmt(r['apa'])} 짝 {r['same']}/{r['near']}/{r['renamed']}")
    B.write_json(AB2 / "validate.json", out)
    return 0


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def cmd_run(ns, specs) -> int:
    B.BUDGET.limit = ns.budget
    arms = [a for a in ns.arms.split(",") if a in ARMS]
    mods = {a: arm_module(a) for a in arms}
    decks = [d for d in ns.decks.split(",") if d in specs]
    jobs = []
    for deck in decks:
        for arm in arms:
            n = ns.base_samples if arm == "base" else ns.samples
            jobs += [(deck, arm, k) for k in range(n)]
    if ns.tuned:
        jobs += [(deck, arm, 0) for deck in TUNED for arm in arms]
    todo = [j for j in jobs if not sample_path(*j).exists()]
    B.note(f"표본 {len(jobs)} 중 새로 만들 것 {len(todo)} · 예산 {ns.budget}")
    fails = []

    def one(job):
        try:
            build_sample(*job, mods, specs, live=True)
        except B.BudgetExceeded as e:
            fails.append((job, str(e)))
        except Exception as e:  # noqa: BLE001 — 한 표본이 죽어도 나머지는 잰다 (다시 돌리면 이어서 한다)
            fails.append((job, f"{type(e).__name__}: {str(e)[:160]}"))

    with ThreadPoolExecutor(max_workers=ns.workers) as ex:
        list(ex.map(one, todo))
    for job, why in fails:
        B.note(f"  ✗ {job}: {why}")
    B.note(f"LLM 호출 {B.BUDGET.used}")
    return 1 if fails else 0


def cmd_report(ns, specs) -> int:
    decks = [d for d in ns.decks.split(",") if d in specs]
    samples = load_samples(decks + list(TUNED), ARMS, specs)
    text = tables(samples, [d for d in decks if d in samples])
    verdict = decide(samples, [d for d in decks if d in samples])
    drift = {}
    for d in decks:
        recs = samples.get(d, {}).get("base") or []
        old = [r["graph"] for r in recs if r.get("legacy")]
        new = [r["graph"] for r in recs if not r.get("legacy")]
        drift[d] = {"old_old": H.mean(p[2]["apa"] for p in H.within(old)),
                    "new_new": H.mean(p[2]["apa"] for p in H.within(new)),
                    "old_new": H.mean(p[2]["apa"] for p in H.cross(old, new))}
    # 표류 규칙(돌리기 전에 적음): 09-29 표본과 오늘 표본 사이 쌍이 오늘 표본끼리보다 덱 평균 0.1 넘게 낮으면 base 를 오늘 표본만으로
    both = [v for v in drift.values() if v["old_new"] is not None and v["new_new"] is not None]
    on, nn = H.mean(v["old_new"] for v in both), H.mean(v["new_new"] for v in both)
    verdict["drift"] = {"old_new": on, "new_new": nn, "fallback": bool(both) and on < nn - DRIFT}
    if verdict["drift"]["fallback"]:
        fresh = {d: {**arms_, "base": [r for r in arms_.get("base", []) if not r.get("legacy")]} for d, arms_ in samples.items()}
        verdict = {**decide(fresh, [d for d in decks if d in samples]), "drift": verdict["drift"]}
    # 튜닝 덱(확인용, 갈래마다 1번) — base s0 과의 일치와 심은 탐침
    tuned = ["\n### 튜닝 덱 확인 (표본 1개씩 — base s0 과 견줌)\n", "| 덱 | 갈래 | 노드 | base 와 apa · pa_old | 심은 탐침 대상 노드 | 심은 탐침 재현 |",
             "|---|---|---|---|---|---|"]
    for d in TUNED:
        b = (samples.get(d, {}).get("base") or [None])[0]
        for a in ARMS:
            r = (samples.get(d, {}).get(a) or [None])[0]
            if r is None or b is None:
                continue
            c = H.compare(b["graph"], r["graph"])
            dn = r["down"]
            tuned.append(f"| {d} | {a} | {dn['nodes']} | {_fmt(c['apa'], 2)} · {_fmt(c['pa_old'], 2)} | "
                         f"{dn['planted_nodes']}/{dn['planted_nodes_n']} | {dn.get('probe_hit')}/{dn.get('probe_n')} |")
    text += "\n" + "\n".join(tuned)
    B.write_json(AB2 / "summary.json", {"verdict": verdict, "drift": drift})
    (AB2 / "tables.md").write_text(text, encoding="utf-8")
    print(text)
    print("\n## 판정\n" + json.dumps(verdict, ensure_ascii=False, indent=1, default=str))
    print("\n## base 옛(09-29)·새 표본 표류 — apa 평균\n" + json.dumps(drift, ensure_ascii=False, indent=1, default=str))
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="labs/qa_bench/graph_ab2.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("validate", "run", "report"))
    ap.add_argument("--arms", default="base,W")
    ap.add_argument("--decks", default=",".join(DECKS))
    ap.add_argument("--samples", type=int, default=4)
    ap.add_argument("--base-samples", type=int, default=6)
    ap.add_argument("--tuned", action="store_true", help="수면·수익률격차를 갈래마다 1번씩 (확인용)")
    ap.add_argument("--budget", type=int, default=90)
    ap.add_argument("--workers", type=int, default=4)
    ns = ap.parse_args(argv)
    specs = B.load_decks(B.DEFAULT_REPO, set())
    return {"validate": cmd_validate, "run": cmd_run, "report": cmd_report}[ns.cmd](ns, specs)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
