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

import math
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ._evidence import (
    clean_slide_text,
    join_sep,
    noise_lines,
    page_marker_rows,
    sentence_ahead,
    strip_chart_descriptions,
    wrap_width,
)

# ---------------------------------------------------------------------------
# 자료 줄 — 글 상자 한 줄, 표는 행 하나가 한 줄
# ---------------------------------------------------------------------------

#: 표 구분 행 「| --- | --- |」.
_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{3,}")
#: 홀로 선 한두 자리 절·단계 번호(「01」「2」「(3)」) — 사실이 아니라 차례 표시다. 쪽 번호 꼴이 아니어도 대조 줄에서 뺀다
#: (앞뒤 줄 문맥 `DeckIndex.window` 를 차례 번호가 차지하지 않게). 「2023」「3.5」 같은 수치 줄은 남긴다 (09-30 G-A12).
_SECTION_NO_RE = re.compile(r"^\(?\d{1,2}\)?\.?$")
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

    줄을 버리는 잣대는 주장 쪽(F-26 `_deck_lines.read_lines`)과 같다 — 쪽 번호 **꼴**과 글 없는 줄만 버리고(숫자만 있는 수치 줄
    「2023」 은 남긴다), 자료 속 지시문은 `clean_slide_text` 가 뺀다 (09-30 WP-Q2). 홀로 선 한두 자리 차례 번호도 뺀다 — 사실이 아니다.
    """
    rows: list[Row] = []
    header = ""
    in_table = False
    # 설문 보기·축 눈금은 자료의 사실이 아니다 — 골자·함정·근거 대조의 재료에서 뺀다 (09-30 held-out C-01: 설문 보기 「3시 이후」 가
    # 골자의 사실이 됐다). 명령 줄(「…로 판정할 것」)은 clean_slide_text 가 이미 지운다.
    noise = noise_lines(raw_text)
    raw_lines = strip_chart_descriptions(raw_text or "").split("\n")
    pages = page_marker_rows([clean_slide_text(x) for x in raw_lines])
    for k, line in enumerate(raw_lines):
        s = line.strip()
        if not s:
            in_table = False
            continue
        table = s.startswith("|")
        if table and _TABLE_SEP_RE.match(s):
            continue
        text = clean_slide_text(s)
        if not text or (not table and (k in pages or text in noise or _SECTION_NO_RE.match(text))):
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
    return _join_wrapped(rows)


def _join_wrapped(rows: list[Row]) -> list[Row]:
    """
    두 줄로 접힌 글 줄을 한 줄로 (`_evidence.continues_to` — 인용 후보와 같은 판단). 표 행·물음 줄·글머리 줄은 그대로.
    09-30 검증 하네스(antonym_gist_rejected): 자료 줄 「스마트폰 위치가 멀어질수록」 / 「인지 과제 수행이 좋아지는 경향」 을 따로 봐서,
    방향이 반대인 골자 「스마트폰이 가까울수록 인지 과제 수행이 좋아지는 경향」 이 방향 검사를 통과했다 (한 줄짜리 같은 문장은 걸렸다).
    """
    texts = [r.text for r in rows if not r.table]
    wrap_at = wrap_width(texts)
    all_texts = [r.text for r in rows]
    out: list[Row] = []
    last_line = ""          # 앞 **물리 줄** — 이어 붙인 덩어리 길이로 폭을 재지 않는다
    for k, r in enumerate(rows):
        prev = out[-1] if out else None
        sep = (join_sep(last_line, r.text, wrap_at, sentence_ahead(all_texts, k))
               if (prev is not None and not prev.table and not r.table) else None)
        last_line = r.text
        if sep is not None:
            out[-1] = Row(slide_no=prev.slide_no, index=prev.index, text=f"{prev.text}{sep}{r.text}")
            continue
        out.append(Row(slide_no=r.slide_no, index=len(out), text=r.text, table=r.table, header=r.header, cells=r.cells))
    return out


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
    #: vocab 의 줄기(조사 뗀 꼴) — `known` 이 쓴다.
    vocab_stems: set[str] = field(default_factory=set)
    #: 문서 변환기가 차트를 읽어 낸 장(「Chart Type:」) — 그 장의 표는 차트 막대 값이다 (`_traps.candidates`).
    chart_slides: set[int] = field(default_factory=set)

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
        """낱말이 자료(·발화)에 있는가. 조사·어미만 다른 꼴(「구조를」 ∋ 「구조」, 「방문객」 ∋ 「방문」)도 같은 낱말로 본다.

        예전엔 **앞 두 글자**만 맞아도 있다고 봤다 — 09-30 레드팀(Q-B): 「가격정책」 이 「가격」 하나로, 「심리적」 이 「심리」 로 통과해
        자료 밖 낱말 비율이 낮게 나왔다. 이제 줄기(조사 뗀 꼴)가 같거나, 한쪽이 다른 쪽 앞머리이면서 **남는 글자가 둘 이하**일 때만."""
        return known_in(word, self.vocab_stems or {stem(w) for w in self.vocab})


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
    charts = {no for no, sl in slides.items() if re.search(r"Chart Type\s*:", getattr(sl, "raw_text", "") or "")}
    return DeckIndex(rows=rows, label_slides=label_slides, topic=topic, vocab=vocab, text=text,
                     vocab_stems={stem(w) for w in vocab}, chart_slides=charts)


def known_in(word: str, stems: set[str]) -> bool:
    """낱말(의 줄기)이 줄기 집합에 있는가 — 같거나, 앞머리가 같고 남는 글자가 둘 이하(어미·접미)."""
    w = stem((word or "").lower())
    if not w:
        return False
    if w in stems:
        return True
    for s in stems:
        if len(s) >= 2 and len(w) >= 2 and (w.startswith(s) or s.startswith(w)) and abs(len(w) - len(s)) <= 2 \
                and w[0] >= "가" and s[0] >= "가":
            return True
    return False


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


#: 「가장 ○○」 의 방향 — 큰 쪽(크다·높다·많다·최대) · 작은 쪽(작다·낮다·적다·최소).
_SUPER_UP_RE = re.compile(r"(?:가장|제일)\s*(?:크|큰|높|많|길|긴|빠르|넓|강하|강한)|최대|최고|최장|최다")
_SUPER_DOWN_RE = re.compile(r"(?:가장|제일)\s*(?:작|낮|적|짧|느리|느린|좁|약하|약한)|최소|최저|최단")


def _table_extreme(named: set[str], idx: DeckIndex, clause: str = "") -> bool:
    """「가장 ○○」 을 표가 받치는가 — 절이 부르는 라벨이 한 표의 행 머리이고, 그 행이 어떤 수치 열에서 절댓값이 **절이 말한 쪽의**
    끝(가장 큰 → 최댓값, 가장 작은 → 최솟값)이다. 차트 표(「요인 | -1.6」)는 「가장 크다」 를 글로 안 쓰고 값으로만 말한다.
    09-30 레드팀(Q-A6): 예전엔 최솟값인 행도 「가장 큰」 의 근거로 받았다. 방향을 못 읽으면(「가장 중요한」) 양 끝 다 받는다."""
    want_up, want_down = bool(_SUPER_UP_RE.search(clause)), bool(_SUPER_DOWN_RE.search(clause))
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
            ends = (hi,) if want_up and not want_down else (lo,) if want_down and not want_up else (hi, lo)
            if any(r in keyed and v in ends for v, r in vals):
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
        backed = _SUPERLATIVE_RE.search(clause) is not None and _table_extreme(named, idx, clause)
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
    # 한글 자료에 영문이 대부분인 표(차트 범례 「Stage | Label / Color」 「N3 | 깊은 수면 / Blue」)는 문서 변환기가 그림을 읽은
    # 것이지 발표자의 설명 표가 아니다 — 09-30 벤치: 다시 쓴 골자에 「Stage: Label / Color · N1-N2: …/ Blue」 가 실렸다.
    if any(_LATIN_WORD_RE.search(c) and not re.search(r"[가-힣]", c) for r in rows for c in r.cells[1:]) \
            and re.search(r"[가-힣]", raw_text or ""):
        rows = [r for r in rows if not any(_LATIN_WORD_RE.search(c) and not re.search(r"[가-힣]", c) for c in r.cells)]
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
                    if not theirs.search(r.text) or mine.search(r.text) or _CLAUSE_NEG_RE.search(r.text):
                        continue
                    rw = _pole_free_words(r.text)
                    shared = cw & rw
                    # 같은 말을 해야 방향을 견준다 — 낱말 둘만 겹친 **다른 조건**의 줄(「알림을 받은 조건에서 과제 수행이 나빠지는
                    # 결과」)과 견주면 자료대로 쓴 골자(「멀어질수록 … 좋아지는」)가 걸렸다. 셋 이상, 또는 그 줄 낱말의 절반 이상.
                    if len(shared) >= DIRECTION_SHARED_MIN and (len(shared) >= 3 or len(shared) * 2 >= len(rw)):
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


#: 방법·조건을 **이름으로** 묻는 꼴 — 「측정 방법과 조건」「선정 기준」「조사 대상」「실제 …와 일치하는지」「대표성」. 이 물음은 수치만으로는
#: 답이 안 된다 — 자료에 방법·출처 줄이 있어야 한다 (09-30 녹음 감사 REC-20: 수치 줄 「…110초」 하나로 「측정 방법과 조건은?」 이,
#: 선정 기준이 없는 덱에서 「구체적인 선정 기준은?」 이 통과했다).
_META_ASK_RE = re.compile(
    r"(?:측정|조사|실험|평가|선정|선발|모집|표집|샘플링|분류|집계)\s*(?:의\s*)?(?:방법|기준|조건|절차|방식|대상|환경|과정)|"
    r"(?:선정|선발|분류|채택|포함|제외)\s*기준|대표성|표본\s*(?:크기|수)")
#: 잰 것이 **실제 상황과 같은지**를 묻는 꼴 — 「실제 매장 환경과 일치하는지」. 자료가 실제와 같다고 적은 줄이 있거나 방법 줄이 있어야 한다.
_VALIDITY_ASK_RE = re.compile(r"실제\s*[가-힣\s]{0,16}?(?:일치하는지|같은지|맞는지|적용되는지|적용될\s*수|다르지\s*않은지)")
#: 방법을 말하는 자료 줄 — 「측정 방법」 머리·「…로 측정/조사/기록」·「…명을 대상으로」·「…간격으로」.
_METHOD_LINE_RE = re.compile(
    r"(?:측정|조사|실험|선정|모집|평가|분석)\s*(?:방법|방식|절차|기준|대상|기간|조건)|(?:으로|로)\s*(?:측정|조사|기록|선정|모집|평가|집계)|"
    r"측정기|간격으로|(?:명|곳|개)을?\s*대상으로")
#: 실제와 같다고 적은 자료 줄 — 「실제 매장과 같은 연습용 키오스크」 같은 꼴.
_VALIDITY_LINE_RE = re.compile(r"실제\s*[가-힣\s]{0,10}(?:같은|일치|동일)")


def _formula_answers(question: str, rows: list[str]) -> bool:
    """장의 식(칸마다 줄이 갈린 식도 다음 몇 줄을 잇는다)의 **좌변**이 질문이 계산을 묻는 대상인가 — 좌변 내용 낱말이 질문에 있다.
    「침대에 누운 시간과 회복 시간의 차이를 어떻게 계산했나요」 는 「수면의 질 = …」 식으로 답할 수 없다."""
    q = [stem(n) for n in content_nouns(question)]
    for i, row in enumerate(rows):
        if "=" not in row:
            continue
        left, right = row.split("=", 1)
        lhs_text = left.strip() or (rows[i - 1] if i else "")
        if not re.search(r"[×✕÷+*]", " ".join([right, *rows[i + 1:i + 6]])):
            continue
        lhs = [stem(n) for n in content_nouns(lhs_text)]
        if lhs and any(_word_in(x, q) for x in lhs):
            return True
    return False


def asks_method(question: str) -> bool:
    """질문이 방법·측정·계산·통제를 묻는가 (방법·조건을 이름으로 묻는 꼴 포함)."""
    q = question or ""
    return bool(_METHOD_ASK_RE.search(q) or _META_ASK_RE.search(q) or _VALIDITY_ASK_RE.search(q))


_CITATION_MARK_RE = re.compile(r"\((?:[^()]*?)(?:19|20)\d{2}[a-z]?\)|et\s+al\.?|doi\s*:|10\.\d{4,9}/", re.I)
#: 계산을 묻는 꼴 — 계산 물음은 근거 장의 식(「X = B × C」)이 답이다 (`_formula_answers`).
_CALC_ASK_RE = re.compile(r"계산|산출|구하|구할|구해")
#: 장 머리로 보는 줄 길이 상한 — 제목·부제는 짧다.
HEADING_MAX = 24


def _is_heading(row: Row) -> bool:
    return not row.table and row.index < HEADING_ROWS and len(row.text) <= HEADING_MAX and not _DATA_RE.search(row.text)


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
    # 장 머리(제목·부제)의 「연구 배경」「조사 개요」 는 출처가 아니다 — 09-30 레드팀(Q-B): 제목 한 줄로 방법 질문이 통과했다.
    # 머리 줄은 인용 표기(「(2019)」·et al.)가 있을 때만 출처로 친다.
    if any(_SOURCE_RE.search(r.text) and (not _is_heading(r) or _CITATION_MARK_RE.search(r.text)) for r in rows):
        return True
    if _META_ASK_RE.search(question or "") or _VALIDITY_ASK_RE.search(question or ""):
        # 방법·조건을 이름으로 묻는 질문 — 방법 줄(측정 방법·…로 조사·…명을 대상으로)이 **덱 어디에든** 있어야 한다. 방법 장은
        # 흔히 따로 있다(「측정 방법」 장). 수치 줄만으로는 답이 안 된다 (09-30 녹음 감사 REC-20). 실제와 같은지 묻는 질문은
        # 자료가 실제와 같다고 적은 줄도 받는다.
        line_re = _METHOD_LINE_RE
        if _VALIDITY_ASK_RE.search(question or "") and not _META_ASK_RE.search(question or ""):
            return any(_METHOD_LINE_RE.search(r.text) or _VALIDITY_LINE_RE.search(r.text) for r in idx.all_rows())
        return any(line_re.search(r.text) for r in idx.all_rows())
    if _CALC_ASK_RE.search(question or "") and any(_formula_answers(question, [r.text for r in idx.rows.get(no, [])])
                                                   for no in anchors):
        return True        # 「X 는 어떻게 계산하나요」 는 근거 장의 「X = …」 식이 답이다 (식에는 수치가 없을 수 있다)
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


#: 문장 경계 — 마침표류 뒤, 또는 마침표 없이 「…요」 로 끝난 뒤. 단 **「요」 로 끝나는 한자어 명사**(주요·필요·중요·수요·
#: 소요·강요·개요·긴요·적요)는 문장 끝이 아니다. 09-30 WP-Q: 골자 「… 이용 감소의 주요 원인이에요.」 가 「주요」 에서 잘려
#: 문장째 거르는 `supported_sentences` 가 반쪽 「원인이에요.」 를 남겼다 (판정의 `keep_sentences` 도 같은 칼을 쓴다).
_SENT_RE = re.compile(r"(?<=[가-힣][.?!])\s+|(?<=[^주필중수소강개긴적]요)\s+(?=[가-힣A-Z])")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_RE.split(text or "") if s and s.strip()]


def strip_paper_sentences(text: str, idx: DeckIndex | None, *, novel: bool) -> str:
    """문헌 이야기를 한 문장을 뗀다. novel 이면 자료 밖 낱말이 절반 이상인 문장도 뗀다 (논문 절을 뗀 질문의 골자)."""
    keep = [s for s in sentences(text)
            if not paper_talk(s, idx) and not (novel and novel_share(s, idx) >= NOVEL_SHARE_MAX)]
    return " ".join(keep)


# ---------------------------------------------------------------------------
# (e) 절 단위 지지 — 골자의 **절마다** 자료 한 곳이 받쳐야 한다 (09-30 held-out 감사 C-01)
#
# 숫자·비교·표·방향 검사(gist_problems)는 **틀린 짝**만 봤다. held-out 5덱에서 무너진 골자는 대부분 짝이 틀린 게 아니라
# **자료에 없는 말을 지어낸** 것이었다 — 「…인슐린 과다 분비가 졸림을 유발해요」「야간 폭식은 심리적·생리적 반응으로」
# 「독서 경험 감소가 방문객 감소의 주요 원인이며」. 절의 **내용 명사**가 자료 한 곳(줄과 앞뒤 줄·표 행과 머리)에 모여 있는지 본다.
# 서술어는 활용이 달라 글자로 못 맞추니 명사만 센다. 관계·평가를 말하는 흔한 추상 명사(영향·역할·원인·현상 …)는 어느 발표에나
# 쓰는 말이라 세지 않는다 — 특정 발표의 낱말은 목록에 없다.
# ---------------------------------------------------------------------------

#: 관계·평가·질문 틀의 추상 명사 — 바꿔 말하기(paraphrase)에 흔히 붙는 말이라 「자료에 있어야 하는 낱말」 로 세지 않는다.
GENERIC_NOUNS = frozenset("""
자료 발표 질문 답 답변 설명 언급 제시 강조 주장 내용 개념 의미 뜻 핵심 중심 주요 중요 필요 가능 가능성 정도 수준 측면 부분 요소 구성
관계 연결 연관 연관성 관련 관련성 영향 역할 기여 작용 효과 결과 원인 이유 근거 요인 조건 경우 상황 문제 방법 방안 대책 해결 해결책
개선 방식 과정 단계 구조 형태 현상 변화 차이 비교 기준 범위 한계 예외 경계 전제 목적 의도 기능 특징 특성 성격 지표 수치 출처 데이터
통계 연구 사례 예시 증거 결론 판단 생각 시각 관점 입장 전체 일부 대부분 모두 각각 여러 다양 구체적 구체 실제 직접 간접 주로 특히 또한
결국 따라서 그래서 이는 이것 그것 이러한 그러한 이번 이후 이전 동시 함께 그대로 다시 먼저 나중 가장 제일 더 덜 매우 크게 작게
실질 실질적 전반 전반적 일반 일반적 기본 기본적 핵심적 결정적 중요성 필요성 점 것 수 때 등 중 간 곳 쪽 편 번 가지 개 명 해 보강 인정
사람 모든 어느 이런 그런 저런 어떤 무슨 각 모든 여러 적용 해당 주체 자체 변수 매개 매개체 수단 도구
장치 계기 바탕 토대 기반 필수 필수적 행위 행동 활동 상태 모습 방향 흐름 모델 전략 체계 시스템 요구 문제점 장점 단점 이점
연간 월간 연평균 평균 전체 총 누적 합계 비율 비중 규모 크기 수준 값 수치 단위 상대적 절대적 대비
무엇 누구 어디 언제 얼마 얼마나 어떻게 어째서 어느쪽 무엇인지 무엇인가요 대상 전후 이상 이하 미만 초과 일반 경향 가능성 확인 검토 활용 이용 제공
이로 인해 이로써 통해 위해 대해 관해 따라 의해 비해 달리 반해 향해 걸쳐 거쳐 이에 이와 그에 그와 이를 그를 이라 이란 라는 라고 이라는
하나 둘 셋 넷 다섯 여섯 일곱 여덟 아홉 첫째 둘째 셋째 전부 서로 각자 나머지 어떤것 무엇이든
""".split())
#: 서술어로 보는 낱말 꼬리 — 명사가 아니라 활용형이다 (「발생해요」「올랐다가」「줄일」「막는」). 명사만 지지 대조에 쓴다.
_PREDICATE_TAIL_RE = re.compile(
    r"(?:다|요|니다|습니다|어요|아요|해요|했|했다|된다|한다|하는|되는|하고|되고|하며|되며|하여|되어|해서|돼서|하면|되면|하게|되게|"
    r"해야|돼야|어야|아야|여야|해도|돼도|어도|아도|하지만|하는데|했는데|"
    r"하지|되지|했고|됐고|한|된|할|될|인|일|던|은|는|을|ㄹ|고|며|면|서|게|지|도록|수록|면서|지만|는데|으나|다가|어서|아서|어야|아야|"
    r"였|었|았|겠|려|러|기|음|함|됨|임)$")
#: 절 경계 — 문장 끝·쉼표(수 안의 쉼표 말고)·줄표·가운뎃점·연결 어미 뒤 빈칸.
_SUPPORT_CLAUSE_RE = re.compile(
    r"(?<=[.?!])\s+|\s+[—–]\s+|(?<!\d),(?!\d)\s*|\s+·\s+|(?:(?<=[가-힣]고)|(?<=[가-힣]며)|(?<=면서)|(?<=지만)|(?<=는데)|(?<=으나))\s+")
#: 지지 대조에서 빼는 인용 — 「…」·«…» 안은 자료 줄을 옮긴 것이라 따로 본다(인용이 자료에 있는지는 호출자가 본다).
_QUOTED_RE = re.compile(r"«[^»]*»|「[^」]*」|“[^”]*”")
#: 절을 「받쳐졌다」 고 보는 몫 — 자료 한 곳(줄과 앞뒤 줄)이 절의 내용 명사를 이만큼 담는다.
CLAUSE_REGION_SHARE = 0.6
#: 한 장 전체로 보면 더 엄하게 — 흩어진 낱말을 이어 붙인 문장일 수 있다.
CLAUSE_SLIDE_SHARE = 0.75


#: 「는」 앞에 와서 관형형(동사)으로 읽히는 줄기 끝 음절 — 「해치는」「보이는」「주는」. 명사 + 는(「회의는」「교사는」)과 가른다.
_VERB_STEM_END = frozenset("치리기히이우주두보오가지시키드르트")
#: ㄴ·ㄹ 관형형 받침을 뗀 음절 가운데 용언 줄기 끝으로 흔한 것.
_ADN_BASE = frozenset("치리기히이우주두보오가지시키드르트하되해나느으려러워와")


def _adnominal_like(word: str) -> bool:
    """관형형 활용처럼 끝나는 낱말 — 조사가 안 붙었는데 끝 음절 받침이 ㄴ·ㄹ(「넓힌」「퍼진」「줄일」)이거나, 「던」 으로 끝나거나,
    동사 줄기 끝 음절 + 「는」(「해치는」). 조사가 붙은 명사(「메커니즘은」「시간을」)는 아니다.
    명사도 이렇게 끝나기에(「기간」「공간」) 자료에 있는 낱말이면 명사로 둔다 (`content_nouns`)."""
    last = word[-1:]
    if not ("가" <= last <= "힣"):
        return False
    if word.endswith("던"):
        return True
    if word.endswith("는") and len(word) >= 2:
        return word[-2] in _VERB_STEM_END
    code = ord(last) - 0xAC00
    if stem(word) != word or code % 28 not in (4, 8):
        return False
    # ㄴ·ㄹ 받침을 뗀 음절이 용언 줄기 끝으로 흔한 꼴일 때만 — 「넓힌(히)」「퍼진(지)」「중요한(하)」「좋은(으)」. 「기존(조)」
    # 「방안(아)」「전환(화)」 같은 한자어 명사는 아니다.
    return chr(0xAC00 + code - code % 28) in _ADN_BASE


#: 보조 용언 활용(「않아」「없는」「있어」「나와 있지」) — 꼬리 규칙(`_PREDICATE_TAIL_RE`)이 못 거르는 꼴. 이 음절로 시작하는 내용
#: 명사는 드물다.
_AUX_PRED_RE = re.compile(r"^(?:않|없|있|나와|나오)[가-힣]{0,3}$")


def content_nouns(text: str, deck_bag: set[str] | None = None) -> list[str]:
    """글의 **내용 명사** 줄기 (순서대로, 중복 없이) — 숫자·서술어·흔한 추상 명사 뺀 것.
    deck_bag(자료 줄기)을 주면 관형형처럼 끝나는 낱말(`_adnominal_like`)은 자료에 있을 때만 명사로 센다 — 형태소 분석 없이
    「넓힌·퍼진·해치는」 을 명사로 읽어 「자료에 없는 낱말」 로 세던 것을 막는다. 대신 「인슐린」 같은 ㄴ 받침 명사도 빠지므로
    **질문을 버릴지** 볼 때(`unknown_terms`)만 쓴다 — 골자 지지 대조는 넉넉히 세는 쪽(다시 쓰는 쪽)이 안전하다."""
    out: list[str] = []
    src = text or ""
    for m in _WORD_RE.finditer(src):
        w = m.group(0).lower()
        if m.start() > 0 and src[m.start() - 1].isdigit():
            continue       # 숫자에 붙은 단위(「8분으로」「9%에서」)는 낱말이 아니다
        if w[0].isdigit() or _ONE_CHAR_NOUN_RE.match(w) or _PREDICATE_TAIL_RE.search(w) and not _noun_with_josa(w) \
                or _AUX_PRED_RE.match(w):
            continue
        s = _cstem(w)
        if len(s) < 2 or s in GENERIC_NOUNS or any(s.startswith(g) and len(s) - len(g) <= 1 for g in GENERIC_NOUNS if len(g) >= 2):
            continue
        if deck_bag is not None and _adnominal_like(w) and not known_in(s, deck_bag):
            continue
        if s not in out:
            out.append(s)
    return out


def _noun_with_josa(word: str) -> bool:
    """「인슐린이」「시간은」 처럼 명사 + 조사 한 겹이면 참 — 꼬리(은·는·을·이 …)가 서술어 꼬리와 겹쳐서 따로 본다.
    줄기가 「하·되·시키」 로 끝나면(「유발하는」→「유발하」) 명사가 아니라 동사 활용이다."""
    s = stem(word)
    return s != word and len(s) >= 2 and not _PREDICATE_TAIL_RE.search(s) and not re.search(r"(?:하|되|시키|해지|돼)$", s)


def _stem_hit(stem_: str, bag: set[str]) -> bool:
    return known_in(stem_, bag)


#: 서술격 꼬리 — 「독자였다」「요인입니다」「요소인데」 의 명사 줄기를 꺼낸다 (지지 대조 전용; `stem` 은 조사만 뗀다).
_COPULA_TAIL_RE = re.compile(
    r"(?:이었다|였다|이다|입니다|이에요|예요|였어요|이었어요|이며|이고|이라서|이라|이란|인데|이지만|인지|이어서|이니까|인|임|였고|이었고)$")
#: 한 글자 명사 + 조사(「질의」「질이」「양을」) — 한 글자 명사는 어디에나 있어 대조에 못 쓴다. 조사 한 겹을 뗀 한 글자면 뺀다.
#: 앞 글자는 **흔한 한 글자 명사**만 — 예전엔 아무 글자나 받아 조사 없이 선 두 글자 명사(「평가」「온도」「도로」「회의」「결과」)가
#: 「평+가」「온+도」 로 읽혀 통째로 빠졌다 (WP-Q 테스트: 식 줄 「… = 맛 평가 × 음식 온도 × …」 의 내용 명사가 반만 남았다).
_ONE_CHAR_NOUN_RE = re.compile(r"^[질양수것등때곳점뒤앞밖속위옆쪽편번값몫힘말글빛돈길집차맛국밥물불몸손발눈귀입꿈]"
                               r"(?:은|는|이|가|을|를|의|에|도|만|과|와|로)$")


def _cstem(word: str) -> str:
    s = stem(word)
    c = _COPULA_TAIL_RE.sub("", s)
    return c if len(c) >= 2 and c != s else s


def _bag(texts) -> set[str]:
    out: set[str] = set()
    for t in texts:
        for w in words(t):
            out.add(stem(w))
            out.add(_cstem(w))
    return out


def _row_bag(idx: DeckIndex, row: Row) -> set[str]:
    return _bag(idx.window(row))


def _slide_bags(idx: DeckIndex) -> dict[int, set[str]]:
    return {no: _bag(r.text for r in rows) for no, rows in idx.rows.items()}


def clause_supported(clause: str, idx: DeckIndex | None, extra_vocab: set[str] | None = None) -> bool:
    """
    절 하나가 자료로 받쳐지는가. 내용 명사가 없으면(틀 문장) 참.
    - 자료 한 곳(줄+앞뒤 줄, 표 행+머리)이 내용 명사의 CLAUSE_REGION_SHARE 이상을 담거나,
    - 한 장이 CLAUSE_SLIDE_SHARE 이상을 담고 자료 어디에도 없는 명사가 없으면 참.
    - 자료 어디에도 없는 명사가 둘 이상이면 거짓 (「인슐린 과다 분비」 처럼 지어낸 말).
    extra_vocab(그래프 라벨 줄기 등)은 「자료 어디에도 없는」 판단에만 더한다 — 라벨은 자료를 읽고 지은 이름이라 지지 근거는 못 된다.
    """
    if idx is None:
        return True
    deck_bag = (idx.vocab_stems or {stem(w) for w in idx.vocab}) | {_cstem(w) for w in idx.vocab}
    # 관형형처럼 끝나고 자료에 없는 말(「곱해진」「넓힌」)은 동사 활용일 수 있다 — 지어낸 명사로도, 몫의 분모로도 세지 않는다.
    # WP-Q 테스트: 「반납 편의성은 …, 앱 안내가 곱해진 것이에요」 가 「곱해진」 하나 때문에 받쳐지지 않는 절이 됐다. 조사가 붙은
    # 명사(「인슐린이」)는 관형형으로 안 읽혀 그대로 센다 — 지어낸 절은 대개 이런 명사가 둘 이상이다.
    nouns = content_nouns(_QUOTED_RE.sub(" ", clause), deck_bag)
    if not nouns:
        return True
    novel = [n for n in nouns if not _stem_hit(n, deck_bag) and not (extra_vocab and _stem_hit(n, extra_vocab))]
    if len(novel) >= 2:
        return False
    need = max(1, math.ceil(CLAUSE_REGION_SHARE * len(nouns) - 1e-9))
    nums = [n for n in numbers(clause) if significant(n)]
    for row in idx.all_rows():
        bag = _row_bag(idx, row)
        hits = sum(1 for n in nouns if _stem_hit(n, bag))
        if hits >= need:
            return True
        # 숫자가 절의 명사와 같은 곳(표 행·줄)에 있으면 그 숫자의 주인을 말한 절이다 — 표는 「| 과잉 매매 | -1.6 |」 처럼 값의
        # 뜻(연간 수익률 %p)을 행에 안 쓴다. 나머지 명사는 자료 어딘가에 있어야 한다(아래 novel 이 없을 때만).
        if nums and hits >= 1 and not novel and all(n in numbers(" ".join(idx.window(row))) for n in nums):
            return True
    if novel:
        return False
    need_slide = CLAUSE_SLIDE_SHARE * len(nouns)
    return any(sum(1 for n in nouns if _stem_hit(n, bag)) >= need_slide for bag in _slide_bags(idx).values())


def support_clauses(text: str) -> list[str]:
    """지지 대조에 쓰는 절 목록 (`_SUPPORT_CLAUSE_RE`)."""
    return [c.strip(" .") for c in _SUPPORT_CLAUSE_RE.split(text or "") if c and len(c.strip(" .")) >= 4]


def unsupported_clauses(text: str, idx: DeckIndex | None, extra_vocab: set[str] | None = None) -> list[str]:
    """자료가 받치지 않는 절 목록 (`clause_supported`). 자료가 없으면 빈 목록."""
    if idx is None or not (text or "").strip():
        return []
    return [c for c in support_clauses(text) if not clause_supported(c, idx, extra_vocab)]


def supported_sentences(text: str, idx: DeckIndex | None, extra_vocab: set[str] | None = None) -> tuple[str, list[str]]:
    """문장마다 절을 대조해 **모든 절이 받쳐진 문장만** 남긴다 → (남은 글, 버린 절). 절 하나만 떼면 연결 어미가 매달려
    말이 안 되므로(「…현상으로,」) 문장째 버린다."""
    if idx is None or not (text or "").strip():
        return text or "", []
    kept: list[str] = []
    dropped: list[str] = []
    for sent in sentences(text) or [text]:
        bad = unsupported_clauses(sent, idx, extra_vocab)
        if bad:
            dropped.extend(bad)
        else:
            kept.append(sent.strip())
    return " ".join(kept).strip(), dropped


# ---------------------------------------------------------------------------
# (f) 「자료에 없다」 는 말도 자료와 대조한다 (09-30 held-out C-01)
# 혈당 t10: 골자 「식후 졸림을 개선하는 구체적인 방법은 자료에 제시되지 않았어요」 — 5장 첫 줄이 「… 순서로 먹으면 식후 졸림을
# 줄일 수 있습니다」 였다. 코치는 한 질문 안에서 1턴엔 「줄일 수 있다고 나와 있어요」, 3턴엔 「제시되지 않았어요」 로 스스로 뒤집었다.
# ---------------------------------------------------------------------------

_ABSENCE_RE = re.compile(
    r"(?:자료|발표|슬라이드)(?:에|에서는?|에는|엔)?\s*(?:\S+\s*){0,4}?(?:없|제시(?:되지|하지|돼\s*있지|되어\s*있지)\s*않|나와\s*있지\s*않|"
    r"나오지\s*않|언급(?:되지|하지)\s*않|명시(?:되지|하지)\s*않|다루지\s*않|찾을\s*수\s*없|확인할\s*수\s*없)"
    r"|(?:제시|언급|명시)(?:되지|하지)\s*않|나와\s*있지\s*않|빠져\s*있")
#: 해결·방법이 없다는 말인지 — 그러면 자료의 「해결 줄」 을 찾는다.
_REMEDY_ASK_RE = re.compile(r"방법|방안|해결책|대책|대안|개선|해결|해소|줄이|줄일|막|낮추|다루|대응|보완")
#: 해결·개선을 말하는 서술어 (어느 분야에나 쓰는 한국어 동사 줄기).
REMEDY_VERB_RE = re.compile(
    r"줄이|줄일|줄입|줄여|줄어|막|낮추|낮춥|낮춰|개선|해결|해소|풀|없애|없앱|늘리|늘립|늘려|높이|높입|높여|지원|확충|도입|바꾸|바꿉|바꿔|"
    r"예방|방지|완화|단축|보완|대응|채우|채웁|지키|지킵|유지")
#: 근거(수치·출처)가 없다는 말인지.
_EVIDENCE_ASK_RE = re.compile(r"수치|출처|근거|데이터|연구|통계|자료\s*조사")
_SOURCE_OR_DATA_RE = re.compile(r"\d|연구|조사|설문|통계|실험|보고서|논문|et\s+al|\(\s*(?:19|20)\d{2}\s*\)", re.I)


#: 목적어 한 덩이 — 「집중을」「원인을」. 개념과 해결 동사 사이에 끼면 동사가 받는 것은 그 목적어다.
_OBJECT_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}(?:을|를)(?=\s|$)")
#: 개념 이름 뒤에 와서 「개념이 동사의 대상·화제」 로 읽히는 조사 (「소음을 줄이다」「소음은 …로 줄인다」「소음도 해결된다」).
_TARGET_JOSA = ("을", "를", "은", "는", "도", "만")


def remedy_of(label: str, line: str) -> bool:
    """
    줄이 **이 개념을** 해결한다고 말하는가 — 개념 이름 + 대상·화제 조사 뒤에 해결 동사(`REMEDY_VERB_RE`)가 오고, 그 사이에 다른
    목적어가 없다. 「흡음재를 붙이면 소음을 줄일 수 있습니다」「소음은 흡음재로 줄입니다」 는 참, 「소음이 집중을 낮춥니다」(개념이
    주어 · 동사는 다른 목적어를 받는다)와 제목 「급식 잔반 줄이기」(조사 없는 명사구)는 거짓이다.
    """
    toks = [t for t in (label or "").split() if t]
    if not toks:
        return False
    for m in re.finditer(r"\s*".join(map(re.escape, toks)) + r"(?P<j>을|를|은|는|도|만|이|가|의)?", line or ""):
        if m.group("j") not in _TARGET_JOSA:
            continue
        rest = line[m.end():]
        verb = REMEDY_VERB_RE.search(rest)
        if verb and not _OBJECT_RE.search(rest[:verb.start()]):
            return True
    return False


def absence_contradicted(text: str, idx: DeckIndex | None, question: str = "", *, plain: bool = True) -> str:
    """
    글이 「자료에 없다」 고 하는데 자료가 그것을 **말하고 있으면** 그 자료 줄 (없으면 "").
    - 해결·방법이 없다는 말 → 대상 명사와 해결 동사가 한 줄에 같이 있으면 그 줄.
    - 수치·출처가 없다는 말 → 대상 명사가 든 줄 곁에 수치·출처가 있으면 그 줄.
    - 그냥 없다는 말 → 대상 명사가 전부 한 줄에 있으면 그 줄.
    대상 명사는 그 문장(없으면 질문)의 내용 명사다. 「그냥 없다」 는 대상이 **그 문장에서** 나왔을 때만 본다 — 질문의 명사는
    주제일 뿐이라(「국 온도는 얼마나 달라지나요」), 주제 줄이 있다고 「달라지는 폭」 이 자료에 있는 것은 아니다. plain=False 면
    해결·수치 두 갈래만 본다 (이유 줄처럼 무엇이 없다는지 흐린 글).
    """
    if idx is None:
        return ""
    for sent in sentences(text) or [text]:
        if not _ABSENCE_RE.search(sent or ""):
            continue
        deck_bag = idx.vocab_stems or {stem(w) for w in idx.vocab}
        targets = [n for n in content_nouns(_QUOTED_RE.sub(" ", sent), deck_bag) if not REMEDY_VERB_RE.match(n)]
        own = bool(targets)
        if not targets:
            targets = [n for n in content_nouns(question, deck_bag) if not REMEDY_VERB_RE.match(n)]
        if not targets:
            continue
        remedy = bool(_REMEDY_ASK_RE.search(sent))
        evidence = bool(_EVIDENCE_ASK_RE.search(sent))
        need = targets if len(targets) <= 2 else targets[:2] if remedy else targets
        rows = [r for r in idx.all_rows() if all(_stem_hit(t, {stem(w) for w in words(r.text)}) for t in need)]
        if remedy:
            # 개념이 해결 동사의 **대상**인 줄이 먼저 (`remedy_of`) — 제목 「급식 잔반 줄이기」 는 해결을 말한 줄이 아니다 (WP-Q 테스트:
            # 4장 「배식 순서를 바꾸면 잔반을 줄일 수 있습니다」 대신 1장 제목이 골자가 됐다). 없으면 장 머리가 아닌 해결 동사 줄.
            hit = next((r for r in rows if any(t in r.text and remedy_of(t, r.text) for t in need)), None) \
                or next((r for r in rows if REMEDY_VERB_RE.search(r.text) and not _is_heading(r)), None)
            if hit is not None:
                return f"S{hit.slide_no} «{hit.text}»"
        for row in rows:
            if evidence and not remedy and any(_SOURCE_OR_DATA_RE.search(t) for t in idx.window(row)[:3]):
                return f"S{row.slide_no} «{row.text}»"
            if not remedy and not evidence and plain and own:
                return f"S{row.slide_no} «{row.text}»"
    return ""


# ---------------------------------------------------------------------------
# (g) 질문 문장의 전제 — 함정이 아닌 질문이 자료와 반대 방향·뒤집힌 비교·자료에 없는 말을 전제로 깔면 거짓 전제다 (C-02)
# 도서관 t5 Q1: 「독서 경험보다 대출 권수가 더 중요하다고 했는데, …」 — 자료 1장은 「대출 권수보다 더 중요한 것은 독서 경험」.
# 같은 세트의 함정 질문과 같은 뒤집힌 문장이 **함정 표시 없이** 나갔고, 정정한 답이 「질문과 다른 이야기」 가 됐다.
# ---------------------------------------------------------------------------

#: 비교 서술어의 방향 — 큰·중요한 쪽(UP) · 작은 쪽(DOWN). 어느 분야에나 쓰는 형용사 줄기.
_CMP_UP = ("중요", "크", "큰", "커", "높", "많", "앞서", "앞선", "우선", "필요", "효과적", "강하", "강한", "넓", "길", "긴", "빠르", "빠른", "낫", "나은", "좋")
_CMP_DOWN = ("작", "낮", "적", "덜", "약하", "약한", "좁", "짧", "느리", "느린", "못하", "못한", "나쁘", "나쁜")
_NP = r"[가-힣A-Za-z0-9·]+(?:\s[가-힣A-Za-z0-9·]+){0,2}?"
#: 끝이 정해진 명사구(제목꼴의 Y)는 욕심껏 — 게으르게 잡으면 「… 것은 반납 편의성입니다」 의 Y 가 첫 낱말 「반납」 에서 멈춘다.
#: 서술격 꼬리(「편의성입니다」)는 `_np_key` 가 뗀다.
_NP_G = r"[가-힣A-Za-z0-9·]+(?:\s[가-힣A-Za-z0-9·]+){0,2}"
#: Y 와 「X보다」 사이에 올 수 있는 부사 — 아무 낱말이나 받으면 X 의 앞 낱말(「반납 편의성」 의 「반납」)을 먹는다 (WP-Q 테스트).
_CMP_ADV = r"(?:(?:오히려|훨씬|사실|실제로|정말|특히|더|더욱)\s+)?"
#: 「X보다 (더) P Y」(제목꼴) · 「X보다 (더) P 것은 Y」 · 「X보다 Y(가) (더) P」 · 「Y(는) X보다 (더) P」.
_CMP_TITLE_RE = re.compile(rf"(?P<x>{_NP})보다\s+(?:더\s+|훨씬\s+|더욱\s+)?(?P<p>[가-힣]{{1,6}}(?:한|은|인|운|른|큰|진|난|된|선))\s+(?:것은\s+|건\s+)?(?P<y>{_NP_G})(?=$|[\s.,?!]|이다|입니다|이에요|예요|라고|이라고|라는|이라는)")
_CMP_XY_RE = re.compile(rf"(?P<x>{_NP})보다\s+(?P<y>{_NP})(?:이|가|은|는)\s+(?:더\s+|훨씬\s+)?(?P<p>[가-힣]{{1,6}})")
_CMP_YX_RE = re.compile(rf"(?P<y>{_NP})(?:이|가|은|는)\s+{_CMP_ADV}(?P<x>{_NP_G})보다\s+(?:더\s+|훨씬\s+|더욱\s+)?(?P<p>[가-힣]{{1,6}})")


def _cmp_dir(pred: str) -> str:
    p = pred or ""
    if p.startswith(_CMP_DOWN):
        return "down"
    if p.startswith(_CMP_UP):
        return "up"
    return ""


#: 명사구 열쇠에서 빼는 한 글자 말 — 「것은」「더」 처럼 대상이 아닌 말. 「수면의 질」 의 「질」, 「대여소 수」 의 「수」 는 남긴다
#: (한 글자를 다 빼면 「수면의 질」 과 「수면 시간」 이 같은 열쇠 「수면」 을 가져 비교 쪽을 못 가렸다).
_NP_STOP_ONE = frozenset("것 등 점 건 더 중 때 곳 쪽 편 번".split())


def _np_key(phrase: str) -> tuple[str, ...]:
    out = []
    for w in words(phrase):
        s_ = _cstem(w)
        if w[0].isdigit() or not s_ or (len(s_) < 2 and s_ in _NP_STOP_ONE) or s_ in GENERIC_NOUNS:
            continue
        out.append(s_)
    return tuple(out)


def comparisons(text: str) -> list[tuple[tuple[str, ...], tuple[str, ...], str]]:
    """글이 말하는 비교 (작은 쪽 명사구, 큰 쪽 명사구, 방향) — 방향은 서술어가 UP 이면 「y 가 x 보다 크다」."""
    out = []
    for rx in (_CMP_TITLE_RE, _CMP_XY_RE, _CMP_YX_RE):
        for m in rx.finditer(text or ""):
            d = _cmp_dir(m.group("p"))
            x, y = _np_key(m.group("x")), _np_key(m.group("y"))
            if d and x and y and x != y:
                out.append((x, y, d))
    return out


def _np_same(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """명사구 둘이 같은 대상인가 — 한쪽 낱말이 다른 쪽에 다 들어 있다(「대출 권수」 ⊂ 「1인당 대출 권수」)."""
    if not a or not b:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return all(any(known_in(w, {v}) for v in long_) for w in short)


def _np_sim(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """같은 대상이면(`_np_same`) 낱말이 얼마나 겹치나 (0~1), 아니면 0."""
    if not _np_same(a, b):
        return 0.0
    hits = sum(1 for w in a if any(known_in(w, {v}) for v in b))
    return hits / max(len(a), len(b))


def comparison_flips(text: str, idx: DeckIndex | None) -> list[str]:
    """글의 비교가 자료 줄의 비교를 **뒤집은** 곳 (자료 줄 목록). 같은 두 대상인데 큰 쪽이 바뀌었다.
    두 쪽이 낱말을 나눠 가지면(「수면 시간」·「수면의 질」) 한쪽이 다른 쪽에 다 들어 있어 바로 대응·뒤집은 대응이 둘 다 「같다」 로
    나온다 — 겹침이 더 큰 대응을 고른다 (WP-Q 테스트: 안 뒤집은 질문을 뒤집었다고 볼 뻔했다)."""
    if idx is None:
        return []
    mine = comparisons(text)
    if not mine:
        return []
    out: list[str] = []
    for row in idx.all_rows():
        for dx, dy, dd in comparisons(row.text):
            for qx, qy, qd in mine:
                a, b = _np_sim(qx, dx), _np_sim(qy, dy)
                c, d = _np_sim(qx, dy), _np_sim(qy, dx)
                direct = a + b if a and b else 0.0
                swapped = c + d if c and d else 0.0
                if (swapped > direct and qd == dd) or (direct > swapped and qd != dd):
                    if row.text not in out:
                        out.append(row.text)
    return out


#: 질문이 자료·발표의 말로 **얹은** 전제 절 — 「…라고 했는데,」「…라는 내용이 있는데,」「…다고 했는데,」.
_ATTRIBUTED_RE = re.compile(r"^(?P<p>.+?)(?:이?라고|다고|라는\s*내용이\s*있는데|이라는\s*내용이\s*있는데|라는\s*말이\s*있는데)\s*(?:했는데|하셨는데|말했는데|설명했는데|주장했는데|제시했는데|,)")


def attributed_premise(question: str) -> str:
    """질문 앞머리의 「…라고 했는데」 전제 절 (없으면 "")."""
    m = _ATTRIBUTED_RE.search(question or "")
    return m.group("p").strip(" 「」“”\"'") if m else ""


#: 최상급을 **자료가 정한 것처럼** 깔고 그 까닭을 묻는 꼴 — 「…가장 중요한 변수로 설정된 이유」「가장 큰 원인이라고 본 근거」.
_PRESUPPOSE_RE = re.compile(r"이유|까닭|근거|배경|(?<![가-힣])왜(?![가-힣])|(?:로|으로)\s*(?:설정|선정|꼽|정한|정했|정하|본|봤|보는|삼은|삼았|둔|두었)"
                            r"|(?:라고|이라고)\s*(?:한|본|했|하는)")


def superlative_premise(question: str, idx: DeckIndex | None) -> str:
    """
    질문이 **자료에 없는 최상급**을 전제로 깔고 그 까닭을 묻는가 → 그 최상급 구절 (아니면 ""). 09-30 녹음 감사 REC-20: 「환기 면적이
    '세 가지 요소' 중 가장 중요한 변수로 설정된 이유」 — 자료는 세 요소를 곱으로 나란히 둘 뿐 순위를 말하지 않았다.
    자료 줄에 최상급 말(가장·제일·최대·최고 …)이 있고 질문의 그 구절과 내용 낱말을 나누면 자료가 한 말이라 막지 않는다. 「무엇이 가장
    중요한가요?」 처럼 순위를 **묻는** 질문은 전제가 아니다.
    """
    if idx is None:
        return ""
    q = _QUOTED_RE.sub(" ", question or "")
    for m in _SUPERLATIVE_RE.finditer(q):
        if not _PRESUPPOSE_RE.search(q[m.end(): m.end() + 40]):
            continue
        nouns = [stem(n) for n in content_nouns(q[max(0, m.start() - 24): m.end() + 12])]
        backed = any(_SUPERLATIVE_RE.search(r.text) and (not nouns or any(_word_in(n, [stem(w) for w in words(r.text)])
                                                                           for n in nouns))
                     for r in idx.all_rows())
        if not backed:
            return q[m.start(): m.end() + 10].strip()
    return ""


def question_premise_problems(question: str, idx: DeckIndex | None, extra_vocab: set[str] | None = None) -> list[str]:
    """
    함정이 아닌 질문 문장이 자료와 어긋나는 전제를 까는가 → 사유 목록 (빈 목록이면 통과).
    - "direction": 같은 대상을 반대 방향 말로 (가까울수록↔멀어질수록 · 늘다↔줄다)
    - "comparison": 자료의 비교를 뒤집었다 (X보다 중요한 Y ↔ Y보다 X 가 더 중요)
    - "superlative": 자료가 안 매긴 최상급을 전제로 까닭을 묻는다 (`superlative_premise`, 09-30 녹음 감사 REC-20)
    - "unsupported_premise": 「…라고 했는데」 로 자료의 말처럼 얹은 절이 자료에 없다 (자료 밖 명사 둘 이상 또는 받치는 곳 없음)
    """
    if idx is None or not (question or "").strip():
        return []
    out: list[str] = []
    if direction_conflicts(question, idx):
        out.append("direction")
    if comparison_flips(question, idx):
        out.append("comparison")
    if superlative_premise(question, idx):
        out.append("superlative")
    premise = attributed_premise(question)
    if premise and len(content_nouns(premise)) >= 2 and not clause_supported(premise, idx, extra_vocab):
        out.append("unsupported_premise")
    return out


# ---------------------------------------------------------------------------
# (h) 답할 수 있는 질문인가 — 질문이 묻는 대상 명사가 자료에 없으면 발표자는 답할 재료가 없다 (09-30 held-out M-04)
# 「다른 유사 서비스와 차별화되는 핵심 요소」「B2C·B2B 가격 정책」「다른 연령층과 어떻게 다른가요」「핵심 메커니즘은」.
# ---------------------------------------------------------------------------

#: 묻는 대상 자리 — 「…X는 무엇인가요」「…X를 어떻게」「X는 어떤가요」 의 X (조사 앞 낱말).
_ASK_HEAD_RE = re.compile(r"([가-힣A-Za-z]{2,})(?:은|는|이|가|을|를)\s+(?:무엇|어떤|어떻게|어디|누구|왜|얼마)")


#: 질문이 묻는 **틀** 낱말 — 방향·인과·경로처럼 물음에 흔히 붙는 말. 답할 수 있는지 볼 때만 뺀다(골자 지지 대조에서는 센다).
ASK_FRAME_NOUNS = frozenset("증가 감소 상승 하락 인과 경로 흐름 원리 작동 구체 순서 우선 영향력 효과성 타당성 설득력 한계점 반례".split())


def unknown_terms(question: str, idx: DeckIndex | None, extra_vocab: set[str] | None = None) -> list[str]:
    """질문의 내용 명사 가운데 자료(·그래프 라벨)에 없는 것. 따옴표 인용 안은 뺀다(자료 줄을 옮긴 것이다)."""
    if idx is None:
        return []
    deck_bag = (idx.vocab_stems or {stem(w) for w in idx.vocab}) | {_cstem(w) for w in idx.vocab}
    return [n for n in content_nouns(_QUOTED_RE.sub(" ", question or ""), deck_bag | (extra_vocab or set()))
            if n not in ASK_FRAME_NOUNS and not _stem_hit(n, deck_bag) and not (extra_vocab and _stem_hit(n, extra_vocab))]


def unanswerable(question: str, idx: DeckIndex | None, extra_vocab: set[str] | None = None) -> list[str]:
    """
    자료로 답할 수 없는 질문이면 자료에 없는 낱말들 (아니면 빈 목록). 자료 밖 명사가 둘 이상이거나, 묻는 대상 자리의 명사
    (「…메커니즘은 무엇인가요」)가 자료 밖이면. 한 낱말 바꿔 말하기(「방문객」↔「방문자」)는 `known_in` 이 받는다.
    """
    unknown = unknown_terms(question, idx, extra_vocab)
    if len(unknown) >= 2:
        return unknown
    head = [stem(m.group(1)) for m in _ASK_HEAD_RE.finditer(_QUOTED_RE.sub(" ", question or ""))]
    return unknown if any(h in unknown for h in head) else []


# ---------------------------------------------------------------------------
# (i) 녹음이 자료와 같은 발표인가 — 겹침이 아주 낮으면 F-08 은 녹음을 무시하고 자료만으로 묻는다 (09-30 held-out C-07)
# /temp: 다른 발표 녹음(겹침 3%)으로 「한끼곳간 … 알림이 집중을 크게 방해하는 이유」 가 나왔다. 리포트(F-04)는 알고 있었는데
# F-08 은 몰랐다. F-04 를 import 하지 않고(모듈 규칙) 같은 뜻의 겹침을 여기서 잰다.
# ---------------------------------------------------------------------------

#: 겹침을 재기에 발화가 너무 짧으면 판단하지 않는다 (내용 낱말 수).
SPEECH_MIN_WORDS = 20
_SPEECH_STOP = frozenset("""
그리고 그래서 하지만 그런데 이것 저것 그것 이거 저거 우리 여기 거기 지금 다음 먼저 이제 정말 가장 조금 때문 경우 생각 부분 정도 이렇게 그렇게
어떤 무엇 합니다 입니다 있습니다 됩니다 습니다 니다 에서 으로 오늘 여러분 발표 슬라이드 감사합니다 안녕하세요 그럼 이번 제가 저희 이렇게
""".split())


def speech_overlap(speech_text: str, deck_text: str) -> tuple[float, int]:
    """발화 낱말(두 글자 이상·불용어 뺀 것) 가운데 자료에도 있는 비율과 발화 낱말 수. 조사 뗀 줄기·앞머리로 맞춘다."""
    speech = {stem(w) for w in words(speech_text) if not w[0].isdigit() and w not in _SPEECH_STOP}
    speech = {w for w in speech if len(w) >= 2 and w not in _SPEECH_STOP}
    if not speech:
        return 0.0, 0
    deck = {stem(w) for w in words(deck_text) if not w[0].isdigit()}
    hit = sum(1 for w in speech if known_in(w, deck))
    return hit / len(speech), len(speech)
