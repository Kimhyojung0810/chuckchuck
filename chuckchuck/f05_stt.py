"""
[F-05] 녹음 음성을 글로 바꾸고, 슬라이드 구간별로 나누는 모듈입니다.
STT(기본 A.X) + 슬라이드 marks 시각을 맞춰 Transcript를 만듭니다.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .contracts import SlideMark, SlideSpeech, STTError, Transcript, Word
from .providers.stt_base import STTProvider
from .providers.stt_impl import get_provider

#: 문장 끝 (09-30 WP-S2 다시 씀). 예전 `[.!?]$|다$|요$|까$|죠$|음$|임$` 는 **끝 글자만** 봐서 문장 한가운데를 끝으로 읽었다 —
#: 혈당 녹음 「…탄수화물을 얼마나 먹었느냐보다 혈당 부하라는 걸로 설명된다는…」 의 「먹었느냐보다」(비교 조사), 「그러니까」(이음),
#: 「다음 장 볼게요」 의 「다음」(명사)이 문장 끝이 되어, 잠금이 풀린 뒷말이 시각대로 다음 장에 붙었다 — 한 문장이 두 장으로
#: 갈렸고, F-11 은 「한 장 구간 안의 이어진 문장」 만 근거로 받으므로(_spoken) 그 문장은 어느 장의 근거도 못 됐다.
#: 규칙은 한국어 문법 낱말로만 짠다 — 특정 발표의 낱말은 없다 (부스에는 처음 보는 녹음이 온다).
#:
#: 1. 문장부호(닫는 따옴표·괄호가 붙어도)는 언제나 끝이다. 쉼표·줄임은 끝이 아니다.
_PUNCT_END_RE = re.compile(r"[.!?。？！][\"'”’」』)\]]*$")
#: 2. 부호 없는 받아쓰기(A.X 는 마침표를 거의 안 찍는다 — 09-30 실측 547낱말 중 8)의 종결 어미 끝 글자.
_ENDING_RE = re.compile(r"(?:다|요|까|죠|음)$")
#: 3. 끝 글자가 종결 어미 같아도 문장이 이어지는 말 — 비교·낱낱·위치 조사(「A보다」「식사마다」「여기에다」), 부사 「다」(「다 같이」),
#:    「요」 로 끝나는 한자어 명사(필요·중요·주요·수요 — `_spoken`·`_evidence` 의 거름과 같은 목록), 「…는데요·…은데요」 이음
#:    (「…계산식인데요, 시간 관계상 넘어갈게요」 는 한 문장이다 — `_spoken._ENDING_WORD_RE` 와 같은 뜻).
_CONTINUES_RE = re.compile(r"(?:^다|보다|마다|에다|(?:필|중|주|수|소|강|개|긴|적)요|[는은인한]데요)$")
#: 「…니까」 는 이음(「그러니까」「있으니까」)이고, 받침 ㅂ 뒤(「습니까」「입니까」「합니까」)만 물음 끝이다.
_NIKKA_RE = re.compile(r"(.)니까$")
#: 「…음」 은 명사(다음·처음·마음·녹음·소음)가 대부분이고, 문장 끝은 받침 ㅆ·ㅄ 뒤의 명사형(「했음」「있음」「없음」)뿐이다.
#: 홀로 선 「음」 은 군말이다 (「음 이건 …」).
_EUM_RE = re.compile(r"(^|.)음$")
#: 「V-다 보면」「V-까 봐」 — 다음 낱말이 이것이면 앞 낱말은 끝이 아니라 이음이다 (「준비하다 보면」「늦을까 봐」).
_JOINED_NEXT_RE = re.compile(r"^(?:보면|보니|보니까|보면은|보면서|보다가|봐|봐서|싶어|싶은|싶다)")
#: 「A일까 B일까가 오늘 주제예요」「늘었을까 줄었을까를 봤어요」 — 다음 낱말도 물음꼴(「…까」「…는지」)이고 조사가 붙었거나 물음으로
#: 끝나면 앞 「…까」 는 문장 끝이 아니라 **안긴 물음**(둘 중 하나를 묻는 명사절)의 앞 반쪽이다 (09-30 녹음 감사 REC-18: 장 경계가
#: 「손해일까 | 이득일까가」 사이로 들어가 한 문장이 두 장으로 갈렸다).
_EMBEDDED_Q_NEXT_RE = re.compile(r"^[가-힣]*(?:까|지)(?:가|를|는|은|도|에|의|로|부터|까지|요)?[.?!]?$")
_JONG_B = 17        # 받침 ㅂ
_JONG_SS = 20       # 받침 ㅆ
_JONG_BS = 18       # 받침 ㅄ

#: 한 문장이 걸칠 수 있는 장 수 — 시작한 장과 그다음 장까지. 끝을 못 읽어(부호도 종결 어미도 없는 말) 잠금이 풀리지 않으면
#: 그 뒤 여러 장의 말이 통째로 앞 장에 붙는다. 다다음 장 구간에 들어선 낱말부터는 잠금을 푼다.
LOCK_MAX_SPAN = 1


def _jong(ch: str) -> int:
    """한글 음절의 받침 번호 (없으면 0, 한글이 아니면 -1)."""
    return (ord(ch) - 0xAC00) % 28 if "가" <= ch <= "힣" else -1


def _sentence_end(text: str, next_text: str = "") -> bool:
    """이 낱말에서 문장이 끝나는가. next_text 는 다음 낱말 — 「V-다 보면」 처럼 뒤를 봐야 가를 수 있는 이음이 있다."""
    t = (text or "").strip()
    if not t:
        return False
    if _PUNCT_END_RE.search(t):
        return True
    if t[-1] in ",·…" or not _ENDING_RE.search(t) or _CONTINUES_RE.search(t):
        return False
    m = _NIKKA_RE.search(t)
    if m:
        return _jong(m.group(1)) == _JONG_B
    m = _EUM_RE.search(t)
    if m:
        return bool(m.group(1)) and _jong(m.group(1)) in (_JONG_SS, _JONG_BS)
    if t.endswith(("다", "까")) and _JOINED_NEXT_RE.match((next_text or "").strip()):
        return False
    if t.endswith("까") and _EMBEDDED_Q_NEXT_RE.match((next_text or "").strip()):
        return False
    return True


def _mark_index(ordered: list[SlideMark], start_sec: float) -> int:
    for i, m in enumerate(ordered):
        if m.start_sec <= start_sec < m.end_sec:
            return i
    return len(ordered) - 1 if start_sec >= ordered[-1].start_sec else 0


def split_by_slide(words: list[Word], marks: list[SlideMark]) -> list[SlideSpeech]:
    """
    단어별 시각과 슬라이드 구간을 대조해 발화를 슬라이드별로 나눈다.

    문장이 시작된 시점의 슬라이드에 문장 전체를 넣는다 — 문장 끝은 `_sentence_end` (조사·이음 어미·명사는 끝이 아니다).
    한 문장은 다음 장까지만 걸친다(LOCK_MAX_SPAN) — 끝을 못 읽어도 여러 장을 삼키지 않는다.
    되돌아가기(재방문)는 visit 로 별도 보존한다.
    """
    if not marks:
        return []

    ordered = sorted(marks, key=lambda m: m.start_sec)
    buckets: list[list[Word]] = [[] for _ in ordered]
    locked_idx: int | None = None

    for k, w in enumerate(words):
        idx = _mark_index(ordered, w.start_sec)
        if locked_idx is not None and idx - locked_idx > LOCK_MAX_SPAN:
            locked_idx = None

        target = locked_idx if locked_idx is not None else idx
        buckets[target].append(w)

        if _sentence_end(w.text, words[k + 1].text if k + 1 < len(words) else ""):
            locked_idx = None
        elif locked_idx is None:
            locked_idx = target

    out: list[SlideSpeech] = []
    for m, bucket in zip(ordered, buckets):
        out.append(SlideSpeech(
            slide_no=m.slide_no,
            visit=m.visit,
            start_sec=m.start_sec,
            end_sec=m.end_sec,
            text=" ".join(w.text for w in bucket),
            words=bucket,
        ))
    return out


def transcribe(
    audio_path: str | Path,
    marks: list[SlideMark] | list[dict],
    *,
    provider: str | STTProvider | None = None,
    provider_kwargs: dict | None = None,
    keywords: list[str] | None = None,
) -> Transcript:
    """
    녹음을 글자로 바꾸고 슬라이드별로 나눈다.

    provider 기본값: STT_PROVIDER 환경변수, 없으면 skt-ax.
    개발 시 provider="mock" 으로 바꾸면 된다.
    """
    if marks and isinstance(marks[0], dict):
        marks = [SlideMark.from_dict(m) for m in marks]  # type: ignore[arg-type]

    if provider is None:
        provider = os.environ.get("STT_PROVIDER", "skt-ax")

    kwargs = dict(provider_kwargs or {})
    if keywords and "keywords" not in kwargs and not isinstance(provider, STTProvider):
        kwargs["keywords"] = keywords

    engine = (
        provider
        if isinstance(provider, STTProvider)
        else get_provider(str(provider), **kwargs)
    )
    engine.check_capability()

    full_text, words = engine.transcribe(audio_path)
    if not words and not full_text:
        raise STTError(f"[{engine.name}] 인식 결과가 비어 있습니다.")

    return Transcript(
        full_text=full_text,
        words=words,
        by_slide=split_by_slide(words, marks),  # type: ignore[arg-type]
        provider=engine.name,
        duration_sec=max((w.end_sec for w in words), default=0.0),
    )


def speech_for_slide(t: Transcript, slide_no: int) -> str:
    """특정 슬라이드에서 한 말 전부 (재방문 포함)."""
    parts = [s.text for s in t.by_slide if s.slide_no == slide_no and s.text.strip()]
    return " ".join(parts)
