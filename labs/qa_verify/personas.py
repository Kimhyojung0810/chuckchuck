"""
자동 페르소나 — 덱과 질문만 보고 **코드가** 발표자 답 대본을 만든다 (LLM 없음, 질문별 손 답안 없음).

labs/qa_convo 는 덱마다 사람이 답안 JSON 을 썼다. 덱이 바뀌면 답안을 다시 써야 해서 되풀이해 돌릴 수 없었다.
여기서는 질문의 근거 줄(대상 저장소의 `_reason.evidence` · `_evidence.ranked_quotes` 가 있으면 그것, 없으면 줄 단위 겹침)을
입말로 이어 **좋은 답**을 만들고, 거기서 한 곳만 바꿔(대상의 `_traps` 전제 생성기 · 없으면 숫자·방향·대비 뒤집기) 오답을 만든다.

페르소나 (기대는 conversation.py 가 판정한다)
- GOOD            근거 줄을 입말로 — 2턴 안에 통과(good 또는 70점 이상)
- PARTIAL→COMPLETE 좋은 답의 앞 절반 → 되물음 뒤 나머지 — 2턴째 통과, 그 뒤 되물음 없음
- WRONG           좋은 답에서 사실 하나를 뒤집음 — 통과 못 하고 칭찬 없음 → GOOD 로 통과
- OFFTOPIC        다른 장(없으면 다른 덱)의 줄 — wrong 또는 「질문과 다른 이야기」
- ONEWORD         개념 이름 한 낱말 — 통과 못 함
- TRAP_AGREE / TRAP_CORRECT  함정 전제를 되뇜(통과 못 함 · 「질문의 전제부터 확인해 보세요」) / 자료의 사실(통과)
- DUNNO           「모르겠어요」 → 자료가 세운 쪽 보기 → 또 「모르겠어요」 → 발판·해설
- HINTS           힌트 사다리를 끝까지 연 뒤 좋은 답

`Helpers` 는 대상 저장소의 함수를 주입받는 자리다 — 비어 있으면 여기 규칙(textkit)으로 떨어진다. 순수 모듈이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from . import textkit as T

#: 좋은 답에 이어 붙일 자료 줄 수 · 글자 상한. 화면 답칸 한 번에 말할 만한 길이.
GOOD_LINES_MAX = 3
GOOD_CHARS_MAX = 190
#: 근거·이유를 묻는 질문 (대상의 `_reason.asks_reason` 이 없을 때의 잣대).
_ASK_REASON_RE = re.compile(r"근거|이유|(?<![가-힣])왜(?![가-힣])|어째서|때문|원인|결론지")
_IMPORTANCE_RE = re.compile(r"왜\s*중요|중요한\s*이유|중요성")
#: 자료 밖을 묻는 질문 — 골자가 「자료에 나와 있지 않아요」 로 다시 쓰였거나 이유(why)가 그렇게 말한다.
_OUT_OF_DECK_RE = re.compile(r"자료에\s*(?:나와\s*있지|명시되지|없|제시되지|언급되지)")
FRAMES = ("자료에서는", "자료를 보면", "슬라이드에서는")
#: 다른 덱의 말 — 같은 덱에서 무관한 줄을 못 찾았을 때. 어느 발표와도 안 겹치는 분야로 둔다.
FOREIGN = (
    "저희 팀은 지난 분기에 물류 창고 세 곳의 재고 회전율을 비교했고, 동절기 배송 지연이 반품률을 끌어올린다는 결론을 얻었어요.",
    "동네 도서관 야간 개방을 시범으로 해 봤더니 평일 저녁 이용자가 늘었고, 좌석 예약제를 같이 두니 민원이 줄었어요.",
    "반려식물 물 주기는 흙 겉면이 마른 뒤가 좋고, 화분 밑 받침에 고인 물은 바로 버려야 뿌리가 썩지 않아요.",
)


@dataclass
class Helpers:
    """대상 저장소에서 주입받는 함수. 없는 것은 None — 페르소나가 제 규칙으로 떨어진다."""
    slide_units: Callable[[str], list[str]] | None = None
    #: (label, summary, [(장, 원문)], question, k) → [(장, 줄)]
    ranked_quotes: Callable[..., list[tuple[int, str]]] | None = None
    #: (question dict, {장: 원문}, anchors) → [(장, 이유 줄)] — `_reason.evidence` 를 감싼 것
    reason_lines: Callable[..., list[tuple[int, str]]] | None = None
    #: (label, anchors, slide_doc dict) → [{"kind","premise","fact","line"}] — `_traps.candidates` 를 감싼 것
    trap_candidates: Callable[..., list[dict]] | None = None
    asks_reason: Callable[[str], bool] | None = None


# ---------------------------------------------------------------------------
# 입말
# ---------------------------------------------------------------------------

def speak(lines: list[str], seed: int = 0, *, reason: bool = False, addon: bool = False) -> str:
    """자료 줄 → 입말 답 한 덩이. 줄 순서를 바꾸고(seed) 조사를 살짝 바꾼다 — 뜻은 그대로다."""
    parts = [T.reported(x) for x in lines if T.reported(x)]
    if not parts:
        return ""
    if len(parts) >= 2 and seed % 2 == 1:
        parts = parts[1:] + parts[:1]
    if seed % 3 == 1:
        parts[0] = T.swap_topic_particle(parts[0])
    frame = "그리고" if addon else FRAMES[seed % len(FRAMES)]
    body = " ".join(f"{p} 하고," for p in parts[:-1])
    text = f"{frame} {body + ' ' if body else ''}{parts[-1]} 해요."
    if reason:
        text += " 그래서 그렇게 결론 낸 거예요."
    return re.sub(r"\s+", " ", text).strip()


def speak_claim(sentence: str, seed: int = 0) -> str:
    """골자·사실 한 문장을 발표자 말투로 (탐침·자료 밖 질문용). 해요체면 그대로, 아니면 「…라고 봐요」."""
    s = T.clean_line(sentence)
    if not s:
        return ""
    if re.search(r"(?:요|죠)$", s):
        out = s + "."
    else:
        out = f"{T.reported(s)} 봐요."
    return T.swap_topic_particle(out) if seed % 3 == 1 else out


# ---------------------------------------------------------------------------
# 근거 줄 고르기
# ---------------------------------------------------------------------------

def _anchors(q: dict, texts: dict[int, str]) -> list[int]:
    nos = [int(n) for n in q.get("slide_nos") or [] if int(n) in texts]
    ev = int(q.get("evidence_slide_no") or 0)
    if ev in texts and ev not in nos:
        nos.append(ev)
    return nos or sorted(texts)


#: 문장이 안 끝난 꼬리 — 조건·연결 어미·조사·제목 표지(「…란」「(%)」「:」). 답의 한 조각으로 쓰면 말이 끊긴다.
_OPEN_TAIL_RE = re.compile(r"(?:면|고|며|는데|지만|란|은|는|을|를|의|에|와|과|로|으로|:|\(%\)|\([^)]*단위[^)]*\))$")


def usable(line: str) -> bool:
    """좋은 답의 재료가 될 줄인가 — 캡션·물음·표지 문구·끊긴 꼬리가 아니다."""
    s = (line or "").strip()
    return (len(s) >= 8 and "?" not in s and not T.is_caption(s) and not T.is_meta(s)
            and not _OPEN_TAIL_RE.search(s) and len(T.tokens(s)) >= 2)


def _sentence_like(line: str) -> bool:
    """서술어로 끝나거나 수치를 담은 줄 — 제목 한 줄(「혈당 부하 계산」)보다 답의 재료로 낫다."""
    return not T.plain_form(line)[1] or bool(T.numbers(line))


def _units(texts: dict[int, str], anchors: list[int], helpers: Helpers) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for no in anchors:
        raw = texts.get(no, "")
        got: list[str] = []
        if helpers.slide_units is not None:
            try:
                got = list(helpers.slide_units(raw))
            except Exception:  # noqa: BLE001 — 대상 함수가 옛 모양이면 제 규칙으로
                got = []
        if not got:
            got = [line for _, line in T.deck_lines({"slides": [{"slide_no": no, "raw_text": raw}]})]
        out += [(no, T.clean_line(T.table_text(u))) for u in got]
    return [(n, u) for n, u in out if usable(u)]


def _in_deck(line: str, texts: dict[int, str]) -> bool:
    sq = T.squash(line)
    return len(sq) >= 4 and any(sq in T.squash(t) for t in texts.values())


def asks_reason(question: str, helpers: Helpers | None = None) -> bool:
    if helpers is not None and helpers.asks_reason is not None:
        try:
            return bool(helpers.asks_reason(question))
        except Exception:  # noqa: BLE001
            pass
    return bool(_ASK_REASON_RE.search(question or "")) and not _IMPORTANCE_RE.search(question or "")


def out_of_deck(q: dict) -> bool:
    """자료 밖을 묻는 질문 — 정직한 답은 「자료에 없어요」 다."""
    checks = ((q.get("basis") or {}).get("checks") or [])
    return "gist_out_of_deck" in checks or bool(_OUT_OF_DECK_RE.search(f"{q.get('answer_gist', '')} {q.get('why', '')}"))


def _rank(cands: list[tuple[int, str]], question: str, gist: str) -> list[tuple[int, str]]:
    scored = []
    for i, (no, line) in enumerate(cands):
        rel = T.overlap(line, question) + T.overlap(line, gist)
        scored.append(((rel >= 1, _sentence_like(line), T.overlap(line, question), T.overlap(line, gist), -i), (no, line)))
    scored.sort(key=lambda s: s[0], reverse=True)
    return [x for _, x in scored]


def good_lines(q: dict, texts: dict[int, str], helpers: Helpers) -> tuple[list[tuple[int, str]], str]:
    """좋은 답의 재료가 될 자료 줄 (장, 줄)과 출처 이름. 자료 줄만 쓴다 — 골자는 틀릴 수 있다(감사 §1)."""
    question, gist, label = q.get("question", ""), q.get("answer_gist", ""), q.get("label", "")
    anchors = _anchors(q, texts)
    basis = q.get("basis") or {}
    picked: list[tuple[int, str]] = []
    source = ""
    reason = [(int(e.get("slide_no") or 0), T.clean_line(e.get("quote", ""))) for e in basis.get("reason") or []
              if e.get("quote")]
    if reason:
        picked, source = reason[:2], "basis_reason"
    elif asks_reason(question, helpers) and helpers.reason_lines is not None:
        try:
            got = helpers.reason_lines(q, texts, anchors)
        except Exception:  # noqa: BLE001
            got = []
        if got:
            picked, source = [(n, T.clean_line(x)) for n, x in got[:2]], "reason_evidence"
    ranked: list[tuple[int, str]] = []
    if helpers.ranked_quotes is not None:
        try:
            ranked = [(n, T.clean_line(T.table_text(x))) for n, x in helpers.ranked_quotes(
                label, "", [(no, texts[no]) for no in anchors], question, 5)]
        except Exception:  # noqa: BLE001
            ranked = []
    units = _units(texts, anchors, helpers)
    pool = [c for c in _rank([r for r in ranked if usable(r[1])], question, gist) + _rank(units, question, gist)
            if c[1] and not c[1].endswith("…")]
    ev = T.clean_line(T.table_text(q.get("evidence_quote", "")))
    if ev and not ev.endswith("…") and _in_deck(ev, texts):
        # 인용이 줄의 조각이면(폭으로 꺾인 줄) 그 줄 전체를 쓴다
        whole = next((u for u in units if T.squash(ev) in T.squash(u[1])), None)
        if whole is not None:
            pool.insert(0, whole)
        elif usable(ev):
            pool.insert(0, (int(q.get("evidence_slide_no") or 0), ev))
    # 맨 앞 줄은 **질문**(과 개념 이름)에 가장 많이 겹치는 줄 — 골자 전체와 겹침으로 고르면 표의 다른 행이 이긴다
    if pool and not picked:
        first = max(pool, key=lambda c: (T.overlap(c[1], question) + 2 * T.overlap(c[1], label), T.overlap(c[1], gist)))
        if T.overlap(first[1], question) + T.overlap(first[1], label) >= 1:
            picked.append(first)
    # 골자 요소마다 가장 많이 겹치는 자료 줄 — 요소를 다 덮어야 판정이 good 을 준다. 근거 장 밖(다른 장)의 줄은 더 많이 겹쳐야 쓴다.
    elsewhere = [c for c in _units(texts, [n for n in sorted(texts) if n not in anchors], helpers)]
    parts = [p for p in (q.get("answer_gist_parts") or []) if p] or [gist]
    for part in parts:
        scored = [((T.overlap(c[1], part) - (0 if c in pool else 1), T.overlap(c[1], question)), c) for c in pool + elsewhere]
        best = max(scored, key=lambda x: x[0], default=None)
        if best and best[0][0] >= 2 and best[1] not in picked:
            picked.append(best[1])
    for c in pool:
        if len(picked) >= GOOD_LINES_MAX:
            break
        if c not in picked and (T.overlap(c[1], question) + T.overlap(c[1], gist)) >= 1 and _sentence_like(c[1]):
            picked.append(c)
    if not source:
        source = "ranked_quotes" if ranked else "units"
    out, seen, total = [], set(), 0
    for no, line in picked:
        key = T.squash(line)
        if not key or key in seen or any(key in s or s in key for s in seen):
            continue
        if total + len(line) > GOOD_CHARS_MAX and out:
            break
        seen.add(key)
        out.append((no, line))
        total += len(line)
    if not out and pool:
        out = [pool[0]]
    return out[:GOOD_LINES_MAX], source


# ---------------------------------------------------------------------------
# 한 곳 뒤집기 · 무관한 줄 · 대비 쌍
# ---------------------------------------------------------------------------

def wrong_from(lines: list[tuple[int, str]], q: dict, slide_doc: dict, helpers: Helpers) -> dict | None:
    """좋은 답의 줄 가운데 하나를 뒤집은 줄 목록 — 대상 `_traps` 전제 생성기를 먼저, 없으면 숫자·방향·대비."""
    texts = T.slide_texts(slide_doc)
    deck = "\n".join(texts.values())
    if helpers.trap_candidates is not None:
        try:
            cands = helpers.trap_candidates(q.get("label", ""), _anchors(q, texts), slide_doc) or []
        except Exception:  # noqa: BLE001
            cands = []
        for c in cands:
            src = T.clean_line(c.get("line", ""))
            for i, (_, line) in enumerate(lines):
                if src and (T.squash(src) in T.squash(line) or T.coverage(line, src) >= 0.6):
                    premise = T.clean_line(re.sub(r"^표에서\s+", "", c.get("premise", "")))
                    new = [x for _, x in lines]
                    new[i] = premise
                    return {"lines": new, "kind": c.get("kind", ""), "from": src, "to": premise, "via": "traps"}
    for kind in T.FLIP_KINDS:                      # 숫자가 어느 줄에든 있으면 숫자를 — 틀린 곳이 가장 또렷하다
        for i, (_, line) in enumerate(lines):
            got = T.one_fact_flip(line, avoid=deck, kinds=(kind,))
            if got:
                new = [x for _, x in lines]
                new[i] = got[0]
                return {"lines": new, "kind": got[1], "from": got[2], "to": got[3], "via": "textkit"}
    return None


def offtopic_line(q: dict, texts: dict[int, str], seed: int, avoid: str) -> tuple[str, str]:
    """(무관한 말, 출처). 근거 장 밖의 줄 가운데 질문·골자·좋은 답과 가장 안 겹치는 것. 없으면 다른 덱의 말."""
    anchors = set(_anchors(q, texts))
    cands = []
    for no, line in T.deck_lines({"slides": [{"slide_no": n, "raw_text": t} for n, t in texts.items()]}):
        line = T.table_text(line)
        if no in anchors or no == min(texts, default=0) or len(line) < 14 or not usable(line) or "|" in line:
            continue
        cands.append((T.overlap(line, avoid), -len(line), line))
    cands.sort()
    if cands and cands[0][0] == 0:
        return cands[0][2], "same_deck"
    return FOREIGN[seed % len(FOREIGN)], "other_deck"


def contrast_pair(q: dict, lines: list[tuple[int, str]]) -> tuple[str, str]:
    """「모르겠어요」 보기의 정답 쪽 — (자료가 세운 쪽, 부정한 쪽). F-08 이 실어 둔 대비가 먼저, 없으면 근거 줄의 「X 아니라 Y」."""
    b = q.get("basis") or {}
    if len(b.get("contrast") or []) == 2 and all(b["contrast"]):
        return str(b["contrast"][0]), str(b["contrast"][1])
    for text in [q.get("evidence_quote", "")] + [x for _, x in lines]:
        sides = T.contrast_sides(text or "")
        if sides and T.noun_phrase_ok(sides[0]) and T.noun_phrase_ok(sides[1]):
            return sides[1], sides[0]
    return "", ""


def no_binary_expected(q: dict) -> bool:
    """
    「모르겠어요」 첫 단계에 보기 둘이 **없어야 맞는** 질문 (09-30 WP-J3 정책) — 입장이 서지 않는 탐침(형제 우선순위)과 자리 표시 골자
    (코드 틀·자료 줄 이어 붙이기)는 검증된 대비 쌍이 없으면 위치 단계다. 가린 낱말 쌍을 만들지 않는 것이 맞다.
    """
    b = q.get("basis") or {}
    if len(b.get("contrast") or []) == 2:
        return False
    if ((b.get("probe") or {}).get("kind") or "") == "sibling_priority":
        return True
    checks = set(b.get("checks") or [])
    rebuilt = {"gist_probe_code", "gist_probe_rebuilt", "gist_rebuilt_trap"}
    return (bool({"gist_template", "fallback_template"} & checks) and not (rebuilt & checks)) or \
        (q.get("answer_gist") or "").startswith("자료는 이렇게 말해요")


def pick_chip(chips: list[str], persona: dict) -> int:
    """
    보기 가운데 자료가 **세운** 쪽. 대비 쌍을 알면 그것, 모르면 좋은 답과 더 겹치고 부정된 절에 없는 쪽.
    탐침 질문의 입장 보기 쌍(「늘 맞아요」/「조건이 붙어요」)이면 잣대의 입장 정의(`textkit.STANCE_TRUTH`)로 맞는 쪽을 고른다 (09-30 WP-J3).
    """
    kind = persona.get("probe") or ""
    if kind and T.stance_pair(chips):
        right = T.stance_correct(chips, kind)
        if right in chips:
            return chips.index(right)
    affirmed = persona.get("dunno_affirmed", "")
    good = persona.get("answers", {}).get("good", "")
    negated = set(T.negated_terms(good)) | set(T.tokens(persona.get("dunno_negated", "")))
    best, idx = None, 0
    for i, c in enumerate(chips):
        score = (
            3 if affirmed and T.overlap(c, affirmed) else 0,
            -3 if any(T._same(t, n) for t in T.tokens(c) for n in negated) else 0,
            T.overlap(c, good),
        )
        if best is None or score > best:
            best, idx = score, i
    return idx


# ---------------------------------------------------------------------------
# 한 질문의 페르소나 묶음
# ---------------------------------------------------------------------------

#: 절이 끝나는 자리 — 연결 어미 뒤 (「…하고 」「…이며 」「…지만, 」). 「최고 성과」 의 「고」 같은 명사 끝은 아니다.
_CLAUSE_END_RE = re.compile(r"(?:하고|되고|이고|았고|었고|였고|했고|지고|하며|이며|되며|면서|지만|는데|어서|아서|으로|며),?\s+")


def _split_half(line: str) -> tuple[str, str]:
    """(앞 절, 나머지). 절 경계가 없으면 쉼표, 그것도 없으면 나누지 않는다."""
    commas = [m.start() for m in re.finditer(",", line)]
    for pat in (_CLAUSE_END_RE, re.compile(r",\s+")):
        for m in pat.finditer(line):
            listy = pat.pattern.startswith(",") and any(0 < abs(c - m.start()) <= 25 for c in commas)
            if 8 <= m.start() <= len(line) - 8 and not listy:        # 「A, B, C」 나열 가운데서는 자르지 않는다
                return line[: m.end()].rstrip(" ,"), line[m.end():]
    return line, ""


def _trap_answers(tp: dict, seed: int) -> dict:
    premise = T.clean_line(re.sub(r"^표에서\s+", "", tp.get("premise", "")))
    fact = T.clean_line(tp.get("fact", ""))
    fact_body = re.sub(r"^표에서\s+", "", fact)
    return {
        "trap_agree": f"{T.reported(premise)} 해요. 그래서 그 부분이 제 발표의 핵심 근거예요." if premise else "",
        "trap_agree_hedge": f"네, {T.plain_form(premise)[0]} 맞아요. 오히려 생각보다 더 그래요." if premise else "",
        "trap_correct": (f"질문에서 말한 것과 달리, 자료{' 표' if fact.startswith('표에서') else ''}에는 "
                         f"{T.reported(fact_body)} 나와 있어요.") if fact_body else "",
    }


def build(q: dict, slide_doc: dict, *, others: list[dict] | None = None, helpers: Helpers | None = None) -> dict:
    """질문 하나 → 페르소나 대본 묶음 (answers · 대비 쌍 · 출처 · 뒤집은 곳)."""
    helpers = helpers or Helpers()
    texts = T.slide_texts(slide_doc)
    seed = T.seed_of(q.get("id", ""), q.get("question", ""))
    label = T.clean_line(q.get("label", ""))
    reason = asks_reason(q.get("question", ""), helpers)
    tp = q.get("trap_premise") or None
    probe = (q.get("basis") or {}).get("probe")
    lines, source = good_lines(q, texts, helpers)
    plain = [x for _, x in lines]
    answers: dict[str, str] = {}
    if tp:
        answers.update(_trap_answers(tp, seed))
        answers["good"] = answers["trap_correct"]
        source = "trap_fact"
    elif out_of_deck(q):
        first = plain[0] if plain else ""
        answers["good"] = "자료에는 그 내용이 나와 있지 않아요." + (f" 자료가 말하는 건 {T.reported(first)} 하는 데까지예요." if first else "")
        # 빈틈을 묻는 질문(「…없는데, 어떻게 해결/보강하려는지」)의 좋은 답은 없다는 인정 + 보강 계획이다 — 인정만 하면 부분 점수가 맞다
        # (09-30 표준 단계: 「자료에 없어요」 만 한 답을 정답 대조군으로 세어 판정이 옳게 준 55 를 실패로 셌다).
        if re.search(r"어떻게|해결|보강|개선|근거|뒷받침", q.get("question", "")):
            answers["good"] += " 그래서 설문이나 통계, 비교 자료를 찾아 보강할게요."
        source = "honest"
    elif probe:
        answers["good"] = speak_claim(q.get("answer_gist", ""), seed)
        source = "gist"
    else:
        answers["good"] = speak(plain, seed, reason=reason)
    # 둘째 턴 — 좋은 답을 한 번 더(다른 순서) 또는 줄을 보태서
    answers["good_more"] = speak(plain[1:] + plain[:1], seed + 1, addon=True) if len(plain) >= 2 else speak(plain, seed + 1)
    if source == "trap_fact":
        pass                         # 함정 질문은 TRAP_AGREE/TRAP_CORRECT 가 맡는다
    elif source in ("gist", "honest"):
        head, rest = _split_half(answers["good"].rstrip("."))
        answers["partial"] = head + ("요." if not re.search(r"요$", head) and rest else ".") if rest else answers["good"]
        answers["complete"] = ("그리고 " + rest.rstrip(".") + ".") if rest else answers["good"]
    elif len(plain) >= 2:
        answers["partial"] = speak(plain[:1], seed)
        answers["complete"] = speak(plain[1:], seed, addon=True)
    elif plain:
        head, rest = _split_half(plain[0])
        answers["partial"] = speak([head], seed)
        answers["complete"] = speak([rest], seed, addon=True) if rest else answers["good"]
    flip = None if (tp or not plain) else wrong_from(lines, q, slide_doc, helpers)
    if flip:
        answers["wrong"] = speak(flip["lines"], seed, reason=reason)
    avoid = " ".join([q.get("question", ""), q.get("answer_gist", ""), label, answers.get("good", "")])
    off, off_src = offtopic_line(q, texts, seed, avoid)
    answers["offtopic"] = speak([off], seed) if off_src == "same_deck" else off
    answers["one_word"] = label.split("(")[0].strip()
    extra = next((t for t in T.tokens(" ".join(plain)) if not T.overlap(t, label) and not re.match(r"\d", t)), "")
    answers["two_word"] = f"{answers['one_word']} {extra}".strip() if extra else answers["one_word"]
    affirmed, negated = contrast_pair(q, lines)
    return {
        "qid": q.get("id", ""), "label": label, "question": q.get("question", ""), "trap": bool(tp),
        "probe": (probe or {}).get("kind", "") if isinstance(probe, dict) else "",
        "reason_question": reason, "out_of_deck": out_of_deck(q),
        "lines": [{"slide_no": n, "text": x} for n, x in lines], "good_source": source,
        "answers": {k: v for k, v in answers.items() if v},
        "wrong_flip": flip, "offtopic_source": off_src,
        "dunno_affirmed": affirmed, "dunno_negated": negated,
        "trap_premise": tp,
    }


def build_all(questions: list[dict], slide_doc: dict, helpers: Helpers | None = None) -> list[dict]:
    return [build(q, slide_doc, others=[o for o in questions if o is not q], helpers=helpers) for q in questions]
