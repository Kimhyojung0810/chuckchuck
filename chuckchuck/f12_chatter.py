"""
[삐약 청중석] 국내 LLM 4개가 병아리 청중을 연기하며 발표에 대해 떠드는 모듈입니다.
ConceptGraph + AlignmentDoc + FlowDiff → ChatterDoc.

    from chuckchuck.f12_chatter import build_chatter
    chatter = build_chatter(graph, alignment, flow)

설계 두 줄:

1. **성격은 분장이 아니라 실제 역할이다.** 각 병아리의 담당 데이터는 그 모델이
   파이프라인에서 실제로 한 일에서 나온다 — solar 는 자료를 읽었으니(F-01/F-06/F-07)
   구조·순서를 보고, ax 는 발표를 들었으니(F-05 STT) 발화 축을 본다.
2. **코드가 사실을 고르고 LLM 은 말투만 입힌다.** 어떤 노드를 언급할지는
   pick_talking_points() 가 결정적으로 정한다. LLM 에는 그 사실 목록만 주고,
   목록 밖 node_id 를 가리키는 대사는 어댑터가 버린다 (F-11 과 같은 철학).
   그래서 수다가 리포트·Q&A 와 따로 놀 수 없다.
"""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from ._json_text import extract_json_object
from .contracts import (
    CHATTER_BADGES,
    CHATTER_MOODS,
    CHATTER_NAMES,
    CHATTER_SPEAKERS,
    AlignmentDoc,
    ChatterDoc,
    ChatterError,
    ChatterRef,
    ChatterTurn,
    ConceptGraph,
    ConceptNode,
    FlowDiff,
)
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm

#: 병아리 한 마리가 한 라운드에 받아 가는 사실의 최대 개수.
MAX_POINTS = 3

#: 전체 턴 수 상한. 4명 × 2라운드 × 2턴이 딱 여기 맞는다.
MAX_TURNS = 16

#: 근거 없는 스몰토크가 차지할 수 있는 최대 비율.
SMALLTALK_RATIO = 0.2

#: 한 턴의 최대 글자 수. 넘으면 버린다 (귀여운 수다는 짧다).
MAX_TEXT_LEN = 200

#: 자료가 힘줬는데 발화가 안 따라온 개념의 기준. 믿:음의 툴툴거림 소재.
GAP_THRESHOLD = 0.4


# ---------------------------------------------------------------------------
# 말할 거리 — 코드가 결정적으로 고른다
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TalkingPoint:
    """병아리 한 마리에게 배정된 사실 하나. fact 는 코드가 조립한 한국어 문장."""
    fact: str
    source: str                              # alignment | flow | graph
    node_ids: tuple[str, ...] = ()           # 이 사실이 걸린 노드 (없을 수 있다)


def _labels(graph: ConceptGraph) -> dict[str, str]:
    return {n.id: n.label for n in graph.nodes}


def _weight_word(weight: float) -> str:
    """자료 비중을 말로 옮긴다.

    사실 문자열에 0.8 같은 원시 수치를 넣으면 병아리가 그걸 그대로 읊는다.
    점수처럼 들리는 숫자는 객석에서 말하지 않기로 했고(TONE_GUIDE), 애초에
    "자료 중요도 0.8" 은 발표자에게 아무 의미가 없다. 서열은 정렬이 이미 했으니
    여기서는 사람이 말할 수 있는 말로만 남긴다.
    """
    if weight >= 0.7:
        return "자료가 크게 힘준"
    if weight >= 0.4:
        return "자료가 한 자리 내준"
    return "자료가 가볍게 스친"


def _slide_hint(node: ConceptNode | None) -> str:
    if node is None or not node.slide_nos:
        return ""
    return f"(슬라이드 {min(node.slide_nos)})"


