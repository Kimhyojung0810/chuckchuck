"""
F-04 파생 — 업로드된 녹음에서 슬라이드 전환 시각을 추정한다.

라이브 리허설은 브라우저가 실제 전환을 기록한다 (`sdk/slide_marks.js`).
그런데 「녹음 파일로 대신하기」로 올린 음성에는 그 기록이 없다.
지금까지는 재생 길이를 장수로 균등 분할해서 채웠는데, 12장 10분이면
무조건 장당 50초가 된다. 실제로는 도입에 2분, 결론에 30초를 쓴다.
그 어긋난 구간이 F-11 정합 판정으로 그대로 넘어가 **엉뚱한 발화가 엉뚱한
슬라이드에 붙는다.** 사용자가 "개념 추출이 제대로 안 된다" 고 느낀 원인이다.

여기서는 발화 내용을 슬라이드 본문과 맞춰서 경계를 되짚는다.
LLM 을 쓰지 않는다 — 같은 입력이면 늘 같은 결과여야 하고(f11_flow·f13_score 와
같은 규율), 발표 직전에 과금 API 를 한 번 더 태울 이유도 없다.

## 알고리즘

1. **토큰화** — 슬라이드 본문과 발화를 각각 내용어로 쪼갠다.
2. **IDF 가중** — 모든 슬라이드에 나오는 말("그리고"·발표 주제어)은 변별력이
   없다. 흔할수록 가중치를 낮춘다.
3. **창 분할** — 발화를 일정 길이 창으로 자르고, 창마다 어느 슬라이드에
   가까운지 점수를 낸다.
4. **단조 정렬(DP)** — 발표는 앞으로 간다. 창 i 가 슬라이드 s 에 있으면
   창 i+1 은 s 이상이다. 이 제약 아래 총점을 최대화하는 경로를 찾는다.
   되돌아가기(재방문)는 다루지 않는다 — 근거 없이 지어내지 않는다.
5. **신뢰도** — 맞춘 점수가 낮으면 추정을 버리고 균등 분할로 물러난다.
   그리고 그 사실을 **숨기지 않고 반환한다** (CLAUDE.md §4 "실패하면 실패로").
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .contracts import SlideDoc, SlideMark, Word

__all__ = ["InferredMarks", "infer_slide_marks", "even_slide_marks"]

#: 발화를 자르는 창 길이(초). 짧으면 잡음에 흔들리고 길면 경계가 뭉개진다.
WINDOW_SEC = 6.0

#: 이 점수 아래면 정렬을 믿지 않고 균등 분할로 물러난다.
#: 자료를 잘못 올렸거나 발화가 자료와 아예 다른 주제일 때 걸린다.
MIN_CONFIDENCE = 0.12

#: 폭 0 인 장(= 발화가 한 낱말도 안 붙는 장)의 허용 비율.
#:
#: DP 경로가 안 들른 장은 0초 구간으로 남고(아래 `a = b = cursor`), `split_by_slide`
#: 가 거기에 단어를 하나도 안 넣는다. 그러면 F-11 정합은 그 개념들을 "말한 적 없음"
#: 으로 보고 화면이 통째로 빈다 — 사용자에게는 **분석이 아예 안 된 것으로 보인다.**
#:
#: 개수 가드(`len(used)`)로는 이걸 못 잡는다. 2026-08-08 실측: 수면 자료 8장에
#: 집중·알림 녹음을 붙였더니 confidence 0.1931 로 MIN_CONFIDENCE 를 넘고
#: 쓰인 장도 5개라 `max(2, 8//2)=4` 를 통과했는데, **2·3·4 장이 폭 0** 이었다.
#: 쓰인 장이 몇 개인지가 아니라 **빈 장이 몇 개인지**를 따로 봐야 걸린다.
#:
#: 값은 1/4 이다. 발표자가 부록 몇 장을 실제로 건너뛰는 일은 흔하지만
#: (33장 중 4장이면 12%), 넷 중 하나가 통째로 비었다면 건너뛴 것이 아니라
#: 못 맞춘 것이다.
MAX_EMPTY_RATIO = 0.25

#: 「아예 다른 내용」 판정 — 아래 두 신호가 **모두** 이 값 아래일 때만 내린다.
#:
#: "잘 맞지 않아요" 는 구간을 못 맞췄다는 말이지 왜 못 맞췄는지가 아니다.
#: 자료와 무관한 녹음을 올린 사용자에게 가장 필요한 정보는 "다른 파일을 올렸다"
#: 이고, 그걸 뭉개면 애매한 분석 결과를 붙잡고 원인을 찾게 된다 (2026-08-08 제보).
#:
#: 2026-08-08 실측 — 실녹음 2종(집중·알림 547단어, 수면 728단어)을 서로의
#: 자료와 무관 자료에 교차로 붙였다 (겹침 · 커버 순):
#:   집중 녹음 ↔ 집중 자료 12장   0.403 · 0.966   ← 맞음. 판정하면 안 됨
#:   수면 녹음 ↔ 수면 자료 8장    0.293 · 0.867   ← 맞음. 판정하면 안 됨
#:   집중 녹음 ↔ 수면 자료(실사고) 0.131 · 0.431   ← 판정해야 함
#:   수면 녹음 ↔ 집중 자료        0.122 · 0.518   ← 판정해야 함
#:   집중 녹음 ↔ RINGLE 마케팅    0.258 · 0.828   ← 경계 — 안 내린다
#:   녹음 불문 ↔ 영어 자료 2종    0.000~0.003     ← 판정해야 함
#:
#: 한국어끼리는 흔한 낱말이 겹쳐서(RINGLE 0.258 > 수면 맞음 0.293 코앞) 겹침
#: 하나로는 못 가른다. 둘을 AND 로 묶으면 틀린 조합 넷은 다 잡히고, 맞는 조합
#: 최솟값(0.293·0.867)과는 두 신호 모두 1.4배 이상 여유가 있다. 경계 사례
#: (RINGLE)는 기존 "맞지 않아요" 문구로 남는다 — 확신 없는 단정은 안 한다.
UNRELATED_MAX_OVERLAP = 0.2   # IDF 가중: 발화 어휘 중 자료에도 있는 비중
UNRELATED_MAX_COVER = 0.6     # 발화가 있는 창 중 어느 슬라이드와든 겹친 비율

#: 조사·접속어는 어느 슬라이드인지 못 가린다.
_STOP = {
    "그리고", "그래서", "하지만", "그런데", "이것", "저것", "그것", "이거", "저거",
    "우리", "여기", "거기", "지금", "다음", "먼저", "이제", "정말", "가장", "조금",
    "때문", "경우", "생각", "부분", "정도", "이렇게", "그렇게", "어떤", "무엇",
    "합니다", "입니다", "있습니다", "됩니다", "습니다", "니다", "에서", "으로",
}

_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")


def _tokens(text: str) -> list[str]:
    """내용어만 남긴다. 두 글자 미만과 불용어는 버린다."""
    out: list[str] = []
    for raw in _TOKEN.findall(str(text or "").lower()):
        if len(raw) < 2 or raw in _STOP:
            continue
        out.append(raw)
        # 한국어는 조사가 붙어 같은 낱말이 갈라진다. 어간 쪽도 넣어
        # "임베딩을" 과 "임베딩" 이 만나게 한다.
        if len(raw) > 3:
            out.append(raw[: len(raw) - 1])
    return out


def _slide_tokens(doc: SlideDoc) -> list[set[str]]:
    """슬라이드마다 토큰 집합. 제목과 본문 블록을 모두 본다."""
    per: list[set[str]] = []
    for s in doc.slides:
        buf = [getattr(s, "title", "") or ""]
        for b in (getattr(s, "blocks", None) or []):
            buf.append(b.get("text", "") if isinstance(b, dict) else str(b))
        per.append(set(_tokens(" ".join(buf))))
    return per


def _idf(per_slide: list[set[str]]) -> dict[str, float]:
    """모든 슬라이드에 나오는 말은 슬라이드를 못 가린다 → 가중치를 낮춘다."""
    n = max(1, len(per_slide))
    df: dict[str, int] = {}
    for toks in per_slide:
        for t in toks:
            df[t] = df.get(t, 0) + 1
    return {t: math.log(1.0 + n / c) for t, c in df.items()}


@dataclass
class InferredMarks:
    """
    추정 결과.

    marks      : 추정한(또는 물러선) 슬라이드 구간
    estimated  : True 면 내용 정합으로 추정, False 면 균등 분할
    confidence : 0~1. 낮을수록 근거가 약하다
    reason     : 화면에 그대로 보여도 되는 한 줄 설명
    match      : 녹음과 자료의 관계 판정.
                 "matched"   — 내용으로 구간을 맞췄다
                 "weak"      — 구간은 못 맞췄지만 다른 내용이라 단정할 근거는 없다
                 "unrelated" — 아예 다른 내용이다 (겹침·커버 둘 다 임계 아래)
                 "unknown"   — 발화나 자료 텍스트가 없어 판정 자체가 불가능하다
    """

    marks: list[SlideMark]
    estimated: bool
    confidence: float
    reason: str
    match: str = "unknown"


def even_slide_marks(duration_sec: float, n_slides: int) -> list[SlideMark]:
    """길이를 장수로 균등 분할한다. 추정이 안 될 때 물러설 자리."""
    n = max(1, int(n_slides))
    total = max(0.0, float(duration_sec))
    step = total / n
    return [
        SlideMark(
            slide_no=i + 1,
            start_sec=round(i * step, 2),
            end_sec=round((i + 1) * step if i < n - 1 else total, 2),
            visit=1,
        )
        for i in range(n)
    ]


def infer_slide_marks(
    doc: SlideDoc,
    words: list[Word] | list[dict],
    duration_sec: float | None = None,
) -> InferredMarks:
    """
    발화 내용을 슬라이드 본문과 맞춰 전환 시각을 되짚는다.

    같은 입력이면 늘 같은 결과다. 외부 호출이 없다.
    """
    n_slides = len(doc.slides)
    seq = [
        w if isinstance(w, dict)
        else {"text": w.text, "start_sec": w.start_sec, "end_sec": w.end_sec}
        for w in (words or [])
    ]
    total = float(duration_sec or (seq[-1]["end_sec"] if seq else 0.0) or 0.0)

    if n_slides <= 1 or not seq or total <= 0:
        return InferredMarks(
            marks=even_slide_marks(total, n_slides), estimated=False, confidence=0.0,
            reason="발화가 없어 길이를 장수로 균등하게 나눴어요.",
        )

    per_slide = _slide_tokens(doc)
    if not any(per_slide):
        return InferredMarks(
            marks=even_slide_marks(total, n_slides), estimated=False, confidence=0.0,
            reason="자료에서 글자를 찾지 못해 길이를 균등하게 나눴어요.",
        )
    idf = _idf(per_slide)

    # ── 3. 창 분할 ────────────────────────────────────────────────
    n_win = max(n_slides, int(math.ceil(total / WINDOW_SEC)))
    win_sec = total / n_win
    win_tokens: list[list[str]] = [[] for _ in range(n_win)]
    for w in seq:
        i = min(n_win - 1, max(0, int(float(w.get("start_sec") or 0.0) / win_sec)))
        win_tokens[i].extend(_tokens(w.get("text", "")))

    # ── 2·3. 점수: 창 × 슬라이드 ──────────────────────────────────
    score = [[0.0] * n_slides for _ in range(n_win)]
    for i, toks in enumerate(win_tokens):
        if not toks:
            continue
        seen = set(toks)
        norm = math.sqrt(len(seen))
        for s in range(n_slides):
            hit = seen & per_slide[s]
            if hit:
                score[i][s] = sum(idf.get(t, 0.0) for t in hit) / norm

    # ── 4. 단조 정렬 (DP) ─────────────────────────────────────────
    # dp[i][s] = 창 i 를 슬라이드 s 에 두었을 때의 최대 누적 점수.
    # 창 i 는 s 에 머무르거나(dp[i-1][s]) s 보다 앞선 슬라이드에서 넘어온다.
    NEG = float("-inf")
    dp = [[NEG] * n_slides for _ in range(n_win)]
    back = [[0] * n_slides for _ in range(n_win)]
    dp[0][0] = score[0][0]          # 발표는 1장에서 시작한다
    for i in range(1, n_win):
        # 침묵은 전환의 근거가 아니다. 말이 없는 창에서는 앞 슬라이드에 머문다 —
        # 안 그러면 빈 구간에서 점수가 전부 0 이라 아무 데서나 넘어가 버린다.
        silent = not win_tokens[i]
        best_prev, best_s = NEG, 0   # s 미만 구간의 최댓값 (단조 제약)
        for s in range(n_slides):
            stay = dp[i - 1][s]
            move = NEG if silent else best_prev
            if stay >= move:
                dp[i][s], back[i][s] = stay + score[i][s], s
            else:
                dp[i][s], back[i][s] = move + score[i][s], best_s
            if dp[i - 1][s] > best_prev:
                best_prev, best_s = dp[i - 1][s], s

    end_s = max(range(n_slides), key=lambda s: dp[n_win - 1][s])
    path = [0] * n_win
    path[n_win - 1] = end_s
    for i in range(n_win - 1, 0, -1):
        path[i - 1] = back[i][path[i]]

    # ── 5. 신뢰도 ─────────────────────────────────────────────────
    matched = sum(score[i][path[i]] for i in range(n_win))
    ceiling = sum(max(row) for row in score) or 1.0
    covered = sum(1 for row in score if any(row)) / n_win
    confidence = round((matched / ceiling) * covered, 4)

    # ── 6. 아예 다른 내용인가 — 정렬과 무관한 전역 겹침 두 가지 ──────
    # 구간을 못 맞춘 것(아래 가드들)과 다른 파일을 올린 것은 다른 사실이고,
    # 사용자에게 필요한 안내도 다르다. 단정은 두 신호가 모두 낮을 때만 한다.
    speech_vocab = {t for toks in win_tokens for t in toks}
    deck_vocab = set().union(*per_slide)
    hit_vocab = speech_vocab & deck_vocab
    idf_all = sum(idf.get(t, 1.0) for t in speech_vocab) or 1.0
    overlap = sum(idf.get(t, 1.0) for t in hit_vocab) / idf_all
    spoken = [i for i, toks in enumerate(win_tokens) if toks]
    cover = (sum(1 for i in spoken if any(score[i])) / len(spoken)) if spoken else 0.0
    if overlap < UNRELATED_MAX_OVERLAP and cover < UNRELATED_MAX_COVER:
        pct = round(100 * len(hit_vocab) / max(1, len(speech_vocab)))
        return InferredMarks(
            marks=even_slide_marks(total, n_slides), estimated=False,
            confidence=confidence, match="unrelated",
            reason=(
                f"녹음이 이 발표 자료와 아예 다른 내용으로 보여요 — 발화에 나온 "
                f"낱말 중 자료에도 있는 낱말이 {pct}%뿐이에요. 다른 발표의 자료나 "
                f"녹음을 올렸는지 확인해 주세요. 슬라이드 구간은 길이를 균등하게 나눴어요."
            ),
        )

    used = sorted({path[i] for i in range(n_win)})
    if confidence < MIN_CONFIDENCE or len(used) < max(2, n_slides // 2):
        return InferredMarks(
            marks=even_slide_marks(total, n_slides), estimated=False,
            confidence=confidence, match="weak",
            reason="발화와 자료가 잘 맞지 않아 길이를 균등하게 나눴어요.",
        )

    # 경로가 안 들른 장은 아래에서 폭 0 이 된다 — 그 장에는 발화가 한 낱말도
    # 안 붙어 F-11 이 "말한 적 없음" 으로 읽는다. 넷 중 하나 넘게 비면 맞춘 것이
    # 아니라 못 맞춘 것이므로, 점수가 임계를 넘었더라도 추정을 버린다.
    empty_ratio = (n_slides - len(used)) / n_slides
    if empty_ratio > MAX_EMPTY_RATIO:
        return InferredMarks(
            marks=even_slide_marks(total, n_slides), estimated=False,
            confidence=confidence, match="weak",
            reason=(
                f"녹음 내용이 자료와 맞지 않아 슬라이드 구간을 알 수 없어요 "
                f"({n_slides}장 중 {n_slides - len(used)}장에 맞는 발화가 없어요). "
                f"길이를 균등하게 나눴으니 슬라이드별 결과는 참고만 해 주세요."
            ),
        )

    # 경로를 구간으로 접는다
    bounds: list[tuple[int, float, float]] = []
    cur, start = path[0], 0.0
    for i in range(1, n_win):
        if path[i] != cur:
            bounds.append((cur, start, i * win_sec))
            cur, start = path[i], i * win_sec
    bounds.append((cur, start, total))

    by_no = {s: (a, b) for s, a, b in bounds}
    marks: list[SlideMark] = []
    cursor = 0.0
    for s in range(n_slides):
        if s in by_no:
            a, b = by_no[s]
            cursor = b
        else:
            a = b = cursor          # 말하지 않고 지나간 장 — 0초로 남긴다
        marks.append(SlideMark(slide_no=s + 1, start_sec=round(a, 2),
                               end_sec=round(b, 2), visit=1))

    return InferredMarks(
        marks=marks, estimated=True, confidence=confidence, match="matched",
        reason="발화 내용을 자료와 맞춰 슬라이드 구간을 추정했어요.",
    )
