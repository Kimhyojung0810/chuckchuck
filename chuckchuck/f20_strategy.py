"""
[F-20] 이 발표를 어떤 구성으로 다시 짜면 좋을지 제안하는 모듈입니다.

분석 결과(개념 트리 · 개념별 판정 · 슬라이드별 사용 시간 · 실제 발화)를 LLM 에
넘겨, 널리 알려진 발표 구성 중 이 발표에 가장 잘 맞는 하나를 고르고 실제
슬라이드 번호와 시간으로 된 재배치 계획을 받는다.

핵심 축은 '핵심을 어디에 두는가' 다.
  early       — 결론을 먼저 던지고 나머지를 근거로 돌린다
  late        — 쌓아 올리다 마지막 한 방으로 남긴다
  throughline — 주장 하나를 세우고 전부 거기에 종속시킨다

주의: 유형 이름에 실존 인물을 쓰지만, 그 사람이 한 말을 만들어내지 않는다.
인물은 구성 방식을 가리키는 수식어일 뿐이고, 생성되는 문장은 언제나
"당신의 발표를 이렇게 바꾸면" 이지 "그 사람이 이렇게 말한다" 가 아니다.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .contracts import StrategyError
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm

#: 입력이 길면 LLM JSON 이 잘린다. F-06 과 같은 이유로 상한을 둔다.
MAX_CONCEPT_CHARS = int(os.environ.get("CHUCKCHUCK_STRATEGY_MAX_CONCEPT_CHARS", "1200"))
MAX_QUOTE_CHARS = int(os.environ.get("CHUCKCHUCK_STRATEGY_MAX_QUOTE_CHARS", "900"))
MAX_SLIDE_CHARS = int(os.environ.get("CHUCKCHUCK_STRATEGY_MAX_SLIDE_CHARS", "1600"))
#: 구성표를 통째로 받아야 해서 F-06 보다 넉넉하다. 잘리면 복구 경로가 받는다.
MAX_TOKENS = int(os.environ.get("CHUCKCHUCK_STRATEGY_MAX_TOKENS", "3500"))

#: 구간 블록 개수 상한. 넘으면 순서표가 아니라 슬라이드 목록이 된다.
MAX_BLOCKS = 8

#: 제안 가능한 구성. LLM 은 이 중에서만 고른다.
STRATEGY_TYPES: dict[str, dict[str, str]] = {
    "잡스식 축 고정형": {
        "climax": "throughline",
        # principle 의 낱말이 그대로 화면 문장에 번진다. '종속'·'최적화' 같은
        # 한자어를 여기 두면 모델이 사용자에게도 그 말로 말한다 (2026-08-07).
        "principle": "주장 한 문장을 세우고 나머지 장이 전부 그 주장을 받치게 한다. "
                     "중심 주장에 가장 많은 시간을 준다.",
        "reads": "개념 트리 중요도, 중심 주장의 판정과 사용 시간",
    },
    "베이조스식 결론 선행형": {
        "climax": "early",
        "principle": "결론과 그것이 청중에게 무엇을 뜻하는지를 먼저 말하고, "
                     "근거를 뒤에 붙인다. 앞부분 배경 설명을 과감히 줄인다.",
        "reads": "도입 구간 시간 비중, 결론 위치",
    },
    "머스크식 전제 축적형": {
        "climax": "late",
        "principle": "누구나 동의할 전제와 수치부터 쌓아 결론이 따라 나오게 만든다. "
                     "빠진 수치를 복원하는 것이 핵심이다.",
        "reads": "누락 판정 개념, 논리 끊김 지점",
    },
    "저커버그식 사용자 서사형": {
        "climax": "late",
        "principle": "한 사람의 구체적인 장면에서 출발해 일반화하고, "
                     "마지막에 그 장면을 다시 불러 마무리한다.",
        "reads": "도입·결론 구간, 구간별 말 속도",
    },
}

SYSTEM_PROMPT = """당신은 발표 구성 코치다.
분석된 발표 데이터를 보고 ① 이 발표에 가장 잘 맞는 구성 유형 하나를 고르고
② 그 유형대로 발표를 다시 짠 구간 순서표를 만든다.

핵심은 순서표다. "어디에 시간을 많이 썼다" 는 진단으로 끝나면 쓸모가 없다.
발표자가 이 표를 보고 그대로 발표 순서를 고칠 수 있어야 한다.

순서표 규칙:
- 구간은 4~7개로 묶는다. 슬라이드를 한 장씩 나열하지 않는다.
- 각 구간의 slides 에는 그 구간에 들어갈 슬라이드 번호를 넣는다.
  반드시 아래 슬라이드 목록에 있는 번호만 쓴다. 없는 번호를 지어내지 않는다.