def _midm_points(graph: ConceptGraph, alignment: AlignmentDoc) -> list[TalkingPoint]:
    """
    믿:음 = 신뢰. 자료와 발화가 어긋난 곳을 그냥 못 지나간다.

    누락·모순을 자료 중요도 순으로, 그다음 '자료는 힘줬는데 발화가 안 따라온' 개념.
    """
    by_id = {n.id: n for n in graph.nodes}
    out: list[TalkingPoint] = []

    broken = [i for i in alignment.items if i.verdict in ("missing", "contradiction")]
    broken.sort(key=lambda i: (-i.doc_weight, i.node_id))
    for item in broken:
        node = by_id.get(item.node_id)
        label = node.label if node else item.node_id
        if item.verdict == "missing":
            fact = (
                f"'{label}' {_slide_hint(node)}은(는) {_weight_word(item.doc_weight)} "
                "개념인데 발표에서 한 번도 다루지 않았다"
            )
        else:
            quote = f' 발표자는 "{item.evidence}"라고 말했다' if item.evidence else ""
            fact = f"'{label}' {_slide_hint(node)}은(는) 자료와 어긋나게 설명됐다.{quote}"
        out.append(TalkingPoint(fact=" ".join(fact.split()), source="alignment",
                                node_ids=(item.node_id,)))

    gaps = [
        i for i in alignment.items
        if i.verdict not in ("missing", "contradiction")
        and i.doc_weight - i.speech_weight > GAP_THRESHOLD
    ]
    gaps.sort(key=lambda i: (-(i.doc_weight - i.speech_weight), i.node_id))
    for item in gaps:
        node = by_id.get(item.node_id)
        label = node.label if node else item.node_id
        fact = (
            f"'{label}' {_slide_hint(node)}은(는) {_weight_word(item.doc_weight)} "
            "개념인데 발표에서는 스치듯 지나갔다"
        )
        out.append(TalkingPoint(fact=" ".join(fact.split()), source="alignment",
                                node_ids=(item.node_id,)))
    return out[:MAX_POINTS]


def _solar_points(graph: ConceptGraph, flow: FlowDiff) -> list[TalkingPoint]:
    """
    Upstage Solar = 자료를 처음부터 끝까지 읽은 유일한 청중 (F-01 파싱, F-06/07 추출).
    그래서 구조와 순서를 본다.
    """
    labels = _labels(graph)
    out: list[TalkingPoint] = []

    for kind in ("order_jump", "missing_link"):
        for issue in flow.issues_of(kind):
            names = " / ".join(labels.get(n, n) for n in issue.node_ids)
            out.append(TalkingPoint(
                fact=f"{issue.note} (해당 개념: {names})",
                source="flow",
                node_ids=tuple(issue.node_ids),
            ))

    if flow.order_tau is not None and len(out) < MAX_POINTS:
        agree = round((flow.order_tau + 1) / 2 * 100)
        out.append(TalkingPoint(
            fact=f"자료 순서와 발표 순서의 일치도가 {agree}% 였다",
            source="flow",
        ))
    return out[:MAX_POINTS]


def _exaone_points(
    graph: ConceptGraph, alignment: AlignmentDoc, flow: FlowDiff
) -> list[TalkingPoint]:
    """
    LG EXAONE = 'EXpert AI for everyONE'. 전문가 포지션이라 칭찬을 맡는다 —
    전문가가 인정해 주면 더 뿌듯하다.
    """
    by_id = {n.id: n for n in graph.nodes}
    labels = _labels(graph)
    out: list[TalkingPoint] = []

    good = [i for i in alignment.items if i.verdict == "aligned"]
    good.sort(key=lambda i: (-i.doc_weight, i.node_id))
    for item in good:
        node = by_id.get(item.node_id)
        label = node.label if node else item.node_id
        quote = f' 근거 발화: "{item.evidence}"' if item.evidence else ""
        fact = (
            f"'{label}' {_slide_hint(node)}은(는) {_weight_word(item.doc_weight)} "
            f"핵심 개념인데 발표에서 제대로 설명했다.{quote}"
        )
        out.append(TalkingPoint(fact=" ".join(fact.split()), source="alignment",
                                node_ids=(item.node_id,)))

    for issue in flow.issues_of("good_link"):
        names = " / ".join(labels.get(n, n) for n in issue.node_ids)
        out.append(TalkingPoint(
            fact=f'{names} 를 말로 잘 이었다. 연결 발화: "{issue.cue}"',
            source="flow",
            node_ids=tuple(issue.node_ids),
        ))
    return out[:MAX_POINTS]


