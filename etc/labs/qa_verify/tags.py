"""
턴 자동 태그 — 코치가 한 말(말풍선 · 판정 JSON)에서 규칙으로 잡히는 문제 후보. 순수 함수 (LLM · 파일 없음).

09-29 대화 감사(docs/review/2026-09-29_QA_근거검증/convo/report.md)의 13 분류를 태그로 옮겼다. 태그 이름은 「분류.항목」:

  ground.*      근거 — 뒤집힌·자료에 없는 골자를 완성 문장으로 보임(§1) · 함정 사실 누설(§7) · 힌트 조각(§11)
  consistency.* 일관성 — 맞는 답 강등(§2) · 느슨한 통과·칭찬(§3) · 이미 말한 결손 · 닫으며 결손(§5)
  relevance.*   관련성 — 자료에 없는 결손(§4) · 되물음 붕괴(§6) · 보기 부적절(§8) · 다른 질문 새어 듦(§10)
  tone.*        말투 — 해요체 변환 오류(아녀요·보예요) · 합쇼체 · 높임(주셔서) · 3인칭 · 내부 표기 · 영문 캡션 · 잘림(§9)
  ux.*          화면 — 순번 불일치 · 강제 종료를 지킨 것으로 셈 · 폴백 react · 긴 react(§10)

가드 문구는 대상 저장소(f09_judge) 의 코드 문구를 대조한다 — 문구가 바뀌면 여기를 같이 고친다.
"""

from __future__ import annotations

import re

from . import textkit as T

# ---------------------------------------------------------------------------
# 문구 · 식
# ---------------------------------------------------------------------------

OFF_TOPIC_LEAD = "질문과 다른 이야기"
TRAP_AGREED_LEAD = "질문의 전제부터 확인해 보세요"
#: 코드 가드가 등급을 내렸을 때의 react 문구 (f09 `_OFF_TOPIC_REACT` · `_TRAP_AGREED_REACT` · `_FOCUS_MISS_REACT` ·
#: `_DECK_CONFLICT_REACT` · `_SELF_OPPOSED_REACT` · `_REASON_MISS_REACT`)
GUARD_MARKS = (
    (OFF_TOPIC_LEAD, "off_topic"),
    (TRAP_AGREED_LEAD, "trap_agreed"),
    ("에 대한 답으로는 조금 멀어요", "focus_miss"),
    ("어긋나는 부분이 있어요", "deck_conflict"),
    ("방향이 거꾸로인 부분이 있어요", "self_opposed"),
    ("질문은 그렇게 결론 낸 이유를 물어요", "reason_miss"),
)
#: 코드 폴백 react (f09 `_REACT_BY_VERDICT`) — LLM react 가 비었거나 버려진 것.
FALLBACK_REACTS = frozenset({
    "네, 그 설명이면 충분해요.", "요지는 잡았어요. 한 가지만 더 짚어 주세요.", "그 부분은 자료와 맞지 않아요.",
    "지금 답변만으로는 판단하기 어려워요.",
})
PRAISE_RE = re.compile(r"정확해요|정확합니다|맞아요|맞습니다|잘 짚|훌륭|좋은 답|잘 설명|제대로 설명|좋아요|완벽")
#: 「X은 맞아요」 — 칭찬의 대상 X 가 누적 답에 있어야 한다.
PRAISE_OBJ_RE = re.compile(r"([^.!?]{4,60}?)(?:은|는|이|가|점은|부분은)\s*(?:맞아요|정확해요|잘 짚었어요|좋아요)")
HONORIFIC_RE = re.compile(r"하신|계신|계시|주실|주시|하셨|셨어요|셨나요|시겠|께서|여쭈|십시오|주셔서|하십니다|보십시오")
HAPSYO_RE = re.compile(r"(?:습니다|입니다|합니다|됩니다|습니까|십시오|았습니다|었습니다)(?=[\s.,!?»」)'\"]|$)")
#: 해요체 변환이 깨진 꼴 (감사 §9: 아닙니다→아녀요 · 보입니다→보예요) + 흔한 잘못
BAD_HAEYO_RE = re.compile(r"아녀요|보예요|[가-힣]녀요(?=[\s.,!?]|$)|되요(?=[\s.,!?]|$)|됬|했요|하요(?=[\s.,!?]|$)")
THIRD_PERSON_RE = re.compile(r"발표자(?:는|가|께서)\s")
INTERNAL_RE = re.compile(r"「S\d+」|(?<![A-Za-z0-9])S\d{1,2}(?![0-9A-Za-z])|\b[a-z]+_[a-z_]+\b|\bnode[_-]?\d+|\bq\d{1,2}\b|\bslide_no\b")
ENGLISH_RE = re.compile(r"Chart Type|Figure Type|The (?:bar |line )?chart|[A-Za-z]{3,}(?:\s+[A-Za-z]{2,}){3,}")
TRUNC_RE = re.compile(r"(?:…|\.\.\.)\s*$")
UI_META_RE = re.compile(r"이어서 묻습니다|좁혀서 다시 묻습니다")
#: 가드 사유 문자열이 되물음·결손에 새어 나온 꼴 (감사 §6)
GUARD_REASON_RE = re.compile(r"질문이 묻는 것:|어긋난 곳:|설명이 부족합니다|자료 \d+장과 어긋나는|방향이 거꾸로인|다시 볼 곳:")
#: 코드 되물음 틀 (f09 `_FOLLOWUP_BY_POINT` · `_FOLLOWUP_BY_TIER` · `_FOLLOWUP_GENERIC`)
FOLLOWUP_TEMPLATE_RE = re.compile(
    r"^(?P<point>.+?) — (?:이 부분은 어떻게 봐요\?|이건 자료에 있었나요, 없었나요\?|이걸 뒷받침할 근거를 하나만 더 들어 주세요\.)$"
    r"|^(?P<point2>.+?) 때문이라고 보면 될까요\?$")
