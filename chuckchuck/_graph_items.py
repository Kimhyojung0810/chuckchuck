"""
개념 그래프(F-07) **후처리** 유틸 — LLM 이 낸 그래프를 자료 구조로 메우고 겹친 노드를 합친다. LLM 을 부르지 않는다.

`_match.py`·`_claim_rules.py` 와 같은 자리다 (DEV_POLICY §4-1 유틸). F-07 만 쓰지만 f07 파일에서 떼어 둔 까닭:
f07 은 프롬프트·위계 조립이고, 이건 **자료 줄을 읽는 규칙**이라 따로 시험·교체할 수 있어야 한다.

왜 있나 (2026-09-29 P5 벤치, held-out·처음 보는 덱):
- F-07 이 식·목록의 **항목**을 노드로 안 남겼다. 「A = B × C × D」 장이 있는데 B·D 노드가 없으면 F-26 이
  compose 를 못 적고, 그러면 F-08 이 긴장·미해결 탐침을 코드로 못 찾는다 (심은 주장 재현율 67% → 52%).
  프롬프트에 「항목은 각각 노드」 를 더하는 안은 위계를 흔든 전례가 있어서(19b66ea 노드 links 칸) 코드로 메운다.
- 한 실행은 같은 이름 노드가 98번 되풀이된 113노드 그래프를 냈다 (반복 루프). 이름이 같은 노드는 한 개념이다.

규칙은 전부 **구조**다 — 식 기호·목록 제목(개수 말·문제 명사)·글머리표·줄 길이·조사. 특정 발표의 낱말은 없다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import _claim_rules as R
from ._match import norm_tokens

#: 덱 하나에 후처리로 더할 노드 상한. 넘치면 식 → 문제 목록 → 그 밖 목록 순으로 앞 장부터 채운다.
#: 많이 더하면 F-26 프롬프트(개념 목록)가 길어지고 F-11 누락 판정 대상이 는다 — 탐침 재료만큼만.
MAX_ADDED = int(os.environ.get("CHUCKCHUCK_GRAPH_MAX_ADDED", "8"))
#: LLM 응답에서 받을 노드 상한. 반복 루프(같은 이름 98번)는 합치기로 먼저 접히고, 이건 마지막 방어선이다.
MAX_NODES = int(os.environ.get("CHUCKCHUCK_GRAPH_MAX_NODES", "80"))
#: 항목 글 상한 — 이보다 길면 개념 이름이 아니라 설명 문장이다.
ITEM_MAX_CHARS = 20
ITEM_MAX_TOKENS = 4
#: 개수 말 없는 목록(「…원인」)이 받는 항목 수. 이보다 많으면 레이아웃이 섞인 것이라 믿지 않는다.
LIST_MAX_ITEMS = 6
#: 식에서 연산 기호로 끝난 줄 뒤, 다음 항을 찾아 내려가 볼 줄 수. Upstage 가 식 조각 사이에 캡션 줄을 끼운다.
FORMULA_LOOKAHEAD = 3

_TAG_RE = re.compile(r"<figcaption>.*?</figcaption>|!\[[^\]]*\]\([^)]*\)|<[^>]+>", re.S | re.I)
_PAGE_NO_RE = re.compile(r"^[\d\s/|.·\-–—]+$")
_BULLET_ONLY_RE = re.compile(r"^[\s•▪■◦·*\-–—]+$")
_OPS = "=×✕+·*÷"
_OP_END_RE = re.compile(rf"[{re.escape(_OPS)}]\s*$")
_OP_START_RE = re.compile(rf"^\s*[{re.escape(_OPS)}]")
_FORMULA_SPLIT_RE = re.compile(r"\s*[×✕*+·÷]\s*|\s+x\s+")
_QUOTE_RE = re.compile(r"[\"'“”‘’「」『』()\[\]]")
_DIGIT_RE = re.compile(r"\d")
_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{2,}")
#: 문장 끝 — `_claim_rules.is_sentence` 보다 좁다. 그쪽은 「…음·함·됨·임」 명사형 끝도 문장으로 보는데,
#: 항목 이름은 그 글자로 끝나기 쉽다 (「소음」「처리함」 같은 표 칸이 문장으로 잘려 목록이 끊겼다).
_TRAILING_WH_RE = re.compile(r"\s+(?:얼마나|어떻게|왜|무엇|언제|어디서?|누가|몇)$")
_OBJ_TOK_RE = re.compile(r"[가-힣](?:을|를)$")
_NOMINAL_END_RE = re.compile(r"(?:음|함|됨|임)$")
_SENTENCE_END_RE = re.compile(r"(?:[.!。]|다|요|죠)\s*[.!]?\s*$")


# ---------------------------------------------------------------------------
# 자료 줄 — f26 slide_lines 의 최소 사본 (식 조각 잇기만 다르다)
# ---------------------------------------------------------------------------

def _clean(line: str) -> str:
    return " ".join(_TAG_RE.sub(" ", line or "").split())


def _plain(line: str) -> str:
    """물음·문장 판정용 — 따옴표를 걷는다 (「“…시간은?”」 은 따옴표 때문에 물음 어미가 가려졌다)."""
    return _QUOTE_RE.sub("", line or "").strip()


def _sentence(text: str) -> bool:
    return bool(_SENTENCE_END_RE.search(text or ""))


def _term_like(line: str) -> bool:
    """식의 한 항이 될 만한 줄 — 짧고, 물음·문장이 아니다."""
    p = _plain(line)
    return bool(p) and len(p) <= ITEM_MAX_CHARS + 6 and not R.is_question(p) and not _sentence(p)


def _item_line(line: str) -> bool:
    """목록 항목처럼 생긴 줄 — 표 행, 번호·글머리표 줄, 또는 문장·물음이 아닌 짧은 줄."""
    line = (line or "").strip()
    if not line:
        return False
    if R.table_cells(line) or R.item_text(line) != line:
        return True
    p = _plain(line)
    return len(p) <= 30 and not _sentence(p) and not R.is_question(p)


def deck_lines(raw_text: str) -> list[str]:
    """
    장 원문을 줄로. 식 조각(「A =」「B ×」「C」)은 한 줄로 잇는다.

    f26 slide_lines 와 다른 점 하나: 연산 기호로 끝난 줄 뒤에 **물음·문장 줄**이 오면 잇지 않고, 몇 줄 아래의
    항 같은 줄을 찾아 잇는다. 09-29 새 덱: 「독서 경험 = 대출 권수 × 머문 시간 ×」 다음 줄이 도식 캡션
    「얼마나 머물렀는가」 여서, 이어 붙인 식이 물음 줄이 되고 마지막 항이 사라졌다.
    """
    lines = [_clean(x) for x in (raw_text or "").split("\n")]
    # 표 구분 행(「| --- |」)은 쪽 번호 꼴과 같아 보이지만 남긴다 — 표 머리 행을 가르는 표시다
    lines = [x for x in lines if x and (_TABLE_SEP_RE.match(x.replace(" ", ""))
                                        or not (_PAGE_NO_RE.match(x) or _BULLET_ONLY_RE.match(x)))]
    out: list[str] = []
    used: set[int] = set()
    for i, line in enumerate(lines):
        if i in used:
            continue
        # 「×」 로 시작하는(또는 「×」 만 있는) 줄은 앞 줄의 식에 붙이고, 그 뒤 항을 이어서 찾는다
        cur = f"{out.pop()} {line}" if out and _OP_START_RE.match(line) else line
        j = i
        while _OP_END_RE.search(cur):
            nxt = next((k for k in range(j + 1, min(len(lines), j + 1 + FORMULA_LOOKAHEAD))
                        if k not in used and _term_like(lines[k])), None)
            if nxt is None:
                break
            cur = f"{cur} {lines[nxt]}"
            used.add(nxt)
            j = nxt
        out.append(cur)
    return out


# ---------------------------------------------------------------------------
# 식·목록 → 항목 묶음
# ---------------------------------------------------------------------------

@dataclass
class ItemGroup:
    """한 장의 식 하나 또는 목록 하나. head 는 식의 좌변 / 목록 제목, items 는 항목 글."""
    slide_no: int
    kind: str                      # formula | list
    head: str
    line: str                      # 근거 줄 (식 줄 또는 목록 제목)
    items: list[str] = field(default_factory=list)
    context: str = ""              # 제목 + 제목 밑 소개 문장 — 부모를 못 찾을 때 이 글에 이름이 나온 노드를 본다


def clean_item(text: str) -> str:
    """항목 글 → 개념 이름 후보. 이름답지 않으면 "" (숫자·긴 글·물음·문장·식 기호·표 칸)."""
    t = _plain(R.item_text(text)).strip(" .,:;·-–—")
    # 끝에 붙은 의문사는 옆 도식 캡션(「얼마나 머물렀는가」)이 잘려 붙은 것이다 — 떼어 낸다
    t = _TRAILING_WH_RE.sub("", t).strip()
    if not t or len(t) > ITEM_MAX_CHARS or _DIGIT_RE.search(t):
        return ""
    if any(op in t for op in "=→:|") or R.is_question(t) or _sentence(t):
        return ""
    toks = norm_tokens(t)
    if not toks or len(toks) > ITEM_MAX_TOKENS or sum(len(x) for x in toks) < 2:
        return ""
    # 이름이 아니라 절이다: 목적격(을·를)으로 끝난 낱말 뒤에 말이 더 오거나, 셋 이상 낱말이 명사형 서술(…없음·…함)로
    # 끝난다 (「…항목은 없음」). 「은·는」 은 보지 않는다 — 「짧은」「않는」 같은 관형형과 같은 글자다.
    if any(_OBJ_TOK_RE.search(x) for x in toks[:-1]) or (len(toks) >= 3 and _NOMINAL_END_RE.search(toks[-1])):
        return ""
    return t


def _formula_group(slide_no: int, line: str) -> ItemGroup | None:
    sides = R.formula_sides(line)
    if not sides:
        return None
    lhs, rhs = sides
    raw_parts = [p for p in _FORMULA_SPLIT_RE.split(rhs) if p.strip(" .")]
    parts = [clean_item(p) for p in raw_parts]
    parts = [p for p in parts if p]
    head = clean_item(lhs)
    # 항이 둘 미만이면 식이 아니라 우연한 「=」 다 (「합계 = 100」)
    if not head or len(parts) < 2:
        return None
    return ItemGroup(slide_no, "formula", head, line, parts, context=lhs)


def _stated_count(head: str) -> int | None:
    """제목의 개수 말(「세 가지」「4단계」) → 수. 없으면 None."""
    m = re.search(r"(두|세|네|다섯|여섯|일곱|여덟|아홉|열|\d{1,2})\s*(?:가지|개|대|단계|요소|요인|조건|축|원칙)", head)
    if not m:
        return None
    words = {"두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}
    w = m.group(1)
    return words.get(w) if w in words else int(w)


def _is_column_names(head_row: str, rows: list[str]) -> bool:
    """
    표 머리 행이 열 이름인가 — 머리의 나머지 칸엔 숫자가 없는데 아래 행의 나머지 칸엔 숫자가 있다.
    파서는 표의 첫 행을 늘 머리로 적는다. 항목 표(「| 원인 | 설명 |」 행만 있는 것)는 첫 행도 항목이다.
    """
    head = R.table_cells(head_row)[1:]
    body = [c for r in rows for c in R.table_cells(r)[1:]]
    return not any(_DIGIT_RE.search(c) for c in head) and any(_DIGIT_RE.search(c) for c in body)


def _list_group(slide_no: int, lines: list[str], idx: int) -> ItemGroup | None:
    head = lines[idx]
    if not R.is_list_heading(_plain(head)):
        return None
    start = idx + 1
    # 제목 밑 소개 문장 하나(「흔한 이유는 이렇습니다.」)는 건너뛴다 — f26 list_items 와 같은 규칙
    if start < len(lines) and not _item_line(lines[start]):
        start += 1
    items: list[str] = []
    window = lines[start: start + LIST_MAX_ITEMS + 3]
    for k, line in enumerate(window):
        # 표는 첫 칸이 항목이다. 다만 머리 행(구분 행 「| --- |」 바로 위)은 열 이름이라 항목이 아니다 —
        # 09-29 IR 덱에서 머리 칸 「지표」 가 항목이 됐다.
        if _TABLE_SEP_RE.match(line.replace(" ", "")):
            continue
        if R.table_cells(line) and k + 1 < len(window) and _TABLE_SEP_RE.match(window[k + 1].replace(" ", "")) \
                and _is_column_names(line, window[k + 2:]):
            continue
        if not _item_line(line):
            break
        item = clean_item(line)
        if not item:
            break
        items.append(item)
    want = _stated_count(head)
    # 개수 말이 있으면 항목 수가 그와 같아야 믿는다 — 다르면 도식 설명 줄이 섞인 레이아웃이다
    if want is not None and len(items) != want:
        return None
    # 개수 말이 없는 목록(「…원인」 제목)은 셋 이상일 때만 믿는다 — 둘짜리는 강조 상자·메모와 구별이 안 된다
    if not (2 if want is not None else 3) <= len(items) <= LIST_MAX_ITEMS:
        return None
    return ItemGroup(slide_no, "list", _plain(head), head, items, context=" ".join(lines[idx:start]))


def item_groups(slides: list[tuple[int, str]]) -> list[ItemGroup]:
    """(장 번호, 원문) 목록 → 식·목록 묶음. 식이 먼저, 그다음 문제 목록, 그 밖 목록 — 각각 장 순서."""
    groups: list[ItemGroup] = []
    for no, raw in slides:
        lines = deck_lines(raw)
        for i, line in enumerate(lines):
            g = _formula_group(no, line) or _list_group(no, lines, i)
            if g is not None:
                groups.append(g)
    rank = {"formula": 0, "list": 1}
    return sorted(groups, key=lambda g: (rank[g.kind], not R.is_problem_head(g.head), g.slide_no))


# ---------------------------------------------------------------------------
# 이름 대조
# ---------------------------------------------------------------------------

def _stem(tok: str) -> str:
    return tok[:-1] if len(tok) > 2 and tok.endswith("의") else tok


def label_keys(label: str) -> tuple[tuple[str, ...], str]:
    """
    이름이 **같은** 개념인지 가르는 두 열쇠 — (조사 「의」 뗀 토큰 정렬, 띄어쓰기 없앤 글).

    양·방향 수식어(저하·부족)는 떼지 않는다. 「집중력」 밑의 「집중력 저하」 는 프롬프트가 일부러 자식으로
    매다는 다른 개념이다 (규칙 D). 합치는 건 「고객의 만족」 = 「고객 만족」, 「온라인예약」 = 「온라인 예약」 뿐.
    """
    toks = [_stem(t) for t in norm_tokens(label)]
    return tuple(sorted(toks)), "".join(toks)


def same_label(a: str, b: str) -> bool:
    ka, kb = label_keys(a), label_keys(b)
    return bool(ka[1]) and (ka[0] == kb[0] or ka[1] == kb[1])


def _covered(inner: list[str], outer: list[str]) -> int:
    return sum(1 for t in inner if any(R.tok_match(o, t) or R.tok_match(t, o) for o in outer))


def present_index(item: str, labels: list[str]) -> int | None:
    """
    항목이 이미 노드로 있으면 그 이름의 자리, 없으면 None. 새 노드를 만들지 가르는 잣대라 **넉넉하게** 있다고 본다
    (겹친 노드가 빠진 노드보다 해롭다 — 같은 개념이 둘이면 F-26 이 둘 중 하나로만 id 를 적는다).

    - 이름이 같다 (`same_label`), 또는 수식어만 다르다 (`_claim_rules.same_concept` — 「대출 권수 감소」 ⊇ 「대출 권수」)
    - 노드 이름이 항목 안에 이어서 나오고 항목 낱말의 절반 이상을 덮는다 (「낡은 온라인 예약 시스템」 ∋ 「온라인 예약 시스템」).
      절반 미만이면 다른 개념이다 (「도서관 방문 감소」 ∌ 「도서관」).
    - 항목이 노드 이름 안에 이어서 나오고 이름이 낱말 하나만 더 가졌다 (「객단가」 ⊂ 「평균 객단가」).
    """
    itoks = R.content_tokens(item)
    for i, lab in enumerate(labels):
        if same_label(item, lab) or R.same_concept(item, lab):
            return i
    for i, lab in enumerate(labels):
        ltoks = R.content_tokens(lab)
        if not ltoks or not itoks:
            continue
        if _seq_in(norm_tokens(item), norm_tokens(lab)) and _covered(ltoks, itoks) * 2 >= len(itoks):
            return i
        if _seq_in(norm_tokens(lab), norm_tokens(item)) and len(ltoks) - _covered(itoks, ltoks) <= 1:
            return i
    return None


def item_present(item: str, labels: list[str]) -> bool:
    return present_index(item, labels) is not None


def _seq_in(outer: list[str], inner: list[str]) -> bool:
    n = len(inner)
    return n > 0 and any(all(R.tok_match(outer[i + j], inner[j]) for j in range(n))
                         for i in range(len(outer) - n + 1))


def match_score(phrase: str, label: str) -> float:
    """
    구절이 이름을 가리키는 정도 (0~1) — 두 쪽 변별 낱말이 서로 덮는 비율의 작은 값.
    한쪽만 보면 「도서관」 이 「도서관 방문 감소」 를, 긴 이름이 짧은 구절을 삼킨다.
    """
    p, lab = R.content_tokens(phrase), R.content_tokens(label)
    if not p or not lab:
        return 0.0
    return min(_covered(p, lab) / len(p), _covered(lab, p) / len(lab))


# ---------------------------------------------------------------------------
# 반복 루프·겹친 이름 — LLM raw 노드 단계에서 합친다
# ---------------------------------------------------------------------------

def dedupe_raw_nodes(raw_nodes: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """
    이름이 같은 raw 노드를 앞쪽(위에서 아래로 적으니 위계가 높은 쪽)에 합친다 → (남은 노드, 버린 id → 남은 id).

    slide_nos 는 합치고, 앞 노드의 parent 가 비었으면 뒤 노드의 parent 를 받는다. 버린 노드를 가리키던
    parent·edges·thesis 는 호출자가 대응표로 옮긴다. 합친 뒤에도 MAX_NODES 를 넘으면 뒤쪽을 자른다.
    """
    kept: list[dict] = []
    alias: dict[str, str] = {}
    by_key: dict = {}
    for raw in raw_nodes:
        label = str(raw.get("label", "") or "")
        keys = label_keys(label)
        have = (by_key.get(("t", keys[0])) or by_key.get(("s", keys[1]))) if keys[1] else None
        if have is None:
            node = dict(raw)
            kept.append(node)
            if keys[1]:
                by_key[("t", keys[0])] = by_key[("s", keys[1])] = node
            continue
        have["slide_nos"] = list(have.get("slide_nos") or []) + [
            n for n in (raw.get("slide_nos") or []) if n not in (have.get("slide_nos") or [])]
        if have.get("parent") in (None, "", "null") and raw.get("parent") not in (None, "", "null"):
            if str(raw.get("parent")) != str(have.get("id")):
                have["parent"] = raw.get("parent")
        rid, hid = str(raw.get("id", "") or ""), str(have.get("id", "") or "")
        # 같은 id 를 다른 이름에 되쓴 경우(겹친 id)는 대응표에 넣지 않는다 — 그 id 는 원래 주인의 것이다
        if rid and hid and rid != hid and rid not in alias and sum(
                1 for r in raw_nodes if str(r.get("id", "") or "") == rid) == 1:
            alias[rid] = hid
    return kept[:MAX_NODES], alias


# ---------------------------------------------------------------------------
# id — 한글 이름을 로마자 slug 로 (새로 더한 노드)
# ---------------------------------------------------------------------------

_INITIAL = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_MEDIAL = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi",
           "yu", "eu", "ui", "i"]
_FINAL = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m", "p", "p", "t", "t",
          "ng", "t", "t", "k", "t", "p", "t"]


def romanize(text: str) -> str:
    """한글 음절을 로마자로 (개정 로마자 표기의 글자 단위 대응, 음운 변화 없음) — 안정된 ascii id 를 만든다."""
    out = []
    for ch in text or "":
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(_INITIAL[code // 588] + _MEDIAL[(code % 588) // 28] + _FINAL[code % 28])
        else:
            out.append(ch.lower() if ch.isascii() and ch.isalnum() else " ")
    return "-".join("".join(out).split())


def slug_id(label: str, used: set[str]) -> str:
    """이름 → 쓰이지 않은 id. 같은 이름은 늘 같은 id (덱이 같으면 캐시·조인이 흔들리지 않는다)."""
    base = re.sub(r"[^a-z0-9]+", "-", romanize(label)).strip("-")[:40].strip("-") or "item"
    cand, k = base, 2
    while cand in used:
        cand, k = f"{base}-{k}", k + 1
    return cand
