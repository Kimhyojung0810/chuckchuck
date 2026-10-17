"""
[F-08 앙상블] 국내 AI 네 모델(Solar · A.X · Mi:dm · EXAONE)이 같이 만드는 Q&A 질문 (2026-10-17, docs/qa-ensemble/PLAN.md).

    자료 올릴 때 ~ 발표 중 (뒤에서)   build_pool()      슬롯(코드) → 모델마다 후보(ens_generate) → 코드 거르기(버림)
                                                        → 서로 평가(ens_peer_review, 작성자 가림·순서 섞음·자기 것 안 매김) → 묶음
    발표 끝 (1~2초, LLM 없음)          pick_opening()    묶음에서 1·2번 — 발표에서 이미 잘 설명한 건 뒤로, 1·2번 중 P1/P2 하나 이상
    1·2번 답하는 동안                   voice_round()     발표 받아쓰기 + 앞 답의 신호(_ens_slots.voice_signals)로 네 모델이 3번+ 후보(ens_voice)
                                        choose_next()     최종 선택 모델이 고른다(ens_pick, 이유 한 줄). 늦으면 묶음의 남은 후보를 바로 낸다.

규율:
- 「무엇을 물을지」는 코드가 정한다(슬롯). 모델은 슬롯마다 문장과 모범답만 쓴다.
- §0-1 핵심 원칙 — 자료의 **핵심을 간파했는지** 묻는다. 미시 확인(숫자·용어·장 번호·말과 자료의 작은 차이)은 거르기가 버린다.
- 통과 못 한 후보는 **버린다** — 템플릿으로 바꾸지 않는다. 같은 슬롯의 다른 모델 후보가 있으면 그걸 쓴다.
- 서로 평가는 작성 모델을 가리고(K01…) 순서를 섞고, 자기 후보는 안 매긴다(실험 모드 `peer_self=True` 에서만 매겨 편향을 잰다).
- 호출 수: 모델마다 슬롯 묶음당 1회(슬롯 ≤5 개씩 → 덱당 1~2회) + 서로 평가 1회. 429 는 물러났다 다시(`_complete`).
- 켜기: `QA_ENSEMBLE=1` (기본 0 — 측정 근거가 나오면 켠다). 모델 `QA_ENS_MODELS=solar,ax,midm,exaone`, 최종 선택 `QA_ENS_PICKER=solar`.
- 호출 로그: 함수 이름이 곧 제출 기능이다 (`_ai_calllog.FUNC_FEATURES` — ens_generate · ens_peer_review · ens_pick · ens_voice · polish_gists).
"""
from __future__ import annotations

import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from . import _ai_calllog
from . import _ens_slots as ES
from . import _grounding as grounding
from ._evidence import clean_slide_text
from ._json_text import extract_json_object
from .contracts import (
    ClaimQuote,
    ConceptGraph,
    Question,
    QuestionBasis,
    SlideDoc,
    Transcript,
    TrapPremise,
)
from .providers.llm_base import LLMProvider

#: solar-pro3 는 2026-10-30 KST 종료 — 후속 solar-pro4(solar4). 10-17 측정: 서로 평가에서 자기 선호 없음(−0.03, pro3 은 +0.39~0.56),
#: 최종 선택에서 심판단 1등과 일치 0.37(다른 후보 0.32) · 자기 계열 고름 0.11(기대 0.16). MODEL_LEDGER §4.
MODELS_DEFAULT = ("solar4", "ax", "midm", "exaone")
PICKER_DEFAULT = "solar4"
#: 한 번 부를 때 실을 슬롯 수 — 덱당 모델별 1~2회 (PLAN 「호출 수 조절」)
SLOTS_PER_CALL = int(os.environ.get("QA_ENS_SLOTS_PER_CALL", "5"))
GEN_MAX_TOKENS = 3000
PEER_MAX_TOKENS = 3000
#: 429 · 일시 오류에 물러날 시간(초). 제공자가 2초 뒤 한 번 다시 부른 다음이다.
BACKOFF_SEC = (4.0, 10.0, 20.0)
#: 서로 평가 점수 무게 — 핵심성이 가장 무겁다 (§0-1)
PEER_WEIGHTS = {"core": 0.4, "grounded": 0.2, "specific": 0.25, "clear": 0.15}


def enabled() -> bool:
    return (os.environ.get("QA_ENSEMBLE") or "0").strip().lower() in ("1", "true", "yes", "on")


def model_names() -> list[str]:
    raw = os.environ.get("QA_ENS_MODELS") or ",".join(MODELS_DEFAULT)
    return [m.strip().lower() for m in raw.split(",") if m.strip()]


def assign_mode() -> str:
    """슬롯을 누구에게 — strength(패턴별 잘하는 두 모델, 기본) · all(넷 다 모든 슬롯) · roles(돌려 가며 둘).
    10-17 dev 2회(같은 심판 한 호출): strength 4.30·4.46 vs all 4.15·4.29 — 두 번 다 +0.16, 심판 넷 중 셋이 같은 쪽, 호출 −20%.
    Mi:dm 은 생성 슬롯이 없고 서로 평가 · 음성 추론을 맡는다."""
    return (os.environ.get("QA_ENS_ASSIGN") or "strength").strip().lower()


def picker_name() -> str:
    return (os.environ.get("QA_ENS_PICKER") or PICKER_DEFAULT).strip().lower()


#: 앙상블 호출에만 얹는 제공자 변수 (10-17 param_replay 실측 — MODEL_LEDGER). 기본은 끔, 측정 뒤 켠다.
#: QA_ENS_EXAONE_PP=1.5 — EXAONE 모델 카드 권장 presence_penalty: 되풀이 고리(4096토큰) 2/20 → 1/20 · p95 49.5 → 20.4초
#: QA_ENS_MIDM_SCHEMA=1 — Mi:dm 에 response_format json_schema: JSON 성공 9/12 → 12/12 · 후보 3.7 → 4.8개 · p50 11.2 → 15.2초
_MIDM_SCHEMA = {"type": "json_schema", "json_schema": {"name": "qa", "schema": {"type": "object", "properties": {
    "items": {"type": "array"}, "scores": {"type": "array"}, "pick": {"type": "string"}, "reason": {"type": "string"}}}}}


def make_llm(name: str) -> LLMProvider:
    from .providers.llm_impl import REGISTRY  # noqa: PLC0415
    llm = REGISTRY[name]()
    pp = (os.environ.get("QA_ENS_EXAONE_PP") or "").strip()
    if name == "exaone" and pp:
        llm.extra_body["presence_penalty"] = float(pp)
    if name == "midm" and (os.environ.get("QA_ENS_MIDM_SCHEMA") or "").strip() in ("1", "true", "on"):
        llm.extra_body["response_format"] = _MIDM_SCHEMA
    return llm


# ─── 호출 · 기록 ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CallRow:
    role: str
    model: str
    sec: float
    ok: bool
    error: str = ""
    retries: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    n_in: int = 0
    n_out: int = 0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _complete(llm: LLMProvider, role: str, calls: list, *, system: str, user: str, temperature: float,
              max_tokens: int) -> dict:
    """JSON 하나 받기 — 429·일시 오류는 물러났다 다시, JSON 이 깨지면 한 번 더. 실패면 {}(그 모델 몫만 빠진다)."""
    t0 = time.monotonic()
    retries = 0
    err = ""
    for wait in (*BACKOFF_SEC, None):
        try:
            raw = llm.complete(system=system, user=user, temperature=temperature, max_tokens=max_tokens, json_mode=True)
            try:
                data = extract_json_object(raw)
            except ValueError:
                retries += 1
                raw = llm.complete(system=system + "\n\n반드시 JSON 객체 하나만 출력한다.", user=user,
                                   temperature=temperature, max_tokens=max_tokens, json_mode=True)
                data = extract_json_object(raw)
            u = getattr(llm, "last_usage", None) or {}
            calls.append(CallRow(role, getattr(llm, "name", "?"), round(time.monotonic() - t0, 2), True, "", retries,
                                 u.get("prompt_tokens"), u.get("completion_tokens")))
            return data
        except Exception as e:  # noqa: BLE001 — 한 모델의 실패가 묶음을 깨지 않는다
            err = f"{type(e).__name__}: {str(e)[:160]}"
            # 연결 실패는 제공자가 이미 한 번 다시 불렀다 — 또 물러나면 죽은 엔드포인트에 묶음이 40초씩 묶인다 (10-17 오류 주입: 87초)
            transient = any(k in err for k in (" 429", " 500", " 502", " 503", " 504"))
            if wait is None or not transient:
                break
            retries += 1
            time.sleep(wait + random.random())
    calls.append(CallRow(role, getattr(llm, "name", "?"), round(time.monotonic() - t0, 2), False, err, retries))
    sys.stderr.write(f"[f08-ens] {role} {getattr(llm, 'name', '?')} 실패: {err}\n")
    return {}