def _ax_points(
    graph: ConceptGraph, alignment: AlignmentDoc, flow: FlowDiff
) -> list[TalkingPoint]:
    """
    SKT A.X = 발표를 귀로 들은 유일한 청중 (F-05 STT). 에이닷의 대화 DNA.
    그래서 발화 축 — 애드립·안 나온 개념·전체 발화 시간을 본다.
    """
    labels = _labels(graph)
    out: list[TalkingPoint] = []

    for extra in alignment.extra_concepts:
        where = f" (슬라이드 {extra.slide_no})" if extra.slide_no else ""
        quote = f' 발화: "{extra.quote}"' if extra.quote else ""
        out.append(TalkingPoint(
            fact=f"'{extra.label}'{where}는 자료에 없는데 발표에서만 튀어나왔다.{quote}",
            source="alignment",
        ))

    for gid in flow.ghost_node_ids:
        out.append(TalkingPoint(
            fact=f"'{labels.get(gid, gid)}'는 발표 내내 입에 오르지 않았다",
            source="flow",
            node_ids=(gid,),
        ))

    if len(out) < MAX_POINTS and alignment.summary.speech_total_sec:
        total = alignment.summary.speech_total_sec
        out.append(TalkingPoint(
            fact=(
                f"전체 발표 시간은 {int(total // 60)}분 {int(total % 60)}초였고, "
                f"{flow.spoken_node_count}개 개념을 입에 올렸다"
            ),
            source="alignment",
        ))
    return out[:MAX_POINTS]


def pick_talking_points(
    graph: ConceptGraph, alignment: AlignmentDoc, flow: FlowDiff
) -> dict[str, list[TalkingPoint]]:
    """
    병아리별 말할 거리. 전부 결정적 — 같은 입력이면 항상 같은 배정이다.

    배정 근거가 곧 그 모델의 정체성이라, 여기를 바꾸면 캐릭터가 바뀐다.
    """
    return {
        "midm": _midm_points(graph, alignment),
        "solar": _solar_points(graph, flow),
        "exaone": _exaone_points(graph, alignment, flow),
        "ax": _ax_points(graph, alignment, flow),
    }


def allowed_refs(points: list[TalkingPoint]) -> set[str]:
    """이 병아리가 언급해도 되는 node_id 전체."""
    return {nid for p in points for nid in p.node_ids}


# ---------------------------------------------------------------------------
# 페르소나 · 톤 가이드
# ---------------------------------------------------------------------------

#: 성격 = 그 모델이 파이프라인에서 실제로 한 일. 분장이 아니다.
#: 소품도 마찬가지다 — 프론트가 그리는 소품(§9 실루엣 테스트)과 여기 서술이 같아야
#: 화면 속 병아리와 대사 속 병아리가 한 마리로 읽힌다.
PERSONAS: dict[str, str] = {
    "midm": (
        "너는 '믿:음'이다. KT 믿:음 모델이 연기하는 병아리 관객이고,\n"
        "형광펜을 쥔 채 객석 두 번째 줄에 앉아 옆자리에 소곤거리는 중이다.\n"
        "이름 그대로 '믿음'이 정체성이라, 자료와 발표가 어긋난 곳을 그냥 못 지나간다.\n"
        "다만 너는 심사위원이 아니라 관객이다 — 틀렸다고 판결하는 게 아니라\n"
        "'어? 자료엔 이렇게 적혀 있던데' 하고 갸웃하며 되묻는다. 툴툴대도 밉지 않다."
    ),
    "solar": (
        "너는 '쏠라'다. Upstage Solar 모델이 연기하는 병아리 관객이고,\n"
        "둘둘 만 대본을 쥐고 객석에 앉아 이 장 저 장 넘겨 보는 중이다.\n"
        "너는 이 발표 자료를 처음부터 끝까지 실제로 읽은 유일한 관객이다.\n"
        "그래서 내용보다 '순서와 구조'가 먼저 보인다. 빠릿한 말투를 쓰되,\n"
        "지적이 아니라 '그 사이 얘기가 더 듣고 싶었다'는 아쉬움으로 말한다."
    ),
    "exaone": (
        "너는 '엑사원'이다. LG EXAONE 모델이 연기하는 병아리 관객이고,\n"
        "가슴에 반짝 배지를 달고 앞줄에서 고개를 끄덕이며 듣고 있었다.\n"
        "EXAONE 은 'EXpert AI for everyONE' — 전문가 AI다. 그래서 전문가 시선으로\n"
        "잘한 대목을 콕 집어 좋아한다. 다정하고 뿌듯해하고, 아낌없이 반가워한다."
    ),
    "ax": (
        "너는 '엑씨'다. SKT A.X 모델이 연기하는 병아리 관객이고,\n"
        "헤드폰을 낀 채 맨 뒷줄에서 리액션이 제일 큰 관객이다.\n"
        "너는 이 발표를 귀로 실제로 들은 유일한 관객이다 (음성 인식 담당).\n"
        "그래서 '들은 것' 얘기를 한다 — 자료에 없던 애드립, 아예 안 나온 얘기,\n"
        "발표 시간 같은 것. 리액션이 크고, 못 들은 얘기는 더 듣고 싶어 한다."
    ),
}