- 지금 자료에 없어서 새로 만들어야 하는 구간은 slides 를 빈 배열로 두고 new 를 true 로 한다.
- from/to 는 전체 길이 안에서 이어지게 배분한다. 앞 구간의 to 가 다음 구간의 from 이다.
- what 은 그 구간에서 무엇을 하는지 한 문장. add 는 거기에 새로 넣을 내용 한 문장.
  더할 게 없는 구간은 add 를 빈 문자열로 둔다. 모든 구간에 억지로 채우지 않는다.
- what 과 add 에는 괄호 숫자를 넣지 않는다. 장 번호는 slides 가, 시간은 from/to 가 이미 말한다.
  (X) 동기(3:12)와 구조(3:56)를 축으로 세우고 데이터셋(14, 16)을 붙여요
  (O) 동기와 구조를 축으로 세우고 데이터셋을 그 증거로 붙여요
  장 번호를 꼭 짚어야 할 때만 "지금 20번에 있는 내용을 여기로" 처럼 문장 안에 풀어 쓴다.

반드시 지킬 것:
- 유형 이름에 사람 이름이 들어가지만, 그 사람이 한 말이나 할 말을 절대 지어내지 않는다.
  이름은 구성 방식을 가리키는 수식어일 뿐이다.
- 모든 문장은 "당신의 발표를 이렇게 바꾸면" 관점으로 쓴다.
- type 에는 큰따옴표 안의 이름만 그대로 넣는다. 괄호 설명이나 수식을 덧붙이지 않는다.
- 실제 발화가 하나라도 주어졌으면 그 중 가장 강한 문장 하나를 골라 keep 에 반드시 넣는다.
  글자 하나 바꾸지 말고 그대로 옮긴다. 발화가 아예 없을 때만 keep 을 생략한다.
- 고른 이유(why)는 이 발표의 구체적인 수치를 근거로 한두 문장으로 쓴다.
- gains 에는 이 순서로 바꾸면 무엇이 좋아지는지 2~3개를 쓴다. claim 은 좋아지는 것
  한 문장, evidence 는 그 근거다. evidence 에는 위 입력에 실제로 있는 시각·수치·개념
  이름을 그대로 짚는다. 입력에 없는 근거를 지어내지 않는다. 근거를 못 대면 그 항목을
  만들지 않는다.
- 아래 예시의 문장을 그대로 가져다 쓰지 않는다. 이 발표의 개념 이름과 수치로 새로 쓴다.
말투 (발표자가 읽는 문장이다. 코치의 메모가 아니다):
- 모든 문장을 해요체로 끝낸다. '한다' '이다' '있다' 로 끝내지 않는다.
  (X) 축을 고정하는 방식과 일치한다  →  (O) 축을 하나로 잡으면 훨씬 선명해져요
- 소리 내어 읽었을 때 자연스러운 쉬운 말을 쓴다. 한자어 명사를 붙여 쓰지 않는다.
  (X) 시간 배분을 최적화할 수 있어요  →  (O) 시간을 더 알맞게 나눌 수 있어요
  (X) 나머지 내용을 종속시키면  →  (O) 나머지가 그 주장을 받치게 하면
  (X) 인지 비용 증가로 이어져요  →  (O) 머리가 더 힘들어져요
- 한 문장에는 하나만 담는다. 두 가지를 말해야 하면 문장을 나눈다.
- '~시', '~시겠어요', '해 주시길' 같은 높임을 쓰지 않는다. '해 주세요' 까지만 쓴다.
- 빼도 뜻이 같은 낱말은 넣지 않는다 ('앞으로', '보다 더', '적극적으로').