# ─── 입력 재료 ────────────────────────────────────────────────────────────────────────────────

@dataclass
class Deck:
    graph: ConceptGraph
    slides: dict
    lines: list
    lines_by_id: dict
    idx: object
    deck_tokens: set
    sources: list
    thesis: str
    claims: object = None

    @classmethod
    def build(cls, graph, slidedoc, claims=None, transcript=None) -> "Deck":
        g = graph if isinstance(graph, ConceptGraph) else ConceptGraph.from_dict(graph)
        sd = slidedoc if isinstance(slidedoc, SlideDoc) or slidedoc is None else SlideDoc.from_dict(slidedoc)
        slides = {s.slide_no: s for s in (sd.slides if sd else [])}
        lines = ES.deck_lines(slides)
        idx = grounding.build_index(slides, list(g.nodes))
        root = ES._root(g)
        text = " ".join(clean_slide_text(s.raw_text or "") for s in slides.values())
        tokens = {t for t in ES._tokens(text)} | {t for n in g.nodes for t in ES._tokens(n.label)}
        if claims is not None and isinstance(claims, dict):
            from .contracts import ClaimDoc  # noqa: PLC0415
            claims = ClaimDoc.from_dict(claims)
        return cls(g, slides, lines, {ln.id: ln for ln in lines}, idx, tokens, [text],
                   root.label if root is not None else "", claims)


def _slot_line(s: ES.Slot, deck: Deck) -> str:
    head = f"{s.id} · {s.pattern} {ES.PATTERNS[s.pattern]} · 대상: 「{s.label}」({s.kind or '개념'}, {','.join(map(str, s.slides))}장)"
    if s.partner_label:
        head += f" ↔ 「{s.partner_label}」"
    head += f" · 관련 줄: {', '.join(s.lines)}"
    if s.trap:
        head += (f"\n    함정 전제(코드가 만든 틀린 말): 「{s.trap['premise']}」 — 이 전제를 **그대로** 발표자가 한 말처럼 질문에 넣고, "
                 f"자료의 사실(「{s.trap['fact']}」)은 질문에 쓰지 않는다. 모범답은 코드가 채운다.")
    return head


# ─── 1) 후보 생성 ─────────────────────────────────────────────────────────────────────────────

GEN_SYSTEM = """당신은 이 발표를 끝까지 들은 심사위원 교수다. 발표자가 **자료의 핵심을 간파했는지** 확인하는 질문을 슬롯마다 하나씩 쓴다.

묻는 것: 핵심 주장이 무엇이고 왜 그런지, 근거가 주장을 어떻게 받치는지, 주장들이 어떻게 이어지는지, 결론이 어디까지 맞고 어디서 안 맞는지, 다른 상황에 옮기면 어떻게 되는지.
묻지 않는 것: 숫자 하나·용어 정의·장 번호·발표 말과 자료의 작은 차이 같은 외우기 확인. 숫자는 결론을 바꿀 때만 재료로 쓴다.
판단 시험: 「잘 답하려면 자료의 핵심 논리를 이해해야 하는가?」 — 외우기만 해도 답할 수 있으면 나쁜 질문이다.

규칙:
- 슬롯의 대상과 패턴을 바꾸지 않는다. 슬롯마다 질문 하나.
- 질문은 해요체, 묻는 것 하나, 100자 안팎(최대 2문장). 물음표는 하나만.
- 「이 조건」「그 결과」처럼 가리키는 말만 쓰지 말고 무엇인지 이름(자료의 고유 개념)을 댄다. 다른 발표에 그대로 쓸 수 있는 뻔한 질문은 쓰지 않는다.
- 자료에 없는 사실·숫자를 전제로 깔지 않는다. 문헌·논문 이름을 지어내지 않는다.
- answer(모범답): 발표자가 그대로 말하면 되는 1~2문장 해요체. 자료 줄에 있는 사실만 쓰고 지어내지 않는다. 「자료는 이렇게 말해요」 같은 머리말·줄 이어 붙이기 금지.
- lines: 모범답의 근거 자료 줄 번호 1~3개 (예: "S3.2"). 줄 번호는 lines 칸에만 쓰고 질문·모범답 문장에는 쓰지 않는다.
- 자료가 그 슬롯의 답을 담지 않으면 {"slot": "T3", "skip": true}.
- why: 이 질문이 이 발표의 핵심을 찌르는 까닭 한 줄, 해요체(「…를 보기 때문이에요」 — 「…합니다」 「…한다」 금지).

출력은 JSON 객체 하나:
{"items": [{"slot": "T1", "question": "…?", "answer": "…요.", "lines": ["S3.2"], "why": "…"}]}"""


#: 시장조사 §5-2 지침 블록을 우리 말투(해요체)로 옮긴 변형 — A/B (`prompt="guide"`). 형태·금지 목록이 더 구체적이다.
GEN_GUIDE_ADDENDUM = """

[형태] 맥락 한 문장(자료의 주장·구절을 짚기) + 질문 한 문장. **질문 문장은 25~70자**(맥락 문장은 따로). 칭찬으로 시작하지 않는다.
[질문의 꼴] 「왜 / 어떻게 이어지나 / 만약 ~라면 / 어디까지 맞나 / 이 근거로 충분한가」 중 하나.
[스스로 시험] ① 자료를 펼쳐 놓고 찾아 읽기만 하면 답할 수 있나? → 그렇다면 다시 쓴다. ② 이 질문을 다른 발표에 그대로 붙여도 말이 되나? → 그렇다면 다시 쓴다.
[금지 — 이런 질문은 버린다] 숫자·용어·장 번호 확인(「12000이 맞나요?」「몇 장에 나왔죠?」) · 발표 말과 자료의 작은 차이 · 한 문장에 질문 두 개 · 대상 없는 지시어(「이 조건은요?」) · 주제 없는 열린 질문(「어떻게 생각하세요?」) · 자료에 없는 사실을 전제로 깐 질문(함정 슬롯이 아닐 때).
숫자는 결론을 바꾸는 근거일 때만 「그 값이 달랐다면 결론이 유지되나」처럼 묻는다."""

#: 역할 나누기 변형(`assign="roles"`) — 슬롯마다 두 모델, 한 호출에 서로 다른 관점 둘 (기술조사 §2-4: 다양성은 온도가 아니라 역할로)
ROLES_ADDENDUM = """

[이번 호출] 슬롯마다 **서로 다른 관점의 후보 두 개**를 쓴다(alt 1·2). 예: 하나는 근거가 주장을 왜 받치는지(보증), 하나는 결론이 기대는 숨은 가정이나 무너지는 조건.
출력: {"items": [{"slot": "T1", "alt": 1, "question": "…", "answer": "…", "lines": ["S3.2"], "why": "…"}, {"slot": "T1", "alt": 2, …}]}"""


