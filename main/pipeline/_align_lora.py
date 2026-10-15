"""
[F-11 내부] 「자료와 맞게 말했나」 판정을 로컬 KT Mi:dm 2.0 LoRA 로 하는 판정기입니다.

F-11(`f11_align.align_speech`)은 한 발표의 개념 전부를 Solar 한 번에 묻는다. 이 모듈은 **개념 하나씩** 묻는다 —
개념 · 그 개념이 나온 장의 자료 글 · 그 장(과 바로 앞뒤 장)의 발화 문장(번호 붙임)을 주고,
{"verdict", "sid", "note"} JSON 한 줄을 받는다. 근거 인용(evidence)은 sid 가 가리키는 발화 문장 원문이다. 판정 확신도는 첫 토큰(판정 낱말)의 확률이다.

학습(etc/finetune/align/)과 서비스가 **같은 함수로** 항목을 만들고(build_items) 프롬프트를 그린다(render_prompt) —
둘이 어긋나면 학습한 것과 다른 것을 묻게 된다.

호출: f11_align.align_speech(..., judge="lora" | "lora+solar") → judge_nodes()
어댑터: CHUCKCHUCK_ALIGN_LORA_PATH (기본 /data/models/_runs/align-lora/runs/<최신>/final 을 쓰지 않는다 — 명시해야 켠다)
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import ALIGN_VERDICTS, ConceptGraph, ConceptNode, SlideDoc, Transcript
from ._spoken import Utterance, utterances

BASE_MODEL = os.environ.get("CHUCKCHUCK_ALIGN_LORA_BASE", "/data/models/Midm-2.0-Base-Instruct")
ADAPTER_ENV = "CHUCKCHUCK_ALIGN_LORA_PATH"

#: 프롬프트 길이 상한(글자). 한국어 Mi:dm 토큰은 대략 2글자 = 1토큰이다.
SLIDE_CHARS = 700          # 장 하나의 자료 글
MAX_SLIDES = 3             # 개념이 걸친 장 중 앞에서부터
OWN_CHARS = 2200           # 개념 장 발화 전체
NEIGHBOR_SENTS = 3         # 앞 장 끝 · 뒤 장 머리 문장 수
NEIGHBOR_CHARS = 420
EVIDENCE_LINES = 6

SYSTEM_PROMPT = """너는 발표 리허설 채점기다. 개념 하나와 그 개념이 나온 슬라이드 글, 발표자가 그 장과 바로 앞뒤 장에서 한 말(문장마다 번호)을 보고 판정한다.

verdict 넷 중 하나:
- aligned: 발화가 개념의 핵심 뜻을 전달했고 자료와 맞다. 낱말이 달라도 뜻이 같으면 aligned. 바로 앞뒤 장에서 말했어도 aligned.
- contradiction: 발화가 자료와 양립할 수 없다 — 수치·단위가 다르거나, 늘었다/줄었다·높다/낮다가 반대거나, 맞다/아니다가 반대거나, 비교한 두 쪽이 뒤바뀌었다. 받아쓰기로 글자만 깨진 것은 아니다.
- missing: 발화에 없고, 빠지면 청중이 발표를 따라가기 어렵다(주장·핵심 정의·결과·조건). 「넘어갈게요」「나중에 설명할게요」처럼 넘긴 말은 설명이 아니다. 이름만 스치고 내용을 말하지 않았으면 missing.
- justified_skip: 발화에 없지만 빼도 이해에 지장이 없다 — 저자·소속·감사·인사·로고, 도표 눈금·막대 이름, 같은 목록의 보조 칸.