ORDINAL_RE = re.compile(r"(\d+)번째 답변")
REACT_MAX = 120
#: 완성 문장(골자)의 내용 낱말 가운데 자료에 있어야 하는 몫 — 이보다 적으면 「자료에 없는 말을 정답으로」 보인 것이다.
#: 탐침 질문의 골자는 자료 줄을 따져 묻는 추론이라 낱말이 좀 새도 된다 — 그래서 절반이 아니라 40%.
GIST_GROUNDED_MIN = 0.4
#: 「통과」 해야 하는 페르소나 턴 · 통과하면 안 되는 턴
PASS_STEPS = frozenset({"good", "good_more", "complete", "trap_correct"})
FAIL_STEPS = frozenset({"wrong", "offtopic", "one_word", "trap_agree"})


def _judge_texts(j: dict) -> list[str]:
    return [str(j.get(k) or "") for k in ("react", "followup", "summary_sentence", "explanation")] + \
        [str(x) for x in j.get("missing_points") or []]


def coach_texts(turn: dict) -> list[str]:
    """코치(상대) 쪽 글 전부 — 새 말풍선(내 말 빼고) + 판정 JSON 의 문장들."""
    out = [b.get("text", "") for b in turn.get("bubbles") or [] if b.get("who") not in ("me",)]
    j = turn.get("judge") or {}
    return [t for t in out + _judge_texts(j) if t]


def passed(j: dict | None) -> bool:
    if not j or j.get("coach_stage"):
        return False
    if j.get("passed") is not None:
        return bool(j["passed"])
    return j.get("verdict") == "good" or int(j.get("score") or 0) >= 70


def guard_of(react: str) -> str:
    for mark, name in GUARD_MARKS:
        if mark in (react or ""):
            return name
    return ""


def _tag(tag: str, detail: str = "", quote: str = "") -> dict:
    return {"tag": tag, "detail": detail[:160], "quote": (quote or "")[:200]}


# ---------------------------------------------------------------------------
# 말투
# ---------------------------------------------------------------------------