#: 패턴 → 잘 쓰는 모델 순 (test 9덱 묶음 전체를 작성 계열 뺀 심판단이 매긴 core): solar4 는 P1 4.76 · P4 4.46 · P10 4.42 · P7 4.22 ·
#: P2 4.17 로 거의 모든 패턴 1등, ax 는 P5(연결) 4.05 · P4 4.13, exaone 은 P7 3.98 · P4 3.93. Mi:dm 은 통과 후보가 적고(35 vs 94) 열린 책 20%.
STRENGTH: dict[str, tuple[str, ...]] = {
    "P1": ("solar4", "ax"), "P2": ("solar4", "exaone"), "P3": ("solar4", "ax"), "P4": ("solar4", "ax"),
    "P5": ("ax", "solar4"), "P6": ("solar4", "ax"), "P7": ("solar4", "exaone"), "P8": ("solar4", "ax"),
    "P9": ("solar4", "ax"), "P10": ("solar4", "ax"),
}


def gen_system(prompt: str = "guide", assign: str = "all") -> str:
    return GEN_SYSTEM + (GEN_GUIDE_ADDENDUM if prompt == "guide" else "") + (ROLES_ADDENDUM if assign in ("roles", "strength") else "")


def gen_prompt(slots: list[ES.Slot], deck: Deck, speech_excerpt: str = "") -> str:
    parts = ["[TASK] qa-ensemble-generate", "", f"## 발표의 핵심 주장\n{deck.thesis}", "", "## 자료 (줄 번호: 원문)",
             ES.deck_block(deck.lines)]
    if speech_excerpt:
        parts += ["", "## 발표 받아쓰기 발췌", speech_excerpt]
    parts += ["", "## 슬롯", *(_slot_line(s, deck) for s in slots)]
    return "\n".join(parts)


def ens_generate(name: str, llm: LLMProvider, slots: list[ES.Slot], deck: Deck, calls: list, *,
                 temperature: float = 0.4, speech_excerpt: str = "", system: str | None = None) -> list[dict]:
    """모델 하나 · 슬롯 묶음 하나 → 원 후보들 (작성 모델 이름을 붙여서)."""
    data = _complete(llm, "generate", calls, system=system or gen_system(), user=gen_prompt(slots, deck, speech_excerpt),
                     temperature=temperature, max_tokens=GEN_MAX_TOKENS)
    ids = {s.id for s in slots}
    out = []
    for it in (data.get("items") or []) if isinstance(data, dict) else []:
        if isinstance(it, dict) and str(it.get("slot")) in ids:
            out.append({**it, "slot": str(it["slot"]), "model": name})
    if calls:
        calls[-1].n_out = len(out)
    return out


# ─── 2) 서로 평가 ─────────────────────────────────────────────────────────────────────────────

PEER_SYSTEM = """당신은 심사위원 동료로서 다른 위원들이 쓴 질문 후보를 채점한다. 작성자는 가려져 있다.
후보마다 1~5 로 채점한다:
- core: 잘 답하려면 자료의 핵심 논리를 이해해야 한다(5) ↔ 자료를 외우기만 해도 답한다·숫자/용어 확인(1)
- grounded: 질문의 전제가 자료와 맞다(5) ↔ 자료에 없는 사실을 전제로 깐다(1)
- specific: 이 발표의 논리에만 맞는 질문이다(5) ↔ 어느 발표에나 쓸 수 있는 뻔한 질문이다(1)
- clear: 무엇을 묻는지 분명하고 답할 수 있다(5) ↔ 가리키는 말이 애매하거나 여러 개를 묻는다(1)
- answer_ok: 모범답이 그 질문의 맞는 답이고 자료와 맞으면 true
자료에 없는 것을 근거로 삼지 않는다. 길이나 말투가 아니라 내용으로 매긴다.
출력은 JSON 객체 하나: {"scores": [{"id": "K01", "core": 4, "grounded": 5, "specific": 4, "clear": 5, "answer_ok": true}]}"""


def peer_prompt(items: list[tuple[str, dict]], deck: Deck, slot_of: dict) -> str:
    parts = ["[TASK] qa-ensemble-peer-review", "", f"## 발표의 핵심 주장\n{deck.thesis}", "", "## 자료",
             ES.deck_block(deck.lines, 180), "", "## 질문 후보"]
    for kid, c in items:
        s = slot_of.get(c["slot"])
        parts.append(f"{kid} [대상 「{s.label if s else '?'}」 · {ES.PATTERNS.get(s.pattern, '') if s else ''}]\n"
                     f"  질문: {c['question']}\n  모범답: {c['answer']}")
    return "\n".join(parts)


def ens_peer_review(name: str, llm: LLMProvider, cands: list[dict], deck: Deck, slot_of: dict, calls: list, *,
                    include_self: bool = False, seed: int = 0) -> dict[str, dict]:
    """평가 모델 하나 → {후보 uid: 점수}. 작성 모델을 가리고(K01…) 순서를 섞는다. 자기 후보는 실험 모드에서만 매긴다."""
    mine = [c for c in cands if include_self or c["model"] != name]
    if not mine:
        return {}
    rng = random.Random(f"{seed}:{name}")
    order = mine[:]
    rng.shuffle(order)
    keyed = [(f"K{i:02d}", c) for i, c in enumerate(order, 1)]
    data = _complete(llm, "peer", calls, system=PEER_SYSTEM, user=peer_prompt(keyed, deck, slot_of),
                     temperature=0.0, max_tokens=PEER_MAX_TOKENS)
    by_k = {k: c for k, c in keyed}
    out: dict[str, dict] = {}
    for row in (data.get("scores") or []) if isinstance(data, dict) else []:
        c = by_k.get(str(row.get("id", "")).strip()) if isinstance(row, dict) else None
        if c is None:
            continue
        sc = {k: _clamp(row.get(k)) for k in PEER_WEIGHTS}
        if any(v is None for v in sc.values()):
            continue
        out[c["uid"]] = {**sc, "answer_ok": bool(row.get("answer_ok", True)), "reviewer": name,
                         "self": c["model"] == name}
    if calls:
        calls[-1].n_in, calls[-1].n_out = len(keyed), len(out)
    return out


def _clamp(v) -> int | None:
    try:
        return max(1, min(5, int(round(float(v)))))
    except (TypeError, ValueError):
        return None


def peer_score(scores: list[dict]) -> float:
    """0~1. 자기 평가는 뺀다. 모범답이 틀렸다는 표가 과반이면 깎는다."""
    rows = [s for s in scores if not s.get("self")]
    if not rows:
        return 0.0
    val = sum(sum(PEER_WEIGHTS[k] * (s[k] - 1) / 4 for k in PEER_WEIGHTS) for s in rows) / len(rows)
    bad = sum(1 for s in rows if not s.get("answer_ok", True))
    return round(val * (0.6 if bad * 2 > len(rows) else 1.0), 4)


# ─── 묶음 ───────────────────────────────────────────────────────────────────────────────────

@dataclass
class Pool:
    slots: list
    candidates: list = field(default_factory=list)    # 거르기 통과 (peer 점수 붙음)
    dropped: list = field(default_factory=list)       # {uid, model, slot, reasons, question}
    calls: list = field(default_factory=list)
    timings: dict = field(default_factory=dict)
    models: list = field(default_factory=list)

    def slot(self, sid: str) -> ES.Slot | None:
        return next((s for s in self.slots if s.id == sid), None)

    def winners(self) -> list[dict]:
        """슬롯마다 1등 — 서로 평가 × 형태(질문 문장 25~70자) (동점이면 모델 이름 순 — 결정적).
        세션 순서는 슬롯 점수(위계 · 패턴) × (0.5 + 서로 평가) × 형태."""
        best: dict[str, dict] = {}
        for c in self.candidates:
            cur = best.get(c["slot"])
            if cur is None or (c["peer"] * form_factor(c), -_model_rank(c["model"])) > \
                    (cur["peer"] * form_factor(cur), -_model_rank(cur["model"])):
                best[c["slot"]] = c
        return sorted(best.values(), key=lambda c: -(self.slot(c["slot"]).score * (0.5 + c["peer"]) * form_factor(c)))

    def to_dict(self) -> dict:
        return {"slots": [s.to_dict() for s in self.slots], "candidates": self.candidates, "dropped": self.dropped,
                "calls": [c.to_dict() for c in self.calls], "timings": self.timings, "models": self.models}