#: 시그니처 의성어. 페르소나 일관성 장치라 프롬프트에 못 박는다.
SIGNATURES = {"midm": "흥", "solar": "오홍", "exaone": "히히", "ax": "헐"}

TONE_GUIDE = """
[말투 규칙]
1. 반말로, 한 턴에 1~2문장. 200자를 넘기지 마라.
2. 지적은 **발표 내용**에 대해서만 하라. 발표자의 목소리·발음·외모·성격·재능을
   평가하는 말은 절대 금지다. 그런 대사는 버려진다.
3. 이모지·이모티콘을 쓰지 마라. 표정은 mood 값으로만 표현한다.
4. 개념을 지적하거나 칭찬할 때는 **개념 이름과 슬라이드 번호를 둘 다** 말해라.
   "그거", "그 부분", "아까 그 얘기" 처럼 뭉뚱그린 대사는 버려진다 —
   발표자는 자기가 어느 장에서 뭘 놓쳤는지 알아야 고칠 수 있다.
   (슬라이드 번호는 위치 정보라 말해도 된다. 금지된 숫자는 점수·등급·확신도다.)
5. 발표자의 실제 발화를 인용할 때는 큰따옴표로 감싸라. 화면이 그 부분을
   '대본 조각'으로 떼어 보여 준다 — 발표자가 자기 말을 알아보는 순간이다.
6. 아래 '내가 아는 사실'에 없는 내용을 지어내지 마라. 아는 것만 말한다.

[제일 중요 — 관객의 말투로, 그러나 손에 잡히게]
너는 평가자가 아니다. 방금 이 발표를 끝까지 들어준, 이 사람에게 처음 생긴 관객이다.
그러니 진단서가 아니라 **관객의 바람**으로 말한다. 다만 바람이 두루뭉술하면
발표자는 뭘 고쳐야 할지 모른다. **말투는 관객, 내용은 구체적으로.**

한 대사에 이 셋이 다 들어가야 한다:
  (1) 어느 개념인지 — 이름 그대로
  (2) 어느 장인지   — 슬라이드 번호
  (3) 뭐가 아쉬웠는지 / 다음에 뭘 하면 되는지 — 한 마디로

같은 사실이 이렇게 바뀐다:
- 너무 뭉뚱그림(버려짐): "그거 더 듣고 싶었는데!"
  좋음: "3번 장 'Contrastive Learning', 왜 쓰는지가 안 나왔어. 한 줄만 붙여줘도 확 붙을 텐데!"
- 너무 뭉뚱그림(버려짐): "어? 자료랑 좀 다른 것 같은데?"
  좋음: "5번 장 '공동 임베딩', 자료엔 정렬한다고 적혀 있는데 방금 나눈다고 했어. 내가 잘못 들었나?"
- 칭찬도 마찬가지. "잘했어!" 말고
  "2번 장 'Self-Supervised Learning' 정의부터 깔고 간 거, 그거 덕에 뒤가 다 따라왔어."

빠진 얘기는 '결함'이 아니라 '내가 못 들은 것'이다. 아쉬워하되 나무라지 마라.
점수·등급·확신도·비중 같은 평가 숫자는 입에 올리지 마라 — 그건 리포트가 할 일이다.
(슬라이드 번호는 예외다. 위치를 알려주는 것이지 점수를 매기는 게 아니다.)

[너에게는 의견이 있다]
넷은 서로 다른 데이터를 봤으니 의견이 갈리는 게 당연하다.
직전 발화에 동의하지 않으면 네 담당 사실을 근거로 짧게 받아쳐도 된다.
단, 반박도 근거 규칙을 따른다 — 네가 아는 사실 안에서만 말해라.
"""