def tone_tags(texts: list[str]) -> list[dict]:
    out: list[dict] = []
    joined = "\n".join(texts)
    if UI_META_RE.search(joined):
        out.append(_tag("tone.ui_meta_hapsyo", UI_META_RE.search(joined).group(0)))
        joined = UI_META_RE.sub("", joined)
    outside = T.strip_quotes(joined)
    m = BAD_HAEYO_RE.search(outside)
    if m:
        out.append(_tag("tone.haeyo_broken", m.group(0), _around(outside, m)))
    hs = HAPSYO_RE.findall(outside)
    if hs:
        m = HAPSYO_RE.search(outside)
        out.append(_tag("tone.hapsyo", ",".join(sorted(set(hs))), _around(outside, m)))
    m = HONORIFIC_RE.search(outside)
    if m:
        out.append(_tag("tone.honorific", m.group(0), _around(outside, m)))
    m = THIRD_PERSON_RE.search(outside)
    if m:
        out.append(_tag("tone.third_person", m.group(0).strip(), _around(outside, m)))
    ids = [x for x in INTERNAL_RE.findall(joined)]
    if ids:
        out.append(_tag("tone.internal_id", ",".join(sorted(set(ids)))[:60], ""))
    m = ENGLISH_RE.search(outside)
    if m:
        out.append(_tag("tone.english", m.group(0)[:50], _around(outside, m)))
    for t in texts:
        for line in t.splitlines():
            if TRUNC_RE.search(line.strip()) and len(line.strip()) > 10:
                out.append(_tag("tone.truncated", line.strip()[-40:], line.strip()))
                break
        else:
            continue
        break
    return out


def _around(text: str, m: re.Match | None, width: int = 50) -> str:
    if not m:
        return ""
    a, b = max(0, m.start() - width), min(len(text), m.end() + width)
    return text[a:b].replace("\n", " ")


# ---------------------------------------------------------------------------
# 판정 한 턴
# ---------------------------------------------------------------------------

def missing_tags(j: dict, deck: str, cumulative: str) -> list[dict]:
    out = []
    for p in [str(x) for x in j.get("missing_points") or [] if str(x).strip()]:
        if len(T.tokens(p)) >= 2 and T.coverage(p, deck) < 0.4:
            out.append(_tag("relevance.missing_not_in_deck", f"자료 겹침 {T.coverage(p, deck):.0%}", p))
        if cumulative and len(T.tokens(p)) >= 2 and T.coverage(p, cumulative) >= 0.6:
            out.append(_tag("consistency.missing_already_said", f"누적 답 겹침 {T.coverage(p, cumulative):.0%}", p))
    return out


def followup_tags(j: dict) -> list[dict]:
    f = str(j.get("followup") or "")
    if not f:
        return []
    out = []
    m = GUARD_REASON_RE.search(f)
    if m:
        out.append(_tag("relevance.followup_glue", f"가드 사유 「{m.group(0)}」", f))
    t = FOLLOWUP_TEMPLATE_RE.match(f.strip())
    if t:
        point = (t.group("point") or t.group("point2") or "").strip()
        if re.search(r"(?:다|요|니다)[.!]?$|[.?!]$", point) or len(point) > 40 or "," in point or not T.noun_like(point):
            out.append(_tag("relevance.followup_glue", "틀 앞자리가 명사구가 아님", f))
    if "뒷받침할 근거" in f and j.get("verdict") == "wrong":
        out.append(_tag("relevance.followup_support_wrong", "틀린 답에 근거를 더 들라고 함", f))
    return out