JSON 만 출력한다. 아래는 전혀 다른 발표(물류 비용 보고)의 예시로, 짜임새와 말투만 본보기다:
{
  "chosen": {
    "type": "잡스식 축 고정형",
    "why": "S07 창고 이야기에 4:10 을 써서 권장 1:30 의 세 배를 넘겼어요.",
    "outline": [
      {"role": "한 문장 선언", "from": "0:00", "to": "0:40", "slides": [], "new": true,
       "what": "물류비를 30% 줄인다는 결론을 먼저 못박아요.",
       "add": "지금 마지막 장에 있는 절감액을 여기로 끌어와 주세요."},
      {"role": "현황", "from": "0:40", "to": "2:10", "slides": [1, 2, 3],
       "what": "창고 이야기를 절반으로 줄이고 비용 구조만 남겨요.",
       "add": ""},
      {"role": "해법", "from": "2:10", "to": "5:00", "slides": [7, 8, 9],
       "what": "적재 알고리즘을 축으로 세우고 나머지를 그 증거로 붙여요.",
       "add": "적재율 개선 수치를 한 줄 넣어 주세요."}
    ],
    "keep": {"quote": "<입력에 있는 발화 그대로>", "at": "04:33"},
    "gains": [
      {"claim": "절감액 결론을 시작 40초 안에 듣게 돼요.",
       "evidence": "지금은 마지막 장에서 4:50 에 처음 나와요."},
      {"claim": "창고 이야기가 절반으로 줄어요.",
       "evidence": "S07 창고 이야기에 4:10 을 써서 권장 1:30 의 세 배를 넘겼어요."}
    ]
  },
  "alternatives": [
    {"type": "베이조스식 결론 선행형", "one_line": "결론을 먼저 말하고 근거를 뒤로 미뤄요."}
  ]
}"""


def _repair_json_text(text: str) -> str:
    """잘린/느슨한 JSON 을 최대한 복구. F-06 과 같은 실패 모드를 다룬다."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    text = re.sub(r",\s*([}\]])", r"\1", text)

    start = text.find("{")
    if start > 0:
        text = text[start:]

    # 응답이 중간에 끊겼으면 마지막으로 완전히 닫힌 객체까지만 남긴다.
    # 이 단계를 건너뛰고 괄호만 세어 붙이면 닫는 순서가 뒤집혀 더 깨진다.
    if text.count("{") > text.count("}"):
        last_complete = text.rfind("}")
        if last_complete > 0:
            chunk = text[: last_complete + 1]
            if chunk.count("[") > chunk.count("]"):
                chunk += "]" * (chunk.count("[") - chunk.count("]"))
            if chunk.count("{") > chunk.count("}"):
                chunk += "}" * (chunk.count("{") - chunk.count("}"))
            text = chunk

    if text.count("[") > text.count("]"):
        text += "]" * (text.count("[") - text.count("]"))
    if text.count("{") > text.count("}"):
        text += "}" * (text.count("{") - text.count("}"))

    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def _extract_json(text: str) -> dict[str, Any]:
    candidates = [text.strip()]
    repaired = _repair_json_text(text)
    if repaired != candidates[0]:
        candidates.append(repaired)
    m = re.search(r"\{.*\}", repaired, flags=re.S)
    if m:
        candidates.append(m.group(0))

    last_err: Exception | None = None
    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError as e:
            last_err = e
            continue

    raise StrategyError(
        f"LLM 응답 JSON 파싱 실패: {last_err}. preview={text[:400]!r}"
    )


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _build_user_prompt(analysis: dict) -> str:
    # 이름을 따옴표로 감싸고 메타데이터를 뒤로 뺀다. 한 줄에 붙여 놓으면
    # 모델이 "(핵심 위치: throughline)" 까지 이름의 일부로 옮겨 적는다.
    types_desc = "\n".join(
        f'- "{name}"\n    {meta["principle"]}\n'
        f'    (핵심 위치 {meta["climax"]} · 볼 지표 {meta["reads"]})'
        for name, meta in STRATEGY_TYPES.items()
    )
    concepts = _clip(
        "\n".join(
            f"  {c.get('label', '')} · {c.get('slide', '')} · 판정 {c.get('verdict', '')}"
            for c in (analysis.get("concepts") or [])
        ),
        MAX_CONCEPT_CHARS,
    )
    times = "\n".join(
        f"  {t.get('slide', '')} {t.get('label', '')} · 권장 {t.get('recommended', '?')} "
        f"· 실제 {t.get('actual', '?')}"
        for t in (analysis.get("time_alloc") or [])
    )
    quotes = _clip(
        "\n".join(
            f"  [{q.get('at', '')}] {q.get('text', '')}"
            for q in (analysis.get("quotes") or [])
        ),
        MAX_QUOTE_CHARS,
    )
    slides = _clip(
        "\n".join(
            f"  {s.get('no')}번 {s.get('title', '')}"
            + (f" (실제 {s['spent']})" if s.get("spent") else "")
            for s in (analysis.get("slides") or [])
            if s.get("no") is not None
        ),
        MAX_SLIDE_CHARS,
    )
    # [TASK] 머리표는 MockLLM 이 어떤 가짜 응답을 낼지 고르는 표식이다.
    return f"""[TASK] presentation-strategy

고를 수 있는 구성 유형:
{types_desc}

발표 정보
  주제: {analysis.get('title', '(제목 없음)')}
  맥락: {analysis.get('occasion', '범용')}
  전체 길이: {analysis.get('duration', '?')}

슬라이드 목록 (outline 의 slides 에는 이 번호만 쓴다)
{slides or '  (없음)'}

개념별 판정
{concepts or '  (없음)'}

구간별 시간
{times or '  (없음)'}

실제 발화 (keep.quote 는 반드시 이 안에서 고른다)
{quotes or '  (없음)'}

가장 잘 맞는 유형 하나를 고르고, 그 유형대로 다시 짠 구간 순서표(outline)를 4~7개로 만들어줘.
왜 바꿔야 하는지(gains)도 2~3개 써줘 — 근거(evidence)는 위 입력의 실제 시각·수치·개념에서만 가져와.
나머지 유형 중 둘은 alternatives 로 한 줄씩만 설명해줘."""