#: `_plain_speech` 가 못 푸는 높임 — 10-17 버그 사냥: 음성 후보 3번+ 질문이 「설명해 주실 수 있을까요?」「거의 설명하지 않으셨어요」 로
#: 그대로 나갔다(CLAUDE §3-1 과도한 경어 금지). 질문 문장만 고친다 — 뜻은 그대로.
_HON_FIX = (
    (re.compile(r"주실\s+수"), "줄 수"), (re.compile(r"않으셨"), "않았"), (re.compile(r"(?<=[가-힣])하셨"), "했"),
    (re.compile(r"보셨"), "봤"), (re.compile(r"주셨"), "줬"), (re.compile(r"(?<=[가-힣])하신(?=\s)"), "한"),
    (re.compile(r"(?<=[가-힣])하실(?=\s)"), "할"),
)


def tidy(c: dict) -> dict:
    """말투만 다듬는다 — 물음 끝 해요체(`_polite_question`), 모범답 해요체(`_polite_statement`), 「…니다요」 같은 섞인 끝.
    내용은 바꾸지 않는다."""
    from .f08_questions import _plain_speech, _polite_question, _polite_statement, _second_person  # noqa: PLC0415
    q = _second_person(_plain_speech(str(c.get("question") or "").strip()))
    a = re.sub(r"(니다|습니다)요(?=[.!]?\s*$|[.!]\s)", r"\1", str(c.get("answer") or "").strip())
    q = re.sub(r"주시겠어요\?", "주세요.", q)
    for pat, rep in _HON_FIX:
        q = pat.sub(rep, q)
    q, a = _strip_line_ids(q), _strip_line_ids(a)
    out = {**c, "question": _polite_question(q), "answer": _polite_statement(_plain_speech(a))}
    if c.get("why"):
        # 「이렇게 물은 까닭」 은 리포트 후보 판에 그대로 보인다 — 「…요구합니다」 같은 합쇼체 · 해라체 끝을 해요체로 (2026-10-17 4단계 보고)
        from ._speech import plain_to_haeyo, to_haeyo  # noqa: PLC0415
        out["why"] = _polite_statement(plain_to_haeyo(to_haeyo(_strip_line_ids(str(c["why"]).strip()))))
    return out


_LINE_ID_PAREN_RE = re.compile(r"\s*[(（\[]\s*S\d{1,3}\.\d{1,3}(?:\s*[~,·–-]\s*S?\d{1,3}(?:\.\d{1,3})?)*\s*[)）\]]")
_LINE_ID_HEAD_RE = re.compile(r"(?<![A-Za-z0-9])S\d{1,3}\.\d{1,3}(?:\s*[~–-]\s*S?\d{1,3}\.\d{1,3})?\s*(?:의|에서|에|은|는|을|를)?\s*")
#: 줄 번호가 주어 · 짝 자리(「S8.19가 말하는 …」「S3.2와 S4.1을 …」)에 선 꼴 — 떼면 조사만 남는다(「가 말하는 …」, 10-17 버그 사냥: 3번 질문으로
#: 그대로 나갔다). 그 장(「자료 8장이」)으로 바꿔 쓴다. 조사는 「장」 의 받침에 맞춘다.
_LINE_ID_SUBJ_RE = re.compile(r"(?<![A-Za-z0-9])S(\d{1,3})\.\d{1,3}(?:\s*[~–-]\s*S?\d{1,3}\.\d{1,3})?(이|가|와|과|으로|로|도|만|까지)(?![가-힣])")
_JANG_JOSA = {"가": "이", "와": "과", "로": "으로"}


def _strip_line_ids(text: str) -> str:
    """프롬프트 줄 번호(「(S3.2)」「S3.4의 차트에서」)를 문장에서 뗀다 — 근거 표시일 뿐 발표자는 모르는 표기다(10-17 dev2: 후보 39·음성 51개가
    이것 하나로 버려졌다). 근거 줄은 lines 칸이 따로 든다. 떼고 나서도 남으면 거르기가 버린다(line_id_leak).
    주어 · 짝 자리의 번호(「S8.19가」)는 떼면 조사만 남으므로 「자료 8장이」 로 바꾼다."""
    t = _LINE_ID_PAREN_RE.sub("", text or "")
    t = _LINE_ID_SUBJ_RE.sub(lambda m: f"자료 {int(m.group(1))}장{_JANG_JOSA.get(m.group(2), m.group(2))}", t)
    t = _LINE_ID_HEAD_RE.sub("", t)
    t = _DANGLING_HEAD_RE.sub("", t)
    return re.sub(r"\s{2,}", " ", t).strip()


#: 떼고 난 문장 맨 앞에 남은 조사 — 모델이 줄 번호 말고 다른 표기(「[S8]가」)를 썼을 때의 안전망
_DANGLING_HEAD_RE = re.compile(r"^(?:가|이|은|는|을|를|의|와|과)\s+")


#: 질문 문장(맥락 문장 뒤 마지막 문장) 길이 — 시장조사 §5-1 B3: 「맥락 한 문장 + 질문 한 문장, 질문 25~70자」 (dev3: 76% 만 지켰다)
FORM_MIN, FORM_MAX = 25, 70


def form_factor(c: dict) -> float:
    body = re.split(r"(?<=[.!])\s+", str(c.get("question") or "").strip())[-1]
    return 1.0 if FORM_MIN <= len(body) <= FORM_MAX else 0.85


def _model_rank(name: str) -> int:
    return MODELS_DEFAULT.index(name) if name in MODELS_DEFAULT else 9


def _chunks(xs: list, n: int) -> list[list]:
    return [xs[i:i + n] for i in range(0, len(xs), n)] or [[]]