def choice_tags(choices: list[str], deck: str, followup: str = "") -> list[dict]:
    """
    보기 둘이 명사구인가 · 세는 단위가 아닌가 · 자료에 있는가. 되물음이 보여 준 인용 «…» 이 「X 아니라 Y」 면
    자료가 세운 쪽 Y 가 보기에 들어 있어야 한다 (둘 다 틀린 보기 — 09-29 부스 「'가지' 쪽인가요, '종목' 쪽인가요?」).
    """
    if not choices:
        return []
    # 입장 보기 쌍(탐침 질문 — 「늘 맞아요」/「조건이 붙어요」)은 자료 낱말 보기가 아니다: 명사·자료 대조 대신 입장 잣대로 본다 (09-30 WP-J3).
    kind = T.stance_pair([str(c) for c in choices])
    if kind:
        return []
    if len(choices) == 2 and all(T._STANCE_CHIP_RE.match(str(c).strip()) for c in choices):
        return [_tag("relevance.choice_invalid", "입장 보기 쌍이 아님(맞는 쪽·틀린 쪽이 하나씩 아님)", " / ".join(map(str, choices)))]
    shown = re.search(r"«([^»]+)»", followup or "")
    sides = T.contrast_sides(shown.group(1)) if shown else None
    affirmed = sides[1] if sides and T.noun_phrase_ok(sides[0]) and T.noun_phrase_ok(sides[1]) else ""
    out = []
    deck_sq = T.squash(deck)
    for c in choices:
        c = str(c)
        words = re.findall(r"[가-힣A-Za-z0-9%.]+", c)
        if len(words) == 1 and words[0] in T.BOUND_NOUNS:
            out.append(_tag("relevance.choice_invalid", "세는 단위·의존 명사", c))
        elif not T.noun_like(c):
            out.append(_tag("relevance.choice_invalid", "활용형 꼬리", c))
        elif deck_sq and T.squash(c) and T.squash(c) not in deck_sq:
            out.append(_tag("relevance.choice_invalid", "자료에 없는 말", c))
    if affirmed and len(choices) == 2 and not any(T.overlap(c, affirmed) for c in choices):
        out.append(_tag("relevance.choice_invalid", f"자료가 세운 쪽 「{affirmed}」 이 보기에 없음", " / ".join(choices)))
    return out


def praise_unsaid(react: str, cumulative: str) -> dict | None:
    """「X은 맞아요」 의 X 가 누적 답에 없다 — 말하지 않은 것을 칭찬했다 (감사 §3)."""
    m = PRAISE_OBJ_RE.search(react or "")
    if not m or not cumulative:
        return None
    obj = m.group(1)
    if len(T.tokens(obj)) >= 2 and T.coverage(obj, cumulative) < 0.34:
        return _tag("consistency.praise_unsaid", f"누적 답 겹침 {T.coverage(obj, cumulative):.0%}", react)
    return None


def trap_leak(texts: list[str], tp: dict | None, corrected: bool) -> dict | None:
    """함정 질문에서 발표자가 바로잡기 **전에** 코치가 자료의 사실(정답 단서)을 흘렸나 (감사 §7)."""
    if not tp or corrected:
        return None
    fact = T.clean_line(re.sub(r"^표에서\s+", "", tp.get("fact", "")))
    premise = tp.get("premise", "")
    joined = " ".join(texts)
    if len(T.squash(fact)) >= 8 and T.squash(fact) in T.squash(joined):
        return _tag("ground.trap_leak", "사실 줄을 그대로", fact)
    if tp.get("kind") == "number":
        right = [n for cue in tp.get("right") or [] for n in T.numbers(cue.partition("|")[0])]
        wrong = set(T.numbers(premise))
        said = set(T.numbers(joined))
        leaked = [n for n in right if n in said and n not in wrong]
        if leaked:
            return _tag("ground.trap_leak", f"정답 수치 {leaked[0]}", joined[:160])
    return None


def cross_leak(texts: list[str], mine: str, others: list[str], window: int = 10) -> dict | None:
    """다른 질문(문장·골자)의 글이 이 질문의 react·되물음에 새어 들었나 — 이 질문·자료에 없는 {window}자(공백 빼고) 이상 조각."""
    hay = T.squash(" ".join(texts))
    mine_sq = T.squash(mine)
    for o in others:
        osq = T.squash(o)
        if len(osq) < window:
            continue
        for i in range(0, len(osq) - window + 1):
            piece = osq[i:i + window]
            if piece in hay and piece not in mine_sq:
                return _tag("relevance.cross_question_leak", "다른 질문의 글 조각", o[:120])
    return None