판정은 내용 기준이다. 말투·발음은 보지 않는다. 외부 지식으로 자료의 옳고 그름을 따지지 않는다.
출력은 JSON 한 줄: {"verdict": "...", "sid": "근거 문장 번호 또는 null", "note": "한국어 한 줄 이유"}
aligned·contradiction 은 sid 가 필수다 — 그 뜻을 가장 직접 말한(모순이면 어긋나게 말한) 문장 하나의 번호. missing·justified_skip 은 sid null."""

#: 생성은 이 접두를 이어 쓴다 — 첫 생성 토큰이 판정 낱말이라 그 확률이 곧 확신도다.
ASSISTANT_PREFIX = '{"verdict": "'

_BOS = "<|begin_of_text|>"
_SYS = "<|start_header_id|>system<|end_header_id|>\n\n"
_USR = "<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
_AST = "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
EOT = "<|eot_id|>"


# ---------------------------------------------------------------------------
# 항목 — 개념 하나 + 자료 글 + 번호 붙인 발화
# ---------------------------------------------------------------------------

def sid_of(slide_no: int, k: int) -> str:
    return f"s{int(slide_no):02d}-{int(k):02d}"


def speech_index(utts: list[Utterance]) -> dict[int, list[tuple[str, Utterance]]]:
    """장 번호 → [(sid, 문장)] — 장 안 말한 순서(재방문 포함)대로 1부터."""
    out: dict[int, list[tuple[str, Utterance]]] = {}
    for u in utts:
        rows = out.setdefault(u.slide_no, [])
        rows.append((sid_of(u.slide_no, len(rows) + 1), u))
    return out


_TOK_RE = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z\-]+|\d+(?:[.,]\d+)?")


def _toks(text: str) -> set[str]:
    out = set()
    for t in _TOK_RE.findall(text or ""):
        t = t.lower()
        out.add(t[:2] if "가" <= t[0] <= "힣" else t)   # 한국어는 앞 두 글자 — 조사·어미를 떼는 거친 줄기
    return out


def _clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _select(rows: list[dict], budget: int, anchor: set[str]) -> list[dict]:
    """발화가 길면(긴 강의) 개념 낱말과 겹치는 문장부터 budget 글자까지 — 순서는 말한 순서 그대로, 빠진 곳은 「…」."""
    if sum(len(r["text"]) for r in rows) <= budget:
        return rows
    scored = sorted(range(len(rows)), key=lambda i: (-len(_toks(rows[i]["text"]) & anchor), i))
    keep, used = set(), 0
    for i in scored:
        n = len(rows[i]["text"])
        if used + n > budget and keep:
            continue
        keep.add(i)
        used += n
        if used >= budget:
            break
    out, last = [], -1
    for i in sorted(keep):
        if last >= 0 and i != last + 1:
            out.append({"sid": "", "text": "…"})
        out.append(rows[i])
        last = i
    return out


def _rows(pairs: list[tuple[str, Utterance]]) -> list[dict]:
    return [{"sid": sid, "text": " ".join(u.text.split())} for sid, u in pairs if u.text.strip()]


def build_item(node: ConceptNode, index: dict[int, list[tuple[str, Utterance]]],
               slides: dict[int, tuple[str, str]]) -> dict:
    """개념 하나의 판정 항목. slides 는 장 번호 → (제목, 원문). 자료 원문이 없으면 비운다(요약·근거만 간다)."""
    nos = sorted({int(n) for n in node.slide_nos})
    anchor = _toks(" ".join([node.label, node.summary or "", *list(node.evidence or [])[:EVIDENCE_LINES]]))
    own: list[dict] = []
    for no in nos:
        own.extend(_rows(index.get(no, [])))
    if not nos:
        # 근거 장이 없는 노드(대개 발표 전체의 핵심 주장) — 발표 전체에서 개념 낱말이 겹치는 문장을 고른다
        for no in sorted(index):
            own.extend(_rows(index[no]))
    item = {
        "node_id": node.id,
        "label": node.label,
        "kind": node.kind or "",
        "weight": round(float(node.weight or 0.0), 2),
        "summary": node.summary or "",
        "evidence": [_clip(e, 200) for e in list(node.evidence or [])[:EVIDENCE_LINES]],
        "slide_nos": nos,
        "slides": [
            {"slide_no": no, "title": _clip(slides[no][0], 120), "text": _clip(slides[no][1], SLIDE_CHARS)}
            for no in nos[:MAX_SLIDES] if no in slides
        ],
        "own": _select(own, OWN_CHARS, anchor),
        "prev": [],
        "next": [],
    }
    if nos:
        prev = _rows(index.get(nos[0] - 1, []))[-NEIGHBOR_SENTS:]
        nxt = _rows(index.get(nos[-1] + 1, []))[:NEIGHBOR_SENTS]
        item["prev"] = _fit(prev, NEIGHBOR_CHARS, keep_tail=True)
        item["next"] = _fit(nxt, NEIGHBOR_CHARS, keep_tail=False)
    return item


def _fit(rows: list[dict], budget: int, keep_tail: bool) -> list[dict]:
    seq = list(reversed(rows)) if keep_tail else list(rows)
    out, used = [], 0
    for r in seq:
        if out and used + len(r["text"]) > budget:
            break
        out.append({"sid": r["sid"], "text": _clip(r["text"], budget)})
        used += len(r["text"])
    return list(reversed(out)) if keep_tail else out


def slide_map(slide_doc: SlideDoc | None) -> dict[int, tuple[str, str]]:
    if slide_doc is None:
        return {}
    return {s.slide_no: (s.title or "", s.raw_text or "") for s in slide_doc.slides}


def build_items(graph: ConceptGraph, transcript: Transcript, slide_doc: SlideDoc | None = None,
                utts: list[Utterance] | None = None) -> list[dict]:
    """그래프의 노드마다 항목 하나. 장이 없는 노드(slide_nos 빔)도 항목은 만든다 — 발화가 비어 판정기가 missing/skip 을 고른다."""
    index = speech_index(utts if utts is not None else utterances(transcript))
    slides = slide_map(slide_doc)
    return [build_item(n, index, slides) for n in graph.nodes]


def item_sentences(item: dict) -> dict[str, str]:
    """sid → 문장 원문 (이 항목에 보인 것만)."""
    return {r["sid"]: r["text"] for part in ("own", "prev", "next") for r in item.get(part, []) if r.get("sid")}


# ---------------------------------------------------------------------------
# 프롬프트 · 정답 · 출력 해석
# ---------------------------------------------------------------------------

def render_user(item: dict) -> str:
    kind = {"thesis": "핵심 주장", "claim": "주장", "concept": "개념"}.get(item.get("kind", ""), "개념")
    nos = ",".join(str(n) for n in item.get("slide_nos", [])) or "없음"
    lines = [f"[개념] {item['label']}", f"종류: {kind} · 중요도 {item.get('weight', 0):.2f} · 근거 장 {nos}"]
    if item.get("summary"):
        lines.append(f"요약: {item['summary']}")
    if item.get("evidence"):
        lines.append("자료 근거:")
        lines += [f"- {e}" for e in item["evidence"]]
    for s in item.get("slides", []):
        lines += ["", f"[슬라이드 {s['slide_no']}] {s['title']}".rstrip(), s["text"] or "(글 없음)"]

    def block(title: str, rows: list[dict]) -> None:
        lines.extend(["", title])
        if not rows:
            lines.append("(발화 없음)")
        for r in rows:
            lines.append(f"{r['sid']} {r['text']}" if r.get("sid") else r["text"])

    block("[발화 — 이 개념의 장]", item.get("own", []))
    if item.get("prev"):
        block("[앞 장 발화]", item["prev"])
    if item.get("next"):
        block("[뒤 장 발화]", item["next"])
    return "\n".join(lines)


def render_prompt(item: dict) -> str:
    """Mi:dm 대화 틀을 손으로 그린다 — 기본 틀은 긴 안내문(수백 토큰)과 오늘 날짜를 끼워 넣어 항목마다 낭비고 재현이 안 된다."""
    return f"{_BOS}{_SYS}{SYSTEM_PROMPT}{_USR}{render_user(item)}{_AST}"


def render_target(verdict: str, sid: str | None = None, note: str = "") -> str:
    """정답 JSON 한 줄(접두 포함, 끝 EOT 제외). 인용 글은 생성하지 않는다 — 번호(sid)가 가리키는 발화 문장을 그대로 쓴다
    (생성한 인용은 한 글자만 달라도 「발표에서 한 말」 이 아니게 되고, 토큰도 몇 배 든다)."""
    body = {"verdict": verdict, "sid": sid if verdict in ("aligned", "contradiction") else None,
            "note": _clip(note, 70)}
    return json.dumps(body, ensure_ascii=False)


def parse_output(text: str, item: dict | None = None) -> dict:
    """생성 글(접두 포함) → {verdict, sid, evidence, note, ok}. 깨졌으면 정규식으로 건지고 ok=False."""
    raw = (text or "").strip()
    if raw.endswith(EOT):
        raw = raw[: -len(EOT)]
    data: dict = {}
    try:
        s = raw.find("{")
        # 첫 객체만 — 덜 배운 모델은 닫은 뒤에도 같은 JSON 을 되풀이한다
        data, _ = json.JSONDecoder().raw_decode(raw[s:]) if s >= 0 else ({}, 0)
        if not isinstance(data, dict):
            data = {}
    except (ValueError, TypeError):
        data = {}
    ok = bool(data)
    if not ok:
        m = re.search(r'"verdict"\s*:\s*"([a-z_]+)"', raw)
        data = {"verdict": m.group(1) if m else ""}
        m = re.search(r'"sid"\s*:\s*"(s\d+-\d+)"', raw)
        if m:
            data["sid"] = m.group(1)
    verdict = str(data.get("verdict", "") or "")
    sid = data.get("sid") or None
    sid = str(sid) if sid else None
    evidence = " ".join(str(data.get("evidence", "") or "").split())
    sents = item_sentences(item) if item else {}
    # 근거는 번호가 가리키는 문장이 우선이다 — 생성한 글이 발화와 한 글자라도 다르면 인용이 아니다
    if sid and sid in sents:
        if not evidence or evidence not in sents[sid]:
            evidence = sents[sid]
    elif evidence and sents and not any(evidence in t for t in sents.values()):
        hit = next((k for k, t in sents.items() if t and t in evidence), None)
        sid, evidence = (hit, sents[hit]) if hit else (None, evidence)
    return {"verdict": verdict if verdict in ALIGN_VERDICTS else "", "sid": sid, "evidence": evidence,
            "note": str(data.get("note", "") or "").strip(), "ok": ok and verdict in ALIGN_VERDICTS}


def evidence_valid(item: dict, sid: str | None, evidence: str) -> bool:
    """인용이 이 항목 발화의 한 문장 안에 그대로 있는가 (aligned·contradiction 근거 검사)."""
    ev = " ".join((evidence or "").split())
    if not ev:
        return False
    sents = item_sentences(item)
    if sid and sid in sents:
        return ev in sents[sid]
    return any(ev in t for t in sents.values())


# ---------------------------------------------------------------------------
# 판정기 — HF transformers + peft, 한 번 올려 두고 묶어서 생성
# ---------------------------------------------------------------------------

@dataclass
class Judgment:
    node_id: str
    verdict: str
    sid: str | None = None
    evidence: str = ""
    note: str = ""
    probs: dict = field(default_factory=dict)
    confidence: float = 0.0
    ok: bool = True
    raw: str = ""


class AlignJudge:
    """판정기 인터페이스 — 테스트는 가짜를 꽂는다(judge_items 만 있으면 된다)."""

    name = "align-judge"

    def judge_items(self, items: list[dict]) -> list[Judgment]:  # pragma: no cover - 인터페이스
        raise NotImplementedError


def adapter_path() -> Path | None:
    p = os.environ.get(ADAPTER_ENV, "").strip()
    return Path(p) if p else None


def adapter_available(path: Path | None = None) -> bool:
    p = path or adapter_path()
    return bool(p) and p.exists() and (p / "adapter_config.json").exists()


class LoraAlignJudge(AlignJudge):
    """Mi:dm 2.0 Base Instruct + F-11 LoRA. 첫 호출에 22GB 를 올린다(1~2분)."""

    def __init__(self, adapter: str | Path | None = None, *, base: str = BASE_MODEL,
                 batch_size: int = 8, max_new_tokens: int = 96, merge: bool = True):
        self.adapter = Path(adapter) if adapter else adapter_path()
        self.base = base
        self.batch_size = batch_size
        self.max_new_tokens = max_new_tokens
        self.merge = merge
        self._model = None
        self._tok = None
        self._verdict_ids: dict[str, int] = {}
        self._lock = threading.Lock()
        self.name = f"midm-lora:{self.adapter.name if self.adapter else '?'}"

    def load(self):
        if self._model is not None:
            return self._model, self._tok
        with self._lock:
            if self._model is not None:
                return self._model, self._tok
            base_only = str(self.adapter) == "none"          # 평가용 — LoRA 없이 베이스 모델 그대로(0-shot 기준선)
            if not base_only and not adapter_available(self.adapter):
                raise FileNotFoundError(f"F-11 LoRA 어댑터가 없어요: {self.adapter}")
            import torch
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer

            tok = AutoTokenizer.from_pretrained(self.base)
            tok.padding_side = "left"
            if tok.pad_token_id is None:
                tok.pad_token = tok.eos_token
            model = AutoModelForCausalLM.from_pretrained(self.base, dtype=torch.bfloat16, device_map={"": 0})
            if not base_only:
                model = PeftModel.from_pretrained(model, str(self.adapter))
                if self.merge:
                    model = model.merge_and_unload()
            model.eval()
            pre = tok.encode(ASSISTANT_PREFIX, add_special_tokens=False)
            for v in ALIGN_VERDICTS:
                ids = tok.encode(ASSISTANT_PREFIX + v, add_special_tokens=False)
                self._verdict_ids[v] = ids[len(pre)]
            self._model, self._tok = model, tok
            return model, tok

    def judge_items(self, items: list[dict]) -> list[Judgment]:
        out: list[Judgment] = []
        for i in range(0, len(items), self.batch_size):
            out.extend(self._batch(items[i:i + self.batch_size]))
        return out

    def _batch(self, items: list[dict]) -> list[Judgment]:
        import torch

        model, tok = self.load()
        # 학습과 같은 경계로 자른다 — 프롬프트와 접두를 따로 토큰화해 잇는다(합쳐 토큰화하면 경계 토큰이 달라질 수 있다)
        pre = tok(ASSISTANT_PREFIX, add_special_tokens=False)["input_ids"]
        seqs = [tok(render_prompt(it), add_special_tokens=False)["input_ids"] + pre for it in items]
        n = max(len(s) for s in seqs)
        ids = torch.full((len(seqs), n), tok.pad_token_id, dtype=torch.long)
        att = torch.zeros((len(seqs), n), dtype=torch.long)
        for b, s in enumerate(seqs):
            ids[b, n - len(s):] = torch.tensor(s)
            att[b, n - len(s):] = 1
        enc = {"input_ids": ids.to(model.device), "attention_mask": att.to(model.device)}
        eot = tok.convert_tokens_to_ids(EOT)
        start = enc["input_ids"].shape[1]
        with torch.no_grad():
            gen = model.generate(**enc, max_new_tokens=self.max_new_tokens, do_sample=False,
                                 repetition_penalty=1.0, eos_token_id=[eot, tok.eos_token_id],
                                 pad_token_id=tok.pad_token_id, output_scores=True, return_dict_in_generate=True,
                                 stopping_criteria=[_ClosedJson(tok, start)])
        first = torch.softmax(gen.scores[0].float(), dim=-1)
        vids = [self._verdict_ids[v] for v in ALIGN_VERDICTS]
        res = []
        for b, it in enumerate(items):
            p = first[b, vids]
            mass = float(p.sum())
            probs = {v: round(float(p[k]) / mass, 4) if mass > 0 else 0.0 for k, v in enumerate(ALIGN_VERDICTS)}
            text = tok.decode(gen.sequences[b, enc["input_ids"].shape[1]:], skip_special_tokens=True)
            got = parse_output(ASSISTANT_PREFIX + text, it)
            verdict = got["verdict"] or max(probs, key=probs.get)
            res.append(Judgment(node_id=it["node_id"], verdict=verdict, sid=got["sid"], evidence=got["evidence"],
                                note=got["note"], probs=probs, confidence=probs.get(verdict, 0.0),
                                ok=got["ok"], raw=text))
        return res


class _ClosedJson:
    """줄마다 JSON 객체가 닫히면(괄호 짝이 맞으면) 그 줄은 끝 — 모델이 EOT 를 늦게 내도 기다리지 않는다."""

    def __init__(self, tok, start: int):
        self.tok, self.start = tok, start

    def __call__(self, input_ids, scores, **kw):
        import torch

        done = []
        for row in input_ids:
            text = ASSISTANT_PREFIX + self.tok.decode(row[self.start:], skip_special_tokens=True)
            done.append(_closed(text))
        return torch.tensor(done, dtype=torch.bool, device=input_ids.device)


def _closed(text: str) -> bool:
    depth, in_str, esc = 0, False, False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return True
    return False


_shared: dict[str, LoraAlignJudge] = {}
_shared_lock = threading.Lock()


def shared_judge(adapter: str | Path | None = None) -> LoraAlignJudge:
    """프로세스에 하나 — 브리지가 요청마다 22GB 를 다시 올리지 않게."""
    path = Path(adapter) if adapter else adapter_path()
    key = str(path)
    with _shared_lock:
        if key not in _shared:
            _shared[key] = LoraAlignJudge(path)
        return _shared[key]