def build_pool(graph, slidedoc, claims=None, *, transcript=None, models: list[str] | None = None,
               llms: dict[str, LLMProvider] | None = None, peer: bool = True, peer_self: bool = False,
               slots_limit: int | None = None, temperature: float = 0.4, seed: int = 0,
               slots: list[ES.Slot] | None = None, prompt: str = "guide", assign: str | None = None) -> Pool:
    """자료만으로(transcript 없이도) 후보 묶음을 만든다. llms 를 주면 그걸 쓴다(벤치·테스트)."""
    t0 = time.monotonic()
    deck = Deck.build(graph, slidedoc, claims)
    slots = slots if slots is not None else ES.build_slots(deck.graph, deck.claims, deck.slides, deck.lines, deck.idx,
                                                           limit=slots_limit)
    names = models or model_names()
    llms = llms or {}
    engines = {}
    for n in names:
        try:
            engines[n] = llms.get(n) or make_llm(n)
        except Exception as e:  # noqa: BLE001 — 키 없는 모델은 빠진다
            sys.stderr.write(f"[f08-ens] {n} 을 못 만들어요: {str(e)[:80]}\n")
    pool = Pool(slots=slots, models=list(engines))
    order = list(engines)
    assign = assign or assign_mode()
    if assign == "strength" and len(order) >= 2:
        # 패턴마다 잘하는 두 모델만 (10-17 test 묶음 전체, 남 심판 core — MODEL_LEDGER §4). 둘 다 없으면 있는 모델로 채운다.
        mine = {n: [] for n in order}
        for s in slots:
            pref = [m for m in STRENGTH.get(s.pattern, ()) if m in engines] or order
            for m in (pref + [x for x in order if x not in pref])[:2]:
                mine[m].append(s)
        jobs = [(n, chunk) for n in order for chunk in _chunks(mine[n], SLOTS_PER_CALL) if chunk]
    elif assign == "roles" and len(order) >= 2:
        # 슬롯 i 는 모델 i, i+1 (돌려 가며) — 슬롯마다 두 모델이 서로 다른 관점 둘씩 = 슬롯당 후보 4개, 모델당 호출 1회 남짓
        mine = {n: [s for i, s in enumerate(slots) if n in (order[i % len(order)], order[(i + 1) % len(order)])] for n in order}
        jobs = [(n, chunk) for n in order for chunk in _chunks(mine[n], SLOTS_PER_CALL) if chunk]
    else:
        jobs = [(n, chunk) for n in order for chunk in _chunks(slots, SLOTS_PER_CALL)]
    system = gen_system(prompt, assign)
    raw: list[dict] = []
    with _ai_calllog.feature_scope("F-08-gen"), ThreadPoolExecutor(max_workers=max(1, len(jobs))) as ex:
        futs = [ex.submit(_ai_calllog.carry(ens_generate), n, engines[n], chunk, deck, pool.calls,
                          temperature=temperature, system=system) for n, chunk in jobs]
        for f in as_completed(futs):
            raw.extend(f.result())
    pool.timings["generate_sec"] = round(time.monotonic() - t0, 2)
    slot_of = {s.id: s for s in slots}
    for i, c in enumerate(sorted(raw, key=lambda c: (c["slot"], _model_rank(c["model"])))):
        c = tidy({**c, "uid": f"{c['model']}:{c['slot']}:{i}"})
        s = slot_of[c["slot"]]
        ok, why = ES.check_candidate(c, s, lines_by_id=deck.lines_by_id, idx=deck.idx, deck_tokens=deck.deck_tokens,
                                     sources=deck.sources)
        if ok is None:
            pool.dropped.append({"uid": c["uid"], "model": c["model"], "slot": c["slot"], "reasons": why,
                                 "question": str(c.get("question") or "")[:200], "answer": str(c.get("answer") or "")[:200]})
        else:
            pool.candidates.append({**ok, "node_id": s.node_id, "label": s.label, "pattern": s.pattern,
                                    "angle": s.angle, "trap": s.trap, "peer": 0.0, "peer_scores": []})
    _dedupe(pool)
    # 생성 호출이 하나도 성공 못 한 모델은 서로 평가에서 뺀다 — 넘어진 엔드포인트를 또 기다리지 않는다
    alive = {c.model for c in pool.calls if c.ok}
    tried = {c.model for c in pool.calls}
    dead = [n for n in engines if getattr(engines[n], "name", n) in tried and getattr(engines[n], "name", n) not in alive]
    for n in dead:
        sys.stderr.write(f"[f08-ens] {n} 생성이 다 실패 — 서로 평가에서 뺀다\n")
        engines.pop(n)
    pool.timings["dead_models"] = dead
    if peer and pool.candidates and engines:
        t1 = time.monotonic()
        with _ai_calllog.feature_scope("F-08-peer"), ThreadPoolExecutor(max_workers=len(engines)) as ex:
            futs = [ex.submit(_ai_calllog.carry(ens_peer_review), n, engines[n], pool.candidates, deck, slot_of,
                              pool.calls, include_self=peer_self, seed=seed) for n in engines]
            results = [f.result() for f in futs]
        for c in pool.candidates:
            c["peer_scores"] = [r[c["uid"]] for r in results if c["uid"] in r]
            c["peer"] = peer_score(c["peer_scores"])
        pool.timings["peer_sec"] = round(time.monotonic() - t1, 2)
    pool.timings["total_sec"] = round(time.monotonic() - t0, 2)
    return pool


#: 같은 슬롯 안에서 거의 같은 질문(낱말 겹침)은 하나만 — 서로 평가 표를 나누지 않게
DUP_OVERLAP = 0.8


def _dedupe(pool: Pool) -> None:
    kept: list[dict] = []
    for c in pool.candidates:
        twin = next((k for k in kept if k["slot"] == c["slot"]
                     and ES.question_tokens_overlap(k["question"], c["question"]) >= DUP_OVERLAP), None)
        if twin is not None:
            twin.setdefault("twins", []).append(c["model"])
            pool.dropped.append({"uid": c["uid"], "model": c["model"], "slot": c["slot"], "reasons": ["duplicate"],
                                 "question": c["question"][:200], "answer": c["answer"][:200]})
            continue
        kept.append(c)
    pool.candidates = kept


# ─── 3) 발표 끝 — 1·2번 (LLM 없음) ─────────────────────────────────────────────────────────────

#: 발표에서 이미 잘 설명한 슬롯을 뒤로 미는 무게 (모범답 낱말이 그 장 발화에 이만큼 나왔으면 「잘 설명함」)
WELL_SAID = 0.7


def said_share(c: dict, speech_of: dict[int, str]) -> float:
    speech = " ".join(speech_of.get(n, "") for n in ([c.get("slide_no")] if c.get("slide_no") else []))
    return ES.speech_cover(c.get("answer", ""), speech) if speech.strip() else 0.0


def pick_opening(pool: Pool, transcript=None, n: int = 2) -> list[dict]:
    """
    묶음에서 1·2번. 슬롯 점수 × (0.5 + 서로 평가) × (잘 설명한 곳이면 0.6). 제약: 다른 노드 · 다른 장 · 1·2번 중 P1/P2 하나 이상.
    LLM 을 부르지 않는다 — 발표 끝에서 바로 나와야 한다 (PLAN p95 ≤ 2초).
    """
    speech_of = _speech_of(transcript)
    many_slides = len({n for s in pool.slots for n in s.slides}) > 4
    ranked = []
    for c in pool.winners():
        s = pool.slot(c["slot"])
        share = said_share(c, speech_of)
        ranked.append((s.score * (0.5 + c["peer"]) * (0.6 if share >= WELL_SAID else 1.0), c, share))
    ranked.sort(key=lambda x: -x[0])
    picked: list[dict] = []
    for _, c, share in ranked:
        home = (pool.slot(c["slot"]).slides or [c.get("slide_no")])[0]
        if any(p["node_id"] == c["node_id"] or (many_slides and p["home"] == home) for p in picked):
            continue                        # 다른 노드 · (장이 넉넉하면) 다른 장 — 작은 덱(≤4장)에서 장 제약은 1·2번을 잎으로 민다
        c = {**c, "home": home}
        picked.append({**c, "said_share": round(share, 2)})
        if len(picked) >= n:
            break
    if picked and not any(p["pattern"] in ("P1", "P2") for p in picked):
        core = next((c for _, c, sh in ranked if c["pattern"] in ("P1", "P2")
                     and all(c["node_id"] != p["node_id"] for p in picked[:1])), None)
        if core is not None:
            picked[-1] = {**core, "said_share": round(said_share(core, speech_of), 2)}
    return picked


DEFENSIVE = ("P7", "P9")


def pick_session(pool: Pool, transcript=None, n: int = 5) -> list[dict]:
    """
    한 세션 몫(기본 5) — 1·2번(`pick_opening`) 뒤에 묶음 순서로 채우되 (노드, 각도) 겹침 없이, 방어형(P7·P9) ≤ 2,
    확장형(P10) ≥ 1 (시장조사 §4 · Kanze 2018: 방어형만 몰면 답이 방어로만 간다). 3번부터는 실제로는 음성 후보가 먼저다 —
    이 목록은 음성이 늦을 때 대신 낼 순서이자 리포트 후보 판의 기본 순서다.
    """
    out = pick_opening(pool, transcript)
    seen = {(c["node_id"], c["angle"]) for c in out}
    for c in pool.winners():
        if len(out) >= n:
            break
        if any(c["uid"] == o["uid"] for o in out) or (c["node_id"], c["angle"]) in seen:
            continue
        if c["pattern"] in DEFENSIVE and sum(1 for o in out if o["pattern"] in DEFENSIVE) >= 2:
            continue
        out.append(c)
        seen.add((c["node_id"], c["angle"]))
    if len(out) >= 3 and not any(o["pattern"] == "P10" for o in out):
        p10 = next((c for c in pool.winners() if c["pattern"] == "P10"), None)
        if p10 is not None:
            out[-1] = p10
    return out


def _speech_of(transcript) -> dict[int, str]:
    if transcript is None:
        return {}
    t = transcript if isinstance(transcript, Transcript) else Transcript.from_dict(transcript)
    return {s.slide_no: t.text_for_slide(s.slide_no) for s in t.by_slide}


# ─── 4) 3번 이후 — 발표 음성 · 앞 답 ─────────────────────────────────────────────────────────

