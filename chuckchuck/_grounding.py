"""
질문 코칭(F-08)이 쓴 **골자·함정 전제·질문** 이 자료로 받쳐지는가를 보는 결정적 검사입니다.
`_evidence.py`·`_probes.py` 와 같은 자리다 — 기능 모듈(fXX_*)이 아니라 유틸이라 F-08 이 import 해도
정책 위반이 아닙니다 (DEV_POLICY §4-1). contracts 타입만 받고 LLM 을 부르지 않습니다.

왜 따로 두나 (2026-09-29 기준선, docs/review/2026-09-29_QA_근거검증/baseline.md §5):
- 골자 검사가 **숫자만** 봤다 (`ungrounded_numbers`). 숫자가 자료 어딘가에 있으면 대상이 틀려도 통과해서,
  표의 「상위 25% vs 하위 25%」 행 값이 「기관 71% · 개인 18%」 로 골자가 됐고 판정은 그걸 정답으로 채점했다.
- 자료는 곱(A = B × C × D)인데 골자가 「C 와 D 가 더 중요」 라는 서열을 지어냈다 — 숫자가 없어 아무 검사에도 안 걸렸다.
- 표의 한 행 값(「수면 후반 각성」)을 다른 행 머리(「카페인」)에 붙였다.
- 함정 표시(trap)는 붙는데 질문에 거짓 전제가 없거나, 전제가 자료에 **사실로** 있었다(58%).

**규칙은 구조로만 말한다** — 숫자·비교 표지·표의 행·슬라이드 줄·그래프 라벨과 깊이. 특정 발표의 낱말을 규칙에
넣지 않는다 (09-29 사용자 지시: 부스에 들어오는 아무 PPT 에나 통해야 한다). 위 예시는 전부 주석·테스트에만 있다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ._evidence import clean_slide_text, strip_chart_descriptions

# ---------------------------------------------------------------------------
# 자료 줄 — 글 상자 한 줄, 표는 행 하나가 한 줄
# ---------------------------------------------------------------------------

#: 쪽 번호("01 / 08")처럼 숫자·구분자만 있는 줄.
_PAGE_NO_RE = re.compile(r"^[\d\s/|.·-]+$")
#: 표 구분 행 「| --- | --- |」.
_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{3,}")
#: 슬라이드 머리로 볼 앞 줄 수 (제목·부제). 숫자 옆에 주어가 없을 때 장 제목이 주어인 경우가 많다.
HEADING_ROWS = 2


@dataclass(frozen=True)
class Row:
    """자료 한 줄. 표 행이면 table=True, header 는 그 표의 첫 행(열 이름), cells 는 칸."""
    slide_no: int
    index: int
    text: str
    table: bool = False
    header: str = ""
    cells: tuple[str, ...] = ()


def slide_rows(slide_no: int, raw_text: str) -> list[Row]:
    """
    슬라이드 원문을 줄로. `_evidence.slide_units` 는 인용 후보라 12자 미만 칸(표의 「| 과잉 매매 | -1.6 |」)을 버린다 —
    숫자가 어느 행에 붙었는지 보려면 표 행을 통째로 한 줄로 남겨야 해서 따로 둔다.
    """
    rows: list[Row] = []
    header = ""
    in_table = False
    for line in strip_chart_descriptions(raw_text).split("\n"):
        s = line.strip()
        if not s:
            in_table = False
            continue
        table = s.startswith("|")
        if table and _TABLE_SEP_RE.match(s):
            continue
        text = clean_slide_text(s)
        if not text or (not table and _PAGE_NO_RE.match(text)):
            continue     # 표 행(「| 1 | 1100 | 1050 |」)은 숫자뿐이어도 쪽 번호가 아니다
        cells: tuple[str, ...] = ()
        if table:
            cells = tuple(c.strip() for c in text.strip().strip("|").split("|"))
            if not in_table:
                header, in_table = text, True
        else:
            in_table = False
        rows.append(Row(slide_no=slide_no, index=len(rows), text=text, table=table,
                        header=header if table else "", cells=cells))
    return rows


# ---------------------------------------------------------------------------
# 낱말 · 숫자 · 라벨 언급
# ---------------------------------------------------------------------------

_SQUASH_RE = re.compile(r"[\s\"'“”‘’「」『』()\[\]«»·,.:;!?~\-–—]+")
_WORD_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{2,}|\d+(?:\.\d+)?")
#: 숫자 한 개. 천 단위 쉼표는 붙인다 ("1,000" → 1000).
_NUM_RE = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\d.])\d+(?:\.\d+)?")
#: 절 경계 — 문장 끝, 연결 어미 뒤 쉼표(~며, ~고, ~면, ~서, ~데, ~만, ~지), 세미콜론, 접속 부사.
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+|\s+·\s+|(?<=[며고서면데만지로까])\s*,\s*|;\s*|\s+(?:그리고|하지만|반면|또한)\s+")
#: 라벨 바로 뒤에 붙어 그 라벨을 「주어·소유주」 로 만드는 조사.
_SUBJECT_PARTICLES = ("은", "는", "이", "가", "의")
#: 라벨 바로 뒤에 붙으면 그 라벨이 명사가 아니라 서술어 줄기라는 뜻인 글자 (하다·되다 활용).
_VERB_TAILS = ("하", "한", "했", "해", "할", "합", "되", "된", "됐", "돼", "될", "됩")


def squash(text: str) -> str:
    return _SQUASH_RE.sub("", (text or "").lower())


def head_word(label: str) -> str:
    """여러 낱말 라벨의 마지막 낱말 (한국어 명사구의 머리). 자료 줄은 머리만 쓰는 일이 많다 — 표는 「시장지수」, 본문은 「지수 8.7%」.
    한 낱말 라벨이면 ""."""
    parts = (label or "").split()
    return parts[-1] if len(parts) >= 2 and len(squash(parts[-1])) >= 2 else ""


def label_words(label: str) -> list[str]:
    """라벨의 낱말(두 글자 이상). 표 머리는 라벨의 한 낱말만 쓰는 일이 많다 (「보유(월)」 ↔ 「보유 기간」)."""
    parts = (label or "").split()
    return [p for p in parts if len(squash(p)) >= 2] if len(parts) >= 2 else []


def mentions(text: str, label: str) -> bool:
    """라벨이 글에 나오는가 — 띄어쓰기·따옴표·가운뎃점 차이는 무시한다 (「시장지수」 ∋ 「시장 지수」)."""
    lab = squash(label)
    return len(lab) >= 2 and lab in squash(text)


def words(text: str) -> list[str]:
    """대조용 낱말 (한글·영문 두 글자 이상, 숫자)."""
    return [w.lower() for w in _WORD_RE.findall(text or "")]


#: 낱말 끝의 조사 — 떼고 줄기로 견준다 (「격차가」 = 「격차의」). 한 번만 뗀다.
_JOSA_END_RE = re.compile(r"(?:에서는|에서|으로|에게|부터|까지|처럼|보다|은|는|이|가|을|를|의|에|와|과|도|만|로)$")


def stem(word: str) -> str:
    """조사를 뗀 줄기. 떼고 두 글자 미만이면 원래 낱말."""
    s = _JOSA_END_RE.sub("", word)
    return s if len(s) >= 2 else word


def _norm_num(raw: str) -> str:
    return raw.replace(",", "")


def significant(num: str) -> bool:
    """사실 주장으로 볼 숫자인가. 한 자리 정수(「세 가지」·「2개」)는 셈이라 빼고, 소수·두 자리 이상만 본다."""
    return "." in num or (num.isdigit() and int(num) >= 10)


def numbers(text: str) -> list[str]:
    return [_norm_num(m.group(0)) for m in _NUM_RE.finditer(text or "")]


def clauses(text: str) -> list[str]:
    return [c.strip() for c in _CLAUSE_SPLIT_RE.split(text or "") if c and c.strip()]


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    label: str
    subject: bool


def _label_pattern(label: str) -> re.Pattern | None:
    lab = squash(label)
    if len(lab) < 2:
        return None
    return re.compile(r"[\s\"'“”‘’「」()·]*".join(re.escape(ch) for ch in lab), re.I)


def label_spans(text: str, labels: list[str]) -> list[_Span]:
    """글 속 라벨 언급 위치. 겹치면 긴 라벨이 이긴다. subject 는 바로 뒤에 주어·소유 조사가 붙었는가."""
    found: list[_Span] = []
    for label in labels:
        pat = _label_pattern(label)
        if pat is None:
            continue
        for m in pat.finditer(text or ""):
            nxt = (text or "")[m.end():m.end() + 1]
            if nxt in _VERB_TAILS:
                continue     # 「기록하므로」 의 「기록」 은 개념이 아니라 서술어다 (09-29 재실행: 라벨 「기록」 이 동사에 걸렸다)
            found.append(_Span(m.start(), m.end(), label, nxt in _SUBJECT_PARTICLES))
    found.sort(key=lambda s: (s.start, -(s.end - s.start)))
    out: list[_Span] = []
    for s in found:
        if out and s.start < out[-1].end:
            continue
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# 자료 색인
# ---------------------------------------------------------------------------

@dataclass
class DeckIndex:
    """자료 줄 + 그래프 라벨. `label_slides` 는 라벨 → 그래프가 준 근거 장, `topic` 은 깊이 1(발표 주제) 라벨."""
    rows: dict[int, list[Row]] = field(default_factory=dict)
    label_slides: dict[str, set[int]] = field(default_factory=dict)
    topic: set[str] = field(default_factory=set)
    vocab: set[str] = field(default_factory=set)
    text: str = ""

    @property
    def labels(self) -> list[str]:
        return list(self.label_slides)

    @property
    def detail_labels(self) -> list[str]:
        """주제 라벨을 뺀 라벨. 주제는 덱 전체에 걸쳐 있어 「이 숫자 옆에 있나」 를 물을 대상이 아니다."""
        return [lab for lab in self.label_slides if lab not in self.topic]

    def all_rows(self) -> list[Row]:
        return [r for no in sorted(self.rows) for r in self.rows[no]]

    def window(self, row: Row) -> list[str]:
        """이 줄의 문맥 — 표 행은 **행 자체와 열 이름**(행은 한 기록이라 옆 행을 섞지 않는다), 글 줄은 앞뒤 한 줄.
        둘 다 장 머리(제목·부제)를 더한다."""
        rows = self.rows.get(row.slide_no, [])
        if row.table:
            texts = [row.text, row.header]
        else:
            texts = [rows[i].text for i in range(max(0, row.index - 1), min(len(rows), row.index + 2))]
        return texts + [r.text for r in rows[:HEADING_ROWS]]

    def rows_with_number(self, num: str) -> list[Row]:
        return [r for r in self.all_rows() if num in numbers(r.text)]

    def near(self, label: str, row: Row, num: str = "", allowed: set[str] | frozenset = frozenset()) -> bool:
        """
        라벨이 이 줄의 숫자 `num` 의 주어일 수 있는가.

        1. 숫자 **앞**(글 줄은 줄 머리부터 숫자까지, 표 행은 행 머리 칸 + 그 숫자 칸의 열 이름)에 라벨이 있으면 참.
        2. 거기에 **다른** 라벨이 있으면 거짓 — 그 숫자는 그 대상의 값이다 (「지수 8.7% vs 기관 7.9%」 의 8.7 은 기관 값이 아니다).
        3. 숫자 앞에 아무 라벨도 없으면 장 단위로 본다 — 같은 장에 라벨(또는 머리 낱말)이 있거나, 그래프가 그 개념의 근거 장으로
           준 장이면 참. 차트 장은 숫자(표 행)와 대상(범례·캡션·제목)이 여러 줄 떨어져 있다 (09-29 재실행: 줄 문맥으로 좁혔을 때
           맞는 골자 넷이 걸렸다).
        """
        before = self.before_number(row, num)
        if before is not None:
            if mentions(before, label) or any(mentions(before, w) for w in label_words(label)):
                return True
            # 다른 라벨이 숫자 앞에 있으면 그 대상의 값이다. 같은 절이 부른 라벨(allowed — 주어 등)은 경쟁자가 아니다:
            # 「상위 25%는 … 보유 기간 19개월」 의 19 는 표 「보유(월) | 19」 의 열 이름 「상위 25%」 아래에 있다.
            if any(mentions(before, other) or mentions(before, head_word(other))
                   for other in self.label_slides
                   if other != label and other not in allowed and not mentions(label, other)):
                return False
        rows = self.rows.get(row.slide_no, [])
        if any(mentions(r.text, label) or mentions(r.text, head_word(label)) for r in rows):
            return True
        return row.slide_no in self.label_slides.get(label, set())

    def before_number(self, row: Row, num: str) -> str | None:
        """숫자 앞의 글 — 글 줄은 줄 머리부터 그 숫자까지, 표 행은 행 머리 칸 + 그 숫자가 든 칸의 열 이름. 못 찾으면 None."""
        if not num:
            return None
        if row.table and row.cells:
            head = [c.strip() for c in row.header.strip().strip("|").split("|")] if row.header else []
            for k, cell in enumerate(row.cells):
                if num in numbers(cell):
                    col = head[k] if k < len(head) and row.text != row.header else ""
                    return f"{row.cells[0] if k else ''} {col}".strip()
            return None
        for m in _NUM_RE.finditer(row.text):
            if _norm_num(m.group(0)) == num:
                return row.text[:m.start()]
        return None

    def known(self, word: str) -> bool:
        """낱말이 자료(·발화)에 있는가. 조사가 붙은 꼴(「구조적」 ∋ 「구조」)도 같은 낱말로 본다."""
        w = word.lower()
        if w in self.vocab:
            return True
        return any(w[:k] in self.vocab for k in range(2, len(w)))


def build_index(slides: dict, nodes: list, transcript_text: str = "") -> DeckIndex | None:
    """slide_no → Slide, ConceptNode 목록 → 색인. 자료가 없으면 None (판단하지 않는다 — 예전 동작)."""
    if not slides:
        return None
    rows = {no: slide_rows(no, getattr(s, "raw_text", "") or "") for no, s in slides.items()}
    label_slides: dict[str, set[int]] = {}
    topic: set[str] = set()
    for n in nodes:
        label = (getattr(n, "label", "") or "").strip()
        if len(squash(label)) < 2:
            continue
        label_slides.setdefault(label, set()).update(getattr(n, "slide_nos", []) or [])
        if (getattr(n, "depth", 0) or 0) <= 1 and getattr(n, "parent_id", None) is None:
            topic.add(label)
    text = " ".join(r.text for no in sorted(rows) for r in rows[no])
    vocab = set(words(text)) | set(words(transcript_text))
    return DeckIndex(rows=rows, label_slides=label_slides, topic=topic, vocab=vocab, text=text)


# ---------------------------------------------------------------------------
# (a) 숫자의 주어 — 숫자가 자료에 있어도 **같은 대상**에 붙어 있어야 한다
# ---------------------------------------------------------------------------

def misplaced_numbers(text: str, idx: DeckIndex | None) -> list[str]:
    """
    글 속 숫자 가운데 자료에는 있지만 **다른 대상에 붙은** 것.

    숫자 앞에서 가장 가까운 라벨, 그리고 가장 가까운 「주어·소유」 라벨(조사 은·는·이·가·의가 붙은 것)을 그 숫자의
    주어로 본다. 자료에서 그 숫자가 나온 줄 어디에서든 주어가 전부 `DeckIndex.near` 면 받쳐진 것이다.
    09-29 실측: 「기관은 … 71%로 개인 평균(18%)보다」 — 71·18 은 「상위 25% vs 하위 25%」 표의 값이다.
    가장 가까운 라벨만 보면 그 행의 머리(매도 규칙)라 통과한다 — 주어(기관)까지 봐야 잡힌다.
    자료에 없는 숫자는 여기서 보지 않는다 (`_speech.ungrounded_numbers` 몫). 주어 라벨이 없는 숫자도 보지 않는다.
    """
    if idx is None:
        return []
    out: list[str] = []
    labels = idx.detail_labels
    for clause in clauses(text):
        spans = label_spans(clause, labels)
        for m in _NUM_RE.finditer(clause):
            num = _norm_num(m.group(0))
            if not significant(num) or any(s.start <= m.start() < s.end for s in spans):
                continue     # 라벨 안의 숫자(「상위 25%」)는 이름이다
            occ = idx.rows_with_number(num)
            # 주어는 숫자가 든 **나열 칸** 안에서만 찾는다 — 「A 9%, B 8%, C 6%」 에서 C 의 숫자에 A 를 주어로 붙이지 않게.
            seg = max(clause.rfind(", ", 0, m.start()), clause.rfind("，", 0, m.start()))
            before = [s for s in spans if seg < s.start and s.end <= m.start()]
            if not occ or not before:
                continue
            nearest = before[-1].label
            subjects = [s for s in before if s.subject and s.label != nearest]
            subject = subjects[-1].label if subjects else ""
            # 가장 가까운 라벨은 그 숫자 줄에서 엄격하게(숫자 앞), 주어 라벨은 장 단위로 본다 — 「A 는 … B(8.7%)」 에서 8.7 은
            # B 의 값이고 A 는 그 장의 이야기이기만 하면 된다. 기준선의 「기관은 … 매도 규칙 준수율이 71%」 는 71 의 장에
            # 기관이 아예 없어서 걸린다.
            named = frozenset(s.label for s in spans)
            if not any(idx.near(nearest, row, num, named) and (not subject or idx.near(subject, row))
                       for row in occ) and num not in out:
                out.append(num)
    return out


# ---------------------------------------------------------------------------
# (b) 비교·서열 — 「보다·가장·더·우선」 은 자료의 같은 비교 줄이 받쳐야 한다
# ---------------------------------------------------------------------------

_COMPARE_MARK_RE = re.compile(r"보다|가장|제일|최우선|우선순위|우선적|(?<![가-힣])더(?=\s)")


#: 자료 줄이 비교를 말하는 다른 꼴 — 「A vs B」·「대비」·「하회·상회」·「못 미친다」. 자료는 「보다」 없이 숫자로 견주는 일이 많다
#: (09-29 재실행: 「상위 25% 그룹도 지수를 2.6%p 하회」 가 받치는 골자 「…시장 지수보다 낮은」 이 걸렸다).
_COMPARE_ROW_RE = re.compile(r"(?<![A-Za-z])vs\.?(?![A-Za-z])|대비|하회|상회|못\s*미|못\s*넘|앞서|뒤처|아니라", re.I)


def has_comparison(text: str) -> bool:
    return bool(_COMPARE_MARK_RE.search(text or ""))


_SUPERLATIVE_RE = re.compile(r"가장|제일|최대|최소|최고|최저")


def _cell_value(cell: str) -> float | None:
    nums = numbers(cell)
    if len(nums) != 1:
        return None
    try:
        return float(nums[0]) * (-1 if re.search(r"[-−–]\s*" + re.escape(nums[0]), cell) else 1)
    except ValueError:
        return None


def _table_extreme(named: set[str], idx: DeckIndex) -> bool:
    """「가장 ○○」 을 표가 받치는가 — 절이 부르는 라벨이 한 표의 행 머리이고, 그 행이 어떤 수치 열에서 절댓값이 가장
    크거나 작다. 차트 표(「요인 | -1.6」)는 「가장 크다」 를 글로 안 쓰고 값으로만 말한다."""
    for block in _tables(idx):
        keyed = [r for r in block if r.cells and any(squash(r.cells[0]) == squash(lab) or mentions(r.cells[0], lab) for lab in named)]
        if not keyed:
            continue
        width = max(len(r.cells) for r in block)
        for col in range(1, width):
            vals = [(abs(v), r) for r in block if len(r.cells) > col and (v := _cell_value(r.cells[col])) is not None]
            if len(vals) < 2:
                continue
            hi = max(v for v, _ in vals)
            lo = min(v for v, _ in vals)
            if any(r in keyed and v in (hi, lo) for v, r in vals):
                return True
    return False


def _table_heads(idx: DeckIndex) -> list[str]:
    """표마다 행 머리(첫 칸) — 두 글자 이상 낱말이 있는 것만."""
    return sorted({r.cells[0] for block in _tables(idx) for r in block
                   if r.cells and len(squash(r.cells[0])) >= 2 and _value_words(r.cells[0])})


def unbacked_comparisons(text: str, idx: DeckIndex | None) -> list[str]:
    """
    비교·서열을 말하는 절 가운데 자료의 비교 줄이 받치지 않는 것.

    절이 부르는 라벨이 **전부** 한 자료 줄(과 그 문맥)에 비교 표지와 함께 있어야 받쳐진 것이다. 라벨을 하나도 안 부르는
    절은 무엇을 견주는지 코드가 알 수 없어 보지 않는다. 09-29 실측: 자료는 「질 = 시간 × 연속성 × 규칙성」(곱)인데
    골자가 「연속성과 규칙성이 회복 효과에 더 큰 영향」 — 자료의 비교 줄(「수면 시간보다 중요한 수면의 질」)에는
    규칙성이 없다.
    """
    if idx is None:
        return []
    out: list[str] = []
    rows = idx.all_rows()
    for clause in clauses(text):
        if not has_comparison(clause):
            continue
        # 표의 행 머리도 견주는 대상이다 — 그래프 노드가 아닌 표 항목(「요인 | 설명」 의 요인들)끼리 순위를 지어내는 골자가 있다
        # (09-30 대화 감사 §1: 자료에 순위가 없는 요인 표를 두고 「A·B 가 가장 큰 영향」).
        named = {s.label for s in label_spans(clause, idx.labels + _table_heads(idx))}
        if not named:
            continue
        backed = _SUPERLATIVE_RE.search(clause) is not None and _table_extreme(named, idx)
        for row in ([] if backed else rows):
            win = " ".join(idx.window(row)[:3] if not row.table else idx.window(row)[:2])
            if (has_comparison(win) or _COMPARE_ROW_RE.search(win)) and all(
                    mentions(win, lab) or mentions(win, head_word(lab)) for lab in named):
                backed = True
                break
        if not backed:
            out.append(clause)
    return out


# ---------------------------------------------------------------------------
# (c) 표의 행 — 한 행의 값을 다른 행 머리에 붙이지 않는다
# ---------------------------------------------------------------------------

def _value_words(cell: str) -> list[str]:
    return [w for w in words(cell) if not w[0].isdigit()]


def _word_in(word: str, bag: list[str]) -> bool:
    return any(b == word or (len(word) >= 2 and b.startswith(word)) for b in bag)


def _tables(idx: DeckIndex) -> list[list[Row]]:
    """장마다 이어진 표 행 묶음. 첫 행도 넣는다 — 문서 변환기는 데이터 첫 행을 표 머리 자리에 두기도 한다
    (09-29 수면 5장: 「| 카페인 | 오후·저녁 섭취 |」 가 머리 행이었다). 열 이름 행은 값이 라벨과 안 겹쳐 해가 없다."""
    out: list[list[Row]] = []
    for no in sorted(idx.rows):
        block: list[Row] = []
        for r in idx.rows[no]:
            if r.table:
                if block and block[-1].header != r.header:
                    out.append(block)
                    block = []
                block.append(r)
            elif block and not r.table:
                out.append(block)
                block = []
        if block:
            out.append(block)
    # 값 칸이 숫자인 표(차트 표)의 첫 행은 열 이름이다 — 데이터로 보지 않는다.
    out = [b[1:] if len(b) > 2 and all(any(numbers(c) for c in r.cells[1:]) for r in b[1:]) else b for b in out]
    return [b for b in out if len(b) >= 2]


#: 행 머리를 나란히 잇는 말만 있는 틈 — 「A와 B는 X」 의 「와 」.
_COORD_GAP_RE = re.compile(r"^\s*(?:와|과|및|이나|나|또는|,|·|/)?\s*$")


def _coordinated(clause: str, before: list[_Span]) -> list[_Span]:
    """값 앞 가장 가까운 머리와, 그 머리에 「와·과·및·,」 로만 이어진 머리들 — 한 서술어를 함께 받는 주어 묶음.
    09-30 대화 감사 §1: 표 「음주 | 수면 후반 각성」 을 「카페인과 음주는 수면 후반 각성을 유발」 로 옮겼다 — 가장 가까운 머리(음주)만
    보면 통과해서, 카페인에 없는 값이 붙은 것을 못 봤다."""
    group = [before[-1]]
    for sp in reversed(before[:-1]):
        if _COORD_GAP_RE.match(clause[sp.end:group[-1].start]):
            group.append(sp)
        else:
            break
    return group


def misattributed_cells(text: str, idx: DeckIndex | None) -> list[str]:
    """
    표 값을 다른 행에 붙인 절. 절에 어떤 행의 값(낱말 둘 이상짜리 칸)이 나오면, 그 값 **앞에서 가장 가까운 행 머리**가
    그 행의 머리(첫 칸)여야 한다. 머리를 여럿 나열한 뒤 한 행의 값을 서술어로 붙이면(「A·B·C 가 모두 X」) 가장 가까운 머리가
    X 의 행이 아닐 때 걸린다. 머리 바로 뒤 괄호로 값을 단 나열(「C(빛·소음)」)은 통과한다.
    09-29 실측: 표 「음주 | 수면 후반 각성」 을 「카페인은 … 수면 후반부에 각성」 으로, 「카페인·음주·스트레스·환경 등이 수면 후반 각성」 으로 옮겼다.
    """
    if idx is None:
        return []
    out: list[str] = []
    tables = _tables(idx)
    for clause in clauses(text):
        bag = words(clause)
        low = clause.lower()
        for block in tables:
            keys = [r.cells[0] for r in block if r.cells and len(squash(r.cells[0])) >= 2 and _value_words(r.cells[0])]
            spans = label_spans(clause, keys)
            bad = False
            for r in block:
                for cell in r.cells[1:]:
                    if any(squash(cell) == squash(lab) for lab in idx.labels):
                        continue     # 값 칸이 개념 이름이면 속성이 아니라 이름이다 (「N3 | 깊은 수면」)
                    vw = _value_words(cell)
                    if len(vw) < 2 or not all(_word_in(w, bag) for w in vw):
                        continue
                    at = min((low.find(w) for w in vw if low.find(w) >= 0), default=-1)
                    before = [sp for sp in spans if sp.end <= at]
                    if before and any(squash(sp.label) != squash(r.cells[0]) for sp in _coordinated(clause, before)):
                        bad = True
                    elif not before and not any(squash(sp.label) == squash(r.cells[0]) for sp in spans) and spans:
                        bad = True   # 값이 먼저 나오고 다른 행 머리만 뒤에 있다
            if bad:
                out.append(clause)
                break
    return out


def described_table(slide_no: int, raw_text: str) -> str:
    """이 장의 **설명 표**(값 칸이 낱말 둘 이상인 행이 있는 표)를 「머리: 값 · 머리: 값」 한 줄로. 없으면 "".
    숫자만 든 차트 표는 넣지 않는다 — 문서 변환기가 막대 길이를 반올림한 값이라 본문 숫자와 어긋난다."""
    rows = [r for r in slide_rows(slide_no, raw_text) if r.table and len(r.cells) >= 2]
    if not any(len(_value_words(c)) >= 2 for r in rows for c in r.cells[1:]):
        return ""
    return " · ".join(f"{r.cells[0]}: {' / '.join(c for c in r.cells[1:] if c)}" for r in rows if r.cells[0])


# ---------------------------------------------------------------------------
# (d) 방향 — 같은 대상을 말하면서 반대 말(가까울수록↔멀어질수록, 늘다↔줄다)을 쓰지 않는다
# ---------------------------------------------------------------------------

#: 방향이 반대인 말의 두 끝 — 어느 발표에나 쓰는 말이다. 한 글자 줄기는 뒤 글자까지 적어 낱말 조각(「작업」「적인」)을 피한다.
_W = r"(?<![가-힣])"
ANTONYM_PAIRS: tuple[tuple[str, str], ...] = (
    (_W + r"가까(?:울|운|워|웠|이)|" + _W + r"가깝", _W + r"멀(?:어|수록|리|고|다|면|었)"),
    (_W + r"늘(?:어|었|고|면|수록|린|리|려|릴|립|다|수)", _W + r"줄(?:어|었|고|면|수록|인|이|여|일|입|다)"),
    (_W + r"높(?:아|았|고|은|을|게|이|여|다|수록)", _W + r"낮(?:아|았|고|은|을|게|추|춰|다|수록)"),
    (r"좋아(?:지|져|진|집)", r"나빠(?:지|져|진|집)"),
    (r"증가", r"감소"), (r"상승", r"하락"), (r"개선", r"악화"), (r"향상", r"저하"), (r"확대", r"축소"), (r"강화", r"약화"),
    (_W + r"많(?:아|았|고|은|을|이|다|수록)", _W + r"적(?:어|었|고|은|을|게|다|수록)"),
    (_W + r"(?:크(?:게|고|다|면|수록)|큰(?![가-힣])|커(?:지|져|진|요))", _W + r"작(?:게|고|다|은|을|아|수록)"),
    (_W + r"(?:빠르|빨라|빠른)", _W + r"(?:느리|느려|느린)"),
    (_W + r"(?:길(?:어|고|게|다|수록)|긴(?![가-힣]))", _W + r"짧(?:아|고|게|은|다|수록)"),
)
_ANTONYM_RES = tuple((re.compile(a), re.compile(b)) for a, b in ANTONYM_PAIRS)
#: 부정이 든 절은 방향을 뒤집어 말한 것일 수 있다 (「줄지 않았다」) — 보지 않는다.
_CLAUSE_NEG_RE = re.compile(r"않|아니|못|없")
#: 방향 대조에 필요한 같은 대상 낱말 수 (반대 말 자신은 빼고).
DIRECTION_SHARED_MIN = 2


def _pole_free_words(text: str) -> set[str]:
    out = set(words(text))
    for a, b in _ANTONYM_RES:
        out = {w for w in out if not (a.match(w) or b.match(w))}
    return {stem(w) for w in out}


def direction_conflicts(text: str, idx: DeckIndex | None) -> list[str]:
    """
    같은 대상을 말하는 자료 줄과 **방향이 반대인** 절. 09-30 대화 감사 §1: 골자 「폰이 가까울수록 … 좋아지는 경향」 이
    자료 6장 「멀어질수록 좋아지는 경향」 과 반대였는데, 숫자·비교·표 검사는 이걸 못 봤고 판정은 이 골자로 정답을 wrong 0 으로 채점했다.
    절과 자료 줄이 반대 말 쌍의 서로 다른 끝을 쓰고(각자 한쪽만), 반대 말을 뺀 낱말이 둘 이상 겹칠 때만 — 부정이 든 절은 뺀다.
    """
    if idx is None:
        return []
    out: list[str] = []
    rows = [r for r in idx.all_rows() if not r.table]
    for clause in clauses(text):
        if _CLAUSE_NEG_RE.search(clause):
            continue
        cw = _pole_free_words(clause)
        hit = False
        for a, b in _ANTONYM_RES:
            for mine, theirs in ((a, b), (b, a)):
                if not mine.search(clause) or theirs.search(clause):
                    continue
                for r in rows:
                    if theirs.search(r.text) and not mine.search(r.text) and not _CLAUSE_NEG_RE.search(r.text) \
                            and len(cw & _pole_free_words(r.text)) >= DIRECTION_SHARED_MIN:
                        hit = True
                        break
                if hit:
                    break
            if hit:
                break
        if hit:
            out.append(clause)
    return out


def gist_problems(text: str, idx: DeckIndex | None) -> list[str]:
    """골자(또는 골자 요소)가 자료와 어긋나는 이유 목록. 빈 목록이면 통과. 자료가 없으면 판단하지 않는다."""
    if idx is None or not (text or "").strip():
        return []
    probs = [f"number:{n}" for n in misplaced_numbers(text, idx)]
    probs += ["compare" for _ in unbacked_comparisons(text, idx)][:1]
    probs += ["table" for _ in misattributed_cells(text, idx)][:1]
    probs += ["direction" for _ in direction_conflicts(text, idx)][:1]
    return probs


# ---------------------------------------------------------------------------
# 함정 전제 — 질문에 실제로 들어 있고, 자료가 **틀렸다고** 말할 수 있는 주장이어야 한다
# ---------------------------------------------------------------------------

#: 전제 한 절의 최소 길이. 이보다 짧으면 주장이 아니라 낱말이다.
PREMISE_MIN = 6
#: 전제가 자료 한 줄과 이만큼 같으면 자료를 옮긴 것이다 (글자 순서까지 본 비율).
PREMISE_VERBATIM_RATIO = 0.9
#: 전제 낱말이 자료 한 줄(과 문맥)에 이 비율 이상 있으면 자료를 바꿔 말한 것이다 — 뒤집은 것이 아니다.
PREMISE_PARAPHRASE_RATIO = 0.8
PREMISE_PARAPHRASE_MIN_WORDS = 3


def premise_in_question(premise: str, question: str) -> bool:
    """전제가 질문 문장 안에 있는가 — 글자 그대로(띄어쓰기·문장부호 무시)거나 낱말 80% 이상."""
    p, q = squash(premise), squash(question)
    if len(p) < PREMISE_MIN:
        return False
    if p in q:
        return True
    pw = words(premise)
    qw = words(question)
    return bool(pw) and sum(_word_in(w, qw) or any(w.startswith(x) and len(x) >= 2 for x in qw) for w in pw) / len(pw) >= 0.8


def premise_drop_reason(premise: str, idx: DeckIndex | None) -> str:
    """
    전제가 자료와 **어긋나지 않는** 이유. "" 이면 함정으로 둔다. 순서가 중요하다:

    1. 자료에 없는 숫자를 얹었다 → 함정 (일부러 바꾼 사실이다).
    2. 자료 한 줄을 거의 그대로 옮겼다 → 사실이다.
    3. 숫자가 전부 자료에 있고 주어도 맞다 → 사실이다 (09-29 실측: 「상위 두 요인이 전체의 58%」 는 자료 그대로였는데
       함정 폴백 골자가 「질문의 전제가 자료와 달라요」 라고 가르쳤다).
    4. 숫자가 자료에 있지만 다른 대상에 붙었다 → 함정.
    5. 비교가 자료의 비교 줄로 받쳐진다 → 사실. 안 받쳐지면 → 함정.
    6. 낱말이 자료 한 줄과 거의 같다 → 자료를 바꿔 말한 것이다.

    함정을 **잘못 떼는** 쪽이 싸다 — 떼면 평범한 질문으로 채점되지만, 잘못 두면 자료대로 한 정답이 오답이 된다.
    """
    if idx is None:
        return ""
    spans = label_spans(premise, idx.labels)
    nums = [_norm_num(m.group(0)) for m in _NUM_RE.finditer(premise)
            if significant(_norm_num(m.group(0))) and not any(s.start <= m.start() < s.end for s in spans)]
    if any(not idx.rows_with_number(n) for n in nums):
        return ""
    p = squash(premise)
    for row in idx.all_rows():
        r = squash(row.text)
        if len(r) >= PREMISE_MIN and (p in r or SequenceMatcher(None, p, r).ratio() >= PREMISE_VERBATIM_RATIO):
            return "premise_is_deck_line"
    if nums:
        return "" if misplaced_numbers(premise, idx) else "premise_numbers_true"
    if has_comparison(premise) and not unbacked_comparisons(premise, idx):
        return "premise_comparison_true"
    pw = [stem(w) for w in words(premise) if not w[0].isdigit()]
    pw = [w for w in pw if len(w) >= 2]
    if len(pw) >= PREMISE_PARAPHRASE_MIN_WORDS:
        for row in idx.all_rows():
            bag = [stem(w) for w in words(" ".join(idx.window(row)[:3]))]
            if sum(_word_in(w, bag) for w in pw) / len(pw) >= PREMISE_PARAPHRASE_RATIO:
                return "premise_paraphrases_deck"
    return ""


# ---------------------------------------------------------------------------
# 방법·측정 질문 — 자료에 방법·수치·출처가 있을 때만 물을 수 있다
# ---------------------------------------------------------------------------

_METHOD_VERB = r"(?:측정|계산|정량화|산출|통제|추정|검증|수집|집계)"
_METHOD_ASK_RE = re.compile(
    rf"어떻게\s*{_METHOD_VERB}|{_METHOD_VERB}(?:하는|한|했던|된|되는|할)?\s*(?:방법|기준|방식|절차|근거)"
    rf"|{_METHOD_VERB}(?:했|하였|됐|되었)|표본|방법론"
)
#: 출처·연구 표지 (F-26 `has_support` 와 같은 뜻 — f26 을 import 하지 않으려고 따로 둔다).
_SOURCE_RE = re.compile(
    r"\((?:[^()]*?)(?:19|20)\d{2}[a-z]?\)|et\s+al\.?|doi\s*:|10\.\d{4,9}/|출처|연구|조사|실험|설문|통계|표본|논문|보고서|메타\s*분석"
    r"|study|survey|experiment|source", re.I)
_DATA_RE = re.compile(r"\d[\d,.]*\s*(?:%|퍼센트|배|명|회|번|시간|분|초|년|개월|주|일|세|살|원|달러|점|건|개|곳|위)|\d+\.\d+")


def asks_method(question: str) -> bool:
    """질문이 방법·측정·계산·통제를 묻는가."""
    return bool(_METHOD_ASK_RE.search(question or ""))


def _has_data(row: Row) -> bool:
    if row.table:
        return any(numbers(c) for c in row.cells[1:])
    return bool(_DATA_RE.search(row.text))


def method_supported(question: str, anchors: list[int], idx: DeckIndex | None) -> bool:
    """
    근거 장에 이 질문이 물을 방법·수치·출처가 있는가. 자료가 없으면 참 (판단하지 않는다).
    출처 표지가 있으면 참. 수치는 질문이 부르는 라벨(주제 제외)이 그 수치 줄의 문맥에 있어야 한다 —
    09-29 실측: 「회복 시간을 어떻게 계산했나요」 의 근거 장엔 설문 보기(「5–7시간」)만 있었다. 라벨을 안 부르면 수치만 있으면 참.
    """
    if idx is None:
        return True
    rows = [r for no in anchors for r in idx.rows.get(no, [])]
    if any(_SOURCE_RE.search(r.text) for r in rows):
        return True
    data = [r for r in rows if _has_data(r)]
    if not data:
        return False
    named = [s.label for s in label_spans(question, idx.detail_labels)]
    if not named:
        return True
    return any(any(mentions(t, lab) for t in idx.window(r) for lab in named) for r in data)


# ---------------------------------------------------------------------------
# 논문에서 온 말 — 발표자가 본 적 없는 문헌 이야기는 골자·힌트에 남기지 않는다
# ---------------------------------------------------------------------------

_PAPER_WORD_RE = re.compile(r"문헌|논문|초록|선행\s*연구")
#: 문장의 낱말 가운데 자료·발화에 없는 비율이 이 이상이면 자료 밖에서 온 문장이다.
NOVEL_SHARE_MAX = 0.5


def paper_talk(text: str, idx: DeckIndex | None) -> bool:
    """문헌·논문·초록을 말하는데 자료는 그 말을 안 쓴다 — 서가(교수가 읽고 온 문헌)에서 새어 나온 말이다."""
    for m in _PAPER_WORD_RE.finditer(text or ""):
        if idx is None or m.group(0) not in idx.text:
            return True
    return False


def novel_share(text: str, idx: DeckIndex | None) -> float:
    """글의 낱말(숫자 제외) 가운데 자료·발화에 없는 비율. 자료가 없으면 0."""
    if idx is None:
        return 0.0
    ws = [w for w in words(text) if not w[0].isdigit()]
    if not ws:
        return 0.0
    return sum(not idx.known(w) for w in ws) / len(ws)


#: 문장 경계 — 한글 뒤 마침표·물음표, 또는 해요체 끝. 「et al. (2020)」 의 마침표에서 자르지 않는다.
_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{1,}")


def paper_residue(text: str, idx: DeckIndex | None, paper_texts: list[str], *, novel: bool = False) -> bool:
    """
    글에 논문에서 온 흔적이 있는가 — 논문 제목·초록에 있고 자료·발화에는 없는 영문 낱말(약어·용어), 또는
    novel 이면 자료·발화에 없는 낱말이 절반 이상. 09-29 재실행: 논문 절을 뗀 질문 「…기상 시간이 SRQ 점수와 강하게
    연결된다고 판단한 근거는?」 과 힌트 「SRQ 는 주관적 도구이며 … r ≤ 0.36」 이 남았다 (SRQ 는 논문 초록의 약어).
    """
    if not (text or "").strip():
        return False
    hay = " ".join(paper_texts).lower()
    deck = (idx.text if idx is not None else "").lower()
    for w in _LATIN_WORD_RE.findall(text or ""):
        lw = w.lower()
        if len(lw) >= 2 and re.search(rf"(?<![a-z]){re.escape(lw)}(?![a-z])", hay) and lw not in deck:
            return True
    return novel and novel_share(text, idx) >= NOVEL_SHARE_MAX


_SENT_RE = re.compile(r"(?<=[가-힣][.?!])\s+|(?<=요)\s+(?=[가-힣A-Z])")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_RE.split(text or "") if s and s.strip()]


def strip_paper_sentences(text: str, idx: DeckIndex | None, *, novel: bool) -> str:
    """문헌 이야기를 한 문장을 뗀다. novel 이면 자료 밖 낱말이 절반 이상인 문장도 뗀다 (논문 절을 뗀 질문의 골자)."""
    keep = [s for s in sentences(text)
            if not paper_talk(s, idx) and not (novel and novel_share(s, idx) >= NOVEL_SHARE_MAX)]
    return " ".join(keep)
