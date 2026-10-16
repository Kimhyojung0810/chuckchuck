"""
네 모델 Q&A(f08_ensemble)의 **코드 쪽** — 그래프 → 질문 대상 지도(슬롯), 후보 거르기, 발표 음성 신호. LLM 을 부르지 않는다.

계획: docs/qa-ensemble/PLAN.md §0-1 · 2a단계.

- 「무엇을 물을지」는 코드가 정한다(슬롯 = 그래프의 노드 × 패턴 P1~P10). 모델은 슬롯마다 문장만 쓴다.
- §0-1 핵심 원칙: 자료의 **핵심을 간파했는지** 묻는다. 숫자 하나·용어 정의·장 번호·말과 자료의 작은 차이 같은 미시 확인은 묻지 않는다.
  그래서 거르기(`check_candidate`)가 미시 확인(`micro`)·뻔한 질문(`generic`)·가리킬 게 없는 지시어(`vague_deixis`)를 **버린다**
  — 템플릿으로 바꾸지 않는다(버리고 같은 슬롯의 다른 모델 후보를 쓴다).
- 3번 이후 신호도 숫자 차이가 아니라 「결론만 말하고 이유를 건너뜀 · 흐림 · 핵심과 어긋난 설명 · 앞 답의 약점」 이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import _grounding as grounding
from . import _traps as traps
from ._deck_lines import read_lines
from ._evidence import clean_slide_text
from ._match import norm_tokens
from ._speech import to_haeyo, ungrounded_numbers

# ─── 패턴 (PLAN 2a 층 1) ─────────────────────────────────────────────────────────────────────

PATTERNS: dict[str, str] = {
    "P1": "핵심 주장 — 발표의 결론이 무엇이고 왜 그 결론인지",
    "P2": "근거 충분성 — 이 근거로 주장이 충분한지, 다른 해석은 없는지",
    "P3": "빈 고리 — 근거가 안 보이는 주장을 무엇이 받치는지",
    "P4": "결론을 좌우하는 조건 — 그 조건이 바뀌면 결론이 어떻게 달라지는지 (숫자 자체를 확인하지 않는다)",
    "P5": "연결 — 두 주장이 어떻게 이어지는지 (인과·순서)",
    "P6": "방법 선택 — 왜 이 방법·설계를 골랐고 대안과 견주면 어떤지",
    "P7": "한계·반례 — 결론이 어디까지 맞고 어디서 안 맞는지",
    "P8": "개념의 역할 — 이 개념이 결론에서 왜 중요한지 (정의를 묻지 않는다)",
    "P9": "함정 — 자료와 어긋난 전제를 짚어 내는지",
    "P10": "옮겨 쓰기·다음 단계 — 이 결론을 실제로 쓰거나 다음 연구로 이으면 어떻게 되는지",
}
#: 패턴 → 화면·장부에 쓰는 각도 이름 (주장·근거·한계·응용·함정)
ANGLE_OF = {"P1": "claim", "P2": "evidence", "P3": "evidence", "P4": "evidence", "P5": "claim", "P6": "evidence",
            "P7": "limit", "P8": "claim", "P9": "trap", "P10": "application"}
#: 패턴 무게 — 핵심을 묻는 패턴이 앞이다 (§0-1). 실험으로 고친다 (QA_BENCH_LEDGER).
PATTERN_WEIGHT = {"P1": 1.0, "P2": 0.95, "P5": 0.9, "P7": 0.9, "P3": 0.85, "P6": 0.85, "P10": 0.8, "P9": 0.75,
                  "P4": 0.7, "P8": 0.5}
KIND_WEIGHT = {"thesis": 1.0, "claim": 0.8}

_METHOD_RE = re.compile(r"설계|방법|검정|모형|모델링|분석|실험|측정|배정|표본|비교군|대조군|통제|코호트|회귀|설문|무작위|맹검|프로토콜|기법|알고리즘")
_LIMIT_RE = re.compile(r"한계|제약|다만|주의|아직|못\s?했|얇다|부족|일반화|다를\s?수|limitation|caveat", re.I)
_NEXT_RE = re.compile(r"다음\s*단계|향후|계획|제안|적용|활용|권고|시사점|next|future", re.I)

_CITATION_RE = re.compile(r"et\s*al\.?|\(\d{4}[a-z]?\)|^[A-Z][a-z]+\s*\(?\d{4}")
#: 덱 크기에 따른 슬롯 수 — 네 모델 × 슬롯 = 후보 수. 많으면 서로 평가 프롬프트가 길어진다.
SLOTS_MIN, SLOTS_MAX = 6, 10
SLOTS_PER_NODE = 2


@dataclass
class DeckLine:
    id: str          # "S3.2"
    slide_no: int
    text: str


@dataclass
class Slot:
    id: str                      # "T1"
    node_id: str
    label: str
    kind: str                    # thesis · claim · concept · ""
    pattern: str                 # P1~P10
    slides: list[int] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)       # 관련 자료 줄 id
    score: float = 0.0
    partner_id: str = ""                                  # P5 의 두 번째 노드
    partner_label: str = ""
    trap: dict | None = None                              # P9 — TrapPremise.to_dict()

    @property
    def angle(self) -> str:
        return ANGLE_OF.get(self.pattern, "claim")

    def to_dict(self) -> dict:
        return {"id": self.id, "node_id": self.node_id, "label": self.label, "kind": self.kind, "pattern": self.pattern,
                "pattern_desc": PATTERNS[self.pattern], "angle": self.angle, "slides": list(self.slides),
                "lines": list(self.lines), "score": round(self.score, 3), "partner_id": self.partner_id,
                "partner_label": self.partner_label, "trap": self.trap}


# ─── 자료 줄 ────────────────────────────────────────────────────────────────────────────────

def deck_lines(slides: dict) -> list[DeckLine]:
    """장 원문을 번호 붙인 줄로 (S3.2 = 3장 둘째 줄). 모델이 근거 줄을 번호로 대고 코드가 원문을 되찾는다."""
    out: list[DeckLine] = []
    for no in sorted(slides):
        for i, line in enumerate(read_lines(getattr(slides[no], "raw_text", "") or "", clean_slide_text), 1):
            if line.strip():
                out.append(DeckLine(f"S{no}.{i}", no, line.strip()))
    return out


def deck_block(lines: list[DeckLine], limit: int = 260) -> str:
    return "\n".join(f"{ln.id}: {ln.text[:limit]}" for ln in lines)


def _tokens(text: str) -> set[str]:
    return {t for t in norm_tokens(text or "") if len(t) >= 2}


def _lines_for(node, lines: list[DeckLine], k: int = 4) -> list[str]:
    """노드를 받치는 자료 줄 — 노드 장 안에서 라벨·요약·근거(evidence)와 낱말이 많이 겹치는 순."""
    want = _tokens(" ".join([node.label, node.summary or "", *(node.evidence or [])]))
    cands = [ln for ln in lines if ln.slide_no in (node.slide_nos or [])] or lines
    scored = sorted(cands, key=lambda ln: -len(want & _tokens(ln.text)))
    return [ln.id for ln in scored[:k] if want & _tokens(ln.text)] or [ln.id for ln in cands[:2]]


# ─── 슬롯 (PLAN 2a) ─────────────────────────────────────────────────────────────────────────

def _root(graph):
    nodes = list(graph.nodes)
    thesis = [n for n in nodes if n.kind == "thesis"]
    if thesis:
        return thesis[0]
    tops = [n for n in nodes if n.parent_id is None]
    return max(tops or nodes, key=lambda n: n.weight) if nodes else None


def _node_weight(node) -> float:
    base = KIND_WEIGHT.get(node.kind, 0.35 + 0.35 * float(node.weight or 0))
    return base * (1.0 if node.importance == "core" else 0.85)


def _slide_text(slides: dict, nos) -> str:
    return " ".join(clean_slide_text(getattr(slides[n], "raw_text", "") or "") for n in nos if n in slides)


def _supported(node, claims) -> bool:
    """주장에 받치는 근거(수치·출처·결과)가 있는가 — F-26 has_support 또는 노드 evidence 의 숫자."""
    for c in (getattr(claims, "claims", None) or []):
        if c.subject_id == node.id or node.id in (c.object_ids or []):
            if c.has_support:
                return True
    return any(grounding.numbers(e) for e in (node.evidence or []))


def _children(graph, node_id: str) -> list:
    return [n for n in graph.nodes if n.parent_id == node_id]


def candidate_slots(graph, claims, slides: dict, lines: list[DeckLine], idx=None) -> list[Slot]:
    """그래프 위치마다 물을 수 있는 패턴 전부 — 점수 높은 순 (아직 자르지 않는다)."""
    root = _root(graph)
    out: list[Slot] = []
    by_id = {n.id: n for n in graph.nodes}

    def add(node, pattern: str, bonus: float = 1.0, **kw):
        out.append(Slot(id="", node_id=node.id, label=node.label, kind=node.kind or "", pattern=pattern,
                        slides=list(node.slide_nos or []), lines=_lines_for(node, lines),
                        score=_node_weight(node) * PATTERN_WEIGHT[pattern] * bonus, **kw))

    if root is not None:
        add(root, "P1", 1.1)
        next_slide = any(_NEXT_RE.search(_slide_text(slides, [n])) for n in slides)
        add(root, "P10", 1.0 if next_slide else 0.9)
        if not any(_LIMIT_RE.search(_slide_text(slides, [n])) for n in slides):
            add(root, "P7", 0.95)            # 한계를 아예 안 다룬 발표 — 결론의 범위를 묻는다
    for node in graph.nodes:
        if root is not None and node.id == root.id:
            continue
        if _CITATION_RE.search(node.label or ""):
            continue                         # 참고문헌 노드(「Leroy (2009)」) — 발표의 논리가 아니다
        text = _slide_text(slides, node.slide_nos or [])
        meta = " ".join([node.label, node.summary or "", *(node.evidence or [])])
        if node.kind == "claim":
            add(node, "P2" if _supported(node, claims) else "P3")
            if _LIMIT_RE.search(meta) or _LIMIT_RE.search(text):
                add(node, "P7")
            if _METHOD_RE.search(meta):
                add(node, "P6")
        elif node.kind in ("", "concept"):
            if _METHOD_RE.search(meta) and node.importance == "core":
                add(node, "P6", 0.9)
            elif _LIMIT_RE.search(meta):
                add(node, "P7", 0.9)
            elif node.importance == "core" and len(_children(graph, node.id)) >= 1:
                add(node, "P8")
            elif node.importance == "core" and float(node.weight or 0) >= 0.6:
                add(node, "P8", 0.8)
        # P4: 결론이 기대는 조건 — 숫자가 든 근거를 가진 주장·핵심 개념이고, 그 조건 말이 있을 때만
        if node.kind in ("claim", "thesis") and any(grounding.numbers(e) for e in (node.evidence or [])) \
                and re.search(r"조건|구간|수준|기준|이상|이하|범위|농도|온도|속도", meta):
            add(node, "P4")
    # P5: 장을 넘나드는 주장 사이 연결 (F-26 인과·비교)
    for c in (getattr(claims, "claims", None) or []):
        if c.kind not in ("cause", "compare", "enable", "lead", "contrast"):
            continue
        a = by_id.get(c.subject_id)
        b = next((by_id[o] for o in (c.object_ids or []) if o in by_id), None)
        if a is None or b is None or set(a.slide_nos or []) == set(b.slide_nos or []):
            continue
        out.append(Slot(id="", node_id=a.id, label=a.label, kind=a.kind or "", pattern="P5",
                        slides=sorted(set(a.slide_nos or []) | set(b.slide_nos or [])),
                        lines=(_lines_for(a, lines, 2) + _lines_for(b, lines, 2)),
                        score=max(_node_weight(a), _node_weight(b)) * PATTERN_WEIGHT["P5"],
                        partner_id=b.id, partner_label=b.label))
    # P9: 함정 — 코드가 자료 줄 하나를 뒤집어 전제를 만든다 (`_traps`, LLM 이 지어내지 않는다)
    if idx is not None:
        for node in sorted([n for n in graph.nodes if n.kind in ("thesis", "claim")] or list(graph.nodes),
                           key=lambda n: -_node_weight(n))[:4]:
            # 숫자 뒤집기는 미시 확인이다(§0-1) — 방향·부정·순서·순위처럼 **논리**를 뒤집은 함정만 쓴다
            cands = [c for c in traps.candidates(node.label, list(node.slide_nos or []), idx) if c.premise.kind != "number"]
            if cands:
                tp = cands[0].premise
                out.append(Slot(id="", node_id=node.id, label=node.label, kind=node.kind or "", pattern="P9",
                                slides=[tp.slide_no] if tp.slide_no else list(node.slide_nos or []),
                                lines=_lines_for(node, lines, 2), score=_node_weight(node) * PATTERN_WEIGHT["P9"],
                                trap=tp.to_dict()))
                break
    out.sort(key=lambda s: -s.score)
    return out


def build_slots(graph, claims, slides: dict, lines: list[DeckLine], idx=None, *, limit: int | None = None) -> list[Slot]:
    """
    질문 대상 지도 — 슬롯 목록. 제약(PLAN 2a): 노드당 패턴 SLOTS_PER_NODE 개까지 · (노드, 패턴) 하나씩 · 잎 개념(P8)은 둘까지 ·
    함정(P9)은 하나. 수는 장 수에 맞춘다(SLOTS_MIN~SLOTS_MAX).
    """
    n_slides = len(slides) or 1
    cap = limit or max(SLOTS_MIN, min(SLOTS_MAX, n_slides * 2 + 2))
    per_node: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    p8 = 0
    chosen: list[Slot] = []
    for s in candidate_slots(graph, claims, slides, lines, idx):
        key = (s.node_id, s.pattern)
        if key in seen or per_node.get(s.node_id, 0) >= SLOTS_PER_NODE:
            continue
        if s.pattern == "P8" and p8 >= 2:
            continue
        if s.pattern == "P9" and any(c.pattern == "P9" for c in chosen):
            continue
        seen.add(key)
        per_node[s.node_id] = per_node.get(s.node_id, 0) + 1
        p8 += s.pattern == "P8"
        chosen.append(s)
        if len(chosen) >= cap:
            break
    for i, s in enumerate(chosen, 1):
        s.id = f"T{i}"
    return chosen


# ─── 후보 거르기 ──────────────────────────────────────────────────────────────────────────────

POLITE_END_RE = re.compile(r"(요|죠|세요|나요|가요|까요|래요|습니까|니까)\s*[?？.!]?\s*$")
#: 가리키는 말 + 일반 명사 — 앞에 이 자료의 고유 낱말이 하나도 없으면 무엇을 가리키는지 알 수 없다 (10-16 「이 조건을 포함하나요?」)
_DEIXIS_RE = re.compile(r"(?<![가-힣])(?:이|그|해당|위|앞의|이런|그런)\s?(조건|결과|방법|부분|수치|값|점|것|경우|차이|실험|변수|주장|결론|가정|과정|요인|현상|데이터|기준|내용|문제)")
#: 미시 확인 — 숫자·용어·장 번호를 외웠는지 묻는 꼴 (§0-1). P4 의 「바뀌면 결론이」 꼴은 아니다
_MICRO_RE = re.compile(
    r"몇\s?(?:장|개|명|퍼센트|%|배|번|회|건|년|시간|분|사이클|도)|얼마(?:였|인가|인지|나\s?되|예요|이에요|입니까)|"
    r"(?:수치|값|비율|숫자)(?:는|가|은|이)\s*(?:무엇|얼마|몇)|(?:정의|뜻)(?:는|가|이|은)\s*(?:무엇|뭔)|무엇의\s*약자|"
    r"몇\s*장에|어느\s*장|(?<![가-힣])[0-9]+\s*장(?:에서|에|의)\s*(?:나온|제시된|적힌)|"
    r"(?:발표에서|말로는)\s*.{0,40}(?:라고|이라고)\s*했는데.{0,30}(?:자료|슬라이드).{0,20}(?:다르|달라|맞나)")
_COND_SHIFT_RE = re.compile(r"바뀌면|달라지면|바꾸면|달라질|바뀔|높아지면|낮아지면|늘리면|줄이면|없다면|라면")
#: 어느 발표에나 붙는 낱말 — 「특화」 셈에서 뺀다
GENERIC = {"발표", "자료", "슬라이드", "결론", "근거", "주장", "이유", "설명", "결과", "방법", "연구", "분석", "내용", "부분",
           "생각", "말씀", "핵심", "한계", "의미", "중요", "관점", "측면", "다음", "단계", "질문", "어떻게", "무엇", "왜",
           "어떤", "가장", "실제", "경우", "문제", "해결", "데이터", "제시", "보여", "있나요", "하나요", "건가요", "인가요"}
ANSWER_SENT_MAX = 3
ANSWER_MIN = 12
#: 모범답의 자료 밖 내용 명사가 이만큼이면 지어낸 답이다 (「리튬 도금 · 전극 손상 · DOD」)
ANSWER_NOVEL_MAX = 3
_SENT_END_RE = re.compile(r"(요|다|죠)[.!]?\s*$")
QUESTION_MAX = 200
_LEAD_RE = re.compile(r"^(?:질문의 전제와 달리,\s*)?자료는 이렇게 말해요\s*—\s*")
_LINE_REF_RE = re.compile(r"S\d{1,3}\.\d{1,3}")


def specific_terms(text: str, label: str, deck_tokens: set[str]) -> list[str]:
    """질문 속 이 자료 고유 낱말 (라벨 낱말·상투어 빼고)."""
    return sorted(t for t in _tokens(text) - _tokens(label) - GENERIC if t in deck_tokens)


def micro(question: str) -> bool:
    q = question or ""
    return bool(_MICRO_RE.search(q)) and not _COND_SHIFT_RE.search(q)


def vague_deixis(question: str, deck_tokens: set[str]) -> bool:
    for m in _DEIXIS_RE.finditer(question or ""):
        before = question[:m.start()]
        if not (_tokens(before) - GENERIC) & deck_tokens:
            return True
    return False


def haeyo_answer(text: str) -> str:
    t = _LEAD_RE.sub("", (text or "").strip())
    return to_haeyo(t)


def check_candidate(c: dict, slot: Slot, *, lines_by_id: dict[str, DeckLine], idx, deck_tokens: set[str],
                    sources: list[str]) -> tuple[dict | None, list[str]]:
    """
    모델 후보 하나 → (다듬은 후보, 버린 까닭들). 까닭이 하나라도 있으면 버린다 — 템플릿으로 바꾸지 않는다.
    다듬기는 말투(물음 끝·모범답 해요체)와 근거 줄 되찾기뿐 — 내용은 바꾸지 않는다.
    """
    why: list[str] = []
    q = re.sub(r"\s+", " ", str(c.get("question") or "")).strip()
    a = re.sub(r"\s+", " ", str(c.get("answer") or "")).strip()
    if not q or c.get("skip"):
        return None, ["skipped"]
    if len(re.findall(r"[가-힣]", q)) < max(6, len(q) // 4):
        why.append("not_korean")
    if len(q) > QUESTION_MAX:
        why.append("too_long")
    if q.count("?") + q.count("？") > 1:
        why.append("multi_ask")
    if not POLITE_END_RE.search(q):
        why.append("impolite")
    if vague_deixis(q, deck_tokens):
        why.append("vague_deixis")
    if micro(q) and slot.pattern != "P9":
        why.append("micro")
    terms = specific_terms(q, "", deck_tokens)
    if not terms:
        why.append("generic")
    trap = slot.trap
    if trap:
        from .contracts import TrapPremise  # noqa: PLC0415
        tp = TrapPremise.from_dict(trap)
        if tp is None or not traps.question_carries(q, tp, slot.label):
            why.append("trap_premise_missing")
        a = traps.trap_gist(tp) if tp is not None else a
    else:
        if ungrounded_numbers(q, sources):
            why.append("number_not_in_deck")
        if grounding.question_premise_problems(q, idx):
            why.append("false_premise")
        if len(grounding.unknown_terms(q, idx)) >= 3:
            why.append("off_deck_terms")
    refs = [r for r in (c.get("lines") or []) if isinstance(r, str)]
    refs = [m for r in refs for m in _LINE_REF_RE.findall(r)]
    found = [lines_by_id[r] for r in refs if r in lines_by_id]
    if not found and not trap:
        why.append("bad_line_ref")
    if not trap:
        a = haeyo_answer(a)
        sents = grounding.sentences(a)
        if not a or len(sents) > ANSWER_SENT_MAX:
            why.append("answer_len")
        if " · " in a or a.count("/") >= 2:
            why.append("answer_messy")
        if ungrounded_numbers(a, sources):
            why.append("answer_number_not_in_deck")
        if not _SENT_END_RE.search(a) or len(a) < ANSWER_MIN:
            why.append("answer_fragment")
        # 「왜」 질문의 모범답은 자료 줄을 잇는 추론이 든다 — 절마다 자료 대조(supported_sentences)로 버리면 핵심 질문이 다 빠진다
        # (10-17 A1 실측: 36개 중 25개). 그래서 **지어낸 낱말**(자료·그래프에 없는 내용 명사 셋 이상)만 버리고, 절 대조는 표시로 남긴다.
        if len(grounding.unknown_terms(a, idx)) >= ANSWER_NOVEL_MAX:
            why.append("answer_off_deck")
        if grounding.gist_problems(a, idx):
            why.append("answer_mismatch")
    if why:
        return None, why
    inference = bool(not trap and grounding.supported_sentences(a, idx)[1])
    slide = found[0].slide_no if found else (slot.slides[0] if slot.slides else 0)
    return {**c, "question": q, "answer": a, "lines": [ln.id for ln in found], "slide_no": slide,
            "quote": found[0].text if found else (trap or {}).get("fact", ""), "terms": terms,
            "answer_inference": inference}, []


def question_tokens_overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a) - GENERIC, _tokens(b) - GENERIC
    return len(ta & tb) / max(1, min(len(ta), len(tb)))


# ─── 발표 음성 신호 (PLAN 2a 층 2·3 — 숫자 차이는 신호가 아니다) ─────────────────────────────────────

SPEECH_COVER_LOW = 0.25
SPEECH_SHARE_LOW = 0.45


def speech_cover(text: str, speech: str) -> float:
    want = _tokens(text) - GENERIC
    return len(want & _tokens(speech)) / max(1, len(want)) if want else 1.0


def voice_signals(graph, slides: dict, speech_of: dict[int, str], alignment=None, answers: list[dict] | None = None,
                  lines: list[DeckLine] | None = None) -> list[dict]:
    """
    3번 이후 질문의 재료 — 핵심 노드(thesis·claim)마다 발표가 그 논리를 어떻게 다뤘나, 그리고 앞 답에서 드러난 약점.

    - skipped_reason: 결론(라벨)은 말했는데 그 근거 줄은 거의 말하지 않았다 — 「결론만 말하고 이유를 건너뜀」
    - vague: 그 장에서 말한 시간·비중이 자료 비중보다 한참 작다(under_spoken) 또는 정합 판정이 missing — 「흐림·건너뜀」
    - misexplained: 정합 판정이 contradiction 인데 숫자 모순이 아니다 — 「핵심과 어긋난 설명」
    - weak_answer: 앞 답 판정이 partial·wrong·unknown — 그 노드와 이웃(부모·자식)으로 더 깊이 / 옆으로 / 바로잡기
    """
    out: list[dict] = []
    items = {it.node_id: it for it in (getattr(alignment, "items", None) or [])}
    lines = lines if lines is not None else deck_lines(slides)
    core = [n for n in graph.nodes if n.kind in ("thesis", "claim")] or \
        sorted(graph.nodes, key=lambda n: -float(n.weight or 0))[:6]
    for node in core:
        speech = " ".join(speech_of.get(n, "") for n in (node.slide_nos or []))
        if not speech.strip():
            continue
        it = items.get(node.id)
        label_said = speech_cover(node.label, speech) >= 0.5
        ev_lines = [ln for ln in lines if ln.id in set(_lines_for(node, lines, 4))]
        ev_cover = [speech_cover(ln.text, speech) for ln in ev_lines] or [1.0]
        low = [ln for ln, cv in zip(ev_lines, ev_cover) if cv < SPEECH_COVER_LOW]
        quote = _speech_quote(node.label, speech)
        if it is not None and it.verdict == "contradiction" and getattr(it, "contra_kind", "") not in ("number", "numeric"):
            if not grounding.numbers(getattr(it, "evidence", "") or ""):
                out.append(_sig("misexplained", node, low[0] if low else (ev_lines[0] if ev_lines else None), quote,
                                "발표 설명이 자료의 주장과 어긋났어요"))
                continue
        if label_said and low and len(low) >= max(1, len(ev_lines) // 2):
            out.append(_sig("skipped_reason", node, low[0], quote, "결론은 말했는데 받치는 근거는 거의 말하지 않았어요"))
            continue
        share = (float(getattr(it, "speech_weight", 0) or 0) / max(0.01, float(getattr(it, "doc_weight", 0) or 0))) \
            if it is not None else 1.0
        if (it is not None and it.verdict == "missing") or share < SPEECH_SHARE_LOW:
            out.append(_sig("vague", node, ev_lines[0] if ev_lines else None, quote,
                            "자료에서 무게가 큰 주장인데 발표에서는 짧게 지나갔어요"))
    by_id = {n.id: n for n in graph.nodes}
    for a in answers or []:
        if a.get("verdict") in ("partial", "wrong", "unknown") and a.get("node_id") in by_id:
            node = by_id[a["node_id"]]
            out.append({**_sig("weak_answer", node, None, (a.get("answer") or "")[:90],
                               "앞 답에서 이 부분 이해가 약했어요" + (f" — 빠진 점: {', '.join(a.get('missing') or [])[:80]}"
                                                                if a.get("missing") else "")),
                        "move": "correct" if a.get("verdict") == "wrong" else "deeper",
                        "neighbors": [n.label for n in graph.nodes if n.parent_id == node.id][:3]
                        + ([by_id[node.parent_id].label] if node.parent_id in by_id else [])})
    for i, s in enumerate(out, 1):
        s["id"] = f"V{i}"
    return out


def _sig(kind: str, node, line: DeckLine | None, speech_quote: str, note: str) -> dict:
    return {"id": "", "kind": kind, "node_id": node.id, "label": node.label, "node_kind": node.kind or "",
            "slide_no": line.slide_no if line else (node.slide_nos[0] if node.slide_nos else 0),
            "deck_line": line.id if line else "", "deck_text": line.text if line else "",
            "speech_quote": speech_quote, "note": note}


def _speech_quote(label: str, speech: str, limit: int = 90) -> str:
    """라벨 낱말이 가장 많이 든 발화 문장 한 구절."""
    sents = [s for s in re.split(r"(?<=[.?!다요])\s+", speech or "") if s.strip()]
    if not sents:
        return ""
    want = _tokens(label)
    best = max(sents, key=lambda s: len(want & _tokens(s)))
    return best.strip()[:limit]


__all__ = ["PATTERNS", "ANGLE_OF", "Slot", "DeckLine", "deck_lines", "deck_block", "build_slots", "candidate_slots",
           "check_candidate", "micro", "vague_deixis", "specific_terms", "voice_signals", "speech_cover",
           "question_tokens_overlap", "GENERIC"]