VOICE_SYSTEM = """당신은 이 발표를 끝까지 듣고 앞 질문 두 개의 답까지 들은 심사위원 교수다. 다음 질문 후보를 1~2개 쓴다.
재료는 「신호」다 — 발표자가 결론만 말하고 이유를 건너뛴 곳, 흐리게 지나간 곳, 핵심과 어긋나게 설명한 곳, 앞 답에서 이해가 약했던 곳.
- 후보마다 신호 하나를 고르고(signal: "V2"), 그 신호가 드러낸 **핵심 논리의 빈틈**을 묻는다.
- 숫자·낱말이 자료와 조금 다른 것을 묻지 않는다. 장 번호·용어 정의를 묻지 않는다. 외우기로 답할 수 있는 질문은 안 된다.
- 앞 답이 약했으면 같은 것을 다시 묻지 말고 한 걸음 더 깊이(왜) 또는 옆으로(이어진 주장) 또는 바로잡게 묻는다.
- 질문은 해요체 한 문장, 묻는 것 하나, 100자 안팎. 가리키는 말만 쓰지 말고 자료의 개념 이름을 댄다.
- answer(모범답): 자료 줄에 있는 사실로 1~2문장 해요체. lines: 근거 자료 줄 번호 1~3개.
- signal 칸에는 아래 「신호」 목록에 **실제로 있는** 번호만 쓴다.
why 는 해요체 한 줄.
출력은 JSON 객체 하나: {"items": [{"signal": "<신호 번호>", "question": "…?", "answer": "…요.", "lines": ["S3.2"], "why": "…"}]}"""

PICK_SYSTEM = """당신은 Q&A 진행을 맡은 심사위원장이다. 다음에 물을 질문 하나를 후보에서 고른다. 작성자는 가려져 있다.
고르는 기준(순서대로): ① 발표자가 자료의 핵심 논리를 이해했는지 드러나는가 ② 발표와 앞 답에서 드러난 빈틈을 찌르는가 ③ 이미 물은 것과 겹치지 않는가 ④ 분명하고 답할 수 있는가.
숫자·용어를 외웠는지 묻는 후보는 고르지 않는다.
출력은 JSON 객체 하나: {"pick": "C3", "reason": "한 줄 이유 (해요체)"}"""


def voice_prompt(signals: list[dict], deck: Deck, asked: list[dict], transcript_text: str) -> str:
    parts = ["[TASK] qa-ensemble-voice", "", f"## 발표의 핵심 주장\n{deck.thesis}", "", "## 자료", ES.deck_block(deck.lines, 180),
             "", "## 발표 받아쓰기 (앞부분)", transcript_text[:2400], "", "## 이미 물은 질문과 답"]
    for a in asked:
        parts.append(f"- Q: {a.get('question', '')}\n  A: {(a.get('answer') or '')[:240]}\n  판정: {a.get('verdict', '?')}"
                     + (f" · 이해 상태: {a['state']}" if a.get("state") else "")
                     + (f" · 빠진 고리: {a['skipped'][:80]}" if a.get("skipped") else ""))
    parts += ["", "## 신호"]
    for s in signals:
        parts.append(f"{s['id']} [{s['kind']}] 「{s['label']}」({s['slide_no']}장) — {s['note']}"
                     + (f" · 자료 줄 {s['deck_line']}: {s['deck_text'][:120]}" if s.get("deck_line") else "")
                     + (f" · 발화: «{s['speech_quote']}»" if s.get("speech_quote") else ""))
    return "\n".join(parts)


def ens_voice(name: str, llm: LLMProvider, signals: list[dict], deck: Deck, asked: list[dict], transcript_text: str,
              calls: list, temperature: float = 0.4) -> list[dict]:
    data = _complete(llm, "voice", calls, system=VOICE_SYSTEM, user=voice_prompt(signals, deck, asked, transcript_text),
                     temperature=temperature, max_tokens=GEN_MAX_TOKENS)
    ids = {s["id"]: s for s in signals}
    out = []
    for it in (data.get("items") or []) if isinstance(data, dict) else []:
        if not isinstance(it, dict):
            continue
        m = re.search(r"V\d+", str(it.get("signal") or ""))
        sid = m.group(0) if m else ""
        if sid not in ids and len(signals) == 1:
            sid = signals[0]["id"]          # 신호가 하나뿐이면 그것 (10-17: 예시의 「V2」 를 네 모델이 다 베꼈다)
        if sid in ids:
            out.append({**it, "signal": sid, "model": name})
    if calls:
        calls[-1].n_out = len(out)
    return out


def ens_pick(name: str, llm: LLMProvider, options: list[dict], asked: list[dict], calls: list, seed: int = 0) -> dict:
    """최종 선택 — 작성자 가림·순서 섞음. {"uid", "reason"} 또는 {} (실패면 호출자가 점수 1등을 낸다)."""
    if not options:
        return {}
    order = options[:]
    random.Random(f"pick:{seed}:{len(asked)}").shuffle(order)
    keyed = [(f"C{i}", c) for i, c in enumerate(order, 1)]
    lines = ["[TASK] qa-ensemble-pick", "", "## 이미 물은 질문"]
    lines += [f"- {a.get('question', '')} (판정 {a.get('verdict', '?')})" for a in asked] or ["- (없음)"]
    lines += ["", "## 후보"]
    lines += [f"{k}: {c['question']}" + (f"  [신호: {c.get('signal_note', '')}]" if c.get("signal_note") else "")
              for k, c in keyed]
    data = _complete(llm, "pick", calls, system=PICK_SYSTEM, user="\n".join(lines), temperature=0.0, max_tokens=400)
    pick = str((data or {}).get("pick", "")).strip()
    c = dict(keyed).get(pick)
    return {"uid": c["uid"], "reason": str(data.get("reason", ""))[:160]} if c else {}


@dataclass
class VoiceRound:
    signals: list
    candidates: list
    dropped: list
    calls: list
    sec: float


def voice_round(pool: Pool, graph, slidedoc, transcript, *, alignment=None, asked: list[dict] | None = None,
                claims=None, models: list[str] | None = None, llms: dict | None = None,
                temperature: float = 0.4) -> VoiceRound:
    """발표 받아쓰기 + 앞 답 → 네 모델이 3번+ 후보. 신호가 없으면 빈 묶음(호출 안 함)."""
    t0 = time.monotonic()
    deck = Deck.build(graph, slidedoc, claims)
    speech_of = _speech_of(transcript)
    from .contracts import AlignmentDoc  # noqa: PLC0415
    al = alignment if alignment is None or not isinstance(alignment, dict) else AlignmentDoc.from_dict(alignment)
    signals = ES.voice_signals(deck.graph, deck.slides, speech_of, al, asked or [], deck.lines)
    if not signals:
        return VoiceRound([], [], [], [], 0.0)
    text = " ".join(speech_of.get(n, "") for n in sorted(speech_of))
    names = models or model_names()
    llms = llms or {}
    calls: list = []
    raw: list[dict] = []
    with _ai_calllog.feature_scope("F-08-voice"), ThreadPoolExecutor(max_workers=len(names)) as ex:
        futs = [ex.submit(_ai_calllog.carry(ens_voice), n, llms.get(n) or make_llm(n), signals, deck, asked or [], text,
                          calls, temperature) for n in names]
        for f in as_completed(futs):
            raw.extend(f.result())
    sig_of = {s["id"]: s for s in signals}
    by_id = {n.id: n for n in deck.graph.nodes}
    speech_vocab = ES._tokens(text)          # 발표에서 한 말 — 음성 질문·모범답은 발화의 낱말을 쓴다
    from ._spoken import spoken_numbers  # noqa: PLC0415
    spoken = spoken_numbers(text)            # 「이십구 퍼센트」→「29%」 — 발화의 수도 출처다
    kept, dropped = [], []
    for i, c in enumerate(raw):
        sig = sig_of[c["signal"]]
        node = by_id.get(sig["node_id"])
        slot = ES.Slot(id="V", node_id=sig["node_id"], label=sig["label"], kind=sig.get("node_kind", ""), pattern="voice",
                       slides=list(node.slide_nos or []) if node else [],
                       lines=[sig["deck_line"]] if sig.get("deck_line") else [],
                       partner_label=" ".join(sig.get("neighbors") or []))
        c = tidy({**c, "uid": f"{c['model']}:{c['signal']}:v{i}"})
        ok, why = ES.check_candidate(c, slot, lines_by_id=deck.lines_by_id, idx=deck.idx, deck_tokens=deck.deck_tokens,
                                     sources=deck.sources + [text, spoken], extra_vocab=speech_vocab)
        if any(ES.question_tokens_overlap(c.get("question", ""), a.get("question", "")) >= DUP_OVERLAP for a in asked or []):
            why = [*why, "repeats_asked"]
            ok = None
        if ok is None:
            dropped.append({"uid": c["uid"], "model": c["model"], "signal": c["signal"], "reasons": why,
                            "question": str(c.get("question") or "")[:200]})
            continue
        kept.append({**ok, "node_id": sig["node_id"], "label": sig["label"], "pattern": "voice", "angle": "voice",
                     "signal_kind": sig["kind"], "signal_note": sig["note"], "signal_quote": sig.get("speech_quote", ""),
                     "peer": 0.0, "peer_scores": []})
    return VoiceRound(signals, kept, dropped, calls, round(time.monotonic() - t0, 2))