def _canonical_type(raw: Any) -> str | None:
    """
    LLM 이 옮겨 적은 유형 이름을 정본으로 되돌린다.

    실제로 관측된 실패는 지어내기가 아니라 '너무 성실한 복사' 였다 —
    프롬프트의 "잡스식 축 고정형 (핵심 위치: throughline)" 을 통째로 type 에 넣었다.
    유형 이름끼리는 서로의 부분 문자열이 아니라 포함 검사가 안전하다.
    """
    name = str(raw or "").strip().strip('"').strip("'")
    if name in STRATEGY_TYPES:
        return name
    for known in STRATEGY_TYPES:
        if known in name:
            return known
    squashed = re.sub(r"\s+", "", name)
    for known in STRATEGY_TYPES:
        if squashed and re.sub(r"\s+", "", known) == squashed:
            return known
    return None


def _known_slide_nos(analysis: dict) -> set[int]:
    """입력에 실제로 있는 슬라이드 번호. outline 이 여기 밖을 가리키면 지운다."""
    nos: set[int] = set()
    for s in analysis.get("slides") or []:
        try:
            nos.add(int(s.get("no")))
        except (TypeError, ValueError):
            continue
    return nos


def _clean_outline(raw: Any, analysis: dict) -> list[dict]:
    """
    구간 순서표를 다듬는다.

    지어낸 슬라이드 번호를 지우는 게 핵심이다 — 발표자는 이 표를 그대로 따라
    자료를 고칠 텐데, 없는 장 번호가 섞이면 그 순간 신뢰가 끝난다.
    번호를 다 잃은 구간은 지우지 않고 '신설' 로 돌린다. 구간의 취지는 남기고
    출처만 못 밝히는 상태가 사실에 가깝다.
    """
    if not isinstance(raw, list):
        return []
    known = _known_slide_nos(analysis)

    def _tidy(text: Any) -> str:
        """
        괄호 숫자를 지운다 — "동기(3:12)와 구조(3:56)" 처럼 시각과 장 번호가
        섞여 들어오면, 오른쪽 슬라이드 배지와 중복되면서 어느 쪽인지도 흐려진다.
        숫자·시각·쉼표로만 이뤄진 괄호만 지우므로 "(1D conv)" 같은 건 남는다.
        """
        s = re.sub(r"\s*[(（](?:\s*\d+(?::\d+)?\s*[,，·~-]?\s*)+[)）]", "", str(text or ""))
        return re.sub(r"\s{2,}", " ", s).strip()

    blocks: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = _tidy(item.get("role"))
        what = _tidy(item.get("what"))
        if not role or not what:
            continue

        # 문자열도 순회가 되므로 리스트인지 먼저 본다 — "2번" 이 [2] 로 둔갑한다
        raw_slides = item.get("slides")
        slides: list[int] = []
        for n in raw_slides if isinstance(raw_slides, list) else []:
            try:
                n = int(n)
            except (TypeError, ValueError):
                continue
            # 슬라이드 목록을 안 받았으면 검사할 근거가 없으니 통과시킨다
            if (not known or n in known) and n not in slides:
                slides.append(n)

        blocks.append({
            "role": role,
            "what": what,
            "slides": slides,
            "new": bool(item.get("new")) or not slides,
            "from": str(item.get("from") or "").strip(),
            "to": str(item.get("to") or "").strip(),
            "add": _tidy(item.get("add")),
        })
        if len(blocks) == MAX_BLOCKS:
            break
    return blocks


#: 근거 불릿 상한. 셋이면 설득되고, 넘치면 나열이 된다.
MAX_GAINS = 3


def _times_of(text: str) -> set[tuple[int, int]]:
    """'4:10' 과 '04:10' 을 같은 시각으로 본다."""
    return {(int(m.group(1)), int(m.group(2)))
            for m in re.finditer(r"(\d+):(\d{2})", str(text or ""))}