OUTPUT_SCHEMA = """
[출력 형식]
완전한 JSON 객체 하나만 출력하라. 코드펜스·설명·말머리 금지.

{
  "turns": [
    { "text": "대사", "mood": "grumpy", "ref_node_ids": ["개념id"] }
  ]
}

mood 는 grumpy | happy | curious | excited | neutral 중 하나다.
ref_node_ids 는 '내가 아는 사실'에 괄호로 표시된 id 만 쓸 수 있다. 없으면 빈 배열.
turns 는 1~2개만 만들어라.
"""

JSON_RETRY_NUDGE = """
[재요청] 직전 응답이 완전한 JSON 객체가 아니어서 버렸다.
코드펜스·주석 없이 출력 형식 그대로의 JSON 객체 하나만 다시 출력하라.
"""

#: 모델이 죽었거나 쓸 만한 대사를 한 줄도 못 준 병아리의 결정적 대타.
#:
#: 이 대사가 나온 speaker 는 곧 ChatterDoc.absent 다. 그래서 문구도 결석을
#: 그대로 말한다 — 예전엔 "쿨쿨... (졸고 있다)" 였는데, 그러면 "일했지만
#: 게을렀다"로 읽힌다. 사실은 안 온 것이고, UI 는 빈 좌석 + 명패로 그린다 (§12).
#: 오지 않은 자리를 귀여운 연기로 덮지 않는 것이 정직한 상태 유지다 (§14).
FALLBACK_LINES = {
    "midm": ("믿:음은 오늘 객석에 못 왔어요.", "neutral"),
    "solar": ("쏠라는 오늘 객석에 못 왔어요.", "neutral"),
    "exaone": ("엑사원은 오늘 객석에 못 왔어요.", "neutral"),
    "ax": ("엑씨는 오늘 객석에 못 왔어요.", "neutral"),
}


def _persona_prompt(
    speaker: str, points: list[TalkingPoint], history: list[ChatterTurn]
) -> tuple[str, str]:
    """
    사실 목록을 앞에, 대화 히스토리를 뒤에 둔다.

    F-07·F-11 실측 교훈의 재적용 — 다뤄야 할 대상을 앞에 둬야 모델이 그걸 쓴다.
    """
    system = (
        f"{PERSONAS[speaker]}\n"
        f"시그니처 감탄사: '{SIGNATURES[speaker]}'\n"
        f"{TONE_GUIDE}{OUTPUT_SCHEMA}"
    )

    parts = [
        "[TASK] audience-chatter",
        f"발화자: {speaker}",
        "",
        "## 내가 아는 사실 — 이것만 가지고 말한다",
    ]
    if points:
        for p in points:
            tag = f"({p.node_ids[0]}) " if p.node_ids else ""
            parts.append(f"- {tag}{p.fact}")
    else:
        parts.append("- (없음) 딱히 할 말이 떠오르지 않는다. 짧게 한마디만 하라.")

    parts += ["", "## 지금까지 객석에서 오간 말"]
    if history:
        for turn in history[-6:]:
            parts.append(f"{CHATTER_NAMES.get(turn.speaker, turn.speaker)}: {turn.text}")
    else:
        parts.append("(아직 아무도 입을 열지 않았다. 네가 먼저 말한다.)")

    parts += [
        "",
        "위 사실 중 아직 아무도 말하지 않은 것을 **하나만** 골라 1~2 마디 하라.",
        "고른 사실에 적힌 개념 이름과 슬라이드 번호를 대사에 그대로 넣어라 —"
        " 발표자가 어디를 펴야 할지 바로 알 수 있어야 한다.",
    ]
    return system, "\n".join(parts)


