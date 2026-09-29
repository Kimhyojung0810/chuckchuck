"""
녹음이 **이 자료의 발표인가** — 발화 낱말과 자료 낱말의 겹침을 재는 공용 유틸. LLM 을 쓰지 않는다.
F-04(업로드 녹음의 슬라이드 구간 추정)와 F-11(정합 판정)이 같은 자로 잰다 (DEV_POLICY §4-1 의 유틸 자리).

2026-08-08 에 f04_infer_marks 안에서 만든 판정을 09-30 에 여기로 옮겼다. held-out 감사 C-07(/temp — 반찬 IR 자료에
집중·알림 녹음, 겹침 3%)에서 F-04 는 「아예 다른 내용」 을 알았는데 **리포트 메모로만** 알렸고, 정합(F-11)·질문(F-08)은 몰랐다.
정합이 스스로 같은 판정을 내리려면 같은 토큰·같은 IDF·같은 창·같은 문턱을 써야 한다 — 문턱이 둘이면 두 화면이 어긋난다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

__all__ = [
    "WINDOW_SEC", "UNRELATED_MAX_OVERLAP", "UNRELATED_MAX_COVER",
    "Overlap", "tokens", "slide_token_sets", "idf", "time_windows", "measure",
]

#: 발화를 자르는 창 길이(초). 짧으면 잡음에 흔들리고 길면 경계가 뭉개진다.
WINDOW_SEC = 6.0

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


def tokens(text: str) -> list[str]:
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


def slide_token_sets(texts: list[str]) -> list[set[str]]:
    """장마다 토큰 집합 (texts[i] = i+1 장의 제목+본문)."""
    return [set(tokens(t)) for t in texts]


def idf(per_slide: list[set[str]]) -> dict[str, float]:
    """모든 슬라이드에 나오는 말은 슬라이드를 못 가린다 → 가중치를 낮춘다."""
    n = max(1, len(per_slide))
    df: dict[str, int] = {}
    for toks in per_slide:
        for t in toks:
            df[t] = df.get(t, 0) + 1
    return {t: math.log(1.0 + n / c) for t, c in df.items()}


def time_windows(words: list[dict], total: float, n_slides: int) -> list[list[str]]:
    """낱말(시각 있는 dict)을 WINDOW_SEC 창으로 — 창마다 내용어 토큰. 창 수는 장 수 이상."""
    n_win = max(n_slides, int(math.ceil(total / WINDOW_SEC))) if total > 0 else max(1, n_slides)
    win_sec = (total / n_win) if total > 0 else 1.0
    out: list[list[str]] = [[] for _ in range(n_win)]
    for w in words:
        i = min(n_win - 1, max(0, int(float(w.get("start_sec") or 0.0) / win_sec)))
        out[i].extend(tokens(w.get("text", "")))
    return out


@dataclass(frozen=True)
class Overlap:
    """발화 ↔ 자료 겹침. overlap·cover 둘 다 문턱 아래면 다른 발표다."""

    overlap: float        # IDF 가중 — 발화 어휘 중 자료에도 있는 비중
    cover: float          # 발화가 있는 창 중 자료 낱말이 하나라도 든 비율
    hit_pct: int          # 사람이 읽는 수 — 발화 낱말 중 자료에도 있는 낱말 %
    spoken_windows: int   # 발화가 있는 창 수 (0 이면 잴 게 없다)

    @property
    def unrelated(self) -> bool:
        return (self.spoken_windows > 0 and self.overlap < UNRELATED_MAX_OVERLAP
                and self.cover < UNRELATED_MAX_COVER)


def measure(per_slide: list[set[str]], windows: list[list[str]], weights: dict[str, float] | None = None) -> Overlap:
    """장별 토큰과 발화 창으로 겹침·커버를 잰다 (F-04 6단계와 같은 식)."""
    w = weights if weights is not None else idf(per_slide)
    speech_vocab = {t for toks in windows for t in toks}
    deck_vocab: set[str] = set().union(*per_slide) if per_slide else set()
    hit_vocab = speech_vocab & deck_vocab
    idf_all = sum(w.get(t, 1.0) for t in speech_vocab) or 1.0
    overlap = sum(w.get(t, 1.0) for t in hit_vocab) / idf_all
    spoken = [toks for toks in windows if toks]
    cover = (sum(1 for toks in spoken if set(toks) & deck_vocab) / len(spoken)) if spoken else 0.0
    pct = round(100 * len(hit_vocab) / max(1, len(speech_vocab)))
    return Overlap(round(overlap, 4), round(cover, 4), pct, len(spoken))