def _clean_gains(raw: Any, analysis: dict) -> list[dict]:
    """
    '왜 바꿔야 하는가' 근거를 다듬는다.

    keep.quote 와 같은 규율이다 — evidence 가 입력의 실제 값(개념·구간 이름,
    슬라이드 제목, 시각)을 하나도 짚지 못하면 그 항목을 버린다. 근거 없는
    좋은 말은 피드백이 아니라 덕담이고, 덕담은 신뢰를 깎는다.
    """
    if not isinstance(raw, list):
        return []

    names = (
        [str(c.get("label") or "") for c in (analysis.get("concepts") or [])]
        + [str(t.get("label") or "") for t in (analysis.get("time_alloc") or [])]
        + [str(s.get("title") or "") for s in (analysis.get("slides") or [])]
    )
    names = [re.sub(r"\s+", "", n) for n in names]
    names = [n for n in names if len(n) >= 2]

    time_parts = [str(analysis.get("duration") or "")]
    for t in analysis.get("time_alloc") or []:
        time_parts += [str(t.get("recommended") or ""), str(t.get("actual") or "")]
    for s in analysis.get("slides") or []:
        time_parts.append(str(s.get("spent") or ""))
    for q in analysis.get("quotes") or []:
        time_parts.append(str(q.get("at") or ""))
    known_times = _times_of(" ".join(time_parts))

    cleaned: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        if not claim or not evidence:
            continue
        squashed = re.sub(r"\s+", "", evidence)
        grounded = (
            any(n in squashed for n in names)
            or bool(_times_of(evidence) & known_times)
        )
        if not grounded:
            continue
        cleaned.append({"claim": claim, "evidence": evidence})
        if len(cleaned) == MAX_GAINS:
            break
    return cleaned


def _validate(data: dict, analysis: dict) -> dict:
    """LLM 이 지어낸 값을 걸러낸다. 환각은 여기서 죽인다."""
    chosen = data.get("chosen")
    if not isinstance(chosen, dict):
        raise StrategyError(f"chosen 이 없습니다: {type(chosen)}")

    name = _canonical_type(chosen.get("type"))
    if name is None:
        raise StrategyError(f"알 수 없는 유형입니다: {chosen.get('type')!r}")
    chosen["type"] = name
    chosen["climax"] = STRATEGY_TYPES[name]["climax"]

    # keep.quote 가 실제 발화에 없으면 통째로 버린다
    keep = chosen.get("keep")
    if isinstance(keep, dict) and keep.get("quote"):
        said = "".join((q.get("text") or "") for q in (analysis.get("quotes") or []))
        needle = re.sub(r"\s+", "", keep["quote"])[:20]
        if not needle or needle not in re.sub(r"\s+", "", said):
            chosen.pop("keep", None)

    chosen["outline"] = _clean_outline(chosen.get("outline"), analysis)
    if not chosen["outline"]:
        raise StrategyError("구간 순서표(outline)가 없습니다.")
    chosen["gains"] = _clean_gains(chosen.get("gains"), analysis)
    chosen.pop("moves", None)   # 구버전 키가 섞여 와도 화면으로 새지 않게 한다

    kept: list[dict] = []
    for alt in data.get("alternatives") or []:
        if not isinstance(alt, dict):
            continue
        alt_name = _canonical_type(alt.get("type"))
        if alt_name is None or alt_name == name:
            continue
        kept.append({**alt, "type": alt_name})
        if len(kept) == 2:
            break
    data["alternatives"] = kept

    data["chosen"] = chosen
    return data


def suggest_strategy(
    analysis: dict,
    *,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
) -> dict:
    """
    분석 결과 → 발표 구성 제안.

    analysis 는 다음을 담는다(전부 선택):
      title, occasion, duration,
      concepts   [{label, slide, verdict}]
      time_alloc [{slide, label, recommended, actual}]
      quotes     [{at, text}]

    반환: {"chosen": {...}, "alternatives": [...]}
    """
    if not isinstance(analysis, dict) or not analysis:
        raise StrategyError("분석 결과가 비어 있어 구성을 제안할 수 없습니다.")

    engine = llm if isinstance(llm, LLMProvider) else get_llm(llm, **(llm_kwargs or {}))
    raw = engine.complete(
        system=SYSTEM_PROMPT,
        user=_build_user_prompt(analysis),
        temperature=0.3,
        max_tokens=MAX_TOKENS,
    )
    return _validate(_extract_json(raw), analysis)