def gist_tags(text: str, deck_lines: list[str]) -> list[dict]:
    """완성 문장(골자)이 자료와 방향이 거꾸로이거나(§1) 자료에 거의 없다."""
    out = []
    if not text:
        return out
    inv = inverted_against(text, deck_lines)
    if inv:
        out.append(_tag("ground.gist_inverted", f"자료 「{inv[0]}」 와 방향 반대", text))
    deck = "\n".join(deck_lines)
    if len(T.tokens(text)) >= 4 and T.coverage(text, deck) < GIST_GROUNDED_MIN:
        out.append(_tag("ground.gist_ungrounded", f"자료 겹침 {T.coverage(text, deck):.0%}", text))
    return out


def inverted_against(text: str, deck_lines: list[str]) -> tuple[str, str] | None:
    """글이 자료 한 줄의 방향 낱말을 **하나만** 뒤집었나 — (자료 줄, 뒤집힌 낱말). 상관 줄(둘 다 뒤집음)은 같은 뜻이다."""
    for line in deck_lines:
        words = [m.group(0) for m in T.ANTONYM_RE.finditer(line)]
        if not words:
            continue
        flips = [w for w in words if T.antonym_of(w) and T.antonym_of(w) in text and w not in text]
        keeps = [w for w in words if w in text]
        if not flips:
            continue
        context = [t for t in T.tokens(line) if not T.ANTONYM_RE.search(t)]
        if T.overlap(context, text) < 2:
            continue
        if len(words) >= 2 and len(flips) == len(words):
            continue                                  # 「멀수록 나빠진다」 ↔ 「가까울수록 좋아진다」 는 같은 말
        if flips and (keeps or len(words) == 1):
            return line, flips[0]
    return None


def turn_tags(turn: dict, ctx: dict) -> list[dict]:
    """
    한 턴의 태그. ctx: question(dict) · step(페르소나 단계) · deck_lines(list) · deck_text(str, 자료 원문 전부) ·
    deck_raw({장: 원문}) · cumulative(str, 이 질문의 앞선 답+이번 답) · others(list[str], 다른 질문 글) ·
    corrected(bool, 함정을 이미 바로잡았나).
    """
    j = turn.get("judge") or {}
    texts = coach_texts(turn)
    deck = ctx.get("deck_text") or "\n".join(ctx.get("deck_lines") or [])
    step = ctx.get("step", "")
    out = tone_tags(texts)
    react = str(j.get("react") or "")
    q = ctx.get("question") or {}
    mine = " ".join([q.get("question", ""), q.get("answer_gist", ""), q.get("evidence_quote", ""),
                     ctx.get("cumulative", ""), deck])
    if j:
        coach = bool(j.get("coach_stage"))
        ok = passed(j)
        if step in FAIL_STEPS and ok:
            out.append(_tag("consistency.loose_pass", f"{step} 가 통과 {j.get('verdict')}/{j.get('score')}", turn.get("input", "")))
        if step in PASS_STEPS and not ok and not coach and guard_of(react):
            out.append(_tag("consistency.good_demoted_guard", f"{guard_of(react)} {j.get('verdict')}/{j.get('score')}", react))
        if not coach and (not ok or step in FAIL_STEPS) and PRAISE_RE.search(react):
            out.append(_tag("consistency.praise_on_fail", f"{step} {j.get('verdict')}/{j.get('score')}", react))
        pu = praise_unsaid(react, ctx.get("cumulative", ""))
        if pu:
            out.append(pu)
        out += missing_tags(j, deck, ctx.get("cumulative", ""))
        if ok and j.get("mastered") and [x for x in j.get("missing_points") or [] if x]:
            out.append(_tag("consistency.pass_with_missing", " / ".join(j["missing_points"])[:120]))
        if ok and not j.get("mastered") and j.get("followup"):
            out.append(_tag("consistency.passed_but_followup", f"{j.get('verdict')}/{j.get('score')} r{j.get('round_no')}", j["followup"]))
        out += followup_tags(j)
        out += choice_tags(list(j.get("choices") or []), ctx.get("deck_text") or deck, str(j.get("followup") or ""))
        if react in FALLBACK_REACTS:
            out.append(_tag("ux.react_fallback", react))
        if len(react) > REACT_MAX:
            out.append(_tag("ux.react_long", f"{len(react)}자", react))
        ordinal = [int(m.group(1)) for b in turn.get("bubbles") or [] for m in [ORDINAL_RE.search(b.get("meta") or "")] if m]
        if ordinal and not coach and j.get("round_no") and ordinal[0] != int(j["round_no"]) + 1:
            out.append(_tag("ux.counter_mismatch", f"화면 {ordinal[0]}번째 · 서버 round_no {j['round_no']}+1"))
        leak = cross_leak([react, str(j.get("followup") or "")], mine, ctx.get("others") or [])
        if leak:
            out.append(leak)
    tl = trap_leak(texts, q.get("trap_premise"), bool(ctx.get("corrected")))
    if tl:
        out.append(tl)
    for b in turn.get("bubbles") or []:
        if b.get("kind") in ("gist", "done") and b.get("text"):
            out += gist_tags(_gist_body(b["text"]), ctx.get("deck_lines") or [])
        if b.get("kind") == "hint":
            out += hint_tags(b.get("text", ""), ctx.get("deck_raw") or {}, q.get("answer_gist", ""))
    return out


