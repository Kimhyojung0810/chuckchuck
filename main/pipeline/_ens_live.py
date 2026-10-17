"""
발표를 들으며 3번+ 질문을 준비하는 재료 (2026-10-17, docs/qa-ensemble/LIVE_REPORT.md) — LLM 없음.

    발표 중 (장을 넘길 때마다)    LiveTalk.put()          그 장에서 확정된 문장(A.X 실시간 받아쓰기)을 판(talk_id) 단위로 쌓는다
                                  new_signals()           다 들은 장의 핵심 노드만 신호(_ens_slots.voice_signals)를 보고, 아직 안 쓴 신호만
    프롬프트 맥락                 speech_digest()         「모든 장의 요지(장마다 한두 문장) + 신호 장 원문」 — 앞 2,400자 자르기 대신

규율:
- 남의 발화가 섞이지 않게 판 단위(세션 + talk_id)로만 쌓는다. 서버 열쇠는 bridge 가 정한다.
- 노드가 여러 장에 걸치면 그 장들을 **다** 들은 뒤에만 신호를 본다 — 첫 장만 듣고 「근거를 건너뛰었다」 고 잘못 짚지 않게.
- 숫자·낱말이 조금 다른 것은 신호가 아니다(§0-1) — voice_signals 가 그대로 지킨다.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import _ens_slots as ES

#: 한 장에서 받아 둘 발화 상한(글자) — 20분 발표 · 한 장 오래 머물러도 메모리 · 프롬프트가 터지지 않게
SLIDE_TEXT_MAX = 4000
#: 장 요지 — 장마다 이 글자 안에서 핵심 문장 한두 개
GIST_CHARS = 150
#: 신호가 든 장은 원문을 이만큼까지
FOCUS_CHARS = 700
#: 받아쓰기 맥락 전체 상한 (예전 앞부분 자르기와 같은 크기 — 프롬프트 크기는 그대로, 덮는 범위만 발표 전체로)
DIGEST_MAX = 2400

_SENT_RE = re.compile(r"(?<=[.?!다요죠])\s+")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_RE.split(text or "") if s.strip()]


def slide_gist(speech: str, slide_tokens: set[str], limit: int = GIST_CHARS) -> str:
    """그 장 발화에서 자료 낱말을 가장 많이 담은 문장 한두 개(말한 순서대로). 발화가 짧으면 그대로."""
    speech = re.sub(r"\s+", " ", speech or "").strip()
    if len(speech) <= limit:
        return speech
    sents = sentences(speech)
    if not sents:
        return speech[:limit]
    want = slide_tokens - ES.GENERIC
    ranked = sorted(range(len(sents)), key=lambda i: (-len(want & ES._tokens(sents[i])), i))
    keep: list[int] = []
    used = 0
    for i in ranked:
        s = sents[i]
        if keep and used + len(s) > limit:
            continue
        keep.append(i)
        used += len(s) + 1
        if used >= limit * 0.8:
            break
    out = " ".join(sents[i] for i in sorted(keep))
    return out if len(out) <= limit else out[: limit - 1].rstrip() + "…"


def speech_digest(speech_of: dict[int, str], slides: dict, focus: list[int] | None = None, *,
                  gist_chars: int = GIST_CHARS, focus_chars: int = FOCUS_CHARS, total: int = DIGEST_MAX) -> str:
    """
    프롬프트에 실을 발표 받아쓰기 — 「## 장별 요지」(모든 장, 장마다 한두 문장) + 「## 신호 장 원문」(focus 장).
    예전엔 받아쓰기 앞 2,400자만 실어 10분 발표면 뒷장 맥락이 통째로 빠졌다. 크기는 그대로 두고 덮는 범위만 발표 전체로.
    """
    nos = [n for n in sorted(speech_of) if (speech_of.get(n) or "").strip()]
    if not nos:
        return ""
    focus = [n for n in dict.fromkeys(focus or []) if n in nos]
    tok_of = {n: _slide_tokens(slides.get(n)) for n in nos}
    gist_lines = [f"- {n}장: {slide_gist(speech_of[n], tok_of[n], gist_chars)}" for n in nos]
    # 요지가 넘치면 장마다 더 줄인다 (장 수가 많은 발표 — 30장이어도 모든 장이 한 줄은 남게)
    while sum(len(x) + 1 for x in gist_lines) > total * 0.55 and gist_chars > 50:
        gist_chars = int(gist_chars * 0.75)
        gist_lines = [f"- {n}장: {slide_gist(speech_of[n], tok_of[n], gist_chars)}" for n in nos]
    out = ["## 장별 요지 (발표 전체)", *gist_lines]
    room = total - sum(len(x) + 1 for x in out)
    if focus and room > 120:
        out += ["", "## 신호가 나온 장의 발화 원문"]
        each = max(120, min(focus_chars, room // len(focus) - 12))
        for n in focus:
            t = re.sub(r"\s+", " ", speech_of[n]).strip()
            out.append(f"[{n}장] {t if len(t) <= each else t[:each - 1].rstrip() + '…'}")
    return "\n".join(out)[: total + 200]


def _slide_tokens(slide) -> set[str]:
    if slide is None:
        return set()
    from ._evidence import clean_slide_text  # noqa: PLC0415
    return ES._tokens(" ".join([getattr(slide, "title", "") or "", clean_slide_text(getattr(slide, "raw_text", "") or "")]))


def sig_key(sig: dict) -> str:
    """같은 신호를 두 번 쓰지 않는 열쇠 — 종류 + 노드 (장을 다시 들러 말이 늘어도 같은 신호면 같은 열쇠). 끝의 @장은 장 고르게 펴기용."""
    return f"{sig.get('kind', '')}:{sig.get('node_id', '')}@{sig.get('slide_no', '')}"


@dataclass
class LiveTalk:
    """발표 한 번(talk_id)의 장별 발화. 브리지 STORE 에 dict 로 담는다(to_dict/from_dict)."""
    slides: dict = field(default_factory=dict)     # {장 번호: 그 장에서 확정된 발화}
    closed: list = field(default_factory=list)     # 다 듣고 넘어간 장 (말한 순서)
    final: bool = False                            # 발표를 마쳤다
    done_sigs: list = field(default_factory=list)  # 이미 음성 후보를 만든 신호 열쇠
    seq: int = 0

    def put(self, slide_no: int, text: str, *, closed: bool = False, final: bool = False) -> None:
        """그 장의 발화 **전체**(지금까지)를 받는다 — 같은 장을 다시 보내면 바꿔 쓴다(멱등)."""
        n = int(slide_no or 0)
        if n > 0 and text is not None:
            t = re.sub(r"\s+", " ", str(text)).strip()[:SLIDE_TEXT_MAX]
            if t or n not in self.slides:
                self.slides[n] = t
            if closed and n not in self.closed:
                self.closed.append(n)
        if final:
            self.final = True
            for k in sorted(self.slides):
                if k not in self.closed:
                    self.closed.append(k)
        self.seq += 1

    def speech_of(self) -> dict[int, str]:
        return {n: t for n, t in self.slides.items() if t}

    def heard_all(self, slide_nos) -> bool:
        nos = [int(x) for x in (slide_nos or []) if x]
        return bool(nos) and (self.final or all(n in self.closed for n in nos))

    def to_dict(self) -> dict:
        return {"slides": {str(k): v for k, v in self.slides.items()}, "closed": list(self.closed), "final": self.final,
                "done_sigs": list(self.done_sigs), "seq": self.seq}

    @classmethod
    def from_dict(cls, d: dict | None) -> "LiveTalk":
        d = d or {}
        return cls(slides={int(k): str(v) for k, v in (d.get("slides") or {}).items() if str(k).isdigit()},
                   closed=[int(x) for x in d.get("closed") or []], final=bool(d.get("final")),
                   done_sigs=list(d.get("done_sigs") or []), seq=int(d.get("seq") or 0))


#: F-11 speech_weight 배합을 따른다 (f11_align._S_TIME · _S_MENTION · _S_SLIDE_COVER) — 시간 대신 글자 수
_W_TIME, _W_MENTION, _W_COVER = 0.45, 0.35, 0.20


def pseudo_alignment(talk: LiveTalk, graph):
    """
    발표 중엔 정합(F-11)이 없다 — 「자료에서 무게가 큰 주장인데 발표에서는 짧게 지나감(vague)」 을 코드로 어림한다(LLM 없음).
    F-11 speech_weight 와 같은 배합(발화 비중 0.45 · 언급 0.35 · 언급한 장 비율 0.20, 최댓값 정규화)에서 시간 대신 글자 수를 쓴다.
    판정(verdict)은 비워 둔다 — 「어긋남(misexplained)」 은 진짜 정합이 와야 본다.
    """
    from types import SimpleNamespace  # noqa: PLC0415
    heard = {n: t for n, t in talk.speech_of().items() if n in talk.closed}
    total = sum(len(t) for t in heard.values())
    if not total:
        return None
    sents = [(n, x) for n, t in heard.items() for x in sentences(t)]
    core = [n for n in graph.nodes if n.kind in ("thesis", "claim") and talk.heard_all(n.slide_nos)]
    basis = {}
    for node in core:
        nos = [int(x) for x in node.slide_nos or []]
        share = sum(len(heard.get(x, "")) for x in nos) / total
        hits = [no for no, x in sents if ES.speech_cover(node.label, x) >= 0.5]
        basis[node.id] = (share, len(hits), len(set(hits) & set(nos)) / max(1, len(nos)))
    top_m = max((b[1] for b in basis.values()), default=0)
    raw = {k: _W_TIME * min(1.0, b[0]) + _W_MENTION * (b[1] / top_m if top_m else 0.0) + _W_COVER * b[2] for k, b in basis.items()}
    top = max(raw.values(), default=0.0)
    if top <= 0:
        return None
    items = [SimpleNamespace(node_id=n.id, verdict="", contra_kind="", evidence="", doc_weight=float(n.weight or 0),
                             speech_weight=round(raw[n.id] / top, 3)) for n in core]
    return SimpleNamespace(items=items)


def new_signals(talk: LiveTalk, graph, slides: dict, lines=None, alignment=None) -> list[dict]:
    """
    다 들은 장의 핵심 노드 신호 중 아직 후보를 안 만든 것 — 장을 넘길 때마다 부른다. 노드의 장을 다 들었을 때만(heard_all).
    정합(alignment)이 없으면 「결론만 말하고 이유를 건너뜀」 만 잡힌다(발표 중엔 정합이 없다). 발표가 끝나 정합이 오면 흐림·어긋남도.
    """
    speech_of = talk.speech_of()
    if not speech_of:
        return []
    by_id = {n.id: n for n in graph.nodes}
    if alignment is None and (os.environ.get("QA_LIVE_PSEUDO") or "1").strip().lower() not in ("0", "false", "off", "no"):
        alignment = pseudo_alignment(talk, graph)
    sigs = ES.voice_signals(graph, slides, speech_of, alignment, [], lines)
    done = set(talk.done_sigs)
    out = [s for s in sigs if sig_key(s) not in done and talk.heard_all((by_id.get(s["node_id"]).slide_nos or [])
                                                                        if by_id.get(s["node_id"]) else [])]
    # 아직 후보를 안 만든 장의 신호를 먼저 — 라운드 상한에 걸려도 발표 뒷장까지 고르게 (같은 장 신호가 앞을 다 먹지 않게)
    covered = {k.rsplit("@", 1)[-1] for k in talk.done_sigs if "@" in k}
    out = [s for _, s in sorted(enumerate(out), key=lambda x: (str(x[1].get("slide_no")) in covered, x[0]))]
    for i, s in enumerate(out, 1):
        s["id"] = f"V{i}"
    return out


__all__ = ["LiveTalk", "new_signals", "pseudo_alignment", "speech_digest", "slide_gist", "sig_key", "sentences"]