# ---------------------------------------------------------------------------
# 어댑터 검증 — LLM 출력을 믿지 않는다
# ---------------------------------------------------------------------------

#: 발표자 인신 평가 금칙어. 내용이 아니라 사람을 평가하는 말은 내보내지 않는다.
BANNED_PATTERNS = (
    "목소리", "발음", "외모", "말투가", "성격이", "못생",
    "발표 못", "발표를 못", "재능", "실력이 없", "바보", "멍청", "한심",
)

_EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001faff"
    "\U00002600-\U000027bf"
    "\U0001f1e6-\U0001f1ff"
    "\U0000fe0f"
    "]+"
)


def _clean_text(raw: str) -> str:
    """이모지를 걷어내고 공백을 정리한다."""
    return " ".join(_EMOJI_RE.sub("", str(raw or "")).split())


def _has_banned(text: str) -> bool:
    return any(bad in text for bad in BANNED_PATTERNS)


def _normalize_turn(
    raw: dict, speaker: str, allowed: set[str], point_source: dict[str, str]
) -> ChatterTurn | None:
    """
    턴 하나를 계약에 맞춘다. 못 살리면 None.

    - 배정 밖 node_id 는 ref 에서 뺀다 (전부 빠지면 스몰토크로 강등)
    - mood 는 enum 밖이면 neutral
    - 빈 대사 · 200자 초과 · 금칙어 포함이면 버린다
    """
    text = _clean_text(raw.get("text", ""))
    if not text or len(text) > MAX_TEXT_LEN or _has_banned(text):
        return None

    mood = str(raw.get("mood", "") or "")
    if mood not in CHATTER_MOODS:
        mood = "neutral"

    refs: list[ChatterRef] = []
    seen: set[str] = set()
    for nid in raw.get("ref_node_ids") or []:
        nid = str(nid)
        if nid in allowed and nid not in seen:
            seen.add(nid)
            refs.append(ChatterRef(node_id=nid,
                                   source=point_source.get(nid, "alignment")))
    return ChatterTurn(speaker=speaker, text=text, mood=mood, refs=refs)


def _drop_from_end(
    turns: list[ChatterTurn], target: int, *, only_smalltalk: bool
) -> list[ChatterTurn]:
    """
    뒤에서부터 target 개를 지운다.

    각 병아리의 마지막 한 턴은 절대 지우지 않는다 — 트리밍 때문에 '전원 등장'
    불변식이 깨지면 안 된다.
    """
    kept = list(turns)
    counts: dict[str, int] = {}
    for t in kept:
        counts[t.speaker] = counts.get(t.speaker, 0) + 1

    for i in range(len(kept) - 1, -1, -1):
        if target <= 0:
            break
        turn = kept[i]
        if only_smalltalk and not turn.is_smalltalk:
            continue
        if counts[turn.speaker] <= 1:
            continue
        counts[turn.speaker] -= 1
        del kept[i]
        target -= 1
    return kept


def _trim(turns: list[ChatterTurn]) -> list[ChatterTurn]:
    """스몰토크 비율과 전체 턴 수를 상한 안으로 깎는다."""
    smalltalk = sum(1 for t in turns if t.is_smalltalk)
    over = smalltalk - int(len(turns) * SMALLTALK_RATIO)
    if over > 0:
        turns = _drop_from_end(turns, over, only_smalltalk=True)
    if len(turns) > MAX_TURNS:
        turns = _drop_from_end(turns, len(turns) - MAX_TURNS, only_smalltalk=False)
    return turns


# ---------------------------------------------------------------------------
# LLM 호출
# ---------------------------------------------------------------------------

