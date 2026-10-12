"""
개념 label 을 텍스트와 대조하는 토큰 매칭 공용 헬퍼입니다.
기능 모듈(fXX_*)이 아니라 유틸이라, 어느 모듈에서 import 해도 정책 위반이 아닙니다.

F-07(문서 개념·키워드 언급 대조)에서 만들었고, F-11(발화 언급 대조)이 같이 씁니다.
규칙: 영문·숫자 토큰은 정확 일치, 한글 토큰은 합성어 포함을 허용합니다.
"""

from __future__ import annotations

import re
import unicodedata

#: 이보다 짧은 label 은 언급 대조를 하지 않는다 (한 글자는 우연히 다 걸린다).
MIN_MATCH_LEN = 2

#: 영문·숫자 run 과 한글 run 을 토큰으로 자른다. 그 밖의 문자는 경계다.
_TOKEN_RE = re.compile(r"[a-z0-9]+|[가-힣]+")
_HANGUL_RE = re.compile(r"^[가-힣]+$")

#: 전각 영숫자·기호(「ＡＩ」「８.７」「％」)와 전각 공백을 반각으로 — NFKC 의 이 부분만 쓴다. 「…」「①」「cm²」 같은 호환 문자는
#: 그대로 둬서 글자 수·문장 부호가 거의 바뀌지 않는다(숫자 위치를 원문 기준으로 쓰는 `_deck_claims.numbers` 가 이 글을 받는다).
_WIDTH_FOLD = {0xFF01 + i: 0x21 + i for i in range(94)} | {0x3000: 0x20}


def fold_text(value) -> str:
    """
    대조 전에 글을 한 모양으로 — NFC(풀어 쓴 한글 자모를 음절로) + 전각 영숫자를 반각으로.

    09-30 레드팀 G-A11: 맥에서 만든 파일의 라벨이 NFD(「ᄉ+ᅮ+ᄆ+ᅧ+ᆫ」)로 오면 토큰이 0개라, 그 라벨을 쓰는 가드가 **조용히
    꺼졌다**(낱말이 하나도 안 겹치니 「판단 근거 없음」). 부스에서는 어떤 기기에서 만든 자료가 올지 모른다.
    """
    return unicodedata.normalize("NFC", str(value or "")).translate(_WIDTH_FOLD)


def norm_tokens(value: str) -> list[str]:
    """대조용 토큰열. 'AI 기반추천' → ['ai', '기반추천']. NFD 한글·전각 영숫자도 같은 토큰이 된다 (NFKC)."""
    return _TOKEN_RE.findall(unicodedata.normalize("NFKC", str(value or "")).lower())


def _token_eq(outer_tok: str, inner_tok: str) -> bool:
    """
    토큰 하나의 일치 판정.

    영문·숫자는 통째로 같아야 한다 — 'ai' 가 'detail' 안에서 걸리면 오탐이다.
    한글은 합성어를 붙여 쓰므로('피보팅근거') 포함이면 같은 개념으로 본다.
    """
    if outer_tok == inner_tok:
        return True
    return bool(
        _HANGUL_RE.match(inner_tok)
        and _HANGUL_RE.match(outer_tok)
        and inner_tok in outer_tok
    )


def contains_tokens(outer: list[str], inner: list[str]) -> bool:
    """inner 토큰열이 outer 토큰열의 연속 부분열로 나타나는가."""
    n = len(inner)
    if n == 0 or n > len(outer):
        return False
    return any(
        all(_token_eq(outer[i + j], inner[j]) for j in range(n))
        for i in range(len(outer) - n + 1)
    )


def label_tokens(label: str) -> list[str]:
    """언급 대조에 쓸 label 토큰열. 너무 짧으면 우연히 다 걸리므로 버린다."""
    tokens = norm_tokens(label)
    return tokens if sum(len(t) for t in tokens) >= MIN_MATCH_LEN else []


def first_match_index(outer: list[str], inner: list[str]) -> int | None:
    """inner 토큰열이 처음 나타나는 outer 인덱스. 없으면 None."""
    n = len(inner)
    if n == 0 or n > len(outer):
        return None
    for i in range(len(outer) - n + 1):
        if all(_token_eq(outer[i + j], inner[j]) for j in range(n)):
            return i
    return None


def count_occurrences(label: str, outer: list[str]) -> int:
    """
    label 토큰열이 outer 토큰열 안에 몇 번 나타나는가 (겹침 없이 센다).

    F-07 의 목록 단위 대조와 달리, 발화처럼 긴 토큰열 하나에서 횟수를 셀 때 쓴다.
    """
    inner = label_tokens(label)
    n = len(inner)
    if n == 0 or n > len(outer):
        return 0
    count = 0
    i = 0
    while i <= len(outer) - n:
        if all(_token_eq(outer[i + j], inner[j]) for j in range(n)):
            count += 1
            i += n
        else:
            i += 1
    return count