def _gist_body(text: str) -> str:
    """완성 문장 말풍선의 본문 — 머리말(「이렇게 말하면 완성이에요 —」 따위)을 뗀다."""
    return re.sub(r"^[^—]{0,40}—\s*", "", (text or "").strip()).strip()


def hint_tags(text: str, deck_raw: dict[int, str], gist: str) -> list[dict]:
    """힌트 한 칸 — 인용이 낱말 조각으로 시작하는가(§11·부스 09-29) · 곧 정답인가."""
    out = []
    m = re.search(r"«([^»]+)»", text or "")
    quote = m.group(1).strip() if m else ""
    if quote and fragment_start(quote, deck_raw):
        out.append(_tag("ground.hint_fragment", "폭으로 꺾인 줄의 낱말 조각으로 시작", quote))
    if quote and gist and len(T.tokens(gist)) >= 3 and T.coverage(gist, quote) >= 0.8:
        out.append(_tag("ground.hint_leaks_answer", "힌트 인용이 곧 골자", quote))
    return out


def wrap_points(raw: str) -> list[str]:
    """원문에서 **낱말 한가운데서 꺾인 줄**의 다음 줄 머리 — 이렇게 시작하는 인용은 조각이다 (사진 OCR·PDF 폭 꺾임)."""
    lines = [ln.rstrip() for ln in (raw or "").split("\n") if ln.strip()]
    width = max((len(ln) for ln in lines), default=0)
    wrap_at = max(30, int(width * 0.7))
    out = []
    for prev, nxt in zip(lines, lines[1:]):
        if (len(prev) >= wrap_at and not re.search(r"[.?!:*」』”\"')\]]$|(?:다|요|죠|음|함|됨|임)$", prev)
                and "가" <= prev[-1] <= "힣" and "가" <= nxt.strip()[0] <= "힣"):
            out.append(nxt.strip())
    return out


def fragment_start(quote: str, deck_raw: dict[int, str]) -> bool:
    q = T.squash(quote)
    for raw in deck_raw.values():
        for head in wrap_points(raw):
            h = T.squash(head)[:8]
            if h and q.startswith(h):
                return True
    return False


# ---------------------------------------------------------------------------
# 모으기
# ---------------------------------------------------------------------------

def tag_counts(turn_rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in turn_rows:
        for t in row.get("tags") or []:
            out[t["tag"]] = out.get(t["tag"], 0) + 1
    return out


def examples(turn_rows: list[dict], tag: str, k: int = 3) -> list[str]:
    ex = []
    for row in turn_rows:
        for t in row.get("tags") or []:
            if t["tag"] == tag:
                where = f"{row.get('deck', '')} Q{row.get('q', '')} {row.get('persona', '')}/{row.get('step', '')}"
                ex.append(f"{where}: {t.get('detail', '')} «{t.get('quote', '')}»")
                break
        if len(ex) >= k:
            break
    return ex


def percentile(values: list[float], p: float) -> float | None:
    vs = sorted(v for v in values if v is not None)
    if not vs:
        return None
    k = min(len(vs) - 1, max(0, int(round(p * (len(vs) - 1)))))
    return vs[k]