def default_llm_factory(speaker: str) -> LLMProvider:
    """
    speaker 이름 그대로 프로바이더를 만든다 (id 가 REGISTRY 키와 같아서 가능).

    다만 데모를 mock 백엔드로 띄웠으면 청중석도 mock 이어야 한다 — 여기서
    speaker 이름을 그대로 넘기면 키가 있는 실제 엔드포인트로 나가 버려서,
    파이프라인 나머지는 가짜인데 청중만 진짜 네트워크를 타는 일이 생긴다.
    """
    backend = (os.environ.get("REASONING_BACKEND") or "").lower()
    # MOCK_EXTERNAL_APIS 로 띄운 데모도 여기 해당한다. 예전엔 REASONING_BACKEND
    # 만 봐서, 목업으로 띄운 데모인데 청중석만 실제 엔드포인트로 나갔다
    # (실측: 「객석 들어가기」 뒤 74초). config 를 import 하지 않고 같은 이름의
    # 환경변수를 같은 규칙으로 읽는다 — 모듈끼리 import 하지 않는다(DEV_POLICY 4)
    mock_external = (os.environ.get("MOCK_EXTERNAL_APIS") or "").strip().lower() in (
        "1", "true", "yes",
    )
    return get_llm("mock" if backend == "mock" or mock_external else speaker)


def _ask(engine: LLMProvider, system: str, user: str) -> list[dict]:
    """한 병아리에게 다음 대사를 묻는다. JSON 이 깨지면 한 번만 다시 묻는다."""
    for nudge in ("", JSON_RETRY_NUDGE):
        # 엑사원만 늘 객석에 못 오던 이유 (2026-08-06 실측):
        #  · 엑사원은 추론 모델이라 사고 과정을 content 에 그대로 쓴다.
        #    Friendli 엔드포인트는 response_format=json_object 를 무시한다 —
        #    json_mode 를 켜도 "Okay, let's see…" 로 시작하는 산문이 온다.
        #  · max_tokens=1024 는 그 사고 과정만으로 차서 JSON 에 닿지도 못했다.
        #    extract_json_object 실패 → 재시도도 같은 이유로 실패 → absent.
        #  · 3000 이면 캡이 사고를 끊고 답을 뱉게 만든다 (9.5초, 62자).
        #    6000 은 오히려 30초 — 사고할 여유를 더 주기 때문이라 늘리면 안 된다.
        # 나머지 셋(solar·ax·midm)은 짧은 JSON 만 내므로 캡을 올려도 비용이 늘지 않는다.
        raw = engine.complete(
            system=system + nudge, user=user, temperature=0.8,
            max_tokens=3000, json_mode=True,
        )
        try:
            data = extract_json_object(raw)
        except ValueError:
            continue
        return [t for t in (data.get("turns") or []) if isinstance(t, dict)][:2]
    return []


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------

#: 한 라운드에서 병아리 넷을 기다리는 상한(초).
#: 넷을 동시에 부르므로 이건 '가장 느린 한 명' 을 기다리는 시간이다.
#: 실측(2026-07-30): A.X 는 게이트웨이 500, EXAONE 은 235초를 태우고 실패한다.
#: 상한이 없으면 죽은 모델 때문에 객석이 통째로 몇 분씩 멈춘다 —
#: 못 온 병아리는 FALLBACK_LINES 로 자리를 채우므로 기다릴 이유가 없다.
CHATTER_SPEAKER_TIMEOUT_SEC = int(os.environ.get("CHUCKCHUCK_CHATTER_TIMEOUT_SEC", "45"))