#: 최종 선택(3번+)을 기다리는 상한 — 화면의 다음 질문 요청 상한(6초)보다 넉넉히 짧게. 0 이면 끝까지 기다린다(벤치).
PICK_WAIT_SEC = float(os.environ.get("QA_ENS_PICK_WAIT_SEC", "3.5"))
_PICK_EXEC = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ens-pick")


def choose_next(pool: Pool, vr: VoiceRound | None, asked: list[dict], *, picker: str | None = None,
                llm: LLMProvider | None = None, seed: int = 0, calls: list | None = None,
                pick_wait: float | None = None) -> dict:
    """
    다음 질문 하나. 음성 후보가 있으면 그 후보 + 묶음의 남은 상위 2개를 최종 선택 모델이 고른다(이유 한 줄).
    음성 후보가 없거나 선택이 실패하면 묶음의 남은 1등(「묶음에서 대신 냄」, substituted=True).
    """
    # 이미 물은 노드 + 이해했다고 본 노드(understood)는 다시 고르지 않는다 (노드 이해 상태 — 2026-10-17 5단계)
    asked_nodes = {a.get("node_id") for a in asked}
    asked_q = [a.get("question", "") for a in asked]
    rest = [c for c in pool.winners() if c["node_id"] not in asked_nodes
            and all(ES.question_tokens_overlap(c["question"], q) < DUP_OVERLAP for q in asked_q)]
    voice = [c for c in (vr.candidates if vr else []) if all(ES.question_tokens_overlap(c["question"], q) < DUP_OVERLAP
                                                                for q in asked_q)]
    if not voice:
        return {**rest[0], "substituted": True, "pick_reason": "음성 후보가 아직 없어 묶음에서 냈어요"} if rest else {}
    options = voice + rest[:2]
    calls = calls if calls is not None else []
    name = picker or picker_name()

    def run_pick() -> dict:
        with _ai_calllog.feature_scope("F-08-pick"):
            return ens_pick(name, llm or make_llm(name), options, asked, calls, seed)

    # 최종 선택은 상한 안에서만 기다린다 — 화면은 다음 질문 요청을 6초(ENSEMBLE_NEXT_TIMEOUT_MS)만 기다리고 준비한 질문으로 간다.
    # 10-17 버그 사냥: 선택 모델이 21.6초 · 44초 걸린 판이 있었다 — 화면은 준비한 질문을 냈는데 서버는 늦게 고른 질문을 판(리포트)에
    # 「이번에 물은 질문」 으로 남겼다. 늦으면 음성 후보 1등을 낸다(선택은 뒤에서 마저 끝나도 쓰지 않는다).
    wait = PICK_WAIT_SEC if pick_wait is None else pick_wait
    if wait and wait > 0:
        fut = _PICK_EXEC.submit(_ai_calllog.carry(run_pick, "F-08-pick"))
        try:
            got = fut.result(timeout=wait)
        except Exception as e:  # noqa: BLE001 — 늦음 · 실패 모두 1등으로
            sys.stderr.write(f"[f08-ens] 최종 선택 {wait:.1f}초 안에 안 옴 — 음성 후보 1등으로: {type(e).__name__}\n")
            got = {"late": True}
    else:
        got = run_pick()
    c = next((o for o in options if o["uid"] == got.get("uid")), None)
    if c is None:
        c = max(voice, key=lambda o: o.get("peer", 0))
        why = "선택 모델이 늦어 음성 후보 1등을 냈어요" if got.get("late") else "선택 모델이 답하지 않아 첫 음성 후보를 냈어요"
        return {**c, "substituted": False, "pick_reason": why, "pick_failed": True}
    return {**c, "substituted": False, "pick_reason": got.get("reason", "")}


def plan_total(time_left_sec: float, asked: int, pool: Pool, signals: list[dict], *, per_question_sec: float = 75.0,
               lo: int = 3, hi: int = 6) -> int:
    """전체 질문 수 (+@): 남은 시간 · 안 물은 핵심 슬롯 · 남은 신호로. 3~6."""
    by_time = asked + int(max(0.0, time_left_sec) // per_question_sec)
    core_left = sum(1 for c in pool.winners() if c["pattern"] in ("P1", "P2", "P5", "P7"))
    want = max(lo, min(hi, 2 + len(signals) + (1 if core_left > 2 else 0)))
    return max(lo, min(hi, min(want, max(by_time, lo))))


# ─── Question 으로 ───────────────────────────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"[^0-9a-z가-힣]+")


def to_question(c: dict, i: int, graph=None) -> Question:
    """후보 → contracts.Question (F-09 판정·힌트 사다리가 그대로 읽는다). 모범답은 자료 줄로 받친 깨끗한 문장이라 골자 바닥을 쓴다."""
    tp = None
    if c.get("pattern") == "P9" and c.get("trap"):
        tp = TrapPremise.from_dict(c["trap"])
    checks = ["ensemble", f"by:{c.get('model', '?')}", f"pattern:{c.get('pattern', '')}"]
    if not c.get("answer_inference"):
        checks.append("gist_polished")     # 절마다 자료로 받쳐진 모범답 — 골자 바닥(F-09)을 쓴다. 추론이 든 답은 F-09 가 스스로 대조한다
    if c.get("signal_kind"):
        checks.append(f"signal:{c['signal_kind']}")
    quote = c.get("quote") or ""
    slide = int(c.get("slide_no") or 0)
    source = {"voice": "under_spoken"}.get(c.get("pattern", ""), "core_weight")
    return Question(
        id=f"e{i:02d}-{_SLUG_RE.sub('-', (c.get('node_id') or 'q').lower())[:24]}",
        node_id=c.get("node_id", ""), label=c.get("label", ""), question=c["question"], why=str(c.get("why") or "")[:160],
        severity=1 if c.get("pattern") in ("P1", "P2", "P9") else 2, trap=tp is not None, source=source,
        slide_nos=[slide] if slide else [], answer_gist=c.get("answer", ""),
        evidence_slide_no=slide, evidence_quote=quote[:180],
        basis=QuestionBasis(source=source, slot=c.get("slot", ""), rank=i,
                            evidence=[ClaimQuote(slide, quote[:180])] if quote else [], checks=checks),
        trap_premise=tp,
    )


__all__ = ["enabled", "model_names", "picker_name", "build_pool", "pick_opening", "voice_round", "choose_next",
           "plan_total", "to_question", "pick_session", "Pool", "VoiceRound", "Deck", "peer_score"]


# ─── 1단계: 모범답 정리 (지금 방식의 질문에도 쓴다 — f08_questions.build_questions 끝) ──────────────────────

GIST_SYSTEM = """당신은 발표 코치다. 질문마다 발표자가 **그대로 말하면 되는 모범답**을 다시 쓴다.
- 1~2문장, 해요체. 질문에 바로 답한다. 「자료는 이렇게 말해요」 같은 머리말, 「·」「/」로 줄 이어 붙이기, 장 번호 나열, 표 머리줄 옮기기 금지.
- 주어진 자료 줄에 있는 사실만 쓴다. 숫자는 자료 줄의 숫자만. 자료 줄로 답할 수 없으면 {"id": "q01", "skip": true}.
- lines: 근거로 쓴 자료 줄 번호 1~2개. 줄 번호는 lines 칸에만 — 모범답 문장에는 쓰지 않는다.
- 질문이 이미 인용한 주장을 그대로 되풀이하는 것은 답이 아니다 — 그 주장을 받치는 근거·이유를 쓴다.
출력은 JSON 객체 하나: {"items": [{"id": "q01", "answer": "…요.", "lines": ["S3.2"]}]}"""

_DIRTY_GIST_RE = re.compile(r"자료는 이렇게 말해요\s*—|\s·\s|/.*/|한계\s*:|^[1-9][.)]?\s(?=[가-힣]{2,})")
#: 코드가 정리할 때 버리는 줄 머리 — 글머리 번호(「1 군당 셀이」), 「제목: 」 꼬리표
_LINE_HEAD_RE = re.compile(r"^(?:\d{1,2}[.)]?\s+|[가-힣A-Za-z]{1,8}\s*:\s+)")


def dirty_gist(q: Question) -> bool:
    """지저분한 모범답 — 자료 줄을 이어 붙인 틀(「자료는 이렇게 말해요 — A · B」), 「·」「/」 잇기, 「한계:」 꼬리, 글머리 번호."""
    g = (q.answer_gist or "").strip()
    return bool(g) and bool(_DIRTY_GIST_RE.search(g))


def _gist_targets(questions: list[Question]) -> list[Question]:
    return [q for q in questions if dirty_gist(q) and not q.trap and q.source != "contradiction"]


def _letter_spaced(line: str) -> bool:
    from .f08_questions import _letter_spaced as ls  # noqa: PLC0415
    return ls(line)


def _spaced_out(line: str) -> bool:
    """글자마다 띄운 표지 줄 — 「경 영 정 보 학 과 · 2 0 2 6 . 1 0 . 6」. 한 글자 낱말이 절반 넘으면."""
    words = [w for w in (line or "").split() if w not in ("·", "|", "/")]
    return len(words) >= 6 and sum(1 for w in words if len(w) == 1) * 2 > len(words)


def _tidy_line(line: str) -> str:
    return _LINE_HEAD_RE.sub("", (line or "").strip()).rstrip(" .")


def code_gist(q: Question, deck: Deck) -> str:
    """LLM 이 못 고친 골자 — 근거 장의 자료 줄 **하나**로 「자료 N장은 「…」라고 해요.」 (표 머리줄·글머리·이어 붙이기 없이)."""
    from ._traps import _quoted_josa  # noqa: PLC0415
    nos = q.slide_nos or ([q.evidence_slide_no] if q.evidence_slide_no else [])
    want = ES._tokens(" ".join([q.question, q.label, q.evidence_quote]))
    qtok = ES._tokens(q.question)
    # 질문이 이미 인용한 줄(주장 문장)을 되읊으면 답이 아니다 — 「이 주장을 받치는 근거는?」 에 그 주장을 돌려줬다 (10-17 dev3 partial 55)
    cands = [ln for ln in deck.lines if ln.slide_no in nos and " / " not in ln.text and len(_tidy_line(ln.text)) >= 12
             and not ES._CITATION_RE.search(ln.text) and not _letter_spaced(ln.text) and not _spaced_out(ln.text)
             and len(ES._tokens(ln.text) - qtok) >= 2]
    if not cands:
        return ""
    best = max(cands, key=lambda ln: len(want & ES._tokens(ln.text)))
    text = _tidy_line(best.text)
    return f"자료 {best.slide_no}장은 「{text}」{_quoted_josa(text, '이라고', '라고')} 해요."


def polish_gists(questions: list[Question], deck: Deck, llm: LLMProvider, calls: list | None = None) -> dict:
    """
    지저분한 모범답만 골라 **한 번** 불러 다시 쓴다(`F-08-gist`). 통과(말투·숫자·자료 밖 낱말·절마다 자료 대조)하면 바꾸고 `gist_polished`,
    못 하면 코드가 자료 줄 하나로 정리하고 `gist_evidence_line`(틀 골자 — F-09 는 골자 바닥을 쓰지 않는다). 질문 문장은 안 바꾼다.
    → {"targets": n, "polished": n, "code": n, "kept": n}
    """
    calls = calls if calls is not None else []
    targets = _gist_targets(questions)
    stat = {"targets": len(targets), "polished": 0, "code": 0, "kept": 0}
    if not targets:
        return stat
    keyed = {f"q{i:02d}": q for i, q in enumerate(targets, 1)}
    nos = sorted({n for q in targets for n in (q.slide_nos or [q.evidence_slide_no]) if n})
    parts = ["[TASK] qa-gist-polish", "", "## 자료 줄", ES.deck_block([ln for ln in deck.lines if ln.slide_no in nos], 220),
             "", "## 질문"]
    parts += [f"{k}: {q.question}  (근거 장 {','.join(map(str, q.slide_nos))})" for k, q in keyed.items()]
    with _ai_calllog.feature_scope("F-08-gist"):
        data = _complete(llm, "gist", calls, system=GIST_SYSTEM, user="\n".join(parts), temperature=0.2, max_tokens=1500)
    got = {str(it.get("id")): it for it in (data.get("items") or []) if isinstance(it, dict)} if isinstance(data, dict) else {}
    for k, q in keyed.items():
        it = got.get(k) or {}
        raw_a = str(it.get("answer") or "")
        # 모범답에 줄 번호를 썼으면 떼지 않고 버린다 — 떼면 「자료 줄 와 인용되어」 처럼 문장이 부서진다 (10-17 dev3)
        a = tidy({"question": q.question, "answer": raw_a})["answer"] if not it.get("skip") and not ES.LINE_ID_RE.search(raw_a) else ""
        refs = [r for r in (it.get("lines") or []) if isinstance(r, str) and r in deck.lines_by_id]
        ok = bool(a) and _gist_ok(a, deck) and bool(refs)
        checks = q.basis.checks if q.basis is not None else None
        if ok:
            q.answer_gist, q.answer_gist_parts = a, []
            ln = deck.lines_by_id[refs[0]]
            q.evidence_slide_no, q.evidence_quote = ln.slide_no, ln.text[:180]
            if checks is not None:
                if not grounding.supported_sentences(a, deck.idx)[1]:
                    checks.append("gist_polished")         # 절마다 자료로 받쳐짐 — 골자 바닥
                else:
                    # 자료 줄을 잇는 추론이 든 깨끗한 모범답 — 더는 틀 자리 표시가 아니다. 보통 LLM 골자처럼 F-09 가 스스로 대조한다
                    checks[:] = [c for c in checks if c not in ("gist_template", "fallback_template")] + ["gist_polished_inference"]
            stat["polished"] += 1
            continue
        fixed = code_gist(q, deck)
        if fixed:
            q.answer_gist, q.answer_gist_parts = fixed, []
            if checks is not None:
                checks.append("gist_evidence_line")
            stat["code"] += 1
        else:
            stat["kept"] += 1
    return stat


def _gist_ok(a: str, deck: Deck) -> bool:
    from ._speech import ungrounded_numbers  # noqa: PLC0415
    if _DIRTY_GIST_RE.search(a) or not re.search(r"(요|다)[.!]?\s*$", a) or len(a) < 12:
        return False
    if len(grounding.sentences(a)) > 2 or ungrounded_numbers(a, deck.sources):
        return False
    if len(grounding.unknown_terms(a, deck.idx)) >= 2 or grounding.gist_problems(a, deck.idx):
        return False
    return not ES.LINE_ID_RE.search(a)