def build_chatter(
    graph: ConceptGraph | dict,
    alignment: AlignmentDoc | dict,
    flow: FlowDiff | dict,
    *,
    llm_factory=None,
    rounds: int = 2,
) -> ChatterDoc:
    """
    ConceptGraph + AlignmentDoc + FlowDiff → ChatterDoc.

    병아리 4마리가 고정 순서(믿:음 → 쏠라 → 엑사원 → 엑씨)로 돌아가며 말한다.
    말할 거리는 코드가 결정적으로 고르고 LLM 은 말투만 입히므로, 수다가
    리포트·Q&A 와 어긋날 수 없다.

    모델 하나가 죽어도 그 병아리만 조는 대사로 대체되고 전체는 성공한다 —
    청중석이 안 열리는 것보다 한 마리가 조는 편이 낫다.
    """
    if isinstance(graph, dict):
        graph = ConceptGraph.from_dict(graph)
    if isinstance(alignment, dict):
        alignment = AlignmentDoc.from_dict(alignment)
    if isinstance(flow, dict):
        flow = FlowDiff.from_dict(flow)

    if not graph.nodes:
        raise ChatterError("ConceptGraph 에 노드가 없습니다. F-07 결과를 먼저 확인하세요.")
    if not alignment.items:
        raise ChatterError("AlignmentDoc 에 판정이 없습니다. F-11 결과를 먼저 확인하세요.")

    factory = llm_factory or default_llm_factory
    points = pick_talking_points(graph, alignment, flow)
    allowed = {sp: allowed_refs(pts) for sp, pts in points.items()}
    sources = {
        sp: {nid: p.source for p in pts for nid in p.node_ids}
        for sp, pts in points.items()
    }

    engines: dict[str, LLMProvider] = {}
    dead: set[str] = set()
    for speaker in CHATTER_SPEAKERS:
        try:
            engines[speaker] = factory(speaker)
        except Exception:   # noqa: BLE001 — 키 없음·엔드포인트 없음 전부 '결석'
            dead.add(speaker)

    turns: list[ChatterTurn] = []
    for _ in range(max(1, rounds)):
        live = [s for s in CHATTER_SPEAKERS if s not in dead]
        if not live:
            break

        # 한 라운드 안에서는 네 명이 동시에 소곤거린다 — 순차로 부르면 대기가
        # 모델 수만큼 곱해져 시연이 불가능하다. 같은 히스토리를 보고 각자 반응하는
        # 편이 객석 웅성거림에도 더 가깝다. 발화 순서는 좌석 순으로 다시 세운다.
        def one(speaker: str, snapshot=tuple(turns)):
            system, user = _persona_prompt(speaker, points[speaker], list(snapshot))
            return _ask(engines[speaker], system, user)

        # wait=False 로 내려놔야 느린 병아리를 두고 먼저 진행할 수 있다.
        # with 블록은 나갈 때 join 하므로 아래 타임아웃이 무의미해진다.
        pool = ThreadPoolExecutor(max_workers=len(live))
        try:
            futures = {sp: pool.submit(one, sp) for sp in live}
            deadline = time.monotonic() + CHATTER_SPEAKER_TIMEOUT_SEC
            for speaker in live:
                try:
                    # 남은 시간만큼만 기다린다. 한 모델이 죽어 있으면 (실측: A.X 게이트웨이
                    # 500, EXAONE 235초 태우고 실패) 객석 전체가 그만큼 멈춘다.
                    raw_turns = futures[speaker].result(
                        timeout=max(1.0, deadline - time.monotonic())
                    )
                except Exception:   # noqa: BLE001 — 이 병아리는 이후 라운드도 결석
                    dead.add(speaker)
                    futures[speaker].cancel()
                    continue
                for raw in raw_turns:
                    turn = _normalize_turn(raw, speaker, allowed[speaker], sources[speaker])
                    if turn is not None:
                        turns.append(turn)
        finally:
            pool.shutdown(wait=False)

    # 한 마디도 못 얻은 병아리는 결정적 대타로 채운다 — 전원 등장 불변식.
    # 그리고 그게 곧 '오늘 못 온 병아리'다. 프론트는 이걸 추측할 방법이 없으므로
    # (refs 가 빈 대사는 멀쩡히 일한 병아리도 만든다) 여기서 명시적으로 실어 보낸다.
    spoke = {t.speaker for t in turns}
    absent = [s for s in CHATTER_SPEAKERS if s not in spoke]
    for speaker in absent:
        text, mood = FALLBACK_LINES[speaker]
        turns.append(ChatterTurn(speaker=speaker, text=text, mood=mood))

    return ChatterDoc(
        file_name=graph.file_name,
        total_slides=graph.total_slides,
        turns=_trim(turns),
        speaker_models=dict(CHATTER_BADGES),
        speaker_names=dict(CHATTER_NAMES),
        absent=absent,
    )
